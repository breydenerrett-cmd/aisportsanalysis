"""What the stored boards offered over a window: games a day, books quoting a game, and the prices, per sport and market.

Collected as a side effect of the one replay pass the impact meter already makes (``drill.impact_windows`` hands an instance to
``drill.run_user_many`` as its ``collector``), so the pre-build check (src/hounds/quiz/insight.py) reads the boards without a second
scan. Rows observed at or after their game's start are skipped, as the engine skips them. Pure counting: no model, no clock.
No FastAPI here.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Optional

# board row market -> the rule market ids it carries; side columns per market
_MARKET = {None: "moneyline", "h2h": "moneyline", "spreads": "spread", "totals": "total"}
_SIDES = {"moneyline": (("home", "home_price"), ("away", "away_price")),
          "spread": (("home", "home_price"), ("away", "away_price")),
          "total": (("over", "over_price"), ("under", "under_price"))}


class BoardStats:
    def __init__(self, first: str, last: str):
        self.first, self.last = first, last
        self._events: dict = {}          # (SPORT, market) -> {date: {event_id}}
        self._books: dict = {}           # (SPORT, market) -> {event_id: {book}}
        self._prices: dict = {}          # (SPORT, market, side) -> Counter(price)

    def __call__(self, window_rows: Mapping) -> None:
        for date, rows in window_rows.items():
            if date < self.first or date > self.last:
                continue
            for row in rows:
                market = _MARKET.get(row.get("market"))
                event_id = row.get("event_id")
                if market is None or not event_id:
                    continue
                observed, start = row.get("observed_utc"), row.get("commence_time")
                if observed is not None and start is not None and observed >= start:
                    continue
                key = (str(row.get("sport") or "mlb").upper(), market)
                self._events.setdefault(key, {}).setdefault(date, set()).add(event_id)
                book = row.get("book")
                if book:
                    self._books.setdefault(key, {}).setdefault(event_id, set()).add(book)
                for side, field in _SIDES[market]:
                    price = row.get(field)
                    if isinstance(price, (int, float)) and not isinstance(price, bool):
                        self._prices.setdefault(key + (side,), Counter())[int(price)] += 1

    def summary(self) -> dict:
        """{"SPORT|market": {games, max_per_day, books_median, books_max, prices: {side: Counter}}}."""
        out: dict = {}
        for key, by_day in self._events.items():
            sport, market = key
            sizes = sorted(len(b) for b in (self._books.get(key) or {}).values())
            out[f"{sport}|{market}"] = {
                "games": len(set().union(*by_day.values())) if by_day else 0,
                "max_per_day": max((len(v) for v in by_day.values()), default=0),
                "books_median": sizes[len(sizes) // 2] if sizes else 0,
                "books_max": sizes[-1] if sizes else 0,
                "prices": {side: dict(self._prices.get(key + (side,)) or {}) for side, _f in _SIDES[market]},
            }
        return out


def median_price(prices: Mapping) -> Optional[int]:
    """The middle price of a {price: count} table, or None."""
    flat = sorted(p for p, n in prices.items() for _ in range(min(int(n), 50)))
    return flat[len(flat) // 2] if flat else None


def in_band(prices: Mapping, low: Any, high: Any) -> int:
    """How many quotes in a {price: count} table sit inside [low, high] (a missing end is open)."""
    total = 0
    for price, n in prices.items():
        if low is not None and price < low:
            continue
        if high is not None and price > high:
            continue
        total += int(n)
    return total
