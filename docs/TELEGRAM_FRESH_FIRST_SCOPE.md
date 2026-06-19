# Telegram Ignore Old Backlog and Process Fresh Live — Scope (TASK-001)

Job ID: 2026-06-19_172411_videocam-ai-ignore-old-telegram-image-backlog-and-process-fr-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19

## Problem Statement

In production the Telegram bot processes backlog frames oldest-first, delaying delivery of fresh live frames. Logs show the sender iterating over old files such as `frame_2026-06-18 23:59:54.jpg` while newer frames captured minutes ago wait in queue. The current `_send_new_images_iteration()` sorts images alphabetically (ascending) and walks forward from the `LAST_SENT_IMAGE` cursor, so any unsent backlog in the current folder is drained before fresh frames are considered. There is no time-based filter to skip truly stale files, and `/admin` gives no visibility into backlog depth or how recently the last frame was captured versus sent.

Prior increments added:

- concurrency guard, per-iteration send cap, cooldown bypass
- startup state initialization (prevents restart backlog drain)
- triage-aware `kept/` preference and perceptual-hash threshold increase
- send statistics counters (`_SENT_COUNT`, `_SKIPPED_DUPLICATE_COUNT`, `_SKIPPED_NON_KEPT_COUNT`)

These improve quality and prevent spirals but **do not** change the fundamental oldest-first traversal order or suppress stale files based on absolute age.

### Specific Failure Modes

1. **Oldest-first backlog drain**: Within the current dated folder, unsent images are processed in alphabetical order. If the bot falls behind (e.g., due to a cap, cooldown, or temporary downtime), fresh frames are stuck behind older ones.
2. **No absolute-age filter**: A frame from eight hours ago is treated the same as a frame from two minutes ago. There is no configurable cutoff to ignore stale files.
3. **Limited operator visibility**: `/admin` shows total sent and skipped counts but does not report backlog size, the age of the newest capture, the time of the last successful send, or the reason the most recent frame was skipped.

## Current Baseline

- `tg_bot/bot.py` uses `_get_image_list()` which returns `sorted(files)` (alphabetical ascending).
- `_send_new_images_iteration()` determines `start_index` from `LAST_SENT_IMAGE` in that ascending list, then iterates `image_files[start_index:]` in order.
- Perceptual-hash similarity and cooldown bypass decide whether to send or skip each frame.
- `send_photo()` updates `LAST_SENT_IMAGE`, `LAST_SENT_FOLDER`, `_LAST_SENT_TIMESTAMP`, and `.last_sent_file`.
- `MAX_IMAGES_PER_ITERATION` caps sends per tick; `_SENDER_LOCK` prevents overlap.
- `/admin` displays `_SENT_COUNT`, `_SKIPPED_DUPLICATE_COUNT`, and `_SKIPPED_NON_KEPT_COUNT`.
- `IMAGE_SIMILARITY_THRESHOLD` (default 10) and `SEND_COOLDOWN_SECONDS` (default 300) are already configurable via env vars.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session, that makes the sender prioritize fresh frames and skip stale ones while preserving existing cursor stability.

### Included

1. **Newest-first processing of remaining unsent images.** After computing `start_index` using the stable ascending-sorted list (so the `LAST_SENT_IMAGE` cursor remains correct), sort the sub-list `image_files[start_index:]` by file modification time descending. The freshest unsent frames are sent before older backlog frames within the same iteration, while new arrivals that sort after the cursor in ascending order are still reached correctly on subsequent ticks.

2. **Configurable max-age staleness filter.** Add `MAX_IMAGE_AGE_SECONDS` env var (default 3600 seconds = 1 hour). In `_send_new_images_iteration()`, skip individual images whose `mtime` is older than `now - MAX_IMAGE_AGE_SECONDS`. Increment a new `_SKIPPED_STALE_COUNT` counter.

3. **Extended `/admin` counters and timestamps:**
   - `_SKIPPED_STALE_COUNT`: images skipped because they exceeded `MAX_IMAGE_AGE_SECONDS`.
   - `latest capture time`: timestamp of the newest image in the current folder (from `mtime`).
   - `latest sent time`: formatted `_LAST_SENT_TIMESTAMP` (or "Never" if zero).
   - `backlog size`: count of unsent images remaining in the current folder after the cursor.
   - `last skipped reason`: most recent skip reason string (`"similar"`, `"non-kept"`, `"stale"`, or `""`).

4. **Focused unit tests** for:
   - `_get_image_list()` returning mtime-descending order when called for the newest-first sub-list sort.
   - Newest-first behavior sending the fresher of two pending images before the older one.
   - Max-age filter skipping an old file and incrementing `_SKIPPED_STALE_COUNT`.
   - `/admin` message including new fields (stale counter, backlog size, latest times, last reason).
   - Backward compatibility when `MAX_IMAGE_AGE_SECONDS` is not set (default 3600 applies).

5. **README / TG_BOT_RUNBOOK update** documenting `MAX_IMAGE_AGE_SECONDS`, newest-first behavior, and new `/admin` fields.

### NOT Included (Exclusions)

- No changes to the triage pipeline (`cams_grabber/snapshot_triage.py`).
- No changes to the `kept/` preference logic or `_kept_images_exist()` / `_get_image_list()` fallback behavior.
- No changes to perceptual-hash similarity, `IMAGE_SIMILARITY_THRESHOLD`, or cooldown bypass logic.
- No changes to concurrency guard, send cap, or startup initialization.
- No persistent statistics database or file; counters and skipped-reason remain in-memory and reset on restart.
- No changes to `/state` command or web viewer.
- No changes to camera capture, Docker infrastructure, or deployment scripts.
- No removal or replacement of `.last_sent_file` cursor persistence.
- No set-based deduplication beyond the existing `LAST_SENT_IMAGE` cursor.

## Measurable Acceptance Criteria

- When two or more unsent images exist in the current folder, `_send_new_images_iteration()` sends the image with the more recent modification time before the older one (newest-first within the remaining window).
- Images whose `mtime` is older than `MAX_IMAGE_AGE_SECONDS` (default 3600) are skipped, and `_SKIPPED_STALE_COUNT` increments exactly once per skipped stale image.
- When `MAX_IMAGE_AGE_SECONDS` env var is set to a custom value, that value is used; when unset, the default 3600 is used; when set to a non-integer string, the default 3600 is used (graceful fallback).
- `/admin` text summary includes:
  - `Skipped (stale): N`
  - `Backlog size: N`
  - `Latest capture: <timestamp or "Unknown">`
  - `Latest sent: <timestamp or "Never">`
  - `Last skip reason: <reason or "—">`
- Existing `LAST_SENT_IMAGE` cursor behavior is preserved: new images that arrive after the cursor position are not skipped due to the newest-first re-sort (verified by test).
- Existing concurrency guard, send cap, cooldown bypass, triage-aware selection, startup initialization, `/state`, and image-sending behavior outside the new age/filtering are preserved (no regression).
- `py_compile` passes on all modified Python files.
- All existing tg_bot tests continue to pass.
- New tests cover newest-first ordering, max-age filter, stale counter, and `/admin` extended fields.

## Assumptions

- File modification times are a reasonable proxy for capture time. The project already relies on `mtime` for freshness checks in `_get_latest_image_path()` and `_summarize_live_output()`.
- A default `MAX_IMAGE_AGE_SECONDS=3600` (one hour) is a reasonable starting cutoff for street-camera content; operators can tune it.
- The existing ascending sort is retained only for cursor alignment (`start_index` lookup). The actual sending order is determined by a secondary descending-mtime sort on the remaining sub-list.
- Backlog size is computed from the current folder only, not across all historical folders.

## Risks

1. **Clock skew or backdated files may misorder images.** If `mtime` is unreliable, newest-first sorting may send frames out of true chronological order. Mitigation: the project already relies on `mtime` for other features; this scope does not introduce new time-based dependencies.
2. **Very high max-age may not suppress enough stale files; very low max-age may suppress legitimate frames.** Mitigation: the threshold is configurable via env var; operators can tune based on observed camera interval and traffic patterns.
3. **In-memory counters and last-reason reset on restart.** Mitigation: acceptable for a first increment; persistent statistics can be added in a future increment.
4. **Scope overlap with pending Telegram reviews.** This increment touches `tg_bot/bot.py`, which has prior TASK-003/004/005 changes in `review_required`. Mitigation: ensure prior tasks are accepted and committed before implementing this scope, or rebase on the accepted state.
