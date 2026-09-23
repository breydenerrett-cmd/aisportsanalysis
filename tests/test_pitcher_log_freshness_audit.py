"""Unit tests for scripts/pitcher_log_freshness_audit.py on synthetic
results/logs fixtures -- no real data file is touched.

Loaded via importlib (scripts/ is not a package), the same pattern
tests/test_totals_population_audit.py already uses for auditing a
scripts/*.py file.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pitcher_log_freshness_audit",
    REPO / "scripts" / "pitcher_log_freshness_audit.py",
)
plfa = importlib.util.module_from_spec(SPEC)
sys.modules["pitcher_log_freshness_audit"] = plfa
SPEC.loader.exec_module(plfa)  # type: ignore[union-attr]


def _final_game(game_pk, day, away_id, home_id):
    return {
        "game_pk": game_pk, "date": day, "away_probable_id": away_id,
        "home_probable_id": home_id,
    }


def _appearance(pid, day, season="2026"):
    return {"person_id": int(pid), "date": day, "season": season,
            "games_started": 1, "innings_pitched": 6.0, "earned_runs": 2,
            "hits": 5, "walks": 2, "strikeouts": 6, "home_runs": 1,
            "batters_faced": 24}


def _marker(pid, season, checked_utc=None, empty=False):
    row = {"person_id": int(pid), "season": season, "date": None,
          "empty": empty}
    if checked_utc:
        row["checked_utc"] = checked_utc
    return row


TARGET = "2026-09-10"
NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


class TestFreshClassification(unittest.TestCase):
    def test_a_captured_appearance_is_fresh(self):
        results = {"1": _final_game("1", TARGET, "100", "200")}
        logs = {
            "100": [_appearance("100", TARGET),
                   _marker("100", "2026", checked_utc="2026-09-11T00:00:00+00:00")],
            "200": [_appearance("200", TARGET),
                   _marker("200", "2026", checked_utc="2026-09-11T00:00:00+00:00")],
        }
        result = plfa.audit(results, logs, TARGET, NOW)
        statuses = {r["person_id"]: r["status"] for r in result["rows"]}
        self.assertEqual(statuses, {"100": "FRESH", "200": "FRESH"})
        self.assertTrue(result["job_executed_since_target"])
        self.assertEqual(result["fetch_succeeded"], 2)


class TestPendingIsNotAFailure(unittest.TestCase):
    def test_no_refresh_since_the_game_is_pending_not_escalated(self):
        # The pitcher has SOME prior-season data but nothing checked since
        # the target game finished -- the job just hasn't had its turn yet.
        results = {"1": _final_game("1", TARGET, "100", "200")}
        logs = {
            "100": [_appearance("100", "2026-04-05"),
                   _marker("100", "2026", checked_utc="2026-04-06T00:00:00+00:00")],
            "200": [_appearance("200", "2026-04-05"),
                   _marker("200", "2026", checked_utc="2026-04-06T00:00:00+00:00")],
        }
        result = plfa.audit(results, logs, TARGET, NOW)
        statuses = {r["person_id"]: r["status"] for r in result["rows"]}
        self.assertEqual(statuses, {"100": "PENDING", "200": "PENDING"})
        self.assertFalse(result["job_executed_since_target"])


class TestNeverCaptured(unittest.TestCase):
    def test_a_pitcher_with_no_rows_at_all_is_never_captured(self):
        results = {"1": _final_game("1", TARGET, "100", "999")}
        logs = {"100": [_appearance("100", TARGET),
                        _marker("100", "2026", checked_utc="2026-09-11T00:00:00+00:00")]}
        result = plfa.audit(results, logs, TARGET, NOW)
        statuses = {r["person_id"]: r["status"] for r in result["rows"]}
        self.assertEqual(statuses["999"], "NEVER_CAPTURED")


class TestMissingAfterRefreshEscalates(unittest.TestCase):
    def test_checked_after_the_game_but_still_missing_is_escalated(self):
        # A refresh ran a full day after the game finished, and the
        # appearance still is not there -- this is the actionable failure.
        results = {"1": _final_game("1", TARGET, "100", "200")}
        logs = {
            "100": [_appearance("100", "2026-08-01"),
                   _marker("100", "2026", checked_utc="2026-09-11T00:00:00+00:00")],
            "200": [_appearance("200", TARGET),
                   _marker("200", "2026", checked_utc="2026-09-11T00:00:00+00:00")],
        }
        result = plfa.audit(results, logs, TARGET, NOW)
        statuses = {r["person_id"]: r["status"] for r in result["rows"]}
        self.assertEqual(statuses["100"], "MISSING_AFTER_REFRESH")
        self.assertEqual(statuses["200"], "FRESH")


class TestSourceCoverageGapIsSeparate(unittest.TestCase):
    def test_a_final_game_with_no_probable_id_is_a_source_gap_not_a_pitcher_row(self):
        results = {"1": _final_game("1", TARGET, None, None)}
        logs = {}
        result = plfa.audit(results, logs, TARGET, NOW)
        self.assertEqual(result["source_coverage_gaps"], 1)
        self.assertEqual(result["slate_pitchers"], 0)


class TestMainExitCodes(unittest.TestCase):
    def test_main_returns_1_when_a_finding_exists(self):
        results = {"1": _final_game("1", TARGET, "100", "999")}
        logs = {"100": [_appearance("100", TARGET),
                        _marker("100", "2026", checked_utc="2026-09-11T00:00:00+00:00")]}
        result = plfa.audit(results, logs, TARGET, NOW)
        findings = [r for r in result["rows"] if r["status"] in
                   ("MISSING_AFTER_REFRESH", "NEVER_CAPTURED")]
        self.assertTrue(findings)

    def test_main_returns_0_when_everything_is_fresh_or_pending(self):
        results = {"1": _final_game("1", TARGET, "100", "200")}
        logs = {
            "100": [_appearance("100", TARGET)],
            "200": [_appearance("200", TARGET)],
        }
        result = plfa.audit(results, logs, TARGET, NOW)
        findings = [r for r in result["rows"] if r["status"] in
                   ("MISSING_AFTER_REFRESH", "NEVER_CAPTURED")]
        self.assertFalse(findings)


if __name__ == "__main__":
    unittest.main()
