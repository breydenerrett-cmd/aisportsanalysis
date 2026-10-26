"""The arithmetic of a real bet: parlay pricing, payout checks, and what a push or a void does to a ticket.

Everything here is pure (no disk, no clock) so each rule has a test that pins it.

THE RULES (each one a decision, none an accident):

  * A PARLAY WINS ONLY IF EVERY LEG WINS. One lost leg loses the ticket the moment it is known, whatever the other
    legs do. One winning leg beside an unfinished or lost leg is never a win (the bug this module exists to prevent).
  * A PUSH OR VOID LEG DROPS OUT. The ticket is repriced on the legs that are left (a dropped leg counts as decimal
    1.0, the standard book rule); a ticket with every leg dropped is a push (all pushes) or a void (all voids).
    Books differ on edge cases (a same-game parlay with a dropped leg, a leg voided for a scratched player), so a
    repriced ticket is returned with ``needs_confirmation`` true: the number is our arithmetic, and the book's own
    payout, when the ticket shows one, is what the ledger believes. We never say a repriced number is the book's.
  * CASH-OUT IS NOT A RESULT. Cashing out is the owner selling the ticket back for ``amount``: profit is
    amount - stake, and it is neither a win nor a loss for win-rate purposes (the game's outcome never decided it).
  * ROUNDING. A book shows a combined price as a whole number (+253 for a true +253.9), so a stake and payout are
    checked against the price's whole-number interval, not against one exact figure. See ``check_consistency``.

MONEY IS DOLLARS HERE (the real stake the member actually put up), unlike the paper hounds' units. The -200 cap is a
rule for a hound's OWN picks; a real bet the member made is logged at whatever price they got.
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.core import odds as odds_math

WON, LOST, PUSH, VOID = "won", "lost", "push", "void"
LEG_RESULTS = (WON, LOST, PUSH, VOID)
PENDING = "pending"

ROUNDING_POINTS = 1.0         # a displayed American price is a whole number: the true price is within one point of it
PAYOUT_SLACK_USD = 0.02       # two cents for the book's own per-step rounding


def dec(price) -> float:
    """American price -> decimal (total return per dollar staked). Raises ``ValueError`` for an impossible price."""
    try:
        return odds_math.american_to_decimal(price)
    except (odds_math.OddsError, TypeError, ValueError) as exc:
        raise ValueError(f"not an American price: {price!r}") from exc


def to_american(decimal: float) -> int:
    return int(round(odds_math.decimal_to_american(decimal)))


def parlay_decimal(prices: Sequence) -> float:
    out = 1.0
    for p in prices:
        out *= dec(p)
    return out


def money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def payout_for(stake: float, decimal: float) -> float:
    """What a winning ticket pays (stake included), to the cent."""
    return money(stake * decimal)


def _shift(price, delta: float) -> float:
    """Move a displayed price by ``delta`` points of decimal-ward change, staying out of the +100/-100 gap."""
    p = float(price) + (delta if price > 0 else -delta)
    if 0 <= p < 100:
        return 100.0
    if -100 < p < 0:
        return -100.0
    return p


def _interval(price) -> tuple:
    """The decimal prices a displayed whole-number American price could be hiding (price +/- one point)."""
    lo, hi = sorted((dec(_shift(price, -ROUNDING_POINTS)), dec(_shift(price, ROUNDING_POINTS))))
    return lo, hi


def _product(decs: Sequence[float]) -> float:
    out = 1.0
    for d in decs:
        out *= d
    return out


def check_consistency(*, leg_prices: Sequence, total_price, stake, payout) -> list:
    """Every way a ticket's own numbers disagree, as ``{"field", "reason"}`` dicts (empty list = consistent).

    Three checks, each skipped (never failed) when its inputs were not read:
      1. the legs' prices multiply to the ticket's combined price (each leg and the total are whole numbers);
      2. the payout is the stake times the combined price (the total's whole-number interval, two cents of slack);
      3. with no total shown, the payout agrees with the legs directly (widened by each leg's rounding).
    +253 and $100.18 pays $354.51 (a true +253.9), which the interval accepts and an exact multiply would not."""
    issues: list = []
    legs_dec = None
    if leg_prices and all(p is not None for p in leg_prices):
        try:
            legs_dec = [dec(p) for p in leg_prices]
        except ValueError:
            issues.append({"field": "legs", "reason": "a leg price is not a valid American price"})
    total_dec = None
    if total_price is not None:
        try:
            total_dec = dec(total_price)
        except ValueError:
            issues.append({"field": "total_odds", "reason": "the total price is not a valid American price"})
    if legs_dec is not None and total_dec is not None and len(legs_dec) > 1:
        product = _product(legs_dec)
        slack = sum(0.01 / d for d in legs_dec) * product + 0.01
        if abs(product - total_dec) > slack:
            issues.append({"field": "total_odds", "reason":
                           f"the legs multiply to {to_american(product):+d} but the ticket shows {int(total_price):+d}"})
    if stake is not None and payout is not None and stake > 0:
        if total_dec is not None:
            lo, hi = _interval(total_price)
            if not (stake * lo - PAYOUT_SLACK_USD <= payout <= stake * hi + PAYOUT_SLACK_USD):
                issues.append({"field": "payout", "reason":
                               f"a ${stake:.2f} stake at {int(total_price):+d} pays about ${stake * total_dec:.2f}, "
                               f"not ${payout:.2f}"})
        elif legs_dec is not None:
            product = _product(legs_dec)
            slack = sum(0.01 / d for d in legs_dec) * product * stake + PAYOUT_SLACK_USD
            if abs(stake * product - payout) > slack:
                issues.append({"field": "payout", "reason":
                               f"a ${stake:.2f} stake on those legs pays about ${stake * product:.2f}, not ${payout:.2f}"})
    return issues


def ticket_outcome(leg_results: Sequence[Optional[str]], leg_prices: Sequence, stake: float,
                   quoted_payout: Optional[float] = None) -> dict:
    """What the legs decide, by the parlay rules at the top of this module.

    ``leg_results`` holds one of won / lost / push / void, or None for a leg still open. Returns
    ``{"result": won|lost|push|void|pending, "payout", "profit", "repriced", "needs_confirmation", "open_legs"}``.
    A single is a one-leg ticket (the same rules, no special case). ``quoted_payout`` (the ticket's own to-pay figure)
    is believed for an all-won ticket; a repriced ticket never uses it, because it was quoted for the legs as bet."""
    n = len(leg_results)
    if n == 0 or n != len(leg_prices):
        raise ValueError("a ticket needs one result slot and one price per leg")
    stake = float(stake)
    open_legs = sum(1 for r in leg_results if r is None)
    if any(r == LOST for r in leg_results):
        return {"result": LOST, "payout": 0.0, "profit": -money(stake), "repriced": False,
                "needs_confirmation": False, "open_legs": open_legs}
    if open_legs:
        return {"result": PENDING, "payout": None, "profit": None, "repriced": False, "needs_confirmation": False,
                "open_legs": open_legs}
    alive = [p for p, r in zip(leg_prices, leg_results) if r == WON]
    dropped = [r for r in leg_results if r in (PUSH, VOID)]
    if not alive:
        result = VOID if all(r == VOID for r in dropped) else PUSH
        return {"result": result, "payout": money(stake), "profit": 0.0, "repriced": False,
                "needs_confirmation": False, "open_legs": 0}
    if not dropped:
        pay = money(quoted_payout) if quoted_payout is not None else payout_for(stake, parlay_decimal(alive))
        return {"result": WON, "payout": pay, "profit": money(pay - stake), "repriced": False,
                "needs_confirmation": False, "open_legs": 0}
    pay = payout_for(stake, parlay_decimal(alive))
    return {"result": WON, "payout": pay, "profit": money(pay - stake), "repriced": True,
            "needs_confirmation": True, "open_legs": 0}


def cash_out(stake: float, amount: float) -> dict:
    """The owner sold the ticket back: profit is what came back minus what went in (negative when it came back short)."""
    if amount is None or amount < 0:
        raise ValueError("a cash-out amount cannot be negative")
    return {"payout": money(amount), "profit": money(float(amount) - float(stake))}


PRICE_BANDS = (("-150 or shorter", None, -150), ("-149 to -110", -149, -110), ("-109 to +119", -109, 119),
               ("+120 to +249", 120, 249), ("+250 or longer", 250, None))


def price_band(price) -> str:
    """A coarse band for the analytics (an exact price is too thin to learn from). Whole-number American prices."""
    p = int(round(float(price)))
    for label, lo, hi in PRICE_BANDS:
        if (lo is None or p >= lo) and (hi is None or p <= hi):
            return label
    return "other"


def role_of(price) -> str:
    """"favourite" for a price shorter than even money, "plus money" for the rest (copy never says the other word)."""
    return "favourite" if float(price) < 0 else "plus money"
