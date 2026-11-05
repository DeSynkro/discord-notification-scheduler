import json
import os
import re
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Annotated

from pathlib import Path

from fastapi import FastAPI, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from zoneinfo import ZoneInfo

from app.models import Alarm, DAYS_OF_WEEK, TIMEZONES, Webhook
from app.storage import read_json, write_json
from app.render import escape, message_fields, render_log, timezone_input, webhook_options
from app.calendar_alerts import current_month, render_month, router as calendar_router
from app.notification_log import clear_log
from app.scheduler import start as start_scheduler, stop as stop_scheduler
from app.discord import deliver


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = not os.environ.get("DISABLE_SCHEDULER")
    if started:
        start_scheduler()
    yield
    if started:
        stop_scheduler()


app = FastAPI(lifespan=lifespan)
app.include_router(calendar_router)

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
    hook = next((w for w in webhooks if w["name"] == alarm["webhook_name"]), None)
    hook_label = f'<em>{escape(alarm["webhook_name"])}</em>' if not hook else escape(hook["name"])

    days_str = ", ".join(d[:3] for d in alarm["days"]) if alarm["days"] else "All"
    if days_str == "Mon, Tue, Wed, Thu, Fri, Sat, Sun":
        days_str = "Every day"
    elif days_str == "Mon, Tue, Wed, Thu, Fri":
        days_str = "Weekdays"
    elif days_str == "Sat, Sun":
        days_str = "Weekends"

    enabled = alarm["enabled"]
    time_12h = _to_12h(alarm["time"])
    tz_label = escape(alarm.get("timezone", "UTC"))
    msg_type_label = "Rich Embed" if alarm.get("message_type") == "embed" else "Plain Text"

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
        badge += f'<span class="badge badge-err" title="{escape(alarm["last_error"])}">Failed</span>'

    alarm_id = escape(alarm["id"])
    toggle_url = f'/alarms/{alarm_id}/toggle'
    delete_url = f'/alarms/{alarm_id}'
    edit_url = f'/alarms/{alarm_id}'
    test_url = f'/alarms/{alarm_id}/test'

    return f"""<div class="alarm-card" id="alarm-{alarm_id}">
  <div class="alarm-main">
    <div class="alarm-info">
      <strong>{escape(alarm["name"])}</strong>
      <span class="alarm-meta">&#x1f4e2; {hook_label} &middot; &#x1f552; {time_12h} &middot; {days_str} &middot; &#x1f310; {tz_label} &middot; &#x1f4dd; {msg_type_label}</span>
    </div>
    <div class="alarm-badges">{badge}</div>
    <div class="alarm-actions">
      <label class="toggle">
        <input type="checkbox" hx-post="{toggle_url}" hx-target="#alarm-{alarm_id}" hx-swap="outerHTML" {"checked" if enabled else ""}>
        <span class="slider"></span>
      </label>
      <button class="btn-icon" hx-get="{edit_url}" hx-target="#modal-area" hx-swap="innerHTML" title="Edit">&#x270e;</button>
      <button class="btn-icon btn-icon-danger" hx-delete="{delete_url}" hx-target="#alarm-{alarm_id}" hx-swap="outerHTML" hx-confirm="Delete this alarm?" title="Delete">&#x2716;</button>
      <button class="btn-test" hx-post="{test_url}" hx-target="#alarm-{alarm_id}" hx-swap="outerHTML" title="Send test">&#x25b6; Test</button>
    </div>
  </div>
</div>"""


def _safe_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\-_]", "-", name)


def _webhook_modal_form(wh: dict | None = None) -> str:
    is_edit = wh is not None
    action = f'/webhooks/{escape(wh["name"])}' if is_edit else '/webhooks'
    method = 'hx-put' if is_edit else 'hx-post'
    title = 'Edit Webhook' if is_edit else 'New Webhook'
    name_val = escape(wh["name"]) if wh else ""
    url_val = escape(wh["url"]) if wh else ""

    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{title}</h3>
      <button class="btn-icon" onclick="closeModal()">&times;</button>
    </div>
    <form {method}="{action}" hx-target="#webhook-list" hx-swap="innerHTML">
      <label>Name</label>
      <input type="text" name="new_name" value="{name_val}" required maxlength="100">

      <label>Webhook URL</label>
      <input type="url" name="url" value="{url_val}" placeholder="https://discord.com/api/webhooks/..." required>

      <div class="modal-actions">
        <button type="button" class="btn" onclick="closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary">Save</button>
      </div>
    </form>
  </div>
</div>"""


def _webhook_chip_html(wh: dict) -> str:
    name = wh["name"]
    safe = _safe_id(name)
    esc_name = escape(name)
    delete_url = f'/webhooks/{esc_name}'
    test_url = f'/webhooks/{esc_name}/test'
    edit_url = f'/webhooks/{esc_name}/edit'
    return f"""<div class="webhook-chip" id="wh-{safe}">
  <span class="wh-name">{esc_name}</span>
  <button class="btn-icon btn-icon-xs" hx-get="{edit_url}" hx-target="#modal-area" hx-swap="innerHTML" title="Edit">&#x270e;</button>
  <button class="btn-icon btn-icon-danger btn-icon-xs" hx-delete="{delete_url}" hx-target="#wh-{safe}" hx-swap="outerHTML" hx-confirm="Delete webhook '{esc_name}'?" title="Delete">&times;</button>
  <button class="btn-icon btn-icon-xs" hx-post="{test_url}" hx-swap="none" title="Test webhook">&#x25b6;</button>
</div>"""


@app.get("/webhooks/help", response_class=HTMLResponse)
async def webhook_help():
    return """<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>Setting up a Discord Webhook</h3>
      <button class="btn-icon" onclick="closeModal()">&times;</button>
    </div>
    <ol style="margin:0;padding-left:1.2rem;line-height:1.8">
      <li>Open a server you manage (or have "Manage Webhooks" permission in)</li>
      <li>Go to <strong>Server Settings</strong> &gt; <strong>Integrations</strong> &gt; <strong>Webhooks</strong></li>
      <li>Click <strong>Create Webhook</strong></li>
      <li>Give it a name and select the channel where messages will appear</li>
      <li>Copy the webhook URL. It looks like:<br>
        <code style="font-size:0.8rem;word-break:break-all">https://discord.com/api/webhooks/123456789/abc-xyz...</code></li>
      <li>Return here, click <strong>+ Add</strong>, and paste the URL</li>
    </ol>
    <p style="margin-top:1rem;padding:0.6rem;background:rgba(248,81,73,0.1);border-radius:6px;font-size:0.85rem">
      Webhooks can only be created in servers, not in direct messages.
      You need "Manage Webhooks" permission on the server.
    </p>
    <div class="modal-actions">
      <button type="button" class="btn btn-primary" onclick="closeModal()">Got it</button>
    </div>
  </div>
</div>"""


@app.get("/export")
async def export_data():
    webhooks = read_json("webhooks")
    alarms = read_json("alarms")
    payload = {
        "version": 1,
        "exported_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "webhooks": webhooks,
        "alarms": alarms,
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="discord-scheduler-backup.json"'},
    )


IMPORT_FORM = """<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>Import</h3>
      <button class="btn-icon" onclick="closeModal()">&times;</button>
    </div>
    <form hx-encoding="multipart/form-data" hx-post="/import" hx-swap="none" id="import-form">
      <label>Backup file (.json)</label>
      <input type="file" name="file" accept=".json,application/json" required class="file-input">

      <label>Mode</label>
      <div class="import-mode-row">
        <label class="radio-label"><input type="radio" name="mode" value="merge" checked> Merge (add to existing data)</label>
        <label class="radio-label"><input type="radio" name="mode" value="replace"> Replace (clear all existing data)</label>
      </div>

      <div class="modal-actions">
        <button type="button" class="btn" onclick="closeModal()">Cancel</button>
        <button type="submit" class="btn btn-primary">Import</button>
      </div>
    </form>
  </div>
</div>"""


@app.get("/import/form", response_class=HTMLResponse)
async def import_form():
    return IMPORT_FORM


@app.post("/import")
async def import_data(file: UploadFile, mode: str = Form("merge")):
    try:
        raw = await file.read()
        data = json.loads(raw)
    except Exception:
        return Response("", status_code=400, headers={"X-Toast-Message": "Invalid JSON file", "X-Toast-Type": "err"})

    if not isinstance(data, dict) or "webhooks" not in data or "alarms" not in data:
        return Response("", status_code=400, headers={"X-Toast-Message": "Missing 'webhooks' or 'alarms' in file", "X-Toast-Type": "err"})

    imported_webhooks = []
    for i, item in enumerate(data["webhooks"]):
        try:
            wh = Webhook(**item)
            imported_webhooks.append(wh.model_dump())
        except Exception:
            pass

    imported_alarms = []
    for i, item in enumerate(data["alarms"]):
        try:
            alarm = Alarm(**item)
            imported_alarms.append(alarm.model_dump())
        except Exception:
            pass

    if not imported_webhooks and not imported_alarms:
        return Response("", status_code=400, headers={"X-Toast-Message": "No valid webhooks or alarms found in file", "X-Toast-Type": "err"})

    total_wh = len(data["webhooks"])
    total_al = len(data["alarms"])
    valid_wh = len(imported_webhooks)
    valid_al = len(imported_alarms)

    if mode == "replace":
        write_json("webhooks", imported_webhooks)
        write_json("alarms", imported_alarms)
        parts = []
        if total_wh != valid_wh:
            parts.append(f"{valid_wh}/{total_wh} webhooks (skipped {total_wh - valid_wh} invalid)")
        else:
            parts.append(f"{valid_wh} webhooks")
        if total_al != valid_al:
            parts.append(f"{valid_al}/{total_al} alarms (skipped {total_al - valid_al} invalid)")
        else:
            parts.append(f"{valid_al} alarms")
        msg = "Import complete: replaced " + ", ".join(parts)
    else:
        existing_wh = read_json("webhooks")
        existing_al = read_json("alarms")
        existing_wh_names = {w["name"] for w in existing_wh}
        existing_al_ids = {a["id"] for a in existing_al}

        wh_skipped = 0
        for wh in imported_webhooks:
            if wh["name"] in existing_wh_names:
                wh_skipped += 1
            else:
                existing_wh.append(wh)
                existing_wh_names.add(wh["name"])

        al_skipped = 0
        for alarm in imported_alarms:
            if alarm["id"] in existing_al_ids:
                al_skipped += 1
            else:
                existing_al.append(alarm)
                existing_al_ids.add(alarm["id"])

        write_json("webhooks", existing_wh)
        write_json("alarms", existing_al)

        parts = []
        wh_imported = valid_wh - wh_skipped
        al_imported = valid_al - al_skipped
        if wh_imported > 0:
            parts.append(f"{wh_imported} webhook(s)")
        if al_imported > 0:
            parts.append(f"{al_imported} alarm(s)")
        if wh_skipped:
            parts.append(f"{wh_skipped} webhook(s) skipped (duplicate names)")
        if al_skipped:
            parts.append(f"{al_skipped} alarm(s) skipped (duplicate IDs)")
        if not parts:
            parts.append("nothing new")
        msg = "Import complete: merged " + ", ".join(parts)

    return Response("", headers={"X-Toast-Message": msg, "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    webhooks = read_json("webhooks")
    alarms = read_json("alarms")
    for a in alarms:
        a.setdefault("created", "2000-01-01T00:00:00")
    alarms.sort(key=lambda a: a["time"])
    calendar_html = render_month(current_month(), webhooks, alarms, read_json("calendar"))
    log_html = render_log(50)
    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "webhooks": webhooks,
        "alarms": alarms,
        "timezones": TIMEZONES,
        "days": DAYS_OF_WEEK,
        "calendar_html": calendar_html,
        "log_html": log_html,
        "_alarm_card": _alarm_card_html,
        "_webhook_chip": _webhook_chip_html,
    })


@app.get("/log", response_class=HTMLResponse)
async def log_fragment():
    return render_log(50)


@app.delete("/log", response_class=HTMLResponse)
async def clear_log_route():
    clear_log()
    return HTMLResponse(
        "",
        headers={
            "X-Toast-Message": "Log cleared",
            "X-Toast-Type": "ok",
            "HX-Trigger": "refresh-lists",
        },
    )


@app.get("/webhooks", response_class=HTMLResponse)
async def list_webhooks():
    webhooks = read_json("webhooks")
    parts = [_webhook_chip_html(w) for w in webhooks]
    return "".join(parts) or '<span class="empty">No webhooks yet</span>'


@app.get("/webhooks/new", response_class=HTMLResponse)
async def new_webhook_form():
    return _webhook_modal_form()


@app.get("/webhooks/{name}/edit", response_class=HTMLResponse)
async def edit_webhook_form(name: str):
    webhooks = read_json("webhooks")
    wh = next((w for w in webhooks if w["name"] == name), None)
    if not wh:
        return '<div id="modal-area"></div>'
    return _webhook_modal_form(wh)


@app.post("/webhooks", response_class=HTMLResponse)
async def create_webhook(new_name: Annotated[str, Form()], url: Annotated[str, Form()]):
    try:
        wh = Webhook(name=new_name.strip(), url=url.strip())
    except Exception as e:
        error = str(e)
        if "url" in str(e).lower():
            error = "Must be a valid Discord webhook URL"
        return HTMLResponse(
            content=await list_webhooks(),
            status_code=400,
            headers={"X-Toast-Message": error, "X-Toast-Type": "err"},
        )

    webhooks = read_json("webhooks")
    if any(w["name"] == wh.name for w in webhooks):
        return HTMLResponse(
            content=await list_webhooks(),
            status_code=409,
            headers={"X-Toast-Message": f'Webhook "{wh.name}" already exists', "X-Toast-Type": "err"},
        )

    webhooks.append(wh.model_dump())
    write_json("webhooks", webhooks)

    parts = [_webhook_chip_html(w) for w in read_json("webhooks")]
    content = f"""{''.join(parts)}
<div id="modal-area" hx-swap-oob="innerHTML"></div>"""
    return HTMLResponse(content, headers={"X-Toast-Message": f'Webhook "{wh.name}" added', "X-Toast-Type": "ok"})


@app.put("/webhooks/{name}", response_class=HTMLResponse)
async def update_webhook(
    name: str,
    new_name: Annotated[str, Form()],
    url: Annotated[str, Form()],
):
    try:
        wh = Webhook(name=new_name.strip(), url=url.strip())
    except Exception as e:
        error = str(e)
        if "url" in str(e).lower():
            error = "Must be a valid Discord webhook URL"
        parts = [_webhook_chip_html(w) for w in read_json("webhooks")]
        return HTMLResponse("".join(parts), status_code=400, headers={"X-Toast-Message": error, "X-Toast-Type": "err"})

    webhooks = read_json("webhooks")
    idx = next((i for i, w in enumerate(webhooks) if w["name"] == name), None)
    if idx is None:
        parts = [_webhook_chip_html(w) for w in webhooks]
        return HTMLResponse("".join(parts), status_code=404, headers={"X-Toast-Message": f'Webhook "{name}" not found', "X-Toast-Type": "err"})

    if new_name.strip() != name and any(w["name"] == new_name.strip() for w in webhooks):
        parts = [_webhook_chip_html(w) for w in webhooks]
        return HTMLResponse("".join(parts), status_code=409, headers={"X-Toast-Message": f'Webhook "{new_name.strip()}" already exists', "X-Toast-Type": "err"})

    old_name = webhooks[idx]["name"]
    webhooks[idx] = wh.model_dump()
    write_json("webhooks", webhooks)

    if old_name != wh.name:
        alarms = read_json("alarms")
        for a in alarms:
            if a["webhook_name"] == old_name:
                a["webhook_name"] = wh.name
        write_json("alarms", alarms)

    parts = [_webhook_chip_html(w) for w in read_json("webhooks")]
    content = f"""{''.join(parts)}
<div id="modal-area" hx-swap-oob="innerHTML"></div>"""
    return HTMLResponse(content, headers={"X-Toast-Message": f'Webhook "{wh.name}" saved', "X-Toast-Type": "ok"})


@app.delete("/webhooks", response_class=HTMLResponse)
async def delete_all_webhooks():
    webhooks = read_json("webhooks")
    count = len(webhooks)
    write_json("webhooks", [])
    alarms = read_json("alarms")
    for a in alarms:
        a["webhook_name"] = "(deleted)"
    write_json("alarms", alarms)
    return Response("", headers={"X-Toast-Message": f"Deleted {count} webhook(s)", "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


@app.delete("/webhooks/{name}", response_class=HTMLResponse)
async def delete_webhook(name: str):
    webhooks = read_json("webhooks")
    webhooks = [w for w in webhooks if w["name"] != name]
    write_json("webhooks", webhooks)
    alarms = read_json("alarms")
    changed = False
    for a in alarms:
        if a["webhook_name"] == name:
            a["webhook_name"] = "(deleted)"
            changed = True
    if changed:
        write_json("alarms", alarms)
    return Response("", headers={"X-Toast-Message": f'Webhook "{name}" deleted', "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


@app.post("/webhooks/{name}/test")
async def test_webhook(name: str):
    webhooks = read_json("webhooks")
    wh = next((w for w in webhooks if w["name"] == name), None)
    if not wh:
        return Response("", headers={"X-Toast-Message": f'Webhook "{name}" not found', "X-Toast-Type": "err"})

    test_alarm = Alarm(
        name=f"Test: {name}",
        webhook_name=name,
        message=f"Test message from {name} via Discord Notification Scheduler :wave:",
        time="00:00",
        days=[],
    )
    success, err = await deliver(test_alarm, "test", None)
    if success:
        return Response("", headers={"X-Toast-Message": f'Test sent to "{name}"', "X-Toast-Type": "ok"})
    return Response("", headers={"X-Toast-Message": f"Test failed: {err}", "X-Toast-Type": "err"})


@app.get("/alarms", response_class=HTMLResponse)
async def list_alarms(sort: str = "time_asc"):
    webhooks = read_json("webhooks")
    alarms = read_json("alarms")
    for a in alarms:
        a.setdefault("created", "2000-01-01T00:00:00")
    if sort == "time_asc":
        alarms.sort(key=lambda a: a["time"])
    elif sort == "time_desc":
        alarms.sort(key=lambda a: a["time"], reverse=True)
    elif sort == "created":
        alarms.sort(key=lambda a: a["created"], reverse=True)
    elif sort == "created_asc":
        alarms.sort(key=lambda a: a["created"])
    elif sort == "name":
        alarms.sort(key=lambda a: a["name"].lower())
    elif sort == "name_desc":
        alarms.sort(key=lambda a: a["name"].lower(), reverse=True)
    parts = [_alarm_card_html(a, webhooks) for a in alarms]
    response = "".join(parts) or '<span class="empty">No alarms yet</span>'
    return HTMLResponse(response, headers={"X-Sort": sort})


def _form_html(alarm: dict | None = None) -> str:
    webhooks = read_json("webhooks")
    selected = alarm["webhook_name"] if alarm else ""
    wh_options = webhook_options(webhooks, selected)
    tz_val = alarm["timezone"] if alarm else "UTC"
    day_checks = "".join(
        f"""<label class="day-check"><input type="checkbox" name="days" value="{d}"{" checked" if not alarm or d in alarm["days"] else ""}>{d[:3]}</label>"""
        for d in DAYS_OF_WEEK
    )

    is_edit = alarm is not None
    action = f'/alarms/{escape(alarm["id"])}' if is_edit else "/alarms"
    method = "hx-put" if is_edit else "hx-post"
    title = "Edit Alarm" if is_edit else "New Alarm"
    name_val = escape(alarm["name"]) if alarm else ""
    msg_val = alarm["message"] if alarm else ""
    msg_len = len(msg_val)
    time_val = escape(alarm["time"]) if alarm else "09:00"
    msg_type = alarm["message_type"] if alarm else "text"
    embed = alarm["embed"] if alarm else None
    hidden_id = escape(alarm["id"]) if alarm else ""

    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{title}</h3>
      <button class="btn-icon" onclick="closeModal()">&times;</button>
    </div>
    <form {method}="{action}" hx-target="#alarm-list" hx-swap="innerHTML">
      <input type="hidden" name="id" value="{hidden_id}">

      <label>Name</label>
      <input type="text" name="name" value="{name_val}" required maxlength="100">

      <label>Webhook</label>
      <select name="webhook_name" required>
        <option value="">-- Select --</option>
        {wh_options}
      </select>

      {message_fields(msg_val, msg_type, embed, msg_len)}

      <label>Time</label>
      <input type="time" name="time" value="{time_val}" required>

      <label>Days of week</label>
      <div class="days-row">{day_checks}</div>

      {timezone_input(tz_val, TIMEZONES)}

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
        webhooks = read_json("webhooks")
        parts = [_alarm_card_html(a, webhooks) for a in read_json("alarms")]
        return HTMLResponse("".join(parts), status_code=400, headers={"X-Toast-Message": str(e), "X-Toast-Type": "err"})

    alarms = read_json("alarms")
    alarms.append(alarm.model_dump())
    write_json("alarms", alarms)

    webhooks = read_json("webhooks")
    parts = [_alarm_card_html(a, webhooks) for a in alarms]
    content = f"""{''.join(parts)}
<div id="modal-area" hx-swap-oob="innerHTML"></div>"""
    return HTMLResponse(content, headers={"X-Toast-Message": f'Alarm "{alarm.name}" created', "X-Toast-Type": "ok"})


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
        parts = [_alarm_card_html(a, read_json("webhooks")) for a in alarms]
        return HTMLResponse("".join(parts), status_code=404, headers={"X-Toast-Message": "Alarm not found", "X-Toast-Type": "err"})

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
        webhooks = read_json("webhooks")
        parts = [_alarm_card_html(a, webhooks) for a in alarms]
        return HTMLResponse("".join(parts), status_code=400, headers={"X-Toast-Message": str(e), "X-Toast-Type": "err"})

    alarms[idx] = alarm.model_dump()
    write_json("alarms", alarms)

    webhooks = read_json("webhooks")
    parts = [_alarm_card_html(a, webhooks) for a in alarms]
    content = f"""{''.join(parts)}
<div id="modal-area" hx-swap-oob="innerHTML"></div>"""
    return HTMLResponse(content, headers={"X-Toast-Message": f'Alarm "{alarm.name}" saved', "X-Toast-Type": "ok"})


@app.delete("/alarms", response_class=HTMLResponse)
async def delete_all_alarms():
    alarms = read_json("alarms")
    count = len(alarms)
    write_json("alarms", [])
    return Response("", headers={"X-Toast-Message": f"Deleted {count} alarm(s)", "X-Toast-Type": "ok"})


@app.delete("/alarms/{alarm_id}", response_class=HTMLResponse)
async def delete_alarm(alarm_id: str):
    alarms = read_json("alarms")
    alarms = [a for a in alarms if a["id"] != alarm_id]
    write_json("alarms", alarms)
    return Response("", headers={"X-Toast-Message": "Alarm deleted", "X-Toast-Type": "ok"})


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
        return HTMLResponse("", headers={"X-Toast-Message": "Alarm not found", "X-Toast-Type": "err"})

    try:
        alarm = Alarm(**raw)
    except Exception as e:
        return HTMLResponse("", headers={"X-Toast-Message": f"Invalid alarm data: {e}", "X-Toast-Type": "err"})

    success, err = await deliver(alarm, "test", alarm.id)
    if success:
        raw["last_fired"] = datetime.now(ZoneInfo("UTC")).isoformat()
        write_json("alarms", alarms)
    webhooks = read_json("webhooks")
    card = _alarm_card_html(raw, webhooks)
    if success:
        return HTMLResponse(card, headers={"X-Toast-Message": "Test message sent!", "X-Toast-Type": "ok"})
    return HTMLResponse(card, headers={"X-Toast-Message": f"Test failed: {err}", "X-Toast-Type": "err"})
