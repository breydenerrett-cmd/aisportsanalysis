"""The "What changed" section: roster events on the card they belong to.

Three things can go wrong here and all three are the same kind of wrong --
telling a reader something the briefing did not actually know, or knew about
a different game. Another slate's event on tonight's card, an event our
poller only saw after the stated information time, and an UNKNOWN tier that
renders as though it were a small one. Each gets a test.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.analysis import relevance
from src.detect import dossier as dossier_mod
from src.pipeline import briefing
from src.pipeline import rosterwatch
from src.report import dashboard

TODAY = "2026-08-31"
YESTERDAY = "2026-08-30"

TOR_GAME = {"away_team": "TOR", "home_team": "BOS", "date": TODAY,
            "game_pk": 11, "venue": "Fenway Park"}
CIN_GAME = {"away_team": "CIN", "home_team": "NYM", "date": TODAY,
            "game_pk": 22, "venue": "Citi Field"}
GAMES = [dict(TOR_GAME), dict(CIN_GAME)]

# A hand-built pre-cutoff index. Passing it keeps the test off the real pitch
# store: what is under test here is the wiring and the rendering, not the
# scoring, which tests/test_relevance.py pins from the store itself.
INDEX = {"cutoff": TODAY,
         "pitchers": {"900": {"pitches": 2400, "appearances": 30,
                              "starting_appearances": 28,
                              "pitches_per_start": 92.0,
                              "batters_faced": 620}},
         "batters": {"800": {"plate_appearances": 480, "games": 120}}}

MOVE = {"transaction_id": 7, "team": "TOR", "date": TODAY,
        "category": "optioned", "player_id": 900, "player": "A Pitcher",
        "description": "Toronto Blue Jays optioned RHP A Pitcher to Buffalo."}
UNKNOWN_MOVE = {"transaction_id": 8, "team": "TOR", "date": TODAY,
                "category": "recalled", "player_id": 999999,
                "player": "A Callup",
                "description": "Toronto Blue Jays recalled RHP A Callup."}

NOON = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def transaction_event(transaction_id, seen="2026-08-31T11:00:00+00:00",
                      start="2026-08-31T10:45:00+00:00"):
    return {"class": rosterwatch.TRANSACTION_SEEN,
            "transaction_id": transaction_id,
            "interval": (start, seen),
            "inadmissible": start is None,
            "detail": None}


def lineup_event(game_pk, side="away", seen="2026-08-31T11:30:00+00:00"):
    return {"class": rosterwatch.LINEUP_POSTED, "game_pk": game_pk,
            "interval": ("2026-08-31T11:15:00+00:00", seen),
            "inadmissible": False, "detail": {"side": side}}


def sections(events, transactions=None, information_time=NOON, games=None):
    return briefing.what_changed_by_pk(
        games or [dict(g) for g in GAMES], information_time=information_time,
        events=events, transactions=transactions or {}, index=INDEX)


class TestMatchedToTheRightGame(unittest.TestCase):

    def test_a_transaction_lands_only_on_its_own_clubs_game(self):
        out = sections([transaction_event(7)], {7: MOVE})
        self.assertEqual(list(out), [11])
        self.assertEqual(len(out[11]["events"]), 1)
        self.assertIn("Toronto", out[11]["events"][0]["headline"])

    def test_a_game_keyed_event_lands_only_on_that_game(self):
        out = sections([lineup_event(22)])
        self.assertEqual(list(out), [22])
        self.assertIn("CIN", out[22]["events"][0]["headline"])

    def test_yesterdays_move_never_reaches_todays_card(self):
        """Same club, different official date: roster history, not tonight."""
        stale = dict(MOVE, date=YESTERDAY)
        self.assertEqual(sections([transaction_event(7)], {7: stale}), {})

    def test_an_event_for_a_game_not_on_this_slate_is_dropped(self):
        self.assertEqual(sections([lineup_event(33)]), {})

    def test_a_transaction_with_no_parsed_record_reaches_no_card(self):
        """The watch store keeps only the id; an id names no club and no date,
        so there is no game it could honestly be attached to."""
        self.assertEqual(sections([transaction_event(7)], {}), {})


class TestPointInTime(unittest.TestCase):

    def test_an_event_seen_after_the_information_time_is_excluded(self):
        late = transaction_event(7, seen="2026-08-31T19:40:00+00:00",
                                 start="2026-08-31T19:25:00+00:00")
        self.assertEqual(sections([late], {7: MOVE}), {})

    def test_an_event_seen_before_it_is_included(self):
        out = sections([transaction_event(7)], {7: MOVE})
        self.assertEqual(out[11]["information_time"], NOON.isoformat())

    def test_the_cutoff_accepts_an_iso_string_information_time(self):
        out = sections([transaction_event(7)], {7: MOVE},
                       information_time="2026-08-31T12:00:00Z")
        self.assertEqual(list(out), [11])

    def test_an_event_with_no_end_stamp_is_treated_as_unseen(self):
        broken = dict(transaction_event(7), interval=(None, None))
        self.assertEqual(sections([broken], {7: MOVE}), {})


class TestHonestRendering(unittest.TestCase):

    def test_a_scored_event_carries_its_facts_with_denominators(self):
        event = sections([transaction_event(7)], {7: MOVE})[11]["events"][0]
        self.assertEqual(event["tier"], relevance.MEDIUM)  # optioned caps HIGH
        line = " ".join(event["basis"])
        self.assertIn("2400 pitches", line)
        self.assertIn("30 appearance(s)", line)

    def test_unknown_says_it_is_unknown_and_why(self):
        event = sections([transaction_event(8)],
                         {8: UNKNOWN_MOVE})[11]["events"][0]
        self.assertEqual(event["tier"], relevance.UNKNOWN)
        self.assertIn("impact unknown", event["tier_sentence"])
        self.assertIn("unknown, not low", event["tier_sentence"])

    def test_a_first_sighting_says_its_timing_is_unbounded(self):
        event = sections([transaction_event(7, start=None)],
                         {7: MOVE})[11]["events"][0]
        self.assertTrue(event["inadmissible"])
        self.assertIn("no earlier poll", event["timing"])

    def test_the_section_repeats_that_a_tier_is_not_an_edge(self):
        out = sections([transaction_event(7)], {7: MOVE})
        self.assertEqual(out[11]["not_an_edge"], relevance.NOT_AN_EDGE)


class TestTierSentenceAndBasis(unittest.TestCase):
    """The two rendering helpers, on scores rather than through the wiring."""

    def test_a_ranked_tier_renders_as_its_word(self):
        score = relevance.score_event(
            {"class": rosterwatch.LINEUP_POSTED, "detail": {"side": "away"}},
            TODAY, index=INDEX)
        self.assertEqual(relevance.tier_sentence(score), "relevance MEDIUM")
        self.assertEqual(relevance.basis_lines(score), [])

    def test_a_batter_line_names_the_slot_it_did_not_have(self):
        score = relevance.score_event(
            {"class": rosterwatch.HITTER_SCRATCH,
             "detail": {"side": "away", "removed": [800]}}, TODAY, index=INDEX)
        line = relevance.basis_lines(score)[0]
        self.assertIn("480 plate appearances over 120 game(s)", line)
        self.assertIn("lineup slot not supplied", line)

    def test_a_batter_line_names_the_slot_it_did_have(self):
        score = relevance.score_event(
            {"class": rosterwatch.HITTER_SCRATCH,
             "detail": {"side": "away", "removed": [800]}}, TODAY, index=INDEX,
            lineup=[800, 1, 2, 3, 4, 5, 6, 7, 8])
        self.assertIn("batting 1", relevance.basis_lines(score)[0])


class TestDossierAndPage(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "b.html"

    def build(self, events, transactions=None):
        return briefing.build_slate(
            [dict(g) for g in GAMES], None, detectors={},
            price_boards_by_key={}, price_improvement_by_key={},
            roster_events_by_pk=sections(events, transactions),
            information_time=NOON)

    def page(self, slate):
        dashboard.render(slate, self.path)
        return self.path.read_text(encoding="utf-8")

    def test_the_section_reaches_the_dossier_of_that_game_only(self):
        slate = self.build([transaction_event(7)], {7: MOVE})
        tor, cin = (entry["dossier"] for entry in slate["games"])
        self.assertTrue(tor.get("what_changed")["events"])
        self.assertIsNone(cin.get("what_changed"))

    def test_a_quiet_slate_renders_no_section_and_no_gap(self):
        slate = briefing.build_slate(
            [dict(g) for g in GAMES], None, detectors={},
            price_boards_by_key={}, price_improvement_by_key={},
            roster_events_by_pk={}, information_time=NOON)
        for entry in slate["games"]:
            self.assertNotIn("what_changed", entry["dossier"].sections)
            self.assertNotIn("what_changed", entry["dossier"].gaps)
        self.assertNotIn("What changed", self.page(slate))

    def test_the_page_shows_the_event_its_tier_and_its_facts(self):
        html = self.page(self.build([transaction_event(7)], {7: MOVE}))
        self.assertIn("What changed", html)
        self.assertIn("optioned RHP A Pitcher", html)
        self.assertIn("relevance MEDIUM", html)
        self.assertIn("2400 pitches", html)
        self.assertIn("not a prediction", html)

    def test_the_page_spells_out_an_unknown_tier(self):
        html = self.page(self.build([transaction_event(8)], {8: UNKNOWN_MOVE}))
        self.assertIn("impact unknown", html)
        self.assertNotIn("relevance UNKNOWN", html)

    def test_the_dossier_default_carries_no_what_changed_section(self):
        dossier = dossier_mod.build(dict(TOR_GAME), {})
        self.assertNotIn("what_changed", dossier.sections)
        self.assertNotIn("what_changed", dossier.gaps)


if __name__ == "__main__":
    unittest.main()
