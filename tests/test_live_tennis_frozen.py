"""The code's constants ARE the pre-registered constants (docs/PREREG_LIVE_TENNIS.md section 12).

"No rescue by threshold change" has to be a property of the repository, not a promise. This test parses the
machine-readable FROZEN_CONSTANTS block of the pre-registration and requires `config.py` to hold exactly those
values; it also pins the behaviour that makes the test safe to leave lying around: the switch defaults OFF, the
fingerprint moves when any constant moves, and the CLI wiring exists.
"""

from __future__ import annotations

import ast
import hashlib
import io
import os
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from src.research.live_tennis import config

ROOT = Path(__file__).resolve().parent.parent
PREREG = ROOT / config.PREREG_DOC


def frozen_block() -> dict:
    text = PREREG.read_text(encoding="utf-8")
    match = re.search(r"<!-- FROZEN_CONSTANTS_BEGIN -->(.*?)<!-- FROZEN_CONSTANTS_END -->", text, re.S)
    assert match, "the FROZEN_CONSTANTS block is missing from the pre-registration"
    out = {}
    for line in match.group(1).strip().splitlines():
        name, _, raw = line.partition(" = ")
        raw = raw.strip()
        try:
            out[name.strip()] = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            out[name.strip()] = raw          # a bare word or an ISO date
    return out


class FrozenConstantsTests(unittest.TestCase):
    def test_every_frozen_name_is_in_the_prereg_with_the_same_value(self):
        block = frozen_block()
        self.assertEqual(set(block), set(config.FROZEN_NAMES))
        for name, value in block.items():
            self.assertEqual(getattr(config, name), value, f"{name} differs from docs/PREREG_LIVE_TENNIS.md")
            self.assertEqual(type(getattr(config, name)), type(value), f"{name} changed type")

    def test_the_specific_numbers_the_owner_was_told(self):
        self.assertEqual(config.GAP_THRESHOLD_PP, 3.0)
        self.assertEqual((config.BET_FLOOR, config.MATCH_FLOOR), (300, 150))
        self.assertEqual((config.DAILY_CREDIT_CAP, config.MONTHLY_CREDIT_CAP), (200, 4000))
        self.assertEqual(config.REF_MIN_DELAY_SECONDS, 600)
        self.assertEqual(config.STOP_DATE, "2027-01-31")

    def test_fingerprint_is_stable_and_moves_with_any_constant(self):
        first = config.fingerprint()
        self.assertEqual(first, config.fingerprint())
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        for name in ("GAP_THRESHOLD_PP", "BET_FLOOR", "STOP_DATE", "SERVE_LEVEL_WTA"):
            original = getattr(config, name)
            changed = original + 1 if not isinstance(original, str) else original + "x"
            with mock.patch.object(config, name, changed):
                self.assertNotEqual(config.fingerprint(), first, name)
        self.assertEqual(config.fingerprint(), first)

    def test_prereg_is_on_disk_and_says_paper_only(self):
        text = PREREG.read_text(encoding="utf-8")
        self.assertIn("No real money, ever", text)
        sha = hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
        self.assertRegex(sha, r"^[0-9a-f]{64}$")


class FreezeCheckTests(unittest.TestCase):
    def test_the_prereg_file_still_hashes_to_the_registry_note(self):
        """The freeze check in the pre-registration, run as a test: edit the document and this goes red."""
        from src.research import alpha_registry
        from src.research.live_tennis import runner

        rows = [r for r in alpha_registry.read_all()
                if r.get("id") == config.REGISTRY_ID and r.get("kind") == "hypothesis"]
        self.assertEqual(len(rows), 1, "the hypothesis must be registered exactly once")
        sha = runner.prereg_sha256()
        self.assertIsNotNone(sha)
        self.assertIn(sha, rows[0]["note"])
        self.assertEqual(rows[0]["source_doc"], config.PREREG_DOC)
        self.assertEqual(rows[0]["sport"], "tennis")
        self.assertEqual(rows[0]["alpha_declared"], 0.05)


class SwitchAndWiringTests(unittest.TestCase):
    def test_the_switch_defaults_off_and_only_on_turns_it_on(self):
        self.assertFalse(config.switch_on({}))
        for value in ("", "off", "0", "false", "no", "OFF", "maybe"):
            self.assertFalse(config.switch_on({config.ENV_SWITCH: value}), value)
        for value in ("on", "ON", " on ", "1", "true", "yes"):
            self.assertTrue(config.switch_on({config.ENV_SWITCH: value}), value)

    def test_the_real_environment_is_off_during_tests(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(config.ENV_SWITCH, None)
            self.assertFalse(config.switch_on())

    def test_tour_and_format_come_from_the_key(self):
        self.assertEqual(config.tour_of("tennis_atp_vienna_open"), "atp")
        self.assertEqual(config.tour_of("tennis_wta_pan_pacific_open"), "wta")
        self.assertIsNone(config.tour_of("soccer_epl"))
        self.assertEqual(config.sets_to_win("tennis_atp_wimbledon"), 3)
        self.assertEqual(config.sets_to_win("tennis_atp_aus_open_singles"), 3)
        self.assertEqual(config.sets_to_win("tennis_wta_wimbledon"), 2)
        self.assertEqual(config.sets_to_win("tennis_atp_vienna_open"), 2)
        self.assertEqual(config.serve_level("atp"), 0.64)
        self.assertEqual(config.serve_level("wta"), 0.56)
        self.assertIsNone(config.serve_level("itf"))

    def test_cli_is_wired_and_off_makes_no_request_and_writes_nothing(self):
        from src import cli

        parser = cli.build_parser()
        args = parser.parse_args(["research", "live-tennis", "capture"])
        self.assertEqual((args.command, args.research_command, args.live_tennis_command),
                         ("research", "live-tennis", "capture"))
        self.assertIn("research", cli.COMMANDS)
        for sub in (["report"], ["grade"], ["capture", "--loop", "--max-minutes", "1"], ["capture", "--plan"]):
            parser.parse_args(["research", "live-tennis", *sub])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(config.ENV_SWITCH, None)
            # the owner may flip the switch in .env; the test must not depend on that machine's file
            with (mock.patch.object(cli, "_load_dotenv"),
                  mock.patch("src.research.live_tennis.runner.Runner") as runner_cls):
                out = io.StringIO()
                with redirect_stdout(out):
                    code = cli.main(["research", "live-tennis", "capture"])
                self.assertEqual(code, 0)
                runner_cls.assert_not_called()
                self.assertIn("OFF", out.getvalue())

    def test_switch_on_without_an_odds_key_refuses_before_any_request(self):
        from src import cli

        with (mock.patch.dict(os.environ, {config.ENV_SWITCH: "on"}, clear=False),
              mock.patch.object(cli, "_load_dotenv"),
              mock.patch("src.providers.odds.is_configured", return_value=False),
              mock.patch("src.research.live_tennis.runner.Runner") as runner_cls):
            err = io.StringIO()
            with mock.patch("sys.stderr", err):
                code = cli.main(["research", "live-tennis", "capture"])
            self.assertEqual(code, 2)
            runner_cls.assert_not_called()
            self.assertIn("ODDS_API_KEY", err.getvalue())

    def test_plan_makes_no_request_and_reports_the_switch_and_key(self):
        from src import cli

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(config.ENV_SWITCH, None)
            with (mock.patch.object(cli, "_load_dotenv"),
                  mock.patch("src.providers.odds.is_configured", return_value=True),
                  mock.patch("src.research.live_tennis.runner.Runner") as runner_cls,
                  mock.patch("src.research.live_tennis.guard.read_rows", return_value=[])):
                out = io.StringIO()
                with redirect_stdout(out):
                    code = cli.main(["research", "live-tennis", "capture", "--plan"])
        self.assertEqual(code, 0)
        runner_cls.assert_not_called()
        text = out.getvalue()
        self.assertIn("OFF (default)", text)
        self.assertIn("odds API key configured: yes", text)
        self.assertIn("no request was made", text)


if __name__ == "__main__":
    unittest.main()
