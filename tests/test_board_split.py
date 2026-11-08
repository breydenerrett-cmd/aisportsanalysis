"""The multibook store split by sport for the quiz's replays (src/hounds/interact/board_split.py). No FastAPI needed.

The split must be invisible: a replay over the split reads exactly the rows a whole-store scan reads, for every sport, including the
mlb rows that carry no sport field and a line whose sport cannot be read from its text.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from src.hounds.interact import board_split, drill


def line(sport, event, observed, start, home=-120, away=110, book="fanduel"):
    row = {"observed_utc": observed, "event_id": event, "commence_time": start, "home_team": f"H{event}", "away_team": f"A{event}",
           "book": book, "book_last_update": observed, "home_price": home, "away_price": away}
    if sport is not None:
        row["sport"] = sport
    return json.dumps(row, separators=(",", ":"))


class TheSplit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = root / "odds_multibook.jsonl"
        self.split_dir = root / "split"
        rows = [
            line("nhl", "n1", "2026-11-05T20:00:00+00:00", "2026-11-06T00:00:00Z"),
            line("nhl", "n2", "2026-11-06T20:00:00+00:00", "2026-11-07T00:00:00Z", book="draftkings"),
            line("nba", "b1", "2026-11-05T21:00:00+00:00", "2026-11-06T01:00:00Z"),
            line(None, "m1", "2026-11-05T15:00:00+00:00", "2026-11-05T23:00:00Z"),           # no sport field: mlb
            line("tennis", "t1", "2026-11-06T09:00:00+00:00", "2026-11-06T12:00:00Z"),
            line("nhl", "old", "2026-09-01T20:00:00+00:00", "2026-09-02T00:00:00Z"),          # long before the window
        ]
        self.store.write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"LH_BOARD_SPLIT_DIR": str(self.split_dir)})
        self.env.start()
        self.path = mock.patch("src.pipeline.snapshots.DEFAULT_MULTIBOOK_PATH", self.store)
        self.path.start()

    def tearDown(self):
        self.path.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_rows_over_the_split_are_exactly_the_whole_store_rows(self):
        lo, hi = "2026-11-04", "2026-11-08"
        whole = {s: drill._window_rows(lo, hi, [s]) for s in ("NHL", "NBA", "MLB", "TENNIS", "SOCCER")}
        self.assertFalse(board_split.ready(lo, hi))
        board_split.ensure(lo, hi)
        self.assertTrue(board_split.ready(lo, hi))
        for sport, want in whole.items():
            self.assertIsNotNone(board_split.path_for(sport.lower(), lo, hi))
            self.assertEqual(drill._window_rows(lo, hi, [sport]), want, sport)
        self.assertEqual(sorted(r["event_id"] for d in whole["NHL"].values() for r in d), ["n1", "n2"])
        self.assertEqual([r["event_id"] for d in whole["MLB"].values() for r in d], ["m1"])

    def test_a_new_capture_makes_a_new_split_and_the_old_one_is_removed(self):
        lo, hi = "2026-11-04", "2026-11-08"
        first = board_split.ensure(lo, hi)
        time.sleep(1.1)                                              # mtime has one-second resolution on some file systems
        with open(self.store, "a", encoding="utf-8") as fh:
            fh.write(line("nhl", "n3", "2026-11-07T20:00:00+00:00", "2026-11-08T00:00:00Z") + "\n")
        self.assertFalse(board_split.ready(lo, hi))
        second = board_split.ensure(lo, hi)
        self.assertNotEqual(first, second)
        self.assertFalse(first.exists())
        self.assertIn("n3", [r["event_id"] for d in drill._window_rows(lo, hi, ["NHL"]).values() for r in d])

    def test_a_line_whose_sport_the_text_cannot_prove_is_read_for_every_sport(self):
        self.assertEqual(board_split._sport_of('{"sport":"nhl","x":1}'), "nhl")
        self.assertEqual(board_split._sport_of('{"x":1}'), "mlb")
        self.assertEqual(board_split._sport_of('{"sport": "nhl"}'), board_split.ANY)       # spaced key: the reader decides
        self.assertEqual(board_split._sport_of('{"sport":"../etc"}'), board_split.ANY)

    def test_the_child_process_writes_the_same_split_as_the_pass_in_process(self):
        lo, hi = "2026-11-04", "2026-11-08"
        here = board_split.ensure(lo, hi)
        want = {p.name: p.read_text(encoding="utf-8") for p in here.iterdir()}
        import shutil
        shutil.rmtree(here)
        with mock.patch.object(board_split.subprocess, "run", wraps=board_split.subprocess.run) as ran:
            child = board_split.ensure(lo, hi, child=True)
        self.assertEqual(ran.call_count, 1)
        self.assertEqual({p.name: p.read_text(encoding="utf-8") for p in child.iterdir()}, want)

    def test_a_failed_child_is_an_error_not_a_missing_split(self):
        with mock.patch.object(board_split, "_run_child", side_effect=OSError("board split child exited 1: boom")):
            with self.assertRaises(OSError):
                board_split.ensure("2026-11-04", "2026-11-08", child=True)
        self.assertFalse(board_split.ready("2026-11-04", "2026-11-08"))

    def test_start_runs_in_the_background_and_reports_ready(self):
        lo, hi = "2026-11-04", "2026-11-08"
        self.assertFalse(board_split.start(lo, hi))
        for _ in range(100):
            if board_split.ready(lo, hi):
                break
            time.sleep(0.05)
        self.assertTrue(board_split.start(lo, hi))


class TheCatchphrase(unittest.TestCase):
    """2026-11-08: a hockey hound's catchphrase naming the NHL was blanked as a reserved word."""

    def test_a_league_name_is_fine_in_a_catchphrase_and_still_refused_in_a_name(self):
        from src.hounds import user_spec
        from src.hounds.quiz import compose
        out = compose.compose({"sports": ["NHL"], "personality": "underdog_hunter", "tagline": "Lives for NHL dogs"})
        self.assertEqual(out["spec"]["tagline"], "Lives for NHL dogs")
        self.assertNotIn("tagline_rejected", [w["code"] for w in out["warnings"]])
        self.assertIsNotNone(user_spec.text_problem("NHL Hound"))
        self.assertIn('"official"', user_spec.text_problem("Official picks", allow_leagues=True))

    def test_a_refused_catchphrase_falls_back_to_the_style_line_and_says_so(self):
        from src.hounds.quiz import compose
        out = compose.compose({"sports": ["MLB"], "personality": "chalk_eater", "tagline": "House always wins"})
        self.assertEqual(out["spec"]["tagline"], "Eats the chalk. Never -200 or worse.")
        msg = [w["message"] for w in out["warnings"] if w["code"] == "tagline_rejected"][0]
        self.assertIn('"house"', msg)
        self.assertIn("Eats the chalk", msg)


if __name__ == "__main__":
    unittest.main()
