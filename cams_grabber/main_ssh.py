import cv2
from ultralytics import YOLO
from collections import defaultdict
import logging
import os
import sys
import time
import threading
import numpy as np
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logging.getLogger("ultralytics").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
RTSP_URL = "rtsp://admin:12311231aA%40@192.168.100.2:554/Streaming/Channels/101"

TARGET_CLASSES = {"car", "person"}
VEHICLE_CLASSES = {"car", "truck", "bus"}
CONF_THRESHOLD = 0.60
MIN_PERSIST_FRAMES = 4        # require 4 consecutive frames before saving (was 1)
COOLDOWN_SECONDS = 20         # per-object re-save gate in seconds (was COOLDOWN=20 with misleading comment)
MISSING_TOLERANCE = 4
DIAG_INTERVAL = 100

# Conservative quality thresholds — rejects obviously corrupt/composite frames.
# Lower than snapshot_triage defaults to avoid rejecting valid dark scenes.
BLUR_THRESHOLD = 30.0         # Laplacian variance; below = very blurry or corrupt
GRADIENT_THRESHOLD = 5.0      # gradient magnitude variance; below = flat/corrupt

# ---------------------------------------------------------------------------
# Frame quality validators (same math as snapshot_triage.py)
# ---------------------------------------------------------------------------

def _compute_blur_score(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _compute_gradient_score(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gx, gy = np.gradient(gray.astype(np.float64))
    magnitude = np.sqrt(gx**2 + gy**2)
    return float(magnitude.var())


def _is_frame_valid(frame: np.ndarray) -> bool:
    """Return False if the frame looks corrupt (blurry, composite, or flat)."""
    blur = _compute_blur_score(frame)
    grad = _compute_gradient_score(frame)
    if blur < BLUR_THRESHOLD or grad < GRADIENT_THRESHOLD:
        logging.warning("⚠️ Frame discarded: blur=%.1f grad=%.1f", blur, grad)
        return False
    return True


# ---------------------------------------------------------------------------
# RTSP reader thread — keeps only the latest fresh frame
# ---------------------------------------------------------------------------
# Each slot: (sequence_id: int, frame: np.ndarray, capture_ts: datetime)
_latest_slot: tuple | None = None
_frame_seq: int = 0
_frame_lock = threading.Lock()


def _open_stream(url: str) -> cv2.VideoCapture:
    """Open RTSP stream with TCP transport and a single-frame buffer."""
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def _reader_thread(url: str) -> None:
    """Daemon thread: continuously reads frames and stores only the latest one."""
    global _latest_slot, _frame_seq
    backoff = 1.0
    cap = _open_stream(url)
    logging.info("📡 RTSP reader thread connected (TCP)")
    while True:
        ret, frame = cap.read()
        if ret and frame is not None:
            ts = datetime.now()
            with _frame_lock:
                _frame_seq += 1
                _latest_slot = (_frame_seq, frame, ts)
            backoff = 1.0
        else:
            logging.warning("⚠️ Frame read failed — reconnecting in %.1fs", backoff)
            cap.release()
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            cap = _open_stream(url)


def _get_latest_slot() -> tuple | None:
    with _frame_lock:
        return _latest_slot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_daily_output_dir() -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = Path("output") / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def iou(boxA: list, boxB: list) -> float:
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union = areaA + areaB - interArea
    return interArea / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# Upgraded to yolov8s for better accuracy; device=0 pins to the GPU exposed
# inside the container via CUDA_VISIBLE_DEVICES=1 in docker-compose.
model = YOLO("yolov8s.pt")

object_last_seen: dict = {}
detection_buffer: dict = defaultdict(int)
missing_counter: dict = defaultdict(int)
prev_active: set = set()
frame_id = 0
_last_consumed_seq = 0

t = threading.Thread(target=_reader_thread, args=(RTSP_URL,), daemon=True)
t.start()

# ---------------------------------------------------------------------------
# Main inference loop
# ---------------------------------------------------------------------------

while True:
    slot = _get_latest_slot()
    if slot is None or slot[0] == _last_consumed_seq:
        time.sleep(0.01)
        continue

    seq_id, frame, capture_ts = slot
    _last_consumed_seq = seq_id

    # Discard corrupt or composite frames before running inference
    if not _is_frame_valid(frame):
        continue

    results = model.track(frame, persist=True, verbose=False, device=0)
    annotated = results[0].plot()
    class_names = results[0].names

    current_time = capture_ts  # filename timestamps now reflect actual capture time
    current_active: set = set()

    for box in results[0].boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        obj_id = int(box.id.item()) if box.id is not None else None
        if obj_id is None:
            continue
        class_name = class_names[cls_id]
        if class_name in VEHICLE_CLASSES:
            class_name = "vehicle"
        if class_name not in TARGET_CLASSES and class_name != "vehicle":
            continue
        if conf < CONF_THRESHOLD:
            continue

        detection_buffer[obj_id] += 1
        if detection_buffer[obj_id] < MIN_PERSIST_FRAMES:
            continue

        box_coords = box.xyxy[0].tolist()

        duplicate = False
        for stored_box, last_seen_time in object_last_seen.values():
            if (current_time - last_seen_time).total_seconds() <= COOLDOWN_SECONDS:
                if iou(box_coords, stored_box) > 0.7:
                    duplicate = True
                    break
        if duplicate:
            continue

        current_active.add((class_name, obj_id))
        missing_counter[obj_id] = 0

        last_seen = object_last_seen.get(obj_id)
        if last_seen is None or (current_time - last_seen[1]).total_seconds() > COOLDOWN_SECONDS:
            timestamp_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            logging.info(
                "🔔 New object: ID=%d Class=%s Conf=%.2f", obj_id, class_name, conf
            )
            output_dir = get_daily_output_dir()
            # Primary artifact: clean original frame (no annotations)
            filename = output_dir / f"frame_{timestamp_str}_id{obj_id}_{class_name}.jpg"
            cv2.imwrite(str(filename), frame)
            # Debug artifact: annotated frame with YOLO boxes
            debug_filename = output_dir / f"frame_{timestamp_str}_id{obj_id}_{class_name}_debug.jpg"
            cv2.imwrite(str(debug_filename), annotated)
            if filename.exists():
                logging.info("✅ Saved %s", filename)
                web_frame = Path("output") / "frame_for_web.jpg"
                cv2.imwrite(str(web_frame), annotated)
                logging.info("🌐 Updated web frame")
            else:
                logging.error("❌ Failed to save %s", filename)
            object_last_seen[obj_id] = (box_coords, current_time)
            detection_buffer[obj_id] = 0
        else:
            logging.info(
                "⏳ Cooldown active for ID=%d (%s), last seen %s",
                obj_id, class_name, last_seen[1],
            )

    # Handle missing objects with tolerance
    to_remove: set = set()
    for obj_id in list(object_last_seen.keys()):
        active_ids = {oid for _, oid in current_active}
        if obj_id not in active_ids:
            missing_counter[obj_id] += 1
            if missing_counter[obj_id] >= MISSING_TOLERANCE:
                to_remove.add(obj_id)
                missing_counter.pop(obj_id, None)
        else:
            missing_counter[obj_id] = 0

    prev_active = {item for item in prev_active if item[1] not in to_remove} | current_active

    frame_id += 1
    if frame_id % DIAG_INTERVAL == 0:
        detected = [
            f"{class_names[int(b.cls[0])]}({float(b.conf[0]):.2f})"
            for b in results[0].boxes
        ]
        logging.info("🔎 Diagnostic: frame %d, detections: %s", frame_id, detected)
