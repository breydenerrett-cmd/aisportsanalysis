"""Coverage-map and scoreboard tests, on synthetic trees only.

Nothing here touches the real data/ directory: every reader in coverage takes
its path (or a root) as a parameter, and the tests exercise the same file
shapes the production stores use -- JSONL with empty markers, the odds dirs'
mlb_<season>.jsonl naming, the statcast manifest -- at toy size, so the
counting logic is checked against numbers a human can verify by eye.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.research import coverage, scoreboard


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write((row if isinstance(row, str) else json.dumps(row)) + "\n")


def _build_tree(root: Path):
    """A miniature historical dir with hand-checkable per-season counts."""
    # Results: 4 games in 2023, 2 in 2024, 1 sealed 2025 row.
    lines = ["game_pk,date,away_team,home_team"]
    for pk, date in (("1", "2023-04-01"), ("2", "2023-04-01"),
                     ("3", "2023-04-02"), ("4", "2023-04-03"),
                     ("5", "2024-05-01"), ("6", "2024-05-02"),
                     ("7", "2025-04-01")):
        lines.append(f"{pk},{date},AAA,BBB")
    (root / "mlb_results.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Lineups: 3 of the 4 games in 2023, 0 of 2 in 2024, plus an off-day
    # marker that must count as coverage, not as a game.
    _write_jsonl(root / "lineups.jsonl", [
        {"date": "2023-04-01", "game_pk": 1, "away": [], "home": []},
        {"date": "2023-04-01", "game_pk": 2, "away": [], "home": []},
        {"date": "2023-04-02", "game_pk": 3, "away": [], "home": []},
        {"date": "2023-04-04", "empty": True},
    ])

    # Odds history: 2023 snapshots carrying events lists; 2025 is sealed and
    # must be counted by line without parsing.
    _write_jsonl(root / "odds_history" / "mlb_2023.jsonl", [
        {"snapshot_at": "x", "events": [{"id": "a"}, {"id": "b"}]},
        {"snapshot_at": "y", "events": [{"id": "c"}]},
    ])
    _write_jsonl(root / "odds_history" / "mlb_2025.jsonl",
                 ["not even json", "{\"events\": []}"])

    # F5 odds: one event per line (no "events" list), 2 in 2023, 1 in 2024.
    _write_jsonl(root / "odds_first_five" / "mlb_2023.jsonl", [
        {"event_id": "a", "date": "2023-04-01"},
        {"event_id": "b", "date": "2023-04-02"},
    ])
    _write_jsonl(root / "odds_first_five" / "mlb_2024.jsonl", [
        {"event_id": "c", "date": "2024-05-01"},
    ])

    # F5 results: 3 rows over the discovery seasons.
    _write_jsonl(root / "first_five_results.jsonl", [
        {"date": "2023-04-01", "game_pk": "1"},
        {"date": "2023-04-02", "game_pk": "3"},
        {"date": "2024-05-01", "game_pk": "5"},
    ])

    # Transactions include a sealed-season row; only its date key is read.
    _write_jsonl(root / "transactions.jsonl", [
        {"date": "2023-06-01", "player": "A"},
        {"date": "2026-08-17", "player": "B"},
    ])

    # Pitcher logs carry an explicit season key and empty markers.
    _write_jsonl(root / "pitcher_logs.jsonl", [
        {"person_id": 1, "season": "2023", "date": "2023-05-06"},
        {"person_id": 1, "season": "2024", "date": None, "empty": True},
    ])
    _write_jsonl(root / "bullpen_log.jsonl", [
        {"date": "2024-08-19", "game_pk": 1},
    ])

    manifest = {"windows": {
        "2023-03-30..2023-04-02": {"file": "a.jsonl.gz", "rows": 100},
        "2023-04-03..2023-04-06": {"file": "b.jsonl.gz", "rows": 50},
        "2024-04-01..2024-04-04": {"file": "c.jsonl.gz", "rows": 25},
    }}
    (root / "statcast").mkdir(parents=True, exist_ok=True)
    (root / "statcast" / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")


class TestExpectedN(unittest.TestCase):
    def test_multiplies_and_floors(self):
        # 1000 * 0.5 * 0.75 * 0.2 = 75 exactly.
        self.assertEqual(coverage.expected_n(0.5, 0.75, 0.2, games=1000), 75)
        # 100 * 0.5 * 0.75 * 0.9 = 33.75 -> floors to 33, never rounds up.
        self.assertEqual(coverage.expected_n(0.5, 0.75, 0.9, games=100), 33)

    def test_default_price_match(self):
        self.assertEqual(coverage.expected_n(1.0, fire_rate=1.0, games=100),
                         int(100 * coverage.DEFAULT_PRICE_MATCH_PCT))

    def test_rejects_out_of_range_fractions(self):
        for bad in (-0.1, 1.5, "half", None):
            with self.assertRaises(ValueError):
                coverage.expected_n(bad, games=100)
        with self.assertRaises(ValueError):
            coverage.expected_n(0.5, fire_rate=2.0, games=100)

    def test_games_from_results_csv_uses_discovery_seasons_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_tree(root)
            # 4 + 2 discovery games; the 2025 row must not inflate the base.
            n = coverage.expected_n(1.0, 1.0, 1.0,
                                    results_path=root / "mlb_results.csv")
            self.assertEqual(n, 6)

    def test_none_when_no_games_knowable(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.csv"
            self.assertIsNone(coverage.expected_n(0.5, results_path=missing))


class TestCounters(unittest.TestCase):
    def test_jsonl_season_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.jsonl"
            _write_jsonl(path, [
                {"season": "2023", "date": "1999-01-01"},  # season key wins
                {"date": "2024-05-01"},
                {"date": "2024-06-01"},
                {"date": "2023-04-04", "empty": True},     # marker, not data
                {"date": "banana"},                        # unknown season
                "{broken",                                 # bad line
            ])
            counts = coverage.jsonl_season_counts(path)
            self.assertTrue(counts["exists"])
            self.assertEqual(counts["seasons"], {"2023": 1, "2024": 2})
            self.assertEqual(counts["rows"], 4)
            self.assertEqual(counts["markers"], 1)
            self.assertEqual(counts["bad_lines"], 1)
            self.assertEqual(counts["unknown_season"], 1)

    def test_jsonl_missing_file_is_empty_not_error(self):
        counts = coverage.jsonl_season_counts(Path("/nonexistent/x.jsonl"))
        self.assertFalse(counts["exists"])
        self.assertEqual(counts["seasons"], {})

    def test_odds_event_counts_parses_discovery_lines_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_tree(root)
            counts = coverage.odds_event_counts(root / "odds_history")
            # 2023 parsed as events (2 + 1); 2025 counted by line, unparsed --
            # which is why the deliberately invalid line still counts.
            self.assertEqual(counts["seasons"], {"2023": 3, "2025": 2})
            self.assertEqual(counts["line_count_only"], ["2025"])

    def test_odds_event_counts_one_event_per_line_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_tree(root)
            counts = coverage.odds_event_counts(root / "odds_first_five")
            self.assertEqual(counts["seasons"], {"2023": 2, "2024": 1})

    def test_statcast_seasons_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_tree(root)
            sc = coverage.statcast_seasons(root / "statcast" / "manifest.json")
            self.assertEqual(sc["seasons"], {"2023": 150, "2024": 25})
            self.assertEqual(sc["windows"], 3)
            self.assertEqual(sc["pitches"], 175)

    def test_results_by_season(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_tree(root)
            self.assertEqual(coverage.results_by_season(root / "mlb_results.csv"),
                             {"2023": 4, "2024": 2, "2025": 1})


class TestReport(unittest.TestCase):
    def test_report_on_synthetic_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_tree(root)
            rep = coverage.report(root=root)

            self.assertEqual(rep["results_csv"]["rows_or_games"], 7)
            self.assertIn("2025", rep["results_csv"]["notes"])

            # Lineup coverage: 3 of 6 discovery games -> 50.0%, and the
            # off-day marker must not count as a game.
            lineups = rep["lineups"]
            self.assertEqual(lineups["seasons"], {"2023": 3})
            self.assertEqual(lineups["rows_or_games"], 3)
            self.assertEqual(lineups["coverage_pct"], 50.0)

            # F5 odds coverage vs the same 6 games: 3 events -> 50.0%.
            self.assertEqual(rep["odds_first_five"]["coverage_pct"], 50.0)
            self.assertIsNone(rep["odds_history"]["coverage_pct"])
            self.assertIn("2025", rep["odds_history"]["notes"])

            self.assertEqual(rep["first_five_results"]["coverage_pct"], 50.0)
            self.assertEqual(rep["transactions"]["seasons"],
                             {"2023": 1, "2026": 1})
            self.assertIn("sealed", rep["transactions"]["notes"])
            self.assertEqual(rep["pitcher_logs"]["seasons"], {"2023": 1})
            self.assertEqual(rep["statcast"]["rows_or_games"], 175)

            for entry in rep.values():
                self.assertEqual(sorted(entry),
                                 ["coverage_pct", "notes", "rows_or_games",
                                  "seasons"])

    def test_report_marks_missing_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = coverage.report(root=Path(tmp))
            self.assertIn("missing", rep["lineups"]["notes"])
            self.assertEqual(rep["lineups"]["rows_or_games"], 0)
            self.assertIsNone(rep["lineups"]["coverage_pct"])

    def test_format_report_is_a_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_tree(root)
            text = coverage.format_report(root=root)
            self.assertIsInstance(text, str)
            for name in ("source", "results_csv", "lineups", "odds_history",
                         "odds_first_five", "statcast", "pitcher_logs"):
                self.assertIn(name, text)
            self.assertIn("50.0%", text)


class TestScoreboard(unittest.TestCase):
    def test_record_fills_defaults_and_read_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research" / "scoreboard.jsonl"
            written = scoreboard.record(
                {"started": "2026-08-29T02:00Z", "hypotheses_screened": 12,
                 "hypotheses_killed": 9, "extra": "kept"}, path=path)
            self.assertEqual(written["hypotheses_replicated"], 0)
            self.assertEqual(written["survivors"], 0)
            self.assertEqual(written["credits_spent"], 0)
            self.assertEqual(written["finished"], "")
            self.assertEqual(written["notes"], "")
            self.assertEqual(written["extra"], "kept")

            scoreboard.record({"notes": "second run"}, path=path)
            rows = scoreboard.read(path=path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["hypotheses_screened"], 12)
            self.assertEqual(rows[1]["notes"], "second run")

    def test_record_never_invents_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scoreboard.jsonl"
            row = scoreboard.record({}, path=path)
            self.assertEqual(row["started"], "")
            self.assertEqual(row["finished"], "")

    def test_record_rejects_non_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scoreboard.jsonl"
            with self.assertRaises(scoreboard.ScoreboardError):
                scoreboard.record(["not", "a", "dict"], path=path)

    def test_read_missing_file_is_empty(self):
        self.assertEqual(scoreboard.read(path=Path("/nonexistent/s.jsonl")), [])

    def test_read_raises_on_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scoreboard.jsonl"
            path.write_text("{broken\n", encoding="utf-8")
            with self.assertRaises(scoreboard.ScoreboardError):
                scoreboard.read(path=path)

    def test_format_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scoreboard.jsonl"
            self.assertEqual(scoreboard.format_latest(path=path),
                             "no runs recorded")
            scoreboard.record({"started": "a", "finished": "b",
                               "hypotheses_screened": 5, "hypotheses_killed": 4,
                               "survivors": 1, "credits_spent": 40,
                               "notes": "M6 dead"}, path=path)
            text = scoreboard.format_latest(path=path)
            self.assertIn("a -> b", text)
            self.assertIn("screened 5", text)
            self.assertIn("killed 4", text)
            self.assertIn("survivors 1", text)
            self.assertIn("credits 40", text)
            self.assertIn("M6 dead", text)


if __name__ == "__main__":
    unittest.main()
