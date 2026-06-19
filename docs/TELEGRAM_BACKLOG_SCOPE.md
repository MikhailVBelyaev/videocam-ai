# Telegram Image Backlog Problem Scope (TASK-001)

Job ID: 2026-06-19_151143_videocam-ai-fix-remaining-telegram-image-backlog-problem-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19

## Problem Statement

After a restart or deploy, the Telegram bot starts with no `.last_sent_file` state.
In this situation `_send_new_images_iteration()` begins from the *first* (oldest)
image in the latest dated folder and walks through every image, skipping most as
"too similar" to the (non-existent) last-sent image. This creates an unnecessary
backlog drain loop:

- The bot wastes iterations comparing old frames.
- Log noise increases with "Skipped ... (too similar)" messages.
- Fresh images captured after restart are delayed until the old backlog is scanned.

Production on `068948f` currently loops over old `2026-06-18` images after each
restart instead of resuming from the latest existing image.

## Current Baseline

- `tg_bot/bot.py` loads `LAST_SENT_FOLDER` and `LAST_SENT_IMAGE` from
  `output/.last_sent_file` in `main()`.
- If the file is missing or empty, both globals are `None`.
- `_send_new_images_iteration()` then sets `start_index = 0` and iterates through
  **all** images in the latest dated folder.
- Perceptual-hash similarity against `LAST_SENT_IMAGE` skips most frames, but the
  loop still touches every file.
- Concurrency guard (`asyncio.Lock`), send cap (`MAX_IMAGES_PER_ITERATION`),
  and cooldown bypass (`SEND_COOLDOWN_SECONDS`) are already in place from the
  previous increment.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that eliminates the restart backlog drain.

Included:
1. **Startup state initialization** in `tg_bot/bot.py`. When `load_last_sent_file()`
   returns `(None, None)` on startup, scan the latest dated folder for the most
   recently modified image file and initialize `LAST_SENT_IMAGE` and
   `LAST_SENT_FOLDER` to that file and its folder **without sending it**.
   This makes the next scheduled iteration start from the image *after* the
   initialized one, effectively only processing newly arriving frames.
2. **Focused unit tests** covering:
   - no-state startup with images → initialized to latest image.
   - no-state startup with empty folder → remains `None`.
   - no-state startup with no dated folders → remains `None`.
   - existing `.last_sent_file` present → behavior unchanged.
3. **README / TG_BOT_RUNBOOK update** noting that on first start or restart
   without persisted state the bot resumes from the latest existing image rather
   than draining the folder.

## Measurable Acceptance Criteria

- When `output/.last_sent_file` does not exist on startup, `LAST_SENT_IMAGE` is
  set to the absolute path of the most recently modified image in the latest
  dated folder, and `LAST_SENT_FOLDER` is set to that folder name.
- The first scheduled `_send_new_images_iteration()` after such a startup begins
  from the image *after* the initialized one, not from the first image in the
  folder.
- If the latest dated folder contains no image files, startup leaves
  `LAST_SENT_IMAGE` as `None`.
- If `OUTPUT_DIR` contains no dated folders, startup leaves `LAST_SENT_IMAGE`
  as `None`.
- Existing behavior when `.last_sent_file` exists is unchanged (no regression).
- Existing concurrency guard, send cap, cooldown bypass, `/admin`, and `/state`
  behaviors are unchanged.
- `py_compile` passes on `tg_bot/bot.py`.
- All existing tg_bot tests continue to pass.

## Explicit Exclusions

- No changes to the image-sending loop logic, perceptual-hash comparison, or
  similarity threshold.
- No changes to the concurrency guard, send cap, or cooldown bypass logic.
- No changes to `/admin` or `/state` command behavior.
- No changes to the camera capture pipeline, triage pipeline, or web viewer.
- No new database, persistent queue, or state mechanism beyond the existing
  `.last_sent_file`.
- No REST API or webhook changes; the bot continues to use polling.
- No container infrastructure changes in `docker-compose.yml`.
- No removal of the existing duplicate filter.
- No changes to `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID`, or admin
  restriction logic.
- No deployment scripts or host-specific configuration.

## Assumptions

- `OUTPUT_DIR` contains dated subfolders (`YYYY-MM-DD/`) with image files.
- The most recently modified image in the latest folder is an acceptable proxy
  for "already processed" on restart.
- The existing `_get_latest_image_path()` helper (or equivalent logic) can be
  reused for the startup scan.
- Images are added to the latest folder in roughly chronological order by
  modification time.

## Risks

1. **Most recent image may never have been sent.** If the sender was down while
   triage continued copying images, initializing to the latest file will skip
   that one frame on restart. Mitigation: this is acceptable for restart
   recovery; the alternative is draining the entire folder, which is the current
   problematic behavior.
2. **Clock skew or backdated files may misorder images.** If file modification
   times are unreliable, the initialized pointer could be wrong. Mitigation:
   the project already relies on `mtime` for freshness checks; this scope does
   not introduce new time-based logic.
3. **Scope overlap with pending Telegram delivery reviews.** This increment
   touches `tg_bot/bot.py`, which has prior TASK-003/004/005 changes in
   `review_required`. Mitigation: the scope document should be reviewed and
   accepted, then the design prepared, before implementation begins.
