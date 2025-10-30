import os
import time
import json
import logging
import requests
from datetime import datetime
from collections import deque
from rich.console import Console
from rich.table import Table
from rich import box
from rich.live import Live
from rich.panel import Panel
from rich.align import Align

# === CONFIG ===
console = Console()

# Legge da config.json (se presente), altrimenti da variabili d'ambiente
config_path = "config.json"
if os.path.exists(config_path):
    with open(config_path) as f:
        config = json.load(f)
    API_KEY_MEXC = config["MEXC"]["API_KEY"]
    SECRET_KEY_MEXC = config["MEXC"]["SECRET_KEY"]
    API_KEY_LBANK = config["LBANK"]["API_KEY"]
    SECRET_KEY_LBANK = config["LBANK"]["SECRET_KEY"]
    TELEGRAM_TOKEN = config["TELEGRAM"]["8471152392:AAHHYjhIcaGV1DVherO5sVYKO8OZubgY4r0"]
    CHAT_ID = config["TELEGRAM"]["721323324"]
    SPREAD_THRESHOLD = config["SETTINGS"]["SPREAD_ALERT_THRESHOLD"]
    CHECK_INTERVAL = config["SETTINGS"]["CHECK_INTERVAL_MINUTES"] * 60
    MAX_PAIRS = config["SETTINGS"]["MAX_PAIRS"]
else:
    API_KEY_MEXC = os.getenv("API_KEY_MEXC")
    SECRET_KEY_MEXC = os.getenv("SECRET_KEY_MEXC")
    API_KEY_LBANK = os.getenv("API_KEY_LBANK")
    SECRET_KEY_LBANK = os.getenv("SECRET_KEY_LBANK")
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHAT_ID = os.getenv("CHAT_ID")
    SPREAD_THRESHOLD = 3
    CHECK_INTERVAL = 600
    MAX_PAIRS = 200

# === TELEGRAM ===
def send_telegram(msg):
    """Invia un messaggio Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram non configurato")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        logging.error(f"Errore Telegram: {e}")

# === API PRICE GETTERS ===
def normalize_symbol(sym: str) -> str:
    """Rimuove underscore, trattini e forza maiuscolo"""
    return sym.replace("_", "").replace("-", "").upper()

def get_mexc_pairs():
    try:
        r = requests.get("https://api.mexc.com/api/v3/exchangeInfo", timeout=10)
        data = r.json()
        return [normalize_symbol(s["symbol"]) for s in data["symbols"] if s["status"] == "TRADING"]
    except Exception as e:
        logging.error(f"Errore MEXC pairs: {e}")
        return []

def get_lbank_pairs():
    try:
        r = requests.get("https://api.lbkex.com/v2/currencyPairs.do", timeout=10)
        data = r.json()
        return [normalize_symbol(s) for s in data["data"]]
    except Exception as e:
        logging.error(f"Errore LBank pairs: {e}")
        return []

def get_price_mexc(symbol):
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}", timeout=10)
        return float(r.json()["price"])
    except Exception:
        return None

def get_price_lbank(symbol):
    try:
        r = requests.get(f"https://api.lbkex.com/v2/ticker.do?symbol={symbol.lower()}", timeout=10)
        d = r.json()
        return float(d["ticker"]["latest"])
    except Exception:
        return None

# === DASHBOARD ===
def draw_chart(spread_history):
    """Crea mini-grafici a barre colorate ASCII per i 10 spread principali"""
    chart_lines = []
    for sym, values in spread_history.items():
        bars = "".join("█" if v > 0 else "░" for v in values)
        chart_lines.append(f"[cyan]{sym:<10}[/cyan] {bars}  {values[-1]:+.2f}%")
    if not chart_lines:
        return "Nessun dato storico ancora."
    return "\n".join(chart_lines)

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
        table.add_row(sym, f"{pm:.4f}", f"{pl:.4f}", f"[{color}]{spread:.2f}%[/{color}]", action)

    chart_text = draw_chart(spread_history)
    chart_panel = Panel(Align.left(chart_text), title="📈 Top 10 Spread Trend", border_style="cyan")

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

                if not mexc_pairs or not lbank_pairs:
                    logging.warning("⚠️ Nessuna coppia trovata dalle API. Riprovo tra 10 min...")
                    time.sleep(CHECK_INTERVAL)
                    continue

                common = sorted(list(set(mexc_pairs) & set(lbank_pairs)))
                pairs_data = []

                logging.info(f"Trovate {len(common)} coppie comuni. Analisi prime {MAX_PAIRS}...")

                for symbol in common[:MAX_PAIRS]:
                    p_mexc = get_price_mexc(symbol)
                    p_lbank = get_price_lbank(symbol)
                    if not p_mexc or not p_lbank:
                        continue

                    spread = ((p_lbank - p_mexc) / p_mexc) * 100
                    action = ""
                    if abs(spread) >= SPREAD_THRESHOLD:
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
                        spread_history[symbol] = deque(maxlen=20)
                    if symbol in spread_history:
                        spread_history[symbol].append(spread)

                dashboard = create_dashboard(pairs_data, spread_history)
                console.clear()
                console.print(dashboard)

                logging.info("✅ Ciclo completato. Attendo prossimo aggiornamento...")
                time.sleep(CHECK_INTERVAL)

            except Exception as e:
                logging.error(f"Errore nel loop: {e}")
                send_telegram(f"⚠️ Errore nel bot: {e}")
                time.sleep(60)

# === AVVIO ===
def start_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    Thread(target=arbitrage_loop, daemon=True).start()
    start_flask()



