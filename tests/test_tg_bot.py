import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytz

from tg_bot.bot import (
    _format_admin_message,
    _get_latest_run_date,
    _is_admin_chat,
    _is_fresh,
    _read_latest_summary,
)


class TgBotAdminTests(unittest.TestCase):
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
                # Make file unreadable
                os.chmod(path, 0o000)
                try:
                    result = _read_latest_summary()
                    self.assertIsNone(result)
                finally:
                    os.chmod(path, 0o644)

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
        """Admin chat with no triage data gets 'No triage data available.'"""
        import asyncio
        from unittest.mock import AsyncMock
        from tg_bot.bot import admin_command

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("tg_bot.bot.ADMIN_CHAT_ID", "12345"), \
             patch("tg_bot.bot._read_latest_summary", return_value=None):
            coro = admin_command(update, context)
            asyncio.get_event_loop().run_until_complete(coro)
            update.message.reply_text.assert_called_once_with(
                "No triage data available."
            )

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


if __name__ == "__main__":
    unittest.main()
