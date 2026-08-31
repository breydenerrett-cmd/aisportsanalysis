"""Tests for src/report/dashboard.py and src/detect/dossier.py.

The page's one job beyond showing data is never letting an unvalidated number
read as a validated one, so the evidence labelling is what gets tested hardest.
Second is the self-containment: a briefing that needs a server or a CDN is not
openable on a phone in a year's time, which is the entire point of it.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

import src.analysis as analysis
from src.analysis import prices as prices_mod
from src.analysis import synthesis as synthesis_mod
from src.detect import base
from src.detect import dossier as dossier_mod
from src.report import dashboard
from src.report import ranker


def slate(findings=(), verdict="no_play", gaps=None):
    d = dossier_mod.Dossier({"away_team": "BOS", "home_team": "NYY",
                             "date": "2026-08-28", "game_pk": 1,
                             "venue": "Yankee Stadium"})
    d.add("market", {"markets": {"h2h": {"away_price": 142, "home_price": -168,
                                         "away_fair": 0.41, "home_fair": 0.59}}})
    for name, reason in (gaps or {}).items():
        d.miss(name, reason)
    return {"date": "2026-08-28",
            "games": [{"dossier": d, "findings": list(findings),
                       "verdict": verdict, "summary": "x"}],
            "notes": ["a note"]}


def extract(path):
    """The page is now rendered server-side, so the assertions read the HTML."""
    return Path(path).read_text(encoding="utf-8")


class TestSelfContained(unittest.TestCase):
    """No server, no CDN, no fonts. It has to open from a file in a year."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_no_external_references(self):
        dashboard.render(slate(), self.path)
        html = self.path.read_text(encoding="utf-8")
        for pattern in ("http://", "https://", "src=\"//"):
            self.assertNotIn(pattern, html,
                             f"page reaches outside itself via {pattern}")

    def test_there_is_no_javascript_at_all(self):
        # An earlier version built the page in JS from an embedded JSON blob.
        # That renders fine in a normal tab and produces a COMPLETELY BLANK PAGE
        # anywhere inline scripts are blocked -- a sandboxed preview pane, a
        # strict CSP, a viewer with scripting off. It failed exactly that way the
        # first time it was opened somewhere other than here.
        dashboard.render(slate(), self.path)
        html = self.path.read_text(encoding="utf-8")
        self.assertIn("<style>", html)
        self.assertNotIn("<script", html)

    def test_the_content_is_in_the_html_not_in_a_data_blob(self):
        finding = base.Finding("d", base.SIGNAL, "a very specific claim",
                               value=1, baseline=0)
        dashboard.render(slate([finding]), self.path)
        body = self.path.read_text(encoding="utf-8")
        body = body[body.index("<body>"):]
        self.assertIn("a very specific claim", body)
        # And the visible markup is substantial, not a stub waiting for script.
        self.assertGreater(len(body), 2000)

    def test_expand_and_collapse_is_native(self):
        dashboard.render(slate(), self.path)
        html = self.path.read_text(encoding="utf-8")
        self.assertIn("<details", html)
        self.assertIn("<summary", html)

    def test_hostile_text_cannot_inject_markup(self):
        # Venue and team names come from an external feed. Rendering them into
        # HTML unescaped would turn a feed value into page structure.
        payload = slate()
        payload["games"][0]["dossier"].game["venue"] = "<b>bold</b>"
        dashboard.render(payload, self.path)
        html = self.path.read_text(encoding="utf-8")
        self.assertNotIn("<b>bold</b>", html)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", html)


class TestEvidenceLabelling(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_every_finding_carries_a_human_label_and_meaning(self):
        finding = base.Finding("d", base.SIGNAL, "x", value=1, baseline=0,
                               evidence=base.UNPROVEN)
        html = extract(dashboard.render(slate([finding]), self.path))
        self.assertIn("Unproven", html)
        self.assertIn("Never tested", html)

    def test_unproven_is_the_default_a_finding_must_argue_out_of(self):
        self.assertEqual(base.Finding("d", base.CONTEXT, "x").evidence,
                         base.UNPROVEN)

    def test_every_status_has_a_label(self):
        for status in base.EVIDENCE_ORDER:
            self.assertIn(status, dashboard.EVIDENCE_LABELS)

    def test_the_footer_always_states_the_paper_only_rule(self):
        self.assertIn("No bet is placed",
                      extract(dashboard.render(slate(), self.path)))


class TestGapsAreRendered(unittest.TestCase):
    """A gap shown as a gap; never an empty box that reads as a zero."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_a_missing_section_carries_its_reason(self):
        html = extract(dashboard.render(
            slate(gaps={"lineups": "not posted yet"}), self.path))
        self.assertIn("not posted yet", html)

    def test_counts_are_rendered_from_the_verdicts(self):
        html = extract(dashboard.render(slate(verdict="flagged"), self.path))
        self.assertIn("flagged", html)
        self.assertIn("<b>1</b>", html)


class TestPlainSerialisation(unittest.TestCase):

    def test_an_unserialisable_value_becomes_its_repr_not_a_hole(self):
        # Dropping it would render as missing data, which is a different and
        # false statement from "this value is odd".
        class Weird:
            def __repr__(self):
                return "<weird>"
        self.assertEqual(dashboard._plain({"k": Weird()}), {"k": "<weird>"})

    def test_nested_structures_survive(self):
        self.assertEqual(dashboard._plain({"a": [1, {"b": 2}]}), {"a": [1, {"b": 2}]})

    def test_none_and_scalars_pass_through(self):
        self.assertEqual(dashboard._plain([None, 1, 1.5, "x", True]),
                         [None, 1, 1.5, "x", True])


class TestDossierDevigsOnce(unittest.TestCase):
    """No detector may ever see a raw implied probability."""

    def test_fair_probabilities_are_attached_and_sum_to_one(self):
        section = dossier_mod._market_section(
            {"h2h": {"away_price": 142, "home_price": -168}})
        h2h = section["markets"]["h2h"]
        self.assertAlmostEqual(h2h["away_fair"] + h2h["home_fair"], 1.0, places=3)

    def test_the_hold_is_reported(self):
        section = dossier_mod._market_section(
            {"h2h": {"away_price": -110, "home_price": -110}})
        self.assertGreater(section["markets"]["h2h"]["hold_pct"], 4.0)

    def test_totals_are_devigged_on_their_own_axis(self):
        section = dossier_mod._market_section(
            {"totals": {"total": 8.5, "over_price": -102, "under_price": -120}})
        totals = section["markets"]["totals"]
        self.assertAlmostEqual(totals["over_fair"] + totals["under_fair"], 1.0,
                               places=3)
        self.assertEqual(totals["total"], 8.5)

    def test_the_implied_bullpen_shift_is_full_game_minus_first_five(self):
        # The whole idea. Reversing the subtraction credits the wrong bullpen.
        section = dossier_mod._market_section({
            "h2h": {"away_price": 142, "home_price": -168},
            "h2h_1st_5_innings": {"away_price": 168, "home_price": -215}})
        full = section["markets"]["h2h"]["home_fair"]
        five = section["markets"]["h2h_1st_5_innings"]["home_fair"]
        self.assertAlmostEqual(section["implied_bullpen_shift"],
                               round(full - five, 4), places=4)
        self.assertLess(section["implied_bullpen_shift"], 0)

    def test_an_undevigable_market_records_the_error_rather_than_a_number(self):
        section = dossier_mod._market_section(
            {"h2h": {"away_price": 0, "home_price": -110}})
        self.assertIn("devig_error", section["markets"]["h2h"])
        self.assertNotIn("away_fair", section["markets"]["h2h"])

    def test_all_books_survives_into_the_section(self):
        section = dossier_mod._market_section(
            {"all_books": {"h2h": [{"book": "a", "away_price": 1, "home_price": 2}]}})
        self.assertEqual(len(section["all_books"]["h2h"]), 1)


class TestDossierRecordsAbsence(unittest.TestCase):

    def test_a_gap_is_named_with_a_reason(self):
        d = dossier_mod.Dossier({"away_team": "A", "home_team": "B"})
        d.miss("weather", "not fetched")
        self.assertEqual(d.gaps["weather"], "not fetched")

    def test_sections_and_gaps_are_disjoint_in_the_dict(self):
        d = dossier_mod.Dossier({"away_team": "A", "home_team": "B"})
        d.add("teams", {"x": 1})
        d.miss("weather", "no")
        payload = d.to_dict()
        self.assertIn("teams", payload["sections"])
        self.assertIn("weather", payload["gaps"])


# ---------------------------------------------------------------------------
# Red-team regressions. Each of these pins a sentence the page got WRONG when
# it was read the way a sharp bettor reads it: not "is the number right" but
# "does the rendered page claim something it cannot support".
# ---------------------------------------------------------------------------

class TestThePageCanCountItsOwnLosers(unittest.TestCase):
    """One fact, one number, everywhere it is stated.

    The briefing header said "Thirteen pre-registered hypotheses" (the V1-only
    figure) while every game card's note below it said 27, and the Ranker
    banner said twenty-four. Three counts of the identical fact, two of them on
    one rendered page. A reader who catches the page miscounting its own
    falsification record has no reason to believe the rest of it.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_the_header_states_the_count_from_the_one_constant(self):
        dashboard.render(slate(), self.path)
        html = extract(self.path)
        self.assertIn(analysis.HYPOTHESES_TESTED_WORD, html)
        self.assertNotIn("Thirteen pre-registered", html)

    def test_the_briefing_and_the_ranker_state_the_same_count(self):
        dashboard.render(slate(), self.path)
        page = extract(self.path)
        banner = ranker.BANNER
        # Both surfaces spell the count out; neither carries a stale numeral.
        self.assertIn(analysis.HYPOTHESES_TESTED_WORD, page)
        self.assertIn(analysis.HYPOTHESES_TESTED_WORD, banner)
        for stale in ("Thirteen", "Twenty-four", "twenty-four"):
            self.assertNotIn(stale, page)
            self.assertNotIn(stale, banner)

    def test_the_per_game_note_states_the_same_count(self):
        self.assertIn(str(analysis.HYPOTHESES_TESTED), synthesis_mod.NOTE)


class TestTheLeadDoesNotDenyItsOwnFindings(unittest.TestCase):
    """"Nothing unusual on this slate" while a card lists a 2.0 finding.

    The lead only ever considered non-context findings, but when it found none
    it announced that NO detector had found anything out of the ordinary --
    with, directly beneath it, a travel finding scored 2.0 standard units from
    normal. The lead may only claim what it actually looked at.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def _context_finding(self):
        return base.Finding(
            "travel_load", base.CONTEXT,
            "BOS has played 8 games in seven days, where a normal week holds 6.",
            value=8.0, baseline=6.0, sample="7-day window", surprise=2.0,
            evidence=base.TESTED_NULL)

    def test_a_context_only_slate_is_not_called_free_of_findings(self):
        dashboard.render(slate([self._context_finding()]), self.path)
        html = extract(self.path)
        self.assertNotIn("No detector found anything out of the ordinary", html)
        self.assertNotIn("Nothing unusual on this slate", html)

    def test_it_says_what_it_checked_and_counts_what_it_skipped(self):
        dashboard.render(slate([self._context_finding()]), self.path)
        html = extract(self.path)
        self.assertIn("points at a side", html)
        self.assertIn("1 context finding(s) did fire", html)

    def test_a_truly_empty_slate_says_so_without_hedging(self):
        dashboard.render(slate([]), self.path)
        self.assertIn("No context finding fired either.", extract(self.path))


class TestSampleMeansSample(unittest.TestCase):
    """The header promises every number carries the sample it rests on.

    Travel and bullpen findings carry a PERIOD in the sample slot -- "7-day
    window", "since SF, 3 day(s) ago" -- and synthesis already refuses to read
    those as denominators when ranking. Rendering them under the word "sample"
    lent them a sample size they do not have.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_an_elapsed_period_is_not_labelled_a_sample(self):
        finding = base.Finding(
            "travel_load", base.CONTEXT, "SF flew 2,126 miles east from home.",
            value=2126.5, baseline=215.0, sample="since SF, 3 day(s) ago",
            surprise=3.9, evidence=base.TESTED_NULL)
        dashboard.render(slate([finding]), self.path)
        html = extract(self.path)
        self.assertIn("no sample size stated", html)
        self.assertNotIn("sample since SF", html)

    def test_a_real_count_keeps_the_word_sample(self):
        finding = base.Finding(
            "stale_book", base.SIGNAL, "A book sits off the pack.",
            value=0.62, baseline=0.64, sample="11 books", surprise=1.7,
            evidence=base.TESTED_NULL)
        dashboard.render(slate([finding]), self.path)
        html = extract(self.path)
        self.assertIn("sample 11 books", html)
        self.assertNotIn("no sample size stated", html)

    def test_the_renderer_and_the_ranker_ask_the_same_question(self):
        # Two layers deciding "is this a sample" independently would label one
        # string two ways on one page.
        self.assertIsNone(synthesis_mod.sample_size("7-day window"))
        self.assertEqual(synthesis_mod.sample_size("11 books"), 11)


class TestPriceImprovementIsNotFlattered(unittest.TestCase):
    """The improvement column, in the units its heading claims.

    It was headed "improvement (prob pts)" and printed a probability FRACTION
    (-0.0056) -- a hundredfold understatement, and a different scale from the
    "1.9 points of win probability" a detector quotes on the same card. A
    missing value printed as a confident +0.0000.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def _slate(self, sides, observed="2026-08-31T10:08:30+00:00"):
        s = slate()
        s["games"][0]["dossier"].add("price_improvement", {
            "sides": sides,
            "dispersion": {"books": 10, "home_probability_range": 0.0103},
            "observed_utc": observed,
            "label": prices_mod.LABEL})
        return s

    def test_points_are_rendered_in_points_not_in_fractions(self):
        dashboard.render(self._slate({
            "away": {"best_book": "b", "best_price": 147,
                     "consensus_probability": 0.399,
                     "improvement_points": -0.0056,
                     "improvement_return_pct": -1.38}}), self.path)
        html = extract(self.path)
        self.assertIn("-0.56", html)
        self.assertNotIn("-0.0056", html)
        self.assertIn("win-prob points", html)

    def test_a_missing_number_is_a_dash_not_a_confident_zero(self):
        dashboard.render(self._slate({
            "away": {"best_book": "b", "best_price": 147}}), self.path)
        html = extract(self.path)
        self.assertNotIn("+0.00%", html)
        self.assertNotIn("0.0%", html)

    def test_an_all_negative_board_says_why_it_is_negative(self):
        dashboard.render(self._slate({
            "away": {"best_book": "b", "best_price": 147,
                     "consensus_probability": 0.399,
                     "improvement_points": -0.0056,
                     "improvement_return_pct": -1.38}}), self.path)
        html = extract(self.path)
        self.assertIn("still carries the book", html)
        self.assertIn("normally negative", html)

    def test_a_positive_board_does_not_carry_the_negative_note(self):
        dashboard.render(self._slate({
            "away": {"best_book": "b", "best_price": 147,
                     "consensus_probability": 0.399,
                     "improvement_points": 0.0056,
                     "improvement_return_pct": 1.38}}), self.path)
        self.assertNotIn("normally negative", extract(self.path))

    def test_the_board_carries_the_instant_it_was_captured(self):
        # A detector on the same card quotes its own book count from its own
        # snapshot. The page rendered "10 books" beside "the 11-book consensus"
        # with nothing to say they were different boards.
        dashboard.render(self._slate({
            "away": {"best_book": "b", "best_price": 147,
                     "consensus_probability": 0.399,
                     "improvement_points": -0.0056,
                     "improvement_return_pct": -1.38}}), self.path)
        html = extract(self.path)
        self.assertIn("10 books at one instant", html)
        self.assertIn("2026-08-31T10:08:30+00:00", html)

    def test_an_unrecorded_instant_is_admitted_rather_than_implied(self):
        dashboard.render(self._slate({
            "away": {"best_book": "b", "best_price": 147,
                     "consensus_probability": 0.399,
                     "improvement_points": -0.0056,
                     "improvement_return_pct": -1.38}}, observed=None),
            self.path)
        self.assertIn("capture instant not recorded", extract(self.path))


class TestSuppressedMeansSuppressed(unittest.TestCase):
    """A page must not describe itself falsely.

    Under a splits table quoting a thin starter at .535 OPS on 23 batters
    faced, the page printed "his rates are small-sample noise and are
    suppressed rather than shown". The sentence was about the season rate line
    only; a reader taking it at face value read the .535 as the OTHER starter's.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def _slate(self, with_splits):
        s = slate()
        d = s["games"][0]["dossier"]
        d.add("starters", {"away_sp_thin": True, "home_sp_thin": False,
                           "either_sp_thin": True, "away_sp_innings": 9.3,
                           "home_sp_fip": 4.60, "home_sp_innings": 143.7})
        if with_splits:
            d.add("splits", {"away": {"record": {"splits": {
                "Home Games": {"ops": 0.535, "batters_faced": 23,
                               "innings": 6.1}}}}})
        return s

    def test_it_does_not_claim_to_suppress_what_it_prints(self):
        dashboard.render(self._slate(True), self.path)
        html = extract(self.path)
        self.assertIn("0.535", html)
        self.assertNotIn("suppressed rather than shown", html)

    def test_the_thin_starter_is_named_and_his_rows_are_marked(self):
        dashboard.render(self._slate(True), self.path)
        html = extract(self.path)
        self.assertIn("BOS", html)          # the away club, the thin one
        self.assertIn("(small sample)", html)
        self.assertIn("ARE shown", html)

    def test_with_no_splits_rows_it_only_claims_the_rate_line(self):
        dashboard.render(self._slate(False), self.path)
        html = extract(self.path)
        self.assertIn("withheld rather than shown", html)
        self.assertNotIn("ARE shown", html)


class TestAHypotheticalCardSaysSoOnTheCard(unittest.TestCase):
    """The artifact outlives the terminal line that explained it.

    `analyze` builds a card for any two clubs on any date, and told the
    operator "no real game on this date" in the TERMINAL. The saved HTML read
    as an ordinary game card -- venue, verdict, real season records -- with the
    word "hypothetical" only in the missing-data list at the bottom.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_the_marker_matches_the_sentence_the_cli_actually_stamps(self):
        from src import cli
        self.assertEqual(dashboard.HYPOTHETICAL_GAP, cli.HYPOTHETICAL_GAP)

    def test_the_collapsed_header_carries_it(self):
        dashboard.render(
            slate(gaps={"starters": dashboard.HYPOTHETICAL_GAP,
                        "lineups": dashboard.HYPOTHETICAL_GAP}), self.path)
        html = extract(self.path)
        self.assertIn("HYPOTHETICAL, never played", html)

    def test_the_body_says_the_game_does_not_exist(self):
        dashboard.render(
            slate(gaps={"starters": dashboard.HYPOTHETICAL_GAP,
                        "lineups": dashboard.HYPOTHETICAL_GAP}), self.path)
        html = extract(self.path)
        self.assertIn("This game does not exist", html)

    def test_a_real_game_carries_no_such_banner(self):
        dashboard.render(slate(gaps={"weather": "not fetched"}), self.path)
        html = extract(self.path)
        self.assertNotIn("HYPOTHETICAL", html)
        self.assertNotIn("This game does not exist", html)


class TestWinsColumnIsCalledWins(unittest.TestCase):
    """A column headed "Record" holding only wins invites a reader to supply
    the losses that were never there."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_the_header_names_the_field_it_holds(self):
        s = slate()
        s["games"][0]["dossier"].add("teams", {"away_wins": 54, "home_wins": 80,
                                               "away_win_pct": 0.403})
        dashboard.render(s, self.path)
        html = extract(self.path)
        self.assertIn("<td>Wins</td>", html)
        self.assertNotIn("<td>Record</td>", html)


if __name__ == "__main__":
    unittest.main()
