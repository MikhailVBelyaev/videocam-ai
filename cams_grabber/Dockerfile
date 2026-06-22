FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-tools \
    python3-gi \
    gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0 \
    && rm -rf /var/lib/apt/lists/*

# Pin PyTorch CUDA 11.8 build BEFORE installing requirements.
# If requirements.txt is installed first, ultralytics pulls torch 2.x with
# CUDA 13 dependencies (~2 GB of extra libs). Installing torch first satisfies
# the torch requirement so pip reuses this install instead of downloading again.
RUN pip3 install --no-cache-dir \
    torch==2.2.2+cu118 torchvision==0.17.2+cu118 \
    -f https://download.pytorch.org/whl/torch_stable.html

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY main_ssh.py .

# Download YOLOv8s weights at build time so the container is self-contained
RUN python3 -c "from ultralytics import YOLO; YOLO('yolov8s.pt')"

RUN mkdir -p /app/output

CMD ["python3", "main_ssh.py"]
