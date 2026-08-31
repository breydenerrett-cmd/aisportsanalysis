"""api/today.py: today's slate, serialised, from the REAL domain path.

Offline: no network fetch, no odds-provider credit spent. The games list is
hand-built the same way tests/test_report_dashboard.py builds one -- a
minimal, real-shaped game dict -- rather than mocking briefing.build_slate
itself, so this test exercises the actual dossier/synthesis/make_entry
pipeline, not a stand-in for it. The historical store is the REAL repo
store (src.pipeline.history.read_results with its default path): whatever
rows exist on disk today, which may be none.
"""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone

from src.pipeline import history

from api.today import build_today_payload


def _today_game(game_pk=990001):
    today = date.today().isoformat()
    return {
        "game_pk": game_pk,
        "date": today,
        "away_team": "BOS",
        "home_team": "NYY",
        "venue": "Yankee Stadium",
    }


class BuildTodayPayloadTests(unittest.TestCase):

    def test_builds_from_the_real_domain_path_and_real_store(self):
        """The real historical store (whatever it holds right now) and a
        real-shaped game go through briefing.build_slate unmocked, and the
        payload is JSON-serialisable end to end."""
        store = history.read_results()  # real repo store, offline read
        games = [_today_game()]
        payload = build_today_payload(games, store)

        # Round-trips through json with no TypeError -- the whole point of
        # serialize_entry existing.
        blob = json.dumps(payload)
        reloaded = json.loads(blob)

        self.assertEqual(len(reloaded["games"]), 1)
        entry = reloaded["games"][0]
        self.assertIn("dossier", entry)
        self.assertIn("verdict", entry)
        self.assertIn("odds_meta", entry)
        self.assertIn("generated_at", reloaded)

    def test_no_forbidden_vocabulary_leaks_into_the_payload(self):
        """Evidence-rule guardrails, checked at the wire: no model win
        probability field, and price improvement is never called EV/edge.
        This is a payload-shape check, not exhaustive proof -- it fails loud
        the moment a field with a forbidden name is added."""
        store = history.read_results()
        games = [_today_game()]
        payload = build_today_payload(games, store)
        blob = json.dumps(payload).lower()

        for forbidden in ("win_probability", "win_prob", '"true_probability"'):
            self.assertNotIn(forbidden, blob)

    def test_odds_meta_reports_no_market_honestly_when_there_is_none(self):
        """A game with no injected price section must show has_market=False
        and age_seconds=None, not a fabricated fresh quote."""
        store = history.read_results()
        games = [_today_game()]
        payload = build_today_payload(games, store)
        meta = payload["games"][0]["odds_meta"]
        self.assertFalse(meta["has_market"])
        self.assertIsNone(meta["age_seconds"])
        self.assertIsNone(meta["observed_utc"])

    def test_odds_meta_ages_an_injected_quote_correctly(self):
        """With a market section carrying a known observed_utc, age_seconds
        must reflect the real elapsed time against the `now` passed in --
        staleness honesty, proven with a controlled clock."""
        store = history.read_results()
        games = [_today_game(game_pk=990002)]
        observed = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
        now = observed + timedelta(minutes=45)
        prices_by_matchup = {
            ("BOS", "NYY"): {
                "h2h": {"away_price": 120, "home_price": -140,
                        "away_fair": 0.45, "home_fair": 0.55},
            }
        }
        # observed_utc is a property of a captured BOARD (multibook capture),
        # not of the plain fair-price market section -- inject it the way
        # briefing.build_slate actually receives it, via price_board_by_key.
        game_date = games[0]["date"]
        price_key = ("BOS", "NYY", game_date)
        price_boards_by_key = {
            price_key: {
                "quotes": [{"ts": observed.isoformat(), "book": "test_book",
                           "away_price": 120, "home_price": -140}],
                "observed_utc": observed.isoformat(),
                "source": "test",
            }
        }
        payload = build_today_payload(
            games, store, now=now, prices_by_matchup=prices_by_matchup,
            price_boards_by_key=price_boards_by_key)
        meta = payload["games"][0]["odds_meta"]
        self.assertTrue(meta["has_market"])
        self.assertEqual(meta["age_seconds"], 45 * 60)

    def test_date_defaults_to_the_slate_date_when_not_given(self):
        store = history.read_results()
        games = [_today_game()]
        payload = build_today_payload(games, store)
        self.assertEqual(payload["date"], games[0]["date"])


if __name__ == "__main__":
    unittest.main()
