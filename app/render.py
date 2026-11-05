import html
from datetime import datetime
from zoneinfo import ZoneInfo

from app.notification_log import read_log


def escape(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def header_text(value) -> str:
    text = " ".join(str(value).split())
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return (safe or "Something went wrong")[:300]


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
    color = escape(embed.get("color") or "#5865F2")
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

        <label>Embed color</label>
        <div class="color-row">
          <input type="color" name="embed_color" value="{color}" oninput="this.nextElementSibling.value=this.value">
          <input type="text" class="color-text" value="{color}" maxlength="7" oninput="this.previousElementSibling.value=this.value">
        </div>
      </div>"""


def render_log(page: int = 1, page_size: int = 10) -> str:
    rows = read_log()
    total = len(rows)
    if total == 0:
        return (
            '<input type="hidden" id="log-page" name="page" value="1">'
            '<span class="empty">No notifications logged yet</span>'
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
            '<span class="badge badge-ok">Sent</span>'
            if status == "ok"
            else '<span class="badge badge-err">Failed</span>'
        )
        meta = (
            f'<span class="log-kind {escape(kind)}">{escape(kind_label)}</span>'
            f'{escape(row.get("webhook_name", ""))}'
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
  <button class="btn btn-sm" hx-get="/log?page={page - 1}" hx-target="#log-view" hx-swap="innerHTML" hx-trigger="click"{prev_disabled}>&#x2039; Prev</button>
  <span class="log-page-label">Page {page} of {pages}</span>
  <button class="btn btn-sm" hx-get="/log?page={page + 1}" hx-target="#log-view" hx-swap="innerHTML" hx-trigger="click"{next_disabled}>Next &#x203a;</button>
</div>"""

    return (
        f'<input type="hidden" id="log-page" name="page" value="{page}">'
        f'<div class="log-list">{"".join(parts)}</div>'
        f'{pager}'
    )
