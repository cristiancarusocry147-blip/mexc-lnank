import os
import time
import json
import logging
import requests
import random
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, render_template_string
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# === FLASK SETUP ===
app = Flask(__name__)

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
last_alert_time = {}

def send_telegram_message(message, pair):
    """Invia messaggio solo se non già inviato di recente"""
    now = datetime.now()
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("Telegram non configurato")
        return
    if pair in last_alert_time and now - last_alert_time[pair] < timedelta(minutes=30):
        return  # evita spam
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
        last_alert_time[pair] = now
        logging.info(f"📨 Notifica Telegram inviata per {pair}")
    except Exception as e:
        logging.error(f"Errore Telegram: {e}")

# === MOCK DATI ===
def get_random_price():
    return round(100 + random.uniform(-5, 5), 2)

def get_common_pairs():
    return [f"COIN{i}/USDT" for i in range(1, 201)]

# === STATO GLOBALE ===
pairs_data = []
last_update = None

# === DASHBOARD CLI ===
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
    global pairs_data, last_update
    logging.info("🚀 Avvio bot arbitraggio multi-coppia")
    pairs = get_common_pairs()

    while True:
        temp_data = []
        for pair in pairs:
            price_mexc = get_random_price()
            price_lbank = get_random_price()
            spread = ((price_lbank - price_mexc) / price_mexc) * 100

            if spread >= 3:
                action = "🟢 Compra su MEXC / Vendi su LBank"
                send_telegram_message(f"🚨 {pair}: Spread +{spread:.2f}% → {action}", pair)
            elif spread <= -3:
                action = "🔴 Vendi su MEXC / Compra su LBank"
                send_telegram_message(f"🚨 {pair}: Spread {spread:.2f}% → {action}", pair)
            else:
                action = "💤 Nessuna azione"

            temp_data.append((pair, price_mexc, price_lbank, spread, action))

        pairs_data = sorted(temp_data, key=lambda x: abs(x[3]), reverse=True)
        last_update = datetime.now()
        print_dashboard(pairs_data)
        logging.info("✅ Ciclo completato. Attendo 10 minuti...")
        time.sleep(600)

# === DASHBOARD WEB ===
@app.route('/')
def home():
    if not pairs_data:
        return "<h3>⏳ In attesa dei primi dati...</h3>"
    html = f"""
    <html>
    <head>
        <meta http-equiv="refresh" content="30">
        <style>
            body {{
                background-color: #0d1117;
                color: #c9d1d9;
                font-family: 'Consolas', monospace;
                padding: 20px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                padding: 10px;
                text-align: center;
                border-bottom: 1px solid #30363d;
            }}
            th {{
                color: #58a6ff;
            }}
            .green {{ color: #3fb950; }}
            .red {{ color: #f85149; }}
        </style>
    </head>
    <body>
        <h1>📊 Arbitrage Dashboard</h1>
        <p>Ultimo aggiornamento: {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'N/A'}</p>
        <table>
            <tr><th>Coppia</th><th>MEXC</th><th>LBank</th><th>Spread %</th><th>Azione</th></tr>
            {''.join(f"<tr><td>{p[0]}</td><td>{p[1]:.2f}</td><td>{p[2]:.2f}</td><td class='{'green' if p[3]>0 else 'red'}'>{p[3]:.2f}%</td><td>{p[4]}</td></tr>" for p in pairs_data[:20])}
        </table>
        <p style='color:#8b949e;'>Aggiornamento automatico ogni 30s</p>
    </body>
    </html>
    """
    return html

# === AVVIO ===
def start_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    Thread(target=arbitrage_loop, daemon=True).start()
    start_flask()






