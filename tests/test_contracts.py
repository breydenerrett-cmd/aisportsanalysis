"""Pins for the customer product contracts (src/analysis/contracts.py).

What is pinned here is product, not implementation detail:
- a quantitative claim without its sample size and evidence label is REFUSED;
- the Bet Check counterargument is structurally mandatory;
- the evidence translation covers every internal label exactly once;
- quoted price / market-implied consensus / price improvement are distinct,
  non-interchangeable types, and no win-probability field exists;
- serialisation is deterministic.
"""

import dataclasses
import json
import unittest

from src.analysis import contracts as c
from src.analysis import synthesis
from src.detect import base as detect

NOW = "2026-08-31T18:00:00+00:00"


def quote(book="fanduel", price=-118):
    return c.QuotedPrice(book=book, american_price=price, observed_utc=NOW)


def consensus(p=0.5321, books=11):
    return c.MarketImpliedConsensus(implied_probability=p, books=books,
                                    observed_utc=NOW)


def claim(**kw):
    base = dict(statement="Their starter has been above league average.",
                evidence_label=detect.UNPROVEN)
    base.update(kw)
    return c.Claim(**base)


def ref():
    return c.GameRef(game_id="game-SD-TB-2026-08-31", away="SD", home="TB",
                     date="2026-08-31")


def betcheck(**kw):
    base = dict(
        query=c.BetQuery(raw="Yankees ML -125", parsed=True, team="NYY",
                         side="home", market="h2h", price=-125),
        game=ref(),
        thesis_support=(claim(),),
        counterargument=(),
        best_available_price=quote(),
        market_consensus=consensus(),
        your_price_beats_consensus=True,
        what_changed=(),
    )
    base.update(kw)
    return c.BetCheckContract(**base)


class ClaimRefusal(unittest.TestCase):
    def test_quantitative_without_sample_refused(self):
        with self.assertRaises(ValueError):
            claim(value=0.371)

    def test_quantitative_without_sample_unit_refused(self):
        with self.assertRaises(ValueError):
            claim(value=0.371, sample_n=340)

    def test_quantitative_with_zero_sample_refused(self):
        with self.assertRaises(ValueError):
            claim(value=0.371, sample_n=0, sample_unit="plate appearances")

    def test_quantitative_with_sample_and_evidence_accepted(self):
        k = claim(value=0.371, sample_n=340, sample_unit="plate appearances")
        self.assertTrue(k.is_quantitative)

    def test_unknown_evidence_label_refused(self):
        with self.assertRaises(ValueError):
            claim(evidence_label="explored")   # merged vocab regression

    def test_qualitative_claim_needs_no_sample(self):
        self.assertFalse(claim().is_quantitative)

    def test_empty_statement_refused(self):
        with self.assertRaises(ValueError):
            claim(statement="")


class EvidenceTranslation(unittest.TestCase):
    def test_covers_every_internal_label_exactly_once(self):
        internal = set(synthesis.EVIDENCE_LABELS)
        mapped = set(c._CUSTOMER_EVIDENCE)
        self.assertEqual(internal, mapped)
        for status in internal:
            ce = c.customer_evidence(status)
            self.assertEqual(ce.internal, status)

    def test_unmapped_state_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            c.customer_evidence("no_play")     # a verdict, not evidence
        with self.assertRaises(ValueError):
            c.customer_evidence("HIGH")        # a relevance tier

    def test_ordinary_observations_get_no_badge(self):
        # The 153-UNPROVEN-badge failure: observed and unproven are the
        # bulk of today's output and must render without a badge.
        self.assertFalse(c.customer_evidence(synthesis.OBSERVED).show_badge)
        self.assertFalse(c.customer_evidence(detect.UNPROVEN).show_badge)

    def test_negative_evidence_stays_visible(self):
        ce = c.customer_evidence(detect.TESTED_NULL)
        self.assertTrue(ce.show_badge)
        self.assertNotEqual(ce.label, "Observation")

    def test_ladder_top_reserved(self):
        self.assertEqual(c.customer_evidence(detect.PROVEN).tier, 5)
        self.assertEqual(
            c.customer_evidence(detect.FORWARD_TESTING).tier, 4)

    def test_no_internal_vocabulary_leaks(self):
        for ce in c._CUSTOMER_EVIDENCE.values():
            self.assertNotIn("unproven", ce.label.lower())
            self.assertNotIn("_", ce.label)


class MarketSemantics(unittest.TestCase):
    def test_types_are_distinct_shapes(self):
        q_fields = {f.name for f in dataclasses.fields(c.QuotedPrice)}
        m_fields = {f.name for f in
                    dataclasses.fields(c.MarketImpliedConsensus)}
        self.assertNotEqual(q_fields, m_fields)
        self.assertNotIn("implied_probability", q_fields)
        self.assertNotIn("american_price", m_fields)

    def test_improvement_refuses_swapped_arguments(self):
        with self.assertRaises(TypeError):
            c.PriceImprovement(best=consensus(), consensus=quote(),
                               improvement_points=0.01,
                               improvement_return_pct=1.2)

    def test_improvement_label_mandatory(self):
        with self.assertRaises(ValueError):
            c.PriceImprovement(best=quote(), consensus=consensus(),
                               improvement_points=0.01,
                               improvement_return_pct=1.2, label="")

    def test_consensus_below_book_floor_refused(self):
        with self.assertRaises(ValueError):
            consensus(books=3)

    def test_no_win_probability_field_anywhere(self):
        banned = ("win_probability", "win_prob", "p_win", "prob_win",
                  "model_probability", "true_probability")
        for cls in c.CONTRACTS + (c.Claim, c.QuotedPrice,
                                  c.MarketImpliedConsensus,
                                  c.PriceImprovement, c.OddsRow,
                                  c.ChangeItem, c.MarketBlock):
            for f in dataclasses.fields(cls):
                for b in banned:
                    self.assertNotIn(b, f.name.lower(), f"{cls}.{f.name}")

    def test_board_requires_capture_instant(self):
        with self.assertRaises(ValueError):
            c.OddsBoardContract(observed_utc="", rows=())


class BetCheckShape(unittest.TestCase):
    def test_counterargument_cannot_be_none(self):
        with self.assertRaises(TypeError):
            betcheck(counterargument=None)

    def test_empty_counterargument_renders_stated_text(self):
        bc = betcheck(counterargument=())
        self.assertEqual(bc.counterargument_lines,
                         (c.NO_COUNTERARGUMENTS_TEXT,))
        payload = json.loads(bc.to_json())
        self.assertEqual(payload["counterargument_lines"],
                         [c.NO_COUNTERARGUMENTS_TEXT])

    def test_counterargument_key_always_serialised(self):
        payload = json.loads(betcheck().to_json())
        self.assertIn("counterargument", payload)
        self.assertIn("counterargument_lines", payload)

    def test_recommendation_permanently_none(self):
        with self.assertRaises((ValueError, TypeError)):
            betcheck(recommendation="bet it")
        payload = json.loads(betcheck().to_json())
        self.assertIn("recommendation", payload)
        self.assertIsNone(payload["recommendation"])

    def test_evidence_status_only_customer_ladder(self):
        with self.assertRaises(ValueError):
            betcheck(evidence_status="unproven")   # internal vocab leak
        betcheck(evidence_status="Observation")    # customer vocab fine

    def test_unparsed_bet_needs_reason(self):
        with self.assertRaises(ValueError):
            c.BetQuery(raw="???", parsed=False)


class OtherContracts(unittest.TestCase):
    def test_quick_view_truncates_at_five(self):
        factors = tuple(c.Factor(supports=True, sentence=f"s{i}")
                        for i in range(6))
        with self.assertRaises(ValueError):
            c.GameQuickContract(ref=ref(), factors=factors,
                                best_available_price=None,
                                historical_evidence_note="none yet")

    def test_quick_view_both_sides_always_appear(self):
        gq = c.GameQuickContract(
            ref=ref(),
            factors=(c.Factor(supports=True, sentence="good starter"),),
            best_available_price=None,
            historical_evidence_note="none yet")
        self.assertEqual(gq.counterargument_lines,
                         (c.NO_COUNTERARGUMENTS_TEXT,))

    def test_change_item_tier_is_relevance_vocab_only(self):
        with self.assertRaises(ValueError):
            c.ChangeItem(seen_utc=NOW, category="lineup", headline="x",
                         tier="proven")   # evidence ladder is NOT a tier
        c.ChangeItem(seen_utc=NOW, category="lineup", headline="x",
                     tier="UNKNOWN")

    def test_what_changed_personalization_blocked_without_accounts(self):
        with self.assertRaises(ValueError):
            c.WhatChangedContract(since_label="since you last looked",
                                  events=(), personalized=True)

    def test_what_changed_empty_state_is_stated(self):
        wc = c.WhatChangedContract(since_label="since this morning",
                                   events=())
        payload = json.loads(wc.to_json())
        self.assertEqual(payload["empty_text"], c.EMPTY_WHAT_CHANGED_TEXT)

    def test_today_summary_mandatory(self):
        with self.assertRaises(ValueError):
            c.TodayContract(date="2026-08-31", slate_summary="", games=(),
                            what_changed=(), what_matters=(), best_prices=())


class CapabilityMetadata(unittest.TestCase):
    def test_every_field_carries_a_known_state(self):
        for cls in c.CONTRACTS:
            caps = c.field_capabilities(cls)
            for name, state in caps.items():
                self.assertIn(state, c.CAPABILITY_STATES, f"{cls}.{name}")

    def test_reconciliation_table_pins(self):
        bc = c.field_capabilities(c.BetCheckContract)
        self.assertEqual(bc["strongest_reason"], c.ENGINEERING_REQUIRED)
        self.assertEqual(bc["bottom_line"], c.ENGINEERING_REQUIRED)
        self.assertEqual(bc["best_available_price"], c.REAL_TODAY)
        adv = c.field_capabilities(c.GameAdvancedContract)
        self.assertEqual(adv["batted_ball"], c.RESEARCH_DEPENDENT)
        today = c.field_capabilities(c.TodayContract)
        self.assertEqual(today["data_support_meter"], c.ENGINEERING_REQUIRED)
        odds = c.field_capabilities(c.OddsBoardContract)
        self.assertEqual(odds["f5_vs_full_game"], c.ENGINEERING_REQUIRED)


class DeterministicSerialisation(unittest.TestCase):
    def test_repeatable_and_sorted(self):
        objs = [
            betcheck(),
            c.WhatChangedContract(since_label="since this morning",
                                  events=()),
            c.OddsBoardContract(observed_utc=NOW, rows=(
                c.OddsRow(game_id="g", market="Moneyline", best=quote(),
                          consensus=consensus(),
                          book_disagreement="books mostly agree"),)),
            c.TodayContract(date="2026-08-31",
                            slate_summary="15 games tonight.",
                            games=(ref(),), what_changed=(),
                            what_matters=(), best_prices=()),
            c.GameQuickContract(
                ref=ref(),
                factors=(c.Factor(supports=False, sentence="long travel"),),
                best_available_price=quote(),
                historical_evidence_note="no demonstrated betting edge yet"),
            c.GameAdvancedContract(ref=ref(), starting_pitchers=(),
                                   lineups=(), bullpen=(), market=None,
                                   context=(), evidence_method=()),
        ]
        for obj in objs:
            a, b = obj.to_json(), obj.to_json()
            self.assertEqual(a, b)
            payload = json.loads(a)
            self.assertEqual(list(payload), sorted(payload))


if __name__ == "__main__":
    unittest.main()
