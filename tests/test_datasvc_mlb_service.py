"""src/datasvc/mlb/service.py: MLB through the data service's door, offline and injected.

The stores are a temporary directory, the schedule provider is a counting fake, the clock is a list the
test advances and every read of a file goes through a counter. Nothing here touches the repo's data, the
network or the real clock.

What is pinned, in the order of the task's acceptance list:
  * a packet is byte for byte the analyst's own (same hash as `cli._packet` over the same item);
  * fifty reads of an unchanged snapshot make zero upstream requests and open zero files;
  * a store version change invalidates, and every packet is internally consistent with its version (a
    change DURING a build is caught and the build repeated);
  * the history of each dataset says whether it was observed at the time or reconstructed later;
  * stale, unknown and unreachable are said as such, never zeros, never a made-up name.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.analyst import cli
from src.analyst import packet as packet_mod
from src.datasvc import client as core
from src.datasvc.mlb import service as svc
from tests import analyst_fixtures as F

NOW = F.NOW
DATE = F.DATE


def schedule_game(pk=849835, away="NYY", home="TB", state="pending", **over):
    game = {"game_pk": pk, "date": DATE, "start_time_utc": F.FIRST_PITCH, "state": state, "game_type": "D",
            "detailed_state": "Final" if state == "final" else "Scheduled", "venue": "Tropicana Field",
            "away_team": away, "home_team": home, "away_team_id": 147, "home_team_id": 139,
            "away_score": None, "home_score": None, "away_probable": "Gerrit Cole", "home_probable": "Drew Rasmussen",
            "away_probable_id": 543037, "home_probable_id": 656876, "double_header": "N", "game_number": 1,
            "winner": None, "home_won": None, "total_runs": None, "run_differential": None}
    if state == "final":
        game.update(away_score=9, home_score=1, winner=away, home_won=0, total_runs=10, run_differential=8)
    game.update(over)
    return game


@contextlib.contextmanager
def counting_opens():
    """Counts every open() of a file while active (builtins.open and io.open, which Path.open calls)."""
    counter = {"n": 0, "paths": []}
    real_builtin, real_io = builtins.open, io.open

    def wrap(real):
        def counted(file, *a, **k):
            counter["n"] += 1
            counter["paths"].append(str(file))
            return real(file, *a, **k)
        return counted

    with mock.patch.object(builtins, "open", wrap(real_builtin)), mock.patch.object(io, "open", wrap(real_io)):
        yield counter


class World:
    """Two real store files, a loader that READS them, a counting schedule fetcher and a movable clock."""

    def __init__(self, directory: Path, games=None):
        self.dir = directory
        self.results = directory / "mlb_results.csv"
        self.odds = directory / "odds_multibook.jsonl"
        self.set_results("results v1")
        self.set_odds("odds v1")
        self.games = list(games if games is not None else [schedule_game()])
        self.fetches = []
        self.fetch_error = None
        self.now = NOW
        self.builds = 0
        self.on_build = None            # called inside the loader, after it read the files
        self.service = svc.MlbService(
            fetch_games=self.fetch, loader=self.load, stores=self.stores(), clock=lambda: self.now,
            config_loader=lambda: dict(F.CFG), data_root=directory / "data",
            results_reader=lambda: {}, pitcher_reader=lambda: {})

    def stores(self):
        return (svc.StoreFile("mlb_results", lambda d: self.results),
                svc.StoreFile("odds_multibook", lambda d: self.odds, segments=True))

    def set_results(self, text):
        self.results.write_text(text, encoding="utf-8")

    def set_odds(self, text):
        self.odds.write_text(text, encoding="utf-8")

    def fetch(self, date):
        self.fetches.append(date)
        if self.fetch_error:
            raise RuntimeError(self.fetch_error)
        return [dict(g) for g in self.games]

    def load(self, date, games, now):
        """The analyst's per-game items, with the file contents folded into the game so a packet shows which
        version of the files it was built from."""
        self.builds += 1
        marker = f"{self.results.read_text(encoding='utf-8')}|{self.odds.read_text(encoding='utf-8')}"
        if self.on_build:
            self.on_build()
        items = []
        for g in games:
            payload = F.payload(g["state"])
            game = payload["advanced"]["game"]
            game.update(game_pk=g["game_pk"], away_team=g["away_team"], home_team=g["home_team"],
                        venue=marker, state=g["state"])
            items.append({"payload": payload, "multibook_rows": F.multibook_rows(),
                          "team_total_rows": F.team_total_rows(), "batter_prop_rows": F.batter_prop_rows(),
                          "pitcher_prop_rows": F.pitcher_prop_rows(), "prop_board": F.prop_board(),
                          "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"},
                          "section_as_of": {"teams": "2026-10-02", "starters": "2026-10-02"}})
        return items


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.world = World(Path(self._tmp.name))
        self.svc = self.world.service


class Rows(Base):
    def test_a_final_game_has_its_result_and_an_unplayed_one_has_none(self):
        self.world.games = [schedule_game(pk=1, state="final", away_score=9),
                            schedule_game(pk=2, away="BOS", home="BAL", away_probable=None, away_probable_id=None,
                                          home_probable=None, home_probable_id=None)]
        out = self.svc.games(DATE)
        self.assertTrue(out["available"])
        final, pending = out["data"]
        self.assertEqual(final["result"], {"away_score": 9, "home_score": 1, "winner": "NYY", "home_won": 0,
                                           "total_runs": 10, "run_differential": 8})
        self.assertIsNone(pending["result"])                               # never a 0-0 for a game not played
        self.assertIsNone(pending["away"]["probable_starter"])             # never a made-up starter
        self.assertEqual(final["probable_starter_basis"], "retroactive")
        self.assertEqual(pending["probable_starter_basis"], "as_listed_at_observed_utc")

    def test_a_game_in_progress_shows_no_score(self):
        self.world.games = [schedule_game(state="pending", detailed_state="In Progress", away_score=3, home_score=2)]
        row = self.svc.games(DATE)["data"][0]
        self.assertIsNone(row["result"])

    def test_games_come_in_schedule_order_and_say_when_the_schedule_was_read(self):
        self.world.games = [schedule_game(pk=2, start_time_utc="2026-10-03T23:30:00Z"), schedule_game(pk=1)]
        out = self.svc.games(DATE)
        self.assertEqual([r["game_pk"] for r in out["data"]], [1, 2])
        self.assertEqual(out["meta"]["observed_utc"], "2026-10-03T18:00:00Z")
        self.assertEqual(out["meta"]["sport"], "mlb")

    def test_an_off_day_is_an_empty_slate_that_says_so(self):
        self.world.games = []
        out = self.svc.games(DATE)
        self.assertTrue(out["available"])
        self.assertEqual(out["data"], [])
        self.assertEqual([m["item"] for m in out["meta"]["missing"]], ["games"])

    def test_a_malformed_date_is_the_callers_mistake(self):
        for bad in (None, "", "2026-13-40", "10/03/2026", "2026-1-3"):
            with self.assertRaises(core.DataError) as ctx:
                self.svc.games(bad)
            self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(self.world.fetches, [])                           # refused before any request

    def test_participants_name_the_clubs_and_the_probable_starters_with_ids(self):
        out = self.svc.participants(DATE)
        self.assertEqual(out["data"]["clubs"], [{"team": "NYY", "team_id": 147}, {"team": "TB", "team_id": 139}])
        self.assertEqual([s["person_id"] for s in out["data"]["probable_starters"]], [543037, 656876])

    def test_game_finds_one_game_and_says_so_when_there_is_none(self):
        self.assertEqual(self.svc.game(DATE, "nyy", "tb")["data"]["game_pk"], 849835)
        miss = self.svc.game(DATE, "BOS", "BAL")
        self.assertFalse(miss["available"])
        self.assertEqual(miss["missing"][0]["code"], "not_found")


class PacketIsTheAnalysts(Base):
    def test_the_packet_is_byte_for_byte_what_the_analyst_builds(self):
        built_at = "2026-10-03T18:00:00Z"
        out = self.svc.packet(DATE, "NYY", "TB", built_at=built_at)
        self.assertTrue(out["available"])
        item = self.world.load(DATE, [schedule_game()], NOW)[0]
        direct = cli._packet(item, built_at, F.CFG)
        self.assertEqual(packet_mod.packet_hash(out["data"]), packet_mod.packet_hash(direct))
        self.assertEqual(json.dumps(out["data"]), json.dumps(direct))      # same bytes, same key order
        self.assertEqual(out["meta"]["packet_hash"], packet_mod.packet_hash(direct))

    def test_the_default_loader_makes_the_items_the_analysts_loader_makes(self):
        """`default_loader` is `cli.default_loader` with the schedule supplied: with the `source` functions
        patched to canned data, both return the same items."""
        games = [schedule_game()]
        slate = [{"payload": F.payload(), "game": F.payload()["advanced"]["game"]}]
        rows = {849835: {"multibook": F.multibook_rows(), "team_totals": F.team_total_rows(),
                         "batter_props": F.batter_prop_rows(), "pitcher_props": F.pitcher_prop_rows(),
                         "team_names": {"away": "New York Yankees", "home": "Tampa Bay Rays"}}}
        from src.analyst import source
        with mock.patch.object(source, "slate_payloads", return_value=slate) as slate_mock, \
                mock.patch.object(source, "price_rows", return_value=rows), \
                mock.patch.object(source, "prop_board_for", return_value={849835: F.prop_board()}), \
                mock.patch.object(source, "stats_through", return_value="2026-10-02"):
            ours = svc.default_loader(DATE, games, NOW)
            theirs = cli.default_loader(DATE)
        self.assertEqual(ours, theirs)
        passed_fetch = slate_mock.call_args_list[0].kwargs["fetch_games"]
        self.assertEqual(passed_fetch("anything"), games)                  # the service's one schedule read is used

    def test_a_doubleheader_is_ambiguous_and_an_unknown_game_is_not_found(self):
        self.world.games = [schedule_game(pk=1), schedule_game(pk=2, game_number=2)]
        dh = self.svc.packet(DATE, "NYY", "TB")
        self.assertFalse(dh["available"])
        self.assertEqual(dh["missing"][0]["code"], "ambiguous")
        unknown = self.svc.packet(DATE, "LAD", "SF")
        self.assertEqual(unknown["missing"][0]["code"], "not_found")

    def test_serving_a_packet_writes_nothing(self):
        before = sorted(p.name for p in Path(self._tmp.name).iterdir())
        self.svc.packet(DATE, "NYY", "TB")
        self.assertEqual(sorted(p.name for p in Path(self._tmp.name).iterdir()), before)

    def test_a_bad_built_at_is_the_callers_mistake(self):
        with self.assertRaises(core.DataError) as ctx:
            self.svc.packet(DATE, "NYY", "TB", built_at="yesterday-ish")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (422, "invalid_parameter"))


class MetaIsHonest(Base):
    def setUp(self):
        super().setUp()
        self.meta = self.svc.packet(DATE, "NYY", "TB")["meta"]

    def test_ids_and_the_provider_mapping_are_stable_and_named(self):
        ids = self.meta["ids"]
        self.assertEqual((ids["game_pk"], ids["away"], ids["home"]), (849835, "NYY", "TB"))
        self.assertEqual(ids["provider_ids"]["mlb_statsapi"]["game_pk"], 849835)
        self.assertEqual(self.meta["units"]["prices"], "American odds")

    def test_every_source_names_its_basis(self):
        by_name = {s["dataset"]: s for s in self.meta["sources"]}
        self.assertEqual(by_name["schedule"]["basis"], core.RECONSTRUCTED)
        self.assertIn("retroactive", by_name["schedule"]["basis_note"])
        self.assertEqual(by_name["odds_multibook"]["basis"], core.OBSERVED)
        self.assertEqual(by_name["mlb_results"]["basis"], core.RECONSTRUCTED)
        self.assertIn("retroactive", by_name["mlb_results"]["basis_note"])
        for source in self.meta["sources"]:
            self.assertTrue(source["basis"] and source["basis_note"] and source["source"], source)

    def test_basis_table_covers_every_store_a_packet_is_built_from_or_says_it_does_not(self):
        for name in svc.PACKET_STORES:
            claim = core.BASIS["mlb"].get(name)
            if claim is None:
                continue                                                   # reported as not_classified, no claim
            self.assertIn(claim["basis"], (core.OBSERVED, core.RECONSTRUCTED, core.SINGLE_VALUE), name)

    def test_our_observation_time_is_the_schedule_read_and_a_quote_keeps_its_own(self):
        self.assertEqual(self.meta["observed_utc"], "2026-10-03T18:00:00Z")
        self.assertEqual(self.meta["newest_quote_as_of"], "2026-10-03T16:51:16Z")

    def test_the_source_update_time_is_the_books_own_where_a_row_supplies_one(self):
        self.assertIsNone(self.meta["source_updated_utc"])
        self.assertTrue(self.meta["source_updated_utc_reason"])
        rows = F.multibook_rows()
        for row in rows:
            row["last_update"] = "2026-10-03T16:50:00Z"
        rows[0]["last_update"] = "2026-10-03T16:50:30Z"
        world = self.world
        original = world.load

        def with_updates(date, games, now):
            items = original(date, games, now)
            items[0]["multibook_rows"] = rows
            return items

        service = svc.MlbService(fetch_games=world.fetch, loader=with_updates, stores=world.stores(),
                                 clock=lambda: NOW, config_loader=lambda: dict(F.CFG))
        meta = service.packet(DATE, "NYY", "TB")["meta"]
        self.assertEqual(meta["source_updated_utc"], "2026-10-03T16:50:30Z")

    def test_missing_reasons_come_from_the_packet_unchanged(self):
        packet = self.svc.packet(DATE, "NYY", "TB")["data"]
        self.assertEqual(self.meta["missing"], packet["missing"])
        self.assertTrue(all(m["reason"] for m in self.meta["missing"]))

    def test_the_data_version_names_the_file_kind_and_is_a_stable_hash(self):
        again = svc.MlbService(fetch_games=self.world.fetch, loader=self.world.load, stores=self.world.stores(),
                               clock=lambda: NOW, config_loader=lambda: dict(F.CFG))
        meta2 = again.packet(DATE, "NYY", "TB")["meta"]
        self.assertEqual(meta2["data_version"], self.meta["data_version"])  # same files, same schedule, same hash
        self.assertTrue(self.meta["data_version"].startswith("dv1-"))
        files = {s["dataset"]: s for s in self.meta["sources"]}
        self.assertEqual(files["odds_multibook"]["version_kind"], "size_and_mtime_on_this_machine")


class Caching(Base):
    def test_fifty_reads_of_an_unchanged_snapshot_cost_no_upstream_request_and_no_file_open(self):
        first = self.svc.packet(DATE, "NYY", "TB")                         # warm: one fetch, one build
        self.assertEqual((len(self.world.fetches), self.world.builds), (1, 1))
        with counting_opens() as opens:
            for i in range(50):
                self.world.now = NOW + timedelta(seconds=i)                # time passes, inside the TTL
                out = self.svc.packet(DATE, "NYY", "TB")
                self.assertEqual(out, first)                               # the very answer, not a rebuild
                self.svc.games(DATE)
        self.assertEqual(opens["n"], 0, opens["paths"])
        self.assertEqual(len(self.world.fetches), 1)                       # zero upstream requests after the warm read
        self.assertEqual(self.world.builds, 1)
        self.assertEqual(self.svc.counters["packet_builds"], 1)
        self.assertEqual(self.svc.counters["packet_cache_hits"], 50)

    def test_a_cached_packet_keeps_its_own_time_never_a_fresh_one(self):
        first = self.svc.packet(DATE, "NYY", "TB")
        self.world.now = NOW + timedelta(seconds=90)
        again = self.svc.packet(DATE, "NYY", "TB")
        self.assertEqual(again["meta"]["built_utc"], first["meta"]["built_utc"])
        self.assertEqual(again["data"]["built_at"], first["data"]["built_at"])

    def test_a_chosen_built_at_is_cut_from_the_cached_items_without_reading_a_store(self):
        self.svc.packet(DATE, "NYY", "TB")
        with counting_opens() as opens:
            out = self.svc.packet(DATE, "NYY", "TB", built_at="2026-10-03T17:00:00Z")
        self.assertEqual(opens["n"], 0)
        self.assertEqual(out["data"]["built_at"], "2026-10-03T17:00:00Z")
        self.assertEqual((len(self.world.fetches), self.world.builds), (1, 1))

    def test_the_schedule_is_read_again_after_its_ttl_and_an_equal_read_changes_nothing(self):
        first = self.svc.packet(DATE, "NYY", "TB")
        self.world.now = NOW + timedelta(seconds=svc.DEFAULT_SCHEDULE_TTL_S + 1)
        again = self.svc.packet(DATE, "NYY", "TB")
        self.assertEqual(len(self.world.fetches), 2)                       # one more upstream request, by design
        self.assertEqual(again, first)                                     # the same schedule: the same snapshot
        self.assertEqual(self.svc.counters["packet_builds"], 1)
        self.assertEqual(again["meta"]["observed_utc"], "2026-10-03T18:00:00Z")

    def test_a_store_version_change_invalidates(self):
        before = self.svc.packet(DATE, "NYY", "TB")
        self.world.set_odds("odds v2 which is longer")
        after = self.svc.packet(DATE, "NYY", "TB")
        self.assertNotEqual(before["meta"]["data_version"], after["meta"]["data_version"])
        self.assertIn("odds v2", after["data"]["game"]["venue"])
        self.assertEqual(self.world.builds, 2)
        self.assertEqual(len(self.world.fetches), 1)                       # the schedule did not need re-reading

    def test_a_changed_schedule_invalidates_and_is_part_of_the_version(self):
        before = self.svc.packet(DATE, "NYY", "TB")
        self.world.games = [schedule_game(away_probable="Carlos Rodon", away_probable_id=607074)]
        self.world.now = NOW + timedelta(seconds=svc.DEFAULT_SCHEDULE_TTL_S + 1)
        after = self.svc.packet(DATE, "NYY", "TB")
        self.assertNotEqual(before["meta"]["data_version"], after["meta"]["data_version"])
        self.assertEqual(after["meta"]["observed_utc"], "2026-10-03T18:02:01Z")

    def test_a_version_bump_in_the_middle_of_a_sequence_gives_internally_consistent_packets(self):
        seen = []
        for i in range(50):
            if i == 25:
                self.world.set_results("results v2, rewritten")
            out = self.svc.packet(DATE, "NYY", "TB")
            marker = out["data"]["game"]["venue"]                          # what the build actually read
            seen.append((out["meta"]["data_version"], marker))
        versions = {v for v, _ in seen}
        self.assertEqual(len(versions), 2)
        for version in versions:
            markers = {m for v, m in seen if v == version}
            self.assertEqual(len(markers), 1, "one version, one set of file contents")
        self.assertEqual(seen[0][1], "results v1|odds v1")
        self.assertEqual(seen[-1][1], "results v2, rewritten|odds v1")
        self.assertEqual({v for v, _ in seen[:25]} & {v for v, _ in seen[25:]}, set())

    def test_a_store_that_changes_during_a_build_is_read_again_so_one_packet_never_mixes_versions(self):
        fired = []

        def change_once():
            if not fired:
                fired.append(1)
                self.world.set_odds("odds v2 arrived mid read")

        self.world.on_build = change_once
        out = self.svc.packet(DATE, "NYY", "TB")
        self.assertEqual(self.world.builds, 2)                             # the first build was thrown away
        self.assertIn("odds v2 arrived mid read", out["data"]["game"]["venue"])
        self.assertEqual(out["meta"]["data_version"],
                         self.svc.packet(DATE, "NYY", "TB")["meta"]["data_version"])

    def test_stores_that_never_stop_changing_are_unavailable_not_a_mixed_packet(self):
        counter = []

        def always_change():
            counter.append(1)
            self.world.set_odds(f"odds change {len(counter)}")

        self.world.on_build = always_change
        out = self.svc.packet(DATE, "NYY", "TB")
        self.assertFalse(out["available"])
        self.assertEqual(out["missing"][0]["item"], "snapshot")
        self.assertEqual(self.world.builds, svc.BUILD_ATTEMPTS)

    def test_a_caller_that_edits_its_answer_does_not_edit_the_cache(self):
        first = self.svc.packet(DATE, "NYY", "TB")
        first["data"]["markets"].clear()
        first["meta"]["ids"]["game_pk"] = -1
        again = self.svc.packet(DATE, "NYY", "TB")
        self.assertIn("moneyline", again["data"]["markets"])
        self.assertEqual(again["meta"]["ids"]["game_pk"], 849835)

    def test_only_the_newest_dates_are_held_so_the_memory_is_bounded(self):
        days = [f"2026-09-{n:02d}" for n in range(10, 10 + svc.MAX_DATES_HELD + 3)]
        for day in days:
            self.world.games = [schedule_game(date=day)]
            self.svc.packet(day, "NYY", "TB")
        self.assertEqual(len(self.svc._items), svc.MAX_DATES_HELD)
        self.assertEqual(list(self.svc._items), days[-svc.MAX_DATES_HELD:])
        self.assertTrue(all(key[0] in self.svc._items for key in self.svc._packets))
        before = self.world.builds
        self.svc.packet(days[-1], "NYY", "TB")                              # the newest is still held
        self.assertEqual(self.world.builds, before)
        self.svc.packet(days[0], "NYY", "TB")                               # the oldest was dropped: built again
        self.assertEqual(self.world.builds, before + 1)

    def test_other_dates_and_other_games_do_not_share_a_cached_packet(self):
        self.world.games = [schedule_game(pk=1), schedule_game(pk=2, away="BOS", home="BAL")]
        a = self.svc.packet(DATE, "NYY", "TB")
        b = self.svc.packet(DATE, "BOS", "BAL")
        self.assertEqual((a["data"]["game"]["game_pk"], b["data"]["game"]["game_pk"]), (1, 2))
        self.assertEqual(self.world.builds, 1)                              # one date's items serve both games


class Unreachable(Base):
    def test_no_schedule_and_none_held_is_unavailable_with_the_reason(self):
        self.world.fetch_error = "timed out"
        out = self.svc.packet(DATE, "NYY", "TB")
        self.assertFalse(out["available"])
        self.assertEqual(out["missing"][0]["code"], "unavailable")
        self.assertIn("timed out", out["missing"][0]["reason"])

    def test_a_failed_refresh_serves_the_earlier_read_and_says_it_is_old(self):
        first = self.svc.games(DATE)
        self.world.fetch_error = "provider down"
        self.world.now = NOW + timedelta(seconds=svc.DEFAULT_SCHEDULE_TTL_S + 1)
        out = self.svc.games(DATE)
        self.assertEqual(out["data"], first["data"])
        self.assertEqual(out["meta"]["observed_utc"], "2026-10-03T18:00:00Z")    # never a fresh timestamp on old data
        self.assertEqual(out["meta"]["missing"][0]["kind"], "stale")
        self.assertIn("provider down", out["meta"]["missing"][0]["reason"])

    def test_an_outage_costs_one_request_per_ttl_window_not_one_per_call(self):
        self.svc.games(DATE)
        self.world.fetch_error = "provider down"
        self.world.now = NOW + timedelta(seconds=svc.DEFAULT_SCHEDULE_TTL_S + 1)
        for _ in range(10):
            self.svc.games(DATE)
        self.assertEqual(len(self.world.fetches), 2)

    def test_games_fall_back_to_the_results_store_and_say_so(self):
        row = {"game_pk": "5", "date": DATE, "start_time_utc": F.FIRST_PITCH, "away_team": "NYY", "home_team": "TB",
               "away_team_id": "147", "home_team_id": "139", "away_score": "3", "home_score": "2", "winner": "NYY",
               "home_won": "0", "total_runs": "5", "run_differential": "1", "away_probable": "Gerrit Cole",
               "away_probable_id": "543037", "home_probable": None, "home_probable_id": None,
               "game_type": "R", "venue": "Tropicana Field", "double_header": "N", "game_number": "1"}
        service = svc.MlbService(fetch_games=self.world.fetch, stores=self.world.stores(), clock=lambda: NOW,
                                 results_reader=lambda: {"5": row})
        self.world.fetch_error = "provider down"
        out = service.games(DATE)
        self.assertTrue(out["available"])
        self.assertEqual(out["data"][0]["result"]["away_score"], 3)
        self.assertIsNone(out["data"][0]["home"]["probable_starter"])
        self.assertEqual(out["data"][0]["probable_starter_basis"], "retroactive")
        self.assertIsNone(out["meta"]["observed_utc"])
        self.assertIn("results store", out["meta"]["missing"][0]["reason"])
        self.assertEqual(service.games("2026-10-04")["missing"][0]["code"], "unavailable")   # nothing stored for that date


class PitcherHistory(Base):
    def setUp(self):
        super().setUp()
        logs = {"543037": [{"person_id": 543037, "date": "2026-09-01", "innings_pitched": 6.0},
                           {"person_id": 543037, "date": "2026-09-07", "innings_pitched": 5.1},
                           {"person_id": 543037, "date": None, "checked_utc": "2026-09-08T00:00:00Z"}]}
        self.svc = svc.MlbService(fetch_games=self.world.fetch, loader=self.world.load, stores=self.world.stores(),
                                  clock=lambda: NOW, pitcher_reader=lambda: logs)
        self.world.stores = lambda: (svc.StoreFile("pitcher_logs", lambda d: self.world.results),)

    def test_appearances_newest_first_without_the_bookkeeping_marker(self):
        out = self.svc.pitcher_history("543037")
        self.assertEqual([a["date"] for a in out["data"]["appearances"]], ["2026-09-07", "2026-09-01"])
        self.assertEqual(out["page"]["total"], 2)
        self.assertEqual(out["meta"]["sources"][0]["basis"], core.RECONSTRUCTED)

    def test_an_unknown_pitcher_is_unavailable_and_a_name_is_refused(self):
        out = self.svc.pitcher_history("1")
        self.assertFalse(out["available"])
        self.assertEqual(out["missing"][0]["code"], "not_found")
        with self.assertRaises(core.DataError):
            self.svc.pitcher_history("Gerrit Cole")


class Status(unittest.TestCase):
    def test_status_reports_every_store_with_how_its_history_was_obtained_and_never_calls_an_absent_one_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = svc.MlbService(data_root=Path(tmp), clock=lambda: NOW)
            out = service.status(NOW)
        self.assertEqual(out["datasets"]["mlb_results"]["present"], False)
        self.assertTrue(out["datasets"]["mlb_results"]["stale"])
        self.assertEqual(out["datasets"]["mlb_results"]["basis"], core.RECONSTRUCTED)
        self.assertEqual(out["datasets"]["standings"]["basis"], core.OBSERVED)
        self.assertEqual(out["datasets"]["transactions"]["basis"], "not_classified")
        self.assertIn("mlb_results", out["core_stale"])

    def test_a_current_store_is_reported_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / "historical"
            hist.mkdir()
            (hist / "standings.jsonl").write_text(json.dumps({"date": "2026-10-02", "team": "NYY"}) + "\n",
                                                  encoding="utf-8")
            out = svc.MlbService(data_root=Path(tmp), clock=lambda: NOW).status(NOW)
        entry = out["datasets"]["standings"]
        self.assertEqual((entry["present"], entry["through"]), (True, "2026-10-02"))
        self.assertFalse(entry["stale"])


if __name__ == "__main__":
    unittest.main()
