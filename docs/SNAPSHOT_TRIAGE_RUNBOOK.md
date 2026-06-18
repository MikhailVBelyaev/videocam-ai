# Snapshot Triage Runbook

## Purpose

Run a deterministic local-folder snapshot triage pass for one camera image directory.

## Inputs

- Supported file types: `.jpg`, `.jpeg`, `.png`
- One input directory path containing snapshots
- Files are read non-recursively from the input directory root

## Outputs

- CSV report: `output/triage_report.csv`
- JSON statistics summary: `output/triage_summary.json`
- Rejected image copies: `rejected/`
- Kept image copies (optional): `kept/` (when `--kept-dir` is provided)
- Timelapse video (optional): `output/kept_timelapse.mp4` (when `--generate-video` is passed)
- Source images are never deleted

## Run

From repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python cams_grabber/snapshot_triage.py <input_dir>
```

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

The command logs summary metrics:

- total images
- kept images
- rejected count per reason

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `input_dir` (positional) | required | Directory containing JPG/PNG images |
| `--output-dir` | `output` | Directory for CSV report and JSON summary |
| `--rejected-dir` | `rejected` | Directory for rejected image copies |
| `--kept-dir` | None (skip) | Directory to copy kept frames to |
| `--generate-video` | off | Generate a timelapse video from kept frames |
| `--video-fps` | 5.0 | Frame rate for the timelapse video |
| `--blur-threshold` | 100.0 | Reject images with Laplacian variance below this value |
| `--gradient-threshold` | 20.0 | Reject images with gradient magnitude variance below this value |
| `--brightness-threshold` | 55.0 | Reject images with mean grayscale brightness below this value |
| `--duplicate-distance-threshold` | 5 | Reject image as duplicate when Hamming distance <= threshold |
| `--detect-objects` | off | Run MobileNet-SSD object detection and add car/person counts |
| `--model-dir` | `models` | Directory containing MobileNetSSD model files |
| `--expected-objects` | "" | Comma-separated list of expected objects (e.g., `car,person`) |

## CSV Columns

- `filename`
- `decision` (`keep` or `reject`)
- `reason` (`blur`, `low_light`, `duplicate`, `unreadable`, or empty for kept)
- `blur_score` (Laplacian variance)
- `gradient_score` (gradient magnitude variance)
- `brightness_score` (mean grayscale brightness)
- `duplicate_group` (group id for duplicate rejections)
- `car_count` (MobileNet-SSD car detections; 0 when detection disabled)
- `person_count` (MobileNet-SSD person detections; 0 when detection disabled)

## JSON Summary Schema (`triage_summary.json`)

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
  "total_objects_by_type": {
    "car": 45,
    "person": 12
  },
  "missing_expected_objects": [
    {"filename": "IMG_0001.jpg", "missing": ["car"]}
  ],
  "kept_frames": [
    {"filename": "IMG_0001.jpg", "quality_rank": 0.85, "object_counts": {"car": 1, "person": 0}},
    {"filename": "IMG_0007.jpg", "quality_rank": 0.72, "object_counts": {"car": 2, "person": 1}}
  ]
}
```

The `quality_rank` ranges from 0.0 to 1.0 (higher is better). It is computed as:

```
quality_rank = normalize(blur_score) * 0.4
             + normalize(gradient_score) * 0.3
             + normalize(brightness_score) * 0.3
```

where `normalize(x) = (x - min) / (max - min)` per-score across all images.
When all images have the same score, `quality_rank` is 0.0.

Object detection fields (`total_objects_by_type`, `missing_expected_objects`,
`object_counts` inside `kept_frames`) are present only when `--detect-objects`
is enabled and the model loaded successfully.

## Kept Directory

When `--kept-dir` is provided, kept frames are copied to the specified directory
using `shutil.copy2` (preserving file metadata). Only frames with
`decision == "keep"` are copied. The directory is created if it does not exist.

## Timelapse Video

When `--generate-video` is passed and at least one frame is kept, a timelapse
video is written to `output/kept_timelapse.mp4`. Frames follow the same
stable filename-sorted order as the CSV report.

- Codec fallback chain: `mp4v` -> `avc1` -> `XVID` -> skip with warning.
- Video dimensions match the first kept frame; subsequent frames are resized
  if necessary.
- If no frames are kept, no video is generated.
- No audio track is included.

**Note**: Video codec availability varies by host. Test on the target host
before relying on video output in production.

## Rule Tuning

- Increase `--blur-threshold` to reject more soft images.
- Increase `--gradient-threshold` to reject more soft images via gradient magnitude.
- Increase `--brightness-threshold` to reject more dark images.
- Increase `--duplicate-distance-threshold` to reject more near-duplicates.
- Decrease these thresholds to keep more images.

For deterministic re-runs, use the same input files and threshold values.

## Determinism

Repeated runs with identical input and config produce identical:

- `decision`, `reason`, `duplicate_group` in the CSV report
- `triage_summary.json` content
- Kept directory file contents
- Rejected directory file contents

## Object Detection Setup

When `--detect-objects` is passed, the pipeline uses OpenCV DNN with
MobileNet-SSD (Caffe) to count cars and people per image.

**Required model files:**

- `MobileNetSSD_deploy.prototxt` (~30 KB)
- `MobileNetSSD_deploy.caffemodel` (~23 MB)

Place both files in the directory specified by `--model-dir` (default: `models`).
You can download them from the OpenCV GitHub samples repository:

```bash
mkdir -p models
curl -L -o models/MobileNetSSD_deploy.prototxt \
  https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/MobileNetSSD_deploy.prototxt
curl -L -o models/MobileNetSSD_deploy.caffemodel \
  https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/MobileNetSSD_deploy.caffemodel
```

**Behavior when models are missing:**

- A warning is logged.
- Triage continues with `car_count=0` and `person_count=0` for every image.
- No object-related keys are added to `triage_summary.json`.

**Accuracy notes:**

- MobileNet-SSD is fast on CPU but less accurate than YOLOv8.
- Counts are advisory; false positives/negatives are possible.
- Only `car` and `person` get dedicated CSV columns; other COCO classes
  (including `vehicle`, which maps `bus` detections) appear in JSON `object_counts`.

## Validation Status

Validated in repository state dated 2026-06-18:

- `.venv/bin/python cams_grabber/snapshot_triage.py --help` (pass)
- `.venv/bin/python -m unittest -v tests/test_snapshot_triage.py` (52 tests, pass)
- `.venv/bin/python -m unittest discover -s tests -v` (pass)
- `.venv/bin/python -m py_compile cams_grabber/snapshot_triage.py tests/test_snapshot_triage.py` (pass)

Covered verification points:

- blur rejection (Laplacian and gradient)
- gradient metric independent blur catch
- low-light rejection
- duplicate rejection and deterministic `duplicate_group` assignment
- stable CSV schema and decisions on re-run
- rejected-copy behavior and source-image immutability
- JSON summary schema completeness, value consistency, and determinism
- quality rank computation (ordering, single image, empty input)
- kept directory: exact copy of kept frames, no rejected frames, no directory when not configured
- timelapse video: creation, graceful skip on empty kept, skip when not requested
- CLI parser: `--generate-video`, `--video-fps`, `--kept-dir`, `--detect-objects`, `--model-dir`, `--expected-objects`
- full pipeline integration: JSON + kept dir + video together
- object detection: graceful skip on missing model, CSV/JSON population, missing expected objects flagging, deterministic rerun

## Limitations

- Single local input folder only; no multi-camera orchestration.
- No real-time stream ingestion.
- No cloud/API/database integration.
- Source images are never auto-deleted.
- Object detection uses MobileNet-SSD; accuracy is lower than YOLOv8 and counts are advisory.
- Default thresholds were calibrated against synthetic fixtures; production
  tuning with real camera samples is recommended.
- Video codec availability depends on the host OpenCV build.
- Mixed image sizes in video are resized to match the first kept frame;
  aspect ratio distortion may occur.