"""The Odds API provider. Key-gated, fails safe, never invents a price.

WHAT THIS FETCHES
-----------------
All three markets the charter calls for: h2h (moneyline), spreads (run line),
and totals (over/under). An earlier build fetched only h2h, which meant three
of the four required outputs could never be produced.

ON THE KEY
----------
Everything here is gated on ODDS_API_KEY. Without it, every function returns a
clear not-configured result instead of raising, and the key is never printed,
logged, or included in an error message -- error text from this module is safe
to paste anywhere.

ON CREDITS
----------
The Odds API bills per request, and the cost scales with how many markets and
regions are requested. `estimate_credits` reports the cost of a call before it
is made, because a snapshot job running every 15 minutes across three markets
will exhaust a free tier in days if nobody checked the arithmetic first.

ON NOT INVENTING PRICES
-----------------------
If a book does not offer a market, that market is absent. It is never filled
with a neighbouring book's price, an average, or a default. A missing price
means no bet on that market, which is the correct outcome.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_HOST = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"
USER_AGENT = "aisportsanalysis/0.1 (stdlib urllib)"
DEFAULT_TIMEOUT = 20

ENV_KEY = "ODDS_API_KEY"
ENV_BOOK = "DEFAULT_BOOK"
ENV_REGION = "ODDS_API_REGION"

DEFAULT_REGION = "us"
DEFAULT_MARKETS = ("h2h", "spreads", "totals")
ODDS_FORMAT = "american"

SETUP_MESSAGE = (
    f"no {ENV_KEY}: copy .env.example to .env and add a key from "
    "the-odds-api.com (the free tier is sufficient)"
)


class OddsProviderError(RuntimeError):
    """Raised when the odds API cannot be reached or returns junk.

    Error text from this module never contains the API key.
    """


class NotConfigured(OddsProviderError):
    """Raised when an odds call is attempted with no API key present."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def api_key(env=None):
    """Read the key from the environment. Returns None when absent."""
    source = os.environ if env is None else env
    key = (source.get(ENV_KEY) or "").strip()
    return key or None


def is_configured(env=None) -> bool:
    return api_key(env) is not None


def status(env=None) -> dict:
    """Report configuration without ever exposing the key itself.

    Always succeeds, including with no key -- this is what a status endpoint
    or a preflight check calls, and it must never be the thing that fails.
    """
    source = os.environ if env is None else env
    configured = is_configured(source)
    return {
        "provider": "the-odds-api",
        "sport": "MLB",
        "configured": configured,
        "env_var": ENV_KEY,
        "default_book": (source.get(ENV_BOOK) or "").strip() or None,
        "region": (source.get(ENV_REGION) or "").strip() or DEFAULT_REGION,
        "markets": list(DEFAULT_MARKETS),
        "message": None if configured else SETUP_MESSAGE,
    }


def estimate_credits(markets=DEFAULT_MARKETS, regions=(DEFAULT_REGION,)) -> dict:
    """Credit cost of one odds request, before making it.

    The Odds API charges 1 credit per region per market for the odds endpoint.
    Requesting three markets in one region costs 3 credits per call -- so a
    job polling every 15 minutes costs 3 * 96 = 288 credits a day, which
    overruns a 500-credit monthly free tier in under two days.

    Knowing this before scheduling a snapshot job is the difference between a
    working pipeline and a dead one on the third of the month.
    """
    market_list = _validate_markets(markets)
    region_list = [r for r in regions if r]
    if not region_list:
        raise OddsProviderError("at least one region is required")
    per_call = len(market_list) * len(region_list)
    return {
        "markets": market_list,
        "regions": region_list,
        "credits_per_call": per_call,
        "calls_per_day_at_15min": 96,
        "credits_per_day_at_15min": per_call * 96,
        "free_tier_monthly": 500,
        "days_until_free_tier_exhausted": round(500 / (per_call * 96), 1),
    }


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _get_json(path: str, params: dict, timeout: int = DEFAULT_TIMEOUT):
    """Single network seam. Tests patch this and nothing else.

    Error messages are constructed without the URL so the key -- which travels
    as a query parameter -- can never leak into a log or a stack trace.
    """
    url = f"{API_HOST}/{path.lstrip('/')}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise OddsProviderError(
                "odds API rejected the key (HTTP 401) -- verify it is current"
            ) from None
        if exc.code == 429:
            raise OddsProviderError(
                "odds API quota exhausted (HTTP 429) -- check remaining credits"
            ) from None
        raise OddsProviderError(f"odds API returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise OddsProviderError(f"could not reach odds API: {exc.reason}") from None
    except json.JSONDecodeError:
        raise OddsProviderError("odds API returned invalid JSON") from None


def fetch_odds(markets=DEFAULT_MARKETS, region=None, env=None,
               timeout: int = DEFAULT_TIMEOUT):
    """Fetch current odds. Raises NotConfigured when no key is present."""
    source = os.environ if env is None else env
    key = api_key(source)
    if key is None:
        raise NotConfigured(SETUP_MESSAGE)
    params = {
        "apiKey": key,
        "regions": region or (source.get(ENV_REGION) or "").strip() or DEFAULT_REGION,
        "markets": ",".join(_validate_markets(markets)),
        "oddsFormat": ODDS_FORMAT,
    }
    return _get_json(f"sports/{SPORT}/odds", params, timeout=timeout)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_event(event: dict, preferred_book=None) -> dict:
    """Flatten one API event into per-market prices.

    Picks the preferred book when it offers the market, otherwise the first
    book that does. Markets no book offers are simply absent -- never filled
    with a substitute.
    """
    record = {
        "event_id": event.get("id"),
        "commence_time": event.get("commence_time"),
        "home_team": event.get("home_team"),
        "away_team": event.get("away_team"),
        "markets": {},
    }

    bookmakers = event.get("bookmakers") or []
    ordered = _order_books(bookmakers, preferred_book)

    for market_key in DEFAULT_MARKETS:
        for book in ordered:
            market = _find_market(book, market_key)
            if market is None:
                continue
            outcomes = _parse_outcomes(market, market_key, record)
            if outcomes is None:
                continue
            record["markets"][market_key] = {
                "book": book.get("key"),
                "last_update": market.get("last_update") or book.get("last_update"),
                **outcomes,
            }
            break

    return record


def _order_books(bookmakers, preferred_book):
    if not preferred_book:
        return list(bookmakers)
    preferred = [b for b in bookmakers if b.get("key") == preferred_book]
    others = [b for b in bookmakers if b.get("key") != preferred_book]
    return preferred + others


def _find_market(book, market_key):
    for market in book.get("markets") or []:
        if market.get("key") == market_key:
            return market
    return None


def _parse_outcomes(market, market_key, record):
    """Extract prices for one market, or None if the data is incomplete.

    Returning None rather than a partial record is deliberate: half a market is
    not usable, and a half-filled row invites a downstream default.
    """
    outcomes = market.get("outcomes") or []
    by_name = {o.get("name"): o for o in outcomes if o.get("name")}

    if market_key == "h2h":
        home = by_name.get(record["home_team"])
        away = by_name.get(record["away_team"])
        if not home or not away:
            return None
        if home.get("price") is None or away.get("price") is None:
            return None
        return {"home_price": home["price"], "away_price": away["price"]}

    if market_key == "spreads":
        home = by_name.get(record["home_team"])
        away = by_name.get(record["away_team"])
        if not home or not away:
            return None
        if any(x.get("price") is None or x.get("point") is None
               for x in (home, away)):
            return None
        return {
            "home_line": home["point"], "home_price": home["price"],
            "away_line": away["point"], "away_price": away["price"],
        }

    if market_key == "totals":
        over, under = by_name.get("Over"), by_name.get("Under")
        if not over or not under:
            return None
        if any(x.get("price") is None or x.get("point") is None
               for x in (over, under)):
            return None
        return {
            "total": over["point"],
            "over_price": over["price"], "under_price": under["price"],
        }

    return None


def normalize(events, preferred_book=None) -> list:
    """Normalize a full API response."""
    return [normalize_event(e, preferred_book=preferred_book) for e in events]


def fetch_normalized(markets=DEFAULT_MARKETS, region=None, env=None,
                     preferred_book=None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Fetch and normalize in one call, with a fetch timestamp.

    The timestamp matters for line-movement tracking: a price is only
    meaningful alongside when it was observed.
    """
    source = os.environ if env is None else env
    book = preferred_book or (source.get(ENV_BOOK) or "").strip() or None
    events = fetch_odds(markets=markets, region=region, env=source, timeout=timeout)
    normalized = normalize(events, preferred_book=book)
    return {
        "fetched_utc": datetime.now(timezone.utc).isoformat(),
        "preferred_book": book,
        "event_count": len(normalized),
        "events": normalized,
        "coverage": _coverage(normalized),
    }


def _coverage(events) -> dict:
    """How many events carried each market. Surfaces silent gaps."""
    counts = {market: 0 for market in DEFAULT_MARKETS}
    for event in events:
        for market in event.get("markets", {}):
            if market in counts:
                counts[market] += 1
    total = len(events)
    return {
        "events": total,
        "by_market": counts,
        "missing": {m: total - c for m, c in counts.items()},
    }


def _validate_markets(markets):
    market_list = [m.strip() for m in markets if isinstance(m, str) and m.strip()]
    if not market_list:
        raise OddsProviderError("at least one market is required")
    unknown = [m for m in market_list if m not in DEFAULT_MARKETS]
    if unknown:
        raise OddsProviderError(
            f"unsupported market(s) {', '.join(unknown)}; "
            f"expected any of {', '.join(DEFAULT_MARKETS)}"
        )
    return market_list
