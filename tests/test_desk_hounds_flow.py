"""The desk flow end to end, offline: prepare, plan, answer, check, publish, grade.

Everything is injected. A temp folder is the repo root, the loader returns the shared synthetic game, the clock
is a lambda and every "subagent answer" is built by the test from the packet. Nothing here reads the repo's
evidence, calls a model or touches a network.
"""

from __future__ import annotations

import copy
import json
import os
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.analyst import cli as analyst_cli
from src.analyst import packet as packet_mod
from src.analyst import pilot
from src.hounds import ledgers
from src.hounds.desk import builder, cli, ledger, prepare, publish, risk, roles, session, state
from tests import _desk_hounds_fixtures as H
from tests import analyst_fixtures as F
from tests import nfl_analyst_fixtures as NF


def other_item(away, home, pk):
    """A second synthetic game: the shared one under other clubs and another game pk."""
    item = H.mlb_item()
    adv = item["payload"]["advanced"]
    adv["away_team"], adv["home_team"] = away, home
    adv["game_id"] = f"{away}-{home}-2026-10-03-1"
    adv["game"].update(away_team=away, home_team=home, game_pk=pk)
    return item


class Flow(H.Env):
    """Helpers to drive a prepared game through its stages."""

    def setUp(self):
        super().setUp()
        self.takes: dict = {}          # stage -> [take builder(packet) -> decision]

    def silent(self, *_):
        pass

    def plan(self, **kw):
        return session.plan(F.DATE, cfg=F.CFG, now=self.clock(), out=self.out.append, root=self.root, **kw)

    def check_all(self):
        return session.check_all(F.DATE, now=self.clock(), out=self.out.append, root=self.root)

    def answer_for(self, game, stage):
        role = roles.ROLES[stage]
        if role.kind == roles.KIND_REPORT:
            return H.report_answer(game.packet, stage)
        takes = [t(game.packet) for t in self.takes.get(stage, [])]
        return H.decision_answer(game.packet, stage, takes)

    def drive(self, rounds=6):
        """Plan, answer every job cleanly, check; repeat until nothing is left to ask."""
        for _ in range(rounds):
            result = self.plan()
            if not result["jobs"]:
                return result
            for job in result["jobs"]:
                self.write(job["answer"], self.answer_for(job["game"], job["stage"]))
            self.check_all()
        return self.plan()

    def publish(self, **kw):
        kw.setdefault("model", "claude-sonnet-5-5")
        return publish.publish(self.mlb_game(), cfg=F.CFG, now=self.clock(), out=self.out.append,
                               root=self.root, **kw)


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


class Publishing(Flow):
    def setUp(self):
        super().setUp()
        self.prepare_mlb()
        self.moneyline_nyy = lambda p: H.take(p, "moneyline", "NYY", H.just_above_fair(p, "moneyline", "NYY"))
        self.total_under = lambda p: H.take(p, "total", "Under 7", H.just_above_fair(p, "total", "Under 7"))

    def bet_rows(self):
        return [r for r in ledger.rows(self.root) if r["kind"] == ledger.KIND_BET]

    def test_publish_writes_definitions_bets_a_game_row_and_a_transcript(self):
        self.takes = {"head": [self.moneyline_nyy], "persona_fader": [self.moneyline_nyy, self.total_under]}
        self.drive()
        self.assertEqual(self.publish(tokens_in=1000, tokens_out=500), 0, self.text)
        rows = ledger.rows(self.root)
        self.assertEqual([r["kind"] for r in rows[:7]], ["hound"] * 7)
        self.assertEqual({r["hound_id"] for r in rows[:7]}, {h["id"] for h in roles.HOUNDS})
        bets = self.bet_rows()
        self.assertEqual(sorted((b["hound_id"], b["slot_id"]) for b in bets),
                         [("desk_ai", "moneyline"), ("desk_fader", "moneyline"), ("desk_fader", "total")])
        b = next(b for b in bets if b["hound_id"] == "desk_ai")
        game = self.mlb_game()
        opt = game.packet["markets"]["moneyline"]["options"][1]
        self.assertEqual(
            {k: b[k] for k in ("kind", "date", "sport", "event_id", "game_pk", "away", "home", "start_utc",
                               "lock_utc", "market", "selection", "side", "line", "price_best", "book",
                               "book_count", "consensus_fair", "who_decided", "segment")},
            {"kind": "hound_bet", "date": F.DATE, "sport": "mlb", "event_id": "evt-nyy-tb", "game_pk": 849835,
             "away": "NYY", "home": "TB", "start_utc": F.FIRST_PITCH, "lock_utc": game.meta["built_at"],
             "market": "moneyline", "selection": "NYY", "side": "away", "line": None,
             "price_best": opt["best"]["price"], "book": opt["best"]["book"], "book_count": 3,
             "consensus_fair": opt["fair_probability"], "who_decided": "model", "segment": "forward"})
        self.assertEqual(b["price_average"], risk.board_average(opt))
        self.assertNotEqual(b["price_average"], b["price_best"])
        self.assertEqual(b["packet_hash"], game.meta["packet_hash"])
        self.assertEqual(b["prompt_hash"], roles.hound_prompt_hash("desk_ai"))
        self.assertTrue(b["reason"])
        gamerow = rows[-1]
        self.assertEqual(gamerow["kind"], "desk_game")
        self.assertNotIn("hound_id", gamerow)
        self.assertEqual(gamerow["hounds"]["desk_ai"]["takes"], 1)
        self.assertEqual(gamerow["hounds"]["desk_sharp"]["takes"], 0)
        self.assertEqual(gamerow["run"]["tokens_in"], 1000)
        transcript = game.folder / gamerow["transcript"].split("/")[-1]
        import hashlib
        self.assertEqual(hashlib.sha256(transcript.read_bytes()).hexdigest(), gamerow["transcript_sha256"])
        self.assertEqual(b["transcript_sha256"], gamerow["transcript_sha256"])

    def test_the_transcript_holds_every_stage_and_every_attempt(self):
        self.takes = {"head": [self.moneyline_nyy]}
        game = self.mlb_game()
        self.plan()
        bad = H.report_answer(game.packet, "analyst_stats", findings=[
            {"claim": "The home side wins 61 percent of such games.",
             "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}], "derived": []}])
        self.write(game.answer_file("analyst_stats", 1), bad)
        self.drive()
        self.assertEqual(self.publish(), 0, self.text)
        transcript = json.loads((game.folder / "transcript.json").read_text(encoding="utf-8"))
        stages = {s["stage"]: s for s in transcript["stages"]}
        self.assertEqual(set(stages), set(roles.ALL_STAGES))
        self.assertEqual([a["attempt"] for a in stages["analyst_stats"]["attempts"]], [1, 2])
        self.assertTrue(stages["analyst_stats"]["attempts"][0]["rejected"])
        self.assertEqual(stages["analyst_stats"]["final_attempt"], 2)
        self.assertEqual(stages["analyst_stats"]["attempts"][0]["response"], bad)
        self.assertIn("Unproven", transcript["label"])
        self.assertEqual(transcript["hounds"]["desk_ai"]["takes"][0]["slot_id"], "moneyline")

    def test_a_take_at_minus_200_or_worse_is_never_published(self):
        over = lambda p: H.take(p, "prop_02", "Over 0.5", 0.9)           # best -220
        self.takes = {"head": [over], "persona_square": [over], "persona_grinder": [over]}
        self.drive()
        self.assertEqual(self.publish(), 0, self.text)
        self.assertEqual(self.bet_rows(), [])
        transcript = json.loads((self.mlb_game().folder / "transcript.json").read_text(encoding="utf-8"))
        struck = transcript["hounds"]["desk_ai"]["struck"]
        self.assertEqual([(s["slot_id"], s["rule"]) for s in struck], [("prop_02", "R2")])

    def test_a_decision_the_checker_struck_is_not_published(self):
        counter = iter(range(83, 90))
        bad = lambda p: H.take(p, "moneyline", "NYY", H.just_above_fair(p, "moneyline", "NYY"), reasons=[
            {"claim": f"The road side has won {next(counter)} percent of such games.",
             "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}], "derived": []}])
        self.takes = {"head": [bad]}
        game = self.mlb_game()
        self.drive()
        # three rejected attempts for the head leave its latest attempt final; its TAKE stays struck
        head = self.game_state("head")
        self.assertEqual(head["state"], state.EXHAUSTED)
        self.assertEqual(self.publish(), 0, self.text)
        self.assertEqual([b for b in self.bet_rows() if b["hound_id"] == "desk_ai"], [])

    def game_state(self, stage):
        return self.mlb_game().state(stage)

    def test_the_ledger_chain_verifies_and_a_tamper_is_found(self):
        self.takes = {"head": [self.moneyline_nyy]}
        self.drive()
        self.publish()
        self.assertTrue(ledger.verify(self.root).ok)
        path = ledger.path(self.root)
        lines = path.read_text(encoding="utf-8").splitlines()
        idx = next(i for i, line in enumerate(lines) if '"hound_bet"' in line)
        lines[idx] = lines[idx].replace('"price_best": ', '"price_best": 9')
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = ledger.verify(self.root)
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, idx + 1)

    def test_publish_refuses_a_rehearsal(self):
        other = H.Env()
        self.takes = {}
        # a fresh folder prepared as a rehearsal
        meta_path = self.mlb_game().folder / "prepare.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["rehearsal"] = True
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.drive()
        self.assertEqual(self.publish(), 2)
        self.assertIn("rehearsal", self.text)
        self.assertEqual(ledger.rows(self.root), [])

    def test_publish_refuses_after_the_game_has_started(self):
        self.drive()
        self.now = F.NOW + timedelta(hours=5)
        self.assertEqual(self.publish(), 2)
        self.assertIn("has passed", self.text)
        self.assertEqual(ledger.rows(self.root), [])

    def test_publish_refuses_a_packet_older_than_ninety_minutes(self):
        self.drive()
        self.now = F.NOW + timedelta(minutes=95)
        self.assertEqual(self.publish(), 2)
        self.assertIn("minutes ago", self.text)

    def test_publish_refuses_when_a_prompt_has_changed_since_prepare(self):
        self.drive()
        meta_path = self.mlb_game().folder / "prepare.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["role_hashes"]["head"] = "0" * 64
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.assertEqual(self.publish(), 2)
        self.assertIn("has changed since this game was prepared", self.text)

    def test_a_published_game_cannot_be_published_again(self):
        self.drive()
        self.assertEqual(self.publish(), 0)
        rows_before = len(ledger.rows(self.root))
        self.out.clear()
        self.assertEqual(self.publish(), 2)
        self.assertEqual(len(ledger.rows(self.root)), rows_before)

    def test_a_hound_with_no_final_decision_is_skipped_not_counted_as_a_pass(self):
        self.takes = {"head": [self.moneyline_nyy]}
        game = self.mlb_game()
        # answer everything except the Sharp
        result = self.plan()
        for job in result["jobs"]:
            if job["stage"] != "persona_sharp":
                self.write(job["answer"], self.answer_for(job["game"], job["stage"]))
        self.check_all()
        for _ in range(2):
            result = self.plan()
            for job in result["jobs"]:
                if job["stage"] != "persona_sharp":
                    self.write(job["answer"], self.answer_for(job["game"], job["stage"]))
            self.check_all()
        self.assertEqual(self.publish(), 0, self.text)
        gamerow = ledger.rows(self.root)[-1]
        self.assertEqual(gamerow["skipped"], ["desk_sharp"])
        self.assertNotIn("desk_sharp", gamerow["hounds"])
        # the Sharp answers later, before the game: its own batch, its own transcript
        job = next(j for j in self.plan()["jobs"] if j["stage"] == "persona_sharp")
        self.write(job["answer"], self.answer_for(job["game"], "persona_sharp"))
        self.check_all()
        self.assertEqual(self.publish(), 0, self.text)
        self.assertEqual(ledger.rows(self.root)[-1]["hounds"].keys(), {"desk_sharp"})
        self.assertTrue((game.folder / "transcript_2.json").exists())
        self.assertEqual(self.publish(), 2)

    def test_the_disagreement_table_names_the_split(self):
        takes_underdog = lambda p: H.take(p, "moneyline", "NYY", H.just_above_fair(p, "moneyline", "NYY"))
        takes_favourite = lambda p: H.take(p, "moneyline", "TB", H.just_above_fair(p, "moneyline", "TB"))
        self.takes = {"persona_fader": [takes_underdog], "persona_square": [takes_favourite],
                      "head": [takes_underdog], "persona_weather": [self.total_under]}
        self.drive()
        self.assertEqual(self.publish(), 0, self.text)
        table = json.loads((self.mlb_game().folder / "disagreement.json").read_text(encoding="utf-8"))
        by_slot = {r["slot_id"]: r for r in table["slots"]}
        ml = by_slot["moneyline"]
        self.assertEqual(ml["status"], "split")
        self.assertEqual(ml["hounds"]["desk_fader"]["selection"], "NYY")
        self.assertEqual(ml["hounds"]["desk_square"]["selection"], "TB")
        self.assertEqual(ml["hounds"]["desk_historian"]["decision"], "PASS")
        self.assertEqual(by_slot["total"]["status"], "lone")
        self.assertEqual(by_slot["run_line"]["status"], "none")
        self.assertGreaterEqual(table["counts"]["split"], 1)
        self.assertIn("not confirmation", table["note"])

    def test_agree_needs_two_takers_on_one_side(self):
        takes_underdog = lambda p: H.take(p, "moneyline", "NYY", H.just_above_fair(p, "moneyline", "NYY"))
        self.takes = {"persona_fader": [takes_underdog], "head": [takes_underdog]}
        self.drive()
        self.publish()
        table = json.loads((self.mlb_game().folder / "disagreement.json").read_text(encoding="utf-8"))
        self.assertEqual({r["slot_id"]: r["status"] for r in table["slots"]}["moneyline"], "agree")

    def test_football_publishes_with_its_own_ids(self):
        H.Env.setUp(self)           # a clean root for this test
        self.assertEqual(self.prepare_nfl(), 0, self.text)
        game = self.nfl_game()
        underdog = game.packet["markets"]["moneyline"]["options"][1]["selection"]
        self.assertEqual(underdog, "BUF")
        take = lambda p: H.take(p, "moneyline", "BUF", H.just_above_fair(p, "moneyline", "BUF"))
        self.takes = {"persona_fader": [take]}
        for _ in range(4):
            result = session.plan(NF.DATE, cfg=NF.CFG, now=lambda: NF.NOW, out=self.silent, root=self.root)
            if not result["jobs"]:
                break
            for job in result["jobs"]:
                self.write(job["answer"], self.answer_for(job["game"], job["stage"]))
            session.check_all(NF.DATE, now=lambda: NF.NOW, out=self.silent, root=self.root)
        code = publish.publish(self.nfl_game(), model="m", cfg=NF.CFG, now=lambda: NF.NOW, out=self.out.append,
                               root=self.root)
        self.assertEqual(code, 0, self.text)
        bet = self.bet_rows()[0]
        self.assertEqual((bet["hound_id"], bet["sport"], bet["nfl_game_id"], bet["market"], bet["side"]),
                         ("desk_fader", "nfl", NF.GAME_ID, "moneyline", "away"))
        self.assertNotIn("game_pk", bet)
        self.assertEqual(bet["start_utc"], NF.KICKOFF)


class GradingAndTheReader(Flow):
    def setUp(self):
        super().setUp()
        self.prepare_mlb()
        underdog = lambda p: H.take(p, "moneyline", "NYY", H.just_above_fair(p, "moneyline", "NYY"))
        under = lambda p: H.take(p, "total", "Under 7", H.just_above_fair(p, "total", "Under 7"))
        self.takes = {"head": [underdog, under]}
        self.drive()
        self.assertEqual(self.publish(), 0, self.text)

    def grade(self, results):
        return cli.main(["--root", str(self.root), "grade", "--date", F.DATE], out=self.out.append,
                        now=self.clock(), results=lambda d: results)

    def test_grading_settles_at_both_prices_and_is_idempotent(self):
        self.assertEqual(self.grade(({849835: {"away_score": "5", "home_score": "3"}}, [])), 0)
        graded = [r for r in ledger.rows(self.root) if r["kind"] == ledger.KIND_GRADED]
        by = {r["market"]: r for r in graded}
        ml = by["moneyline"]
        opt = self.mlb_game().packet["markets"]["moneyline"]["options"][1]
        self.assertEqual(ml["result"], "win")
        self.assertAlmostEqual(ml["units_best_price"], opt["best"]["price"] / 100, places=2)
        avg = risk.board_average(opt)
        self.assertAlmostEqual(ml["units_average_price"], avg / 100, places=2)
        self.assertEqual(ml["units"], ml["units_best_price"])
        self.assertIsNone(ml["close_price"])
        self.assertIsNone(ml["clv_pts"])
        self.assertEqual(by["total"]["result"], "loss")        # 8 runs against an Under 7
        self.assertEqual(by["total"]["units_best_price"], -1.0)
        before = len(ledger.rows(self.root))
        self.out.clear()
        self.grade(({849835: {"away_score": "5", "home_score": "3"}}, []))
        self.assertEqual(len(ledger.rows(self.root)), before)
        self.assertTrue(ledger.verify(self.root).ok)

    def test_a_game_with_no_result_stays_ungraded_never_a_loss(self):
        self.grade(({}, []))
        self.assertEqual([r for r in ledger.rows(self.root) if r["kind"] == ledger.KIND_GRADED], [])
        self.assertIn("still waiting", self.text)

    def test_the_leaderboards_own_reader_reads_the_desk_ledger(self):
        self.grade(({849835: {"away_score": "5", "home_score": "3"}}, []))
        bets, defs = ledgers.pack_ledger_rows(ledger.path(self.root))
        self.assertEqual(set(defs), {h["id"] for h in roles.HOUNDS})
        self.assertEqual({d["category"] for d in defs.values()}, {"ai-desk", "persona"})
        self.assertEqual(len(bets), 2)
        ml = next(b for b in bets if b.market_key == "h2h")
        opt = self.mlb_game().packet["markets"]["moneyline"]["options"][1]
        self.assertEqual((ml.hound_id, ml.side, ml.price, ml.price_average, ml.who_decided, ml.segment,
                          ml.result, ml.event_id),
                         ("desk_ai", "away", opt["best"]["price"], risk.board_average(opt), "model",
                          "forward", "win", "evt-nyy-tb"))
        self.assertAlmostEqual(ml.units, opt["best"]["price"] / 100, places=2)
        total = next(b for b in bets if b.market_key == "totals")
        self.assertEqual((total.side, total.line, total.result), ("under", "7.0", "loss"))
        self.assertTrue(all(b.decision_utc and b.decision_utc < b.start_utc for b in bets))


if __name__ == "__main__":
    unittest.main()
