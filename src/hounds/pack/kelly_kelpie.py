"""Kelly the Kelpie: Bargain Bloodhound's picks, staked by a quarter Kelly."""

from __future__ import annotations

from typing import List

from src.core import staking
from src.hounds.pack import bargain_bloodhound
from src.hounds.pack.base import Context, Hound, Selection

FRACTION = 0.25
BANKROLL_UNITS = 100.0
MAX_STAKE = 3.0
MIN_STAKE = 0.05


def stake_for(fair: float, price_best: float) -> float:
    f = staking.kelly_fraction(fair, price_best)
    return round(min(MAX_STAKE, BANKROLL_UNITS * FRACTION * f), 2)


class KellyKelpie(Hound):
    id = "kelly_kelpie"
    name = "Kelly the Kelpie"
    tagline = "Bets the Kelly fraction."
    category = "math"
    style = "fractional Kelly staking"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    RULE = ("Same selections as Bargain Bloodhound. Stake = a quarter of the full Kelly fraction (consensus "
            "fair probability at the best price) of a 100-unit bankroll, capped at 3 units, rounded to 0.01; "
            "pass if under 0.05 units. Results scale by the stake.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        b = bargain_bloodhound.bargain(board)
        if b is None:
            return []
        m, side, info = b
        stake = stake_for(info["fair"], info["price_best"])
        if stake < MIN_STAKE:
            return []
        reason = f"Quarter Kelly at {info['price_best']:+d} with fair {info['fair']:.3f}: stake {stake:.2f} units."
        return [Selection("moneyline", side, round(m, 6), reason, stake=stake)]


HOUND = KellyKelpie()
