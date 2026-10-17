"""`card publish` for MLB after the value-picks pause cut-off (owner decision
2026-10-16, docs/decisions/MLB_VALUE_PICKS_PAUSED.md).

WHAT IS PINNED
--------------
  * a date AFTER config/mlb_public_card.json's date, under rule v1 (the default
    afternoon_slate.sh runs) and rule v2: no schedule fetch, no board build, no
    ledger write of any kind, one `  no card:` line, exit 0;
  * under `--rule all` (what capture_slot.sh runs every slot): V1 and V2 are
    NOT published, the three registered shadows (A, C, E) ARE, each into its
    own store and never into the V1 or V2 store; `--dry-run` writes nothing;
  * `--rule shadow-*` on its own is not public and is untouched;
  * a date ON or BEFORE the cut-off goes through exactly the code it always
    did (the existing card tests cover that path in depth; here it is shown to
    call the publishers);
  * the printed line is one both shell scripts already treat as a fact about
    the slate and not a failure: it matches the `grep -q "^  no card:"` that
    scripts/afternoon_slate.sh runs (read out of the script itself), and the
    command exits 0, which is all capture_slot.sh needs (`|| true`);
  * a missing or malformed config pauses the same dates (the fallback is the
    owner's date), and a good config moves the line;
  * sports other than MLB are not affected.

No network, no disk write: every provider seam is mocked and the config is a
temp file.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from src import cli
from src.appstate import card_ledger
from src.appstate import mlb_public_card as mpc

ROOT = Path(__file__).resolve().parent.parent
AFTERNOON = ROOT / "scripts" / "afternoon_slate.sh"
CAPTURE = ROOT / "scripts" / "capture_slot.sh"

PAUSED_DATE = "2026-10-17"
LAST_PUBLIC = "2026-10-16"
NO_CARD_LINE = ("  no card: value picks paused after 2026-10-16 "
                "(config/mlb_public_card.json)")


def _args(date_str=PAUSED_DATE, rule="v1", dry_run=False, sport="mlb"):
    return argparse.Namespace(card_command="publish", sport=sport, date=date_str,
                              dry_run=dry_run, rule=rule)


def _v2_card(rule="X"):
    pick = {"price_class": "MAIN", "take": True, "entry_class": "pick",
            "bet_sentence": "Yankees moneyline at -140", "books": 8, "failed_gates": []}
    return {"date": PAUSED_DATE, "rule": rule, "games_on_slate": 1, "raw_pool_size": 1,
            "n_picks": 1, "n_fills": 0, "n_plus_money_picks": 0, "picks": [pick],
            "prop_picks": [], "fills": [], "withdrawn": [], "all_bets": [pick]}


V1_EMPTY = {"date": PAUSED_DATE, "picks": [], "reason": "no card", "games_on_slate": 1,
            "games_open": 1, "games_started": 0, "calibrated": True}


class _Case(unittest.TestCase):
    def setUp(self):
        mpc._WARNED.clear()
        self.p = {}
        for name, target, kwargs in (
            ("fetch", "src.providers.mlb.fetch_games", {"return_value": []}),
            ("results", "src.pipeline.history.read_results", {"return_value": {}}),
            ("slate", "src.pipeline.briefing.build_slate", {"return_value": {"games": []}}),
            ("enrich", "src.pipeline.enrichment.enrichment_inputs", {"return_value": {}}),
            ("opps", "src.analysis.opportunities.build_opportunities", {"return_value": {"rows": []}}),
            ("v2card", "src.report.card_v2.card_v2_for_date", {"return_value": _v2_card()}),
            ("v1card", "src.report.card.card_for_date", {"return_value": V1_EMPTY}),
            ("publish_all", "src.report.card.publish_all", {"return_value": {}}),
            ("publish_v2", "src.appstate.card_ledger.publish_v2",
             {"return_value": {"n_picks": 1, "n_fills": 0, "already_published": False}}),
            ("publish_v1", "src.appstate.card_ledger.publish",
             {"return_value": {"picks": [], "already_published": False}}),
        ):
            patcher = mock.patch(target, **kwargs)
            self.p[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, **kwargs):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.cmd_card(_args(**kwargs))
        return code, out.getvalue()

    def assert_nothing_built_or_written(self):
        for name in ("fetch", "slate", "opps", "v2card", "v1card", "publish_all",
                     "publish_v2", "publish_v1"):
            self.p[name].assert_not_called()

    def published_stores(self):
        return [call.kwargs.get("path") for call in self.p["publish_v2"].call_args_list]


class ThePausedDefaultAndV2Rules(_Case):
    def test_default_rule_writes_nothing_and_says_why(self):
        code, text = self.run_cli(rule="v1")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn(NO_CARD_LINE, text.splitlines())
        self.assert_nothing_built_or_written()

    def test_rule_v2_writes_nothing_and_says_why(self):
        code, text = self.run_cli(rule="v2")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn(NO_CARD_LINE, text.splitlines())
        self.assert_nothing_built_or_written()

    def test_the_rule_is_defaulted_the_way_the_afternoon_script_calls_it(self):
        """afternoon_slate.sh passes no --rule; the parser's default must land
        in the paused branch."""
        parsed = cli.build_parser().parse_args(["card", "publish", "--date", PAUSED_DATE])
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.cmd_card(parsed)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn(NO_CARD_LINE, out.getvalue().splitlines())
        self.assert_nothing_built_or_written()

    def test_dry_run_is_the_same_and_far_future_dates_too(self):
        for date_str in ("2026-10-17", "2026-12-31", "2099-01-01"):
            for rule in ("v1", "v2"):
                with self.subTest(date_str=date_str, rule=rule):
                    code, text = self.run_cli(date_str=date_str, rule=rule, dry_run=True)
                    self.assertEqual(code, cli.EXIT_OK)
                    self.assertIn(NO_CARD_LINE, text.splitlines())
        self.assert_nothing_built_or_written()


class ThePausedAllRule(_Case):
    def test_v1_and_v2_are_not_published_and_the_three_shadows_are(self):
        code, text = self.run_cli(rule="all")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn(NO_CARD_LINE, text.splitlines())
        self.p["publish_all"].assert_not_called()      # publish_all always carries V1 and V2
        self.p["publish_v1"].assert_not_called()
        self.p["v1card"].assert_not_called()
        self.assertEqual(self.p["publish_v2"].call_count, 3)
        self.assertEqual(
            self.published_stores(),
            [card_ledger.CARD_STORE_V2_SHADOW_A, card_ledger.CARD_STORE_V2_SHADOW_C,
             card_ledger.CARD_STORE_V2_SHADOW_E])
        self.assertNotIn(card_ledger.CARD_STORE_V2, self.published_stores())

    def test_only_the_shadow_rule_params_are_built(self):
        from src.analysis import best_bets_card
        self.run_cli(rule="all")
        built = [call.kwargs["params"] for call in self.p["v2card"].call_args_list]
        self.assertEqual(built, [best_bets_card.SHADOW_A, best_bets_card.SHADOW_C,
                                 best_bets_card.SHADOW_E])
        self.assertNotIn(best_bets_card.V2, built)

    def test_each_shadow_reports_itself_and_no_v1_or_v2_line(self):
        _code, text = self.run_cli(rule="all")
        for name in ("shadow-a", "shadow-c", "shadow-e"):
            self.assertIn(f"  {name}: published 1 pick(s)", text)
        self.assertNotIn("  v2: published", text)
        self.assertNotIn("  v1: published", text)
        self.assertNotIn("shadow-d", text)

    def test_dry_run_writes_nothing(self):
        code, text = self.run_cli(rule="all", dry_run=True)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn(NO_CARD_LINE, text.splitlines())
        self.assertIn("--dry-run: nothing written.", text)
        self.p["publish_v2"].assert_not_called()
        self.p["publish_all"].assert_not_called()

    def test_a_shadow_that_cannot_be_built_does_not_stop_the_others(self):
        from src.report import card_v2
        good = _v2_card()
        self.p["v2card"].side_effect = [card_v2.CardV2Error("no params"), good, good]
        code, _text = self.run_cli(rule="all")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(self.p["publish_v2"].call_count, 2)

    def test_a_single_shadow_rule_is_not_public_and_is_untouched(self):
        code, text = self.run_cli(rule="shadow-a")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("THE CARD (shadow-a)", text)
        self.assertNotIn("value picks paused", text)
        self.assertEqual(self.published_stores(), [card_ledger.CARD_STORE_V2_SHADOW_A])


class OnAndBeforeTheCutOffNothingChanges(_Case):
    def test_rule_v2_still_publishes_on_the_cut_off_day(self):
        code, text = self.run_cli(date_str=LAST_PUBLIC, rule="v2")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertNotIn("value picks paused", text)
        self.p["fetch"].assert_called_once()
        self.assertEqual(self.published_stores(), [card_ledger.CARD_STORE_V2])

    def test_rule_all_still_publishes_every_rule_through_publish_all(self):
        self.p["publish_all"].return_value = {
            "v1": {"picks": []}, "v2": {"n_picks": 1}, "shadow-a": {"n_picks": 1},
            "shadow-c": {"n_picks": 0}, "shadow-e": {"n_picks": 0}}
        for date_str in (LAST_PUBLIC, "2026-10-15", "2026-09-22"):
            with self.subTest(date_str):
                self.p["publish_all"].reset_mock()
                code, text = self.run_cli(date_str=date_str, rule="all")
                self.assertEqual(code, cli.EXIT_OK)
                self.assertNotIn("value picks paused", text)
                self.p["publish_all"].assert_called_once()
                self.assertIsNotNone(self.p["publish_all"].call_args.kwargs["v1_card"])

    def test_the_default_rule_still_builds_and_freezes_a_card(self):
        card = {**V1_EMPTY, "picks": [{"rank": 1, "label": "STRONG", "bet": "Yankees ML",
                                        "book": "x", "books": 5}]}
        self.p["v1card"].return_value = card
        with mock.patch("src.report.card.freeze_window",
                        return_value={"ready": True, "reason": ""}), \
                mock.patch("src.report.card.v1_store_path", return_value="v1.jsonl"):
            code, text = self.run_cli(date_str=LAST_PUBLIC, rule="v1")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertNotIn("value picks paused", text)
        self.p["publish_v1"].assert_called_once()


class TheConfigDecidesAndFailsClosed(_Case):
    def use_config(self, content):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "mlb_public_card.json"
        if content is not None:
            path.write_text(content, encoding="utf-8")
        patcher = mock.patch.object(mpc, "config_path", return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_later_date_in_the_config_publishes_up_to_it(self):
        self.use_config(json.dumps({mpc.CONFIG_KEY: "2026-10-20"}))
        _code, text = self.run_cli(date_str="2026-10-20", rule="v2")
        self.assertNotIn("value picks paused", text)
        self.assertEqual(self.p["publish_v2"].call_count, 1)
        self.p["publish_v2"].reset_mock()
        _code, text = self.run_cli(date_str="2026-10-21", rule="v2")
        self.assertIn("  no card: value picks paused after 2026-10-20 "
                      "(config/mlb_public_card.json)", text.splitlines())
        self.p["publish_v2"].assert_not_called()

    def test_a_missing_or_malformed_config_still_pauses_later_dates(self):
        for name, content in (("missing", None), ("not json", "{ nope"), ("empty", ""),
                              ("no key", "{}"), ("bad date", json.dumps({mpc.CONFIG_KEY: "soon"}))):
            with self.subTest(name):
                mpc._WARNED.clear()
                self.use_config(content)
                self.p["publish_v2"].reset_mock()
                code, text = self.run_cli(date_str=PAUSED_DATE, rule="v2")
                self.assertEqual(code, cli.EXIT_OK)
                self.assertIn(NO_CARD_LINE, text.splitlines())
                self.p["publish_v2"].assert_not_called()

    def test_a_missing_config_still_publishes_the_cut_off_day(self):
        self.use_config(None)
        _code, text = self.run_cli(date_str=LAST_PUBLIC, rule="v2")
        self.assertNotIn("value picks paused", text)
        self.assertEqual(self.p["publish_v2"].call_count, 1)


class OtherSportsAreNotTouched(_Case):
    def test_nfl_after_the_cut_off_goes_through_its_own_publisher(self):
        card = {"picks": [], "reason": "no priced board"}
        with mock.patch("src.report.nfl_card.card_to_publish", return_value=card) as nfl:
            code, text = self.run_cli(rule="v1", sport="nfl")
        self.assertEqual(code, cli.EXIT_OK)
        nfl.assert_called_once()
        self.assertIn("  no card: no priced board", text)
        self.assertNotIn("value picks paused", text)

    def test_mma_after_the_cut_off_goes_through_its_own_publisher(self):
        card = {"picks": [], "reason": "no bouts"}
        with mock.patch("src.report.ufc_card.card_to_publish", return_value=card) as ufc:
            code, text = self.run_cli(rule="v1", sport="mma")
        self.assertEqual(code, cli.EXIT_OK)
        ufc.assert_called_once()
        self.assertNotIn("value picks paused", text)


class TheShellScriptsReadThePausedRunAsNotAnError(_Case):
    """A bash-free check: the two scripts' own conditions, taken from the
    scripts, applied to what the command printed."""

    def test_afternoon_slate_matches_the_line_as_a_no_card_fact(self):
        text = AFTERNOON.read_text(encoding="utf-8")
        found = re.search(r'grep -q "(\^  no card:)"', text)
        self.assertIsNotNone(found, "afternoon_slate.sh no longer greps for the no-card line")
        pattern = found.group(1)
        # the script runs the command with no `|| true`, so the exit status is
        # what decides ESCALATE; it must be 0
        self.assertIn('CARD_OUT=$(python3 -m src.cli card publish --date "$TODAY" 2>&1)', text)
        code, out = self.run_cli(rule="v1")
        self.assertEqual(code, 0)
        self.assertTrue(any(re.search(pattern, line) for line in out.splitlines()),
                        "the paused line is not read as `no card:` by afternoon_slate.sh")

    def test_capture_slot_calls_rule_all_and_ignores_the_exit_code(self):
        text = CAPTURE.read_text(encoding="utf-8")
        call = 'CARD_OUT=$(python3 -m src.cli card publish --date "$SLATE_DATE" --rule all 2>&1) || true'
        self.assertIn(call, text)
        code, _out = self.run_cli(rule="all")
        self.assertEqual(code, 0)

    def test_the_line_is_not_an_error_shaped_line(self):
        _code, out = self.run_cli(rule="v1")
        for line in out.splitlines():
            self.assertFalse(line.startswith(("ERROR", "ESCALATE", "Traceback")), line)


if __name__ == "__main__":
    unittest.main()
