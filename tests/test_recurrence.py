from datetime import date, datetime, time, timezone

from app.recurrence import compute_next_fire, occurrences_between

UTC = timezone.utc


def test_none_returns_first_occurrence():
    got = compute_next_fire(date(2026, 3, 3), time(9, 0), "UTC", "none")
    assert got == "2026-03-03T09:00:00+00:00"


def test_none_returns_none_after_it_passed():
    got = compute_next_fire(
        date(2026, 3, 3), time(9, 0), "UTC", "none",
        after_utc=datetime(2026, 3, 4, tzinfo=UTC),
    )
    assert got is None


def test_daily_advances_one_day():
    got = compute_next_fire(
        date(2026, 3, 3), time(9, 0), "UTC", "daily",
        after_utc=datetime(2026, 3, 3, 9, 0, tzinfo=UTC),
    )
    assert got == "2026-03-04T09:00:00+00:00"


def test_weekly_advances_seven_days():
    got = compute_next_fire(
        date(2026, 3, 3), time(9, 0), "UTC", "weekly",
        after_utc=datetime(2026, 3, 3, 9, 0, tzinfo=UTC),
    )
    assert got == "2026-03-10T09:00:00+00:00"


def test_monthly_clamps_jan_31_to_feb_28():
    got = compute_next_fire(
        date(2026, 1, 31), time(9, 0), "UTC", "monthly",
        after_utc=datetime(2026, 1, 31, 9, 0, tzinfo=UTC),
    )
    assert got == "2026-02-28T09:00:00+00:00"


def test_monthly_clamp_does_not_drift():
    got = compute_next_fire(
        date(2026, 1, 31), time(9, 0), "UTC", "monthly",
        after_utc=datetime(2026, 2, 28, 9, 0, tzinfo=UTC),
    )
    assert got == "2026-03-31T09:00:00+00:00"


def test_yearly_maps_feb_29_to_feb_28():
    got = compute_next_fire(
        date(2028, 2, 29), time(9, 0), "UTC", "yearly",
        after_utc=datetime(2028, 2, 29, 9, 0, tzinfo=UTC),
    )
    assert got == "2029-02-28T09:00:00+00:00"


def test_yearly_leap_day_returns_on_leap_years():
    got = compute_next_fire(
        date(2028, 2, 29), time(9, 0), "UTC", "yearly",
        after_utc=datetime(2031, 2, 28, 9, 0, tzinfo=UTC),
    )
    assert got == "2032-02-29T09:00:00+00:00"


def test_daily_keeps_wall_clock_across_dst():
    got = compute_next_fire(
        date(2026, 3, 7), time(9, 0), "America/New_York", "daily",
        after_utc=datetime(2026, 3, 7, 14, 0, tzinfo=UTC),
    )
    assert got == "2026-03-08T13:00:00+00:00"


def test_first_occurrence_converts_timezone_to_utc():
    got = compute_next_fire(date(2026, 11, 5), time(9, 0), "Asia/Tokyo", "none")
    assert got == "2026-11-05T00:00:00+00:00"


def test_occurrences_between_finds_each_daily_fire():
    got = occurrences_between(
        date(2026, 11, 5), time(9, 0), "UTC", "daily",
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 12, 1, tzinfo=UTC),
    )
    assert len(got) == 26
    assert got[0].isoformat() == "2026-11-05T09:00:00+00:00"
    assert got[-1].isoformat() == "2026-11-30T09:00:00+00:00"


def test_occurrences_between_returns_empty_for_past_one_time():
    got = occurrences_between(
        date(2026, 11, 5), time(9, 0), "UTC", "none",
        datetime(2026, 12, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert got == []
