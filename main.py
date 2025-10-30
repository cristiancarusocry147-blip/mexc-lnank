import os
import time
import json
import logging
import asyncio
from datetime import datetime, timedelta
from threading import Thread, Lock

import requests
from flask import Flask
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# ccxt async
import ccxt.async_support as ccxt

# ========= CONFIG =========
CONFIG_PATH = "config.json"
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        config = json.load(f)
else:
    config = {}

TELEGRAM_TOKEN = config.get("TELEGRAM", {}).get("TOKEN") or os.getenv("TELEGRAM_TOKEN")
CHAT_ID = config.get("TELEGRAM", {}).get("CHAT_ID") or os.getenv("CHAT_ID")

CHECK_INTERVAL = int(config.get("SETTINGS", {}).get("CHECK_INTERVAL_MINUTES", 10)) * 60
MAX_PAIRS = int(config.get("SETTINGS", {}).get("MAX_PAIRS", 200))
SPREAD_THRESHOLD = float(config.get("SETTINGS", {}).get("SPREAD_ALERT_THRESHOLD", 3.0))

# ========= LOGGING & UI =========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
console = Console()
app = Flask(__name__)

# ========= SHARED STATE =========
pairs_data = []            # list of dicts: {base, mexc_sym, lbank_sym, mexc_price, lbank_price, spread, action}
last_update = None
last_pairs_update = None
pairs_lock = Lock()
last_alert_time = {}       # cooldown per pair (seconds since epoch)

# ========= TELEGRAM (sync) =========
def send_telegram_message_sync(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram not configured")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception as e:
        logging.error(f"Errore Telegram send: {e}")

async def send_telegram_message(text):
    # helper wrapper so async code can call it
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, send_telegram_message_sync, text)

# ========= HELPERS =========
def extract_base(sym: str) -> str:
    # Accept formats: "BTC/USDT", "BTC_USDT", "BTCUSDT"
    s = sym.replace("-", "_").replace("/", "_").upper()
    if "_" in s:
        base = s.split("_")[0]
    else:
        # remove USDT suffix if present
        base = s[:-4] if s.endswith("USDT") else s
    return base

# ========= CCXT ASYNC FETCHERS =========
async def fetch_mexc_symbols(retries: int = 2):
    for attempt in range(1, retries + 2):
        mexc = None
        try:
            mexc = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "swap"}})
            await mexc.load_markets()
            symbols = []
            for m in mexc.markets.values():
                sym = m.get("symbol")  # e.g. "BTC/USDT"
                if not sym:
                    continue
                sym_upper = sym.upper()
                is_usdt = "USDT" in sym_upper
                mtype = m.get("type")
                is_swap = (mtype == "swap") or (m.get("contract") is True) or (m.get("future") is True)
                if is_usdt and (is_swap or mtype in (None, "swap", "future")):
                    # keep standard ccxt symbol (with /)
                    symbols.append(sym_upper.replace("_", "/").replace(" ", ""))
            await mexc.close()
            symbols = sorted(list(set(symbols)))
            logging.info(f"Trovate {len(symbols)} coppie MEXC (futures/swap).")
            return symbols
        except Exception as e:
            logging.warning(f"fetch_mexc_symbols attempt {attempt} failed: {e}")
            if mexc:
                try:
                    await mexc.close()
                except Exception:
                    pass
            await asyncio.sleep(2)
    logging.error("fetch_mexc_symbols exhausted retries")
    return []

async def fetch_lbank_symbols(retries: int = 2):
    # Try ccxt first (if available), otherwise fallback to REST
    for attempt in range(1, retries + 2):
        lbank = None
        try:
            # ccxt exchange id for LBank is "lbank" on many versions; use try/except
            try:
                lbank = ccxt.lbank({"enableRateLimit": True, "options": {"defaultType": "swap"}})
                await lbank.load_markets()
                symbols = []
                for m in lbank.markets.values():
                    sym = m.get("symbol")
                    if not sym:
                        continue
                    sym_upper = sym.upper()
                    is_usdt = "USDT" in sym_upper
                    mtype = m.get("type")
                    is_swap = (mtype == "swap") or (m.get("contract") is True) or (m.get("future") is True)
                    if is_usdt and (is_swap or mtype in (None, "swap", "future")):
                        symbols.append(sym_upper.replace("_", "/"))
                await lbank.close()
                symbols = sorted(list(set(symbols)))
                logging.info(f"Trovate {len(symbols)} coppie LBank (futures/swap) via ccxt.")
                return symbols
            except Exception as ccxt_err:
                # fallback to REST endpoint (may fail on some networks)
                logging.debug(f"ccxt.lbank failed: {ccxt_err}; trying REST fallback")
                url = "https://api.lbkex.net/v2/futures/contracts.do"
                resp = await asyncio.get_event_loop().run_in_executor(None, requests.get, url, )
                if resp.status_code != 200:
                    raise ValueError(f"LBank REST returned {resp.status_code}")
                data = resp.json()
                # `data` expected to have list of contracts; adapt if different
                symbols = []
                for item in data.get("data", []):
                    sym = item.get("symbol") or item.get("symbolName") or ""
                    if not sym:
                        continue
                    sym_upper = sym.upper().replace("_", "/")
                    if "USDT" in sym_upper:
                        symbols.append(sym_upper)
                symbols = sorted(list(set(symbols)))
                logging.info(f"Trovate {len(symbols)} coppie LBank (futures/swap) via REST fallback.")
                return symbols
        except Exception as e:
            logging.warning(f"fetch_lbank_symbols attempt {attempt} failed: {e}")
            if lbank:
                try:
                    await lbank.close()
                except Exception:
                    pass
            await asyncio.sleep(2)
    logging.error("fetch_lbank_symbols exhausted retries")
    return []

async def build_pairs():
    """Return list of dicts: { base, mexc_sym, lbank_sym } up to MAX_PAIRS"""
    try:
        mexc_symbols, lbank_symbols = await asyncio.gather(fetch_mexc_symbols(), fetch_lbank_symbols())
        mexc_map = {extract_base(s): s for s in mexc_symbols}
        lbank_map = {extract_base(s): s for s in lbank_symbols}
        commons = []
        for base, m_sym in mexc_map.items():
            l_sym = lbank_map.get(base)
            if l_sym:
                commons.append({"base": base, "mexc": m_sym, "lbank": l_sym})
            if len(commons) >= MAX_PAIRS:
                break
        logging.info(f"✅ Trovate {len(commons)} coppie comuni (MEXC/LBank).")
        if len(commons) == 0:
            logging.warning("Nessuna coppia comune trovata.")
        return commons
    except Exception as e:
        logging.error(f"Errore build_pairs: {e}")
        return []

# ========= PRICE FETCHERS (async via ccxt) =========
async def fetch_price(ccxt_exch, symbol):
    try:
        ticker = await ccxt_exch.fetch_ticker(symbol)
        # prefer 'last' if present
        price = ticker.get('last') or ticker.get('close') or ticker.get('info', {}).get('lastPrice') or None
        return float(price) if price is not None else None
    except Exception as e:
        return None

# ========= ASYNC MAIN WORKER =========
async def async_worker_loop():
    global pairs_data, last_update, last_pairs_update

    # create persistent ccxt clients (reuse for performance)
    mexc_client = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    # lbank might be not supported by ccxt on some installs; handle with try
    try:
        lbank_client = ccxt.lbank({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    except Exception:
        lbank_client = None

    # initial notification
    await send_telegram_message("🤖 Bot futures perpetual MEXC-LBank avviato!")

    while True:
        try:
            # build pairs (gets exchange symbol formats)
            commons = await build_pairs()
            last_pairs_update = datetime.utcnow()

            temp_results = []
            # for each pair, fetch prices (concurrency)
            sem = asyncio.Semaphore(10)  # limit concurrent requests
            async def fetch_pair(pair_entry):
                async with sem:
                    m_sym = pair_entry["mexc"]
                    l_sym = pair_entry["lbank"]
                    # fetch prices (use clients)
                    px_m = await fetch_price(mexc_client, m_sym) if mexc_client else None
                    if lbank_client:
                        px_l = await fetch_price(lbank_client, l_sym)
                    else:
                        # fallback to REST for LBank if needed
                        try:
                            r = await asyncio.get_event_loop().run_in_executor(None, requests.get,
                                                                               f"https://api.lbkex.net/v2/futures/ticker.do?symbol={l_sym.replace('/','_')}")
                            if r.status_code == 200:
                                j = r.json()
                                px_l = float(j.get("data", {}).get("lastPrice"))
                            else:
                                px_l = None
                        except Exception:
                            px_l = None
                    return (pair_entry["base"], m_sym, l_sym, px_m, px_l)

            tasks = [fetch_pair(pe) for pe in commons]
            results = await asyncio.gather(*tasks)

            now = datetime.utcnow()
            for base, m_sym, l_sym, price_m, price_l in results:
                if price_m is None or price_l is None:
                    continue
                spread = ((price_l - price_m) / price_m) * 100
                action = "—"
                # anti-spam cooldown: 60 sec per pair
                key = f"{m_sym}|{l_sym}"
                last_time = last_alert_time.get(key, 0)
                if abs(spread) >= SPREAD_THRESHOLD:
                    if time.time() - last_time > 60:  # 1 minute cooldown
                        if spread > 0:
                            action = "📈 Vendi su LBank / Compra su MEXC"
                        else:
                            action = "📉 Vendi su MEXC / Compra su LBank"
                        # send telegram (async wrapper)
                        await send_telegram_message(f"⚡ {base}: {spread:.2f}% — {action}")
                        last_alert_time[key] = time.time()

                temp_results.append({
                    "base": base,
                    "mexc_sym": m_sym,
                    "lbank_sym": l_sym,
                    "mexc": price_m,
                    "lbank": price_l,
                    "spread": spread,
                    "action": action
                })

            # update shared state
            with pairs_lock:
                pairs_data = sorted(temp_results, key=lambda x: abs(x["spread"]), reverse=True)
                last_update = now

            # CLI dashboard update
            render_cli_dashboard()

            logging.info("Ciclo completato. Attesa prossimo aggiornamento...")
            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            logging.error(f"Errore main worker loop: {e}")
            await asyncio.sleep(10)

# ========= CLI (rich) =========
def render_cli_dashboard():
    with pairs_lock:
        top = pairs_data[:10]
    console.clear()
    console.rule(f"[bold cyan]PERPETUAL FUTURES ARBITRAGE — {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Pair")
    table.add_column("MEXC", justify="right")
    table.add_column("LBank", justify="right")
    table.add_column("Spread %", justify="right")
    table.add_column("Action", justify="center")
    for p in top:
        color = "green" if p["spread"] > 0 else "red"
        table.add_row(p["base"], f"{p['mexc']:.3f}", f"{p['lbank']:.3f}", f"[{color}]{p['spread']:.2f}[/{color}]", p["action"])
    console.print(Panel(table, title="[bold magenta]PERPETUAL FUTURES ARBITRAGE DASHBOARD[/bold magenta]"))
    console.print(f"[bold cyan]Pairs updated:[/bold cyan] {last_pairs_update.strftime('%Y-%m-%d %H:%M:%S') if last_pairs_update else 'N/A'}")
    console.print(f"[bold cyan]Last prices updated:[/bold cyan] {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'N/A'}")

# ========= FLASK DASHBOARD =========
@app.route("/")
def web_home():
    with pairs_lock:
        rows = pairs_data[:50]
        lu = last_update.strftime("%Y-%m-%d %H:%M:%S") if last_update else "N/A"
        lp = last_pairs_update.strftime("%Y-%m-%d %H:%M:%S") if last_pairs_update else "N/A"

    rows_html = "".join(
        f"<tr><td>{r['base']}</td><td>{r['mexc_sym']}</td><td>{r['lbank_sym']}</td><td class='{'green' if r['spread']>0 else 'red'}'>{r['spread']:.2f}%</td><td>{r['action']}</td></tr>"
        for r in rows
    )

    html = f"""
    <html>
    <head>
      <meta http-equiv="refresh" content="30">
      <style>
        body{{background:#0b1220;color:#c9d1d9;font-family:Consolas,monospace;padding:18px}}
        table{{width:100%;border-collapse:collapse}}
        th,td{{padding:8px;text-align:center;border-bottom:1px solid #26313a}}
        th{{color:#58a6ff}}
        .green{{color:#3fb950}}
        .red{{color:#f85149}}
        .info{{color:#8b949e}}
      </style>
    </head>
    <body>
      <h1>📊 Perpetual Futures Arbitrage (MEXC ⇄ LBank)</h1>
      <p class='info'>Last pairs refresh: {lp} — Last prices: {lu}</p>
      <table>
        <tr><th>Base</th><th>MEXC sym</th><th>LBank sym</th><th>Spread %</th><th>Action</th></tr>
        {rows_html}
      </table>
      <p class='info'>Auto-refresh every 30s</p>
    </body>
    </html>
    """
    return html

# ========= STARTUP =========
def start_async_loop_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(async_worker_loop())

if __name__ == "__main__":
    # start async worker in separate daemon thread
    t = Thread(target=start_async_loop_in_thread, daemon=True)
    t.start()

    # start Flask in main thread (Render expects this)
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)












