FROM nvidia/cuda:11.8.0-base-ubuntu22.04

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
 python3 python3-pip upower \
&& rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the monitor script
COPY monitor.py .

CMD ["python3", "monitor.py"]
