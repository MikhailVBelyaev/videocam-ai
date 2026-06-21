import cv2
import os
import sys
import time
import json
import threading
import logging
import numpy as np
from datetime import datetime
from pathlib import Path
from collections import deque

import imagehash
from PIL import Image
from flask import Flask, jsonify, send_file, abort, Response
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
MAX_RESULTS = 60
POLL_INTERVAL = 2.0           # seconds between directory scans
PRELOAD_RECENT = 10           # seed dashboard with last N existing frames on startup

BLUR_THRESHOLD = 30.0
GRADIENT_THRESHOLD = 5.0
BRIGHTNESS_MIN = 15.0
BRIGHTNESS_MAX = 245.0
SIMILARITY_THRESHOLD = 8      # perceptual hash distance; below = duplicate
CONF_THRESHOLD = 0.35         # lower than production — we want to verify presence

TARGET_CLASSES = {"car", "truck", "bus", "person", "motorbike", "bicycle"}

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
results_buffer: deque = deque(maxlen=MAX_RESULTS)
results_lock = threading.Lock()
processed_count = 0
pass_count = 0
last_phash = None

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
    global last_phash

    img = cv2.imread(str(img_path))
    if img is None:
        return {
            "filename": img_path.name,
            "rel_path": str(img_path.relative_to(OUTPUT_DIR)),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "status": "FAIL",
            "issues": ["unreadable image"],
            "blur": 0.0, "gradient": 0.0, "brightness": 0.0,
            "hash_distance": None, "is_different": None, "detections": [],
        }

    blur = _blur_score(img)
    gradient = _gradient_score(img)
    brightness = _brightness(img)

    ph = _phash(img)
    hash_distance = int(ph - last_phash) if last_phash is not None else None
    is_different = (hash_distance is None) or (hash_distance > SIMILARITY_THRESHOLD)
    last_phash = ph

    # YOLO verification — did the system actually capture a real object?
    yolo_results = model.predict(img, verbose=False, device=0, conf=CONF_THRESHOLD)
    detections = []
    for box in yolo_results[0].boxes:
        cls_name = yolo_results[0].names[int(box.cls[0])]
        conf = float(box.conf[0])
        if cls_name in TARGET_CLASSES:
            detections.append({"class": cls_name, "conf": round(conf, 2)})

    has_object = len(detections) > 0

    # Determine issues
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
    if not is_different:
        issues.append(f"duplicate frame (Δhash={hash_distance})")

    if len(issues) == 0:
        status = "PASS"
    elif not has_object or blur < BLUR_THRESHOLD or not is_different:
        status = "FAIL"
    else:
        status = "WARN"

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
        "is_different": is_different,
        "detections": detections,
    }


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
                    and "_debug" not in f.name     # skip annotated debug copies
                    and str(f) not in seen
                ):
                    files.append(f)
    except OSError:
        pass
    return files


def watcher(model: YOLO):
    global processed_count, pass_count
    seen: set = set()

    # Collect all existing files
    all_existing = _image_files(set())

    # Seed dashboard with the last PRELOAD_RECENT frames
    preload = all_existing[-PRELOAD_RECENT:] if len(all_existing) > PRELOAD_RECENT else all_existing
    for f in all_existing:
        seen.add(str(f))

    logger.info("Pre-seeding dashboard with %d recent frames...", len(preload))
    for img_path in preload:
        try:
            result = analyze(img_path, model)
            with results_lock:
                results_buffer.append(result)
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
                    results_buffer.append(result)
                    processed_count += 1
                    if result["status"] == "PASS":
                        pass_count += 1
                logger.info(
                    "%s → %s  blur=%.0f  bright=%.0f  objects=%s",
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


@app.route("/api/results")
def api_results():
    with results_lock:
        data = list(results_buffer)
        total = processed_count
        passes = pass_count
    return jsonify({"results": data, "total": total, "pass_count": passes})


@app.route("/")
def dashboard():
    return Response(DASHBOARD_HTML, mimetype="text/html")


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Camera QA — Live</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0d0d0d;color:#ddd;min-height:100vh}
header{
  background:#111827;padding:14px 20px;
  display:flex;justify-content:space-between;align-items:center;
  border-bottom:1px solid #1f2937;position:sticky;top:0;z-index:10
}
h1{font-size:1rem;color:#60a5fa;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:#22c55e;
  animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
#stats{display:flex;gap:20px;font-size:.8rem;color:#6b7280}
#stats b{color:#e5e7eb}
#bar{display:flex;height:4px;background:#1f2937;margin-bottom:0}
#bar-pass{background:#16a34a;transition:width .5s}
#bar-warn{background:#ea580c;transition:width .5s}
#bar-fail{background:#dc2626;transition:width .5s}
#grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:14px;padding:14px
}
.card{
  background:#111827;border-radius:8px;overflow:hidden;
  border:1px solid #1f2937;transition:border-color .3s
}
.card.PASS{border-color:#166534}
.card.WARN{border-color:#9a3412}
.card.FAIL{border-color:#991b1b}
.card.new{animation:flashin .6s}
@keyframes flashin{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.thumb{
  width:100%;height:180px;object-fit:cover;display:block;
  background:#0d0d0d;cursor:pointer
}
.card-body{padding:10px 12px}
.row1{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.fname{font-size:.68rem;color:#6b7280;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;max-width:220px}
.ts{font-size:.65rem;color:#374151}
.badge{
  padding:2px 9px;border-radius:20px;font-size:.65rem;
  font-weight:700;letter-spacing:.5px
}
.badge.PASS{background:#14532d;color:#86efac}
.badge.WARN{background:#7c2d12;color:#fdba74}
.badge.FAIL{background:#7f1d1d;color:#fca5a5}
.metrics{
  display:grid;grid-template-columns:1fr 1fr 1fr;
  gap:4px;margin:8px 0;font-size:.68rem
}
.m{color:#6b7280}
.m span{display:block;font-size:.78rem;font-weight:600;color:#9ca3af}
.m.ok span{color:#4ade80}
.m.warn span{color:#fb923c}
.m.bad span{color:#f87171}
.objects{font-size:.68rem;margin-top:4px;display:flex;flex-wrap:wrap;gap:3px}
.obj{
  background:#1e3a5f;color:#93c5fd;border-radius:3px;
  padding:1px 7px;white-space:nowrap
}
.issues{font-size:.65rem;color:#f87171;margin-top:5px;line-height:1.5}
.diff-ok{color:#4ade80}
.diff-no{color:#f87171}
/* Lightbox */
#lb{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.9);
  z-index:100;cursor:zoom-out;align-items:center;justify-content:center
}
#lb.open{display:flex}
#lb img{max-width:95vw;max-height:95vh;border-radius:6px}
</style>
</head>
<body>
<div id="lb" onclick="this.classList.remove('open')">
  <img id="lb-img" src="">
</div>
<header>
  <h1><span class="dot"></span>Camera QA — Live</h1>
  <div id="stats">
    Frames: <b id="s-total">0</b> &nbsp;
    Pass: <b id="s-pass" style="color:#4ade80">0</b> &nbsp;
    Warn: <b id="s-warn" style="color:#fb923c">0</b> &nbsp;
    Fail: <b id="s-fail" style="color:#f87171">0</b> &nbsp;
    Rate: <b id="s-rate">—</b> &nbsp;
    Updated: <b id="s-time">—</b>
  </div>
</header>
<div id="bar"><div id="bar-pass" style="width:0%"></div><div id="bar-warn" style="width:0%"></div><div id="bar-fail" style="width:0%"></div></div>
<div id="grid"><p style="padding:40px;color:#374151;text-align:center">Waiting for frames…</p></div>

<script>
let prevTotal = -1;

function cls(val, low, high) {
  if (val < low) return 'bad';
  if (val > high) return 'warn';
  return 'ok';
}

function blurCls(v)  { return v >= 30 ? 'ok' : 'bad'; }
function gradCls(v)  { return v >= 5  ? 'ok' : 'bad'; }
function brightCls(v){ return v >= 15 && v <= 245 ? 'ok' : v < 15 ? 'bad' : 'warn'; }

function diffHtml(r) {
  if (r.hash_distance === null) return '<span style="color:#6b7280">first</span>';
  return r.is_different
    ? `<span class="diff-ok">✓ diff (Δ${r.hash_distance})</span>`
    : `<span class="diff-no">✗ dup (Δ${r.hash_distance})</span>`;
}

function card(r, isNew) {
  const objs = (r.detections||[]).map(d=>
    `<span class="obj">${d.class} ${Math.round(d.conf*100)}%</span>`
  ).join('');
  const issues = r.issues && r.issues.length
    ? `<div class="issues">⚠ ${r.issues.join(' &middot; ')}</div>`
    : '';
  const newCls = isNew ? ' new' : '';
  return `
<div class="card ${r.status}${newCls}">
  <img class="thumb" src="/img/${r.rel_path}"
    loading="lazy"
    onerror="this.style.background='#1f2937';this.removeAttribute('src')"
    onclick="document.getElementById('lb-img').src=this.src;document.getElementById('lb').classList.add('open')">
  <div class="card-body">
    <div class="row1">
      <div class="fname" title="${r.filename}">${r.filename.replace(/_debug/,'')}</div>
      <div class="ts">${r.timestamp.replace('T',' ')}</div>
    </div>
    <span class="badge ${r.status}">${r.status}</span>
    <div class="metrics">
      <div class="m ${blurCls(r.blur)}"><span>${r.blur}</span>Blur</div>
      <div class="m ${gradCls(r.gradient)}"><span>${r.gradient}</span>Gradient</div>
      <div class="m ${brightCls(r.brightness)}"><span>${r.brightness}</span>Brightness</div>
    </div>
    <div style="font-size:.65rem;color:#6b7280;margin-bottom:4px">${diffHtml(r)}</div>
    <div class="objects">${objs || '<span style="color:#374151">no objects</span>'}</div>
    ${issues}
  </div>
</div>`;
}

async function refresh() {
  try {
    const r = await fetch('/api/results');
    const d = await r.json();
    if (d.total === prevTotal) return;

    const results = [...d.results].reverse();
    const isFirstLoad = prevTotal === -1;
    prevTotal = d.total;

    const pass = results.filter(r=>r.status==='PASS').length;
    const warn = results.filter(r=>r.status==='WARN').length;
    const fail = results.filter(r=>r.status==='FAIL').length;
    const rate = d.total > 0 ? Math.round(d.pass_count/d.total*100) : 0;

    document.getElementById('s-total').textContent = d.total;
    document.getElementById('s-pass').textContent = pass;
    document.getElementById('s-warn').textContent = warn;
    document.getElementById('s-fail').textContent = fail;
    document.getElementById('s-rate').textContent = rate + '% pass';
    document.getElementById('s-time').textContent = new Date().toLocaleTimeString();

    const n = results.length;
    document.getElementById('bar-pass').style.width = (pass/n*100)+'%';
    document.getElementById('bar-warn').style.width = (warn/n*100)+'%';
    document.getElementById('bar-fail').style.width = (fail/n*100)+'%';

    // Only animate the newest card (first in reversed list)
    document.getElementById('grid').innerHTML =
      results.map((r,i) => card(r, !isFirstLoad && i===0)).join('');
  } catch(e) { console.error(e); }
}

refresh();
setInterval(refresh, 3000);
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
