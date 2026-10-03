"""Where a stale store SHOWS: the game page's labels, and /health.

The refresh (tests/test_display_refresh.py) keeps stores current. This file
pins what is said when one is NOT, because the failure on 2026-10-03 was not
only old data but old data presented as current: "no relief appearances in the
last 7 days" from a bullpen log that stopped on Sept 6, "days rest 14" from a
pitcher log that stopped on Sept 7, a team record a week old with no date.

WHERE THE LABELS LIVE (changed 2026-10-03, review item 2). They first lived in
the dossier sections (`teams.results_stale`, `starters.logs_stale`, the
bullpen workload's `log_stale`). Two things were wrong with that. They were
read off the newest GAME in a store, so the day after a league-wide off day
every page said "results end ..." for a store that was as current as it can be.
And a dossier section is a model and ledger input (`card._flatten` merges
`teams` and `starters` into the card's features; the analyst freezes whole
sections into its hashed packet), so a label there changes what is frozen into
a public record. They are now a DISPLAY fact: `store_freshness.coverage_for_game`
reads what each store COVERS and `api/games.py` attaches it beside the dossier
as `advanced.data_coverage`.

  - the dossier's teams / starters sections and the bullpen workload carry NO
    label: each is exactly what its feature builder returns
  - the coverage block says what each store covers and whether that is too old
    for THIS game, by coverage and not by the newest game
  - the day after a league-wide off day is not stale; a store that really ends
    weeks before the game is
  - a PAST game viewed after the fact is not called stale because the store
    has since moved on
  - the published card payload is byte-identical with and without the block
  - /health carries `data_freshness`, informational, and never flips `status`
  - the container guard is OFF in a plain test/dev process
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src import paths
from src.appstate import apphealth
from src.detect import dossier
from src.pipeline import (bullpen, display_refresh, enrichment, features as team_features,
                          history, pitchers, store_freshness)
from src.providers import mlb
from tests.test_store_freshness import _results, _write_jsonl

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:                                     # pragma: no cover
    _HAVE_FASTAPI = False
if _HAVE_FASTAPI:
    from api import games as games_mod


def _store(through="2026-09-23"):
    rows = {}
    pk = 0
    for day in range(1, 24):
        date = f"2026-09-{day:02d}"
        if date > through:
            break
        for away, home in (("NYY", "BOS"), ("LAD", "SD")):
            pk += 1
            rows[str(pk)] = {"game_pk": str(pk), "date": date, "game_type": "R", "away_team": away,
                             "home_team": home, "away_score": "3", "home_score": "2",
                             "winner": away, "home_won": "0", "total_runs": "5",
                             "run_differential": "1"}
    return rows


def _logs(last="2026-09-07"):
    return {"111": [{"person_id": 111, "date": "2026-09-01", "season": "2026", "games_started": 1,
                     "innings_pitched": 6.0, "earned_runs": 2, "runs": 2, "hits": 5, "walks": 1,
                     "strikeouts": 6, "home_runs": 1, "batters_faced": 24, "pitches": 90},
                    {"person_id": 111, "date": last, "season": "2026", "games_started": 1,
                     "innings_pitched": 5.0, "earned_runs": 1, "runs": 1, "hits": 4, "walks": 1,
                     "strikeouts": 5, "home_runs": 0, "batters_faced": 21, "pitches": 80}]}


def _game(date):
    return {"game_pk": 1, "date": date, "away_team": "NYY", "home_team": "BOS",
            "away_probable_id": 111, "home_probable_id": 111}


def _marker(day):
    return {"person_id": 111, "season": "2026", "date": None, "empty": False,
            "checked_utc": f"{day}T13:00:00+00:00"}


class _Root(unittest.TestCase):
    """A temp data root whose stores a test writes, read through the real
    `coverage_for_game`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.hist = self.root / "historical"
        self.hist.mkdir()
        store_freshness.reset_cache_for_tests()

    def coverage(self, game_date):
        store_freshness.reset_cache_for_tests()
        return store_freshness.coverage_for_game(game_date, root=self.root)

    def write(self, *, results_through=None, newest_game=None, pitcher_rows=None, bullpen_rows=None):
        if results_through is not None:
            _results(self.hist, [(newest_game or results_through, "R")], {results_through: 0})
        if pitcher_rows is not None:
            _write_jsonl(self.hist / "pitcher_logs.jsonl", pitcher_rows)
        if bullpen_rows is not None:
            _write_jsonl(self.hist / "bullpen_log.jsonl", bullpen_rows)


class TheDossierCarriesNoCoverageLabels(unittest.TestCase):
    """A dossier section is a model and a ledger input. It stays exactly what
    its builder returns, so nothing the card reads or the analyst freezes moves
    when a store ages."""

    def test_the_teams_section_is_exactly_the_feature_builders_answer(self):
        store = _store()
        d = dossier.build(_game("2026-10-03"), store, pitcher_logs=_logs("2026-09-07"))
        self.assertEqual(d.sections["teams"],
                         team_features.matchup_features(store, "NYY", "BOS", "2026-10-03"))

    def test_the_starters_section_is_exactly_the_pitcher_features(self):
        logs = _logs("2026-09-07")
        d = dossier.build(_game("2026-10-03"), _store(), pitcher_logs=logs)
        self.assertEqual(d.sections["starters"],
                         pitchers.matchup_pitcher_features(logs, 111, 111, "2026-10-03"))

    def test_no_label_key_appears_in_any_section_however_old_the_stores_are(self):
        d = dossier.build(_game("2026-10-03"), _store("2026-09-01"), pitcher_logs=_logs("2026-09-02"))
        labels = {"results_through", "results_stale", "logs_through", "logs_stale",
                  "log_through", "log_stale", "data_coverage"}
        for name, section in d.sections.items():
            if isinstance(section, dict):
                self.assertFalse(labels & set(section), (name, labels & set(section)))

    def test_a_bullpen_workload_is_exactly_what_team_workload_returns(self):
        games = [{"game_pk": 1, "away_team": "NYY", "home_team": "BOS"}]
        log = [{"date": "2026-09-06", "team": "NYY", "person_id": 1, "started": False, "innings": 1.0}]
        with ExitStack() as stack:
            for target, name, value in (
                    (bullpen, "read_log", log),
                    (enrichment.pitchers, "read_logs", {}),
                    (enrichment.lineup_store, "read", {}),
                    (enrichment.lineups, "read_handedness", {}),
                    (enrichment.lineups, "read_splits", {}),
                    (enrichment.standings, "read", {}),
                    (enrichment.matchup_history, "read", {}),
                    (enrichment.weather_capture, "read", []),
                    (enrichment.news, "read", []),
                    (enrichment.statcast, "read", {"rows": []})):
                stack.enter_context(mock.patch.object(target, name, return_value=value))
            pens = enrichment.enrichment_inputs(games, "2026-10-03", {})["bullpen_by_team"]
        for team in ("NYY", "BOS"):
            self.assertEqual(pens[team], bullpen.team_workload(log, team, "2026-10-03"))
            self.assertFalse({"log_through", "log_stale"} & set(pens[team]))


class WhatReachesALedgerDoesNotDependOnTheLabels(unittest.TestCase):
    """The two public records built from a slate's dossiers, the published card
    and the analyst's frozen packet, must not move when a coverage label is
    present or absent. The first version of the labels put them in the dossier;
    these pin that nothing downstream reads them either way."""

    @classmethod
    def setUpClass(cls):
        from tests.test_model_inputs_regular_season import _card_for, _logs as _two_starters, _slate
        cls._card_for = staticmethod(_card_for)
        cls.inputs, cls.entries, cls.card = _slate(_two_starters(with_postseason=False))
        cls.card_json = json.dumps(cls.card, sort_keys=True, default=str)

    def test_the_card_is_a_real_one(self):
        self.assertEqual(len(self.card["picks"]), 1, self.card.get("reason"))

    def test_the_published_card_is_byte_identical_with_the_old_style_labels_added(self):
        for entry in self.entries:
            sections = entry["dossier"].sections
            sections["teams"] = dict(sections["teams"], results_through="2026-10-02", results_stale=True)
            sections["starters"] = dict(sections["starters"], logs_through="2026-09-07", logs_stale=True)
        try:
            again = json.dumps(self._card_for(self.entries), sort_keys=True, default=str)
        finally:
            for entry in self.entries:
                for name, keys in (("teams", ("results_through", "results_stale")),
                                   ("starters", ("logs_through", "logs_stale"))):
                    for key in keys:
                        entry["dossier"].sections[name].pop(key, None)
        self.assertEqual(again, self.card_json)

    def test_the_analyst_packet_sections_carry_no_label(self):
        from src.analysis import gamepayload
        from src.analyst import packet
        advanced = gamepayload.build_advanced_view(
            self.entries[0], now=datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc))
        sections, _missing = packet._sections(advanced, {}, {}, "2026-10-03")
        labels = {"results_through", "results_stale", "logs_through", "logs_stale",
                  "log_through", "log_stale"}
        for name, block in sections.items():
            values = block.get("values")
            if isinstance(values, dict):
                self.assertFalse(labels & set(values), (name, labels & set(values)))
        self.assertIn("teams", sections)
        self.assertIn("starters", sections)


class TheGamePageSaysWhatItsStoresCover(_Root):

    def test_a_game_after_the_stores_end_is_marked_stale_with_the_date(self):
        self.write(results_through="2026-09-23",
                   pitcher_rows=[{"person_id": 111, "date": "2026-09-07", "season": "2026"}],
                   bullpen_rows=[{"date": "2026-09-06", "empty": True}])
        cover = self.coverage("2026-10-03")
        self.assertEqual(cover["results"], {"through": "2026-09-23", "stale": True})
        self.assertEqual(cover["pitcher_logs"], {"through": "2026-09-07", "stale": True})
        self.assertEqual(cover["bullpen_log"], {"through": "2026-09-06", "stale": True})

    def test_a_game_the_stores_do_cover_is_not(self):
        self.write(results_through="2026-09-23",
                   pitcher_rows=[{"person_id": 111, "date": "2026-09-23", "season": "2026"}],
                   bullpen_rows=[{"date": "2026-09-23", "empty": True}])
        cover = self.coverage("2026-09-24")
        for key in ("results", "pitcher_logs", "bullpen_log"):
            self.assertFalse(cover[key]["stale"], key)

    def test_yesterdays_games_are_the_newest_a_pregame_page_can_hold(self):
        self.write(results_through="2026-09-23")
        self.assertFalse(self.coverage("2026-09-24")["results"]["stale"])
        self.assertTrue(self.coverage("2026-09-25")["results"]["stale"])

    def test_a_past_game_is_not_called_stale_because_the_store_moved_on(self):
        self.write(results_through="2026-09-23",
                   pitcher_rows=[{"person_id": 111, "date": "2026-09-23", "season": "2026"}])
        cover = self.coverage("2026-09-10")
        self.assertFalse(cover["results"]["stale"])
        self.assertFalse(cover["pitcher_logs"]["stale"])

    def test_an_absent_or_undated_store_is_stale_and_never_fresh(self):
        cover = self.coverage("2026-10-03")             # nothing on disk at all
        for key in ("results", "pitcher_logs", "bullpen_log"):
            self.assertEqual(cover[key], {"through": None, "stale": True}, key)
        self.assertTrue(store_freshness.ends_before(None, "2026-10-03"))
        self.assertTrue(store_freshness.ends_before("not-a-date", "2026-10-03"))
        self.assertTrue(store_freshness.ends_before("2026-10-02", "not-a-date"))
        (self.hist / "bullpen_log.jsonl").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.coverage("2026-10-03")["bullpen_log"], {"through": None, "stale": True})


class TheDayAfterALeagueWideOffDay(_Root):
    """The false label this item fixes. No games on the 3rd, a refresh on the
    4th covered it, so the results store is as current as it can be even though
    its newest GAME is the 2nd. The old label compared the newest game with
    the game being viewed (two days) and printed "results end Oct 2" on every
    game page."""

    def test_coverage_counts_the_off_day_so_no_page_is_called_stale(self):
        self.write(results_through="2026-10-03", newest_game="2026-10-02",
                   pitcher_rows=[{"person_id": 111, "date": "2026-10-01", "season": "2026"},
                                 _marker("2026-10-04")],
                   bullpen_rows=[{"date": "2026-10-02", "team": "NYY", "person_id": 1},
                                 {"date": "2026-10-03", "empty": True}])
        cover = self.coverage("2026-10-04")
        self.assertEqual(cover["results"], {"through": "2026-10-03", "stale": False})
        self.assertEqual(cover["pitcher_logs"], {"through": "2026-10-04", "stale": False})
        self.assertEqual(cover["bullpen_log"], {"through": "2026-10-03", "stale": False})

    def test_the_newest_game_alone_would_have_said_stale(self):
        # What the dossier computed: the newest GAME in the store against the
        # game being viewed. That is the false label.
        self.assertTrue(store_freshness.ends_before("2026-10-02", "2026-10-04"))

    def test_a_store_that_really_stops_early_is_still_flagged(self):
        self.write(results_through="2026-10-01", newest_game="2026-10-01")
        self.assertTrue(self.coverage("2026-10-04")["results"]["stale"])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class TheGameRouteAttachesTheCoverageBesideTheDossier(_Root):
    """api/games.get_game, on the day after a league-wide off day."""

    DATE = "2026-10-04"

    def setUp(self):
        super().setUp()
        self.write(results_through="2026-10-03", newest_game="2026-10-02",
                   pitcher_rows=[_marker("2026-10-04")],
                   bullpen_rows=[{"date": "2026-10-03", "empty": True}])
        store = _store("2026-09-23")
        store["990"] = dict(store["1"], game_pk="990", date="2026-10-02")   # the newest game: the 2nd

        def entries(_date):
            from src.pipeline import briefing
            slate = briefing.build_slate([dict(_game(self.DATE), venue="Fenway Park",
                                               start_time_utc=f"{self.DATE}T23:05:00Z")],
                                         store, price_boards_by_key={}, roster_events_by_pk={})
            return slate["games"], [], {"stale": False}

        self._store = store
        for p in (mock.patch.object(games_mod, "_build_entries", side_effect=entries),
                  mock.patch.object(paths, "data_root", return_value=self.root),
                  mock.patch.object(history, "read_results", return_value=store)):
            p.start()
            self.addCleanup(p.stop)

    def payload(self):
        store_freshness.reset_cache_for_tests()
        return games_mod.get_game(self.DATE, "NYY", "BOS")

    def test_the_payload_carries_the_coverage_and_the_off_day_is_not_stale(self):
        advanced = self.payload()["advanced"]
        self.assertEqual(advanced["data_coverage"]["results"], {"through": "2026-10-03", "stale": False})
        self.assertFalse(advanced["data_coverage"]["pitcher_logs"]["stale"])
        self.assertFalse(advanced["data_coverage"]["bullpen_log"]["stale"])

    def test_the_dossier_sections_beside_it_carry_no_label(self):
        sections = self.payload()["advanced"]["sections"]
        self.assertNotIn("results_stale", sections["teams"])
        self.assertNotIn("results_through", sections["teams"])
        self.assertEqual(sections["teams"],
                         team_features.matchup_features(self._store, "NYY", "BOS", self.DATE))

    def test_a_coverage_failure_costs_the_labels_never_the_page(self):
        with mock.patch.object(store_freshness, "coverage_for_game", side_effect=RuntimeError("boom")):
            payload = self.payload()
        self.assertIsNone(payload["advanced"]["data_coverage"])
        self.assertIn("quick", payload)

    def test_the_block_is_json_serialisable_with_the_rest(self):
        json.dumps(self.payload())


class HealthCarriesTheDataFreshness(unittest.TestCase):

    def test_it_is_present_informational_and_never_flips_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "historical").mkdir()
            store_freshness.reset_cache_for_tests()
            now = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)
            with mock.patch.object(apphealth, "check_app_db",
                                   return_value=apphealth.DbCheck(reachable=True, path="x")):
                data = apphealth.report(data_dir=root, now=now)
        fresh = data["data_freshness"]
        self.assertEqual(fresh["expected_through"], "2026-10-02")
        self.assertEqual(set(fresh["core_stale"]),
                         {"mlb_results", "pitcher_logs", "bullpen_log", "standings"})
        self.assertIn("guard", fresh)
        # every core store is absent here, and the site is still "ok": a stale
        # input is something the page labels, not a reason to leave rotation.
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["reasons"], [])

    def test_a_failure_inside_the_freshness_check_cannot_take_health_down(self):
        with mock.patch.object(store_freshness, "report", side_effect=RuntimeError("boom")):
            out = apphealth.check_data_freshness(Path("/nonexistent"), datetime.now(timezone.utc))
        self.assertIn("boom", out["error"])


class TheFetcherAsksForThePostseasonOnlyWhenTold(unittest.TestCase):

    def _log(self, **kw):
        seen = {}

        def fake(path, params=None, timeout=None):
            seen["params"] = dict(params or {})
            return {"stats": [{"splits": [
                {"date": "2026-09-29", "gameType": "F", "isHome": True,
                 "stat": {"gamesStarted": 1, "inningsPitched": "6.0", "earnedRuns": 2}}]}]}

        with mock.patch.object(mlb, "_get_json", fake):
            rows = mlb.fetch_pitcher_game_log(1, 2026, **kw)
        return rows, seen["params"]

    def test_the_default_request_and_rows_are_exactly_what_they_always_were(self):
        rows, params = self._log()
        self.assertEqual(params, {"stats": "gameLog", "group": "pitching", "season": 2026})
        self.assertNotIn("game_type", rows[0])

    def test_asking_for_the_postseason_tags_rows_and_never_requests_the_aggregate_P(self):
        rows, params = self._log(game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual(params["gameType"], "D,F,L,R,W")
        self.assertEqual(rows[0]["game_type"], "F")

    def test_P_alone_is_still_honoured(self):
        _rows, params = self._log(game_types={"P"})
        self.assertEqual(params["gameType"], "P")


class TheGuardIsOffByDefault(unittest.TestCase):

    def test_no_thread_starts_in_a_plain_process(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop(display_refresh.ENV_GUARD_INTERVAL, None)
            self.assertIsNone(display_refresh.start_background_guard())
        self.assertFalse(display_refresh.guard_status()["enabled"])


if __name__ == "__main__":
    unittest.main()
