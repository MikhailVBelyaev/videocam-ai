# Next Actions

Last updated: 2026-06-18

## Current Priority

TASK-003 implementation of Phase A (object detection and statistics) for
"Improve production image quality and statistics"
(Job ID: 2026-06-17_172653) is complete and awaiting human review.

## Completed Increments

- TASK-001 scope was approved by human review on 2026-06-17.
- TASK-002 design was completed on 2026-06-18.
- TASK-003 implementation of Phase A (object detection) completed on 2026-06-18.
  - Added MobileNet-SSD object detection via OpenCV DNN with car/person counting.
  - Extended CSV with `car_count` and `person_count`.
  - Extended JSON with `total_objects_by_type`, `object_counts` per kept frame,
    and `missing_expected_objects`.
  - Added `--detect-objects`, `--model-dir`, `--expected-objects` CLI flags.
  - Added 5 new focused tests; all 32 tests pass.
  - Updated runbook and README with setup instructions and new schemas.
  - Status: `review_required`.
- TASK-004 QA validation and implementation increment completed on 2026-06-18.
  - Implemented JSON statistics summary, kept-directory copy, and timelapse video generation.
  - Added 23 new focused tests; all 27 tests pass.
  - Updated runbook with new outputs, CLI flags, JSON schema, and codec notes.
  - Status: `review_required`.
- TASK-004 QA validation (task-004) completed on 2026-06-18.
  - Added 20 new focused tests covering object detection unit tests, _check_missing_expected,
    pipeline edge cases, _compute_statistics with detection data, and timelapse edge cases.
  - All 52 tests pass. `py_compile` clean.
  - No source code changes required; all tests validate existing behavior.
  - Status: `review_required`.
- TASK-005 documentation increment completed on 2026-06-18.
  - Updated `README.md` with all current CLI flags, outputs, and JSON summary description.
  - Updated `docs/PROJECT_STATUS_MEMORY.md` and `docs/NEXT_ACTIONS.md`.
  - Status: `review_required`.
- TASK-002 design for "Improve production image quality and statistics" completed on 2026-06-18.
  - Design doc at `docs/TASK002_IMPROVE_IMAGE_QUALITY_STATISTICS_DESIGN.md`.
  - Object detection (car/person counting) explicitly scoped in.
  - Enhanced quality metrics (contrast, overexposure) documented.
  - Status: `review_required`.

## Review Items

- Review the TASK-003 Phase A implementation diff for `cams_grabber/snapshot_triage.py`,
  `tests/test_snapshot_triage.py`, `README.md`, and `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`.
  - Verify object detection integration is correct and test coverage is adequate.
  - Verify graceful fallback when model files are missing.
  - Verify CSV and JSON schema extensions match the design doc.
  - Decide whether to accept, revise, or reject the implementation.
- Review the TASK-002 design doc `docs/TASK002_IMPROVE_IMAGE_QUALITY_STATISTICS_DESIGN.md`.
  - Verify affected services, modules, data flows, and interfaces are accurate.
  - Verify implementation approach and tradeoffs are acceptable.
  - Decide whether to accept, revise, or reject the design.
  - If accepted, prepare a TASK-003 implementation job for Phase B (enhanced quality metrics).
- Review the TASK-005 documentation diff for `README.md`, `docs/PROJECT_STATUS_MEMORY.md`,
  `docs/NEXT_ACTIONS.md`, `docs/DEVELOPMENT_LOG.md`, and `docs/PROJECT_MANAGER.yaml`.
- Verify that README accurately describes all implemented CLI flags and outputs.
- Verify that project status docs reflect the current implementation state.

## Object Detection Scope Note

The job description explicitly allowed object detection/statistics as in-scope
for this increment. Phase A (object detection using MobileNet-SSD via OpenCV DNN,
with car/person counting, per-image object counts in JSON, and missing-expected-object
flagging) has been implemented and is in `review_required`.

Phase B (enhanced quality metrics: contrast score, overexposure score, updated
quality rank formula) remains documented in the TASK-002 design doc and is
recommended as a follow-up implementation increment.

## Pending Scope (From Earlier Increments)

- TASK-004 QA validation and implementation is in `review_required`.
- TASK-005 documentation increment is in `review_required`.
- Phase B (contrast/overexposure metrics and updated quality rank) is pending
  a prepared implementation job.
