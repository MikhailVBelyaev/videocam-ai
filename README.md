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

## Telegram bot

The `tg_bot` service sends new camera frames to Telegram and responds to the `/admin` command.

Environment variables (set in `tg_bot/.env`):

- `TELEGRAM_TOKEN` — bot token from BotFather
- `TELEGRAM_CHAT_ID` — default chat ID for image posts
- `TELEGRAM_ADMIN_CHAT_ID` — optional chat ID authorized for `/admin` (falls back to `TELEGRAM_CHAT_ID`)

Commands:

- `/admin` — returns a single-page summary from the latest `output/triage_summary.json`:
  - latest run date and freshness indicator
  - total and kept image counts
  - car and person counts (when object detection is enabled)
  - missing expected object count (if any)

Non-admin chats are silently ignored.

Run the bot locally (ensure `output/` exists and `tg_bot/.env` is configured):

```bash
.venv/bin/python -m pip install -r tg_bot/requirements.txt
.venv/bin/python tg_bot/bot.py
```

Or start via Docker Compose:

```bash
docker compose up -d tg_bot
```

The bot polls `output/` every 5 seconds and posts new images to `TELEGRAM_CHAT_ID`.

Full operating details, tuning guidance, JSON schema, and limitations are in:

- `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`
