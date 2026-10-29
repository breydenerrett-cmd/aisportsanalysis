"""A full rebuild that comes back with nothing (owner, 2026-10-29: a Gematria hound's rebuild ended "did not produce a rule set ... This counted
as one of today's rebuilds", plus a rehearsal block reading "Updated rules: Not rehearsed, 0 graded bets", and only a Close button: "this doesn't
feel very helpful").

  THE ALLOWANCE   a rebuild that found no candidate does not use up the member's day; the AI spend is still on the books (the month's cap sees
                  it) and a model that keeps failing cannot be re-asked for free all day
  THE WHY         the card carries counts taken from what the rebuild really did (tried, broke a rule check, too close, could not be read,
                  rehearsed with their graded bets) and 2 to 4 plain lines made from them
  THE BLOCK       with no candidate there is no "Updated rules" side and no "0 graded bets" placeholder
  THE GEMATRIA    the root-cause hunt: a member Gematria hound's survivors ARE rehearsed together by the real batch drill, and an empty result
  HOUND           can only mean no survivor (never a batch that silently returned nothing)

No real model is called: a fake client stands in for the SDK, and the drill runs over a fixture board.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from src.hounds import user_engine, user_gematria as G, user_settle
from src.hounds.interact import drill, gematria_training as GT, rebuild_ai, rebuild_budget as budget, training_plans as plans
from src.hounds.interact.rites import RiteError
from tests.test_ai_hounds import nba_rows
from tests.test_gematria_member_style import DATE, runtime_factory
from tests.test_gematria_training import BIG, GemBase, gem_responder
from tests.test_training_plans import Base, FakeClient, angle_of, stage_of

UTC = timezone.utc
BANNED = ("beta", "edge", "lock", "guarantee", "profit", "will win", " new ")


class Failing(FakeClient):
    """A client whose request for the angles in ``fail`` raises, like a dropped connection."""

    def __init__(self, responder, fail, which=angle_of):
        super().__init__(responder)
        self.fail, self.which = set(fail), which

    def stream(self, **kw):
        if stage_of(kw) == "angle" and self.which(kw) in self.fail:
            self.calls.append(kw)
            raise RuntimeError("connection dropped")
        return super().stream(**kw)


def tweak_responder(dog_spec):
    cur = rebuild_ai.v2_of(dog_spec)
    small = {"summary": "tiny", "spec_json": json.dumps(dict(cur, max_bets_per_day=cur["max_bets_per_day"] % 5 + 1))}

    def responder(kw):
        return small if stage_of(kw) == "angle" else {}
    return responder


class TheAllowance(Base):
    def nothing(self, **over):
        return self.rebuild(client=FakeClient(tweak_responder(self.dog_obj().spec)), **over)[0]

    def test_a_rebuild_with_no_candidate_leaves_the_days_allowance_whole(self):
        card = self.nothing()
        self.assertFalse(card["found"])
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 0)
        self.assertEqual(card["usage"], {"used_today": 0, "limit_per_day": budget.FREE_REBUILDS_PER_DAY, "left_today": budget.FREE_REBUILDS_PER_DAY})
        # the free member's one rebuild is still theirs
        self.assertTrue(self.rebuild()[0]["found"])
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 1)

    def test_the_message_no_longer_says_it_counted_and_says_it_did_not(self):
        card = self.nothing()
        self.assertNotIn("counted as one", card["message"])
        self.assertIn("did not use up one of today's rebuilds", card["message"])
        self.assertIn("Nothing was changed", card["message"])
        self.assertIn("Fine-tune is still open", card["message"])

    def test_the_spend_is_still_on_the_books(self):
        before = self.ledger_book.month_spend()
        self.nothing()
        (row,) = self.ledger_book.rows()
        self.assertEqual(row["status"], budget.NO_CANDIDATE_STATUS)
        self.assertGreater(row["cost_usd"], 0)
        self.assertGreater(row["calls"], 0)
        self.assertGreater(self.ledger_book.month_spend(), before)             # the month's cap sees the real money

    def test_a_found_rebuild_still_uses_up_the_day(self):
        self.assertTrue(self.rebuild()[0]["found"])
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 1)
        with self.assertRaises(RiteError) as ctx:
            self.rebuild()
        self.assertEqual(ctx.exception.code, "daily_limit")

    def test_a_model_that_keeps_failing_cannot_be_asked_for_free_all_day(self):
        for _ in range(budget.NO_CANDIDATE_RETRIES_PER_DAY):
            self.assertFalse(self.nothing()["found"])
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 0)
        with self.assertRaises(RiteError) as ctx:
            self.nothing()
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("daily_limit", 429))
        self.assertIn("did not come back with a usable rule set", str(ctx.exception))
        self.assertIn("Fine-tune is still open", str(ctx.exception))
        # a different member is not held up by it, and tomorrow it is open again
        self.assertEqual(self.ledger_book.no_candidates_today(self.other.id), 0)
        self.clock[0] = datetime(2026, 10, 21, 0, 5, tzinfo=UTC)
        self.assertFalse(self.nothing()["found"])

    def test_a_fine_tune_write_up_is_not_a_no_candidate_either(self):
        self.ledger_book.record(user_id=self.owner.id, hound_id="x", status="fine_tune", calls=1, cost_usd=0.01, input_tokens=1, output_tokens=1)
        self.assertEqual((self.ledger_book.used_today(self.owner.id), self.ledger_book.no_candidates_today(self.owner.id)), (0, 0))


class TheWhy(Base):
    def run_mixed(self):
        """6 angles: one throws away on the law (-200), one stays a tweak, one drops its connection, the rest are fine but identical."""
        cur = rebuild_ai.v2_of(self.dog_obj().spec)
        tweak = json.dumps(dict(cur, max_bets_per_day=cur["max_bets_per_day"] % 5 + 1))
        bad = json.dumps({"version": 2, "rules": [dict(rule, price_min=-250) for rule in cur["rules"]]})
        per = {"mix": bad, "price": tweak}

        def responder(kw):
            if stage_of(kw) != "angle":
                return {}
            a = angle_of(kw)
            return {"summary": "x", "spec_json": per.get(a, tweak)}
        return self.rebuild(client=Failing(responder, fail={"situation"}))[0]

    def test_the_why_is_counted_from_what_the_rebuild_really_did(self):
        card = self.run_mixed()
        why = card["why"]
        self.assertFalse(card["found"])
        self.assertEqual(why["tried"], len(rebuild_ai.angles()))
        self.assertEqual(why["broke_checks"], 1)                       # the -200 one
        self.assertEqual(why["unreadable"], 1)                         # the dropped connection
        self.assertEqual(why["too_close"], why["tried"] - 2)           # every other answer stayed a tweak, even after the send-back
        self.assertEqual((why["built"], why["rehearsed"], why["graded"]), (0, 0, []))
        self.assertEqual(why["days"], plans.REPLAY_DAYS)
        self.assertEqual(why["min_bets"], plans.MIN_REPLAY_BETS)

    def test_the_lines_are_two_to_four_short_plain_sentences_made_from_the_counts(self):
        why = self.run_mixed()["why"]
        lines = why["lines"]
        self.assertTrue(2 <= len(lines) <= 4, lines)
        text = " ".join(lines)
        self.assertIn(f"It tried {why['tried']} versions", text)
        self.assertIn("1 broke a rule check", text)
        self.assertIn("1 could not be read", text)
        self.assertIn(f"{why['too_close']} were too close to the rules it has now", text)
        self.assertIn(f"None got as far as a rehearsal on the last {plans.REPLAY_DAYS} days.", text)
        for line in lines:
            self.assertLess(len(line), 140)
        low = " " + text.lower() + " "
        for word in BANNED:
            self.assertNotIn(word, low)

    def test_the_why_never_blames_a_stage_that_did_not_fail(self):
        why = self.run_mixed()["why"]
        text = " ".join(why["lines"])
        self.assertNotIn("repeated", text)                             # nothing repeated another version
        self.assertNotIn("spending limit", text)

    def test_the_lines_say_thin_rehearsals_honestly(self):
        """The branch for candidates that WERE rehearsed but each on too few bets (what the owner's example sentence describes)."""
        results = [{"spec": {"a": 1}, "refused": None}, {"spec": {"a": 2}, "refused": None}, {"spec": {"a": 3}, "refused": None},
                   {"spec": None, "refused": "invalid: price_min is wrong"}]
        survivors = results[:3]
        replayed = [{"replay": {"graded": g}} for g in (4, 7, 9)]
        why = plans.rebuild_why(results, survivors, replayed, days=14)
        self.assertEqual((why["tried"], why["built"], why["broke_checks"], why["rehearsed"], why["graded"]), (4, 3, 1, 3, [4, 7, 9]))
        self.assertEqual(why["lines"][0], "It tried 4 versions of the rules.")
        self.assertEqual(why["lines"][1], "1 broke a rule check.")
        self.assertEqual(why["lines"][2], "3 were rehearsed on the last 14 days, with 4, 7, 9 graded bets, each under the 20 needed to compare.")

    def test_counts_that_are_one_say_was_and_a_version(self):
        why = plans.rebuild_why([{"spec": None, "refused": "too_similar"}], [], [], days=14)
        self.assertEqual(why["lines"][:2], ["It tried 1 version of the rules.", "1 was too close to the rules it has now."])

    def test_repeats_and_the_spending_stop_are_named_when_they_happen(self):
        results = [{"spec": {"a": 1}, "refused": None}, {"spec": {"a": 1}, "refused": None}, {"spec": None, "refused": "over_budget"}]
        why = plans.rebuild_why(results, results[:1], [], days=14)
        self.assertEqual((why["repeats"], why["stopped_early"]), (1, 1))
        self.assertIn("1 repeated another version", why["lines"][1])
        self.assertIn("1 was not asked for, to stay inside the spending limit", why["lines"][1])

    def test_each_refusal_code_has_one_bucket(self):
        for code, kind in (("invalid: x", "broke_checks"), ("too_similar", "too_close"), ("over_budget", "stopped_early"), ("call_failed", "unreadable"),
                           ("not_json", "unreadable"), ("max_tokens", "unreadable"), ("refusal", "unreadable"), (None, "unreadable")):
            self.assertEqual(plans.refusal_kind(code), kind)

    def test_nothing_is_logged_that_could_hold_a_key(self):
        with self.assertLogs("linehound.hounds.training_plans", level="INFO") as logs:
            self.run_mixed()
        joined = "\n".join(logs.output)
        self.assertIn("rebuild found no candidate", joined)
        self.assertNotIn("sk-ant", joined)


class TheBlock(unittest.TestCase):
    def test_with_no_candidate_the_sample_line_is_about_the_rules_it_has_now(self):
        base = plans.numbers_of({"record": {"graded": 12, "wins": 3, "losses": 9, "pushes": 0}, "units_average_price": -5.67})
        block = plans.rehearsal_block(base, None, days=14)
        self.assertIsNone(block["after"])
        self.assertNotIn("0 graded", block["sample_text"])
        self.assertEqual(block["sample_text"], "12 graded bets in the rehearsal of the rules it has now: a small sample, so treat it as a rough look.")

    def test_a_candidate_side_reads_as_before(self):
        base = plans.numbers_of({"record": {"graded": 40, "wins": 20, "losses": 20, "pushes": 0}, "units_average_price": -4.0})
        after = plans.numbers_of({"record": {"graded": 1, "wins": 1, "losses": 0, "pushes": 0}, "units_average_price": 1.0})
        self.assertEqual(plans.rehearsal_block(base, after, days=30)["sample_text"], "1 graded bet in the rehearsal: a small sample, so treat it as a rough look.")
        big = plans.numbers_of({"record": {"graded": 31, "wins": 20, "losses": 11, "pushes": 0}, "units_average_price": 3.0})
        self.assertEqual(plans.rehearsal_block(base, big, days=30)["sample_text"], "31 graded bets in the rehearsal.")

    def test_nothing_to_say_when_nothing_was_rehearsed_at_all(self):
        self.assertEqual(plans.rehearsal_block(None, None, days=14)["sample_text"], "")


# ---------------------------------------------------------------------------------------------------------------
# THE GEMATRIA HUNT. What the production card could and could not mean:
#   * "Updated rules, same days: Not rehearsed / 0 graded bets in the rehearsal" was ``rehearsal_block(base, None)``: the "0" is a placeholder
#     for a missing side (training_plans.rehearsal_block, n = 0 when ``after`` is None), not a measurement of a candidate.
#   * ``rank`` keeps every rehearsed candidate (graded bets only reorder them), so the ``found: false`` branch is reached ONLY when there is no
#     rehearsed candidate at all, i.e. every angle was thrown away before the rehearsal (rule check, too close, an unreadable or stopped call).
#   * The batch rehearsal itself works: this class runs the REAL ``drill.drill_many`` over a fixture board and every survivor comes back with
#     numbers, including one that places no bet.
class TheGematriaHunt(GemBase):
    NOW_DRILL = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    def rehearse(self):
        seen = {"batches": []}
        inject = dict(rows_by_date={DATE: nba_rows()}, mlb_results={}, nfl_results=lambda d: {}, game_pk_index={})

        def many(specs, days, now):
            seen["batches"].append(len(specs))
            return drill.drill_many(specs=list(specs), days=days, now=self.NOW_DRILL, **inject)

        def one(spec, days, now):
            return drill.drill(spec=dict(spec), days=days, now=self.NOW_DRILL, rehearsal=True, **inject)
        return seen, one, many

    def test_the_real_batch_drill_gives_every_survivor_numbers_and_the_card_is_found(self):
        seen, one, many = self.rehearse()
        client = FakeClient(gem_responder())
        with mock.patch.object(G, "make_runtime", runtime_factory()), mock.patch.object(user_settle, "settle", lambda **k: None), \
                mock.patch.object(user_engine, "ledger_path", lambda p=None: p or self.dir / "drill.jsonl"):
            card = plans.full_rebuild(self.dog_obj(), self.owner.id, client=client,
                                      **self.common(replay_fn=one, replay_many_fn=many))
        self.assertTrue(card["found"], card.get("why") or card.get("message"))
        self.assertEqual(len(seen["batches"]), 1)                                  # one pass for all the survivors
        self.assertGreaterEqual(seen["batches"][0], 1)
        plan = self.store.load(card["plan_id"])
        self.assertTrue(plan["choices"])
        for choice in plan["choices"].values():
            self.assertIsNotNone(choice["after"])                                  # every offered version carries real rehearsal numbers
            self.assertIn("graded", choice["after"])
        self.assertEqual(card["rehearsal"]["days"], plans.REPLAY_DAYS_GEMATRIA)

    def test_a_candidate_that_places_no_bet_in_the_rehearsal_is_still_ranked_not_dropped(self):
        """``rank`` orders by the gate and keeps the rest: a zero-bet rehearsal is a result, not an absence."""
        zero = {"replay": plans.numbers_of({"record": {"graded": 0, "wins": 0, "losses": 0, "pushes": 0}, "units_average_price": None})}
        rich = {"replay": plans.numbers_of({"record": {"graded": 25, "wins": 12, "losses": 13, "pushes": 0}, "units_average_price": -1.0})}
        ranked = plans.rank(None, [zero, rich])
        self.assertEqual(len(ranked), 2)
        self.assertIs(ranked[0], rich)

    def test_when_every_gematria_angle_is_thrown_away_the_card_says_so_in_numbers_and_the_day_is_kept(self):
        refuse = {a[0]: dict(BIG, tuning={"price_min": -250}) for a in GT.GEM_ANGLES}
        card = plans.full_rebuild(self.dog_obj(), self.owner.id, client=FakeClient(gem_responder(per_angle=refuse)),
                                  **self.common(replay_fn=lambda sp, d, n: {"record": {"graded": 12, "wins": 3, "losses": 9, "pushes": 0},
                                                                          "units_average_price": -5.67, "days": d, "picks": []}))
        self.assertFalse(card["found"])
        self.assertTrue(card["chalk"])                                              # a Gematria card still says how the hound leans
        why = card["why"]
        self.assertEqual((why["broke_checks"], why["too_close"], why["rehearsed"]), (why["tried"], 0, 0))
        self.assertEqual(card["rehearsal"]["before"]["graded"], 12)
        self.assertIsNone(card["rehearsal"]["after"])
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 0)
        self.assertEqual(self.ledger_book.rows()[-1]["status"], budget.NO_CANDIDATE_STATUS)
        self.assertEqual(card["rehearsal"]["days"], plans.REPLAY_DAYS_GEMATRIA)


if __name__ == "__main__":
    unittest.main()
