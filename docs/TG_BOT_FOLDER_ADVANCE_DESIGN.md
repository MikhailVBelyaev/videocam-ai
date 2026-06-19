# TASK-002 Design: Fix tg_bot Still Stuck on Old LAST_SENT_FOLDER After Fresh-First

Job ID: 2026-06-19_190332_videocam-ai-fix-tg-bot-still-stuck-on-old-last-sent-folder-a-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `tg_bot/bot.py` | Telegram bot sending camera frames and handling `/admin`/`/state` | **Primary** — adds folder advancement logic when zero images are sent from a non-latest folder; extends `/admin` stuck-state visibility |
| `cams_grabber/snapshot_triage.py` | Local-folder image triage producing JSON/CSV | **None** — no source changes; `output/` dated folders are consumed read-only |
| `web_viewer` | Flask web server serving `output/` on port 8082 | None |
| `sys_monitor/monitor.py` | System health monitoring | None |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None |

### 1.2 Module-Level Changes

**`tg_bot/bot.py`**

Current image-sender flow (simplified):
```
JobQueue tick (every 5s)
  └─ image_sender_job
       └─ _send_new_images_iteration()
            ├─ list dated folders → sort ascending
            ├─ if LAST_SENT_FOLDER in subfolders:
            │      folder_index = subfolders.index(LAST_SENT_FOLDER)
            │   else:
            │      folder_index = len(subfolders) - 1
            ├─ current_folder = subfolders[folder_index]
            ├─ image_files = _get_image_list(current_folder)
            ├─ compute start_index from LAST_SENT_IMAGE
            ├─ remaining = image_files[start_index:]
            ├─ sort remaining by mtime descending
            └─ for each candidate:
                 ├─ stale? → skip, _SKIPPED_STALE_COUNT++
                 ├─ similar within cooldown? → skip, _SKIPPED_DUPLICATE_COUNT++
                 ├─ non-kept? → skip, _SKIPPED_NON_KEPT_COUNT++
                 └─ send_photo() → update LAST_SENT_IMAGE, LAST_SENT_FOLDER, .last_sent_file
```

Problem: when `LAST_SENT_FOLDER` is an old dated folder and every candidate in `remaining` is skipped, the loop exits with `sent_count == 0`. The function returns without changing `LAST_SENT_FOLDER`, so the next tick repeats the same old folder forever.

New flow:
```
JobQueue tick (every 5s)
  └─ image_sender_job
       └─ _send_new_images_iteration()
            ├─ list dated folders → sort ascending
            ├─ if LAST_SENT_FOLDER in subfolders:
            │      folder_index = subfolders.index(LAST_SENT_FOLDER)
            │   else:
            │      folder_index = len(subfolders) - 1
            ├─ current_folder = subfolders[folder_index]
            ├─ image_files = _get_image_list(current_folder)
            ├─ compute start_index from LAST_SENT_IMAGE
            ├─ remaining = image_files[start_index:]
            ├─ sort remaining by mtime descending
            ├─ for each candidate:
            │    ├─ stale? → skip
            │    ├─ similar within cooldown? → skip
            │    ├─ non-kept? → skip
            │    └─ send_photo() → sent_count++
            │
            ├─ NEW: if sent_count == 0 and current_folder != newest_folder:
            │         advance LAST_SENT_FOLDER to next folder
            │         clear LAST_SENT_IMAGE = None
            │         save_last_sent_file(new_folder, "")
            │      else:
            │         stay put (latest-folder boundary guard)
            └─ cleanup_old_folders()
```

New/changed functions and globals in `tg_bot/bot.py`:

| Symbol | Change | Description |
|--------|--------|-------------|
| `_send_new_images_iteration()` | Modify | After the send loop, adds folder-advancement block: if `sent_count == 0` and `current_folder` is not the newest dated folder, advance `LAST_SENT_FOLDER` to the next folder, clear `LAST_SENT_IMAGE` to `None`, and persist via `save_last_sent_file()` |
| `_format_admin_message()` | Modify | Appends `Watched folder`, `Newest folder`, `State file`, and `Status` fields to the Markdown summary |
| `save_last_sent_file()` | No change | Reused to persist advanced folder state; must handle empty `file_path` gracefully (format `new_folder/\n`) |
| `load_last_sent_file()` | No change | Must read `folder/\n` without crashing; already returns `(None, None)` for malformed lines |

**`tests/test_tg_bot.py`**

New tests to add (focused, no broad refactor):
- **Old folder all stale → advances**: mock `OUTPUT_DIR` with `2026-06-18/` (all images older than `MAX_IMAGE_AGE_SECONDS`) and `2026-06-19/` (fresh images). Set `LAST_SENT_FOLDER` to `2026-06-18`. Verify `_send_new_images_iteration()` advances `LAST_SENT_FOLDER` to `2026-06-19` and clears `LAST_SENT_IMAGE`.
- **Old folder all similar → advances**: mock old folder where every remaining image is similar to `LAST_SENT_IMAGE` and cooldown has not expired. Verify advancement to next folder.
- **Old folder fully sent → advances**: mock old folder where `LAST_SENT_IMAGE` is the last image. Verify `sent_count == 0` and advancement.
- **Latest folder zero sends → stays put**: mock single dated folder where all images are stale. Verify `LAST_SENT_FOLDER` does not change and no exception is raised.
- **Normal send in old folder → no advance**: mock old folder with one fresh unsent image. Verify the image is sent, `sent_count > 0`, and `LAST_SENT_FOLDER` remains unchanged.
- **Multi-folder rapid advancement**: mock three old folders all stale. Verify the bot advances through them in successive iterations until reaching the latest.
- **`/admin` stuck-state fields**: mock `LAST_SENT_FOLDER`, `LAST_SENT_IMAGE`, and `_get_latest_run_date()`. Verify `_format_admin_message()` includes correct `Watched folder`, `Newest folder`, `State file`, and `Status` lines.
- **State file persistence on advancement**: verify that after advancement, `.last_sent_file` contains `new_folder/\n` and `load_last_sent_file()` reads it as `(new_folder, None)`.

**`README.md` / `docs/TG_BOT_RUNBOOK.md`**

Modified:
- Document folder advancement behavior: when the current folder yields zero sends because all remaining images are skipped, the bot automatically advances to the next dated folder.
- Document latest-folder boundary guard: when already on the newest folder, the bot stays put.
- Document new `/admin` fields: `Watched folder`, `Newest folder`, `State file`, `Status`.
- Add troubleshooting entry: "Bot stuck on old folder" — check `/admin` `Status` field; if `Stuck on <folder>`, the bot will auto-advance on the next zero-send iteration.

### 1.3 Data Flow Diagram

Folder advancement inside `_send_new_images_iteration()`:
```
_send_new_images_iteration()
  │
  ├─ list subfolders → sort ascending
  │
  ├─ determine current_folder from LAST_SENT_FOLDER
  │
  ├─ image_files = _get_image_list(current_folder)
  │
  ├─ compute start_index from LAST_SENT_IMAGE
  │
  ├─ remaining = image_files[start_index:]
  │
  ├─ sort remaining by mtime descending
  │
  ├─ sent_count = 0
  │
  ├─ for filename in remaining:
  │    ├─ stale?      → _SKIPPED_STALE_COUNT++, _LAST_SKIP_REASON="stale", continue
  │    ├─ similar?    → _SKIPPED_DUPLICATE_COUNT++, _LAST_SKIP_REASON="similar", continue
  │    ├─ non-kept?   → _SKIPPED_NON_KEPT_COUNT++, _LAST_SKIP_REASON="non-kept", continue
  │    └─ send_photo() → sent_count++
  │         └─ update LAST_SENT_IMAGE, LAST_SENT_FOLDER, .last_sent_file
  │
  ├─ NEW: newest_folder = _get_latest_run_date()
  │
  ├─ NEW: if sent_count == 0 and current_folder != newest_folder:
  │    │         next_index = subfolders.index(current_folder) + 1
  │    │         new_folder = subfolders[next_index]
  │    │         LAST_SENT_FOLDER = new_folder
  │    │         LAST_SENT_IMAGE = None
  │    │         save_last_sent_file(new_folder, "")
  │    │         logger.info(f"Advanced to folder: {new_folder}")
  │    │    else:
  │    │         pass  # stay put
  │
  └─ cleanup_old_folders()
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
    read output/triage_summary.json (or live_output fallback)
         │
         ▼
    _format_admin_message()
         │
         ├─ existing fields (Images, Objects, Videos, Missing, Sent, Skipped counters)
         ├─ existing fields (Backlog size, Latest capture, Latest sent, Last skip reason)
         ├─ NEW: Watched folder: <folder>
         ├─ NEW: Newest folder: <folder>
         ├─ NEW: State file: <content or "not set">
         └─ NEW: Status: Fresh | Stuck on <folder>
         │
         ▼
    reply_text(text, Markdown)
         │
         ▼
    _get_latest_image_path() → reply_photo (existing behavior)
```

### 1.4 Interfaces

**No new environment variables.**

**No new Python package dependencies.**

**File system interfaces (extended):**
- `output/.last_sent_file` — now written with an empty filename on folder advancement (format: `new_folder/\n`). Must be readable by `load_last_sent_file()` without crashing.
- `output/YYYY-MM-DD/` dated subfolders — read to determine `newest_folder` and advancement target.

**Telegram API interfaces:** Unchanged.

---

## 2. Implementation Approach

### 2.1 Recommended: Additive changes to `tg_bot/bot.py`

Make two narrowly scoped, additive changes. No refactor of command handlers, Docker state logic, startup initialization, or the send loop body.

**Change A — Folder advancement block in `_send_new_images_iteration()`:**

After the existing send loop and before `cleanup_old_folders()`, add:

```python
        # Folder advancement: if nothing was sent and we are not on the latest folder,
        # advance to the next dated folder so the bot does not stay stuck on stale folders.
        newest_folder = _get_latest_run_date()
        if sent_count == 0 and newest_folder and current_folder != newest_folder:
            next_index = folder_index + 1
            if next_index < len(subfolders):
                new_folder = subfolders[next_index]
                global LAST_SENT_IMAGE, LAST_SENT_FOLDER
                LAST_SENT_FOLDER = new_folder
                LAST_SENT_IMAGE = None
                save_last_sent_file(new_folder, "")
                logger.info(f"Advanced to folder: {new_folder}")
```

Rationale:
- The advancement trigger (`sent_count == 0`) is a safe proxy for "all remaining images in this folder were actively filtered out." If even one image passes filters and is sent, the folder is still productive and should not advance.
- The boundary guard (`current_folder != newest_folder`) prevents advancing past the latest folder, which would cause an `IndexError` or infinite loop.
- Clearing `LAST_SENT_IMAGE` to `None` is correct because there is no meaningful cursor in the new folder yet; the next iteration will compute `start_index = 0`.
- Persisting via `save_last_sent_file(new_folder, "")` writes `new_folder/\n`, which `load_last_sent_file()` already handles (it splits on `/` and validates `len(parts) == 2`; an empty second part returns `(None, None)`).

**Change B — Extend `_format_admin_message()`:**

Append the following lines before the final `return`:

```python
    # Stuck-state visibility
    watched_folder = LAST_SENT_FOLDER or "Unknown"
    newest_folder = _get_latest_run_date() or "Unknown"
    state_file_content = "not set"
    try:
        if os.path.exists(LAST_SENT_FILE):
            with open(LAST_SENT_FILE, "r") as f:
                state_file_content = f.read().strip() or "empty"
    except OSError:
        state_file_content = "unreadable"

    if watched_folder == newest_folder:
        status = "✅ Fresh"
    else:
        status = f"⚠️ Stuck on {watched_folder}"

    lines.extend([
        "",
        f"*Watched folder:* `{watched_folder}`",
        f"*Newest folder:* `{newest_folder}`",
        f"*State file:* `{state_file_content}`",
        f"*Status:* {status}",
    ])
```

Rationale:
- All four fields are derived from existing globals and helpers; no new state is introduced.
- The `Status` indicator gives operators an immediate yes/no answer to "is the bot stuck?"
- Reading `.last_sent_file` directly (rather than relying on `load_last_sent_file()`) preserves the raw content for debugging; `load_last_sent_file()` normalizes paths, which hides format issues.

### 2.2 Alternative: Advance unconditionally after every iteration

Always move to the next folder at the end of each iteration, wrapping around or stopping at the latest.

**Pros**: Simpler logic; no `sent_count` dependency.
**Cons**: Would skip unsent images in the current folder if the send cap (`MAX_IMAGES_PER_ITERATION`) was reached. A folder with 10 fresh images and cap=5 would advance after sending 5, leaving 5 unsent forever.

**Verdict**: Rejected. The `sent_count == 0` condition is the only safe trigger; it means the folder is exhausted, not merely capped.

### 2.3 Alternative: Advance only when all images are stale

Check whether every remaining image exceeded `MAX_IMAGE_AGE_SECONDS`, and advance only in that case.

**Pros**: More precise trigger; does not advance on similarity skips.
**Cons**: More complex to implement (requires tracking skip reasons per iteration); does not handle the case where all images are similar within cooldown or all are non-kept. The `sent_count == 0` condition already covers all three skip paths uniformly.

**Verdict**: Rejected. `sent_count == 0` is simpler, covers all skip paths, and is safe because any productive folder will have at least one send.

### 2.4 Alternative: Advance to the newest folder instead of the next folder

Jump directly from an old folder to `_get_latest_run_date()`.

**Pros**: Reaches fresh content in one iteration.
**Cons**: Skips intermediate folders that might contain fresh images. If `2026-06-18` and `2026-06-19` both exist, jumping from `2026-06-17` straight to `2026-06-19` would miss `2026-06-18` entirely.

**Verdict**: Rejected. Advancing one folder at a time preserves chronological ordering and ensures no folder is skipped.

### 2.5 Alternative: Use a separate state file for folder advancement

Write folder-advancement state to a new file (e.g., `.last_folder_file`) instead of reusing `.last_sent_file`.

**Pros**: Isolates folder state from image state; cleaner contract.
**Cons**: Introduces a new file contract, requires new read/write logic, and duplicates the existing state model. The scope explicitly excludes new architecture.

**Verdict**: Rejected. Reusing `.last_sent_file` with an empty filename is a minimal, backward-compatible extension of the existing contract.

---

## 3. Key Tradeoffs

### 3.1 Advancement Trigger

| Approach | Pros | Cons |
|----------|------|------|
| `sent_count == 0` (recommended) | Covers stale, similar, and non-kept skips uniformly; simple; safe (productive folders never advance) | If a folder has only one fresh image and it is skipped for similarity, the folder advances; that one image may never be sent |
| Stale-only trigger | More precise for the reported bug | Misses similar and non-kept lock-in; more complex |
| Unconditional per-iteration advance | Very simple | Skips capped-but-unsent images |

**Decision**: `sent_count == 0`.

### 3.2 Advancement Step Size

| Approach | Pros | Cons |
|----------|------|------|
| Next folder (recommended) | Preserves chronological order; no folder skipped | May take multiple iterations to reach the latest folder |
| Jump to newest folder | One-iteration recovery | Skips intermediate folders that may have fresh images |

**Decision**: Next folder.

### 3.3 State File Format on Cleared LAST_SENT_IMAGE

| Approach | Pros | Cons |
|----------|------|------|
| `folder/\n` via `save_last_sent_file(folder, "")` (recommended) | Reuses existing writer; `load_last_sent_file()` already handles malformed lines | Raw content shows an empty filename |
| `folder/None` or `folder/null` | Explicit sentinel | Requires modifying `load_last_sent_file()` to parse the sentinel; new contract risk |
| New file for folder state | Clean separation | New contract; out of scope |

**Decision**: `folder/\n`.

### 3.4 /admin Stuck-State Field Source

| Approach | Pros | Cons |
|----------|------|------|
| Read `.last_sent_file` directly for raw content (recommended) | Preserves exact file content for debugging; reveals format issues | Duplicates one `open()` call already present in `load_last_sent_file()` |
| Reuse `load_last_sent_file()` | Single read path | Normalizes paths and hides raw content; harder to debug malformed files |

**Decision**: Direct read for raw display.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `python-telegram-bot==20.6` | Used by `tg_bot/bot.py` | Command handlers, JobQueue | None — unchanged |
| `_get_latest_run_date()` | Already implemented and QA-tested | Determine newest folder for boundary guard | Low — existing helper with OSError handling |
| `save_last_sent_file()` | Already implemented | Persist advanced folder state | Low — existing helper |
| `load_last_sent_file()` | Already implemented | Read advanced state on restart | Low — already handles malformed lines |
| `output/` volume mount | Already in `docker-compose.yml` | File access for images and state | None |

No new Python package dependencies.
No new container infrastructure changes.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Overlapping working-tree changes in `tg_bot/bot.py` with pending fresh-first TASK-003/004/005 increments (in `review_required`) | Medium | This design touches only the end of `_send_new_images_iteration()` and `_format_admin_message()`; no changes to the send loop body, command handlers, concurrency/cooldown logic, startup initialization, or triage-aware selection. Coordinate merge order: accept prior `tg_bot` increments before implementing this design. |
| Advancing past unsent images that were skipped only for similarity (cooldown not expired) | Low | The cooldown is time-based (default 300s); if the bot advances to a newer folder, the old image is likely outdated anyway. Operators can lower `MAX_IMAGE_AGE_SECONDS` to force stale skipping before cooldown skipping. |
| Rapid multi-folder advancement on restart consumes iterations without sending | Low | This is desired behavior; the bot should reach the newest folder quickly. State is persisted after each advancement, so a restart resumes from the advanced position. |
| `save_last_sent_file(new_folder, "")` writes `new_folder/\n`, which `load_last_sent_file()` may mis-parse | Low | `load_last_sent_file()` splits on `/` and validates `len(parts) == 2`; a trailing newline after the slash still yields `parts == ["new_folder", ""]`, which satisfies `len(parts) == 2`. The returned `filename` is empty, so `os.path.join(OUTPUT_DIR, folder, "")` evaluates to `OUTPUT_DIR/folder/`, which is not a valid file path. Callers of `load_last_sent_file()` (only `main()`) should treat a returned `LAST_SENT_IMAGE` of `OUTPUT_DIR/folder/` as effectively `None` for cursor purposes. In practice, `main()` does `if LAST_SENT_IMAGE:` which is truthy for a non-empty string, but the path `OUTPUT_DIR/folder/` does not exist as a file, so `_send_new_images_iteration()` will fail `os.path.isfile(path)` and fall back to `start_index = 0`. This is acceptable. To be strictly safe, the implementation can add a guard in `main()` or `_send_new_images_iteration()` to treat a non-existent `LAST_SENT_IMAGE` as `None`. |
| State file write races with concurrent `send_photo()` updates | Low | `save_last_sent_file()` opens the file with `"w"` (truncate + write), which is atomic for small files on POSIX. The advancement block runs inside the same thread as the send loop, and `image_sender_job` holds `_SENDER_LOCK`, so no concurrent sender exists. `/admin` does not write state. |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `tg_bot/bot.py` | Modify | Add folder advancement block to `_send_new_images_iteration()`; extend `_format_admin_message()` with stuck-state fields |
| `tests/test_tg_bot.py` | Modify | Add focused tests for folder advancement, latest-folder boundary guard, backward compatibility, multi-folder rapid advancement, state file persistence, and `/admin` stuck-state fields |
| `README.md` | Modify | Document folder advancement behavior, latest-folder boundary guard, and new `/admin` fields |
| `docs/TG_BOT_RUNBOOK.md` | Modify | Document folder advancement behavior, latest-folder boundary guard, new `/admin` fields, and "bot stuck on old folder" troubleshooting entry |
| `tg_bot/requirements.txt` | No change | No new dependencies |
| `docker-compose.yml` | No change | Explicitly excluded by scope |
| `cams_grabber/snapshot_triage.py` | No change | Explicitly excluded by scope |
| `web_viewer/app.py` | No change | Explicitly excluded by scope |

---

## 7. Validation Plan

1. `python3 -m py_compile tg_bot/bot.py tests/test_tg_bot.py` — syntax check on modified Python files.
2. Run new unit tests: `python3 -m unittest -v tests.test_tg_bot.TgBotFolderAdvanceTests` — verify advancement, boundary guard, backward compatibility, and `/admin` fields.
3. Run existing test suites: `python3 -m unittest -v tests/test_tg_bot.py`, `python3 -m unittest -v tests/test_snapshot_triage.py`, `python3 -m unittest -v tests/test_web_viewer.py` — ensure no regression.
4. Manual smoke test (local or container):
   - Populate `output/2026-06-18/` with 3 stale images (mtime > 1 hour ago).
   - Populate `output/2026-06-19/` with 3 fresh images.
   - Set `.last_sent_file` to `2026-06-18/oldest.jpg`.
   - Start bot; verify first iteration skips all stale images in `2026-06-18` and advances to `2026-06-19`.
   - Verify `.last_sent_file` is updated to `2026-06-19/\n`.
   - Verify next iteration sends fresh images from `2026-06-19`.
   - Send `/admin` from authorized chat → verify text summary includes `Watched folder`, `Newest folder`, `State file`, and `Status: Fresh` (or `Stuck on ...` before advancement).
   - Test boundary guard: set `.last_sent_file` to `2026-06-19/last.jpg` (last image). Verify zero sends, no advancement, no crash.
5. Inspect final Git diff to confirm only `tg_bot/bot.py`, `tests/test_tg_bot.py`, `README.md`, and `docs/TG_BOT_RUNBOOK.md` are changed.
