import pytest
from pydantic import ValidationError

from app.models import CALENDAR_REPEATS, CalendarAlert, LogEntry


def _base(**overrides):
    data = {
        "name": "Rent",
        "webhook_name": "general",
        "message": "Rent is due",
        "date": "2026-11-20",
        "time": "09:00",
        "timezone": "UTC",
    }
    data.update(overrides)
    return data


def test_calendar_repeats_contains_the_five_modes():
    assert CALENDAR_REPEATS == ("none", "daily", "weekly", "monthly", "yearly")


def test_calendar_alert_accepts_valid_values():
    alert = CalendarAlert(**_base(repeat="monthly"))
    assert alert.repeat == "monthly"
    assert alert.enabled is True
    assert alert.next_fire is None
    assert len(alert.id) == 12


def test_calendar_alert_rejects_bad_date():
    with pytest.raises(ValidationError):
        CalendarAlert(**_base(date="2026-02-30"))


def test_calendar_alert_rejects_non_padded_date():
    with pytest.raises(ValidationError):
        CalendarAlert(**_base(date="2026-1-1"))


def test_calendar_alert_rejects_bad_repeat():
    with pytest.raises(ValidationError):
        CalendarAlert(**_base(repeat="hourly"))


def test_calendar_alert_rejects_bad_timezone():
    with pytest.raises(ValidationError):
        CalendarAlert(**_base(timezone="Mars/Olympus"))


def test_calendar_alert_rejects_bad_message_type():
    with pytest.raises(ValidationError):
        CalendarAlert(**_base(message_type="html"))


def test_calendar_alert_rejects_bad_embed_color():
    with pytest.raises(ValidationError):
        CalendarAlert(**_base(message_type="embed", embed={"title": "x", "color": "red"}))


def test_calendar_alert_accepts_embed_color():
    alert = CalendarAlert(
        **_base(message_type="embed", embed={"title": "x", "color": "#ff0000"})
    )
    assert alert.embed.color == "#FF0000"


def test_log_entry_accepts_valid_values():
    entry = LogEntry(
        ts="2026-11-05T19:30:00+00:00",
        kind="calendar",
        name="Rent",
        webhook_name="general",
        status="ok",
        preview="Rent is due",
    )
    assert entry.kind == "calendar"
    assert entry.timezone == "UTC"
    assert entry.source_id is None


def test_log_entry_rejects_bad_kind():
    with pytest.raises(ValidationError):
        LogEntry(ts="x", kind="other", name="n", webhook_name="g", status="ok", preview="p")


def test_log_entry_rejects_bad_status():
    with pytest.raises(ValidationError):
        LogEntry(ts="x", kind="weekly", name="n", webhook_name="g", status="maybe", preview="p")
