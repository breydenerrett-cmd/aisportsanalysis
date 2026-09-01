"""Settle saved bets (src.appstate.savedbets) against real final results.

WHY THIS IS SEPARATE FROM src/appstate/savedbets.py
-----------------------------------------------------
savedbets.py owns the saved_bets table -- the schema, the single write path
into settlement_status (mark_settled), the read paths (list_bets,
list_unsettled_bets). This module owns none of that storage; it only knows
how to GRADE a bet against a results store and drive savedbets' write path.
That split means a change to how sqlite is touched never has to touch the
grading rules, and vice versa.

WHY GRADING NEVER GUESSES
---------------------------
A saved bet's `game` and `side` are free text a client typed or copied
(api/mybets.py's SaveBetRequest docstring) -- there is no guarantee they
parse cleanly, and no separate "game date" field was added by this task
(POST /my-bets is explicitly unchanged). Every step below that cannot reach
a confident verdict returns `unsettled` with a stated reason instead of
picking the more likely of two readings. The one exception is deriving a
game's date from `saved_at`: Bet Check only ever checks today's slate, so
the date a bet was saved is the date of the game it names in the real
product flow. That is a stand-in for a missing field, not a guess about
which of several games -- the away/home clubs must still match a stored
result on that exact date, or the bet stays unsettled.

WHY moneyline SIDE ONLY, NO PROFIT
------------------------------------
grade_bet answers one question: did the named side win the game. It never
computes a payout in dollars from `price` -- there is no bet-placement or
bankroll feature in this codebase, and adding profit math here would be
building half of one. See docs/LAUNCH_DECISIONS.md and CLAUDE.md's banned-
vocabulary rule.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable, Optional, Union

from src.appstate import savedbets

# `results` is whatever src.pipeline.history.read_results() returns: a dict
# keyed by game_pk, each value carrying at least date/away_team/home_team
# (club abbreviations, see src/providers/mlb.py's _team_abbrev)/away_score/
# home_score/home_won. Typed loosely here on purpose -- this module must not
# import src.pipeline.history to get a real type, since src/pipeline is the
# research side and src/appstate is the product side (module docstring).
ResultsStore = dict
# A caller may pass the dict itself, or a zero-arg callable that produces it
# lazily (e.g. history.read_results) -- see _resolve_results.
StoreReader = Union[ResultsStore, Callable[[], ResultsStore]]

# A side naming a club is allowed one trailing "ML"/"moneyline" marker
# (case-insensitive, arbitrary surrounding space) -- that is the only shape
# tests/test_api_mybets.py exercises today ("BOS ML"). Anything else that
# is not the bare literal "home"/"away" is graded as void-unmatchable rather
# than stripped further, so a typo'd suffix never silently resolves.
_ML_SUFFIX_RE = re.compile(r"\s*(ML|MONEYLINE)\s*$", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_results(store_reader: StoreReader) -> ResultsStore:
    return store_reader() if callable(store_reader) else store_reader


def _split_game(game: str) -> Optional[tuple]:
    """An "AWAY@HOME" saved-bet game string -> (away_abbrev, home_abbrev),
    or None if it isn't in that shape. Every saved game string this codebase
    writes today follows it (tests/test_api_mybets.py), but nothing stops a
    client sending arbitrary text through SaveBetRequest.game -- a string
    this function cannot parse is reported unsettled, never guessed at.
    """
    if not game or game.count("@") != 1:
        return None
    away, home = (part.strip() for part in game.split("@", 1))
    if not away or not home:
        return None
    return away, home


def _game_date(bet: savedbets.SavedBet) -> str:
    """See the module docstring's note on deriving a game's date from
    saved_at -- there is no other date on a saved bet to use."""
    return (bet.saved_at or "")[:10]


def _find_results(results: ResultsStore, game_date: str,
                  away_abbrev: str, home_abbrev: str) -> list:
    """Every stored result for this date and exact club pairing.

    Zero means no final game matched this date+pair (not yet played,
    postponed, or the bet named a club pair that never played that day).
    More than one means a doubleheader -- the free-text `game` field has no
    game_number to disambiguate the way GET /game/{date}/{away}/{home}'s
    URL scheme does, so both cases are left to the caller to report as
    unmatched rather than this function picking one game to grade against.
    """
    away_u, home_u = away_abbrev.upper(), home_abbrev.upper()
    return [row for row in results.values()
            if row.get("date") == game_date
            and (row.get("away_team") or "").upper() == away_u
            and (row.get("home_team") or "").upper() == home_u]


def _resolve_side(side: str, away_abbrev: str, home_abbrev: str) -> Optional[str]:
    """A saved bet's free-text `side` -> "away" or "home", or None if it
    names neither club (a typo, a different club's abbreviation, a spread
    or total instead of a moneyline pick -- all of these are "cannot tell",
    never "probably meant X"). Case-insensitive throughout, matching how
    src.analysis.gamepayload.find_entries already treats club abbreviations
    as case-insensitive tokens.
    """
    normalized = (side or "").strip().upper()
    if normalized == "HOME":
        return "home"
    if normalized == "AWAY":
        return "away"
    club = _ML_SUFFIX_RE.sub("", normalized).strip()
    if club == away_abbrev.upper():
        return "away"
    if club == home_abbrev.upper():
        return "home"
    return None


def _is_tie(game: dict) -> bool:
    """True only when both scores are present and equal. MLB ties are rare
    (a suspended, never-resumed game) but real, and a moneyline bet on one
    is a push, not a loss -- silently grading it as a loss would be exactly
    the kind of guess this module exists to refuse.
    """
    away_score, home_score = game.get("away_score"), game.get("home_score")
    if away_score in (None, "") or home_score in (None, ""):
        return False
    return int(float(away_score)) == int(float(home_score))


def grade_bet(bet: savedbets.SavedBet, results: ResultsStore) -> dict:
    """Grade one saved bet against the results store.

    Returns {"outcome": ...} where outcome is one of savedbets'
    SETTLEMENT_STATUSES, or "unsettled" (with a "reason") when no confident
    verdict is reachable yet or at all. Pure and read-only: never touches
    the database or mutates `bet` -- settle_saved_bets is the only writer.
    """
    parsed = _split_game(bet.game)
    if parsed is None:
        return {"outcome": "unsettled",
                "reason": f"game {bet.game!r} is not in AWAY@HOME form"}
    away_abbrev, home_abbrev = parsed

    game_date = _game_date(bet)
    matches = _find_results(results, game_date, away_abbrev, home_abbrev)
    if not matches:
        return {"outcome": "unsettled",
                "reason": f"no final result for {bet.game} on {game_date}"}
    if len(matches) > 1:
        return {"outcome": "unsettled",
                "reason": (f"{len(matches)} final results matched {bet.game} "
                          f"on {game_date} (doubleheader) -- cannot "
                          "disambiguate which game this bet was on")}

    game = matches[0]
    if _is_tie(game):
        return {"outcome": "push",
                "reason": "game ended tied (suspended, never resumed)"}

    home_won = game.get("home_won")
    if home_won in (None, ""):
        return {"outcome": "unsettled", "reason": "game has no decided winner"}
    home_won = bool(int(home_won))

    side = _resolve_side(bet.side, away_abbrev, home_abbrev)
    if side is None:
        return {"outcome": "void-unmatchable",
                "reason": (f"side {bet.side!r} does not name either club "
                          f"in {bet.game}")}

    side_won = home_won if side == "home" else not home_won
    return {"outcome": "won" if side_won else "lost"}


def settle_saved_bets(store_reader: StoreReader, *, db=None, now=None) -> dict:
    """Grade every unsettled saved bet (all users) and persist verdicts.

    Idempotent and safe to call on every daily run: list_unsettled_bets only
    ever returns rows with settlement_status IS NULL, and mark_settled's
    WHERE clause repeats that guard at the write, so a bet already settled
    on a previous run is never re-touched. A bet that stays unsettled this
    run (game not final yet, unparseable text) is simply left as-is for the
    next run to try again -- its reason is reported here for visibility,
    not written to the row, since "why not yet" is not itself a verdict.
    """
    results = _resolve_results(store_reader)
    settled_at = now or _now_iso()

    counts = {"won": 0, "lost": 0, "push": 0, "void_unmatchable": 0}
    unsettled = []

    for bet in savedbets.list_unsettled_bets(db=db):
        verdict = grade_bet(bet, results)
        outcome = verdict["outcome"]
        if outcome == "unsettled":
            unsettled.append({"id": bet.id, "game": bet.game,
                              "reason": verdict["reason"]})
            continue
        savedbets.mark_settled(bet.id, outcome, reason=verdict.get("reason"),
                               settled_at=settled_at, db=db)
        counts[outcome.replace("-", "_")] += 1

    return {
        "settled": sum(counts.values()),
        "unsettled": len(unsettled),
        "counts": counts,
        "unsettled_detail": unsettled,
    }


def settle_saved_bets_if_app_db_exists(store_reader: StoreReader, *, db=None,
                                       now=None) -> dict:
    """The daily-loop hook: settle My Bets, unless there is no app db to
    settle against.

    src/pipeline is the research side and must never create the product
    database as a side effect of running -- savedbets._connect() would
    happily CREATE app.db on first touch, which is exactly backwards for a
    research run on a machine that has never served the API. Checking
    existence first, and returning cleanly instead of calling into
    savedbets at all when it is absent, keeps that dependency one-way: the
    product db can be settled from the daily loop when it exists, but the
    daily loop never brings it into existence.
    """
    resolved_db = db or savedbets.db_path()
    if not resolved_db.exists():
        return {"skipped": True, "reason": f"no app db at {resolved_db}"}
    return settle_saved_bets(store_reader, db=resolved_db, now=now)
