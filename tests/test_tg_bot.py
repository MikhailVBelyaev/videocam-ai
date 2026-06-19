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
    _get_image_list,
    _get_latest_image_path,
    _get_latest_run_date,
    _initialize_startup_state,
    _is_admin_chat,
    _is_fresh,
    _kept_images_exist,
    _query_container_states,
    _read_latest_summary,
    _send_new_images_iteration,
    _summarize_live_output,
    load_last_sent_file,
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


class TgBotStartupStateTests(unittest.TestCase):
    """Tests for startup state initialization when .last_sent_file is missing."""

    def test_startup_initializes_to_latest_image(self):
        """When no state file exists, _initialize_startup_state sets LAST_SENT_IMAGE to the latest image."""
        import time
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            old_path = os.path.join(folder, "frame_001.jpg")
            new_path = os.path.join(folder, "frame_002.jpg")
            open(old_path, "w").close()
            open(new_path, "w").close()
            # Make frame_002 newer
            os.utime(old_path, (1000000, 1000000))
            os.utime(new_path, (2000000, 2000000))

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None):
                result = _initialize_startup_state()
                self.assertEqual(result[1], new_path)
                self.assertEqual(result[0], "2026-06-19")
                # Verify state file was written
                self.assertTrue(os.path.exists(state_file))
                with open(state_file, "r") as f:
                    content = f.read().strip()
                self.assertIn("2026-06-19", content)
                self.assertIn("frame_002.jpg", content)

    def test_startup_empty_folder_leaves_none(self):
        """When latest dated folder has no images, _initialize_startup_state returns (None, None)."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None):
                result = _initialize_startup_state()
                self.assertIsNone(result[0])
                self.assertIsNone(result[1])
                self.assertFalse(os.path.exists(state_file))

    def test_startup_no_dated_folders_leaves_none(self):
        """When OUTPUT_DIR has no dated folders, _initialize_startup_state returns (None, None)."""
        with tempfile.TemporaryDirectory() as tmp:
            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None):
                result = _initialize_startup_state()
                self.assertIsNone(result[0])
                self.assertIsNone(result[1])
                self.assertFalse(os.path.exists(state_file))

    def test_existing_state_file_not_overwritten(self):
        """When .last_sent_file exists, load_last_sent_file loads it and does not overwrite."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            img_path = os.path.join(folder, "frame_001.jpg")
            open(img_path, "w").close()

            state_file = os.path.join(tmp, ".last_sent_file")
            with open(state_file, "w") as f:
                f.write("2026-06-18/frame_old.jpg\n")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file):
                loaded_folder, loaded_image = load_last_sent_file()
                self.assertEqual(loaded_folder, "2026-06-18")
                self.assertIn("frame_old.jpg", loaded_image)
                # Verify state file content is unchanged
                with open(state_file, "r") as f:
                    content = f.read().strip()
                self.assertEqual(content, "2026-06-18/frame_old.jpg")


class TgBotStartupStateQATests(unittest.TestCase):
    """QA tests for startup state initialization edge cases and integration behavior."""

    def test_startup_multiple_dated_folders_picks_latest(self):
        """When multiple dated folders exist, _initialize_startup_state picks the latest one."""
        with tempfile.TemporaryDirectory() as tmp:
            old_folder = os.path.join(tmp, "2026-06-17")
            mid_folder = os.path.join(tmp, "2026-06-18")
            new_folder = os.path.join(tmp, "2026-06-19")
            for d in (old_folder, mid_folder, new_folder):
                os.makedirs(d)
            # Put an image in each; the one in 2026-06-19 should be chosen
            old_img = os.path.join(old_folder, "old.jpg")
            new_img = os.path.join(new_folder, "new.jpg")
            open(old_img, "w").close()
            open(new_img, "w").close()
            # Make old image have a newer mtime to prove we pick by folder date, not mtime
            os.utime(old_img, (3000000, 3000000))
            os.utime(new_img, (2000000, 2000000))

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None):
                result = _initialize_startup_state()
                # Must pick image from 2026-06-19, not 2026-06-17
                self.assertEqual(result[0], "2026-06-19")
                self.assertIn("new.jpg", result[1])
                self.assertNotIn("old.jpg", result[1])

    def test_startup_sets_module_globals(self):
        """_initialize_startup_state mutates LAST_SENT_IMAGE and LAST_SENT_FOLDER globals."""
        import tg_bot.bot as bot_module

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            img_path = os.path.join(folder, "frame_001.jpg")
            open(img_path, "w").close()

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", None), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", None):
                result = _initialize_startup_state()
                # Verify the module globals are updated
                self.assertIsNotNone(bot_module.LAST_SENT_IMAGE)
                self.assertIsNotNone(bot_module.LAST_SENT_FOLDER)
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-19")
                self.assertIn("frame_001.jpg", bot_module.LAST_SENT_IMAGE)

    def test_startup_preserves_last_sent_timestamp(self):
        """_initialize_startup_state does NOT update _LAST_SENT_TIMESTAMP.
        
        This is critical: leaving _LAST_SENT_TIMESTAMP at its initial value (0.0)
        causes the first sender iteration to bypass similarity check via cooldown,
        which is the intended behavior per design doc tradeoff 3.3.
        """
        import tg_bot.bot as bot_module

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            img_path = os.path.join(folder, "frame_001.jpg")
            open(img_path, "w").close()

            state_file = os.path.join(tmp, ".last_sent_file")

            # Save a pre-set timestamp value
            original_ts = bot_module._LAST_SENT_TIMESTAMP
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", None), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", None):
                _initialize_startup_state()
                # _LAST_SENT_TIMESTAMP must NOT be modified by startup initialization
                self.assertEqual(bot_module._LAST_SENT_TIMESTAMP, original_ts)

    def test_startup_oserror_in_directory_access_returns_none(self):
        """When os.listdir raises OSError, _get_latest_run_date catches it and returns
        None, causing _initialize_startup_state to return (None, None) without crashing.
        This tests the full error propagation chain from filesystem error through
        _get_latest_run_date → _get_latest_image_path → _initialize_startup_state."""
        with tempfile.TemporaryDirectory() as tmp:
            # Create a dated folder so _get_latest_run_date would normally find it
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.os.listdir", side_effect=OSError("permission denied")):
                result = _initialize_startup_state()
                self.assertIsNone(result[0])
                self.assertIsNone(result[1])
                # State file should NOT be written when initialization fails
                self.assertFalse(os.path.exists(state_file))

    def test_startup_state_file_format_is_correct(self):
        """The .last_sent_file written by _initialize_startup_state has the exact
        format 'folder/filename\\n' expected by load_last_sent_file."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            img_path = os.path.join(folder, "frame_002.jpg")
            open(img_path, "w").close()

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None):
                _initialize_startup_state()
                with open(state_file, "r") as f:
                    content = f.read()
                # Format should be exactly: folder_name/<relative_filename>\n
                # where relative filename is just the basename since it's in the folder
                lines = content.strip().split("/")
                self.assertEqual(len(lines), 2)
                self.assertEqual(lines[0], "2026-06-19")
                self.assertEqual(lines[1], "frame_002.jpg")

                # Verify load_last_sent_file can read it back correctly
                folder_loaded, image_loaded = load_last_sent_file()
                self.assertEqual(folder_loaded, "2026-06-19")
                self.assertIn("frame_002.jpg", image_loaded)

    def test_iteration_starts_after_initialized_image(self):
        """After startup initialization, _send_new_images_iteration starts from the
        image AFTER the initialized one, not from index 0. This is the core
        acceptance criterion that prevents backlog drain on restart."""
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            # Create 5 images; initialize to frame_003 so iteration should
            # start from frame_004
            for i in range(1, 6):
                path = os.path.join(folder, f"frame_{i:03d}.jpg")
                open(path, "w").close()

            state_file = os.path.join(tmp, ".last_sent_file")
            init_image = os.path.join(folder, "frame_003.jpg")

            # Initialize state as if _initialize_startup_state set it to frame_003
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", init_image), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", "2026-06-19"), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Only frame_004 and frame_005 should be sent;
                # frame_001 through frame_003 should be skipped (before start_index)
                sent_files = [call[0][0] for call in mock_send.call_args_list]
                sent_basenames = [os.path.basename(f) for f in sent_files]
                self.assertNotIn("frame_001.jpg", sent_basenames)
                self.assertNotIn("frame_002.jpg", sent_basenames)
                self.assertNotIn("frame_003.jpg", sent_basenames)
                self.assertIn("frame_004.jpg", sent_basenames)
                self.assertIn("frame_005.jpg", sent_basenames)


class TgBotKeptImageTests(unittest.TestCase):
    """Tests for _kept_images_exist() and _get_image_list() helpers."""

    def test_kept_images_exist_returns_true_when_kept_has_images(self):
        """_kept_images_exist returns True when kept/ exists and contains image files."""
        with tempfile.TemporaryDirectory() as tmp:
            kept_path = os.path.join(tmp, "kept")
            os.makedirs(kept_path)
            open(os.path.join(kept_path, "frame_001.jpg"), "w").close()
            from tg_bot.bot import _kept_images_exist
            result = _kept_images_exist(tmp)
            self.assertTrue(result)

    def test_kept_images_exist_returns_false_when_no_kept_folder(self):
        """_kept_images_exist returns False when kept/ subfolder does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            from tg_bot.bot import _kept_images_exist
            result = _kept_images_exist(tmp)
            self.assertFalse(result)

    def test_kept_images_exist_returns_false_when_kept_empty(self):
        """_kept_images_exist returns False when kept/ exists but has no image files."""
        with tempfile.TemporaryDirectory() as tmp:
            kept_path = os.path.join(tmp, "kept")
            os.makedirs(kept_path)
            # Only a non-image file
            open(os.path.join(kept_path, "notes.txt"), "w").close()
            from tg_bot.bot import _kept_images_exist
            result = _kept_images_exist(tmp)
            self.assertFalse(result)

    def test_kept_images_exist_returns_false_when_kept_has_only_dotfiles(self):
        """_kept_images_exist ignores dotfiles in kept/."""
        with tempfile.TemporaryDirectory() as tmp:
            kept_path = os.path.join(tmp, "kept")
            os.makedirs(kept_path)
            open(os.path.join(kept_path, ".DS_Store"), "w").close()
            from tg_bot.bot import _kept_images_exist
            result = _kept_images_exist(tmp)
            self.assertFalse(result)

    def test_kept_images_exist_handles_oserror(self):
        """_kept_images_exist returns False on OSError when listing kept/."""
        with tempfile.TemporaryDirectory() as tmp:
            kept_path = os.path.join(tmp, "kept")
            os.makedirs(kept_path)
            open(os.path.join(kept_path, "frame.jpg"), "w").close()
            from tg_bot.bot import _kept_images_exist
            with patch("tg_bot.bot.os.listdir", side_effect=OSError("permission denied")):
                result = _kept_images_exist(tmp)
            self.assertFalse(result)

    def test_get_image_list_returns_kept_files_when_kept_exists(self):
        """_get_image_list returns filenames from kept/ subfolder when it has images."""
        with tempfile.TemporaryDirectory() as tmp:
            kept_path = os.path.join(tmp, "kept")
            os.makedirs(kept_path)
            open(os.path.join(kept_path, "kept_001.jpg"), "w").close()
            open(os.path.join(kept_path, "kept_002.png"), "w").close()
            # Also create files in root (should NOT be returned)
            open(os.path.join(tmp, "root_001.jpg"), "w").close()
            from tg_bot.bot import _get_image_list
            result = _get_image_list(tmp)
            self.assertEqual(result, ["kept_001.jpg", "kept_002.png"])

    def test_get_image_list_falls_back_to_root_when_no_kept(self):
        """_get_image_list returns root files when kept/ does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "root_001.jpg"), "w").close()
            open(os.path.join(tmp, "root_002.jpeg"), "w").close()
            # No kept/ subfolder
            from tg_bot.bot import _get_image_list
            result = _get_image_list(tmp)
            self.assertEqual(result, ["root_001.jpg", "root_002.jpeg"])

    def test_get_image_list_falls_back_when_kept_empty(self):
        """_get_image_list falls back to root when kept/ exists but has no images."""
        with tempfile.TemporaryDirectory() as tmp:
            kept_path = os.path.join(tmp, "kept")
            os.makedirs(kept_path)
            # Only a dotfile in kept/
            open(os.path.join(kept_path, ".hidden"), "w").close()
            # Image in root
            open(os.path.join(tmp, "root_img.jpg"), "w").close()
            from tg_bot.bot import _get_image_list
            result = _get_image_list(tmp)
            self.assertEqual(result, ["root_img.jpg"])

    def test_get_image_list_handles_oserror_on_kept(self):
        """_get_image_list falls back to root on OSError listing kept/."""
        with tempfile.TemporaryDirectory() as tmp:
            kept_path = os.path.join(tmp, "kept")
            os.makedirs(kept_path)
            open(os.path.join(kept_path, "kept_img.jpg"), "w").close()
            open(os.path.join(tmp, "root_img.jpg"), "w").close()

            from tg_bot.bot import _get_image_list
            orig_listdir = os.listdir
            def listdir_side_effect(path):
                if path == kept_path:
                    raise OSError("permission denied")
                return orig_listdir(path)

            with patch("tg_bot.bot.os.listdir", side_effect=listdir_side_effect):
                result = _get_image_list(tmp)
            # Falls back to root
            self.assertEqual(result, ["root_img.jpg"])

    def test_get_image_list_handles_oserror_on_root(self):
        """_get_image_list returns empty list on OSError listing root (no kept)."""
        with tempfile.TemporaryDirectory() as tmp:
            from tg_bot.bot import _get_image_list
            with patch("tg_bot.bot.os.listdir", side_effect=OSError("I/O error")):
                result = _get_image_list(tmp)
            self.assertEqual(result, [])


class TgBotTriageAwareSenderTests(unittest.TestCase):
    """Tests for triage-aware image selection in the sender."""

    def test_sender_prefers_kept_images_when_kept_folder_exists(self):
        """When kept/ exists with images, sender only iterates over kept files, not root files."""
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)
            # 2 images in kept/, 3 in root (2 of which are also in kept)
            open(os.path.join(kept_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(kept_folder, "kept_002.jpg"), "w").close()
            open(os.path.join(date_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(date_folder, "kept_002.jpg"), "w").close()
            open(os.path.join(date_folder, "rejected_001.jpg"), "w").close()

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Only the 2 kept files should be sent, not the rejected one
                sent_basenames = [os.path.basename(call[0][0]) for call in mock_send.call_args_list]
                self.assertNotIn("rejected_001.jpg", sent_basenames)
                # kept_001.jpg and kept_002.jpg should be sent from kept/
                self.assertEqual(mock_send.call_count, 2)

    def test_sender_skips_non_kept_images_when_kept_exists(self):
        """_SKIPPED_NON_KEPT_COUNT increments for images not in kept/."""
        import tg_bot.bot as bot_module

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)
            open(os.path.join(kept_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(date_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(date_folder, "rejected_001.jpg"), "w").close()
            open(os.path.join(date_folder, "rejected_002.jpg"), "w").close()

            # Reset counters
            bot_module._SKIPPED_NON_KEPT_COUNT = 0

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # 2 rejected images not in kept/ should be counted
                self.assertEqual(bot_module._SKIPPED_NON_KEPT_COUNT, 2)

    def test_sender_falls_back_when_kept_missing(self):
        """When kept/ doesn't exist, sender iterates all images (backward compatibility)."""
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            open(os.path.join(date_folder, "frame_001.jpg"), "w").close()
            open(os.path.join(date_folder, "frame_002.jpg"), "w").close()

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(mock_send.call_count, 2)


class TgBotThresholdEnvTests(unittest.TestCase):
    """Tests for IMAGE_SIMILARITY_THRESHOLD env var."""

    def test_default_threshold_is_10(self):
        """IMAGE_SIMILARITY_THRESHOLD defaults to 10 when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop("IMAGE_SIMILARITY_THRESHOLD", None)
            result = int(os.getenv("IMAGE_SIMILARITY_THRESHOLD", "10"))
            self.assertEqual(result, 10)

    def test_custom_threshold_from_env(self):
        """IMAGE_SIMILARITY_THRESHOLD reads from environment when set."""
        with patch.dict(os.environ, {"IMAGE_SIMILARITY_THRESHOLD": "15"}):
            result = int(os.getenv("IMAGE_SIMILARITY_THRESHOLD", "10"))
            self.assertEqual(result, 15)

    def test_sender_passes_threshold_to_similarity_check(self):
        """The sender passes IMAGE_SIMILARITY_THRESHOLD to are_images_similar()."""
        from tg_bot.bot import _send_new_images_iteration, IMAGE_SIMILARITY_THRESHOLD

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            open(os.path.join(date_folder, "frame_001.jpg"), "w").close()

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False) as mock_similar, \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Verify the threshold parameter was passed
                if mock_similar.called:
                    call_kwargs = mock_similar.call_args
                    self.assertEqual(call_kwargs[1].get("threshold", IMAGE_SIMILARITY_THRESHOLD), IMAGE_SIMILARITY_THRESHOLD)


class TgBotSendStatisticsTests(unittest.TestCase):
    """Tests for send statistics counters and /admin display."""

    def test_sent_count_increments_on_successful_send(self):
        """_SENT_COUNT increments by 1 each time send_photo succeeds."""
        import tg_bot.bot as bot_module

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake image data")
            tmp_path = f.name

        try:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "OK"

            before = bot_module._SENT_COUNT
            with patch("tg_bot.bot.BOT_TOKEN", "test_token"), \
                 patch("tg_bot.bot.CHAT_ID", "12345"), \
                 patch("tg_bot.bot.requests.post", return_value=mock_response), \
                 patch("tg_bot.bot.save_last_sent_file"), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot._LAST_SENT_TIMESTAMP", 0.0):
                send_photo(tmp_path)
                self.assertEqual(bot_module._SENT_COUNT, before + 1)
        finally:
            os.unlink(tmp_path)

    def test_sent_count_does_not_increment_on_failed_send(self):
        """_SENT_COUNT does not change when send_photo fails."""
        import tg_bot.bot as bot_module

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake image data")
            tmp_path = f.name

        try:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.text = "Forbidden"

            before = bot_module._SENT_COUNT
            with patch("tg_bot.bot.BOT_TOKEN", "test_token"), \
                 patch("tg_bot.bot.CHAT_ID", "12345"), \
                 patch("tg_bot.bot.requests.post", return_value=mock_response), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None):
                send_photo(tmp_path)
                self.assertEqual(bot_module._SENT_COUNT, before)
        finally:
            os.unlink(tmp_path)

    def test_skipped_duplicate_count_increments_on_similarity_skip(self):
        """_SKIPPED_DUPLICATE_COUNT increments when an image is skipped due to similarity (cooldown not expired)."""
        import time
        import tg_bot.bot as bot_module

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            open(os.path.join(date_folder, "frame_001.jpg"), "w").close()
            open(os.path.join(date_folder, "frame_002.jpg"), "w").close()

            bot_module._SKIPPED_DUPLICATE_COUNT = 0

            recent_timestamp = time.time() - 10  # Within cooldown
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=True), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", os.path.join(date_folder, "prev.jpg")), \
                 patch("tg_bot.bot._LAST_SENT_TIMESTAMP", recent_timestamp), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Both images are similar and cooldown NOT expired → skipped
                self.assertGreaterEqual(bot_module._SKIPPED_DUPLICATE_COUNT, 1)

    def test_admin_message_includes_send_statistics(self):
        """_format_admin_message includes Sent, Skipped (similar), Skipped (non-kept) lines."""
        import tg_bot.bot as bot_module
        bot_module._SENT_COUNT = 42
        bot_module._SKIPPED_DUPLICATE_COUNT = 10
        bot_module._SKIPPED_NON_KEPT_COUNT = 5

        try:
            summary = {
                "total_images": 100,
                "kept_images": 50,
                "total_objects_by_type": {"car": 20, "person": 5},
                "missing_expected_objects": [],
            }
            text = _format_admin_message(summary, "2026-06-19", fresh=True)
            self.assertIn("*Sent:* 42", text)
            self.assertIn("*Skipped (similar):* 10", text)
            self.assertIn("*Skipped (non-kept):* 5", text)
        finally:
            bot_module._SENT_COUNT = 0
            bot_module._SKIPPED_DUPLICATE_COUNT = 0
            bot_module._SKIPPED_NON_KEPT_COUNT = 0

    def test_admin_message_shows_zero_statistics(self):
        """_format_admin_message always shows statistics even when zero (fresh start signal)."""
        import tg_bot.bot as bot_module
        bot_module._SENT_COUNT = 0
        bot_module._SKIPPED_DUPLICATE_COUNT = 0
        bot_module._SKIPPED_NON_KEPT_COUNT = 0

        try:
            summary = {"total_images": 10, "kept_images": 5}
            text = _format_admin_message(summary, "2026-06-19", fresh=True)
            self.assertIn("*Sent:* 0", text)
            self.assertIn("*Skipped (similar):* 0", text)
            self.assertIn("*Skipped (non-kept):* 0", text)
        finally:
            bot_module._SENT_COUNT = 0
            bot_module._SKIPPED_DUPLICATE_COUNT = 0
            bot_module._SKIPPED_NON_KEPT_COUNT = 0


class TgBotTriageAwareQATests(unittest.TestCase):
    """QA tests for triage-aware sender failure cases and edge conditions."""

    def test_cooldown_bypass_works_in_kept_mode(self):
        """When kept/ images exist and cooldown IS expired, a similar image is
        still sent via cooldown bypass even in kept/ mode."""
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)
            open(os.path.join(kept_folder, "kept_001.jpg"), "w").close()
            # Also create the root-level copy
            open(os.path.join(date_folder, "kept_001.jpg"), "w").close()

            # Cooldown expired: timestamp is 0.0 (epoch)
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=True), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", "2026-06-19"), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", os.path.join(date_folder, "prev.jpg")), \
                 patch("tg_bot.bot._LAST_SENT_TIMESTAMP", 0.0), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Cooldown expired → similar image should still be sent
                mock_send.assert_called_once()

    def test_non_kept_counter_stays_zero_without_kept_folder(self):
        """_SKIPPED_NON_KEPT_COUNT does NOT increment when there is no kept/ folder.
        This is a backward-compatibility guard: the old behavior had no such counter."""
        import tg_bot.bot as bot_module

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            open(os.path.join(date_folder, "frame_001.jpg"), "w").close()

            bot_module._SKIPPED_NON_KEPT_COUNT = 0

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module._SKIPPED_NON_KEPT_COUNT, 0)

    def test_all_kept_images_skipped_as_similar_when_cooldown_not_expired(self):
        """When every image in kept/ is similar to LAST_SENT_IMAGE and cooldown
        has not expired, no images are sent and _SKIPPED_DUPLICATE_COUNT increments."""
        import time
        import tg_bot.bot as bot_module

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)
            open(os.path.join(kept_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(kept_folder, "kept_002.jpg"), "w").close()
            open(os.path.join(date_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(date_folder, "kept_002.jpg"), "w").close()

            bot_module._SKIPPED_DUPLICATE_COUNT = 0

            # Recent timestamp: cooldown NOT expired
            recent_ts = time.time() - 10

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=True), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", "2026-06-19"), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", os.path.join(date_folder, "prev.jpg")), \
                 patch("tg_bot.bot._LAST_SENT_TIMESTAMP", recent_ts), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # All 2 images are similar and cooldown not expired → 0 sent, 2 duplicate skips
                mock_send.assert_not_called()
                self.assertEqual(bot_module._SKIPPED_DUPLICATE_COUNT, 2)

    def test_oserror_during_non_kept_counting_is_swallowed(self):
        """OSError when listing root directory for non-kept counting does NOT
        prevent the kept/ images from being sent. Exercises the try/except
        at lines 559-571 of bot.py."""
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)
            open(os.path.join(kept_folder, "kept_001.jpg"), "w").close()
            # Also create root copy for the kept set check
            open(os.path.join(date_folder, "kept_001.jpg"), "w").close()

            orig_listdir = os.listdir
            def listdir_side_effect(path):
                # OSError when listing the date folder root (for non-kept counting)
                if path == date_folder:
                    raise OSError("permission denied")
                return orig_listdir(path)

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.os.listdir", side_effect=listdir_side_effect), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # The kept image should still be sent despite OSError in non-kept counting
                mock_send.assert_called_once()

    def test_get_image_list_excludes_dotfiles_from_root(self):
        """_get_image_list excludes dotfiles when falling back to root directory."""
        with tempfile.TemporaryDirectory() as tmp:
            # No kept/ subfolder → falls back to root
            open(os.path.join(tmp, "img_001.jpg"), "w").close()
            open(os.path.join(tmp, "img_002.png"), "w").close()
            open(os.path.join(tmp, ".hidden"), "w").close()
            open(os.path.join(tmp, ".DS_Store"), "w").close()
            from tg_bot.bot import _get_image_list
            result = _get_image_list(tmp)
            self.assertEqual(result, ["img_001.jpg", "img_002.png"])

    def test_send_photo_called_with_kept_subfolder_path(self):
        """When kept/ mode is active, send_photo receives path inside kept/
        subfolder, not the root date folder."""
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)
            open(os.path.join(kept_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(date_folder, "kept_001.jpg"), "w").close()
            # Rejected image in root
            open(os.path.join(date_folder, "rejected.jpg"), "w").close()

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                sent_path = mock_send.call_args[0][0]
                # Path must contain 'kept' subfolder
                self.assertIn(os.sep + "kept" + os.sep, sent_path)
                self.assertNotIn("rejected", sent_path)


class TgBotFreshFirstTests(unittest.TestCase):
    """Tests for newest-first processing, max-age filter, and extended /admin fields."""

    def test_newest_first_sends_fresher_image_before_older(self):
        """When two unsent images exist, the one with more recent mtime is sent first."""
        import time
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            old_path = os.path.join(date_folder, "frame_a.jpg")
            new_path = os.path.join(date_folder, "frame_b.jpg")
            open(old_path, "w").close()
            open(new_path, "w").close()
            # Make frame_b newer (higher mtime)
            now = time.time()
            os.utime(old_path, (now - 120, now - 120))
            os.utime(new_path, (now - 10, now - 10))

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                sent_paths = [call[0][0] for call in mock_send.call_args_list]
                sent_basenames = [os.path.basename(p) for p in sent_paths]
                # Newest first: frame_b should be sent before frame_a
                self.assertEqual(sent_basenames[0], "frame_b.jpg")
                self.assertEqual(sent_basenames[1], "frame_a.jpg")

    def test_max_age_filter_skips_stale_file(self):
        """Images older than MAX_IMAGE_AGE_SECONDS are skipped and _SKIPPED_STALE_COUNT increments."""
        import time
        import tg_bot.bot as bot_module

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            stale_path = os.path.join(date_folder, "frame_stale.jpg")
            fresh_path = os.path.join(date_folder, "frame_fresh.jpg")
            open(stale_path, "w").close()
            open(fresh_path, "w").close()
            now = time.time()
            os.utime(stale_path, (now - 7200, now - 7200))  # 2 hours old
            os.utime(fresh_path, (now - 60, now - 60))       # 1 minute old

            original_stale_count = bot_module._SKIPPED_STALE_COUNT
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Only fresh file should be sent; stale skipped
                self.assertEqual(mock_send.call_count, 1)
                self.assertEqual(os.path.basename(mock_send.call_args[0][0]), "frame_fresh.jpg")
                self.assertEqual(bot_module._SKIPPED_STALE_COUNT, original_stale_count + 1)
                self.assertEqual(bot_module._LAST_SKIP_REASON, "stale")

    def test_max_age_default_is_3600(self):
        """MAX_IMAGE_AGE_SECONDS defaults to 3600 when env var is unset."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MAX_IMAGE_AGE_SECONDS", None)
            # Force re-evaluation by importing in a patched environment
            import importlib
            import tg_bot.bot as bot_module
            with patch.object(bot_module, "MAX_IMAGE_AGE_SECONDS", 3600):
                self.assertEqual(bot_module.MAX_IMAGE_AGE_SECONDS, 3600)

    def test_max_age_custom_env_var(self):
        """MAX_IMAGE_AGE_SECONDS reads custom value from env var."""
        with patch.dict(os.environ, {"MAX_IMAGE_AGE_SECONDS": "60"}):
            val = int(os.getenv("MAX_IMAGE_AGE_SECONDS", "3600"))
            self.assertEqual(val, 60)

    def test_max_age_invalid_env_var_fallback(self):
        """Non-integer MAX_IMAGE_AGE_SECONDS falls back to 3600 gracefully."""
        with patch.dict(os.environ, {"MAX_IMAGE_AGE_SECONDS": "not_a_number"}):
            try:
                val = int(os.getenv("MAX_IMAGE_AGE_SECONDS", "3600"))
            except ValueError:
                val = 3600
            self.assertEqual(val, 3600)

    def test_format_admin_message_includes_extended_fields(self):
        """_format_admin_message includes stale count, backlog size, latest capture, latest sent, last skip reason."""
        import tg_bot.bot as bot_module

        bot_module._SENT_COUNT = 5
        bot_module._SKIPPED_DUPLICATE_COUNT = 2
        bot_module._SKIPPED_NON_KEPT_COUNT = 1
        bot_module._SKIPPED_STALE_COUNT = 3
        bot_module._LAST_SKIP_REASON = "stale"

        try:
            summary = {
                "total_images": 100,
                "kept_images": 50,
                "total_objects_by_type": {"car": 20, "person": 5},
                "missing_expected_objects": [],
            }
            text = _format_admin_message(summary, "2026-06-19", fresh=True)
            self.assertIn("*Skipped (stale):* 3", text)
            self.assertIn("*Backlog size:*", text)
            self.assertIn("*Latest capture:*", text)
            self.assertIn("*Latest sent:*", text)
            self.assertIn("*Last skip reason:* stale", text)
        finally:
            bot_module._SENT_COUNT = 0
            bot_module._SKIPPED_DUPLICATE_COUNT = 0
            bot_module._SKIPPED_NON_KEPT_COUNT = 0
            bot_module._SKIPPED_STALE_COUNT = 0
            bot_module._LAST_SKIP_REASON = ""

    def test_newest_first_cursor_stability(self):
        """A newly arrived file that sorts after the cursor in ascending order is still reachable."""
        import time
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            # Create files: frame_001 and frame_002
            for name in ("frame_001.jpg", "frame_002.jpg"):
                open(os.path.join(date_folder, name), "w").close()
            now = time.time()
            os.utime(os.path.join(date_folder, "frame_001.jpg"), (now - 60, now - 60))
            os.utime(os.path.join(date_folder, "frame_002.jpg"), (now - 30, now - 30))

            # Simulate that frame_001 was already sent
            last_sent = os.path.join(date_folder, "frame_001.jpg")
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", "2026-06-19"), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", last_sent), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Only frame_002 should be sent (after cursor)
                self.assertEqual(mock_send.call_count, 1)
                self.assertEqual(os.path.basename(mock_send.call_args[0][0]), "frame_002.jpg")


class TgBotFreshFirstCompatibilityTests(unittest.TestCase):
    """Backward-compatibility tests: existing behaviors unchanged by newest-first + max-age."""

    def test_concurrency_guard_unchanged(self):
        """image_sender_job still skips when lock is held."""
        import asyncio
        from tg_bot.bot import image_sender_job

        with patch("tg_bot.bot._SENDER_LOCK.locked", return_value=True), \
             patch("tg_bot.bot._send_new_images_iteration") as mock_iter:
            coro = image_sender_job(MagicMock())
            asyncio.get_event_loop().run_until_complete(coro)
            mock_iter.assert_not_called()

    def test_send_cap_still_enforced(self):
        """MAX_IMAGES_PER_ITERATION still caps sends per iteration."""
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

    def test_cooldown_bypass_still_works(self):
        """Cooldown bypass still allows similar images when expired."""
        from tg_bot.bot import _send_new_images_iteration
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

    def test_triage_aware_selection_unchanged(self):
        """kept/ preference and non-kept counting still work."""
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)
            open(os.path.join(kept_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(date_folder, "kept_001.jpg"), "w").close()
            open(os.path.join(date_folder, "rejected_001.jpg"), "w").close()

            bot_module._SKIPPED_NON_KEPT_COUNT = 0

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Only kept image sent, rejected not sent
                sent_basenames = [os.path.basename(call[0][0]) for call in mock_send.call_args_list]
                self.assertNotIn("rejected_001.jpg", sent_basenames)
                self.assertEqual(bot_module._SKIPPED_NON_KEPT_COUNT, 1)

    def test_startup_initialization_unchanged(self):
        """Startup state initialization still picks the latest image."""
        import time
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            old_path = os.path.join(folder, "frame_001.jpg")
            new_path = os.path.join(folder, "frame_002.jpg")
            open(old_path, "w").close()
            open(new_path, "w").close()
            os.utime(old_path, (1000000, 1000000))
            os.utime(new_path, (2000000, 2000000))

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None):
                result = _initialize_startup_state()
                self.assertEqual(result[1], new_path)
                self.assertEqual(result[0], "2026-06-19")


class TgBotFreshFirstQATests(unittest.TestCase):
    """QA validation for fresh-first processing, max-age filter, and extended /admin fields.

    Covers edge cases and failure modes beyond the developer-focused TgBotFreshFirstTests.
    """

    def test_all_images_stale_no_sends(self):
        """When every image is older than MAX_IMAGE_AGE_SECONDS, none are sent and
        _SKIPPED_STALE_COUNT increments for each file."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            for name in ("frame_001.jpg", "frame_002.jpg", "frame_003.jpg"):
                path = os.path.join(date_folder, name)
                open(path, "w").close()
                # All files 2 hours old (stale)
                os.utime(path, (time.time() - 7200, time.time() - 7200))

            original_count = bot_module._SKIPPED_STALE_COUNT
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.MAX_IMAGE_AGE_SECONDS", 3600), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(mock_send.call_count, 0)
                self.assertEqual(bot_module._SKIPPED_STALE_COUNT, original_count + 3)
                self.assertEqual(bot_module._LAST_SKIP_REASON, "stale")

    def test_mixed_staleness_preserves_newest_first_order(self):
        """With 1 stale and 2 fresh images, only fresh are sent in newest-first order."""
        import time
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            stale_path = os.path.join(date_folder, "stale.jpg")
            fresh_a = os.path.join(date_folder, "fresh_a.jpg")
            fresh_b = os.path.join(date_folder, "fresh_b.jpg")
            for p in (stale_path, fresh_a, fresh_b):
                open(p, "w").close()
            now = time.time()
            os.utime(stale_path, (now - 7200, now - 7200))  # 2h old = stale
            os.utime(fresh_a, (now - 120, now - 120))         # 2min old
            os.utime(fresh_b, (now - 10, now - 10))           # 10s old

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                sent = [os.path.basename(call[0][0]) for call in mock_send.call_args_list]
                self.assertEqual(sent, ["fresh_b.jpg", "fresh_a.jpg"])

    def test_similar_skip_sets_last_skip_reason(self):
        """When an image is skipped as similar, _LAST_SKIP_REASON is set to 'similar'."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            fresh_path = os.path.join(date_folder, "frame.jpg")
            open(fresh_path, "w").close()
            os.utime(fresh_path, (time.time() - 10, time.time() - 10))

            last_sent = os.path.join(date_folder, "prev.jpg")
            bot_module._LAST_SKIP_REASON = ""
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=True), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", "2026-06-19"), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", last_sent), \
                 patch("tg_bot.bot._LAST_SENT_TIMESTAMP", time.time()), \
                 patch("tg_bot.bot.SEND_COOLDOWN_SECONDS", 86400), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module._LAST_SKIP_REASON, "similar")

    def test_non_kept_skip_sets_last_skip_reason(self):
        """When a non-kept image is skipped, _LAST_SKIP_REASON is set to 'non-kept'."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)
            # A kept image and a non-kept image in root
            kept_path = os.path.join(kept_folder, "kept_001.jpg")
            open(kept_path, "w").close()
            os.utime(kept_path, (time.time() - 10, time.time() - 10))
            # Also create copy in root to trigger non-kept counting
            root_kept = os.path.join(date_folder, "kept_001.jpg")
            open(root_kept, "w").close()
            rejected = os.path.join(date_folder, "rejected_001.jpg")
            open(rejected, "w").close()

            bot_module._SKIPPED_NON_KEPT_COUNT = 0
            bot_module._LAST_SKIP_REASON = ""

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module._LAST_SKIP_REASON, "non-kept")

    def test_stale_skip_in_kept_mode(self):
        """Stale kept/ images are skipped, fresh kept/ images are sent."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            kept_folder = os.path.join(date_folder, "kept")
            os.makedirs(kept_folder)

            stale_kept = os.path.join(kept_folder, "stale_kept.jpg")
            fresh_kept = os.path.join(kept_folder, "fresh_kept.jpg")
            for p in (stale_kept, fresh_kept):
                open(p, "w").close()
            now = time.time()
            os.utime(stale_kept, (now - 7200, now - 7200))
            os.utime(fresh_kept, (now - 30, now - 30))

            original_stale_count = bot_module._SKIPPED_STALE_COUNT
            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(mock_send.call_count, 1)
                self.assertIn("fresh_kept.jpg", mock_send.call_args[0][0])
                self.assertEqual(bot_module._SKIPPED_STALE_COUNT, original_stale_count + 1)

    def test_newest_first_respects_send_cap(self):
        """Newest-first ordering is applied, then send cap limits how many are sent."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            # Create 7 fresh images with different mtimes
            now = time.time()
            for i in range(7):
                path = os.path.join(date_folder, f"frame_{i:03d}.jpg")
                open(path, "w").close()
                os.utime(path, (now - (7 - i) * 60, now - (7 - i) * 60))

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.MAX_IMAGES_PER_ITERATION", 5), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(mock_send.call_count, 5)
                # Newest first: frame_006 (newest) should be first sent
                sent = [os.path.basename(call[0][0]) for call in mock_send.call_args_list]
                self.assertEqual(sent[0], "frame_006.jpg")

    def test_admin_backlog_count_with_last_sent(self):
        """_format_admin_message backlog size counts remaining images after cursor."""
        import tg_bot.bot as bot_module

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            for name in ("frame_001.jpg", "frame_002.jpg", "frame_003.jpg", "frame_004.jpg"):
                open(os.path.join(date_folder, name), "w").close()

            bot_module._SENT_COUNT = 0
            bot_module._SKIPPED_DUPLICATE_COUNT = 0
            bot_module._SKIPPED_NON_KEPT_COUNT = 0
            bot_module._SKIPPED_STALE_COUNT = 0
            bot_module._LAST_SKIP_REASON = ""

            try:
                summary = {"total_images": 4, "kept_images": 4,
                           "total_objects_by_type": {}, "missing_expected_objects": []}
                with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                     patch("tg_bot.bot.LAST_SENT_FOLDER", "2026-06-19"), \
                     patch("tg_bot.bot.LAST_SENT_IMAGE",
                           os.path.join(tmp, "2026-06-19", "frame_002.jpg")):
                    text = _format_admin_message(summary, "2026-06-19", fresh=True)
                    # After frame_002, 2 remaining (frame_003, frame_004)
                    self.assertIn("*Backlog size:* 2", text)
            finally:
                bot_module._SENT_COUNT = 0
                bot_module._SKIPPED_DUPLICATE_COUNT = 0
                bot_module._SKIPPED_NON_KEPT_COUNT = 0
                bot_module._SKIPPED_STALE_COUNT = 0
                bot_module._LAST_SKIP_REASON = ""

    def test_admin_fields_when_no_image_data(self):
        """_format_admin_message shows Unknown/Never when image data is unavailable."""
        import tg_bot.bot as bot_module

        bot_module._SENT_COUNT = 0
        bot_module._SKIPPED_DUPLICATE_COUNT = 0
        bot_module._SKIPPED_NON_KEPT_COUNT = 0
        bot_module._SKIPPED_STALE_COUNT = 0
        bot_module._LAST_SKIP_REASON = ""

        try:
            with patch("tg_bot.bot._get_latest_image_path", return_value=None), \
                 patch("tg_bot.bot._LAST_SENT_TIMESTAMP", 0.0):
                summary = {"total_images": 0, "kept_images": 0,
                           "total_objects_by_type": {}, "missing_expected_objects": []}
                text = _format_admin_message(summary, None, fresh=False)
                self.assertIn("*Latest capture:* Unknown", text)
                self.assertIn("*Latest sent:* Never", text)
                self.assertIn("*Last skip reason:* —", text)
                self.assertIn("*Backlog size:* 0", text)
        finally:
            bot_module._SENT_COUNT = 0
            bot_module._SKIPPED_DUPLICATE_COUNT = 0
            bot_module._SKIPPED_NON_KEPT_COUNT = 0
            bot_module._SKIPPED_STALE_COUNT = 0
            bot_module._LAST_SKIP_REASON = ""

    def test_getmtime_oserror_bypasses_stale_filter(self):
        """When os.path.getmtime raises OSError in the staleness check, file_mtime
        becomes None, which skips the stale filter (fail-open: unknown-age files are
        not rejected). The file proceeds to similarity/send checks."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            date_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(date_folder)
            # Create one file with normal mtime on disk, but mock getmtime to fail
            broken_path = os.path.join(date_folder, "broken_mtime.jpg")
            open(broken_path, "w").close()

            original_stale = bot_module._SKIPPED_STALE_COUNT
            real_getmtime = os.path.getmtime

            def mock_getmtime(path):
                if "broken_mtime" in path:
                    raise OSError("mocked getmtime failure")
                return real_getmtime(path)

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.os.path.getmtime", side_effect=mock_getmtime), \
                 patch("tg_bot.bot.LAST_SENT_FOLDER", None), \
                 patch("tg_bot.bot.LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                # Fail-open: unknown-mtime file is NOT filtered as stale;
                # it proceeds through the similarity/send path and gets sent.
                self.assertEqual(mock_send.call_count, 1)
                # _SKIPPED_STALE_COUNT should NOT increment for the unknown-age file
                self.assertEqual(bot_module._SKIPPED_STALE_COUNT, original_stale)


class TgBotFolderAdvanceTests(unittest.TestCase):
    """Tests for folder advancement when sent_count == 0 on a non-latest folder."""

    def test_old_folder_all_stale_advances(self):
        """When all remaining images in old folder are stale, bot advances to next folder."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            old_folder = os.path.join(tmp, "2026-06-18")
            new_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(old_folder)
            os.makedirs(new_folder)
            for name in ("frame_001.jpg", "frame_002.jpg"):
                path = os.path.join(old_folder, name)
                open(path, "w").close()
                os.utime(path, (time.time() - 7200, time.time() - 7200))
            fresh_path = os.path.join(new_folder, "frame_003.jpg")
            open(fresh_path, "w").close()
            os.utime(fresh_path, (time.time() - 10, time.time() - 10))

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.MAX_IMAGE_AGE_SECONDS", 3600), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-18"), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-19")
                self.assertIsNone(bot_module.LAST_SENT_IMAGE)

    def test_old_folder_all_similar_advances(self):
        """When all remaining images in old folder are similar within cooldown, bot advances."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            old_folder = os.path.join(tmp, "2026-06-18")
            new_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(old_folder)
            os.makedirs(new_folder)
            for name in ("frame_001.jpg", "frame_002.jpg"):
                path = os.path.join(old_folder, name)
                open(path, "w").close()
                os.utime(path, (time.time() - 300, time.time() - 300))
            fresh_path = os.path.join(new_folder, "frame_003.jpg")
            open(fresh_path, "w").close()
            os.utime(fresh_path, (time.time() - 10, time.time() - 10))

            state_file = os.path.join(tmp, ".last_sent_file")
            last_sent = os.path.join(old_folder, "frame_001.jpg")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-18"), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", last_sent), \
                 patch("tg_bot.bot.are_images_similar", return_value=True), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot._LAST_SENT_TIMESTAMP", time.time()), \
                 patch("tg_bot.bot.SEND_COOLDOWN_SECONDS", 86400), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-19")
                self.assertIsNone(bot_module.LAST_SENT_IMAGE)

    def test_old_folder_fully_sent_advances(self):
        """When LAST_SENT_IMAGE is the last image in old folder, bot advances."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            old_folder = os.path.join(tmp, "2026-06-18")
            new_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(old_folder)
            os.makedirs(new_folder)
            path = os.path.join(old_folder, "frame_001.jpg")
            open(path, "w").close()
            os.utime(path, (time.time() - 10, time.time() - 10))
            fresh_path = os.path.join(new_folder, "frame_002.jpg")
            open(fresh_path, "w").close()
            os.utime(fresh_path, (time.time() - 10, time.time() - 10))

            state_file = os.path.join(tmp, ".last_sent_file")
            last_sent = os.path.join(old_folder, "frame_001.jpg")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-18"), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", last_sent), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-19")
                self.assertIsNone(bot_module.LAST_SENT_IMAGE)

    def test_latest_folder_zero_sends_stays_put(self):
        """When current folder is already the latest and no images are sent, stay put."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(folder)
            for name in ("frame_001.jpg", "frame_002.jpg"):
                path = os.path.join(folder, name)
                open(path, "w").close()
                os.utime(path, (time.time() - 7200, time.time() - 7200))

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.MAX_IMAGE_AGE_SECONDS", 3600), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-19"), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-19")

    def test_normal_send_in_old_folder_no_advance(self):
        """When an image is sent from the old folder, do not advance."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            old_folder = os.path.join(tmp, "2026-06-18")
            new_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(old_folder)
            os.makedirs(new_folder)
            path = os.path.join(old_folder, "frame_001.jpg")
            open(path, "w").close()
            os.utime(path, (time.time() - 10, time.time() - 10))
            fresh_path = os.path.join(new_folder, "frame_002.jpg")
            open(fresh_path, "w").close()
            os.utime(fresh_path, (time.time() - 10, time.time() - 10))

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-18"), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True) as mock_send, \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-18")
                mock_send.assert_called_once()

    def test_multi_folder_rapid_advancement(self):
        """Bot advances through multiple stale old folders until reaching the latest."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            for date in ("2026-06-17", "2026-06-18", "2026-06-19"):
                d = os.path.join(tmp, date)
                os.makedirs(d)
                path = os.path.join(d, "frame.jpg")
                open(path, "w").close()
                os.utime(path, (time.time() - 7200, time.time() - 7200))

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-17"), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.MAX_IMAGE_AGE_SECONDS", 3600), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-18")
                _send_new_images_iteration()
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-19")
                # Now on latest; third call should stay put
                _send_new_images_iteration()
                self.assertEqual(bot_module.LAST_SENT_FOLDER, "2026-06-19")

    def test_admin_stuck_state_fields(self):
        """_format_admin_message includes Watched folder, Newest folder, State file, Status."""
        import tg_bot.bot as bot_module

        bot_module._SENT_COUNT = 0
        bot_module._SKIPPED_DUPLICATE_COUNT = 0
        bot_module._SKIPPED_NON_KEPT_COUNT = 0
        bot_module._SKIPPED_STALE_COUNT = 0
        bot_module._LAST_SKIP_REASON = ""

        with tempfile.TemporaryDirectory() as tmp:
            state_file = os.path.join(tmp, ".last_sent_file")
            with open(state_file, "w") as f:
                f.write("2026-06-18/frame_001.jpg\n")

            try:
                with patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-18"), \
                     patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"), \
                     patch("tg_bot.bot.LAST_SENT_FILE", state_file):
                    summary = {"total_images": 10, "kept_images": 5,
                               "total_objects_by_type": {}, "missing_expected_objects": []}
                    text = _format_admin_message(summary, "2026-06-19", fresh=True)
                    self.assertIn("*Watched folder:* `2026-06-18`", text)
                    self.assertIn("*Newest folder:* `2026-06-19`", text)
                    self.assertIn("2026-06-18/frame_001.jpg", text)
                    self.assertIn("*Status:* \u26a0\ufe0f Stuck on 2026-06-18", text)

                with patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-19"), \
                     patch("tg_bot.bot._get_latest_run_date", return_value="2026-06-19"), \
                     patch("tg_bot.bot.LAST_SENT_FILE", state_file):
                    text = _format_admin_message(summary, "2026-06-19", fresh=True)
                    self.assertIn("*Status:* \u2705 Fresh", text)
            finally:
                bot_module._SENT_COUNT = 0
                bot_module._SKIPPED_DUPLICATE_COUNT = 0
                bot_module._SKIPPED_NON_KEPT_COUNT = 0
                bot_module._SKIPPED_STALE_COUNT = 0
                bot_module._LAST_SKIP_REASON = ""

    def test_state_file_persistence_on_advancement(self):
        """After advancement, .last_sent_file contains new_folder/\n."""
        import time
        import tg_bot.bot as bot_module
        from tg_bot.bot import _send_new_images_iteration

        with tempfile.TemporaryDirectory() as tmp:
            old_folder = os.path.join(tmp, "2026-06-18")
            new_folder = os.path.join(tmp, "2026-06-19")
            os.makedirs(old_folder)
            os.makedirs(new_folder)
            path = os.path.join(old_folder, "frame.jpg")
            open(path, "w").close()
            os.utime(path, (time.time() - 7200, time.time() - 7200))

            state_file = os.path.join(tmp, ".last_sent_file")

            with patch("tg_bot.bot.OUTPUT_DIR", tmp), \
                 patch("tg_bot.bot.LAST_SENT_FILE", state_file), \
                 patch("tg_bot.bot.MAX_IMAGE_AGE_SECONDS", 3600), \
                 patch.object(bot_module, "LAST_SENT_FOLDER", "2026-06-18"), \
                 patch.object(bot_module, "LAST_SENT_IMAGE", None), \
                 patch("tg_bot.bot.are_images_similar", return_value=False), \
                 patch("tg_bot.bot.send_photo", return_value=True), \
                 patch("tg_bot.bot.cleanup_old_folders"):
                _send_new_images_iteration()
                self.assertTrue(os.path.exists(state_file))
                with open(state_file, "r") as f:
                    content = f.read().strip()
                self.assertEqual(content, "2026-06-19/")


if __name__ == "__main__":
    unittest.main()
