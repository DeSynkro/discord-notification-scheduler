import asyncio
import json
from datetime import datetime, timezone

from app import scheduler
from app.storage import read_json, write_json

VALID_URL = "https://discord.com/api/webhooks/123456789012345678/abc"

CAL = {
    "name": "Test alert",
    "webhook_name": "general",
    "message": "m",
    "message_type": "text",
    "date": "2099-11-20",
    "time": "09:00",
    "timezone": "UTC",
    "repeat": "none",
}

ALARM = {
    "name": "Test alarm",
    "webhook_name": "general",
    "message": "m",
    "message_type": "text",
    "time": "09:00",
    "timezone": "UTC",
    "days": ["Monday"],
}


def _import(client, payload, mode="merge"):
    return client.post(
        "/import",
        files={"file": ("backup.json", json.dumps(payload), "application/json")},
        data={"mode": mode},
    )


def test_webhook_rename_updates_calendar(client):
    client.post("/webhooks", data={"new_name": "general", "url": VALID_URL})
    client.post("/calendar", data=CAL)
    resp = client.put(
        "/webhooks/general",
        data={"new_name": "renamed", "url": VALID_URL},
    )
    assert resp.status_code == 200
    assert read_json("calendar")[0]["webhook_name"] == "renamed"


def test_webhook_delete_updates_calendar(client):
    client.post("/webhooks", data={"new_name": "general", "url": VALID_URL})
    client.post("/calendar", data=CAL)
    resp = client.delete("/webhooks/general")
    assert resp.status_code == 200
    assert read_json("calendar")[0]["webhook_name"] == "(deleted)"


def test_webhook_delete_all_updates_calendar(client):
    client.post("/webhooks", data={"new_name": "general", "url": VALID_URL})
    client.post("/calendar", data=CAL)
    resp = client.delete("/webhooks")
    assert resp.status_code == 200
    assert read_json("calendar")[0]["webhook_name"] == "(deleted)"


def test_import_rejects_non_list_webhooks(client):
    resp = _import(client, {"version": 2, "webhooks": None, "alarms": []})
    assert resp.status_code == 400


def test_import_rejects_non_list_calendar(client):
    resp = _import(
        client,
        {"version": 2, "webhooks": [], "alarms": [], "calendar": {}},
    )
    assert resp.status_code == 400


def test_import_replace_with_empty_backup_clears(client):
    write_json("webhooks", [{"name": "general", "url": VALID_URL}])
    resp = _import(
        client,
        {"version": 2, "webhooks": [], "alarms": [], "calendar": []},
        mode="replace",
    )
    assert resp.status_code == 200
    assert read_json("webhooks") == []


def test_toggle_past_one_time_alert_stays_disabled(client):
    write_json("calendar", [{
        "id": "calpast00001",
        "name": "Past",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "embed": None,
        "color": "#3FB950",
        "date": "2000-01-01",
        "time": "09:00",
        "timezone": "UTC",
        "repeat": "none",
        "enabled": False,
        "created": "2026-01-01T00:00:00+00:00",
        "next_fire": None,
        "last_fired": None,
        "last_error": None,
    }])
    client.post("/calendar/calpast00001/toggle")
    row = read_json("calendar")[0]
    assert row["enabled"] is False
    assert row["next_fire"] is None


def test_toggle_repeating_alert_recomputes_next_fire(client):
    write_json("calendar", [{
        "id": "calrepeat0001",
        "name": "Repeat",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "embed": None,
        "color": "#3FB950",
        "date": "2026-11-01",
        "time": "09:00",
        "timezone": "UTC",
        "repeat": "daily",
        "enabled": False,
        "created": "2026-01-01T00:00:00+00:00",
        "next_fire": "2026-11-01T09:00:00+00:00",
        "last_fired": None,
        "last_error": None,
    }])
    client.post("/calendar/calrepeat0001/toggle")
    row = read_json("calendar")[0]
    assert row["enabled"] is True
    assert datetime.fromisoformat(row["next_fire"]) > datetime.now(timezone.utc)


def test_create_alarm_requires_a_day(client):
    payload = dict(ALARM)
    payload.pop("days")
    resp = client.post("/alarms", data=payload)
    assert resp.status_code == 400
    assert read_json("alarms") == []


def test_edit_alarm_preserves_created(client):
    client.post("/alarms", data=ALARM)
    rows = read_json("alarms")
    rows[0]["created"] = "2020-01-01T00:00:00+00:00"
    write_json("alarms", rows)
    alarm_id = rows[0]["id"]

    resp = client.put(f"/alarms/{alarm_id}", data=ALARM)
    assert resp.status_code == 200
    assert read_json("alarms")[0]["created"] == "2020-01-01T00:00:00+00:00"


def test_alarm_test_records_last_error(client):
    client.post("/alarms", data={**ALARM, "webhook_name": "missing"})
    alarm_id = read_json("alarms")[0]["id"]

    resp = client.post(f"/alarms/{alarm_id}/test")
    assert resp.status_code == 200
    row = read_json("alarms")[0]
    assert row["last_error"]
    assert "not found" in row["last_error"]


def test_weekly_same_local_time_is_not_sent_twice(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.DATA_DIR", tmp_path)
    write_json("alarms", [{
        "id": "alarmdup0001",
        "name": "Dup",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "embed": None,
        "time": "09:00",
        "days": ["Thursday"],
        "timezone": "UTC",
        "enabled": True,
        "created": "2026-01-01T00:00:00+00:00",
        "last_fired": "2026-11-05T09:00:00+00:00",
        "last_error": None,
    }])

    calls = []

    async def fake_deliver(alert, kind, source_id=None):
        calls.append(kind)
        return True, ""

    monkeypatch.setattr(scheduler, "deliver", fake_deliver)
    scheduler._sent_this_minute.clear()
    scheduler._last_poll_key = None

    asyncio.run(
        scheduler._poll_weekly(
            datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
        )
    )
    assert calls == []


def test_origin_allows_explicit_default_port(client):
    resp = client.post(
        "/calendar",
        data=CAL,
        headers={"Origin": "http://testserver:80"},
    )
    assert resp.status_code != 403


def test_origin_allows_trailing_dot(client):
    resp = client.post(
        "/calendar",
        data=CAL,
        headers={"Origin": "http://testserver."},
    )
    assert resp.status_code != 403
