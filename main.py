import cv2
from ultralytics import YOLO

# Load YOLOv8n (tiny model, faster on GPU)
model = YOLO("yolov8n.pt")

# Hikvision RTSP (with %40 for @ in password)
rtsp_url = "rtsp://admin:12311231aA%40@192.168.100.2:554/Streaming/Channels/101"

# Use FFmpeg backend to handle H.265
cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        print("⚠️ Failed to grab frame")
        break

    # Run YOLO
    results = model(frame)
    annotated = results[0].plot()

    # Show detections
    cv2.imshow("Hikvision Stream", annotated)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
