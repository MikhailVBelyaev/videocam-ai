import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tg_bot"))
import nvr_clip  # noqa: E402


def test_event_time_is_utc_and_nvr_url_is_local():
    e = nvr_clip.event_epoch("2026-11-25T10:36:31")          # 15:36:31 по Ташкенту
    a, b = nvr_clip.clip_window(e, 5)
    url = nvr_clip.nvr_url("cam1", a, b, password="12aA@")
    assert "starttime=20261125T153626Z" in url and "endtime=20261125T153636Z" in url
    assert "/tracks/101?" in url and "12aA%40@" in url        # пароль %-кодирован


def test_second_camera_track():
    assert nvr_clip.nvr_url("cam2", 0, 10, password="x").split("/tracks/")[1].startswith("201?")
