# Next Actions

Last updated: 2026-06-18

## Current Priority

TASK-005 documentation for the Telegram `/admin` command
(Job ID: 2026-06-18_115153_videocam-ai-add-to-tg-service-admin-command-and-show-1-task-005)
is complete and awaiting human review.

## Completed Increments (Docs)

- TASK-005 documentation increment for the Telegram `/admin` command completed on 2026-06-18.
  - Verified `README.md` Telegram bot section against `tg_bot/bot.py` implementation.
  - Added local and Docker Compose operating steps to README.
  - Updated project status docs (`PROJECT_STATUS_MEMORY.md`, `NEXT_ACTIONS.md`, `PROJECT_MANAGER.yaml`, `DEVELOPMENT_LOG.md`).
  - All 23 tg_bot tests pass; all 52 snapshot triage tests pass. `py_compile` clean.
  - Status: `review_required`.

- TASK-004 QA validation for the Telegram `/admin` command completed on 2026-06-18.
  - Added 11 focused tests in `tests/test_tg_bot.py` covering edge cases and
    integration behavior of the `/admin` command.
  - All 23 tg_bot tests pass; all 52 snapshot triage tests pass.
  - `py_compile` clean. No source code changes required.
  - Status: `review_required`.

## Completed Increments

- TASK-003 implementation of the Telegram `/admin` command completed on 2026-06-18.
  - Refactored `tg_bot/bot.py` to `python-telegram-bot` Application with JobQueue.
  - Added `/admin` handler with admin-chat restriction and triage summary formatting.
  - Added 12 focused tests in `tests/test_tg_bot.py`; all pass.
  - All 52 existing snapshot triage tests pass. `py_compile` clean.
  - Updated `README.md` with Telegram bot env vars and `/admin` documentation.
  - Status: `review_required`.

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

- Review the TASK-003 implementation diff for `tg_bot/bot.py`, `tests/test_tg_bot.py`,
  `tg_bot/__init__.py`, and `README.md`.
  - Verify `/admin` command returns formatted summary with total_images, kept_images,
    car_count, person_count from latest `triage_summary.json`.
  - Verify missing/malformed `triage_summary.json` yields "No triage data available."
  - Verify non-admin chats are silently ignored.
  - Verify existing image-sending behavior is unchanged (no regression).
  - Verify `py_compile` and unit tests pass.
  - Decide whether to accept, revise, or reject the implementation.

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
- Review the TASK-005 documentation diff for the Telegram `/admin` command:
  `README.md`, `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
  `docs/DEVELOPMENT_LOG.md`, and `docs/PROJECT_MANAGER.yaml`.
  - Verify README accurately describes env vars, `/admin` behavior, and operating steps.
  - Verify project status docs reflect the current implementation state.
  - Decide whether to accept, revise, or reject the documentation.

## Object Detection Scope Note

The job description explicitly allowed object detection/statistics as in-scope
for this increment. Phase A (object detection using MobileNet-SSD via OpenCV DNN,
with car/person counting, per-image object counts in JSON, and missing-expected-object
flagging) has been implemented and is in `review_required`.

Phase B (enhanced quality metrics: contrast score, overexposure score, updated
quality rank formula) remains documented in the TASK-002 design doc and is
recommended as a follow-up implementation increment.

## New Review Items (TASK-001 /admin command scope)

- Review `docs/TG_ADMIN_COMMAND_SCOPE.md` for the Telegram `/admin` command increment.
  - Verify minimum deliverable is small enough for one Codex session.
  - Verify acceptance criteria are measurable and exclusions are explicit.
  - Decide whether to accept, revise, or reject the scope.

## New Review Items (TASK-002 /admin command design)

- Review `docs/TG_ADMIN_COMMAND_DESIGN.md` for the Telegram `/admin` command increment.
  - Verify affected services, modules, data flows, and interfaces are accurate.
  - Verify implementation approach and tradeoffs are acceptable.
  - Decide whether to accept, revise, or reject the design.
  - If accepted, prepare a TASK-003 implementation job for the `/admin` command increment.

## Pending Scope (From Earlier Increments)

- TASK-004 QA validation and implementation is in `review_required`.
- TASK-005 documentation increment is in `review_required`.
- Phase B (contrast/overexposure metrics and updated quality rank) is pending
  a prepared implementation job.