"""Hindsight reviews (src/ai/postmortems.py and its parts): queue on settle, priority, the budget wall, parsing, sources, the coaching feed.

The story these pin (owner ask 2026-10-28): after a paper bet settles, Claude with web search says what happened and why, at most
$20 a month, member hounds first, never as pre-game reasoning, never from a source the web did not return. Every test fakes the
client and the clock and points every store at a temp dir: nothing here touches the network or the repository's data.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.ai import postmortem_cost as cost
from src.ai import postmortem_parse as pm
from src.ai import postmortem_store as store
from src.ai import postmortems
from tests.postmortem_fixtures import (
    ENV, KEY, NOW, URLS, FakeClient, Rig, bet, book_of, hound_data, message, review_json)


def ok_result(**kw):
    return SimpleNamespace(type="succeeded", message=message(**kw))


class WithRig(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.close)
        self.e = self.rig.engine
        self.client = self.rig.client


# ---------------------------------------------------------------------------------------------------------------------
class TheMoney(unittest.TestCase):
    def test_haiku_usage_is_priced_at_the_real_rate_plus_a_cent_a_search(self):
        usage = SimpleNamespace(input_tokens=20000, output_tokens=1000, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                                server_tool_use=SimpleNamespace(web_search_requests=3))
        self.assertAlmostEqual(cost.usage_cost(cost.HAIKU, usage), 20000 * 0.10 / 1e6 + 1000 * 0.50 / 1e6 + 0.03, places=8)

    def test_a_batch_halves_the_tokens_and_not_the_searches(self):
        usage = {"input_tokens": 20000, "output_tokens": 1000, "server_tool_use": {"web_search_requests": 3}}
        full, half = cost.usage_cost(cost.HAIKU, usage), cost.usage_cost(cost.HAIKU, usage, batch=True)
        self.assertAlmostEqual(half, (20000 * 0.10 + 1000 * 0.50) / 1e6 * 0.5 + 0.03, places=8)
        self.assertGreater(full, half)

    def test_sonnet_and_the_long_prompt_rate_card(self):
        self.assertAlmostEqual(cost.usage_cost(cost.SONNET, {"input_tokens": 1_000_000, "output_tokens": 100_000}), 2.0 + 1.0, places=6)
        long_haiku = cost.usage_cost(cost.HAIKU, {"input_tokens": 200_000, "output_tokens": 0})
        self.assertAlmostEqual(long_haiku, 200_000 * 0.50 / 1e6, places=6)            # past 100K the dearer card applies

    def test_cache_reads_and_writes_are_priced_apart(self):
        usage = {"input_tokens": 0, "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000, "output_tokens": 0}
        self.assertAlmostEqual(cost.usage_cost(cost.SONNET, usage), 2.0 * 1.25 + 2.0 * 0.10, places=6)

    def test_no_usage_is_none_so_the_caller_charges_the_worst_case(self):
        self.assertIsNone(cost.usage_cost(cost.HAIKU, None))

    def test_the_worst_case_counts_every_search_and_every_output_token(self):
        small = cost.worst_case_cost(cost.HAIKU, 4000, 4000, 0)
        with_searches = cost.worst_case_cost(cost.HAIKU, 4000, 4000, 3)
        self.assertGreater(with_searches, small + 3 * cost.WEB_SEARCH_USD - 1e-9)
        self.assertLess(cost.worst_case_cost(cost.HAIKU, 4000, 4000, 3, batch=True), with_searches)
        self.assertGreater(cost.worst_case_cost(cost.SONNET, 4000, 8000, 6), cost.worst_case_cost(cost.HAIKU, 4000, 4000, 3))

    def test_the_cap_is_twenty_dollars_with_an_env_override(self):
        self.assertEqual(postmortems.POSTMORTEM_MONTHLY_USD, 20.0)
        self.assertEqual(postmortems.monthly_cap({}), 20.0)
        self.assertEqual(postmortems.monthly_cap({postmortems.ENV_CAP: "7.5"}), 7.5)
        self.assertEqual(postmortems.monthly_cap({postmortems.ENV_CAP: "junk"}), 20.0)
        self.assertEqual(postmortems.monthly_cap({postmortems.ENV_CAP: "-3"}), 0.0)
        self.assertEqual(postmortems.monthly_cap({postmortems.ENV_CAP: "nan"}), 20.0)


# ---------------------------------------------------------------------------------------------------------------------
class TheAnswer(unittest.TestCase):
    def evidence(self, **kw):
        return pm.analyze_message(message(**kw))

    def test_a_valid_answer_is_stored_with_only_the_known_keys(self):
        ev = self.evidence()
        review, problems = pm.parse_review(ev["text"], ev)
        self.assertEqual(problems, [])
        self.assertEqual(review["luck_vs_process"], "mixed")
        self.assertTrue(review["grounded"])
        self.assertEqual(sorted(review), sorted([
            "what_happened", "key_factors", "factor_tags", "reason_relevance", "reason_assessment", "luck_vs_process",
            "info_hound_lacked", "lesson", "analyst_takes", "sources", "confidence", "grounded"]))

    def test_a_markdown_fence_is_accepted_and_nothing_is_repaired(self):
        ev = self.evidence(text="```json\n" + json.dumps(review_json()) + "\n```")
        self.assertIsNotNone(pm.parse_review(ev["text"], ev)[0])
        bad = review_json(luck_vs_process="pure_skill")
        ev = self.evidence(review=bad)
        review, problems = pm.parse_review(ev["text"], ev)
        self.assertIsNone(review)
        self.assertTrue(any("luck_vs_process" in p for p in problems))

    def test_a_missing_key_or_not_json_or_a_list_is_a_failure(self):
        gone = review_json()
        del gone["lesson"]
        for text in (json.dumps(gone), "I could not find anything.", "[1, 2]", ""):
            ev = self.evidence(text=text)
            review, problems = pm.parse_review(ev["text"], ev)
            self.assertIsNone(review, text)
            self.assertTrue(problems)

    def test_a_deep_review_must_carry_deeper_notes(self):
        ev = self.evidence()
        self.assertIsNone(pm.parse_review(ev["text"], ev, pm.DEPTH_DEEP)[0])
        deep = review_json(deeper_notes="The fast review missed that the closer was unavailable on back-to-back days.")
        ev = self.evidence(review=deep)
        review, problems = pm.parse_review(ev["text"], ev, pm.DEPTH_DEEP)
        self.assertEqual(problems, [])
        self.assertIn("deeper_notes", review)

    def test_sources_are_kept_only_when_a_search_returned_the_url(self):
        made_up = review_json(sources=[{"url": "https://example.com/recap", "title": "Recap", "kind": "recap"},
                                       {"url": "https://invented.example/story", "title": "Made up", "kind": "news"}])
        ev = self.evidence(review=made_up)
        review, _ = pm.parse_review(ev["text"], ev)
        self.assertEqual([s["url"] for s in review["sources"]], ["https://example.com/recap"])

    def test_a_url_match_ignores_a_fragment_a_trailing_slash_and_host_case(self):
        listed = review_json(sources=[{"url": "HTTPS://Example.com/recap/#top", "title": "Recap", "kind": "recap"}])
        ev = self.evidence(review=listed)
        review, _ = pm.parse_review(ev["text"], ev)
        self.assertEqual(len(review["sources"]), 1)
        self.assertEqual(review["sources"][0]["url"], "https://example.com/recap")      # the URL the search returned, not the model's spelling

    def test_an_analyst_take_without_a_real_source_is_dropped(self):
        ev = self.evidence(review=review_json(analyst_takes=[
            {"outlet": "Real", "take": "Pitching depth decided it.", "url": "https://example.org/injuries"},
            {"outlet": "Fake", "take": "A made-up column.", "url": "https://nowhere.example/x"}]))
        review, _ = pm.parse_review(ev["text"], ev)
        self.assertEqual([t["outlet"] for t in review["analyst_takes"]], ["Real"])

    def test_a_review_with_no_real_source_is_ungrounded_and_low_confidence(self):
        ev = self.evidence(urls={})                      # the searches returned nothing
        review, problems = pm.parse_review(ev["text"], ev)
        self.assertEqual(problems, [])
        self.assertEqual(review["sources"], [])
        self.assertEqual(review["analyst_takes"], [])
        self.assertFalse(review["grounded"])
        self.assertEqual(review["confidence"], "low")

    def test_a_cited_url_the_model_did_not_list_is_added(self):
        cite = [SimpleNamespace(url="https://example.org/injuries", title="Injury report")]
        ev = self.evidence(review=review_json(sources=[]), citations=cite)
        review, _ = pm.parse_review(ev["text"], ev)
        self.assertEqual([s["url"] for s in review["sources"]], ["https://example.org/injuries"])

    def test_a_tag_outside_the_vocabulary_is_counted_as_other(self):
        ev = self.evidence(review=review_json(factor_tags=["starter_performance", "vibes", "vibes"]))
        review, _ = pm.parse_review(ev["text"], ev)
        self.assertEqual(review["factor_tags"], ["starter_performance", "other"])

    def test_a_search_error_block_adds_no_urls(self):
        msg = SimpleNamespace(content=[SimpleNamespace(type="web_search_tool_result", content=SimpleNamespace(type="web_search_tool_result_error", error_code="unavailable")),
                                       SimpleNamespace(type="text", text="{}", citations=None)], stop_reason="end_turn", usage=None)
        self.assertEqual(pm.analyze_message(msg)["results"], {})

    def test_the_request_names_the_right_search_tool_for_each_model(self):
        fast, _ = pm.request_params({"result": "loss"}, pm.DEPTH_FAST)
        deep, _ = pm.request_params({"result": "loss"}, pm.DEPTH_DEEP)
        self.assertEqual(fast["model"], "claude-haiku-5-5")
        self.assertEqual(fast["tools"], [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}])
        self.assertEqual(deep["model"], "claude-sonnet-5-5")
        self.assertEqual(deep["tools"], [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}])
        self.assertEqual(fast["output_config"], {"effort": "low"})
        self.assertNotIn("temperature", fast)                       # Haiku 5.5 and Sonnet 5.5 reject sampling parameters
        self.assertNotIn("thinking", deep)                          # and Sonnet 5.5 rejects thinking disabled

    def test_the_prompt_says_hindsight_and_carries_the_hounds_own_reason(self):
        params, _ = pm.request_params({"reason": "Rested starter at plus money.", "result": "loss", "hound_name": "Dee", "game": "A at B"}, pm.DEPTH_FAST)
        text = params["system"] + params["messages"][0]["content"]
        self.assertIn("HINDSIGHT", params["system"])
        self.assertIn("Rested starter at plus money.", text)
        self.assertIn("untrusted", params["system"])
        self.assertIn("LOSS", text)

    def test_custom_ids_round_trip_and_fit_the_api_rule(self):
        key = store.bet_key("u-1", bet())
        cid = pm.custom_id(key, "deep")
        self.assertRegex(cid, r"^[A-Za-z0-9_-]{1,64}$")
        self.assertEqual(pm.split_custom_id(cid), (key, "deep"))
        self.assertIsNone(pm.split_custom_id("nonsense"))


# ---------------------------------------------------------------------------------------------------------------------
class TheFiles(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.q = store.QueueStore(os.path.join(self.tmp.name, "q.jsonl"))
        self.l = store.ReviewLedger(os.path.join(self.tmp.name, "l.jsonl"))

    def test_a_bet_key_is_stable_and_follows_what_makes_a_ticket_this_ticket(self):
        a = bet(1)
        self.assertEqual(store.bet_key("u-1", a), store.bet_key("u-1", bet(1)))
        self.assertNotEqual(store.bet_key("u-1", a), store.bet_key("u-2", a))
        self.assertNotEqual(store.bet_key("u-1", a), store.bet_key("u-1", bet(2)))
        self.assertNotEqual(store.bet_key("u-1", a), store.bet_key("u-1", bet(1, segment="replay")))
        self.assertRegex(store.bet_key("u-1", a), r"^pm_[0-9a-f]{16}$")
        self.assertEqual(store.bet_key("u-1", a), store.bet_key("u-1", bet(1, result="win")))     # the result is not part of the identity

    def snap(self, n=1, **kw):
        row = bet(n, **kw)
        return {"bet_key": store.bet_key("u-1", row), "hound_id": "u-1", "result": row.result, "date": row.date, "game": row.game}

    def test_the_queue_survives_a_restart_and_a_second_reader_sees_appends(self):
        self.q.enqueue(self.snap(1), store.TIER_MEMBER)
        again = store.QueueStore(self.q.path)
        self.assertEqual(len(again.pending()), 1)
        self.q.enqueue(self.snap(2), store.TIER_HOUSE)
        self.assertEqual(len(again.pending()), 2)                    # incremental read: no restart needed

    def test_an_item_is_queued_once(self):
        self.assertTrue(self.q.enqueue(self.snap(1), store.TIER_MEMBER))
        self.assertFalse(self.q.enqueue(self.snap(1), store.TIER_MEMBER))
        self.assertEqual(len(self.q.pending()), 1)

    def test_a_torn_last_line_waits_and_is_then_read(self):
        self.q.enqueue(self.snap(1), store.TIER_MEMBER)
        with open(self.q.path, "ab") as fh:
            fh.write(b'{"kind":"queued","bet_key":"pm_0000000000000000","depth":"fast","tier":"house","bet":{"bet_key":"pm_0000')
        fresh = store.QueueStore(self.q.path)
        self.assertEqual(len(fresh.pending()), 1)
        with open(self.q.path, "ab") as fh:
            fh.write(b'000000000000"}}\n')
        self.assertEqual(len(fresh.pending()), 2)

    def test_the_ledger_is_first_write_wins_and_reads_back_by_offset(self):
        b = self.snap(1)
        self.assertTrue(self.l.append(bet=b, depth="fast", model="m", review={"lesson": "first", "grounded": True}, cost_usd=0.01, web_searches=2, batch_id="x"))
        self.assertFalse(self.l.append(bet=b, depth="fast", model="m", review={"lesson": "second", "grounded": True}, cost_usd=0.01, web_searches=2, batch_id="y"))
        self.assertEqual(self.l.get(b["bet_key"])["fast"]["review"]["lesson"], "first")
        self.assertIsNone(self.l.get(b["bet_key"])["deep"])
        self.assertTrue(self.l.append(bet=b, depth="deep", model="m2", review={"lesson": "deeper", "grounded": True}, cost_usd=0.2, web_searches=5, batch_id="z"))
        self.assertEqual(self.l.get(b["bet_key"])["deep"]["review"]["lesson"], "deeper")
        self.assertEqual(store.ReviewLedger(self.l.path).count(), 2)           # a fresh reader indexes the same file

    def test_a_ledger_row_is_labelled_hindsight_and_paper_only(self):
        b = self.snap(1)
        self.l.append(bet=b, depth="fast", model="m", review={"grounded": True}, cost_usd=0, web_searches=0, batch_id=None)
        row = self.l.get(b["bet_key"])["fast"]
        self.assertEqual(row["label"], "Hindsight review")
        self.assertTrue(row["paper_only"])


# ---------------------------------------------------------------------------------------------------------------------
class TheQueue(WithRig):
    def test_a_settled_forward_bet_is_queued_and_a_replay_open_push_or_void_is_not(self):
        data = hound_data("u-1", [bet(1, result="loss"), bet(2, result="win"), bet(3, result="push"), bet(4, result="void"),
                                  bet(5, result=None), bet(6, result="loss", segment="replay")])
        self.e.scan(book_of(data))
        queued = {i["bet_key"] for i in self.rig.queue.pending()}
        want = {store.bet_key("u-1", b) for b in data.bets if b.segment == "forward" and b.result in ("win", "loss")}
        self.assertEqual(queued, want)
        self.assertEqual(len(queued), 2)

    def test_a_bet_that_settles_between_two_scans_is_queued_by_the_second(self):
        data = hound_data("u-1", [bet(1, result=None)])
        self.e.scan(book_of(data))
        self.assertEqual(self.rig.queue.pending(), [])
        data.bets[0] = bet(1, result="loss")                       # the live-settle pass graded it
        self.e.scan(book_of(data))
        self.assertEqual(len(self.rig.queue.pending()), 1)

    def test_a_second_scan_queues_nothing_twice(self):
        book = book_of(hound_data("u-1", [bet(1), bet(2)]))
        self.e.scan(book)
        again = self.e.scan(book)
        self.assertEqual((again["queued"], len(self.rig.queue.pending())), (0, 2))

    def test_bets_graded_before_the_first_scan_are_history_not_backlog(self):
        old = bet(1, graded_utc="2026-10-20T12:00:00Z", date="2026-10-20")
        fresh = bet(2, graded_utc="2026-10-28T19:00:00Z")
        no_stamp_old = bet(3, graded_utc=None, date="2026-10-01")
        self.e.scan(book_of(hound_data("u-1", [old, fresh, no_stamp_old])))
        self.assertEqual({i["bet_key"] for i in self.rig.queue.pending()}, {store.bet_key("u-1", fresh)})

    def test_the_since_line_is_written_once_and_can_be_moved_back_by_env(self):
        self.e.scan(book_of(hound_data("u-1", [bet(1)])))
        first = self.rig.queue.since()
        self.rig.clock.advance(days=3)
        self.e.scan(book_of(hound_data("u-1", [bet(1)])))
        self.assertEqual(self.rig.queue.since(), first)
        env = dict(ENV, **{postmortems.ENV_SINCE: "2026-10-01"})
        rig = Rig(env)
        self.addCleanup(rig.close)
        rig.engine.scan(book_of(hound_data("u-1", [bet(3, graded_utc=None, date="2026-10-05")])))
        self.assertEqual(len(rig.queue.pending()), 1)

    def test_priority_is_member_hounds_then_house_hounds_then_the_learner(self):
        member = hound_data("u-1", [bet(1)], kind="user")
        house = hound_data("h-1", [bet(2, hound_id="h-1")], kind="house", category="stats")
        learner = hound_data("learner", [bet(i, hound_id="learner") for i in range(10, 70)], kind="house", category="learner")
        self.e.scan(book_of(learner, house, member))              # the book lists the Learner first on purpose
        order = [i["hound_id"] for i in self.rig.queue.pending()]
        self.assertEqual(order[0], "u-1")
        self.assertEqual(order[1], "h-1")
        self.assertTrue(all(h == "learner" for h in order[2:]))

    def test_inside_a_tier_fast_comes_before_deep_and_older_before_newer(self):
        self.rig.queue.enqueue({"bet_key": "pm_aaaaaaaaaaaaaaaa", "hound_id": "u-1"}, store.TIER_MEMBER, "deep")
        self.rig.queue.enqueue({"bet_key": "pm_bbbbbbbbbbbbbbbb", "hound_id": "u-1"}, store.TIER_MEMBER, "fast")
        self.rig.queue.enqueue({"bet_key": "pm_cccccccccccccccc", "hound_id": "u-1"}, store.TIER_MEMBER, "fast")
        self.assertEqual([(i["bet_key"][3], i["depth"]) for i in self.rig.queue.pending()], [("b", "fast"), ("c", "fast"), ("a", "deep")])

    def test_the_learner_is_sampled_one_in_five_and_the_draw_never_flips(self):
        bets = [bet(i, hound_id="learner") for i in range(100, 400)]
        book = book_of(hound_data("learner", bets, kind="house", category="learner"))
        self.e.scan(book)
        kept = len(self.rig.queue.pending())
        self.assertGreater(kept, 300 * 0.12)
        self.assertLess(kept, 300 * 0.30)
        before = {i["bet_key"] for i in self.rig.queue.pending()}
        rig2 = Rig()
        self.addCleanup(rig2.close)
        rig2.engine.scan(book)
        self.assertEqual({i["bet_key"] for i in rig2.queue.pending()}, before)         # deterministic across machines
        self.e.scan(book)                                                              # and a re-scan adds nothing
        self.assertEqual({i["bet_key"] for i in self.rig.queue.pending()}, before)

    def test_a_house_hound_is_not_sampled(self):
        bets = [bet(i, hound_id="h-1") for i in range(100, 130)]
        self.e.scan(book_of(hound_data("h-1", bets, kind="house", category="stats")))
        self.assertEqual(len(self.rig.queue.pending()), 30)

    def test_baseline_controls_are_never_reviewed(self):
        self.e.scan(book_of(hound_data("b-1", [bet(1, hound_id="b-1")], kind="baseline", category="baseline")))
        self.assertEqual(self.rig.queue.pending(), [])


# ---------------------------------------------------------------------------------------------------------------------
class TheBatch(WithRig):
    def test_no_key_means_the_queue_waits_and_no_client_is_built(self):
        rig = Rig(env={})
        self.addCleanup(rig.close)
        out = rig.engine.tick(book_of(hound_data("u-1", [bet(1)])))
        self.assertEqual(out["waiting"], "no_api_key")
        self.assertEqual(rig.built, [])
        self.assertEqual(len(rig.queue.pending()), 1)               # still queued, not lost
        self.assertEqual(rig.client.batches.created, [])

    def test_the_sdk_not_being_installed_is_a_wait_not_a_crash(self):
        def boom(key, timeout):
            raise ImportError("no anthropic")
        self.e._client_factory = boom
        out = self.e.tick(book_of(hound_data("u-1", [bet(1)])))
        self.assertEqual(out["waiting"], "sdk_not_installed")

    def test_a_tick_submits_one_batch_of_fast_requests_with_the_right_shape(self):
        self.e.tick(book_of(hound_data("u-1", [bet(1), bet(2)])))
        self.assertEqual(len(self.client.batches.created), 1)
        reqs = self.client.batches.created[0]
        self.assertEqual(len(reqs), 2)
        for r in reqs:
            p = r["params"]
            self.assertEqual(p["model"], "claude-haiku-5-5")
            self.assertEqual(p["tools"][0]["type"], "web_search_20250305")
            self.assertEqual(p["tools"][0]["max_uses"], 3)
            self.assertTrue(r["custom_id"].endswith("_fast"))
        self.assertEqual(self.rig.built, [KEY])                     # the key goes to the client factory and nowhere else

    def test_the_batch_reserves_its_worst_case_and_the_reservation_counts_against_the_cap(self):
        self.e.tick(book_of(hound_data("u-1", [bet(1), bet(2)])))
        reserved = self.rig.usage.reserved(postmortems.PROVIDER)
        self.assertGreater(reserved, 0)
        self.assertEqual(self.e.committed(), reserved)
        self.assertEqual(len(self.rig.usage.open_batches()), 1)

    def test_a_finished_batch_writes_the_ledger_and_the_meter(self):
        book = book_of(hound_data("u-1", [bet(1, result="win", price=120)]))
        self.e.tick(book)
        self.rig.clock.advance(minutes=30)
        out = self.e.tick(book)
        self.assertEqual(out["collect"]["reviews"], 1)
        key = store.bet_key("u-1", book.hounds["u-1"].bets[0])
        row = self.rig.ledger.get(key)["fast"]
        self.assertEqual(row["review"]["lesson"], review_json()["lesson"])
        self.assertEqual(row["label"], "Hindsight review")
        self.assertEqual(row["web_searches"], 3)
        want = cost.usage_cost(cost.HAIKU, message().usage, batch=True)
        self.assertAlmostEqual(self.rig.usage.month_spend(postmortems.PROVIDER), want, places=8)
        self.assertEqual(self.rig.usage.reserved(postmortems.PROVIDER), 0)             # read, so the reservation is released
        self.assertEqual(self.rig.queue.counts()["done"], 1)

    def test_a_loss_earns_a_deep_review_and_a_small_win_does_not(self):
        book = book_of(hound_data("u-1", [bet(1, result="loss"), bet(2, result="win", price=120)]))
        self.e.tick(book)
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        loss_key = store.bet_key("u-1", book.hounds["u-1"].bets[0])
        win_key = store.bet_key("u-1", book.hounds["u-1"].bets[1])
        self.assertIsNotNone(self.rig.queue.get(loss_key, "deep"))
        self.assertIsNone(self.rig.queue.get(win_key, "deep"))

    def test_a_big_win_earns_a_deep_review(self):
        book = book_of(hound_data("u-1", [bet(1, result="win", price=250)]))          # +2.5 units
        self.e.tick(book)
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        self.assertIsNotNone(self.rig.queue.get(store.bet_key("u-1", book.hounds["u-1"].bets[0]), "deep"))

    def test_the_deep_pass_runs_on_sonnet_with_more_searches_and_sees_the_fast_review(self):
        book = book_of(hound_data("u-1", [bet(1, result="loss")]))
        self.e.tick(book)
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)                                           # collect the fast review, queue the deep one and send it
        deep_batch = self.client.batches.created[-1]
        self.assertEqual(len(deep_batch), 1)
        p = deep_batch[0]["params"]
        self.assertEqual(p["model"], "claude-sonnet-5-5")
        self.assertEqual(p["tools"], [{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}])
        self.assertIn("THE EARLIER FAST REVIEW", p["messages"][0]["content"])
        self.assertIn(review_json()["what_happened"][:30], p["messages"][0]["content"])
        self.client.batches.answers[deep_batch[0]["custom_id"]] = ok_result(
            review=review_json(deeper_notes="The fast review missed that the closer had thrown 40 pitches the night before."), input_tokens=60000, output_tokens=3000, searches=5)
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        key = store.bet_key("u-1", book.hounds["u-1"].bets[0])
        self.assertIn("deeper_notes", self.rig.ledger.get(key)["deep"]["review"])
        self.assertIsNotNone(self.rig.ledger.get(key)["fast"])                       # the fast row is kept beside it

    def test_batches_are_spaced_but_a_full_one_goes_at_once(self):
        self.e.tick(book_of(hound_data("u-1", [bet(1)])))
        self.assertEqual(len(self.client.batches.created), 1)
        self.rig.clock.advance(minutes=5)
        out = self.e.tick(book_of(hound_data("u-1", [bet(1), bet(2)])))
        self.assertEqual(out["submit"]["reason"], "batching")
        self.assertEqual(len(self.client.batches.created), 1)
        many = book_of(hound_data("u-1", [bet(i) for i in range(1, 30)]))
        self.e.tick(many)
        self.assertEqual(len(self.client.batches.created), 2)
        self.assertEqual(len(self.client.batches.created[1]), postmortems.BATCH_MAX_REQUESTS)

    def test_an_unfinished_batch_is_left_alone_and_read_later(self):
        book = book_of(hound_data("u-1", [bet(1)]))
        self.client.batches.status = "in_progress"
        self.e.tick(book)
        self.rig.clock.advance(minutes=30)
        out = self.e.tick(book)
        self.assertEqual(out["collect"]["batches_read"], 0)
        self.assertEqual(self.rig.ledger.count(), 0)
        self.client.batches.status = "ended"
        self.rig.clock.advance(minutes=30)
        self.assertEqual(self.e.tick(book)["collect"]["reviews"], 1)

    def test_a_batch_that_never_ends_is_given_up_on_and_its_items_go_back_in_line(self):
        book = book_of(hound_data("u-1", [bet(1)]))
        self.client.batches.status = "in_progress"
        self.e.tick(book)
        self.rig.clock.advance(hours=27)
        self.e.tick(book)
        self.assertNotIn("msgbatch_1", self.rig.queue.open_batches())                     # the dead batch is closed...
        self.assertEqual(self.rig.usage.open_batches(), ["msgbatch_2"])                    # ...its reservation released, the item sent again
        key = store.bet_key("u-1", book.hounds["u-1"].bets[0])
        self.assertEqual(self.rig.queue.get(key, "fast")["attempts"], 1)
        self.assertEqual(self.rig.queue.counts()["done"], 0)

    def test_reading_the_same_batch_twice_never_writes_a_second_review_or_charge(self):
        book = book_of(hound_data("u-1", [bet(1, result="win", price=120)]))
        self.e.tick(book)
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        spent = self.rig.usage.month_spend(postmortems.PROVIDER)
        count = self.rig.ledger.count()
        self.e.collect(self.client)                                  # a replay (a crash before the batch was marked read)
        self.assertEqual((self.rig.ledger.count(), self.rig.usage.month_spend(postmortems.PROVIDER)), (count, spent))

    def test_a_failed_submit_cools_the_provider_and_writes_no_reservation(self):
        self.client.batches.fail_create = RuntimeError(f"boom {KEY}")
        out = self.e.tick(book_of(hound_data("u-1", [bet(1)])))
        self.assertEqual(out["submit"]["reason"], "submit_failed")
        self.assertEqual(self.rig.usage.reserved(postmortems.PROVIDER), 0)
        self.assertIsNotNone(self.rig.usage.cooldown(postmortems.PROVIDER))
        self.client.batches.fail_create = None
        self.rig.clock.advance(minutes=5)
        self.assertEqual(self.e.tick(book_of(hound_data("u-1", [bet(1)])))["submit"]["reason"], "cooling_down")
        self.assertEqual(len(self.rig.queue.pending()), 1)           # nothing was lost

    def test_a_tick_while_another_holds_the_lock_does_nothing(self):
        with open(self.e.lock_path, "w", encoding="ascii") as fh:
            fh.write(store.iso(self.rig.clock() + timedelta(minutes=5)))
        out = self.e.tick(book_of(hound_data("u-1", [bet(1)])))
        self.assertIn("skipped", out)
        self.assertEqual(self.client.batches.created, [])
        self.rig.clock.advance(minutes=11)                          # the holder crashed: the lock expires
        self.assertIn("submit", self.e.tick(book_of(hound_data("u-1", [bet(1)]))))

    def test_posting_reviews_off_is_a_switch(self):
        self.e.env = dict(ENV, **{postmortems.ENV_FLAG: "off"})
        self.assertEqual(self.e.tick(book_of(hound_data("u-1", [bet(1)]))), {"disabled": True})


# ---------------------------------------------------------------------------------------------------------------------
class TheBudgetWall(WithRig):
    def test_a_cap_of_zero_stops_every_call(self):
        self.e.env = dict(ENV, **{postmortems.ENV_CAP: "0"})
        out = self.e.tick(book_of(hound_data("u-1", [bet(1)])))
        self.assertEqual(out["submit"]["reason"], "monthly_cap")
        self.assertEqual(self.client.batches.created, [])
        self.assertEqual(len(self.rig.queue.pending()), 1)

    def test_spend_already_at_the_cap_stops_calls_and_a_new_month_starts_fresh(self):
        self.rig.usage.record_call(provider=postmortems.PROVIDER, model="claude-haiku-5-5", status="ok", cost_usd=19.999, purpose="postmortem:fast")
        book = book_of(hound_data("u-1", [bet(1)]))
        out = self.e.tick(book)
        self.assertEqual(out["submit"]["reason"], "monthly_cap")
        self.assertEqual(self.client.batches.created, [])
        self.rig.clock.advance(days=5)                              # Nov 2: a new UTC month, a new budget
        self.assertEqual(self.e.tick(book)["submit"]["submitted"], 1)

    def test_the_cap_holds_for_the_batch_that_would_have_crossed_it(self):
        one = cost.worst_case_cost(*self.worst_args(), batch=True)
        self.e.env = dict(ENV, **{postmortems.ENV_CAP: str(round(one * 2.5, 6))})        # room for two requests, not three
        self.e.tick(book_of(hound_data("u-1", [bet(1), bet(2), bet(3)])))
        self.assertEqual(len(self.client.batches.created[0]), 2)
        self.assertLessEqual(self.e.committed(), self.e.cap())

    def worst_args(self):
        item = {"result": "loss", "hound_name": "Hound u-1", "rule_text": "Back a rested starter at plus money.", "reason": "Fires on a rested starter at plus money.",
                "game": "Team A1 at Team B1", "selection": "Team B1 moneyline", "market": "h2h", "date": "2026-10-28", "start_utc": "2026-10-28T23:05:00Z",
                "sport": "mlb", "price": 120, "price_average": 115, "clv_pts": 0.6, "units": -1.0}
        _, chars = pm.request_params(item, pm.DEPTH_FAST)
        model, max_tokens, uses, _ = pm.DEPTH_PLAN[pm.DEPTH_FAST]
        return model, chars, max_tokens, uses

    def test_strict_priority_a_member_request_that_does_not_fit_stops_the_line(self):
        deep_worst = cost.worst_case_cost(cost.SONNET, 4000, 8000, 6, batch=True)
        self.rig.queue.enqueue({"bet_key": "pm_" + "a" * 16, "hound_id": "u-1", "hound_name": "x", "result": "loss"}, store.TIER_MEMBER, "deep")
        self.rig.queue.enqueue({"bet_key": "pm_" + "b" * 16, "hound_id": "h-1", "hound_name": "y", "result": "loss"}, store.TIER_HOUSE, "fast")
        self.e.env = dict(ENV, **{postmortems.ENV_CAP: str(round(deep_worst * 0.5, 6))})
        out = self.e.tick(None)
        self.assertEqual(out["submit"]["reason"], "monthly_cap")                  # the cheap house request did not jump the member's

    def test_the_cost_of_a_missing_usage_is_the_worst_case_never_zero(self):
        book = book_of(hound_data("u-1", [bet(1, result="win", price=120)]))
        self.e.tick(book)
        cid = self.client.batches.created[0][0]["custom_id"]
        self.client.batches.answers[cid] = SimpleNamespace(type="succeeded", message=message(usage=None))
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        self.assertGreater(self.rig.usage.month_spend(postmortems.PROVIDER), 0.01)


# ---------------------------------------------------------------------------------------------------------------------
class TheFailures(WithRig):
    def collect_with(self, result, *, bets=None):
        book = book_of(hound_data("u-1", bets or [bet(1, result="win", price=120)]))
        self.e.tick(book)
        cid = self.client.batches.created[-1][0]["custom_id"]
        self.client.batches.answers[cid] = result
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        return book

    def test_an_answer_that_is_not_json_is_a_failure_that_still_costs_and_is_retried_once(self):
        book = self.collect_with(SimpleNamespace(type="succeeded", message=message(text="Sorry, I could not do this.")))
        self.assertEqual(self.rig.ledger.count(), 0)
        self.assertGreater(self.rig.usage.month_spend(postmortems.PROVIDER), 0)             # the call was made, so it is on the meter
        key = store.bet_key("u-1", book.hounds["u-1"].bets[0])
        item = self.rig.queue.get(key, "fast")
        self.assertEqual((item["status"], item["attempts"]), ("submitted", 1))               # back in line, and sent again for its one more try
        self.assertEqual(len(self.client.batches.created), 2)
        cid = self.client.batches.created[-1][0]["custom_id"]
        self.client.batches.answers[cid] = SimpleNamespace(type="succeeded", message=message(text="still not JSON"))
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        self.assertEqual(self.rig.queue.pending(), [])                                       # ...and a second failure is final
        self.assertEqual(self.rig.queue.counts()["failed"], 1)
        self.assertEqual(len(self.client.batches.created), 2)                                # no third try

    def test_a_refusal_is_final_with_no_retry(self):
        self.collect_with(SimpleNamespace(type="succeeded", message=message(text="", stop_reason="refusal")))
        self.assertEqual(self.rig.queue.pending(), [])
        self.assertEqual(self.rig.queue.counts()["failed"], 1)

    def test_a_paused_turn_is_not_stored_as_a_review(self):
        self.collect_with(SimpleNamespace(type="succeeded", message=message(text='{"half": ', stop_reason="pause_turn")))
        self.assertEqual(self.rig.ledger.count(), 0)

    def test_an_errored_request_costs_nothing_and_an_invalid_request_is_final(self):
        errored = SimpleNamespace(type="errored", error=SimpleNamespace(type="invalid_request"))
        self.collect_with(errored)
        self.assertEqual(self.rig.usage.month_spend(postmortems.PROVIDER), 0)
        self.assertEqual(self.rig.queue.counts()["failed"], 1)
        self.assertEqual(self.rig.queue.pending(), [])

    def test_a_server_error_or_an_expired_request_goes_back_in_line(self):
        book = self.collect_with(SimpleNamespace(type="expired"))
        item = self.rig.queue.get(store.bet_key("u-1", book.hounds["u-1"].bets[0]), "fast")
        self.assertEqual((item["status"], item["attempts"]), ("submitted", 1))

    def test_a_prompt_that_carries_a_person_or_a_key_is_refused_and_never_sent(self):
        data = hound_data("u-1", [bet(1, reason="Call me at 415-555-0100 or mail someone@example.com")])
        self.e.tick(book_of(data))
        self.assertEqual(self.client.batches.created, [])
        self.assertEqual(self.rig.queue.counts()["failed"], 1)
        self.assertEqual(self.rig.queue.pending(), [])
        rig = Rig()
        self.addCleanup(rig.close)
        rig.engine.tick(book_of(hound_data("u-1", [bet(1, reason=f"my key is {KEY}")])))
        self.assertEqual(rig.client.batches.created, [])

    def test_a_missing_answer_for_a_submitted_item_puts_it_back_in_line(self):
        book = book_of(hound_data("u-1", [bet(1, result="win", price=120)]))
        self.e.tick(book)
        self.client.batches.results = lambda batch_id: []
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        item = self.rig.queue.get(store.bet_key("u-1", book.hounds["u-1"].bets[0]), "fast")
        self.assertEqual(item["attempts"], 1)                                                # back in line, not lost

    def test_logs_and_reports_never_carry_the_key(self):
        self.client.batches.fail_create = RuntimeError(f"401 for key {KEY}")
        with self.assertLogs("linehound.ai.postmortems", level="DEBUG") as logs:
            report = self.e.tick(book_of(hound_data("u-1", [bet(1)])))
            logging.getLogger("linehound.ai.postmortems").error("sentinel")           # assertLogs needs at least one record
        text = "\n".join(logs.output) + json.dumps(report, default=str)
        self.assertNotIn(KEY, text)
        self.assertNotIn(KEY, open(self.rig.queue.path, encoding="utf-8").read())
        self.assertNotIn(KEY, open(self.rig.usage.path, encoding="utf-8").read())
        self.assertNotIn(KEY, repr(self.e.status()))


# ---------------------------------------------------------------------------------------------------------------------
class TheCoachingFeed(WithRig):
    SHAPE = {"hound_id", "label", "note", "as_of", "reviews", "grounded", "pending", "lessons", "factors", "luck_vs_process",
             "reason_relevance", "info_gaps", "paper_only"}

    def review_all(self, bets, hound="u-1", **review_over):
        book = book_of(hound_data(hound, bets))
        self.e.tick(book)
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        return book

    def test_a_hound_with_no_reviews_gets_the_same_shape_with_zeros(self):
        out = postmortems.summary_for("nobody", 5, engine=self.e)
        self.assertEqual(set(out), self.SHAPE)
        self.assertEqual((out["reviews"], out["lessons"], out["factors"], out["info_gaps"]), (0, [], {}, []))
        self.assertTrue(out["paper_only"])

    def test_the_summary_carries_lessons_and_per_factor_tallies(self):
        self.review_all([bet(1, result="loss"), bet(2, result="win", price=120), bet(3, result="loss")])
        out = postmortems.summary_for("u-1", 10, engine=self.e)
        self.assertEqual(set(out), self.SHAPE)
        self.assertEqual(out["reviews"], 3)
        self.assertEqual(out["factors"]["starter_performance"], {"n": 3, "wins": 1, "losses": 2})
        self.assertEqual(out["luck_vs_process"], {"mixed": 3})
        self.assertEqual(out["reason_relevance"], {"partly_valid": 3})
        self.assertEqual(out["label"], "Hindsight review")
        self.assertIn("after the result", out["note"])
        self.assertTrue(out["info_gaps"])
        lesson = out["lessons"][0]
        self.assertEqual(set(lesson), {"bet_key", "date", "game", "selection", "result", "lesson", "luck_vs_process", "reason_relevance", "depth", "sources"})
        self.assertEqual(lesson["sources"], 2)

    def test_identical_lessons_are_listed_once_and_the_limit_is_honoured(self):
        self.review_all([bet(i, result="loss") for i in range(1, 5)])
        self.assertEqual(len(postmortems.summary_for("u-1", 10, engine=self.e)["lessons"]), 1)           # same text four times
        distinct = Rig()
        self.addCleanup(distinct.close)
        book = book_of(hound_data("u-1", [bet(i, result="win", price=120) for i in range(1, 5)]))
        distinct.engine.tick(book)
        for req in distinct.client.batches.created[0]:
            distinct.client.batches.answers[req["custom_id"]] = ok_result(review=review_json(lesson=f"Lesson number {req['custom_id'][3:9]} is distinct."))
        distinct.clock.advance(minutes=30)
        distinct.engine.tick(book)
        self.assertEqual(len(postmortems.summary_for("u-1", 10, engine=distinct.engine)["lessons"]), 4)
        self.assertEqual(len(postmortems.summary_for("u-1", 2, engine=distinct.engine)["lessons"]), 2)

    def test_an_unsourced_review_is_counted_but_never_fed_to_a_prompt(self):
        book = book_of(hound_data("u-1", [bet(1, result="win", price=120)]))
        self.e.tick(book)
        cid = self.client.batches.created[0][0]["custom_id"]
        self.client.batches.answers[cid] = SimpleNamespace(type="succeeded", message=message(urls={}))
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        out = postmortems.summary_for("u-1", 10, engine=self.e)
        self.assertEqual((out["reviews"], out["grounded"]), (1, 0))
        self.assertEqual((out["lessons"], out["factors"], out["info_gaps"]), ([], {}, []))

    def test_the_deep_review_stands_in_for_the_fast_one_and_one_bet_counts_once(self):
        book = book_of(hound_data("u-1", [bet(1, result="loss")]))
        self.e.tick(book)
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)                                           # the fast review is collected, the deep request goes out
        cid = self.client.batches.created[-1][0]["custom_id"]
        self.client.batches.answers[cid] = ok_result(review=review_json(deeper_notes="The closer was unavailable after 40 pitches the night before.",
                                                                          lesson="Check the closer's recent workload.", factor_tags=["bullpen_or_depth"]))
        self.rig.clock.advance(minutes=30)
        self.e.tick(book)
        out = postmortems.summary_for("u-1", 10, engine=self.e)
        self.assertEqual(out["reviews"], 1)
        self.assertEqual(out["factors"], {"bullpen_or_depth": {"n": 1, "wins": 0, "losses": 1}})
        self.assertEqual(out["lessons"][0]["depth"], "deep")

    def test_the_summary_never_raises_even_with_an_unreadable_engine(self):
        class Broken:
            def summary_for(self, *a, **k):
                raise OSError("disk gone")
        out = postmortems.summary_for("u-1", 5, engine=Broken())
        self.assertEqual(set(out), self.SHAPE)
        self.assertEqual(out["reviews"], 0)

    def test_pending_counts_the_hounds_own_waiting_bets(self):
        self.e.tick(book_of(hound_data("u-1", [bet(1), bet(2)])))
        self.assertEqual(postmortems.summary_for("u-1", 5, engine=self.e)["pending"], 2)
        self.assertEqual(postmortems.summary_for("other", 5, engine=self.e)["pending"], 0)

    def test_reviews_for_a_hound_come_back_keyed_by_bet_with_the_label_and_no_cost(self):
        book = self.review_all([bet(1, result="win", price=120)])
        key = store.bet_key("u-1", book.hounds["u-1"].bets[0])
        got = self.e.reviews_for_hound("u-1")
        self.assertEqual(list(got), [key])
        self.assertEqual(got[key]["label"], "Hindsight review")
        self.assertNotIn("cost_usd", got[key])
        self.assertNotIn("batch_id", got[key])
        self.assertEqual(self.e.review_for(key)["depth"], "fast")
        self.assertIsNone(self.e.review_for("pm_" + "0" * 16))


# ---------------------------------------------------------------------------------------------------------------------
class TheImageAndTheVolume(unittest.TestCase):
    """New files must be in the Docker image (the Dockerfile copies whole trees), and the runtime stores must be on the volume, not in it."""

    REPO = os.path.join(os.path.dirname(__file__), "..")

    def read(self, *parts):
        return open(os.path.join(self.REPO, *parts), encoding="utf-8").read()

    def test_every_new_file_lives_under_a_tree_the_dockerfile_copies_and_the_dockerignore_admits(self):
        dockerfile, ignore = self.read("deploy", "Dockerfile"), self.read(".dockerignore")
        for tree in ("COPY src/ src/", "COPY api/ api/", "COPY web/ web/"):
            self.assertIn(tree, dockerfile)
        new_files = ["src/ai/postmortems.py", "src/ai/postmortem_cost.py", "src/ai/postmortem_parse.py", "src/ai/postmortem_store.py",
                     "src/hounds/bet_export.py", "api/hounds_postmortems.py", "web/js/record-postmortems.js"]
        ignored = [ln.strip() for ln in ignore.splitlines() if ln.strip() and not ln.startswith(("#", "!"))]
        for path in new_files:
            self.assertTrue(os.path.exists(os.path.join(self.REPO, path)), path)
            self.assertFalse(any(path == i or path.startswith(i.rstrip("/") + "/") for i in ignored), path)

    def test_the_queue_and_the_ledger_default_to_files_beside_the_app_database(self):
        from src.appstate import users as users_store
        queue, ledger = store.default_paths({})
        base = users_store.db_path().parent
        self.assertEqual((queue.parent, ledger.parent), (base, base))
        self.assertEqual((queue.name, ledger.name), (store.QUEUE_FILE, store.LEDGER_FILE))
        self.assertNotIn(os.path.join("evidence"), str(queue))

    def test_the_paths_can_be_overridden_by_env(self):
        q, l = store.default_paths({store.ENV_QUEUE: "/vol/q.jsonl", store.ENV_LEDGER: "/vol/l.jsonl"})
        self.assertEqual((str(q).replace("\\", "/"), str(l).replace("\\", "/")), ("/vol/q.jsonl", "/vol/l.jsonl"))

    def test_the_documented_cost_per_bet_follows_from_the_price_table(self):
        fast = cost.usage_cost(cost.HAIKU, {"input_tokens": 25000, "output_tokens": 2000, "server_tool_use": {"web_search_requests": 3}}, batch=True)
        deep = cost.usage_cost(cost.SONNET, {"input_tokens": 80000, "output_tokens": 5000, "server_tool_use": {"web_search_requests": 6}}, batch=True)
        self.assertAlmostEqual(fast, 0.0318, places=3)
        self.assertAlmostEqual(deep, 0.165, places=3)
        average = fast + 0.45 * deep                                  # every bet is reviewed fast; a loss or a big win is reviewed deep
        self.assertAlmostEqual(average, 0.106, places=2)
        self.assertGreater(postmortems.POSTMORTEM_MONTHLY_USD / average, 150)


class TheLoopHook(unittest.TestCase):
    """The tick rides the live-settle loop: after each pass, in its thread, never able to stop it."""

    def run_loop(self, after_pass, passes=2):
        from src.hounds import live_settle
        stop = threading.Event()
        seen = []

        def do_pass():
            seen.append("pass")
            if seen.count("pass") >= passes:
                stop.set()

        thread = live_settle.start_loop(interval_s=0.01, stop_event=stop, env={"LIVE_SETTLE": "on"}, do_pass=do_pass,
                                        after_pass=lambda: (seen.append("after"), after_pass())[1])
        thread.join(5)
        return seen

    def test_the_hook_runs_after_every_pass(self):
        seen = self.run_loop(lambda: None)
        self.assertEqual(seen[:4], ["pass", "after", "pass", "after"])

    def test_a_hook_that_raises_does_not_stop_the_loop(self):
        def boom():
            raise RuntimeError("bug")
        with self.assertLogs("linehound.hounds.live_settle", level="ERROR"):
            seen = self.run_loop(boom)
        self.assertEqual(seen.count("pass"), 2)

    def test_the_app_wires_the_tick_into_the_loop(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "api", "app.py"), encoding="utf-8").read()
        self.assertIn("after_pass=postmortems.tick_safely", src)
        self.assertIn("app.include_router(hounds_postmortems_router)", src)
        self.assertLess(src.index("app.include_router(hounds_tips_router)"), src.index("app.include_router(hounds_postmortems_router)"))

    def test_tick_safely_never_raises(self):
        postmortems.reset_default_engine()
        self.addCleanup(postmortems.reset_default_engine)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            env = {store.ENV_QUEUE: os.path.join(tmp, "q.jsonl"), store.ENV_LEDGER: os.path.join(tmp, "l.jsonl"),
                   "AI_USAGE_PATH": os.path.join(tmp, "u.jsonl"), "ANTHROPIC_API_KEY": ""}
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                out = postmortems.tick_safely(book=None)
                bad = postmortems.tick_safely(book=object())              # a book of the wrong shape: a named error, not an exception
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        self.assertEqual(out.get("waiting"), "no_api_key")
        self.assertIn("error", bad)


if __name__ == "__main__":
    unittest.main()
