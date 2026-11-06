import re

from app.storage import read_json, write_json

WEBHOOK = {
    "name": "general",
    "url": "https://discord.com/api/webhooks/123456789012345678/abc",
}

ALARM = {
    "id": "a10000000000",
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
    "last_fired": None,
    "last_error": None,
}


def _seed():
    write_json("webhooks", [WEBHOOK])
    write_json("alarms", [ALARM])


def test_toggle_scopes_the_refresh(client):
    _seed()
    resp = client.post("/alarms/a10000000000/toggle")
    assert resp.status_code == 200
    assert resp.headers["HX-Trigger"] == "alarm-toggled"
    assert "is-off" in resp.text
    assert read_json("alarms")[0]["enabled"] is False


def test_board_patches_in_place_but_alarm_list_does_not(client):
    _seed()
    html = client.get("/").text
    board = re.search(r'<section class="next-up"[^>]*>', html)
    assert board and "data-next-key=" in board.group(0)
    assert "hx-trigger" not in board.group(0)

    alarm_list = re.search(r'<div id="alarm-list"[^>]*>', html)
    assert alarm_list and "alarm-toggled" not in alarm_list.group(0)

    calendar = re.search(r'<div id="calendar-view"[^>]*>', html)
    assert calendar and "alarm-toggled from:body" in calendar.group(0)


def test_next_up_data_endpoint(client):
    _seed()
    data = client.get("/next-up/data").json()
    assert data["empty"] is False
    assert data["next_key"] == "weekly:a10000000000"
    assert data["lead"]["name"] == "Weekly report"
    assert data["count"] == len(data["window"])
    assert isinstance(data["then_html"], str)


def test_toggle_does_not_trigger_full_list_refresh(client):
    _seed()
    resp = client.post("/alarms/a10000000000/toggle")
    assert "refresh-lists" not in resp.headers.get("HX-Trigger", "")
