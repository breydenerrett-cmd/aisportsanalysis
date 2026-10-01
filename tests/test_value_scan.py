"""Tests for scripts/value_scan.py.

The statistics functions take plain lists of entry dicts: no disk, no clock. Two
tests build a tiny ledger in a temp directory and run `main()` end to end; one
asserts the sealed-window guard exits 2.
"""

import contextlib
import hashlib
import io
import json
import math
import os
import tempfile
import unittest

from scripts import value_scan as vs


def entry(**kw):
    """A canonical entry dict (the shape the loaders produce)."""
    base = {
        "rule": "V2 public", "date": "2026-09-23", "kind": "game",
        "market_raw": "moneyline", "market": "moneyline", "entry_class": "pick",
        "price": -150, "result": "WIN", "ledger_units": None,
        "side": "home", "line": None, "p_our": None, "p_mkt": None,
        "observed_utc": None, "first_pitch_utc": None, "game_pk": 1, "game_id": "g1",
        "game_type": "R", "event_id": None, "home_team": None, "away_team": None,
        "player": None, "sport": "mlb", "reason": None, "value_need": None,
        "failed_gates": None, "price_class": "MAIN", "postseason": False,
    }
    base.update(kw)
    return base


class UnitsTest(unittest.TestCase):
    def test_units_negative_price_win_and_loss(self):
        self.assertAlmostEqual(vs.units(-150, "WIN"), 100.0 / 150.0)
        self.assertEqual(vs.units(-150, "LOSS"), -1.0)

    def test_units_positive_price_win_and_loss(self):
        self.assertAlmostEqual(vs.units(150, "WIN"), 1.5)
        self.assertEqual(vs.units(150, "LOSS"), -1.0)

    def test_push_void_unresolved_earn_nothing(self):
        for result in ("PUSH", "VOID", "UNRESOLVED"):
            self.assertEqual(vs.units(-110, result), 0.0)

    def test_roi_and_total_units_use_only_staked_entries(self):
        es = [entry(price=-150, result="WIN"), entry(price=150, result="LOSS"),
              entry(result="VOID"), entry(result="PUSH")]
        self.assertAlmostEqual(vs.total_units(es), 100.0 / 150.0 - 1.0)
        self.assertAlmostEqual(vs.roi(es), (100.0 / 150.0 - 1.0) / 2)
        self.assertIsNone(vs.roi([entry(result="VOID")]))

    def test_breakeven(self):
        self.assertAlmostEqual(vs.breakeven(-150), 0.6)
        self.assertAlmostEqual(vs.breakeven(150), 0.4)
        self.assertIsNone(vs.breakeven(50))


class MarketComparisonTest(unittest.TestCase):
    def test_market_expected_units(self):
        es = [entry(price=-150, p_mkt=0.6, result="WIN"),         # fair: 0
              entry(price=100, p_mkt=0.5, result="LOSS"),         # fair: 0
              entry(price=-110, p_mkt=0.5, result="LOSS")]        # 0.5*(1+100/110) - 1
        exp, n = vs.market_expected_units(es)
        self.assertEqual(n, 3)
        self.assertAlmostEqual(exp, 0.5 * (1.0 + 100.0 / 110.0) - 1.0)

    def test_market_expected_units_skips_entries_without_market_probability(self):
        exp, n = vs.market_expected_units([entry(p_mkt=None)])
        self.assertIsNone(exp)
        self.assertEqual(n, 0)

    def test_z_vs_market(self):
        es = [entry(p_mkt=0.5, result="WIN")] * 3 + [entry(p_mkt=0.5, result="LOSS")]
        z, wins, exp, n = vs.z_vs_market(es)
        self.assertEqual((wins, n), (3, 4))
        self.assertAlmostEqual(exp, 2.0)
        self.assertAlmostEqual(z, (3 - 2.0) / math.sqrt(4 * 0.25))

    def test_z_is_none_without_variance_or_data(self):
        self.assertIsNone(vs.z_vs_market([entry(p_mkt=None)])[0])
        self.assertIsNone(vs.z_vs_market([entry(p_mkt=1.0, result="WIN")])[0])

    def test_paired_brier_difference_and_standard_error(self):
        es = [entry(p_our=0.8, p_mkt=0.6, result="WIN"),
              entry(p_our=0.7, p_mkt=0.5, result="LOSS")]
        b = vs.brier_pair(es)
        self.assertEqual(b["n"], 2)
        self.assertAlmostEqual(b["ours"], (0.04 + 0.49) / 2)
        self.assertAlmostEqual(b["market"], (0.16 + 0.25) / 2)
        diffs = [0.04 - 0.16, 0.49 - 0.25]
        self.assertAlmostEqual(b["diff"], sum(diffs) / 2)
        sd = math.sqrt(sum((d - sum(diffs) / 2) ** 2 for d in diffs) / 1)
        self.assertAlmostEqual(b["se"], sd / math.sqrt(2))

    def test_brier_uses_only_entries_carrying_both_probabilities(self):
        es = [entry(p_our=0.8, p_mkt=0.6), entry(p_our=None, p_mkt=0.6),
              entry(p_our=0.8, p_mkt=None)]
        self.assertEqual(vs.brier_pair(es)["n"], 1)
        self.assertIsNone(vs.brier_pair([entry(p_our=None, p_mkt=0.6)]))


class VerdictTest(unittest.TestCase):
    GOOD = dict(clv_mean=0.5, clv_lo=0.1, z=2.5)

    def test_n_boundaries(self):
        self.assertEqual(vs.verdict(29, **self.GOOD), "TOO FEW")
        self.assertEqual(vs.verdict(30, **self.GOOD), "NO EVIDENCE")
        self.assertEqual(vs.verdict(99, **self.GOOD), "NO EVIDENCE")
        self.assertEqual(vs.verdict(100, **self.GOOD), "CANDIDATE")

    def test_clv_interval_touching_zero_is_not_enough(self):
        self.assertEqual(vs.verdict(100, clv_mean=0.5, clv_lo=0.0, z=2.5), "NO EVIDENCE")
        self.assertEqual(vs.verdict(100, clv_mean=0.5, clv_lo=-0.01, z=2.5), "NO EVIDENCE")
        self.assertEqual(vs.verdict(100, clv_mean=0.5, clv_lo=0.01, z=2.5), "CANDIDATE")

    def test_clv_mean_and_z_thresholds(self):
        self.assertEqual(vs.verdict(100, clv_mean=0.0, clv_lo=0.1, z=2.5), "NO EVIDENCE")
        self.assertEqual(vs.verdict(100, clv_mean=0.5, clv_lo=0.1, z=2.0), "NO EVIDENCE")
        self.assertEqual(vs.verdict(100, clv_mean=0.5, clv_lo=0.1, z=2.01), "CANDIDATE")

    def test_unmeasurable_clv_or_z_can_never_be_a_candidate(self):
        self.assertEqual(vs.verdict(500, clv_mean=None, clv_lo=None, z=9.0), "NO EVIDENCE")
        self.assertEqual(vs.verdict(500, clv_mean=0.5, clv_lo=0.1, z=None), "NO EVIDENCE")

    def test_clv_summary_interval_is_mean_minus_196_se(self):
        ms = [{"clv_bps": 100.0 * x, "beats_close": x > 0} for x in (1.0, 2.0, 3.0, -1.0)]
        es = [entry(clv=m) for m in ms]
        c = vs.clv_summary(es)
        pts = [1.0, 2.0, 3.0, -1.0]
        mu, se = vs.mean_se(pts)
        self.assertEqual(c["n"], 4)
        self.assertAlmostEqual(c["mean"], mu)
        self.assertAlmostEqual(c["lo"], mu - 1.96 * se)
        self.assertAlmostEqual(c["beat"], 0.75)

    def test_clv_refusals_are_named_not_replaced(self):
        es = [entry(kind="prop", clv={"absence": "PROP_NOT_MEASURED"}),
              entry(clv={"absence": "CLOSE_STALE"}),
              entry(clv={"clv_bps": -120.0, "beats_close": False})]
        c = vs.clv_summary(es)
        self.assertEqual(c["n"], 1)
        self.assertEqual(c["refused"], {"CLOSE_STALE": 1, "PROP_NOT_MEASURED": 1})

    def test_summarize_applies_the_rule_to_the_row(self):
        es = [entry(p_mkt=0.5, result="WIN") for _ in range(10)]
        self.assertEqual(vs.summarize(es)["verdict"], "TOO FEW")


class SeparationTest(unittest.TestCase):
    def test_postseason_and_fills_never_enter_a_pick_row(self):
        es = [entry(result="WIN"),
              entry(result="LOSS", entry_class="fill"),
              entry(result="WIN", postseason=True),
              entry(result="WIN", postseason=True, entry_class="fill")]
        groups = vs.group_populations(es)
        self.assertEqual(len(groups), 4)
        pick_row = groups[("V2 public", "moneyline", "pick", "regular")]
        self.assertEqual(len(pick_row), 1)
        s = vs.summarize(pick_row)
        self.assertEqual((s["n_staked"], s["wins"], s["losses"]), (1, 1, 0))
        ps = vs.summarize(groups[("V2 public", "moneyline", "pick", "postseason")])
        self.assertEqual(ps["n_staked"], 1)

    def test_withdrawn_and_void_are_counted_never_staked(self):
        es = [entry(entry_class="withdrawn", result="WIN"),
              entry(entry_class="withdrawn", result="LOSS"),
              entry(result="VOID"), entry(result="UNRESOLVED"), entry(result="PUSH")]
        for e in es:
            self.assertFalse(vs.is_staked(e))
        s = vs.summarize(es)
        self.assertEqual(s["n_staked"], 0)
        self.assertEqual(s["units"], 0.0)
        self.assertEqual(s["withdrawn"], 2)
        self.assertEqual((s["voids"], s["unresolved"], s["pushes"]), (1, 1, 1))

    def test_withdrawn_entries_form_their_own_class(self):
        groups = vs.group_populations([entry(entry_class="withdrawn"), entry()])
        self.assertIn(("V2 public", "moneyline", "withdrawn", "regular"), groups)
        self.assertIn(("V2 public", "moneyline", "pick", "regular"), groups)

    def test_population_with_no_probability_prints_not_recorded(self):
        es = [entry(rule="NFL V1", p_our=None, p_mkt=0.6, result="WIN") for _ in range(3)]
        text = vs.render({"entries": es, "status": {}, "ufc": (0, 0), "clv_error": None,
                          "as_of": None}, now="NOW")
        row = [ln for ln in text.splitlines() if ln.startswith("| R01 | NFL V1")][0]
        self.assertIn("not recorded", row)
        brier = [ln for ln in text.splitlines() if ln.startswith("| R01 |") and "not recorded" in ln]
        self.assertTrue(brier)
        self.assertIsNone(vs.summarize(es)["mean_our"])

    def test_value_gate_comparison(self):
        es = ([entry(p_our=0.62, value_need=0.60, p_mkt=0.55, result="WIN"),
               entry(p_our=0.62, value_need=0.60, p_mkt=0.55, result="LOSS"),
               entry(p_our=0.62, value_need=0.60, p_mkt=0.55, result="LOSS")] +
              [entry(p_our=0.50, value_need=0.60, p_mkt=0.55, result="WIN"),
               entry(p_our=0.50, value_need=0.60, p_mkt=0.55, result="WIN"),
               entry(p_our=0.50, value_need=0.60, p_mkt=0.55, result="LOSS")])
        res = vs.value_gate_comparison(es)
        self.assertEqual((res["passed"]["n"], res["failed"]["n"]), (3, 3))
        self.assertAlmostEqual(res["passed"]["win_minus_mkt"], 1 / 3 - 0.55)
        self.assertAlmostEqual(res["failed"]["win_minus_mkt"], 2 / 3 - 0.55)
        self.assertAlmostEqual(res["diff"], -1 / 3)
        self.assertLess(res["z"], 0)

    def test_value_gate_ignores_entries_without_a_value_mark(self):
        res = vs.value_gate_comparison([entry(p_our=None, value_need=None, p_mkt=0.5)])
        self.assertEqual(res["n"], 0)
        self.assertIsNone(res["diff"])


class SealedWindowTest(unittest.TestCase):
    def test_boundaries(self):
        with self.assertRaises(vs.SealedWindowError):
            vs.check_sealed(["2026-01-01"])
        with self.assertRaises(vs.SealedWindowError):
            vs.check_sealed(["2026-08-27"])
        vs.check_sealed(["2025-12-31", "2026-08-28", "2026-09-10", None])

    def test_postseason_classification_is_mlb_calendar_only(self):
        es = [entry(date="2026-09-27", game_pk=1, game_id="g1"),
              entry(date="2026-09-29", game_pk=2, game_id="g2"),
              entry(rule="NFL V1", sport="nfl", date="2026-10-05", game_pk=None,
                    game_id="2026_05_X_Y")]
        vs.mark_postseason(es)
        self.assertEqual([e["postseason"] for e in es], [False, True, False])


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _v1_rows(date="2026-09-12"):
    pub = {"kind": "card_published", "date": date, "row_hash": "pub1",
           "rule": "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1",
           "picks": [{"game_pk": 11, "game_id": "A-B-1", "market": "moneyline", "price": -150,
                      "side": "home", "market_probability": 0.58, "model_probability": 0.60,
                      "label": "LEAN", "observed_utc": "2026-09-12T15:00:00Z",
                      "first_pitch_utc": "2026-09-12T23:00:00Z"}],
           "prop_picks": [{"game_pk": 11, "player": "P One", "market": "batter_hits",
                           "price": -200, "side": "Under", "line": 1.5,
                           "market_probability": 0.64, "probability": 0.70, "kind": "prop"}],
           "total_picks": []}
    settled = {"kind": "card_settled", "date": date, "published_row_hash": "pub1",
               "picks": [{"game_pk": 11, "game_id": "A-B-1", "market": "moneyline",
                          "price": -150, "result": "WIN", "profit_units": 0.6667}],
               "prop_picks": [{"game_pk": 11, "player": "P One", "market": "batter_hits",
                               "price": -200, "side": "Under", "line": 1.5,
                               "result": "LOSS", "profit_units": -1.0}],
               "total_picks": []}
    return [pub, settled]


def _v2_rows(date="2026-09-23"):
    def g(**kw):
        d = {"kind": "game", "market": "moneyline", "price": -130, "result": "WIN",
             "profit_units": 0.7692, "entry_class": "pick", "price_class": "MAIN",
             "market_probability": 0.55, "our_probability": 0.60, "our_probability_used": 0.562,
             "value_need": 0.57, "failed_gates": [], "withdrawn": False, "game_pk": 21,
             "game_type": "R", "side": "home"}
        d.update(kw)
        return d
    graded = [g(), g(entry_class="fill", failed_gates=["G7_VALUE"], result="LOSS",
                     profit_units=-1.0, game_pk=22),
              g(withdrawn=True, game_pk=23), g(result="VOID", profit_units=0.0, game_pk=24)]
    return [{"kind": "card_published", "date": date, "row_hash": "p2", "rule": "V2"},
            {"kind": "card_settled", "date": date, "rule": "V2", "published_row_hash": "p2",
             "graded": graded}]


class EndToEndTest(unittest.TestCase):
    def _run(self, evidence, out, extra=()):
        argv = ["--evidence-dir", evidence, "--out", out,
                "--multibook", os.path.join(evidence, "no_multibook.jsonl"),
                "--event-map", os.path.join(evidence, "no_event_map.jsonl")] + list(extra)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return vs.main(argv)

    def test_main_end_to_end_is_read_only_deterministic_and_survives_an_unreadable_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "evidence")
            os.makedirs(ev)
            _write_jsonl(os.path.join(ev, "cards_v1.jsonl"), _v1_rows())
            _write_jsonl(os.path.join(ev, "cards_v2.jsonl"), _v2_rows())
            with open(os.path.join(ev, "cards_v2_shadow_a.jsonl"), "w", encoding="utf-8") as fh:
                fh.write("this is not json\n")
            before = {n: _sha(os.path.join(ev, n)) for n in os.listdir(ev)}
            out1, out2 = os.path.join(tmp, "a.md"), os.path.join(tmp, "b.md")
            self.assertEqual(self._run(ev, out1), 0)
            self.assertEqual(self._run(ev, out2), 0)
            after = {n: _sha(os.path.join(ev, n)) for n in os.listdir(ev)}
            self.assertEqual(before, after)          # nothing written to any ledger

            def body(p):
                with open(p, encoding="utf-8") as fh:
                    return [ln for ln in fh.read().splitlines() if not ln.startswith("Generated:")]
            t1, t2 = body(out1), body(out2)
            self.assertEqual(t1, t2)                 # deterministic but for the generated line
            text = "\n".join(t1)
            self.assertIn("unreadable: JSONDecodeError", text)
            row = [ln for ln in t1 if ln.startswith("| R") and "| V1 public | moneyline | pick |" in ln][0]
            self.assertIn("| 1 | 1-0 |", row)
            self.assertIn("+0.67", row)
            v1_hits = [ln for ln in t1 if "| V1 public | hits prop | pick |" in ln][0]
            self.assertIn("| 0-1 |", v1_hits)
            v2_pick = [ln for ln in t1 if ln.startswith("| R") and "| V2 public | moneyline | pick |" in ln][0]
            self.assertIn("| 1-0 |", v2_pick)
            v2_fill = [ln for ln in t1 if ln.startswith("| R") and "| V2 public | moneyline | fill |" in ln][0]
            self.assertIn("| 0-1 |", v2_fill)
            # withdrawn and void: counted, in the never-staked table, not in a staked row
            self.assertTrue(any("| V2 public | moneyline | withdrawn |" in ln for ln in t1))
            self.assertIn("NFL model probability not frozen", text)
            self.assertIn("V2 value gate", text)

    def test_sealed_window_exits_2_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "evidence")
            os.makedirs(ev)
            _write_jsonl(os.path.join(ev, "cards_v1.jsonl"), _v1_rows(date="2026-05-01"))
            out = os.path.join(tmp, "VALUE_SCAN.md")
            self.assertEqual(self._run(ev, out), 2)
            self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
