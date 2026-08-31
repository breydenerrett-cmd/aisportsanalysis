"""V5 feature groundwork tests: starter_velocity_gap, point-in-time.

Same fixture philosophy as tests/test_matrix.py -- a tiny gzipped store in
statcast_pitches' exact on-disk shape, walked through rebuilt.build_snapshots
and matrix.build, no accumulator stubbed -- and the same injection discipline
as tests/test_validation_pit.py: a payload dated after the cutoff must not
move the row by one byte, and the identical payload dated before the cutoff
MUST move it, so after-cutoff silence means "refused", not "ignored".

Velocity fixture, checkable by hand (all speeds exactly representable):
  pitcher 800 (HOME starter -- the AWAY lineup faces him): 6 appearances.
    oldest (2023-03-01): 30 FF at 99.0  -> OUTSIDE the 5-start window
    5 newer games:      30 FF at 95.0 each (150 fastballs) -> avg 95.0
    plus 30 SL at 80.0 and 2 FF with no radar reading -> all ignored
  pitcher 810 (AWAY starter): 99 FF at 96.0 -- one under the 100 floor.
  pitcher 820: 50 + 50 FF at 90.0 -- exactly at the floor, usable.
  pitcher 900: 100 FF at 93.0 -- league filler.
  league average = (30*99 + 150*95 + 99*96 + 100*90 + 100*93) / 479

There is no groundball fixture on purpose: the pitch store keeps no
batted-ball-type column (statcast_pitches.KEEP has no bb_type; zero of the
real store's 2.74M rows carry one), so starter_groundball_share was
deliberately not built rather than faked from event-name proxies.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import rebuilt
from src.research import matrix
from tests.test_matrix import _pitch, _slots

BASE_WINDOW = "2023-03-01..2023-03-04"
CUTOFF = "2023-04-01"  # monthly cutoff for the game day below

LEAGUE_SUM = 30 * 99.0 + 150 * 95.0 + 99 * 96.0 + 100 * 90.0 + 100 * 93.0
LEAGUE_COUNT = 30 + 150 + 99 + 100 + 100
# Pitcher 800's last-5-appearance average is exactly 95.0.
EXPECTED_AWAY_GAP = round(95.0 - LEAGUE_SUM / LEAGUE_COUNT, 4)

GAME = {"game_pk": "800001", "date": "2023-04-05",
        "start_time_utc": "2023-04-05T23:10:00Z",
        "away_team": "CLE", "home_team": "SEA",
        "away_probable_id": "810", "home_probable_id": "800"}

POSTED = {"game_pk": "800001", "away": _slots(9001), "home": _slots(9101)}


def _fb(day, pk, pitcher, speed, pitch_type="FF"):
    """A stored-pitch row with velocity fields, built on test_matrix._pitch
    so the row shape has exactly one definition across the matrix tests."""
    return dict(_pitch(pitcher, "9500", "R", pitch_type, "0.0", "field_out"),
                game_date=day, game_pk=pk, release_speed=speed)


def _velocity_rows() -> list:
    rows = []
    # Pitcher 800, oldest appearance: 30 FF at 99.0 -- the 6th-most-recent
    # game, which the 5-start window must exclude.
    rows += [_fb("2023-03-01", "3001", "800", "99.0") for _ in range(30)]
    # Pitcher 800, five newer appearances: 30 FF at 95.0 each. Two games
    # share a date with distinct game_pks (a doubleheader) on purpose.
    for day, pk in (("2023-03-02", "3002"), ("2023-03-03", "3003"),
                    ("2023-03-03", "3004"), ("2023-03-04", "3005"),
                    ("2023-03-04", "3006")):
        rows += [_fb(day, pk, "800", "95.0") for _ in range(30)]
    # Noise that must NOT count as fastball velocity: sliders, and FF rows
    # whose radar reading is missing.
    rows += [_fb("2023-03-04", "3006", "800", "80.0", "SL") for _ in range(30)]
    rows += [_fb("2023-03-04", "3006", "800", None) for _ in range(2)]
    # Pitcher 810: 99 fastballs, one under MIN_FASTBALLS_FOR_VELOCITY.
    rows += [_fb("2023-03-02", "3050", "810", "96.0") for _ in range(99)]
    # Pitcher 820: exactly 100 fastballs across two appearances.
    rows += [_fb("2023-03-02", "3060", "820", "90.0") for _ in range(50)]
    rows += [_fb("2023-03-03", "3061", "820", "90.0") for _ in range(50)]
    # Pitcher 900: league filler.
    rows += [_fb("2023-03-01", "3070", "900", "93.0") for _ in range(100)]
    return rows


def _write_store(root: Path, windows: dict) -> Path:
    """A gzipped store plus manifest, the exact shape statcast_pitches
    writes, extended windows and all (the test_validation_pit pattern)."""
    store = root / "statcast"
    store.mkdir(parents=True)
    manifest = {}
    for window, rows in windows.items():
        name = f"pitches_{window}.jsonl.gz"
        with gzip.open(store / name, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        manifest[window] = {"rows": len(rows), "file": name}
    (store / "manifest.json").write_text(
        json.dumps({"windows": manifest}), encoding="utf-8")
    return store


class VelocityGapRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.store = _write_store(Path(cls._tmp.name),
                                 {BASE_WINDOW: _velocity_rows()})
        cls.acc = rebuilt.build_snapshots([CUTOFF], store=cls.store)[CUTOFF]
        cls.row = matrix.row_for_game(cls.acc, GAME, POSTED, {})

    def test_away_feature_reads_the_home_starter(self):
        # The cross-join: the AWAY lineup faces the HOME starter 800, so
        # away_starter_velocity_gap is 800's recent velocity vs league.
        self.assertEqual(self.row["away_starter_velocity_gap"],
                         EXPECTED_AWAY_GAP)

    def test_home_feature_reads_the_away_starter_and_floors(self):
        # The HOME lineup faces the AWAY starter 810, who has 99 measured
        # fastballs -- one under the floor. None plus a gap, never a number.
        self.assertIsNone(self.row["home_starter_velocity_gap"])
        self.assertTrue(any(g.startswith("home_starter_velocity_gap:")
                            and "99 measured fastballs" in g
                            for g in self.row["gaps"]))

    def test_window_excludes_sixth_most_recent_appearance(self):
        velo = rebuilt.fastball_velocity(self.acc, "800")
        self.assertTrue(velo["usable"])
        # 150 fastballs, not 180: the 99.0-mph game fell out of the window;
        # not 182: the two radar-less FF rows were skipped, not guessed.
        self.assertEqual(velo["fastballs"], 150)
        self.assertEqual(velo["games"], rebuilt.VELOCITY_STARTS_WINDOW)
        # And the average is exactly 95.0: no 99.0 game, no 80.0 sliders.
        self.assertEqual(velo["avg"], 95.0)

    def test_floor_is_exact(self):
        under = rebuilt.fastball_velocity(self.acc, "810")
        self.assertFalse(under["usable"])
        self.assertEqual(under["fastballs"],
                         rebuilt.MIN_FASTBALLS_FOR_VELOCITY - 1)
        self.assertIsNone(under["avg"])
        at_floor = rebuilt.fastball_velocity(self.acc, "820")
        self.assertTrue(at_floor["usable"])
        self.assertEqual(at_floor["fastballs"],
                         rebuilt.MIN_FASTBALLS_FOR_VELOCITY)
        self.assertEqual(at_floor["avg"], 90.0)

    def test_unknown_pitcher_is_none_with_reason(self):
        velo = rebuilt.fastball_velocity(self.acc, "999999")
        self.assertFalse(velo["usable"])
        self.assertEqual(velo["fastballs"], 0)
        self.assertIsNone(velo["avg"])

    def test_missing_starter_records_gap(self):
        game = dict(GAME, home_probable_id=None)
        row = matrix.row_for_game(self.acc, game, POSTED, {})
        self.assertIsNone(row["away_starter_velocity_gap"])
        self.assertTrue(any(g.startswith("away_opposing_starter:")
                            for g in row["gaps"]))

    def test_league_average_is_all_prior_fastballs(self):
        self.assertEqual(rebuilt.league_fastball_velocity(self.acc),
                         LEAGUE_SUM / LEAGUE_COUNT)

    def test_empty_accumulation_reports_none(self):
        # A cutoff before the store's first pitch: opening-week honesty.
        acc = rebuilt.build_snapshots(["2023-01-01"],
                                      store=self.store)["2023-01-01"]
        self.assertIsNone(rebuilt.league_fastball_velocity(acc))
        row = matrix.row_for_game(acc, GAME, POSTED, {})
        self.assertIsNone(row["away_starter_velocity_gap"])
        self.assertIsNone(row["home_starter_velocity_gap"])


class VelocityPointInTimeInjectionTest(unittest.TestCase):
    """The tests/test_validation_pit.py discipline, on the velocity feature.

    The payload is 200 fastballs at 105.0 from pitcher 800 -- extreme so a
    leak cannot hide inside rounding. Identical at every timestamp; the only
    variable is WHEN the data claims to be relative to the 2023-04-01
    cutoff of game day D = 2023-04-05.
    """

    @staticmethod
    def _payload(day):
        return [_fb(day, "9990", "800", "105.0") for _ in range(200)]

    @classmethod
    def _row_line(cls, extra_windows=None) -> bytes:
        windows = {BASE_WINDOW: _velocity_rows()}
        windows.update(extra_windows or {})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = _write_store(root, windows)
            path = matrix.build(2023, dates=[GAME["date"]],
                                out_dir=root / "research", store=store,
                                results={"800001": dict(GAME)},
                                lineups_by_pk={"800001": POSTED},
                                handedness={})
            for line in path.read_bytes().splitlines():
                if json.loads(line).get("game_pk") == "800001":
                    return line
        raise AssertionError("game 800001 produced no matrix row")

    @classmethod
    def setUpClass(cls):
        cls.clean = cls._row_line()

    def test_build_is_deterministic(self):
        # The byte comparisons below presume this.
        self.assertEqual(self._row_line(), self.clean)

    def test_pitches_after_game_day_cannot_move_the_row(self):
        tampered = self._row_line(
            {"2023-04-06..2023-04-09": self._payload("2023-04-06")})
        self.assertEqual(tampered, self.clean)

    def test_pitches_on_game_day_cannot_move_the_row(self):
        # After the monthly cutoff even though before first pitch.
        tampered = self._row_line(
            {"2023-04-05..2023-04-08": self._payload("2023-04-05")})
        self.assertEqual(tampered, self.clean)

    def test_pitches_between_cutoff_and_game_cannot_move_the_row(self):
        tampered = self._row_line(
            {"2023-04-02..2023-04-04": self._payload("2023-04-02")})
        self.assertEqual(tampered, self.clean)

    def test_detector_fires_on_pre_cutoff_injection(self):
        # The identical payload BEFORE the cutoff must move the velocity
        # feature -- otherwise the silence above proves nothing.
        tampered = self._row_line(
            {"2023-03-25..2023-03-28": self._payload("2023-03-25")})
        self.assertNotEqual(tampered, self.clean)
        clean_row = json.loads(self.clean)
        moved_row = json.loads(tampered)
        self.assertNotEqual(moved_row["away_starter_velocity_gap"],
                            clean_row["away_starter_velocity_gap"])


if __name__ == "__main__":
    unittest.main()
