"""Behavioural regression, through the real daily-loop entry point
(`src.cli.cmd_daily` -> its step-3 closure `do_pitchers`), for the
2026-09-22 "0 pitchers fetched" incident.

Both arms below call the ACTUAL `src.cli.cmd_daily` -- not a hand-rolled
call to `build_log_store` -- with the same injected provider fixture
(`mlb.fetch_pitcher_game_log` mocked, no network) and the same fixture
results store. Steps 1,2,4-9 of the daily loop are neutralised (mocked to
deterministic no-ops); none of them touch the pitcher log store, and this
test is only about step 3.

OLD ARM: `pitchers.build_log_store` is intercepted so the `refresh`/
`max_refetch_per_run` keywords cmd_daily's do_pitchers now passes are
stripped before the call reaches the real function -- the call that
actually executes is byte-for-byte the pre-fix call
(`build_log_store(ids, today[:4])`, i.e. `resume=True` default,
`refresh=False` default), reproducing the exact historical bug mechanism
(`_has_season` treating any cached row, including a marker, as "done for
the season").

NEW ARM: cmd_daily runs completely unmodified -- today's real do_pitchers
wiring (refresh=True, max_refetch_per_run=400) is exercised exactly as
production calls it.
"""
import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import cli
from src.pipeline import history, pitchers
from src.providers import mlb

PERSON_ID = "660271"
GAME_PK = "777001"
SEASON = "2026"
TODAY = "2026-09-22"


def _appearance(day):
    return {
        "person_id": int(PERSON_ID), "date": day, "season": SEASON,
        "is_home": False, "games_started": 1, "innings_pitched": 6.0,
        "earned_runs": 2, "runs": 2, "hits": 5, "walks": 2,
        "strikeouts": 6, "home_runs": 1, "batters_faced": 24, "pitches": 95,
    }


class CmdDailyPitcherRefreshRegressionTest(unittest.TestCase):
    """One test driving `src.cli.cmd_daily`, per the verification task: the
    pre-fix call shape misses a new completed appearance the provider now
    has, the corrected call shape picks it up -- both through the real
    daily entry point, both fed the same injected provider response."""

    def _run_daily(self, store_path, *, simulate_old_call):
        real_build_log_store = pitchers.build_log_store

        def _routed(person_ids, season, path=None, **kwargs):
            if simulate_old_call:
                kwargs.pop("refresh", None)
                kwargs.pop("max_refetch_per_run", None)
            return real_build_log_store(person_ids, season, store_path, **kwargs)

        results = {
            GAME_PK: {"game_pk": GAME_PK, "date": TODAY, "status": "Final",
                      "away_probable_id": PERSON_ID, "home_probable_id": None},
        }

        with mock.patch.object(pitchers, "build_log_store", side_effect=_routed), \
             mock.patch.object(history, "read_results", return_value=results), \
             mock.patch("src.pipeline.dense.any_game_scheduled", return_value=False), \
             mock.patch("src.pipeline.history.ingest_range",
                        return_value={"processed": 0, "total_games_stored": 0}), \
             mock.patch("src.pipeline.bullpen.build_log",
                        return_value={"appearances": 0, "games": 0}), \
             mock.patch("src.cli.cmd_brief", return_value=cli.EXIT_OK), \
             mock.patch("src.cli.cmd_ledger", return_value=None), \
             mock.patch("src.cli.cmd_grade", return_value=None), \
             mock.patch("src.cli.cmd_scan_grade", return_value=None), \
             mock.patch("src.appstate.settlement.settle_saved_bets_if_app_db_exists",
                        return_value={"skipped": True, "reason": "test"}), \
             mock.patch("src.pipeline.boxscores.ingest_date",
                        return_value={"games_written": 0, "games_skipped": 0,
                                      "pitcher_rows": 0, "batter_rows": 0}), \
             mock.patch.object(mlb, "fetch_pitcher_game_log",
                               return_value=[_appearance("2026-09-10"),
                                             _appearance(TODAY)]):
            cli.cmd_daily(argparse.Namespace(date=TODAY))

    def _seed(self, path):
        pitchers.write_logs({
            PERSON_ID: [_appearance("2026-09-10"),
                        {"person_id": int(PERSON_ID), "season": SEASON,
                         "date": None, "empty": False,
                         "checked_utc": "2026-09-11T00:00:00+00:00"}],
        }, path)

    def test_old_call_shape_misses_new_appearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = Path(tmp) / "old_logs.jsonl"
            self._seed(old_path)
            self._run_daily(old_path, simulate_old_call=True)
            old_logs = pitchers.read_logs(old_path)
            old_dates = sorted(a["date"] for a in old_logs[PERSON_ID] if a.get("date"))
            print("VERBATIM OLD daily-path dates after run:", old_dates)
            self.assertNotIn(TODAY, old_dates,
                             "pre-fix call shape must MISS the new completed "
                             "appearance (this is the 2026-09-22 defect)")

    def test_corrected_call_shape_includes_new_appearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            new_path = Path(tmp) / "new_logs.jsonl"
            self._seed(new_path)
            self._run_daily(new_path, simulate_old_call=False)
            new_logs = pitchers.read_logs(new_path)
            new_dates = sorted(a["date"] for a in new_logs[PERSON_ID] if a.get("date"))
            print("VERBATIM CORRECTED daily-path dates after run:", new_dates)
            self.assertIn(TODAY, new_dates,
                         "corrected daily path (refresh=True) must include "
                         "the new completed appearance")


if __name__ == "__main__":
    unittest.main()
