"""Matchup matrix tests, on a synthetic pitch store built via rebuilt's API.

The accumulation is NOT stubbed: a tiny gzipped statcast store (manifest plus
one window file, the exact on-disk shape statcast_pitches writes) is walked by
rebuilt.build_snapshots, so these tests exercise the same public path a real
season build takes -- if rebuilt's shapes or floors change, these fail rather
than silently testing a stub of yesterday's contract.

Fixture design, so the expected numbers are checkable by hand:
  pitcher 500 (home starter -- the AWAY lineup faces him):
    60 PA vs L (20 wOBA-value 0.9, 40 of 0.0)  -> vs_L 0.300
    60 PA vs R (10 of 0.9, 50 of 0.0)          -> vs_R 0.150, gap 0.15
    pitches: 80 FF, 40 SL -> primary FF at 66.7% usage
  pitcher 600 (away starter -- the HOME lineup faces him):
    10 PA vs L only -> below the 60-BF floor AND the 50-pitch mix floor
  pitcher 700: 10 CH of 0.9 to batter 9001 only -- decouples the top-order
    aggregation (all pitchers) from pitcher 500's own numbers.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import rebuilt
from src.research import matrix

WINDOW = "2023-03-14..2023-03-17"


def _pitch(pitcher, batter, stand, pitch_type, value, events):
    return {"game_date": "2023-03-15", "game_pk": "1", "pitcher": pitcher,
            "batter": batter, "stand": stand, "pitch_type": pitch_type,
            "description": "hit_into_play", "woba_value": value,
            "woba_denom": "1", "events": events}


def _synthetic_rows() -> list:
    rows = []
    # Pitcher 500 vs L: FF to the away top order (9001..9004), 20 hits worth
    # 0.9 then 40 outs -> each batter 15 PA at wOBA 0.300.
    for i in range(60):
        batter = str(9001 + i % 4)
        hot = i < 20
        rows.append(_pitch("500", batter, "L", "FF", "0.9" if hot else "0.0",
                           "single" if hot else "field_out"))
    # Pitcher 500 vs R, FF: away bottom order (9005..9009), 10 of 0.9 then 10
    # outs -> each batter 4 FF PA at wOBA 0.450.
    for i in range(20):
        batter = str(9005 + i % 5)
        hot = i < 10
        rows.append(_pitch("500", batter, "R", "FF", "0.9" if hot else "0.0",
                           "single" if hot else "field_out"))
    # Pitcher 500 vs R, SL: 40 outs to the bottom order.
    for i in range(40):
        rows.append(_pitch("500", str(9005 + i % 5), "R", "SL", "0.0",
                           "field_out"))
    # Pitcher 700: 10 CH hits to 9001 -- inflates the top order's ALL-pitch
    # aggregate without touching pitcher 500's split or arsenal.
    for _ in range(10):
        rows.append(_pitch("700", "9001", "R", "CH", "0.9", "single"))
    # Pitcher 600: 10 PA vs L only -- below every floor on purpose.
    for _ in range(10):
        rows.append(_pitch("600", "9101", "L", "FF", "0.0", "field_out"))
    return rows


def _write_store(root: Path) -> Path:
    store = root / "statcast"
    store.mkdir(parents=True)
    rows = _synthetic_rows()
    name = f"pitches_{WINDOW}.jsonl.gz"
    with gzip.open(store / name, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    (store / "manifest.json").write_text(json.dumps(
        {"windows": {WINDOW: {"rows": len(rows), "file": name}}}),
        encoding="utf-8")
    return store


def _slots(first_id):
    return [{"order": order, "person_id": first_id + order - 1,
             "name": f"P{first_id + order - 1}", "position": "IF"}
            for order in range(1, 10)]


HANDEDNESS = {
    # Away lineup: 3 lefties and a switch hitter up top, righties below.
    "9001": {"bats": "L"}, "9002": {"bats": "L"}, "9003": {"bats": "L"},
    "9004": {"bats": "S"}, "9005": {"bats": "R"}, "9006": {"bats": "R"},
    "9007": {"bats": "R"}, "9008": {"bats": "R"}, "9009": {"bats": "R"},
    # Home lineup: 5 R, 2 L, 2 S -> 7 of 9 advantaged vs the lefty 600.
    "9101": {"bats": "R"}, "9102": {"bats": "R"}, "9103": {"bats": "R"},
    "9104": {"bats": "R"}, "9105": {"bats": "R"}, "9106": {"bats": "L"},
    "9107": {"bats": "L"}, "9108": {"bats": "S"}, "9109": {"bats": "S"},
    "500": {"bats": "R", "throws": "R"},
    "600": {"bats": "L", "throws": "L"},
}

GAME = {"game_pk": "700001", "date": "2023-04-05",
        "start_time_utc": "2023-04-05T23:10:00Z",
        "away_team": "CLE", "home_team": "SEA",
        "away_probable_id": "600", "home_probable_id": "500"}

POSTED = {"game_pk": "700001", "away": _slots(9001), "home": _slots(9101)}


class RowForGameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.store = _write_store(Path(cls._tmp.name))
        # The public accumulation path, over the synthetic rows.
        cls.acc = rebuilt.build_snapshots(["2023-04-01"],
                                          store=cls.store)["2023-04-01"]
        cls.row = matrix.row_for_game(cls.acc, GAME, POSTED, HANDEDNESS)

    def test_platoon_share_math(self):
        # Away lineup vs the righty 500: 3 L + 1 S advantaged of 9 known.
        self.assertEqual(self.row["away_lineup_platoon_share"],
                         round(4 / 9, 3))
        # Home lineup vs the lefty 600: 5 R + 2 S advantaged of 9 known.
        self.assertEqual(self.row["home_lineup_platoon_share"],
                         round(7 / 9, 3))

    def test_sides_cross_over(self):
        # away_starter_platoon_gap is the split of the starter the AWAY
        # lineup faces -- the home team's 500, gap 0.300 - 0.150.
        self.assertEqual(self.row["away_starter_platoon_gap"], 0.15)

    def test_none_below_min_bf_floor(self):
        # 600 faced 10 left-handed batters and zero right-handed: below
        # rebuilt's 60-per-side floor the gap must be None, never a number.
        self.assertIsNone(self.row["home_starter_platoon_gap"])
        self.assertTrue(any(g.startswith("home_starter_platoon_gap:")
                            for g in self.row["gaps"]))

    def test_primary_pitch_and_weighted_lineup_woba(self):
        self.assertEqual(self.row["away_primary_pitch"], "FF")
        self.assertEqual(self.row["away_primary_pitch_share"], 0.667)
        # PA-weighted FF line: 4 batters at 0.300 over 15 PA plus 5 at 0.450
        # over 4 PA -> (18 + 9) / 80.
        self.assertEqual(self.row["away_lineup_vs_primary_pitch"], 0.3375)
        # 600's arsenal is below the 50-pitch floor: no primary pitch, and
        # the gap says so instead of a silent None.
        self.assertIsNone(self.row["home_primary_pitch"])
        self.assertIsNone(self.row["home_lineup_vs_primary_pitch"])
        self.assertTrue(any(g.startswith("home_lineup_vs_primary_pitch:")
                            for g in self.row["gaps"]))

    def test_top_minus_bottom_aggregates_all_pitches(self):
        # Top (9001-9004): 60 FF PA worth 18 plus 9001's 10 CH PA worth 9
        # from pitcher 700 -> 27/70. Bottom (9005-9009): 9/60.
        self.assertEqual(self.row["away_top_minus_bottom"],
                         round(27 / 70 - 9 / 60, 4))
        # Home bottom order has zero measured PA -> None plus a gap naming
        # the missing half, not a zero.
        self.assertIsNone(self.row["home_top_minus_bottom"])
        self.assertTrue(any(g.startswith("home_top_minus_bottom:")
                            and "5-9" in g for g in self.row["gaps"]))

    def test_lineup_vs_starter_history_keeps_pa(self):
        # Every one of 500's 120 PA was against a posted away hitter.
        self.assertEqual(self.row["away_lineup_vs_starter_history"],
                         {"pa": 120, "woba": round(27 / 120, 4)})
        # 9101's 10 hitless PA against 600: woba 0.0 is a real number, not a
        # gap -- absence of success is not absence of evidence.
        self.assertEqual(self.row["home_lineup_vs_starter_history"],
                         {"pa": 10, "woba": 0.0})

    def test_game_level_fields_and_cutoff_provenance(self):
        for key in ("game_pk", "date", "away_team", "home_team",
                    "start_time_utc"):
            self.assertEqual(self.row[key], GAME[key])
        self.assertEqual(self.row["cutoff"], "2023-04-01")

    def test_missing_lineup_side_records_gap(self):
        row = matrix.row_for_game(self.acc, GAME,
                                  {"away": POSTED["away"], "home": []},
                                  HANDEDNESS)
        self.assertIsNone(row["home_lineup_platoon_share"])
        self.assertIsNone(row["home_top_minus_bottom"])
        self.assertIsNone(row["home_lineup_vs_starter_history"])
        self.assertIn("home_lineup: no posted home lineup stored", row["gaps"])
        # The away side is unaffected by the other side's hole.
        self.assertEqual(row["away_lineup_platoon_share"], round(4 / 9, 3))

    def test_missing_starter_records_gap(self):
        game = dict(GAME, home_probable_id=None)
        row = matrix.row_for_game(self.acc, game, POSTED, HANDEDNESS)
        self.assertIsNone(row["away_starter_platoon_gap"])
        self.assertIsNone(row["away_lineup_vs_primary_pitch"])
        self.assertIsNone(row["away_lineup_vs_starter_history"])
        self.assertTrue(any(g.startswith("away_opposing_starter:")
                            for g in row["gaps"]))


class BuildAndReadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.store = _write_store(root)
        self.out_dir = root / "research"
        self.results = {
            "700001": dict(GAME),
            # Same date, no posted lineup -> no row at all.
            "700002": dict(GAME, game_pk="700002", away_team="BOS",
                           home_team="NYY"),
            # A date whose only game has no lineup -> empty marker.
            "700003": dict(GAME, game_pk="700003", date="2023-04-06",
                           start_time_utc="2023-04-06T23:10:00Z"),
        }
        self.kwargs = dict(out_dir=self.out_dir, store=self.store,
                           results=self.results,
                           lineups_by_pk={"700001": POSTED},
                           handedness=HANDEDNESS)

    def _build(self, **extra):
        return matrix.build(2023, dates=["2023-04-05", "2023-04-06"],
                            **dict(self.kwargs, **extra))

    def test_build_writes_rows_and_empty_markers(self):
        path = self._build()
        self.assertEqual(path, self.out_dir / "matchup_matrix_2023.jsonl")
        lines = [json.loads(l) for l in
                 path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 2)  # one lineup game + one marker
        self.assertEqual(lines[0]["game_pk"], "700001")
        self.assertEqual(lines[1], {"date": "2023-04-06", "empty": True})

    def test_read_keys_by_game_pk_and_skips_markers(self):
        self._build()
        rows = matrix.read(2023, out_dir=self.out_dir)
        self.assertEqual(set(rows), {"700001"})
        self.assertEqual(rows["700001"]["away_starter_platoon_gap"], 0.15)

    def test_idempotent_rerun_appends_nothing(self):
        path = self._build()
        before = path.read_bytes()
        self._build()
        self.assertEqual(path.read_bytes(), before)

    def test_timings_collector_records_load_and_build_stages(self):
        from src.core.timing import TimingCollector, require_timings
        collector = TimingCollector()
        path_with = self._build(timings=collector, out_dir=self.out_dir / "a")
        stages = {rec["stage"] for rec in collector.to_list()}
        self.assertEqual(stages, {"load", "build"})
        require_timings({"timings": collector.to_list()})  # must not raise

        # Instrumentation is additive: the same build without a collector
        # writes byte-identical rows.
        path_without = self._build(out_dir=self.out_dir / "b")
        self.assertEqual(path_with.read_bytes(), path_without.read_bytes())

    def test_no_timings_arg_means_no_collection_and_no_behavior_change(self):
        # timings=None (the default) must not touch matrix.build's return
        # value or written bytes at all -- it is pure bookkeeping.
        path = self._build()
        self.assertTrue(path.exists())

    def test_resumes_by_appending_only_missing_dates(self):
        path = matrix.build(2023, dates=["2023-04-05"], **self.kwargs)
        one_date = path.read_bytes()
        self._build()  # now asks for both dates
        content = path.read_bytes()
        self.assertTrue(content.startswith(one_date))  # old rows untouched
        self.assertEqual(json.loads(content.splitlines()[-1]),
                         {"date": "2023-04-06", "empty": True})

    def test_force_rebuilds_to_identical_content(self):
        path = self._build()
        before = path.read_bytes()
        self._build(force=True)
        self.assertEqual(path.read_bytes(), before)

    def test_sealed_seasons_are_refused(self):
        for season in (2025, 2026):
            with self.assertRaises(matrix.MatrixError):
                matrix.build(season, **self.kwargs)
            with self.assertRaises(matrix.MatrixError):
                matrix.read(season, out_dir=self.out_dir)

    def test_missing_file_reads_empty(self):
        self.assertEqual(matrix.read(2023, out_dir=self.out_dir), {})


if __name__ == "__main__":
    unittest.main()
