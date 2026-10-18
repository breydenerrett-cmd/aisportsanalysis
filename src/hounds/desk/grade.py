"""`grade`: settle the desk hounds' bets from the results the cards and the analyst already use.

SAME RESULTS, SAME RULES
------------------------
A bet is graded by the analyst's own grading code (`src/analyst/grading.py` for baseball,
`src/analyst/nfl_grading.py` for football), which calls the card ledger's `grade_pick` /
`grade_total_pick` and the props settlement rule against the same results store. The grading spec
(`family`, side, line, player, stat) was frozen into the bet row at publish, so grading needs no packet.

TWO FIGURES PER BET
-------------------
Flat one-unit paper stakes, settled twice from the one result: at the price taken (`units_best_price`, also
written as `units`, the field the leaderboard reader reads) and at the board's mean price
(`units_average_price`, the price a bettor who shopped nothing would have got). A push or void is 0 in both.
A bet whose game has no result yet stays ungraded (never a loss); the next `grade` picks it up.

THE CLOSING PRICE IS NOT HERE
-----------------------------
`close_price` and `clv_pts` are written null: the referee measures them from the odds store by event id
(`src/hounds/stats.py`), the one place that definition lives, and a second copy here could only disagree.

Pure apart from the append-only ledger: no clock beyond the injected one, no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from src.analyst import cli, grading, nfl_grading, nfl_pilot, pilot
from src.hounds.desk import ledger

EXIT_OK = 0

_LOWER = {grading.WIN: "win", grading.LOSS: "loss", grading.PUSH: "push", grading.VOID: "void"}


def grade(*, date: Optional[str] = None, results: Optional[Callable] = None, nfl_store=None,
          now: Optional[Callable] = None, out: Callable = print, root: Optional[Path] = None) -> int:
    """Grade every ungraded forward bet (of `date`, or all). `results(date)` is the baseball source
    `(results by game_pk, box rows)`, default `analyst.cli.default_results`; `nfl_store` is the football data
    store, default `nfl_pilot.default_store()`. Both are read once per date."""
    moment = (now or cli._now)()
    all_rows = ledger.rows(root)
    done = ledger.graded_ids(all_rows)
    pending = [r for r in all_rows if r.get("kind") == ledger.KIND_BET and r["bet_id"] not in done
               and (date is None or r["date"] == date)]
    chain = ledger.chain(root)
    wrote = unresolved = 0
    cache: dict = {}
    for bet in pending:
        key = (bet["sport"], bet["date"])
        if key not in cache:
            if bet["sport"] == "mlb":
                by_pk, box = (results or cli.default_results)(bet["date"])
                cache[key] = (by_pk, grading.index_box_rows(box))
            else:
                store = nfl_store if nfl_store is not None else nfl_pilot.default_store()
                cache[key] = (nfl_grading.results_for(store, bet["date"]), None)
        by_pk, boxed = cache[key]
        spec = bet.get("grading") or {}
        ref = bet.get("game_pk") if bet["sport"] == "mlb" else bet.get("nfl_game_id")
        result = by_pk.get(ref) or by_pk.get(str(ref))
        if bet["sport"] == "mlb":
            box_by_key, box_games = boxed
            best = grading._grade_bet(spec, bet["price_best"], ref, result, box_by_key, box_games)
            avg = grading._grade_bet(spec, bet["price_average"], ref, result, box_by_key, box_games)
        else:
            best = nfl_grading._grade_bet(spec, bet["price_best"], ref, result)
            avg = nfl_grading._grade_bet(spec, bet["price_average"], ref, result)
        if best["result"] not in _LOWER:
            unresolved += 1
            continue
        chain.append(ledger.graded_row(
            bet, result=_LOWER[best["result"]], units_best=best.get("profit_units"),
            units_average=avg.get("profit_units") if avg["result"] in _LOWER else None,
            graded_utc=pilot._iso(moment), note=best.get("reason")))
        wrote += 1
    out(f"graded {wrote} bet(s); {unresolved} still waiting for a result; {len(pending)} were ungraded")
    return EXIT_OK
