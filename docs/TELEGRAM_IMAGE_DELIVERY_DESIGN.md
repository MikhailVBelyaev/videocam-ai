# TASK-002 Design: Fix Production Telegram Image Delivery and Admin Statistics

Job ID: 2026-06-19_140208_videocam-ai-fix-production-telegram-image-delivery-and-admin-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `tg_bot/bot.py` | Telegram bot sending camera frames and handling `/admin`/`/state` | **Primary** — adds concurrency guard, send cap, cooldown bypass to image sender; extends `/admin` to send latest image file |
| `cams_grabber/snapshot_triage.py` | Local-folder image triage producing JSON/CSV | **None** — no source changes; `output/triage_summary.json` and dated folders are consumed read-only |
| `web_viewer` | Flask web server serving `output/` on port 8082 | None |
| `sys_monitor/monitor.py` | System health monitoring | None |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None |

### 1.2 Module-Level Changes

**`tg_bot/bot.py`**

Current image-sender flow:
```
JobQueue runs image_sender_job every 5s
  └─ asyncio.to_thread(_send_new_images_iteration)
       └─ scan output/ dated folders → iterate ALL unsent images
            └─ perceptual-hash similarity check → sendPhoto one-by-one
                 └─ update .last_sent_file and global LAST_SENT_IMAGE
```

New flow:
```
JobQueue runs image_sender_job every 5s
  └─ acquire asyncio.Lock (skip if already locked)
       └─ asyncio.to_thread(_send_new_images_iteration)
            └─ scan output/ dated folders → iterate unsent images
                 ├─ if cooldown expired → bypass similarity for next candidate
                 ├─ similarity check → skip duplicate
                 ├─ sendPhoto → increment cap counter
                 └─ break when cap reached
```

New `/admin` flow:
```
CommandHandler("admin")
  ├─ read output/triage_summary.json + latest folder
  ├─ compose text → reply_text (existing behavior, unchanged)
  └─ find latest image file → reply_photo (new)
       └─ on failure, send text fallback
```

New/changed functions in `tg_bot/bot.py`:

| Function | Change | Description |
|----------|--------|-------------|
| `_SENDER_LOCK` | Add | Module-level `asyncio.Lock()` guarding `image_sender_job` |
| `_LAST_SENT_TIMESTAMP` | Add | Module-level `float` tracking epoch seconds of last successful `send_photo()` |
| `MAX_IMAGES_PER_ITERATION` | Add | `int(os.getenv("MAX_IMAGES_PER_ITERATION", "5"))` |
| `SEND_COOLDOWN_SECONDS` | Add | `int(os.getenv("SEND_COOLDOWN_SECONDS", "300"))` |
| `send_photo()` | Modify | Updates `_LAST_SENT_TIMESTAMP = time.time()` on success |
| `_send_new_images_iteration()` | Modify | Adds per-iteration send cap and cooldown-bypass logic inside the send loop |
| `image_sender_job()` | Modify | Acquires `_SENDER_LOCK`; skips invocation if lock is already held |
| `_get_latest_image_path()` | Add | Returns absolute path to the most recently modified image in the latest dated folder, or `None` |
| `admin_command()` | Modify | After existing text reply, calls `_get_latest_image_path()` and sends photo via `update.message.reply_photo()`; catches exceptions and sends text fallback |

**`tests/test_tg_bot.py`**

New tests to add (focused, no broad refactor):
- Concurrency guard: simulate a slow `_send_new_images_iteration`; verify a second `image_sender_job` coroutine returns immediately without entering the thread.
- Send cap: mock `output/` with 10 synthetic images; verify `send_photo` is called at most `MAX_IMAGES_PER_ITERATION` times in one iteration.
- Cooldown bypass: set `_LAST_SENT_TIMESTAMP` to > `SEND_COOLDOWN_SECONDS` ago, mock `are_images_similar` to `True`; verify `send_photo` is still called for the next candidate.
- `/admin` image send: mock `_get_latest_image_path` to return a path; verify `update.message.reply_photo` is called with that path.
- `/admin` no image fallback: mock `_get_latest_image_path` to `None`; verify text-only reply with a "No latest image available" note and no photo attempt.
- `/admin` image send failure: mock `_get_latest_image_path` to return a path and `reply_photo` to raise `TelegramError`; verify graceful text fallback and no unhandled exception.

**`README.md`**

Modified:
- Document new `MAX_IMAGES_PER_ITERATION` and `SEND_COOLDOWN_SECONDS` environment variables (optional, with defaults).
- Document `/admin` behavior: text summary + latest image file.
- Document image-sender guard behavior: no overlapping iterations, cap of 5 images per 5-second tick, 300-second cooldown duplicate bypass.

### 1.3 Data Flow Diagram

Image sender (new guard/cap/cooldown):
```
JobQueue tick (every 5s)
       │
       ▼
image_sender_job(context)
       │
       ▼
  _SENDER_LOCK locked?
    ├─ Yes → skip (log INFO)
    └─ No  → acquire lock
              │
              ▼
    asyncio.to_thread(_send_new_images_iteration)
              │
              ▼
    scan output/ for dated folders
              │
              ▼
    iterate unsent images in current folder
              │
              ▼
    ┌─────────────────────────────────────────────┐
    │ cooldown expired?                           │
    │ ├─ Yes → bypass similarity ONCE for this    │
    │ │        candidate, then normal check       │
    │ └─ No  → are_images_similar()?              │
    │          ├─ Yes → skip                      │
    │          └─ No  → send_photo()              │
    │                   ├─ success: increment cap │
    │                   │         update timestamp│
    │                   │         update state    │
    │                   │         cap reached?    │
    │                   │         ├─ Yes → break  │
    │                   │         └─ No  → next   │
    │                   └─ fail: log, next        │
    └─────────────────────────────────────────────┘
              │
              ▼
    cleanup_old_folders()
              │
              ▼
    release lock
```

`/admin` command (extended):
```
User sends /admin
       │
       ▼
admin_command(update, context)
       │
       ▼
  _is_admin_chat?
    ├─ No → silent return
    └─ Yes
         │
         ▼
    read output/triage_summary.json
         │
         ▼
    scan output/ for latest date folder
         │
         ▼
    _format_admin_message() → reply_text(text, Markdown)
         │
         ▼
    _get_latest_image_path()
         │
         ▼
    path exists?
    ├─ Yes → reply_photo(photo=path)
    │          └─ on exception → reply_text("No latest image available.")
    └─ No  → reply_text("No latest image available.")
```

### 1.4 Interfaces

**New environment variables (optional):**
- `MAX_IMAGES_PER_ITERATION` — maximum images sent in one `_send_new_images_iteration()` call. Default: `5`.
- `SEND_COOLDOWN_SECONDS` — seconds since last successful send after which the perceptual-hash duplicate filter is bypassed for the next candidate. Default: `300`.

**No new Python package dependencies.**

**File system interfaces (unchanged):**
- `output/` directory mounted as Docker volume (already configured).
- `output/YYYY-MM-DD/` dated subfolders created by `snapshot_triage.py`.
- `output/.last_sent_file` state file (format unchanged).
- `output/triage_summary.json` read-only dependency (schema unchanged).

**Telegram API interfaces (extended):**
- Existing `sendPhoto` for background image delivery (unchanged endpoint, updated internal tracking).
- New `sendPhoto` call inside `/admin` via `update.message.reply_photo()`.

---

## 2. Implementation Approach

### 2.1 Recommended: Additive changes to existing `tg_bot/bot.py`

Make four narrowly scoped, additive changes to the current `python-telegram-bot` Application setup. No refactor of the command handlers or Docker state logic.

**Change A — Concurrency guard:**
1. Add `_SENDER_LOCK = asyncio.Lock()` at module level.
2. Modify `image_sender_job()`:
   ```python
   async def image_sender_job(context: ContextTypes.DEFAULT_TYPE):
       if _SENDER_LOCK.locked():
           logger.info("Skipping overlapping image_sender_job")
           return
       async with _SENDER_LOCK:
           await asyncio.to_thread(_send_new_images_iteration)
   ```
   Rationale: The check-then-acquire pattern is safe in asyncio because there is no `await` between `locked()` and `async with`, so no other coroutine can interleave. If the lock is held, the job skips entirely rather than waiting, preserving the 5-second cadence and avoiding queue buildup.

**Change B — Per-iteration send cap:**
1. Add `MAX_IMAGES_PER_ITERATION = int(os.getenv("MAX_IMAGES_PER_ITERATION", "5"))` near other module constants.
2. In `_send_new_images_iteration()`, initialize `sent_count = 0` before the send loop.
3. After a successful `send_photo(path)`:
   ```python
   sent_count += 1
   if sent_count >= MAX_IMAGES_PER_ITERATION:
       break
   ```
   Rationale: Capping inside the iteration function keeps the boundary close to the send logic and naturally resumes at the next unsent image on the following tick because `LAST_SENT_IMAGE` is updated per successful send.

**Change C — Time-based duplicate bypass:**
1. Add `SEND_COOLDOWN_SECONDS = int(os.getenv("SEND_COOLDOWN_SECONDS", "300"))` and `_LAST_SENT_TIMESTAMP = 0.0` at module level.
2. In `send_photo()`, on success:
   ```python
   global _LAST_SENT_TIMESTAMP
   _LAST_SENT_TIMESTAMP = time.time()
   ```
3. In `_send_new_images_iteration()`, before the similarity check:
   ```python
   cooldown_expired = (time.time() - _LAST_SENT_TIMESTAMP) > SEND_COOLDOWN_SECONDS
   if LAST_SENT_IMAGE is not None and are_images_similar(LAST_SENT_IMAGE, path):
       if cooldown_expired:
           logger.info(f"Cooldown expired; sending {filename} despite similarity")
       else:
           logger.info(f"Skipped {filename} (too similar to last sent image)")
           continue
   ```
   Note: `cooldown_expired` is evaluated per candidate. Because the loop proceeds to `send_photo()` when expired, the timestamp updates immediately, so subsequent similar images in the same iteration are still subject to the similarity check. This satisfies the "next candidate image" wording in the scope.

**Change D — `/admin` sends latest image:**
1. Add `_get_latest_image_path()`:
   ```python
   def _get_latest_image_path() -> str | None:
       run_date = _get_latest_run_date()
       if not run_date:
           return None
       folder_path = os.path.join(OUTPUT_DIR, run_date)
       try:
           files = [
               f for f in os.listdir(folder_path)
               if f.lower().endswith(IMAGE_EXTENSIONS)
               and os.path.isfile(os.path.join(folder_path, f))
           ]
           if not files:
               return None
           latest = max(files, key=lambda f: os.path.getmtime(os.path.join(folder_path, f)))
           return os.path.join(folder_path, latest)
       except OSError:
           return None
   ```
2. Modify `admin_command()` to send the photo after the text reply:
   ```python
   text = _format_admin_message(summary, run_date, fresh)
   await update.message.reply_text(text, parse_mode="Markdown")

   image_path = _get_latest_image_path()
   if image_path:
       try:
           await update.message.reply_photo(photo=image_path)
       except Exception as e:
           logger.error(f"Failed to send latest image: {e}")
           await update.message.reply_text("No latest image available.")
   else:
       await update.message.reply_text("No latest image available.")
   ```
   Rationale: `reply_photo` accepts a file path string in `python-telegram-bot` v20, so no manual file-handle management is required. The photo is sent as a separate message so Telegram renders both the formatted text and the image.

### 2.2 Alternative: `threading.Lock` inside `_send_new_images_iteration()`

Use a `threading.Lock` acquired at the top of the synchronous function instead of an `asyncio.Lock` in the async wrapper.

**Pros**: Simpler mental model (sync function guards itself); no async state to reason about.
**Cons**: The `asyncio.to_thread()` call still spawns a thread every 5 seconds even when the lock is held; the thread immediately blocks and returns, wasting threadpool resources. Also, skipping the scheduled job is less explicit.

**Verdict**: Rejected. `asyncio.Lock` at the async boundary prevents unnecessary thread creation and makes the skip behavior explicit in logs.

### 2.3 Alternative: Persistent cooldown timestamp in `.last_sent_file`

Store the last-sent epoch timestamp inside `.last_sent_file` (e.g., `folder/filename|timestamp`) so the cooldown survives bot restarts.

**Pros**: Survives container restart; no in-memory state.
**Cons**: Requires changing the `.last_sent_file` format and the parser in `load_last_sent_file()` and `save_last_sent_file()`. The scope explicitly excludes persistent queue or file-based state beyond the existing `.last_sent_file` contract, and the format change is a regression risk for existing deployments.

**Verdict**: Rejected. In-memory `_LAST_SENT_TIMESTAMP` is sufficient; on restart the first image may be subject to similarity again, which is harmless. If restart survival is needed later, it can be added as a small follow-up increment.

### 2.4 Alternative: Cooldown bypass resets a flag instead of time check inside loop

Use a boolean `_COOLDOWN_BYPASS_READY` set by a background timer instead of computing `time.time() - _LAST_SENT_TIMESTAMP` inside the loop.

**Pros**: Decouples timer logic from send loop.
**Cons**: Adds another piece of global mutable state and a timer task; the time-delta check is simpler and stateless.

**Verdict**: Rejected. Direct time comparison is simpler and easier to test.

---

## 3. Key Tradeoffs

### 3.1 Concurrency Guard Placement

| Approach | Pros | Cons |
|----------|------|------|
| `asyncio.Lock` in `image_sender_job` (recommended) | Prevents thread spawn when busy; explicit skip logging; async-native | Slightly more complex than a plain function call |
| `threading.Lock` inside `_send_new_images_iteration` | Self-contained sync function | Wastes threadpool slots; skip is silent unless manually logged |

**Decision**: `asyncio.Lock` at the async boundary.

### 3.2 Send Cap Boundary

| Approach | Pros | Cons |
|----------|------|------|
| Cap inside `_send_new_images_iteration` (recommended) | Close to send logic; natural resume via `LAST_SENT_IMAGE` | Counter variable adds one line of state |
| Cap in `image_sender_job` via time limit | No counter needed | Less predictable (depends on execution speed, not image count) |

**Decision**: Image-count cap inside the iteration function.

### 3.3 Cooldown Time Source

| Approach | Pros | Cons |
|----------|------|------|
| In-memory global `float` (recommended) | Simple, zero file I/O, easy to mock in tests | Lost on restart |
| File mtime of `.last_sent_file` | Survives restart | Requires stat call; mtime resolution may be coarse on some filesystems |
| Extended `.last_sent_file` format with timestamp | Survives restart; explicit | Changes file contract; regression risk for existing state files |

**Decision**: In-memory global `_LAST_SENT_TIMESTAMP`. Restart behavior is acceptable.

### 3.4 `/admin` Image Send Method

| Approach | Pros | Cons |
|----------|------|------|
| `reply_photo` with file path string (recommended) | Clean API; ptb handles file open/close; sends as reply thread | Separate message from text summary |
| `send_photo` with explicit `chat_id` | Same API used by background sender | Must pass `chat_id` manually; no reply threading |
| Inline photo URL | No file upload; instant | Requires web-accessible URL; not guaranteed in all deployments |

**Decision**: `update.message.reply_photo(photo=path)`. The separate message is actually preferable because Telegram renders Markdown text and images independently; combining them reduces formatting control.

### 3.5 Bypass Scope (one image vs. entire iteration)

| Approach | Pros | Cons |
|----------|------|------|
| Bypass once for the next candidate only (recommended) | Minimal noise; respects duplicate filter for bulk of backlog | Slightly more code |
| Bypass for entire iteration when expired | Simpler (skip check entirely for one tick) | Could send many similar frames in a burst if cap is high and backlog exists |

**Decision**: Bypass once per cooldown period. This matches the scope wording and minimizes unexpected duplicate sends.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `python-telegram-bot==20.6` | Used by `tg_bot/bot.py` | Command handlers, `reply_photo`, JobQueue | None — already in use and tested |
| `asyncio` | stdlib, already used | `Lock` for concurrency guard | None |
| `time` | stdlib, already used | Epoch timestamp for cooldown | None |
| `output/` volume mount | Already in `docker-compose.yml` | File access for images and JSON | None |
| `triage_summary.json` schema | Stable (TASK-003/004/005) | `/admin` text data source | Low — additive with `.get()` defaults |

No new Python package dependencies.
No new container infrastructure changes.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Overlapping working-tree changes in `tg_bot/bot.py` with pending `/admin`/`/state` TASK-003 increments | Medium | This design only touches image-sending globals, `admin_command`, and test additions; the `/state` command and existing `/admin` text logic are intentionally unchanged. Coordinate merge order: accept prior `tg_bot` TASK-003 increments before implementing this design. |
| Cooldown bypass sends an unwanted nearly identical frame | Low | Cooldown is configurable via env var; operators can raise `SEND_COOLDOWN_SECONDS` to reduce frequency or set it very high to effectively disable bypass. |
| Send cap delays delivery during high-activity bursts | Low | Default of 5 images per 5 seconds is high for this use case; cap is configurable; backlog drains linearly. |
| `/admin` image fails for files near Telegram's 10 MB photo limit | Low | Camera frames are expected to be well under 10 MB; `reply_photo` exception is caught and falls back to text-only. |
| `_LAST_SENT_TIMESTAMP` lost on container restart causes immediate similarity bypass | Low | Only affects the very first candidate after restart; if the scene is static, one duplicate may be sent, then normal filtering resumes. |
| Mocking `asyncio.Lock` in unit tests is less intuitive than sync locks | Low | Test can patch `bot._SENDER_LOCK` with a mock that records acquire/locked calls; or test the sync function in isolation and test the async wrapper separately. |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `tg_bot/bot.py` | Modify | Add `_SENDER_LOCK`, `_LAST_SENT_TIMESTAMP`, `MAX_IMAGES_PER_ITERATION`, `SEND_COOLDOWN_SECONDS`; modify `send_photo`, `_send_new_images_iteration`, `image_sender_job`, `admin_command`; add `_get_latest_image_path` |
| `tests/test_tg_bot.py` | Modify | Add focused tests for concurrency guard, send cap, cooldown bypass, `/admin` image send, `/admin` no-image fallback, and `/admin` image send failure |
| `README.md` | Modify | Document `MAX_IMAGES_PER_ITERATION`, `SEND_COOLDOWN_SECONDS`, `/admin` image behavior, and sender guard behavior |
| `tg_bot/requirements.txt` | No change | No new dependencies |
| `docker-compose.yml` | No change | Explicitly excluded by scope |
| `cams_grabber/snapshot_triage.py` | No change | Explicitly excluded by scope |
| `web_viewer/app.py` | No change | Explicitly excluded by scope |

---

## 7. Validation Plan

1. `python3 -m py_compile tg_bot/bot.py tests/test_tg_bot.py` — syntax check on modified Python files.
2. Run new unit tests: `python3 -m unittest -v tests/test_tg_bot.py` — verify concurrency guard skip, send cap enforcement, cooldown bypass, and `/admin` photo fallback behaviors.
3. Run existing test suites: `python3 -m unittest -v tests/test_snapshot_triage.py` and `python3 -m unittest -v tests/test_web_viewer.py` — ensure no regression.
4. Manual smoke test (local or container):
   - Set `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID`.
   - Populate `output/YYYY-MM-DD/` with 10+ images, including some perceptually similar pairs.
   - Start bot; verify no "maximum running instances reached" warnings after forcing a slow send (e.g., temporary network throttle).
   - Verify only 5 images are sent in the first 5-second tick; remaining images sent on subsequent ticks.
   - Wait 5+ minutes; verify the next similar frame is sent despite perceptual hash.
   - Send `/admin` from authorized chat → verify text summary followed by a photo of the latest image.
   - Remove all images from latest folder → verify `/admin` returns text summary with "No latest image available."
5. Inspect final Git diff to confirm only `tg_bot/bot.py`, `tests/test_tg_bot.py`, and `README.md` are changed.
