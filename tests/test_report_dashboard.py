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

from src.detect import base
from src.detect import dossier as dossier_mod
from src.report import dashboard


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
    html = Path(path).read_text(encoding="utf-8")
    raw = re.search(r'<script id="slate" type="application/json">(.*?)</script>',
                    html, re.S).group(1)
    return html, json.loads(raw.replace("<\\/", "</"))


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

    def test_styles_and_script_are_inline(self):
        dashboard.render(slate(), self.path)
        html = self.path.read_text(encoding="utf-8")
        self.assertIn("<style>", html)
        self.assertIn("<script>", html)

    def test_the_json_cannot_break_out_of_its_script_tag(self):
        # A team name containing "</script>" would otherwise end the block and
        # turn the rest of the payload into markup.
        payload = slate()
        payload["games"][0]["dossier"].game["venue"] = "</script><b>x</b>"
        dashboard.render(payload, self.path)
        html = self.path.read_text(encoding="utf-8")
        self.assertNotIn("</script><b>", html)


class TestEvidenceLabelling(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_every_finding_carries_a_human_label_and_meaning(self):
        finding = base.Finding("d", base.SIGNAL, "x", value=1, baseline=0,
                               evidence=base.UNPROVEN)
        _, data = extract(dashboard.render(slate([finding]), self.path))
        rendered = data["games"][0]["findings"][0]
        self.assertEqual(rendered["evidence_label"], "Unproven")
        self.assertIn("Never tested", rendered["evidence_meaning"])

    def test_unproven_is_the_default_a_finding_must_argue_out_of(self):
        self.assertEqual(base.Finding("d", base.CONTEXT, "x").evidence,
                         base.UNPROVEN)

    def test_every_status_has_a_label(self):
        for status in base.EVIDENCE_ORDER:
            self.assertIn(status, dashboard.EVIDENCE_LABELS)

    def test_the_footer_always_states_the_paper_only_rule(self):
        html, _ = extract(dashboard.render(slate(), self.path))
        self.assertIn("No bet is placed", html)


class TestGapsAreRendered(unittest.TestCase):
    """A gap shown as a gap; never an empty box that reads as a zero."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "b.html"

    def tearDown(self):
        self.dir.cleanup()

    def test_a_missing_section_carries_its_reason(self):
        _, data = extract(dashboard.render(
            slate(gaps={"lineups": "not posted yet"}), self.path))
        self.assertEqual(data["games"][0]["gaps"]["lineups"], "not posted yet")

    def test_counts_are_computed_from_the_verdicts(self):
        _, data = extract(dashboard.render(slate(verdict="flagged"), self.path))
        self.assertEqual(data["counts"]["flagged"], 1)
        self.assertEqual(data["counts"]["games"], 1)


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


if __name__ == "__main__":
    unittest.main()
