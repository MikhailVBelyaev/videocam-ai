# TASK-002 Design: Fix Production Telegram Image Delivery — Bot Sends Repeated Static/Latest

Job ID: 2026-06-19_163018_videocam-ai-fix-production-telegram-image-delivery-bot-sends-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `tg_bot/bot.py` | Telegram bot sending camera frames and handling `/admin`/`/state` | **Primary** — adds triage-aware image selection, configurable perceptual-hash threshold, send statistics counters, and `/admin` statistics display |
| `cams_grabber/snapshot_triage.py` | Local-folder image triage producing JSON/CSV + `kept/` subfolder | **None** — no source changes; `kept/` subfolder and `triage_summary.json` are consumed read-only |
| `web_viewer/app.py` | Flask web server serving `output/` on port 8082 | None |
| `sys_monitor/monitor.py` | System health monitoring | None |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None |

### 1.2 Module-Level Changes

**`tg_bot/bot.py`**

Current sender flow (lines 468–536):

```
JobQueue runs image_sender_job every 5s
  └─ asyncio.Lock guard (skip if already running)
       └─ asyncio.to_thread(_send_new_images_iteration)
            └─ scan output/ dated folders
            └─ list ALL image files in current folder (kept + rejected)
            └─ for each file after LAST_SENT_IMAGE:
                 ├─ are_images_similar(LAST_SENT_IMAGE, path, threshold=5)
                 │    ├─ similar + cooldown not expired → skip
                 │    ├─ similar + cooldown expired   → send (repeated static!)
                 │    └─ not similar                  → send
                 └─ cap at MAX_IMAGES_PER_ITERATION (5)
```

New sender flow:

```
JobQueue runs image_sender_job every 5s
  └─ asyncio.Lock guard (skip if already running)
       └─ asyncio.to_thread(_send_new_images_iteration)
            └─ scan output/ dated folders
            └─ _kept_images_exist(current_folder)?
                 ├─ Yes → list only images in kept/ subfolder
                 │        skip images NOT in kept/ → _SKIPPED_NON_KEPT_COUNT
                 └─ No  → list all images in current folder (backward compat)
            └─ for each file after LAST_SENT_IMAGE:
                 ├─ are_images_similar(LAST_SENT_IMAGE, path, threshold=IMAGE_SIMILARITY_THRESHOLD)
                 │    ├─ similar + cooldown not expired → skip → _SKIPPED_DUPLICATE_COUNT
                 │    ├─ similar + cooldown expired   → send (fewer with higher threshold)
                 │    └─ not similar                  → send
                 └─ cap at MAX_IMAGES_PER_ITERATION (5)
            └─ sent → _SENT_COUNT
```

New/changed functions and variables in `tg_bot/bot.py`:

| Symbol | Change | Description |
|--------|--------|-------------|
| `IMAGE_SIMILARITY_THRESHOLD` | Add | `int(os.getenv("IMAGE_SIMILARITY_THRESHOLD", "10"))` — replaces hardcoded `threshold=5` in `are_images_similar()` calls |
| `_SENT_COUNT` | Add | Module-level `int` counter: total images successfully sent since startup |
| `_SKIPPED_DUPLICATE_COUNT` | Add | Module-level `int` counter: images skipped due to perceptual-hash similarity (cooldown not expired) |
| `_SKIPPED_NON_KEPT_COUNT` | Add | Module-level `int` counter: images skipped because they were not in the `kept/` subfolder |
| `_kept_images_exist(folder_path)` | Add | Returns `True` if `folder_path/kept/` exists and contains at least one image file; `False` otherwise |
| `_get_image_list(folder_path)` | Add | Returns sorted list of image filenames; uses `kept/` subfolder when available, falls back to folder root |
| `_send_new_images_iteration()` | Modify | Uses `_get_image_list()` instead of bare `os.listdir()`; increments `_SKIPPED_NON_KEPT_COUNT` for non-kept skips; increments `_SKIPPED_DUPLICATE_COUNT` for similarity skips; increments `_SENT_COUNT` per successful send; passes `IMAGE_SIMILARITY_THRESHOLD` to `are_images_similar()` |
| `are_images_similar()` | Modify | Default `threshold` parameter remains for backward compat, but the sender now passes `IMAGE_SIMILARITY_THRESHOLD` explicitly |
| `_format_admin_message()` | Modify | Appends `Sent: N`, `Skipped (similar): N`, `Skipped (non-kept): N` lines when counters are non-zero or always (see tradeoff 3.2) |

**`tests/test_tg_bot.py`**

New tests to add (focused, no broad refactor):

- `_kept_images_exist` helper: returns `True` when `kept/` exists with image files; returns `False` when `kept/` does not exist or is empty or has no image files; `OSError` handling
- `_get_image_list` helper: returns `kept/` filenames when `kept/` exists and has images; falls back to folder root when `kept/` absent or empty; handles `OSError`
- `_send_new_images_iteration` preferring kept images: when `kept/` exists, only iterates over kept images; counts non-kept skips
- `_send_new_images_iteration` fallback: when `kept/` does not exist, iterates over all images as before
- Send statistics counters: `_SENT_COUNT` increments on successful send; `_SKIPPED_DUPLICATE_COUNT` increments on similarity skip; `_SKIPPED_NON_KEPT_COUNT` increments when image is not in `kept/`
- `/admin` output: includes `Sent:`, `Skipped (similar):`, `Skipped (non-kept):` lines
- Threshold from env var: `IMAGE_SIMILARITY_THRESHOLD` env var controls the threshold; default is 10

**`README.md`** / **`docs/TG_BOT_RUNBOOK.md`**

Modified:
- Document `IMAGE_SIMILARITY_THRESHOLD` environment variable (optional, default 10)
- Document triage-aware image selection behavior (prefer `kept/`, fallback to all)
- Document send statistics in `/admin` output
- Document that higher threshold reduces repeated static frames

### 1.3 Data Flow Diagram

Image sender (triage-aware with counters):

```
JobQueue tick (every 5s)
       │
       ▼
image_sender_job(context)
       │
       ▼
  _SENDER_LOCK locked?
    ├─ Yes → skip
    └─ No  → acquire lock
              │
              ▼
    asyncio.to_thread(_send_new_images_iteration)
              │
              ▼
    scan output/ for dated subfolders
              │
              ▼
    _kept_images_exist(current_folder)?
      ├─ Yes → _get_image_list returns kept/ filenames
      │        for each file in folder NOT in kept/:
      │          _SKIPPED_NON_KEPT_COUNT += 1
      └─ No  → _get_image_list returns all filenames
              │
              ▼
    iterate unsent images in selected list
              │
              ▼
    ┌────────────────────────────────────────────────────┐
    │ are_images_similar(LAST_SENT_IMAGE, path,          │
    │                    threshold=IMAGE_SIMILARITY_THRESHOLD)? │
    │ ├─ Yes + cooldown not expired → skip                │
    │ │   _SKIPPED_DUPLICATE_COUNT += 1                  │
    │ ├─ Yes + cooldown expired    → send                │
    │ └─ No                        → send                │
    │     ├─ send_photo(path) success                    │
    │     │   _SENT_COUNT += 1                           │
    │     │   cap reached? → break                      │
    │     └─ send failure → next                        │
    └────────────────────────────────────────────────────┘
              │
              ▼
    cleanup_old_folders()
              │
              ▼
    release lock
```

`/admin` command (extended with statistics):

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
    read output/triage_summary.json (or _summarize_live_output)
         │
         ▼
    _format_admin_message(summary, run_date, fresh)
         │  ← NEW: append Sent/Skipped (similar)/Skipped (non-kept) lines
         ▼
    reply_text(text, Markdown)
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

**New environment variable (optional):**
- `IMAGE_SIMILARITY_THRESHOLD` — perceptual-hash distance threshold for `are_images_similar()`. Default: `10` (was hardcoded `5`). Higher values suppress more near-identical frames.

**Existing environment variables (unchanged):**
- `MAX_IMAGES_PER_ITERATION` (default 5) — unchanged
- `SEND_COOLDOWN_SECONDS` (default 300) — unchanged
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID` — unchanged

**File system interfaces (extended):**
- `output/YYYY-MM-DD/kept/` — **new read path**: when this subfolder exists and contains image files, the sender iterates only over these files instead of the date folder root. This is the primary mechanism for triage-aware selection.
- `output/triage_summary.json` — existing read dependency (schema unchanged, used only by `/admin`).
- `output/.last_sent_file` — existing state file (format unchanged).

**No new Python package dependencies.**
**No changes to Docker infrastructure.**

---

## 2. Implementation Approach

### 2.1 Recommended: Additive changes to existing `tg_bot/bot.py`

Make five narrowly scoped, additive changes. No refactor of existing command handlers, Docker state logic, or `/state` command.

**Change A — Configurable perceptual-hash threshold:**

1. Add module-level constant:
   ```python
   IMAGE_SIMILARITY_THRESHOLD = int(os.getenv("IMAGE_SIMILARITY_THRESHOLD", "10"))
   ```
2. Modify `are_images_similar()` call site in `_send_new_images_iteration()`:
   ```python
   # Before:
   if LAST_SENT_IMAGE is not None and are_images_similar(LAST_SENT_IMAGE, path):
   # After:
   if LAST_SENT_IMAGE is not None and are_images_similar(LAST_SENT_IMAGE, path, threshold=IMAGE_SIMILARITY_THRESHOLD):
   ```
3. Keep the default `threshold` parameter of `are_images_similar()` at `5` for backward compatibility so existing tests that call it without specifying `threshold` continue to pass. New code in the sender explicitly passes `IMAGE_SIMILARITY_THRESHOLD`.

Rationale: Raising the threshold from 5 to 10 directly reduces the number of near-identical static/parked-car frames that bypass the similarity check. The cooldown bypass still works, but with a higher threshold, fewer frames will be classified as "different enough" to warrant a send, so cooldown-forced sends will also be less frequent for static scenes.

**Change B — Triage-aware image selection helpers:**

1. Add `_kept_images_exist(folder_path: str) -> bool`:
   ```python
   def _kept_images_exist(folder_path: str) -> bool:
       """Return True if the kept/ subfolder exists and contains at least one image file."""
       kept_path = os.path.join(folder_path, "kept")
       if not os.path.isdir(kept_path):
           return False
       try:
           for f in os.listdir(kept_path):
               if f.lower().endswith(IMAGE_EXTENSIONS) and not f.startswith("."):
                   return True
       except OSError:
           return False
       return False
   ```

2. Add `_get_image_list(folder_path: str) -> list[str]`:
   ```python
   def _get_image_list(folder_path: str) -> list[str]:
       """Return sorted image filenames. Prefer kept/ subfolder when it exists."""
       if _kept_images_exist(folder_path):
           kept_path = os.path.join(folder_path, "kept")
           try:
               files = [
                   f for f in os.listdir(kept_path)
                   if f.lower().endswith(IMAGE_EXTENSIONS)
                   and not f.startswith(".")
                   and os.path.isfile(os.path.join(kept_path, f))
               ]
               return sorted(files)
           except OSError:
               pass

       # Fallback: all images in the date folder root
       try:
           files = [
               f for f in os.listdir(folder_path)
               if f.lower().endswith(IMAGE_EXTENSIONS)
               and not f.startswith(".")
               and os.path.isfile(os.path.join(folder_path, f))
           ]
           return sorted(files)
       except OSError:
           return []
   ```

3. Modify `_send_new_images_iteration()` to use `_get_image_list()` instead of bare `os.listdir()`:
   ```python
   # Replace the block that lists image files (lines 500-507):
   #   for file in os.listdir(folder_path):
   #       if file.startswith('.'):
   #           continue
   #       if not file.lower().endswith(('.jpg', '.jpeg', '.png')):
   #           continue
   #       image_files.append(file)
   #   image_files.sort()
   # With:
   is_kept_mode = _kept_images_exist(folder_path)
   image_files = _get_image_list(folder_path)
   ```

4. Add non-kept skip counting when in `kept/` mode — after determining `is_kept_mode`, iterate the date folder root to count files skipped because they are not in `kept/`:
   ```python
   global _SKIPPED_NON_KEPT_COUNT
   if is_kept_mode:
       try:
           all_files = [
               f for f in os.listdir(folder_path)
               if f.lower().endswith(IMAGE_EXTENSIONS)
               and not f.startswith(".")
               and os.path.isfile(os.path.join(folder_path, f))
           ]
           kept_set = set(image_files)  # image_files already contains kept/ filenames
           for f in all_files:
               if f not in kept_set:
                   _SKIPPED_NON_KEPT_COUNT += 1
       except OSError:
           pass
   ```

   Note: The non-kept skip counting happens once per iteration, not per image. It counts how many root-folder images exist that are not in `kept/`.

   Alternative: compute `all_files` only for counting, not for iteration. This avoids the overhead of listing the root when `kept/` is available, but the root listing is needed to compute the skip count. Since `_send_new_images_iteration()` already runs at most once per 5 seconds and the directories are small (daily folders with hundreds of frames at most), the extra `os.listdir` call is negligible.

Rationale: When `kept/` exists and contains images, the sender only considers triage-approved frames. This eliminates sending frames already rejected by the quality pipeline. The `kept/` check is a directory existence check plus a file count — inexpensive. The fallback to all images ensures backward compatibility when triage has not run or the `kept/` folder is empty.

**Change C — Send statistics counters:**

1. Add module-level counters initialized to 0:
   ```python
   _SENT_COUNT = 0
   _SKIPPED_DUPLICATE_COUNT = 0
   _SKIPPED_NON_KEPT_COUNT = 0
   ```

2. Increment `_SENT_COUNT` in `send_photo()` on success (after the existing `LAST_SENT_IMAGE`/`LAST_SENT_FOLDER` updates):
   ```python
   global _SENT_COUNT
   _SENT_COUNT += 1
   ```

3. Increment `_SKIPPED_DUPLICATE_COUNT` in `_send_new_images_iteration()` when skipping a similar image (cooldown not expired):
   ```python
   global _SKIPPED_DUPLICATE_COUNT
   _SKIPPED_DUPLICATE_COUNT += 1
   logger.info(f"Skipped {filename} (too similar to last sent image)")
   continue
   ```

4. Increment `_SKIPPED_NON_KEPT_COUNT` as shown in Change B above.

5. All three counters reset to 0 on process restart (in-memory only, matching the scope exclusion of persistent statistics).

Rationale: In-memory counters are the simplest implementation. They give operators immediate visibility into how the sender is filtering images, which directly diagnoses the "bot sends repeated static/latest" problem. If counters show high `_SKIPPED_DUPLICATE_COUNT` and low `_SENT_COUNT`, the threshold is working. If `_SKIPPED_NON_KEPT_COUNT` is high, triage is filtering effectively.

**Change D — `/admin` statistics display:**

1. Modify `_format_admin_message()` to append send statistics:
   ```python
   # After existing line building, add:
   lines.extend([
       "",
       f"*Sent:* {_SENT_COUNT}",
       f"*Skipped (similar):* {_SKIPPED_DUPLICATE_COUNT}",
       f"*Skipped (non-kept):* {_SKIPPED_NON_KEPT_COUNT}",
   ])
   ```

2. The statistics are always shown (not conditional on value) so operators can see at a glance whether the sender has been active and whether filtering is working. Zero counters indicate a fresh start or no image flow.

Rationale: Always showing counters provides a quick health check. Conditional display would hide the fact that the bot has not sent any images since startup.

**Change E — Threshold in `are_images_similar()` call:**

Already covered in Change A. The `are_images_similar()` function signature (`threshold=5` default) is unchanged; the sender passes `threshold=IMAGE_SIMILARITY_THRESHOLD` (default 10) at the call site.

### 2.2 Alternative: Use `triage_summary.json` `kept_frames` list instead of `kept/` subfolder

Instead of checking for the `kept/` subfolder, read `triage_summary.json` and filter images by the `kept_frames` filename list.

**Pros**: Does not require the `--kept-dir` flag to be configured in the triage pipeline. Works whenever `triage_summary.json` is written (which is always).
**Cons**: Couples the sender to the `triage_summary.json` schema. The JSON may not be written yet when the sender ticks (triage may be running on a different schedule). Requires JSON parsing on every sender tick.
**Verdict**: Rejected. The `kept/` subfolder approach is simpler (directory existence check + file listing) and aligns with the project convention of `kept/` as a well-known output directory. The fallback behavior (all images when `kept/` is absent) handles the same edge case (triage not yet run) without JSON parsing.

### 2.3 Alternative: Filter images by `triage_summary.json` `kept_frames` filenames AND `kept/` subfolder

Check both the `kept/` subfolder existence and `triage_summary.json` to build the intersection.

**Pros**: Extra safety — ensures only frames that are both in `kept/` and listed in the JSON are sent.
**Cons**: Over-engineered for the stated problem. If `kept/` exists and has files, that is sufficient evidence that triage produced them. The JSON may be stale or not yet written.
**Verdict**: Rejected. The `kept/` subfolder alone is the correct signal.

### 2.4 Alternative: Persistent statistics in `.last_sent_file` or separate file

Store `_SENT_COUNT`, `_SKIPPED_DUPLICATE_COUNT`, and `_SKIPPED_NON_KEPT_COUNT` across restarts.

**Pros**: Survives container restart; operators can see lifetime totals.
**Cons**: Requires file format change or separate file. The scope explicitly excludes persistent statistics. In-memory counters are sufficient for diagnosing the "repeated static/latest" problem.
**Verdict**: Rejected per scope exclusions. Can be added in a future increment if needed.

### 2.5 Alternative: Set `IMAGE_SIMILARITY_THRESHOLD` per-iteration based on `kept_frames` count

Dynamically adjust the threshold based on how many kept frames are available.

**Pros**: Adapts to scene activity.
**Cons**: Adds complexity and unpredictability. Operators expect a consistent, tunable threshold. Dynamic adjustment makes debugging harder.
**Verdict**: Rejected. A fixed, configurable threshold is simpler, debuggable, and matches the scope.

---

## 3. Key Tradeoffs

### 3.1 Image Source: `kept/` Subfolder vs. All Images

| Approach | Pros | Cons |
|----------|------|------|
| Prefer `kept/` when available (recommended) | Eliminates rejected/low-quality frames from delivery; aligns with triage pipeline output; simple directory check | If `kept/` is empty or stale (triage not yet run), falls back to all images, which may include rejected frames in that brief window |
| Always use all images, filter by `triage_summary.json` | No dependency on `--kept-dir` flag being configured | Requires JSON parse every tick; schema coupling; JSON may not exist when sender ticks |
| Always use all images, no filtering (current behavior) | Simple; no dependency on triage output | Continues to send rejected/low-quality frames (the root cause of the bug) |

**Decision**: Prefer `kept/` subfolder when available, fall back to all images when absent. This is the smallest change that directly addresses the "bot sends rejected frames" failure mode.

### 3.2 `/admin` Statistics Display: Always Show vs. Conditional

| Approach | Pros | Cons |
|----------|------|------|
| Always show counters (recommended) | Operators can immediately see if sender has been active and how filtering is working; zero counters are meaningful (fresh start) | Adds 3 lines to every `/admin` response |
| Show only when counters > 0 | Shorter response in steady state | Hides "no activity since restart" signal; requires conditional formatting logic |

**Decision**: Always show counters. Three extra lines is minimal overhead, and zero counters are a useful signal that the sender has not sent any images since startup.

### 3.3 Perceptual-Hash Threshold: Default 10 vs. Default 5

| Approach | Pros | Cons |
|----------|------|------|
| Default 10 (recommended) | Directly reduces static-scene flooding; more frames suppressed as near-identical; operators can lower if too aggressive | May suppress genuine scene changes that are close in appearance but actually different |
| Default 5 (current) | Backward compatible | Does not fix the bug; static scenes still produce near-identical frames that differ by hash distance 6–9 |
| Default 15 | Even fewer static frames | Higher risk of suppressing genuine changes |

**Decision**: Default 10. This matches the scope document recommendation. The threshold is configurable via `IMAGE_SIMILARITY_THRESHOLD` env var. Street camera content typically produces perceptual-hash distances of 0–3 for truly static scenes and 15+ for genuine activity changes, so 10 is a reasonable middle ground that suppresses static while allowing real events through. The cooldown bypass (every 300s) still delivers one frame from a static scene, so operators can verify the camera is alive.

### 3.4 Non-Kept Counting: Full Directory Scan vs. Count-Only

| Approach | Pros | Cons |
|----------|------|------|
| Count all root-folder images not in `kept/` set (recommended) | Accurate `_SKIPPED_NON_KEPT_COUNT` for operator visibility | Extra `os.listdir()` call per iteration (negligible for small daily folders) |
| Estimate from `triage_summary.json` `total_images - kept_images` | No extra directory scan | Requires JSON parse; may be stale; more coupling |
| Skip counting, just skip silently | No extra overhead | Operators lose visibility into how many frames are being filtered |

**Decision**: Count with `os.listdir()` when `kept/` exists. The overhead is negligible (hundreds of entries at most, once per 5 seconds).

### 3.5 Counter Increment Location: `send_photo()` vs. `_send_new_images_iteration()`

| Approach | Pros | Cons |
|----------|------|------|
| `_SENT_COUNT` in `send_photo()` (recommended) | Counts every successful send, including `/admin` test sends if any are added later | Single point of truth for "images sent" |
| `_SENT_COUNT` in `_send_new_images_iteration()` | Only counts background sender sends | Misses any future send path |

**Decision**: `_SENT_COUNT` in `send_photo()`. This provides a single counter for all successful sends. `_SKIPPED_DUPLICATE_COUNT` and `_SKIPPED_NON_KEPT_COUNT` stay in `_send_new_images_iteration()` because those skips only happen in the background sender loop.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `imagehash` | Used by `are_images_similar()` | Threshold parameter change | None — existing function, only call-site change |
| `os.path`, `os.listdir` | stdlib, already used | `kept/` directory checks | None |
| `IMAGE_SIMILARITY_THRESHOLD` env var | New | Configurable threshold | Low — env var with sensible default (10) |
| `kept/` subfolder | Created by `snapshot_triage.py` when `--kept-dir` is provided | Triage-aware selection | Medium — requires production deployment to pass `--kept-dir` flag. Fallback to all images when `kept/` absent mitigates this. |
| `triage_summary.json` schema | Stable (TASK-003/004/005) | `/admin` text (already consumed) | None — no schema changes |

No new Python package dependencies.
No container infrastructure changes.
No triage pipeline source changes.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| `kept/` folder missing or empty in production (triage not configured or behind) | Medium | Fallback to all images in dated folder when `kept/` is absent or empty. No data loss, only a temporary reversion to current behavior. Operators should configure `--kept-dir` in the triage pipeline for full effect. |
| Higher threshold (10) may suppress genuine scene changes | Medium | Threshold is configurable via `IMAGE_SIMILARITY_THRESHOLD` env var. Operators can tune it. The 300-second cooldown bypass ensures at least one frame per 5 minutes from a static scene, providing a "keep-alive" signal. |
| `kept/` folder lag: triage runs less frequently than sender ticks | Low | Sender sees `kept/` contents as of the last triage run. New frames not yet in `kept/` are not sent until triage catches up. This is by design — it prevents sending untriaged frames. Fallback to all images only occurs when `kept/` is completely absent. |
| Counters reset on bot restart | Low | Accepted per scope — in-memory statistics are sufficient for diagnosing the immediate problem. Persistent counters can be added in a future increment. |
| Scope overlap with pending reviews in `tg_bot/bot.py` | Medium | Prior TASK-003/004/005 increments are in `review_required`. Implementation should be rebased on accepted state to avoid merge conflicts. The design only touches image-sending logic and `/admin` display, not `/state` or other command handlers. |
| Extra `os.listdir()` call for non-kept counting | Negligible | Small daily folders (hundreds of entries) listed once per 5-second tick. Impact is sub-millisecond on typical hardware. |
| `_get_image_list()` changes iteration semantics when `kept/` subfolder exists | Low | When `kept/` exists and is non-empty, `LAST_SENT_IMAGE` resolution and `start_index` computation still work because filenames in `kept/` are a subset of root filenames (same basenames). The `LAST_SENT_IMAGE` path will need to be compared by basename, not full path, since the kept image is in `kept/` but `LAST_SENT_IMAGE` may point to the root or `kept/` subfolder. |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `tg_bot/bot.py` | Modify | Add `IMAGE_SIMILARITY_THRESHOLD`, `_SENT_COUNT`, `_SKIPPED_DUPLICATE_COUNT`, `_SKIPPED_NON_KEPT_COUNT`; add `_kept_images_exist()` and `_get_image_list()` helpers; modify `_send_new_images_iteration()` for triage-aware selection and counter increments; modify `are_images_similar()` call to pass `IMAGE_SIMILARITY_THRESHOLD`; modify `_format_admin_message()` to include statistics; increment `_SENT_COUNT` in `send_photo()` |
| `tests/test_tg_bot.py` | Modify | Add focused tests for `_kept_images_exist()`, `_get_image_list()`, triage-aware selection, fallback behavior, counter increments, `/admin` statistics display, and `IMAGE_SIMILARITY_THRESHOLD` env var |
| `README.md` | Modify | Document `IMAGE_SIMILARITY_THRESHOLD` env var, triage-aware image selection behavior, send statistics in `/admin`, and updated threshold default |
| `docs/TG_BOT_RUNBOOK.md` | Modify | Document `IMAGE_SIMILARITY_THRESHOLD` env var, triage-aware selection behavior, send statistics counters, and updated threshold default |
| `cams_grabber/snapshot_triage.py` | No change | Explicitly excluded by scope |
| `web_viewer/app.py` | No change | Explicitly excluded by scope |
| `docker-compose.yml` | No change | Explicitly excluded by scope |

---

## 7. Validation Plan

1. `python3 -m py_compile tg_bot/bot.py tests/test_tg_bot.py` — syntax check on modified Python files.
2. Run new unit tests: `python3 -m unittest -v tests/test_tg_bot.py` — verify `_kept_images_exist()`, `_get_image_list()`, triage-aware selection, fallback, counter increments, `/admin` statistics, and `IMAGE_SIMILARITY_THRESHOLD`.
3. Run existing test suites: `python3 -m unittest -v tests/test_snapshot_triage.py` and `python3 -m unittest -v tests/test_web_viewer.py` — ensure no regression.
4. Manual smoke test:
   - Create `output/2026-06-20/kept/` with 3 image files and `output/2026-06-20/` root with 5 files (3 in `kept/` + 2 rejected).
   - Verify sender iterates only the 3 kept files; `_SKIPPED_NON_KEPT_COUNT = 2`.
   - Remove `kept/` folder; verify sender falls back to all 5 files; `_SKIPPED_NON_KEPT_COUNT` unchanged.
   - Verify similar images within `IMAGE_SIMILARITY_THRESHOLD=10` are skipped; `_SKIPPED_DUPLICATE_COUNT` increments.
   - Verify `/admin` shows all 3 counter lines.
   - Set `IMAGE_SIMILARITY_THRESHOLD=5`; verify more frames pass the similarity check (backward compat).
5. Inspect final Git diff to confirm only `tg_bot/bot.py`, `tests/test_tg_bot.py`, `README.md`, and `docs/TG_BOT_RUNBOOK.md` are changed.