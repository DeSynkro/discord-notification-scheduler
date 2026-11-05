from calendar import monthrange
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

REPEATS = ("none", "daily", "weekly", "monthly", "yearly")


def _local_occurrences(
    alert_date: date,
    alert_time: time,
    tz_name: str,
    repeat: str,
) -> Iterator[datetime]:
    if repeat not in REPEATS:
        raise ValueError(f"Unknown repeat: {repeat}")

    tz = ZoneInfo(tz_name)
    first = datetime.combine(alert_date, alert_time, tzinfo=tz)

    if repeat == "none":
        yield first
        return

    if repeat == "daily":
        current = first
        while True:
            yield current
            current = current + timedelta(days=1)
    elif repeat == "weekly":
        current = first
        while True:
            yield current
            current = current + timedelta(days=7)
    elif repeat == "monthly":
        index = 0
        while True:
            total = (alert_date.month - 1) + index
            year = alert_date.year + total // 12
            month = total % 12 + 1
            day = min(alert_date.day, monthrange(year, month)[1])
            yield first.replace(year=year, month=month, day=day)
            index += 1
    else:  # yearly
        index = 0
        while True:
            year = alert_date.year + index
            day = min(alert_date.day, monthrange(year, alert_date.month)[1])
            yield first.replace(year=year, day=day)
            index += 1


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def compute_next_fire(
    alert_date: date,
    alert_time: time,
    tz_name: str,
    repeat: str,
    after_utc: datetime | None = None,
) -> str | None:
    after = _as_utc(after_utc) if after_utc is not None else None
    for local in _local_occurrences(alert_date, alert_time, tz_name, repeat):
        candidate = _as_utc(local)
        if after is None or candidate > after:
            return candidate.isoformat()
    return None


def occurrences_between(
    alert_date: date,
    alert_time: time,
    tz_name: str,
    repeat: str,
    start_utc: datetime,
    end_utc: datetime,
) -> list[datetime]:
    start = _as_utc(start_utc)
    end = _as_utc(end_utc)
    found: list[datetime] = []
    for local in _local_occurrences(alert_date, alert_time, tz_name, repeat):
        candidate = _as_utc(local)
        if candidate >= end:
            break
        if candidate >= start:
            found.append(candidate)
            if len(found) >= 62:
                break
    return found
