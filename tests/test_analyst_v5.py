"""Prompt v5: no "repo" in what a customer reads, offline.

The published brief for Braves at Dodgers (2026-10-04) told a customer "the repo model likes the over
more than the market does". "Repo" is our word for this code base; the packet fields that carry the
numbers are `repo_model_probability` and `repo_market_probability`, and the model copied the word out
of them. v4 handled the same class of slip for "packet" (tests/test_analyst_v4.py); v5 does it for
"repo": rule 14a says what to write instead ("LineHound's own model") and the checker strikes the word
in every MLB field a reader sees, so a slip is a struck call, not a published one.

Every packet here is built from the shared synthetic game in `tests/analyst_fixtures.py`.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path

from src.analyst import analyst as A
from src.analyst import critic as C
from src.analyst import ledger, pilot, situation_prompt
from src.analyst import ufc_analyst as U
from tests import analyst_fixtures as F
from tests import ufc_analyst_fixtures as UF
from tests.test_analyst_pilot import Env

V3_PROMPT_SHA256 = "a9b1ebe59219e59bb93e0f2e86d7cbba7f0dcbd24eee988812e77187dddb7577"
V3_PROMPT_HASH = "8c667bbbcceb40d1a332fbf9308a97428d422e11cb0f6066de73b58694ee2c34"
V4_PROMPT_SHA256 = "98dc8f5e9021c74ac3631072988d04bbcd6070bf5a1a7927bd8adfe4cd240a35"
V4_PROMPT_HASH = "4c5a4b7d0aa3b15096bbcc89e7029995b54068bac1d37d07fb31dcb97626aecd"
V5_PROMPT_SHA256 = "bf16609aa9923e4dc0940c6498a5097bee25dc40dec516ea6b330ddb55f9c871"
V5_PROMPT_HASH = "acf8a530117b6bda68c72d69b1fe643951cb5e399054cff45920c5b3a3b8e08c"
UFC_PROMPT_HASH = "0c924190a80f5c579941ce46d8fee834056b9ec82b7ba207e51ca923c3d28c4a"

RULE_14A = next(l for l in A.SYSTEM_PROMPT.split("\n") if l.startswith("14a."))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ThePromptIsVersionFive(unittest.TestCase):
    def test_it_is_v5_and_the_rule_says_what_to_say_instead(self):
        self.assertEqual(A.PROMPT_VERSION, "analyst_prompt_v5")
        self.assertEqual(A.SITUATION_PROMPT_VERSION, "analyst_prompt_v5_situation")
        self.assertIn('never "the packet"', RULE_14A)                      # v4's sentence is still there
        self.assertIn('never write "repo"', RULE_14A)
        self.assertIn('"the repo model"', RULE_14A)
        self.assertIn("LineHound's own model", RULE_14A)
        self.assertIn(RULE_14A, A.SITUATION_SYSTEM_PROMPT)

    def test_every_other_rule_is_byte_for_byte_v3_and_v4(self):
        """Take rule 14a out and the text is exactly the v3 prompt: v4 and v5 changed 14a and nothing else."""
        without = "\n".join(l for l in A.SYSTEM_PROMPT.split("\n") if not l.startswith("14a."))
        self.assertEqual(sha(without), V3_PROMPT_SHA256)

    def test_the_hashes_are_pinned_and_older_rows_keep_theirs(self):
        self.assertEqual(sha(A.SYSTEM_PROMPT), V5_PROMPT_SHA256)
        self.assertEqual(ledger.prompt_hash(), V5_PROMPT_HASH)
        self.assertEqual(len({V3_PROMPT_HASH, V4_PROMPT_HASH, V5_PROMPT_HASH}), 3)
        self.assertEqual(len({V3_PROMPT_SHA256, V4_PROMPT_SHA256, V5_PROMPT_SHA256}), 3)

    def test_no_rule_number_moved_and_the_situation_section_still_starts_at_17(self):
        rules = [int(n) for n in re.findall(r"^(\d+)\. ", A.SYSTEM_PROMPT, re.M)]
        self.assertEqual(rules, list(range(1, 17)))
        self.assertTrue(situation_prompt.MLB_SITUATION_SECTION.startswith("THE SITUATION\n17. "))

    def test_the_ufc_prompt_and_hash_did_not_move(self):
        self.assertEqual(U.UFC_PROMPT_VERSION, "analyst_ufc_prompt_v1")
        self.assertEqual(U.prompt_hash(), UFC_PROMPT_HASH)
        self.assertNotIn("14a.", U.UFC_SYSTEM_PROMPT)

    def test_the_request_carries_the_v5_prompt(self):
        body = A.build_request(F.build(), F.CFG)
        self.assertEqual(body["system"], A.SYSTEM_PROMPT)
        self.assertIn(RULE_14A, body["system"])


class TheWordRepoIsStruck(unittest.TestCase):
    def setUp(self):
        self.packet = F.build()

    def good(self) -> dict:
        return F.good_output(self.packet)

    def test_the_helper_strikes_repo_only_when_asked_and_only_as_a_whole_word(self):
        said = "The repo model likes the over more than the market does."
        self.assertEqual(C.banned_words(said), [])
        self.assertEqual(C.banned_words(said, internal=True), ["repo"])
        self.assertEqual(C.banned_words("Both repos agree.", internal=True), ["repo"])
        self.assertEqual(C.banned_words("A stray Repo.", internal=True), ["repo"])
        self.assertEqual(C.banned_words("It is in the repository.", internal=True), ["repository"])
        self.assertEqual(C.banned_words("Two repositories disagree.", internal=True), ["repository"])
        self.assertEqual(C.banned_words("LineHound's own model likes the over.", internal=True), [])

    def test_report_and_reported_are_not_struck(self):
        for text in ("The report says the starter is healthy.", "He reported no soreness.",
                     "A reporter asked about it.", "Reports differ.", "The reporting is thin.",
                     "Repossession is not a thing here.", "The reputation of the bullpen is fine."):
            self.assertEqual(C.banned_words(text, internal=True), [], text)

    def test_a_field_name_is_one_word_and_is_not_struck(self):
        self.assertEqual(C.banned_words("repo_model_probability is 0.58.", internal=True), [])

    def test_a_reason_claim_that_says_the_repo_model_strikes_the_call(self):
        out = self.good()
        out["calls"][1]["reasons"][0]["claim"] = "The repo model likes this side more than the market does."
        v = C.verify(self.packet, out)
        self.assertEqual([s["slot_id"] for s in v.struck], ["run_line"])
        self.assertIn("reasons[0] uses the banned word 'repo'", v.struck[0]["problems"])
        self.assertEqual(v.calls[1]["verdict"], "PASS")
        self.assertNotIn("repo model", str(v.calls[1]).lower())

    def test_a_case_against_the_summary_and_what_would_change_it_are_held_to_it_too(self):
        out = self.good()
        out["calls"][0]["case_against"]["claim"] = "The repo model sees the home side as the better price."
        out["calls"][2]["what_would_change_it"] = "A move in the repo model's number."
        out["summary"] += " The repo model likes the over more than the market does."
        v = C.verify(self.packet, out)
        self.assertEqual(sorted(s["slot_id"] for s in v.struck), ["moneyline", "total"])
        self.assertIn("case_against uses the banned word 'repo'", v.struck[0]["problems"])
        self.assertEqual(v.summary_status, "withheld")
        self.assertIn("the summary uses the banned word 'repo'", v.summary_problems)

    def test_a_clean_answer_in_the_new_words_is_untouched(self):
        out = self.good()
        out["calls"][1]["reasons"][0]["claim"] = "LineHound's own model likes this side more than the market does."
        v = C.verify(self.packet, out)
        self.assertFalse([p for s in v.struck for p in s["problems"] if "banned word" in p])

    def test_an_evidence_path_with_repo_in_its_name_is_not_prose(self):
        out = self.good()
        out["calls"][0]["reasons"][0]["evidence"][0]["path"] = "markets.moneyline.repo_model_probability"
        v = C.verify(self.packet, out)
        problems = " ".join(p for s in v.struck for p in s["problems"])
        self.assertNotIn("banned word", problems)

    def test_the_ufc_analyst_is_not_held_to_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkt = UF.packet(UF.make_store(Path(tmp)))
        out = UF.good_output(pkt)
        out["calls"][0]["reasons"][0]["claim"] = "The repo model has the numbers."
        out["summary"] += " The repo model likes the other side."
        v = U.verify(pkt, out)
        text = " ".join(" ".join(s["problems"]) for s in v.struck) + " ".join(v.summary_problems)
        self.assertNotIn("banned word 'repo'", text)

    def test_the_pilot_check_reports_the_strike(self):
        out = self.good()
        out["calls"][1]["reasons"][0]["claim"] = "The repo model likes this side more than the market does."
        report = pilot.evaluate(self.packet, out)
        struck = [c for c in report.calls if not c.kept]
        self.assertEqual([c.slot_id for c in struck], ["run_line"])
        lines = []
        pilot.print_report(report, lines.append)
        self.assertIn("the banned word 'repo'", "\n".join(lines))


class ThePilotWorksWithV5(Env):
    def test_prepare_check_and_publish_carry_v5(self):
        self.assertEqual(self.prepare(), 0, self.text)
        meta = pilot.load_prepared(str(self.folder)).meta
        self.assertEqual((meta["prompt_version"], meta["prompt_hash"]), ("analyst_prompt_v5", V5_PROMPT_HASH))
        request = (self.folder / "request.json").read_text(encoding="utf-8")
        self.assertIn("never write", request)
        self.assertEqual(self.publish(), 0, self.text)
        row = self.store_rows()[0]
        self.assertEqual((row["prompt_version"], row["prompt_hash"]), ("analyst_prompt_v5", V5_PROMPT_HASH))

    def test_a_folder_prepared_under_v4_cannot_be_published_under_v5(self):
        """The Braves at Dodgers brief was prepared under v4. A new brief is prepared afresh: a folder whose
        recorded prompt is not the current one is refused, so an answer written for the old request (the
        one that let "the repo model" through) can never be frozen as an answer to the new one."""
        self.assertEqual(self.prepare(), 0, self.text)
        meta_path = self.folder / "prepare.json"
        meta = pilot._read_json(meta_path, "prepare.json")
        meta.update(prompt_version="analyst_prompt_v4", prompt_hash=V4_PROMPT_HASH)
        pilot._write_json(meta_path, meta)
        self.assertEqual(self.publish(), 2)
        self.assertIn("has changed since this game was prepared", self.text)

    def test_a_folder_prepared_under_v3_cannot_be_published_under_v5(self):
        self.assertEqual(self.prepare(), 0, self.text)
        meta_path = self.folder / "prepare.json"
        meta = pilot._read_json(meta_path, "prepare.json")
        meta.update(prompt_version="analyst_prompt_v3", prompt_hash=V3_PROMPT_HASH)
        pilot._write_json(meta_path, meta)
        self.assertEqual(self.publish(), 2)
        self.assertIn("has changed since this game was prepared", self.text)


class RowsPublishedUnderEarlierPromptsStillLoadAndServe(Env):
    """The v3 and v4 rows are never rewritten. Moving the live prompt must not make them unreadable."""

    def _published_under(self, version: str) -> None:
        from unittest import mock
        with mock.patch.object(A, "PROMPT_VERSION", version):
            self.assertEqual(self.prepare(), 0, self.text)
            self.assertEqual(self.publish(), 0, self.text)

    def _check(self, version: str) -> None:
        self._published_under(version)
        self.assertEqual(A.PROMPT_VERSION, "analyst_prompt_v5")           # the patch is gone again
        rows = self.store_rows()
        published = [r for r in rows if r["kind"] == ledger.KIND_PUBLISHED]
        self.assertEqual([r["prompt_version"] for r in published], [version])
        view = ledger.game_view(F.DATE, "NYY", "TB", all_rows=rows)
        self.assertIsNotNone(view)
        self.assertEqual(view["provenance"], "session_assisted")
        self.assertTrue(view["calls"])
        self.assertEqual({c["slot_id"] for c in view["calls"]}, {c["slot_id"] for c in published[0]["calls"]})

    def test_a_v3_row_loads_and_serves(self):
        self._check("analyst_prompt_v3")

    def test_a_v4_row_loads_and_serves(self):
        self._check("analyst_prompt_v4")

    def test_a_v5_refresh_supersedes_a_v4_row_and_both_stay_in_the_ledger(self):
        self._published_under("analyst_prompt_v4")
        self.out.clear()
        self.assertEqual(self.prepare(), 0, self.text)
        self.assertEqual(self.publish(refresh=True), 0, self.text)
        published = [r for r in self.store_rows() if r["kind"] == ledger.KIND_PUBLISHED]
        self.assertEqual([(r["version"], r["prompt_version"]) for r in published],
                         [(1, "analyst_prompt_v4"), (2, "analyst_prompt_v5")])
        self.assertEqual(published[1]["supersedes"], published[0]["row_hash"])


if __name__ == "__main__":
    unittest.main()
