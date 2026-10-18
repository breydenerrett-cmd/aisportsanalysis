"""The three halves of the Hounds feature agree: ledgers, stats, routes, scheduler, pages.

Each class pins one misalignment found when H1 (core + read API), H3 (user hounds) and H2 (pages) were
put together, with the story in its docstring. Nothing reads a live store: boards, results and the
app database are built here.

The scheduler, route-order and page-contract classes live further down this file.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.hounds import contract, ledgers, stats, user_defs, user_engine as eng
from src.hounds import user_settle as st
from src.hounds.ledgers import Sources
from tests._hounds_user_fixtures import (DATE, EVENT, T_LATE, T_LOCK, board_rows, hound,
                                         result_row, standard_rows, utc)

AT_LOCK = utc("2026-10-20T21:10:00Z")
NEXT_DAY = utc("2026-10-21T12:00:00Z")
PK = "900001"
INDEX = {EVENT: {"game_pk": PK}}

# Three books disagree: average of +100, +200, +150 (decimals 2, 3, 2.5) is +150, the best is +200.
# Six books, because the closing board needs the consensus floor (src.analysis.prices.MIN_BOOKS) to count.
SPREAD_OUT_LOCK = [("a", -130, 100), ("b", -150, 200), ("c", -140, 150),
                   ("d", -130, 100), ("e", -150, 200), ("f", -140, 150)]


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def read_rows(path) -> list:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def user_row(h: dict, **over) -> dict:
    """A user_store-shaped hound row for a fixture hound."""
    row = {"id": h["id"], "owner_user_id": 7, "name": "Dog Days", "tagline": "Dogs bark",
           "spec": h["spec"], "spec_hash": h["spec_hash"], "status": "running",
           "retire_reason": None, "retired_at": None, "retired_by": None,
           "created_at": h["created_at"], "version_of": None, "root_id": h["id"], "version_no": 1,
           "copied_from": None, "coach_opt_in": False}
    row.update(over)
    return row


class World:
    """A temp world: the standard game's boards, a user ledger, and Sources pointing at them."""

    def __init__(self, root: Path, board=None):
        self.root = root
        self.multibook = root / "data" / "processed" / "odds_multibook.jsonl"
        write_jsonl(self.multibook, board if board is not None else standard_rows())
        self.ledger = str(root / "data" / "app" / "hounds_user_v1.jsonl")
        self.hounds = []

    def add_hound(self, hid="u-int1", **spec) -> dict:
        h = hound(hid, **spec)
        self.hounds.append(user_row(h))
        return h

    def bet(self, mode="live"):
        eng.run(DATE, [hound_for(r) for r in self.hounds], eng.load_rows(DATE, ["MLB"],
                multibook_path=str(self.multibook)), ledger=self.ledger, now=AT_LOCK,
                game_pk_index=INDEX, mode=mode)

    def settle(self, away=5, home=3):
        return st.settle(ledger=self.ledger, now=NEXT_DAY, close_fn=lambda b: None,
                         mlb_results={PK: result_row(PK, DATE, "BOS", "SEA", away, home)},
                         game_pk_index=INDEX)

    def sources(self) -> Sources:
        r = self.root
        return Sources(
            decisions=r / "evidence" / "decisions_v2.jsonl", wagers=r / "evidence" / "w.jsonl",
            accounts_dir=r / "data" / "paper_accounts", multibook=self.multibook,
            card_v2=None, house_hounds_cfg=r / "config" / "house_hounds.json",
            house_pack_cfg=r / "config" / "house_pack.json",
            pack_ledgers=(("user", Path(self.ledger)),),
            user_hounds=lambda: [user_defs.definition(h) for h in self.hounds],
            user_stamp=lambda: ("user_hounds", len(self.hounds)))


def hound_for(row: dict) -> dict:
    return {"id": row["id"], "spec": row["spec"], "spec_hash": row["spec_hash"],
            "created_at": row["created_at"]}


class UserLedgerIsReadByTheSharedStats(unittest.TestCase):
    """MISALIGNMENT 2. H3 computed its own CLV and verdict and named its prices ``price`` and
    ``best_price``; H1's reader looks for ``price_average`` / ``price_best`` and its referee is the
    only one allowed to speak. The user ledger now carries the contract's names and every public
    number about a user hound comes from stats.build."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.w = World(Path(self._tmp.name), board_rows(T_LOCK, moneyline=SPREAD_OUT_LOCK)
                       + board_rows(T_LATE, moneyline=SPREAD_OUT_LOCK))
        self.h = self.w.add_hound(price_min=100, price_max=300)

    def tearDown(self):
        self._tmp.cleanup()

    def summary(self, hid="u-int1"):
        return stats.build(self.w.sources()).hounds[hid]

    def test_units_average_price_is_the_headline_and_units_recorded_price_is_the_best_quote(self):
        self.w.bet()
        self.w.settle()
        s = self.summary().summary
        self.assertEqual(s.kind, "user")
        self.assertEqual((s.record.bets, s.record.wins), (1, 1))
        self.assertEqual(s.record.units_average_price, 1.5)    # won at the board average, +150
        self.assertEqual(s.record.units_recorded_price, 2.0)   # won at the best quote recorded, +200
        row = self.summary().bets[0]
        self.assertEqual((row.price_average, row.price, row.book), (150, 200, "b"))
        self.assertEqual((row.segment, row.who_decided), ("forward", "rule"))
        self.assertIn("board average", row.reason)

    def test_the_label_is_the_referees_not_the_engines(self):
        self.w.bet()
        self.w.settle()
        d = self.summary()
        # one measurable bet: the pre-registered referee says TOO EARLY whatever the result
        self.assertEqual(d.summary.verdict.label, "TOO EARLY")
        self.assertEqual(d.summary.clv.n, 1)
        self.assertGreater(d.summary.clv.mean_pts, 0)          # +200 recorded vs a +150 close
        self.assertTrue(d.summary.verified)
        self.assertEqual(d.summary.name, "Dog Days")
        self.assertTrue(d.summary.owner_display.startswith("Handler "))

    def test_the_engines_own_clv_column_never_reaches_a_public_number(self):
        self.w.bet()
        self.w.settle()
        rows = read_rows(self.w.ledger)
        for r in rows:
            if r["kind"] == st.KIND_GRADED:
                r["clv_pts"] = 99.0                            # absurd, and ignored
        write_jsonl(Path(self.w.ledger), rows)
        d = self.summary()
        self.assertLess(d.summary.clv.mean_pts, 20)
        self.assertNotEqual(d.bets[0].clv_pts, 99.0)            # H1's own measurement is what shows

    def test_a_replay_run_is_a_separate_block_and_never_a_forward_number(self):
        self.w.bet(mode="replay")
        self.w.settle()
        s = self.summary().summary
        self.assertEqual(s.record.bets, 0)                     # nothing forward
        self.assertEqual((s.replay.bets, s.replay.wins), (1, 1))
        self.assertEqual(s.verdict.label, "TOO EARLY")
        self.assertEqual(s.verdict.sentence.split()[1], "0")   # n = 0
        self.assertEqual(self.summary().bets[0].segment, "replay")

    def test_a_hound_with_no_bet_yet_is_running_not_benched(self):
        s = self.summary().summary
        self.assertEqual((s.status, s.record.bets, s.verdict.label), ("running", 0, "TOO EARLY"))

    def test_a_retired_hound_goes_to_the_graveyard_with_the_contracts_cause(self):
        self.w.hounds[0].update(status="retired", retired_at="2026-10-21T01:00:00Z",
                                retired_by="owner:7", retire_reason="not for me")
        s = self.summary().summary
        self.assertEqual(s.status, "retired")
        self.assertEqual((s.retired.date, s.retired.cause), ("2026-10-21", "retired by the owner"))
        book = stats.build(self.w.sources())
        self.assertEqual([x.id for x in stats.graveyard(book)], ["u-int1"])
        self.assertEqual(stats.leaderboard(book), [])

    def test_rows_written_before_the_contract_names_read_the_same(self):
        """Old rows (``price`` = average, ``best_price``, ``n_books``, ``commence_time``,
        ``provenance``) mean what the new names mean."""
        self.w.bet()
        self.w.settle()
        new = self.summary().summary
        new_names = ("price_average", "price_best", "book", "book_count", "start_utc", "segment",
                     "who_decided", "reason", "date", "units", "units_best_price",
                     "units_average_price")
        rows = read_rows(self.w.ledger)
        for r in rows:
            for k in new_names:
                r.pop(k, None)
        write_jsonl(Path(self.w.ledger), rows)
        old = self.summary().summary
        self.assertEqual(old.record.units_average_price, new.record.units_average_price)
        self.assertEqual(old.record.units_recorded_price, new.record.units_recorded_price)
        self.assertEqual((old.record.bets, old.verdict.label), (new.record.bets, new.verdict.label))

    def test_the_default_ledger_sits_beside_the_app_database_not_in_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app" / "app.db"
            with mock.patch.dict(os.environ, {"APP_DB_PATH": str(db)}, clear=False):
                os.environ.pop(eng.ENV_LEDGER, None)
                self.assertEqual(Path(eng.ledger_path()), db.parent / eng.LEDGER_NAME)
                self.assertEqual(dict(Sources.default().pack_ledgers)["user"],
                                 db.parent / eng.LEDGER_NAME)
            with mock.patch.dict(os.environ, {eng.ENV_LEDGER: str(Path(tmp) / "x.jsonl")}):
                self.assertEqual(eng.ledger_path(), str(Path(tmp) / "x.jsonl"))
            self.assertEqual(eng.ledger_path("explicit.jsonl"), "explicit.jsonl")


class PackLedgerShape(unittest.TestCase):
    """The house pack's real ledger (evidence/hounds_house_v1.jsonl, replay segment) disagreed with
    H1's reader, which had only been run on fixtures. Found 2026-10-18 reading the real file; the
    READER was fixed, the pack files were not touched."""

    def rows(self):
        bet = {"kind": "hound_bet", "hound_id": "totals_terrier", "date": "2026-09-08",
               "event_id": "E1", "sport": "mlb", "market": "total", "line": 8.5,
               "selection": "Over 8.5", "side": "over", "price_average": -108, "price_best": 100,
               "book": "fanatics", "book_count": 10, "lock_utc": "2026-09-08T21:41:00Z",
               "start_utc": "2026-09-08T22:41:00Z", "who_decided": "random", "segment": "replay",
               "reason": "Seeded dart.", "row_hash": "H-BET"}
        graded = {"kind": "hound_graded", "hound_id": "totals_terrier", "date": "2026-09-08",
                  "event_id": "E1", "sport": "mlb", "market": "total", "selection": "Over 8.5",
                  "side": "over", "result": "WIN", "units_best_price": 1.0,
                  "units_average_price": 0.9259, "segment": "replay", "bet_row_hash": "H-BET",
                  "row_hash": "H-GRADED-1"}                    # no ``line``, no ``bet_id``
        return bet, graded

    def test_a_graded_row_finds_its_bet_by_bet_row_hash_when_it_has_no_line(self):
        bet, graded = self.rows()
        bets, _ = ledgers.pack_rows([bet, graded])
        self.assertEqual(len(bets), 1)                         # was 2: one ungraded, one orphan
        b = bets[0]
        self.assertEqual((b.result, b.line, b.units, b.price, b.price_average),
                         ("win", "8.5", 1.0, 100, -108))

    def test_the_last_grading_of_a_bet_wins(self):
        bet, graded = self.rows()
        regraded = dict(graded, result="LOSS", units_best_price=-1.0, row_hash="H-GRADED-2")
        bets, _ = ledgers.pack_rows([bet, graded, regraded])
        self.assertEqual((len(bets), bets[0].result, bets[0].units), (1, "loss", -1.0))

    def test_a_seeded_draw_is_decided_by_code(self):
        bet, _ = self.rows()
        bets, _ = ledgers.pack_rows([bet])
        self.assertEqual(bets[0].who_decided, "code")
        self.assertIn(bets[0].who_decided, contract.WHO_DECIDED)

    def test_units_average_price_is_not_read_as_recorded_units(self):
        bet, graded = self.rows()
        graded.pop("units_best_price")
        graded["profit_units"] = 0.9259                        # the user ledger's AVERAGE-price profit
        bets, _ = ledgers.pack_rows([bet, graded])
        self.assertIsNone(bets[0].units)                       # recomputed from price_best instead
        self.assertEqual(stats.recorded_units(bets[0]), 1.0)
        self.assertEqual(stats.average_units(bets[0]), round(100 / 108, 4))


if __name__ == "__main__":
    unittest.main()
