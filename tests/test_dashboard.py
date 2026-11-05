import re
from pathlib import Path

import pytest

from app.storage import write_json


@pytest.fixture
def weekly_seed(tmp_data):
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


@pytest.fixture
def past_seed(tmp_data):
    write_json("calendar", [{
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
        "color": "#3FB950",
        "created": "2026-01-01T00:00:00+00:00",
        "next_fire": None,
        "last_fired": "2026-11-01T09:00:00+00:00",
        "last_error": None,
    }])


def _checkbox_tag(html, field_id):
    match = re.search(rf'<input[^>]*id="{field_id}"[^>]*>', html)
    assert match
    return match.group(0)


def test_dashboard_has_bubbles_and_views(client):
    html = client.get("/").text
    assert 'data-view="alarms"' in html
    assert 'data-view="calendar"' in html
    assert 'data-view="log"' in html
    assert 'id="calendar-view"' in html
    assert 'id="log-view"' in html
    assert 'id="show-weekly"' in html
    assert 'id="show-past"' in html
    assert 'id="sort-select"' in html


def test_calendar_view_does_not_inherit_include():
    html = Path("app/templates/index.html").read_text()
    assert 'hx-disinherit="hx-include"' in html


def test_dashboard_unchecks_weekly_when_cookie_off(client, weekly_seed):
    client.cookies.set("dns_show_weekly", "0")
    html = client.get("/").text
    assert "checked" not in _checkbox_tag(html, "show-weekly")


def test_dashboard_checks_weekly_when_cookie_on(client, weekly_seed):
    client.cookies.set("dns_show_weekly", "1")
    html = client.get("/").text
    assert "checked" in _checkbox_tag(html, "show-weekly")


def test_dashboard_unchecks_past_when_cookie_off(client, weekly_seed):
    client.cookies.set("dns_show_past", "0")
    html = client.get("/").text
    assert "checked" not in _checkbox_tag(html, "show-past")


def test_dashboard_checks_past_when_cookie_on(client, weekly_seed):
    client.cookies.set("dns_show_past", "1")
    html = client.get("/").text
    assert "checked" in _checkbox_tag(html, "show-past")


def test_calendar_fragment_hides_weekly_when_cookie_off(client, weekly_seed):
    client.cookies.set("dns_show_weekly", "0")
    html = client.get("/calendar?month=2026-11").text
    assert "Weekly report" not in html


def test_calendar_fragment_shows_weekly_when_cookie_on(client, weekly_seed):
    client.cookies.set("dns_show_weekly", "1")
    html = client.get("/calendar?month=2026-11").text
    assert "Weekly report" in html


def test_explicit_show_weekly_overrides_cookie(client, weekly_seed):
    client.cookies.set("dns_show_weekly", "0")
    html = client.get("/calendar?month=2026-11&show_weekly=1").text
    assert "Weekly report" in html


def test_calendar_hides_past_by_default(client, past_seed):
    html = client.get("/calendar?month=2026-11").text
    assert "Past fired alert" not in html


def test_calendar_shows_past_with_cookie(client, past_seed):
    client.cookies.set("dns_show_past", "1")
    html = client.get("/calendar?month=2026-11").text
    assert "Past fired alert" in html
