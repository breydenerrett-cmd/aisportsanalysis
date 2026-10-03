"""`python -m src.datasvc.cli nfl backfill|update|status|matchup`, beside the UFC subcommands, offline.

The parser is tested directly; the handlers run with the pipeline or the store replaced by fakes, so
nothing touches the network or data/datasvc/nfl; and one test runs the real command in a subprocess
against a temporary AISPORTS_DATA_DIR holding the synthetic league.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from src.datasvc import cli
from src.datasvc.nfl import cli as nfl_cli
from src.datasvc.nfl import pipeline
from tests import _nfl_world as W
from tests.test_datasvc_nfl_features import G

REPO = Path(__file__).resolve().parents[1]


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    return code, out.getvalue()


class TheParser(unittest.TestCase):
    def parse(self, *argv):
        return cli.build_parser().parse_args(list(argv))

    def test_backfill_takes_since_or_seasons_and_a_player_window(self):
        a = self.parse("nfl", "backfill", "--since", "2021", "--player-since", "2024", "--max-requests", "50", "--delay", "1")
        self.assertEqual((a.sport, a.command, a.since, a.seasons, a.player_since, a.max_requests, a.delay),
                         ("nfl", "backfill", 2021, None, 2024, 50, 1.0))
        self.assertIs(a.func, nfl_cli.cmd_backfill)
        b = self.parse("nfl", "backfill", "--seasons", "2026,2025")
        self.assertEqual((b.since, b.seasons, b.player_since, b.max_requests, b.delay), (None, "2026,2025", None, None, 0.35))

    def test_since_and_seasons_are_exclusive_and_one_is_required(self):
        for argv in (("nfl", "backfill"), ("nfl", "backfill", "--since", "2021", "--seasons", "2025")):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                self.parse(*argv)
            self.assertEqual(caught.exception.code, 2)

    def test_update_status_and_matchup(self):
        self.assertEqual((self.parse("nfl", "update").today, self.parse("nfl", "update", "--today", "2026-10-03").today),
                         (None, "2026-10-03"))
        self.assertFalse(self.parse("nfl", "status").check)
        self.assertTrue(self.parse("nfl", "status", "--check").check)
        m = self.parse("nfl", "matchup", "KC", "BUF", "--season", "2026", "--week", "5", "--as-of", "2026-10-11")
        self.assertEqual((m.a, m.b, m.season, m.week, m.as_of, m.game_id), ("KC", "BUF", 2026, 5, "2026-10-11", None))
        g = self.parse("nfl", "matchup", "--game-id", "2026_05_TB_DAL")
        self.assertEqual((g.a, g.b, g.game_id), (None, None, "2026_05_TB_DAL"))

    def test_the_ufc_subcommands_are_exactly_as_they_were(self):
        a = self.parse("ufc", "backfill", "--since", "2019", "--no-profiles", "--max-requests", "9")
        self.assertEqual((a.sport, a.command, a.since, a.years, a.no_profiles, a.max_requests), ("ufc", "backfill", 2019, None, True, 9))
        self.assertIs(a.func, cli.cmd_backfill)
        self.assertIs(self.parse("ufc", "update").func, cli.cmd_update)
        self.assertIs(self.parse("ufc", "status").func, cli.cmd_status)
        m = self.parse("ufc", "matchup", "Alex Archer", "Ben Brawler", "--as-of", "2026-07-01")
        self.assertEqual((m.a, m.b, m.as_of), ("Alex Archer", "Ben Brawler", "2026-07-01"))
        self.assertIs(m.func, cli.cmd_matchup)

    def test_a_sport_is_required_and_an_unknown_one_is_refused(self):
        for argv in ((), ("tennis", "status")):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.parse(*argv)


class BackfillAndUpdateHandlers(unittest.TestCase):
    def fake_summary(self, **over):
        return dict({"kind": "backfill", "seasons": [], "errors": [], "stopped": None, "per_season": {}}, **over)

    def test_since_runs_every_season_through_the_current_one(self):
        with mock.patch.object(pipeline, "backfill", return_value=self.fake_summary()) as backfill, \
                mock.patch.object(pipeline, "current_season", return_value=2026):
            code, out = run_main(["nfl", "backfill", "--since", "2024", "--player-since", "2025", "--max-requests", "7"])
        self.assertEqual(code, 0)
        args, kwargs = backfill.call_args
        self.assertEqual(args[0], [2024, 2025, 2026])
        self.assertEqual(kwargs["player_since"], 2025)
        self.assertEqual(kwargs["fetcher"].max_requests, 7)
        self.assertEqual(kwargs["fetcher"].delay_s, 0.35)
        self.assertEqual(json.loads(out)["kind"], "backfill")

    def test_seasons_runs_exactly_those(self):
        with mock.patch.object(pipeline, "backfill", return_value=self.fake_summary()) as backfill:
            run_main(["nfl", "backfill", "--seasons", "2026, 2025"])
        self.assertEqual(backfill.call_args[0][0], [2026, 2025])
        self.assertIsNone(backfill.call_args[1]["player_since"])

    def test_a_browser_check_is_exit_code_two_and_errors_are_shown(self):
        summary = self.fake_summary(stopped="source blocked: the source served a browser check", errors=["season 2025: boom"])
        with mock.patch.object(pipeline, "backfill", return_value=summary):
            code, out = run_main(["nfl", "backfill", "--seasons", "2025"])
        self.assertEqual(code, 2)
        self.assertIn("1 error(s); first: ['season 2025: boom']", out)

    def test_a_request_cap_is_not_a_failure(self):
        summary = self.fake_summary(stopped="request cap reached (x); run again to continue")
        with mock.patch.object(pipeline, "backfill", return_value=summary):
            self.assertEqual(run_main(["nfl", "backfill", "--seasons", "2025"])[0], 0)

    def test_update_passes_today_through(self):
        with mock.patch.object(pipeline, "update", return_value=self.fake_summary(kind="update")) as update:
            code, _ = run_main(["nfl", "update", "--today", "2026-10-03", "--delay", "0.5"])
        self.assertEqual(code, 0)
        self.assertEqual(update.call_args[0][0], date(2026, 10, 3))
        self.assertEqual(update.call_args[1]["fetcher"].delay_s, 0.5)
        with mock.patch.object(pipeline, "update", return_value=self.fake_summary(kind="update")) as update:
            run_main(["nfl", "update"])
        self.assertIsNone(update.call_args[0][0])


class StatusAndMatchupHandlers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = W.build_world(Path(self._tmp.name) / "nfl")
        self.patch = mock.patch.object(nfl_cli, "NflStore", lambda: self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_status_prints_each_datasets_count_and_newest_from_the_store_it_opened(self):
        code, out = run_main(["nfl", "status"])
        self.assertEqual(code, 0)
        status = json.loads(out)
        self.assertEqual((status["games"]["records"], status["team_games"]["records"], status["player_games"]["records"],
                          status["injuries"]["records"]), (15, 30, 15, 8))
        self.assertEqual(status["games"]["newest"], "2025-10-19T13:30:00Z")

    def test_status_check_is_exit_one_when_a_check_fails_and_zero_when_none_does(self):
        code, out = run_main(["nfl", "status", "--check"])           # the world store has no manifest and no 2024 players
        self.assertEqual(code, 1)
        report = json.loads(out[out.index('{\n "ok"'):])
        self.assertFalse(report["ok"])
        with mock.patch.object(pipeline, "check", return_value={"ok": True, "checks": []}) as check:
            self.assertEqual(run_main(["nfl", "status", "--check"])[0], 0)
        self.assertIs(check.call_args[0][0], self.store)              # the check ran over the store the command opened

    def test_matchup_by_two_teams_prints_the_sheet(self):
        code, out = run_main(["nfl", "matchup", "KC", "BUF", "--season", "2025", "--week", "1"])
        self.assertEqual(code, 0)
        sheet = json.loads(out)
        self.assertEqual(sheet["game"]["game_id"], G["g03"])
        self.assertEqual(sheet["as_of_source"], "kickoff")
        self.assertEqual((sheet["home"]["team"], sheet["away"]["team"]), ("KC", "BUF"))

    def test_matchup_by_game_id_and_with_an_earlier_as_of(self):
        code, out = run_main(["nfl", "matchup", "--game-id", G["g14"], "--as-of", "2025-10-01"])
        self.assertEqual(code, 0)
        sheet = json.loads(out)
        self.assertEqual((sheet["game"]["game_id"], sheet["as_of"], sheet["as_of_source"]),
                         (G["g14"], "2025-10-01T00:00:00Z", "argument"))

    def test_matchup_errors_are_exit_two_with_a_message(self):
        for argv, text in ((["nfl", "matchup"], "give two teams"),
                           (["nfl", "matchup", "KC"], "give two teams"),
                           (["nfl", "matchup", "--game-id", "2099_01_AAA_BBB"], "no game"),
                           (["nfl", "matchup", "KC", "ZZZ"], "no team"),
                           (["nfl", "matchup", "KC", "Chiefs"], "does not play itself"),
                           (["nfl", "matchup", "--game-id", G["g05"], "--as-of", "2030-01-01"], "after the kickoff"),
                           (["nfl", "matchup", "KC", "BUF", "--season", "2024", "--week", "1"], "no game between")):
            code, out = run_main(argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(text, out, argv)


class TheRealCommandInASubprocess(unittest.TestCase):
    """Run `python -m src.datasvc.cli nfl ...` for real, against a data directory holding the league."""

    def run_cli(self, data_root, *argv):
        env = dict(os.environ, AISPORTS_DATA_DIR=str(data_root), PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, "-m", "src.datasvc.cli", *argv], cwd=REPO, env=env, capture_output=True,
                              text=True, timeout=120)

    def test_status_check_and_matchup_run_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = W.build_world(Path(tmp) / "datasvc" / "nfl")
            pipeline.backfill((2025, 2024), fetcher=W.FakeFetcher(W.source_files()), store=store, today=date(2025, 10, 20),
                              log=lambda m: None, player_since=2025)
            status = self.run_cli(tmp, "nfl", "status", "--check")
            self.assertEqual(status.returncode, 0, status.stderr[-800:])
            text = status.stdout
            self.assertIn('"records": 15', text)
            self.assertIn('"ok": true', text)
            sheet = self.run_cli(tmp, "nfl", "matchup", "KC", "BUF", "--season", "2025", "--week", "1")
            self.assertEqual(sheet.returncode, 0, sheet.stderr[-800:])
            self.assertEqual(json.loads(sheet.stdout)["game"]["game_id"], G["g03"])
            bad = self.run_cli(tmp, "nfl", "matchup", "KC", "ZZZ")
            self.assertEqual(bad.returncode, 2)

    def test_the_help_lists_both_sports(self):
        result = self.run_cli(tempfile.gettempdir(), "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("ufc", result.stdout)
        self.assertIn("nfl", result.stdout)


if __name__ == "__main__":
    unittest.main()
