# QA Service Runbook

## Purpose

The `qa_service` independently re-validates every frame saved by `cams_grabber`.
It does not affect the production capture pipeline — it only reads files and reports.

Dashboard: `http://oldgamepc.tail7c033b.ts.net:8083`

---

## Dashboard tabs

### Tab 1 — Dashboard

**Summary cards (top row):** one card per time window (10 min / 1 h / 6 h / 12 h / 24 h).
Each card shows:
- Total frames processed in that window
- Vehicle count (frames containing car / truck / bus)
- People count (frames containing person)
- Pills: good (PASS) / same (WARN) / bad (FAIL)
- Color bar: green ≥ 70% / yellow ≥ 40% / red < 40%

**Stats table:** same windows in rows with columns:

| Column | Meaning |
|---|---|
| Period | Time window |
| Total frames | All frames QA processed |
| 🚗 Vehicles | Frames where QA found a car/truck/bus |
| 🚶 People | Frames where QA found a person |
| ✅ Good | PASS — sharp image, object visible, vehicle moved |
| ⚠️ Stationary | WARN — object visible but vehicle hasn't moved |
| ❌ Bad | FAIL — quality problem or no object found |
| Quality | PASS % (green ≥ 70%, yellow ≥ 40%, red < 40%) |

Stats refresh automatically every 30 seconds.

### Tab 2 — Gallery

5 images per page, newest first.

- **Prev / Next** buttons at top and bottom
- **Go to page N** input for direct navigation
- Page 1 auto-refreshes every 15 s while you are on it
- Other pages stay stable while you browse
- Click any image → full-size lightbox overlay

Each image card shows:
- Tracking ID and capture timestamp
- Status badge: PASS / WARN / FAIL
- Quality metrics: Blur score / Gradient score / Brightness
- Vehicle movement: "moved (Δ8)" or "stationary (Δ0)"
- Detected objects with confidence %
- Issues list (if any)

---

## Status meanings

### PASS
The frame is good. Object is clearly visible, image is sharp, and the vehicle has
moved (or it is the first capture of this tracking ID).

### WARN — "no change since last capture (Δhash=0)"
The image is fine but the vehicle hasn't moved since the previous save of the same
tracking ID. This is **normal and expected** for parked or slow-moving vehicles:
`cams_grabber` saves a frame every 20 s cooldown cycle, so a parked car generates
repeated near-identical frames. WARN is informational, not an error.

### FAIL
A real quality problem. One or more of:
- **"no target object visible"** — YOLOv8n could not find any car / truck / bus / person
  in the frame. The production detector triggered, but the saved image contains nothing
  recognisable. This may indicate a false-positive detection in cams_grabber, or a
  partially-decoded H.264 frame that YOLO couldn't interpret.
- **"blurry (blur=12)"** — Laplacian variance below 30. The frame is too blurry to be useful.
- **"corrupt/flat (gradient=1.2)"** — Gradient variance below 5. Likely a malformed or
  partially decoded frame (common with UDP RTSP; less common with TCP).
- **"unreadable image"** — OpenCV could not open the file at all.

---

## Expected quality rates

With normal daytime operation:
- PASS rate 40–60% is healthy (roughly half of saves are first captures, half are stationary recaptures)
- High WARN rate (> 50%) is normal — means the same vehicles are being watched repeatedly
- FAIL rate > 5% warrants investigation

Common causes of FAIL spikes:
- Camera reboot / power loss → H.264 decode errors until keyframe re-established
- Poor lighting (night without IR, or overexposed in direct sun)
- Camera motion blur (heavy wind, vibration)

---

## API endpoints

```
GET http://host:8083/api/stats
```
Returns time-window statistics JSON:
```json
{
  "windows": [
    { "minutes": 10, "total": 12, "vehicles": 10, "people": 2,
      "passes": 5, "warns": 6, "fails": 1, "rate": 42 },
    ...
  ],
  "total": 450,
  "pass_count": 210
}
```

```
GET http://host:8083/api/gallery?page=1
```
Returns 5 items per page, newest first:
```json
{
  "items": [ { "filename": "...", "status": "PASS", "detections": [...], ... } ],
  "page": 1,
  "total_pages": 90,
  "total": 450
}
```

```
GET http://host:8083/img/2026-06-21/frame_2026-06-21%2014:00:41_id9257_vehicle.jpg
```
Serves the image file directly from the `output/` volume.

---

## Configuration (in `qa_service/qa.py`)

| Constant | Default | Meaning |
|---|---|---|
| `BLUR_THRESHOLD` | 30.0 | Laplacian variance below this → FAIL |
| `GRADIENT_THRESHOLD` | 5.0 | Gradient variance below this → FAIL |
| `BRIGHTNESS_MIN` | 15.0 | Mean grayscale below this → FAIL |
| `BRIGHTNESS_MAX` | 245.0 | Mean grayscale above this → FAIL |
| `SAME_ID_DUP_THRESHOLD` | 5 | Phash distance ≤ this for same ID → WARN (stationary) |
| `CONF_THRESHOLD` | 0.35 | YOLOv8n confidence threshold for QA detection |
| `POLL_INTERVAL` | 2.0 s | How often to scan `output/` for new files |
| `PRELOAD_RECENT` | 50 | Frames pre-seeded from disk on startup |

---

## Troubleshooting

**Dashboard shows "Loading…" and never updates**
- Check container is running: `docker ps --filter name=qa_service`
- Check logs: `docker logs qa_service --tail 30`
- Check port 8083 is reachable from your browser (Tailscale VPN must be connected)

**All results show FAIL with "no target object visible"**
- The production model (cams_grabber, yolov8s) is detecting at conf ≥ 0.60
- The QA model (yolov8n) checks at conf ≥ 0.35 — a lower bar
- If yolov8n can't find objects at 0.35, the captures may be genuinely bad
- Check actual images in the gallery; look for empty/dark/blurry frames

**"Numpy is not available" errors**
- torch 2.2.2+cu118 requires numpy < 2.0
- Ensure `requirements.txt` has `numpy<2` — if missing, rebuild: `docker compose up -d --build qa_service`

**Container exits immediately on startup**
- Run `docker logs qa_service` to see the Python traceback
- Most common: import error due to missing package, or GPU not accessible
- Check GPU: `ssh user@oldgamepc.tail7c033b.ts.net "nvidia-smi"`

**Stats table shows zero for all windows**
- The service just started and hasn't processed enough frames yet (PRELOAD_RECENT=50 seeds on startup)
- Wait 2–5 minutes for live frames to arrive
- Or check: `curl http://localhost:8083/api/stats` from the server

**High memory usage**
- `stats_log` holds up to 5000 results in memory (~5 MB) — this is safe
- If container memory grows beyond expected, restart: `docker compose restart qa_service`

---

## Restart / rebuild

```bash
# Restart without rebuild (fast — keeps image, just restarts process)
ssh user@oldgamepc.tail7c033b.ts.net "docker compose restart qa_service"

# Rebuild and restart (after code changes)
ssh user@oldgamepc.tail7c033b.ts.net "cd ~/Projects/videocam-ai && docker compose up -d --build qa_service"

# Check logs after restart
ssh user@oldgamepc.tail7c033b.ts.net "docker logs qa_service --tail 30"
```
