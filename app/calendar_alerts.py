from datetime import date as dt_date
from datetime import datetime
from datetime import time as dt_time
from datetime import timezone as dt_timezone
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from app.discord import deliver
from app.models import DAYS_OF_WEEK, TIMEZONES, CalendarAlert
from app.recurrence import compute_next_fire, occurrences_between
from app.render import escape, message_fields, timezone_input, webhook_options
from app.storage import read_json, write_json

router = APIRouter()

DISPLAY_TZ = datetime.now().astimezone().tzinfo or dt_timezone.utc

REPEAT_OPTIONS = (
    ("none", "None (one-time)"),
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("yearly", "Yearly"),
)


def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _error_text(exc: Exception) -> str:
    return (" ".join(str(exc).split()) or "Invalid alert data")[:300]


def _toast(message: str, kind: str = "ok") -> dict[str, str]:
    clean = (" ".join(str(message).split()) or "Something went wrong")[:300]
    return {"X-Toast-Message": clean, "X-Toast-Type": kind}


def _modal_close() -> str:
    return '<div id="modal-area" hx-swap-oob="innerHTML"></div>'


def _repeat_options(selected: str) -> str:
    parts = []
    for value, label in REPEAT_OPTIONS:
        sel = " selected" if value == selected else ""
        parts.append(f'<option value="{value}"{sel}>{label}</option>')
    return "".join(parts)


def _build_alert(
    name: str,
    webhook_name: str,
    message: str,
    message_type: str,
    date: str,
    time: str,
    timezone: str,
    repeat: str,
    embed_title: str,
    embed_color: str,
    existing: dict | None = None,
) -> CalendarAlert:
    embed = None
    if message_type == "embed":
        embed = {"title": embed_title or None, "color": embed_color or None}

    preserved = {}
    if existing:
        for key in ("id", "created", "enabled", "last_fired", "last_error"):
            value = existing.get(key)
            if value is not None:
                preserved[key] = value

    alert = CalendarAlert(
        **preserved,
        name=name.strip(),
        webhook_name=webhook_name.strip(),
        message=message.strip(),
        message_type=message_type,
        date=date,
        time=time,
        timezone=timezone,
        repeat=repeat,
        embed=embed,
    )
    alert.next_fire = compute_next_fire(
        dt_date.fromisoformat(alert.date),
        dt_time.fromisoformat(alert.time),
        alert.timezone,
        alert.repeat,
        after_utc=_now(),
    )
    if alert.repeat == "none" and alert.next_fire is None:
        raise ValueError("One-time alerts must be in the future")
    return alert


def render_modal(alert: CalendarAlert | None = None, prefill_date: str = "") -> str:
    webhooks = read_json("webhooks")
    wh_options = webhook_options(webhooks, alert.webhook_name if alert else "")

    is_edit = alert is not None
    action = f'/calendar/{escape(alert.id)}' if is_edit else '/calendar'
    method = "hx-put" if is_edit else "hx-post"
    title = "Edit Calendar Alert" if is_edit else "New Calendar Alert"
    name_val = escape(alert.name) if alert else ""
    msg_val = alert.message if alert else ""
    msg_type = alert.message_type if alert else "text"
    embed = alert.embed.model_dump() if alert and alert.embed else None
    default_date = prefill_date or datetime.now().date().isoformat()
    date_val = escape(alert.date if alert else default_date)
    time_val = escape(alert.time if alert else "09:00")
    repeat_val = alert.repeat if alert else "none"
    tz_val = alert.timezone if alert else "UTC"

    if is_edit:
        enabled_row = f"""<div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:0.6rem">
        <span class="hint">Enabled</span>
        <label class="toggle" title="Enable or disable this alert">
          <input type="checkbox" {"checked" if alert.enabled else ""} hx-post="/calendar/{escape(alert.id)}/toggle" hx-swap="none">
          <span class="slider"></span>
        </label>
      </div>"""
        left_actions = f"""<div style="display:flex;gap:0.5rem">
          <button type="button" class="btn btn-danger btn-sm" hx-delete="/calendar/{escape(alert.id)}" hx-swap="none" hx-confirm="Delete this alert?">Delete</button>
          <button type="button" class="btn btn-sm" hx-post="/calendar/{escape(alert.id)}/test" hx-swap="none">&#x25b6; Test</button>
        </div>"""
    else:
        enabled_row = ""
        left_actions = "<span></span>"

    submit_label = "Save" if is_edit else "Create Alert"

    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{title}</h3>
      <button class="btn-icon" onclick="closeModal()">&times;</button>
    </div>
    <form {method}="{action}" hx-swap="none" id="calendar-form">
      {enabled_row}
      <label>Name</label>
      <input type="text" name="name" value="{name_val}" required maxlength="100">

      <label>Webhook</label>
      <select name="webhook_name" required>
        <option value="">-- Select --</option>
        {wh_options}
      </select>

      {message_fields(msg_val, msg_type, embed)}

      <label class="form-section-label">When</label>
      <div class="field-row">
        <div>
          <label>Date</label>
          <input type="date" name="date" value="{date_val}" required>
        </div>
        <div>
          <label>Time</label>
          <input type="time" name="time" value="{time_val}" required>
        </div>
        <div>
          <label>Repeat</label>
          <select name="repeat">{_repeat_options(repeat_val)}</select>
        </div>
      </div>

      {timezone_input(tz_val, TIMEZONES)}
      <p class="hint" style="margin-top:0.4rem">One-time alerts deactivate after they fire. Repeating alerts keep the same day each cycle, and short months clamp to their last day.</p>

      <div class="modal-actions" style="justify-content:space-between">
        {left_actions}
        <div style="display:flex;gap:0.5rem">
          <button type="button" class="btn" onclick="closeModal()">Cancel</button>
          <button type="submit" class="btn btn-primary">{submit_label}</button>
        </div>
      </div>
    </form>
  </div>
</div>"""


WEEKDAY_NAMES = tuple(DAYS_OF_WEEK)


def current_month() -> dt_date:
    return datetime.now(DISPLAY_TZ).date().replace(day=1)


def _shift_month(month: dt_date, delta: int) -> dt_date:
    total = (month.year * 12 + (month.month - 1)) + delta
    return dt_date(total // 12, total % 12 + 1, 1)


def _month_bounds(month: dt_date) -> tuple[dt_date, dt_date]:
    start = month.replace(day=1)
    return start, _shift_month(start, 1)


def _event(kind: str, row: dict, time_value: str) -> dict:
    return {
        "kind": kind,
        "id": row.get("id", ""),
        "name": row.get("name", ""),
        "time": time_value,
    }


def _weekly_events_for_day(day: dt_date, alarms: list[dict]) -> list[dict]:
    weekday = WEEKDAY_NAMES[day.weekday()]
    events = []
    for alarm in alarms:
        if not alarm.get("enabled", True):
            continue
        if weekday not in alarm.get("days", []):
            continue
        events.append(_event("weekly", alarm, alarm.get("time", "")))
    return events


def _calendar_events_by_day(month: dt_date, alerts: list[dict]) -> dict[dt_date, list[dict]]:
    start, end = _month_bounds(month)
    start_utc = datetime.combine(start, dt_time.min, tzinfo=DISPLAY_TZ).astimezone(dt_timezone.utc)
    end_utc = datetime.combine(end, dt_time.min, tzinfo=DISPLAY_TZ).astimezone(dt_timezone.utc)
    grouped: dict[dt_date, list[dict]] = {}

    for row in alerts:
        try:
            alert = CalendarAlert(**row)
        except Exception:
            continue
        if not alert.enabled:
            continue
        for occurrence in occurrences_between(
            dt_date.fromisoformat(alert.date),
            dt_time.fromisoformat(alert.time),
            alert.timezone,
            alert.repeat,
            start_utc,
            end_utc,
        ):
            day = occurrence.astimezone(DISPLAY_TZ).date()
            if start <= day < end:
                grouped.setdefault(day, []).append(_event("calendar", row, alert.time))
    return grouped


def _events_for_day(day: dt_date, alarms: list[dict], alerts: list[dict]) -> list[dict]:
    events = _weekly_events_for_day(day, alarms)
    day_start = datetime.combine(day, dt_time.min, tzinfo=DISPLAY_TZ)
    start_utc = day_start.astimezone(dt_timezone.utc)
    end_utc = (day_start + timedelta(days=1)).astimezone(dt_timezone.utc)

    for row in alerts:
        try:
            alert = CalendarAlert(**row)
        except Exception:
            continue
        if not alert.enabled:
            continue
        for occurrence in occurrences_between(
            dt_date.fromisoformat(alert.date),
            dt_time.fromisoformat(alert.time),
            alert.timezone,
            alert.repeat,
            start_utc,
            end_utc,
        ):
            if occurrence.astimezone(DISPLAY_TZ).date() == day:
                events.append(_event("calendar", row, alert.time))
                break

    events.sort(key=lambda event: (event["time"], event["name"].lower()))
    return events


def _event_url(event: dict) -> str:
    if event["kind"] == "weekly":
        return f'/alarms/{escape(event["id"])}'
    return f'/calendar/{escape(event["id"])}/edit'


def _event_pill(event: dict) -> str:
    return (
        f'<span class="cal-event {event["kind"]}" role="button" tabindex="0" '
        f'hx-get="{_event_url(event)}" hx-target="#modal-area" hx-swap="innerHTML" '
        f'hx-on:click="event.stopPropagation()" '
        f'title="{escape(event["name"])}, {escape(event["time"])}">'
        f'{escape(event["name"])}</span>'
    )


def _day_cell(day: dt_date, month: dt_date, today: dt_date, events: list[dict]) -> str:
    classes = ["cal-day"]
    if day.month != month.month:
        classes.append("out")
    if day == today:
        classes.append("today")

    pills = "".join(_event_pill(event) for event in events[:3])
    if len(events) > 3:
        pills += (
            f'<span class="cal-more" role="button" tabindex="0" '
            f'hx-get="/calendar/day?date={day.isoformat()}" hx-target="#modal-area" '
            f'hx-swap="innerHTML" hx-on:click="event.stopPropagation()">'
            f'+{len(events) - 3} more</span>'
        )

    return f"""<div class="{' '.join(classes)}" role="button" tabindex="0" hx-get="/calendar/new?date={day.isoformat()}" hx-target="#modal-area" hx-swap="innerHTML">
  <span class="cal-num">{day.day}</span>
  <span class="cal-add">+</span>
  <div class="cal-events">{pills}</div>
</div>"""


def render_month(month: dt_date, webhooks: list[dict], alarms: list[dict], alerts: list[dict]) -> str:
    month = month.replace(day=1)
    start, end = _month_bounds(month)
    dated = _calendar_events_by_day(month, alerts)
    today = datetime.now(DISPLAY_TZ).date()
    grid_start = start - timedelta(days=start.weekday())

    cells = []
    for offset in range(42):
        day = grid_start + timedelta(days=offset)
        events = []
        if start <= day < end:
            events.extend(_weekly_events_for_day(day, alarms))
            events.extend(dated.get(day, []))
        events.sort(key=lambda event: (event["time"], event["name"].lower()))
        cells.append(_day_cell(day, month, today, events))

    prev_month = _shift_month(month, -1).strftime("%Y-%m")
    next_month = _shift_month(month, 1).strftime("%Y-%m")
    today_month = today.replace(day=1).strftime("%Y-%m")
    weekdays = "".join(
        f"<span>{name}</span>" for name in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    )

    header = f"""<input type="hidden" id="cal-month" name="month" value="{month.strftime('%Y-%m')}">
<div class="cal-header">
  <div class="cal-controls">
    <button class="btn btn-sm" hx-get="/calendar?month={today_month}" hx-target="#calendar-view" hx-swap="innerHTML">Today</button>
    <button class="btn-icon" hx-get="/calendar?month={prev_month}" hx-target="#calendar-view" hx-swap="innerHTML" title="Previous month">&#x2039;</button>
    <span class="cal-month">{month.strftime('%B %Y')}</span>
    <button class="btn-icon" hx-get="/calendar?month={next_month}" hx-target="#calendar-view" hx-swap="innerHTML" title="Next month">&#x203a;</button>
  </div>
  <button class="btn btn-primary btn-sm" hx-get="/calendar/new?date={today.isoformat()}" hx-target="#modal-area" hx-swap="innerHTML">+ New Alert</button>
</div>
<div class="cal-legend">
  <span><i class="dot weekly"></i> Weekly alarm</span>
  <span><i class="dot dated"></i> Calendar alert</span>
</div>"""

    return f"""{header}
<div class="calendar">
  <div class="cal-weekdays">{weekdays}</div>
  <div class="cal-grid">{''.join(cells)}</div>
</div>
<p class="cal-hint">Click a day to add an alert. Click a green event to edit it.</p>"""


def render_day_modal(day: dt_date, webhooks: list[dict], alarms: list[dict], alerts: list[dict]) -> str:
    events = _events_for_day(day, alarms, alerts)
    rows = []
    for event in events:
        label = "Weekly alarm" if event["kind"] == "weekly" else "Calendar alert"
        rows.append(f"""<div class="day-event-row">
  <span class="cal-event {event['kind']}">{escape(event['name'])}</span>
  <span class="day-event-meta">{escape(event['time'])} &middot; {label}</span>
  <button class="btn-icon btn-icon-xs" hx-get="{_event_url(event)}" hx-target="#modal-area" hx-swap="innerHTML" title="Edit">&#x270e;</button>
</div>""")

    body = "".join(rows) or '<p class="empty">No alerts on this day.</p>'
    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{day.strftime('%A, %B %-d')}</h3>
      <button class="btn-icon" onclick="closeModal()">&times;</button>
    </div>
    <div class="day-list">{body}</div>
    <div class="modal-actions" style="justify-content:space-between">
      <button type="button" class="btn" onclick="closeModal()">Close</button>
      <button class="btn btn-primary" hx-get="/calendar/new?date={day.isoformat()}" hx-target="#modal-area" hx-swap="innerHTML">+ Add alert</button>
    </div>
  </div>
</div>"""


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_fragment(month: str = ""):
    try:
        month_date = datetime.strptime(month, "%Y-%m").date()
    except (TypeError, ValueError):
        month_date = current_month()
    return render_month(
        month_date,
        read_json("webhooks"),
        read_json("alarms"),
        read_json("calendar"),
    )


@router.get("/calendar/day", response_class=HTMLResponse)
async def calendar_day_modal(date: str = ""):
    try:
        day = dt_date.fromisoformat(date)
    except (TypeError, ValueError):
        day = datetime.now(DISPLAY_TZ).date()
    return render_day_modal(
        day,
        read_json("webhooks"),
        read_json("alarms"),
        read_json("calendar"),
    )


@router.get("/calendar/new", response_class=HTMLResponse)
async def new_calendar_alert_form(date: str = ""):
    return render_modal(None, date)


@router.get("/calendar/{alert_id}/edit", response_class=HTMLResponse)
async def edit_calendar_alert_form(alert_id: str):
    row = next((r for r in read_json("calendar") if r["id"] == alert_id), None)
    if row is None:
        return HTMLResponse("", status_code=404, headers=_toast("Alert not found", "err"))
    try:
        alert = CalendarAlert(**row)
    except Exception as exc:
        return HTMLResponse("", status_code=400, headers=_toast(_error_text(exc), "err"))
    return render_modal(alert)


@router.post("/calendar", response_class=HTMLResponse)
async def create_calendar_alert(
    name: Annotated[str, Form()],
    webhook_name: Annotated[str, Form()],
    message: Annotated[str, Form()],
    message_type: Annotated[str, Form()],
    date: Annotated[str, Form()],
    time: Annotated[str, Form()],
    timezone: Annotated[str, Form()],
    repeat: Annotated[str, Form()] = "none",
    embed_title: Annotated[str, Form()] = "",
    embed_color: Annotated[str, Form()] = "",
):
    try:
        alert = _build_alert(
            name, webhook_name, message, message_type,
            date, time, timezone, repeat, embed_title, embed_color,
        )
    except Exception as exc:
        return HTMLResponse("", status_code=400, headers=_toast(_error_text(exc), "err"))

    rows = read_json("calendar")
    rows.append(alert.model_dump())
    write_json("calendar", rows)
    return HTMLResponse(
        _modal_close(),
        headers={
            **_toast(f'Alert "{alert.name}" created'),
            "HX-Trigger": "refresh-lists",
            "X-Close-Modal": "1",
        },
    )


@router.put("/calendar/{alert_id}", response_class=HTMLResponse)
async def update_calendar_alert(
    alert_id: str,
    name: Annotated[str, Form()],
    webhook_name: Annotated[str, Form()],
    message: Annotated[str, Form()],
    message_type: Annotated[str, Form()],
    date: Annotated[str, Form()],
    time: Annotated[str, Form()],
    timezone: Annotated[str, Form()],
    repeat: Annotated[str, Form()] = "none",
    embed_title: Annotated[str, Form()] = "",
    embed_color: Annotated[str, Form()] = "",
):
    rows = read_json("calendar")
    idx = next((i for i, row in enumerate(rows) if row["id"] == alert_id), None)
    if idx is None:
        return HTMLResponse("", status_code=404, headers=_toast("Alert not found", "err"))

    try:
        alert = _build_alert(
            name, webhook_name, message, message_type,
            date, time, timezone, repeat, embed_title, embed_color,
            existing=rows[idx],
        )
    except Exception as exc:
        return HTMLResponse("", status_code=400, headers=_toast(_error_text(exc), "err"))

    rows[idx] = alert.model_dump()
    write_json("calendar", rows)
    return HTMLResponse(
        _modal_close(),
        headers={
            **_toast(f'Alert "{alert.name}" saved'),
            "HX-Trigger": "refresh-lists",
            "X-Close-Modal": "1",
        },
    )


@router.delete("/calendar", response_class=HTMLResponse)
async def delete_all_calendar_alerts():
    rows = read_json("calendar")
    write_json("calendar", [])
    return HTMLResponse(
        "",
        headers={**_toast(f"Deleted {len(rows)} alert(s)"), "HX-Trigger": "refresh-lists"},
    )


@router.delete("/calendar/{alert_id}", response_class=HTMLResponse)
async def delete_calendar_alert(alert_id: str):
    rows = read_json("calendar")
    remaining = [row for row in rows if row["id"] != alert_id]
    if len(remaining) == len(rows):
        return HTMLResponse("", status_code=404, headers=_toast("Alert not found", "err"))
    write_json("calendar", remaining)
    return HTMLResponse(
        _modal_close(),
        headers={
            **_toast("Alert deleted"),
            "HX-Trigger": "refresh-lists",
            "X-Close-Modal": "1",
        },
    )


@router.post("/calendar/{alert_id}/toggle", response_class=HTMLResponse)
async def toggle_calendar_alert(alert_id: str):
    rows = read_json("calendar")
    row = next((r for r in rows if r["id"] == alert_id), None)
    if row is None:
        return HTMLResponse("", status_code=404, headers=_toast("Alert not found", "err"))

    row["enabled"] = not row.get("enabled", True)
    write_json("calendar", rows)
    state = "enabled" if row["enabled"] else "disabled"
    return HTMLResponse(
        "",
        headers={**_toast(f'Alert "{row.get("name", "")}" {state}'), "HX-Trigger": "refresh-lists"},
    )


@router.post("/calendar/{alert_id}/test", response_class=HTMLResponse)
async def test_calendar_alert(alert_id: str):
    rows = read_json("calendar")
    row = next((r for r in rows if r["id"] == alert_id), None)
    if row is None:
        return HTMLResponse("", status_code=404, headers=_toast("Alert not found", "err"))

    try:
        alert = CalendarAlert(**row)
    except Exception as exc:
        return HTMLResponse("", status_code=400, headers=_toast(_error_text(exc), "err"))

    success, err = await deliver(alert, "test", alert.id)
    if success:
        row["last_fired"] = _now().isoformat()
        row["last_error"] = None
        write_json("calendar", rows)
        return HTMLResponse(
            "",
            headers={**_toast("Test message sent!"), "HX-Trigger": "refresh-lists"},
        )

    row["last_error"] = err
    write_json("calendar", rows)
    return HTMLResponse(
        "",
        headers={**_toast(f"Test failed: {err}", "err"), "HX-Trigger": "refresh-lists"},
    )
