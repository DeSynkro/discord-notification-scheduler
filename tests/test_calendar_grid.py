from datetime import timezone

import pytest

from app.storage import write_json


@pytest.fixture
def seeded_data(tmp_data, monkeypatch):
    monkeypatch.setattr("app.calendar_alerts.DISPLAY_TZ", timezone.utc)
    write_json("webhooks", [{
        "name": "general",
        "url": "https://discord.com/api/webhooks/123456789012345678/abc",
    }])
    write_json("alarms", [{
        "id": "alarm0000001",
        "name": "Weekly report",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "embed": None,
        "time": "10:00",
        "days": ["Monday"],
        "timezone": "UTC",
        "enabled": True,
        "created": "2026-01-01T00:00:00+00:00",
    }])
    write_json("calendar", [{
        "id": "cal000000001",
        "name": "Dentist appointment",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "embed": None,
        "date": "2026-11-05",
        "time": "14:30",
        "timezone": "UTC",
        "repeat": "none",
        "enabled": True,
        "created": "2026-01-01T00:00:00+00:00",
        "next_fire": "2026-11-05T14:30:00+00:00",
        "last_fired": None,
        "last_error": None,
    }])


def test_grid_contains_weekly_and_dated_events(client, seeded_data):
    html = client.get("/calendar?month=2026-11").text
    assert "Weekly report" in html
    assert "Dentist appointment" in html
    assert 'id="cal-month"' in html
    assert "/calendar/new?date=" in html


def test_other_month_is_dimmed(client, seeded_data):
    html = client.get("/calendar?month=2026-11").text
    assert "cal-day out" in html


def test_day_modal_lists_entries(client, seeded_data):
    html = client.get("/calendar/day?date=2026-11-05").text
    assert "Dentist appointment" in html
