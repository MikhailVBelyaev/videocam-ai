import os
import time
import requests
import logging
import sys
from datetime import datetime
import pytz

# Setup logging for Docker (stdout) with Tashkent timezone
class TashkentFormatter(logging.Formatter):
    converter = datetime.fromtimestamp
    def formatTime(self, record, datefmt=None):
        tz = pytz.timezone("Asia/Tashkent")
        dt = datetime.fromtimestamp(record.created, tz)
        if datefmt:
            return dt.strftime(datefmt)
        else:
            return dt.isoformat()

handler = logging.StreamHandler(sys.stdout)
formatter = TashkentFormatter("%(asctime)s [%(levelname)s] %(message)s")
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

OUTPUT_DIR = "output"
STATE_FILE = os.path.join(OUTPUT_DIR, ".sent_files")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("❌ TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set as env variables")

def load_sent_files():
    """Load already sent files from state file"""
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_file(file_path: str):
    """Append a new sent file to state file"""
    with open(STATE_FILE, "a") as f:
        f.write(file_path + "\n")

def send_photo(file_path: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(file_path, "rb") as photo:
        res = requests.post(url, data={"chat_id": CHAT_ID}, files={"photo": photo})
    if res.status_code == 200:
        logger.info(f"✅ Sent {file_path} to Telegram")
        save_sent_file(file_path)
        return True
    else:
        logger.error(f"⚠️ Failed to send {file_path}: {res.text}")
        return False

def main():
    logger.info("📡 Telegram bot started, watching for new files...")
    sent_files = load_sent_files()
    logger.info(f"Loaded {len(sent_files)} previously sent files from state")

    while True:
        try:
            for file in sorted(os.listdir(OUTPUT_DIR)):
                path = os.path.join(OUTPUT_DIR, file)
                if path not in sent_files and os.path.isfile(path):
                    if send_photo(path):
                        sent_files.add(path)
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")

        time.sleep(5)  # check every 5s

if __name__ == "__main__":
    main()
