"""Put the pick grades on the public tickets list (``GET /hounds/{id}/bets``) without touching a ledger.

``src/hounds/pick_grades.py`` is the pure grader. This is the thin glue that gathers what it needs from the stats book the
route already holds: the hound's WHOLE record (every season, every status, forward bets only), widened to every version of
its lineage, and the page of tickets being returned. Nothing is read from disk here beyond the lineage lookup of a member
hound (one indexed query), nothing is written anywhere, and a failure to grade can never fail the list: the tickets are
returned without a ``grades`` block and the page says "not yet available".

WHY THE WHOLE LINEAGE. A member hound's edit or training makes a NEW version with a new id (``user_store``: ``version_of``,
``root_id``); the old version's bets stay on the old id. The owner's ruling is that a version is graded on its lineage's
record (every version of the same root), and point in time keeps that honest: a pick only ever sees what had settled before
it was placed, whichever version placed it. A house hound is one id with its versions stamped on the rows, so its own
record already is its lineage. When the lineage cannot be looked up, the hound's own version is used.

The ticket list's season, status, outcome and sort filters narrow the PAGE, never the history the grades are read from.

ONE GRADER FOR EVERY SCREEN. The Analyze report (``analyze_report.load_report``) shows the same tickets with the same two meters,
and ``grades_by_key`` is how it gets them: the SAME ``history_for`` and ``pick_grades.grades_for_page`` as ``attach_grades``, keyed by
the ticket's stable key instead of its position on a page. A pick therefore reads the same Confidence and Value on its card and in
the report, because there is one history and one grader (owner ask 2026-10-29: "same grades everywhere").
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from src.hounds import pick_grades, seasons

logger = logging.getLogger(__name__)


def lineage_ids(hound_id: str) -> list:
    """Every version id of the hound's lineage (oldest first), always including ``hound_id``; just ``[hound_id]`` for a house
    hound, for a hound the app database does not know, and whenever the lookup fails."""
    ids = [hound_id]
    try:
        from src.hounds import user_defs
        if user_defs.db_exists():
            from src.hounds import user_store
            found = [v["id"] for v in user_store.lineage(hound_id)]
            if hound_id in found:
                ids = found
    except Exception:  # noqa: BLE001 -- a lookup failure falls back to the hound's own version
        logger.exception("pick grades: lineage lookup failed for %s", hound_id)
    return ids


def _all_bets(data) -> list:
    return list(data.view(seasons.ALL).bets) if data is not None else []


def history_for(hound_id: str, own_data, data_for: Callable[[str], Optional[object]]) -> list:
    """Every ``BetRow`` of the hound's lineage: its own (``own_data``, already in hand) plus each other version's, fetched
    with ``data_for(version_id)`` (a ``stats.HoundData`` or None)."""
    rows = _all_bets(own_data)
    for vid in lineage_ids(hound_id):
        if vid != hound_id:
            rows.extend(_all_bets(data_for(vid)))
    return rows


def grades_by_key(hound_id: str, own_data, data_for: Callable[[str], Optional[object]], key_fn: Callable[[object], str]) -> dict:
    """``{key_fn(bet): grades}`` for every forward ticket of the hound's whole record (all seasons), graded against its lineage's
    history exactly as ``attach_grades`` grades a page of them. A replay ticket has no grades and is left out. Raises what the grader
    raises: the caller decides what a failure costs (the report goes on without meters)."""
    page = [b for b in _all_bets(own_data) if getattr(b, "segment", "forward") == "forward"]
    blocks = pick_grades.grades_for_page(history_for(hound_id, own_data, data_for), page)
    return {key_fn(bet): block for bet, block in zip(page, blocks) if block is not None}


def attach_grades(payload: dict, page_items: list, hound_id: str, own_data,
                  data_for: Callable[[str], Optional[object]]) -> dict:
    """Add a ``grades`` block to each item of ``payload["items"]`` (the JSON of ``page_items``, same order). Additive: every
    existing key is untouched. Returns ``payload``. A replay ticket gets ``grades: null``."""
    try:
        items = payload.get("items") or []
        if not items or len(items) != len(page_items):
            return payload
        grades = pick_grades.grades_for_page(history_for(hound_id, own_data, data_for), page_items)
        for item, block in zip(items, grades):
            item["grades"] = block
    except Exception:  # noqa: BLE001 -- the list is the product; a grading failure only leaves the meters empty
        logger.exception("pick grades failed for %s", hound_id)
    return payload
