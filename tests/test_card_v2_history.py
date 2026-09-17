"""T5 -- `card_ledger.history_v2`, the day-by-day detail behind
`/card/history?rule=v2` (`record_v2`'s pooled-totals counterpart).

Same fixture style as `tests/test_card_v2_ledger.py`: an injected temp-dir
store path and a fixed clock, never the real ledger.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.analysis import best_bets_card as bbc
from src.appstate import card_ledger as cl

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _candidate(**over):
    base = dict(
        game_id="G1", game_pk="G1", price=-140, market_probability=0.55,
        our_probability=0.65, books=8, observed_utc=NOW - timedelta(seconds=60),
        has_started=False, calibrated=True, bet_sentence="the Padres",
        first_pitch_utc="2026-09-16T23:00:00Z", kind="game", market="moneyline",
        side="home", game_type="R", entry_class="pick", score=0.10,
        failed_gates=[],
    )
    base.update(over)
    return base


class HistoryV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "cards_v2.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _publish_and_settle(self, date, game_id="G1", won=True):
        card = {"date": date, "all_bets": [_candidate(
            game_id=game_id, game_pk=game_id,
            first_pitch_utc=f"{date}T23:00:00Z")], "params": bbc.V2}
        cl.publish_v2(card, now=_iso(NOW), path=self.path)
        result = ({"away_score": 2, "home_score": 5, "home_won": True}
                  if won else {"away_score": 5, "home_score": 2, "home_won": False})
        cl.settle_v2(date, {game_id: result}, path=self.path)

    def test_no_rows_returns_an_empty_shape(self):
        out = cl.history_v2(path=self.path)
        self.assertEqual([], out["days"])
        self.assertEqual(0, out["total_days"])
        self.assertFalse(out["truncated"])

    def test_one_settled_day_is_reported_newest_first(self):
        self._publish_and_settle("2026-09-15")
        self._publish_and_settle("2026-09-16")
        out = cl.history_v2(path=self.path)
        self.assertEqual(2, out["total_days"])
        self.assertEqual(["2026-09-16", "2026-09-15"],
                         [d["date"] for d in out["days"]])

    def test_limit_caps_and_reports_truncated_honestly(self):
        self._publish_and_settle("2026-09-14")
        self._publish_and_settle("2026-09-15")
        self._publish_and_settle("2026-09-16")
        out = cl.history_v2(path=self.path, limit=2)
        self.assertEqual(2, len(out["days"]))
        self.assertEqual(3, out["total_days"])
        self.assertTrue(out["truncated"])

    def test_each_day_carries_its_own_graded_entries_with_price_class(self):
        self._publish_and_settle("2026-09-16")
        out = cl.history_v2(path=self.path)
        day = out["days"][0]
        self.assertIn("graded", day)
        self.assertEqual(1, len(day["graded"]))
        self.assertIn("price_class", day["graded"][0])
        self.assertIn("entry_class", day["graded"][0])

    def test_unsettled_published_days_are_not_listed(self):
        # Published but never settled -- history_v2 reads KIND_SETTLED rows
        # only, exactly like record_v2 does (a published-only day has
        # nothing graded yet to report).
        card = {"date": "2026-09-16", "all_bets": [_candidate()], "params": bbc.V2}
        cl.publish_v2(card, now=_iso(NOW), path=self.path)
        out = cl.history_v2(path=self.path)
        self.assertEqual([], out["days"])


if __name__ == "__main__":
    unittest.main()
