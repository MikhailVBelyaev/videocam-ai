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

The `tg_bot` service sends new camera frames to Telegram and responds to the `/admin` command.

Environment variables (set in `tg_bot/.env`):

- `TELEGRAM_TOKEN` — bot token from BotFather
- `TELEGRAM_CHAT_ID` — default chat ID for image posts
- `TELEGRAM_ADMIN_CHAT_ID` — optional chat ID authorized for `/admin` (falls back to `TELEGRAM_CHAT_ID`)
- `MAX_IMAGES_PER_ITERATION` — optional cap on images sent per 5-second tick (default: `5`)
- `SEND_COOLDOWN_SECONDS` — optional cooldown after which the duplicate filter is bypassed (default: `300`)
- `IMAGE_SIMILARITY_THRESHOLD` — optional perceptual hash distance threshold for skipping similar images (default: `10`)
- `MAX_IMAGE_AGE_SECONDS` — optional maximum age in seconds for an image to be considered fresh enough to send (default: `3600`)

Commands:

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

The bot polls `output/` every 5 seconds and posts new images to `TELEGRAM_CHAT_ID`.
On first start or when `output/.last_sent_file` is missing, the bot initializes its
state to the most recent image in the latest dated folder without sending it. This
prevents draining the entire folder on restart.
The sender includes three production safeguards:

- **Concurrency guard** — overlapping sender iterations are skipped so only one pass runs at a time.
- **Per-iteration cap** — at most `MAX_IMAGES_PER_ITERATION` images are sent in a single tick; remaining images resume on the next tick.
- **Cooldown bypass** — if no image has been sent for `SEND_COOLDOWN_SECONDS`, the next candidate is delivered even if it is perceptually similar to the last sent image.

Within the remaining unsent window, fresher frames are sent before older backlog frames (newest-first by file modification time). Images whose modification time is older than `MAX_IMAGE_AGE_SECONDS` are skipped as stale.

When a `kept/` triage subfolder exists, only those images are sent; others are
skipped as non-kept. Images whose perceptual hash distance from the last sent
image is ≤ `IMAGE_SIMILARITY_THRESHOLD` are also skipped as similar duplicates.
The `/admin` command reports send statistics (sent, skipped similar, skipped non-kept, skipped stale), backlog size, latest capture time, latest sent time, and last skip reason.

Full operating details, tuning guidance, JSON schema, and limitations are in:

- `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`
- `docs/TG_BOT_RUNBOOK.md`
- `docs/WEB_VIEWER_RUNBOOK.md`
