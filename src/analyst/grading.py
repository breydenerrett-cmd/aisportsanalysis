"""Grading an analyst call from the results the cards already use.

SAME RESULTS, SAME RULES AS THE CARDS
-------------------------------------
A moneyline, run line or game total call is graded by the card ledger's own
`grade_pick` / `grade_total_pick` against the same results store
(`src.pipeline.history`), so the analyst and a card can never disagree about
who won a game. Player props are graded by `src.board.settle_props.settle`, the
settlement rule the card's props use, against the same box-score store. The one
market the cards do not publish, a team total, is graded here with the same
three comparisons (over, under, push on the line).

This module imports the card ledger to call it. It never writes to it, and
nothing here changes what a card grades.

EVERY FAMILY IS GRADED ON ITS OWN
---------------------------------
`moneyline`, `run_line`, `total`, `team_total` and `prop` are separate
families. A record that blended them would let a good run on one hide a bad one
on another, and the families have nothing in common but the sport.

WHAT A GRADE IS
---------------
WIN, LOSS, PUSH (the line landed on the number: stake returned), VOID (the bet
could not stand: a player who never appeared, a game with no usable price) and
UNRESOLVED (no result yet: never a loss, never a void, so a postponed or
unplayed game does not look like a bad night). Returns are flat one-unit stakes
at the published price, the only stake plan this project uses; that is a way to
add results up, not a claim that anyone staked anything.

A PASS is not graded as a bet. It carries `would_have`, the result the passed
side would have had at its best quoted price, so the record can show whether
the passes were right without counting them as wins or losses.

Pure apart from the call into the card ledger: no I/O, no clock.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from src.appstate import card_ledger
from src.board import settle_props
from src.core import odds as odds_math

FAMILIES = ("moneyline", "run_line", "total", "team_total", "prop")
FAMILY_LABELS = {"moneyline": "Moneyline", "run_line": "Run line", "total": "Game total",
                 "team_total": "Team totals", "prop": "Player props"}

WIN, LOSS, PUSH, VOID, UNRESOLVED, PASS = "WIN", "LOSS", "PUSH", "VOID", "UNRESOLVED", "PASS"
SETTLED = (WIN, LOSS, PUSH, VOID)


def spec_for(market: Mapping, selection: str) -> dict:
    """What grading needs to know about one call, frozen into the published
    row so a result can be graded without the packet. `reference_price` is the
    best quote at publication, used only to say what a PASS would have done."""
    opt = next((o for o in market["options"] if o["selection"] == selection), None)
    ctx = market.get("context") or {}
    best = (opt or {}).get("best") or {}
    return {
        "family": market["market"],
        "side": (opt or {}).get("side"),
        "line": (opt or {}).get("line"),
        "team_side": ctx.get("team_side"),
        "player": ctx.get("player"),
        "stat": ctx.get("stat"),
        "reference_price": best.get("price"),
    }


def _units(won: bool, price: Any) -> Optional[float]:
    try:
        return round((odds_math.american_to_decimal(price) - 1.0) if won else -1.0, 4)
    except (odds_math.OddsError, TypeError, ValueError):
        return None


def _grade_bet(spec: Mapping, price: Any, game_pk: Any, result: Optional[Mapping],
               box_by_key: Mapping, box_games: frozenset) -> dict:
    family = spec.get("family")
    if family == "prop":
        return _grade_prop(spec, price, game_pk, box_by_key, box_games)
    if result is None:
        return {"result": UNRESOLVED, "profit_units": 0.0,
                "reason": "no final score stored for this game yet"}
    if family in ("moneyline", "run_line"):
        pick = {"game_pk": game_pk, "market": family, "side": spec.get("side"),
                "line": spec.get("line"), "price": price}
        graded = card_ledger.grade_pick(pick, result)
    elif family == "total":
        pick = {"game_pk": game_pk, "market": "total", "side": spec.get("side"),
                "line": spec.get("line"), "price": price}
        graded = card_ledger.grade_total_pick(pick, result)
    elif family == "team_total":
        graded = _grade_team_total(spec, price, result)
    else:
        return {"result": VOID, "profit_units": 0.0, "reason": f"unknown market family {family!r}"}
    out = {"result": graded["result"], "profit_units": graded.get("profit_units")}
    if graded.get("reason"):
        out["reason"] = graded["reason"]
    return out


def _grade_team_total(spec: Mapping, price: Any, result: Mapping) -> dict:
    explicit = card_ledger._explicit_void(result)
    if explicit is not None:
        return explicit
    away, home = card_ledger._score(result.get("away_score")), card_ledger._score(result.get("home_score"))
    if away is None or home is None:
        return {"result": UNRESOLVED, "profit_units": 0.0,
                "reason": "no final score stored for this game yet"}
    side, line, team_side = spec.get("side"), spec.get("line"), spec.get("team_side")
    if team_side not in ("away", "home") or side not in ("over", "under") \
            or not isinstance(line, (int, float)):
        return {"result": VOID, "profit_units": 0.0, "reason": "team-total call is missing its side or line"}
    runs = away if team_side == "away" else home
    if abs(runs - float(line)) < 1e-9:
        return {"result": PUSH, "profit_units": 0.0, "reason": "the team total landed on the line"}
    won = runs > line if side == "over" else runs < line
    units = _units(won, price)
    if units is None:
        return {"result": VOID, "profit_units": 0.0, "reason": f"unusable published price {price!r}"}
    return {"result": WIN if won else LOSS, "profit_units": units}


def index_box_rows(rows) -> tuple:
    """({(game_pk, player, kind): row}, {game_pk with any box row}); keys are
    strings, because the results and box stores disagree on int versus str."""
    by_key, games = {}, set()
    for row in rows or ():
        pk = str(row.get("game_pk"))
        games.add(pk)
        kind = row.get("type")
        if kind in ("batter", "pitcher") and row.get("player_name"):
            by_key[(pk, row["player_name"], kind)] = row
    return by_key, frozenset(games)


def _grade_prop(spec: Mapping, price: Any, game_pk: Any, box_by_key: Mapping,
                box_games: frozenset) -> dict:
    stat = settle_props.PROP_STAT_RULES.get(spec.get("stat"))
    line, side = spec.get("line"), spec.get("side")
    if stat is None:
        return {"result": VOID, "profit_units": 0.0,
                "reason": f"no settlement rule for {spec.get('stat')!r}"}
    if not isinstance(line, (int, float)) or side not in ("over", "under"):
        return {"result": VOID, "profit_units": 0.0, "reason": "prop call is missing its side or line"}
    pk = str(game_pk)
    kind = "pitcher" if str(spec.get("stat", "")).startswith("pitcher_") else "batter"
    row = box_by_key.get((pk, spec.get("player"), kind))
    explicit = card_ledger._explicit_void(row)
    if explicit is not None:
        return explicit
    if row is None:
        if pk in box_games:
            return {"result": VOID, "profit_units": 0.0,
                    "reason": "the player has no recorded appearance in this game's box score"}
        return {"result": UNRESOLVED, "profit_units": 0.0,
                "reason": "no box score stored for this game yet"}
    try:
        outcome = settle_props.settle(
            row, {"subject_id": None, "stat": stat, "line": f"{float(line):g}", "side": side})
    except settle_props.SettleError as exc:
        return {"result": VOID, "profit_units": 0.0, "reason": str(exc)}
    if outcome == "void":
        return {"result": VOID, "profit_units": 0.0,
                "reason": "the box row cannot support this stat"}
    if outcome == "push":
        return {"result": PUSH, "profit_units": 0.0}
    units = _units(outcome == "win", price)
    if units is None:
        return {"result": VOID, "profit_units": 0.0, "reason": f"unusable published price {price!r}"}
    return {"result": WIN if outcome == "win" else LOSS, "profit_units": units}


def grade_call(call: Mapping, game_pk: Any, result: Optional[Mapping],
               box_by_key: Mapping, box_games: frozenset) -> dict:
    """One published call, graded. A TAKE (either kind) is a bet at its price;
    a PASS is not, and reports `would_have` instead."""
    spec = call.get("grading") or {}
    base = {"slot_id": call["slot_id"], "family": spec.get("family"),
            "stat": spec.get("stat"), "player": spec.get("player"),
            "selection": call["selection"], "verdict": call["verdict"],
            "price": call.get("price"), "book": call.get("book")}
    if call["verdict"] in ("TAKE", "TAKE_OTHER_SIDE"):
        base.update(_grade_bet(spec, call.get("price"), game_pk, result, box_by_key, box_games))
        return base
    ref = call.get("price") if call.get("price") is not None else spec.get("reference_price")
    base.update({"result": PASS, "profit_units": None, "would_have": None})
    if ref is not None:
        would = _grade_bet(spec, ref, game_pk, result, box_by_key, box_games)
        if would["result"] != UNRESOLVED:
            base["would_have"] = {"result": would["result"], "price": ref}
    return base


def grade_game(published: Mapping, result: Optional[Mapping], box_rows) -> dict:
    """The graded body for one published row: every call, plus whether every
    BET has a settled result (`complete`) and the final score when known."""
    box_by_key, box_games = index_box_rows(box_rows)
    pk = published.get("game_pk")
    calls = [grade_call(c, pk, result, box_by_key, box_games) for c in published.get("calls") or []]
    bets = [c for c in calls if c["verdict"] in ("TAKE", "TAKE_OTHER_SIDE")]
    complete = all(c["result"] in SETTLED for c in bets) and (bool(bets) or result is not None)
    final = None
    if result is not None:
        a, h = card_ledger._score(result.get("away_score")), card_ledger._score(result.get("home_score"))
        if a is not None and h is not None:
            final = {"away_score": a, "home_score": h}
    return {"calls": calls, "complete": bool(complete), "final": final}
