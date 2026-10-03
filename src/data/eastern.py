"""US Eastern time without a time zone database.

WHY THIS EXISTS (2026-10-03)
----------------------------
Several modules turn an Eastern wall-clock time into UTC or back (an NFL kickoff, the Eastern
date of a first pitch, the days an NFL capture slot covers) and use `zoneinfo`'s
"America/New_York". `zoneinfo` needs a tz database, which this repo's Windows machines do not
have, so each of those modules fell back to a fixed -04:00 and said in its docstring that every
game falls inside daylight time. That is false for the NFL: US daylight time ends on the first
Sunday of November and the season runs into February, so from November every Eastern clock read
an hour early (a Sunday 1 pm December kickoff became 17:00 UTC instead of 18:00).

`EASTERN_FALLBACK` is a `tzinfo` with the US rules written out, and `eastern()` returns
`ZoneInfo("America/New_York")` when the database exists and that fallback otherwise. Where the
database exists nothing changes. The rules are the ones src/datasvc/nfl/timeutil.py (which now
imports them from here) and tests/test_eastern_fallback.py check against `zoneinfo`.

The rules: from 2007, daylight time runs from the second Sunday of March at 02:00 local to the
first Sunday of November at 02:00 local; from 1987 to 2006, the first Sunday of April to the last
Sunday of October. Earlier years use the 1987 rule (no data here is that old). The hour that is
skipped in March and the hour that happens twice in November follow PEP 495, as `zoneinfo` does:
`fold=0` takes the offset in force before the change, `fold=1` the one after.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional, Tuple

FIRST_YEAR = 1987

_EST = timedelta(hours=-5)
_EDT = timedelta(hours=-4)
_HOUR = timedelta(hours=1)
_ZERO = timedelta(0)


def nth_sunday(year: int, month: int, n: int) -> date:
    """The n-th Sunday of a month (n >= 1), or the last one when n == -1."""
    if n == -1:
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - 6) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def us_dst_dates(year: int) -> Tuple[date, date]:
    """(first day of daylight time, first day back on standard time) in the US, both Sundays.

    From 2007: second Sunday of March to first Sunday of November. 1987 to 2006: first
    Sunday of April to last Sunday of October. The change happens at 02:00 local time.
    """
    if year >= 2007:
        return nth_sunday(year, 3, 2), nth_sunday(year, 11, 1)
    if year >= FIRST_YEAR:
        return nth_sunday(year, 4, 1), nth_sunday(year, 10, -1)
    raise ValueError(f"US daylight rules are only written out from {FIRST_YEAR}; got {year}")


def _dst_dates_for(year: int) -> Tuple[date, date]:
    """`us_dst_dates`, with the 1987 rule standing in before 1987 so a tz never raises."""
    if year >= FIRST_YEAR:
        return us_dst_dates(year)
    return nth_sunday(year, 4, 1), nth_sunday(year, 10, -1)


class _UsEastern(tzinfo):
    """America/New_York's offsets, written out (see the module docstring)."""

    def _daylight(self, dt: datetime) -> bool:
        start, end = _dst_dates_for(dt.year)
        wall = dt.replace(tzinfo=None, fold=0)
        spring = datetime.combine(start, time(2))
        autumn = datetime.combine(end, time(1))
        if spring <= wall < spring + _HOUR:        # 02:00-02:59 does not exist that day
            return dt.fold == 1
        if autumn <= wall < autumn + _HOUR:        # 01:00-01:59 happens twice that day
            return dt.fold == 0
        return spring + _HOUR <= wall < autumn

    def utcoffset(self, dt: Optional[datetime]) -> Optional[timedelta]:
        if dt is None:
            return None
        return _EDT if self._daylight(dt) else _EST

    def dst(self, dt: Optional[datetime]) -> Optional[timedelta]:
        if dt is None:
            return None
        return _HOUR if self._daylight(dt) else _ZERO

    def tzname(self, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        return "EDT" if self._daylight(dt) else "EST"

    def fromutc(self, dt: datetime) -> datetime:
        if dt.tzinfo is not self:
            raise ValueError("fromutc: dt.tzinfo is not self")
        utc = dt.replace(tzinfo=None)
        start, end = _dst_dates_for(utc.year)
        # 02:00 EST is 07:00 UTC; 02:00 EDT is 06:00 UTC.
        daylight = datetime.combine(start, time(7)) <= utc < datetime.combine(end, time(6))
        local = utc + (_EDT if daylight else _EST)
        autumn = datetime.combine(end, time(1))
        second_pass = not daylight and autumn <= local < autumn + _HOUR
        return local.replace(tzinfo=self, fold=1 if second_pass else 0)

    def __repr__(self) -> str:
        return "EASTERN_FALLBACK"


EASTERN_FALLBACK = _UsEastern()


def eastern() -> tzinfo:
    """America/New_York: `zoneinfo`'s when the tz database exists, else `EASTERN_FALLBACK`."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # noqa: BLE001 -- no tz database is a property of the machine, not an error
        return EASTERN_FALLBACK
