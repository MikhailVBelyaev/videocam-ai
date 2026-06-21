import cv2
import re
import sys
import time
import threading
import logging
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque

import imagehash
from PIL import Image
from flask import Flask, jsonify, send_file, abort, Response, request
from ultralytics import YOLO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
logging.getLogger("ultralytics").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path("/app/output")
POLL_INTERVAL = 2.0
PRELOAD_RECENT = 50       # seed stats log on startup

BLUR_THRESHOLD = 30.0
GRADIENT_THRESHOLD = 5.0
BRIGHTNESS_MIN = 15.0
BRIGHTNESS_MAX = 245.0
SAME_ID_DUP_THRESHOLD = 5
CONF_THRESHOLD = 0.35

TARGET_CLASSES = {"car", "truck", "bus", "person", "motorbike", "bicycle"}
VEHICLE_CLASSES = {"car", "truck", "bus", "motorbike"}

_ID_RE = re.compile(r"_id(\d+)_")

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
# stats_log keeps all results for time-window analysis (24h ~ 5000 frames max)
stats_log: deque = deque(maxlen=5000)
results_lock = threading.Lock()
processed_count = 0
pass_count = 0
_id_last_hash: dict = {}

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------

def _blur_score(img: np.ndarray) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _gradient_score(img: np.ndarray) -> float:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gx, gy = np.gradient(gray.astype(np.float64))
    return float(np.sqrt(gx**2 + gy**2).var())


def _brightness(img: np.ndarray) -> float:
    return float(np.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))


def _phash(img: np.ndarray) -> imagehash.ImageHash:
    return imagehash.average_hash(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))


# ---------------------------------------------------------------------------
# Frame analysis
# ---------------------------------------------------------------------------

def analyze(img_path: Path, model: YOLO) -> dict:
    img = cv2.imread(str(img_path))
    if img is None:
        return {
            "filename": img_path.name,
            "rel_path": str(img_path.relative_to(OUTPUT_DIR)),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "status": "FAIL",
            "issues": ["unreadable image"],
            "blur": 0.0, "gradient": 0.0, "brightness": 0.0,
            "hash_distance": None, "is_different": None,
            "tracking_id": None, "detections": [],
        }

    blur = _blur_score(img)
    gradient = _gradient_score(img)
    brightness = _brightness(img)

    m = _ID_RE.search(img_path.name)
    tracking_id = int(m.group(1)) if m else None

    ph = _phash(img)
    prev_hash = _id_last_hash.get(tracking_id) if tracking_id is not None else None
    hash_distance = int(ph - prev_hash) if prev_hash is not None else None
    no_change = (hash_distance is not None) and (hash_distance <= SAME_ID_DUP_THRESHOLD)
    _id_last_hash[tracking_id] = ph

    yolo_results = model.predict(img, verbose=False, device=0, conf=CONF_THRESHOLD)
    detections = []
    for box in yolo_results[0].boxes:
        cls_name = yolo_results[0].names[int(box.cls[0])]
        conf = float(box.conf[0])
        if cls_name in TARGET_CLASSES:
            detections.append({"class": cls_name, "conf": round(conf, 2)})

    has_object = len(detections) > 0

    issues = []
    if blur < BLUR_THRESHOLD:
        issues.append(f"blurry (blur={blur:.0f})")
    if gradient < GRADIENT_THRESHOLD:
        issues.append(f"corrupt/flat (gradient={gradient:.1f})")
    if brightness < BRIGHTNESS_MIN:
        issues.append(f"too dark (brightness={brightness:.0f})")
    elif brightness > BRIGHTNESS_MAX:
        issues.append(f"overexposed (brightness={brightness:.0f})")
    if not has_object:
        issues.append("no target object visible")
    if no_change:
        issues.append(f"no change since last capture (Δhash={hash_distance})")

    quality_fail = not has_object or blur < BLUR_THRESHOLD or gradient < GRADIENT_THRESHOLD

    if quality_fail:
        status = "FAIL"
    elif issues:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "filename": img_path.name,
        "rel_path": str(img_path.relative_to(OUTPUT_DIR)),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "issues": issues,
        "blur": round(blur, 1),
        "gradient": round(gradient, 1),
        "brightness": round(brightness, 1),
        "hash_distance": hash_distance,
        "is_different": not no_change,
        "tracking_id": tracking_id,
        "detections": detections,
    }


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def _compute_window(results: list, minutes: int) -> dict:
    cutoff = datetime.now() - timedelta(minutes=minutes)
    window = [r for r in results
              if datetime.fromisoformat(r["timestamp"]) >= cutoff]
    total = len(window)
    vehicles = sum(1 for r in window
                   if any(d["class"] in VEHICLE_CLASSES for d in r.get("detections", [])))
    people = sum(1 for r in window
                 if any(d["class"] == "person" for d in r.get("detections", [])))
    passes = sum(1 for r in window if r["status"] == "PASS")
    warns  = sum(1 for r in window if r["status"] == "WARN")
    fails  = sum(1 for r in window if r["status"] == "FAIL")
    rate = round(passes / total * 100) if total else 0
    return dict(minutes=minutes, total=total, vehicles=vehicles, people=people,
                passes=passes, warns=warns, fails=fails, rate=rate)


# ---------------------------------------------------------------------------
# Directory watcher
# ---------------------------------------------------------------------------

def _image_files(seen: set) -> list:
    files = []
    try:
        for date_dir in sorted(OUTPUT_DIR.iterdir()):
            if not date_dir.is_dir():
                continue
            try:
                datetime.strptime(date_dir.name, "%Y-%m-%d")
            except ValueError:
                continue
            for f in sorted(date_dir.iterdir()):
                if (
                    f.is_file()
                    and f.suffix.lower() in {".jpg", ".jpeg", ".png"}
                    and not f.name.startswith(".")
                    and "_debug" not in f.name
                    and str(f) not in seen
                ):
                    files.append(f)
    except OSError:
        pass
    return files


def watcher(model: YOLO):
    global processed_count, pass_count
    seen: set = set()

    all_existing = _image_files(set())
    preload = all_existing[-PRELOAD_RECENT:] if len(all_existing) > PRELOAD_RECENT else all_existing
    for f in all_existing:
        seen.add(str(f))

    logger.info("Pre-seeding with %d recent frames...", len(preload))
    for img_path in preload:
        try:
            result = analyze(img_path, model)
            with results_lock:
                stats_log.append(result)
                processed_count += 1
                if result["status"] == "PASS":
                    pass_count += 1
        except Exception as e:
            logger.error("Preload error %s: %s", img_path.name, e)

    logger.info("Watcher active — monitoring %s", OUTPUT_DIR)

    while True:
        new_files = _image_files(seen)
        for img_path in new_files:
            seen.add(str(img_path))
            try:
                result = analyze(img_path, model)
                with results_lock:
                    stats_log.append(result)
                    processed_count += 1
                    if result["status"] == "PASS":
                        pass_count += 1
                logger.info(
                    "%s → %s  blur=%.0f  bright=%.0f  obj=%s",
                    img_path.name, result["status"],
                    result["blur"], result["brightness"],
                    [d["class"] for d in result["detections"]],
                )
            except Exception as e:
                logger.error("Error on %s: %s", img_path.name, e)
        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route("/img/<path:rel>")
def serve_img(rel):
    p = OUTPUT_DIR / rel
    if not p.is_file():
        abort(404)
    return send_file(str(p))


@app.route("/api/stats")
def api_stats():
    with results_lock:
        data = list(stats_log)
        total = processed_count
        passes = pass_count
    windows = [_compute_window(data, m) for m in [10, 60, 360, 720, 1440]]
    return jsonify({"windows": windows, "total": total, "pass_count": passes})


@app.route("/api/gallery")
def api_gallery():
    page = max(1, int(request.args.get("page", 1)))
    status_filter = request.args.get("status", "").upper() or None
    per_page = 5
    with results_lock:
        items = list(stats_log)
    items.reverse()   # newest first
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_items = items[start:start + per_page]
    return jsonify({"items": page_items, "page": page,
                    "total_pages": total_pages, "total": total})


@app.route("/")
def index():
    return Response(PAGE_HTML, mimetype="text/html")


# ---------------------------------------------------------------------------
# HTML — two-tab SPA
# ---------------------------------------------------------------------------

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Camera QA</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0b0f1a;color:#d1d5db;min-height:100vh}

/* ── Header ── */
header{
  background:#111827;padding:12px 20px;
  display:flex;align-items:center;justify-content:space-between;
  border-bottom:1px solid #1f2937;position:sticky;top:0;z-index:20
}
h1{font-size:1rem;color:#60a5fa;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.2}}
#upd{font-size:.72rem;color:#4b5563}

/* ── Tabs ── */
nav{display:flex;gap:0;border-bottom:1px solid #1f2937;background:#111827}
.tab-btn{
  padding:10px 24px;font-size:.85rem;font-weight:600;border:none;
  background:none;color:#6b7280;cursor:pointer;border-bottom:2px solid transparent;
  transition:color .2s,border-color .2s
}
.tab-btn.active{color:#60a5fa;border-bottom-color:#60a5fa}
.tab-btn:hover{color:#93c5fd}

/* ── Dashboard ── */
#tab-dashboard{padding:16px 20px}

/* Quick summary cards */
.summary-row{
  display:grid;
  grid-template-columns:repeat(5,1fr);
  gap:10px;margin-bottom:20px
}
.scard{
  background:#111827;border:1px solid #1f2937;border-radius:8px;
  padding:12px 14px;text-align:center
}
.scard .period{font-size:.68rem;color:#6b7280;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
.scard .big{font-size:1.6rem;font-weight:700;color:#e5e7eb;line-height:1}
.scard .sub{font-size:.7rem;color:#6b7280;margin-top:4px}
.scard .pills{display:flex;justify-content:center;gap:5px;margin-top:8px;flex-wrap:wrap}
.pill{font-size:.65rem;font-weight:700;padding:2px 7px;border-radius:20px}
.pill.p{background:#14532d;color:#86efac}
.pill.w{background:#7c2d12;color:#fdba74}
.pill.f{background:#7f1d1d;color:#fca5a5}
.rate-bar{height:4px;border-radius:2px;background:#1f2937;margin-top:8px;overflow:hidden}
.rate-bar-fill{height:100%;border-radius:2px;background:#22c55e;transition:width .5s}

/* Stats table */
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.82rem}
thead th{
  background:#1f2937;color:#9ca3af;font-weight:600;
  padding:10px 14px;text-align:left;
  border-bottom:1px solid #374151;white-space:nowrap
}
tbody tr{border-bottom:1px solid #1f2937;transition:background .15s}
tbody tr:hover{background:#111827}
td{padding:10px 14px;vertical-align:middle}
td.num{text-align:right;font-variant-numeric:tabular-nums;color:#e5e7eb}
td.period-cell{font-weight:600;color:#93c5fd}
.rate-cell{font-weight:700}
.rate-good{color:#4ade80}
.rate-mid{color:#facc15}
.rate-bad{color:#f87171}
.count-v{color:#93c5fd}
.count-p{color:#c4b5fd}
.count-pass{color:#4ade80}
.count-warn{color:#fb923c}
.count-fail{color:#f87171}

/* ── Gallery ── */
#tab-gallery{padding:16px 20px}
.pager{
  display:flex;align-items:center;justify-content:center;
  gap:12px;margin-bottom:14px;flex-wrap:wrap
}
.pager-btn{
  background:#1f2937;border:1px solid #374151;color:#d1d5db;
  padding:6px 16px;border-radius:6px;cursor:pointer;font-size:.82rem;
  transition:background .15s
}
.pager-btn:hover:not(:disabled){background:#374151}
.pager-btn:disabled{opacity:.35;cursor:default}
.pager-info{font-size:.82rem;color:#9ca3af}
.pager-jump{display:flex;align-items:center;gap:6px;font-size:.78rem;color:#6b7280}
.pager-jump input{
  width:52px;padding:4px 6px;background:#1f2937;border:1px solid #374151;
  color:#d1d5db;border-radius:4px;text-align:center;font-size:.78rem
}

.gallery-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:14px;margin-bottom:16px
}
.gcard{
  background:#111827;border:1px solid #1f2937;border-radius:8px;
  overflow:hidden;transition:border-color .2s
}
.gcard.PASS{border-color:#166534}
.gcard.WARN{border-color:#9a3412}
.gcard.FAIL{border-color:#991b1b}
.gthumb{
  width:100%;height:175px;object-fit:cover;display:block;
  background:#0b0f1a;cursor:zoom-in
}
.gbody{padding:10px 12px}
.grow1{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.gid{font-size:.72rem;color:#6b7280}
.gts{font-size:.65rem;color:#374151}
.badge{padding:2px 9px;border-radius:20px;font-size:.65rem;font-weight:700;letter-spacing:.5px}
.badge.PASS{background:#14532d;color:#86efac}
.badge.WARN{background:#7c2d12;color:#fdba74}
.badge.FAIL{background:#7f1d1d;color:#fca5a5}
.gmetrics{display:grid;grid-template-columns:repeat(3,1fr);gap:3px;margin:7px 0;font-size:.67rem}
.gm{color:#6b7280}.gm span{display:block;font-weight:600;color:#9ca3af}
.gm.ok span{color:#4ade80}.gm.bad span{color:#f87171}.gm.mid span{color:#fb923c}
.gobjs{font-size:.68rem;display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.gobj{background:#1e3a5f;color:#93c5fd;border-radius:3px;padding:1px 6px}
.gissues{font-size:.65rem;color:#f87171;margin-top:5px;line-height:1.5}

/* Lightbox */
#lb{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);
  z-index:100;align-items:center;justify-content:center;cursor:zoom-out
}
#lb.open{display:flex}
#lb img{max-width:96vw;max-height:96vh;border-radius:6px}
</style>
</head>
<body>

<div id="lb" onclick="this.classList.remove('open')">
  <img id="lb-img" src="">
</div>

<header>
  <h1><span class="dot"></span>&nbsp;Camera QA — Live</h1>
  <span id="upd">—</span>
</header>

<nav>
  <button class="tab-btn active" onclick="switchTab('dashboard',this)">📊 Dashboard</button>
  <button class="tab-btn" onclick="switchTab('best',this)">✅ Gallery</button>
  <button class="tab-btn" onclick="switchTab('gallery',this)">📋 All Frames</button>
</nav>

<!-- ═══════════════════════════════════════════ DASHBOARD ══ -->
<div id="tab-dashboard">

  <div class="summary-row" id="summary-row">
    <!-- filled by JS -->
  </div>

  <div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Period</th>
        <th style="text-align:right">Total frames</th>
        <th style="text-align:right">🚗 Vehicles</th>
        <th style="text-align:right">🚶 People</th>
        <th style="text-align:right">✅ Good</th>
        <th style="text-align:right">⚠️ Stationary</th>
        <th style="text-align:right">❌ Bad</th>
        <th style="text-align:right">Quality</th>
      </tr>
    </thead>
    <tbody id="stats-tbody">
      <tr><td colspan="8" style="text-align:center;color:#4b5563;padding:24px">Loading…</td></tr>
    </tbody>
  </table>
  </div>

</div>

<!-- ═══════════════════════════════════════════ GALLERY (PASS) ═ -->
<div id="tab-best" style="display:none">

  <div class="pager" id="best-pager-top">
    <button class="pager-btn" id="best-btn-prev" onclick="changeBestPage(-1)" disabled>← Prev</button>
    <span class="pager-info" id="best-page-info">—</span>
    <button class="pager-btn" id="best-btn-next" onclick="changeBestPage(+1)" disabled>Next →</button>
    <span class="pager-jump">
      Go to page
      <input type="number" id="best-page-input" min="1" value="1"
             onkeydown="if(event.key==='Enter') jumpToBestPage()">
      <button class="pager-btn" onclick="jumpToBestPage()">Go</button>
    </span>
  </div>

  <div class="gallery-grid" id="best-gallery-grid">
    <p style="padding:40px;color:#374151;text-align:center;grid-column:1/-1">Loading…</p>
  </div>

  <div class="pager" id="best-pager-bottom">
    <button class="pager-btn" onclick="changeBestPage(-1)" id="best-btn-prev2" disabled>← Prev</button>
    <span class="pager-info" id="best-page-info2">—</span>
    <button class="pager-btn" onclick="changeBestPage(+1)" id="best-btn-next2" disabled>Next →</button>
  </div>

</div>

<!-- ═══════════════════════════════════════════ ALL FRAMES ══ -->
<div id="tab-gallery" style="display:none">

  <div class="pager" id="pager-top">
    <button class="pager-btn" id="btn-prev" onclick="changePage(-1)" disabled>← Prev</button>
    <span class="pager-info" id="page-info">—</span>
    <button class="pager-btn" id="btn-next" onclick="changePage(+1)" disabled>Next →</button>
    <span class="pager-jump">
      Go to page
      <input type="number" id="page-input" min="1" value="1"
             onkeydown="if(event.key==='Enter') jumpToPage()">
      <button class="pager-btn" onclick="jumpToPage()">Go</button>
    </span>
  </div>

  <div class="gallery-grid" id="gallery-grid">
    <p style="padding:40px;color:#374151;text-align:center;grid-column:1/-1">Loading…</p>
  </div>

  <div class="pager" id="pager-bottom">
    <button class="pager-btn" onclick="changePage(-1)" id="btn-prev2" disabled>← Prev</button>
    <span class="pager-info" id="page-info2">—</span>
    <button class="pager-btn" onclick="changePage(+1)" id="btn-next2" disabled>Next →</button>
  </div>

</div>

<script>
// ── Tab switching ───────────────────────────────────────────
let currentTab = 'dashboard';

function switchTab(name, btn) {
  currentTab = name;
  document.getElementById('tab-dashboard').style.display = name === 'dashboard' ? '' : 'none';
  document.getElementById('tab-best').style.display      = name === 'best'      ? '' : 'none';
  document.getElementById('tab-gallery').style.display   = name === 'gallery'   ? '' : 'none';
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  if (name === 'gallery') loadGallery(currentPage);
  if (name === 'best')    loadBestGallery(bestPage);
}

// ── Helpers ─────────────────────────────────────────────────
const PERIODS = [
  {minutes:10,   label:'10 min'},
  {minutes:60,   label:'1 hour'},
  {minutes:360,  label:'6 hours'},
  {minutes:720,  label:'12 hours'},
  {minutes:1440, label:'24 hours'},
];

function rateClass(r) {
  return r >= 70 ? 'rate-good' : r >= 40 ? 'rate-mid' : 'rate-bad';
}

function blurCls(v)   { return v >= 30 ? 'ok' : 'bad'; }
function gradCls(v)   { return v >= 5  ? 'ok' : 'bad'; }
function brightCls(v) { return v>=15&&v<=245?'ok':v<15?'bad':'mid'; }

function zoomImg(src) {
  document.getElementById('lb-img').src = src;
  document.getElementById('lb').classList.add('open');
}

// ── Dashboard stats ─────────────────────────────────────────
async function loadStats() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    renderSummaryCards(d.windows);
    renderStatsTable(d.windows);
    document.getElementById('upd').textContent =
      'Updated ' + new Date().toLocaleTimeString();
  } catch(e) { console.error(e); }
}

function renderSummaryCards(windows) {
  const row = document.getElementById('summary-row');
  row.innerHTML = windows.map(w => {
    const rc = rateClass(w.rate);
    const pct = w.total ? Math.round(w.passes/w.total*100) : 0;
    return `
    <div class="scard">
      <div class="period">${PERIODS.find(p=>p.minutes===w.minutes)?.label??w.minutes+'m'}</div>
      <div class="big">${w.total}</div>
      <div class="sub">${w.vehicles} vehicles &middot; ${w.people} people</div>
      <div class="pills">
        <span class="pill p">${w.passes} good</span>
        <span class="pill w">${w.warns} same</span>
        ${w.fails?`<span class="pill f">${w.fails} bad</span>`:''}
      </div>
      <div class="rate-bar">
        <div class="rate-bar-fill" style="width:${pct}%;background:${pct>=70?'#22c55e':pct>=40?'#eab308':'#ef4444'}"></div>
      </div>
    </div>`;
  }).join('');
}

function renderStatsTable(windows) {
  const tbody = document.getElementById('stats-tbody');
  if (!windows.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#4b5563;padding:24px">No data yet</td></tr>';
    return;
  }
  tbody.innerHTML = windows.map(w => {
    const label = PERIODS.find(p=>p.minutes===w.minutes)?.label ?? w.minutes+'m';
    const rc = rateClass(w.rate);
    return `<tr>
      <td class="period-cell">${label}</td>
      <td class="num">${w.total}</td>
      <td class="num count-v">${w.vehicles}</td>
      <td class="num count-p">${w.people}</td>
      <td class="num count-pass">${w.passes}</td>
      <td class="num count-warn">${w.warns}</td>
      <td class="num count-fail">${w.fails||'—'}</td>
      <td class="num rate-cell ${rc}">${w.total?w.rate+'%':'—'}</td>
    </tr>`;
  }).join('');
}

// ── Gallery (PASS only) ──────────────────────────────────────
let bestPage       = 1;
let bestTotalPages = 1;

async function loadBestGallery(page) {
  try {
    const r = await fetch(`/api/gallery?page=${page}&status=PASS`);
    const d = await r.json();
    bestPage       = d.page;
    bestTotalPages = d.total_pages;
    renderBestGallery(d.items, d.page, d.total_pages, d.total);
  } catch(e) { console.error(e); }
}

function renderBestGallery(items, page, totalPgs, total) {
  const info = `Page ${page} of ${totalPgs} &nbsp;·&nbsp; ${total} good frames`;
  document.getElementById('best-page-info').innerHTML  = info;
  document.getElementById('best-page-info2').innerHTML = info;
  ['best-btn-prev','best-btn-prev2'].forEach(id =>
    document.getElementById(id).disabled = page <= 1);
  ['best-btn-next','best-btn-next2'].forEach(id =>
    document.getElementById(id).disabled = page >= totalPgs);
  document.getElementById('best-page-input').value = page;
  document.getElementById('best-page-input').max   = totalPgs;
  if (!items.length) {
    document.getElementById('best-gallery-grid').innerHTML =
      '<p style="padding:40px;color:#374151;text-align:center;grid-column:1/-1">No good-quality frames yet</p>';
    return;
  }
  document.getElementById('best-gallery-grid').innerHTML = items.map(r => {
    const objs = (r.detections||[]).map(d =>
      `<span class="gobj">${d.class} ${Math.round(d.conf*100)}%</span>`).join('');
    return `
    <div class="gcard PASS">
      <img class="gthumb"
        src="/img/${r.rel_path}"
        loading="lazy"
        onerror="this.style.background='#1f2937';this.removeAttribute('src')"
        onclick="zoomImg(this.src)">
      <div class="gbody">
        <div class="grow1">
          <span class="gid">${r.tracking_id ? 'ID '+r.tracking_id : '—'} &middot; ${r.timestamp?.replace('T',' ')??''}</span>
          <span class="badge PASS">PASS</span>
        </div>
        <div class="gmetrics">
          <div class="gm ${blurCls(r.blur)}"><span>${r.blur}</span>Blur</div>
          <div class="gm ${gradCls(r.gradient)}"><span>${r.gradient}</span>Gradient</div>
          <div class="gm ${brightCls(r.brightness)}"><span>${r.brightness}</span>Brightness</div>
        </div>
        <div class="gobjs">${objs||'<span style="color:#374151">no objects</span>'}</div>
      </div>
    </div>`;
  }).join('');
}

function changeBestPage(delta) {
  const next = bestPage + delta;
  if (next >= 1 && next <= bestTotalPages) loadBestGallery(next);
}

function jumpToBestPage() {
  const v = parseInt(document.getElementById('best-page-input').value, 10);
  if (v >= 1 && v <= bestTotalPages) loadBestGallery(v);
}

// ── All Frames gallery ───────────────────────────────────────
let currentPage = 1;
let totalPages  = 1;

async function loadGallery(page) {
  try {
    const r = await fetch(`/api/gallery?page=${page}`);
    const d = await r.json();
    currentPage = d.page;
    totalPages  = d.total_pages;
    renderGallery(d.items, d.page, d.total_pages, d.total);
  } catch(e) { console.error(e); }
}

function renderGallery(items, page, totalPgs, total) {
  const info = `Page ${page} of ${totalPgs} &nbsp;·&nbsp; ${total} frames`;
  document.getElementById('page-info').innerHTML  = info;
  document.getElementById('page-info2').innerHTML = info;

  ['btn-prev','btn-prev2'].forEach(id =>
    document.getElementById(id).disabled = page <= 1);
  ['btn-next','btn-next2'].forEach(id =>
    document.getElementById(id).disabled = page >= totalPgs);

  document.getElementById('page-input').value = page;
  document.getElementById('page-input').max   = totalPgs;

  if (!items.length) {
    document.getElementById('gallery-grid').innerHTML =
      '<p style="padding:40px;color:#374151;text-align:center;grid-column:1/-1">No frames yet</p>';
    return;
  }

  document.getElementById('gallery-grid').innerHTML = items.map(r => {
    const objs = (r.detections||[]).map(d =>
      `<span class="gobj">${d.class} ${Math.round(d.conf*100)}%</span>`).join('');
    const issues = r.issues?.length
      ? `<div class="gissues">⚠ ${r.issues.join(' · ')}</div>` : '';
    const diff = r.hash_distance === null
      ? '<span style="color:#6b7280">first capture</span>'
      : r.is_different
        ? `<span style="color:#4ade80">✓ moved (Δ${r.hash_distance})</span>`
        : `<span style="color:#fb923c">~ stationary (Δ${r.hash_distance})</span>`;
    return `
    <div class="gcard ${r.status}">
      <img class="gthumb"
        src="/img/${r.rel_path}"
        loading="lazy"
        onerror="this.style.background='#1f2937';this.removeAttribute('src')"
        onclick="zoomImg(this.src)">
      <div class="gbody">
        <div class="grow1">
          <span class="gid">${r.tracking_id ? 'ID '+r.tracking_id : '—'} &middot; ${r.timestamp?.replace('T',' ')??''}</span>
          <span class="badge ${r.status}">${r.status}</span>
        </div>
        <div class="gmetrics">
          <div class="gm ${blurCls(r.blur)}"><span>${r.blur}</span>Blur</div>
          <div class="gm ${gradCls(r.gradient)}"><span>${r.gradient}</span>Gradient</div>
          <div class="gm ${brightCls(r.brightness)}"><span>${r.brightness}</span>Brightness</div>
        </div>
        <div style="font-size:.65rem;color:#6b7280;margin-bottom:4px">${diff}</div>
        <div class="gobjs">${objs||'<span style="color:#374151">no objects</span>'}</div>
        ${issues}
      </div>
    </div>`;
  }).join('');
}

function changePage(delta) {
  const next = currentPage + delta;
  if (next >= 1 && next <= totalPages) loadGallery(next);
}

function jumpToPage() {
  const v = parseInt(document.getElementById('page-input').value, 10);
  if (v >= 1 && v <= totalPages) loadGallery(v);
}

// ── Auto-refresh ─────────────────────────────────────────────
loadStats();
setInterval(loadStats, 30000);   // stats refresh every 30s

// Auto-refresh page 1 of whichever gallery tab is active
setInterval(() => {
  if (currentTab === 'gallery' && currentPage === 1) loadGallery(1);
  if (currentTab === 'best'    && bestPage === 1)    loadBestGallery(1);
}, 15000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("Loading QA model (yolov8n) on GPU 2...")
    model = YOLO("yolov8n.pt")

    t = threading.Thread(target=watcher, args=(model,), daemon=True)
    t.start()

    logger.info("QA dashboard running on :5001")
    app.run(host="0.0.0.0", port=5001, threaded=True)


if __name__ == "__main__":
    main()
