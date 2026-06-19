import os
import time
import requests
import logging
import sys
import json
from datetime import datetime, timedelta
import pytz
from PIL import Image
import imagehash
import shutil
import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

try:
    import docker
    from docker.errors import NotFound, DockerException
except ImportError:
    docker = None
    NotFound = None
    DockerException = None

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
for noisy_logger in ("httpx", "httpcore", "telegram", "apscheduler.executors.default"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

OUTPUT_DIR = "output"
LAST_SENT_FILE = os.path.join(OUTPUT_DIR, ".last_sent_file")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or CHAT_ID
KEEP_DAYS = 3
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv")

MAX_IMAGES_PER_ITERATION = int(os.getenv("MAX_IMAGES_PER_ITERATION", "5"))
SEND_COOLDOWN_SECONDS = int(os.getenv("SEND_COOLDOWN_SECONDS", "300"))
_SENDER_LOCK = asyncio.Lock()
_LAST_SENT_TIMESTAMP = 0.0


def cleanup_old_folders():
    """
    Remove old dated folders in OUTPUT_DIR, keeping only the most recent KEEP_DAYS.
    Only directories with names like YYYY-MM-DD are considered.
    """
    try:
        entries = os.listdir(OUTPUT_DIR)
        date_dirs = []
        for entry in entries:
            full_path = os.path.join(OUTPUT_DIR, entry)
            if os.path.isdir(full_path):
                try:
                    # Check if name is a date like YYYY-MM-DD
                    datetime.strptime(entry, "%Y-%m-%d")
                    date_dirs.append(entry)
                except ValueError:
                    continue
        date_dirs_sorted = sorted(date_dirs)
        to_delete = date_dirs_sorted[:-KEEP_DAYS] if len(date_dirs_sorted) > KEEP_DAYS else []
        for entry in to_delete:
            full_path = os.path.join(OUTPUT_DIR, entry)
            try:
                shutil.rmtree(full_path)
                logger.info(f"🗑️ Deleted old folder: {full_path}")
            except Exception as e:
                logger.error(f"Failed to delete folder {full_path}: {e}")
    except Exception as e:
        logger.error(f"Error during cleanup_old_folders: {e}")


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


def load_last_sent_file():
    """Load the last sent folder and file path from the state file"""
    if not os.path.exists(LAST_SENT_FILE):
        return None, None
    with open(LAST_SENT_FILE, "r") as f:
        line = f.read().strip()
        if line:
            parts = line.split('/', 1)
            if len(parts) == 2:
                folder, filename = parts
                return folder, os.path.join(OUTPUT_DIR, folder, filename)
            else:
                return None, None
        else:
            return None, None


def save_last_sent_file(folder: str, file_path: str):
    """Save the last sent folder and file path to the state file"""
    rel_path = os.path.relpath(file_path, os.path.join(OUTPUT_DIR, folder))
    with open(LAST_SENT_FILE, "w") as f:
        f.write(f"{folder}/{rel_path}\n")


def send_photo(file_path: str):
    global LAST_SENT_IMAGE, LAST_SENT_FOLDER, _LAST_SENT_TIMESTAMP
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(file_path, "rb") as photo:
        res = requests.post(url, data={"chat_id": CHAT_ID}, files={"photo": photo})
    if res.status_code == 200:
        logger.info(f"✅ Sent {file_path} to Telegram")
        # Extract folder from file_path
        folder = os.path.relpath(os.path.dirname(file_path), OUTPUT_DIR)
        save_last_sent_file(folder, file_path)
        LAST_SENT_IMAGE = file_path
        LAST_SENT_FOLDER = folder
        _LAST_SENT_TIMESTAMP = time.time()
        return True
    else:
        logger.error(f"⚠️ Failed to send {file_path}: {res.text}")
        return False


# ---------------------------------------------------------------------------
# /admin command helpers
# ---------------------------------------------------------------------------

def _is_admin_chat(update: Update) -> bool:
    """Return True if the incoming update is from the configured admin chat."""
    chat_id = str(update.effective_chat.id)
    return chat_id == str(ADMIN_CHAT_ID)


def _read_latest_summary() -> dict | None:
    """Read and parse output/triage_summary.json, or None if missing/malformed."""
    path = os.path.join(OUTPUT_DIR, "triage_summary.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _get_latest_run_date() -> str | None:
    """Return the most recent YYYY-MM-DD folder name in OUTPUT_DIR, or None."""
    try:
        entries = os.listdir(OUTPUT_DIR)
        date_dirs = []
        for entry in entries:
            full_path = os.path.join(OUTPUT_DIR, entry)
            if os.path.isdir(full_path):
                try:
                    datetime.strptime(entry, "%Y-%m-%d")
                    date_dirs.append(entry)
                except ValueError:
                    continue
        if not date_dirs:
            return None
        return max(date_dirs)
    except OSError:
        return None


def _get_latest_image_path() -> str | None:
    """Return absolute path to the most recently modified image in the latest dated folder, or None."""
    run_date = _get_latest_run_date()
    if not run_date:
        return None
    folder_path = os.path.join(OUTPUT_DIR, run_date)
    try:
        files = [
            f for f in os.listdir(folder_path)
            if f.lower().endswith(IMAGE_EXTENSIONS)
            and os.path.isfile(os.path.join(folder_path, f))
        ]
        if not files:
            return None
        latest = max(files, key=lambda f: os.path.getmtime(os.path.join(folder_path, f)))
        return os.path.join(folder_path, latest)
    except OSError:
        return None


def _summarize_live_output() -> dict | None:
    """Summarize the latest live output folder when no triage summary exists."""
    run_date = _get_latest_run_date()
    if not run_date:
        return None
    folder_path = os.path.join(OUTPUT_DIR, run_date)
    try:
        filenames = [
            name
            for name in os.listdir(folder_path)
            if not name.startswith(".") and os.path.isfile(os.path.join(folder_path, name))
        ]
    except OSError:
        return None

    image_files = [
        name for name in filenames if name.lower().endswith(IMAGE_EXTENSIONS)
    ]
    video_files = [
        name for name in filenames if name.lower().endswith(VIDEO_EXTENSIONS)
    ]
    media_files = image_files + video_files
    if not media_files:
        return None

    latest_name = max(
        media_files,
        key=lambda name: os.path.getmtime(os.path.join(folder_path, name)),
    )
    latest_path = os.path.join(folder_path, latest_name)
    latest_dt = datetime.fromtimestamp(
        os.path.getmtime(latest_path),
        pytz.timezone("Asia/Tashkent"),
    ).isoformat(timespec="seconds")

    vehicle_count = sum(
        1 for name in media_files if "vehicle" in name.lower() or "car" in name.lower()
    )
    person_count = sum(1 for name in media_files if "person" in name.lower())

    return {
        "summary_source": "live_output",
        "total_images": len(image_files),
        "kept_images": len(image_files),
        "video_files": len(video_files),
        "total_objects_by_type": {"car": vehicle_count, "person": person_count},
        "latest_file": latest_name,
        "latest_file_time": latest_dt,
        "missing_expected_objects": [],
    }


def _is_fresh(run_date: str | None) -> bool:
    """Return True if run_date is within the last 24 hours."""
    if not run_date:
        return False
    try:
        run_dt = datetime.strptime(run_date, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
        now = datetime.now(pytz.UTC)
        return (now - run_dt) <= timedelta(days=1)
    except ValueError:
        return False


def _format_admin_message(summary: dict, run_date: str | None, fresh: bool) -> str:
    """Compose a single-page Markdown message for the /admin command."""
    total = summary.get("total_images", 0)
    kept = summary.get("kept_images", 0)
    objects = summary.get("total_objects_by_type", {})
    car_count = objects.get("car", 0)
    person_count = objects.get("person", 0)
    missing = summary.get("missing_expected_objects", [])
    missing_count = len(missing)
    video_count = summary.get("video_files")
    latest_file = summary.get("latest_file")
    latest_file_time = summary.get("latest_file_time")
    source = summary.get("summary_source")

    status = "✅ Fresh (within 24h)" if fresh else "⚠️ Stale"
    date_str = run_date or "Unknown"

    lines = [
        "*Admin Summary*",
        "",
        f"*Latest run:* {date_str}",
        f"*Status:* {status}",
        "",
        f"*Images:* {total} total, {kept} kept",
        f"*Objects:* {car_count} cars, {person_count} people",
    ]
    if video_count is not None:
        lines.append(f"*Videos:* {video_count}")
    if latest_file:
        lines.extend(["", f"*Latest file:* `{latest_file}`"])
    if latest_file_time:
        lines.append(f"*Latest time:* {latest_file_time}")
    if source == "live_output":
        lines.append("")
        lines.append("_Live output summary; no triage report found._")
    if missing_count:
        lines.append(f"*Missing expected:* {missing_count} frames")
    return "\n".join(lines)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /admin command: return triage summary to authorized chats only."""
    if not _is_admin_chat(update):
        return  # silent ignore for non-admin chats

    summary = _read_latest_summary()
    run_date = _get_latest_run_date()
    fresh = _is_fresh(run_date)

    if summary is None:
        summary = _summarize_live_output()

    if summary is None:
        await update.message.reply_text("No output data available.")
        return

    text = _format_admin_message(summary, run_date, fresh)
    await update.message.reply_text(text, parse_mode="Markdown")

    image_path = _get_latest_image_path()
    if image_path:
        try:
            await update.message.reply_photo(photo=image_path)
        except Exception as e:
            logger.error(f"Failed to send latest image: {e}")
            await update.message.reply_text("No latest image available.")
    else:
        await update.message.reply_text("No latest image available.")


# ---------------------------------------------------------------------------
# /state command helpers
# ---------------------------------------------------------------------------

EXPECTED_CONTAINERS = ["cams_grabber", "tg_bot", "sys_monitor", "web_viewer"]


def _format_uptime(started_at: str | None) -> str:
    """Return a human-readable uptime string from an ISO 8601 timestamp."""
    if not started_at:
        return "N/A"
    try:
        # Docker returns ISO 8601 with nanoseconds (e.g., 2026-06-19T08:00:00.123456789Z)
        # Truncate to microseconds for Python's fromisoformat
        dt_str = started_at
        if "." in dt_str:
            base, frac = dt_str.split(".", 1)
            # Keep only up to 6 digits of fractional seconds
            frac = frac.rstrip("Z")
            frac = frac[:6]
            if frac:
                dt_str = f"{base}.{frac}"
            else:
                dt_str = base
        dt_str = dt_str.rstrip("Z")
        # fromisoformat handles timezone offsets but not "Z" directly in older Python,
        # though Python 3.12 supports it. Replace Z with +00:00 for safety.
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        started = datetime.fromisoformat(dt_str)
        # Ensure started is timezone-aware before subtracting
        if started.tzinfo is None:
            started = started.replace(tzinfo=pytz.UTC)
        now = datetime.now(pytz.UTC)
        delta = now - started
        if delta < timedelta(seconds=60):
            return f"up {int(delta.total_seconds())}s"
        if delta < timedelta(hours=1):
            return f"up {delta.seconds // 60}m"
        if delta < timedelta(days=1):
            return f"up {delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
        return f"up {delta.days}d {delta.seconds // 3600}h"
    except Exception:
        return started_at or "N/A"


def _query_container_states():
    """Query Docker daemon for expected container states. Returns list of dicts or None."""
    if docker is None:
        return None
    try:
        client = docker.DockerClient.from_env()
    except DockerException:
        return None
    states = []
    for name in EXPECTED_CONTAINERS:
        try:
            c = client.containers.get(name)
            attrs = c.attrs.get("State", {})
            health = attrs.get("Health", {}).get("Status", "N/A")
            states.append({
                "name": name,
                "status": attrs.get("Status", "unknown"),
                "health": health,
                "started_at": attrs.get("StartedAt"),
            })
        except NotFound:
            states.append({
                "name": name,
                "status": "not-found",
                "health": "N/A",
                "started_at": None,
            })
    client.close()
    return states


def _format_state_message(states):
    """Compose a single-page Markdown message from container state dicts."""
    lines = ["*Container Status*", ""]
    for s in states:
        status = s["status"]
        status_emoji = "✅" if status == "running" else "❌" if status in ("exited", "not-found") else "⚠️"
        health = s["health"]
        uptime = _format_uptime(s["started_at"])
        lines.append(
            f"{status_emoji} *{s['name']}* — {status} | health: {health} | {uptime}"
        )
    return "\n".join(lines)


async def state_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /state command: return container status to authorized chats only."""
    if not _is_admin_chat(update):
        return  # silent ignore for non-admin chats

    states = _query_container_states()
    if states is None:
        await update.message.reply_text(
            "Container runtime unavailable. Docker socket not mounted?"
        )
        return

    text = _format_state_message(states)
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Background image sender (adapted from the original polling loop)
# ---------------------------------------------------------------------------

LAST_SENT_IMAGE = None
LAST_SENT_FOLDER = None


def _send_new_images_iteration():
    """One pass of the original image-sending loop (no sleep)."""
    global LAST_SENT_IMAGE, LAST_SENT_FOLDER
    try:
        # List subfolders in OUTPUT_DIR with valid date names
        subfolders = []
        for entry in os.listdir(OUTPUT_DIR):
            full_path = os.path.join(OUTPUT_DIR, entry)
            if os.path.isdir(full_path):
                try:
                    datetime.strptime(entry, "%Y-%m-%d")
                    subfolders.append(entry)
                except ValueError:
                    continue
        if not subfolders:
            return
        subfolders.sort()

        # Determine which folder to process
        if LAST_SENT_FOLDER and LAST_SENT_FOLDER in subfolders:
            folder_index = subfolders.index(LAST_SENT_FOLDER)
        else:
            folder_index = len(subfolders) - 1  # Latest folder

        current_folder = subfolders[folder_index]
        folder_path = os.path.join(OUTPUT_DIR, current_folder)

        # List image files in the current folder
        image_files = []
        for file in os.listdir(folder_path):
            if file.startswith('.'):
                continue
            if not file.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            image_files.append(file)
        image_files.sort()

        start_index = 0
        if LAST_SENT_IMAGE is not None and LAST_SENT_FOLDER == current_folder:
            last_sent_filename = os.path.basename(LAST_SENT_IMAGE)
            try:
                start_index = image_files.index(last_sent_filename) + 1
            except ValueError:
                start_index = 0

        sent_count = 0
        for filename in image_files[start_index:]:
            path = os.path.join(folder_path, filename)
            if os.path.isfile(path):
                if LAST_SENT_IMAGE is not None and are_images_similar(LAST_SENT_IMAGE, path):
                    cooldown_expired = (time.time() - _LAST_SENT_TIMESTAMP) > SEND_COOLDOWN_SECONDS
                    if cooldown_expired:
                        logger.info(f"Cooldown expired; sending {filename} despite similarity")
                    else:
                        logger.info(f"Skipped {filename} (too similar to last sent image)")
                        continue
                if send_photo(path):
                    sent_count += 1
                    if sent_count >= MAX_IMAGES_PER_ITERATION:
                        break
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")

    cleanup_old_folders()


async def image_sender_job(context: ContextTypes.DEFAULT_TYPE):
    """Async wrapper that runs the synchronous image-sender in a thread."""
    if _SENDER_LOCK.locked():
        logger.info("Skipping overlapping image_sender_job")
        return
    async with _SENDER_LOCK:
        await asyncio.to_thread(_send_new_images_iteration)


def main():
    global LAST_SENT_IMAGE, LAST_SENT_FOLDER
    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError("❌ TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set as env variables")

    logger.info("📡 Telegram bot started, watching for new files...")
    LAST_SENT_FOLDER, LAST_SENT_IMAGE = load_last_sent_file()
    if LAST_SENT_IMAGE:
        logger.info(f"Loaded last sent file from state: {LAST_SENT_IMAGE}")
    else:
        logger.info("No previously sent file found in state")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("state", state_command))
    app.job_queue.run_repeating(image_sender_job, interval=5, first=5)
    app.run_polling()


if __name__ == "__main__":
    main()
