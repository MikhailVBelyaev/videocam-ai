# Snapshot Triage Pipeline Design (TASK-002)

Last updated: 2026-06-16
Status: review_required
Job ID: 2026-06-13_085814_it-s-project-with-cameras-with-cameras-which-i-have-in-task-002
Project: videocam-ai

## Scope

Design only for a deterministic single-camera snapshot triage pipeline.

Included:
- Scan one local input folder of image snapshots.
- Compute three quality signals: blur, brightness, and near-duplicate similarity.
- Write `output/triage_report.csv`.
- Copy rejected snapshots into `rejected/`.

Explicit exclusions carried from TASK-001:
- No real-time camera stream.
- No object detection/event detection.
- No cloud/API/database.
- No source-image deletion.
- No multi-camera orchestration.

## Affected Modules / Services

Design targets the following module boundaries (single process CLI):

1) `cams_grabber/snapshot_triage.py` (CLI entrypoint + orchestration)
- Parse CLI/config.
- Build runtime config.
- Run pipeline steps in deterministic filename order.
- Emit summary logs.

2) `cams_grabber/image_discovery.py` (folder scanner)
- Enumerate `.jpg`, `.jpeg`, `.png` in one input directory.
- Normalize and sort by case-insensitive filename for reproducible runs.
- Reject invalid input path early.

3) `cams_grabber/quality_signals.py` (signal calculators)
- Blur score: variance of Laplacian on grayscale image.
- Brightness score: grayscale mean intensity.
- Duplicate fingerprint: perceptual hash (average hash) and Hamming distance.

4) `cams_grabber/triage_rules.py` (decision engine)
- Apply rules in deterministic order:
  a) blur
  b) low_light
  c) duplicate
- Assign `keep`/`reject`, `reason`, and optional `duplicate_group`.

5) `cams_grabber/report_writer.py` (CSV writer)
- Write `output/triage_report.csv` with fixed schema and stable row order.

6) `cams_grabber/rejected_export.py` (copy service)
- Copy rejected files to `rejected/` preserving original filename.
- Never delete/mutate source snapshots.

Note: For minimal implementation, modules 2-6 can be implemented inside one file first, then split later without changing external behavior.

## Data Flow

1. CLI receives: input folder + optional thresholds/output locations.
2. Scanner builds sorted candidate image list.
3. For each image:
   - read image;
   - compute blur and brightness;
   - if quality gates pass, compute perceptual hash and compare with accepted set.
4. Decision engine emits a triage record:
   - `filename`, `decision`, `reason`, `blur_score`, `brightness_score`, `duplicate_group`.
5. If `reject`, copy source file to `rejected/`.
6. Append record to report rows.
7. Write CSV and print summary counters.

## CLI and Configuration Interface

Required CLI:
- positional: `input_dir`

Optional CLI:
- `--output-dir` default `output`
- `--rejected-dir` default `rejected`
- `--blur-threshold` default `100.0`
- `--brightness-threshold` default `55.0`
- `--duplicate-distance-threshold` default `5`

Config contract:
- Thresholds are numeric and validated at startup.
- Input directory must exist and be readable.
- Output directories are created if missing.

## Output Contract

Folder structure (relative to run working directory unless absolute paths passed):
- `output/triage_report.csv`
- `rejected/<filename>` copied rejects

CSV columns (fixed order):
1. `filename`
2. `decision` (`keep`|`reject`)
3. `reason` (`blur`|`low_light`|`duplicate`|empty for keep)
4. `blur_score`
5. `brightness_score`
6. `duplicate_group` (empty unless duplicate)

## Threshold and Rule Semantics

Defaults:
- Blur threshold: reject if `blur_score < 100.0`.
- Brightness threshold: reject if `brightness_score < 55.0`.
- Duplicate threshold: reject if Hamming distance `<= 5` to an already accepted image hash.

Rule precedence:
- First matching reject reason wins; duplicate is evaluated only after blur/brightness pass.

Determinism requirements:
- Stable input sort.
- Stable rule order.
- Stable duplicate-group assignment sequence.

## Validation Approach (Design-Time)

Focused checks for implementation phase:
- Unit: signal calculators return deterministic values for fixture images.
- Unit: rule ordering preserves first-reason semantics.
- Unit: duplicate grouping is deterministic across repeated runs.
- Integration: same input + config => identical CSV `decision`/`reason` outputs.
- Integration: rejected images are copied, source files unchanged.
- Negative: invalid input path returns explicit error.

## Tradeoffs

- Average hash is lightweight and fast for local CPU-only runs, but less robust than heavier perceptual models.
- Sequential single-process execution is simplest and deterministic, but slower for very large folders.
- Reject-copy behavior favors safety and auditability over storage efficiency.
