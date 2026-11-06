import json

from app.storage import read_json, write_json

WH = {
    "name": "general",
    "url": "https://discord.com/api/webhooks/123456789012345678/abc",
}

CAL = {
    "id": "cal000000001",
    "name": "Rent",
    "webhook_name": "general",
    "message": "Rent is due",
    "message_type": "text",
    "embed": None,
    "date": "2099-11-20",
    "time": "09:00",
    "timezone": "UTC",
    "repeat": "none",
    "enabled": True,
    "created": "2026-01-01T00:00:00+00:00",
    "next_fire": "2026-01-01T00:00:00+00:00",
    "last_fired": None,
    "last_error": None,
}


def _import(client, payload, mode="merge"):
    return client.post(
        "/import",
        files={"file": ("backup.json", json.dumps(payload), "application/json")},
        data={"mode": mode},
    )


def test_export_includes_calendar_and_version_2(client):
    payload = client.get("/export").json()
    assert payload["version"] == 2
    assert "calendar" in payload


def test_import_v1_still_works(client):
    resp = _import(client, {"version": 1, "webhooks": [WH], "alarms": []})
    assert resp.status_code == 200
    assert read_json("calendar") == []


def test_import_merge_dedupes_calendar_by_id(client):
    _import(client, {"version": 2, "webhooks": [], "alarms": [], "calendar": [CAL]})
    _import(client, {"version": 2, "webhooks": [], "alarms": [], "calendar": [CAL]})
    rows = read_json("calendar")
    assert len(rows) == 1
    assert rows[0]["id"] == "cal000000001"


def test_import_replace_clears_calendar(client):
    _import(client, {"version": 2, "webhooks": [], "alarms": [], "calendar": [CAL]})
    other = {**CAL, "id": "cal000000002", "name": "Other"}
    _import(
        client,
        {"version": 2, "webhooks": [], "alarms": [], "calendar": [other]},
        mode="replace",
    )
    rows = read_json("calendar")
    assert len(rows) == 1
    assert rows[0]["id"] == "cal000000002"


def test_import_replace_without_calendar_preserves_it(client):
    write_json("calendar", [CAL])
    resp = _import(
        client,
        {"version": 1, "webhooks": [WH], "alarms": []},
        mode="replace",
    )
    assert resp.status_code == 200
    assert read_json("calendar") == [CAL]


def test_import_recomputes_next_fire(client):
    _import(client, {"version": 2, "webhooks": [], "alarms": [], "calendar": [CAL]})
    row = read_json("calendar")[0]
    assert row["next_fire"].startswith("2099-11-20")


def test_import_form_renders_close_icon(client):
    html = client.get("/import/form").text
    assert "{icon(" not in html
    assert "<svg" in html
    assert 'type="button"' in html


def test_webhook_help_renders_close_icon(client):
    html = client.get("/webhooks/help").text
    assert "{icon(" not in html
    assert "<svg" in html


def test_import_storage_error_returns_toast(client, monkeypatch):
    from app.storage import StorageError

    def fail(*args, **kwargs):
        raise StorageError("The data folder is not writable")

    monkeypatch.setattr("app.main.write_json", fail)
    resp = _import(client, {"webhooks": [WH], "alarms": []})
    assert resp.status_code == 500
    assert "writable" in resp.headers.get("X-Toast-Message", "").lower()
