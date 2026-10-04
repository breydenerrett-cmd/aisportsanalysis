"""An unknown column may survive a round trip; it must never become a model input (2026-10-04).

`store_persist` carries a column of the results CSV the code does not know (rather than narrowing the committed
file). That is only safe if nothing downstream reads the extra column. The claim under test: the team feature
builder (`features.build_training_table`, `matchup_features`) and the starter features
(`starter_rest.starter_rest`) give byte-identical output from a results file that carries an extra column and from
the same file without it, even when that column is shaped like a leak (a copy of the label).
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import features, history, pitchers, starter_rest
from src.pipeline import store_persist as sp

TEAMS = ["NYY", "BOS", "SD", "LAD", "ATL", "HOU"]


def games():
    out, pk = {}, 1000
    for day in range(1, 29):
        for k in range(3):
            pk += 1
            away, home = TEAMS[(day + 2 * k) % 6], TEAMS[(day + 2 * k + 1) % 6]
            a, h = (day + k) % 7, (day * 3 + k) % 8
            if a == h:
                h += 1
            out[str(pk)] = {
                "game_pk": str(pk), "date": f"2026-04-{day:02d}", "game_type": "R", "away_team": away,
                "home_team": home, "away_score": str(a), "home_score": str(h),
                "winner": away if a > h else home, "home_won": "1" if h > a else "0",
                "away_probable_id": "111", "home_probable_id": "222"}
    return out


class ARowOfUnknownColumnsChangesNoFeature(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        rows = {pk: {c: row.get(c) for c in history.RESULT_COLUMNS} for pk, row in games().items()}
        self.plain, self.wide = base / "plain.csv", base / "wide.csv"
        history.write_results(rows, self.plain)
        # the extra column looks as predictive as a column can: a copy of the label, and one of the score
        wide_rows = {pk: {**row, "venue_id": row["home_won"], "park_runs": row["home_score"]}
                     for pk, row in rows.items()}
        sp._write_results_wide(wide_rows, self.wide, ["venue_id", "park_runs"])
        self.logs = base / "pitcher_logs.jsonl"
        pitchers.write_logs({"111": [
            {"person_id": 111, "date": f"2026-04-{d:02d}", "season": "2026", "games_started": 1, "innings_pitched": 6.0,
             "earned_runs": 2, "runs": 2, "hits": 5, "walks": 1, "strikeouts": 6, "home_runs": 1,
             "batters_faced": 24, "pitches": 90} for d in (2, 7, 12, 17, 22)]}, self.logs)

    def test_the_wide_file_really_carries_the_column(self):
        with self.wide.open(newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        self.assertEqual(header[-2:], ["venue_id", "park_runs"])
        self.assertTrue(all("venue_id" in row for row in history.read_results(self.wide).values()))
        self.assertFalse(any("venue_id" in row for row in history.read_results(self.plain).values()))

    def test_the_training_table_is_byte_identical(self):
        for kw in ({}, {"require_complete": False}):
            with self.subTest(**kw):
                a = features.build_training_table(history.read_results(self.plain), **kw)
                b = features.build_training_table(history.read_results(self.wide), **kw)
                self.assertGreater(a["count"], 0)
                self.assertEqual(json.dumps(a, sort_keys=True).encode("utf-8"),
                                 json.dumps(b, sort_keys=True).encode("utf-8"))
                for row in b["rows"]:
                    self.assertNotIn("venue_id", row)
                    self.assertNotIn("park_runs", row)

    def test_the_training_table_with_pitchers_is_byte_identical(self):
        logs = pitchers.read_logs(self.logs)
        a = features.build_training_table(history.read_results(self.plain), require_complete=False, pitcher_logs=logs)
        b = features.build_training_table(history.read_results(self.wide), require_complete=False, pitcher_logs=logs)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_matchup_features_are_byte_identical(self):
        plain, wide = history.read_results(self.plain), history.read_results(self.wide)
        for away, home in (("NYY", "BOS"), ("SD", "LAD"), ("ATL", "HOU")):
            self.assertEqual(
                json.dumps(features.matchup_features(plain, away, home, "2026-04-28"), sort_keys=True),
                json.dumps(features.matchup_features(wide, away, home, "2026-04-28"), sort_keys=True))

    def test_the_starter_features_are_byte_identical(self):
        plain, wide = history.read_results(self.plain), history.read_results(self.wide)
        seen = 0
        for pk in plain:
            a = starter_rest.starter_rest(plain[pk], plain[pk]["date"], path=self.logs)
            b = starter_rest.starter_rest(wide[pk], wide[pk]["date"], path=self.logs)
            self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
            seen += a["away"] is not None
        self.assertGreater(seen, 0, "the comparison saw real starter rows")


if __name__ == "__main__":
    unittest.main()
