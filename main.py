import os
import time
import json
import logging
import requests
import random
from datetime import datetime
from threading import Thread   # ✅ Import corretto
from flask import Flask
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# === FLASK SETUP ===
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Arbitrage bot attivo su Render!"

# === COLORI TERMINALE ===
console = Console()

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# === CONFIG ===
CONFIG_PATH = "config.json"
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        config = json.load(f)
else:
    config = {}

API_KEY_MEXC = config.get("MEXC", {}).get("API_KEY", "")
SECRET_KEY_MEXC = config.get("MEXC", {}).get("SECRET_KEY", "")
API_KEY_LBANK = config.get("LBANK", {}).get("API_KEY", "")
SECRET_KEY_LBANK = config.get("LBANK", {}).get("SECRET_KEY", "")
TELEGRAM_TOKEN = config.get("TELEGRAM", {}).get("TOKEN", "")
CHAT_ID = config.get("TELEGRAM", {}).get("CHAT_ID", "")

# === TELEGRAM ===
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram non configurato")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        logging.error(f"Errore Telegram: {e}")

# === MOCK PREZZI ===
def get_random_price():
    return round(100 + random.uniform(-5, 5), 2)

def get_common_pairs():
    # Simuliamo 200 coppie comuni
    return [f"COIN{i}/USDT" for i in range(1, 201)]

# === DASHBOARD ===
def print_dashboard(pairs_data):
    console.clear()
    console.rule(f"[bold cyan]📊 Futures Arbitrage Dashboard — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    table = Table(show_header=True, header_style="bold magenta", style="on black")
    table.add_column("Coppia", justify="center")
    table.add_column("MEXC", justify="center")
    table.add_column("LBank", justify="center")
    table.add_column("Spread %", justify="center")
    table.add_column("Azione", justify="center")

    for pair, mexc, lbank, spread, action in pairs_data[:10]:
        color = "green" if spread > 0 else "red"
        table.add_row(pair, f"{mexc:.2f}", f"{lbank:.2f}", f"[{color}]{spread:.2f}%[/{color}]", action)

    console.print(table)
    console.print(Panel.fit("🕒 Aggiornamento automatico ogni 10 minuti", style="bold cyan"))

# === LOGICA ARBITRAGGIO ===
def arbitrage_loop():
    logging.info("🚀 Avvio bot arbitraggio multi-coppia")
    send_telegram_message("🚀 Bot arbitraggio multi-coppia avviato!")

    pairs = get_common_pairs()
    logging.info(f"Trovate {len(pairs)} coppie comuni. Analisi prime 200...")

    while True:
        pairs_data = []
        for pair in pairs:
            price_mexc = get_random_price()
            price_lbank = get_random_price()
            spread = ((price_lbank - price_mexc) / price_mexc) * 100

            if spread >= 3:
                action = "🟢 Compra su MEXC / Vendi su LBank"
                send_telegram_message(f"🚨 {pair}: Spread +{spread:.2f}% → {action}")
            elif spread <= -3:
                action = "🔴 Vendi su MEXC / Compra su LBank"
                send_telegram_message(f"🚨 {pair}: Spread {spread:.2f}% → {action}")
            else:
                action = "💤 Nessuna azione"

            pairs_data.append((pair, price_mexc, price_lbank, spread, action))

        # Ordina per spread più alto
        pairs_data = sorted(pairs_data, key=lambda x: abs(x[3]), reverse=True)
        print_dashboard(pairs_data)
        logging.info("✅ Ciclo completato. Attendo 10 minuti...")
        time.sleep(600)  # 10 minuti

# === AVVIO ===
def start_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    Thread(target=arbitrage_loop, daemon=True).start()
    start_flask()





