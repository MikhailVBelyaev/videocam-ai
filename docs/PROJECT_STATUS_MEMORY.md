# Project Status Memory

Last updated: 2026-06-19

## Latest Update

- TASK-005 documentation for "Change /admin: add web server page with cars and"
  is complete and in `review_required`. Created `docs/WEB_VIEWER_RUNBOOK.md`
  covering `/admin` behavior, static file serving, configuration, operating
  steps, validation commands, and troubleshooting. Updated `README.md` to
  reference the new runbook. Updated project status docs. All 28 web_viewer
  tests pass; all 127 total tests pass.
- TASK-004 QA validation for "Change /admin: add web server page with cars and"
  is complete and in `review_required`. Added 14 focused QA tests in
  `tests/test_web_viewer.py` covering error paths (OSError on file read/list,
  invalid date string), boundary conditions (5-image cap, extension filtering,
  subdirectory exclusion), rendering edge cases (None summary, no links,
  Stale label, non-car/person objects ignored), and integration (404 for missing
  file, empty dir renders error). All 28 web_viewer tests pass; all 127 total
  tests pass. No source code changes required.
- TASK-003 implementation for "Change /admin: add web server page with cars and"
  is complete and in `review_required`. Replaced nginx `web_viewer` with a minimal
  Flask Python web server. Added `/admin` HTML endpoint displaying triage statistics
  (total images, kept images, car/person counts, missing expected objects), latest
  run date, freshness indicator, and links to latest images. Preserved existing
  static file serving. Added 14 focused tests in `tests/test_web_viewer.py`; all pass.
  Updated `docker-compose.yml` with new build context, volume mount, port mapping,
  and healthcheck. Updated `README.md` with web viewer documentation.
- TASK-002 design for "Change /admin: add web server page with cars and" is complete
  and in `review_required`. Defined Flask replacement approach, data flows, interfaces,
  tradeoffs, risks, and validation plan in `docs/WEB_ADMIN_PAGE_DESIGN.md`.
- TASK-001 scope for the same feature is complete and in `review_required`.
  Defined minimum deliverable, acceptance criteria, and explicit exclusions in
  `docs/WEB_ADMIN_PAGE_SCOPE.md`.
- TASK-005 documentation for "add to command /state info about running containers"
  is complete and in `review_required`. Verified `README.md` against `tg_bot/bot.py`; added operating
  steps; updated project status docs.
- TASK-003 implementation of the Telegram `/state` command is complete and in
  `review_required`. Added container status query via Docker SDK, formatted output
  with emoji/uptime, admin restriction, and read-only socket mount.
- TASK-004 QA validation for the `/state` command is complete and in
  `review_required`. Added 8 focused tests covering DockerException, dict
  structure, mixed containers, client cleanup, missing Health key, nanosecond
  uptime truncation, minutes-only formatting, and emoji mapping.
- Added 12 focused tests in `tests/test_tg_bot.py`; all pass alongside 52 existing
  snapshot triage tests.
- TASK-001 scope was defined for the camera snapshot quality triage increment.
- Scope now includes a minimum deliverable, measurable acceptance criteria, and explicit exclusions.
- TASK-003 implementation of Phase A (object detection and statistics) is complete
  and in `review_required`. Added MobileNet-SSD object detection via OpenCV DNN,
  car/person counting in CSV and JSON, missing-expected-object flagging, and
  graceful fallback when model files are missing.
- TASK-004 QA validation and implementation is in `review_required`.
- TASK-005 documentation increment is in `review_required`.
- Object detection/object statistics are now implemented for the snapshot triage
  pipeline via optional `--detect-objects` CLI flag.
- Phase B (enhanced quality metrics: contrast score, overexposure score, updated
  quality rank formula) remains documented in the TASK-002 design doc and is
  pending a future implementation increment.
- Local validation environment is documented in `requirements-dev.txt` and uses
  `opencv-python-headless` plus `numpy<2.0`.
- Human approved publishing the reviewed snapshot triage package to GitHub.

## Start Here

Read `AGENTS.md`, `docs/PROJECT_MANAGER.yaml`, and `docs/NEXT_ACTIONS.md` before editing.
