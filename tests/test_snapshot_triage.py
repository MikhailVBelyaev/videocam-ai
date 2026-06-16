import csv
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from cams_grabber.snapshot_triage import TriageConfig, run_triage


class SnapshotTriageTests(unittest.TestCase):
    def _make_checkerboard(self, size: int = 128, high: int = 255, low: int = 0) -> np.ndarray:
        base = ((np.indices((size, size)).sum(axis=0) % 2) * (high - low) + low).astype(np.uint8)
        return cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)

    def test_triage_outputs_expected_decisions_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            input_dir = tmp_dir / "input"
            output_dir = tmp_dir / "output"
            output_dir_second = tmp_dir / "output_second"
            rejected_dir = tmp_dir / "rejected"
            rejected_dir_second = tmp_dir / "rejected_second"

            input_dir.mkdir(parents=True, exist_ok=True)

            sharp = self._make_checkerboard()
            duplicate = sharp.copy()
            blurred = cv2.GaussianBlur(sharp, (31, 31), 0)
            low_light = self._make_checkerboard(high=30, low=0)

            cv2.imwrite(str(input_dir / "01_sharp.png"), sharp)
            cv2.imwrite(str(input_dir / "02_duplicate.png"), duplicate)
            cv2.imwrite(str(input_dir / "03_blur.png"), blurred)
            cv2.imwrite(str(input_dir / "04_low_light.png"), low_light)

            source_before = {
                image_path.name: image_path.read_bytes()
                for image_path in sorted(input_dir.iterdir(), key=lambda p: p.name)
            }

            config = TriageConfig(
                input_dir=input_dir,
                output_dir=output_dir,
                rejected_dir=rejected_dir,
                blur_threshold=200.0,
                brightness_threshold=40.0,
                duplicate_distance_threshold=0,
            )
            summary = run_triage(config)

            self.assertEqual(summary.total_images, 4)
            self.assertEqual(summary.kept_images, 1)
            self.assertEqual(summary.rejected_by_reason.get("duplicate"), 1)
            self.assertEqual(summary.rejected_by_reason.get("blur"), 1)
            self.assertEqual(summary.rejected_by_reason.get("low_light"), 1)

            report_path = output_dir / "triage_report.csv"
            self.assertTrue(report_path.exists())

            with report_path.open("r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))

            self.assertEqual(
                [
                    "filename",
                    "decision",
                    "reason",
                    "blur_score",
                    "brightness_score",
                    "duplicate_group",
                ],
                list(rows[0].keys()),
            )

            decisions = {row["filename"]: (row["decision"], row["reason"]) for row in rows}
            self.assertEqual(decisions["01_sharp.png"], ("keep", ""))
            self.assertEqual(decisions["02_duplicate.png"], ("reject", "duplicate"))
            self.assertEqual(decisions["03_blur.png"], ("reject", "blur"))
            self.assertEqual(decisions["04_low_light.png"], ("reject", "low_light"))

            duplicate_row = next(row for row in rows if row["filename"] == "02_duplicate.png")
            self.assertEqual(duplicate_row["duplicate_group"], "group_0001")

            for filename in ["02_duplicate.png", "03_blur.png", "04_low_light.png"]:
                self.assertTrue((rejected_dir / filename).exists())

            self.assertFalse((rejected_dir / "01_sharp.png").exists())

            source_after = {
                image_path.name: image_path.read_bytes()
                for image_path in sorted(input_dir.iterdir(), key=lambda p: p.name)
            }
            self.assertEqual(source_after, source_before)

            second_summary = run_triage(
                TriageConfig(
                    input_dir=input_dir,
                    output_dir=output_dir_second,
                    rejected_dir=rejected_dir_second,
                    blur_threshold=200.0,
                    brightness_threshold=40.0,
                    duplicate_distance_threshold=0,
                )
            )
            self.assertEqual(second_summary.total_images, summary.total_images)
            self.assertEqual(second_summary.kept_images, summary.kept_images)
            self.assertEqual(second_summary.rejected_by_reason, summary.rejected_by_reason)

            with (output_dir_second / "triage_report.csv").open("r", encoding="utf-8", newline="") as fh:
                rows_second = list(csv.DictReader(fh))

            decisions_second = {row["filename"]: (row["decision"], row["reason"]) for row in rows_second}
            self.assertEqual(decisions_second, decisions)

            duplicate_group_second = {
                row["filename"]: row["duplicate_group"] for row in rows_second
            }
            self.assertEqual(duplicate_group_second["02_duplicate.png"], "group_0001")


if __name__ == "__main__":
    unittest.main()
