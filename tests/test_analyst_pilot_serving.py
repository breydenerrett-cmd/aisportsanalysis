"""Prompt v2's case against, and what the pilot's row serves: label, provenance, missing, case_against.

Three halves, all offline and injected:

  * the critic and the shape check treat `case_against` exactly as a reason is treated, strike a TAKE
    without a good one, and leave the UFC schema alone;
  * `ledger.game_view` carries each call's case against, the packet's `missing` list and the row's
    provenance;
  * the routes (skipped without FastAPI, as on the Linux CI job) serve the main ledger first, the
    pilot's row with the pilot label when the main one has none, the pilot record as its own block,
    and re-read when EITHER ledger changes.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.analyst import LABEL, PILOT_LABEL
from src.analyst import analyst as A
from src.analyst import critic as C
from src.analyst import ledger, pilot, situation_prompt
from tests import analyst_fixtures as F
from tests.test_analyst_critic import call, struck_ids, verify


class ThePromptAsksForTheCaseAgainst(unittest.TestCase):
    def test_it_is_version_four_and_still_says_what_a_case_against_is(self):
        self.assertEqual(A.PROMPT_VERSION, "analyst_prompt_v4")
        text = A.SYSTEM_PROMPT
        self.assertIn("13a. case_against:", text)
        self.assertIn("the strongest reason from the packet that this bet loses", text)
        self.assertIn("not general risk", text)
        self.assertIn("For a PASS it is null.", text)
        self.assertEqual(C.banned_words(text.split("THE WORDS")[0]), [])

    def test_no_rule_number_moved_so_the_situation_section_still_follows_sixteen(self):
        rules = [int(n) for n in __import__("re").findall(r"^(\d+)\. ", A.SYSTEM_PROMPT, __import__("re").M)]
        self.assertEqual(rules, list(range(1, 17)))
        self.assertTrue(situation_prompt.MLB_SITUATION_SECTION.startswith("THE SITUATION\n17. "))
        self.assertTrue(A.SITUATION_SYSTEM_PROMPT.startswith(A.SYSTEM_PROMPT[:-len(situation_prompt.CLOSING_LINE)]))

    def test_the_mlb_schema_requires_it_and_the_shared_one_does_not(self):
        item = A.MLB_RESPONSE_SCHEMA["properties"]["calls"]["items"]
        self.assertIn("case_against", item["required"])
        self.assertEqual(sorted(item["required"]), sorted(item["properties"]))
        shared = A.RESPONSE_SCHEMA["properties"]["calls"]["items"]
        self.assertNotIn("case_against", shared["properties"])

    def test_the_schema_is_picked_by_the_packet_so_ufc_is_untouched(self):
        self.assertIs(A.schema_for(F.build()), A.MLB_RESPONSE_SCHEMA)
        self.assertIs(A.schema_for({"bout": {"bout_id": "1"}, "markets": {}}), A.RESPONSE_SCHEMA)
        self.assertIs(A.build_request(F.build(), F.CFG)["output_config"]["format"]["schema"],
                      A.MLB_RESPONSE_SCHEMA)

    def test_the_shape_check_accepts_null_and_absent_and_rejects_a_malformed_one(self):
        packet = F.build()
        out = F.good_output(packet)
        self.assertEqual(A.validate_output(out, packet), [])
        out["calls"][1].pop("case_against")
        self.assertEqual(A.validate_output(out, packet), [])
        out["calls"][0]["case_against"] = "because"
        self.assertTrue(any("case_against needs a claim and an evidence list" in e
                            for e in A.validate_output(out, packet)))
        out["calls"][0]["case_against"] = {"claim": "x", "evidence": [{"path": "a"}]}
        self.assertTrue(any("case_against.evidence[0] needs a path and a value" in e
                            for e in A.validate_output(out, packet)))


class TheCriticHoldsTheCaseAgainstToTheReasonStandard(unittest.TestCase):
    def struck_problems(self, mutate):
        v = verify(F.build(), mutate)
        self.assertEqual(struck_ids(v), ["moneyline"])
        self.assertEqual(call(v, "moneyline")["verdict"], "PASS")
        return v.struck[0]["problems"]

    def test_a_good_case_against_is_kept_as_written(self):
        v = verify(F.build())
        self.assertEqual(v.struck, [])
        ml = call(v, "moneyline")
        self.assertEqual(ml["case_against"], F.good_output(F.build())["calls"][0]["case_against"])

    def test_a_take_with_no_case_against_is_struck_with_a_stated_reason(self):
        problems = self.struck_problems(lambda o: o["calls"][0].__setitem__("case_against", None))
        self.assertTrue(any("a TAKE needs a case_against" in p for p in problems))

    def test_a_wrong_evidence_value_in_it_is_struck_like_a_reasons(self):
        def m(o):
            o["calls"][0]["case_against"]["evidence"][0]["value"] = 1.23
        problems = self.struck_problems(m)
        self.assertTrue(any(p.startswith("case_against.evidence[0]") and "not 1.23" in p for p in problems))

    def test_a_path_that_does_not_resolve_is_struck(self):
        def m(o):
            o["calls"][0]["case_against"]["evidence"][0]["path"] = "data.home_sp_era"
        problems = self.struck_problems(m)
        self.assertTrue(any("case_against.evidence[0]" in p for p in problems))

    def test_no_evidence_is_struck(self):
        def m(o):
            o["calls"][0]["case_against"]["evidence"] = []
        self.assertTrue(any("case_against cites no packet path" in p for p in self.struck_problems(m)))

    def test_an_empty_claim_is_struck(self):
        def m(o):
            o["calls"][0]["case_against"]["claim"] = "  "
        self.assertTrue(any("case_against has no claim" in p for p in self.struck_problems(m)))

    def test_an_invented_number_a_banned_word_and_a_stranger_are_struck(self):
        def number(o):
            o["calls"][0]["case_against"]["claim"] = "The home starter has a 1.11 ERA."
        self.assertTrue(any("case_against quotes 1.11" in p for p in self.struck_problems(number)))

        def banned(o):
            o["calls"][0]["case_against"]["claim"] = "The home side is a lock."
        self.assertTrue(any("case_against uses the banned word 'lock'" in p for p in self.struck_problems(banned)))

        def name(o):
            o["calls"][0]["case_against"]["claim"] = "Aaron Judge has owned the home starter."
        self.assertTrue(any("case_against names" in p for p in self.struck_problems(name)))

    def test_a_pass_publishes_no_case_against_whatever_the_model_sent(self):
        packet = F.build()
        out = F.good_output(packet)
        out["calls"][1]["case_against"] = F.case_against_for(packet, out["calls"][1]["slot_id"])
        v = C.verify(packet, out)
        self.assertEqual(v.struck, [])
        self.assertIsNone(call(v, out["calls"][1]["slot_id"])["case_against"])

    def test_a_struck_call_carries_no_case_against_to_a_reader(self):
        def m(o):
            o["calls"][0]["reasons"][1]["claim"] = "A 9.99 thing."
        v = verify(F.build(), m)
        self.assertIsNone(call(v, "moneyline")["case_against"])
        self.assertNotIn("9.99", json.dumps(v.calls))


class Published(unittest.TestCase):
    """A pilot ledger in a temp folder, built through the real pilot commands."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        out = []
        pilot.prepare(F.DATE, "NYY@TB", cfg=F.CFG, root=cls.root, now=lambda: F.NOW, out=out.append,
                      loader=lambda d: [{
                          "payload": F.payload(), "multibook_rows": F.multibook_rows(),
                          "team_total_rows": F.team_total_rows(), "batter_prop_rows": F.batter_prop_rows(),
                          "pitcher_prop_rows": F.pitcher_prop_rows(), "prop_board": F.prop_board(),
                          "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"},
                          "section_as_of": {"teams": "2026-10-02", "starters": "2026-10-02"}}])
        answer = cls.root / "answer.json"
        answer.write_text(json.dumps(F.good_output(F.build())), encoding="utf-8")
        code = pilot.publish(str(pilot.game_folder(F.DATE, "NYY", "TB", cls.root)), str(answer),
                             model="claude-sonnet-5-5", cfg=F.CFG, root=cls.root, now=lambda: F.NOW,
                             out=out.append)
        assert code == 0, out
        cls.pilot_path = pilot.store_paths(cls.root)["store"]
        cls.rows = ledger.rows(cls.pilot_path)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class TheViewCarriesWhatThePageDraws(Published):
    def test_each_take_has_its_case_against_and_each_pass_none(self):
        view = ledger.game_view(F.DATE, "NYY", "TB", all_rows=self.rows)
        by = {c["slot_id"]: c for c in view["calls"]}
        self.assertEqual(by["moneyline"]["verdict"], "TAKE_OTHER_SIDE")
        self.assertIn("lower ERA", by["moneyline"]["case_against"]["claim"])
        self.assertTrue(by["moneyline"]["case_against"]["evidence"])
        self.assertTrue(all(c["case_against"] is None for c in view["calls"] if c["verdict"] == "PASS"))

    def test_the_packets_own_missing_list_is_served(self):
        view = ledger.game_view(F.DATE, "NYY", "TB", all_rows=self.rows)
        self.assertEqual(view["missing"], F.build()["missing"])
        self.assertTrue(view["missing"])      # the synthetic game has holes (no lineups, thin props)

    def test_provenance_is_session_assisted_for_a_pilot_row_and_api_for_any_other(self):
        self.assertEqual(ledger.game_view(F.DATE, "NYY", "TB", all_rows=self.rows)["provenance"],
                         "session_assisted")
        plain = [dict(r) for r in self.rows]
        for r in plain:
            r.pop("provenance", None)
        self.assertEqual(ledger.game_view(F.DATE, "NYY", "TB", all_rows=plain)["provenance"], "api")

    def test_an_unreadable_packet_file_means_none_not_an_empty_list(self):
        moved = [dict(r, packet_path=str(self.root / "gone.json.gz")) if r["kind"] == ledger.KIND_PUBLISHED else r
                 for r in self.rows]
        self.assertIsNone(ledger.game_view(F.DATE, "NYY", "TB", all_rows=moved)["missing"])

    def test_a_row_written_before_v2_has_no_case_against_and_still_renders(self):
        old = []
        for r in self.rows:
            if r["kind"] == ledger.KIND_PUBLISHED:
                r = dict(r, calls=[{k: v for k, v in c.items() if k != "case_against"} for c in r["calls"]])
            old.append(r)
        view = ledger.game_view(F.DATE, "NYY", "TB", all_rows=old)
        self.assertTrue(all(c["case_against"] is None for c in view["calls"]))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutesServeTheRightRowWithTheRightLabel(Published):
    def setUp(self):
        from api import analyst as api_analyst
        self.api = api_analyst
        self.main_rows = self._main_rows()

    def _main_rows(self):
        with tempfile.TemporaryDirectory() as d:
            packet = F.build()
            ledger.publish(packet, C.verify(packet, F.good_output(packet)), now=F.NOW, model="m",
                           path=str(Path(d) / "m.jsonl"), packet_dir=str(Path(d) / "p"))
            return ledger.rows(str(Path(d) / "m.jsonl"))

    def get(self, main, pilot_rows, away="NYY", home="TB"):
        with mock.patch.object(self.api, "_rows", return_value=main), \
                mock.patch.object(self.api, "_pilot_rows", return_value=pilot_rows):
            return self.api.get_analysis(F.DATE, away, home)

    def test_a_game_only_the_pilot_published_is_served_with_the_pilot_label(self):
        body = self.get([], self.rows)
        self.assertTrue(body["available"])
        self.assertEqual(body["label"], PILOT_LABEL)
        self.assertEqual(body["analysis"]["provenance"], "session_assisted")
        self.assertIn("supervised session", body["label"])
        self.assertIn("Unproven", body["label"])

    def test_the_main_ledger_wins_when_it_has_the_game(self):
        body = self.get(self.main_rows, self.rows)
        self.assertEqual(body["label"], LABEL)
        self.assertEqual(body["analysis"]["provenance"], "api")

    def test_a_game_neither_ledger_has_says_so_with_the_main_label(self):
        body = self.get([], self.rows, away="BOS", home="NYM")
        self.assertEqual((body["available"], body["label"]), (False, LABEL))
        self.assertIsNone(body["analysis"])

    def test_the_record_carries_the_pilot_as_a_separate_block_never_in_the_main_counts(self):
        with mock.patch.object(self.api, "_rows", return_value=[]), \
                mock.patch.object(self.api, "_pilot_rows", return_value=self.rows):
            rec = self.api.get_record()
        self.assertEqual(rec["games_published"], 0)
        self.assertEqual(rec["label"], LABEL)
        self.assertEqual(rec["pilot"]["games_published"], 1)
        self.assertEqual(rec["pilot"]["label"], PILOT_LABEL)
        self.assertEqual(rec["families"]["moneyline"]["taken"], 0)
        self.assertEqual(rec["pilot"]["families"]["moneyline"]["taken"], 1)

    def test_with_no_pilot_rows_the_pilot_block_is_none(self):
        with mock.patch.object(self.api, "_rows", return_value=[]), \
                mock.patch.object(self.api, "_pilot_rows", return_value=[]):
            self.assertIsNone(self.api.get_record()["pilot"])

    def test_the_pilot_record_never_serves_an_unsettled_games_calls(self):
        with mock.patch.object(self.api, "_rows", return_value=[]), \
                mock.patch.object(self.api, "_pilot_rows", return_value=self.rows):
            self.assertEqual(self.api.get_record()["pilot"]["recent"], [])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheCacheSignatureCoversBothStores(unittest.TestCase):
    def setUp(self):
        from api import analyst as api_analyst
        self.api = api_analyst
        self.api.reset_cache_for_tests()
        self.addCleanup(self.api.reset_cache_for_tests)

    def test_the_signature_is_one_entry_per_store_and_names_both_paths(self):
        seen = []
        with mock.patch.object(self.api, "_stat", side_effect=lambda t: seen.append(str(t)) or (1, 2)):
            sig = self.api._signature()
        self.assertEqual(sig, ((1, 2), (1, 2)))
        self.assertTrue(any(s.replace("\\", "/").endswith(ledger.STORE.replace("\\", "/")) for s in seen))
        self.assertTrue(any(s.replace("\\", "/").endswith(pilot.STORE.replace("\\", "/")) for s in seen))

    def test_a_change_in_only_the_pilot_file_makes_both_be_read_again(self):
        none = (None, None)
        sigs = [((1, 1), (5, 5)), ((1, 1), (5, 5)), ((1, 1), (6, 6))]
        with mock.patch.object(self.api, "_signature", side_effect=sigs), \
                mock.patch.object(self.api.ledger, "rows", return_value=["x"]) as read:
            self.api._load()
            self.api._load()
            self.assertEqual(read.call_count, 2)       # main + pilot, once
            self.api._load()
            self.assertEqual(read.call_count, 4)       # the pilot file changed: re-read
        self.assertNotEqual(sigs[0], sigs[2])
        self.assertEqual(none, (None, None))

    def test_a_missing_pilot_store_reads_as_no_rows_without_touching_disk(self):
        with mock.patch.object(self.api, "_signature", return_value=((1, 1), (None, None))), \
                mock.patch.object(self.api.ledger, "rows", return_value=["m"]) as read:
            rows, pilot_rows = self.api._load()
        self.assertEqual((rows, pilot_rows), (["m"], []))
        self.assertEqual(read.call_count, 1)


if __name__ == "__main__":
    unittest.main()
