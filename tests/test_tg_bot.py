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
    _get_latest_run_date,
    _is_admin_chat,
    _is_fresh,
    _query_container_states,
    _read_latest_summary,
    _summarize_live_output,
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
             patch("tg_bot.bot._is_fresh", return_value=True):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            text = update.message.reply_text.call_args[0][0]
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
             patch("tg_bot.bot._is_fresh", return_value=True):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            call_args = update.message.reply_text.call_args
            text = call_args[0][0]
            self.assertIn("50", text)
            self.assertIn("10", text)
            self.assertIn("8", text)
            self.assertIn("2", text)
            self.assertEqual(call_args[1]["parse_mode"], "Markdown")

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


if __name__ == "__main__":
    unittest.main()
