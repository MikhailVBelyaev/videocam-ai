# TASK-002 Design: Production Media Quality & Object Statistics Pipeline

Job ID: 2026-06-17_173502_videocam-ai-build-production-media-quality-and-object-statis-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-18
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `cams_grabber/snapshot_triage.py` | Local-folder image triage (blur, low-light, duplicate detection) | **Primary** — receives 3 new outputs, 3 new CLI flags |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None — separate pipeline |
| `tg_bot/bot.py` | Telegram bot sending new detection frames from `output/` | **Minor** — must ignore new `triage_summary.json` and `kept_timelapse.mp4` (already filters by extension) |
| `sys_monitor/monitor.py` | System health monitoring | None |
| `web_viewer` (nginx:alpine) | Serves `output/` on port 8082 | **Minor** — new JSON/video files become browsable; no config change needed |
| `docker-compose.yml` | Orchestrates all 4 containers | None — `output/` volume already shared |

### 1.2 Module-Level Changes

**`cams_grabber/snapshot_triage.py`**

Current flow:
```
input_dir → sorted images → per-image scoring → keep/reject decision → CSV + rejected copies
```

New flow:
```
input_dir → sorted images → per-image scoring → keep/reject decision
  ├─→ CSV report (existing)
  ├─→ rejected/ copies (existing)
  ├─→ output/triage_summary.json (NEW)
  ├─→ output/kept_timelapse.mp4 (NEW, optional)
  └─→ kept/ copies (NEW, optional)
```

New functions to add:
- `_compute_statistics(rows: list[dict]) -> dict` — aggregates score distributions and quality ranks
- `_write_summary_json(output_dir: Path, stats: dict) -> None` — serialises to `triage_summary.json`
- `_generate_timelapse(kept_paths: list[Path], output_dir: Path, fps: float) -> Path | None` — writes MP4
- `_copy_kept_frames(kept_rows: list[dict], input_dir: Path, kept_dir: Path) -> None` — copies kept images

Modified:
- `TriageConfig` — add `generate_video: bool`, `video_fps: float`, `kept_dir: Path | None`
- `run_triage()` — call new functions after CSV write
- `_build_parser()` — add `--generate-video`, `--video-fps`, `--kept-dir`

**`tests/test_snapshot_triage.py`**

New test cases:
- JSON output schema completeness (all required keys present, correct types)
- Timelapse generation: file exists, frame count matches kept images, correct order
- Kept directory: exact copy of kept frames, no rejected frames
- Graceful skip when no frames kept (no video, empty kept dir)
- Deterministic rerun produces identical JSON

### 1.3 Data Flow Diagram

```
[Camera folder] ──┐
                  │
                  ▼
          snapshot_triage.py
                  │
     ┌────────────┼────────────────┬──────────────┐
     │            │                │              │
     ▼            ▼                ▼              ▼
triage_report.csv  rejected/   triage_summary.json  kept_timelapse.mp4  kept/
     │            │                │              │              │
     │            │                │              │              │
     └────────────┴────────────────┴──────────────┴──────────────┘
                              │
                              ▼
                    output/ (shared Docker volume)
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
          tg_bot reads    web_viewer     human review
          for new frames  serves files   of kept/ + JSON
```

### 1.4 Interfaces

**New CLI interface:**

```
snapshot_triage.py <input_dir> \
  --output-dir output \
  --rejected-dir rejected \
  --kept-dir kept \                    # NEW (default: None = skip)
  --generate-video \                   # NEW (default: False)
  --video-fps 5.0 \                    # NEW (default: 5.0)
  --blur-threshold 100.0 \
  --gradient-threshold 20.0 \
  --brightness-threshold 55.0 \
  --duplicate-distance-threshold 5
```

**New output contract (`triage_summary.json`):**

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
    "brightness_score": {"min": 10.0, "max": 210.5, "mean": 85.3,  "std": 45.7}
  },
  "kept_frames": [
    {"filename": "IMG_0001.jpg", "quality_rank": 0.85},
    {"filename": "IMG_0007.jpg", "quality_rank": 0.72}
  ]
}
```

**quality_rank formula:**
```
quality_rank = normalize(blur_score) * 0.4
             + normalize(gradient_score) * 0.3
             + normalize(brightness_score) * 0.3
```
where `normalize(x) = (x - min) / (max - min)` per-score across all images.
Higher is better. Ties broken by filename sort order (stable with CSV).

---

## 2. Implementation Approach

### 2.1 Phased Approach

**Phase A (this increment): Statistics + JSON + kept directory**
- Add `_compute_statistics()`, `_write_summary_json()`, `_copy_kept_frames()`
- Add `--kept-dir` CLI flag
- Add focused tests for JSON schema and kept directory
- No video generation yet — lowest risk, highest value

**Phase B (follow-up): Timelapse video**
- Add `_generate_timelapse()` with codec fallback chain (`mp4v` → `avc1` → `XVID`)
- Add `--generate-video` and `--video-fps` flags
- Add video-specific tests
- Document codec availability in runbook

**Rationale**: Splitting the increment reduces risk. Phase A requires no new dependencies and is fully testable with the standard library. Phase B depends on OpenCV codec availability which varies by host (see Risk 1).

### 2.2 Alternative: Single Increment

Implement all three outputs (JSON + video + kept-dir) in one Codex session.

**Pros**: One review cycle, faster overall delivery.
**Cons**: Larger diff, harder to isolate failures, codec issues could block the entire increment.

**Recommendation**: Use the phased approach if human review cycles are available. Use single increment if speed is prioritized and the target host has confirmed codec support.

---

## 3. Key Tradeoffs

### 3.1 Video Codec Strategy

| Approach | Pros | Cons |
|----------|------|------|
| `mp4v` only | Simple, widely available | May fail on minimal/headless OpenCV builds |
| Fallback chain (`mp4v` → `avc1` → `XVID`) | Resilient across hosts | More code paths to test, different output file sizes |
| AVI fallback | Almost always available | Larger files, no web playback |

**Decision**: Fallback chain (`mp4v` → `avc1` → `XVID` → warn + skip). Document in runbook.

### 3.2 Video Frame Resizing

| Approach | Pros | Cons |
|----------|------|------|
| Use first kept frame dimensions, resize others | Simple, no cropping | Aspect ratio distortion on mixed sizes |
| Letterbox to first frame | Preserves aspect ratio | Black bars, slightly more complex |
| Fixed output size (e.g., 1920x1080) | Consistent output | Upscaling artifacts, crop decisions |

**Decision**: Use first kept frame dimensions + resize for Phase B. Document limitation. Letterboxing can be a future enhancement.

### 3.3 Quality Rank Computation

| Approach | Pros | Cons |
|----------|------|------|
| Min-max normalization per run | Simple, self-contained | Rank values change between runs with different input sets |
| Fixed reference thresholds | Comparable across runs | Requires calibration, brittle to camera changes |
| Per-image z-score against running stats | Statistically meaningful | Requires persistent state (breaks stateless design) |

**Decision**: Min-max normalization per run. It's self-contained, requires no external state, and is sufficient for intra-run ranking (the stated use case: "review the best frames first").

### 3.4 Scope Consolidation

Two overlapping scopes exist:
- **Job ID 2026-06-17_172653** (`PRODUCTION_VIDEO_STATISTICS_SCOPE.md`): JSON + video
- **Job ID 2026-06-17_173502** (`PRODUCTION_MEDIA_QUALITY_OBJECT_STATISTICS_SCOPE.md`): JSON + video + kept-dir

**Decision**: Consolidate into one implementation increment using the broader scope (2026-06-17_173502) which subsumes the narrower one. Close 2026-06-17_172653 as superseded.

### 3.5 Object Detection / Object Statistics

The original request asked for car/person counting and "missing expected object" classification. The TASK-001 scope explicitly excludes object detection under project guardrails.

**Decision for this increment**: Exclude object detection from implementation scope.

**Recommended future interface**: When object detection is approved in a future increment, the statistics module should accept an optional `object_counts: dict[str, int]` field per image, enabling:
- Per-run object type frequency counts
- Correlation between object presence and quality scores
- "Missing expected object" flagging against a configurable expectation list

This keeps the statistics module extensible without coupling it to YOLO or any specific detection model.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `json` (stdlib) | Available | JSON output | None |
| `shutil.copy2` (stdlib) | Available | Kept frame copies | None |
| `numpy` | In requirements-dev.txt | Score distributions (min/max/mean/std) | None |
| `cv2.VideoWriter` | In cams_grabber/requirements.txt | Timelapse video | Medium — codec availability |
| `opencv-python-headless` | In requirements-dev.txt | Video generation in test env | Low — mp4v may not be bundled |

No new package dependencies are required for Phase A. Phase B uses existing `opencv-python` which already bundles codec support on the production host.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| TASK-003 gradient blur changes are in-flight on `snapshot_triage.py` | Medium | Base implementation on accepted TASK-003 state or rebase after acceptance |
| OpenCV codec unavailable on test host | Medium | Test with `cv2.VideoWriter_fourcc(*"mp4v")`; if None, skip video test and document |
| Mixed image sizes in video | Low | Document behavior; letterboxing is a future enhancement |
| JSON schema breaks downstream consumers | Low | New file is additive; existing CSV consumers unaffected |
| Scope overlap with TASK-003 | Medium | See mitigation above |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `cams_grabber/snapshot_triage.py` | Modify | Add 4 functions, extend TriageConfig, extend CLI, extend run_triage |
| `tests/test_snapshot_triage.py` | Modify | Add 5+ new test cases |
| `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` | Modify | Document new outputs, CLI flags, JSON schema, codec notes |
| `README.md` | Modify | Add new default outputs and CLI flags |
| `requirements-dev.txt` | No change | Existing deps suffice |
| `docker-compose.yml` | No change | Volume mounts already cover output/ |

---

## 7. Validation Plan

1. `python3 -m py_compile cams_grabber/snapshot_triage.py` — syntax check
2. `python3 -m unittest -v tests/test_snapshot_triage.py` — full test suite
3. Manual run with sample images: verify JSON schema, kept directory, and (Phase B) video
4. Deterministic rerun: diff JSON outputs between two identical runs
5. Edge cases: empty input dir, all-rejected input, single-image input
