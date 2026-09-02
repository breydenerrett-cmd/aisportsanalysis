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

WHY THE CLOSING PRICE REUSES THE GRADING-PATH PRIMITIVES
-----------------------------------------------------------
src/pipeline/grading.py already has a fully-built, tested closing-line
computer for the internal research ledger: `_find_series` (which
canonicalises club names via src.data.parks.canonical_team -- the odds
feed's snapshot rows carry full provider names like "Boston Red Sox"
while a saved bet's `game` carries this codebase's abbreviations, and
matching them wrong would attach another game's closing price) and
`_index_snapshots`. `compute_closing_price` below calls those two
directly, then finishes with src.pipeline.snapshots.closing_observation/
closing_line_value -- the exact same "last observation strictly before
first pitch" definition the forward ledger's CLV uses. Re-deriving any of
that here instead of calling it would risk a saved bet's closing price and
the research ledger's CLV quietly disagreeing about which snapshot was
the close, for the same game, computed twice.

VOCABULARY: THIS IS "CLOSING PRICE", NEVER "CLV"
----------------------------------------------------
The research ledger's internal metric is allowed to say CLV -- it is
read by nobody but this codebase's own validation process. A customer
never sees that word: docs/API_CONTRACTS.md's rule (restated in
design/linehound-v2/RECONCILED_CONTRACT_CURRENT_HEAD.md) calls this
"closing price" / "price vs close", and price_vs_close_cents is the one
number this module exposes -- a plain difference in American-odds cents,
never called an edge or expected value.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable, Optional, Union

from src.appstate import savedbets
from src.core import odds as odds_math
from src.pipeline import grading as grading_mod
from src.pipeline import snapshots as snapshots_mod

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


# Returned by compute_closing_price on every path -- success leaves
# closing_reason None with the three value fields set; failure leaves the
# value fields None with closing_reason stating why. Always all four keys,
# never a partial dict, so a caller can splat it straight into
# savedbets.record_closing without checking which case it got.
_NO_CLOSING = {"closing_price": None, "closing_observed_utc": None,
              "price_vs_close_cents": None, "closing_reason": None}


def compute_closing_price(bet: savedbets.SavedBet, snapshot_rows) -> dict:
    """The closing-price facts for one saved bet, or an explicit reason
    there are none. See the module docstring's "WHY THE CLOSING PRICE
    REUSES THE GRADING-PATH PRIMITIVES" for why this calls into
    src.pipeline.grading/snapshots rather than re-deriving their logic.

    h2h ONLY: grading._index_snapshots groups the snapshot store by the
    h2h market (its own default), so a game with only spread/total rows in
    the store reports "no odds snapshots captured for this game", the same
    as no snapshots at all. A saved bet whose `game`/`side` cannot be
    pinned to one recognisable club-vs-club h2h pick -- unparseable game
    text, or a side naming neither club (a typo, or a spread/total pick
    instead of a moneyline one -- the same cases grade_bet refuses to
    guess at and settles void-unmatchable) -- is reported "market not
    captured": this only ever prices a plain moneyline pick, and there is
    no market field on a saved bet to say otherwise.

    Pure and read-only, like grade_bet: never touches the database.
    """
    parsed = _split_game(bet.game)
    if parsed is None:
        return {**_NO_CLOSING, "closing_reason": "market not captured"}
    away_abbrev, home_abbrev = parsed

    side = _resolve_side(bet.side, away_abbrev, home_abbrev)
    if side is None:
        return {**_NO_CLOSING, "closing_reason": "market not captured"}

    if bet.price is None:
        return {**_NO_CLOSING,
                "closing_reason": "no price recorded for this saved bet"}

    by_game = grading_mod._index_snapshots(snapshot_rows)
    series = grading_mod._find_series(by_game, away_abbrev, home_abbrev,
                                      _game_date(bet))
    if not series:
        return {**_NO_CLOSING,
                "closing_reason": "no odds snapshots captured for this game"}

    closing = snapshots_mod.closing_observation(series)
    if closing is None:
        return {**_NO_CLOSING,
                "closing_reason": "no snapshot taken before first pitch"}

    field = "home_price" if side == "home" else "away_price"
    closing_price = (closing.get("prices") or {}).get(field)
    if closing_price is None:
        return {**_NO_CLOSING, "closing_reason": f"closing snapshot has no {field}"}

    try:
        value = snapshots_mod.closing_line_value(bet.price, closing_price)
    except odds_math.OddsError as exc:
        return {**_NO_CLOSING, "closing_reason": f"unusable prices: {exc}"}

    return {
        "closing_price": closing_price,
        "closing_observed_utc": closing.get("observed_utc"),
        "price_vs_close_cents": value["cents"],
        "closing_reason": None,
    }


def settle_saved_bets(store_reader: StoreReader, *, db=None, now=None,
                      snapshot_rows=None) -> dict:
    """Grade every unsettled saved bet (all users) and persist verdicts.

    Idempotent and safe to call on every daily run: list_unsettled_bets only
    ever returns rows with settlement_status IS NULL, and mark_settled's
    WHERE clause repeats that guard at the write, so a bet already settled
    on a previous run is never re-touched. A bet that stays unsettled this
    run (game not final yet, unparseable text) is simply left as-is for the
    next run to try again -- its reason is reported here for visibility,
    not written to the row, since "why not yet" is not itself a verdict.

    Every bet settled THIS run -- won, lost, push, or void-unmatchable --
    also gets its closing-price fields computed and persisted in the same
    pass, via compute_closing_price/savedbets.record_closing. `snapshot_rows`
    is the odds-snapshot store (src.pipeline.snapshots' row shape); like
    `store_reader`, tests inject a small hermetic list, and a real caller
    passes the live src.pipeline.snapshots.read() -- there is no implicit
    default read of the production store here, the same explicit-injection
    pattern src.pipeline.grading.settle already uses for the identical
    parameter. This function never revisits a bet settled on an EARLIER
    run to add closing fields it did not have yet -- that would be
    settling rewriting an already-settled row, which the docstring above
    already rules out. backfill_closing_prices is the one-time catch-up
    for rows that predate this feature.
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
        closing = compute_closing_price(bet, snapshot_rows or [])
        savedbets.record_closing(bet.id, computed_at=settled_at, db=db, **closing)
        counts[outcome.replace("-", "_")] += 1

    return {
        "settled": sum(counts.values()),
        "unsettled": len(unsettled),
        "counts": counts,
        "unsettled_detail": unsettled,
    }


def backfill_closing_prices(snapshot_rows, *, db=None, now=None) -> dict:
    """Fill closing-price fields on already-settled bets that predate this
    feature -- the ONE-TIME catch-up settle_saved_bets deliberately does
    not do itself (its own docstring: settling never rewrites an
    already-settled row). Callable from the CLI as
    `python3 -m src.cli mybets-closing-backfill`.

    Idempotent: savedbets.list_settled_bets_missing_closing only returns
    rows whose closing computation has never been attempted
    (closing_computed_at IS NULL), and savedbets.record_closing's own WHERE
    clause repeats that guard at the write -- so running this twice, or
    running it concurrently with settle_saved_bets settling new bets, can
    never double-write or race a row. A row this pass cannot find a close
    for (no snapshots ever captured for its game) is still marked
    attempted, via record_closing's computed_at stamp, so it is not
    reselected forever.
    """
    computed_at = now or _now_iso()
    rows = savedbets.list_settled_bets_missing_closing(db=db)
    filled, ungraded_reasons = 0, {}
    for bet in rows:
        closing = compute_closing_price(bet, snapshot_rows)
        savedbets.record_closing(bet.id, computed_at=computed_at, db=db, **closing)
        reason = closing["closing_reason"]
        if reason:
            ungraded_reasons[reason] = ungraded_reasons.get(reason, 0) + 1
        else:
            filled += 1
    return {
        "checked": len(rows),
        "filled": filled,
        "ungraded": len(rows) - filled,
        "ungraded_reasons": ungraded_reasons,
    }


def settle_saved_bets_if_app_db_exists(store_reader: StoreReader, *, db=None,
                                       now=None, snapshot_rows=None) -> dict:
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

    `snapshot_rows` passes straight through to settle_saved_bets (see its
    own docstring) -- this hook does not read the live snapshot store
    itself for the same reason it does not read the live results store
    itself: the caller (src.cli's daily loop) already has both and is
    where "read the real store" belongs, not a function whose whole job is
    "should this run at all".
    """
    resolved_db = db or savedbets.db_path()
    if not resolved_db.exists():
        return {"skipped": True, "reason": f"no app db at {resolved_db}"}
    return settle_saved_bets(store_reader, db=resolved_db, now=now,
                             snapshot_rows=snapshot_rows)
