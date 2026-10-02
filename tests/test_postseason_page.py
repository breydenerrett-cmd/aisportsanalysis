"""tests/test_postseason_page.py -- the public postseason page.

Every team here is a placeholder (A1..A6 in the "American" league, N1..N6 in
the "National"): the builder is generic over whatever field the standings
give it, and these tests exist to prove the STATE LOGIC and the honesty
rules, not to say anything about a real club:

  * series state (complete / live / upcoming / waiting) from the results store
  * only COMPLETED series advance a team
  * every probability is in [0, 1] and sums to what the bracket requires
  * announced starters are MODEL-USED, projected ones SCENARIO INPUT, and a
    start dated after `now` is never treated as known
  * an undeterminable field returns the honest-absence payload
  * /postseason is public and never a 500
  * the snapshot script is idempotent per day and its chain verifies
  * the daily loop runs the snapshot after the results catch-up
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.analysis import postseason_config as pc
from src.ledger.chain import HashChainLedger
from src.report import postseason_page as page

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
SEASON = "2026"

AL = [f"A{i}" for i in range(1, 7)]
NL = [f"N{i}" for i in range(1, 7)]


# ---------------------------------------------------------------------------
# synthetic data
# ---------------------------------------------------------------------------

def _rotation(team):
    """Five starter ids per team, stable and unique."""
    index = (AL + NL).index(team)
    return [100000 + index * 10 + slot for slot in range(5)]


def _row(pk, day, game_type, away, home, away_score, home_score, away_sp, home_sp,
         number=1, start=None):
    return {
        "game_pk": str(pk), "date": day, "start_time_utc": start or f"{day}T23:05:00Z",
        "venue": f"{home} Park", "game_type": game_type,
        "away_team": away, "home_team": home,
        "away_probable": f"SP{away_sp}" if away_sp else None,
        "home_probable": f"SP{home_sp}" if home_sp else None,
        "away_probable_id": str(away_sp) if away_sp else None,
        "home_probable_id": str(home_sp) if home_sp else None,
        "away_score": str(away_score), "home_score": str(home_score),
        "winner": home if home_score > away_score else away,
        "home_won": "1" if home_score > away_score else "0",
        "game_number": str(number), "double_header": "N",
    }


def regular_season_rows():
    """~20 regular-season games per team through 2026-09-27, with the five
    starters rotating, so every club has a rotation pool and a run rate."""
    rng = random.Random(20260927)
    teams = AL + NL
    rows, pk = [], 1
    for round_no in range(20):
        order = teams[:]
        rng.shuffle(order)
        day = (date(2026, 8, 28) + timedelta(days=round_no)).isoformat()
        for i in range(0, 12, 2):
            away, home = order[i], order[i + 1]
            away_score, home_score = rng.randint(1, 7), rng.randint(1, 7)
            if away_score == home_score:
                home_score += 1
            rows.append(_row(pk, day, "R", away, home, away_score, home_score,
                             _rotation(away)[round_no % 5], _rotation(home)[round_no % 5]))
            pk += 1
    return rows


def pitcher_logs(last_day=28):
    """Season logs for every rotation starter, last entry dated 2026-09-<last_day>.
    The default (09-28) is two days behind the 09-30 `as_of` of the standard
    scenario, inside the 3-day window where nothing is called stale."""
    days = sorted(set(range(1, last_day, 3)) | {last_day})
    logs = {}
    for team in AL + NL:
        for slot, pid in enumerate(_rotation(team)):
            logs[str(pid)] = [{
                "person_id": pid, "date": f"2026-09-{d:02d}", "season": "2026",
                "is_home": bool(d % 2), "games_started": 1, "innings_pitched": 6.0,
                "earned_runs": 2 + (slot % 3), "runs": 2 + (slot % 3), "hits": 6,
                "walks": 2, "strikeouts": 6, "home_runs": 1, "batters_faced": 25,
                "pitches": 95} for d in days]
    return logs


def standings_rows(captured="2026-09-28T10:00:00+00:00", date="2026-09-28"):
    rows = []
    for league_id, teams in ((103, AL), (104, NL)):
        for i, team in enumerate(teams, start=1):
            leader = i <= 3
            # distinct records across both leagues, so no World Series pair
            # ties unless a test makes it
            wins = (100 if league_id == 103 else 99) - 3 * i
            rows.append({
                "team_abbrev": team, "team_name": f"Club{team}", "league_id": league_id,
                "division_leader": leader, "wildcard_rank": None if leader else i - 3,
                "wins": wins, "losses": 162 - wins,
                "win_pct": round(wins / 162, 3), "date": date, "captured_at": captured,
                "games_played": 162})
        rows.append({
            "team_abbrev": f"X{league_id}", "team_name": "Out", "league_id": league_id,
            "division_leader": False, "wildcard_rank": 4, "wins": 70, "losses": 92,
            "win_pct": .432, "date": date, "captured_at": captured, "games_played": 162})
    return rows


def _postseason(rows_spec):
    rows = []
    for index, spec in enumerate(rows_spec):
        rows.append(_row(900000 + index, *spec))
    return rows


def store_with(postseason_specs=(), extra=()):
    rows = regular_season_rows() + _postseason(postseason_specs) + list(extra)
    return {r["game_pk"]: r for r in rows}


# (date, type, away, home, away_score, home_score, away_sp, home_sp)
def scenario_specs():
    """AL 3v6 complete (A3 wins 2-0); AL 4v5 live 1-0 for A4; NL 3v6 complete
    with the No. 6 seed winning 2-1; NL 4v5 not started."""
    a3, a6 = _rotation("A3"), _rotation("A6")
    a4, a5 = _rotation("A4"), _rotation("A5")
    n3, n6 = _rotation("N3"), _rotation("N6")
    return [
        ("2026-09-29", "F", "A6", "A3", 1, 4, a6[0], a3[0]),
        ("2026-09-30", "F", "A6", "A3", 2, 3, a6[1], a3[1]),
        ("2026-09-29", "F", "A5", "A4", 2, 5, a5[0], a4[0]),
        ("2026-09-29", "F", "N6", "N3", 6, 2, n6[0], n3[0]),
        ("2026-09-30", "F", "N6", "N3", 1, 3, n6[1], n3[1]),
        ("2026-09-30", "F", "N6", "N3", 5, 4, n6[2], n3[2]),
    ]


def schedule_game(pk, day, away, home, away_sp, home_sp, game_type="F"):
    return {"game_pk": pk, "date": day, "start_time_utc": f"{day}T23:05:00Z",
            "state": "pending", "game_type": game_type, "venue": f"{home} Park",
            "away_team": away, "home_team": home,
            "away_probable_id": away_sp, "home_probable_id": home_sp,
            "away_probable": f"SP{away_sp}" if away_sp else None,
            "home_probable": f"SP{home_sp}" if home_sp else None}


def build(store=None, standings=None, probables=None, now=NOW, **kw):
    kw.setdefault("pitcher_logs", pitcher_logs())
    kw.setdefault("bullpen_log", [])
    kw.setdefault("ledger_rows", [])
    return page.build(
        now,
        results_store=store if store is not None else store_with(scenario_specs()),
        standings=standings if standings is not None else standings_rows(),
        probables=probables, **kw)


def _series(payload, sid_suffix):
    return next(s for s in payload["series"] if s["id"].endswith(sid_suffix))


class _Scenario(unittest.TestCase):
    """One build shared by every state assertion (a build prices ~25
    matchups; doing it per test would just be slow)."""

    @classmethod
    def setUpClass(cls):
        cls.probables = [
            schedule_game(1, "2026-10-01", "A5", "A4", _rotation("A5")[1], _rotation("A4")[1]),
            # a game FAR in the future with announced starters: still announced
            schedule_game(2, "2026-10-03", "N6", "N2", _rotation("N6")[3], None, "D"),
        ]
        cls.payload = build(probables=cls.probables)


# ---------------------------------------------------------------------------
# series state
# ---------------------------------------------------------------------------

class SeriesStateTests(_Scenario):

    def test_the_page_is_available_and_carries_the_required_fields(self):
        p = self.payload
        self.assertTrue(p["available"], p.get("reason"))
        for key in ("as_of", "model", "method", "caveats", "series", "teams", "built_at"):
            self.assertIn(key, p)
        self.assertEqual(p["as_of"], "2026-09-30")
        self.assertEqual(p["caveats"][0], page.CAVEAT)
        self.assertIn("no track record yet", p["caveats"][0])

    def test_a_completed_wild_card_series(self):
        s = _series(self.payload, "AL-WC-3v6")
        self.assertEqual(s["status"], "complete")
        self.assertEqual(s["winner"], "A3")
        self.assertEqual(s["final_score"], "A3 won 2-0")
        chances = {t["team"]: t["chance"] for t in s["teams"]}
        self.assertEqual(chances, {"A3": 1.0, "A6": 0.0})
        self.assertEqual(s["home_field"], "A3")

    def test_a_series_that_is_one_nothing(self):
        s = _series(self.payload, "AL-WC-4v5")
        self.assertEqual(s["status"], "live")
        self.assertEqual({t["team"]: t["wins"] for t in s["teams"]}, {"A4": 1, "A5": 0})
        self.assertEqual(s["score_text"], "A4 leads 1-0")
        chances = {t["team"]: t["chance"] for t in s["teams"]}
        self.assertAlmostEqual(sum(chances.values()), 1.0, places=5)
        self.assertGreater(chances["A4"], 0.5)   # up 1-0 AND hosting both remaining games

    def test_an_unstarted_series(self):
        s = _series(self.payload, "NL-WC-4v5")
        self.assertEqual(s["status"], "upcoming")
        self.assertEqual({t["team"]: t["wins"] for t in s["teams"]}, {"N4": 0, "N5": 0})
        self.assertEqual(s["score_text"], "Series not started")

    def test_an_upset_is_reported_as_the_actual_winner(self):
        s = _series(self.payload, "NL-WC-3v6")
        self.assertEqual(s["status"], "complete")
        self.assertEqual(s["winner"], "N6")
        self.assertEqual(s["final_score"], "N6 won 2-1")

    def test_a_division_series_with_a_decided_opponent_is_upcoming(self):
        s = _series(self.payload, "AL-DS-2")
        self.assertEqual(s["status"], "upcoming")
        self.assertEqual({t["team"] for t in s["teams"]}, {"A2", "A3"})
        self.assertEqual(s["home_field"], "A2")
        nl = _series(self.payload, "NL-DS-2")
        self.assertEqual({t["team"] for t in nl["teams"]}, {"N2", "N6"})

    def test_a_division_series_waiting_on_an_undecided_wild_card(self):
        s = _series(self.payload, "AL-DS-1")
        self.assertEqual(s["status"], "waiting")
        self.assertEqual([t["team"] for t in s["teams"]], ["A1"])
        self.assertEqual(s["waiting_on"], [_series(self.payload, "AL-WC-4v5")["id"]])
        self.assertIsNone(s["teams"][0]["chance"])

    def test_later_rounds_are_waiting_with_no_invented_teams(self):
        for suffix in ("AL-LCS-1", "NL-LCS-1", "MLB-WS-1"):
            s = _series(self.payload, suffix)
            self.assertEqual(s["status"], "waiting", suffix)
            self.assertEqual(s["teams"], [], suffix)

    def test_only_completed_series_advance_a_team(self):
        teams = {t["team"]: t for t in self.payload["teams"]}
        # eliminated only where a series is complete and they lost
        self.assertEqual(teams["A6"]["status"], "eliminated")
        self.assertEqual(teams["N3"]["status"], "eliminated")
        for alive in ("A3", "N6", "A4", "A5", "N4", "N5", "A1", "A2", "N1", "N2"):
            self.assertEqual(teams[alive]["status"], "alive", alive)
        # the live A4-A5 series has not eliminated anyone
        self.assertEqual(teams["A5"]["wins_pennant"] > 0, True)
        # an eliminated club has no chance of anything
        for key in ("reaches_division_series", "reaches_lcs", "wins_pennant", "wins_world_series"):
            self.assertEqual(teams["A6"][key] if key != "reaches_division_series" else 0.0, 0.0)
        self.assertEqual(teams["N3"]["reaches_division_series"], 0.0)

    def test_a_decided_wild_card_winner_reaches_the_division_series_for_certain(self):
        teams = {t["team"]: t for t in self.payload["teams"]}
        self.assertEqual(teams["A3"]["reaches_division_series"], 1.0)
        self.assertEqual(teams["N6"]["reaches_division_series"], 1.0)
        self.assertEqual(teams["A1"]["reaches_division_series"], 1.0)

    def test_the_live_round_is_the_earliest_unfinished_one(self):
        self.assertEqual(self.payload["live_round"], "WC")


# ---------------------------------------------------------------------------
# probabilities
# ---------------------------------------------------------------------------

class ProbabilityTests(_Scenario):

    def test_every_number_is_a_probability(self):
        for s in self.payload["series"]:
            for t in s["teams"]:
                if t["chance"] is not None:
                    self.assertTrue(0.0 <= t["chance"] <= 1.0, (s["id"], t))
            for g in s["games"]:
                if "home_chance" in g:
                    self.assertTrue(0.0 < g["home_chance"] < 1.0, (s["id"], g))
                    self.assertAlmostEqual(g["home_chance"] + g["away_chance"], 1.0, places=5)
        for t in self.payload["teams"]:
            for key in ("reaches_division_series", "reaches_lcs", "wins_pennant",
                        "wins_world_series"):
                self.assertTrue(0.0 <= t[key] <= 1.0, (t["team"], key))

    def test_two_sides_of_a_series_sum_to_one(self):
        for s in self.payload["series"]:
            if len(s["teams"]) == 2:
                self.assertAlmostEqual(sum(t["chance"] for t in s["teams"]), 1.0, places=5, msg=s["id"])

    def test_the_bracket_sums_exactly(self):
        teams = self.payload["teams"]
        by_league = {lg: [t for t in teams if t["league"] == lg] for lg in ("AL", "NL")}
        for lg, rows in by_league.items():
            self.assertAlmostEqual(sum(t["reaches_division_series"] for t in rows), 4.0, places=5, msg=lg)
            self.assertAlmostEqual(sum(t["reaches_lcs"] for t in rows), 2.0, places=5, msg=lg)
            self.assertAlmostEqual(sum(t["wins_pennant"] for t in rows), 1.0, places=5, msg=lg)
        self.assertAlmostEqual(sum(t["wins_world_series"] for t in teams), 1.0, places=5)

    def test_the_table_is_sorted_by_world_series_chance(self):
        values = [t["wins_world_series"] for t in self.payload["teams"]]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_the_series_number_conditions_on_the_score(self):
        """A4 up 1-0 must be better off than the same series at 0-0."""
        fresh = build(store=store_with([s for s in scenario_specs() if s[2:4] != ("A5", "A4")]),
                      probables=[])
        before = {t["team"]: t["chance"] for t in _series(fresh, "AL-WC-4v5")["teams"]}
        after = {t["team"]: t["chance"] for t in _series(self.payload, "AL-WC-4v5")["teams"]}
        self.assertGreater(after["A4"], before["A4"])

    def test_the_page_matches_the_solver_called_directly(self):
        """The number on the page is `conditional_series_win_prob` over the
        per-game numbers on the page, not a second formula."""
        from src.analysis import matchup_model as mm
        s = _series(self.payload, "AL-WC-4v5")
        a, b = s["teams"][0], s["teams"][1]
        remaining = [g for g in s["games"] if g.get("status") in ("next", "future")]
        probs = [g["home_chance"] if g["home"] == a["team"] else g["away_chance"]
                 for g in remaining]
        expected = mm.conditional_series_win_prob(probs, a["wins"], b["wins"], 2)
        self.assertAlmostEqual(a["chance"], expected, places=4)


# ---------------------------------------------------------------------------
# starters: known vs projected
# ---------------------------------------------------------------------------

class StarterLabelTests(_Scenario):

    def test_an_announced_game_is_model_used(self):
        s = _series(self.payload, "AL-WC-4v5")
        nxt = s["next_game"]
        self.assertEqual(nxt["number"], 2)
        self.assertEqual(nxt["starter_label"], page.MODEL_USED)
        self.assertEqual(nxt["starters"]["home"]["source"], "actual")
        self.assertEqual(nxt["starters"]["home"]["id"], _rotation("A4")[1])
        self.assertEqual(nxt["date"], "2026-10-01")

    def test_a_game_with_no_announcement_is_a_scenario_input(self):
        s = _series(self.payload, "AL-WC-4v5")
        game3 = next(g for g in s["games"] if g["number"] == 3)
        self.assertEqual(game3["starter_label"], page.SCENARIO_INPUT)
        # CHANGED (owner rule 2026-10-01): a projected pitcher is never shown
        # in the starter slot; the side the schedule has not named is TBD.
        # old: source == "projected" on both sides
        for side in ("home", "away"):
            self.assertIsNone(game3["starters"][side]["source"])
            self.assertEqual(game3["starters"][side]["display"], "TBD")
        self.assertEqual(game3["starter_input_class"], page.PROJECTED_CURRENT)
        self.assertTrue(game3["if_needed"])

    def test_a_projected_starter_never_repeats_inside_the_rest_window(self):
        s = _series(self.payload, "AL-WC-4v5")
        game3 = next(g for g in s["games"] if g["number"] == 3)
        used = {_rotation("A4")[0], _rotation("A4")[1]}
        # CHANGED: the projected pitcher now lives only in the what-if line
        # (old: starters.home.id). The rest rule is unchanged.
        projected = game3["scenarios"][0]["starters"]["home"]["id"]
        self.assertIsNotNone(projected)
        self.assertNotIn(projected, used)

    def test_an_unstarted_series_with_nothing_announced_is_all_scenario(self):
        s = _series(self.payload, "NL-WC-4v5")
        self.assertTrue(s["games"])
        # nothing announced and nothing played: even game 1 is projected,
        # never presented as known
        for g in s["games"]:
            self.assertEqual(g["starter_label"], page.SCENARIO_INPUT, g["number"])
            for side in ("home", "away"):
                # CHANGED (old: source == "projected"): TBD, never a name
                self.assertIsNone(g["starters"][side]["source"])
                self.assertEqual(g["starters"][side]["display"], "TBD")

    def test_a_start_dated_after_now_is_not_read_as_known(self):
        """A results row for game 2 dated TOMORROW (a leak, or a clock
        problem) must change nothing: the row is excluded, the game stays
        a scenario."""
        leak = _row(990001, "2026-10-02", "F", "A5", "A4", 9, 0,
                    _rotation("A5")[1], _rotation("A4")[1])
        leaky = build(store=store_with(scenario_specs(), extra=[leak]), probables=[])
        s = _series(leaky, "AL-WC-4v5")
        self.assertEqual(s["status"], "live")
        self.assertEqual({t["team"]: t["wins"] for t in s["teams"]}, {"A4": 1, "A5": 0})
        game2 = next(g for g in s["games"] if g["number"] == 2)
        self.assertEqual(game2["starter_label"], page.SCENARIO_INPUT)
        # CHANGED (old: source == "projected"): the leaked row names nobody
        self.assertIsNone(game2["starters"]["home"]["source"])
        self.assertEqual(game2["starters"]["home"]["display"], "TBD")

    def test_a_starter_with_no_season_log_is_not_called_model_used(self):
        s = _series(build(probables=self.probables, pitcher_logs={}), "AL-WC-4v5")
        self.assertEqual(s["next_game"]["starter_label"], page.UNAVAILABLE)
        self.assertIsNotNone(s["next_game"]["starter_note"])

    def test_labels_are_the_matchup_models_own_vocabulary(self):
        from src.analysis import matchup_model as mm
        self.assertEqual((page.MODEL_USED, page.SCENARIO_INPUT, page.UNAVAILABLE),
                         (mm.MODEL_USED, mm.SCENARIO_INPUT, mm.UNAVAILABLE))


# ---------------------------------------------------------------------------
# honest absence
# ---------------------------------------------------------------------------

class HonestAbsenceTests(unittest.TestCase):

    def assertAbsent(self, payload, fragment=None):
        self.assertFalse(payload["available"])
        self.assertTrue(payload["reason"])
        self.assertEqual(payload["series"], [])
        self.assertEqual(payload["teams"], [])
        self.assertIn(page.CAVEAT, payload["caveats"])
        # What the reader sees is one of the builder's plain sentences; the
        # specifics (club codes, dates, store names) live in `detail`.
        self.assertIn(payload["reason"], page.PUBLIC_REASONS.values())
        if fragment:
            self.assertIn(fragment, payload["detail"])
        json.dumps(payload)

    def test_no_standings_at_all(self):
        self.assertAbsent(build(standings={}), "standings")

    def test_only_a_stale_standings_snapshot(self):
        stale = standings_rows(captured="2026-09-08T20:00:00+00:00", date="2026-09-08")
        payload = build(standings=stale)
        self.assertAbsent(payload, "2026-09-08")

    def test_a_standings_snapshot_from_the_last_evening_is_not_final(self):
        evening = standings_rows(captured="2026-09-27T23:00:00+00:00", date="2026-09-27")
        self.assertAbsent(build(standings=evening))

    def test_a_snapshot_the_morning_after_is_final(self):
        ok = standings_rows(captured="2026-09-28T09:00:00+00:00", date="2026-09-27")
        self.assertTrue(build(standings=ok)["available"])

    def test_a_tie_between_division_winners_is_not_guessed(self):
        rows = standings_rows()
        for r in rows:
            if r["team_abbrev"] in ("A1", "A2"):
                r["wins"], r["losses"] = 95, 67
        self.assertAbsent(build(standings=rows), "tiebreak")

    def test_a_game_that_fits_no_series_is_a_conflict_not_a_guess(self):
        stray = _row(990002, "2026-09-30", "F", "A1", "N1", 3, 2, None, None)
        self.assertAbsent(build(store=store_with(scenario_specs(), extra=[stray])), "fits no series")

    def test_division_series_games_before_the_feeding_series_is_done(self):
        early = _row(990003, "2026-09-30", "D", "A4", "A1", 3, 2, None, None)
        self.assertAbsent(build(store=store_with(scenario_specs(), extra=[early])), "Wild Card")

    def test_home_field_that_contradicts_the_seeds_is_a_conflict(self):
        specs = scenario_specs()
        specs[0] = ("2026-09-29", "F", "A3", "A6", 4, 1, None, None)  # No. 6 hosting
        self.assertAbsent(build(store=store_with(specs)), "home field")

    def test_a_game_after_a_series_was_won_is_a_conflict(self):
        extra = _row(990004, "2026-10-01", "F", "A6", "A3", 1, 0, None, None)
        self.assertAbsent(build(store=store_with(scenario_specs(), extra=[extra])), "already won")

    def test_a_results_store_that_stopped_advancing_is_not_shown_as_current(self):
        payload = build(results_through="2026-09-26")
        self.assertAbsent(payload, "2026-09-26")
        self.assertEqual(payload["missing"], "results")

    def test_one_day_of_lag_is_acceptable(self):
        self.assertTrue(build(results_through="2026-09-30")["available"])

    def test_a_seeded_club_missing_from_the_results_store(self):
        store = {k: r for k, r in store_with(scenario_specs()).items()
                 if "N4" not in (r["home_team"], r["away_team"])}
        self.assertAbsent(build(store=store), "N4")

    def test_before_the_postseason_the_page_shows_every_series_as_upcoming(self):
        payload = build(store=store_with(), now=datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc),
                        results_through="2026-09-27")
        self.assertTrue(payload["available"], payload.get("reason"))
        statuses = {s["id"].split("-", 2)[2]: s["status"] for s in payload["series"]}
        self.assertEqual(statuses["WC-3v6"], "upcoming")
        self.assertEqual(statuses["LCS-1"], "waiting")
        total = sum(t["wins_world_series"] for t in payload["teams"])
        self.assertAlmostEqual(total, 1.0, places=5)


# ---------------------------------------------------------------------------
# a full run through to the World Series
# ---------------------------------------------------------------------------

class CompletedBracketTests(unittest.TestCase):

    @staticmethod
    def _sweep(specs, day, game_type, hi, lo, hosts):
        """`hi` (the better seed) wins every game of a series, hosted as
        `hosts` says (a list of 'hi'/'lo')."""
        for offset, host in enumerate(hosts):
            home, away = (hi, lo) if host == "hi" else (lo, hi)
            hi_home = home == hi
            specs.append((f"2026-10-{day + offset:02d}", game_type, away, home,
                          1 if hi_home else 4, 4 if hi_home else 1, None, None))

    def test_a_champion_ends_with_all_the_chance_on_one_club(self):
        specs = scenario_specs()
        # finish the two wild card series that were still open
        specs += [("2026-09-29", "F", "N5", "N4", 1, 2, None, None),
                  ("2026-09-30", "F", "N5", "N4", 1, 2, None, None),
                  ("2026-09-30", "F", "A5", "A4", 1, 3, None, None)]      # A4 wins 2-0
        ds_hosts = ["hi", "hi", "lo"]                                      # 2-2-1, sweep ends in 3
        self._sweep(specs, 3, "D", "A1", "A4", ds_hosts)                   # AL: No. 1 vs the 4v5 winner
        self._sweep(specs, 3, "D", "A2", "A3", ds_hosts)                   # AL: No. 2 vs the 3v6 winner
        self._sweep(specs, 3, "D", "N1", "N4", ds_hosts)
        self._sweep(specs, 3, "D", "N2", "N6", ds_hosts)
        lcs_hosts = ["hi", "hi", "lo", "lo"]
        self._sweep(specs, 11, "L", "A1", "A2", lcs_hosts)
        self._sweep(specs, 11, "L", "N1", "N2", lcs_hosts)
        # World Series: A1 has the better record, hosts games 1-2, wins 4-0
        for offset, (home, away) in enumerate(
                [("A1", "N1"), ("A1", "N1"), ("N1", "A1"), ("N1", "A1")]):
            specs.append((f"2026-10-{23 + offset:02d}", "W", away, home,
                          1 if home == "A1" else 4, 4 if home == "A1" else 1, None, None))
        payload = page.build(
            datetime(2026, 11, 2, 15, tzinfo=timezone.utc),
            results_store=store_with(specs), standings=standings_rows(),
            probables=[], pitcher_logs=pitcher_logs(), bullpen_log=[], ledger_rows=[])
        self.assertTrue(payload["available"], payload.get("reason"))
        self.assertEqual(payload["champion"], "A1")
        teams = {t["team"]: t for t in payload["teams"]}
        self.assertEqual(teams["A1"]["status"], "champion")
        self.assertEqual(teams["A1"]["wins_world_series"], 1.0)
        self.assertAlmostEqual(sum(t["wins_world_series"] for t in payload["teams"]), 1.0, places=6)
        self.assertEqual(sum(1 for t in payload["teams"] if t["status"] == "alive"), 0)
        self.assertIsNone(payload["live_round"])
        ws = _series(payload, "MLB-WS-1")
        self.assertEqual(ws["status"], "complete")
        self.assertEqual(ws["home_field"], "A1")
        self.assertEqual(ws["final_score"], "A1 won 4-0")


# ---------------------------------------------------------------------------
# the forecast ledger and the "what we said before" line
# ---------------------------------------------------------------------------

class LedgerTests(unittest.TestCase):

    def test_snapshot_rows_cover_only_live_and_upcoming_series_with_two_teams(self):
        payload = build(probables=[])
        rows = page.snapshot_rows(payload, "2026-10-01")
        ids = {r["series_id"].split("-", 2)[2] for r in rows}
        self.assertEqual(ids, {"WC-4v5", "DS-2"} | {"WC-4v5"})
        # AL WC 4v5 (live), NL WC 4v5, AL DS 2, NL DS 2
        self.assertEqual(len(rows), 4)
        for r in rows:
            self.assertEqual(r["model"], page.MODEL_ID)
            self.assertEqual(r["date"], "2026-10-01")
            self.assertAlmostEqual(sum(r["series_chance"].values()), 1.0, places=5)
            self.assertEqual(r["games_played"], sum(r["wins"].values()))
        self.assertEqual(page.snapshot_rows(unavailable_payload(), "2026-10-01"), [])

    def test_a_completed_series_shows_what_the_page_said_before_game_one(self):
        ledger = [
            {"series_id": "2026-AL-WC-3v6", "date": "2026-09-28", "games_played": 0,
             "series_chance": {"A3": 0.64, "A6": 0.36}, "model": page.MODEL_ID},
            {"series_id": "2026-AL-WC-3v6", "date": "2026-09-29", "games_played": 1,
             "series_chance": {"A3": 0.80, "A6": 0.20}, "model": page.MODEL_ID},
            {"series_id": "2026-NL-WC-3v6", "date": "2026-09-28", "games_played": 0,
             "series_chance": {"N3": 0.70, "N6": 0.30}, "model": page.MODEL_ID},
        ]
        payload = build(ledger_rows=ledger)
        al = _series(payload, "AL-WC-3v6")["said_before"]
        self.assertEqual(al["date"], "2026-09-28")
        self.assertEqual(al["chance"], {"A3": 0.64, "A6": 0.36})
        self.assertEqual(al["favourite"], "A3")
        self.assertTrue(al["favourite_advanced"])
        nl = _series(payload, "NL-WC-3v6")["said_before"]
        self.assertEqual(nl["favourite"], "N3")
        self.assertFalse(nl["favourite_advanced"])      # the No. 6 seed won
        self.assertEqual(payload["scorecard"], {
            "completed_series": 2, "graded_before_game_one": 2, "favourite_advanced": 1})

    def test_a_series_with_no_row_before_game_one_says_so(self):
        mid_series_only = [{"series_id": "2026-AL-WC-3v6", "date": "2026-09-30",
                            "games_played": 1, "series_chance": {"A3": .8, "A6": .2}}]
        s = _series(build(ledger_rows=mid_series_only), "AL-WC-3v6")
        self.assertIsNone(s["said_before"])
        self.assertIn("No forecast was recorded before game 1", s["said_before_note"])

    def test_a_live_series_has_no_before_line(self):
        s = _series(build(ledger_rows=[]), "AL-WC-4v5")
        self.assertIsNone(s["said_before"])


def unavailable_payload():
    return page.unavailable("test")


# ---------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------

try:
    import fastapi  # noqa: F401
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False


def _asgi(app, path):
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": [], "client": ("127.0.0.1", 1),
             "server": ("testserver", 80)}
    out, parts = {}, []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
        elif message["type"] == "http.response.body":
            parts.append(message.get("body", b""))

    asyncio.new_event_loop().run_until_complete(app(scope, receive, send))
    return out["status"], json.loads(b"".join(parts))


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class RouteTests(unittest.TestCase):

    def setUp(self):
        from api import postseason as route
        self.route = route
        route.reset_cache_for_tests()

    def tearDown(self):
        self.route.reset_cache_for_tests()

    def test_the_route_is_public_in_the_real_app(self):
        from api.app import app
        with mock.patch.object(self.route, "_build_payload",
                               return_value={"available": False, "reason": "x", "caveats": []}):
            status, body = _asgi(app, "/postseason")
        self.assertEqual(status, 200)
        self.assertFalse(body["available"])
        self.assertNotEqual(status, 401)

    def test_the_route_is_not_in_the_paid_group(self):
        """No dependency on the route or on the way the app mounts it.
        FastAPI versions differ on how an included router shows up in
        `app.routes`, so both shapes are read."""
        from api.app import app
        own = [r for r in self.route.router.routes if getattr(r, "path", None) == "/postseason"]
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0].dependencies, [])
        self.assertEqual(list(own[0].dependant.dependencies), [])
        mounted = [r for r in app.routes if getattr(r, "original_router", None) is self.route.router]
        if mounted:
            self.assertEqual(mounted[0].include_context.dependencies, [])
        else:
            flat = [r for r in app.routes if getattr(r, "path", None) == "/postseason"]
            self.assertEqual(len(flat), 1)
            self.assertEqual(flat[0].dependencies, [])

    def test_a_builder_that_raises_returns_the_honest_payload_not_a_500(self):
        from api.app import app
        with mock.patch.object(self.route, "_build_payload", side_effect=RuntimeError("boom")):
            status, body = _asgi(app, "/postseason")
        self.assertEqual(status, 200)
        self.assertFalse(body["available"])
        self.assertIn("reason", body)
        self.assertIn(page.CAVEAT, body["caveats"])
        self.assertNotIn("boom", json.dumps(body))

    def test_a_good_build_is_served_and_cached_once(self):
        good = {"available": True, "as_of": "2026-09-30", "series": [], "teams": [],
                "caveats": [page.CAVEAT]}
        with mock.patch.object(self.route, "_build_payload", return_value=good) as built:
            first = self.route.get_postseason()
            second = self.route.get_postseason()
        self.assertEqual(built.call_count, 1)
        self.assertTrue(first["available"] and second["available"])
        self.assertIn("freshness", first)

    def test_a_failure_after_a_good_build_serves_the_last_good_value_flagged_stale(self):
        good = {"available": True, "as_of": "2026-09-30", "series": [], "teams": [],
                "caveats": [page.CAVEAT]}
        with mock.patch.object(self.route, "_build_payload", return_value=good):
            self.route.get_postseason()
        self.route._cache._entries[self.route.CACHE_KEY].built_at = datetime(
            2000, 1, 1, tzinfo=timezone.utc)
        with mock.patch.object(self.route, "_build_payload", side_effect=RuntimeError("boom")):
            out = self.route.get_postseason()
        self.assertTrue(out["available"])
        self.assertTrue(out["freshness"]["stale"])


# ---------------------------------------------------------------------------
# the snapshot script
# ---------------------------------------------------------------------------

class SnapshotScriptTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "postseason_forecasts.jsonl"
        sys.path.insert(0, str(ROOT / "scripts"))
        import postseason_snapshot
        self.script = postseason_snapshot
        self.payload = build(probables=[])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_appends_one_row_per_series_and_a_second_run_appends_nothing(self):
        first = self.script.snapshot(self.payload, "2026-10-01", self.path)
        self.assertEqual(first["appended"], 4)
        again = self.script.snapshot(self.payload, "2026-10-01", self.path)
        self.assertEqual(again["appended"], 0)
        self.assertEqual(again["already_written"], 4)
        self.assertEqual(len(HashChainLedger(self.path).read()), 4)

    def test_a_new_day_adds_a_new_row_per_series(self):
        self.script.snapshot(self.payload, "2026-10-01", self.path)
        nxt = self.script.snapshot(self.payload, "2026-10-02", self.path)
        self.assertEqual(nxt["appended"], 4)
        rows = HashChainLedger(self.path).read()
        self.assertEqual(len(rows), 8)
        keys = {(r["series_id"], r["date"]) for r in rows}
        self.assertEqual(len(keys), 8)

    def test_the_chain_verifies_and_an_edit_breaks_it(self):
        self.script.snapshot(self.payload, "2026-10-01", self.path)
        self.assertTrue(HashChainLedger(self.path).verify().ok)
        text = self.path.read_text(encoding="utf-8").replace("0.", "9.", 1)
        self.path.write_text(text, encoding="utf-8")
        self.assertFalse(HashChainLedger(self.path).verify().ok)

    def test_an_unavailable_page_writes_nothing(self):
        out = self.script.snapshot(page.unavailable("no standings"), "2026-10-01", self.path)
        self.assertEqual(out["appended"], 0)
        self.assertFalse(self.path.exists())

    def test_the_ledger_default_is_the_evidence_file(self):
        self.assertEqual(self.script.LEDGER_PATH.name, "postseason_forecasts.jsonl")
        self.assertEqual(self.script.LEDGER_PATH.parent.name, "evidence")


# ---------------------------------------------------------------------------
# daily loop wiring
# ---------------------------------------------------------------------------

def _bash():
    candidates = []
    if sys.platform == "win32":
        candidates += [r"C:\Program Files\Git\bin\bash.exe",
                       r"C:\Program Files\Git\usr\bin\bash.exe"]
    candidates.append(shutil.which("bash"))
    for path in candidates:
        if not path or not Path(path).exists():
            continue
        low = path.lower()
        if sys.platform == "win32" and ("windowsapps" in low or "system32" in low):
            continue
        return path
    return None


class DailyLoopWiringTests(unittest.TestCase):

    def setUp(self):
        self.text = (ROOT / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")

    def test_the_snapshot_runs_after_the_results_catch_up_and_before_the_commit(self):
        call = "python3 scripts/postseason_snapshot.py"
        self.assertIn(call, self.text)
        self.assertGreater(self.text.index(call), self.text.index("== results catch-up"))
        self.assertLess(self.text.index(call), self.text.index("git add data/processed"))

    def test_a_failure_escalates_and_does_not_stop_the_loop(self):
        self.assertIn('|| echo "ESCALATE: postseason snapshot failed"', self.text)

    def test_the_ledger_is_staged_by_the_existing_evidence_add(self):
        add = next(line for line in self.text.splitlines() if line.startswith("git add "))
        self.assertIn(" evidence ", add + " ")

    @unittest.skipUnless(_bash(), "no POSIX bash available")
    def test_the_script_still_parses(self):
        result = subprocess.run([_bash(), "-n", str(ROOT / "scripts" / "daily_loop.sh")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_script_file_is_lf(self):
        self.assertNotIn(b"\r\n", (ROOT / "scripts" / "daily_loop.sh").read_bytes())


# ---------------------------------------------------------------------------
# customer language
# ---------------------------------------------------------------------------

class CustomerLanguageTests(unittest.TestCase):

    def test_the_new_report_file_passes_the_customer_language_scan(self):
        import tests.test_customer_language as tcl
        path = ROOT / "src" / "report" / "postseason_page.py"
        self.assertTrue(path.is_file())
        violations = []
        token = tcl.re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
        for lineno, text in tcl._string_literals(path):
            violations.extend(tcl._violations_in(text, f"postseason_page.py:{lineno}"))
            if len(text.split()) >= 5:
                violations.extend(
                    f"postseason_page.py:{lineno} says {m.group(0)!r} in prose"
                    for m in token.finditer(text))
        self.assertEqual(violations, [])

    def test_the_payload_text_passes_the_same_scan(self):
        import tests.test_customer_language as tcl
        payload = build(probables=[])
        texts = [payload["method"], *payload["caveats"]]
        texts += [t["status_text"] for t in payload["teams"] if t["status_text"]]
        texts += [s.get("final_score") for s in payload["series"] if s.get("final_score")]
        violations = []
        for text in texts:
            violations.extend(tcl._violations_in(text, "payload"))
        self.assertEqual(violations, [])

    def test_the_required_caveat_is_verbatim(self):
        self.assertEqual(
            page.CAVEAT,
            "These are model estimates and can be wrong. They have no track record yet.")


class FormatSanityTests(unittest.TestCase):
    """The page leans on `postseason_config`; if that moves, say so here."""

    def test_the_round_formats_the_page_uses_match_the_config(self):
        self.assertEqual(page.ROUND_FORMAT["WC"]["k"], 2)
        self.assertEqual(page.ROUND_FORMAT["DS"]["k"], 3)
        self.assertEqual(page.ROUND_FORMAT["LCS"]["k"], 4)
        self.assertEqual(page.ROUND_FORMAT["WS"]["home_field_by"], pc.HOME_FIELD_BY_RECORD)

    def test_the_payload_is_json_serialisable(self):
        json.dumps(build(probables=[]))
        json.dumps(copy.deepcopy(page.unavailable("x", NOW)))



class FinalStandingsFromTheFeedTest(unittest.TestCase):
    """The store never holds a final table on its own: the daily job snapshots
    the last regular-season day in the morning, before its games, and the feed
    returns nothing for later dates. Found 2026-10-01, when the real page said
    "not available" three days into the postseason."""

    END = "2026-09-27"

    def _rows(self, n=30):
        return [{"team_abbrev": f"T{i:02d}", "wins": 90, "losses": 72} for i in range(n)]

    def _stale_store(self):
        # What the runner really has: the last day, captured that morning.
        return {self.END: {r["team_abbrev"]: {**r, "date": self.END,
                                               "captured_at": "2026-09-27T10:12:00+00:00"}
                           for r in self._rows()}}

    def _now(self, text="2026-10-01T19:00:00+00:00"):
        from datetime import datetime
        return datetime.fromisoformat(text)

    def test_a_morning_snapshot_of_the_last_day_is_not_final(self):
        from src.report import postseason_page as pp
        self.assertIsNone(pp._final_snapshot(pp._standings_by_date(self._stale_store()), "2026-10-01"))

    def test_the_feed_completes_it_and_the_store_is_untouched(self):
        from src.report import postseason_page as pp
        stored = self._stale_store()
        asked = []

        def fetch(season, date=None):
            asked.append((season, date))
            return "raw"

        out = pp.with_final_standings(stored, self._now(), fetch, lambda raw: self._rows())
        self.assertEqual(asked, [("2026", self.END)])
        snap = pp._final_snapshot(pp._standings_by_date(out), "2026-10-01")
        self.assertIsNotNone(snap)
        self.assertEqual(snap[0], self.END)
        self.assertEqual(len(snap[1]), 30)
        self.assertEqual(stored[self.END]["T00"]["captured_at"], "2026-09-27T10:12:00+00:00")

    def test_no_request_when_the_store_already_has_a_final_table(self):
        from src.report import postseason_page as pp
        stored = self._stale_store()
        for row in stored[self.END].values():
            row["captured_at"] = "2026-09-28T10:12:00+00:00"

        def boom(*a, **k):
            raise AssertionError("no request needed")

        self.assertIs(pp.with_final_standings(stored, self._now(), boom, boom), stored)

    def test_no_request_before_the_season_is_over(self):
        from src.report import postseason_page as pp

        def boom(*a, **k):
            raise AssertionError("no request needed")

        for when in ("2026-09-27T23:00:00+00:00", "2026-09-28T03:00:00+00:00"):
            stored = self._stale_store()
            self.assertIs(pp.with_final_standings(stored, self._now(when), boom, boom), stored)

    def test_a_partial_or_failed_answer_changes_nothing(self):
        from src.report import postseason_page as pp
        stored = self._stale_store()

        def down(*a, **k):
            raise OSError("feed unreachable")

        self.assertIs(pp.with_final_standings(stored, self._now(), down, lambda raw: []), stored)
        self.assertIs(pp.with_final_standings(
            stored, self._now(), lambda *a, **k: "raw", lambda raw: self._rows(29)), stored)
        self.assertIs(pp.with_final_standings(
            stored, self._now(), lambda *a, **k: [], lambda raw: []), stored)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class RouteTopUpStartsWhereTheStoreStopsTest(unittest.TestCase):
    """A deployed image's results store is as old as its deploy. The top-up
    has to start the day after the store's coverage ends, fetch each finished
    date once per process, and never claim coverage past a date it missed."""

    def setUp(self):
        from api import postseason as route
        self.route = route
        route.reset_cache_for_tests()
        self.addCleanup(route.reset_cache_for_tests)

    def _result(self, day, finals=(), pending=0):
        return {"date": day, "final": list(finals), "pending": [], "cancelled": [],
                "summary": {"total": len(finals) + pending, "final": len(finals),
                            "pending": pending, "cancelled": 0}}

    def _run(self, fetch, now_text="2026-10-01T19:00:00+00:00"):
        from datetime import datetime
        from unittest import mock
        manifest = {"2026-09-23": {"pending": 0}}
        with mock.patch.object(self.route.mlb, "fetch_results", side_effect=fetch):
            return self.route._topup_results({}, manifest, datetime.fromisoformat(now_text))

    def test_starts_the_day_after_coverage_and_keeps_regular_season_games(self):
        asked = []

        def fetch(day):
            asked.append(day)
            game = {"game_pk": int(day.replace("-", "")), "date": day,
                    "game_type": "R" if day <= "2026-09-27" else "F"}
            return self._result(day, [game])

        store, through = self._run(fetch)
        self.assertEqual(asked[0], "2026-09-24")
        self.assertEqual(asked[-1], "2026-10-01")
        self.assertIn("20260925", store)
        self.assertEqual(store["20260925"]["game_type"], "R")
        self.assertIn("20260930", store)
        self.assertEqual(through, "2026-10-01")

    def test_a_finished_date_is_fetched_once_per_process(self):
        asked = []

        def fetch(day):
            asked.append(day)
            return self._result(day, pending=1 if day == "2026-10-01" else 0)

        self._run(fetch)
        self._run(fetch)
        self.assertEqual(asked.count("2026-09-24"), 1)
        self.assertEqual(asked.count("2026-10-01"), 2)

    def test_a_date_that_cannot_be_read_stops_coverage_there(self):
        def fetch(day):
            if day == "2026-09-26":
                raise OSError("feed unreachable")
            return self._result(day)

        _, through = self._run(fetch)
        self.assertEqual(through, "2026-09-25")



# ---------------------------------------------------------------------------
# fixes from the independent check, 2026-10-01
# ---------------------------------------------------------------------------

EVENING = datetime(2026, 10, 2, 0, 30, tzinfo=timezone.utc)   # 8:30 pm Eastern, Oct 1
LATE = datetime(2026, 10, 2, 3, 30, tzinfo=timezone.utc)      # 11:30 pm Eastern, Oct 1
FULL_SCOPE = frozenset({"F", "D", "L", "W"})
BANNED_WORDS = (r"\bpicks?\b", r"\block\b", r"\bsharp\b", r"\bwinning\b",
                r"\bguaranteed?\b", r"\bprofit\b", r"\bfavou?rites?\b", r"\bboard\b")


def _in_progress_game():
    """A Wild Card game that began at 00:00Z on Oct 2, i.e. 8 pm Eastern on
    the baseball date Oct 1, with both starters announced."""
    game = schedule_game(1, "2026-10-01", "A5", "A4", _rotation("A5")[1], _rotation("A4")[1])
    game["start_time_utc"] = "2026-10-02T00:00:00Z"
    return game


def _schedule_feed(*games):
    """A fetch_games(date) that, like the real feed, files each game under its
    baseball date (`officialDate`), not its UTC date."""
    asked = []

    def fetch(day):
        asked.append(day)
        return [g for g in games if g["date"] == day]
    fetch.asked = asked
    return fetch


def _next_game(payload, suffix="AL-WC-4v5"):
    return _series(payload, suffix)["next_game"]


class BaseballDateTests(unittest.TestCase):
    """The US Eastern calendar date, from a fixed rule (no tz database is
    needed or assumed: Windows Pythons often ship without one)."""

    def test_an_evening_game_after_midnight_utc_is_still_the_same_baseball_day(self):
        self.assertEqual(page.baseball_date(EVENING), "2026-10-01")
        self.assertEqual(page.baseball_date(LATE), "2026-10-01")
        self.assertEqual(page.baseball_date(datetime(2026, 10, 2, 3, 59, tzinfo=timezone.utc)),
                         "2026-10-01")
        self.assertEqual(page.baseball_date(datetime(2026, 10, 2, 4, 0, tzinfo=timezone.utc)),
                         "2026-10-02")

    def test_afternoon_is_unchanged(self):
        self.assertEqual(page.baseball_date(NOW), "2026-10-01")

    def test_daylight_saving_boundaries(self):
        utc = timezone.utc
        # DST began Sunday 2026-03-08 at 07:00Z, ended Sunday 2026-11-01 at 06:00Z.
        self.assertEqual(page.baseball_date(datetime(2026, 3, 8, 4, 30, tzinfo=utc)), "2026-03-07")
        self.assertEqual(page.baseball_date(datetime(2026, 3, 8, 7, 30, tzinfo=utc)), "2026-03-08")
        self.assertEqual(page.baseball_date(datetime(2026, 11, 1, 5, 30, tzinfo=utc)), "2026-11-01")
        self.assertEqual(page.baseball_date(datetime(2026, 11, 2, 4, 30, tzinfo=utc)), "2026-11-01")
        self.assertEqual(page.baseball_date(datetime(2026, 11, 2, 5, 30, tzinfo=utc)), "2026-11-02")


class EveningRolloverTests(unittest.TestCase):
    """From 8 pm Eastern the UTC date is already tomorrow. The game being
    played must stay on the page with its announced starters and schedule
    facts, and must never be described as played."""

    def setUp(self):
        self.game = _in_progress_game()
        self.far = schedule_game(2, "2026-10-03", "N6", "N2", _rotation("N6")[3], None, "D")

    def test_the_lookahead_starts_a_day_before_the_baseball_date(self):
        for when in (EVENING, LATE):
            fetch = _schedule_feed(self.game)
            games = page.upcoming_games(when, fetch)
            self.assertEqual([g["game_pk"] for g in games], [1], when)
            self.assertEqual(fetch.asked[0], "2026-09-30", when)

    def test_a_game_in_progress_keeps_its_starters_and_schedule_facts(self):
        for when in (EVENING, LATE):
            probables = page.upcoming_games(when, _schedule_feed(self.game, self.far))
            payload = build(probables=probables, now=when, results_through="2026-09-30")
            self.assertTrue(payload["available"], payload.get("reason"))
            nxt = _next_game(payload)
            self.assertEqual(nxt["number"], 2, when)
            self.assertEqual(nxt["starter_label"], page.MODEL_USED, when)
            self.assertEqual(nxt["starters"]["home"]["source"], "actual")
            self.assertEqual(nxt["starters"]["home"]["id"], _rotation("A4")[1])
            self.assertEqual(nxt["starters"]["away"]["id"], _rotation("A5")[1])
            self.assertEqual(nxt["date"], "2026-10-01", when)
            self.assertEqual(nxt["start_utc"], "2026-10-02T00:00:00Z", when)
            self.assertEqual(nxt["venue"], "A4 Park", when)

    def test_a_game_in_progress_is_never_described_as_played(self):
        probables = page.upcoming_games(EVENING, _schedule_feed(self.game))
        payload = build(probables=probables, now=EVENING, results_through="2026-09-30")
        s = _series(payload, "AL-WC-4v5")
        self.assertEqual(s["score_text"], "A4 leads 1-0")
        self.assertEqual([g["status"] for g in s["games"]][:2], ["final", "next"])
        self.assertEqual(sum(1 for g in s["games"] if g["status"] == "final"), 1)
        self.assertTrue(s["next_game"]["started"])
        # the same game in the afternoon has not started
        afternoon = build(probables=probables, results_through="2026-09-30")
        self.assertFalse(_next_game(afternoon)["started"])

    def test_the_chance_does_not_move_when_the_clock_passes_midnight_utc(self):
        probables = page.upcoming_games(EVENING, _schedule_feed(self.game, self.far))
        afternoon = build(probables=probables, results_through="2026-09-30")
        for when in (EVENING, LATE):
            later = build(probables=probables, now=when, results_through="2026-09-30")
            self.assertTrue(later["available"], later.get("reason"))
            self.assertEqual(_series(later, "AL-WC-4v5")["teams"],
                             _series(afternoon, "AL-WC-4v5")["teams"], when)
            self.assertEqual(_next_game(later)["home_chance"],
                             _next_game(afternoon)["home_chance"], when)

    def test_one_day_of_result_lag_is_judged_against_the_baseball_date(self):
        # Oct 1 is still being played, so results run through Sep 30: one day.
        self.assertTrue(build(now=EVENING, results_through="2026-09-30")["available"])
        self.assertFalse(build(now=EVENING, results_through="2026-09-29")["available"])


class ResultsThroughManifestTests(unittest.TestCase):

    @staticmethod
    def _ok(scope=("D", "F", "L", "W")):
        return {"total": 4, "pending": 0, "game_types": list(scope)}

    @staticmethod
    def _pending():
        return {"total": 4, "pending": 1, "game_types": ["D", "F", "L", "W"]}

    def _through(self, manifest):
        return page.results_through_from_manifest(manifest, FULL_SCOPE)

    def test_an_earlier_pending_date_ends_the_run(self):
        manifest = {"2026-09-27": self._ok(), "2026-09-29": self._ok(), "2026-09-30": self._ok(),
                    "2026-10-01": self._pending(), "2026-10-02": self._ok()}
        self.assertEqual(self._through(manifest), "2026-09-30")

    def test_only_postseason_dates_pending_gives_no_postseason_coverage(self):
        manifest = {"2026-10-01": self._pending(), "2026-10-02": self._ok()}
        self.assertIsNone(self._through(manifest))

    def test_a_missing_postseason_date_ends_the_run(self):
        manifest = {"2026-09-29": self._ok(), "2026-10-01": self._ok()}
        self.assertEqual(self._through(manifest), "2026-09-29")

    def test_an_under_scoped_postseason_date_ends_the_run(self):
        manifest = {"2026-09-29": self._ok(), "2026-09-30": self._ok(scope=("R",)),
                    "2026-10-01": self._ok()}
        self.assertEqual(self._through(manifest), "2026-09-29")

    def test_a_postseason_off_day_on_file_does_not_break_the_run(self):
        manifest = {"2026-09-29": self._ok(), "2026-09-30": {**self._ok(), "total": 0},
                    "2026-10-01": self._ok()}
        self.assertEqual(self._through(manifest), "2026-10-01")

    def test_an_unbroken_run_returns_its_last_date(self):
        manifest = {"2026-09-29": self._ok(), "2026-09-30": self._ok(), "2026-10-01": self._ok()}
        self.assertEqual(self._through(manifest), "2026-10-01")

    def test_regular_season_gaps_and_pending_dates_stay_as_before(self):
        manifest = {"2026-09-24": {"pending": 0}, "2026-09-25": {"pending": 1},
                    "2026-09-27": {"pending": 0}}
        self.assertEqual(self._through(manifest), "2026-09-27")
        self.assertEqual(self._through({"2026-09-24": {"pending": 0}}), "2026-09-24")
        self.assertIsNone(self._through({}))


class StaleInputsTests(unittest.TestCase):

    def setUp(self):
        self.probables = [
            schedule_game(1, "2026-10-01", "A5", "A4", _rotation("A5")[1], _rotation("A4")[1])]

    def _al(self, payload):
        return _series(payload, "AL-WC-4v5")

    def test_data_that_is_current_has_no_stale_caveat(self):
        p = build(probables=self.probables, pitcher_logs=pitcher_logs(27))   # 3 days behind
        self.assertEqual(p["caveats"][0], page.CAVEAT)

    def test_pitcher_numbers_more_than_three_days_old_come_first(self):
        p = build(probables=self.probables, pitcher_logs=pitcher_logs(7))
        # CHANGED wording (old: "..., so recent starts are not in these
        # estimates."): the new sentence says what is true now, that a
        # starter is left out unless his numbers are current.
        self.assertEqual(p["caveats"][0], "Pitcher numbers on file run through Sept 7. A "
                                          "starting pitcher is left out of an estimate "
                                          "unless his numbers are current.")
        self.assertIn(page.CAVEAT, p["caveats"][1:])
        four = build(probables=self.probables, pitcher_logs=pitcher_logs(26))  # 4 days behind
        self.assertIn("Sept 26", four["caveats"][0])

    def test_a_stale_bullpen_store_gets_its_own_plain_caveat(self):
        caveats = page.stale_input_caveats(
            {"pitcher_logs": "2026-09-30", "bullpen_log": "2026-09-20"}, "2026-09-30")
        # CHANGED wording (old: "..., so recent relief work is not in these
        # estimates."): stale bullpens are now left out entirely.
        self.assertEqual(caveats, ["Bullpen numbers on file run through Sept 20, so "
                                   "bullpens are left out of these estimates."])
        self.assertEqual(page.stale_input_caveats(
            {"pitcher_logs": "2026-09-27", "bullpen_log": "2026-09-27"}, "2026-09-30"), [])

    def test_the_three_day_line_between_used_and_not_used(self):
        # REPLACES test_between_four_and_ten_days_behind_starters_are_still_
        # projected: the 3-to-10-day "caveat but still used" band is gone.
        # 3 days behind (the 09-30 as_of): current, the announced game uses
        # its starters. 4 days behind: not current, they are left out.
        three = self._al(build(probables=self.probables, pitcher_logs=pitcher_logs(27)))
        self.assertEqual(three["next_game"]["starter_input_class"], page.CONFIRMED_CURRENT)
        four = self._al(build(probables=self.probables, pitcher_logs=pitcher_logs(26)))
        self.assertEqual(four["next_game"]["starter_input_class"], page.STALE_REFERENCE_ONLY)
        game3 = next(g for g in four["games"] if g["number"] == 3)
        self.assertEqual(game3["starter_input_class"], page.STALE_REFERENCE_ONLY)
        self.assertEqual(game3["starter_label"], page.UNAVAILABLE)
        self.assertEqual(game3["scenarios"], [])

    def test_more_than_ten_days_behind_nothing_is_projected(self):
        p = build(probables=self.probables, pitcher_logs=pitcher_logs(19))   # 11 days behind
        self.assertTrue(p["available"])
        s = self._al(p)
        game3 = next(g for g in s["games"] if g["number"] == 3)
        self.assertEqual(game3["starter_label"], page.UNAVAILABLE)
        # CHANGED (old: "Starter not announced"): the line now also says
        # what the estimate does use.
        self.assertEqual(game3["starter_text"], "Starters not announced: estimate uses "
                                                "team results and ballpark only")
        for side in ("home", "away"):
            self.assertIsNone(game3["starters"][side]["id"])
            self.assertIsNone(game3["starters"][side]["source"])
        self.assertTrue(0.0 < game3["home_chance"] < 1.0)
        # the announced game keeps its named starters
        nxt = s["next_game"]
        self.assertEqual(nxt["number"], 2)
        self.assertEqual(nxt["starters"]["home"]["id"], _rotation("A4")[1])
        self.assertEqual(nxt["starters"]["home"]["name"], f"SP{_rotation('A4')[1]}")
        # CHANGED (old: MODEL-USED): the announced starters are shown by name
        # but, with numbers this old, are NOT in the estimate.
        self.assertEqual(nxt["starter_label"], page.UNAVAILABLE)
        self.assertEqual(nxt["starter_input_class"], page.STALE_REFERENCE_ONLY)
        self.assertEqual(nxt["starters"]["home"]["note"],
                         "numbers on file end Sept 19, not used")
        # and an unannounced series is priced, not left out
        nl = _series(p, "NL-WC-4v5")
        self.assertEqual({g["starter_label"] for g in nl["games"]}, {page.UNAVAILABLE})
        self.assertAlmostEqual(sum(t["chance"] for t in nl["teams"]), 1.0, places=5)
        self.assertAlmostEqual(sum(t["wins_world_series"] for t in p["teams"]), 1.0, places=5)
        self.assertIn("Sept 19", p["caveats"][0])

    def test_with_no_pitcher_log_at_all_nothing_is_projected_and_it_says_so(self):
        p = build(probables=self.probables, pitcher_logs={})
        self.assertTrue(p["available"])
        self.assertIn("pitcher numbers", p["caveats"][0].lower())
        game3 = next(g for g in self._al(p)["games"] if g["number"] == 3)
        self.assertEqual(game3["starter_label"], page.UNAVAILABLE)


class PlainStarterWordsTests(_Scenario):

    def test_announced_starters(self):
        nxt = _series(self.payload, "AL-WC-4v5")["next_game"]
        self.assertEqual(nxt["starter_status"], "announced")
        # CHANGED (old: "Announced starters")
        self.assertEqual(nxt["starter_text"], "Starters confirmed, current numbers used")

    def test_projected_starters(self):
        game3 = next(g for g in _series(self.payload, "AL-WC-4v5")["games"] if g["number"] == 3)
        self.assertEqual(game3["starter_status"], "projected")
        # CHANGED (old: "Projected starters, not announced")
        self.assertEqual(game3["starter_text"], "Starters not announced: estimate uses "
                                                "team results and ballpark only")

    def test_announced_but_no_pitching_log(self):
        s = _series(build(probables=self.probables, pitcher_logs={}), "AL-WC-4v5")
        nxt = s["next_game"]
        self.assertEqual(nxt["starter_status"], "announced_no_log")
        # CHANGED (old: "Starters announced · not in the estimate (no 2026
        # pitching log)")
        self.assertEqual(nxt["starter_text"],
                         "Announced, but no 2026 pitching numbers on file: not used")
        self.assertEqual(nxt["starter_label"], page.UNAVAILABLE)   # machine key unchanged
        self.assertNotIn("number", nxt["starter_note"])

    def test_payload_text_has_none_of_the_jargon_or_banned_words(self):
        import re
        p = build(probables=self.probables, pitcher_logs=pitcher_logs(7))
        texts = [p["method"], p["grading_note"], *p["caveats"], *page.PUBLIC_REASONS.values()]
        for s in p["series"]:
            for g in s["games"]:
                texts += [g.get("starter_text"), g.get("starter_note")]
        for text in (t for t in texts if t):
            for pattern in BANNED_WORDS:
                self.assertIsNone(re.search(pattern, text, re.I), (pattern, text))
            for jargon in ("MODEL-USED", "SCENARIO INPUT", "UNAVAILABLE", "in the number",
                           "treated as independent", "relief rate", "scenario"):
                self.assertNotIn(jargon.lower(), text.lower(), text)


class PublicReasonTests(unittest.TestCase):

    def test_a_pricing_failure_shows_a_plain_sentence_and_keeps_the_detail(self):
        boom = page.PricingFailure("cannot price CWS at HOU: thin sample in mlb_results.csv")
        with mock.patch.object(page._Context, "price_game", side_effect=boom):
            p = build(probables=[])
        self.assertFalse(p["available"])
        self.assertEqual(p["missing"], "pricing")
        self.assertEqual(p["reason"], page.PUBLIC_REASONS["pricing"])
        for leak in ("cannot price", "CWS", "HOU", "mlb_results", ".csv"):
            self.assertNotIn(leak, p["reason"])
        self.assertIn("cannot price CWS at HOU", p["detail"])

    def test_every_builder_reason_comes_from_the_small_set(self):
        cases = {
            "final_standings": build(standings={}),
            "results": build(results_through="2026-09-26"),
            "field": build(store=store_with(scenario_specs(), extra=[
                _row(990002, "2026-09-30", "F", "A1", "N1", 3, 2, None, None)])),
        }
        for code, payload in cases.items():
            self.assertEqual(payload["missing"], code)
            self.assertEqual(payload["reason"], page.PUBLIC_REASONS[code])
            self.assertTrue(payload["detail"])
        self.assertEqual(set(page.PUBLIC_REASONS),
                         {"final_standings", "results", "field", "pricing"})


class GradingNoteTests(unittest.TestCase):
    """The sentence under HOW WE GRADE THIS comes from what the ledger holds."""

    def _note(self, ledger):
        return build(probables=[], ledger_rows=ledger)["grading_note"]

    def test_an_empty_ledger_does_not_promise_anything(self):
        note = self._note([])
        self.assertIn("Wild Card Series", note)
        self.assertIn("cannot be graded", note)
        self.assertNotIn("written down before its first game", note)
        self.assertNotIn("Starting with", note)

    def test_rows_for_the_division_series_unlock_the_starting_with_sentence(self):
        rows = [{"series_id": f"2026-{lg}-DS-2", "date": "2026-10-01", "games_played": 0,
                 "series_chance": {a: .5, b: .5}}
                for lg, a, b in (("AL", "A2", "A3"), ("NL", "N2", "N6"))]
        note = self._note(rows)
        self.assertIn("Starting with the Division Series, each series estimate is written "
                      "down before its first game and kept", note)
        self.assertIn("Wild Card Series", note)

    def test_a_partial_set_of_rows_does_not_unlock_it(self):
        rows = [{"series_id": "2026-AL-DS-2", "date": "2026-10-01", "games_played": 0,
                 "series_chance": {"A2": .5, "A3": .5}}]
        self.assertNotIn("Starting with", self._note(rows))

    def test_every_started_series_recorded_says_each_one_is(self):
        rows = [{"series_id": sid, "date": "2026-09-28", "games_played": 0,
                 "series_chance": {a: .5, b: .5}}
                for sid, a, b in (("2026-AL-WC-3v6", "A3", "A6"), ("2026-AL-WC-4v5", "A4", "A5"),
                                  ("2026-NL-WC-3v6", "N3", "N6"), ("2026-NL-WC-4v5", "N4", "N5"),
                                  ("2026-AL-DS-2", "A2", "A3"), ("2026-NL-DS-2", "N2", "N6"))]
        note = self._note(rows)
        self.assertNotIn("cannot be graded", note)
        self.assertIn("each series estimate is written down before its first game and kept",
                      note.lower())


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class RouteUnavailableDoesNotReplaceAGoodPageTests(unittest.TestCase):

    GOOD = {"available": True, "as_of": "2026-09-30", "series": [], "teams": [],
            "caveats": [page.CAVEAT]}
    PLAIN = ("The latest game results have not come in yet, so the series scores "
             "cannot be shown as current.")
    BAD = {"available": False, "reason": PLAIN, "series": [],
           "teams": [], "caveats": [page.CAVEAT], "missing": "results",
           "detail": "results run through 2026-09-26"}

    def setUp(self):
        from api import postseason as route
        self.route = route
        route.reset_cache_for_tests()
        self.addCleanup(route.reset_cache_for_tests)

    def _expire(self):
        self.route._cache._entries[self.route.CACHE_KEY].built_at = datetime(
            2000, 1, 1, tzinfo=timezone.utc)

    def test_an_unavailable_build_after_a_good_one_serves_the_good_page_stale(self):
        with mock.patch.object(self.route, "_build_payload", return_value=dict(self.GOOD)):
            self.route.get_postseason()
        self._expire()
        with mock.patch.object(self.route, "_build_payload", return_value=dict(self.BAD)):
            out = self.route.get_postseason()
        self.assertTrue(out["available"])
        self.assertTrue(out["freshness"]["stale"])
        # and the good page is still what the cache holds
        self.assertTrue(self.route._cache._entries[self.route.CACHE_KEY].value["available"])

    def test_with_no_good_page_the_builders_own_unavailable_payload_is_served(self):
        with mock.patch.object(self.route, "_build_payload", return_value=dict(self.BAD)):
            out = self.route.get_postseason()
        self.assertFalse(out["available"])
        self.assertEqual(out["reason"], self.PLAIN)
        self.assertEqual(out["missing"], "results")
        self.assertNotIn("detail", out)   # internal detail is not served

    def test_a_later_plain_failure_does_not_serve_an_old_unavailable_reason(self):
        with mock.patch.object(self.route, "_build_payload", return_value=dict(self.BAD)):
            self.route.get_postseason()
        self.route.reset_cache_for_tests()
        with mock.patch.object(self.route, "_build_payload", side_effect=RuntimeError("boom")):
            out = self.route.get_postseason()
        self.assertEqual(out["reason"], self.route.ABSENT_REASON)

    def test_the_schedule_lookahead_is_seven_days(self):
        self.assertEqual(self.route.SCHEDULE_DAYS_AHEAD, 7)
        asked = {}

        def fake_upcoming(now, fetch, days_ahead):
            asked["days"] = days_ahead
            return []

        with mock.patch.object(self.route.history, "read_results", return_value={}), \
                mock.patch.object(self.route.history, "read_manifest", return_value={}), \
                mock.patch.object(self.route, "_topup_results", return_value=({}, None)), \
                mock.patch.object(self.route, "_topup_standings", return_value={}), \
                mock.patch.object(self.route.standings_store, "read", return_value={}), \
                mock.patch.object(self.route.postseason_page, "upcoming_games", fake_upcoming), \
                mock.patch.object(self.route.postseason_page, "build", return_value={"x": 1}):
            self.route._build_payload()
        self.assertEqual(asked["days"], 7)

    def test_a_game_six_days_out_with_a_named_starter_is_found(self):
        far = schedule_game(5, "2026-10-07", "A5", "A4", _rotation("A5")[2], _rotation("A4")[2])
        got = page.upcoming_games(NOW, _schedule_feed(far), self.route.SCHEDULE_DAYS_AHEAD)
        self.assertEqual([g["game_pk"] for g in got], [5])
        self.assertEqual(len(page.upcoming_games(NOW, _schedule_feed(far), 3)), 0)

    def test_the_topup_uses_the_baseball_date(self):
        """At 8:30 pm Eastern the feed's Oct 1 games are still being played:
        coverage must stop at Sep 30, not run on to a UTC 'today' of Oct 2."""
        asked = []

        def fetch(day):
            asked.append(day)
            pending = 1 if day == "2026-10-01" else 0
            return {"date": day, "final": [], "pending": [], "cancelled": [],
                    "summary": {"total": pending, "final": 0, "pending": pending,
                                "cancelled": 0}}

        manifest = {"2026-09-23": {"pending": 0}}
        with mock.patch.object(self.route.mlb, "fetch_results", side_effect=fetch):
            _, through = self.route._topup_results({}, manifest, EVENING)
        self.assertEqual(through, "2026-09-30")
        self.assertNotIn("2026-10-02", asked)


ROOT_WEB = ROOT / "web"
WEB_FILES = ("postseason.html", "js/postseason.js", "js/postseason-page.js")


class WebCopyTests(unittest.TestCase):
    """Static checks on the page's own files: wording, links, error states."""

    def _text(self, name):
        return (ROOT_WEB / name).read_text(encoding="utf-8")

    def test_no_banned_word_in_the_three_web_files(self):
        import re
        for name in WEB_FILES:
            text = self._text(name)
            for pattern in BANNED_WORDS:
                for m in re.finditer(pattern, text, re.I):
                    self.fail(f"{name}: {m.group(0)!r} near {text[max(0, m.start()-30):m.end()+30]!r}")

    def test_reader_facing_jargon_is_gone(self):
        js = self._text("js/postseason.js")
        for jargon in ("STARTERS UNKNOWN", "ANNOUNCED STARTERS ·", "PROJECTED STARTERS ·",
                       "treated as independent", "relief rate", "in the number",
                       "behind our daily picks", "not predictions of profit"):
            self.assertNotIn(jargon, js)
        # CHANGED (old: the four 2026-10-01 starter phrases): the page's own
        # fallback words are now the four classes' lines.
        self.assertIn("Starters confirmed, current numbers used", js)
        self.assertIn("Starter not announced: estimate uses team results and ballpark only", js)
        self.assertIn("Announced, but pitcher numbers on file", js)
        self.assertIn("Scenario, not the estimate", js)
        self.assertNotIn("(projected)", js)

    def test_the_unavailable_and_error_states_are_plain(self):
        js = self._text("js/postseason.js")
        self.assertIn("Postseason odds are not available right now", js)
        self.assertNotIn("THE BRACKET IS NOT SET YET", js)
        self.assertIn("We could not load this page. Try again in a minute.", js)
        self.assertNotIn("We could not reach", js)
        self.assertNotIn("Technical detail", js)
        self.assertNotIn("renderError", js)

    def test_the_call_to_action_stays_single_and_says_no_edge_is_claimed(self):
        js = self._text("js/postseason.js")
        self.assertEqual(js.count('"postseason-cta"'), 1)
        # CHANGED 2026-10-01: the trial wording is no longer a static string.
        # It comes from the server's checkout state (checkout.js), so a deploy
        # with checkout off never promises a trial on this page either.
        self.assertNotIn("7-day", js)
        self.assertIn("loadCheckoutState", js)
        self.assertIn("request early access", js)
        self.assertIn("-day free trial", js)
        self.assertIn("No edge is claimed.", js)

    def test_the_footer_links_resolve_from_the_standalone_page(self):
        self.assertIn('renderDisclaimerFooter(footer, { linkPrefix: "index.html" })',
                      self._text("js/postseason-page.js"))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_the_date_label_and_the_clock_agree_in_the_viewers_zone(self):
        """2026-10-02T00:00Z is 5 pm on Oct 1 in Pacific time and 9 am on
        Oct 2 in Tokyo; the date label must follow the clock in both."""
        import os
        script = (
            "import('" + (ROOT_WEB / "js" / "postseason.js").as_uri() + "').then(m => "
            "console.log(JSON.stringify(m.gameWhen({date: '2026-10-01', "
            "start_utc: '2026-10-02T00:00:00Z'}))))")
        seen = {}
        for zone in ("America/Los_Angeles", "Asia/Tokyo"):
            out = subprocess.run(
                ["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                env={**os.environ, "TZ": zone}, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            seen[zone] = json.loads(out.stdout)
        self.assertEqual(seen["America/Los_Angeles"][0], "THU OCT 1")
        self.assertIn("5:00 PM", seen["America/Los_Angeles"][1])
        self.assertEqual(seen["Asia/Tokyo"][0], "FRI OCT 2")
        self.assertIn("9:00 AM", seen["Asia/Tokyo"][1])

# ---------------------------------------------------------------------------
# the owner's rule, 2026-10-01: stale pitcher data is never a silent input
# ---------------------------------------------------------------------------

import collections
import contextlib
import io
import re as _re

from src.analysis import matchup_model as _mm

STARTER_CLASS_NAMES = ("CONFIRMED_CURRENT", "PROJECTED_CURRENT", "STALE_REFERENCE_ONLY",
                       "UNAVAILABLE")


def bullpen_rows(last_day=28):
    """Relief appearances for every club on 2026-09-01 .. 09-<last_day>, in
    the shape `bullpen.read_log()` yields (what `relief_rate` reads)."""
    rows = []
    for index, team in enumerate(AL + NL):
        for day in range(1, last_day + 1):
            rows.append({"date": f"2026-09-{day:02d}", "team": team, "started": False,
                         "innings": 2.0, "earned_runs": 1 + ((index + day) % 4),
                         "person_id": 1, "game_pk": day})
    return rows


def dense_logs(last_day):
    """Season logs with a start on EVERY day through 2026-09-<last_day>: enough
    innings (20+) that the model WOULD price from these starters if they were
    read. (`pitcher_logs(7)` has three starts, which the model treats as too
    thin to use, so it could not show a stale log leaking into a number.)"""
    logs = {}
    for team in AL + NL:
        for slot, pid in enumerate(_rotation(team)):
            logs[str(pid)] = [{
                "person_id": pid, "date": f"2026-09-{d:02d}", "season": "2026",
                "is_home": bool(d % 2), "games_started": 1, "innings_pitched": 6.0,
                "earned_runs": 2 + (slot % 3), "runs": 2 + (slot % 3), "hits": 6,
                "walks": 2 + slot, "strikeouts": 6, "home_runs": 1, "batters_faced": 25,
                "pitches": 95} for d in range(1, last_day + 1)]
    return logs


def pitcher_rows(pid, days=(1, 4, 10, 16, 22, 28), walks=2, strikeouts=6):
    """One pitcher's season log in the stored shape, on the given September
    days. A fresh feed answer looks exactly like this. The model prices a
    starter from home runs, walks and strikeouts (FIP), so those are what a
    test varies to move a number."""
    return [{"person_id": pid, "date": f"2026-09-{d:02d}", "season": "2026",
             "is_home": bool(d % 2), "games_started": 1, "innings_pitched": 6.0,
             "earned_runs": 3, "runs": 3, "hits": 6, "walks": walks,
             "strikeouts": strikeouts, "home_runs": 1, "batters_faced": 25,
             "pitches": 95} for d in days]


def all_games(payload):
    """Every unplayed game of every series that carries one."""
    return [g for s in payload["series"] for g in s["games"]
            if g.get("status") in ("next", "future")]


def numbers(payload):
    """Every number a reader can see as an estimate: the team table, each
    series' chances and each unplayed game's primary chance."""
    return {
        "teams": payload["teams"],
        "series": {s["id"]: [t["chance"] for t in s["teams"]] for s in payload["series"]},
        "games": {(s["id"], g["number"]): g["home_chance"] for s in payload["series"]
                  for g in s["games"] if g.get("status") in ("next", "future")},
    }


def _tweak(logs, teams, extra_walks=6):
    """`logs` with every rotation pitcher of `teams` walking more batters:
    the numbers the model prices a starter from (FIP) move, for those teams
    only."""
    out = copy.deepcopy(logs)
    for team in teams:
        for pid in _rotation(team):
            for row in out[str(pid)]:
                row["walks"] += extra_walks
    return out


def _sides(game):
    return game["starters"]["away"], game["starters"]["home"]


class _StarterRuleBase(unittest.TestCase):
    """The builds every rule test below reads. The schedule names both
    starters of AL WC game 2 (A5 at A4) and the away starter of NL DS game 1;
    every other starter slot is unannounced."""

    @classmethod
    def setUpClass(cls):
        cls.probables = [
            schedule_game(1, "2026-10-01", "A5", "A4", _rotation("A5")[1], _rotation("A4")[1]),
            schedule_game(2, "2026-10-03", "N6", "N2", _rotation("N6")[3], None, "D"),
        ]
        cls.current = build(probables=cls.probables)                          # logs to 09-28
        cls.stale = build(probables=cls.probables, pitcher_logs=dense_logs(7))
        cls.empty = build(probables=cls.probables, pitcher_logs={})

    def game(self, payload, suffix="AL-WC-4v5", number=None):
        s = _series(payload, suffix)
        if number is None:
            return s["next_game"]
        return next(g for g in s["games"] if g["number"] == number)


class CurrencyRuleTests(unittest.TestCase):

    def test_one_constant_and_the_old_band_is_gone(self):
        self.assertEqual(page.CURRENT_INPUT_DAYS, 3)
        self.assertFalse(hasattr(page, "NO_PROJECTION_DAYS"))
        self.assertFalse(hasattr(page, "STALE_INPUT_CAVEAT_DAYS"))
        self.assertFalse(hasattr(page, "projects_starters"))

    def test_three_days_is_current_four_is_not(self):
        self.assertTrue(page.is_current("2026-09-30", "2026-09-30"))
        self.assertTrue(page.is_current("2026-09-27", "2026-09-30"))
        self.assertFalse(page.is_current("2026-09-26", "2026-09-30"))
        self.assertFalse(page.is_current(None, "2026-09-30"))


class StarterClassTests(_StarterRuleBase):

    def test_confirmed_current(self):
        g = self.game(self.current)
        away, home = _sides(g)
        self.assertEqual(away["input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(home["input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(g["starter_input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(g["starter_label"], page.MODEL_USED)
        self.assertTrue(away["in_model"] and home["in_model"])
        self.assertEqual(home["display"], f"SP{_rotation('A4')[1]}")
        self.assertEqual(g["starter_text"], "Starters confirmed, current numbers used")

    def test_projected_current_when_the_schedule_names_nobody(self):
        g = self.game(self.current, "NL-WC-4v5", 1)
        for side in _sides(g):
            self.assertEqual(side["input_class"], "PROJECTED_CURRENT")
            self.assertEqual(side["display"], "TBD")
        self.assertEqual(g["starter_input_class"], "PROJECTED_CURRENT")
        self.assertEqual(g["starter_label"], page.SCENARIO_INPUT)

    def test_a_named_side_beside_an_unnamed_one_is_projected_for_the_game(self):
        g = self.game(self.current, "NL-DS-2", 1)
        away, home = _sides(g)
        self.assertEqual((g["away"], g["home"]), ("N6", "N2"))
        self.assertEqual(away["input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(away["display"], f"SP{_rotation('N6')[3]}")
        self.assertEqual(home["input_class"], "PROJECTED_CURRENT")
        self.assertEqual(home["display"], "TBD")
        self.assertEqual(g["starter_input_class"], "PROJECTED_CURRENT")
        # one side confirmed does not put the starters in the number
        self.assertFalse(away["in_model"] or home["in_model"])

    def test_stale_reference_only_for_named_and_for_projected_pitchers(self):
        g = self.game(self.stale)
        for side in _sides(g):
            self.assertEqual(side["input_class"], "STALE_REFERENCE_ONLY")
            self.assertEqual(side["note"], "numbers on file end Sept 7, not used")
            self.assertFalse(side["in_model"])
        self.assertEqual(g["starter_input_class"], "STALE_REFERENCE_ONLY")
        self.assertEqual(g["starter_label"], page.UNAVAILABLE)
        self.assertEqual(g["starter_text"],
                         "Announced, but pitcher numbers on file end Sept 7: not used")
        unnamed = self.game(self.stale, "NL-WC-4v5", 1)
        for side in _sides(unnamed):
            self.assertEqual(side["input_class"], "STALE_REFERENCE_ONLY")
            self.assertEqual(side["display"], "TBD")
        self.assertEqual(unnamed["scenarios"], [])

    def test_unavailable_when_nobody_is_identified_or_there_is_no_log(self):
        # a named pitcher with no log at all
        g = self.game(self.empty)
        for side in _sides(g):
            self.assertEqual(side["input_class"], "UNAVAILABLE")
            self.assertEqual(side["display"], f"SP{side['id']}")      # named, so shown
        self.assertEqual(g["starter_input_class"], "UNAVAILABLE")
        # only one of the two has no log: that side is UNAVAILABLE, and the
        # game is the weaker of the two
        logs = pitcher_logs()
        del logs[str(_rotation("A4")[1])]
        one = self.game(build(probables=self.probables, pitcher_logs=logs))
        away, home = _sides(one)
        self.assertEqual(away["input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(home["input_class"], "UNAVAILABLE")
        self.assertEqual(one["starter_input_class"], "UNAVAILABLE")
        # nobody identified: a results store that is not current projects nobody
        lagging = build(store=store_with(), now=datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc),
                        results_through="2026-09-26")
        self.assertTrue(lagging["available"], lagging.get("reason"))
        g = next(g for g in all_games(lagging))
        for side in _sides(g):
            self.assertEqual(side["input_class"], "UNAVAILABLE")
        # the same data with results through yesterday projects again
        fine = build(store=store_with(), now=datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc),
                     results_through="2026-09-27")
        self.assertEqual(next(g for g in all_games(fine))["starter_input_class"],
                         "PROJECTED_CURRENT")

    def test_the_game_class_is_the_weakest_side(self):
        rows = {_rotation("A4")[1]: pitcher_rows(_rotation("A4")[1], days=(4, 29)),
                _rotation("A5")[1]: None}
        g = self.game(build(probables=self.probables, pitcher_logs=dense_logs(7),
                            fresh_pitcher_logs=rows.get))
        away, home = _sides(g)
        self.assertEqual(home["input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(away["input_class"], "STALE_REFERENCE_ONLY")
        self.assertEqual(g["starter_input_class"], "STALE_REFERENCE_ONLY")

    def test_every_game_carries_a_class_and_the_machine_fields_agree(self):
        for payload in (self.current, self.stale, self.empty):
            for g in all_games(payload):
                self.assertIn(g["starter_input_class"], STARTER_CLASS_NAMES)
                self.assertEqual(g["starter_input_class"], max(
                    (g["starters"]["away"]["input_class"], g["starters"]["home"]["input_class"]),
                    key=STARTER_CLASS_NAMES.index))
                used = [i for i in g["inputs"] if i["key"] == "starters"][0]["used"]
                self.assertEqual(used, g["starter_input_class"] == "CONFIRMED_CURRENT")
                self.assertEqual(g["starter_label"] == page.MODEL_USED, used)


class StaleNeverInThePrimaryNumberTests(_StarterRuleBase):

    def test_a_stale_named_starter_gives_the_same_number_as_no_starters(self):
        """The 'not silently in the number' test. `empty` (no pitcher log at
        all) prices every game without starters; a store 23 days old must
        give exactly the same estimates. On the old builder the named
        pitcher's stale log fed the number and these differed."""
        self.assertEqual(numbers(self.stale), numbers(self.empty))
        g_stale, g_empty = self.game(self.stale), self.game(self.empty)
        self.assertEqual(g_stale["home_chance"], g_empty["home_chance"])
        # and the test has teeth: with the same starters CURRENT the number moves
        self.assertNotEqual(self.game(self.current)["home_chance"], g_empty["home_chance"])

    def test_a_stale_bullpen_log_gives_the_same_number_as_no_bullpen_log(self):
        stale = build(probables=self.probables, bullpen_log=bullpen_rows(6))
        none = build(probables=self.probables, bullpen_log=[])
        current = build(probables=self.probables, bullpen_log=bullpen_rows(28))
        self.assertEqual(numbers(stale), numbers(none))       # games, series, bracket
        self.assertNotEqual(numbers(current)["games"], numbers(none)["games"])
        self.assertNotEqual(numbers(current)["teams"], numbers(none)["teams"])
        # the not-yet-set series use the neutral price: it follows the same rule
        self.assertEqual(_series(stale, "AL-DS-2")["teams"], _series(none, "AL-DS-2")["teams"])
        for g in all_games(stale):
            bullpens = [i for i in g["inputs"] if i["key"] == "bullpens"][0]
            self.assertFalse(bullpens["used"])
            self.assertEqual(bullpens["status"], "STALE_REFERENCE_ONLY")
            self.assertEqual(bullpens["through"], "2026-09-06")
        for g in all_games(current):
            self.assertTrue([i for i in g["inputs"] if i["key"] == "bullpens"][0]["used"])

    def test_no_series_pennant_or_world_series_number_moves_with_stale_numbers(self):
        base = dense_logs(7)
        a = build(probables=self.probables, pitcher_logs=base)
        b = build(probables=self.probables, pitcher_logs=_tweak(base, AL + ["N6", "N2"]))
        self.assertEqual(numbers(a), numbers(b))
        # while a CURRENT starter's numbers do move the number they feed
        live = pitcher_logs()
        moved = build(probables=self.probables, pitcher_logs=_tweak(live, ["A4", "A5"]))
        self.assertNotEqual(numbers(self.current)["games"][("2026-AL-WC-4v5", 2)],
                            numbers(moved)["games"][("2026-AL-WC-4v5", 2)])

    def test_sums_hold_in_every_state(self):
        fetched = build(probables=self.probables, pitcher_logs=dense_logs(7),
                        fresh_pitcher_logs=lambda pid: pitcher_rows(pid, days=(4, 29)))
        self.assertTrue(any(g["starter_input_class"] == "CONFIRMED_CURRENT"
                            for g in all_games(fetched)))
        for payload in (self.current, self.stale, self.empty, fetched):
            by_league = {lg: [t for t in payload["teams"] if t["league"] == lg]
                         for lg in ("AL", "NL")}
            for lg, rows in by_league.items():
                self.assertAlmostEqual(sum(t["reaches_division_series"] for t in rows), 4.0,
                                       places=5, msg=lg)
                self.assertAlmostEqual(sum(t["reaches_lcs"] for t in rows), 2.0, places=5, msg=lg)
                self.assertAlmostEqual(sum(t["wins_pennant"] for t in rows), 1.0, places=5,
                                       msg=lg)
            self.assertAlmostEqual(sum(t["wins_world_series"] for t in payload["teams"]), 1.0,
                                   places=5)


class TbdStaysTbdTests(_StarterRuleBase):

    def test_an_unannounced_side_never_shows_a_pitcher_in_any_class(self):
        fetched = build(probables=self.probables, pitcher_logs=dense_logs(7),
                        fresh_pitcher_logs=lambda pid: pitcher_rows(pid, days=(4, 29)))
        checked = 0
        for payload in (self.current, self.stale, self.empty, fetched):
            for g in all_games(payload):
                for side in ("away", "home"):
                    slot = g["starters"][side]
                    if slot["source"] is None:
                        self.assertEqual(slot["display"], "TBD")
                        self.assertIsNone(slot["id"])
                        self.assertIsNone(slot["name"])
                        checked += 1
                    else:
                        self.assertEqual(slot["source"], "actual")
        self.assertGreater(checked, 40)
        # the schedule's own named starters are the only names that appear
        legit = {f"SP{_rotation('A5')[1]}", f"SP{_rotation('A4')[1]}", f"SP{_rotation('N6')[3]}"}
        for payload in (self.current, self.stale, self.empty, fetched):
            shown = {g["starters"][side]["display"] for g in all_games(payload)
                     for side in ("away", "home")}
            self.assertLessEqual(shown - {"TBD"}, legit)

    def test_a_pitcher_the_schedule_did_not_name_is_never_in_a_text_a_reader_sees(self):
        g = self.game(self.current, "NL-WC-4v5", 1)
        scn = g["scenarios"][0]
        projected = {scn["starters"]["away"]["name"], scn["starters"]["home"]["name"]}
        slot_text = " ".join(filter(None, (
            g["starter_text"], g["inputs_used_text"],
            *[s["display"] for s in _sides(g)])))
        for name in projected:
            self.assertNotIn(name, slot_text)


class ScenarioTests(_StarterRuleBase):

    def test_a_projected_game_has_a_labelled_scenario_that_is_not_the_estimate(self):
        g = self.game(self.current, "AL-WC-4v5", 3)
        self.assertEqual(g["starter_input_class"], "PROJECTED_CURRENT")
        self.assertEqual(len(g["scenarios"]), 1)
        scn = g["scenarios"][0]
        self.assertEqual(scn["key"], "projected_rotation")
        self.assertTrue(scn["label"].startswith(
            "If the projected starters pitch (not announced): "))
        self.assertIn(scn["starters"]["away"]["name"], scn["label"])
        self.assertIn(scn["starters"]["home"]["name"], scn["label"])
        self.assertAlmostEqual(scn["home_chance"] + scn["away_chance"], 1.0, places=5)
        self.assertNotEqual(scn["home_chance"], g["home_chance"])

    def test_scenarios_exist_only_for_projected_current_games(self):
        for payload in (self.current, self.stale, self.empty):
            for g in all_games(payload):
                self.assertEqual(bool(g["scenarios"]),
                                 g["starter_input_class"] == "PROJECTED_CURRENT")

    def test_the_scenario_feeds_no_series_chance(self):
        s = _series(self.current, "AL-WC-4v5")
        a, b = s["teams"]
        remaining = [g for g in s["games"] if g.get("status") in ("next", "future")]
        self.assertTrue(any(g["scenarios"] for g in remaining))

        def chance(use_scenario):
            probs = []
            for g in remaining:
                src = g["scenarios"][0] if (use_scenario and g["scenarios"]) else g
                probs.append(src["home_chance"] if g["home"] == a["team"]
                             else src["away_chance"])
            return _mm.conditional_series_win_prob(probs, a["wins"], b["wins"], 2)

        self.assertAlmostEqual(a["chance"], chance(False), places=5)
        self.assertNotAlmostEqual(a["chance"], chance(True), places=5)

    def test_the_scenario_is_the_number_the_game_would_get_if_those_starters_were_announced(self):
        g = self.game(self.current, "AL-WC-4v5", 3)
        scn = g["scenarios"][0]
        announced = self.probables + [schedule_game(
            3, "2026-10-02", "A5", "A4", scn["starters"]["away"]["id"],
            scn["starters"]["home"]["id"])]
        later = build(probables=announced)
        g3 = self.game(later, "AL-WC-4v5", 3)
        self.assertEqual(g3["starter_input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(g3["home_chance"], scn["home_chance"])


class FreshLogTests(_StarterRuleBase):

    A5, A4 = _rotation("A5")[1], _rotation("A4")[1]

    def _fetcher(self, rows_by_pid):
        calls = []

        def fetch(pid):
            calls.append(pid)
            return rows_by_pid(pid) if callable(rows_by_pid) else rows_by_pid.get(pid)
        fetch.calls = calls
        return fetch

    def _stale_build(self, fetch, logs=None):
        return build(probables=self.probables, pitcher_logs=logs or dense_logs(7),
                     fresh_pitcher_logs=fetch)

    def test_a_fresh_log_turns_a_stale_named_starter_current_and_only_then_it_counts(self):
        days = (1, 4, 10, 16, 22, 29)
        fetch = self._fetcher({self.A5: pitcher_rows(self.A5, days, walks=0, strikeouts=12),
                               self.A4: pitcher_rows(self.A4, days, walks=9, strikeouts=3)})
        fetched = self.game(self._stale_build(fetch))
        for side in _sides(fetched):
            self.assertEqual(side["input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(fetched["starter_input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(fetched["starter_label"], page.MODEL_USED)
        stale = self.game(self.stale)
        self.assertNotEqual(fetched["home_chance"], stale["home_chance"])
        # the number is the one the same rows give when they ARE the store
        merged = dense_logs(7)
        merged[str(self.A5)] = pitcher_rows(self.A5, days, walks=0, strikeouts=12)
        merged[str(self.A4)] = pitcher_rows(self.A4, days, walks=9, strikeouts=3)
        as_store = self.game(build(probables=self.probables, pitcher_logs=merged))
        self.assertEqual(as_store["starter_input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(fetched["home_chance"], as_store["home_chance"])

    def test_a_fetcher_that_raises_or_answers_nothing_leaves_it_stale(self):
        def boom(pid):
            raise OSError("feed down")

        no_rows = [None, boom, lambda pid: [], lambda pid: "not rows",
                   # rows dated after today are not usable either
                   lambda pid: [dict(r, date="2026-10-02") for r in pitcher_rows(pid)]]
        for fetch in no_rows:
            payload = self._stale_build(fetch)
            self.assertTrue(payload["available"], payload.get("reason"))
            g = self.game(payload)
            self.assertEqual(g["starter_input_class"], "STALE_REFERENCE_ONLY")
            self.assertEqual(numbers(payload), numbers(self.stale))

    def test_no_new_start_since_the_store_date_is_still_current(self):
        """The feed is the source of truth for 'nothing newer exists': the
        stored rows, returned unchanged, make a pitcher current."""
        stored = dense_logs(7)
        fetch = self._fetcher(lambda pid: copy.deepcopy(stored.get(str(pid))))
        g = self.game(self._stale_build(fetch, logs=stored))
        self.assertEqual(g["starter_input_class"], "CONFIRMED_CURRENT")

    def test_each_pitcher_is_looked_up_once_named_ones_first_and_never_when_current(self):
        fetch = self._fetcher(lambda pid: pitcher_rows(pid, days=(4, 29)))
        self._stale_build(fetch)
        self.assertEqual(len(fetch.calls), len(set(fetch.calls)))
        self.assertEqual(set(fetch.calls[:3]), {self.A5, self.A4, _rotation("N6")[3]})
        none_needed = self._fetcher(lambda pid: pitcher_rows(pid))
        build(probables=self.probables, fresh_pitcher_logs=none_needed)    # store is current
        self.assertEqual(none_needed.calls, [])

    def test_fresh_rows_dated_on_or_after_the_game_are_not_read(self):
        days = (1, 4, 10, 16, 22, 29)
        clean = {self.A5: pitcher_rows(self.A5, days), self.A4: pitcher_rows(self.A4, days)}
        spike = dict(walks=40, home_runs=10, strikeouts=0, innings_pitched=1.0)
        leaky = {pid: rows + [dict(rows[-1], date="2026-10-01", **spike),
                              dict(rows[-1], date="2026-10-02", **spike)]
                 for pid, rows in clean.items()}
        a = self.game(self._stale_build(self._fetcher(clean)))
        b = self.game(self._stale_build(self._fetcher(leaky)))
        self.assertEqual(a["starter_input_class"], "CONFIRMED_CURRENT")
        self.assertEqual(a["home_chance"], b["home_chance"])
        self.assertEqual(b["starters"]["home"]["numbers_through"], "2026-09-29")

    def test_the_input_logs_are_never_modified(self):
        logs = dense_logs(7)
        before = copy.deepcopy(logs)
        self._stale_build(self._fetcher(lambda pid: pitcher_rows(pid, days=(4, 29))), logs=logs)
        self.assertEqual(logs, before)


class InputsTextTests(_StarterRuleBase):

    def test_the_owners_example_sentence(self):
        payload = build(probables=self.probables, bullpen_log=bullpen_rows(6))
        g = self.game(payload, "AL-WC-4v5", 3)
        self.assertEqual(
            g["inputs_used_text"],
            "2 of 4 inputs are current and used: team results through Sept 30, ballpark. "
            "Not used: starting pitchers (not announced), bullpens (numbers on file end Sept 6).")

    def test_all_current(self):
        # CHANGED 2026-10-01: a game that uses starters has a FIFTH input, the
        # league pitching baseline, with a status of its own (owner's rule:
        # it must not read as current just because the starter's log is).
        payload = build(probables=self.probables, bullpen_log=bullpen_rows(28))
        g = self.game(payload)
        self.assertEqual(
            g["inputs_used_text"],
            "All 5 inputs are current and used: team results through Sept 30, ballpark, "
            "starting pitchers through Sept 28, bullpens through Sept 28, "
            "league pitching baseline through Sept 28.")
        self.assertEqual([i["key"] for i in g["inputs"]],
                         ["team_results", "park", "starters", "bullpens",
                          "league_pitching_baseline"])
        for item in g["inputs"]:
            self.assertEqual(set(item), {"key", "label", "used", "status", "through", "note"})

    def test_a_stale_named_starter_is_named_with_its_date(self):
        g = self.game(self.stale)
        self.assertIn("starting pitchers (numbers on file end Sept 7)", g["inputs_used_text"])

    def test_the_counts_agree_with_the_per_game_classes(self):
        for payload in (self.current, self.stale, self.empty):
            games = all_games(payload)
            counts = collections.Counter(g["starter_input_class"] for g in games)
            summary = payload["input_summary"]
            self.assertEqual(summary["starter_counts"],
                             {c: counts.get(c, 0) for c in STARTER_CLASS_NAMES})
            self.assertEqual(summary["unplayed_games"], len(games))
            starters = next(c for c in summary["components"] if c["key"] == "starters")
            self.assertEqual(starters["counts"], summary["starter_counts"])
            self.assertEqual([c["key"] for c in summary["components"]],
                             ["team_results", "park", "starters", "bullpens"])
            for g in games:
                used_current = sum(1 for i in g["inputs"]
                                   if i["used"] and i["status"] in ("CURRENT", "CONFIRMED_CURRENT"))
                # A game that uses starters lists a fifth input, the league
                # pitching baseline (CHANGED 2026-10-01).
                n = len(g["inputs"])
                self.assertEqual(n, 5 if g["starter_input_class"] == "CONFIRMED_CURRENT" else 4)
                self.assertTrue(g["inputs_used_text"].startswith(
                    f"All {n}" if used_current == n else f"{used_current} of {n}"),
                    g["inputs_used_text"])
            confirmed = counts.get("CONFIRMED_CURRENT", 0)
            if confirmed:
                self.assertIn(f"in {confirmed} of {len(games)} games", summary["text"])
            else:
                self.assertIn(f"None of the {len(games)} games", summary["text"])

    def test_the_page_sentence_names_a_stale_bullpen(self):
        payload = build(probables=self.probables, bullpen_log=bullpen_rows(6))
        self.assertIn("bullpens are left out because their numbers on file end Sept 6",
                      payload["input_summary"]["text"])
        self.assertIn("bullpens are included", build(
            probables=self.probables, bullpen_log=bullpen_rows(28))["input_summary"]["text"])

    def test_reader_text_is_plain_and_clean(self):
        fetched = build(probables=self.probables, pitcher_logs=dense_logs(7),
                        fresh_pitcher_logs=lambda pid: pitcher_rows(pid, days=(4, 29)))
        texts = []
        for payload in (self.current, self.stale, self.empty, fetched):
            texts += [payload["input_summary"]["text"], payload["method"]]
            texts += [c["note"] for c in payload["input_summary"]["components"] if c["note"]]
            for g in all_games(payload):
                texts += [g["starter_text"], g["inputs_used_text"], g.get("starter_note")]
                texts += [i["note"] for i in g["inputs"] if i["note"]]
                texts += [s["note"] for s in _sides(g) if s["note"]]
                texts += [x["label"] for x in g["scenarios"]]
        texts = [t for t in texts if t]
        self.assertGreater(len(texts), 100)
        for text in texts:
            for pattern in BANNED_WORDS + (r"\bedge\b",):
                self.assertIsNone(_re.search(pattern, text, _re.I), (pattern, text))
            self.assertIsNone(_re.search(r"[A-Z]+_[A-Z]+", text), text)
            for jargon in ("MODEL-USED", "SCENARIO INPUT", "in the number", "relief rate"):
                self.assertNotIn(jargon.lower(), text.lower(), text)


class LedgerClassTests(_StarterRuleBase):

    def test_a_row_records_what_each_game_estimate_was_made_from(self):
        al = next(r for r in page.snapshot_rows(self.current, "2026-10-01")
                  if r["series_id"].endswith("AL-WC-4v5"))
        self.assertEqual(al["next_game"]["starter_input_class"], "CONFIRMED_CURRENT")
        self.assertTrue(al["next_game"]["starters_used"])
        self.assertFalse(al["next_game"]["bullpens_used"])       # no bullpen log in the fixture
        games = al["inputs"]["games"]
        self.assertEqual([g["number"] for g in games], [2, 3])
        self.assertEqual([g["starter_input_class"] for g in games],
                         ["CONFIRMED_CURRENT", "PROJECTED_CURRENT"])
        self.assertEqual([g["starters_used"] for g in games], [True, False])
        json.dumps(al)

    def test_a_stale_state_is_recorded_as_not_used(self):
        al = next(r for r in page.snapshot_rows(self.stale, "2026-10-01")
                  if r["series_id"].endswith("AL-WC-4v5"))
        self.assertEqual(al["next_game"]["starter_input_class"], "STALE_REFERENCE_ONLY")
        self.assertFalse(al["next_game"]["starters_used"])
        withpen = build(probables=self.probables, bullpen_log=bullpen_rows(28))
        al = next(r for r in page.snapshot_rows(withpen, "2026-10-01")
                  if r["series_id"].endswith("AL-WC-4v5"))
        self.assertTrue(al["next_game"]["bullpens_used"])
        self.assertTrue(all(g["bullpens_used"] for g in al["inputs"]["games"]))

    def test_every_row_has_a_class_for_every_game(self):
        for r in page.snapshot_rows(self.current, "2026-10-01"):
            self.assertTrue(r["inputs"]["games"])
            for g in r["inputs"]["games"]:
                self.assertIn(g["starter_input_class"], STARTER_CLASS_NAMES)
                self.assertIsInstance(g["starters_used"], bool)
                self.assertIsInstance(g["bullpens_used"], bool)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class RouteFreshLogTests(unittest.TestCase):

    def setUp(self):
        from api import postseason as route
        self.route = route
        route.reset_cache_for_tests()
        self.addCleanup(route.reset_cache_for_tests)

    def _patch(self, **kw):
        return mock.patch.object(self.route.mlb, "fetch_pitcher_game_log", **kw)

    def test_the_cap_is_24_new_requests_and_the_skips_are_logged(self):
        self.assertEqual(self.route.MAX_FRESH_PITCHER_FETCHES, 24)
        err = io.StringIO()
        with self._patch(return_value=[]) as fetch:
            fetcher = self.route._fresh_fetcher(NOW)
            answers = [fetcher(pid) for pid in range(30)]
            with contextlib.redirect_stderr(err):
                fetcher.report()
        self.assertEqual(fetch.call_count, 24)
        self.assertEqual(answers[:24], [[]] * 24)
        self.assertEqual(answers[24:], [None] * 6)       # skipped = not current
        self.assertIn("6 pitcher(s) skipped", err.getvalue())
        quiet = io.StringIO()
        with self._patch(return_value=[]):
            small = self.route._fresh_fetcher(NOW)
            small(1)
            with contextlib.redirect_stderr(quiet):
                small.report()
        self.assertEqual(quiet.getvalue(), "")

    def test_a_lookup_is_remembered_for_the_baseball_day_only(self):
        rows = pitcher_rows(7)
        with self._patch(return_value=rows) as fetch:
            self.route._fresh_fetcher(NOW)(7)
            self.route._fresh_fetcher(NOW)(7)                       # a later build, same day
            self.assertEqual(fetch.call_count, 1)
            fetch.assert_called_with(7, "2026")
            # the memo is not charged against a later build's cap
            later = self.route._fresh_fetcher(NOW)
            for pid in range(100, 124):
                later(pid)
            self.assertEqual(later(7), rows)
            self.assertEqual(fetch.call_count, 25)
            self.route._fresh_fetcher(NOW + timedelta(days=1))(7)    # the next baseball day
            self.assertEqual(fetch.call_count, 26)
        self.assertEqual({k[1] for k in self.route._fresh_logs_memo}, {"2026-10-02"})

    def test_an_evening_build_uses_the_baseball_day_for_the_memo(self):
        with self._patch(return_value=pitcher_rows(7)) as fetch:
            self.route._fresh_fetcher(EVENING)(7)       # 8:30 pm Eastern Oct 1 = Oct 2 UTC
            self.route._fresh_fetcher(NOW)(7)           # 11 am Eastern Oct 1: same day
        self.assertEqual(fetch.call_count, 1)

    def test_a_failed_lookup_never_fails_the_build_and_is_not_remembered(self):
        probables = [schedule_game(1, "2026-10-01", "A5", "A4", _rotation("A5")[1],
                                   _rotation("A4")[1])]
        with self._patch(side_effect=OSError("feed down")) as fetch:
            payload = build(probables=probables, pitcher_logs=dense_logs(7),
                            fresh_pitcher_logs=self.route._fresh_fetcher(NOW))
        self.assertTrue(payload["available"], payload.get("reason"))
        self.assertGreater(fetch.call_count, 0)
        self.assertEqual(_next_game(payload)["starter_input_class"], "STALE_REFERENCE_ONLY")
        self.assertEqual(self.route._fresh_logs_memo, {})
        with self._patch(side_effect=lambda pid, season: pitcher_rows(pid, days=(4, 29))):
            again = build(probables=probables, pitcher_logs=dense_logs(7),
                          fresh_pitcher_logs=self.route._fresh_fetcher(NOW))
        self.assertEqual(_next_game(again)["starter_input_class"], "CONFIRMED_CURRENT")

    def test_the_route_hands_the_builder_a_fetcher(self):
        seen = {}

        def fake_build(now, **kwargs):
            seen.update(kwargs)
            return {"x": 1}

        with mock.patch.object(self.route.history, "read_results", return_value={}), \
                mock.patch.object(self.route.history, "read_manifest", return_value={}), \
                mock.patch.object(self.route, "_topup_results", return_value=({}, None)), \
                mock.patch.object(self.route, "_topup_standings", return_value={}), \
                mock.patch.object(self.route.standings_store, "read", return_value={}), \
                mock.patch.object(self.route.postseason_page, "upcoming_games",
                                  lambda now, fetch, days: []), \
                mock.patch.object(self.route.postseason_page, "build", fake_build):
            self.route._build_payload()
        self.assertTrue(callable(seen["fresh_pitcher_logs"]))

    def test_the_snapshot_script_passes_its_own_capped_fetcher(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import postseason_snapshot
        self.assertEqual(postseason_snapshot.MAX_FRESH_PITCHER_FETCHES, 24)
        text = (ROOT / "scripts" / "postseason_snapshot.py").read_text(encoding="utf-8")
        self.assertIn("fresh_pitcher_logs=fetcher", text)
        self.assertIn("capped_pitcher_fetcher", text)


class CappedFetcherTests(unittest.TestCase):

    def test_the_builder_helper_caps_memoises_and_swallows_failures(self):
        calls = []

        def fetch(pid):
            calls.append(pid)
            if pid == 3:
                raise RuntimeError("boom")
            return [{"date": "2026-09-01"}]

        memo = {}
        fetcher = page.capped_pitcher_fetcher(fetch, cap=3, memo=memo, day="2026-10-01")
        self.assertEqual(fetcher(1), [{"date": "2026-09-01"}])
        self.assertEqual(fetcher(1), [{"date": "2026-09-01"}])
        self.assertIsNone(fetcher(3))                      # raised: None, and it cost a request
        self.assertEqual(fetcher(2), [{"date": "2026-09-01"}])
        self.assertIsNone(fetcher(4))                      # past the cap
        self.assertEqual(calls, [1, 3, 2])
        self.assertEqual(fetcher.counts, {"requests": 3, "skipped": 1})
        self.assertNotIn((3, "2026-10-01"), memo)


# ---------------------------------------------------------------------------
# the page itself, rendered from a real payload with a minimal DOM
# ---------------------------------------------------------------------------

RENDER_SCRIPT = r"""
import { readFileSync } from "node:fs";
class Node_ {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this._text = "";
    this.style = { setProperty() {} }; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
  get firstChild() { return this.children[0] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(" "); }
}
globalThis.document = {
  createElement: (t) => new Node_(t),
  createTextNode: (t) => { const n = new Node_("#text"); n._text = t; return n; },
};
const m = await import(process.argv[2]);
const payload = JSON.parse(readFileSync(process.argv[3], "utf-8"));
const host = new Node_("div");
m.renderPostseasonPayload(host, payload);
function find(node, hook, out = []) {
  if (node.attrs && node.attrs["data-hook"] === hook) out.push(node);
  for (const c of node.children) find(c, hook, out);
  return out;
}
const hooks = ["ps-input-summary", "ps-pitchers", "ps-starter-tag", "ps-inputs-used",
               "ps-scenario", "ps-game-chance"];
const out = {};
for (const h of hooks) out[h] = find(host, h).map((n) => n.textContent);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PageRenderTests(_StarterRuleBase):

    def _render(self, payload):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        data, script = tmp / "payload.json", tmp / "render.mjs"
        data.write_text(json.dumps(payload), encoding="utf-8")
        script.write_text(RENDER_SCRIPT, encoding="utf-8")
        out = subprocess.run(
            ["node", str(script), (ROOT_WEB / "js" / "postseason.js").as_uri(), str(data)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_the_page_shows_tbd_the_line_the_inputs_and_a_quiet_labelled_scenario(self):
        shown = self._render(self.current)
        self.assertEqual(len(shown["ps-input-summary"]), 1)
        self.assertEqual(shown["ps-input-summary"][0], self.current["input_summary"]["text"])
        pitchers = " | ".join(shown["ps-pitchers"])
        self.assertIn("TBD", pitchers)
        self.assertNotIn("(projected)", pitchers)
        # every unannounced slot reads TBD, and no projected name is on the page
        scn_names = {x["starters"][side]["name"] for g in all_games(self.current)
                     for x in g["scenarios"] for side in ("away", "home")}
        scn_names -= {f"SP{_rotation('A5')[1]}", f"SP{_rotation('A4')[1]}",
                      f"SP{_rotation('N6')[3]}"}
        for name in scn_names:
            self.assertNotIn(name, pitchers)
        self.assertIn("Starters confirmed, current numbers used", shown["ps-starter-tag"])
        self.assertTrue(all(_re.match(r"^(All [45]|[2-4] of [45]) inputs are current and used", t)
                            for t in shown["ps-inputs-used"]), shown["ps-inputs-used"])
        self.assertTrue(shown["ps-scenario"])
        for text in shown["ps-scenario"]:
            self.assertIn("Scenario, not the estimate", text)
            self.assertIn("If the projected starters pitch (not announced)", text)

    def test_a_stale_named_starter_is_named_with_its_date_and_has_no_scenario(self):
        shown = self._render(self.stale)
        pitchers = " | ".join(shown["ps-pitchers"])
        self.assertIn("numbers on file end Sept 7, not used", pitchers)
        self.assertIn("Announced, but pitcher numbers on file end Sept 7: not used",
                      shown["ps-starter-tag"])
        self.assertEqual(shown["ps-scenario"], [])



class LeagueBaselineHasItsOwnStatusTests(_StarterRuleBase):
    """Owner's rule, 2026-10-01: the league-wide pitching baseline, computed
    from the STORED logs, must not read as current because the individual
    starter's log is."""

    def test_a_fresh_starter_on_a_stale_store_reports_a_stale_baseline(self):
        # Store ends Sept 7; the announced starters' own logs arrive fresh.
        payload = build(probables=self.probables, pitcher_logs=dense_logs(7),
                        fresh_pitcher_logs=lambda pid: pitcher_rows(pid, days=(4, 29)))
        g = next(g for g in all_games(payload)
                 if g["starter_input_class"] == "CONFIRMED_CURRENT")
        by_key = {i["key"]: i for i in g["inputs"]}
        self.assertEqual(by_key["starters"]["status"], "CONFIRMED_CURRENT")
        baseline = by_key["league_pitching_baseline"]
        self.assertTrue(baseline["used"])
        self.assertEqual(baseline["status"], "STALE_REFERENCE_ONLY")
        self.assertEqual(baseline["through"], "2026-09-07")
        self.assertIn("Used, but not current: league pitching baseline through Sept 7",
                      g["inputs_used_text"])
        self.assertFalse(g["inputs_used_text"].startswith("All"))

    def test_a_game_without_starters_does_not_list_it(self):
        for g in all_games(self.stale):
            self.assertNotIn("league_pitching_baseline", [i["key"] for i in g["inputs"]])


if __name__ == "__main__":
    unittest.main()
