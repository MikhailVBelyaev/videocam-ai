# Telegram Bot Runbook

## Purpose

Operate the `tg_bot` service that sends new camera frames to Telegram and responds
to admin commands.

## Environment Variables

Configure these in `tg_bot/.env`:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_TOKEN` | Yes | — | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Default chat ID for image posts |
| `TELEGRAM_ADMIN_CHAT_ID` | No | `TELEGRAM_CHAT_ID` | Chat ID authorized for `/admin` and `/state` |
| `MAX_IMAGES_PER_ITERATION` | No | `5` | Maximum images sent in one 5-second sender tick |
| `SEND_COOLDOWN_SECONDS` | No | `300` | Seconds after which the duplicate filter is bypassed for the next candidate |
| `IMAGE_SIMILARITY_THRESHOLD` | No | `10` | Perceptual hash distance threshold; images within this distance of the last sent image are skipped as duplicates |
| `MAX_IMAGE_AGE_SECONDS` | No | `3600` | Maximum age in seconds for an image to be considered fresh enough to send; older images are skipped as stale |

## Image Sender Safeguards

The bot polls `output/` every 5 seconds and posts new images to `TELEGRAM_CHAT_ID`.
The sender includes three production safeguards:

### 1. Concurrency Guard

`image_sender_job` is scheduled every 5 seconds. If a previous iteration is still
running (e.g., slow network or large backlog), the new invocation is skipped
instead of overlapping.

- Implementation: `asyncio.Lock` acquired at the async boundary
- Behavior: locked → log "Skipping overlapping image_sender_job" and return
- Resume: the next 5-second tick continues from the last unsent image

### 2. Per-Iteration Send Cap

At most `MAX_IMAGES_PER_ITERATION` images are sent in a single tick. Remaining
images resume on the next tick.

- Default: 5 images per 5-second tick
- Boundary: the cap is enforced inside `_send_new_images_iteration()` after each
  successful `send_photo()`
- Resume: `LAST_SENT_IMAGE` is updated per successful send, so the next tick
  naturally continues from the next unsent image

### 3. Cooldown Bypass

If no image has been sent for `SEND_COOLDOWN_SECONDS`, the next candidate image
is delivered even if it is perceptually similar to the last sent image.

- Default: 300 seconds (5 minutes)
- Scope: bypass applies to **one candidate only**. After that send, the timestamp
  updates and normal similarity filtering resumes for the remainder of the iteration.
- Purpose: prevents the bot from going silent when the scene is static

## Triage-aware Image Sending

When snapshot triage has been run, it writes kept images into a `kept/`
subfolder inside each dated output folder (e.g. `output/2026-06-19/kept/`).
The bot uses these triage results to decide which images to send:

- **Prefer `kept/` images** — when a `kept/` subfolder exists, only images
  listed in it are candidates for sending. Images that exist in the root
  dated folder but not in `kept/` are skipped and counted as **non-kept**.
- **Fallback to full folder** — when no `kept/` subfolder exists, all images
  in the dated folder are candidates (unchanged behavior).
- **Similar-image skipping** — candidates whose perceptual hash distance from
  the last sent image is ≤ `IMAGE_SIMILARITY_THRESHOLD` are skipped and
  counted as **similar duplicates**. Default threshold is 10; raise it to
  allow more visual variation through, lower it to be stricter.
| **Send statistics** — the `/admin` command appends lines showing:
  `Sent: N`, `Skipped (similar): N`, `Skipped (non-kept): N`, `Skipped (stale): N`,
  `Backlog size: N`, `Latest capture: <timestamp>`, `Latest sent: <timestamp>`,
  `Last skip reason: <reason>`.

These counts reset on each bot process restart.

## Newest-First Processing

Within the remaining unsent window, the sender re-sorts images by file
modification time (`mtime`) descending before iterating. This means fresher
frames are sent before older backlog frames within the same tick, while the
`LAST_SENT_IMAGE` cursor remains stable because `start_index` is still computed
from the full ascending-sorted list.

## Max-Age Staleness Filter

Individual images whose `mtime` is older than `MAX_IMAGE_AGE_SECONDS`
(default 3600 seconds = 1 hour) are skipped as stale. The filter is evaluated
after the newest-first sort, so the freshest candidates are checked first.
Skipped stale images increment `_SKIPPED_STALE_COUNT` and set the last skip
reason to `"stale"`.

## Startup Behavior

On first start or when `output/.last_sent_file` is missing, the bot scans the
latest dated folder for the most recently modified image and initializes
`LAST_SENT_IMAGE` and `LAST_SENT_FOLDER` to that file **without sending it**.
The state is immediately persisted to `.last_sent_file` so subsequent restarts
skip re-initialization.

This prevents the backlog drain loop that would otherwise walk through every
image in the folder from index 0 on startup.

## Commands

### `/admin`

Returns a single-page Markdown summary **and sends the latest image file** to
authorized chats only.

Data sources (tried in order):
1. `output/triage_summary.json` — latest triage statistics
2. Live `output/YYYY-MM-DD/` folder — media counts when no triage summary exists

Text output includes:
- Latest run date and freshness indicator (within 24h = fresh)
- Total and kept image counts
- Car and person counts (when object detection is enabled)
- Video file count (live output only)
- Latest file name and timestamp (live output only)
- Missing expected object count (if any)
- Send statistics: sent, skipped similar, skipped non-kept, skipped stale
- Backlog size (unsent images after the cursor)
- Latest capture time and latest sent time
- Last skip reason (similar, non-kept, stale, or —)

Image output:
- After the text reply, the bot sends the most recently modified image file
  from the latest `output/YYYY-MM-DD/` folder via `reply_photo`.
- If no image files exist, the bot replies with "No latest image available."
- If `reply_photo` raises an exception, the bot catches it and falls back to the
  same text note.

Non-admin chats are silently ignored.

### `/state`

Returns a single-page Markdown container status summary to authorized chats only.

Monitored containers:
- `cams_grabber`
- `tg_bot`
- `sys_monitor`
- `web_viewer`

Output per container:
- Status emoji: `running=✅`, `exited=❌`, `not-found=❌`, `restarting=⚠️`, `dead=⚠️`
- Container name and raw status
- Health status (`healthy`, `unhealthy`, `starting`, or `N/A` when unavailable)
- Human-readable uptime (e.g., `up 2h 15m`, `up 3d 4h`) or `N/A`

If the Docker socket is not mounted, the bot replies:

```
Container runtime unavailable. Docker socket not mounted?
```

Non-admin chats are silently ignored.

## Docker Socket Setup

The `/state` command requires read-only access to the host Docker socket.
The `docker-compose.yml` already includes the mount:

```yaml
tg_bot:
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
```

After any change to the compose file, recreate the container:

```bash
docker compose up -d --force-recreate tg_bot
```

Security notes:
- The mount is **read-only** (`:ro`)
- The bot only queries container state; it cannot start, stop, or restart containers
- Both `/admin` and `/state` are restricted to the configured admin chat

## Local Operation

Ensure `output/` exists and `tg_bot/.env` is configured.

Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r tg_bot/requirements.txt
```

Run the bot:

```bash
.venv/bin/python tg_bot/bot.py
```

The bot polls `output/` every 5 seconds and posts new images to `TELEGRAM_CHAT_ID`.

## Docker Compose Operation

Start the service:

```bash
docker compose up -d tg_bot
```

View logs:

```bash
docker compose logs -f tg_bot
```

Restart after code changes (bot.py is mounted with `:cached`):

```bash
docker compose restart tg_bot
```

## Validation

Syntax check:

```bash
.venv/bin/python -m py_compile tg_bot/bot.py tests/test_tg_bot.py
```

Run focused tests:

```bash
.venv/bin/python -m unittest -v tests/test_tg_bot.py
```

Run full test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected results:
- 115 tg_bot tests pass
- 52 snapshot triage tests pass
- 28 web_viewer tests pass
- 195 total tests pass
- `py_compile` clean on all modified Python files

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/state` returns "Container runtime unavailable" | Docker socket not mounted into `tg_bot` container | Verify `docker-compose.yml` has the `:ro` socket mount and recreate the container |
| `/state` shows `not-found` for a running container | Container name mismatch | Ensure container names in `docker-compose.yml` match `EXPECTED_CONTAINERS` in `tg_bot/bot.py` |
| Bot does not respond to `/admin` or `/state` | Chat ID is not the configured admin chat | Check `TELEGRAM_ADMIN_CHAT_ID` (falls back to `TELEGRAM_CHAT_ID`) |
| Images are not posted | `output/` directory missing or empty | Ensure `output/` exists and contains dated `YYYY-MM-DD` folders with images |
| Duplicate images sent repeatedly | `.last_sent_file` state out of sync | Delete `output/.last_sent_file` and restart the bot |
| Bot goes silent during static scenes | Cooldown bypass has not yet expired | This is expected behavior; the next image is sent after `SEND_COOLDOWN_SECONDS` even if similar |
| Sender warnings about "maximum running instances reached" | Overlapping sender iterations (pre-guard behavior) | Ensure you are running the version with `_SENDER_LOCK`; restart the bot if the lock appears stuck |
| `/admin` sends text but no photo | Latest dated folder contains no images, or photo exceeds Telegram limits | Verify `output/YYYY-MM-DD/` contains `.jpg`/`.jpeg`/`.png` files; check logs for send errors |
| Bot drains old images slowly after restart | `.last_sent_file` was missing on startup | This is fixed in the current version; verify logs show "Initialized state to latest image" on first start |
| Too many similar images sent | `IMAGE_SIMILARITY_THRESHOLD` is set too high | Lower `IMAGE_SIMILARITY_THRESHOLD` (default 10); values below 5 will aggressively filter even real changes |
| All images skipped as similar | `IMAGE_SIMILARITY_THRESHOLD` is set too low | Raise `IMAGE_SIMILARITY_THRESHOLD`; values above 15 allow most visual variation through |
| Non-kept images not appearing in `/admin` stats | No `kept/` subfolder exists in the dated output folder | When no `kept/` subfolder exists, `_SKIPPED_NON_KEPT_COUNT` stays zero (backward-compatible fallback to all images) |
| Bot sends old backlog before fresh frames | Expected behavior prior to newest-first sort | Current version re-sorts remaining unsent images by `mtime` descending; verify `MAX_IMAGE_AGE_SECONDS` is not set too low |
| All unsent images skipped as stale | `MAX_IMAGE_AGE_SECONDS` is set too low, or system clock is skewed | Raise `MAX_IMAGE_AGE_SECONDS` (default 3600); verify file modification times are reasonable |
| Stale images still sent | `MAX_IMAGE_AGE_SECONDS` is set too high | Lower `MAX_IMAGE_AGE_SECONDS` to match expected camera interval and acceptable lag |
