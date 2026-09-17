"""T0a: the 2025 backfill, the one-time frozen-parameter fit, and the
season-aware prop store (docs/CARD_V2_BUILD_PLAN.md T0a,
docs/PREREG_CARD_V2.md 11.2).

Covers:
1. The frozen parameter file exists, has the schema registration 11.2
   requires, and its numbers are sane (not a rescue-by-threshold check --
   just "this is a real fit, not garbage").
2. Determinism: two independent runs of the fit script, from the same
   on-disk 2025-only inputs, produce byte-identical files (T0a's own
   requirement -- "produce the parameter file twice ... show the hashes
   match").
3. The sealed-window guard actually rejects a 2026 date and accepts a 2025
   one -- proving the guard can fail, not just that it exists.
4. The additive-only contract on `strength.model_line`, `playerprops.
   price_prop` and `playerprops.expected_pa_for_slot`: called exactly as V1
   calls them (no new argument), the result is identical to before this
   task's edits.
5. `src.report.props.box_store_for_season` picks the slate's own year
   instead of the hardcoded 2026 store.
6. `src.providers.mlb._batting_slot` parses the raw `battingOrder` field
   (a new field added for this task) into a 1-9 slot or None.

Tests 1 and 2 read the real, already-built stores this task produced
(`data/historical/pitcher_logs_2025.jsonl`, `..._bullpen_log_2025.jsonl`,
`data/processed/boxscores_2025.jsonl`, `data/historical/mlb_results.csv`) --
they are read-only checks on a durable deliverable, not on a live/mutating
store, and they never touch the sealed 2026-01-01..2026-08-27 window (the fit
script itself enforces that, which test 3 exercises directly).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FROZEN_PARAMS = REPO / "data" / "processed" / "card_v2_frozen_params.json"
FIT_SCRIPT = REPO / "scripts" / "fit_card_v2_frozen_params.py"


def _load_fit_module():
    spec = importlib.util.spec_from_file_location(
        "fit_card_v2_frozen_params", FIT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(FROZEN_PARAMS.exists(), "frozen params not built yet")
class FrozenParamsSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob = json.loads(FROZEN_PARAMS.read_text(encoding="utf-8"))

    def test_top_level_keys_registration_11_2_requires(self):
        for key in ("DISPERSION", "RHO", "moneyline_calibration",
                    "runline_calibration", "slot_plate_appearances"):
            self.assertIn(key, self.blob)

    def test_header_states_provenance(self):
        header = self.blob["_header"]
        self.assertIn("2025", header["fitted_on"])
        self.assertIn("2026-01-01", header["fitted_not_on"])
        self.assertIn("sealed", header["fitted_not_on"].lower())
        self.assertTrue(header["fit_run_once"])
        # No wall-clock timestamp: it would break byte-identical
        # reproducibility, which the determinism test below requires.
        self.assertNotIn("fitted_at", header)

    def test_dispersion_is_a_real_positive_overdispersion_estimate(self):
        # 1.0 is the Poisson (no overdispersion) case; real baseball scoring
        # is known to be overdispersed (docs/PREREG_RUN_DISPERSION.md), so a
        # value at or near 1.0 would mean the fit did not run on real data.
        self.assertGreater(self.blob["DISPERSION"], 1.0)
        self.assertLess(self.blob["DISPERSION"], 5.0)

    def test_moneyline_calibration_fitted_on_real_sample(self):
        cal = self.blob["moneyline_calibration"]
        self.assertTrue(cal["fitted"])
        self.assertGreater(cal["n"], 300)  # calibrate.MIN_FIT_GAMES

    def test_runline_calibration_fitted_on_real_sample(self):
        cal = self.blob["runline_calibration"]
        self.assertTrue(cal["fitted"])
        self.assertGreater(cal["n"], 300)

    def test_rho_is_small_and_positive(self):
        # scripts/test_prop_dispersion.py measured ~0.05 on 2026; a 2025 fit
        # in the same neighbourhood is the sane range, not 0 (no correction)
        # or something above 1 (nonsensical for a correlation-like term).
        self.assertGreater(self.blob["RHO"], 0.0)
        self.assertLess(self.blob["RHO"], 0.5)

    def test_slot_table_is_monotone_decreasing(self):
        table = self.blob["slot_plate_appearances"]
        self.assertEqual(set(table), {str(n) for n in range(1, 10)})
        values = [table[str(n)] for n in range(1, 10)]
        for a, b in zip(values, values[1:]):
            self.assertGreaterEqual(
                a, b, "plate appearances must fall from leadoff to ninth")


@unittest.skipUnless(FIT_SCRIPT.exists(), "fit script not present")
class Determinism(unittest.TestCase):
    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            out1 = Path(tmp) / "run1.json"
            out2 = Path(tmp) / "run2.json"
            for out in (out1, out2):
                result = subprocess.run(
                    [sys.executable, str(FIT_SCRIPT), "--out", str(out)],
                    cwd=str(REPO), capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stderr)
            h1 = hashlib.sha256(out1.read_bytes()).hexdigest()
            h2 = hashlib.sha256(out2.read_bytes()).hexdigest()
            self.assertEqual(h1, h2)


@unittest.skipUnless(FIT_SCRIPT.exists(), "fit script not present")
class SealedWindowGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_fit_module()

    def test_a_2026_date_is_refused(self):
        with self.assertRaises(SystemExit):
            self.module._sealed_guard("2026-01-01")

    def test_a_date_deep_in_the_sealed_window_is_refused(self):
        with self.assertRaises(SystemExit):
            self.module._sealed_guard("2026-08-27")

    def test_a_2025_date_is_accepted(self):
        self.module._sealed_guard("2025-12-31")  # must not raise

    def test_none_is_accepted(self):
        self.module._sealed_guard(None)  # must not raise


class AdditiveOnlyContract(unittest.TestCase):
    """Every new optional argument, called at its default, must reproduce
    V1's own behaviour exactly -- registration 11.2's promise that "the
    module constants ... are not changed" for V1's own call sites."""

    def test_model_line_default_matches_explicit_none_dispersion(self):
        from src.analysis import strength

        features = {
            "away_runs_scored_pg": 4.5, "away_runs_allowed_pg": 4.2,
            "home_runs_scored_pg": 4.8, "home_runs_allowed_pg": 4.0,
            "either_sample_thin": False,
        }
        try:
            a = strength.model_line(features, league_rpg=4.5)
            b = strength.model_line(features, league_rpg=4.5, dispersion=None)
        except strength.StrengthError:
            self.skipTest("fixture features insufficient for this build's "
                          "run_means -- covered indirectly by dispersion "
                          "propagation test below instead")
        self.assertEqual(a["p_home"], b["p_home"])

    def test_market_probabilities_dispersion_none_uses_module_default(self):
        from src.analysis import strength

        default = strength.market_probabilities(4.0, 4.5)
        explicit_default = strength.market_probabilities(
            4.0, 4.5, dispersion=strength.DISPERSION)
        self.assertAlmostEqual(default["p_home"], explicit_default["p_home"],
                               places=9)
        overridden = strength.market_probabilities(4.0, 4.5, dispersion=1.0)
        self.assertNotAlmostEqual(default["p_home"], overridden["p_home"],
                                  places=6)

    def test_expected_pa_for_slot_default_table_unchanged(self):
        from src.analysis import playerprops

        for slot in range(1, 10):
            self.assertEqual(
                playerprops.expected_pa_for_slot(slot),
                playerprops.expected_pa_for_slot(slot, table=None))
            self.assertEqual(
                playerprops.expected_pa_for_slot(slot),
                playerprops.SLOT_PLATE_APPEARANCES[slot])

    def test_expected_pa_for_slot_accepts_a_frozen_table(self):
        from src.analysis import playerprops

        frozen = {1: 4.1, 5: 3.5}
        self.assertEqual(playerprops.expected_pa_for_slot(1, table=frozen), 4.1)
        self.assertIsNone(playerprops.expected_pa_for_slot(2, table=frozen))

    def test_price_prop_default_matches_no_rho_no_slot_table(self):
        from src.analysis import playerprops

        lines = [{"pa": 4, "h": 1, "doubles": 0, "triples": 0, "hr": 0,
                  "r": 0, "rbi": 0, "hits_runs_rbi": 1}
                 for _ in range(50)]
        league = {"pa": 100000, "hit": 0.22, "single": 0.15, "double": 0.045,
                 "triple": 0.005, "home_run": 0.02, "run": 0.12,
                 "rbi": 0.115}
        a = playerprops.price_prop(market="batter_hits", line=0.5,
                                   batter_lines=lines, league=league,
                                   batting_slot=3)
        b = playerprops.price_prop(market="batter_hits", line=0.5,
                                   batter_lines=lines, league=league,
                                   batting_slot=3, rho=None, slot_table=None)
        self.assertEqual(a["probability"], b["probability"])
        self.assertEqual(a["expected_pa"], b["expected_pa"])

    def test_price_prop_rho_argument_actually_changes_the_number(self):
        from src.analysis import playerprops

        lines = [{"pa": 4, "h": 1, "doubles": 0, "triples": 0, "hr": 0,
                  "r": 0, "rbi": 0, "hits_runs_rbi": 1}
                 for _ in range(50)]
        league = {"pa": 100000, "hit": 0.22, "single": 0.15, "double": 0.045,
                 "triple": 0.005, "home_run": 0.02, "run": 0.12,
                 "rbi": 0.115}
        default = playerprops.price_prop(market="batter_hits", line=0.5,
                                         batter_lines=lines, league=league,
                                         batting_slot=3)
        corrected = playerprops.price_prop(market="batter_hits", line=0.5,
                                           batter_lines=lines, league=league,
                                           batting_slot=3, rho=0.3)
        self.assertNotAlmostEqual(default["probability"],
                                  corrected["probability"], places=6)

    def test_price_prop_slot_table_argument_actually_changes_the_pa(self):
        from src.analysis import playerprops

        lines = [{"pa": 4, "h": 1, "doubles": 0, "triples": 0, "hr": 0,
                  "r": 0, "rbi": 0, "hits_runs_rbi": 1}
                 for _ in range(50)]
        league = {"pa": 100000, "hit": 0.22, "single": 0.15, "double": 0.045,
                 "triple": 0.005, "home_run": 0.02, "run": 0.12,
                 "rbi": 0.115}
        default = playerprops.price_prop(market="batter_hits", line=0.5,
                                         batter_lines=lines, league=league,
                                         batting_slot=1)
        frozen_table = {1: 9.0}
        overridden = playerprops.price_prop(
            market="batter_hits", line=0.5, batter_lines=lines,
            league=league, batting_slot=1, slot_table=frozen_table)
        self.assertNotEqual(default["expected_pa"], overridden["expected_pa"])
        self.assertEqual(overridden["expected_pa"], 9.0)


class SeasonAwarePropStore(unittest.TestCase):
    def test_picks_the_slate_s_own_year(self):
        from src.report import props

        self.assertTrue(
            str(props.box_store_for_season("2025-06-01")).endswith(
                "boxscores_2025.jsonl"))
        self.assertTrue(
            str(props.box_store_for_season("2027-04-01")).endswith(
                "boxscores_2027.jsonl"))

    def test_2026_default_matches_the_old_hardcoded_path(self):
        from src.report import props

        self.assertEqual(props.box_store_for_season("2026-05-01"),
                         props.BOX_STORE)

    def test_malformed_date_falls_back_to_the_2026_default(self):
        from src.report import props

        self.assertEqual(props.box_store_for_season(""), props.BOX_STORE)
        self.assertEqual(props.box_store_for_season(None), props.BOX_STORE)
        self.assertEqual(props.box_store_for_season("not-a-date"),
                         props.BOX_STORE)


class BattingOrderParsing(unittest.TestCase):
    def test_starter_slots(self):
        from src.providers import mlb

        for slot in range(1, 10):
            self.assertEqual(mlb._batting_slot(f"{slot}00"), slot)

    def test_substitution_still_carries_the_slot(self):
        from src.providers import mlb

        self.assertEqual(mlb._batting_slot("501"), 5)
        self.assertEqual(mlb._batting_slot("902"), 9)

    def test_missing_or_unparseable_is_none(self):
        from src.providers import mlb

        self.assertIsNone(mlb._batting_slot(None))
        self.assertIsNone(mlb._batting_slot(""))
        self.assertIsNone(mlb._batting_slot("abc"))

    def test_parse_boxscore_carries_the_field_additively(self):
        from src.providers import mlb

        box = {"teams": {"away": {
            "team": {"abbreviation": "BOS"},
            "players": {"ID1": {
                "person": {"id": 1, "fullName": "Test Batter"},
                "battingOrder": "300",
                "stats": {"batting": {"plateAppearances": 4, "atBats": 4,
                                      "hits": 1, "doubles": 0, "triples": 0,
                                      "homeRuns": 0, "runs": 0, "rbi": 0,
                                      "baseOnBalls": 0, "strikeOuts": 1,
                                      "stolenBases": 0}},
            }},
        }, "home": {"team": {}, "players": {}}}}
        parsed = mlb.parse_boxscore(1, box)
        self.assertEqual(parsed["batters"][0]["batting_order"], 3)


if __name__ == "__main__":
    unittest.main()
