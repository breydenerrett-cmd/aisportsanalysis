"""UFC_CARD_V1 -- the pre-registered UFC moneyline selector.

THE RULE, PRE-REGISTERED 2026-09-21 (before any UFC pick exists or is
graded; docs/PREREG_UFC_CARD_V1.md is the durable copy of what is below)
---------------------------------------------------------------------------
  1. MARKET: moneyline (h2h) only -- the only market The Odds API's
     mma_mixed_martial_arts key confirms today.
  2. A bout is judged only when at least MIN_BOOKS books quote it. Fewer
     than that and the bout is not evaluated at all -- not "found nothing",
     never looked at.
  3. CONSENSUS: for each side, the mean of that side's proportional de-vig
     probability across every book quoting the bout (NOT leave-one-book-out
     -- UFC boards are thin enough that removing one of only 3-4 books from
     its own consensus would swing the number on the bout that most needs a
     stable one). The average American price per side is the plain
     arithmetic mean of the American prices themselves, the number the card
     grades at lock (owner ruling: consensus price, not best-book price).
  4. CANDIDATE, one of two ways:
       a. the CONSENSUS FAVOURITE (the side with the higher consensus
          probability) -- only if its average price is BETTER than
          WORST_FAVOURITE_PRICE (-200 or worse is never published, the same
          owner rule NFL_CARD_V2 applies); or
       b. EITHER side priced from DOG_MIN_PRICE to DOG_MAX_PRICE
          (+100 to +150) whose consensus probability is at least
          DOG_MIN_PROB (0.45) -- a plus-money price the market itself still
          rates as more likely than not to lose, priced generously enough
          that even a modest edge over that consensus is worth publishing.
     A bout can produce at most one candidate (see `select`'s "favourite
     first, else the best-qualifying dog" tie-break).
  5. RANK by consensus probability (most confident first) -- the product
     picks the most CONFIDENT outcomes, not the best price (owner ruling).
  6. Publish at most MAX_PICKS.
  7. LOCK: each bout locks 90 minutes before ITS OWN commence_time
     (src/sports/mma.py's `lock_lead_hours=1.5`, applied by
     `src.appstate.card_ledger.publish` exactly as NFL/tennis lock per game
     -- this module does not lock anything itself, it only selects).
  8. FIGHTER CHANGE: if a bout's fighter pair changes after its pick has
     locked, the pick is VOID. Enforced at settlement, not here --
     see `src.report.ufc_card.settle_for_date`.

WHAT THIS DOES AND DOES NOT CLAIM
----------------------------------
Same as NFL_CARD_V2 (src/analysis/nfl_value.py): a pick here is a
statement that the market itself rates this fighter as the more likely
winner, not a claim of our own edge. No "proven edge" language anywhere on
this card, ever (owner ruling) -- UFC_CARD_V1 is a brand-new, ungraded test.

Pure functions: every input arrives as an argument.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional, Sequence

from src.core import odds as odds_math

RULE_ID = "UFC_CARD_V1"
MODEL_ID = "ufc_consensus_v1"

MIN_BOOKS = 3
# Owner ruling: never publish a moneyline at -200 or worse. "Better than
# -200" means less negative -- -110 passes, -199 passes, -200 does not.
WORST_FAVOURITE_PRICE = -200
DOG_MIN_PRICE = 100
DOG_MAX_PRICE = 150
DOG_MIN_PROB = 0.45
MAX_PICKS = 5
LOCK_LEAD_HOURS = 1.5

CARD_BASIS = (
    "Each bout is judged only when at least three sportsbooks quote it. The "
    "consensus chance for each fighter is the average, across those books, "
    "of the market's own price with the vig removed. A pick is either the "
    "consensus favourite at a price better than -200, or a fighter priced "
    "+100 to +150 whom the market itself still rates at 45% or better to "
    "win. Picks are ranked by how confident the market's own consensus is, "
    "not by price, and graded at the average price across books at lock, "
    "not the best single book."
)
CARD_DISCLAIMER = (
    "This is analysis, not advice, and not a guarantee. UFC_CARD_V1 is a "
    "brand-new test with no track record yet -- every pick is published "
    "before the bout and graded win, loss or void. Being tested, bet at "
    "your own risk."
)


def _parse_utc(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_price(american) -> str:
    if american is None:
        return "—"
    n = int(round(float(american)))
    return f"+{n}" if n > 0 else str(n)


def latest_quotes(rows: Iterable[Mapping]) -> dict:
    """{(event_id, book): newest h2h row} -- one quote per book per bout,
    the newest it posted."""
    latest: dict = {}
    for row in rows:
        if (row.get("market") or "h2h") != "h2h":
            continue
        key = (row.get("event_id"), row.get("book"))
        seen = latest.get(key)
        if seen is None or str(row.get("observed_utc") or "") >= str(seen.get("observed_utc") or ""):
            latest[key] = row
    return latest


def _upcoming_bouts(rows: Iterable[Mapping], *, now: datetime) -> dict:
    """{event_id: [each book's latest h2h row]} for bouts not yet started."""
    bouts: dict = defaultdict(list)
    for (event_id, _book), row in latest_quotes(rows).items():
        commence = _parse_utc(row.get("commence_time"))
        if commence is None or commence <= now:
            continue
        bouts[event_id].append(row)
    return bouts


def bout_consensus(rows_for_bout: Sequence[Mapping]) -> Optional[dict]:
    """Consensus no-vig probability and average American price per side for
    one bout, from every book's latest h2h quote -- or None if fewer than
    MIN_BOOKS books produce a priceable quote.

    `home`/`away` here are whichever two fighters the odds feed named --
    UFC has no home/away meaning, the labels are carried only because the
    multibook row shape uses them; `select` below reports each side as
    "team" (the fighter's own name).
    """
    home_probs, away_probs = [], []
    home_prices, away_prices = [], []
    home_team = away_team = None
    commence_time = None
    for row in rows_for_bout:
        home_price = _float(row.get("home_price"))
        away_price = _float(row.get("away_price"))
        if home_price is None or away_price is None:
            continue
        try:
            fair_home, fair_away = odds_math.devig_two_way(
                home_price, away_price, method="proportional")
        except (odds_math.OddsError, TypeError, ValueError):
            continue
        home_probs.append(fair_home)
        away_probs.append(fair_away)
        home_prices.append(home_price)
        away_prices.append(away_price)
        home_team = home_team or row.get("home_team")
        away_team = away_team or row.get("away_team")
        commence_time = commence_time or row.get("commence_time")

    if len(home_probs) < MIN_BOOKS:
        return None

    def _avg_american(prices):
        # Average in DECIMAL odds, then convert back (2026-09-21 review). A
        # plain mean of American prices breaks across even money: -105 and
        # +105 average to 0, which is not a price, and near-even fights are
        # exactly the ones this card picks.
        decimals = [odds_math.american_to_decimal(p) for p in prices]
        return odds_math.decimal_to_american(sum(decimals) / len(decimals))

    return {
        "n_books": len(home_probs),
        "home_team": home_team,
        "away_team": away_team,
        "commence_time": commence_time,
        "home_probability": sum(home_probs) / len(home_probs),
        "away_probability": sum(away_probs) / len(away_probs),
        "home_avg_price": _avg_american(home_prices),
        "away_avg_price": _avg_american(away_prices),
    }


def bout_candidate(consensus: Mapping) -> Optional[dict]:
    """The one candidate a bout's consensus produces, or None.

    Favourite first: if the consensus favourite's average price beats
    WORST_FAVOURITE_PRICE, that IS the bout's candidate -- a bout never
    produces both a favourite pick and a dog pick (one pick per bout, same
    as NFL_CARD_V2's one pick per game). Only when the favourite does not
    qualify does either side get a chance to qualify as a dog.
    """
    sides = [
        ("home", consensus["home_probability"], consensus["home_avg_price"],
         consensus["home_team"]),
        ("away", consensus["away_probability"], consensus["away_avg_price"],
         consensus["away_team"]),
    ]
    favourite = max(sides, key=lambda s: s[1])
    fav_side, fav_prob, fav_price, fav_team = favourite
    if fav_price > WORST_FAVOURITE_PRICE:
        return {"side": fav_side, "probability": fav_prob, "price": fav_price,
                "team": fav_team, "kind": "favourite"}

    for side, prob, price, team in sides:
        if DOG_MIN_PRICE <= price <= DOG_MAX_PRICE and prob >= DOG_MIN_PROB:
            return {"side": side, "probability": prob, "price": price,
                    "team": team, "kind": "dog"}
    return None


def _why(cand: Mapping, consensus: Mapping) -> list:
    pct = cand["probability"] * 100.0
    return [
        f"{consensus['n_books']} sportsbooks quote this bout; once the vig is "
        f"removed and averaged across them, the market rates {cand['team']} "
        f"at {pct:.1f}% to win.",
        (f"The average price across those books is {_fmt_price(cand['price'])} "
         + ("-- better than our -200 limit, so this consensus favourite is "
            "eligible." if cand["kind"] == "favourite" else
            "-- a plus-money price the market still rates at 45% or better, "
            "so this underdog is eligible.")),
    ]


def select(rows: Iterable[Mapping], *, now: datetime,
           game_ids: Optional[Mapping] = None,
           max_picks: int = MAX_PICKS) -> list:
    """The published UFC_CARD_V1 picks: at most one per bout, ranked by
    consensus probability, capped at `max_picks`.

    `game_ids` maps (home_team, away_team) full fighter-name pairs to the
    event_id settlement keys results on. Every bout here comes straight
    from the multibook store, so in practice `game_ids` is left None and
    each bout's own event_id is used directly -- the parameter exists only
    to match NFL_CARD_V2's `select` signature, which some callers may reuse
    generically.
    """
    candidates = []
    for event_id, bout_rows in _upcoming_bouts(rows, now=now).items():
        consensus = bout_consensus(bout_rows)
        if consensus is None:
            continue
        cand = bout_candidate(consensus)
        if cand is None:
            continue
        candidates.append((event_id, consensus, cand))

    ranked = sorted(candidates, key=lambda item: -item[2]["probability"])
    picks = []
    for event_id, consensus, cand in ranked:
        if len(picks) >= max_picks:
            break
        resolved_id = (game_ids or {}).get(
            (consensus["home_team"], consensus["away_team"]), event_id)
        if resolved_id is None:
            continue
        picks.append({
            "game_id": resolved_id,
            "rank": len(picks) + 1,
            "sport": "mma",
            "home_team": consensus["home_team"],
            "away_team": consensus["away_team"],
            "side": cand["side"],
            "team": cand["team"],
            "market": "moneyline",
            "line": None,
            "price": round(cand["price"], 2),
            "book": "consensus (average across books)",
            "market_probability": round(cand["probability"], 4),
            "model_probability": None,
            "n_books": consensus["n_books"],
            "label": "FAVOURITE" if cand["kind"] == "favourite" else "DOG",
            "bet": f"{cand['team']} to win at {_fmt_price(cand['price'])} (consensus)",
            "why": _why(cand, consensus),
            "kickoff_utc": consensus["commence_time"],
            "first_pitch_utc": consensus["commence_time"],
            "experimental": True,
        })
    return picks
