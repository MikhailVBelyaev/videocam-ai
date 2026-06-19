# Telegram Bot Runbook

## Purpose

Operate the `tg_bot` service that sends new camera frames to Telegram and responds
to admin commands.

## Environment Variables

Configure these in `tg_bot/.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Default chat ID for image posts |
| `TELEGRAM_ADMIN_CHAT_ID` | No | Chat ID authorized for `/admin` and `/state` (falls back to `TELEGRAM_CHAT_ID`) |

## Commands

### `/admin`

Returns a single-page Markdown summary to authorized chats only.

Data sources (tried in order):
1. `output/triage_summary.json` — latest triage statistics
2. Live `output/YYYY-MM-DD/` folder — media counts when no triage summary exists

Output includes:
- Latest run date and freshness indicator (within 24h = fresh)
- Total and kept image counts
- Car and person counts (when object detection is enabled)
- Video file count (live output only)
- Latest file name and timestamp (live output only)
- Missing expected object count (if any)

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
- 47 tg_bot tests pass
- 52 snapshot triage tests pass
- `py_compile` clean on all modified Python files

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/state` returns "Container runtime unavailable" | Docker socket not mounted into `tg_bot` container | Verify `docker-compose.yml` has the `:ro` socket mount and recreate the container |
| `/state` shows `not-found` for a running container | Container name mismatch | Ensure container names in `docker-compose.yml` match `EXPECTED_CONTAINERS` in `tg_bot/bot.py` |
| Bot does not respond to `/admin` or `/state` | Chat ID is not the configured admin chat | Check `TELEGRAM_ADMIN_CHAT_ID` (falls back to `TELEGRAM_CHAT_ID`) |
| Images are not posted | `output/` directory missing or empty | Ensure `output/` exists and contains dated `YYYY-MM-DD` folders with images |
| Duplicate images sent repeatedly | `.last_sent_file` state out of sync | Delete `output/.last_sent_file` and restart the bot |
