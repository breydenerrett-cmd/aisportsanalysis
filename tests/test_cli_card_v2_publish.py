"""T5 -- `src.cli.cmd_card`'s `--rule v2` branch.

Same discipline `tests/test_cli_nfl_card_publish.py` uses for the NFL
branch: call `cli.cmd_card` itself (the function a terminal actually runs)
with every provider seam mocked, so this is a fast unit test with no
network and no disk write.
"""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from src import cli


def _args(date_str="2026-09-20", dry_run=False, rule="v2", sport="mlb"):
    return argparse.Namespace(card_command="publish", sport=sport,
                              date=date_str, dry_run=dry_run, rule=rule)


def _card_payload(n_picks=1, n_fills=0, n_plus_money=0):
    pick = {
        "price_class": "MAIN", "take": True, "entry_class": "pick",
        "bet_sentence": "Yankees moneyline at -140", "books": 8,
        "failed_gates": [],
    }
    return {
        "date": "2026-09-20", "rule": "DAILY_CARD_BEST_BETS_V2",
        "games_on_slate": 1, "raw_pool_size": 1,
        "n_picks": n_picks, "n_fills": n_fills,
        "n_plus_money_picks": n_plus_money,
        "picks": [pick] if n_picks else [], "prop_picks": [], "fills": [],
        "withdrawn": [], "all_bets": [pick] if n_picks else [],
    }


class CmdCardV2BranchTests(unittest.TestCase):
    def _patched(self, payload=None, dry_run=False, publish_error=None):
        payload = payload if payload is not None else _card_payload()
        patches = [
            mock.patch("src.providers.mlb.fetch_games", return_value=[]),
            mock.patch("src.pipeline.history.read_results", return_value={}),
            mock.patch("src.pipeline.briefing.build_slate",
                      return_value={"games": []}),
            mock.patch("src.pipeline.enrichment.enrichment_inputs",
                      return_value={}),
            mock.patch("src.analysis.opportunities.build_opportunities",
                      return_value={"rows": []}),
            mock.patch("src.report.card_v2.card_v2_for_date",
                      return_value=payload),
        ]
        if publish_error is None:
            patches.append(mock.patch(
                "src.appstate.card_ledger.publish_v2",
                return_value={"n_picks": payload["n_picks"],
                             "n_fills": payload["n_fills"],
                             "already_published": False}))
        return patches

    def test_dry_run_never_calls_publish_v2(self):
        with mock.patch("src.appstate.card_ledger.publish_v2",
                        side_effect=AssertionError("publish_v2 called on dry-run")):
            for p in self._patched(dry_run=True)[:-1]:
                p.start()
                self.addCleanup(p.stop)
            out = io.StringIO()
            with redirect_stdout(out):
                result = cli.cmd_card(_args(dry_run=True))
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("--dry-run: nothing written.", out.getvalue())

    def test_a_real_run_calls_publish_v2_and_prints_the_pick(self):
        for p in self._patched(dry_run=False):
            p.start()
            self.addCleanup(p.stop)
        out = io.StringIO()
        with redirect_stdout(out):
            result = cli.cmd_card(_args(dry_run=False))
        text = out.getvalue()
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("THE CARD (v2 preview)", text)
        self.assertIn("Yankees moneyline at -140", text)
        self.assertIn("published: 1 pick(s)", text)

    def test_rule_v2_is_mlb_only(self):
        out = io.StringIO()
        with redirect_stdout(io.StringIO()):
            result = cli.cmd_card(_args(sport="nfl", rule="v2"))
        self.assertEqual(result, cli.EXIT_ERROR)

    def test_a_missing_frozen_parameter_file_prints_an_error_not_a_traceback(self):
        from src.report import card_v2 as card_v2_mod

        with mock.patch("src.providers.mlb.fetch_games", return_value=[]), \
             mock.patch("src.pipeline.history.read_results", return_value={}), \
             mock.patch("src.pipeline.briefing.build_slate",
                       return_value={"games": []}), \
             mock.patch("src.pipeline.enrichment.enrichment_inputs",
                       return_value={}), \
             mock.patch("src.analysis.opportunities.build_opportunities",
                       return_value={"rows": []}), \
             mock.patch("src.report.card_v2.card_v2_for_date",
                       side_effect=card_v2_mod.CardV2Error("missing frozen file")):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                result = cli.cmd_card(_args(dry_run=True))
        self.assertEqual(result, cli.EXIT_ERROR)
        self.assertIn("ERROR", err.getvalue())

    def test_default_rule_is_v1_and_never_touches_card_v2(self):
        with mock.patch("src.report.card_v2.card_v2_for_date",
                        side_effect=AssertionError("v2 called on default rule")):
            args = argparse.Namespace(card_command="publish", sport="mlb",
                                      date="2026-09-20", dry_run=True,
                                      rule=None)
            with mock.patch("src.providers.mlb.fetch_games",
                            side_effect=cli.mlb.MLBError("stop before v1's own network call")):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    result = cli.cmd_card(args)
        # Reaches v1's OWN error path (a real network call this test
        # refuses), never `card_v2_for_date` -- proving the branch was
        # never entered rather than merely not asserted on.
        self.assertEqual(result, cli.EXIT_ERROR)
        self.assertIn("ERROR", err.getvalue())


if __name__ == "__main__":
    unittest.main()
