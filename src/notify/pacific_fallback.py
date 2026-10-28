"""US Pacific time without a time zone database (the same job ``src/data/eastern.py`` does for Eastern).

WHY: the morning lineup (alert_morning.py) runs on the member's own clock and the owner's default is Pacific. A machine with
no tz database (a Windows laptop, a slim container) would otherwise read "America/Los_Angeles" as unknown and quietly fall
back to UTC, which would send a 9 AM Pacific text at 2 AM. The daylight rules are the Eastern file's (second Sunday of March
to first Sunday of November, changing at 02:00 LOCAL), so this subclasses that class and only changes the offsets and the
UTC instants of the two changes. ``alerts.zone`` uses it only when ``zoneinfo`` has no answer.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from src.data import eastern as _e

_PST = timedelta(hours=-8)
_PDT = timedelta(hours=-7)


class _UsPacific(_e._UsEastern):
    def utcoffset(self, dt):
        return None if dt is None else (_PDT if self._daylight(dt) else _PST)

    def tzname(self, dt):
        return None if dt is None else ("PDT" if self._daylight(dt) else "PST")

    def fromutc(self, dt: datetime) -> datetime:
        if dt.tzinfo is not self:
            raise ValueError("fromutc: dt.tzinfo is not self")
        utc = dt.replace(tzinfo=None)
        start, end = _e._dst_dates_for(utc.year)
        # 02:00 PST is 10:00 UTC; 02:00 PDT is 09:00 UTC.
        daylight = datetime.combine(start, time(10)) <= utc < datetime.combine(end, time(9))
        local = utc + (_PDT if daylight else _PST)
        autumn = datetime.combine(end, time(1))
        second_pass = not daylight and autumn <= local < autumn + timedelta(hours=1)
        return local.replace(tzinfo=self, fold=1 if second_pass else 0)

    def __repr__(self) -> str:
        return "PACIFIC_FALLBACK"


PACIFIC_FALLBACK = _UsPacific()
