"""The coach's AI read of a diagnosis (src/hounds/interact/coach_ai.py, coach.py) and how a training uses it.

Runs without FastAPI and without a network: the router is faked, or the REAL router runs over a fake adapter (so the schema check,
the monthly cap and the cost accounting are the real ones). Owner request 2026-10-21: Haiku ranks the most likely reasons a hound
is losing; a reason that cites nothing real is dropped; the final changes come only from the rules engine's menu; capped or down,
the rules engine's ranking is the read and the screen says so.
"""

from __future__ import annotations

import json
import random
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.ai import router as R
from src.hounds import user_coach, user_spec, user_store
from src.hounds.interact import coach, coach_ai, diagnosis as D, rites, training
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for
from tests._hounds_user_fixtures import spec_dict
from tests.test_hounds_training import MIXED, Train, assert_narrower, synthetic_plan, v1_specs, v2_specs

PLAN = [(7, dict(result="LOSS", side="away", price=180)), (2, dict(result="WIN", side="away", price=180)),
        (6, dict(result="WIN", side="home", price=-125, sport="NFL")), (3, dict(result="LOSS", side="home", price=-125, sport="NFL"))]
KEY = "test-key-not-a-real-secret-0001"


class FakeAdapter:
    """Stands in for the Anthropic adapter: the reply is computed from the user message it was sent, so a scripted 'Haiku' can cite
    the ids that really are in the table (or fake ones). Records every call, including whether the system prompt was cacheable."""

    def __init__(self, make, tin=2400, tout=380, cache_write=0, cache_read=0):
        self.make, self.calls = make, []
        self.tin, self.tout, self.cache_write, self.cache_read = tin, tout, cache_write, cache_read

    def complete(self, spec, model, system, user, *, api_key, timeout_s, max_tokens, cache_system=False):
        self.calls.append({"system": system, "user": user, "cache_system": cache_system, "max_tokens": max_tokens, "key": api_key})
        payload = json.loads(user)
        return R.AdapterResult(text=json.dumps(self.make(payload)), input_tokens=self.tin, output_tokens=self.tout,
                               cache_write_tokens=self.cache_write, cache_read_tokens=self.cache_read)


def real_router(tmp, adapter, cap=None, key=KEY):
    env = {"ANTHROPIC_API_KEY": key}
    if cap is not None:
        env["AI_PAID_CAP_USD"] = str(cap)
    return R.Router(config=R.load_config(), env=env, adapters={"anthropic": adapter}, usage_path=Path(tmp) / "usage.jsonl")


class FakeAnswer:
    def __init__(self, output=None, ok=True, reason="", cost=0.0004, model="claude-haiku-5-5"):
        self.output, self.ok, self.reason, self.cost_usd, self.model, self.latency_ms, self.attempts = output, ok, reason, cost, model, 900, []


class FakeRouter:
    def __init__(self, answer=None, raises=None):
        self.answer, self.raises, self.calls = answer, raises, []

    def ask(self, system, user, **kw):
        self.calls.append((system, user, kw))
        if self.raises:
            raise self.raises
        return self.answer


def good_reply(payload, picks=None):
    """What a careful model would say about THIS table: the first two ranked, trusted-or-not, real ids."""
    ranked = payload["ranked"]
    rows = {r["id"]: r for r in payload["rows"]}
    first, second = ranked[0], ranked[1] if len(ranked) > 1 else ranked[0]
    return {"summary": "The record is short, and the weakest parts are on the road.",
            "reasons": [{"factors": [first], "text": "This cut lost the most units and is the first place to look.", "confidence": "high"},
                        {"factors": [second], "text": "This cut also lost units.", "confidence": "medium"}],
            "try": picks if picks is not None else [c["cid"] for c in payload["candidates"][:2]]}


class Setup(Train):
    def setUp(self):
        super().setUp()
        self.hound = self.dog("Rusty Pup", sports=["MLB", "NFL"])
        self.rows = rows_for(self.hound["id"], PLAN)
        self.bets = rites.forward_bets(self.hound["id"], self.rows)
        self.spec = user_store.get_hound(self.hound["id"])["spec"]
        self.analysis = training.analyse(self.bets, self.spec)
        self.table = D.diagnose(self.bets, self.spec, rows=self.rows)
        self.entries = training.menu(self.spec, self.analysis, self.table)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def ask(self, make, **kw):
        adapter = FakeAdapter(make, **{k: v for k, v in kw.items() if k in ("tin", "tout", "cache_write", "cache_read")})
        router = real_router(self.tmp.name, adapter, cap=kw.get("cap"))
        return coach_ai.assess(self.table, self.entries, router=router), adapter, router


class TheModelOnlyEverReadsTheTable(Setup):
    def test_what_is_sent_is_numbers_and_ids_with_no_person_bet_team_or_rule_label(self):
        read, adapter, _router = self.ask(good_reply)
        call = adapter.calls[0]
        text = call["system"] + call["user"]
        for forbidden in ("Rusty Pup", self.hound["id"], "Seattle", "Boston", "@", "owner"):
            self.assertNotIn(forbidden, call["user"])
        for bet in self.bets:
            self.assertNotIn(bet.bet_id, text)
        sent = json.loads(call["user"])
        self.assertEqual(sent["settled"], 18)
        self.assertEqual({c["cid"] for c in sent["candidates"]}, {e["cid"] for e in self.entries})
        self.assertEqual(sent["ranked"], self.table["ranked"])

    def test_the_fixed_system_prompt_is_big_enough_to_be_cached_and_is_marked_so(self):
        router = real_router(self.tmp.name, FakeAdapter(good_reply))
        spec = router.specs[0]
        self.assertTrue(router.wants_cache(spec, coach_ai.SYSTEM_PROMPT), "the system prompt is over the router's cache line")
        read, adapter, _r = self.ask(good_reply)
        self.assertTrue(adapter.calls[0]["cache_system"])
        self.assertEqual(adapter.calls[0]["system"], coach_ai.SYSTEM_PROMPT, "the system prompt is fixed: only the user turn varies")
        self.assertEqual(adapter.calls[0]["max_tokens"], coach_ai.MAX_TOKENS)

    def test_the_system_prompt_tells_it_to_read_not_to_compute_or_promise(self):
        p = coach_ai.SYSTEM_PROMPT
        for needle in ("not_checked", "too_few", "at least one row that lost units", "Never say or imply what will happen",
                       "the ONLY changes the app allows", "hound", "paper"):
            self.assertIn(needle, p)

    def test_a_good_answer_is_the_ai_read_with_the_tables_own_lines_cited(self):
        read, adapter, _r = self.ask(good_reply)
        self.assertEqual((read["source"], read["label"], read["status"]), ("ai", "AI read", "ok"))
        self.assertEqual(read["model"], "claude-haiku-5-5")
        table = D.by_id(self.table)
        self.assertEqual(len(read["reasons"]), 2)
        for r in read["reasons"]:
            for cited in r["cited"]:
                self.assertEqual(cited["line"], table[cited["id"]]["line"], "the screen shows the table's line, not the model's")
        self.assertGreater(read["cost_usd"], 0)


class ACitationThatIsNotRealIsDropped(Setup):
    def reply(self, reasons, **kw):
        return lambda payload: {"summary": kw.get("summary", "A short read."), "reasons": reasons(payload), "try": kw.get("picks", [])}

    def test_a_reason_citing_an_id_that_does_not_exist_is_dropped_and_a_real_one_stays(self):
        real = self.table["ranked"][0]
        read, _a, _r = self.ask(self.reply(lambda p: [
            {"factors": ["band:made_up"], "text": "Invented cut.", "confidence": "high"},
            {"factors": [real], "text": "The real weak spot.", "confidence": "medium"}]))
        self.assertEqual([r["factors"] for r in read["reasons"]], [[real]])
        self.assertEqual(read["dropped"], [{"factors": ["band:made_up"], "why": "cites a factor that was not checked"}])
        self.assertEqual(read["source"], "ai")

    def test_a_reason_with_one_real_and_one_fake_id_is_dropped_whole(self):
        real = self.table["ranked"][0]
        read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [real, "venue:sideways"], "text": "Half real.", "confidence": "low"},
                                                      {"factors": [real], "text": "Fully real.", "confidence": "low"}]))
        self.assertEqual([r["text"] for r in read["reasons"]], ["Fully real."])

    def test_if_every_reason_is_fake_the_rules_engine_read_is_used_and_the_spend_is_still_recorded(self):
        read, _a, router = self.ask(self.reply(lambda p: [{"factors": ["nope:1"], "text": "Nothing real.", "confidence": "high"}]))
        self.assertEqual((read["source"], read["label"], read["status"]), ("rules", "Coach's read (rules engine)", "dropped_all"))
        self.assertEqual([r["factors"] for r in read["reasons"]][0], [self.table["ranked"][0]])
        self.assertGreater(read["cost_usd"], 0, "the call was made and paid for; the read says so")
        self.assertEqual(read["picks"], [])

    def test_a_factor_that_was_not_checked_cannot_be_cited(self):
        self.assertIn("rest:none", D.by_id(self.table))
        read, _a, _r = self.ask(self.reply(lambda p: [{"factors": ["rest:none"], "text": "Rest.", "confidence": "high"}]))
        self.assertEqual(read["source"], "rules")
        self.assertEqual(read["dropped"][0]["why"], "cites a factor that was not checked")

    def test_a_reason_that_cites_only_cuts_that_did_not_lose_is_dropped(self):
        winning = next(f["id"] for f in self.table["rows"] if f["kind"] == "segment" and f["direction"] == "for")
        read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [winning], "text": "This one made money.", "confidence": "high"}]))
        self.assertEqual(read["dropped"][0]["why"], "cites nothing that lost units")

    def test_a_reason_that_promises_or_forecasts_is_dropped(self):
        real = self.table["ranked"][0]
        for words in ("The new version will do better.", "Fix this and it should win.", "Dropping it should improve results.",
                      "That is where the edge is.", "Going forward it is profitable."):
            with self.subTest(words=words):
                read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [real], "text": words, "confidence": "high"}]))
                self.assertEqual(read["source"], "rules", words)
                self.assertEqual(read["dropped"][0]["why"], "promises or forecasts")

    def test_softer_forecasts_numbers_in_words_links_and_bet_instructions_are_dropped_too(self):
        # checker finding 2026-10-21: the first filter caught "will" and "improve" but let these through
        real = self.table["ranked"][0]
        for words in ("It should bounce back.", "It is due to turn around.", "Expect a rebound.", "It'll recover.",
                      "Likely to recover soon.", "The new version is expected to do well.", "Keep an eye on it next week.",
                      "Lost three of its first four.", "About half of them lost.", "See http://evil.example/x.",
                      "Email me at a@b.com.", "Take the other side of these."):
            with self.subTest(words=words):
                read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [real], "text": words, "confidence": "low"}]))
                self.assertEqual(read["source"], "rules", words)
                self.assertTrue(read["dropped"], words)

    def test_a_reason_that_states_a_number_its_factors_do_not_contain_is_dropped(self):
        real = self.table["ranked"][0]
        read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [real], "text": "It went 17-2 with 94 percent of picks.", "confidence": "high"}]))
        self.assertEqual(read["dropped"][0]["why"], "states a number its factors do not contain")

    def test_a_number_that_is_in_the_cited_factor_is_fine(self):
        f = next(x for x in self.table["rows"] if x["id"] == self.table["ranked"][0])
        text = f"Went {f['wins']}-{f['losses']} over {f['n']} bets."
        read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [f["id"]], "text": text, "confidence": "low"}]))
        self.assertEqual((read["source"], read["reasons"][0]["text"]), ("ai", text))

    def test_confidence_never_exceeds_what_the_cited_cuts_can_support(self):
        small = next(f for f in self.table["rows"] if f["kind"] == "segment" and f["direction"] == "against" and f["level"] == "too_few")
        read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [small["id"]], "text": "Only a handful of bets here.", "confidence": "high"}]))
        self.assertEqual((read["reasons"][0]["confidence"], read["reasons"][0]["thin"]), ("low", True))

    def test_the_word_dog_never_reaches_the_screen(self):
        real = self.table["ranked"][0]
        read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [real], "text": "The dog lost on the road; other dogs did too.", "confidence": "low"}]))
        self.assertEqual(read["reasons"][0]["text"], "The hound lost on the road; other hounds did too.")

    def test_a_summary_that_forecasts_is_not_shown_but_the_reasons_still_are(self):
        real = self.table["ranked"][0]
        read, _a, _r = self.ask(self.reply(lambda p: [{"factors": [real], "text": "Weakest part.", "confidence": "low"}],
                                           summary="It will bounce back."))
        self.assertIsNone(read["summary"])
        self.assertEqual(read["source"], "ai")

    def test_an_invalid_shape_never_gets_past_the_router(self):
        read, _a, _r = self.ask(lambda p: {"summary": "x", "reasons": [], "try": []})        # minItems 1 fails the schema
        self.assertEqual((read["source"], read["status"]), ("rules", "down"))


class TheFinalChangesComeOnlyFromTheMenu(Setup):
    def wide_dog(self):
        """A dog whose price range starts inside the underdog band, so tightening that band is on the menu beside dropping MLB."""
        hound = self.dog("Wide Pup", sports=["MLB", "NFL"], price_min=110, price_max=250)
        rows = rows_for(hound["id"], PLAN)
        bets = rites.forward_bets(hound["id"], rows)
        spec = user_store.get_hound(hound["id"])["spec"]
        analysis = training.analyse(bets, spec)
        table = D.diagnose(bets, spec, rows=rows)
        return hound, spec, analysis, training.menu(spec, analysis, table)

    def test_a_pick_on_the_menu_is_used_first_and_marked_as_the_coachs(self):
        hound, spec, analysis, entries = self.wide_dog()
        cids = [e["cid"] for e in entries]
        self.assertGreaterEqual(len(cids), 2, cids)
        base = training.propose(spec, analysis, seed_key="train-v1", hound_id=hound["id"], light=False)
        last = cids[-1]
        self.assertNotEqual(base[1][0]["cid"], last, "the pick is not simply what the rules would have done first")
        new, changes, mode, _note = training.propose(spec, analysis, seed_key="train-v1", hound_id=hound["id"], light=False,
                                                     preferred=[last], entries=entries)
        self.assertEqual((mode, changes[0]["cid"], changes[0]["pick"], len(changes)), ("analysed", last, "coach", 1))
        assert_narrower(self, spec, new)
        self.assertTrue(all(c["cid"] in cids for c in changes))

    def test_a_pick_that_is_not_on_the_menu_is_ignored_and_the_rules_order_runs(self):
        base = training.propose(self.spec, self.analysis, seed_key="train-v1", hound_id=self.hound["id"], light=False)
        for bogus in (["widen_price:all"], ["drop_sport:CRICKET", "max_bets:99"], ["", "tighten_band:made_up"]):
            with self.subTest(bogus=bogus):
                got = training.propose(self.spec, self.analysis, seed_key="train-v1", hound_id=self.hound["id"], light=False,
                                       preferred=bogus, entries=self.entries)
                self.assertEqual(got[0], base[0])
                self.assertEqual([c["cid"] for c in got[1]], [c["cid"] for c in base[1]])
                self.assertTrue(all(c["pick"] == "rules" for c in got[1]))

    def test_a_trained_hound_only_ever_has_changes_from_the_menu_whatever_the_model_asks_for(self):
        menu_cids = {e["cid"] for e in self.entries}
        asks = [["drop_sport:NFL", "widen_price:all", "min_books:1", "venue:away"], ["fewer_bets"] * 5, ["x"] * 10,
                list(menu_cids)[::-1]]
        for i, ask in enumerate(asks):
            with self.subTest(ask=ask):
                # a fixed name: hash() is salted per process, and a random number can land on a banned one (CI 2026-10-22)
                hound = self.dog(f"Menu Pup {chr(65 + i)}", sports=["MLB", "NFL"])
                rows = rows_for(hound["id"], PLAN)
                shown = coach.Coach(assess_fn=lambda table, entries, _ask=ask: {
                    **coach_ai.rules_read(table, status="ok"), "source": "ai", "label": "AI read", "picks": list(_ask), "model": "m"})
                out = self.train(hound, rows, coach=shown)
                self.assertTrue(all(c["cid"] in menu_cids for c in out["changes"]), [c["cid"] for c in out["changes"]])
                new = user_store.get_hound(out["new"]["id"])
                assert_narrower(self, user_store.get_hound(hound["id"])["spec"], new["spec"])
                user_spec.validate_spec(new["spec"], taken_names=())

    def test_a_sweep_over_every_shape_every_menu_entry_alone_and_all_of_them_shuffled_narrows_and_validates(self):
        checked = 0
        for i, spec in enumerate(list(v1_specs())[:40] + list(v2_specs())[:25]):
            rng = random.Random(i)
            rows = rows_for("u-x", synthetic_plan(spec, rng))
            bets = rites.forward_bets("u-x", rows)
            analysis = training.analyse(bets, spec, training.rule_index_of(rows, "u-x"))
            table = D.diagnose(bets, spec, rows=rows, rule_index=training.rule_index_of(rows, "u-x"))
            entries = training.menu(spec, analysis, table)
            cids = [e["cid"] for e in entries]
            orders = [[c] for c in cids]
            shuffled = list(cids)
            rng.shuffle(shuffled)
            orders.append(shuffled)
            for order in orders:
                new, changes, mode, _n = training.propose(spec, analysis, seed_key="train-v1", hound_id="u-x", light=False,
                                                          preferred=order, entries=entries)
                if new is None:
                    continue
                with self.subTest(name=spec["name"], order=order):
                    self.assertTrue(1 <= len(changes) <= training.MAX_CHANGES)
                    self.assertNotEqual(user_spec.spec_hash(new), user_spec.spec_hash(spec))
                    assert_narrower(self, spec, new)
                    self.assertEqual(user_coach.narrowing_problems(spec, new) if not user_spec.is_v2(spec) else [], [])
                    self.assertTrue(all(c["cid"] in cids or c["pick"] == "rules" for c in changes))
                checked += 1
        self.assertGreater(checked, 50)

    def test_a_pick_aimed_at_thin_books_raises_the_books_a_price_needs(self):
        from tests._hounds_rites_fixtures import ticket
        spec = user_spec.validate_spec(spec_dict(name="Books Pup", sports=["MLB"], min_books=3))
        rows = []
        for i in range(12):
            few = i < 6
            pair = ticket("h-bk", day=i, result="LOSS" if few else "WIN", side="home", price=120)
            pair[0].update(book_count=3 if few else 8, n_books=3 if few else 8)
            rows += pair
        bets = rites.forward_bets("h-bk", rows)
        analysis = training.analyse(bets, spec)
        table = D.diagnose(bets, spec, rows=rows)
        entries = training.menu(spec, analysis, table)
        entry = next(e for e in entries if e["cid"] == "more_books:all")
        self.assertEqual(entry["addresses"], ["books:few"])
        new, changes, _m, _n = training.propose(spec, analysis, seed_key="train-v1", hound_id="h-bk", light=False,
                                                preferred=["more_books:all"], entries=entries)
        self.assertEqual((changes[0]["id"], changes[0]["pick"], new["min_books"], spec["min_books"]), ("more_books", "coach", 4, 3))
        self.assertEqual(changes[0]["factors"], ["books:few"])
        self.assertIn("0-6", changes[0]["why"])
        assert_narrower(self, spec, new)

    def test_a_menu_entry_for_books_or_the_daily_limit_exists_only_when_the_table_lost_there(self):
        # three bets on one day with a limit of 2, all lost: "the daily limit" cut lost, so fewer_bets is on the menu
        spec = user_spec.validate_spec(spec_dict(name="Cap Pup", sports=["MLB"], max_bets_per_day=3))
        rows = []
        plan = [(0, "LOSS"), (0, "LOSS"), (0, "LOSS"), (1, "WIN"), (2, "WIN"), (3, "WIN"), (4, "WIN")]
        from tests._hounds_rites_fixtures import ticket
        for day, res in plan:
            rows += ticket("h-cap", day=day, result=res, side="home", price=110)
        bets = rites.forward_bets("h-cap", rows)
        analysis = training.analyse(bets, spec)
        table = D.diagnose(bets, spec, rows=rows)
        self.assertIn("fewer_bets", [e["cid"] for e in training.menu(spec, analysis, table)])
        self.assertNotIn("fewer_bets", [e["cid"] for e in training.menu(spec, analysis, None)])


class CappedOrDownTheRulesEngineReads(Setup):
    def test_the_monthly_cap_turns_the_ai_read_into_the_rules_engine_read_without_a_call(self):
        adapter = FakeAdapter(good_reply)
        router = real_router(self.tmp.name, adapter, cap=0.0000001)
        read = coach_ai.assess(self.table, self.entries, router=router)
        self.assertEqual(adapter.calls, [], "no call is made once the cap would be crossed")
        self.assertEqual((read["source"], read["label"], read["status"], read["cost_usd"]), ("rules", "Coach's read (rules engine)", "capped", 0.0))
        self.assertTrue(read["reasons"])

    def test_a_router_that_is_down_or_out_of_credit_or_without_a_key_falls_back_the_same_way(self):
        cases = {"down": FakeAnswer(ok=False, reason="no answer (anthropic: timeout)", cost=0.0),
                 "capped": FakeAnswer(ok=False, reason="no answer (anthropic: skipped - monthly paid cap of $5.00 reached)", cost=0.0),
                 "off": FakeAnswer(ok=False, reason="no answer (anthropic: skipped - no ANTHROPIC_API_KEY set)", cost=0.0)}
        for status, answer in cases.items():
            with self.subTest(status=status):
                read = coach_ai.assess(self.table, self.entries, router=FakeRouter(answer))
                self.assertEqual((read["source"], read["label"], read["status"]), ("rules", "Coach's read (rules engine)", status))
                self.assertEqual(read["reasons"][0]["factors"], [self.table["ranked"][0]])

    def test_a_router_that_raises_never_breaks_the_read_and_its_message_is_never_logged(self):
        with self.assertLogs("linehound.hounds.coach_ai", level="WARNING") as logs:
            read = coach_ai.assess(self.table, self.entries, router=FakeRouter(raises=RuntimeError("sk-ant-secret exploded")))
        self.assertEqual((read["source"], read["status"]), ("rules", "down"))
        self.assertNotIn("secret", json.dumps(read))
        self.assertNotIn("secret", " ".join(logs.output))
        self.assertIn("RuntimeError", " ".join(logs.output))

    def test_no_key_on_the_server_means_no_router_is_even_built(self):
        with mock.patch("src.ai.router.default_router", side_effect=AssertionError("a router was built with no key")):
            read = coach_ai.assess(self.table, self.entries, env={})
        self.assertEqual((read["source"], read["status"]), ("rules", "off"))

    def test_too_few_bets_never_calls_the_model(self):
        tiny = D.diagnose(self.bets[:3], self.spec, rows=self.rows)
        router = FakeRouter(FakeAnswer(output={}))
        read = coach_ai.assess(tiny, [], router=router)
        self.assertEqual((router.calls, read["status"]), ([], "skipped"))

    def test_the_card_calls_it_the_rules_engine_when_the_ai_did_not_read(self):
        read = coach_ai.assess(self.table, self.entries, router=FakeRouter(FakeAnswer(ok=False, reason="monthly paid cap", cost=0.0)))
        view = training.coach_view(read)
        self.assertEqual((view["label"], view["resting"], view["model_label"]), ("Coach's read (rules engine)", True, None))
        ai = coach_ai.assess(self.table, self.entries, router=real_router(self.tmp.name, FakeAdapter(good_reply)))
        view = training.coach_view(ai)
        self.assertEqual((view["label"], view["resting"], view["model_label"]), ("AI read", False, "Claude Haiku"))
        self.assertNotIn("cost", json.dumps(view), "spend is for the log and the event, not the page")

    def test_the_page_is_told_why_the_rules_engine_read_it_in_a_word(self):
        resting = coach_ai.assess(self.table, self.entries, router=FakeRouter(FakeAnswer(ok=False, reason="monthly paid cap", cost=0.0)))
        self.assertEqual(training.coach_view(resting)["why"], "resting")
        tiny = coach_ai.assess(D.diagnose(self.bets[:3], self.spec, rows=self.rows), [], router=FakeRouter(FakeAnswer(output={})))
        self.assertEqual(training.coach_view(tiny)["why"], "too_few")
        fake = coach_ai.assess(self.table, self.entries, router=real_router(self.tmp.name, FakeAdapter(
            lambda p: {"summary": "s", "reasons": [{"factors": ["nope:1"], "text": "x", "confidence": "low"}], "try": []})))
        self.assertEqual(training.coach_view(fake)["why"], "dropped")
        ai = coach_ai.assess(self.table, self.entries, router=real_router(self.tmp.name, FakeAdapter(good_reply)))
        self.assertIsNone(training.coach_view(ai)["why"])


class TheSpendIsLoggedPerTraining(Setup):
    def test_the_trained_event_carries_the_source_the_reasons_and_the_cost(self):
        adapter = FakeAdapter(good_reply, tin=2400, tout=380)
        shown = coach.Coach(router=real_router(self.tmp.name, adapter))
        out = self.train(self.hound, self.rows, coach=shown)
        events = user_store.list_events("trained", root_id=self.hound["root_id"])
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]["coach"]
        self.assertEqual((payload["source"], payload["status"], payload["model"]), ("ai", "ok", "claude-haiku-5-5"))
        # 2400 input tokens at $0.10 per million and 380 output tokens at $0.50 per million (config/ai_providers.json)
        self.assertAlmostEqual(payload["cost_usd"], 2400 * 0.10 / 1e6 + 380 * 0.50 / 1e6, places=7)
        self.assertTrue(payload["reasons"] and all(set(r) == {"factors", "confidence"} for r in payload["reasons"]))
        self.assertEqual(out["coach"]["label"], "AI read")
        usage = real_router(self.tmp.name, adapter).usage
        self.assertAlmostEqual(usage.month_spend("anthropic"), payload["cost_usd"], places=7)

    def test_the_log_line_names_the_cost(self):
        shown = coach.Coach(router=real_router(self.tmp.name, FakeAdapter(good_reply)))
        with self.assertLogs("linehound.hounds.training", level="INFO") as logs:
            self.train(self.hound, self.rows, coach=shown)
        line = next(m for m in logs.output if "training done" in m)
        self.assertRegex(line, r"coach=ai status=ok cost_usd=0\.0004\d+")

    def test_a_rules_engine_training_records_zero_cost_and_the_source(self):
        out = self.train(self.hound, self.rows)           # no coach injected: the rules engine reads, no router, no disk
        payload = user_store.list_events("trained", root_id=self.hound["root_id"])[0]["payload"]["coach"]
        self.assertEqual((payload["source"], payload["cost_usd"]), ("rules", 0.0))
        self.assertEqual(out["coach"]["label"], "Coach's read (rules engine)")

    def test_the_prompt_cache_is_read_at_a_tenth_after_the_first_call(self):
        first = FakeAdapter(good_reply, tin=600, tout=380, cache_write=1700, cache_read=0)
        again = FakeAdapter(good_reply, tin=600, tout=380, cache_write=0, cache_read=1700)
        a, _x, _r = Setup.ask(self, good_reply, tin=600, tout=380, cache_write=1700)
        b, _y, _r2 = Setup.ask(self, good_reply, tin=600, tout=380, cache_read=1700)
        self.assertGreater(a["cost_usd"], b["cost_usd"])
        self.assertAlmostEqual(a["cost_usd"] - b["cost_usd"], 1700 * 0.10 / 1e6 * (1.25 - 0.10), places=7)

    def test_one_training_costs_a_tenth_of_a_cent_or_less_at_the_configured_prices(self):
        a, _x, _r = Setup.ask(self, good_reply, tin=600, tout=420, cache_read=1700)
        self.assertLess(a["cost_usd"], 0.001)
        self.assertLess(coach_ai.MAX_TOKENS * 0.50 / 1e6 + 4200 * 0.10 / 1e6, 0.001, "even the worst case a single call may cost is under a tenth of a cent")


class TheCoachKeepsItsReadBetweenTheSteps(Setup):
    def test_the_assess_step_is_asked_once_per_set_of_settled_bets_and_the_training_takes_it(self):
        adapter = FakeAdapter(good_reply)
        shown = coach.Coach(router=real_router(self.tmp.name, adapter))
        inp = {"hound_id": self.hound["id"], "bets": self.bets, "spec": self.spec, "rows": self.rows, "rule_index": {}}
        table = shown.diagnosis(inp)
        entries = training.menu(self.spec, self.analysis, table)
        first = shown.read(inp, entries, table)
        again = shown.read(inp, entries, table)
        self.assertEqual(len(adapter.calls), 1)
        self.assertIs(first, again)
        self.train(self.hound, self.rows, coach=shown)
        self.assertEqual(len(adapter.calls), 1, "the training did not pay for the read a second time")

    def test_a_new_settled_bet_is_a_new_key_so_the_read_is_not_stale(self):
        k1 = coach.key_for(self.hound["id"], self.spec, self.bets)
        more = rites.forward_bets(self.hound["id"], self.rows + rows_for(self.hound["id"], [(1, dict(result="LOSS"))]))
        self.assertNotEqual(k1, coach.key_for(self.hound["id"], self.spec, more))
        self.assertEqual(k1, coach.key_for(self.hound["id"], self.spec, list(reversed(self.bets))))

    def test_the_cache_expires(self):
        now = [0.0]
        shown = coach.Coach(rules_only=True, ttl_s=10, clock=lambda: now[0])
        inp = {"hound_id": self.hound["id"], "bets": self.bets, "spec": self.spec, "rows": self.rows, "rule_index": {}}
        a = shown.diagnosis(inp)
        self.assertIs(a, shown.diagnosis(inp))
        now[0] = 11
        self.assertIsNot(a, shown.diagnosis(inp))

    def test_two_taps_at_once_pay_for_one_read(self):
        import threading
        calls = []
        gate = threading.Event()

        def slow(table, entries):
            calls.append(1)
            gate.wait(2)
            return coach_ai.rules_read(table, status="ok")

        shown = coach.Coach(assess_fn=slow)
        inp = {"hound_id": self.hound["id"], "bets": self.bets, "spec": self.spec, "rows": self.rows, "rule_index": {}}
        table = shown.diagnosis(inp)
        out = []
        threads = [threading.Thread(target=lambda: out.append(shown.read(inp, self.entries, table))) for _ in range(2)]
        [t.start() for t in threads]
        gate.set()
        [t.join(5) for t in threads]
        self.assertEqual((len(calls), len(out)), (1, 2))


class ReadStepRoutesWriteNothing(Setup):
    def test_the_diagnose_and_assess_steps_write_nothing_and_refuse_what_the_training_refuses(self):
        shown = coach.Coach(router=real_router(self.tmp.name, FakeAdapter(good_reply)))
        a = training.read_step(self.resolve(self.hound["id"]), self.owner.id, shown, stage="diagnose", now=NOW, rows=self.rows)
        self.assertNotIn("coach", a)
        self.assertEqual((a["diagnosis"]["settled"], a["stage"]), (18, "diagnose"))
        b = training.read_step(self.resolve(self.hound["id"]), self.owner.id, shown, stage="assess", now=NOW, rows=self.rows)
        self.assertEqual(b["coach"]["label"], "AI read")
        self.assertEqual(len(user_store.lineage(self.hound["id"])), 1, "nothing was trained")
        self.assertEqual(user_store.list_events("trained"), [])
        for bad in (dict(who=self.other.id), ):
            with self.assertRaises(rites.RiteError) as ctx:
                training.read_step(self.resolve(self.hound["id"]), bad["who"], shown, stage="diagnose", now=NOW, rows=self.rows)
            self.assertEqual(ctx.exception.code, "not_found")
        from tests._hounds_rites_fixtures import ticket
        with self.assertRaises(rites.RiteError) as ctx:
            training.read_step(self.resolve(self.hound["id"]), self.owner.id, shown, stage="diagnose", now=NOW,
                               rows=self.rows + ticket(self.hound["id"], result=None, start_hours_ago=-3, now=NOW))
        self.assertEqual(ctx.exception.code, "open_tickets")

    def test_the_page_never_receives_the_cost_or_the_routers_reason(self):
        shown = coach.Coach(router=real_router(self.tmp.name, FakeAdapter(good_reply)))
        b = training.read_step(self.resolve(self.hound["id"]), self.owner.id, shown, stage="assess", now=NOW, rows=self.rows)
        text = json.dumps(b)
        self.assertNotIn("cost_usd", text)
        self.assertNotIn("monthly paid cap", text)
        self.assertNotIn("bet_id", text)


class TheCardNeverPromises(Setup):
    def test_no_sentence_the_coach_adds_says_the_new_version_will_be_better(self):
        shown = coach.Coach(router=real_router(self.tmp.name, FakeAdapter(good_reply)))
        out = self.train(self.hound, self.rows, coach=shown)
        words = re.compile(r"\b(will|improve\w*|better|edge|profit\w*|guarantee\w*|should win)\b", re.I)
        texts = [out["coach"].get("summary") or ""] + [r["text"] for r in out["coach"]["reasons"]] + [c["line"] for r in out["coach"]["reasons"] for c in r["cited"]]
        for t in texts:
            self.assertIsNone(words.search(t), t)
        self.assertNotRegex(json.dumps(out["coach"]), r"\bdogs?\b")

    def test_a_light_adjustment_never_asks_the_model(self):
        hound = self.dog("Young Pup")
        adapter = FakeAdapter(good_reply)
        shown = coach.Coach(router=real_router(self.tmp.name, adapter))
        out = self.train(hound, rows_for(hound["id"], [(3, dict(result="LOSS"))]), coach=shown)
        self.assertEqual((out["mode"], adapter.calls), ("light", []))
        self.assertEqual(out["coach"]["label"], "Coach's read (rules engine)")


if __name__ == "__main__":
    unittest.main()
