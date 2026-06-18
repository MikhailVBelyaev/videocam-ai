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

Full operating details, tuning guidance, JSON schema, and limitations are in:

- `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`
