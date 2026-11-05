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
    assert 'class="log-preview"' in html


def test_clear_log(client, seeded_log):
    resp = client.delete("/log")
    assert resp.headers["HX-Trigger"] == "refresh-lists"
    assert client.get("/log").text.count("log-row") == 0


def test_log_is_paged(client, tmp_data):
    for index in range(30):
        alarm = Alarm(
            name=f"Alert {index}",
            webhook_name="general",
            message=f"message {index}",
            time="10:00",
        )
        notification_log.append_log("weekly", alarm, alarm.id, True, "")

    page1 = client.get("/log?page=1").text
    page2 = client.get("/log?page=2").text
    page3 = client.get("/log?page=3").text

    assert "Page 1 of 3" in page1
    assert "Page 2 of 3" in page2
    assert "Page 3 of 3" in page3
    assert "Alert 29" in page1
    assert "Alert 29" not in page2
    assert "Alert 20" in page1
    assert "Alert 19" in page2
    assert "Alert 0" in page3
    assert "Alert 0" not in page2
