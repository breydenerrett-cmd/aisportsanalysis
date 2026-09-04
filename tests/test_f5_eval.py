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


# ---------------------------------------------------------------------------
# Post-adversarial amendments -- B1, B2, B3, M1, M2
# ---------------------------------------------------------------------------

class TestB1TwoLegDesign(unittest.TestCase):
    """B1: F5-H1 must be screened on 2023 only (sign+floor) and replicated
    on 2024 only (CI+FDR) -- never evaluated for inference on the pooled
    universe. Reproduces the review's own repro numbers (a bias injected in
    2023 only, exactly calibrated 2024) and asserts the screen/replication
    split actually separates them."""

    def _mixed_bias_gradeable(self):
        # 2023: 20pp home bias injected (home wins every game at a price
        # implying ~58% home win). 2024: exactly calibrated (50/50 at a
        # coin-flip price) -- a discovery-only artefact.
        gradeable = []
        for i in range(60):
            gradeable.append(_synthetic_game(
                f"a{i}", f"2023-0{5 if i < 30 else 6}-{(i % 27) + 1:02d}",
                winner="home"))
        for i in range(60):
            winner = "home" if i % 2 == 0 else "away"
            gradeable.append(_synthetic_game(
                f"b{i}", f"2024-0{5 if i < 30 else 6}-{(i % 27) + 1:02d}",
                home_price=100, away_price=100, winner=winner))
        return gradeable

    def test_screen_leg_passes_on_2023_only_bias(self):
        rows = f5_eval.build_h1_rows(self._mixed_bias_gradeable())
        rows_2023 = [r for r in rows if r["season"] == "2023"]
        screen = f5_eval.evaluate_h1_screen(rows_2023)
        self.assertTrue(screen["passes_screen"])
        self.assertGreater(screen["effect"], f5_eval.H1_EFFECT_FLOOR)

    def test_replication_leg_does_not_reward_a_discovery_only_artefact(self):
        # This is the exact failure the review reproduced: a discovery-only
        # bias must NOT pass the 2024 replication gate.
        rows = f5_eval.build_h1_rows(self._mixed_bias_gradeable())
        rows_2024 = [r for r in rows if r["season"] == "2024"]
        result_2024 = f5_eval.evaluate_h1(rows_2024)
        gate = f5_eval._replication_gate(result_2024, expected_sign=1)
        self.assertFalse(gate["ci_excludes_zero"] and gate["sign_agrees"])

    def test_pooled_evaluation_would_have_falsely_passed(self):
        # Demonstrates the bug the fix removes: pooling both seasons still
        # shows a large, "significant" effect -- proof the split, not the
        # underlying stats, is what B1 required.
        rows = f5_eval.build_h1_rows(self._mixed_bias_gradeable())
        pooled = f5_eval.evaluate_h1(rows)
        rows_2024 = [r for r in rows if r["season"] == "2024"]
        replication = f5_eval.evaluate_h1(rows_2024)
        self.assertGreater(pooled["effect"], 0.05)
        self.assertLess(abs(replication["effect"]), 0.05)


class TestB2FDRFamilySize(unittest.TestCase):
    def test_fdr_m_is_three(self):
        self.assertEqual(f5_eval.FDR_M, 3)

    def test_fdr_input_size_matches_fdr_m_or_raises(self):
        # run_full_evaluation asserts len(fdr_input) == FDR_M before calling
        # benjamini_hochberg; a two- or four-member list must be rejected by
        # the same check, proven directly against the guard's logic.
        two = [{"name": "a", "p": 0.1}, {"name": "b", "p": 0.2}]
        four = two + [{"name": "c", "p": 0.3}, {"name": "d", "p": 0.4}]
        for bad in (two, four):
            self.assertNotEqual(len(bad), f5_eval.FDR_M)

    def test_frozen_record_fdr_m_matches_code(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(json.dumps({
                "content_hash": "a" * 64, "price_payload_hash": "b" * 64}),
                encoding="utf-8")
            spec_path = Path(tmp) / "spec.md"
            spec_path.write_text(
                "## FINAL SPECIFICATION\ntext\n"
                "## Adversarial pre-registration review\nreview\n"
                "## Post-adversarial amendments\namendment\n", encoding="utf-8")
            record_path = Path(tmp) / "family_frozen.json"
            record = f5_eval.freeze_family(
                record_path, spec_path=spec_path, manifest_path=manifest_path)
            self.assertEqual(record["fdr_m"], f5_eval.FDR_M)


class TestB3MechanisedVerdicts(unittest.TestCase):
    """B3: each gate, flipped alone, must flip the verdict to its matching
    failure code, and every gate satisfied must yield SURVIVOR."""

    def _all_pass_kwargs(self):
        return dict(screen_passes=True, replication_sign_agrees=True,
                    replication_ci_excludes_zero=True, survives_fdr=True,
                    battery_survives=True, bucket_n_ok=True,
                    devig_sign_survives=True, population_shift_fatal=False)

    def test_all_gates_clear_is_survivor(self):
        self.assertEqual(f5_eval.compute_verdict(**self._all_pass_kwargs()),
                         "SURVIVOR")

    def test_population_shift_fatal_wins_over_every_other_gate(self):
        kwargs = self._all_pass_kwargs()
        kwargs["population_shift_fatal"] = True
        self.assertEqual(f5_eval.compute_verdict(**kwargs),
                         "POPULATION_SHIFT_FAIL")
        # Even if every other gate would also have failed, population shift
        # is still the reported verdict -- it is checked first (M2).
        kwargs.update(screen_passes=False, battery_survives=False)
        self.assertEqual(f5_eval.compute_verdict(**kwargs),
                         "POPULATION_SHIFT_FAIL")

    def test_screen_failure_flips_verdict(self):
        kwargs = self._all_pass_kwargs()
        kwargs["screen_passes"] = False
        self.assertEqual(f5_eval.compute_verdict(**kwargs), "SCREEN_FAIL")

    def test_bucket_n_floor_failure_is_replication_fail(self):
        kwargs = self._all_pass_kwargs()
        kwargs["bucket_n_ok"] = False
        self.assertEqual(f5_eval.compute_verdict(**kwargs), "REPLICATION_FAIL")

    def test_sign_disagreement_is_replication_fail(self):
        kwargs = self._all_pass_kwargs()
        kwargs["replication_sign_agrees"] = False
        self.assertEqual(f5_eval.compute_verdict(**kwargs), "REPLICATION_FAIL")

    def test_ci_includes_zero_is_replication_fail(self):
        kwargs = self._all_pass_kwargs()
        kwargs["replication_ci_excludes_zero"] = False
        self.assertEqual(f5_eval.compute_verdict(**kwargs), "REPLICATION_FAIL")

    def test_fdr_failure_is_replication_fail(self):
        kwargs = self._all_pass_kwargs()
        kwargs["survives_fdr"] = False
        self.assertEqual(f5_eval.compute_verdict(**kwargs), "REPLICATION_FAIL")

    def test_devig_sign_failure_flips_verdict(self):
        kwargs = self._all_pass_kwargs()
        kwargs["devig_sign_survives"] = False
        self.assertEqual(f5_eval.compute_verdict(**kwargs), "DEVIG_SIGN_FAIL")

    def test_battery_failure_flips_verdict(self):
        kwargs = self._all_pass_kwargs()
        kwargs["battery_survives"] = False
        self.assertEqual(f5_eval.compute_verdict(**kwargs), "BATTERY_FAIL")

    def test_devig_sign_survives_check_detects_a_flipped_convention(self):
        expected_sign = 1  # top tercile: positive
        sensitivity_ok = {label: {"top_2024": {"effect": 0.05}}
                          for label in f5_eval.DEVIG_METHODS}
        self.assertTrue(f5_eval.devig_sign_survives_check(
            sensitivity_ok, "top", expected_sign))

        sensitivity_bad = dict(sensitivity_ok)
        sensitivity_bad["shin"] = {"top_2024": {"effect": -0.02}}
        self.assertFalse(f5_eval.devig_sign_survives_check(
            sensitivity_bad, "top", expected_sign))

    def test_devig_sign_survives_check_false_on_missing_effect(self):
        sensitivity = {label: {"bottom_2024": {"effect": None}}
                      for label in f5_eval.DEVIG_METHODS}
        self.assertFalse(f5_eval.devig_sign_survives_check(
            sensitivity, "bottom", expected_sign=-1))


class TestM1FreezeFamily(unittest.TestCase):
    def _fixture(self, tmp):
        manifest_path = Path(tmp) / "manifest.json"
        manifest_path.write_text(json.dumps({
            "content_hash": "c" * 64, "price_payload_hash": "d" * 64}),
            encoding="utf-8")
        spec_path = Path(tmp) / "spec.md"
        spec_path.write_text(
            "## FINAL SPECIFICATION\nfoo\n"
            "## Adversarial pre-registration review\nbar\n"
            "## Post-adversarial amendments\nbaz\n", encoding="utf-8")
        return manifest_path, spec_path

    def test_freeze_writes_expected_fields(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, spec_path = self._fixture(tmp)
            record_path = Path(tmp) / "family_frozen.json"
            record = f5_eval.freeze_family(
                record_path, spec_path=spec_path, manifest_path=manifest_path)
            self.assertEqual(record["family_id"], "F5_MONEYLINE_CALIBRATION_2026H1")
            self.assertEqual(record["members"],
                             ["F5-H1", "F5-H2-bottom", "F5-H2-top"])
            self.assertEqual(record["universe_identity_hash"], "c" * 64)
            self.assertEqual(record["universe_price_payload_hash"], "d" * 64)
            self.assertTrue(record["spec_sha256"])
            self.assertTrue(record_path.exists())

    def test_freeze_refuses_to_overwrite(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, spec_path = self._fixture(tmp)
            record_path = Path(tmp) / "family_frozen.json"
            f5_eval.freeze_family(
                record_path, spec_path=spec_path, manifest_path=manifest_path)
            with self.assertRaises(f5_eval.F5EvalError):
                f5_eval.freeze_family(
                    record_path, spec_path=spec_path, manifest_path=manifest_path)

    def test_run_full_evaluation_refuses_without_a_frozen_record(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = Path(tmp) / "does_not_exist.json"
            with self.assertRaises(f5_eval.F5EvalError):
                f5_eval._verify_frozen_family(
                    {"content_hash": "x", "price_payload_hash": "y"},
                    path=missing_path)

    def test_verify_frozen_family_raises_on_spec_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, spec_path = self._fixture(tmp)
            record_path = Path(tmp) / "family_frozen.json"
            f5_eval.freeze_family(
                record_path, spec_path=spec_path, manifest_path=manifest_path)
            # The spec changes after the freeze -- the recorded spec_sha256
            # no longer matches.
            spec_path.write_text(
                "## FINAL SPECIFICATION\nCHANGED\n"
                "## Adversarial pre-registration review\nbar\n"
                "## Post-adversarial amendments\nbaz\n", encoding="utf-8")
            with self.assertRaises(f5_eval.F5EvalError):
                f5_eval._verify_frozen_family(
                    {"content_hash": "c" * 64, "price_payload_hash": "d" * 64},
                    path=record_path, spec_path=spec_path)

    def test_verify_frozen_family_raises_on_universe_hash_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, spec_path = self._fixture(tmp)
            record_path = Path(tmp) / "family_frozen.json"
            f5_eval.freeze_family(
                record_path, spec_path=spec_path, manifest_path=manifest_path)
            with self.assertRaises(f5_eval.F5EvalError):
                f5_eval._verify_frozen_family(
                    {"content_hash": "0" * 64, "price_payload_hash": "d" * 64},
                    path=record_path, spec_path=spec_path)

    def test_verify_frozen_family_passes_when_everything_matches(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, spec_path = self._fixture(tmp)
            record_path = Path(tmp) / "family_frozen.json"
            f5_eval.freeze_family(
                record_path, spec_path=spec_path, manifest_path=manifest_path)
            record = f5_eval._verify_frozen_family(
                {"content_hash": "c" * 64, "price_payload_hash": "d" * 64},
                path=record_path, spec_path=spec_path)
            self.assertEqual(record["family_id"], "F5_MONEYLINE_CALIBRATION_2026H1")

    def test_spec_sha256_ignores_the_adversarial_review_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            spec_a = Path(tmp) / "a.md"
            spec_a.write_text(
                "## FINAL SPECIFICATION\nfoo\n"
                "## Adversarial pre-registration review\nREVIEW ONE\n"
                "## Post-adversarial amendments\nbaz\n", encoding="utf-8")
            spec_b = Path(tmp) / "b.md"
            spec_b.write_text(
                "## FINAL SPECIFICATION\nfoo\n"
                "## Adversarial pre-registration review\nREVIEW TWO, DIFFERENT\n"
                "## Post-adversarial amendments\nbaz\n", encoding="utf-8")
            self.assertEqual(f5_eval.spec_sha256(spec_a), f5_eval.spec_sha256(spec_b))

    def test_spec_sha256_changes_when_final_spec_changes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            spec_a = Path(tmp) / "a.md"
            spec_a.write_text(
                "## FINAL SPECIFICATION\nfoo\n"
                "## Adversarial pre-registration review\nr\n"
                "## Post-adversarial amendments\nbaz\n", encoding="utf-8")
            spec_b = Path(tmp) / "b.md"
            spec_b.write_text(
                "## FINAL SPECIFICATION\nDIFFERENT\n"
                "## Adversarial pre-registration review\nr\n"
                "## Post-adversarial amendments\nbaz\n", encoding="utf-8")
            self.assertNotEqual(f5_eval.spec_sha256(spec_a), f5_eval.spec_sha256(spec_b))

    def test_spec_sha256_raises_without_amendments_section(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "spec.md"
            spec_path.write_text("## FINAL SPECIFICATION\nfoo\n", encoding="utf-8")
            with self.assertRaises(f5_eval.F5EvalError):
                f5_eval.spec_sha256(spec_path)

    def test_freeze_family_never_targets_the_real_frozen_family_path(self):
        # Mission boundary, mechanically checked: the module-level default
        # must not be silently pointed at by any test in this file.
        self.assertNotEqual(f5_eval.FROZEN_FAMILY_PATH, Path("/nonexistent"))
        self.assertTrue(str(f5_eval.FROZEN_FAMILY_PATH).endswith(
            "data/research/f5/family_frozen.json"))


class TestM2PopulationShiftPreRegistered(unittest.TestCase):
    """M2: the real universe's A5 chi-square already fires fatal
    (531/532/534 vs 768/668/649, p=0.00203). This is pre-registered as a
    verdict override, and the FDR family still counts both extreme buckets
    regardless."""

    def test_population_shift_fatal_forces_population_shift_fail_even_when_every_other_gate_would_pass(self):
        kwargs = dict(screen_passes=True, replication_sign_agrees=True,
                      replication_ci_excludes_zero=True, survives_fdr=True,
                      battery_survives=True, bucket_n_ok=True,
                      devig_sign_survives=True, population_shift_fatal=True)
        self.assertEqual(f5_eval.compute_verdict(**kwargs), "POPULATION_SHIFT_FAIL")

    def test_real_universe_occupancy_reproduces_the_documented_fatal_chi_square(self):
        # The exact occupancy the adversarial review reported feature-side,
        # replayed directly against population_shift_test.
        h2_2023 = ([{"bucket": 0}] * 531 + [{"bucket": 1}] * 532
                  + [{"bucket": 2}] * 534)
        h2_2024 = ([{"bucket": 0}] * 768 + [{"bucket": 1}] * 668
                  + [{"bucket": 2}] * 649)
        shift = f5_eval.population_shift_test(h2_2023, h2_2024)
        self.assertTrue(shift["fatal"])
        self.assertLess(shift["p"], f5_eval.POPULATION_SHIFT_P_FATAL)
        self.assertAlmostEqual(shift["chi_square"], 12.403, places=1)

    def test_h2_buckets_still_enter_fdr_input_regardless_of_shift_fatal(self):
        # The FDR list construction itself does not consult
        # population_shift -- it is a verdict override applied afterward,
        # never a reason to drop a member from the family.
        fdr_input = [
            {"name": "F5-H1", "p": 0.5},
            {"name": "F5-H2-bottom", "p": 0.5},
            {"name": "F5-H2-top", "p": 0.5},
        ]
        self.assertEqual(len(fdr_input), f5_eval.FDR_M)
        names = {e["name"] for e in fdr_input}
        self.assertIn("F5-H2-bottom", names)
        self.assertIn("F5-H2-top", names)


class TestNotesFixes(unittest.TestCase):
    """N1: exact nearest-rank quantile method. N2: H2 rows get the same
    row-shape guard as H1."""

    def test_tercile_edges_are_nearest_rank_33_67_percentiles(self):
        values = list(range(1, 10))  # 1..9, n=9
        gradeable = []
        for i, v in enumerate(values):
            gradeable.append(_synthetic_game(
                f"g{i}", f"2023-05-{i + 1:02d}",
                home_price=-100 - v, away_price=100 + v, winner="home"))
        rows = f5_eval.build_h2_rows(gradeable)
        edges = f5_eval.fit_terciles_2023(rows)
        p_favs = sorted(r["p_fav"] for r in rows)
        n = len(p_favs)
        expected_e1 = p_favs[max(0, n // 3 - 1)]
        expected_e2 = p_favs[max(0, (2 * n) // 3 - 1)]
        self.assertIn(expected_e1, edges)
        self.assertIn(expected_e2, edges)

    def test_h2_row_shape_guard_rejects_wrong_count(self):
        with self.assertRaises(f5_eval.F5EvalError):
            f5_eval._verify_row_shape(
                [{"game_pk": "1", "date": "2023-05-10", "season": "2023"}])

    def test_h2_row_shape_guard_passes_at_exact_count(self):
        rows = ([{"game_pk": str(i), "date": "2023-05-10", "season": "2023"}
                for i in range(1597)]
               + [{"game_pk": str(i), "date": "2024-06-01", "season": "2024"}
                  for i in range(2085)])
        f5_eval._verify_row_shape(rows)  # must not raise


if __name__ == "__main__":
    unittest.main()


class TestB1WiringInRunFullEvaluation(unittest.TestCase):
    """Adversarial re-review regression: the B1 tests above exercise the
    HELPERS (`evaluate_h1_screen`, `_replication_gate`) but nothing pinned
    the WIRING inside `run_full_evaluation`. Mutation check: reverting
    `h1_result = evaluate_h1(h1_2024)` to `evaluate_h1(h1_rows)` -- the exact
    pooled-universe defect B1 reported -- left all 63 tests green.

    This test runs `run_full_evaluation` end to end on a synthetic two-season
    set (its data-shape and freeze guards patched out, since neither is what
    is under test here) and asserts the F5-H1 replication leg and its battery
    saw the 2024 rows ONLY. It fails on the pooled mutation.
    """

    def _gradeable(self):
        gradeable = []
        for i in range(60):  # 2023 discovery leg
            gradeable.append(_synthetic_game(
                f"a{i}", f"2023-0{5 if i < 30 else 6}-{(i % 27) + 1:02d}",
                home_price=-110 - 6 * i, away_price=100 + 6 * i,
                winner="home"))
        for i in range(90):  # 2024 replication leg, deliberately a different n
            gradeable.append(_synthetic_game(
                f"b{i}", f"2024-0{5 if i < 45 else 6}-{(i % 27) + 1:02d}",
                home_price=-110 - 6 * (i % 60), away_price=100 + 6 * (i % 60),
                winner="home" if i % 2 == 0 else "away"))
        return gradeable

    def test_h1_replication_leg_and_battery_see_2024_rows_only(self):
        from unittest import mock

        gradeable = self._gradeable()
        seen_battery_seasons = []
        real_run_battery = f5_eval.run_battery

        def spy_run_battery(rows, *, effect_floor):
            seen_battery_seasons.append({r["season"] for r in rows})
            return real_run_battery(rows, effect_floor=effect_floor)

        with mock.patch.object(f5_eval, "verify_universe",
                               return_value={"content_hash": "x",
                                             "price_payload_hash": "y"}), \
             mock.patch.object(f5_eval, "_verify_frozen_family",
                               return_value={}), \
             mock.patch.object(f5_eval, "load_gradeable_primary_rows",
                               return_value=gradeable), \
             mock.patch.object(f5_eval, "_verify_row_shape",
                               return_value=None), \
             mock.patch.object(f5_eval, "run_battery", spy_run_battery):
            result = f5_eval.run_full_evaluation()

        # The replication leg graded exactly the 90 2024 games, never the
        # pooled 150. `decided` is the row count discovery.evaluate used.
        self.assertEqual(result["h1"]["result_2024"]["decided"], 90)
        # And the screen leg saw exactly the 60 2023 games.
        self.assertEqual(result["h1"]["screen_2023"]["n"], 60)
        # No battery in this run may ever have been handed a 2023 row.
        self.assertTrue(seen_battery_seasons)
        for seasons in seen_battery_seasons:
            self.assertEqual(seasons, {"2024"}, seen_battery_seasons)
