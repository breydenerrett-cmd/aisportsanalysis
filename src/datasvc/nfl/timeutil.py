"""Clocks for NFL data, with no time zone database.

WHY THIS EXISTS
---------------
The schedule gives each kickoff as a calendar date and a 24-hour clock time in US Eastern.
Turning that into a UTC instant needs the Eastern daylight-saving rules, and the obvious
tool (`zoneinfo`) needs a tz database that this repo's Windows machines and slim
containers do not have. `src.providers.nfl.start_utc` then falls back to a fixed UTC-4,
which is wrong for every game between the first Sunday of November and the second Sunday
of March: Sunday 1 pm Eastern in December is 18:00 UTC, not 17:00 UTC. A kickoff an hour
early moves a game across the leakage gate, so the rules are written out here and tested
against `zoneinfo` wherever it is available.

`utc_offset_hours` does the same for the handful of regions that host NFL games (the US
zones, the UK, central Europe, Brazil, Mexico, Victoria, Australia), for the travel and
time-zone features.

Valid for 1987 onward (the first year of the 1987-2006 US rule). nflverse starts in 1999.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple, Union

# One definition of an instant for the whole data service: ISO text, a bare date is the
# start of that day (00:00 UTC), a trailing Z is accepted on every Python we support.
from src.datasvc.ufc.features import instant, iso_utc, parse_instant

__all__ = ["instant", "iso_utc", "parse_instant", "eastern_to_utc", "us_dst_dates",
           "utc_offset_hours", "season_of", "ZONES", "FIRST_YEAR"]

# The US rules live in src/data/eastern.py (2026-10-03), so the Eastern fallback the NFL card's
# provider and the snapshot store use is the same rule this module tests against zoneinfo.
from src.data.eastern import FIRST_YEAR, us_dst_dates
from src.data.eastern import nth_sunday as _nth_sunday

_UTC = timezone.utc
_CLOCK = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def eastern_to_utc(gameday: str, gametime: Optional[str]) -> Optional[str]:
    """`2025-12-25`, `13:00` (US Eastern) as `2025-12-25T18:00:00Z`; None for a blank time.

    Raises ValueError for a date or clock that is not one. A wall-clock time inside the
    hour that does not exist (spring) or happens twice (autumn) is read as daylight time;
    no NFL game starts between 01:00 and 03:00 so the choice never matters in practice.
    """
    if gametime is None or not str(gametime).strip():
        return None
    day = date.fromisoformat(str(gameday).strip())
    match = _CLOCK.match(str(gametime))
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ValueError(f"not a 24-hour clock time: {gametime!r}")
    local = datetime(day.year, day.month, day.day, int(match.group(1)), int(match.group(2)))
    start, end = us_dst_dates(day.year)
    daylight = datetime.combine(start, time(2, 0)) <= local < datetime.combine(end, time(2, 0))
    utc = local + timedelta(hours=4 if daylight else 5)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


# -- UTC offsets of the regions that host games -----------------------------------------------

# name -> (standard-time offset in hours, daylight rule). The rule is one of
# "us" (US dates above), "eu" (last Sunday of March to last Sunday of October, 01:00 UTC),
# "au" (southern hemisphere: first Sunday of October to first Sunday of April) or "none".
ZONES = {
    "us_eastern": (-5, "us"),
    "us_central": (-6, "us"),
    "us_mountain": (-7, "us"),
    "us_pacific": (-8, "us"),
    "us_arizona": (-7, "none"),      # Arizona does not change its clocks
    "uk": (0, "eu"),
    "central_europe": (1, "eu"),
    "brazil": (-3, "none"),          # no daylight time since 2019
    "mexico": (-6, "none"),          # none since 2022-10-30; every game here is later than that
    "au_victoria": (10, "au"),
}


def _utc(day: date, hour: int, offset_hours: int = 0) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=_UTC) - timedelta(hours=offset_hours)


def _daylight(rule: str, std: int, when: datetime) -> bool:
    year = when.year
    if rule == "us":
        start, end = us_dst_dates(year)
        return _utc(start, 2, std) <= when < _utc(end, 2, std + 1)
    if rule == "eu":
        return _utc(_nth_sunday(year, 3, -1), 1) <= when < _utc(_nth_sunday(year, 10, -1), 1)
    if rule == "au":
        return when >= _utc(_nth_sunday(year, 10, 1), 2, std) or when < _utc(_nth_sunday(year, 4, 1), 2, std)
    return False


def utc_offset_hours(zone: str, when_utc: Union[datetime, str]) -> int:
    """The zone's offset from UTC, in whole hours, at an instant (daylight time included)."""
    if zone not in ZONES:
        raise KeyError(f"unknown zone {zone!r}")
    when = parse_instant(when_utc)
    std, rule = ZONES[zone]
    return std + (1 if _daylight(rule, std, when) else 0)


def season_of(when: Union[datetime, date, str]) -> int:
    """The NFL season an instant falls in: named for the year it starts, March to February."""
    stamp = parse_instant(when)
    return stamp.year if stamp.month >= 3 else stamp.year - 1
