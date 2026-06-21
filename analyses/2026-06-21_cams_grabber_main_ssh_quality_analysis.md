# Quality Analysis — `cams_grabber/main_ssh.py`

**Date:** 2026-06-21  
**Model:** Claude Opus 4.8  
**Module analysed:** `cams_grabber/main_ssh.py`  
**Data source:** Live QA service at port 8083 (96 frames, last 1 hour)

---

## Live QA snapshot

| Window | Total | Vehicles | People | PASS | WARN | FAIL | Rate |
|---|---|---|---|---|---|---|---|
| 10 min | 43 | 43 | 3 | 16 | 27 | 0 | 37% |
| 1 h | 96 | 93 | 6 | 35 | 58 | 3 | 36% |

**FAIL frames (all 3 same root cause):**

| File | blur | grad | bright | Objects | Issues |
|---|---|---|---|---|---|
| `frame_2026-06-21 14:16:47_id9906_vehicle.jpg` | 1406 | 183 | 95 | none | no target object visible, Δhash=0 |
| `frame_2026-06-21 14:17:47_id9906_vehicle.jpg` | 1423 | 186 | 97 | none | no target object visible, Δhash=1 |
| `frame_2026-06-21 14:20:28_id9906_vehicle.jpg` | 1411 | 184 | 95 | none | no target object visible, Δhash=0 |

Key observation: image quality is excellent (blur 1400+). QA's yolov8n at conf ≥ 0.35 finds zero objects. Production yolov8s at conf ≥ 0.60 triggered. This is a ghost/phantom detection.

---

## Findings ranked by impact

### 1. Ghost detections cause all FAILs — Fix A + B + C

**Root cause:** id9906 is a phantom tracking ID that ByteTrack kept alive on a static background patch (reflection, shadow, or a car that left frame). The save is gated only on the object's own cooldown timer. When cooldown expires, the next frame where yolov8s emits any box labelled id9906 — even conf=0.60 on a texture artifact — writes a full raw frame to disk. QA's independent yolov8n then finds nothing because the object was never really there.

Three compounding issues:
- `detection_buffer[obj_id]` only resets on save (line 229), so persistence credit accumulates across non-consecutive detections over many seconds — a flicker that hits threshold on 4 sparse frames counts as "4 consecutive frames"
- No minimum box area check: phantom detections on background texture produce tiny boxes that still trigger saves
- `CONF_THRESHOLD = 0.60` is used for both tracking AND saving — marginal detections trigger disk writes

**Fixes:**

**Fix A** — Reset `detection_buffer[obj_id]` to 0 for every ID absent from the current frame (after the box loop). Currently it only resets on save, allowing ghost credit to accumulate.

**Fix B** — Add minimum box area gate: reject boxes covering less than 0.3% of frame area. Phantom detections on background are typically tiny.

**Fix C** — Add `SAVE_CONF_THRESHOLD = 0.70` checked at the actual `cv2.imwrite` call. Track at 0.60 (keeps ByteTrack smooth) but only persist to disk at 0.70 (eliminates marginal saves).

**Expected impact:** FAIL rate → ~0. These are the only true bad frames.

---

### 2. `object_last_seen` grows unbounded — memory leak + correctness bug (Fix I)

**Root cause:** `to_remove` is computed (line 237–244) but **never applied to `object_last_seen`** or `detection_buffer`. The code only filters `prev_active` (which is never used in any decision). Stale object entries from objects that left the frame hours ago remain in memory forever and participate in the IoU duplicate scan on every frame.

**Impact:** (a) memory grows without bound on long-running process, (b) IoU cross-check degrades as it scans hundreds of stale boxes.

**Fix I** — After computing `to_remove`, apply it:
```python
for obj_id in to_remove:
    object_last_seen.pop(obj_id, None)
    detection_buffer.pop(obj_id, None)
    _last_save_hash.pop(obj_id, None)
```

---

### 3. 60% WARN rate — stationary recaptures (Fix D)

**Root cause:** `COOLDOWN_SECONDS = 20` causes every tracked parked vehicle to save a frame every 20 seconds, regardless of whether the scene changed. A car parked for 1 hour generates ~180 near-identical frames.

**Fix D** — Per-ID perceptual hash comparison before saving. Store the phash of the last saved frame per tracking ID in `_last_save_hash: dict`. Before writing to disk, compare the current frame's phash against the stored one. If distance ≤ 5 (same threshold QA uses), skip the save and update position/cooldown without writing.

**Expected impact:** parked car → 1 save on arrival, then no more until it moves. WARN rate drops from 60% to near zero. Disk usage drops significantly. Telegram noise drops.

---

### 4. No brightness gate in production (Fix G)

**Root cause:** `_is_frame_valid()` checks blur and gradient but not brightness. QA flags frames below 15 or above 245 mean grayscale. Night-time, overexposed, or IR-washout frames pass production's gate and get saved, then FAIL at QA.

**Fix G** — Add brightness check to `_is_frame_valid()` matching QA's thresholds:
```python
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
brightness = float(np.mean(gray))
if brightness < BRIGHTNESS_MIN or brightness > BRIGHTNESS_MAX:
    return False
```

---

### 5. Frame skips under GPU load — missed fast-moving objects (Fix H)

**Root cause:** The single-slot buffer means if yolov8s inference takes longer than the camera's inter-frame interval (~33ms at 30fps), the reader overwrites `_latest_slot` while the main thread is still doing inference. A fast-moving person crossing the frame may never accumulate `MIN_PERSIST_FRAMES = 4` consecutive detections because the main loop only sees every Nth frame.

**Fix H (measure first):** Log when `seq_id - _last_consumed_seq > 1` so the skip rate is visible. Also add `imgsz=640` to `model.track()` — yolov8s at 640px is significantly faster than the default 1280px on a GTX 1060 with no meaningful accuracy loss for this use case.

---

## Summary table

| ID | Fix | Impact | Effort |
|---|---|---|---|
| Fix A | Reset detection_buffer on absence | Eliminates ghost detections | Low |
| Fix B | Minimum box area check | Eliminates phantom saves | Low |
| Fix C | SAVE_CONF_THRESHOLD=0.70 | Eliminates marginal saves | Low |
| Fix I | Apply to_remove to object_last_seen | Fixes memory leak + IoU correctness | Low |
| Fix D | Per-ID phash gate before save | Eliminates 60% WARN noise, saves disk | Medium |
| Fix G | Brightness gate in _is_frame_valid | Closes gap between prod and QA filters | Low |
| Fix H | Log skips + imgsz=640 | Reduces missed fast-moving objects | Low |

All fixes implemented in: `cams_grabber/main_ssh.py` (2026-06-21)
