"""src/situation/postseason_history.py: the display-only store of earlier postseasons.

The network is `get_json`; every test injects canned responses shaped like the Stats API's own, so
nothing here makes a request. The walls the module promises (never a training population, writes only
its own directory) are checked by reading the source and the paths, not trusted.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src import paths
from src.pipeline import history
from src.providers import mlb
from src.situation import cli as situation_cli
from src.situation import postseason_history as ph

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


def raw_game(pk, date, away, home, away_score, home_score, game_type="D", *, coded="F", detailed="Final",
             series_game=1, in_series=5, series_desc="Division Series", away_p="A Starter", home_p="H Starter"):
    """One game as the schedule endpoint returns it."""
    return {
        "gamePk": pk, "officialDate": date, "gameDate": f"{date}T23:00:00Z", "gameType": game_type,
        "seriesDescription": series_desc, "seriesGameNumber": series_game, "gamesInSeries": in_series,
        "status": {"codedGameState": coded, "detailedState": detailed},
        "venue": {"name": f"{home} Park"}, "doubleHeader": "N", "gameNumber": 1,
        "teams": {
            "away": {"team": {"id": 1, "abbreviation": away}, "score": away_score,
                     "probablePitcher": {"id": 11, "fullName": away_p}},
            "home": {"team": {"id": 2, "abbreviation": home}, "score": home_score,
                     "probablePitcher": {"id": 22, "fullName": home_p}},
        },
        "linescore": {"innings": []},
    }


def schedule_payload(*games):
    by_date = {}
    for g in games:
        by_date.setdefault(g["officialDate"], []).append(g)
    return {"dates": [{"date": d, "games": gs} for d, gs in sorted(by_date.items())]}


def standings_payload(rows):
    """rows: (team id, wins, losses). One division, as the standings endpoint returns it."""
    return {"records": [{"division": {"id": 201, "name": "AL East"}, "league": {"id": 103},
                         "teamRecords": [{"team": {"id": tid, "name": f"Club {tid}"}, "season": "2019",
                                          "wins": w, "losses": l, "gamesPlayed": w + l,
                                          "winningPercentage": f"{w / (w + l):.3f}", "divisionRank": "1",
                                          "gamesBack": "-"} for tid, w, l in rows]}]}


class FakeApi:
    """A `get_json` that answers from a table and remembers every request."""

    def __init__(self, schedule, standings):
        self.schedule, self.standings = schedule, standings
        self.calls = []

    def __call__(self, path, params=None, timeout=None):
        self.calls.append((path, dict(params or {}), timeout))
        if path == "schedule":
            season = int(str(params["startDate"])[:4])
            body = self.schedule[season]
        elif path == "standings":
            body = self.standings[int(params["season"])]
        else:
            raise AssertionError(f"unexpected request {path}")
        if isinstance(body, Exception):
            raise body
        return body


def two_seasons():
    sched = {
        2019: schedule_payload(raw_game(1, "2019-10-01", "MIL", "WSH", 3, 4, "F", in_series=1, series_desc="NL Wild Card Game"),
                               raw_game(2, "2019-10-03", "TB", "HOU", 2, 6, "D", series_game=1),
                               raw_game(3, "2019-10-04", "TB", "HOU", 4, 1, "D", series_game=2)),
        2018: schedule_payload(raw_game(10, "2018-10-02", "COL", "CHC", 2, 1, "F", in_series=1)),
    }
    stand = {2019: standings_payload([(139, 96, 66), (117, 107, 55), (109, 85, 77), (133, 97, 65)]),
             2018: standings_payload([(112, 95, 68)])}
    return FakeApi(sched, stand)


class TheParsing(unittest.TestCase):
    def test_a_final_postseason_game_becomes_a_row_with_its_series_facts(self):
        payload = schedule_payload(raw_game(2, "2019-10-03", "TB", "HOU", 2, 6, "D", series_game=1, in_series=5))
        [row] = ph.parse_schedule(2019, payload, fetched_utc="T", source_url="U")
        self.assertEqual((row["game_pk"], row["date"], row["game_type"], row["away_team"], row["home_team"]),
                         (2, "2019-10-03", "D", "TB", "HOU"))
        self.assertEqual((row["away_score"], row["home_score"], row["winner"], row["home_won"]), (2, 6, "HOU", 1))
        self.assertEqual((row["series_game_number"], row["games_in_series"], row["series_description"]),
                         (1, 5, "Division Series"))
        self.assertEqual((row["season"], row["source_url"], row["fetched_utc"]), (2019, "U", "T"))
        self.assertEqual((row["away_probable"], row["home_probable"]), ("A Starter", "H Starter"))

    def test_only_final_postseason_games_are_kept(self):
        payload = schedule_payload(
            raw_game(1, "2019-10-03", "TB", "HOU", 2, 6, "D"),
            raw_game(2, "2019-10-04", "TB", "HOU", None, None, "D", coded="S", detailed="Scheduled"),
            raw_game(3, "2019-10-04", "TB", "HOU", 1, 0, "D", coded="D", detailed="Postponed"),
            raw_game(4, "2019-09-28", "TB", "HOU", 5, 1, "R"),
            raw_game(5, "2019-10-05", "TB", "HOU", 1, 3, "S"))
        rows = ph.parse_schedule(2019, payload, fetched_utc="T", source_url="U")
        self.assertEqual([r["game_pk"] for r in rows], [1])

    def test_a_game_listed_as_postponed_and_final_on_the_same_day_is_one_game(self):
        payload = schedule_payload(raw_game(7, "2019-10-17", "NYY", "HOU", None, None, "L", coded="D", detailed="Postponed"),
                                   raw_game(7, "2019-10-17", "NYY", "HOU", 8, 3, "L"))
        rows = ph.parse_schedule(2019, payload, fetched_utc="T", source_url="U")
        self.assertEqual(len(rows), 1)

    def test_a_feed_that_ignores_the_game_type_query_cannot_put_a_regular_season_game_in(self):
        payload = schedule_payload(*[raw_game(i, "2019-09-28", "TB", "HOU", 3, 2, "R") for i in range(5)])
        self.assertEqual(ph.parse_schedule(2019, payload, fetched_utc="T", source_url="U"), [])

    def test_standings_become_one_final_record_per_club_under_one_spelling(self):
        rows = ph.parse_standings(2019, standings_payload([(109, 85, 77), (133, 97, 65), (139, 96, 66)]),
                                  as_of="final regular season", fetched_utc="T", source_url="U")
        self.assertEqual([(r["team"], r["wins"], r["losses"]) for r in rows],
                         [("ARI", 85, 77), ("OAK", 97, 65), ("TB", 96, 66)])        # AZ and ATH are ARI and OAK
        self.assertEqual({r["as_of"] for r in rows}, {"final regular season"})

    def test_a_record_with_no_wins_or_no_club_is_skipped_not_zero_filled(self):
        payload = standings_payload([(139, 96, 66)])
        payload["records"][0]["teamRecords"].append({"team": {"id": 99999}, "wins": 80, "losses": 82})
        payload["records"][0]["teamRecords"].append({"team": {"id": 117}, "wins": None, "losses": None})
        rows = ph.parse_standings(2019, payload, as_of="x", fetched_utc="T", source_url="U")
        self.assertEqual([r["team"] for r in rows], ["TB"])


class TheFetch(unittest.TestCase):
    def test_the_schedule_request_asks_for_the_four_postseason_types_in_the_postseason_window(self):
        api = two_seasons()
        ph.fetch_season(2019, get_json=api, fetched_utc="T", sleep=lambda s: None)
        path, params, _ = api.calls[0]
        self.assertEqual(path, "schedule")
        self.assertEqual(params["gameType"], "F,D,L,W")
        self.assertEqual((params["startDate"], params["endDate"]), ("2019-09-15", "2019-11-20"))
        self.assertIn("probablePitcher", params["hydrate"])

    def test_the_standings_request_carries_no_date(self):
        """The first run asked for 'the day before the first postseason game' and, on an off day, the
        feed answered with no divisions: a record for one season and none for the other ten."""
        api = two_seasons()
        ph.fetch_season(2019, get_json=api, fetched_utc="T", sleep=lambda s: None)
        path, params, _ = api.calls[1]
        self.assertEqual(path, "standings")
        self.assertNotIn("date", params)
        self.assertEqual(params["season"], 2019)

    def test_two_requests_a_season_and_a_pause_before_each(self):
        api, naps = two_seasons(), []
        ph.fetch_season(2019, get_json=api, fetched_utc="T", sleep=naps.append, delay=0.7)
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(naps, [0.7, 0.7])

    def test_a_season_with_no_games_makes_no_standings_request(self):
        api = FakeApi({2014: {"dates": []}}, {})
        games, records = ph.fetch_season(2014, get_json=api, fetched_utc="T", sleep=lambda s: None)
        self.assertEqual((games, records, len(api.calls)), ([], [], 1))

    def test_a_cached_response_costs_no_request_and_no_pause(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            api, naps = two_seasons(), []
            first = ph.fetch_season(2019, get_json=api, fetched_utc="T", cache=cache, sleep=naps.append)
            api2, naps2 = two_seasons(), []
            second = ph.fetch_season(2019, get_json=api2, fetched_utc="T", cache=cache, sleep=naps2.append)
        self.assertEqual((len(api.calls), len(api2.calls), naps2), (2, 0, []))
        self.assertEqual(first, second)

    def test_refresh_fetches_again(self):
        with tempfile.TemporaryDirectory() as d:
            ph.fetch_season(2019, get_json=two_seasons(), fetched_utc="T", cache=Path(d), sleep=lambda s: None)
            api = two_seasons()
            ph.fetch_season(2019, get_json=api, fetched_utc="T", cache=Path(d), sleep=lambda s: None, refresh=True)
        self.assertEqual(len(api.calls), 2)


class TheStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def ingest(self, seasons, api=None, **kw):
        return ph.ingest(seasons, self.root, get_json=api or two_seasons(), sleep=lambda s: None, now=NOW, **kw)

    def test_it_writes_games_records_and_a_manifest_that_says_what_the_store_is(self):
        m = self.ingest([2018, 2019])
        self.assertEqual((m["games"], m["season_records"], m["seasons"]), (4, 5, [2018, 2019]))
        self.assertIs(m["never_a_training_population"], True)
        self.assertIn("Never a training population", m["label"])
        self.assertEqual(m["fetched_utc"], "2026-10-03T12:00:00Z")
        for name in (ph.GAMES_FILE, ph.RECORDS_FILE, ph.MANIFEST_FILE):
            self.assertTrue((self.root / name).exists())
        self.assertEqual(json.loads((self.root / ph.MANIFEST_FILE).read_text(encoding="utf-8"))["games"], 4)

    def test_load_gives_the_games_and_the_records_keyed_by_season_and_club(self):
        self.ingest([2019])
        held = ph.load(self.root)
        self.assertEqual([g["game_pk"] for g in held.games], [1, 2, 3])
        self.assertEqual(held.seasons(), [2019])
        self.assertEqual(held.season_records[(2019, "TB")]["wins"], 96)
        self.assertEqual(held.season_records[(2019, "ARI")]["losses"], 77)

    def test_a_second_run_replaces_in_place_and_never_duplicates(self):
        self.ingest([2019])
        self.ingest([2019])
        held = ph.load(self.root)
        self.assertEqual(len(held.games), 3)
        self.assertEqual(len(held.season_records), 4)

    def test_a_new_season_is_merged_with_what_is_already_there(self):
        self.ingest([2019])
        m = self.ingest([2018])
        self.assertEqual((m["games"], m["seasons"]), (4, [2018, 2019]))

    def test_a_season_that_fails_is_reported_and_the_others_still_land(self):
        api = two_seasons()
        api.schedule[2018] = mlb.MLBError("could not reach MLB API for schedule")
        m = self.ingest([2018, 2019], api=api)
        self.assertEqual([e["season"] for e in m["errors"]], [2018])
        self.assertEqual(m["seasons"], [2019])
        self.assertEqual(len(ph.load(self.root).games), 3)

    def test_a_missing_store_is_empty_not_an_error_and_a_truncated_line_costs_one_row(self):
        self.assertEqual(ph.load(self.root).games, [])
        self.ingest([2019])
        with (self.root / ph.GAMES_FILE).open("a", encoding="utf-8") as fh:
            fh.write('{"game_pk": 99, "date": "2019-')           # a write that died mid-line
        self.assertEqual(len(ph.load(self.root).games), 3)

    def test_the_progress_callback_hears_each_season(self):
        heard = []
        self.ingest([2018, 2019], on_season=lambda season, games, records: heard.append((season, games, records)))
        self.assertEqual(heard, [(2018, 1, 1), (2019, 3, 4)])


class TheWalls(unittest.TestCase):
    """Display and research only: never a training population."""

    def test_the_store_is_not_where_the_training_data_is(self):
        root = ph.default_root().resolve()
        self.assertEqual(root.parts[-2:], ("research", "postseason_history"))
        self.assertNotIn(paths.historical_path().resolve(), root.parents)
        self.assertNotEqual(root, paths.historical_path().resolve())

    def test_no_pipeline_module_reads_it_or_the_situation_layer(self):
        pipeline = Path(paths.repo_root()) / "src" / "pipeline"
        offenders = []
        for path in sorted(pipeline.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for needle in ("postseason_history", "src.situation", "from src import situation"):
                if needle in text:
                    offenders.append(f"{path.name}: {needle}")
        self.assertEqual(offenders, [], "a module that fits or prices a model must not read the display-only store")

    def test_the_training_table_keeps_its_default_that_leaves_the_postseason_out(self):
        from src.pipeline import features
        self.assertEqual(features._TRAINING_GAME_TYPES, mlb.TRAINING_GAME_TYPES)
        self.assertEqual(set(mlb.TRAINING_GAME_TYPES), {"R"})

    def test_ingest_never_touches_the_results_store_or_its_manifest(self):
        before = {p: p.stat().st_mtime_ns for p in (history.DEFAULT_STORE, history.DEFAULT_MANIFEST)
                  if Path(p).exists()}
        with tempfile.TemporaryDirectory() as d:
            ph.ingest([2019], Path(d) / "s", get_json=two_seasons(), sleep=lambda s: None, now=NOW)
        after = {p: p.stat().st_mtime_ns for p in before}
        self.assertEqual(before, after)

    def test_only_postseason_game_types_are_stored(self):
        self.assertEqual(ph.POSTSEASON_TYPES, ("F", "D", "L", "W"))
        self.assertEqual(set(ph.POSTSEASON_TYPES) & set(mlb.TRAINING_GAME_TYPES), set())

    def test_the_results_store_wins_where_both_hold_a_game_and_the_standings_win_for_records(self):
        mine = {"game_pk": "1", "date": "2019-10-01", "game_type": "F", "away_team": "MIL", "home_team": "WSH",
                "away_score": "9", "home_score": "0", "winner": "MIL"}
        regular = [{"game_pk": str(500 + i), "date": "2019-09-01", "game_type": "R", "away_team": "TB",
                    "home_team": "NYY", "away_score": "3", "home_score": "1", "winner": "TB"} for i in range(3)]
        with tempfile.TemporaryDirectory() as d:
            ph.ingest([2019], Path(d), get_json=two_seasons(), sleep=lambda s: None, now=NOW)
            games, records = situation_cli.load_inputs(d, main=[mine] + regular)
        by_pk = {str(g["game_pk"]): g for g in games}
        self.assertEqual(by_pk["1"]["away_score"], "9")             # the results store's row, not the feed's
        self.assertEqual({"2", "3"} & set(by_pk), {"2", "3"})       # the feed's other games are there
        self.assertEqual((records[(2019, "TB")]["wins"], records[(2019, "TB")]["losses"]), (96, 66))   # standings
        self.assertEqual(records[(2019, "NYY")], {"wins": 0, "losses": 3})                              # games, no standings


class TheIngestCommand(unittest.TestCase):
    def test_the_command_ingests_and_says_what_it_stored(self):
        out = []
        with tempfile.TemporaryDirectory() as d:
            code = situation_cli.execute_ingest(start=2018, end=2019, root=str(Path(d) / "s"),
                                                get_json=two_seasons(), cache=Path(d) / "cache",
                                                sleep=lambda s: None, out=out.append)
        self.assertEqual(code, 0)
        text = "\n".join(out)
        self.assertIn("2019: 3 postseason games, 4 club records", text)
        self.assertIn("store: 4 games and 5 club records over 2 seasons (2018 to 2019)", text)

    def test_an_end_before_the_start_is_an_error(self):
        out = []
        self.assertEqual(situation_cli.execute_ingest(start=2020, end=2019, out=out.append), 2)
        self.assertIn("ERROR", out[0])


if __name__ == "__main__":
    unittest.main()
