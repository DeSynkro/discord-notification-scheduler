import html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.icons import icon
from app.notification_log import read_log


def escape(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def header_text(value) -> str:
    text = " ".join(str(value).split())
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return (safe or "Something went wrong")[:300]


def channel_label(name: str, missing: bool = False) -> str:
    cls = "channel missing" if missing else "channel"
    return f'<span class="{cls}"><span class="hash">#</span>{escape(name)}</span>'


def webhook_options(webhooks: list[dict], selected: str = "") -> str:
    parts = []
    for webhook in webhooks:
        name = escape(webhook["name"])
        is_selected = " selected" if webhook["name"] == selected else ""
        parts.append(f'<option value="{name}"{is_selected}>{name}</option>')
    return "".join(parts)


def timezone_input(value: str = "UTC", timezones: list[str] | None = None) -> str:
    zones = timezones or []
    options = "".join(f'<option value="{escape(tz)}"></option>' for tz in zones)
    return f"""<label>Timezone</label>
      <input type="text" name="timezone" list="tz-list" value="{escape(value)}" required>
      <datalist id="tz-list">{options}</datalist>"""


def message_fields(
    message: str = "",
    message_type: str = "text",
    embed: dict | None = None,
    msg_len: int | None = None,
) -> str:
    embed = embed or {}
    title = escape(embed.get("title") or "")
    text_checked = "checked" if message_type == "text" else ""
    embed_checked = "checked" if message_type == "embed" else ""
    embed_visible = "" if message_type == "embed" else 'style="display:none"'
    length = len(message) if msg_len is None else msg_len

    return f"""<label>Message <span class="hint">(Discord markdown supported)</span></label>
      <textarea name="message" rows="4" required maxlength="2000">{escape(message)}</textarea>
      <div id="char-count" class="char-count">{length} / 2000</div>
      <div id="preview-area" class="preview-box"></div>

      <div class="msg-type-row">
        <label class="radio-label"><input type="radio" name="message_type" value="text" {text_checked} onchange="toggleEmbed(this)"> Plain text</label>
        <label class="radio-label"><input type="radio" name="message_type" value="embed" {embed_checked} onchange="toggleEmbed(this)"> Rich embed</label>
      </div>

      <div id="embed-fields" class="embed-fields" {embed_visible}>
        <label>Embed title (optional)</label>
        <input type="text" name="embed_title" value="{title}" maxlength="256">
      </div>"""


def _log_summary(rows: list[dict]) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    sent = failed = 0
    for row in rows:
        try:
            moment = datetime.fromisoformat(row.get("ts", ""))
        except (TypeError, ValueError):
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if moment < cutoff:
            continue
        if row.get("status") == "ok":
            sent += 1
        elif row.get("status") == "err":
            failed += 1

    if sent + failed == 0:
        return (
            '<div class="log-summary">'
            '<span class="log-summary-label">Last 24 hours</span>'
            '<span class="log-summary-quiet">No deliveries</span>'
            '</div>'
        )
    failed_cls = " is-err" if failed else ""
    return (
        '<div class="log-summary">'
        '<span class="log-summary-label">Last 24 hours</span>'
        f'<span class="log-stat"><strong>{sent}</strong> sent</span>'
        f'<span class="log-stat{failed_cls}"><strong>{failed}</strong> failed</span>'
        '</div>'
    )


def render_log(page: int = 1, page_size: int = 10) -> str:
    rows = read_log()
    total = len(rows)
    if total == 0:
        return (
            '<input type="hidden" id="log-page" name="page" value="1">'
            '<div class="empty-state">'
            f'<span class="empty-icon">{icon("log", 20)}</span>'
            '<strong>No deliveries yet</strong>'
            '<span>Send a test from an alarm or a webhook to see it here.</span>'
            '</div>'
        )

    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), pages)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]

    parts = []
    for row in page_rows:
        kind = row.get("kind", "")
        kind_label = {
            "weekly": "Weekly",
            "calendar": "Calendar",
            "test": "Test",
        }.get(kind, kind.title())
        ts_label = row.get("ts", "")
        try:
            moment = datetime.fromisoformat(ts_label)
            tz_name = row.get("timezone") or "UTC"
            moment = moment.astimezone(ZoneInfo(tz_name))
            ts_label = moment.strftime("%b %-d, %-I:%M %p")
        except Exception:
            pass

        status = row.get("status")
        badge = (
            '<span class="badge badge-ok"><span class="dot"></span>Sent</span>'
            if status == "ok"
            else '<span class="badge badge-err"><span class="dot"></span>Failed</span>'
        )
        meta = (
            f'<span class="log-kind {escape(kind)}">{escape(kind_label)}</span>'
            f'{channel_label(row.get("webhook_name", ""))}'
        )
        preview = row.get("preview", "")
        preview_html = (
            f'<span class="log-preview">{escape(preview)}</span>' if preview else ""
        )
        error_html = (
            f'<span class="log-error">{escape(row["error"])}</span>'
            if row.get("error") else ""
        )

        parts.append(f"""<div class="log-row">
  <span class="log-time">{escape(ts_label)}</span>
  <div class="log-main">
    <strong>{escape(row.get("name", ""))}</strong>
    <span class="log-meta">{meta}</span>
    {preview_html}
    {error_html}
  </div>
  {badge}
</div>""")

    pager = ""
    if pages > 1:
        prev_disabled = " disabled" if page <= 1 else ""
        next_disabled = " disabled" if page >= pages else ""
        pager = f"""<div class="log-pager">
  <button class="btn btn-sm" hx-get="/log?page={page - 1}" hx-target="#log-view" hx-swap="innerHTML" hx-trigger="click"{prev_disabled}>{icon("chevron-left", 13)} Prev</button>
  <span class="log-page-label">Page {page} of {pages}</span>
  <button class="btn btn-sm" hx-get="/log?page={page + 1}" hx-target="#log-view" hx-swap="innerHTML" hx-trigger="click"{next_disabled}>Next {icon("chevron-right", 13)}</button>
</div>"""

    return (
        f'<input type="hidden" id="log-page" name="page" value="{page}">'
        f'{_log_summary(rows)}'
        f'<div class="log-list">{"".join(parts)}</div>'
        f'{pager}'
    )
