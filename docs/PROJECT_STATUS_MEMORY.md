# Project Status Memory

Last updated: 2026-06-19

## Latest Update

- TASK-002 design for "Fix production Telegram image delivery: bot sends repeated
  static/latest" is complete and in `review_required`. Created
  `docs/TELEGRAM_REPEATED_STATIC_DESIGN.md` defining affected services, modules,
  data flows, implementation approach (triage-aware image selection via `kept/`
  subfolder, configurable `IMAGE_SIMILARITY_THRESHOLD` default 10, send statistics
  counters in `/admin`), five key tradeoffs, risks, and validation plan.
  No source code changes; all 156 tests pass; `py_compile` clean.

## Prior Update

- TASK-001 scope definition for "Fix production Telegram image delivery: bot sends
  repeated static/latest" is complete and in `review_required`. Created
  `docs/TELEGRAM_REPEATED_STATIC_SCOPE.md` defining minimum deliverable (triage-aware
  image selection, perceptual-hash threshold increase to configurable default 10,
  send statistics counters in `/admin`), measurable acceptance criteria, and explicit
  exclusions. No source code changes; all 156 tests pass; `py_compile` clean.

## Prior Update

- TASK-005 documentation for "Fix remaining Telegram image backlog problem" is
  complete and in `review_required`. Updated `docs/TG_BOT_RUNBOOK.md` validation
  counts to 76 tg_bot tests / 156 total tests. Verified `README.md` consistency.
  Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
  `docs/DEVELOPMENT_LOG.md`, and `docs/PROJECT_MANAGER.yaml`. All 156 tests pass.
  `py_compile` clean.
- TASK-004 QA validation for "Fix remaining Telegram image backlog problem"
  is complete and in `review_required`. Added 6 focused QA tests in
  `tests/test_tg_bot.py` (TgBotStartupStateQATests) covering:
  multiple-dated-folder selection, module global mutation,
  `_LAST_SENT_TIMESTAMP` preservation (cooldown bypass tradeoff),
  OSError error propagation chain, state file format correctness, and
  iteration start-index after initialization. No source code changes required.
  All 76 tg_bot tests pass; all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
  Total 156 tests pass. `py_compile` clean.
- TASK-003 implementation for "Fix remaining Telegram image backlog problem"
  is complete and in `review_required`. Modified `tg_bot/bot.py` to add
  `_initialize_startup_state()` helper and call it from `main()` when no
  `.last_sent_file` exists. Added 4 focused tests in `tests/test_tg_bot.py`
  (TgBotStartupStateTests). Updated `README.md` and `docs/TG_BOT_RUNBOOK.md`
  with startup behavior docs and validation counts (70 tg_bot tests, 150 total).
  Updated project status docs. All 150 tests pass. `py_compile` clean.
- TASK-002 design for "Fix remaining Telegram image backlog problem"
  is complete and in `review_required`. Created `docs/TELEGRAM_BACKLOG_DESIGN.md`
  with affected services, modules, data flows, interfaces, implementation approach,
  tradeoffs, risks, and validation plan. All 146 tests pass; no source code changes.
- TASK-005 documentation for "Fix production Telegram image delivery and admin statistics"
  is complete and in `review_required`. Updated `docs/TG_BOT_RUNBOOK.md` with image
  sender safeguards (concurrency guard, per-iteration send cap, cooldown bypass),
  `/admin` latest image file send behavior, new env vars, expanded troubleshooting,
  and updated validation counts. Verified `README.md` consistency. Updated project
  status docs. All 146 tests pass. `py_compile` clean.
- TASK-004 QA validation for "Fix production Telegram image delivery and admin statistics"
  is complete and in `review_required`. Added 13 focused QA tests in `tests/test_tg_bot.py`
  (53 → 66 tg_bot tests). Tests cover: sender lock-free positive case, cooldown-blocking
  negative case, sub-cap positive case, send_photo timestamp update on success and no-update
  on failure, `_get_latest_image_path` edge cases (no folders, empty folder, mtime ordering,
  non-image filtering, OSError), `_get_latest_run_date` OSError, and `_summarize_live_output`
  no-media and OSError. All 146 total tests pass. `py_compile` clean. No source code changes
  required.
- TASK-003 implementation for "Fix production Telegram image delivery and admin statistics"
  is complete and in `review_required`. Modified `tg_bot/bot.py` to add concurrency guard
  (`asyncio.Lock`), per-iteration send cap (`MAX_IMAGES_PER_ITERATION`, default 5),
  time-based duplicate bypass cooldown (`SEND_COOLDOWN_SECONDS`, default 300), and
  `/admin` latest image file send with graceful fallback. Added 6 focused tests in
  `tests/test_tg_bot.py` covering guard skip, cap enforcement, cooldown bypass, and
  `/admin` photo behaviors. Updated `README.md` with new env vars and sender safeguard
  descriptions. All 53 tg_bot tests pass; all 52 snapshot triage tests pass; all 28
  web_viewer tests pass. Total 133 tests pass. `py_compile` clean.
- TASK-002 design for "Fix production Telegram image delivery and admin statistics"
  is complete and in `review_required`. Created `docs/TELEGRAM_IMAGE_DELIVERY_DESIGN.md`
  defining affected services (`tg_bot/bot.py` primary), module-level changes
  (concurrency guard, send cap, cooldown bypass, `/admin` latest image send),
  data flow diagrams, interfaces, implementation approach, tradeoffs, risks,
  and validation plan. All 127 tests pass; no source code changes.
- TASK-001 scope for "Fix production Telegram image delivery and admin statistics"
  is complete and in `review_required`. Created `docs/TELEGRAM_IMAGE_DELIVERY_SCOPE.md`
  defining minimum deliverable (concurrency guard, per-iteration send cap, time-based
  duplicate bypass, `/admin` latest image send), measurable acceptance criteria, and
  explicit exclusions. All 127 tests pass; no source code changes.
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
