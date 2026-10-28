"""The lineage-wide Deep review (src/ai/deep_review.py, wired in src/ai/postmortems.py; owner ask 2026-10-28).

    "All hounds need to do a DEEP analysis on their previous and current results."

One review per hound lineage with ten settled forward bets across ALL its versions: every number counted in Python and handed to the model,
the words only explain them (and code checks the words), written again after ten more settle, appended and never overwritten, counted
against the backfill's wall, and shown labelled hindsight. Every client is a fake and every store a temp file: no network, no spend.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from src.ai import deep_review as dr
from src.ai import postmortem_cost as cost
from src.ai import postmortem_parse as pm
from src.ai import postmortem_store as store
from src.ai import postmortems
from tests.backfill_fixtures import BackfillRig, lineage_message, lineage_text, many_old_bets, old_bet, user_row
from tests.postmortem_fixtures import KEY, bet, book_of, hound_data

PB = postmortems.PROVIDER_BACKFILL


def member(label, bets, *, status="running", hound_id=None, rule="Back a rested starter at plus money."):
    return {"label": label, "status": status, "hound_id": hound_id or f"u-{label[1:]}", "rule_text": rule, "bets": bets}


def b(n, result, *, price=120, **kw):
    return bet(n, result=result, price=price, **kw)


class TheNumbers(unittest.TestCase):
    def setUp(self):
        v1 = [b(1, "win"), b(2, "win"), b(3, "loss"), b(4, "push"), b(5, None), b(6, "loss", segment="replay"), b(7, "win", segment="replay"),
              b(8, "void")]
        v2 = [b(9, "loss", price=-130), b(10, "win", price=-130, market="spreads", line="-1.5"), b(11, "loss", price=250, sport="nba")]
        self.members = [member("v1", v1, status="replaced by a later version"), member("v2", v2)]
        self.stats = dr.compute_stats("Dee", self.members)

    def test_only_settled_forward_bets_are_counted_never_a_replay_open_or_void_row(self):
        self.assertEqual(self.stats["settled"], 7)
        self.assertEqual(dr.settled_count(self.members), 7)
        self.assertEqual(self.stats["record"], {"wins": 3, "losses": 3, "pushes": 1})
        self.assertEqual(self.stats["versions"], 2)

    def test_units_win_rate_and_the_basis_are_worked_out_in_python(self):
        dec = lambda a: 1 + (a / 100.0 if a > 0 else 100.0 / abs(a))                           # noqa: E731
        want = round((dec(115) - 1) * 2 - 1 + 0 - 1 + (dec(-135) - 1) - 1, 2)
        self.assertEqual(self.stats["units_basis"], "board-average price")
        self.assertAlmostEqual(self.stats["units"], want, places=2)
        self.assertEqual(self.stats["win_pct"], round(100 * 3 / 6, 1))
        self.assertAlmostEqual(self.stats["units_per_bet"], round(want / 7, 3), places=3)

    def test_units_fall_back_to_the_price_taken_when_the_board_average_is_mostly_missing(self):
        rows = [b(i, "win", price_average=None) for i in range(1, 6)] + [b(6, "loss", price_average=None)]
        stats = dr.compute_stats("Dee", [member("v1", rows)])
        self.assertEqual(stats["units_basis"], "price the hound took")
        self.assertAlmostEqual(stats["units"], round(5 * 1.2 - 1, 2), places=2)

    def test_the_breakdowns_by_sport_market_price_band_and_version(self):
        by_sport = {c["label"]: c for c in self.stats["by_sport"]}
        self.assertEqual((by_sport["MLB"]["bets"], by_sport["NBA"]["bets"]), (6, 1))
        by_market = {c["label"]: c for c in self.stats["by_market"]}
        self.assertEqual((by_market["Moneyline"]["bets"], by_market["Spread"]["bets"]), (6, 1))
        bands = {c["label"]: c for c in self.stats["by_price_band"]}
        self.assertEqual(bands["underdogs"]["bets"], 4)                                         # +120 x4 taken, +115 average
        self.assertEqual(bands["underdogs"]["range"], "+110 to +199")
        self.assertEqual(bands["favourites"]["bets"], 2)                                        # -130 x2
        self.assertEqual(bands["long shots"]["bets"], 1)                                        # +250
        self.assertEqual([c["label"] for c in self.stats["by_price_band"]], ["favourites", "underdogs", "long shots"])    # in price order
        by_version = {v["version"]: v for v in self.stats["by_version"]}
        self.assertEqual((by_version["v1"]["bets"], by_version["v2"]["bets"]), (4, 3))
        self.assertEqual(by_version["v1"]["status"], "replaced by a later version")
        self.assertEqual(by_version["v1"]["rule"], "Back a rested starter at plus money.")

    def test_favourite_against_underdog_follows_the_price_for_a_moneyline_and_the_line_for_a_spread(self):
        fu = self.stats["favourite_vs_underdog"]
        self.assertEqual(fu["favourite"]["bets"], 2)                                            # the -130 moneyline loss and the -1.5 spread win
        self.assertEqual(fu["underdog"]["bets"], 5)                                             # +120 x4 (one a push) and +250
        self.assertAlmostEqual(fu["favourite"]["share_pct"] + fu["underdog"]["share_pct"], 100.0, places=0)
        self.assertEqual(fu["favourite"]["share_pct"], round(100 * 2 / 7, 1))

    def test_a_total_has_no_side_and_so_no_share(self):
        stats = dr.compute_stats("Dee", [member("v1", [b(1, "win", market="totals", line="8.5")])])
        self.assertEqual(stats["favourite_vs_underdog"], {})

    def test_closing_line_value_is_there_only_where_it_was_stored(self):
        clv = self.stats["closing_line_value"]
        self.assertEqual((clv["measured_bets"], clv["mean_points"], clv["beat_the_close_pct"]), (7, 0.6, 100.0))
        rows = [b(1, "win", clv_pts=None), b(2, "loss", clv_pts=-0.4), b(3, "win", clv_pts=0.2)]
        mixed = dr.compute_stats("Dee", [member("v1", rows)])["closing_line_value"]
        self.assertEqual((mixed["measured_bets"], mixed["mean_points"], mixed["beat_the_close_pct"]), (2, -0.1, 50.0))
        none = dr.compute_stats("Dee", [member("v1", [b(1, "win", clv_pts=None)])])
        self.assertIsNone(none["closing_line_value"])                                           # never a zero

    def test_a_lineage_with_nothing_settled_is_all_none_not_zero(self):
        stats = dr.compute_stats("Dee", [member("v1", [b(1, None)])])
        self.assertEqual(stats["settled"], 0)
        self.assertIsNone(stats["win_pct"])
        self.assertIsNone(stats["units_per_bet"])
        self.assertIsNone(stats["first_bet_date"])

    def test_the_old_minus_200_line_is_its_own_band_and_the_bands_match_the_training_screens(self):
        old = dr.compute_stats("Dee", [member("v1", [b(1, "win", price=-220, price_average=-225)])])
        self.assertEqual(old["by_price_band"][0]["label"], "heavy favourites (old rule)")
        self.assertEqual(old["by_price_band"][0]["range"], "-200 or worse")
        from src.hounds.interact import training
        ours = [(k, rng) for k, _n, rng, _lo, _hi in dr.PRICE_BANDS[1:]]
        theirs = [(k, rng) for k, _n, rng, _lo, _hi in training.PRICE_BANDS]
        self.assertEqual(ours, theirs)
        for price in (-199, -151, -150, -111, -110, 109, 110, 199, 200, 450):
            probe = SimpleNamespace(price=price, price_average=None)
            self.assertEqual(dr.band_key(probe), training.band_of(price), price)

    def test_each_breakdown_shows_only_its_biggest_groups(self):
        rows = [b(i, "win", sport=f"s{i}") for i in range(1, 15)]
        stats = dr.compute_stats("Dee", [member("v1", rows)])
        self.assertEqual(len(stats["by_sport"]), dr.GROUPS_SHOWN)

    def test_the_stats_are_json_primitives_only(self):
        self.assertEqual(json.loads(json.dumps(self.stats)), self.stats)

    def test_a_long_rule_text_is_clipped(self):
        stats = dr.compute_stats("Dee", [member("v1", [b(1, "win")], rule="word " * 200)])
        self.assertLessEqual(len(stats["by_version"][0]["rule"]), dr.RULE_CHARS)


class TheTrigger(unittest.TestCase):
    def test_ten_settled_make_a_lineage_due_and_ten_more_make_it_due_again(self):
        self.assertFalse(dr.due(9, 0))
        self.assertTrue(dr.due(10, 0))
        self.assertFalse(dr.due(19, 10))
        self.assertTrue(dr.due(20, 10))
        self.assertTrue(dr.due(35, 10))
        self.assertFalse(dr.due(10, 10))

    def test_the_review_key_is_stable_for_a_state_and_moves_with_the_bucket(self):
        k = dr.review_key("root-1", 0, 12)
        self.assertRegex(k, r"^dr_[0-9a-f]{16}$")
        self.assertEqual(k, dr.review_key("root-1", 0, 12))
        self.assertEqual(k, dr.review_key("root-1", 0, 19))                                     # more bets inside the bucket: the same request
        self.assertNotEqual(k, dr.review_key("root-1", 0, 20))                                  # ten more settled: a fresh attempt is allowed
        self.assertNotEqual(k, dr.review_key("root-1", 12, 12))                                 # and a new review is a new key
        self.assertNotEqual(k, dr.review_key("root-2", 0, 12))
        self.assertEqual(pm.split_custom_id(pm.custom_id(k, pm.DEPTH_LINEAGE)), (k, pm.DEPTH_LINEAGE))
        self.assertRegex(pm.custom_id(k, pm.DEPTH_LINEAGE), r"^[A-Za-z0-9_-]{1,64}$")


class TheRequest(unittest.TestCase):
    def setUp(self):
        self.stats = dr.compute_stats("Dee", [member("v1", [b(i, "win" if i % 2 else "loss") for i in range(1, 13)])])
        self.params, self.chars = dr.request_params(self.stats)

    def test_it_is_sonnet_5_5_with_adaptive_thinking_and_a_json_schema(self):
        p = self.params
        self.assertEqual(p["model"], "claude-sonnet-5-5")
        self.assertEqual(p["thinking"], {"type": "adaptive"})
        self.assertEqual(p["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(p["output_config"]["effort"], dr.EFFORT)
        self.assertEqual(sorted(p["output_config"]["format"]["schema"]["required"]), sorted(dr.SCHEMA["required"]))
        self.assertIs(p["output_config"]["format"]["schema"]["additionalProperties"], False)

    def test_it_sets_none_of_the_parameters_this_model_refuses(self):
        p = self.params
        for banned in ("temperature", "top_p", "top_k", "budget_tokens"):
            self.assertNotIn(banned, p)
            self.assertNotIn(banned, p["thinking"])
        self.assertEqual([m["role"] for m in p["messages"]], ["user"])                          # no assistant prefill
        self.assertNotIn("tools", p)                                                            # and no web search: the numbers are the evidence

    def test_the_prompt_hands_over_the_counted_numbers_and_the_rules_of_the_road(self):
        user = self.params["messages"][0]["content"]
        self.assertIn(json.dumps(self.stats, separators=(",", ":"), sort_keys=True), user)
        system = self.params["system"]
        for phrase in ("HINDSIGHT", "ONLY numbers that appear in the JSON", "never say ROI", "paper", "never any other word"):
            self.assertIn(phrase.lower(), system.lower())
        self.assertIn("quoted data", system)

    def test_the_api_schema_uses_only_the_keywords_structured_outputs_accept(self):
        def keys(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield k
                    if k != "properties":
                        yield from keys(v)
                    else:
                        for sub in v.values():
                            yield from keys(sub)
            elif isinstance(node, list):
                for v in node:
                    yield from keys(v)
        self.assertTrue(set(keys(dr.API_SCHEMA)) <= {"type", "properties", "required", "additionalProperties", "items"})

    def test_what_it_costs_is_a_couple_of_cents_a_hound(self):
        typical = dr.estimate_cost()
        self.assertAlmostEqual(typical, (4000 * 2.0 + 2500 * 10.0) / 1e6 * 0.5, places=6)
        self.assertAlmostEqual(typical, 0.0165, places=4)
        worst = dr.worst_cost(self.stats)
        self.assertGreater(worst, typical)
        self.assertLess(worst, 0.04)                                                            # what a batch reserves per hound


class TheAnswer(unittest.TestCase):
    def setUp(self):
        self.stats = dr.compute_stats("Dee", [member("v1", [b(i, "win" if i % 2 else "loss") for i in range(1, 13)])])

    def text(self, **over):
        return lineage_text(self.stats, **over)

    def test_a_good_answer_is_stored_with_only_the_known_keys(self):
        review, problems = dr.parse_review(self.text(), self.stats)
        self.assertEqual(problems, [])
        self.assertEqual(sorted(review), ["changes", "failing", "headline", "sample_note", "working"])

    def test_a_number_the_app_did_not_count_sinks_the_answer(self):
        review, problems = dr.parse_review(self.text(headline="It has 99 wins and 3 losses over the whole run."), self.stats)
        self.assertIsNone(review)
        self.assertTrue(any("99" in p for p in problems))

    def test_every_number_it_was_handed_is_fine_in_any_of_its_written_forms(self):
        s = self.stats
        line = f"It won {s['win_pct']}% of its bets and {s['record']['wins']} of {s['settled']} settled bets, at {s['units']} units."
        review, problems = dr.parse_review(self.text(working=[line]), s)
        self.assertEqual(problems, [])
        pct0 = f"About {round(s['win_pct'])} in every hundred bets won."
        self.assertIsNone(dr.parse_review(self.text(working=[pct0 + " It lost 77 of them."]), s)[0])

    def test_a_number_in_the_hounds_own_name_or_rule_text_may_be_repeated_and_no_other_may(self):
        rows = [b(i, "win" if i % 2 else "loss") for i in range(1, 13)]
        stats = dr.compute_stats("Dee 7", [member("v1", rows, rule="It needs at least 31 books quoting a price.")])
        ok, problems = dr.parse_review(lineage_text(stats, working=["Its rule asks for 31 books, and it won 6 of 12."]), stats)
        self.assertEqual(problems, [])
        self.assertIsNone(dr.parse_review(lineage_text(stats, working=["It asks for 47 books."]), stats)[0])
        self.assertEqual(dr.parse_review(lineage_text(stats, headline="Dee 7 won 6 of its 12 settled bets in all."), stats)[1], [])

    def test_a_hound_whose_name_holds_a_banned_word_may_be_called_by_its_name_and_nothing_else_may(self):
        rows = [b(i, "win" if i % 2 else "loss") for i in range(1, 13)]
        stats = dr.compute_stats("The Old Dog", [member("v1", rows)])
        ok, problems = dr.parse_review(lineage_text(stats, headline="The Old Dog won 6 of its 12 settled bets in all."), stats)
        self.assertEqual(problems, [])
        self.assertIsNone(dr.parse_review(lineage_text(stats, failing=["The Old Dog leans on one dog too often."]), stats)[0])
        self.assertIsNone(dr.parse_review(lineage_text(stats, failing=["The Old Dog was new to the spread rule."]), stats)[0])

    def test_small_counts_written_as_words_need_no_number(self):
        review, problems = dr.parse_review(self.text(changes=["Try one change: drop the weakest market for two weeks."]), self.stats)
        self.assertEqual(problems, [])

    def test_a_banned_word_sinks_the_answer_and_a_longer_word_does_not(self):
        for word in ("new", "beta", "dog", "dogs", "profit", "profitable", "ROI", "variance", "edge", "guaranteed", "sure thing", "Bet Check"):
            review, problems = dr.parse_review(self.text(failing=[f"It leans on the {word} too often."]), self.stats)
            self.assertIsNone(review, word)
            self.assertTrue(any("banned" in p for p in problems), word)
        text = "nothing cleared " + "the bar"
        self.assertIsNone(dr.parse_review(self.text(failing=[f"It said {text} for a week."]), self.stats)[0])
        ok, problems = dr.parse_review(self.text(working=["The newest bets did best, and a renewed rule helped."]), self.stats)
        self.assertEqual(problems, [])

    def test_the_schema_is_strict_and_nothing_is_repaired(self):
        cases = {
            "not json": "I could not do that.",
            "a list": "[1, 2]",
            "empty": "",
            "missing key": json.dumps({k: v for k, v in json.loads(self.text()).items() if k != "failing"}),
            "an extra key": json.dumps(dict(json.loads(self.text()), tip="bet the over")),
            "three changes": self.text(changes=["Change one thing at a time here.", "Change another thing later on.", "A third idea to try."]),
            "no changes": self.text(changes=[]),
            "too many words": self.text(headline="word " * 40),
            "a string where a list belongs": self.text(working="it works"),
        }
        for name, text in cases.items():
            review, problems = dr.parse_review(text, self.stats)
            self.assertIsNone(review, name)
            self.assertTrue(problems, name)

    def test_a_markdown_fence_is_accepted(self):
        review, problems = dr.parse_review("```json\n" + self.text() + "\n```", self.stats)
        self.assertEqual(problems, [])

    def test_the_public_view_is_labelled_hindsight_and_carries_no_cost_or_batch(self):
        row = {"review_key": "dr_x", "created_utc": "2026-10-28T20:00:00Z", "model": dr.MODEL, "settled": 12, "stats": self.stats,
               "review": json.loads(self.text()), "cost_usd": 0.0165, "batch_id": "msgbatch_1"}
        pub = dr.public_review(row)
        self.assertEqual(pub["label"], "Deep review (hindsight)")
        self.assertIn("after the results", pub["note"])
        self.assertEqual(pub["settled"], 12)
        self.assertEqual(pub["versions"], 1)
        self.assertNotIn("cost_usd", pub)
        self.assertNotIn("batch_id", pub)
        self.assertNotIn("stats", pub)
        self.assertEqual(pub["by_version"][0]["version"], "v1")
        self.assertEqual(pub["headline"], json.loads(self.text())["headline"])


# ---------------------------------------------------------------------------------------------------------------------
class WithLineages(unittest.TestCase):
    def setUp(self):
        self.rows = [user_row("u-1", "u-1", 1, status="retired", reason="superseded by u-2: fine-tune"), user_row("u-2", "u-1", 2)]
        self.rig = BackfillRig(on=True, lineages=True, user_rows=self.rows)
        self.addCleanup(self.rig.close)
        self.e, self.client = self.rig.engine, self.rig.client

    def book(self, v1=6, v2=6, *, extra=()):
        return book_of(hound_data("u-1", many_old_bets("u-1", v1, day=10), kind="user"),
                       hound_data("u-2", many_old_bets("u-2", v2, day=12), kind="user"), *extra)

    def lineage_items(self, status=None):
        return self.rig.backfill_items(pm.DEPTH_LINEAGE, status)

    def request_ids(self, n=-1):
        return [r["custom_id"] for r in self.client.batches.created[n]]


class TheLineageQueue(WithLineages):
    def test_ten_settled_across_the_versions_queue_one_deep_review_for_the_lineage(self):
        self.rig.tick(self.book(6, 6))
        items = self.lineage_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["hound_id"], "u-1")                                           # keyed by the lineage's root, not a version
        self.assertEqual(items[0]["bet"]["hound_ids"], ["u-1", "u-2"])
        self.assertEqual(items[0]["bet"]["settled"], 12)
        self.assertEqual(items[0]["tier"], store.TIER_MEMBER)

    def test_nine_settled_are_not_enough_and_a_replay_open_or_void_row_does_not_count(self):
        v1 = many_old_bets("u-1", 5) + [old_bet(50, "u-1", result="void"), old_bet(51, "u-1", result=None), old_bet(52, "u-1", segment="replay")]
        v2 = many_old_bets("u-2", 4, first_n=20)
        self.rig.tick(book_of(hound_data("u-1", v1, kind="user"), hound_data("u-2", v2, kind="user")))
        self.assertEqual(self.lineage_items(), [])
        self.rig.tick(book_of(hound_data("u-1", v1, kind="user"), hound_data("u-2", v2 + [old_bet(99, "u-2")], kind="user")), minutes=1)
        self.assertEqual(len(self.lineage_items()), 1)

    def test_each_lineage_is_its_own_review_and_a_baseline_has_none(self):
        pack_old = hound_data("pk@v1", many_old_bets("pk@v1", 6), kind="house", category="stats")
        pack_now = hound_data("pk", many_old_bets("pk", 6, first_n=30), kind="house", category="stats")
        base = hound_data("b-1", many_old_bets("b-1", 12, first_n=60), kind="baseline", category="baseline")
        self.rig.tick(self.book(6, 6, extra=(pack_old, pack_now, base)))
        self.assertEqual(sorted(i["hound_id"] for i in self.lineage_items()), ["pk", "u-1"])
        pack = next(i for i in self.lineage_items() if i["hound_id"] == "pk")
        self.assertEqual(pack["bet"]["hound_ids"], ["pk@v1", "pk"])

    def test_the_learner_has_a_lineage_too_and_members_go_first(self):
        learner = hound_data("learner", many_old_bets("learner", 40, first_n=100), kind="house", category="learner")
        house = hound_data("h-1", many_old_bets("h-1", 12, first_n=200), kind="house", category="stats")
        self.rig.tick(self.book(6, 6, extra=(learner, house)))
        order = [i["tier"] for i in self.rig.queue.pending(store.ORIGIN_BACKFILL) if i["depth"] == pm.DEPTH_LINEAGE]
        self.assertEqual(sorted(order, key=store.TIER_RANK.get), order)
        self.assertEqual(sorted(i["hound_id"] for i in self.lineage_items()), ["h-1", "learner", "u-1"])

    def test_planning_twice_queues_one_and_an_open_one_blocks_another(self):
        book = self.book()
        self.rig.tick(book)
        before = self.rig.queue_text()
        self.assertEqual(self.e.backfill_plan(book, self.rig.cfg)["lineages_queued"], 0)
        self.assertEqual(self.rig.queue_text(), before)
        more = self.book(20, 20)                                                                # the bucket moves while the first is in flight
        self.assertEqual(self.e.backfill_plan(more, self.rig.cfg)["lineages_queued"], 0)
        self.assertEqual(len(self.lineage_items()), 1)

    def test_with_the_switch_off_no_lineage_is_queued_or_computed(self):
        self.rig.cfg["on"] = False
        self.rig.tick(self.book(30, 30))
        self.assertEqual(self.lineage_items(), [])
        self.assertNotIn("lineage", self.rig.queue_text())

    def test_a_deep_review_rides_the_first_backfill_batch_ahead_of_past_bets(self):
        self.rig.tick(self.book())
        ids = self.request_ids()
        self.assertTrue(ids[0].endswith("_lineage"), ids[:3])
        self.assertTrue(all(i.endswith("_fast") for i in ids[1:]))
        self.assertEqual(len(ids), 1 + 12)

    def test_the_request_is_sonnet_with_the_python_counted_numbers(self):
        self.rig.tick(self.book())
        req = self.client.batches.created[0][0]
        key, depth = pm.split_custom_id(req["custom_id"])
        stats = self.rig.queue.get(key, depth)["bet"]["stats"]
        self.assertEqual(req["params"], dr.request_params(stats)[0])
        self.assertEqual(req["params"]["model"], "claude-sonnet-5-5")
        self.assertEqual(stats["settled"], 12)
        self.assertEqual([v["version"] for v in stats["by_version"]], ["v1", "v2"])
        self.assertEqual([v["status"] for v in stats["by_version"]], ["replaced by a later version", "running"])
        self.assertEqual(stats["hound"], "Hound u-2")                                           # named for the newest version

    def test_only_a_window_of_lineages_is_queued_at_a_time(self):
        extra = tuple(hound_data(f"h-{i}", many_old_bets(f"h-{i}", 10, first_n=300 + i * 20), kind="house", category="stats") for i in range(30))
        self.rig.tick(self.book(6, 6, extra=extra))
        self.assertEqual(len(self.lineage_items()), postmortems.BACKFILL_LINEAGE_WINDOW)
        self.assertEqual(self.e.status()["backfill"]["lineage_reviews"]["remaining"], 31 - postmortems.BACKFILL_LINEAGE_WINDOW)


class TheLineageResult(WithLineages):
    def read(self, book=None, answer=True):
        book = book or self.book()
        self.rig.tick(book)
        if answer:
            self.rig.answer_lineages()
        self.rig.tick(book, minutes=30)
        return book

    def only_row(self):
        rows = self.rig.deep.rows_for("u-1")
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_a_good_answer_is_appended_with_the_counted_numbers_beside_the_words(self):
        self.read()
        row = self.only_row()
        self.assertEqual(row["kind"], "deep_review")
        self.assertEqual(row["label"], "Deep review (hindsight)")
        self.assertEqual((row["lineage_key"], row["settled"], row["model"]), ("u-1", 12, "claude-sonnet-5-5"))
        self.assertEqual(row["hound_ids"], ["u-1", "u-2"])
        self.assertEqual(row["stats"]["settled"], 12)
        self.assertEqual(row["review"]["working"], ["Underdog picks held up better than favourites."])
        self.assertIs(row["paper_only"], True)
        self.assertEqual(row["seq"], 1)
        self.assertEqual(self.rig.queue.counts(origin=store.ORIGIN_BACKFILL, depth=pm.DEPTH_LINEAGE)["done"], 1)

    def test_the_money_is_the_apis_own_usage_with_no_search_and_counts_against_the_backfill_wall(self):
        self.read()
        want_deep = cost.usage_cost(cost.SONNET, {"input_tokens": 4000, "output_tokens": 2500}, batch=True)
        row = self.only_row()
        self.assertAlmostEqual(row["cost_usd"], want_deep, places=8)
        self.assertAlmostEqual(want_deep, dr.estimate_cost(), places=8)
        fast = 12 * cost.usage_cost(cost.HAIKU, SimpleNamespace(input_tokens=20000, output_tokens=1500, cache_creation_input_tokens=0,
                                                                  cache_read_input_tokens=0,
                                                                  server_tool_use=SimpleNamespace(web_search_requests=3)), batch=True)
        self.assertAlmostEqual(self.rig.usage.total_spend(PB), want_deep + fast, places=6)
        self.assertEqual(self.rig.usage.month_spend(postmortems.PROVIDER), 0)                   # the $20 a month wall never sees it

    def test_a_second_read_of_the_same_batch_writes_nothing_twice(self):
        book = self.read()
        before = self.rig.deep.count()
        self.rig.tick(book, minutes=30)
        self.assertEqual(self.rig.deep.count(), before)

    def test_the_review_is_not_written_again_until_ten_more_settle_and_then_a_new_row_is_added(self):
        book = self.read()
        first = self.only_row()
        self.assertEqual(self.e.backfill_plan(book, self.rig.cfg)["lineages_queued"], 0)        # 12 settled, last review covered 12
        nine = self.book(6 + 4, 6 + 5)                                                          # 21 settled: nine more
        self.rig.tick(nine, minutes=30)
        self.assertEqual(self.lineage_items(), self.lineage_items("done"))
        ten = book_of(hound_data("u-1", many_old_bets("u-1", 6, day=10) + many_old_bets("u-1", 5, first_n=40, day=14), kind="user"),
                      hound_data("u-2", many_old_bets("u-2", 6, day=12) + many_old_bets("u-2", 5, first_n=60, day=15), kind="user"))
        self.rig.tick(ten, minutes=30)                                                          # 22 settled: ten more
        self.assertEqual(len(self.lineage_items()), 2)
        self.rig.answer_lineages()
        self.rig.tick(ten, minutes=30)
        rows = self.rig.deep.rows_for("u-1")
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["settled"] for r in rows], [22, 12])                                # newest first, the old one kept
        self.assertEqual(rows[1], first)                                                        # and untouched, byte for byte
        self.assertEqual([r["seq"] for r in rows], [2, 1])
        self.assertEqual(len(self.e.deep_reviews_for("u-1")), 2)

    def test_a_number_the_app_never_counted_fails_the_review_the_money_is_still_spent_and_it_is_tried_once_more(self):
        book = self.book()
        self.rig.tick(book)
        cid = [i for i in self.request_ids() if i.endswith("_lineage")][0]
        key = pm.split_custom_id(cid)[0]
        stats = self.rig.queue.get(key, pm.DEPTH_LINEAGE)["bet"]["stats"]
        self.client.batches.answers[cid] = SimpleNamespace(type="succeeded", message=lineage_message(lineage_text(
            stats, headline="It has 1234 wins and 3 losses over the whole run.")))
        spent_before = self.rig.usage.total_spend(PB)
        self.rig.tick(book, minutes=30)
        self.assertEqual(self.rig.deep.count(), 0)
        self.assertGreater(self.rig.usage.total_spend(PB), spent_before)                        # a bad answer still cost something
        self.assertEqual(self.rig.queue.get(key, pm.DEPTH_LINEAGE)["status"], "submitted")      # retried: back in line and sent again
        self.assertEqual(self.rig.queue.get(key, pm.DEPTH_LINEAGE)["attempts"], 1)
        self.rig.tick(book, minutes=30)                                                         # the same bad answer a second time
        self.assertEqual(self.rig.queue.get(key, pm.DEPTH_LINEAGE)["status"], "failed")
        self.assertEqual(self.rig.deep.count(), 0)

    def test_a_lineage_that_failed_waits_for_ten_more_settled_bets_then_is_tried_again(self):
        book = self.book()
        self.rig.tick(book)
        cid = [i for i in self.request_ids() if i.endswith("_lineage")][0]
        key = pm.split_custom_id(cid)[0]
        self.client.batches.answers[cid] = SimpleNamespace(type="succeeded", message=lineage_message("I could not do that."))
        for _ in range(3):
            self.rig.tick(book, minutes=30)
        self.assertEqual(self.rig.queue.get(key, pm.DEPTH_LINEAGE)["status"], "failed")
        self.assertEqual(self.e.backfill_plan(book, self.rig.cfg)["lineages_queued"], 0)        # not retried on the same bets
        bigger = self.book(14, 14)                                                              # 28 settled: the bucket moved
        self.assertEqual(self.e.backfill_plan(bigger, self.rig.cfg)["lineages_queued"], 1)

    def test_a_refusal_or_an_errored_request_is_not_a_review(self):
        book = self.book()
        self.rig.tick(book)
        cid = [i for i in self.request_ids() if i.endswith("_lineage")][0]
        self.client.batches.answers[cid] = SimpleNamespace(type="succeeded", message=lineage_message("", stop_reason="refusal"))
        self.rig.tick(book, minutes=30)
        self.assertEqual(self.rig.deep.count(), 0)
        key = pm.split_custom_id(cid)[0]
        self.assertEqual(self.rig.queue.get(key, pm.DEPTH_LINEAGE)["status"], "failed")

    def test_a_missing_usage_is_charged_the_worst_case_never_zero(self):
        book = self.book()
        self.rig.tick(book)
        cid = [i for i in self.request_ids() if i.endswith("_lineage")][0]
        key = pm.split_custom_id(cid)[0]
        stats = self.rig.queue.get(key, pm.DEPTH_LINEAGE)["bet"]["stats"]
        self.client.batches.answers[cid] = SimpleNamespace(type="succeeded", message=lineage_message(lineage_text(stats), usage=None))
        self.rig.tick(book, minutes=30)
        row = self.only_row()
        self.assertAlmostEqual(row["cost_usd"], dr.worst_cost(stats), places=6)
        self.assertGreater(row["cost_usd"], dr.estimate_cost())

    def test_the_logs_and_the_ledger_never_carry_the_key(self):
        self.read()
        with open(self.rig.deep.path, encoding="utf-8") as fh:
            self.assertNotIn(KEY, fh.read())
        self.assertNotIn(KEY, repr(self.e.status()))


class TheLineageWall(WithLineages):
    def test_a_wall_that_fits_one_hound_and_not_two_stops_the_line_in_priority_order(self):
        extra = (hound_data("h-1", many_old_bets("h-1", 12, first_n=300), kind="house", category="stats"),)
        probe = BackfillRig(on=True, lineages=True, user_rows=self.rows)
        self.addCleanup(probe.close)
        probe.tick(self.book(6, 6, extra=extra))
        worst = [dr.worst_cost(i["bet"]["stats"]) for i in probe.backfill_items(pm.DEPTH_LINEAGE)]
        self.assertEqual(len(worst), 2)
        self.rig.cfg["cap_usd"] = worst[0] + 1e-6
        out = self.rig.tick(self.book(6, 6, extra=extra))
        self.assertEqual(out["backfill_submit"]["submitted"], 1)                                # the member lineage; the house one did not fit
        ids = self.request_ids()
        self.assertTrue(ids[0].endswith("_lineage") and len(ids) == 1)
        self.assertEqual(self.rig.queue.get(pm.split_custom_id(ids[0])[0], pm.DEPTH_LINEAGE)["hound_id"], "u-1")

    def test_a_spent_wall_queues_no_deep_review(self):
        self.rig.usage.record_call(provider=PB, model="m", status="ok", cost_usd=25.0)
        out = self.rig.tick(self.book())
        self.assertEqual(out["backfill"]["waiting"], "backfill_cap")
        self.assertEqual(self.lineage_items(), [])

    def test_the_status_counts_the_deep_reviews(self):
        self.rig.tick(self.book())
        self.assertEqual(self.e.status()["backfill"]["lineage_reviews"], {"done": 0, "queued": 1, "failed": 0, "remaining": 0})
        self.rig.answer_lineages()
        self.rig.tick(self.book(), minutes=30)
        self.assertEqual(self.e.status()["backfill"]["lineage_reviews"]["done"], 1)

    def test_a_chain_loader_that_fails_stops_neither_the_live_reviews_nor_the_past_bets(self):
        def boom(book):
            raise RuntimeError("db")
        self.e._chains_loader = boom                                                            # noqa: SLF001
        with self.assertLogs("linehound.ai.postmortems", level="ERROR"):
            out = self.rig.tick(book_of(hound_data("u-1", [bet(99, result="loss")] + many_old_bets("u-1", 12), kind="user")))
        self.assertEqual(out["backfill"]["lineages_error"], "RuntimeError")
        self.assertEqual(out["backfill"]["bets_queued"], 12)
        self.assertEqual(out["submit"]["submitted"], 1)


class TheLedgerOnDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "d.jsonl")
        self.d = store.DeepReviewLedger(self.path)

    def write(self, d, key="dr_" + "a" * 16, lineage="L", settled=12, review=None):
        return d.append(lineage_key=lineage, review_key=key, hound_ids=["u-1"], settled=settled, stats={"settled": settled, "versions": 1},
                        review=review or {"headline": "A headline."}, model="claude-sonnet-5-5", cost_usd=0.0165, batch_id="b")

    def test_first_write_wins_and_a_new_review_is_a_new_row(self):
        self.assertTrue(self.write(self.d))
        self.assertFalse(self.write(self.d, review={"headline": "Changed."}))
        self.assertEqual(self.d.latest("L")["review"]["headline"], "A headline.")
        self.assertTrue(self.write(self.d, key="dr_" + "b" * 16, settled=25))
        self.assertEqual(self.d.count("L"), 2)
        self.assertEqual(self.d.last_settled("L"), 25)
        self.assertEqual(self.d.last_settled("nobody"), 0)
        self.assertEqual([r["seq"] for r in self.d.rows_for("L")], [2, 1])

    def test_it_survives_a_restart_and_a_second_reader_sees_appends(self):
        self.write(self.d)
        other = store.DeepReviewLedger(self.path)
        self.assertEqual(other.count(), 1)
        self.write(self.d, key="dr_" + "c" * 16, settled=40)
        self.assertEqual(other.count(), 2)                                                      # read incrementally, no restart needed
        self.assertTrue(other.has("dr_" + "c" * 16))
        self.assertFalse(other.has("dr_" + "d" * 16))

    def test_a_torn_last_line_waits_and_a_truncated_file_is_re_read(self):
        self.write(self.d)
        with open(self.path, "ab") as fh:
            fh.write(b'{"kind":"deep_review","review_key":"dr_torn')
        self.assertEqual(self.d.count(), 1)
        with open(self.path, "wb") as fh:
            fh.write(b"")
        self.assertEqual(self.d.count(), 0)

    def test_the_default_path_sits_beside_the_other_two_and_can_be_overridden(self):
        from src.appstate import users as users_store
        q, l = store.default_paths({})
        self.assertEqual(store.default_deep_path({}).parent, q.parent)
        self.assertEqual(store.default_deep_path({}).name, store.DEEP_FILE)
        self.assertEqual(str(store.default_deep_path({store.ENV_DEEP: "/vol/d.jsonl"})).replace("\\", "/"), "/vol/d.jsonl")
        self.assertEqual(store.default_deep_path({}).parent, users_store.db_path().parent)

    def test_a_row_is_labelled_hindsight_and_holds_no_person(self):
        self.write(self.d)
        raw = open(self.path, encoding="utf-8").read()
        self.assertIn("Deep review (hindsight)", raw)
        for word in ("email", "user_id", "token", "api_key"):
            self.assertNotIn(word, raw)


class TheFilesShip(unittest.TestCase):
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_every_new_file_lives_under_a_tree_the_dockerfile_copies_and_the_dockerignore_admits(self):
        dockerfile = open(os.path.join(self.ROOT, "deploy", "Dockerfile"), encoding="utf-8").read()
        ignore = open(os.path.join(self.ROOT, ".dockerignore"), encoding="utf-8").read()
        for tree in ("COPY src/ src/", "COPY api/ api/", "COPY web/ web/", "COPY config/ config/"):
            self.assertIn(tree, dockerfile)
        new_files = ["src/ai/deep_review.py", "src/ai/hindsight_feed.py", "src/hounds/version_chain.py", "config/postmortem_backfill.json"]
        ignored = [ln.strip() for ln in ignore.splitlines() if ln.strip() and not ln.startswith(("#", "!"))]
        for path in new_files:
            self.assertTrue(os.path.exists(os.path.join(self.ROOT, path)), path)
            self.assertFalse(any(path == i or path.startswith(i.rstrip("/") + "/") for i in ignored), path)


if __name__ == "__main__":
    unittest.main()
