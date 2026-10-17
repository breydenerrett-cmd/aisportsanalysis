"""INFO_TIMING_V1 harness tests, synthetic rows only (docs/PREREG_INFO_TIMING.md).

Pinned: the sealed window refuses and sealed raw lines are discarded BEFORE
parsing; no price at or after first pitch is used; the entry capture is
strictly after the information time and the close strictly after the entry;
lineup history is strictly before the game date; the registered decision rule.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.model.discovery import clustered_bootstrap
from src.research import info_timing as it

T0 = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
FP = T0 + timedelta(hours=3)


def at(minutes):
    return (T0 + timedelta(minutes=minutes)).isoformat()


def board(over, under, books=3):
    return {f"b{i}": {"Over": over, "Under": under} for i in range(books)}


class SealAndReaders(unittest.TestCase):

    def test_sealed_and_2025_dates_raise(self):
        for d in ("2026-01-01", "2026-05-05", "2026-08-27", "2025-07-01"):
            with self.assertRaises(it.SealedDataError):
                it.assert_allowed_date(d)
        self.assertEqual(it.assert_allowed_date("2026-09-08"), "2026-09-08")
        self.assertEqual(it.assert_allowed_date("2026-08-28"), "2026-08-28")

    def test_regulars_refuses_sealed_game_date(self):
        with self.assertRaises(it.SealedDataError):
            it.regulars([], "NYY", "2026-07-01")

    def _tmp(self, text, suffix=".jsonl"):
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_props_reader_discards_sealed_line_before_parsing(self):
        good = {"game_date": "2026-09-20", "event_id": "E", "market": "batter_hits",
                "line": 0.5, "side": "Over", "price": -150, "player": "A B",
                "book": "x", "observed_utc": at(0)}
        text = ('{"game_date": "2026-05-01", THIS IS NOT JSON\n'
                '{"game_date": "2025-09-20", NOR THIS\n' + json.dumps(good) + "\n")
        out = it.read_props(self._tmp(text), {"E"})
        self.assertEqual(list(out["E"]), [("A B", "batter_hits", 0.5)])

    def test_results_reader_discards_sealed_line_and_keeps_no_scores(self):
        header = ("game_pk,date,start_time_utc,venue,game_type,away_team,home_team,"
                  "away_team_id,home_team_id,away_probable,home_probable,away_probable_id,"
                  "home_probable_id,away_score,home_score,winner,home_won,total_runs,"
                  "run_differential,double_header,game_number\n")
        sealed = '1,2026-06-01,"BROKEN\n'
        good = ("2,2026-09-20,2026-09-20T21:00:00Z,V,R,NYY,BOS,1,2,p,q,3,4,"
                "5,6,BOS,1,11,1,N,1\n")
        out = it.read_results(self._tmp(header + sealed + good, ".csv"))
        self.assertEqual(set(out), {2})
        self.assertEqual(set(out[2]), {"date", "start", "game_type", "away", "home",
                                       "double_header"})

    def test_game_line_reader_discards_sealed_line(self):
        good = {"observed_utc": at(0), "event_id": "E", "book": "x",
                "home_price": -120, "away_price": 110, "away_team": "A", "home_team": "H"}
        text = '{"observed_utc": "2026-08-01T00:00:00Z", BROKEN\n' + json.dumps(good) + "\n"
        out, teams = it.read_game_lines([self._tmp(text)], {"E"})
        self.assertEqual(list(out["E"]["moneyline"]), [at(0)])

    def test_lineup_history_discards_sealed_line(self):
        good = {"date": "2026-09-01", "game_pk": 7,
                "away": [{"person_id": 1, "name": "A"}], "home": []}
        text = '{"date": "2026-04-01", BROKEN\n' + json.dumps(good) + "\n"
        hist, names = it.read_lineup_history(self._tmp(text), {7: {"away": "NYY", "home": "BOS"}})
        self.assertEqual(hist, [{"date": "2026-09-01", "game_pk": 7, "team": "NYY", "ids": [1]}])
        self.assertEqual(names, {1: "A"})


class Consensus(unittest.TestCase):

    def test_devig_and_average(self):
        c = it.consensus(board(-150, 120, books=2), "Over", min_books=2)
        raw_o, raw_u = 150 / 250, 100 / 220
        self.assertAlmostEqual(c["fair"], raw_o / (raw_o + raw_u))
        self.assertAlmostEqual(c["avg_raw"], raw_o)
        self.assertEqual(c["n_books"], 2)

    def test_min_books_and_one_sided_books(self):
        b = {"x": {"Over": -110, "Under": -110}, "y": {"Over": -110}}
        self.assertIsNone(it.consensus(b, "Over", min_books=2))
        self.assertIsNotNone(it.consensus(b, "Over", min_books=1))

    def test_booksum_floor(self):
        b = {"x": {"Over": 150, "Under": 150}, "y": {"Over": -110, "Under": -110}}
        c = it.consensus(b, "Over", min_books=1, min_booksum=0.98)
        self.assertEqual(c["n_books"], 1)


class PointInTime(unittest.TestCase):

    def _series(self, extra=None):
        inst = {at(-30): board(-110, -110), at(10): board(-120, 100),
                at(60): board(-130, 110), at(170): board(-140, 120)}
        inst.update(extra or {})
        return it.build_series(inst, FP)

    def test_entry_strictly_after_info_and_close_before_pitch(self):
        series = self._series({at(0): board(-200, 170)})
        r = it.measure(series, "Over", t_info=T0, t_pre=T0 - timedelta(minutes=5),
                       first_pitch=FP, min_books=2)
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["entry_utc"], at(10))   # the capture AT t_info is not the entry
        self.assertEqual(r["close_utc"], at(170))
        self.assertGreater(it.parse_t(r["entry_utc"]), T0)
        self.assertLess(it.parse_t(r["close_utc"]), FP)

    def test_prices_at_or_after_first_pitch_change_nothing(self):
        base = it.measure(self._series(), "Over", t_info=T0, t_pre=None,
                          first_pitch=FP, min_books=2)
        late = self._series({at(180): board(-900, 600), at(200): board(-900, 600)})
        moved = it.measure(late, "Over", t_info=T0, t_pre=None, first_pitch=FP, min_books=2)
        self.assertEqual(base, moved)
        self.assertTrue(all(t < FP for t, _ in late))

    def test_pre_capture_is_at_or_before_bracket_start(self):
        r = it.measure(self._series(), "Over", t_info=T0, t_pre=T0 - timedelta(minutes=40),
                       first_pitch=FP, min_books=2)
        self.assertIsNone(r["pre_move"])  # the -30 capture is after the bracket start
        r = it.measure(self._series(), "Over", t_info=T0, t_pre=T0 - timedelta(minutes=30),
                       first_pitch=FP, min_books=2)
        self.assertIsNotNone(r["pre_move"])

    def test_values(self):
        r = it.measure(self._series(), "Over", t_info=T0, t_pre=None, first_pitch=FP,
                       min_books=2)
        e = it.consensus(board(-120, 100), "Over", min_books=2)
        k = it.consensus(board(-140, 120), "Over", min_books=2)
        self.assertAlmostEqual(r["m1"], 100 * (k["fair"] - e["fair"]))
        self.assertAlmostEqual(r["m2"], 100 * (k["fair"] - e["avg_raw"]))
        self.assertAlmostEqual(r["m2_best"], 100 * (k["fair"] - e["best_raw"]))
        self.assertGreater(r["m1"], 0)
        self.assertLess(r["m2"], r["m1"])  # the vig is paid
        self.assertAlmostEqual(r["lag_min"], 10.0)

    def test_no_entry_and_no_later_capture(self):
        s = it.build_series({at(-30): board(-110, -110)}, FP)
        self.assertEqual(it.measure(s, "Over", t_info=T0, t_pre=None, first_pitch=FP,
                                    min_books=2)["status"], "NO_ENTRY_CAPTURE")
        s = it.build_series({at(-30): board(-110, -110), at(20): board(-110, -110)}, FP)
        self.assertEqual(it.measure(s, "Over", t_info=T0, t_pre=None, first_pitch=FP,
                                    min_books=2)["status"], "NO_LATER_CAPTURE")

    def test_invalid_capture_is_skipped_for_entry(self):
        inst = {at(5): board(-120, 100, books=1), at(15): board(-120, 100),
                at(90): board(-125, 105)}
        r = it.measure(it.build_series(inst, FP), "Over", t_info=T0, t_pre=None,
                       first_pitch=FP, min_books=2)
        self.assertEqual(r["entry_utc"], at(15))

    def test_pick_line_most_books_then_preference(self):
        series = [(T0 - timedelta(minutes=1), {8.5: board(-110, -110, 9)}),
                  (T0 + timedelta(minutes=5), {8.0: board(-110, -110, 6),
                                               8.5: board(-110, -110, 6),
                                               9.0: board(-110, -110, 2)})]
        line = it.pick_line(series, "Under", lambda bl: sorted(bl), t_info=T0,
                            min_books=6, prefer=lambda L: L)
        self.assertEqual(line, 8.0)


class Regulars(unittest.TestCase):

    def _hist(self, n, start_day=1):
        rows = []
        for i in range(n):
            ids = [1, 2, 3, 4, 5, 6, 7, 8, 9] if i % 2 else [1, 2, 3, 4, 5, 6, 7, 8, 10]
            rows.append({"date": f"2026-09-{start_day + i:02d}", "game_pk": 100 + i,
                         "team": "NYY", "ids": ids})
        return rows

    def test_needs_ten_prior_games_and_seven_starts(self):
        self.assertIsNone(it.regulars(self._hist(9), "NYY", "2026-09-20"))
        reg = it.regulars(self._hist(10), "NYY", "2026-09-20")
        self.assertEqual(reg, {1, 2, 3, 4, 5, 6, 7, 8})  # 9 and 10 have 5 starts each

    def test_strictly_before_the_game_date(self):
        hist = self._hist(12)  # dates 09-01..09-12
        a = it.regulars(hist, "NYY", "2026-09-11")
        mutated = [dict(h, ids=[99] * 9) if h["date"] >= "2026-09-11" else h for h in hist]
        self.assertEqual(a, it.regulars(mutated, "NYY", "2026-09-11"))
        self.assertIsNone(it.regulars(hist, "NYY", "2026-09-10"))  # only 9 earlier games

    def test_history_before_august_28_is_ignored(self):
        hist = [dict(h, date=h["date"].replace("2026-09", "2026-08")) for h in self._hist(10, 18)]
        self.assertIsNone(it.regulars(hist, "NYY", "2026-09-01"))


class Names(unittest.TestCase):

    def test_normalisation(self):
        self.assertEqual(it.norm_name("Ronald Acuña Jr."), "ronald acuna")
        self.assertEqual(it.norm_name("J.P. Crawford"), "j p crawford")
        self.assertEqual(it.norm_name("Michael Harris II"), "michael harris")

    def test_match_posted_and_ambiguity(self):
        names = {1: "Ronald Acuña Jr.", 2: "Will Smith", 3: "Will Smith", 4: "Nobody Quoted"}
        matched, refused = it.match_posted([1, 2, 3, 4], names,
                                           ["Ronald Acuna Jr", "Will Smith"])
        self.assertEqual(matched, {1: "Ronald Acuna Jr"})
        self.assertEqual(refused, {2: "AMBIGUOUS_NAME", 3: "AMBIGUOUS_NAME",
                                   4: "NO_PROP_QUOTED"})

    def test_left_out(self):
        idx = it.name_index({1: "A One", 2: "B Two", 3: "C Three", 4: "C Three"})
        out = it.left_out(["A One", "B Two", "C Three", "Z Unknown"], [1], idx)
        self.assertEqual(out, {"A One": "POSTED", "B Two": "R2",
                               "C Three": "AMBIGUOUS_NAME", "Z Unknown": "NAME_UNMATCHED"})


class Decision(unittest.TestCase):

    def _rows(self, vals, dates):
        return [{"date": f"2026-09-{8 + (i % dates):02d}", "event_key": str(i), "v": v}
                for i, v in enumerate(vals)]

    def test_summary_interval_is_the_discovery_bootstrap(self):
        rows = self._rows([0.5, -0.2, 1.0, 0.3, 0.1, -0.4, 0.9, 0.2], 4)
        s = it.summarize(rows, "v")
        ci = clustered_bootstrap(rows, lambda r: sum(x["v"] for x in r) / len(r),
                                 resamples=it.RESAMPLES, seed=it.SEED)
        self.assertEqual((s["low"], s["high"]), (ci["low"], ci["high"]))
        self.assertEqual(s["n_dates"], 4)
        self.assertAlmostEqual(s["mde"], 2.8 * s["se"])

    def test_rule(self):
        m = lambda n, nd, mean, low, high: {"n": n, "n_dates": nd, "mean": mean,
                                            "low": low, "high": high}
        self.assertEqual(it.decide(m(40, 6, 0.3, 0.1, 0.5), m(40, 6, 0.5, 0.1, 0.9)),
                         it.VERDICT_SUPPORTED)
        self.assertEqual(it.decide(m(40, 6, -0.1, -0.3, 0.1), m(40, 6, 0.5, 0.1, 0.9)),
                         it.VERDICT_NOT_SUPPORTED)  # M1 sign disagrees
        self.assertEqual(it.decide(m(40, 6, 0.3, 0.1, 0.5), m(40, 6, 0.2, 0.0, 0.4)),
                         it.VERDICT_NOT_SUPPORTED)  # interval touches zero
        self.assertEqual(it.decide(m(29, 6, 0.3, 0.1, 0.5), m(29, 6, 0.5, 0.1, 0.9)),
                         it.VERDICT_NOT_MEASURABLE)
        self.assertEqual(it.decide(m(40, 4, 0.3, 0.1, 0.5), m(40, 4, 0.5, 0.1, 0.9)),
                         it.VERDICT_NOT_MEASURABLE)
        self.assertEqual(it.REGISTRY_RESULT[it.VERDICT_NOT_MEASURABLE], "below_floor")

    def test_coverage(self):
        cov = it.lag_coverage([5, 45, 100, 200, None], 5)
        self.assertEqual((cov["within_30"], cov["within_60"], cov["within_120"]), (1, 2, 3))
        self.assertEqual(cov["none_before_pitch"], 1)


if __name__ == "__main__":
    unittest.main()
