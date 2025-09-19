import cv2
from ultralytics import YOLO
from collections import Counter, defaultdict
import logging
import sys
from datetime import datetime

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

frame_id = 0
prev_counts = Counter()  # last confirmed counts
pending_counts = None
stability_counter = 0
STABILITY_FRAMES = 5  # require 5 consecutive frames before confirming change

# Keep only these classes
TARGET_CLASSES = {"car", "person"}
CONF_THRESHOLD = 0.58  # allow slightly lower confidence to reduce false negatives

# Track previous detections to avoid duplicates
last_detected_ids = defaultdict(set)  # {class_name: set of object IDs}

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        logging.warning("⚠️ Failed to grab frame")
        break

    results = model(frame, verbose=False)
    annotated = results[0].plot()
    class_names = results[0].names

    # Extract detected objects
    detected_classes = [
        class_names[int(c)]
        for c, conf in zip(results[0].boxes.cls, results[0].boxes.conf)
        if class_names[int(c)] in TARGET_CLASSES and conf >= CONF_THRESHOLD
    ]
    counts = Counter(detected_classes)

    # Stability check
    if counts != prev_counts:
        if counts == pending_counts:
            stability_counter += 1
        else:
            pending_counts = counts
            stability_counter = 1

        if stability_counter >= STABILITY_FRAMES:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logging.info(f"🕒 {timestamp} | 🔔 Change detected! {dict(counts)}")

            # Save frame only if at least 1 target object detected
            if sum(counts.values()) > 0:
                filename = f"output/frame_{timestamp}_{dict(counts)}.jpg"
                cv2.imwrite(filename, annotated)
                logging.info(f"✅ Saved {filename}")

            prev_counts = counts
            stability_counter = 0
            pending_counts = None

    frame_id += 1

cap.release()
