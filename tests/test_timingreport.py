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
    # umpirewatch.events is mocked here too, for the same reason
    # rosterwatch.events is: every call in this file must be hermetic
    # against the real data/watch stores, umpirewatch's included now that
    # timingreport folds it into the same event stream (see
    # src/research/timingreport.py's "THE CLASS LIST IS DATA-DRIVEN" note).
    with mock.patch.object(timingreport.rosterwatch, "events",
                           return_value=events), \
         mock.patch.object(timingreport.umpirewatch, "events",
                           return_value=[]):
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

    def test_a_transaction_maps_to_the_clubs_next_game(self):
        pk = timingreport._next_game_for(
            "CIN", _event(end="2026-08-31T20:00:00+00:00"), GAMES)
        self.assertEqual(pk, "100")
        none = timingreport._next_game_for(
            "CIN", _event(end="2026-09-05T00:00:00+00:00"), GAMES)
        self.assertIsNone(none)

    def test_a_west_coast_board_is_not_filed_under_tomorrow(self):
        """commence_time is UTC; MLB files the game under its Eastern date."""
        rows = [_mb_row(f"b{i}", away="San Diego Padres",
                        home="Los Angeles Dodgers",
                        ts="2026-09-01T01:30:00Z") for i in range(6)]
        for row in rows:
            row["commence_time"] = "2026-09-01T02:10:00Z"
        self.assertEqual(len(timingreport._quotes_for_game(rows, GAMES["200"])),
                         6)

    def test_the_two_clubs_spelt_differently_still_match(self):
        """The schedule says ATH/AZ where the odds feed resolves OAK/ARI."""
        game = {"game_pk": "300", "date": "2026-08-31", "away_team": "AZ",
                "home_team": "ATH", "start_time_utc": "2026-08-31T23:10:00Z"}
        rows = [_mb_row("b1", away="Arizona Diamondbacks", home="Athletics")]
        self.assertEqual(len(timingreport._quotes_for_game(rows, game)), 1)


class MappabilityTests(unittest.TestCase):
    """Unmappable is not one condition, and the report must not say it is."""

    def test_tonights_game_is_awaiting_settlement_not_broken(self):
        games = {k: v for k, v in GAMES.items() if k == "100"}
        with mock.patch.object(timingreport.rosterwatch, "events",
                               return_value=[_event(
                                   game_pk="999",
                                   end="2026-09-02T20:00:00+00:00")]), \
             mock.patch.object(timingreport.umpirewatch, "events",
                               return_value=[]):
            result = timingreport.report(multibook_rows=[], games=games,
                                         transactions=[])
        entry = result["classes"]["starter_scratch"]
        self.assertEqual(entry["unmappable"],
                         {timingreport.NOT_YET_PLAYED: 1})
        self.assertEqual(result["settled_through"], "2026-08-31")

    def test_a_missing_game_on_a_settled_date_is_named_a_defect(self):
        entry = _report([_event(game_pk="999")])["classes"]["starter_scratch"]
        self.assertEqual(entry["unmappable"], {timingreport.GAME_MISSING: 1})

    def test_the_report_distinguishes_the_two_in_its_text(self):
        events = [_event(game_pk="999"),
                  _event(game_pk="998", end="2026-09-02T20:00:00+00:00")]
        text = timingreport.format_report(_report(events))
        self.assertIn(timingreport.NOT_YET_PLAYED, text)
        self.assertIn(timingreport.GAME_MISSING, text)
        self.assertIn("settled through 2026-08-31", text)

    def test_a_transaction_row_written_now_maps_through_its_own_club(self):
        """No join to the historical store: the watch row carries the club."""
        event = {"class": "transaction_first_seen", "transaction_id": 5,
                 "team": "CIN", "team_recorded": True,
                 "interval": ("2026-08-31T19:45:00+00:00",
                              "2026-08-31T20:00:00+00:00"),
                 "inadmissible": False, "detail": None}
        entry = _report([event])["classes"]["transaction_first_seen"]
        self.assertEqual(entry["unmappable"], {})

    def test_a_row_written_before_club_capture_is_reported_not_dropped(self):
        event = {"class": "transaction_first_seen", "transaction_id": 5,
                 "team": None, "team_recorded": False,
                 "interval": ("2026-08-31T19:45:00+00:00",
                              "2026-08-31T20:00:00+00:00"),
                 "inadmissible": False, "detail": None}
        entry = _report([event])["classes"]["transaction_first_seen"]
        self.assertEqual(entry["events"], 1)
        self.assertEqual(entry["admissible"], 1)
        self.assertEqual(entry["unmappable"],
                         {timingreport.TEAM_NOT_RECORDED: 1})

    def test_a_recorded_but_empty_club_is_a_different_answer(self):
        event = {"class": "transaction_first_seen", "transaction_id": 5,
                 "team": None, "team_recorded": True,
                 "interval": ("2026-08-31T19:45:00+00:00",
                              "2026-08-31T20:00:00+00:00"),
                 "inadmissible": False, "detail": None}
        entry = _report([event])["classes"]["transaction_first_seen"]
        self.assertEqual(entry["unmappable"], {timingreport.TEAM_UNKNOWN: 1})

    def test_a_mapped_event_with_too_thin_a_board_is_excluded_not_unmappable(self):
        rows = [_mb_row(f"b{i}") for i in range(3)]
        entry = _report([_event()], rows)["classes"]["starter_scratch"]
        self.assertEqual(entry["unmappable"], {})
        self.assertEqual(entry["measurable"], 0)
        self.assertEqual(sum(entry["excluded"].values()), 1)


class FormatTests(unittest.TestCase):
    def test_an_empty_watch_says_young_not_broken(self):
        text = timingreport.format_report(_report([]))
        self.assertIn("young", text)


class UmpireClassHookTests(unittest.TestCase):
    """docs/RESEARCH_V3_UMPIRE_CLASS.md's 5th class, folded in through the
    same data-driven mechanism as rosterwatch's four: `report()` has no
    hard-coded roster of class names to update, so admitting the class is
    just a second events source merged into the same stream.
    """

    @staticmethod
    def _umpire_event(inadmissible, end="2026-08-31T20:00:00+00:00",
                      game_pk="100"):
        return {"class": "umpire_crew_revealed", "game_pk": game_pk,
                "interval": (None if inadmissible else
                            "2026-08-31T19:45:00+00:00", end),
                "inadmissible": inadmissible,
                "detail": {"home_plate_umpire": "Ump1", "crew_size": 4}}

    def test_zero_events_means_the_class_is_not_in_the_report_yet(self):
        # Exactly like any of the other four classes on their first day:
        # a class with no events at all does not occupy a slot -- there is
        # no roster for it to occupy one in.
        self.assertNotIn("umpire_crew_revealed", _report([])["classes"])

    def test_an_inadmissible_first_sighting_reports_accumulating_0_of_30(self):
        with mock.patch.object(timingreport.rosterwatch, "events",
                               return_value=[]), \
             mock.patch.object(timingreport.umpirewatch, "events",
                               return_value=[self._umpire_event(True)]):
            result = timingreport.report(multibook_rows=[], games=GAMES,
                                         transactions=[])
        entry = result["classes"]["umpire_crew_revealed"]
        self.assertEqual(entry["events"], 1)
        self.assertEqual(entry["admissible"], 0)
        self.assertIn("accumulating", entry["status"])
        self.assertIn("0 of 30", entry["status"])
        self.assertNotIn("response_table", entry)

    def test_admissible_umpire_events_accumulate_toward_the_same_30_floor(self):
        events = [self._umpire_event(False) for _ in range(29)]
        with mock.patch.object(timingreport.rosterwatch, "events",
                               return_value=[]), \
             mock.patch.object(timingreport.umpirewatch, "events",
                               return_value=events):
            result = timingreport.report(multibook_rows=[], games=GAMES,
                                         transactions=[])
        entry = result["classes"]["umpire_crew_revealed"]
        self.assertEqual(entry["admissible"], 29)
        self.assertIn("accumulating", entry["status"])
        self.assertNotIn("response_table", entry)

    def test_reaching_the_floor_produces_the_pre_registered_tables(self):
        rows = [_mb_row(f"b{i}") for i in range(8)]
        events = [self._umpire_event(False) for _ in range(30)]
        with mock.patch.object(timingreport.rosterwatch, "events",
                               return_value=[]), \
             mock.patch.object(timingreport.umpirewatch, "events",
                               return_value=events):
            result = timingreport.report(multibook_rows=rows, games=GAMES,
                                         transactions=[])
        entry = result["classes"]["umpire_crew_revealed"]
        self.assertEqual(entry["status"],
                         "at floor: pre-registered tables follow")
        self.assertIn("response_table", entry)

    def test_it_coexists_with_rosterwatch_classes_in_the_same_report(self):
        with mock.patch.object(timingreport.rosterwatch, "events",
                               return_value=[_event()]), \
             mock.patch.object(timingreport.umpirewatch, "events",
                               return_value=[self._umpire_event(True)]):
            result = timingreport.report(multibook_rows=[], games=GAMES,
                                         transactions=[])
        self.assertIn("starter_scratch", result["classes"])
        self.assertIn("umpire_crew_revealed", result["classes"])


if __name__ == "__main__":
    unittest.main()
