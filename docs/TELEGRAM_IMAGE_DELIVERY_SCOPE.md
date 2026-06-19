# Telegram Image Delivery and Admin Statistics Scope (TASK-001)

Job ID: 2026-06-19_140208_videocam-ai-fix-production-telegram-image-delivery-and-admin-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19

## Problem Statement

In production, the Telegram bot exhibits three related issues:

1. **Overlapping sender jobs**: `image_sender_job` runs every 5 seconds. If
   `_send_new_images_iteration()` takes longer than 5 seconds (e.g., large backlog
   or slow network), multiple job instances overlap, leading to "maximum running
   instances reached" warnings and unpredictable send behavior.
2. **Backlog loops**: When many unsent images accumulate, a single iteration
   attempts to send all of them. This can take minutes, exacerbating the overlap
   problem and causing the bot to fall further behind.
3. **`/admin` shows text-only summary**: The `/admin` command reports statistics
   but does not send the actual latest image, so an admin cannot immediately see
   what the camera currently sees.

## Current Baseline

- `tg_bot/bot.py` uses `python-telegram-bot` `Application` with `JobQueue`.
- `image_sender_job` is scheduled with `interval=5` via `run_repeating`.
- `_send_new_images_iteration()` iterates through ALL unsent images in the
  current folder, checking perceptual-hash similarity against `LAST_SENT_IMAGE`.
- Similar images are skipped; dissimilar images are sent one-by-one via
  synchronous `requests.post` to the Telegram `sendPhoto` API.
- `send_photo()` updates `LAST_SENT_FILE` and global state after each successful
  send.
- `/admin` reads `output/triage_summary.json` (or falls back to live-output
  heuristic) and returns a Markdown text message.
- No concurrency guard exists; `_send_new_images_iteration()` is a plain
  synchronous function run via `asyncio.to_thread()`.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that makes image delivery predictable and adds the latest image to `/admin`.

Included:
1. **Concurrency guard** in `tg_bot/bot.py` to prevent overlapping
   `image_sender_job` executions. Use a simple lock or running flag so only one
   sender iteration runs at a time.
2. **Per-iteration send cap** to prevent backlog spirals. After sending a fixed
   maximum number of images (e.g., 5) in one iteration, the loop breaks and
   resumes from the next unsent image on the following scheduled tick.
3. **Time-based duplicate bypass** to ensure fresh images are still delivered
   even when consecutive frames are perceptually similar. If no image has been
   sent within a configurable cooldown window (e.g., 5 minutes), the similarity
   check is skipped for the next candidate image.
4. **`/admin` sends the latest image file** in addition to the existing text
   summary. After the Markdown text reply, the bot sends the most recent image
   file from the latest dated folder in `output/`. If no image is available,
   the text summary is sent alone with a note.
5. **Focused unit tests** for the cap logic, cooldown logic, and `/admin` image
   attachment behavior.
6. **Runbook / README update** documenting the new behavior, cap limit, cooldown
   interval, and any new environment variables.

## Measurable Acceptance Criteria

- When `_send_new_images_iteration()` is already running, a second scheduled
  invocation is skipped (no overlap).
- No more than `MAX_IMAGES_PER_ITERATION` (default 5) images are sent in a
  single iteration.
- If the time since the last successful send exceeds `SEND_COOLDOWN_SECONDS`
  (default 300), the next candidate image is sent regardless of perceptual-hash
  similarity.
- Sending `/admin` from the admin chat returns the existing Markdown text summary
  **and** a photo message containing the latest image file from `output/`.
- If the latest dated folder contains no image files, `/admin` returns the text
  summary with a "No latest image available" note and no photo.
- Existing `/admin` text content (stats, freshness, counts) is unchanged.
- Existing `/state` behavior and image-sending behavior outside the new guard/cap
  are preserved (no regression).
- `py_compile` passes on all modified Python files.
- All existing tg_bot tests continue to pass.

## Explicit Exclusions

- No changes to the perceptual-hash algorithm, threshold, or image-comparison
  library.
- No changes to the camera capture pipeline, triage pipeline, or web viewer.
- No batching or album sending; images are still sent individually.
- No new database, persistent queue, or file-based send queue beyond the existing
  `.last_sent_file` state.
- No REST API or webhook changes; the bot continues to use polling.
- No container infrastructure changes in `docker-compose.yml`.
- No removal of the existing duplicate filter; the cooldown is an additive bypass.
- No changes to `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID`, or admin
  restriction logic.
- No deployment scripts or host-specific configuration.

## Assumptions

- The `python-telegram-bot` JobQueue continues to schedule `image_sender_job`
  with a fixed interval.
- `OUTPUT_DIR` contains dated subfolders (`YYYY-MM-DD/`) with image files.
- Telegram `sendPhoto` API remains the transport for image delivery.
- The test environment can mock filesystem state, Telegram API responses, and
  time for unit testing.
- A `threading.Lock` or `asyncio.Lock` is sufficient for concurrency control
  given the current `asyncio.to_thread()` wrapper.

## Risks

1. **Cooldown bypass may send unwanted similar frames.** If the camera is
   stationary and the scene unchanged, the forced send will post a nearly
   identical image. Mitigation: the cooldown is configurable; operators can tune
   it or disable it by setting a very large value.
2. **Cap may delay delivery during high-activity bursts.** If more than 5
   distinct images arrive within 5 seconds, some will wait for the next tick.
   Mitigation: 5 images per 5 seconds is a high rate for this use case; the cap
   is documented and can be adjusted.
3. **`/admin` image send may fail for large files.** Telegram has a 10 MB photo
   limit and a 20 MB document limit. Mitigation: camera frames are expected to
   be well under these limits; if a file is too large, the bot catches the error
   and returns text only.
4. **Scope overlap with pending `/admin` and `/state` reviews.** This increment
   touches the same file (`tg_bot/bot.py`) as prior TASK-003 implementations.
   Mitigation: ensure prior tasks are accepted and committed before implementing
   this scope, or rebase on the accepted state.
