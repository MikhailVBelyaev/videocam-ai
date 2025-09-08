import os
import time
import requests
import logging
import sys

# Setup logging for Docker (stdout)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

OUTPUT_DIR = "output"
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("❌ TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set as env variables")

def send_photo(file_path: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(file_path, "rb") as photo:
        res = requests.post(url, data={"chat_id": CHAT_ID}, files={"photo": photo})
    if res.status_code == 200:
        logging.info(f"✅ Sent {file_path} to Telegram")
    else:
        logging.error(f"⚠️ Failed to send {file_path}: {res.text}")

def main():
    logging.info("📡 Telegram bot started, watching for new files...")
    sent_files = set()

    while True:
        try:
            for file in sorted(os.listdir(OUTPUT_DIR)):
                path = os.path.join(OUTPUT_DIR, file)
                if path not in sent_files and os.path.isfile(path):
                    send_photo(path)
                    sent_files.add(path)
        except Exception as e:
            logging.exception(f"Unexpected error: {e}")

        time.sleep(5)  # check every 5s

if __name__ == "__main__":
    main()
