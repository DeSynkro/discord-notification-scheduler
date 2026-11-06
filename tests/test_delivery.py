import asyncio
from datetime import datetime, timezone

from app import discord, scheduler
from app.models import Alarm
from app.storage import write_json


def _alarm():
    return Alarm(name="T", webhook_name="g", message="m", time="09:00")


def test_build_payload_uses_alarm_color_for_embed():
    alarm = Alarm(
        name="T", webhook_name="g", message="m", time="09:00",
        message_type="embed", color="#FF0000",
        embed={"title": "Report"},
    )
    payload = discord._build_payload(alarm)
    assert payload["embeds"][0]["color"] == 0xFF0000


def test_build_payload_prefers_alarm_color_over_legacy_embed_color():
    alarm = Alarm(
        name="T", webhook_name="g", message="m", time="09:00",
        message_type="embed", color="#0000FF",
        embed={"title": "Report", "color": "#FF0000"},
    )
    payload = discord._build_payload(alarm)
    assert payload["embeds"][0]["color"] == 0x0000FF


def test_build_payload_keeps_legacy_embed_color_without_alarm_color():
    alarm = Alarm(
        name="T", webhook_name="g", message="m", time="09:00",
        message_type="embed",
        embed={"title": "Report", "color": "#00FF00"},
    )
    payload = discord._build_payload(alarm)
    assert payload["embeds"][0]["color"] == 0x00FF00


def test_deliver_logs_success(monkeypatch):
    calls = {}

    async def fake_send(alarm):
        return True, ""

    def fake_log(kind, item, source_id, success, error):
        calls.update(kind=kind, source_id=source_id, success=success, error=error)

    monkeypatch.setattr(discord, "send_webhook", fake_send)
    monkeypatch.setattr(discord, "append_log", fake_log)

    alarm = _alarm()
    ok, err = asyncio.run(discord.deliver(alarm, "weekly", alarm.id))
    assert ok is True and err == ""
    assert calls == {
        "kind": "weekly",
        "source_id": alarm.id,
        "success": True,
        "error": "",
    }


def test_deliver_logs_failure(monkeypatch):
    calls = {}

    async def fake_send(alarm):
        return False, "boom"

    def fake_log(kind, item, source_id, success, error):
        calls.update(kind=kind, source_id=source_id, success=success, error=error)

    monkeypatch.setattr(discord, "send_webhook", fake_send)
    monkeypatch.setattr(discord, "append_log", fake_log)

    alarm = _alarm()
    ok, err = asyncio.run(discord.deliver(alarm, "test", None))
    assert ok is False and err == "boom"
    assert calls == {
        "kind": "test",
        "source_id": None,
        "success": False,
        "error": "boom",
    }


def test_weekly_poll_skips_bad_record_and_delivers_good_one(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.DATA_DIR", tmp_path)
    write_json(
        "alarms",
        [
            {"id": "bad"},
            {
                "id": "good",
                "name": "Test",
                "webhook_name": "general",
                "message": "m",
                "message_type": "text",
                "embed": None,
                "time": "09:00",
                "days": ["Thursday"],
                "timezone": "UTC",
                "enabled": True,
            },
        ],
    )

    calls = []

    async def fake_deliver(alert, kind, source_id=None):
        calls.append((kind, source_id))
        return True, ""

    monkeypatch.setattr(scheduler, "deliver", fake_deliver)

    now = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
    asyncio.run(scheduler._poll_weekly(now))
    assert calls == [("weekly", "good")]
