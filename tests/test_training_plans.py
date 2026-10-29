"""Fine-tune and Full rebuild (src/hounds/interact/training_plans.py, rebuild_ai.py, rebuild_budget.py), owner request 2026-10-27.

No real API call is ever made: a fake client stands in for the ``anthropic`` SDK and a fake replay stands in for the drill. The story
each group pins:

  FINE-TUNE   a change is offered ONLY if it beat the current rule on the rehearsal by the gate; if none does the answer says so and
              offers the rebuild; a suggestion that is not better is never shown.
  REBUILD     a candidate too close to the current rule is sent back once and dropped if still too close; the law (-200, rule count,
              catalog conditions) is enforced in code on every candidate and on the analyst's merge; the best survivor by the
              rehearsal is shown with before/after numbers; the explainer cannot invent a number.
  COST        a free member gets one rebuild a day and a paid one three; the month's spend guard refuses; a missing key is
              "unavailable right now"; no secret reaches a ledger, a plan or a log.
  APPLY       goes through user_store.create_version, only for the plan's owner, only once, only against the rule the plan was made for.
"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.hounds import user_spec, user_store
from src.hounds.interact import rebuild_ai, rebuild_budget as budget, training, training_plans as plans
from src.hounds.interact.rites import RiteError
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for

KEY = "sk-ant-test-SECRETVALUE123456"
ENV = {"ANTHROPIC_API_KEY": KEY}
MIXED = [(7, dict(result="LOSS", side="away", price=180)), (2, dict(result="WIN", side="away", price=180)),
         (6, dict(result="WIN", side="home", price=110, sport="NFL")), (3, dict(result="LOSS", side="home", price=110, sport="NFL"))]


def summary(graded, units, wins=None, days=30):
    wins = graded // 2 if wins is None else wins
    return {"record": {"graded": graded, "wins": wins, "losses": graded - wins, "pushes": 0, "bets": graded},
            "units_average_price": units, "days": days, "picks": []}


def rule(**kw):
    base = {"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": 100, "price_max": 250, "min_books": 3, "when": None}
    base.update(kw)
    return base


RULE_SET = [rule(label="mlb dogs", when={"op": "all", "items": [{"id": "role", "value": "underdog"}]}),
            rule(label="nfl spread", sports=["NFL"], markets=["spread"], price_min=-150, price_max=120),
            rule(label="mlb totals", markets=["total"], side="under", price_min=-130, price_max=110),
            rule(label="nhl", sports=["NHL"], price_min=110, price_max=300)]


def big_spec(n=2, **top):
    spec = {"version": 2, "rules": RULE_SET[:n], "max_bets_per_day": 3, "stake_units": 1.0, "lock_minutes": 120, "rank_by": "earliest_lock"}
    spec.update(top)
    return spec


def fake_replay(spec, days, now):
    """The baseline (a classic rule set) is 40 graded bets at -4 units; a rebuilt one earns 3 units per rule less 2, on 30 bets."""
    if not user_spec.is_v2(spec):
        return summary(40, -4.0, days=days) if spec.get("max_bets_per_day") != 1 else summary(30, 2.0, days=days)
    return summary(30, 3.0 * len(spec["rules"]) - 2.0, days=days)


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """Stands in for ``anthropic.Anthropic``: ``responder(kwargs)`` returns the JSON payload for the stage the request is."""

    def __init__(self, responder):
        self.responder, self.calls, self.messages = responder, [], self

    def stream(self, **kw):
        self.calls.append(kw)
        payload = self.responder(kw)
        text = json.dumps(payload)
        usage = SimpleNamespace(input_tokens=len(kw["messages"][0]["content"]) // 4, output_tokens=2500)
        return FakeStream(SimpleNamespace(stop_reason="end_turn", usage=usage, content=[SimpleNamespace(type="text", text=text)]))


def stage_of(kw) -> str:
    required = kw["output_config"]["format"]["schema"]["required"]
    return "analyst" if "chosen" in required else "explainer" if "lines" in required else "angle"


def angle_of(kw) -> str:
    text = kw["messages"][0]["content"]
    return next((a[0] for a in rebuild_ai.ANGLES if f"YOUR ANGLE: {a[1]}." in text), "?")


GOOD_EXPLAIN = {"lines": ["It now looks at more kinds of games than before.", "The rules it had were losing in the rehearsal.",
                          "In the rehearsal of the last 30 days the updated rules had 30 graded bets."],
                "changed": ["It bets up to 3 a day now"]}


def standard_responder(per_angle=None, analyst=None, explain=None):
    per_angle = per_angle or {}

    def responder(kw):
        stage = stage_of(kw)
        if stage == "angle":
            a = angle_of(kw)
            n = {"mix": 1, "price": 2, "situation": 2, "cut": 1, "timing": 3, "volume": 2}.get(a, 2)
            spec = per_angle.get(a, big_spec(n, max_bets_per_day=3 + (n % 2) - 1 if n else 2))
            return {"summary": f"{a} angle rebuild with {n} rules", "spec_json": json.dumps(spec)}
        if stage == "analyst":
            return analyst if analyst is not None else {"chosen": "merge", "spec_json": json.dumps(big_spec(4, max_bets_per_day=2)),
                                                       "reasons": ["More rules cover more of the games"], "cut": ["one rule"],
                                                       "added": ["four rules"], "weak_spots": ["the sample is small"]}
        return explain if explain is not None else GOOD_EXPLAIN
    return responder


class Base(RitesCase):
    def setUp(self):
        super().setUp()
        self.tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp2.cleanup)
        self.dir = Path(self.tmp2.name)
        self.clock = [datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)]
        self.ledger_book = budget.RebuildLedger(self.dir / "rebuilds.jsonl", clock=lambda: self.clock[0])
        self.store = plans.PlanStore(self.dir / "plans")
        self.hound_row = self.dog("Rusty Pup", sports=["MLB", "NFL"], markets=["moneyline", "spread"], side_rule="underdog")
        self.rows = rows_for(self.hound_row["id"], MIXED)

    def common(self, **over):
        kw = dict(now=NOW, rows=self.rows, db=self.db, replay_fn=fake_replay, env=ENV, ledger=self.ledger_book, store=self.store,
                  router_spend=lambda: (0.0, 5.0))
        kw.update(over)
        return kw

    def dog_obj(self):
        return self.resolve(self.hound_row["id"])

    def rebuild(self, client=None, paid=False, **over):
        client = client or FakeClient(standard_responder())
        return plans.full_rebuild(self.dog_obj(), self.owner.id, paid=paid, client=client, **self.common(**over)), client

    def fine(self, replay_fn=None, client=None, **over):
        """Always with a fake client: with a key in the env and none injected, the real SDK would be built (and, where it is installed,
        would call out)."""
        client = client or FakeClient(standard_responder())
        return plans.fine_tune(self.dog_obj(), self.owner.id, client=client, **self.common(**dict({"replay_fn": replay_fn or fake_replay}, **over)))


# ---------------------------------------------------------------------------------------------------------------
class FineTune(Base):
    def test_a_change_is_offered_only_when_it_beat_the_current_rule_on_the_rehearsal(self):
        card = self.fine()        # fake_replay: one bet a day earns +2 on 30 bets, the current rule -4 on 40
        self.assertTrue(card["found"])
        self.assertEqual((card["rehearsal"]["before"]["units"], card["rehearsal"]["after"]["units"]), (-4.0, 2.0))
        self.assertEqual((card["rehearsal"]["before"]["graded"], card["rehearsal"]["after"]["graded"]), (40, 30))
        self.assertFalse(card["rehearsal"]["counted"])
        self.assertIn("not counted", card["rehearsal"]["label"])
        self.assertTrue(card["beats_current"])
        self.assertTrue(self.store.load(card["plan_id"]))

    def test_no_change_that_does_not_beat_it_is_ever_shown(self):
        same = lambda spec, days, now: summary(40, -4.0, days=days)                       # noqa: E731
        card = self.fine(replay_fn=same)
        self.assertFalse(card["found"])
        self.assertNotIn("plan_id", card)
        self.assertTrue(card["rebuild_offer"])
        self.assertIn("None of the", card["message"])
        self.assertIn("full rebuild", card["message"].lower())
        self.assertEqual(list((self.dir / "plans").glob("*.json")) if (self.dir / "plans").exists() else [], [])

    def test_a_better_looking_change_on_too_few_bets_is_not_offered(self):
        thin = lambda spec, days, now: summary(40, -4.0, days=days) if spec.get("max_bets_per_day") != 1 else summary(8, 6.0, days=days)  # noqa: E731
        self.assertFalse(self.fine(replay_fn=thin)["found"])

    def test_a_change_that_only_stops_betting_is_not_better(self):
        starve = lambda spec, days, now: summary(40, -4.0, days=days) if spec.get("max_bets_per_day") != 1 else summary(12, 3.0, days=days)  # noqa: E731
        self.assertFalse(self.fine(replay_fn=starve)["found"])

    def test_the_gate_in_numbers(self):
        base = plans.numbers_of(summary(40, -4.0))
        ok = plans.numbers_of(summary(30, 2.0))
        self.assertTrue(plans.beats(base, ok))
        self.assertFalse(plans.beats(base, plans.numbers_of(summary(30, -3.5))))                 # under the units gain
        self.assertFalse(plans.beats(base, plans.numbers_of(summary(19, 5.0))))                  # under the bet floor
        winner = plans.numbers_of(summary(40, 4.0))
        self.assertFalse(plans.beats(winner, plans.numbers_of(summary(200, 5.0))))               # more units only by betting far more
        self.assertFalse(plans.beats(None, ok))
        self.assertFalse(plans.beats(base, None))

    def test_the_explanation_is_in_plain_words_even_with_no_key(self):
        card = self.fine(env={})
        self.assertEqual(card["explanation"]["source"], "template")
        self.assertTrue(card["explanation"]["lines"])

    def test_the_explainer_runs_on_the_fine_tune_too(self):
        client = FakeClient(standard_responder(explain={"lines": ["It takes at most 1 bet a day now.", "The rehearsal went better.",
                                                              "That was 30 graded bets over the last 30 days."], "changed": ["1 bet a day"]}))
        card = self.fine(client=client)
        self.assertEqual(card["explanation"]["source"], "ai")
        self.assertEqual([stage_of(c) for c in client.calls], ["explainer"])


# ---------------------------------------------------------------------------------------------------------------
class TheLaw(Base):
    def current(self):
        return rebuild_ai.v2_of(self.dog_obj().spec)

    def test_a_label_the_menu_would_refuse_is_blanked_not_a_reason_to_lose_the_candidate(self):
        spec, why = rebuild_ai.vet_spec(big_spec(2, rules=[dict(RULE_SET[0], label="MLB underdogs"), dict(RULE_SET[1], label="Road spreads")]), self.current())
        self.assertIsNone(why)
        self.assertEqual([r["label"] for r in spec["rules"]], ["", "Road spreads"])

    def test_a_good_rule_set_passes_and_keeps_the_hounds_name_and_look(self):
        spec, why = rebuild_ai.vet_spec(json.dumps(dict(big_spec(2), name="Evil Name", style="gematria", color="gold")), self.current())
        self.assertIsNone(why)
        self.assertEqual(spec["name"], "Rusty Pup")
        self.assertNotIn("style", spec)

    def test_a_price_at_minus_200_is_refused_whole(self):
        bad = big_spec(2)
        bad["rules"] = [dict(RULE_SET[0], price_min=-200, price_max=100)] + RULE_SET[1:2]
        spec, why = rebuild_ai.vet_spec(bad, self.current())
        self.assertIsNone(spec)
        self.assertIn("price_min", why)

    def test_more_than_the_maximum_rules_is_refused(self):
        spec, why = rebuild_ai.vet_spec(big_spec(4, rules=RULE_SET + [rule(label="five")]), self.current())
        self.assertIsNone(spec)
        self.assertIn(str(rebuild_ai.user_rules.MAX_RULES), why)

    def test_a_condition_that_is_not_in_the_catalog_is_refused_not_repaired(self):
        bad = big_spec(1, rules=[rule(when={"op": "all", "items": [{"id": "guaranteed_winner", "value": 1}]})])
        spec, why = rebuild_ai.vet_spec(bad, self.current())
        self.assertIsNone(spec)
        self.assertTrue(why)

    def test_text_that_is_not_json_is_refused(self):
        self.assertIsNone(rebuild_ai.vet_spec("not json at all", self.current())[0])
        self.assertIsNone(rebuild_ai.vet_spec("[1,2]", self.current())[0])

    def test_the_distance_measures_a_cosmetic_tweak_and_a_real_rebuild(self):
        cur = self.current()
        tweak = dict(cur, max_bets_per_day=cur["max_bets_per_day"] % 5 + 1)
        d = rebuild_ai.spec_distance(cur, user_spec.validate_spec(tweak))
        self.assertTrue(rebuild_ai.too_similar(d))
        rebuilt, _ = rebuild_ai.vet_spec(big_spec(3), cur)
        d2 = rebuild_ai.spec_distance(cur, rebuilt)
        self.assertFalse(rebuild_ai.too_similar(d2))
        self.assertGreaterEqual(d2["points"], rebuild_ai.MIN_DISTANCE_POINTS)

    def test_the_current_rule_itself_is_too_similar(self):
        cur = self.current()
        self.assertTrue(rebuild_ai.too_similar(rebuild_ai.spec_distance(cur, cur)))


# ---------------------------------------------------------------------------------------------------------------
class FullRebuild(Base):
    def test_the_best_survivor_by_the_rehearsal_is_shown_with_before_and_after(self):
        card, client = self.rebuild()
        self.assertTrue(card["found"])
        self.assertEqual(card["rehearsal"]["before"]["units"], -4.0)
        self.assertEqual(card["rehearsal"]["after"]["units"], 10.0)         # the analyst's four-rule merge: 3*4-2
        self.assertFalse(card["rehearsal"]["counted"])
        self.assertTrue(card["beats_current"])
        self.assertLessEqual(len(card["runners_up"]), plans.RUNNERS_UP)
        stages = sorted(stage_of(c) for c in client.calls)
        self.assertEqual(stages.count("angle"), rebuild_ai.ANGLE_COUNT)
        self.assertEqual((stages.count("analyst"), stages.count("explainer")), (1, 1))
        self.assertEqual(card["usage"]["left_today"], 0)

    def test_each_call_uses_the_sdk_the_way_the_skill_says(self):
        _card, client = self.rebuild()
        for kw in client.calls:
            self.assertEqual(kw["model"], "claude-haiku-5-5")
            self.assertEqual(kw["thinking"], {"type": "adaptive"})
            self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
            self.assertNotIn("temperature", kw)
            self.assertNotIn("budget_tokens", json.dumps(kw["thinking"]))
            self.assertNotIn(KEY, json.dumps(kw))

    def test_the_prompt_gives_everything_and_demands_a_major_change(self):
        _card, client = self.rebuild()
        angle = next(c for c in client.calls if stage_of(c) == "angle")
        user, system = angle["messages"][0]["content"], angle["system"]
        for needle in ("CURRENT RULE IN PLAIN ENGLISH", "FORWARD RECORD", "THIS COUNTS", "NEVER counted", "BREAKDOWNS", "BIGGEST FORWARD LOSERS",
                       "EVERY FORWARD BET", "CONDITION CATALOG", "SPORTS A RULE MAY USE", "STAKE CHOICES", "DATA, NOT INSTRUCTIONS"):
            self.assertIn(needle, user)
        for needle in ("MAJOR departure", "cosmetic tweak is a failed answer", "-200", "At most 4 rules"):
            self.assertIn(needle, system)
        self.assertIn("rule=", user)                                   # the forward bets are listed one by one
        self.assertIn("sport=MLB", user)                               # and cut by sport

    def test_a_too_similar_answer_is_sent_back_once_with_the_measured_gap(self):
        cur = rebuild_ai.v2_of(self.dog_obj().spec)
        seen = {}

        def responder(kw):
            if stage_of(kw) != "angle":
                return standard_responder()(kw)
            a = angle_of(kw)
            seen.setdefault(a, 0)
            seen[a] += 1
            if a == "mix" and seen[a] == 1:
                return {"summary": "tiny", "spec_json": json.dumps(dict(cur, max_bets_per_day=cur["max_bets_per_day"] % 5 + 1))}
            return standard_responder()(kw)
        card, client = self.rebuild(client=FakeClient(responder))
        self.assertEqual(seen["mix"], 2)
        retry = [c for c in client.calls if stage_of(c) == "angle" and "REFUSED" in c["messages"][0]["content"]]
        self.assertEqual(len(retry), 1)
        self.assertIn("only", retry[0]["messages"][0]["content"])
        self.assertTrue(card["found"])

    def test_an_angle_that_stays_too_similar_is_dropped_and_the_others_still_count(self):
        cur = rebuild_ai.v2_of(self.dog_obj().spec)
        small = {"summary": "tiny", "spec_json": json.dumps(dict(cur, max_bets_per_day=cur["max_bets_per_day"] % 5 + 1))}
        std = standard_responder()
        card, client = self.rebuild(client=FakeClient(lambda kw: small if stage_of(kw) == "angle" and angle_of(kw) == "mix" else std(kw)))
        self.assertTrue(card["found"])
        self.assertEqual(sum(1 for c in client.calls if stage_of(c) == "angle" and "YOUR ANGLE: Markets and sports mix." in c["messages"][0]["content"]),
                         1 + rebuild_ai.ANGLE_RETRIES)
        ids = [card["choice"]] + [u["choice"] for u in card["runners_up"]]
        self.assertTrue(all(i for i in ids))

    def test_when_every_answer_is_too_similar_nothing_is_shown_and_the_day_is_not_used_up(self):
        """Until 2026-10-29 this rebuild "counted as one of today's rebuilds"; the owner found that unhelpful. The spend is still logged
        (tests/test_rebuild_no_candidate.py holds the whole story); the member keeps the allowance."""
        cur = rebuild_ai.v2_of(self.dog_obj().spec)
        small = {"summary": "tiny", "spec_json": json.dumps(dict(cur, max_bets_per_day=cur["max_bets_per_day"] % 5 + 1))}
        card, _client = self.rebuild(client=FakeClient(lambda kw: small if stage_of(kw) == "angle" else {}))
        self.assertFalse(card["found"])
        self.assertNotIn("plan_id", card)
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 0)
        self.assertTrue(self.ledger_book.rows())

    def test_the_law_is_enforced_on_every_candidate_and_on_the_analysts_merge(self):
        cap = big_spec(2)
        cap["rules"] = [dict(RULE_SET[0], price_min=-200, price_max=100), RULE_SET[1]]
        junk = {"chosen": "merge", "spec_json": json.dumps(cap), "reasons": [], "cut": [], "added": [], "weak_spots": []}
        card, _c = self.rebuild(client=FakeClient(standard_responder(per_angle={"mix": cap}, analyst=junk)))
        self.assertTrue(card["found"])
        self.assertNotEqual(card["rehearsal"]["after"]["units"], 10.0)          # the refused merge was not used
        for choice in [card["choice"]] + [u["choice"] for u in card["runners_up"]]:
            spec = self.store.load(card["plan_id"])["choices"][choice]["spec"]
            self.assertTrue(all(r["price_min"] >= user_spec.SHORTEST_ALLOWED_PRICE for r in spec["rules"]))
            self.assertLessEqual(len(spec["rules"]), rebuild_ai.user_rules.MAX_RULES)

    def test_the_analysts_merge_is_replayed_like_any_candidate(self):
        replayed = []

        def spy(spec, days, now):
            replayed.append(len(spec.get("rules") or []))
            return fake_replay(spec, days, now)
        self.rebuild(replay_fn=spy)
        self.assertIn(4, replayed)                                       # the four-rule merge was rehearsed, not trusted

    def test_the_explainer_cannot_invent_a_number(self):
        lie = {"lines": ["It will win 87 percent of its bets.", "The rehearsal looked good.", "It bets 9 a day now."], "changed": ["x"]}
        card, _c = self.rebuild(client=FakeClient(standard_responder(explain=lie)))
        self.assertEqual(card["explanation"]["source"], "template")

    def test_the_explainer_may_not_use_a_banned_word(self):
        facts = {"before": {"graded": 40, "units": -4.0}, "after": {"graded": 30, "units": 10.0}, "days": 30}
        for word in ("This new hound is great.", "A dog of a rule.", "Guaranteed profit.", "Its ROI is strong.", "Nothing cleared the bar."):
            data = {"lines": [word, "Line two.", "Line three."], "changed": ["a"]}
            self.assertIsNone(rebuild_ai.explanation_ok(data, facts), word)

    def test_the_templated_explanation_obeys_the_copy_rules_and_only_uses_given_numbers(self):
        for kind in ("rebuild", "minor"):
            facts = {"kind": kind, "days": 30, "before": {"graded": 40, "units": -4.0}, "after": {"graded": 12, "units": 3.5}, "small_sample": True,
                     "changes": ["Most bets a day: 2 -> 1"]}
            out = rebuild_ai.template_explanation(facts)
            text = " ".join(out["lines"] + out["changed"])
            self.assertIsNone(rebuild_ai.BANNED_WORDS.search(text), text)
            self.assertIn("rehearsal", text)
            allowed = rebuild_ai.numbers_in(facts)
            self.assertTrue(set(rebuild_ai._NUMBER.findall(text)) <= allowed, text)

    def test_a_failed_call_is_not_a_crash(self):
        class Boom:
            messages = None

            def stream(self, **kw):
                raise RuntimeError(f"upstream said {KEY}")
        boom = Boom()
        boom.messages = boom
        card, _c = self.rebuild(client=boom)
        self.assertFalse(card["found"])


# ---------------------------------------------------------------------------------------------------------------
class TheMeter(Base):
    def test_missing_key_is_unavailable_not_an_error(self):
        client = FakeClient(standard_responder())
        with self.assertRaises(RiteError) as ctx:
            plans.full_rebuild(self.dog_obj(), self.owner.id, client=client, **self.common(env={}))
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("unavailable", 503))
        self.assertIn("unavailable right now", str(ctx.exception))
        self.assertEqual(client.calls, [])

    def test_a_fine_tunes_write_up_never_uses_up_the_rebuild_for_the_day(self):
        self.fine(client=FakeClient(standard_responder()))
        self.assertTrue(self.ledger_book.rows())                         # its spend is logged...
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 0)  # ...but it is not a rebuild
        self.assertTrue(self.rebuild()[0]["found"])

    def test_a_blank_key_is_the_same_as_none(self):
        self.assertIsNone(budget.api_key({"ANTHROPIC_API_KEY": "   "}))

    def test_a_free_member_gets_one_rebuild_a_day(self):
        self.rebuild()
        with self.assertRaises(RiteError) as ctx:
            self.rebuild()
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("daily_limit", 429))
        self.clock[0] = datetime(2026, 10, 21, 0, 5, tzinfo=timezone.utc)          # tomorrow, UTC
        self.assertTrue(self.rebuild()[0]["found"])

    def test_a_paid_member_gets_three(self):
        for _ in range(budget.PAID_REBUILDS_PER_DAY):
            self.assertTrue(self.rebuild(paid=True)[0]["found"])
        with self.assertRaises(RiteError) as ctx:
            self.rebuild(paid=True)
        self.assertEqual(ctx.exception.code, "daily_limit")
        self.assertGreater(budget.PAID_REBUILDS_PER_DAY, budget.FREE_REBUILDS_PER_DAY)

    def test_another_members_rebuilds_do_not_use_up_mine(self):
        self.ledger_book.record(user_id=self.other.id, hound_id="x", status="ok", calls=8, cost_usd=0.02, input_tokens=1, output_tokens=1)
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 0)

    def test_the_monthly_spend_guard_refuses(self):
        self.ledger_book.record(user_id=self.other.id, hound_id="x", status="ok", calls=8, cost_usd=budget.MONTHLY_REBUILD_USD, input_tokens=1, output_tokens=1)
        with self.assertRaises(RiteError) as ctx:
            self.rebuild()
        self.assertEqual(ctx.exception.code, "monthly_spend")

    def test_the_routers_shared_cap_is_a_second_wall(self):
        with self.assertRaises(RiteError) as ctx:
            self.rebuild(router_spend=lambda: (4.999, 5.0))
        self.assertEqual(ctx.exception.code, "monthly_spend")

    def test_the_owner_can_lower_the_month_by_environment(self):
        self.assertEqual(budget.monthly_cap({budget.MONTHLY_REBUILD_ENV: "0.5"}), 0.5)
        self.assertEqual(budget.monthly_cap({budget.MONTHLY_REBUILD_ENV: "junk"}), budget.MONTHLY_REBUILD_USD)
        with self.assertRaises(RiteError):
            self.rebuild(env=dict(ENV, **{budget.MONTHLY_REBUILD_ENV: "0.0001"}))

    def test_spend_is_the_apis_own_usage_times_the_price_and_is_written_to_the_ledger(self):
        self.rebuild()
        rows = self.ledger_book.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["calls"], rebuild_ai.ANGLE_COUNT + 2)
        expected = sum(budget.usage_cost("claude-haiku-5-5", {"input_tokens": 0, "output_tokens": 2500}) for _ in range(row["calls"]))
        self.assertGreater(row["cost_usd"], expected)                    # plus the prompts' input tokens
        self.assertLess(row["cost_usd"], budget.MONTHLY_REBUILD_USD)
        self.assertEqual(self.ledger_book.month_spend(), row["cost_usd"])

    def test_a_call_that_would_pass_the_ceiling_is_not_made(self):
        meter = rebuild_ai.Meter(0.0000001)
        client = FakeClient(standard_responder())
        got = rebuild_ai.Caller("k", meter, client=client).call("claude-haiku-5-5", "s", "u" * 3000, rebuild_ai.CANDIDATE_SCHEMA, max_tokens=12000, stage="t")
        self.assertEqual((got["ok"], got["reason"], client.calls), (False, "over_budget", []))

    def test_usage_missing_is_charged_its_worst_case_never_zero(self):
        self.assertIsNone(budget.usage_cost("claude-haiku-5-5", None))

    def test_the_worst_case_is_the_dearer_price_past_100k_tokens(self):
        self.assertGreater(budget.worst_case_cost("claude-haiku-5-5", 150_000, 1000), budget.worst_case_cost("claude-haiku-5-5", 90_000, 1000) * 4)

    def test_no_secret_reaches_the_ledger_a_plan_or_a_log(self):
        with self.assertLogs("linehound.hounds", level="INFO") as logs:
            logging.getLogger("linehound.hounds.rebuild").info("sentinel")
            card, _c = self.rebuild()
        blob = "\n".join(logs.output) + (self.dir / "rebuilds.jsonl").read_text(encoding="utf-8")
        blob += "".join(f.read_text(encoding="utf-8") for f in (self.dir / "plans").glob("*.json")) + json.dumps(card)
        self.assertNotIn(KEY, blob)
        self.assertNotIn("SECRETVALUE", blob)

    def test_the_angle_list_and_count_are_constants(self):
        self.assertEqual(rebuild_ai.ANGLE_COUNT, 6)
        self.assertEqual(len(rebuild_ai.angles()), 6)
        self.assertEqual(len(rebuild_ai.angles(9)), 9)
        self.assertEqual(len(rebuild_ai.angles(50)), len(rebuild_ai.ANGLES))
        self.assertFalse(rebuild_ai.USE_SONNET_SYNTHESIS)
        self.assertEqual(rebuild_ai.MODEL, "claude-haiku-5-5")

    def test_the_estimate_comes_from_the_real_prompt_size(self):
        worst, in_tokens = plans._stage_cost_worst("x" * 30000, 6)
        bigger, _ = plans._stage_cost_worst("x" * 90000, 6)
        self.assertGreater(bigger, worst)
        self.assertGreater(in_tokens, 10000)


# ---------------------------------------------------------------------------------------------------------------
class Apply(Base):
    def made(self):
        card = self.fine()
        self.assertTrue(card["found"])
        return card

    def apply(self, card, user=None, **kw):
        return plans.apply_plan(self.dog_obj(), (user or self.owner).id, card["plan_id"], now=NOW, rows=self.rows, db=self.db, store=self.store, **kw)

    def test_apply_makes_the_next_version_through_create_version_and_freezes_the_old_one(self):
        card = self.made()
        out = self.apply(card, basis=card["basis"])
        self.assertEqual(out["mode"], "fine_tune")
        new = user_store.get_hound(out["new"]["id"], db=self.db)
        old = user_store.get_hound(self.hound_row["id"], db=self.db)
        self.assertEqual((new["version_no"], new["coached_from"], new["origin"]), (2, self.hound_row["id"], user_store.ORIGIN_FINE_TUNE))
        self.assertEqual(old["status"], user_store.STATUS_RETIRED)
        self.assertEqual(old["spec"], self.hound_row["spec"])                 # the old record stays with the old version
        self.assertEqual(out["new"]["record"]["bets"], 0)
        self.assertTrue(out["old"]["frozen"])
        events = user_store.list_events(root_id=self.hound_row["root_id"])
        self.assertEqual(events[-1]["payload"]["mode"], "fine_tune")

    def test_a_rebuild_applies_with_its_own_origin(self):
        card, _c = self.rebuild()
        out = self.apply(card)
        self.assertEqual(out["origin"], user_store.ORIGIN_REBUILD)
        self.assertEqual(user_store.get_hound(out["new"]["id"], db=self.db)["spec"]["rules"][0]["markets"], ["moneyline"])

    def test_a_runner_up_can_be_applied_by_its_choice(self):
        card, _c = self.rebuild()
        pick = card["runners_up"][0]["choice"] if card["runners_up"] else card["choice"]
        out = self.apply(card, choice=pick)
        self.assertEqual(user_store.get_hound(out["new"]["id"], db=self.db)["version_no"], 2)

    def test_only_the_plans_owner_can_apply_it(self):
        card = self.made()
        with self.assertRaises(RiteError) as ctx:
            self.apply(card, user=self.other)
        self.assertEqual(ctx.exception.status, 404)

    def test_a_plan_is_used_once(self):
        card = self.made()
        self.apply(card)
        with self.assertRaises(RiteError):
            self.apply(card)

    def test_a_plan_for_a_rule_that_has_changed_is_stale(self):
        card = self.made()
        with self.assertRaises(RiteError) as ctx:
            self.apply(card, basis="u-other:0000")
        self.assertEqual(ctx.exception.code, training.STALE_PROPOSAL)

    def test_the_law_is_checked_again_at_apply_even_if_the_saved_plan_is_tampered_with(self):
        card, _c = self.rebuild()
        path = self.dir / "plans" / f"{card['plan_id']}.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        spec = body["choices"][body["main"]]["spec"]
        spec["rules"][0]["price_min"] = -250
        path.write_text(json.dumps(body), encoding="utf-8")
        with self.assertRaises(RiteError) as ctx:
            self.apply(card)
        self.assertEqual(ctx.exception.code, "spec_invalid")
        self.assertEqual(user_store.get_hound(self.hound_row["id"], db=self.db)["status"], self.hound_row["status"])

    def test_an_unknown_plan_id_is_just_not_found(self):
        for bad in ("../../etc/passwd", "x" * 24, "short", ""):
            with self.assertRaises(RiteError):
                plans.apply_plan(self.dog_obj(), self.owner.id, bad, now=NOW, rows=self.rows, db=self.db, store=self.store)


class Jobs(Base):
    def test_a_job_runs_and_its_card_is_readable_only_by_its_owner(self):
        board = plans.JobBoard()
        job = board.start(self.owner.id, "h", "minor", lambda progress: (progress("Working"), {"found": False})[1], background=False)
        self.assertEqual((job["state"], job["result"]), ("done", {"found": False}))
        self.assertIsNone(board.get(job["job_id"], self.other.id))
        self.assertEqual(board.get(job["job_id"], self.owner.id)["state"], "done")

    def test_a_refusal_inside_a_job_is_kept_as_the_jobs_error(self):
        def work(progress):
            raise RiteError("daily_limit", "used up", 429)
        job = plans.JobBoard().start(self.owner.id, "h", "rebuild", work, background=False)
        self.assertEqual((job["state"], job["error"]["code"]), ("failed", "daily_limit"))


if __name__ == "__main__":
    unittest.main()
