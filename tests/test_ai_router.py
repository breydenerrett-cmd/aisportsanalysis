"""The AI router: fallback order, quota skips, the hard paid cap, strict JSON, batches, and no network.

Every transport is a fake. ``setUp`` also makes the real network entry points raise, so a test that reached
for the internet would go red instead of quietly spending money.
"""

from __future__ import annotations

import socket
import tempfile
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.ai import decision, router as R, schema
from src.ai.usage import UsageStore

UTC = timezone.utc
GOOD = ('{"decision": "bet", "market": "moneyline", "side": "home", "confidence": 3, '
        '"reason": "Home price is longer than the books\' number."}')
PASS_ = '{"decision": "pass", "market": null, "side": null, "confidence": 2, "reason": "Nothing stands out."}'


class Clock:
    def __init__(self, start="2026-10-20T12:00:00"):
        self.now = datetime.fromisoformat(start).replace(tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class FakeAdapter:
    """Scripted per provider id: each call pops the next item (an AdapterResult, or an exception to raise)."""

    def __init__(self, scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls = []

    def complete(self, spec, model, system, user, *, api_key, timeout_s, max_tokens, cache_system=False):
        self.calls.append(spec.id)
        script = self.scripts[spec.id]
        item = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(item, BaseException):
            raise item
        return item


def reply(text, tin=1000, tout=100):
    return R.AdapterResult(text=text, input_tokens=tin, output_tokens=tout)


def fake_config(*providers, cap_extra=None):
    prov = {}
    for pid, extra in providers:
        entry = {"kind": "fake", "enabled": True, "env_key": f"KEY_{pid.upper()}", "model": f"model-{pid}",
                 "max_tokens": 200, "price_in_per_m": 0.0, "price_out_per_m": 0.0, "timeout_s": 20}
        entry.update(extra or {})
        prov[pid] = entry
    return {"order": [p for p, _ in providers], "providers": prov,
            "defaults": {"quota_cooldown_minutes": 30, "error_cooldown_minutes": 3, "auth_cooldown_minutes": 120,
                         "spend_limit_cooldown_minutes": 360, "max_attempts": 3}}


class RouterCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.clock = Clock()
        self.usage_path = Path(self._tmp.name) / "ai_usage.jsonl"
        for target in ("urllib.request.urlopen", "socket.create_connection"):
            patcher = mock.patch(target, side_effect=AssertionError("a test reached for the network"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def usage(self):
        return UsageStore(self.usage_path, clock=self.clock)

    def router(self, config, scripts, env=None, adapter=None):
        env = dict({f"KEY_{p.upper()}": "k" * 12 for p in config["providers"]}, **(env or {}))
        adapter = adapter or FakeAdapter(scripts)
        r = R.Router(config, env=env, adapters={"fake": adapter}, usage=self.usage())
        return r, adapter

    def ask(self, r, **kw):
        return r.ask("rules", "board", schema=decision.DECISION_SCHEMA, validator=decision.check_decision, **kw)


class FallbackAndQuotaTests(RouterCase):
    def test_providers_are_tried_in_config_order_until_one_answers(self):
        cfg = fake_config(("a", None), ("b", None), ("c", None))
        r, adapter = self.router(cfg, {"a": [R.AdapterError("error", "HTTP 500")], "b": [reply(GOOD)], "c": [reply(GOOD)]})
        ans = self.ask(r)
        self.assertTrue(ans.ok)
        self.assertEqual((ans.provider, ans.model), ("b", "model-b"))
        self.assertEqual(adapter.calls, ["a", "b"])
        self.assertEqual(set(ans.to_dict()) >= {"provider", "model", "latency_ms", "cost_usd", "output"}, True)

    def test_a_429_skips_that_provider_for_the_cooldown_then_it_is_tried_again(self):
        cfg = fake_config(("a", None), ("b", None))
        r, adapter = self.router(cfg, {"a": [R.AdapterError("quota", "HTTP 429"), reply(GOOD)], "b": [reply(GOOD)]})
        self.assertEqual(self.ask(r).provider, "b")
        self.assertEqual(adapter.calls, ["a", "b"])
        adapter.calls.clear()
        self.clock.advance(minutes=29)
        self.assertEqual(self.ask(r).provider, "b")
        self.assertEqual(adapter.calls, ["b"], "inside the 30-minute cooldown, a is not even called")
        adapter.calls.clear()
        self.clock.advance(minutes=2)
        self.assertEqual(self.ask(r).provider, "a")
        self.assertEqual(adapter.calls, ["a"])

    def test_retry_after_sets_the_cooldown(self):
        cfg = fake_config(("a", None), ("b", None))
        r, adapter = self.router(cfg, {"a": [R.AdapterError("quota", "HTTP 429", retry_after_s=600)], "b": [reply(GOOD)]})
        self.ask(r)
        adapter.calls.clear()
        self.clock.advance(minutes=11)
        self.ask(r)
        self.assertEqual(adapter.calls[0], "a")

    def test_a_cooldown_survives_a_restart(self):
        cfg = fake_config(("a", None), ("b", None))
        r, _ = self.router(cfg, {"a": [R.AdapterError("quota", "HTTP 429")], "b": [reply(GOOD)]})
        self.ask(r)
        r2, adapter2 = self.router(cfg, {"a": [reply(GOOD)], "b": [reply(GOOD)]})
        self.assertEqual(self.ask(r2).provider, "b")
        self.assertEqual(adapter2.calls, ["b"])

    def test_daily_cap_skips_a_provider_and_resets_the_next_day(self):
        cfg = fake_config(("a", {"daily_cap": 2}), ("b", None))
        r, adapter = self.router(cfg, {"a": [reply(GOOD)], "b": [reply(GOOD)]})
        self.assertEqual([self.ask(r).provider for _ in range(3)], ["a", "a", "b"])
        self.clock.advance(days=1)
        self.assertEqual(self.ask(r).provider, "a")

    def test_every_provider_down_is_no_answer_not_a_guess(self):
        cfg = fake_config(("a", None), ("b", None))
        r, _ = self.router(cfg, {"a": [R.AdapterError("timeout", "slow")], "b": [R.AdapterError("quota", "HTTP 429")]})
        ans = self.ask(r)
        self.assertFalse(ans.ok)
        self.assertIsNone(ans.output)
        self.assertIsNone(ans.provider)
        self.assertIn("no answer", ans.reason)
        self.assertTrue(r.degraded())

    def test_a_provider_without_its_key_or_switched_off_is_never_called(self):
        cfg = fake_config(("a", {"enabled": False}), ("b", None), ("c", None))
        r, adapter = self.router(cfg, {"a": [reply(GOOD)], "b": [reply(GOOD)], "c": [reply(GOOD)]}, env={"KEY_B": ""})
        self.assertEqual(self.ask(r).provider, "c")
        self.assertEqual(adapter.calls, ["c"])
        reasons = {p["id"]: p["disabled_reason"] for p in r.status()["providers"]}
        self.assertIn("switched off", reasons["a"])
        self.assertIn("KEY_B", reasons["b"])

    def test_auth_failure_cools_down_for_hours(self):
        cfg = fake_config(("a", None), ("b", None))
        r, adapter = self.router(cfg, {"a": [R.AdapterError("auth", "HTTP 401")], "b": [reply(GOOD)]})
        self.ask(r)
        adapter.calls.clear()
        self.clock.advance(minutes=100)
        self.ask(r)
        self.assertEqual(adapter.calls, ["b"])

    def test_an_exception_the_adapter_did_not_expect_is_still_a_skip(self):
        cfg = fake_config(("a", None), ("b", None))
        r, _ = self.router(cfg, {"a": [RuntimeError("adapter bug")], "b": [reply(GOOD)]})
        self.assertEqual(self.ask(r).provider, "b")

    def test_timeouts_are_clamped_to_twenty_seconds(self):
        cfg = fake_config(("a", {"timeout_s": 300}))
        self.assertEqual(R.specs_from_config(cfg)[0].timeout_s, 20.0)


class StrictJsonTests(RouterCase):
    def test_invalid_output_is_retried_once_on_the_next_provider(self):
        cfg = fake_config(("a", None), ("b", None), ("c", None))
        r, adapter = self.router(cfg, {"a": [reply("I think the home side")], "b": [reply(GOOD)], "c": [reply(GOOD)]})
        ans = self.ask(r)
        self.assertEqual((ans.ok, ans.provider), (True, "b"))
        self.assertEqual(adapter.calls, ["a", "b"])

    def test_two_invalid_replies_in_a_row_is_no_answer(self):
        cfg = fake_config(("a", None), ("b", None), ("c", None))
        r, adapter = self.router(cfg, {"a": [reply("nope")], "b": [reply('{"decision": "maybe"}')], "c": [reply(GOOD)]})
        ans = self.ask(r)
        self.assertFalse(ans.ok)
        self.assertEqual(adapter.calls, ["a", "b"], "the third provider is not tried: one retry only")

    def test_a_single_provider_with_an_invalid_reply_has_no_second_chance(self):
        r, adapter = self.router(fake_config(("a", None)), {"a": [reply("```nonsense```")]})
        self.assertFalse(self.ask(r).ok)
        self.assertEqual(adapter.calls, ["a"])

    def test_schema_rejections_each_pinned(self):
        bad = {
            "confidence 9": GOOD.replace('"confidence": 3', '"confidence": 9'),
            "confidence 0": GOOD.replace('"confidence": 3', '"confidence": 0'),
            "confidence as text": GOOD.replace('"confidence": 3', '"confidence": "3"'),
            "confidence float": GOOD.replace('"confidence": 3', '"confidence": 3.5'),
            "extra key": GOOD[:-1] + ', "stake": 5}',
            "missing reason": '{"decision": "pass", "market": null, "side": null, "confidence": 1}',
            "bad decision": GOOD.replace('"bet"', '"lock"'),
            "bad market": GOOD.replace('"moneyline"', '"parlay"'),
            "26 words": GOOD.replace("Home price is longer than the books' number.", " ".join(["word"] * 26)),
            "empty reason": GOOD.replace("Home price is longer than the books' number.", "  "),
            "a list": "[1, 2]",
            "bet with no side": GOOD.replace('"side": "home"', '"side": null'),
            "side not of the market": GOOD.replace('"market": "moneyline"', '"market": "total"'),
        }
        for label, text in bad.items():
            with self.subTest(label):
                obj, why = schema.extract_json_object(text)
                problems = [why] if why else decision.validate_decision(obj)
                self.assertTrue(problems, f"{label} must be rejected")

    def test_25_words_and_a_fenced_block_are_accepted(self):
        text = "```json\n" + GOOD.replace("Home price is longer than the books' number.", " ".join(["w"] * 25)) + "\n```"
        obj, why = schema.extract_json_object(text)
        self.assertIsNone(why)
        self.assertEqual(decision.validate_decision(obj), [])

    def test_a_think_block_is_dropped_but_the_value_is_never_repaired(self):
        obj, why = schema.extract_json_object("<think>hmm</think>" + PASS_)
        self.assertIsNone(why)
        self.assertEqual(obj["decision"], "pass")
        long = GOOD.replace('"confidence": 3', '"confidence": 12')
        self.assertTrue(decision.validate_decision(schema.extract_json_object(long)[0]))

    def test_refusal_is_a_skip_not_an_invalid_reply(self):
        cfg = fake_config(("a", None), ("b", None), ("c", None))
        refused = R.AdapterResult(text="", input_tokens=10, output_tokens=0, refused=True)
        r, adapter = self.router(cfg, {"a": [refused], "b": [reply("bad")], "c": [reply(GOOD)]})
        ans = self.ask(r)
        self.assertEqual(ans.provider, "c")
        self.assertEqual(adapter.calls, ["a", "b", "c"])


class PaidCapTests(RouterCase):
    PAID = {"paid": True, "price_in_per_m": 0.10, "price_out_per_m": 0.50, "max_tokens": 1000}

    def paid_router(self, cap, scripts=None, tin=1000, tout=100):
        cfg = fake_config(("paid", self.PAID))
        return self.router(cfg, scripts or {"paid": [reply(GOOD, tin, tout)]}, env={"AI_PAID_CAP_USD": str(cap)})

    def test_default_cap_is_five_dollars_and_bad_values_fall_back_to_it(self):
        self.assertEqual(R.paid_cap_usd({}), 5.0)
        self.assertEqual(R.paid_cap_usd({"AI_PAID_CAP_USD": ""}), 5.0)
        self.assertEqual(R.paid_cap_usd({"AI_PAID_CAP_USD": "lots"}), 5.0)
        self.assertEqual(R.paid_cap_usd({"AI_PAID_CAP_USD": "nan"}), 5.0)
        self.assertEqual(R.paid_cap_usd({"AI_PAID_CAP_USD": "2.5"}), 2.5)
        self.assertEqual(R.paid_cap_usd({"AI_PAID_CAP_USD": "-3"}), 0.0)

    def test_cost_comes_from_response_usage_at_the_owners_prices(self):
        r, _ = self.paid_router(5, tin=1_000_000, tout=1_000_000)
        ans = self.ask(r)
        self.assertAlmostEqual(ans.cost_usd, 0.60, places=6)       # $0.10/M in + $0.50/M out
        self.assertAlmostEqual(r.paid_spend(), 0.60, places=6)

    def test_missing_usage_is_charged_the_worst_case_not_zero(self):
        r, _ = self.paid_router(5, scripts={"paid": [R.AdapterResult(text=GOOD)]})
        ans = self.ask(r)
        self.assertGreater(ans.cost_usd, 0.0)

    def test_the_cap_refuses_the_call_that_would_cross_it_and_makes_no_call(self):
        r, adapter = self.paid_router(0.0006, tin=1000, tout=100)   # worst case ~ $0.0005: the first call fits, a second would not
        self.assertTrue(self.ask(r).ok)
        spent = r.paid_spend()
        self.assertLess(spent, 0.0006)
        ans = self.ask(r)                                           # spent + worst case would pass the cap
        self.assertFalse(ans.ok)
        self.assertIn("monthly paid cap", ans.reason)
        self.assertEqual(adapter.calls, ["paid"], "no second call went out")

    def test_the_cap_holds_across_a_restart_because_spend_is_in_the_file(self):
        r, _ = self.paid_router(0.0006)
        self.ask(r)
        self.ask(r)
        r2, adapter2 = self.paid_router(0.0006)
        self.assertFalse(self.ask(r2).ok)
        self.assertEqual(adapter2.calls, [])

    def test_a_new_month_starts_a_new_budget(self):
        r, adapter = self.paid_router(0.0006)
        self.ask(r)
        self.assertFalse(self.ask(r).ok)
        self.clock.advance(days=12)                                  # 2026-11-01
        self.assertTrue(self.ask(r).ok)

    def test_cap_zero_turns_paid_calls_off(self):
        r, adapter = self.paid_router(0)
        self.assertFalse(self.ask(r).ok)
        self.assertEqual(adapter.calls, [])
        self.assertIn("is 0", r.status()["providers"][0]["disabled_reason"])

    def test_the_default_cap_lets_a_hound_sized_call_through_and_never_exceeds_five_dollars(self):
        cfg = fake_config(("paid", self.PAID))
        r, adapter = self.router(cfg, {"paid": [reply(GOOD, 2000, 300)]})
        for _ in range(100):
            self.ask(r)
        self.assertLessEqual(r.paid_spend(), 5.0)
        self.assertEqual(len(adapter.calls), 100)

    def test_status_reports_spend_against_the_cap_and_the_last_errors(self):
        cfg = fake_config(("paid", self.PAID))
        r, _ = self.router(cfg, {"paid": [reply("not json"), reply(GOOD)]}, env={"AI_PAID_CAP_USD": "5"})
        self.ask(r)
        st = r.status()
        self.assertEqual(st["paid"]["cap_usd"], 5.0)
        self.assertGreater(st["paid"]["spend_usd"], 0)
        self.assertEqual(st["paid"]["remaining_usd"], round(5.0 - st["paid"]["spend_usd"], 8))
        self.assertEqual(st["last_errors"][0]["status"], "invalid")
        self.assertEqual(st["providers"][0]["calls_today"], 1)
        self.assertFalse(st["degraded"])


class PromptGuardTests(RouterCase):
    def test_an_email_a_phone_or_a_key_in_a_prompt_is_refused_before_any_call(self):
        cfg = fake_config(("a", None))
        r, adapter = self.router(cfg, {"a": [reply(GOOD)]})
        for text in ("contact me at brey@example.com", "call 555-867-5309 now", "my id 123-45-6789",
                     "key sk-ant-api03-abcdefghijklmnop", "Bearer abcdefghijklmnopqrstuvwx"):
            with self.subTest(text):
                ans = r.ask("rules", text, schema=decision.DECISION_SCHEMA)
                self.assertFalse(ans.ok)
                self.assertIn("refused", ans.reason)
        self.assertEqual(adapter.calls, [])

    def test_a_configured_secret_value_in_a_prompt_is_refused(self):
        cfg = fake_config(("a", None))
        r, adapter = self.router(cfg, {"a": [reply(GOOD)]}, env={"APP_ADMIN_TOKEN": "tok-1234567890"})
        self.assertFalse(r.ask("rules", "the token is tok-1234567890", schema=decision.DECISION_SCHEMA).ok)
        self.assertEqual(adapter.calls, [])

    def test_ordinary_game_and_market_text_passes_the_guard(self):
        text = ('Game data: {"away":"New York Yankees","home":"Boston Red Sox","lock_utc":"2026-09-20T22:05:00Z",'
                '"markets":{"moneyline":{"sides":{"home":{"avg_price":-120,"best_price":-115}}}}} 8.5 -110 +105')
        self.assertEqual(R.check_prompt(text), [])

    def test_a_key_inside_an_error_message_is_redacted_before_it_is_stored(self):
        cfg = fake_config(("a", None))
        secret = "supersecretvalue99"
        r, _ = self.router(cfg, {"a": [R.AdapterError("error", f"boom {secret} boom")]}, env={"KEY_A": secret})
        self.ask(r)
        self.assertNotIn(secret, self.usage_path.read_text(encoding="utf-8"))


class AnthropicAdapterTests(RouterCase):
    class Msgs:
        def __init__(self, outer):
            self.outer = outer

        def create(self, **kw):
            self.outer.created.append(kw)
            item = self.outer.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

    class Client:
        def __init__(self, script):
            self.script, self.created = list(script), []
            self.messages = AnthropicAdapterTests.Msgs(self)

    @staticmethod
    def message(text=GOOD, tin=900, tout=80, stop="end_turn", write=0, read=0):
        usage = mock.Mock(input_tokens=tin, output_tokens=tout, cache_creation_input_tokens=write,
                          cache_read_input_tokens=read)
        return mock.Mock(content=[mock.Mock(type="thinking", text="hidden"), mock.Mock(type="text", text=text)],
                         usage=usage, stop_reason=stop)

    def anthropic_router(self, script, env=None):
        client = self.Client(script)
        adapter = R.AnthropicAdapter(client_factory=lambda key, timeout: client)
        cfg = R.load_config()
        env = dict({"ANTHROPIC_API_KEY": "sk-ant-test-0000000000"}, **(env or {}))
        r = R.Router(cfg, env=env, adapters={"anthropic": adapter}, usage=self.usage())
        return r, client

    def test_shipped_config_is_haiku_5_5_effort_low_with_the_owners_prices_and_cap(self):
        spec = R.specs_from_config(R.load_config())[0]
        self.assertEqual((spec.id, spec.kind, spec.model, spec.effort), ("anthropic", "anthropic", "claude-haiku-5-5", "low"))
        self.assertEqual((spec.price_in_per_m, spec.price_out_per_m), (0.10, 0.50))
        self.assertTrue(spec.paid and spec.enabled)
        self.assertEqual(spec.env_key, "ANTHROPIC_API_KEY")
        self.assertEqual(R.load_config()["paid_cap"]["default_usd"], 5.0)

    def test_the_request_is_haiku_with_effort_low_and_the_system_prompt_apart_from_the_data(self):
        r, client = self.anthropic_router([self.message()])
        ans = self.ask(r)
        self.assertTrue(ans.ok)
        sent = client.created[0]
        self.assertEqual(sent["model"], "claude-haiku-5-5")
        self.assertEqual(sent["output_config"], {"effort": "low"})
        self.assertEqual(sent["system"], "rules")
        self.assertEqual(sent["messages"], [{"role": "user", "content": "board"}])
        self.assertNotIn("temperature", sent)
        self.assertNotIn("cache_control", sent)
        self.assertAlmostEqual(ans.cost_usd, 900 * 0.10 / 1e6 + 80 * 0.50 / 1e6, places=9)

    def test_a_large_stable_system_prompt_is_cached_at_the_system_block_and_small_ones_are_not(self):
        r, client = self.anthropic_router([self.message(), self.message(write=5000, read=0, tin=100)])
        r.ask("short rules", "board", schema=decision.DECISION_SCHEMA)
        self.assertIsInstance(client.created[0]["system"], str)
        big = "stable rules. " * 500                                   # ~7000 chars: ~1750 tokens, over the 1024 line
        r.ask(big, "volatile board", schema=decision.DECISION_SCHEMA)
        system = client.created[1]["system"]
        self.assertEqual(system, [{"type": "text", "text": big, "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(client.created[1]["messages"][0]["content"], "volatile board")
        self.assertNotIn("cache_control", client.created[1])

    def test_cache_tokens_are_priced_at_their_own_rates(self):
        r, _ = self.anthropic_router([self.message(tin=1000, tout=0, write=2000, read=4000)])
        ans = self.ask(r)
        expected = (1000 * 0.10 + 2000 * 0.10 * 1.25 + 4000 * 0.10 * 0.10) / 1e6
        self.assertAlmostEqual(ans.cost_usd, expected, places=9)

    def test_sdk_errors_are_classified_by_status_and_name(self):
        class E(Exception):
            def __init__(self, status, msg="x", headers=None):
                super().__init__(msg)
                self.status_code = status
                self.response = mock.Mock(headers=headers or {})

        class APITimeoutError(Exception):
            pass

        cases = [(E(429, headers={"retry-after": "120"}), "quota"), (E(402), "quota"), (E(401), "auth"),
                 (E(403), "auth"), (E(500), "error"), (E(529), "error"), (APITimeoutError("t"), "timeout"),
                 (socket.timeout("t"), "timeout"), (E(400, "Your credit balance is too low"), "spend_limit"),
                 (E(400, "bad request"), "error")]
        for exc, kind in cases:
            with self.subTest(type(exc).__name__ + str(getattr(exc, "status_code", ""))):
                self.assertEqual(R.classify_exception(exc).kind, kind)
        self.assertEqual(R.classify_exception(E(429, headers={"retry-after": "120"})).retry_after_s, 120.0)

    def test_a_429_from_the_sdk_puts_haiku_on_cooldown_and_the_answer_is_no_answer(self):
        class RateLimitError(Exception):
            status_code = 429

        r, client = self.anthropic_router([RateLimitError("slow down"), self.message()])
        self.assertFalse(self.ask(r).ok)
        self.assertFalse(self.ask(r).ok)
        self.assertEqual(len(client.created), 1, "the second ask is skipped during the cooldown")
        self.assertTrue(r.degraded())
        self.assertIn("cooling down", r.status()["providers"][0]["blocked_reason"])
        self.clock.advance(minutes=31)
        self.assertTrue(self.ask(r).ok)

    def test_a_refusal_stop_reason_is_not_an_answer(self):
        r, _ = self.anthropic_router([self.message(text="", stop="refusal")])
        ans = self.ask(r)
        self.assertFalse(ans.ok)
        self.assertEqual(ans.attempts[0].status, "refused")

    def test_a_missing_sdk_is_an_error_not_a_crash(self):
        adapter = R.AnthropicAdapter()
        with mock.patch.dict("sys.modules", {"anthropic": None}):
            r = R.Router(R.load_config(), env={"ANTHROPIC_API_KEY": "sk-ant-test-0000000000"},
                         adapters={"anthropic": adapter}, usage=self.usage())
            ans = self.ask(r)
        self.assertFalse(ans.ok)
        self.assertIn("not installed", ans.reason)

    def test_the_resting_line_is_the_owners(self):
        self.assertEqual(R.RESTING_LINE, "My AI brain is resting, here's what my rules say.")


class BatchTests(RouterCase):
    class Batches:
        def __init__(self, outer):
            self.outer = outer

        def create(self, requests):
            self.outer.submitted.append(requests)
            return mock.Mock(id=f"msgbatch_{len(self.outer.submitted)}")

        def retrieve(self, batch_id):
            return mock.Mock(processing_status=self.outer.status)

        def results(self, batch_id):
            return iter(self.outer.entries)

    class Client:
        def __init__(self):
            self.submitted, self.status, self.entries = [], "in_progress", []
            self.messages = mock.Mock(batches=BatchTests.Batches(self))

    @staticmethod
    def entry(cid, text=None, kind="succeeded", tin=1000, tout=100):
        if kind != "succeeded":
            return mock.Mock(custom_id=cid, result=mock.Mock(type=kind, error=mock.Mock(type="server_error")))
        usage = mock.Mock(input_tokens=tin, output_tokens=tout, cache_creation_input_tokens=0, cache_read_input_tokens=0)
        msg = mock.Mock(content=[mock.Mock(type="text", text=text)], usage=usage, stop_reason="end_turn")
        return mock.Mock(custom_id=cid, result=mock.Mock(type="succeeded", message=msg))

    def setUp(self):
        super().setUp()
        self.client = self.Client()
        self.adapter = R.AnthropicAdapter(client_factory=lambda key, timeout: self.client)

    def batch_router(self, cap=5):
        return R.Router(R.load_config(), env={"ANTHROPIC_API_KEY": "sk-ant-test-0000000000", "AI_PAID_CAP_USD": str(cap)},
                        adapters={"anthropic": self.adapter}, usage=self.usage())

    def jobs(self):
        return [R.BatchJob("recap-a", "write a recap", "game a"), R.BatchJob("recap-b", "write a recap", "game b"),
                R.BatchJob("recap-c", "write a recap", "game c")]

    def test_submit_sends_every_job_with_its_custom_id_and_reserves_half_price_worst_case(self):
        r = self.batch_router()
        sub = r.submit_batch(self.jobs(), purpose="recaps")
        self.assertTrue(sub.ok, sub.reason)
        sent = self.client.submitted[0]
        self.assertEqual([x["custom_id"] for x in sent], ["recap-a", "recap-b", "recap-c"])
        self.assertEqual(sent[0]["params"]["model"], "claude-haiku-5-5")
        self.assertEqual(sent[0]["params"]["output_config"], {"effort": "low"})
        spec = r.specs[0]
        full = sum(r.estimate_cost(spec, j.system, j.user, spec.max_tokens) for j in self.jobs())
        self.assertAlmostEqual(sub.reserved_usd, full * 0.5, places=8)
        self.assertAlmostEqual(r.paid_spend(), sub.reserved_usd, places=8)
        self.assertEqual(r.usage.open_batches(), [sub.batch_id])
        self.assertEqual(sub.batch_id, "msgbatch_1")

    def test_results_come_back_in_any_order_and_are_keyed_by_custom_id_never_position(self):
        r = self.batch_router()
        jobs = self.jobs()
        sub = r.submit_batch(jobs)
        self.client.status = "ended"
        self.client.entries = [self.entry("recap-c", "third"), self.entry("recap-a", "first"), self.entry("recap-b", "second")]
        out = r.collect_batch(sub.batch_id, jobs)
        self.assertTrue(out.done)
        self.assertEqual({k: v.output for k, v in out.results.items()},
                         {"recap-a": {"text": "first"}, "recap-b": {"text": "second"}, "recap-c": {"text": "third"}})

    def test_batch_spend_counts_at_fifty_percent_and_is_billed_once(self):
        r = self.batch_router()
        jobs = self.jobs()
        sub = r.submit_batch(jobs)
        self.client.status = "ended"
        self.client.entries = [self.entry(j.custom_id, "x", tin=1_000_000, tout=1_000_000) for j in jobs]
        out = r.collect_batch(sub.batch_id, jobs)
        self.assertAlmostEqual(out.cost_usd, 3 * 0.60 * 0.5, places=6)      # $0.60 per full-price job, halved
        self.assertAlmostEqual(r.paid_spend(), out.cost_usd, places=6)      # reservation released, actual counted
        self.assertEqual(r.usage.open_batches(), [])
        again = r.collect_batch(sub.batch_id, jobs)
        self.assertTrue(again.already_billed)
        self.assertEqual(sorted(again.results), ["recap-a", "recap-b", "recap-c"])
        self.assertAlmostEqual(r.paid_spend(), out.cost_usd, places=6, msg="a second read must not bill again")

    def test_a_batch_that_would_cross_the_cap_is_refused_whole_and_nothing_is_sent(self):
        r = self.batch_router(cap=0.0005)
        sub = r.submit_batch(self.jobs())
        self.assertFalse(sub.ok)
        self.assertIn("cap", sub.reason)
        self.assertEqual(self.client.submitted, [])

    def test_an_open_batchs_reservation_counts_against_a_realtime_call(self):
        r = self.batch_router(cap=0.0020)
        self.assertTrue(r.submit_batch(self.jobs()).ok)
        reserved = r.paid_spend()
        self.assertGreater(reserved, 0.0005)
        self.assertFalse(r.skip_reason(r.specs[0], 0.0015) is None, "reservation + a normal call would cross the cap")

    def test_not_ended_is_not_done_and_bills_nothing(self):
        r = self.batch_router()
        sub = r.submit_batch(self.jobs())
        out = r.collect_batch(sub.batch_id)
        self.assertEqual((out.done, out.status, out.results), (False, "in_progress", {}))

    def test_wait_for_batch_polls_until_ended_then_stops_and_a_deadline_returns_not_done(self):
        r = self.batch_router()
        jobs = self.jobs()
        sub = r.submit_batch(jobs)
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 3:
                self.client.status = "ended"
                self.client.entries = [self.entry(j.custom_id, "t") for j in jobs]

        out = r.wait_for_batch(sub.batch_id, jobs, poll_seconds=30, max_wait_seconds=600, sleep=sleep)
        self.assertTrue(out.done)
        self.assertEqual(sleeps, [30, 30, 30])
        self.assertEqual(sorted(out.results), ["recap-a", "recap-b", "recap-c"])
        # a batch that never ends: the deadline returns, the reservation stays, nothing is billed
        self.client.status = "in_progress"
        sub2 = r.submit_batch([R.BatchJob("later-1", "s", "u")])
        late = r.wait_for_batch(sub2.batch_id, poll_seconds=100, max_wait_seconds=250, sleep=lambda s: None)
        self.assertFalse(late.done)
        self.assertEqual(r.usage.open_batches(), [sub2.batch_id])

    def test_errored_and_expired_items_are_failures_not_answers(self):
        r = self.batch_router()
        jobs = self.jobs()
        sub = r.submit_batch(jobs)
        self.client.status = "ended"
        self.client.entries = [self.entry("recap-a", "ok"), self.entry("recap-b", kind="errored"), self.entry("recap-c", kind="expired")]
        out = r.collect_batch(sub.batch_id, jobs)
        self.assertEqual([out.results[k].ok for k in ("recap-a", "recap-b", "recap-c")], [True, False, False])

    def test_duplicate_or_bad_custom_ids_and_pii_are_refused(self):
        r = self.batch_router()
        self.assertFalse(r.submit_batch([R.BatchJob("x", "s", "u"), R.BatchJob("x", "s", "u")]).ok)
        self.assertFalse(r.submit_batch([R.BatchJob("has space", "s", "u")]).ok)
        self.assertFalse(r.submit_batch([R.BatchJob("p", "s", "mail brey@example.com")]).ok)
        self.assertEqual(self.client.submitted, [])


class UsageStoreTests(unittest.TestCase):
    def test_incremental_reads_see_another_writer_and_wait_for_a_torn_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            path = Path(tmp) / "u.jsonl"
            a, b = UsageStore(path, clock=clock), UsageStore(path, clock=clock)
            a.record_call(provider="p", model="m", status="ok", cost_usd=0.25)
            self.assertEqual(b.month_spend("p"), 0.25)
            b.record_call(provider="p", model="m", status="ok", cost_usd=0.25)
            self.assertEqual(a.month_spend("p"), 0.5)
            with path.open("ab") as fh:
                fh.write(b'{"kind":"call","provider":"p","status":"ok","cost_usd":9')          # a crash mid-write
            self.assertEqual(a.month_spend("p"), 0.5)
            self.assertEqual(a.calls_today("p"), 2)


if __name__ == "__main__":
    unittest.main()
