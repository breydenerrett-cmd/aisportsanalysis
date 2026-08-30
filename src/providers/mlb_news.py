"""Roster moves and injury news, from MLB's own free transactions feed.

WHY THIS AND NOT A NEWS SITE
----------------------------
The tool is supposed to surface things a bettor would not already be thinking
about. Beat-reporter narrative is the obvious place to look and it is the wrong
place to start, for one reason: it cannot be replayed.

A claim built on a web search made tonight can never be tested against 2023,
because there is no honest way to reconstruct what a search would have returned
on a Tuesday three years ago. Two full research families have now died in ways
that only careful backtesting could reveal, and building the next layer on
inputs that can never be backtested would repeat that at a larger scale.

MLB publishes every transaction with a date. That makes it replayable, which
makes it testable, which is the whole difference. Narrative can be layered on
top later as colour -- clearly marked as unverifiable -- once the backbone is
something we can actually validate.

WHAT MAKES THIS INTERESTING RATHER THAN ADMIN
----------------------------------------------
Most of the feed is noise: minor-league assignments, workout-group paperwork,
organisational shuffling. Roughly a quarter of rows touch a major-league club at
all. Inside that quarter sits the material that moves games and prices --
a third baseman placed on the injured list, a closer activated, a starter
recalled to make tonight's start.

The filter is therefore aggressive on purpose, and every dropped row is dropped
by a rule that can be read rather than by a threshold that was tuned.

POINT-IN-TIME BY CONSTRUCTION
-----------------------------
Every transaction carries its own date, and nothing is stored without one. A
cutoff is then a filter over rows, not a promise about an endpoint's behaviour
-- which is exactly the property the stats endpoints turned out not to have.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

from src.data import parks
from src.pipeline import slate as slate_mod

# The thirty major-league clubs by MLB's own team id, from
# /api/v1/teams?sportId=1. Stable identifiers, and the only reliable way to tell
# a parent club from an affiliate that shares its nickname.
MLB_TEAM_IDS = {
    108: "LAA", 109: "AZ", 110: "BAL", 111: "BOS", 112: "CHC", 113: "CIN",
    114: "CLE", 115: "COL", 116: "DET", 117: "HOU", 118: "KC", 119: "LAD",
    120: "WSH", 121: "NYM", 133: "ATH", 134: "PIT", 135: "SD", 136: "SEA",
    137: "SF", 138: "STL", 139: "TB", 140: "TEX", 141: "TOR", 142: "MIN",
    143: "PHI", 144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}

API_HOST = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "aisportsanalysis/1.0"
DEFAULT_TIMEOUT = 30

# The categories worth a bettor's attention, mapped from MLB's own typeDesc plus
# the wording of the description. MLB files injured-list moves under the generic
# "Status Change", so the type alone cannot separate a player going ON the IL
# from one coming OFF it, and those are opposite facts about a team.
IL_PLACEMENT = "il_placement"
IL_ACTIVATION = "il_activation"
IL_TRANSFER = "il_transfer"
RECALLED = "recalled"
OPTIONED = "optioned"
DESIGNATED = "designated"
TRADED = "traded"
SIGNED = "signed"
REHAB = "rehab"
OTHER = "other"

# Categories that say something about who is available tonight. The rest are
# stored but never surfaced -- kept because a category we ignore today may
# matter to a hypothesis tomorrow, and re-fetching history is wasted work.
NOTABLE = (IL_PLACEMENT, IL_ACTIVATION, IL_TRANSFER, RECALLED, OPTIONED,
           DESIGNATED, TRADED)


class NewsError(RuntimeError):
    """Raised when the transactions feed cannot be read."""


def _get_json(path, params, timeout=DEFAULT_TIMEOUT):
    url = f"{API_HOST}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise NewsError(f"MLB transactions returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise NewsError(f"could not reach MLB transactions: {exc.reason}") from None
    except json.JSONDecodeError:
        raise NewsError("MLB transactions returned invalid JSON") from None


def classify(transaction) -> str:
    """What kind of move this is, from the type and the sentence MLB wrote.

    The description is consulted because "Status Change" covers both directions
    of an injured-list move. Reading the verb is not elegant, but MLB's own
    wording is consistent and the alternative is treating a player going on the
    IL as identical to one coming off it.
    """
    type_desc = (transaction.get("typeDesc") or "").strip().lower()
    text = (transaction.get("description") or "").lower()

    if "rehab assignment" in text:
        return REHAB
    if type_desc == "status change":
        if "transferred" in text and "injured list" in text:
            return IL_TRANSFER
        if "activated" in text or "reinstated" in text:
            return IL_ACTIVATION
        if "placed" in text and ("injured list" in text or "il" in text):
            return IL_PLACEMENT
        return OTHER
    return {
        "recalled": RECALLED,
        "optioned": OPTIONED,
        "designated for assignment": DESIGNATED,
        "trade": TRADED,
        "signed as free agent": SIGNED,
    }.get(type_desc, OTHER)


def _club(team) -> str:
    """Abbreviation for a major-league club, or None for anything else.

    Filtered by TEAM ID, not by name. Name matching looked like it worked and
    quietly let affiliates through: the Fredericksburg Nationals, Syracuse Mets,
    Iowa Cubs and Dunedin Blue Jays all end in their parent club's nickname, so
    a suffix match files a Single-A development-list move under a major-league
    team. MLB's ids are stable and unambiguous, and the fallback to name
    matching only runs when an id is absent.
    """
    team = team or {}
    identifier = team.get("id")
    if identifier in MLB_TEAM_IDS:
        return parks.canonical_team(MLB_TEAM_IDS[identifier])
    if identifier is not None:
        # A known id that is not a major-league club is a definite no, not a
        # reason to go guessing at the name.
        return None
    name = team.get("name")
    return slate_mod.team_abbrev_from_name(name) if name else None


def _injury_note(text) -> str:
    """The trailing injury phrase MLB appends, when there is one.

    "... on the 10-day injured list retroactive to August 27, 2026. Left groin
    strain." The last sentence is the diagnosis, and it is the part a reader
    actually wants.
    """
    parts = [p.strip() for p in (text or "").split(".") if p.strip()]
    if len(parts) < 2:
        return None
    tail = parts[-1]
    # A trailing fragment that is really the end of the sentence rather than a
    # diagnosis -- "retroactive to August 27, 2026" -- is not a note.
    if any(word in tail.lower() for word in ("retroactive", "assigned", "list")):
        return None
    return tail if len(tail) <= 120 else None


def parse(transaction) -> dict:
    """One feed row as a stored record, or None if it touches no major-league club."""
    to_club = _club(transaction.get("toTeam"))
    from_club = _club(transaction.get("fromTeam"))
    if to_club is None and from_club is None:
        return None

    date = transaction.get("effectiveDate") or transaction.get("date")
    if not date:
        # Undated news cannot be used point-in-time and is worse than absent,
        # because it would silently be treated as known on every date.
        return None

    person = transaction.get("person") or {}
    description = transaction.get("description") or ""
    return {
        "transaction_id": transaction.get("id"),
        "date": date,
        "filed_date": transaction.get("date"),
        "category": classify(transaction),
        "type_desc": transaction.get("typeDesc"),
        "player_id": person.get("id"),
        "player": person.get("fullName"),
        "to_team": to_club,
        "from_team": from_club,
        # The club the move is ABOUT. A player placed on the IL has no toTeam
        # in some rows and no fromTeam in others; the reader wants one answer.
        "team": to_club or from_club,
        "description": description,
        "injury_note": _injury_note(description),
    }


def fetch(start_date, end_date=None, timeout=DEFAULT_TIMEOUT) -> list:
    """Major-league transactions over a date range, oldest first.

    Dates are inclusive and ISO-formatted. A range with no transactions is an
    empty list, not an error -- the off-season is quiet and that is not a fault.
    """
    start = _iso(start_date)
    end = _iso(end_date or start_date)
    payload = _get_json("transactions",
                        {"startDate": start, "endDate": end}, timeout)
    rows = []
    for transaction in payload.get("transactions") or []:
        record = parse(transaction)
        if record is not None:
            rows.append(record)
    rows.sort(key=lambda r: (r["date"], r["transaction_id"] or 0))
    return rows


def _iso(value) -> str:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    return str(value)
