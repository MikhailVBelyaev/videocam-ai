# Web Viewer Admin Page Scope (TASK-001)

Job ID: 2026-06-19_060847_videocam-ai-change-admin-add-web-server-page-with-cars-and-task-001
Project: videocam-ai
Status: review_required
Last updated: 2026-06-19

## Problem Statement

The `web_viewer` service currently serves static camera output files via nginx, but
there is no browser-accessible admin dashboard showing object detection statistics,
recent processing activity, or latest media. The original request asks for a web
server `/admin` page with "cars and people statistics, latest images, latest videos,
and service status."

## Current Baseline

- `docker-compose.yml` defines `web_viewer` as `nginx:alpine` serving
  `./output:/usr/share/nginx/html:ro` on host port `8082`.
- `cams_grabber/snapshot_triage.py` produces `output/triage_summary.json` with:
  - `total_images`, `kept_images`
  - `total_objects_by_type` (e.g., `car`, `person` counts)
  - `missing_expected_objects`
- `output/` also contains dated subfolders (`YYYY-MM-DD/`) with images, videos,
  `triage_report.csv`, `kept_timelapse.mp4`, and `rejected/` copies.
- Telegram `/admin` already consumes `triage_summary.json` and returns a formatted
  text summary; Telegram `/state` returns container runtime status.
- No dynamic web application or HTML rendering currently exists in the project.

## Minimum Deliverable

One reviewable implementation increment, achievable in a single Codex session,
that adds a browser-accessible `/admin` page to the web viewer and preserves
existing static-file serving.

Included:
1. Replace the `web_viewer` nginx service with a minimal Python web server
   (e.g., Flask or FastAPI) running in its own Docker image, or add a new
   lightweight Python service alongside nginx if preserving nginx is simpler.
   The chosen approach must still serve static files from `output/` on the
   existing path (e.g., `/YYYY-MM-DD/...`) so existing bookmarks and Telegram
   links continue to work.
2. Add an `/admin` endpoint that reads the latest `output/triage_summary.json`
   and renders a simple HTML page containing:
   - Latest run date (from most recent `YYYY-MM-DD` folder name in `output/`)
   - Freshness indicator (whether latest folder is within last 24h)
   - `total_images` and `kept_images`
   - `car_count` and `person_count` from `total_objects_by_type`
   - `missing_expected_objects` count (if any)
   - Links to the latest image file(s) in the most recent dated folder
3. If `triage_summary.json` is missing or malformed, render a concise error
   message in the HTML instead of crashing.
4. Update `docker-compose.yml` to use the new web viewer service (image, build
   context, ports, and volume mounts).
5. Add one focused test validating the `/admin` HTML response and data parsing
   logic (e.g., that car/person counts appear when present and default to 0
   when absent).
6. Update `README.md` with the new web viewer behavior, any new env vars or
   configuration, and the `/admin` URL.

## Measurable Acceptance Criteria

- Navigating to `http://<host>:8082/admin` renders an HTML page containing at
  least `total_images`, `kept_images`, `car_count`, `person_count` from the
  latest `triage_summary.json`.
- If `triage_summary.json` is missing or malformed, the page renders a clear
  error message and returns HTTP 200 (or 404 if explicitly chosen) without
  crashing the server.
- Existing static-file URLs (e.g., `http://<host>:8082/2026-06-19/frame.jpg`)
  continue to work (no regression).
- The `/admin` page includes clickable links to at least one latest image from
  the most recent dated folder.
- A new or existing test validates the `/admin` response HTML and data parsing.
- `py_compile` passes on all modified Python files.

## Explicit Exclusions

- No container/service status display on the web `/admin` page (this remains the
  domain of the Telegram `/state` command; a future increment may add it).
- No video player or streaming interface; video files may be linked as static
  downloads but are not embedded or played inline.
- No authentication, authorization, or session management; the `/admin` page is
  assumed to run on a trusted internal network.
- No real-time updates, WebSockets, or server-sent events; the page is a
  static snapshot rendered on request.
- No database, persistent log store, or caching layer.
- No REST API or JSON endpoint for `/admin`; only HTML rendering is required.
- No changes to `tg_bot/bot.py`, `cams_grabber/snapshot_triage.py`,
  `sys_monitor/monitor.py`, or `cams_grabber/main_ssh.py`.
- No object detection model changes or new detection classes.
- No deployment scripts or host-specific configuration outside
  `docker-compose.yml`.
- No CSS frameworks or complex styling; inline styles or a single small
  `<style>` block are acceptable.

## Assumptions

- The web viewer continues to run inside Docker Compose on the same host as the
  other services.
- `output/` is available via volume mount at a known path inside the web viewer
  container.
- `triage_summary.json` schema remains stable (additive changes are acceptable
  if the parser uses `.get()` with defaults).
- Browser access to port `8082` is internal and trusted; no auth is required.
- The existing dated-folder naming convention (`YYYY-MM-DD`) remains stable.
- A lightweight Python web framework (Flask, FastAPI, or similar) is acceptable
  to add to the project dependencies.

## Risks

- Replacing nginx with a Python web server may increase memory/CPU usage and
  reduce static-file serving performance. Mitigation: keep the app minimal; if
  performance becomes an issue, a future increment can add nginx as a reverse
  proxy or revert to nginx + a separate admin microservice.
- Future changes to `triage_summary.json` schema may break `/admin` rendering.
  Mitigation: use `.get()` with sensible defaults and document the dependency.
- If `docker-compose.yml` is updated, existing deployments must be recreated
  (`docker compose up -d --force-recreate web_viewer`) for the change to take
  effect. Mitigation: document the requirement in `README.md`.
- Adding a new Python service introduces another container to monitor and
  maintain. Mitigation: add a simple healthcheck to the new service in
  `docker-compose.yml`.
