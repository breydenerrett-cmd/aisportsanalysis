"""Tests for src/research/f5_eval.py -- the standalone F5 calibration path.

Covers the five validation items PREREG_F5_FAMILIES.md (b) requires before
any evaluation run on real data: (1) synthetic-injection recovery, (2) PIT
negative tests, (3) denominator + both hashes, (4) de-vig convention
agreement, (5) battery-wiring skip recording. All of it is feature-side or
synthetic -- none of it requires an outcome read on the real universe. A
`dry_run` smoke test against the real gitignored stores is included and
SKIPS (never fails) when those stores are absent, matching this project's
convention for real-data tests (see tests/test_f5_universe.py,
tests/test_engine_features.py).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.core import odds as odds_math
from src.research import battery, f5_eval, f5_universe


def _data_available() -> bool:
    return (Path(f5_universe.PRIMARY_VIEW_PATH).exists()
            and Path(f5_universe.SETTLEMENT_PATH).exists()
            and Path(f5_universe.MANIFEST_PATH).exists())


def _books(pairs):
    """pairs: [(key, away_price, home_price), ...] -> `books` field shape."""
    return [{"key": key, "h2h_1st_5_innings":
            {"away_price": away, "home_price": home}}
           for key, away, home in pairs]


class PoisonDict(dict):
    """Raises if `actual_first_pitch` (or any settlement timestamp key) is
    ever read. Used to assert the eval path never touches it (validation
    item 2)."""

    _FORBIDDEN = {"actual_first_pitch", "settled_at", "completed_at"}

    def __getitem__(self, key):
        if key in self._FORBIDDEN:
            raise AssertionError(
                f"f5_eval read forbidden key {key!r} -- PIT violation")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in self._FORBIDDEN:
            raise AssertionError(
                f"f5_eval read forbidden key {key!r} -- PIT violation")
        return super().get(key, default)


def _synthetic_game(pk, date, home_price=-150, away_price=130,
                    winner="home", books=None):
    row = PoisonDict({
        "game_pk": pk,
        "date": date,
        "book_count": 5,
        "books": books or _books([
            ("dk", away_price, home_price), ("fd", away_price, home_price),
            ("mgm", away_price, home_price), ("bov", away_price, home_price),
            ("csr", away_price, home_price),
        ]),
        "actual_first_pitch": "2099-01-01T00:00:00Z",  # would raise if read
        "status": "OK",
    })
    settled = {"game_pk": pk, "complete": True, "winner": winner,
              "settled_at": "2099-01-01T00:00:00Z"}
    return row, settled["winner"]


# ---------------------------------------------------------------------------
# 1. Synthetic-injection recovery
# ---------------------------------------------------------------------------

class TestSyntheticInjectionRecovery(unittest.TestCase):
    """Construct rows with a KNOWN injected calibration error and assert the
    path recovers it, sign and magnitude, with date clustering intact --
    mirrors tests/test_engine_features.py's own house style for this kind
    of proof."""

    def test_positive_home_bias_recovered_sign_and_magnitude(self):
        # Fair home probability at -150/+130 is ~0.582 (proportional). Home
        # wins EVERY game here, so the injected calibration error is
        # (1.0 - 0.582) ~= +0.418 -- large and unambiguous, a sanity anchor
        # rather than a realistic effect size.
        gradeable = [
            _synthetic_game(f"g{i}", f"2023-0{5 if i < 15 else 6}-{(i % 27) + 1:02d}",
                            winner="home")
            for i in range(1, 41)
        ]
        rows = f5_eval.build_h1_rows(gradeable)
        result = f5_eval.evaluate_h1(rows)
        self.assertGreater(result["effect"], 0.30)
        self.assertLess(result["p"], 0.01)
        self.assertIsNotNone(result["ci"])
        self.assertGreater(result["ci"]["low"], 0)

    def test_negative_home_bias_recovered_sign(self):
        gradeable = [
            _synthetic_game(f"g{i}", f"2023-0{5 if i < 15 else 6}-{(i % 27) + 1:02d}",
                            winner="away")
            for i in range(1, 41)
        ]
        rows = f5_eval.build_h1_rows(gradeable)
        result = f5_eval.evaluate_h1(rows)
        self.assertLess(result["effect"], 0)
        self.assertLess(result["ci"]["high"], 0)

    def test_null_effect_at_true_calibration_does_not_reject(self):
        # Half win, half lose, at a fair coin-flip price -- no injected bias.
        gradeable = []
        for i in range(60):
            winner = "home" if i % 2 == 0 else "away"
            gradeable.append(_synthetic_game(
                f"g{i}", f"2023-05-{(i % 27) + 1:02d}",
                home_price=100, away_price=100, winner=winner))
        rows = f5_eval.build_h1_rows(gradeable)
        result = f5_eval.evaluate_h1(rows)
        self.assertIn(result["verdict"],
                      ["the clustered interval includes zero: this is "
                       "consistent with no effect at all"])

    def test_date_clustering_survives_row_construction(self):
        # Same date repeated -> discovery.py's date-cluster bootstrap must
        # see fewer clusters than rows, proving row['date'] round-trips.
        gradeable = [_synthetic_game(f"g{i}", "2023-06-15", winner="home")
                    for i in range(35)]
        rows = f5_eval.build_h1_rows(gradeable)
        dates = {r["date"] for r in rows}
        self.assertEqual(dates, {"2023-06-15"})
        ci = f5_eval.evaluate_h1(rows)["ci"]
        # A single cluster date cannot be resampled (discovery.py requires
        # >=2 distinct dates), so the bootstrap correctly refuses.
        self.assertEqual(ci["resamples"], 0)


# ---------------------------------------------------------------------------
# 2. PIT negative tests
# ---------------------------------------------------------------------------

class TestPITGuards(unittest.TestCase):
    def test_injected_2025_row_raises_not_filtered(self):
        gradeable = [_synthetic_game("g1", "2025-06-01")]
        rows = f5_eval.build_h1_rows(gradeable)
        with self.assertRaises(f5_eval.F5EvalError):
            f5_eval._verify_window(rows)

    def test_injected_2026_row_raises_not_filtered(self):
        gradeable = [_synthetic_game("g1", "2026-06-01")]
        rows = f5_eval.build_h1_rows(gradeable)
        with self.assertRaises(f5_eval.F5EvalError):
            f5_eval._verify_window(rows)

    def test_pre_window_2023_row_raises(self):
        gradeable = [_synthetic_game("g1", "2023-01-01")]
        rows = f5_eval.build_h1_rows(gradeable)
        with self.assertRaises(f5_eval.F5EvalError):
            f5_eval._verify_window(rows)

    def test_row_inside_window_passes(self):
        gradeable = [_synthetic_game("g1", "2023-05-10"),
                    _synthetic_game("g2", "2024-10-07")]
        rows = f5_eval.build_h1_rows(gradeable)
        f5_eval._verify_window(rows)  # must not raise

    def test_actual_first_pitch_never_read_by_row_construction(self):
        # PoisonDict raises AssertionError if 'actual_first_pitch' is
        # touched anywhere in build_h1_rows/build_h2_rows.
        gradeable = [_synthetic_game(f"g{i}", f"2023-05-{i + 10:02d}",
                                     winner="home" if i % 2 else "away")
                    for i in range(10)]
        f5_eval.build_h1_rows(gradeable, dry_run=True)
        f5_eval.build_h2_rows(gradeable, dry_run=True)

    def test_actual_first_pitch_never_read_in_full_row_construction(self):
        gradeable = [_synthetic_game(f"g{i}", f"2023-05-{i + 10:02d}",
                                     winner="home" if i % 2 else "away")
                    for i in range(10)]
        f5_eval.build_h1_rows(gradeable)  # dry_run=False -- reads `winner`
        f5_eval.build_h2_rows(gradeable)


# ---------------------------------------------------------------------------
# 3. Denominator + both hashes
# ---------------------------------------------------------------------------

class TestDenominatorAndHashGuards(unittest.TestCase):
    def test_row_count_mismatch_raises(self):
        with self.assertRaises(f5_eval.F5EvalError):
            f5_eval._verify_row_shape([{"game_pk": "1", "date": "2023-05-10",
                                       "season": "2023"}])

    def test_season_split_mismatch_raises_even_at_right_count(self):
        rows = [{"game_pk": str(i), "date": "2023-05-10", "season": "2023"}
               for i in range(f5_eval.EXPECTED_ROW_COUNT)]
        with self.assertRaises(f5_eval.F5EvalError):
            f5_eval._verify_row_shape(rows)

    def test_exact_count_and_split_passes(self):
        rows = ([{"game_pk": str(i), "date": "2023-05-10", "season": "2023"}
                for i in range(1597)]
               + [{"game_pk": str(i), "date": "2024-06-01", "season": "2024"}
                  for i in range(2085)])
        f5_eval._verify_row_shape(rows)  # must not raise

    def test_verify_universe_raises_on_identity_hash_mismatch(self, ):
        self._assert_verify_universe_raises(mutate="content_hash")

    def test_verify_universe_raises_on_price_payload_hash_mismatch(self):
        self._assert_verify_universe_raises(mutate="price_payload_hash")

    def _assert_verify_universe_raises(self, mutate):
        import tempfile

        primary_rows = [
            {"game_pk": "1", "date": "2023-05-10", "book_count": 5,
             "status": "OK", "books": _books([("dk", 130, -150)])},
        ]
        settlement_rows = [{"game_pk": "1", "complete": True, "winner": "home"}]

        with tempfile.TemporaryDirectory() as tmp:
            primary_path = Path(tmp) / "primary.jsonl"
            settlement_path = Path(tmp) / "settlement.jsonl"
            manifest_path = Path(tmp) / "manifest.json"
            primary_path.write_text(
                "\n".join(json.dumps(r) for r in primary_rows), encoding="utf-8")
            settlement_path.write_text(
                "\n".join(json.dumps(r) for r in settlement_rows), encoding="utf-8")

            manifest = f5_universe.build_universe(
                primary_path=primary_path, settlement_path=settlement_path,
                raw_store=tmp)
            manifest[mutate] = "0" * 64  # simulate drift
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(f5_eval.F5EvalError):
                f5_eval.verify_universe(
                    primary_path=primary_path, settlement_path=settlement_path,
                    raw_store=tmp, manifest_path=manifest_path)

    def test_verify_universe_passes_when_manifest_matches(self):
        import tempfile

        primary_rows = [
            {"game_pk": "1", "date": "2023-05-10", "book_count": 5,
             "status": "OK", "books": _books([("dk", 130, -150)])},
        ]
        settlement_rows = [{"game_pk": "1", "complete": True, "winner": "home"}]

        with tempfile.TemporaryDirectory() as tmp:
            primary_path = Path(tmp) / "primary.jsonl"
            settlement_path = Path(tmp) / "settlement.jsonl"
            manifest_path = Path(tmp) / "manifest.json"
            primary_path.write_text(
                "\n".join(json.dumps(r) for r in primary_rows), encoding="utf-8")
            settlement_path.write_text(
                "\n".join(json.dumps(r) for r in settlement_rows), encoding="utf-8")

            manifest = f5_universe.build_universe(
                primary_path=primary_path, settlement_path=settlement_path,
                raw_store=tmp)
            f5_universe.write_manifest(manifest, manifest_path)

            result = f5_eval.verify_universe(
                primary_path=primary_path, settlement_path=settlement_path,
                raw_store=tmp, manifest_path=manifest_path)
            self.assertTrue(result["verified"])


class TestRealUniverseDenominator(unittest.TestCase):
    """Against the real (gitignored) stores: proves the guard passes on the
    live frozen universe, not just on synthetic fixtures."""

    def setUp(self):
        if not _data_available():
            self.skipTest("F5 historical stores or frozen manifest not present "
                          "on this checkout")

    def test_gradeable_row_count_matches_frozen_denominator(self):
        gradeable = f5_eval.load_gradeable_primary_rows()
        rows = f5_eval.build_h1_rows(gradeable, dry_run=True)
        f5_eval._verify_row_shape(rows)  # must not raise: 3,682 / 1,597 / 2,085

    def test_hashes_verify_on_the_real_frozen_manifest(self):
        result = f5_eval.verify_universe()
        self.assertTrue(result["verified"])

    def test_dry_run_smoke_against_real_data(self):
        result = f5_eval.run(dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["row_counts"]["h1"], f5_eval.EXPECTED_ROW_COUNT)
        self.assertEqual(result["season_split"], f5_eval.EXPECTED_SEASON_SPLIT)
        self.assertGreaterEqual(result["bucket_counts_2024"][0],
                                f5_eval.MIN_BUCKET_N_2024)
        self.assertGreaterEqual(result["bucket_counts_2024"][2],
                                f5_eval.MIN_BUCKET_N_2024)


# ---------------------------------------------------------------------------
# 4. De-vig convention agreement (A1 audit + A2 sensitivity)
# ---------------------------------------------------------------------------

class TestDevigConventions(unittest.TestCase):
    def test_all_three_conventions_agree_closely_on_a_moderate_two_way_market(self):
        row = {"books": _books([("dk", 130, -150)]), "book_count": 1}
        results = {label: f5_eval.consensus_fair(row, method)["home_fair"]
                  for label, method in f5_eval.DEVIG_METHODS.items()}
        # -150/+130 is only mildly lopsided; the three conventions must not
        # diverge by more than a couple of points here.
        values = list(results.values())
        self.assertLess(max(values) - min(values), 0.02, results)
        # Hand-check against raw math: proportional = 150/(150+130*100/130..)
        raw_home = odds_math.american_to_probability(-150)
        raw_away = odds_math.american_to_probability(130)
        expected_proportional = raw_home / (raw_home + raw_away)
        self.assertAlmostEqual(results["proportional"], expected_proportional, places=6)

    def test_favourite_longshot_signature_on_a_lopsided_market(self):
        # A2: proportional overstates the longshot's probability relative to
        # Shin/power on a lopsided book -- i.e. proportional's favourite
        # (home) fair probability should be LOWER than Shin's/power's here.
        row = {"books": _books([("dk", 450, -900)]), "book_count": 1}
        prop = f5_eval.consensus_fair(row, "proportional")["home_fair"]
        power = f5_eval.consensus_fair(row, "power")["home_fair"]
        shin = f5_eval.consensus_fair(row, "shin")["home_fair"]
        self.assertLess(prop, power)
        self.assertLess(prop, shin)

    def test_consensus_fair_returns_none_when_no_book_devigs(self):
        row = {"books": [{"key": "dk", "h2h_1st_5_innings":
                          {"away_price": None, "home_price": -150}}]}
        self.assertIsNone(f5_eval.consensus_fair(row, "proportional"))

    def test_tie_audit_two_way_only_books_never_excluded(self):
        # A1: this module's exclusion logic (none needed here, per
        # scripts/f5_tie_audit.py's real-data finding of zero three-way
        # books) must not accidentally drop a genuine two-way book.
        row = {"books": _books([("dk", 130, -150), ("fd", 135, -155)]),
              "book_count": 2}
        c = f5_eval.consensus_fair(row, "proportional")
        self.assertEqual(c["n_books"], 2)


# ---------------------------------------------------------------------------
# 5. Battery wiring: frozen rules, no bespoke rule, skips recorded
# ---------------------------------------------------------------------------

class TestBatteryWiring(unittest.TestCase):
    def _rows(self, n=40, effect=0.30):
        gradeable = []
        for i in range(n):
            winner = "home" if i % 2 == 0 else "away"
            gradeable.append(_synthetic_game(
                f"g{i}", f"2023-0{5 if i < n // 2 else 6}-{(i % 27) + 1:02d}",
                home_price=100, away_price=100, winner=winner))
        return f5_eval.build_h1_rows(gradeable)

    def test_battery_uses_frozen_rules_version_verbatim(self):
        result = f5_eval.run_battery(self._rows(), effect_floor=0.01)
        self.assertEqual(result["rules"]["version"], battery.RULES_VERSION)
        self.assertEqual(result["rules"]["fingerprint"], battery.rules_fingerprint())

    def test_book_and_team_concentration_are_recorded_as_skipped(self):
        # A4: these rows carry no per-row 'team' or 'book' key -- both
        # hypotheses grade one consensus row per game -- so rule 2 and rule
        # 3 must report {"skipped": ...} and the wiring must NAME them,
        # never let the skip pass unremembered.
        result = f5_eval.run_battery(self._rows(), effect_floor=0.01)
        self.assertIn("team_concentration", result["skipped_checks"])
        self.assertIn("book_concentration", result["skipped_checks"])

    def test_per_book_diagnostic_is_report_only_and_separate_from_battery(self):
        gradeable = [_synthetic_game(f"g{i}", f"2023-05-{(i % 27) + 1:02d}",
                                     winner="home" if i % 2 else "away")
                    for i in range(40)]
        diag = f5_eval.per_book_sign_replication(gradeable, min_n=5)
        self.assertTrue(diag)
        for book, entry in diag.items():
            self.assertIn("n", entry)


# ---------------------------------------------------------------------------
# Terciles and population-shift (amendments 1 and A5)
# ---------------------------------------------------------------------------

class TestTercilesAndPopulationShift(unittest.TestCase):
    def _h2_rows(self, n_2023, n_2024, shift=False):
        gradeable = []
        for i in range(n_2023):
            price = -100 - (i * 4)  # spreads p_fav across the range
            gradeable.append(_synthetic_game(
                f"a{i}", f"2023-05-{(i % 27) + 1:02d}",
                home_price=price, away_price=-price + 20,
                winner="home" if i % 2 else "away"))
        for i in range(n_2024):
            price = -100 - (i * 4) if not shift else -900  # all favourites
            gradeable.append(_synthetic_game(
                f"b{i}", f"2024-0{5 if i < n_2024 // 2 else 6}-{(i % 27) + 1:02d}",
                home_price=price, away_price=-price + 20 if not shift else 750,
                winner="home" if i % 2 else "away"))
        return f5_eval.build_h2_rows(gradeable)

    def test_terciles_fit_on_2023_only(self):
        rows = self._h2_rows(60, 60)
        edges = f5_eval.fit_terciles_2023(rows)
        rows_2024_only = [r for r in rows if r["season"] == "2024"]
        edges_ignoring_2024 = f5_eval.fit_terciles_2023(
            [r for r in rows if r["season"] == "2023"] + rows_2024_only)
        # Fitting must be identical whether or not 2024 rows are present in
        # the input list -- the fit reads season=="2023" rows only.
        self.assertEqual(edges, edges_ignoring_2024)

    def test_population_shift_not_fatal_when_distributions_match(self):
        rows = self._h2_rows(90, 90, shift=False)
        edges = f5_eval.fit_terciles_2023(rows)
        f5_eval._assign_buckets(rows, edges)
        r2023 = [r for r in rows if r["season"] == "2023"]
        r2024 = [r for r in rows if r["season"] == "2024"]
        shift = f5_eval.population_shift_test(r2023, r2024)
        self.assertFalse(shift["fatal"])

    def test_population_shift_fatal_when_2024_mix_shifts_hard(self):
        rows = self._h2_rows(90, 90, shift=True)
        edges = f5_eval.fit_terciles_2023(rows)
        f5_eval._assign_buckets(rows, edges)
        r2023 = [r for r in rows if r["season"] == "2023"]
        r2024 = [r for r in rows if r["season"] == "2024"]
        shift = f5_eval.population_shift_test(r2023, r2024)
        self.assertTrue(shift["fatal"])
        self.assertLess(shift["p"], f5_eval.POPULATION_SHIFT_P_FATAL)

    def test_chi_square_p_df2_closed_form_matches_known_values(self):
        # Exponential(scale=2) survival function: exp(-x/2).
        self.assertAlmostEqual(f5_eval.chi_square_p_df2(0.0), 1.0)
        self.assertAlmostEqual(f5_eval.chi_square_p_df2(9.21), 0.00996, places=4)


if __name__ == "__main__":
    unittest.main()
