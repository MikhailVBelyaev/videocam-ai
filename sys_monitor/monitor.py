import os
import time
import json
import psutil
import requests
import subprocess
from datetime import datetime

SYSINFO_PATH = "/app/output/.sysinfo.json"

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
    """Return (display_string, structured_list) for all GPUs."""
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
        gpu_list = []
        for line in output.splitlines():
            try:
                idx, temp, util, mem_used, mem_total = [x.strip() for x in line.split(",")]
                gpu_info.append(f"GPU{idx}: {temp}°C | Util {util}% | VRAM {mem_used}/{mem_total} MB")
                gpu_list.append({"index": idx, "temp": temp, "util": util,
                                  "mem_used": mem_used, "mem_total": mem_total})
            except Exception:
                gpu_info.append(f"GPU parse error: {line}")
        return "\n".join(gpu_info), gpu_list
    except Exception as e:
        return f"GPU info error: {e}", []

def get_ups_status():
    """Read UPS status from a host-generated file (avoid upower in Docker)."""
    try:
        ups_file = "/app/ups_status.txt"
        if not os.path.exists(ups_file):
            return "UPS info: File not found"
        with open(ups_file, "r") as f:
            lines = [line.strip() for line in f.readlines()]
        return "\n".join(lines) if lines else "UPS info: Empty file"
    except Exception as e:
        return f"UPS info error: {e}"

def get_cpu_temps():
    """Get CPU package temperature using sensors command."""
    try:
        output = subprocess.check_output(["sensors"], text=True)
        package_temp = None
        for line in output.splitlines():
            line = line.strip()
            if "Package id 0:" in line:
                # Example: Package id 0:  +58.0°C  (high = +80.0°C, crit = +100.0°C)
                parts = line.split()
                for part in parts:
                    if part.startswith("+") and part.endswith("°C"):
                        package_temp = part.strip("+").replace("°C", "")
                        break
        cpu_temp_str = f"CPU Package Temp: {package_temp}°C" if package_temp else "CPU Package Temp: N/A"
        return cpu_temp_str
    except Exception as e:
        return f"CPU temp info error: {e}"

def _write_sysinfo(data: dict):
    try:
        with open(SYSINFO_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Failed to write sysinfo: {e}")


SYSINFO_INTERVAL = 60    # seconds between .sysinfo.json updates (used by /state)
TELEGRAM_INTERVAL = 3600  # seconds between hourly Telegram reports


def main():
    """Main monitoring loop.

    .sysinfo.json is refreshed every SYSINFO_INTERVAL seconds so /state always
    shows current hardware stats. Telegram reports are sent once per hour.
    """
    last_telegram_ts = 0.0
    while True:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        gpu_str, gpu_list = get_gpu_stats()
        ups = get_ups_status()
        cpu_temps = get_cpu_temps()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Extract numeric CPU temp for JSON
        cpu_temp_val = None
        for token in cpu_temps.split():
            if token.endswith("°C"):
                try:
                    cpu_temp_val = float(token.replace("°C", ""))
                except ValueError:
                    pass

        _write_sysinfo({
            "timestamp": timestamp,
            "cpu_percent": cpu,
            "cpu_temp": cpu_temp_val,
            "ram_percent": round(ram.percent, 1),
            "ram_used_mb": ram.used // (1024 ** 2),
            "ram_total_mb": ram.total // (1024 ** 2),
            "disk_percent": round(disk.percent, 1),
            "disk_used_gb": disk.used // (1024 ** 3),
            "disk_total_gb": disk.total // (1024 ** 3),
            "gpus": gpu_list,
            "ups": ups,
        })

        now = time.time()
        if now - last_telegram_ts >= TELEGRAM_INTERVAL:
            msg = (
                f"🖥 System Report - {timestamp}\n"
                f"CPU Usage: {cpu}%\n"
                f"{cpu_temps}\n"
                f"RAM Usage: {ram.percent}% ({ram.used // (1024**2)}MB / {ram.total // (1024**2)}MB)\n"
                f"Disk Usage: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)\n"
                f"{gpu_str}\n"
                f"{ups}"
            )
            send_message(msg)
            last_telegram_ts = now

        time.sleep(SYSINFO_INTERVAL)

if __name__ == "__main__":
    main()
