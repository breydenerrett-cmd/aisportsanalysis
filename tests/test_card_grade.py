"""src/report/card.py::attach_knowledge -- the grade on each pick.

Built on a Dossier assembled by hand, so the test decides what is known
about the game rather than the disk deciding it.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.analysis import grade
from src.analysis import prices as prices_mod
from src.appstate import card_ledger
from src.detect import dossier as dossier_mod
from src.report import card as card_mod

NOW = datetime(2026, 9, 12, 20, 0, tzinfo=timezone.utc)
NINE = [{"person_id": i, "name": f"Batter {i}"} for i in range(1, 10)]


def _dossier(*, game_pk=777, lineups=True, probables=True, books=9,
             age_minutes=10, gaps=()):
    game = {"game_pk": game_pk, "date": "2026-09-12", "away_team": "BOS",
            "home_team": "NYY", "start_time_utc": "2026-09-12T23:05:00Z",
            "away_probable_id": 11 if probables else None,
            "home_probable_id": 22 if probables else None}
    d = dossier_mod.Dossier(game, information_time=NOW)
    if lineups:
        d.add("lineups", {"away": {"batters": NINE}, "home": {"batters": NINE}})
    else:
        d.miss("lineups", "lineup not posted yet, or not fetched")
    observed = (NOW - timedelta(minutes=age_minutes)).isoformat()
    d.add("price_improvement", {"observed_utc": observed,
                                "dispersion": {"books": books},
                                "sides": {}})
    for name in ("teams", "starters", "bullpen", "weather", "park"):
        if name in gaps:
            d.miss(name, f"{name} not built")
        else:
            d.add(name, {})
    return d


def _payload(*picks):
    return {"picks": [dict(p) for p in picks]}


def _pick(game_pk=777, market="moneyline", price=-150, model_p=0.62):
    return {"game_pk": game_pk, "market": market, "price": price,
            "model_probability": model_p}


class AttachKnowledge(unittest.TestCase):
    def test_a_fully_known_game_is_an_A_on_its_pick(self):
        payload = card_mod.attach_knowledge(
            _payload(_pick(model_p=0.55)), [{"dossier": _dossier()}], now=NOW)
        knowledge = payload["picks"][0]["knowledge"]
        self.assertEqual(knowledge["letter"], "A")
        # -150 needs 60%; 55% does not clear it, so no plus.
        self.assertEqual(knowledge["grade"], "A")

    def test_the_plus_when_the_number_clears_the_price(self):
        payload = card_mod.attach_knowledge(
            _payload(_pick(price=-150, model_p=0.66)), [{"dossier": _dossier()}], now=NOW)
        self.assertEqual(payload["picks"][0]["knowledge"]["grade"], "A+")

    def test_no_plus_on_a_run_line_pick(self):
        """On a run-line pick `model_probability` is a cover probability and
        `price` is the run-line price -- comparing them is a different
        question than the plus asks."""
        payload = card_mod.attach_knowledge(
            _payload(_pick(market="run_line", price=120, model_p=0.99)),
            [{"dossier": _dossier()}], now=NOW)
        self.assertEqual(payload["picks"][0]["knowledge"]["grade"], "A")

    def test_a_pick_with_no_dossier_gets_no_grade_not_a_guess(self):
        payload = card_mod.attach_knowledge(
            _payload(_pick(game_pk=999)), [{"dossier": _dossier(game_pk=777)}], now=NOW)
        self.assertIsNone(payload["picks"][0]["knowledge"])

    def test_the_join_is_on_game_pk_whatever_its_type(self):
        payload = card_mod.attach_knowledge(
            _payload(_pick(game_pk="777")), [{"dossier": _dossier(game_pk=777)}], now=NOW)
        self.assertIsNotNone(payload["picks"][0]["knowledge"])

    def test_a_missing_lineup_grades_c_however_good_the_board(self):
        payload = card_mod.attach_knowledge(
            _payload(_pick()), [{"dossier": _dossier(lineups=False)}], now=NOW)
        self.assertEqual(payload["picks"][0]["knowledge"]["letter"], "C")

    def test_a_thin_board_grades_b(self):
        payload = card_mod.attach_knowledge(
            _payload(_pick()), [{"dossier": _dossier(books=prices_mod.MIN_BOOKS - 1)}],
            now=NOW)
        self.assertEqual(payload["picks"][0]["knowledge"]["letter"], "B")

    def test_the_legend_rides_the_card(self):
        payload = card_mod.attach_knowledge(_payload(), [], now=NOW)
        self.assertEqual(payload["knowledge_legend"], list(grade.legend()))

    def test_the_grade_is_frozen_with_the_pick(self):
        """Shown to the reader, so part of what was claimed."""
        self.assertIn("knowledge", card_ledger.FROZEN_FIELDS)
        payload = card_mod.attach_knowledge(
            _payload(_pick()), [{"dossier": _dossier()}], now=NOW)
        frozen = card_ledger._frozen_pick(payload["picks"][0])
        self.assertEqual(frozen["knowledge"]["letter"], "A")


if __name__ == "__main__":
    unittest.main()
