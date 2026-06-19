# TASK-002 Design: Web Viewer /admin Page

Job ID: 2026-06-19_060847_videocam-ai-change-admin-add-web-server-page-with-cars-and-task-002
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19
Author: Hermes Project Manager (execution agent)

---

## 1. Affected Services, Modules, Data Flows, and Interfaces

### 1.1 Services Inventory

| Service | Role | Impact |
|---------|------|--------|
| `web_viewer` | Serves `output/` on port 8082 | **Primary** — replaces `nginx:alpine` with a minimal Python web server; adds `/admin` HTML endpoint |
| `cams_grabber/snapshot_triage.py` | Local-folder image triage producing JSON/CSV | **None** — no source changes; `output/triage_summary.json` is consumed read-only |
| `tg_bot/bot.py` | Telegram bot sending frames and handling `/admin`/`/state` | **None** — no source changes; the web `/admin` page mirrors tg_bot logic but does not call it |
| `sys_monitor/monitor.py` | System health monitoring | None |
| `cams_grabber/main_ssh.py` | RTSP stream + YOLOv8 real-time detection | None |

### 1.2 Module-Level Changes

**New `web_viewer/` service (replaces nginx)**

Current flow:
```
nginx:alpine
  └─ serve ./output:/usr/share/nginx/html:ro on port 8082
```

New flow:
```
Python web server (Flask)
  ├─ GET /admin          → read triage_summary.json + latest folder → render HTML
  └─ GET /<static path>  → serve files from output/ (preserved)
```

New files to create:
- `web_viewer/Dockerfile` — `python:3.12-slim` base, install requirements, copy app
- `web_viewer/requirements.txt` — `flask` and `pytz`
- `web_viewer/app.py` — Flask application with `/admin` route and static file serving

New functions in `web_viewer/app.py`:
- `_read_latest_summary() -> dict | None` — reads `output/triage_summary.json`, returns parsed dict or None
- `_get_latest_run_date() -> str | None` — finds most recent `YYYY-MM-DD` folder in `output/`
- `_is_fresh(run_date: str | None) -> bool` — returns True if run_date is within last 24h
- `_get_latest_image_links(run_date: str) -> list[str]` — lists image files in latest folder for HTML links
- `_render_admin_page(summary: dict | None, run_date: str | None, fresh: bool, links: list[str]) -> str` — builds HTML string
- `admin_page()` — Flask route handler for `/admin`
- `serve_static(path: str)` — Flask route handler for static file serving

Modified:
- `docker-compose.yml` — replace `image: nginx:alpine` with `build: ./web_viewer`; update volume mount target to match container path; add healthcheck

**`tests/test_web_viewer.py`**

New test module:
- Unit test `/admin` with mocked `triage_summary.json`: verifies HTML contains `total_images`, `kept_images`, `car_count`, `person_count`
- Unit test `/admin` with missing JSON: verifies error message is present in HTML and response is HTTP 200
- Unit test `/admin` with malformed JSON: verifies graceful fallback
- Unit test static file serving: verifies `/<date>/<filename>` returns file content with correct mimetype
- Unit test car/person defaults to 0 when absent from `total_objects_by_type`

**`README.md`**

Modified:
- Document new web viewer behavior, `/admin` URL (`http://<host>:8082/admin`), and container recreate step

### 1.3 Data Flow Diagram

```
Browser GET /admin
       │
       ▼
┌─────────────────────────────┐
│ web_viewer/app.py           │
│ Flask /admin route          │
└────────┬────────────────────┘
         │
    ┌────┴──────────────────────────────┐
    │                                   │
    ▼                                   ▼
read output/triage_summary.json    scan output/ dated folders
    │                                   │
    ▼                                   ▼
_parse JSON stats                 _find latest YYYY-MM-DD
    │                                   │
    └────────────┬──────────────────────┘
                 │
                 ▼
        _render_admin_page()
                 │
                 ▼
        HTML response (inline styles)
                 │
                 ▼
        Browser renders dashboard
```

Static file flow (preserved):
```
Browser GET /2026-06-19/frame.jpg
       │
       ▼
Flask send_from_directory(OUTPUT_DIR, "2026-06-19/frame.jpg")
       │
       ▼
File bytes + correct Content-Type
```

### 1.4 Interfaces

**No new environment variables.**
- `OUTPUT_DIR` defaults to `/app/output` inside the container (set via volume mount in `docker-compose.yml`).

**New HTTP interface:**
- `GET /admin` — returns HTML page (200) containing:
  - Latest run date (from most recent `YYYY-MM-DD` folder in `output/`)
  - Freshness indicator (e.g., "Fresh (within 24h)" or "Stale")
  - `total_images` and `kept_images`
  - `car_count` and `person_count` from `total_objects_by_type`
  - `missing_expected_objects` count (if any)
  - Clickable links to latest image file(s) in the most recent dated folder
- `GET /admin` with missing/malformed `triage_summary.json` — returns HTML with a concise error message (HTTP 200 or 404; 200 is preferred so the page always renders)
- `GET /<path>` — serves static files from `output/` (preserving existing URLs)

**Data dependency contract (`output/triage_summary.json`):**
```json
{
  "total_images": 150,
  "kept_images": 23,
  "total_objects_by_type": {"car": 45, "person": 12},
  "missing_expected_objects": [{"filename": "IMG_0001.jpg", "missing": ["car"]}]
}
```
The design uses `.get()` with defaults (`total_objects_by_type` defaults to `{}`, `missing_expected_objects` defaults to `[]`) so future schema changes do not crash the page.

**File system interface:**
- `output/` directory mounted as Docker volume (already configured in `docker-compose.yml`; path adjusted for new container layout)
- `output/YYYY-MM-DD/` dated subfolders created by `snapshot_triage.py`

---

## 2. Implementation Approach

### 2.1 Recommended: Flask with Explicit Static Route

Replace `nginx:alpine` with a minimal Flask application in a custom `web_viewer` Docker image.

Structure:
1. Create `web_viewer/Dockerfile` based on `python:3.12-slim`.
2. Create `web_viewer/requirements.txt` with `flask` and `pytz`.
3. Create `web_viewer/app.py`:
   - Configure `OUTPUT_DIR` from env var (default `/app/output`).
   - Register `@app.route("/admin")` that reads `triage_summary.json`, scans `OUTPUT_DIR` for latest date folder, computes freshness, finds latest images, and renders HTML with inline styles.
   - Register catch-all `@app.route("/", defaults={"path": ""})` and `@app.route("/<path:path>")` that uses `send_from_directory(OUTPUT_DIR, path)` to preserve existing static-file URLs.
4. Update `docker-compose.yml`:
   - Replace `image: nginx:alpine` with `build: ./web_viewer`.
   - Update volume mount from `./output:/usr/share/nginx/html:ro` to `./output:/app/output:ro`.
   - Add a simple healthcheck (e.g., `curl -f http://localhost:8082/admin` or `python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/admin')"` depending on internal port).
5. Expose the same host port `8082` mapped to the Flask port (default 5000, or configure to 80 for consistency).

Why this is the best fit:
- Flask is lightweight, well-documented, and provides built-in routing, templating (Jinja2), and static file serving.
- The entire service fits in a single `app.py` under 200 lines.
- The Flask development server is acceptable for an internal low-traffic admin page; if traffic grows, a future increment can add gunicorn or nginx as a reverse proxy without changing the application code.
- `pytz` is already used by `tg_bot/bot.py` and `cams_grabber/snapshot_triage.py`, so it is a familiar dependency.

Code sketch (not production code):
```python
import os
import json
from datetime import datetime, timedelta
from flask import Flask, send_from_directory
import pytz

app = Flask(__name__)
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def _read_latest_summary():
    path = os.path.join(OUTPUT_DIR, "triage_summary.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _get_latest_run_date():
    try:
        entries = os.listdir(OUTPUT_DIR)
        date_dirs = [e for e in entries if os.path.isdir(os.path.join(OUTPUT_DIR, e))]
        valid = []
        for d in date_dirs:
            try:
                datetime.strptime(d, "%Y-%m-%d")
                valid.append(d)
            except ValueError:
                continue
        return max(valid) if valid else None
    except OSError:
        return None


def _is_fresh(run_date):
    if not run_date:
        return False
    try:
        run_dt = datetime.strptime(run_date, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
        return (datetime.now(pytz.UTC) - run_dt) <= timedelta(days=1)
    except ValueError:
        return False


def _get_latest_image_links(run_date):
    folder = os.path.join(OUTPUT_DIR, run_date)
    try:
        files = sorted(
            [f for f in os.listdir(folder)
             if f.lower().endswith(IMAGE_EXTENSIONS)
             and os.path.isfile(os.path.join(folder, f))],
            key=lambda f: os.path.getmtime(os.path.join(folder, f)),
            reverse=True,
        )
        return [f"/{run_date}/{f}" for f in files[:5]]
    except OSError:
        return []


def _render_admin_page(summary, run_date, fresh, links):
    total = summary.get("total_images", 0) if summary else 0
    kept = summary.get("kept_images", 0) if summary else 0
    objects = summary.get("total_objects_by_type", {}) if summary else {}
    car_count = objects.get("car", 0)
    person_count = objects.get("person", 0)
    missing = summary.get("missing_expected_objects", []) if summary else []
    status = "Fresh (within 24h)" if fresh else "Stale"
    date_str = run_date or "Unknown"

    links_html = "\n".join(f'<li><a href="{l}">{l}</a></li>' for l in links) if links else "<li>No images found</li>"
    error_html = "<p style='color:red'>No triage data available.</p>" if summary is None else ""

    return f"""
    <!doctype html>
    <html>
      <head><title>Admin — videocam-ai</title></head>
      <body style="font-family:sans-serif; max-width:600px; margin:2em auto;">
        <h1>Admin Dashboard</h1>
        {error_html}
        <p><strong>Latest run:</strong> {date_str}</p>
        <p><strong>Status:</strong> {status}</p>
        <p><strong>Images:</strong> {total} total, {kept} kept</p>
        <p><strong>Objects:</strong> {car_count} cars, {person_count} people</p>
        {"<p><strong>Missing expected:</strong> " + str(len(missing)) + " frames</p>" if missing else ""}
        <h2>Latest images</h2>
        <ul>{links_html}</ul>
      </body>
    </html>
    """


@app.route("/admin")
def admin_page():
    summary = _read_latest_summary()
    run_date = _get_latest_run_date()
    fresh = _is_fresh(run_date)
    links = _get_latest_image_links(run_date) if run_date else []
    html = _render_admin_page(summary, run_date, fresh, links)
    return html, 200


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(OUTPUT_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

Dockerfile sketch:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 5000
CMD ["python", "app.py"]
```

docker-compose.yml change sketch:
```yaml
  web_viewer:
    build: ./web_viewer
    container_name: web_viewer
    volumes:
      - ./output:/app/output:ro
    ports:
      - "8082:5000"
    restart: always
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/admin')"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 2.2 Alternative: FastAPI

Use FastAPI with Jinja2 templates instead of Flask.

**Pros**: Async-native, automatic API docs (though not required), modern type hints.
**Cons**: Slightly heavier dependency footprint (`fastapi`, `uvicorn`, `jinja2`); async adds complexity for a simple synchronous file-I/O page; overkill for a single HTML endpoint.

**Verdict**: Rejected. Flask is sufficient, lighter, and aligns with the "small enough for one Codex session" constraint.

### 2.3 Alternative: Keep nginx + Add Sidecar Python Service

Retain `nginx:alpine` for static files and add a new `web_admin` service (e.g., port 8083) running the Python admin page.

**Pros**: Zero risk to static-file serving performance; nginx remains for its strengths.
**Cons**: Two containers instead of one; users must remember two ports; more complex `docker-compose.yml`; the scope explicitly states "replace the web_viewer nginx service."

**Verdict**: Rejected. The approved scope specifies replacing nginx, and the Flask static-file route is adequate for the expected load.

### 2.4 Alternative: Pure stdlib `http.server` + Custom Handler

Implement a `BaseHTTPRequestHandler` subclass that handles `/admin` and falls back to file serving.

**Pros**: Zero new Python dependencies; smallest possible image.
**Cons**: No routing framework means manual URL parsing; no templating means verbose string concatenation; harder to test and maintain; security headers and MIME-type handling must be implemented manually.

**Verdict**: Rejected. Flask adds minimal overhead and significantly reduces boilerplate and maintenance burden.

---

## 3. Key Tradeoffs

### 3.1 Web Framework Choice

| Approach | Pros | Cons |
|----------|------|------|
| Flask (recommended) | Lightweight, built-in routing/templating/static files, well-known, testable | One new dependency; single-threaded dev server |
| FastAPI | Async-native, automatic docs | Heavier deps; async complexity unnecessary |
| stdlib `http.server` | Zero deps | Manual routing, no templating, brittle, hard to test |

**Decision**: Flask. It provides the right abstraction level for one dynamic page plus static file serving, and the dev server is acceptable for internal low-traffic use.

### 3.2 nginx Replacement vs Augmentation

| Approach | Pros | Cons |
|----------|------|------|
| Replace nginx with Flask (recommended) | Single container, simpler ops, satisfies scope | Flask dev server slower for static files; may need gunicorn/nginx later if traffic grows |
| Keep nginx + sidecar service | Best static-file performance | Two containers, two ports, more complex compose; conflicts with scope directive |

**Decision**: Replace nginx with Flask. Static-file performance is acceptable for the current use case (browsing camera output images). If performance becomes a concern, a future increment can introduce gunicorn or an nginx reverse proxy without changing application code.

### 3.3 HTML Rendering Approach

| Approach | Pros | Cons |
|----------|------|------|
| Inline HTML string with f-string/Jinja2 (recommended) | Simple, no extra template files, self-contained | Larger Python file; minor escaping risk |
| Separate Jinja2 template file | Cleaner separation of presentation and logic | Extra file to manage in Docker image; overkill for one small page |

**Decision**: Render HTML via an f-string or Jinja2 `render_template_string` inside `app.py`. The page is small enough that a single inline template keeps the service self-contained.

### 3.4 Static File Serving Approach

| Approach | Pros | Cons |
|----------|------|------|
| Flask `send_from_directory` catch-all route (recommended) | Preserves existing URL structure; minimal code | No directory index pages; Flask dev server handles concurrent requests sequentially |
| Flask `static_folder` | Built-in, automatic | Maps to a fixed `/static` URL prefix by default; existing URLs like `/2026-06-19/frame.jpg` would break unless reconfigured |

**Decision**: Explicit catch-all route using `send_from_directory(OUTPUT_DIR, path)`. This guarantees that existing URLs (`/YYYY-MM-DD/...`) continue to work without any prefix change.

### 3.5 Error Handling for Missing Data

| Approach | Pros | Cons |
|----------|------|------|
| Render error message in HTML with HTTP 200 (recommended) | User sees a working page with explanation; no browser error screens | Semantically less precise than 404 |
| Return HTTP 404 with error HTML | Semantically correct for missing summary | Browser may show generic 404 page depending on configuration; less friendly |

**Decision**: HTTP 200 with an inline error message. The page itself exists; only the data is temporarily absent. This matches the Telegram `/admin` behavior which replies with text rather than an error.

---

## 4. Dependency Analysis

| Dependency | Current Status | Needed For | Risk |
|-----------|---------------|------------|------|
| `flask` | Not in project | Web server framework, routing, templating, static file serving | Low — stable, widely used, pure Python |
| `pytz` | Used by `tg_bot/bot.py` and `cams_grabber/snapshot_triage.py` | Timezone-aware freshness check | None — already in project ecosystem |
| `python:3.12-slim` | Used by `tg_bot` | Base Docker image for `web_viewer` | None — consistent with existing services |
| `output/` volume mount | Already in `docker-compose.yml` | File access for JSON and images | None — path updated in compose file |
| `triage_summary.json` schema | Stable (TASK-003/004/005) | `/admin` data source | Low — additive schema with `.get()` defaults |

One new Python package dependency: `flask`.
One new infrastructure change: `web_viewer` build context and updated volume mount in `docker-compose.yml`.

---

## 5. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Flask dev server performance is lower than nginx for static files | Low | Expected traffic is minimal (single admin browsing); if traffic grows, future increment can add gunicorn or nginx reverse proxy without code changes |
| Future changes to `triage_summary.json` schema break `/admin` rendering | Low | Use `.get()` with sensible defaults for every field; document the dependency in design and scope docs |
| Existing bookmarks or integrations depend on nginx-specific behavior (e.g., directory indexing, MIME types) | Low | `send_from_directory` infers MIME types automatically; directory indexing is not a documented feature; validate with smoke tests |
| If `docker-compose.yml` is updated, existing deployments must be recreated for the change to take effect | Low | Document `docker compose up -d --force-recreate web_viewer` in `README.md` |
| Adding a new Python service introduces another container to monitor | Low | Add a simple HTTP healthcheck to the new service in `docker-compose.yml`; container runtime is already monitored by Telegram `/state` |
| Overlapping working-tree changes in `docker-compose.yml` | Medium | This design only touches `web_viewer/` (new), `docker-compose.yml`, `tests/test_web_viewer.py`, and `README.md`; no overlap with pending `tg_bot/` or `cams_grabber/` changes |
| Implementation exceeds one Codex session | Low | Scope is bounded to one route, one HTML template, one static file route, a Dockerfile, and 3–4 focused tests; matches the size of the previous `/admin` Telegram implementation |

---

## 6. Files to Change (Implementation Phase)

| File | Change Type | Description |
|------|-------------|-------------|
| `web_viewer/Dockerfile` | Create | `python:3.12-slim` image installing Flask and running `app.py` |
| `web_viewer/requirements.txt` | Create | Lists `flask` and `pytz` |
| `web_viewer/app.py` | Create | Flask app with `/admin` route, static catch-all route, and helper functions |
| `docker-compose.yml` | Modify | Replace `web_viewer` image with `build: ./web_viewer`; update volume mount; add healthcheck |
| `tests/test_web_viewer.py` | Create | Focused unit tests for `/admin` HTML response, missing/malformed JSON, static file serving, and default counts |
| `README.md` | Modify | Document new web viewer behavior, `/admin` URL, and container recreate step |
| `tg_bot/bot.py` | No change | Explicitly excluded by scope |
| `cams_grabber/snapshot_triage.py` | No change | Explicitly excluded by scope |
| `sys_monitor/monitor.py` | No change | Explicitly excluded by scope |

---

## 7. Validation Plan

1. `python3 -m py_compile web_viewer/app.py tests/test_web_viewer.py` — syntax check on new/modified Python files.
2. Install new dependency in `.venv`: `.venv/bin/python -m pip install flask pytz` — verify install succeeds.
3. Run new unit tests: `.venv/bin/python -m unittest -v tests/test_web_viewer.py` — verify `/admin` HTML contains stats, handles missing JSON, serves static files, and defaults counts to 0.
4. Run existing test suites: `.venv/bin/python -m unittest -v tests/test_snapshot_triage.py` and `.venv/bin/python -m unittest -v tests/test_tg_bot.py` — ensure no regression.
5. Manual smoke test (requires Docker environment):
   - Build and start the new `web_viewer`: `docker compose up -d --build web_viewer`
   - Ensure `output/` contains a dated folder with images and a valid `triage_summary.json`.
   - Navigate to `http://<host>:8082/admin` → verify HTML page shows run date, freshness, image counts, car/person counts, and image links.
   - Navigate to `http://<host>:8082/YYYY-MM-DD/frame.jpg` → verify static image is served correctly (no regression).
   - Remove `triage_summary.json` → verify `/admin` shows error message without crashing.
   - Verify healthcheck passes in `docker ps`.
6. Inspect final Git diff to confirm only `web_viewer/`, `docker-compose.yml`, `tests/test_web_viewer.py`, and `README.md` are changed.
