"""src/analysis/gamepayload.py: pure JSON-payload builders, on fixture data.

Stdlib only, like gamepayload.py itself -- no store on disk, no network, and
(unlike tests/test_api_games.py) no FastAPI. Every entry here is built the
same way tests/test_report_dashboard.py and tests/test_api_today.py build
one: through the real domain path (src.pipeline.briefing.make_entry /
build_slate), so these tests exercise the actual dossier/synthesis pipeline
rather than a hand-rolled stand-in for its shape.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from src.analysis import gamepayload
from src.detect import dossier as dossier_mod
from src.pipeline import briefing, history


def _game(game_pk=880001, away="BOS", home="NYY", date="2026-08-31"):
    return {"game_pk": game_pk, "date": date, "away_team": away,
            "home_team": home, "venue": "Yankee Stadium",
            "start_time_utc": f"{date}T23:05:00Z"}


def _priced_game_entries(**kwargs):
    """One real entry with a full multi-book board on it, through
    build_slate -- the same fixture shape tests/test_api_today.py's
    odds-aging test builds, reused here for the market/price sections."""
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
    slate = briefing.build_slate(
        [game], store, prices_by_matchup=prices_by_matchup,
        price_boards_by_key=price_boards_by_key)
    return slate["games"], observed


class GameIdTests(unittest.TestCase):

    def test_stable_and_url_safe(self):
        # _game() carries a game_pk, so it is appended as the disambiguating
        # marker -- see test_never_empty_on_a_bare_game for the case with
        # neither a game_number nor a game_pk.
        game_id = gamepayload.game_id(_game())
        self.assertEqual(game_id, "BOS-NYY-2026-08-31-880001")
        # No character outside [A-Za-z0-9-], so it is safe to embed in a URL
        # or a JSON key without escaping.
        self.assertTrue(all(ch.isalnum() or ch == "-" for ch in game_id))

    def test_doubleheader_games_disambiguate(self):
        first = gamepayload.game_id(dict(_game(), game_number=1))
        second = gamepayload.game_id(dict(_game(), game_number=2))
        self.assertNotEqual(first, second)

    def test_never_empty_on_a_bare_game(self):
        self.assertTrue(gamepayload.game_id({}))


class FindEntriesTests(unittest.TestCase):

    def test_finds_by_clubs_case_insensitively(self):
        entries, _ = _priced_game_entries()
        found = gamepayload.find_entries(entries, "bos", "nyy")
        self.assertEqual(len(found), 1)

    def test_no_match_returns_empty_list(self):
        entries, _ = _priced_game_entries()
        self.assertEqual(gamepayload.find_entries(entries, "SEA", "TEX"), [])


class SlateListTests(unittest.TestCase):

    def test_shape_and_json_round_trip(self):
        entries, _ = _priced_game_entries()
        payload = gamepayload.build_slate_list(entries, date="2026-08-31")
        blob = json.dumps(payload)
        reloaded = json.loads(blob)
        self.assertEqual(reloaded["checked_games"], 1)
        row = reloaded["games"][0]
        self.assertEqual(row["game_id"], "BOS-NYY-2026-08-31-880001")
        self.assertEqual(row["away_team"], "BOS")
        self.assertIn("market_implied_consensus", row)
        self.assertIn("board_summary", row)
        self.assertIn("data_quality", row)

    def test_market_implied_consensus_is_named_honestly(self):
        """The field name is the evidence-rule guardrail itself: a
        de-vigged board number must never be relabelled as a read on the
        outcome."""
        entries, _ = _priced_game_entries()
        payload = gamepayload.build_slate_list(entries)
        consensus = payload["games"][0]["market_implied_consensus"]
        self.assertAlmostEqual(consensus["away_fair"], 0.438, places=3)
        self.assertAlmostEqual(consensus["home_fair"], 0.562, places=3)
        blob = json.dumps(payload).lower()
        self.assertNotIn("true_probability", blob)
        self.assertNotIn("win_probability", blob)

    def test_zero_games_is_an_honest_empty_slate_not_an_error(self):
        payload = gamepayload.build_slate_list([], date="2026-12-25")
        self.assertEqual(payload["checked_games"], 0)
        self.assertEqual(payload["games"], [])

    def test_board_summary_carries_staleness(self):
        entries, observed = _priced_game_entries()
        now = observed + timedelta(minutes=30)
        payload = gamepayload.build_slate_list(entries, now=now)
        summary = payload["games"][0]["board_summary"]
        self.assertTrue(summary["has_board"])
        self.assertEqual(summary["age_seconds"], 30 * 60)
        self.assertEqual(summary["books"], 7)

    def test_data_quality_flags_a_gap_with_its_reason(self):
        entries, _ = _priced_game_entries()
        payload = gamepayload.build_slate_list(entries)
        quality = payload["games"][0]["data_quality"]
        self.assertFalse(quality["has_lineups"])
        self.assertIn("lineups", quality["gaps"])


class QuickViewTests(unittest.TestCase):

    def test_shape_and_json_round_trip(self):
        entries, _ = _priced_game_entries()
        payload = gamepayload.build_quick_view(entries[0])
        blob = json.dumps(payload)
        reloaded = json.loads(blob)
        self.assertEqual(reloaded["game_id"], "BOS-NYY-2026-08-31-880001")
        self.assertIn("top_findings", reloaded)
        self.assertIn("price", reloaded)

    def test_price_section_reports_best_available_vs_consensus(self):
        entries, observed = _priced_game_entries()
        now = observed + timedelta(minutes=5)
        payload = gamepayload.build_quick_view(entries[0], now=now)
        price = payload["price"]
        self.assertTrue(price["available"])
        self.assertEqual(price["books"], 7)
        for side in ("away", "home"):
            self.assertIn("best_price", price["sides"][side])
            self.assertIn("consensus_probability", price["sides"][side])
        self.assertTrue(price["staleness"]["has_board"])
        self.assertEqual(price["staleness"]["age_seconds"], 5 * 60)

    def test_no_board_reports_unavailable_with_a_reason(self):
        game = _game(game_pk=880002)
        slate = briefing.build_slate([game], history.read_results())
        payload = gamepayload.build_quick_view(slate["games"][0])
        self.assertFalse(payload["price"]["available"])
        self.assertTrue(payload["price"]["reason"])

    def test_no_win_probability_or_ev_language_leaks_into_the_payload(self):
        entries, _ = _priced_game_entries()
        blob = json.dumps(gamepayload.build_quick_view(entries[0])).lower()
        for forbidden in ("win_probability", "win_prob", '"true_probability"',
                          '"ev"', '"edge"'):
            self.assertNotIn(forbidden, blob)

    def test_top_findings_carry_sample_and_evidence_label(self):
        """Whatever synthesis ranked for this entry reaches the quick view
        with its sample and evidence label intact -- read back, not
        recomputed (test_synthesis.py already proves the ranking itself)."""
        entries, _ = _priced_game_entries()
        entry = entries[0]
        expected = (entry.get("synthesis") or {}).get("items") or []
        payload = gamepayload.build_quick_view(entry)
        self.assertEqual(len(payload["top_findings"]), len(expected))
        for item, wire in zip(expected, payload["top_findings"]):
            self.assertEqual(wire["statement"], item["statement"])
            self.assertEqual(wire["evidence_label"], item["evidence_label"])
            self.assertEqual(wire["sample"], item["sample"])


class AdvancedViewTests(unittest.TestCase):

    def test_shape_and_json_round_trip(self):
        entries, _ = _priced_game_entries()
        payload = gamepayload.build_advanced_view(entries[0])
        blob = json.dumps(payload)
        reloaded = json.loads(blob)
        self.assertEqual(reloaded["game_id"], "BOS-NYY-2026-08-31-880001")
        self.assertIn("sections", reloaded)
        self.assertIn("gaps", reloaded)
        self.assertIn("market", reloaded["sections"])

    def test_absent_section_is_a_null_with_a_reason_never_fabricated(self):
        entries, _ = _priced_game_entries()
        payload = gamepayload.build_advanced_view(entries[0])
        self.assertNotIn("lineups", payload["sections"])
        self.assertIn("lineups", payload["gaps"])
        self.assertTrue(payload["gaps"]["lineups"])

    def test_findings_are_serialised_with_evidence_labels(self):
        entries, _ = _priced_game_entries()
        payload = gamepayload.build_advanced_view(entries[0])
        for finding in payload["findings"]:
            self.assertIn("evidence_label", finding)
            self.assertIn("sample", finding)


class ChangedItemsTests(unittest.TestCase):

    def test_quiet_slate_reports_checked_count_not_a_bare_empty_list(self):
        entries, _ = _priced_game_entries()
        payload = gamepayload.build_changed_items(entries, date="2026-08-31")
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["checked_games"], 1)
        self.assertTrue(payload["notes"])
        self.assertIn("Checked 1 game", payload["notes"][0])

    def test_zero_games_gets_no_manufactured_note(self):
        payload = gamepayload.build_changed_items([], date="2026-12-25")
        self.assertEqual(payload["checked_games"], 0)
        self.assertEqual(payload["notes"], [])

    def test_items_carry_a_timestamp_and_a_source_date(self):
        """Built directly against a dossier holding a synthetic what_changed
        section, rather than the real rosterwatch store, so this test does
        not depend on any watch data existing on disk."""
        dossier = dossier_mod.Dossier(_game())
        dossier.add("what_changed", {
            "cutoff": "2026-08-31",
            "not_an_edge": "descriptive only",
            "events": [{
                "class": "lineup_posted", "headline": "BOS: lineup posted",
                "tier": "MEDIUM", "tier_sentence": "relevance MEDIUM",
                "basis": [], "reasons": [], "seen_utc": "2026-08-31T16:00:00Z",
                "timing": "first seen at 2026-08-31T16:00:00Z",
                "inadmissible": False, "summary": "Lineup posted: MEDIUM.",
            }],
        })
        entry = briefing.make_entry(dossier)
        payload = gamepayload.build_changed_items([entry], date="2026-08-31")
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["seen_utc"], "2026-08-31T16:00:00Z")
        self.assertEqual(item["cutoff"], "2026-08-31")
        self.assertEqual(item["game_id"], "BOS-NYY-2026-08-31-880001")
        self.assertEqual(item["not_an_edge"], "descriptive only")

    def test_items_sorted_most_recent_first(self):
        dossier = dossier_mod.Dossier(_game())
        dossier.add("what_changed", {
            "cutoff": "2026-08-31", "not_an_edge": "x",
            "events": [
                {"class": "lineup_posted", "headline": "older",
                 "seen_utc": "2026-08-31T10:00:00Z", "basis": [],
                 "reasons": [], "timing": "", "tier": "MEDIUM",
                 "tier_sentence": "", "summary": ""},
                {"class": "lineup_posted", "headline": "newer",
                 "seen_utc": "2026-08-31T18:00:00Z", "basis": [],
                 "reasons": [], "timing": "", "tier": "MEDIUM",
                 "tier_sentence": "", "summary": ""},
            ],
        })
        entry = briefing.make_entry(dossier)
        payload = gamepayload.build_changed_items([entry])
        self.assertEqual([i["headline"] for i in payload["items"]],
                         ["newer", "older"])


if __name__ == "__main__":
    unittest.main()
