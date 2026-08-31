"""Tests for src/analysis/betcheck.py.

Bet Check is the one surface where a user's own words become the input, so
the parser gets tested hardest for the thing it must never do: guess. Every
ambiguous case must refuse and name what was ambiguous. The checker gets
tested for the structural rule the architecture doc calls out -- a finding
without a sample and an evidence label cannot enter the object -- and for the
never-EV wording surviving all the way to the bottom line.
"""

import unittest

from src.analysis import betcheck
from src.detect import base
from src.detect import dossier as dossier_mod


def game_dossier(away="BOS", home="NYY", sections=None):
    d = dossier_mod.Dossier({"away_team": away, "home_team": home,
                             "date": "2026-08-28", "game_pk": 1,
                             "venue": "Yankee Stadium"})
    for name, data in (sections or {}).items():
        d.add(name, data)
    return d


def finding(detector="platoon_mismatch", claim="NYY's starter allows lots.",
           side=base.AWAY, kind=base.SIGNAL, evidence=base.TESTED_NULL,
           sample="250 BF vs L, 300 vs R", surprise=2.0, baseline=0.0):
    return base.Finding(detector, kind, claim, value=0.09, baseline=baseline,
                        sample=sample, surprise=surprise, side=side,
                        evidence=evidence)


def board(rows=9, away_price=-110, home_price=-110):
    """A board with enough books to clear prices.MIN_BOOKS."""
    return {"quotes": [{"book": f"book_{i}", "away_price": away_price,
                        "home_price": home_price} for i in range(rows)]}


# ---------------------------------------------------------------------------
# Parsing: success across variants
# ---------------------------------------------------------------------------

class ParseSuccessTests(unittest.TestCase):
    def test_nickname_ml_negative_price(self):
        result = betcheck.parse("Yankees ML -125")
        self.assertTrue(result["ok"])
        self.assertEqual(result["team"], "NYY")
        self.assertEqual(result["market"], "h2h")
        self.assertEqual(result["price"], -125)

    def test_abbreviation_moneyline_positive_price(self):
        result = betcheck.parse("BOS moneyline +140")
        self.assertTrue(result["ok"])
        self.assertEqual(result["team"], "BOS")
        self.assertEqual(result["price"], 140)

    def test_full_club_name_h2h(self):
        result = betcheck.parse("New York Yankees h2h -150")
        self.assertTrue(result["ok"])
        self.assertEqual(result["team"], "NYY")

    def test_aliased_abbreviation_resolves_canonically(self):
        # ATH is the schedule's spelling; the canonical park/board key is OAK.
        result = betcheck.parse("ATH ML +105")
        self.assertTrue(result["ok"])
        self.assertEqual(result["team"], "OAK")

    def test_money_line_two_words(self):
        result = betcheck.parse("Red Sox money line -110")
        self.assertTrue(result["ok"])
        self.assertEqual(result["team"], "BOS")

    def test_input_is_echoed_verbatim(self):
        result = betcheck.parse("Yankees ML -125")
        self.assertEqual(result["input"], "Yankees ML -125")


# ---------------------------------------------------------------------------
# Parsing: structured refusals, never a guess
# ---------------------------------------------------------------------------

class ParseRefusalTests(unittest.TestCase):
    def test_unsupported_market_named_explicitly(self):
        result = betcheck.parse("Yankees spread -125")
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "market")
        self.assertIn("spread", result["reason"])
        self.assertIn("not supported", result["reason"])

    def test_run_line_refused_by_name(self):
        result = betcheck.parse("Yankees run line -125")
        self.assertFalse(result["ok"])
        self.assertIn("run line", result["reason"])

    def test_first_five_refused_by_name(self):
        result = betcheck.parse("Yankees first five -110")
        self.assertFalse(result["ok"])
        self.assertIn("first five", result["reason"])

    def test_no_market_named(self):
        result = betcheck.parse("Yankees -125")
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "market")

    def test_no_price_found(self):
        result = betcheck.parse("Yankees ML")
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "price")

    def test_unsigned_number_is_not_taken_as_a_price(self):
        result = betcheck.parse("Yankees ML 125")
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "price")

    def test_no_team_named(self):
        result = betcheck.parse("ML -125")
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "team")

    def test_two_teams_named_is_ambiguous(self):
        result = betcheck.parse("Yankees Red Sox ML -125")
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "team")

    def test_multiple_prices_is_ambiguous(self):
        result = betcheck.parse("Yankees ML -125 or -130")
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "price")

    def test_empty_string_refused(self):
        result = betcheck.parse("")
        self.assertFalse(result["ok"])

    def test_non_string_refused_not_raised(self):
        result = betcheck.parse(None)
        self.assertFalse(result["ok"])


# ---------------------------------------------------------------------------
# check(): game matching
# ---------------------------------------------------------------------------

class GameMatchTests(unittest.TestCase):
    def test_bet_on_a_game_not_on_the_slate_is_refused_cleanly(self):
        # The dossier is BOS @ NYY; the bet names a third club entirely.
        result = betcheck.check("Dodgers ML -140", game_dossier())
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "team")
        self.assertIn("not on this game's slate", result["reason"])

    def test_matched_game_is_returned(self):
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=[])
        self.assertTrue(result["ok"])
        self.assertEqual(result["game"]["away_team"], "BOS")
        self.assertEqual(result["game"]["home_team"], "NYY")
        self.assertEqual(result["side"], base.HOME)

    def test_away_side_bet_resolves_to_away(self):
        result = betcheck.check("BOS ML +130", game_dossier(), findings=[])
        self.assertEqual(result["side"], base.AWAY)

    def test_a_parse_failure_passed_straight_through(self):
        result = betcheck.check("Dodgers spread -140", game_dossier())
        self.assertFalse(result["ok"])
        self.assertEqual(result["ambiguous"], "market")

    def test_already_parsed_bet_is_accepted_directly(self):
        parsed = betcheck.parse("Yankees ML -125")
        result = betcheck.check(parsed, game_dossier(), findings=[])
        self.assertTrue(result["ok"])


# ---------------------------------------------------------------------------
# check(): for/against partition
# ---------------------------------------------------------------------------

class PartitionTests(unittest.TestCase):
    def test_supporting_and_opposing_split_by_side(self):
        findings = [
            finding(detector="a", claim="for the home side", side=base.HOME),
            finding(detector="b", claim="against the home side", side=base.AWAY),
        ]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)  # NYY is home
        self.assertEqual(len(result["supporting"]), 1)
        self.assertEqual(result["supporting"][0]["claim"], "for the home side")
        self.assertEqual(len(result["opposing"]), 1)
        self.assertEqual(result["opposing"][0]["claim"], "against the home side")

    def test_neither_side_findings_are_excluded_from_both(self):
        findings = [finding(detector="c", claim="about neither team",
                            side=base.NEITHER)]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertEqual(result["supporting"], [])
        self.assertEqual(result["opposing"], [])

    def test_context_findings_never_enter_the_partition(self):
        findings = [finding(detector="d", claim="context on the home side",
                            side=base.HOME, kind=base.CONTEXT)]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertEqual(result["supporting"], [])
        self.assertEqual(result["opposing"], [])

    def test_a_game_with_only_context_findings_still_returns_cleanly(self):
        findings = [
            finding(detector="e", claim="home context", side=base.HOME,
                   kind=base.CONTEXT),
            finding(detector="f", claim="away context", side=base.AWAY,
                   kind=base.CONTEXT),
        ]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertTrue(result["ok"])
        self.assertEqual(result["supporting"], [])
        self.assertEqual(result["opposing"], [])
        self.assertEqual(result["bottom_line"]["verdict"], "does_not_distinguish")

    def test_finding_missing_sample_is_a_warning_not_a_claim(self):
        findings = [finding(detector="g", claim="thin claim", side=base.HOME,
                           sample=None)]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertEqual(result["supporting"], [])
        self.assertEqual(len(result["sample_quality_warnings"]), 1)
        self.assertEqual(result["sample_quality_warnings"][0]["claim"],
                        "thin claim")

    def test_finding_missing_surprise_is_a_warning_not_a_claim(self):
        findings = [finding(detector="h", claim="unscored claim",
                           side=base.HOME, surprise=None)]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertEqual(result["supporting"], [])
        self.assertEqual(len(result["sample_quality_warnings"]), 1)


# ---------------------------------------------------------------------------
# Sample and label structurally present on every surviving claim
# ---------------------------------------------------------------------------

class SampleAndLabelTests(unittest.TestCase):
    def test_every_supporting_and_opposing_claim_carries_sample_and_label(self):
        findings = [
            finding(detector="a", claim="home claim", side=base.HOME),
            finding(detector="b", claim="away claim", side=base.AWAY),
        ]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        for claim in result["supporting"] + result["opposing"]:
            self.assertIsNotNone(claim["sample"])
            self.assertTrue(claim["evidence_label"])

    def test_evidence_label_matches_synthesis_vocabulary(self):
        findings = [finding(detector="a", claim="home claim", side=base.HOME,
                           evidence=base.TESTED_NULL)]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertEqual(result["supporting"][0]["evidence_label"],
                        "Tested — no edge")


# ---------------------------------------------------------------------------
# Market context: price context, never EV
# ---------------------------------------------------------------------------

class MarketContextTests(unittest.TestCase):
    def test_no_board_is_honestly_reported_unavailable(self):
        result = betcheck.check("Yankees ML -125", game_dossier(), findings=[])
        self.assertFalse(result["market_context"]["available"])

    def test_thin_board_is_honestly_reported_unavailable(self):
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                board=board(rows=3), findings=[])
        self.assertFalse(result["market_context"]["available"])

    def test_stated_price_beating_consensus_is_labelled_line_shopping_value(self):
        # Home consensus at -110/-110 implies ~0.5238; a stated +150 on the
        # home side beats that consensus by a wide margin.
        result = betcheck.check("Yankees ML +150", game_dossier(),
                                board=board(), findings=[])
        context = result["market_context"]
        self.assertTrue(context["available"])
        self.assertTrue(context["beats_consensus"])
        self.assertIn("line-shopping value", context["note"])

    def test_stated_price_worse_than_consensus_never_called_ev(self):
        result = betcheck.check("Yankees ML -500", game_dossier(),
                                board=board(), findings=[])
        context = result["market_context"]
        self.assertFalse(context["beats_consensus"])
        self.assertNotIn("edge", context["note"])

    def test_market_context_label_is_the_prices_module_label(self):
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                board=board(), findings=[])
        self.assertEqual(result["market_context"]["label"], prices_label())


def prices_label():
    from src.analysis import prices
    return prices.LABEL


# ---------------------------------------------------------------------------
# What-changed passthrough
# ---------------------------------------------------------------------------

class WhatChangedTests(unittest.TestCase):
    def test_what_changed_events_surface_when_present(self):
        events_section = {"events": [{"headline": "starter scratched"}]}
        dossier = game_dossier(sections={"what_changed": events_section})
        result = betcheck.check("Yankees ML -125", dossier, findings=[])
        self.assertEqual(result["what_changed"], events_section)

    def test_what_changed_absent_when_dossier_has_none(self):
        result = betcheck.check("Yankees ML -125", game_dossier(), findings=[])
        self.assertIsNone(result["what_changed"])


# ---------------------------------------------------------------------------
# Bottom line: honest, and always states no predictive edge is claimed
# ---------------------------------------------------------------------------

class BottomLineTests(unittest.TestCase):
    def test_no_findings_at_all_does_not_distinguish(self):
        result = betcheck.check("Yankees ML -125", game_dossier(), findings=[])
        self.assertEqual(result["bottom_line"]["verdict"], "does_not_distinguish")

    def test_more_supporting_than_opposing_supports(self):
        findings = [
            finding(detector="a", claim="one", side=base.HOME),
            finding(detector="b", claim="two", side=base.HOME),
            finding(detector="c", claim="three", side=base.AWAY),
        ]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertEqual(result["bottom_line"]["verdict"], "supports")

    def test_more_opposing_than_supporting_opposes(self):
        findings = [
            finding(detector="a", claim="one", side=base.AWAY),
            finding(detector="b", claim="two", side=base.AWAY),
            finding(detector="c", claim="three", side=base.HOME),
        ]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertEqual(result["bottom_line"]["verdict"], "opposes")

    def test_tied_counts_does_not_distinguish(self):
        findings = [
            finding(detector="a", claim="one", side=base.HOME),
            finding(detector="b", claim="two", side=base.AWAY),
        ]
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=findings)
        self.assertEqual(result["bottom_line"]["verdict"], "does_not_distinguish")

    def test_bottom_line_always_states_no_predictive_edge(self):
        for findings in ([], [finding(side=base.HOME)], [finding(side=base.AWAY)]):
            result = betcheck.check("Yankees ML -125", game_dossier(),
                                    findings=findings)
            self.assertIn("No predictive edge is claimed",
                         result["bottom_line"]["disclaimer"])

    def test_bottom_line_never_uses_the_word_edge_as_a_claim(self):
        # "no demonstrated betting edge" style language is fine; asserting a
        # positive edge is not. The disclaimer must say none is claimed.
        result = betcheck.check("Yankees ML -125", game_dossier(),
                                findings=[finding(side=base.HOME)])
        disclaimer = result["bottom_line"]["disclaimer"]
        self.assertIn("none has survived", disclaimer)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class DeterminismTests(unittest.TestCase):
    def test_parse_is_deterministic(self):
        results = [betcheck.parse("Yankees ML -125") for _ in range(5)]
        self.assertTrue(all(r == results[0] for r in results))

    def test_check_is_deterministic(self):
        findings = [
            finding(detector="a", claim="one", side=base.HOME),
            finding(detector="b", claim="two", side=base.AWAY),
        ]
        results = [betcheck.check("Yankees ML -125", game_dossier(),
                                  board=board(), findings=list(findings))
                  for _ in range(5)]
        self.assertTrue(all(r == results[0] for r in results))


if __name__ == "__main__":
    unittest.main()
