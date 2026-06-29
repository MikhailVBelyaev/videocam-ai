# videocam-ai — Deep Analysis Report

**Date:** 2026-06-29  
**Scope:** Full codebase audit — structure, architecture, security  
**Method:** Static analysis of all source files; no dynamic execution  

---

## Executive Summary

The project is a well-conceived, single-purpose surveillance system with clear domain logic and good
documentation discipline. For a private home server with no public exposure, the operational risk is
low. However, there are **three findings that require immediate attention**:

1. **Camera credentials committed to git** — RTSP password is in `main_ssh.py` and
   `docker-compose.yml` in plain text and is permanently in the git history.
2. **Path traversal in `qa_service`** — the `/img/<path:rel>` endpoint allows reading arbitrary
   files inside the container using URL-encoded `..` sequences.
3. **Test suite tests a deleted API** — `test_tg_bot.py` and `test_web_viewer.py` import ~20
   functions that no longer exist; they fail with `ImportError` and provide zero confidence.

Overall health: **moderate**. The core detection pipeline is solid; the support services need
hardening before the system is extended or exposed beyond LAN.

---

## Architecture Map

```
┌─────────────────── Docker host (oldgamepc) ───────────────────────────┐
│                                                                         │
│  ┌──────────────────────┐   RTSP/TCP   ┌────────────────────────────┐ │
│  │  IP Camera           │ ──────────▶  │  cams_grabber_cam1         │ │
│  │  192.168.100.2       │              │  (GPU 1, NVDEC+YOLOv8s)    │ │
│  └──────────────────────┘              └──────────────┬─────────────┘ │
│                                                        │ writes        │
│  ┌─────────────────────────────────────────────────── ▼ ─────────────┐│
│  │                     output/cam1/YYYY-MM-DD/                        ││
│  │  frame_TS_idN_vehicle.jpg   frame_TS_idN_vehicle_debug.jpg         ││
│  │  clip_TS_idN_person.mp4     .frame_stacking  .sysinfo.json         ││
│  └───┬──────────────────┬───────────────┬──────────────┬─────────────┘│
│      │ polls 5s         │ polls 2s       │ reads        │ reads ro     │
│      ▼                  ▼               ▼              ▼              │
│  ┌────────┐      ┌──────────┐    ┌────────────┐  ┌──────────────┐    │
│  │ tg_bot │      │qa_service│    │ sys_monitor│  │ web_viewer   │    │
│  │ :none  │      │ :8083    │    │ :none      │  │ :8082        │    │
│  │ Tg API │      │ Flask+   │    │ writes     │  │ Flask gallery│    │
│  │ polling│      │ YOLOv8n  │    │ .sysinfo   │  │ read-only    │    │
│  └────────┘      │ SQLite   │    │ Tg alerts  │  └──────────────┘    │
│                  └──────────┘    └────────────┘                       │
│                                                                         │
│  Telegram ◀── tg_bot / sys_monitor (HTTPS, outbound only)             │
└─────────────────────────────────────────────────────────────────────────┘
```

**Data flow:** Camera → GStreamer/NVDEC → frame buffer → YOLO track → quality gate →
disk (output/) → tg_bot/qa_service/web_viewer.

**Layers:** No formal layering; each service is a single Python file. There is no shared library;
the `output/` filesystem directory is the only integration contract between services.

---

## Architecture & Structure Findings

### A1 — God-script: `main_ssh.py` runs at module level (Medium)

`cams_grabber/main_ssh.py` places its entire inference loop (lines 352–575) at module scope:

```python
# line 352
while True:
    slot = _get_latest_slot()
    ...
```

Consequences:
- The file is **not importable** — importing it starts the GStreamer pipeline, loads the GPU, and
  enters an infinite loop. There are no unit tests for any of the detection logic as a result.
- The YOLO model, GStreamer pipeline, and ~15 module-level dicts are global singletons. Any future
  multi-camera-per-process design would require a full rewrite.
- Module-level state (`object_last_seen`, `detection_buffer`, `_last_save_hash`, `_recording`,
  `_writer`, `_preroll`, `_record_cooldown`) is init'd at import time; a crash/exception in the
  startup block before the loop is unreachable.

Recommendation: wrap the loop in `main()` and guard with `if __name__ == "__main__": main()`.

---

### A2 — Test suite imports a deleted API (Medium)

`tests/test_tg_bot.py` (line 12–28) imports these names from `tg_bot.bot`:

```python
_get_image_list, _get_latest_image_path, _get_latest_run_date,
_initialize_startup_state, _is_admin_chat, _is_fresh, _kept_images_exist,
_query_container_states, _read_latest_summary, _send_new_images_iteration,
_summarize_live_output, load_last_sent_file, save_last_sent_file, send_photo,
LAST_SENT_IMAGE, LAST_SENT_FOLDER, _format_admin_message, _format_state_message,
_format_uptime
```

Of these, at least 10 (`_get_image_list`, `_kept_images_exist`, `_initialize_startup_state`,
`load_last_sent_file`, `save_last_sent_file`, `LAST_SENT_IMAGE`, `LAST_SENT_FOLDER`, and the
multi-camera refactor globals) **do not exist** in the current `bot.py`. The import fails with
`ImportError`, so the entire test class never runs. Similarly `tests/test_web_viewer.py` imports
`_get_latest_image_links`, `_get_latest_run_date`, `_is_fresh`, `_read_latest_summary`,
`_render_admin_page` — none of which exist in current `web_viewer/app.py`.

`tests/test_snapshot_triage.py` appears to test the offline `snapshot_triage.py` tool and is
likely still functional.

Consequence: **there is no passing test suite for the two most-changed services.** Any regression
in `tg_bot` or `web_viewer` is invisible.

---

### A3 — `deploy_videocam_ai.sh` violates documented workflow (Low)

`CLAUDE.md` states: *"Never deploy directly from local filesystem (no rsync). Always go through GitHub."*

The script at `deploy_videocam_ai.sh:17` does exactly that:
```bash
rsync -av ... ./ "$TARGET_SERVER:$REMOTE_DIR/"
```

It also hardcodes `TARGET_SERVER="user@192.168.100.194"` (local LAN IP) rather than
the Tailscale address (`oldgamepc.tail7c033b.ts.net`) documented everywhere else. Running this
script from outside the LAN silently fails or connects to the wrong host.

---

### A4 — Duplicate route definition in `web_viewer/app.py` (Low)

`app.py` registers two handlers for `/`:
- `@app.route("/")` → `index()` (line 140)
- `@app.route("/", defaults={"path": ""})` → `serve_static()` (line 284)

Flask resolves this by using the first-registered rule (`index()`), so no runtime error occurs.
But `serve_static` with `path=""` would serve `OUTPUT_DIR/` root if Flask ever matched it,
which would return a directory listing or 404 depending on Flask version. Code smell that should
be resolved by removing `defaults={"path": ""}` from the catch-all.

---

### A5 — Flask development server in production (Medium)

Both `web_viewer/app.py:291` and `qa_service/qa.py:917` use:
```python
app.run(host="0.0.0.0", ...)
```

Flask's built-in dev server is single-threaded (web_viewer) or pseudo-threaded (qa_service uses
`threaded=True`), not designed for concurrent HTTP connections, and prints
`WARNING: This is a development server. Do not use it in a production deployment.` in logs.
Under simultaneous browser tabs or rapid gallery navigation, responses may stall or queue.

---

### A6 — `_id_last_hash` dict grows without bound in `qa_service/qa.py` (Low)

```python
# qa_service/qa.py:126
_id_last_hash: dict = {}
```

This dictionary is keyed by `(camera, tracking_id)` tuples and is never pruned. YOLO tracking IDs
are monotonically increasing per session; each session restart of cams_grabber adds new IDs.
Over weeks of continuous operation the dict grows to tens of thousands of entries. With ~100 bytes
per entry, 100k entries ≈ 10 MB — noticeable but not critical on a server with GBs of RAM.

---

### A7 — SQLite connection shared across threads without a lock (Medium)

In `qa_service/qa.py`:
```python
conn = _init_db()  # single connection object
# ...
t = threading.Thread(target=watcher, args=(model, conn), ...)  # uses conn for writes
app.run(..., threaded=True)  # Flask uses conn for reads in _db_load_24h
```

`check_same_thread=False` is set, and WAL mode reduces lock contention, but there is no mutex
protecting `conn` across concurrent read (Flask) and write (watcher) operations on the same
connection object. Under SQLite's WAL mode, concurrent readers and a single writer work at the
file level, but `sqlite3.Connection` objects in Python are not thread-safe for concurrent use
without explicit locking. A call to `conn.execute()` from Flask overlapping with `conn.commit()`
from the watcher can cause a `ProgrammingError: recursive use of cursors not allowed` or silent
data corruption.

---

## Security Findings

| # | Severity | File : Line | Finding | Exploitability |
|---|----------|-------------|---------|----------------|
| S1 | **High** | `cams_grabber/main_ssh.py:35` | Camera credentials (`admin`/`12311231aA@`) hardcoded as default for `RTSP_URL`. Permanently in git history. | Anyone who clones the repo gets valid camera credentials. |
| S2 | **High** | `docker-compose.yml:13` | Same credentials in `RTSP_URL` environment variable, committed to git. | Same as S1; also visible to anyone who reads CI logs or Docker env dumps. |
| S3 | **High** | `qa_service/qa.py:368-373` | **Path traversal** in `/img/<path:rel>`: uses `OUTPUT_DIR / rel` then `send_file()` without sanitization. `Path.__truediv__` does not block `..` segments. | `GET /img/../../etc/passwd` resolves to container's `/etc/passwd`. Container runs as root, so any file in the container is readable. |
| S4 | **Medium** | `web_viewer/app.py:62-74`, `203-206` | **Path traversal via `camera` query param**: `_images_for_date(camera, date)` calls `os.path.join(OUTPUT_DIR, camera, date)` where `camera` is raw user input. `_date_dirs(camera)` has the same pattern. | `GET /raw?camera=../&date=` lists directory contents outside `output/`. Container mounts `output/` and `/var/run/docker.sock` (tg_bot only), so scope is limited but real. |
| S5 | **Medium** | `docker-compose.yml:87` | Docker socket mounted in `tg_bot`: `- /var/run/docker.sock:/var/run/docker.sock:ro`. The Docker SDK used by `/state` command can read **all container environment variables** (including RTSP URL, Telegram token) via `c.attrs`. | If tg_bot is compromised (e.g. via Telegram Bot API), attacker enumerates all secrets in running containers. Read-only mount does NOT prevent metadata reading. |
| S6 | **Medium** | `web_viewer/app.py:284-287` | `serve_static` serves everything under `OUTPUT_DIR` including `.sysinfo.json` (hardware fingerprint), `.frame_stacking` (toggle state), per-camera `.last_sent_file` (internal cursor state). `send_from_directory` blocks path traversal (`..`) but not dot-files. | `GET /.sysinfo.json` returns CPU/RAM/GPU/disk details. `GET /cam1/.last_sent_file` leaks internal bot cursor. |
| S7 | **Medium** | All services | No authentication on HTTP ports 8082 (web_viewer) and 8083 (qa_service). All saved surveillance footage accessible to any device on the LAN or Tailscale network. | Anyone on Tailscale network can browse all footage, QA stats, and use the path traversal bugs. |
| S8 | **Low** | `cams_grabber/Dockerfile`, `qa_service/Dockerfile`, `sys_monitor/Dockerfile` | Containers run as root (no `USER` directive). If any service is compromised, the attacker has root inside the container. | Increases blast radius of any other vulnerability. |
| S9 | **Low** | `cams_grabber/main_ssh.py:194-275` | GStreamer may log the RTSP URL (with embedded credentials) to stderr/Docker logs when the pipeline initializes or reconnects. GStreamer's `rtspsrc` element logs its location property in debug output. | Credentials appear in `docker logs cams_grabber_cam1` if GStreamer debug logging is enabled. |
| S10 | **Low** | `web_viewer/app.py:159-197` | HTML constructed with f-strings using `fname` (filename) and `selected_cam`/`selected` (user query params). Values from filesystem listing are system-controlled, but `selected_cam` from query string is injected into `<select>` option values. If `selected_cam` contains `"` or `>`, it could break HTML structure. | Not a practical XSS path in this deployment since `os.listdir` normalizes names, but a technically unsanitized HTML construction pattern. |

---

## Prioritized Fix Plan

### Critical / Fix now

#### Fix 1 — Remove credentials from git history (S1, S2)
**What:** Camera password `12311231aA@` is committed. Git history cannot be undone without a
force-push rewrite, but the password should be rotated and removed from tracked files.

**How:**
1. Rotate the camera password on the device's web interface.
2. Move the RTSP URL into `tg_bot/.env` (already gitignored) and source it via `env_file:` in
   docker-compose.yml, or create a dedicated `cams_grabber/.env`.
3. Remove the hardcoded default from `main_ssh.py:35` — raise an error if `RTSP_URL` is unset:
   ```python
   RTSP_URL = os.getenv("RTSP_URL")
   if not RTSP_URL:
       raise ValueError("RTSP_URL environment variable is required")
   ```
4. Optional: run `git filter-repo` to scrub the password from history.

**Effort:** 2h. **Risk:** Password must be rotated on camera first or service breaks.

---

#### Fix 2 — Path traversal in `qa_service` `/img/` route (S3)
**What:** Replace `send_file(str(p))` with `send_from_directory`, which uses Flask/Werkzeug's
`safe_join` to reject `..` path segments.

**In `qa_service/qa.py:368-373`:**
```python
# Before:
@app.route("/img/<path:rel>")
def serve_img(rel):
    p = OUTPUT_DIR / rel
    if not p.is_file():
        abort(404)
    return send_file(str(p))

# After:
from flask import send_from_directory
@app.route("/img/<path:rel>")
def serve_img(rel):
    return send_from_directory(str(OUTPUT_DIR), rel)
```

`send_from_directory` raises 404 automatically for missing files and rejects traversal.

**Effort:** 15 minutes. **Risk:** None — behaviour-equivalent for valid paths.

---

#### Fix 3 — Path traversal in `web_viewer` camera/date params (S4)
**What:** Validate `camera` and `date` query params against the actual filesystem listing before
use in path construction.

**In `web_viewer/app.py`, guard camera and date:**
```python
selected_cam = request.args.get("camera", cameras[0] if cameras else "")
if selected_cam not in cameras:   # cameras() already validated against filesystem
    selected_cam = cameras[0] if cameras else ""
dates = _date_dirs(selected_cam) if selected_cam else []
selected = request.args.get("date", dates[0] if dates else "")
if selected not in dates:
    selected = dates[0] if dates else ""
```

**Effort:** 30 minutes. **Risk:** Minimal — only valid camera/date values continue.

---

### Medium term / Fix soon

#### Fix 4 — Repair broken test suite (A2)
**What:** `tests/test_tg_bot.py` and `tests/test_web_viewer.py` are dead. Update them to match
the current API (`_cameras()`, `_cam_state`, `_send_camera_images()`, etc.) or delete the
non-functional test cases and write new ones against the current interface.

At minimum: ensure `pytest tests/` passes without `ImportError` before the next deploy.

**Effort:** 4–8h. **Risk:** Tests may reveal regressions in the multi-camera refactor.

---

#### Fix 5 — Replace Flask dev server with gunicorn (A5)
**What:** In `web_viewer/Dockerfile` and `qa_service/Dockerfile`, install gunicorn and change the
CMD. Also update `web_viewer/requirements.txt` and `qa_service/requirements.txt`.

```dockerfile
# web_viewer/Dockerfile
RUN pip install --no-cache-dir gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
```
```dockerfile
# qa_service/Dockerfile  
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--threads", "4", "qa:app"]
```

Note: `qa_service` must keep its `watcher` daemon thread alive. With gunicorn's `--threads` the
thread survives (gevent worker would kill it). Use sync worker with `--threads 4` or pre-fork and
start the watcher in an `@app.before_first_request`/startup hook.

**Effort:** 2h. **Risk:** Requires testing startup of watcher thread under gunicorn.

---

#### Fix 6 — Add lock for SQLite connection in `qa_service` (A7)
**What:** Protect `conn` with a threading lock, or (better) open a new connection per request
using `threading.local()`.

```python
# qa_service/qa.py — simplest fix
_db_lock = threading.Lock()

def _db_insert(conn, result):
    with _db_lock:
        conn.execute("""INSERT OR IGNORE ...""", (...))
        conn.commit()

# In Flask route:
def api_stats():
    with _db_lock:
        rows = conn.execute("SELECT ...").fetchall()
```

Or use `threading.local()` to give each thread its own connection.

**Effort:** 1h. **Risk:** Low — WAL mode already reduces contention; this adds correctness.

---

#### Fix 7 — Restrict Docker socket access (S5)
**What:** The `_query_container_states()` function only needs container status (State.Status,
State.Health, State.StartedAt). It does not need to read environment variables. However,
the Docker SDK with a read-only socket exposes everything in `c.attrs`.

Options (in ascending effort):
- **Option A (minimal):** Accept the current risk. The socket is read-only; an attacker needs
  code execution inside tg_bot first, which is not a realistic path for a private Telegram bot.
- **Option B (recommended):** Replace the Docker SDK call with a local `docker ps --format json`
  subprocess. Remove the socket mount entirely. Read `.sysinfo.json` for hardware stats.
- **Option C:** Use Docker's TCP API over a reverse proxy that limits to the specific endpoints
  needed (complex, not warranted for this scale).

**Effort for B:** 2h. **Risk:** Loses real-time health info if `.sysinfo.json` becomes stale (but
sys_monitor now updates every 60s).

---

#### Fix 8 — Wrap `main_ssh.py` loop in `main()` (A1)
**What:** Move all module-level state initialization and the inference loop into a `main()`
function guarded by `if __name__ == "__main__":`. This enables unit testing of helpers
(`_is_frame_valid`, `_stack_frames`, `iou`, `_phash`) and prevents accidental import side-effects.

```python
def main():
    global model, _qk, object_last_seen, ...
    model = YOLO("yolov8s.pt")
    _init_quality_kernels()
    t = threading.Thread(target=_reader_thread, args=(RTSP_URL,), daemon=True)
    t.start()
    while True:
        ...

if __name__ == "__main__":
    main()
```

**Effort:** 2h. **Risk:** No behavior change at runtime. Enables future testability.

---

### Long-term / Refactor

#### Fix 9 — Add basic HTTP authentication to web ports (S7)
For a surveillance system, HTTP Basic Auth (enforced over Tailscale's already-encrypted transport)
is a simple first barrier. Both Flask services could use flask-httpauth or a simple decorator:

```python
import functools, os
from flask import request, Response

_WEB_USER = os.getenv("WEB_USER", "")
_WEB_PASS = os.getenv("WEB_PASS", "")

def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != _WEB_USER or auth.password != _WEB_PASS:
            return Response("Auth required", 401,
                            {"WWW-Authenticate": 'Basic realm="videocam"'})
        return f(*args, **kwargs)
    return decorated
```

**Effort:** 3h for both services + `.env` integration. **Risk:** Breaks direct browser access
until credentials are configured.

---

#### Fix 10 — Filter hidden files from `web_viewer` static serving (S6)
The `serve_static` route currently serves `.sysinfo.json`, `.last_sent_file`, `.frame_stacking`:
```python
@app.route("/<path:path>")
def serve_static(path):
    # Block dot-files
    if any(part.startswith('.') for part in Path(path).parts):
        abort(404)
    return send_from_directory(OUTPUT_DIR, path)
```

**Effort:** 20 minutes.

---

#### Fix 11 — Prune `_id_last_hash` in `qa_service` (A6)
Add a TTL or cap by keeping only the last N tracking IDs seen within the last 24h:
```python
# After updating _id_last_hash, prune stale entries
# (simplest: cap to 10000 entries)
if len(_id_last_hash) > 10000:
    # Remove oldest half
    keys = list(_id_last_hash.keys())
    for k in keys[:5000]:
        del _id_last_hash[k]
```

**Effort:** 30 minutes.

---

#### Fix 12 — Add non-root users to Dockerfiles (S8)
```dockerfile
# After COPY:
RUN useradd -r -u 1001 appuser && chown -R appuser /app
USER appuser
```

Note: containers requiring NVDEC (`cams_grabber`, `qa_service`) need the user to be in the
`video` group; `sys_monitor` needs access to `nvidia-smi`. Test before deploying.

**Effort:** 3h (per service needs validation). **Risk:** Permission issues with output/ volume.

---

## Appendix: Verification Scope

### Files read in full

| File | Status |
|------|--------|
| `cams_grabber/main_ssh.py` | ✅ Complete |
| `cams_grabber/Dockerfile` | ✅ Complete |
| `cams_grabber/requirements.txt` | ✅ Complete |
| `tg_bot/bot.py` | ✅ Complete |
| `tg_bot/Dockerfile` | ✅ Complete |
| `tg_bot/requirements.txt` | ✅ Complete |
| `qa_service/qa.py` | ✅ Complete |
| `qa_service/Dockerfile` | ✅ Complete |
| `qa_service/requirements.txt` | ✅ Complete |
| `web_viewer/app.py` | ✅ Complete |
| `web_viewer/Dockerfile` | ✅ Complete |
| `web_viewer/requirements.txt` | ✅ Complete |
| `sys_monitor/monitor.py` | ✅ Complete |
| `sys_monitor/Dockerfile` | ✅ Complete |
| `sys_monitor/requirements.txt` | ✅ Complete |
| `docker-compose.yml` | ✅ Complete |
| `ups_monitor.sh` | ✅ Complete |
| `deploy_videocam_ai.sh` | ✅ Complete |
| `.gitignore` | ✅ Complete |
| `tests/test_tg_bot.py` | ✅ First 1399 lines (sufficient to confirm import failure) |
| `tests/test_web_viewer.py` | ✅ Complete |
| `tests/test_snapshot_triage.py` | ✅ Complete |
| `CLAUDE.md`, `docs/ARCHITECTURE.md` | ✅ Via system context |

### Not checked

| Item | Reason |
|------|--------|
| `cams_grabber/snapshot_triage.py` | Offline batch tool, not part of live pipeline |
| `docs/*.md` (30+ files) | Design history, not production code |
| `analyses/` | Historical analysis output |
| `.claude/settings.local.json` | IDE settings |
| Runtime behavior / dynamic analysis | Read-only audit scope |
| Network exposure beyond Tailscale | Requires infrastructure access |
| Camera firmware / RTSP stream security | Out of scope |
| Telegram Bot API token validity | Secret; not checked |

### Requires further investigation

- Whether GStreamer actually logs the RTSP URL to stdout in the running container (verify with
  `docker logs cams_grabber_cam1 2>&1 | grep rtsp`).
- Whether `_format_state_message` in `tg_bot/bot.py` accepts a `sysinfo` parameter — the current
  signature is `_format_state_message(states, sysinfo)` but `state_command` passes only `states`
  to the function after the refactor. This may be a silent bug causing `/state` to omit hardware
  stats. Verify with a live `/state` call.
