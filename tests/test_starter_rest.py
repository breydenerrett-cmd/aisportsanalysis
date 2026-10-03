"""When each starter last pitched, postseason included, for the game page alone.

2026-10-03: in October the page's DAYS REST read the dossier's `*_sp_days_rest`, a model
input built from regular-season logs only (`pitchers.regular_season_logs`), so a starter
who threw a Wild Card game on Sept 30 showed 14 days (the cap, counted from his last
regular-season start) before an Oct 4 Division Series start. `src.pipeline.starter_rest`
reads the whole store for the page, beside the dossier; the model input does not move.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import pitchers
from src.pipeline import starter_rest

ROOT = Path(__file__).resolve().parents[1]

ROWS = [
    {"person_id": 100, "date": "2026-09-20", "game_type": "R", "games_started": 1, "innings_pitched": 6.0},
    {"person_id": 100, "date": "2026-09-26", "games_started": 1, "innings_pitched": 5.2},   # no game_type: regular
    {"person_id": 100, "date": "2026-09-30", "game_type": "F", "games_started": 1, "innings_pitched": 6.1},
    {"person_id": 200, "date": "2026-09-27", "game_type": "R", "games_started": 0, "innings_pitched": 1.0},
    {"person_id": 200, "date": None, "checked_utc": "2026-10-03T10:00:00Z"},                  # a marker
    {"person_id": 300, "date": "2026-10-01", "empty": True},
]


def _write(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class LastOuting(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "pitcher_logs.jsonl"
        _write(self.path, ROWS)

    def rest(self, game_date, away=100, home=200):
        return starter_rest.starter_rest({"away_probable_id": away, "home_probable_id": home}, game_date, self.path)

    def test_a_wild_card_start_counts(self):
        out = self.rest("2026-10-04")
        self.assertEqual(out["away"], {"date": "2026-09-30", "days_before": 4, "game_type": "F", "postseason": True,
                                       "round": "Wild Card", "started": True, "innings": 6.1})

    def test_a_relief_outing_is_said_so(self):
        home = self.rest("2026-10-04")["home"]
        self.assertEqual((home["date"], home["days_before"], home["started"], home["round"]),
                         ("2026-09-27", 7, False, None))

    def test_only_outings_before_the_game_day_count(self):
        self.assertEqual(self.rest("2026-09-30")["away"]["date"], "2026-09-26")

    def test_unknown_or_missing_probables_and_markers_give_none(self):
        out = self.rest("2026-10-04", away=999, home=None)
        self.assertEqual(out, {"away": None, "home": None})
        self.assertIsNone(self.rest("2026-10-04", away=300)["away"])        # only an `empty` row on file

    def test_a_missing_store_gives_none_for_both(self):
        missing = self.path.with_name("absent.jsonl")
        out = starter_rest.starter_rest({"away_probable_id": 100, "home_probable_id": 200}, "2026-10-04", missing)
        self.assertEqual(out, {"away": None, "home": None})

    def test_the_store_is_read_once_per_version_of_the_file(self):
        with mock.patch.object(starter_rest, "_build_index", wraps=starter_rest._build_index) as built:
            for _ in range(3):
                self.rest("2026-10-04")
            self.assertEqual(built.call_count, 1)
            _write(self.path, ROWS + [{"person_id": 100, "date": "2026-10-03", "game_type": "D",
                                       "games_started": 1, "innings_pitched": 5.0}])
            out = self.rest("2026-10-05")
            self.assertEqual(built.call_count, 2)
        self.assertEqual((out["away"]["round"], out["away"]["days_before"]), ("Division Series", 2))

    def test_the_model_input_still_reads_the_regular_season_only(self):
        logs = pitchers.regular_season_logs(pitchers.read_logs(self.path))
        features = pitchers.pitcher_features(logs, 100, "2026-10-04")
        self.assertEqual(features["sp_days_rest"], 8)                       # from Sept 26, by design
        self.assertEqual(self.rest("2026-10-04")["away"]["days_before"], 4)  # the page's figure


NODE = shutil.which("node")
PAGE = r"""
const { lastOutingText } = await import(process.env.STORY);
const cases = JSON.parse(process.env.CASES);
console.log("@@" + JSON.stringify(cases.map((c) => lastOutingText(c))));
"""


class ThePageSentence(unittest.TestCase):
    def test_the_route_attaches_it_beside_the_dossier(self):
        source = (ROOT / "api" / "games.py").read_text(encoding="utf-8")
        self.assertIn('payload["advanced"]["starter_rest"] = starter_rest.starter_rest(entry["dossier"].game, date)',
                      source)
        story = (ROOT / "web" / "js" / "gamestory.js").read_text(encoding="utf-8")
        self.assertIn("advanced.starter_rest", story)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_what_a_reader_sees(self):
        with tempfile.TemporaryDirectory() as tmp:
            for module in (ROOT / "web" / "js").glob("*.js"):      # gamestory.js and what it imports
                shutil.copy(module, Path(tmp) / module.name)
            script = Path(tmp) / "run.mjs"
            script.write_text(PAGE, encoding="utf-8")
            cases = [
                {"date": "2026-09-30", "days_before": 4, "round": "Wild Card", "started": True},
                {"date": "2026-09-27", "days_before": 1, "round": None, "started": False},
            ]
            env = dict(os.environ, STORY=(Path(tmp) / "gamestory.js").as_uri(), CASES=json.dumps(cases))
            run = subprocess.run([NODE, str(script)], capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            line = next(l for l in run.stdout.splitlines() if l.startswith("@@"))
            self.assertEqual(json.loads(line[2:]), [
                "4 days (last pitched Sept 30, Wild Card game)",
                "1 day (last pitched Sept 27, in relief)",
            ])


if __name__ == "__main__":
    unittest.main()
