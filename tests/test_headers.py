VALID_URL = "https://discord.com/api/webhooks/123456789012345678/abc"


def test_emoji_webhook_name_does_not_crash(client):
    resp = client.post("/webhooks", data={"new_name": "🚀", "url": VALID_URL})
    assert resp.status_code == 200
    assert resp.headers["X-Toast-Type"] == "ok"


def test_emoji_alarm_name_does_not_crash(client):
    resp = client.post("/alarms", data={
        "name": "🚀",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "time": "09:00",
        "timezone": "UTC",
        "days": ["Monday"],
    })
    assert resp.status_code == 200


def test_emoji_calendar_name_does_not_crash(client):
    resp = client.post("/calendar", data={
        "name": "🚀",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "date": "2099-11-20",
        "time": "09:00",
        "timezone": "UTC",
        "repeat": "none",
    })
    assert resp.status_code == 200


def test_emoji_validation_error_does_not_crash(client):
    resp = client.post("/calendar", data={
        "name": "x",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "date": "🚀",
        "time": "09:00",
        "timezone": "UTC",
        "repeat": "none",
    })
    assert resp.status_code == 400


def test_emoji_sort_header_does_not_crash(client):
    resp = client.get("/alarms?sort=🚀")
    assert resp.status_code == 200
