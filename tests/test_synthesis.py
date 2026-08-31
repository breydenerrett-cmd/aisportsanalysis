"""Tests for src/analysis/synthesis.py.

The synthesis block is the one part of the page a reader is guaranteed to
read, so the things it must never do are what get tested hardest: never mint
an item out of missing data, never show a number without its sample, never
let price improvement read as an edge, and never say the same thing twice in
different words.
"""

import tempfile
import unittest
from pathlib import Path

from src.analysis import synthesis
from src.detect import base
from src.detect import dossier as dossier_mod
from src.report import dashboard


def game_dossier(sections=None):
    d = dossier_mod.Dossier({"away_team": "BOS", "home_team": "NYY",
                            "date": "2026-08-28", "game_pk": 1,
                            "venue": "Yankee Stadium"})
    for name, data in (sections or {}).items():
        d.add(name, data)
    return d


def depth(away=None, home=None):
    """A matchup-depth section shaped exactly as matchup.build_section emits."""
    return {
        "cutoff": "2026-08-28",
        "nature": "observations",
        "away": away if away is not None else {
            "team": "BOS", "reason": "no posted away lineup stored"},
        "home": home if home is not None else {
            "team": "NYY", "reason": "no posted home lineup stored"},
    }


def away_entry(handedness=None, pitch_mix=None, concentration=None,
               starter_stuff=None):
    return {
        "team": "BOS",
        "opposing_starter_id": "42",
        "opposing_starter_throws": "L",
        "handedness": handedness or {},
        "pitch_mix": pitch_mix or {},
        "concentration": concentration or {},
        "starter_stuff": starter_stuff or {},
    }


PLATOON = {"starter": {"gap": 0.090, "vs_left_woba": 0.390,
                       "vs_right_woba": 0.300, "vs_left_faced": 250,
                       "vs_right_faced": 300, "weaker_against": "L"},
           "lineup": {"share": 0.66, "advantaged": 6, "known": 9}}

CONCENTRATION = {"top": {"woba": 0.300, "pa": 400},
                 "bottom": {"woba": 0.360, "pa": 500},
                 "gap": -0.060}

PITCH_MIX = {"primary": {"pitch_type": "FF", "usage_pct": 58.0,
                         "pitches": 900, "total_pitches": 1550},
             "lineup_vs_primary": {"woba": 0.400, "pa": 340,
                                   "batters_measured": 8}}

VELOCITY = {"velocity": {"avg": 91.4, "league_avg": 93.9, "gap": -2.5,
                         "fastballs": 400, "games": 5},
            "groundball": {"share": 0.52, "batted_balls": 300}}

PRICE = {
    "sides": {"away": {"best_book": "pinnacle", "best_price": 148,
                       "consensus_probability": 0.41,
                       "improvement_points": 0.0068,
                       "improvement_return_pct": 3.5},
              "home": {"best_book": "fanduel", "best_price": -160,
                       "consensus_probability": 0.59,
                       "improvement_points": 0.0011,
                       "improvement_return_pct": 0.4}},
    "dispersion": {"books": 9, "home_probability_range": 0.021},
    "label": "price improvement / line-shopping value",
}


def finding(detector="platoon_mismatch", claim="NYY's starter allows lots.",
            surprise=2.0, sample="250 BF vs L, 300 vs R",
            kind=base.SIGNAL, evidence=base.TESTED_NULL,
            market_relevance="bears on the first five", baseline=0.0):
    return base.Finding(detector, kind, claim, value=0.09, baseline=baseline,
                        sample=sample, surprise=surprise, side=base.AWAY,
                        market_relevance=market_relevance, evidence=evidence)


class TestNothingFabricated(unittest.TestCase):
    """None in, nothing out. The rule the rest of the project already follows."""

    def test_all_inputs_missing_yields_no_items(self):
        self.assertEqual(synthesis.top_findings(), [])
        self.assertEqual(synthesis.top_findings(None, None, None, None), [])

    def test_empty_dossier_yields_the_no_edge_headline(self):
        result = synthesis.synthesize(game_dossier(), [])
        self.assertEqual(result["items"], [])
        self.assertFalse(result["cleared"])
        self.assertEqual(result["headline"], synthesis.NO_EDGE_HEADLINE)
        self.assertIn("no demonstrated betting edge", result["headline"])

    def test_depth_present_but_every_picture_empty_mints_nothing(self):
        result = synthesis.synthesize(
            game_dossier(), [], depth=depth(away=away_entry()))
        self.assertEqual(result["items"], [])

    def test_a_sectionwide_reason_becomes_a_recorded_absence(self):
        result = synthesis.synthesize(
            game_dossier(), [],
            depth={"reason": "no posted lineup for this game"})
        self.assertEqual(result["items"], [])
        self.assertIn("no posted lineup for this game",
                      [s["reason"] for s in result["suppressed"]])

    def test_a_side_reason_becomes_a_recorded_absence(self):
        result = synthesis.synthesize(game_dossier(), [], depth=depth())
        self.assertEqual(result["items"], [])
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("no posted away lineup stored", reasons)

    def test_pitch_mix_without_a_baseline_is_cut_not_guessed(self):
        """No pooled overall line means no reference point, so no item."""
        result = synthesis.synthesize(
            game_dossier(), [],
            depth=depth(away=away_entry(pitch_mix=PITCH_MIX)))
        self.assertEqual(result["items"], [])
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("no baseline", reasons)

    def test_pitch_mix_with_a_baseline_states_the_gap_against_it(self):
        result = synthesis.synthesize(
            game_dossier(), [],
            depth=depth(away=away_entry(pitch_mix=PITCH_MIX,
                                        concentration=CONCENTRATION)))
        statements = [i["statement"] for i in result["items"]]
        self.assertTrue(any("FF" in s and "0.400" in s for s in statements))

    def test_groundball_share_never_becomes_an_item(self):
        """It is measured, has no league baseline, and so stays a description."""
        result = synthesis.synthesize(
            game_dossier(), [], depth=depth(away=away_entry(
                starter_stuff=VELOCITY)))
        for item in result["items"]:
            self.assertNotIn("Ground balls", item["statement"])
            self.assertNotIn("ground-ball", item["statement"])
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("no league ground-ball baseline", reasons)

    def test_a_finding_with_no_surprise_is_never_ranked(self):
        result = synthesis.synthesize(
            game_dossier(), [finding(surprise=None)])
        self.assertEqual(result["items"], [])
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("comparable scale", reasons)

    def test_a_finding_with_no_sample_is_never_ranked(self):
        result = synthesis.synthesize(game_dossier(), [finding(sample=None)])
        self.assertEqual(result["items"], [])
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("no sample size attached", reasons)

    def test_context_findings_are_never_summarised(self):
        note = base.Finding("stale_book", base.CONTEXT, "just context",
                            sample="10 books", surprise=9.0)
        result = synthesis.synthesize(game_dossier(), [note])
        self.assertEqual(result["items"], [])


class TestSamplesAlwaysAttached(unittest.TestCase):

    def full_result(self):
        d = game_dossier({"matchup_depth": depth(away=away_entry(
            handedness=PLATOON, pitch_mix=PITCH_MIX,
            concentration=CONCENTRATION, starter_stuff=VELOCITY)),
            "price_improvement": PRICE})
        return synthesis.synthesize(d, [finding()], limit=10)

    def test_there_is_something_to_test(self):
        self.assertGreaterEqual(len(self.full_result()["items"]), 3)

    def test_every_item_carries_a_sample(self):
        for item in self.full_result()["items"]:
            self.assertTrue(item["sample"],
                            f"{item['statement']} has no sample")
            self.assertIsInstance(item["sample"], str)
            self.assertRegex(item["sample"], r"\d",
                             "a sample with no number in it is not a sample")

    def test_every_item_carries_an_evidence_label(self):
        for item in self.full_result()["items"]:
            self.assertTrue(item["evidence_label"])
            self.assertTrue(item["evidence_meaning"])

    def test_a_below_floor_sample_is_marked_as_such(self):
        thin = dict(PLATOON, starter=dict(PLATOON["starter"],
                                          gap=0.120,
                                          vs_left_faced=30,
                                          vs_right_faced=25))
        result = synthesis.synthesize(
            game_dossier(), [], depth=depth(away=away_entry(handedness=thin)))
        self.assertEqual(len(result["items"]), 1)
        self.assertTrue(result["items"][0]["below_floor"])

    def test_a_healthy_sample_is_not_marked_below_floor(self):
        result = synthesis.synthesize(
            game_dossier(), [], depth=depth(away=away_entry(
                handedness=PLATOON)))
        self.assertFalse(result["items"][0]["below_floor"])


class TestAnUpperBoundIsNotADenominator(unittest.TestCase):
    """"<20 IP" says fewer than twenty innings, not twenty innings of evidence.

    The parser read the number and credited the thin-starter debunk with the
    very sample it exists to warn about -- and the renderer, asking the same
    function, printed it under the word "sample".
    """

    def test_a_less_than_bound_names_no_sample(self):
        self.assertIsNone(synthesis.sample_size("<20 IP"))
        self.assertIsNone(synthesis.sample_size("under 20 IP"))
        self.assertIsNone(synthesis.sample_size("fewer than 30 PA"))
        self.assertIsNone(synthesis.sample_size("at most 12 starts"))

    def test_a_plain_count_is_still_read(self):
        self.assertEqual(synthesis.sample_size("20 IP"), 20)
        self.assertEqual(synthesis.sample_size("129 fastballs"), 129)

    def test_a_bound_does_not_swallow_the_counts_beside_it(self):
        self.assertEqual(
            synthesis.sample_size("under 20 IP, 129 fastballs"), 129)

    def test_a_bound_scores_as_an_absent_sample_not_a_real_one(self):
        bounded = synthesis._sample_term(synthesis.sample_size("<20 IP"),
                                         "detector")
        absent = synthesis._sample_term(None, "detector")
        real = synthesis._sample_term(synthesis.sample_size("20 IP"),
                                      "detector")
        self.assertEqual(bounded, absent)
        self.assertNotEqual(real, bounded)

    def test_a_bounded_sample_reaches_the_page_unlabelled(self):
        # The renderer asks the same function, so the page says "no sample
        # size stated -- <20 IP" rather than "sample <20 IP".
        result = synthesis.synthesize(
            game_dossier(), [finding(detector="starter_mismatch",
                                     sample="<20 IP")], limit=10)
        for item in result["items"]:
            self.assertIsNone(item["sample_n"])


class TestRanking(unittest.TestCase):

    def test_bigger_and_better_sampled_effects_rank_higher(self):
        d = game_dossier({"price_improvement": PRICE})
        result = synthesis.synthesize(d, [], depth=depth(away=away_entry(
            handedness=PLATOON, concentration=CONCENTRATION)))
        categories = [i["category"] for i in result["items"]]
        self.assertEqual(categories,
                         ["price improvement", "starter platoon split",
                          "lineup concentration"])
        scores = [i["score"] for i in result["items"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_a_familiar_fact_loses_to_an_unfamiliar_one_of_equal_size(self):
        """Top-heavy lineups are what everyone assumes; an inverted one is not."""
        ordinary = {"top": {"woba": 0.360, "pa": 400},
                    "bottom": {"woba": 0.300, "pa": 500}, "gap": 0.060}
        novel = synthesis.synthesize(
            game_dossier(), [], limit=None,
            depth=depth(away=away_entry(concentration=CONCENTRATION)))
        self.assertEqual(len(novel["items"]), 1)
        self.assertIn("out-hit its top", novel["items"][0]["statement"])
        # Same gap, same samples; only the direction differs, and the
        # direction everyone already assumes scores lower.
        familiar_score = synthesis._score(
            synthesis._candidates(None, depth(away=away_entry(
                concentration=ordinary)), None, None)[0][0])["score"]
        self.assertLess(familiar_score, novel["items"][0]["score"])

    def test_a_tiny_effect_does_not_clear_the_bar(self):
        tiny = dict(PLATOON, starter=dict(PLATOON["starter"], gap=0.004))
        result = synthesis.synthesize(
            game_dossier(), [], depth=depth(away=away_entry(handedness=tiny)))
        self.assertEqual(result["items"], [])
        self.assertEqual(result["headline"], synthesis.NO_EDGE_HEADLINE)
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("below the", reasons)

    def test_refuted_evidence_ranks_below_an_open_question_of_equal_size(self):
        pair = [finding(detector="lineup_vs_starter", claim="A refuted claim.",
                        evidence=base.TESTED_NULL),
                finding(detector="bullpen_exposure", claim="An open claim.",
                        evidence=base.UNPROVEN)]
        result = synthesis.synthesize(game_dossier(), pair)
        self.assertEqual([i["statement"] for i in result["items"]],
                         ["An open claim.", "A refuted claim."])

    def test_the_headline_is_the_top_item(self):
        result = synthesis.synthesize(
            game_dossier(), [], depth=depth(away=away_entry(
                handedness=PLATOON)))
        self.assertEqual(result["headline"], result["items"][0]["statement"])

    def test_limit_is_respected_and_the_overflow_is_recorded(self):
        d = game_dossier({"matchup_depth": depth(away=away_entry(
            handedness=PLATOON, pitch_mix=PITCH_MIX,
            concentration=CONCENTRATION, starter_stuff=VELOCITY)),
            "price_improvement": PRICE})
        result = synthesis.synthesize(d, [finding()], limit=2)
        self.assertEqual(len(result["items"]), 2)
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("outside the top 2", reasons)

    def test_top_findings_returns_the_same_ranked_list(self):
        d = game_dossier({"matchup_depth": depth(away=away_entry(
            handedness=PLATOON, concentration=CONCENTRATION)),
            "price_improvement": PRICE})
        items = synthesis.top_findings(d, limit=5)
        self.assertEqual([i["statement"] for i in items],
                         [i["statement"]
                          for i in synthesis.synthesize(d, [])["items"]])


class TestDeduplication(unittest.TestCase):

    def test_the_same_starter_split_is_stated_once(self):
        """The platoon detector and the depth handedness picture read the same
        split off the same pitcher. The page must not say it twice."""
        d = game_dossier()
        result = synthesis.synthesize(
            d, [finding()], depth=depth(away=away_entry(handedness=PLATOON)))
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["source"],
                         "matchup depth (handedness)")
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("restates the same fact", reasons)

    def test_the_duplicate_that_was_cut_is_still_named(self):
        d = game_dossier()
        result = synthesis.synthesize(
            d, [finding()], depth=depth(away=away_entry(handedness=PLATOON)))
        cut = [s for s in result["suppressed"]
               if "restates" in s["reason"]]
        self.assertEqual(len(cut), 1)
        self.assertEqual(cut[0]["statement"], "NYY's starter allows lots.")

    def test_two_sides_of_the_same_kind_are_not_confused_for_duplicates(self):
        both = depth(away=away_entry(handedness=PLATOON),
                     home=dict(away_entry(handedness=PLATOON), team="NYY"))
        result = synthesis.synthesize(game_dossier(), [], depth=both)
        self.assertEqual(len(result["items"]), 2)

    def test_a_pitch_mix_claim_dedupes_against_the_depth_picture(self):
        claim = ("NYY's starter throws his four-seamer 58% of the time, and "
                 "against that same pitch BOS's posted lineup measures a "
                 "0.400 wOBA.")
        d = game_dossier()
        result = synthesis.synthesize(
            d, [finding(detector="pitch_mix_mismatch", claim=claim,
                        sample="8 hitters, 340 plate appearances")],
            depth=depth(away=away_entry(pitch_mix=PITCH_MIX,
                                        concentration=CONCENTRATION)))
        pitch_items = [i for i in result["items"]
                       if i["fact_key"] == "pitch_mix:away"]
        self.assertEqual(len(pitch_items), 1)

    def test_an_unrecognisable_claim_shape_still_ranks_without_deduping(self):
        """A claim that does not name its pitcher's team gets a detector-scoped
        key rather than a guessed side -- a wrong dedup is worse than none."""
        result = synthesis.synthesize(
            game_dossier(),
            [finding(detector="platoon_mismatch", claim="Somebody's starter.")],
            depth=depth(away=away_entry(handedness=PLATOON)))
        self.assertEqual(len(result["items"]), 2)


class TestPriceIsNeverAnEdge(unittest.TestCase):

    def test_the_statement_says_what_it_is_not(self):
        result = synthesis.synthesize(
            game_dossier(), [], price_improvement=PRICE)
        statement = result["items"][0]["statement"]
        self.assertIn("line-shopping value", statement)
        self.assertIn("not expected value", statement)
        self.assertIn("not a prediction", statement)

    def test_it_never_calls_itself_an_edge_or_ev(self):
        result = synthesis.synthesize(
            game_dossier(), [], price_improvement=PRICE)
        for item in result["items"]:
            lowered = item["statement"].lower()
            self.assertNotIn("edge", lowered)
            self.assertNotIn("+ev", lowered)
            self.assertNotIn("clv", lowered)

    def test_the_best_side_is_the_one_reported(self):
        result = synthesis.synthesize(
            game_dossier(), [], price_improvement=PRICE)
        item = result["items"][0]
        self.assertEqual(item["side"], "away")
        self.assertIn("BOS", item["statement"])
        self.assertIn("pinnacle", item["statement"])

    def test_a_thin_board_is_a_reason_not_a_number(self):
        result = synthesis.synthesize(
            game_dossier(), [],
            price_improvement={"skipped": "3 books quoted; below the floor"})
        self.assertEqual(result["items"], [])
        self.assertIn("3 books quoted; below the floor",
                      [s["reason"] for s in result["suppressed"]])

    def test_trivial_improvement_does_not_reach_the_summary(self):
        small = {"sides": {"away": dict(PRICE["sides"]["away"],
                                        improvement_return_pct=0.3)},
                 "dispersion": {"books": 9}}
        result = synthesis.synthesize(game_dossier(), [],
                                      price_improvement=small)
        self.assertEqual(result["items"], [])
        reasons = " ".join(s["reason"] for s in result["suppressed"])
        self.assertIn("below the 1.0% floor", reasons)


class TestDossierWiring(unittest.TestCase):

    def test_sections_are_read_off_the_dossier_when_not_passed(self):
        d = game_dossier({"matchup_depth": depth(away=away_entry(
            handedness=PLATOON)), "price_improvement": PRICE})
        result = synthesis.synthesize(d)
        keys = {i["fact_key"] for i in result["items"]}
        self.assertIn("platoon:away", keys)
        self.assertIn("price:away", keys)

    def test_a_dossier_with_only_gaps_produces_nothing(self):
        d = game_dossier()
        d.miss("matchup_depth", "not built for this slate")
        d.miss("price_improvement", "no multi-book observations")
        self.assertEqual(synthesis.synthesize(d, [])["items"], [])


class TestDashboardRendersIt(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def slate(self, sections=None, findings=()):
        return {"date": "2026-08-28",
                "games": [{"dossier": game_dossier(sections),
                           "findings": list(findings), "verdict": "no_play",
                           "summary": "x"}],
                "notes": []}

    def render(self, slate):
        dashboard.render(slate, self.path)
        return self.path.read_text(encoding="utf-8")

    def test_the_block_is_the_top_of_the_card(self):
        html = self.render(self.slate({
            "matchup_depth": depth(away=away_entry(handedness=PLATOON))}))
        self.assertIn("What matters tonight", html)
        self.assertLess(html.index("What matters tonight"),
                        html.index("Why this game is interesting"))

    def test_the_no_edge_line_renders_when_nothing_clears(self):
        html = self.render(self.slate())
        self.assertIn("no demonstrated betting edge", html)

    def test_samples_render_next_to_every_statement(self):
        html = self.render(self.slate({
            "matchup_depth": depth(away=away_entry(handedness=PLATOON))}))
        self.assertIn("250 batters faced left-handed, 300 right-handed", html)

    def test_a_precomputed_synthesis_is_used_as_is(self):
        slate = self.slate()
        slate["games"][0]["synthesis"] = {
            "items": [], "cleared": False,
            "headline": "a precomputed headline", "note": "n",
            "suppressed": []}
        self.assertIn("a precomputed headline", self.render(slate))

    def test_what_was_left_out_is_rendered_with_its_reason(self):
        # synthesize() computed an honest audit trail and the page threw it
        # away, so the summary looked like everything the system had to say.
        unrankable = finding(claim="A claim with no surprise attached.",
                             surprise=None)
        html = self.render(self.slate(findings=[unrankable]))
        self.assertIn("What was left out, and why", html)
        self.assertIn("A claim with no surprise attached.", html)
        self.assertIn("could not express its surprise", html)

    def test_the_audit_trail_is_collapsed_by_default(self):
        html = self.render(self.slate(findings=[finding(surprise=None)]))
        self.assertIn("<details class=\"cut\">", html)
        self.assertNotIn("<details class=\"cut\" open", html)

    def test_nothing_left_out_renders_no_section(self):
        slate = self.slate()
        slate["games"][0]["synthesis"] = {
            "items": [], "cleared": False, "headline": "h", "note": "n",
            "suppressed": []}
        self.assertNotIn("What was left out, and why", self.render(slate))

    def test_the_reasons_are_the_ones_synthesis_wrote(self):
        # Nothing here is paraphrased, softened or invented by the renderer.
        slate = self.slate()
        slate["games"][0]["synthesis"] = {
            "items": [], "cleared": False, "headline": "h", "note": "n",
            "suppressed": [{"statement": "a cut statement",
                            "reason": "a verbatim reason"}]}
        html = self.render(slate)
        self.assertIn("a cut statement", html)
        self.assertIn("a verbatim reason", html)

    def test_the_page_stays_script_free(self):
        html = self.render(self.slate({
            "matchup_depth": depth(away=away_entry(handedness=PLATOON)),
            "price_improvement": PRICE}))
        self.assertNotIn("<script", html.lower())


if __name__ == "__main__":
    unittest.main()
