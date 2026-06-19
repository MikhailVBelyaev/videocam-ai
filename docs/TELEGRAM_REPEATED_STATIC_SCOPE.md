# Telegram Repeated Static/Latest Delivery Fix — Scope (TASK-001)

Job ID: 2026-06-19_163018_videocam-ai-fix-production-telegram-image-delivery-bot-sends-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19

## Problem Statement

In production, the Telegram bot sends repeated near-identical static/parked-car frames
while missing genuine street events. The core issue is that the sender has no awareness
of image quality, triage decisions, or scene staleness — it sends every frame that
passes a low perceptual-hash similarity threshold against a single reference image,
regardless of whether the triage pipeline classified it as "kept" or "rejected."

Prior increments added:

- concurrency guard (`asyncio.Lock`) for `image_sender_job`
- per-iteration send cap (`MAX_IMAGES_PER_ITERATION`, default 5)
- time-based duplicate bypass cooldown (`SEND_COOLDOWN_SECONDS`, default 300)
- `/admin` latest image file send
- startup state initialization (backlog drain prevention)

These address overlap and backlog spirals but **do not** solve the fundamental problem
that the bot sends near-identical static frames and has no quality or triage awareness.

### Specific Failure Modes

1. **Static-scene flooding**: A parked car produces frames that differ just enough in
   perceptual hash (threshold=5) to bypass the similarity filter, resulting in near-
   identical images sent every few iterations.
2. **No triage awareness**: The sender iterates over ALL images in the dated folder,
   including frames the triage pipeline already rejected as blurry, dark, or low
   quality. It does not consult `triage_summary.json` or the `kept/` subfolder.
3. **No staleness detection**: If the camera stops producing frames, the sender goes
   silent. `/admin` shows stats but gives no indication that output is stale or that
   no images have been sent recently.
4. **No send statistics**: There are no counters for sent, skipped, or duplicate
   frames. Operators have no way to know how many images were suppressed as
   near-duplicates vs. actually delivered.

## Current Baseline

- `tg_bot/bot.py` uses `python-telegram-bot` `Application` with `JobQueue`.
- `image_sender_job` runs every 5 seconds; acquires `_SENDER_LOCK` and delegates to
  `_send_new_images_iteration()` via `asyncio.to_thread()`.
- `_send_new_images_iteration()` iterates image files in `OUTPUT_DIR/YYYY-MM-DD/`,
  starting from the file after `LAST_SENT_IMAGE`. For each file:
  - Compares perceptual hash against `LAST_SENT_IMAGE` (threshold=5).
  - If similar AND cooldown has NOT expired: skip.
  - If similar AND cooldown HAS expired: send (this directly causes repeated static
    frames).
  - If not similar: send.
  - Caps sends at `MAX_IMAGES_PER_ITERATION` (5).
- `are_images_similar()` uses `imagehash.average_hash()` with a fixed threshold.
- `send_photo()` updates `LAST_SENT_IMAGE`, `LAST_SENT_FOLDER`,
  `_LAST_SENT_TIMESTAMP`, and `.last_sent_file` on success.
- `cleanup_old_folders()` removes date folders older than `KEEP_DAYS` (3).
- `OUTPUT_DIR/YYYY-MM-DD/kept/` contains triage-kept frames (copied by
  `snapshot_triage.py`).
- `OUTPUT_DIR/triage_summary.json` contains quality statistics and `kept_frames`
  list with filenames and quality ranks.
- `/admin` reads `triage_summary.json` (or falls back to `_summarize_live_output`)
  and sends a Markdown summary plus the latest image file.
- `/state` queries Docker for container status.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that makes image delivery triage-aware and reduces static-scene flooding.

### Included

1. **Triage-aware image selection** in `_send_new_images_iteration()`. When
   `OUTPUT_DIR/YYYY-MM-DD/kept/` exists and is non-empty, prefer sending images
   from the `kept/` subfolder instead of the date folder root. Skip images that are
   not in the `kept/` list. This eliminates sending frames already rejected by triage.

2. **Perceptual-hash threshold increase** for static-scene filtering. Raise the
   default `are_images_similar()` threshold from 5 to a configurable value
   (env var `IMAGE_SIMILARITY_THRESHOLD`, default 10). Higher threshold means more
   near-identical frames are suppressed. This directly addresses the "repeated
   static/latest" problem.

3. **Send statistics counters** in module-level variables:
   - `_SENT_COUNT`: total images successfully sent since startup.
   - `_SKIPPED_DUPLICATE_COUNT`: images skipped due to similarity/cooldown.
   - `_SKIPPED_NON_KEPT_COUNT`: images skipped because they were not in `kept/`.
   These counters are included in the `/admin` text summary.

4. **Focused unit tests** for:
   - `_kept_images_exist()` helper returning True/False for kept subfolder presence.
   - `_send_new_images_iteration()` preferring kept images when available and falling
     back to all images when no kept subfolder exists.
   - Send statistics counters incrementing correctly.
   - `/admin` output including the new statistics fields.
   - Threshold value read from env var with correct default.

5. **README / TG_BOT_RUNBOOK update** documenting the new behavior, env var,
   and send statistics.

### NOT Included (Exclusions)

- No changes to the triage pipeline (`cams_grabber/snapshot_triage.py`).
- No changes to the web viewer or `/state` command.
- No changes to camera capture pipeline or `cams_grabber` service.
- No staleness detection or "no new images" alerting (this is a separate increment).
- No persistent send-log database or file; statistics are in-memory and reset on
  restart (acceptable for now).
- No changes to Docker infrastructure or deployment.
- No removal of `SEND_COOLDOWN_SECONDS`; the cooldown bypass remains, but with a
  higher similarity threshold fewer cooldown-forced sends will be near-identical.
- No changes to `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID`, or admin restriction.
- No motion detection or object-detection inference in `tg_bot`; it relies on the
  triage pipeline's `kept/` output.

## Measurable Acceptance Criteria

- When `OUTPUT_DIR/YYYY-MM-DD/kept/` exists and contains image files,
  `_send_new_images_iteration()` only iterates over images in `kept/`, not the
  date folder root. Images not in `kept/` are skipped and counted in
  `_SKIPPED_NON_KEPT_COUNT`.
- When `kept/` does not exist or is empty, `_send_new_images_iteration()` falls
  back to iterating all images in the date folder root (backward-compatible
  behavior with no triage pipeline).
- `are_images_similar()` uses `IMAGE_SIMILARITY_THRESHOLD` env var (default 10)
  instead of hardcoded 5. Frames within threshold 10 of the last sent image are
  suppressed unless the cooldown has expired.
- `/admin` text summary includes three new lines:
  `Sent: N`, `Skipped (similar): N`, `Skipped (non-kept): N`.
- `IMAGE_SIMILARITY_THRESHOLD` env var is documented in README and runbook.
- Existing concurrency guard, send cap, cooldown bypass, startup initialization,
  `/state`, and image-sending behavior outside the new filtering are preserved
  (no regression).
- `py_compile` passes on all modified Python files.
- All existing tg_bot tests continue to pass.
- New tests cover triage-aware selection, threshold env var, and send statistics.

## Assumptions

- The `kept/` subfolder is created by `cams_grabber/snapshot_triage.py` when it runs.
  It may not exist if triage has not run yet, or may be empty on a fresh day.
- File basenames in `kept/` are a subset of file basenames in the date folder root.
  The triage pipeline copies (not renames) kept files, so basenames match.
- The triage pipeline runs independently and may not always have produced `kept/`
  before the sender ticks. The fallback to all images handles this case.
- `IMAGE_SIMILARITY_THRESHOLD=10` is a reasonable starting default for street-camera
  content; operators can tune it. The perceptual hash algorithm is unchanged.

## Risks

1. **Kept-folder lag**: If triage runs infrequently or falls behind, the `kept/`
   folder may not contain the most recent frames, and the sender will skip them
   until triage catches up. Mitigation: fallback to all images when `kept/` is
   missing or empty; no frames are permanently lost, only delayed.
2. **Higher threshold may suppress real changes**: Raising the perceptual-hash
   threshold from 5 to 10 means more frames are classified as "similar" and
   suppressed. Mitigation: the threshold is configurable; the cooldown bypass
   still forces a send every `SEND_COOLDOWN_SECONDS` for genuinely new
   (non-similar) content that just happens to be within threshold.
3. **In-memory statistics reset on restart**: Send counters are lost when the
   bot restarts. Mitigation: this is acceptable for a first increment; persistent
   statistics can be added in a future increment.
4. **Scope overlap with pending reviews**: This increment touches `tg_bot/bot.py`,
  which has prior TASK-003/004/005 changes in `review_required`. Mitigation: ensure
  prior tasks are accepted and committed before implementing this scope, or rebase
  on the accepted state.