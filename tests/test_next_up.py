from datetime import datetime, timezone

from app.next_up import board_data, render_next_up, upcoming
from app.storage import write_json

WEBHOOK = {
    "name": "general",
    "url": "https://discord.com/api/webhooks/123456789012345678/abc",
}


def _alarm(**overrides):
    alarm = {
        "id": "a10000000000",
        "name": "Weekly report",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "embed": None,
        "time": "10:00",
        "days": ["Monday"],
        "timezone": "UTC",
        "enabled": True,
        "created": "2026-01-01T00:00:00+00:00",
        "last_fired": None,
        "last_error": None,
    }
    alarm.update(overrides)
    return alarm


def test_upcoming_picks_next_weekly_occurrence():
    # Sunday 8 November 2026, 12:00 UTC
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    items = upcoming([_alarm()], [], [WEBHOOK], now)
    assert len(items) == 1
    assert items[0]["when"] == datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)


def test_upcoming_skips_disabled_alarms():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    assert upcoming([_alarm(enabled=False)], [], [WEBHOOK], now) == []


def test_upcoming_orders_soonest_first():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    later = _alarm(id="a20000000000", name="Later", days=["Thursday"])
    items = upcoming([later, _alarm()], [], [WEBHOOK], now)
    assert [item["name"] for item in items] == ["Weekly report", "Later"]


def test_render_next_up_empty_state():
    html = render_next_up([], [], [], datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc))
    assert "Nothing scheduled" in html
    assert "Add channel" in html


def test_upcoming_uses_alarm_color_and_edit_url():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    alarm = _alarm(color="#ff0000")
    items = upcoming([alarm], [], [WEBHOOK], now)
    assert items[0]["color"] == "#FF0000"
    assert items[0]["edit_url"] == "/alarms/a10000000000"


def test_upcoming_ignores_embed_color_for_pin_color():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    alarm = _alarm(
        color="#00FF00",
        message_type="embed",
        embed={"title": "Report", "color": "#FF0000"},
    )
    items = upcoming([alarm], [], [WEBHOOK], now)
    assert items[0]["color"] == "#00FF00"


def test_upcoming_defaults_to_no_color_without_alarm_color():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    items = upcoming([_alarm()], [], [WEBHOOK], now)
    assert items[0]["color"] is None


def test_upcoming_uses_calendar_color():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    alert = {
        "id": "cal000000001",
        "name": "Rent",
        "webhook_name": "general",
        "message": "m",
        "message_type": "text",
        "embed": None,
        "date": "2099-11-20",
        "time": "09:00",
        "timezone": "UTC",
        "repeat": "none",
        "enabled": True,
        "color": "#112233",
    }
    items = upcoming([], [alert], [WEBHOOK], now)
    assert items[0]["color"] == "#112233"
    assert items[0]["edit_url"] == "/calendar/cal000000001/edit"


def test_render_next_up_marker_has_tooltip_data():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    alarm = _alarm(color="#FF0000")
    html = render_next_up([WEBHOOK], [alarm], [], now)
    assert 'class="rail-marker weekly"' in html
    assert 'data-edit-url="/alarms/a10000000000"' in html
    assert "data-name=\"Weekly report\"" in html
    assert "--marker-color:#FF0000" in html


def test_board_data_marker_fields():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    alarm = _alarm(color="#FF0000")
    data = board_data([WEBHOOK], [alarm], [], now)
    marker = data["window"][0]
    assert marker["name"] == "Weekly report"
    assert marker["channel"] == "general"
    assert marker["edit_url"] == "/alarms/a10000000000"
    assert marker["color"] == "#FF0000"
    assert "time_label" in marker


def test_counts_report_all_deliveries_beyond_marker_cap():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    alarms = [
        _alarm(
            id=f"a{i:011d}",
            name=f"Alarm {i}",
            time=f"{13 + i // 2:02d}:{(i % 2) * 30:02d}",
            days=["Sunday"],
        )
        for i in range(12)
    ]
    data = board_data([WEBHOOK], alarms, [], now)
    assert data["counts"] == {"both": 12, "weekly": 12, "calendar": 0}
    assert len(data["window"]) == 8

    html = render_next_up([WEBHOOK], alarms, [], now)
    assert 'data-count-both="12"' in html
    assert 'data-count-weekly="12"' in html
    assert 'data-count-calendar="0"' in html


def test_rail_has_kind_filter_and_clickable_rows():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    first = _alarm(id="a10000000000", time="18:00", days=["Sunday"])
    second = _alarm(id="a20000000000", time="10:00", days=["Monday"])
    html = render_next_up([WEBHOOK], [first, second], [], now)
    assert 'data-rail-filter="both"' in html
    assert 'data-rail-filter="weekly"' in html
    assert 'data-rail-filter="calendar"' in html
    assert 'class="then-row"' in html
    assert 'data-kind="weekly"' in html
    assert 'data-edit-url="/alarms/a20000000000"' in html


def test_render_next_up_shows_countdown_and_channel():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    html = render_next_up([WEBHOOK], [_alarm()], [], now)
    assert "Next delivery" in html
    assert "data-countdown=" in html
    assert "#" in html
    assert "general" in html


def test_next_up_fragment_route(client):
    assert client.get("/next-up").status_code == 200


def test_dashboard_includes_delivery_board(client):
    write_json("webhooks", [WEBHOOK])
    write_json("alarms", [_alarm()])
    html = client.get("/").text
    assert 'id="next-up"' in html
    assert "Next delivery" in html
