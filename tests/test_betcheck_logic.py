"""Tests for src.analysis.betcheck.build_contract -- the structured, paid-
beta path that turns (date, away_club, home_club, side, american_price)
plus a board and a findings list into a BetCheckContract.

stdlib only, no fastapi import: this is the engine step, exercised directly
against the domain objects (src.detect.base.Finding) rather than through
the HTTP layer -- api/betcheck.py and tests/test_api_betcheck.py cover the
network-facing wiring on top of this.
"""

from __future__ import annotations

import unittest

from src.analysis import betcheck
from src.analysis import contracts as c
from src.detect import base


def finding(detector="d", claim="a claim", side=base.HOME, kind=base.SIGNAL,
           evidence=base.TESTED_NULL, sample="250 BF vs L, 300 vs R",
           surprise=2.0, value=0.09, baseline=0.0):
    return base.Finding(detector, kind, claim, value=value, baseline=baseline,
                        sample=sample, surprise=surprise, side=side,
                        evidence=evidence)


def board(rows=9, away_price=-110, home_price=-110,
         observed_utc="2026-08-31T18:00:00+00:00"):
    """A board with enough books to clear prices.MIN_BOOKS, with a capture
    instant -- the shape dossier.get("multibook_board") actually carries."""
    return {"quotes": [{"book": f"book_{i}", "away_price": away_price,
                        "home_price": home_price} for i in range(rows)],
           "observed_utc": observed_utc}


# ---------------------------------------------------------------------------
# Shape and identity
# ---------------------------------------------------------------------------

class ShapeTests(unittest.TestCase):
    def test_returns_a_bet_check_contract(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertIsInstance(result, c.BetCheckContract)

    def test_recommendation_is_always_none(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertIsNone(result.recommendation)

    def test_side_must_be_away_or_home(self):
        with self.assertRaises(ValueError):
            betcheck.build_contract("2026-08-31", "BOS", "NYY", "sideways",
                                    -125, findings=[])

    def test_unknown_club_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            betcheck.build_contract("2026-08-31", "ZZZ", "NYY", "home", -125,
                                    findings=[])

    def test_your_bet_is_echoed_in_the_query(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertTrue(result.query.parsed)
        self.assertEqual(result.query.team, "NYY")
        self.assertEqual(result.query.side, "home")
        self.assertEqual(result.query.price, -125)
        self.assertEqual(result.query.market, "h2h")

    def test_aliased_club_resolves_canonically(self):
        # ATH is the schedule's spelling; the canonical park/board key is OAK.
        result = betcheck.build_contract(
            "2026-08-31", "ATH", "NYY", "away", 105, findings=[])
        self.assertEqual(result.game.away, "OAK")
        self.assertEqual(result.query.team, "OAK")

    def test_game_ref_carries_the_stated_identity(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertEqual(result.game.away, "BOS")
        self.assertEqual(result.game.home, "NYY")
        self.assertEqual(result.game.date, "2026-08-31")
        self.assertIn("BOS", result.game.game_id)
        self.assertIn("NYY", result.game.game_id)


# ---------------------------------------------------------------------------
# The counterargument is structurally mandatory -- present even when empty.
# ---------------------------------------------------------------------------

class CounterargumentTests(unittest.TestCase):
    def test_no_findings_at_all_still_carries_the_mandated_empty_text(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertEqual(result.counterargument, ())
        self.assertEqual(result.counterargument_lines,
                        (c.NO_COUNTERARGUMENTS_TEXT,))

    def test_only_supporting_findings_still_carries_the_empty_text(self):
        findings = [finding(detector="a", claim="for the home side",
                            side=base.HOME)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertEqual(len(result.thesis_support), 1)
        self.assertEqual(result.counterargument_lines,
                        (c.NO_COUNTERARGUMENTS_TEXT,))

    def test_opposing_findings_populate_the_counterargument(self):
        findings = [finding(detector="a", claim="against the home side",
                            side=base.AWAY)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertEqual(result.counterargument_lines,
                        ("against the home side",))

    def test_counterargument_json_key_always_present(self):
        import json
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        payload = json.loads(result.to_json())
        self.assertIn("counterargument", payload)
        self.assertIn("counterargument_lines", payload)


# ---------------------------------------------------------------------------
# For/against partition, mirroring check()'s rules
# ---------------------------------------------------------------------------

class PartitionTests(unittest.TestCase):
    def test_supporting_and_opposing_split_by_side(self):
        findings = [
            finding(detector="a", claim="for the home side", side=base.HOME),
            finding(detector="b", claim="against the home side", side=base.AWAY),
        ]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertEqual(len(result.thesis_support), 1)
        self.assertEqual(result.thesis_support[0].statement, "for the home side")
        self.assertEqual(len(result.counterargument), 1)
        self.assertEqual(result.counterargument[0].statement,
                        "against the home side")

    def test_neither_side_findings_excluded_from_both(self):
        findings = [finding(detector="c", claim="about neither team",
                            side=base.NEITHER)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertEqual(result.thesis_support, ())
        self.assertEqual(result.counterargument, ())

    def test_context_findings_never_enter_the_partition(self):
        findings = [finding(detector="d", claim="context on the home side",
                            side=base.HOME, kind=base.CONTEXT, surprise=None,
                            value=None)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertEqual(result.thesis_support, ())
        self.assertEqual(result.counterargument, ())

    def test_away_side_bet_partitions_against_away(self):
        findings = [
            finding(detector="a", claim="for away", side=base.AWAY),
            finding(detector="b", claim="for home", side=base.HOME),
        ]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "away", 130, findings=findings)
        self.assertEqual(result.thesis_support[0].statement, "for away")
        self.assertEqual(result.counterargument[0].statement, "for home")


# ---------------------------------------------------------------------------
# Rule S: sample lines, structurally paired with any numeric claim
# ---------------------------------------------------------------------------

class SampleLineTests(unittest.TestCase):
    def test_quantitative_claim_carries_its_sample_line(self):
        findings = [finding(detector="a", claim="platoon mismatch",
                            side=base.HOME, sample="8 hitters, 340 PA")]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        claim = result.thesis_support[0]
        self.assertTrue(claim.is_quantitative)
        self.assertEqual(claim.sample_n, 340)
        self.assertEqual(claim.sample_unit, "8 hitters, 340 PA")

    def test_finding_with_no_sample_is_never_quantitative(self):
        findings = [finding(detector="a", claim="a hunch", side=base.HOME,
                            sample=None)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        claim = result.thesis_support[0]
        self.assertFalse(claim.is_quantitative)
        self.assertIsNone(claim.value)

    def test_finding_with_unparseable_sample_is_never_quantitative(self):
        # "since SF, 3 day(s) ago" names an elapsed period, not a count --
        # synthesis.sample_size returns None for it. Rule S must then
        # refuse the numeric value rather than let it through unpaired.
        findings = [finding(detector="a", claim="a stale claim",
                            side=base.HOME,
                            sample="since SF, 3 day(s) ago")]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        claim = result.thesis_support[0]
        self.assertFalse(claim.is_quantitative)
        self.assertIsNone(claim.value)

    def test_evidence_label_is_the_internal_vocabulary(self):
        findings = [finding(detector="a", claim="one", side=base.HOME,
                            evidence=base.TESTED_NULL)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertEqual(result.thesis_support[0].evidence_label,
                        base.TESTED_NULL)


# ---------------------------------------------------------------------------
# Market: best price, consensus-as-a-price, and the explicit unavailable
# state -- never a default.
# ---------------------------------------------------------------------------

class MarketTests(unittest.TestCase):
    def test_missing_board_is_explicit_unavailable_not_a_default(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertIsNone(result.best_available_price)
        self.assertIsNone(result.market_consensus)
        self.assertIsNone(result.your_price_beats_consensus)
        self.assertIsNone(result.price_improvement)
        self.assertIn("unavailable", result.bottom_line.lower())

    def test_thin_board_is_explicit_unavailable(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125,
            board=board(rows=3), findings=[])
        self.assertIsNone(result.best_available_price)
        self.assertIsNone(result.market_consensus)

    def test_board_without_capture_instant_is_explicit_unavailable(self):
        raw_quotes = board()["quotes"]   # a bare list -- no observed_utc
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125,
            board=raw_quotes, findings=[])
        self.assertIsNone(result.best_available_price)
        self.assertIsNone(result.market_consensus)

    def test_full_board_populates_best_price_and_consensus_as_a_price(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125,
            board=board(), findings=[])
        self.assertIsInstance(result.best_available_price, c.QuotedPrice)
        self.assertIsInstance(result.market_consensus, c.MarketImpliedConsensus)
        self.assertEqual(result.market_consensus.books, 9)
        self.assertIsInstance(result.price_improvement, c.PriceImprovement)

    def test_better_stated_price_beats_consensus(self):
        # -110/-110 consensus pays ~1.909 decimal; a stated +150 on the
        # home side pays a higher decimal -- a better price.
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", 150,
            board=board(), findings=[])
        self.assertTrue(result.your_price_beats_consensus)

    def test_worse_stated_price_does_not_beat_consensus(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -500,
            board=board(), findings=[])
        self.assertFalse(result.your_price_beats_consensus)


# ---------------------------------------------------------------------------
# Evidence status, historical support, and the bottom line
# ---------------------------------------------------------------------------

class RollupTests(unittest.TestCase):
    def test_evidence_status_none_with_no_claims(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertIsNone(result.evidence_status)
        self.assertIsNone(result.historical_support)

    def test_evidence_status_is_a_customer_ladder_label(self):
        findings = [finding(detector="a", claim="one", side=base.HOME,
                            evidence=base.TESTED_NULL)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        allowed = {ce.label for ce in c._CUSTOMER_EVIDENCE.values()}
        self.assertIn(result.evidence_status, allowed)

    def test_historical_support_is_one_of_three_words(self):
        findings = [finding(detector="a", claim="one", side=base.HOME,
                            evidence=base.PROVEN)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertIn(result.historical_support,
                     ("Weak", "Moderate", "Strong"))

    def test_bottom_line_states_no_findings_case(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertIn("does not distinguish", result.bottom_line)

    def test_bottom_line_always_states_no_predictive_edge(self):
        for findings in ([], [finding(side=base.HOME)], [finding(side=base.AWAY)]):
            result = betcheck.build_contract(
                "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
            self.assertIn("No predictive edge is claimed", result.bottom_line)

    def test_strongest_and_weakest_reason_pick_the_top_surprise(self):
        findings = [
            finding(detector="a", claim="weak support", side=base.HOME,
                   surprise=0.5),
            finding(detector="b", claim="strong support", side=base.HOME,
                   surprise=3.0),
            finding(detector="c", claim="strong opposition", side=base.AWAY,
                   surprise=2.5),
        ]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertEqual(result.strongest_reason, "strong support")
        self.assertEqual(result.weakest_reason, "strong opposition")

    def test_unscored_findings_never_become_the_strongest_reason(self):
        findings = [finding(detector="a", claim="unscored", side=base.HOME,
                           surprise=None, value=None, sample=None)]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=findings)
        self.assertIsNone(result.strongest_reason)


# ---------------------------------------------------------------------------
# What changed
# ---------------------------------------------------------------------------

class WhatChangedTests(unittest.TestCase):
    def test_events_with_a_headline_are_carried_through(self):
        events = [{"headline": "starter scratched", "tier": "HIGH",
                  "seen_utc": "2026-08-31T12:00:00+00:00"}]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[],
            what_changed=events)
        self.assertEqual(len(result.what_changed), 1)
        self.assertEqual(result.what_changed[0].headline, "starter scratched")
        self.assertEqual(result.what_changed[0].tier, "HIGH")

    def test_a_headline_less_event_is_dropped_not_fabricated(self):
        events = [{"tier": "HIGH"}]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[],
            what_changed=events)
        self.assertEqual(result.what_changed, ())

    def test_unknown_tier_becomes_the_stated_unknown_not_a_guess(self):
        events = [{"headline": "something happened", "tier": "not-a-tier"}]
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[],
            what_changed=events)
        self.assertEqual(result.what_changed[0].tier, "UNKNOWN")

    def test_no_what_changed_argument_is_an_empty_tuple(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, findings=[])
        self.assertEqual(result.what_changed, ())


# ---------------------------------------------------------------------------
# No model win probability anywhere, and price improvement never called EV.
# ---------------------------------------------------------------------------

class VocabularyTests(unittest.TestCase):
    def test_no_win_probability_field_in_the_serialised_contract(self):
        import json
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125,
            board=board(), findings=[])
        blob = json.dumps(json.loads(result.to_json())).lower()
        for forbidden in ("win_probability", "win_prob", "true_probability"):
            self.assertNotIn(forbidden, blob)

    def test_price_improvement_never_called_ev_or_edge_unqualified(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -500,
            board=board(), findings=[])
        blob = result.price_improvement.to_json().lower()
        for forbidden in ("\"ev\"", "expected_value", "edge", "roi"):
            self.assertNotIn(forbidden, blob)

    def test_market_context_worse_price_never_called_ev_in_bottom_line(self):
        result = betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -500,
            board=board(), findings=[])
        self.assertNotIn("edge", result.bottom_line.replace(
            "No predictive edge is claimed here", ""))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def test_build_contract_is_deterministic(self):
        findings = [
            finding(detector="a", claim="one", side=base.HOME),
            finding(detector="b", claim="two", side=base.AWAY),
        ]
        results = [betcheck.build_contract(
            "2026-08-31", "BOS", "NYY", "home", -125, board=board(),
            findings=list(findings)) for _ in range(5)]
        blobs = [r.to_json() for r in results]
        self.assertTrue(all(b == blobs[0] for b in blobs))


if __name__ == "__main__":
    unittest.main()
