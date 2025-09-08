import os
import time
import psutil
import requests
import subprocess
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("❌ TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set as env variables")

def send_message(text: str):
    """Send a Telegram message."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        res = requests.post(url, data={"chat_id": CHAT_ID, "text": text})
        if res.status_code == 200:
            print(f"✅ Report sent successfully")
        else:
            print(f"⚠️ Failed to send report: {res.text}")
    except Exception as e:
        print(f"⚠️ Exception while sending report: {e}")

def get_gpu_stats():
    """Get GPU temperature, utilization, and VRAM usage."""
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,temperature.gpu,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits"
            ],
            text=True
        ).strip()

        gpu_info = []
        for line in output.splitlines():
            try:
                idx, temp, util, mem_used, mem_total = line.split(", ")
                gpu_info.append(
                    f"GPU{idx}: {temp}°C | Util {util}% | VRAM {mem_used}/{mem_total} MB"
                )
            except Exception:
                gpu_info.append(f"GPU parse error: {line}")
        return "\n".join(gpu_info)
    except Exception as e:
        return f"GPU info error: {e}"

def get_ups_status():
    """Get UPS state and percentage via upower."""
    try:
        # Adjust the path for your UPS device
        ups_path = "/org/freedesktop/UPower/devices/ups_hiddev0"
        output = subprocess.check_output(["upower", "-i", ups_path], text=True).strip()
        state, percent = None, None
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("state:"):
                state = line.split("state:")[1].strip()
            elif line.startswith("percentage:"):
                percent = line.split("percentage:")[1].strip()
        if state and percent:
            return f"UPS: {state} | {percent}"
        return "UPS: Not detected"
    except Exception as e:
        return f"UPS info error: {e}"

def main():
    """Main monitoring loop (runs every hour)."""
    while True:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        gpu = get_gpu_stats()
        ups = get_ups_status()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        msg = (
            f"🖥 System Report {timestamp}\n"
            f"CPU: {cpu}%\n"
            f"RAM: {ram.percent}% ({ram.used // (1024**2)}MB/{ram.total // (1024**2)}MB)\n"
            f"Disk: {disk.percent}% ({disk.used // (1024**3)}GB/{disk.total // (1024**3)}GB)\n"
            f"{gpu}\n"
            f"{ups}"
        )

        send_message(msg)
        time.sleep(3600)  # wait 1 hour

if __name__ == "__main__":
    main()
