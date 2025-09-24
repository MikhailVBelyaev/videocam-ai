import cv2
from ultralytics import YOLO
from collections import defaultdict
import logging
import sys
from datetime import datetime
from pathlib import Path

def iou(boxA, boxB):
    # box format: [x1, y1, x2, y2]
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    interWidth = max(0, xB - xA)
    interHeight = max(0, yB - yA)
    interArea = interWidth * interHeight

    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])

    unionArea = boxAArea + boxBArea - interArea

    if unionArea == 0:
        return 0.0

    return interArea / unionArea

def get_daily_output_dir():
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = Path("output") / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.debug(f"📁 Using output directory: {output_dir.resolve()}")
    return output_dir

# Configure logging for Docker
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# Disable extra Ultralytics logging
logging.getLogger("ultralytics").setLevel(logging.WARNING)

# Load YOLOv8 model
model = YOLO("yolov8n.pt")

# Hikvision RTSP stream
rtsp_url = "rtsp://admin:12311231aA%40@192.168.100.2:554/Streaming/Channels/101"
cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

output_dir = get_daily_output_dir()

frame_id = 0
DIAG_INTERVAL = 100  # log every 100 frames for diagnostics

# Keep only these classes
TARGET_CLASSES = {"car", "person"}
CONF_THRESHOLD = 0.60  # require stronger confidence
MIN_PERSIST_FRAMES = 1  # allow faster confirmation
VEHICLE_CLASSES = {"car", "truck", "bus"}
MISSING_TOLERANCE = 4
COOLDOWN = 20  # shorter cooldown for testing

# Track last seen time and box coords for each object ID to implement cooldown and duplicate detection
object_last_seen = {}
detection_buffer = defaultdict(int)
missing_counter = defaultdict(int)
prev_active = set()

STABILITY_FRAMES = 5  # require 12 consecutive frames before confirming change (not used now but kept as constant)


while cap.isOpened():
    ret, frame = cap.read()
    if not ret or frame is None:
        logging.warning("⚠️ Failed to grab frame, retrying...")
        continue
    logging.debug("✅ Frame grabbed successfully")

    results = model.track(frame, persist=True, verbose=False)
    annotated = results[0].plot()
    class_names = results[0].names

    current_time = datetime.now()
    current_active = set()

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
        for stored_box, last_seen in object_last_seen.values():
            if (current_time - last_seen).total_seconds() <= COOLDOWN:
                if iou(box_coords, stored_box) > 0.7:
                    duplicate = True
                    break

        if duplicate:
            continue

        current_active.add((class_name, obj_id))
        missing_counter[obj_id] = 0

        last_seen = object_last_seen.get(obj_id)
        if last_seen is None or (current_time - last_seen[1]).total_seconds() > COOLDOWN:
            # Save detection and update last seen
            timestamp_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            logging.info(f"🕒 {timestamp_str} | 🔔 New object detected: ID={obj_id}, Class={class_name}, Confidence={conf:.2f}")
            output_dir = get_daily_output_dir()
            filename = output_dir / f"frame_{timestamp_str}_id{obj_id}_{class_name}.jpg"
            logging.info(f"🖼️ Preparing to save frame to {filename}")
            cv2.imwrite(str(filename), annotated)
            if not Path(filename).exists():
                logging.error(f"❌ Failed to save image at {filename}")
            else:
                logging.info(f"✅ Image successfully saved at {filename}")
                web_frame = Path("output") / "frame_for_web.jpg"
                cv2.imwrite(str(web_frame), annotated)
                logging.info(f"🌐 Updated latest web frame at {web_frame}")
            object_last_seen[obj_id] = (box_coords, current_time)
            detection_buffer[obj_id] = 0
        else:
            # Cooldown active, skip save but log
            timestamp_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            logging.info(f"⏳ Skipped save for ID={obj_id}, Class={class_name} due to cooldown (last seen {last_seen[1]})")

    # Handle missing objects with tolerance
    to_remove = set()
    for obj_id in list(object_last_seen.keys()):
        active_ids = {id for _, id in current_active}
        if obj_id not in active_ids:
            missing_counter[obj_id] += 1
            if missing_counter[obj_id] >= MISSING_TOLERANCE:
                to_remove.add(obj_id)
                missing_counter.pop(obj_id, None)
        else:
            missing_counter[obj_id] = 0

    if to_remove:
        new_active = set(filter(lambda x: x[1] not in to_remove, prev_active))
        if new_active != prev_active:
            prev_active = new_active

    prev_active = {item for item in prev_active if item[1] not in to_remove} | current_active

    # Skip logging empty state if current_active is empty but some missing_counter values are still less than MISSING_TOLERANCE
    if not current_active and prev_active and any(count < MISSING_TOLERANCE for count in missing_counter.values()):
        # Do not update prev_active or log changes here to avoid false "Change detected!" messages
        pass
    else:
        if not current_active and not prev_active:
            # Only log "{}" when prev_active becomes empty and all missing counters are >= MISSING_TOLERANCE
            if all(count >= MISSING_TOLERANCE for count in missing_counter.values()):
                frame_id += 1
                if frame_id % DIAG_INTERVAL == 0:
                    detected = []
                    for box in results[0].boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        class_name = class_names[cls_id]
                        detected.append(f"{class_name}({conf:.2f})")
                    logging.info(f"🔎 Diagnostic: frame {frame_id}, raw detections: {detected}")
        else:
            frame_id += 1
            if frame_id % DIAG_INTERVAL == 0:
                detected = []
                for box in results[0].boxes:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    class_name = class_names[cls_id]
                    detected.append(f"{class_name}({conf:.2f})")
                logging.info(f"🔎 Diagnostic: frame {frame_id}, raw detections: {detected}")

cap.release()
