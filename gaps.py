"""Find study gaps in a calendar and turn them into send times.

Gaps:     timed events with a gap keyword (e.g. "Team bus"), and meet days.
Blocked:  every other timed event (shifts, practice, warm-ups, races, lectures), and sleep.
Output:   one send time at the start of each free window of at least min_gap_minutes,
          at most max_sets_per_day per day.

Usage: python gaps.py data/chloe.ics
"""
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import icalendar

import db


@dataclass(frozen=True)
class Event:
    summary: str
    start: datetime | date
    end: datetime | date
    all_day: bool


@dataclass(frozen=True)
class SendTime:
    at: datetime
    window_end: datetime
    label: str


def load_events(ics_path, tz: ZoneInfo) -> list[Event]:
    with open(ics_path, "rb") as f:
        cal = icalendar.Calendar.from_ical(f.read())
    events = []
    for ve in cal.walk("VEVENT"):
        start, end = ve.decoded("DTSTART"), ve.decoded("DTEND")
        all_day = not isinstance(start, datetime)
        if not all_day:
            start, end = start.astimezone(tz), end.astimezone(tz)
        events.append(Event(str(ve.get("SUMMARY", "")), start, end, all_day))
    return events


def _at(d: date, hhmm: str, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time.fromisoformat(hhmm), tz)


def _subtract(window, blocked):
    """Remove blocked intervals from one (start, end) window; return the free pieces."""
    pieces = [window]
    for bs, be in blocked:
        nxt = []
        for s, e in pieces:
            if be <= s or bs >= e:
                nxt.append((s, e))
                continue
            if s < bs:
                nxt.append((s, bs))
            if be < e:
                nxt.append((be, e))
        pieces = nxt
    return pieces


def find_send_times(events: list[Event], cfg: dict) -> list[SendTime]:
    g = cfg["gaps"]
    tz = ZoneInfo(g["timezone"])
    gap_kw = [k.lower() for k in g["gap_keywords"]]
    meet_kw = [k.lower() for k in g["meet_keywords"]]

    def is_gap(ev):
        return any(k in ev.summary.lower() for k in gap_kw)

    timed = [e for e in events if not e.all_day]
    gap_events = [(e.start, e.end, e.summary) for e in timed if is_gap(e)]
    blocked = [(e.start, e.end) for e in timed if not is_gap(e)]

    meet_days = []
    for e in events:
        if e.all_day and any(k in e.summary.lower() for k in meet_kw):
            d = e.start
            while d < e.end:  # DTEND of an all-day event is exclusive
                meet_days.append((_at(d, g["meet_day_start"], tz), _at(d, g["sleep_start"], tz), "Meet day"))
                d += timedelta(days=1)

    candidates = gap_events + meet_days
    if not candidates:
        return []

    # Sleep is blocked every night across the calendar's range.
    first = min(c[0] for c in candidates).date() - timedelta(days=1)
    last = max(c[1] for c in candidates).date() + timedelta(days=1)
    d = first
    while d <= last:
        blocked.append((_at(d, g["sleep_start"], tz), _at(d + timedelta(days=1), g["sleep_end"], tz)))
        d += timedelta(days=1)

    min_gap = timedelta(minutes=g["min_gap_minutes"])
    sends = []
    # A bus ride is its own gap, so meet-day windows also exclude bus time.
    for windows, exclude in ((gap_events, blocked), (meet_days, blocked + [(s, e) for s, e, _ in gap_events])):
        for s, e, label in windows:
            for ps, pe in _subtract((s, e), exclude):
                if pe - ps >= min_gap:
                    sends.append(SendTime(ps, pe, label))

    per_day: dict[date, int] = {}
    capped = []
    for st in sorted(sends, key=lambda x: x.at):
        n = per_day.get(st.at.date(), 0)
        if n < g["max_sets_per_day"]:
            capped.append(st)
            per_day[st.at.date()] = n + 1
    return capped


def send_times_for(ics_path, cfg: dict) -> list[SendTime]:
    return find_send_times(load_events(ics_path, ZoneInfo(cfg["gaps"]["timezone"])), cfg)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else db.ROOT / "data" / "chloe.ics"
    for st in send_times_for(path, db.load_config()):
        print(f"{st.at:%a %b %d %H:%M}  (free until {st.window_end:%H:%M})  {st.label}")
