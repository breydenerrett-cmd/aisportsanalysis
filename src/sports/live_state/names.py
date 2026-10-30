"""Name folding and the "is this the same game" rules for the live game state.

WHY THIS IS NOT JUST ``live_scores.teams_match``
-------------------------------------------------
The grader's matcher (``src/hounds/live_scores.py``) compares two TEAM names after folding accents, "Los Angeles" to
"LA", "Saint" to "St" and dropping a club suffix. This module reuses it unchanged and adds only what the NHL needs on
top: the Stats API names a club by two fields (``placeName`` + ``commonName``: "Montréal" + "Canadiens") and the odds
feed by one string ("Montreal Canadiens", "St Louis Blues", "NY Rangers", "Utah Hockey Club" last season and "Utah
Mammoth" now), and a three letter abbreviation is accepted when the caller sent one.

THE STRICTNESS IS THE GRADER'S (every doubt is a non-answer)
-------------------------------------------------------------
  * BOTH names must agree, in the SAME orientation (home with home). A neutral-site game the two vendors list the other
    way round is not matched and never flipped;
  * exactly ONE candidate may fit; two (a doubleheader, a name two teams share) means no answer;
  * the candidate's scheduled start must be within a window of the caller's start.

TENNIS IS THE ONE PLACE ORIENTATION IS NOT REQUIRED. Tennis has no home side: The Odds API lists a match "home, away" in
whatever order the book sent and ESPN lists it by its own ``order`` (src/research/live_tennis/state.py ``orient``). A
player is identified by NAME, so the two names are matched as a pair in either order, the answer is laid out in the
CALLER'S order, and a pair that fits both ways (two identical names) or neither way is no answer.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from typing import Mapping, Optional

from src.hounds import live_scores as ls

#: How far apart the caller's start and the vendor's scheduled start may be and still be one NHL game. The grader's own
#: 12 hours (``live_scores.MATCH_WINDOW``): well under a day, so a playoff series' next game is never this game.
NHL_WINDOW = ls.MATCH_WINDOW
#: A tennis match is played in order of play ("followed by" the match before it), so the listed start can be many hours
#: before the first ball. The pair of NAMES is what identifies a match; the window only rules out another week's meeting.
TENNIS_WINDOW = timedelta(hours=18)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# After ``ls.norm_team``: shorthand the odds feed and the NHL both use for the same club.
_NHL_PREFIX_ALIASES = (("ny ", "new york "), ("nj ", "new jersey "), ("tb ", "tampa bay "), ("sj ", "san jose "))
_NHL_WHOLE_ALIASES = {"utah hockey club": "utah mammoth", "utah hc": "utah mammoth"}


def fold_text(value: Optional[str]) -> str:
    """Lower case, accents dropped, every run of non-letters/digits one space: "Liñana" -> "linana", "Herrero-Linana" -> "herrero linana"."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return _NON_ALNUM.sub(" ", text).strip()


def nhl_fold(name: Optional[str]) -> str:
    text = ls.norm_team(name)
    for old, new in _NHL_PREFIX_ALIASES:
        if text.startswith(old):
            text = new + text[len(old):]
            break
    return _NHL_WHOLE_ALIASES.get(text, text)


def nhl_team_matches(name: Optional[str], team: Mapping) -> bool:
    """Does the caller's `name` name this NHL club? `team` carries ``abbrev`` and, when known, ``name`` (the full
    "San Jose Sharks"). An unknown full name never matches by name; a 2-4 letter token matches the abbreviation only."""
    text = str(name or "").strip()
    if not text:
        return False
    abbrev = str(team.get("abbrev") or "").strip().upper()
    if abbrev and text.upper() == abbrev:
        return True
    full = team.get("name")
    if not full:
        return False
    a, b = nhl_fold(text), nhl_fold(full)
    return bool(a) and a == b


def same_player(a: Optional[str], b: Optional[str]) -> bool:
    x, y = fold_text(a), fold_text(b)
    return bool(x) and x == y


def within(start_a: Optional[datetime], start_b: Optional[datetime], window: timedelta) -> bool:
    """Both starts known and inside the window. A candidate with no start can never be matched: the window is half the rule."""
    if start_a is None or start_b is None:
        return False
    return abs(start_a - start_b) <= window


def last_word_name(name: Optional[str]) -> str:
    """"Maya Joint" -> "Joint", "Alicia Herrero Linana" -> "Herrero Linana": the name minus the first token, for a one-line label."""
    parts = str(name or "").split()
    if not parts:
        return ""
    return " ".join(parts[1:]) if len(parts) > 1 else parts[0]
