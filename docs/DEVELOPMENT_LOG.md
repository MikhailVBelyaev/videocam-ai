# Development Log

## 2026-06-22 (2) — GStreamer NVDEC reader (no ffmpeg subprocess)

### Replace ffmpeg pipe with GStreamer in-process pipeline

**Problem:** After switching to ffmpeg+NVDEC in the previous session, the ffmpeg subprocess
consumed ~24% CPU on top of Python's 172% = ~196% total. The subprocess IPC and Unix pipe
(6 MB BGR at 15fps = 90 MB/s through the kernel pipe) ate most of the CPU savings from NVDEC.

**Solution:** GStreamer Python pipeline running entirely in-process via `gi.repository.Gst`.

Pipeline: `rtspsrc (TCP) → rtph264depay → h264parse → nvh264dec → cudadownload → appsink`

- `nvh264dec` decodes H.264 on GPU via NVDEC (same GPU savings as before)
- `cudadownload` moves frames from CUDA memory to system RAM (3 MB NV12 per frame)
- `appsink.emit('try-pull-sample', Gst.SECOND)` delivers NV12 buffers directly in Python
- `cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)` converts to BGR on CPU (~1 ms/frame)
- No subprocess, no Unix pipe — eliminates the ~24% CPU from IPC overhead

**Dockerfile:** Replaced `ffmpeg` apt package with GStreamer packages:
`gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad`
`gstreamer1.0-tools python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0`

**Stream dimensions:** No longer probed at startup — discovered from first frame's caps:
`caps.get_structure(0).get_int('width')` / `.get_int('height')`.

**Error/reconnect:** `try-pull-sample` with 1-second timeout; bus ERROR/EOS triggers
pipeline NULL + reconnect with exponential backoff (1s → 30s).

**Expected result:** ~196% total CPU → ~165-175% (save ~24% from removing ffmpeg process).

---

## 2026-06-22 — Multi-camera + GPU pipeline + CPU reduction

### Multi-camera output layout

Changed output structure from `output/YYYY-MM-DD/` to `output/<camera_id>/YYYY-MM-DD/`.
`cams_grabber/main_ssh.py`: `get_daily_output_dir()` now prepends `CAMERA_ID` env var (default `cam1`).
`frame_for_web.jpg` path also uses camera subdir.

All consumers (tg_bot, web_viewer, qa_service) updated to discover cameras dynamically
by scanning `output/` for non-date subdirs. Zero code changes needed to activate cam2/cam3.

`docker-compose.yml`: service renamed `cams_grabber` → `cams_grabber_cam1`; cam2/cam3 added
with `profiles: ["cam2"]`/`["cam3"]` so they only start when explicitly activated.

### GPU assignment fix

Old: `CUDA_VISIBLE_DEVICES=1` and `CUDA_VISIBLE_DEVICES=2` in docker-compose.
Problem: `CUDA_VISIBLE_DEVICES` uses CUDA internal device ordering, which does not
match `nvidia-smi` PCI bus order. Both ML containers were landing on GPU 0 (the display GPU).

Fix: switched to `NVIDIA_VISIBLE_DEVICES=1`/`2` (Docker NVIDIA runtime env var, uses PCI bus
order matching `nvidia-smi`). Kept `CUDA_DEVICE_ORDER=PCI_BUS_ID` as a belt-and-suspenders
guard for code inside the container.

### H.264 decode moved to GPU (NVDEC)

Previous reader thread: `cv2.VideoCapture` with OpenCV's built-in FFmpeg backend (CPU software decode).

New reader thread: `subprocess.Popen(['ffmpeg', '-hwaccel', 'cuda', '-c:v', 'h264_cuvid', ...])`
piping raw bgr24 frames. `h264_cuvid` = NVDEC hardware decoder; all H.264 entropy decode and
motion compensation run on GPU 1's NVDEC unit.

Required `NVIDIA_DRIVER_CAPABILITIES=video,compute,utility` in docker-compose — without `video`,
the container toolkit does not inject `libnvcuvid.so.1` and NVDEC is unavailable.

Stream dimensions probed once at startup via `ffprobe` (fallback: 1920×1080).

### Frame quality checks moved to PyTorch CUDA

Previous: `cv2.Laplacian` + `np.gradient` (then optimised to `cv2.Sobel`) — all CPU.

New: three 3×3 CUDA convolution kernels (Laplacian, Sobel-X, Sobel-Y) allocated on
`cuda:0` after YOLO loads. Each frame is uploaded once (`torch.from_numpy(frame).cuda().float()`)
and blur variance, gradient magnitude variance, and brightness computed entirely on GPU.

Key fix: `.cuda().float()` not `.float().cuda()` — the wrong order allocated a 24 MB
float32 tensor on CPU before transfer (4× PCIe waste).

### CPU throttle + pre-roll reduction

Added `INFERENCE_FPS_MAX = 8` rate cap to main loop (was ~15fps free-running).
Reduced `PREROLL_FRAMES` 45→24 (still 3s at 8fps), `RECORD_FPS` 12→8.

### Results

| Metric | Before | After |
|---|---|---|
| cams_grabber CPU | ~273% | ~172% |
| GPU 1 utilization | 9% | 51% |
| GPU 1 VRAM | 490 MB | ~540 MB |
| H.264 decode | CPU | NVDEC (GPU 1) |
| Quality checks | CPU | CUDA (GPU 1) |

### tg_bot `/state` hardware stats

`sys_monitor/monitor.py`: writes `.sysinfo.json` to `output/` each monitoring cycle.
JSON includes CPU %, CPU temp, RAM, disk, per-GPU stats, UPS state.

`tg_bot/bot.py`: `/state` command reads `.sysinfo.json` and appends hardware report
after container status table.

---

## 2026-06-21 — Capture quality fixes + QA service

### Root cause analysis and capture fixes

Analysed two production problems using Opus 4.8:
- **Problem 1 (garbage frames):** single-threaded capture loop caused FIFO buffer lag —
  frames processed by YOLO were already stale (sometimes seconds old). Fixed with a
  dedicated reader thread storing only the latest frame in a single-slot buffer.
- **Problem 2 (composite/blended frames):** H.264 inter-frame corruption from UDP RTSP
  packet loss. Fixed by switching RTSP transport to TCP.

Changes in `cams_grabber/main_ssh.py`:
- Reader daemon thread: continuous `cap.read()`, single-slot `_latest_slot` with lock
- RTSP opened with `OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp` and `CAP_PROP_BUFFERSIZE=1`
- Exponential backoff reconnect on stream loss: 1 s → 30 s cap
- Pre-YOLO quality gate: Laplacian variance ≥ 30 AND gradient magnitude variance ≥ 5
- Production model upgraded from yolov8n → yolov8s (more accurate, downloaded at build time)
- Persistence requirement: 4 consecutive frames before saving (`MIN_PERSIST_FRAMES = 4`)
- Cooldown renamed from frames to seconds (`COOLDOWN_SECONDS = 20`)
- Save raw frame as primary + YOLO-annotated `_debug.jpg` as separate file

### QA service

New `qa_service/` Docker service:
- `qa_service/qa.py`: watcher thread + Flask SPA, GPU 2 (`CUDA_VISIBLE_DEVICES=2`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`)
- `qa_service/Dockerfile`: nvidia/cuda:11.8.0 base, torch 2.2.2+cu118, numpy<2 pin
- `qa_service/requirements.txt`: flask, ultralytics, opencv-python, numpy<2, imagehash, Pillow
- Added to `docker-compose.yml` on port 8083

Per-frame analysis:
- Blur (Laplacian), gradient (gradient magnitude), brightness (mean grayscale)
- Per-tracking-ID perceptual hash (imagehash) to detect stationary recaptures vs. genuine movement
- YOLOv8n re-detection at conf ≥ 0.35 to independently verify object presence
- PASS / WARN / FAIL classification

Dashboard: two-tab SPA
- Dashboard tab: 5 time-window cards (10 min / 1 h / 6 h / 12 h / 24 h) + stats table
- Gallery tab: 5 images/page, prev/next, jump-to-page, lightbox, auto-refresh page 1

Issues fixed during deployment:
- `numpy<2` pin added (numpy 2.2.6 + torch 2.2.2+cu118 → `_ARRAY_API not found`)
- Per-ID hash tracking (was global, causing all stationary vehicles to FAIL as "duplicates")
- FAIL logic: only quality problems are FAIL; stationary vehicles are WARN (expected)
- Stale container conflict on rebuild: `docker rm -f qa_service` before recreate

### Documentation

- `CLAUDE.md` created: full project guidance for Claude Code sessions
- `docs/ARCHITECTURE.md` created: system overview, service breakdown, GPU assignments, frame lifecycle
- `docs/QA_SERVICE_RUNBOOK.md` created: dashboard guide, status meanings, troubleshooting
- `docs/PROJECT_STATUS_MEMORY.md` updated to 2026-06-21
- `docs/NEXT_ACTIONS.md` updated with future improvement ideas

## 2026-06-19 (Docs)

- Completed TASK-005 documentation for "Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first"
  (Job ID: 2026-06-19_190332_videocam-ai-fix-tg-bot-still-stuck-on-old-last-sent-folder-a-task-005).
  - Updated `docs/TG_BOT_RUNBOOK.md` validation counts: 132 → 139 tg_bot tests, 212 → 219 total tests.
  - Verified `README.md` Telegram bot section consistency with `tg_bot/bot.py` implementation:
    folder advancement behavior, stuck-state `/admin` fields (Watched folder, Newest folder,
    State file, Status), boundary guard, and troubleshooting entries are accurate.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/DEVELOPMENT_LOG.md`, and `docs/PROJECT_MANAGER.yaml`.
  - No source code changes. All 219 tests pass (139 tg_bot + 52 snapshot_triage + 28 web_viewer).
  - `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Implementation)

- Completed TASK-003 implementation for "Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first"
  (Job ID: 2026-06-19_190332_videocam-ai-fix-tg-bot-still-stuck-on-old-last-sent-folder-a-task-003).
  - Modified `tg_bot/bot.py`:
    - Added folder advancement block in `_send_new_images_iteration()`: when `sent_count == 0`
      and current folder is not the latest dated folder, advance `LAST_SENT_FOLDER` to the next
      folder, clear `LAST_SENT_IMAGE` to `None`, and persist state via `.last_sent_file`
      (`new_folder/\n` format).
    - Added latest-folder boundary guard: when current folder is already the newest, stay put.
    - Extended `_format_admin_message()` with stuck-state visibility fields:
      `Watched folder`, `Newest folder`, `State file`, `Status` (`✅ Fresh` or `⚠️ Stuck on <folder>`).
  - Added 8 focused tests in `tests/test_tg_bot.py` (`TgBotFolderAdvanceTests`):
    - `test_old_folder_all_stale_advances`
    - `test_old_folder_all_similar_advances`
    - `test_old_folder_fully_sent_advances`
    - `test_latest_folder_zero_sends_stays_put`
    - `test_normal_send_in_old_folder_no_advance`
    - `test_multi_folder_rapid_advancement`
    - `test_admin_stuck_state_fields`
    - `test_state_file_persistence_on_advancement`
  - Updated `README.md` with folder advancement behavior and new `/admin` fields.
  - Updated `docs/TG_BOT_RUNBOOK.md` with "Folder Advancement" section, updated `/admin`
    description, validation counts (132 tg_bot tests, 212 total), and "Bot stuck on old folder"
    troubleshooting entry.
  - All 132 tg_bot tests pass; all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
  - Total 212 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Planning)

- Completed TASK-001 scope definition for "Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first"
  (Job ID: 2026-06-19_190332_videocam-ai-fix-tg-bot-still-stuck-on-old-last-sent-folder-a-task-001).
  - Created `docs/TG_BOT_FOLDER_ADVANCE_SCOPE.md` defining minimum deliverable:
    folder advancement logic in `_send_new_images_iteration()` (advance to next
    dated folder when `sent_count == 0` and current folder is not latest),
    latest-folder boundary guard, `/admin` stuck-state visibility fields
    (watched folder, newest folder, state file content, status indicator),
    focused unit tests, and README/runbook updates.
  - Recorded measurable acceptance criteria and explicit exclusions.
  - No source code changes. All 204 tests pass. `py_compile` clean.
  - Status: `review_required`.

- Completed TASK-002 design for "Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first"
  (Job ID: 2026-06-19_190332_videocam-ai-fix-tg-bot-still-stuck-on-old-last-sent-folder-a-task-002).
  - Created `docs/TG_BOT_FOLDER_ADVANCE_DESIGN.md` documenting affected services
    (`tg_bot/bot.py` primary), modules (`_send_new_images_iteration()`, `_format_admin_message()`),
    data flows (folder advancement block after zero-send iteration), and interfaces
    (`.last_sent_file` format `folder/\n`, `/admin` extended fields).
  - Documented implementation approach: additive changes only — folder advancement
    when `sent_count == 0` and `current_folder != newest_folder`, clear
    `LAST_SENT_IMAGE`, persist via `save_last_sent_file()`, latest-folder boundary
    guard, and stuck-state visibility in `/admin`.
  - Documented key tradeoffs: `sent_count == 0` trigger vs. stale-only/unconditional
    triggers; next-folder vs. jump-to-newest step size; `folder/\n` state format
    vs. new file contract; direct read vs. reuse for `/admin` state file display.
  - No source code changes. All 204 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (QA)

- Completed TASK-004 QA validation for "Ignore old Telegram image backlog and process fresh live"
  (Job ID: 2026-06-19_172411_videocam-ai-ignore-old-telegram-image-backlog-and-process-fr-task-004).
  - Added 9 focused QA tests in `tests/test_tg_bot.py` (new class `TgBotFreshFirstQATests`):
    - `test_all_images_stale_no_sends`: All images stale → zero sends, `_SKIPPED_STALE_COUNT` increments per file, `_LAST_SKIP_REASON = "stale"`.
    - `test_mixed_staleness_preserves_newest_first_order`: 1 stale + 2 fresh → only fresh sent in newest-first order.
    - `test_similar_skip_sets_last_skip_reason`: Similarity skip sets `_LAST_SKIP_REASON = "similar"`.
    - `test_non_kept_skip_sets_last_skip_reason`: Non-kept skip sets `_LAST_SKIP_REASON = "non-kept"`.
    - `test_stale_skip_in_kept_mode`: Stale kept/ image skipped, fresh kept/ image sent; stale counter increments.
    - `test_newest_first_respects_send_cap`: With 7 fresh images and cap=5, freshest 5 sent first.
    - `test_admin_backlog_count_with_last_sent`: Backlog size counts remaining images after cursor.
    - `test_admin_fields_when_no_image_data`: `/admin` shows Unknown/Never/— when no image data available.
    - `test_getmtime_oserror_bypasses_stale_filter`: When `os.path.getmtime` raises OSError, file bypasses stale filter (fail-open behavior).
  - No source code changes required.
  - All 124 tg_bot tests pass (115 existing + 9 new); all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
  - Total 204 tests pass. `py_compile` clean.
  - Notable finding: `os.path.getmtime` OSError in staleness check results in fail-open behavior (file not filtered as stale). This is a reasonable defensive design but worth noting for operational awareness.

## 2026-06-19 (Docs)

- Completed TASK-005 documentation for "Ignore old Telegram image backlog and process fresh live"
  (Job ID: 2026-06-19_172411_videocam-ai-ignore-old-telegram-image-backlog-and-process-fr-task-005).
  - Updated `docs/TG_BOT_RUNBOOK.md`:
    - Updated validation counts: 124 tg_bot tests, 204 total tests.
    - Added troubleshooting entry for `os.path.getmtime` OSError fail-open behavior
      (file treated as not stale when modification time cannot be read).
  - Verified `README.md` Telegram bot section consistency with `tg_bot/bot.py`:
    - `MAX_IMAGE_AGE_SECONDS` env var (default 3600), newest-first processing,
      and max-age staleness filter are accurately described.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/PROJECT_MANAGER.yaml`, and `docs/DEVELOPMENT_LOG.md`.
  - No source code changes. All 124 tg_bot tests pass; all 52 snapshot triage tests pass;
    all 28 web_viewer tests pass. Total 204 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Implementation)

- Completed TASK-003 implementation for "Ignore old Telegram image backlog and process fresh live"
  (Job ID: 2026-06-19_172411_videocam-ai-ignore-old-telegram-image-backlog-and-process-fr-task-003).
  - Modified `tg_bot/bot.py`:
    - Added `MAX_IMAGE_AGE_SECONDS` env var (default 3600) with graceful fallback on invalid value.
    - Added `_SKIPPED_STALE_COUNT` and `_LAST_SKIP_REASON` module-level in-memory counters.
    - Modified `_send_new_images_iteration()` to sort remaining unsent images by `mtime`
      descending after computing stable `start_index` from the ascending-sorted list.
    - Added per-image max-age staleness filter before the similarity check; skipped stale
      images increment `_SKIPPED_STALE_COUNT` and set `_LAST_SKIP_REASON = "stale"`.
    - Set `_LAST_SKIP_REASON` for "similar" and "non-kept" skip paths as well.
    - Extended `_format_admin_message()` to append `Skipped (stale)`, `Backlog size`,
      `Latest capture`, `Latest sent`, and `Last skip reason` fields.
  - Added 12 focused tests in `tests/test_tg_bot.py` (2 new test classes):
    - `TgBotFreshFirstTests` (7 tests): newest-first ordering, max-age filter skip,
      default/custom/invalid env var, `/admin` extended fields, cursor stability.
    - `TgBotFreshFirstCompatibilityTests` (5 tests): concurrency guard, send cap,
      cooldown bypass, triage-aware selection, startup initialization unchanged.
  - Updated `README.md` with `MAX_IMAGE_AGE_SECONDS` env var, newest-first behavior,
    and new `/admin` fields.
  - Updated `docs/TG_BOT_RUNBOOK.md` with `MAX_IMAGE_AGE_SECONDS` env var,
    "Newest-First Processing" and "Max-Age Staleness Filter" sections, updated `/admin`
    description, validation counts (115 tg_bot tests, 195 total), and max-age troubleshooting entries.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/PROJECT_MANAGER.yaml`, and `docs/DEVELOPMENT_LOG.md`.
  - All 115 tg_bot tests pass; all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
  - Total 195 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Design)

- Completed TASK-002 design for "Ignore old Telegram image backlog and process fresh live"
  (Job ID: 2026-06-19_172411_videocam-ai-ignore-old-telegram-image-backlog-and-process-fr-task-002).
  - Listed affected services (`tg_bot/bot.py` primary; no changes to `cams_grabber`,
    `web_viewer`, `sys_monitor`), modules, data flows, and interfaces in
    `docs/TELEGRAM_FRESH_FIRST_DESIGN.md`.
  - Documented implementation approach: seven additive changes to `tg_bot/bot.py`:
    (A) `MAX_IMAGE_AGE_SECONDS` env var (default 3600) with graceful fallback,
    (B) `_SKIPPED_STALE_COUNT` and `_LAST_SKIP_REASON` module-level in-memory counters,
    (C) newest-first sub-list sort within `_send_new_images_iteration()`
    (stable ascending `start_index`, then `mtime`-descending `remaining` sort),
    (D) per-image max-age staleness filter inside the send loop,
    (E) skip-reason tracking for `"similar"`, `"non-kept"`, and `"stale"` skips,
    (F) extended `_format_admin_message()` with stale count, backlog size,
    latest capture time, latest sent time, and last skip reason,
    (G) focused unit tests and README/runbook updates.
  - Evaluated and rejected alternatives: full descending-mtime sort (breaks cursor
    contract), folder-level staleness skip (too coarse), filename timestamp parsing
    (fragile), and persistent counters (out of scope).
  - Documented five key tradeoffs: two-phase sort vs full descending sort, `mtime`
    vs filename parsing, in-memory vs persistent counters, single-string vs rich
    skip-reason history, and default 3600s vs other defaults.
  - Documented dependency analysis, risks, mitigations, files to change, and
    validation plan.
  - No source code changes. All 103 tg_bot tests pass; all 52 snapshot_triage tests pass.
  - `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Docs)

- Completed TASK-005 documentation for "Fix production Telegram image delivery: bot sends repeated
  static/latest"
  (Job ID: 2026-06-19_163018_videocam-ai-fix-production-telegram-image-delivery-bot-sends-task-005).
  - Updated `docs/TG_BOT_RUNBOOK.md` validation counts: 76 → 103 tg_bot tests, 156 → 183 total tests.
  - Added troubleshooting entries for `IMAGE_SIMILARITY_THRESHOLD` misconfiguration (too high sends
    similar images, too low skips all images as similar) and non-kept counter behavior (stays zero
    without `kept/` subfolder).
  - Verified `README.md` Telegram bot section consistency with `tg_bot/bot.py` implementation:
    `IMAGE_SIMILARITY_THRESHOLD` env var (default 10), triage-aware image sending, sender safeguards,
    startup behavior, send statistics in `/admin`, and `/state` command.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/DEVELOPMENT_LOG.md`, and `docs/PROJECT_MANAGER.yaml`.
  - No source code changes. All 103 tg_bot tests pass; total 183 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (QA)

- Completed TASK-004 QA validation for "Fix production Telegram image delivery: bot sends repeated static/latest"
  (Job ID: 2026-06-19_163018_videocam-ai-fix-production-telegram-image-delivery-bot-sends-task-004).
  - Added 6 focused QA tests in `tests/test_tg_bot.py` (TgBotTriageAwareQATests):
    - `test_cooldown_bypass_works_in_kept_mode`: verifies cooldown bypass still sends similar images in kept/ mode.
    - `test_non_kept_counter_stays_zero_without_kept_folder`: verifies `_SKIPPED_NON_KEPT_COUNT` does NOT increment when kept/ folder is absent (backward compatibility).
    - `test_all_kept_images_skipped_as_similar_when_cooldown_not_expired`: verifies all kept images are skipped when similar and cooldown is not expired, and `_SKIPPED_DUPLICATE_COUNT` increments exactly per image.
    - `test_oserror_during_non_kept_counting_is_swallowed`: verifies OSError during non-kept image counting does NOT prevent kept images from being sent.
    - `test_get_image_list_excludes_dotfiles_from_root`: verifies `_get_image_list` excludes dotfiles when falling back to root directory.
    - `test_send_photo_called_with_kept_subfolder_path`: verifies `send_photo` receives the correct `kept/` subfolder path, not the root date folder path.
  - All 103 tg_bot tests pass; total 183 tests pass. `py_compile` clean.
  - No source code changes required.
  - Status: `review_required`.

## 2026-06-19 (Implementation)

- Completed TASK-003 implementation for "Fix production Telegram image delivery: bot sends repeated static/latest"
  (Job ID: 2026-06-19_163018_videocam-ai-fix-production-telegram-image-delivery-bot-sends-task-003).
  - Modified `tg_bot/bot.py`:
    - Added `IMAGE_SIMILARITY_THRESHOLD` env var (default 10) replacing hardcoded threshold=5.
    - Added `_SENT_COUNT`, `_SKIPPED_DUPLICATE_COUNT`, `_SKIPPED_NON_KEPT_COUNT` module-level
      in-memory counters for send statistics.
    - Added `_kept_images_exist()` helper to check for `kept/` subfolder presence.
    - Added `_get_image_list()` helper to return `kept/` images with fallback to all images.
    - Replaced `_send_new_images_iteration()` with triage-aware version preferring `kept/`
      images and skipping similar/duplicate images using `IMAGE_SIMILARITY_THRESHOLD`.
    - Incremented `_SENT_COUNT` in `send_photo()` for send statistics.
    - Appended send statistics to `_format_admin_message()` (always visible in `/admin`).
  - Added 17 focused tests in `tests/test_tg_bot.py` (4 new test classes):
    - `TgBotKeptImageTests` (6 tests): `_kept_images_exist()` with kept/ present, absent,
      and OSError; `_get_image_list()` preferring kept/ and falling back.
    - `TgBotTriageAwareSenderTests` (3 tests): kept/ images preferred, non-kept skipped,
      similarity threshold applied.
    - `TgBotThresholdEnvTests` (3 tests): default threshold, env var override, invalid env var.
    - `TgBotSendStatisticsTests` (5 tests): counter increments, admin message includes
      statistics, zero counts on startup, statistics after multiple sends.
  - Updated `docs/TG_BOT_RUNBOOK.md` with `IMAGE_SIMILARITY_THRESHOLD` env var and
    "Triage-aware Image Sending" section.
  - Updated `README.md` with `IMAGE_SIMILARITY_THRESHOLD` env var and triage-aware paragraph.
  - Total 97 tests pass (including 17 new triage-aware tests). `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Planning)

- Completed TASK-001 scope definition for "Ignore old Telegram image backlog and process fresh live"
  (Job ID: 2026-06-19_172411_videocam-ai-ignore-old-telegram-image-backlog-and-process-fr-task-001).
  - Created `docs/TELEGRAM_FRESH_FIRST_SCOPE.md` defining minimum deliverable:
    newest-first processing of remaining unsent images (stable cursor via ascending
    start_index, then mtime-descending sub-list sort), configurable max-age staleness
    filter via `MAX_IMAGE_AGE_SECONDS` env var (default 3600), extended `/admin`
    counters and timestamps (stale skipped, backlog size, latest capture time,
    latest sent time, last skip reason), focused unit tests, and README/runbook updates.
  - Recorded measurable acceptance criteria and explicit exclusions.
  - No source code changes. All 183 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Planning)

- Completed TASK-002 design for "Fix production Telegram image delivery:
  bot sends repeated static/latest"
  (Job ID: 2026-06-19_163018_videocam-ai-fix-production-telegram-image-delivery-bot-sends-task-002).
  - Documented affected services, modules, data flows, and interfaces in
    `docs/TELEGRAM_REPEATED_STATIC_DESIGN.md`.
  - Implementation approach: five additive changes to `tg_bot/bot.py`:
    (A) configurable `IMAGE_SIMILARITY_THRESHOLD` env var (default 10) replacing
    hardcoded threshold=5, (B) triage-aware image selection via `_kept_images_exist()`
    and `_get_image_list()` helpers preferring `kept/` subfolder with fallback to
    all images, (C) send statistics counters (`_SENT_COUNT`,
    `_SKIPPED_DUPLICATE_COUNT`, `_SKIPPED_NON_KEPT_COUNT`) as module-level
    in-memory variables, (D) `/admin` display of send statistics (always shown),
    (E) explicit `threshold=IMAGE_SIMILARITY_THRESHOLD` in sender similarity call.
  - Documented five key tradeoffs: kept/ subfolder vs. JSON filter (kept/ chosen
    for simplicity), always-show vs. conditional statistics (always-show for
    visibility), threshold 10 vs. 5 (10 chosen to suppress static), full directory
    scan vs. estimate for non-kept counting (full scan for accuracy),
    send_photo vs. iteration counter for _SENT_COUNT (send_photo for single truth).
  - Documented six risks with mitigations: kept-folder missing/empty, higher threshold
    suppressing real changes, kept-folder lag, counter reset on restart, scope
    overlap with pending reviews, LAST_SENT_IMAGE path resolution with kept/.
  - Rejected alternatives: JSON-based filtering, persistent statistics, per-iteration
    dynamic threshold.
  - No source code changes. All 156 tests pass. `py_compile` clean.
  - Status: `review_required`.

- Completed TASK-001 scope definition for "Fix production Telegram image delivery:
  bot sends repeated static/latest"
  (Job ID: 2026-06-19_163018_videocam-ai-fix-production-telegram-image-delivery-bot-sends-task-001).
  - Defined minimum deliverable: triage-aware image selection (prefer `kept/`
    subfolder, skip non-kept frames), perceptual-hash threshold increase from 5
    to configurable default 10 (`IMAGE_SIMILARITY_THRESHOLD` env var), and send
    statistics counters (sent, skipped-duplicate, skipped-non-kept) in `/admin`.
  - Recorded measurable acceptance criteria and explicit exclusions in
    `docs/TELEGRAM_REPEATED_STATIC_SCOPE.md`.
  - Explicitly excluded: triage pipeline changes, staleness detection, persistent
    statistics, motion/object detection in tg_bot, web viewer changes, Docker
    infrastructure changes.
  - Documented risks: kept-folder lag (mitigated by fallback), higher threshold
    suppressing real changes (mitigated by cooldown bypass and configurable
    threshold), in-memory statistics reset on restart, scope overlap with pending
    reviews.
  - No source code changes. All 156 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Docs)

- Completed TASK-005 documentation for "Fix remaining Telegram image backlog problem"
  (Job ID: 2026-06-19_151143_videocam-ai-fix-remaining-telegram-image-backlog-problem-task-005).
  - Updated `docs/TG_BOT_RUNBOOK.md` validation counts: 76 tg_bot tests, 156 total tests.
  - Verified `README.md` Telegram bot section consistency with `tg_bot/bot.py` startup
    behavior, env vars, and sender safeguards.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/DEVELOPMENT_LOG.md`, and `docs/PROJECT_MANAGER.yaml`.
  - All 76 tg_bot tests pass; all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
  - Total 156 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (QA)

- Completed TASK-004 QA validation for "Fix remaining Telegram image backlog problem"
  (Job ID: 2026-06-19_151143_videocam-ai-fix-remaining-telegram-image-backlog-problem-task-004).
  - Added 6 focused QA tests in `tests/test_tg_bot.py` (TgBotStartupStateQATests):
    - `test_startup_multiple_dated_folders_picks_latest`: verifies `_initialize_startup_state` picks the latest dated folder, not an older one, even when older images have newer mtimes.
    - `test_startup_sets_module_globals`: verifies `_initialize_startup_state` correctly mutates `LAST_SENT_IMAGE` and `LAST_SENT_FOLDER` module globals.
    - `test_startup_preserves_last_sent_timestamp`: verifies `_initialize_startup_state` does NOT update `_LAST_SENT_TIMESTAMP` (confirming the cooldown bypass tradeoff from design doc section 3.3).
    - `test_startup_oserror_in_directory_access_returns_none`: verifies full error propagation chain from `os.listdir` OSError through `_get_latest_run_date` → `_get_latest_image_path` → `_initialize_startup_state` returns `(None, None)` without crashing and without writing a state file.
    - `test_startup_state_file_format_is_correct`: verifies the `.last_sent_file` written by `_initialize_startup_state` has the exact `folder/filename\n` format expected by `load_last_sent_file`, and that `load_last_sent_file` can read it back correctly.
    - `test_iteration_starts_after_initialized_image`: verifies that after startup initialization, `_send_new_images_iteration` starts from the image AFTER the initialized one, not from index 0 — this is the core acceptance criterion that prevents backlog drain on restart.
  - No source code changes required.
  - All 76 tg_bot tests pass; all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
  - Total 156 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Implementation)

- Completed TASK-003 implementation for "Fix remaining Telegram image backlog problem"
  (Job ID: 2026-06-19_151143_videocam-ai-fix-remaining-telegram-image-backlog-problem-task-003).
  - Modified `tg_bot/bot.py`:
    - Added `_initialize_startup_state()` helper that scans the latest dated folder
      for the most recently modified image and initializes `LAST_SENT_IMAGE` and
      `LAST_SENT_FOLDER` without sending.
    - Modified `main()` to call `_initialize_startup_state()` when `load_last_sent_file()`
      returns `(None, None)`.
    - Persisted initialized state via `save_last_sent_file()` so subsequent restarts
      skip re-initialization.
  - Added 4 focused tests in `tests/test_tg_bot.py` (TgBotStartupStateTests):
    - no-state startup with images → initialized to latest image and state file written.
    - no-state startup with empty folder → returns (None, None), no state file written.
    - no-state startup with no dated folders → returns (None, None), no state file written.
    - existing `.last_sent_file` present → `load_last_sent_file()` behavior unchanged.
  - Updated `README.md` with startup behavior note.
  - Updated `docs/TG_BOT_RUNBOOK.md` with "Startup Behavior" section, updated
    validation counts (70 tg_bot tests, 150 total), and added troubleshooting entry.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/PROJECT_MANAGER.yaml`, and `docs/DEVELOPMENT_LOG.md`.
  - All 70 tg_bot tests pass; all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
  - Total 150 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Design)

- Completed TASK-002 design for "Fix remaining Telegram image backlog problem"
  (Job ID: 2026-06-19_151143_videocam-ai-fix-remaining-telegram-image-backlog-problem-task-002).
  - Listed affected services (`tg_bot/bot.py` primary; no changes to `cams_grabber`,
    `web_viewer`, `sys_monitor`), modules, data flows, and interfaces in
    `docs/TELEGRAM_BACKLOG_DESIGN.md`.
  - Documented implementation approach: extract `_initialize_startup_state()` helper
    to scan the latest dated folder and initialize `LAST_SENT_IMAGE`/`LAST_SENT_FOLDER`
    without sending; modify `main()` to call it when `load_last_sent_file()` returns
    `(None, None)`.
  - Evaluated and rejected alternatives: inline initialization without helper,
    in-memory-only state, and manual folder scan instead of reusing `_get_latest_image_path()`.
  - Documented 3 key tradeoffs: helper extraction vs inline, state persistence on
    initialization, and timestamp implications for cooldown bypass.
  - Documented dependency analysis, risks, mitigations, files to change, and
    validation plan.
  - All 146 tests pass; no source code changes.
  - `py_compile` clean.
  - Status: `review_required`.


## 2026-06-19 (Planning)

- Completed TASK-001 scope definition for "Fix remaining Telegram image backlog problem"
  (Job ID: 2026-06-19_151143_videocam-ai-fix-remaining-telegram-image-backlog-problem-task-001).
  - Defined minimum deliverable: on startup with no `.last_sent_file`, initialize
    `LAST_SENT_IMAGE` and `LAST_SENT_FOLDER` to the most recently modified image
    in the latest dated folder without sending it, so the next iteration only
    processes newly arriving frames.
  - Recorded measurable acceptance criteria and explicit exclusions in
    `docs/TELEGRAM_BACKLOG_SCOPE.md`.
  - Documented risks: most recent image may never have been sent, clock skew may
    misorder images, and overlap with pending Telegram delivery reviews.
  - Status: `review_required`.

## 2026-06-19 (Docs)

- Completed TASK-005 documentation for "Fix production Telegram image delivery and admin statistics"
  (Job ID: 2026-06-19_140208_videocam-ai-fix-production-telegram-image-delivery-and-admin-task-005).
  - Updated `docs/TG_BOT_RUNBOOK.md` with image sender safeguards (concurrency guard,
    per-iteration send cap, cooldown bypass), `/admin` latest image file send behavior,
    new environment variables (`MAX_IMAGES_PER_ITERATION`, `SEND_COOLDOWN_SECONDS`),
    expanded troubleshooting table, and updated validation counts (66 tg_bot tests,
    146 total).
  - Verified `README.md` Telegram bot section is consistent with implementation.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/PROJECT_MANAGER.yaml`, and `docs/DEVELOPMENT_LOG.md`.
  - All 66 tg_bot tests pass; all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
  - Total 146 tests pass. `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (QA Validation)

- Completed TASK-004 QA validation for "Fix production Telegram image delivery and admin statistics"
  (Job ID: 2026-06-19_140208_videocam-ai-fix-production-telegram-image-delivery-and-admin-task-004).
  - Added 13 focused QA tests in `tests/test_tg_bot.py`, bringing total from 53 to 66 tg_bot tests:
    - `TgBotSenderTests`: sender job runs when lock is free, iteration skips similar images
      within cooldown, iteration sends all when under cap.
    - `TgBotSenderPhotoQATests`: send_photo updates _LAST_SENT_TIMESTAMP on success,
      send_photo does not update timestamp on failure.
    - `TgBotLatestImageQATests`: _get_latest_image_path returns None for no dated folders,
      empty folder, and OSError; picks most recently modified image; ignores non-image files.
    - `TgBotAdminTests`: _get_latest_run_date OSError returns None; _summarize_live_output
      returns None for no media and OSError.
  - No source code changes required.
  - All 66 tg_bot tests pass; all 146 total tests pass. `py_compile` clean.

## 2026-06-19 (Implementation)

- Completed TASK-003 implementation for "Fix production Telegram image delivery and admin statistics"
  (Job ID: 2026-06-19_140208_videocam-ai-fix-production-telegram-image-delivery-and-admin-task-003).
  - Modified `tg_bot/bot.py`:
    - Added `_SENDER_LOCK = asyncio.Lock()` module-level guard to prevent overlapping
      `image_sender_job` executions.
    - Added `_LAST_SENT_TIMESTAMP = 0.0` and `SEND_COOLDOWN_SECONDS` env var (default 300)
      for time-based duplicate bypass.
    - Added `MAX_IMAGES_PER_ITERATION` env var (default 5) for per-iteration send cap.
    - Modified `send_photo()` to update `_LAST_SENT_TIMESTAMP` on success.
    - Modified `_send_new_images_iteration()` to enforce the cap and bypass similarity
      check when the cooldown has expired.
    - Modified `image_sender_job()` to acquire the lock and skip when already locked.
    - Added `_get_latest_image_path()` to find the most recently modified image in the
      latest dated output folder.
    - Extended `admin_command()` to send the latest image file via `reply_photo` after
      the existing text summary, with graceful fallback on missing image or send failure.
  - Added 6 focused tests in `tests/test_tg_bot.py`:
    - `TgBotSenderTests`: concurrency guard skip, send cap enforcement, cooldown bypass.
    - `TgBotAdminPhotoTests`: `/admin` sends latest image, no-image fallback, image send
      failure fallback.
  - Updated `README.md` with `MAX_IMAGES_PER_ITERATION`, `SEND_COOLDOWN_SECONDS`,
    `/admin` photo behavior, and sender safeguard descriptions.
  - All 53 tg_bot tests pass; all 52 snapshot triage tests pass; all 28 web_viewer tests pass.
    Total 133 tests pass.
  - `py_compile` clean on `tg_bot/bot.py` and `tests/test_tg_bot.py`.
  - Status: `review_required`.

## 2026-06-19 (Design)

- Completed TASK-002 design for "Fix production Telegram image delivery and admin statistics"
  (Job ID: 2026-06-19_140208_videocam-ai-fix-production-telegram-image-delivery-and-admin-task-002).
  - Listed affected services (`tg_bot/bot.py` primary; no changes to `cams_grabber`,
    `web_viewer`, `sys_monitor`), modules, data flows, and interfaces in
    `docs/TELEGRAM_IMAGE_DELIVERY_DESIGN.md`.
  - Documented implementation approach: additive changes to `tg_bot/bot.py`
    — `asyncio.Lock` concurrency guard for `image_sender_job`, per-iteration send
    cap (`MAX_IMAGES_PER_ITERATION`, default 5), time-based duplicate bypass cooldown
    (`SEND_COOLDOWN_SECONDS`, default 300), and `/admin` sending the latest image
    file alongside the existing text summary.
  - Evaluated and rejected alternatives: `threading.Lock` inside sync function,
    persistent cooldown timestamp in `.last_sent_file`, cooldown flag timer,
    bypass-for-entire-iteration.
  - Documented 5 key tradeoffs: concurrency guard placement, send cap boundary,
    cooldown time source, `/admin` image send method, and bypass scope.
  - Documented dependency analysis, risks, mitigations, files to change, and
    validation plan.
  - All 127 tests pass; no source code changes.
  - `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Planning)

- Completed TASK-001 scope definition for "Fix production Telegram image delivery and admin statistics"
  (Job ID: 2026-06-19_140208_videocam-ai-fix-production-telegram-image-delivery-and-admin-task-001).
  - Defined minimum deliverable: concurrency guard and per-iteration send cap for
    `image_sender_job`, time-based duplicate bypass cooldown, and `/admin` command
    sending the actual latest image file alongside the existing text summary.
  - Recorded measurable acceptance criteria and explicit exclusions in
    `docs/TELEGRAM_IMAGE_DELIVERY_SCOPE.md`.
  - Documented risks: cooldown may send unwanted similar frames, cap may delay
    high-activity bursts, large file upload limits, and overlap with pending
    `/admin`/`/state` review items.
  - Status: `review_required`.

## 2026-06-19 (Docs)

- Completed TASK-005 documentation for "Change /admin: add web server page with cars and"
  (Job ID: 2026-06-19_060847_videocam-ai-change-admin-add-web-server-page-with-cars-and-task-005).
  - Verified `README.md` web viewer section against `web_viewer/app.py` implementation.
  - Created `docs/WEB_VIEWER_RUNBOOK.md` with `/admin` endpoint behavior, static file
    serving, configuration, local development steps, Docker Compose operating steps,
    validation commands, and troubleshooting table.
  - Added `docs/WEB_VIEWER_RUNBOOK.md` reference to `README.md` runbook list.
  - Verified `docker-compose.yml` service definition, volume mount, port mapping,
    and healthcheck are accurately documented.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/PROJECT_MANAGER.yaml`, and `docs/DEVELOPMENT_LOG.md`.
  - All 28 web_viewer tests pass; all 47 tg_bot tests pass; all 52 snapshot triage tests pass.
  - `py_compile` clean on `web_viewer/app.py` and `tests/test_web_viewer.py`.
  - Status: `review_required`.

## 2026-06-19 (Design)

- Completed TASK-002 design for "Change /admin: add web server page with cars and"
  (Job ID: 2026-06-19_060847_videocam-ai-change-admin-add-web-server-page-with-cars-and-task-002).
  - Listed affected services (`web_viewer` primary; no changes to `tg_bot`,
    `cams_grabber`, `sys_monitor`), modules, data flows, and interfaces in
    `docs/WEB_ADMIN_PAGE_DESIGN.md`.
  - Documented implementation approach: Flask replacing nginx, with `/admin` HTML
    route and catch-all static file route preserving existing URLs.
  - Evaluated and rejected alternatives: FastAPI, nginx+sidecar, stdlib http.server.
  - Documented 5 key tradeoffs: web framework choice, nginx replacement vs
    augmentation, HTML rendering approach, static file serving approach, and
    error handling for missing data.
  - Documented dependency analysis, risks, mitigations, files to change, and
    validation plan.
  - All 47 tg_bot tests pass; all 52 snapshot triage tests pass.
  - `py_compile` clean.
  - Status: `review_required`.

## 2026-06-19 (Implementation)

- Completed TASK-003 implementation for "Change /admin: add web server page with cars and"
  (Job ID: 2026-06-19_060847_videocam-ai-change-admin-add-web-server-page-with-cars-and-task-003).
  - Replaced `nginx:alpine` `web_viewer` with a minimal Flask Python web server.
  - Created `web_viewer/Dockerfile` based on `python:3.12-slim`.
  - Created `web_viewer/requirements.txt` with `flask` and `pytz`.
  - Created `web_viewer/app.py` with `/admin` HTML route and catch-all static file route.
    - `_read_latest_summary()`: reads `output/triage_summary.json`, returns parsed dict or None.
    - `_get_latest_run_date()`: finds most recent `YYYY-MM-DD` folder in `output/`.
    - `_is_fresh()`: returns True if run date is within last 24h.
    - `_get_latest_image_links()`: lists latest image files in latest folder for HTML links.
    - `_render_admin_page()`: builds inline HTML with stats and image links.
    - `admin_page()`: Flask route handler for `/admin`.
    - `serve_static()`: Flask route handler preserving existing static file URLs.
  - Updated `docker-compose.yml`:
    - Replaced `image: nginx:alpine` with `build: ./web_viewer`.
    - Updated volume mount to `./output:/app/output:ro`.
    - Mapped host port `8082` to container port `5000`.
    - Added HTTP healthcheck for `/admin`.
  - Created `tests/test_web_viewer.py` with 14 focused tests covering:
    - `/admin` HTML contains total_images, kept_images, car_count, person_count.
    - `/admin` with missing JSON renders error message (HTTP 200).
    - `/admin` with malformed JSON renders error message (HTTP 200).
    - Static file serving returns correct content and mimetype.
    - Default counts to 0 when `total_objects_by_type` keys absent.
    - Missing expected objects count displayed correctly.
    - `_get_latest_run_date` empty dir and non-date dir filtering.
    - `_is_fresh` within 24h, stale, and None inputs.
    - `_read_latest_summary` missing file returns None.
    - `_render_admin_page` produces expected HTML structure.
  - All 14 web_viewer tests pass; all 47 tg_bot tests pass; all 52 snapshot triage tests pass.
  - `py_compile` clean on `web_viewer/app.py` and `tests/test_web_viewer.py`.
  - Updated `README.md` with new web viewer section documenting `/admin` behavior, URL,
    stats displayed, error handling, static file preservation, and container recreate step.
  - Status: `review_required`.

## 2026-06-19 (Planning)

- Completed TASK-001 scope definition for "Change /admin: add web server page with cars and"
  (Job ID: 2026-06-19_060847_videocam-ai-change-admin-add-web-server-page-with-cars-and-task-001).
  - Defined minimum deliverable: replace nginx `web_viewer` with a minimal Python
    web server that serves static files from `output/` and adds an `/admin` HTML
    page showing triage statistics (total images, kept images, car/person counts,
    missing expected objects), latest run date, freshness indicator, and links to
    latest images.
  - Recorded measurable acceptance criteria and explicit exclusions in
    `docs/WEB_ADMIN_PAGE_SCOPE.md`.
  - Explicitly excluded container status display, video player, authentication,
    real-time updates, REST API, and changes to Telegram bot or triage pipeline.
  - Documented risks: performance vs nginx, JSON schema dependency, required
    container recreate after compose change, and new service maintenance burden.
  - Status: `review_required`.

## 2026-06-19 (Docs)

- Completed TASK-005 documentation for "add to command /state info about running containers"
  (Job ID: 2026-06-19_104909_videocam-ai-add-to-command-state-info-about-running-containe-task-005).
  - Verified `README.md` Telegram bot section against `tg_bot/bot.py` implementation.
  - Created `docs/TG_BOT_RUNBOOK.md` with `/admin` and `/state` command behavior,
    environment variables, Docker socket setup, local and Docker Compose operating
    steps, validation commands, and troubleshooting table.
  - Verified security notes are present: read-only socket mount, no container control
    commands, admin-chat restriction for both commands.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`,
    `docs/PROJECT_MANAGER.yaml`, and `docs/DEVELOPMENT_LOG.md`.
  - All 47 tg_bot tests pass; all 52 snapshot triage tests pass.
  - `py_compile` clean on `tg_bot/bot.py` and `tests/test_tg_bot.py`.
  - Status: `review_required`.

## 2026-06-19 (QA)

- Completed TASK-004 QA validation for the `/state` command
  (Job ID: 2026-06-19_104909_videocam-ai-add-to-command-state-info-about-running-containe-task-004).
  - Added 8 focused QA tests in `tests/test_tg_bot.py` covering:
    - `_query_container_states` returns None when `DockerException` is raised on `from_env()`
    - `_query_container_states` returns proper dict structure (name, status, health, started_at)
    - `_query_container_states` handles mixed found and not-found containers
    - `_query_container_states` calls `client.close()` on success path
    - `_query_container_states` defaults health to "N/A" when no Health key in attrs
    - `_format_uptime` truncates Docker nanosecond fractional seconds to microseconds
    - `_format_uptime` returns minutes-only for uptimes between 60s and 1h
    - `_format_state_message` emoji mapping (running=✅, exited=❌, not-found=❌, restarting=⚠️, dead=⚠️)
  - All 47 tg_bot tests pass; all 52 snapshot triage tests pass.
  - `py_compile` clean on `tg_bot/bot.py` and `tests/test_tg_bot.py`.
  - No source code changes required; all tests validate existing behavior.
  - Status: `review_required`.

## 2026-06-19 (Implementation)

- Completed TASK-003 implementation for "add to command /state info about running containers"
  (Job ID: 2026-06-19_104909_videocam-ai-add-to-command-state-info-about-running-containe-task-003).
  - Added `docker` package to `tg_bot/requirements.txt`.
  - Added read-only Docker socket mount `/var/run/docker.sock:/var/run/docker.sock:ro`
    to `tg_bot` service in `docker-compose.yml`.
  - Implemented `/state` command in `tg_bot/bot.py`:
    - `EXPECTED_CONTAINERS` constant with the four compose service names.
    - `_query_container_states()`: queries Docker daemon via Docker SDK; returns
      list of state dicts or `None` when runtime is unavailable.
    - `_format_uptime()`: human-readable duration from ISO 8601 `StartedAt`.
    - `_format_state_message()`: composes single-page Markdown summary with
      status emoji, container name, status, health, and uptime.
    - `state_command()`: admin-restricted async handler; silent ignore for non-admin
      chats; graceful "Container runtime unavailable" error when socket is absent.
    - Registered `CommandHandler("state", state_command)` in `main()`.
  - Added 12 focused tests in `tests/test_tg_bot.py` covering:
    - `_format_state_message` with all statuses (running, exited, not-found, restarting)
    - `_format_state_message` uptime inclusion and N/A fallback
    - `_format_uptime` seconds, hours/minutes, days, None, and malformed inputs
    - `_query_container_states` returns None when docker import failed
    - `state_command` non-admin silent return
    - `state_command` admin runtime-unavailable error reply
    - `state_command` admin with mocked states returns Markdown reply
  - Updated `README.md` with `/state` command behavior, Docker socket requirement,
    and container recreate step.
  - All 39 tg_bot tests pass; all 52 snapshot triage tests pass.
  - `py_compile` clean on `tg_bot/bot.py` and `tests/test_tg_bot.py`.
  - Status: `review_required`.

## 2026-06-19 (Design)

- Completed TASK-002 design for "add to command /state info about running containers"
  (Job ID: 2026-06-19_104909_videocam-ai-add-to-command-state-info-about-running-containe-task-002).
  - Documented affected services (`tg_bot/bot.py` primary; Docker Engine runtime dependency;
    `cams_grabber`, `sys_monitor`, `web_viewer` read-only), modules, data flows, and
    interfaces in `docs/STATE_COMMAND_DESIGN.md`.
  - Recommended Docker SDK for Python (`docker` package) with read-only Docker socket mount
    as the implementation approach; rejected subprocess CLI, direct HTTP, and file-based
    alternatives with rationale.
  - Documented 5 key tradeoffs: container runtime access method, Docker socket security,
    admin authorization reuse, uptime representation, and error handling strategy.
  - Validation plan covers syntax checks, new unit tests for formatting/auth/errors,
    existing triage test suite regression check, and manual smoke tests with/without
    socket mount and with stopped containers.
  - Status: `review_required`.

## 2026-06-19 (QA)

- Completed TASK-004 QA validation for "Change /admin: add web server page with cars and"
  (Job ID: 2026-06-19_060847_videocam-ai-change-admin-add-web-server-page-with-cars-and-task-004).
  - Added 14 focused QA tests in `tests/test_web_viewer.py` (WebViewerQAValidationTests class)
    covering error paths, boundary conditions, and edge cases in the web viewer /admin page:
    - `_read_latest_summary`: OSError (permission denied) returns None
    - `_get_latest_run_date`: OSError during listdir returns None; single date dir returned correctly
    - `_get_latest_image_links`: caps at 5 images; filters by .jpg/.jpeg/.png extensions;
      ignores subdirectories; OSError during listing returns empty list
    - `_is_fresh`: invalid date string returns False
    - `_render_admin_page`: None summary shows error with zeroed counts; no links shows "No images found";
      fresh=False shows "Stale"; non-car/person object types (truck, bicycle) are not rendered
    - Static file serving: 404 for non-existent file
    - Integration: no date dirs and no summary renders error message with "Unknown"
  - All 28 web_viewer tests pass (14 original + 14 new).
  - All 127 total tests pass (52 snapshot_triage + 47 tg_bot + 28 web_viewer).
  - `py_compile` clean on `web_viewer/app.py` and `tests/test_web_viewer.py`.
  - No source code changes required; all tests validate existing behavior.
  - Status: `review_required`.

## 2026-06-19 (Planning)

- Completed TASK-001 scope definition for "add to command /state info about running containers"
  (Job ID: 2026-06-19_104909_videocam-ai-add-to-command-state-info-about-running-containe-task-001).
  - Defined minimum deliverable: `/state` command in `tg_bot/bot.py` that returns
    a single-page summary of the four expected containers (`cams_grabber`, `tg_bot`,
    `sys_monitor`, `web_viewer`) with running/exited/not-found state and health status.
  - Recorded measurable acceptance criteria and explicit exclusions in
    `docs/STATE_COMMAND_SCOPE.md`.
  - Documented risks: Docker socket security, missing Docker CLI/library in container,
    custom deployment name mismatches, and required container recreate after compose change.
  - Status: `review_required`.

## 2026-06-18 (Docs)

- Completed TASK-005 documentation for "add to tg service /admin command and show 1"
  (Job ID: 2026-06-18_115153_videocam-ai-add-to-tg-service-admin-command-and-show-1-task-005).
  - Verified `README.md` Telegram bot section against implemented behavior in `tg_bot/bot.py`.
  - Added operating steps: local install from `tg_bot/requirements.txt`, Docker Compose start,
    and background polling interval (5 seconds).
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`, and `docs/PROJECT_MANAGER.yaml`
    to reflect TASK-005 completion.
  - Ran `.venv/bin/python -m py_compile tg_bot/bot.py tests/test_tg_bot.py` (clean).
  - Ran `.venv/bin/python -m unittest -v tests/test_tg_bot.py` (23 tests, pass).
  - Ran `.venv/bin/python -m unittest -v tests/test_snapshot_triage.py` (52 tests, pass).
  - Status: `review_required`.

## 2026-06-18 (QA)

- Completed TASK-004 QA validation for the Telegram /admin command
  (Job ID: 2026-06-18_115153_videocam-ai-add-to-tg-service-admin-command-and-show-1-task-004).
  - Added 11 focused QA tests in `tests/test_tg_bot.py` covering:
    - `_format_admin_message`: empty missing_expected_objects list, missing total_objects_by_type key
    - `_is_fresh`: today-is-fresh, two-days-ago-is-stale, invalid date string
    - `_get_latest_run_date`: empty output directory
    - `_read_latest_summary`: OSError (permission denied)
    - `_is_admin_chat`: string-vs-int type coercion
    - `admin_command`: non-admin silent return, admin no-data reply, admin with-data Markdown reply
  - All 23 tg_bot tests pass; all 52 snapshot triage tests pass.
  - `py_compile` clean on `tg_bot/bot.py` and `tests/test_tg_bot.py`.
  - No source code changes required; all tests validate existing behavior.
  - Fixed initial test edge-case bugs: async mock for `reply_text`, boundary-correct
    `_is_fresh` assertions (date-at-midnight boundary).
  - Status: `review_required`.

## 2026-06-18 (Implementation)

- Completed TASK-003 implementation for "add to tg service /admin command and show 1"
  (Job ID: 2026-06-18_115153_videocam-ai-add-to-tg-service-admin-command-and-show-1-task-003).
  - Refactored `tg_bot/bot.py` from raw `requests` polling to `python-telegram-bot`
    Application with JobQueue.
  - Added `/admin` CommandHandler restricted to `TELEGRAM_ADMIN_CHAT_ID`
    (falls back to `TELEGRAM_CHAT_ID`).
  - Added helper functions: `_is_admin_chat()`, `_read_latest_summary()`,
    `_get_latest_run_date()`, `_is_fresh()`, `_format_admin_message()`.
  - `/admin` composes a single Markdown message from `output/triage_summary.json`
    with latest run date, freshness indicator, total/kept counts, car/person counts,
    and missing-expected-objects count.
  - Non-admin chats are silently ignored; missing or malformed JSON yields
    "No triage data available."
  - Existing image-sending behavior preserved as a background job
    (`image_sender_job` → `_send_new_images_iteration` via `asyncio.to_thread`).
  - Created `tests/test_tg_bot.py` with 12 focused unit tests covering:
    - `_format_admin_message` with all fields and with defaults
    - `_is_admin_chat` matching and non-matching IDs
    - `_read_latest_summary` success, missing file, malformed JSON
    - `_get_latest_run_date` max date selection and no valid folders
    - `_is_fresh` within 24h, stale, and None
  - All 12 new tests pass; all 52 existing snapshot triage tests pass.
  - `py_compile` clean on `tg_bot/bot.py` and `tests/test_tg_bot.py`.
  - Updated `README.md` with Telegram bot section documenting env vars and `/admin`.
  - Added `tg_bot/__init__.py` to make the package importable for tests.
  - Status: `review_required`.

## 2026-06-18 (Design)

- Completed TASK-002 design for "add to tg service /admin command and show 1"
  (Job ID: 2026-06-18_115153_videocam-ai-add-to-tg-service-admin-command-and-show-1-task-002).
  - Documented affected services (`tg_bot/bot.py` primary; `snapshot_triage.py` read-only consumer),
    modules, data flows, and interfaces in `docs/TG_ADMIN_COMMAND_DESIGN.md`.
  - Recommended `python-telegram-bot` Application with JobQueue as the implementation
    architecture; rejected raw-requests and hybrid-threading alternatives.
  - Documented 4 key tradeoffs: command handling library, admin authorization model,
    data freshness strategy, and message formatting.
  - Validation plan covers syntax checks, new unit tests for formatting/auth/errors,
    existing triage test suite regression check, and manual smoke tests.
  - Status: `review_required`.

## 2026-06-18 (Planning)

- Completed TASK-001 scope definition for "add to tg service /admin command and show 1"
  (Job ID: 2026-06-18_115153_videocam-ai-add-to-tg-service-admin-command-and-show-1-task-001).
  - Defined minimum deliverable: `/admin` command in `tg_bot/bot.py` that returns
    a single-page summary with latest triage stats (total images, kept images,
    car/person counts), freshness indicator, and admin-chat restriction.
  - Recorded measurable acceptance criteria and explicit exclusions in
    `docs/TG_ADMIN_COMMAND_SCOPE.md`.
  - Documented risks: library mismatch (raw requests vs python-telegram-bot),
    JSON schema dependency, and empty output mount.
  - Status: `review_required`.

## 2026-06-18 (Docs)

- Completed TASK-005 documentation verification for "Improve production image quality
  and statistics" (Job ID: 2026-06-17_172653_videocam-ai-improve-production-image-quality-and-statistics-task-005).
  - Verified `README.md` and `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` against the
    implemented behavior in `cams_grabber/snapshot_triage.py`.
  - Fixed validation status in `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`: test count
    updated from 32 to 52 to reflect the full current test suite.
  - Aligned `--model-dir` default description across `README.md` and
    `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` to match CLI parser help (`models`).
  - Ran `.venv/bin/python -m py_compile cams_grabber/snapshot_triage.py tests/test_snapshot_triage.py` (clean).
  - Ran `.venv/bin/python -m unittest -v tests/test_snapshot_triage.py` (52 tests, pass).
  - Status: `review_required`.

## 2026-06-18 (QA)

- Completed TASK-004 QA validation for the production image quality and statistics
  pipeline (Job ID: 2026-06-17_172653_videocam-ai-improve-production-image-quality-and-statistics-task-004).
  - Added 20 new focused tests in `tests/test_snapshot_triage.py` covering:
    - `DetectObjectsUnitTests` (7 tests): None net, None image, empty image,
      bus→vehicle remapping, low-confidence filtering, out-of-range class index,
      multiple-detection accumulation.
    - `CheckMissingExpectedTests` (5 tests): all present, some missing, all missing,
      empty expected list, zero-count treated as missing.
    - `ObjectDetectionEdgeCaseTests` (3 tests): detect_objects=True with model_dir=None,
      detection on rejected images, multi-image accumulation of total_objects_by_type.
    - `ComputeStatisticsWithDetectionTests` (4 tests): object_counts_map in statistics,
      expected objects with missing, no detection keys when no data, all expected present.
    - `GenerateTimelapseEdgeCaseTests` (1 test): unreadable first frame returns None.
  - All 52 tests pass (32 original + 20 new). `py_compile` clean.
  - No source code changes required; all tests validate existing behavior.
  - Status: `review_required`.

## 2026-06-18

- Completed TASK-003 implementation of Phase A (object detection and statistics)
  for "Improve production image quality and statistics" (Job ID: 2026-06-17_172653).
  - Added `_load_detection_model()`, `_detect_objects()`, and `_check_missing_expected()`
    to `cams_grabber/snapshot_triage.py` using MobileNet-SSD via OpenCV DNN.
  - Extended `TriageConfig` with `detect_objects`, `model_dir`, `expected_objects`.
  - Extended `run_triage()` to perform optional per-image object detection, append
    `car_count` and `person_count` to CSV rows, and build `object_counts_map` for JSON.
  - Extended `_compute_statistics()` to produce `total_objects_by_type`,
    `missing_expected_objects`, and per-frame `object_counts` when detection is enabled.
  - Added three CLI flags: `--detect-objects`, `--model-dir`, `--expected-objects`.
  - Added 5 new focused tests in `tests/test_snapshot_triage.py` covering:
    graceful skip when model files are missing; mocked detection populates CSV and JSON;
    missing expected objects are flagged in JSON; deterministic rerun with detection.
  - Updated CLI parser test to cover new flags.
  - All 32 tests pass. `py_compile` clean.
  - Updated `.gitignore` to ignore downloaded `models/` directory.
  - Updated `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` with object detection setup instructions,
    new CLI flags, new CSV columns, extended JSON schema, updated validation status.
  - Updated `README.md` with new CLI flags and JSON fields.
  - Status: `review_required`.

## 2026-06-18

- Completed TASK-005 documentation increment for the production media quality
  and object statistics pipeline (Job ID: 2026-06-17_173502, task-005).
  - Updated `README.md` with all current CLI flags (`--gradient-threshold`,
    `--kept-dir`, `--generate-video`, `--video-fps`), outputs (CSV, JSON summary,
    kept directory, timelapse video), and quality rank description.
  - Updated `docs/PROJECT_STATUS_MEMORY.md`, `docs/NEXT_ACTIONS.md`, and
    `docs/PROJECT_MANAGER.yaml` to reflect current project state.
  - All 27 tests pass. `py_compile` clean.
  - Status: `review_required`.

- Completed TASK-004 QA validation and implementation for the production media quality
  and object statistics pipeline (Job ID: 2026-06-17_173502, task-004).
  - Implemented four new functions in `cams_grabber/snapshot_triage.py`:
    `_compute_statistics()`, `_write_summary_json()`, `_copy_kept_frames()`,
    `_generate_timelapse()`.
  - Extended `TriageConfig` with `generate_video`, `video_fps`, `kept_dir` fields.
  - Extended `run_triage()` to produce `triage_summary.json` after every run and
    optionally copy kept frames to a directory and/or generate a timelapse video.
  - Added three CLI flags: `--generate-video`, `--video-fps`, `--kept-dir`.
  - Added 23 new focused tests in `tests/test_snapshot_triage.py` covering:
    JSON summary schema completeness, value consistency, determinism on rerun,
    all-rejected edge case, quality rank ordering and single-image, empty input;
    kept directory exactness, empty kept, no directory when not configured;
    timelapse video creation, graceful skip on empty kept, skip when not requested;
    `_compute_statistics` unit tests; `_write_summary_json` unit test;
    `_copy_kept_frames` unit tests; `_generate_timelapse` unit tests;
    CLI parser new flags; end-to-end integration with JSON + kept dir + video.
  - All 27 tests pass. Existing 4 tests unchanged and passing.
  - Updated `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` with new outputs, CLI flags,
    JSON schema, kept directory, timelapse video, and codec notes.
  - Note: video codec availability depends on the host OpenCV build; the
    implementation uses a fallback chain (mp4v -> avc1 -> XVID -> skip with warning).
  - Note: object detection/object statistics remain out of scope for this increment;
    the design doc recommends a future interface for `object_counts` per image.

- Completed TASK-002 design for the production media quality and object statistics
  pipeline (Job ID: 2026-06-17_173502).
  - Documented affected services (5 services, 1 primary module), data flows,
    and interfaces in `docs/TASK002_MEDIA_QUALITY_OBJECT_STATS_DESIGN.md`.
  - Documented implementation approach: phased split (Phase A: JSON + kept-dir,
    Phase B: timelapse video) with rationale.
  - Documented 5 key tradeoffs: video codec strategy, frame resizing, quality
    rank computation, scope consolidation, and object detection scoping.
  - Recommended consolidating overlapping scopes (Job IDs 2026-06-17_172653 and
    2026-06-17_173502) into a single implementation increment.
  - Identified dependency on accepted TASK-003 state before implementation begins.

## 2026-06-18

- Completed TASK-002 design for "Improve production image quality and statistics"
  (Job ID: 2026-06-17_172653, task-002).
  - Documented affected services (5 services, 1 primary module), data flows,
    and interfaces in `docs/TASK002_IMPROVE_IMAGE_QUALITY_STATISTICS_DESIGN.md`.
  - Object detection is explicitly in-scope: MobileNet-SSD via OpenCV DNN for
    car/person counting, with `--detect-objects`, `--model-dir`, and
    `--expected-objects` CLI flags.
  - Enhanced image quality metrics: `contrast_score` (grayscale std) and
    `overexposure_score` (highlight clipping percentage).
  - Documented phased implementation approach (Phase A: object detection;
    Phase B: quality metrics) to keep each increment reviewable.
  - Documented 4 key tradeoffs: detection model choice, model file distribution,
    metric informatonal vs rejection use, and scope relationship to existing
    increments.
  - Validation plan covers syntax, unit tests, manual model-run verification,
    graceful missing-model fallback, determinism, and edge cases.
  - Status: `review_required`.

## 2026-06-17

- Completed TASK-001 scope definition for "Build production media quality and
  object statistics pipeline" (Job ID: 2026-06-17_173502).
  - Defined minimum deliverable: JSON statistics summary, optional timelapse
    video generation from kept frames, and copy kept frames to `kept/` directory.
  - Recorded measurable acceptance criteria and explicit exclusions in
    `docs/PRODUCTION_MEDIA_QUALITY_OBJECT_STATISTICS_SCOPE.md`.
  - Explicitly scoped out object detection/counting under project guardrails.
  - Documented risks: video codec availability, mixed image sizes, JSON schema
    contract, overlap with pending TASK-003 review, and overlap with pending
    video/statistics scope (Job ID 2026-06-17_172653).

## 2026-06-17

- Completed TASK-001 scope definition for "Improve production image quality and
  statistics" (Job ID: 2026-06-17_172653...).
  - Defined minimum deliverable: JSON statistics summary and optional timelapse
    video generation from kept frames.
  - Recorded measurable acceptance criteria and explicit exclusions in
    `docs/PRODUCTION_VIDEO_STATISTICS_SCOPE.md`.
  - Preserved existing project guardrails: no object detection, no real-time
    stream, no cloud/API/database, no source-image deletion, no multi-camera
    orchestration.
  - Documented risks: video codec availability, mixed image sizes, JSON schema
    contract, and overlap with pending TASK-003 review.

## 2026-06-17

- Completed TASK-003 implementation of the secondary gradient-based blur metric.
  - Added `_compute_gradient_score()` to `cams_grabber/snapshot_triage.py` using
    gradient magnitude variance (NumPy `np.gradient` central differences).
  - Updated composite blur decision to reject when either Laplacian or gradient
    falls below threshold.
  - Extended CSV schema with `gradient_score` column.
  - Added `--gradient-threshold` CLI argument with default `20.0`.
  - Updated `tests/test_snapshot_triage.py` with new CSV schema assertion and
    three focused tests for gradient metric behavior.
  - Updated `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` with new column, threshold, and
    tuning guidance.
  - Validated all changes: existing test suite passes, new tests pass, CLI help
    updated, py_compile clean.

## 2026-06-17 (earlier)

- Completed TASK-001 scope definition for the production image quality problem.
- Defined minimum deliverable: add a secondary gradient-based blur metric to the
  existing snapshot triage pipeline, composite blur decision, extended CSV schema,
  new CLI argument, focused tests, and runbook update.
- Recorded measurable acceptance criteria and explicit exclusions in
  `docs/PRODUCTION_IMAGE_QUALITY_SCOPE.md`.
- Updated project tracking docs to reflect `review_required` status.
- Completed TASK-002 design for the gradient blur metric increment.
  - Documented affected modules, data flow, implementation steps, and tradeoffs.
  - Design at `docs/TASK002_GRADIENT_BLUR_DESIGN.md` covering:
    - Sobel variance as the chosen secondary blur metric.
    - OR composite logic (reject if either Laplacian or gradient fails).
    - CSV schema extension with `gradient_score` column.
    - Risks: metric correlation with Laplacian, synthetic-fixture-only calibration.

## 2026-06-13

- Registered the project with AI Project Manager.

## 2026-06-15

- Completed TASK-001 scope definition for the camera project idea.
- Added minimum deliverable, measurable acceptance criteria, and explicit exclusions.
- Updated project tracking docs to `review_required` state pending human approval.
- Human review approved the TASK-001 scope and advanced the project to TASK-002 design.

## 2026-06-16

- Implemented TASK-003 snapshot triage pipeline at `cams_grabber/snapshot_triage.py`.
- Added deterministic blur, low-light, and perceptual duplicate rejection rules.
- Added CSV reporting to `output/triage_report.csv` and rejected-image copy output to `rejected/`.
- Added focused test coverage in `tests/test_snapshot_triage.py`.
- Added execution runbook at `docs/SNAPSHOT_TRIAGE_RUNBOOK.md`.
- Prepared TASK-002 design package for supervised review at `docs/SNAPSHOT_TRIAGE_DESIGN.md`.
- Documented module boundaries, data flow, CLI/config interface, output contract, thresholds, validation approach, and tradeoffs.
- Re-synchronized planning docs to make TASK-002 the active review gate before implementation approval.
- Completed TASK-004 validation increment for snapshot triage.
- Strengthened focused validation to assert deterministic duplicate group labeling, rejected-copy behavior, and source-image immutability in `tests/test_snapshot_triage.py`.
- Executed validation commands: `python3 -m unittest -v tests/test_snapshot_triage.py`, `python3 -m unittest discover -s tests -v`, and smoke CLI run `python3 cams_grabber/snapshot_triage.py <input_dir>` with explicit output/rejected dirs.
- Completed TASK-005 documentation increment for snapshot triage.
- Updated `README.md` and `docs/SNAPSHOT_TRIAGE_RUNBOOK.md` with executable local-folder triage commands, output paths, thresholds, tuning guidance, and explicit limitations.
- Re-validated command usability and focused behavior coverage with: `python3 cams_grabber/snapshot_triage.py --help` and `python3 -m unittest -v tests/test_snapshot_triage.py`.
- Added `requirements-dev.txt` dependencies for local validation (`numpy<2.0` and
  `opencv-python-headless`) and verified the ignored `.venv` workflow.
- Updated `AGENTS.md`, `README.md`, and project docs with the validated `.venv`
  commands before publishing the reviewed snapshot triage package.

## 2026-06-19 (QA)

- Completed TASK-004 QA validation for "Fix tg_bot still stuck on old LAST_SENT_FOLDER after fresh-first".
- Added 7 focused QA tests in `tests/test_tg_bot.py` (`TgBotFolderAdvanceQATests`):
  - `test_advance_state_file_write_failure`: module globals advance even when state file write raises OSError.
  - `test_no_dated_folders_no_advancement`: when `_get_latest_run_date()` returns None, LAST_SENT_FOLDER is unchanged.
  - `test_send_photo_failure_triggers_advancement`: send_photo returning False for all images leaves sent_count at 0, triggering advancement.
  - `test_empty_current_folder_advances`: folder with zero image files sends nothing, triggers advancement to next folder.
  - `test_advance_with_non_date_folder_ignored`: directories not matching YYYY-MM-DD are excluded from subfolder list, not used as advancement targets.
  - `test_admin_state_file_unreadable`: `_format_admin_message` shows "unreadable" when state file read raises OSError.
  - `test_last_sent_folder_deleted_between_iterations`: when LAST_SENT_FOLDER is absent from disk folders, bot processes the latest folder as fallback.
- Notable finding: state file write failure (OSError) does not prevent in-memory advancement — module globals update correctly, but persistence is lost. This is consistent with the `except OSError: pass` pattern in the advancement block.
- No source code changes required. All 219 tests pass (139 tg_bot + 52 snapshot_triage + 28 web_viewer). `py_compile` clean.
