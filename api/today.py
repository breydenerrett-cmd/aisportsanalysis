"""JSON serving of today's slate — the first api/ endpoint.

Read-only. Builds on the REAL domain path (src.pipeline.briefing.build_slate
-> the entries src.pipeline.briefing.make_entry produces) and never
re-derives anything the domain layer already computed. src/ imports nothing
from here (tests/test_api_boundary.py enforces that); this module imports
FROM src, never the reverse.

ODDS-AGE METADATA: every entry that carries a market section reports how
old that quote is as of the moment this payload was built, computed from
the same `observed_utc` the price boards already carry (src/analysis/prices.py).
Staleness has to be visible starting at the first endpoint, not bolted on
later, or "the odds are old" becomes a fact only the dashboard knows.

SERIALISATION NOTE (TODO): src/analysis/contracts.py now exists and defines
the customer-facing Claim/QuotedPrice/CustomerEvidence shapes, but those
shapes cover individual claims, not a whole briefing entry. Until a
contracts-level "entry -> customer payload" translator exists, this module
serialises the entry dict directly (Dossier.to_dict() plus the plain verdict
fields already on the entry). When that translator lands, swap the body of
`serialize_entry` to route every claim through it instead of passing the
dossier/findings through untranslated -- this is the one place that needs
to change.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.detect import dossier as dossier_mod
from src.pipeline import briefing


def _odds_age_seconds(observed_utc: Optional[str], *, now: datetime) -> Optional[float]:
    """Seconds between an observed quote and `now`. None if there is no quote
    to age -- absence over a fabricated age of zero."""
    if not observed_utc:
        return None
    try:
        observed = datetime.fromisoformat(str(observed_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max((now.astimezone(timezone.utc) - observed).total_seconds(), 0.0)


def _odds_meta(entry: dict, *, now: datetime) -> dict:
    """Odds-age metadata for one entry, honest about the case where there is
    no market section at all rather than inventing a zero-age quote.

    `observed_utc` is a property of a captured BOARD (the multibook capture,
    or the price-improvement summary built from it) -- src/analysis/prices.py
    -- not of the plain fair-price `market` section, which carries no
    capture timestamp at all. `has_market` still asks the `market` section,
    since that is what the briefing itself uses to decide whether a price
    exists for this game.
    """
    dossier = entry.get("dossier")
    if not isinstance(dossier, dossier_mod.Dossier):
        return {"observed_utc": None, "age_seconds": None, "has_market": False}
    market = dossier.get("market")
    board_section = dossier.get("price_improvement") or dossier.get("multibook_board")
    observed_utc = (board_section or {}).get("observed_utc")
    return {
        "observed_utc": observed_utc,
        "age_seconds": _odds_age_seconds(observed_utc, now=now),
        "has_market": market is not None,
    }


def serialize_entry(entry: dict, *, now: datetime) -> dict:
    """One slate entry, JSON-safe.

    No win probability field is emitted anywhere here (the model is
    UNCALIBRATED). Any de-vigged number that passes through from the market
    section keeps its existing name (`away_fair` / `home_fair` /
    "market-implied consensus" language) -- this function relabels nothing.
    """
    dossier = entry.get("dossier")
    dossier_payload = (dossier.to_dict()
                       if isinstance(dossier, dossier_mod.Dossier) else dossier)
    findings = [f.to_dict() if hasattr(f, "to_dict") else f
               for f in entry.get("findings", [])]
    return {
        "dossier": dossier_payload,
        "findings": findings,
        "verdict": entry.get("verdict"),
        "side": entry.get("side"),
        "market": entry.get("market"),
        "summary": entry.get("summary"),
        "odds_meta": _odds_meta(entry, now=now),
    }


def build_today_payload(games: list, store: dict, *, date: Optional[str] = None,
                        now: Optional[datetime] = None, **build_slate_kwargs) -> dict:
    """The JSON payload for one day's slate, built from the real domain path.

    `games` and `store` are dependency-injected rather than fetched here, so
    this function is callable offline in a test with a real (possibly empty)
    historical store and a hand-built or already-fetched game list -- the
    live HTTP path (once wired) is the only caller that reaches out to the
    network to produce them.
    """
    now = now or datetime.now(timezone.utc)
    slate = briefing.build_slate(games, store, **build_slate_kwargs)
    return {
        "date": date or slate.get("date"),
        "generated_at": now.isoformat(),
        "games": [serialize_entry(e, now=now) for e in slate["games"]],
        "notes": slate.get("notes", []),
    }
