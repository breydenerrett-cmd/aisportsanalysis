"""The user scope's wiring: the effect of a promotion, and the periodic tick the hounds engine runs.

The user hounds live in the app database on the API's volume, so the user scope's referee, its
shadow runner and its scorecard run INSIDE the API process (``user_runner.run_pass`` calls ``tick``
after the champions' engine and settle). Everything is a no-op until a challenger exists, and a
challenger can only exist if the owner switched the coach on, so a server that never enabled the coach
pays one small file read per pass.

A PROMOTION'S EFFECT is ``user_store.create_version`` (the old version is retired as superseded and
keeps its spec, its ledger rows and its record; the new version has a new id and an empty record) plus
one diary row, ``decision: "applied"``, ``decided_by: "referee"``, so the owner's undo (which looks for
exactly such a row) works on a promoted version like on any coached one. It is IDEMPOTENT: if a
version with the challenger's rule already exists as a child of the champion, that one is returned.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.hounds import user_engine, user_spec, user_store
from src.hounds.learning import ledger as L
from src.hounds.learning import rules

REASON_MAX = 200


def apply_promotion(c: L.Challenger, promo: Mapping, *, db=None, now: Optional[datetime] = None) -> str:
    """Make the promoted challenger the next version of its user hound; return the new hound id."""
    champion = user_store.get_hound(c.parent_ref, db=db)
    if champion is None:
        raise user_store.StoreError("not_found", "the champion this challenger was born under is gone")
    want = user_spec.spec_hash(c.spec)
    for h in user_store.lineage(c.parent_ref, db=db):
        if h["version_of"] == c.parent_ref and h["spec_hash"] == want:
            return h["id"]
    reason = f"promoted challenger {c.id} (p_adj {promo.get('p_adj'):.4f}): {c.hypothesis}"[:REASON_MAX]
    new = user_store.create_version(c.parent_ref, c.spec, actor="referee", reason=reason, now=now, db=db)
    user_store.add_diary(
        round_id="referee", hound=champion, decision=user_store.DECISION_APPLIED, decided_by="referee",
        old_spec=champion["spec"], new_spec=c.spec, new_hound_id=new["id"], challenger_id=c.id,
        reason=reason, quip="", now=now, db=db)
    return new["id"]


def champion_current(c: L.Challenger, state: L.State, *, db=None) -> bool:
    """Is the hound the challenger was born under still the running champion? A retired or replaced
    (or deleted) parent means the pairing partner is gone."""
    parent = user_store.get_hound(c.parent_ref, db=db)
    return parent is not None and parent["status"] != user_store.STATUS_RETIRED


def champion_ledger() -> str:
    return user_engine.ledger_path()


def tick(*, now: datetime, ledger: Optional[str] = None, rows_for: Optional[Callable] = None,
         multibook_path: Optional[str] = None, game_pk_index: Optional[Mapping] = None,
         settle_kwargs: Optional[dict] = None, book=None, attach_fn: Optional[Callable] = None,
         scope: Optional[L.Scope] = None, daily: bool = True) -> dict:
    """One pass of the user scope, called by ``user_runner.run_pass`` after the champions' engine and
    settle. Cheap when nothing is going on (one small file read). Steps fail independently."""
    from src.hounds.learning import runner, shadow
    from src.hounds import user_runner
    champions_ledger = user_engine.ledger_path(ledger)
    sc = scope or L.Scope.user(Path(champions_ledger).parent)
    state = L.read_state(sc)
    live = [c for c in state.live() if c.kind == "user"]
    out: dict = {"live": len(live), "errors": []}
    if live:
        try:
            out["shadow"] = shadow.run_user(sc, user_runner.pass_dates(now), now=now, rows_for=rows_for,
                                            multibook_path=multibook_path, game_pk_index=game_pk_index)
            out["settled"] = shadow.settle_user(sc, now=now, **(settle_kwargs or {}))
        except Exception as exc:  # noqa: BLE001 -- the shadow pass never takes the champions' pass down
            out["errors"].append(f"shadow: {exc!r}")
    if daily and runner.scorecard_due(sc, now):
        try:
            out["referee"] = runner.run_referee(
                sc, now=now, champion_ledger=champions_ledger, attach_fn=attach_fn, kinds=("user",),
                champion_current=lambda c, st: champion_current(c, st),
                apply_user_promotion=lambda c, promo: apply_promotion(c, promo, now=now))
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"referee: {exc!r}")
        try:
            from src.hounds import stats
            out["scorecard"] = runner.run_scorecard(sc, now=now, book=book or stats.peek_book(),
                                                    champion_ledger=champions_ledger, attach_fn=attach_fn)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"scorecard: {exc!r}")
    return out
