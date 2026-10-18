"""Closing-line values for a champion's bets and its challengers', by the referee's own machinery.

One streaming pass over the captured odds (``boards.scan``, the same pass the public stats run) and
the unchanged ``src.report.clv`` measurement (``stats.attach_clv``): the number a challenger is judged
on is, to the decimal, the number the race shows for a champion (docs/PREREG_HOUND_VERDICT.md).
The pass costs seconds and runs in the batch commands (referee, scorecard), never on a request.

``attach`` is the seam tests replace: a fixture hands the referee bets whose ``clv_pts`` are set.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from src.hounds import boards, ledgers, stats
from src.hounds.learning import ledger as L


def attach(bets: Sequence, multibook_path=None) -> None:
    """Fill ``clv_pts`` / ``clv_measurable`` on ``bets`` in place (the real measurement)."""
    if not bets:
        return
    from src.pipeline import snapshots
    path = multibook_path or snapshots.DEFAULT_MULTIBOOK_PATH
    dated = [b.date for b in bets if b.date]
    index, _teams = boards.scan(list(bets), path, since=min(dated) if dated else None)
    stats.attach_clv(list(bets), index)


class BetSource:
    """Reads both ledgers of a scope once and answers ``(champion_bets, challenger_bets)`` per
    challenger, with closing-line values attached by ONE scan over everything wanted."""

    def __init__(self, scope: L.Scope, champion_ledger, *, attach_fn: Optional[Callable] = None):
        self.scope = scope
        self.champion_ledger = champion_ledger
        self.attach_fn = attach_fn or attach
        self._champ: Optional[list] = None
        self._chall: Optional[list] = None

    def load(self, challengers: Sequence[L.Challenger]) -> None:
        champ_all, _ = ledgers.pack_ledger_rows(self.champion_ledger)
        chall_all, _ = ledgers.pack_ledger_rows(self.scope.challenger_bets)
        want_champ = set()
        for c in challengers:
            want_champ.add(c.parent_ref if c.kind == "user" else c.hound_id)
        champ = [b for b in champ_all if b.hound_id in want_champ and b.segment == "forward"]
        ids = {c.id for c in challengers}
        chall = [b for b in chall_all if b.hound_id in ids and b.segment == "forward"]
        self.attach_fn(champ + chall)
        self._champ, self._chall = champ, chall

    def bets_for(self, c: L.Challenger) -> tuple:
        if self._champ is None:
            self.load([c])
        if c.kind == "user":
            champ = [b for b in self._champ if b.hound_id == c.parent_ref]
        else:
            champ = [b for b in self._champ if b.hound_id == c.hound_id
                     and b.hound_version == c.parent_version]
        return champ, [b for b in self._chall if b.hound_id == c.id]


def matured_lookup(state: L.State, champion_ledger, *, attach_fn: Optional[Callable] = None) -> Callable:
    """``fn(promotion) -> (mean of the first 100 measurable bets, how many measurable) | None`` for the
    scorecard's promotion hit rate (prereg section 9b): the NEW champion version's own forward bets
    since its promotion. Reads the champion ledger once and measures once."""
    promos = [p for p in state.promotions if p.get("applied")]
    if not promos:
        return lambda promo: None
    attach_fn = attach_fn or attach
    bets, _defs = ledgers.pack_ledger_rows(champion_ledger)
    mine = {}
    for p in promos:
        if p.get("kind_of") == "user":
            hid = p.get("new_hound_id")
            picked = [b for b in bets if b.hound_id == hid] if hid else []
        else:
            picked = [b for b in bets if b.hound_id == p.get("hound_id")
                      and b.hound_version == int(p["to_version"])]
        since = L.parse(p.get("effective_utc") or p.get("utc"))
        picked = [b for b in picked if b.segment == "forward"
                  and (L.parse(b.decision_utc) or since) >= since]
        mine[p["challenger_id"]] = picked
    attach_fn([b for group in mine.values() for b in group])

    def fn(promo: dict):
        usable = sorted((b for b in mine.get(promo.get("challenger_id"), [])
                         if b.clv_measurable and b.clv_pts is not None),
                        key=lambda b: (b.decision_utc or "", b.event_id or ""))
        if not usable:
            return None
        from src.hounds.learning import rules
        first = usable[:rules.MATURE_BETS]
        return round(sum(b.clv_pts for b in first) / len(first), 4), len(usable)

    return fn
