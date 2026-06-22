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

from telegram import BotCommand, Update
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
STACKING_FLAG_FILE = os.path.join(OUTPUT_DIR, ".frame_stacking")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or CHAT_ID
KEEP_DAYS = 3
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv")

MAX_IMAGES_PER_ITERATION = int(os.getenv("MAX_IMAGES_PER_ITERATION", "5"))
SEND_COOLDOWN_SECONDS = int(os.getenv("SEND_COOLDOWN_SECONDS", "300"))
IMAGE_SIMILARITY_THRESHOLD = int(os.getenv("IMAGE_SIMILARITY_THRESHOLD", "10"))
try:
    MAX_IMAGE_AGE_SECONDS = int(os.getenv("MAX_IMAGE_AGE_SECONDS", "3600"))
except ValueError:
    MAX_IMAGE_AGE_SECONDS = 3600

_SENDER_LOCK = asyncio.Lock()
_LAST_SENT_TIMESTAMP = 0.0
_SENT_COUNT = 0
_SKIPPED_DUPLICATE_COUNT = 0
_SKIPPED_STALE_COUNT = 0
_LAST_SKIP_REASON = ""

# Per-camera state: {camera_id: {"folder": str|None, "image": str|None, "last_sent_ts": float}}
_cam_state: dict = {}


# ---------------------------------------------------------------------------
# Camera / folder helpers
# ---------------------------------------------------------------------------

def _is_date_str(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _cameras() -> list:
    """Return sorted list of camera dir names under OUTPUT_DIR (non-date, non-dot subdirs)."""
    try:
        return sorted([
            e for e in os.listdir(OUTPUT_DIR)
            if os.path.isdir(os.path.join(OUTPUT_DIR, e))
            and not e.startswith('.')
            and not _is_date_str(e)
        ])
    except OSError:
        return []


def _get_dates_for_camera(camera: str) -> list:
    base = os.path.join(OUTPUT_DIR, camera)
    try:
        return sorted([
            e for e in os.listdir(base)
            if os.path.isdir(os.path.join(base, e)) and _is_date_str(e)
        ])
    except OSError:
        return []


def _get_latest_run_date_for_camera(camera: str):
    dates = _get_dates_for_camera(camera)
    return dates[-1] if dates else None


def _get_latest_run_date() -> str | None:
    dates = [_get_latest_run_date_for_camera(c) for c in _cameras()]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def _get_image_list_for_folder(folder_path: str) -> list:
    try:
        return sorted([
            f for f in os.listdir(folder_path)
            if f.lower().endswith(IMAGE_EXTENSIONS)
            and not f.startswith(".")
            and not f.endswith("_debug.jpg")
            and os.path.isfile(os.path.join(folder_path, f))
        ])
    except OSError:
        return []


def _get_latest_image_path() -> str | None:
    best_path = None
    best_mtime = 0.0
    for camera in _cameras():
        run_date = _get_latest_run_date_for_camera(camera)
        if not run_date:
            continue
        folder = os.path.join(OUTPUT_DIR, camera, run_date)
        for f in _get_image_list_for_folder(folder):
            path = os.path.join(folder, f)
            try:
                mtime = os.path.getmtime(path)
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_path = path
            except OSError:
                pass
    return best_path


def _is_fresh(run_date: str | None) -> bool:
    if not run_date:
        return False
    try:
        run_dt = datetime.strptime(run_date, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
        return (datetime.now(pytz.UTC) - run_dt) <= timedelta(days=1)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Per-camera state persistence
# ---------------------------------------------------------------------------

def _cam_state_file(camera: str) -> str:
    return os.path.join(OUTPUT_DIR, camera, ".last_sent_file")


def _load_cam_state(camera: str):
    f = _cam_state_file(camera)
    if not os.path.exists(f):
        return None, None
    try:
        with open(f) as fp:
            line = fp.read().strip()
        if line:
            parts = line.split('/', 1)
            if len(parts) == 2:
                folder, filename = parts
                if filename:
                    return folder, os.path.join(OUTPUT_DIR, camera, folder, filename)
                return folder, None
    except OSError:
        pass
    return None, None


def _save_cam_state(camera: str, folder: str, file_path=None):
    try:
        os.makedirs(os.path.join(OUTPUT_DIR, camera), exist_ok=True)
        with open(_cam_state_file(camera), 'w') as fp:
            if file_path:
                fp.write(f"{folder}/{os.path.basename(file_path)}\n")
            else:
                fp.write(f"{folder}/\n")
    except OSError:
        pass


def _init_all_cameras():
    """Load or initialize per-camera state for all visible camera dirs."""
    for camera in _cameras():
        folder, image = _load_cam_state(camera)
        if folder:
            _cam_state[camera] = {"folder": folder, "image": image, "last_sent_ts": 0.0}
            logger.info(f"[{camera}] Loaded state: folder={folder} image={os.path.basename(image) if image else None}")
        else:
            run_date = _get_latest_run_date_for_camera(camera)
            if run_date:
                fp = os.path.join(OUTPUT_DIR, camera, run_date)
                files = _get_image_list_for_folder(fp)
                if files:
                    latest = os.path.join(fp, max(files, key=lambda f: os.path.getmtime(os.path.join(fp, f))))
                    _cam_state[camera] = {"folder": run_date, "image": latest, "last_sent_ts": 0.0}
                    _save_cam_state(camera, run_date, latest)
                    logger.info(f"[{camera}] Initialized to latest: {os.path.basename(latest)}")
                else:
                    _cam_state[camera] = {"folder": run_date, "image": None, "last_sent_ts": 0.0}
            else:
                _cam_state[camera] = {"folder": None, "image": None, "last_sent_ts": 0.0}


# ---------------------------------------------------------------------------
# Old folder cleanup
# ---------------------------------------------------------------------------

def cleanup_old_folders():
    for camera in _cameras():
        cam_dir = os.path.join(OUTPUT_DIR, camera)
        dates = _get_dates_for_camera(camera)
        to_delete = dates[:-KEEP_DAYS] if len(dates) > KEEP_DAYS else []
        for date in to_delete:
            full = os.path.join(cam_dir, date)
            try:
                shutil.rmtree(full)
                logger.info(f"Deleted old folder: {full}")
            except Exception as e:
                logger.error(f"Failed to delete {full}: {e}")


# ---------------------------------------------------------------------------
# Image similarity
# ---------------------------------------------------------------------------

def are_images_similar(img1_path, img2_path, threshold=5):
    try:
        h1 = imagehash.average_hash(Image.open(img1_path))
        h2 = imagehash.average_hash(Image.open(img2_path))
        return (h1 - h2) <= threshold
    except Exception as e:
        logger.error(f"Error comparing images: {e}")
        return False


# ---------------------------------------------------------------------------
# Telegram send
# ---------------------------------------------------------------------------

def send_photo(file_path: str, caption: str = None) -> bool:
    global _LAST_SENT_TIMESTAMP, _SENT_COUNT
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {"chat_id": CHAT_ID}
    if caption:
        data["caption"] = caption
    try:
        with open(file_path, "rb") as photo:
            res = requests.post(url, data=data, files={"photo": photo})
        if res.status_code == 200:
            logger.info(f"Sent {file_path}")
            _LAST_SENT_TIMESTAMP = time.time()
            _SENT_COUNT += 1
            return True
        else:
            logger.error(f"Failed to send {file_path}: {res.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending {file_path}: {e}")
        return False


# ---------------------------------------------------------------------------
# Per-camera image sender
# ---------------------------------------------------------------------------

def _send_camera_images(camera: str, multi_cam: bool):
    global _cam_state, _SKIPPED_DUPLICATE_COUNT, _SKIPPED_STALE_COUNT, _LAST_SKIP_REASON

    # Ensure state entry exists (handles cameras discovered after startup)
    if camera not in _cam_state:
        folder, image = _load_cam_state(camera)
        if not folder:
            folder = _get_latest_run_date_for_camera(camera)
        _cam_state[camera] = {"folder": folder, "image": image, "last_sent_ts": 0.0}

    state = _cam_state[camera]
    last_sent_folder = state["folder"]
    last_sent_image = state["image"]
    last_sent_ts = state["last_sent_ts"]

    subfolders = _get_dates_for_camera(camera)
    if not subfolders:
        return

    if last_sent_folder and last_sent_folder in subfolders:
        folder_index = subfolders.index(last_sent_folder)
    else:
        folder_index = len(subfolders) - 1

    current_folder = subfolders[folder_index]
    folder_path = os.path.join(OUTPUT_DIR, camera, current_folder)
    image_files = _get_image_list_for_folder(folder_path)

    start_index = 0
    if last_sent_image and last_sent_folder == current_folder:
        fn = os.path.basename(last_sent_image)
        try:
            start_index = image_files.index(fn) + 1
        except ValueError:
            start_index = 0

    remaining = image_files[start_index:]
    remaining.sort(
        key=lambda f: os.path.getmtime(os.path.join(folder_path, f))
                      if os.path.exists(os.path.join(folder_path, f)) else 0.0,
        reverse=True,
    )

    now = time.time()
    sent_count = 0
    for filename in remaining:
        path = os.path.join(folder_path, filename)
        if not os.path.isfile(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime < now - MAX_IMAGE_AGE_SECONDS:
            _SKIPPED_STALE_COUNT += 1
            _LAST_SKIP_REASON = "stale"
            logger.info(f"[{camera}] Skipped {filename} (stale)")
            continue
        if last_sent_image and are_images_similar(last_sent_image, path, IMAGE_SIMILARITY_THRESHOLD):
            if (now - last_sent_ts) <= SEND_COOLDOWN_SECONDS:
                _SKIPPED_DUPLICATE_COUNT += 1
                _LAST_SKIP_REASON = "similar"
                logger.info(f"[{camera}] Skipped {filename} (similar)")
                continue
        caption = camera if multi_cam else None
        if send_photo(path, caption=caption):
            state["folder"] = current_folder
            state["image"] = path
            state["last_sent_ts"] = time.time()
            last_sent_image = path
            last_sent_ts = state["last_sent_ts"]
            _save_cam_state(camera, current_folder, path)
            sent_count += 1
            if sent_count >= MAX_IMAGES_PER_ITERATION:
                break

    # Advance to the next date folder when this one is exhausted
    newest = _get_latest_run_date_for_camera(camera)
    if sent_count == 0 and newest and current_folder != newest:
        next_i = folder_index + 1
        if next_i < len(subfolders):
            nf = subfolders[next_i]
            state["folder"] = nf
            state["image"] = None
            _save_cam_state(camera, nf, None)
            logger.info(f"[{camera}] Advanced to folder {nf}")


def _send_new_images_iteration():
    cameras = _cameras()
    if not cameras:
        return
    multi = len(cameras) > 1
    for camera in cameras:
        try:
            _send_camera_images(camera, multi)
        except Exception as e:
            logger.exception(f"[{camera}] Unexpected error: {e}")
    cleanup_old_folders()


async def image_sender_job(context: ContextTypes.DEFAULT_TYPE):
    if _SENDER_LOCK.locked():
        logger.info("Skipping overlapping image_sender_job")
        return
    async with _SENDER_LOCK:
        await asyncio.to_thread(_send_new_images_iteration)


# ---------------------------------------------------------------------------
# /admin command helpers
# ---------------------------------------------------------------------------

def _is_admin_chat(update: Update) -> bool:
    return str(update.effective_chat.id) == str(ADMIN_CHAT_ID)


def _read_latest_summary() -> dict | None:
    path = os.path.join(OUTPUT_DIR, "triage_summary.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _summarize_live_output() -> dict | None:
    cameras = _cameras()
    if not cameras:
        return None

    total_images = total_videos = total_vehicles = total_people = 0
    latest_name = latest_dt = None
    latest_mtime = 0.0

    for camera in cameras:
        run_date = _get_latest_run_date_for_camera(camera)
        if not run_date:
            continue
        folder = os.path.join(OUTPUT_DIR, camera, run_date)
        try:
            filenames = [f for f in os.listdir(folder)
                         if not f.startswith('.') and os.path.isfile(os.path.join(folder, f))]
        except OSError:
            continue
        imgs = [f for f in filenames if f.lower().endswith(IMAGE_EXTENSIONS) and not f.endswith("_debug.jpg")]
        vids = [f for f in filenames if f.lower().endswith(VIDEO_EXTENSIONS)]
        total_images += len(imgs)
        total_videos += len(vids)
        total_vehicles += sum(1 for f in imgs if "vehicle" in f or "car" in f)
        total_people += sum(1 for f in imgs if "person" in f)
        for f in imgs + vids:
            try:
                mt = os.path.getmtime(os.path.join(folder, f))
                if mt > latest_mtime:
                    latest_mtime = mt
                    latest_name = f"{camera}/{f}"
                    latest_dt = datetime.fromtimestamp(mt, pytz.timezone("Asia/Tashkent")).isoformat(timespec="seconds")
            except OSError:
                pass

    if total_images + total_videos == 0:
        return None
    return {
        "summary_source": "live_output",
        "total_images": total_images,
        "kept_images": total_images,
        "video_files": total_videos,
        "total_objects_by_type": {"car": total_vehicles, "person": total_people},
        "latest_file": latest_name,
        "latest_file_time": latest_dt,
        "missing_expected_objects": [],
    }


def _format_admin_message(summary: dict, run_date: str | None, fresh: bool) -> str:
    total = summary.get("total_images", 0)
    kept = summary.get("kept_images", 0)
    objects = summary.get("total_objects_by_type", {})
    car_count = objects.get("car", 0)
    person_count = objects.get("person", 0)
    video_count = summary.get("video_files")
    latest_file = summary.get("latest_file")
    latest_file_time = summary.get("latest_file_time")
    source = summary.get("summary_source")
    missing_count = len(summary.get("missing_expected_objects", []))

    status = "✅ Fresh (within 24h)" if fresh else "⚠️ Stale"
    date_str = run_date or "Unknown"

    lines = [
        "*Admin Summary*", "",
        f"*Latest run:* {date_str}",
        f"*Status:* {status}", "",
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
        lines += ["", "_Live output summary; no triage report found._"]
    if missing_count:
        lines.append(f"*Missing expected:* {missing_count} frames")

    lines += [
        "", f"*Sent:* {_SENT_COUNT}",
        f"*Skipped (similar):* {_SKIPPED_DUPLICATE_COUNT}",
        f"*Skipped (stale):* {_SKIPPED_STALE_COUNT}",
    ]

    # Backlog: unsent images summed across all cameras
    backlog = 0
    for camera in _cameras():
        state = _cam_state.get(camera, {})
        cam_folder = state.get("folder")
        cam_image = state.get("image")
        cam_date = _get_latest_run_date_for_camera(camera)
        if cam_date:
            fp = os.path.join(OUTPUT_DIR, camera, cam_date)
            imgs = _get_image_list_for_folder(fp)
            si = 0
            if cam_image and cam_folder == cam_date:
                fn = os.path.basename(cam_image)
                try:
                    si = imgs.index(fn) + 1
                except ValueError:
                    pass
            backlog += len(imgs) - si

    # Latest capture time (across all cameras)
    latest_cap = _get_latest_image_path()
    latest_cap_str = "Unknown"
    if latest_cap:
        try:
            latest_cap_str = datetime.fromtimestamp(
                os.path.getmtime(latest_cap), pytz.timezone("Asia/Tashkent")
            ).isoformat(timespec="seconds")
        except Exception:
            pass

    # Latest sent time
    latest_sent_str = "Never"
    if _LAST_SENT_TIMESTAMP:
        try:
            latest_sent_str = datetime.fromtimestamp(
                _LAST_SENT_TIMESTAMP, pytz.timezone("Asia/Tashkent")
            ).isoformat(timespec="seconds")
        except Exception:
            pass

    lines += [
        "", f"*Backlog:* {backlog}",
        f"*Latest capture:* {latest_cap_str}",
        f"*Latest sent:* {latest_sent_str}",
        f"*Last skip reason:* {_LAST_SKIP_REASON or '—'}",
    ]

    # Per-camera cursor status
    cameras = _cameras()
    if cameras:
        lines += ["", "*Cameras:*"]
        for cam in cameras:
            state = _cam_state.get(cam, {})
            watching = state.get("folder", "?")
            newest = _get_latest_run_date_for_camera(cam) or "?"
            stuck_flag = "⚠️" if watching != newest else "✅"
            lines.append(f"  {stuck_flag} `{cam}` watching `{watching}` (newest `{newest}`)")

    return "\n".join(lines)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_chat(update):
        return
    summary = _read_latest_summary() or _summarize_live_output()
    if summary is None:
        await update.message.reply_text("No output data available.")
        return
    run_date = _get_latest_run_date()
    fresh = _is_fresh(run_date)
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
# /stacking commands
# ---------------------------------------------------------------------------

async def stacking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_chat(update):
        return
    enabled = os.path.exists(STACKING_FLAG_FILE)
    state = "ON" if enabled else "OFF"
    await update.message.reply_text(
        f"*Frame stacking:* {state}\n\n"
        "Combines 3 aligned frames to reduce sensor noise at night.\n"
        "Use /stacking\\_on or /stacking\\_off to toggle.",
        parse_mode="Markdown",
    )


async def stacking_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_chat(update):
        return
    try:
        open(STACKING_FLAG_FILE, "w").close()
        await update.message.reply_text(
            "Frame stacking *enabled*. The next saved frame will be a 3-frame median stack.",
            parse_mode="Markdown",
        )
        logger.info("Frame stacking enabled via Telegram command")
    except OSError as e:
        await update.message.reply_text(f"Failed to enable stacking: {e}")


async def stacking_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_chat(update):
        return
    try:
        if os.path.exists(STACKING_FLAG_FILE):
            os.remove(STACKING_FLAG_FILE)
        await update.message.reply_text(
            "Frame stacking *disabled*. Frames will be saved as single raw captures.",
            parse_mode="Markdown",
        )
        logger.info("Frame stacking disabled via Telegram command")
    except OSError as e:
        await update.message.reply_text(f"Failed to disable stacking: {e}")


# ---------------------------------------------------------------------------
# /state command helpers
# ---------------------------------------------------------------------------

EXPECTED_CONTAINERS = [
    "cams_grabber_cam1", "cams_grabber_cam2", "cams_grabber_cam3",
    "tg_bot", "sys_monitor", "web_viewer", "qa_service",
]


def _format_uptime(started_at: str | None) -> str:
    if not started_at:
        return "N/A"
    try:
        dt_str = started_at
        if "." in dt_str:
            base, frac = dt_str.split(".", 1)
            frac = frac.rstrip("Z")[:6]
            dt_str = f"{base}.{frac}" if frac else base
        dt_str = dt_str.rstrip("Z")
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        started = datetime.fromisoformat(dt_str)
        if started.tzinfo is None:
            started = started.replace(tzinfo=pytz.UTC)
        delta = datetime.now(pytz.UTC) - started
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


SYSINFO_FILE = os.path.join(OUTPUT_DIR, ".sysinfo.json")


def _read_sysinfo() -> dict | None:
    try:
        with open(SYSINFO_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _format_sysinfo(s: dict) -> str:
    ts = s.get("timestamp", "?")
    cpu = s.get("cpu_percent", "?")
    cpu_temp = s.get("cpu_temp")
    ram_pct = s.get("ram_percent", "?")
    ram_used = s.get("ram_used_mb", "?")
    ram_total = s.get("ram_total_mb", "?")
    disk_pct = s.get("disk_percent", "?")
    disk_used = s.get("disk_used_gb", "?")
    disk_total = s.get("disk_total_gb", "?")
    gpus = s.get("gpus", [])

    temp_str = f" | {cpu_temp}°C" if cpu_temp is not None else ""
    lines = [
        f"", f"🖥 *Hardware* (as of {ts})",
        f"CPU: {cpu}%{temp_str}",
        f"RAM: {ram_pct}% ({ram_used} / {ram_total} MB)",
        f"Disk: {disk_pct}% ({disk_used} / {disk_total} GB)",
    ]
    for g in gpus:
        lines.append(
            f"GPU{g['index']}: {g['temp']}°C | {g['util']}% | {g['mem_used']}/{g['mem_total']} MB"
        )
    return "\n".join(lines)


def _format_state_message(states, sysinfo: dict | None) -> str:
    lines = ["*Container Status*", ""]
    for s in states:
        status = s["status"]
        emoji = "✅" if status == "running" else "❌" if status in ("exited", "not-found") else "⚠️"
        lines.append(
            f"{emoji} *{s['name']}* — {status} | health: {s['health']} | {_format_uptime(s['started_at'])}"
        )
    if sysinfo:
        lines.append(_format_sysinfo(sysinfo))
    return "\n".join(lines)


async def state_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_chat(update):
        return
    states = _query_container_states()
    if states is None:
        await update.message.reply_text("Container runtime unavailable. Docker socket not mounted?")
        return
    sysinfo = _read_sysinfo()
    await update.message.reply_text(_format_state_message(states, sysinfo), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Bot command menu + startup
# ---------------------------------------------------------------------------

BOT_COMMANDS = [
    BotCommand("admin",        "Summary + latest captured image"),
    BotCommand("state",        "Container health and uptime"),
    BotCommand("stacking",     "Show frame stacking state (ON / OFF)"),
    BotCommand("stacking_on",  "Enable nighttime multi-frame stacking"),
    BotCommand("stacking_off", "Disable nighttime multi-frame stacking"),
]


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("Bot command menu registered (%d commands)", len(BOT_COMMANDS))


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set as env variables")

    logger.info("Telegram bot started, watching for new files...")
    _init_all_cameras()

    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("admin",        admin_command))
    app.add_handler(CommandHandler("state",        state_command))
    app.add_handler(CommandHandler("stacking",     stacking_command))
    app.add_handler(CommandHandler("stacking_on",  stacking_on_command))
    app.add_handler(CommandHandler("stacking_off", stacking_off_command))
    app.job_queue.run_repeating(image_sender_job, interval=5, first=5)
    app.run_polling()


if __name__ == "__main__":
    main()
