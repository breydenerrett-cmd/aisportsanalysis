"""Validation gate, check 5: the matchup matrix is point-in-time safe.

WHY THIS CHECK EXISTS
---------------------
Every hypothesis reads its features from the matchup matrix, so a single
future-leak there poisons every result downstream. The matrix's own tests
prove its arithmetic; this file proves its TIME DISCIPLINE, by injection: the
same game is built from a clean store and from stores tampered with extra
pitch data at three timestamps relative to the game's date D = 2023-04-05
(monthly cutoff 2023-04-01):

  - strictly AFTER D            -> must not move the row by one byte
  - ON D (after the cutoff)     -> must not move the row by one byte
  - in the month BEFORE D,      -> MUST move the row
    before the cutoff

The third case is the tamper detector proving it can fire. Byte-identical
rows under an injection that the builder is BLIND to would be a vacuous
proof -- maybe nothing can move the row. Only when the identical payload
demonstrably changes the row from before the cutoff does the after-cutoff
silence mean "the future was seen and refused", not "the store was ignored".

WHY BYTE COMPARISON IS VALID
----------------------------
build() writes each row with json.dumps(..., sort_keys=True), so two rows
computed from equal inputs serialize identically; comparing raw JSONL line
bytes is therefore exact -- no tolerance behind which a small leak could
hide. Determinism itself (same store twice -> same bytes) is asserted first,
because the byte comparison presumes it.

Everything runs through the same public path a real season build takes:
a gzipped store in statcast_pitches' on-disk shape, walked by
rebuilt.build_snapshots inside matrix.build. No accumulator is stubbed.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.research import matrix
from tests.test_matrix import (GAME, HANDEDNESS, POSTED, WINDOW, _pitch,
                               _synthetic_rows)

# The tampered payload is EXTREME on purpose: 100 extra plate appearances by
# pitcher 500 (the starter the away lineup faces) at wOBA 0.9, thrown to the
# posted away hitters, 60 of them sliders. If admitted it moves the platoon
# gap, the pitch-mix shares, every batter_vs_pitch line, the batter totals
# behind top_minus_bottom, and the matchup history at once -- a leak of even
# one of these features cannot hide.
TAMPER_BATTERS = [str(9001 + i) for i in range(9)]  # the posted away lineup


def _pitch_on(day, pitcher, batter, stand, pitch_type, value, events):
    """A _pitch-shaped row whose game_date is overridden.

    Built on tests.test_matrix._pitch so the row shape stays whatever that
    fixture says a stored pitch looks like -- one definition, not two.
    """
    return dict(_pitch(pitcher, batter, stand, pitch_type, value, events),
                game_date=day)


def _tamper_rows(day) -> list:
    """The injection payload, dated `day` -- identical at every timestamp so
    the only variable across the three tests is WHEN the data claims to be."""
    rows = []
    for i in range(100):
        pitch_type = "SL" if i < 60 else "FF"
        rows.append(_pitch_on(day, "500", TAMPER_BATTERS[i % 9], "R",
                              pitch_type, "0.9", "single"))
    return rows


def _write_store(root: Path, windows: dict) -> Path:
    """A gzipped store in the exact on-disk shape tests.test_matrix._write
    _store produces (one .jsonl.gz per window plus manifest.json), extended
    to take extra windows so a tampered store is built through the same
    public path as the clean one, never patched in memory."""
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


def _row_line_for_game(extra_windows=None) -> bytes:
    """Build the matrix for game day D from a fresh store (base synthetic
    rows plus any injected windows) into a fresh out_dir, and return the raw
    bytes of game 700001's JSONL line. Fresh directories per call so no test
    can lean on another's resume file."""
    windows = {WINDOW: _synthetic_rows()}
    windows.update(extra_windows or {})
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = _write_store(root, windows)
        path = matrix.build(2023, dates=[GAME["date"]],
                            out_dir=root / "research", store=store,
                            results={"700001": dict(GAME)},
                            lineups_by_pk={"700001": POSTED},
                            handedness=HANDEDNESS)
        for line in path.read_bytes().splitlines():
            if json.loads(line).get("game_pk") == "700001":
                return line
    raise AssertionError("game 700001 produced no matrix row")


class MatrixPointInTimeInjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The clean baseline every injection is compared against, built once.
        cls.clean = _row_line_for_game()

    def test_repeated_builds_are_byte_identical(self):
        # Determinism underwrites every byte comparison below: if two clean
        # builds could differ, "tampered equals clean" would prove nothing.
        self.assertEqual(_row_line_for_game(), self.clean)

    def test_data_dated_after_the_game_cannot_move_the_row(self):
        # The payload sits in a window strictly after D and is dated
        # 2023-04-07. A builder that read season totals, or took the nearest
        # snapshot instead of the game's own month, would inhale it; the
        # point-in-time builder must produce the identical bytes.
        line = _row_line_for_game(
            {"2023-04-06..2023-04-09": _tamper_rows("2023-04-07")})
        self.assertEqual(line, self.clean)

    def test_data_dated_on_game_day_cannot_move_the_row(self):
        # Same payload dated D itself, in a window straddling D. Game-day
        # data is AFTER the monthly cutoff 2023-04-01, and admitting the
        # game's own day is the classic off-by-one leak (a <= where a < was
        # meant); the row must again be byte-identical.
        line = _row_line_for_game(
            {"2023-04-04..2023-04-07": _tamper_rows(GAME["date"])})
        self.assertEqual(line, self.clean)

    def test_data_dated_before_the_cutoff_must_move_the_row(self):
        # The DETECTOR TEST: the identical payload dated 2023-03-21 -- before
        # the 2023-04-01 cutoff -- must change the row. If it did not, the
        # two silences above would be indistinguishable from a builder that
        # ignores injected windows altogether.
        line = _row_line_for_game(
            {"2023-03-20..2023-03-23": _tamper_rows("2023-03-21")})
        self.assertNotEqual(line, self.clean)
        # And the movement must be semantic, in a named feature: 100 extra
        # vs-R PA at 0.9 drag 500's vs-R wOBA up, so the away gap (vs_L minus
        # vs_R) must leave its clean value of 0.15.
        row = json.loads(line)
        self.assertIsNotNone(row["away_starter_platoon_gap"])
        self.assertNotEqual(row["away_starter_platoon_gap"], 0.15)

    def test_sealed_seasons_are_refused_before_any_data_is_read(self):
        # 2025-26 are tuning/sealed sets; the guard must be structural. The
        # store kwarg points at a real synthetic store so a refusal is
        # provably the season guard firing, not a missing-file crash.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = _write_store(root, {WINDOW: _synthetic_rows()})
            for season in (2025, 2026):
                with self.assertRaises(matrix.MatrixError):
                    matrix.build(season, out_dir=root / "research",
                                 store=store, results={},
                                 lineups_by_pk={}, handedness=HANDEDNESS)


if __name__ == "__main__":
    unittest.main()
