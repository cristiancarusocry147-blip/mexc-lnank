import os
import time
import json
import logging
import requests
import random
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# === FLASK APP ===
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

# === TELEGRAM CONTROL ===
last_alert_time = {}

def send_telegram_message(message, pair):
    """Evita spam: 1 messaggio per coppia ogni 30 minuti"""
    now = datetime.now()
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.warning("⚠️ Telegram non configurato")
        return
    if pair in last_alert_time and (now - last_alert_time[pair]) < timedelta(minutes=30):
        return  # evita spam
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10
        )
        last_alert_time[pair] = now
        logging.info(f"✅ Notifica Telegram inviata per {pair}")
    except Exception as e:
        logging.error(f"Errore Telegram: {e}")

# === DATI REALI (API) ===
def get_common_pairs():
    """Recupera coppie comuni tra futures perpetual di MEXC e LBank"""
    try:
        # === MEXC Futures (USDT-M Perpetual) ===
        mexc_url = "https://contract.mexc.com/api/v1/contract/detail"
        mexc_data = requests.get(mexc_url, timeout=10).json()
        mexc_pairs = {item["symbol"].upper().replace("_", "").replace("-", "") for item in mexc_data.get("data", [])}

        # === LBank Futures (Perpetual) ===
        lbank_url = "https://www.lbkex.net/v2/futures/contracts.do"
        lbank_data = requests.get(lbank_url, timeout=10).json()
        lbank_pairs = {item["symbol"].upper().replace("_", "").replace("-", "") for item in lbank_data.get("data", [])}

        # Trova coppie comuni
        common = list(mexc_pairs & lbank_pairs)
        common = [pair.replace("USDT", "/USDT") for pair in common if pair.endswith("USDT")][:200]

        logging.info(f"✅ Trovate {len(common)} coppie futures perpetual comuni MEXC/LBank.")
        return common

    except Exception as e:
        logging.error(f"Errore nel recupero coppie futures: {e}")
        return []

# === STATO GLOBALE ===
pairs_data = []
last_update = None
last_pairs_update = None

# === DASHBOARD CLI ===
def print_dashboard(pairs_data):
    console.clear()
    console.rule(f"[bold cyan]📊 Arbitrage Dashboard — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    table = Table(show_header=True, header_style="bold magenta", style="on black")
    table.add_column("Coppia")
    table.add_column("MEXC")
    table.add_column("LBank")
    table.add_column("Spread %")
    table.add_column("Azione")

    for pair, mexc, lbank, spread, action in pairs_data[:10]:
        color = "green" if spread > 0 else "red"
        table.add_row(pair, f"{mexc:.2f}", f"{lbank:.2f}", f"[{color}]{spread:.2f}%[/{color}]", action)

    console.print(table)
    console.print(Panel.fit("🕒 Aggiornamento automatico ogni 10 minuti", style="bold cyan"))

# === LOOP PRINCIPALE ===
def arbitrage_loop():
    global pairs_data, last_update, last_pairs_update
    logging.info("🚀 Avvio bot arbitraggio multi-coppia")

    while True:
        pairs = get_common_pairs()
        last_pairs_update = datetime.now()

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
        return "<h3 style='color:white;background:black;padding:20px;'>⏳ In attesa dei primi dati...</h3>"
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
            h1 {{ color: #58a6ff; }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 10px;
                text-align: center;
                border-bottom: 1px solid #30363d;
            }}
            th {{ color: #58a6ff; }}
            .green {{ color: #3fb950; }}
            .red {{ color: #f85149; }}
            .info {{ color: #8b949e; }}
        </style>
    </head>
    <body>
        <h1>📊 Futures Arbitrage Dashboard</h1>
        <p class='info'>Ultimo aggiornamento dati: {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'N/A'}</p>
        <p class='info'>Ultimo aggiornamento coppie da API: {last_pairs_update.strftime('%Y-%m-%d %H:%M:%S') if last_pairs_update else 'N/A'}</p>
        <table>
            <tr><th>Coppia</th><th>MEXC</th><th>LBank</th><th>Spread %</th><th>Azione</th></tr>
            {''.join(f"<tr><td>{p[0]}</td><td>{p[1]:.2f}</td><td>{p[2]:.2f}</td><td class='{'green' if p[3]>0 else 'red'}'>{p[3]:.2f}%</td><td>{p[4]}</td></tr>" for p in pairs_data[:20])}
        </table>
        <p class='info'>Aggiornamento automatico ogni 30 secondi</p>
    </body>
    </html>
    """
    return html

# === AVVIO ===
def start_flask():
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🌐 Web dashboard attiva su porta {port}")
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    t = Thread(target=arbitrage_loop, daemon=True)
    t.start()
    start_flask()








