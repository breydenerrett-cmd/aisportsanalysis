"""The one-time backfill of hindsight reviews (src/ai/postmortems.py, config/postmortem_backfill.json; owner ask 2026-10-28).

    "All hounds need to do a DEEP analysis on their previous and current results; all previous results in previous versions still need
    record kept and stored somewhere even if not presented to users in an easy fashion."

Bets graded BEFORE the reviews began are reviewed once, newest first, through the same requests and the same Message Batches path, behind
their own one-time dollar wall. With the switch off nothing is queued and nothing is spent. Every test fakes the client and the clock and
points every store at a temp dir: nothing here touches the network or the repository's data.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from src.ai import postmortem_cost as cost
from src.ai import postmortem_parse as pm
from src.ai import postmortem_store as store
from src.ai import postmortems
from tests.backfill_fixtures import BackfillRig, many_old_bets, old_bet
from tests.postmortem_fixtures import KEY, NOW, bet, book_of, hound_data, message

ROOT = Path(__file__).resolve().parent.parent
PB = postmortems.PROVIDER_BACKFILL


class WithRig(unittest.TestCase):
    ON = True
    CAP = 25.0

    def setUp(self):
        self.rig = BackfillRig(on=self.ON, cap=self.CAP)
        self.addCleanup(self.rig.close)
        self.e, self.client = self.rig.engine, self.rig.client


# ---------------------------------------------------------------------------------------------------------------------
class TheSwitch(unittest.TestCase):
    def test_the_committed_file_is_off_with_a_25_dollar_wall(self):
        raw = (ROOT / "config" / "postmortem_backfill.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw), {"on": False, "cap_usd": 25})
        self.assertEqual(postmortems.load_backfill_config(), {"on": False, "cap_usd": 25.0})

    def test_the_loader_is_safe_by_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            def write(text):
                path = Path(tmp) / "c.json"
                path.write_text(text, encoding="utf-8")
                return postmortems.load_backfill_config(path)
            self.assertEqual(postmortems.load_backfill_config(Path(tmp) / "missing.json"), {"on": False, "cap_usd": 0.0})
            self.assertEqual(write("{not json"), {"on": False, "cap_usd": 0.0})
            self.assertEqual(write("[1, 2]"), {"on": False, "cap_usd": 0.0})
            self.assertFalse(write('{"on": "true", "cap_usd": 25}')["on"])               # only the JSON value true switches it on
            self.assertFalse(write('{"on": 1, "cap_usd": 25}')["on"])
            self.assertEqual(write('{"on": true}'), {"on": True, "cap_usd": 0.0})        # no wall named means nothing can be spent
            self.assertEqual(write('{"on": true, "cap_usd": "25"}')["cap_usd"], 0.0)
            self.assertEqual(write('{"on": true, "cap_usd": -5}')["cap_usd"], 0.0)
            self.assertEqual(write('{"on": true, "cap_usd": NaN}')["cap_usd"], 0.0)
            self.assertEqual(write('{"on": true, "cap_usd": 12.5}'), {"on": True, "cap_usd": 12.5})

    def test_the_file_the_loader_reads_ships_in_the_image(self):
        path = postmortems.BACKFILL_CONFIG_PATH
        self.assertTrue(path.is_absolute() and path.is_file())
        self.assertEqual(path.relative_to(ROOT).as_posix(), "config/postmortem_backfill.json")
        self.assertRegex((ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8"), re.compile(r"^COPY config/ config/\s*$", re.M))
        ignore = [ln.strip() for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
        self.assertFalse(any(rule.rstrip("/") in ("config", "config/*", "/config") or rule.endswith("postmortem_backfill.json") for rule in ignore))

    def test_the_engine_reads_the_switch_fresh_every_tick(self):
        rig = BackfillRig(on=False)
        self.addCleanup(rig.close)
        book = book_of(hound_data("u-1", many_old_bets("u-1", 3)))
        self.assertEqual(rig.tick(book)["backfill"], {"on": False})
        rig.cfg["on"] = True
        self.assertEqual(rig.tick(book)["backfill"]["bets_queued"], 3)

    def test_a_config_that_raises_is_off_not_a_failed_tick(self):
        rig = BackfillRig(on=True)
        self.addCleanup(rig.close)

        def boom():
            raise OSError("disk")
        rig.engine._backfill_config = boom                                                   # noqa: SLF001
        with self.assertLogs("linehound.ai.postmortems", level="ERROR"):
            out = rig.tick(book_of(hound_data("u-1", [bet(1)])))
        self.assertEqual(out["backfill"], {"on": False})
        self.assertIn("submit", out)                                                         # the live reviews still ran


class SwitchedOff(WithRig):
    ON = False

    def test_off_queues_nothing_spends_nothing_and_sends_no_backfill_batch(self):
        old = many_old_bets("u-1", 30)
        fresh = bet(99, result="loss")                                                       # graded after reviews began: the live flow
        out = self.rig.tick(book_of(hound_data("u-1", old + [fresh])))
        self.assertEqual(out["backfill"], {"on": False})
        self.assertNotIn("backfill_submit", out)
        self.assertEqual(self.rig.backfill_items(), [])
        self.assertNotIn("backfill", self.rig.queue_text())                                  # not one line of the log is a backfill line
        self.assertEqual(len(self.client.batches.created), 1)                                # only the live bet went out
        self.assertEqual(len(self.client.batches.created[0]), 1)
        self.assertEqual(self.rig.usage.total_spend(PB) + self.rig.usage.reserved_total(PB), 0)
        self.assertEqual(self.e.status()["backfill"]["on"], False)

    def test_off_with_no_key_and_no_book_is_still_a_no_op(self):
        rig = BackfillRig(on=False, env={})
        self.addCleanup(rig.close)
        self.assertEqual(rig.tick(None)["backfill"], {"on": False})
        self.assertFalse(os.path.exists(rig.queue.path))

    def test_the_default_engine_reads_the_committed_file_so_a_fresh_checkout_does_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            q = store.QueueStore(os.path.join(tmp, "q.jsonl"))
            engine = postmortems.Engine(queue=q, ledger=store.ReviewLedger(os.path.join(tmp, "l.jsonl")),
                                        usage=postmortems.UsageStore(os.path.join(tmp, "u.jsonl")), env={}, peek_book=lambda: None)
            self.assertEqual(engine._backfill_cfg(), {"on": False, "cap_usd": 25.0})        # noqa: SLF001
            out = engine.tick(book_of(hound_data("u-1", many_old_bets("u-1", 5))))
            self.assertEqual(out["backfill"], {"on": False})
            self.assertEqual(q.counts(origin=store.ORIGIN_BACKFILL), {"pending": 0, "submitted": 0, "done": 0, "failed": 0})


# ---------------------------------------------------------------------------------------------------------------------
class TheCatchUp(WithRig):
    def plan(self, *datas):
        book = book_of(*datas)
        self.e.scan(book)
        return self.e.backfill_plan(book, self.rig.cfg)

    def test_past_bets_are_queued_newest_first(self):
        bets = [old_bet(n, day=d) for d in (3, 9, 5, 7, 1) for n in (d * 10, d * 10 + 1)]
        self.plan(hound_data("u-1", bets))
        order = [i["bet"]["date"] for i in self.rig.queue.pending(store.ORIGIN_BACKFILL)]
        self.assertEqual(order, sorted(order, reverse=True))
        self.assertEqual(order[0], "2026-10-09")
        self.assertEqual(len(order), 10)

    def test_newest_first_also_orders_across_hounds(self):
        a = hound_data("u-1", [old_bet(1, "u-1", day=2), old_bet(2, "u-1", day=8)])
        b = hound_data("h-1", [old_bet(3, "h-1", day=5)], kind="house", category="stats")
        self.plan(a, b)
        self.assertEqual([i["bet"]["date"][-2:] for i in self.rig.queue.pending(store.ORIGIN_BACKFILL)], ["08", "05", "02"])

    def test_only_settled_forward_wins_and_losses_are_queued_never_a_replay_row(self):
        bets = [old_bet(1, result="loss"), old_bet(2, result="win"), old_bet(3, result="push"), old_bet(4, result="void"),
                old_bet(5, result=None), old_bet(6, result="loss", segment="replay"), old_bet(7, result="win", segment="replay")]
        self.rig.tick(book_of(hound_data("u-1", bets)))
        keys = {i["bet_key"] for i in self.rig.backfill_items()}
        self.assertEqual(keys, {store.bet_key("u-1", bets[0]), store.bet_key("u-1", bets[1])})

    def test_baseline_controls_are_never_reviewed(self):
        self.rig.tick(book_of(hound_data("b-1", [old_bet(1, "b-1")], kind="baseline", category="baseline")))
        self.assertEqual(self.rig.backfill_items(), [])

    def test_every_version_is_covered_a_retired_one_and_a_pack_archive_too(self):
        v1 = hound_data("u-1", [old_bet(1, "u-1")], kind="user")                           # a retired version keeps its own id and bets
        v2 = hound_data("u-2", [old_bet(2, "u-2")], kind="user")
        pack_old = hound_data("pk@v1", [old_bet(3, "pk@v1")], kind="house", category="stats")
        pack_now = hound_data("pk", [old_bet(4, "pk")], kind="house", category="stats")
        self.rig.tick(book_of(v1, v2, pack_old, pack_now))
        self.assertEqual({i["hound_id"] for i in self.rig.backfill_items(pm.DEPTH_FAST)}, {"u-1", "u-2", "pk@v1", "pk"})

    def test_a_second_pass_queues_nothing_twice(self):
        book = book_of(hound_data("u-1", many_old_bets("u-1", 8)))
        self.rig.tick(book)
        before = self.rig.queue_text()
        again = self.e.backfill_plan(book, self.rig.cfg)
        self.assertEqual((again["bets_queued"], again["lineages_queued"]), (0, 0))
        self.assertEqual(self.rig.queue_text(), before)                                      # not one byte appended by a re-plan

    def test_a_bet_already_reviewed_or_already_queued_is_skipped(self):
        bets = many_old_bets("u-1", 4)
        data = hound_data("u-1", bets)
        reviewed = store.bet_key("u-1", bets[0])
        snap = postmortems.snapshot(data.summary, bets[0], reviewed)
        self.rig.ledger.append(bet=snap, depth=pm.DEPTH_FAST, model="claude-haiku-5-5", review={"lesson": "x"}, cost_usd=0.03, web_searches=3, batch_id="b")
        queued_live = store.bet_key("u-1", bets[1])
        self.rig.queue.enqueue(postmortems.snapshot(data.summary, bets[1], queued_live), store.TIER_MEMBER)
        self.rig.tick(book_of(data))
        mine = {i["bet_key"] for i in self.rig.backfill_items()}
        self.assertEqual(mine, {store.bet_key("u-1", bets[2]), store.bet_key("u-1", bets[3])})
        self.assertEqual(self.rig.queue.get(queued_live, pm.DEPTH_FAST)["origin"], store.ORIGIN_LIVE)

    def test_a_bet_the_live_scan_already_owns_is_not_taken_again(self):
        fresh = bet(1, result="loss")
        self.rig.tick(book_of(hound_data("u-1", [fresh])))
        self.assertEqual(self.rig.backfill_items(), [])
        self.assertEqual(self.rig.queue.get(store.bet_key("u-1", fresh), pm.DEPTH_FAST)["origin"], store.ORIGIN_LIVE)

    def test_only_a_window_of_past_bets_is_queued_at_a_time_and_the_rest_is_counted(self):
        self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 90))))
        self.assertEqual(len(self.rig.backfill_items(pm.DEPTH_FAST)), postmortems.BACKFILL_WINDOW)
        status = self.e.status()["backfill"]
        self.assertEqual(status["bets"]["remaining"], 90 - postmortems.BACKFILL_WINDOW)
        newest = max(i["bet"]["date"] for i in self.rig.backfill_items())
        self.assertEqual(newest, "2026-10-10")

    def test_the_learner_is_sampled_one_in_five_with_no_log_line_for_the_ones_passed_over(self):
        book = book_of(hound_data("learner", many_old_bets("learner", 120), kind="house", category="learner"))
        self.rig.tick(book)
        kept = len(self.rig.backfill_items(pm.DEPTH_FAST))
        want = sum(1 for b in book.hounds["learner"].bets if pm.sample_hit(store.bet_key("learner", b), postmortems.LEARNER_SAMPLE_ONE_IN))
        self.assertEqual(kept, want)
        self.assertNotIn('"skipped"', self.rig.queue_text())
        self.assertGreater(kept, 120 * 0.10)
        self.assertLess(kept, 120 * 0.32)

    def test_the_catch_up_continues_as_batches_are_read(self):
        book = book_of(hound_data("u-1", many_old_bets("u-1", 90, result_cycle=("win",))))
        for _ in range(12):
            self.rig.tick(book, minutes=30)
        done = self.e.status()["backfill"]["bets"]
        self.assertEqual(done["done"] + done["queued"] + done["failed"] + done["remaining"], 90)
        self.assertEqual((done["remaining"], done["queued"], done["failed"]), (0, 0, 0))
        self.assertEqual(done["done"], 90)


# ---------------------------------------------------------------------------------------------------------------------
class TheLanes(WithRig):
    def test_live_reviews_go_first_in_their_own_batch_and_the_backfill_rides_another(self):
        book = book_of(hound_data("u-1", [bet(99, result="loss")] + many_old_bets("u-1", 25)))
        out = self.rig.tick(book)
        self.assertEqual(out["submit"]["submitted"], 1)
        self.assertEqual(out["backfill_submit"]["submitted"], 20)
        live, past = self.client.batches.created
        self.assertEqual(len(live), 1)
        live_keys = {pm.split_custom_id(r["custom_id"])[0] for r in live}
        past_keys = {pm.split_custom_id(r["custom_id"])[0] for r in past}
        self.assertFalse(live_keys & past_keys)
        self.assertEqual(self.rig.queue.get(next(iter(live_keys)), pm.DEPTH_FAST)["origin"], store.ORIGIN_LIVE)
        self.assertTrue(all(self.rig.queue.get(k, pm.DEPTH_FAST)["origin"] == store.ORIGIN_BACKFILL for k in past_keys))

    def test_pending_lists_live_items_before_backfill_ones(self):
        data = hound_data("u-1", many_old_bets("u-1", 3))
        self.rig.queue.enqueue(postmortems.snapshot(data.summary, data.bets[0], "pm_" + "a" * 16), store.TIER_LEARNER, pm.DEPTH_FAST,
                               origin=store.ORIGIN_BACKFILL)
        self.rig.queue.enqueue({"bet_key": "pm_" + "b" * 16, "hound_id": "x", "date": "2026-01-01"}, store.TIER_LEARNER)
        self.assertEqual([i["origin"] for i in self.rig.queue.pending()], [store.ORIGIN_LIVE, store.ORIGIN_BACKFILL])

    def test_a_backfill_batch_never_delays_a_live_one_each_origin_keeps_its_own_clock(self):
        self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 25))))
        self.assertEqual(len(self.client.batches.created), 1)
        self.assertIsNone(self.rig.queue.last_submit(store.ORIGIN_LIVE))
        self.assertIsNotNone(self.rig.queue.last_submit(store.ORIGIN_BACKFILL))
        out = self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 25) + [bet(99, result="loss")])), minutes=1)
        self.assertEqual(out["submit"]["submitted"], 1)                                      # a minute later, live goes at once

    def test_the_backfill_waits_between_small_batches(self):
        wins = ("win",)                                                                       # a small win earns no deep pass
        book = book_of(hound_data("u-1", many_old_bets("u-1", 5, result_cycle=wins)))
        self.assertEqual(self.rig.tick(book)["backfill_submit"]["submitted"], 5)
        book2 = book_of(hound_data("u-1", many_old_bets("u-1", 5, result_cycle=wins) + many_old_bets("u-1", 5, first_n=50, day=9, result_cycle=wins)))
        out = self.rig.tick(book2, minutes=1)
        self.assertEqual(out["backfill_submit"]["reason"], "batching")
        self.assertEqual(self.rig.tick(book2, minutes=30)["backfill_submit"]["submitted"], 5)

    def test_at_most_three_backfill_batches_are_unread_at_once(self):
        self.client.batches.status = "in_progress"
        book = book_of(hound_data("u-1", many_old_bets("u-1", 90)))
        reasons = [self.rig.tick(book, minutes=1)["backfill_submit"] for _ in range(4)]
        self.assertEqual([r.get("submitted") for r in reasons[:3]], [20, 20, 20])
        self.assertEqual(len(self.client.batches.created), postmortems.BACKFILL_MAX_OPEN_BATCHES)
        # three unread batches hold the whole window; anything more that is waiting (a deep pass, a Deep review) waits for one to be read
        self.rig.queue.enqueue({"bet_key": "pm_" + "d" * 16, "hound_id": "u-1", "date": "2026-10-10"}, store.TIER_MEMBER, pm.DEPTH_DEEP,
                               origin=store.ORIGIN_BACKFILL)
        out = self.e.submit_backfill(self.client, self.rig.cfg)
        self.assertEqual(out["reason"], "batches_open")
        self.assertEqual(len(self.client.batches.created), 3)

    def test_a_cooling_provider_holds_the_backfill_too(self):
        self.rig.usage.record_cooldown(postmortems.PROVIDER, NOW + timedelta(hours=1), "429")
        out = self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 25))))
        self.assertEqual(out["backfill_submit"], {"submitted": 0, "reason": "cooling_down"})

    def test_no_key_queues_the_window_and_waits_to_send(self):
        rig = BackfillRig(on=True, env={})
        self.addCleanup(rig.close)
        out = rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 5))))
        self.assertEqual(out["waiting"], "no_api_key")
        self.assertEqual(out["backfill"]["bets_queued"], 5)
        self.assertEqual(rig.client.batches.created, [])


# ---------------------------------------------------------------------------------------------------------------------
class TheRequestsAreTheExistingOnes(WithRig):
    def test_a_backfill_request_is_byte_for_byte_a_live_request(self):
        bets = many_old_bets("u-1", 3)
        data = hound_data("u-1", bets)
        self.rig.tick(book_of(data))
        for req in self.client.batches.created[0]:
            key, depth = pm.split_custom_id(req["custom_id"])
            snap = self.rig.queue.get(key, depth)["bet"]
            self.assertEqual(req["params"], pm.request_params(snap, depth)[0])
            self.assertEqual(req["params"]["model"], "claude-haiku-5-5")
            self.assertEqual(req["params"]["tools"][0]["type"], "web_search_20250305")
            self.assertEqual(req["params"]["tools"][0]["max_uses"], 3)
            self.assertIn("HINDSIGHT", req["params"]["system"])

    def test_a_backfilled_loss_earns_the_deep_pass_on_the_backfill_lane_and_it_sees_the_fast_review(self):
        bets = [old_bet(1, result="loss"), old_bet(2, result="win", price=110)]
        book = book_of(hound_data("u-1", bets))
        self.rig.tick(book)
        self.rig.tick(book, minutes=30)                         # reads the fast batch, queues the loss's deep pass and sends it
        deep = self.rig.backfill_items(pm.DEPTH_DEEP)
        self.assertEqual([i["bet_key"] for i in deep], [store.bet_key("u-1", bets[0])])
        self.assertEqual(deep[0]["origin"], store.ORIGIN_BACKFILL)
        sonnet = [r for batch in self.client.batches.created for r in batch if r["params"]["model"] == "claude-sonnet-5-5"]
        self.assertEqual(len(sonnet), 1)
        self.assertIn("THE EARLIER FAST REVIEW", sonnet[0]["params"]["messages"][0]["content"])
        self.assertEqual(sonnet[0]["params"]["tools"][0]["type"], "web_search_20260209")


# ---------------------------------------------------------------------------------------------------------------------
class TheWall(WithRig):
    def test_the_money_is_the_apis_own_usage_under_the_backfill_label_and_the_month_never_sees_it(self):
        book = book_of(hound_data("u-1", many_old_bets("u-1", 4, result_cycle=("win",))))
        self.rig.tick(book)
        self.assertGreater(self.rig.usage.reserved_total(PB), 0)
        self.assertEqual(self.rig.usage.reserved(postmortems.PROVIDER), 0)                   # the month's wall holds nothing for it
        self.rig.tick(book, minutes=30)
        want = 4 * cost.usage_cost(cost.HAIKU, message().usage, batch=True)
        self.assertAlmostEqual(self.rig.usage.total_spend(PB), want, places=8)
        self.assertEqual(self.rig.usage.month_spend(postmortems.PROVIDER), 0)
        self.assertEqual(self.e.committed(), 0)                                              # the $20 a month wall is untouched
        self.assertEqual(self.rig.usage.reserved_total(PB), 0)                               # read, so the reservation is released
        self.assertAlmostEqual(self.e.status()["backfill"]["spent_usd"], want, places=8)

    def test_the_wall_holds_for_the_batch_that_would_have_crossed_it(self):
        data = hound_data("u-1", many_old_bets("u-1", 25, result_cycle=("win",)))
        probe = BackfillRig(on=True)                                                         # same bets, same order: learn what each request reserves
        self.addCleanup(probe.close)
        probe.tick(book_of(data))
        worst = [probe.worst_of(pm.split_custom_id(r["custom_id"])[0]) for r in probe.client.batches.created[0]]
        self.rig.cfg["cap_usd"] = sum(worst[:5]) + 1e-6
        out = self.rig.tick(book_of(data))
        self.assertEqual(out["backfill_submit"]["submitted"], 5)                             # the sixth did not fit, so the line stopped
        self.assertLessEqual(self.rig.usage.reserved_total(PB), self.rig.cfg["cap_usd"])
        again = self.rig.tick(book_of(data), minutes=30)
        self.assertEqual(again["backfill_submit"]["submitted"], 0)
        self.assertLessEqual(self.e.backfill_committed(), self.rig.cfg["cap_usd"])

    def test_a_zero_wall_queues_and_sends_nothing(self):
        self.rig.cfg["cap_usd"] = 0.0
        out = self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 5))))
        self.assertEqual(out["backfill"]["waiting"], "backfill_cap")
        self.assertEqual(self.rig.backfill_items(), [])
        self.assertEqual(self.client.batches.created, [])

    def test_the_two_walls_are_separate_a_spent_month_does_not_stop_the_backfill_and_the_backfill_does_not_spend_the_month(self):
        rig = BackfillRig(on=True, month_cap=0)                                              # the $20 a month wall is shut
        self.addCleanup(rig.close)
        out = rig.tick(book_of(hound_data("u-1", [bet(99, result="loss")] + many_old_bets("u-1", 5))))
        self.assertEqual(out["submit"]["reason"], "monthly_cap")                             # the live review waits
        self.assertEqual(out["backfill_submit"]["submitted"], 5)                             # the backfill does not
        rig.tick(book_of(hound_data("u-1", [bet(99, result="loss")] + many_old_bets("u-1", 5))), minutes=30)
        self.assertEqual(rig.usage.month_spend(postmortems.PROVIDER), 0)

    def test_the_wall_is_one_time_it_sums_every_month_and_a_batch_that_outlives_the_month_still_reserves(self):
        self.rig.usage.record_call(provider=PB, model="m", status="ok", cost_usd=1.5)
        self.rig.clock.advance(days=40)                                                      # a new month
        self.rig.usage.record_call(provider=PB, model="m", status="ok", cost_usd=2.0)
        self.assertEqual(self.rig.usage.month_spend(PB), 2.0)
        self.assertEqual(self.rig.usage.total_spend(PB), 3.5)
        self.assertEqual(self.e.backfill_spent(), 3.5)
        self.client.batches.status = "in_progress"
        book = book_of(hound_data("u-1", many_old_bets("u-1", 25)))
        self.rig.tick(book)
        held = self.rig.usage.reserved_total(PB)
        self.assertGreater(held, 0)
        self.rig.clock.advance(days=40)                                                      # and another
        self.assertEqual(self.rig.usage.reserved(PB), 0)                                     # the month view forgot it ...
        self.assertEqual(self.rig.usage.reserved_total(PB), held)                            # ... the one-time wall did not
        self.assertEqual(self.e.backfill_committed(), round(3.5 + held, 8))

    def test_spent_money_that_reaches_the_wall_stops_new_batches(self):
        self.rig.usage.record_call(provider=PB, model="m", status="ok", cost_usd=self.CAP)
        out = self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 25))))
        self.assertEqual(out["backfill"]["waiting"], "backfill_cap")
        self.assertEqual(len(self.client.batches.created), 0)

    def test_a_missing_usage_is_charged_its_worst_case_never_zero(self):
        book = book_of(hound_data("u-1", many_old_bets("u-1", 1, result_cycle=("win",))))
        self.rig.tick(book)
        key = self.rig.backfill_items()[0]["bet_key"]
        cid = pm.custom_id(key, pm.DEPTH_FAST)
        self.client.batches.answers[cid] = SimpleNamespace(type="succeeded", message=message(usage=None))
        self.rig.tick(book, minutes=30)
        self.assertGreater(self.rig.usage.total_spend(PB), 0)

    def test_the_backfill_cost_per_bet_follows_from_the_price_table(self):
        fast = cost.usage_cost(cost.HAIKU, {"input_tokens": 25000, "output_tokens": 2000, "server_tool_use": {"web_search_requests": 3}}, batch=True)
        deep = cost.usage_cost(cost.SONNET, {"input_tokens": 80000, "output_tokens": 5000, "server_tool_use": {"web_search_requests": 6}}, batch=True)
        average = fast + 0.45 * deep                                                         # every bet fast; a loss or a big win deep as well
        self.assertAlmostEqual(average, 0.106, places=2)
        self.assertGreater(25.0 / average, 200)                                              # the $25 wall covers more than 200 past bets in full

    def test_logs_and_status_never_carry_the_key(self):
        with self.assertLogs("linehound.ai.postmortems", level="DEBUG") as logs:
            postmortems.logger.error("probe")
            self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 6))))
            self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 6))), minutes=30)
        self.assertNotIn(KEY, "\n".join(logs.output))
        self.assertNotIn(KEY, repr(self.e.status()))
        self.assertNotIn(KEY, self.rig.queue_text())


# ---------------------------------------------------------------------------------------------------------------------
class TheProgress(WithRig):
    def test_the_status_shows_done_queued_remaining_and_spent(self):
        book = book_of(hound_data("u-1", many_old_bets("u-1", 90, result_cycle=("win",))))
        status = self.e.status()["backfill"]
        self.assertEqual((status["on"], status["cap_usd"], status["spent_usd"]), (True, 25.0, 0.0))
        self.assertIsNone(status["bets"]["remaining"])                                       # nothing has been counted yet
        self.rig.tick(book)
        bets = self.e.status()["backfill"]["bets"]
        self.assertEqual((bets["done"], bets["queued"], bets["remaining"]), (0, postmortems.BACKFILL_WINDOW, 90 - postmortems.BACKFILL_WINDOW))
        self.rig.tick(book, minutes=30)
        after = self.e.status()["backfill"]
        self.assertEqual(after["bets"]["done"], 20)
        self.assertGreater(after["spent_usd"], 0)
        self.assertGreater(after["reserved_usd"], 0)                                         # the next batch is out and holds its worst case

    def test_the_tick_report_carries_the_plan(self):
        out = self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 3))))
        self.assertEqual(out["backfill"]["on"], True)
        self.assertEqual(out["backfill"]["bets_queued"], 3)

    def test_the_live_queue_counts_do_not_include_the_backfill(self):
        self.rig.tick(book_of(hound_data("u-1", many_old_bets("u-1", 3) + [bet(99, result="loss")])))
        self.assertEqual(sum(self.e.status()["queue"].values()), 1)

    def test_status_safely_merges_the_last_tick_and_never_raises(self):
        out = postmortems.status_safely(engine=self.e)
        self.assertIn("backfill", out)
        self.assertIn("ticks", out)

        class Broken:
            def status(self):
                raise RuntimeError("no")
        self.assertEqual(postmortems.status_safely(engine=Broken()), {"error": "RuntimeError"})


# ---------------------------------------------------------------------------------------------------------------------
class TheUsageMeter(unittest.TestCase):
    def test_the_two_new_aggregates_sum_every_month_for_one_provider(self):
        import tempfile
        from src.ai.usage import UsageStore
        from tests.postmortem_fixtures import Clock
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock(NOW)
            u = UsageStore(os.path.join(tmp, "u.jsonl"), clock=clock)
            u.record_call(provider="a", model="m", status="ok", cost_usd=1.0)
            u.record_batch_submit(batch_id="b1", provider="a", model="m", reserved_usd=0.5, n_requests=1)
            clock.advance(days=45)
            u.record_call(provider="a", model="m", status="ok", cost_usd=2.0)
            u.record_call(provider="b", model="m", status="ok", cost_usd=9.0)
            u.record_batch_submit(batch_id="b2", provider="a", model="m", reserved_usd=0.25, n_requests=1)
            self.assertEqual((u.month_spend("a"), u.total_spend("a"), u.total_spend("b")), (2.0, 3.0, 9.0))
            self.assertEqual((u.reserved("a"), u.reserved_total("a"), u.reserved_total("b")), (0.25, 0.75, 0.0))
            u.record_batch_done(batch_id="b1", provider="a", status="ended", actual_usd=0.1)
            self.assertEqual(u.reserved_total("a"), 0.25)


if __name__ == "__main__":
    unittest.main()
