from datetime import date as dt_date
from datetime import datetime
from datetime import time as dt_time
from datetime import timezone as dt_timezone
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, Request
from app.responses import SafeHTMLResponse as HTMLResponse

from app.discord import deliver
from app.colors import effective_color
from app.icons import icon
from app.models import DAYS_OF_WEEK, TIMEZONES, CalendarAlert
from app.recurrence import compute_next_fire, occurrences_between
from app.render import escape, message_fields, timezone_input, webhook_options
from app.storage import read_json, write_json

router = APIRouter()


def _display_tz():
    try:
        target = Path("/etc/localtime").resolve()
        marker = "zoneinfo/"
        if marker in str(target):
            return ZoneInfo(str(target).split(marker, 1)[1])
    except Exception:
        pass
    return datetime.now().astimezone().tzinfo or dt_timezone.utc


DISPLAY_TZ = _display_tz()

MIN_DAY = dt_date(1900, 1, 1)
MAX_DAY = dt_date(2200, 12, 31)
MIN_MONTH = MIN_DAY.replace(day=1)
MAX_MONTH = MAX_DAY.replace(day=1)

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
    color: str = "#3FB950",
    existing: dict | None = None,
    for_test: bool = False,
) -> CalendarAlert:
    chosen_color = (color or "#3FB950").strip()
    embed = None
    if message_type == "embed":
        embed = {"title": embed_title or None, "color": chosen_color}

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
        color=chosen_color,
    )
    alert.next_fire = compute_next_fire(
        dt_date.fromisoformat(alert.date),
        dt_time.fromisoformat(alert.time),
        alert.timezone,
        alert.repeat,
        after_utc=_now(),
    )
    if not for_test and alert.repeat == "none" and alert.next_fire is None:
        raise ValueError("One-time alerts must be in the future")
    return alert


def render_modal(alert: CalendarAlert | None = None, prefill_date: str = "") -> str:
    webhooks = read_json("webhooks")
    wh_options = webhook_options(webhooks, alert.webhook_name if alert else "")

    is_edit = alert is not None
    action = f'/calendar/{escape(alert.id)}' if is_edit else '/calendar'
    method = "hx-put" if is_edit else "hx-post"
    title = "Edit calendar alert" if is_edit else "New calendar alert"
    name_val = escape(alert.name) if alert else ""
    msg_val = alert.message if alert else ""
    msg_type = alert.message_type if alert else "text"
    embed = alert.embed.model_dump() if alert and alert.embed else None
    default_date = prefill_date or datetime.now().date().isoformat()
    date_val = escape(alert.date if alert else default_date)
    time_val = escape(alert.time if alert else "09:00")
    repeat_val = alert.repeat if alert else "none"
    tz_val = alert.timezone if alert else "UTC"
    color_val = escape(alert.color if alert else "#3FB950")

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
          <button type="button" class="btn btn-sm" hx-post="/calendar/{escape(alert.id)}/test" hx-include="closest form" hx-swap="none">{icon("play", 12)} Test</button>
        </div>"""
    else:
        enabled_row = ""
        left_actions = "<span></span>"

    submit_label = "Save" if is_edit else "Create alert"

    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{title}</h3>
      <button type="button" class="btn-icon" onclick="closeModal()" aria-label="Close">{icon("x", 16)}</button>
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

      <label for="calendar-color">Color<span class="hint"> used for the calendar, rail pin and embed</span></label>
      <div class="color-row">
        <input type="color" id="calendar-color" value="{color_val}" aria-label="Pick calendar color" oninput="this.nextElementSibling.value=this.value">
        <input type="text" name="color" class="color-text" id="calendar-color-hex" value="{color_val}" maxlength="7" required pattern="^#[0-9a-fA-F]{{6}}$" title="Hex color, e.g. #3FB950" aria-label="Calendar color hex" oninput="this.previousElementSibling.value=this.value">
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


def _event(
    kind: str,
    row: dict,
    time_value: str,
    color: str | None = None,
    enabled: bool = True,
) -> dict:
    return {
        "kind": kind,
        "id": row.get("id", ""),
        "name": row.get("name", ""),
        "time": time_value,
        "color": color,
        "enabled": enabled,
    }


def _weekly_occurrences(alarm: dict, start_dt: datetime, end_dt: datetime):
    try:
        tz = ZoneInfo(alarm["timezone"])
        alarm_time = dt_time.fromisoformat(alarm["time"])
    except Exception:
        return

    days = set(alarm.get("days", []))
    local_start = start_dt.astimezone(tz).date() - timedelta(days=1)
    local_end = end_dt.astimezone(tz).date() + timedelta(days=2)
    current = local_start
    while current < local_end:
        if WEEKDAY_NAMES[current.weekday()] in days:
            local_dt = datetime.combine(current, alarm_time, tzinfo=tz)
            yield local_dt.astimezone(DISPLAY_TZ)
        current += timedelta(days=1)


def _weekly_events_by_day(month: dt_date, alarms: list[dict]) -> dict[dt_date, list[dict]]:
    start, end = _month_bounds(month)
    start_dt = datetime.combine(start, dt_time.min, tzinfo=DISPLAY_TZ)
    end_dt = datetime.combine(end, dt_time.min, tzinfo=DISPLAY_TZ)
    grouped: dict[dt_date, list[dict]] = {}

    for alarm in alarms:
        if not alarm.get("enabled", True):
            continue
        for display_dt in _weekly_occurrences(alarm, start_dt, end_dt):
            day = display_dt.date()
            if start <= day < end:
                grouped.setdefault(day, []).append(
                    _event("weekly", alarm, display_dt.strftime("%H:%M"), effective_color(alarm))
                )
    return grouped


def _calendar_events_by_day(
    month: dt_date,
    alerts: list[dict],
    show_past: bool = False,
) -> dict[dt_date, list[dict]]:
    start, end = _month_bounds(month)
    start_utc = datetime.combine(start, dt_time.min, tzinfo=DISPLAY_TZ).astimezone(dt_timezone.utc)
    end_utc = datetime.combine(end, dt_time.min, tzinfo=DISPLAY_TZ).astimezone(dt_timezone.utc)
    grouped: dict[dt_date, list[dict]] = {}
    now_local = datetime.now(DISPLAY_TZ)

    for row in alerts:
        try:
            alert = CalendarAlert(**row)
        except Exception:
            continue
        for occurrence in occurrences_between(
            dt_date.fromisoformat(alert.date),
            dt_time.fromisoformat(alert.time),
            alert.timezone,
            alert.repeat,
            start_utc,
            end_utc,
        ):
            local = occurrence.astimezone(DISPLAY_TZ)
            day = local.date()
            if start <= day < end and (
                alert.enabled or (show_past and local < now_local)
            ):
                grouped.setdefault(day, []).append(
                    _event("calendar", row, local.strftime("%H:%M"), alert.color, alert.enabled)
                )
    return grouped


def _events_for_day(
    day: dt_date,
    alarms: list[dict],
    alerts: list[dict],
    show_weekly: bool = True,
    show_past: bool = False,
) -> list[dict]:
    day_start = datetime.combine(day, dt_time.min, tzinfo=DISPLAY_TZ)
    day_end = day_start + timedelta(days=1)
    start_utc = day_start.astimezone(dt_timezone.utc)
    end_utc = day_end.astimezone(dt_timezone.utc)
    now_local = datetime.now(DISPLAY_TZ)
    events: list[dict] = []

    if show_weekly:
        for alarm in alarms:
            if not alarm.get("enabled", True):
                continue
            for display_dt in _weekly_occurrences(alarm, day_start, day_end):
                if display_dt.date() == day:
                    events.append(
                        _event("weekly", alarm, display_dt.strftime("%H:%M"), effective_color(alarm))
                    )

    for row in alerts:
        try:
            alert = CalendarAlert(**row)
        except Exception:
            continue
        for occurrence in occurrences_between(
            dt_date.fromisoformat(alert.date),
            dt_time.fromisoformat(alert.time),
            alert.timezone,
            alert.repeat,
            start_utc,
            end_utc,
        ):
            local = occurrence.astimezone(DISPLAY_TZ)
            if local.date() == day and (
                alert.enabled or (show_past and local < now_local)
            ):
                events.append(
                    _event("calendar", row, local.strftime("%H:%M"), alert.color, alert.enabled)
                )
                break

    events.sort(key=lambda event: (event["time"], event["name"].lower()))
    return events


def _event_url(event: dict) -> str:
    if event["kind"] == "weekly":
        return f'/alarms/{escape(event["id"])}'
    return f'/calendar/{escape(event["id"])}/edit'


def _event_pill(event: dict) -> str:
    style = ""
    if event.get("color"):
        style = f' style="--event-color: {escape(event["color"])};"'
    disabled = " disabled" if event.get("enabled") is False else ""
    title = f'{escape(event["name"])}, {escape(event["time"])}'
    if event.get("enabled") is False:
        title += " (disabled)"
    return (
        f'<span class="cal-event {event["kind"]}{disabled}"{style} role="button" tabindex="0" '
        f'hx-get="{_event_url(event)}" hx-target="#modal-area" hx-swap="innerHTML" '
        f'hx-trigger="click, keyup[key==\'Enter\'], keyup[key==\' \']" hx-on:click="event.stopPropagation()" hx-on:keyup="event.stopPropagation()" '
        f'title="{title}">'
        f'{escape(event["name"])}</span>'
    )


def _day_cell(
    day: dt_date,
    month: dt_date,
    today: dt_date,
    events: list[dict],
    show_weekly: bool = True,
    show_past: bool = False,
) -> str:
    classes = ["cal-day"]
    if day.month != month.month:
        classes.append("out")
    if day == today:
        classes.append("today")

    pills = "".join(_event_pill(event) for event in events[:3])
    if len(events) > 3:
        params = (
            f"&show_weekly={1 if show_weekly else 0}"
            f"&show_past={1 if show_past else 0}"
        )
        pills += (
            f'<span class="cal-more" role="button" tabindex="0" '
            f'hx-get="/calendar/day?date={day.isoformat()}{params}" hx-target="#modal-area" '
            f'hx-swap="innerHTML" hx-trigger="click, keyup[key==\'Enter\'], keyup[key==\' \']" hx-on:click="event.stopPropagation()" hx-on:keyup="event.stopPropagation()">'
            f'+{len(events) - 3} more</span>'
        )

    return f"""<div class="{' '.join(classes)}" role="button" tabindex="0" hx-get="/calendar/new?date={day.isoformat()}" hx-target="#modal-area" hx-swap="innerHTML" hx-trigger="click, keyup[key=='Enter'], keyup[key==' ']">
  <span class="cal-num">{day.day}</span>
  <span class="cal-add">+</span>
  <div class="cal-events">{pills}</div>
</div>"""


def render_month(
    month: dt_date,
    webhooks: list[dict],
    alarms: list[dict],
    alerts: list[dict],
    show_weekly: bool = True,
    show_past: bool = False,
) -> str:
    month = month.replace(day=1)
    if month < MIN_MONTH:
        month = MIN_MONTH
    elif month > MAX_MONTH:
        month = MAX_MONTH
    start, end = _month_bounds(month)
    dated = _calendar_events_by_day(month, alerts, show_past)
    weekly = _weekly_events_by_day(month, alarms) if show_weekly else {}
    today = datetime.now(DISPLAY_TZ).date()
    new_date = today if (today.year == month.year and today.month == month.month) else month
    grid_start = start - timedelta(days=start.weekday())

    cells = []
    for offset in range(42):
        day = grid_start + timedelta(days=offset)
        events = []
        if start <= day < end:
            events.extend(weekly.get(day, []))
            events.extend(dated.get(day, []))
        events.sort(key=lambda event: (event["time"], event["name"].lower()))
        cells.append(_day_cell(day, month, today, events, show_weekly, show_past))

    prev_month = _shift_month(month, -1).strftime("%Y-%m")
    next_month = _shift_month(month, 1).strftime("%Y-%m")
    today_month = today.replace(day=1).strftime("%Y-%m")
    checked = "checked" if show_weekly else ""
    past_checked = "checked" if show_past else ""
    weekdays = "".join(
        f"<span>{name}</span>" for name in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    )

    header = f"""<input type="hidden" id="cal-month" name="month" value="{month.strftime('%Y-%m')}">
<div class="cal-header">
  <div class="cal-controls">
    <button class="btn btn-sm" hx-get="/calendar?month={today_month}" hx-target="#calendar-view" hx-swap="innerHTML" hx-trigger="click" hx-include="#show-weekly, #show-past">Today</button>
    <button class="btn-icon" hx-get="/calendar?month={prev_month}" hx-target="#calendar-view" hx-swap="innerHTML" hx-trigger="click" hx-include="#show-weekly, #show-past" title="Previous month">{icon("chevron-left", 16)}</button>
    <span class="cal-month">{month.strftime('%B %Y')}</span>
    <button class="btn-icon" hx-get="/calendar?month={next_month}" hx-target="#calendar-view" hx-swap="innerHTML" hx-trigger="click" hx-include="#show-weekly, #show-past" title="Next month">{icon("chevron-right", 16)}</button>
  </div>
  <div class="cal-actions">
    <label class="cal-toggle" title="Show weekly alarms on the calendar">
      <input type="checkbox" id="show-weekly" name="show_weekly" value="1" {checked}
             hx-get="/calendar" hx-target="#calendar-view" hx-swap="innerHTML"
             hx-include="#cal-month, #show-past" hx-trigger="change">
      Show weekly alarms
    </label>
    <label class="cal-toggle" title="Show past and fired alerts">
      <input type="checkbox" id="show-past" name="show_past" value="1" {past_checked}
             hx-get="/calendar" hx-target="#calendar-view" hx-swap="innerHTML"
             hx-include="#cal-month, #show-weekly" hx-trigger="change">
      Show past alerts
    </label>
    <button class="btn btn-primary btn-sm" hx-get="/calendar/new?date={new_date.isoformat()}" hx-target="#modal-area" hx-swap="innerHTML" hx-trigger="click">{icon("plus", 14)} New alert</button>
  </div>
</div>"""

    return f"""{header}
<div class="calendar">
  <div class="cal-weekdays">{weekdays}</div>
  <div class="cal-grid">{''.join(cells)}</div>
</div>
<p class="cal-hint">Click a day to add an alert. Click an event to edit it.</p>"""


def render_day_modal(
    day: dt_date,
    webhooks: list[dict],
    alarms: list[dict],
    alerts: list[dict],
    show_weekly: bool = True,
    show_past: bool = False,
) -> str:
    if day < MIN_DAY:
        day = MIN_DAY
    elif day > MAX_DAY:
        day = MAX_DAY
    events = _events_for_day(day, alarms, alerts, show_weekly, show_past)
    rows = []
    for event in events:
        label = "Weekly alarm" if event["kind"] == "weekly" else "Calendar alert"
        style = ""
        if event.get("color"):
            style = f' style="--event-color: {escape(event["color"])};"'
        disabled = " disabled" if event.get("enabled") is False else ""
        rows.append(f"""<div class="day-event-row">
  <span class="cal-event {event['kind']}{disabled}"{style}>{escape(event['name'])}</span>
  <span class="day-event-meta">{escape(event['time'])} &middot; {label}</span>
  <button class="btn-icon btn-icon-xs" hx-get="{_event_url(event)}" hx-target="#modal-area" hx-swap="innerHTML" title="Edit" aria-label="Edit">{icon("pencil", 14)}</button>
</div>""")

    body = "".join(rows) or '<p class="empty">No alerts on this day.</p>'
    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{day.strftime('%A, %B %-d')}</h3>
      <button type="button" class="btn-icon" onclick="closeModal()" aria-label="Close">{icon("x", 16)}</button>
    </div>
    <div class="day-list">{body}</div>
    <div class="modal-actions" style="justify-content:space-between">
      <button type="button" class="btn" onclick="closeModal()">Close</button>
      <button class="btn btn-primary" hx-get="/calendar/new?date={day.isoformat()}" hx-target="#modal-area" hx-swap="innerHTML">{icon("plus", 14)} Add alert</button>
    </div>
  </div>
</div>"""


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_fragment(
    request: Request,
    month: str = "",
    show_weekly: str = "",
    show_past: str = "",
):
    try:
        month_date = datetime.strptime(month, "%Y-%m").date()
    except (TypeError, ValueError):
        month_date = current_month()

    if show_weekly in ("0", "1"):
        weekly = show_weekly == "1"
    else:
        weekly = request.cookies.get("dns_show_weekly", "1") != "0"

    if show_past in ("0", "1"):
        past = show_past == "1"
    else:
        past = request.cookies.get("dns_show_past", "0") == "1"

    return render_month(
        month_date,
        read_json("webhooks"),
        read_json("alarms"),
        read_json("calendar"),
        show_weekly=weekly,
        show_past=past,
    )


@router.get("/calendar/day", response_class=HTMLResponse)
async def calendar_day_modal(
    request: Request,
    date: str = "",
    show_weekly: str = "",
    show_past: str = "",
):
    try:
        day = dt_date.fromisoformat(date)
    except (TypeError, ValueError):
        day = datetime.now(DISPLAY_TZ).date()

    if show_weekly in ("0", "1"):
        weekly = show_weekly == "1"
    else:
        weekly = request.cookies.get("dns_show_weekly", "1") != "0"

    if show_past in ("0", "1"):
        past = show_past == "1"
    else:
        past = request.cookies.get("dns_show_past", "0") == "1"

    return render_day_modal(
        day,
        read_json("webhooks"),
        read_json("alarms"),
        read_json("calendar"),
        show_weekly=weekly,
        show_past=past,
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
    color: Annotated[str, Form()] = "#3FB950",
):
    try:
        alert = _build_alert(
            name, webhook_name, message, message_type,
            date, time, timezone, repeat, embed_title,
            color=color,
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
    color: Annotated[str, Form()] = "#3FB950",
):
    rows = read_json("calendar")
    idx = next((i for i, row in enumerate(rows) if row["id"] == alert_id), None)
    if idx is None:
        return HTMLResponse("", status_code=404, headers=_toast("Alert not found", "err"))

    try:
        alert = _build_alert(
            name, webhook_name, message, message_type,
            date, time, timezone, repeat, embed_title,
            color=color,
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
    state = "enabled" if row["enabled"] else "disabled"

    if row["enabled"]:
        try:
            alert = CalendarAlert(**row)
            next_fire = compute_next_fire(
                dt_date.fromisoformat(alert.date),
                dt_time.fromisoformat(alert.time),
                alert.timezone,
                alert.repeat,
                after_utc=_now(),
            )
        except Exception:
            next_fire = None
        row["next_fire"] = next_fire
        if next_fire is None:
            row["enabled"] = False
            state = "has no future occurrence"

    write_json("calendar", rows)
    return HTMLResponse(
        "",
        headers={**_toast(f'Alert "{row.get("name", "")}" {state}'), "HX-Trigger": "refresh-lists"},
    )


@router.post("/calendar/{alert_id}/test", response_class=HTMLResponse)
async def test_calendar_alert(alert_id: str, request: Request):
    rows = read_json("calendar")
    row = next((r for r in rows if r["id"] == alert_id), None)
    if row is None:
        return HTMLResponse("", status_code=404, headers=_toast("Alert not found", "err"))

    form = await request.form()
    try:
        if "name" in form:
            alert = _build_alert(
                str(form.get("name") or ""),
                str(form.get("webhook_name") or ""),
                str(form.get("message") or ""),
                str(form.get("message_type") or "text"),
                str(form.get("date") or ""),
                str(form.get("time") or ""),
                str(form.get("timezone") or "UTC"),
                str(form.get("repeat") or "none"),
                str(form.get("embed_title") or ""),
                color=str(form.get("color") or row.get("color") or "#3FB950"),
                existing=row,
                for_test=True,
            )
        else:
            alert = CalendarAlert(**row)
    except Exception as exc:
        return HTMLResponse("", status_code=400, headers=_toast(_error_text(exc), "err"))

    success, err = await deliver(alert, "test", alert.id)

    latest = read_json("calendar")
    idx = next((i for i, r in enumerate(latest) if r["id"] == alert_id), None)
    if idx is not None:
        if success:
            latest[idx]["last_fired"] = _now().isoformat()
            latest[idx]["last_error"] = None
        else:
            latest[idx]["last_error"] = err
        write_json("calendar", latest)

    if success:
        return HTMLResponse(
            "",
            headers={**_toast("Test message sent"), "HX-Trigger": "refresh-lists"},
        )

    return HTMLResponse(
        "",
        headers={**_toast(f"Test failed: {err}", "err"), "HX-Trigger": "refresh-lists"},
    )
