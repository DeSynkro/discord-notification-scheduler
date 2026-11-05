def test_dashboard_has_bubbles_and_views(client):
    html = client.get("/").text
    assert 'data-view="alarms"' in html
    assert 'data-view="calendar"' in html
    assert 'data-view="log"' in html
    assert 'id="calendar-view"' in html
    assert 'id="log-view"' in html
    assert 'id="sort-select"' in html
