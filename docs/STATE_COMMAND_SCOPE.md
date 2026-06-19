# Container State Command Scope (TASK-001)

Job ID: 2026-06-19_104909_videocam-ai-add-to-command-state-info-about-running-containe-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19

## Problem Statement

The Telegram bot provides `/admin` for triage statistics, but there is no way for an
admin to check whether the project's Docker containers are running and healthy from
Telegram. The original request asks for a `/state` command that shows "info about
running containers".

## Current Baseline

- `tg_bot/bot.py` implements `/admin` restricted to `TELEGRAM_ADMIN_CHAT_ID`.
- `docker-compose.yml` defines four services:
  - `cams_grabber` (healthcheck: `pgrep -f main_ssh.py`)
  - `tg_bot` (healthcheck: inspects `/proc/1/cmdline`)
  - `sys_monitor` (no healthcheck)
  - `web_viewer` (no healthcheck)
- `sys_monitor/monitor.py` sends hourly system reports (CPU, RAM, disk, GPU, UPS)
  but does not report container status.
- None of the services currently mount the Docker socket or otherwise expose
  container runtime state to the bot.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that adds a `/state` command to the Telegram bot and returns a single-page
container status summary.

Included:
1. Add `/state` command handling to `tg_bot/bot.py` (or a small new module
   imported by it).
2. When `/state` is received, query the runtime state of the four expected
   containers (`cams_grabber`, `tg_bot`, `sys_monitor`, `web_viewer`) and
   compose a single formatted Telegram message containing:
   - Container name
   - Running / exited / not-found status
   - Health status if available (`healthy`, `unhealthy`, `starting`, or `N/A`)
   - Uptime or age if readily available
3. Restrict `/state` to the configured admin chat ID, using the same mechanism
   as `/admin` (`TELEGRAM_ADMIN_CHAT_ID`, fallback to `TELEGRAM_CHAT_ID`).
   Non-admin chats receive no reply (silent ignore).
4. If container runtime access is unavailable (e.g., Docker socket not mounted),
   reply with a concise error message instead of crashing.
5. Add one focused test validating the `/state` message formatting logic and
   admin restriction.
6. Update `README.md` with the new command and any new configuration requirements.
7. Update `docker-compose.yml` if a volume mount (e.g., Docker socket) is required
   for the bot to read container states.

## Measurable Acceptance Criteria

- Sending `/state` to the bot returns a single message containing the status of
  all four expected containers (`cams_grabber`, `tg_bot`, `sys_monitor`, `web_viewer`).
- Each container line shows at minimum: name, running/exited/not-found state,
  and health status (or `N/A` when unavailable).
- If container runtime access is unavailable, the bot replies with a clear error
  message instead of crashing.
- The command is restricted: `/state` requests from chats other than the
  configured admin chat ID are silently ignored.
- Existing `/admin` behavior and image-sending behavior are unchanged (no regression).
- A new or existing test validates the `/state` response formatting and admin restriction.
- `py_compile` passes on all modified Python files.

## Explicit Exclusions

- No interactive inline keyboards, pagination, or callback queries.
- No bot commands to start, stop, restart, or otherwise control containers.
- No new database, persistent log store, or file-based audit log.
- No REST API or webhook server changes; the bot continues to use polling.
- No changes to `cams_grabber/snapshot_triage.py`, `cams_grabber/main_ssh.py`,
  `sys_monitor/monitor.py`, or `web_viewer` configuration, except for any
  `docker-compose.yml` mount needed by `tg_bot`.
- No container log streaming or tailing.
- No host system metrics (CPU, RAM, disk) in `/state`; that remains the domain
  of `sys_monitor`.

## Assumptions

- The bot continues to use polling (not webhooks).
- `TELEGRAM_ADMIN_CHAT_ID` reuse; no new env vars are required unless the
  implementation approach demands one.
- Container names match the `container_name` values in `docker-compose.yml`.
- Docker socket or equivalent container-runtime access can be added to the
  `tg_bot` service via `docker-compose.yml` volume mount if needed.
- If a Python Docker client library is used, it can be added to
  `tg_bot/requirements.txt`.
- The existing test environment can mock container runtime responses for unit
  testing.

## Risks

- Adding Docker socket access to the `tg_bot` container increases attack surface.
  Mitigation: mount read-only if the library supports it; restrict to admin chat;
  do not expose container control commands.
- The Docker CLI or Python `docker` library may not be present in the
  `python:3.12-slim` base image. Mitigation: add the dependency to
  `tg_bot/Dockerfile` or `requirements.txt`, or use a lightweight HTTP call to
  the Docker daemon if feasible.
- Custom deployments may use different container names or orchestrators
  (e.g., Kubernetes). Mitigation: scope to the four documented compose services;
  handle "not found" gracefully.
- If `docker-compose.yml` is updated with a socket mount, existing deployments
  must be recreated (`docker compose up -d --force-recreate tg_bot`) for the
  change to take effect. Mitigation: document the requirement in `README.md`.
