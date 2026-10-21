"""The decision: take the side with the stronger numerology case only when the case is clearly stronger and the price is fair; otherwise PASS and say why.

Checked in this order, and the first failure is the logged reason (``code``):

  no_history     we hold no stored results for this sport/league, so no count can be made; nothing is guessed
  no_facts       a team is unknown to the facts layer (no names to read)
  thin_data      fewer than ``min_milestones_per_side`` outcome-conditional counts in either world: too little to compare
  uneven_search  one world was searched much more than the other (a margin would then measure data coverage)
  no_board       no moneyline board at the lock (three books, inside the freshness window). NOT final: a later pass may find it
  small_margin   the stronger world does not lead by ``min_margin`` (a tie is a small margin)
  outside_band   the stronger side's average price is outside the band; never -200 or worse. The other side is NOT taken instead
  bet            all of the above passed

No price is used to CHOOSE a side; the price can only veto it. The module reads nothing after the lock: its inputs are the
signals (built from lock-time history) and the lock board.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from src.hounds.gematria import signals as sig_mod
from src.hounds.gematria.rules import Rules
from src.hounds.pack import base

CODES = ("no_history", "no_facts", "thin_data", "uneven_search", "no_board", "small_margin", "outside_band", "bet")
NEVER_LOGGED = ("no_history", "no_facts", "no_board")   # not covered, or not yet decidable: no decision row, no log clutter


@dataclass
class Verdict:
    status: str                     # "bet" | "pass"
    code: str
    reason: str
    side: Optional[str] = None
    market: str = "moneyline"
    price: Optional[int] = None
    margin: float = 0.0
    scores: dict = field(default_factory=dict)
    confidence: Optional[int] = None         # 1..5 from the margin, less one when the other side's case is nearly as strong (the posts' warning bullets)

    @property
    def is_bet(self) -> bool:
        return self.status == "bet"


def _pass(code: str, reason: str, sig: Optional[sig_mod.Signals] = None) -> Verdict:
    v = Verdict("pass", code, reason)
    if sig is not None:
        v.margin = sig.margin
        v.scores = {"home": sig.home.score, "away": sig.away.score}
    return v


def decide(sig: Optional[sig_mod.Signals], board: Mapping, rules: Rules, *, history_available: bool,
           teams_known: bool) -> Verdict:
    d = rules.decision
    if not history_available:
        return _pass("no_history", "no stored results for this sport, so no count can be made")
    if not teams_known:
        return _pass("no_facts", "a team is not in the facts layer")
    assert sig is not None
    if min(sig.home.milestones, sig.away.milestones) < d.min_milestones_per_side:
        return _pass("thin_data", f"only {sig.home.milestones} and {sig.away.milestones} counts for the two sides; "
                                  f"need {d.min_milestones_per_side} each", sig)
    hi, lo = max(sig.home.comparisons, sig.away.comparisons), min(sig.home.comparisons, sig.away.comparisons)
    if hi and (hi - lo) / hi > d.max_search_imbalance:
        return _pass("uneven_search", f"the two sides were searched {sig.home.comparisons} and {sig.away.comparisons} "
                                      "times; a margin would measure data coverage", sig)
    if "moneyline" not in d.markets or not (board.get("markets") or {}).get("moneyline"):
        return _pass("no_board", "no moneyline board at the lock", sig)
    margin = sig.margin
    if abs(margin) < d.min_margin:
        return _pass("small_margin", f"margin {abs(margin):g} is under the {d.min_margin:g} needed", sig)
    side = "home" if margin > 0 else "away"
    info = base.side_info(board, "moneyline", side)
    if info is None:
        return _pass("no_board", "the stronger side is not on the lock board", sig)
    price = int(info["price_average"])
    lo_p, hi_p = max(base.PRICE_MIN, d.price_band[0]), min(base.PRICE_MAX, d.price_band[1])
    if not (lo_p <= price <= hi_p) or price <= -200:
        v = _pass("outside_band", f"average price {price:+d} is outside the band ({lo_p:+d} to {hi_p:+d}; never -200 or worse)", sig)
        v.side, v.price = side, price
        return v
    winner, loser = sig.side(side).score, sig.side(sig_mod.other(side)).score
    conf = 1 + sum(1 for b in d.confidence_bands if abs(margin) >= b)
    if winner > 0 and loser / winner >= d.counter_signal_ratio:
        conf -= 1
    verdict = Verdict("bet", "bet", f"the {side} side leads the count {sig.side(side).score:g} to "
                                 f"{sig.side(sig_mod.other(side)).score:g} (margin {abs(margin):g})",
                   side=side, price=price, margin=margin, scores={"home": sig.home.score, "away": sig.away.score})
    verdict.confidence = max(1, min(5, conf))
    return verdict
