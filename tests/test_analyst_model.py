"""The analyst's request, its schema checks, the spend cap, and BLOCKED."""

from __future__ import annotations

import copy
import json
import unittest

from src.analyst import analyst as A
from src.analyst import config as config_mod
from tests import analyst_fixtures as F


class TheRequest(unittest.TestCase):
    def setUp(self):
        self.packet = F.build()
        self.body = A.build_request(self.packet, F.CFG)

    def test_model_comes_from_config_and_defaults_to_sonnet_5_5(self):
        self.assertEqual(self.body["model"], "claude-sonnet-5-5")
        self.assertEqual(A.build_request(self.packet, dict(F.CFG, model="claude-x"))["model"], "claude-x")

    def test_it_asks_for_a_json_schema_and_sends_no_rejected_parameters(self):
        self.assertEqual(self.body["output_config"]["format"]["type"], "json_schema")
        self.assertIs(self.body["output_config"]["format"]["schema"], A.MLB_RESPONSE_SCHEMA)
        self.assertEqual(self.body["output_config"]["effort"], "medium")
        for rejected in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
            self.assertNotIn(rejected, self.body)
        self.assertEqual(self.body["messages"][0]["role"], "user")
        self.assertEqual(len(self.body["messages"]), 1)  # no assistant prefill

    def test_the_prompt_states_the_non_negotiable_rules(self):
        text = self.body["system"]
        for fragment in ("Reason only from the packet", "A claim without a packet path is forbidden",
                         "PASS is the default", "Never TAKE any bet at a price of -200 or worse, in any market",
                         "Never write: lock, guaranteed, free money",
                         "120 to 200 words", "Never start a path with data.",
                         "markets.moneyline.options[0].best.price",
                         "Say plainly when the market is probably right"):
            self.assertIn(fragment, text)

    def test_the_user_message_is_the_packet_and_the_slot_ids(self):
        content = self.body["messages"][0]["content"]
        self.assertIn(A.packet_json(self.packet), content)
        self.assertIn("moneyline, run_line, total", content)

    def test_the_key_is_never_in_the_body(self):
        self.assertNotIn("sk-ant", json.dumps(self.body))

    def test_a_repair_request_carries_the_reasons_it_was_rejected(self):
        body = A.build_request(self.packet, F.CFG, repair=["summary is 90 words"])
        self.assertIn("summary is 90 words", body["messages"][0]["content"])

    def test_the_schema_is_strict_everywhere(self):
        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                    self.assertEqual(sorted(node["required"]), sorted(node["properties"]))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(A.RESPONSE_SCHEMA)
        walk(A.MLB_RESPONSE_SCHEMA)
        walk(A.CRITIC_SCHEMA)


class Blocked(unittest.TestCase):
    def test_no_key_means_blocked_and_no_call(self):
        http = F.FakeHttp((200, F.api_response(F.good_output(F.build()))))
        with self.assertRaises(A.Blocked) as ctx:
            A.analyze(F.build(), F.CFG, api_key=None, http_post=http)
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))
        self.assertEqual(http.calls, 0)

    def test_an_empty_key_is_no_key(self):
        self.assertIsNone(config_mod.api_key({"ANTHROPIC_API_KEY": "   "}))
        self.assertIsNone(config_mod.api_key({}))
        self.assertEqual(config_mod.api_key({"ANTHROPIC_API_KEY": " k "}), "k")


class AnalyzeHappyPath(unittest.TestCase):
    def test_returns_the_parsed_answer_and_its_cost_from_the_usage(self):
        packet = F.build()
        http = F.FakeHttp((200, F.api_response(F.good_output(packet),
                                               {"input_tokens": 10000, "output_tokens": 5000})))
        result = A.analyze(packet, F.CFG, api_key="sk-test", http_post=http)
        self.assertEqual(len(result.output["calls"]), len(packet["slots"]))
        # 10,000 in at $2/M + 5,000 out at $10/M = $0.07
        self.assertAlmostEqual(result.cost_usd, 0.07, places=6)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.usage["output_tokens"], 5000)

    def test_the_key_is_sent_as_a_header_and_nowhere_else(self):
        packet = F.build()
        http = F.FakeHttp((200, F.api_response(F.good_output(packet))))
        A.analyze(packet, F.CFG, api_key="sk-test-123", http_post=http)
        req = http.requests[0]
        self.assertEqual(req["headers"]["x-api-key"], "sk-test-123")
        self.assertEqual(req["headers"]["anthropic-version"], "2023-06-01")
        self.assertNotIn("sk-test-123", json.dumps(req["body"]))
        self.assertEqual(req["url"], "https://api.anthropic.com/v1/messages")

    def test_cost_counts_cache_reads_and_writes_at_their_own_price(self):
        usage = {"input_tokens": 1000, "output_tokens": 1000,
                 "cache_read_input_tokens": 10000, "cache_creation_input_tokens": 1000}
        # 1000*2 + 1000*2*1.25 + 10000*0.2 + 1000*10, per million
        self.assertAlmostEqual(A.cost_usd(usage, F.CFG), (2000 + 2500 + 2000 + 10000) / 1e6)

    def test_thinking_blocks_are_ignored_and_only_text_is_read(self):
        packet = F.build()
        http = F.FakeHttp((200, F.api_response(F.good_output(packet))))
        self.assertTrue(A.analyze(packet, F.CFG, api_key="k", http_post=http).output["summary"])


class ShapeValidation(unittest.TestCase):
    def setUp(self):
        self.packet = F.build()
        self.good = F.good_output(self.packet)

    def errors(self, mutate):
        out = copy.deepcopy(self.good)
        mutate(out)
        return A.validate_output(out, self.packet)

    def test_a_good_answer_has_no_shape_errors(self):
        self.assertEqual(A.validate_output(self.good, self.packet), [])

    def test_not_an_object(self):
        self.assertEqual(A.validate_output([], self.packet), ["the answer is not a JSON object"])

    def test_short_and_long_summaries_are_rejected(self):
        self.assertTrue(any("summary is" in e for e in self.errors(lambda o: o.update(summary="too short"))))
        self.assertTrue(any("summary is" in e for e in self.errors(lambda o: o.update(summary="word " * 250))))

    def test_a_missing_slot_is_rejected(self):
        errs = self.errors(lambda o: o["calls"].pop())
        self.assertTrue(any("missing; every slot needs one call" in e for e in errs))

    def test_a_duplicate_slot_is_rejected(self):
        errs = self.errors(lambda o: o["calls"].append(copy.deepcopy(o["calls"][0])))
        self.assertTrue(any("more than one call" in e for e in errs))

    def test_an_unknown_slot_is_rejected(self):
        def m(o): o["calls"][0]["slot_id"] = "moneyline_2"
        self.assertTrue(any("not a slot in the packet" in e for e in self.errors(m)))

    def test_wrong_market_label(self):
        def m(o): o["calls"][1]["market"] = "total"
        self.assertTrue(any("market must be" in e for e in self.errors(m)))

    def test_bad_enums_and_numbers(self):
        def m(o):
            c = o["calls"][1]
            c.update(verdict="BET", confidence="certain", fair_estimate=1.4, price=110.5)
        errs = " | ".join(self.errors(m))
        for fragment in ("verdict must be", "confidence must be", "fair_estimate must be a probability",
                         "price must be a whole number"):
            self.assertIn(fragment, errs)

    def test_a_bool_is_not_a_price_or_a_probability(self):
        def m(o):
            o["calls"][1].update(price=True, fair_estimate=True)
        errs = " | ".join(self.errors(m))
        self.assertIn("price must be a whole number", errs)
        self.assertIn("fair_estimate must be a probability", errs)

    def test_missing_and_extra_keys(self):
        def drop(o): del o["calls"][0]["reasons"]
        def extra(o): o["calls"][0]["bonus"] = 1
        def top(o): o["note"] = "hi"
        self.assertTrue(any("is missing" in e for e in self.errors(drop)))
        self.assertTrue(any("unexpected keys" in e for e in self.errors(extra)))
        self.assertTrue(any("unexpected top-level" in e for e in self.errors(top)))

    def test_reasons_need_a_claim_and_an_evidence_list(self):
        def m(o): o["calls"][0]["reasons"] = [{"claim": "x"}]
        self.assertTrue(any("needs a claim and an evidence list" in e for e in self.errors(m)))
        def n(o): o["calls"][0]["reasons"] = []
        self.assertTrue(any("non-empty list" in e for e in self.errors(n)))

    def test_calls_out_of_slot_order_are_rejected(self):
        def m(o): o["calls"][0], o["calls"][1] = o["calls"][1], o["calls"][0]
        self.assertTrue(any("same order" in e for e in self.errors(m)))


class MalformedOutputIsRetriedOnceThenRejected(unittest.TestCase):
    def test_a_malformed_first_answer_gets_one_repair_attempt(self):
        packet = F.build()
        bad = F.good_output(packet)
        bad["summary"] = "far too short"
        http = F.FakeHttp((200, F.api_response(bad, {"input_tokens": 100, "output_tokens": 100})),
                          (200, F.api_response(F.good_output(packet), {"input_tokens": 200, "output_tokens": 300})))
        result = A.analyze(packet, F.CFG, api_key="k", http_post=http)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(http.calls, 2)
        self.assertIn("summary is", http.requests[1]["body"]["messages"][0]["content"])
        self.assertEqual(result.usage["input_tokens"], 300)   # both attempts are paid for
        self.assertEqual(len(result.request_ids), 2)

    def test_two_malformed_answers_raise_with_the_reasons_and_the_usage(self):
        packet = F.build()
        bad = F.good_output(packet)
        bad["summary"] = "far too short"
        http = F.FakeHttp((200, F.api_response(bad)), (200, F.api_response(bad)))
        with self.assertRaises(A.MalformedOutput) as ctx:
            A.analyze(packet, F.CFG, api_key="k", http_post=http)
        self.assertTrue(any("summary is" in e for e in ctx.exception.errors))
        self.assertEqual(ctx.exception.usage["output_tokens"], 10000)

    def test_text_that_is_not_json_is_malformed(self):
        http = F.FakeHttp((200, F.api_response("this is not json")))
        with self.assertRaises(A.MalformedOutput):
            A.analyze(F.build(), dict(F.CFG, max_attempts=1), api_key="k", http_post=http)

    def test_a_refusal_is_not_retried_and_not_published(self):
        http = F.FakeHttp((200, F.api_response("", stop_reason="refusal")))
        with self.assertRaises(A.ModelRefused):
            A.analyze(F.build(), F.CFG, api_key="k", http_post=http)
        self.assertEqual(http.calls, 1)

    def test_a_truncated_answer_is_unusable(self):
        http = F.FakeHttp((200, F.api_response('{"summary": "x', stop_reason="max_tokens")))
        with self.assertRaises(A.ModelRefused):
            A.analyze(F.build(), F.CFG, api_key="k", http_post=http)


class HttpErrors(unittest.TestCase):
    def test_a_rate_limit_is_retried_then_succeeds(self):
        packet = F.build()
        http = F.FakeHttp((429, b'{"error": {"message": "slow down"}}'),
                          (200, F.api_response(F.good_output(packet))))
        slept = []
        result = A.analyze(packet, F.CFG, api_key="k", http_post=http, sleep=slept.append)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(slept), 1)

    def test_a_client_error_raises_with_the_apis_message_and_no_key(self):
        http = F.FakeHttp((401, b'{"error": {"message": "invalid x-api-key"}}'))
        with self.assertRaises(A.HttpFailure) as ctx:
            A.analyze(F.build(), F.CFG, api_key="sk-secret-value", http_post=http)
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertNotIn("sk-secret-value", str(ctx.exception))
        self.assertEqual(http.calls, 1)

    def test_a_response_that_is_not_json_raises(self):
        http = F.FakeHttp((200, b"<html>"))
        with self.assertRaises(A.HttpFailure):
            A.analyze(F.build(), F.CFG, api_key="k", http_post=http)


class TheSpendCapIsHard(unittest.TestCase):
    def test_a_call_that_could_pass_the_cap_is_not_made(self):
        meter = A.SpendMeter(max_usd=0.05, max_tokens=10_000_000)
        http = F.FakeHttp((200, F.api_response(F.good_output(F.build()))))
        with self.assertRaises(A.SpendCapReached) as ctx:
            A.analyze(F.build(), F.CFG, api_key="k", http_post=http, meter=meter)
        self.assertIn("spend cap", str(ctx.exception))
        self.assertEqual(http.calls, 0)

    def test_the_token_cap_stops_a_run_too(self):
        meter = A.SpendMeter(max_usd=100.0, max_tokens=5_000)
        with self.assertRaises(A.SpendCapReached) as ctx:
            A.analyze(F.build(), F.CFG, api_key="k", http_post=F.FakeHttp((200, b"{}")), meter=meter)
        self.assertIn("token cap", str(ctx.exception))

    def test_spend_accumulates_and_the_second_game_is_stopped(self):
        packet = F.build()
        meter = A.SpendMeter(max_usd=0.5, max_tokens=10_000_000)
        http = F.FakeHttp((200, F.api_response(F.good_output(packet),
                                               {"input_tokens": 10000, "output_tokens": 40000})))
        A.analyze(packet, F.CFG, api_key="k", http_post=http, meter=meter)   # $0.42
        self.assertAlmostEqual(meter.spent_usd, 0.42, places=6)
        with self.assertRaises(A.SpendCapReached):
            A.analyze(packet, F.CFG, api_key="k", http_post=http, meter=meter)
        self.assertEqual(http.calls, 1)

    def test_a_retry_is_checked_against_the_cap_too(self):
        packet = F.build()
        bad = F.good_output(packet)
        bad["summary"] = "short"
        meter = A.SpendMeter(max_usd=0.45, max_tokens=10_000_000)
        http = F.FakeHttp((200, F.api_response(bad, {"input_tokens": 10000, "output_tokens": 40000})))
        with self.assertRaises(A.SpendCapReached):
            A.analyze(packet, F.CFG, api_key="k", http_post=http, meter=meter)
        self.assertEqual(http.calls, 1)

    def test_the_default_config_has_a_cap(self):
        cap = F.CFG["spend_cap"]
        self.assertGreater(cap["max_usd_per_run"], 0)
        self.assertGreater(cap["max_tokens_per_run"], 0)

    def test_a_bad_cap_is_an_error_not_a_default(self):
        with self.assertRaises(config_mod.ConfigError):
            config_mod.validate(dict(F.CFG, spend_cap={"max_usd_per_run": 0, "max_tokens_per_run": 1}))
        with self.assertRaises(config_mod.ConfigError):
            config_mod.validate(dict(F.CFG, price_per_million_usd={"input": "x", "output": 1}))


class TheKeyOnlyTravelsOverHttps(unittest.TestCase):
    def test_a_non_https_api_url_is_a_config_error_not_a_leak(self):
        for bad in ("http://api.anthropic.com/v1/messages", "ftp://x", "", None, 5):
            with self.assertRaises(config_mod.ConfigError):
                config_mod.validate(dict(F.CFG, api_url=bad))

    def test_the_shipped_url_is_https_and_the_timeout_covers_a_long_answer(self):
        cfg = config_mod.load()
        self.assertTrue(cfg["api_url"].startswith("https://"))
        self.assertGreaterEqual(cfg["request_timeout_s"], 600)


class TheShippedConfig(unittest.TestCase):
    def test_config_file_loads_and_matches_the_defaults_that_matter(self):
        cfg = config_mod.load()
        self.assertEqual(cfg["model"], "claude-sonnet-5-5")
        self.assertEqual(cfg["price_per_million_usd"]["input"], 2.0)
        self.assertEqual(cfg["price_per_million_usd"]["output"], 10.0)
        self.assertEqual(cfg["min_graded_for_rates"], 30)
        self.assertFalse(cfg["model_critic"]["enabled"])


if __name__ == "__main__":
    unittest.main()
