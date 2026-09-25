"""Shadow-only: enumerate BOTH moneyline sides before V2's rule runs.

WHY THIS IS A SEPARATE FILE AND NOT AN EDIT
-------------------------------------------
`docs/PREREG_CARD_V2.md` section 2 registers the moneyline candidate set as
"Both sides of every game". The live path does not build it. `card_v2.
_build_game_candidates` delegates to `daily_card.build_pick_candidates`,
which calls `daily_card._consensus_side` and keeps `max(p_away, p_home)` --
so every game contributes exactly one candidate and its
`market_probability` is `>= 0.50` by construction. G5's PLUS_MONEY branch
(`best_bets_card.py:376-381`) requires `market_probability < 0.50`. The two
conditions are disjoint, so the registered PLUS_MONEY class cannot fire on a
game moneyline at all: in 332 moneyline rows across `evidence/cards_v2*.jsonl`
every price is negative and the smallest `market_probability` is 0.5003.

The correction therefore CANNOT be made in place. Registration 11.2 puts
`src/report/card_v2.py` and `src/analysis/best_bets_card.py` inside
`code_fingerprint` (`card_ledger.V2_FINGERPRINT_FILES`) and says a change to
any fingerprinted file "restarts the counted sample". Editing either file --
even to add a flag that is off by default -- restarts V2's published sample
on the day it was registered, which is a cost the correction has not earned
and which the owner has not approved. `daily_card.py` is worse: it sits in
`V1_FINGERPRINT_FILES` and is what the frozen V1 comparison is pinned to.

So this module changes nothing. It IMPORTS the registered path, calls it
unmodified for the market-favoured side, and adds the side the registered
path never builds. Both fingerprints are unchanged by construction, and
`tests/test_card_v2_candidate_enumeration.py` asserts their exact registered
values rather than trusting that claim.

WHAT IS AND IS NOT CORRECTED HERE
---------------------------------
Corrected, each its own explicitly versioned arm, default OFF except the
first (already collecting a forward record since 2026-09-23):
  * game moneyline, both sides (`ENUMERATION_ID`);
  * player props, both sides of every registered contract, when
    `enumerate_props=True` (`ENUMERATION_ID_PROPS`; `src/report/props.py:148`
    keeps only `propboard.most_likely`'s side on the live path);
  * the standard run line, both REAL quoted sides, when
    `enumerate_run_line=True` (`ENUMERATION_ID_RUNLINE`, added 2026-09-24,
    D1a) -- section 2 registers "both sides at exactly +1.5 and -1.5"; the
    live path only ever attaches the FAVOURED side's run line as a display
    alternative (`daily_card._attach_run_line`), with the market's own price
    and no model number, never as a candidate either side could be picked
    from.
Each arm is a SEPARATE id on purpose (see `ENUMERATION_ID_PROPS`'s own
comment) -- a registered experiment may never change what it measures
mid-sample, so widening one arm's pool can never be folded into another's id
or turned on by another arm's flag.

Nothing in this file should be read as "V2's candidate set now matches its
registration": every arm above still runs through the unedited registered
gates, ranking and thresholds, and none is wired to anything that publishes.

THIS IS NOT APPROVED TO PUBLISH
-------------------------------
No scheduler, publisher, API route or page calls this module. It exists to
be measured offline against the live path. Promotion is a separate owner
decision and, under section 16's own words ("Anything else is a new rule
id"), a new rule id rather than an amendment to V2.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from src.analysis import best_bets_card, calibrate, daily_card, strength
from src.report import card as card_v1
from src.report import card_v2


# Stamped on every candidate this module ADDS, never on the ones the
# registered path built. A candidate without this key came out of
# `card_v2._build_game_candidates` untouched; that is the property
# `test_registered_candidates_are_passed_through_unchanged` checks.
ENUMERATION_ID = "moneyline_both_sides_v1"

# The PROP arm, added 2026-09-23. A SEPARATE id on purpose.
#
# `moneyline_both_sides_v1` is already collecting a forward record under its
# recorded rule. Folding props into it would silently change what that arm
# measures halfway through its own sample, which is the thing a registered
# experiment may never do. So props are their own arm, off by default, and
# a run states which arm produced it. Neither arm's thresholds move.
ENUMERATION_ID_PROPS = "props_both_sides_v1"

# Why a side the registered path built could not be mirrored. These are
# NOT gate names: a gate refusal means the candidate existed and the rule
# said no, which is a different fact from the candidate never being built,
# and the coverage ledger has to keep them apart (that conflation is what
# made an empty card read as "nothing cleared the bar").
NO_OPPOSITE_ROW = "no_opposite_quote_row"
NO_OPPOSITE_PRICE = "no_opposite_best_price"
NO_OPPOSITE_MARKET_P = "no_opposite_market_probability"


def _identities(entries: Sequence, *, date: str) -> dict:
    """`{game_id: card._game_identity(...)}` for the team NAMES.

    `card_v2._build_game_candidates` drops `opponent_name` when it maps a
    `daily_card` candidate into best_bets_card shape, so the mirrored side's
    display name is not recoverable from its output. `_game_identity` is a
    pure read of the entry's own dossier -- no model, no clock, no store --
    so recomputing it here cannot change any number.
    """
    out = {}
    for entry in entries or ():
        try:
            game = card_v1._game_identity(entry, date=date)
        except Exception:  # noqa: BLE001 - a malformed entry is not fatal
            continue
        gid = game.get("game_id")
        if gid:
            out[gid] = game
    return out


def _mirror(candidate: Mapping, *, row: Mapping, game: Optional[Mapping],
            side: str) -> dict:
    """The candidate for the side the registered path discarded.

    Every field is either read straight off the opposite side's own quote
    row, copied from the game-level facts the favoured candidate already
    carries (game identity, first pitch, game type, calibration state), or
    -- for `our_probability` alone -- taken as the complement.

    THE COMPLEMENT IS EXACT, and only because of where it is read from.
    `card_v2._build_game_candidates` assigns `line["p_away"] = 1.0 -
    line["p_home"]` itself after applying the frozen Platt fit, so the two
    calibrated sides are complementary by that assignment, not by an
    assumption about `strength.model_line`'s raw output. When the frozen fit
    is missing that assignment never runs, `calibrated` is False, and G9
    refuses every game candidate on both sides -- so the one case where the
    complement could be inexact is a case where no candidate on either side
    can be a pick or a fill. The side is still enumerated there, so the
    coverage ledger counts it and attributes it to G9 rather than losing it.
    """
    price = row.get("best_price")
    market_p = row.get("market_implied_probability")
    our_p = candidate.get("our_probability")
    if our_p is not None:
        our_p = 1.0 - our_p
    if side == "away":
        team_name = (game or {}).get("away_name") or candidate.get("away_team")
    else:
        team_name = (game or {}).get("home_name") or candidate.get("home_team")

    mirrored = {
        "kind": "game",
        "game_id": candidate.get("game_id"),
        "game_pk": candidate.get("game_pk"),
        "player_id": None,
        "player": None,
        "price": price,
        "market_probability": market_p,
        "our_probability": our_p,
        "model_probability": our_p,
        "books": row.get("books"),
        "observed_utc": card_v2._observed_dt(row.get("observed_utc")),
        "has_started": False,
        "calibrated": candidate.get("calibrated"),
        "first_pitch": candidate.get("first_pitch"),
        "first_pitch_utc": candidate.get("first_pitch_utc"),
        "team_name": team_name,
        "away_team": candidate.get("away_team"),
        "home_team": candidate.get("home_team"),
        "game_type": candidate.get("game_type"),
        "market": "moneyline",
        "side": side,
        "line": None,
        "enumeration": ENUMERATION_ID,
    }
    mirrored["bet_sentence"] = card_v2._bet_sentence(mirrored)
    # Two DIFFERENT facts that the old `is_underdog` field ran together.
    # `market_underdog` is what G5's PLUS_MONEY branch actually tests; a
    # positive American price on a market-favoured side is not the same
    # thing and must never be counted as an underdog admitted by this fix.
    mirrored["market_underdog"] = (market_p is not None and market_p < 0.50)
    mirrored["positive_price"] = (price is not None and price > 0)
    mirrored["enumerated_side_role"] = (
        "market_underdog" if mirrored["market_underdog"] else "market_co_side")
    return mirrored


def build_game_candidates(entries: Sequence, opportunity_rows: Sequence, *,
                          date: str, now: datetime, frozen: Mapping,
                          multibook_rows=None) -> tuple:
    """`(candidates, raw_pool_size, not_built)`.

    `candidates` is the registered path's output, in its original order and
    with its dicts untouched, followed by one mirrored candidate per game
    whose opposite side carried a usable quote. `not_built` lists the sides
    that could not be mirrored, each with a reason, so a missing side is
    never silently absent from the count.
    """
    registered, registered_pool = card_v2._build_game_candidates(
        entries, opportunity_rows, date=date, now=now, frozen=frozen,
        multibook_rows=multibook_rows)

    ml_rows = card_v1.moneyline_rows(opportunity_rows)
    identities = _identities(entries, date=date)

    added: list = []
    not_built: list = []
    for candidate in registered:
        if candidate.get("market") != "moneyline":
            continue
        gid = candidate.get("game_id")
        other = "home" if candidate.get("side") == "away" else "away"
        row = (ml_rows.get(gid) or {}).get(other)
        if not row:
            not_built.append({"game_id": gid, "side": other,
                              "reason": NO_OPPOSITE_ROW})
            continue
        if row.get("best_price") is None:
            not_built.append({"game_id": gid, "side": other,
                              "reason": NO_OPPOSITE_PRICE})
            continue
        if row.get("market_implied_probability") is None:
            not_built.append({"game_id": gid, "side": other,
                              "reason": NO_OPPOSITE_MARKET_P})
            continue
        added.append(_mirror(candidate, row=row,
                             game=identities.get(gid), side=other))

    return registered + added, registered_pool + len(added), not_built


def both_sides_prop_board(date: str, **kwargs) -> dict:
    """`props.board_for_date`'s payload with BOTH sides of every registered
    contract, for injection as `card_v2_for_date`'s `prop_board`.

    THE DEFECT. Registration section 2 registers the prop candidate set as
    "Both sides of every `batter_hits` and `batter_total_bases` contract".
    `propboard.build` already produces both -- `propboard.py:232` loops
    `(("Over", over), ("Under", under))` and stamps `side` on each, with its
    own price and de-vigged probability. Nothing is missing at the board.

    The loss is one filter. `props.board_for_date` passes the board through
    `propboard.most_likely`, which keeps only `probability > LIKELY_FLOOR`
    (0.50). Since the two sides of a contract are complementary by
    construction, that discards the under side of every contract, and any
    over the model makes less than even. V2 never sees them.

    This reuses the registered builder and skips only that filter and the
    display cap. It does NOT widen the market set: section 2 registers two
    markets, so `daily_card.PROP_MARKETS` is applied here. Home runs stay
    out -- they are not registered, and no book quotes their under
    (`propboard.py:59`), so there is no second side to enumerate anyway.

    `card_v2._build_prop_candidates` takes this through
    `card._enriched_prop_contracts`'s injection seam, so the schedule join,
    the started-game filter and the candidate shape are all the registered
    ones. No registered file is edited.
    """
    from src.analysis import playerprops, propboard
    from src.pipeline import batter_props
    from src.report import props as props_mod

    rows = kwargs.get("prop_rows")
    rows = list(rows) if rows is not None else batter_props.read_processed()
    batters = kwargs.get("batter_rows")
    batters = (list(batters) if batters is not None
               else props_mod._batter_rows(
                   props_mod.box_store_for_season(date)))
    by_name = props_mod._by_name(batters)

    history = [row for row in batters
               if str(row.get("date") or "")[:10] < date]
    if not history:
        return {"date": date, "contracts": [], "counts": {},
                "reason": "no batter history before this date"}

    slots = kwargs.get("slots")
    built = propboard.build(
        rows, date=date, batters_by_name=by_name,
        league=playerprops.league_rates(history),
        slots_by_player=(slots if slots is not None
                         else props_mod._slots_for(date)))

    registered = [c for c in built["contracts"]
                  if c.get("market") in daily_card.PROP_MARKETS]
    registered.sort(key=lambda c: (str(c.get("player") or ""),
                                   str(c.get("market") or ""),
                                   str(c.get("line") or ""),
                                   str(c.get("side") or "")))
    return {
        "date": date,
        "contracts": [props_mod._public(c) for c in registered],
        "long_shots": [],
        "counts": propboard.summarise(built),
        "reason": None if registered else (
            "no registered prop contracts are priced for this slate yet"),
        "enumeration": ENUMERATION_ID_PROPS,
    }


# ---------------------------------------------------------------------------
# D1a: the run-line arm. Added 2026-09-24, its own explicitly versioned id,
# default OFF. Unlike the two arms above, this one applies a calibration
# this module reads itself rather than reusing one the registered candidate
# already carries -- read `_runline_calibration`'s docstring before touching
# any of this. Applying the WRONG calibration here would be worse than
# applying none.
# ---------------------------------------------------------------------------

ENUMERATION_ID_RUNLINE = "run_line_both_sides_v1"

# Why a run-line side was not built. Distinct names from NO_OPPOSITE_* (the
# moneyline arm's reasons) on purpose -- see that block's comment. These
# candidates are built from scratch, not mirrored from an existing one, so
# the failure modes differ: a whole GAME can be excluded before either side
# is even attempted (no model output at all), which cannot happen to the
# moneyline mirror -- a favoured-side candidate already existing there is
# itself the proof the model succeeded for that game.
RL_ALREADY_STARTED = "run_line_game_already_started"
RL_NO_LEAGUE_RATE = "run_line_no_league_runs_per_game"
RL_MODEL_REFUSED = "run_line_model_refused"
RL_NO_QUOTE_ROW = "run_line_no_quote_row"
RL_NO_PRICE = "run_line_no_best_price"
RL_NOT_STANDARD_LINE = "run_line_not_standard_line"
RL_FUTURE_QUOTE = "run_line_quote_observed_after_now"


def _runline_calibration(frozen: Mapping) -> Optional[calibrate.Calibration]:
    """The frozen run-line COVER calibration, or `None` if the frozen file's
    own fit failed -- mirrors `card_v2._moneyline_calibration`'s "None is a
    real answer" contract exactly, one level down in this file because
    `card_v2.py` may not be edited to add it there.

    A DIFFERENT NUMBER FROM THE MONEYLINE FIT, on purpose. Registration 11.2
    lists both as separate fitted numbers the frozen file holds: "the
    moneyline Platt `a` and `b`, **the side-level run-line cover
    calibration**". G9's own row names it too: "holds the moneyline
    calibration (for a moneyline) or the run-line cover calibration (for a
    run line)". Both are fit by the same T0a script on the same 2025 games,
    but one is fit on which team wins and the other on which side covers a
    spread -- applying the moneyline pair to a run-line probability is
    exactly the category error the module docstring warns against, and
    nowhere in this function does `card_v2._moneyline_calibration` or its
    `cal.apply` ever touch a run-line number.

    LIVE, THIS IS TRUE AND UNUSED TODAY. `data/processed/
    card_v2_frozen_params.json` already carries `"runline_calibration":
    {"a": 0.0, "b": 0.950892, "n": 8108, "fitted": true, ...}` -- fit,
    frozen, sitting there since T0a, applied by NO code anywhere in this
    repo until this function, because no code anywhere else ever builds a
    run-line CANDIDATE for it to be applied to
    (`daily_card._attach_run_line` only ever displays the market's own
    price, never a model number). Section 2's "today no calibration touches
    run-line numbers" describes that gap, not an absent registration -- 11.2
    registers this number on equal footing with `DISPERSION`, the moneyline
    fit, `RHO` and the slot table, all of which other code in this repo
    already applies.

    `a == 0.0` IS LOAD-BEARING. `Calibration.apply` is
    `sigmoid(a + b*logit(p_raw))`; for two probabilities that are exact
    complements (`p + q == 1`), `sigmoid(b*logit(p)) + sigmoid(b*logit(1-p))
    == 1` for ANY `b` only when `a == 0` (`logit(1-p) == -logit(p)`, so a
    nonzero `a` breaks the symmetry). The two REAL quoted sides of one
    game's standard run line are exact complements by construction (the two
    `market_probabilities` pairs `strength.py`'s own module docstring names,
    read in `_run_line_side_candidate` via `strength.run_line_probability`
    on the same `line_dist`), so applying this SAME `(a, b)` pair
    independently to each side keeps them summing to 1 after calibration,
    exactly as before it.
    `tests.test_card_v2_candidate_enumeration.RunLineCalibrationStaysComplementary`
    measures this rather than assuming it.
    """
    blob = frozen.get("runline_calibration") or {}
    if not blob.get("fitted"):
        return None
    try:
        return calibrate.Calibration(
            float(blob["a"]), float(blob["b"]), int(blob["n"]),
            float(blob.get("base_rate", 0.5)))
    except (KeyError, TypeError, ValueError):
        return None


def _run_line_bet_sentence(candidate: Mapping) -> str:
    """Mirrors `card_v2._bet_sentence`'s convention: no "Take " prefix --
    `best_bets_card.bet_sentence` adds that at render time, and this module
    publishes nothing that would ever call it."""
    line = candidate.get("line") or 0.0
    sign = "+" if line > 0 else ""
    price_txt = daily_card._fmt_price(candidate.get("price"))
    return f"{candidate.get('team_name')} {sign}{line:g} at {price_txt}"


def _run_line_side_candidate(game: Mapping, line_dist: Mapping, side: str,
                             row: Mapping, *, now: datetime,
                             cal: Optional[calibrate.Calibration]):
    """`(candidate, None)` or `(None, reason)` for ONE real quoted run-line
    side.

    Split out of `build_run_line_candidates`'s loop so the two checks that
    protect against a bad quote row -- "is this really the standard line"
    and "is this quote from the future" -- are each one small function a
    test can drive with a hand-built `row`, without needing a live board or
    a monkeypatched store.

    THE LINE IS READ, NEVER INFERRED -- same rule and same reason as
    `daily_card._attach_run_line`'s own comment. `row["line"]` comes
    straight off `card.run_line_rows`'s own signed value for this side
    (`home_line` if `side == "home"` else `-home_line`), never derived from
    a price's sign or a moneyline favourite. `card.run_line_rows` already
    filters to exactly +-1.5 (registration section 2: "no alternate
    lines"), so the isinstance-and-tolerance check below is
    belt-and-suspenders against a caller that bypasses it -- and it is
    exactly what lets a test exercise the defence directly, by calling this
    function with a hand-built `row` rather than through
    `card.run_line_rows`.
    """
    price = row.get("best_price")
    if price is None:
        return None, RL_NO_PRICE

    line = row.get("line")
    if not isinstance(line, (int, float)) or isinstance(line, bool):
        return None, RL_NOT_STANDARD_LINE
    line = float(line)
    if abs(abs(line) - card_v1.RUN_LINE) > 1e-9:
        return None, RL_NOT_STANDARD_LINE

    observed = card_v2._observed_dt(row.get("observed_utc"))
    if observed is not None and observed > now:
        # D1c: `best_bets_card.quote_age_seconds` is `(now - observed_utc)
        # .total_seconds()`, and G3 fails only when that is None or GREATER
        # than the freshness bound -- a NEGATIVE age (a quote timestamped
        # after `now`) is neither, so it would read as the freshest possible
        # quote rather than as the error it is. This module cannot edit G3
        # (`best_bets_card.py` is not in its write area), so the guard has
        # to live here: a future-dated quote never becomes a candidate at
        # all, in either a live or a `--now` retrospective run.
        return None, RL_FUTURE_QUOTE

    underdog = line > 0
    raw_p = strength.run_line_probability(line_dist, side, underdog=underdog)
    calibrated_p = cal.apply(raw_p) if cal is not None else None
    our_p = calibrated_p if calibrated_p is not None else raw_p

    team_name = ((game.get("home_name") if side == "home"
                 else game.get("away_name"))
                or (game.get("home_team") if side == "home"
                    else game.get("away_team")))

    candidate = {
        "kind": "game",
        "game_id": game.get("game_id"),
        "game_pk": game.get("game_pk"),
        "player_id": None,
        "player": None,
        "price": price,
        "book": row.get("best_book"),
        "books": row.get("books"),
        "market_probability": row.get("consensus_probability"),
        "our_probability": our_p,
        # Provenance (D1a): the number BEFORE any calibration touched it,
        # kept on every candidate regardless of whether `cal` was available,
        # so a reader never has to trust `calibrated` alone to know what
        # `our_probability` would have been without it.
        "our_probability_raw": raw_p,
        "model_probability": our_p,
        "books_observed_utc": row.get("observed_utc"),
        "observed_utc": observed,
        "has_started": False,  # the caller already excludes started games
        "calibrated": cal is not None,
        "first_pitch": game.get("first_pitch_utc"),
        "first_pitch_utc": game.get("first_pitch_utc"),
        "team_name": team_name,
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "game_type": game.get("game_type", "R"),
        "market": "run_line",
        "side": side,
        "line": line,
        "underdog": underdog,
        "market_underdog": (row.get("consensus_probability") is not None
                            and row.get("consensus_probability") < 0.50),
        "positive_price": (price is not None and price > 0),
        "enumeration": ENUMERATION_ID_RUNLINE,
    }
    candidate["bet_sentence"] = _run_line_bet_sentence(candidate)
    return candidate, None


def build_run_line_candidates(entries: Sequence, *, date: str, now: datetime,
                              frozen: Mapping, multibook_rows=None) -> tuple:
    """`(candidates, raw_pool_size, not_built)` -- both REAL quoted sides of
    the standard run line (registration section 2: "Both sides at exactly
    +1.5 and -1.5, no alternate lines") for every game this snapshot
    supports.

    A candidate is "supported" when: the game has not started as of `now`;
    `strength.league_runs_per_game` and `strength.model_line` both succeed on
    it (the same frozen `DISPERSION` `card_v2._build_game_candidates` uses,
    read from the SAME `frozen` mapping every other arm reads, so all arms
    stay comparable on one snapshot); and `card.run_line_rows` carries a
    priced quote for that side with a real price and the standard line.

    WHY THIS DUPLICATES PART OF `card_v2._build_game_candidates`'s OWN LOOP.
    That function computes a `strength.model_line(...)` per game and then
    THROWS IT AWAY -- it returns only `(candidates, raw_pool_size)`, never
    the model line itself, so `strength.run_line_probability` (which needs
    the full joint distribution's `p_*_plus`/`p_*_minus`, not the `p_home`/
    `p_away` the returned candidate carries) has nothing to read. `card_v2.py`
    is fingerprinted and may not be edited to return it. So this recomputes
    the same call, on the same inputs, in the same order (`_flatten` ->
    `league_runs_per_game` -> `relief_rates_for` -> `model_line`) -- read-only
    duplication of a CALL, not a second implementation of the model. If
    `card_v2._build_game_candidates` ever changes how it builds `features`
    this function has to be re-read against it; that risk is inherent to a
    shadow-only module that may not edit the file it shadows (module
    docstring, "THE CORRECTION THEREFORE CANNOT BE MADE IN PLACE").

    CALIBRATION IS APPLIED HERE, deliberately unlike section 2's own
    illustration (2026-09-15, before T0a existed -- see
    `_runline_calibration`). `our_probability` is calibrated when the frozen
    fit is present (`calibrated: True`, so G9 can pass) and left raw
    otherwise (`calibrated: False`, so G9 refuses it, exactly as
    `card_v2._build_game_candidates` leaves a moneyline candidate raw and
    G9-failing when ITS calibration is missing). `our_probability_raw` is
    kept on every candidate regardless.

    `raw_pool_size` is the count of candidates actually constructed (both
    real sides, summed over every supported game) -- the same meaning
    `build_game_candidates`'s own `raw_pool_size` has for the moneyline arm,
    so the two numbers can be added or compared directly.
    """
    dispersion = frozen.get("DISPERSION")
    cal = _runline_calibration(frozen)

    feature_rows = [card_v1._flatten(e) for e in entries or ()]
    league_rpg = strength.league_runs_per_game(feature_rows)
    relief = card_v1.relief_rates_for(date)

    games, model_lines, not_built = [], {}, []
    for entry in entries or ():
        game = card_v1._game_identity(entry, date=date)
        gid = game.get("game_id")
        if card_v1._has_started(game["first_pitch_utc"], now):
            not_built.append({"game_id": gid, "side": "home",
                              "reason": RL_ALREADY_STARTED})
            not_built.append({"game_id": gid, "side": "away",
                              "reason": RL_ALREADY_STARTED})
            continue
        if not league_rpg:
            not_built.append({"game_id": gid, "side": "home",
                              "reason": RL_NO_LEAGUE_RATE})
            not_built.append({"game_id": gid, "side": "away",
                              "reason": RL_NO_LEAGUE_RATE})
            continue
        game["features"]["away_bullpen_rate"] = relief.get(game["away_team"])
        game["features"]["home_bullpen_rate"] = relief.get(game["home_team"])
        game["game_type"] = card_v2._game_type(entry)
        try:
            line_dist = strength.model_line(
                game["features"], league_rpg=league_rpg,
                run_line=card_v1.RUN_LINE, dispersion=dispersion)
        except strength.StrengthError:
            not_built.append({"game_id": gid, "side": "home",
                              "reason": RL_MODEL_REFUSED})
            not_built.append({"game_id": gid, "side": "away",
                              "reason": RL_MODEL_REFUSED})
            continue
        games.append(game)
        model_lines[gid] = line_dist

    rl_rows = card_v1.run_line_rows(date, rows=multibook_rows)

    candidates = []
    for game in games:
        gid = game["game_id"]
        line_dist = model_lines[gid]
        sides = rl_rows.get(gid) or {}
        for side in ("home", "away"):
            row = sides.get(side)
            if not row:
                not_built.append({"game_id": gid, "side": side,
                                  "reason": RL_NO_QUOTE_ROW})
                continue
            candidate, reason = _run_line_side_candidate(
                game, line_dist, side, row, now=now, cal=cal)
            if candidate is None:
                not_built.append({"game_id": gid, "side": side,
                                  "reason": reason})
                continue
            candidates.append(candidate)

    return candidates, len(candidates), not_built


def reconcile_identity_sets(before: Sequence, after: Sequence, *,
                            identity=None) -> dict:
    """EXACT set reconciliation between two candidate/row pools, keyed by a
    stable identity -- added, removed and unchanged, never a subtraction of
    totals (D1b).

    WHY THIS FUNCTION EXISTS. `len(after) - len(before)` is a NET number: it
    is silent about rows that left the pool, and silent about which of the
    surviving rows are the same ones. Two pools that differ by 90 in total
    size can do that with 90 added and 0 removed, or with 117 added and 27
    removed (both net to 90) -- and only the second is what actually
    happened between `evidence/shadow_enumeration`'s 2026-09-23 144- and
    234-candidate prop-pool runs (see
    `evidence/shadow_enumeration/PROP_POOL_RECONCILIATION_2026-09-23.md`).
    "234 - 144 = 90" and "117 added" are BOTH true and do not contradict
    each other once removals are counted separately; treating either one
    alone as "the" count of what changed is the reporting error this
    function exists to make impossible to repeat.

    `identity` defaults to `(player, market, line, side)` -- D1b's own
    "stable contract identity" -- read with `.get` so a row missing a key
    contributes `None` there rather than raising. A caller reconciling game
    markets instead of props passes its own, e.g. `(game_id, market, side,
    line)`, since props carry no `game_id` and games carry no `player`.

    Returns `added`/`removed`/`unchanged` as lists of the IDENTITY tuples
    (not the rows -- two pools may serialise the same identity's row
    differently, e.g. a refreshed price, and this function only answers "is
    this contract present", not "did its row change"), the three counts,
    the two input sizes, and the duplicate-identity counts a caller must see
    rather than have silently absorbed into a `set` built over the same
    keys.
    """
    if identity is None:
        def identity(row):
            return (row.get("player"), row.get("market"), row.get("line"),
                    row.get("side"))

    before_ids = [identity(r) for r in before]
    after_ids = [identity(r) for r in after]
    before_set, after_set = set(before_ids), set(after_ids)

    added = sorted(after_set - before_set, key=repr)
    removed = sorted(before_set - after_set, key=repr)
    unchanged = sorted(before_set & after_set, key=repr)

    return {
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "n_added": len(added),
        "n_removed": len(removed),
        "n_unchanged": len(unchanged),
        "n_before": len(before_ids),
        "n_after": len(after_ids),
        "duplicate_identities_before": len(before_ids) - len(before_set),
        "duplicate_identities_after": len(after_ids) - len(after_set),
    }


def primary_gate_rejection_counts(census: Sequence) -> dict:
    """Exclusive PRIMARY-reason counts over a `gate_census` result (D1b):
    one bucket per candidate, its FIRST failed gate (`census`'s own
    `primary_reason`, already `fails[0]` in `best_bets_card`'s gate order --
    see `gate_census`'s docstring for why a candidate must be counted once,
    not once per gate it fails). `None` (passed every gate) counts under
    `"PASSED_ALL_GATES"` so the buckets always sum to `len(census)`.

    A caller wanting the overlapping SECONDARY failures reads each row's own
    `also_failed` instead -- deliberately NOT summarised here, since summing
    across every row's `also_failed` double- (or triple-, or more-) counts a
    candidate that fails several gates, which is exactly the pooling
    mistake this function exists to refuse to make. `also_failed` counts,
    when reported, must say so out loud, the same way this function's
    docstring does.
    """
    counts = Counter(row.get("primary_reason") or "PASSED_ALL_GATES"
                     for row in census)
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def gate_census(candidates: Sequence, *, now: datetime,
                params: best_bets_card.RuleParams) -> list:
    """Per-candidate gate outcome, for candidates `select` throws away.

    `best_bets_card.select` copies each candidate (`c = dict(raw)`) and
    returns only picks and fills, so a candidate refused by a gate that is
    not fill-eligible leaves no trace in its result at all -- there is no
    way to ask the returned payload why a side was refused. This calls the
    same public `failed_gates` the rule itself calls, on the same dicts,
    so the census cannot drift from the decision it describes.

    PRIMARY reason is `fails[0]`, in the module's own gate order, and the
    remaining failures are kept separately: a candidate that fails three
    gates must be counted once, not three times, or the ledger's stages
    stop reconciling.
    """
    out = []
    for raw in candidates:
        c = dict(raw)
        c["__params__"] = params
        fails = best_bets_card.failed_gates(c, now=now, params=params)
        out.append({
            "game_id": raw.get("game_id"),
            "player_id": raw.get("player_id"),
            "kind": raw.get("kind"),
            "side": raw.get("side"),
            "market": raw.get("market"),
            "price": raw.get("price"),
            "market_probability": raw.get("market_probability"),
            "our_probability": raw.get("our_probability"),
            "price_class": best_bets_card.price_class(raw.get("price"))
                           if raw.get("price") is not None else None,
            "enumeration": raw.get("enumeration"),
            "market_underdog": raw.get("market_underdog"),
            "primary_reason": fails[0] if fails else None,
            "also_failed": list(fails[1:]),
            "fill_eligible": best_bets_card.is_fill_eligible(fails),
        })
    return out


def card_v2_for_date_shadow(entries: Sequence, opportunity_rows: Sequence, *,
                            date: str, now: Optional[datetime] = None,
                            params: best_bets_card.RuleParams = best_bets_card.V2,
                            frozen: Optional[Mapping] = None,
                            prior: Optional[Mapping] = None,
                            multibook_rows=None, prop_board=None,
                            event_map=None, enumerate_props: bool = False,
                            enumerate_run_line: bool = False) -> dict:
    """`card_v2.card_v2_for_date`'s payload with both moneyline sides, and
    optionally both prop sides and both run-line sides.

    Deliberately a copy of that function's post-`select` assembly rather
    than a call into it: calling it would rebuild the one-sided game pool
    this module exists to replace. Prop candidates come from the registered
    builder untouched, and the rule itself (`best_bets_card.select`) is the
    registered, unedited one. The ONLY difference from the live path is
    which candidates are handed to it.

    `enumerate_run_line` (D1a, added 2026-09-24): default OFF. When True,
    `build_run_line_candidates` widens the pool with both real quoted run-line
    sides of every supported game, using the SAME `multibook_rows` snapshot
    the moneyline arm reads, so game-market coverage stays comparable across
    arms (task constraint: "All arms consume the SAME snapshot"). Both a
    run-line and a moneyline candidate for one game carry the SAME `game_id`,
    so G11 (`best_bets_card._game_key`, unedited) still keeps at most one
    entry per game across the two markets, exactly as registered -- no new
    dedup logic is needed here or anywhere in this file for that to hold.
    """
    now = now or datetime.now(timezone.utc)
    frozen = frozen if frozen is not None else card_v2.load_frozen_params()

    game_candidates, game_pool, not_built = build_game_candidates(
        entries, opportunity_rows, date=date, now=now, frozen=frozen,
        multibook_rows=multibook_rows)

    # OFF BY DEFAULT. With `enumerate_props=False` this call is byte-for-byte
    # the moneyline arm that is already collecting a forward record, and its
    # prop pool is the registered one-sided board. Turning it on is a
    # DIFFERENT arm with its own id -- never a mid-sample change to the
    # arm above.
    if enumerate_props and prop_board is None:
        prop_board = both_sides_prop_board
    prop_candidates, prop_pool = card_v2._build_prop_candidates(
        entries, date=date, now=now, prop_board=prop_board,
        event_map=event_map)

    # OFF BY DEFAULT, same discipline as props immediately above: with
    # `enumerate_run_line=False` the three lines below never run, so this
    # arm cannot affect the moneyline arm's already-collecting sample no
    # matter what `multibook_rows` contains.
    if enumerate_run_line:
        run_line_candidates, run_line_pool, run_line_not_built = (
            build_run_line_candidates(
                entries, date=date, now=now, frozen=frozen,
                multibook_rows=multibook_rows))
    else:
        run_line_candidates, run_line_pool, run_line_not_built = [], 0, []

    candidates = game_candidates + prop_candidates + run_line_candidates
    raw_pool_size = game_pool + prop_pool + run_line_pool

    result = best_bets_card.select(candidates, now=now, params=params,
                                   prior=prior)

    for entry in result["all_bets"]:
        entry.setdefault("take", entry.get("entry_class") == "pick")
        if entry.get("kind") == "prop":
            entry.setdefault("lineup_posted",
                             entry.get("expected_pa_source") == "batting_slot")

    parts = [ENUMERATION_ID]
    if enumerate_props:
        parts.append(ENUMERATION_ID_PROPS)
    if enumerate_run_line:
        parts.append(ENUMERATION_ID_RUNLINE)

    result.update({
        "date": date,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "games_on_slate": len(entries or ()),
        "raw_pool_size": raw_pool_size,
        # Shadow-only provenance. `rule` still carries the registered rule
        # id because the RULE is unchanged -- only the candidate set differs
        # -- and a reader who sees this payload must be able to tell that
        # apart from a published V2 card at a glance. With both new flags at
        # their default False this is exactly "+".join([ENUMERATION_ID]) ==
        # ENUMERATION_ID, byte-identical to before either flag existed.
        "enumeration": "+".join(parts),
        "enumerate_props": enumerate_props,
        "enumerate_run_line": enumerate_run_line,
        "shadow": True,
        "sides_not_built": not_built,
        "run_line_sides_not_built": run_line_not_built,
        "gate_census": gate_census(candidates, now=now, params=params),
    })

    if result["n_picks"] < params.floor:
        if raw_pool_size == 0:
            result["empty_reason"] = (
                "No priced board to evaluate for this date: no game or "
                "player prop reached a priced, unstarted candidate.")
        else:
            result["empty_reason"] = best_bets_card.short_card_sentence(
                result["n_picks"])

    card_v1.attach_knowledge(result, entries, now=now)
    return result
