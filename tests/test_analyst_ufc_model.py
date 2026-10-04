"""The UFC prompt, the request and the call: the MLB machinery with a fight prompt.

The HTTP caller is injected everywhere; nothing here touches a network or reads the repo's
data. `tests/test_analyst_model.py` pins the MLB side and is untouched by any of this.
"""

from __future__ import annotations

import re
import tempfile
import unittest

from src.analyst import analyst as A
from src.analyst import ledger as mlb_ledger
from src.analyst import packet as base
from src.analyst import ufc_analyst as U
from tests import ufc_analyst_fixtures as F

# The MLB prompt's sentences that the UFC prompt rewords on purpose, because they name
# baseball. Every OTHER sentence of the MLB prompt must be in the UFC prompt word for word:
# if a rule is added to or changed in the MLB prompt, this test fails until the UFC prompt
# carries it or this list says, in writing, that it should not.
REWORDED = {
    # Rule 3a of MLB prompt v3 (2026-10-04), declared derivations. The UFC analyst does not carry it for the
    # same reason: its schema, critic and hash are unchanged, and the critic ignores a `derived` key on a UFC
    # reason (tests/test_analyst_derived.py pins that), so a UFC number is checked against the packet as before.
    "3a.",
    "The one exception to doing arithmetic is a calculation you declare.",
    "A number you work out yourself (a difference, a sum, a ratio, a percent change, the days between two dates, the chance a price implies, a count or an average) may appear in a reason, a case against or the summary only if that item lists it in `derived` as {value, unit, op, inputs, note}.",
    "`op` is one of difference, sum, ratio, percent_change, days_between, implied_probability, count, mean.",
    "`inputs` are packet paths, in order:",
    "difference is the first minus the second, ratio is the first over the second, percent_change is the change from the first to the second as a percent of the first, days_between is the calendar days between two dates in UTC (later minus earlier), implied_probability takes one American price, count takes one list.",
    "`unit` is what the value is measured in (days, runs, percent, and so on) and `note` says in plain words what it is.",
    "The checker recomputes every derived value from the packet, and a wrong one strikes the call.",
    "Put the summary's in `summary_derived`.",
    "An item with no calculated number has an empty `derived`.",
    # Rule 14a of MLB prompt v4 (2026-10-04), no "packet" in what a reader sees. The UFC analyst does not
    # carry it: its prompt and prompt hash must not change, and the critic only strikes the word in an MLB
    # item (tests/test_analyst_v4.py pins both). A UFC rule of its own is a later decision.
    "14a.",
    "Everything a reader sees (the summary, every reason's claim, the case against and what_would_change_it) is read by a customer who has never heard of a packet.",
    "In those fields call the data \"the data\" or \"what we have\", never \"the packet\".",
    "The checker strikes the word \"packet\" there.",
    "Evidence paths keep their own form.",
    # Rule 13a of MLB prompt v2 (2026-10-03), the required case against. The UFC analyst deliberately
    # does not carry it: the UFC request, schema, critic and prompt hash are unchanged (the MLB schema
    # is its own copy, `analyst.MLB_RESPONSE_SCHEMA`), and a UFC case against is a later decision.
    "13a.",
    "case_against:",
    "for a TAKE or a TAKE_OTHER_SIDE, the strongest reason from the packet that this bet loses, written as {claim, evidence} and built like a reason.",
    "It must name a specific weakness in this bet, such as a number in the packet that points the other way, not general risk:",
    "\"anything can happen in baseball\" is not a case against.",
    "Cite at least one packet path, and quote only numbers that are in the packet.",
    "Argue it as hard as you would argue the other side.",
    "For a PASS it is null.",
    "You are a baseball betting analyst.",
    "You write the analysis of one MLB game and make a call on every market the packet prices.",
    "Your work is published before the game, graded afterward, and shown next to its record whatever that record turns out to be.",
    "Use no outside knowledge of any team, player, injury, weather, standing or result, even if you are sure of it.",
    "markets.moneyline.options[0].best.price and sections.starters.values.home_sp_era.",
    "Do no arithmetic of your own on packet numbers in prose (no differences, sums or ratios); quote the packet's numbers.",
    "The books' own de-vigged number is in the packet as fair_probability, and for props the repo model's number is in context.",
    "one sentence naming a specific new fact that would flip the call, such as a lineup change or a scratch.",
    "\"Even though TB is -127, I like it:",
    "the starter has the better numbers over his last starts and the price is close to a coin flip.\" Only with facts that are actually in the packet.",
}


def sentences(text: str) -> list:
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\d+\.\s+", "", line.strip())
        for s in re.split(r"(?<=[.!?:])\s+", line):
            if s.strip():
                out.append(s.strip())
    return out


class World(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = F.make_store(cls._tmp.name)
        cls.packet = F.packet(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class ThePrompt(World):
    def test_it_is_versioned_and_hashed_with_the_schema(self):
        self.assertEqual(U.UFC_PROMPT_VERSION, "analyst_ufc_prompt_v1")
        self.assertRegex(U.prompt_hash(), r"^[0-9a-f]{64}$")
        self.assertNotEqual(U.prompt_hash(), mlb_ledger.prompt_hash())

    def test_every_mlb_rule_is_in_it_word_for_word_except_the_baseball_ones(self):
        missing = {s for s in sentences(A.SYSTEM_PROMPT) if s not in U.UFC_SYSTEM_PROMPT}
        self.assertEqual(missing, REWORDED)

    def test_the_rewordings_say_the_ufc_thing(self):
        text = U.UFC_SYSTEM_PROMPT
        for needle in ("You are a mixed martial arts betting analyst.", "one UFC bout",
                       "published before the bout", "any fighter, opponent, camp, injury, weight cut, ranking or result",
                       "including the differences it already holds in sections.matchup",
                       "fair_probability is the price as a probability with the bookmaker's margin taken out",
                       "implied_probability is the same price with the margin left in",
                       "such as a late price move or a change of opponent"):
            self.assertIn(needle, text)
        self.assertNotIn("MLB", text)
        self.assertNotRegex(text, r"(?i)baseball|pitcher|lineup|run line|\binnings?\b")

    def test_the_hard_rules_are_stated(self):
        text = U.UFC_SYSTEM_PROMPT
        self.assertIn("PASS is the default.", text)
        self.assertIn("Never TAKE any bet at a price of -200 or worse, in any market", text)
        self.assertIn("A claim without a packet path is forbidden.", text)
        self.assertIn("Never write: lock, guaranteed, free money, sure thing, can't lose, +EV.", text)
        self.assertIn("Say plainly when the market is probably right", text)
        self.assertIn("Do not recommend a stake size", text)
        self.assertIn("120 to 200 words", text)

    def test_the_fight_guidance_is_there(self):
        text = U.UFC_SYSTEM_PROMPT
        for heading in ("THE FIGHT", "Style matchup.", "Finishing threat against durability.",
                        "Pace and fight time against the rounds total.", "Layoff and short notice.",
                        "Thin samples."):
            self.assertIn(heading, text)
        self.assertIn("a round is five minutes", text)
        self.assertIn("a rate from one or two fights is not a rate", text)
        self.assertIn("Short notice, injuries, weight cuts and camp changes are not in the packet.", text)

    def test_the_summary_example_has_no_number_and_no_name_to_be_copied(self):
        example = re.search(r'A voice like: "([^"]+)"', U.UFC_SYSTEM_PROMPT).group(1)
        self.assertNotRegex(example, r"\d")
        self.assertNotRegex(example, r"[A-Z][a-z]+ [A-Z][a-z]+")

    def test_every_path_the_prompt_names_resolves_in_a_real_packet(self):
        paths = {p.rstrip(".,)") for p in re.findall(r"(?:markets|sections)\.[A-Za-z0-9_.\[\]]+", U.UFC_SYSTEM_PROMPT)}
        self.assertGreaterEqual(len(paths), 4)
        for path in paths:
            ok, found = base.resolve_path(self.packet, path)
            self.assertTrue(ok, f"{path}: {found}")

    def test_every_field_the_prompt_names_is_a_key_in_the_packet(self):
        keys = set()

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    keys.add(k)
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(self.packet)
        for name in ("finish_rate", "knockdowns_landed_per_15", "submission_attempts_per_15",
                     "been_finished_rate", "knockdowns_suffered_per_15", "average_fight_time_s",
                     "distance_rate", "days_since_last_fight", "thin_sample", "wins_by_method",
                     "losses_by_method", "last_three", "not_assessed", "scheduled_rounds",
                     "fair_probability", "implied_probability", "layoff", "styles"):
            self.assertIn(name, keys, f"the prompt names {name!r} and the packet has no such key")
            self.assertIn(name, U.UFC_SYSTEM_PROMPT)


class TheRequest(World):
    def setUp(self):
        self.body = U.build_request(self.packet, F.CFG)

    def test_the_system_prompt_is_the_ufc_one_and_the_schema_is_the_shared_one(self):
        self.assertEqual(self.body["system"], U.UFC_SYSTEM_PROMPT)
        self.assertEqual(self.body["output_config"]["format"]["schema"], A.RESPONSE_SCHEMA)
        self.assertEqual(self.body["model"], "claude-sonnet-5-5")

    def test_the_request_has_no_temperature_thinking_or_prefill(self):
        self.assertFalse({"temperature", "thinking", "top_p", "top_k"} & set(self.body))
        self.assertEqual([m["role"] for m in self.body["messages"]], ["user"])

    def test_the_user_message_is_the_packet_and_the_slots_in_order(self):
        text = self.body["messages"][0]["content"]
        self.assertIn("PACKET (JSON)", text)
        self.assertIn(A.packet_json(self.packet), text)
        self.assertTrue(text.rstrip().endswith("moneyline, rounds_total, method_a_ko, method_a_sub, "
                                               "method_a_dec, method_b_ko, method_b_sub, method_b_dec."))

    def test_the_mlb_request_is_unchanged_by_the_new_parameter(self):
        from tests import analyst_fixtures as M
        body = A.build_request(M.build(), M.CFG)
        self.assertEqual(body["system"], A.SYSTEM_PROMPT)
        self.assertIn("baseball", body["system"])

    def test_a_repair_request_carries_the_reasons(self):
        body = U.build_request(self.packet, F.CFG, repair=["summary is 5 words"])
        self.assertIn("summary is 5 words", body["messages"][0]["content"])
        self.assertEqual(body["system"], U.UFC_SYSTEM_PROMPT)


class TheCall(World):
    def answer(self, output=None, usage=None, **kw):
        return 200, F.api_response(output if output is not None else F.good_output(self.packet), usage, **kw)

    def analyze(self, http, **kw):
        return U.analyze(self.packet, F.CFG, api_key="sk-test", http_post=http, sleep=lambda s: None, **kw)

    def test_a_good_answer_is_accepted_and_costed(self):
        http = F.FakeHttp(self.answer(usage={"input_tokens": 9000, "output_tokens": 4000}))
        result = self.analyze(http)
        self.assertEqual((result.attempts, http.calls), (1, 1))
        self.assertAlmostEqual(result.cost_usd, 9000 * 2 / 1e6 + 4000 * 10 / 1e6)
        sent = http.requests[0]
        self.assertEqual(sent["body"]["system"], U.UFC_SYSTEM_PROMPT)
        self.assertEqual(sent["headers"]["x-api-key"], "sk-test")

    def test_without_a_key_nothing_is_sent(self):
        http = F.FakeHttp(self.answer())
        with self.assertRaises(A.Blocked):
            U.analyze(self.packet, F.CFG, api_key=None, http_post=http)
        self.assertEqual(http.calls, 0)

    def test_a_malformed_answer_is_repaired_once_with_the_ufc_prompt_again(self):
        bad = F.good_output(self.packet)
        bad["summary"] = "too short"
        http = F.FakeHttp(self.answer(bad), self.answer())
        result = self.analyze(http)
        self.assertEqual((result.attempts, http.calls), (2, 2))
        self.assertIn("summary is 2 words", http.requests[1]["body"]["messages"][0]["content"])
        self.assertEqual(http.requests[1]["body"]["system"], U.UFC_SYSTEM_PROMPT)

    def test_a_slot_the_packet_does_not_have_is_rejected(self):
        bad = F.good_output(self.packet)
        bad["calls"][1]["slot_id"] = "prop_01"
        errors = A.validate_output(bad, self.packet)
        self.assertTrue(any("not a slot in the packet" in e for e in errors))

    def test_a_missing_method_slot_is_rejected_and_the_order_is_enforced(self):
        bad = F.good_output(self.packet)
        del bad["calls"][-1]
        self.assertTrue(any("method_b_dec" in e and "missing" in e for e in A.validate_output(bad, self.packet)))
        swapped = F.good_output(self.packet)
        swapped["calls"][2], swapped["calls"][3] = swapped["calls"][3], swapped["calls"][2]
        self.assertTrue(any("same order" in e for e in A.validate_output(swapped, self.packet)))

    def test_a_good_output_has_no_shape_errors(self):
        self.assertEqual(A.validate_output(F.good_output(self.packet), self.packet), [])

    def test_the_market_of_a_call_must_match_its_slot(self):
        bad = F.good_output(self.packet)
        bad["calls"][2]["market"] = "moneyline"
        self.assertTrue(any("market must be 'method'" in e for e in A.validate_output(bad, self.packet)))

    def test_the_spend_cap_stops_a_call_before_it_is_made(self):
        cfg = dict(F.CFG, spend_cap={"max_usd_per_run": 0.01, "max_tokens_per_run": 10_000_000})
        http = F.FakeHttp(self.answer())
        with self.assertRaises(A.SpendCapReached):
            U.analyze(self.packet, cfg, api_key="sk-test", http_post=http, meter=A.SpendMeter.from_config(cfg))
        self.assertEqual(http.calls, 0)

    def test_a_refusal_is_not_retried_and_carries_its_cost(self):
        http = F.FakeHttp((200, F.api_response("", {"input_tokens": 9000, "output_tokens": 20}, stop_reason="refusal")))
        with self.assertRaises(A.ModelRefused) as ctx:
            self.analyze(http)
        self.assertEqual(http.calls, 1)
        self.assertGreater(ctx.exception.cost_usd, 0)


if __name__ == "__main__":
    unittest.main()
