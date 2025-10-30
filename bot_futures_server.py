import json
import time
import logging
import requests
import os
from datetime import datetime

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

# === CONFIG (da variabili d'ambiente) ===
API_KEY_MEXC = os.getenv("API_KEY_MEXC")
SECRET_KEY_MEXC = os.getenv("SECRET_KEY_MEXC")
API_KEY_LBANK = os.getenv("API_KEY_LBANK")
SECRET_KEY_LBANK = os.getenv("SECRET_KEY_LBANK")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Verifica chiavi
if not all([TELEGRAM_TOKEN, CHAT_ID]):
    logging.error("❌ Mancano variabili TELEGRAM_TOKEN o CHAT_ID. Impostale su Render.")
    raise SystemExit("Errore: Variabili Telegram non trovate")

# === TELEGRAM ===
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        logging.error(f"Errore Telegram: {e}")

# === MOCK PREZZI (sostituisci con API reali) ===
def get_prices():
    # Sostituisci con chiamate reali alle API MEXC / LBank
    price_mexc = 100.0 + (os.urandom(1)[0] % 10) / 10  # 100.0 - 109.9
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

# === MAIN LOOP ===
def main():
    logging.info("✅ Bot futures avviato.")
    send_telegram_message("🚀 Bot futures avviato con successo!")

    last_alert_time = 0

    while True:
        try:
            price_mexc, price_lbank = get_prices()
            spread = ((price_lbank - price_mexc) / price_mexc) * 100

            alert_msg = ""
            if abs(spread) >= 3:
                now = time.time()
                # Evita spam: massimo 1 notifica ogni 10 minuti
                if now - last_alert_time > 600:
                    alert_msg = f"🚨 Spread {spread:.2f}% tra MEXC ({price_mexc:.2f}) e LBank ({price_lbank:.2f})"
                    logging.info(alert_msg)
                    send_telegram_message(alert_msg)
                    last_alert_time = now

            print_dashboard(price_mexc, price_lbank, spread, alert_msg)
            time.sleep(10)

        except Exception as e:
            logging.error(f"Errore nel loop: {e}")
            send_telegram_message(f"⚠️ Errore nel bot: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
