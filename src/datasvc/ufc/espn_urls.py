"""Every ESPN MMA URL the UFC data layer requests, in one place.

ESPN's core API links resources with "$ref" URLs (http, with lang/region
parameters). `ref_url` turns one into the canonical https form the fetcher caches
under, and `id_from_ref` reads an id out of one.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional, Union

from src.datasvc.http import canonical_url

CORE = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc"
ATHLETES = "https://sports.core.api.espn.com/v2/sports/mma/athletes"
SITE = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc"
UFCCOM = "https://www.ufc.com/athlete"


def season_events(year: int, limit: int = 1000) -> str:
    """Every event of one calendar year, as $refs."""
    return f"{CORE}/events?dates={int(year)}&limit={int(limit)}"


def event(event_id: str) -> str:
    """One event with all its competitions (bouts) embedded."""
    return f"{CORE}/events/{event_id}"


def competition(event_id: str, comp_id: str) -> str:
    return f"{CORE}/events/{event_id}/competitions/{comp_id}"


def competition_status(event_id: str, comp_id: str) -> str:
    """Status of one bout, with the result (method, detail, target) once final."""
    return f"{CORE}/events/{event_id}/competitions/{comp_id}/status"


def competition_details(event_id: str, comp_id: str, limit: int = 1000) -> str:
    """Play-by-play events of one bout (takedown attempts, knockdowns, round ends)."""
    return f"{CORE}/events/{event_id}/competitions/{comp_id}/details?limit={int(limit)}"


def competitor(event_id: str, comp_id: str, athlete_id: str) -> str:
    return f"{CORE}/events/{event_id}/competitions/{comp_id}/competitors/{athlete_id}"


def competitor_statistics(event_id: str, comp_id: str, athlete_id: str) -> str:
    """One fighter's totals for one bout (43 statistics on recent fights)."""
    return f"{CORE}/events/{event_id}/competitions/{comp_id}/competitors/{athlete_id}/statistics/0"


def competition_odds(event_id: str, comp_id: str) -> str:
    """Odds for one bout (DraftKings: moneyline, rounds total, method of victory; open/close/current)."""
    return f"{CORE}/events/{event_id}/competitions/{comp_id}/odds"


def athlete(athlete_id: str) -> str:
    return f"{ATHLETES}/{athlete_id}"


def athlete_records(athlete_id: str) -> str:
    return f"{ATHLETES}/{athlete_id}/records"


def athlete_eventlog(athlete_id: str, limit: int = 200) -> str:
    return f"{ATHLETES}/{athlete_id}/eventlog?limit={int(limit)}"


def scoreboard(day: Union[str, date]) -> str:
    """The site API's scoreboard for one date (YYYYMMDD or a date)."""
    text = day.strftime("%Y%m%d") if isinstance(day, date) else str(day).replace("-", "")
    return f"{SITE}/scoreboard?dates={text}"


def ufccom_athlete(slug: str) -> str:
    return f"{UFCCOM}/{slug}"


def ref_url(value) -> Optional[str]:
    """The canonical URL of a "$ref" (given the ref string or the dict holding it)."""
    ref = value.get("$ref") if isinstance(value, dict) else value
    return canonical_url(ref) if ref else None


_ID_PATTERNS = {
    "event": re.compile(r"/events/(\d+)"),
    "competition": re.compile(r"/competitions/(\d+)"),
    "competitor": re.compile(r"/competitors/(\d+)"),
    "athlete": re.compile(r"/athletes/(\d+)"),
    "venue": re.compile(r"/venues/(\d+)"),
    "provider": re.compile(r"/odds/(\d+)"),
}


def id_from_ref(value, kind: str) -> Optional[str]:
    """The id of `kind` (event, competition, competitor, athlete, venue, provider) in a $ref."""
    ref = value.get("$ref") if isinstance(value, dict) else value
    if not ref:
        return None
    found = _ID_PATTERNS[kind].search(str(ref))
    return found.group(1) if found else None
