"""The real stores behind the diagnosis's rest and line-movement factors.

``diagnosis.diagnose`` takes a ``Context`` so a test can hand it fakes and so a request that has no stores answers "not
checked" instead of reading a disk by accident. This module builds the context a live request uses:

  REST          ``user_facts.FactBook``, the schedule and results the rules engine itself reads (a team that played the day
                before has 0 days off). Loaded once per context, the first time a bet needs it.
  LINE MOVEMENT the captured multi-book odds (``boards.scan``, the same one-pass reader the public stats use). For each bet the
                hound's own recorded board-average price is turned into a win probability, the closing board's average price
                for the same side and line is turned into one the same way, and the move is the difference in points
                (negative = the board moved against the pick). Both ends are raw averages across books, so the book's margin
                sits in both and does not make every pick look like it moved against. A bet is counted only when the market
                closed on the same line, at least ``MIN_CLOSE_BOOKS`` books quoted it, and the closing capture was not stale.
                The scan runs on copies of the bets, on a thread, and gives up after ``CLOSE_BUDGET_S`` seconds: a read that
                is too slow is a named "not checked", never a hung request.

A failure of either is a reason string in ``Context.reasons``; the factor then reads "not checked (reason)".
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
from typing import Any, Mapping, Optional, Sequence

from src.core import odds as odds_math
from src.hounds import boards
from src.hounds.interact.diagnosis import Context
from src.report import clv

logger = logging.getLogger("linehound.hounds.diagnosis_live")

CLOSE_BUDGET_S = 12.0           # how long the closing-odds scan may take inside a request
MIN_CLOSE_BOOKS = boards.MIN_AVERAGE_BOOKS
_SCAN_GATE = threading.Semaphore(1)


class Unavailable(Exception):
    """A factor's store could not answer; the message is the reason the screen shows."""


def _implied(price) -> Optional[float]:
    try:
        return 1.0 / odds_math.american_to_decimal(price)
    except Exception:  # noqa: BLE001 -- a price that is not a price is "unknown"
        return None


def board_moves(bets: Sequence, *, multibook_path=None, budget_s: float = CLOSE_BUDGET_S) -> dict:
    """``{bet_id: points}``: how far the board's average win probability for the pick moved between the bet and the close.
    Only the bets that could be measured are in it. Raises ``Unavailable`` when the odds store is missing or too slow."""
    from src.pipeline import snapshots
    path = multibook_path or snapshots.DEFAULT_MULTIBOOK_PATH
    if not path or not os.path.exists(str(path)):
        raise Unavailable("no captured odds are stored on this server")
    # one scan at a time on this process: a second training that wants the closing odds while one is being read goes without them
    # (the factor says so) instead of starting a second pass over the store
    if not _SCAN_GATE.acquire(blocking=False):
        raise Unavailable("the closing odds are being read for another request just now")
    copies = [dataclasses.replace(b) for b in bets]
    box: dict = {}

    def work():
        try:
            dated = [b.date for b in copies if b.date]
            box["index"], _teams = boards.scan(copies, path, since=min(dated) if dated else None)
        except Exception as exc:  # noqa: BLE001 -- reported below as a reason
            box["error"] = exc
        finally:
            _SCAN_GATE.release()

    worker = threading.Thread(target=work, daemon=True, name="diagnosis-board-moves")
    worker.start()
    worker.join(budget_s)
    if worker.is_alive():
        raise Unavailable("the closing odds took too long to read")
    if "error" in box:
        logger.warning("diagnosis: closing-odds scan failed (%s: %s)", type(box["error"]).__name__, box["error"])
        raise Unavailable("the closing odds could not be read")
    index = box["index"]
    moves: dict = {}
    for b in copies:
        shape = clv.MARKET_SHAPES.get(b.market_key)
        if shape is None or b.side not in shape.sides or not b.event_id:
            continue
        start = b.price_average if b.price_average is not None else b.avg_price
        if start is None:
            continue
        try:
            board = clv.closing_board(index.get(b.event_id), b.market_key, b.side, b.line)
        except clv.ClvError:
            continue
        if not isinstance(board, Mapping) or "quotes" not in board or board.get("lead_stale"):
            continue
        slot = shape.sides[b.side].slot
        prices = [q.get(f"{slot}_price") for q in board["quotes"]]
        prices = [int(p) for p in prices if isinstance(p, (int, float)) and not isinstance(p, bool) and abs(p) >= 100]
        if len(prices) < MIN_CLOSE_BOOKS:
            continue
        close_avg = boards.american_mean(prices)
        p0, p1 = _implied(start), _implied(close_avg) if close_avg is not None else None
        if p0 is None or p1 is None:
            continue
        moves[b.bet_id] = round((p1 - p0) * 100.0, 3)
    return moves


def live_context(*, multibook_path=None, budget_s: float = CLOSE_BUDGET_S) -> Context:
    """The context a live request uses: real schedule, real captured odds, each one a named reason when it cannot answer."""
    ctx = Context()
    state: dict = {}

    def book():
        if "book" not in state:
            from src.hounds.user_facts import FactBook
            state["book"] = FactBook.from_stores("")
        return state["book"]

    def rest_days(sport: str, team: str, slate: str, lock: Any) -> Optional[int]:
        try:
            from src.hounds.user_engine_v2 import team_code
            code = team_code(team, sport)
            return book().rest_days(sport, code, slate, lock) if code else None
        except Exception as exc:  # noqa: BLE001
            ctx.reasons.setdefault("rest", "the schedule could not be read")
            logger.warning("diagnosis: schedule unavailable (%s: %s)", type(exc).__name__, exc)
            return None

    def moves(bets: Sequence) -> Mapping:
        try:
            return board_moves(bets, multibook_path=multibook_path, budget_s=budget_s)
        except Unavailable as exc:
            ctx.reasons["move"] = str(exc)
            return {}

    ctx.rest_days = rest_days
    ctx.board_moves = moves
    return ctx
