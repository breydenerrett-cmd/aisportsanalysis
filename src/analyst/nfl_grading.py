"""Grading an NFL analyst call from the NFL data store's final scores.

SAME RULES AS THE CARDS AND THE MLB ANALYST, THREE FAMILIES
-----------------------------------------------------------
A moneyline, a point spread or a game total call is graded by the card ledger's own `grade_pick` /
`grade_total_pick` (the spread through its "spread" market, whose arithmetic is the run line's), so
the NFL analyst and a card can never disagree about who covered. The one thing added here is the
tie: `grade_pick` treats a moneyline tie as a loss for both sides, which is not what a sportsbook
does and not what a reader would call fair, so a tied game is a PUSH on the moneyline (stake
returned). A tie is not a push on a spread or a total unless the number says so; those already are
graded by the margin against the line.

EVERY FAMILY IS GRADED ON ITS OWN
---------------------------------
`moneyline`, `spread` and `total` are separate families, for the reason the MLB record gives: a
good run on one must not hide a bad one on another.

WHAT A GRADE IS
---------------
The MLB module's: WIN, LOSS, PUSH, VOID and UNRESOLVED (no final score stored yet: never a loss, so
a game the store has not updated looks like exactly that and not like a bad night). A PASS is not a
bet and carries `would_have`, the result the passed side would have had at its best quoted price.
Returns are flat one-unit stakes at the published price. Pure apart from the call into the card
ledger: no I/O, no clock.

WHERE THE RESULT COMES FROM
---------------------------
`results_for(store, date)`: the data store's final games whose Eastern game date is `date`, keyed by
the store's game id (the row's `game_pk`). Nothing here fetches anything; the owner's
`python -m src.datasvc.cli nfl update` is what brings a finished game's score into the store.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from src.analyst import grading as mlb_grading
from src.appstate import card_ledger

FAMILIES = ("moneyline", "spread", "total")
FAMILY_LABELS = {"moneyline": "Moneyline", "spread": "Point spread", "total": "Game total"}

WIN, LOSS, PUSH, VOID, UNRESOLVED, PASS = (mlb_grading.WIN, mlb_grading.LOSS, mlb_grading.PUSH,
                                           mlb_grading.VOID, mlb_grading.UNRESOLVED, mlb_grading.PASS)
SETTLED = mlb_grading.SETTLED
spec_for = mlb_grading.spec_for           # generic: family, side, line, reference price


def _grade_bet(spec: Mapping, price: Any, game_pk: Any, result: Optional[Mapping]) -> dict:
    family = spec.get("family")
    if result is None:
        return {"result": UNRESOLVED, "profit_units": 0.0,
                "reason": "no final score stored for this game yet"}
    pick = {"game_pk": game_pk, "market": family, "side": spec.get("side"),
            "line": spec.get("line"), "price": price}
    if family == "moneyline":
        away, home = card_ledger._score(result.get("away_score")), card_ledger._score(result.get("home_score"))
        if away is not None and home is not None and away == home and not result.get("void"):
            return {"result": PUSH, "profit_units": 0.0, "reason": "the game ended in a tie"}
        graded = card_ledger.grade_pick(pick, result)
    elif family == "spread":
        graded = card_ledger.grade_pick(pick, result)
    elif family == "total":
        graded = card_ledger.grade_total_pick(pick, result)
    else:
        return {"result": VOID, "profit_units": 0.0, "reason": f"unknown market family {family!r}"}
    out = {"result": graded["result"], "profit_units": graded.get("profit_units")}
    if graded.get("reason"):
        out["reason"] = graded["reason"]
    return out


def grade_call(call: Mapping, game_pk: Any, result: Optional[Mapping]) -> dict:
    """One published call, graded. A TAKE (either kind) is a bet at its price; a PASS is not, and
    reports `would_have` instead."""
    spec = call.get("grading") or {}
    base = {"slot_id": call["slot_id"], "family": spec.get("family"), "stat": None, "player": None,
            "selection": call["selection"], "verdict": call["verdict"],
            "price": call.get("price"), "book": call.get("book")}
    if call["verdict"] in ("TAKE", "TAKE_OTHER_SIDE"):
        base.update(_grade_bet(spec, call.get("price"), game_pk, result))
        return base
    ref = call.get("price") if call.get("price") is not None else spec.get("reference_price")
    base.update({"result": PASS, "profit_units": None, "would_have": None})
    if ref is not None:
        would = _grade_bet(spec, ref, game_pk, result)
        if would["result"] != UNRESOLVED:
            base["would_have"] = {"result": would["result"], "price": ref}
    return base


def grade_game(published: Mapping, result: Optional[Mapping], box_rows=None) -> dict:
    """The graded body for one published row: every call, whether every BET has a settled result
    (`complete`) and the final score when known. `box_rows` is accepted for the ledger's grader
    signature and unused (there are no props)."""
    pk = published.get("game_pk")
    calls = [grade_call(c, pk, result) for c in published.get("calls") or []]
    bets = [c for c in calls if c["verdict"] in ("TAKE", "TAKE_OTHER_SIDE")]
    complete = all(c["result"] in SETTLED for c in bets) and (bool(bets) or result is not None)
    final = None
    if result is not None:
        a, h = card_ledger._score(result.get("away_score")), card_ledger._score(result.get("home_score"))
        if a is not None and h is not None:
            final = {"away_score": a, "home_score": h}
    return {"calls": calls, "complete": bool(complete), "final": final}


def results_for(store, date: str) -> dict:
    """`{game_id: {"away_score", "home_score"}}` for the store's final games played on `date`.

    A game counts only with a `final` status AND two integer scores, and a status the store marks
    removed never does. Keys are the store's ids, which is what a published row's `game_pk` holds."""
    out = {}
    for game in store.games:
        if game.get("gameday") != date or game.get("status") != "final":
            continue
        away, home = card_ledger._score(game.get("away_score")), card_ledger._score(game.get("home_score"))
        if away is None or home is None:
            continue
        out[game["game_id"]] = {"away_score": away, "home_score": home}
    return out
