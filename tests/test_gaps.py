from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import db
import gaps

TZ = ZoneInfo("America/Halifax")
CFG = db.load_config()
EVENTS = gaps.load_events(db.ROOT / "data" / "chloe.ics", TZ)
SENDS = gaps.find_send_times(EVENTS, CFG)


def at(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm, tzinfo=TZ)


def set_overlaps(start, end):
    """True if any 5-minute set would run inside [start, end)."""
    return any(s.at < end and s.at + gaps.timedelta(minutes=5) > start for s in SENDS)


def test_set_goes_to_friday_bus():
    assert any(at(23, 14) <= s.at < at(23, 16) for s in SENDS)


def test_nothing_during_friday_shift():
    assert not set_overlaps(at(23, 16), at(23, 22))


def test_nothing_during_saturday_warmup():
    assert not set_overlaps(at(24, 6, 45), at(24, 7, 45))


@pytest.mark.parametrize("day", [23, 24, 25, 26])
def test_nothing_at_night(day):
    for s in SENDS:
        if s.at.day == day:
            assert at(day, 4, 50) <= s.at < at(day, 23)


def test_no_set_overlaps_any_blocked_event():
    for e in EVENTS:
        if not e.all_day and "bus" not in e.summary.lower():
            assert not set_overlaps(e.start, e.end), e.summary


def test_regular_weekday_gets_no_sets_and_daily_cap_holds():
    days = [s.at.day for s in SENDS]
    assert 26 not in days  # Monday: no bus, no meet
    assert max(days.count(d) for d in set(days)) <= CFG["gaps"]["max_sets_per_day"]
