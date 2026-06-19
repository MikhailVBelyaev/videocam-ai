# TASK-002 Design: Ignore Old Telegram Image Backlog and Process Fresh Live

Job ID: 2026-06-19_172411_videocam-ai-ignore-old-telegram-image-backlog-and-process-fr-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `tg_bot/bot.py` | Telegram bot sending camera frames and handling `/admin`/`/state` | **Primary** — changes image-sender traversal order to newest-first and adds max-age staleness filter; extends `/admin` counters/timestamps |
| `cams_grabber/snapshot_triage.py` | Local-folder image triage producing JSON/CSV | **None** — no source changes; `output/` dated folders are consumed read-only |
| `web_viewer` | Flask web server serving `output/` on port 8082 | None |
| `sys_monitor/monitor.py` | System health monitoring | None |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None |

### 1.2 Module-Level Changes

**`tg_bot/bot.py`**

Current image-sender flow:
```
JobQueue runs image_sender_job every 5s
  └─ acquire _SENDER_LOCK (skip if held)
       └─ asyncio.to_thread(_send_new_images_iteration)
            └─ scan output/ dated folders
                 └─ _get_image_list() → sorted(files) (alphabetical ascending)
                      └─ compute start_index from LAST_SENT_IMAGE in ascending list
                           └─ iterate image_files[start_index:] in alphabetical order
                                └─ similarity / cooldown / send cap logic
                                     └─ send_photo() or skip
```

New flow:
```
JobQueue runs image_sender_job every 5s
  └─ acquire _SENDER_LOCK (skip if held)
       └─ asyncio.to_thread(_send_new_images_iteration)
            └─ scan output/ dated folders
                 └─ _get_image_list() → sorted(files) (alphabetical ascending)
                      └─ compute start_index from LAST_SENT_IMAGE in ascending list
                           └─ sort image_files[start_index:] by mtime descending
                                └─ iterate remaining images newest-first
                                     ├─ mtime older than MAX_IMAGE_AGE_SECONDS? → skip stale
                                     ├─ similarity / cooldown / send cap logic
                                     └─ send_photo() or skip
```

New/changed functions and globals in `tg_bot/bot.py`:

| Symbol | Change | Description |
|--------|--------|-------------|
| `MAX_IMAGE_AGE_SECONDS` | Add | `int(os.getenv("MAX_IMAGE_AGE_SECONDS", "3600"))` — staleness cutoff in seconds |
| `_SKIPPED_STALE_COUNT` | Add | Module-level `int` counting images skipped because they exceeded `MAX_IMAGE_AGE_SECONDS` |
| `_LAST_SKIP_REASON` | Add | Module-level `str` recording the most recent skip reason (`"similar"`, `"non-kept"`, `"stale"`, or `""`) |
| `_send_new_images_iteration()` | Modify | Sorts remaining unsent images by mtime descending after computing `start_index`; applies max-age filter; tracks `_LAST_SKIP_REASON` |
| `_format_admin_message()` | Modify | Appends `_SKIPPED_STALE_COUNT`, backlog size, latest capture time, latest sent time, and `_LAST_SKIP_REASON` to the Markdown summary |
| `send_photo()` | Modify | Clears `_LAST_SKIP_REASON` on successful send (optional; keeps reason if last action was a skip) |

**`tests/test_tg_bot.py`**

New tests to add (focused, no broad refactor):
- Newest-first ordering: mock a dated folder with two unsent images where the alphabetically later file has an older mtime; verify the fresher file is sent first.
- Newest-first cursor stability: mock `LAST_SENT_IMAGE` pointing to the alphabetically first file; verify a newly arrived file that sorts after the cursor in ascending order is still reachable on the next tick.
- Max-age filter skips stale file: mock an image with mtime older than `MAX_IMAGE_AGE_SECONDS`; verify it is skipped, `_SKIPPED_STALE_COUNT` increments, and `_LAST_SKIP_REASON` becomes `"stale"`.
- Max-age default: verify `_send_new_images_iteration()` uses 3600 seconds when the env var is unset.
- Max-age custom value: set `MAX_IMAGE_AGE_SECONDS=60`; verify the filter uses 60 seconds.
- Max-age invalid env var: set `MAX_IMAGE_AGE_SECONDS=not_a_number`; verify graceful fallback to 3600.
- `/admin` extended fields: mock counters and state; verify `_format_admin_message()` includes `Skipped (stale): N`, `Backlog size: N`, `Latest capture: <timestamp>`, `Latest sent: <timestamp or Never>`, and `Last skip reason: <reason>`.
- Backward compatibility: verify existing concurrency guard, send cap, cooldown bypass, triage-aware selection, and startup initialization are unchanged.

**`README.md` / `docs/TG_BOT_RUNBOOK.md`**

Modified:
- Document `MAX_IMAGE_AGE_SECONDS` environment variable (default 3600).
- Document newest-first behavior: within the remaining unsent window, fresher frames are sent before older backlog frames.
- Document new `/admin` fields: stale skipped count, backlog size, latest capture time, latest sent time, last skip reason.

### 1.3 Data Flow Diagram

Image sender (newest-first + max-age filter):
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
    determine current_folder and image_base_path
              │
              ▼
    image_files = _get_image_list(folder_path)  (alphabetical ascending)
              │
              ▼
    compute start_index from LAST_SENT_IMAGE
              │
              ▼
    remaining = image_files[start_index:]
              │
              ▼
    sort remaining by mtime descending  ← NEW
              │
              ▼
    ┌─────────────────────────────────────────────┐
    │ for each filename in remaining (newest-first)│
    │ ├─ path = join(image_base_path, filename)   │
    │ ├─ os.path.getmtime(path) < now - max_age?  │
    │ │   ├─ Yes → _SKIPPED_STALE_COUNT++         │
    │ │   │        _LAST_SKIP_REASON = "stale"    │
    │ │   │        continue                       │
    │ │   └─ No  → proceed                        │
    │ ├─ similarity check / cooldown bypass       │
    │ │   ├─ skip → _LAST_SKIP_REASON = "similar" │
    │ │   │         _SKIPPED_DUPLICATE_COUNT++    │
    │ │   └─ send → send_photo()                  │
    │ │             _SENT_COUNT++                 │
    │ │             sent_count++                  │
    │ │             cap reached? → break          │
    │ └─ non-kept counted in bulk before loop     │
    │     (sets _LAST_SKIP_REASON = "non-kept")   │
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
    read output/triage_summary.json (or live_output fallback)
         │
         ▼
    _format_admin_message() → includes new counters/timestamps
         │
         ▼
    reply_text(text, Markdown)
         │
         ▼
    _get_latest_image_path() → reply_photo (existing behavior)
```

### 1.4 Interfaces

**New environment variable (optional):**
- `MAX_IMAGE_AGE_SECONDS` — maximum age in seconds for an image to be considered fresh enough to send. Default: `3600` (1 hour).

**No new Python package dependencies.**

**File system interfaces (unchanged):**
- `output/` directory mounted as Docker volume (already configured).
- `output/YYYY-MM-DD/` dated subfolders created by `snapshot_triage.py`.
- `output/.last_sent_file` state file (format unchanged).
- `output/triage_summary.json` read-only dependency (schema unchanged).

**Telegram API interfaces:** Unchanged.

---

## 2. Implementation Approach

### 2.1 Recommended: Additive changes to `tg_bot/bot.py`

Make five narrowly scoped, additive changes. No refactor of command handlers, Docker state logic, or startup initialization.

**Change A — Environment variable and new counters:**

1. Add near existing module constants:
   ```python
   MAX_IMAGE_AGE_SECONDS = int(os.getenv("MAX_IMAGE_AGE_SECONDS", "3600"))
   ```
2. Add module-level counters:
   ```python
   _SKIPPED_STALE_COUNT = 0
   _LAST_SKIP_REASON = ""
   ```

Rationale: Keeping the env var near existing `MAX_IMAGES_PER_ITERATION` and `SEND_COOLDOWN_SECONDS` follows the established convention. `_LAST_SKIP_REASON` is a single string to minimize state; operators only need the most recent reason.

**Change B — Newest-first sub-list sort:**

Inside `_send_new_images_iteration()`, after computing `start_index`:

```python
remaining = image_files[start_index:]
remaining.sort(
    key=lambda f: os.path.getmtime(os.path.join(image_base_path, f)),
    reverse=True,
)
```

Then iterate `for filename in remaining:` instead of `for filename in image_files[start_index:]:`.

Rationale: The ascending-sorted `image_files` list is still used for `start_index` lookup so the `LAST_SENT_IMAGE` cursor remains stable. Only the remaining unsent sub-list is re-sorted by mtime descending. This ensures fresh arrivals that sort after the cursor in ascending order are still found correctly, because the cursor is anchored to the full ascending list.

**Change C — Max-age staleness filter:**

Inside the send loop, before the similarity check:

```python
now = time.time()
for filename in remaining:
    path = os.path.join(image_base_path, filename)
    if not os.path.isfile(path):
        continue
    if os.path.getmtime(path) < now - MAX_IMAGE_AGE_SECONDS:
        logger.info(f"Skipped {filename} (older than {MAX_IMAGE_AGE_SECONDS}s)")
        _SKIPPED_STALE_COUNT += 1
        _LAST_SKIP_REASON = "stale"
        continue
    ...
```

Rationale: The filter is evaluated per candidate after the newest-first sort, so the freshest files are checked first. Stale files are skipped silently with a log line, preserving the existing skip/counter pattern.

**Change D — Track last skip reason for similarity and non-kept skips:**

1. In the similarity skip branch (inside `_send_new_images_iteration`):
   ```python
   _SKIPPED_DUPLICATE_COUNT += 1
   _LAST_SKIP_REASON = "similar"
   continue
   ```
2. In the non-kept bulk counting block (already existing):
   ```python
   for f in all_files:
       if f not in kept_set:
           _SKIPPED_NON_KEPT_COUNT += 1
           _LAST_SKIP_REASON = "non-kept"
   ```

Rationale: `_LAST_SKIP_REASON` gives operators immediate visibility into why the most recent frame was not sent. Setting it in all skip paths keeps the behavior consistent.

**Change E — Extend `_format_admin_message()`:**

Append the following lines before the final return:

```python
# Backlog size: unsent images after the cursor in the current folder
backlog_size = len(image_files) - start_index

# Latest capture time from the most recent image in the latest dated folder
latest_capture_path = _get_latest_image_path()
latest_capture_str = "Unknown"
if latest_capture_path:
    latest_capture_dt = datetime.fromtimestamp(
        os.path.getmtime(latest_capture_path),
        pytz.timezone("Asia/Tashkent"),
    ).isoformat(timespec="seconds")
    latest_capture_str = latest_capture_dt

# Latest sent time
latest_sent_str = "Never"
if _LAST_SENT_TIMESTAMP:
    latest_sent_dt = datetime.fromtimestamp(
        _LAST_SENT_TIMESTAMP,
        pytz.timezone("Asia/Tashkent"),
    ).isoformat(timespec="seconds")
    latest_sent_str = latest_sent_dt

lines.extend([
    "",
    f"*Skipped (stale):* {_SKIPPED_STALE_COUNT}",
    f"*Backlog size:* {backlog_size}",
    f"*Latest capture:* {latest_capture_str}",
    f"*Latest sent:* {latest_sent_str}",
    f"*Last skip reason:* {_LAST_SKIP_REASON or '—'}",
])
```

Rationale: All new fields are derived from existing state or existing helpers (`_get_latest_image_path`). No new file I/O patterns are introduced. Tashkent timezone is used for consistency with existing logging and `_summarize_live_output()`.

**Change F — Focused unit tests:**

Add a new test class `TgBotFreshFirstTests` covering newest-first ordering, max-age filter, default/custom/invalid env var, and `/admin` extended fields. Add a new test class `TgBotFreshFirstCompatibilityTests` verifying that existing cursor behavior, concurrency guard, send cap, cooldown bypass, triage-aware selection, and startup initialization are unchanged.

### 2.2 Alternative: Replace ascending sort entirely with descending-mtime sort

Sort `image_files` by mtime descending from the start, and use a set-based or dictionary-based cursor instead of `index()` in a list.

**Pros**: Simpler mental model (one sort order).
**Cons**: Requires changing the cursor persistence format (`.last_sent_file`) and the `start_index` lookup logic. The current contract relies on stable alphabetical ordering for `LAST_SENT_IMAGE` index lookup. Changing this risks breaking backward compatibility with existing `.last_sent_file` states and complicates the cursor alignment when new files arrive.

**Verdict**: Rejected. The two-phase sort (ascending for cursor, descending for send) preserves cursor stability with minimal code change.

### 2.3 Alternative: Skip stale files at the folder level instead of per-image

If the entire folder is older than `MAX_IMAGE_AGE_SECONDS`, skip the whole folder.

**Pros**: Faster; no per-image stat calls.
**Cons**: Too coarse — a folder may contain both fresh and stale images (e.g., after a camera outage). The scope requires per-image filtering.

**Verdict**: Rejected. Per-image filtering matches the scope and is necessary for mixed-age folders.

### 2.4 Alternative: Use filename timestamp parsing instead of mtime

Parse the timestamp embedded in filenames like `frame_2026-06-19 23:59:54.jpg`.

**Pros**: Immune to clock skew or `touch` operations.
**Cons**: Fragile — depends on a strict filename format that may change; requires parsing logic not present in the codebase. The project already uses `mtime` for freshness in `_get_latest_image_path()` and `_summarize_live_output()`.

**Verdict**: Rejected. Reusing `mtime` is consistent with existing code and avoids adding filename-parsing logic.

### 2.5 Alternative: Persistent counters and skip-reason history

Write `_SKIPPED_STALE_COUNT` and a history of skip reasons to a JSON or text file on disk.

**Pros**: Survives restart; richer operator history.
**Cons**: Adds file I/O on every skip; requires new file contract design; scope explicitly excludes persistent statistics.

**Verdict**: Rejected. In-memory counters and a single string are sufficient for the first increment.

---

## 3. Key Tradeoffs

### 3.1 Cursor Stability vs. Freshness Priority

| Approach | Pros | Cons |
|----------|------|------|
| Ascending for cursor, then descending mtime for send (recommended) | Stable `LAST_SENT_IMAGE` index lookup; fresh frames sent first; minimal code change | Two sorts per iteration (negligible for small folders) |
| Full descending-mtime sort with set cursor | Single sort order | Breaks existing `.last_sent_file` contract; requires cursor redesign |
| Keep ascending order only | No code change | Fresh frames stuck behind backlog |

**Decision**: Two-phase sort.

### 3.2 Freshness Proxy

| Approach | Pros | Cons |
|----------|------|------|
| `mtime` (recommended) | Already used in `_get_latest_image_path()` and `_summarize_live_output()`; no new parsing logic | Vulnerable to clock skew or accidental `touch` |
| Filename timestamp parsing | Immune to `mtime` tampering | Fragile; requires strict filename format |

**Decision**: `mtime`.

### 3.3 Counter Persistence

| Approach | Pros | Cons |
|----------|------|------|
| In-memory (recommended) | Zero file I/O; simple; fast | Reset on restart |
| JSON/text file persistence | Survives restart | File I/O on every skip; new contract; out of scope |

**Decision**: In-memory.

### 3.4 Last-Skip-Reason Granularity

| Approach | Pros | Cons |
|----------|------|------|
| Single string (recommended) | Minimal state; enough for operator visibility | Only the most recent reason is shown |
| Per-iteration dict or list | Richer history | More state; more complex `/admin` formatting; overkill for scope |

**Decision**: Single string `_LAST_SKIP_REASON`.

### 3.5 Default Max-Age Value

| Approach | Pros | Cons |
|----------|------|------|
| 3600 seconds (1 hour, recommended) | Reasonable for street-camera content with ~1–5 minute intervals; gives room for temporary downtime | May be too long for high-frequency cameras; too short for very sparse cameras |
| 600 seconds (10 minutes) | More aggressive freshness | May skip legitimate frames during minor slowdowns |
| No default (require explicit env var) | Forces operator decision | Adds setup friction |

**Decision**: Default 3600, configurable via `MAX_IMAGE_AGE_SECONDS`.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `python-telegram-bot==20.6` | Used by `tg_bot/bot.py` | Command handlers, JobQueue | None — unchanged |
| `asyncio`, `time`, `os` | stdlib, already used | Lock, epoch time, file stat | None |
| `_get_latest_image_path()` | Already implemented and QA-tested | Latest capture time for `/admin` | Low — existing helper with OSError handling |
| `_get_image_list()` | Already implemented | Image list for sender | None |
| `output/` volume mount | Already in `docker-compose.yml` | File access for images and state | None |
| `pytz` | Already used | Timezone formatting in `/admin` | None |

No new Python package dependencies.
No new container infrastructure changes.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Overlapping working-tree changes in `tg_bot/bot.py` with pending Telegram delivery TASK-003/004/005 increments (repeated-static fix in `review_required`) | Medium | This design touches only `_send_new_images_iteration()` send loop and `_format_admin_message()`; no changes to command handlers, concurrency/cooldown logic, startup initialization, or triage-aware selection. Coordinate merge order: accept prior `tg_bot` increments before implementing this design. |
| Clock skew or backdated files misorder images in newest-first sort | Low | The project already relies on `mtime` for `_get_latest_image_path()` and `_summarize_live_output()`; this design does not introduce new time-based dependencies. |
| Very high `MAX_IMAGE_AGE_SECONDS` may not suppress enough stale files; very low value may suppress legitimate frames | Low | The threshold is configurable via env var; operators can tune based on observed camera interval and traffic patterns. |
| In-memory counters and `_LAST_SKIP_REASON` reset on restart | Low | Acceptable for a first increment; persistent statistics can be added in a future increment. |
| Newest-first re-sort could theoretically place a newly arrived file before the cursor if `mtime` is older than the cursor file | Low | The cursor is computed on the full ascending list before re-sorting, so new arrivals are always after `start_index`. The descending sort only reorders within `remaining`, never dropping items. |
| Scope overlap with pending fresh-first scope review | Low | The scope doc (`docs/TELEGRAM_FRESH_FIRST_SCOPE.md`) is already in `review_required`; this design implements exactly that scope with no expansion. |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `tg_bot/bot.py` | Modify | Add `MAX_IMAGE_AGE_SECONDS`, `_SKIPPED_STALE_COUNT`, `_LAST_SKIP_REASON`; modify `_send_new_images_iteration()` for newest-first sub-list sort and max-age filter; modify `_format_admin_message()` for new counters/timestamps |
| `tests/test_tg_bot.py` | Modify | Add focused tests for newest-first ordering, max-age filter, env var handling, `/admin` extended fields, and backward compatibility |
| `README.md` | Modify | Document `MAX_IMAGE_AGE_SECONDS`, newest-first behavior, and new `/admin` fields |
| `docs/TG_BOT_RUNBOOK.md` | Modify | Document `MAX_IMAGE_AGE_SECONDS`, newest-first behavior, and new `/admin` fields |
| `tg_bot/requirements.txt` | No change | No new dependencies |
| `docker-compose.yml` | No change | Explicitly excluded by scope |
| `cams_grabber/snapshot_triage.py` | No change | Explicitly excluded by scope |
| `web_viewer/app.py` | No change | Explicitly excluded by scope |

---

## 7. Validation Plan

1. `python3 -m py_compile tg_bot/bot.py tests/test_tg_bot.py` — syntax check on modified Python files.
2. Run new unit tests: `python3 -m unittest -v tests.test_tg_bot.TgBotFreshFirstTests` — verify newest-first ordering, max-age filter, and `/admin` extended fields.
3. Run existing test suites: `python3 -m unittest -v tests/test_tg_bot.py`, `python3 -m unittest -v tests/test_snapshot_triage.py`, `python3 -m unittest -v tests/test_web_viewer.py` — ensure no regression.
4. Manual smoke test (local or container):
   - Populate `output/2026-06-19/` with 5 images of varying mtimes, including one older than 1 hour.
   - Remove `.last_sent_file` or position cursor before the batch.
   - Start bot; verify log shows fresher files sent before older ones.
   - Verify the stale file is skipped with a log line and `_SKIPPED_STALE_COUNT` increments.
   - Send `/admin` from authorized chat → verify text summary includes `Skipped (stale): 1`, `Backlog size: N`, `Latest capture: <timestamp>`, `Latest sent: <timestamp>`, and `Last skip reason: stale`.
   - Set `MAX_IMAGE_AGE_SECONDS=0` → verify all remaining files are skipped as stale.
   - Set `MAX_IMAGE_AGE_SECONDS=999999` → verify no files are skipped for staleness.
5. Inspect final Git diff to confirm only `tg_bot/bot.py`, `tests/test_tg_bot.py`, `README.md`, and `docs/TG_BOT_RUNBOOK.md` are changed.
