# Web Viewer Runbook

## Purpose

Operate the `web_viewer` service that serves static camera output files and
provides a browser-accessible `/admin` dashboard with triage statistics and
latest images.

## Configuration

The `web_viewer` service is defined in `docker-compose.yml`:

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
    test:
      [
        "CMD",
        "python",
        "-c",
        "import urllib.request; urllib.request.urlopen('http://localhost:5000/admin')",
      ]
    interval: 30s
    timeout: 10s
    retries: 3
```

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTPUT_DIR` | `/app/output` | Path to the output directory inside the container |

The `OUTPUT_DIR` is set via the volume mount and does not normally need to be
changed.

## Endpoints

### `GET /admin`

Returns an HTML dashboard containing:

- **Latest run date** — from the most recent `YYYY-MM-DD` folder in `output/`
- **Freshness indicator** — `Fresh (within 24h)` or `Stale`
- **Image counts** — total and kept images from `triage_summary.json`
- **Object counts** — car and person counts from `total_objects_by_type`
- **Missing expected objects** — count of frames missing expected objects (if any)
- **Latest images** — clickable links to up to 5 most recent images in the latest
  dated folder

If `output/triage_summary.json` is missing or malformed, the page renders a
concise error message (`No triage data available.`) with zeroed counts and
continues to show the latest run date and image links when available.

The page uses inline CSS and requires no external assets.

### Static files

Any path other than `/admin` is served as a static file from `output/`.

Examples:

- `http://<host>:8082/2026-06-19/frame.jpg`
- `http://<host>:8082/2026-06-19/triage_report.csv`
- `http://<host>:8082/2026-06-19/kept_timelapse.mp4`

This preserves existing bookmarks and Telegram links.

## Local Development

Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r web_viewer/requirements.txt
```

Run the development server:

```bash
OUTPUT_DIR=./output .venv/bin/python web_viewer/app.py
```

The server listens on `http://localhost:5000`.

Visit:

- `http://localhost:5000/admin` — dashboard
- `http://localhost:5000/<date>/<file>` — static files

## Docker Compose Operation

Build and start the service:

```bash
docker compose up -d --build web_viewer
```

After updating `docker-compose.yml`, recreate the container:

```bash
docker compose up -d --force-recreate web_viewer
```

View logs:

```bash
docker compose logs -f web_viewer
```

Check health:

```bash
docker ps --filter name=web_viewer
```

## Validation

Syntax check:

```bash
.venv/bin/python -m py_compile web_viewer/app.py tests/test_web_viewer.py
```

Run focused tests:

```bash
.venv/bin/python -m unittest -v tests/test_web_viewer.py
```

Run full test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Expected results:
- 28 web_viewer tests pass
- 47 tg_bot tests pass
- 52 snapshot triage tests pass
- `py_compile` clean on all modified Python files

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/admin` shows "No triage data available" | `triage_summary.json` missing or malformed | Run `cams_grabber/snapshot_triage.py` to generate the summary |
| `/admin` shows "Unknown" run date | No `YYYY-MM-DD` folders in `output/` | Ensure the triage pipeline has run and created dated folders |
| Static image URLs return 404 | File does not exist in `output/` or path is wrong | Verify the dated folder and file names |
| Healthcheck failing | Flask app not starting or `/admin` crashing | Check `docker compose logs web_viewer` for traceback |
| Port 8082 already in use | Another service is bound to the host port | Stop the conflicting service or change the port mapping in `docker-compose.yml` |
| Old nginx container still running | Container was not recreated after compose change | Run `docker compose up -d --force-recreate web_viewer` |
