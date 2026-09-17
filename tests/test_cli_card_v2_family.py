"""T5 -- `src.cli.cmd_card`'s shadow-a/shadow-c/shadow-e/all rules, for both
`publish` and `settle`.

Same discipline as `tests/test_cli_card_v2_publish.py` (which this file
does not duplicate -- it covers `--rule v2` alone): call `cli.cmd_card`
itself with every provider seam mocked, no network, no disk write.
"""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from src import cli


def _publish_args(date_str="2026-09-20", dry_run=False, rule="shadow-a",
                  sport="mlb"):
    return argparse.Namespace(card_command="publish", sport=sport,
                              date=date_str, dry_run=dry_run, rule=rule)


def _settle_args(date_str="2026-09-20", rule="v2", sport="mlb"):
    return argparse.Namespace(card_command="settle", sport=sport,
                              date=date_str, rule=rule)


def _card_payload(rule="DAILY_CARD_BEST_BETS_V2_SHADOW_A_BAND_ONLY", n_picks=1):
    pick = {
        "price_class": "MAIN", "take": True, "entry_class": "pick",
        "bet_sentence": "Yankees moneyline at -140", "books": 8,
        "failed_gates": [],
    }
    return {
        "date": "2026-09-20", "rule": rule,
        "games_on_slate": 1, "raw_pool_size": 1,
        "n_picks": n_picks, "n_fills": 0, "n_plus_money_picks": 0,
        "picks": [pick] if n_picks else [], "prop_picks": [], "fills": [],
        "withdrawn": [], "all_bets": [pick] if n_picks else [],
    }


def _publish_patches(payload=None):
    payload = payload if payload is not None else _card_payload()
    return [
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
        mock.patch("src.appstate.card_ledger.publish_v2",
                  return_value={"n_picks": payload["n_picks"], "n_fills": 0,
                               "already_published": False}),
    ]


class ShadowRulePublishTests(unittest.TestCase):
    """--rule shadow-a / shadow-c / shadow-e: same shape as --rule v2, one
    rule at a time, its own store (mocked away; only the call is checked)."""

    def _run(self, rule):
        patches = _publish_patches(_card_payload())
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        out = io.StringIO()
        with redirect_stdout(out):
            result = cli.cmd_card(_publish_args(rule=rule))
        return result, out.getvalue()

    def test_shadow_a_publishes_and_labels_itself(self):
        result, text = self._run("shadow-a")
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("THE CARD (shadow-a)", text)
        self.assertIn("published: 1 pick(s)", text)

    def test_shadow_c_publishes_and_labels_itself(self):
        result, text = self._run("shadow-c")
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("THE CARD (shadow-c)", text)

    def test_shadow_e_publishes_and_labels_itself(self):
        result, text = self._run("shadow-e")
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("THE CARD (shadow-e)", text)

    def test_shadow_rules_are_mlb_only(self):
        with mock.patch("src.providers.mlb.fetch_games", return_value=[]):
            result = cli.cmd_card(_publish_args(rule="shadow-a", sport="nfl"))
        self.assertEqual(result, cli.EXIT_ERROR)

    def test_there_is_no_shadow_d_choice(self):
        parser = cli.build_parser()
        with self.assertRaises(SystemExit):
            with redirect_stderr(io.StringIO()):
                parser.parse_args(["card", "publish", "--date", "2026-09-20",
                                   "--rule", "shadow-d"])


class AllRulePublishTests(unittest.TestCase):
    def test_all_publishes_v1_and_every_v2_family_rule(self):
        patches = _publish_patches(_card_payload())
        # `card_for_date`/`publish_all` are V1's + the orchestrator's own
        # calls, mocked separately from the v2-family seam above.
        patches += [
            mock.patch("src.report.card.card_for_date",
                      return_value={"date": "2026-09-20", "picks": [],
                                   "reason": "no card"}),
            mock.patch("src.report.card.publish_all",
                      return_value={
                          "v1": {"picks": [], "already_published": False},
                          "v2": {"n_picks": 1, "n_fills": 0},
                          "shadow-a": {"n_picks": 1, "n_fills": 0},
                          "shadow-c": {"n_picks": 0, "n_fills": 0},
                          "shadow-e": {"n_picks": 0, "n_fills": 0},
                      }),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        out = io.StringIO()
        with redirect_stdout(out):
            result = cli.cmd_card(_publish_args(rule="all"))
        text = out.getvalue()
        self.assertEqual(result, cli.EXIT_OK)
        for name in ("v1", "v2", "shadow-a", "shadow-c", "shadow-e"):
            self.assertIn(name, text)
        self.assertNotIn("shadow-d", text)

    def test_all_dry_run_never_calls_publish_all(self):
        patches = _publish_patches(_card_payload())
        patches.append(mock.patch(
            "src.report.card.card_for_date",
            return_value={"date": "2026-09-20", "picks": [], "reason": "x"}))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch("src.report.card.publish_all",
                        side_effect=AssertionError("publish_all called on dry-run")):
            out = io.StringIO()
            with redirect_stdout(out):
                result = cli.cmd_card(_publish_args(rule="all", dry_run=True))
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("--dry-run: nothing written.", out.getvalue())


class V2FamilySettleTests(unittest.TestCase):
    def test_settle_v2_calls_settle_v2_on_its_own_store(self):
        with mock.patch("src.pipeline.history.read_results",
                        return_value={"1": {"date": "2026-09-20",
                                            "game_pk": 1}}), \
             mock.patch("src.pipeline.boxscores.read", return_value=[]), \
             mock.patch("src.appstate.card_ledger.settle_v2",
                        return_value={"wins": 1, "losses": 0, "pushes": 0}) as settle_v2:
            out = io.StringIO()
            with redirect_stdout(out):
                result = cli.cmd_card(_settle_args(rule="v2"))
        self.assertEqual(result, cli.EXIT_OK)
        settle_v2.assert_called_once()
        self.assertIn("v2: settled", out.getvalue())

    def test_settle_all_settles_v2_and_every_shadow_not_v1(self):
        with mock.patch("src.pipeline.history.read_results",
                        return_value={"1": {"date": "2026-09-20",
                                            "game_pk": 1}}), \
             mock.patch("src.pipeline.boxscores.read", return_value=[]), \
             mock.patch("src.appstate.card_ledger.settle_v2",
                        return_value={"wins": 0, "losses": 1, "pushes": 0}) as settle_v2, \
             mock.patch("src.appstate.card_ledger.settle",
                        side_effect=AssertionError("V1 settle called by --rule all")):
            out = io.StringIO()
            with redirect_stdout(out):
                result = cli.cmd_card(_settle_args(rule="all"))
        self.assertEqual(result, cli.EXIT_OK)
        self.assertEqual(settle_v2.call_count, 4)  # v2 + 3 shadows, no shadow-d
        text = out.getvalue()
        for name in ("v2", "shadow-a", "shadow-c", "shadow-e"):
            self.assertIn(name, text)
        self.assertNotIn("shadow-d", text)

    def test_settle_default_rule_v1_unchanged(self):
        with mock.patch("src.appstate.card_ledger.settle_v2",
                        side_effect=AssertionError("v2 settle called on default rule")), \
             mock.patch("src.pipeline.history.read_results", return_value={}):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                result = cli.cmd_card(_settle_args(rule="v1"))
        self.assertEqual(result, cli.EXIT_ERROR)
        self.assertIn("historical store is empty", err.getvalue())


if __name__ == "__main__":
    unittest.main()
