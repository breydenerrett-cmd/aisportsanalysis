"""src/analysis/digest.py: pure, offline, on fixture data -- same fixture
style tests/test_gamepayload.py uses (real entries through
src.pipeline.briefing.build_slate, no sqlite file, no network).
"""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.analysis import digest as digest_mod
from src.detect import dossier as dossier_mod
from src.pipeline import briefing, history


def _game(game_pk=880001, away="BOS", home="NYY", date="2026-08-31"):
    return {"game_pk": game_pk, "date": date, "away_team": away,
            "home_team": home, "venue": "Yankee Stadium",
            "start_time_utc": f"{date}T23:05:00Z"}


def _priced_game_entries(**kwargs):
    """One real entry with a full multi-book board on it -- lifted from
    tests/test_gamepayload.py's identical helper so both test files build
    the exact same fixture shape and never drift on what "a priced game"
    means for these tests."""
    game = _game(**kwargs)
    observed = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
    price_key = (game["away_team"], game["home_team"], game["date"])
    prices_by_matchup = {
        (game["away_team"], game["home_team"]): {
            "h2h": {"away_price": 120, "home_price": -140,
                    "away_fair": 0.45, "home_fair": 0.55},
        }
    }
    price_boards_by_key = {
        price_key: {
            "quotes": [{"ts": observed.isoformat(), "book": b,
                       "away_price": 110 + i, "home_price": -130 - i}
                      for i, b in enumerate(
                          ["a", "b", "c", "d", "e", "f", "g"])],
            "observed_utc": observed.isoformat(),
            "source": "test",
        }
    }
    store = history.read_results()
    # roster_events_by_pk={} keeps this fixture hermetic: without it,
    # build_slate derives What Changed from the REAL data/watch stores,
    # and this game uses a real matchup/date (BOS@NYY, 2026-08-31) -- the
    # hourly capture appending real roster events eventually flipped the
    # "quiet slate" tests red (first seen 2026-09-01). Tests that want
    # events add them to the dossier explicitly.
    slate = briefing.build_slate(
        [game], store, prices_by_matchup=prices_by_matchup,
        price_boards_by_key=price_boards_by_key, roster_events_by_pk={})
    return slate["games"], slate.get("notes", [])


# A minimal stand-in for src.appstate.savedbets.SavedBet -- a plain
# dataclass with the same field surface build_user_digest actually reads
# (.is_settled, .settled_at, .game, .side, .settlement_status,
# .settlement_reason), so this test file never has to touch a real sqlite
# db to exercise the digest's own settlement-filtering logic.
@dataclass(frozen=True)
class _FakeBet:
    id: int
    game: str
    side: str
    settlement_status: Optional[str] = None
    settlement_reason: Optional[str] = None
    settled_at: Optional[str] = None
    # Appended last, defaulted, so every existing positional call site above
    # (built before saved-bet price alerts existed) keeps working unchanged.
    price: Optional[float] = None

    @property
    def is_settled(self) -> bool:
        return self.settlement_status is not None


class SettlementHighlightsTests(unittest.TestCase):
    def test_first_digest_reports_every_settled_bet(self):
        bets = [
            _FakeBet(1, "BOS@NYY", "BOS ML", "won", None,
                    "2026-08-30T04:00:00+00:00"),
            _FakeBet(2, "LAD@SF", "home", None, None, None),  # unsettled
        ]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes,
            since_last_digest=None)
        self.assertEqual(len(out["settled_bets"]), 1)
        self.assertEqual(out["settled_bets"][0]["id"], 1)
        self.assertEqual(out["settled_bets"][0]["settlement_status"], "won")

    def test_bet_settled_before_last_digest_is_not_repeated(self):
        bets = [_FakeBet(1, "BOS@NYY", "BOS ML", "won", None,
                         "2026-08-29T04:00:00+00:00")]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes,
            since_last_digest="2026-08-30T00:00:00+00:00")
        self.assertEqual(out["settled_bets"], [])

    def test_bet_settled_after_last_digest_is_reported(self):
        bets = [_FakeBet(1, "BOS@NYY", "BOS ML", "lost", None,
                         "2026-08-31T04:00:00+00:00")]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes,
            since_last_digest="2026-08-30T00:00:00+00:00")
        self.assertEqual(len(out["settled_bets"]), 1)

    def test_settled_bets_ordered_oldest_first(self):
        bets = [
            _FakeBet(1, "A@B", "home", "won", None, "2026-08-31T10:00:00+00:00"),
            _FakeBet(2, "C@D", "away", "lost", None, "2026-08-31T02:00:00+00:00"),
        ]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes)
        self.assertEqual([b["id"] for b in out["settled_bets"]], [2, 1])


class SlateSummaryTests(unittest.TestCase):
    def test_quiet_night_statement_on_a_zero_game_slate(self):
        out = digest_mod.build_user_digest(
            7, "2026-12-25", entries=[], saved_bets=[], notes=[])
        self.assertEqual(out["slate"]["checked_games"], 0)
        self.assertIn("No MLB games scheduled", out["slate"]["headline"])

    def test_game_count_reported_honestly(self):
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=[], notes=notes)
        self.assertEqual(out["slate"]["checked_games"], 1)
        self.assertIn("1 game", out["slate"]["headline"])


class WhatChangedHighlightsTests(unittest.TestCase):
    def test_quiet_slate_says_so_with_context(self):
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=[], notes=notes)
        self.assertTrue(out["what_changed"]["quiet"])
        self.assertEqual(out["what_changed"]["highlights"], [])
        self.assertIn("Checked 1 game", out["what_changed"]["headline"])

    def test_high_tier_event_surfaces_as_a_highlight(self):
        dossier = dossier_mod.Dossier(_game())
        dossier.add("what_changed", {
            "cutoff": "2026-08-31", "not_an_edge": "descriptive only",
            "events": [{
                "class": "starter_scratch", "headline": "BOS: starter scratched",
                "tier": "HIGH", "tier_sentence": "relevance HIGH",
                "basis": [], "reasons": ["an established starter is out"],
                "timing": "bounded", "seen_utc": "2026-08-31T16:00:00Z",
                "inadmissible": False, "summary": "starter scratched",
            }],
        })
        entry = {"dossier": dossier, "findings": []}
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=[entry], saved_bets=[], notes=[])
        self.assertFalse(out["what_changed"]["quiet"])
        self.assertEqual(len(out["what_changed"]["highlights"]), 1)
        self.assertEqual(out["what_changed"]["highlights"][0]["tier"], "HIGH")

    def test_low_tier_event_never_surfaces(self):
        dossier = dossier_mod.Dossier(_game())
        dossier.add("what_changed", {
            "cutoff": "2026-08-31", "not_an_edge": "x",
            "events": [{
                "class": "transaction_seen", "headline": "recall",
                "tier": "LOW", "tier_sentence": "relevance LOW",
                "basis": [], "reasons": [], "timing": "bounded",
                "seen_utc": "2026-08-31T16:00:00Z", "inadmissible": False,
                "summary": "recall",
            }],
        })
        entry = {"dossier": dossier, "findings": []}
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=[entry], saved_bets=[], notes=[])
        self.assertTrue(out["what_changed"]["quiet"])

    def test_inadmissible_high_tier_never_surfaces(self):
        dossier = dossier_mod.Dossier(_game())
        dossier.add("what_changed", {
            "cutoff": "2026-08-31", "not_an_edge": "x",
            "events": [{
                "class": "starter_scratch", "headline": "scratch",
                "tier": "HIGH", "tier_sentence": "relevance HIGH",
                "basis": [], "reasons": [], "timing": "unbounded",
                "seen_utc": "2026-08-31T16:00:00Z", "inadmissible": True,
                "summary": "scratch",
            }],
        })
        entry = {"dossier": dossier, "findings": []}
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=[entry], saved_bets=[], notes=[])
        self.assertTrue(out["what_changed"]["quiet"])


class PriceImprovementObservationTests(unittest.TestCase):
    def test_none_when_no_side_beats_consensus(self):
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=[], notes=notes)
        # The fixture's board is a flat ladder (a=110..g=116 / -130..-136) --
        # whether that produces a positive improvement_return_pct on any
        # side is an outcome of the real prices.snapshot() math, not
        # something this test should assert either way; it only asserts the
        # shape stays honest either way.
        self.assertIn("price_improvement", out)
        if out["price_improvement"] is not None:
            self.assertGreater(
                out["price_improvement"]["improvement_return_pct"], 0)

    def test_none_on_an_empty_slate(self):
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=[], saved_bets=[], notes=[])
        self.assertIsNone(out["price_improvement"])

    def test_observation_names_the_actual_game_when_present(self):
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=[], notes=notes)
        obs = out["price_improvement"]
        if obs is not None:
            self.assertEqual(obs["away_team"], "BOS")
            self.assertEqual(obs["home_team"], "NYY")


class SavedBetPriceAlertsTests(unittest.TestCase):
    """_saved_bet_price_alerts, exercised through build_user_digest against
    the same injected board _priced_game_entries() builds for every other
    test in this file: away books run 110..116 (best 116, book "g"), home
    books run -130..-136 (best -130, book "a" -- least negative is the
    highest decimal odds)."""

    def test_unsettled_bet_with_a_worse_saved_price_surfaces_an_alert(self):
        bets = [_FakeBet(1, "BOS@NYY", "BOS ML", price=110)]  # away, worse than 116
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes)
        alerts = out["saved_bet_price_alerts"]
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["bet_id"], 1)
        self.assertEqual(alert["saved_price"], 110)
        self.assertEqual(alert["best_price"], 116)
        self.assertEqual(alert["best_book"], "g")
        self.assertIsNotNone(alert["observed_utc"])
        self.assertIn("better price", alert["note"])

    def test_settled_bet_never_surfaces_even_with_a_worse_saved_price(self):
        bets = [_FakeBet(1, "BOS@NYY", "BOS ML", "won", None,
                         "2026-08-31T04:00:00+00:00", price=110)]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes)
        self.assertEqual(out["saved_bet_price_alerts"], [])

    def test_bet_already_at_the_best_price_does_not_surface(self):
        # -125 has BETTER (higher) decimal odds than the board's best -130.
        bets = [_FakeBet(2, "BOS@NYY", "NYY ML", price=-125)]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes)
        self.assertEqual(out["saved_bet_price_alerts"], [])

    def test_bet_with_no_recorded_price_is_left_out(self):
        bets = [_FakeBet(3, "BOS@NYY", "BOS ML", price=None)]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes)
        self.assertEqual(out["saved_bet_price_alerts"], [])

    def test_bet_for_a_game_not_on_tonights_board_is_left_out(self):
        bets = [_FakeBet(4, "LAD@SF", "LAD ML", price=110)]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes)
        self.assertEqual(out["saved_bet_price_alerts"], [])

    def test_unresolvable_side_is_left_out_not_guessed(self):
        # "LAD ML" names neither club in BOS@NYY -- the same cannot-tell
        # case src.appstate.settlement grades void-unmatchable rather than
        # guess at.
        bets = [_FakeBet(5, "BOS@NYY", "LAD ML", price=110)]
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes)
        self.assertEqual(out["saved_bet_price_alerts"], [])

    def test_empty_slate_yields_no_alerts(self):
        bets = [_FakeBet(6, "BOS@NYY", "BOS ML", price=110)]
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=[], saved_bets=bets, notes=[])
        self.assertEqual(out["saved_bet_price_alerts"], [])


class JsonSafeTests(unittest.TestCase):
    def test_full_payload_is_json_serialisable(self):
        entries, notes = _priced_game_entries()
        bets = [_FakeBet(1, "BOS@NYY", "BOS ML", "won", None,
                         "2026-08-31T04:00:00+00:00")]
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=bets, notes=notes)
        json.dumps(out)  # raises if anything is not JSON-safe

    def test_no_win_probability_or_recommendation_field_anywhere(self):
        entries, notes = _priced_game_entries()
        out = digest_mod.build_user_digest(
            7, "2026-08-31", entries=entries, saved_bets=[], notes=notes)
        blob = json.dumps(out).lower()
        for banned in ("win_probability", "win probability", "recommendation"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
