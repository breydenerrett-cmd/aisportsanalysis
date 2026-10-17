"""The MLB value-picks pause (owner decision 2026-10-16): the one config value,
the helper that reads it, the sentence a reader sees, and the decision note.

Same contract as tests/test_ufc_public_card.py, which this mirrors:

  * config/mlb_public_card.json says what the brief says, and its path is
    anchored at the repository root, never the working directory;
  * a missing, unreadable, malformed or nonsensical config falls back to the
    owner's own date (2026-10-16), never to "no pause";
  * a date after the last public date is paused, a date on or before it is not,
    and a string that is not a date is never "after" anything;
  * the reason is plain words and passes the wording sweeps the site is held to;
  * `python3 -m src.appstate.mlb_public_card` prints one date and exits 0;
  * the decision note exists and says what it has to say.

Every config these tests read is a temp file passed in by path; the only real
file read is the committed one, by the tests that are about the committed one.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.appstate import mlb_public_card as mpc
from tests.test_customer_language import _violations_in
from tests.test_no_nothing_clears_the_bar import BANNED_JARGON, BANNED_PHRASES, _normalise

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "mlb_public_card.json"
DOC = ROOT / "docs" / "decisions" / "MLB_VALUE_PICKS_PAUSED.md"

EM_DASH = chr(0x2014)       # written as a number so this file carries no dash itself
EN_DASH = chr(0x2013)

UNUSABLE_CONFIGS = {
    "not json": "this is not json {",
    "empty file": "",
    "a list": "[]",
    "a string": '"2026-10-30"',
    "key missing": json.dumps({"decided": "2026-10-16"}),
    "null date": json.dumps({mpc.CONFIG_KEY: None}),
    "number, not a date": json.dumps({mpc.CONFIG_KEY: 20261030}),
    "word, not a date": json.dumps({mpc.CONFIG_KEY: "tomorrow"}),
    "month 13": json.dumps({mpc.CONFIG_KEY: "2026-13-01"}),
    "day 40": json.dumps({mpc.CONFIG_KEY: "2026-10-40"}),
    "unpadded": json.dumps({mpc.CONFIG_KEY: "2026-10-7"}),
    "trailing newline": json.dumps({mpc.CONFIG_KEY: "2026-10-30\n"}),
    "date and time": json.dumps({mpc.CONFIG_KEY: "2026-10-30T00:00:00"}),
    "the UFC key, not this one": json.dumps({"favourites_rule_last_public_date": "2026-10-30"}),
}


class _TempConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        mpc._WARNED.clear()
        quiet = logging.NullHandler()      # the fallback's warning is expected here
        logging.getLogger(mpc.__name__).addHandler(quiet)
        self.addCleanup(logging.getLogger(mpc.__name__).removeHandler, quiet)

    def write(self, content, name="mlb_public_card.json", *, binary=False):
        path = self.dir / name
        if binary:
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def config_with(self, date):
        return self.write(json.dumps({mpc.CONFIG_KEY: date, "decided": "2026-10-16",
                                      "reason": "a test"}))


class TheCommittedConfig(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_it_has_exactly_the_three_keys(self):
        self.assertEqual(sorted(self.config),
                         ["decided", "reason", "value_picks_last_public_date"])

    def test_the_last_public_date_and_the_decision_date_are_2026_10_16(self):
        self.assertEqual(self.config["value_picks_last_public_date"], "2026-10-16")
        self.assertEqual(self.config["decided"], "2026-10-16")

    def test_the_reason_is_the_one_the_page_shows(self):
        self.assertEqual(self.config["reason"], mpc.PAUSED_REASON)

    def test_the_helper_reads_the_committed_file(self):
        self.assertEqual(mpc.configured_last_public_date(), "2026-10-16")
        self.assertEqual(mpc.last_public_date(), "2026-10-16")

    def test_the_path_is_under_the_repository_root_and_absolute(self):
        self.assertTrue(mpc.config_path().is_absolute())
        self.assertEqual(mpc.config_path(), CONFIG)


class TheBuiltInFallback(unittest.TestCase):
    def test_it_is_a_real_date_and_the_owners_date(self):
        self.assertIsNotNone(mpc.parse_iso_date(mpc.DEFAULT_LAST_PUBLIC_DATE))
        self.assertEqual(mpc.DEFAULT_LAST_PUBLIC_DATE, "2026-10-16")

    def test_the_committed_file_and_the_fallback_agree(self):
        """If someone moves the date in the file the image still carries the
        owner's original until the constant moves too; the decision note says
        so. Today they are the same date."""
        self.assertEqual(mpc.configured_last_public_date(), mpc.DEFAULT_LAST_PUBLIC_DATE)


class ReadingTheConfig(_TempConfig):
    def test_a_good_file_gives_its_own_date(self):
        path = self.config_with("2026-10-30")
        self.assertEqual(mpc.configured_last_public_date(path), "2026-10-30")
        self.assertEqual(mpc.last_public_date(path), "2026-10-30")

    def test_a_missing_file_is_none_and_the_fallback_date(self):
        path = self.dir / "does_not_exist.json"
        self.assertIsNone(mpc.configured_last_public_date(path))
        self.assertEqual(mpc.last_public_date(path), "2026-10-16")

    def test_every_kind_of_unusable_config_falls_back_to_the_owners_date(self):
        for name, content in UNUSABLE_CONFIGS.items():
            with self.subTest(name):
                mpc._WARNED.clear()
                path = self.write(content)
                self.assertIsNone(mpc.configured_last_public_date(path))
                self.assertEqual(mpc.last_public_date(path), "2026-10-16")

    def test_a_directory_or_undecodable_bytes_are_unreadable_not_a_crash(self):
        self.assertEqual(mpc.last_public_date(self.dir), "2026-10-16")
        bad = self.write(b"\xff\xfe\x00\xd8 not utf-8", name="bad.json", binary=True)
        self.assertEqual(mpc.last_public_date(bad), "2026-10-16")

    def test_it_never_raises_whatever_goes_wrong_finding_the_file(self):
        for bad_path in (12345, object(), ["a", "list"]):
            with self.subTest(path=repr(bad_path)):
                self.assertEqual(mpc.last_public_date(bad_path), "2026-10-16")
        with mock.patch.object(mpc, "config_path", side_effect=RuntimeError("no root")):
            self.assertEqual(mpc.last_public_date(), "2026-10-16")
            self.assertIsNotNone(mpc.paused_card("2026-10-17"))
            self.assertIsNone(mpc.paused_card("2026-10-16"))

    def test_a_file_saved_with_a_byte_order_mark_still_reads(self):
        body = json.dumps({mpc.CONFIG_KEY: "2026-10-30"}).encode("utf-8")
        path = self.write(b"\xef\xbb\xbf" + body, binary=True)
        self.assertEqual(mpc.last_public_date(path), "2026-10-30")

    def test_it_does_not_read_the_working_directory(self):
        decoy = self.dir / "config"
        decoy.mkdir()
        (decoy / "mlb_public_card.json").write_text(
            json.dumps({mpc.CONFIG_KEY: "2099-01-01"}), encoding="utf-8")
        here = os.getcwd()
        os.chdir(self.dir)
        try:
            self.assertEqual(mpc.last_public_date(), "2026-10-16")
        finally:
            os.chdir(here)

    def test_a_problem_is_logged_once_and_says_which(self):
        path = self.dir / "gone.json"
        with self.assertLogs(mpc.__name__, level="WARNING") as logged:
            mpc.last_public_date(path)
            mpc.last_public_date(path)
        self.assertEqual(len(logged.records), 1)
        message = logged.records[0].getMessage()
        self.assertIn("gone.json", message)
        self.assertIn("2026-10-16", message)

    def test_a_good_file_logs_nothing(self):
        path = self.config_with("2026-10-30")
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger = logging.getLogger(mpc.__name__)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        mpc.last_public_date(path)
        self.assertEqual(records, [])


class WhichDatesArePaused(_TempConfig):
    def test_the_day_after_and_every_later_day_is_paused(self):
        path = self.config_with("2026-10-16")
        for date in ("2026-10-17", "2026-10-23", "2026-12-31", "2027-01-01", "2099-12-31"):
            with self.subTest(date):
                self.assertTrue(mpc.is_paused_for(date, path))
                self.assertIsNotNone(mpc.paused_card(date, path))

    def test_the_last_public_day_and_every_earlier_day_is_not(self):
        path = self.config_with("2026-10-16")
        for date in ("2026-10-16", "2026-10-15", "2026-09-22", "2025-01-01"):
            with self.subTest(date):
                self.assertFalse(mpc.is_paused_for(date, path))
                self.assertIsNone(mpc.paused_card(date, path))

    def test_the_cut_off_follows_the_config_not_a_constant(self):
        path = self.config_with("2026-10-20")
        self.assertIsNone(mpc.paused_card("2026-10-20", path))
        self.assertIsNone(mpc.paused_card("2026-10-17", path))
        self.assertEqual(mpc.paused_card("2026-10-21", path)["paused_after"], "2026-10-20")

    def test_a_string_that_is_not_a_date_is_never_after_anything(self):
        path = self.config_with("2026-10-16")
        for value in ("", "abc", "2026-10-7", "20261020", "2026-10-20T00:00", "2026-02-30",
                      " 2026-10-20", None, 20261020, b"2026-10-20"):
            with self.subTest(repr(value)):
                self.assertFalse(mpc.is_paused_for(value, path))
                self.assertIsNone(mpc.paused_card(value, path))

    def test_it_is_a_comparison_of_dates_not_of_strings(self):
        path = self.config_with("2026-12-31")
        self.assertIsNone(mpc.paused_card("2026-12-31", path))
        self.assertIsNotNone(mpc.paused_card("2027-01-01", path))


class ThePausedPayload(_TempConfig):
    def setUp(self):
        super().setUp()
        self.payload = mpc.paused_card("2026-10-17", self.config_with("2026-10-16"))

    def test_no_picks_paused_the_reason_and_the_links(self):
        self.assertEqual(self.payload["picks"], [])
        self.assertEqual(self.payload["count"], 0)
        self.assertIs(self.payload["paused"], True)
        self.assertEqual(self.payload["reason"], mpc.PAUSED_REASON)
        hrefs = [link["href"] for link in self.payload["links"]]
        self.assertEqual(hrefs, ["#/record-card", "sample.html", "#/odds"])
        for link in self.payload["links"]:
            self.assertTrue(link["label"].strip())

    def test_it_names_the_sport_the_date_and_the_cut_off(self):
        self.assertEqual(self.payload["sport"], "mlb")
        self.assertEqual(self.payload["date"], "2026-10-17")
        self.assertEqual(self.payload["paused_after"], "2026-10-16")

    def test_it_is_not_a_frozen_card_and_carries_no_rule_or_prices(self):
        self.assertIs(self.payload["frozen"], False)
        for key in ("rule", "all_bets", "prop_picks", "total_picks", "published_utc",
                    "prices_as_of"):
            self.assertNotIn(key, self.payload)

    def test_every_call_returns_its_own_dict(self):
        first = mpc.paused_card("2026-10-17", self.config_with("2026-10-16"))
        first["picks"].append("leaked")
        first["links"][0]["href"] = "elsewhere"
        second = mpc.paused_card("2026-10-17", self.config_with("2026-10-16"))
        self.assertEqual(second["picks"], [])
        self.assertEqual(second["links"][0]["href"], "#/record-card")

    def test_it_round_trips_as_json(self):
        self.assertEqual(json.loads(json.dumps(self.payload)), self.payload)

    def test_the_sample_brief_link_points_at_a_page_that_exists(self):
        self.assertTrue((ROOT / "web" / "sample.html").exists())


class TheReasonAReaderSees(unittest.TestCase):
    def test_it_says_why_what_continues_and_what_it_takes_to_return(self):
        text = mpc.PAUSED_REASON
        self.assertIn("MLB picks are paused", text)
        self.assertIn("paid a premium over the market's own price", text)
        self.assertIn("carried nothing the market did not already know", text)
        self.assertIn("test we register in advance", text)
        self.assertIn("The daily brief and the price board continue", text)
        self.assertIn("stays on the record page", text)

    def test_plain_words_no_dashes_no_claims_about_results(self):
        text = mpc.PAUSED_REASON
        for dash in (EM_DASH, EN_DASH, "--"):
            self.assertNotIn(dash, text)
        lowered = text.lower()
        for word in ("bet check", "betcheck", "profit", "roi", "units", "win rate", "guarantee",
                     "clv", "closing line value", "de-vig"):
            self.assertNotIn(word, lowered, word)

    def test_it_passes_the_wording_sweeps_the_site_is_held_to(self):
        normal = _normalise(mpc.PAUSED_REASON)
        for phrase in BANNED_PHRASES + BANNED_JARGON:
            self.assertNotIn(phrase, normal, phrase)
        self.assertEqual(_violations_in(mpc.PAUSED_REASON, "MLB paused reason"), [])


class TheCommandAnythingCanRun(_TempConfig):
    def _run(self, cwd, env=None):
        merged = dict(os.environ, **(env or {}))
        return subprocess.run([sys.executable, "-m", "src.appstate.mlb_public_card"],
                              cwd=str(cwd), capture_output=True, text=True, timeout=60, env=merged)

    def test_main_prints_one_date_and_returns_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mpc.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "2026-10-16\n")

    def test_the_module_run_as_a_script_prints_the_committed_date(self):
        done = self._run(ROOT)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "2026-10-16")
        self.assertNotIn("MLB pause config", done.stderr)

    def test_it_prints_the_same_date_from_another_working_directory(self):
        done = self._run(self.dir, env={"PYTHONPATH": str(ROOT)})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "2026-10-16")


class TheDecisionNote(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        self.lowered = self.text.lower()

    def test_it_states_the_effective_date_and_the_one_value(self):
        self.assertIn("2026-10-16", self.text)
        self.assertIn("value_picks_last_public_date", self.text)
        self.assertIn("config/mlb_public_card.json", self.text)

    def test_it_points_at_the_evidence(self):
        self.assertIn("docs/research/loss_diagnosis/00_SYNTHESIS.md", self.text)

    def test_it_says_what_stops_what_continues_how_to_reverse_and_when_to_resume(self):
        for heading in ("## What stops", "## What continues", "## How to reverse it",
                        "## What must be true to resume"):
            self.assertIn(heading, self.text)
        self.assertIn("closing-line value", self.lowered)
        self.assertIn("excludes zero", self.lowered)
        self.assertIn("shadow", self.lowered)
        self.assertIn("no fingerprinted file was edited", self.lowered)

    def test_plain_words(self):
        self.assertNotIn(EM_DASH, self.text)
        self.assertNotIn("betcheck", self.lowered)


if __name__ == "__main__":
    unittest.main()
