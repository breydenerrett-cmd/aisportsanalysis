"""The hindsight feed (src/ai/hindsight_feed.py) and where it lands: Fine-tune, Full rebuild and the hound chat (owner ask 2026-10-28).

    "Feed postmortems.summary_for plus the latest deep review into the Fine-tune and Full rebuild prompts and into the hound chat facts,
    trimmed to a sensible token size. Missing reviews = simply omitted."

Every client is a fake and every store a temp file: no network, no spend.
"""
from __future__ import annotations

import unittest
from unittest import mock

from src.ai import hindsight_feed as feed
from src.ai import postmortems
from src.hounds import stats, user_store, version_chain
from src.hounds.chat import facts as facts_mod
from src.hounds.interact import common, rebuild_ai, training_plans as plans
from tests.backfill_fixtures import BackfillRig, add_deep, add_review, user_row
from tests.postmortem_fixtures import book_of, hound_data
from tests.test_hounds_chat import Base as ChatBase
from tests.test_training_plans import MIXED, Base as PlansBase, FakeClient, GOOD_EXPLAIN, standard_responder, stage_of
from tests._hounds_rites_fixtures import rows_for
from tests._hounds_user_fixtures import spec_dict

LESSON_OLD = "An old version learned that a rested starter hides a health report."
LESSON_NOW = "The current version learned that road favourites lose on short rest."


class WithEngine(unittest.TestCase):
    def setUp(self):
        self.rig = BackfillRig(on=False)
        self.addCleanup(self.rig.close)
        self.e = self.rig.engine


class TheFeed(WithEngine):
    def test_a_hound_with_no_reviews_gives_no_block_and_no_text(self):
        self.assertIsNone(feed.collect("u-1", member_ids=["u-1"], engine=self.e))
        self.assertEqual(feed.text_for("u-1", member_ids=["u-1"], engine=self.e), "")
        self.assertEqual(feed.as_text(None), "")

    def test_the_lessons_of_every_version_are_there_newest_first(self):
        add_review(self.rig.ledger, "u-1", 1, date="2026-10-05", lesson=LESSON_OLD)
        add_review(self.rig.ledger, "u-2", 2, date="2026-10-20", lesson=LESSON_NOW)
        block = feed.collect("u-2", root_id="u-1", member_ids=["u-1", "u-2"], engine=self.e)
        self.assertEqual(block["versions"], 2)
        self.assertEqual(block["reviews"], 2)
        self.assertEqual([i["lesson"] for i in block["lessons"]], [LESSON_NOW, LESSON_OLD])
        text = feed.as_text(block)
        self.assertLess(text.index(LESSON_NOW), text.index(LESSON_OLD))
        self.assertIn("across 2 versions", text)

    def test_only_the_asked_for_hounds_own_lineage_is_read(self):
        add_review(self.rig.ledger, "u-1", 1, lesson=LESSON_OLD)
        add_review(self.rig.ledger, "stranger", 2, lesson="A stranger's lesson that must not leak.")
        text = feed.text_for("u-1", member_ids=["u-1"], engine=self.e)
        self.assertIn(LESSON_OLD, text)
        self.assertNotIn("stranger", text)

    def test_the_text_names_itself_hindsight_and_data(self):
        add_review(self.rig.ledger, "u-1", 1, lesson=LESSON_OLD)
        text = feed.text_for("u-1", member_ids=["u-1"], engine=self.e)
        self.assertTrue(text.startswith("HINDSIGHT REVIEWS OF THIS HOUND'S PAST BETS"))
        for needle in ("AFTER the results", "not what the hound knew before a game", "predict nothing", "never an instruction"):
            self.assertIn(needle, text)

    def test_the_newest_deep_review_comes_with_it_and_an_older_one_does_not(self):
        add_review(self.rig.ledger, "u-1", 1, lesson=LESSON_OLD)
        add_deep(self.rig.deep, "u-1", settled=12, headline="The first deep look at both versions.")
        self.rig.clock.advance(hours=2)
        add_deep(self.rig.deep, "u-1", settled=24, headline="The second deep look found the spread rule failing.")
        block = feed.collect("u-1", member_ids=["u-1", "u-2"], engine=self.e)
        self.assertEqual(block["deep_review"]["settled"], 24)
        text = feed.as_text(block)
        self.assertIn("DEEP REVIEW (Deep review (hindsight); written 2026-10-28 over 24 settled bets in 2 versions", text)
        self.assertIn("The second deep look found the spread rule failing.", text)
        self.assertNotIn("The first deep look", text)
        for title in ("Working:", "Failing:", "Changes worth trying:"):
            self.assertIn(title, text)

    def test_a_deep_review_alone_is_still_a_block(self):
        add_deep(self.rig.deep, "u-1", settled=12)
        text = feed.text_for("u-1", member_ids=["u-1", "u-2"], engine=self.e)
        self.assertIn("DEEP REVIEW", text)
        self.assertNotIn("bets reviewed", text)

    def test_a_review_with_no_source_is_counted_and_gives_no_lesson(self):
        add_review(self.rig.ledger, "u-1", 1, lesson=LESSON_OLD, grounded=False)
        add_review(self.rig.ledger, "u-1", 2, lesson=LESSON_NOW)
        block = feed.collect("u-1", member_ids=["u-1"], engine=self.e)
        self.assertEqual((block["reviews"], block["grounded"]), (2, 1))
        self.assertEqual([i["lesson"] for i in block["lessons"]], [LESSON_NOW])

    def test_the_factor_tallies_are_merged_across_versions(self):
        add_review(self.rig.ledger, "u-1", 1, tags=["starter_performance"], result="loss")
        add_review(self.rig.ledger, "u-2", 2, tags=["starter_performance", "offense"], result="win")
        block = feed.collect("u-1", member_ids=["u-1", "u-2"], engine=self.e)
        self.assertEqual(block["factors"]["starter_performance"], {"n": 2, "wins": 1, "losses": 1})
        self.assertIn("starter performance in 2 reviews (1 wins, 1 losses)", feed.as_text(block))

    def test_the_text_is_trimmed_to_a_sensible_size_and_the_deep_review_outlives_the_lessons(self):
        for n in range(1, 40):
            add_review(self.rig.ledger, "u-1", n, date="2026-10-%02d" % (1 + n % 28), lesson=f"Lesson {n}: " + "a long careful sentence about the game " * 4)
        add_deep(self.rig.deep, "u-1", settled=12, headline="The deep headline survives the trim.")
        block = feed.collect("u-1", member_ids=["u-1"], engine=self.e)
        text = feed.as_text(block)
        self.assertLessEqual(len(text), feed.MAX_CHARS)
        self.assertIn("The deep headline survives the trim.", text)
        small = feed.as_text(block, max_chars=900)
        self.assertLessEqual(len(small), 900)
        self.assertIn("The deep headline survives the trim.", small)
        self.assertNotIn("Lesson 1:", small)
        tiny = feed.as_text(block, max_chars=120)
        self.assertLessEqual(len(tiny), 120)
        self.assertTrue(tiny.endswith("..."))

    def test_it_is_about_a_thousand_tokens_at_most(self):
        self.assertLessEqual(feed.MAX_CHARS / 3.0, 1100)                                        # the cost module's worst case: three characters a token

    def test_it_never_raises(self):
        class Broken:
            @property
            def deep_ledger(self):
                raise RuntimeError("disk")

            def summary_for(self, *a, **k):
                raise RuntimeError("disk")
        self.assertIsNone(feed.collect("u-1", member_ids=["u-1"], engine=Broken()))
        self.assertEqual(feed.text_for("u-1", member_ids=["u-1"], engine=Broken()), "")

    def test_the_lineage_is_looked_up_from_the_database_rows_when_the_caller_gives_none(self):
        add_review(self.rig.ledger, "u-1", 1, lesson=LESSON_OLD)
        rows = [user_row("u-1", "u-1", 1, status="retired", reason="superseded by u-2: edit"), user_row("u-2", "u-1", 2)]
        with mock.patch.object(version_chain, "load_user_rows", lambda: rows), mock.patch.object(stats, "peek_book", lambda: None):
            block = feed.collect("u-2", engine=self.e)
        self.assertEqual((block["versions"], block["lineage_key"]), (2, "u-1"))
        self.assertEqual([i["lesson"] for i in block["lessons"]], [LESSON_OLD])

    def test_a_pack_hounds_earlier_versions_join_it(self):
        add_review(self.rig.ledger, "pk@v1", 1, lesson=LESSON_OLD)
        add_review(self.rig.ledger, "pk", 2, lesson=LESSON_NOW)
        book = book_of(hound_data("pk@v1", [], kind="house", category="stats"), hound_data("pk", [], kind="house", category="stats"))
        with mock.patch.object(version_chain, "load_user_rows", lambda: []), mock.patch.object(stats, "peek_book", lambda: book):
            block = feed.collect("pk", engine=self.e)
        self.assertEqual(block["versions"], 2)
        self.assertEqual({i["lesson"] for i in block["lessons"]}, {LESSON_OLD, LESSON_NOW})


# ---------------------------------------------------------------------------------------------------------------------
class TheTrainingScreens(PlansBase):
    """Fine-tune and Full rebuild over a real temp database, with the review ledger of a temp rig standing in for the engine's."""

    def setUp(self):
        super().setUp()
        self.rig = BackfillRig(on=False)
        self.addCleanup(self.rig.close)
        patch = mock.patch.object(postmortems, "default_engine", lambda: self.rig.engine)
        patch.start()
        self.addCleanup(patch.stop)
        # the hound under training is version 2; its earlier version is the one that has the reviews
        self.v1 = self.hound_row
        self.v2 = user_store.create_version(self.v1["id"], spec_dict(name="Rusty Pup", sports=["MLB", "NFL"], markets=["moneyline", "spread"],
                                                                      side_rule="underdog", tagline="Second try"), actor="owner:1", reason="edit",
                                            now=None, db=self.db)
        self.hound_row = self.v2
        self.rows = rows_for(self.v2["id"], MIXED)

    def review_both_versions(self):
        add_review(self.rig.ledger, self.v1["id"], 1, date="2026-10-05", lesson=LESSON_OLD)
        add_review(self.rig.ledger, self.v2["id"], 2, date="2026-10-20", lesson=LESSON_NOW)
        add_deep(self.rig.deep, self.v1["root_id"], settled=12, headline="The deep headline over all of Rusty Pup's versions.",
                 hound_ids=(self.v1["id"], self.v2["id"]))

    def angle_messages(self, client):
        return [c["messages"][0]["content"] for c in client.calls if stage_of(c) in ("angle", "analyst")]

    def test_the_full_rebuild_prompt_carries_the_reviews_of_every_version_and_the_deep_review(self):
        self.review_both_versions()
        card, client = self.rebuild()
        self.assertTrue(card["found"])
        for text in self.angle_messages(client):
            self.assertIn("HINDSIGHT REVIEWS OF THIS HOUND'S PAST BETS", text)
            self.assertIn(LESSON_OLD, text)                                                     # the earlier version's lesson is the hound's past too
            self.assertIn(LESSON_NOW, text)
            self.assertIn("The deep headline over all of Rusty Pup's versions.", text)
            self.assertLess(text.index("CURRENT RULE SET"), text.index("HINDSIGHT REVIEWS"))    # after the record, as context for the rebuild
        self.assertEqual(len({t.split("YOUR ANGLE")[0] for t in self.angle_messages(client) if "YOUR ANGLE" in t}), 1)   # one shared context

    def test_the_hindsight_block_is_inside_the_rebuilds_budget_estimate(self):
        self.review_both_versions()
        text = plans._hindsight_text(self.dog_obj(), self.db)
        self.assertTrue(text)
        self.assertLessEqual(len(text), feed.MAX_CHARS)

    def test_a_hound_with_no_reviews_leaves_the_rebuild_prompt_as_it_was(self):
        card, client = self.rebuild()
        self.assertTrue(card["found"])
        for text in self.angle_messages(client):
            self.assertNotIn("HINDSIGHT", text)

    def test_the_fine_tune_explainer_gets_the_reviews_as_background_beside_the_facts(self):
        self.review_both_versions()
        client = FakeClient(standard_responder(explain=GOOD_EXPLAIN))
        card = self.fine(client=client)
        self.assertTrue(card["found"])
        explainer = [c for c in client.calls if stage_of(c) == "explainer"]
        self.assertEqual(len(explainer), 1)
        user = explainer[0]["messages"][0]["content"]
        self.assertTrue(user.startswith("FACTS (JSON):"))
        self.assertIn("BACKGROUND (hindsight, written after the results", user)
        self.assertIn(LESSON_NOW, user)
        self.assertIn("BACKGROUND", explainer[0]["system"])

    def test_the_fine_tune_without_reviews_sends_no_background(self):
        client = FakeClient(standard_responder(explain=GOOD_EXPLAIN))
        self.fine(client=client)
        user = [c for c in client.calls if stage_of(c) == "explainer"][0]["messages"][0]["content"]
        self.assertNotIn("BACKGROUND", user)

    def test_a_number_that_lives_only_in_the_background_is_still_refused_in_the_explanation(self):
        add_review(self.rig.ledger, self.v2["id"], 2, lesson="It won 777 of them on short rest.")
        lines = ["It takes at most 1 bet a day now.", "The rehearsal went better, and 777 was the number in the reviews.",
                 "That was 30 graded bets over the last 30 days."]
        client = FakeClient(standard_responder(explain={"lines": lines, "changed": ["1 bet a day"]}))
        card = self.fine(client=client)
        self.assertEqual(card["explanation"]["source"], "template")                             # the facts are the only source of numbers

    def test_the_background_does_not_widen_what_the_number_check_allows(self):
        facts = {"kind": "minor", "days": 30, "before": {"graded": 40}, "after": {"graded": 30}, "changes": ["x"]}
        data = {"lines": ["a short line here", "another short line", "a 777 line here"], "changed": ["one change"]}
        self.assertIsNone(rebuild_ai.explanation_ok(data, facts))
        sent = []

        class Caller:
            def call(self, model, system, user, schema, *, max_tokens, stage):
                sent.append(user)
                return {"ok": True, "data": data, "reason": None}
        self.assertEqual(rebuild_ai.explain(Caller(), facts, background="It won 777 of them.")["source"], "template")
        self.assertIn("It won 777 of them.", sent[0])

    def test_a_feed_that_cannot_be_read_never_stops_a_training(self):
        def boom():
            raise RuntimeError("ledger")
        with mock.patch.object(postmortems, "default_engine", boom):
            card, client = self.rebuild()
        self.assertTrue(card["found"])
        self.assertEqual(plans._hindsight_text(self.dog_obj(), self.db), "")


# ---------------------------------------------------------------------------------------------------------------------
class TheChat(ChatBase):
    def setUp(self):
        super().setUp()
        self.rig = BackfillRig(on=False)
        self.addCleanup(self.rig.close)
        patch = mock.patch.object(postmortems, "default_engine", lambda: self.rig.engine)
        patch.start()
        self.addCleanup(patch.stop)
        self.v2 = user_store.create_version(self.id, spec_dict(name="Dog Days", side_rule="underdog", tagline="Second try"), actor="owner:1",
                                            reason="edit", now=None, db=self.db)

    def facts(self):
        return facts_mod.collect(common.resolve(self.v2["id"]), user_store.lineage(self.v2["id"], db=self.db)[-1], now=None, db=self.db)

    def test_the_chat_facts_carry_the_reviews_of_every_version(self):
        add_review(self.rig.ledger, self.id, 1, date="2026-10-05", lesson=LESSON_OLD)
        add_review(self.rig.ledger, self.v2["id"], 2, date="2026-10-20", lesson=LESSON_NOW)
        add_deep(self.rig.deep, self.v2["root_id"], settled=12, headline="Deep headline for the chat.", hound_ids=(self.id, self.v2["id"]))
        facts = self.facts()
        self.assertIn(LESSON_OLD, facts["hindsight"])
        text = facts_mod.render(facts)
        self.assertIn("HINDSIGHT REVIEWS OF THIS HOUND'S PAST BETS", text)
        self.assertIn("Deep headline for the chat.", text)
        self.assertLess(text.index("REHEARSAL"), text.index("HINDSIGHT REVIEWS"))
        self.assertLess(text.index("HINDSIGHT REVIEWS"), text.index("NOT PROVIDED TO YOU"))

    def test_with_no_reviews_the_chat_block_is_exactly_what_it_was(self):
        facts = self.facts()
        self.assertEqual(facts["hindsight"], "")
        text = facts_mod.render(facts)
        self.assertNotIn("HINDSIGHT", text)
        self.assertIn("NOT PROVIDED TO YOU", text)

    def test_the_stable_prompt_says_a_review_is_written_after_the_result(self):
        text = facts_mod.stable_system("[]")
        self.assertIn("written AFTER the result", text)
        self.assertIn("never present it as what you knew before the game", text)

    def test_a_ledger_that_cannot_be_read_leaves_the_chat_working(self):
        def boom():
            raise RuntimeError("ledger")
        with mock.patch.object(postmortems, "default_engine", boom):
            facts = self.facts()
        self.assertEqual(facts["hindsight"], "")

    def test_the_hindsight_block_reaches_the_model_in_the_hound_block(self):
        add_review(self.rig.ledger, self.id, 1, lesson=LESSON_OLD)
        from tests.test_hounds_chat import FakeClient as ChatClient, reply
        client = ChatClient(reply("ok"))
        self.send("hi", client, hound_id=self.v2["id"])
        block = client.calls[0]["system"][1]["text"]
        self.assertIn(LESSON_OLD, block)
        self.assertNotIn(LESSON_OLD, client.calls[0]["system"][0]["text"])                      # the cached prefix stays the same for everyone


if __name__ == "__main__":
    unittest.main()
