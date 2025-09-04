import cv2
from ultralytics import YOLO

model = YOLO("yolov8n.pt")  # lightweight model

rtsp_url = "rtsp://user:pass@192.168.1.50:554/Streaming/Channels/101"
cap = cv2.VideoCapture(rtsp_url)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    results = model(frame)   # runs on GPU if available
    annotated = results[0].plot()

    cv2.imshow("Hikvision Stream", annotated)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
