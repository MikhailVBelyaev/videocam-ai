# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

Read [`docs/PROJECT_STATUS_MEMORY.md`](docs/PROJECT_STATUS_MEMORY.md) and
[`docs/NEXT_ACTIONS.md`](docs/NEXT_ACTIONS.md) at the start of every session.
Log progress in [`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md) after each significant change.
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) is the source of truth for system design decisions.

---

## What this project is

An always-on **AI-powered outdoor camera surveillance system** running on a home server.

An IP camera streams RTSP H.264 video from a courtyard. The system:
1. Captures frames in real time using a dedicated reader thread (RTSP over TCP)
2. Runs YOLOv8s object detection to identify vehicles and people
3. Saves a clean frame each time a new object is tracked (20 s cooldown per ID)
4. Sends captured frames to a private Telegram channel for immediate review
5. Exposes a web gallery for browsing all saved frames
6. Runs a separate QA service that independently re-validates each saved frame
   and reports quality/statistics on a live web dashboard

The system runs 24/7 in Docker on the production server with automatic restart.

---

## Current state

All five services are deployed and running:

| Service | Status | Port |
|---|---|---|
| `cams_grabber` | Running — RTSP capture + YOLOv8s, GPU 1 | — |
| `tg_bot` | Running — sends new frames to Telegram | — |
| `sys_monitor` | Running — hardware health monitoring | — |
| `web_viewer` | Running — browse saved frames | 8082 |
| `qa_service` | Running — QA dashboard + stats | 8083 |

See `docs/PROJECT_STATUS_MEMORY.md` for the full picture.

---

## Deploy workflow (always follow this)

```bash
# 1. Make and test changes locally
# 2. Commit
git add <files>
git commit -m "message"

# 3. Push to GitHub
git push origin main

# 4. Pull on production server
ssh user@oldgamepc.tail7c033b.ts.net "cd ~/Projects/videocam-ai && git pull origin main"

# 5. Rebuild only the changed service
ssh user@oldgamepc.tail7c033b.ts.net "cd ~/Projects/videocam-ai && docker compose up -d --build <service>"
```

**Never** deploy directly from local filesystem (no rsync). Always go through GitHub.
**Never** rebuild all services unless you changed docker-compose.yml or a shared dependency.

---

## Running the stack

```bash
# Start all services
docker compose up -d --build

# Rebuild and restart one service
docker compose up -d --build cams_grabber

# View live logs
docker compose logs -f cams_grabber
docker compose logs -f qa_service

# Check running containers
docker ps

# Check GPU usage on host
nvidia-smi
```

---

## Production server

- **Host:** `user@oldgamepc.tail7c033b.ts.net` (Tailscale VPN)
- **Passwordless SSH:** configured (local `~/.ssh/id_rsa.pub` in remote `authorized_keys`)
- **GPUs:** 3× NVIDIA GTX 1060 6 GB (PCI bus order = nvidia-smi order when `CUDA_DEVICE_ORDER=PCI_BUS_ID`)
- **Project path:** `~/Projects/videocam-ai`
- **Output:** `~/Projects/videocam-ai/output/YYYY-MM-DD/`

**GPU assignments:**

| GPU (nvidia-smi) | Service | env var |
|---|---|---|
| GPU 0 | X11 / display (9 MiB) | — |
| GPU 1 | `cams_grabber` — YOLOv8s production | `CUDA_VISIBLE_DEVICES=1` |
| GPU 2 | `qa_service` — YOLOv8n QA verification | `CUDA_VISIBLE_DEVICES=2` + `CUDA_DEVICE_ORDER=PCI_BUS_ID` |

Note: `CUDA_VISIBLE_DEVICES=N` restricts the container to exactly 1 GPU (visible as device 0 inside).
Check `nvidia-smi` — if it shows the cams_grabber process on GPU 0 despite `CUDA_VISIBLE_DEVICES=1`,
this is a display artefact of CUDA's internal device ordering vs PCI bus order. PyTorch inside the
container correctly sees 1 device. The qa_service explicitly adds `CUDA_DEVICE_ORDER=PCI_BUS_ID`
to guarantee it lands on GPU 2.

---

## Services

### cams_grabber (`cams_grabber/main_ssh.py`)

Core capture and detection loop.

- Opens RTSP stream with **TCP transport** (avoids UDP packet-loss corruption)
- **Reader thread** runs continuously, stores only the latest frame in a single-slot buffer
  (eliminates FIFO buffer lag — main loop always gets a fresh frame)
- Main loop pulls fresh frames, validates quality (blur + gradient), runs `model.track()`
- Saves **raw clean frame** as primary file + annotated debug copy (`*_debug.jpg`)
- 20 s cooldown per tracking ID before saving another frame of the same object
- Requires 4 consecutive detections before saving (avoids false positives)
- Model: `yolov8s.pt` (small) — downloaded at build time, not committed to git

Key constants in `main_ssh.py`:
```
CONF_THRESHOLD = 0.60
MIN_PERSIST_FRAMES = 4
COOLDOWN_SECONDS = 20
BLUR_THRESHOLD = 30.0
```

### tg_bot (`tg_bot/bot.py`)

Sends new saved frames to Telegram.

- Polls `output/` every 5 s
- Sends newest-first; skips stale (>1 h old) and perceptually similar frames
- Automatically advances to the next dated folder when current folder is exhausted
- On first start: initializes to the most recent existing image without sending it
  (prevents flooding on restart)
- Commands: `/admin` (summary + latest image), `/state` (container health)
- Config: `tg_bot/.env` — `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID`

### sys_monitor (`sys_monitor/monitor.py`)

Monitors hardware health and sends Telegram alerts.

- Watches CPU temperature, RAM, GPU VRAM usage, disk space
- Alerts when thresholds are exceeded
- Reads `sys_monitor/ups_status.txt` for UPS state (written by `ups_monitor.sh`)
- Uses `gpus: all` + `NVIDIA_VISIBLE_DEVICES=all` to see all three GPUs

### web_viewer (`web_viewer/app.py`)

Flask-based web gallery for browsing saved frames.

- Port **8082**
- `/` — date-grouped gallery of all saved images
- `/admin` — summary dashboard (image counts, freshness, object stats)
- Mounts `output/` read-only
- Static file URL: `http://host:8082/YYYY-MM-DD/filename.jpg`

### qa_service (`qa_service/qa.py`)

Independent quality assurance service on GPU 2.

- Port **8083**
- Watches `output/` for new clean frames (skips `*_debug.jpg`)
- For each frame runs: blur score, gradient score, brightness, perceptual hash (per tracking ID),
  and YOLOv8n re-detection to verify the object is actually visible
- **PASS** = sharp image + object detected + vehicle moved since last capture
- **WARN** = object detected but vehicle hasn't moved (stationary parked car — expected)
- **FAIL** = blurry / corrupt / no object found in saved frame (real capture problem)
- Keeps up to 5000 results for 24 h time-window statistics
- **Tab 1 — Dashboard:** 5 quick-stat cards (10 min / 1 h / 6 h / 12 h / 24 h) + stats table
  (Total / Vehicles / People / Good / Stationary / Bad / Quality %)
- **Tab 2 — Gallery:** 5 images per page, newest first, prev/next navigation, jump-to-page
- Auto-refreshes stats every 30 s; gallery page 1 every 15 s

---

## Key files

| File | Purpose |
|---|---|
| `cams_grabber/main_ssh.py` | RTSP capture, reader thread, YOLO tracking, frame saving |
| `cams_grabber/snapshot_triage.py` | Offline batch triage tool (not used in live pipeline) |
| `tg_bot/bot.py` | Telegram bot — frame delivery + admin commands |
| `sys_monitor/monitor.py` | Hardware health monitor + Telegram alerts |
| `web_viewer/app.py` | Flask gallery — browse saved frames |
| `qa_service/qa.py` | QA watcher + Flask dashboard (two-tab SPA) |
| `docker-compose.yml` | All service definitions, volumes, GPU assignments |
| `tg_bot/.env` | Telegram secrets — never commit |
| `output/` | Saved frames — `YYYY-MM-DD/frame_TIMESTAMP_id{N}_{class}.jpg` |
| `docs/ARCHITECTURE.md` | Deep-dive: data flow, GPU assignments, frame lifecycle |
| `docs/QA_SERVICE_RUNBOOK.md` | QA service operating guide |

---

## Frame filename convention

```
output/2026-06-21/frame_2026-06-21 14:00:41_id9257_vehicle.jpg      ← clean primary
output/2026-06-21/frame_2026-06-21 14:00:41_id9257_vehicle_debug.jpg ← annotated copy
```

- `id9257` = YOLO tracking ID (monotonically increasing per session)
- `vehicle` = class bucket saved by cams_grabber
- QA service parses `_id(\d+)_` from the filename to track per-object hash state

---

## Conventions

- Python 3.10 (Ubuntu 22.04 base image). No type annotations required.
- All secrets in `tg_bot/.env`. Never commit real tokens.
- `output/` is gitignored. It is a mounted Docker volume shared across services.
- Model weights (`yolov8s.pt`, `yolov8n.pt`) are downloaded at Docker build time via
  `RUN python3 -c "from ultralytics import YOLO; YOLO('model.pt')"` — never committed to git.
- PyTorch version: `2.2.2+cu118` (CUDA 11.8). Pin `numpy<2` alongside it to avoid the
  `_ARRAY_API not found` incompatibility between torch and numpy 2.x.
- `CUDA_DEVICE_ORDER=PCI_BUS_ID` ensures CUDA index matches `nvidia-smi` index.
- Debug frames (`*_debug.jpg`) are annotated copies for human review — all automated
  services (tg_bot, qa_service) skip them.
- Do not add features outside the current service boundary without discussion.

---

## When unsure

- Check `nvidia-smi` on the production server before any GPU config change.
- If a service fails to start, check `docker logs <service> --tail 50` first.
- The `output/` directory is the shared contract between services — do not change its
  structure or naming convention without updating all consumers.
- For Telegram bot changes: test `/admin` and `/state` commands manually after deploy.
- Do not push directly to `main` with untested GPU or RTSP changes — they can silently
  drop frames or crash the capture loop.
