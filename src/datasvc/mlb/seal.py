"""The sealed window for the MLB box-score layer: outcomes dated 2026-01-01..2026-08-27 are never read.

CLAUDE.md and docs/EVIDENCE_RULES say the 2026-01-01..2026-08-27 outcomes are sealed (2025 is tuning-only). This
layer fetches MLB game results, so the rule is enforced here, in code, at every door, and each door has a test
(tests/test_datasvc_mlb_statsapi.py):

* THE FETCH. `check_url` is called before any request. A schedule request for a sealed day, a date range that
  overlaps the window, a season-wide player game-log or stats request (they return every game of the season,
  sealed ones included), a box score for a game we did not get from an open schedule day: all refused before
  the network is touched. Only two URL shapes are allowed at all (an open day's schedule, and the box score of a
  game that schedule listed).
* THE PARSE. A payload that carries a game dated inside the window raises `SealedWindowError` instead of being
  parsed (an API that answers a different date than asked, or a suspended game resumed from a sealed day).
* THE STORE. `MlbBoxStore.append` refuses any row dated inside the window, and reads drop such rows.
* THE READ API. A date or season-wide question that reaches into the window is refused by name.
* WHAT IS NOT STORED. A box score carries season-to-date totals and records (`seasonStats`, `era`, `avg`, a
  team's win-loss record, a decision note like "(W, 2-0)"). Those are cumulative over games that include sealed
  ones, so the parser keeps game-level counting stats only.

`FORWARD_FROM` is the owner's scope for this layer ("forward from today only", 2026-10-20): the pipeline starts
there and does not backfill. It is a default floor that code can lower on purpose; the sealed window it can not.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date, datetime
from typing import Any, Iterable, Optional, Set

SEALED_FIRST = date(2026, 1, 1)
SEALED_LAST = date(2026, 8, 27)
FORWARD_FROM = date(2026, 10, 20)

API_HOST = "statsapi.mlb.com"


class SealedWindowError(RuntimeError):
    """Something tried to read an MLB outcome dated inside the sealed window."""


class UnsupportedUrl(RuntimeError):
    """A statsapi URL outside the two shapes this layer is allowed to request."""


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def is_sealed(value: Any) -> bool:
    d = _as_date(value)
    return d is not None and SEALED_FIRST <= d <= SEALED_LAST


def overlaps_sealed(first: Any, last: Any) -> bool:
    a, b = _as_date(first), _as_date(last)
    if a is None or b is None:
        return False
    return not (b < SEALED_FIRST or a > SEALED_LAST)


def assert_open(value: Any, what: str = "date") -> None:
    if is_sealed(value):
        raise SealedWindowError(f"{what} {str(value)[:10]} is inside the sealed window "
                                f"{SEALED_FIRST}..{SEALED_LAST}: MLB outcomes there are never read")


def drop_sealed(rows: Iterable[dict], fields: Iterable[str] = ("date", "date_utc")) -> list:
    """Rows whose date is outside the window (read-side defence in depth)."""
    out = []
    for r in rows:
        if any(is_sealed(r.get(f)) for f in fields if r.get(f)):
            continue
        out.append(r)
    return out


_SCHEDULE = re.compile(r"^/api/v1/schedule/?$")
_BOX = re.compile(r"^/api/v1/game/(\d+)/(boxscore|linescore)/?$")
_TEAMS = re.compile(r"^/api/v1/teams/?$")


def check_url(url: str, listed_games: Optional[Set[str]] = None) -> None:
    """Raise unless `url` is one of the allowed shapes and reaches only open dates.

    Allowed: `schedule?sportId=1&date=D` (D open) and `game/<pk>/boxscore|linescore` for a `pk` in
    `listed_games` (a game an open schedule day listed), and the static `teams?sportId=1` list."""
    parts = urllib.parse.urlsplit(url)
    if parts.netloc.lower() != API_HOST:
        raise UnsupportedUrl(f"{url}: not {API_HOST}")
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    for key in ("date", "startDate", "endDate"):
        if key in query:
            assert_open(query[key], f"{key}")
    if "startDate" in query or "endDate" in query:
        if overlaps_sealed(query.get("startDate") or query.get("endDate"), query.get("endDate") or query.get("startDate")):
            raise SealedWindowError(f"date range {query.get('startDate')}..{query.get('endDate')} reaches into the sealed window")
    if "season" in query and str(query["season"]).strip() == "2026" and not _SCHEDULE.match(parts.path):
        raise SealedWindowError("a season-wide 2026 request returns sealed outcomes")
    if _SCHEDULE.match(parts.path):
        if "date" not in query or "startDate" in query or "endDate" in query:
            raise UnsupportedUrl(f"{url}: only a single-day schedule (date=YYYY-MM-DD) is allowed")
        return
    m = _BOX.match(parts.path)
    if m:
        if listed_games is None or m.group(1) not in listed_games:
            raise UnsupportedUrl(f"{url}: game {m.group(1)} was not listed by an open schedule day")
        return
    if _TEAMS.match(parts.path) and "season" not in query:
        return
    raise UnsupportedUrl(f"{url}: not an allowed statsapi shape (open schedule day, box score of a listed game, teams)")
