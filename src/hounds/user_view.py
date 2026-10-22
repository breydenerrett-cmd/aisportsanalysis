"""The public view of a user hound: ONE referee, ONE contract.

``user_settle`` can compute a closing-line value and a verdict of its own. Neither is public. A hound's
label, record, CLV and series come from ``src.hounds.stats`` (which reads this program's ledgers through
``ledgers.pack_ledger_rows``, measures CLV with ``src.report.clv`` and labels with
``src.hounds.verdict``, the pre-registered referee, docs/PREREG_HOUND_VERDICT.md). This module is the
one place that turns "a hound row from the app database" into a ``HoundSummary``-shaped dict, so the
creation API, ``/hounds/mine``, the scorecard and the public race all say the same thing.

WHERE THE NUMBERS COME FROM, IN ORDER
  1. the cached stats book, fresh or stale (a stale one is a few seconds behind, never wrong in kind);
  2. if the book has not been built yet, or does not know this hound yet (it was created a moment
     ago): the same ``stats.summarize`` over this hound's own rows of the user ledger, WITHOUT the
     board scan. That has a real record (the ledger holds the prices and results) and no CLV, so the
     referee says TOO EARLY with n = 0. That is the true answer for "no closing price measured yet",
     not a guess, and a background build is started so the next read has the measured one.
Nothing here ever waits for the stats build.

TWO PRICES, ONE MEANING (owner grading ruling 2026-09-21, restated 2026-10-18)
  units_average_price   units had the bet been taken at the board AVERAGE at lock: the headline.
  units_recorded_price  units at the single BEST quote recorded at lock: the small print.
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.hounds import ledgers, seasons, stats, user_defs, user_engine, verdict as vd
from src.hounds.contract import VerdictBlock, paginate, to_json


def _ledger_bets(hound_id: str, rows: Optional[Sequence] = None) -> list:
    if rows is None:
        bets, _defs = ledgers.pack_ledger_rows(user_engine.ledger_path())
    else:
        bets, _defs = ledgers.pack_rows(rows)
    return [b for b in bets if b.hound_id == hound_id]


def _from_ledger(defn: dict, rows: Optional[Sequence] = None) -> stats.HoundData:
    """Stats for one hound from its own ledger rows alone (no board scan, so no CLV)."""
    bets = _ledger_bets(defn["id"], rows)
    stamps = [str(b.decision_utc or b.date)[:10] for b in bets if (b.decision_utc or b.date)]
    as_of = max(stamps, default=None)
    return stats.with_seasons(stats.summarize(defn, bets, {}, as_of), defn, bets, {}, as_of)


def hound_data(hound_id: str, *, kick_build: bool = True,
               rows: Optional[Sequence] = None) -> Optional[stats.HoundData]:
    """The stats for one user hound, or None when the app database does not know it.

    ``rows`` (ledger rows in hand, for a caller that already read them) skips the cached book and
    summarises those rows alone."""
    if rows is None:
        book = stats.peek_book()
        if book is not None and hound_id in book.hounds:
            return book.hounds[hound_id]
    defn = user_defs.get_definition(hound_id)
    if defn is None:
        return None
    if kick_build and rows is None:
        stats.refresh_async()
    return _from_ledger(defn, rows)


def summary(hound: dict) -> dict:
    """The contract ``HoundSummary`` (as JSON primitives) for a ``user_store`` hound row."""
    data = hound_data(hound["id"])
    if data is None:                                    # the row exists but is unreadable as a spec
        data = _from_ledger(user_defs.definition(hound))
    return to_json(data.summary)


def verdict_block(hound_id: str, rows: Optional[Sequence] = None) -> dict:
    """``{label, sentence, units_note}`` from the referee; TOO EARLY, n = 0 when nothing is measured."""
    data = hound_data(hound_id, rows=rows)
    if data is not None:
        return to_json(data.summary.verdict)
    v = vd.verdict_for([])
    return to_json(VerdictBlock(label=v.label, sentence=v.sentence, units_note=vd.units_note(0)))


def detail(hound_id: str, *, page: int = 1, page_size: Optional[int] = None,
           season: str = seasons.ALL) -> Optional[dict]:
    """A ``hound_payload``-shaped dict for a user hound the public book does not list yet, else None."""
    data = hound_data(hound_id)
    if data is None:
        return None
    from src.hounds.contract import hound_payload
    book = stats.peek_book()
    view = data.view(season)
    return hound_payload(view.summary, view.series, paginate(view.bets, page, page_size),
                         book.as_of if book else None, seasons.meta(season))


def bets_for(hound_id: str, *, page: int = 1, page_size: Optional[int] = None,
             segment: Optional[str] = None, status: Optional[str] = None,
             season: str = seasons.ALL, outcome: Optional[str] = None, sort: Optional[str] = None) -> Optional[dict]:
    data = hound_data(hound_id)
    if data is None:
        return None
    view = data.view(season)
    rows = view.bets if segment is None else [b for b in view.bets if b.segment == segment]
    from src.hounds.contract import bets_payload, filter_by_status, refine_bets
    rows = refine_bets(filter_by_status(rows, status), outcome, sort)
    book = stats.peek_book()
    return bets_payload(hound_id, paginate(rows, page, page_size), book.as_of if book else None,
                        seasons.meta(season))
