"""The UFC favourites pause (owner decision 2026-10-03): the one config value,
the helper that reads it, the sentence a reader sees, and the decision note.

WHAT THIS PINS
--------------
  * config/ufc_public_card.json says what the brief says, and its path is
    anchored at the repository root, never the working directory;
  * a missing, unreadable, malformed or nonsensical config falls back to the
    owner's own date (2026-10-03), never to "no pause" -- the deployed image did
    not copy config/ when this was written, so that state is real;
  * a date after the last public date is paused, a date on or before it is not,
    and a string that is not a date is never "after" anything;
  * the reason is the sentence the owner approved, in plain words, with no
    claim about results or returns;
  * the CLI scripts/capture_slot.sh reads prints one date and exits 0, from any
    working directory;
  * the decision note exists and says what it has to say.

Every config these tests read is a temp file passed in by path. The only real
file read is the committed one, by the tests that are about the committed one.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.appstate import ufc_public_card as upc
from tests.test_customer_language import _violations_in
from tests.test_no_nothing_clears_the_bar import BANNED_JARGON, BANNED_PHRASES, _normalise

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "ufc_public_card.json"
DOC = ROOT / "docs" / "decisions" / "UFC_FAVOURITES_PAUSED.md"

# The sentence from the brief, written out in full here on purpose: if the
# constant is ever reworded this fails, and a reworded sentence is the owner's
# call, not a refactor's.
THE_REASON = (
    "UFC picks are paused. The old rule took the betting favourite in every "
    "fight, which is not analysis. Picks come back when each fight has a real "
    "breakdown behind it. Every UFC pick made so far stays on the record page."
)

EM_DASH = chr(0x2014)       # written as a number so this file carries no dash itself
EN_DASH = chr(0x2013)


class _TempConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        # one warning per problem is the design; a test must see its own
        upc._WARNED.clear()
        # the warnings are expected here; keep them off the test run's stderr
        # (assertLogs still sees them)
        quiet = logging.NullHandler()
        logging.getLogger(upc.__name__).addHandler(quiet)
        self.addCleanup(logging.getLogger(upc.__name__).removeHandler, quiet)

    def write(self, content, name="ufc_public_card.json", *, binary=False):
        path = self.dir / name
        if binary:
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def config_with(self, date):
        return self.write(json.dumps({upc.CONFIG_KEY: date, "decided": "2026-10-03",
                                      "reason": "a test"}))


class TheCommittedConfig(unittest.TestCase):
    """The file the brief asked for, exactly."""

    def setUp(self):
        self.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_it_has_exactly_the_three_keys(self):
        self.assertEqual(sorted(self.config),
                         ["decided", "favourites_rule_last_public_date", "reason"])

    def test_the_last_public_date_and_the_decision_date_are_2026_10_03(self):
        self.assertEqual(self.config["favourites_rule_last_public_date"], "2026-10-03")
        self.assertEqual(self.config["decided"], "2026-10-03")

    def test_the_reason_is_one_plain_sentence(self):
        reason = self.config["reason"]
        self.assertIsInstance(reason, str)
        self.assertTrue(reason.strip())
        self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", reason)), 1, reason)
        self.assertNotIn(EM_DASH, reason)

    def test_the_helper_reads_the_committed_file(self):
        self.assertEqual(upc.configured_last_public_date(), "2026-10-03")
        self.assertEqual(upc.last_public_date(), "2026-10-03")

    def test_the_path_is_under_the_repository_root_and_absolute(self):
        self.assertTrue(upc.config_path().is_absolute())
        self.assertEqual(upc.config_path(), CONFIG)


class TheBuiltInFallback(unittest.TestCase):
    def test_it_is_a_real_date_and_the_owners_date(self):
        self.assertIsNotNone(upc.parse_iso_date(upc.DEFAULT_LAST_PUBLIC_DATE))
        self.assertEqual(upc.DEFAULT_LAST_PUBLIC_DATE, "2026-10-03")


class ReadingTheConfig(_TempConfig):
    def test_a_good_file_gives_its_own_date(self):
        path = self.config_with("2026-10-17")
        self.assertEqual(upc.configured_last_public_date(path), "2026-10-17")
        self.assertEqual(upc.last_public_date(path), "2026-10-17")

    def test_a_missing_file_is_none_and_the_fallback_date(self):
        path = self.dir / "does_not_exist.json"
        self.assertIsNone(upc.configured_last_public_date(path))
        self.assertEqual(upc.last_public_date(path), "2026-10-03")

    def test_every_kind_of_unusable_config_falls_back_to_the_owners_date(self):
        cases = {
            "not json": "this is not json {",
            "empty file": "",
            "a list": "[]",
            "a string": '"2026-10-17"',
            "key missing": json.dumps({"decided": "2026-10-03"}),
            "null date": json.dumps({upc.CONFIG_KEY: None}),
            "number, not a date": json.dumps({upc.CONFIG_KEY: 20261017}),
            "word, not a date": json.dumps({upc.CONFIG_KEY: "tomorrow"}),
            "month 13": json.dumps({upc.CONFIG_KEY: "2026-13-01"}),
            "day 40": json.dumps({upc.CONFIG_KEY: "2026-10-40"}),
            "unpadded": json.dumps({upc.CONFIG_KEY: "2026-10-3"}),
            "trailing space": json.dumps({upc.CONFIG_KEY: "2026-10-17 "}),
            "trailing newline": json.dumps({upc.CONFIG_KEY: "2026-10-17\n"}),
            "date and time": json.dumps({upc.CONFIG_KEY: "2026-10-17T00:00:00"}),
        }
        for name, content in cases.items():
            with self.subTest(name):
                upc._WARNED.clear()
                path = self.write(content)
                self.assertIsNone(upc.configured_last_public_date(path))
                self.assertEqual(upc.last_public_date(path), "2026-10-03")

    def test_a_directory_or_undecodable_bytes_are_unreadable_not_a_crash(self):
        self.assertEqual(upc.last_public_date(self.dir), "2026-10-03")
        bad = self.write(b"\xff\xfe\x00\xd8 not utf-8", name="bad.json", binary=True)
        self.assertEqual(upc.last_public_date(bad), "2026-10-03")

    def test_it_never_raises_whatever_goes_wrong_finding_or_opening_the_file(self):
        """It guards a public route: a failure of any kind reads as
        "unreadable" and gives the owner's date, never a 500."""
        for bad_path in (12345, object(), ["a", "list"]):
            with self.subTest(path=repr(bad_path)):
                self.assertEqual(upc.last_public_date(bad_path), "2026-10-03")
        with mock.patch.object(upc, "config_path", side_effect=RuntimeError("no root")):
            self.assertEqual(upc.last_public_date(), "2026-10-03")
            self.assertIsNotNone(upc.paused_card("2026-10-10"))
            self.assertIsNone(upc.paused_card("2026-10-03"))

    def test_a_file_saved_with_a_byte_order_mark_still_reads(self):
        """PowerShell writes one. It must not read as malformed and quietly
        undo a date someone chose."""
        body = json.dumps({upc.CONFIG_KEY: "2026-10-17"}).encode("utf-8")
        path = self.write(b"\xef\xbb\xbf" + body, binary=True)
        self.assertEqual(upc.last_public_date(path), "2026-10-17")

    def test_it_does_not_read_the_working_directory(self):
        """Run with another working directory the committed value still comes
        back, and a same-named file there is ignored."""
        decoy = self.dir / "config"
        decoy.mkdir()
        (decoy / "ufc_public_card.json").write_text(
            json.dumps({upc.CONFIG_KEY: "2099-01-01"}), encoding="utf-8")
        here = os.getcwd()
        os.chdir(self.dir)
        try:
            self.assertEqual(upc.last_public_date(), "2026-10-03")
        finally:
            os.chdir(here)

    def test_a_problem_is_logged_once_and_says_which(self):
        path = self.dir / "gone.json"
        with self.assertLogs(upc.__name__, level="WARNING") as logged:
            upc.last_public_date(path)
            upc.last_public_date(path)
            upc.last_public_date(path)
        self.assertEqual(len(logged.records), 1)
        message = logged.records[0].getMessage()
        self.assertIn("gone.json", message)
        self.assertIn("2026-10-03", message)

    def test_a_good_file_logs_nothing(self):
        path = self.config_with("2026-10-17")
        logger = logging.getLogger(upc.__name__)
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        upc.last_public_date(path)
        self.assertEqual(records, [])


class WhichDatesArePaused(_TempConfig):
    def test_the_day_after_and_every_later_day_is_paused(self):
        path = self.config_with("2026-10-03")
        for date in ("2026-10-04", "2026-10-10", "2026-12-31", "2027-01-01", "2099-12-31"):
            with self.subTest(date):
                self.assertTrue(upc.is_paused_for(date, path))
                self.assertIsNotNone(upc.paused_card(date, path))

    def test_the_last_public_day_and_every_earlier_day_is_not(self):
        path = self.config_with("2026-10-03")
        for date in ("2026-10-03", "2026-10-02", "2026-09-26", "2025-01-01", "2000-02-29"):
            with self.subTest(date):
                self.assertFalse(upc.is_paused_for(date, path))
                self.assertIsNone(upc.paused_card(date, path))

    def test_the_cut_off_follows_the_config_not_a_constant(self):
        path = self.config_with("2026-10-10")
        self.assertIsNone(upc.paused_card("2026-10-10", path))
        self.assertIsNone(upc.paused_card("2026-10-04", path))
        self.assertIsNotNone(upc.paused_card("2026-10-11", path))
        self.assertEqual(upc.paused_card("2026-10-11", path)["paused_after"], "2026-10-10")

    def test_a_string_that_is_not_a_date_is_never_after_anything(self):
        path = self.config_with("2026-10-03")
        for value in ("", "abc", "2026-10-3", "2026-1-10", "20261010", "2026-10-10T00:00",
                      "2026-02-30", "../2026-10-10", " 2026-10-10", "2026-10-10\n", None, 20261010,
                      b"2026-10-10"):
            with self.subTest(repr(value)):
                self.assertFalse(upc.is_paused_for(value, path))
                self.assertIsNone(upc.paused_card(value, path))

    def test_it_is_a_comparison_of_dates_not_of_strings(self):
        """"2026-10-04" > "2026-10-03" is true as text too, but a year or a
        month turning over is where text and dates part ways."""
        path = self.config_with("2026-12-31")
        self.assertIsNone(upc.paused_card("2026-12-31", path))
        self.assertIsNotNone(upc.paused_card("2027-01-01", path))
        self.assertIsNone(upc.paused_card("2026-09-30", path))


class ThePausedPayload(_TempConfig):
    def setUp(self):
        super().setUp()
        self.payload = upc.paused_card("2026-10-10", self.config_with("2026-10-03"))

    def test_no_picks_paused_and_the_reason(self):
        self.assertEqual(self.payload["picks"], [])
        self.assertEqual(self.payload["count"], 0)
        self.assertIs(self.payload["paused"], True)
        self.assertEqual(self.payload["reason"], THE_REASON)

    def test_it_names_the_sport_the_date_and_the_cut_off(self):
        self.assertEqual(self.payload["sport"], "mma")
        self.assertEqual(self.payload["date"], "2026-10-10")
        self.assertEqual(self.payload["paused_after"], "2026-10-03")

    def test_it_is_not_a_frozen_card_and_carries_no_rule_or_prices(self):
        self.assertIs(self.payload["frozen"], False)
        for key in ("rule", "all_bets", "prop_picks", "total_picks", "published_utc",
                    "prices_as_of"):
            self.assertNotIn(key, self.payload)

    def test_every_call_returns_its_own_dict(self):
        first = upc.paused_card("2026-10-10", self.config_with("2026-10-03"))
        first["picks"].append("leaked")
        first["reason"] = "changed"
        second = upc.paused_card("2026-10-10", self.config_with("2026-10-03"))
        self.assertEqual(second["picks"], [])
        self.assertEqual(second["reason"], THE_REASON)

    def test_it_round_trips_as_json(self):
        self.assertEqual(json.loads(json.dumps(self.payload)), self.payload)


class TheReasonASeesOnScreen(unittest.TestCase):
    def test_it_is_the_sentence_the_owner_approved(self):
        self.assertEqual(upc.PAUSED_REASON, THE_REASON)

    def test_plain_words_no_dashes_no_claims(self):
        text = upc.PAUSED_REASON
        for dash in (EM_DASH, EN_DASH, "--"):
            self.assertNotIn(dash, text)
        lowered = text.lower()
        for word in ("bet check", "betcheck", "profit", "edge", "roi", "units", "win rate",
                     "return", "guarantee", "beat the market"):
            self.assertNotIn(word, lowered, word)

    def test_it_passes_the_wording_sweeps_the_site_is_held_to(self):
        normal = _normalise(upc.PAUSED_REASON)
        for phrase in BANNED_PHRASES + BANNED_JARGON:
            self.assertNotIn(phrase, normal, phrase)
        self.assertEqual(_violations_in(upc.PAUSED_REASON, "UFC paused reason"), [])

    def test_it_names_its_own_record_page_and_the_return_condition(self):
        self.assertIn("stays on the record page", upc.PAUSED_REASON)
        self.assertIn("Picks come back", upc.PAUSED_REASON)


class TheCommandTheScriptRuns(_TempConfig):
    def _run(self, cwd, env=None):
        merged = dict(os.environ, **(env or {}))
        return subprocess.run([sys.executable, "-m", "src.appstate.ufc_public_card"],
                              cwd=str(cwd), capture_output=True, text=True, timeout=60,
                              env=merged)

    def test_main_prints_one_date_and_returns_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = upc.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "2026-10-03\n")

    def test_the_module_run_as_the_script_runs_it_prints_the_committed_date(self):
        done = self._run(ROOT)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "2026-10-03")
        self.assertEqual(len(done.stdout.strip().splitlines()), 1)
        self.assertNotIn("UFC pause config", done.stderr, "a good config logs no warning")

    def test_it_prints_the_same_date_from_another_working_directory(self):
        done = self._run(self.dir, env={"PYTHONPATH": str(ROOT)})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "2026-10-03")


class TheDecisionNote(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        self.lowered = self.text.lower()

    def test_it_quotes_the_owner(self):
        self.assertIn("Do you understand that there needs to be actual analysis", self.text)

    def test_it_states_the_effective_date_and_the_one_value(self):
        self.assertIn("2026-10-03", self.text)
        self.assertIn("favourites_rule_last_public_date", self.text)
        self.assertIn("config/ufc_public_card.json", self.text)

    def test_it_says_what_stays_what_stops_and_how_to_reverse(self):
        for heading in ("## What stops", "## What stays", "## How to reverse it"):
            self.assertIn(heading, self.text)
        for kept in ("published pick", "record", "odds capture"):
            self.assertIn(kept, self.lowered, kept)
        self.assertIn("new public ufc favourites picks stop", self.lowered)

    def test_it_says_the_rule_file_was_not_edited(self):
        self.assertIn("src/analysis/ufc_card.py", self.text)
        self.assertRegex(self.lowered, r"src/analysis/ufc_card\.py`? was not edited")

    def test_plain_words(self):
        self.assertNotIn(EM_DASH, self.text)
        self.assertNotIn("bet check", self.lowered)
        self.assertNotIn("betcheck", self.lowered)


if __name__ == "__main__":
    unittest.main()
