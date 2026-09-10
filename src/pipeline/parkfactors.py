"""Park run factors, derived point-in-time from finished games.

WHY THIS EXISTS
---------------
`src.analysis.strength` prices Coors Field exactly like Petco Park. Both are
"a game", the run means come from team rates and starters, and the venue
never enters the arithmetic at all. `docs/THE_CARD.md` has listed park among
the known omissions since the file existed, and `src/data/parks.py` has
carried each venue's altitude and roof the whole time without anything using
them to price a run.

THE NAIVE VERSION IS WRONG AND IS NOT WHAT THIS DOES
-----------------------------------------------------
The obvious factor is "runs per game at this venue over the league average".
It is confounded by WHO PLAYS THERE: the Rockies bat in 81 games at Coors,
so a venue factor built that way is part park and part the home club's own
offence, and applying it to a model that already knows the home club's
offence counts the same thing twice.

The standard correction, and the one here, is the one Bill James described:
compare a club's own games AT HOME with its own games ON THE ROAD. The same
roster appears in both, so what is left is the venue.

    factor = (runs per game in the club's home games)
           / (runs per game in the club's road games)

Both sides count BOTH clubs' runs, because a park inflates or suppresses
scoring for everyone in it.

REGRESSED HARD, ON PURPOSE
---------------------------
A season gives about 70 home games per park, and a raw factor on 70 games is
mostly noise -- the year-to-year correlation of unregressed single-season
park factors is famously poor. `PRIOR_GAMES` pulls every factor toward 1.0
over 150 imaginary games at neutral, so a full season earns roughly a third
of its raw signal and an April park is barely moved from neutral at all.

150 is fixed here in advance and is not tuned against any result. It is
deliberately conservative: an over-regressed park factor is a small missed
opportunity, an under-regressed one actively injects noise into every game
at that venue.

POINT-IN-TIME BY CONSTRUCTION
-----------------------------
`park_factors(store, as_of_date)` counts only games that finished strictly
before `as_of_date`. A game on the cutoff is the game being predicted and
its own runs are not available to predict it.

Pure. stdlib only, reads nothing -- the caller supplies the store.
"""

from __future__ import annotations

from typing import Mapping, Optional

# Imaginary neutral games mixed into every club's split. See the module
# docstring for why this is large and why it is not tuned.
PRIOR_GAMES = 150.0

# A factor may not leave this band whatever the data says. Coors sits near
# 1.15 in a normal season and nothing legitimate reaches 1.5; a value
# outside this is a data fault, and clamping is preferable to letting one
# venue's corrupt rows move every game played there.
MIN_FACTOR = 0.80
MAX_FACTOR = 1.25

# Below this many home games a club's split is not worth computing at all
# and the answer is neutral. Distinct from the regression: this is "we have
# essentially nothing", not "we have a little".
MIN_HOME_GAMES = 10


def _int(value) -> Optional[int]:
    """Coerce, never isinstance. The results store round-trips through CSV
    and keeps scores as strings -- an isinstance(int) guard here would count
    zero games out of two thousand, which is exactly the fault that made
    `card_ledger.grade_pick` void every pick on 2026-09-10."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def park_factors(store: Mapping, as_of_date: str, *,
                 prior_games: float = PRIOR_GAMES) -> dict:
    """`{team: factor}` -- the run multiplier for that club's home park.

    Keyed by the HOME CLUB rather than by venue name, because that is what a
    slate entry carries and because a venue string can change spelling
    between feeds while a club abbreviation does not.

    A club with too few home games comes back at exactly 1.0 with
    `thin: True`, never absent, so a caller can tell "neutral because we
    measured neutral" from "neutral because we know nothing".
    """
    cutoff = str(as_of_date)
    home_runs, home_games = {}, {}
    away_runs, away_games = {}, {}

    for row in (store or {}).values():
        date = str(row.get("date") or "")
        if not date or date >= cutoff:
            continue
        away_score = _int(row.get("away_score"))
        home_score = _int(row.get("home_score"))
        if away_score is None or home_score is None:
            continue
        total = away_score + home_score
        home = row.get("home_team")
        away = row.get("away_team")
        if home:
            home_runs[home] = home_runs.get(home, 0) + total
            home_games[home] = home_games.get(home, 0) + 1
        if away:
            away_runs[away] = away_runs.get(away, 0) + total
            away_games[away] = away_games.get(away, 0) + 1

    out = {}
    for team in set(home_games) | set(away_games):
        hg = home_games.get(team, 0)
        ag = away_games.get(team, 0)
        if hg < MIN_HOME_GAMES or ag < MIN_HOME_GAMES:
            out[team] = {"team": team, "factor": 1.0, "thin": True,
                         "home_games": hg, "away_games": ag,
                         "raw_factor": None}
            continue
        home_rate = home_runs[team] / hg
        away_rate = away_runs[team] / ag
        if away_rate <= 0:
            out[team] = {"team": team, "factor": 1.0, "thin": True,
                         "home_games": hg, "away_games": ag,
                         "raw_factor": None}
            continue

        raw = home_rate / away_rate
        # Regressed toward neutral by `prior_games` imaginary games at 1.0,
        # weighted by the smaller of the two samples -- a club with 70 home
        # games and 8 road games has learned almost nothing.
        weight = float(min(hg, ag))
        factor = (raw * weight + 1.0 * prior_games) / (weight + prior_games)
        factor = min(max(factor, MIN_FACTOR), MAX_FACTOR)
        out[team] = {
            "team": team,
            "factor": round(factor, 4),
            "raw_factor": round(raw, 4),
            "home_games": hg,
            "away_games": ag,
            "thin": weight < prior_games / 3.0,
        }
    return out


def factor_for(factors: Mapping, home_team: str) -> float:
    """One club's factor, or 1.0. Never raises -- a game at an unknown park
    is priced neutrally rather than dropped."""
    row = (factors or {}).get(home_team)
    if not isinstance(row, Mapping):
        return 1.0
    value = row.get("factor")
    try:
        return float(value) if value else 1.0
    except (TypeError, ValueError):
        return 1.0
