"""The NFL prompt's pins and the NFL checker: what it keeps, what it strikes, and why.

Offline: the packet is built from the synthetic league (tests/nfl_analyst_fixtures.py), the answers
are written by hand against it, and nothing reaches a model or a network.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from src.analyst import analyst as A
from src.analyst import critic, ledger, nfl_analyst, nfl_packet
from tests import nfl_analyst_fixtures as F

# The sha256 of NFL_SYSTEM_PROMPT. A change to the prompt must change this AND NFL_PROMPT_VERSION in
# the same commit: every published row records both, and a row made under one prompt must not be
# readable as made under another.
PROMPT_SHA256 = "56df866129793f09c15b5173e407f324e300df8d6280955d2506470374898782"


class Env(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = F.make_store(Path(cls._tmp.name))
        cls.packet = F.build(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def output(self):
        return F.deep(F.good_output(self.packet))

    def call(self, out, slot):
        return next(c for c in out["calls"] if c["slot_id"] == slot)

    def verify(self, out):
        return nfl_analyst.verify(self.packet, out)

    def published(self, v, slot):
        return next(c for c in v.calls if c["slot_id"] == slot)

    def struck(self, v):
        return {s["slot_id"]: s["problems"] for s in v.struck}

    def spread_take(self, selection="BUF +3.5", verdict="TAKE_OTHER_SIDE"):
        """A spread TAKE on a given side, built to be valid in every respect but the one a test changes."""
        market = self.packet["markets"]["spread"]
        opt = next(o for o in market["options"] if o["selection"] == selection)
        price, book = opt["best"]["price"], opt["best"]["book"]
        from src.core import odds as odds_math
        fair = round(odds_math.american_to_probability(price) + 0.03, 4)
        pass_price = int(round(odds_math.probability_to_american(fair)))
        return {
            "slot_id": "spread", "market": "spread", "selection": selection, "verdict": verdict,
            "price": price, "book": book, "fair_estimate": fair, "confidence": "low",
            "reasons": [{"claim": "The books are split on this number.",
                         "evidence": [{"path": "markets.spread.context.books_on_this_number",
                                       "value": market["context"]["books_on_this_number"]}], "derived": []}],
            "pass_price": pass_price,
            "what_would_change_it": "A change at quarterback.",
            "case_against": {"claim": "The books' own number already makes this the other side's game.",
                             "evidence": [{"path": "markets.spread.lean", "value": market["lean"]}],
                             "derived": []},
        }

    def with_spread(self, call):
        out = self.output()
        out["calls"] = [call if c["slot_id"] == "spread" else c for c in out["calls"]]
        return out


class ThePrompt(Env):
    def test_the_version_and_the_hash_are_pinned_together(self):
        self.assertEqual(nfl_analyst.NFL_PROMPT_VERSION, "analyst_prompt_nfl_v1")
        digest = hashlib.sha256(nfl_analyst.NFL_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
        self.assertEqual(digest, PROMPT_SHA256,
                         "the NFL prompt changed: bump NFL_PROMPT_VERSION and re-pin this hash")

    def test_the_mlb_prompt_and_its_version_are_untouched(self):
        self.assertEqual(A.PROMPT_VERSION, "analyst_prompt_v5")
        self.assertNotIn("THE FOOTBALL", A.SYSTEM_PROMPT)
        self.assertNotEqual(nfl_analyst.prompt_hash(), ledger.prompt_hash())
        self.assertEqual(ledger.prompt_hash(nfl_analyst.NFL_SYSTEM_PROMPT), nfl_analyst.prompt_hash())

    def test_it_keeps_every_numbered_rule_of_the_mlb_v5_prompt(self):
        mlb = set(re.findall(r"^(\d+a?)\. ", A.SYSTEM_PROMPT, re.M))
        nfl = set(re.findall(r"^(\d+a?)\. ", nfl_analyst.NFL_SYSTEM_PROMPT, re.M))
        self.assertEqual(mlb, nfl)
        self.assertTrue({"13a", "14a", "3a"} <= nfl)

    def test_it_adds_the_football_rules_F1_to_F8(self):
        found = re.findall(r"^(F\d)\. ", nfl_analyst.NFL_SYSTEM_PROMPT, re.M)
        self.assertEqual(found, [f"F{i}" for i in range(1, 9)])

    def test_the_bans_the_cap_and_the_spread_and_total_rules_are_stated(self):
        p = nfl_analyst.NFL_SYSTEM_PROMPT
        for needle in ("Never write: lock, guaranteed, free money, sure thing, can't lose, +EV",
                       "Never TAKE any bet at a price of -200 or worse, in any market",
                       "never write \"repo\", \"repos\", \"repository\" or \"the repo model\"",
                       "never \"the packet\"", "A spread call names the side and the number",
                       "A total call names the number", "Never invent a key number",
                       "Do not recommend a stake size"):
            self.assertIn(needle, p)
        self.assertIn("land on 3, 7 and a few others", p)

    def test_it_speaks_football_not_baseball(self):
        p = nfl_analyst.NFL_SYSTEM_PROMPT.lower()
        for word in ("baseball", "pitcher", "inning", "first pitch", "lineup", "run line", "bullpen",
                     "starter's era", " mlb "):
            self.assertNotIn(word, p, word)

    def test_the_request_is_the_shared_one_with_the_nfl_prompt_and_the_mlb_schema(self):
        body = nfl_analyst.build_request(self.packet, F.CFG)
        self.assertEqual(body["system"], nfl_analyst.NFL_SYSTEM_PROMPT)
        self.assertEqual(body["output_config"]["format"]["schema"], A.MLB_RESPONSE_SCHEMA)
        self.assertEqual(body["model"], F.CFG["model"])
        for forbidden in ("temperature", "thinking", "top_p"):
            self.assertNotIn(forbidden, body)
        text = body["messages"][0]["content"]
        self.assertIn("moneyline, spread, total", text)
        self.assertEqual(json.loads(text.split("\n")[1])["game"]["away"], "BUF")

    def test_the_schema_has_the_same_call_shape_as_the_mlb_one(self):
        item = A.schema_for(self.packet)["properties"]["calls"]["items"]
        for key in ("slot_id", "market", "selection", "verdict", "price", "book", "fair_estimate",
                    "confidence", "reasons", "case_against", "what_would_change_it", "pass_price"):
            self.assertIn(key, item["properties"])


class WhatItKeeps(Env):
    def test_a_valid_answer_is_kept_whole(self):
        v = self.verify(self.output())
        self.assertEqual(v.struck, [], v.struck)
        self.assertEqual((v.summary_status, v.summary_problems), ("ok", []))
        self.assertEqual([c["verdict"] for c in v.calls], ["TAKE_OTHER_SIDE", "PASS", "PASS"])

    def test_a_valid_spread_take_is_kept(self):
        out = self.with_spread(self.spread_take("BUF +3.5", "TAKE_OTHER_SIDE"))
        lean = self.packet["markets"]["spread"]["lean"]
        if lean == "BUF +3.5":
            out = self.with_spread(self.spread_take("BUF +3.5", "TAKE"))
        v = self.verify(out)
        self.assertEqual(v.struck, [], v.struck)

    def test_a_sentence_may_name_the_quoted_spread_and_total_and_where_the_number_started(self):
        out = self.output()
        c = self.call(out, "total")
        c["reasons"][0]["claim"] = "The books hang the total at 47.5, so Over 47.5 and Under 47.5 are the two sides."
        c = self.call(out, "spread")
        c["reasons"][0]["claim"] = "BUF +3.5 and KC -3.5 are the two sides, and the Bills at +3.5 get the half point."
        self.assertEqual(self.verify(out).struck, [])

    def test_the_scoring_facts_can_be_talked_about(self):
        out = self.output()
        out["calls"][1]["reasons"][0]["claim"] = ("A field goal is 3 points and a touchdown with the extra point "
                                                  "is 7, so 3 and 7 are the key numbers.")
        self.assertEqual(self.verify(out).struck, [])

    def test_a_declared_calculation_in_points_is_recomputed_and_allowed(self):
        out = self.output()
        home = F.value(self.packet, "sections.home.values.form.last_3.points_for_per_game")
        away = F.value(self.packet, "sections.away.values.form.last_3.points_for_per_game")
        gap = round(home - away, 2)
        c = self.call(out, "total")
        c["reasons"][0] = {
            "claim": f"The home side outscored the road side by {gap:g} points a game over three games.",
            "evidence": [{"path": "sections.home.values.form.last_3.points_for_per_game", "value": home},
                         {"path": "sections.away.values.form.last_3.points_for_per_game", "value": away}],
            "derived": [{"value": gap, "unit": "points", "op": "difference", "note": "home minus away",
                         "inputs": ["sections.home.values.form.last_3.points_for_per_game",
                                    "sections.away.values.form.last_3.points_for_per_game"]}]}
        v = self.verify(out)
        self.assertEqual(v.struck, [], v.struck)
        kept = self.published(v, "total")["reasons"][0]
        self.assertEqual(kept["derived"][0]["value"], gap)
        self.assertEqual(kept["derived"][0]["unit"], "points")
        # the same sentence with a wrong declared value is struck
        bad = F.deep(out)
        bad_reason = self.call(bad, "total")["reasons"][0]
        bad_reason["derived"][0]["value"] = gap + 5
        bad_reason["claim"] = bad_reason["claim"].replace(f"{gap:g}", f"{gap + 5:g}")
        self.assertIn("total", self.struck(self.verify(bad)))


class WhatItStrikes(Env):
    def test_a_spread_selection_that_is_not_a_quoted_option_is_struck_and_the_line_says_so(self):
        call = self.spread_take("BUF +3.5", "TAKE_OTHER_SIDE")
        call["selection"] = "BUF +4"
        v = self.verify(self.with_spread(call))
        problems = self.struck(v)["spread"]
        self.assertTrue(any("is not one of" in p for p in problems), problems)
        self.assertTrue(any("is not a quoted option" in p and "BUF +3.5" in p for p in problems), problems)
        self.assertEqual(self.published(v, "spread")["verdict"], "PASS")
        self.assertEqual(self.published(v, "spread")["verification"]["status"], critic.UNVERIFIED)

    def test_a_reason_that_names_a_spread_number_nobody_quoted_is_struck_even_when_that_digit_is_in_the_data(self):
        self.assertIn(4, [int(n) for n in nfl_packet.base.numbers_in_packet(self.packet) if float(n) == int(n)],
                      "the test needs a 4 somewhere in the packet, or the generic check would catch it")
        out = self.output()
        self.call(out, "spread")["reasons"][0]["claim"] = "BUF +4 is the number the books should have hung."
        v = self.verify(out)
        problems = self.struck(v)["spread"]
        self.assertTrue(any("names BUF +4" in p and "BUF" in p and "+3.5" in p for p in problems), problems)

    def test_a_nickname_next_to_the_wrong_number_is_struck_and_the_other_clubs_number_is_not_borrowed(self):
        out = self.output()
        self.call(out, "spread")["reasons"][0]["claim"] = "The Chiefs -3 is a fine number."
        self.assertIn("spread", self.struck(self.verify(out)))
        out = self.output()
        self.call(out, "spread")["reasons"][0]["claim"] = "The Chiefs +3.5 is a fine number."     # BUF's number, not KC's
        self.assertIn("spread", self.struck(self.verify(out)))

    def test_a_total_number_nobody_quoted_is_struck(self):
        out = self.output()
        self.call(out, "total")["reasons"][0]["claim"] = "The Over 48 looks too high."
        problems = self.struck(self.verify(out))["total"]
        self.assertTrue(any("names Over 48" in p and "47.5" in p for p in problems), problems)

    def test_a_summary_that_names_a_wrong_spread_number_is_withheld_and_the_calls_still_publish(self):
        out = self.output()
        out["summary"] = out["summary"].replace("a field goal and a half", "BUF +6")
        v = self.verify(out)
        self.assertEqual(v.summary_status, "withheld")
        self.assertTrue(any("names BUF +6" in p for p in v.summary_problems), v.summary_problems)
        self.assertEqual(len(v.calls), 3)

    def test_a_name_that_is_not_in_the_packet_is_struck(self):
        out = self.output()
        self.call(out, "moneyline")["reasons"][1]["claim"] = "Josh Allen has owned this defence."
        problems = self.struck(self.verify(out))["moneyline"]
        self.assertTrue(any("names 'josh allen'" in p for p in problems), problems)

    def test_no_baseball_club_is_vouched_for(self):
        out = self.output()
        self.call(out, "moneyline")["reasons"][1]["claim"] = "Tampa Bay Rays fans would like this one."
        problems = self.struck(self.verify(out))["moneyline"]
        self.assertTrue(any("tampa bay rays" in p for p in problems), problems)

    def test_a_player_the_report_lists_may_be_named(self):
        out = self.output()
        self.call(out, "moneyline")["reasons"][1]["claim"] = "Bee Quarterback is listed as questionable."
        self.assertEqual(self.struck(self.verify(out)), {})

    def test_a_take_at_minus_two_hundred_or_worse_is_struck_in_every_market(self):
        out = self.output()
        ml = self.packet["markets"]["moneyline"]
        lean = ml["options"][0]
        self.assertLessEqual(lean["best"]["price"], -200)
        call = F.deep(self.call(out, "moneyline"))
        call.update(verdict="TAKE", selection=ml["lean"], price=lean["best"]["price"], book=lean["best"]["book"],
                    fair_estimate=0.75, pass_price=-300)
        out["calls"][0] = call
        problems = self.struck(self.verify(out))["moneyline"]
        self.assertTrue(any("-200 or worse and cannot be a TAKE" in p for p in problems), problems)

    def test_a_take_on_the_wrong_side_of_the_lean_or_without_a_case_against_is_struck(self):
        out = self.output()
        call = self.call(out, "moneyline")
        call["case_against"] = None
        self.assertTrue(any("needs a case_against" in p for p in self.struck(self.verify(out))["moneyline"]))
        out = self.output()
        call = self.call(out, "moneyline")
        call["verdict"] = "TAKE"                 # names the road side, which is not the lean
        self.assertTrue(any("TAKE must name the lean" in p for p in self.struck(self.verify(out))["moneyline"]))

    def test_a_price_and_book_that_were_not_quoted_are_struck(self):
        out = self.output()
        self.call(out, "moneyline")["price"] = 999
        self.assertTrue(any("is not a quote for" in p for p in self.struck(self.verify(out))["moneyline"]))

    def test_a_number_that_is_not_in_the_packet_is_struck(self):
        self.assertNotIn(11, [int(n) for n in nfl_packet.base.numbers_in_packet(self.packet) if float(n) == int(n)])
        out = self.output()
        self.call(out, "total")["reasons"][0]["claim"] = "Margins land on 11 far too often to ignore."
        self.assertIn("total", self.struck(self.verify(out)))

    def test_our_words_and_the_banned_words_are_struck_wherever_a_reader_sees_them(self):
        for field, text in (("claim", "The packet says nothing beyond the price."),
                            ("claim", "The repo model likes the under."),
                            ("claim", "This is a lock."),
                            ("claim", "We have an edge on the total.")):
            out = self.output()
            self.call(out, "total")["reasons"][0]["claim"] = text
            self.assertIn("total", self.struck(self.verify(out)), text)
        out = self.output()
        out["summary"] = out["summary"].replace("The home side", "The packet says the home side")
        self.assertEqual(self.verify(out).summary_status, "withheld")
        out = self.output()
        self.call(out, "spread")["what_would_change_it"] = "News from the repo."
        self.assertIn("spread", self.struck(self.verify(out)))

    def test_a_pass_publishes_no_case_against_and_none_is_held_to_the_line_rule(self):
        out = self.output()
        sp = self.call(out, "spread")
        sp["case_against"] = {"claim": "BUF +9 would be the number.", "evidence": []}
        v = self.verify(out)
        self.assertEqual(self.struck(v), {})
        self.assertIsNone(self.published(v, "spread")["case_against"])


class TheLineRuleOnItsOwn(Env):
    def test_the_quoted_numbers_are_the_options_and_where_they_started(self):
        q = nfl_analyst.quoted_numbers(self.packet)
        self.assertEqual(q["spread"], {"BUF": {3.5}, "KC": {-3.5}})
        self.assertEqual(q["total"], {47.5})

    def test_a_club_code_is_matched_as_written_so_the_words_no_and_la_are_safe(self):
        packet = {"game": {"away": "NO", "home": "LA"},
                  "markets": {"spread": {"options": [{"side": "away", "line": 3.0}, {"side": "home", "line": -3.0}]}}}
        self.assertEqual(nfl_analyst.line_problems(packet, "There is no -4 in it, and la +9 either.", "x"), [])
        self.assertTrue(nfl_analyst.line_problems(packet, "NO +4 is wrong and LA -3 is right.", "x"))
        self.assertEqual(nfl_analyst.line_problems(packet, "LA -3 and NO +3 are the two sides.", "x"), [])

    def test_a_game_with_no_spread_in_the_packet_has_no_quoted_number(self):
        packet = {"game": {"away": "BUF", "home": "KC"}, "markets": {}}
        problems = nfl_analyst.line_problems(packet, "BUF +3.5 looks right.", "x")
        self.assertTrue(problems and "none quoted" in problems[0])

    def test_a_turnover_margin_written_as_a_plain_number_is_not_a_spread_claim(self):
        self.assertEqual(nfl_analyst.line_problems(self.packet, "A turnover margin of -1.5 a game.", "x"), [])
        self.assertEqual(nfl_analyst.line_problems(self.packet, "Held under 20 points twice.", "x"), [])


if __name__ == "__main__":
    unittest.main()
