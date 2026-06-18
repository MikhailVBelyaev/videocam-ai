# TASK-002 Design: Improve Production Image Quality and Statistics

Job ID: 2026-06-17_172653_videocam-ai-improve-production-image-quality-and-statistics-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-18
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `cams_grabber/snapshot_triage.py` | Local-folder image triage (blur, low-light, duplicate detection, JSON/video output) | **Primary** — receives object detection, enhanced quality metrics, extended CSV/JSON |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None — separate pipeline; design intentionally avoids coupling to keep snapshot triage self-contained |
| `tg_bot/bot.py` | Telegram bot sending new detection frames from `output/` dated subfolders | **Minor** — must ignore new `triage_report.csv`, `triage_summary.json`, and `kept_timelapse.mp4` (already filters by image extension) |
| `sys_monitor/monitor.py` | System health monitoring | None |
| `web_viewer` (nginx:alpine) | Serves `output/` on port 8082 | **Minor** — new CSV/JSON/video files become browsable; no config change needed |

### 1.2 Module-Level Changes

**`cams_grabber/snapshot_triage.py`**

Current flow:
```
input_dir → sorted images → per-image scoring (blur, gradient, brightness)
  → keep/reject decision → CSV + rejected copies + JSON + kept/ + optional video
```

New flow:
```
input_dir → sorted images → per-image scoring (blur, gradient, brightness, contrast, overexposure)
  ├─→ optional object detection (car, person counts) per image
  → keep/reject decision
  ├─→ CSV report (existing + car_count, person_count, contrast_score, overexposure_score)
  ├─→ rejected/ copies (existing)
  ├─→ output/triage_summary.json (existing + object_counts, missing_expected_objects)
  ├─→ output/kept_timelapse.mp4 (existing, optional)
  └─→ kept/ copies (existing, optional)
```

New functions to add:
- `_detect_objects(image_bgr: np.ndarray, net: cv2.dnn.Net, class_names: list[str]) -> dict[str, int]` — runs MobileNet-SSD forward pass, counts detections by class
- `_load_detection_model(model_dir: Path) -> tuple[cv2.dnn.Net, list[str]]` — loads Caffe prototxt + caffemodel, returns net and class list
- `_compute_contrast_score(image_bgr: np.ndarray) -> float` — grayscale standard deviation
- `_compute_overexposure_score(image_bgr: np.ndarray) -> float` — percentage of pixels with value >= 250
- `_check_missing_expected(object_counts: dict[str, int], expected: list[str]) -> list[str]` — returns which expected objects are absent

Modified:
- `TriageConfig` — add `detect_objects: bool`, `model_dir: Path | None`, `expected_objects: list[str]`
- `run_triage()` — call new scoring and detection functions; append new columns to rows; include object stats in JSON
- `_build_parser()` — add `--detect-objects`, `--model-dir`, `--expected-objects`
- `_compute_statistics()` — extend JSON with `object_counts` per kept frame, `total_objects_by_type`, `missing_expected_objects`
- `_compute_quality_rank()` — update formula to include contrast and overexposure

**`tests/test_snapshot_triage.py`**

New test cases:
- Object detection schema: when `--detect-objects` is used, CSV contains `car_count` and `person_count`
- Object detection counts are non-negative integers and consistent with synthetic fixtures
- Missing expected object flag appears in JSON when expected objects are configured but absent
- Contrast score ordering (higher contrast = higher score)
- Overexposure score ordering (moderate overexposure flagged appropriately)
- Updated quality rank includes contrast and overexposure
- Graceful skip when model files are missing (warn + continue without object counts)
- Deterministic rerun with object detection enabled produces identical CSV and JSON

### 1.3 Data Flow Diagram

```
[Camera folder] ──┐
                  │
                  ▼
          snapshot_triage.py
                  │
     ┌────────────┼────────────────┬──────────────┬────────────────┐
     │            │                │              │                │
     ▼            ▼                ▼              ▼                ▼
triage_report.csv  rejected/   triage_summary.json  kept_timelapse.mp4  kept/
  (extended)       (existing)    (extended)          (existing)         (existing)
     │            │                │              │                │
     └────────────┴────────────────┴──────────────┴────────────────┘
                              │
                              ▼
                    output/ (shared Docker volume)
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
          tg_bot reads    web_viewer     human review
          for new frames  serves files   of kept/ + JSON + object stats
```

### 1.4 Interfaces

**New CLI interface:**

```
snapshot_triage.py <input_dir> \
  --output-dir output \
  --rejected-dir rejected \
  --kept-dir kept \
  --generate-video \
  --video-fps 5.0 \
  --blur-threshold 100.0 \
  --gradient-threshold 20.0 \
  --brightness-threshold 55.0 \
  --duplicate-distance-threshold 5 \
  --detect-objects \                  # NEW (default: False)
  --model-dir ./models \              # NEW (default: models/)
  --expected-objects car,person       # NEW (default: empty)
```

**Extended output contract (`triage_report.csv` columns):**

Existing columns plus:
- `car_count` (int, >= 0)
- `person_count` (int, >= 0)
- `contrast_score` (float, grayscale std)
- `overexposure_score` (float, percentage of near-white pixels)

**Extended JSON summary contract (`triage_summary.json`):**

```json
{
  "total_images": 150,
  "kept_images": 23,
  "rejected_by_reason": {
    "blur": 80,
    "low_light": 30,
    "duplicate": 15,
    "unreadable": 2
  },
  "score_distributions": {
    "blur_score":       {"min": 12.3, "max": 890.1, "mean": 145.6, "std": 120.4},
    "gradient_score":   {"min": 2.1,  "max": 95.3,  "mean": 35.2,  "std": 22.1},
    "brightness_score": {"min": 10.0, "max": 210.5, "mean": 85.3,  "std": 45.7},
    "contrast_score":   {"min": 5.0,  "max": 80.2,  "mean": 42.1,  "std": 15.3},
    "overexposure_score":{"min": 0.0, "max": 95.0,  "mean": 8.5,   "std": 12.1}
  },
  "total_objects_by_type": {
    "car": 45,
    "person": 12
  },
  "missing_expected_objects": [
    {"filename": "IMG_0001.jpg", "missing": ["car"]}
  ],
  "kept_frames": [
    {
      "filename": "IMG_0001.jpg",
      "quality_rank": 0.85,
      "object_counts": {"car": 1, "person": 0}
    }
  ]
}
```

**Updated quality_rank formula:**
```
quality_rank = normalize(blur_score)       * 0.30
             + normalize(gradient_score)   * 0.20
             + normalize(brightness_score) * 0.20
             + normalize(contrast_score)   * 0.20
             + normalize(overexposure_score)* 0.10
```
where `normalize(x) = (x - min) / (max - min)` per-score across all images.
Overexposure is weighted lower because moderate values are acceptable; the metric mainly penalizes extreme clipping. Higher is better. Ties broken by filename sort order.

---

## 2. Implementation Approach

### 2.1 Phased Approach

**Phase A (this increment): Object detection and statistics**
- Add `_detect_objects()`, `_load_detection_model()`
- Add `--detect-objects`, `--model-dir`, `--expected-objects` CLI flags
- Extend CSV with `car_count`, `person_count`
- Extend JSON with `total_objects_by_type`, `object_counts` per kept frame, `missing_expected_objects`
- Add focused tests for object detection integration
- Document model download location in runbook

**Phase B (follow-up): Enhanced image quality metrics**
- Add `_compute_contrast_score()` and `_compute_overexposure_score()`
- Extend CSV with `contrast_score` and `overexposure_score`
- Extend JSON score distributions
- Update `quality_rank` formula to include new metrics
- Add focused tests for contrast and overexposure behavior

**Rationale**: Phase A is the highest-value addition (object counting) and introduces a new external dependency (model files). Phase B is self-contained NumPy/OpenCV math with no new dependencies. Splitting them keeps each session reviewable and avoids conflating model-setup issues with metric-tuning issues.

### 2.2 Alternative: Single Increment

Implement object detection + enhanced quality metrics in one session.

**Pros**: One review cycle, faster delivery.
**Cons**: Larger diff; model download issues could delay metric work; harder to isolate test failures.

**Recommendation**: Phased approach. Object detection is the riskiest new capability; quality metrics are low-risk and can follow quickly.

---

## 3. Key Tradeoffs

### 3.1 Object Detection Model Choice

| Approach | Pros | Cons |
|----------|------|------|
| YOLOv8 via `ultralytics` (used in `main_ssh.py`) | Best accuracy, same model as real-time pipeline | Heavy dependency (~100MB+), not in `requirements-dev.txt`, slower per-image CPU inference |
| OpenCV DNN + MobileNet-SSD Caffe | Lightweight (~23MB model), no new Python deps, fast on CPU | Lower accuracy than YOLOv8, requires downloading model files |
| Haar cascades + HOGDescriptor | No model files needed (Haar XMLs bundled) | Very poor accuracy for cars; HOG only detects people |
| OpenCV DNN + ONNX YOLOv5s | Good accuracy, single file | Larger model (~27MB), more complex NMS post-processing |

**Decision**: MobileNet-SSD Caffe via OpenCV DNN. It is the sweet spot for a local-folder batch pipeline: no new pip dependencies, reasonable accuracy for car/person counting, fast enough for batch processing, and the model files can be downloaded once and reused.

**Model files required:**
- `MobileNetSSD_deploy.prototxt` (~30 KB)
- `MobileNetSSD_deploy.caffemodel` (~23 MB)
- Standard COCO class list: `background`, `aeroplane`, `bicycle`, `bird`, `boat`, `bottle`, `bus`, `car`, `cat`, `chair`, `cow`, `diningtable`, `dog`, `horse`, `motorbike`, `person`, `pottedplant`, `sheep`, `sofa`, `train`, `tvmonitor`

The design exposes only `car` and `person` counts by default (plus `vehicle` which maps `bus` → `vehicle`). Other classes are counted in `object_counts` but not given dedicated CSV columns.

### 3.2 Model File Distribution

| Approach | Pros | Cons |
|----------|------|------|
| Check into repo | Always available, versioned | Bloated repo, ~23 MB binary |
| Download on first run | No repo bloat | Requires internet, adds runtime latency, failure mode if offline |
| Expect at `--model-dir` | Clean separation, no bloat | Human must download and place files |

**Decision**: Expect at `--model-dir` (default `models/`), with clear runbook instructions for downloading from the OpenCV GitHub samples repository. This mirrors the pattern used by many OpenCV DNN tutorials and avoids repo bloat.

### 3.3 Contrast and Overexposure Metrics

| Metric | Computation | Rejection Use |
|--------|-------------|---------------|
| `contrast_score` | `np.std(gray)` | Higher is better; no hard rejection threshold by default (informational) |
| `overexposure_score` | `np.mean(gray >= 250) * 100` | Percentage of clipped pixels; optional `--overexposure-threshold` for future rejection rule |

**Decision**: Both are informational by default (no automatic rejection). They feed into `quality_rank` so reviewers see them in ranking. A future increment can add `--overexposure-threshold` for hard rejection if production data shows value.

### 3.4 Scope Relationship to Existing Increments

- **TASK-003 (gradient blur)**: Already accepted; this design builds on top of it.
- **TASK-004/005 (JSON/video/kept-dir)**: Already implemented; this design extends the JSON and CSV schemas additively.
- **Job ID 2026-06-17_173502**: Superseded by the TASK-004/005 implementation. This new design addresses the original 2026-06-17_172653 scope with object detection now explicitly included.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `cv2.dnn` | In `opencv-python-headless` | Object detection inference | Low — DNN module is bundled |
| MobileNet-SSD model files | Not in repo | Object detection weights | Medium — human must download once |
| `numpy` | In `requirements-dev.txt` | Contrast/overexposure math | None |
| `json` / `csv` / `shutil` | stdlib | Extended outputs | None |
| `ultralytics` | Used in `main_ssh.py` only | Not used here | None — deliberately decoupled |

No new Python package dependencies are required for either phase.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Model files missing at runtime | Medium | Graceful fallback: warn and continue without object counts; do not fail the triage run |
| MobileNet-SSD false positives/negatives | Medium | Document accuracy limitations; counts are advisory, not authoritative; YOLOv8 upgrade is a future option |
| CSV schema break downstream consumers | Low | New columns are additive at the end; existing parsers that read by index may break — document column order explicitly |
| Performance regression on large folders | Low | MobileNet-SSD inference is fast (~50-100 ms per image on CPU); document expected throughput |
| Overlap with existing working-tree changes | Medium | Verify TASK-004/005 are committed before implementation; base new work on clean `main` |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `cams_grabber/snapshot_triage.py` | Modify | Add detection + quality functions, extend TriageConfig, extend CLI, extend CSV/JSON output |
| `tests/test_snapshot_triage.py` | Modify | Add 6-8 new test cases for object detection and quality metrics |
| `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` | Modify | Document new CLI flags, model setup, CSV columns, JSON fields, accuracy notes |
| `README.md` | Modify | Add new CLI flags and model setup instructions |
| `requirements-dev.txt` | No change | Existing deps suffice |
| `.gitignore` | Modify | Add `models/` directory to ignore downloaded model files |

---

## 7. Validation Plan

1. `python3 -m py_compile cams_grabber/snapshot_triage.py` — syntax check
2. `python3 -m unittest -v tests/test_snapshot_triage.py` — full test suite
3. Manual run with sample images and downloaded model files: verify CSV columns, JSON schema, and object counts
4. Missing model file test: verify graceful warning and continued execution
5. Deterministic rerun: diff CSV and JSON outputs between two identical runs
6. Edge cases: empty input dir, all-rejected input, single-image input, no detections in any image
