"""Read-only view of why no system took a position on a game.

WHY THIS EXISTS
----------------
"Nothing clears the bar tonight" is the honest and most common answer this
product gives, and until now it was also an unexplained one. A reader looking
at a game with no pick could not tell whether the systems examined it and
declined, or never reached it at all. Those are completely different facts and
the page presented them identically.

`src.engine.slate.record_stand_downs` writes the raw rows; this module turns
them into a sentence. It never writes, never fetches, and treats a missing
ledger as "not recorded" rather than as "nothing stood down" -- an empty file
and an absent one mean different things, and conflating them would let a
broken writer read as a clean slate.

THE READINGS ARE DELIBERATELY NOT INTERCHANGEABLE
--------------------------------------------------
NO_LINEUP is a clock: the lineup had not posted when the system looked, and it
may well decide later tonight. NO_SIGNAL is a verdict: the system saw the
lineup and found nothing. Rendering both as "no play" would throw away the
distinction a reader most needs -- the first says come back, the second says
this game was examined and passed on.
"""

from __future__ import annotations

import collections
from typing import Optional

from src.ledger.chain import HashChainLedger

DEFAULT_STORE = "evidence/stand_downs_v1.jsonl"

# The reasons `src.evolab.decide` can return, in the order a reader should be
# told about them: the clock first (it may still change tonight), then the
# judgements, then the board.
REASON_ORDER = ("NO_LINEUP", "NO_SIGNAL", "BELOW_ENTRY", "TOO_FEW_BOOKS",
                "MARKET_UNAVAILABLE", "NOT_ELIGIBLE")

# One plain sentence per reason. No jargon: these render to a customer.
REASON_SENTENCE = {
    "NO_LINEUP": "the lineup had not posted when the systems looked",
    "NO_SIGNAL": "the systems read the matchup and found nothing they act on",
    "BELOW_ENTRY": "the case was there but under the entry bar",
    "TOO_FEW_BOOKS": "too few books were quoting to price it",
    "MARKET_UNAVAILABLE": "the market they work in was not on the board",
    "NOT_ELIGIBLE": "the game did not meet their eligibility rules",
}

# NO_LINEUP is the only reason that is purely a matter of timing, so it is the
# only one a reader should be told may change on its own.
TRANSIENT_REASONS = frozenset({"NO_LINEUP"})


def read(store: str = DEFAULT_STORE) -> list:
    """Every stand-down row, oldest first. A missing ledger reads empty."""
    try:
        return HashChainLedger(store).read()
    except Exception:  # noqa: BLE001 -- an unreadable ledger is a gap
        return []


def by_game(date: str, store: str = DEFAULT_STORE) -> dict:
    """`{game_key: {reason: [system_id, ...]}}` for one date."""
    out: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in read(store):
        if row.get("date") != date or not row.get("game_key"):
            continue
        reason = row.get("reason") or "UNKNOWN"
        out[row["game_key"]][reason].append(row.get("system_id"))
    return {game: dict(reasons) for game, reasons in out.items()}


def _ordered(reasons: dict) -> list:
    """Reasons in REASON_ORDER, unknown ones last but never dropped -- a
    reason this module has not been taught about is still a real answer and
    must not vanish because the vocabulary moved on."""
    known = [r for r in REASON_ORDER if r in reasons]
    unknown = sorted(r for r in reasons if r not in REASON_ORDER)
    return known + unknown


def summarize_game(date: str, game_key: str,
                   store: str = DEFAULT_STORE) -> Optional[dict]:
    """Why no system took a position on this game, or None if not recorded.

    None means the ledger holds nothing for this game -- the slate may not
    have reached it. That is deliberately distinct from a summary listing
    zero systems, which cannot occur: a row exists only because a system
    actually declined.
    """
    reasons = by_game(date, store).get(game_key)
    if not reasons:
        return None
    ordered = _ordered(reasons)
    counts = {r: len(reasons[r]) for r in ordered}
    total = sum(counts.values())
    # ONE lead reason, computed once and shared. An earlier version derived
    # `may_change_tonight` from REASON_ORDER position while the headline used
    # the dominant reason, so a game where 12 systems said NO_SIGNAL and one
    # said NO_LINEUP rendered "the systems found nothing" next to "this can
    # change once it posts". Two fields disagreeing about one game is worse
    # than either being wrong alone.
    lead = _lead_reason(counts, ordered)
    return {
        "game_key": game_key,
        "date": date,
        "n_systems": total,
        "reasons": [
            {
                "reason": r,
                "n_systems": counts[r],
                "sentence": REASON_SENTENCE.get(
                    r, "the systems declined for a reason this page has not "
                       "been taught to explain"),
                "transient": r in TRANSIENT_REASONS,
                "systems": sorted(s for s in reasons[r] if s),
            }
            for r in ordered
        ],
        "headline": headline(counts, ordered, total),
        "may_change_tonight": lead in TRANSIENT_REASONS,
    }


def _lead_reason(counts: dict, ordered: list) -> Optional[str]:
    """The reason covering the most systems -- the actual state of the game.

    A tie keeps REASON_ORDER, so the clock is named before a judgement rather
    than by dictionary order.
    """
    if not ordered:
        return None
    return max(ordered, key=lambda r: (counts[r], -ordered.index(r)))


def headline(counts: dict, ordered: list, total: int) -> str:
    """One sentence a reader can act on, about `_lead_reason`."""
    lead = _lead_reason(counts, ordered)
    if lead is None:
        return "No system recorded a reason for standing down on this game."
    n = counts[lead]
    sentence = REASON_SENTENCE.get(lead, "the systems declined")
    if lead in TRANSIENT_REASONS:
        return (f"No pick here yet: {sentence} "
                f"({n} of {total} systems). This can change once it posts.")
    return (f"No pick here: {sentence} "
            f"({n} of {total} systems).")
