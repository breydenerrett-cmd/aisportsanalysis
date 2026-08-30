"""Tests for the roster-news layer."""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import news
from src.providers import mlb_news


def _tx(identifier, date, to_team=None, from_team=None, type_desc="Status Change",
        description="", player="A Player", player_id=1):
    return {
        "id": identifier,
        "date": date,
        "effectiveDate": date,
        "typeDesc": type_desc,
        "description": description,
        "person": {"id": player_id, "fullName": player},
        "toTeam": to_team,
        "fromTeam": from_team,
    }


REDS = {"id": 113, "name": "Cincinnati Reds"}
METS = {"id": 121, "name": "New York Mets"}
# A Double-A affiliate that ends in its parent club's nickname. This is the case
# that broke name-based filtering.
SYRACUSE = {"id": 552, "name": "Syracuse Mets"}


class ClassifyTests(unittest.TestCase):
    def test_placed_on_the_injured_list(self):
        tx = _tx(1, "2026-08-27", REDS, description=(
            "Cincinnati Reds placed 3B Ke'Bryan Hayes on the 10-day injured "
            "list retroactive to August 27, 2026. Left groin strain."))
        self.assertEqual(mlb_news.classify(tx), mlb_news.IL_PLACEMENT)

    def test_activated_from_the_injured_list_is_the_opposite_fact(self):
        tx = _tx(2, "2026-08-27", METS, description=(
            "New York Mets activated LF Juan Soto from the 10-day injured list."))
        self.assertEqual(mlb_news.classify(tx), mlb_news.IL_ACTIVATION)

    def test_a_rehab_assignment_is_not_a_roster_move(self):
        tx = _tx(3, "2026-08-27", REDS, type_desc="Assigned", description=(
            "Toronto Blue Jays sent RHP Jameson Taillon on a rehab assignment "
            "to Buffalo Bisons."))
        self.assertEqual(mlb_news.classify(tx), mlb_news.REHAB)
        self.assertNotIn(mlb_news.REHAB, mlb_news.NOTABLE)

    def test_recalled_and_optioned_come_from_the_type(self):
        self.assertEqual(
            mlb_news.classify(_tx(4, "2026-08-27", REDS, type_desc="Recalled")),
            mlb_news.RECALLED)
        self.assertEqual(
            mlb_news.classify(_tx(5, "2026-08-27", REDS, type_desc="Optioned")),
            mlb_news.OPTIONED)


class ClubFilterTests(unittest.TestCase):
    def test_a_major_league_club_resolves(self):
        record = mlb_news.parse(_tx(1, "2026-08-27", REDS, description="x. y."))
        self.assertEqual(record["team"], "CIN")

    def test_an_affiliate_sharing_its_parents_nickname_is_rejected(self):
        """Syracuse Mets is Triple-A. Name matching filed its moves under NYM."""
        record = mlb_news.parse(_tx(2, "2026-08-27", SYRACUSE))
        self.assertIsNone(record)

    def test_a_move_between_a_club_and_its_affiliate_keeps_the_club(self):
        record = mlb_news.parse(
            _tx(3, "2026-08-27", SYRACUSE, from_team=METS, type_desc="Optioned",
                description="New York Mets optioned RHP X to Syracuse Mets."))
        self.assertEqual(record["team"], "NYM")

    def test_a_transaction_with_no_date_is_dropped(self):
        tx = _tx(4, None, REDS)
        tx["effectiveDate"] = None
        self.assertIsNone(mlb_news.parse(tx))


class InjuryNoteTests(unittest.TestCase):
    def test_the_diagnosis_is_extracted(self):
        record = mlb_news.parse(_tx(1, "2026-08-27", REDS, description=(
            "Cincinnati Reds placed 3B Ke'Bryan Hayes on the 10-day injured "
            "list. Left groin strain.")))
        self.assertEqual(record["injury_note"], "Left groin strain")

    def test_a_retroactive_clause_is_not_a_diagnosis(self):
        record = mlb_news.parse(_tx(2, "2026-08-27", REDS, description=(
            "Cincinnati Reds placed 3B X on the 10-day injured list "
            "retroactive to August 27, 2026.")))
        self.assertIsNone(record["injury_note"])


class PointInTimeTests(unittest.TestCase):
    """The guarantee the whole store exists to provide."""

    def _rows(self):
        return [
            {"transaction_id": 1, "date": "2026-08-20", "team": "CIN",
             "category": mlb_news.IL_PLACEMENT, "player_id": 10,
             "description": "before the window"},
            {"transaction_id": 2, "date": "2026-08-28", "team": "CIN",
             "category": mlb_news.IL_PLACEMENT, "player_id": 11,
             "description": "inside the window"},
            {"transaction_id": 3, "date": "2026-08-30", "team": "CIN",
             "category": mlb_news.IL_PLACEMENT, "player_id": 12,
             "description": "the day of the game"},
            {"transaction_id": 4, "date": "2026-09-02", "team": "CIN",
             "category": mlb_news.IL_PLACEMENT, "player_id": 13,
             "description": "after the game"},
        ]

    def test_news_from_after_the_game_can_never_reach_it(self):
        got = news.for_team(self._rows(), "CIN", "2026-08-30")
        self.assertNotIn("after the game", [r["description"] for r in got])

    def test_a_move_dated_the_day_of_the_game_is_excluded(self):
        """MLB dates a move by the day it took effect, not the minute announced."""
        got = news.for_team(self._rows(), "CIN", "2026-08-30")
        self.assertNotIn("the day of the game", [r["description"] for r in got])

    def test_a_move_older_than_the_window_falls_out(self):
        got = news.for_team(self._rows(), "CIN", "2026-08-30", window_days=5)
        self.assertEqual([r["description"] for r in got], ["inside the window"])

    def test_the_window_is_inclusive_at_its_far_edge(self):
        got = news.for_team(self._rows(), "CIN", "2026-08-30", window_days=10)
        self.assertIn("before the window", [r["description"] for r in got])

    def test_repeated_filings_of_one_move_appear_once(self):
        """The feed genuinely files some moves twice under different ids."""
        rows = self._rows()
        duplicate = dict(rows[1], transaction_id=99)
        got = news.for_team(rows + [duplicate], "CIN", "2026-08-29")
        same_move = [r for r in got if r["player_id"] == 11]
        self.assertEqual(len(same_move), 1)

    def test_only_notable_categories_surface(self):
        rows = [{"transaction_id": 1, "date": "2026-08-28", "team": "CIN",
                 "category": mlb_news.REHAB, "player_id": 10,
                 "description": "rehab"}]
        self.assertEqual(news.for_team(rows, "CIN", "2026-08-30"), [])


class StoreTests(unittest.TestCase):
    def test_reading_a_missing_store_is_empty_not_an_error(self):
        self.assertEqual(news.read("does/not/exist.jsonl"), [])

    def test_a_corrupt_line_costs_one_row_not_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tx.jsonl"
            path.write_text(
                json.dumps({"transaction_id": 1, "date": "2026-08-01"}) + "\n"
                + "{not json\n"
                + json.dumps({"transaction_id": 2, "date": "2026-08-02"}) + "\n",
                encoding="utf-8")
            self.assertEqual(len(news.read(path)), 2)


class SentenceTests(unittest.TestCase):
    def test_the_retroactive_clause_is_trimmed_for_the_reader(self):
        row = {"description": ("Cincinnati Reds placed 3B X on the 10-day "
                               "injured list retroactive to August 27, 2026. "
                               "Left groin strain.")}
        text = news.sentence(row)
        self.assertNotIn("retroactive", text)
        self.assertIn("Left groin strain", text)

    def test_a_row_with_no_description_still_says_something(self):
        row = {"player": "A Player", "category": "il_placement"}
        self.assertIn("A Player", news.sentence(row))


class AttachTests(unittest.TestCase):
    def test_a_raw_game_dict_is_understood(self):
        game = {"away_team": "CIN", "home_team": "NYM"}
        rows = [{"transaction_id": 1, "date": "2026-08-28", "team": "CIN",
                 "category": mlb_news.IL_PLACEMENT, "player_id": 10,
                 "description": "Cincinnati Reds placed X on the IL."}]
        section = news.attach(game, rows, "2026-08-30")
        self.assertEqual(len(section["teams"]["CIN"]), 1)
        self.assertEqual(section["teams"]["NYM"], [])
        self.assertIsNone(section["reason"])

    def test_a_quiet_stretch_gives_a_reason_rather_than_silence(self):
        game = {"away_team": "CIN", "home_team": "NYM"}
        section = news.attach(game, [], "2026-08-30")
        self.assertIsNotNone(section["reason"])

    def test_each_row_carries_a_reader_ready_sentence(self):
        game = {"away_team": "CIN", "home_team": "NYM"}
        rows = [{"transaction_id": 1, "date": "2026-08-28", "team": "CIN",
                 "category": mlb_news.IL_PLACEMENT, "player_id": 10,
                 "description": "Cincinnati Reds placed X on the IL."}]
        section = news.attach(game, rows, "2026-08-30")
        self.assertIn("sentence", section["teams"]["CIN"][0])


if __name__ == "__main__":
    unittest.main()
