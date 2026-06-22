import cv2
from ultralytics import YOLO
from collections import defaultdict, deque
import logging
import os
import sys
import time
import threading
import numpy as np
import torch
import torch.nn.functional as F
from datetime import datetime
from pathlib import Path
import imagehash
from PIL import Image
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

Gst.init(None)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logging.getLogger("ultralytics").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
RTSP_URL  = os.getenv("RTSP_URL",  "rtsp://admin:12311231aA%40@192.168.100.2:554/Streaming/Channels/101")
CAMERA_ID = os.getenv("CAMERA_ID", "cam1")

ANIMAL_CLASSES = {
    "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe",
}
VIDEO_TARGET_CLASSES = {"person"} | ANIMAL_CLASSES  # classes we record clips of (not vehicles)

TARGET_CLASSES = {"car", "person"} | ANIMAL_CLASSES
VEHICLE_CLASSES = {"car", "truck", "bus"}
CONF_THRESHOLD = 0.60          # tracking threshold — object must clear this to be counted
SAVE_CONF_THRESHOLD = 0.70     # stricter gate at actual disk write — reduces ghost saves
MIN_PERSIST_FRAMES = 4         # consecutive qualifying detections before saving
COOLDOWN_SECONDS = 20          # per-object re-save gate in seconds
MISSING_TOLERANCE = 4          # frames before object considered gone
DIAG_INTERVAL = 100

MIN_BOX_AREA_FRACTION = 0.003  # reject boxes < 0.3% of frame area (phantom detections on texture)
SAME_SCENE_THRESHOLD = 5       # phash distance <= this for same tracking ID -> scene unchanged, skip

# Video clip recording
RECORD_MIN_PERSIST_FRAMES = 5  # one higher than MIN_PERSIST_FRAMES — clip is a heavier commit than a JPG
INFERENCE_FPS_MAX = 8          # cap main-loop rate; cuts per-frame CPU work (quality checks + pre-roll copies)
_INFERENCE_INTERVAL = 1.0 / INFERENCE_FPS_MAX

PREROLL_FRAMES = 24            # ring-buffer depth: 3s pre-roll at INFERENCE_FPS_MAX
MAX_CLIP_SECONDS = 30          # hard per-clip cap; bounds disk use for loitering objects
CLIP_COOLDOWN_SECONDS = 60     # gap between clips for the same tracking ID
RECORD_FPS = float(INFERENCE_FPS_MAX)  # match video header to actual capture rate
FOURCC_STR = "mp4v"            # MPEG-4 Part2 — only codec reliably encodable by the opencv wheel + HTML5-playable

# Frame quality thresholds
BLUR_THRESHOLD = 30.0
GRADIENT_THRESHOLD = 500.0     # scaled for cv2.Sobel (Sobel values ~8x larger than np.gradient)
BRIGHTNESS_MIN = 15.0          # mean grayscale below this -> dark/corrupt
BRIGHTNESS_MAX = 245.0         # mean grayscale above this -> overexposed/corrupt

# ── NIGHTTIME MULTI-FRAME STACKING ──────────────────────────────────────────
# Combines the last STACK_DEPTH validated frames into one image using ECC
# alignment + pixel-wise median. Reduces sensor noise at night, improves
# background sharpness. Fast-moving subjects may appear slightly softened.
#
# Runtime toggle (no rebuild needed):
#   Send /stacking_on  in Telegram → enables  (creates output/.frame_stacking)
#   Send /stacking_off in Telegram → disables (deletes output/.frame_stacking)
#   Send /stacking     in Telegram → shows current state
#
# Code default (applied only on first deploy when the flag file does not exist yet):
FRAME_STACKING_ENABLED = True      # change to False to default to off on next fresh deploy
STACK_DEPTH = 3                    # frames to merge (3 ≈ 1.7× noise reduction)
STACKING_FLAG_FILE = Path("/app/output/.frame_stacking")
# ────────────────────────────────────────────────────────────────────────────

# ---------------------------------------------------------------------------
# Frame quality validators — run on GPU via PyTorch to keep CPU free
# ---------------------------------------------------------------------------

_qk: dict | None = None  # quality-check kernels, initialised after YOLO loads CUDA


def _init_quality_kernels() -> None:
    global _qk
    dev = torch.device('cuda:0')
    _qk = {
        'lap': torch.tensor([[0., 1., 0.], [1., -4., 1.], [0., 1., 0.]], device=dev).view(1, 1, 3, 3),
        'sx':  torch.tensor([[-1., 0., 1.], [-2., 0., 2.], [-1., 0., 1.]], device=dev).view(1, 1, 3, 3),
        'sy':  torch.tensor([[-1., -2., -1.], [0., 0., 0.], [1., 2., 1.]], device=dev).view(1, 1, 3, 3),
    }


def _is_frame_valid(frame: np.ndarray) -> bool:
    """GPU quality check: Laplacian blur var, Sobel gradient var, brightness."""
    if _qk is None:
        return True  # kernels not yet ready — pass through until startup completes
    with torch.no_grad():
        # Upload uint8 (6 MB) to GPU first, then convert to float32 on GPU (not CPU).
        # Wrong order (.float().cuda()) would allocate 24 MB on CPU before transfer.
        t = torch.from_numpy(frame).cuda().float()          # HWC BGR float32 on GPU
        gray = (0.114 * t[:, :, 0] + 0.587 * t[:, :, 1] + 0.299 * t[:, :, 2])
        gray = gray.unsqueeze(0).unsqueeze(0)               # [1, 1, H, W]

        lap = F.conv2d(gray, _qk['lap'], padding=1)
        blur_var = lap.var().item()
        if blur_var < BLUR_THRESHOLD:
            logging.warning("Frame discarded: blur_var=%.1f", blur_var)
            return False

        gx = F.conv2d(gray, _qk['sx'], padding=1)
        gy = F.conv2d(gray, _qk['sy'], padding=1)
        grad_var = (gx ** 2 + gy ** 2).sqrt().var().item()
        if grad_var < GRADIENT_THRESHOLD:
            logging.warning("Frame discarded: grad_var=%.1f", grad_var)
            return False

        brightness = gray.mean().item()
        if brightness < BRIGHTNESS_MIN or brightness > BRIGHTNESS_MAX:
            logging.warning("Frame discarded: brightness=%.1f", brightness)
            return False
    return True


def _phash(frame_bgr: np.ndarray) -> imagehash.ImageHash:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return imagehash.average_hash(Image.fromarray(rgb))


def _stack_frames(reference: np.ndarray, preroll: deque) -> np.ndarray:
    """Align and median-stack the last STACK_DEPTH frames to cut sensor noise.

    Each source frame is aligned to the reference using ECC (translation only —
    sufficient for a fixed camera with minor vibration). Pixel-wise median then
    suppresses random noise while keeping edges sharper than a plain average.
    Falls back silently to the raw reference if alignment fails or there are not
    enough frames buffered yet.
    """
    recent_frames = [f for f, _ in list(preroll)]
    sources = recent_frames[-(STACK_DEPTH - 1):]   # frames BEFORE the reference
    if not sources:
        return reference

    h, w = reference.shape[:2]
    ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)

    aligned = [reference]
    for src in sources:
        if src.shape[:2] != (h, w):
            continue
        try:
            src_gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
            warp = np.eye(2, 3, dtype=np.float32)
            _, warp = cv2.findTransformECC(
                ref_gray, src_gray, warp, cv2.MOTION_TRANSLATION, criteria
            )
            warped = cv2.warpAffine(
                src, warp, (w, h),
                flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
            )
            aligned.append(warped)
        except cv2.error:
            aligned.append(src)   # alignment failed — use unaligned, still helps median

    if len(aligned) < 2:
        return reference

    stacked = np.median(np.stack(aligned, axis=0), axis=0).astype(np.uint8)
    return stacked


# ---------------------------------------------------------------------------
# RTSP reader thread — GPU H.264 decode via NVDEC (h264_cuvid)
# ---------------------------------------------------------------------------
# Each slot: (sequence_id: int, frame: np.ndarray, capture_ts: datetime)
_latest_slot: tuple | None = None
_frame_seq: int = 0
_frame_lock = threading.Lock()


def _reader_thread(url: str) -> None:
    """Daemon thread: decode H.264 on GPU via GStreamer nvh264dec (NVDEC), store latest BGR frame.

    Pipeline: rtspsrc (TCP) → rtph264depay → h264parse → nvh264dec → cudadownload
    → NV12 in system RAM → cv2.cvtColor YUV2BGR → single-slot buffer.

    No subprocess, no Unix pipe. GStreamer appsink delivers NV12 buffers (3 MB)
    directly in-process; cv2.cvtColor converts to BGR (6 MB) in ~1 ms on CPU.
    Eliminates the ffmpeg subprocess (~24 % CPU overhead from IPC and pipe reads).
    """
    global _latest_slot, _frame_seq
    backoff = 1.0

    while True:
        pipeline = None
        try:
            # nvh264dec outputs NV12 in CUDA memory; cudadownload moves it to system
            # RAM so appsink can map it as a plain CPU buffer (3 MB NV12 per frame).
            pipeline = Gst.parse_launch(
                'rtspsrc name=src latency=0 ! '
                'rtph264depay ! h264parse ! nvh264dec ! '
                'cudadownload ! video/x-raw,format=NV12 ! '
                'appsink name=sink sync=false max-buffers=2 drop=true'
            )
            src = pipeline.get_by_name('src')
            src.set_property('location', url)
            src.set_property('protocols', 4)   # 4 = TCP; avoids UDP packet-loss corruption
            sink = pipeline.get_by_name('sink')

            ret = pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("GStreamer pipeline failed to enter PLAYING state")

            width = height = None

            while True:
                # 1-second timeout lets us check the bus for errors / EOS
                sample = sink.emit('try-pull-sample', Gst.SECOND)
                if sample is None:
                    msg = pipeline.get_bus().timed_pop_filtered(
                        0, Gst.MessageType.ERROR | Gst.MessageType.EOS
                    )
                    if msg:
                        if msg.type == Gst.MessageType.ERROR:
                            err, _ = msg.parse_error()
                            logging.warning("GStreamer pipeline error: %s", err)
                        break
                    continue

                # Discover dimensions from first frame's caps; stable thereafter
                if width is None:
                    caps = sample.get_caps()
                    st = caps.get_structure(0)
                    width = st.get_int('width')[1]
                    height = st.get_int('height')[1]
                    logging.info("GStreamer NVDEC connected: %dx%d NV12", width, height)
                    backoff = 1.0

                buf = sample.get_buffer()
                ok, info = buf.map(Gst.MapFlags.READ)
                if not ok:
                    break

                # NV12 layout: Y plane [H, W] followed by interleaved UV plane [H/2, W]
                nv12 = np.frombuffer(info.data, dtype=np.uint8).reshape(height * 3 // 2, width)
                bgr = cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)
                buf.unmap(info)

                ts = datetime.now()
                with _frame_lock:
                    _frame_seq += 1
                    _latest_slot = (_frame_seq, bgr, ts)

        except Exception as e:
            logging.warning("GStreamer reader error: %s", e)
        finally:
            if pipeline is not None:
                pipeline.set_state(Gst.State.NULL)

        logging.warning("GStreamer reader disconnected, retrying in %.0fs", backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 30.0)


def _get_latest_slot() -> tuple | None:
    with _frame_lock:
        return _latest_slot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_daily_output_dir() -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = Path("output") / CAMERA_ID / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def iou(boxA: list, boxB: list) -> float:
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interArea = max(0, xB - xA) * max(0, yB - yA)
    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union = areaA + areaB - interArea
    return interArea / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# yolov8s for production accuracy; device=0 is GPU exposed via CUDA_VISIBLE_DEVICES=1
model = YOLO("yolov8s.pt")
_init_quality_kernels()    # needs CUDA already initialised by YOLO above
logging.info("GPU quality-check kernels ready on cuda:0")

object_last_seen: dict = {}
detection_buffer: dict = defaultdict(int)
missing_counter: dict = defaultdict(int)
_last_save_hash: dict = {}     # per-tracking-ID phash of last saved frame
prev_active: set = set()
frame_id = 0
_last_consumed_seq = 0

# Initialise the stacking flag file from the code default.
# Only touches the file if it doesn't exist yet — so Telegram toggles survive rebuilds.
try:
    if FRAME_STACKING_ENABLED and not STACKING_FLAG_FILE.exists():
        STACKING_FLAG_FILE.touch()
    elif not FRAME_STACKING_ENABLED and STACKING_FLAG_FILE.exists():
        STACKING_FLAG_FILE.unlink()
except OSError:
    pass

# Video clip recording state
_preroll: deque = deque(maxlen=PREROLL_FRAMES)
_recording: bool = False
_writer: cv2.VideoWriter | None = None
_record_id: int | None = None
_record_class: str = ""
_record_start_ts: datetime | None = None
_record_missing: int = 0
_record_cooldown: dict = {}    # obj_id -> datetime of last clip end

t = threading.Thread(target=_reader_thread, args=(RTSP_URL,), daemon=True)
t.start()

# ---------------------------------------------------------------------------
# Main inference loop
# ---------------------------------------------------------------------------

_last_inference_ts: float = 0.0

while True:
    # Enforce INFERENCE_FPS_MAX to reduce CPU load from per-frame quality checks and pre-roll copies.
    # The reader thread still runs at full camera rate; we just process only the latest frame each tick.
    now = time.monotonic()
    gap = _INFERENCE_INTERVAL - (now - _last_inference_ts)
    if gap > 0:
        time.sleep(gap)

    slot = _get_latest_slot()
    if slot is None or slot[0] == _last_consumed_seq:
        time.sleep(0.005)
        continue

    _last_inference_ts = time.monotonic()
    seq_id, frame, capture_ts = slot

    if seq_id > _last_consumed_seq + 1:
        logging.debug("Skipped %d frames (throttled)", seq_id - _last_consumed_seq - 1)

    _last_consumed_seq = seq_id

    # Discard corrupt or extreme-brightness frames before running inference
    if not _is_frame_valid(frame):
        continue

    # Feed pre-roll ring buffer and write the current frame into any active clip.
    # Both happen before inference so the clip contains every valid frame, not just
    # frames where a detection fired.
    _preroll.append((frame.copy(), capture_ts))
    if _recording and _writer is not None:
        _writer.write(frame)

    # imgsz=640 keeps inference fast enough on GTX 1060 to reduce frame skips
    results = model.track(frame, persist=True, verbose=False, device=0, imgsz=640)
    annotated = results[0].plot()
    class_names = results[0].names

    current_time = capture_ts
    current_active: set = set()
    current_detected_ids: set = set()  # IDs that cleared conf+class filter this frame
    frame_h, frame_w = frame.shape[:2]
    frame_area = frame_h * frame_w

    for box in results[0].boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        obj_id = int(box.id.item()) if box.id is not None else None
        if obj_id is None:
            continue
        class_name = class_names[cls_id]
        if class_name in VEHICLE_CLASSES:
            class_name = "vehicle"
        if class_name not in TARGET_CLASSES and class_name != "vehicle":
            continue
        if conf < CONF_THRESHOLD:
            continue

        # Reject phantom detections: tiny boxes on background texture
        box_coords = box.xyxy[0].tolist()
        box_area = (box_coords[2] - box_coords[0]) * (box_coords[3] - box_coords[1])
        if box_area < MIN_BOX_AREA_FRACTION * frame_area:
            logging.debug(
                "Box too small (%.4f%% of frame) for ID=%d, skipping",
                100 * box_area / frame_area, obj_id,
            )
            continue

        current_detected_ids.add(obj_id)
        detection_buffer[obj_id] += 1
        if detection_buffer[obj_id] < MIN_PERSIST_FRAMES:
            continue

        duplicate = False
        for stored_box, last_seen_time in object_last_seen.values():
            if (current_time - last_seen_time).total_seconds() <= COOLDOWN_SECONDS:
                if iou(box_coords, stored_box) > 0.7:
                    duplicate = True
                    break
        if duplicate:
            continue

        current_active.add((class_name, obj_id))
        missing_counter[obj_id] = 0

        # ── Video clip start gate (people and animals only) ──────────────────
        # Runs in parallel to the JPG save logic; does not touch object_last_seen
        # or _last_save_hash so it cannot interfere with the frame-save pipeline.
        if (
            not _recording
            and class_name in VIDEO_TARGET_CLASSES
            and detection_buffer[obj_id] >= RECORD_MIN_PERSIST_FRAMES
        ):
            cooldown_ts = _record_cooldown.get(obj_id)
            clip_ready = (
                cooldown_ts is None
                or (current_time - cooldown_ts).total_seconds() >= CLIP_COOLDOWN_SECONDS
            )
            if clip_ready:
                output_dir = get_daily_output_dir()
                timestamp_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
                clip_path = output_dir / f"clip_{timestamp_str}_id{obj_id}_{class_name}.mp4"
                fourcc = cv2.VideoWriter_fourcc(*FOURCC_STR)
                w = cv2.VideoWriter(str(clip_path), fourcc, RECORD_FPS, (frame_w, frame_h))
                if w.isOpened():
                    for pr_frame, _ in _preroll:
                        w.write(pr_frame)
                    _recording = True
                    _writer = w
                    _record_id = obj_id
                    _record_class = class_name
                    _record_start_ts = current_time
                    _record_missing = 0
                    logging.info(
                        "Recording clip: ID=%d class=%s → %s", obj_id, class_name, clip_path.name
                    )
                else:
                    logging.error("VideoWriter failed to open for %s", clip_path)
        # ─────────────────────────────────────────────────────────────────────

        last_seen = object_last_seen.get(obj_id)
        if last_seen is None or (current_time - last_seen[1]).total_seconds() > COOLDOWN_SECONDS:
            # Stricter confidence gate at save point: track at 0.60, write at 0.70
            if conf < SAVE_CONF_THRESHOLD:
                logging.info(
                    "Conf %.2f below save threshold for ID=%d, tracking only", conf, obj_id
                )
                continue

            # Scene-change gate: skip if visually unchanged vs last save for this ID
            ph = _phash(frame)
            prev_hash = _last_save_hash.get(obj_id)
            if prev_hash is not None:
                dist = int(ph - prev_hash)
                if dist <= SAME_SCENE_THRESHOLD:
                    logging.info(
                        "Scene unchanged (delta_hash=%d) for ID=%d, skipping save", dist, obj_id
                    )
                    object_last_seen[obj_id] = (box_coords, current_time)
                    detection_buffer[obj_id] = 0
                    continue

            timestamp_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            logging.info(
                "New object: ID=%d Class=%s Conf=%.2f", obj_id, class_name, conf
            )
            output_dir = get_daily_output_dir()
            # Primary artifact: stacked (noise-reduced) frame when flag is on, else raw
            save_frame = _stack_frames(frame, _preroll) if STACKING_FLAG_FILE.exists() else frame
            filename = output_dir / f"frame_{timestamp_str}_id{obj_id}_{class_name}.jpg"
            cv2.imwrite(str(filename), save_frame)
            # Debug artifact: annotated raw frame with YOLO boxes (always single frame)
            debug_filename = output_dir / f"frame_{timestamp_str}_id{obj_id}_{class_name}_debug.jpg"
            cv2.imwrite(str(debug_filename), annotated)
            if filename.exists():
                logging.info("Saved %s", filename)
                _last_save_hash[obj_id] = ph
                web_frame = Path("output") / CAMERA_ID / "frame_for_web.jpg"
                cv2.imwrite(str(web_frame), annotated)
            else:
                logging.error("Failed to save %s", filename)
            object_last_seen[obj_id] = (box_coords, current_time)
            detection_buffer[obj_id] = 0
        else:
            logging.info(
                "Cooldown active for ID=%d (%s), last seen %s",
                obj_id, class_name, last_seen[1],
            )

    # ── Video clip stop check ────────────────────────────────────────────────
    if _recording:
        if _record_id in current_detected_ids:
            _record_missing = 0
        else:
            _record_missing += 1
        elapsed = (current_time - _record_start_ts).total_seconds()
        if _record_missing >= MISSING_TOLERANCE or elapsed >= MAX_CLIP_SECONDS:
            _writer.release()
            _record_cooldown[_record_id] = current_time
            logging.info(
                "Saved clip: ID=%d class=%s duration=%.1fs", _record_id, _record_class, elapsed
            )
            _recording = False
            _writer = None
            _record_id = None
            _record_class = ""
            _record_start_ts = None
            _record_missing = 0
    # ─────────────────────────────────────────────────────────────────────────

    # Reset detection_buffer for IDs absent this frame -- prevents ghost credit accumulation
    for obj_id in list(detection_buffer.keys()):
        if obj_id not in current_detected_ids:
            detection_buffer[obj_id] = 0

    # Handle missing objects with tolerance.
    # Use current_detected_ids (cleared conf threshold) not current_active (cleared all
    # save gates) — the duplicate check and MIN_PERSIST gate legitimately block an object
    # from current_active even when it is still physically present in the scene.
    to_remove: set = set()
    for obj_id in list(object_last_seen.keys()):
        if obj_id not in current_detected_ids:
            missing_counter[obj_id] += 1
            if missing_counter[obj_id] >= MISSING_TOLERANCE:
                to_remove.add(obj_id)
                missing_counter.pop(obj_id, None)
        else:
            missing_counter[obj_id] = 0

    # Apply removals -- fixes unbounded growth of object_last_seen (was never cleaned before)
    for obj_id in to_remove:
        object_last_seen.pop(obj_id, None)
        detection_buffer.pop(obj_id, None)
        _last_save_hash.pop(obj_id, None)
        _record_cooldown.pop(obj_id, None)

    prev_active = {item for item in prev_active if item[1] not in to_remove} | current_active

    frame_id += 1
    if frame_id % DIAG_INTERVAL == 0:
        detected = [
            f"{class_names[int(b.cls[0])]}({float(b.conf[0]):.2f})"
            for b in results[0].boxes
        ]
        logging.info("Diagnostic: frame %d, detections: %s", frame_id, detected)
