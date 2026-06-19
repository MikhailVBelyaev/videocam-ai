# TASK-002 Design: Fix Remaining Telegram Image Backlog Problem

Job ID: 2026-06-19_151143_videocam-ai-fix-remaining-telegram-image-backlog-problem-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `tg_bot/bot.py` | Telegram bot sending camera frames and handling `/admin`/`/state` | **Primary** — adds startup state initialization when `.last_sent_file` is missing |
| `cams_grabber/snapshot_triage.py` | Local-folder image triage producing JSON/CSV | **None** — no source changes; `output/` dated folders are consumed read-only |
| `web_viewer` | Flask web server serving `output/` on port 8082 | None |
| `sys_monitor/monitor.py` | System health monitoring | None |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None |

### 1.2 Module-Level Changes

**`tg_bot/bot.py`**

Current startup flow:
```
main()
  └─ load_last_sent_file()
       ├─ file exists → LAST_SENT_FOLDER, LAST_SENT_IMAGE set
       └─ file missing → LAST_SENT_FOLDER=None, LAST_SENT_IMAGE=None
            └─ JobQueue tick → _send_new_images_iteration()
                 └─ start_index = 0 → iterate ALL images in latest folder
                      └─ similarity check skips most, but loop touches every file
```

New startup flow:
```
main()
  └─ load_last_sent_file()
       ├─ file exists → behavior unchanged
       └─ file missing → LAST_SENT_FOLDER=None, LAST_SENT_IMAGE=None
            └─ _initialize_startup_state()
                 └─ _get_latest_image_path()
                      ├─ image found → set LAST_SENT_IMAGE, LAST_SENT_FOLDER
                      │                → save_last_sent_file() (persist state)
                      └─ no image → remains None
            └─ next JobQueue tick → _send_new_images_iteration()
                 └─ start_index after initialized image → only new frames processed
```

New/changed functions in `tg_bot/bot.py`:

| Function | Change | Description |
|----------|--------|-------------|
| `_initialize_startup_state()` | Add | Scans latest dated folder for most recently modified image; initializes `LAST_SENT_IMAGE` and `LAST_SENT_FOLDER` without sending; persists state via `save_last_sent_file()` |
| `main()` | Modify | Calls `_initialize_startup_state()` when `load_last_sent_file()` returns `(None, None)` |

**`tests/test_tg_bot.py`**

New tests to add (focused, no broad refactor):
- No-state startup with images: mock `OUTPUT_DIR` with dated folder and images; verify `_initialize_startup_state()` sets `LAST_SENT_IMAGE` to the most recently modified image and `LAST_SENT_FOLDER` to the folder name.
- No-state startup with empty folder: mock `OUTPUT_DIR` with dated folder containing no images; verify `_initialize_startup_state()` returns `(None, None)` and leaves globals unset.
- No-state startup with no dated folders: mock `OUTPUT_DIR` empty; verify `_initialize_startup_state()` returns `(None, None)`.
- Existing `.last_sent_file` present: mock `LAST_SENT_FILE` with content; verify `load_last_sent_file()` behavior is unchanged and `_initialize_startup_state()` is not invoked (or does not overwrite).

**`README.md` / `docs/TG_BOT_RUNBOOK.md`**

Modified:
- Document startup behavior: on first start or restart without persisted state, the bot resumes from the latest existing image rather than draining the folder.

### 1.3 Data Flow Diagram

Startup state initialization:
```
main()
  │
  ▼
load_last_sent_file()
  │
  ├─ file exists? ──Yes──► set LAST_SENT_FOLDER, LAST_SENT_IMAGE
  │                          └─ log "Loaded last sent file from state"
  │
  └─ No ──► log "No previously sent file found in state"
       │
       ▼
_initialize_startup_state()
       │
       ▼
_get_latest_image_path()
       │
       ├─ returns path ──► set LAST_SENT_IMAGE = path
       │                    set LAST_SENT_FOLDER = folder name
       │                    save_last_sent_file(folder, path)
       │                    log "Initialized state to latest image: {path}"
       │
       └─ returns None ──► leave globals as None
                            log "No images found for state initialization"
```

### 1.4 Interfaces

**No new environment variables.**

**No new Python package dependencies.**

**File system interfaces (extended):**
- `output/.last_sent_file` — now written during startup initialization in addition to post-send updates. Format unchanged.
- `output/YYYY-MM-DD/` dated subfolders — read to find latest image on startup.

**Telegram API interfaces:** Unchanged.

---

## 2. Implementation Approach

### 2.1 Recommended: Additive changes to `tg_bot/bot.py`

**Change A — Extract startup initialization helper:**

Add `_initialize_startup_state()`:

```python
def _initialize_startup_state() -> tuple[str | None, str | None]:
    """Initialize LAST_SENT_IMAGE and LAST_SENT_FOLDER to the latest existing image when no state file exists."""
    global LAST_SENT_IMAGE, LAST_SENT_FOLDER
    latest_image = _get_latest_image_path()
    if latest_image:
        LAST_SENT_IMAGE = latest_image
        LAST_SENT_FOLDER = os.path.relpath(os.path.dirname(latest_image), OUTPUT_DIR)
        save_last_sent_file(LAST_SENT_FOLDER, LAST_SENT_IMAGE)
        logger.info(f"Initialized state to latest image: {latest_image}")
        return LAST_SENT_FOLDER, LAST_SENT_IMAGE
    return None, None
```

Rationale: Extracting the helper makes it independently unit-testable without invoking the blocking `app.run_polling()` in `main()`.

**Change B — Modify `main()` to call helper:**

```python
def main():
    global LAST_SENT_IMAGE, LAST_SENT_FOLDER
    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError("❌ TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set as env variables")

    logger.info("📡 Telegram bot started, watching for new files...")
    LAST_SENT_FOLDER, LAST_SENT_IMAGE = load_last_sent_file()
    if LAST_SENT_IMAGE:
        logger.info(f"Loaded last sent file from state: {LAST_SENT_IMAGE}")
    else:
        logger.info("No previously sent file found in state")
        _initialize_startup_state()

    app = Application.builder().token(BOT_TOKEN).build()
    ...
```

Rationale: Minimal change to existing `main()` structure; the helper encapsulates the new behavior.

**Change C — Persist initialized state:**

Call `save_last_sent_file()` inside `_initialize_startup_state()` so that:
- A subsequent restart finds `.last_sent_file` and skips re-initialization.
- The first scheduled iteration begins from the image after the initialized one, not from index 0.

Rationale: Without persistence, every restart without `.last_sent_file` would re-scan and re-initialize, which is harmless but redundant. Persistence aligns with the existing state contract.

### 2.2 Alternative: Inline initialization in `main()` without helper

Keep the logic inline in `main()` and test it via integration tests or by mocking `Application`.

**Pros**: No new function; smaller diff.
**Cons**: `main()` is not unit-testable without heavy mocking of `Application.builder()` and `run_polling()`. The scope requires focused unit tests.

**Verdict**: Rejected. Extracting a helper is a one-function, ~10-line addition that dramatically improves testability.

### 2.3 Alternative: Do not persist state on initialization

Initialize `LAST_SENT_IMAGE` and `LAST_SENT_FOLDER` in memory but do not write `.last_sent_file`.

**Pros**: Zero file writes on startup; slightly safer if initialization picks the wrong image.
**Cons**: Every restart without `.last_sent_file` repeats the scan; container restarts in a crash-loop would log initialization repeatedly; the state file contract is not maintained.
**Verdict**: Rejected. Writing `.last_sent_file` is a single line (`save_last_sent_file`) and preserves the existing state persistence model.

### 2.4 Alternative: Use `_get_latest_run_date()` + manual scan instead of `_get_latest_image_path()`

Reimplement the folder scan in `_initialize_startup_state()` instead of reusing `_get_latest_image_path()`.

**Pros**: No dependency on a helper that also serves `/admin`.
**Cons**: Duplicates logic; `_get_latest_image_path()` already implements exactly the scan we need and is covered by QA tests.
**Verdict**: Rejected. Reusing the existing helper minimizes code duplication and leverages existing test coverage.

---

## 3. Key Tradeoffs

### 3.1 Helper Extraction vs. Inline

| Approach | Pros | Cons |
|----------|------|------|
| Extract `_initialize_startup_state()` (recommended) | Independently testable; clear separation of concerns; minimal change to `main()` | One new function |
| Inline in `main()` | Smaller function count | Not unit-testable without heavy mocking |

**Decision**: Extract helper.

### 3.2 State Persistence on Initialization

| Approach | Pros | Cons |
|----------|------|------|
| Write `.last_sent_file` on initialization (recommended) | Survives restart; aligns with existing state contract; eliminates redundant scans | One file write on first start |
| In-memory only | No file I/O on startup | Re-scans on every restart; inconsistent with rest of state model |

**Decision**: Persist via `save_last_sent_file()`.

### 3.3 Timestamp Implications for Cooldown Bypass

Initializing `LAST_SENT_IMAGE` without updating `_LAST_SENT_TIMESTAMP` means the first candidate in the next iteration will see `cooldown_expired = (time.time() - 0.0) > 300` → `True`, causing an immediate bypass of the similarity check for the first new frame.

| Approach | Pros | Cons |
|----------|------|------|
| Leave `_LAST_SENT_TIMESTAMP` unchanged (recommended) | No extra state to manage; first new frame after restart is sent promptly, which is usually desired | If the scene is completely static, one duplicate frame may be sent immediately after restart |
| Set `_LAST_SENT_TIMESTAMP = time.time()` on initialization | Prevents immediate cooldown bypass; more conservative | First new frame may be skipped for 300s if similar; adds implicit behavior not in scope |

**Decision**: Leave `_LAST_SENT_TIMESTAMP` unchanged. The scope does not mention timestamp initialization, and the cooldown bypass on the first candidate is harmless.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `python-telegram-bot==20.6` | Used by `tg_bot/bot.py` | `main()` Application setup | None — unchanged |
| `_get_latest_image_path()` | Already implemented and QA-tested | Startup scan for latest image | Low — existing helper with OSError handling |
| `_get_latest_run_date()` | Already implemented and QA-tested | Used by `_get_latest_image_path()` | None |
| `save_last_sent_file()` | Already implemented | Persist initialized state | None |
| `output/` volume mount | Already in `docker-compose.yml` | File access for images and state | None |

No new Python package dependencies.
No new container infrastructure changes.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Overlapping working-tree changes in `tg_bot/bot.py` with pending Telegram delivery TASK-003/004/005 increments | Medium | This design touches only `main()` and adds one helper; no changes to image-sending loop, command handlers, or concurrency/cooldown logic. Coordinate merge order: accept prior `tg_bot` increments before implementing this design. |
| Initialized image may never have been sent | Low | The scope explicitly accepts this tradeoff: initializing to the latest file is preferable to draining the entire folder. The bot will resume processing new frames immediately. |
| `mtime` ordering may not match chronological capture order | Low | The project already relies on `mtime` for freshness checks (`_is_fresh`, `_get_latest_image_path`); this design does not introduce new time-based logic. |
| Writing `.last_sent_file` on startup could race with concurrent `send_photo()` updates | Low | `save_last_sent_file()` opens the file with `"w"` (truncate + write), which is atomic for small files on POSIX. The first scheduled iteration runs 5 seconds after startup, so no race exists under normal startup. |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `tg_bot/bot.py` | Modify | Add `_initialize_startup_state()`; modify `main()` to call it when `load_last_sent_file()` returns `(None, None)` |
| `tests/test_tg_bot.py` | Modify | Add focused tests for no-state startup with images, empty folder, no dated folders, and existing-state unchanged behavior |
| `README.md` | Modify | Document startup state initialization behavior |
| `docs/TG_BOT_RUNBOOK.md` | Modify | Document startup state initialization behavior |
| `tg_bot/requirements.txt` | No change | No new dependencies |
| `docker-compose.yml` | No change | Explicitly excluded by scope |
| `cams_grabber/snapshot_triage.py` | No change | Explicitly excluded by scope |
| `web_viewer/app.py` | No change | Explicitly excluded by scope |

---

## 7. Validation Plan

1. `python3 -m py_compile tg_bot/bot.py tests/test_tg_bot.py` — syntax check on modified Python files.
2. Run new unit tests: `python3 -m unittest -v tests.test_tg_bot.TgBotStartupStateTests` — verify initialization behavior.
3. Run existing test suites: `python3 -m unittest -v tests/test_tg_bot.py`, `python3 -m unittest -v tests/test_snapshot_triage.py`, `python3 -m unittest -v tests/test_web_viewer.py` — ensure no regression.
4. Manual smoke test (local or container):
   - Remove `output/.last_sent_file`.
   - Populate `output/2026-06-19/` with 10 images of varying mtimes.
   - Start bot; verify log shows initialization to the most recently modified image.
   - Verify `.last_sent_file` is created with that image.
   - Verify first scheduled iteration starts from the image after the initialized one.
   - Stop bot, restore `.last_sent_file`; verify startup loads existing state and skips initialization.
5. Inspect final Git diff to confirm only `tg_bot/bot.py`, `tests/test_tg_bot.py`, `README.md`, and `docs/TG_BOT_RUNBOOK.md` are changed.
