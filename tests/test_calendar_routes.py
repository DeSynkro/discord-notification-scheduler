from datetime import datetime, timedelta, timezone

from app.storage import read_json, write_json


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


def test_create_alert_stores_color(client):
    resp = client.post("/calendar", data=_base(color="#ff8800"))
    assert resp.status_code == 200
    assert read_json("calendar")[0]["color"] == "#FF8800"


def test_invalid_color_returns_toast(client):
    resp = client.post("/calendar", data=_base(color="orange"))
    assert resp.status_code == 400
    assert resp.headers["X-Toast-Type"] == "err"


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


def test_test_route_uses_unsaved_form_values(client, monkeypatch):
    client.post("/calendar", data=_base())
    alert_id = read_json("calendar")[0]["id"]

    calls = []

    async def fake_deliver(alert, kind, source_id=None):
        calls.append({
            "name": alert.name,
            "message": alert.message,
            "message_type": alert.message_type,
            "color": alert.color,
            "embed_title": alert.embed.title if alert.embed else None,
        })
        return True, ""

    monkeypatch.setattr("app.calendar_alerts.deliver", fake_deliver)
    resp = client.post(
        f"/calendar/{alert_id}/test",
        data=_base(
            name="Unsaved name",
            message="Unsaved message",
            message_type="embed",
            embed_title="Live preview",
            color="#00ff00",
        ),
    )
    assert resp.status_code == 200
    assert calls[0] == {
        "name": "Unsaved name",
        "message": "Unsaved message",
        "message_type": "embed",
        "color": "#00FF00",
        "embed_title": "Live preview",
    }
    assert read_json("calendar")[0]["name"] == "Rent"


def test_test_route_preserves_concurrent_calendar_changes(client, monkeypatch):
    client.post("/calendar", data=_base())
    alert_id = read_json("calendar")[0]["id"]

    async def fake_deliver(alert, kind, source_id=None):
        rows = read_json("calendar")
        concurrent = dict(rows[0])
        concurrent["id"] = "concurrent001"
        concurrent["name"] = "Concurrent edit"
        rows.append(concurrent)
        write_json("calendar", rows)
        return True, ""

    monkeypatch.setattr("app.calendar_alerts.deliver", fake_deliver)
    resp = client.post(f"/calendar/{alert_id}/test")
    assert resp.status_code == 200
    rows = read_json("calendar")
    assert len(rows) == 2
    assert any(row["id"] == "concurrent001" for row in rows)
    assert next(row for row in rows if row["id"] == alert_id)["last_fired"] is not None


def test_test_route_allows_past_one_time_alert(client, monkeypatch):
    client.post("/calendar", data=_base())
    rows = read_json("calendar")
    rows[0]["date"] = "2000-01-01"
    rows[0]["next_fire"] = None
    write_json("calendar", rows)
    alert_id = rows[0]["id"]

    calls = []

    async def fake_deliver(alert, kind, source_id=None):
        calls.append(alert)
        return True, ""

    monkeypatch.setattr("app.calendar_alerts.deliver", fake_deliver)
    resp = client.post(
        f"/calendar/{alert_id}/test",
        data=_base(date="2000-01-01"),
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0].id == alert_id


def test_modal_prefills_date(client):
    resp = client.get("/calendar/new?date=2026-12-25")
    assert resp.status_code == 200
    assert 'value="2026-12-25"' in resp.text
