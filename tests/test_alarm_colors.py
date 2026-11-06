import re

import pytest

from app.models import Alarm
from app.storage import read_json, write_json
WEBHOOK = {
    "name": "general",
    "url": "https://discord.com/api/webhooks/123456789012345678/abc",
}

ALARM = {
    "name": "Colored alarm",
    "webhook_name": "general",
    "message": "m",
    "message_type": "text",
    "time": "09:00",
    "timezone": "UTC",
    "days": ["Monday"],
}


def test_alarm_form_has_color_picker(client):
    html = client.get("/alarms/new").text
    assert 'name="color"' in html
    assert 'type="color"' in html
    assert "#8B9BFF" in html


def test_color_hex_field_is_the_submitted_field(client):
    html = client.get("/alarms/new").text
    assert re.search(r'<input type="text" name="color" class="color-text"', html)
    assert not re.search(r'<input type="color" name="color"', html)
    assert 'pattern="^#[0-9a-fA-F]{6}$"' in html


def test_calendar_color_hex_field_is_the_submitted_field(client):
    html = client.get("/calendar/new").text
    assert re.search(r'<input type="text" name="color" class="color-text"', html)
    assert not re.search(r'<input type="color" name="color"', html)


def test_create_alarm_saves_color(client):
    write_json("webhooks", [WEBHOOK])
    resp = client.post("/alarms", data={**ALARM, "color": "#ff0000"})
    assert resp.status_code == 200
    assert read_json("alarms")[0]["color"] == "#FF0000"


def test_update_alarm_saves_color(client):
    write_json("webhooks", [WEBHOOK])
    client.post("/alarms", data=ALARM)
    alarm_id = read_json("alarms")[0]["id"]
    resp = client.put(f"/alarms/{alarm_id}", data={**ALARM, "color": "#00ff00"})
    assert resp.status_code == 200
    assert read_json("alarms")[0]["color"] == "#00FF00"


def test_alarm_color_must_be_hex():
    with pytest.raises(ValueError):
        Alarm(**ALARM, color="red")
