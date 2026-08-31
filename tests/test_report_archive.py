"""Tests for per-game permalinks and the season archive index.

Two properties carry the weight here. An anchor has to name the game rather
than its slot on the page, or a saved link silently points at a different
matchup after a postponement. And the archive has to list what it could not
read, by name -- an index that hides the files it failed on is an index that
overstates the record it claims to keep.
"""

import tempfile
import unittest
from pathlib import Path

from src.analysis import synthesis as synthesis_mod
from src.detect import base
from src.detect import dossier as dossier_mod
from src.report import archive
from src.report import dashboard


def _game(away="BOS", home="NYY", date="2026-08-28", pk=1, number=None):
    game = {"away_team": away, "home_team": home, "date": date, "game_pk": pk,
            "venue": "Yankee Stadium"}
    if number is not None:
        game["game_number"] = number
    d = dossier_mod.Dossier(game)
    d.add("market", {"markets": {"h2h": {"away_price": 142, "home_price": -168}}})
    return d


def _slate(dossiers, date="2026-08-28", findings=()):
    findings = list(findings)
    # §2.1: the dashboard no longer derives synthesis for an entry that lacks
    # it, so every hand-built entry has to carry one, computed the same way
    # briefing.build_slate does for the real pipeline.
    return {"date": date,
            "games": [{"dossier": d, "findings": findings,
                       "verdict": "no_play", "summary": "x",
                       "synthesis": synthesis_mod.synthesize(d, findings)}
                      for d in dossiers],
            "notes": []}


class TestPermalinks(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def _render(self, slate, name="b.html"):
        path = self.root / name
        dashboard.render(slate, path)
        return path.read_text(encoding="utf-8")

    def test_anchor_is_derived_from_teams_and_date(self):
        html = self._render(_slate([_game()]))
        self.assertIn('id="game-BOS-NYY-2026-08-28"', html)

    def test_the_anchor_is_visible_on_the_card_as_a_link(self):
        html = self._render(_slate([_game()]))
        self.assertIn('href="#game-BOS-NYY-2026-08-28"', html)
        self.assertIn("#game-BOS-NYY-2026-08-28<", html)

    def test_anchor_survives_a_game_being_dropped_from_the_slate(self):
        """The whole point. Enumeration ids move when the slate changes."""
        full = _slate([_game("LAD", "SD"), _game("BOS", "NYY"),
                       _game("CHC", "MIL")])
        trimmed = _slate([_game("BOS", "NYY"), _game("CHC", "MIL")])
        self.assertIn('id="game-BOS-NYY-2026-08-28"', self._render(full))
        self.assertIn('id="game-BOS-NYY-2026-08-28"',
                      self._render(trimmed, "c.html"))

    def test_rebuilding_the_same_slate_produces_the_same_anchors(self):
        slate = _slate([_game("LAD", "SD"), _game("BOS", "NYY")])
        first = self._render(slate, "one.html")
        second = self._render(_slate([_game("LAD", "SD"), _game("BOS", "NYY")]),
                              "two.html")
        ids = lambda text: sorted(  # noqa: E731
            line for line in text.split('id="') if line.startswith("game-"))
        self.assertEqual([i.split('"')[0] for i in ids(first)],
                         [i.split('"')[0] for i in ids(second)])

    def test_a_doubleheader_gets_two_distinct_stable_anchors(self):
        html = self._render(_slate([_game(pk=11, number=1),
                                    _game(pk=12, number=2)]))
        self.assertIn('id="game-BOS-NYY-2026-08-28-1"', html)
        self.assertIn('id="game-BOS-NYY-2026-08-28-2"', html)

    def test_the_slate_summary_links_to_the_stable_anchor(self):
        finding = base.Finding("d", base.SIGNAL, "a claim", value=1, baseline=0,
                               surprise=3.0)
        html = self._render(_slate([_game()], findings=[finding]))
        self.assertIn('class="leaditem" href="#game-BOS-NYY-2026-08-28"', html)

    def test_permalinks_add_no_script(self):
        html = self._render(_slate([_game()]))
        self.assertNotIn("<script", html)

    def test_the_embedded_index_never_closes_its_own_comment(self):
        finding = base.Finding("d", base.SIGNAL, "an em--dash--heavy claim",
                               value=1, baseline=0)
        html = self._render(_slate([_game()], findings=[finding]))
        head = html[html.index("<body>"):html.index("<div class=\"wrap\">")]
        self.assertEqual(head.count("-->"), 1)


class TestArchiveScan(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_it_lists_the_real_files_it_finds(self):
        dashboard.render(_slate([_game()], date="2026-08-28"),
                         self.root / "briefing.html")
        dashboard.render(_slate([_game("LAD", "SD")], date="2026-08-29"),
                         self.root / "analyze_LAD_SD_2026-08-29.html")
        result = archive.scan(self.root)
        self.assertEqual([r["file"] for r in result["records"]],
                         ["analyze_LAD_SD_2026-08-29.html", "briefing.html"])
        for record in result["records"]:
            self.assertIsNone(record["unparseable"])
            self.assertEqual(record["games"], 1)
            self.assertEqual(record["source"], archive.SOURCE_EMBEDDED)

    def test_an_unreadable_file_is_named_not_skipped(self):
        dashboard.render(_slate([_game()]), self.root / "briefing.html")
        (self.root / "junk.html").write_text("<h1>not ours</h1>",
                                             encoding="utf-8")
        result = archive.scan(self.root)
        bad = [r for r in result["records"] if r["unparseable"]]
        self.assertEqual([r["file"] for r in bad], ["junk.html"])
        self.assertIn("not written by this project", bad[0]["unparseable"])

    def test_a_page_without_the_embedded_index_is_still_read(self):
        """Briefings written before the marker existed must not vanish."""
        dashboard.render(_slate([_game()]), self.root / "old.html")
        path = self.root / "old.html"
        text = path.read_text(encoding="utf-8")
        marker = text.index("<!--" + dashboard.INDEX_MARKER)
        path.write_text(text[:marker] + text[text.index("-->", marker) + 3:],
                        encoding="utf-8")
        record = archive.read_artifact(path)
        self.assertIsNone(record["unparseable"])
        self.assertEqual(record["source"], archive.SOURCE_MARKUP)
        self.assertEqual(record["date"], "2026-08-28")
        self.assertEqual(record["games"], 1)

    def test_named_exclusions_are_reported_rather_than_dropped_quietly(self):
        (self.root / "demo_latest.html").write_text("x", encoding="utf-8")
        result = archive.scan(self.root)
        self.assertEqual(result["records"], [])
        self.assertEqual([n for n, _ in result["skipped"]],
                         ["demo_latest.html"])

    def test_a_missing_directory_says_so_instead_of_claiming_emptiness(self):
        result = archive.scan(self.root / "nope")
        self.assertTrue(result["missing_directory"])


class TestArchivePage(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        dashboard.render(_slate([_game()]), self.root / "briefing.html")
        (self.root / "junk.html").write_text("<h1>not ours</h1>",
                                             encoding="utf-8")
        self.out = self.root / "archive.html"
        archive.render(self.root, self.out)
        self.html = self.out.read_text(encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def test_no_script_and_no_network(self):
        self.assertNotIn("<script", self.html)
        for pattern in ("http://", "https://", 'src="//'):
            self.assertNotIn(pattern, self.html)

    def test_it_links_each_artifact_relatively(self):
        self.assertIn('href="briefing.html"', self.html)

    def test_the_unparseable_file_is_named_on_the_page(self):
        self.assertIn("junk.html", self.html)
        self.assertIn("unparseable", self.html)

    def test_it_does_not_index_itself(self):
        again = archive.scan(self.root, out_name=self.out)
        self.assertNotIn("archive.html", [r["file"] for r in again["records"]])


if __name__ == "__main__":
    unittest.main()
