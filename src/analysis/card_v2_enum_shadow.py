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
Corrected: game moneyline, both sides.
NOT corrected, still open and still departing from section 2:
  * run line -- section 2 registers "both sides at exactly +1.5 and -1.5";
    the live path attaches the favoured side's run line as a display
    alternative only (`daily_card._attach_run_line`), so no run line is ever
    a candidate for either side;
  * player props -- section 2 registers "both sides of every contract";
    `src/report/props.py:148` keeps only `propboard.most_likely`'s side.
Nothing in this file should be read as "V2's candidate set now matches its
registration".

THIS IS NOT APPROVED TO PUBLISH
-------------------------------
No scheduler, publisher, API route or page calls this module. It exists to
be measured offline against the live path. Promotion is a separate owner
decision and, under section 16's own words ("Anything else is a new rule
id"), a new rule id rather than an amendment to V2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from src.analysis import best_bets_card, daily_card
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
                            event_map=None, enumerate_props: bool = False) -> dict:
    """`card_v2.card_v2_for_date`'s payload with both moneyline sides.

    Deliberately a copy of that function's post-`select` assembly rather
    than a call into it: calling it would rebuild the one-sided game pool
    this module exists to replace. Prop candidates come from the registered
    builder untouched, and the rule itself (`best_bets_card.select`) is the
    registered, unedited one. The ONLY difference from the live path is
    which candidates are handed to it.
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

    candidates = game_candidates + prop_candidates
    raw_pool_size = game_pool + prop_pool

    result = best_bets_card.select(candidates, now=now, params=params,
                                   prior=prior)

    for entry in result["all_bets"]:
        entry.setdefault("take", entry.get("entry_class") == "pick")
        if entry.get("kind") == "prop":
            entry.setdefault("lineup_posted",
                             entry.get("expected_pa_source") == "batting_slot")

    result.update({
        "date": date,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "games_on_slate": len(entries or ()),
        "raw_pool_size": raw_pool_size,
        # Shadow-only provenance. `rule` still carries the registered rule
        # id because the RULE is unchanged -- only the candidate set differs
        # -- and a reader who sees this payload must be able to tell that
        # apart from a published V2 card at a glance.
        "enumeration": (
            f"{ENUMERATION_ID}+{ENUMERATION_ID_PROPS}" if enumerate_props
            else ENUMERATION_ID),
        "enumerate_props": enumerate_props,
        "shadow": True,
        "sides_not_built": not_built,
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
