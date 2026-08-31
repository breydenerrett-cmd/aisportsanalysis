"""Tests for the any-matchup `analyze` command (src/cli.py).

What is locked here, in the spirit of tests/test_evidence_honesty.py:
  - a real historical game resolves its own game_pk from the results store and
    renders the same per-game card the slate briefing produces;
  - a pairing with no real game on the date renders an HONEST hypothetical
    card: the starter and lineup sections carry the one named reason instead
    of fabricated data;
  - the given date is the information cutoff -- games played after it never
    reach the team-form section;
  - an unknown team abbreviation errors clearly instead of guessing;
  - the output file lands exactly where the command promises.

Every store the command reads is patched to a synthetic fixture, so the suite
never depends on what data/ happens to hold.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from src import cli

DATE = "2023-05-20"
REAL_PK = "900001"


def _row(pk, date, away, home, away_score, home_score, **extra):
    """One results-store row, string-valued like the CSV store round-trip."""
    home_won = int(home_score) > int(away_score)
    row = {
        "game_pk": str(pk), "date": date,
        "start_time_utc": f"{date}T23:10:00Z",
        "venue": "Citi Field", "game_type": "R",
        "away_team": away, "home_team": home,
        "away_team_id": "113", "home_team_id": "121",
        "away_probable": None, "home_probable": None,
        "away_probable_id": None, "home_probable_id": None,
        "away_score": str(away_score), "home_score": str(home_score),
        "winner": home if home_won else away,
        "home_won": "1" if home_won else "0",
        "total_runs": str(int(away_score) + int(home_score)),
        "run_differential": str(abs(int(home_score) - int(away_score))),
        "double_header": "N", "game_number": "1",
    }
    row.update(extra)
    return row


def _fixture_store():
    """CIN with 3 wins strictly before DATE, plus post-cutoff wins that must
    never be counted, plus the real CIN @ NYM game ON the date itself."""
    rows = [
        # CIN's point-in-time record: 3-0 before the cutoff.
        _row(1, "2023-05-10", "CIN", "PIT", 5, 2),
        _row(2, "2023-05-11", "CIN", "PIT", 4, 1),
        _row(3, "2023-05-13", "PIT", "CIN", 2, 6),
        # NYM before the cutoff: 1-1.
        _row(4, "2023-05-12", "NYM", "PHI", 3, 1),
        _row(5, "2023-05-14", "PHI", "NYM", 7, 0),
        # The real game being analysed. Its own result exists in the store and
        # must not leak into its features.
        _row(REAL_PK, DATE, "CIN", "NYM", 2, 3,
             away_probable="Aaron Away", home_probable="Henry Home",
             away_probable_id="111", home_probable_id="222"),
        # Future relative to the cutoff: 4 more CIN wins. If any of these
        # reach the card, the point-in-time contract is broken.
        _row(7, "2023-05-21", "CIN", "STL", 9, 0),
        _row(8, "2023-05-22", "CIN", "STL", 9, 0),
        _row(9, "2023-05-23", "CIN", "STL", 9, 0),
        _row(10, "2023-05-24", "CIN", "STL", 9, 0),
    ]
    return {row["game_pk"]: row for row in rows}


class AnalyzeCommandTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = _fixture_store()
        self.lineups = {}
        for target, value in (
            ("src.pipeline.history.read_results", self.store),
            ("src.pipeline.pitchers.read_logs", {}),
            ("src.pipeline.bullpen.read_log", []),
            ("src.analysis.prices.by_matchup", {}),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The lineup store is a mutable per-test fixture.
        patcher = mock.patch("src.pipeline.lineup_store.read",
                             side_effect=lambda *a, **k: self.lineups)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, away="CIN", home="NYM", date=DATE, out="__tmp__"):
        if out == "__tmp__":
            out = str(Path(self.tmp.name) / "card.html")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            code = cli.cmd_analyze(Namespace(away=away, home=home,
                                             date=date, out=out))
        return code, stdout.getvalue(), stderr.getvalue(), out

    # -- a real historical game -------------------------------------------

    def test_real_game_resolves_its_game_pk_and_renders(self):
        code, out, _, path = self._run()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn(f"real game {REAL_PK}", out)
        html = Path(path).read_text(encoding="utf-8")
        self.assertIn("CIN @ NYM", html)
        # A real game is not a hypothetical, and must never be labelled one.
        self.assertNotIn(cli.HYPOTHETICAL_GAP, html)
        # The promised path is the one printed.
        self.assertIn(path, out)

    def test_team_form_is_point_in_time_to_the_given_date(self):
        _, _, _, path = self._run()
        html = Path(path).read_text(encoding="utf-8")
        wins = re.search(r"Wins</td><td class=\"n\">(\d+)</td>"
                         r"<td class=\"n\">(\d+)</td>", html)
        self.assertIsNotNone(wins, "the teams table must render a Wins row")
        # CIN is 3-0 before the cutoff. The 4 post-cutoff wins in the store
        # must not appear; 7 here would mean future leakage.
        self.assertEqual(wins.group(1), "3")
        self.assertEqual(wins.group(2), "1")

    def test_stored_lineup_flows_through_to_the_card(self):
        self.lineups = {REAL_PK: {
            "game_pk": int(REAL_PK), "date": DATE,
            "away": [{"order": 1, "person_id": 501,
                      "name": "Fixture Batter", "position": "1B"}],
            "home": []}}
        # Matchup depth would walk the real pitch store; it is not what this
        # test is about, so it is pinned to the honest empty answer.
        with mock.patch("src.analysis.matchup.depth_by_pk", return_value={}):
            code, _, _, path = self._run()
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("Fixture Batter",
                      Path(path).read_text(encoding="utf-8"))

    # -- a hypothetical pairing -------------------------------------------

    def test_hypothetical_pairing_renders_with_named_gaps(self):
        code, out, _, path = self._run(away="CIN", home="BOS")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("no real game on this date", out)
        html = Path(path).read_text(encoding="utf-8")
        self.assertIn("CIN @ BOS", html)
        # Both the starter and the lineup section carry the one honest
        # sentence -- twice in the body, twice in the missing-data list.
        self.assertGreaterEqual(html.count(cli.HYPOTHETICAL_GAP), 2)
        # Team form still computes point-in-time for a hypothetical pairing.
        self.assertRegex(html, r"Wins</td><td class=\"n\">3</td>")

    def test_hypothetical_card_fabricates_no_starter_data(self):
        _, _, _, path = self._run(away="CIN", home="BOS")
        html = Path(path).read_text(encoding="utf-8")
        # The starter section must be the gap sentence, not a stats table.
        section = re.search(r"Starting pitchers</h3>(.*?)<h3>", html, re.S)
        self.assertIsNotNone(section)
        self.assertIn(cli.HYPOTHETICAL_GAP, section.group(1))
        self.assertNotIn("<table>", section.group(1))

    # -- errors, named clearly --------------------------------------------

    def test_unknown_team_abbreviation_errors_clearly(self):
        code, _, err, _ = self._run(away="XYZ")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("XYZ", err)
        self.assertIn("unknown team abbreviation", err)

    def test_team_cannot_play_itself(self):
        code, _, err, _ = self._run(away="NYM", home="NYM")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("cannot play itself", err)

    def test_invalid_date_errors_clearly(self):
        code, _, err, _ = self._run(date="2023-13-99")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("invalid date", err)

    def test_empty_store_errors_instead_of_guessing(self):
        with mock.patch("src.pipeline.history.read_results", return_value={}):
            code, _, err, _ = self._run()
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("historical store is empty", err)

    # -- output location and wiring ---------------------------------------

    def test_default_output_path_lands_where_promised(self):
        original = os.getcwd()
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        os.chdir(workdir.name)
        self.addCleanup(os.chdir, original)
        code, out, _, _ = self._run(out=None)
        self.assertEqual(code, cli.EXIT_OK)
        promised = Path("artifacts") / f"analyze_CIN_NYM_{DATE}.html"
        self.assertTrue(promised.exists(),
                        f"{promised} was promised but not written")
        self.assertIn(str(promised), out)

    def test_alias_abbreviations_resolve_to_canonical_teams(self):
        # The results store speaks CIN; an alias spelling must find the same
        # game rather than silently building a hypothetical for a ghost team.
        code, out, _, _ = self._run(away="cin", home="nym")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn(f"real game {REAL_PK}", out)

    def test_parser_wires_the_analyze_command(self):
        args = cli.build_parser().parse_args(
            ["analyze", "--away", "CIN", "--home", "NYM", "--date", DATE])
        self.assertEqual(args.command, "analyze")
        self.assertIs(cli.COMMANDS["analyze"], cli.cmd_analyze)
        self.assertIsNone(args.out)

    def test_find_stored_game_orders_doubleheaders(self):
        store = dict(self.store)
        store["900002"] = _row("900002", DATE, "CIN", "NYM", 1, 0,
                               game_number="2", double_header="Y")
        matches = cli._find_stored_game(store, "CIN", "NYM", DATE)
        self.assertEqual([m["game_pk"] for m in matches],
                         [REAL_PK, "900002"])
        # And the ordered pairing matters: the reverse fixture does not exist.
        self.assertEqual(cli._find_stored_game(store, "NYM", "CIN", DATE), [])


if __name__ == "__main__":
    unittest.main()
