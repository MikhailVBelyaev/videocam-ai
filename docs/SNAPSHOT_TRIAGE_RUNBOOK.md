# Snapshot Triage Runbook

## Purpose

Run a deterministic local-folder snapshot triage pass for one camera image directory.

## Inputs

- Supported file types: `.jpg`, `.jpeg`, `.png`
- One input directory path containing snapshots
- Files are read non-recursively from the input directory root

## Outputs

- CSV report: `output/triage_report.csv`
- Rejected image copies: `rejected/`
- Source images are never deleted

## Run

From repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python cams_grabber/snapshot_triage.py <input_dir>
```

Example with explicit output directories and thresholds:

```bash
.venv/bin/python cams_grabber/snapshot_triage.py ./sample_input --output-dir ./output --rejected-dir ./rejected --blur-threshold 100 --brightness-threshold 55 --duplicate-distance-threshold 5
```

The command logs summary metrics:

- total images
- kept images
- rejected count per reason

## CSV Columns

- `filename`
- `decision` (`keep` or `reject`)
- `reason` (`blur`, `low_light`, `duplicate`, or empty for kept)
- `blur_score` (Laplacian variance)
- `brightness_score` (mean grayscale brightness)
- `duplicate_group` (group id for duplicate rejections)

## Rule Tuning

- Increase `--blur-threshold` to reject more soft images.
- Increase `--brightness-threshold` to reject more dark images.
- Increase `--duplicate-distance-threshold` to reject more near-duplicates.
- Decrease these thresholds to keep more images.

For deterministic re-runs, use the same input files and threshold values.

## Validation Status

Validated in repository state dated 2026-06-16:

- `.venv/bin/python cams_grabber/snapshot_triage.py --help` (pass)
- `.venv/bin/python -m unittest -v tests/test_snapshot_triage.py` (pass)
- `.venv/bin/python -m unittest discover -s tests -v` (pass)
- `.venv/bin/python -m py_compile cams_grabber/snapshot_triage.py tests/test_snapshot_triage.py` (pass)

Covered verification points:

- blur rejection
- low-light rejection
- duplicate rejection and deterministic `duplicate_group` assignment
- stable CSV schema and decisions on re-run
- rejected-copy behavior and source-image immutability

## Limitations

- Single local input folder only; no multi-camera orchestration.
- No real-time stream ingestion.
- No object/event detection.
- No cloud/API/database integration.
- Source images are never auto-deleted.
