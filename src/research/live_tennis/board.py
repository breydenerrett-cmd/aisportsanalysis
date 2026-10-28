"""A live match-winner board: quotes, freshness, consensus, best and average price.

Input is one raw The Odds API event (`bookmakers` -> `markets` -> `outcomes`), output plain dicts. Nothing
here knows the score, the model or the clock beyond the `not_before` instant a caller hands it.

FRESH (docs/PREREG_LIVE_TENNIS.md section 5): a quote is fresh only if the book's own `last_update` is AT OR
AFTER `not_before`. For a decision, `not_before` is `t_c`, the moment OUR poll first saw the previous set
completed, so a fresh quote cannot be a price from before the set's result. That is stricter than needed on
purpose: a stale quote sits on the side that just WON the set, and betting it then measuring against any later
price manufactures a positive closing-line value no real bettor could have captured. A quote with no readable
`last_update` is stale.

AVERAGE price here means the mean RAW (vig-included) implied probability over the fresh books: the break-even
of the board average, the convention of `docs/PREREG_INFO_TIMING.md`. BEST means the highest decimal odds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from src.core import odds as core_odds

H2H = "h2h"


def parse_utc(value) -> Optional[datetime]:
    """An aware UTC datetime from an ISO string or datetime, else None. Never guesses a zone-less time away from UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _price(value) -> Optional[float]:
    """A valid American price or None: a real number, not a bool, at least 100 in magnitude."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or abs(value) < 100:
        return None
    return float(value)


def parse_quotes(event: Mapping) -> List[dict]:
    """Every book's two-sided match-winner quote on one raw event, sorted by book key.

    -> [{book, last_update, home_price, away_price}]. A book missing a side, with an unknown outcome name, or
    with an invalid price contributes nothing (half a market is not a quote). `last_update` is the market's own
    stamp, else the book's, as the vendor wrote it (a string), or None.
    """
    home, away = event.get("home_team"), event.get("away_team")
    out: List[dict] = []
    for book in event.get("bookmakers") or []:
        if not isinstance(book, Mapping):
            continue
        for market in book.get("markets") or []:
            if not isinstance(market, Mapping) or market.get("key") != H2H:
                continue
            by_name = {o.get("name"): o for o in market.get("outcomes") or [] if isinstance(o, Mapping)}
            home_price = _price((by_name.get(home) or {}).get("price"))
            away_price = _price((by_name.get(away) or {}).get("price"))
            if home_price is None or away_price is None or home == away:
                continue
            out.append({"book": book.get("key"), "last_update": market.get("last_update") or book.get("last_update"),
                        "home_price": home_price, "away_price": away_price})
            break
    out.sort(key=lambda q: str(q["book"]))
    return out


def split_fresh(quotes: Iterable[Mapping], not_before: datetime) -> Tuple[List[dict], List[dict]]:
    """(fresh, stale): fresh iff `last_update` parses and is at or after `not_before`. Order is kept."""
    fresh, stale = [], []
    for quote in quotes:
        stamp = parse_utc(quote.get("last_update"))
        (fresh if stamp is not None and stamp >= not_before else stale).append(dict(quote))
    return fresh, stale


def _implied(price: float) -> float:
    return core_odds.american_to_probability(price)


def board_stats(quotes: Sequence[Mapping]) -> Optional[dict]:
    """Consensus, best and average price over `quotes` (call it with the FRESH quotes), or None when empty.

    -> {n_books, consensus_home, consensus_away, avg_implied_home, avg_implied_away, best_home, best_away,
        best_implied_sum, overround_median}; best_* = {price, book, implied}.
    """
    quotes = list(quotes)
    if not quotes:
        return None
    fair_home, imp_home, imp_away, overrounds = [], [], [], []
    for quote in quotes:
        ih, ia = _implied(quote["home_price"]), _implied(quote["away_price"])
        imp_home.append(ih)
        imp_away.append(ia)
        overrounds.append(ih + ia)
        fair_home.append(core_odds.devig_two_way(quote["home_price"], quote["away_price"])[0])
    n = len(quotes)

    def best(side: str) -> dict:
        key = f"{side}_price"
        top = max(quotes, key=lambda q: (core_odds.american_to_decimal(q[key]), -quotes.index(q)))
        return {"price": top[key], "book": top["book"], "implied": _implied(top[key])}

    best_home, best_away = best("home"), best("away")
    overrounds.sort()
    middle = overrounds[n // 2] if n % 2 else 0.5 * (overrounds[n // 2 - 1] + overrounds[n // 2])
    consensus_home = sum(fair_home) / n
    return {
        "n_books": n,
        "consensus_home": consensus_home,
        "consensus_away": 1.0 - consensus_home,
        "avg_implied_home": sum(imp_home) / n,
        "avg_implied_away": sum(imp_away) / n,
        "best_home": best_home,
        "best_away": best_away,
        "best_implied_sum": best_home["implied"] + best_away["implied"],
        "overround_median": middle,
    }


def side_view(stats: Mapping, side: str) -> dict:
    """One side of `board_stats`: {consensus, avg_implied, best_price, best_book, best_implied}. side is 'home' or 'away'."""
    if side not in ("home", "away"):
        raise ValueError("side must be 'home' or 'away'")
    best = stats[f"best_{side}"]
    return {"consensus": stats[f"consensus_{side}"], "avg_implied": stats[f"avg_implied_{side}"],
            "best_price": best["price"], "best_book": best["book"], "best_implied": best["implied"]}
