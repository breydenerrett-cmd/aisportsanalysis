"""House pack runner: point in time, the -200 rule, daily cap, idempotency, no bet after start, chain."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import timedelta

from src.hounds import pack as pack_mod
from src.hounds import pack_run
from src.hounds.pack import base
from src.ledger.chain import HashChainLedger
from tests.test_house_pack_hounds import START, T, all_picks, basic_stores, game_rows, mlb_game


class _Fav(base.Hound):
    """A test hound that always takes the favourite, whatever its price."""
    id = "test_fav"
    name = "Test Fav"
    category = "simple"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    band = (-100000, 100000)

    def pick(self, board, ctx):
        h, a = base.side_info(board, "moneyline", "home"), base.side_info(board, "moneyline", "away")
        if not h:
            return []
        side = "home" if h["fair"] > a["fair"] else "away"
        return [base.Selection("moneyline", side, 1.0, "favourite")]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "hounds.jsonl")

    def rows(self):
        return HashChainLedger(self.path).read()


class PointInTimeTests(Base):
    def test_quote_after_lock_never_enters_the_board_or_the_picks(self):
        clean = basic_stores()
        late = game_rows("evA", START, observed=START - timedelta(minutes=30), home_ml=-400, away_ml=320,
                         spread=(-2.5, 150, -180), total=(11.5, -120, 100))
        dirty = basic_stores(extra_rows=late)
        ctx_c, ctx_d = base.build_context(clean, "evA"), base.build_context(dirty, "evA")
        self.assertEqual(base.lock_board(clean, ctx_c), base.lock_board(dirty, ctx_d))
        self.assertEqual(all_picks(clean), all_picks(dirty))

    def test_results_and_bullpen_stamped_on_or_after_the_game_date_are_never_used(self):
        clean = basic_stores()
        games = list(clean.mlb_games) + [mlb_game(999, "2026-09-20", "NYY", "BOS", 0, 20),
                                         mlb_game(998, "2026-09-21", "NYY", "BOS", 0, 20)]
        bull = [{"date": "2026-09-20", "team": "NYY", "started": False, "pitches": 900}]
        dirty = basic_stores(mlb_games=games, bullpen=bull)
        self.assertEqual(all_picks(clean), all_picks(dirty))
        ctx = base.build_context(dirty, "evA")
        self.assertTrue(all(g["date"] < "2026-09-20" for g in ctx.mlb_games))
        self.assertEqual(ctx.bullpen, [])

    def test_sealed_rows_are_dropped_before_their_scores_are_read(self):
        path = os.path.join(self._tmp.name, "results.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("game_pk,date,start_time_utc,game_type,away_team,home_team,away_score,home_score\n")
            fh.write("1,2026-05-01,2026-05-01T23:00:00Z,R,NYY,BOS,SEALED,SEALED\n")
            fh.write("2,2026-08-27,2026-08-27T23:00:00Z,R,NYY,BOS,1,2\n")
            fh.write("3,2026-08-28,2026-08-28T23:00:00Z,R,AZ,ATH,3,4\n")
        rows = base.read_mlb_results(path)
        self.assertEqual([r["game_pk"] for r in rows], ["3"])
        self.assertEqual((rows[0]["away"], rows[0]["home"]), ("ARI", "OAK"))   # one spelling per club

    def test_sealed_dates_are_refused_by_the_cli(self):
        self.assertEqual(pack_run.main(["--date", "2026-06-01", "--replay", "--ledger", self.path]), 2)


class RunnerTests(Base):
    def test_minus_200_is_refused(self):
        st = base.Stores()
        for r in game_rows("evH", START, home_ml=-250, away_ml=210):
            st.add_row(r)
        st.finalize()
        c = pack_run.run(st, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.path,
                         hounds=[_Fav()])
        self.assertEqual(c["written"], 0)
        st2 = base.Stores()
        for r in game_rows("evH", START, home_ml=-199, away_ml=170):
            st2.add_row(r)
        st2.finalize()
        pack_run.run(st2, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.path,
                     hounds=[_Fav()])
        self.assertEqual([r["price_average"] for r in self.rows()], [-199])

    def test_no_real_hound_ever_writes_minus_200_or_worse(self):
        st = base.Stores()
        for i in range(4):
            for r in game_rows(f"ev{i}", START + timedelta(minutes=i), home_ml=-300, away_ml=250):
                st.add_row(r)
        st.finalize()
        pack_run.run(st, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.path)
        self.assertTrue(all(r["price_average"] > -200 for r in self.rows()))

    def test_at_most_three_per_day_in_lock_order_and_one_per_game(self):
        st = base.Stores()
        for i in range(6):
            for r in game_rows(f"ev{i}", START + timedelta(minutes=10 * i)):
                st.add_row(r)
        st.finalize()
        pack_run.run(st, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.path,
                     hounds=[_Fav()])
        rows = self.rows()
        self.assertEqual([r["event_id"] for r in rows], ["ev0", "ev1", "ev2"])
        pack_run.run(st, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.path)
        by = {}
        for r in self.rows():
            by.setdefault((r["hound_id"], r["date"]), []).append(r["event_id"])
        for (hid, _), evs in by.items():
            self.assertLessEqual(len(evs), 3, hid)
            self.assertEqual(len(evs), len(set(evs)), hid)

    def test_idempotent(self):
        st = basic_stores()
        pack_run.run(st, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.path)
        first = self.rows()
        self.assertTrue(first)
        c = pack_run.run(st, ["2026-09-20"], replay=True, now=START + timedelta(hours=6), path=self.path)
        self.assertEqual(c["written"], 0)
        self.assertEqual(self.rows(), first)

    def test_forward_never_after_start_and_never_before_lock(self):
        st = basic_stores()
        before = pack_run.run(st, ["2026-09-20"], replay=False, now=START - timedelta(minutes=61), path=self.path)
        self.assertEqual((before["written"], before["skipped_not_locked"]), (0, 1))
        after = pack_run.run(st, ["2026-09-20"], replay=False, now=START, path=self.path)
        self.assertEqual((after["written"], after["skipped_started"]), (0, 1))
        live = pack_run.run(st, ["2026-09-20"], replay=False, now=START - timedelta(minutes=30), path=self.path)
        self.assertGreater(live["written"], 0)
        rows = self.rows()
        self.assertTrue(all(r["segment"] == "forward" for r in rows))
        self.assertTrue(all(r["lock_utc"] < r["start_utc"] for r in rows))

    def test_replay_only_for_games_that_started(self):
        st = basic_stores()
        c = pack_run.run(st, ["2026-09-20"], replay=True, now=START - timedelta(minutes=30), path=self.path)
        self.assertEqual(c["written"], 0)

    def test_row_shape_and_chain(self):
        st = basic_stores()
        pack_run.run(st, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.path)
        rows = self.rows()
        need = {"kind", "hound_id", "date", "sport", "event_id", "game_pk", "away", "home", "start_utc", "lock_utc",
                "market", "selection", "line", "price_average", "price_best", "book", "book_count",
                "consensus_fair", "reason", "who_decided", "segment", "prev_hash", "row_hash"}
        for r in rows:
            self.assertTrue(need <= set(r), need - set(r))
            self.assertEqual(r["kind"], "hound_bet")
            self.assertEqual(r["game_pk"], "900001")
            self.assertIn(r["market"], ("moneyline", "spread", "total"))
            self.assertIn(r["who_decided"], ("rule", "model", "random"))
        self.assertTrue(pack_run.verify(self.path)[0])
        with open(self.path, encoding="utf-8") as fh:
            lines = fh.readlines()
        bad = json.loads(lines[0])
        bad["price_average"] = 999
        lines[0] = json.dumps(bad, sort_keys=True) + "\n"
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        ok, _, line, _ = pack_run.verify(self.path)
        self.assertFalse(ok)
        self.assertEqual(line, 1)


if __name__ == "__main__":
    unittest.main()
