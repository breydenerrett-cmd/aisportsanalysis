"""The V3 timing report: the floor is mechanical, joins are per-game."""

import unittest
from unittest import mock

from src.research import timingreport


def _event(cls="starter_scratch", game_pk="100", inadmissible=False,
           end="2026-08-31T20:00:00+00:00"):
    return {"class": cls, "game_pk": game_pk,
            "interval": ("2026-08-31T19:45:00+00:00", end),
            "inadmissible": inadmissible, "detail": {}}


GAMES = {"100": {"game_pk": "100", "date": "2026-08-31",
                 "away_team": "CIN", "home_team": "NYM",
                 "start_time_utc": "2026-08-31T23:10:00Z"},
         "200": {"game_pk": "200", "date": "2026-08-31",
                 "away_team": "SD", "home_team": "LAD",
                 "start_time_utc": "2026-09-01T02:10:00Z"}}


def _mb_row(book, away="Cincinnati Reds", home="New York Mets",
            ts="2026-08-31T19:30:00Z"):
    return {"observed_utc": ts, "event_id": "e", "book": book,
            "commence_time": "2026-08-31T23:10:00Z",
            "away_team": away, "home_team": home,
            "book_last_update": ts, "away_price": -110, "home_price": -110}


def _report(events, rows=None):
    with mock.patch.object(timingreport.rosterwatch, "events",
                           return_value=events):
        return timingreport.report(multibook_rows=rows or [], games=GAMES,
                                   transactions=[])


class FloorTests(unittest.TestCase):
    def test_below_the_floor_no_table_exists_anywhere_in_the_output(self):
        result = _report([_event() for _ in range(29)])
        entry = result["classes"]["starter_scratch"]
        self.assertIn("accumulating", entry["status"])
        self.assertNotIn("response_table", entry)
        self.assertNotIn("measured", entry)

    def test_inadmissible_events_count_toward_nothing_but_the_event_count(self):
        events = [_event(inadmissible=True) for _ in range(40)]
        entry = _report(events)["classes"]["starter_scratch"]
        self.assertEqual(entry["events"], 40)
        self.assertEqual(entry["admissible"], 0)
        self.assertIn("accumulating", entry["status"])

    def test_at_the_floor_the_pre_registered_tables_appear(self):
        rows = [_mb_row(f"b{i}") for i in range(8)]
        events = [_event() for _ in range(30)]
        entry = _report(events, rows)["classes"]["starter_scratch"]
        self.assertEqual(entry["status"],
                         "at floor: pre-registered tables follow")
        self.assertIn("response_table", entry)


class JoinTests(unittest.TestCase):
    def test_another_games_board_never_reaches_the_measurement(self):
        """A Padres board on the same date must not price a Reds event."""
        rows = ([_mb_row(f"b{i}") for i in range(6)]
                + [_mb_row(f"other{i}", away="San Diego Padres",
                           home="Los Angeles Dodgers") for i in range(6)])
        quotes = timingreport._quotes_for_game(rows, GAMES["100"])
        self.assertEqual(len(quotes), 6)
        self.assertTrue(all(q["book"].startswith("b") for q in quotes))

    def test_an_unmappable_event_is_counted_with_its_reason(self):
        events = [_event(game_pk="999")]
        entry = _report(events)["classes"]["starter_scratch"]
        self.assertEqual(entry["unmappable"],
                         {"game not in results store": 1})

    def test_a_transaction_maps_to_the_clubs_next_game(self):
        pk = timingreport._next_game_for(
            "CIN", _event(end="2026-08-31T20:00:00+00:00"), GAMES)
        self.assertEqual(pk, "100")
        none = timingreport._next_game_for(
            "CIN", _event(end="2026-09-05T00:00:00+00:00"), GAMES)
        self.assertIsNone(none)


class FormatTests(unittest.TestCase):
    def test_an_empty_watch_says_young_not_broken(self):
        text = timingreport.format_report(_report([]))
        self.assertIn("young", text)


if __name__ == "__main__":
    unittest.main()
