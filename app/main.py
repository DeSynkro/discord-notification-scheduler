import hashlib
import json
import os
import re
from datetime import date as dt_date, datetime, time as dt_time
from contextlib import asynccontextmanager
from typing import Annotated

from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, Request, UploadFile
from app.responses import SafeHTMLResponse as HTMLResponse, SafeResponse as Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from zoneinfo import ZoneInfo

from app.models import Alarm, CalendarAlert, DAYS_OF_WEEK, TIMEZONES, Webhook
from app.storage import StorageError, read_json, write_json
from app.recurrence import compute_next_fire
from app.render import channel_label, escape, message_fields, render_log, timezone_input, webhook_options
from app.icons import icon
from app.calendar_alerts import DISPLAY_TZ, current_month, render_month, router as calendar_router
from app.colors import effective_color
from app.notification_log import clear_log
from app.next_up import board_data, render_next_up, time_ago
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


@app.exception_handler(StorageError)
async def storage_error_handler(request: Request, exc: StorageError):
    return Response(
        "",
        status_code=500,
        headers={
            "X-Toast-Message": "Could not save data. The data folder is not writable.",
            "X-Toast-Type": "err",
        },
    )


@app.middleware("http")
async def check_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        origin = request.headers.get("origin")
        if origin and not _origin_matches(
            origin,
            request.headers.get("host", ""),
            request.url.scheme,
        ):
            return Response("Forbidden", status_code=403)
    return await call_next(request)


def _origin_matches(origin: str, host: str, scheme: str) -> bool:
    origin_url = urlparse(origin)
    host_url = urlparse(f"//{host}")
    default_port = 443 if scheme == "https" else 80
    origin_port = origin_url.port or (443 if origin_url.scheme == "https" else 80)
    host_port = host_url.port or default_port
    origin_host = (origin_url.hostname or "").rstrip(".").lower()
    host_host = (host_url.hostname or "").rstrip(".").lower()
    return origin_host == host_host and origin_port == host_port

templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
STYLE_VERSION = hashlib.sha1((static_dir / "style.css").read_bytes()).hexdigest()[:10]


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
    hook_label = channel_label(alarm["webhook_name"], missing=not hook)

    days_str = ", ".join(d[:3] for d in alarm["days"]) if alarm["days"] else "All"
    if days_str == "Mon, Tue, Wed, Thu, Fri, Sat, Sun":
        days_str = "Every day"
    elif days_str == "Mon, Tue, Wed, Thu, Fri":
        days_str = "Weekdays"
    elif days_str == "Sat, Sun":
        days_str = "Weekends"

    enabled = alarm["enabled"]
    time_12h = _to_12h(alarm["time"])
    try:
        clock, period = time_12h.rsplit(" ", 1)
    except ValueError:
        clock, period = time_12h, ""
    tz_label = escape(alarm.get("timezone", "UTC"))
    msg_type_label = "Rich embed" if alarm.get("message_type") == "embed" else "Plain text"

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
            ago = time_ago(alarm["last_fired"])
            label = f"Sent {ago}" if ago else "Sent"
            badge = f'<span class="badge badge-ok" title="Last sent {ts}"><span class="dot"></span>{label}</span>'
        except Exception:
            pass
    if alarm.get("last_error"):
        badge += f'<span class="badge badge-err" title="{escape(alarm["last_error"])}"><span class="dot"></span>Failed</span>'
    if not enabled:
        badge += '<span class="badge badge-off"><span class="dot"></span>Paused</span>'

    alarm_id = escape(alarm["id"])
    toggle_url = f'/alarms/{alarm_id}/toggle'
    delete_url = f'/alarms/{alarm_id}'
    edit_url = f'/alarms/{alarm_id}'
    test_url = f'/alarms/{alarm_id}/test'
    card_cls = "alarm-card" if enabled else "alarm-card is-off"

    return f"""<div class="{card_cls}" id="alarm-{alarm_id}">
  <div class="alarm-main">
    <div class="alarm-time">{clock}<span class="alarm-period">{period}</span></div>
    <div class="alarm-info">
      <strong>{escape(alarm["name"])}</strong>
      <span class="alarm-meta">{hook_label}<span class="sep">/</span>{days_str}<span class="sep">/</span>{tz_label}<span class="sep">/</span>{msg_type_label}</span>
    </div>
    <div class="alarm-badges">{badge}</div>
    <div class="alarm-actions">
      <label class="toggle" title="{"Pause" if enabled else "Resume"} alarm">
        <input type="checkbox" hx-post="{toggle_url}" hx-target="#alarm-{alarm_id}" hx-swap="outerHTML" {"checked" if enabled else ""} aria-label="{"Pause" if enabled else "Resume"} alarm">
        <span class="slider"></span>
      </label>
      <button class="btn-icon" hx-get="{edit_url}" hx-target="#modal-area" hx-swap="innerHTML" title="Edit" aria-label="Edit">{icon("pencil", 15)}</button>
      <button class="btn-icon btn-icon-danger" hx-delete="{delete_url}" hx-target="#alarm-{alarm_id}" hx-swap="outerHTML" hx-confirm="Delete this alarm?" title="Delete" aria-label="Delete">{icon("trash", 15)}</button>
      <button class="btn-test" hx-post="{test_url}" hx-target="#alarm-{alarm_id}" hx-swap="outerHTML" title="Send test" aria-label="Send test">{icon("play", 12)} Test</button>
    </div>
  </div>
</div>"""


def _safe_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\-_]", "-", name)


def _webhook_modal_form(wh: dict | None = None) -> str:
    is_edit = wh is not None
    action = f'/webhooks/{escape(wh["name"])}' if is_edit else '/webhooks'
    method = 'hx-put' if is_edit else 'hx-post'
    title = 'Edit webhook' if is_edit else 'New webhook'
    name_val = escape(wh["name"]) if wh else ""
    url_val = escape(wh["url"]) if wh else ""

    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{title}</h3>
      <button type="button" class="btn-icon" onclick="closeModal()" aria-label="Close">{icon("x", 16)}</button>
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
    esc_name = escape(name)
    delete_url = f'/webhooks/{esc_name}'
    test_url = f'/webhooks/{esc_name}/test'
    edit_url = f'/webhooks/{esc_name}/edit'
    return f"""<div class="webhook-chip">
  <span class="wh-name"><span class="hash">#</span>{esc_name}</span>
  <div class="wh-actions">
    <button class="btn-icon" hx-get="{edit_url}" hx-target="#modal-area" hx-swap="innerHTML" title="Edit" aria-label="Edit">{icon("pencil", 13)}</button>
    <button class="btn-icon btn-icon-danger" hx-delete="{delete_url}" hx-target="closest .webhook-chip" hx-swap="outerHTML" hx-confirm="Delete webhook '{esc_name}'?" title="Delete" aria-label="Delete">{icon("trash", 13)}</button>
    <button class="btn-icon" hx-post="{test_url}" hx-swap="none" title="Test webhook" aria-label="Test webhook">{icon("play", 12)}</button>
  </div>
</div>"""


@app.get("/webhooks/help", response_class=HTMLResponse)
async def webhook_help():
    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>Setting up a Discord webhook</h3>
      <button type="button" class="btn-icon" onclick="closeModal()" aria-label="Close">{icon("x", 16)}</button>
    </div>
    <ol style="margin:0;padding-left:1.2rem;line-height:1.8">
      <li>Open a server you manage (or have "Manage Webhooks" permission in)</li>
      <li>Go to <strong>Server Settings</strong> &gt; <strong>Integrations</strong> &gt; <strong>Webhooks</strong></li>
      <li>Click <strong>Create Webhook</strong></li>
      <li>Give it a name and select the channel where messages will appear</li>
      <li>Copy the webhook URL. It looks like:<br>
        <code style="font-size:0.8rem;word-break:break-all">https://discord.com/api/webhooks/123456789/abc-xyz...</code></li>
      <li>Return here, open <strong>Channels</strong> in the sidebar, and click <strong>Add</strong></li>
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
    calendar_alerts = read_json("calendar")
    payload = {
        "version": 2,
        "exported_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "webhooks": webhooks,
        "alarms": alarms,
        "calendar": calendar_alerts,
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="discord-scheduler-backup.json"'},
    )


IMPORT_FORM = f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>Import</h3>
      <button type="button" class="btn-icon" onclick="closeModal()" aria-label="Close">{icon("x", 16)}</button>
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

    if not isinstance(data["webhooks"], list) or not isinstance(data["alarms"], list):
        return Response("", status_code=400, headers={"X-Toast-Message": "'webhooks' and 'alarms' must be arrays", "X-Toast-Type": "err"})

    if "calendar" in data and not isinstance(data["calendar"], list):
        return Response("", status_code=400, headers={"X-Toast-Message": "'calendar' must be an array", "X-Toast-Type": "err"})

    imported_webhooks = []
    for item in data["webhooks"]:
        try:
            wh = Webhook(**item)
            imported_webhooks.append(wh.model_dump())
        except Exception:
            pass

    imported_alarms = []
    for item in data["alarms"]:
        try:
            alarm = Alarm(**item)
            imported_alarms.append(alarm.model_dump())
        except Exception:
            pass

    raw_calendar = data.get("calendar", [])
    if not isinstance(raw_calendar, list):
        raw_calendar = []
    imported_calendar = []
    now = datetime.now(ZoneInfo("UTC"))
    for item in raw_calendar:
        try:
            alert = CalendarAlert(**item)
            next_fire = compute_next_fire(
                dt_date.fromisoformat(alert.date),
                dt_time.fromisoformat(alert.time),
                alert.timezone,
                alert.repeat,
                after_utc=now,
            )
            alert.next_fire = next_fire
            if next_fire is None:
                alert.enabled = False
            imported_calendar.append(alert.model_dump())
        except Exception:
            pass

    if mode != "replace" and not imported_webhooks and not imported_alarms and not imported_calendar:
        return Response("", status_code=400, headers={"X-Toast-Message": "No valid webhooks, alarms, or calendar alerts found in file", "X-Toast-Type": "err"})

    total_wh = len(data["webhooks"])
    total_al = len(data["alarms"])
    total_cal = len(raw_calendar)
    valid_wh = len(imported_webhooks)
    valid_al = len(imported_alarms)
    valid_cal = len(imported_calendar)

    if mode == "replace":
        write_json("webhooks", imported_webhooks)
        write_json("alarms", imported_alarms)
        if "calendar" in data:
            write_json("calendar", imported_calendar)
        parts = []
        if total_wh != valid_wh:
            parts.append(f"{valid_wh}/{total_wh} webhooks (skipped {total_wh - valid_wh} invalid)")
        else:
            parts.append(f"{valid_wh} webhooks")
        if total_al != valid_al:
            parts.append(f"{valid_al}/{total_al} alarms (skipped {total_al - valid_al} invalid)")
        else:
            parts.append(f"{valid_al} alarms")
        if "calendar" not in data:
            parts.append("calendar left unchanged")
        elif total_cal != valid_cal:
            parts.append(f"{valid_cal}/{total_cal} calendar alerts (skipped {total_cal - valid_cal} invalid)")
        else:
            parts.append(f"{valid_cal} calendar alerts")
        msg = "Import complete: replaced " + ", ".join(parts)
    else:
        existing_wh = read_json("webhooks")
        existing_al = read_json("alarms")
        existing_cal = read_json("calendar")
        existing_wh_names = {w["name"] for w in existing_wh}
        existing_al_ids = {a["id"] for a in existing_al}
        existing_cal_ids = {a["id"] for a in existing_cal}

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

        cal_skipped = 0
        for alert in imported_calendar:
            if alert["id"] in existing_cal_ids:
                cal_skipped += 1
            else:
                existing_cal.append(alert)
                existing_cal_ids.add(alert["id"])

        write_json("webhooks", existing_wh)
        write_json("alarms", existing_al)
        write_json("calendar", existing_cal)

        parts = []
        wh_imported = valid_wh - wh_skipped
        al_imported = valid_al - al_skipped
        cal_imported = valid_cal - cal_skipped
        if wh_imported > 0:
            parts.append(f"{wh_imported} webhook(s)")
        if al_imported > 0:
            parts.append(f"{al_imported} alarm(s)")
        if cal_imported > 0:
            parts.append(f"{cal_imported} calendar alert(s)")
        if wh_skipped:
            parts.append(f"{wh_skipped} webhook(s) skipped (duplicate names)")
        if al_skipped:
            parts.append(f"{al_skipped} alarm(s) skipped (duplicate IDs)")
        if cal_skipped:
            parts.append(f"{cal_skipped} calendar alert(s) skipped (duplicate IDs)")
        if not parts:
            parts.append("nothing new")
        msg = "Import complete: merged " + ", ".join(parts)

    return Response("", headers={"X-Toast-Message": msg, "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    webhooks = read_json("webhooks")
    alarms = read_json("alarms")
    calendar_rows = read_json("calendar")
    for a in alarms:
        a.setdefault("created", "2000-01-01T00:00:00")
    alarms.sort(key=lambda a: a["time"])
    show_weekly = request.cookies.get("dns_show_weekly", "1") != "0"
    show_past = request.cookies.get("dns_show_past", "0") == "1"
    calendar_html = render_month(
        current_month(),
        webhooks,
        alarms,
        calendar_rows,
        show_weekly=show_weekly,
        show_past=show_past,
    )
    log_html = render_log()
    return templates.TemplateResponse(request, "index.html", {
        "request": request,
        "webhooks": webhooks,
        "alarms": alarms,
        "timezones": TIMEZONES,
        "days": DAYS_OF_WEEK,
        "calendar_html": calendar_html,
        "log_html": log_html,
        "next_up_html": render_next_up(webhooks, alarms, calendar_rows),
        "today_label": datetime.now(DISPLAY_TZ).strftime("%A, %B %-d"),
        "clock_label": datetime.now(DISPLAY_TZ).strftime("%-I:%M %p"),
        "style_version": STYLE_VERSION,
        "icon": icon,
        "_alarm_card": _alarm_card_html,
        "_webhook_chip": _webhook_chip_html,
    })


@app.get("/next-up", response_class=HTMLResponse)
async def next_up_fragment():
    return render_next_up(read_json("webhooks"), read_json("alarms"), read_json("calendar"))


@app.get("/next-up/data")
async def next_up_data():
    return board_data(read_json("webhooks"), read_json("alarms"), read_json("calendar"))


@app.get("/log", response_class=HTMLResponse)
async def log_fragment(page: int = 1):
    return render_log(page)


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

        calendar = read_json("calendar")
        changed_cal = False
        for alert in calendar:
            if alert.get("webhook_name") == old_name:
                alert["webhook_name"] = wh.name
                changed_cal = True
        if changed_cal:
            write_json("calendar", calendar)

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

    calendar = read_json("calendar")
    for alert in calendar:
        alert["webhook_name"] = "(deleted)"
    write_json("calendar", calendar)
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

    calendar = read_json("calendar")
    changed_cal = False
    for alert in calendar:
        if alert.get("webhook_name") == name:
            alert["webhook_name"] = "(deleted)"
            changed_cal = True
    if changed_cal:
        write_json("calendar", calendar)

    return Response("", headers={"X-Toast-Message": f'Webhook "{name}" deleted', "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


@app.post("/webhooks/{name}/test")
async def test_webhook(name: str):
    webhooks = read_json("webhooks")
    wh = next((w for w in webhooks if w["name"] == name), None)
    if not wh:
        return Response("", headers={"X-Toast-Message": f'Webhook "{name}" not found', "X-Toast-Type": "err"})

    test_alarm = Alarm(
        name=f"Test: {name}"[:100],
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
    response = "".join(parts) or (
        '<div class="empty-state">'
        f'<span class="empty-icon">{icon("bell", 20)}</span>'
        '<strong>No alarms scheduled</strong>'
        '<span>Create an alarm to send a message on a weekly schedule.</span>'
        '<button class="btn btn-primary" hx-get="/alarms/new" hx-target="#modal-area" hx-swap="innerHTML">'
        f'{icon("plus", 14)} New alarm</button>'
        '</div>'
    )
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
    title = "Edit alarm" if is_edit else "New alarm"
    name_val = escape(alarm["name"]) if alarm else ""
    msg_val = alarm["message"] if alarm else ""
    msg_len = len(msg_val)
    time_val = escape(alarm["time"]) if alarm else "09:00"
    msg_type = alarm["message_type"] if alarm else "text"
    embed = alarm["embed"] if alarm else None
    hidden_id = escape(alarm["id"]) if alarm else ""
    color_val = escape(effective_color(alarm) or "#8B9BFF")

    return f"""<div id="modal-overlay" class="modal-overlay" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>{title}</h3>
      <button type="button" class="btn-icon" onclick="closeModal()" aria-label="Close">{icon("x", 16)}</button>
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

      <label for="alarm-color">Alarm color<span class="hint"> used for the rail pin and embed</span></label>
      <div class="color-row">
        <input type="color" id="alarm-color" value="{color_val}" aria-label="Pick alarm color" oninput="this.nextElementSibling.value=this.value">
        <input type="text" name="color" class="color-text" id="alarm-color-hex" value="{color_val}" maxlength="7" required pattern="^#[0-9a-fA-F]{{6}}$" title="Hex color, e.g. #5865F2" aria-label="Alarm color hex" oninput="this.previousElementSibling.value=this.value">
      </div>

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
    color: Annotated[str, Form()] = "#8B9BFF",
):
    if not days:
        webhooks = read_json("webhooks")
        parts = [_alarm_card_html(a, webhooks) for a in read_json("alarms")]
        return HTMLResponse("".join(parts), status_code=400, headers={"X-Toast-Message": "Select at least one day", "X-Toast-Type": "err"})

    chosen_color = (color or "#8B9BFF").strip()
    try:
        embed = None
        if message_type == "embed":
            embed = {"title": embed_title or None, "color": chosen_color}
        alarm = Alarm(
            name=name.strip(),
            webhook_name=webhook_name.strip(),
            message=message.strip(),
            message_type=message_type,
            time=time,
            timezone=timezone,
            days=days or list(DAYS_OF_WEEK),
            embed=embed,
            color=chosen_color,
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
    return HTMLResponse(content, headers={"X-Toast-Message": f'Alarm "{alarm.name}" created', "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


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
    color: Annotated[str, Form()] = "",
):
    alarms = read_json("alarms")
    idx = next((i for i, a in enumerate(alarms) if a["id"] == alarm_id), None)
    if idx is None:
        parts = [_alarm_card_html(a, read_json("webhooks")) for a in alarms]
        return HTMLResponse("".join(parts), status_code=404, headers={"X-Toast-Message": "Alarm not found", "X-Toast-Type": "err"})

    if not days:
        webhooks = read_json("webhooks")
        parts = [_alarm_card_html(a, webhooks) for a in alarms]
        return HTMLResponse("".join(parts), status_code=400, headers={"X-Toast-Message": "Select at least one day", "X-Toast-Type": "err"})

    try:
        chosen_color = (color or effective_color(alarms[idx]) or "#8B9BFF").strip()
        embed = None
        if message_type == "embed":
            embed = {"title": embed_title or None, "color": chosen_color}
        alarm = Alarm(
            id=alarm_id,
            created=alarms[idx].get("created") or datetime.now(ZoneInfo("UTC")).isoformat(),
            name=name.strip(),
            webhook_name=webhook_name.strip(),
            message=message.strip(),
            message_type=message_type,
            time=time,
            timezone=timezone,
            days=days or list(DAYS_OF_WEEK),
            embed=embed,
            color=chosen_color,
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
    return HTMLResponse(content, headers={"X-Toast-Message": f'Alarm "{alarm.name}" saved', "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


@app.delete("/alarms", response_class=HTMLResponse)
async def delete_all_alarms():
    alarms = read_json("alarms")
    count = len(alarms)
    write_json("alarms", [])
    return Response("", headers={"X-Toast-Message": f"Deleted {count} alarm(s)", "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


@app.delete("/alarms/{alarm_id}", response_class=HTMLResponse)
async def delete_alarm(alarm_id: str):
    alarms = read_json("alarms")
    alarms = [a for a in alarms if a["id"] != alarm_id]
    write_json("alarms", alarms)
    return Response("", headers={"X-Toast-Message": "Alarm deleted", "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})


@app.post("/alarms/{alarm_id}/toggle", response_class=HTMLResponse)
async def toggle_alarm(alarm_id: str):
    alarms = read_json("alarms")
    alarm = next((a for a in alarms if a["id"] == alarm_id), None)
    if not alarm:
        return ""
    alarm["enabled"] = not alarm.get("enabled", True)
    write_json("alarms", alarms)
    webhooks = read_json("webhooks")
    card = _alarm_card_html(alarm, webhooks)
    return HTMLResponse(card, headers={"HX-Trigger": "alarm-toggled"})


def _update_alarm_fields(alarm_id: str, **fields) -> None:
    rows = read_json("alarms")
    for row in rows:
        if row.get("id") == alarm_id:
            row.update(fields)
            write_json("alarms", rows)
            return


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
        _update_alarm_fields(
            alarm.id,
            last_fired=datetime.now(ZoneInfo("UTC")).isoformat(),
            last_error=None,
        )
    else:
        _update_alarm_fields(alarm.id, last_error=err)

    alarms = read_json("alarms")
    raw = next((a for a in alarms if a["id"] == alarm_id), raw)
    webhooks = read_json("webhooks")
    card = _alarm_card_html(raw, webhooks)
    if success:
        return HTMLResponse(card, headers={"X-Toast-Message": "Test message sent", "X-Toast-Type": "ok", "HX-Trigger": "refresh-lists"})
    return HTMLResponse(card, headers={"X-Toast-Message": f"Test failed: {err}", "X-Toast-Type": "err", "HX-Trigger": "refresh-lists"})
