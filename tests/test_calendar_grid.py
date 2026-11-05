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
    write_json("calendar", [
        {
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
            "color": "#FF8800",
            "created": "2026-01-01T00:00:00+00:00",
            "next_fire": "2026-11-05T14:30:00+00:00",
            "last_fired": None,
            "last_error": None,
        },
        {
            "id": "cal000000002",
            "name": "Past fired alert",
            "webhook_name": "general",
            "message": "m",
            "message_type": "text",
            "embed": None,
            "date": "2026-11-01",
            "time": "09:00",
            "timezone": "UTC",
            "repeat": "none",
            "enabled": False,
            "color": "#FF8800",
            "created": "2026-01-01T00:00:00+00:00",
            "next_fire": None,
            "last_fired": "2026-11-01T09:00:00+00:00",
            "last_error": None,
        },
        {
            "id": "cal000000003",
            "name": "Future disabled alert",
            "webhook_name": "general",
            "message": "m",
            "message_type": "text",
            "embed": None,
            "date": "2099-01-01",
            "time": "09:00",
            "timezone": "UTC",
            "repeat": "none",
            "enabled": False,
            "color": "#FF8800",
            "created": "2026-01-01T00:00:00+00:00",
            "next_fire": None,
            "last_fired": None,
            "last_error": None,
        },
    ])


def test_grid_contains_weekly_and_dated_events(client, seeded_data):
    html = client.get("/calendar?month=2026-11&show_weekly=1").text
    assert "Weekly report" in html
    assert "Dentist appointment" in html
    assert 'id="cal-month"' in html
    assert 'id="show-weekly"' in html
    assert 'id="show-past"' in html
    assert 'hx-include="#show-weekly, #show-past"' in html
    assert "cal-legend" not in html
    assert "/calendar/new?date=" in html


def test_weekly_alarms_can_be_hidden(client, seeded_data):
    client.cookies.set("dns_show_weekly", "0")
    html = client.get("/calendar?month=2026-11").text
    assert "Weekly report" not in html
    assert "Dentist appointment" in html


def test_grid_uses_alert_color(client, seeded_data):
    html = client.get("/calendar?month=2026-11").text
    assert "#FF8800" in html


def test_month_navigation_returns_other_month(client, seeded_data):
    html = client.get("/calendar?month=2026-10").text
    assert "October 2026" in html


def test_other_month_is_dimmed(client, seeded_data):
    html = client.get("/calendar?month=2026-11").text
    assert "cal-day out" in html


def test_day_modal_lists_entries(client, seeded_data):
    html = client.get("/calendar/day?date=2026-11-05").text
    assert "Dentist appointment" in html


def test_past_disabled_alert_is_hidden_by_default(client, seeded_data):
    html = client.get("/calendar?month=2026-11").text
    assert "Past fired alert" not in html


def test_past_disabled_alert_visible_when_requested(client, seeded_data):
    html = client.get("/calendar?month=2026-11&show_past=1").text
    assert "Past fired alert" in html
    assert "cal-event calendar disabled" in html


def test_future_disabled_alert_is_hidden_even_when_requested(client, seeded_data):
    html = client.get("/calendar?month=2026-11&show_past=1").text
    assert "Future disabled alert" not in html
