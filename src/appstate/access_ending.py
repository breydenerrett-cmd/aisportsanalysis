"""When a member's full access is about to end, and what to tell them: `ending_notice(user)`.

WHY THIS EXISTS (owner ask 2026-10-27)
--------------------------------------
Members whose access has an end date (an invited 7-day tester, a 7-day free trial that was
cancelled) got no warning before it ended. The owner ruling the same day is that an ended tester
becomes a FREE member and keeps their kennel (src/appstate/access.py), so the warning has two jobs:
say plainly that the full access ends and on what day, and sell the upgrade by naming the real
things only the paid plan keeps.

WHO IS WARNED, AND WHO IS NOT
-----------------------------
  tester   a `testers` window that is still open (`access.access_token_end` kind "tester")
  trial    a subscription still paid through a future instant that is scheduled to END
           (`cancel_at` set): a free trial the member cancelled. A trial that will renew is not
           ending, so it is never warned (that would be a false claim).
  nobody   a paid subscriber who renews, a comp (free member), a self-serve free account, an
           admin-invited beta user, a suspended account, anyone with no end date.

The answer is decided HERE, on the server, from the stored end date, so the page cannot disagree with
the gate: `show_warning` is true only inside WARN_DAYS calendar days (Pacific, the owner's clock)
and never after the end. Time is injected (`now`) so tests never read a clock.

THE DAY COUNT IS A CALENDAR COUNT IN PACIFIC TIME. "Ends in 2 days (on Friday, October 30)" must
agree with the date printed beside it, so N is the difference between the Pacific calendar dates of
the end and of now, not a rounded number of 24-hour spans. 0 means the end falls on today's date and
has not yet passed: "ends today".

COPY RULES (owner): no "beta", "new", "dog", no profit claims, never Bet Check, paper only, and
21+ / 1-800-GAMBLER wherever picks are promoted. The words the page shows are web/js/access-ending-copy.js;
the email's are in src/notify/email_render.py. tests/test_access_ending.py pins both.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from src.appstate import access, customers, users as users_store
from src.data.eastern import us_dst_dates

WARN_DAYS = 3                   # the banner shows when the end is this many calendar days away or fewer
EMAIL_DAYS = (2, 0)             # and the email goes once at 2 days and once on the last day
KIND_TESTER = "tester"
KIND_TRIAL = "trial"

# The banner's and the email's words (web/js/access-ending-copy.js says the same; a test pins that they agree).
KEEP_LINE = "You keep your kennel and every hound in it."
LOSE_LINE = "Without a paid plan you lose Gameday, Matchups, Props and the daily picks card."

_PST = timedelta(hours=-8)
_PDT = timedelta(hours=-7)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def to_pacific(moment: datetime) -> datetime:
    """`moment` as a Pacific wall-clock datetime (naive). Written out because Windows machines have no tz
    database (the same reason as src/data/eastern.py): daylight time runs from 02:00 PST on the US spring
    Sunday (10:00 UTC) to 02:00 PDT on the autumn one (09:00 UTC)."""
    utc = _aware(moment).astimezone(timezone.utc).replace(tzinfo=None)
    start, end = us_dst_dates(utc.year)
    daylight = (datetime(start.year, start.month, start.day, 10) <= utc
                < datetime(end.year, end.month, end.day, 9))
    return utc + (_PDT if daylight else _PST)


def pacific_date(moment: datetime) -> date:
    return to_pacific(moment).date()


def day_label(moment: datetime) -> str:
    """"Friday, October 30" in Pacific time."""
    d = pacific_date(moment)
    return f"{_WEEKDAYS[d.weekday()]}, {_MONTHS[d.month - 1]} {d.day}"


def days_until(ends_at: datetime, now: datetime) -> Optional[int]:
    """Calendar days (Pacific) from now to the end, or None once the end has passed."""
    if _aware(ends_at) <= _aware(now):
        return None
    return (pacific_date(ends_at) - pacific_date(now)).days


def _parse(value) -> Optional[datetime]:
    try:
        return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def access_end(user: Optional[users_store.User], *, now: Optional[datetime] = None) -> Optional[dict]:
    """{"kind": "tester" | "trial", "ends_at": datetime} for a member whose full access has an end date
    still ahead, else None. Never raises: an unreadable store reads as "no end date known", because a
    warning that cannot be backed by a stored date is not shown."""
    if user is None or user.status == "suspended":
        return None
    when = _aware(now) if now is not None else datetime.now(timezone.utc)
    try:
        found = access.access_token_end(user, now=when)
        if found is not None and found[0] == "tester" and _aware(found[1]) > when:
            return {"kind": KIND_TESTER, "ends_at": _aware(found[1])}
        record = customers.get_subscription_record(user.id)
        if record and record.get("cancel_at") and record.get("status") in customers.PAID_STATUSES:
            ends = _parse(record.get("paid_through"))
            if ends is not None and ends > when and customers.has_paid_access(user.id, when):
                return {"kind": KIND_TRIAL, "ends_at": ends}
    except Exception as exc:  # noqa: BLE001 -- see docstring
        print(f"access_ending: end date unreadable: {exc!r}", file=sys.stderr, flush=True)
    return None


def ending_notice(user: Optional[users_store.User], *, now: Optional[datetime] = None) -> dict:
    """What GET /me/access says about this member. Always has `show_warning`; the rest is present only when
    there is an end date (no secrets, no email address)."""
    when = _aware(now) if now is not None else datetime.now(timezone.utc)
    end = access_end(user, now=when)
    if end is None:
        return {"show_warning": False, "kind": None}
    n = days_until(end["ends_at"], when)
    return {"show_warning": n is not None and n <= WARN_DAYS, "kind": end["kind"],
            "ends_at": end["ends_at"].strftime("%Y-%m-%dT%H:%M:%SZ"), "days_left": n,
            "ends_today": n == 0, "ends_on": day_label(end["ends_at"])}
