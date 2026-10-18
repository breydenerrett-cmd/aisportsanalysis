"""The batch steps shared by the operator CLI (house scope) and the API process's tick (user scope).

  shadow     run the live challengers on today's boards (shadow.py), settle them
  referee    examine looks, batch the month, promote or retire (referee.py)
  scorecard  the daily system scorecard and the auto-pause (scorecard.py)

Each step is independent and returns a small report; a step that cannot run says why instead of
raising, so one missing input (no stats book yet, no odds store on this machine) never stops the
steps that can.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Mapping, Optional

from src.hounds.learning import ledger as L
from src.hounds.learning import measure, rules, scorecard
from src.hounds.learning.referee import Referee


def run_referee(scope: L.Scope, *, now: datetime, champion_ledger, attach_fn: Optional[Callable] = None,
                champion_current: Optional[Callable] = None,
                apply_user_promotion: Optional[Callable] = None,
                kinds: tuple = ("pack", "user")) -> dict:
    """One referee run, if there is anything for it to do (a live challenger or an unapplied promotion)."""
    state = L.read_state(scope)
    live = [c for c in state.live() if c.kind in kinds]
    if not live and not state.unapplied_promotions():
        return {"scope": scope.name, "skipped": "no live challengers and nothing to apply"}
    src = measure.BetSource(scope, champion_ledger, attach_fn=attach_fn)
    src.load(live)
    return Referee(scope, now=now, bets_for=src.bets_for, champion_current=champion_current,
                   apply_user_promotion=apply_user_promotion, kinds=kinds).run()


def hound_info_from_book(book) -> dict:
    return {hid: {"kind": d.summary.kind, "category": d.summary.category, "status": d.summary.status}
            for hid, d in book.hounds.items()}


def run_scorecard(scope: L.Scope, *, now: datetime, book, champion_ledger,
                  attach_fn: Optional[Callable] = None) -> dict:
    """Store today's scorecard (once per date) and apply the pause rule. Needs the stats book."""
    if book is None:
        return {"scope": scope.name, "skipped": "the public stats book is not built yet"}
    state = L.read_state(scope)
    matured = measure.matured_lookup(state, champion_ledger, attach_fn=attach_fn)
    out = scorecard.run_daily(scope, now=now, clv_bets=book.clv_bets, hound_info=hound_info_from_book(book),
                              matured_fn=matured)
    out.pop("payload", None)
    out["scope"] = scope.name
    return out


def scorecard_due(scope: L.Scope, now: datetime) -> bool:
    today = now.astimezone(L.timezone.utc).date().isoformat()
    return not any(str(sc.get("date")) == today for sc in L.read_state(scope).scorecards)
