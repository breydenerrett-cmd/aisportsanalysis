"""One smoke test: the engine and settle against the REAL captured stores for past forward dates.

Counts are printed, never asserted exactly: the point is that the real board's shapes (MLB rows with
no sport key, NFL rows, in-play rows, mixed lines) run through the engine and the card ledger's
grading without an exception, that the ledger it writes verifies, and that a replay is idempotent.
It writes to a scratch ledger only. Skipped on a checkout without the multibook store.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.hounds import user_engine as eng
from src.hounds import user_settle as st
from tests._hounds_user_fixtures import hound, utc

DATES = ("2026-10-11", "2026-10-14")     # an NFL Sunday and a midweek MLB date, both played
STORE = Path(paths.repo_root()) / "data" / "processed" / "odds_multibook.jsonl"
RESULTS = Path(paths.repo_root()) / "data" / "historical" / "mlb_results.csv"
NOW = utc("2026-10-20T00:00:00Z")


@unittest.skipUnless(STORE.exists() and RESULTS.exists(), "real stores not present")
class RealStoresSmoke(unittest.TestCase):
    def test_replay_forward_dates_then_settle_them(self):
        hounds = [
            hound("u-s1", name="Smoke Dogs"),
            hound("u-s2", name="Smoke Moves", markets=["moneyline", "spread", "total"],
                  side_rule="market_moved_toward", price_min=-195, price_max=300, min_books=3,
                  max_bets_per_day=5),
            hound("u-s3", name="Smoke Overs", markets=["total"], side_rule="over", price_min=-150,
                  price_max=150, lock_minutes=60),
            hound("u-s4", name="Smoke Pigskin", sports=["MLB", "NFL"], markets=["spread"],
                  side_rule="favourite", price_min=-195, price_max=150),
        ]
        index = eng._load_game_pk_index()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "smoke.jsonl")
            for date in DATES:
                rows = eng.load_rows(date, {"MLB", "NFL"})
                self.assertGreater(len(rows), 0)
                report = eng.run(date, hounds, rows, ledger=ledger, mode="replay", now=NOW,
                                 game_pk_index=index)
                again = eng.run(date, hounds, rows, ledger=ledger, mode="replay", now=NOW)
                self.assertEqual(again["bets_written"], 0)
                print(f"\nhounds smoke {date}: games_seen={report['games_seen']} "
                      f"bets_written={report['bets_written']} by_hound={report['by_hound']} "
                      f"skipped={report['skipped']}")
            # NFL scores need the network; inject none so those bets stay pending, offline.
            settled = st.settle(ledger=ledger, now=NOW, lookback_days=30,
                                nfl_results=lambda d: {})
            verify = eng.verify_ledger(ledger)
            print(f"hounds smoke settle: considered={settled['considered']} graded={settled['graded']} "
                  f"pending={settled['pending']} by_result={settled['by_result']} | "
                  f"chain ok={verify.ok} rows={verify.rows_checked}")
            self.assertTrue(verify.ok)
            bets = [r for r in eng.read_ledger(ledger) if r["kind"] == eng.KIND_BET]
            for row in bets:
                self.assertGreater(row["price"], -200)               # the cap holds on real data
                self.assertLess(row["lock_utc"], row["commence_time"])
                self.assertLess(row["board_observed_utc"], row["commence_time"])
            self.assertEqual(settled["graded"] + settled["pending"], settled["considered"])
            self.assertGreater(len(bets), 0)


if __name__ == "__main__":
    unittest.main()
