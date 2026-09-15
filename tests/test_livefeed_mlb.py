"""Tests for src/pipeline/livefeed_mlb.py"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline import livefeed_mlb


class TestLivefeedMLB(unittest.TestCase):
    """MLB live game-state poller tests."""

    def setUp(self):
        """Set up a temporary directory for test data."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.live_dir = Path(self.temp_dir.name)

    def tearDown(self):
        """Clean up the temporary directory."""
        self.temp_dir.cleanup()

    def test_live_game_writes_one_row_with_mapped_fields(self):
        """A Live game writes one row with correct field mappings."""
        # Clock: 2025-06-15 12:00:00 UTC = 2025-06-15 08:00:00 ET
        clock = lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        schedule = [
            _make_game(
                game_pk=123456,
                abstract_state="Live",
                detailed_state="In Play",
                home_name="New York Yankees",
                away_name="Boston Red Sox",
                home_prob_id=111111,
                away_prob_id=222222,
            ),
        ]

        linescore = _make_linescore(
            current_inning=3,
            inning_half="Top",
            inning_state="Top",
            outs=2,
            balls=1,
            strikes=2,
            batter_id=333333,
            pitcher_id=444444,
            first_runner_id=555555,
            second_runner_id=None,
            third_runner_id=None,
            home_runs=2,
            away_runs=1,
            home_hits=7,
            away_hits=5,
        )

        def fetch_schedule(date, timeout=None):
            return schedule

        def fetch_linescore(game_pk, timeout=None):
            return linescore

        report = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=fetch_schedule,
            fetch_linescore=fetch_linescore,
            clock=clock,
            timeout=20,
        )

        # Check report.
        self.assertEqual(report["date"], "2025-06-15")
        self.assertEqual(report["live_games"], 1)
        self.assertEqual(report["rows_written"], 1)
        self.assertEqual(report["finals_written"], 0)
        self.assertEqual(len(report["errors"]), 0)

        # Check the written row.
        rows = livefeed_mlb.read_states("2025-06-15", live_dir=self.live_dir)
        self.assertEqual(len(rows), 1)
        row = rows[0]

        self.assertEqual(row["game_pk"], 123456)
        self.assertEqual(row["status"], "Live")
        self.assertEqual(row["detailed_state"], "In Play")
        self.assertEqual(row["inning"], 3)
        self.assertEqual(row["half"], "top")  # lowercased
        self.assertEqual(row["inning_state"], "Top")
        self.assertEqual(row["outs"], 2)
        self.assertEqual(row["balls"], 1)
        self.assertEqual(row["strikes"], 2)
        self.assertEqual(row["batter_id"], 333333)
        self.assertEqual(row["pitcher_id"], 444444)
        self.assertEqual(row["runners"]["first"], 555555)
        self.assertEqual(row["runners"]["second"], None)
        self.assertEqual(row["runners"]["third"], None)
        self.assertEqual(row["home_runs"], 2)
        self.assertEqual(row["away_runs"], 1)
        self.assertEqual(row["home_hits"], 7)
        self.assertEqual(row["away_hits"], 5)
        self.assertEqual(row["home_probable_pitcher_id"], 111111)
        self.assertEqual(row["away_probable_pitcher_id"], 222222)
        self.assertEqual(row["home_team"], "New York Yankees")
        self.assertEqual(row["away_team"], "Boston Red Sox")
        self.assertEqual(row["sport"], "mlb")

    def test_state_id_is_16_hex_chars(self):
        """state_id is exactly 16 hex characters."""
        clock = lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        schedule = [_make_game(game_pk=123456, abstract_state="Live")]
        linescore = _make_linescore()

        report = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule,
            fetch_linescore=lambda game_pk, timeout=None: linescore,
            clock=clock,
        )

        rows = livefeed_mlb.read_states("2025-06-15", live_dir=self.live_dir)
        state_id = rows[0]["state_id"]

        self.assertEqual(len(state_id), 16)
        # Check that it's valid hex.
        int(state_id, 16)

    def test_state_id_differs_across_polls(self):
        """state_id changes when observed_utc is different."""
        schedule = [_make_game(game_pk=123456, abstract_state="Live")]
        linescore = _make_linescore()

        # First poll at 12:00 UTC.
        clock1 = lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule,
            fetch_linescore=lambda game_pk, timeout=None: linescore,
            clock=clock1,
        )

        # Second poll at 12:05 UTC.
        clock2 = lambda: datetime(2025, 6, 15, 12, 5, 0, tzinfo=timezone.utc)
        livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule,
            fetch_linescore=lambda game_pk, timeout=None: linescore,
            clock=clock2,
        )

        rows = livefeed_mlb.read_states("2025-06-15", live_dir=self.live_dir)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["state_id"], rows[1]["state_id"])

    def test_preview_game_writes_nothing(self):
        """A Preview game writes no row."""
        clock = lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        schedule = [_make_game(game_pk=123456, abstract_state="Preview")]

        report = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule,
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(),
            clock=clock,
        )

        self.assertEqual(report["live_games"], 0)
        self.assertEqual(report["rows_written"], 0)
        self.assertEqual(report["finals_written"], 0)

        rows = livefeed_mlb.read_states("2025-06-15", live_dir=self.live_dir)
        self.assertEqual(len(rows), 0)

    def test_final_game_writes_exactly_one_final_row_across_two_polls(self):
        """A Final game writes exactly one final row on first observation."""
        clock = lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        schedule_live = [
            _make_game(
                game_pk=123456,
                abstract_state="Live",
                home_runs=None,
                away_runs=None,
            ),
        ]

        schedule_final = [
            _make_game(
                game_pk=123456,
                abstract_state="Final",
                detailed_state="Final",
                home_runs=3,
                away_runs=2,
            ),
        ]

        # First poll: game is Live, writes one row.
        report1 = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule_live,
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(),
            clock=clock,
        )

        self.assertEqual(report1["rows_written"], 1)
        self.assertEqual(report1["finals_written"], 0)

        # Second poll: game is Final, writes one final row (no live row).
        report2 = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule_final,
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(),
            clock=clock,
        )

        self.assertEqual(report2["rows_written"], 0)
        self.assertEqual(report2["finals_written"], 1)

        rows = livefeed_mlb.read_states("2025-06-15", live_dir=self.live_dir)
        self.assertEqual(len(rows), 2)

        # First row is Live.
        self.assertEqual(rows[0]["status"], "Live")
        # Second row is Final.
        self.assertEqual(rows[1]["status"], "Final")
        self.assertEqual(rows[1]["home_runs"], 3)
        self.assertEqual(rows[1]["away_runs"], 2)

        # Third poll: game is still Final, but last row is already Final,
        # so no new row is written.
        report3 = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule_final,
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(),
            clock=clock,
        )

        self.assertEqual(report3["rows_written"], 0)
        self.assertEqual(report3["finals_written"], 0)

        rows = livefeed_mlb.read_states("2025-06-15", live_dir=self.live_dir)
        self.assertEqual(len(rows), 2)  # Still only 2 rows.

    def test_fetch_linescore_error_leaves_other_game_written_and_lists_error(self):
        """When fetch_linescore raises, the error is recorded and other games proceed."""
        clock = lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        schedule = [
            _make_game(game_pk=111111, abstract_state="Live"),
            _make_game(game_pk=222222, abstract_state="Live"),
        ]

        def fetch_linescore(game_pk, timeout=None):
            if game_pk == 111111:
                raise RuntimeError("Network error")
            return _make_linescore()

        report = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule,
            fetch_linescore=fetch_linescore,
            clock=clock,
        )

        # First game failed, second succeeded.
        self.assertEqual(report["rows_written"], 1)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["errors"][0]["source"], "linescore")
        self.assertEqual(report["errors"][0]["game_pk"], 111111)

        rows = livefeed_mlb.read_states("2025-06-15", live_dir=self.live_dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_pk"], 222222)

    def test_latest_states_returns_newest_row_per_game(self):
        """latest_states returns the newest row for each game."""
        clock1 = lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        clock2 = lambda: datetime(2025, 6, 15, 12, 5, 0, tzinfo=timezone.utc)

        schedule = [
            _make_game(game_pk=111111, abstract_state="Live"),
            _make_game(game_pk=222222, abstract_state="Live"),
        ]

        # First poll: both games.
        livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule,
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(
                batter_id=111 if game_pk == 111111 else 222
            ),
            clock=clock1,
        )

        # Second poll: only game 111111.
        livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: [schedule[0]],
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(
                batter_id=333
            ),
            clock=clock2,
        )

        latest = livefeed_mlb.latest_states("2025-06-15", live_dir=self.live_dir)

        # Game 111111 should have the newest row (batter_id=333).
        self.assertIn(111111, latest)
        self.assertEqual(latest[111111]["batter_id"], 333)

        # Game 222222 should have the only row (batter_id=222).
        self.assertIn(222222, latest)
        self.assertEqual(latest[222222]["batter_id"], 222)

    def test_date_defaults_to_et_date_of_clock(self):
        """game_date defaults to the ET date of clock()."""
        # 2025-06-15 08:00 ET = 2025-06-15 12:00 UTC
        clock = lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        schedule = [_make_game(game_pk=123456, abstract_state="Live")]

        livefeed_mlb.poll(
            game_date=None,  # Should default to ET date.
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: (
                schedule if date == "2025-06-15" else []
            ),
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(),
            clock=clock,
        )

        report = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=lambda date, timeout=None: schedule,
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(),
            clock=clock,
        )

        self.assertEqual(report["date"], "2025-06-15")

    def test_03_00z_clock_is_previous_et_date(self):
        """A 03:00 UTC clock (23:00 ET previous day) uses the previous ET date."""
        # 2025-06-15 03:00 UTC = 2025-06-14 23:00 ET (previous day)
        clock = lambda: datetime(2025, 6, 15, 3, 0, 0, tzinfo=timezone.utc)

        schedule = [_make_game(game_pk=123456, abstract_state="Live")]

        def fetch_schedule(date, timeout=None):
            return schedule if date == "2025-06-14" else []

        report = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=fetch_schedule,
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(),
            clock=clock,
        )

        self.assertEqual(report["date"], "2025-06-14")

    def test_is_final_returns_true_for_final_status(self):
        """is_final returns True when status is Final."""
        row_live = {"status": "Live"}
        row_final = {"status": "Final"}

        self.assertFalse(livefeed_mlb.is_final(row_live))
        self.assertTrue(livefeed_mlb.is_final(row_final))

    def test_read_states_returns_empty_list_for_missing_file(self):
        """read_states returns an empty list when the file doesn't exist."""
        states = livefeed_mlb.read_states("2025-06-15", live_dir=self.live_dir)
        self.assertEqual(states, [])

    def test_network_error_in_schedule_fetch_records_error_and_returns(self):
        """A schedule fetch error is recorded and the poll returns with no games."""
        def fetch_schedule(date, timeout=None):
            raise RuntimeError("Network unreachable")

        report = livefeed_mlb.poll(
            game_date=None,
            live_dir=self.live_dir,
            fetch_schedule=fetch_schedule,
            fetch_linescore=lambda game_pk, timeout=None: _make_linescore(),
            clock=lambda: datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["errors"][0]["source"], "schedule")
        self.assertEqual(report["live_games"], 0)
        self.assertEqual(report["rows_written"], 0)


# --- Fixtures ---

def _make_game(game_pk=123456, abstract_state="Preview", detailed_state=None,
               home_name=None, away_name=None, home_prob_id=None,
               away_prob_id=None, home_runs=None, away_runs=None):
    """Fixture: one game record."""
    return {
        "gamePk": game_pk,
        "officialDate": "2025-06-15",
        "gameDate": "2025-06-15T12:00:00Z",
        "status": {
            "abstractGameState": abstract_state,
            "detailedState": detailed_state or abstract_state,
        },
        "teams": {
            "home": {
                "team": {
                    "id": 147,
                    "name": home_name or "Home Team",
                },
                "score": home_runs,
                "probablePitcher": {
                    "id": home_prob_id,
                } if home_prob_id else {},
            },
            "away": {
                "team": {
                    "id": 111,
                    "name": away_name or "Away Team",
                },
                "score": away_runs,
                "probablePitcher": {
                    "id": away_prob_id,
                } if away_prob_id else {},
            },
        },
    }


def _make_linescore(current_inning=None, inning_half=None, inning_state=None,
                   outs=None, balls=None, strikes=None, batter_id=None,
                   pitcher_id=None, first_runner_id=None, second_runner_id=None,
                   third_runner_id=None, home_runs=None, away_runs=None,
                   home_hits=None, away_hits=None):
    """Fixture: one linescore record."""
    return {
        "currentInning": current_inning,
        "inningHalf": inning_half,
        "inningState": inning_state,
        "outs": outs,
        "balls": balls,
        "strikes": strikes,
        "offense": {
            "batter": {"id": batter_id} if batter_id else {},
            "first": {"id": first_runner_id} if first_runner_id else {},
            "second": {"id": second_runner_id} if second_runner_id else {},
            "third": {"id": third_runner_id} if third_runner_id else {},
        },
        "defense": {
            "pitcher": {"id": pitcher_id} if pitcher_id else {},
        },
        "teams": {
            "home": {
                "runs": home_runs,
                "hits": home_hits,
            },
            "away": {
                "runs": away_runs,
                "hits": away_hits,
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
