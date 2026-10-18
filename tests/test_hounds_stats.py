"""Hound numbers against a small synthetic world (tests/_hounds_fixtures.py).

No live ledger is read for a numeric assertion here. The expected values are
worked by hand in the comments so a failure says which arithmetic moved.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.hounds import boards, stats, verdict as vd
from tests import _hounds_fixtures as F


def implied(price):
    return 100 / (100 + price) if price > 0 else -price / (-price + 100)


class FixtureBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.src = F.make_world(cls.root)
        stats.clear_cache()
        cls.book = stats.build(cls.src)

    @classmethod
    def tearDownClass(cls):
        stats.clear_cache()
        cls._tmp.cleanup()

    def h(self, hid):
        return self.book.hounds[hid]

    def bet(self, hid, game_fragment, segment="forward"):
        rows = [b for b in self.h(hid).bets
                if game_fragment in b.game and b.segment == segment]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]


class RecordAndUnits(FixtureBase):
    def test_alpha_record_counts_forward_graded_only(self):
        s = self.h("alpha").summary
        # E1 win, E2 loss, E4 push forward; E3 is ungraded; E5 is a replay loss.
        self.assertEqual((s.record.bets, s.record.wins, s.record.losses,
                          s.record.pushes, s.record.voids), (3, 1, 1, 1, 0))

    def test_units_at_recorded_price(self):
        # win at -118 = +100/118 = 0.8475, loss -1, push 0.
        self.assertAlmostEqual(self.h("alpha").summary.record.units_recorded_price,
                               0.8475 - 1.0, places=4)

    def test_units_at_average_price(self):
        # E1 board mean decimal: (1.8333+1.8+1.7692+1.8475+1.8197+1.7937)/6
        # = 1.8106 -> American -123 -> win pays 100/123 = 0.8130; loss -1; push 0.
        s = self.h("alpha").summary
        self.assertAlmostEqual(s.record.units_average_price, 0.8130 - 1.0, places=3)

    def test_average_price_null_when_board_missing(self):
        # delta's only game (E8) is not in the captured odds at all.
        self.assertIsNone(self.h("delta").summary.record.units_average_price)

    def test_void_counts_as_a_bet_with_zero_units(self):
        s = self.h("bravo").summary
        self.assertEqual((s.record.bets, s.record.voids, s.record.units_recorded_price),
                         (1, 1, 0.0))

    def test_replay_is_separate_and_not_in_the_forward_record(self):
        s = self.h("alpha").summary
        self.assertIsNotNone(s.replay)
        self.assertEqual((s.replay.bets, s.replay.losses), (1, 1))
        self.assertEqual(s.replay.units_recorded_price, -1.0)
        row = self.bet("alpha", "E5", segment="replay")
        self.assertEqual(row.segment, "replay")


class ClvAgainstTheClose(FixtureBase):
    def test_h2h_clv_points_worked_by_hand(self):
        # E1 close: home -135 / away +115 at all six books.
        # raw home 135/235 = 0.574468, raw away 100/215 = 0.465116, sum 1.039584
        # fair home = 0.552588; implied(-118) = 0.541284 -> +1.130 points.
        row = self.bet("alpha", "E1")
        self.assertAlmostEqual(row.clv_pts, 100 * (0.574468 / 1.039584 - implied(-118)), places=2)

    def test_totals_clv_points_worked_by_hand(self):
        # E4 close: over +100 / under -120. raw under 0.545455, raw over 0.5,
        # fair under = 0.521739; implied(-110) = 0.523810 -> -0.207 points.
        row = self.bet("alpha", "E4")
        self.assertAlmostEqual(row.clv_pts, 100 * (0.545455 / 1.045455 - implied(-110)), places=2)

    def test_summary_clv_is_the_mean_of_graded_forward_measurable_bets(self):
        c = self.h("alpha").summary.clv
        self.assertEqual(c.n, 3)         # E1, E2, E4 (E3 ungraded, E5 replay)
        expect = [self.bet("alpha", g).clv_pts for g in ("E1", "E2", "E4")]
        self.assertAlmostEqual(c.mean_pts, sum(expect) / 3, places=3)
        self.assertIsNone(c.ci_low)      # n=3: no interval, TOO EARLY
        self.assertEqual(self.h("alpha").summary.verdict.label, vd.TOO_EARLY)

    def test_replay_decision_is_never_measurable(self):
        self.assertIsNone(self.bet("alpha", "E5", segment="replay").clv_pts)
        self.assertNotIn(("2026-10-02", None), self.h("alpha").clv_points)

    def test_pack_bets_get_clv_through_the_same_code(self):
        # charlie E6: home +112 vs close home +120 / away -140.
        # raw home 100/220 = 0.454545, raw away 140/240 = 0.583333, sum 1.037879
        # fair home = 0.437956; implied(112) = 0.471698 -> -3.374 points.
        row = self.bet("charlie", "E6")
        self.assertAlmostEqual(row.clv_pts, 100 * (0.454545 / 1.037879 - implied(112)), places=2)


class VerificationAndWho(FixtureBase):
    def test_price_found_on_the_board_is_verified_and_wrong_price_is_not(self):
        self.assertTrue(self.bet("alpha", "E1").verified)       # -118 at bk4 on T0
        self.assertFalse(self.bet("alpha", "E2").verified)      # +112 vs best +110
        self.assertTrue(self.bet("alpha", "E4").verified)       # -110 at bk2

    def test_hound_verified_needs_95_percent_of_checkable(self):
        s = self.h("alpha").summary
        self.assertEqual(s.checkable_share, 1.0)
        self.assertEqual(s.verified_share, 0.5)
        self.assertFalse(s.verified)

    def test_a_hound_with_no_checkable_board_is_not_verified(self):
        self.assertFalse(self.h("delta").summary.verified)
        self.assertIsNone(self.h("delta").summary.verified_share)

    def test_who_decided_from_provenance(self):
        self.assertEqual(self.bet("alpha", "E1").who_decided, "rule")      # placeholder
        self.assertEqual(self.bet("bravo", "E1").who_decided, "model")     # model_derived

    def test_refusals_are_in_the_stream_marked_and_decided_by_code(self):
        refused = [i for i in self.book.stream if i.refused]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0].verdict, "refused_thin")
        self.assertEqual(refused[0].who_decided, "code")
        self.assertEqual(refused[0].hound_id, "alpha")
        self.assertIn("Refused", refused[0].reason)

    def test_stream_is_newest_first_and_forward_only(self):
        stamps = [i.decided_utc for i in self.book.stream]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertTrue(all(i.segment == "forward" for i in self.book.stream))


class SeriesAndSpark(FixtureBase):
    def test_series_starts_at_zero_the_day_before_the_first_bet(self):
        series = self.h("alpha").series
        self.assertEqual((series[0].date, series[0].cum_units_recorded_price,
                          series[0].cum_units_average_price, series[0].bets_settled),
                         ("2026-09-30", 0.0, 0.0, 0))
        self.assertEqual(series[1].date, "2026-10-01")
        self.assertEqual(series[1].bets_settled, 3)
        self.assertAlmostEqual(series[1].cum_units_recorded_price, -0.1525, places=4)
        self.assertAlmostEqual(series[1].cum_units_average_price, 0.8130 - 1.0, places=3)

    def test_cum_clv_is_null_below_20_bets(self):
        self.assertTrue(all(p.cum_clv_mean_pts is None for p in self.h("alpha").series))

    def test_average_series_is_null_when_unavailable_but_recorded_is_not(self):
        for p in self.h("delta").series:
            self.assertIsNone(p.cum_units_average_price)
        self.assertAlmostEqual(self.h("delta").series[-1].cum_units_recorded_price, 0.9524)

    def test_one_point_per_day_with_graded_bets_plus_the_zero(self):
        self.assertEqual(len(self.h("alpha").series), 2)     # replay day excluded

    def test_spark_is_last_30_cumulative_average_points(self):
        spark = self.h("alpha").summary.spark
        self.assertEqual(spark, [0.0, round(0.8130 - 1.0, 3)])


class PackAndUserLedgers(FixtureBase):
    def test_pack_hound_definition_and_bets(self):
        s = self.h("charlie").summary
        self.assertEqual((s.name, s.category, s.kind), ("Charlie", "math", "house"))
        self.assertEqual(s.record.wins, 1)
        # settled from the recorded (best) price 112 -> +1.12; average price 110 -> 1.10
        self.assertAlmostEqual(s.record.units_recorded_price, 1.12)
        self.assertAlmostEqual(s.record.units_average_price, 1.10)

    def test_pack_replay_row_is_segregated(self):
        s = self.h("charlie").summary
        self.assertEqual(s.record.bets, 1)
        self.assertEqual((s.replay.bets, s.replay.losses), (1, 1))

    def test_user_hound_comes_from_the_user_ledger(self):
        s = self.h("u-1").summary
        self.assertEqual((s.kind, s.owner_display, s.name), ("user", "pat", "Rover"))
        self.assertEqual(s.record.losses, 1)
        # a user hound is never retired by the house rule
        self.assertIsNone(s.retired)

    def test_market_alias_and_side_text(self):
        row = self.bet("u-1", "E1")
        self.assertEqual(row.market, "h2h")
        self.assertEqual(row.selection, "Away E1 moneyline")


class StatusKindsAndOrder(FixtureBase):
    def test_as_of_is_the_newest_forward_decision_day(self):
        self.assertEqual(self.book.as_of, "2026-10-02")

    def test_status(self):
        self.assertEqual(self.h("alpha").summary.status, "running")
        self.assertEqual(self.h("delta").summary.status, "benched")   # 2026-09-20

    def test_baseline_never_leads_the_board(self):
        ids = [s.id for s in stats.leaderboard(self.book)]
        self.assertEqual(ids[-1], "bravo")
        self.assertEqual(self.h("bravo").summary.kind, "baseline")
        self.assertEqual(self.h("bravo").summary.category, "baseline")

    def test_graveyard_empty_when_nobody_is_retired(self):
        self.assertEqual(stats.graveyard(self.book), [])


class ReadOnlyAndSealed(unittest.TestCase):
    def test_build_changes_no_input_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            before = src.fingerprint()
            stats.build(src)
            self.assertEqual(src.fingerprint(), before)

    def test_sealed_window_rows_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            path = Path(tmp) / "data/paper_accounts/sys_a.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(F.account("sealed1", "sys_a", "2026-08-01", "win",
                                              5.0, "h2h", "home", None, 400)) + "\n")
            with (Path(tmp) / "evidence/paper_wagers_v2.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(F.wager("sealed1", "sys_a", "E1", "h2h", "home",
                                            None, 400, date="2026-08-01")) + "\n")
            book = stats.build(src)
            self.assertEqual(book.hounds["alpha"].summary.record.bets, 3)


class RetirementInTheBook(unittest.TestCase):
    def test_down_more_than_25_units_retires_with_the_day_and_cause(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            wagers, accounts = [], []
            for i in range(26):
                day = f"2026-09-{1 + i:02d}"
                wagers.append(F.wager(f"L{i}", "sys_d", f"X{i}", "h2h", "home", None,
                                      -110, utc=f"{day}T15:00:00+00:00", date=day))
                accounts.append(F.account(f"L{i}", "sys_d", day, "loss", -1.0,
                                          "h2h", "home", None, -110))
            with (Path(tmp) / "evidence/paper_wagers_v2.jsonl").open("a", encoding="utf-8") as fh:
                for w in wagers:
                    fh.write(json.dumps(w) + "\n")
            with (Path(tmp) / "data/paper_accounts/sys_d.jsonl").open("a", encoding="utf-8") as fh:
                for a in accounts:
                    fh.write(json.dumps(a) + "\n")
            book = stats.build(src)
            s = book.hounds["delta"].summary
            # 26 losses on 09-01..09-26, plus the fixture's +0.9524 win on 09-20:
            # the running total first drops below -25 on the 26th day.
            self.assertEqual(s.status, "retired")
            self.assertEqual(s.retired.cause, vd.CAUSE_UNITS)
            self.assertEqual(s.retired.date, "2026-09-26")
            self.assertEqual([x.id for x in stats.graveyard(book)], ["delta"])
            self.assertNotIn("delta", [x.id for x in stats.leaderboard(book)])


class OldDogStaticRetirement(unittest.TestCase):
    def test_configured_static_retirement_and_not_measured_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            cfg = json.loads(src.house_hounds_cfg.read_text(encoding="utf-8"))
            cfg["hounds"].append({
                "id": "old-dog", "name": "The Old Dog", "kind": "house", "card": True,
                "category": "stats", "rule_text": "r",
                "retired": {"date": "2026-10-16", "cause": "paused 2026-10-16: x"},
                "verdict_sentence": "Not re-measured."})
            src.house_hounds_cfg.write_text(json.dumps(cfg), encoding="utf-8")
            book = stats.build(src)
            s = book.hounds["old-dog"].summary
            self.assertEqual((s.status, s.retired.cause), ("retired", "paused 2026-10-16: x"))
            self.assertEqual(s.verdict.label, vd.NOT_MEASURED)
            self.assertFalse(s.verified)
            self.assertIsNone(s.clv)


class Caching(unittest.TestCase):
    def test_second_call_returns_the_same_book_without_rescanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            stats.clear_cache()
            with mock.patch.object(boards, "scan", wraps=boards.scan) as scan:
                first = stats.get_book(src)
                second = stats.get_book(src)
                self.assertIs(first, second)
                self.assertEqual(scan.call_count, 1)

    def test_a_changed_file_invalidates_the_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            stats.clear_cache()
            first = stats.get_book(src)
            with src.wagers.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(F.wager("w9", "sys_a", "E3", "h2h", "home", None, -110,
                                            date="2026-10-03")) + "\n")
            second = stats.get_book(src)
            self.assertIsNot(first, second)
            self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_an_mtime_only_change_invalidates_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = F.make_world(Path(tmp))
            stats.clear_cache()
            first = stats.get_book(src)
            st = os.stat(src.house_hounds_cfg)
            os.utime(src.house_hounds_cfg, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
            self.assertIsNot(first, stats.get_book(src))

    def tearDown(self):
        stats.clear_cache()


class BoardHelpers(unittest.TestCase):
    def test_american_mean_is_the_mean_decimal_price(self):
        self.assertEqual(boards.american_mean([100, 100]), 100)
        self.assertEqual(boards.american_mean([-110, -110, -110]), -110)
        self.assertEqual(boards.american_mean([]), None)

    def test_an_invalid_store_price_is_ignored_not_fatal(self):
        side = boards.clv.MARKET_SHAPES["h2h"].sides["home"]
        self.assertIsNone(boards._side_price(side, {"home_price": 98}, None))
        self.assertEqual(boards._side_price(side, {"home_price": -110}, None), -110)


if __name__ == "__main__":
    unittest.main()
