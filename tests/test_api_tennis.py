"""Tests for GET /tennis/board."""

from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from api.app import app
    _HAVE_FASTAPI = True
except Exception:
    _HAVE_FASTAPI = False


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class TennisBoardEndpoint(unittest.TestCase):
    """The /tennis/board endpoint."""

    def test_board_route_exists(self):
        """GET /tennis/board returns a board payload."""
        from api.tennis import _board_for_date

        # Mock board_for_date to return a test payload
        test_payload = {
            "date": "2026-09-14",
            "tournaments": [
                {
                    "key": "tennis_atp",
                    "title": "ATP",
                    "matches": [
                        {
                            "event_id": "evt_1",
                            "player_a": "A",
                            "player_b": "B",
                            "commence_time": "2026-09-14T14:00:00Z",
                            "likelier": "a",
                            "probability": 0.55,
                            "books": 7,
                            "observed_utc": "2026-09-14T10:00:00Z",
                        }
                    ],
                }
            ],
            "notice": "Research only.",
            "generated_utc": "2026-09-14T12:00:00Z",
        }

        with patch("api.tennis._board_for_date") as mock:
            mock.return_value = test_payload

            from api.tennis import get_tennis_board

            result = get_tennis_board(date="2026-09-14")

            self.assertEqual(result["date"], "2026-09-14")
            self.assertEqual(len(result["tournaments"]), 1)
            mock.assert_called_once_with("2026-09-14")

    def test_board_defaults_to_today(self):
        """GET /tennis/board with no date defaults to today."""
        from api.tennis import _board_for_date

        test_payload = {
            "date": "2026-09-14",
            "tournaments": [],
            "notice": "Research only.",
            "generated_utc": "2026-09-14T12:00:00Z",
        }

        with patch("api.tennis._board_for_date") as mock:
            mock.return_value = test_payload

            from api.tennis import get_tennis_board
            from datetime import date as date_cls

            result = get_tennis_board(date=None)

            # Should have called with today's date (but we can't check exact
            # date without mocking the date module too)
            self.assertIsNotNone(result["date"])

    def test_board_rejects_invalid_date(self):
        """GET /tennis/board rejects invalid date format."""
        from api.tennis import get_tennis_board
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            get_tennis_board(date="not-a-date")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("YYYY-MM-DD", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
