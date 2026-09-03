"""Tests for src/engine/features.py: the one feature builder both the live
engine and the historical replay share.

Matrix-equivalence runs against the REAL, tracked
`data/research/matchup_matrix_2023.jsonl` and the real historical primitives
(`data/historical/{mlb_results.csv,lineups.jsonl,handedness.json}` -- copied
read-only into this worktree for this session; see the task report for
sha256s) that produced it, per the task's own instruction not to fabricate a
synthetic stand-in for the one thing this test exists to prove. Every other
test in this file builds tiny synthetic stores under a tempdir, exactly like
tests/test_asof.py, so the rest of the suite stays hermetic.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core import asof as asof_module
from src.engine import features as F
from src.engine import glue
from src.research import funnel, matrix as matrix_module

REAL_MATRIX_2023 = Path("data/research/matchup_matrix_2023.jsonl")


def _real_matrix_row(game_pk: str) -> dict:
    with REAL_MATRIX_2023.open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("game_pk") == game_pk:
                return row
    raise AssertionError(f"game {game_pk} not found in {REAL_MATRIX_2023}")


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _pk(row: dict):
    v = row.get("game_pk")
    return str(v) if v is not None else None


def _obs(row: dict):
    return row.get("observed_utc")


class TestFeatureAccounting(unittest.TestCase):
    """The exclusion list is exhaustive against the matrix's own registered
    numeric columns -- if matrix.py or funnel.py ever grows/shrinks a
    column, this fails instead of silently going stale."""

    def test_reproducible_plus_unavailable_equals_numeric_matrix_columns(self):
        self.assertEqual(
            set(F.REPRODUCIBLE_FEATURES) | set(F.UNAVAILABLE_FEATURES),
            set(funnel.NUMERIC_FEATURES))

    def test_reproducible_and_unavailable_are_disjoint(self):
        self.assertEqual(
            set(F.REPRODUCIBLE_FEATURES) & set(F.UNAVAILABLE_FEATURES), set())

    def test_feature_specs_names_are_exactly_the_reproducible_set(self):
        self.assertEqual(
            {spec.name for spec in F.FEATURE_SPECS}, set(F.REPRODUCIBLE_FEATURES))

    def test_live_capture_start_matches_asof_exactly(self):
        # A private constant duplicated deliberately (see module docstring);
        # this is the guard against the two ever drifting onto different
        # eras unnoticed.
        self.assertEqual(F._LIVE_CAPTURE_START, asof_module._LIVE_CAPTURE_START)


class TestMatrixEquivalenceReal2023(unittest.TestCase):
    """build_features, on the real historical primitives, reproduces the
    real matchup-matrix row's own lineup_platoon_share values exactly."""

    def test_game_718781_both_sides_present(self):
        row = _real_matrix_row("718781")
        self.assertEqual(row["away_lineup_platoon_share"], 0.667)
        self.assertEqual(row["home_lineup_platoon_share"], 0.222)

        values = F.build_features("718781", row["start_time_utc"])

        self.assertEqual(
            values["away_lineup_platoon_share"].value,
            row["away_lineup_platoon_share"])
        self.assertEqual(
            values["home_lineup_platoon_share"].value,
            row["home_lineup_platoon_share"])
        self.assertEqual(set(values), {"away_lineup_platoon_share",
                                       "home_lineup_platoon_share"})

    def test_game_717427_one_side_absent_matches_matrix_null(self):
        row = _real_matrix_row("717427")
        self.assertEqual(row["away_lineup_platoon_share"], 0.778)
        self.assertIsNone(row["home_lineup_platoon_share"])

        values = F.build_features("717427", row["start_time_utc"] or
                                  row["date"] + "T00:00:00Z")

        self.assertEqual(
            values["away_lineup_platoon_share"].value,
            row["away_lineup_platoon_share"])
        # Matrix has None -> build_features has no key at all (absence, not
        # a None value on the dict).
        self.assertNotIn("home_lineup_platoon_share", values)

    def test_every_returned_value_is_grade_d_for_2023(self):
        row = _real_matrix_row("718781")
        values = F.build_features("718781", row["start_time_utc"])
        for fv in values.values():
            self.assertEqual(fv.known_at_grade, asof_module.GRADE_D)
            self.assertIsNone(fv.known_at)

    def test_unknown_game_pk_is_honestly_empty(self):
        self.assertEqual(F.build_features("999999999999", "2023-04-01T00:00:00Z"), {})


class TestLivePathSyntheticStores(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.lineups_path = self.tmp / "lineups_watch.jsonl"
        self.probables_path = self.tmp / "probables_watch.jsonl"
        self.handedness = {
            "500": {"throws": "L"}, "600": {"throws": "R"},
            "111": {"bats": "R"}, "112": {"bats": "L"},
            "211": {"bats": "R"}, "212": {"bats": "R"},
        }

    def _stores(self):
        return [
            asof_module.StoreSpec(
                name="lineups_watch", path=self.lineups_path,
                game_key_of=_pk, time_of=_obs,
                fields={"home_lineup": lambda r: r.get("home_lineup") or None,
                        "away_lineup": lambda r: r.get("away_lineup") or None}),
            asof_module.StoreSpec(
                name="probables_watch", path=self.probables_path,
                game_key_of=_pk, time_of=_obs,
                fields={"home_probable_id": lambda r: r.get("home_probable_id"),
                        "away_probable_id": lambda r: r.get("away_probable_id")}),
        ]

    def _seed(self, lineup_t="2026-04-01T18:00:00+00:00",
              probable_t="2026-04-01T17:00:00+00:00"):
        _write_jsonl(self.lineups_path, [
            {"game_pk": 999, "observed_utc": lineup_t,
             "away_lineup": [111, 112], "home_lineup": [211, 212]},
        ])
        _write_jsonl(self.probables_path, [
            {"game_pk": 999, "observed_utc": probable_t,
             "away_probable_id": 500, "home_probable_id": 600},
        ])

    def test_both_sides_computed_grade_a(self):
        self._seed()
        sources = F.FeatureSources(as_of_stores=self._stores(),
                                   handedness=self.handedness)
        values = F.build_features("999", "2026-04-01T19:00:00+00:00", sources=sources)
        self.assertEqual(values["away_lineup_platoon_share"].value, 0.5)
        self.assertEqual(values["home_lineup_platoon_share"].value, 1.0)
        for fv in values.values():
            self.assertEqual(fv.known_at_grade, asof_module.GRADE_A)
            self.assertIsNotNone(fv.known_at)

    def test_stop_at_t_shift_earlier_only_removes_never_changes(self):
        self._seed()
        sources = F.FeatureSources(as_of_stores=self._stores(),
                                   handedness=self.handedness)
        full = F.build_features("999", "2026-04-01T19:00:00+00:00", sources=sources)
        # Shift t to before the lineup was posted but after the probable:
        # the lineup-dependent features must vanish, not change value.
        partial = F.build_features(
            "999", "2026-04-01T17:30:00+00:00", sources=sources)
        self.assertEqual(partial, {})
        # Further still: before either was known.
        earliest = F.build_features(
            "999", "2026-04-01T16:00:00+00:00", sources=sources)
        self.assertEqual(earliest, {})
        # Every key present at the earlier instants is also present at the
        # later one, with an IDENTICAL value -- shifting t later than an
        # already-present instant cannot retroactively change a number.
        for key, fv in partial.items():
            self.assertEqual(full[key].value, fv.value)

    def test_missing_probable_leaves_feature_absent_not_defaulted(self):
        _write_jsonl(self.lineups_path, [
            {"game_pk": 999, "observed_utc": "2026-04-01T18:00:00+00:00",
             "away_lineup": [111, 112], "home_lineup": [211, 212]},
        ])
        # No probables_watch row at all.
        sources = F.FeatureSources(as_of_stores=[self._stores()[0]],
                                   handedness=self.handedness)
        values = F.build_features("999", "2026-04-01T19:00:00+00:00", sources=sources)
        self.assertEqual(values, {})

    def test_unknown_handedness_leaves_feature_absent(self):
        self._seed()
        sources = F.FeatureSources(as_of_stores=self._stores(), handedness={})
        values = F.build_features("999", "2026-04-01T19:00:00+00:00", sources=sources)
        self.assertEqual(values, {})

    def test_deterministic_ordering_across_repeated_calls(self):
        self._seed()
        sources = F.FeatureSources(as_of_stores=self._stores(),
                                   handedness=self.handedness)
        first = F.build_features("999", "2026-04-01T19:00:00+00:00", sources=sources)
        second = F.build_features("999", "2026-04-01T19:00:00+00:00", sources=sources)
        self.assertEqual(list(first.items()), list(second.items()))
        self.assertEqual(sorted(first), ["away_lineup_platoon_share",
                                         "home_lineup_platoon_share"])


class TestPriceBlindness(unittest.TestCase):
    """No odds/price store path is ever opened while building features --
    on either the live or the replay branch."""

    PRICE_MARKERS = ("l1_observations", "odds_multibook", "odds_snapshots",
                     "f5_close", "prop_listing", "prop_prices",
                     "batter_props", "derivative_markets")

    def _opened_paths(self, fn):
        opened = []
        real_open = Path.open

        def spy_open(self_path, *a, **kw):
            opened.append(str(self_path))
            return real_open(self_path, *a, **kw)

        Path.open = spy_open
        try:
            fn()
        finally:
            Path.open = real_open
        return opened

    def test_replay_branch_never_opens_a_price_store(self):
        opened = self._opened_paths(
            lambda: F.build_features("718781", "2023-03-30T16:45:39+00:00"))
        self.assertTrue(opened, "sanity: the replay branch should read something")
        for path in opened:
            for marker in self.PRICE_MARKERS:
                self.assertNotIn(marker, path, f"{path} looks price-shaped")

    def test_live_branch_never_opens_a_price_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lineups_path = Path(tmp.name) / "lineups_watch.jsonl"
        probables_path = Path(tmp.name) / "probables_watch.jsonl"
        _write_jsonl(lineups_path, [
            {"game_pk": 999, "observed_utc": "2026-04-01T18:00:00+00:00",
             "away_lineup": [111, 112], "home_lineup": [211, 212]}])
        _write_jsonl(probables_path, [
            {"game_pk": 999, "observed_utc": "2026-04-01T17:00:00+00:00",
             "away_probable_id": 500, "home_probable_id": 600}])
        stores = [
            asof_module.StoreSpec(
                name="lineups_watch", path=lineups_path,
                game_key_of=_pk, time_of=_obs,
                fields={"home_lineup": lambda r: r.get("home_lineup") or None,
                        "away_lineup": lambda r: r.get("away_lineup") or None}),
            asof_module.StoreSpec(
                name="probables_watch", path=probables_path,
                game_key_of=_pk, time_of=_obs,
                fields={"home_probable_id": lambda r: r.get("home_probable_id"),
                        "away_probable_id": lambda r: r.get("away_probable_id")}),
        ]
        handedness = {"500": {"throws": "L"}, "600": {"throws": "R"},
                      "111": {"bats": "R"}, "112": {"bats": "L"},
                      "211": {"bats": "R"}, "212": {"bats": "R"}}
        sources = F.FeatureSources(as_of_stores=stores, handedness=handedness)
        opened = self._opened_paths(
            lambda: F.build_features("999", "2026-04-01T19:00:00+00:00",
                                     sources=sources))
        self.assertTrue(opened, "sanity: the live branch should read something")
        for path in opened:
            for marker in self.PRICE_MARKERS:
                self.assertNotIn(marker, path, f"{path} looks price-shaped")

    def test_glue_build_snapshot_never_opens_a_price_store_while_featuring(self):
        # build_snapshot's own L1/price read happens through build_board, a
        # SEPARATE call this test never makes; this isolates that
        # build_snapshot's feature-building half specifically stays
        # price-blind even when it is handed a real game_pk.
        opened = self._opened_paths(
            lambda: glue.build_snapshot(
                glue.GameRef(event_id="evt1", game_pk="718781"),
                "2023-03-30T16:45:39+00:00"))
        for path in opened:
            for marker in self.PRICE_MARKERS:
                self.assertNotIn(marker, path, f"{path} looks price-shaped")


class TestGlueIntegration(unittest.TestCase):
    """build_snapshot populates PriceBlindSnapshot.features/assumption_exposure
    from build_features end to end, for a real 2023 game_pk."""

    def test_features_and_exposure_populated_for_a_real_2023_game(self):
        ref = glue.GameRef(event_id="evt-718781", game_pk="718781")
        snapshot = glue.build_snapshot(ref, "2023-03-30T16:45:39+00:00")
        self.assertEqual(snapshot.features.get("away_lineup_platoon_share"), 0.667)
        self.assertEqual(snapshot.features.get("home_lineup_platoon_share"), 0.222)
        self.assertIn("D:away_lineup_platoon_share", snapshot.assumption_exposure)
        self.assertIn("D:home_lineup_platoon_share", snapshot.assumption_exposure)

    def test_explicit_features_argument_still_wins(self):
        ref = glue.GameRef(event_id="evt-718781", game_pk="718781")
        snapshot = glue.build_snapshot(
            ref, "2023-03-30T16:45:39+00:00", features={"away_x": 9.0})
        self.assertEqual(dict(snapshot.features), {"away_x": 9.0})


if __name__ == "__main__":
    unittest.main()
