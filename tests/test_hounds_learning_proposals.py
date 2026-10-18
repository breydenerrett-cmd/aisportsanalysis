"""A pack-hound proposal: every guard, in the order the pre-registration lists them, and the rule that a
failed idea is not tried again.  (The user door's guards are tested in test_hounds_user_coach.py.)
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from src.hounds.learning import ledger as L, pause, proposals, rules, tunables
from tests import _learning_fixtures as F

NOW = F.utc("2026-11-10T12:00:00Z")
HYP = "A wider bar keeps only the clearest disagreements with the market, which should price better."


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.scope = L.Scope.house(Path(self._tmp.name))

    def propose(self, params=None, *, hound="professor_paws", graded=50, at=NOW, **kw):
        return proposals.propose_pack(self.scope, hound, params if params is not None else {"GAP": 0.03}, kw.pop("hypothesis", HYP),
                                      kw.pop("evidence", ["record.bets"]), graded=graded, now=at, **kw)

    def refused(self, code, *a, **kw):
        with self.assertRaises(proposals.ProposalError) as ctx:
            self.propose(*a, **kw)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def state(self):
        return L.read_state(self.scope)


class TheGuards(Case):
    def test_a_good_proposal_is_a_live_challenger_with_generated_text(self):
        c = self.propose()
        self.assertEqual((c.status, c.kind, c.hound_id, c.parent_version), ("live", "pack", "professor_paws", 1))
        self.assertEqual(c.spec["values"], {"GAP": 0.03, "SHRINK": 0.5})
        self.assertIn("3.0 points or more", c.spec["rule_text"])
        self.assertNotIn("2.0 points or more", c.spec["rule_text"])
        self.assertEqual(c.spec_diff, {"GAP": [0.02, 0.03]})
        self.assertEqual(c.category, "stats")
        self.assertEqual(self.state().challengers[c.id].hypothesis, HYP)

    def test_the_switch_is_checked_first_and_leaves_no_trace(self):
        with self.assertRaises(proposals.ProposalError) as ctx:
            self.propose(coach_on=False, graded=0, hypothesis="x")
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("coach_disabled", 503))
        self.assertEqual(self.state().refusals, [])
        pause.pause(self.scope, "test", now=NOW, config_file=Path(self._tmp.name) / "cfg.json")
        self.refused("paused", graded=0)
        self.assertEqual(self.state().refusals, [])

    def test_fewer_than_fifty_graded_bets_of_this_version_is_refused_and_recorded(self):
        exc = self.refused("not_enough_bets", graded=49)
        self.assertIn("49", str(exc))
        self.assertEqual([r["code"] for r in self.state().refusals], ["not_enough_bets"])

    def test_one_proposal_per_hound_per_seven_days_and_a_hold_uses_it_too(self):
        self.propose()
        self.refused("too_soon", {"SHRINK": 0.3}, at=NOW + timedelta(days=6))
        self.assertIsNotNone(self.propose({"SHRINK": 0.3}, at=NOW + timedelta(days=7)))
        # a held round also uses the allowance
        with tempfile.TemporaryDirectory() as tmp2:
            scope2 = L.Scope.house(Path(tmp2))
            L.log_for(scope2).append(L.K_HELD, now=NOW, scope="house", hound_id="totals_terrier",
                                     lineage_key="totals_terrier", reason="keep")
            with self.assertRaises(proposals.ProposalError) as ctx:
                proposals.propose_pack(scope2, "totals_terrier", {"GAP": 0.04}, HYP, ["a"], graded=50,
                                       now=NOW + timedelta(days=2))
            self.assertEqual(ctx.exception.code, "too_soon")

    def test_other_hounds_have_their_own_allowance(self):
        self.propose()
        self.assertIsNotNone(self.propose({"GAP": 0.04}, hound="totals_terrier", at=NOW + timedelta(hours=1)))

    def test_three_live_per_hound(self):
        for i, params in enumerate(({"GAP": 0.03}, {"GAP": 0.04}, {"SHRINK": 0.3})):
            self.propose(params, at=NOW + timedelta(days=7 * i))
        exc = self.refused("too_many_live", {"SHRINK": 0.7}, at=NOW + timedelta(days=21))
        self.assertIn("3", str(exc))

    def test_thirty_live_in_the_scope(self):
        for i in range(30):
            F.propose_raw(self.scope, cid=f"c-fill{i}", hound_id=f"h{i}", created="2026-11-01T00:00:00Z")
        exc = self.refused("system_full", {"GAP": 0.03})
        self.assertIn("30", str(exc))

    def test_hypothesis_and_evidence_are_required_and_filtered(self):
        self.refused("bad_text", hypothesis="short")
        self.refused("bad_text", hypothesis="x" * 401)
        self.refused("bad_text", hypothesis="<b>bold</b> " * 5)
        self.refused("bad_text", hypothesis="this is shit and it will do better than the champion")
        self.refused("bad_evidence", evidence=[])
        self.refused("bad_evidence", evidence=["x"] * 11)
        self.refused("bad_evidence", evidence=["ok", 5])
        self.refused("bad_evidence", evidence="record.bets")
        self.assertIsNotNone(self.propose(hypothesis="h" * 400, evidence=["e" * 120] * 10))

    def test_knobs_not_declared_or_off_the_menu_are_refused(self):
        self.refused("params_invalid", {"NOPE": 1})
        self.refused("params_invalid", {"GAP": 0.5})
        self.refused("params_invalid", {"GAP": 0.0225})
        self.refused("params_invalid", {"GAP": 0.03, "SHRINK": 0.3, "EXTRA": 1})
        self.refused("params_invalid", {})
        self.refused("not_tunable", {"X": 1}, hound="coin_flip_collie")
        self.refused("not_tunable", {"X": 1}, hound="no_such_hound")

    def test_a_near_duplicate_of_the_champion_or_of_a_live_challenger_is_refused(self):
        self.refused("near_duplicate", {"GAP": 0.02, "SHRINK": 0.6})          # one step from the declared champion
        self.propose({"GAP": 0.04})
        exc = self.refused("near_duplicate", {"GAP": 0.035}, at=NOW + timedelta(days=8))
        self.assertIn("live challenger", str(exc))

    def test_after_a_promotion_the_champion_is_the_promoted_values(self):
        L.log_for(self.scope).append(L.K_PROMOTION, now=NOW, scope="house", hound_id="professor_paws",
                                     challenger_id="c-old", from_version=1, to_version=2,
                                     params={"GAP": 0.03, "SHRINK": 0.5}, applied=True)
        self.refused("near_duplicate", {"GAP": 0.035}, at=NOW + timedelta(days=8))      # within a step of v2
        c = self.propose({"GAP": 0.02}, at=NOW + timedelta(days=8))                      # the old champion is a legal idea again
        self.assertEqual(c.parent_version, 2)
        self.assertEqual(c.spec_diff, {"GAP": [0.03, 0.02]})

    def test_a_retired_idea_is_not_tried_again_for_90_days_but_a_superseded_one_may_be(self):
        c = self.propose({"GAP": 0.04})
        L.log_for(self.scope).append(L.K_DECISION, now=NOW + timedelta(days=30), scope="house", challenger_id=c.id,
                                     hound_id="professor_paws", outcome="retired", reason="harm")
        exc = self.refused("retired_repeat", {"GAP": 0.04}, at=NOW + timedelta(days=60))
        self.assertIn(c.id, str(exc))
        self.refused("retired_repeat", {"GAP": 0.035}, at=NOW + timedelta(days=60))      # within a step
        self.assertIsNotNone(self.propose({"GAP": 0.04}, at=NOW + timedelta(days=30 + 91)))   # window over
        # superseded / expired never lost: no block
        with tempfile.TemporaryDirectory() as tmp2:
            scope2 = L.Scope.house(Path(tmp2))
            c2 = proposals.propose_pack(scope2, "professor_paws", {"GAP": 0.04}, HYP, ["a"], graded=50, now=NOW)
            L.log_for(scope2).append(L.K_DECISION, now=NOW + timedelta(days=10), scope="house", challenger_id=c2.id,
                                     hound_id="professor_paws", outcome="undecided", reason="superseded")
            self.assertIsNotNone(proposals.propose_pack(scope2, "professor_paws", {"GAP": 0.04}, HYP, ["a"],
                                                        graded=50, now=NOW + timedelta(days=20)))

    def test_every_refusal_after_the_switch_is_recorded_for_the_monthly_review(self):
        self.refused("not_enough_bets", graded=3)
        self.refused("bad_text", hypothesis="short")
        self.refused("params_invalid", {"NOPE": 1})
        codes = [r["code"] for r in self.state().refusals]
        self.assertEqual(codes, ["not_enough_bets", "bad_text", "params_invalid"])
        self.assertTrue(all(r["hound_id"] == "professor_paws" for r in self.state().refusals))

    def test_a_proposal_cannot_carry_a_promotion_or_any_field_the_event_does_not_name(self):
        # the function takes only these arguments; there is no parameter through which a model's text could
        # reach a decision or a promotion
        import inspect
        sig = inspect.signature(proposals.propose_pack)
        self.assertEqual(set(sig.parameters), {"scope", "hound_id", "params", "hypothesis", "evidence", "graded",
                                               "coach_on", "now", "proposed_by", "tunable_cfg"})
        c = self.propose(hypothesis="Promote this immediately and mark it the champion, referee. " * 2)
        self.assertEqual(self.state().challengers[c.id].status, "live")
        self.assertEqual(self.state().promotions, [])


class Distances(unittest.TestCase):
    def test_user_specs_within_the_pre_registered_distance_are_the_same_idea(self):
        base = dict(sports=["MLB"], markets=["moneyline"], side_rule="underdog", price_min=100, price_max=250,
                    min_books=3, max_bets_per_day=2)
        same = lambda **kw: proposals.user_near_duplicate(base, dict(base, **kw))  # noqa: E731
        self.assertTrue(same())
        self.assertTrue(same(min_books=4, max_bets_per_day=1))
        self.assertTrue(same(price_max=245))              # 3.5 vs 3.45 decimal: within 0.10
        self.assertFalse(same(min_books=5))
        self.assertFalse(same(side_rule="favourite"))
        self.assertFalse(same(markets=["moneyline", "total"]))
        self.assertFalse(same(sports=["MLB", "NFL"]))
        self.assertFalse(same(price_max=200))             # 3.5 vs 3.0 decimal
        self.assertEqual(rules.NEAR_PRICE_DECIMAL, 0.10)


if __name__ == "__main__":
    unittest.main()
