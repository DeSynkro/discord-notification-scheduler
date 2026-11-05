import pytest

from app import notification_log
from app.models import Alarm


@pytest.fixture
def seeded_log(tmp_data):
    alarm = Alarm(name="Weekly report", webhook_name="general", message="m", time="10:00")
    notification_log.append_log("weekly", alarm, alarm.id, True, "")
    notification_log.append_log("weekly", alarm, alarm.id, False, "Connection timed out")


def test_log_fragment_lists_entries(client, seeded_log):
    html = client.get("/log").text
    assert "Weekly report" in html
    assert "Failed" in html
    assert "Connection timed out" in html


def test_clear_log(client, seeded_log):
    resp = client.delete("/log")
    assert resp.headers["HX-Trigger"] == "refresh-lists"
    assert client.get("/log").text.count("log-row") == 0
