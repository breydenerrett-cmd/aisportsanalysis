"""The daily digest: per-user, personal, and built the same way every other
JSON payload in this package is -- pure functions over already-built slate
entries and already-fetched user state, nothing fetched or guessed here.

WHY THIS DOES NOT IMPORT src.appstate
---------------------------------------
Every other src/analysis module (gamepayload.py in particular) stays pure:
it takes entries `src.pipeline.briefing.build_slate` already produced and a
user's own state passed in by the caller, and only selects, labels and
reshapes -- src.analysis.gamepayload's own module docstring states this
rule and this module follows it for the same reason. src.appstate owns the
product database (saved bets, analytics events); reaching into it from here
would blur the line api/digest.py exists to keep thin: the API layer
fetches (mlb.fetch_games, history.read_results, savedbets.list_bets,
events.latest_event) and this module only assembles what it is handed.
That also keeps build_user_digest testable offline with hand-built
SavedBet-shaped objects and no sqlite file anywhere, the same offline
guarantee tests/test_gamepayload.py relies on for the rest of this package.

WHAT "SINCE LAST DIGEST" MEANS
---------------------------------
`since_last_digest` is the ISO timestamp of the user's previous digest
(their previous `GET /digest` call's `generated_at`), or None on their
first digest ever. A settled bet only appears in `settled_bets` once: a bet
settled before that timestamp was already reported in an earlier digest,
and reporting it again would make every digest after the first a growing
re-run of the same news. On a user's first digest (`since_last_digest` is
None) every bet already settled is new to them, because there is no earlier
digest that could have told them -- this module does not paper over that
distinction with a fabricated window.

VOCABULARY RULES, RESTATED
-----------------------------
This module inherits every rule src/analysis/gamepayload.py's docstring
states: market-implied consensus, never "true"; price improvement is
line-shopping value, never EV or edge; no win-probability field; every
quantitative claim keeps the sample or evidence it rests on beside it. A
quiet slate or quiet history reports what was checked, never an empty
section with no context. tests/test_customer_language.py enforces this
file the same way it already enforces the rest of src/analysis.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from src.analysis import gamepayload

# A digest is read in ten seconds, not browsed like the full /changed/{date}
# band -- so only the tiers worth a reader's attention ride in the digest's
# own highlights list. LOW and UNKNOWN stay reachable from the full band,
# never dropped from the record, just not repeated here.
_HIGHLIGHT_TIERS = ("HIGH", "MEDIUM")
# Cap on how many changed-items the digest surfaces even when several
# qualify -- generous over a normal night's roster churn (rosterwatch fires
# on individual scratches/lineups/transactions, not dozens at once) while
# keeping the digest itself short.
MAX_CHANGED_HIGHLIGHTS = 5


def _settlement_highlights(saved_bets: list, since_last_digest: Optional[str]) -> list:
    """Every settled bet this user has not already been told about.

    Ordered oldest-settled-first, like a timeline read top to bottom, not a
    most-recent-first feed. A bet that is not yet settled (still pending, or
    permanently unsettled per src.appstate.settlement's own rules) never
    appears here -- absence, not a fabricated "pending" line, since this
    digest reports outcomes, not status.
    """
    out = []
    for bet in saved_bets:
        if not bet.is_settled:
            continue
        settled_at = bet.settled_at or ""
        if since_last_digest and settled_at <= since_last_digest:
            continue
        out.append({
            "id": bet.id,
            "game": bet.game,
            "side": bet.side,
            "settlement_status": bet.settlement_status,
            "settlement_reason": bet.settlement_reason,
            "settled_at": bet.settled_at,
        })
    out.sort(key=lambda item: item["settled_at"] or "")
    return out


def _slate_summary(entries: list, notes: Optional[list], *, date: Optional[str],
                   now: datetime) -> dict:
    """Tonight's slate, reduced to a game count and one honest sentence.

    Reuses gamepayload.build_slate_list rather than recomputing
    `checked_games` -- this digest can never disagree with what GET
    /games/{date} would say about the same date.
    """
    payload = gamepayload.build_slate_list(entries, date=date, now=now,
                                           notes=notes)
    checked = payload["checked_games"]
    if checked == 0:
        headline = f"No MLB games scheduled for {date}." if date else \
            "No MLB games scheduled."
    elif checked == 1:
        headline = "1 game on tonight's slate."
    else:
        headline = f"{checked} games on tonight's slate."
    return {"date": date, "checked_games": checked, "headline": headline,
            "notes": list(payload.get("notes") or [])}


def _changed_highlights(entries: list, *, date: Optional[str], now: datetime) -> dict:
    """The HIGH/MEDIUM-tier subset of tonight's What Changed band.

    Reuses gamepayload.build_changed_items for the same reason
    _slate_summary reuses build_slate_list: this digest reports a subset of
    what GET /changed/{date} already computed, never a second opinion on it.
    `inadmissible` items (below the quality floor for V3, per
    src/analysis/relevance.py's module docstring) are excluded from a
    customer-facing highlight the same way they are excluded from any
    finding -- inadmissible is not "less interesting", it is "not
    reportable" for a different reason than a LOW tier is.
    """
    payload = gamepayload.build_changed_items(entries, date=date, now=now)
    items = payload["items"]
    notable = [item for item in items
              if item.get("tier") in _HIGHLIGHT_TIERS
              and not item.get("inadmissible")]
    if not notable:
        headline = (f"Checked {payload['checked_games']} game(s); nothing "
                    "notable changed since our last look.") if entries else \
            "No games checked -- nothing to report."
    else:
        n = len(notable)
        headline = (f"{n} notable change{'s' if n != 1 else ''} since our "
                    "last look.")
    return {
        "checked_games": payload["checked_games"],
        "headline": headline,
        "quiet": not notable,
        "highlights": notable[:MAX_CHANGED_HIGHLIGHTS],
    }


def _price_improvement_observation(entries: list) -> Optional[dict]:
    """The single largest price-improvement observation on tonight's board,
    or None when nothing on the board beat consensus.

    "Largest" is a plain top-1 by `improvement_return_pct` across every
    priced side of every game on the slate -- one honest observation, not a
    claim that it is the only one or the best one will still be there by
    the time a reader looks. Never EV, never edge: the fields and the
    `note` text are read back from src.analysis.prices unchanged, the same
    contract src.analysis.gamepayload._price_section keeps for the
    single-game quick view.
    """
    best = None
    for entry in entries:
        dossier = entry.get("dossier")
        if dossier is None:
            continue
        section = dossier.get("price_improvement")
        if not section or section.get("skipped"):
            continue
        game = dossier.game
        for side_name, detail in (section.get("sides") or {}).items():
            if not detail or detail.get("skipped"):
                continue
            pct = detail.get("improvement_return_pct")
            if pct is None or pct <= 0:
                continue
            if best is None or pct > best["improvement_return_pct"]:
                best = {
                    "game_id": gamepayload.game_id(game),
                    "away_team": game.get("away_team"),
                    "home_team": game.get("home_team"),
                    "side": side_name,
                    "best_price": detail.get("best_price"),
                    "best_book": detail.get("best_book"),
                    "consensus_probability": detail.get("consensus_probability"),
                    "improvement_points": detail.get("improvement_points"),
                    "improvement_return_pct": pct,
                    "note": section.get("note"),
                }
    return best


def build_user_digest(user_id, date: Optional[str], *, entries: list,
                      saved_bets: list, notes: Optional[list] = None,
                      since_last_digest: Optional[str] = None,
                      now: Optional[datetime] = None) -> dict:
    """The full daily digest for one user.

    `entries`/`notes` are tonight's already-built slate
    (src.pipeline.briefing.build_slate's `games`/`notes`, for `date`);
    `saved_bets` is that user's own rows
    (src.appstate.savedbets.list_bets(user_id), any settlement state
    already resolved by the daily sweep); `since_last_digest` is the
    `generated_at` of their previous digest, or None on their first one.
    Every one of those is fetched by the caller (api/digest.py) -- see the
    module docstring for why this function does not fetch any of it itself.

    Returns one JSON-safe dict: `settled_bets` (this user's outcomes since
    last time), `slate` (tonight's game count and a one-line summary),
    `what_changed` (the notable subset of tonight's What Changed band), and
    `price_improvement` (one observation, or None). Nothing here is a
    recommendation or a prediction -- see the module docstring's vocabulary
    rules.
    """
    now = now or datetime.now(timezone.utc)
    return {
        "user_id": user_id,
        "date": date,
        "generated_at": now.isoformat(),
        "since_last_digest": since_last_digest,
        "settled_bets": _settlement_highlights(saved_bets, since_last_digest),
        "slate": _slate_summary(entries, notes, date=date, now=now),
        "what_changed": _changed_highlights(entries, date=date, now=now),
        "price_improvement": _price_improvement_observation(entries),
    }
