import json
import os
import tempfile
import unittest
from unittest.mock import patch

from web_viewer.app import (
    _get_latest_image_links,
    _get_latest_run_date,
    _is_fresh,
    _read_latest_summary,
    _render_admin_page,
    app,
)


class WebViewerAdminTests(unittest.TestCase):
    def test_admin_page_with_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                # Create dated folder and summary
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                open(os.path.join(folder, "frame_001.jpg"), "w").close()
                summary = {
                    "total_images": 150,
                    "kept_images": 23,
                    "total_objects_by_type": {"car": 45, "person": 12},
                    "missing_expected_objects": [],
                }
                with open(os.path.join(tmp, "triage_summary.json"), "w", encoding="utf-8") as f:
                    json.dump(summary, f)

                client = app.test_client()
                response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("150", html)
        self.assertIn("23", html)
        self.assertIn("45", html)
        self.assertIn("12", html)
        self.assertIn("2026-06-19", html)
        self.assertIn("frame_001.jpg", html)

    def test_admin_page_missing_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                client = app.test_client()
                response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("No triage data available", html)

    def test_admin_page_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                with open(os.path.join(tmp, "triage_summary.json"), "w", encoding="utf-8") as f:
                    f.write("not-json")

                client = app.test_client()
                response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("No triage data available", html)

    def test_static_file_serving(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                image_path = os.path.join(folder, "frame.jpg")
                with open(image_path, "wb") as f:
                    f.write(b"fake-image-data")

                client = app.test_client()
                response = client.get("/2026-06-19/frame.jpg")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"fake-image-data")
        self.assertEqual(response.mimetype, "image/jpeg")

    def test_admin_page_defaults_counts_when_keys_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                open(os.path.join(folder, "frame.jpg"), "w").close()
                summary = {"total_images": 10, "kept_images": 5}
                with open(os.path.join(tmp, "triage_summary.json"), "w", encoding="utf-8") as f:
                    json.dump(summary, f)

                client = app.test_client()
                response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("0 cars, 0 people", html)
        self.assertNotIn("Missing expected", html)

    def test_admin_page_shows_missing_expected_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                open(os.path.join(folder, "frame.jpg"), "w").close()
                summary = {
                    "total_images": 10,
                    "kept_images": 5,
                    "total_objects_by_type": {},
                    "missing_expected_objects": [
                        {"filename": "a.jpg", "missing": ["car"]},
                        {"filename": "b.jpg", "missing": ["person"]},
                    ],
                }
                with open(os.path.join(tmp, "triage_summary.json"), "w", encoding="utf-8") as f:
                    json.dump(summary, f)

                client = app.test_client()
                response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("Missing expected", html)
        self.assertIn("2 frames", html)

    def test_get_latest_run_date_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                result = _get_latest_run_date()
        self.assertIsNone(result)

    def test_get_latest_run_date_ignores_non_date_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                os.makedirs(os.path.join(tmp, "2026-06-18"))
                os.makedirs(os.path.join(tmp, "not-a-date"))
                os.makedirs(os.path.join(tmp, "2026-06-20"))
                result = _get_latest_run_date()
        self.assertEqual(result, "2026-06-20")

    def test_is_fresh_within_24h(self):
        self.assertTrue(_is_fresh("2026-06-19"))

    def test_is_fresh_stale(self):
        self.assertFalse(_is_fresh("2020-01-01"))

    def test_is_fresh_none(self):
        self.assertFalse(_is_fresh(None))

    def test_read_latest_summary_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                result = _read_latest_summary()
        self.assertIsNone(result)

    def test_get_latest_image_links_no_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                os.makedirs(os.path.join(tmp, "2026-06-19"))
                result = _get_latest_image_links("2026-06-19")
        self.assertEqual(result, [])

    def test_render_admin_page_structure(self):
        html = _render_admin_page(
            {"total_images": 5, "kept_images": 2, "total_objects_by_type": {"car": 1}, "missing_expected_objects": []},
            "2026-06-19",
            True,
            ["/2026-06-19/img.jpg"],
        )
        self.assertIn("Admin Dashboard", html)
        self.assertIn("5 total, 2 kept", html)
        self.assertIn("1 cars, 0 people", html)
        self.assertIn("img.jpg", html)
        self.assertIn("Fresh", html)


class WebViewerQAValidationTests(unittest.TestCase):
    """QA validation tests covering failure paths, edge cases, and
    boundary conditions in the web_viewer /admin page implementation."""

    # ---- _read_latest_summary error paths ----

    def test_read_latest_summary_os_error(self):
        """An unreadable file (OSError) returns None without crashing."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                path = os.path.join(tmp, "triage_summary.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"total_images": 1}, f)
                # Patch open to raise OSError on read
                with patch("builtins.open", side_effect=OSError("Permission denied")):
                    result = _read_latest_summary()
        self.assertIsNone(result)

    # ---- _get_latest_run_date error paths ----

    def test_get_latest_run_date_os_error(self):
        """OSError during listdir returns None without crashing."""
        with patch("os.listdir", side_effect=OSError("Permission denied")):
            result = _get_latest_run_date()
        self.assertIsNone(result)

    def test_get_latest_run_date_single_date_dir(self):
        """A single valid date directory is returned correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                os.makedirs(os.path.join(tmp, "2026-06-19"))
                result = _get_latest_run_date()
        self.assertEqual(result, "2026-06-19")

    # ---- _get_latest_image_links edge cases ----

    def test_get_latest_image_links_caps_at_five(self):
        """Only the 5 most recent images are linked when more exist."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                # Create 8 image files
                for i in range(8):
                    p = os.path.join(folder, f"frame_{i:03d}.jpg")
                    with open(p, "w") as f:
                        f.write("x")
                result = _get_latest_image_links("2026-06-19")
        self.assertEqual(len(result), 5)
        # All links should start with /2026-06-19/
        for link in result:
            self.assertTrue(link.startswith("/2026-06-19/"))

    def test_get_latest_image_links_filters_by_extension(self):
        """Only .jpg, .jpeg, and .png files are included in links."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                for ext in ("jpg", "jpeg", "png", "txt", "csv", "json"):
                    with open(os.path.join(folder, f"file.{ext}"), "w") as f:
                        f.write("x")
                result = _get_latest_image_links("2026-06-19")
        filenames = [link.split("/")[-1] for link in result]
        self.assertIn("file.jpg", filenames)
        self.assertIn("file.jpeg", filenames)
        self.assertIn("file.png", filenames)
        self.assertNotIn("file.txt", filenames)
        self.assertNotIn("file.csv", filenames)
        self.assertNotIn("file.json", filenames)

    def test_get_latest_image_links_ignores_subdirectories(self):
        """Subdirectories inside a date folder are not treated as image links."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                open(os.path.join(folder, "image.jpg"), "w").close()
                os.makedirs(os.path.join(folder, "thumbnails"))
                result = _get_latest_image_links("2026-06-19")
        self.assertEqual(result, ["/2026-06-19/image.jpg"])

    def test_get_latest_image_links_os_error(self):
        """OSError during directory listing returns empty list without crashing."""
        with patch("os.listdir", side_effect=OSError("Permission denied")):
            result = _get_latest_image_links("2026-06-19")
        self.assertEqual(result, [])

    # ---- _is_fresh error paths ----

    def test_is_fresh_invalid_date_string(self):
        """An invalid date string returns False without crashing."""
        self.assertFalse(_is_fresh("not-a-date"))

    # ---- _render_admin_page edge cases ----

    def test_render_admin_page_none_summary_shows_error(self):
        """When summary is None, error paragraph is rendered with zeroed counts."""
        html = _render_admin_page(None, None, False, [])
        self.assertIn("No triage data available", html)
        self.assertIn("0 total, 0 kept", html)
        self.assertIn("0 cars, 0 people", html)
        self.assertIn("Stale", html)
        self.assertIn("No images found", html)

    def test_render_admin_page_no_links_shows_no_images(self):
        """When links list is empty, 'No images found' is rendered."""
        html = _render_admin_page(
            {"total_images": 10, "kept_images": 3, "total_objects_by_type": {}, "missing_expected_objects": []},
            "2026-06-19",
            True,
            [],
        )
        self.assertIn("No images found", html)
        self.assertIn("Fresh", html)

    def test_render_admin_page_stale_status(self):
        """When fresh=False, 'Stale' is displayed."""
        html = _render_admin_page(
            {"total_images": 5, "kept_images": 1, "total_objects_by_type": {}, "missing_expected_objects": []},
            "2026-01-01",
            False,
            [],
        )
        self.assertIn("Stale", html)
        self.assertNotIn("Fresh", html)

    def test_render_admin_page_non_car_person_objects_ignored(self):
        """Object types other than car and person are not rendered in the stats."""
        html = _render_admin_page(
            {"total_images": 10, "kept_images": 5, "total_objects_by_type": {"car": 3, "person": 1, "truck": 8, "bicycle": 2}, "missing_expected_objects": []},
            "2026-06-19",
            True,
            [],
        )
        self.assertIn("3 cars, 1 people", html)
        # truck and bicycle counts should not appear in the rendered output
        self.assertNotIn("8", html)
        self.assertNotIn("bicycle", html)

    # ---- Static file serving edge cases ----

    def test_static_file_not_found_returns_404(self):
        """Requesting a non-existent static file returns 404."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                client = app.test_client()
                response = client.get("/nonexistent/file.jpg")
        self.assertEqual(response.status_code, 404)

    # ---- admin_page integration edge cases ----

    def test_admin_page_no_date_dirs_no_summary(self):
        """When no date directories and no summary exist, page renders with error."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("web_viewer.app.OUTPUT_DIR", tmp):
                client = app.test_client()
                response = client.get("/admin")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("No triage data available", html)
        self.assertIn("Unknown", html)
