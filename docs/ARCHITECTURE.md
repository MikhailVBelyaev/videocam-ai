# Architecture

Last updated: 2026-06-21

## System overview

```
IP Camera (RTSP H.264, 1920×1080)
        │
        │ TCP stream (avoids UDP packet loss / composite frames)
        ▼
┌─────────────────────────────────────────────────┐
│  cams_grabber  (GPU 1 — YOLOv8s)               │
│                                                  │
│  Reader thread ──► single-slot buffer            │
│        │          (always fresh frame)           │
│        ▼                                         │
│  Quality gate (blur + gradient)                  │
│        │                                         │
│        ▼                                         │
│  model.track() ──► persist 4 frames              │
│        │           cooldown 20 s / ID            │
│        ▼                                         │
│  Save raw frame  +  debug annotated copy         │
└──────────────────────┬──────────────────────────┘
                       │  output/YYYY-MM-DD/*.jpg
           ┌───────────┼───────────┬──────────────┐
           ▼           ▼           ▼              ▼
      ┌─────────┐ ┌──────────┐ ┌───────┐ ┌────────────┐
      │ tg_bot  │ │web_viewer│ │  qa_  │ │sys_monitor │
      │(no GPU) │ │(no GPU)  │ │service│ │(all GPUs)  │
      │port —   │ │port 8082 │ │GPU 2  │ │port —      │
      └────┬────┘ └──────────┘ │8083   │ └────────────┘
           │                   └───────┘
           ▼
      Telegram channel
```

## Services

### cams_grabber

**Role:** sole producer of frames. All other services are consumers.

**Two-thread design:**
```
Reader thread                    Main thread
─────────────                    ───────────
cap.read() loop                  while True:
  if ret:                          slot = _latest_slot
    with _frame_lock:              if slot is None or seq == _last_seq:
      _frame_seq += 1                sleep(0.01); continue
      _latest_slot = (seq,          seq, frame, ts = slot
                      frame, ts)    if not _is_frame_valid(frame): continue
  else:                             results = model.track(frame, ...)
    reconnect w/ backoff            if detection criteria met: save
```

The reader thread discards all but the latest frame. The main thread never
processes a stale frame from the FIFO buffer — a key fix for the "garbage image"
production problem.

**Frame validation before YOLO:**
- `_compute_blur_score()` — Laplacian variance, threshold 30.0
- `_compute_gradient_score()` — gradient magnitude variance, threshold 5.0
- Frames failing either check are skipped (likely corrupt / H.264 decode artefact)

**Detection persistence:**
- Object must appear in `MIN_PERSIST_FRAMES = 4` consecutive frames before saving
- Per-ID cooldown `COOLDOWN_SECONDS = 20` prevents repeated saves of same object

**Output files per event:**
```
frame_2026-06-21 14:00:41_id9257_vehicle.jpg        ← cv2.imwrite(frame)   raw
frame_2026-06-21 14:00:41_id9257_vehicle_debug.jpg  ← cv2.imwrite(annotated) debug
```

### tg_bot

**Role:** deliver new captures to Telegram, provide admin insight.

**Send loop (every 5 s):**
1. Read `.last_sent_file` → know current folder + last sent image
2. List current folder images, sort by mtime (newest first within unsent window)
3. Filter: skip stale (> `MAX_IMAGE_AGE_SECONDS`), skip `*_debug.jpg`
4. Skip perceptually similar to last sent (phash distance ≤ `IMAGE_SIMILARITY_THRESHOLD`)
5. Send up to `MAX_IMAGES_PER_ITERATION` per tick
6. Advance to next folder if current folder yields 0 sends and is not newest

**State file** `output/.last_sent_file`:
```
2026-06-21/\n           ← current folder
```
On first start (file missing): initialise to newest image without sending.

### web_viewer

**Role:** human-readable gallery for browsing and reviewing saved frames.

Flask app (port 5000 inside container, mapped to host 8082):
- `/` — lists `output/YYYY-MM-DD/` folders with image thumbnails
- `/admin` — JSON summary dashboard, reads `output/triage_summary.json` if present
- `/YYYY-MM-DD/filename.jpg` — direct static file access (proxied through Flask)

Mounts `output/` read-only. No GPU. No database.

### qa_service

**Role:** independent quality auditor. Never modifies files, only reads and reports.

**Watcher loop (every 2 s):**
1. Scan `output/YYYY-MM-DD/` for new files not in `seen` set
2. Skip `*_debug.jpg` (annotated copies, not originals)
3. For each new frame: compute quality metrics + run YOLOv8n
4. Compare phash against last phash for the same tracking ID
5. Classify: PASS / WARN / FAIL
6. Append to `stats_log` (deque, maxlen 5000)

**Quality checks:**

| Check | Method | Threshold |
|---|---|---|
| Blur | Laplacian variance | ≥ 30.0 |
| Gradient | Gradient magnitude variance | ≥ 5.0 |
| Brightness | Mean grayscale | 15–245 |
| Object presence | YOLOv8n detection | conf ≥ 0.35 |
| Per-ID change | Perceptual hash distance vs same ID | > 5 = moved |

**Status logic:**
```
quality_fail = not has_object OR blur < 30 OR gradient < 5
if quality_fail → FAIL
elif any issue → WARN   (typically: "no change since last capture")
else → PASS
```

**WARN on stationary cars** is expected and normal: the cams_grabber re-saves the
same parked vehicle every 20 s cooldown cycle. The per-ID phash tracks when the
vehicle itself moves, so WARN means "still there, unchanged" — not an error.

**Flask endpoints:**
- `GET /` — two-tab SPA (Dashboard + Gallery)
- `GET /api/stats` — time-window statistics JSON
- `GET /api/gallery?page=N` — paginated gallery (5 per page, newest first)
- `GET /img/<rel_path>` — proxy image file from `output/`

### sys_monitor

**Role:** hardware health monitoring and alert delivery.

Watches: CPU temperature, RAM usage, GPU VRAM (all 3), disk space.
Sends Telegram alerts when thresholds are exceeded.
Reads `sys_monitor/ups_status.txt` (written by host-side `ups_monitor.sh` via cron).
Uses `NVIDIA_VISIBLE_DEVICES=all` to see all three GPUs.

---

## GPU assignments

```
nvidia-smi index │ Service       │ CUDA env
─────────────────┼───────────────┼──────────────────────────────────────────────
GPU 0            │ X11 / desktop │ (no container)
GPU 1            │ cams_grabber  │ CUDA_VISIBLE_DEVICES=1
GPU 2            │ qa_service    │ CUDA_VISIBLE_DEVICES=2, CUDA_DEVICE_ORDER=PCI_BUS_ID
```

`CUDA_VISIBLE_DEVICES=N` makes the container's CUDA runtime see exactly 1 GPU
(reported as device 0 inside the container). Without `CUDA_DEVICE_ORDER=PCI_BUS_ID`,
CUDA's internal ordering may differ from `nvidia-smi`. The qa_service adds the
`PCI_BUS_ID` flag explicitly so its `CUDA_VISIBLE_DEVICES=2` reliably maps to
nvidia-smi GPU 2.

---

## Data flow

```
Camera ──RTSP/TCP──► cams_grabber ──writes──► output/YYYY-MM-DD/*.jpg
                                                    │
                    ┌───────────────────────────────┤ (shared Docker volume, read-only)
                    │                               │
                    ▼                               ▼
             tg_bot reads,                  qa_service reads,
             sends to Telegram              validates, updates stats_log
                                                    │
                                            web_viewer reads,
                                            serves gallery
```

The `output/` directory is the **only** shared contract between services.
Its structure must not change without updating all consumer services.

---

## Docker compose volume mounts

| Service | Mount | Mode |
|---|---|---|
| cams_grabber | `./output:/app/output` | rw |
| tg_bot | `./output:/app/output` | rw |
| web_viewer | `./output:/app/output` | ro |
| qa_service | `./output:/app/output` | ro |
| sys_monitor | `./output:/app/output` | rw |

---

## Frame lifecycle

```
1. Camera emits H.264 NAL units over RTSP/TCP
2. FFmpeg (via OpenCV CAP_FFMPEG) decodes to BGR frames
3. Reader thread stores latest frame in _latest_slot (discards older)
4. Main thread validates: blur ≥ 30 AND gradient ≥ 5
5. YOLOv8s tracks objects: car / truck / bus / person
6. If tracking ID held ≥ 4 consecutive frames AND cooldown expired:
   a. Save raw frame as .jpg (the "primary" file)
   b. Save annotated copy as _debug.jpg
7. tg_bot picks up primary .jpg within next 5 s tick, sends to Telegram
8. qa_service picks up primary .jpg within next 2 s poll:
   a. Re-validates quality
   b. Runs YOLOv8n to confirm object visible
   c. Records PASS / WARN / FAIL in stats_log
9. web_viewer serves primary .jpg on demand to browser
```

---

## Why two YOLO models?

| Aspect | cams_grabber (yolov8s) | qa_service (yolov8n) |
|---|---|---|
| Purpose | Production detection | Independent quality verification |
| Model size | Small (22 MB) | Nano (6 MB) |
| Accuracy | Higher — needed to correctly trigger saves | Lower — QA only needs to confirm object visible |
| GPU | GPU 1 (dedicated) | GPU 2 (dedicated) |
| Speed requirement | Real-time, continuous | Batch, 2 s poll |

Using a different model for QA means a FAIL result (no object found by QA) is a
genuine signal that the saved frame contains no recognisable object — not just a
repeat of what the production detector already said.

---

## Known limitations

- Single camera only. Adding a second camera requires a second `cams_grabber` instance
  with a different `RTSP_URL` and a separate output subfolder.
- The reader thread reconnects on stream loss (exponential backoff 1 s → 30 s) but
  does not alert — sys_monitor does not currently watch cams_grabber's connection state.
- `output/` grows unbounded. No automatic cleanup is implemented.
- qa_service stores up to 5000 results in memory. On restart the stats_log is re-seeded
  from the last 50 files on disk. History older than 50 frames is lost on restart.
