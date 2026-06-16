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
- `rejected/` (copies of rejected images)

Default thresholds:

- `--blur-threshold 100.0`
- `--brightness-threshold 55.0`
- `--duplicate-distance-threshold 5`

Example with explicit output locations and thresholds:

```bash
.venv/bin/python cams_grabber/snapshot_triage.py ./sample_input --output-dir ./output --rejected-dir ./rejected --blur-threshold 100 --brightness-threshold 55 --duplicate-distance-threshold 5
```

Validate the pipeline:

```bash
.venv/bin/python -m unittest -v tests/test_snapshot_triage.py
.venv/bin/python -m unittest discover -s tests -v
```

Full operating details, tuning guidance, and limitations are in:

- `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`
