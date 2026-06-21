FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Install PyTorch (CUDA 11.8 build) explicitly
RUN pip3 install --no-cache-dir torch==2.2.2+cu118 torchvision==0.17.2+cu118 torchaudio==2.2.2+cu118 \
    -f https://download.pytorch.org/whl/torch_stable.html

# Copy your app files
COPY main_ssh.py .
COPY yolov8s.pt .

# Ensure output folder exists
RUN mkdir -p /app/output

# Default command
CMD ["python3", "main_ssh.py"]
