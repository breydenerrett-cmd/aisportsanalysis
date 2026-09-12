"""The knowledge grade on the screens that show it (card.js, games.js,
tiles.js). Plain-text scans, like the other web structure tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_no_developer_notes_on_screen import _rendered_strings

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"


def _read(name: str) -> str:
    return (WEB_JS / name).read_text(encoding="utf-8")


class TheCardShowsIt(unittest.TestCase):
    def setUp(self):
        self.text = _read("card.js")

    def test_a_grade_chip_sits_beside_the_label(self):
        body = self.text.split("function pickCard(")[1].split("\nfunction ")[0]
        self.assertIn('"data-hook": "card-grade"', body)
        self.assertIn("pick.knowledge", body)
        label_at = body.find("card2__label card2__label--")
        grade_at = body.find('"data-hook": "card-grade"')
        self.assertLess(label_at, grade_at)

    def test_the_reason_is_the_hover_text(self):
        body = self.text.split("function pickCard(")[1].split("\nfunction ")[0]
        self.assertIn("title: knowledge.why", body)

    def test_the_legend_is_served_not_typed(self):
        note = self.text.split("function standingNote(")[1].split("\nfunction ")[0]
        self.assertIn("payload.knowledge_legend", note)
        self.assertIn('"data-hook": "card-grade-legend"', note)
        # No client-side copy of the legend's sentences.
        rendered = " ".join(t for _n, t in _rendered_strings(WEB_JS / "card.js"))
        self.assertNotIn("not how much we expect to win", rendered)


class TheGamesGridShowsIt(unittest.TestCase):
    def setUp(self):
        self.text = _read("games.js")

    def test_the_grade_rides_the_tile_flag(self):
        body = self.text.split("export async function renderGamesList(")[1].split("\nexport ")[0]
        self.assertIn("row2.knowledge", body)
        self.assertIn("flag,", body)

    def test_the_grade_flag_is_never_money_red(self):
        body = self.text.split("export async function renderGamesList(")[1].split("\nexport ")[0]
        flag_block = body.split("const flag = knowledge")[1].split(";")[0]
        self.assertNotIn('"money"', flag_block)

    def test_the_legend_is_served_not_typed(self):
        self.assertIn("payload.knowledge_legend", self.text)
        self.assertIn('"data-hook": "games-grade-legend"', self.text)


class TheTileCarriesTheReason(unittest.TestCase):
    def test_a_flag_may_carry_a_title(self):
        text = _read("tiles.js")
        self.assertIn("opts.flag.title", text)


if __name__ == "__main__":
    unittest.main()
