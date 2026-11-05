from datetime import date as dt_date
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.discord import deliver
from app.models import Alarm, CalendarAlert
from app.recurrence import compute_next_fire
from app.storage import read_json, write_json

scheduler = AsyncIOScheduler(timezone=dt_timezone.utc)

# Keep track of what we already sent in the current minute. This stops us
# from double-sending when the polling job fires again before the clock
# ticks over to the next minute.
_sent_this_minute: set[str] = set()
_last_poll_key: tuple | None = None


def _reset_minute(now: datetime) -> None:
    global _last_poll_key
    key = (now.year, now.month, now.day, now.hour, now.minute)
    if key != _last_poll_key:
        _sent_this_minute.clear()
        _last_poll_key = key


async def _poll_weekly(now: datetime) -> None:
    _reset_minute(now)
    raw = read_json("alarms")
    changed = False

    for item in raw:
        try:
            alarm = Alarm(**item)
        except Exception:
            continue

        if not alarm.enabled:
            continue

        try:
            tz = ZoneInfo(alarm.timezone)
        except (KeyError, ValueError):
            tz = dt_timezone.utc
        local_now = now.astimezone(tz)

        if local_now.strftime("%H:%M") != alarm.time:
            continue

        if local_now.strftime("%A") not in alarm.days:
            continue

        key = f"alarm:{alarm.id}"
        if key in _sent_this_minute:
            continue
        _sent_this_minute.add(key)

        success, err = await deliver(alarm, "weekly", alarm.id)
        if success:
            item["last_fired"] = now.isoformat()
            item["last_error"] = None
        else:
            item["last_error"] = err
        changed = True

    if changed:
        write_json("alarms", raw)


async def _poll_calendar(now: datetime) -> None:
    _reset_minute(now)
    raw = read_json("calendar")
    changed = False

    for item in raw:
        try:
            alert = CalendarAlert(**item)
        except Exception:
            continue

        if not alert.enabled:
            continue

        anchor_date = dt_date.fromisoformat(alert.date)
        anchor_time = dt_time.fromisoformat(alert.time)

        try:
            next_fire = datetime.fromisoformat(item["next_fire"])
            if next_fire.tzinfo is None:
                next_fire = next_fire.replace(tzinfo=dt_timezone.utc)
            next_fire = next_fire.astimezone(dt_timezone.utc)
        except (KeyError, TypeError, ValueError):
            item["next_fire"] = compute_next_fire(
                anchor_date, anchor_time, alert.timezone, alert.repeat,
                after_utc=now,
            )
            changed = True
            continue

        if next_fire > now:
            continue

        if now - next_fire > timedelta(minutes=5):
            item["next_fire"] = compute_next_fire(
                anchor_date, anchor_time, alert.timezone, alert.repeat,
                after_utc=now,
            )
            if item["next_fire"] is None:
                item["enabled"] = False
            changed = True
            continue

        key = f"calendar:{alert.id}"
        if key in _sent_this_minute:
            continue
        _sent_this_minute.add(key)

        success, err = await deliver(alert, "calendar", alert.id)
        if success:
            item["last_fired"] = now.isoformat()
            item["last_error"] = None
        else:
            item["last_error"] = err

        item["next_fire"] = compute_next_fire(
            anchor_date, anchor_time, alert.timezone, alert.repeat,
            after_utc=next_fire,
        )
        if item["next_fire"] is None:
            item["enabled"] = False
        changed = True

    if changed:
        write_json("calendar", raw)


def recompute_all(now: datetime | None = None) -> None:
    now = now or datetime.now(dt_timezone.utc)
    raw = read_json("calendar")
    changed = False

    for item in raw:
        try:
            alert = CalendarAlert(**item)
        except Exception:
            continue

        next_fire = compute_next_fire(
            dt_date.fromisoformat(alert.date),
            dt_time.fromisoformat(alert.time),
            alert.timezone,
            alert.repeat,
            after_utc=now,
        )
        if next_fire != item.get("next_fire"):
            item["next_fire"] = next_fire
            changed = True
        if next_fire is None and item.get("enabled", True):
            item["enabled"] = False
            changed = True

    if changed:
        write_json("calendar", raw)


async def _poll(now: datetime | None = None) -> None:
    now = now or datetime.now(dt_timezone.utc)
    await _poll_weekly(now)
    await _poll_calendar(now)


def start():
    recompute_all()
    scheduler.add_job(
        _poll,
        "interval",
        seconds=60,
        id="alarm_poll",
        replace_existing=True,
        misfire_grace_time=30,
    )
    scheduler.start()


def stop():
    scheduler.shutdown(wait=False)
