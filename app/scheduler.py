from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.models import Alarm
from app.storage import read_json, write_json
from app.discord import deliver

scheduler = AsyncIOScheduler(timezone=dt_timezone.utc)

# Keep track of which alarms we already sent in the current minute.
# This stops us from double-sending when the polling job fires again
# before the clock ticks over to the next minute.
_sent_this_minute: set[str] = set()
_last_poll_minute: int = -1


async def _poll_weekly(now: datetime) -> None:
    global _last_poll_minute

    current_minute = now.minute

    # Reset the sent-this-minute tracker when the minute ticks over
    if current_minute != _last_poll_minute:
        _sent_this_minute.clear()
        _last_poll_minute = current_minute

    raw = read_json("alarms")
    changed = False

    for item in raw:
        try:
            alarm = Alarm(**item)
        except Exception:
            continue

        if not alarm.enabled:
            continue

        # Convert current time to the alarm's timezone
        try:
            tz = ZoneInfo(alarm.timezone)
        except (KeyError, ValueError):
            tz = dt_timezone.utc
        local_now = now.astimezone(tz)

        # Check if the time matches
        if local_now.strftime("%H:%M") != alarm.time:
            continue

        # Check if today is one of the selected days
        today_name = local_now.strftime("%A")
        if today_name not in alarm.days:
            continue

        # Already fired this alarm in this minute
        if alarm.id in _sent_this_minute:
            continue

        _sent_this_minute.add(alarm.id)
        success, err = await deliver(alarm, "weekly", alarm.id)

        if success:
            item["last_fired"] = datetime.now(dt_timezone.utc).isoformat()
            item["last_error"] = None
        else:
            item["last_error"] = err

        changed = True

    if changed:
        write_json("alarms", raw)


async def _poll(now: datetime | None = None) -> None:
    await _poll_weekly(now or datetime.now(dt_timezone.utc))


def start():
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
