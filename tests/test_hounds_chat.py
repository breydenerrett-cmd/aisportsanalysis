"""Talk to your hound (owner request 2026-10-28): src/hounds/chat, src/ai/hound_chat.py and api/hounds_chat.py.

Pinned here, each one written to fail on the code before the chat existed (there was no chat at all):

  history      what is said persists per member and hound LINEAGE and reloads; only a bounded window goes to the model
  who          only the owner chats; a stranger's hound, a house hound and an unknown id are all a 404 and never reach a model
  limits       free 20 / paid 100 a day, taken before the model and given back when the model fails; clearing the chat resets nothing;
               no key says "unavailable"; the shared AI cap, the chat's own monthly ceiling and the daily call ceiling stop a turn
  law          a proposed change is applied to a COPY and checked: -200 or worse, more than MAX_RULES rules and an unknown condition are
               refused, with one chance to fix and then a plain "I can't, and why"
  apply        nothing changes until Apply; Apply makes version n+1 (origin owner_chat, reason quoting the request); Cancel changes nothing
  styles       a Gematria hound may change its sports, bets a day and stake and nothing else; an Apprentice is offered no tools
  the call     Haiku 5.5 only, adaptive thinking, no budget_tokens / temperature / prefill, strict tools, a cached stable prefix, the cost
               written into the router's usage store so the shared cap sees it, and no secret anywhere in a log or a payload

No network, no real model: the client is a fake that returns what a test scripts.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.ai import hound_chat
from src.ai import router as router_mod
from src.appstate import users as users_store
from src.hounds import stats, user_engine, user_rules, user_spec, user_store
from src.hounds.chat import facts as facts_mod
from src.hounds.chat import proposals, service, store
from src.hounds.interact import common
from tests._hounds_rules_fixtures import rule as make_rule, v2 as make_v2
from tests._hounds_user_fixtures import spec_dict, utc

REPO = Path(__file__).resolve().parent.parent
NOW = utc("2026-10-20T21:30:00Z")
CREATED = utc("2026-10-19T12:00:00Z")
KEY = "sk-ant-test-0123456789abcdef"
ENV = {"ANTHROPIC_API_KEY": KEY, "AI_PAID_CAP_USD": "5"}
CATALOG = "[]"                       # the catalog is exercised in its own test; a short one keeps every other request small


# ---------------------------------------------------------------------------------------------------------------------
# a fake model
# ---------------------------------------------------------------------------------------------------------------------

def reply(text="", tools=(), usage=(3000, 150, 0, 0), stop=None):
    """What ``messages.create`` returns: a thinking block (hidden text, as Haiku 5.5 sends it), the text, then any tool calls."""
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    for n, (name, args) in enumerate(tools):
        content.append(SimpleNamespace(type="tool_use", id=f"toolu_{n}_{name}", name=name, input=args))
    u = SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1], cache_creation_input_tokens=usage[2], cache_read_input_tokens=usage[3])
    return SimpleNamespace(content=content, stop_reason=stop or ("tool_use" if tools else "end_turn"), usage=u)


class FakeClient:
    """``script`` is a list of replies (or exceptions, or callables of the request); the last one repeats."""

    def __init__(self, *script):
        self.script = list(script) or [reply("Woof.")]
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(dict(kw, messages=[dict(m) for m in kw["messages"]]))
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if callable(step):
            step = step(kw)
        if isinstance(step, Exception):
            raise step
        return step


class RateLimited(Exception):
    status_code = 429


def tool_results(call):
    """The tool_result blocks of the last user message of a request."""
    last = call["messages"][-1]
    return last["content"] if isinstance(last["content"], list) else []


# ---------------------------------------------------------------------------------------------------------------------
# the base: a temp app database with an owner, a stranger and one hound
# ---------------------------------------------------------------------------------------------------------------------

class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        self.ledger = str(tmp / "hounds_user_v1.jsonl")
        for p in (mock.patch.object(users_store, "db_path", lambda: self.db),
                  mock.patch.object(user_engine, "ledger_path", lambda path=None: path or self.ledger),
                  mock.patch.object(stats, "refresh_async", lambda *a, **k: False),
                  mock.patch.object(stats, "peek_book", lambda: None),
                  mock.patch.object(stats, "get_book_nowait", lambda *a, **k: (None, "warming")),
                  mock.patch.object(common, "now_utc", lambda: NOW)):
            p.start()
            self.addCleanup(p.stop)
        self.owner = users_store.create_user("owner@example.com", status="active", db=self.db)
        self.other = users_store.create_user("other@example.com", status="active", db=self.db)
        self.hound = user_store.create_hound(self.owner.id, spec_dict(name="Dog Days", side_rule="underdog"), now=CREATED)
        self.id = self.hound["id"]
        self.router = router_mod.Router(config=router_mod.load_config(), env=ENV, usage_path=tmp / "usage.jsonl")

    def send(self, text, client, user=None, paid=False, hound_id=None, env=None, **over):
        kw = dict(now=NOW, db=self.db, env=ENV if env is None else env, router=self.router, client=client, catalog=CATALOG)
        kw.update(over)
        return service.send((user or self.owner).id, paid, hound_id or self.id, text, **kw)

    def open(self, user=None, paid=False, hound_id=None, env=None):
        return service.open_chat((user or self.owner).id, paid, hound_id or self.id, now=NOW, db=self.db,
                                 env=ENV if env is None else env, router=self.router)

    def tool_turn(self, text, tools, closing="Tap Apply to make it so.", client=None, **over):
        client = client or FakeClient(reply("", tools), reply(closing))
        return self.send(text, client, **over), client

    def lineage(self):
        return user_store.lineage(self.id, db=self.db)

    def current(self):
        return self.lineage()[-1]

    def make_hound(self, spec, owner=None, name=None):
        return user_store.create_hound((owner or self.owner).id, spec, now=CREATED, db=self.db)

    def err(self, fn, *a, **k):
        with self.assertRaises(service.ChatError) as ctx:
            fn(*a, **k)
        return ctx.exception


# ---------------------------------------------------------------------------------------------------------------------
class History(Base):
    def test_what_is_said_persists_and_reloads_in_order(self):
        client = FakeClient(reply("Two bets so far."), reply("Short prices lose me money."))
        first = self.send("How am I doing?", client)
        self.send("Why?", client)
        self.assertEqual([m["role"] for m in first["messages"]], ["member", "hound"])
        opened = self.open()
        self.assertEqual([(m["role"], m["text"]) for m in opened["messages"]],
                         [("member", "How am I doing?"), ("hound", "Two bets so far."), ("member", "Why?"), ("hound", "Short prices lose me money.")])
        self.assertEqual(opened["hound"]["name"], "Dog Days")

    def test_the_second_message_carries_the_first_exchange_to_the_model(self):
        client = FakeClient(reply("Two bets so far."), reply("Because."))
        self.send("How am I doing?", client)
        self.send("Why?", client)
        sent = client.calls[1]["messages"]
        self.assertEqual([(m["role"], m["content"]) for m in sent],
                         [("user", "How am I doing?"), ("assistant", "Two bets so far."), ("user", "Why?")])

    def test_the_conversation_follows_the_hound_across_versions(self):
        client = FakeClient(reply("hello"))
        self.send("Hi", client)
        v2 = user_store.create_version(self.id, spec_dict(name="Dog Days", side_rule="underdog", max_bets_per_day=1), actor="owner", reason="edit",
                                       now=CREATED, db=self.db)
        opened = service.open_chat(self.owner.id, False, v2["id"], now=NOW, db=self.db, env=ENV, router=self.router)
        self.assertEqual([m["text"] for m in opened["messages"]], ["Hi", "hello"])
        old = service.open_chat(self.owner.id, False, self.id, now=NOW, db=self.db, env=ENV, router=self.router)
        self.assertEqual(old["hound"]["id"], v2["id"], "an old version's id talks to the hound as it is now")

    def test_only_a_bounded_window_goes_to_the_model(self):
        root = self.hound["root_id"]
        for i in range(60):
            store.add_message(self.owner.id, root, self.id, 1, store.ROLE_MEMBER if i % 2 == 0 else store.ROLE_HOUND, f"line {i}", db=self.db)
        client = FakeClient(reply("ok"))
        self.send("latest", client)
        sent = client.calls[0]["messages"]
        self.assertLessEqual(len(sent), service.HISTORY_WINDOW + 1)
        self.assertEqual(sent[0]["role"], "user", "a conversation opens on the member")
        self.assertEqual(sent[-1], {"role": "user", "content": "latest"})
        self.assertEqual(sent[-2]["content"], "line 59")
        self.assertNotIn("line 0", [m["content"] for m in sent])

    def test_notices_are_shown_but_never_sent_to_the_model(self):
        root = self.hound["root_id"]
        store.add_message(self.owner.id, root, self.id, 1, store.ROLE_MEMBER, "hi", db=self.db)
        store.add_message(self.owner.id, root, self.id, 1, store.ROLE_NOTICE, "Cancelled. No change was made.", db=self.db)
        client = FakeClient(reply("ok"))
        self.send("again", client)
        self.assertNotIn("Cancelled", json.dumps(client.calls[0]["messages"]))
        self.assertIn("Cancelled. No change was made.", [m["text"] for m in self.open()["messages"]])

    def test_clear_chat_deletes_the_conversation_and_nothing_else(self):
        self.send("Hi", FakeClient(reply("hello")))
        out = service.clear_chat(self.owner.id, self.id, db=self.db)
        self.assertEqual(out["cleared"], 2)
        self.assertEqual(self.open()["messages"], [])
        self.assertEqual(len(self.lineage()), 1)

    def test_the_tables_are_made_idempotently_and_the_history_is_trimmed(self):
        store.ensure(self.db)
        store.ensure(self.db)
        root = self.hound["root_id"]
        with mock.patch.object(store, "KEEP_PER_LINEAGE", 5):
            for i in range(9):
                store.add_message(self.owner.id, root, self.id, 1, store.ROLE_MEMBER, f"m{i}", db=self.db)
        self.assertEqual([m["text"] for m in store.history(self.owner.id, root, db=self.db)], ["m4", "m5", "m6", "m7", "m8"])


# ---------------------------------------------------------------------------------------------------------------------
class OwnerOnly(Base):
    def test_a_stranger_gets_not_found_everywhere_and_no_model_is_called(self):
        client = FakeClient(reply("secret"))
        for call in (lambda: self.open(user=self.other), lambda: self.send("hi", client, user=self.other),
                     lambda: service.clear_chat(self.other.id, self.id, db=self.db),
                     lambda: service.apply_proposal(self.other.id, self.id, 1, db=self.db),
                     lambda: service.cancel_proposal(self.other.id, self.id, 1, db=self.db)):
            exc = self.err(call)
            self.assertEqual((exc.status, exc.code), (404, "not_found"))
        self.assertEqual(client.calls, [])
        self.assertEqual(store.used_today(self.other.id, now=NOW, db=self.db), 0)

    def test_a_house_hound_and_an_unknown_id_have_no_chat(self):
        client = FakeClient(reply("x"))
        for hid in ("chalk_chihuahua", "no-such-hound", "../etc"):
            self.assertEqual(self.err(self.send, "hi", client, hound_id=hid).status, 404, hid)
        self.assertEqual(client.calls, [])

    def test_a_hound_removed_from_the_kennel_is_gone(self):
        user_store.retire_hound(self.id, by=f"owner:{self.owner.id}", reason="removed from the kennel by its owner", db=self.db)
        self.assertEqual(self.err(self.open).status, 404)

    def test_a_buried_hound_can_be_talked_to_but_is_given_no_tools(self):
        client = FakeClient(reply("I'm resting."))
        with mock.patch.object(user_store, "get_hound", wraps=user_store.get_hound):
            row = copy.deepcopy(self.current())
        row["status"] = user_store.STATUS_BURIED
        with mock.patch.object(service, "resolve", lambda uid, hid, db=None: (common.resolve(self.id), row)):
            self.send("How are you?", client)
        self.assertNotIn("tools", client.calls[0], "a buried hound cannot be edited, so it has no edit tools")
        self.assertIn("buried", client.calls[0]["system"][1]["text"])


# ---------------------------------------------------------------------------------------------------------------------
class Limits(Base):
    def test_the_constants_are_the_owners(self):
        self.assertEqual((service.FREE_MESSAGES_PER_DAY, service.PAID_MESSAGES_PER_DAY), (20, 100))
        self.assertEqual((service.limit_for(False), service.limit_for(True)), (20, 100))

    def test_the_day_is_enforced_and_a_refusal_never_reaches_the_model(self):
        client = FakeClient(reply("ok"))
        with mock.patch.object(service, "FREE_MESSAGES_PER_DAY", 3):
            for i in range(3):
                self.send(f"q{i}", client)
            exc = self.err(self.send, "q3", client)
            self.assertEqual((exc.status, exc.code), (429, "daily_limit"))
            self.assertEqual((exc.extra["used"], exc.extra["limit"]), (3, 3))
            self.assertEqual(len(client.calls), 3)
            self.assertEqual(self.open()["limits"]["left_today"], 0)

    def test_a_paid_account_has_the_larger_day(self):
        client = FakeClient(reply("ok"))
        with mock.patch.object(service, "FREE_MESSAGES_PER_DAY", 1), mock.patch.object(service, "PAID_MESSAGES_PER_DAY", 2):
            self.send("a", client, paid=True)
            self.send("b", client, paid=True)
            self.assertEqual(self.err(self.send, "c", client, paid=True).code, "daily_limit")
            self.assertEqual(self.open(paid=True)["limits"]["limit_per_day"], 2)

    def test_clearing_the_chat_does_not_reset_the_day(self):
        client = FakeClient(reply("ok"))
        with mock.patch.object(service, "FREE_MESSAGES_PER_DAY", 2):
            self.send("a", client)
            self.send("b", client)
            service.clear_chat(self.owner.id, self.id, db=self.db)
            self.assertEqual(self.err(self.send, "c", client).code, "daily_limit")

    def test_the_day_rolls_over_at_midnight_utc(self):
        client = FakeClient(reply("ok"))
        with mock.patch.object(service, "FREE_MESSAGES_PER_DAY", 1):
            self.send("a", client)
            self.assertEqual(self.err(self.send, "b", client).code, "daily_limit")
            self.send("c", client, now=utc("2026-10-21T00:05:00Z"))

    def test_a_turn_that_fails_is_given_back_and_nothing_is_saved(self):
        with mock.patch.object(service, "FREE_MESSAGES_PER_DAY", 1):
            exc = self.err(self.send, "a", FakeClient(RuntimeError("boom")))
            self.assertEqual((exc.status, exc.code), (502, "model_failed"))
            self.assertEqual(self.open()["messages"], [])
            self.assertEqual(self.open()["limits"]["left_today"], 1)
            self.send("a", FakeClient(reply("ok")))                      # the one message is still there to use

    def test_two_taps_at_once_cannot_both_take_the_last_message(self):
        a = store.begin_turn(self.owner.id, "root", "h", 1, now=NOW, db=self.db)
        with self.assertRaises(store.CapReached):
            store.begin_turn(self.owner.id, "root", "h", 1, now=NOW, db=self.db)
        store.finish_turn(a, store.STATE_FAILED, db=self.db)
        store.begin_turn(self.owner.id, "root", "h", 1, now=NOW, db=self.db)

    def test_no_key_says_unavailable_and_spends_nothing(self):
        client = FakeClient(reply("x"))
        exc = self.err(self.send, "hi", client, env={})
        self.assertEqual((exc.status, exc.code), (503, "unavailable"))
        self.assertEqual(client.calls, [])
        self.assertEqual(store.used_today(self.owner.id, now=NOW, db=self.db), 0)
        opened = self.open(env={})
        self.assertFalse(opened["available"])
        self.assertEqual(opened["reason"], service.UNAVAILABLE_TEXT)
        self.assertTrue(self.open()["available"])

    def test_a_missing_package_is_unavailable_not_a_crash(self):
        def factory(key):
            raise ImportError("no anthropic")
        exc = self.err(self.send, "hi", None, client_factory=factory)
        self.assertEqual(exc.code, "unavailable")
        self.assertEqual(self.open()["limits"]["left_today"], service.FREE_MESSAGES_PER_DAY)

    def test_a_message_with_an_email_or_a_key_in_it_is_refused_before_the_model(self):
        client = FakeClient(reply("x"))
        for text in ("mail me at brey@example.com", "call 555-123-4567 now", f"my key is {KEY}"):
            self.assertEqual(self.err(self.send, text, client).code, "private_info", text)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.open()["limits"]["left_today"], service.FREE_MESSAGES_PER_DAY)

    def test_an_empty_or_long_message_is_refused(self):
        client = FakeClient(reply("x"))
        self.assertEqual(self.err(self.send, "   ", client).code, "message_required")
        self.assertEqual(self.err(self.send, "x" * (service.MESSAGE_MAX_CHARS + 1), client).code, "message_too_long")
        self.assertEqual(client.calls, [])

    def test_the_shared_ai_cap_stops_a_turn_before_the_model(self):
        self.router.usage.record_call(provider="anthropic", model="claude-haiku-5-5", status="ok", cost_usd=4.9999, purpose="ai_hound")
        client = FakeClient(reply("x"))
        exc = self.err(self.send, "hi", client)
        self.assertEqual((exc.status, exc.code), (503, "resting"))
        self.assertEqual(client.calls, [])
        self.assertEqual(self.open()["limits"]["left_today"], service.FREE_MESSAGES_PER_DAY)
        self.assertFalse(self.open()["available"])

    def test_the_chats_own_monthly_ceiling_sits_under_the_shared_cap(self):
        client = FakeClient(reply("x"))
        self.send("one", FakeClient(reply("ok", usage=(3000, 150, 0, 0))))
        self.assertGreater(store.month_spend(now=NOW, db=self.db), 0)
        env = dict(ENV, **{service.MONTHLY_CHAT_ENV: str(store.month_spend(now=NOW, db=self.db))})
        exc = self.err(self.send, "two", client, env=env)
        self.assertEqual(exc.code, "resting")
        self.assertEqual(client.calls, [])

    def test_the_meter_is_checked_before_every_round_not_only_the_first(self):
        huge = reply("", [("propose_bets_per_day", {"bets_per_day": 1})], usage=(10_000_000, 0, 0, 0))        # $5.00 at the long-prompt price
        client = FakeClient(huge, reply("Tap Apply."))
        exc = self.err(self.send, "bet fewer", client)
        self.assertEqual((exc.status, exc.code), (503, "resting"))
        self.assertEqual(len(client.calls), 1, "the second round was never made")
        self.assertEqual(self.open()["messages"], [])
        self.assertEqual(self.open()["limits"]["left_today"], service.FREE_MESSAGES_PER_DAY, "a turn the member got nothing from is given back")
        self.assertGreaterEqual(self.router.paid_spend(), 5.0, "the round that was made is on the meter")
        self.assertGreater(store.month_spend(now=NOW, db=self.db), 0, "and in the chat's own month, failed or not")

    def test_chat_cannot_use_up_the_daily_calls_the_ai_hounds_share(self):
        client = FakeClient(reply("ok"))
        with mock.patch.object(service, "CHAT_CALLS_PER_DAY_ALL", 2):
            self.send("a", client)
            self.send("b", client)
            self.assertEqual(self.err(self.send, "c", client).code, "resting")

    def test_a_429_cools_the_provider_down_for_everyone(self):
        exc = self.err(self.send, "hi", FakeClient(RateLimited("slow down")))
        self.assertEqual(exc.code, "model_failed")
        self.assertIsNotNone(self.router.usage.cooldown("anthropic"))
        self.assertEqual(self.err(self.send, "again", FakeClient(reply("x"))).code, "resting")

    def test_the_spend_lands_in_the_routers_usage_store_so_the_shared_cap_sees_it(self):
        before = self.router.paid_spend()
        out = self.send("hi", FakeClient(reply("ok", usage=(4000, 200, 0, 0))))
        expected = (4000 * 0.10 + 200 * 0.50) / 1e6
        self.assertAlmostEqual(out["cost_usd"], expected, places=8)
        self.assertAlmostEqual(self.router.paid_spend() - before, expected, places=8)
        row = json.loads(Path(self.router.usage.path).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((row["provider"], row["model"], row["purpose"], row["status"]), ("anthropic", "claude-haiku-5-5", "hound_chat", "ok"))


# ---------------------------------------------------------------------------------------------------------------------
class TheCall(Base):
    def test_the_request_is_haiku_only_with_adaptive_thinking_and_none_of_the_removed_parameters(self):
        client = FakeClient(reply("ok"))
        self.send("hi", client)
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-haiku-5-5")
        self.assertEqual(call["thinking"], {"type": "adaptive"})
        self.assertEqual(call["output_config"], {"effort": "low"})
        for banned in ("temperature", "top_p", "top_k", "budget_tokens"):
            self.assertNotIn(banned, json.dumps(call, default=str), banned)
        self.assertEqual(call["messages"][-1]["role"], "user", "no assistant prefill")
        self.assertLessEqual(call["max_tokens"], 4000)

    def test_the_stable_prefix_is_cached_and_the_hounds_own_block_follows_it(self):
        client = FakeClient(reply("ok"))
        self.send("hi", client)
        system = client.calls[0]["system"]
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", system[1])
        self.assertIn("YOUR NAME: Dog Days", system[1]["text"])
        self.assertNotIn("Dog Days", system[0]["text"], "nothing about one hound in the cached prefix, or no two hounds could share it")

    def test_every_tool_is_a_strict_client_tool(self):
        client = FakeClient(reply("ok"))
        self.send("hi", client)
        tools = client.calls[0]["tools"]
        self.assertEqual([t["name"] for t in tools], ["propose_bets_per_day", "propose_stake_units", "propose_price_band", "propose_add_sports", "propose_remove_sports", "propose_rule_change"])
        for tool in tools:
            self.assertIs(tool["strict"], True)
            schema = tool["input_schema"]
            self.assertIs(schema["additionalProperties"], False)
            self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]), "strict schemas list every property as required")

    def test_cost_is_worked_out_from_the_apis_own_usage_including_the_cache(self):
        msg = reply("x", usage=(1000, 100, 2000, 3000))
        cost, tin, write, read, tout = hound_chat.message_cost(msg, worst=9.0)
        self.assertEqual((tin, write, read, tout), (1000, 2000, 3000, 100))
        self.assertAlmostEqual(cost, (1000 * 0.10 + 2000 * 0.10 * 1.25 + 3000 * 0.10 * 0.10 + 100 * 0.50) / 1e6, places=9)
        self.assertEqual(hound_chat.message_cost(SimpleNamespace(content=[], usage=None, stop_reason="end_turn"), worst=0.0123)[0], 0.0123,
                         "usage missing: the round is charged its worst case, never zero")

    def test_a_typical_message_costs_a_fraction_of_a_cent(self):
        out = self.send("hi", FakeClient(reply("ok", usage=(7000, 600, 0, 0))))
        self.assertLess(out["cost_usd"], 0.005)

    def test_a_refusal_is_not_shown_as_an_answer(self):
        exc = self.err(self.send, "hi", FakeClient(reply("", stop="refusal")))
        self.assertEqual(exc.code, "model_failed")
        self.assertEqual(self.open()["messages"], [])

    def test_a_cut_off_answer_is_not_saved(self):
        exc = self.err(self.send, "hi", FakeClient(reply("The rule I ha", stop="max_tokens")))
        self.assertEqual(exc.code, "model_failed")

    def test_no_secret_reaches_a_log_a_payload_or_the_error_text(self):
        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler = Grab()
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.DEBUG)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        boom = RuntimeError(f"auth failed for {KEY}")
        exc = self.err(self.send, "hi", FakeClient(boom))
        self.send("hi", FakeClient(reply("ok")))
        self.assertNotIn(KEY, str(exc))
        self.assertTrue(records)
        self.assertFalse([r for r in records if KEY in r], "the key is in a log line")
        usage_text = Path(self.router.usage.path).read_text(encoding="utf-8")
        self.assertNotIn(KEY, usage_text)
        self.assertNotIn(KEY, json.dumps(self.open(), default=str))

    def test_chat_adds_no_model_client_to_the_interact_package(self):
        for path in (REPO / "src" / "hounds" / "interact").glob("*.py"):
            self.assertNotIn("hound_chat", path.read_text(encoding="utf-8"), path.name)
        self.assertNotIn("import anthropic", (REPO / "src" / "ai" / "hound_chat.py").read_text(encoding="utf-8"),
                         "the SDK is imported lazily, in src/ai/sdk_client.py")

    def test_the_thinking_blocks_go_back_whole_inside_a_tool_loop(self):
        client = FakeClient(reply("", [("propose_bets_per_day", {"bets_per_day": 1})]), reply("Tap Apply."))
        self.send("bet less", client)
        assistant = client.calls[1]["messages"][-2]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual([getattr(b, "type") for b in assistant["content"]], ["thinking", "tool_use"])
        self.assertEqual(tool_results(client.calls[1])[0]["tool_use_id"], "toolu_0_propose_bets_per_day")


# ---------------------------------------------------------------------------------------------------------------------
class Grounding(Base):
    def test_the_system_prompt_forbids_inventing_and_names_the_words_to_avoid(self):
        text = facts_mod.stable_system(CATALOG)
        for needle in ("I don't have that", "NEVER counts", "paper money", "tap Apply", "-200", "at most 4 rules", "hound"):
            self.assertIn(needle, text)
        self.assertIn("Never mention Bet Check", text)

    def test_the_hound_block_holds_only_this_hounds_data(self):
        client = FakeClient(reply("ok"))
        other = self.make_hound(spec_dict(name="Rival Rex", side_rule="favourite", price_min=-190, price_max=-110), owner=self.other)
        self.send("hi", client)
        block = client.calls[0]["system"][1]["text"]
        self.assertIn("YOUR NAME: Dog Days", block)
        self.assertIn("YOUR RULE IN PLAIN ENGLISH", block)
        self.assertIn("NOT PROVIDED TO YOU", block)
        for stranger in ("Rival Rex", "other@example.com", "owner@example.com", other["id"]):
            self.assertNotIn(stranger, block)
        self.assertNotIn("owner@example.com", json.dumps(client.calls[0], default=str))

    def test_the_record_and_each_bet_with_its_reason_are_in_the_block_and_a_rehearsal_is_labelled_never_counted(self):
        summary = {"record": {"bets": 3, "wins": 2, "losses": 1, "pushes": 0, "units_average_price": 1.75}, "open_bets": 1,
                   "replay": {"bets": 12, "wins": 5, "losses": 7, "pushes": 0, "units_recorded_price": -3.2, "note": "Replay: never counted in the verdict."},
                   "verdict": {"label": "TOO EARLY"}}
        tickets = [{"date": "2026-10-19", "game": "Boston Red Sox at Seattle Mariners", "selection": "Boston Red Sox to win", "price": 120, "result": "win",
                    "units": 1.2, "reason": "Underdog in range, 5 books quoting."}]
        facts = facts_mod.collect(common.resolve(self.id), self.current(), now=NOW, db=self.db)
        facts.update(summary=summary, tickets=tickets)
        text = facts_mod.render(facts)
        self.assertIn("settled 3: 2 wins, 1 losses, 0 pushes", text)
        self.assertIn("+1.75 units at the average price", text)
        self.assertIn("2026-10-19 | Boston Red Sox at Seattle Mariners | Boston Red Sox to win | +120 | win | +1.20 | Underdog in range, 5 books quoting.", text)
        self.assertIn("small sample", text)
        self.assertRegex(text, r"REHEARSAL .*hindsight, NEVER counted")
        self.assertIn("12 graded in the replay", text)
        self.assertLess(text.index("FORWARD RECORD"), text.index("REHEARSAL"))

    def test_with_no_numbers_yet_the_block_says_so_instead_of_inventing_any(self):
        facts = facts_mod.collect(common.resolve(self.id), self.current(), now=NOW, db=self.db)
        facts.update(summary=None, tickets=[])
        text = facts_mod.render(facts)
        self.assertIn("(no bets yet)", text)
        self.assertIn("you have no numbers for it yet", text)
        self.assertIn("none was run for this hound", text)

    def test_the_hound_speaks_in_its_own_voice(self):
        facts = facts_mod.collect(common.resolve(self.id), self.current(), now=NOW, db=self.db)
        self.assertIn("long shots", facts["voice"])           # an underdog rule: the underdog voice
        self.assertIn(facts["voice"], facts_mod.render(facts))

    def test_the_catalog_is_in_the_stable_prefix_and_is_the_real_one(self):
        text = facts_mod.stable_system()
        self.assertIn('"id":"role"', text)
        self.assertEqual(text, facts_mod.stable_system(), "byte-identical between calls, or it cannot be cached")

    def test_a_dog_in_the_models_words_is_a_hound_in_the_page(self):
        self.assertEqual(service.scrub("My dog is a good dog. Dogs bet. Dog days."), "My hound is a good hound. Hounds bet. Hound days.")
        out = self.send("hi", FakeClient(reply("Your dog likes long shots.")))
        self.assertEqual(out["messages"][1]["text"], "Your hound likes long shots.")


# ---------------------------------------------------------------------------------------------------------------------
class TheLaw(Base):
    """What a proposed change must pass. Every one of these is refused whole; a refusal comes back to the model as a tool error."""

    def refused(self, tools, closing="I can't do that."):
        client = FakeClient(reply("", tools), reply("", tools), reply(closing))
        out = self.send("change it", client)
        return out, client

    def test_a_price_at_minus_200_is_refused_and_nothing_is_proposed(self):
        out, client = self.refused([("propose_price_band", {"price_min": -200, "price_max": 100, "rules": []})])
        results = tool_results(client.calls[1])
        self.assertTrue(results[0]["is_error"])
        self.assertIn("-200", results[0]["content"])
        self.assertIsNone(out["messages"][1]["proposal"])
        self.assertEqual(len(self.lineage()), 1)

    def test_minus_200_is_refused_inside_a_whole_rule_set_too(self):
        bad = make_v2(name="Dog Days", rules=[make_rule(price_min=-250, price_max=-110)])
        out, client = self.refused([("propose_rule_change", {"rules_json": json.dumps(bad)})])
        self.assertTrue(tool_results(client.calls[1])[0]["is_error"])
        self.assertIsNone(out["messages"][1]["proposal"])

    def test_the_hand_check_holds_even_if_the_builders_gate_were_loosened(self):
        spec = copy.deepcopy(proposals.v2_of(self.current()["spec"]))
        spec["rules"][0]["price_min"] = -200
        with self.assertRaises(proposals.Refusal) as ctx:
            proposals.check_law(spec)
        self.assertIn("never allowed", str(ctx.exception))

    def test_more_than_the_most_rules_is_refused(self):
        five = make_v2(name="Dog Days", rules=[make_rule(price_min=100 + i * 10, price_max=300 + i * 10) for i in range(user_rules.MAX_RULES + 1)])
        out, client = self.refused([("propose_rule_change", {"rules_json": json.dumps(five)})])
        content = tool_results(client.calls[1])[0]["content"]
        self.assertTrue(tool_results(client.calls[1])[0]["is_error"])
        self.assertIn(f"at most {user_rules.MAX_RULES} rules", content)
        self.assertEqual(len(self.lineage()), 1)

    def test_a_condition_that_is_not_in_the_catalog_is_refused(self):
        bad = make_v2(name="Dog Days", rules=[make_rule(when={"op": "all", "items": [{"id": "not_a_condition"}]})])
        out, client = self.refused([("propose_rule_change", {"rules_json": json.dumps(bad)})])
        self.assertTrue(tool_results(client.calls[1])[0]["is_error"])
        self.assertIsNone(out["messages"][1]["proposal"])

    def test_a_rule_set_that_is_not_json_is_refused(self):
        out, client = self.refused([("propose_rule_change", {"rules_json": "{not json"})])
        self.assertTrue(tool_results(client.calls[1])[0]["is_error"])

    def test_an_unknown_rule_number_and_a_hound_with_no_sport_are_refused(self):
        out, client = self.refused([("propose_price_band", {"price_min": 100, "price_max": 200, "rules": [7]})])
        self.assertIn("there is no rule 7", tool_results(client.calls[1])[0]["content"])
        out, client = self.refused([("propose_remove_sports", {"sports": ["MLB"]})])
        self.assertIn("at least one sport", tool_results(client.calls[1])[0]["content"])

    def test_the_model_gets_one_chance_to_fix_a_refusal_and_a_good_second_call_is_staged(self):
        client = FakeClient(reply("", [("propose_price_band", {"price_min": -200, "price_max": 100, "rules": []})]),
                            reply("", [("propose_price_band", {"price_min": 110, "price_max": 200, "rules": []})]),
                            reply("I'd move my price band to +110 to +200. Tap Apply."))
        out = self.send("make my price band shorter", client)
        first, second = tool_results(client.calls[1])[0], tool_results(client.calls[2])[0]
        self.assertTrue(first["is_error"])
        self.assertIn("fix it ONCE", first["content"])
        self.assertFalse(second.get("is_error", False))
        card = out["messages"][1]["proposal"]
        self.assertEqual(card["status"], "pending")
        self.assertTrue(any("+110" in str(c["after"]) for c in card["changes"]))

    def test_a_second_refusal_is_final_and_the_model_is_told_to_say_why(self):
        bad = {"price_min": -200, "price_max": 100, "rules": []}
        client = FakeClient(reply("", [("propose_price_band", bad)]), reply("", [("propose_price_band", bad), ("propose_price_band", bad)]),
                            reply("I can't do that: a price of -200 or worse is never allowed."))
        out = self.send("make it -200", client)
        results = tool_results(client.calls[2])
        self.assertIn("Do NOT call a tool again", results[0]["content"])
        self.assertIn("Do NOT call a tool again", results[1]["content"], "a third call in the same turn is not even tried")
        self.assertIn("can't do that", out["messages"][1]["text"])
        self.assertIsNone(out["messages"][1]["proposal"])
        self.assertEqual(len(self.lineage()), 1)

    def test_after_a_final_refusal_even_a_valid_call_in_the_same_turn_is_not_applied(self):
        bad = {"price_min": -200, "price_max": 100, "rules": []}
        good = ("propose_bets_per_day", {"bets_per_day": 1})
        client = FakeClient(reply("", [("propose_price_band", bad)]), reply("", [("propose_price_band", bad), good]), reply("I can't do that."))
        out = self.send("make it -200 and one bet", client)
        self.assertIn("Do NOT call a tool again", tool_results(client.calls[2])[1]["content"])
        self.assertIsNone(out["messages"][1]["proposal"], "the turn ended on a refusal: nothing is staged behind it")

    def test_when_the_model_says_nothing_after_a_final_refusal_the_hound_still_says_why(self):
        bad = {"price_min": -200, "price_max": 100, "rules": []}
        client = FakeClient(reply("", [("propose_price_band", bad)]), reply("", [("propose_price_band", bad)]), reply(""))
        out = self.send("make it -200", client)
        self.assertRegex(out["messages"][1]["text"], r"^I can't do that: .*-200")

    def test_a_valid_change_is_staged_as_a_card_and_changes_nothing(self):
        out, client = self.tool_turn("bet fewer games a day", [("propose_bets_per_day", {"bets_per_day": 1})])
        card = out["messages"][1]["proposal"]
        self.assertEqual(card["status"], "pending")
        self.assertEqual([c["what"] for c in card["changes"]], ["Most bets a day"])
        self.assertEqual((card["changes"][0]["before"], card["changes"][0]["after"]), ("2", "1"))
        self.assertIn("At most 1 bet a day", card["rule_after"])
        self.assertNotIn("spec", card, "the stored rule set never goes to the page")
        self.assertNotIn("base_hash", card)
        self.assertEqual(len(self.lineage()), 1)
        self.assertEqual(self.current()["spec"]["max_bets_per_day"], 2)

    def test_two_tools_in_one_turn_make_one_card(self):
        out, _ = self.tool_turn("one bet a day, two units", [("propose_bets_per_day", {"bets_per_day": 1}), ("propose_stake_units", {"stake_units": 2.0})])
        self.assertEqual(sorted(c["what"] for c in out["messages"][1]["proposal"]["changes"]), ["Most bets a day", "Stake"])

    def test_a_tool_that_changes_nothing_stages_nothing(self):
        out, client = self.tool_turn("two bets a day", [("propose_bets_per_day", {"bets_per_day": 2})], closing="That's already how I am.")
        self.assertIsNone(out["messages"][1]["proposal"])
        self.assertIn("Nothing to change", tool_results(client.calls[1])[0]["content"])
        self.assertFalse(tool_results(client.calls[1])[0].get("is_error", False))

    def test_a_new_card_replaces_one_still_waiting(self):
        a, _ = self.tool_turn("one bet", [("propose_bets_per_day", {"bets_per_day": 1})])
        b, _ = self.tool_turn("three bets", [("propose_bets_per_day", {"bets_per_day": 3})])
        by_id = {m["id"]: m for m in self.open()["messages"]}
        self.assertEqual(by_id[a["messages"][1]["id"]]["proposal"]["status"], "replaced")
        self.assertEqual(by_id[b["messages"][1]["id"]]["proposal"]["status"], "pending")

    def test_the_hound_cannot_rename_itself_or_restyle_from_chat(self):
        full = make_v2(name="Totally Different", tagline="sneaky", rules=[make_rule(side="away", price_min=100, price_max=300)], bet_in_play=True)
        out, _ = self.tool_turn("rewrite me", [("propose_rule_change", {"rules_json": json.dumps(dict(full, name="Totally Different", color="gold"))})])
        spec = [m for m in store.history(self.owner.id, self.hound["root_id"], db=self.db) if m["proposal"]][0]["proposal"]["spec"]
        self.assertEqual(spec["name"], "Dog Days")
        self.assertNotIn("bet_in_play", spec)
        self.assertEqual(spec["color"], "ember")

    def test_add_and_remove_sports_use_the_closest_honest_copy(self):
        out, _ = self.tool_turn("add NBA", [("propose_add_sports", {"sports": ["NBA"]})])
        spec = [m for m in store.history(self.owner.id, self.hound["root_id"], db=self.db) if m["proposal"]][0]["proposal"]["spec"]
        self.assertEqual(sorted(spec["sports"]), ["MLB", "NBA"])
        user_spec.validate_spec(spec)

    def test_an_edit_the_validator_refuses_never_becomes_a_card_even_via_the_narrow_tools(self):
        out, client = self.refused([("propose_price_band", {"price_min": 300, "price_max": 100, "rules": []})])
        self.assertIsNone(out["messages"][1]["proposal"])
        self.assertTrue(tool_results(client.calls[1])[0]["is_error"])


# ---------------------------------------------------------------------------------------------------------------------
class ApplyAndCancel(Base):
    def propose(self, tools=None, text="bet fewer games a day"):
        out, _ = self.tool_turn(text, tools or [("propose_bets_per_day", {"bets_per_day": 1})])
        return out["messages"][1]["id"]

    def apply(self, mid, user=None, hound_id=None):
        return service.apply_proposal((user or self.owner).id, hound_id or self.id, mid, now=NOW, db=self.db)

    def test_nothing_changes_until_apply_and_apply_makes_version_two(self):
        mid = self.propose()
        self.assertEqual(len(self.lineage()), 1)
        out = self.apply(mid)
        lineage = self.lineage()
        self.assertEqual([h["version_no"] for h in lineage], [1, 2])
        new, old = lineage[1], lineage[0]
        self.assertEqual(new["spec"]["max_bets_per_day"], 1)
        self.assertEqual(old["status"], user_store.STATUS_RETIRED)
        self.assertEqual(new["status"], user_store.STATUS_RUNNING)
        self.assertEqual(new["origin"], proposals.ORIGIN_OWNER_CHAT)
        self.assertEqual(proposals.ORIGIN_OWNER_CHAT, "owner_chat")
        self.assertIn('chat: "bet fewer games a day"', old["retire_reason"])
        self.assertEqual(old["retired_by"], f"owner:{self.owner.id}")
        self.assertEqual(out["hound"]["id"], new["id"])
        self.assertEqual(out["hound"]["version_no"], 2)
        self.assertEqual(out["messages"][0]["proposal"]["status"], "applied")
        self.assertEqual(out["messages"][0]["proposal"]["applied"]["version_no"], 2)
        self.assertEqual(out["messages"][1]["role"], "notice")
        self.assertIn("version 2", out["messages"][1]["text"])

    def test_the_origin_reads_as_edited_in_chat_wherever_the_kennel_reads_it(self):
        self.apply(self.propose())
        self.assertEqual(user_store.ORIGIN_LABELS.get(self.current()["origin"]), "edited in chat")

    def test_the_conversation_and_the_card_survive_the_apply(self):
        mid = self.propose()
        self.apply(mid)
        opened = service.open_chat(self.owner.id, False, self.current()["id"], now=NOW, db=self.db, env=ENV, router=self.router)
        self.assertEqual([m["role"] for m in opened["messages"]], ["member", "hound", "notice"])
        self.assertEqual(opened["messages"][1]["proposal"]["status"], "applied")

    def test_apply_twice_is_refused_and_makes_one_version(self):
        mid = self.propose()
        self.apply(mid)
        exc = self.err(self.apply, mid)
        self.assertEqual((exc.status, exc.code), (409, "proposal_applied"))
        self.assertEqual(len(self.lineage()), 2)

    def test_cancel_changes_nothing_at_all(self):
        mid = self.propose()
        out = service.cancel_proposal(self.owner.id, self.id, mid, now=NOW, db=self.db)
        self.assertEqual(out["messages"][0]["proposal"]["status"], "cancelled")
        self.assertEqual(out["messages"][1]["role"], "notice")
        self.assertEqual(len(self.lineage()), 1)
        self.assertEqual(self.current()["status"], user_store.STATUS_RUNNING)
        self.assertEqual(self.current()["spec"], self.hound["spec"])
        self.assertEqual(self.err(self.apply, mid).code, "proposal_cancelled")

    def test_a_stranger_cannot_apply_or_cancel_the_owners_card(self):
        mid = self.propose()
        for call in (lambda: self.apply(mid, user=self.other),
                     lambda: service.cancel_proposal(self.other.id, self.id, mid, db=self.db)):
            self.assertEqual(self.err(call).status, 404)
        self.assertEqual(len(self.lineage()), 1)

    def test_a_card_for_an_earlier_version_is_stale_and_is_never_applied(self):
        mid = self.propose()
        user_store.create_version(self.id, spec_dict(name="Dog Days", side_rule="underdog", max_bets_per_day=3), actor="owner", reason="edit by hand",
                                  now=CREATED, db=self.db)
        exc = self.err(self.apply, mid)
        self.assertEqual((exc.status, exc.code), (409, "proposal_stale"))
        self.assertEqual(len(self.lineage()), 2, "only the owner's own hand edit exists")
        self.assertEqual(self.current()["spec"]["max_bets_per_day"], 3)

    def test_what_is_applied_is_what_the_stored_proposal_says_and_it_is_checked_again(self):
        mid = self.propose()
        message = store.get_message(mid, self.owner.id, self.hound["root_id"], db=self.db)
        tampered = copy.deepcopy(message["proposal"])
        tampered["spec"]["rules"][0]["price_min"] = -300
        store.set_proposal(mid, tampered, db=self.db)
        exc = self.err(self.apply, mid)
        self.assertEqual((exc.status, exc.code), (422, "proposal_invalid"))
        self.assertEqual(len(self.lineage()), 1)

    def test_a_buried_hound_cannot_be_changed(self):
        mid = self.propose()
        buried = copy.deepcopy(self.current())
        buried["status"] = user_store.STATUS_BURIED
        with mock.patch.object(service, "resolve", lambda uid, hid, db=None: (common.resolve(self.id), buried)):
            exc = self.err(self.apply, mid)
        self.assertEqual((exc.status, exc.code), (409, "not_editable"))
        self.assertEqual(len(self.lineage()), 1)

    def test_apply_after_clearing_the_chat_is_not_found(self):
        mid = self.propose()
        service.clear_chat(self.owner.id, self.id, db=self.db)
        self.assertEqual(self.err(self.apply, mid).status, 404)

    def test_a_whole_rule_set_applies_as_the_next_version(self):
        rules = [make_rule(side="away", price_min=100, price_max=220), make_rule(markets=["total"], side="over", price_min=-130, price_max=110)]
        full = make_v2(name="Dog Days", rules=rules, max_bets_per_day=3, stake_units=1.5)
        mid = self.propose([("propose_rule_change", {"rules_json": json.dumps(full)})], text="only road underdogs and overs")
        self.apply(mid)
        new = self.current()["spec"]
        self.assertEqual((len(new["rules"]), new["max_bets_per_day"], new["stake_units"], new["name"]), (2, 3, 1.5, "Dog Days"))


# ---------------------------------------------------------------------------------------------------------------------
class Styles(Base):
    def gematria_hound(self):
        spec = user_spec.validate_spec({"version": 2, "style": "gematria", "name": "Numbers Pup", "sports": ["NBA"], "max_bets_per_day": 2, "stake_units": 1.0})
        return user_store.create_hound(self.owner.id, spec, now=CREATED, db=self.db)

    def test_a_gematria_hound_is_offered_only_its_three_choices(self):
        g = self.gematria_hound()
        client = FakeClient(reply("ok"))
        self.send("hi", client, hound_id=g["id"])
        self.assertEqual([t["name"] for t in client.calls[0]["tools"]], ["propose_bets_per_day", "propose_stake_units", "propose_add_sports", "propose_remove_sports"])

    def test_a_gematria_hound_refuses_a_price_band_and_a_whole_rule_set_by_name(self):
        g = self.gematria_hound()
        for tool in (("propose_price_band", {"price_min": 100, "price_max": 200, "rules": []}),
                     ("propose_rule_change", {"rules_json": json.dumps(make_v2(name="Numbers Pup", rules=[make_rule()]))})):
            client = FakeClient(reply("", [tool]), reply("", [tool]), reply("I can't change that."))
            out = self.send("change my rule", client, hound_id=g["id"])
            results = tool_results(client.calls[1])
            self.assertTrue(results[0]["is_error"])
            self.assertIn("fixed method", results[0]["content"])
            self.assertIsNone(out["messages"][1]["proposal"])
        self.assertEqual(len(user_store.lineage(g["id"], db=self.db)), 1)

    def test_a_gematria_hound_can_change_its_sports_bets_and_stake_and_stays_gematria(self):
        g = self.gematria_hound()
        client = FakeClient(reply("", [("propose_add_sports", {"sports": ["NHL"]}), ("propose_bets_per_day", {"bets_per_day": 3}), ("propose_stake_units", {"stake_units": 2.0})]),
                            reply("Tap Apply."))
        out = self.send("add hockey, three bets, two units", client, hound_id=g["id"])
        mid = out["messages"][1]["id"]
        service.apply_proposal(self.owner.id, g["id"], mid, now=NOW, db=self.db)
        new = user_store.lineage(g["id"], db=self.db)[-1]["spec"]
        self.assertEqual((new["style"], new["sports"], new["max_bets_per_day"], new["stake_units"]), ("gematria", ["NBA", "NHL"], 3, 2.0))
        self.assertEqual(new["rules"][0]["markets"], ["moneyline"])
        self.assertIsNone(new["rules"][0]["when"])

    def test_a_gematria_hound_can_drop_a_sport_but_not_its_last(self):
        spec = user_spec.validate_spec({"version": 2, "style": "gematria", "name": "Two Sport Pup", "sports": ["NBA", "NHL"], "max_bets_per_day": 2, "stake_units": 1.0})
        g = user_store.create_hound(self.owner.id, spec, now=CREATED, db=self.db)
        out, _ = self.tool_turn("drop hockey", [("propose_remove_sports", {"sports": ["NHL"]})], hound_id=g["id"])
        self.assertEqual([c["what"] for c in out["messages"][1]["proposal"]["changes"]], ["Rules"])
        client = FakeClient(reply("", [("propose_remove_sports", {"sports": ["NBA", "NHL"]})]), reply("", [("propose_remove_sports", {"sports": ["NBA", "NHL"]})]), reply("No."))
        out = self.send("drop everything", client, hound_id=g["id"])
        self.assertIn("at least one sport", tool_results(client.calls[1])[0]["content"])
        self.assertEqual(self.current_of(g)["spec"]["sports"], ["NBA", "NHL"])

    def current_of(self, g):
        return user_store.lineage(g["id"], db=self.db)[-1]

    def test_a_gematria_change_outside_its_three_choices_is_caught_on_the_finished_copy(self):
        g = self.gematria_hound()
        old = proposals.v2_of(g["spec"])
        new = copy.deepcopy(old)
        new["lock_minutes"] = 120
        self.assertEqual(proposals.changed_outside(old, new), ["lock_minutes"])
        new = copy.deepcopy(old)
        new["max_bets_per_day"], new["sports"] = 4, ["NBA", "NHL"]
        self.assertEqual(proposals.changed_outside(old, new), [])

    def test_an_apprentice_is_given_no_tools_and_is_told_why(self):
        spec = user_spec.validate_spec({"version": 2, "style": "apprentice", "name": "Student Pup", "max_bets_per_day": 2, "stake_units": 1.0})
        a = user_store.create_hound(self.owner.id, spec, now=CREATED, db=self.db)
        client = FakeClient(reply("I learn from your bets."))
        self.send("change my rule", client, hound_id=a["id"])
        self.assertNotIn("tools", client.calls[0])
        self.assertIn("Lessons", client.calls[0]["system"][1]["text"])

    def test_a_classic_hounds_rule_is_edited_as_its_version_two_equivalent(self):
        out, _ = self.tool_turn("bet fewer", [("propose_bets_per_day", {"bets_per_day": 1})])
        service.apply_proposal(self.owner.id, self.id, out["messages"][1]["id"], now=NOW, db=self.db)
        self.assertTrue(user_spec.is_v2(self.current()["spec"]))


# ---------------------------------------------------------------------------------------------------------------------
class Copy(Base):
    BANNED = re.compile(r"\b(beta|new|dogs?)\b", re.IGNORECASE)
    NO_PROFIT = re.compile(r"\b(profit|guarantee|sure thing|can'?t lose|beat the (book|market))", re.IGNORECASE)

    def test_the_words_the_page_and_the_service_say_follow_the_owners_copy_rules(self):
        words = [service.UNAVAILABLE_TEXT, service.RESTING_TEXT, service.COULD_NOT_ANSWER, service.PRIVATE_TEXT, service.PROPOSED_FALLBACK]
        words += [proposals.ORIGIN_LABEL, "Applied. X is now on version 2. The earlier version keeps its record.", "Cancelled. No change was made."]
        for text in words:
            self.assertIsNone(self.BANNED.search(text), text)
            self.assertIsNone(self.NO_PROFIT.search(text), text)
            self.assertNotIn("nothing cleared the bar", text.lower())
            self.assertNotIn("bet check", text.lower())

    def test_the_page_script_has_no_banned_word_and_never_advertises_bet_check(self):
        source = (REPO / "web" / "js" / "dog-chat.js").read_text(encoding="utf-8")
        source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
        source = re.sub(r"(^|[^:])//[^\n]*", r"\1", source)
        strings = re.findall(r'"([^"\n]{3,})"|`([^`\n]{3,})`', source)
        for a, b in strings:
            text = a or b
            if text.startswith(("./", "/hounds", "[data-hook", "dc-", "dk-", "hound.html", "data-")) or re.fullmatch(r"[\w\-.\[\]=' ,:>#]+", text) and " " not in text.strip():
                continue
            self.assertIsNone(self.BANNED.search(text), text)
            self.assertIsNone(self.NO_PROFIT.search(text), text)
        self.assertNotIn("betcheck", source.lower())
        self.assertNotIn("bet check", source.lower())


# ---------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Routes(Base):
    def setUp(self):
        super().setUp()
        from api import hounds_chat as api
        self.api = api
        for p in (mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": KEY}),
                  mock.patch.object(router_mod, "default_router", lambda: self.router),
                  mock.patch.object(hound_chat, "default_client", lambda key: self.client)):
            p.start()
            self.addCleanup(p.stop)
        self.client = FakeClient(reply("Woof, two bets.", usage=(3000, 120, 0, 0)))
        self.token = users_store.issue_invite_token(self.owner.id, db=self.db)

    def call(self, fn, *a, **k):
        return fn(*a, response=Response(), **k) if "response" not in k else fn(*a, **k)

    def test_the_owner_chats_and_reads_the_history_back(self):
        out = self.api.chat_send(self.id, self.api.ChatRequest(message="How am I doing?"), Response(), current_user=self.owner, _rl=None)
        self.assertEqual([m["role"] for m in out["messages"]], ["member", "hound"])
        self.assertTrue(out["paper_only"])
        back = self.api.chat_open(self.id, Response(), current_user=self.owner, _rl=None)
        self.assertEqual(len(back["messages"]), 2)
        self.assertTrue(back["available"])
        self.assertEqual(back["limits"]["limit_per_day"], service.limit_for(not self._free()))

    def _free(self):
        from api import auth as auth_mod
        return auth_mod.is_free_member(self.owner)

    def test_a_stranger_is_a_404_on_every_route(self):
        for fn, args in ((self.api.chat_open, (self.id, Response())),
                         (self.api.chat_send, (self.id, self.api.ChatRequest(message="hi"), Response())),
                         (self.api.chat_clear, (self.id, Response())),
                         (self.api.chat_apply, (self.id, 1, Response())),
                         (self.api.chat_cancel, (self.id, 1, Response()))):
            with self.assertRaises(HTTPException) as ctx:
                fn(*args, current_user=self.other, _rl=None)
            self.assertEqual(ctx.exception.status_code, 404)
            self.assertEqual(ctx.exception.detail["error"], "not_found")
        self.assertEqual(self.client.calls, [])

    def test_the_refusals_carry_a_stable_code_and_words(self):
        with self.assertRaises(HTTPException) as ctx:
            self.api.chat_send(self.id, self.api.ChatRequest(message="mail me at a@b.co"), Response(), current_user=self.owner, _rl=None)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (422, "private_info"))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            with self.assertRaises(HTTPException) as ctx:
                self.api.chat_send(self.id, self.api.ChatRequest(message="hi"), Response(), current_user=self.owner, _rl=None)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail["error"]), (503, "unavailable"))

    def test_apply_and_cancel_and_clear_are_routes(self):
        self.client.script = [reply("", [("propose_bets_per_day", {"bets_per_day": 1})]), reply("Tap Apply.")]
        sent = self.api.chat_send(self.id, self.api.ChatRequest(message="bet fewer"), Response(), current_user=self.owner, _rl=None)
        mid = sent["messages"][1]["id"]
        applied = self.api.chat_apply(self.id, mid, Response(), current_user=self.owner, _rl=None)
        self.assertEqual(applied["hound"]["version_no"], 2)
        self.client.script = [reply("", [("propose_bets_per_day", {"bets_per_day": 3})]), reply("Tap Apply.")]
        sent = self.api.chat_send(applied["hound"]["id"], self.api.ChatRequest(message="three"), Response(), current_user=self.owner, _rl=None)
        cancelled = self.api.chat_cancel(applied["hound"]["id"], sent["messages"][1]["id"], Response(), current_user=self.owner, _rl=None)
        self.assertEqual(cancelled["messages"][0]["proposal"]["status"], "cancelled")
        cleared = self.api.chat_clear(applied["hound"]["id"], Response(), current_user=self.owner, _rl=None)
        self.assertGreater(cleared["cleared"], 0)
        with self.assertRaises(HTTPException) as ctx:
            self.api.chat_apply(applied["hound"]["id"], mid, Response(), current_user=self.owner, _rl=None)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_the_routes_exist_and_the_router_is_mounted_before_the_public_hounds_routes(self):
        paths = {(m, r.path) for r in self.api.router.routes for m in getattr(r, "methods", ()) or ()}
        for want in (("GET", "/hounds/{hound_id}/chat"), ("POST", "/hounds/{hound_id}/chat"), ("DELETE", "/hounds/{hound_id}/chat"),
                     ("POST", "/hounds/{hound_id}/chat/proposals/{message_id}/apply"), ("POST", "/hounds/{hound_id}/chat/proposals/{message_id}/cancel")):
            self.assertIn(want, paths)
        source = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("from api.hounds_chat import router as hounds_chat_router", source)
        at = source.index("app.include_router(hounds_chat_router)")
        self.assertLess(at, source.index("app.include_router(hounds_router)"))


class NoFastApi(unittest.TestCase):
    def test_the_chat_package_and_the_model_module_import_with_fastapi_hidden(self):
        code = ("import sys\n"
                "for n in ('fastapi','starlette','pydantic','uvicorn'): sys.modules[n] = None\n"
                "import src.ai.hound_chat, src.hounds.chat.store, src.hounds.chat.facts, src.hounds.chat.proposals, src.hounds.chat.service\n"
                "print('ok')\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), "ok", done.stderr)

    def test_no_chat_module_imports_fastapi_or_the_api_package(self):
        for path in list((REPO / "src" / "hounds" / "chat").glob("*.py")) + [REPO / "src" / "ai" / "hound_chat.py"]:
            text = path.read_text(encoding="utf-8")
            for banned in ("import fastapi", "from fastapi", "from api", "import api"):
                self.assertNotIn(banned, text, path.name)


if __name__ == "__main__":
    unittest.main()
