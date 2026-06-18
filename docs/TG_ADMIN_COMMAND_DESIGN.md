# TASK-002 Design: Telegram /admin Command

Job ID: 2026-06-18_115153_videocam-ai-add-to-tg-service-admin-command-and-show-1-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-18
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `tg_bot/bot.py` | Telegram bot sending new camera frames and handling `/admin` | **Primary** — adds command parsing, admin authorization, and on-demand summary reply |
| `cams_grabber/snapshot_triage.py` | Local-folder image triage producing JSON/CSV | **None** — no source changes; `output/triage_summary.json` is consumed read-only |
| `sys_monitor/monitor.py` | System health monitoring | **None** — no source changes; future increment may consume its reports |
| `web_viewer` (nginx:alpine) | Serves `output/` on port 8082 | None |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None |

### 1.2 Module-Level Changes

**`tg_bot/bot.py`**

Current flow:
```
poll output/ dated folders → detect new images → sendPhoto to TELEGRAM_CHAT_ID
  → update .last_sent_file state
```

New flow (two architectures considered; see Section 2):
```
Option B (recommended):
  python-telegram-bot Updater starts
    ├─ CommandHandler("admin") → read output/triage_summary.json + latest folder
    │                              → compose text → send_message (admin only)
    └─ Background job/timer → poll output/ folders → sendPhoto (unchanged logic)
```

New functions to add:
- `_is_admin_chat(update: Update) -> bool` — compares `update.effective_chat.id` against `TELEGRAM_ADMIN_CHAT_ID` (fallback `TELEGRAM_CHAT_ID`)
- `_read_latest_summary() -> dict | None` — reads `output/triage_summary.json`, returns parsed dict or None
- `_get_latest_run_date() -> str | None` — finds most recent `YYYY-MM-DD` folder in `output/`, returns folder name or None
- `_format_admin_message(summary: dict, run_date: str | None, fresh: bool) -> str` — builds single-page Telegram message
- `admin_command(update: Update, context: CallbackContext)` — handler wired to `/admin`

Modified:
- `main()` — initialize `python-telegram-bot` Application with handlers and background image-sending loop
- Environment reading — add `TELEGRAM_ADMIN_CHAT_ID` (optional)

**`tests/`**

New test module (recommended): `tests/test_tg_bot.py` or inline additions to existing test file.
- Unit test `_format_admin_message()` with mock summary dict: verifies presence of `total_images`, `kept_images`, `car_count`, `person_count`, and `missing_expected_objects` count
- Unit test `_is_admin_chat()` with matching and non-matching chat IDs
- Unit test `_read_latest_summary()` with missing file and malformed JSON

**`README.md`**

- Document `/admin` command behavior and env var `TELEGRAM_ADMIN_CHAT_ID`

### 1.3 Data Flow Diagram

```
User sends /admin
       │
       ▼
Telegram API (getUpdates)
       │
       ▼
┌─────────────────┐
│ tg_bot/bot.py   │
│ CommandHandler  │
└────────┬────────┘
         │
    ┌────┴──────────────────────────────┐
    │                                   │
    ▼                                   ▼
read output/triage_summary.json    read output/ dated folders
    │                                   │
    ▼                                   ▼
_parse JSON stats                 _find latest YYYY-MM-DD
    │                                   │
    └────────────┬──────────────────────┘
                 │
                 ▼
        _format_admin_message()
                 │
                 ▼
        send_message(admin_chat_id)
                 │
                 ▼
        Telegram chat reply
```

### 1.4 Interfaces

**New environment variable:**
- `TELEGRAM_ADMIN_CHAT_ID` (optional) — Telegram chat ID authorized to use `/admin`. Falls back to `TELEGRAM_CHAT_ID` if unset.

**New command interface:**
- Text message: `/admin` in any chat where the bot is present.
- Response (admin chat): single formatted message containing:
  - Latest run date (from most recent `YYYY-MM-DD` folder in `output/`)
  - `total_images` and `kept_images`
  - `car_count` and `person_count` from `total_objects_by_type`
  - `missing_expected_objects` count (if any)
  - Freshness indicator (e.g., "✅ Fresh (within 24h)" or "⚠️ Stale")
- Response (non-admin chat): silent ignore (no reply, no error logged to user).
- Error response: if `triage_summary.json` is missing or malformed, reply with "No triage data available."

**Data dependency contract (`output/triage_summary.json`):**
```json
{
  "total_images": 150,
  "kept_images": 23,
  "total_objects_by_type": {"car": 45, "person": 12},
  "missing_expected_objects": [{"filename": "IMG_0001.jpg", "missing": ["car"]}]
}
```
The design uses `.get()` with defaults (`total_objects_by_type` defaults to `{}`, `missing_expected_objects` defaults to `[]`) so future schema changes do not crash the handler.

**File system interface:**
- `output/` directory mounted as Docker volume (already configured in `docker-compose.yml`)
- `output/YYYY-MM-DD/` dated subfolders created by `snapshot_triage.py`

---

## 2. Implementation Approach

### 2.1 Recommended Architecture: python-telegram-bot with Background Job

Migrate `tg_bot/bot.py` from raw `requests` polling to `python-telegram-bot==20.6` (already in `requirements.txt`).

Structure:
1. Build `Application.builder().token(BOT_TOKEN).build()`
2. Register `CommandHandler("admin", admin_command)`
3. Run existing image-sending logic as a `JobQueue` repeating job or a custom asyncio background task.
4. Call `application.run_polling()`

Why this is the best fit:
- `python-telegram-bot` is already listed in `requirements.txt` but unused; this resolves that inconsistency.
- Built-in `getUpdates` polling, offset management, and error handling.
- Easy admin restriction via `Filters.Chat(admin_chat_id)` or a custom filter.
- Clean separation between command handling and background image sending.

Code sketch (not production code):
```python
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_chat(update):
        return  # silent ignore
    summary = _read_latest_summary()
    run_date = _get_latest_run_date()
    fresh = _is_fresh(run_date)
    if summary is None:
        await update.message.reply_text("No triage data available.")
        return
    text = _format_admin_message(summary, run_date, fresh)
    await update.message.reply_text(text, parse_mode="Markdown")

# Background image sender (adapted from current loop)
async def image_sender_job(context: ContextTypes.DEFAULT_TYPE):
    ...  # existing logic adapted to async or run in executor

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("admin", admin_command))
app.job_queue.run_repeating(image_sender_job, interval=5, first=5)
app.run_polling()
```

### 2.2 Alternative: Raw requests with manual getUpdates polling

Extend the existing `while True` loop to also call `getUpdates` and parse `/admin`.

**Pros**: No library switch; smallest possible diff to image-sending logic.
**Cons**: Manual offset tracking is error-prone; no built-in command routing; async reply handling is messy; mixing two polling concerns in one loop reduces clarity.

**Verdict**: Rejected. The existing `python-telegram-bot` dependency makes the framework approach strictly better for maintainability.

### 2.3 Alternative: Hybrid threading

Keep the existing synchronous `while True` image loop in the main thread, and spawn a daemon thread running a minimal `python-telegram-bot` updater for commands only.

**Pros**: Zero risk to image-sending logic.
**Cons**: Two separate update loops hit the Telegram API independently; potential for race conditions on shared state (`.last_sent_file`); harder to shut down cleanly.

**Verdict**: Rejected. A single `Application` with `job_queue` is simpler and the ptb framework is designed for exactly this use case.

---

## 3. Key Tradeoffs

### 3.1 Command Handling Library

| Approach | Pros | Cons |
|----------|------|------|
| Raw `requests` + manual `getUpdates` | No refactor of existing loop | Error-prone offset management, no command framework, harder to test |
| `python-telegram-bot` (recommended) | Already in requirements, clean handlers, built-in filters, easy testing | Requires refactoring existing loop into async or executor-compatible form |
| Hybrid threading | Preserves existing loop exactly | Two API polling loops, shared-state races, complex shutdown |

**Decision**: `python-telegram-bot` Application with JobQueue. The refactor is bounded: the image-sending logic moves into a background job; command handling is declarative.

### 3.2 Admin Authorization Model

| Approach | Pros | Cons |
|----------|------|------|
| Single env var `TELEGRAM_ADMIN_CHAT_ID` (recommended) | Simple, stateless, fits Docker deployment | Only one admin chat; requires container restart to change |
| File-based whitelist | Supports multiple admins | Adds persistent file management, not needed for scope |
| Inline hardcoded list | No env changes | Requires code change for new admins, inflexible |

**Decision**: Single env var `TELEGRAM_ADMIN_CHAT_ID`, falling back to `TELEGRAM_CHAT_ID`. This satisfies the scope requirement for admin restriction with minimal complexity.

### 3.3 Data Freshness Strategy

| Approach | Pros | Cons |
|----------|------|------|
| Read JSON on every `/admin` (recommended) | Always shows latest data; no memory state | Small I/O per command; negligible for local file |
| Cache in memory with TTL | Faster replies | Stale data risk; adds caching complexity |
| Read folder mtime | Simple | Less explicit than folder name parsing |

**Decision**: Read `triage_summary.json` and scan `output/` folders on every `/admin` invocation. The file is small and local; I/O cost is negligible.

### 3.4 Message Formatting

| Approach | Pros | Cons |
|----------|------|------|
| Plain text | No parse_mode risk, always renders | Less readable for structured stats |
| Markdown (recommended) | Bold labels, emoji indicators, readable | Must escape special chars; Telegram MarkdownV2 is strict |
| HTML | Same readability as Markdown | Must escape `<`, `>`, `&` |

**Decision**: Markdown with basic formatting (bold labels, emoji status). Use `.get()` defaults to avoid KeyError crashes that could break formatting.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `python-telegram-bot==20.6` | In `tg_bot/requirements.txt`, unused | Command handling, polling, JobQueue | Low — version is pinned and v20 is stable |
| `requests` | Used heavily in current bot | May be reduced to only `sendPhoto` if using ptb built-ins | Low — ptb wraps the same HTTP API |
| `Pillow`, `ImageHash`, `pytz` | Used in current bot | Unchanged for image-sending background job | None |
| `triage_summary.json` schema | Stable (TASK-003/004/005) | `/admin` data source | Low — additive schema with `.get()` defaults |
| `output/` volume mount | Already in `docker-compose.yml` | File access for JSON and folder scan | None |

No new Python package dependencies are required.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Refactoring existing image-sending loop into ptb JobQueue introduces regression | Medium | Keep image-sending logic functionally identical; extract into a standalone async function; test with a mock output directory |
| `python-telegram-bot` v20 async model conflicts with synchronous `PIL`/`imagehash` code | Low | Run synchronous code via `asyncio.get_event_loop().run_in_executor()` or use ptb’s `context.application.create_task` with blocking call wrapper |
| Non-admin users discover `/admin` and spam it | Low | Silent ignore plus optional logging at INFO level; no network reply means no feedback loop for attackers |
| `triage_summary.json` schema changes break `/admin` formatting | Low | Use `.get()` with defaults for every field; document schema dependency in design and scope docs |
| Missing `output/` mount or empty directory | Low | Graceful error message: "No triage data available"; do not crash the bot |
| Existing working-tree changes overlap | Medium | This design only touches `tg_bot/bot.py`, `tests/`, and `README.md`; no overlap with `cams_grabber/` changes pending in review |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `tg_bot/bot.py` | Modify | Refactor to `python-telegram-bot` Application; add `/admin` CommandHandler; add helper functions for summary read, folder scan, message format, admin check |
| `tests/test_tg_bot.py` | Create | Add focused unit tests for `_format_admin_message`, `_is_admin_chat`, `_read_latest_summary` |
| `README.md` | Modify | Document `/admin` command and `TELEGRAM_ADMIN_CHAT_ID` env var |
| `tg_bot/requirements.txt` | No change | `python-telegram-bot==20.6` already listed |
| `docker-compose.yml` | No change | Volume mounts and env file already sufficient |
| `cams_grabber/snapshot_triage.py` | No change | Explicitly excluded by scope |
| `sys_monitor/monitor.py` | No change | Explicitly excluded by scope |

---

## 7. Validation Plan

1. `python3 -m py_compile tg_bot/bot.py tests/test_tg_bot.py` — syntax check
2. Run new unit tests: `python3 -m unittest -v tests/test_tg_bot.py` — verify formatting, auth, and error handling
3. Run existing test suite: `python3 -m unittest -v tests/test_snapshot_triage.py` — ensure no regression in triage pipeline
4. Manual smoke test (local or container):
   - Set `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, and optionally `TELEGRAM_ADMIN_CHAT_ID`
   - Place a valid `output/triage_summary.json` in the mounted output directory
   - Send `/admin` from authorized chat → verify formatted reply
   - Send `/admin` from unauthorized chat → verify silent ignore
   - Remove `triage_summary.json` → verify error reply
5. Confirm existing image-sending behavior still detects and sends new frames from `output/YYYY-MM-DD/`
