import re
from contextlib import asynccontextmanager
from typing import Annotated

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from zoneinfo import ZoneInfo

from app.models import Alarm, DAYS_OF_WEEK, TIMEZONES, Webhook
from app.storage import read_json, write_json
from app.scheduler import start as start_scheduler, stop as stop_scheduler
from app.discord import send_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(lifespan=lifespan)

templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _to_12h(time_24: str) -> str:
    try:
        h, m = time_24.split(":")
        h = int(h)
        period = "AM" if h < 12 else "PM"
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        return f"{h12}:{m} {period}"
    except (ValueError, AttributeError):
        return time_24


def _alarm_card_html(alarm: dict, webhooks: list[dict]) -> str:
    from datetime import datetime

    hook = next((w for w in webhooks if w["name"] == alarm["webhook_name"]), None)
    hook_label = hook["name"] if hook else f"<em>{alarm['webhook_name']}</em>"

    days_str = ", ".join(d[:3] for d in alarm["days"]) if alarm["days"] else "All"
    if days_str == "Mon, Tue, Wed, Thu, Fri, Sat, Sun":
        days_str = "Every day"
    elif days_str == "Mon, Tue, Wed, Thu, Fri":
        days_str = "Weekdays"
    elif days_str == "Sat, Sun":
        days_str = "Weekends"

    enabled = alarm["enabled"]
    time_12h = _to_12h(alarm["time"])

    badge = ""
    if alarm.get("last_fired"):
        try:
            t = datetime.fromisoformat(alarm["last_fired"])
            tz_name = alarm.get("timezone", "UTC")
            try:
                tz = ZoneInfo(tz_name)
                t_local = t.astimezone(tz)
            except (KeyError, ValueError):
                t_local = t
            ts = t_local.strftime("%b %-d, %-I:%M %p")
            badge = f'<span class="badge badge-ok" title="Last sent {ts}">Sent {ts}</span>'
        except Exception:
            pass
    if alarm.get("last_error"):
        badge += f'<span class="badge badge-err" title="{alarm["last_error"]}">Failed</span>'

    toggle_url = f'/alarms/{alarm["id"]}/toggle'
    delete_url = f'/alarms/{alarm["id"]}'
    edit_url = f'/alarms/{alarm["id"]}'
    test_url = f'/alarms/{alarm["id"]}/test'

    return f"""<div class="alarm-card" id="alarm-{alarm["id"]}">
  <div class="alarm-main">
    <div class="alarm-info">
      <strong>{alarm["name"]}</strong>
      <span class="alarm-meta">&#x1f4e2; {hook_label} &middot; &#x1f552; {time_12h} &middot; {days_str}</span>
    </div>
    <div class="alarm-badges">{badge}</div>
    <div class="alarm-actions">
      <label class="toggle">
        <input type="checkbox" hx-post="{toggle_url}" hx-target="#alarm-{alarm["id"]}" hx-swap="outerHTML" {"checked" if enabled else ""}>
        <span class="slider"></span>
      </label>
      <button class="btn-icon" hx-get="{edit_url}" hx-target="#modal-area" hx-swap="innerHTML" title="Edit">&#x270e;</button>
      <button class="btn-icon btn-icon-danger" hx-delete="{delete_url}" hx-target="#alarm-{alarm["id"]}" hx-swap="outerHTML" hx-confirm="Delete this alarm?" title="Delete">&#x2716;</button>
      <button class="btn-test" hx-post="{test_url}" hx-target="#toast-area" hx-swap="beforeend" title="Send test">&#x25b6; Test</button>
    </div>
  </div>
</div>"""


def _safe_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\-_]", "-", name)


def _webhook_chip_html(wh: dict) -> str:
    name = wh["name"]
    safe = _safe_id(name)
    delete_url = f'/webhooks/{name}'
    test_url = f'/webhooks/{name}/test'
    return f"""<div class="webhook-chip" id="wh-{safe}">
  <span class="wh-name">{name}</span>
  <button class="btn-icon btn-icon-danger btn-icon-xs" hx-delete="{delete_url}" hx-target="#wh-{safe}" hx-swap="outerHTML" hx-confirm="Delete webhook '{name}'?" title="Delete">&times;</button>
  <button class="btn-icon btn-icon-xs" hx-post="{test_url}" hx-target="#toast-area" hx-swap="beforeend" title="Test webhook">&#x25b6;</button>
</div>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    webhooks = read_json("webhooks")
    alarms = read_json("alarms")
    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "webhooks": webhooks,
        "alarms": alarms,
        "timezones": TIMEZONES,
        "days": DAYS_OF_WEEK,
        "_alarm_card": _alarm_card_html,
        "_webhook_chip": _webhook_chip_html,
    })


WEBHOOK_FORM = """<form id="wh-form" hx-post="/webhooks" hx-target="#webhook-list" hx-swap="innerHTML">
  <input type="text" name="name" placeholder="Name" required>
  <input type="url" name="url" placeholder="https://discord.com/api/webhooks/..." required>
  <button type="submit" class="btn btn-primary btn-sm">Save</button>
  <button type="button" class="btn btn-sm" onclick="document.getElementById('wh-form-area').innerHTML=''">Cancel</button>
</form>"""


@app.get("/webhooks/new", response_class=HTMLResponse)
async def new_webhook_form():
    return WEBHOOK_FORM


@app.get("/webhooks", response_class=HTMLResponse)
async def list_webhooks():
    webhooks = read_json("webhooks")
    parts = [_webhook_chip_html(w) for w in webhooks]
    return "".join(parts) or '<span class="empty">No webhooks yet</span>'


@app.post("/webhooks", response_class=HTMLResponse)
async def create_webhook(name: Annotated[str, Form()], url: Annotated[str, Form()]):
    try:
        wh = Webhook(name=name.strip(), url=url.strip())
    except Exception as e:
        error = str(e)
        if "url" in str(e).lower():
            error = "Must be a valid Discord webhook URL"
        return f"""{await list_webhooks()}
<div id="toast-area" hx-swap-oob="beforeend" class="toast toast-err">{error}</div>"""

    webhooks = read_json("webhooks")
    if any(w["name"] == wh.name for w in webhooks):
        return f"""{await list_webhooks()}
<div id="toast-area" hx-swap-oob="beforeend" class="toast toast-err">Webhook "{wh.name}" already exists</div>"""

    webhooks.append(wh.model_dump())
    write_json("webhooks", webhooks)

    return f"""{await list_webhooks()}
<div id="toast-area" hx-swap-oob="beforeend" class="toast toast-ok">Webhook added</div>
<div id="wh-form-area" hx-swap-oob="true"></div>"""


@app.delete("/webhooks/{name}", response_class=HTMLResponse)
async def delete_webhook(name: str):
    webhooks = read_json("webhooks")
    webhooks = [w for w in webhooks if w["name"] != name]
    write_json("webhooks", webhooks)
    # Also remove any alarms using this webhook
    alarms = read_json("alarms")
    changed = False
    for a in alarms:
        if a["webhook_name"] == name:
            a["webhook_name"] = "(deleted)"
            changed = True
    if changed:
        write_json("alarms", alarms)
    return ""


@app.post("/webhooks/{name}/test", response_class=HTMLResponse)
async def test_webhook(name: str):
    webhooks = read_json("webhooks")
    wh = next((w for w in webhooks if w["name"] == name), None)
    if not wh:
        return f'<div class="toast toast-err">Webhook "{name}" not found</div>'

    # Build a quick test alarm object and send
    test_alarm = Alarm(
        name="Test",
        webhook_name=name,
        message="Test message from Discord Notification Scheduler :wave:",
        time="00:00",
        days=[],
    )
    success, err = await send_webhook(test_alarm)
    if success:
        return f'<div class="toast toast-ok">Test sent to "{name}"</div>'
    return f'<div class="toast toast-err">Test failed: {err}</div>'


@app.get("/alarms", response_class=HTMLResponse)
async def list_alarms():
    webhooks = read_json("webhooks")
    alarms = read_json("alarms")
    parts = [_alarm_card_html(a, webhooks) for a in alarms]
    return "".join(parts) or '<span class="empty">No alarms yet</span>'


def _form_html(alarm: dict | None = None) -> str:
    webhooks = read_json("webhooks")
    wh_options = "".join(
        f'<option value="{w["name"]}"{" selected" if alarm and alarm["webhook_name"]==w["name"] else ""}>{w["name"]}</option>'
        for w in webhooks
    )
    tz_list = "".join(
        f'<option value="{tz}">' for tz in TIMEZONES
    )
    tz_val = alarm["timezone"] if alarm else "UTC"
    day_checks = "".join(
        f"""<label class="day-check"><input type="checkbox" name="days" value="{d}"{" checked" if not alarm or d in alarm["days"] else ""}>{d[:3]}</label>"""
        for d in DAYS_OF_WEEK
    )

    is_edit = alarm is not None
    action = f'/alarms/{alarm["id"]}' if is_edit else "/alarms"
    method = "hx-put" if is_edit else "hx-post"
    title = "Edit Alarm" if is_edit else "New Alarm"
    name_val = alarm["name"] if alarm else ""
    msg_val = alarm["message"] if alarm else ""
    time_val = alarm["time"] if alarm else "09:00"
    msg_type = alarm["message_type"] if alarm else "text"
    embed_title = (alarm["embed"] or {}).get("title", "") if alarm else ""
    embed_color = (alarm["embed"] or {}).get("color", "#5865F2") if alarm else "#5865F2"

    text_checked = 'checked' if msg_type == 'text' else ''
    embed_checked = 'checked' if msg_type == 'embed' else ''
    embed_visible = '' if msg_type == 'embed' else 'style="display:none"'

    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{title}</h3>
      <button class="btn-icon" onclick="closeModal()">&times;</button>
    </div>
    <form {method}="{action}" hx-target="#alarm-list" hx-swap="innerHTML">
      <input type="hidden" name="id" value="{alarm["id"] if alarm else ""}">

      <label>Name</label>
      <input type="text" name="name" value="{name_val}" required maxlength="100">

      <label>Webhook</label>
      <select name="webhook_name" required>
        <option value="">-- Select --</option>
        {wh_options}
      </select>

      <label>Message <span class="hint">(Discord markdown supported)</span></label>
      <textarea name="message" rows="4" required maxlength="2000">{msg_val}</textarea>
      <div id="preview-area" class="preview-box"></div>

      <div class="msg-type-row">
        <label class="radio-label"><input type="radio" name="message_type" value="text" {text_checked} onchange="toggleEmbed(this)"> Plain text</label>
        <label class="radio-label"><input type="radio" name="message_type" value="embed" {embed_checked} onchange="toggleEmbed(this)"> Rich embed</label>
      </div>

      <div id="embed-fields" class="embed-fields" {embed_visible}>
        <label>Embed title (optional)</label>
        <input type="text" name="embed_title" value="{embed_title}" maxlength="256">

        <label>Embed color</label>
        <div class="color-row">
          <input type="color" name="embed_color" value="{embed_color}">
          <input type="text" class="color-text" value="{embed_color}" maxlength="7" oninput="this.previousElementSibling.value=this.value">
        </div>
      </div>

      <label>Time</label>
      <input type="time" name="time" value="{time_val}" required>

      <label>Days of week</label>
      <div class="days-row">{day_checks}</div>

      <label>Timezone</label>
      <input type="text" name="timezone" list="tz-list" value="{tz_val}" required>
      <datalist id="tz-list">{tz_list}</datalist>

      <div class="modal-actions">
        <button type="button" class="btn" onclick="closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary">Save</button>
      </div>
    </form>
  </div>
</div>"""


@app.get("/alarms/new", response_class=HTMLResponse)
async def new_alarm_form():
    return _form_html()


@app.get("/alarms/{alarm_id}", response_class=HTMLResponse)
async def edit_alarm_form(alarm_id: str):
    alarms = read_json("alarms")
    alarm = next((a for a in alarms if a["id"] == alarm_id), None)
    if not alarm:
        return '<div id="modal-area"></div>'
    return _form_html(alarm)


@app.post("/alarms", response_class=HTMLResponse)
async def create_alarm(
    name: Annotated[str, Form()],
    webhook_name: Annotated[str, Form()],
    message: Annotated[str, Form()],
    message_type: Annotated[str, Form()],
    time: Annotated[str, Form()],
    timezone: Annotated[str, Form()],
    days: Annotated[list[str], Form()] = [],
    embed_title: Annotated[str, Form()] = "",
    embed_color: Annotated[str, Form()] = "",
):
    try:
        embed = None
        if message_type == "embed":
            embed = {"title": embed_title or None, "color": embed_color or None}
        alarm = Alarm(
            name=name.strip(),
            webhook_name=webhook_name.strip(),
            message=message.strip(),
            message_type=message_type,
            time=time,
            timezone=timezone,
            days=days or list(DAYS_OF_WEEK),
            embed=embed,
        )
    except Exception as e:
        return f'<div class="toast toast-err">{str(e)}</div>'

    alarms = read_json("alarms")
    alarms.append(alarm.model_dump())
    write_json("alarms", alarms)

    webhooks = read_json("webhooks")
    parts = [_alarm_card_html(a, webhooks) for a in alarms]
    return f"""{''.join(parts)}
<div id="modal-area" hx-swap-oob="true"></div>"""


@app.put("/alarms/{alarm_id}", response_class=HTMLResponse)
async def update_alarm(
    alarm_id: str,
    name: Annotated[str, Form()],
    webhook_name: Annotated[str, Form()],
    message: Annotated[str, Form()],
    message_type: Annotated[str, Form()],
    time: Annotated[str, Form()],
    timezone: Annotated[str, Form()],
    days: Annotated[list[str], Form()] = [],
    embed_title: Annotated[str, Form()] = "",
    embed_color: Annotated[str, Form()] = "",
):
    alarms = read_json("alarms")
    idx = next((i for i, a in enumerate(alarms) if a["id"] == alarm_id), None)
    if idx is None:
        return '<div class="toast toast-err">Alarm not found</div>'

    try:
        embed = None
        if message_type == "embed":
            embed = {"title": embed_title or None, "color": embed_color or None}
        alarm = Alarm(
            id=alarm_id,
            name=name.strip(),
            webhook_name=webhook_name.strip(),
            message=message.strip(),
            message_type=message_type,
            time=time,
            timezone=timezone,
            days=days or list(DAYS_OF_WEEK),
            embed=embed,
            enabled=alarms[idx].get("enabled", True),
            last_fired=alarms[idx].get("last_fired"),
            last_error=alarms[idx].get("last_error"),
        )
    except Exception as e:
        return f'<div class="toast toast-err">{str(e)}</div>'

    alarms[idx] = alarm.model_dump()
    write_json("alarms", alarms)

    webhooks = read_json("webhooks")
    parts = [_alarm_card_html(a, webhooks) for a in alarms]
    return f"""{''.join(parts)}
<div id="modal-area" hx-swap-oob="true"></div>"""


@app.delete("/alarms/{alarm_id}", response_class=HTMLResponse)
async def delete_alarm(alarm_id: str):
    alarms = read_json("alarms")
    alarms = [a for a in alarms if a["id"] != alarm_id]
    write_json("alarms", alarms)
    return ""


@app.post("/alarms/{alarm_id}/toggle", response_class=HTMLResponse)
async def toggle_alarm(alarm_id: str):
    alarms = read_json("alarms")
    alarm = next((a for a in alarms if a["id"] == alarm_id), None)
    if not alarm:
        return ""
    alarm["enabled"] = not alarm.get("enabled", True)
    write_json("alarms", alarms)
    webhooks = read_json("webhooks")
    return _alarm_card_html(alarm, webhooks)


@app.post("/alarms/{alarm_id}/test", response_class=HTMLResponse)
async def test_alarm(alarm_id: str):
    alarms = read_json("alarms")
    raw = next((a for a in alarms if a["id"] == alarm_id), None)
    if not raw:
        return '<div class="toast toast-err">Alarm not found</div>'

    try:
        alarm = Alarm(**raw)
    except Exception as e:
        return f'<div class="toast toast-err">Invalid alarm data: {e}</div>'

    success, err = await send_webhook(alarm)
    if success:
        return '<div class="toast toast-ok">Test message sent!</div>'
    return f'<div class="toast toast-err">Test failed: {err}</div>'
