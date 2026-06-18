import argparse
import csv
import json
import logging
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

logger = logging.getLogger(__name__)

MOBILENET_SSD_CLASSES = [
    "background",
    "aeroplane",
    "bicycle",
    "bird",
    "boat",
    "bottle",
    "bus",
    "car",
    "cat",
    "chair",
    "cow",
    "diningtable",
    "dog",
    "horse",
    "motorbike",
    "person",
    "pottedplant",
    "sheep",
    "sofa",
    "train",
    "tvmonitor",
]


@dataclass(frozen=True)
class TriageConfig:
    input_dir: Path
    output_dir: Path
    rejected_dir: Path
    blur_threshold: float = 100.0
    gradient_threshold: float = 20.0
    brightness_threshold: float = 55.0
    duplicate_distance_threshold: int = 5
    generate_video: bool = False
    video_fps: float = 5.0
    kept_dir: Path | None = None
    detect_objects: bool = False
    model_dir: Path | None = None
    expected_objects: list[str] | None = None


@dataclass(frozen=True)
class TriageSummary:
    total_images: int
    kept_images: int
    rejected_by_reason: dict[str, int]
    report_path: Path


def _sorted_image_paths(input_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in input_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ],
        key=lambda p: p.name.lower(),
    )


def _compute_blur_score(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _compute_gradient_score(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gx, gy = np.gradient(gray.astype(np.float64))
    magnitude = np.sqrt(gx**2 + gy**2)
    return float(magnitude.var())


def _compute_brightness_score(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def _average_hash(image_bgr: np.ndarray, hash_size: int = 8) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hash_size, hash_size), interpolation=cv2.INTER_AREA)
    mean_value = resized.mean()
    return (resized >= mean_value).astype(np.uint8)


def _hamming_distance(hash_a: np.ndarray, hash_b: np.ndarray) -> int:
    return int(np.count_nonzero(hash_a != hash_b))


def _load_detection_model(model_dir: Path) -> tuple[cv2.dnn.Net | None, list[str]]:
    """Load MobileNet-SSD Caffe model from model_dir.

    Returns (net, class_names) or (None, class_names) if files are missing.
    """
    prototxt = model_dir / "MobileNetSSD_deploy.prototxt"
    caffemodel = model_dir / "MobileNetSSD_deploy.caffemodel"
    if not prototxt.exists() or not caffemodel.exists():
        logger.warning(
            "Model files not found in %s (expected %s and %s). "
            "Object detection will be skipped.",
            model_dir,
            prototxt.name,
            caffemodel.name,
        )
        return None, MOBILENET_SSD_CLASSES
    try:
        net = cv2.dnn.readNetFromCaffe(str(prototxt), str(caffemodel))
        return net, MOBILENET_SSD_CLASSES
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Failed to load detection model: %s. Object detection will be skipped.", exc
        )
        return None, MOBILENET_SSD_CLASSES


def _detect_objects(
    image_bgr: np.ndarray, net: cv2.dnn.Net | None, class_names: list[str]
) -> dict[str, int]:
    """Run MobileNet-SSD inference and return per-class detection counts."""
    if net is None or image_bgr is None or image_bgr.size == 0:
        return {}

    h, w = image_bgr.shape[:2]
    blob = cv2.dnn.blobFromImage(image_bgr, 0.007843, (300, 300), 127.5)
    net.setInput(blob)
    detections = net.forward()

    counts: dict[str, int] = {}
    for i in range(detections.shape[2]):
        confidence = float(detections[0, 0, i, 2])
        if confidence < 0.5:
            continue
        class_idx = int(detections[0, 0, i, 1])
        if class_idx < 0 or class_idx >= len(class_names):
            continue
        class_name = class_names[class_idx]
        if class_name == "bus":
            class_name = "vehicle"
        counts[class_name] = counts.get(class_name, 0) + 1

    return counts


def _check_missing_expected(object_counts: dict[str, int], expected: list[str]) -> list[str]:
    """Return which expected objects are absent from the counts."""
    return [obj for obj in expected if object_counts.get(obj, 0) == 0]


def _compute_statistics(
    rows: list[dict],
    kept_rows: list[dict],
    object_counts_map: dict[str, dict[str, int]] | None = None,
    expected_objects: list[str] | None = None,
) -> dict:
    """Compute aggregate statistics and quality ranks from triage rows.

    Returns a dict matching the triage_summary.json schema:
    - total_images, kept_images, rejected_by_reason
    - score_distributions with min/max/mean/std for each score
    - kept_frames with filename and quality_rank
    - total_objects_by_type (when object detection enabled)
    - missing_expected_objects (when expected objects configured)
    """
    total = len(rows)
    kept_count = len(kept_rows)

    rejected_by_reason: dict[str, int] = {}
    for row in rows:
        if row["decision"] == "reject":
            reason = row["reason"]
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1

    score_keys = ["blur_score", "gradient_score", "brightness_score"]
    score_distributions: dict[str, dict[str, float]] = {}
    for key in score_keys:
        values = [float(row[key]) for row in rows]
        if values:
            arr = np.array(values)
            score_distributions[key] = {
                "min": float(arr.min()),
                "max": float(arr.max()),
                "mean": float(arr.mean()),
                "std": float(arr.std()),
            }
        else:
            score_distributions[key] = {"min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}

    # Quality rank computation for kept frames
    # quality_rank = normalize(blur_score) * 0.4
    #               + normalize(gradient_score) * 0.3
    #               + normalize(brightness_score) * 0.3
    # where normalize(x) = (x - min) / (max - min) across all images
    kept_frames: list[dict] = []
    total_objects_by_type: dict[str, int] = {}
    missing_expected_objects: list[dict] = []

    if kept_rows:
        # Compute global min/max for normalization across ALL images
        all_blur = np.array([float(r["blur_score"]) for r in rows])
        all_grad = np.array([float(r["gradient_score"]) for r in rows])
        all_bright = np.array([float(r["brightness_score"]) for r in rows])

        def _normalize(values: np.ndarray, val: float) -> float:
            vmin, vmax = float(values.min()), float(values.max())
            if vmax == vmin:
                return 0.0
            return (val - vmin) / (vmax - vmin)

        for row in kept_rows:
            qr = (
                _normalize(all_blur, float(row["blur_score"])) * 0.4
                + _normalize(all_grad, float(row["gradient_score"])) * 0.3
                + _normalize(all_bright, float(row["brightness_score"])) * 0.3
            )
            frame_info: dict = {"filename": row["filename"], "quality_rank": round(qr, 6)}

            if object_counts_map and row["filename"] in object_counts_map:
                counts = dict(object_counts_map[row["filename"]])
                frame_info["object_counts"] = counts
                for cls, cnt in counts.items():
                    total_objects_by_type[cls] = total_objects_by_type.get(cls, 0) + cnt
                if expected_objects:
                    missing = _check_missing_expected(counts, expected_objects)
                    if missing:
                        missing_expected_objects.append(
                            {"filename": row["filename"], "missing": missing}
                        )

            kept_frames.append(frame_info)

    result: dict = {
        "total_images": total,
        "kept_images": kept_count,
        "rejected_by_reason": rejected_by_reason,
        "score_distributions": score_distributions,
        "kept_frames": kept_frames,
    }

    if total_objects_by_type:
        result["total_objects_by_type"] = total_objects_by_type
    if missing_expected_objects:
        result["missing_expected_objects"] = missing_expected_objects

    return result


def _write_summary_json(output_dir: Path, stats: dict) -> Path:
    """Write triage summary statistics to triage_summary.json."""
    summary_path = output_dir / "triage_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2)
    logger.info("Summary JSON written to %s", summary_path)
    return summary_path


def _copy_kept_frames(kept_rows: list[dict], input_dir: Path, kept_dir: Path) -> None:
    """Copy kept frames to a separate directory, preserving metadata."""
    kept_dir.mkdir(parents=True, exist_ok=True)
    for row in kept_rows:
        src = input_dir / row["filename"]
        dst = kept_dir / row["filename"]
        shutil.copy2(src, dst)
    logger.info("Copied %d kept frames to %s", len(kept_rows), kept_dir)


def _generate_timelapse(kept_paths: list[Path], output_dir: Path, fps: float) -> Path | None:
    """Generate a timelapse video from kept frames.

    Uses codec fallback chain: mp4v -> avc1 -> XVID -> skip with warning.
    Returns the path to the generated video, or None if no codec works.
    """
    if not kept_paths:
        logger.info("No kept frames; skipping timelapse video generation.")
        return None

    # Read first frame to determine dimensions
    first_frame = cv2.imread(str(kept_paths[0]), cv2.IMREAD_COLOR)
    if first_frame is None:
        logger.warning("Could not read first kept frame for timelapse; skipping video.")
        return None

    height, width = first_frame.shape[:2]
    output_path = output_dir / "kept_timelapse.mp4"

    codec_candidates = ["mp4v", "avc1", "XVID"]
    writer = None
    used_codec = None

    for codec in codec_candidates:
        fourcc = cv2.VideoWriter_fourcc(*codec)
        w = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
        if w.isOpened():
            writer = w
            used_codec = codec
            break
        else:
            w.release()

    if writer is None:
        logger.warning("No working video codec found; skipping timelapse video generation.")
        return None

    try:
        for frame_path in kept_paths:
            frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            # Resize if dimensions don't match
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(frame)
    finally:
        writer.release()

    if not output_path.exists() or output_path.stat().st_size == 0:
        logger.warning("Timelapse video was not written successfully.")
        return None

    logger.info("Timelapse video written to %s (codec: %s)", output_path, used_codec)
    return output_path


def run_triage(config: TriageConfig) -> TriageSummary:
    if not config.input_dir.exists() or not config.input_dir.is_dir():
        raise ValueError(
            f"Input directory does not exist or is not a directory: {config.input_dir}"
        )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.rejected_dir.mkdir(parents=True, exist_ok=True)

    report_path = config.output_dir / "triage_report.csv"
    image_paths = _sorted_image_paths(config.input_dir)

    # Load object detection model if enabled
    net: cv2.dnn.Net | None = None
    class_names: list[str] = []
    if config.detect_objects and config.model_dir is not None:
        net, class_names = _load_detection_model(config.model_dir)

    rows: list[dict[str, str]] = []
    object_counts_map: dict[str, dict[str, int]] = {}
    rejected_by_reason: Counter[str] = Counter()
    kept_hashes: list[tuple[int, np.ndarray]] = []
    next_group_id = 1
    kept_images = 0

    for image_path in image_paths:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            blur_score = 0.0
            gradient_score = 0.0
            brightness_score = 0.0
            car_count = 0
            person_count = 0
            decision = "reject"
            reason = "unreadable"
            duplicate_group = ""
            rejected_by_reason[reason] += 1
            shutil.copy2(image_path, config.rejected_dir / image_path.name)
        else:
            blur_score = _compute_blur_score(image)
            gradient_score = _compute_gradient_score(image)
            brightness_score = _compute_brightness_score(image)
            duplicate_group = ""

            # Object detection
            if net is not None:
                object_counts = _detect_objects(image, net, class_names)
                object_counts_map[image_path.name] = object_counts
                car_count = object_counts.get("car", 0)
                person_count = object_counts.get("person", 0)
            else:
                car_count = 0
                person_count = 0

            if blur_score < config.blur_threshold or gradient_score < config.gradient_threshold:
                decision = "reject"
                reason = "blur"
            elif brightness_score < config.brightness_threshold:
                decision = "reject"
                reason = "low_light"
            else:
                current_hash = _average_hash(image)
                duplicate_match_group_id = None
                for group_id, accepted_hash in kept_hashes:
                    if _hamming_distance(current_hash, accepted_hash) <= config.duplicate_distance_threshold:
                        duplicate_match_group_id = group_id
                        break

                if duplicate_match_group_id is not None:
                    decision = "reject"
                    reason = "duplicate"
                    duplicate_group = f"group_{duplicate_match_group_id:04d}"
                else:
                    group_id = next_group_id
                    next_group_id += 1
                    kept_hashes.append((group_id, current_hash))
                    decision = "keep"
                    reason = ""
                    kept_images += 1

            if decision == "reject":
                rejected_by_reason[reason] += 1
                shutil.copy2(image_path, config.rejected_dir / image_path.name)

        rows.append(
            {
                "filename": image_path.name,
                "decision": decision,
                "reason": reason,
                "blur_score": f"{blur_score:.4f}",
                "gradient_score": f"{gradient_score:.4f}",
                "brightness_score": f"{brightness_score:.4f}",
                "duplicate_group": duplicate_group,
                "car_count": str(car_count),
                "person_count": str(person_count),
            }
        )

    with report_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "filename",
                "decision",
                "reason",
                "blur_score",
                "gradient_score",
                "brightness_score",
                "duplicate_group",
                "car_count",
                "person_count",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Total images: %d", len(image_paths))
    logger.info("Kept images: %d", kept_images)
    for reason in sorted(rejected_by_reason):
        logger.info("Rejected (%s): %d", reason, rejected_by_reason[reason])

    # --- New outputs: JSON summary, kept directory, timelapse video ---
    kept_rows = [r for r in rows if r["decision"] == "keep"]

    # JSON summary
    stats = _compute_statistics(
        rows,
        kept_rows,
        object_counts_map=object_counts_map if object_counts_map else None,
        expected_objects=config.expected_objects,
    )
    _write_summary_json(config.output_dir, stats)

    # Kept directory
    if config.kept_dir is not None:
        _copy_kept_frames(kept_rows, config.input_dir, config.kept_dir)

    # Timelapse video
    if config.generate_video and kept_rows:
        kept_paths = [config.input_dir / r["filename"] for r in kept_rows]
        _generate_timelapse(kept_paths, config.output_dir, config.video_fps)

    return TriageSummary(
        total_images=len(image_paths),
        kept_images=kept_images,
        rejected_by_reason=dict(rejected_by_reason),
        report_path=report_path,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Single-camera snapshot triage pipeline")
    parser.add_argument("input_dir", type=Path, help="Directory containing JPG/PNG images")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory where triage_report.csv is written (default: output)",
    )
    parser.add_argument(
        "--rejected-dir",
        type=Path,
        default=Path("rejected"),
        help="Directory where rejected image copies are stored (default: rejected)",
    )
    parser.add_argument(
        "--blur-threshold",
        type=float,
        default=100.0,
        help="Reject images with Laplacian variance below this value",
    )
    parser.add_argument(
        "--gradient-threshold",
        type=float,
        default=20.0,
        help="Reject images with gradient magnitude variance below this value",
    )
    parser.add_argument(
        "--brightness-threshold",
        type=float,
        default=55.0,
        help="Reject images with mean grayscale brightness below this value",
    )
    parser.add_argument(
        "--duplicate-distance-threshold",
        type=int,
        default=5,
        help="Reject image as duplicate when average-hash Hamming distance is <= threshold",
    )
    parser.add_argument(
        "--generate-video",
        action="store_true",
        default=False,
        help="Generate a timelapse video from kept frames (default: off)",
    )
    parser.add_argument(
        "--video-fps",
        type=float,
        default=5.0,
        help="Frame rate for the timelapse video (default: 5.0)",
    )
    parser.add_argument(
        "--kept-dir",
        type=Path,
        default=None,
        help="Directory to copy kept frames to (default: skip copy)",
    )
    parser.add_argument(
        "--detect-objects",
        action="store_true",
        default=False,
        help="Run MobileNet-SSD object detection and add car/person counts (default: off)",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("models"),
        help="Directory containing MobileNetSSD_deploy.prototxt and .caffemodel (default: models)",
    )
    parser.add_argument(
        "--expected-objects",
        type=str,
        default="",
        help="Comma-separated list of expected objects (e.g., car,person)",
    )
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    expected_objects = None
    if args.expected_objects:
        expected_objects = [s.strip() for s in args.expected_objects.split(",") if s.strip()]

    config = TriageConfig(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        rejected_dir=args.rejected_dir,
        blur_threshold=args.blur_threshold,
        gradient_threshold=args.gradient_threshold,
        brightness_threshold=args.brightness_threshold,
        duplicate_distance_threshold=args.duplicate_distance_threshold,
        generate_video=args.generate_video,
        video_fps=args.video_fps,
        kept_dir=args.kept_dir,
        detect_objects=args.detect_objects,
        model_dir=args.model_dir,
        expected_objects=expected_objects,
    )

    run_triage(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
