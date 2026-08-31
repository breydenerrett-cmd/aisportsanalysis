"""The Elo benchmark's mechanics, pinned by hand.

The scoring run itself needs the odds store; these tests pin everything
that must be true regardless: forecasts precede updates, the season
boundary regresses, constants match the frozen doc, and the loss math is
the loss math.
"""

import math
import unittest

from src.research import elobench


def _row(date, away, home, home_won, pk="1", start=""):
    return {"date": date, "away_team": away, "home_team": home,
            "home_won": "1" if home_won else "0", "game_pk": pk,
            "start_time_utc": start, "game_type": "R"}


class ForecastTests(unittest.TestCase):
    def test_the_first_meeting_is_home_advantage_only(self):
        rows = [_row("2023-04-01", "CIN", "NYM", True)]
        forecast = elobench.forecasts(rows)[0]
        expected = 1.0 / (1.0 + 10.0 ** (-(24.0 / 400.0)))
        self.assertAlmostEqual(forecast["elo_home"], expected, places=10)

    def test_a_result_updates_ratings_only_after_its_own_forecast(self):
        """Two identical matchups: game one's forecast is the prior, game
        two's forecast has moved toward the game-one winner."""
        rows = [_row("2023-04-01", "CIN", "NYM", True, pk="1"),
                _row("2023-04-02", "CIN", "NYM", True, pk="2")]
        first, second = elobench.forecasts(rows)
        self.assertGreater(second["elo_home"], first["elo_home"])

    def test_the_update_is_k_scaled_and_zero_sum(self):
        rows = [_row("2023-04-01", "CIN", "NYM", True, pk="1"),
                _row("2023-04-02", "NYM", "CIN", False, pk="2")]
        first, second = elobench.forecasts(rows)
        # After NYM (home) wins game one, NYM gained K*(1-p) and CIN lost
        # the same; game two's home is CIN so its forecast must reflect a
        # rating gap of exactly 2*K*(1-p) against CIN.
        p = first["elo_home"]
        gap = -2.0 * elobench.K * (1.0 - p)
        expected = 1.0 / (1.0 + 10.0 ** (-((gap + 24.0) / 400.0)))
        self.assertAlmostEqual(second["elo_home"], expected, places=10)

    def test_the_season_boundary_regresses_one_third(self):
        rows = ([_row(f"2023-04-{d:02d}", "CIN", "NYM", True, pk=str(d))
                 for d in range(1, 11)]
                + [_row("2024-04-01", "CIN", "NYM", True, pk="99")])
        forecasts = elobench.forecasts(rows)
        # Reconstruct 2023-final ratings by replaying the updates.
        ratings = {"CIN": 1500.0, "NYM": 1500.0}
        for f in forecasts[:10]:
            p = f["elo_home"]
            ratings["NYM"] += elobench.K * (1.0 - p)
            ratings["CIN"] += elobench.K * (0.0 - (1.0 - p))
        regressed = {t: r + (1500.0 - r) / 3.0 for t, r in ratings.items()}
        expected = elobench.forecast_probability(regressed["NYM"],
                                                 regressed["CIN"])
        self.assertAlmostEqual(forecasts[10]["elo_home"], expected, places=10)


class ConstantsTests(unittest.TestCase):
    def test_the_frozen_constants_are_the_documented_ones(self):
        """docs/BENCHMARK_ELO.md froze these; changing one is a new
        benchmark, not a tweak."""
        self.assertEqual(elobench.K, 4.0)
        self.assertEqual(elobench.HOME_ADVANTAGE, 24.0)
        self.assertAlmostEqual(elobench.PRESEASON_REGRESSION, 1.0 / 3.0)
        self.assertEqual(elobench.MIN_BOOKS, 6)
        self.assertEqual((elobench.BURN_SEASON, elobench.SCORED_SEASON),
                         (2023, 2024))

    def test_postseason_and_unfinished_rows_never_enter(self):
        import csv
        import io
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=[
            "date", "away_team", "home_team", "home_won", "game_pk",
            "start_time_utc", "game_type"])
        writer.writeheader()
        writer.writerow(_row("2023-10-15", "CIN", "NYM", True) | {"game_type": "P"})
        writer.writerow(_row("2023-06-15", "CIN", "NYM", True) | {"home_won": ""})
        writer.writerow(_row("2023-06-16", "CIN", "NYM", True))
        buffer.seek(0)
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "r.csv"
            path.write_text(buffer.getvalue(), encoding="utf-8")
            rows = elobench.read_results(path)
        self.assertEqual([r["date"] for r in rows], ["2023-06-16"])


class LossTests(unittest.TestCase):
    def test_log_loss_and_brier_by_hand(self):
        self.assertAlmostEqual(elobench._log_loss(0.75, True),
                               -math.log(0.75), places=12)
        self.assertAlmostEqual(elobench._log_loss(0.75, False),
                               -math.log(0.25), places=12)
        self.assertAlmostEqual(elobench._brier(0.75, True), 0.0625)

    def test_a_degenerate_forecast_cannot_return_infinity(self):
        self.assertTrue(math.isfinite(elobench._log_loss(0.0, True)))
        self.assertTrue(math.isfinite(elobench._log_loss(1.0, False)))


if __name__ == "__main__":
    unittest.main()
