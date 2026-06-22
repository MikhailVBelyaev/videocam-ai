import os
from datetime import datetime

from flask import Flask, redirect, request, send_from_directory, url_for, Response

app = Flask(__name__)
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/app/output")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
VIDEO_EXTENSIONS = (".mp4",)
PER_PAGE = 20
VIDEO_PER_PAGE = 6

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cameras():
    """Return sorted list of camera dirs (non-date subdirs of OUTPUT_DIR)."""
    try:
        result = []
        for e in sorted(os.listdir(OUTPUT_DIR)):
            if os.path.isdir(os.path.join(OUTPUT_DIR, e)) and not e.startswith('.'):
                try:
                    datetime.strptime(e, "%Y-%m-%d")
                except ValueError:
                    result.append(e)
        return result
    except OSError:
        return []


def _date_dirs(camera):
    base = os.path.join(OUTPUT_DIR, camera)
    try:
        valid = []
        for e in os.listdir(base):
            if os.path.isdir(os.path.join(base, e)):
                try:
                    datetime.strptime(e, "%Y-%m-%d")
                    valid.append(e)
                except ValueError:
                    pass
        return sorted(valid, reverse=True)
    except OSError:
        return []


def _videos_for_date(camera, date_str):
    folder = os.path.join(OUTPUT_DIR, camera, date_str)
    try:
        files = [
            f for f in os.listdir(folder)
            if f.lower().endswith(VIDEO_EXTENSIONS)
            and os.path.isfile(os.path.join(folder, f))
        ]
        files.sort(key=lambda f: os.path.getmtime(os.path.join(folder, f)), reverse=True)
        return files
    except OSError:
        return []


def _images_for_date(camera, date_str):
    folder = os.path.join(OUTPUT_DIR, camera, date_str)
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


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0b0f1a; color: #c9d1e0; font-family: sans-serif; }
nav { background: #141824; padding: 0.75rem 1.5rem; display: flex; gap: 1.5rem; align-items: center; }
nav a { color: #7a8caa; text-decoration: none; font-size: 0.9rem; font-weight: 600;
        padding: 0.35rem 0.7rem; border-radius: 4px; }
nav a:hover, nav a.active { color: #e0e8f5; background: #1e2535; }
.title { padding: 1.2rem 1.5rem 0.5rem; font-size: 1rem; color: #7a8caa;
         display: flex; align-items: center; gap: 1rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        gap: 1rem; padding: 1rem 1.5rem; }
.card { background: #141824; border-radius: 8px; overflow: hidden;
        border: 1px solid #1e2535; transition: border-color 0.2s; }
.card:hover { border-color: #3a4a6a; }
.card img { width: 100%; height: 170px; object-fit: cover; display: block; cursor: pointer; }
.card-body { padding: 0.55rem 0.7rem 0.65rem; font-size: 0.78rem; color: #556070; }
.card-body .fn { color: #8a9ab8; font-size: 0.76rem; word-break: break-all; }
.pager { display: flex; gap: 0.5rem; align-items: center; justify-content: center;
         padding: 1rem 1.5rem 2rem; }
.pager a, .pager span { padding: 0.4rem 0.8rem; border-radius: 4px; font-size: 0.85rem;
                         background: #141824; border: 1px solid #1e2535; color: #7a8caa;
                         text-decoration: none; }
.pager a:hover { background: #1e2535; color: #e0e8f5; }
.pager span { color: #e0e8f5; background: #1e2535; border-color: #3a4a6a; }
.empty { padding: 3rem; text-align: center; color: #556070; }
select { background: #141824; color: #c9d1e0; border: 1px solid #1e2535;
         border-radius: 4px; padding: 0.3rem 0.6rem; font-size: 0.85rem; cursor: pointer; }
#lb { display:none; position:fixed; top:0;left:0;width:100%;height:100%;
      background:rgba(0,0,0,0.88); z-index:999; align-items:center; justify-content:center; }
#lb.open { display:flex; }
#lb img { max-width:95vw; max-height:95vh; border-radius:6px; }
#lb-x { position:fixed; top:1rem; right:1.2rem; color:#fff; font-size:2rem; cursor:pointer; }
"""

_LB_HTML = '<div id="lb" onclick="this.classList.remove(\'open\')"><span id="lb-x" onclick="document.getElementById(\'lb\').classList.remove(\'open\')">&times;</span><img id="lb-img" src=""></div>'
_LB_JS = "document.querySelectorAll('.card img').forEach(i=>i.addEventListener('click',()=>{document.getElementById('lb-img').src=i.src;document.getElementById('lb').classList.add('open')}));"


def _nav(active):
    links = [("Raw", "/raw"), ("Videos", "/videos"), ("Admin", "/admin")]
    out = ""
    for label, href in links:
        cls = "active" if label == active else ""
        out += f'<a href="{href}" class="{cls}">{label}</a>'
    return f"<nav>{out}</nav>"


def _pager(page, total_pages, base):
    if total_pages <= 1:
        return ""
    parts = []
    if page > 1:
        parts.append(f'<a href="{base}&page={page-1}">&#8592; Prev</a>')
    parts.append(f'<span>Page {page} / {total_pages}</span>')
    if page < total_pages:
        parts.append(f'<a href="{base}&page={page+1}">Next &#8594;</a>')
    return f'<div class="pager">{"".join(parts)}</div>'


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("raw_gallery"))


@app.route("/raw")
def raw_gallery():
    cameras = _cameras()
    selected_cam = request.args.get("camera", cameras[0] if cameras else "")
    dates = _date_dirs(selected_cam) if selected_cam else []
    selected = request.args.get("date", dates[0] if dates else "")
    page = max(1, int(request.args.get("page", 1)))

    all_images = _images_for_date(selected_cam, selected) if selected_cam and selected else []
    total = len(all_images)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)
    page_images = all_images[(page - 1) * PER_PAGE: page * PER_PAGE]

    cam_opts = "".join(
        f'<option value="{c}" {"selected" if c == selected_cam else ""}>{c}</option>'
        for c in cameras
    )
    cam_sel = f'<select onchange="location=\'/raw?camera=\'+this.value">{cam_opts}</select>'
    date_opts = "".join(
        f'<option value="{d}" {"selected" if d == selected else ""}>{d}</option>'
        for d in dates
    )
    date_sel = f'<select onchange="location=\'/raw?camera={selected_cam}&date=\'+this.value">{date_opts}</select>'

    cards = ""
    for fname in page_images:
        img_url = f"/{selected_cam}/{selected}/{fname}"
        ts = fname[6:25] if len(fname) > 25 else fname
        cards += f"""
        <div class="card">
          <img src="{img_url}" alt="{fname}" loading="lazy">
          <div class="card-body">
            <div>{ts}</div>
            <div class="fn">{fname}</div>
          </div>
        </div>"""

    if not cards:
        cards = '<div class="empty">No images for this date.</div>'

    pager = _pager(page, total_pages, f"/raw?camera={selected_cam}&date={selected}&x=1")
    selectors = f"{cam_sel} &nbsp; {date_sel}" if len(cameras) > 1 else date_sel

    return Response(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Raw — videocam-ai</title>
<style>{_CSS}</style></head><body>
{_nav("Raw")}
<div class="title"><span>All captures — {total} frames for {selected}</span>{selectors}</div>
<div class="grid">{cards}</div>
{pager}
{_LB_HTML}
<script>{_LB_JS}</script>
</body></html>""", mimetype="text/html")


@app.route("/videos")
def videos_page():
    cameras = _cameras()
    selected_cam = request.args.get("camera", cameras[0] if cameras else "")
    dates = _date_dirs(selected_cam) if selected_cam else []
    selected = request.args.get("date", dates[0] if dates else "")
    page = max(1, int(request.args.get("page", 1)))

    all_videos = _videos_for_date(selected_cam, selected) if selected_cam and selected else []
    total = len(all_videos)
    total_pages = max(1, (total + VIDEO_PER_PAGE - 1) // VIDEO_PER_PAGE)
    page = min(page, total_pages)
    page_videos = all_videos[(page - 1) * VIDEO_PER_PAGE: page * VIDEO_PER_PAGE]

    cam_opts = "".join(
        f'<option value="{c}" {"selected" if c == selected_cam else ""}>{c}</option>'
        for c in cameras
    )
    cam_sel = f'<select onchange="location=\'/videos?camera=\'+this.value">{cam_opts}</select>'
    date_opts = "".join(
        f'<option value="{d}" {"selected" if d == selected else ""}>{d}</option>'
        for d in dates
    )
    date_sel = f'<select onchange="location=\'/videos?camera={selected_cam}&date=\'+this.value">{date_opts}</select>'

    cards = ""
    for fname in page_videos:
        video_url = f"/{selected_cam}/{selected}/{fname}"
        ts = fname[5:24] if len(fname) > 24 else fname
        size_bytes = os.path.getsize(os.path.join(OUTPUT_DIR, selected_cam, selected, fname))
        size_mb = f"{size_bytes / 1_048_576:.1f} MB"
        cards += f"""
        <div class="card">
          <video controls preload="metadata"
            style="width:100%;height:170px;object-fit:cover;background:#000;display:block">
            <source src="{video_url}" type="video/mp4">
          </video>
          <div class="card-body">
            <div>{ts} &nbsp;·&nbsp; {size_mb}</div>
            <div class="fn">{fname}</div>
          </div>
        </div>"""

    if not cards:
        cards = '<div class="empty">No video clips for this date.</div>'

    pager = _pager(page, total_pages, f"/videos?camera={selected_cam}&date={selected}&x=1")
    selectors = f"{cam_sel} &nbsp; {date_sel}" if len(cameras) > 1 else date_sel

    return Response(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Videos — videocam-ai</title>
<style>{_CSS}</style></head><body>
{_nav("Videos")}
<div class="title"><span>Clips — {total} videos for {selected}</span>{selectors}</div>
<div class="grid">{cards}</div>
{pager}
</body></html>""", mimetype="text/html")


@app.route("/admin")
def admin_page():
    cameras = _cameras()
    latest_cam = cameras[0] if cameras else None
    dates = _date_dirs(latest_cam) if latest_cam else []
    latest = dates[0] if dates else None
    imgs = _images_for_date(latest_cam, latest)[:5] if latest_cam and latest else []
    links = "".join(
        f'<li><a href="/{latest_cam}/{latest}/{f}" style="color:#4a8cdf">{f}</a></li>'
        for f in imgs
    ) or "<li>No images</li>"

    return Response(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Admin — videocam-ai</title>
<style>{_CSS} .a{{padding:1.5rem;max-width:600px}} .a h2{{color:#c9d1e0;margin:1rem 0 0.4rem;font-size:1rem}} .a ul{{padding-left:1.2rem;font-size:0.85rem}}</style></head><body>
{_nav("Admin")}
<div class="a">
  <h2>Latest date: {latest or "none"}</h2>
  <h2>Latest captures</h2>
  <ul>{links}</ul>
</div>
</body></html>""", mimetype="text/html")


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(OUTPUT_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
