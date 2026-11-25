# videocam-ai

## Existing camera runtime

The existing RTSP/YOLO camera script is still available:

```bash
CUDA_VISIBLE_DEVICES=1 python3 cams_grabber/main_ssh.py
```

## Snapshot triage (local folder)

This repository includes a deterministic single-camera snapshot triage pipeline.

Set up local development dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run from repository root:

```bash
.venv/bin/python cams_grabber/snapshot_triage.py <input_dir>
```

Default outputs:

- `output/triage_report.csv`
- `output/triage_summary.json`
- `rejected/` (copies of rejected images)

Default thresholds:

- `--blur-threshold 100.0`
- `--gradient-threshold 20.0`
- `--brightness-threshold 55.0`
- `--duplicate-distance-threshold 5`

Optional outputs:

- `--kept-dir <dir>` copies kept frames to a separate directory
- `--generate-video` creates a timelapse video from kept frames (`output/kept_timelapse.mp4`)
- `--video-fps 5.0` sets the frame rate for the timelapse video
- `--detect-objects` enables MobileNet-SSD car/person counting in CSV and JSON
- `--model-dir <dir>` specifies where MobileNetSSD model files live (default: `models`)
- `--expected-objects car,person` flags missing expected objects in JSON summary

Example with all outputs and thresholds:

```bash
.venv/bin/python cams_grabber/snapshot_triage.py ./sample_input \
  --output-dir ./output \
  --rejected-dir ./rejected \
  --kept-dir ./kept \
  --generate-video \
  --video-fps 5.0 \
  --blur-threshold 100 \
  --gradient-threshold 20 \
  --brightness-threshold 55 \
  --duplicate-distance-threshold 5 \
  --detect-objects \
  --model-dir ./models \
  --expected-objects car,person
```

The JSON summary (`output/triage_summary.json`) contains:

- `total_images` and `kept_images` counts
- `rejected_by_reason` breakdown (blur, low_light, duplicate, unreadable)
- `score_distributions` with min/max/mean/std for blur, gradient, and brightness scores
- `kept_frames` with per-frame `quality_rank` (0.0 to 1.0, higher is better)
- `total_objects_by_type` and per-frame `object_counts` when `--detect-objects` is enabled
- `missing_expected_objects` when `--expected-objects` is used and objects are absent

Validate the pipeline:

```bash
.venv/bin/python -m py_compile cams_grabber/snapshot_triage.py tests/test_snapshot_triage.py
.venv/bin/python -m unittest -v tests/test_snapshot_triage.py
.venv/bin/python -m unittest discover -s tests -v
```

## Web viewer

The `web_viewer` service serves static camera output files and provides a browser-accessible `/admin` dashboard.

`/admin` page (`http://<host>:8082/admin`) shows:

- Latest run date (from most recent `YYYY-MM-DD` folder in `output/`)
- Freshness indicator (within last 24h or stale)
- Total and kept image counts
- Car and person counts (when object detection is enabled)
- Missing expected object count (if any)
- Links to the latest images in the most recent dated folder

If `output/triage_summary.json` is missing or malformed, the page renders a concise error message without crashing.

Static file URLs (e.g., `http://<host>:8082/2026-06-19/frame.jpg`) continue to work as before.

After updating `docker-compose.yml`, recreate the container for the change to take effect:

```bash
docker compose up -d --force-recreate web_viewer
```

## Telegram bot

The `tg_bot` service sends **home-approach events** to Telegram and responds to
owner commands. Raw detection frames remain in `output/<camera>/<date>/` for
the existing retention period; road traffic is archive/statistics input, not a
Telegram notification.

The initial owner-calibrated polygon is stored at
`output/cam1/zone_config.json` on the first start. It is a copy of
`cams_grabber/zone_config.default.json`, traced from the owner's red boundary.
An event is created only after a supported object has stably entered the
home-side polygon. Each event has a JSON queue record and an evidence image in
`output/cam1/<date>/events/`; both are deleted together with their dated folder
by the existing retention job.

Environment variables (set in `tg_bot/.env`):

- `TELEGRAM_TOKEN` — bot token from BotFather
- `TELEGRAM_CHAT_ID` — default chat ID for image posts
- `TELEGRAM_ADMIN_CHAT_ID` — optional chat ID authorized for `/admin` (falls back to `TELEGRAM_CHAT_ID`)
- `MAX_IMAGES_PER_ITERATION` — optional cap on images sent per 5-second tick (default: `5`)
- `SEND_COOLDOWN_SECONDS` — optional cooldown after which the duplicate filter is bypassed (default: `300`)
- `IMAGE_SIMILARITY_THRESHOLD` — optional perceptual hash distance threshold for skipping similar images (default: `10`)
- `MAX_IMAGE_AGE_SECONDS` — optional maximum age in seconds for an image to be considered fresh enough to send (default: `3600`)

Commands:

- `/menu` — interactive home-approach controls: today/week statistics, mute for
  one hour, and unmute.
- `/stats` — raw semantic detection counts plus home-approach event counts.

- `/admin` — returns a single-page summary from the latest `output/triage_summary.json` **and sends the latest image file**:
  - latest run date and freshness indicator
  - total and kept image counts
  - car and person counts (when object detection is enabled)
  - missing expected object count (if any)
  - photo message with the most recent image from `output/`

- `/state` — returns a single-page container status summary (admin chat only):
  - status for `cams_grabber`, `tg_bot`, `sys_monitor`, `web_viewer`
  - running / exited / not-found state and health status (`N/A` when unavailable)
  - uptime or age for each container

Non-admin chats are silently ignored for both commands.

The `/state` command requires the Docker socket to be mounted into the `tg_bot`
container. The `docker-compose.yml` already includes a read-only mount:
`/var/run/docker.sock:/var/run/docker.sock:ro`. After updating the compose file,
recreate the container for the change to take effect:

```bash
docker compose up -d --force-recreate tg_bot
```

Run the bot locally (ensure `output/` exists and `tg_bot/.env` is configured):

```bash
.venv/bin/python -m pip install -r tg_bot/requirements.txt
.venv/bin/python tg_bot/bot.py
```

Or start via Docker Compose:

```bash
docker compose up -d tg_bot
```

The bot polls the event queue every 5 seconds and posts only new home-approach
evidence images to `TELEGRAM_CHAT_ID`. It does not drain raw camera frames.
On first start or when `output/.last_sent_file` is missing, the bot initializes its
state to the most recent image in the latest dated folder without sending it. This
prevents draining the entire folder on restart.
The sender includes three production safeguards:

- **Concurrency guard** — overlapping sender iterations are skipped so only one pass runs at a time.
- **Per-iteration cap** — at most `MAX_IMAGES_PER_ITERATION` images are sent in a single tick; remaining images resume on the next tick.
- **Cooldown bypass** — if no image has been sent for `SEND_COOLDOWN_SECONDS`, the next candidate is delivered even if it is perceptually similar to the last sent image.

Within the remaining unsent window, fresher frames are sent before older backlog frames (newest-first by file modification time). Images whose modification time is older than `MAX_IMAGE_AGE_SECONDS` are skipped as stale.

When the current dated folder yields zero sends because all remaining images are skipped (stale, similar, or non-kept), the bot automatically advances to the next dated folder on the next tick. A boundary guard prevents advancing past the newest folder.

When a `kept/` triage subfolder exists, only those images are sent; others are
skipped as non-kept. Images whose perceptual hash distance from the last sent
image is ≤ `IMAGE_SIMILARITY_THRESHOLD` are also skipped as similar duplicates.
The `/admin` command reports send statistics (sent, skipped similar, skipped non-kept, skipped stale), backlog size, latest capture time, latest sent time, last skip reason, watched folder, newest folder, state file content, and status indicator (Fresh or Stuck on ...).

Full operating details, tuning guidance, JSON schema, and limitations are in:

- `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`
- `docs/TG_BOT_RUNBOOK.md`
- `docs/WEB_VIEWER_RUNBOOK.md`

## Ролик события по кнопке (регистратор Hikvision)

**Зачем.** В уведомлении «кто-то у дома» был только кадр, а что происходило до и после, видно не было. Владелец (2026-11-25)
попросил кнопки под уведомлением: нажал — и бот присылает видео вокруг момента события.

**Как работает.**
- Под фото события `tg_bot` ставит кнопки `🎬 ±5 с`, `±10 с`, `±20 с` (`_clip_keyboard` в `tg_bot/bot.py`).
- По нажатию (`clip_callback`) бот забирает отрезок `[t−N, t+N]` из **архива регистратора** DS-7108NI-Q1 `192.168.100.23`
  RTSP-воспроизведением `/Streaming/tracks/101?starttime=…Z&endtime=…Z` и отвечает видео на это же сообщение (`tg_bot/nvr_clip.py`).
  Без перекодирования (`ffmpeg -c copy`, только видеодорожка: вторая дорожка регистратора в mp4 не кладётся). Ролик ±20 с ≈ 10 МБ.
- Ролики строго по одному (`_CLIP_LOCK`), ffmpeg с `nice 19`.
- **Время:** события пишутся в UTC без пояса, регистратор ищет по местному времени (UTC+5, «Z» в запросе у Hikvision значит «местное») —
  `nvr_clip.nvr_url` переводит. Часы регистратора и x99 сверены 2026-11-25: расхождение < 1 с.
- **Задержка архива:** регистратор отдаёт отрезок примерно через минуту после его конца (30 с — `400 Bad Request`, 60 с и больше — OK).
  Поэтому бот ждёт `NVR_LAG_SECONDS` (60) после конца окна и повторяет запрос до 3 раз. Ролик приходит через ~1–2 мин после нажатия.
- Дорожки: `cam1` → 101 (камера `.2`), `cam2` → 201 (камера `.3`), переменная `NVR_TRACKS`.

**Почему регистратор, а не свой буфер на x99.** Архив регистратора уже пишется и хранится сутками, x99 не тратит диск и процессор; ролик
можно получить и для старого уведомления. Минус — задержка ~1 мин и зависимость от пароля регистратора.

**Настройки** (`tg_bot/.env`, в git не попадает): `NVR_HOST`, `NVR_USER`, `NVR_PASS` (пароль как есть, бот сам кодирует), необязательно
`NVR_TRACKS`, `NVR_LAG_SECONDS`, `NVR_TZ_HOURS`. ⚠️ Неверный пароль несколько раз подряд — Hikvision блокирует адрес x99 (не подбирать).

**Как проверено.** `tests/test_nvr_clip.py` (UTC → местное время, кодирование пароля, дорожки); живой ролик с регистратора по реальному
событию из контейнера `tg_bot`; кадр с меткой камеры совпал с запрошенным временем.

**Как выключить.** Убрать `NVR_PASS` из `tg_bot/.env` и `docker restart tg_bot` — кнопки перестанут появляться, остальное не меняется.
