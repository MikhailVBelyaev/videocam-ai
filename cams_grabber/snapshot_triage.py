import argparse
import csv
import logging
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriageConfig:
    input_dir: Path
    output_dir: Path
    rejected_dir: Path
    blur_threshold: float = 100.0
    brightness_threshold: float = 55.0
    duplicate_distance_threshold: int = 5


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


def run_triage(config: TriageConfig) -> TriageSummary:
    if not config.input_dir.exists() or not config.input_dir.is_dir():
        raise ValueError(f"Input directory does not exist or is not a directory: {config.input_dir}")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.rejected_dir.mkdir(parents=True, exist_ok=True)

    report_path = config.output_dir / "triage_report.csv"
    image_paths = _sorted_image_paths(config.input_dir)

    rows: list[dict[str, str]] = []
    rejected_by_reason: Counter[str] = Counter()
    kept_hashes: list[tuple[int, np.ndarray]] = []
    next_group_id = 1
    kept_images = 0

    for image_path in image_paths:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            blur_score = 0.0
            brightness_score = 0.0
            decision = "reject"
            reason = "unreadable"
            duplicate_group = ""
            rejected_by_reason[reason] += 1
            shutil.copy2(image_path, config.rejected_dir / image_path.name)
        else:
            blur_score = _compute_blur_score(image)
            brightness_score = _compute_brightness_score(image)
            duplicate_group = ""

            if blur_score < config.blur_threshold:
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
                "brightness_score": f"{brightness_score:.4f}",
                "duplicate_group": duplicate_group,
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
                "brightness_score",
                "duplicate_group",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Total images: %d", len(image_paths))
    logger.info("Kept images: %d", kept_images)
    for reason in sorted(rejected_by_reason):
        logger.info("Rejected (%s): %d", reason, rejected_by_reason[reason])

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
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    config = TriageConfig(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        rejected_dir=args.rejected_dir,
        blur_threshold=args.blur_threshold,
        brightness_threshold=args.brightness_threshold,
        duplicate_distance_threshold=args.duplicate_distance_threshold,
    )

    run_triage(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
