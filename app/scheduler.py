from datetime import date as dt_date
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.discord import deliver
from app.models import Alarm, CalendarAlert, DAYS_OF_WEEK
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


def _update_record(
    kind: str,
    record_id: str,
    *,
    expect_next_fire: str | None = None,
    **fields,
) -> bool:
    """Update only one record, re-reading the file first.

    This avoids overwriting edits that happened while a delivery was in
    flight. When expect_next_fire is given, the update is skipped if the
    stored next_fire no longer matches it, meaning the user edited or
    disabled the alert mid-delivery.
    """
    rows = read_json(kind)
    for row in rows:
        if row.get("id") != record_id:
            continue
        if expect_next_fire is not None and row.get("next_fire") != expect_next_fire:
            return False
        row.update(fields)
        write_json(kind, rows)
        return True
    return False


async def _poll_weekly(now: datetime) -> None:
    _reset_minute(now)

    for item in read_json("alarms"):
        try:
            alarm = Alarm(**item)
            if not alarm.enabled:
                continue

            try:
                tz = ZoneInfo(alarm.timezone)
            except (KeyError, ValueError):
                tz = dt_timezone.utc
            local_now = now.astimezone(tz)

            if local_now.strftime("%H:%M") != alarm.time:
                continue
            if DAYS_OF_WEEK[local_now.weekday()] not in alarm.days:
                continue

            # A fall-back DST transition repeats the same wall-clock time
            # twice in one local day. Do not send it twice.
            last_fired = item.get("last_fired")
            if last_fired:
                try:
                    last_local = datetime.fromisoformat(last_fired).astimezone(tz)
                    if (
                        last_local.date() == local_now.date()
                        and last_local.strftime("%H:%M") == alarm.time
                    ):
                        continue
                except Exception:
                    pass

            key = f"alarm:{alarm.id}"
            if key in _sent_this_minute:
                continue
            _sent_this_minute.add(key)

            success, err = await deliver(alarm, "weekly", alarm.id)
            if success:
                _update_record(
                    "alarms", alarm.id,
                    last_fired=now.isoformat(), last_error=None,
                )
            else:
                _update_record("alarms", alarm.id, last_error=err)
        except Exception:
            # One bad record must never stop the rest of the pass.
            continue


async def _poll_calendar(now: datetime) -> None:
    _reset_minute(now)

    for item in read_json("calendar"):
        try:
            alert = CalendarAlert(**item)
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
                nxt = compute_next_fire(
                    anchor_date, anchor_time, alert.timezone, alert.repeat,
                    after_utc=now,
                )
                fields = {"next_fire": nxt}
                if nxt is None:
                    fields["enabled"] = False
                _update_record(
                    "calendar", alert.id,
                    expect_next_fire=item.get("next_fire"),
                    **fields,
                )
                continue

            if next_fire > now:
                continue

            if now - next_fire > timedelta(minutes=5):
                nxt = compute_next_fire(
                    anchor_date, anchor_time, alert.timezone, alert.repeat,
                    after_utc=now,
                )
                fields = {"next_fire": nxt}
                if nxt is None:
                    fields["enabled"] = False
                _update_record(
                    "calendar", alert.id,
                    expect_next_fire=item.get("next_fire"),
                    **fields,
                )
                continue

            key = f"calendar:{alert.id}"
            if key in _sent_this_minute:
                continue
            _sent_this_minute.add(key)

            success, err = await deliver(alert, "calendar", alert.id)
            nxt = compute_next_fire(
                anchor_date, anchor_time, alert.timezone, alert.repeat,
                after_utc=next_fire,
            )
            fields = {"next_fire": nxt}
            if success:
                fields["last_fired"] = now.isoformat()
                fields["last_error"] = None
            else:
                fields["last_error"] = err
            if nxt is None:
                fields["enabled"] = False

            _update_record(
                "calendar", alert.id,
                expect_next_fire=item.get("next_fire"),
                **fields,
            )
        except Exception:
            continue


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
