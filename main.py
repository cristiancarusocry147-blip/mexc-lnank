import os
import time
import requests
import logging
from datetime import datetime
from collections import deque
from rich.console import Console
from rich.table import Table
from rich import box
from rich.live import Live
from rich.panel import Panel
from rich.align import Align
from rich.plot import Plot

# === CONFIG ===
API_KEY_MEXC = os.getenv("API_KEY_MEXC", "dummy")
SECRET_KEY_MEXC = os.getenv("SECRET_KEY_MEXC", "dummy")
API_KEY_LBANK = os.getenv("API_KEY_LBANK", "dummy")
SECRET_KEY_LBANK = os.getenv("SECRET_KEY_LBANK", "dummy")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

console = Console()

# === TELEGRAM ===
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram non configurato")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        logging.error(f"Errore Telegram: {e}")

# === API PRICE GETTERS ===
def get_mexc_pairs():
    try:
        r = requests.get("https://api.mexc.com/api/v3/exchangeInfo", timeout=10)
        data = r.json()
        return [s["symbol"] for s in data["symbols"] if s["status"] == "TRADING"]
    except Exception:
        return []

def get_lbank_pairs():
    try:
        r = requests.get("https://api.lbkex.com/v2/currencyPairs.do", timeout=10)
        data = r.json()
        return [s.replace("_", "").upper() for s in data["data"]]
    except Exception:
        return []

def get_price_mexc(symbol):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=10)
        return float(r.json()["price"])
    except Exception:
        return None

def get_price_lbank(symbol):
    try:
        s = symbol.lower()
        r = requests.get(f"https://api.lbkex.com/v2/ticker.do?symbol={s}", timeout=10)
        d = r.json()
        return float(d["ticker"]["latest"])
    except Exception:
        return None

# === DASHBOARD ===
def create_dashboard(pairs_data, spread_history):
    table = Table(
        title=f"[bold cyan]Futures Arbitrage Dashboard[/bold cyan] — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
        style="bright_white on black",
    )
    table.add_column("Coppia", justify="center", style="cyan")
    table.add_column("MEXC", justify="right", style="yellow")
    table.add_column("LBank", justify="right", style="yellow")
    table.add_column("Spread %", justify="right", style="magenta")
    table.add_column("Azione", justify="center", style="bold green")

    for sym, pm, pl, spread, action in pairs_data:
        color = "green" if spread > 0 else "red"
        table.add_row(
            sym, f"{pm:.4f}", f"{pl:.4f}", f"[{color}]{spread:.2f}%[/{color}]", action
        )

    # Mini chart spread per le 10 coppie principali
    plot = Plot(width=70, height=15)
    for sym, history in spread_history.items():
        plot.add_series(sym, list(history))
    chart_panel = Panel(Align.center(plot, vertical="middle"), title="📈 Top 10 Spread Trend")

    layout = Table.grid(expand=True)
    layout.add_row(table)
    layout.add_row(chart_panel)

    return layout

# === MAIN LOOP ===
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.info("🚀 Avvio bot arbitraggio multi-coppia")
    send_telegram("🤖 Bot arbitraggio avviato con successo!")

    spread_history = {}

    with Live(console=console, refresh_per_second=0.5, screen=True):
        while True:
            try:
                mexc_pairs = get_mexc_pairs()
                lbank_pairs = get_lbank_pairs()
                common = sorted(list(set(mexc_pairs) & set(lbank_pairs)))

                pairs_data = []
                logging.info(f"Trovate {len(common)} coppie comuni. Analisi prime 200...")

                for symbol in common[:200]:
                    p_mexc = get_price_mexc(symbol)
                    p_lbank = get_price_lbank(symbol.lower())
                    if not p_mexc or not p_lbank:
                        continue

                    spread = ((p_lbank - p_mexc) / p_mexc) * 100
                    action = ""
                    if abs(spread) >= 3:
                        if p_mexc < p_lbank:
                            action = "💹 COMPRA su MEXC / VENDI su LBank"
                        else:
                            action = "💹 COMPRA su LBank / VENDI su MEXC"
                        msg = f"🚨 {symbol}: spread {spread:.2f}% → {action}"
                        logging.info(msg)
                        send_telegram(msg)

                    pairs_data.append((symbol, p_mexc, p_lbank, spread, action))

                    # Aggiorna storico spread per grafico (solo prime 10 coppie)
                    if symbol not in spread_history and len(spread_history) < 10:
                        spread_history[symbol] = deque(maxlen=10)
                    if symbol in spread_history:
                        spread_history[symbol].append(spread)

                dashboard = create_dashboard(pairs_data, spread_history)
                console.clear()
                console.print(dashboard)

                logging.info("✅ Ciclo completato. Attendo 10 minuti...")
                time.sleep(600)

            except Exception as e:
                logging.error(f"Errore nel loop: {e}")
                send_telegram(f"⚠️ Errore nel bot: {e}")
                time.sleep(60)

if __name__ == "__main__":
    main()

