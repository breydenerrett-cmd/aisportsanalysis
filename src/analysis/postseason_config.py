"""2026 MLB postseason format and calendar, recorded from verification.

WHAT THIS FILE IS
------------------
Pure configuration: no series or bracket math lives here (that is
src/analysis/postseason.py) and no real "these are this year's contenders"
seeding is hardcoded here either -- a bracket is always supplied by whoever
calls postseason.py's engine, as data, never assumed by this module.

THE CALENDAR
------------
Adopted from docs/SEASON_END_PLAN.md:9-17 without re-deriving it -- that
document verified these dates live against the MLB schedule endpoint
(statsapi.mlb.com/api/v1/schedule) on 2026-08-31. Not re-checked here.

THE FORMAT, VERIFIED HERE, 2026-09-24
--------------------------------------
Team counts, byes, best-of length, the home/away pattern per round, who
holds home-field advantage in each round, and the Division Series matchup
rule were verified live during this task against:

  https://www.mlb.com/news/mlb-playoff-format-faq
  https://www.mlb.com/news/2026-mlb-playoff-and-world-series-schedule

plus one corroborating web search for the Division Series pairing rule
specifically (cross-checked against en.wikipedia.org's "American League
Division Series" / "Wild Card Series" articles and independent 2026
bracket-preview pages, since the primary FAQ page's wording on re-seeding
was easy to misread). See FORMAT_VERIFICATION at the bottom of this file for
the retrieval date, sources, and the exact facts extracted -- kept next to
the constants it justifies so the two cannot drift apart silently.

TWO THINGS THIS VERIFICATION CHANGED FROM WHAT MIGHT HAVE BEEN ASSUMED
-------------------------------------------------------------------------
1. World Series home-field advantage is NOT seed-based. Wild Card, Division
   Series and LCS all give it to the better seed; the World Series gives it
   to whichever pennant winner has the better REGULAR-SEASON record,
   independent of postseason seeding (true since 2017; it replaced the
   2003-2016 rule where the All-Star Game winner's league got it). An
   AL-seed-vs-NL-seed number comparison is not even meaningful here, since
   the two teams are from different leagues -- this file encodes that as a
   per-round `home_field_by` of "seed" or "record" specifically so the
   bracket engine cannot apply the wrong rule to the World Series by
   accident.
2. The Division Series bracket is NOT re-seeded after the Wild Card round.
   Seed 1 always plays the winner of the 4-vs-5 Wild Card series and seed 2
   always plays the winner of the 3-vs-6 Wild Card series, even when that
   means the No. 1 seed draws a team that finished with a better record
   than the other Wild Card winner would have. This was a plausible enough
   assumption to get wrong silently, which is exactly why it was checked
   against the source instead of assumed.

WHAT IS STILL UNKNOWN / OUT OF SCOPE HERE
-------------------------------------------
* MLB's real World Series home-field tiebreak when both pennant winners
  have an EXACTLY equal regular-season win percentage (head-to-head, then
  each team's own-division record, then intraleague record) needs data
  this file does not model (a specific opponent-vs-opponent split, not just
  a season win total). `postseason.py`'s `_home_field_holder` raises rather
  than guessing if this happens; it is not expected to happen often, and no
  attempt is made here to estimate how often.
* The within-league seeding tiebreak (head-to-head record first, among
  teams tied on regular-season win percentage) is out of scope: this module
  takes each league's 1-6 seeding as a given input, never computes it.

NO PREDICTIVE CLAIM. This file records a published tournament STRUCTURE,
not an opinion about who wins it.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Calendar -- adopted from docs/SEASON_END_PLAN.md:9-17 (verified live
# against statsapi.mlb.com/api/v1/schedule, 2026-08-31). Not re-verified
# here; see that document for the retrieval detail. `game_type` values match
# src/providers/mlb.py's gameType codes (cross-checked, not imported, to
# keep this module dependency-free -- see
# tests/test_postseason_config.py::GameTypeCodesMatchProviderTests).
# ---------------------------------------------------------------------------

REGULAR_SEASON_ENDS = "2026-09-27"

CALENDAR = {
    "wild_card": {"start": "2026-09-29", "end": "2026-10-01", "game_type": "F"},
    "division_series": {"start": "2026-10-03", "end": "2026-10-10", "game_type": "D"},
    "lcs": {"start": "2026-10-11", "end": "2026-10-20", "game_type": "L"},
    "world_series": {"start": "2026-10-23", "end": "2026-10-31", "game_type": "W"},
}

CALENDAR_ROUNDS_IN_ORDER = ("wild_card", "division_series", "lcs", "world_series")


# ---------------------------------------------------------------------------
# Field structure -- verified 2026-09-24, see FORMAT_VERIFICATION below.
# ---------------------------------------------------------------------------

TEAMS_PER_LEAGUE = 6
LEAGUES = ("AL", "NL")
BYE_SEEDS = (1, 2)
FIELD_SEEDS = (1, 2, 3, 4, 5, 6)

# Fixed pairing for the Wild Card round: seed 3 hosts seed 6, seed 4 hosts
# seed 5. Keyed by name (not tuple position) so downstream code cannot
# silently transpose "3v6" and "4v5" -- see postseason.py's use of
# WILD_CARD_SERIES_KEYS / DS_OPPONENT_SERIES_FOR_SEED.
WILD_CARD_SERIES_KEYS = ("3v6", "4v5")
WILD_CARD_PAIRINGS = {"3v6": (3, 6), "4v5": (4, 5)}

# Fixed Division Series bracket, NOT re-seeded after Wild Card results
# (verified -- see module docstring). Seed 1 always plays the "4v5" Wild
# Card series' winner; seed 2 always plays the "3v6" series' winner.
DS_OPPONENT_SERIES_FOR_SEED = {1: "4v5", 2: "3v6"}

HOME_FIELD_BY_SEED = "seed"        # lower seed number hosts
HOME_FIELD_BY_RECORD = "record"    # better regular-season win_pct hosts


WILD_CARD = {
    "name": "Wild Card Series",
    "game_type": "F",
    "best_of": 3,
    "k": 2,
    # Verified: ALL games hosted by the higher (numerically lower) seed.
    "home_pattern": (True, True, True),
    "home_field_by": HOME_FIELD_BY_SEED,
}

DIVISION_SERIES = {
    "name": "Division Series",
    "game_type": "D",
    "best_of": 5,
    "k": 3,
    # Verified: 2-2-1, higher seed hosts games 1, 2, 5.
    "home_pattern": (True, True, False, False, True),
    "home_field_by": HOME_FIELD_BY_SEED,
}

LCS = {
    "name": "League Championship Series",
    "game_type": "L",
    "best_of": 7,
    "k": 4,
    # Verified: 2-3-2, higher seed hosts games 1, 2, 6, 7.
    "home_pattern": (True, True, False, False, False, True, True),
    "home_field_by": HOME_FIELD_BY_SEED,
}

WORLD_SERIES = {
    "name": "World Series",
    "game_type": "W",
    "best_of": 7,
    "k": 4,
    # Verified: 2-3-2 SHAPE is the same as the LCS, but home field within
    # that shape is decided differently -- see home_field_by below.
    "home_pattern": (True, True, False, False, False, True, True),
    "home_field_by": HOME_FIELD_BY_RECORD,  # NOT seed -- see module docstring
}

ROUNDS_IN_ORDER = (WILD_CARD, DIVISION_SERIES, LCS, WORLD_SERIES)


FORMAT_VERIFICATION = {
    "retrieved": "2026-09-24",
    "sources": (
        "https://www.mlb.com/news/mlb-playoff-format-faq",
        "https://www.mlb.com/news/2026-mlb-playoff-and-world-series-schedule",
    ),
    "corroborating_check": (
        "web search cross-checking the Division Series pairing/re-seeding "
        "question against en.wikipedia.org's 'American League Division "
        "Series' and 'Wild Card Series' articles and independent 2026 "
        "bracket-preview pages, 2026-09-24"
    ),
    "facts": {
        "teams": "12 total, 6 per league: 3 division winners + 3 wild cards, seeded 1-6",
        "byes": "seeds 1 and 2 in each league bypass the Wild Card round",
        "wild_card_pairing": "fixed: seed 3 vs seed 6, seed 4 vs seed 5",
        "wild_card_format": "best-of-3, ALL games hosted by the higher (numerically lower) seed",
        "division_series_pairing": (
            "FIXED, NOT re-seeded after Wild Card results: seed 1 always "
            "plays the winner of the 4-vs-5 series; seed 2 always plays "
            "the winner of the 3-vs-6 series, regardless of which team "
            "actually wins its Wild Card series"
        ),
        "division_series_format": "best-of-5, 2-2-1, higher seed hosts games 1, 2, 5",
        "lcs_format": "best-of-7, 2-3-2, higher seed hosts games 1, 2, 6, 7",
        "world_series_format": "best-of-7, 2-3-2",
        "world_series_home_field": (
            "the team with the BETTER REGULAR-SEASON RECORD hosts games "
            "1, 2, 6, 7 -- NOT the better postseason seed. In effect since "
            "2017 (replaced the All-Star-Game-decides-it rule used "
            "2003-2016)."
        ),
        "world_series_tiebreak_if_records_equal": (
            "head-to-head record between the two teams, then each team's "
            "own-division record, then intraleague record -- NOT modelled "
            "by this file or by postseason.py; the bracket engine raises "
            "PostseasonError rather than guessing if it happens"
        ),
        "seeding_tiebreak_within_a_league": (
            "head-to-head record is the first tiebreaker among teams tied "
            "on regular-season win percentage when seeds are assigned -- "
            "out of scope here, since this module takes each league's "
            "1-6 seeding as a given input and never computes it"
        ),
    },
    "still_unknown": (
        "No source read during this verification gave exact off-day "
        "placement within a round beyond the date ranges "
        "docs/SEASON_END_PLAN.md already records; the bracket engine does "
        "not need it and none is claimed here."
    ),
}
