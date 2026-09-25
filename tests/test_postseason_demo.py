"""tests/test_postseason_demo.py -- the demonstration builders in
scripts/postseason_demo.py: the sealed-window filters, the conditional
seeding derivation, and (2026-09-25 Opus review fixes) the v2 World Series
demonstration's internal consistency.

Most of this suite uses small synthetic fixtures, never the real
2026-01-01..2026-08-27 window itself -- proving the FILTER excludes that
window correctly without the test needing to read it.

`StateTableConsistencyTests` is the one exception: it runs
`run_world_series_2024_demo_v2` against the REAL historical store, because
the property it checks -- that the state table's k=0 row and the standalone
pre-series forecast agree EXACTLY, since they are conceptually the same
computation done two different ways -- is an integration property across
real starter/bullpen/park data that a synthetic fixture would not exercise
honestly. It costs a few real seconds, not the whole suite.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "postseason_demo", REPO / "scripts" / "postseason_demo.py")
demo = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("postseason_demo", demo)
SPEC.loader.exec_module(demo)


class SealedWindowFilterTests(unittest.TestCase):
    def test_2026_rows_inside_the_sealed_window_are_removed(self):
        store = {
            "1": {"date": "2026-01-01"},   # sealed: first sealed day
            "2": {"date": "2026-08-27"},   # sealed: last sealed day
            "3": {"date": "2026-08-28"},   # unsealed: first unsealed day
            "4": {"date": "2026-09-23"},   # unsealed
        }
        out = demo._unsealed_2026_store(store)
        self.assertEqual({"3", "4"}, set(out))

    def test_non_2026_rows_pass_through_untouched(self):
        store = {
            "1": {"date": "2024-05-01"},
            "2": {"date": "2025-10-01"},
            "3": {"date": "2026-01-01"},  # sealed
        }
        out = demo._unsealed_2026_store(store)
        self.assertEqual({"1", "2"}, set(out))

    def test_bullpen_log_filter_matches_store_filter_boundary(self):
        log = [
            {"date": "2026-08-27", "team": "AAA"},  # sealed
            {"date": "2026-08-28", "team": "AAA"},  # unsealed
            {"date": "2025-08-28", "team": "AAA"},  # not even 2026
        ]
        out = demo._unsealed_2026_bullpen_log(log)
        self.assertEqual([{"date": "2026-08-28", "team": "AAA"},
                          {"date": "2025-08-28", "team": "AAA"}], out)

    def test_empty_input_stays_empty(self):
        self.assertEqual({}, demo._unsealed_2026_store({}))
        self.assertEqual([], demo._unsealed_2026_bullpen_log([]))


class DeriveConditionalSeedingTests(unittest.TestCase):
    """A synthetic 6-team-per-league standings snapshot -- shaped like
    data/historical/standings.jsonl's real rows but small enough to hand-
    verify the seeding rule against."""

    @staticmethod
    def _row(league_id, team, div_rank, win_pct, is_leader, wc_rank, captured="2099-01-01T00:00:00Z"):
        return {"captured_at": captured, "league_id": league_id, "team_abbrev": team,
                "division_rank": div_rank, "win_pct": win_pct,
                "division_leader": is_leader, "wildcard_rank": wc_rank}

    def _snapshot(self):
        rows = []
        # AL (103): three "divisions" of two teams each, for a minimal
        # 6-team field -- leaders X1 > X2 > X3 by win_pct, wildcards by
        # wc_rank (deliberately NOT in win_pct order, to prove the function
        # sorts by wc_rank and not by re-deriving it from win_pct).
        rows.append(self._row(103, "X1", 1, 0.600, True, None))
        rows.append(self._row(103, "X2", 1, 0.580, True, None))
        rows.append(self._row(103, "X3", 1, 0.550, True, None))
        rows.append(self._row(103, "W1", 2, 0.500, False, 1))
        rows.append(self._row(103, "W2", 2, 0.700, False, 2))  # highest win_pct, still seed 5
        rows.append(self._row(103, "W3", 2, 0.490, False, 3))
        # NL (104), same shape.
        for i, (team, wp, leader, wc) in enumerate([
            ("Y1", 0.610, True, None), ("Y2", 0.590, True, None),
            ("Y3", 0.560, True, None), ("V1", 0.510, False, 1),
            ("V2", 0.505, False, 2), ("V3", 0.480, False, 3),
        ]):
            rows.append(self._row(104, team, 1, wp, leader, wc))
        return rows

    def test_division_leaders_seeded_1_to_3_by_win_pct(self):
        derived = demo.derive_conditional_seeding(self._snapshot())
        al = derived["seeding"]["AL"]
        self.assertEqual("X1", al[1]["team"])
        self.assertEqual("X2", al[2]["team"])
        self.assertEqual("X3", al[3]["team"])

    def test_wildcards_seeded_4_to_6_by_wildcard_rank_not_win_pct(self):
        derived = demo.derive_conditional_seeding(self._snapshot())
        al = derived["seeding"]["AL"]
        self.assertEqual("W1", al[4]["team"])  # wc_rank 1, despite W2 having higher win_pct
        self.assertEqual("W2", al[5]["team"])
        self.assertEqual("W3", al[6]["team"])

    def test_both_leagues_present(self):
        derived = demo.derive_conditional_seeding(self._snapshot())
        self.assertEqual({"AL", "NL"}, set(derived["seeding"]))

    def test_captured_at_is_reported_verbatim(self):
        derived = demo.derive_conditional_seeding(self._snapshot())
        self.assertEqual("2099-01-01T00:00:00Z", derived["captured_at"])

    def test_multiple_captured_at_values_raise(self):
        rows = self._snapshot()
        rows[0] = dict(rows[0], captured_at="2099-01-02T00:00:00Z")
        with self.assertRaises(RuntimeError):
            demo.derive_conditional_seeding(rows)

    def test_wrong_team_count_raises_rather_than_silently_truncating(self):
        rows = self._snapshot()
        rows.pop()  # drop one NL wildcard -> only 2 wildcards for NL
        with self.assertRaises(RuntimeError):
            demo.derive_conditional_seeding(rows)

    def test_no_team_is_hardcoded(self):
        """Swap every team name for a nonsense string and confirm the
        derivation still works -- proving the function reads names from the
        rows rather than assuming any real 2026 club."""
        rows = self._snapshot()
        for row in rows:
            row["team_abbrev"] = "Q_" + row["team_abbrev"]
        derived = demo.derive_conditional_seeding(rows)
        self.assertEqual("Q_X1", derived["seeding"]["AL"][1]["team"])


class StateTableConsistencyTests(unittest.TestCase):
    """2026-09-25 Opus review, fix 3, checked against REAL 2024 World
    Series data (see module docstring for why this one class reads real
    data instead of a synthetic fixture)."""

    @classmethod
    def setUpClass(cls):
        from src.pipeline import bullpen, history, pitchers
        store = history.read_results()
        pitcher_logs = pitchers.read_logs()
        bullpen_log = bullpen.read_log()
        cls.result = demo.run_world_series_2024_demo_v2(store, pitcher_logs, bullpen_log)

    def test_state_table_has_exactly_six_rows_k_zero_to_five(self):
        self.assertEqual([0, 1, 2, 3, 4, 5], [row["k"] for row in self.result["state_table"]])

    def test_row_k_zero_matches_the_standalone_pre_series_forecast_exactly(self):
        """These are the SAME computation (game 1 real+announced, every
        other game projected from pre-series history) expressed two
        different ways -- a standalone forecast, and the k=0 row of the
        state table. If they ever disagree, one of the two code paths has
        drifted from the other."""
        row0 = self.result["state_table"][0]
        forecast = self.result["pre_series_forecast"]
        self.assertEqual(forecast["p_lad_wins_series"], row0["p_lad_wins_series"])

    def test_record_after_k_games_matches_the_real_result(self):
        # LAD won games 1, 2, 3, 5 and lost game 4 (LAD won the series 4-1).
        expected = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (4, 1)]
        actual = [(row["lad_wins"], row["lad_losses"]) for row in self.result["state_table"]]
        self.assertEqual(expected, actual)

    def test_p_reaches_exactly_one_at_the_real_clinch(self):
        # After 5 real games LAD had already clinched (4 wins) in reality.
        self.assertEqual(1.0, self.result["state_table"][-1]["p_lad_wins_series"])

    def test_p_rises_after_a_real_win_and_falls_after_a_real_loss(self):
        """Game 4 (index 3, 0-based) was a LAD LOSS; game 5 (index 4) was a
        LAD WIN. The state table's own row-to-row probability must move in
        the matching direction on real data, not just in a synthetic toy."""
        rows = self.result["state_table"]
        p_after_3 = rows[3]["p_lad_wins_series"]   # after 3 real games (3-0)
        p_after_4 = rows[4]["p_lad_wins_series"]   # after the game-4 LOSS (3-1)
        p_after_5 = rows[5]["p_lad_wins_series"]   # after the game-5 WIN (4-1)
        self.assertLess(p_after_4, p_after_3)      # a loss must lower it
        self.assertGreater(p_after_5, p_after_4)   # a win must raise it

    def test_games_six_and_seven_always_get_a_projected_starter_never_unknown(self):
        for row in self.result["state_table"]:
            remaining_by_game_number = {g["game_number"]: g for g in row["remaining_games"]}
            for game_number in (6, 7):
                if game_number not in remaining_by_game_number:
                    continue  # already resolved out of the "remaining" list -- fine
                game = remaining_by_game_number[game_number]
                self.assertIsNotNone(game["home_sp_id"], msg=f"k={row['k']} game {game_number}")
                self.assertIsNotNone(game["away_sp_id"], msg=f"k={row['k']} game {game_number}")
                self.assertEqual("projected", game["home_sp_source"])
                self.assertEqual("projected", game["away_sp_source"])

    def test_already_played_games_use_actual_starters_in_every_row(self):
        for row in self.result["state_table"]:
            k = row["k"]
            for game in row["remaining_games"]:
                if game["game_number"] <= k:  # should not even occur (see below) but guard anyway
                    self.fail("an already-played game must not appear in remaining_games")
            # every game number from 1..k is NOT in remaining_games at all --
            # its outcome is already folded into (lad_wins, lad_losses).
            numbers = {g["game_number"] for g in row["remaining_games"]}
            self.assertTrue(all(n > k for n in numbers))

    def test_hindsight_and_pre_series_are_both_present_and_distinctly_labelled(self):
        self.assertIn("NOT A FORECAST", self.result["hindsight_series_solve"]["label"])
        self.assertIn("PRE-SERIES FORECAST", self.result["pre_series_forecast"]["label"])

    # ---- 2026-09-25 SECOND review: the rotation-projection fixes ----

    def test_every_pitcher_id_in_the_artifact_is_int(self):
        """The second review's id-type bug (int vs str) must not resurface
        anywhere in the written artifact."""
        ids = []
        for g in self.result["attribution_by_game"]:
            ids += [g["inputs"]["away_sp_id"], g["inputs"]["home_sp_id"]]
        for g in self.result["pre_series_forecast"]["per_game"]:
            ids += [g["away_sp_id"], g["home_sp_id"]]
        for row in self.result["state_table"]:
            for g in row["remaining_games"]:
                ids += [g["away_sp_id"], g["home_sp_id"]]
        for pid in self.result["pre_series_forecast"]["rotation_pool"]["LAD"]:
            ids.append(pid)
        for pid in self.result["pre_series_forecast"]["rotation_pool"]["NYY"]:
            ids.append(pid)
        non_int = [pid for pid in ids if not isinstance(pid, int)]
        self.assertEqual([], non_int, msg=f"non-int ids found: {non_int!r}")

    def test_no_projected_starter_repeats_within_four_consecutive_team_games(self):
        """For every row, and for every team: a PROJECTED start must never
        match any of that team's starters (real or projected) in the
        previous 3 games -- i.e. no repeat within 4 consecutive team games.
        """
        # Real starters for games 1-5 (index 0-4), by team, from the
        # attribution table (which only ever reports real, played games).
        real_by_team_index = {}
        for g in self.result["attribution_by_game"]:
            idx = g["game_number"] - 1
            real_by_team_index.setdefault(g["home"], {})[idx] = g["inputs"]["home_sp_id"]
            real_by_team_index.setdefault(g["away"], {})[idx] = g["inputs"]["away_sp_id"]

        for row in self.result["state_table"]:
            k = row["k"]
            by_index = {}  # (team, index) -> (pid, source)
            for g in row["remaining_games"]:
                idx = g["game_number"] - 1
                by_index[(g["home"], idx)] = (g["home_sp_id"], g["home_sp_source"])
                by_index[(g["away"], idx)] = (g["away_sp_id"], g["away_sp_source"])

            for team in ("LAD", "NYY"):
                sequence = []
                for idx in range(7):
                    if idx < k or idx == 0:
                        sequence.append((real_by_team_index[team][idx], "actual"))
                    else:
                        sequence.append(by_index[(team, idx)])
                for j in range(7):
                    pid_j, src_j = sequence[j]
                    if src_j != "projected":
                        continue
                    for i in range(max(0, j - 3), j):
                        pid_i, _ = sequence[i]
                        self.assertNotEqual(
                            pid_i, pid_j,
                            msg=f"k={k} team={team} game {i + 1} and {j + 1} both {pid_j}: "
                                f"{[p for p, _ in sequence]}")

    def test_regression_k1_game2_never_projects_the_game1_starters(self):
        """The exact real-data failure the second review reported: at k=1
        (right after game 1), game 2 must not project either game-1
        starter (543037 Cole or 656427 Flaherty) -- they just pitched."""
        row_k1 = next(r for r in self.result["state_table"] if r["k"] == 1)
        game2 = next(g for g in row_k1["remaining_games"] if g["game_number"] == 2)
        self.assertNotIn(game2["home_sp_id"], (543037, 656427))
        self.assertNotIn(game2["away_sp_id"], (543037, 656427))

    def test_rotation_pool_excludes_the_flagged_non_rotation_pitchers(self):
        """656629 (Michael Kopech, 1 start all season) and 573186 (Marcus
        Stroman, 29 starts but none in the 30 days before the series) were
        both incorrectly projected before this fix; neither belongs in
        either team's rotation pool now."""
        pool = self.result["pre_series_forecast"]["rotation_pool"]
        self.assertNotIn(656629, pool["LAD"])
        self.assertNotIn(573186, pool["NYY"])


if __name__ == "__main__":
    unittest.main()
