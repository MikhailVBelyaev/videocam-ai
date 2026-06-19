# Telegram Bot Folder Advancement Scope (TASK-001)

Job ID: 2026-06-19_190332_videocam-ai-fix-tg-bot-still-stuck-on-old-last-sent-folder-a-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19

## Problem Statement

In production the Telegram bot can become stuck on an old dated folder even when
newer folders with fresh images exist. The root cause is in
`_send_new_images_iteration()` lines 602–605:

```python
if LAST_SENT_FOLDER and LAST_SENT_FOLDER in subfolders:
    folder_index = subfolders.index(LAST_SENT_FOLDER)
else:
    folder_index = len(subfolders) - 1  # Latest folder
```

When `output/.last_sent_file` points to `2026-06-18` and a new folder
`2026-06-19` appears, the condition `LAST_SENT_FOLDER in subfolders` is `True`,
so `folder_index` is pinned to the old folder. The bot iterates only within
`2026-06-18`; if all remaining images there are stale (skipped by the max-age
filter) or already sent, the sender sends zero images per tick but never
advances to `2026-06-19`. Fresh frames in the new folder are never seen.

This bug was masked before the fresh-first increment because old images were
sent oldest-first; after `MAX_IMAGE_AGE_SECONDS` was introduced, old images are
skipped, exposing the lack of folder-level advancement.

### Specific Failure Modes

1. **Stale-folder lock-in:** `LAST_SENT_FOLDER` = older date, all remaining
   images in that folder exceed `MAX_IMAGE_AGE_SECONDS` → every iteration
   skips them with `_SKIPPED_STALE_COUNT += 1`, but `LAST_SENT_FOLDER` never
   changes.
2. **Silent backlog growth:** Operator sees `/admin` stale counts rising and
   backlog size shrinking to zero, yet no new images are sent. There is no
   visibility into *which* folder the bot is watching versus which folder is
   newest.
3. **Post-restart drift:** After a restart, `.last_sent_file` may load an old
   folder. Startup initialization (`_initialize_startup_state()`) only runs
   when `.last_sent_file` is missing, so a stale persisted folder is never
   corrected.

## Current Baseline

- `tg_bot/bot.py` lists dated folders, sorts them ascending, and picks the
  folder at `subfolders.index(LAST_SENT_FOLDER)` when `LAST_SENT_FOLDER` is
  present.
- `_send_new_images_iteration()` computes `start_index` from `LAST_SENT_IMAGE`,
  then sorts remaining images by `mtime` descending (fresh-first) and applies
  the max-age filter, similarity check, and send cap.
- `send_photo()` updates `LAST_SENT_IMAGE`, `LAST_SENT_FOLDER`, and
  `.last_sent_file` only when a photo is actually sent.
- `_format_admin_message()` shows stale count, backlog size, latest capture,
  latest sent, and last skip reason, but does **not** show which folder is
  being watched, what `.last_sent_file` contains, or whether the watched
  folder is the newest.
- `cleanup_old_folders()` deletes folders older than `KEEP_DAYS` (default 3),
  so the stale folder may eventually disappear, but that can take days.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that eliminates stale-folder lock-in and gives the operator visibility into
folder state.

### Included

1. **Folder advancement logic in `_send_new_images_iteration()`.**
   After the send loop completes, if `sent_count == 0` (no image was sent in
   this iteration) and the current folder is **not** the latest dated folder,
   advance `LAST_SENT_FOLDER` to the next dated folder (by ascending date)
   and clear `LAST_SENT_IMAGE` to `None`. Persist the new state via
   `save_last_sent_file()`.

   This allows the next scheduled iteration to start fresh in the next folder.
   If that folder also yields zero sends, the advancement repeats until the
   latest folder is reached.

2. **Latest-folder boundary guard.**
   When the current folder is already the latest dated folder and `sent_count
   == 0`, do **not** advance (there is no newer folder). The bot stays put,
   which is the correct behavior when the latest folder simply has no fresh
   images yet.

3. **`/admin` stuck-state visibility.**
   Extend `_format_admin_message()` to include:
   - `Watched folder`: `LAST_SENT_FOLDER` or `"Unknown"`.
   - `Newest folder`: result of `_get_latest_run_date()` or `"Unknown"`.
   - `State file`: content of `.last_sent_file` or `"not set"`.
   - `Status`: `"Fresh"` when `LAST_SENT_FOLDER == newest folder`, else
     `"Stuck on <folder>"`.

4. **Focused unit tests** for:
   - Old folder with all stale images → advances to newer folder.
   - Old folder with all similar images (cooldown not expired) → advances to
     newer folder.
   - Old folder fully sent (empty remaining) → advances to newer folder.
   - Latest folder with zero sends → stays put, no crash.
   - Normal send in old folder → does **not** advance (backward compatibility).
   - `/admin` message shows correct watched folder, newest folder, state file
     content, and status indicator.

5. **README / TG_BOT_RUNBOOK update** documenting folder advancement behavior,
   the stuck-state `/admin` fields, and a troubleshooting entry for
   "bot stuck on old folder".

### NOT Included (Exclusions)

- No changes to the triage pipeline (`cams_grabber/snapshot_triage.py`).
- No changes to the max-age staleness filter (`MAX_IMAGE_AGE_SECONDS`),
  similarity threshold (`IMAGE_SIMILARITY_THRESHOLD`), or cooldown bypass
  (`SEND_COOLDOWN_SECONDS`).
- No changes to newest-first sub-list sort or `kept/` preference logic.
- No changes to concurrency guard, send cap, startup initialization,
  `load_last_sent_file()`, or `send_photo()` core behavior.
- No changes to `/state` command or web viewer.
- No changes to camera capture, Docker infrastructure, or deployment scripts.
- No persistent statistics database; folder state remains in `.last_sent_file`.
- No automatic deletion or modification of old folders beyond existing
  `cleanup_old_folders()`.
- No new Telegram commands.

## Measurable Acceptance Criteria

- Given `LAST_SENT_FOLDER` points to a non-latest dated folder and all
  remaining images in that folder are skipped (stale, similar within cooldown,
  or non-kept), the next `_send_new_images_iteration()` processes the next
  dated folder (not the old one).
- Given `LAST_SENT_FOLDER` points to the latest dated folder and all images
  are skipped, `LAST_SENT_FOLDER` does not change and no exception is raised.
- Given `LAST_SENT_FOLDER` points to a non-latest folder with at least one
  unsent image that passes all filters, that image is sent and `LAST_SENT_FOLDER`
  remains on that folder (no premature advancement).
- After folder advancement, `.last_sent_file` is updated to reflect the new
  folder and a cleared `LAST_SENT_IMAGE` (format: `new_folder/\n`).
- `/admin` text summary includes:
  - `Watched folder: <folder>`
  - `Newest folder: <folder>`
  - `State file: <content or "not set">`
  - `Status: Fresh` or `Status: Stuck on <folder>`
- Existing concurrency guard, send cap, cooldown bypass, triage-aware selection,
  startup initialization, max-age filter, newest-first ordering, `/state`,
  and image-sending behavior are unchanged (no regression).
- `py_compile` passes on all modified Python files.
- All existing tg_bot tests continue to pass.
- New tests cover folder advancement, latest-folder boundary guard, backward
  compatibility, and `/admin` stuck-state fields.

## Assumptions

- Dated folders are named `YYYY-MM-DD` and sort lexicographically in the same
  order as chronological order.
- Advancing to the next folder when zero images were sent is safe because the
  zero-send condition means all remaining images in the current folder were
  actively filtered out (stale, similar, non-kept), not merely waiting.
- Clearing `LAST_SENT_IMAGE` to `None` on advancement is correct because there
  is no meaningful cursor in the new folder yet; the next iteration will start
  from `start_index = 0`.
- Operator visibility via `/admin` is sufficient for detecting stuck-folder
  situations; no alerting or automated recovery beyond advancement is needed.

## Risks

1. **Advancing past unsent non-stale images.** If an image is skipped only
   because of cooldown (similar within `SEND_COOLDOWN_SECONDS`) and the folder
   advances, that image may never be sent. Mitigation: the cooldown is
   time-based (default 300s); if the bot advances to a newer folder, the old
   image is likely outdated anyway. If needed, operators can lower
   `MAX_IMAGE_AGE_SECONDS` to force stale skipping before cooldown skipping.
2. **Rapid multi-folder advancement on restart.** If several old folders exist
   and all have stale images, the bot may advance through them in successive
   iterations. Mitigation: this is the desired behavior; the bot should reach
   the newest folder quickly. State is persisted after each advancement.
3. **Scope overlap with pending fresh-first reviews.** This increment touches
   `tg_bot/bot.py`, which has prior TASK-003/004/005 fresh-first changes in
   `review_required`. Mitigation: ensure prior tasks are accepted and committed
   before implementing this scope, or rebase on the accepted state.
4. **State file format on cleared LAST_SENT_IMAGE.** Saving `folder/\n` with
   an empty filename must be readable by `load_last_sent_file()` without
   crashing. Mitigation: `load_last_sent_file()` already handles malformed
   lines by returning `(None, None)`; a trailing newline after the slash is
   gracefully handled.
