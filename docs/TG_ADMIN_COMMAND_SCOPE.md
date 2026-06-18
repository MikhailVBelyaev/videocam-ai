# Telegram Admin Command Scope (TASK-001)

Job ID: 2026-06-18_115153_videocam-ai-add-to-tg-service-admin-command-and-show-1-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-18

## Problem Statement

The Telegram bot currently sends new camera images as they appear in `output/`, but
there is no way for an admin to query the current state of services, recent object
detection statistics, or recent processing activity. The original request asks for
an `/admin` command that shows "1 page state of services, statistics car, people,
log of work".

## Current Baseline

- `tg_bot/bot.py` polls `output/` for new images and sends them via `requests`.
  No command handling is implemented.
- `cams_grabber/snapshot_triage.py` produces `output/triage_summary.json` with:
  - `total_images`, `kept_images`
  - `total_objects_by_type` (e.g., `car`, `person` counts)
  - `missing_expected_objects`
- `sys_monitor/monitor.py` sends hourly system reports (CPU, RAM, disk, GPU, UPS)
  to the same Telegram chat.
- `docker-compose.yml` defines four services: `cams_grabber`, `tg_bot`,
  `sys_monitor`, `web_viewer`.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that adds an `/admin` command to the Telegram bot and returns a single-page
summary.

Included:
1. Add `/admin` command handling to `tg_bot/bot.py` (or a small new module
   imported by it).
2. When `/admin` is received, read the latest `output/triage_summary.json` and
   compose a single formatted Telegram message containing:
   - Latest run date (from most recent `YYYY-MM-DD` folder name in `output/`)
   - `total_images` and `kept_images`
   - `car_count` and `person_count` from `total_objects_by_type`
   - `missing_expected_objects` count (if any)
   - Simple "freshness" indicator (e.g., whether latest folder is within last 24h)
3. Restrict `/admin` to a configured admin chat ID:
   - New optional env var `TELEGRAM_ADMIN_CHAT_ID`
   - Fallback to `TELEGRAM_CHAT_ID` if not set
   - Non-admin chats receive no reply (silent ignore)
4. If `triage_summary.json` is missing or malformed, reply with a concise error
   message (e.g., "No triage data available").
5. Add one focused test validating the `/admin` message formatting logic.
6. Update `README.md` with the new command and `TELEGRAM_ADMIN_CHAT_ID` env var.

## Measurable Acceptance Criteria

- Sending `/admin` to the bot returns a single message containing at least:
  `total_images`, `kept_images`, `car_count`, `person_count` from the latest
  `triage_summary.json`.
- If `triage_summary.json` is missing or malformed, the bot replies with a clear
  error message instead of crashing.
- The command is restricted: `/admin` requests from chats other than the
  configured admin chat ID are silently ignored.
- Existing image-sending behavior is unchanged (no regression).
- A new or existing test validates the `/admin` response formatting.
- `py_compile` passes on all modified Python files.

## Explicit Exclusions

- No interactive inline keyboards, pagination, or callback queries.
- No bot commands to start, stop, or restart services.
- No new database, persistent log store, or file-based audit log.
- No REST API or webhook server changes; the bot continues to use polling.
- No changes to `cams_grabber/snapshot_triage.py`, `sys_monitor/monitor.py`,
  `cams_grabber/main_ssh.py`, or `docker-compose.yml`.
- No object detection model changes or new detection classes.
- No deployment scripts or host-specific configuration.

## Assumptions

- The bot continues to use polling (not webhooks).
- `triage_summary.json` is available in the mounted `output/` directory.
- `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` remain the only required env vars;
  `TELEGRAM_ADMIN_CHAT_ID` is optional.
- The existing `requests`-based approach may be extended, or `python-telegram-bot`
  (already in `requirements.txt`) may be introduced for command handling.
- Input ordering and JSON schema remain stable.

## Risks

- The current `bot.py` uses raw `requests`, while `python-telegram-bot` is listed
  in `requirements.txt` but unused. Mixing approaches or switching libraries may
  introduce regressions. Mitigation: keep changes small; if introducing
  `python-telegram-bot`, ensure the existing image-sending loop still works or is
  cleanly replaced.
- Future changes to `triage_summary.json` schema may break `/admin` parsing.
  Mitigation: use `.get()` with sensible defaults and document the dependency
  in the scope.
- The bot container shares `output/` via volume mount; if the mount fails or the
  directory is empty, `/admin` will show no data. Mitigation: handle missing
  files gracefully as specified in acceptance criteria.
