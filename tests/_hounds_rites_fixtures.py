"""Ledger rows for the two owner rites (tests/test_hounds_outback.py, test_hounds_training.py, test_hounds_rites_*.py).

A settled ticket is two ledger rows exactly as the engine and the grader write them: a ``hound_user_bet`` row and a
``hound_user_graded`` row that names it by ``bet_id``. Nothing here reads a live store; ``rows_for`` is the list the
rites take through their ``rows=`` seam, ``write_ledger`` puts them in a real hash-chained file for the route tests.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.hounds import user_engine, user_settle
from src.ledger.chain import HashChainLedger

BASE_DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
_ids = itertools.count(1)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _profit(result: str, price: int) -> float:
    if result == "LOSS":
        return -1.0
    if result == "PUSH":
        return 0.0
    return price / 100.0 if price > 0 else 100.0 / abs(price)


def ticket(hound_id: str, *, day: int = 0, result: Optional[str] = "WIN", sport: str = "MLB", market: str = "moneyline",
           side: str = "home", price: int = -120, line: Optional[float] = None, rule_index: Optional[int] = None,
           start_hours_ago: Optional[float] = None, now: Optional[datetime] = None) -> list:
    """The rows for ONE ticket: its bet row and, when ``result`` is given (WIN/LOSS/PUSH/VOID), its graded row.

    ``day`` places it ``day`` days after 2026-10-01. ``start_hours_ago`` (with ``now``) pins the game's start so a test
    can make a ticket "open" (recent) or "ungraded" (more than 36 hours past)."""
    n = next(_ids)
    moment = BASE_DAY + timedelta(days=day, hours=18)
    start = (now - timedelta(hours=start_hours_ago)) if (now is not None and start_hours_ago is not None) else moment + timedelta(hours=2)
    bet_id = f"b-test{n:06d}"
    away, home = "Boston Red Sox", "Seattle Mariners"
    selection = f"{home if side == 'home' else away} to win" if market == "moneyline" else \
        (f"{side.title()} 8.5" if market == "total" else f"{home if side == 'home' else away} {line or -1.5:+g}")
    bet = {"kind": user_engine.KIND_BET, "ledger_version": 1, "paper_only": True, "bet_id": bet_id, "hound_id": hound_id,
           "sport": sport, "event_id": f"evt{n:06d}", "slate_date": moment.strftime("%Y-%m-%d"), "date": moment.strftime("%Y-%m-%d"),
           "commence_time": _iso(start), "start_utc": _iso(start), "away_team": away, "home_team": home, "market": market,
           "side": side, "line": line, "selection": selection, "price": price, "price_average": price, "best_price": price,
           "price_best": price, "best_book": "book_a", "book": "book_a", "n_books": 5, "book_count": 5,
           "lock_utc": _iso(moment), "recorded_utc": _iso(moment), "units": 1, "segment": "forward", "provenance": "live",
           "who_decided": "rule", "reason": "test"}
    if rule_index is not None:
        bet.update({"rule_index": rule_index, "stake_units": 1.0, "spec_version": 2})
    rows = [bet]
    if result is not None:
        profit = _profit(result, price)
        rows.append({"kind": user_settle.KIND_GRADED, "ledger_version": 1, "paper_only": True, "bet_id": bet_id,
                     "hound_id": hound_id, "result": result, "profit_units": profit, "profit_units_best": profit,
                     "units": profit, "units_best_price": profit, "units_average_price": profit,
                     "date": bet["slate_date"], "slate_date": bet["slate_date"], "segment": "forward",
                     "graded_utc": _iso(moment + timedelta(hours=8))})
    return rows


def rows_for(hound_id: str, spec: list) -> list:
    """Many tickets at once. ``spec`` is a list of ``(count, keyword dict)``: ``[(6, dict(result="LOSS", side="away"))]``."""
    rows: list = []
    day = 0
    for count, kw in spec:
        for _ in range(count):
            rows.extend(ticket(hound_id, day=day, **kw))
            day += 1
    return rows


def write_ledger(path, rows) -> None:
    chain = HashChainLedger(path)
    for row in rows:
        chain.append(dict(row))


# ---------------------------------------------------------------------------------------------------------------
# the case every rites test builds on: a temp app database, a temp ledger, an owner, someone else, a dog
# ---------------------------------------------------------------------------------------------------------------

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds import stats, user_store
from src.hounds.interact import common
from tests._hounds_user_fixtures import spec_dict, utc

NOW = utc("2026-10-20T21:30:00Z")


class RitesCase(unittest.TestCase):
    """No FastAPI anywhere in here: the rites are plain functions over the app database and the ledger."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.ledger = str(tmp / "hounds_user_v1.jsonl")
        for p in (mock.patch.object(users_store, "db_path", lambda: self.db),
                  mock.patch.object(user_engine, "ledger_path", lambda path=None: path or self.ledger),
                  mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
                  mock.patch.object(stats, "peek_book", lambda: None),
                  mock.patch.object(stats, "get_book_nowait", lambda *a, **k: (None, "warming")),
                  mock.patch.object(common, "now_utc", lambda: NOW)):
            p.start()
            self.addCleanup(p.stop)
        self.owner = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.other = users_store.create_user("other@example.com", status="active", db=self.db)

    def dog(self, name="Rusty Pup", owner=None, **spec) -> dict:
        row = user_store.create_hound((owner or self.owner).id, spec_dict(name=name, **spec))
        return row

    def resolve(self, hound_id):
        return common.resolve(hound_id)
