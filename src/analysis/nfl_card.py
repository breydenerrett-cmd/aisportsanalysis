"""NFL_CARD_V1 — picks on market side, model agreement required, moneyline only.

THE RULE, PRE-REGISTERED
------------------------
Before any slate is read, fixed in code so it cannot be chosen in view of the
candidates:

  1. Every game that has not started and carries a moneyline on at least
     `prices.MIN_BOOKS` books is a candidate.
  2. The SIDE is whichever the de-vigged market consensus makes more likely.
     That is the market's opinion, not ours.
  3. Our own run model must AGREE that side is more likely. Where it disagrees,
     the pick is labelled SPLIT.
  4. The MARKET is always the moneyline.
  5. Rank by consensus confidence. Publish at most `MAX_PICKS`.
  6. SPLIT candidates rank after all non-split ones.

Pure functions: every input arrives as an argument, every output is built from
those arguments alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence, Mapping

from src.analysis import daily_card
from src.analysis.prices import MIN_BOOKS

# Reuse the confidence bands from the MLB card.
BAND_STRONG = daily_card.BAND_STRONG
BAND_LEAN = daily_card.BAND_LEAN

LABEL_STRONG = "STRONG"
LABEL_LEAN = "LEAN"
LABEL_SLIGHT = "SLIGHT"
LABEL_SPLIT = "SPLIT"

MAX_PICKS = 5

NFL_CARD_RULE = "NFL_CARD_V1"

# PROVENANCE, published on every card row so a reader can check what made
# the pick the same way an MLB row lets them (src/appstate/card_ledger.py's
# FROZEN_FIELDS/publish() read `basis`/`disclaimer`/`model_id`/`calibrated`
# straight off whatever card dict is handed to `publish()`). Distinct from
# MLB's own strings (src.analysis.strength.MODEL_ID, daily_card.CARD_BASIS/
# CARD_DISCLAIMER) because the rule itself is different: no fitted
# probability model, no calibration curve -- a market-consensus read that a
# separate team-strength model either agrees or splits with. Until
# 2026-09-19 `src/report/nfl_card.py`'s live card payload never set any of
# these four fields at all, so every published NFL row on the record had a
# null `basis`, `disclaimer`, `model_id` and `calibrated` where an MLB row
# has real values -- a slip on the public record nobody could check.
MODEL_ID = "nfl_market_consensus_v1"
CARD_BASIS = (
    "The side is whichever the de-vigged multi-book market consensus makes "
    "more likely. Our own team-strength model has to agree that side is "
    "more likely, or the pick is labelled SPLIT. The bet is always the "
    "moneyline. Ranked by market confidence."
)
CARD_DISCLAIMER = (
    "These are reads, not guarantees, and they are not claims of positive "
    "expected value. Backing the more likely side wins most individual bets "
    "and shows no positive estimated return under the market benchmark. "
    "Every pick here is published before kickoff and graded win or lose. "
    "NFL_CARD_V1 is experimental -- performance is still being evaluated."
)


def _fmt_price(american) -> str:
    """Format American odds. "-205" or "+118"."""
    if american is None:
        return "—"
    n = int(round(float(american)))
    return f"+{n}" if n > 0 else str(n)


def _has_started(kickoff_utc, now: datetime) -> bool:
    """True if the game has already started or time is uncertain."""
    if not kickoff_utc:
        return True
    try:
        when = datetime.fromisoformat(str(kickoff_utc).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= now.astimezone(timezone.utc)


def _consensus_side(h2h_quotes: Sequence[dict]) -> Optional[tuple[str, float]]:
    """Which side the de-vigged consensus favors, or None.

    h2h_quotes: [{book, home_price, away_price, observed_utc}, ...]
                from prices.snapshot() after filtering to a single instant.

    Returns (side, probability) where side is "home" or "away", or None if:
    - Fewer than MIN_BOOKS quotes
    - Consensus is exactly 0.5 (neither side favoured)
    - De-viggging fails on any quote
    """
    from src.core import odds as odds_math

    if not h2h_quotes or len(h2h_quotes) < MIN_BOOKS:
        return None

    fairs = []
    for quote in h2h_quotes:
        try:
            fair_away, fair_home = odds_math.devig_two_way(
                quote.get("away_price"), quote.get("home_price")
            )
            fairs.append((fair_away, fair_home))
        except odds_math.OddsError:
            continue

    if len(fairs) < MIN_BOOKS:
        return None

    n = len(fairs)
    consensus_away = sum(f[0] for f in fairs) / n
    consensus_home = sum(f[1] for f in fairs) / n

    if abs(consensus_away - consensus_home) < 1e-9:
        # Exactly 0.5 -- neither side favoured
        return None

    if consensus_home > consensus_away:
        return ("home", consensus_home)
    else:
        return ("away", consensus_away)


def _best_price_for_side(h2h_quotes: Sequence[dict], side: str) -> tuple[Optional[float], Optional[str]]:
    """Best (highest) decimal odds for a side, and which book quotes it.

    side: "home" or "away"
    Returns (american_price, book) or (None, None) if no valid quotes.
    """
    from src.core import odds as odds_math

    best_decimal = None
    best_price = None
    best_book = None

    for quote in h2h_quotes:
        if side == "home":
            price = quote.get("home_price")
        else:
            price = quote.get("away_price")

        if price is None:
            continue

        try:
            decimal = odds_math.american_to_decimal(price)
        except odds_math.OddsError:
            continue

        if best_decimal is None or decimal > best_decimal:
            best_decimal = decimal
            best_price = price
            best_book = quote.get("book")

    return (best_price, best_book)


def candidate(entry: dict, *, now: datetime) -> Optional[dict]:
    """One candidate pick, or None when the game cannot be picked.

    entry: {"game_id", "week", "home_team", "away_team" (full names),
            "home_code", "away_code", "kickoff_utc", "neutral_site",
            "h2h_quotes": [{book, home_price, away_price, observed_utc}],
            "spread_quotes": [...], "model": game_probability dict or None,
            "grade": nfl_grade.grade dict or None}

    Returns None when:
    - Kickoff has passed
    - h2h board has fewer than MIN_BOOKS books
    - Consensus is exactly 0.5 (neither side favoured)

    Otherwise returns dict with:
    {"game_id", "home_team", "away_team" (full names), "home_code", "away_code",
     "side" ("home"/"away"), "team" (full name), "kickoff_utc", "first_pitch_utc",
     "market_probability" (de-vigged consensus), "model_probability" (or None),
     "model_agrees" (bool or None), "label" (STRONG/LEAN/SLIGHT/SPLIT),
     "price" (American), "book", "why": [sentences],
     "alternative": {market, line, price, book, text} or None,
     "experimental": True}
    """
    if _has_started(entry.get("kickoff_utc"), now):
        return None

    h2h_quotes = entry.get("h2h_quotes") or []
    side_prob = _consensus_side(h2h_quotes)
    if side_prob is None:
        return None

    side, market_prob = side_prob

    # Get model's opinion
    model_data = entry.get("model")
    model_agrees = None
    model_prob = None

    if model_data:
        if model_data.get("thin"):
            # Model is thin -- no agreement statement
            model_agrees = None
            model_prob = None
        else:
            if side == "home":
                model_prob = model_data.get("p_home")
            else:
                model_prob = model_data.get("p_away")

            if model_prob is not None:
                model_agrees = model_prob > 0.5

    # Get best price for the side
    price, book = _best_price_for_side(h2h_quotes, side)

    # Determine label
    if not model_agrees and model_agrees is not None:
        label = LABEL_SPLIT
    elif market_prob >= BAND_STRONG:
        label = LABEL_STRONG
    elif market_prob >= BAND_LEAN:
        label = LABEL_LEAN
    else:
        label = LABEL_SLIGHT

    # Build why sentences
    team_name = entry.get(f"{side}_team")
    why_sentences = []

    # Market sentence
    market_pct = f"{round(market_prob * 100)}%"
    why_sentences.append(
        f"The market makes {team_name} the favourite at kickoff."
    )

    # Model agreement sentence
    if model_agrees is None:
        why_sentences.append(
            "Our own numbers do not have enough games yet to weigh in."
        )
    elif model_agrees:
        why_sentences.append("Our own numbers agree.")
    else:
        why_sentences.append(
            "Our own numbers lean the other way, so this one is a split."
        )

    # Add grade reasons if game is not ready
    grade = entry.get("grade")
    if grade and not grade.get("ready"):
        for reason in grade.get("reasons") or []:
            why_sentences.append(reason)

    # Alternative (spread quote if available)
    alternative = None
    spread_quotes = entry.get("spread_quotes") or []
    if spread_quotes:
        # Find the spread for this side
        for sq in spread_quotes:
            sq_side_data = sq.get(side)
            if sq_side_data:
                line = sq_side_data.get("line")
                spread_price = sq_side_data.get("price")
                spread_book = sq_side_data.get("book")
                if line is not None and spread_price is not None:
                    # Format the line for display
                    line_str = f"{float(line):+g}"
                    # Build the trade text
                    bet_text = f"Or take {team_name} {line_str} at {_fmt_price(spread_price)}"
                    alternative = {
                        "market": "spread",
                        "line": line,
                        "price": spread_price,
                        "book": spread_book,
                        "text": bet_text,
                    }
                    break

    return {
        "game_id": entry.get("game_id"),
        "rank": None,  # Set by select()
        "sport": "nfl",
        "home_team": entry.get("home_team"),
        "away_team": entry.get("away_team"),
        "home_code": entry.get("home_code"),
        "away_code": entry.get("away_code"),
        "side": side,
        "team": team_name,
        "market": "moneyline",
        "price": price,
        "book": book,
        "market_probability": market_prob,
        "model_probability": model_prob,
        "model_agrees": model_agrees,
        "label": label,
        "bet": f"Take {team_name} to win at {_fmt_price(price)}",
        "why": why_sentences,
        "alternative": alternative,
        "kickoff_utc": entry.get("kickoff_utc"),
        "first_pitch_utc": entry.get("kickoff_utc"),  # Same value
        "experimental": True,
    }


def select(entries: Sequence[dict], *, now: datetime,
           max_picks: int = MAX_PICKS) -> list[dict]:
    """The published picks, ranked by confidence, capped at max_picks.

    entries: List of entry dicts (from nfl_slate.py).
    now: Current datetime (timezone-aware UTC).
    max_picks: Maximum number of picks to return (default MAX_PICKS).

    Returns list of pick dicts, ranked 1..n, at most max_picks.
    No minimum: empty entries produces empty result.
    """
    candidates = []
    for entry in (entries or []):
        cand = candidate(entry, now=now)
        if cand:
            candidates.append(cand)

    # Split into agreed and split
    agreed = [c for c in candidates if c.get("model_agrees") is not False]
    split = [c for c in candidates if c.get("model_agrees") is False]

    # Sort by market probability descending
    agreed.sort(key=lambda c: -(c.get("market_probability") or 0.0))
    split.sort(key=lambda c: -(c.get("market_probability") or 0.0))

    # Select: non-split first, then split, up to max_picks
    picks = []
    seen_games = set()

    for cand in agreed:
        if len(picks) >= max_picks:
            break
        game_id = cand.get("game_id")
        if game_id not in seen_games:
            seen_games.add(game_id)
            picks.append(cand)

    for cand in split:
        if len(picks) >= max_picks:
            break
        game_id = cand.get("game_id")
        if game_id not in seen_games:
            seen_games.add(game_id)
            picks.append(cand)

    # Set ranks
    for i, pick in enumerate(picks, start=1):
        pick["rank"] = i

    return picks
