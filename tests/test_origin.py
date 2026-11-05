CAL = {
    "name": "Rent",
    "webhook_name": "general",
    "message": "Rent is due",
    "message_type": "text",
    "date": "2099-11-20",
    "time": "09:00",
    "timezone": "UTC",
    "repeat": "none",
}


def test_cross_origin_post_is_rejected(client):
    resp = client.post("/calendar", data=CAL, headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403


def test_same_origin_post_is_allowed(client):
    resp = client.post("/calendar", data=CAL, headers={"Origin": "http://testserver"})
    assert resp.status_code != 403


def test_missing_origin_is_allowed(client):
    resp = client.post("/calendar", data=CAL)
    assert resp.status_code == 200
