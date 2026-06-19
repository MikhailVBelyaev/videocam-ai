import json
import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, mock_open, patch

import pytz

from tg_bot.bot import (
    _format_admin_message,
    _format_state_message,
    _format_uptime,
    _get_latest_image_path,
    _get_latest_run_date,
    _is_admin_chat,
    _is_fresh,
    _query_container_states,
    _read_latest_summary,
    _summarize_live_output,
    send_photo,
)


class TgBotAdminTests(unittest.TestCase):
    def test_telegram_http_transport_logs_are_suppressed(self):
        for logger_name in ("httpx", "httpcore", "telegram"):
            self.assertGreaterEqual(logging.getLogger(logger_name).level, logging.WARNING)

    def test_format_admin_message_with_all_fields(self):
        summary = {
            "total_images": 150,
            "kept_images": 23,
            "total_objects_by_type": {"car": 45, "person": 12},
            "missing_expected_objects": [{"filename": "IMG_0001.jpg", "missing": ["car"]}],
        }
        text = _format_admin_message(summary, "2026-06-18", fresh=True)
        self.assertIn("150", text)
        self.assertIn("23", text)
        self.assertIn("45", text)
        self.assertIn("12", text)
        self.assertIn("1 frames", text)
        self.assertIn("2026-06-18", text)
        self.assertIn("Fresh", text)

    def test_format_admin_message_defaults_when_keys_missing(self):
        summary = {}
        text = _format_admin_message(summary, None, fresh=False)
        self.assertIn("0 total, 0 kept", text)
        self.assertIn("0 cars, 0 people", text)
        self.assertNotIn("Missing expected", text)
        self.assertIn("Unknown", text)
        self.assertIn("Stale", text)

    def test_summarize_live_output_counts_latest_folder_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                open(os.path.join(folder, "frame_001_vehicle.jpg"), "w").close()
                open(os.path.join(folder, "frame_002_person.png"), "w").close()
                open(os.path.join(folder, "clip_001_vehicle.mp4"), "w").close()

                result = _summarize_live_output()

        self.assertIsNotNone(result)
        self.assertEqual(result["summary_source"], "live_output")
        self.assertEqual(result["total_images"], 2)
        self.assertEqual(result["kept_images"], 2)
        self.assertEqual(result["video_files"], 1)
        self.assertEqual(result["total_objects_by_type"], {"car": 2, "person": 1})
        self.assertIn(result["latest_file"], {
            "frame_001_vehicle.jpg",
            "frame_002_person.png",
            "clip_001_vehicle.mp4",
        })

    def test_format_admin_message_includes_live_output_details(self):
        summary = {
            "summary_source": "live_output",
            "total_images": 2,
            "kept_images": 2,
            "video_files": 1,
            "total_objects_by_type": {"car": 2, "person": 1},
            "latest_file": "frame_001_vehicle.jpg",
            "latest_file_time": "2026-06-19T10:23:00+05:00",
            "missing_expected_objects": [],
        }
        text = _format_admin_message(summary, "2026-06-19", fresh=True)

        self.assertIn("2 total, 2 kept", text)
        self.assertIn("1", text)
        self.assertIn("frame_001_vehicle.jpg", text)
        self.assertIn("Live output summary", text)

    def test_is_admin_chat_matching_id(self):
        with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "12345"}, clear=False):
            with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"):
                update = MagicMock()
                update.effective_chat.id = 12345
                self.assertTrue(_is_admin_chat(update))

    def test_is_admin_chat_non_matching_id(self):
        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"):
            update = MagicMock()
            update.effective_chat.id = 99999
            self.assertFalse(_is_admin_chat(update))

    def test_read_latest_summary_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                path = os.path.join(tmp, "triage_summary.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"total_images": 10}, f)
                result = _read_latest_summary()
                self.assertEqual(result, {"total_images": 10})

    def test_read_latest_summary_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                result = _read_latest_summary()
                self.assertIsNone(result)

    def test_read_latest_summary_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                path = os.path.join(tmp, "triage_summary.json")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("not json")
                result = _read_latest_summary()
                self.assertIsNone(result)

    def test_get_latest_run_date_finds_max_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                os.makedirs(os.path.join(tmp, "2026-06-17"))
                os.makedirs(os.path.join(tmp, "2026-06-18"))
                os.makedirs(os.path.join(tmp, "not-a-date"))
                result = _get_latest_run_date()
                self.assertEqual(result, "2026-06-18")

    def test_get_latest_run_date_no_valid_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                os.makedirs(os.path.join(tmp, "not-a-date"))
                result = _get_latest_run_date()
                self.assertIsNone(result)

    def test_is_fresh_within_24h(self):
        today = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
        self.assertTrue(_is_fresh(today))

    def test_is_fresh_stale(self):
        old = (datetime.now(pytz.UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
        self.assertFalse(_is_fresh(old))

    def test_is_fresh_none(self):
        self.assertFalse(_is_fresh(None))

    # ------- QA: additional focused tests -------

    def test_format_admin_message_no_missing_expected(self):
        """When missing_expected_objects is empty, 'Missing expected' line is absent."""
        summary = {
            "total_images": 10,
            "kept_images": 5,
            "total_objects_by_type": {"car": 2, "person": 1},
            "missing_expected_objects": [],
        }
        text = _format_admin_message(summary, "2026-06-18", fresh=True)
        self.assertIn("10 total, 5 kept", text)
        self.assertNotIn("Missing expected", text)

    def test_format_admin_message_without_total_objects_by_type_key(self):
        """When 'total_objects_by_type' is missing entirely, defaults to 0."""
        summary = {"total_images": 3, "kept_images": 1}
        text = _format_admin_message(summary, "2026-06-17", fresh=False)
        self.assertIn("0 cars, 0 people", text)

    def test_is_fresh_today_is_fresh(self):
        """Today's date (parsed as midnight UTC) is always within 24h."""
        today = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
        self.assertTrue(_is_fresh(today))

    def test_is_fresh_two_days_ago_is_stale(self):
        """A date two days ago (at midnight UTC) is always beyond 24h."""
        two_days_ago = (datetime.now(pytz.UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
        self.assertFalse(_is_fresh(two_days_ago))

    def test_is_fresh_invalid_date_string(self):
        """An invalid date string returns False."""
        self.assertFalse(_is_fresh("not-a-date"))

    def test_get_latest_run_date_empty_output_dir(self):
        """An empty output directory returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                result = _get_latest_run_date()
                self.assertIsNone(result)

    def test_read_latest_summary_os_error(self):
        """An unreadable file (OSError) returns None."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                path = os.path.join(tmp, "triage_summary.json")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("{}")
                with patch("builtins.open", mock_open()) as mocked_open:
                    mocked_open.side_effect = OSError("unreadable")
                    result = _read_latest_summary()
                self.assertIsNone(result)

    def test_is_admin_chat_string_vs_int_coercion(self):
        """Admin chat ID comparison works with int chat id and string env var."""
        with patch("tg_bot.bot.ADMIN_CHAT_ID", "55555"):
            update = MagicMock()
            update.effective_chat.id = 55555
            self.assertTrue(_is_admin_chat(update))

    def test_admin_command_non_admin_silent_return(self):
        """The admin_command handler must reply nothing for non-admin chats."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import admin_command

        update = MagicMock()
        update.effective_chat.id = 99999  # non-admin
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            # reply_text should NOT have been called
            update.message.reply_text.assert_not_called()

    def test_admin_command_admin_no_data(self):
        """Admin chat with no triage or live output data gets a clear message."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import admin_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._read_latest_summary", return_value=None), \
             patch("tg_bot.bot._summarize_live_output", return_value=None):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            update.message.reply_text.assert_called_once_with(
                "No output data available."
            )

    def test_admin_command_admin_uses_live_output_fallback(self):
        """Admin chat gets live output summary when triage summary is absent."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import admin_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        summary = {
            "summary_source": "live_output",
            "total_images": 3,
            "kept_images": 3,
            "video_files": 1,
            "total_objects_by_type": {"car": 2, "person": 1},
            "latest_file": "frame_001_vehicle.jpg",
            "missing_expected_objects": [],
        }

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._read_latest_summary", return_value=None), \
             patch("tg_bot.bot._summarize_live_output", return_value=summary), \
             patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"), \
             patch("tg_bot.bot._is_fresh", return_value=True), \
             patch("tg_bot.bot._get_latest_image_path", return_value=None):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            text = update.message.reply_text.call_args_list[0][0][0]
            self.assertIn("3 total, 3 kept", text)
            self.assertIn("Live output summary", text)

    def test_admin_command_admin_with_data(self):
        """Admin chat with valid summary gets a formatted Markdown reply."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import admin_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        summary = {
            "total_images": 50,
            "kept_images": 10,
            "total_objects_by_type": {"car": 8, "person": 2},
            "missing_expected_objects": [],
        }

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._read_latest_summary", return_value=summary), \
             patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-18"), \
             patch("tg_bot.bot._is_fresh", return_value=True), \
             patch("tg_bot.bot._get_latest_image_path", return_value=None):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            call_args = update.message.reply_text.call_args_list[0]
            text = call_args[0][0]
            self.assertIn("50", text)
            self.assertIn("10", text)
            self.assertIn("8", text)
            self.assertIn("2", text)
            self.assertEqual(call_args[1]["parse_mode"], "Markdown")

    def test_get_latest_run_date_oserror(self):
        """OSError during directory listing returns None without crashing."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "2026-06-19"))
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.os.listdir", side_effect=OSError("permission denied")):
                result = _get_latest_run_date()
                self.assertIsNone(result)

    def test_summarize_live_output_no_media_returns_none(self):
        """_summarize_live_output returns None when folder has no media files."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp):
                folder = os.path.join(tmp, "2026-06-19")
                os.makedirs(folder)
                # Only hidden/dot files and non-media files
                open(os.path.join(folder, ".hidden"), "w").close()
                open(os.path.join(folder, "notes.txt"), "w").close()

                result = _summarize_live_output()

        self.assertIsNone(result)

    def test_summarize_live_output_oserror_returns_none(self):
        """_summarize_live_output returns None when listing the latest folder fails."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "2026-06-19"))
            def listdir_side_effect(path):
                if path == tmp:
                    return ["2026-06-19"]
                raise OSError("I/O error")
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.os.listdir", side_effect=listdir_side_effect):
                result = _summarize_live_output()

        self.assertIsNone(result)

    # ------- /state command tests -------

    def test_format_state_message_all_statuses(self):
        """_format_state_message renders running, exited, not-found, and unknown statuses."""
        states = [
            {"name": "cams_grabber", "status": "running", "health": "healthy", "started_at": "2026-06-19T08:00:00Z"},
            {"name": "tg_bot", "status": "exited", "health": "N/A", "started_at": "2026-06-19T07:00:00Z"},
            {"name": "sys_monitor", "status": "not-found", "health": "N/A", "started_at": None},
            {"name": "web_viewer", "status": "restarting", "health": "starting", "started_at": "2026-06-19T09:00:00Z"},
        ]
        text = _format_state_message(states)
        self.assertIn("cams_grabber", text)
        self.assertIn("tg_bot", text)
        self.assertIn("sys_monitor", text)
        self.assertIn("web_viewer", text)
        self.assertIn("running", text)
        self.assertIn("exited", text)
        self.assertIn("not-found", text)
        self.assertIn("restarting", text)
        self.assertIn("healthy", text)
        self.assertIn("starting", text)

    def test_format_state_message_includes_uptime(self):
        """_format_state_message includes uptime when started_at is present."""
        states = [
            {"name": "cams_grabber", "status": "running", "health": "healthy", "started_at": "2026-06-19T08:00:00Z"},
        ]
        text = _format_state_message(states)
        # Uptime should be present and not "N/A" for a recent start time
        self.assertIn("up", text)
        self.assertNotIn("N/A", text)

    def test_format_state_message_not_found_no_uptime(self):
        """_format_state_message shows N/A uptime when started_at is None."""
        states = [
            {"name": "sys_monitor", "status": "not-found", "health": "N/A", "started_at": None},
        ]
        text = _format_state_message(states)
        self.assertIn("N/A", text)

    def test_format_uptime_seconds(self):
        """_format_uptime returns seconds for very recent starts."""
        from unittest.mock import patch
        now = datetime(2026, 6, 19, 10, 0, 30, tzinfo=pytz.UTC)
        with patch("tg_bot.bot.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _format_uptime("2026-06-19T10:00:00Z")
            self.assertTrue(result.startswith("up "))
            self.assertIn("s", result)

    def test_format_uptime_hours_minutes(self):
        """_format_uptime returns hours and minutes for multi-hour uptime."""
        from unittest.mock import patch
        now = datetime(2026, 6, 19, 14, 30, 0, tzinfo=pytz.UTC)
        with patch("tg_bot.bot.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _format_uptime("2026-06-19T08:00:00Z")
            self.assertIn("6h", result)
            self.assertIn("30m", result)

    def test_format_uptime_days(self):
        """_format_uptime returns days for long-running containers."""
        from unittest.mock import patch
        now = datetime(2026, 6, 22, 10, 0, 0, tzinfo=pytz.UTC)
        with patch("tg_bot.bot.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _format_uptime("2026-06-19T08:00:00Z")
            self.assertIn("3d", result)

    def test_format_uptime_none(self):
        """_format_uptime returns N/A when started_at is None."""
        self.assertEqual(_format_uptime(None), "N/A")

    def test_format_uptime_malformed(self):
        """_format_uptime returns the raw string when parsing fails."""
        self.assertEqual(_format_uptime("not-a-date"), "not-a-date")

    def test_query_container_states_docker_unavailable(self):
        """_query_container_states returns None when docker import failed."""
        with patch("tg_bot.bot.docker", None), \
             patch("tg_bot.bot.DockerException", None):
            result = _query_container_states()
            self.assertIsNone(result)

    def test_state_command_non_admin_silent_return(self):
        """The state_command handler must reply nothing for non-admin chats."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import state_command

        update = MagicMock()
        update.effective_chat.id = 99999  # non-admin
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"):
            coro = state_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            update.message.reply_text.assert_not_called()

    def test_state_command_admin_runtime_unavailable(self):
        """Admin chat gets error message when Docker runtime is unavailable."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import state_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._query_container_states", return_value=None):
            coro = state_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            update.message.reply_text.assert_called_once_with(
                "Container runtime unavailable. Docker socket not mounted?"
            )

    def test_state_command_admin_with_states(self):
        """Admin chat gets formatted Markdown reply when runtime returns states."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import state_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        states = [
            {"name": "cams_grabber", "status": "running", "health": "healthy", "started_at": "2026-06-19T08:00:00Z"},
            {"name": "tg_bot", "status": "running", "health": "N/A", "started_at": "2026-06-19T08:00:00Z"},
            {"name": "sys_monitor", "status": "running", "health": "N/A", "started_at": "2026-06-19T08:00:00Z"},
            {"name": "web_viewer", "status": "running", "health": "N/A", "started_at": "2026-06-19T08:00:00Z"},
        ]

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._query_container_states", return_value=states):
            coro = state_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            call_args = update.message.reply_text.call_args
            text = call_args[0][0]
            self.assertIn("cams_grabber", text)
            self.assertIn("Container Status", text)
            self.assertEqual(call_args[1]["parse_mode"], "Markdown")

    # ------- QA: additional focused /state tests -------

    def test_query_container_states_docker_exception(self):
        """_query_container_states returns None when DockerClient.from_env raises DockerException."""
        from docker.errors import DockerException as RealDockerException
        mock_docker = MagicMock()
        mock_docker.DockerClient.from_env.side_effect = RealDockerException("Connection refused")
        with patch("tg_bot.bot.docker", mock_docker), \
             patch("tg_bot.bot.DockerException", RealDockerException):
            result = _query_container_states()
        self.assertIsNone(result)

    def test_query_container_states_returns_proper_structure(self):
        """_query_container_states returns dicts with name, status, health, started_at keys."""
        mock_container = MagicMock()
        mock_container.attrs = {
            "State": {
                "Status": "running",
                "Health": {"Status": "healthy"},
                "StartedAt": "2026-06-19T08:00:00Z",
            }
        }
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container

        mock_docker = MagicMock()
        mock_docker.DockerClient.from_env.return_value = mock_client

        with patch("tg_bot.bot.docker", mock_docker), \
             patch("tg_bot.bot.EXPECTED_CONTAINERS", ["test_svc"]):
            result = _query_container_states()

        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["name"], "test_svc")
        self.assertEqual(entry["status"], "running")
        self.assertEqual(entry["health"], "healthy")
        self.assertEqual(entry["started_at"], "2026-06-19T08:00:00Z")

    def test_query_container_states_mixed_found_not_found(self):
        """_query_container_states handles a mix of found and not-found containers."""
        mock_container = MagicMock()
        mock_container.attrs = {
            "State": {
                "Status": "running",
                "StartedAt": "2026-06-19T08:00:00Z",
            }
        }
        mock_client = MagicMock()
        # cams_grabber is found, others raise NotFound
        from docker.errors import NotFound as RealNotFound
        mock_client.containers.get.side_effect = [
            mock_container,
            RealNotFound("not found"),
            RealNotFound("not found"),
            RealNotFound("not found"),
        ]

        mock_docker = MagicMock()
        mock_docker.DockerClient.from_env.return_value = mock_client

        with patch("tg_bot.bot.docker", mock_docker), \
             patch("tg_bot.bot.NotFound", RealNotFound):
            result = _query_container_states()

        self.assertEqual(len(result), 4)
        self.assertEqual(result[0]["status"], "running")
        self.assertEqual(result[1]["status"], "not-found")
        self.assertEqual(result[2]["status"], "not-found")
        self.assertEqual(result[3]["status"], "not-found")

    def test_query_container_states_closes_client(self):
        """_query_container_states calls client.close() after querying all containers."""
        mock_container = MagicMock()
        mock_container.attrs = {"State": {"Status": "running"}}
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container

        mock_docker = MagicMock()
        mock_docker.DockerClient.from_env.return_value = mock_client

        with patch("tg_bot.bot.docker", mock_docker), \
             patch("tg_bot.bot.EXPECTED_CONTAINERS", ["svc1"]):
            _query_container_states()

        mock_client.close.assert_called_once()

    def test_query_container_states_no_health_key(self):
        """_query_container_states defaults health to N/A when State has no Health key."""
        mock_container = MagicMock()
        mock_container.attrs = {
            "State": {
                "Status": "running",
                "StartedAt": "2026-06-19T08:00:00Z",
                # No Health key at all
            }
        }
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container

        mock_docker = MagicMock()
        mock_docker.DockerClient.from_env.return_value = mock_client

        with patch("tg_bot.bot.docker", mock_docker), \
             patch("tg_bot.bot.EXPECTED_CONTAINERS", ["svc1"]):
            result = _query_container_states()

        self.assertEqual(result[0]["health"], "N/A")

    def test_format_uptime_nanosecond_fraction(self):
        """_format_uptime truncates Docker nanosecond fractional seconds to microseconds."""
        from unittest.mock import patch as ut_patch
        now = datetime(2026, 6, 19, 10, 0, 0, tzinfo=pytz.UTC)
        with ut_patch("tg_bot.bot.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            # Docker returns nanoseconds like 2026-06-19T08:00:00.123456789Z
            # After truncation to microseconds, uptime ~1h 59m (0.123s short of 2h)
            result = _format_uptime("2026-06-19T08:00:00.123456789Z")
            self.assertIn("up", result)
            self.assertIn("1h", result)
            self.assertIn("59m", result)

    def test_format_uptime_minutes_only(self):
        """_format_uptime returns minutes for uptime between 60s and 1h."""
        from unittest.mock import patch as ut_patch
        now = datetime(2026, 6, 19, 10, 5, 0, tzinfo=pytz.UTC)
        with ut_patch("tg_bot.bot.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = _format_uptime("2026-06-19T10:01:00Z")
            self.assertTrue(result.startswith("up "))
            self.assertIn("4m", result)
            # Should NOT contain 'h' since it's under 1 hour
            self.assertNotIn("h", result.replace("4m", ""))

    def test_format_state_message_emoji_mapping(self):
        """_format_state_message uses correct emoji per status: running=✅, exited=❌, not-found=❌, restarting=⚠️, unknown=⚠️."""
        states = [
            {"name": "svc_running", "status": "running", "health": "healthy", "started_at": "2026-06-19T08:00:00Z"},
            {"name": "svc_exited", "status": "exited", "health": "N/A", "started_at": None},
            {"name": "svc_notfound", "status": "not-found", "health": "N/A", "started_at": None},
            {"name": "svc_restarting", "status": "restarting", "health": "starting", "started_at": "2026-06-19T09:00:00Z"},
            {"name": "svc_dead", "status": "dead", "health": "unhealthy", "started_at": None},
        ]
        text = _format_state_message(states)
        lines = text.split("\n")
        # Find each service line
        for line in lines:
            if "svc_running" in line:
                self.assertIn("✅", line)
            elif "svc_exited" in line:
                self.assertIn("❌", line)
            elif "svc_notfound" in line:
                self.assertIn("❌", line)
            elif "svc_restarting" in line:
                self.assertIn("⚠️", line)
            elif "svc_dead" in line:
                self.assertIn("⚠️", line)


class TgBotSenderTests(unittest.TestCase):
    def test_image_sender_job_skips_when_locked(self):
        """A second scheduled job is skipped when the sender lock is already held."""
        import asyncio
        from tg_bot.bot import image_sender_job

        with patch("tg_bot.bot._SENDER_LOCK.locked", return_value=True), \
             patch("tg_bot.bot._send_new_images_iteration") as mock_iter:
            coro = image_sender_job(MagicMock())
            asyncio.get_event_loop().run_until_complete(coro)
            mock_iter.assert_not_called()

    def test_send_new_images_iteration_caps_at_max(self):
        """No more than MAX_IMAGES_PER_ITERATION images are sent in one iteration."""
        from tg_bot.bot import _send_new_images_iteration, MAX_IMAGES_PER_ITERATION
        folder = "2026-06-19"
        files = [f"frame_{i:03d}.jpg" for i in range(10)]

        def listdir_side_effect(path):
            if path == "output":
                return [folder]
            if folder in path:
                return files
            return []

        with patch("tg_bot.bot.os.listdir", side_effect=listdir_side_effect), \
             patch("tg_bot.bot.os.path.isdir", return_value=True), \
             patch("tg_bot.bot.os.path.isfile", return_value=True), \
             patch("tg_bot.bot.are_images_similar", return_value=False), \
             patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
             patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
             patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
             patch("tg_bot.bot.cleanup_old_folders"):
            _send_new_images_iteration()
            self.assertEqual(mock_send.call_count, MAX_IMAGES_PER_ITERATION)

    def test_send_new_images_iteration_cooldown_bypass(self):
        """When cooldown expired, a perceptually similar image is still sent."""
        from tg_bot.bot import _send_new_images_iteration, SEND_COOLDOWN_SECONDS
        folder = "2026-06-19"
        files = ["frame_001.jpg"]

        def listdir_side_effect(path):
            if path == "output":
                return [folder]
            if folder in path:
                return files
            return []

        with patch("tg_bot.bot.os.listdir", side_effect=listdir_side_effect), \
             patch("tg_bot.bot.os.path.isdir", return_value=True), \
             patch("tg_bot.bot.os.path.isfile", return_value=True), \
             patch("tg_bot.bot.are_images_similar", return_value=True), \
             patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
             patch("tg_bot.bot.LAST_SENT_FOLDER", folder), \
             patch("tg_bot.bot.LAST_SENT_IMAGE", os.path.join("output", folder, "prev.jpg")), \
             patch("tg_bot.bot._LAST_SENT_TIMESTAMP", 0.0), \
             patch("tg_bot.bot.cleanup_old_folders"):
            _send_new_images_iteration()
            mock_send.assert_called_once()

    # ------- QA: additional focused sender tests -------

    def test_sender_job_runs_when_lock_free(self):
        """When the sender lock is free, image_sender_job executes the iteration."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import image_sender_job

        mock_lock = MagicMock()
        mock_lock.locked.return_value = False
        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=None)

        context = MagicMock()
        with patch("tg_bot.bot._SENDER_LOCK", mock_lock), \
             patch("tg_bot.bot._send_new_images_iteration") as mock_iter:
            coro = image_sender_job(context)
            asyncio.get_event_loop().run_until_complete(coro)
            mock_iter.assert_called_once()

    def test_iteration_skips_similar_within_cooldown(self):
        """When cooldown has NOT expired, perceptually similar images are skipped."""
        import time
        from tg_bot.bot import _send_new_images_iteration

        folder = "2026-06-19"
        files = ["frame_001.jpg", "frame_002.jpg"]

        def listdir_side_effect(path):
            if path == "output":
                return [folder]
            if folder in path:
                return files
            return []

        recent_timestamp = time.time() - 10  # 10 seconds ago, well within 300s cooldown
        with patch("tg_bot.bot.os.listdir", side_effect=listdir_side_effect), \
             patch("tg_bot.bot.os.path.isdir", return_value=True), \
             patch("tg_bot.bot.os.path.isfile", return_value=True), \
             patch("tg_bot.bot.are_images_similar", return_value=True), \
             patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
             patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
             patch("tg_bot.bot.LAST_SENT_IMAGE", os.path.join("output", folder, "prev.jpg")), \
             patch("tg_bot.bot._LAST_SENT_TIMESTAMP", recent_timestamp), \
             patch("tg_bot.bot.cleanup_old_folders"):
            _send_new_images_iteration()
            # Both images are similar and cooldown is NOT expired, so none should be sent
            mock_send.assert_not_called()

    def test_iteration_sends_all_under_cap(self):
        """When fewer images than MAX_IMAGES_PER_ITERATION exist, all are sent."""
        from tg_bot.bot import _send_new_images_iteration
        folder = "2026-06-19"
        files = ["frame_001.jpg", "frame_002.jpg"]  # Only 2, under default cap of 5

        def listdir_side_effect(path):
            if path == "output":
                return [folder]
            if folder in path:
                return files
            return []

        with patch("tg_bot.bot.os.listdir", side_effect=listdir_side_effect), \
             patch("tg_bot.bot.os.path.isdir", return_value=True), \
             patch("tg_bot.bot.os.path.isfile", return_value=True), \
             patch("tg_bot.bot.are_images_similar", return_value=False), \
             patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
             patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
             patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
             patch("tg_bot.bot.cleanup_old_folders"):
            _send_new_images_iteration()
            self.assertEqual(mock_send.call_count, 2)


class TgBotAdminPhotoTests(unittest.TestCase):
    def test_admin_command_sends_latest_image(self):
        """Admin chat receives the latest image file after the text summary."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import admin_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        update.message.reply_photo = AsyncMock()
        context = MagicMock()

        summary = {
            "total_images": 10,
            "kept_images": 5,
            "total_objects_by_type": {"car": 2, "person": 1},
            "missing_expected_objects": [],
        }

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._read_latest_summary", return_value=summary), \
             patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"), \
             patch("tg_bot.bot._is_fresh", return_value=True), \
             patch("tg_bot.bot._get_latest_image_path", return_value="/output/2026-06-19/frame.jpg"):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            update.message.reply_photo.assert_called_once_with(photo="/output/2026-06-19/frame.jpg")

    def test_admin_command_no_image_fallback(self):
        """When no latest image exists, /admin sends a text fallback instead of a photo."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import admin_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        update.message.reply_photo = AsyncMock()
        context = MagicMock()

        summary = {
            "total_images": 10,
            "kept_images": 5,
            "total_objects_by_type": {"car": 2, "person": 1},
            "missing_expected_objects": [],
        }

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._read_latest_summary", return_value=summary), \
             patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"), \
             patch("tg_bot.bot._is_fresh", return_value=True), \
             patch("tg_bot.bot._get_latest_image_path", return_value=None):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            update.message.reply_photo.assert_not_called()
            self.assertEqual(update.message.reply_text.call_count, 2)
            self.assertEqual(update.message.reply_text.call_args_list[1][0][0], "No latest image available.")

    def test_admin_command_image_send_failure_fallback(self):
        """If reply_photo raises, /admin falls back to a text message."""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import admin_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        update.message.reply_photo = AsyncMock(side_effect=Exception("TelegramError"))
        context = MagicMock()

        summary = {
            "total_images": 10,
            "kept_images": 5,
            "total_objects_by_type": {"car": 2, "person": 1},
            "missing_expected_objects": [],
        }

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._read_latest_summary", return_value=summary), \
             patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"), \
             patch("tg_bot.bot._is_fresh", return_value=True), \
             patch("tg_bot.bot._get_latest_image_path", return_value="/output/2026-06-19/frame.jpg"):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            update.message.reply_photo.assert_called_once()
            self.assertEqual(update.message.reply_text.call_count, 2)
            self.assertEqual(update.message.reply_text.call_args_list[1][0][0], "No latest image available.")


class TgBotSenderPhotoQATests(unittest.TestCase):
    """QA tests for send_photo timestamp behavior (cooldown correctness)."""

    def test_send_photo_updates_last_sent_timestamp_on_success(self):
        """send_photo sets _LAST_SENT_TIMESTAMP when the Telegram API returns 200."""
        import time
        import tg_bot.bot as bot_module

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake image data")
            tmp_path = f.name

        try:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "OK"

            with patch("tg_bot.bot.BOT_TOKEN", "test_token"), \
                 patch("tg_bot.bot.CHAT_ID", "12345"), \
                 patch("tg_bot.bot.requests.post", return_value=mock_response), \
                 patch("tg_bot.bot.save_last_sent_file"), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot._LAST_SENT_TIMESTAMP", 0.0):
                before = time.time()
                result = send_photo(tmp_path)
                after = time.time()
                self.assertTrue(result)
                # Verify _LAST_SENT_TIMESTAMP was updated to a value close to now
                self.assertGreaterEqual(bot_module._LAST_SENT_TIMESTAMP, before)
                self.assertLessEqual(bot_module._LAST_SENT_TIMESTAMP, after)
        finally:
            os.unlink(tmp_path)

    def test_send_photo_does_not_update_timestamp_on_failure(self):
        """send_photo does not update _LAST_SENT_TIMESTAMP when the API returns non-200."""
        import tg_bot.bot as bot_module

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake image data")
            tmp_path = f.name

        try:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.text = "Forbidden"

            original_ts = bot_module._LAST_SENT_TIMESTAMP
            with patch("tg_bot.bot.BOT_TOKEN", "test_token"), \
                 patch("tg_bot.bot.CHAT_ID", "12345"), \
                 patch("tg_bot.bot.requests.post", return_value=mock_response), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None):
                result = send_photo(tmp_path)
                self.assertFalse(result)
                # _LAST_SENT_TIMESTAMP should not have been updated
                self.assertEqual(bot_module._LAST_SENT_TIMESTAMP, original_ts)
        finally:
            os.unlink(tmp_path)


class TgBotLatestImageQATests(unittest.TestCase):
    """QA tests for _get_latest_image_path edge cases."""

    def test_no_dated_folders_returns_none(self):
        """_get_latest_image_path returns None when no dated folders exist."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot._get_latest_run_date", return_value=None):
                result = _get_latest_image_path()
                self.assertIsNone(result)

    def test_empty_folder_returns_none(self):
        """_get_latest_image_path returns None when the dated folder has no images."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            # No files in the folder
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"):
                result = _get_latest_image_path()
                self.assertIsNone(result)

    def test_picks_most_recently_modified_image(self):
        """_get_latest_image_path returns the image with the most recent mtime."""
        import time

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            old_path = os.path.join(folder, "frame_001.jpg")
            new_path = os.path.join(folder, "frame_002.jpg")
            # Create both files
            open(old_path, "w").close()
            open(new_path, "w").close()
            # Make frame_002 newer
            os.utime(old_path, (1000000, 1000000))
            os.utime(new_path, (2000000, 2000000))

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"):
                result = _get_latest_image_path()
                self.assertEqual(result, new_path)

    def test_ignores_non_image_files(self):
        """_get_latest_image_path returns only .jpg/.jpeg/.png files, ignoring others."""
        import time

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            img_path = os.path.join(folder, "frame_001.jpg")
            txt_path = os.path.join(folder, "notes.txt")
            vid_path = os.path.join(folder, "clip.mp4")
            open(img_path, "w").close()
            open(txt_path, "w").close()
            open(vid_path, "w").close()
            # Make non-image files newer
            os.utime(txt_path, (3000000, 3000000))
            os.utime(vid_path, (3000000, 3000000))

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"):
                result = _get_latest_image_path()
                self.assertEqual(result, img_path)

    def test_oserror_returns_none(self):
        """_get_latest_image_path returns None on OSError when listing the folder."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"), \
                 patch("os.listdir", side_effect=OSError("permission denied")):
                result = _get_latest_image_path()
                self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
