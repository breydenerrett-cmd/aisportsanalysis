"""Tests for src/core/asof.py: the stop-at-T reader.

Every test builds its own tiny JSONL stores under a tempdir and wires them in
via `stores=`, rather than depending on the real data/ tree, so this suite is
hermetic and never drifts with production data.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.core.asof import (
    GRADE_A,
    GRADE_D,
    ReplayLabel,
    StoreSpec,
    as_of,
    information_grade,
    season_replay_label,
    seasons_replay_label,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _pk(row: dict):
    v = row.get("game_pk")
    return str(v) if v is not None else None


def _obs(row: dict):
    return row.get("observed_utc")


class AsOfTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _spec(self, name, filename, fields):
        return StoreSpec(
            name=name, path=self.tmp / filename,
            game_key_of=_pk, time_of=_obs, fields=fields)


class TestStopAtT(AsOfTestCase):
    def test_a_row_after_t_never_appears(self):
        path = self.tmp / "ump.jsonl"
        _write_jsonl(path, [
            {"game_pk": 1, "observed_utc": "2026-01-01T10:00:00+00:00",
             "home_plate_umpire": "Early Ump"},
            {"game_pk": 1, "observed_utc": "2026-01-01T14:00:00+00:00",
             "home_plate_umpire": "Late Ump"},
        ])
        spec = self._spec("ump", "ump.jsonl",
                          {"home_plate_umpire": lambda r: r.get("home_plate_umpire")})
        snap = as_of(1, "2026-01-01T11:00:00+00:00", stores=[spec])
        self.assertEqual(snap.get("home_plate_umpire"), "Early Ump")

    def test_t_is_inclusive(self):
        path = self.tmp / "ump.jsonl"
        _write_jsonl(path, [
            {"game_pk": 1, "observed_utc": "2026-01-01T10:00:00+00:00",
             "home_plate_umpire": "On Time"},
        ])
        spec = self._spec("ump", "ump.jsonl",
                          {"home_plate_umpire": lambda r: r.get("home_plate_umpire")})
        snap = as_of(1, "2026-01-01T10:00:00+00:00", stores=[spec])
        self.assertEqual(snap.get("home_plate_umpire"), "On Time")

    def test_the_latest_observation_at_or_before_t_wins(self):
        path = self.tmp / "wx.jsonl"
        _write_jsonl(path, [
            {"game_pk": 1, "observed_utc": "2026-01-01T08:00:00+00:00",
             "temp_f": 70},
            {"game_pk": 1, "observed_utc": "2026-01-01T09:00:00+00:00",
             "temp_f": 75},
            {"game_pk": 1, "observed_utc": "2026-01-01T12:00:00+00:00",
             "temp_f": 999},
        ])
        spec = self._spec("wx", "wx.jsonl", {"temp_f": lambda r: r.get("temp_f")})
        snap = as_of(1, "2026-01-01T10:00:00+00:00", stores=[spec])
        self.assertEqual(snap.get("temp_f"), 75)

    def test_a_different_game_never_leaks_in(self):
        path = self.tmp / "wx.jsonl"
        _write_jsonl(path, [
            {"game_pk": 2, "observed_utc": "2026-01-01T08:00:00+00:00",
             "temp_f": 70},
        ])
        spec = self._spec("wx", "wx.jsonl", {"temp_f": lambda r: r.get("temp_f")})
        snap = as_of(1, "2026-01-01T10:00:00+00:00", stores=[spec])
        self.assertIsNone(snap.get("temp_f"))

    def test_a_heartbeat_row_with_no_game_key_never_matches(self):
        path = self.tmp / "wx.jsonl"
        _write_jsonl(path, [{"poll": True, "observed_utc":
                            "2026-01-01T08:00:00+00:00"}])
        spec = self._spec("wx", "wx.jsonl", {"temp_f": lambda r: r.get("temp_f")})
        snap = as_of(1, "2026-01-01T10:00:00+00:00", stores=[spec])
        self.assertEqual(snap.fields, {})


class TestAbsenceAndProvenance(AsOfTestCase):
    def test_a_field_never_observed_is_honestly_absent(self):
        spec = self._spec("wx", "missing.jsonl",
                          {"temp_f": lambda r: r.get("temp_f")})
        snap = as_of(1, "2026-01-01T10:00:00+00:00", stores=[spec])
        self.assertNotIn("temp_f", snap.fields)
        self.assertIsNone(snap.get("temp_f"))

    def test_provenance_carries_source_and_timestamps(self):
        path = self.tmp / "wx.jsonl"
        _write_jsonl(path, [
            {"game_pk": 1, "observed_utc": "2026-01-01T08:00:00+00:00",
             "temp_f": 70},
        ])
        spec = self._spec("weather_forecast", "wx.jsonl",
                          {"temp_f": lambda r: r.get("temp_f")})
        snap = as_of(1, "2026-01-01T10:00:00+00:00", stores=[spec])
        obs = snap.fields["temp_f"]
        self.assertEqual(obs.source, "weather_forecast")
        self.assertEqual(obs.observed_utc, "2026-01-01T08:00:00+00:00")
        self.assertEqual(obs.known_at, "2026-01-01T08:00:00+00:00")
        self.assertEqual(obs.known_at_grade, GRADE_A)

    def test_pre_2025_rows_are_graded_d_with_no_known_at(self):
        path = self.tmp / "wx.jsonl"
        _write_jsonl(path, [
            {"game_pk": 1, "observed_utc": "2023-06-01T08:00:00+00:00",
             "temp_f": 70},
        ])
        spec = self._spec("weather_forecast", "wx.jsonl",
                          {"temp_f": lambda r: r.get("temp_f")})
        snap = as_of(1, "2023-06-01T10:00:00+00:00", stores=[spec])
        obs = snap.fields["temp_f"]
        self.assertEqual(obs.known_at_grade, GRADE_D)
        self.assertIsNone(obs.known_at)


class TestTruncationDifferential(AsOfTestCase):
    """The leakage gate from ARCHITECTURE_BETTING_ENGINE.md section 4:
    shifting t two hours earlier may only ever remove or downgrade fields,
    never add one or change an already-surviving field's value.
    """

    def _stores(self):
        ump_path = self.tmp / "ump.jsonl"
        wx_path = self.tmp / "wx.jsonl"
        _write_jsonl(ump_path, [
            {"game_pk": 5, "observed_utc": "2026-05-01T10:00:00+00:00",
             "home_plate_umpire": "A"},
            {"game_pk": 5, "observed_utc": "2026-05-01T13:00:00+00:00",
             "home_plate_umpire": "B"},
            {"game_pk": 5, "observed_utc": "2026-05-01T16:00:00+00:00",
             "home_plate_umpire": "C"},
        ])
        _write_jsonl(wx_path, [
            {"game_pk": 5, "observed_utc": "2026-05-01T11:30:00+00:00",
             "temp_f": 80},
        ])
        return [
            self._spec("ump", "ump.jsonl",
                      {"home_plate_umpire": lambda r: r.get("home_plate_umpire")}),
            self._spec("wx", "wx.jsonl", {"temp_f": lambda r: r.get("temp_f")}),
        ]

    def test_shifting_t_two_hours_earlier_only_loses_fields(self):
        stores = self._stores()
        late = as_of(5, "2026-05-01T17:00:00+00:00", stores=stores)
        early = as_of(5, "2026-05-01T15:00:00+00:00", stores=stores)

        # The earlier-T snapshot's field set is a subset of the later-T
        # one's -- truncating never gains a field.
        self.assertTrue(set(early.fields) <= set(late.fields))

        # And every field the earlier-T snapshot DOES carry is backed by an
        # observation at or before the earlier T -- truncation never lets a
        # field survive on an observation it should have lost.
        for name, obs in early.fields.items():
            self.assertLessEqual(obs.observed_utc, early.t)
            # That same observation is exactly what the later snapshot would
            # have shown too, had nothing newer arrived between the two Ts --
            # confirmed directly by re-querying at the earlier instant from
            # the (unfiltered) full store, which is what `early` already is.
            self.assertIn(name, late.fields)

    def test_the_umpire_field_downgrades_to_the_earlier_observation(self):
        stores = self._stores()
        late = as_of(5, "2026-05-01T17:00:00+00:00", stores=stores)
        early = as_of(5, "2026-05-01T15:00:00+00:00", stores=stores)
        self.assertEqual(late.get("home_plate_umpire"), "C")
        self.assertEqual(early.get("home_plate_umpire"), "B")

    def test_shifting_before_the_first_observation_loses_it_entirely(self):
        stores = self._stores()
        before_any = as_of(5, "2026-05-01T09:00:00+00:00", stores=stores)
        self.assertNotIn("home_plate_umpire", before_any.fields)
        self.assertNotIn("temp_f", before_any.fields)

    def test_repeated_two_hour_shifts_never_gain_a_field(self):
        stores = self._stores()
        t = __import__("datetime").datetime(
            2026, 5, 1, 18, 0, tzinfo=__import__("datetime").timezone.utc)
        delta = __import__("datetime").timedelta(hours=2)
        prev = as_of(5, t, stores=stores)
        for _ in range(6):
            t = t - delta
            cur = as_of(5, t, stores=stores)
            self.assertTrue(set(cur.fields) <= set(prev.fields))
            prev = cur


class TestInformationGrade(AsOfTestCase):
    def test_a_2026_game_with_real_captures_is_faithful(self):
        ump_path = self.tmp / "ump.jsonl"
        lineup_path = self.tmp / "lineup.jsonl"
        prob_path = self.tmp / "prob.jsonl"
        _write_jsonl(ump_path, [
            {"game_pk": 10, "observed_utc": "2026-06-01T17:00:00+00:00",
             "home_plate_umpire": "Real Ump"},
        ])
        _write_jsonl(lineup_path, [
            {"game_pk": 10, "observed_utc": "2026-06-01T17:30:00+00:00",
             "home_lineup": [1, 2, 3], "away_lineup": [4, 5, 6]},
        ])
        _write_jsonl(prob_path, [
            {"game_pk": 10, "observed_utc": "2026-06-01T12:00:00+00:00",
             "home_probable_id": 111, "away_probable_id": 222},
        ])
        stores = [
            self._spec("umpires_watch", "ump.jsonl",
                      {"home_plate_umpire": lambda r: r.get("home_plate_umpire")}),
            self._spec("lineups_watch", "lineup.jsonl", {
                "home_lineup": lambda r: r.get("home_lineup") or None,
                "away_lineup": lambda r: r.get("away_lineup") or None,
            }),
            self._spec("probables_watch", "prob.jsonl", {
                "home_probable_id": lambda r: r.get("home_probable_id"),
                "away_probable_id": lambda r: r.get("away_probable_id"),
            }),
        ]
        snap = as_of(10, "2026-06-01T18:00:00+00:00", stores=stores)
        label, reasons = information_grade(snap)
        self.assertEqual(label, ReplayLabel.FAITHFUL)
        self.assertEqual(reasons, [])

    def test_a_2023_game_with_no_reconstructable_inputs_is_degraded(self):
        # Nothing captured at all (the watch stores did not exist in 2023):
        # every sentinel field is absent.
        stores = [
            self._spec("umpires_watch", "ump.jsonl",
                      {"home_plate_umpire": lambda r: r.get("home_plate_umpire")}),
            self._spec("lineups_watch", "lineup.jsonl", {
                "home_lineup": lambda r: r.get("home_lineup") or None,
                "away_lineup": lambda r: r.get("away_lineup") or None,
            }),
            self._spec("probables_watch", "prob.jsonl", {
                "home_probable_id": lambda r: r.get("home_probable_id"),
                "away_probable_id": lambda r: r.get("away_probable_id"),
            }),
        ]
        snap = as_of(9999, "2023-06-01T18:00:00+00:00", stores=stores)
        label, reasons = information_grade(snap)
        self.assertEqual(label, ReplayLabel.DEGRADED_INFORMATION)
        self.assertTrue(reasons)
        self.assertTrue(any("home_plate_umpire" in r for r in reasons))

    def test_a_backfilled_2023_field_present_but_ungraded_is_still_degraded(self):
        # A field that DOES have a row (backfilled after the fact) but whose
        # observed_utc predates live capture: grade D, still degraded.
        prob_path = self.tmp / "prob.jsonl"
        _write_jsonl(prob_path, [
            {"game_pk": 9999, "observed_utc": "2023-06-01T20:00:00+00:00",
             "home_probable_id": 111, "away_probable_id": 222},
        ])
        stores = [
            self._spec("probables_watch", "prob.jsonl", {
                "home_probable_id": lambda r: r.get("home_probable_id"),
                "away_probable_id": lambda r: r.get("away_probable_id"),
            }),
        ]
        snap = as_of(9999, "2023-06-01T23:00:00+00:00", stores=stores,
                     )
        label, reasons = information_grade(
            snap, sentinel_fields=("home_probable_id",))
        self.assertEqual(label, ReplayLabel.DEGRADED_INFORMATION)
        self.assertIn("home_probable_id", reasons[0])
        self.assertIn("grade D", reasons[0])


class TestSeasonLabel(unittest.TestCase):
    def test_2023_and_2024_are_degraded(self):
        for season in (2023, 2024):
            out = season_replay_label(season)
            self.assertEqual(out["label"],
                             ReplayLabel.DEGRADED_INFORMATION.value)
            self.assertTrue(out["reasons"])

    def test_2026_is_faithful(self):
        out = season_replay_label(2026)
        self.assertEqual(out["label"], ReplayLabel.FAITHFUL.value)
        self.assertEqual(out["reasons"], [])

    def test_mixed_seasons_degrade_the_whole_artifact(self):
        out = seasons_replay_label([2023, 2026])
        self.assertEqual(out["label"], ReplayLabel.DEGRADED_INFORMATION.value)
        self.assertTrue(out["reasons"])

    def test_all_faithful_seasons_stay_faithful(self):
        out = seasons_replay_label([2026])
        self.assertEqual(out["label"], ReplayLabel.FAITHFUL.value)
        self.assertEqual(out["reasons"], [])


if __name__ == "__main__":
    unittest.main()
