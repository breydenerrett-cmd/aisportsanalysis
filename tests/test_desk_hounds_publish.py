"""Publishing: the ledger rows, the transcript, the refusals, the disagreement table. Offline."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import timedelta

from src.hounds.desk import ledger, publish, risk, roles, session, state
from tests import _desk_hounds_fixtures as H
from tests import analyst_fixtures as F
from tests import nfl_analyst_fixtures as NF
from tests._desk_hounds_fixtures import Flow


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


if __name__ == "__main__":
    unittest.main()
