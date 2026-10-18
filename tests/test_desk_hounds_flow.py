"""The desk flow, offline: prepare, request files, the publication rule, the session runner.

Everything is injected. A temp folder is the repo root, the loader returns the shared synthetic game, the clock
is a lambda and every "subagent answer" is built by the test from the packet. Nothing here reads the repo's
evidence, calls a model or touches a network. Publishing and grading are in test_desk_hounds_publish.py and
test_desk_hounds_grade.py (split so no one module is a slow pole of the fast tier).
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.analyst import cli as analyst_cli
from src.analyst import packet as packet_mod
from src.analyst import pilot
from src.hounds.desk import builder, cli, ledger, publish, roles, session, state
from tests import _desk_hounds_fixtures as H
from tests import analyst_fixtures as F
from tests import nfl_analyst_fixtures as NF
from tests._desk_hounds_fixtures import Flow, other_item


class PacketReuse(Flow):
    def test_the_packet_is_the_one_the_analyst_builds(self):
        self.assertEqual(self.prepare_mlb(), 0, self.text)
        held = json.loads((self.mlb_game().folder / "packet.json").read_text(encoding="utf-8"))
        direct = analyst_cli._packet(H.mlb_item(), "2026-10-03T18:00:00Z", F.CFG)
        self.assertEqual(packet_mod.packet_hash(held), packet_mod.packet_hash(direct))

    def test_the_football_packet_is_the_one_the_football_analyst_builds(self):
        self.assertEqual(self.prepare_nfl(), 0, self.text)
        held = json.loads((self.nfl_game().folder / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(packet_mod.packet_hash(held), packet_mod.packet_hash(NF.build(self._store)))

    def test_prepare_writes_the_packet_and_prepare_json_and_nothing_else(self):
        self.prepare_mlb()
        self.assertEqual(sorted(p.name for p in self.mlb_game().folder.iterdir()), ["packet.json", "prepare.json"])

    def test_prepare_json_says_what_was_prepared(self):
        self.prepare_mlb()
        meta = self.mlb_game().meta
        self.assertEqual(meta["event_id"], "evt-nyy-tb")
        self.assertEqual(meta["game_ref"], 849835)
        self.assertEqual(meta["start_utc"], F.FIRST_PITCH)
        self.assertEqual(meta["role_hashes"], roles.role_hashes())
        self.assertEqual(set(meta["token_estimates"]["stages"]), set(roles.ALL_STAGES))
        self.assertEqual(meta["caps"], {"games_per_run": 2, "answers_per_run": 30, "attempts_per_stage": 3})
        self.assertFalse(meta["rehearsal"])
        self.assertIn("request tokens", self.text)

    def test_football_prepare_has_the_football_ids(self):
        self.prepare_nfl()
        meta = self.nfl_game().meta
        self.assertEqual((meta["sport"], meta["game_ref"], meta["start_utc"]),
                         ("nfl", NF.GAME_ID, NF.KICKOFF))

    def test_the_second_prepare_of_a_folder_is_refused(self):
        self.prepare_mlb()
        self.out.clear()
        self.assertEqual(self.prepare_mlb(), 2)
        self.assertIn("never rewritten", self.text)

    def test_a_game_that_has_started_is_not_prepared(self):
        self.now = F.NOW + timedelta(hours=6)
        self.assertEqual(self.prepare_mlb(), 2)
        self.assertIn("SKIP", self.text)
        self.assertFalse(state.desk_dir(self.root).exists())

    def test_a_game_that_prices_no_market_is_not_prepared(self):
        self.assertEqual(self.prepare_mlb(H.mlb_item(multibook_rows=[], team_total_rows=[],
                                                    batter_prop_rows=[], pitcher_prop_rows=[])), 2)
        self.assertIn("SKIP", self.text)

    def test_a_third_open_game_is_refused(self):
        items = [H.mlb_item(), other_item("BOS", "SEA", 1), other_item("LAD", "SD", 2)]
        self.assertEqual(self.prepare_mlb(*items, game="NYY@TB"), 0)
        self.assertEqual(self.prepare_mlb(*items, game="BOS@SEA"), 0)
        self.out.clear()
        self.assertEqual(self.prepare_mlb(*items, game="LAD@SD"), 2)
        self.assertIn("at most 2 games", self.text)

    def test_a_rehearsal_is_not_publishable_and_not_counted(self):
        items = [H.mlb_item(), other_item("BOS", "SEA", 1), other_item("LAD", "SD", 2)]
        for g in ("NYY@TB", "BOS@SEA", "LAD@SD"):
            self.assertEqual(self.prepare_mlb(*items, game=g, rehearsal=True), 0)


class Requests(Flow):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.prepare_mlb(), 0)
        self.game = self.mlb_game()

    def read_request(self, stage, attempt=1):
        return json.loads(self.game.request_file(stage, attempt).read_text(encoding="utf-8"))

    def test_a_first_wave_request_holds_the_packet_and_the_role_text_only(self):
        slots = ", ".join(s["slot_id"] for s in self.game.packet["slots"])
        for stage in roles.ANALYST_STAGES + roles.PERSONA_STAGES:
            self.game.ensure_request(stage, F.CFG)
            body = self.read_request(stage)
            role = roles.ROLES[stage]
            self.assertEqual(body["system"], role.system, stage)
            self.assertEqual(body["output_config"]["format"]["schema"], role.schema(), stage)
            self.assertEqual(len(body["messages"]), 1)
            task = ("Write your report now." if role.kind == roles.KIND_REPORT else
                    "Make your decision now. List only your TAKEs; a slot you do not list is a PASS.")
            self.assertEqual(
                body["messages"][0]["content"],
                builder.DATA_HEADER + json.dumps(self.game.packet, sort_keys=True, separators=(",", ":"),
                                                 ensure_ascii=True)
                + f"\n\n{task} The market slots in the data are: {slots}.", stage)

    def test_a_request_never_names_another_hound_or_stage(self):
        for stage in roles.ANALYST_STAGES + roles.PERSONA_STAGES:
            self.game.ensure_request(stage, F.CFG)
            text = json.dumps(self.read_request(stage))
            for other in ("bull researcher", "bear researcher", "desk head", "CHECKED MATERIAL"):
                if other not in roles.ROLES[stage].system:
                    self.assertNotIn(other, text, (stage, other))

    def test_a_request_file_is_never_rewritten(self):
        path = self.game.ensure_request("analyst_stats", F.CFG)
        before = path.read_bytes()
        again = self.game.ensure_request("analyst_stats", F.CFG)
        self.assertEqual((again, again.read_bytes()), (path, before))

    def test_later_stages_are_blocked_until_their_upstream_is_final(self):
        self.assertEqual(self.game.state("bull")["state"], state.BLOCKED)
        self.assertIsNone(self.game.ensure_request("bull", F.CFG))
        self.assertEqual(self.game.state("head")["state"], state.BLOCKED)
        self.assertEqual(self.game.state("analyst_stats")["state"], state.TODO)

    def test_bull_and_bear_see_the_checked_reports_and_not_a_struck_claim(self):
        self.plan()
        for stage in roles.ANALYST_STAGES:
            ans = H.report_answer(self.game.packet, stage)
            if stage == "analyst_market":
                ans["findings"].append({"claim": "The home side wins 61 percent of such games.",
                                        "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}],
                                        "derived": []})
            self.write(self.game.answer_file(stage, 1), ans)
        self.check_all()
        self.assertEqual(self.game.state("analyst_market")["state"], state.TODO)   # rejected: answer again
        self.assertEqual(self.game.state("bull")["state"], state.BLOCKED)
        self.plan()
        self.write(self.game.answer_file("analyst_market", 2), H.report_answer(self.game.packet, "analyst_market"))
        self.check_all()
        self.plan()
        for stage in ("bull", "bear"):
            content = self.read_request(stage)["messages"][0]["content"]
            self.assertIn(builder.REPORTS_HEADER.strip(), content)
            for analyst in roles.ANALYST_STAGES:
                self.assertIn(f"({analyst})", content)
            self.assertNotIn("61 percent", content)

    def test_an_exhausted_analyst_reaches_the_next_stage_with_only_its_kept_findings(self):
        self.plan()
        bad = H.report_answer(self.game.packet, "analyst_stats")
        bad["text"] = "far too short to be a report"
        for n in (1, 2, 3):
            self.plan()
            ans = copy.deepcopy(bad)
            ans["findings"][0]["claim"] = f"The market names a favourite in this game {n}."
            self.write(self.game.answer_file("analyst_stats", n), ans)
            self.check_all()
        self.assertEqual(self.game.state("analyst_stats")["state"], state.EXHAUSTED)
        for stage in roles.ANALYST_STAGES[1:]:
            self.write(self.game.answer_file(stage, 1), H.report_answer(self.game.packet, stage))
        self.check_all()
        self.plan()
        material = self.game.upstream("bull")["analyst_stats"]
        self.assertIsNone(material)          # a shape failure leaves nothing the checker passed
        content = self.read_request("bull")["messages"][0]["content"]
        self.assertIn("no checked answer was produced for this stage", content)

    def test_a_reanswer_request_carries_the_rejection_lines_and_nothing_else(self):
        self.plan()
        ans = H.report_answer(self.game.packet, "analyst_stats", findings=[
            {"claim": "The home side wins 61 percent of such games.",
             "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}], "derived": []}])
        self.write(self.game.answer_file("analyst_stats", 1), ans)
        self.check_all()
        row = self.game.attempts("analyst_stats")[0]
        self.assertTrue(row["rejected"])
        self.plan()
        first = self.read_request("analyst_stats", 1)
        second = self.read_request("analyst_stats", 2)
        extra = second["messages"][0]["content"][len(first["messages"][0]["content"]):]
        self.assertEqual(extra, "\n\nYour previous answer was rejected for these reasons. Fix them and answer "
                                "again:\n- " + "\n- ".join(row["rejection_lines"]))
        self.assertNotIn("61 percent of such games", second["messages"][0]["content"][:len(
            first["messages"][0]["content"])])
        self.assertEqual({k: v for k, v in second.items() if k != "messages"},
                         {k: v for k, v in first.items() if k != "messages"})


class AttemptsRule(Flow):
    """The analyst pilot's publication rule, stage by stage (the pilot's own attempt code)."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.prepare_mlb(), 0)
        self.game = self.mlb_game()
        self.plan()

    def bad(self, n=1):
        return H.report_answer(self.game.packet, "analyst_stats", findings=[
            {"claim": f"The home side wins {60 + n} percent of such games.",
             "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}], "derived": []}])

    def good(self):
        return H.report_answer(self.game.packet, "analyst_stats")

    def check(self, answer, n):
        self.out.clear()
        path = self.write(self.game.answer_file("analyst_stats", n), answer)
        return session.check_answer(self.game, "analyst_stats", path, now=self.clock(), out=self.out.append)

    def test_a_clean_first_answer_is_final_and_a_second_answer_is_refused(self):
        self.assertEqual(self.check(self.good(), 1), "recorded")
        self.assertEqual(self.game.state("analyst_stats")["state"], state.CLEAN)
        other = self.good()
        other["findings"][0]["claim"] = "A different claim about the favourite."
        path = self.write(self.game.answer_file("analyst_stats", 2), other)
        self.out.clear()
        self.assertEqual(session.check_answer(self.game, "analyst_stats", path, now=self.clock(),
                                              out=self.out.append), "refused")
        self.assertIn("reroll", self.text)
        self.assertEqual(len(self.game.attempts("analyst_stats")), 1)

    def test_the_same_answer_twice_counts_once(self):
        self.check(self.bad(), 1)
        path = self.game.answer_file("analyst_stats", 1)
        self.out.clear()
        self.assertEqual(session.check_answer(self.game, "analyst_stats", path, now=self.clock(),
                                              out=self.out.append), "already recorded")
        self.assertEqual(len(self.game.attempts("analyst_stats")), 1)

    def test_a_rejected_answer_may_be_answered_again_at_most_twice(self):
        for n in (1, 2, 3):
            self.plan()
            self.assertEqual(self.check(self.bad(n), n), "recorded")
        self.assertEqual(self.game.state("analyst_stats")["state"], state.EXHAUSTED)
        self.assertEqual(self.game.state("analyst_stats")["attempts"], 3)
        path = self.write(self.game.answer_file("analyst_stats", 4), self.good())
        self.out.clear()
        self.assertEqual(session.check_answer(self.game, "analyst_stats", path, now=self.clock(),
                                              out=self.out.append), "refused")
        self.assertEqual(len(self.game.attempts("analyst_stats")), 3)

    def test_the_latest_attempt_is_the_one_used(self):
        self.check(self.bad(1), 1)
        self.plan()
        self.check(self.good(), 2)
        self.assertEqual(self.game.state("analyst_stats")["state"], state.CLEAN)
        check = self.game.final_check("analyst_stats")
        self.assertEqual(check.report.struck, 0)

    def test_an_unreadable_answer_is_a_rejected_attempt_with_a_reason(self):
        path = self.game.answer_file("analyst_stats", 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("this is not json", encoding="utf-8")
        self.assertEqual(session.check_answer(self.game, "analyst_stats", path, now=self.clock(),
                                              out=self.out.append), "recorded")
        row = self.game.attempts("analyst_stats")[0]
        self.assertTrue(row["rejected"])
        self.assertTrue(row["rejection_lines"][0].startswith("shape:"))

    def test_an_answer_for_a_blocked_stage_is_refused(self):
        path = self.write(self.game.answer_file("bull", 1), H.report_answer(self.game.packet, "bull"))
        self.assertEqual(session.check_answer(self.game, "bull", path, now=self.clock(), out=self.out.append),
                         "refused")

    def test_publish_refuses_a_stage_whose_saved_attempt_was_edited(self):
        self.check(self.good(), 1)
        for stage in roles.ALL_STAGES[1:]:
            pass
        saved = pilot.attempt_file(self.game.stage_dir("analyst_stats"), 1)
        saved.write_text(saved.read_text(encoding="utf-8") + " ", encoding="utf-8")
        self.takes = {}
        self.drive()
        self.out.clear()
        code = self.publish()
        self.assertEqual(code, 2)
        self.assertIn("no longer the bytes that were checked", self.text)


class SessionRunner(Flow):
    def test_the_caps_are_the_pre_registered_numbers(self):
        self.assertEqual((state.MAX_GAMES_PER_RUN, state.MAX_ANSWERS_PER_RUN, state.MAX_ATTEMPTS), (2, 30, 3))

    def test_plan_with_no_prepared_game_says_so(self):
        result = self.plan()
        self.assertEqual(result["jobs"], [])
        self.assertIn("Run `prepare` first", self.text)

    def test_plan_lists_one_job_per_request_in_wave_order(self):
        self.prepare_mlb()
        result = self.plan()
        self.assertEqual([j["stage"] for j in result["jobs"]], list(roles.ANALYST_STAGES + roles.PERSONA_STAGES))
        for job in result["jobs"]:
            self.assertTrue(Path(job["request"]).exists())
            self.assertFalse(Path(job["answer"]).exists())
        self.assertIn("SUBAGENT PROMPT", self.text)
        self.assertIn("Read only the file", self.text)
        self.assertIn("wave 1", self.text)

    def test_waves_two_and_three_appear_only_when_their_upstream_is_final(self):
        self.prepare_mlb()
        first = self.plan()
        for job in first["jobs"]:
            self.write(job["answer"], self.answer_for(job["game"], job["stage"]))
        self.check_all()
        second = self.plan()
        self.assertEqual([j["stage"] for j in second["jobs"]], ["bull", "bear"])
        for job in second["jobs"]:
            self.write(job["answer"], self.answer_for(job["game"], job["stage"]))
        self.check_all()
        third = self.plan()
        self.assertEqual([j["stage"] for j in third["jobs"]], ["head"])
        self.write(third["jobs"][0]["answer"], self.answer_for(third["jobs"][0]["game"], "head"))
        self.check_all()
        last = self.plan()
        self.assertEqual(last["jobs"], [])
        self.assertTrue(last["final"])
        self.assertIn("EVERY STAGE IS FINAL", self.text)

    def test_a_game_is_thirteen_answers_and_two_games_are_twenty_six(self):
        items = [H.mlb_item(), other_item("BOS", "SEA", 1)]
        for g in ("NYY@TB", "BOS@SEA"):
            self.assertEqual(self.prepare_mlb(*items, game=g), 0)
        self.drive()
        total = sum(state.attempts_recorded(g) for g in state.games_for_date(F.DATE, self.root))
        self.assertEqual(total, 26)
        self.assertLessEqual(total, state.MAX_ANSWERS_PER_RUN)

    def test_at_most_two_games_are_planned_and_the_rest_are_deferred(self):
        items = [H.mlb_item(), other_item("BOS", "SEA", 1), other_item("LAD", "SD", 2)]
        for g in ("NYY@TB", "BOS@SEA", "LAD@SD"):
            self.prepare_mlb(*items, game=g, rehearsal=True)
        result = self.plan()
        self.assertEqual(len(result["selected"]), 2)
        self.assertEqual(len(result["deferred"]), 1)
        self.assertIn("deferred", self.text)
        self.assertEqual({j["game"].game_id for j in result["jobs"]}, {g.game_id for g in result["selected"]})

    def test_the_answer_cap_cuts_the_plan_and_says_what_was_left_out(self):
        self.prepare_mlb()
        with mock.patch.object(state, "MAX_ANSWERS_PER_RUN", 4):
            result = self.plan()
        self.assertEqual(len(result["jobs"]), 4)
        self.assertIn("CUT BY THE ANSWER CAP: 6 job(s)", self.text)

    def test_status_shows_answered_checked_and_published(self):
        self.prepare_mlb()
        first = self.plan()
        self.write(first["jobs"][0]["answer"], self.answer_for(first["jobs"][0]["game"], first["jobs"][0]["stage"]))
        self.out.clear()
        view = session.status(F.DATE, now=self.clock(), out=self.out.append, root=self.root)
        self.assertIn("answered, waiting to be checked", self.text)
        self.assertIn("waiting for an answer", self.text)
        self.assertIn("blocked on analyst_stats", self.text)
        self.check_all()
        self.out.clear()
        session.status(F.DATE, now=self.clock(), out=self.out.append, root=self.root)
        self.assertIn("checked, clean", self.text)
        self.drive()
        self.assertEqual(self.publish(), 0)
        self.out.clear()
        view = session.status(F.DATE, now=self.clock(), out=self.out.append, root=self.root)
        self.assertIn("published hounds: desk_ai", self.text)
        self.assertTrue(view["chain_ok"])

    def test_the_plan_can_be_printed_as_json_for_a_scheduled_task(self):
        self.prepare_mlb()
        lines: list = []
        code = cli.main(["--root", str(self.root), "session-plan", "--date", F.DATE, "--json"],
                        out=lines.append, now=self.clock(), cfg=F.CFG)
        self.assertEqual(code, 0)
        data = json.loads("\n".join(lines))
        self.assertEqual([j["stage"] for j in data["jobs"]], list(roles.ANALYST_STAGES + roles.PERSONA_STAGES))
        job = data["jobs"][0]
        self.assertTrue(Path(job["request"]).exists())
        self.assertIn(job["request"], job["prompt"])
        self.assertIn(job["answer"], job["prompt"])
        self.assertEqual(data["caps"], {"games_per_run": 2, "answers_per_run": 30})
        self.assertFalse(data["every_stage_final"])

    def test_the_cli_drives_the_same_loop(self):
        self.prepare_mlb()
        lines: list = []
        code = cli.main(["--root", str(self.root), "session-plan", "--date", F.DATE], out=lines.append,
                        now=self.clock(), cfg=F.CFG)
        self.assertEqual(code, 0)
        self.assertTrue(any("JOBS: 10" in line for line in lines), lines[:5])
        code = cli.main(["--root", str(self.root), "session-status", "--date", F.DATE], out=lines.append,
                        now=self.clock())
        self.assertEqual(code, 0)
        code = cli.main(["--root", str(self.root), "verify"], out=lines.append)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
