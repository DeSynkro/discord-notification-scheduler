from datetime import datetime, timedelta, timezone

from app.storage import read_json


def _future_date(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _base(**overrides):
    data = {
        "name": "Rent",
        "webhook_name": "general",
        "message": "Rent is due",
        "message_type": "text",
        "date": _future_date(),
        "time": "09:00",
        "timezone": "UTC",
        "repeat": "none",
    }
    data.update(overrides)
    return data


def test_create_alert_sets_next_fire_and_refreshes(client):
    resp = client.post("/calendar", data=_base())
    assert resp.status_code == 200
    assert resp.headers["HX-Trigger"] == "refresh-lists"
    assert resp.headers["X-Toast-Type"] == "ok"
    rows = read_json("calendar")
    assert rows[0]["name"] == "Rent"
    assert rows[0]["next_fire"] is not None


def test_edit_alert_updates_and_preserves_id(client):
    client.post("/calendar", data=_base())
    row = read_json("calendar")[0]
    resp = client.put(
        f"/calendar/{row['id']}",
        data=_base(name="Rent updated", message="New message"),
    )
    assert resp.status_code == 200
    updated = read_json("calendar")[0]
    assert updated["id"] == row["id"]
    assert updated["created"] == row["created"]
    assert updated["name"] == "Rent updated"
    assert updated["message"] == "New message"


def test_toggle_alert_flips_enabled(client):
    client.post("/calendar", data=_base())
    alert_id = read_json("calendar")[0]["id"]
    client.post(f"/calendar/{alert_id}/toggle")
    assert read_json("calendar")[0]["enabled"] is False
    client.post(f"/calendar/{alert_id}/toggle")
    assert read_json("calendar")[0]["enabled"] is True


def test_delete_alert_removes_record_and_closes_modal(client):
    client.post("/calendar", data=_base())
    alert_id = read_json("calendar")[0]["id"]
    resp = client.delete(f"/calendar/{alert_id}")
    assert resp.headers["HX-Trigger"] == "refresh-lists"
    assert 'hx-swap-oob="innerHTML"' in resp.text
    assert read_json("calendar") == []


def test_delete_all_calendar_alerts(client):
    client.post("/calendar", data=_base())
    resp = client.delete("/calendar")
    assert resp.status_code == 200
    assert resp.headers["HX-Trigger"] == "refresh-lists"
    assert read_json("calendar") == []


def test_validation_error_returns_toast(client):
    resp = client.post("/calendar", data=_base(date="2026-02-30"))
    assert resp.status_code == 400
    assert resp.headers["X-Toast-Type"] == "err"
    assert read_json("calendar") == []


def test_past_one_time_alert_is_rejected(client):
    resp = client.post("/calendar", data=_base(date="2000-01-01"))
    assert resp.status_code == 400
    assert resp.headers["X-Toast-Type"] == "err"


def test_test_route_calls_deliver(client, monkeypatch):
    client.post("/calendar", data=_base())
    alert_id = read_json("calendar")[0]["id"]

    calls = []

    async def fake_deliver(alert, kind, source_id=None):
        calls.append((kind, source_id))
        return True, ""

    monkeypatch.setattr("app.calendar_alerts.deliver", fake_deliver)
    resp = client.post(f"/calendar/{alert_id}/test")
    assert resp.status_code == 200
    assert calls == [("test", alert_id)]
    assert read_json("calendar")[0]["last_fired"] is not None


def test_modal_prefills_date(client):
    resp = client.get("/calendar/new?date=2026-12-25")
    assert resp.status_code == 200
    assert 'value="2026-12-25"' in resp.text
