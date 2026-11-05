import pytest

from app import notification_log
from app.models import Alarm


@pytest.fixture
def alarm():
    return Alarm(name="Test", webhook_name="general", message="hi", time="09:00")


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.DATA_DIR", tmp_path)
    return tmp_path


def test_preview_collapses_whitespace_and_truncates():
    assert notification_log.preview("a\n\nb   c") == "a b c"
    assert len(notification_log.preview("x" * 300)) == 200


def test_preview_handles_empty_message():
    assert notification_log.preview("   \n\t ") == ""


def test_append_puts_newest_first_and_keeps_status(tmp_log, alarm):
    notification_log.append_log("weekly", alarm, alarm.id, True, "")
    notification_log.append_log("test", alarm, None, False, "boom")
    rows = notification_log.read_log()
    assert rows[0]["status"] == "err"
    assert rows[0]["error"] == "boom"
    assert rows[0]["kind"] == "test"
    assert rows[0]["source_id"] is None
    assert rows[1]["status"] == "ok"
    assert rows[1]["error"] is None
    assert rows[1]["source_id"] == alarm.id


def test_append_records_metadata(tmp_log, alarm):
    notification_log.append_log("weekly", alarm, alarm.id, True, "")
    row = notification_log.read_log()[0]
    assert row["name"] == "Test"
    assert row["webhook_name"] == "general"
    assert row["timezone"] == "UTC"
    assert row["preview"] == "hi"
    assert row["ts"]


def test_cap_drops_oldest(tmp_log, monkeypatch):
    monkeypatch.setattr(notification_log, "MAX_LOG", 3)
    for index in range(5):
        alarm = Alarm(
            name="Test", webhook_name="general", message=str(index), time="09:00"
        )
        notification_log.append_log("weekly", alarm, alarm.id, True, "")
    rows = notification_log.read_log()
    assert len(rows) == 3
    assert [row["preview"] for row in rows] == ["4", "3", "2"]


def test_read_log_limit_returns_newest(tmp_log):
    for index in range(3):
        alarm = Alarm(
            name="Test", webhook_name="general", message=str(index), time="09:00"
        )
        notification_log.append_log("weekly", alarm, alarm.id, True, "")
    assert [row["preview"] for row in notification_log.read_log(limit=2)] == ["2", "1"]


def test_clear_empties_log(tmp_log, alarm):
    notification_log.append_log("weekly", alarm, alarm.id, True, "")
    notification_log.clear_log()
    assert notification_log.read_log() == []
