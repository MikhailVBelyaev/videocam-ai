"""Ролик события из архива регистратора Hikvision (RTSP-воспроизведение), без перекодирования.

Время события в events/*.json записано в UTC без пояса (контейнеры живут в UTC), а регистратор ищет запись
по своему МЕСТНОМУ времени (Ташкент, UTC+5) — поэтому окно переводится в местное. Проверено 2026-11-25:
запрос 17:14:17–17:14:27 дал ролик с меткой камеры 17:14:16–17:14:25.
"""
import calendar
import os
import subprocess
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

NVR_HOST = os.getenv("NVR_HOST", "192.168.100.23")
NVR_USER = os.getenv("NVR_USER", "admin")
NVR_PASS = os.getenv("NVR_PASS", "")
NVR_TZ = timezone(timedelta(hours=int(os.getenv("NVR_TZ_HOURS", "5"))))
# камера videocam-ai -> дорожка регистратора (канал 1 = .2 = cam1, канал 2 = .3)
NVR_TRACKS = dict(x.split(":") for x in os.getenv("NVR_TRACKS", "cam1:101,cam2:201").split(",") if x)
ALLOWED_PADS = (5, 10, 20)
# Регистратор отдаёт отрезок примерно через минуту после его конца (замер 2026-11-25: 30 с — 400 Bad Request, 60 с и больше — OK),
# и не сразу закрывает предыдущий сеанс воспроизведения — поэтому ждём и повторяем.
NVR_LAG_SECONDS = int(os.getenv("NVR_LAG_SECONDS", "60"))
NVR_RETRIES, NVR_RETRY_PAUSE = 3, 20


def event_epoch(ts: str) -> int:
    """2026-11-25T10:36:31 (UTC, без пояса) -> unix-время."""
    return calendar.timegm(datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timetuple())


def clip_window(epoch: int, pad: int) -> tuple:
    return epoch - pad, epoch + pad


def nvr_url(camera: str, start: int, end: int, password: str = None) -> str:
    fmt = lambda t: datetime.fromtimestamp(t, NVR_TZ).strftime("%Y%m%dT%H%M%S") + "Z"  # «Z» — особенность Hikvision, время местное
    pw = urllib.parse.quote(NVR_PASS if password is None else password, safe="")
    return (f"rtsp://{urllib.parse.quote(NVR_USER, safe='')}:{pw}@{NVR_HOST}:554/Streaming/tracks/{NVR_TRACKS[camera]}"
            f"?starttime={fmt(start)}&endtime={fmt(end)}")


def fetch_clip(camera: str, epoch: int, pad: int, out_path: str, on_stage=None) -> str:
    """Скачать ролик [epoch-pad, epoch+pad] в out_path (mp4). Возвращает путь; при ошибке — RuntimeError без пароля в тексте.
    on_stage(текст) — сообщать этапы владельцу (ожидание архива, скачивание, повтор)."""
    stage = on_stage or (lambda _text: None)
    if pad not in ALLOWED_PADS or camera not in NVR_TRACKS or not NVR_PASS:
        raise RuntimeError("ролик недоступен: нет пароля регистратора или неизвестная камера")
    start, end = clip_window(epoch, pad)
    wait = end + NVR_LAG_SECONDS - time.time()
    if wait > 0:
        stage(f"⏳ Жду, пока регистратор запишет отрезок в архив: ~{int(wait)} с")
        time.sleep(wait)
    cmd = ["nice", "-n", "19", "ffmpeg", "-v", "error", "-rtsp_transport", "tcp", "-i", nvr_url(camera, start, end),
           "-map", "0:v:0", "-c", "copy", "-t", str(end - start), "-movflags", "+faststart", "-y", out_path]
    err = ""
    for attempt in range(NVR_RETRIES):
        if attempt:
            stage(f"⏳ Регистратор ещё не отдал запись, повтор {attempt + 1} из {NVR_RETRIES} через {NVR_RETRY_PAUSE} с")
            time.sleep(NVR_RETRY_PAUSE)
        stage(f"⬇️ Скачиваю {end - start} с видео с регистратора…")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=(end - start) * 3 + 60)
        if r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) >= 10_000:
            return out_path
        err = (r.stderr or "").replace(urllib.parse.quote(NVR_PASS, safe=""), "***").strip()[-300:] or str(r.returncode)
    raise RuntimeError(f"регистратор не отдал запись ({err})")
