"""Price verdict: one word for one price, versus the de-vigged consensus.

WHAT THIS IS
------------
The Task-B1 surface: given a stated American price and the de-vigged
multi-book consensus for the same side at one capture instant, produce one
of eight fixed words (`WORDS`) plus the numbers and plain-English sentences
that justify it. This is Engine 1's price-improvement idea
(`src.analysis.prices`) reshaped into a single verdict a reader can act on
without doing the arithmetic themselves.

WHAT THIS IS NOT
----------------
Not a model. Not a prediction of who wins. `value_points` is the same
de-vigged-consensus-vs-stated-price comparison `prices.snapshot` already
makes, expressed in probability points instead of American-odds cents. No
independent model probability is read, computed, or implied anywhere in
this module -- every verdict this module builds carries the literal string
"NO INDEPENDENT MODEL YET" for exactly that reason (`build_price_verdict`'s
`independent_model` key). See docs/DEMO_SHIP_CHECKLIST.md, "The verdict
rule", for the full spec this module implements.

THE WORD
--------
`value_points(p_fair, p_price)` is `(p_fair - p_price) * 100`: positive
means the stated price implies LESS than the fair (de-vigged) probability,
i.e. a better-than-fair price. `verdict_word` maps that number onto one of
eight words by fixed threshold, then applies the LOW-evidence-tier cap
(`STRONG VALUE` -> `VALUE`, `FADE ALERT` -> `OVERPRICED`) -- a thin or stale
board is not allowed to produce the two most extreme words.

THE TIER
--------
`evidence_tier(books, age_seconds)` answers "how much should a reader trust
the word", never "what the probability is" -- it is a completely separate
axis from `value_points`, exactly as the evidence ladder is separate from
the relevance tier elsewhere in this codebase (`contracts.py`'s "FOUR
[now FIVE] SEPARATE VOCABULARIES" note).

stdlib only. No fastapi/pydantic import (tests/test_api_boundary.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.analysis import prices as prices_mod
from src.core import odds as odds_math

# The eight allowed words, exact spelling, in the order the verdict rule
# lists them (strongest good price down to strongest bad price, with
# INSUFFICIENT DATA last as the escape hatch rather than a ninth tier).
WORDS = (
    "STRONG VALUE",
    "VALUE",
    "LEAN",
    "FAIR PRICE",
    "PASS",
    "OVERPRICED",
    "FADE ALERT",
    "INSUFFICIENT DATA",
)

TIERS = ("HIGH", "MEDIUM", "LOW")

# Same floor as prices.snapshot -- a consensus over fewer books is a
# handful's opinion, not a market's. Reused rather than re-declared so the
# two numbers can never drift apart.
MIN_BOOKS = prices_mod.MIN_BOOKS

BASIS = (
    "Price verdict = your price versus the de-vigged multi-book consensus "
    "at one capture instant. Line-shopping value on the same bet, never "
    "expected value, never a prediction of who wins. No independent model "
    "probability exists yet."
)


# ---------------------------------------------------------------------------
# Pure building blocks
# ---------------------------------------------------------------------------

def value_points(p_fair, p_price):
    """(p_fair - p_price) * 100, rounded to 2 places, or None if either
    input is missing. Positive = the price implies LESS than the fair
    probability = a better-than-fair price."""
    if p_fair is None or p_price is None:
        return None
    return round((p_fair - p_price) * 100.0, 2)


def evidence_tier(books, age_seconds) -> "Optional[str]":
    """HIGH/MEDIUM/LOW from board depth and age alone. None below the
    book floor -- a thin board earns no tier at all, not a low one.

    HIGH requires BOTH >= 9 books and a board no older than 30 minutes;
    MEDIUM requires >= 6 books and no older than 2 hours; anything at or
    above the 6-book floor that misses both of those (including an unknown
    age) is LOW rather than untiered -- age unknown is treated as old, not
    as fresh.
    """
    if books is None or books < MIN_BOOKS:
        return None
    if books >= 9 and age_seconds is not None and age_seconds <= 1800:
        return "HIGH"
    if books >= MIN_BOOKS and age_seconds is not None and age_seconds <= 7200:
        return "MEDIUM"
    return "LOW"


_LOW_CAP = {"STRONG VALUE": "VALUE", "FADE ALERT": "OVERPRICED"}


def verdict_word(value_points_, tier) -> str:
    """The word for a value_points number, with the LOW-tier cap applied.

    `value_points_` of None means there is nothing to grade --
    INSUFFICIENT DATA. Otherwise fixed thresholds per the verdict rule,
    then: on a LOW-evidence board, the two most extreme words are capped
    one notch inward (a thin or stale board cannot produce the strongest
    claim in either direction).
    """
    if value_points_ is None:
        return "INSUFFICIENT DATA"
    vp = value_points_
    if vp >= 3.0:
        word = "STRONG VALUE"
    elif vp >= 1.5:
        word = "VALUE"
    elif vp >= 0.5:
        word = "LEAN"
    elif vp >= -1.0:
        word = "FAIR PRICE"
    elif vp >= -2.5:
        word = "PASS"
    elif vp >= -4.5:
        word = "OVERPRICED"
    else:
        word = "FADE ALERT"
    if tier == "LOW":
        word = _LOW_CAP.get(word, word)
    return word


def _fmt_price(price) -> str:
    return f"+{price}" if isinstance(price, (int, float)) and price > 0 else str(price)


def _age_seconds(observed_utc, now=None):
    """Seconds between `observed_utc` and `now` (UTC-aware), or None if
    `observed_utc` is missing or unparseable. `now` may be a `datetime`
    (naive treated as UTC) or omitted for the real current instant --
    never a string, so a caller cannot smuggle an unparseable "now" past
    the same guard `observed_utc` gets."""
    if not observed_utc:
        return None
    try:
        obs = datetime.fromisoformat(str(observed_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if obs.tzinfo is None:
        obs = obs.replace(tzinfo=timezone.utc)
    if now is None:
        now_dt = datetime.now(timezone.utc)
    elif isinstance(now, datetime):
        now_dt = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    else:
        return None
    # Whole seconds: sub-second jitter between two calls made moments apart
    # (build_contract's determinism test builds the same contract five
    # times in a tight loop with no injected `now`) must not turn into a
    # different age_seconds and so a different serialised contract.
    return round((now_dt - obs).total_seconds())


def _implied_probability(american_price):
    if american_price is None:
        return None
    try:
        return round(odds_math.american_to_probability(american_price), 4)
    except odds_math.OddsError:
        return None


def _fair_price(consensus_probability):
    if consensus_probability is None:
        return None
    try:
        return round(odds_math.probability_to_american(consensus_probability))
    except odds_math.OddsError:
        return None


# ---------------------------------------------------------------------------
# build_price_verdict -- the whole thing, assembled
# ---------------------------------------------------------------------------

def build_price_verdict(*, american_price, consensus_probability, books,
                        observed_utc, now=None, best_price=None,
                        best_book=None, reasons=(), risks=()) -> dict:
    """One price verdict object. Every key is present on every call --
    an unavailable input produces None fields and an INSUFFICIENT DATA
    word, never an absent key or a guessed number.

    `reasons`/`risks` are caller-supplied sentences (e.g. thesis-support or
    counterargument claim statements, verbatim) folded in ahead of the
    ones this function generates from the price/board numbers themselves.
    """
    reasons = list(reasons)
    risks = list(risks)

    age_seconds = _age_seconds(observed_utc, now)
    p_price = _implied_probability(american_price)
    have_consensus = consensus_probability is not None and books is not None \
        and books >= MIN_BOOKS

    if not have_consensus or p_price is None:
        word = "INSUFFICIENT DATA"
        vp = None
        tier = None
        fair = None
        if consensus_probability is None:
            risks.append(
                "INSUFFICIENT DATA: no de-vigged consensus available for "
                "this side")
        elif books is not None and books < MIN_BOOKS:
            risks.append(
                f"INSUFFICIENT DATA: fewer than {MIN_BOOKS} books quoted "
                "this side")
        if american_price is None:
            risks.append("INSUFFICIENT DATA: no price was stated")
        elif p_price is None:
            risks.append(
                "INSUFFICIENT DATA: the stated price could not be read as "
                "a valid American price")
    else:
        vp = value_points(consensus_probability, p_price)
        tier = evidence_tier(books, age_seconds)
        word = verdict_word(vp, tier)
        fair = _fair_price(consensus_probability)

        reasons.append(
            f"Your price {_fmt_price(american_price)} implies "
            f"{p_price * 100:.1f}%; de-vigged consensus "
            f"{consensus_probability * 100:.1f}% across {books} books "
            f"({vp:+.1f} pts)")
        if best_price is not None and best_book and american_price is not None:
            try:
                beats = (odds_math.american_to_decimal(best_price)
                        > odds_math.american_to_decimal(american_price))
            except odds_math.OddsError:
                beats = False
            if beats:
                reasons.append(
                    f"Best on the board: {_fmt_price(best_price)} at "
                    f"{best_book}")
        if age_seconds is not None:
            minutes = age_seconds / 60.0
            if minutes < 60:
                reasons.append(f"Board captured {minutes:.0f} min ago")
            else:
                reasons.append(f"Board captured {minutes / 60.0:.1f} hr ago")

        if tier == "LOW":
            if age_seconds is not None and age_seconds > 7200:
                risks.append(
                    f"Board is {age_seconds / 3600.0:.0f} hr old — prices "
                    "may have moved")
            else:
                risks.append(
                    "Board age is unknown — prices may have moved")
        if books < 8:
            risks.append(f"Only {books} books quoted")

    return {
        "word": word,
        "value_points": vp,
        "fair_price": fair,
        "stated_implied_probability": p_price,
        "market_implied_probability": consensus_probability,
        "evidence_tier": tier,
        "books": books,
        "observed_utc": observed_utc,
        "age_seconds": age_seconds,
        "independent_model": "NO INDEPENDENT MODEL YET",
        "market_reference_provenance": "market_derived",
        "reasons": tuple(reasons),
        "risks": tuple(risks),
        "basis": BASIS,
    }
