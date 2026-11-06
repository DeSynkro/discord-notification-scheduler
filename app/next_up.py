"""Next-delivery board: derived schedule data for the dashboard hero."""

from datetime import date as dt_date
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from app.calendar_alerts import DISPLAY_TZ
from app.colors import effective_color
from app.icons import icon
from app.models import DAYS_OF_WEEK
from app.render import escape

RAIL_HOURS = 24


def _kind_label(item: dict) -> str:
    return "Weekly alarm" if item.get("kind") == "weekly" else "Calendar alert"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _next_weekly(alarm: dict, now: datetime) -> datetime | None:
    if not alarm.get("enabled", True):
        return None
    days = alarm.get("days") or DAYS_OF_WEEK
    try:
        hours, minutes = (int(part) for part in alarm["time"].split(":"))
        tz = ZoneInfo(alarm.get("timezone") or "UTC")
    except (KeyError, ValueError, TypeError):
        return None

    local_now = now.astimezone(tz)
    for offset in range(8):
        local_day = local_now.date() + timedelta(days=offset)
        if DAYS_OF_WEEK[local_day.weekday()] not in days:
            continue
        candidate = datetime.combine(local_day, dt_time(hours, minutes), tzinfo=tz)
        candidate_utc = candidate.astimezone(timezone.utc)
        if candidate_utc > now:
            return candidate_utc
    return None


def _next_calendar(alert: dict, now: datetime) -> datetime | None:
    if not alert.get("enabled", True):
        return None

    raw = alert.get("next_fire")
    if raw:
        try:
            candidate = _as_utc(datetime.fromisoformat(raw))
        except (TypeError, ValueError):
            candidate = None
        if candidate and candidate > now:
            return candidate

    try:
        from app.recurrence import compute_next_fire

        value = compute_next_fire(
            dt_date.fromisoformat(alert["date"]),
            dt_time.fromisoformat(alert["time"]),
            alert.get("timezone") or "UTC",
            alert.get("repeat") or "none",
            after_utc=now,
        )
    except (KeyError, ValueError, TypeError):
        return None
    return _as_utc(datetime.fromisoformat(value)) if value else None


def upcoming(
    alarms: list[dict],
    alerts: list[dict],
    webhooks: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    now = _as_utc(now or datetime.now(timezone.utc))
    known = {webhook.get("name") for webhook in webhooks}
    items: list[dict] = []

    for alarm in alarms:
        when = _next_weekly(alarm, now)
        if when is None:
            continue
        items.append({
            "id": alarm.get("id", ""),
            "kind": "weekly",
            "name": alarm.get("name", ""),
            "channel": alarm.get("webhook_name", ""),
            "missing": alarm.get("webhook_name") not in known,
            "when": when,
            "tz_name": alarm.get("timezone") or "UTC",
            "color": effective_color(alarm),
            "edit_url": f'/alarms/{alarm.get("id", "")}',
        })

    for alert in alerts:
        when = _next_calendar(alert, now)
        if when is None:
            continue
        items.append({
            "id": alert.get("id", ""),
            "kind": "calendar",
            "name": alert.get("name", ""),
            "channel": alert.get("webhook_name", ""),
            "missing": alert.get("webhook_name") not in known,
            "when": when,
            "tz_name": alert.get("timezone") or "UTC",
            "color": effective_color(alert),
            "edit_url": f'/calendar/{alert.get("id", "")}/edit',
        })

    items.sort(key=lambda item: (item["when"], item["name"].lower()))
    return items


def relative_time(when: datetime, now: datetime | None = None) -> str:
    now = _as_utc(now or datetime.now(timezone.utc))
    seconds = int((_as_utc(when) - now).total_seconds())
    if seconds <= 0:
        return "due now"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"in {days}d {hours}h"
    if hours:
        return f"in {hours}h {minutes}m"
    if minutes:
        return f"in {minutes}m"
    return f"in {secs}s"


def time_ago(value: str, now: datetime | None = None) -> str:
    try:
        when = _as_utc(datetime.fromisoformat(value))
    except (TypeError, ValueError):
        return ""
    now = _as_utc(now or datetime.now(timezone.utc))
    seconds = int((now - when).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    return when.astimezone(DISPLAY_TZ).strftime("%b %-d")


def _day_label(when: datetime, now: datetime) -> str:
    local_day = when.astimezone(DISPLAY_TZ).date()
    today = now.astimezone(DISPLAY_TZ).date()
    delta = (local_day - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return when.astimezone(DISPLAY_TZ).strftime("%a, %b %-d")


def _channel(name: str, missing: bool = False) -> str:
    cls = "channel missing" if missing else "channel"
    return f'<span class="{cls}"><span class="hash">#</span>{escape(name)}</span>'


def _key(item: dict) -> str:
    return f'{item.get("kind", "")}:{item.get("id", "")}'


def _rail(now: datetime, window: list[dict]) -> str:
    markers = []
    for index, item in enumerate(window[:8]):
        pct = (item["when"] - now).total_seconds() / (RAIL_HOURS * 3600) * 100
        pct = max(0.6, min(99.4, pct))
        local = item["when"].astimezone(DISPLAY_TZ)
        time_label = local.strftime("%a %-I:%M %p")
        kind_label = _kind_label(item)
        color = item.get("color")
        color_style = f' --marker-color:{escape(color)};' if color else ""
        aria = f'{kind_label}: {item["name"]}, {time_label}'
        if item.get("channel"):
            aria += f', #{item["channel"]}'
        aria += ". Edit"
        markers.append(
            f'<button type="button" class="rail-marker {escape(item["kind"])}" '
            f'data-key="{escape(_key(item))}" data-name="{escape(item["name"])}" '
            f'data-channel="{escape(item["channel"])}" data-time="{escape(time_label)}" '
            f'data-kind-label="{escape(kind_label)}" data-edit-url="{escape(item["edit_url"])}" '
            f'data-color="{escape(color) if color else ""}" aria-label="{escape(aria)}" '
            f'style="left:{pct:.2f}%;{color_style} --marker-delay:{index * 30}ms"></button>'
        )

    ticks = "".join(
        f'<span class="rail-tick" style="left:{pct}%"></span>' for pct in (25, 50, 75)
    )
    count = len(window)
    count_label = f"{count} in the next 24 hours" if count else "Quiet for 24 hours"

    return f"""<div class="next-rail">
  <div class="rail-head">
    <div class="rail-heading">
      <span class="rail-title">Your next 24 hours</span>
      <span class="rail-count" aria-live="polite">{count_label}</span>
    </div>
    <div class="rail-filter" role="group" aria-label="Filter deliveries">
      <button type="button" class="rail-filter-btn is-active" data-rail-filter="both" aria-pressed="true">Both</button>
      <button type="button" class="rail-filter-btn" data-rail-filter="weekly" aria-pressed="false">Alarms</button>
      <button type="button" class="rail-filter-btn" data-rail-filter="calendar" aria-pressed="false">Calendar</button>
    </div>
  </div>
  <div class="rail-track">
    <span class="rail-line"></span>
    {ticks}
    <span class="rail-now" title="Now"><span class="rail-now-dot"></span></span>
    {''.join(markers)}
  </div>
  <div class="rail-labels"><span>now</span><span>6h</span><span>12h</span><span>18h</span><span>24h</span></div>
  <div class="rail-hint">Hover a pin to preview / click a pin or row to edit</div>
</div>"""


def _then_rows(window: list[dict]) -> str:
    rows = []
    for item in window[:8]:
        local = item["when"].astimezone(DISPLAY_TZ)
        color_style = f' style="background:{escape(item["color"])}"' if item.get("color") else ""
        rows.append(f"""<button type="button" class="then-row" data-kind="{escape(item['kind'])}" data-edit-url="{escape(item['edit_url'])}" aria-label="Edit {escape(item['name'])}">
    <span class="kind-dot {escape(item['kind'])}"{color_style}></span>
    <span class="then-time">{local.strftime('%a %-I:%M %p')}</span>
    <span class="then-name">{escape(item['name'])}</span>
    {_channel(item['channel'], item['missing'])}
  </button>""")

    if not rows:
        return '<span class="then-empty">No deliveries in the next 24 hours</span>'

    return "".join(rows) + '<span class="then-empty then-filter-empty" hidden></span>'


def _empty(webhooks: list[dict], now: datetime) -> str:
    if webhooks:
        primary = (
            '<button class="btn btn-primary" hx-get="/alarms/new" '
            'hx-target="#modal-area" hx-swap="innerHTML">'
            f'{icon("plus", 14)} New alarm</button>'
        )
        secondary = (
            '<button class="btn" hx-get="/calendar/new" '
            'hx-target="#modal-area" hx-swap="innerHTML">New alert</button>'
        )
        copy = "Add an alarm or a calendar alert and the next delivery shows up here."
    else:
        primary = (
            '<button class="btn btn-primary" hx-get="/webhooks/new" '
            'hx-target="#modal-area" hx-swap="innerHTML">'
            f'{icon("plus", 14)} Add channel</button>'
        )
        secondary = (
            '<button class="btn" hx-get="/webhooks/help" '
            'hx-target="#modal-area" hx-swap="innerHTML">Setup guide</button>'
        )
        copy = "Add your first Discord channel, then schedule an alarm."

    return f"""<section class="next-up is-empty" id="next-up">
  <div class="next-lead">
    <span class="next-eyebrow">Next delivery</span>
    <h2 class="next-empty-title">Nothing scheduled</h2>
    <p class="next-empty-copy">{copy}</p>
    <div class="next-empty-actions">{primary}{secondary}</div>
  </div>
  <div class="next-rail is-empty">
    <div class="rail-head">
      <span class="rail-title">Your next 24 hours</span>
      <span class="rail-count" aria-live="polite">Quiet for 24 hours</span>
    </div>
    <div class="rail-track">
      <span class="rail-line"></span>
      <span class="rail-now"><span class="rail-now-dot"></span></span>
    </div>
    <div class="rail-labels"><span>now</span><span>6h</span><span>12h</span><span>18h</span><span>24h</span></div>
  </div>
</section>"""


def render_next_up(
    webhooks: list[dict],
    alarms: list[dict],
    alerts: list[dict],
    now: datetime | None = None,
) -> str:
    now = _as_utc(now or datetime.now(timezone.utc))
    items = upcoming(alarms, alerts, webhooks, now)
    if not items:
        return _empty(webhooks, now)

    first = items[0]
    local = first["when"].astimezone(DISPLAY_TZ)
    clock = local.strftime("%I:%M").lstrip("0")
    period = local.strftime("%p")
    day_label = _day_label(first["when"], now)
    countdown = relative_time(first["when"], now)
    kind_label = "Weekly alarm" if first["kind"] == "weekly" else "Calendar alert"
    try:
        source = first["when"].astimezone(ZoneInfo(first["tz_name"]))
    except Exception:
        source = local
    source_label = f'{source.strftime("%-I:%M %p")} {first["tz_name"]}'
    window = [item for item in items if item["when"] <= now + timedelta(hours=RAIL_HOURS)]
    counts = {
        "both": len(window),
        "weekly": sum(1 for item in window if item["kind"] == "weekly"),
        "calendar": sum(1 for item in window if item["kind"] == "calendar"),
    }

    return f"""<section class="next-up" id="next-up" data-next-key="{escape(_key(first))}" data-count-both="{counts['both']}" data-count-weekly="{counts['weekly']}" data-count-calendar="{counts['calendar']}" aria-label="Next delivery">
  <div class="next-lead">
    <span class="next-eyebrow"><span class="live-dot"></span>Next delivery</span>
    <div class="next-clock">
      <span class="next-time">{clock}</span>
      <span class="next-period">{period}</span>
    </div>
    <div class="next-when"><span class="next-day">{day_label}</span><span class="sep">/</span><span class="next-count" data-countdown="{first['when'].isoformat()}">{countdown}</span></div>
    <div class="next-name">{escape(first['name'])}</div>
    <div class="next-meta">{_channel(first['channel'], first['missing'])}<span class="sep">/</span>{escape(kind_label)}<span class="sep">/</span>{escape(source_label)}</div>
  </div>
  <div class="next-rail-wrap">
    {_rail(now, window)}
    <div class="rail-then">{_then_rows(window)}</div>
  </div>
</section>"""


def board_data(
    webhooks: list[dict],
    alarms: list[dict],
    alerts: list[dict],
    now: datetime | None = None,
) -> dict:
    now = _as_utc(now or datetime.now(timezone.utc))
    items = upcoming(alarms, alerts, webhooks, now)
    if not items:
        return {"empty": True}

    first = items[0]
    local = first["when"].astimezone(DISPLAY_TZ)
    kind_label = "Weekly alarm" if first["kind"] == "weekly" else "Calendar alert"
    try:
        source = first["when"].astimezone(ZoneInfo(first["tz_name"]))
    except Exception:
        source = local
    source_label = f'{source.strftime("%-I:%M %p")} {first["tz_name"]}'
    window = [item for item in items if item["when"] <= now + timedelta(hours=RAIL_HOURS)]

    markers = []
    for index, item in enumerate(window[:8]):
        pct = (item["when"] - now).total_seconds() / (RAIL_HOURS * 3600) * 100
        pct = max(0.6, min(99.4, pct))
        local_when = item["when"].astimezone(DISPLAY_TZ)
        markers.append({
            "key": _key(item),
            "kind": item["kind"],
            "left_pct": round(pct, 2),
            "delay": index * 30,
            "name": item["name"],
            "channel": item["channel"],
            "time_label": local_when.strftime("%a %-I:%M %p"),
            "kind_label": _kind_label(item),
            "edit_url": item["edit_url"],
            "color": item.get("color"),
        })

    count = len(window)
    counts = {
        "both": count,
        "weekly": sum(1 for item in window if item["kind"] == "weekly"),
        "calendar": sum(1 for item in window if item["kind"] == "calendar"),
    }
    meta_html = (
        f'{_channel(first["channel"], first["missing"])}'
        f'<span class="sep">/</span>{escape(kind_label)}'
        f'<span class="sep">/</span>{escape(source_label)}'
    )

    return {
        "empty": False,
        "next_key": _key(first),
        "lead": {
            "time": local.strftime("%I:%M").lstrip("0"),
            "period": local.strftime("%p"),
            "day": _day_label(first["when"], now),
            "countdown_iso": first["when"].isoformat(),
            "countdown_text": relative_time(first["when"], now),
            "name": first["name"],
            "meta_html": meta_html,
        },
        "window": markers,
        "count": count,
        "counts": counts,
        "count_label": f"{count} in the next 24 hours" if count else "Quiet for 24 hours",
        "then_html": _then_rows(window),
    }
