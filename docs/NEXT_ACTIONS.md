# Next Actions

Last updated: 2026-06-19

## Current Priority

TASK-002 design for "Fix production Telegram image delivery: bot sends repeated
static/latest" is complete and in `review_required`. Created
`docs/TELEGRAM_REPEATED_STATIC_DESIGN.md` defining affected services, data flows,
implementation approach (triage-aware image selection via `kept/` subfolder,
configurable `IMAGE_SIMILARITY_THRESHOLD` default 10, send statistics counters
in `/admin`), five key tradeoffs, risks, and validation plan. No source code
changes; all 156 tests pass.

## New Review Items (TASK-002 repeated-static design)

- Review `docs/TELEGRAM_REPEATED_STATIC_DESIGN.md`.
  - Verify affected services, modules, data flows, and interfaces are accurate.
  - Verify implementation approach covers: triage-aware image selection (prefer
    `kept/` subfolder, fallback to all images), configurable perceptual-hash
    threshold (`IMAGE_SIMILARITY_THRESHOLD`, default 10), send statistics
    counters (`_SENT_COUNT`, `_SKIPPED_DUPLICATE_COUNT`, `_SKIPPED_NON_KEPT_COUNT`),
    and `/admin` statistics display.
  - Verify key tradeoffs are documented with rationale (kept/ vs. JSON filter,
    always-show vs. conditional statistics, threshold 10 vs. 5, full directory
    scan for non-kept counting, send_photo vs. iteration counter location).
  - Verify risks and mitigations are adequate (kept-folder lag, higher threshold
    suppressing real changes, counter reset on restart, scope overlap with
    pending reviews, kept/ path resolution with LAST_SENT_IMAGE).
  - Verify no scope expansion into triage pipeline changes, web viewer, camera
    capture, staleness detection, persistent statistics, or Docker infrastructure.
  - Decide whether to accept, revise, or reject the design.
  - If accepted, prepare a TASK-003 implementation job.

## Prior Review Items (TASK-001 repeated-static scope)

## Prior Review Items (TASK-005 Telegram backlog documentation)

- Review `docs/TG_BOT_RUNBOOK.md` diff for updated validation counts.
  - Verify tg_bot test count is 76 and total test count is 156.
  - Verify startup behavior section, troubleshooting table, and command descriptions
    remain accurate against `tg_bot/bot.py`.
  - Decide whether to accept, revise, or reject the documentation.
- Review `README.md` Telegram bot section for consistency with `tg_bot/bot.py`.
  - Verify startup behavior description is accurate.
  - Verify env var list matches implementation.
  - Decide whether to accept, revise, or reject.
- Review `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
  `docs/DEVELOPMENT_LOG.md`, and `docs/PROJECT_MANAGER.yaml` diffs.
  - Verify TASK-005 is recorded accurately and counts are correct.
  - Decide whether to accept, revise, or reject the project status updates.

## Completed Review Items (TASK-004 Telegram backlog QA)

- Reviewed `tests/test_tg_bot.py` diff for 6 new QA tests (TgBotStartupStateQATests).
  - Verified `_initialize_startup_state` picks the latest dated folder when multiple exist.
  - Verified module globals `LAST_SENT_IMAGE` and `LAST_SENT_FOLDER` are correctly mutated.
  - Verified `_LAST_SENT_TIMESTAMP` is NOT modified by startup initialization
    (confirming design doc tradeoff 3.3).
  - Verified OSError in `os.listdir` propagates correctly through
    `_get_latest_run_date` → `_get_latest_image_path` → `_initialize_startup_state`
    returning `(None, None)` without crashing or writing a state file.
  - Verified `.last_sent_file` format written by `_initialize_startup_state` is
    exactly `folder/filename\n` and readable by `load_last_sent_file`.
  - Verified `_send_new_images_iteration` starts from the image after the initialized
    one, not from index 0 (core backlog-drain prevention).
  - Status: `review_required`.

## Prior Review Items (TASK-003 Telegram backlog implementation)

- Review `tg_bot/bot.py` diff for the Telegram backlog fix.
  - Verify `_initialize_startup_state()` scans the latest dated folder and sets
    `LAST_SENT_IMAGE`/`LAST_SENT_FOLDER` to the most recently modified image.
  - Verify `save_last_sent_file()` is called during initialization to persist state.
  - Verify `main()` calls `_initialize_startup_state()` only when `load_last_sent_file()`
    returns `(None, None)`.
  - Verify existing behavior when `.last_sent_file` exists is unchanged (no regression).
  - Verify existing concurrency guard, send cap, cooldown bypass, `/admin`, and `/state`
    behaviors are unchanged.
  - Decide whether to accept, revise, or reject the implementation.

- Review `tests/test_tg_bot.py` diff for 4 new focused tests.
  - Verify `TgBotStartupStateTests` covers no-state startup with images, empty folder,
    no dated folders, and existing-state unchanged behavior.
  - Decide whether to accept, revise, or reject the test coverage.

- Review `README.md` and `docs/TG_BOT_RUNBOOK.md` diffs.
  - Verify startup behavior is documented accurately.
  - Verify validation counts are updated (76 tg_bot tests, 156 total).
  - Decide whether to accept, revise, or reject the documentation.

## Completed Review Items (TASK-002 Telegram backlog design)

- Design doc `docs/TELEGRAM_BACKLOG_DESIGN.md` reviewed and accepted.
  - Affected services, modules, data flows, and interfaces verified.
  - Implementation approach (helper extraction, state persistence) verified.
  - Key tradeoffs and risks documented with adequate mitigations.
  - No scope expansion into camera capture, triage pipeline, web viewer, object
    detection, or container infrastructure.
  - Status: accepted; TASK-003 implementation prepared and completed.

## Completed Review Items (TASK-001 Telegram backlog scope)

- Scope doc `docs/TELEGRAM_BACKLOG_SCOPE.md` reviewed and accepted.
  - Minimum deliverable covers startup state initialization when `.last_sent_file` is missing.
  - Acceptance criteria are measurable and exclusions are explicit.
  - Status: accepted; TASK-002 design prepared and completed.

## Completed Review Items (TASK-005 Telegram Docs)

- Verified `README.md` Telegram bot section against `tg_bot/bot.py` implementation.
- Updated `docs/TG_BOT_RUNBOOK.md`:
  - Added "Image Sender Safeguards" section covering concurrency guard (`asyncio.Lock`),
    per-iteration send cap (`MAX_IMAGES_PER_ITERATION`, default 5), and cooldown bypass
    (`SEND_COOLDOWN_SECONDS`, default 300).
  - Updated `/admin` command description to include latest image file send behavior
    and graceful fallback on missing image or send failure.
  - Added `MAX_IMAGES_PER_ITERATION` and `SEND_COOLDOWN_SECONDS` to environment
    variables table.
  - Expanded troubleshooting table with entries for static-scene silence,
    overlapping sender warnings, and missing `/admin` photo.
  - Updated validation counts: 66 tg_bot tests, 146 total tests.
- Updated project status docs (`PROJECT_STATUS_MEMORY.md`, `NEXT_ACTIONS.md`,
  `PROJECT_MANAGER.yaml`, `DEVELOPMENT_LOG.md`).
- All 146 tests pass. `py_compile` clean.
- Decide whether to accept, revise, or extend.

## Completed Review Items (TASK-004 Telegram QA)

- QA validated the TASK-003 implementation in `tg_bot/bot.py`.
- Added 13 focused QA tests in `tests/test_tg_bot.py` (53 → 66 tg_bot tests):
  - `TgBotSenderTests`: sender job runs when lock is free, iteration skips similar images
    within cooldown, iteration sends all when under cap.
  - `TgBotSenderPhotoQATests`: send_photo updates `_LAST_SENT_TIMESTAMP` on success;
    send_photo does not update timestamp on failure.
  - `TgBotLatestImageQATests`: `_get_latest_image_path` returns None for no dated folders,
    empty folder, OSError; picks most recently modified image; ignores non-image files.
  - `TgBotAdminTests`: `_get_latest_run_date` OSError returns None; `_summarize_live_output`
    returns None for no-media and OSError.
- All 146 tests pass (66 tg_bot + 52 snapshot_triage + 28 web_viewer).
- `py_compile` clean on `tg_bot/bot.py` and `tests/test_tg_bot.py`.
- No source code changes required.
- Decide whether to accept, revise, or extend.

## Prior Review Items (TASK-003 Telegram image delivery implementation)

- Review `tg_bot/bot.py` diff for the Telegram image delivery fix.
  - Verify `_SENDER_LOCK` prevents overlapping `image_sender_job` executions.
  - Verify `MAX_IMAGES_PER_ITERATION` (default 5) caps sends per iteration.
  - Verify `SEND_COOLDOWN_SECONDS` (default 300) bypasses perceptual-hash duplicate
    filter when expired.
  - Verify `send_photo()` updates `_LAST_SENT_TIMESTAMP` on success.
  - Verify `_get_latest_image_path()` returns the most recent image in the latest
    dated folder, or None when no images exist.
  - Verify `admin_command()` sends the text summary first, then attempts `reply_photo`
    with the latest image, and falls back to text on failure or absence.
  - Verify non-admin chats are still silently ignored.
  - Verify existing `/state` behavior is unchanged (no regression).
  - Decide whether to accept, revise, or reject the implementation.

- Review `tests/test_tg_bot.py` diff for 6 new focused tests.
  - Verify `TgBotSenderTests` covers lock skip, send cap, and cooldown bypass.
  - Verify `TgBotAdminPhotoTests` covers image send, no-image fallback, and send-failure fallback.
  - Decide whether to accept, revise, or reject the test coverage.

- Review `README.md` diff for updated Telegram bot documentation.
  - Verify new env vars (`MAX_IMAGES_PER_ITERATION`, `SEND_COOLDOWN_SECONDS`) are documented.
  - Verify `/admin` photo behavior and sender safeguards are described accurately.
  - Decide whether to accept, revise, or reject the documentation.

## New Review Items (TASK-002 Telegram image delivery design)

- Review `docs/TELEGRAM_IMAGE_DELIVERY_DESIGN.md`.
  - Verify affected services, modules, data flows, and interfaces are accurate.
  - Verify implementation approach covers: concurrency guard with `asyncio.Lock`,
    per-iteration send cap, time-based duplicate bypass cooldown, and `/admin`
    sending the latest image file.
  - Verify key tradeoffs are documented with rationale (guard placement, cap
    boundary, cooldown source, image send method, bypass scope).
  - Verify risks and mitigations are adequate (overlap with pending `tg_bot`
    changes, cooldown sending unwanted frames, cap delaying bursts, large file
    limits, timestamp loss on restart).
  - Verify no scope expansion into camera capture, triage pipeline, web viewer,
    object detection, or container infrastructure.
  - Decide whether to accept, revise, or reject the design.
  - If accepted, prepare a TASK-003 implementation job.

## New Review Items (TASK-001 Telegram image delivery scope)

- Review `docs/TELEGRAM_IMAGE_DELIVERY_SCOPE.md`.
  - Verify minimum deliverable covers: concurrency guard for `image_sender_job`,
    per-iteration send cap (default 5), time-based duplicate bypass cooldown
    (default 300s), and `/admin` sending the latest image file.
  - Verify acceptance criteria are measurable and exclusions are explicit.
  - Verify no scope expansion into camera capture, triage pipeline, web viewer,
    or object detection model changes.
  - Decide whether to accept, revise, or reject the scope.
  - If accepted, prepare a TASK-002 design job.

## New Review Items (TASK-005 web admin page documentation)

- Review `docs/WEB_VIEWER_RUNBOOK.md` for the web viewer `/admin` page increment.
  - Verify `/admin` endpoint behavior, static file serving, configuration,
    local development steps, Docker Compose operating steps, validation commands,
    and troubleshooting table are accurate.
  - Verify `README.md` web viewer section and runbook references are correct.
  - Decide whether to accept, revise, or reject the documentation.

## New Review Items (TASK-004 web admin page QA validation)

- Review `tests/test_web_viewer.py` diff for 14 new QA tests.
  - Verify `_read_latest_summary` OSError path returns None.
  - Verify `_get_latest_run_date` OSError returns None; single date dir returned correctly.
  - Verify `_get_latest_image_links` caps at 5, filters by extension, ignores subdirectories,
    and returns empty list on OSError.
  - Verify `_is_fresh` invalid date string returns False.
  - Verify `_render_admin_page` with None summary shows error with zeroed counts.
  - Verify `_render_admin_page` with no links shows "No images found".
  - Verify `_render_admin_page` with fresh=False shows "Stale" (not "Fresh").
  - Verify non-car/person object types (truck, bicycle) are not rendered in stats.
  - Verify static file 404 for non-existent path.
  - Verify admin page renders with error and "Unknown" date when no data exists.
  - Decide whether to accept, revise, or reject the QA tests.

## New Review Items (TASK-003 web admin page implementation)

- Review `web_viewer/app.py`, `web_viewer/Dockerfile`, `web_viewer/requirements.txt`
  diff for the web viewer `/admin` page increment.
  - Verify `/admin` renders HTML with run date, freshness, total/kept counts,
    car/person counts, missing expected count, and image links.
  - Verify missing/malformed `triage_summary.json` renders error message without crash.
  - Verify static file URLs (`/YYYY-MM-DD/frame.jpg`) continue to work.
  - Decide whether to accept, revise, or reject the implementation.

- Review `docker-compose.yml` diff for the `web_viewer` service replacement.
  - Verify `build: ./web_viewer`, volume mount, port mapping, and healthcheck.
  - Verify container recreate step is documented in `README.md`.
  - Decide whether to accept, revise, or reject the infrastructure changes.

- Review `tests/test_web_viewer.py` diff for 14 new tests.
  - Verify test coverage for `/admin` HTML response, missing/malformed JSON,
    static file serving, default counts, missing expected objects, and helper units.
  - Decide whether to accept, revise, or reject the test coverage.

- Review `README.md` diff for web viewer documentation.
  - Verify `/admin` URL, stats displayed, error behavior, static file preservation,
    and container recreate step are documented.
  - Decide whether to accept, revise, or reject the documentation.

## New Review Items (TASK-002 web admin page design)

- Review `docs/WEB_ADMIN_PAGE_DESIGN.md` for the web viewer `/admin` page increment.
  - Verify affected services, modules, data flows, and interfaces are accurate.
  - Verify implementation approach (Flask replacing nginx) and tradeoffs are acceptable.
  - Verify risks and mitigations are adequate (performance, schema dependency, static file regression).
  - Decide whether to accept, revise, or reject the design.
  - If accepted, prepare a TASK-003 implementation job.

## New Review Items (TASK-001 web admin page scope)

- Review `docs/WEB_ADMIN_PAGE_SCOPE.md` for the web viewer `/admin` page increment.
  - Verify minimum deliverable covers: static file serving preserved, `/admin`
    HTML page with triage stats (total images, kept images, car/person counts,
    missing expected objects), latest run date, freshness indicator, and links
    to latest images.
  - Verify acceptance criteria are measurable and exclusions are explicit.
  - Verify container status display, video player, authentication, real-time
    updates, REST API, and Telegram bot changes are explicitly excluded.
  - Decide whether to accept, revise, or reject the scope.

## New Review Items (TASK-004 /state QA validation)

- Review `tests/test_tg_bot.py` diff for 8 new QA tests.
  - Verify `_query_container_states` DockerException path returns None.
  - Verify `_query_container_states` dict structure (name, status, health, started_at).
  - Verify `_query_container_states` mixed found/not-found containers.
  - Verify `_query_container_states` calls `client.close()` on success path.
  - Verify `_query_container_states` defaults health to "N/A" when no Health key.
  - Verify `_format_uptime` nanosecond truncation and minutes-only formatting.
  - Verify `_format_state_message` emoji mapping for all status values.
  - Decide whether to accept, revise, or reject the QA tests.

## New Review Items (TASK-003 /state command implementation)

- Review `tg_bot/bot.py` diff for the Telegram `/state` command increment.
  - Verify `_query_container_states()` uses Docker SDK and handles `DockerException`.
  - Verify `_format_state_message()` renders running/exited/not-found/restarting with emoji, health, and uptime.
  - Verify `state_command()` reuses `_is_admin_chat()` and silently ignores non-admin chats.
  - Verify runtime-unavailable path replies with "Container runtime unavailable. Docker socket not mounted?"
  - Decide whether to accept, revise, or reject the implementation.

- Review `tests/test_tg_bot.py` diff for new `/state` tests.
  - Verify tests cover formatting, uptime, admin restriction, runtime-unavailable error, and Markdown parse_mode.
  - Decide whether to accept, revise, or reject the test coverage.

- Review `tg_bot/requirements.txt` and `docker-compose.yml` changes.
  - Verify `docker` package is added and read-only socket mount is present.
  - Decide whether to accept, revise, or reject the infrastructure changes.

- Review `README.md` diff for `/state` documentation.
  - Verify `/state` behavior, Docker socket requirement, and container recreate step are documented.
  - Decide whether to accept, revise, or reject the documentation.

## New Review Items (TASK-005 /state documentation)

- Review `docs/TG_BOT_RUNBOOK.md` for the Telegram `/state` command increment.
  - Verify runbook covers `/admin` and `/state` command behavior, environment variables,
    Docker socket setup, local and Docker Compose operating steps, validation commands,
    and troubleshooting table.
  - Verify security notes (read-only mount, no container control, admin restriction) are present.
  - Decide whether to accept, revise, or reject the documentation.

## Completed Increments (Implementation)

- TASK-005 documentation for "Change /admin: add web server page with cars and"
  completed on 2026-06-19.
  - Verified `README.md` web viewer section against `web_viewer/app.py` implementation.
  - Created `docs/WEB_VIEWER_RUNBOOK.md` with `/admin` behavior, static file serving,
    configuration, operating steps, validation commands, and troubleshooting.
  - Updated project status docs (`PROJECT_STATUS_MEMORY.md`, `NEXT_ACTIONS.md`,
    `PROJECT_MANAGER.yaml`, `DEVELOPMENT_LOG.md`).
  - All 28 web_viewer tests pass; all 127 total tests pass. `py_compile` clean.
  - Status: `review_required`.

- TASK-003 implementation for "add to command /state info about running containers" completed on 2026-06-19.
  - Added `docker` package to `tg_bot/requirements.txt`.
  - Added read-only Docker socket mount to `docker-compose.yml`.
  - Implemented `/state` command in `tg_bot/bot.py` with Docker SDK query, human-readable uptime,
    and admin restriction.
  - Added 12 focused tests in `tests/test_tg_bot.py`; all 39 tg_bot tests pass.
  - All 52 snapshot triage tests pass. `py_compile` clean.
  - Updated `README.md` with `/state` command docs and Docker socket requirement.
  - Status: `review_required`.

- TASK-002 design for "add to command /state info about running containers" completed on 2026-06-19.
  - Documented affected services (`tg_bot/bot.py` primary; Docker Engine runtime dependency),
    modules, data flows, and interfaces in `docs/STATE_COMMAND_DESIGN.md`.
  - Recommended Docker SDK for Python with read-only Docker socket mount.
  - Documented 5 key tradeoffs: runtime access method, socket security, auth reuse,
    uptime representation, error handling.
  - Status: `review_required`.

- TASK-005 documentation for "add to command /state info about running containers" completed on 2026-06-19.
  - Verified `README.md` Telegram bot section against `tg_bot/bot.py` implementation.
  - Created `docs/TG_BOT_RUNBOOK.md` with command behavior, Docker socket setup,
    operating steps, validation commands, and troubleshooting table.
  - Updated project status docs (`PROJECT_STATUS_MEMORY.md`, `NEXT_ACTIONS.md`,
    `PROJECT_MANAGER.yaml`, `DEVELOPMENT_LOG.md`).
  - All 47 tg_bot tests pass; all 52 snapshot triage tests pass. `py_compile` clean.
  - Status: `review_required`.

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