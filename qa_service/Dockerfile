FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

RUN apt-get update && apt-get install -y \
    python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install CUDA 11.8 PyTorch first so ultralytics reuses it
RUN pip3 install --no-cache-dir torch==2.2.2+cu118 torchvision==0.17.2+cu118 \
    -f https://download.pytorch.org/whl/torch_stable.html

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY qa.py .

# Download yolov8n weights at build time
RUN python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

RUN mkdir -p /app/output

CMD ["python3", "qa.py"]
