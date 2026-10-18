"""The paired slots of a challenger and its champion (docs/PREREG_LEARNING_LOOP.md section 5).

A SLOT is one game and one market. For each slot where either side bet, the value of a side is its
bet's closing-line value (points), or 0 if it passed, and the difference is
``challenger - champion``. Everything that can quietly bias that number is handled here, in the open:

  * MEASURABLE ONLY. A bet with no usable close (``clv_measurable`` false) makes its slot
    EXCLUDED, never zero. The count is returned, so the page can show it.
  * A PASS IS 0, BUT ONLY IF THE CHALLENGER WAS LOOKING. A champion bet in a slot where the
    challenger has no bet counts as the challenger passing only if the shadow runner actually covered
    that game (``covered``: the event ids it considered between lock and start). A shadow runner that
    was down for a day would otherwise "pass" on every game the champion bet, and since a typical bet's
    closing-line value is negative, that would hand every challenger a free win. Uncovered slots are
    excluded and counted.
  * SETTLED SLOTS ONLY, AND A STABLE PREFIX. A slot is final once its game started at least
    ``SETTLE_LAG_HOURS`` ago. Slots are ordered by lock time and the sample ends at the first slot not
    yet final, so "the first 100 slots" never changes after the fact (look k uses exactly the first
    n_k, whenever the referee runs).
  * FORWARD BETS FROM THE CHALLENGER'S START ONLY. The champion's earlier bets are not in the pair.

Pure: bets in, slots out. The closing-line values are attached upstream (``measure.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Optional

from src.hounds.learning import ledger as L
from src.hounds.learning import rules

TOL = 1e-12


@dataclass(frozen=True)
class Slot:
    event_id: str
    market: str
    date: str                     # slate date (the cluster)
    lock: str                     # the earlier decision time of the two bets
    champ: Optional[float]        # None = the champion passed
    chall: Optional[float]        # None = the challenger passed
    diff: float                   # (chall or 0) - (champ or 0)


@dataclass
class Pairing:
    slots: list = field(default_factory=list)       # final, chronological prefix
    excluded: int = 0                               # a bet without a measurable close
    uncovered: int = 0                              # champion bet, shadow runner did not look
    pending: int = 0                                # not final yet (the prefix stops before them)
    after_cut: int = 0                              # final slots after the first pending one

    def sample(self, n: int) -> list:
        return self.slots[:n]

    def dates_in(self, n: int) -> int:
        return len({s.date for s in self.slots[:n]})

    def volume(self, n: int) -> dict:
        part = self.slots[:n]
        return {"challenger_bets": sum(1 for s in part if s.chall is not None),
                "champion_bets": sum(1 for s in part if s.champ is not None)}


def volume_ok(vol: dict) -> bool:
    """The floor against winning by abstaining (prereg section 5)."""
    return (vol["challenger_bets"] >= rules.VOLUME_FLOOR_MIN_BETS
            and vol["challenger_bets"] >= rules.VOLUME_FLOOR_SHARE * vol["champion_bets"])


def volume_ok_analyst(vol: dict) -> bool:
    """The analyst arm's floor (prereg section 12): TAKE calls in at least half as many games as the
    champion prompt. The 50-bet minimum does not apply: a game's calls are not bets in that sense."""
    return vol["challenger_bets"] >= rules.ANALYST_MIN_TAKE_GAME_SHARE * vol["champion_bets"]


def volume_ok_for(kind: str, vol: dict) -> bool:
    return volume_ok_analyst(vol) if kind == "analyst" else volume_ok(vol)


def _key(bet) -> tuple:
    return (str(bet.event_id), str(bet.market_key))


def _usable(bet) -> bool:
    return bool(bet.clv_measurable and bet.clv_pts is not None)


def build(champion_bets: Iterable, challenger_bets: Iterable, *, since: datetime, as_of: datetime,
          covered: set) -> Pairing:
    """The pairing of one challenger. ``champion_bets`` are the champion VERSION's bets,
    ``challenger_bets`` the challenger's own; both with ``clv_pts`` / ``clv_measurable`` attached."""
    champ = {}
    for b in champion_bets:
        if b.segment != "forward" or not b.event_id:
            continue
        locked = L.parse(b.decision_utc)
        if locked is None or locked < since:
            continue
        champ.setdefault(_key(b), b)
    chall = {}
    for b in challenger_bets:
        if b.segment != "forward" or not b.event_id:
            continue
        locked = L.parse(b.decision_utc)
        if locked is None or locked < since:          # the engines never write one; the pair never reads one
            continue
        chall.setdefault(_key(b), b)

    out = Pairing()
    final = []
    pending_locks = []
    lag = timedelta(hours=rules.SETTLE_LAG_HOURS)
    for key in sorted(set(champ) | set(chall)):
        cb, hb = champ.get(key), chall.get(key)
        ref = cb or hb
        start = L.parse(ref.start_utc)
        lock_text = min(x for x in (cb.decision_utc if cb else None, hb.decision_utc if hb else None) if x)
        if start is None or start + lag > as_of:
            pending_locks.append(lock_text)
            out.pending += 1
            continue
        if hb is None and key[0] not in covered:
            out.uncovered += 1
            continue
        if (cb is not None and not _usable(cb)) or (hb is not None and not _usable(hb)):
            out.excluded += 1
            continue
        c_val = cb.clv_pts if cb is not None else None
        h_val = hb.clv_pts if hb is not None else None
        final.append(Slot(event_id=key[0], market=key[1], date=str(ref.date)[:10], lock=lock_text,
                          champ=c_val, chall=h_val, diff=(h_val or 0.0) - (c_val or 0.0)))
    final.sort(key=lambda s: (s.lock, s.event_id, s.market))
    if pending_locks:
        cut = min(pending_locks)
        kept = [s for s in final if s.lock < cut]
        out.after_cut = len(final) - len(kept)
        final = kept
    out.slots = final
    return out
