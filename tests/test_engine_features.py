"""Tests for src/engine/features.py: the one feature builder both the live
engine and the historical replay share.

Matrix-equivalence runs against the REAL, tracked
`data/research/matchup_matrix_2023.jsonl` and the real historical primitives
(`data/historical/{mlb_results.csv,lineups.jsonl,handedness.json,statcast/}`
-- copied read-only into this worktree for this session; see the task
report for sha256s) that produced it, per the task's own instruction not to
fabricate a synthetic stand-in for the one thing this test exists to prove.
Every other test in this file builds tiny synthetic stores under a tempdir,
exactly like tests/test_asof.py and tests/test_matrix.py, so the rest of
the suite stays hermetic and fast (a full walk of the real ~4M-row pitch
store measures ~27s -- see the task report -- which is why only the two
early-2023 cutoffs the equivalence test needs, both under 1.2s, touch the
real store at all).
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from src.core import asof as asof_module
from src.engine import features as F
from src.engine import glue
from src.research import funnel

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


def _write_statcast_store(root: Path, rows: list, window: str) -> Path:
    store = root / "statcast"
    store.mkdir(parents=True, exist_ok=True)
    name = f"pitches_{window}.jsonl.gz"
    with gzip.open(store / name, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    manifest_path = store / "manifest.json"
    manifest = {"windows": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["windows"][window] = {"rows": len(rows), "file": name}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return store


class TestFeatureAccounting(unittest.TestCase):
    """The exclusion accounting is exhaustive against the matrix's own
    registered numeric columns -- if matrix.py or funnel.py ever
    grows/shrinks a column, this fails instead of silently going stale."""

    def test_all_seven_numeric_matrix_columns_are_reproducible(self):
        self.assertEqual(set(F.REPRODUCIBLE_FEATURES), set(funnel.NUMERIC_FEATURES))

    def test_unavailable_features_is_empty(self):
        # The bar is now "the primitive genuinely does not exist" -- nothing
        # numeric that matrix.py computes meets that bar today.
        self.assertEqual(F.UNAVAILABLE_FEATURES, ())

    def test_feature_specs_names_are_exactly_the_reproducible_set(self):
        self.assertEqual(
            {spec.name for spec in F.FEATURE_SPECS}, set(F.REPRODUCIBLE_FEATURES))

    def test_live_capture_start_matches_asof_exactly(self):
        # A private constant duplicated deliberately (see module docstring);
        # this is the guard against the two ever drifting onto different
        # eras unnoticed.
        self.assertEqual(F._LIVE_CAPTURE_START, asof_module._LIVE_CAPTURE_START)


class TestMatrixEquivalenceReal2023(unittest.TestCase):
    """build_features, on the real historical primitives (including the
    real pitch store), reproduces the real matchup-matrix row's values
    exactly -- absences included."""

    def test_game_718781_only_lineup_platoon_share_present(self):
        # Cutoff "2023-03-01" is before the store's first pitch: every
        # rebuilt-derived feature is genuinely absent (0 pre-cutoff data),
        # matching the matrix row's own null columns exactly.
        row = _real_matrix_row("718781")
        self.assertEqual(row["away_lineup_platoon_share"], 0.667)
        self.assertEqual(row["home_lineup_platoon_share"], 0.222)
        for name in F.PITCH_ACCUMULATOR_FEATURES:
            self.assertIsNone(row[f"away_{name}"])
            self.assertIsNone(row[f"home_{name}"])

        values = F.build_features("718781", row["start_time_utc"])

        self.assertEqual(set(values), {"away_lineup_platoon_share",
                                       "home_lineup_platoon_share"})
        self.assertEqual(values["away_lineup_platoon_share"].value, 0.667)
        self.assertEqual(values["home_lineup_platoon_share"].value, 0.222)

    def test_game_718339_all_seven_features_both_sides(self):
        # A game deep enough into the season that every away-side feature
        # clears its rebuilt sample floor, and home is a genuine mixed
        # bag (some present, some absent) -- the strongest single proof
        # available that this module's wiring, not just its lineup-share
        # sliver, reproduces src.research.matrix.row_for_game exactly.
        row = _real_matrix_row("718339")
        values = F.build_features("718339", row["start_time_utc"])

        for side in ("away", "home"):
            for name in F.REPRODUCIBLE_FEATURES:
                key = f"{side}_{name}"
                expected = row[key]
                if expected is None:
                    self.assertNotIn(
                        key, values,
                        f"{key} should be absent (matrix has null)")
                else:
                    self.assertIn(key, values, f"{key} should be present")
                    self.assertEqual(
                        values[key].value, expected,
                        f"{key}: {values[key].value} != matrix's {expected}")

        # Sanity: this game actually exercises every feature on the away
        # side (a vacuously-passing all-None loop above would prove nothing).
        self.assertEqual(
            {name for name in F.REPRODUCIBLE_FEATURES
             if f"away_{name}" in values},
            set(F.REPRODUCIBLE_FEATURES))

    def test_every_returned_value_is_grade_d_for_2023(self):
        row = _real_matrix_row("718339")
        values = F.build_features("718339", row["start_time_utc"])
        self.assertTrue(values)
        for fv in values.values():
            self.assertEqual(fv.known_at_grade, asof_module.GRADE_D)
            self.assertIsNone(fv.known_at)

    def test_unknown_game_pk_is_honestly_empty(self):
        self.assertEqual(F.build_features("999999999999", "2023-04-01T00:00:00Z"), {})


# ---------------------------------------------------------------------------
# Live path: synthetic lineup/probable stores AND a synthetic pitch store,
# so these tests stay fast and hermetic (see module docstring).
# ---------------------------------------------------------------------------

LIVE_WINDOW = "2026-08-01..2026-08-04"
GAME_DATE = "2026-08-02"       # the day every synthetic pitch below is dated
PITCHER_500 = "500"            # home's probable -- away lineup faces him
PITCHER_600 = "600"            # away's probable -- below every sample floor


def _pitch(pitcher, batter=None, stand=None, pitch_type=None, value=None,
          events=None, release_speed=None, bb_type=None,
          game_date=GAME_DATE, game_pk="9001"):
    row = {"game_date": game_date, "game_pk": game_pk, "pitcher": pitcher}
    if batter is not None:
        row["batter"] = batter
    if stand is not None:
        row["stand"] = stand
    if pitch_type is not None:
        row["pitch_type"] = pitch_type
    if value is not None:
        row["woba_value"] = value
        row["woba_denom"] = "1"
    if events is not None:
        row["description"] = "hit_into_play"
        row["events"] = events
    if release_speed is not None:
        row["release_speed"] = release_speed
    if bb_type is not None:
        row["bb_type"] = bb_type
    return row


def _rich_pitcher_500_rows(game_date=GAME_DATE) -> list:
    """Enough pitches for pitcher 500 to clear every one of rebuilt's
    sample floors at once: platoon split (>=60 BF/side), pitch mix
    (>=50 pitches), fastball velocity (>=100 measured FF), groundball
    share (>=50 batted balls). Exact numbers are not hand-asserted here --
    the real-data equivalence tests above already prove the arithmetic
    against a real matrix row; this fixture only proves the WIRING (every
    feature name shows up, absence/leak rules hold)."""
    rows = []
    for i in range(60):  # vs L: away top order 9001-9004
        hot = i < 20
        rows.append(_pitch(PITCHER_500, str(9001 + i % 4), "L", "FF",
                           "0.9" if hot else "0.0",
                           "single" if hot else "field_out",
                           game_date=game_date))
    for i in range(60):  # vs R: away bottom order 9005-9009
        hot = i < 10
        rows.append(_pitch(PITCHER_500, str(9005 + i % 5), "R", "FF",
                           "0.9" if hot else "0.0",
                           "single" if hot else "field_out",
                           game_date=game_date))
    # 20 extra non-PA FF pitches (no woba_denom) purely to clear the
    # 100-measured-fastball velocity floor without disturbing the platoon
    # PA counts/wOBA above (80 -> 100).
    for _ in range(20):
        rows.append(_pitch(PITCHER_500, pitch_type="FF", release_speed=94.0,
                           game_date=game_date))
    # Give every FF row above a release_speed too (velocity accumulates
    # per-row, not per-PA).
    for row in rows:
        if row.get("pitch_type") == "FF" and "release_speed" not in row:
            row["release_speed"] = 95.0
    # 55 batted balls (bb_type only) to clear the 50-batted-ball groundball
    # floor: 30 grounders, 25 fly balls -> share 30/55.
    for _ in range(30):
        rows.append(_pitch(PITCHER_500, bb_type="ground_ball", game_date=game_date))
    for _ in range(25):
        rows.append(_pitch(PITCHER_500, bb_type="fly_ball", game_date=game_date))
    return rows


def _thin_pitcher_600_rows(game_date=GAME_DATE) -> list:
    """Pitcher 600: 10 PA vs L only -- below every rebuilt floor on purpose,
    proving those six features stay absent rather than defaulted when a
    real primitive exists but is too thin."""
    return [_pitch(PITCHER_600, "9101", "L", "FF", "0.0", "field_out",
                   game_date=game_date) for _ in range(10)]


HANDEDNESS = {
    "9001": {"bats": "R"}, "9002": {"bats": "R"}, "9003": {"bats": "R"},
    "9004": {"bats": "R"}, "9005": {"bats": "R"}, "9006": {"bats": "R"},
    "9007": {"bats": "R"}, "9008": {"bats": "R"}, "9009": {"bats": "R"},
    "9101": {"bats": "L"},
    "500": {"throws": "L"}, "600": {"throws": "R"},
}


class LiveFeatureTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.lineups_path = self.tmp / "lineups_watch.jsonl"
        self.probables_path = self.tmp / "probables_watch.jsonl"

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

    def _seed_lineups_and_probables(self, observed="2026-08-02T18:00:00+00:00"):
        # Away lineup (faces home's probable, 500), home lineup (faces
        # away's probable, 600, deliberately below every floor).
        away_ids = list(range(9001, 9010))
        home_ids = [9101] + list(range(9201, 9209))
        _write_jsonl(self.lineups_path, [
            {"game_pk": 999, "observed_utc": observed,
             "away_lineup": away_ids, "home_lineup": home_ids}])
        _write_jsonl(self.probables_path, [
            {"game_pk": 999, "observed_utc": observed,
             "away_probable_id": PITCHER_600, "home_probable_id": PITCHER_500}])

    def _sources(self, statcast_store, handedness=None):
        return F.FeatureSources(
            as_of_stores=self._stores(), statcast_store=statcast_store,
            handedness=handedness if handedness is not None else HANDEDNESS)


class TestSixPitchAccumulatorFeaturesLive(LiveFeatureTestBase):
    def test_away_side_gets_all_six_home_side_gets_none(self):
        # cutoff = date(t) = 2026-08-03; the pitch store's coverage
        # (window ending 2026-08-04, but every synthetic row is dated
        # 2026-08-02, strictly before cutoff) reaches through the day
        # before cutoff, so this should grade A.
        store = _write_statcast_store(
            self.tmp, _rich_pitcher_500_rows() + _thin_pitcher_600_rows(),
            LIVE_WINDOW)
        self._seed_lineups_and_probables()
        sources = self._sources(store)
        values = F.build_features("999", "2026-08-03T19:00:00+00:00", sources=sources)

        for name in F.PITCH_ACCUMULATOR_FEATURES:
            self.assertIn(f"away_{name}", values, f"away_{name} missing")
            # Pitcher 600 (home's probable) is deliberately below every
            # rebuilt floor, and none of the home lineup's own batters ever
            # appear in a measured pitch row either -- every one of the six
            # must be honestly absent, not defaulted, on the home side.
            self.assertNotIn(
                f"home_{name}", values,
                f"home_{name} should be absent (thin/no primitive data)")

        for fv in values.values():
            self.assertEqual(fv.known_at_grade, asof_module.GRADE_A)
            self.assertIsNotNone(fv.known_at)

    def test_missing_pitch_store_leaves_six_features_absent_not_defaulted(self):
        self._seed_lineups_and_probables()
        empty_store = self.tmp / "no_such_statcast_dir"
        sources = self._sources(empty_store)
        values = F.build_features("999", "2026-08-03T19:00:00+00:00", sources=sources)
        for name in F.PITCH_ACCUMULATOR_FEATURES:
            self.assertNotIn(f"away_{name}", values)
            self.assertNotIn(f"home_{name}", values)
        # lineup_platoon_share has no pitch-store dependency at all.
        self.assertIn("away_lineup_platoon_share", values)


class TestFreshnessGrading(LiveFeatureTestBase):
    """The pitch store's own coverage bound, never `t`, decides freshness."""

    def test_store_current_through_day_before_t_grades_a(self):
        store = _write_statcast_store(self.tmp, _rich_pitcher_500_rows(),
                                      "2026-08-01..2026-08-02")
        self._seed_lineups_and_probables()
        sources = self._sources(store)
        values = F.build_features("999", "2026-08-03T12:00:00+00:00", sources=sources)
        fv = values["away_starter_groundball_share"]
        self.assertEqual(fv.known_at_grade, asof_module.GRADE_A)
        self.assertEqual(fv.known_at, "2026-08-02")

    def test_stale_store_grades_d_and_reports_true_coverage_not_t(self):
        # Coverage ends 2026-07-20, well behind t's own day (2026-08-03) --
        # a real, measured lag (the actual store's newest window today ends
        # 2026-08-27, see the module docstring). observed_utc must be the
        # coverage bound, never t or the day before t.
        store = _write_statcast_store(
            self.tmp, _rich_pitcher_500_rows(game_date="2026-07-19"),
            "2026-07-17..2026-07-20")
        self._seed_lineups_and_probables()
        sources = self._sources(store)
        values = F.build_features("999", "2026-08-03T12:00:00+00:00", sources=sources)
        fv = values["away_starter_groundball_share"]
        self.assertEqual(fv.known_at_grade, asof_module.GRADE_D)
        self.assertIsNone(fv.known_at)
        self.assertEqual(fv.observed_utc, "2026-07-20")
        self.assertNotIn("2026-08-03", fv.observed_utc)


class TestNoLeakage(LiveFeatureTestBase):
    def test_a_pitch_dated_on_ts_own_day_never_contributes(self):
        """The direct proof: seeding a store with (a) the same rows a
        passing run uses, dated strictly before cutoff, and (b) a second,
        much larger batch of ground-ball rows dated ON `t`'s own calendar
        day, produces IDENTICAL output to (a) alone -- the leaking batch
        would otherwise swing the groundball share from 30/55 to 80/105."""
        clean_rows = _rich_pitcher_500_rows()  # dated GAME_DATE = 2026-08-02
        leaking_rows = [
            _pitch(PITCHER_500, bb_type="ground_ball", game_date="2026-08-03")
            for _ in range(50)
        ]  # dated ON t's own day (t below is 2026-08-03T19:00Z)
        self._seed_lineups_and_probables()

        store_clean = _write_statcast_store(
            self.tmp / "clean", clean_rows, "2026-08-01..2026-08-02")
        clean = F.build_features(
            "999", "2026-08-03T19:00:00+00:00", sources=self._sources(store_clean))

        store_with_leak = _write_statcast_store(
            self.tmp / "leak", clean_rows + leaking_rows, "2026-08-01..2026-08-03")
        leaked = F.build_features(
            "999", "2026-08-03T19:00:00+00:00", sources=self._sources(store_with_leak))

        self.assertEqual(
            clean["away_starter_groundball_share"].value,
            leaked["away_starter_groundball_share"].value)
        self.assertEqual(clean["away_starter_groundball_share"].value,
                         round(30 / 55, 4))


class TestEasternCutoffB5(LiveFeatureTestBase):
    """B5 regression: the cutoff must be `t`'s own EASTERN calendar day
    (matching `src.pipeline.snapshots.official_date`, what slate membership
    keys on), never its bare UTC day. `t=2026-09-01T00:02:08Z` -- a real
    shape from the published ledger's own decisions -- is `2026-08-31
    20:02:08` Eastern: the game's own official date is `2026-08-31`, one
    calendar day EARLIER than `t`'s UTC date. Before the fix, `cutoff_date
    = t_dt.date().isoformat()` produced `2026-09-01`, so `game_date <
    cutoff` admitted every pitch dated `2026-08-31` -- the game's own
    official date, including a game still in progress at `t` or, on a
    backfilled run, the subject game itself."""

    def test_eastern_date_of_a_00_to_04z_instant_is_the_prior_calendar_day(self):
        # Direct unit proof of the helper the fix introduces.
        t_dt = F._parse_utc("2026-09-01T00:02:08+00:00")
        self.assertEqual(F._eastern_date(t_dt), "2026-08-31")

    def test_no_pitch_from_ts_own_official_eastern_date_reaches_features(self):
        t = "2026-09-01T00:02:08+00:00"  # Eastern: 2026-08-31T20:02:08
        clean_rows = _rich_pitcher_500_rows(game_date="2026-08-29")
        # Dated on t's own OFFICIAL (Eastern) date, 2026-08-31 -- under the
        # bare-UTC bug this is STRICTLY BEFORE the wrong cutoff
        # (2026-09-01) and would leak straight in.
        leaking_rows = [
            _pitch(PITCHER_500, bb_type="ground_ball", game_date="2026-08-31")
            for _ in range(50)
        ]
        self._seed_lineups_and_probables(observed="2026-08-31T18:00:00+00:00")

        store_clean = _write_statcast_store(
            self.tmp / "clean", clean_rows, "2026-08-28..2026-08-30")
        clean = F.build_features("999", t, sources=self._sources(store_clean))

        store_with_leak = _write_statcast_store(
            self.tmp / "leak", clean_rows + leaking_rows, "2026-08-28..2026-08-31")
        leaked = F.build_features("999", t, sources=self._sources(store_with_leak))

        # No leak: identical output with or without the game's-own-date rows.
        self.assertEqual(
            clean["away_starter_groundball_share"].value,
            leaked["away_starter_groundball_share"].value)
        self.assertEqual(clean["away_starter_groundball_share"].value,
                         round(30 / 55, 4))

        # The grade must not assert knowledge of 2026-08-31 (t's own
        # official date, not yet finished at t) -- known_at is the day
        # BEFORE the correct Eastern cutoff, 2026-08-30, never 2026-08-31
        # (what the UTC-day bug's day_before_cutoff would have been).
        fv = leaked["away_starter_groundball_share"]
        self.assertEqual(fv.known_at_grade, asof_module.GRADE_A)
        self.assertEqual(fv.known_at, "2026-08-30")
        self.assertNotEqual(fv.known_at, "2026-08-31")


class TestPriceBlindness(unittest.TestCase):
    """No odds/price store path is ever opened while building features --
    on either the live or the replay branch, including the new pitch-store
    reads."""

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
        row = _real_matrix_row("718339")
        opened = self._opened_paths(
            lambda: F.build_features("718339", row["start_time_utc"]))
        self.assertTrue(opened, "sanity: the replay branch should read something")
        for path in opened:
            for marker in self.PRICE_MARKERS:
                self.assertNotIn(marker, path, f"{path} looks price-shaped")

    def test_live_branch_never_opens_a_price_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        lineups_path = root / "lineups_watch.jsonl"
        probables_path = root / "probables_watch.jsonl"
        observed = "2026-08-02T18:00:00+00:00"
        _write_jsonl(lineups_path, [
            {"game_pk": 999, "observed_utc": observed,
             "away_lineup": list(range(9001, 9010)),
             "home_lineup": [9101] + list(range(9201, 9209))}])
        _write_jsonl(probables_path, [
            {"game_pk": 999, "observed_utc": observed,
             "away_probable_id": PITCHER_600, "home_probable_id": PITCHER_500}])
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
        store = _write_statcast_store(root, _rich_pitcher_500_rows(), LIVE_WINDOW)
        sources = F.FeatureSources(as_of_stores=stores, statcast_store=store,
                                   handedness=HANDEDNESS)
        opened = self._opened_paths(
            lambda: F.build_features("999", "2026-08-03T19:00:00+00:00",
                                     sources=sources))
        self.assertTrue(opened, "sanity: the live branch should read something")
        for path in opened:
            for marker in self.PRICE_MARKERS:
                self.assertNotIn(marker, path, f"{path} looks price-shaped")

    def test_glue_build_snapshot_never_opens_a_price_store_while_featuring(self):
        opened = self._opened_paths(
            lambda: glue.build_snapshot(
                glue.GameRef(event_id="evt1", game_pk="718339"),
                _real_matrix_row("718339")["start_time_utc"]))
        for path in opened:
            for marker in self.PRICE_MARKERS:
                self.assertNotIn(marker, path, f"{path} looks price-shaped")


class TestGlueIntegration(unittest.TestCase):
    """build_snapshot populates PriceBlindSnapshot.features/assumption_exposure
    from build_features end to end, for a real 2023 game_pk."""

    def test_features_and_exposure_populated_for_a_real_2023_game(self):
        row = _real_matrix_row("718339")
        ref = glue.GameRef(event_id="evt-718339", game_pk="718339")
        snapshot = glue.build_snapshot(ref, row["start_time_utc"])
        self.assertEqual(
            snapshot.features.get("away_starter_velocity_gap"),
            row["away_starter_velocity_gap"])
        self.assertIn("D:away_starter_velocity_gap", snapshot.assumption_exposure)
        self.assertIn("D:away_lineup_platoon_share", snapshot.assumption_exposure)

    def test_explicit_features_argument_still_wins(self):
        ref = glue.GameRef(event_id="evt-718339", game_pk="718339")
        snapshot = glue.build_snapshot(
            ref, "2023-05-02T00:00:00Z", features={"away_x": 9.0})
        self.assertEqual(dict(snapshot.features), {"away_x": 9.0})


if __name__ == "__main__":
    unittest.main()
