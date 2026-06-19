# TASK-002 Design: Telegram /state Container Status Command

Job ID: 2026-06-19_104909_videocam-ai-add-to-command-state-info-about-running-containe-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `tg_bot/bot.py` | Telegram bot sending frames and handling `/admin` | **Primary** — adds `/state` command handler, admin authorization reuse, and container-runtime query logic |
| `cams_grabber/snapshot_triage.py` | Local-folder image triage | **None** — no source changes |
| `sys_monitor/monitor.py` | System health monitoring | **None** — no source changes; could be extended later to include container state |
| `web_viewer` (nginx:alpine) | Serves `output/` on port 8082 | None |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None |
| Docker Engine (host) | Container runtime | **Runtime dependency** — `tg_bot` container queries it via socket mount |

### 1.2 Module-Level Changes

**`tg_bot/bot.py`**

Current flow (already refactored to `python-telegram-bot`):
```
Application starts
  ├─ CommandHandler("admin") → read triage_summary.json → reply
  └─ JobQueue (5s) → poll output/ → sendPhoto
```

New flow:
```
Application starts
  ├─ CommandHandler("admin") → existing logic (unchanged)
  ├─ CommandHandler("state") → _query_container_states() → _format_state_message() → reply
  └─ JobQueue (5s) → existing image sender (unchanged)
```

New functions to add:
- `_query_container_states() -> list[dict]` — connects to Docker daemon, queries the four expected containers, returns a list of state dicts
- `_format_state_message(states: list[dict]) -> str` — composes a single-page Markdown message from the state list
- `state_command(update: Update, context: ContextTypes.DEFAULT_TYPE)` — handler wired to `/state`, reuses `_is_admin_chat()`

Modified:
- `main()` — register `CommandHandler("state", state_command)`

**`docker-compose.yml`**

Modified:
- `tg_bot` service volumes — add `/var/run/docker.sock:/var/run/docker.sock:ro` (read-only) so the bot can query container runtime state without container control privileges.

**`tg_bot/requirements.txt`**

Modified:
- Add `docker` (Docker SDK for Python) to enable programmatic container queries.

**`tests/test_tg_bot.py`**

Modified:
- Add unit test `_format_state_message()` with mocked state dicts: verifies presence of container names, running/exited/not-found, health status, and uptime/age
- Add unit test `state_command()` admin restriction: non-admin chat silent ignore
- Add unit test `state_command()` runtime unavailable: graceful error message when Docker socket is absent

**`README.md`**

Modified:
- Document `/state` command behavior
- Document `docker` dependency and Docker socket volume mount requirement
- Document required container recreate after `docker-compose.yml` change

### 1.3 Data Flow Diagram

```
User sends /state (admin chat only)
       │
       ▼
Telegram API (getUpdates)
       │
       ▼
┌─────────────────┐
│ tg_bot/bot.py   │
│ CommandHandler  │
│ _is_admin_chat  │
└────────┬────────┘
         │ (authorized)
         ▼
┌─────────────────────────────┐
│ _query_container_states()   │
│   docker.DockerClient       │
│   .from_env()               │
└────────┬────────────────────┘
         │ (Unix socket)
         ▼
┌─────────────────────────────┐
│ Docker daemon (host)        │
└────────┬────────────────────┘
         │ (container inspect)
         ▼
┌──────────────────────────────────────┐
│ cams_grabber, tg_bot,                │
│ sys_monitor, web_viewer              │
│   State.Status                       │
│   State.Health.Status (if present)   │
│   State.StartedAt                    │
└────────┬─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│ _format_state_message()     │
│   Markdown text             │
└────────┬────────────────────┘
         │
         ▼
    send_message(admin_chat_id)
         │
         ▼
    Telegram chat reply
```

### 1.4 Interfaces

**No new environment variables.**
- Reuses existing `TELEGRAM_ADMIN_CHAT_ID` (falls back to `TELEGRAM_CHAT_ID`) for authorization.

**New command interface:**
- Text message: `/state` in any chat where the bot is present.
- Response (admin chat): single formatted Markdown message containing one line per expected container:
  - Container name
  - Running / exited / not-found status
  - Health status (`healthy`, `unhealthy`, `starting`, or `N/A`)
  - Uptime or age (e.g., "up 2h 15m" or "created 2026-06-19 08:00")
- Response (non-admin chat): silent ignore (no reply, no error logged to user).
- Error response (runtime unavailable): "Container runtime unavailable. Docker socket not mounted?" instead of a crash.

**Docker Engine interface (Unix socket):**
- Path inside container: `/var/run/docker.sock` (mounted read-only from host)
- Python library: `docker.DockerClient.from_env()` uses `DOCKER_HOST` env var or defaults to the Unix socket
- API calls: `client.containers.list(all=True)` or `client.containers.get(name)`
- Attributes read (read-only): `container.attrs['State']['Status']`, `container.attrs['State']['Health']['Status']`, `container.attrs['State']['StartedAt']`, `container.attrs['Created']`
- No write operations: no start, stop, restart, kill, or remove calls.

---

## 2. Implementation Approach

### 2.1 Recommended: Docker SDK for Python + Read-Only Socket Mount

Add `docker` to `tg_bot/requirements.txt`, mount the host Docker socket into the `tg_bot` container as read-only, and use `docker.DockerClient.from_env()` to query container states.

Structure:
1. In `_query_container_states()`, attempt `docker.DockerClient.from_env()`.
2. If the client fails to initialize (socket missing or unreachable), return `None` to signal "runtime unavailable."
3. For each expected container name (`cams_grabber`, `tg_bot`, `sys_monitor`, `web_viewer`), call `client.containers.get(name)`.
4. If `NotFound`, record state as `not-found`.
5. If found, extract `State.Status`, `State.Health.Status` (if present), and `State.StartedAt`.
6. Close the client and return a list of dicts.
7. In `state_command()`, if `_is_admin_chat()` is False, return silently.
8. If states is `None`, reply with the runtime-unavailable error.
9. Otherwise, call `_format_state_message(states)` and reply with `parse_mode="Markdown"`.

Why this is the best fit:
- `docker` is the official Python SDK; it handles Unix socket transport, JSON parsing, and error types (`docker.errors.NotFound`, `docker.errors.DockerException`).
- Read-only socket mount (`:ro`) prevents accidental container control from the bot, satisfying the scope security concern.
- The code is compact and testable: the client can be mocked or patched in unit tests.
- The implementation fits within a single Codex session.

Code sketch (not production code):
```python
import docker
from docker.errors import NotFound, DockerException

EXPECTED_CONTAINERS = ["cams_grabber", "tg_bot", "sys_monitor", "web_viewer"]


def _query_container_states():
    try:
        client = docker.DockerClient.from_env()
    except DockerException:
        return None
    states = []
    for name in EXPECTED_CONTAINERS:
        try:
            c = client.containers.get(name)
            attrs = c.attrs["State"]
            health = attrs.get("Health", {}).get("Status", "N/A")
            states.append({
                "name": name,
                "status": attrs.get("Status", "unknown"),
                "health": health,
                "started_at": attrs.get("StartedAt"),
            })
        except NotFound:
            states.append({
                "name": name,
                "status": "not-found",
                "health": "N/A",
                "started_at": None,
            })
    client.close()
    return states


def _format_state_message(states):
    lines = ["*Container Status*", ""]
    for s in states:
        status_emoji = "✅" if s["status"] == "running" else "❌"
        health = s["health"]
        started = s["started_at"] or "N/A"
        lines.append(
            f"{status_emoji} *{s['name']}* — {s['status']} | health: {health} | started: {started}"
        )
    return "\n".join(lines)


async def state_command(update, context):
    if not _is_admin_chat(update):
        return
    states = _query_container_states()
    if states is None:
        await update.message.reply_text(
            "Container runtime unavailable. Docker socket not mounted?"
        )
        return
    text = _format_state_message(states)
    await update.message.reply_text(text, parse_mode="Markdown")
```

### 2.2 Alternative: Subprocess `docker` CLI

Install the Docker CLI inside the `tg_bot` container and call `docker inspect --format=...` via `subprocess.run()`.

**Pros**: No new Python package if the CLI is already present.
**Cons**: `python:3.12-slim` does not include the Docker CLI; adding it increases image size and complexity. Parsing shell output is brittle compared to structured JSON via the SDK.

**Verdict**: Rejected. Installing the Docker CLI in a slim Python image is heavier and more fragile than adding the `docker` Python package.

### 2.3 Alternative: Direct HTTP to Docker Unix Socket

Use `requests` (already in requirements) with a Unix socket transport adapter (e.g., `requests-unixsocket`) to call the Docker Engine HTTP API directly.

**Pros**: Reuses existing `requests` dependency.
**Cons**: Requires an additional adapter package or custom socket-to-HTTP bridging code. The Docker SDK already wraps this cleanly.

**Verdict**: Rejected. The `docker` package is the idiomatic abstraction; reimplementing its transport layer adds unnecessary code.

### 2.4 Alternative: File-Based State Sharing via sys_monitor

Extend `sys_monitor/monitor.py` to query container states and write them to a shared JSON file in `output/`, which `tg_bot/bot.py` reads on `/state`.

**Pros**: No Docker socket mount in `tg_bot`; no new dependencies in `tg_bot`.
**Cons**: Requires modifying `sys_monitor/monitor.py`, which is explicitly excluded by scope. Adds polling latency and a file-format contract that must be versioned.

**Verdict**: Rejected. Excluded by the scope document (`docs/STATE_COMMAND_SCOPE.md`).

---

## 3. Key Tradeoffs

### 3.1 Container Runtime Access Method

| Approach | Pros | Cons |
|----------|------|------|
| Docker SDK for Python + read-only socket mount (recommended) | Official SDK, clean error types, compact code, well-tested | Requires socket mount (security surface area) and one new PyPI dependency |
| Subprocess `docker` CLI | No Python package needed | Docker CLI not in base image; brittle text parsing; larger image |
| Direct HTTP to Unix socket | Reuses `requests` | Requires adapter or custom transport; more code |
| File-based via sys_monitor | No socket in tg_bot | Excluded by scope; adds latency and file contract complexity |

**Decision**: Docker SDK for Python with a read-only socket mount. The security risk is mitigated by the read-only mount and the absence of container-control commands.

### 3.2 Docker Socket Security

| Approach | Pros | Cons |
|----------|------|------|
| Read-only mount `:ro` (recommended) | Prevents accidental or malicious container control via the bot | Still exposes container inspect/read API; host information leakage possible |
| Read-write mount | Easier to test (no permission issues) | Full container control from bot; unacceptable attack surface |
| No mount; file-based fallback | No socket exposure | Requires sys_monitor changes (excluded) or degrades to "runtime unavailable" always |

**Decision**: Read-only mount (`/var/run/docker.sock:/var/run/docker.sock:ro`). Document in `README.md` that this is required and that the bot does not expose container-control commands.

### 3.3 Admin Authorization

| Approach | Pros | Cons |
|----------|------|------|
| Reuse `_is_admin_chat()` (recommended) | Zero new config; consistent with `/admin` | Same single-admin limitation as `/admin` |
| Separate env var for `/state` | Could allow different admins for stats vs. control | Overkill for scope; adds config burden |

**Decision**: Reuse existing `_is_admin_chat()` and `TELEGRAM_ADMIN_CHAT_ID` fallback. No new environment variables.

### 3.4 Uptime Representation

| Approach | Pros | Cons |
|----------|------|------|
| Raw ISO timestamp from `StartedAt` | Exact, unambiguous | Less readable in a chat message |
| Human-readable duration (e.g., "up 2h 15m") (recommended) | Quick to scan | Requires parsing ISO 8601 and computing delta; may show "up 0m" for freshly restarted containers |

**Decision**: Human-readable duration with a fallback to raw timestamp if parsing fails. The code sketch shows `started_at` as the initial field; the implementation can format it as a duration.

### 3.5 Error Handling Strategy

| Approach | Pros | Cons |
|----------|------|------|
| Runtime unavailable → single error reply (recommended) | Clear to admin; bot stays up | None significant |
| Per-container error lines | More granular | Noisier message; overkill for four containers |
| Crash the bot on DockerException | Simple code | Unacceptable availability risk |

**Decision**: Catch `DockerException` at client initialization and reply with a concise error. Catch `NotFound` per-container and render as "not-found" in the summary.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `docker` (Docker SDK for Python) | Not in requirements | Container runtime queries | Low — pure Python wrapper over HTTP/Unix socket; stable API |
| `python-telegram-bot==20.6` | In `tg_bot/requirements.txt`, used | Command handling, polling | None — already working for `/admin` |
| `requests`, `Pillow`, `ImageHash`, `pytz` | In requirements, used | Image sending unchanged | None |
| Docker Engine Unix socket | On host, not yet mounted into tg_bot | Container query transport | Low — standard Docker deployment pattern |
| `docker-compose.yml` socket mount | Not yet present | Runtime access for bot | Low — one-line volume addition |

One new Python package dependency: `docker`.
One new infrastructure dependency: read-only Docker socket mount in `docker-compose.yml`.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Docker socket mount increases attack surface | Medium | Mount read-only (`:ro`); do not expose start/stop/restart commands; restrict to admin chat |
| `docker` PyPI package unavailable or incompatible with `python:3.12-slim` | Low | Pin a stable version; the package is pure Python with no compiled extensions |
| Container names differ in custom deployments | Low | Hardcode the four names from `docker-compose.yml`; handle `NotFound` gracefully; document that custom names require code change |
| Docker daemon temporarily unreachable | Low | `DockerException` on client init → reply with error message; bot continues running |
| Existing working-tree changes overlap | Medium | This design only touches `tg_bot/bot.py`, `tests/test_tg_bot.py`, `tg_bot/requirements.txt`, `docker-compose.yml`, and `README.md`; no overlap with pending `cams_grabber/` changes |
| Implementation exceeds one Codex session | Low | Scope is bounded to four containers, one command, one handler, one formatter, and three focused tests; matches the size of the previous `/admin` implementation |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `tg_bot/bot.py` | Modify | Add `EXPECTED_CONTAINERS`, `_query_container_states()`, `_format_state_message()`, `state_command()`; register `CommandHandler("state", state_command)` in `main()` |
| `tests/test_tg_bot.py` | Modify | Add tests for `_format_state_message`, `state_command` admin restriction, and runtime-unavailable graceful error |
| `tg_bot/requirements.txt` | Modify | Add `docker` package |
| `docker-compose.yml` | Modify | Add `/var/run/docker.sock:/var/run/docker.sock:ro` volume to `tg_bot` service |
| `README.md` | Modify | Document `/state` command, Docker socket requirement, and container recreate step |
| `cams_grabber/snapshot_triage.py` | No change | Explicitly excluded by scope |
| `sys_monitor/monitor.py` | No change | Explicitly excluded by scope |

---

## 7. Validation Plan

1. `python3 -m py_compile tg_bot/bot.py tests/test_tg_bot.py` — syntax check on modified files.
2. Install new dependency in `.venv`: `.venv/bin/python -m pip install docker` — verify install succeeds.
3. Run new unit tests: `python3 -m unittest -v tests/test_tg_bot.py` — verify `/state` formatting, admin restriction, and runtime-unavailable path.
4. Run existing test suite: `python3 -m unittest -v tests/test_snapshot_triage.py` — ensure no regression in triage pipeline.
5. Manual smoke test (requires Docker environment):
   - Ensure `docker-compose.yml` has the socket mount.
   - Recreate the `tg_bot` container: `docker compose up -d --force-recreate tg_bot`
   - Send `/state` from authorized chat → verify four-container summary reply.
   - Send `/state` from unauthorized chat → verify silent ignore.
   - Temporarily rename one container or stop it → verify status reflects exited/not-found.
   - Temporarily remove socket mount → verify "Container runtime unavailable" reply.
6. Confirm existing `/admin` behavior and image-sending behavior are unchanged (no regression).
