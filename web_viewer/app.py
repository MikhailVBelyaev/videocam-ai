import json
import os
from datetime import datetime, timedelta

import pytz
from flask import Flask, send_from_directory

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
            [
                f
                for f in os.listdir(folder)
                if f.lower().endswith(IMAGE_EXTENSIONS)
                and os.path.isfile(os.path.join(folder, f))
            ],
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

    links_html = (
        "\n".join(f'<li><a href="{l}">{l}</a></li>' for l in links)
        if links
        else "<li>No images found</li>"
    )
    error_html = (
        "<p style='color:red'>No triage data available.</p>"
        if summary is None
        else ""
    )

    return f"""<!doctype html>
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
