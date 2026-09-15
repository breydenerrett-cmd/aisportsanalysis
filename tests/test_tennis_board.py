"""Tests for tennis_board.board_for_date."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone


class TestBoardForDate(unittest.TestCase):
    """board_for_date with fixture rows."""

    def test_board_with_two_tournaments_and_six_books(self):
        """Two tournaments, one match with 7 books (consensus), one with 3."""
        from src.report import tennis_board

        # Fixture: two tournaments with matches
        rows = [
            # Tournament 1: ATP China Open, match 1 with 7 books
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_atp_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Djokovic",
                "home_team": "Alcaraz",
                "book": "fanduel",
                "away_price": -110,
                "home_price": -110,
                "sport": "tennis_atp_china_open",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_atp_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Djokovic",
                "home_team": "Alcaraz",
                "book": "draftkings",
                "away_price": -115,
                "home_price": -105,
                "sport": "tennis_atp_china_open",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_atp_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Djokovic",
                "home_team": "Alcaraz",
                "book": "betmgm",
                "away_price": -120,
                "home_price": -100,
                "sport": "tennis_atp_china_open",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_atp_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Djokovic",
                "home_team": "Alcaraz",
                "book": "caesars",
                "away_price": -118,
                "home_price": -102,
                "sport": "tennis_atp_china_open",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_atp_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Djokovic",
                "home_team": "Alcaraz",
                "book": "betrivers",
                "away_price": -111,
                "home_price": -109,
                "sport": "tennis_atp_china_open",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_atp_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Djokovic",
                "home_team": "Alcaraz",
                "book": "pointsbetus",
                "away_price": -114,
                "home_price": -106,
                "sport": "tennis_atp_china_open",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_atp_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Djokovic",
                "home_team": "Alcaraz",
                "book": "bovada",
                "away_price": -113,
                "home_price": -107,
                "sport": "tennis_atp_china_open",
            },
            # Tournament 2: WTA US Open, match 2 with 3 books (below MIN_BOOKS)
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_wta_1",
                "commence_time": "2026-09-14T16:00:00Z",
                "away_team": "Swiatek",
                "home_team": "Sabalenka",
                "book": "fanduel",
                "away_price": -105,
                "home_price": -115,
                "sport": "tennis_wta_us_open",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_wta_1",
                "commence_time": "2026-09-14T16:00:00Z",
                "away_team": "Swiatek",
                "home_team": "Sabalenka",
                "book": "draftkings",
                "away_price": -103,
                "home_price": -117,
                "sport": "tennis_wta_us_open",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_wta_1",
                "commence_time": "2026-09-14T16:00:00Z",
                "away_team": "Swiatek",
                "home_team": "Sabalenka",
                "book": "betmgm",
                "away_price": -107,
                "home_price": -113,
                "sport": "tennis_wta_us_open",
            },
        ]

        tournaments = [
            {
                "key": "tennis_atp_china_open",
                "title": "ATP China Open",
                "active": True,
            },
            {
                "key": "tennis_wta_us_open",
                "title": "WTA US Open",
                "active": True,
            },
        ]

        payload = tennis_board.board_for_date(
            "2026-09-14", rows=rows, tournaments=tournaments,
            now=datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc))

        # Verify structure
        self.assertEqual(payload["date"], "2026-09-14")
        self.assertIn("notice", payload)
        self.assertIn("generated_utc", payload)
        self.assertIn("tournaments", payload)

        # Two tournaments
        self.assertEqual(len(payload["tournaments"]), 2)

        # Tournament 1: has 7-book match with consensus
        t1 = payload["tournaments"][0]
        self.assertEqual(t1["key"], "tennis_atp_china_open")
        self.assertEqual(t1["title"], "ATP China Open")
        self.assertEqual(len(t1["matches"]), 1)
        m1 = t1["matches"][0]
        self.assertEqual(m1["event_id"], "evt_atp_1")
        self.assertEqual(m1["player_a"], "Djokovic")
        self.assertEqual(m1["player_b"], "Alcaraz")
        self.assertEqual(m1["books"], 7)
        # With 7 books, we have a consensus
        self.assertIsNotNone(m1["probability"])
        self.assertIn(m1["likelier"], ("a", "b"))

        # Tournament 2: has 3-book match (below MIN_BOOKS=6)
        t2 = payload["tournaments"][1]
        self.assertEqual(t2["key"], "tennis_wta_us_open")
        self.assertEqual(t2["title"], "WTA US Open")
        self.assertEqual(len(t2["matches"]), 1)
        m2 = t2["matches"][0]
        self.assertEqual(m2["event_id"], "evt_wta_1")
        self.assertEqual(m2["books"], 3)
        # With only 3 books, probability should be None
        self.assertIsNone(m2["probability"])

    def test_notice_present(self):
        """The notice is always present and correct."""
        from src.report import tennis_board

        payload = tennis_board.board_for_date(
            "2026-09-15", rows=[], tournaments=[])

        expected_notice = (
            "Research only. No tennis picks until results grading is connected.")
        self.assertEqual(payload["notice"], expected_notice)

    def test_empty_board_for_empty_date(self):
        """Empty tournaments list when no matches for that date."""
        from src.report import tennis_board

        payload = tennis_board.board_for_date(
            "2026-09-15", rows=[], tournaments=[])

        self.assertEqual(payload["date"], "2026-09-15")
        self.assertEqual(payload["tournaments"], [])

    def test_tournament_title_prettification(self):
        """Tournament title from discovery, or prettified from key."""
        from src.report import tennis_board

        rows = [
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Player A",
                "home_team": "Player B",
                "book": "fanduel",
                "away_price": -110,
                "home_price": -110,
                "sport": "tennis_atp_wimbledon",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Player A",
                "home_team": "Player B",
                "book": "draftkings",
                "away_price": -110,
                "home_price": -110,
                "sport": "tennis_atp_wimbledon",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Player A",
                "home_team": "Player B",
                "book": "betmgm",
                "away_price": -110,
                "home_price": -110,
                "sport": "tennis_atp_wimbledon",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Player A",
                "home_team": "Player B",
                "book": "caesars",
                "away_price": -110,
                "home_price": -110,
                "sport": "tennis_atp_wimbledon",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Player A",
                "home_team": "Player B",
                "book": "betrivers",
                "away_price": -110,
                "home_price": -110,
                "sport": "tennis_atp_wimbledon",
            },
            {
                "observed_utc": "2026-09-14T10:00:00+00:00",
                "event_id": "evt_1",
                "commence_time": "2026-09-14T14:00:00Z",
                "away_team": "Player A",
                "home_team": "Player B",
                "book": "pointsbetus",
                "away_price": -110,
                "home_price": -110,
                "sport": "tennis_atp_wimbledon",
            },
        ]

        # No tournament from discovery - title should be prettified
        payload = tennis_board.board_for_date(
            "2026-09-14", rows=rows, tournaments=[])

        self.assertEqual(len(payload["tournaments"]), 1)
        tournament = payload["tournaments"][0]
        # "tennis_atp_wimbledon" -> "Atp Wimbledon"
        self.assertIn("Wimbledon", tournament["title"])


if __name__ == "__main__":
    unittest.main()
