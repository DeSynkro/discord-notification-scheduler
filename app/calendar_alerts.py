from datetime import date as dt_date
from datetime import datetime
from datetime import time as dt_time
from datetime import timezone as dt_timezone
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from app.discord import deliver
from app.models import TIMEZONES, CalendarAlert
from app.recurrence import compute_next_fire
from app.render import escape, message_fields, timezone_input, webhook_options
from app.storage import read_json, write_json

router = APIRouter()

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
        headers={**_toast(f'Alert "{alert.name}" created'), "HX-Trigger": "refresh-lists"},
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
        headers={**_toast(f'Alert "{alert.name}" saved'), "HX-Trigger": "refresh-lists"},
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
        headers={**_toast("Alert deleted"), "HX-Trigger": "refresh-lists"},
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
