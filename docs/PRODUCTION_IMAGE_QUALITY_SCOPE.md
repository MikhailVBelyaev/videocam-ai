# Production Image Quality Scope (TASK-001)

Job ID: 2026-06-17_111901_videocam-ai-production-image-quality-problem-many-images-are-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-17

## Problem Statement

Production snapshots from the camera pipeline contain a high rate of blurry frames.
The existing snapshot triage pipeline already rejects images based on a single
Laplacian-variance blur score, but production feedback indicates many blurry
images still pass this gate. The original request also mentions missing important
objects; that concern is scoped out under current project guardrails.

## Current Baseline

- `cams_grabber/snapshot_triage.py` computes one blur signal: variance of the
  Laplacian on a grayscale image (`blur_score`).
- A single configurable threshold (`--blur-threshold`, default `100.0`) decides
  keep vs reject.
- The test suite validates this behavior with synthetic sharp, blurred,
  low-light, and duplicate fixtures.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that improves blur detection without expanding into excluded domains.

Included:
1. Add a secondary gradient-based blur metric (Sobel variance / Tenengrad) in
   `cams_grabber/snapshot_triage.py`.
2. Update the blur decision so an image is rejected when **either** the
   Laplacian variance or the new gradient metric falls below its threshold.
3. Extend the CSV schema with a new `gradient_score` column.
4. Add a `--gradient-threshold` CLI argument with a sensible default derived
   from the existing test fixtures.
5. Add focused unit tests for the new metric and the composite blur behavior.
6. Update `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` with the new column, threshold, and
   tuning guidance.

## Measurable Acceptance Criteria

- A synthetic Gaussian-blurred image (sigma >= 5, 128x128) is rejected by at
  least one of the two blur metrics using default thresholds.
- A synthetic sharp checkerboard image passes both blur metrics using default
  thresholds.
- CSV output contains the new `gradient_score` column in stable row order.
- The existing test suite (`tests/test_snapshot_triage.py`) passes without
  modification.
- Repeated runs with identical input and config produce identical `decision`,
  `reason`, and `duplicate_group` values.

## Explicit Exclusions

- No object detection or object-presence validation (outside current guardrails).
- No real-time camera stream processing.
- No cloud/API/database integration.
- No source-image deletion.
- No multi-camera orchestration.
- No production deployment or host-specific configuration.
- No removal of the existing Laplacian metric; it remains the primary blur signal.

## Assumptions

- OpenCV and NumPy remain the only image-processing dependencies.
- Input is still a single local directory of `.jpg`/`.jpeg`/`.png` files.
- Default thresholds will be calibrated against the existing synthetic test
  fixtures, not production sample data.

## Risks

- The new gradient metric may correlate strongly with Laplacian on the current
  synthetic fixtures, making it hard to prove added value without real production
  samples. Mitigation: document the limitation and recommend a follow-up tuning
  job once production sample images are available.
- Adding a new CSV column changes the output schema. Downstream consumers of
  `triage_report.csv` may need to be updated. Mitigation: append the new column
  at the end of the schema to minimize breakage.
