"""The AI hounds, end to end through the real runner: forward only, one decision per game, -200 never, a pass on
any failure, the provider on every bet, no person in a prompt, and a council that needs a majority.

Every model call is a fake client; ``setUp`` makes the network entry points raise.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.ai import router as R
from src.hounds import ai_defs, ai_packet, ai_runner, house, pack as pack_mod, pack_run
from src.hounds.pack import ai_hounds, base
from src.ledger.chain import HashChainLedger
from tests.test_house_pack_hounds import START, T, basic_stores, game_rows, mlb_game
from tests.test_ai_router import Clock, FakeAdapter, fake_config, reply

ROOT = Path(__file__).resolve().parents[1]
LOCKED = START - timedelta(minutes=30)          # inside the lock window: lock passed, start not yet
KEY = "sk-ant-test-0000000000"


def answer(decision="bet", market="moneyline", side="home", confidence=3, reason="Home price looks short of the books' number."):
    return json.dumps({"decision": decision, "market": market, "side": side, "confidence": confidence, "reason": reason})


PASS = answer("pass", None, None, 2, "Nothing here stands out.")


class ScriptedClient:
    """An Anthropic-shaped client whose replies come from ``respond(request) -> text`` (or raise)."""

    def __init__(self, respond):
        self.respond, self.requests = respond, []
        self.messages = mock.Mock(create=self._create)

    def _create(self, **kw):
        self.requests.append(kw)
        text = self.respond(kw)
        usage = mock.Mock(input_tokens=1200, output_tokens=90, cache_creation_input_tokens=0, cache_read_input_tokens=0)
        return mock.Mock(content=[mock.Mock(type="text", text=text)], usage=usage, stop_reason="end_turn")


class HoundCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.ledger = str(self.dir / "ai_hounds_v1.jsonl")
        self.decisions = str(self.dir / "ai_decisions_v1.jsonl")
        self.clock = Clock("2026-09-20T22:40:00")
        for target in ("urllib.request.urlopen", "socket.create_connection"):
            patcher = mock.patch(target, side_effect=AssertionError("a test reached for the network"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def haiku_router(self, respond, env=None):
        self.client = ScriptedClient(respond)
        adapter = R.AnthropicAdapter(client_factory=lambda key, timeout: self.client)
        usage = R.UsageStore(self.dir / "ai_usage.jsonl", clock=self.clock)
        return R.Router(R.load_config(), env=dict({"ANTHROPIC_API_KEY": KEY, "AI_PAID_CAP_USD": "5"}, **(env or {})),
                        adapters={"anthropic": adapter}, usage=usage)

    def run_pass(self, router, stores=None, now=LOCKED, **kw):
        return ai_runner.run_pass(now=now, router=router, stores=stores or basic_stores(), ledger=self.ledger,
                                  decisions=self.decisions, refresh_stats=lambda: None, **kw)

    def bets(self):
        return [r for r in HashChainLedger(self.ledger).read() if r.get("kind") == pack_run.KIND_BET]

    def decided(self):
        return [r for r in HashChainLedger(self.decisions).read() if r.get("kind") == "ai_decision"]


class RegistryAndConfigTests(unittest.TestCase):
    def test_ai_hounds_are_not_in_the_rule_pack_and_the_pack_is_untouched(self):
        self.assertEqual(len(pack_mod.PACK), 21)
        for hid in ai_defs.ids():
            self.assertNotIn(hid, pack_mod.BY_ID)

    def test_shipped_config_runs_one_claude_hound_and_parks_the_council(self):
        self.assertEqual([e["id"] for e in ai_defs.entries()], ["ai_claude"])
        self.assertEqual(ai_defs.ids(), frozenset({"ai_claude", "ai_council"}))
        entry = ai_defs.entry_for("ai_claude")
        self.assertEqual((entry["name"], entry["category"], entry["who_decided"], entry["providers"]),
                         ("Claude Hound", "ai", "model", ["anthropic"]))
        self.assertIs(ai_defs.entry_for("ai_council")["enabled"], False)

    def test_the_public_definitions_list_claude_hound_in_the_ai_category_and_not_the_parked_council(self):
        defs = house.definitions(ROOT / "config" / "house_hounds.json", ROOT / "config" / "house_pack.json",
                                 ROOT / "config" / "desk_hounds.json", ROOT / "config" / "ai_hounds.json")
        ai = [d for d in defs if d["source"] == "ai_cfg"]
        self.assertEqual([d["id"] for d in ai], ["ai_claude"])
        self.assertEqual((ai[0]["category"], ai[0]["not_started_when_empty"]), ("ai", True))
        from src.hounds.contract import CATEGORIES
        self.assertIn("ai", CATEGORIES)

    def test_the_rule_text_is_honest_about_what_it_does(self):
        text = ai_defs.entry_for("ai_claude")["rule_text"].lower()
        for needle in ("forward only", "paper only", "-200", "unproven"):
            self.assertIn(needle, text)
        everything = json.dumps(ai_defs.load_config()).lower()
        for banned in ("bet check", "betcheck", "guarantee", "sure thing", "beats the market", "locks"):
            self.assertNotIn(banned, everything)
        self.assertIn("no edge or profit is claimed", ai_defs.load_config()["disclaimer"].lower())


class ForwardOnlyTests(HoundCase):
    def hound(self):
        runtime = ai_hounds.AIRuntime(self.haiku_router(lambda kw: PASS), HashChainLedger(self.decisions))
        return ai_hounds.build_hounds(runtime)[0]

    def test_the_runner_refuses_to_replay_an_ai_hound(self):
        with self.assertRaises(ai_defs.ForwardOnlyError) as caught:
            pack_run.run(basic_stores(), ["2026-09-20"], replay=True, now=START + timedelta(hours=5),
                         path=self.ledger, hounds=[self.hound()])
        self.assertIn("forward-only", str(caught.exception))
        self.assertEqual(self.bets(), [])
        self.assertEqual(self.client.requests, [], "no model call was made on the way to the refusal")

    def test_the_cli_refuses_replay_with_the_message(self):
        with mock.patch("builtins.print") as out:
            self.assertEqual(ai_runner.main(["once", "--replay"]), 2)
        self.assertIn(ai_defs.FORWARD_ONLY_MESSAGE, out.call_args[0][0])

    def test_the_backtest_and_drill_refuse_an_ai_dog_by_name(self):
        from src.hounds.interact import ask_eval, common, drill, fire
        dog = common.resolve("ai_claude")
        self.assertIsNotNone(dog)
        self.assertTrue(dog.forward_only)
        with self.assertRaises(drill.DrillError) as caught:
            drill.drill(days=7, dog=dog)
        self.assertEqual((caught.exception.code, caught.exception.status), ("ai_forward_only", 422))
        self.assertIn("forward-only", str(caught.exception))
        with self.assertRaises(fire.NotFirable) as caught2:
            ask_eval.earlier_today(dog)
        self.assertIn("forward-only", str(caught2.exception))
        with self.assertRaises(drill.DrillError):
            ask_eval.backtest(dog, 7, signed_in=True)

    def test_a_rule_hound_can_still_be_replayed(self):
        n = pack_run.run(basic_stores(), ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.ledger)
        self.assertGreater(n["games"], 0)


class OneGameTests(HoundCase):
    def test_a_bet_is_written_with_the_provider_the_model_and_a_link_to_its_decision(self):
        router = self.haiku_router(lambda kw: answer())
        report = self.run_pass(router)
        self.assertEqual(report["run"]["written"], 1)
        (bet,) = self.bets()
        self.assertEqual((bet["hound_id"], bet["segment"], bet["who_decided"], bet["stake"]),
                         ("ai_claude", "forward", "model", 1.0))
        self.assertEqual((bet["provider"], bet["model"], bet["confidence"]), ("anthropic", "claude-haiku-5-5", 3))
        self.assertEqual((bet["market"], bet["side"]), ("moneyline", "home"))
        self.assertTrue(bet["ai_hound"])
        (dec,) = self.decided()
        self.assertEqual(bet["decision_hash"], dec["row_hash"])
        self.assertEqual((dec["decided"], dec["code"], dec["provider"], dec["model"]), ("bet", "model_bet", "anthropic", "claude-haiku-5-5"))
        self.assertTrue(HashChainLedger(self.ledger).verify().ok)
        self.assertTrue(HashChainLedger(self.decisions).verify().ok)

    def test_a_model_pass_is_logged_and_writes_no_bet(self):
        self.run_pass(self.haiku_router(lambda kw: PASS))
        self.assertEqual(self.bets(), [])
        self.assertEqual([(d["decided"], d["code"]) for d in self.decided()], [("pass", "model_pass")])

    def test_each_game_is_asked_once_even_across_passes(self):
        router = self.haiku_router(lambda kw: PASS)
        self.run_pass(router)
        self.run_pass(router, now=LOCKED + timedelta(minutes=15))
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(len(self.decided()), 1)

    def test_a_provider_failure_is_a_logged_pass_and_is_never_back_filled(self):
        def boom(kw):
            raise RuntimeError("upstream is down")

        router = self.haiku_router(boom)
        report = self.run_pass(router)
        self.assertEqual(self.bets(), [])
        (dec,) = self.decided()
        self.assertEqual((dec["decided"], dec["code"]), ("pass", "no_answer"))
        self.assertIsNone(dec["market"])
        self.assertIn("no answer", dec["detail"])
        self.assertEqual(report["run"]["written"], 0)
        # the provider recovers later in the window: the game is NOT asked again, so nothing is back-filled
        router2 = self.haiku_router(lambda kw: answer())
        self.run_pass(router2, now=LOCKED + timedelta(minutes=10))
        self.assertEqual(self.bets(), [])
        self.assertEqual(self.client.requests, [], "the recovered provider was never asked about the game")

    def test_an_invalid_answer_is_a_pass_not_a_repair(self):
        self.run_pass(self.haiku_router(lambda kw: answer(confidence=9)))
        self.assertEqual(self.bets(), [])
        self.assertEqual(self.decided()[0]["code"], "no_answer")

    def test_over_the_monthly_cap_the_hound_passes_and_says_why(self):
        router = self.haiku_router(lambda kw: answer(), env={"AI_PAID_CAP_USD": "0.0000001"})
        self.run_pass(router)
        self.assertEqual(self.bets(), [])
        self.assertEqual(self.client.requests, [])
        (dec,) = self.decided()
        self.assertEqual(dec["code"], "no_answer")
        self.assertTrue(router.degraded())

    def test_a_game_before_its_lock_or_after_its_start_is_never_asked(self):
        router = self.haiku_router(lambda kw: answer())
        before = self.run_pass(router, now=START - timedelta(minutes=61))
        after = self.run_pass(router, now=START)
        self.assertEqual((before["run"]["skipped_not_locked"], after["run"]["skipped_started"]), (1, 1))
        self.assertEqual(self.client.requests, [])

    def test_with_no_provider_enabled_the_pass_does_nothing_and_writes_nothing(self):
        router = self.haiku_router(lambda kw: answer(), env={"ANTHROPIC_API_KEY": ""})
        report = self.run_pass(router)
        self.assertIn("no AI provider", report["skipped"])
        self.assertFalse(os.path.exists(self.ledger) or os.path.exists(self.decisions))
        self.assertEqual(self.client.requests, [])


class NflTests(HoundCase):
    NFL_START = T("2026-10-18T17:00:00")

    def nfl_stores(self):
        st = base.Stores()
        for r in game_rows("nfl1", self.NFL_START, away="Kansas City Chiefs", home="Buffalo Bills", sport="nfl",
                           observed=self.NFL_START - timedelta(hours=3), home_ml=-110, away_ml=-110, spread=(-1.5, -110, -110)):
            st.add_row(r)
        st.nfl_games = [
            {"game_id": "g1", "season": 2026, "away_team": "KC", "home_team": "DEN", "kickoff_utc": "2026-10-04T17:00:00Z",
             "status": "final", "away_score": 27, "home_score": 20, "gameday": "2026-10-04"},
            {"game_id": "g2", "season": 2026, "away_team": "MIA", "home_team": "BUF", "kickoff_utc": "2026-10-11T17:00:00Z",
             "status": "final", "away_score": 10, "home_score": 24, "gameday": "2026-10-11"},
            {"game_id": "g3", "season": 2026, "away_team": "KC", "home_team": "BUF", "kickoff_utc": "2026-10-18T17:00:00Z",
             "status": "scheduled", "away_score": None, "home_score": None, "gameday": "2026-10-18"}]
        st.finalize()
        return st

    def test_an_nfl_game_is_asked_with_football_form_and_a_spread_bet_is_priced_on_the_board(self):
        router = self.haiku_router(lambda kw: answer("bet", "spread", "home", 4, "Buffalo has been scoring more."))
        self.run_pass(router, stores=self.nfl_stores(), now=self.NFL_START - timedelta(minutes=30))
        user = self.client.requests[0]["messages"][0]["content"]
        packet = json.loads(user[user.index("{"):])
        self.assertEqual(packet["game"]["sport"], "NFL")
        self.assertEqual(packet["form"]["home"]["club"], "BUF")
        self.assertEqual(packet["form"]["home"]["games"], 1)
        self.assertIn("points_for_per_game", packet["form"]["home"])
        self.assertNotIn("g3", user)
        (bet,) = self.bets()
        self.assertEqual((bet["sport"], bet["market"], bet["side"], bet["line"]), ("nfl", "spread", "home", -1.5))


class PriceRuleTests(HoundCase):
    def stores_at(self, home_ml, away_ml, **kw):
        st = base.Stores()
        for r in game_rows("evH", START, home_ml=home_ml, away_ml=away_ml, **kw):
            st.add_row(r)
        st.finalize()
        return st

    def test_minus_200_or_worse_is_never_bet_however_confident_the_model(self):
        for price in (-200, -250, -400):
            with self.subTest(price):
                router = self.haiku_router(lambda kw: answer(confidence=5))
                self.run_pass(router, stores=self.stores_at(price, 180))
                self.assertEqual([b for b in self.bets() if b["price_average"] <= -200], [])
                self.assertEqual(self.decided()[-1]["code"], "outside_band")
                self.assertEqual(self.decided()[-1]["decided"], "pass")
            for p in (self.ledger, self.decisions):
                if os.path.exists(p):
                    os.remove(p)

    def test_minus_199_is_allowed(self):
        self.run_pass(self.haiku_router(lambda kw: answer()), stores=self.stores_at(-199, 170))
        self.assertEqual([b["price_average"] for b in self.bets()], [-199])

    def test_the_runner_still_applies_the_cap_if_a_hound_returned_a_bad_price(self):
        # defence in depth: even a selection the hound let through is refused by pack_run's own rule
        class Rogue(ai_hounds.AIHound):
            def pick(self, board, ctx):
                return [ai_hounds.AISelection("moneyline", "home", 5.0, "x", 1.0, row_extra={})]

        runtime = ai_hounds.AIRuntime(self.haiku_router(lambda kw: PASS), HashChainLedger(self.decisions))
        rogue = Rogue(ai_defs.entry_for("ai_claude"), runtime)
        pack_run.run(self.stores_at(-300, 250), ["2026-09-20"], replay=False, now=LOCKED, path=self.ledger, hounds=[rogue])
        self.assertEqual(self.bets(), [])

    def test_a_market_that_is_not_on_the_board_is_a_pass(self):
        st = base.Stores()
        for r in game_rows("evH", START, spread=None, total=None):
            st.add_row(r)
        st.finalize()
        self.run_pass(self.haiku_router(lambda kw: answer("bet", "total", "over")), stores=st)
        self.assertEqual(self.bets(), [])
        self.assertEqual(self.decided()[0]["code"], "market_not_on_board")

    def test_a_spread_and_a_total_can_be_bet_and_carry_their_lines(self):
        self.run_pass(self.haiku_router(lambda kw: answer("bet", "total", "over")))
        (bet,) = self.bets()
        self.assertEqual((bet["market"], bet["side"], bet["line"]), ("total", "over", 8.5))
        for p in (self.ledger, self.decisions):
            os.remove(p)
        self.run_pass(self.haiku_router(lambda kw: answer("bet", "spread", "away")))
        (bet,) = self.bets()
        self.assertEqual((bet["market"], bet["side"], bet["line"]), ("spread", "away", 1.5))

    def test_three_bets_a_day_at_most_and_the_model_is_not_asked_past_the_cap(self):
        st = base.Stores()
        for i in range(6):
            for r in game_rows(f"ev{i}", START + timedelta(minutes=2 * i)):
                st.add_row(r)
        st.finalize()
        router = self.haiku_router(lambda kw: answer())
        self.run_pass(router, stores=st, now=LOCKED + timedelta(minutes=20))
        self.assertEqual(len(self.bets()), 3)
        self.assertEqual(len(self.client.requests), 3, "the 4th to 6th games are not even asked")
        self.run_pass(router, stores=st, now=LOCKED + timedelta(minutes=25))
        self.assertEqual(len(self.bets()), 3)


class PromptTests(HoundCase):
    def sent(self, stores=None, **kw):
        router = self.haiku_router(lambda kw_: PASS)
        self.run_pass(router, stores=stores, **kw)
        req = self.client.requests[0]
        return req["system"], req["messages"][0]["content"]

    def test_no_person_no_secret_and_no_pii_is_in_what_is_sent(self):
        system, user = self.sent()
        self.assertEqual(R.check_prompt(system + "\n" + user, [KEY]), [])
        lowered = (system + user).lower()
        for banned in ("@", "token", "password", "bet check", "betcheck", "user_id", "account"):
            self.assertNotIn(banned, lowered, banned)
        self.assertIn("New York Yankees", user)
        self.assertIn("-200", system)

    def test_a_quote_after_the_lock_and_a_result_after_the_game_never_reach_the_model(self):
        clean_sys, clean_user = self.sent()
        for p in (self.ledger, self.decisions):
            if os.path.exists(p):
                os.remove(p)
        late = game_rows("evA", START, observed=START - timedelta(minutes=20), home_ml=-400, away_ml=320)
        games = [mlb_game(999, "2026-09-20", "NYY", "BOS", 11, 0), mlb_game(998, "2026-09-21", "NYY", "BOS", 0, 9)]
        base_stores = basic_stores()
        dirty = basic_stores(extra_rows=late, mlb_games=list(base_stores.mlb_games) + games)
        self.assertEqual(self.sent(stores=dirty), (clean_sys, clean_user))

    def test_the_packet_has_the_board_by_book_the_movement_and_the_form(self):
        st = basic_stores()
        ctx = base.build_context(st, "evA")
        board = base.lock_board(st, ctx)
        packet = ai_packet.build_packet(ctx, board, st.quotes_by_event["evA"])
        ml = packet["markets"]["moneyline"]
        self.assertEqual(len(ml["by_book"]), 5)
        self.assertEqual({"avg_price", "best_price", "best_book", "books", "fair_prob"}, set(ml["sides"]["home"]))
        self.assertEqual(set(packet["markets"]), {"moneyline", "spread", "total"})
        self.assertIsNotNone(packet["movement"]["moneyline"])
        self.assertEqual(packet["form"]["away"]["club"], "NYY")
        self.assertGreater(packet["form"]["away"]["games"], 0)
        self.assertEqual(packet["game"]["lock_utc"], base.iso(ctx.lock))
        self.assertEqual(ai_packet.build_packet(ctx, board, [])["markets"]["moneyline"]["by_book"], [])

    def test_news_is_kept_only_if_observed_at_or_before_the_lock(self):
        st = basic_stores()
        ctx = base.build_context(st, "evA")
        items = [{"observed_utc": base.iso(ctx.lock - timedelta(minutes=5)), "text": "Starter confirmed."},
                 {"observed_utc": base.iso(ctx.lock + timedelta(minutes=5)), "text": "Starter scratched."},
                 {"observed_utc": None, "text": "undated"}]
        kept = ai_packet.news_items(ctx, lambda c: items)
        self.assertEqual([k["text"] for k in kept], ["Starter confirmed."])
        self.assertEqual(ai_packet.news_items(ctx, None), [])

    def test_the_system_prompt_names_the_owners_rules_and_the_version_is_stamped(self):
        system, _ = self.sent()
        for needle in ("paper-only", "pass", "-200", "25 words", "ONE JSON object"):
            self.assertIn(needle, system)
        self.assertEqual(self.decided()[0]["prompt_version"], "ai_hound_prompt_v1")


class CouncilTests(HoundCase):
    def op(self, hid, status="bet", side="home", market="moneyline", conf=3, eligible=True, model="m"):
        return ai_hounds.Opinion(hound_id=hid, event_id="e", status=status, code="x", market=market, side=side,
                                 confidence=conf, eligible=eligible and status == "bet", model=model)

    def test_a_strict_majority_of_valid_answers_on_one_side_bets(self):
        ops = [self.op("a"), self.op("b"), self.op("c"), self.op("d", "pass", None, None)]
        out = ai_hounds.council_decision(ops, 3)
        self.assertEqual((out.status, out.side, out.market, out.code), ("bet", "home", "moneyline", "council_majority"))
        self.assertIn("3 of 4", out.reason)

    def test_exactly_half_is_not_a_majority(self):
        ops = [self.op("a"), self.op("b"), self.op("c", side="away"), self.op("d", "pass", None, None)]
        self.assertEqual(ai_hounds.council_decision(ops, 3).code, "council_no_majority")

    def test_split_sides_do_not_bet(self):
        ops = [self.op("a"), self.op("b", side="away"), self.op("c", side="away"), self.op("d", side="home")]
        self.assertEqual(ai_hounds.council_decision(ops, 3).status, "pass")

    def test_below_quorum_it_passes_and_failed_members_are_not_counted_either_way(self):
        two = [self.op("a"), self.op("b")]
        self.assertEqual(ai_hounds.council_decision(two, 3).code, "council_quorum")
        failed = ai_hounds.Opinion("c", "e", "failed", "no_answer")
        three = [self.op("a"), self.op("b"), failed]
        self.assertEqual(ai_hounds.council_decision(three, 3).code, "council_quorum")
        four = three + [self.op("d")]
        self.assertEqual(ai_hounds.council_decision(four, 3).status, "bet")           # 3 of 3 valid, the failed one ignored

    def test_a_bet_nobody_could_place_is_not_a_vote(self):
        ops = [self.op("a"), self.op("b"), self.op("c", eligible=False), self.op("d", eligible=False)]
        self.assertEqual(ai_hounds.council_decision(ops, 3).code, "council_no_majority")

    def test_agreement_on_a_side_picks_the_market_most_chose_and_ties_go_to_the_moneyline(self):
        ops = [self.op("a", market="spread"), self.op("b", market="spread"), self.op("c", market="moneyline"),
               self.op("d", market="moneyline")]
        self.assertEqual(ai_hounds.council_decision(ops, 3).market, "moneyline")
        ops[2] = self.op("c", market="spread")
        self.assertEqual(ai_hounds.council_decision(ops, 3).market, "spread")

    def council_run(self, answers):
        providers = [(f"m{i}", None) for i in range(len(answers))]
        cfg = fake_config(*providers)
        adapter = FakeAdapter({f"m{i}": [reply(a)] for i, a in enumerate(answers)})
        router = R.Router(cfg, env={f"KEY_M{i}": "k" * 12 for i in range(len(answers))}, adapters={"fake": adapter},
                          usage=R.UsageStore(self.dir / "u.jsonl", clock=self.clock))
        hounds_cfg = dict(ai_defs.load_config())
        base_entry = ai_defs.entry_for("ai_claude")
        council = dict(ai_defs.entry_for("ai_council"), enabled=True)
        hounds_cfg["hounds"] = [dict(base_entry, id=f"ai_m{i}", name=f"M{i}", providers=[f"m{i}"])
                                for i in range(len(answers))] + [council]
        path = self.dir / "ai_hounds.json"
        path.write_text(json.dumps(hounds_cfg), encoding="utf-8")
        self.run_pass(router, hounds_config=path)
        return {b["hound_id"]: b for b in self.bets()}

    def test_the_council_hound_bets_when_most_models_agree(self):
        bets = self.council_run([answer(), answer(), answer(side="away"), answer()])
        self.assertIn("ai_council", bets)
        self.assertEqual((bets["ai_council"]["side"], bets["ai_council"]["provider"]), ("home", "council"))
        self.assertEqual(sorted(h for h in bets if h != "ai_council"), ["ai_m0", "ai_m1", "ai_m2", "ai_m3"])

    def test_the_council_hound_passes_when_the_models_split(self):
        bets = self.council_run([answer(), answer(side="away"), answer(side="away"), answer()])
        self.assertNotIn("ai_council", bets)
        council = [d for d in self.decided() if d["hound_id"] == "ai_council"]
        self.assertEqual(council[0]["code"], "council_no_majority")

    def test_the_council_is_not_built_from_the_shipped_config(self):
        runtime = ai_hounds.AIRuntime(self.haiku_router(lambda kw: PASS), HashChainLedger(self.decisions))
        self.assertEqual([h.id for h in ai_hounds.build_hounds(runtime)], ["ai_claude"])


class RunnerSwitchAndStatusTests(HoundCase):
    def test_the_kill_switch_defaults_off(self):
        self.assertFalse(ai_runner.enabled({}))
        for v in ("off", "", "0", "no", "maybe"):
            self.assertFalse(ai_runner.enabled({"AI_HOUNDS": v}), v)
        for v in ("on", "ON", "1", "true", "yes"):
            self.assertTrue(ai_runner.enabled({"AI_HOUNDS": v}), v)

    def test_the_loop_starts_nothing_unless_it_is_on(self):
        calls = []
        self.assertIsNone(ai_runner.start_loop(env={}, do_pass=lambda: calls.append(1)))
        stop = threading.Event()
        done = threading.Event()
        thread = ai_runner.start_loop(env={"AI_HOUNDS": "on"}, interval_s=0.01, stop_event=stop,
                                      do_pass=lambda: (calls.append(1), done.set()))
        self.assertIsNotNone(thread)
        self.assertTrue(done.wait(2))
        stop.set()
        thread.join(2)
        self.assertGreaterEqual(len(calls), 1)

    def test_the_interval_has_a_floor(self):
        self.assertEqual(ai_runner.interval_seconds({}), 900.0)
        self.assertEqual(ai_runner.interval_seconds({"AI_HOUNDS_INTERVAL_SECONDS": "1"}), ai_runner.MIN_INTERVAL_SECONDS)
        self.assertEqual(ai_runner.interval_seconds({"AI_HOUNDS_INTERVAL_SECONDS": "x"}), 900.0)

    def test_pass_safely_records_an_error_and_never_raises(self):
        with mock.patch.object(ai_runner, "run_pass", side_effect=RuntimeError("bad")):
            self.assertIn("error", ai_runner.pass_safely())
        self.assertIn("RuntimeError", ai_runner.STATUS["last_error"])

    def test_the_status_panel_shows_providers_usage_spend_cap_and_errors_and_no_key(self):
        router = self.haiku_router(lambda kw: answer())
        self.run_pass(router)
        status = ai_runner.build_status(router=router, env={"AI_HOUNDS": "on"}, ledger=self.ledger,
                                        decisions=self.decisions, now=LOCKED)
        self.assertTrue(status["switch"]["on"])
        (prov,) = status["router"]["providers"]
        self.assertEqual((prov["id"], prov["model"], prov["enabled"], prov["calls_today"]), ("anthropic", "claude-haiku-5-5", True, 1))
        self.assertEqual(status["router"]["paid"]["cap_usd"], 5.0)
        self.assertGreater(status["router"]["paid"]["spend_usd"], 0)
        self.assertEqual((status["ledger"]["bets"], status["ledger"]["decisions_today"]), (1, 1))
        self.assertEqual(status["router"]["last_errors"], [])
        self.assertNotIn(KEY, json.dumps(status))
        self.assertTrue(status["forward_only"] and status["paper_only"])

    def test_the_status_panel_shows_the_last_errors_and_the_degraded_flag(self):
        class Boom(Exception):
            status_code = 500

        def boom(kw):
            raise Boom("server error")

        router = self.haiku_router(boom)
        self.run_pass(router)
        status = ai_runner.build_status(router=router, env={}, ledger=self.ledger, decisions=self.decisions)
        self.assertEqual(status["router"]["last_errors"][0]["status"], "error")
        self.assertTrue(status["router"]["degraded"])
        self.assertFalse(status["switch"]["on"])

    def test_the_admin_route_is_mounted_behind_the_admin_gate(self):
        try:
            from fastapi.testclient import TestClient
            from api.app import app
        except Exception as exc:                                   # noqa: BLE001 -- CI has no FastAPI
            self.skipTest(f"FastAPI not importable here: {type(exc).__name__}")
        self.assertIn("/admin/ai/status", app.openapi()["paths"])
        client = TestClient(app)
        with mock.patch.dict(os.environ, {"APP_ADMIN_TOKEN": "admin-token-for-test", "AI_USAGE_PATH": str(self.dir / "u.jsonl"),
                                          "AI_HOUNDS_LEDGER": self.ledger, "AI_HOUNDS_DECISIONS": self.decisions}):
            R.reset_default_router()
            self.addCleanup(R.reset_default_router)
            self.assertEqual(client.get("/admin/ai/status").status_code, 401)
            self.assertEqual(client.get("/admin/ai/status", headers={"X-Admin-Token": "wrong"}).status_code, 401)
            ok = client.get("/admin/ai/status", headers={"X-Admin-Token": "admin-token-for-test"})
        self.assertEqual(ok.status_code, 200)
        body = ok.json()
        self.assertEqual(body["router"]["providers"][0]["model"], "claude-haiku-5-5")
        self.assertEqual(body["router"]["paid"]["cap_usd"], 5.0)
        self.assertNotIn("admin-token-for-test", ok.text)


if __name__ == "__main__":
    unittest.main()
