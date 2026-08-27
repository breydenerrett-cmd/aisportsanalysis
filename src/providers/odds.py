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
ENV_MARKETS = "ODDS_API_MARKETS"
ENV_ODDS_FORMAT = "ODDS_API_ODDS_FORMAT"

DEFAULT_REGION = "us"
DEFAULT_MARKETS = ("h2h", "spreads", "totals")

# First-five-innings markets. These are NOT available on the featured /odds endpoint
# -- it answers 422 INVALID_MARKET for them, verified against the live API -- and are
# only served per event by /events/{id}/odds.
#
# THE COST SHAPE IS COMPLETELY DIFFERENT AND IT DRIVES THE DESIGN
# ---------------------------------------------------------------
# Featured /odds bills markets x regions ONCE for the whole slate. The per-event
# endpoint bills markets x regions PER EVENT. Measured live: 2 markets on one event
# cost 2 credits, so a 16-game slate at 2 F5 markets is 32 credits a snapshot, and
# the 500-credit free month buys about fifteen full-slate F5 snapshots. Fetching the
# whole slate's first-five prices four times a day would exhaust a month in under
# two days.
#
# So F5 is fetched for NAMED EVENTS ONLY. That is not a limitation worked around; it
# is the mismatch scanner's output used as it was meant to be. A scanner that stays
# quiet on twelve of fifteen games is what makes first-five pricing affordable at
# all, and a scanner that fired on everything would be unaffordable regardless of
# whether it was right.
EVENT_MARKETS = ("h2h_1st_5_innings", "spreads_1st_5_innings", "totals_1st_5_innings")

# Everything a caller may legitimately name. Kept separate from DEFAULT_MARKETS,
# which is what gets requested when nothing is configured -- conflating "allowed"
# with "default" is what previously made an F5 market unnameable.
SUPPORTED_MARKETS = DEFAULT_MARKETS + EVENT_MARKETS
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

def configured_markets(env=None):
    """Markets to request, honouring ODDS_API_MARKETS.

    This setting has been advertised in .env.example since the beginning and was
    never read, so every request spent three credits whether or not three markets
    were wanted. Credits-per-call is exactly the input recommend_live_schedule()
    uses to choose a cadence against the free tier, so ignoring it meant the
    snapshot schedule could only ever run at a third of its achievable frequency.
    """
    source = os.environ if env is None else env
    raw = (source.get(ENV_MARKETS) or "").strip()
    if not raw:
        return list(DEFAULT_MARKETS)
    return _validate_markets([m.strip() for m in raw.split(",")])


def configured_odds_format(env=None) -> str:
    """Odds format, honouring ODDS_API_ODDS_FORMAT.

    Only american is supported downstream -- every conversion in src/core/odds.py
    assumes it -- so an unsupported value is rejected loudly rather than silently
    returning decimal prices that would be misread as American.
    """
    source = os.environ if env is None else env
    raw = (source.get(ENV_ODDS_FORMAT) or "").strip().lower()
    if not raw:
        return ODDS_FORMAT
    if raw != ODDS_FORMAT:
        raise OddsProviderError(
            f"unsupported {ENV_ODDS_FORMAT}={raw!r}; this project's odds maths "
            f"assumes {ODDS_FORMAT} prices throughout, and a decimal price read "
            "as American would be silently wrong"
        )
    return raw


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
        "markets": configured_markets(source),
        "message": None if configured else SETUP_MESSAGE,
    }


def estimate_credits(markets=None, regions=(DEFAULT_REGION,), env=None) -> dict:
    """Credit cost of one odds request, before making it.

    The Odds API charges 1 credit per region per market for the odds endpoint.
    Requesting three markets in one region costs 3 credits per call -- so a
    job polling every 15 minutes costs 3 * 96 = 288 credits a day, which
    overruns a 500-credit monthly free tier in under two days.

    Knowing this before scheduling a snapshot job is the difference between a
    working pipeline and a dead one on the third of the month.
    """
    market_list = (configured_markets(env) if markets is None
                   else _validate_markets(markets))
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

# Verified against the-odds-api.com documentation and pricing pages.
# Historical endpoints cost 10x the live endpoints and require a paid plan.
HISTORICAL_CREDIT_MULTIPLIER = 10
HISTORICAL_COVERAGE_START = "2020-06-06"

# Monthly plans, USD -> credits included.
PRICING_TIERS = (
    ("free", 0, 500),
    ("20K", 30, 20_000),
    ("100K", 59, 100_000),
    ("5M", 119, 5_000_000),
    ("15M", 249, 15_000_000),
)

# An MLB regular season runs roughly this many days.
SEASON_DAYS = 186


def estimate_backfill_credits(seasons: int = 3, markets=("h2h",),
                              regions=("us",), snapshots_per_day: int = 10) -> dict:
    """Cost of backfilling historical closing odds.

    This is the Phase 3 decision gate priced out. Historical odds are the one
    input with no free substitute -- without them there is no backtest, because
    you would be betting into prices that no longer exist.

    `snapshots_per_day` defaults to 10 because MLB first pitches span roughly
    1pm to 10pm ET, and one snapshot per hour catches every game close to its
    own closing line. One snapshot call returns every game live at that
    timestamp, so the cost scales with snapshots, not with games.

    The headline: this is a ONE-TIME backfill, not a subscription. Pull the
    history, then cancel. Daily operation afterwards fits the free tier.
    """
    market_list = _validate_markets(markets)
    region_list = [r for r in regions if r]
    if not region_list:
        raise OddsProviderError("at least one region is required")
    if seasons < 1 or snapshots_per_day < 1:
        raise OddsProviderError("seasons and snapshots_per_day must be positive")

    per_call = (len(market_list) * len(region_list)
                * HISTORICAL_CREDIT_MULTIPLIER)
    calls = snapshots_per_day * SEASON_DAYS * seasons
    total = per_call * calls

    # Cheapest single month that covers the whole backfill.
    plan = next(((name, price) for name, price, credits in PRICING_TIERS
                 if credits >= total), None)

    return {
        "seasons": seasons,
        "markets": market_list,
        "regions": region_list,
        "snapshots_per_day": snapshots_per_day,
        "credits_per_call": per_call,
        "total_calls": calls,
        "total_credits": total,
        "cheapest_plan": plan[0] if plan else "exceeds listed tiers",
        "one_time_cost_usd": plan[1] if plan else None,
        "coverage_starts": HISTORICAL_COVERAGE_START,
        "note": "one-time backfill; cancel afterwards. Daily live use is separate.",
    }


def recommend_live_schedule(daily_snapshots: int = 4, markets=None,
                            env=None) -> dict:
    """Find a live snapshot cadence that fits inside the free tier.

    Line movement cannot be backfilled from free sources, so capture has to
    start early and run continuously. The constraint is that a naive
    15-minute poll burns the free tier in under two days.
    """
    market_list = (configured_markets(env) if markets is None
                   else _validate_markets(markets))
    per_call = len(market_list)
    monthly = per_call * daily_snapshots * 30
    free_credits = PRICING_TIERS[0][2]
    return {
        "daily_snapshots": daily_snapshots,
        "markets": market_list,
        "credits_per_call": per_call,
        "credits_per_month": monthly,
        "free_tier_monthly": free_credits,
        "fits_free_tier": monthly <= free_credits,
        "headroom": free_credits - monthly,
    }


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


def fetch_odds(markets=None, region=None, env=None,
               timeout: int = DEFAULT_TIMEOUT):
    """Fetch current odds. Raises NotConfigured when no key is present.

    `markets` defaults to whatever ODDS_API_MARKETS configures, so the credit cost
    of a call matches what `credits` reports.
    """
    source = os.environ if env is None else env
    key = api_key(source)
    if key is None:
        raise NotConfigured(SETUP_MESSAGE)
    resolved = configured_markets(source) if markets is None else _validate_markets(markets)
    params = {
        "apiKey": key,
        "regions": region or (source.get(ENV_REGION) or "").strip() or DEFAULT_REGION,
        "markets": ",".join(resolved),
        "oddsFormat": configured_odds_format(source),
    }
    return _get_json(f"sports/{SPORT}/odds", params, timeout=timeout)


def list_events(env=None, timeout: int = DEFAULT_TIMEOUT):
    """List upcoming events with their ids. Free -- the /events endpoint costs 0 credits.

    Needed because the per-event odds endpoint is addressed by event id, and ids are
    not derivable from team names. Being free, this can be called on every run without
    thinking about the budget, which is why event lookup is not cached.
    """
    source = os.environ if env is None else env
    key = api_key(source)
    if key is None:
        raise NotConfigured(SETUP_MESSAGE)
    return _get_json(f"sports/{SPORT}/events", {"apiKey": key}, timeout=timeout)


def fetch_event_odds(event_id, markets=None, region=None, env=None,
                     timeout: int = DEFAULT_TIMEOUT):
    """Fetch odds for ONE event, which is the only way to reach first-five markets.

    Billed markets x regions for this single event. Call it for games a scan has
    actually flagged; calling it across a whole slate is what exhausts a free month
    in a day and a half. See EVENT_MARKETS for the measured numbers.
    """
    source = os.environ if env is None else env
    key = api_key(source)
    if key is None:
        raise NotConfigured(SETUP_MESSAGE)
    if not event_id or not isinstance(event_id, str):
        raise OddsProviderError(f"event id must be a non-empty string, got {event_id!r}")
    resolved = (list(EVENT_MARKETS) if markets is None
                else _validate_markets(markets, allow_event_markets=True))
    params = {
        "apiKey": key,
        "regions": region or (source.get(ENV_REGION) or "").strip() or DEFAULT_REGION,
        "markets": ",".join(resolved),
        "oddsFormat": configured_odds_format(source),
    }
    return _get_json(f"sports/{SPORT}/events/{event_id}/odds", params, timeout=timeout)


def estimate_event_credits(events: int, markets=None, regions=(DEFAULT_REGION,)) -> dict:
    """What a per-event fetch costs, stated next to what the same markets would cost
    if they were available on the featured endpoint.

    The comparison is the point. The featured endpoint's cost is flat in the number
    of games; this one is linear. Reporting only the total invites the reader to
    reuse a featured-endpoint intuition that is wrong by a factor of the slate size.
    """
    market_list = (list(EVENT_MARKETS) if markets is None
                   else _validate_markets(markets, allow_event_markets=True))
    region_list = [r for r in regions if r]
    if not region_list:
        raise OddsProviderError("at least one region is required")
    if events < 0:
        raise OddsProviderError(f"events must not be negative, got {events}")
    per_event = len(market_list) * len(region_list)
    total = per_event * events
    return {
        "markets": market_list,
        "events": events,
        "credits_per_event": per_event,
        "credits_total": total,
        "if_it_were_a_featured_call": per_event,
        "free_tier_monthly": 500,
        "snapshots_per_free_month": (500 // total) if total else None,
    }


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

    # The superset, not just the featured three. A market no book offers is simply
    # absent, so scanning for first-five keys costs nothing on a featured response
    # and means an event response does not need a second, near-identical normalizer.
    for market_key in DEFAULT_MARKETS + EVENT_MARKETS:
        for book in ordered:
            market = _find_market(book, market_key)
            if market is None:
                continue
            outcomes = _parse_outcomes(market, _shape_of(market_key), record)
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


# First-five markets carry exactly the outcome shape of their full-game counterparts
# -- two named sides, or Over/Under with a point -- so they are parsed by the same
# code rather than by a copy of it that could drift.
_MARKET_SHAPES = {
    "h2h_1st_5_innings": "h2h",
    "spreads_1st_5_innings": "spreads",
    "totals_1st_5_innings": "totals",
}


def _shape_of(market_key):
    return _MARKET_SHAPES.get(market_key, market_key)


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


def fetch_normalized(markets=None, region=None, env=None,
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


def _validate_markets(markets, allow_event_markets=False):
    market_list = [m.strip() for m in markets if isinstance(m, str) and m.strip()]
    if not market_list:
        raise OddsProviderError("at least one market is required")
    unknown = [m for m in market_list if m not in SUPPORTED_MARKETS]
    if unknown:
        raise OddsProviderError(
            f"unsupported market(s) {', '.join(unknown)}; "
            f"expected any of {', '.join(SUPPORTED_MARKETS)}"
        )
    if allow_event_markets:
        return market_list

    # Mixing the two families in one call cannot work: they are served by different
    # endpoints with different billing. Caught here rather than as a 422 halfway
    # through a snapshot run, because the failure would otherwise land after the
    # credits for the featured markets had already been spent.
    event_only = [m for m in market_list if m in EVENT_MARKETS]
    if event_only:
        raise OddsProviderError(
            f"market(s) {', '.join(event_only)} are first-five markets and are not "
            "served by the featured odds endpoint; use fetch_event_odds, which "
            "bills per event rather than per slate"
        )
    return market_list
