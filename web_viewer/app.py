import json
import os
from datetime import datetime, timedelta

import pytz
import requests as http
from flask import Flask, redirect, request, send_from_directory, url_for, Response

app = Flask(__name__)
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")
QA_BASE = os.getenv("QA_SERVICE_URL", "http://qa_service:5001")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
RAW_PER_PAGE = 20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_dirs():
    """Return sorted list of YYYY-MM-DD directories, newest first."""
    try:
        entries = os.listdir(OUTPUT_DIR)
        valid = []
        for e in entries:
            if os.path.isdir(os.path.join(OUTPUT_DIR, e)):
                try:
                    datetime.strptime(e, "%Y-%m-%d")
                    valid.append(e)
                except ValueError:
                    pass
        return sorted(valid, reverse=True)
    except OSError:
        return []


def _images_for_date(date_str):
    """Return clean frames for a date, newest first (skips *_debug.jpg)."""
    folder = os.path.join(OUTPUT_DIR, date_str)
    try:
        files = [
            f for f in os.listdir(folder)
            if f.lower().endswith(IMAGE_EXTENSIONS)
            and not f.endswith("_debug.jpg")
            and os.path.isfile(os.path.join(folder, f))
        ]
        files.sort(key=lambda f: os.path.getmtime(os.path.join(folder, f)), reverse=True)
        return files
    except OSError:
        return []


def _date_from_filename(filename):
    """Extract YYYY-MM-DD from frame filename."""
    try:
        return filename[6:16]
    except Exception:
        return None


def _nav(active):
    links = [
        ("Gallery", "/gallery"),
        ("Raw",     "/raw"),
        ("Admin",   "/admin"),
    ]
    items = ""
    for label, href in links:
        cls = "active" if label == active else ""
        items += f'<a href="{href}" class="{cls}">{label}</a>'
    return f'<nav>{items}</nav>'


_BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0b0f1a; color: #c9d1e0; font-family: sans-serif; }
nav { background: #141824; padding: 0.75rem 1.5rem; display: flex; gap: 1.5rem; align-items: center; }
nav a { color: #7a8caa; text-decoration: none; font-size: 0.9rem; font-weight: 600;
        padding: 0.35rem 0.7rem; border-radius: 4px; }
nav a:hover { color: #e0e8f5; background: #1e2535; }
nav a.active { color: #e0e8f5; background: #1e2535; }
.page-title { padding: 1.2rem 1.5rem 0.5rem; font-size: 1.1rem; color: #7a8caa; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 1rem; padding: 1rem 1.5rem; }
.card { background: #141824; border-radius: 8px; overflow: hidden;
        border: 1px solid #1e2535; transition: border-color 0.2s; }
.card:hover { border-color: #3a4a6a; }
.card img { width: 100%; height: 180px; object-fit: cover; display: block; cursor: pointer; }
.card-body { padding: 0.6rem 0.75rem 0.75rem; font-size: 0.78rem; color: #7a8caa; }
.card-body .title { color: #c9d1e0; font-weight: 600; margin-bottom: 0.3rem; font-size: 0.82rem; }
.badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 3px;
         font-size: 0.72rem; font-weight: 700; margin-bottom: 0.3rem; }
.badge.PASS { background: #1a3a2a; color: #4caf87; }
.badge.WARN { background: #3a2a10; color: #c8962a; }
.badge.FAIL { background: #3a1a1a; color: #c84040; }
.meta { color: #556070; margin-top: 0.2rem; }
.pager { display: flex; gap: 0.5rem; align-items: center; justify-content: center;
         padding: 1rem 1.5rem 2rem; flex-wrap: wrap; }
.pager a, .pager span { padding: 0.4rem 0.8rem; border-radius: 4px; font-size: 0.85rem;
                         background: #141824; border: 1px solid #1e2535; color: #7a8caa;
                         text-decoration: none; }
.pager a:hover { background: #1e2535; color: #e0e8f5; }
.pager span.cur { background: #1e2535; color: #e0e8f5; border-color: #3a4a6a; }
.empty { padding: 3rem 1.5rem; text-align: center; color: #556070; }
.lightbox { display:none; position:fixed; top:0;left:0;width:100%;height:100%;
            background:rgba(0,0,0,0.88); z-index:999; align-items:center; justify-content:center; }
.lightbox.open { display:flex; }
.lightbox img { max-width:95vw; max-height:95vh; border-radius:6px; }
.lightbox-close { position:fixed; top:1rem; right:1.2rem; color:#fff; font-size:2rem;
                  cursor:pointer; line-height:1; }
select { background:#141824; color:#c9d1e0; border:1px solid #1e2535; border-radius:4px;
         padding:0.35rem 0.6rem; font-size:0.85rem; cursor:pointer; }
"""

_LIGHTBOX_JS = """
const lb = document.getElementById('lb');
const lbImg = document.getElementById('lb-img');
document.querySelectorAll('.card img').forEach(img => {
  img.addEventListener('click', () => {
    lbImg.src = img.dataset.full || img.src;
    lb.classList.add('open');
  });
});
document.getElementById('lb-close').addEventListener('click', () => lb.classList.remove('open'));
lb.addEventListener('click', e => { if (e.target === lb) lb.classList.remove('open'); });
"""

_LIGHTBOX_HTML = """
<div class="lightbox" id="lb">
  <span class="lightbox-close" id="lb-close">&times;</span>
  <img id="lb-img" src="" alt="">
</div>
"""


def _pager_html(page, total_pages, base_url):
    if total_pages <= 1:
        return ""
    parts = []
    if page > 1:
        parts.append(f'<a href="{base_url}&page={page-1}">&#8592; Prev</a>')
    parts.append(f'<span class="cur">Page {page} / {total_pages}</span>')
    if page < total_pages:
        parts.append(f'<a href="{base_url}&page={page+1}">Next &#8594;</a>')
    return f'<div class="pager">{"".join(parts)}</div>'


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("gallery_page"))


@app.route("/gallery")
def gallery_page():
    page = max(1, int(request.args.get("page", 1)))
    try:
        resp = http.get(f"{QA_BASE}/api/gallery?page={page}&status=PASS", timeout=4)
        data = resp.json()
    except Exception:
        data = {"items": [], "page": 1, "total_pages": 1, "total": 0}

    items = data.get("items", [])
    total = data.get("total", 0)
    total_pages = data.get("total_pages", 1)
    cur_page = data.get("page", page)

    cards = ""
    for r in items:
        fname = r.get("filename", "")
        date = _date_from_filename(fname)
        img_url = f"/{date}/{fname}" if date else "#"
        status = r.get("status", "PASS")
        tid = r.get("tracking_id", "?")
        dets = ", ".join(
            f'{d["class"]} {int(d["conf"]*100)}%' for d in r.get("detections", [])
        ) or "—"
        blur = r.get("blur", 0)
        ts = fname[6:25] if len(fname) > 25 else fname

        cards += f"""
        <div class="card">
          <img src="{img_url}" data-full="{img_url}" alt="{fname}" loading="lazy">
          <div class="card-body">
            <div class="title">ID {tid} &mdash; {ts}</div>
            <span class="badge {status}">{status}</span>
            <div class="meta">Objects: {dets}</div>
            <div class="meta">Blur: {blur:.0f}</div>
          </div>
        </div>"""

    if not cards:
        cards = '<div class="empty">No good-quality frames yet — check back soon.</div>'

    pager = _pager_html(cur_page, total_pages, "/gallery?x=1")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Gallery &mdash; videocam-ai</title>
  <style>{_BASE_CSS}</style>
</head>
<body>
{_nav("Gallery")}
<div class="page-title">Good-quality captures &mdash; {total} frames</div>
<div class="grid">{cards}</div>
{pager}
{_LIGHTBOX_HTML}
<script>{_LIGHTBOX_JS}</script>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/raw")
def raw_gallery():
    dates = _date_dirs()
    selected = request.args.get("date", dates[0] if dates else "")
    page = max(1, int(request.args.get("page", 1)))

    all_images = _images_for_date(selected) if selected else []
    total = len(all_images)
    total_pages = max(1, (total + RAW_PER_PAGE - 1) // RAW_PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * RAW_PER_PAGE
    page_images = all_images[start:start + RAW_PER_PAGE]

    date_opts = "".join(
        f'<option value="{d}" {"selected" if d == selected else ""}>{d}</option>'
        for d in dates
    )
    date_sel = f'<select onchange="location=\'/raw?date=\'+this.value">{date_opts}</select>'

    cards = ""
    for fname in page_images:
        img_url = f"/{selected}/{fname}"
        ts = fname[6:25] if len(fname) > 25 else fname
        cards += f"""
        <div class="card">
          <img src="{img_url}" data-full="{img_url}" alt="{fname}" loading="lazy">
          <div class="card-body">
            <div class="title">{ts}</div>
            <div class="meta">{fname}</div>
          </div>
        </div>"""

    if not cards:
        cards = '<div class="empty">No images found for this date.</div>'

    base_url = f"/raw?date={selected}&x=1"
    pager = _pager_html(page, total_pages, base_url)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Raw Gallery &mdash; videocam-ai</title>
  <style>{_BASE_CSS}</style>
</head>
<body>
{_nav("Raw")}
<div class="page-title" style="display:flex;align-items:center;gap:1rem;">
  <span>All captures &mdash; {total} frames</span>
  {date_sel}
</div>
<div class="grid">{cards}</div>
{pager}
{_LIGHTBOX_HTML}
<script>{_LIGHTBOX_JS}</script>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/admin")
def admin_page():
    dates = _date_dirs()
    latest = dates[0] if dates else None
    imgs = _images_for_date(latest)[:5] if latest else []
    links_html = "".join(
        f'<li><a href="/{latest}/{f}">{f}</a></li>' for f in imgs
    ) or "<li>No images</li>"
    try:
        stats = http.get(f"{QA_BASE}/api/stats", timeout=3).json()
        w1h = next((w for w in stats.get("windows", []) if w["minutes"] == 60), {})
        qa_html = f"""
        <p><strong>Last hour:</strong> {w1h.get('total', '?')} frames &mdash;
           PASS {w1h.get('passes', '?')} / WARN {w1h.get('warns', '?')} / FAIL {w1h.get('fails', '?')}
           ({w1h.get('rate', '?')}% quality)</p>"""
    except Exception:
        qa_html = "<p>QA service not reachable.</p>"

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Admin &mdash; videocam-ai</title>
  <style>{_BASE_CSS}
    .admin {{ padding: 1.5rem; max-width: 640px; }}
    .admin h2 {{ color: #c9d1e0; margin: 1.2rem 0 0.5rem; font-size: 1rem; }}
    .admin p {{ margin: 0.3rem 0; font-size: 0.9rem; }}
    .admin ul {{ padding-left: 1.2rem; font-size: 0.85rem; }}
    .admin a {{ color: #4a8cdf; }}
  </style>
</head>
<body>
{_nav("Admin")}
<div class="admin">
  <h2>Latest date: {latest or "none"}</h2>
  {qa_html}
  <h2>Latest captures</h2>
  <ul>{links_html}</ul>
</div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(OUTPUT_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
