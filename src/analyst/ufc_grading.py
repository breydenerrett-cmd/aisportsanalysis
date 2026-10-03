"""Grading a UFC analyst call from the data layer's bout results.

THE RESULTS ARE THE DATA LAYER'S
--------------------------------
A bout's result is read from the bout record the data layer holds
(`winner_id`, `result_method`, `result_method_raw`, `end_round`, `end_time_s`,
`status`). Nothing here looks at a card, at a result provider, or at the MLB
grader's inputs: the UFC analyst's record is its own.

THREE FAMILIES, GRADED AND COUNTED ON THEIR OWN
-----------------------------------------------
`moneyline`, `method` (a fighter to win by one method) and `rounds_total`. A
record that blended them would let a good run on one hide a bad one on another.

THE RULES
---------
Moneyline    WIN when the fighter the call backs is the recorded winner, LOSS when
             the other fighter is. A disqualification win is a win.
Method       WIN when the backed fighter won AND the way he won is the priced
             method. `KO_TKO` and `DQ` are "ko_tko_dq"; `SUB` is "submission";
             `DEC_UNANIMOUS`, `DEC_SPLIT`, `DEC_MAJORITY` and the generic
             `DECISION` are "decision". LOSS otherwise (the other man won, or he
             won another way). `OTHER` is a VOID unless its raw label says it was a
             stoppage by the doctor (`tko---doctors-stoppage`: all 11 `OTHER` results
             among the 1,591 finished bouts in the store on 2026-10-03), which every
             book's method market counts as a TKO.
Rounds total The elapsed fight time is (end_round - 1) x 300 + end_time_s seconds
             (a UFC round is five minutes in every bout), compared with the line
             in rounds x 300. Over wins when the bout lasted longer than the line,
             Under when it ended before it. A bout that went the distance ends at
             the last round's 300 seconds, so it is over every line below its
             scheduled rounds.

THE HALF-ROUND BOUNDARY
-----------------------
A line is a half-round ("over 2.5": past the middle of the third round). A bout that
ends EXACTLY on the line (2:30 of round 3 against 2.5) is a PUSH: the stake comes
back, neither Over nor Under wins. That is the usual treatment of a total that lands
on its line and the only one that does not pick a winner by an arbitrary clock
tie-break. It was NOT checked against any one book's published rule (this module has
no network), so it is stated here and in docs/AI_ANALYST.md for the record to be
checked against. It is rare (4 of the 1,591 timed bouts in the store on 2026-10-03
ended at exactly 150.0 seconds) and a book's own rule, if it differs, is a `correction`
row away. Seconds are compared, never floats of rounds, so 4.5 x 300 = 1350 is exact.

DRAWS, NO CONTESTS, CANCELLATIONS
---------------------------------
A draw and a no contest are VOID in every family (the stake comes back, the call is
neither a win nor a loss), and so is a bout the data layer marks canceled. A bout
that is not final yet (scheduled, in progress, postponed) is UNRESOLVED: never a
loss, never a void, so an unfought bout does not look like a bad night. A final bout
the store has no usable result for (no winner, no end time) is UNRESOLVED too,
because a later ingest may supply it, and the record counts it as unresolved until it
does.

A PASS is not a bet. Like the MLB grader it carries `would_have`, the result the
passed side would have had at its best quoted price, so the record can show whether
the passes were right without counting them as wins or losses.

Returns are flat one-unit stakes at the published price: a way to add results up, not
a claim that anyone staked anything.

Pure: no I/O, no clock.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from src.analyst import grading

FAMILIES = ("moneyline", "method", "rounds_total")
FAMILY_LABELS = {"moneyline": "Moneyline", "method": "Method of victory",
                 "rounds_total": "Rounds total"}

WIN, LOSS, PUSH, VOID, UNRESOLVED, PASS = (grading.WIN, grading.LOSS, grading.PUSH, grading.VOID,
                                           grading.UNRESOLVED, grading.PASS)
SETTLED = grading.SETTLED

ROUND_SECONDS = 300.0

METHODS = ("ko_tko_dq", "submission", "decision")

# The data layer's `result_method` values, as the three method-of-victory prices.
METHOD_OF_RESULT = {
    "KO_TKO": "ko_tko_dq", "DQ": "ko_tko_dq", "SUB": "submission",
    "DEC_UNANIMOUS": "decision", "DEC_SPLIT": "decision", "DEC_MAJORITY": "decision",
    "DECISION": "decision",
}

# `OTHER` hides the doctor's stoppage (raw label "tko---doctors-stoppage"). A TKO in every
# book's method market, so it is read as one; any other OTHER is not guessed at.
OTHER_TKO_PREFIX = "tko"

METHOD_WORDS = {
    "KO_TKO": "KO/TKO", "SUB": "submission", "DEC_UNANIMOUS": "unanimous decision",
    "DEC_SPLIT": "split decision", "DEC_MAJORITY": "majority decision", "DECISION": "decision",
    "DQ": "disqualification",
}
FINISHES = ("KO_TKO", "SUB", "DQ")


# ---------------------------------------------------------------------------
# the grading spec, frozen into the published row
# ---------------------------------------------------------------------------

def spec_for(market: Mapping, selection: str, bout: Mapping) -> dict:
    """What grading needs to know about one call, frozen into the published row so a
    result can be graded without the packet. `bout` is the packet's `bout` block.
    `reference_price` is the best quote at publication, used only to say what a PASS
    would have done."""
    opt = next((o for o in market["options"] if o["selection"] == selection), None)
    ctx = market.get("context") or {}
    family = market["market"]
    side = (opt or {}).get("side")
    fighter_side = side if family == "moneyline" else ctx.get("fighter_side")
    fighter = bout.get({"a": "fighter_a", "b": "fighter_b"}.get(fighter_side)) or {}
    best = (opt or {}).get("best") or {}
    return {
        "family": family,
        "side": side,
        "line": (opt or {}).get("line"),
        "fighter_side": fighter_side,
        "fighter_id": fighter.get("id"),
        "fighter_name": fighter.get("name"),
        "method": ctx.get("method"),
        "reference_price": best.get("price"),
    }


# ---------------------------------------------------------------------------
# reading a result
# ---------------------------------------------------------------------------

def method_bucket(bout: Mapping) -> Optional[str]:
    """The method-of-victory price a recorded result settles, or None."""
    method = bout.get("result_method")
    if method in METHOD_OF_RESULT:
        return METHOD_OF_RESULT[method]
    if method == "OTHER" and str(bout.get("result_method_raw") or "").lower().startswith(OTHER_TKO_PREFIX):
        return "ko_tko_dq"
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) != float("inf") else None


def elapsed_seconds(bout: Mapping) -> Optional[float]:
    """Seconds fought, from the end round and the clock in it; None when either is
    missing or the clock is outside a round (a bad record is not graded on)."""
    rnd, clock = _number(bout.get("end_round")), _number(bout.get("end_time_s"))
    if rnd is None or clock is None or rnd < 1 or rnd != int(rnd) or not 0 <= clock <= ROUND_SECONDS:
        return None
    return (int(rnd) - 1) * ROUND_SECONDS + clock


def _units(won: bool, price: Any) -> Optional[float]:
    return grading._units(won, price)


def _verdict_of(won: bool, price: Any) -> dict:
    units = _units(won, price)
    if units is None:
        return {"result": VOID, "profit_units": 0.0, "reason": f"unusable published price {price!r}"}
    return {"result": WIN if won else LOSS, "profit_units": units}


def _gate(bout: Optional[Mapping]) -> Optional[dict]:
    """A grade that holds for every family, or None when the bout has a result to read."""
    if not bout:
        return {"result": UNRESOLVED, "profit_units": 0.0, "reason": "the bout is not in the results store"}
    status = bout.get("status")
    if status == "canceled":
        return {"result": VOID, "profit_units": 0.0, "reason": "the bout was canceled"}
    if status != "final":
        return {"result": UNRESOLVED, "profit_units": 0.0, "reason": f"the bout is {status}, not final"}
    method = bout.get("result_method")
    if method == "DRAW":
        return {"result": VOID, "profit_units": 0.0, "reason": "the bout was a draw"}
    if method == "NC":
        return {"result": VOID, "profit_units": 0.0, "reason": "the bout was a no contest"}
    return None


def _winner(bout: Mapping) -> tuple:
    """(winner id, why not). The winner must be one of the bout's two fighters."""
    winner = bout.get("winner_id")
    fighters = {str(bout.get("fighter_a_id")), str(bout.get("fighter_b_id"))}
    if winner in (None, ""):
        return None, "the bout is final but no winner is recorded"
    if str(winner) not in fighters:
        return None, "the recorded winner is neither of the bout's fighters"
    return str(winner), None


def _grade_bet(spec: Mapping, price: Any, bout: Optional[Mapping]) -> dict:
    gate = _gate(bout)
    if gate is not None:
        return gate
    family = spec.get("family")
    if family in ("moneyline", "method"):
        fighter = spec.get("fighter_id")
        if not fighter:
            return {"result": VOID, "profit_units": 0.0,
                    "reason": f"{family} call is missing the fighter it backs"}
        winner, why = _winner(bout)
        if winner is None:
            return {"result": UNRESOLVED, "profit_units": 0.0, "reason": why}
        if family == "moneyline":
            return _verdict_of(winner == str(fighter), price)
        wanted = spec.get("method")
        if wanted not in METHODS:
            return {"result": VOID, "profit_units": 0.0, "reason": "method call is missing its method"}
        if not bout.get("result_method"):
            return {"result": UNRESOLVED, "profit_units": 0.0, "reason": "no result method is recorded"}
        bucket = method_bucket(bout)
        if bucket is None:
            return {"result": VOID, "profit_units": 0.0,
                    "reason": f"the result method {bout.get('result_method')!r} cannot be matched to "
                              "a method of victory price"}
        return _verdict_of(winner == str(fighter) and bucket == wanted, price)
    if family == "rounds_total":
        line, side = spec.get("line"), spec.get("side")
        if not isinstance(line, (int, float)) or isinstance(line, bool) or side not in ("over", "under"):
            return {"result": VOID, "profit_units": 0.0, "reason": "rounds total call is missing its side or line"}
        elapsed = elapsed_seconds(bout)
        if elapsed is None:
            return {"result": UNRESOLVED, "profit_units": 0.0,
                    "reason": "no end round and time is recorded for this bout"}
        line_seconds = float(line) * ROUND_SECONDS
        if abs(elapsed - line_seconds) < 1e-6:
            return {"result": PUSH, "profit_units": 0.0,
                    "reason": "the bout ended exactly on the line, so the stake comes back"}
        return _verdict_of((elapsed > line_seconds) == (side == "over"), price)
    return {"result": VOID, "profit_units": 0.0, "reason": f"unknown market family {family!r}"}


# ---------------------------------------------------------------------------
# calls and bouts
# ---------------------------------------------------------------------------

def grade_call(call: Mapping, bout: Optional[Mapping]) -> dict:
    """One published call, graded. A TAKE (either kind) is a bet at its price; a PASS is
    not, and reports `would_have` instead."""
    spec = call.get("grading") or {}
    base = {"slot_id": call["slot_id"], "family": spec.get("family"),
            "fighter_id": spec.get("fighter_id"), "method": spec.get("method"),
            "selection": call["selection"], "verdict": call["verdict"],
            "price": call.get("price"), "book": call.get("book")}
    if call["verdict"] in ("TAKE", "TAKE_OTHER_SIDE"):
        base.update(_grade_bet(spec, call.get("price"), bout))
        return base
    ref = call.get("price") if call.get("price") is not None else spec.get("reference_price")
    base.update({"result": PASS, "profit_units": None, "would_have": None})
    if ref is not None:
        would = _grade_bet(spec, ref, bout)
        if would["result"] != UNRESOLVED:
            base["would_have"] = {"result": would["result"], "price": ref}
    return base


def final_block(bout: Optional[Mapping]) -> Optional[dict]:
    """What the result was, for the graded row; None until the bout is final or canceled."""
    if not bout:
        return None
    status = bout.get("status")
    if status == "canceled":
        return {"outcome": "canceled"}
    if status != "final":
        return None
    method = bout.get("result_method")
    outcome = "draw" if method == "DRAW" else "no_contest" if method == "NC" else "decided"
    return {"outcome": outcome, "winner_id": bout.get("winner_id") or None, "method": method,
            "method_raw": bout.get("result_method_raw"),
            "end_round": bout.get("end_round"), "end_time_s": bout.get("end_time_s")}


def grade_bout(published: Mapping, bout: Optional[Mapping]) -> dict:
    """The graded body for one published row: every call, whether every BET has a
    settled result (`complete`), and what the result was when known."""
    calls = [grade_call(c, bout) for c in published.get("calls") or []]
    bets = [c for c in calls if c["verdict"] in ("TAKE", "TAKE_OTHER_SIDE")]
    final = final_block(bout)
    complete = all(c["result"] in SETTLED for c in bets) and (bool(bets) or final is not None)
    return {"calls": calls, "complete": bool(complete), "final": final}


def result_text(final: Optional[Mapping], fighters: Mapping) -> Optional[str]:
    """The result in words, for the page: "Alex Archer won by KO/TKO in round 2".
    `fighters` is the published row's {"a": {"id", "name"}, "b": {...}}."""
    if not final:
        return None
    outcome = final.get("outcome")
    if outcome == "canceled":
        return "The bout was canceled."
    if outcome == "draw":
        return "The bout was a draw."
    if outcome == "no_contest":
        return "The bout was a no contest."
    winner = next((f.get("name") for f in fighters.values()
                   if str(f.get("id")) == str(final.get("winner_id"))), None)
    if not winner:
        return None
    method = final.get("method")
    words = METHOD_WORDS.get(method)
    finished = method in FINISHES
    if method == "OTHER" and method_bucket({"result_method": "OTHER",
                                             "result_method_raw": final.get("method_raw")}):
        words, finished = "doctor's stoppage", True
    text = f"{winner} won" + (f" by {words}" if words else "")
    if finished and isinstance(final.get("end_round"), int):
        text += f" in round {final['end_round']}"
    return text + "."
