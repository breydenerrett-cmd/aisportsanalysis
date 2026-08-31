"""The ledger against the failure modes the reliability audit actually found.

Three findings from 2026-08-30: five duplicate recommendation sets from
repeated briefing runs; a whole date whose FIRST (and therefore kept)
entries carried no prices because the briefing ran before any snapshot
existed; and a skipped settle day nobody noticed until an audit. Each gets
its rule pinned here.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import ledger


def _rec(game_pk, date, prices=None, recorded_at="2026-08-30T04:17:00Z"):
    return {"kind": ledger.RECOMMENDATION, "game_pk": game_pk, "date": date,
            "recorded_at": recorded_at, "verdict": "no_play",
            "prices": prices or {}}


def _write(path, entries):
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


class WriteDedupTests(unittest.TestCase):
    def _slate(self, pks):
        import datetime as dt

        class Dossier:
            def __init__(self, pk):
                self.game = {"game_pk": pk}
                self.sections = {}
                self.gaps = {}
                self.information_time = dt.datetime(
                    2026, 8, 30, 4, 17, tzinfo=dt.timezone.utc)

            def get(self, name, default=None):
                return default

        return {"date": "2026-08-30",
                "games": [{"dossier": Dossier(pk), "verdict": "no_play",
                           "findings": []} for pk in pks]}

    def test_a_rerun_briefing_appends_nothing_new(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.jsonl"
            first = ledger.record_slate(self._slate([1, 2]), path=path)
            second = ledger.record_slate(self._slate([1, 2]), path=path)
            lines = path.read_text().splitlines()
        self.assertEqual(first["recorded"], 2)
        self.assertEqual(second["recorded"], 0)
        self.assertEqual(second["skipped_already_recorded"], 2)
        self.assertEqual(len(lines), 2)

    def test_a_priced_rerun_repairs_a_priceless_record(self):
        """The one repeat worth writing: the 04:17 run recorded the game
        with no prices; the 18:00 run has a market. The second row must be
        written so recommendations() can prefer it."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.jsonl"
            ledger.record_slate(self._slate([1]), path=path)  # price-less
            priced = self._slate([1])
            market = {"markets": {"h2h": {"book": "book_a",
                                          "away_price": -110,
                                          "home_price": -110}}}
            priced["games"][0]["dossier"].get = (
                lambda name, default=None, _m={"market": market}:
                _m.get(name, default))
            second = ledger.record_slate(priced, path=path)
            rows = ledger.recommendations(path=path)
        self.assertEqual(second["recorded"], 1)
        self.assertTrue(rows[0].get("prices"))

    def test_a_new_game_in_a_rerun_is_still_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.jsonl"
            ledger.record_slate(self._slate([1]), path=path)
            second = ledger.record_slate(self._slate([1, 2]), path=path)
        self.assertEqual(second["recorded"], 1)
        self.assertEqual(second["skipped_already_recorded"], 1)


class FirstPricedTests(unittest.TestCase):
    def test_a_priced_entry_supersedes_an_earlier_priceless_one(self):
        entries = [
            _rec(1, "2026-08-30", prices=None,
                 recorded_at="2026-08-30T04:17:00Z"),
            _rec(1, "2026-08-30", prices={"away": -110, "home": -110},
                 recorded_at="2026-08-30T18:00:00Z"),
        ]
        kept = ledger.recommendations(entries)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["recorded_at"], "2026-08-30T18:00:00Z")

    def test_among_priced_entries_the_first_still_wins(self):
        """The original rule survives where it was right: a later, closer
        price must never replace what the system first actually knew."""
        entries = [
            _rec(1, "2026-08-30", prices={"away": -110, "home": -110},
                 recorded_at="2026-08-30T12:00:00Z"),
            _rec(1, "2026-08-30", prices={"away": -150, "home": +130},
                 recorded_at="2026-08-30T22:00:00Z"),
        ]
        kept = ledger.recommendations(entries)
        self.assertEqual(kept[0]["recorded_at"], "2026-08-30T12:00:00Z")

    def test_a_never_priced_game_keeps_its_first_row_and_its_gap(self):
        entries = [_rec(1, "2026-08-30", prices=None)]
        kept = ledger.recommendations(entries)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["prices"], {})


class SettleGapTests(unittest.TestCase):
    def test_a_skipped_settle_day_is_named_in_status(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.jsonl"
            _write(path, [
                _rec(1, "2026-08-29"),
                {"kind": ledger.SETTLEMENT, "game_pk": 1,
                 "settled_at": "x", "result": {}, "closing": None,
                 "closing_reason": "r"},
                _rec(2, "2026-08-30"),   # never settled -- the gap
                _rec(3, "2026-08-31"),   # today; pending is normal
            ])
            status = ledger.status(path=path)
        self.assertIn("2026-08-30", status["unsettled_past_dates"])
        self.assertNotIn("2026-08-31", status["unsettled_past_dates"])
        self.assertNotIn("2026-08-29", status["unsettled_past_dates"])


if __name__ == "__main__":
    unittest.main()
