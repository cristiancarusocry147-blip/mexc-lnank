import json
import os
import time
import logging
import requests
import threading
from datetime import datetime
from flask import Flask

# === FLASK (necessario per Render) ===
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Arbitrage Bot online e funzionante!"

# === COLORI TERMINALE ===
RED = "\033[91m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"

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
try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    raise SystemExit("❌ File config.json mancante!")

API_KEY_MEXC = config["MEXC"]["API_KEY"]
SECRET_KEY_MEXC = config["MEXC"]["SECRET_KEY"]
API_KEY_LBANK = config["LBANK"]["API_KEY"]
SECRET_KEY_LBANK = config["LBANK"]["SECRET_KEY"]
TELEGRAM_TOKEN = config["TELEGRAM"]["TOKEN"]
CHAT_ID = str(config["TELEGRAM"]["CHAT_ID"])

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# === STATO DEL BOT ===
alerts_enabled = True  # True = invia alert, False = fermo

# === TELEGRAM ===
def send_telegram_message(chat_id, message):
    try:
        url = f"{BASE_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        logging.error(f"Errore Telegram: {e}")

# === MOCK PREZZI (sostituibile con API reali) ===
def get_prices():
    price_mexc = 100.0 + (os.urandom(1)[0] % 10) / 10
    price_lbank = 100.0 + (os.urandom(1)[0] % 10) / 10
    return price_mexc, price_lbank

# === DASHBOARD ===
def print_dashboard(price_mexc, price_lbank, spread, alert_msg):
    os.system("clear")
    print(f"{CYAN}╔══════════════════════════════════════════════════╗{RESET}")
    print(f"{CYAN}║         FUTURES ARBITRAGE BOT — DASHBOARD        ║{RESET}")
    print(f"{CYAN}╠══════════════════════════════════════════════════╣{RESET}")
    print(f"  🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  💰 MEXC:  {YELLOW}{price_mexc:.2f}{RESET}")
    print(f"  💰 LBank: {YELLOW}{price_lbank:.2f}{RESET}")
    color = GREEN if spread > 0 else RED
    print(f"  📈 Spread: {color}{spread:.2f}%{RESET}")
    print(f"{CYAN}╠══════════════════════════════════════════════════╣{RESET}")
    if alert_msg:
        print(f"  ⚡ {alert_msg}")
    else:
        print("  💤 Nessun alert attivo.")
    print(f"{CYAN}╚══════════════════════════════════════════════════╝{RESET}")

# === LISTENER TELEGRAM ===
def telegram_listener():
    global alerts_enabled
    logging.info("🎧 Telegram listener avviato.")
    offset = None

    while True:
        try:
            url = f"{BASE_URL}/getUpdates"
            params = {"timeout": 30, "offset": offset}
            resp = requests.get(url, params=params, timeout=35)
            data = resp.json()

            if "result" in data:
                for update in data["result"]:
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    chat_id = str(message.get("chat", {}).get("id"))
                    text = message.get("text", "").strip().lower()

                    if not chat_id or not text:
                        continue

                    # Solo il tuo chat_id può controllare il bot
                    if chat_id != CHAT_ID:
                        send_telegram_message(chat_id, "⛔ Non sei autorizzato a usare questo bot.")
                        continue

                    if text == "/start":
                        send_telegram_message(chat_id, "👋 Benvenuto nel bot di arbitraggio!\nUsa /help per la lista comandi.")
                    elif text == "/help":
                        send_telegram_message(chat_id,
                            "📚 *Comandi disponibili:*\n"
                            "/start - Avvia il bot\n"
                            "/status - Mostra prezzi e spread\n"
                            "/stop - Ferma gli alert temporaneamente\n"
                            "/resume - Riattiva gli alert\n"
                            "/help - Mostra questo messaggio"
                        )
                    elif text == "/status":
                        price_mexc, price_lbank = get_prices()
                        spread = ((price_lbank - price_mexc) / price_mexc) * 100
                        status = "🟢 Attivo" if alerts_enabled else "🔴 In pausa"
                        send_telegram_message(chat_id,
                            f"💰 MEXC: {price_mexc:.2f}\n💰 LBank: {price_lbank:.2f}\n📈 Spread: {spread:.2f}%\n\n⚙️ Stato alert: {status}"
                        )
                    elif text == "/stop":
                        alerts_enabled = False
                        send_telegram_message(chat_id, "🛑 Alert sospesi. Il bot continuerà a monitorare ma non invierà notifiche.")
                    elif text == "/resume":
                        alerts_enabled = True
                        send_telegram_message(chat_id, "✅ Alert riattivati. Il bot riprenderà a notificare gli spread.")
                    else:
                        send_telegram_message(chat_id, "❓ Comando non riconosciuto. Usa /help.")
        except Exception as e:
            logging.error(f"Errore listener Telegram: {e}")
            time.sleep(5)

# === LOOP PRINCIPALE ===
def arbitrage_bot():
    global alerts_enabled
    logging.info("✅ Bot futures avviato.")
    send_telegram_message(CHAT_ID, "🚀 Bot futures avviato con successo!")
    last_alert_time = 0

    while True:
        try:
            price_mexc, price_lbank = get_prices()
            spread = ((price_lbank - price_mexc) / price_mexc) * 100
            alert_msg = ""

            if alerts_enabled and abs(spread) >= 3:
                now = time.time()
                if now - last_alert_time > 600:
                    alert_msg = f"🚨 Spread {spread:.2f}% tra MEXC ({price_mexc:.2f}) e LBank ({price_lbank:.2f})"
                    logging.info(alert_msg)
                    send_telegram_message(CHAT_ID, alert_msg)
                    last_alert_time = now

            print_dashboard(price_mexc, price_lbank, spread, alert_msg)
            time.sleep(10)

        except Exception as e:
            logging.error(f"Errore nel loop principale: {e}")
            send_telegram_message(CHAT_ID, f"⚠️ Errore nel bot: {e}")
            time.sleep(10)

# === AVVIO ===
if __name__ == "__main__":
    threading.Thread(target=arbitrage_bot, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

