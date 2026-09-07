"""Tests for src.analysis.priceverdict (Task B1) and its wiring into
src.analysis.betcheck.build_contract.

Covers: every word boundary (both sides of each threshold), the LOW-tier
caps, INSUFFICIENT DATA for a missing consensus and for a sub-floor book
count, the fair-price conversion, the evidence-tier boundaries, the
vocabulary tripwires against every generated reason/risk string, and a
build_contract integration check that price_verdict actually lands on the
contract with a 6-book fixture board.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.analysis import betcheck
from src.analysis import contracts as c
from src.analysis import priceverdict as pv
from src.core import odds as odds_math
from src.detect import base

from tests.test_customer_language import (
    HARD_BANNED, NEGATION_ONLY, NEGATORS, BANNED_FIELD_NAME_PARTS,
)

NOW = datetime(2026, 8, 31, 18, 30, 0, tzinfo=timezone.utc)


def _assert_clean(testcase, text, where=""):
    for pattern, label in HARD_BANNED:
        testcase.assertNotRegex(
            text, pattern, f"{where}: hard-banned {label!r} in {text!r}")
    import re
    for pattern, label in NEGATION_ONLY:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            window = text[max(0, m.start() - 90):m.start()]
            testcase.assertTrue(
                NEGATORS.search(window),
                f"{where}: {label!r} affirmed with no negation in "
                f"{text!r}")


# ---------------------------------------------------------------------------
# Fixed vocabulary
# ---------------------------------------------------------------------------

class WordsAndTiers(unittest.TestCase):
    def test_words_exact(self):
        self.assertEqual(pv.WORDS, (
            "STRONG VALUE", "VALUE", "LEAN", "FAIR PRICE", "PASS",
            "OVERPRICED", "FADE ALERT", "INSUFFICIENT DATA"))

    def test_tiers_exact(self):
        self.assertEqual(pv.TIERS, ("HIGH", "MEDIUM", "LOW"))


# ---------------------------------------------------------------------------
# value_points
# ---------------------------------------------------------------------------

class ValuePoints(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(pv.value_points(0.55, 0.50), 5.0)
        self.assertEqual(pv.value_points(0.50, 0.55), -5.0)

    def test_none_propagates(self):
        self.assertIsNone(pv.value_points(None, 0.5))
        self.assertIsNone(pv.value_points(0.5, None))
        self.assertIsNone(pv.value_points(None, None))

    def test_rounded_to_two_places(self):
        self.assertEqual(pv.value_points(0.5231, 0.5), 2.31)


# ---------------------------------------------------------------------------
# verdict_word -- every threshold, both sides
# ---------------------------------------------------------------------------

class VerdictWordBoundaries(unittest.TestCase):
    def test_strong_value_boundary(self):
        self.assertEqual(pv.verdict_word(3.0, "HIGH"), "STRONG VALUE")
        self.assertEqual(pv.verdict_word(2.99, "HIGH"), "VALUE")

    def test_value_boundary(self):
        self.assertEqual(pv.verdict_word(1.5, "HIGH"), "VALUE")
        self.assertEqual(pv.verdict_word(1.49, "HIGH"), "LEAN")

    def test_lean_boundary(self):
        self.assertEqual(pv.verdict_word(0.5, "HIGH"), "LEAN")
        self.assertEqual(pv.verdict_word(0.49, "HIGH"), "FAIR PRICE")

    def test_fair_price_boundary(self):
        self.assertEqual(pv.verdict_word(-1.0, "HIGH"), "FAIR PRICE")
        self.assertEqual(pv.verdict_word(-1.01, "HIGH"), "PASS")

    def test_pass_boundary(self):
        self.assertEqual(pv.verdict_word(-2.5, "HIGH"), "PASS")
        self.assertEqual(pv.verdict_word(-2.51, "HIGH"), "OVERPRICED")

    def test_overpriced_boundary(self):
        self.assertEqual(pv.verdict_word(-4.5, "HIGH"), "OVERPRICED")
        self.assertEqual(pv.verdict_word(-4.51, "HIGH"), "FADE ALERT")

    def test_none_is_insufficient_data(self):
        self.assertEqual(pv.verdict_word(None, None), "INSUFFICIENT DATA")
        self.assertEqual(pv.verdict_word(None, "HIGH"), "INSUFFICIENT DATA")


class LowTierCap(unittest.TestCase):
    def test_strong_value_capped_to_value(self):
        self.assertEqual(pv.verdict_word(5.0, "LOW"), "VALUE")

    def test_fade_alert_capped_to_overpriced(self):
        self.assertEqual(pv.verdict_word(-9.0, "LOW"), "OVERPRICED")

    def test_middle_words_unaffected_by_low(self):
        for vp, expected in ((2.0, "VALUE"), (1.0, "LEAN"),
                             (0.0, "FAIR PRICE"), (-2.0, "PASS")):
            self.assertEqual(pv.verdict_word(vp, "LOW"), expected)

    def test_high_and_medium_tier_uncapped(self):
        self.assertEqual(pv.verdict_word(5.0, "HIGH"), "STRONG VALUE")
        self.assertEqual(pv.verdict_word(5.0, "MEDIUM"), "STRONG VALUE")
        self.assertEqual(pv.verdict_word(-9.0, "HIGH"), "FADE ALERT")


# ---------------------------------------------------------------------------
# evidence_tier -- boundaries on both books and age
# ---------------------------------------------------------------------------

class EvidenceTierBoundaries(unittest.TestCase):
    def test_high(self):
        self.assertEqual(pv.evidence_tier(9, 1800), "HIGH")

    def test_nine_books_but_stale_is_medium(self):
        self.assertEqual(pv.evidence_tier(9, 1801), "MEDIUM")

    def test_eight_books_fresh_is_medium_not_high(self):
        self.assertEqual(pv.evidence_tier(8, 1800), "MEDIUM")
        self.assertEqual(pv.evidence_tier(8, 1801), "MEDIUM")

    def test_six_books_at_medium_ceiling(self):
        self.assertEqual(pv.evidence_tier(6, 7200), "MEDIUM")

    def test_six_books_past_medium_ceiling_is_low(self):
        self.assertEqual(pv.evidence_tier(6, 7201), "LOW")

    def test_below_floor_is_none(self):
        self.assertIsNone(pv.evidence_tier(5, 100))
        self.assertIsNone(pv.evidence_tier(None, 100))

    def test_unknown_age_with_enough_books_is_low(self):
        self.assertEqual(pv.evidence_tier(9, None), "LOW")
        self.assertEqual(pv.evidence_tier(20, None), "LOW")


# ---------------------------------------------------------------------------
# fair_price -- probability_to_american's convention, via build_price_verdict
# ---------------------------------------------------------------------------

class FairPriceConversion(unittest.TestCase):
    def _fair(self, consensus_probability):
        result = pv.build_price_verdict(
            american_price=-110, consensus_probability=consensus_probability,
            books=9, observed_utc="2026-08-31T18:00:00+00:00", now=NOW)
        return result["fair_price"]

    def test_half_probability_is_even_money(self):
        self.assertEqual(self._fair(0.5), -100)
        self.assertEqual(round(odds_math.probability_to_american(0.5)), -100)

    def test_sixty_percent(self):
        self.assertEqual(self._fair(0.6), -150)
        self.assertEqual(round(odds_math.probability_to_american(0.6)), -150)


# ---------------------------------------------------------------------------
# build_price_verdict -- INSUFFICIENT DATA paths
# ---------------------------------------------------------------------------

class InsufficientData(unittest.TestCase):
    def test_no_consensus(self):
        result = pv.build_price_verdict(
            american_price=-110, consensus_probability=None, books=None,
            observed_utc=None, now=NOW)
        self.assertEqual(result["word"], "INSUFFICIENT DATA")
        self.assertIsNone(result["value_points"])
        self.assertIsNone(result["evidence_tier"])
        self.assertIsNone(result["fair_price"])

    def test_books_below_floor(self):
        result = pv.build_price_verdict(
            american_price=-110, consensus_probability=0.52, books=5,
            observed_utc="2026-08-31T18:00:00+00:00", now=NOW)
        self.assertEqual(result["word"], "INSUFFICIENT DATA")
        self.assertIsNone(result["value_points"])
        self.assertIsNone(result["evidence_tier"])

    def test_price_missing(self):
        result = pv.build_price_verdict(
            american_price=None, consensus_probability=0.52, books=9,
            observed_utc="2026-08-31T18:00:00+00:00", now=NOW)
        self.assertEqual(result["word"], "INSUFFICIENT DATA")
        self.assertIsNone(result["stated_implied_probability"])

    def test_every_key_always_present(self):
        expected_keys = {
            "word", "value_points", "fair_price",
            "stated_implied_probability", "market_implied_probability",
            "evidence_tier", "books", "observed_utc", "age_seconds",
            "independent_model", "market_reference_provenance", "reasons",
            "risks", "basis"}
        for kwargs in (
            dict(american_price=-110, consensus_probability=None,
                books=None, observed_utc=None),
            dict(american_price=-110, consensus_probability=0.52, books=9,
                observed_utc="2026-08-31T18:00:00+00:00"),
        ):
            result = pv.build_price_verdict(now=NOW, **kwargs)
            self.assertEqual(set(result), expected_keys)

    def test_independent_model_and_provenance_always_stated(self):
        for kwargs in (
            dict(american_price=-110, consensus_probability=None,
                books=None, observed_utc=None),
            dict(american_price=-110, consensus_probability=0.55, books=9,
                observed_utc="2026-08-31T18:00:00+00:00"),
        ):
            result = pv.build_price_verdict(now=NOW, **kwargs)
            self.assertEqual(result["independent_model"],
                             "NO INDEPENDENT MODEL YET")
            self.assertEqual(result["market_reference_provenance"],
                             "market_derived")
            self.assertEqual(result["basis"], pv.BASIS)


# ---------------------------------------------------------------------------
# Real numbers, sanity check on a full call
# ---------------------------------------------------------------------------

class FullVerdictSanity(unittest.TestCase):
    def test_good_price_high_tier(self):
        # -105 implies 51.22%; consensus 48.6% -> vp = (0.486-0.5122)*100
        result = pv.build_price_verdict(
            american_price=-105, consensus_probability=0.486, books=9,
            observed_utc="2026-08-31T18:16:00+00:00", now=NOW,
            best_price=-102, best_book="caesars")
        self.assertEqual(result["evidence_tier"], "HIGH")
        self.assertLess(result["value_points"], 0)
        self.assertEqual(result["word"], pv.verdict_word(
            result["value_points"], "HIGH"))
        self.assertTrue(any("caesars" in r for r in result["reasons"]))
        self.assertTrue(any("Board captured" in r for r in result["reasons"]))

    def test_thin_and_stale_board_is_low_and_capped(self):
        observed = "2026-08-31T14:00:00+00:00"   # 4.5 hours before NOW
        result = pv.build_price_verdict(
            american_price=-150, consensus_probability=0.70, books=6,
            observed_utc=observed, now=NOW)
        self.assertEqual(result["evidence_tier"], "LOW")
        self.assertTrue(any("old" in r for r in result["risks"]))
        self.assertTrue(any("6 books" in r for r in result["risks"]))


# ---------------------------------------------------------------------------
# Vocabulary tripwires -- every generated sentence, across many scenarios
# ---------------------------------------------------------------------------

class VocabularyTripwires(unittest.TestCase):
    SCENARIOS = [
        dict(american_price=-105, consensus_probability=0.486, books=9,
             observed_utc="2026-08-31T18:16:00+00:00",
             best_price=-102, best_book="caesars"),
        dict(american_price=-150, consensus_probability=0.70, books=6,
             observed_utc="2026-08-31T14:00:00+00:00"),
        dict(american_price=120, consensus_probability=0.40, books=12,
             observed_utc="2026-08-31T18:29:00+00:00",
             best_price=130, best_book="fanduel"),
        dict(american_price=-110, consensus_probability=None, books=None,
             observed_utc=None),
        dict(american_price=-110, consensus_probability=0.5, books=4,
             observed_utc="2026-08-31T18:00:00+00:00"),
        dict(american_price=None, consensus_probability=0.5, books=9,
             observed_utc="2026-08-31T18:00:00+00:00"),
    ]

    def test_no_banned_tokens_in_reasons_risks_or_basis(self):
        for kwargs in self.SCENARIOS:
            result = pv.build_price_verdict(now=NOW, **kwargs)
            for sentence in list(result["reasons"]) + list(result["risks"]) \
                    + [result["basis"]]:
                _assert_clean(self, sentence, where=repr(kwargs))

    def test_verdict_words_are_the_allowed_set(self):
        for kwargs in self.SCENARIOS:
            result = pv.build_price_verdict(now=NOW, **kwargs)
            self.assertIn(result["word"], pv.WORDS)

    def test_no_banned_field_name_parts_on_price_verdict(self):
        import dataclasses
        for f in dataclasses.fields(c.PriceVerdict):
            tokens = f.name.lower().split("_")
            for part in BANNED_FIELD_NAME_PARTS:
                part_tokens = part.split("_")
                n = len(part_tokens)
                self.assertFalse(
                    any(tokens[i:i + n] == part_tokens
                        for i in range(len(tokens))),
                    f"PriceVerdict.{f.name} contains banned part {part!r}")


# ---------------------------------------------------------------------------
# contracts.PriceVerdict -- validation
# ---------------------------------------------------------------------------

def _pv_kwargs(**overrides):
    base_kwargs = dict(
        word="VALUE", value_points=2.0, fair_price=-120,
        stated_implied_probability=0.52, market_implied_probability=0.54,
        evidence_tier="HIGH", books=9,
        observed_utc="2026-08-31T18:00:00+00:00", age_seconds=300,
        independent_model="NO INDEPENDENT MODEL YET",
        market_reference_provenance="market_derived", reasons=(),
        risks=(), basis=pv.BASIS)
    base_kwargs.update(overrides)
    return base_kwargs


class PriceVerdictContract(unittest.TestCase):
    def test_valid_construction(self):
        obj = c.PriceVerdict(**_pv_kwargs())
        self.assertEqual(obj.word, "VALUE")

    def test_rejects_unknown_word(self):
        with self.assertRaises(ValueError):
            c.PriceVerdict(**_pv_kwargs(word="SURE THING"))

    def test_rejects_unknown_tier(self):
        with self.assertRaises(ValueError):
            c.PriceVerdict(**_pv_kwargs(evidence_tier="MEDIUM-ISH"))

    def test_none_tier_allowed(self):
        obj = c.PriceVerdict(**_pv_kwargs(
            word="INSUFFICIENT DATA", evidence_tier=None, value_points=None,
            fair_price=None))
        self.assertIsNone(obj.evidence_tier)

    def test_to_json_round_trips(self):
        import json
        obj = c.PriceVerdict(**_pv_kwargs())
        payload = json.loads(obj.to_json())
        self.assertEqual(payload["word"], "VALUE")
        self.assertEqual(payload["basis"], pv.BASIS)


# ---------------------------------------------------------------------------
# build_contract integration -- price_verdict lands on the real contract
# ---------------------------------------------------------------------------

def finding(detector="d", claim="a claim", side=base.HOME, kind=base.SIGNAL,
           evidence=base.TESTED_NULL, sample="250 BF vs L, 300 vs R",
           surprise=2.0, value=0.09, baseline=0.0):
    return base.Finding(detector, kind, claim, value=value, baseline=baseline,
                        sample=sample, surprise=surprise, side=side,
                        evidence=evidence)


def board6(away_price=-110, home_price=-130,
          observed_utc="2026-08-31T18:00:00+00:00"):
    """A 6-book board -- exactly at prices.MIN_BOOKS, with a capture
    instant, matching test_betcheck_logic.py's fixture style."""
    return {"quotes": [{"book": f"book_{i}", "away_price": away_price,
                        "home_price": home_price} for i in range(6)],
           "observed_utc": observed_utc}


class BuildContractIntegration(unittest.TestCase):
    def test_price_verdict_present_on_contract(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, board=board6(),
            findings=[])
        self.assertIsInstance(result.price_verdict, c.PriceVerdict)
        self.assertIn(result.price_verdict.word, pv.WORDS)
        self.assertEqual(result.price_verdict.books, 6)
        self.assertEqual(result.price_verdict.independent_model,
                         "NO INDEPENDENT MODEL YET")

    def test_price_verdict_insufficient_data_without_a_board(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertEqual(result.price_verdict.word, "INSUFFICIENT DATA")
        self.assertIsNone(result.price_verdict.value_points)
        self.assertIsNone(result.price_verdict.evidence_tier)
        self.assertTrue(result.price_verdict.reasons)

    def test_price_verdict_folds_in_thesis_and_counterargument_text(self):
        findings = [
            finding(detector="a", claim="home bullpen has been reliable",
                    side=base.HOME),
            finding(detector="b", claim="away rotation is well-rested",
                    side=base.AWAY),
        ]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, board=board6(),
            findings=findings)
        self.assertIn("home bullpen has been reliable",
                      result.price_verdict.reasons)
        self.assertIn("away rotation is well-rested",
                      result.price_verdict.risks)

    def test_serialised_contract_carries_price_verdict(self):
        import json
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, board=board6(),
            findings=[])
        payload = json.loads(result.to_json())
        self.assertIn("price_verdict", payload)
        self.assertIn("word", payload["price_verdict"])
        self.assertIn(payload["price_verdict"]["word"], pv.WORDS)


if __name__ == "__main__":
    unittest.main()
