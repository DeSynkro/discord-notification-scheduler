import html


def escape(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


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
          <input type="color" name="embed_color" value="{color}">
          <input type="text" class="color-text" value="{color}" maxlength="7" oninput="this.previousElementSibling.value=this.value">
        </div>
      </div>"""
