import asyncio
from datetime import datetime, timezone

import pytest

from app import scheduler
from app.storage import read_json, write_json


@pytest.fixture(autouse=True)
def reset_scheduler_state():
    scheduler._sent_this_minute.clear()
    scheduler._last_poll_key = None
    yield
    scheduler._sent_this_minute.clear()
    scheduler._last_poll_key = None


def _seed_alert(tmp_path, monkeypatch, repeat, next_fire):
    monkeypatch.setattr("app.storage.DATA_DIR", tmp_path)
    write_json("calendar", [{
        "id": "abc123abc123",
        "name": "Test",
        "webhook_name": "general",
        "message": "hi",
        "message_type": "text",
        "embed": None,
        "date": "2026-11-05",
        "time": "09:00",
        "timezone": "UTC",
        "repeat": repeat,
        "enabled": True,
        "created": "2026-11-01T00:00:00+00:00",
        "next_fire": next_fire,
        "last_fired": None,
        "last_error": None,
    }])


def _fake_deliver(monkeypatch, calls, success=True, error=""):
    async def fake(alert, kind, source_id=None):
        calls.append((kind, source_id))
        return success, error

    monkeypatch.setattr(scheduler, "deliver", fake)


def test_due_alert_fires_and_advances(tmp_path, monkeypatch):
    now = datetime(2026, 11, 5, 9, 0, 30, tzinfo=timezone.utc)
    _seed_alert(tmp_path, monkeypatch, "daily", "2026-11-05T09:00:00+00:00")
    calls = []
    _fake_deliver(monkeypatch, calls)

    asyncio.run(scheduler._poll_calendar(now))

    rows = read_json("calendar")
    assert calls == [("calendar", "abc123abc123")]
    assert rows[0]["next_fire"] == "2026-11-06T09:00:00+00:00"
    assert rows[0]["last_fired"] is not None


def test_stale_alert_is_skipped(tmp_path, monkeypatch):
    now = datetime(2026, 11, 5, 9, 10, 0, tzinfo=timezone.utc)
    _seed_alert(tmp_path, monkeypatch, "daily", "2026-11-05T09:00:00+00:00")
    calls = []
    _fake_deliver(monkeypatch, calls)

    asyncio.run(scheduler._poll_calendar(now))

    rows = read_json("calendar")
    assert calls == []
    assert rows[0]["next_fire"] == "2026-11-06T09:00:00+00:00"


def test_one_time_alert_disables_after_firing(tmp_path, monkeypatch):
    now = datetime(2026, 11, 5, 9, 0, 30, tzinfo=timezone.utc)
    _seed_alert(tmp_path, monkeypatch, "none", "2026-11-05T09:00:00+00:00")
    calls = []
    _fake_deliver(monkeypatch, calls)

    asyncio.run(scheduler._poll_calendar(now))

    rows = read_json("calendar")
    assert calls == [("calendar", "abc123abc123")]
    assert rows[0]["enabled"] is False
    assert rows[0]["next_fire"] is None


def test_failure_is_recorded_and_advances(tmp_path, monkeypatch):
    now = datetime(2026, 11, 5, 9, 0, 30, tzinfo=timezone.utc)
    _seed_alert(tmp_path, monkeypatch, "daily", "2026-11-05T09:00:00+00:00")
    calls = []
    _fake_deliver(monkeypatch, calls, success=False, error="boom")

    asyncio.run(scheduler._poll_calendar(now))

    rows = read_json("calendar")
    assert rows[0]["last_error"] == "boom"
    assert rows[0]["next_fire"] == "2026-11-06T09:00:00+00:00"


def test_startup_recompute_skips_missed(tmp_path, monkeypatch):
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    _seed_alert(tmp_path, monkeypatch, "daily", "2026-11-05T09:00:00+00:00")

    scheduler.recompute_all(now)

    assert read_json("calendar")[0]["next_fire"] == "2026-11-11T09:00:00+00:00"
