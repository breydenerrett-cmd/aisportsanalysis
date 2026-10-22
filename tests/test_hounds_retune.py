"""Retune from this chat, and the review every training now goes through (owner requests 2026-10-22).

THE STORY. In a hound's Ask chat the owner wrote "What rules would you change to find more relevant bets today? I don't like that
you won't take a single bet on anything today." Send to training could only narrow a rule. And in production a Gematria hound with no
settled bet was sent to training and came back with "Most bets a day 3 -> 2": a hound that places nothing was made to place less,
and the change was applied before the owner could say no. So:

  * Ask recognises a tuning request, answers with what the rule did on TODAY's board, and gives the OWNER (only) a Retune button.
  * The proposal comes from a closed menu that includes loosening, capped (price band to +400 and never near -200, books never
    below 2, bets a day never past 5); Claude Haiku maps the chat to at most three menu ids and must cite the line it answers.
  * EVERY training is proposal -> review -> apply. A proposal and a tweak write nothing; a veto changes nothing and does not count;
    only Apply makes a version, and the owner can untick changes first.
  * A hound that is not betting is never narrowed.

Everything runs without FastAPI and without a network: the router is a fake, the board is either a fake counting function or the
engine's own over fixture boards.
"""

from __future__ import annotations

import copy
import json
import re
import unittest
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds import user_spec, user_store
from src.hounds.interact import ask, retune, rites, training
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for, ticket, write_ledger
from tests._hounds_user_fixtures import spec_dict, standard_rows, utc
from tests.test_hounds_coach import FakeAnswer, FakeRouter
from tests.test_hounds_interact_ask import context
from tests.test_hounds_training import MIXED, refusal

BANNED = re.compile(r"\b(better|improve|improved|improves|fix|fixed|fixes|stronger|smarter|profit|profitable|edge|winning|will win|beat the|bet check|dogs?)\b", re.I)
OWNER_LINE = "What rules would you change to find more relevant bets today? I don't like that you won't take a single bet on anything today"


def board(spec) -> dict:
    """A fake of today's board that is a pure function of the spec: one candidate each time the long end of the band reaches +120 and
    +250, one per extra sport, one when only two books are needed. 60 games; the rest fail the price band."""
    rules = spec.get("rules") or [spec]
    high = max(r["price_max"] for r in rules)
    books = min(r["min_books"] for r in rules)
    sports = {s for r in rules for s in r["sports"]}
    cands = (high >= 120) + (high >= 250) + (len(sports) - 1) + (books <= 2)
    return {"games": 60, "candidates": cands, "with_candidate": cands, "failed": {"outside_price_band": 60 - cands}, "failed_total": 60 - cands}


def nothing_board(spec) -> dict:
    return {"games": 0, "candidates": 0, "with_candidate": 0, "failed": {}, "failed_total": 0}


def mapped(*items):
    """A Haiku answer: ``(cid, line, quote)`` items."""
    return FakeRouter(FakeAnswer(output={"items": [{"cid": c, "line": line, "quote": q} for c, line, q in items]}))


class Case(RitesCase):
    def idle(self, name="Idle Pup", **spec):
        """A hound with a narrow band that places nothing."""
        return self.dog(name, **{"price_min": 100, "price_max": 110, **spec})

    def review(self, hound, **kw):
        kw.setdefault("now", NOW)
        kw.setdefault("rows", [])
        kw.setdefault("board_fn", board)
        return training.review(self.resolve(hound["id"]), self.owner.id, **kw)

    def apply(self, hound, rows=None, **kw):
        kw.setdefault("env", {})
        kw.setdefault("background", False)
        return training.train(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[] if rows is None else rows, **kw)

    def spec_of(self, hound_id):
        return user_store.get_hound(hound_id)["spec"]

    def assertUntouched(self, hound):
        self.assertEqual(len(user_store.lineage(hound["id"])), 1, "no version was made")
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "running")
        self.assertEqual(user_store.list_events(root_id=hound["root_id"]), [], "no life event was written")
        self.assertEqual(user_store.trained_count(hound["root_id"]), 0, "it does not count as a training")


# ---------------------------------------------------------------------------------------------------------------------------
# 1. the intent
# ---------------------------------------------------------------------------------------------------------------------------

class IntentDetection(unittest.TestCase):
    TUNING = (OWNER_LINE, "you never take any bets", "too few bets today", "Why won't you take a single bet", "not enough action",
              "can you loosen up your rules", "be less picky", "what rules would you change", "retune yourself",
              "give yourself some advice", "too many bets, be more selective", "bet fewer games", "look at more sports",
              "add NBA to your sports", "only bet favourites", "only take underdogs", "avoid back to back games",
              "I don't like that you have no bets")
    NOT_TUNING = ("Why didn't you bet the Yankees?", "what did you bet today", "What would you bet right now?",
                  "how are you doing", "what are your rules", "why did you bet Boston", "what's a spread",
                  "what would you have done this week")

    def test_a_tuning_request_is_recognised(self):
        for text in self.TUNING:
            with self.subTest(text=text):
                self.assertIsNotNone(retune.detect(text))

    def test_an_ordinary_question_is_not(self):
        for text in self.NOT_TUNING:
            with self.subTest(text=text):
                self.assertIsNone(retune.detect(text))

    def test_the_owners_own_sentence_lands_on_retune_not_on_a_pick_question(self):
        self.assertEqual(ask.answer(OWNER_LINE, context())["intent"], "retune")

    def test_more_picks_alone_is_a_request_for_picks_not_a_complaint(self):
        for text in ("give me more picks for tonight", "what would you bet right now, more picks please"):
            self.assertNotEqual(ask.answer(text, context())["intent"], "retune", text)

    def test_a_team_named_is_a_question_about_that_game(self):
        out = ask.answer("why won't you take a single bet on Boston", context())
        self.assertNotEqual(out["intent"], "retune")

    def test_the_kinds_say_what_was_asked_for(self):
        self.assertIn("more", retune.kinds_in("I don't like that you won't take a single bet"))
        self.assertIn("fewer", retune.kinds_in("too many bets"))
        self.assertIn("sports", retune.kinds_in("look at more sports"))
        self.assertIn("favourites", retune.kinds_in("only favourites"))
        self.assertIn("rest", retune.kinds_in("avoid back to backs"))


class TheAskAnswer(unittest.TestCase):
    """Ask answers with the hound's own numbers, and only the owner is given the button."""

    def owner_ctx(self, **facts):
        base = {"eligible": True, "gate": "", "available": True, "games": 60, "candidates": 0, "failed": {"outside_price_band": 52, "rule_not_met": 8},
                "failed_total": 60, "ideas": [{"cid": "widen_band:up", "if_text": "widened my price band to +100 to +250", "candidates": 6, "gain": 6}],
                "menu_empty": False}
        base.update(facts)
        return context(is_owner=True, retune_fn=lambda question: base)

    def test_the_hound_answers_with_what_its_rule_did_on_todays_board(self):
        out = ask.answer(OWNER_LINE, self.owner_ctx())
        self.assertEqual(out["intent"], "retune")
        self.assertIn("Today I checked 60 games and 52 failed my price band.", out["answer"])
        self.assertIn("If I widened my price band to +100 to +250 I'd have 6 candidates.", out["answer"])
        self.assertIn("Nothing changes until you confirm.", out["answer"])

    def test_the_owner_gets_a_retune_button(self):
        out = ask.answer(OWNER_LINE, self.owner_ctx())
        self.assertEqual(out["retune"], {"offer": True, "label": "Retune me", "enabled": True, "note": ""})

    def test_a_hound_that_cannot_be_retuned_now_says_why_and_the_button_is_off(self):
        out = ask.answer(OWNER_LINE, self.owner_ctx(eligible=False, gate="Idle Pup has 1 open ticket. Wait until its open tickets settle."))
        self.assertFalse(out["retune"]["enabled"])
        self.assertIn("1 open ticket", out["retune"]["note"])
        self.assertIn("I cannot be retuned right now", out["answer"])

    def test_a_visitor_gets_the_answer_but_never_the_button(self):
        for ctx in (context(is_owner=False), context(is_owner=False, retune_fn=lambda q: {"eligible": True})):
            out = ask.answer(OWNER_LINE, ctx)
            self.assertEqual(out["intent"], "retune")
            self.assertIsNone(out["retune"], "a visitor is never offered Retune")
            self.assertIn("Only my owner can change my rules", out["answer"])

    def test_a_house_hound_has_nothing_to_retune(self):
        out = ask.answer(OWNER_LINE, context(kind="house", is_owner=True, retune_fn=lambda q: {"eligible": True}))
        self.assertIsNone(out["retune"])

    def test_the_owner_can_ask_but_a_board_that_cannot_be_read_is_said_plainly(self):
        out = ask.answer(OWNER_LINE, self.owner_ctx(available=False))
        self.assertIn("I cannot read today's board just now", out["answer"])

    def test_nothing_in_the_answer_promises_a_result_or_says_dog(self):
        for ctx in (self.owner_ctx(), self.owner_ctx(available=False), self.owner_ctx(eligible=False, gate="Wait.")):
            self.assertIsNone(BANNED.search(ask.answer(OWNER_LINE, ctx)["answer"]), ask.answer(OWNER_LINE, ctx)["answer"])

    def test_the_lines_come_from_real_counts(self):
        hound_spec = user_spec.validate_spec(spec_dict(price_min=100, price_max=110))
        dog = mock.Mock(spec=["spec"])
        dog.spec = hound_spec
        diag = retune.self_diagnosis(dog, board, eligible=True)
        self.assertEqual((diag["games"], diag["candidates"]), (60, 0))
        self.assertEqual([i["cid"] for i in diag["ideas"]][:1], ["widen_band:up"], "the biggest gain on today's board first")
        lines = retune.compose_lines(diag)
        self.assertEqual(lines[0], "Today I checked 60 games and 60 failed my price band. None cleared my rule.")
        self.assertIn("If I widened my price band to +100 to +120 I'd have 1 candidate.", lines[1])


# ---------------------------------------------------------------------------------------------------------------------------
# 2. the menu and its caps
# ---------------------------------------------------------------------------------------------------------------------------

def v1(**over):
    return user_spec.validate_spec(spec_dict(**over))


def v2(**over):
    return user_spec.validate_spec({**user_spec.upgrade_v1(v1(**over)), "name": "Dog Days"})


def band_of(spec):
    rules = spec.get("rules") or [spec]
    return min(r["price_min"] for r in rules), max(r["price_max"] for r in rules)


class TheMenuStaysInsideItsCaps(unittest.TestCase):
    def walk(self, spec, cid_prefix, steps=40):
        """Apply the entry with this cid over and over until it stops being offered."""
        seen = [spec]
        for _ in range(steps):
            entry = next((e for e in retune.loosening_menu(spec) if e["cid"].startswith(cid_prefix)), None)
            if entry is None:
                return seen
            spec = training._validated(entry["build"](copy.deepcopy(spec))["spec"])
            self.assertIsNotNone(spec)
            seen.append(spec)
        self.fail("the entry was never exhausted")

    def test_the_band_widens_to_plus_400_and_stops(self):
        for make in (v1, v2):
            walked = self.walk(make(price_min=100, price_max=110), "widen_band:up")
            self.assertEqual(band_of(walked[-1])[1], 400)
            self.assertTrue(all(band_of(s)[1] <= 400 for s in walked))

    def test_the_short_end_never_gets_near_minus_200(self):
        for make in (v1, v2):
            walked = self.walk(make(price_min=-110, price_max=150), "widen_band:down")
            self.assertEqual(band_of(walked[-1])[0], -190)
            for s in walked:
                self.assertGreater(band_of(s)[0], user_spec.MAX_FAVOURITE_PRICE)
                self.assertFalse(user_spec.beyond_cap(band_of(s)[0]))

    def test_minus_200_or_worse_can_never_enter_by_any_entry_on_any_spec(self):
        specs = [v1(), v1(sports=["MLB", "NFL"], markets=["moneyline", "spread"], price_min=-190, price_max=300),
                 v1(side_rule="favourite", price_min=-190, price_max=-110), v2(), v2(price_min=-190, price_max=-120)]
        for spec in specs:
            for entry in retune.full_menu(spec):
                made = entry["build"](copy.deepcopy(spec))
                self.assertIsNotNone(made, entry["cid"])
                valid = training._validated(made["spec"])
                self.assertIsNotNone(valid, entry["cid"])
                low, high = band_of(valid)
                self.assertFalse(user_spec.beyond_cap(low), f"{entry['cid']} reached {low}")
                self.assertLessEqual(high, 400 if band_of(spec)[1] <= 400 else band_of(spec)[1])

    def test_books_never_go_below_two(self):
        for make in (v1, v2):
            walked = self.walk(make(min_books=5), "lower_books")
            self.assertEqual([min(r["min_books"] for r in (s.get("rules") or [s])) for s in walked], [5, 4, 3, 2])
        self.assertFalse([e for e in retune.loosening_menu(v1(min_books=2)) if e["id"] == "lower_books"])
        self.assertFalse([e for e in retune.loosening_menu(v1(min_books=1)) if e["id"] == "lower_books"], "a hound already below two is not pushed lower")

    def test_bets_a_day_never_pass_five(self):
        walked = self.walk(v1(max_bets_per_day=3), "more_bets")
        self.assertEqual([s["max_bets_per_day"] for s in walked], [3, 4, 5])
        self.assertFalse([e for e in retune.loosening_menu(v1(max_bets_per_day=5)) if e["id"] == "more_bets"])

    def test_a_sport_or_market_is_added_only_where_the_rule_can_carry_it(self):
        cids = {e["cid"] for e in retune.loosening_menu(v1())}
        self.assertIn("add_sport:NFL", cids)
        self.assertNotIn("add_sport:MLB", cids, "already there")
        self.assertIn("add_market:spread", cids)
        # a player-prop rule is MLB only: the menu cannot add another sport to it
        prop = user_spec.validate_spec({**v2(), "rules": [{"label": "", "sports": ["MLB"], "markets": ["batter_hits"], "side": "over",
                                                            "price_min": 100, "price_max": 250, "line_min": None, "line_max": None,
                                                            "min_books": 2, "when": None}]})
        self.assertFalse([e for e in retune.loosening_menu(prop) if e["cid"].startswith("add_sport:")])

    def test_a_numeric_condition_relaxes_one_step_in_the_loosening_direction(self):
        rule = {"label": "", "sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": 100, "price_max": 250,
                "line_min": None, "line_max": None, "min_books": 3,
                "when": {"op": "all", "items": [{"id": "rest_days", "who": "pick", "cmp": "gte", "value": 3},
                                                {"id": "temperature", "cmp": "lte", "value": 70}]}}
        spec = user_spec.validate_spec({**v2(), "rules": [rule]})
        entries = {e["cid"]: e for e in retune.loosening_menu(spec)}
        rest, temp = entries["relax:rule0:rest_days:0"], entries["relax:rule0:temperature:0"]
        self.assertEqual((rest["text"], temp["text"]), ("Days of rest: 3 to 2", "Temperature: 70 to 75"))
        relaxed = training._validated(rest["build"](copy.deepcopy(spec))["spec"])
        self.assertEqual(relaxed["rules"][0]["when"]["items"][0]["value"], 2)
        self.assertEqual(spec["rules"][0]["when"]["items"][0]["value"], 3, "the original is not touched")

    def test_a_condition_already_at_its_limit_offers_no_relaxing(self):
        rule = {"label": "", "sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": 100, "price_max": 250,
                "line_min": None, "line_max": None, "min_books": 3,
                "when": {"op": "all", "items": [{"id": "rest_days", "who": "pick", "cmp": "gte", "value": 0}]}}
        spec = user_spec.validate_spec({**v2(), "rules": [rule]})
        self.assertFalse([e for e in retune.loosening_menu(spec) if e["id"] == "relax_condition"])

    def test_the_menu_holds_the_coachs_narrowing_changes_too(self):
        cids = {e["cid"] for e in retune.full_menu(v1(sports=["MLB", "NFL"]))}
        for expected in ("fewer_bets", "more_books:all", "drop_sport:NFL", "widen_band:up", "lower_books"):
            self.assertIn(expected, cids)
        self.assertEqual(len(cids), len(retune.full_menu(v1(sports=["MLB", "NFL"]))), "a cid appears once")

    def test_every_entry_is_valid_on_its_own_and_changes_the_rule(self):
        for spec in (v1(sports=["MLB", "NFL"], markets=["moneyline", "spread"]), v2()):
            for entry in retune.full_menu(spec):
                made = entry["build"](copy.deepcopy(spec))
                valid = training._validated(made["spec"])
                self.assertIsNotNone(valid, entry["cid"])
                self.assertNotEqual(user_spec.spec_hash(valid), user_spec.spec_hash(spec), entry["cid"])


# ---------------------------------------------------------------------------------------------------------------------------
# 3. the mapping: Haiku picks from the menu and cites the chat
# ---------------------------------------------------------------------------------------------------------------------------

class TheMapping(unittest.TestCase):
    def setUp(self):
        self.spec = v1(price_min=100, price_max=110)
        self.entries = retune.full_menu(self.spec)
        self.lines = [OWNER_LINE]
        self.counted = retune.whatif(self.spec, self.entries, board)

    def map(self, router, lines=None):
        return retune.map_chat(lines or self.lines, self.entries, self.counted, router=router, env={})

    def test_a_pick_from_the_menu_with_a_real_quote_is_kept_and_the_line_is_the_owners_not_the_models(self):
        out = self.map(mapped(("widen_band:up", 0, "won't take a single bet")))
        self.assertEqual((out["source"], out["status"], out["label"]), ("ai", "ok", "AI mapping"))
        (item,) = out["items"]
        self.assertEqual((item["cid"], item["line"], item["text"]), ("widen_band:up", 0, OWNER_LINE))

    def test_a_pick_that_is_not_on_the_menu_is_dropped(self):
        out = self.map(mapped(("set_band:+900", 0, "single bet"), ("widen_band:up", 0, "single bet")))
        self.assertEqual([i["cid"] for i in out["items"]], ["widen_band:up"])
        self.assertIn("not on the menu", [d["why"] for d in out["dropped"]])

    def test_a_citation_is_required_a_missing_line_or_a_quote_not_in_the_line_is_dropped(self):
        router = FakeRouter(FakeAnswer(output={"items": [
            {"cid": "widen_band:up", "quote": "single bet"},                              # no line
            {"cid": "lower_books", "line": 0, "quote": "I never said this"},               # the quote is not in the line
            {"cid": "add_sport:NFL", "line": 5, "quote": "single bet"},                    # no such line
            {"cid": "more_bets", "line": True, "quote": "single bet"}]}))                  # a boolean is not a line number
        out = self.map(router)
        self.assertEqual(out["source"], "rules", "nothing that survived the vet came from the model, so the rules engine maps")
        self.assertEqual(len(out["dropped"]), 4)
        for item in out["items"]:
            self.assertEqual(item["text"], OWNER_LINE, "even the rules engine cites a real line")

    def test_at_most_three_picks_whatever_the_model_says(self):
        cids = [e["cid"] for e in self.entries if e["direction"] == "loosen"][:6]
        out = self.map(mapped(*[(c, 0, "single bet") for c in cids]))
        self.assertEqual(len(out["items"]), 3)

    def test_a_repeated_pick_counts_once(self):
        out = self.map(mapped(("lower_books", 0, "single bet"), ("lower_books", 0, "single bet")))
        self.assertEqual([i["cid"] for i in out["items"]], ["lower_books"])

    def test_a_capped_router_falls_back_to_the_rules_engine_which_still_cites(self):
        out = self.map(FakeRouter(FakeAnswer(ok=False, reason="no answer (monthly paid cap reached)", cost=0.0)))
        self.assertEqual((out["source"], out["status"], out["label"]), ("rules", "capped", "Rules engine mapping"))
        self.assertTrue(out["items"])
        self.assertTrue(all(i["cid"] in {e["cid"] for e in self.entries} and i["text"] == OWNER_LINE for i in out["items"]))

    def test_a_router_that_raises_does_not_break_a_retune(self):
        out = self.map(FakeRouter(raises=RuntimeError("sk-ant-secret exploded")))
        self.assertEqual((out["source"], out["status"]), ("rules", "down"))
        self.assertNotIn("sk-ant", json.dumps(out))

    def test_with_no_key_and_no_router_the_rules_engine_maps(self):
        out = retune.map_chat(self.lines, self.entries, self.counted, router=None, env={})
        self.assertEqual((out["source"], out["status"]), ("rules", "off"))
        self.assertTrue(out["items"])

    def test_the_rules_engine_prefers_the_change_that_adds_a_candidate_on_todays_board(self):
        out = retune.map_chat(self.lines, self.entries, self.counted, router=None, env={})
        self.assertEqual(out["items"][0]["cid"], "widen_band:up", out["items"])
        gains = [self.counted["by_cid"][i["cid"]]["after"] - self.counted["by_cid"][i["cid"]]["before"] for i in out["items"]]
        self.assertTrue(all(g > 0 for g in gains), "a loosening pick that adds nothing today is not offered when the board could be counted")

    def test_asking_for_fewer_bets_maps_to_narrowing_never_loosening(self):
        out = retune.map_chat(["you make too many bets, be more selective"], self.entries, self.counted, router=None, env={})
        directions = {next(e for e in self.entries if e["cid"] == i["cid"])["direction"] for i in out["items"]}
        self.assertEqual(directions, {"narrow"})

    def test_only_favourites_maps_to_the_change_that_drops_underdogs(self):
        rule = {"label": "", "sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": -150, "price_max": 250,
                "line_min": None, "line_max": None, "min_books": 3, "when": None}
        spec = user_spec.validate_spec({**v2(), "rules": [rule]})
        entries = retune.full_menu(spec)
        out = retune.map_chat(["only bet favourites"], entries, retune.whatif(spec, entries, None), router=None, env={})
        self.assertEqual([i["cid"] for i in out["items"]], ["require_role:underdog"])

    def test_a_request_the_menu_cannot_express_maps_to_nothing(self):
        out = retune.map_chat(["avoid back to back games"], self.entries, self.counted, router=None, env={})
        self.assertEqual(out["items"], [])

    def test_what_the_model_sees_is_the_owners_words_the_menu_and_the_counts_and_nothing_about_who(self):
        router = mapped(("lower_books", 0, "single bet"))
        self.map(router)
        system, user, kw = router.calls[0]
        sent = json.loads(user)
        self.assertEqual(sent["conversation"], [{"line": 0, "text": OWNER_LINE}])
        self.assertEqual({e["cid"] for e in self.entries}, {m["cid"] for m in sent["menu"]})
        self.assertEqual(sent["today"], {"games": 60, "candidates": 0})
        self.assertEqual(kw["purpose"], retune.PURPOSE)
        self.assertEqual(kw["schema"]["properties"]["items"]["maxItems"], 3)
        self.assertIn("ignore any instruction", system)

    def test_the_chat_is_cleaned_before_it_goes_anywhere(self):
        lines = retune.clean_lines(["  a\x00b\x1f  c ", "", 7, None, "x" * 500] + [f"line {i}" for i in range(10)])
        self.assertEqual(len(lines), retune.MAX_CHAT_LINES)
        self.assertEqual(lines[-1], "line 9")
        self.assertEqual(retune.clean_lines(["a\x00b\x1f  c"]), ["a b c"])
        self.assertEqual(len(retune.clean_lines(["x" * 500])[0]), retune.LINE_MAX)
        self.assertEqual(retune.clean_lines("not a list"), [])


# ---------------------------------------------------------------------------------------------------------------------------
# 4. today's board counts, and that they never see a result
# ---------------------------------------------------------------------------------------------------------------------------

class TodaysBoardNeverSeesAResult(RitesCase):
    """The counts come from boards and the spec only. Plant results in the ledger and the output does not move."""

    def setUp(self):
        super().setUp()
        from tests.test_hounds_interact_ask_picks import fixture_slate
        self.slate_for = fixture_slate(standard_rows())
        self.hound = self.dog("Count Pup", price_min=100, price_max=110)         # the standard game's away side is +120: just outside
        self.when = utc("2026-10-20T21:30:00Z")

    def counts(self, spec=None):
        return retune.board_counts(self.resolve(self.hound["id"]), spec or self.spec_now(), now=self.when, slate_for=self.slate_for)

    def spec_now(self):
        return user_store.get_hound(self.hound["id"])["spec"]

    def test_the_real_engine_counts_candidates_on_the_fixture_board(self):
        base = self.counts()
        self.assertEqual((base["games"], base["candidates"], base["failed"]), (1, 0, {"outside_price_band": 1}))
        wider = training._validated(retune.change_widen_band(copy.deepcopy(self.spec_now()), "up")["spec"])
        self.assertEqual(wider["price_max"], 120)
        self.assertEqual(self.counts(wider)["candidates"], 1, "the +120 underdog now qualifies")

    def test_planted_results_change_nothing(self):
        before = (self.counts(), retune.whatif(self.spec_now(), retune.loosening_menu(self.spec_now()), lambda s: self.counts(s)))
        hid = self.hound["id"]
        for result in ("WIN", "LOSS"):
            write_ledger(self.ledger, rows_for(hid, [(8, dict(result=result, price=120))]))
            with self.subTest(planted=result):
                after = (self.counts(), retune.whatif(self.spec_now(), retune.loosening_menu(self.spec_now()), lambda s: self.counts(s)))
                self.assertEqual(before, after)

    def test_the_count_never_opens_the_ledger_at_all(self):
        write_ledger(self.ledger, rows_for(self.hound["id"], [(3, dict(result="WIN"))]))
        with mock.patch.object(eng, "read_ledger", side_effect=AssertionError("the count read the ledger")):
            self.assertEqual(self.counts()["games"], 1)

    def test_a_proposal_card_is_identical_whatever_the_settled_results_were(self):
        wins = [(6, dict(result="WIN", side="away", price=180))]
        losses = [(6, dict(result="LOSS", side="away", price=180))]
        cards = []
        for plan in (wins, losses):
            hound = self.dog(f"Twin {plan[0][1]['result']}", price_min=100, price_max=110)
            card = training.review(self.resolve(hound["id"]), self.owner.id, None, origin="chat", chat=[OWNER_LINE], now=NOW,
                                   rows=rows_for(hound["id"], plan), board_fn=lambda s, h=hound: retune.board_counts(
                                       self.resolve(h["id"]), s, now=self.when, slate_for=self.slate_for),
                                   router=None, env={})
            cards.append({k: card[k] for k in ("picks", "today", "nothing")} | {"cids": [c["cid"] for c in card["changes"]]})
        self.assertEqual(cards[0], cards[1])
        self.assertEqual(cards[0]["today"]["before"], 0)

    def test_a_board_that_cannot_be_read_is_none_never_a_guess(self):
        with mock.patch("src.hounds.interact.ask_eval.earlier_user", side_effect=RuntimeError("no store")):
            self.assertIsNone(self.counts())
        card = training.review(self.resolve(self.hound["id"]), self.owner.id, None, origin="chat", chat=[OWNER_LINE], now=NOW, rows=[],
                               board_fn=lambda s: None, router=None, env={})
        self.assertIsNone(card["today"])


# ---------------------------------------------------------------------------------------------------------------------------
# 5. proposal -> review -> apply
# ---------------------------------------------------------------------------------------------------------------------------

class AProposalWritesNothing(Case):
    def test_a_default_proposal_a_retune_proposal_and_a_tweak_leave_everything_untouched(self):
        hound = self.idle()
        before = self.spec_of(hound["id"])
        self.review(hound)
        self.review(hound, origin="chat", chat=[OWNER_LINE], router=None, env={})
        self.review(hound, tweak="look at more sports", router=None, env={})
        self.assertEqual(self.spec_of(hound["id"]), before)
        self.assertUntouched(hound)

    def test_the_card_is_the_whole_proposal_each_change_old_to_new_with_its_reason(self):
        hound = self.idle()
        card = self.review(hound)
        self.assertEqual((card["origin"], card["mode"], card["settled"], card["nothing"]), ("training", "loosen", 0, False))
        self.assertEqual(card["picks"], [c["cid"] for c in card["changes"]])
        for c in card["changes"]:
            self.assertTrue(c["old_text"] and c["new_text"] and c["why"], c)
            self.assertEqual(c["direction"], "loosen")
        self.assertEqual(card["today"]["before"], 0)
        self.assertIn("On today's board it would have", card["today"]["text"])
        self.assertEqual(card["tweak"], {"used": 0, "left": 3, "max": 3})
        self.assertIn("makes no promise about results", card["honesty"])

    def test_the_refusals_apply_to_a_proposal_too(self):
        hound = self.idle()
        rows = rows_for(hound["id"], MIXED) + ticket(hound["id"], result=None, start_hours_ago=-3, now=NOW)
        self.assertEqual(refusal(self, training.review, self.resolve(hound["id"]), self.owner.id, now=NOW, rows=rows).code, "open_tickets")
        self.assertEqual(refusal(self, training.review, self.resolve(hound["id"]), self.other.id, now=NOW, rows=[]).code, "not_found")


class AVetoChangesNothing(Case):
    def test_a_veto_leaves_the_spec_the_version_and_the_limit_untouched(self):
        hound = self.idle()
        before = self.spec_of(hound["id"])
        self.review(hound)
        out = training.veto(self.resolve(hound["id"]), self.owner.id)
        self.assertEqual((out["vetoed"], out["changed"], out["counts_toward_limit"]), (True, False, False))
        self.assertIn("does not count as a training", out["headline"])
        self.assertEqual(self.spec_of(hound["id"]), before)
        self.assertUntouched(hound)

    def test_a_veto_does_not_use_up_the_training_limit(self):
        hound = self.dog("Vet Pup", sports=["MLB", "NFL"])
        first = self.apply(hound, rows_for(hound["id"], MIXED))
        v2_ = user_store.get_hound(first["new"]["id"])
        too_soon = refusal(self, self.apply, v2_, [])
        self.assertEqual(too_soon.code, "training_too_soon")
        training.veto(self.resolve(v2_["id"]), self.owner.id)
        self.assertEqual(refusal(self, self.apply, v2_, []).extra["needs"], too_soon.extra["needs"], "the wait is exactly what it was")
        self.assertEqual(user_store.trained_count(v2_["root_id"]), 1)
        # and a veto on a version that CAN train does not stop it training afterwards
        fresh = self.idle("Fresh Pup")
        training.veto(self.resolve(fresh["id"]), self.owner.id)
        self.assertEqual(self.apply(fresh)["new"]["version_no"], 2)

    def test_someone_elses_hound_cannot_be_vetoed(self):
        hound = self.idle()
        self.assertEqual(refusal(self, training.veto, self.resolve(hound["id"]), self.other.id).code, "not_found")


class OnlyApplyMakesAVersion(Case):
    def test_apply_needs_the_confirm(self):
        hound = self.idle()
        exc = refusal(self, training.train, self.resolve(hound["id"]), self.owner.id, confirmed=False, now=NOW, rows=[], picks=["lower_books"])
        self.assertEqual((exc.code, exc.status), ("confirm_required", 400))
        self.assertUntouched(hound)

    def test_apply_with_the_picks_makes_exactly_those_changes_and_one_version(self):
        hound = self.idle()
        out = self.apply(hound, picks=["lower_books"])
        self.assertEqual([c["cid"] for c in out["changes"]], ["lower_books"])
        self.assertEqual(out["new"]["version_no"], 2)
        spec = self.spec_of(out["new"]["id"])
        self.assertEqual((spec["min_books"], spec["price_max"]), (2, 110), "only the ticked change happened")
        old = user_store.get_hound(hound["id"])
        self.assertEqual((old["status"], old["spec"]["min_books"]), ("retired", 3), "the old version is frozen as it was")
        self.assertEqual(user_store.trained_count(hound["root_id"]), 1)

    def test_unticking_works_apply_what_is_left_ticked(self):
        hound = self.idle()
        card = self.review(hound)
        self.assertGreaterEqual(len(card["picks"]), 2)
        kept = card["picks"][:1]                                    # the owner unticked the rest
        out = self.apply(hound, picks=kept)
        self.assertEqual([c["cid"] for c in out["changes"]], kept)

    def test_unticking_everything_is_not_an_apply(self):
        hound = self.idle()
        exc = refusal(self, self.apply, hound, picks=[])
        self.assertEqual((exc.code, exc.status), ("no_changes_selected", 400))
        self.assertUntouched(hound)

    def test_a_pick_that_is_not_on_the_menu_refuses_the_whole_apply(self):
        hound = self.idle()
        for bad in (["set_band:+900"], ["lower_books", "price_max:5000"], ["../../etc"]):
            exc = refusal(self, self.apply, hound, picks=bad)
            self.assertEqual((exc.code, exc.status), ("unknown_change", 422), bad)
        self.assertUntouched(hound)

    def test_more_than_three_picks_is_refused(self):
        hound = self.idle()
        exc = refusal(self, self.apply, hound, picks=["widen_band:up", "lower_books", "add_market:spread", "add_sport:NFL"])
        self.assertEqual(exc.code, "too_many_changes")

    def test_the_picks_are_checked_against_the_rule_as_it_stands_not_as_it_was_shown(self):
        hound = self.idle(price_max=400)
        exc = refusal(self, self.apply, hound, picks=["widen_band:up"])
        self.assertEqual(exc.code, "unknown_change", "+400 is the cap: that rung is not on the menu any more")


class ATweakStaysInsideTheMenu(Case):
    def test_a_tweak_is_mapped_to_the_menu_cites_what_the_owner_said_and_writes_nothing(self):
        hound = self.idle()
        router = mapped(("add_market:spread", 0, "run line"))
        card = self.review(hound, tweak="also look at the run line", router=router, env={})
        self.assertEqual([c["cid"] for c in card["changes"]], ["add_market:spread"])
        self.assertEqual(card["changes"][0]["cite"], {"line": 0, "text": "also look at the run line", "quote": "run line"})
        self.assertEqual(card["tweak"], {"used": 1, "left": 2, "max": 3})
        self.assertEqual(card["mapper"], {"source": "ai", "label": "AI mapping", "status": "ok"})
        self.assertUntouched(hound)

    def test_the_tweak_includes_the_chat_before_it_when_it_came_from_one(self):
        hound = self.idle()
        router = mapped(("lower_books", 1, "fewer books"))
        self.review(hound, origin="chat", chat=[OWNER_LINE], tweak="fewer books please", router=router, env={})
        sent = json.loads(router.calls[0][1])
        self.assertEqual([c["text"] for c in sent["conversation"]], [OWNER_LINE, "fewer books please"])

    def test_nothing_outside_the_menu_or_the_caps_ever_comes_back(self):
        hound = self.idle(price_max=300)
        menu = {e["cid"]: e for e in retune.full_menu(self.spec_of(hound["id"]))}
        router = mapped(("price_max:900", 0, "wider"), ("widen_band:up", 0, "wider"), ("widen_band:up", 0, "wider"))
        card = self.review(hound, tweak="make the band much wider than that", router=router, env={})
        self.assertTrue(all(c["cid"] in menu for c in card["changes"]))
        applied = self.apply(hound, picks=card["picks"])
        self.assertLessEqual(self.spec_of(applied["new"]["id"])["price_max"], 400)

    def test_a_tweak_the_menu_cannot_express_says_so_and_changes_nothing(self):
        hound = self.idle()
        card = self.review(hound, tweak="avoid back to back games", router=None, env={})
        self.assertTrue(card["nothing"])
        self.assertIn("could not turn that into a change I am allowed to make", card["message"])
        self.assertUntouched(hound)

    def test_three_rounds_and_no_more(self):
        hound = self.idle()
        for n in range(3):
            card = self.review(hound, tweak=f"round {n} look at more sports", router=None, env={})
            self.assertEqual(card["tweak"]["used"], n + 1)
        exc = refusal(self, self.review, hound, tweak="one more", router=None, env={})
        self.assertEqual((exc.code, exc.status), ("tweak_limit", 409))
        self.assertEqual(exc.extra["tweak"], {"used": 3, "left": 0, "max": 3})
        self.assertUntouched(hound)

    def test_the_round_the_page_reports_counts_even_after_a_restart(self):
        hound = self.idle()
        exc = refusal(self, self.review, hound, tweak="more sports", round_no=3, router=None, env={})
        self.assertEqual(exc.code, "tweak_limit")

    def test_a_veto_starts_the_rounds_again_and_an_empty_tweak_is_refused(self):
        hound = self.idle()
        self.review(hound, tweak="more sports", router=None, env={})
        training.veto(self.resolve(hound["id"]), self.owner.id)
        self.assertEqual(self.review(hound, tweak="more sports", router=None, env={})["tweak"]["used"], 1)
        self.assertEqual(refusal(self, self.review, hound, tweak="  \x00 ", router=None, env={}).code, "tweak_empty")

    def test_an_edited_rule_has_its_own_rounds(self):
        hound = self.idle()
        for _ in range(3):
            self.review(hound, tweak="more sports", router=None, env={})
        self.assertEqual(training.tweaks_used(hound["id"], self.spec_of(hound["id"])), 3)
        self.assertEqual(training.tweaks_used(hound["id"], {**self.spec_of(hound["id"]), "price_max": 120}), 0)


class AHoundThatIsNotBettingIsNeverNarrowed(Case):
    NARROWING = {"fewer_bets", "more_books", "drop_sport", "drop_market", "tighten_band", "drop_venue", "require_role"}

    def test_the_default_proposal_for_a_hound_with_no_settled_bet_only_ever_widens(self):
        for board_fn in (board, None):
            hound = self.idle(f"Idle {bool(board_fn)}", max_bets_per_day=3)
            card = self.review(hound, board_fn=board_fn)
            with self.subTest(board=bool(board_fn)):
                self.assertEqual(card["mode"], "loosen")
                self.assertTrue(card["changes"])
                self.assertTrue(all(c["direction"] == "loosen" for c in card["changes"]), card["changes"])
                self.assertFalse(self.NARROWING & {c["id"] for c in card["changes"]})
                self.assertNotIn("more_bets", {c["id"] for c in card["changes"]}, "it places nothing, so its daily limit is not what stops it")
                self.assertEqual(card["framing"], f"{card['name']} has not bet yet. Want it to look at more games?")

    def test_the_production_case_a_gematria_like_hound_is_not_sent_from_3_bets_a_day_to_2(self):
        hound = self.idle("Letters Pup", max_bets_per_day=3)
        out = self.apply(hound)
        self.assertEqual(self.spec_of(out["new"]["id"])["max_bets_per_day"], 3)

    def test_with_the_board_in_hand_only_changes_that_add_a_game_today_are_offered(self):
        hound = self.idle()
        seen = self.review(hound)
        for c in seen["changes"]:
            self.assertGreater(c["today"]["after"], c["today"]["before"], c)

    def test_when_nothing_would_add_a_game_the_card_says_so_and_no_version_can_be_made(self):
        hound = self.idle()
        card = self.review(hound, board_fn=nothing_board)
        self.assertTrue(card["nothing"])
        self.assertIn("nothing sensible to change", card["message"])
        self.assertEqual(card["picks"], [])
        exc = refusal(self, self.apply, hound, board_fn=nothing_board)
        self.assertEqual((exc.code, exc.status), ("nothing_to_change", 409))
        self.assertUntouched(hound)

    def test_a_hound_with_bets_is_still_coached_the_old_way(self):
        hound = self.dog("Busy Pup", sports=["MLB", "NFL"])
        card = self.review(hound, rows=rows_for(hound["id"], MIXED))
        self.assertEqual(card["mode"], "analysed")
        self.assertTrue(all(c["direction"] == "narrow" for c in card["changes"]))
        self.assertIsNone(card["framing"])


class ARetuneFromChat(Case):
    def test_it_is_a_training_with_a_lineage_marker_the_leaderboard_can_read(self):
        hound = self.idle()
        card = self.review(hound, origin="chat", chat=[OWNER_LINE], router=mapped(("widen_band:up", 0, "single bet")), env={})
        out = self.apply(hound, picks=card["picks"], origin="chat")
        self.assertEqual((out["mode"], out["label"], out["origin"], out["lineage"]), ("retune", "Retuned", "owner_retune_chat", "owner retune (from chat)"))
        new = user_store.get_hound(out["new"]["id"])
        self.assertEqual((new["version_no"], new["origin"], new["coached_from"], new["status"]), (2, "owner_retune_chat", hound["id"], "running"))
        old = user_store.get_hound(hound["id"])
        self.assertEqual(old["status"], "retired")
        self.assertIn("owner retune (from chat)", old["retire_reason"])
        (event,) = user_store.list_events(root_id=hound["root_id"])
        self.assertEqual((event["payload"]["origin"], event["payload"]["mode"], event["payload"]["owner_chosen"]), ("owner_retune_chat", "retune", True))
        self.assertEqual(self.spec_of(out["new"]["id"])["price_max"], 120)

    def test_an_ordinary_training_and_an_edit_carry_no_marker(self):
        hound = self.dog("Plain Pup", sports=["MLB", "NFL"])
        out = self.apply(hound, rows_for(hound["id"], MIXED))
        self.assertIsNone(user_store.get_hound(out["new"]["id"])["origin"])
        self.assertIsNone(out["lineage"])
        edited = user_store.create_version(out["new"]["id"], {**self.spec_of(out["new"]["id"]), "max_bets_per_day": 1}, actor="owner", reason="edit")
        self.assertIsNone(edited["origin"])

    def test_it_counts_as_a_training_and_the_limits_hold(self):
        hound = self.idle()
        first = self.apply(hound, picks=["lower_books"], origin="chat")
        again = user_store.get_hound(first["new"]["id"])
        exc = refusal(self, self.apply, again, picks=["widen_band:up"], origin="chat")
        self.assertEqual((exc.code, exc.status, exc.extra["needs"]), ("training_too_soon", 409, 5))
        self.assertEqual(refusal(self, self.review, again, origin="chat", chat=[OWNER_LINE], router=None, env={}).code, "training_too_soon")
        rows = rows_for(again["id"], [(5, dict(result="LOSS"))])
        self.assertEqual(self.apply(again, rows, picks=["widen_band:up"], origin="chat")["new"]["version_no"], 3)
        self.assertEqual(user_store.trained_count(hound["root_id"]), 2)

    def test_an_open_ticket_blocks_a_retune_like_any_training(self):
        hound = self.idle()
        rows = ticket(hound["id"], result=None, start_hours_ago=-3, now=NOW)
        self.assertEqual(refusal(self, self.apply, hound, rows, picks=["lower_books"], origin="chat").code, "open_tickets")
        self.assertUntouched(hound)

    def test_someone_elses_hound_and_a_house_hound_cannot_be_retuned(self):
        hound = self.idle()
        self.assertEqual(refusal(self, training.train, self.resolve(hound["id"]), self.other.id, confirmed=True, now=NOW, rows=[],
                                 picks=["lower_books"], origin="chat").code, "not_found")
        self.assertEqual(refusal(self, training.review, self.resolve("chalk_chihuahua"), self.owner.id, origin="chat", chat=[OWNER_LINE]).code,
                         "not_a_member_dog")

    def test_an_unknown_origin_is_refused(self):
        hound = self.idle()
        self.assertEqual(refusal(self, self.apply, hound, picks=["lower_books"], origin="telepathy").code, "bad_origin")

    def test_a_retune_can_narrow_when_the_owner_asked_for_that(self):
        hound = self.dog("Loud Pup", max_bets_per_day=4)
        card = self.review(hound, origin="chat", chat=["you make too many bets"], router=None, env={})
        self.assertTrue(card["changes"])
        self.assertTrue(all(c["direction"] == "narrow" for c in card["changes"]))
        out = self.apply(hound, picks=card["picks"], origin="chat")
        self.assertLess(self.spec_of(out["new"]["id"])["max_bets_per_day"], 4)

    def test_every_change_cites_the_line_it_answers(self):
        hound = self.idle()
        card = self.review(hound, origin="chat", chat=["hello there", OWNER_LINE], router=None, env={})
        self.assertTrue(card["changes"])
        for c in card["changes"]:
            self.assertEqual(c["cite"]["text"], OWNER_LINE)
            self.assertEqual(c["cite"]["line"], 1)


class TheWordsAreHonest(Case):
    def texts(self, card):
        yield card["honesty"]
        yield card["limit_note"]
        yield card["message"]
        yield card["framing"] or ""
        yield (card["today"] or {}).get("text", "")
        for c in card["changes"]:
            yield c["why"]
            yield c["label"]

    def test_nothing_promises_a_result_or_says_dog_or_bet_check(self):
        hound = self.idle()
        cards = [self.review(hound), self.review(hound, origin="chat", chat=[OWNER_LINE], router=None, env={}),
                 self.review(hound, tweak="avoid back to back games", router=None, env={})]
        for card in cards:
            for text in self.texts(card):
                self.assertIsNone(BANNED.search(text), text)
        out = self.apply(hound, picks=["lower_books"], origin="chat")
        for text in (out["headline"], out["guidance"]["text"], out["honesty"], out["change_sentence"], out["next_training"]):
            self.assertIsNone(BANNED.search(text), text)
        self.assertIn("makes no promise about results", out["guidance"]["text"])
        self.assertIn("starts now", out["guidance"]["text"])

    def test_the_card_says_what_it_changes_how_many_and_which_games_it_looks_at(self):
        card = self.review(self.idle())
        self.assertTrue(card["honesty"].startswith("This changes how many and which games it looks at."))
        self.assertTrue(card["paper_only"])


if __name__ == "__main__":
    unittest.main()
