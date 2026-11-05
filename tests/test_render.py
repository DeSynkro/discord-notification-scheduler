from pathlib import Path

from app.main import _alarm_card_html, _form_html, _webhook_modal_form
from app.render import message_fields, timezone_input, webhook_options


def _alarm(**overrides):
    data = {
        "id": "a" * 12,
        "name": "x",
        "webhook_name": "g",
        "message": "m",
        "message_type": "text",
        "embed": None,
        "time": "09:00",
        "days": [],
        "timezone": "UTC",
        "enabled": True,
        "last_error": None,
    }
    data.update(overrides)
    return data


def test_alarm_card_escapes_error_title(tmp_data):
    alarm = _alarm(last_error='"><script>alert(1)</script>')
    html = _alarm_card_html(alarm, [])
    assert "<script>" not in html
    assert "&quot;&gt;&lt;script&gt;" in html


def test_form_escapes_name_and_message(tmp_data):
    alarm = _alarm(
        name='"><img src=x onerror=1>',
        message="</textarea><script>alert(1)</script>",
    )
    html = _form_html(alarm)
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "&lt;/textarea&gt;" in html


def test_webhook_modal_escapes_name_and_url(tmp_data):
    wh = {
        "name": '"><script>alert(1)</script>',
        "url": 'https://discord.com/api/webhooks/1/x"><script>',
    }
    html = _webhook_modal_form(wh)
    assert "<script>" not in html
    assert "&quot;&gt;&lt;script&gt;" in html


def test_webhook_options_escape_names():
    html = webhook_options([{"name": '"><b>x</b>'}], '"><b>x</b>')
    assert "<b>" not in html
    assert "&quot;&gt;&lt;b&gt;x&lt;/b&gt;" in html


def test_timezone_input_escapes_value():
    html = timezone_input('"><script>', ["UTC"])
    assert "<script>" not in html
    assert 'value="&quot;&gt;&lt;script&gt;"' in html


def test_message_fields_escape_message_and_embed():
    html = message_fields(
        "</textarea><script>alert(1)</script>",
        "embed",
        {"title": '"><img src=x>', "color": "#ff0000"},
    )
    assert "<script>" not in html
    assert "<img src=x>" not in html
    assert "&lt;/textarea&gt;" in html


def test_sort_select_has_id():
    html = Path("app/templates/index.html").read_text()
    assert 'id="sort-select"' in html
