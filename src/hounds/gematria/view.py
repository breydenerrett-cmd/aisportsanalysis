"""Read side of the Gematria Hound: the evidence behind each of its picks, for the "Evidence" section of the hound page.

Read from the AI bets ledger (the same hash-chained file the other ledger-fed hounds' bets are in), never from the stats
book, so it answers at once and before the first pick. A pick's row carries the whole evidence block the hound wrote at the lock
(``runtime.GematriaRuntime.weigh``): both sides' scores, the margin, the price, the search size and the top matches for each
side. This module only reshapes it and adds the grade when the settler has written one. It writes nothing and calls nothing.

THE HOUND ID COMES FROM THE CONFIG, NEVER FROM THE REQUEST'S PATH. Only an id whose ``config/ai_hounds.json`` entry has family
``gematria`` is served; anything else is a 404 at the route.

Paper only. Nothing here is advice and nothing here claims numerology predicts games.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.hounds import NOT_ADVICE, PAPER_ONLY, ai_defs
from src.hounds.gematria import EXPERIMENTAL_LINE
from src.hounds.ledgers import jsonl_rows

MAX_PICKS = 40
KIND_BET = "hound_bet"
KIND_GRADED = "hound_graded"


def is_gematria_hound(hound_id: str) -> bool:
    entry = ai_defs.entry_for(hound_id) if isinstance(hound_id, str) else None
    return bool(entry) and entry.get("family") == "gematria"


def picks_for(hound_id: str, *, ledger: Optional[str] = None, limit: int = MAX_PICKS) -> dict:
    """``{hound_id, started, picks: [...]}``: this hound's bets that carry an evidence block, newest first, each with its grade."""
    path = Path(ai_defs.ledger_path(ledger))
    bets, grades = [], {}
    for r in jsonl_rows(path):
        if r.get("hound_id") != hound_id:
            continue
        if r.get("kind") == KIND_BET and isinstance(r.get("gematria"), dict):
            bets.append(r)
        elif r.get("kind") == KIND_GRADED:
            grades[(r.get("event_id"), r.get("market"), r.get("selection"))] = r
    bets.sort(key=lambda r: (str(r.get("start_utc") or ""), str(r.get("event_id") or "")), reverse=True)
    picks = []
    for r in bets[:limit]:
        g = r["gematria"]
        graded = grades.get((r.get("event_id"), r.get("market"), r.get("selection")))
        picks.append({
            "event_id": r.get("event_id"), "date": r.get("date"), "sport": r.get("sport"), "start_utc": r.get("start_utc"),
            "away": r.get("away"), "home": r.get("home"), "selection": r.get("selection"), "side": r.get("side"),
            "price": r.get("price_average"), "result": graded.get("result") if graded else None,
            "rules_version": g.get("rules_version") or r.get("rules_version"),
            "hound_version": g.get("hound_version") or r.get("hound_version"),
            "scores": g.get("scores"), "margin": g.get("margin"), "threshold": g.get("threshold"),
            "comparisons": g.get("comparisons"), "search_space": g.get("search_space"), "matches": g.get("matches"),
            "history": g.get("history"), "evidence": g.get("evidence"),
        })
    return {"hound_id": hound_id, "started": bool(bets), "picks": picks, "copy": EXPERIMENTAL_LINE,
            "paper_only": PAPER_ONLY, "not_advice": NOT_ADVICE}
