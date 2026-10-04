"""Tests for the opponent-adjusted strikeout comparison, on SYNTHETIC rows only.

`src/research/k_opponent.py` and `scripts/k_opponent_compare.py` implement the
comparison registered in `docs/PREREG_K_OPPONENT.md`. Every row here is built in
this file, so the harness is proven before any outcome-bearing data is touched.
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.model import discovery  # noqa: E402
from src.research import k_baseline as kb  # noqa: E402
from src.research import k_opponent as ko  # noqa: E402


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "k_opponent_compare", REPO_ROOT / "scripts" / "k_opponent_compare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEAMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]


def _date(season, day):
    return f"{season}-{4 + day // 28:02d}-{day % 28 + 1:02d}"


class World:
    """Eight teams, every team plays every day, one starter and one reliever per
    team per game, five starters per team in rotation. Team HHH is built to
    strike out far more batters than the rest, AAA far fewer."""

    def __init__(self, season=2023, seed=7, days=90):
        rng = random.Random(seed)
        self.season = season
        self.pitcher_rows = []      # pitcher_logs rows (starts only)
        self.bullpen_rows = []      # bullpen_log rows (all pitchers)
        self.regular = {}           # game_pk -> date
        bat_k = {t: 0.18 + 0.02 * i for i, t in enumerate(TEAMS)}   # batting K rate
        pk = season * 100000
        for day in range(days):
            date = _date(season, day)
            order = TEAMS[day % 8:] + TEAMS[:day % 8]
            for j in range(4):
                home, away = order[j], order[7 - j]
                pk += 1
                self.regular[pk] = date
                for team, opp in ((home, away), (away, home)):
                    tid = TEAMS.index(team)
                    starter = 1000 + tid * 10 + day % 5
                    reliever = 5000 + tid
                    for pid, started, bf in ((starter, True, rng.randint(18, 28)),
                                             (reliever, False, rng.randint(8, 14))):
                        k = sum(rng.random() < bat_k[opp] for _ in range(bf))
                        self.bullpen_rows.append({
                            "batters_faced": bf, "date": date, "earned_runs": 1,
                            "game_pk": pk, "hits": 4, "innings": 5.0,
                            "name": f"P{pid}", "person_id": pid, "pitches": 80,
                            "started": started, "strikeouts": k, "team": team,
                            "walks": 1})
                        if started:
                            self.pitcher_rows.append({
                                "person_id": pid, "date": date,
                                "season": str(season), "is_home": team == home,
                                "games_started": 1, "innings_pitched": 5.0,
                                "earned_runs": 1, "runs": 1, "hits": 4, "walks": 1,
                                "strikeouts": k, "home_runs": 0,
                                "batters_faced": bf, "pitches": 80})
        self.dates = sorted({r["date"] for r in self.pitcher_rows})

    # -- the pipeline pieces, exactly as the script chains them -------------

    def games(self, rows=None, regular=None):
        return ko.extract_games(self.bullpen_rows if rows is None else rows,
                                self.regular if regular is None else regular)

    def starts(self, rows=None):
        return kb.extract_starts(self.pitcher_rows if rows is None else rows)["starts"]

    def build(self, *, pitcher_rows=None, bullpen_rows=None, **overrides):
        extracted = self.games(bullpen_rows)
        starts = self.starts(pitcher_rows)
        attached = ko.attach_opponents(starts, extracted)
        kwargs = dict(season=self.season, starts=starts, games=extracted["games"],
                      opponents=attached["opponents"], causes=attached["causes"],
                      min_league_starts=20)
        kwargs.update(overrides)
        return ko.build_opponent_rows(**kwargs)


def _by_key(rows):
    return {(r["person_id"], r["date"]): r for r in rows}


class WindowGuardTests(unittest.TestCase):
    def test_the_guard_is_the_k_baseline_guard(self):
        self.assertIs(ko.assert_allowed_date, kb.assert_allowed_date)
        self.assertIs(ko.SealedDataError, kb.SealedDataError)
        self.assertEqual(ko.ALLOWED_SEASONS, kb.ALLOWED_SEASONS)
        for bad in ("2025-04-01", "2025-12-31", "2026-01-01", "2026-08-12",
                    "2026-08-27", "2026-10-03"):
            with self.assertRaises(ko.SealedDataError):
                ko.assert_allowed_date(bad)

    def test_build_refuses_2025_and_2026(self):
        world = World()
        for bad in (2025, 2026):
            with self.assertRaises(ko.SealedDataError):
                world.build(season=bad)

    def test_a_sealed_dated_start_is_a_hard_error(self):
        world = World()
        extracted = world.games()
        starts = world.starts() + [
            {"person_id": 1, "date": "2026-08-12", "k": 5, "bf": 24}]
        with self.assertRaises(ko.SealedDataError):
            ko.attach_opponents(starts, extracted)

    def test_a_sealed_dated_game_is_a_hard_error_in_the_event_builder(self):
        games = {1: {"date": "2026-08-20", "pitching": {"A": [5, 20], "B": [4, 22]},
                     "starters": {}, "rows": {}}}
        with self.assertRaises(ko.SealedDataError):
            ko.batting_events(games, 2026)
        with self.assertRaises(ko.SealedDataError):
            ko.season_league_rate(games, 2026)

    def test_history_refuses_a_sealed_date(self):
        history = ko.OpponentHistory([])
        with self.assertRaises(ko.SealedDataError):
            history.advance_to("2025-05-01")

    def test_sealed_game_rows_are_dropped_on_read_and_change_nothing(self):
        world = World()
        poisoned = world.bullpen_rows + [
            dict(world.bullpen_rows[0], date="2026-08-12", game_pk=99999901),
            dict(world.bullpen_rows[1], date="2026-08-20", game_pk=99999902),
            dict(world.bullpen_rows[2], date="2025-05-01", game_pk=99999903),
            {"date": "2026-08-12", "empty": True}]
        regular = dict(world.regular)
        regular.update({99999901: "2026-08-12", 99999902: "2026-08-20",
                        99999903: "2025-05-01"})
        clean = world.games()
        dirty = ko.extract_games(poisoned, regular)
        self.assertEqual(clean["games"], dirty["games"])
        self.assertEqual(clean["counts"], dirty["counts"])

    def test_script_refuses_other_seasons_before_touching_any_file(self):
        script = _load_script()
        with mock.patch("sys.stderr"), mock.patch.object(
                script, "run", side_effect=AssertionError("must not run")):
            for bad in ("2025", "2026", "2022"):
                self.assertEqual(script.main(["--season", bad]), 2)

    def test_script_never_opens_a_path_for_a_refused_season(self):
        script = _load_script()
        with mock.patch.object(script, "stream_jsonl_years",
                               side_effect=AssertionError("opened")), \
                mock.patch.object(script, "regular_games_for",
                                  side_effect=AssertionError("opened")):
            for bad in (2025, 2026):
                with self.assertRaises(ko.SealedDataError):
                    script.run(bad)

    def test_seasons_needed_is_the_season_and_the_one_before_it_in_window(self):
        script = _load_script()
        self.assertEqual(script.seasons_needed(2023), (2023,))
        self.assertEqual(script.seasons_needed(2024), (2023, 2024))


class StreamingReaderTests(unittest.TestCase):
    """The reader discards an out-of-season raw line BEFORE parsing it, so a
    sealed row is never decoded, never held and never printed."""

    def _write(self, directory, lines):
        path = os.path.join(directory, "mixed.jsonl")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(lines) + "\n")
        return path

    def test_out_of_season_lines_are_never_parsed(self):
        script = _load_script()
        good23 = json.dumps({"date": "2023-05-01", "person_id": 1})
        good24 = json.dumps({"date": "2024-05-01", "person_id": 2})
        # Deliberately NOT valid JSON: if the reader parsed them it would raise.
        sealed = ['{"date": "2026-08-12", BROKEN', '{"date": "2025-07-04", BROKEN',
                  '{"date": "2026-03-26", BROKEN', '{"no_date_here": 1, BROKEN',
                  '{"date": "2022-12-31", BROKEN']
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, [good23] + sealed + [good24])
            self.assertEqual([r["person_id"] for r in
                              script.stream_jsonl_years(path, (2023,))], [1])
            self.assertEqual([r["person_id"] for r in
                              script.stream_jsonl_years(path, (2023, 2024))], [1, 2])

    def test_a_2023_run_holds_no_2024_row(self):
        script = _load_script()
        good24 = '{"date": "2024-05-01", BROKEN'
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, [json.dumps({"date": "2023-05-01", "x": 1}), good24])
            self.assertEqual(len(list(script.stream_jsonl_years(path, (2023,)))), 1)

    def test_results_reader_keeps_only_regular_games_of_the_needed_years(self):
        script = _load_script()
        header = "game_pk,date,start_time_utc,venue,game_type,away_team,home_team"
        lines = [header,
                 "1,2023-05-01,x,v,R,A,B", "2,2023-05-02,x,v,F,A,B",
                 "3,2024-05-01,x,v,R,A,B", "4,2025-05-01,x,v,R,A,B",
                 "5,2026-08-12,x,v,R,A,B", "6,garbage"]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, lines)
            self.assertEqual(script.regular_games_for(path, (2023,)), {1: "2023-05-01"})
            self.assertEqual(script.regular_games_for(path, (2023, 2024)),
                             {1: "2023-05-01", 3: "2024-05-01"})


class ExtractGamesTests(unittest.TestCase):
    def test_a_games_batting_record_is_the_other_teams_pitching(self):
        world = World()
        extracted = world.games()
        pk = next(iter(extracted["games"]))
        game = extracted["games"][pk]
        events = {e[2]: e for e in ko.batting_events(extracted["games"], 2023)
                  if e[1] == pk}
        teams = sorted(game["pitching"])
        self.assertEqual(len(teams), 2)
        a, b = teams
        self.assertEqual(events[a][3:], tuple(game["pitching"][b]))
        self.assertEqual(events[b][3:], tuple(game["pitching"][a]))

    def test_all_pitchers_of_the_team_count_not_only_the_starter(self):
        rows = [
            {"person_id": 1, "game_pk": 7, "date": "2023-05-01", "team": "A",
             "started": True, "strikeouts": 3, "batters_faced": 20},
            {"person_id": 2, "game_pk": 7, "date": "2023-05-01", "team": "A",
             "started": False, "strikeouts": 2, "batters_faced": 10},
            {"person_id": 3, "game_pk": 7, "date": "2023-05-01", "team": "B",
             "started": True, "strikeouts": 4, "batters_faced": 25}]
        g = ko.extract_games(rows, {7: "2023-05-01"})["games"][7]
        self.assertEqual(g["pitching"], {"A": [5, 30], "B": [4, 25]})

    def _base(self, **kw):
        rows = []
        for pid, team in ((1, "A"), (2, "B")):
            rows.append(dict({"person_id": pid, "game_pk": 7, "date": "2023-05-01",
                              "team": team, "started": True, "strikeouts": 3,
                              "batters_faced": 20}, **kw))
        return rows

    def test_exclusions_are_wholesale_and_counted_by_reason(self):
        regular = {7: "2023-05-01"}
        cases = {
            "multi_date": self._base() + [dict(r, date="2023-05-02") for r in self._base()],
            "date_mismatch": [dict(r, date="2023-05-03") for r in self._base()],
            "not_two_teams": [dict(r, team="A") for r in self._base()],
            "duplicate_pitcher_row": self._base() + [self._base()[0]],
            "invalid_k_bf": [dict(self._base()[0], strikeouts=30), self._base()[1]],
        }
        for reason, rows in cases.items():
            with self.subTest(reason):
                out = ko.extract_games(rows, regular)
                self.assertEqual(out["games"], {})
                self.assertEqual(out["excluded_games"], {7: reason})
                self.assertEqual(out["counts"][f"games_excluded_{reason}"], 1)
                self.assertTrue(out["excluded_starts"])
        out = ko.extract_games(self._base(), regular)
        self.assertEqual(list(out["games"]), [7])

    def test_a_missing_or_non_integer_figure_excludes_the_game(self):
        regular = {7: "2023-05-01"}
        for bad in (None, 3.5, True, -1, "3"):
            rows = self._base()
            rows[0]["strikeouts"] = bad
            self.assertEqual(ko.extract_games(rows, regular)["games"], {}, bad)

    def test_an_all_star_game_is_not_a_regular_game(self):
        rows = [dict(r, game_pk=8) for r in self._base()]
        out = ko.extract_games(rows, {7: "2023-05-01"})
        self.assertEqual(out["games"], {})
        self.assertEqual(out["counts"]["rows_not_regular_game"], 2)

    def test_marker_rows_are_skipped_and_counted(self):
        rows = self._base() + [{"date": "2023-07-10", "empty": True}]
        out = ko.extract_games(rows, {7: "2023-05-01"})
        self.assertEqual(out["counts"]["marker_rows"], 1)
        self.assertEqual(list(out["games"]), [7])

    def test_unidentifiable_starts_are_causes_not_guesses(self):
        world = World(days=10)
        extracted = world.games()
        starts = world.starts()
        pid_missing = {"person_id": 424242, "date": starts[0]["date"], "k": 1, "bf": 20}
        pid_other_k = dict(starts[1], k=starts[1]["k"] ^ 1)
        # A start in a game excluded for two dates.
        bad_pk = next(iter(world.regular))
        rows = list(world.bullpen_rows) + [dict(r, date="2023-05-30") for r in
                                           world.bullpen_rows if r["game_pk"] == bad_pk]
        multi = ko.extract_games(rows, world.regular)
        started = next(r for r in world.bullpen_rows
                       if r["game_pk"] == bad_pk and r["started"])
        multi_start = {"person_id": started["person_id"], "date": started["date"],
                       "k": started["strikeouts"], "bf": started["batters_faced"]}
        got = ko.attach_opponents([pid_missing, pid_other_k], extracted)
        self.assertEqual(got["causes"][(424242, starts[0]["date"])], "no_game_match")
        self.assertEqual(got["causes"][(pid_other_k["person_id"], pid_other_k["date"])],
                         "k_bf_disagree")
        self.assertEqual(got["counts"]["with_opponent"], 0)
        got2 = ko.attach_opponents([multi_start], multi)
        self.assertEqual(list(got2["causes"].values()), ["game_excluded_multi_date"])

    def test_the_opposing_team_is_the_other_team_of_the_game(self):
        world = World(days=12)
        extracted = world.games()
        got = ko.attach_opponents(world.starts(), extracted)
        self.assertEqual(got["counts"]["with_opponent"], got["counts"]["starts"])
        for (pid, date), opp in got["opponents"].items():
            self.assertNotEqual(opp["team"], opp["opponent"])
            self.assertEqual(opp["team"], TEAMS[(pid - 1000) // 10])
            game = extracted["games"][opp["game_pk"]]
            self.assertEqual(game["date"], date)
            self.assertEqual(set(game["pitching"]), {opp["team"], opp["opponent"]})


class FactorTests(unittest.TestCase):
    def test_the_registered_constants(self):
        self.assertEqual(ko.OPP_PRIOR_PA, 1000.0)
        self.assertEqual((ko.FACTOR_MIN, ko.FACTOR_MAX), (0.85, 1.15))

    def test_formula_by_hand(self):
        # rate = (K + 1000 r) / (PA + 1000); factor = rate / r
        out = ko.opponent_factor(team_k=450, team_pa=2000, league_rate=0.2)
        rate = (450 + 1000 * 0.2) / (2000 + 1000)
        self.assertAlmostEqual(out["opp_rate"], rate, places=12)
        self.assertAlmostEqual(out["factor"], rate / 0.2, places=12)
        self.assertIsNone(out["bounded"])

    def test_no_history_is_exactly_one(self):
        out = ko.opponent_factor(0, 0, 0.22)
        self.assertEqual(out["factor"], 1.0)
        self.assertIsNone(out["bounded"])

    def test_league_rate_team_is_one_and_more_data_moves_it_further(self):
        self.assertAlmostEqual(ko.opponent_factor(220, 1000, 0.22)["factor"], 1.0)
        small = ko.opponent_factor(30, 100, 0.2)["factor"]
        large = ko.opponent_factor(300, 1000, 0.2)["factor"]
        self.assertTrue(1.0 < small < large)

    def test_bound_binds_and_is_reported(self):
        high = ko.opponent_factor(5000, 5000, 0.2)
        low = ko.opponent_factor(0, 50000, 0.2)
        self.assertEqual(high["factor"], 1.15)
        self.assertEqual(high["bounded"], "high")
        self.assertGreater(high["raw_factor"], 1.15)
        self.assertEqual(low["factor"], 0.85)
        self.assertEqual(low["bounded"], "low")

    def test_unusable_inputs_raise_not_guess(self):
        for args in ((1, 2, 0.0), (1, 2, None), (1, 2, float("nan")),
                     (5, 2, 0.2), (-1, 2, 0.2)):
            with self.assertRaises(ko.KOpponentError):
                ko.opponent_factor(*args)

    def test_candidate_is_baseline_rate_times_factor_times_expected_bf(self):
        out = ko.opponent_candidate_prediction(0.25, 20.0, 1.1)
        self.assertAlmostEqual(out["expected"], 0.25 * 1.1 * 20.0)
        self.assertAlmostEqual(out["over"]["4.5"],
                               kb.poisson_over(0.25 * 1.1 * 20.0, 4.5))
        same = ko.opponent_candidate_prediction(0.25, 20.0, 1.0)
        self.assertEqual(same["over"]["5.5"], kb.poisson_over(5.0, 5.5))

    def test_a_strikeout_prone_opponent_raises_over_and_a_contact_team_lowers_it(self):
        base = kb.poisson_over(5.0, 4.5)
        up = ko.opponent_candidate_prediction(0.25, 20.0, 1.15)["over"]["4.5"]
        down = ko.opponent_candidate_prediction(0.25, 20.0, 0.85)["over"]["4.5"]
        self.assertGreater(up, base)
        self.assertLess(down, base)


class PointInTimeTests(unittest.TestCase):
    def test_a_games_outcome_never_feeds_a_start_dated_on_or_before_it(self):
        world = World()
        full = _by_key(world.build()["rows"])
        cutoff = world.dates[50]
        changed = []
        for r in world.bullpen_rows:
            if r["date"] >= cutoff:
                r = dict(r, strikeouts=r["batters_faced"] // 2)
            changed.append(r)
        # Pitcher-log outcomes change too, so only the target changes after cutoff.
        changed_logs = [dict(r, strikeouts=r["batters_faced"] // 2)
                        if r["date"] >= cutoff else r for r in world.pitcher_rows]
        alt = _by_key(world.build(pitcher_rows=changed_logs, bullpen_rows=changed)["rows"])
        before = [k for k in full if k[1] <= cutoff]
        self.assertTrue(before)
        for key in before:
            for field in ("factor", "opp_pa", "opp_k", "r_ref", "p_base_4.5",
                          "p_cand_4.5", "p_base_5.5", "p_cand_5.5", "opp_games"):
                self.assertEqual(full[key][field], alt[key][field], (key, field))
        after = [k for k in full if k[1] > cutoff]
        self.assertTrue(any(full[k]["factor"] != alt[k]["factor"] for k in after))

    def test_deleting_the_future_changes_nothing_before_it(self):
        world = World()
        full = _by_key(world.build()["rows"])
        cutoff = world.dates[60]
        kept_b = [r for r in world.bullpen_rows if r["date"] <= cutoff]
        kept_p = [r for r in world.pitcher_rows if r["date"] <= cutoff]
        cut = _by_key(world.build(pitcher_rows=kept_p, bullpen_rows=kept_b)["rows"])
        self.assertTrue(cut)
        for key, row in cut.items():
            self.assertEqual(row, full[key])

    def test_the_opponent_record_is_exactly_the_games_strictly_before(self):
        world = World(days=40)
        extracted = world.games()
        events = ko.batting_events(extracted["games"], 2023)
        rows = world.build()["rows"]
        self.assertTrue(rows)
        for row in rows[::7]:
            expected = [e for e in events
                        if e[0] < row["date"] and e[2] == row["opponent"]]
            self.assertEqual(row["opp_games"], len(expected))
            self.assertEqual(row["opp_k"], sum(e[3] for e in expected))
            self.assertEqual(row["opp_pa"], sum(e[4] for e in expected))
            league = [e for e in events if e[0] < row["date"]]
            self.assertAlmostEqual(
                row["r_ref"], sum(e[3] for e in league) / sum(e[4] for e in league))

    def test_a_same_day_game_never_feeds_a_same_day_start(self):
        """A second game the same day (a doubleheader) is not history for the
        first game's start, and vice versa."""
        rows = []
        for pk, (pid_a, pid_b) in ((11, (1, 2)), (12, (3, 4))):
            for pid, team in ((pid_a, "A"), (pid_b, "B")):
                rows.append({"person_id": pid, "game_pk": pk, "date": "2023-06-01",
                             "team": team, "started": True,
                             "strikeouts": 15 if pk == 11 else 0, "batters_faced": 20})
        extracted = ko.extract_games(rows, {11: "2023-06-01", 12: "2023-06-01"})
        events = ko.batting_events(extracted["games"], 2023)
        history = ko.OpponentHistory(events)
        history.advance_to("2023-06-01")
        self.assertEqual(history.team_record("A"), (0, 0, 0))
        self.assertIsNone(history.league_rate())
        history.advance_to("2023-06-02")
        self.assertEqual(history.team_record("A")[1], 40)

    def test_history_cannot_go_backwards(self):
        history = ko.OpponentHistory([])
        history.advance_to("2023-06-02")
        with self.assertRaises(ko.KOpponentError):
            history.advance_to("2023-06-01")

    def test_prior_season_rate_is_used_only_for_the_prior_season_pool(self):
        w23, w24 = World(2023, seed=3, days=60), World(2024, seed=4, days=60)
        games = {}
        games.update(w23.games()["games"])
        games.update(w24.games()["games"])
        starts = w23.starts() + w24.starts()
        regular = {**w23.regular, **w24.regular}
        extracted = ko.extract_games(w23.bullpen_rows + w24.bullpen_rows, regular)
        attached = ko.attach_opponents(starts, extracted)
        built = ko.build_opponent_rows(
            season=2024, starts=starts, games=extracted["games"],
            opponents=attached["opponents"], causes=attached["causes"],
            min_league_starts=200)
        prior_rate = ko.season_league_rate(extracted["games"], 2023)
        pools = {r["pool"] for r in built["rows"]}
        self.assertEqual(pools, {"prior_season", "same_season"})
        for row in built["rows"]:
            if row["pool"] == "prior_season":
                self.assertEqual(row["r_ref"], prior_rate)
            else:
                self.assertNotEqual(row["r_ref"], prior_rate)

    def test_a_2023_run_never_reads_2024_rows(self):
        w23, w24 = World(2023, seed=3, days=60), World(2024, seed=4, days=60)
        alone = w23.build()
        starts = w23.starts() + w24.starts()
        regular = {**w23.regular, **w24.regular}
        poisoned_b = [dict(r, strikeouts=r["batters_faced"]) for r in w24.bullpen_rows]
        extracted = ko.extract_games(w23.bullpen_rows + poisoned_b, regular)
        attached = ko.attach_opponents(starts, extracted)
        mixed = ko.build_opponent_rows(
            season=2023, starts=starts, games=extracted["games"],
            opponents=attached["opponents"], causes=attached["causes"],
            min_league_starts=20)
        self.assertEqual(alone["rows"], mixed["rows"])


class TwoArmsTests(unittest.TestCase):
    def test_baseline_probabilities_are_the_k_baseline_candidate_probabilities(self):
        world = World()
        built = world.build()
        reference = _by_key(kb.build_comparison_rows(
            season=2023, starts=world.starts(), min_league_starts=20)["rows"])
        self.assertTrue(built["rows"])
        for row in built["rows"]:
            ref = reference[(row["person_id"], row["date"])]
            for L in kb.LINES:
                key = kb.line_key(L)
                self.assertEqual(row[f"p_base_{key}"], ref[f"p_cand_{key}"])
            self.assertEqual(row["e_base"], ref["e_cand"])
            self.assertEqual(row["pool"], ref["pool"])
            self.assertEqual(row["prior_starts"], ref["prior_starts"])

    def test_arms_differ_only_by_the_opponent_factor(self):
        built = World().build()
        self.assertTrue(built["rows"])
        for row in built["rows"]:
            self.assertAlmostEqual(row["e_cand"], row["e_base"] * row["factor"],
                                   places=10)
            rebuilt = ko.opponent_candidate_prediction(
                row["k_rate"], row["expected_bf"], row["factor"])
            for L in kb.LINES:
                key = kb.line_key(L)
                self.assertEqual(row[f"p_cand_{key}"], rebuilt["over"][key])
            self.assertAlmostEqual(row["e_base"], row["k_rate"] * row["expected_bf"],
                                   places=10)

    def test_with_the_factor_switched_off_the_arms_coincide_exactly(self):
        # A prior weight so large that every factor is 1 to machine precision.
        built = World().build(prior_pa=1e18)
        self.assertTrue(built["rows"])
        for row in built["rows"]:
            self.assertAlmostEqual(row["factor"], 1.0, places=12)
            for L in kb.LINES:
                key = kb.line_key(L)
                self.assertAlmostEqual(row[f"p_base_{key}"], row[f"p_cand_{key}"],
                                       places=9)
                self.assertAlmostEqual(row[f"d_{key}"], 0.0, places=9)

    def test_a_start_with_no_opponent_history_gets_factor_one(self):
        built = World().build()
        firsts = [r for r in built["rows"] if r["opp_games"] == 0]
        for row in firsts:
            self.assertEqual(row["factor"], 1.0)
            self.assertEqual(row["p_base_4.5"], row["p_cand_4.5"])

    def test_the_strikeout_prone_team_gets_a_higher_factor_than_the_contact_team(self):
        built = World(days=90).build()
        late = [r for r in built["rows"] if r["opp_games"] >= 30]
        self.assertTrue(late)
        hhh = [r["factor"] for r in late if r["opponent"] == "HHH"]
        aaa = [r["factor"] for r in late if r["opponent"] == "AAA"]
        self.assertTrue(hhh and aaa)
        self.assertGreater(min(hhh), max(aaa))

    def test_one_row_per_start_with_both_arms_in_it(self):
        built = World().build()
        rows = built["rows"]
        keys = [(r["person_id"], r["date"]) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))
        for r in rows:
            for L in kb.LINES:
                key = kb.line_key(L)
                for field in (f"y_{key}", f"p_base_{key}", f"p_cand_{key}",
                              f"d_{key}"):
                    self.assertIn(field, r)
                self.assertEqual(r[f"y_{key}"], int(r["k"] >= kb.over_threshold(L)))
                self.assertAlmostEqual(
                    r[f"d_{key}"],
                    kb.log_loss_one(r[f"p_base_{key}"], r[f"y_{key}"])
                    - kb.log_loss_one(r[f"p_cand_{key}"], r[f"y_{key}"]), places=12)

    def test_coverage_adds_up_and_the_dropped_starts_leave_both_arms(self):
        world = World()
        regular = {pk: d for pk, d in world.regular.items()}
        dropped_pk = sorted(regular)[200]
        del regular[dropped_pk]           # its rows become 'not a regular game'
        extracted = world.games(regular=regular)
        starts = world.starts()
        attached = ko.attach_opponents(starts, extracted)
        built = ko.build_opponent_rows(
            season=2023, starts=starts, games=extracted["games"],
            opponents=attached["opponents"], causes=attached["causes"],
            min_league_starts=20)
        c = built["counts"]
        self.assertGreater(c["excluded_no_opponent"], 0)
        self.assertEqual(c["scored"] + c["excluded_no_opponent"], c["baseline_scored"])
        self.assertEqual(c["excluded_no_game_match"], c["excluded_no_opponent"])
        self.assertEqual(len(built["rows"]), c["scored"])
        # The baseline arm is untouched by the missing game: same pool, same rows.
        full = _by_key(World().build()["rows"])
        for row in built["rows"]:
            ref = full[(row["person_id"], row["date"])]
            for L in kb.LINES:
                key = kb.line_key(L)
                self.assertEqual(row[f"p_base_{key}"], ref[f"p_base_{key}"])
        self.assertEqual(len(built["baseline_rows"]), c["baseline_scored"])

    def test_counts_report_bounded_and_exactly_one_shares(self):
        built = World().build()
        c, rows = built["counts"], built["rows"]
        self.assertEqual(c["factor_exactly_one"],
                         sum(1 for r in rows if r["factor"] == 1.0))
        self.assertEqual(c["bounded_low"], sum(1 for r in rows if r["bounded"] == "low"))
        self.assertEqual(c["bounded_high"], sum(1 for r in rows if r["bounded"] == "high"))

    def test_limit_scores_a_slice_only(self):
        self.assertEqual(len(World().build(limit=5)["rows"]), 5)


class SignAndDecisionTests(unittest.TestCase):
    def test_rule_is_the_registered_rule(self):
        self.assertIs(ko.decide, kb.decide)
        first = {"4.5": {"estimate": 0.001, "low": -0.001, "high": 0.002},
                 "5.5": {"estimate": 0.001, "low": -0.001, "high": 0.002}}
        confirming = {"4.5": {"estimate": 0.002, "low": 0.0005, "high": 0.004},
                      "5.5": {"estimate": 0.002, "low": 0.0003, "high": 0.004}}
        self.assertEqual(ko.decide(first, confirming)["verdict"], ko.SUPPORTED)
        confirming["5.5"]["low"] = -0.0001
        self.assertEqual(ko.decide(first, confirming)["verdict"], ko.NOT_SUPPORTED)
        first["4.5"]["estimate"] = 0.0
        confirming["5.5"]["low"] = 0.0003
        self.assertEqual(ko.decide(first, confirming)["verdict"], ko.NOT_SUPPORTED)
        worse = {k: {"estimate": -0.002, "low": -0.004, "high": -0.0005}
                 for k in ("4.5", "5.5")}
        self.assertEqual(ko.decide(first, worse)["verdict"], ko.WORSE)

    def test_positive_d_means_the_candidate_was_better(self):
        # y = 1: the candidate that put more probability on Over wins.
        self.assertGreater(kb.paired_difference(0.4, 0.6, 1), 0.0)
        self.assertLess(kb.paired_difference(0.6, 0.4, 1), 0.0)
        self.assertGreater(kb.paired_difference(0.6, 0.4, 0), 0.0)

    def test_the_bootstrap_is_the_repos_own_clustered_bootstrap(self):
        rng = random.Random(3)
        rows = []
        for i in range(25):
            for _ in range(rng.randint(3, 9)):
                rows.append({"date": f"2023-05-{i + 1:02d}",
                             "d": rng.gauss(0.001, 0.02)})
        mine = kb.clustered_mean_interval(
            kb.per_date_aggregates(rows, "d"), resamples=500, seed=99)
        theirs = discovery.clustered_bootstrap(
            rows, lambda sample: sum(r["d"] for r in sample) / len(sample),
            resamples=500, seed=99)
        self.assertAlmostEqual(mine["low"], theirs["low"], places=5)
        self.assertAlmostEqual(mine["high"], theirs["high"], places=5)
        self.assertEqual((ko.BOOTSTRAP_RESAMPLES, ko.BOOTSTRAP_SEED), (2000, 20261004))


class SummaryTests(unittest.TestCase):
    def test_summary_shape_and_values(self):
        rows = World().build()["rows"]
        summary = ko.summarise_season(rows)
        block = summary["all_scored"]
        for key in ("3.5", "4.5", "5.5", "6.5"):
            line = block["lines"][key]
            self.assertEqual(line["n"], len(rows))
            expect = sum(r[f"d_{key}"] for r in rows) / len(rows)
            self.assertAlmostEqual(line["paired"]["estimate"], expect, places=12)
            self.assertAlmostEqual(
                line["log_loss_baseline"] - line["log_loss_candidate"], expect,
                places=10)
        self.assertEqual(summary["factor"]["n"], len(rows))
        self.assertLessEqual(summary["factor"]["max"], ko.FACTOR_MAX)
        self.assertGreaterEqual(summary["factor"]["min"], ko.FACTOR_MIN)
        self.assertLessEqual(summary["opponent_history_at_least_1000_pa_descriptive"]
                             ["lines"]["4.5"]["n"], len(rows))

    def test_empty_rows_summarise_without_raising(self):
        out = ko.summarise_season([])
        self.assertEqual(out["all_scored"]["lines"]["4.5"]["n"], 0)
        self.assertEqual(out["factor"]["n"], 0)


class ScriptArtifactTests(unittest.TestCase):
    def _write_world(self, directory, world, extra_sealed=True):
        def dump(name, rows, sealed):
            path = os.path.join(directory, name)
            with open(path, "w", encoding="utf-8", newline="") as fh:
                for r in rows:
                    fh.write(json.dumps(r) + "\n")
                if extra_sealed:
                    for line in sealed:
                        fh.write(line + "\n")
            return path
        sealed = ['{"date": "2026-08-12", "person_id": 1, BROKEN',
                  '{"date": "2025-06-01", "person_id": 1, BROKEN']
        logs = dump("pitcher_logs.jsonl", world.pitcher_rows, sealed)
        bullpen = dump("bullpen_log.jsonl", world.bullpen_rows, sealed)
        results = os.path.join(directory, "mlb_results.csv")
        with open(results, "w", encoding="utf-8", newline="") as fh:
            fh.write("game_pk,date,start_time_utc,venue,game_type,away_team,home_team\n")
            for pk, date in sorted(world.regular.items()):
                fh.write(f"{pk},{date},x,v,R,A,B\n")
            fh.write("9999901,2026-08-12,x,v,R,A,B\n")
            fh.write("9999902,2025-06-01,x,v,R,A,B\n")
        return logs, bullpen, results

    def test_run_reads_no_sealed_row_and_prints_none(self):
        script = _load_script()
        world = World(days=100)
        with tempfile.TemporaryDirectory() as tmp:
            logs, bullpen, results = self._write_world(tmp, world)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rows, counts, meta, base = script.run(
                    2023, logs_path=logs, bullpen_path=bullpen, results_path=results)
            self.assertTrue(rows)
            self.assertEqual(meta["years_read"], [2023])
            self.assertEqual(meta["inputs"]["regular_games_in_results"], len(world.regular))
            self.assertEqual(meta["inputs"]["pitcher_logs_rows_read"]["rows"],
                             len(world.pitcher_rows))
            self.assertEqual(meta["inputs"]["bullpen_log_rows_read"]["rows"],
                             len(world.bullpen_rows))
            self.assertNotIn("2026", buf.getvalue() + json.dumps(meta))
            self.assertNotIn("2025", json.dumps(meta))
            self.assertTrue(all(r["date"].startswith("2023") for r in rows))

    def test_script_writes_an_artifact_and_refuses_to_overwrite_it(self):
        script = _load_script()
        world = World(days=100)
        with tempfile.TemporaryDirectory() as tmp:
            logs, bullpen, results = self._write_world(tmp, world)
            out = os.path.join(tmp, "k_opponent_2023.json")
            patched = {"PITCHER_LOGS_PATH": logs, "BULLPEN_LOG_PATH": bullpen,
                       "RESULTS_PATH": results,
                       "BASELINE_ARTIFACT_DIR": os.path.join(tmp, "none")}
            with mock.patch.multiple(script, **patched):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(script.main(["--season", "2023", "--out", out]), 0)
                with open(out, encoding="utf-8") as fh:
                    art = json.load(fh)
                self.assertEqual(art["rule_id"], "K_OPPONENT_V1")
                self.assertEqual(art["fixed_parameters"]["opp_prior_pa"], 1000.0)
                self.assertEqual(art["fixed_parameters"]["factor_min"], 0.85)
                self.assertEqual(art["fixed_parameters"]["factor_max"], 1.15)
                self.assertEqual(art["bootstrap"]["seed"], 20261004)
                self.assertFalse(art["baseline_reconciliation"]["checked"])
                self.assertIn("4.5", art["summary"]["all_scored"]["lines"])
                self.assertNotIn("2026-08", json.dumps(art))
                with mock.patch("sys.stderr"):
                    self.assertEqual(
                        script.main(["--season", "2023", "--out", out]), 2)

    def test_reconciliation_detects_the_registered_baseline(self):
        script = _load_script()
        world = World(days=100)
        with tempfile.TemporaryDirectory() as tmp:
            logs, bullpen, results = self._write_world(tmp, world, extra_sealed=False)
            with contextlib.redirect_stdout(io.StringIO()):
                rows, counts, meta, base = script.run(
                    2023, logs_path=logs, bullpen_path=bullpen, results_path=results)
            digest = script._digest(
                {k: r[k] for k in script.BASELINE_ROW_KEYS} for r in base)
            os.makedirs(os.path.join(tmp, "kb"))
            with open(os.path.join(tmp, "kb", "k_baseline_2023.json"), "w") as fh:
                json.dump({"row_digest": digest}, fh)
            ok = script.baseline_reconciliation(2023, base, os.path.join(tmp, "kb"))
            self.assertTrue(ok["checked"] and ok["equal"])
            tampered = copy.deepcopy(base)
            tampered[0]["p_cand_4.5"] += 1e-9
            bad = script.baseline_reconciliation(2023, tampered, os.path.join(tmp, "kb"))
            self.assertFalse(bad["equal"])

    def test_verdict_mode_applies_the_rule_to_the_two_artifacts(self):
        script = _load_script()

        def art(low, est, high):
            paired = {"estimate": est, "low": low, "high": high}
            lines = {k: {"paired": dict(paired)} for k in ("3.5", "4.5", "5.5", "6.5")}
            return {"summary": {"all_scored": {"lines": lines}}}
        with tempfile.TemporaryDirectory() as tmp:
            for season, a in ((2023, art(-0.001, 0.0005, 0.002)),
                              (2024, art(0.0002, 0.001, 0.002))):
                with open(os.path.join(tmp, f"k_opponent_{season}.json"), "w") as fh:
                    json.dump(a, fh)
            self.assertEqual(script.apply_rule(tmp)["verdict"], ko.SUPPORTED)
            with open(os.path.join(tmp, "k_opponent_2024.json"), "w") as fh:
                json.dump(art(-0.001, 0.0, 0.002), fh)
            self.assertEqual(script.apply_rule(tmp)["verdict"], ko.NOT_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
