import os
import time
import requests
import logging
import sys
from datetime import datetime
import pytz
from PIL import Image
import imagehash

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

LAST_SENT_IMAGE = None

def are_images_similar(img1_path, img2_path, threshold=5):
    """Compare two images using perceptual hash and return True if similar within threshold."""
    try:
        img1 = Image.open(img1_path)
        img2 = Image.open(img2_path)
        hash1 = imagehash.average_hash(img1)
        hash2 = imagehash.average_hash(img2)
        distance = hash1 - hash2
        return distance <= threshold
    except Exception as e:
        logger.error(f"Error comparing images {img1_path} and {img2_path}: {e}")
        return False

def load_sent_files():
    """Load already sent files from state file"""
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_file(file_path: str):
    """Append a new sent file to state file"""
    rel_path = os.path.relpath(file_path, OUTPUT_DIR)
    with open(STATE_FILE, "a") as f:
        f.write(rel_path + "\n")

def send_photo(file_path: str):
    global LAST_SENT_IMAGE
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(file_path, "rb") as photo:
        res = requests.post(url, data={"chat_id": CHAT_ID}, files={"photo": photo})
    if res.status_code == 200:
        logger.info(f"✅ Sent {file_path} to Telegram")
        rel_path = os.path.relpath(file_path, OUTPUT_DIR)
        save_sent_file(rel_path)
        LAST_SENT_IMAGE = file_path
        return True
    else:
        logger.error(f"⚠️ Failed to send {file_path}: {res.text}")
        return False

def main():
    global LAST_SENT_IMAGE
    logger.info("📡 Telegram bot started, watching for new files...")
    sent_files = load_sent_files()
    logger.info(f"Loaded {len(sent_files)} previously sent files from state")

    while True:
        try:
            for root, _, files in os.walk(OUTPUT_DIR):
                for file in sorted(files):
                    if file.startswith('.'):
                        continue
                    if not file.lower().endswith(('.jpg', '.jpeg', '.png')):
                        continue
                    path = os.path.join(root, file)
                    rel_path = os.path.relpath(path, OUTPUT_DIR)
                    if rel_path not in sent_files and os.path.isfile(path):
                        if LAST_SENT_IMAGE is not None and are_images_similar(LAST_SENT_IMAGE, path):
                            logger.info(f"⚠️ Skipped {file} (too similar to last sent image)")
                            continue
                        if send_photo(path):
                            sent_files.add(rel_path)
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")

        time.sleep(5)  # check every 5s

if __name__ == "__main__":
    main()
