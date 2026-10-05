"""The pilot's publication rule: the first answer is the candidate, nobody picks among answers.

The story it pins (2026-10-04, Braves at Dodgers): three answers to one frozen request disagreed on a
strikeout prop; the first was rejected by the checker for unrelated violations, the second (given only
the rejection lines) was published, a third was never offered. Nothing then stopped a session from
answering again and again until an answer looked right, which is a free choice among samples. These
tests pin the code that stops it: `pilot check` records every distinct response as an attempt,
`pilot publish` refuses anything but the latest attempt, refuses a reroll (an answer that follows a
clean one), refuses a fourth attempt, and stores the attempt count and hashes on the row.

Offline and injected, like tests/test_analyst_pilot.py (whose Env it reuses). The last class runs the
rule's ledger change over a COPY of the real pilot ledger to prove rows written before it still load,
verify, serve and grade.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.analyst import ledger, pilot
from tests import analyst_fixtures as F
from tests.test_analyst_pilot import Env

ROOT = Path(__file__).resolve().parent.parent


class Rule(Env):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.prepare(), 0, self.text)
        self.out.clear()

    # --- answers -----------------------------------------------------------

    def clean(self, name="clean.json", confidence="medium"):
        """A clean answer; `confidence` makes distinct clean answers with distinct bytes."""
        out = F.good_output(F.build())
        out["calls"][0]["confidence"] = confidence
        return self.write_response(out, name)

    def struck(self, name="struck.json", value=4.4402):
        """A rejected answer (a wrong evidence value, so the moneyline is struck)."""
        out = F.good_output(F.build())
        out["calls"][0]["reasons"][1]["evidence"][0]["value"] = value
        return self.write_response(out, name)

    def check(self, response):
        return pilot.check(str(self.folder), response, out=self.out.append, now=lambda: self.now)

    def publish_response(self, response):
        return pilot.publish(str(self.folder), response, model="claude-sonnet-5-5", cfg=F.CFG,
                             root=self.root, now=lambda: self.now, out=self.out.append)

    def attempts(self):
        meta = json.loads((self.folder / "prepare.json").read_text(encoding="utf-8"))
        return pilot.read_attempts(self.folder, meta["packet_hash"])

    def published(self):
        return [r for r in self.store_rows() if r["kind"] == ledger.KIND_PUBLISHED]


class TheCandidateIsTheFirstAnswer(Rule):
    def test_a_clean_first_answer_publishes_with_one_attempt_and_its_hash(self):
        response = self.clean()
        self.assertEqual(self.check(response), 0, self.text)
        self.assertIn("attempt 1 of 3 recorded", self.text)
        self.assertIn("CLEAN", self.text)
        self.assertEqual(self.publish_response(response), 0, self.text)
        row = self.published()[0]
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["attempt_hashes"], [hashlib.sha256(Path(response).read_bytes()).hexdigest()])
        self.assertEqual(row["run"]["attempts"], 1)

    def test_the_check_writes_the_attempt_record_and_a_byte_copy(self):
        response = self.clean()
        self.check(response)
        record = [json.loads(line) for line in
                  (self.folder / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(record), 1)
        first = record[0]
        self.assertEqual(first["attempt"], 1)
        self.assertEqual(first["sha256"], hashlib.sha256(Path(response).read_bytes()).hexdigest())
        self.assertEqual((first["kept"], first["struck"], first["rejected"]), (len(F.build()["slots"]), 0, False))
        self.assertEqual(first["rejection_lines"], [])
        self.assertEqual(first["utc"], self.now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual((self.folder / "attempt_1.json").read_bytes(), Path(response).read_bytes())

    def test_a_response_that_was_never_checked_is_refused(self):
        self.assertEqual(self.publish_response(self.clean()), 2)
        self.assertIn("never checked", self.text)
        self.assertEqual(self.published(), [])

    def test_a_different_response_than_the_one_checked_is_refused(self):
        self.check(self.clean())
        self.out.clear()
        self.assertEqual(self.publish_response(self.clean("other.json", confidence="high")), 2)
        self.assertIn("never checked", self.text)

    def test_a_folder_prepared_before_the_rule_has_no_attempts_file_and_needs_a_check(self):
        self.assertFalse((self.folder / "attempts.jsonl").exists())
        self.assertEqual(self.publish_response(self.clean()), 2)
        self.assertIn("run `pilot check`", self.text)
        self.assertEqual(self.check(self.clean()), 0)
        self.assertEqual(self.publish_response(self.clean()), 0, self.text)


class ARejectedAnswerMayBeAnsweredAgain(Rule):
    def test_rejected_then_fixed_publishes_with_two_attempts_and_both_saved(self):
        bad, good = self.struck(), self.clean()
        self.assertEqual(self.check(bad), 0, self.text)
        self.assertIn("REJECTED by the checker", self.text)
        self.assertIn("attempt 2 of 3", self.text)
        self.assertIn("holds 3.8602, not 4.4402", self.text)      # the rejection lines the writer may get
        self.assertEqual(self.check(good), 0, self.text)
        self.assertEqual(self.publish_response(good), 0, self.text)
        row = self.published()[0]
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["attempt_hashes"],
                         [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (bad, good)])
        self.assertEqual((self.folder / "attempt_1.json").read_bytes(), Path(bad).read_bytes())
        self.assertEqual((self.folder / "attempt_2.json").read_bytes(), Path(good).read_bytes())
        self.assertEqual(row["run"]["attempts"], 2)
        self.assertEqual(len(row["struck"]), 0)             # the published answer is the second one

    def test_the_rejection_lines_are_stored_so_the_record_shows_what_the_writer_was_given(self):
        self.check(self.struck())
        lines = self.attempts()[0]["rejection_lines"]
        self.assertTrue(any(l.startswith("moneyline:") and "4.4402" in l for l in lines), lines)
        self.assertTrue(self.attempts()[0]["rejected"])
        self.assertEqual(self.attempts()[0]["struck"], 1)

    def test_a_withheld_summary_is_a_rejection_too(self):
        out = F.good_output(F.build())
        out["summary"] = out["summary"] + " The edge here is big."      # a banned word
        self.check(self.write_response(out))
        attempt = self.attempts()[0]
        self.assertEqual(attempt["summary_status"], "withheld")
        self.assertTrue(attempt["rejected"])
        self.assertTrue(any(l.startswith("summary:") for l in attempt["rejection_lines"]))

    def test_a_shape_failure_counts_as_an_attempt_and_is_a_rejection(self):
        out = F.good_output(F.build())
        out["summary"] = "too short"
        self.assertEqual(self.check(self.write_response(out, "short.json")), 2)
        attempt = self.attempts()[0]
        self.assertTrue(attempt["rejected"])
        self.assertTrue(all(l.startswith("shape:") for l in attempt["rejection_lines"]))
        self.assertIsNone(attempt["kept"])

    def test_a_file_that_is_not_json_is_not_an_answer_and_is_not_recorded(self):
        path = self.root / "junk.json"
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.check(str(path)), 2)
        self.assertEqual(self.attempts(), [])


class NoChoosingAmongAnswers(Rule):
    def test_an_unrejected_answer_followed_by_a_different_one_is_a_reroll_and_is_refused(self):
        first, second = self.clean(), self.clean("second.json", confidence="high")
        self.check(first)
        self.check(second)
        self.assertIn("NOT PUBLISHABLE", self.text)
        self.assertIn("reroll", self.text)
        self.out.clear()
        self.assertEqual(self.publish_response(second), 2)
        self.assertIn("reroll", self.text)
        self.assertEqual(self.published(), [])

    def test_the_clean_first_answer_cannot_be_published_once_a_later_one_exists(self):
        first, second = self.clean(), self.clean("second.json", confidence="high")
        self.check(first)
        self.check(second)
        self.out.clear()
        self.assertEqual(self.publish_response(first), 2)
        self.assertIn("attempt 2 exists", self.text)
        self.assertEqual(self.published(), [])

    def test_publishing_attempt_one_after_attempt_two_exists_is_refused(self):
        bad, good = self.struck(), self.clean()
        self.check(bad)
        self.check(good)
        self.out.clear()
        self.assertEqual(self.publish_response(bad), 2)
        self.assertIn("this response is attempt 1, but attempt 2 exists", self.text)
        self.assertEqual(self.published(), [])
        self.assertEqual(self.publish_response(good), 0, self.text)       # only the latest goes out

    def test_a_fourth_attempt_is_refused_even_though_it_is_the_latest(self):
        answers = [self.struck(f"s{n}.json", value=4.44 + n / 1000) for n in range(3)]
        for answer in answers:
            self.check(answer)
        self.assertIn("no attempts are left", self.text)
        fourth = self.clean()
        self.out.clear()
        self.assertEqual(self.check(fourth), 0)
        self.assertIn("NOT PUBLISHABLE", self.text)
        self.assertEqual(len(self.attempts()), 4)             # still recorded: every answer shown is kept
        self.out.clear()
        self.assertEqual(self.publish_response(fourth), 2)
        self.assertIn("at most 3", self.text)
        self.assertEqual(self.published(), [])

    def test_the_third_attempt_publishes_when_the_first_two_were_rejected(self):
        for n in range(2):
            self.check(self.struck(f"s{n}.json", value=4.44 + n / 1000))
        third = self.clean()
        self.check(third)
        self.assertEqual(self.publish_response(third), 0, self.text)
        self.assertEqual(self.published()[0]["attempts"], 3)

    def test_identical_bytes_checked_twice_count_once(self):
        response = self.clean()
        self.check(response)
        self.out.clear()
        self.check(response)
        self.assertIn("already recorded; it counts once", self.text)
        self.assertEqual(len(self.attempts()), 1)
        self.assertEqual(self.publish_response(response), 0, self.text)
        self.assertEqual(self.published()[0]["attempts"], 1)

    def test_the_same_answer_with_other_whitespace_is_still_the_same_attempt(self):
        out = F.good_output(F.build())
        compact = self.root / "compact.json"
        compact.write_text(json.dumps(out), encoding="utf-8")
        pretty = self.root / "pretty.json"
        pretty.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        self.check(str(compact))
        self.check(str(pretty))
        self.assertEqual(len(self.attempts()), 1)

    def test_a_rejected_answer_checked_again_does_not_reset_or_advance_anything(self):
        bad = self.struck()
        self.check(bad)
        self.check(bad)
        self.assertEqual(len(self.attempts()), 1)
        self.assertEqual(self.publish_response(bad), 0)       # a struck answer still publishes, with its strikes
        self.assertEqual(len(self.published()[0]["struck"]), 1)
        self.assertEqual(self.published()[0]["attempts"], 1)

    def test_an_edited_attempt_file_is_refused_because_the_record_cannot_be_trusted(self):
        response = self.clean()
        self.check(response)
        (self.folder / "attempt_1.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.publish_response(response), 2)
        self.assertIn("no longer the bytes that were checked", self.text)

    def test_attempts_belong_to_the_packet_prepared_so_preparing_again_starts_a_new_count(self):
        for n in range(3):
            self.check(self.struck(f"s{n}.json", value=4.44 + n / 1000))
        self.now = self.now.replace(minute=5)                  # a new built_at, so a new packet
        self.assertEqual(self.prepare(), 0, self.text)
        meta = json.loads((self.folder / "prepare.json").read_text(encoding="utf-8"))
        self.assertEqual(pilot.read_attempts(self.folder, meta["packet_hash"]), [])
        self.assertEqual(len(pilot.read_attempts(self.folder, "x")), 0)


class TheLedgerStillReadsOldRows(unittest.TestCase):
    """Rows written before the rule have no `attempts`. They must still load, serve, grade and keep
    the hash chain, alone and with a new row chained after them."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        (cls.root / "evidence").mkdir()
        cls.store = cls.root / "evidence" / "analyst_pilot_v1.jsonl"
        shutil.copyfile(ROOT / "evidence" / "analyst_pilot_v1.jsonl", cls.store)
        shutil.copytree(ROOT / "evidence" / "analyst_pilot_packets_v1",
                        cls.root / "evidence" / "analyst_pilot_packets_v1")
        cls.original_bytes = (ROOT / "evidence" / "analyst_pilot_v1.jsonl").read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_real_ledger_has_rows_without_the_new_fields(self):
        published = [r for r in ledger.rows(str(self.store)) if r["kind"] == ledger.KIND_PUBLISHED]
        self.assertTrue(published)
        self.assertTrue(all("attempts" not in r and "attempt_hashes" not in r for r in published))

    def test_the_chain_and_every_packet_file_verify_exactly_as_before(self):
        result = ledger.verify(str(self.store), root=self.root)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["rows"], len(ledger.rows(str(self.store))))

    def test_old_rows_are_served(self):
        view = ledger.game_view("2026-10-04", "ATL", "LAD", path=str(self.store), root=self.root)
        self.assertEqual(view["provenance"], "session_assisted")
        self.assertEqual(len(view["calls"]), 14)

    def test_old_rows_grade_and_the_chain_holds_afterwards(self):
        # The published rows only, so there is something left to grade; they are a valid chain prefix.
        rows = ledger.rows(str(self.store))
        keep = [r for r in rows if r["kind"] == ledger.KIND_PUBLISHED]
        lines = self.original_bytes.decode("utf-8").splitlines()
        copy = self.root / "grade_copy.jsonl"
        copy.write_text("\n".join(lines[:len(keep)]) + "\n", encoding="utf-8")
        self.assertTrue(ledger.verify(str(copy), root=self.root)["ok"])
        pub = ledger.latest_published(ledger.rows(str(copy)))["ATL-LAD-2026-10-04-1"]
        results = {pub["game_pk"]: {"away_score": "3", "home_score": "5"}}
        counts = ledger.grade_date("2026-10-04", results, [],
                                   now=datetime(2026, 10, 5, 12, tzinfo=timezone.utc), path=str(copy))
        self.assertEqual(counts["graded"], 1, counts)
        self.assertTrue(ledger.verify(str(copy), root=self.root)["ok"])

    def test_a_new_row_with_the_fields_chains_after_the_old_ones(self):
        """Publish through the real pilot flow on top of a copy of the real ledger."""
        env = Env()
        env.setUp()
        try:
            pilot_store = pilot.store_paths(env.root)["store"]
            Path(pilot_store).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.store, pilot_store)
            shutil.copytree(self.root / "evidence" / "analyst_pilot_packets_v1",
                            env.root / "evidence" / "analyst_pilot_packets_v1", dirs_exist_ok=True)
            self.assertEqual(env.prepare(), 0, env.text)
            response = env.good_response()
            pilot.check(str(env.folder), response, out=lambda *_: None, now=lambda: env.now)
            self.assertEqual(env.publish(response), 0, env.text)
            result = ledger.verify(pilot_store, root=env.root)
            self.assertTrue(result["ok"], result["problems"])
            new = [r for r in ledger.rows(pilot_store) if r["kind"] == ledger.KIND_PUBLISHED][-1]
            self.assertEqual(new["attempts"], 1)
            self.assertEqual(len(new["attempt_hashes"]), 1)
            old = [r for r in ledger.rows(pilot_store) if r["kind"] == ledger.KIND_PUBLISHED][0]
            self.assertNotIn("attempts", old)
        finally:
            env._tmp.cleanup()


class TheCommandPrintsTheRule(Rule):
    def test_check_says_how_many_attempts_remain_and_what_the_writer_may_be_given(self):
        self.check(self.struck())
        self.assertIn("with these lines and nothing else added to the request", self.text)


if __name__ == "__main__":
    unittest.main()
