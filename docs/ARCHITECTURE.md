# Architecture

Last updated: 2026-06-22

## System overview

```
IP Camera (RTSP H.264, 1920×1080)
        │
        │ TCP stream (avoids UDP packet loss / composite frames)
        ▼
┌──────────────────────────────────────────────────────┐
│  cams_grabber_cam1  (GPU 1 — NVDEC + YOLOv8s)       │
│                                                       │
│  Reader thread                                        │
│    ffmpeg -hwaccel cuda -c:v h264_cuvid ──►           │
│    bgr24 pipe ──► single-slot buffer                  │
│        │          (H.264 decode on GPU via NVDEC)     │
│        ▼                                              │
│  GPU quality gate (PyTorch CUDA)                      │
│    Laplacian blur var + Sobel gradient var            │
│    + brightness — all on cuda:0                       │
│        │                                              │
│        ▼                                              │
│  model.track() ──► persist 4 frames                   │
│        │           cooldown 20 s / ID                 │
│        ▼                                              │
│  Save raw frame  +  debug annotated copy              │
└───────────────────────┬──────────────────────────────┘
                        │  output/cam1/YYYY-MM-DD/*.jpg
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

### cams_grabber_cam1

**Role:** sole producer of frames. All other services are consumers.
Runs once per camera; cam2/cam3 start identical containers via Docker Compose profiles.

**Two-thread design:**
```
Reader thread                       Main thread (capped at INFERENCE_FPS_MAX=8)
─────────────                       ─────────────────────────────────────────
ffmpeg subprocess:                  while True:
  -hwaccel cuda                       throttle to 8 fps
  -c:v h264_cuvid                     slot = _latest_slot
  NVDEC decodes H.264 on GPU          if slot is None or seq == _last_seq:
  pipe: raw bgr24 bytes                 sleep(0.005); continue
  np.frombuffer → numpy array         seq, frame, ts = slot
  store in _latest_slot               _is_frame_valid(frame)  ← GPU (PyTorch CUDA)
  reconnect w/ backoff                  if invalid: continue
                                      results = model.track(frame, ...)
                                      if detection criteria met: save
```

The reader thread discards all but the latest frame. The main thread never
processes a stale frame — a key fix for the "garbage image" production problem.

**Frame validation before YOLO (GPU):**
- Laplacian blur variance ≥ 30.0 — `F.conv2d` on `cuda:0`
- Sobel gradient magnitude variance ≥ 500.0 — `F.conv2d` on `cuda:0`
- Brightness (mean) 15–245 — `tensor.mean()` on `cuda:0`
- Frame is uploaded once (`torch.from_numpy(frame).cuda().float()`); all checks run on GPU

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
nvidia-smi index │ PCI bus   │ Service             │ Docker env
─────────────────┼───────────┼─────────────────────┼────────────────────────────────────────────────
GPU 0            │ 01:00.0   │ X11 / desktop       │ (no container)
GPU 1            │ 02:00.0   │ cams_grabber_cam1   │ NVIDIA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID
GPU 2            │ 03:00.0   │ qa_service          │ NVIDIA_VISIBLE_DEVICES=2, CUDA_DEVICE_ORDER=PCI_BUS_ID
```

**`NVIDIA_VISIBLE_DEVICES`** is the Docker NVIDIA runtime env var — it uses the same PCI bus
order as `nvidia-smi`. Use this (not `CUDA_VISIBLE_DEVICES`) to route containers to the right GPU.

`CUDA_DEVICE_ORDER=PCI_BUS_ID` is set as belt-and-suspenders inside the container so any
CUDA code that reads device indices sees the same order as `nvidia-smi`.

**`NVIDIA_DRIVER_CAPABILITIES=video,compute,utility`** is required on containers that use NVDEC.
Without `video`, the container toolkit does not inject `libnvcuvid.so.1` and `h264_cuvid` fails.

---

## Data flow

```
Camera ──RTSP/TCP──► cams_grabber_cam1 ──writes──► output/cam1/YYYY-MM-DD/*.jpg
                                                         │
                    ┌────────────────────────────────────┤ (shared Docker volume, read-only)
                    │                                    │
                    ▼                                    ▼
             tg_bot reads,                       qa_service reads,
             sends to Telegram                   validates, updates stats_log
                                                         │
                                                 web_viewer reads,
                                                 serves gallery
```

The `output/` directory is the **only** shared contract between services.
Its structure must not change without updating all consumer services.

**Multi-camera layout:** each camera writes to its own subdir.
Consumers discover cameras by listing non-date entries in `output/`:
```
output/
  cam1/
    2026-06-22/
      frame_*.jpg
    .last_sent_file   ← tg_bot cursor for cam1
  cam2/               ← populated when cam2 container runs
  .sysinfo.json       ← written by sys_monitor, read by tg_bot /state
```

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
2. ffmpeg subprocess (-hwaccel cuda -c:v h264_cuvid) decodes on GPU (NVDEC)
   → raw bgr24 bytes piped to Python → numpy array
3. Reader thread stores latest frame in _latest_slot (discards older)
4. Main thread (throttled to 8fps) validates on GPU (PyTorch CUDA):
   blur var ≥ 30, Sobel gradient var ≥ 500, brightness 15–245
5. YOLOv8s tracks objects: car / truck / bus / person
6. If tracking ID held ≥ 4 consecutive frames AND cooldown expired:
   a. Save raw frame as .jpg to output/cam1/YYYY-MM-DD/ (the "primary" file)
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

- Frames still cross CPU RAM on each inference tick (ffmpeg pipe → numpy). H.264 decode
  is on GPU (NVDEC) but pixels are downloaded to CPU before the next GPU upload for quality
  checks and YOLO. A GStreamer + NVMM pipeline would eliminate this CPU hop.
- The reader thread reconnects on stream loss (exponential backoff 1 s → 30 s) but does not
  alert — sys_monitor does not watch cams_grabber's connection state.
- `output/` grows unbounded. No automatic cleanup is implemented.
- qa_service stores up to 5000 results in memory. On restart stats_log is re-seeded from the
  last 50 files on disk. History older than 50 frames is lost on restart.
