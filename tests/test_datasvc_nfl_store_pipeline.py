"""src/datasvc/nfl/store.py and pipeline.py: the files on disk, and the backfill and update that fill them.

The whole chain runs offline: `tests/_nfl_world.py` serves a small league in nflverse's own CSV shape
through a fake fetcher, and the backfill must rebuild exactly the store the world builds directly.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from src.datasvc import store as jsonl
from src.datasvc.nfl import pipeline, sources
from src.datasvc.nfl.store import (DATE_FIELDS, FILES, KEYS, NflStore, content_of, counts_toward_newest,
                                   position_group)
from tests import _nfl_world as W
from tests._nfl_world import FakeFetcher

NOW = datetime(2025, 10, 20, 12, 0, tzinfo=timezone.utc)
TODAY = date(2025, 10, 20)
QUIET = lambda message: None  # noqa: E731


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root: Path) -> dict:
    """{file name: (sha256, modification time in ns)} for every file under a store directory."""
    return {p.name: (sha(p), p.stat().st_mtime_ns) for p in sorted(Path(root).iterdir())}


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "nfl"


class TheStoreOnDisk(TempDirCase):
    def test_the_files_keys_and_dates_are_the_contract(self):
        self.assertEqual(FILES, {"games": "games.jsonl", "team_games": "team_games.jsonl",
                                 "player_games": "player_games.jsonl", "injuries": "injuries.jsonl"})
        self.assertEqual(KEYS, {"games": "game_id", "team_games": ("game_id", "team"),
                                "player_games": ("game_id", "player_id"), "injuries": ("game_id", "player_id")})
        self.assertEqual(DATE_FIELDS["games"], "kickoff_utc")
        self.assertEqual(DATE_FIELDS["injuries"], "fetched_utc")

    def test_a_round_trip_keeps_every_record_in_key_order_with_keys_sorted(self):
        store = W.build_world(self.dir)
        world = W.world_rows()
        for name in FILES:
            on_disk = NflStore(self.dir).load(name)
            key = KEYS[name]
            expected = sorted(world[name], key=lambda r: jsonl.key_of(r, key))
            self.assertEqual(on_disk, expected, name)
        first = (self.dir / "games.jsonl").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(list(json.loads(first)), sorted(json.loads(first)))                 # keys sorted inside a record
        self.assertNotIn("\r", (self.dir / "games.jsonl").read_text(encoding="utf-8"))       # LF only, always

    def test_an_unchanged_row_keeps_its_stored_fetch_time_and_a_changed_row_takes_the_new_one(self):
        store = NflStore(self.dir)
        row = dict(W.world_rows()["games"][0])
        store.upsert("games", [dict(row, fetched_utc="2025-01-01T00:00:00Z")])
        counts = store.upsert("games", [dict(row, fetched_utc="2025-06-01T00:00:00Z")])
        self.assertEqual((counts["added"], counts["updated"], counts["unchanged"]), (0, 0, 1))
        self.assertEqual(NflStore(self.dir).games[0]["fetched_utc"], "2025-01-01T00:00:00Z")      # first fetched, still
        counts = store.upsert("games", [dict(row, home_score=99, fetched_utc="2025-06-01T00:00:00Z")])
        self.assertEqual((counts["added"], counts["updated"], counts["unchanged"]), (0, 1, 0))
        got = NflStore(self.dir).games[0]
        self.assertEqual((got["home_score"], got["fetched_utc"]), (99, "2025-06-01T00:00:00Z"))

    def test_a_call_that_changes_nothing_does_not_write_the_file(self):
        store = W.build_world(self.dir)
        before = tree(self.dir)
        counts = store.upsert("games", W.world_rows()["games"])
        self.assertEqual((counts["added"], counts["updated"], counts["unchanged"]), (0, 0, 15))
        self.assertEqual(tree(self.dir), before)          # same bytes and the same modification time

    def test_a_key_repeated_in_one_batch_keeps_the_last_and_nothing_is_ever_deleted(self):
        store = NflStore(self.dir)
        a = W.world_rows()["games"][0]
        b = W.world_rows()["games"][1]
        store.upsert("games", [dict(a, home_score=1), dict(a, home_score=2), b])
        self.assertEqual({g["game_id"]: g["home_score"] for g in store.games}, {a["game_id"]: 2, b["game_id"]: b["home_score"]})
        store.upsert("games", [dict(a, home_score=3)])
        self.assertEqual(len(store.games), 2)              # b is still there although this batch did not mention it

    def test_a_record_missing_a_key_field_is_refused(self):
        with self.assertRaises(ValueError):
            NflStore(self.dir).upsert("games", [{"season": 2025}])

    def test_newest_is_the_newest_game_played_not_the_newest_booked(self):
        store = W.build_world(self.dir)
        self.assertEqual(store.newest("games"), W.eastern("2025-10-19", "09:30"))     # g13; g14 and g15 are booked
        self.assertEqual(store.newest("team_games"), W.eastern("2025-10-19", "09:30"))
        self.assertEqual(store.newest("player_games"), W.eastern("2025-10-12", "09:30"))
        self.assertEqual(store.newest("injuries"), W.FETCHED)

    def test_only_a_final_game_counts_toward_newest(self):
        for status, counts in (("final", True), ("scheduled", False), ("removed", False), ("no_result", False),
                               ("in_progress", False)):
            self.assertEqual(counts_toward_newest("games", {"status": status}), counts, status)
        self.assertTrue(counts_toward_newest("injuries", {"status": "scheduled"}))

    def test_next_scheduled_is_the_soonest_booked_kickoff_after_a_moment(self):
        store = W.build_world(self.dir)
        self.assertEqual(store.next_scheduled("games"), W.eastern("2025-10-26", "16:05"))       # g15 kicks off before g14
        self.assertEqual(store.next_scheduled("games", after=datetime(2025, 10, 26, 20, 10, tzinfo=timezone.utc)),
                         W.eastern("2025-10-26", "16:25"))
        self.assertIsNone(store.next_scheduled("games", after=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertIsNone(store.next_scheduled("injuries"))

    def test_the_manifest_describes_the_files_on_disk_and_carries_the_attribution(self):
        store = W.build_world(self.dir)
        manifest = store.write_manifest(extra={"coverage": {"seasons": [2024, 2025]}})
        on_disk = json.loads((self.dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["files"], on_disk["files"])
        for name, info in on_disk["files"].items():
            path = self.dir / name
            self.assertEqual((info["bytes"], info["sha256"]), (path.stat().st_size, sha(path)), name)
        self.assertEqual(on_disk["files"]["games.jsonl"]["records"], 15)
        self.assertIn("CC BY 4.0", on_disk["attribution"])
        self.assertIn("nflverse", on_disk["attribution"])
        self.assertEqual(on_disk["coverage"], {"seasons": [2024, 2025]})

    def test_the_indexes(self):
        store = W.build_world(self.dir)
        self.assertEqual([g["game_id"] for g in store.games_by_team()["KC"]],
                         ["2024_12_KC_BUF", "2025_01_BUF_KC", "2025_02_KC_SEA", "2025_03_SEA_KC", "2025_05_KC_ARI",
                          "2025_06_ARI_KC", "2025_08_BUF_KC"])
        self.assertEqual(store.team_game_by_key()[("2025_01_BUF_KC", "KC")]["points_for"], 27)
        self.assertEqual([r["game_id"] for r in store.player_games_by_player()["00-MOVER1"]],
                         ["2025_01_BUF_KC", "2025_02_ARI_BUF", "2025_04_SEA_BUF", "2025_05_BUF_SEA"])
        self.assertEqual(store.player_names()["00-KCWR1"], "Kay See")
        self.assertEqual(sorted(store.injury_weeks()), [(2025, 5), (2025, 6)])
        self.assertEqual(len(store.injuries_by_game_team()[("2025_05_KC_ARI", "KC")]), 4)
        self.assertEqual(store.seasons(), [2024, 2025])
        self.assertEqual({t: s for (t, y), s in store.home_stadiums().items() if y == 2025},
                         {"KC": "KAN00", "BUF": "BUF00", "SEA": "SEA00", "ARI": "PHO00"})
        starts = store.qb_starts()
        self.assertEqual([s[1] for s in starts["00-SEAQB2"]], ["2025_04_SEA_BUF", "2025_05_BUF_SEA"])
        self.assertNotIn("2025_08_BUF_KC", [s[1] for s in starts["00-KCQB1"]])               # only games already played

    def test_an_upsert_rebuilds_the_indexes_and_the_cache(self):
        store = W.build_world(self.dir)
        self.assertEqual(len(store.games_by_team()["KC"]), 7)
        extra = dict(W.world_rows()["games"][2], game_id="2025_09_BUF_KC", week=9)
        store.upsert("games", [extra])
        self.assertEqual(len(store.games_by_team()["KC"]), 8)
        self.assertEqual(len(store.games), 16)

    def test_position_groups(self):
        for position, group in (("QB", "QB"), ("FB", "RB"), ("HB", "RB"), ("WR", "WR"), ("TE", "TE"), ("T", "OL"), ("C", "OL"),
                                ("DE", "DL"), ("NT", "DL"), ("OLB", "LB"), ("CB", "DB"), ("SAF", "DB"), ("K", "ST"),
                                ("LS", "ST"), ("XYZ", "OTHER"), (None, "OTHER"), (" wr ", "WR")):
            self.assertEqual(position_group(position), group, position)
        self.assertEqual(position_group(None, "SPEC"), "ST")
        self.assertEqual(position_group("XYZ", "DB"), "DB")

    def test_rows_read_back_share_their_repeated_keys_and_short_values_but_are_equal_to_what_was_written(self):
        """json.loads copies every key and value of every line; sharing them took the four files from about
        103 MB of Python objects to about 31 MB. Sharing must change no value."""
        W.build_world(self.dir)
        store = NflStore(self.dir)
        rows = store.games
        self.assertEqual(rows, sorted(W.world_rows()["games"], key=lambda r: r["game_id"]))
        keys = [next(iter(r)) for r in rows]
        self.assertTrue(all(k is keys[0] for k in keys))                               # one "away_coach" for every row
        self.assertIs(rows[0]["home_team"], next(r["home_team"] for r in rows[1:] if r["home_team"] == rows[0]["home_team"]))
        self.assertIs(rows[0]["season"], next(r["season"] for r in rows[1:] if r["season"] == rows[0]["season"]))
        for row in store.team_games:                                                    # bools are bools, never the int 1
            self.assertIs(type(row["has_stats"]), bool)
        rows_with_true = [r for r in store.games if r["neutral_site"] is True]
        self.assertTrue(rows_with_true)
        self.assertEqual([r["overtime"] for r in store.games if r["overtime"] is not None and r["game_id"].endswith("BUF_SEA")], [True])
        self.assertEqual(NflStore(self.dir).load("games"), rows)

    def test_compact_leaves_long_and_unique_strings_floats_and_nulls_alone(self):
        from src.datasvc.nfl.store import compact
        long_text = "x" * 200
        rows = compact([{"a": long_text, "b": 1.5, "c": None, "d": True, "e": 1}, {"a": long_text, "b": 1.5, "c": None, "d": 1, "e": True}])
        self.assertEqual(rows[0], {"a": long_text, "b": 1.5, "c": None, "d": True, "e": 1})
        self.assertIs(rows[0]["d"], True)
        self.assertIs(type(rows[1]["d"]), int)                                         # an int 1 stays an int next to a True
        self.assertIs(rows[1]["e"], True)

    def test_content_ignores_only_the_fetch_time(self):
        self.assertEqual(content_of({"a": 1, "fetched_utc": "x"}), content_of({"a": 1, "fetched_utc": "y"}))
        self.assertNotEqual(content_of({"a": 1}), content_of({"a": 2}))


class TheBackfill(TempDirCase):
    def run_backfill(self, files=None, seasons=(2025, 2024), **kwargs):
        store = NflStore(self.dir)
        fetcher = kwargs.pop("fetcher", None) or FakeFetcher(files if files is not None else W.source_files())
        summary = pipeline.backfill(seasons, fetcher=fetcher, store=store, today=TODAY, log=QUIET, **kwargs)
        return NflStore(self.dir), summary, fetcher

    def test_it_rebuilds_the_world_exactly_from_the_source_files(self):
        store, summary, fetcher = self.run_backfill()
        world = W.world_rows()
        for name in ("games", "player_games", "injuries"):
            expected = sorted(world[name], key=lambda r: jsonl.key_of(r, KEYS[name]))
            self.assertEqual(store.load(name), expected, name)
        # team games carry the raw statistics too, so compare what the world sets
        got = {(r["game_id"], r["team"]): r for r in store.team_games}
        self.assertEqual(len(got), 30)
        for row in world["team_games"]:
            built = got[(row["game_id"], row["team"])]
            for field, value in row.items():
                if field != "source":
                    self.assertEqual(built[field], value, (row["game_id"], row["team"], field))
        self.assertEqual((summary["games"], summary["team_games"], summary["player_games"], summary["injuries"]),
                         (15, 30, 15, 8))
        self.assertEqual((summary["stopped"], summary["errors"], summary["missing_files"]), (None, [], []))

    def test_the_run_summary_accounts_for_every_source_row(self):
        _, summary, _ = self.run_backfill()
        per = summary["per_season"]["2025"]
        self.assertEqual(per["player_stats"], {"rows": 17, "kept": 15, "dropped_not_offense": 1, "dropped_no_player_id": 1})
        self.assertEqual(per["injuries"], {"rows": 9, "kept": 8, "dropped_full_participation_only": 1})
        self.assertEqual(per["team_stats_rows"], 22)                      # 11 final games in 2025, two rows each
        self.assertEqual(per["team_stats_unmatched"], [])
        self.assertEqual(summary["schedule"]["venue_check"], {"nominal_home_stadium_on_neutral_site": 1})

    def test_the_manifest_records_the_run_the_sources_and_the_coverage(self):
        store, _, _ = self.run_backfill()
        manifest = json.loads((self.dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["coverage"]["seasons"], [2024, 2025])
        self.assertEqual(manifest["coverage"]["player_games_seasons"], [2025])
        self.assertEqual(manifest["coverage"]["injuries_seasons"], [2025])
        self.assertEqual(manifest["last_run"]["kind"], "backfill")
        self.assertEqual(manifest["last_run_errors"], 0)
        self.assertEqual(manifest["sources"]["games"], sources.GAMES_URL)
        self.assertIn("{season}", manifest["sources"]["player_stats"])
        self.assertEqual(manifest["files"]["team_games.jsonl"]["records"], 30)
        self.assertEqual(manifest["files"]["games.jsonl"]["newest"], W.eastern("2025-10-19", "09:30"))

    def test_a_second_run_changes_nothing_not_even_a_modification_time(self):
        self.run_backfill()
        before = tree(self.dir)
        _, summary, _ = self.run_backfill()
        after = tree(self.dir)
        for name in ("games.jsonl", "team_games.jsonl", "player_games.jsonl", "injuries.jsonl"):
            self.assertEqual(after[name], before[name], name)
        self.assertEqual((summary["games"], summary["team_games"], summary["player_games"], summary["injuries"]), (0, 0, 0, 0))

    def test_a_run_that_hits_the_request_cap_keeps_what_it_finished_and_the_next_run_completes_it(self):
        store, summary, _ = self.run_backfill(fetcher=FakeFetcher(W.source_files(), cap=2))
        self.assertIn("request cap reached", summary["stopped"])
        self.assertEqual(len(store.games), 15)                              # the schedule came first
        self.assertEqual(len(store.team_games), 26)                         # then 2025's team statistics (13 games)
        self.assertEqual(len(store.player_games), 0)                        # and the cap hit on the player file
        manifest = json.loads((self.dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["files"]["games.jsonl"]["records"], 15)   # the manifest of a stopped run is true too
        self.assertIn("request cap reached", manifest["last_run"]["stopped"])
        done, summary2, _ = self.run_backfill()
        self.assertIsNone(summary2["stopped"])
        whole = Path(self._tmp.name) / "whole"
        reference = NflStore(whole)
        pipeline.backfill((2025, 2024), fetcher=FakeFetcher(W.source_files()), store=reference, today=TODAY, log=QUIET)
        for name in FILES:
            self.assertEqual(done.load(name), reference.load(name), name)

    def test_a_browser_check_stops_the_whole_run_at_once(self):
        store, summary, fetcher = self.run_backfill(fetcher=FakeFetcher(W.source_files(), blocked_after=1))
        self.assertTrue(summary["stopped"].startswith("source blocked"))
        self.assertEqual(fetcher.stats["requests"], 1)                      # nothing after the block was asked for
        self.assertEqual(len(store.player_games), 0)

    def test_a_season_the_schedule_does_not_have_fetches_nothing(self):
        store, summary, fetcher = self.run_backfill(seasons=(2025, 2023))
        self.assertIn("no games in the schedule", summary["per_season"]["2023"]["note"])
        self.assertFalse([u for u, _ in fetcher.calls if "2023" in u])

    def test_a_missing_statistics_file_is_recorded_and_the_games_still_get_their_rows(self):
        files = W.source_files()
        del files[sources.team_stats_url(2025)]
        store, summary, _ = self.run_backfill(files=files)
        self.assertEqual(summary["missing_files"], [sources.team_stats_url(2025)])
        rows = [r for r in store.team_games if r["season"] == 2025]
        self.assertEqual(len(rows), 26)
        self.assertFalse(any(r["has_stats"] for r in rows))
        self.assertEqual(pipeline.check(store)["checks"][3]["ok"], False)  # a final game without statistics is flagged

    def test_the_schedule_missing_stops_the_run_with_nothing_written(self):
        files = W.source_files()
        del files[sources.games_url()]
        store, summary, _ = self.run_backfill(files=files)
        self.assertEqual(summary["missing_files"], [sources.games_url()])
        self.assertEqual(store.games, [])

    def test_player_since_keeps_the_player_file_to_later_seasons_and_the_manifest_says_so(self):
        files = W.source_files()
        files[sources.player_stats_url(2024)] = W.player_stats_csv(2025).replace("2025_", "2024_")     # would be wrong if read
        store, summary, fetcher = self.run_backfill(files=files, player_since=2025)
        self.assertNotIn(sources.player_stats_url(2024), [u for u, _ in fetcher.calls])
        self.assertEqual(summary["per_season"]["2024"]["player_stats"], {"skipped": "before player_since 2025"})
        self.assertEqual({r["season"] for r in store.player_games}, {2025})
        manifest = json.loads((self.dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["coverage"]["player_games_since"], 2025)
        self.assertEqual(manifest["last_run"]["player_since"], 2025)
        # the other three datasets still cover both seasons
        self.assertEqual({g["season"] for g in store.games}, {2024, 2025})
        self.assertEqual({r["season"] for r in store.team_games}, {2024, 2025})

    def test_historical_files_are_cached_forever_and_recent_ones_may_be_refetched(self):
        _, _, fetcher = self.run_backfill(seasons=(2025, 2024, 2023))
        ages = {u.rsplit("/", 1)[-1]: age for u, age in fetcher.calls}
        self.assertEqual(ages["games.csv"], sources.LIVE_MAX_AGE_S)
        self.assertEqual(ages["stats_team_week_2025.csv"], sources.LIVE_MAX_AGE_S)
        self.assertEqual(ages["stats_team_week_2024.csv"], sources.LIVE_MAX_AGE_S)     # TODAY is in the 2025 season: 2024 is "last season"
        later = FakeFetcher(W.source_files())
        pipeline.backfill((2024,), fetcher=later, store=NflStore(self.dir), today=date(2027, 10, 1), log=QUIET)
        ages_later = {u.rsplit("/", 1)[-1]: age for u, age in later.calls}
        self.assertIsNone(ages_later["stats_team_week_2024.csv"])                     # two seasons back: never refetched
        self.assertEqual(ages_later["games.csv"], sources.LIVE_MAX_AGE_S)


class TheDailyUpdate(TempDirCase):
    def setUp(self):
        super().setUp()
        self.files = W.source_files()
        pipeline.backfill((2025, 2024), fetcher=FakeFetcher(self.files, fetched_utc="2025-10-20T12:00:00Z"),
                          store=NflStore(self.dir), today=TODAY, log=QUIET)

    def update(self, files=None, fetched="2025-10-21T09:00:00Z", today=date(2025, 10, 21)):
        fetcher = FakeFetcher(files if files is not None else self.files, fetched_utc=fetched)
        summary = pipeline.update(today, fetcher=fetcher, store=NflStore(self.dir), log=QUIET)
        return NflStore(self.dir), summary, fetcher

    def test_an_update_with_nothing_new_writes_nothing(self):
        before = tree(self.dir)
        _, summary, _ = self.update()
        after = tree(self.dir)
        for name in ("games.jsonl", "team_games.jsonl", "player_games.jsonl", "injuries.jsonl"):
            self.assertEqual(after[name], before[name], name)
        self.assertEqual((summary["games"], summary["team_games"], summary["player_games"], summary["injuries"]), (0, 0, 0, 0))

    def test_it_asks_only_for_the_schedule_and_the_current_seasons_three_files(self):
        _, _, fetcher = self.update()
        self.assertEqual(sorted(u.rsplit("/", 1)[-1] for u, _ in fetcher.calls),
                         ["games.csv", "injuries_2025.csv", "stats_player_week_2025.csv", "stats_team_week_2025.csv"])
        self.assertTrue(all(age == sources.LIVE_MAX_AGE_S for _, age in fetcher.calls))

    def test_a_game_played_since_the_last_run_arrives_as_changed_rows_and_nothing_else_is_rewritten(self):
        files = dict(self.files)
        # week 8 was played: scores and statistics arrive
        files[sources.games_url()] = W.games_csv(**{"2025_08_BUF_KC": {"away_score": "17", "home_score": "24", "overtime": "0"}})
        stats = W.team_stats_csv(2025).splitlines()
        header = stats[0]
        extra = [",".join(["2025", "8", team, "REG", "2025_08_BUF_KC", opp, "10", "30", "250", "1", "1", "2", "14", "20", "100",
                           "1", "0", "5", "40", "10", "5", "1.0", "-0.5", "2", "0"])
                 for team, opp in (("BUF", "KC"), ("KC", "BUF"))]
        files[sources.team_stats_url(2025)] = "\n".join([header] + stats[1:] + extra) + "\n"
        before = {r["game_id"]: r for r in NflStore(self.dir).games}
        store, summary, _ = self.update(files=files, fetched="2025-10-27T09:00:00Z", today=date(2025, 10, 27))
        games = {g["game_id"]: g for g in store.games}
        self.assertEqual((games["2025_08_BUF_KC"]["status"], games["2025_08_BUF_KC"]["home_score"]), ("final", 24))
        self.assertEqual(games["2025_08_BUF_KC"]["fetched_utc"], "2025-10-27T09:00:00Z")
        # g15 was not played by then: it is no_result, a new status, so it is rewritten too (the schedule's own fact)
        self.assertEqual(games["2025_08_SEA_ARI"]["status"], "no_result")
        # every other game is exactly as it was, down to the fetch time
        for gid, row in before.items():
            if gid not in ("2025_08_BUF_KC", "2025_08_SEA_ARI"):
                self.assertEqual(games[gid], row, gid)
        rows = {(r["game_id"], r["team"]): r for r in store.team_games}
        self.assertEqual((rows[("2025_08_BUF_KC", "KC")]["result"], rows[("2025_08_BUF_KC", "KC")]["points_for"]), ("W", 24))
        self.assertTrue(rows[("2025_08_BUF_KC", "KC")]["has_stats"])
        self.assertEqual(rows[("2025_05_KC_ARI", "KC")]["fetched_utc"], "2025-10-20T12:00:00Z")      # untouched rows keep theirs
        self.assertEqual((summary["games"], summary["team_games"]), (2, 4))

    def test_a_game_that_vanished_from_the_schedule_is_marked_removed_never_deleted(self):
        games = [g for g in W._games() if g["game_id"] != "2025_08_SEA_ARI"]
        files = dict(self.files)
        files[sources.games_url()] = W.games_csv(games)
        store, summary, _ = self.update(files=files)
        by = {g["game_id"]: g for g in store.games}
        self.assertEqual(by["2025_08_SEA_ARI"]["status"], "removed")
        self.assertEqual({r["status"] for r in store.team_games if r["game_id"] == "2025_08_SEA_ARI"}, {"removed"})
        self.assertEqual(summary["schedule"]["removed"], ["2025_08_SEA_ARI"])
        self.assertEqual(len(store.games), 15)
        self.assertEqual(store.newest("games"), W.eastern("2025-10-19", "09:30"))            # a removed game never counts

    def test_a_schedule_that_is_not_a_schedule_changes_nothing_and_removes_nothing(self):
        """An error page, an empty body or another file must never be read as 'every game has vanished'."""
        before = tree(self.dir)
        for body in ("<html><body>Rate limit exceeded</body></html>", "", "a,b\n1,2\n"):
            files = dict(self.files)
            files[sources.games_url()] = body
            store, summary, fetcher = self.update(files=files)
            self.assertEqual({g["status"] for g in store.games} & {"removed"}, set(), repr(body))
            self.assertTrue(summary["errors"], repr(body))
            self.assertIn("not a schedule", summary["errors"][0])
            self.assertEqual(len(fetcher.calls), 1, "the other files are not fetched once the schedule is distrusted")
        after = tree(self.dir)
        for name in ("games.jsonl", "team_games.jsonl", "player_games.jsonl", "injuries.jsonl"):
            self.assertEqual(after[name], before[name], name)

    def test_unreadable_schedule_rows_stop_any_game_being_called_removed(self):
        games = [g for g in W._games() if g["game_id"] != "2025_08_SEA_ARI"]
        text = W.games_csv(games) + ",".join([""] * 46) + "\n"                           # a row with no game id
        files = dict(self.files)
        files[sources.games_url()] = text
        store, summary, _ = self.update(files=files)
        self.assertEqual({g["game_id"]: g["status"] for g in store.games}["2025_08_SEA_ARI"], "scheduled")
        self.assertIn("could not be read", summary["schedule"]["removal_skipped"])
        self.assertNotIn("removed", summary["schedule"])

    def test_statistics_the_store_holds_are_never_nulled_by_a_missing_empty_or_partial_file(self):
        before = {(r["game_id"], r["team"]): r for r in NflStore(self.dir).team_games}
        has_stats = [k for k, r in before.items() if r["has_stats"]]
        self.assertEqual(len(has_stats), 26)
        header = W.team_stats_csv(2025).splitlines()[0] + "\n"
        partial = "\n".join(W.team_stats_csv(2025).splitlines()[:7]) + "\n"              # three games' rows only
        for label, body in (("missing", None), ("empty", header), ("partial", partial)):
            files = dict(self.files)
            if body is None:
                del files[sources.team_stats_url(2025)]
            else:
                files[sources.team_stats_url(2025)] = body
            store, summary, _ = self.update(files=files)
            now = {(r["game_id"], r["team"]): r for r in store.team_games}
            for key in has_stats:
                self.assertEqual(now[key], before[key], (label, key))                   # exactly as before, fetch time included
            kept = summary["per_season"]["2025"].get("team_rows_kept_with_their_stored_statistics")
            self.assertEqual(kept, {"missing": 22, "empty": 22, "partial": 16}[label], label)    # 2025's 22 rows with statistics
        # and a complete file afterwards changes nothing either
        store, _, _ = self.update()
        self.assertEqual({(r["game_id"], r["team"]) for r in store.team_games if r["has_stats"]}, set(has_stats))

    def test_a_played_game_that_vanishes_stays_final(self):
        games = [g for g in W._games() if g["game_id"] != "2025_05_KC_ARI"]
        files = dict(self.files)
        files[sources.games_url()] = W.games_csv(games)
        store, summary, _ = self.update(files=files)
        self.assertEqual({g["game_id"]: g["status"] for g in store.games}["2025_05_KC_ARI"], "final")
        self.assertNotIn("removed", summary["schedule"])

    def test_the_players_since_setting_survives_an_update(self):
        other = Path(self._tmp.name) / "since"
        pipeline.backfill((2025, 2024), fetcher=FakeFetcher(self.files), store=NflStore(other), today=TODAY, log=QUIET,
                          player_since=2025)
        pipeline.update(TODAY, fetcher=FakeFetcher(self.files), store=NflStore(other), log=QUIET)
        manifest = json.loads((other / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["coverage"]["player_games_since"], 2025)
        self.assertEqual(manifest["last_run"]["kind"], "update")

    def test_the_off_season_has_no_stats_files_and_that_is_not_an_error(self):
        """The new season's schedule is out in the spring; its stats files are not until the first game."""
        files = dict(self.files)
        opener = dict(W._games()[-2], game_id="2026_01_BUF_KC", season=2026, week=1, gameday="2026-09-10")
        files[sources.games_url()] = W.games_csv(W._games() + [opener])
        store, summary, _ = self.update(files=files, today=date(2026, 9, 1))
        self.assertEqual({g["season"] for g in store.games}, {2024, 2025, 2026})
        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["missing_files"], [sources.team_stats_url(2026), sources.player_stats_url(2026),
                                                    sources.injuries_url(2026)])
        self.assertIsNone(summary["stopped"])


class TheCurrentSeason(unittest.TestCase):
    def test_march_to_february(self):
        self.assertEqual(pipeline.current_season(date(2026, 10, 3)), 2026)
        self.assertEqual(pipeline.current_season(date(2027, 1, 20)), 2026)
        self.assertEqual(pipeline.current_season(date(2027, 3, 1)), 2027)


class StatusAndChecks(TempDirCase):
    def test_status_lists_each_dataset_with_its_age_and_the_next_kickoff(self):
        store = W.build_world(self.dir)
        status = pipeline.status(store, now=datetime(2025, 10, 21, 13, 30, tzinfo=timezone.utc))
        self.assertEqual(status["games"]["records"], 15)
        self.assertEqual(status["games"]["newest"], "2025-10-19T13:30:00Z")
        self.assertEqual(status["games"]["age_hours"], 48.0)
        self.assertEqual(status["games"]["next_scheduled"], "2025-10-26T20:05:00Z")
        self.assertIsNone(status["injuries"]["next_scheduled"])

    def test_a_dataset_that_is_not_there_is_zero_records_not_an_error(self):
        status = pipeline.status(NflStore(self.dir))
        self.assertEqual(status["games"], {"records": 0, "newest": None, "age_hours": None, "next_scheduled": None})

    def test_the_checks_pass_on_a_store_the_backfill_built(self):
        store = NflStore(self.dir)
        pipeline.backfill((2025, 2024), fetcher=FakeFetcher(W.source_files()), store=store, today=TODAY, log=QUIET,
                          player_since=2025)
        report = pipeline.check(NflStore(self.dir))
        self.assertEqual([c for c in report["checks"] if not c["ok"]], [])
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["checks"]), 9)

    def test_a_season_with_played_games_and_no_player_rows_is_flagged_unless_the_manifest_says_it_was_left_out(self):
        store = NflStore(self.dir)
        pipeline.backfill((2025, 2024), fetcher=FakeFetcher(W.source_files()), store=store, today=TODAY, log=QUIET)
        by = {c["name"]: c for c in pipeline.check(NflStore(self.dir))["checks"]}
        name = "every season with played games (from player_games_since, when set) has player rows"
        self.assertFalse(by[name]["ok"])                                  # 2024 has games and no player rows
        self.assertIn("2024", by[name]["detail"])

    def build_and_check(self, damage):
        store = NflStore(self.dir)
        pipeline.backfill((2025, 2024), fetcher=FakeFetcher(W.source_files()), store=store, today=TODAY, log=QUIET,
                          player_since=2025)
        damage(NflStore(self.dir))
        report = pipeline.check(NflStore(self.dir))
        return report, {c["name"]: c["ok"] for c in report["checks"]}

    def test_a_missing_team_row_is_found(self):
        def damage(store):
            rows = [r for r in store.team_games if not (r["game_id"] == "2025_05_KC_ARI" and r["team"] == "ARI")]
            store.write("team_games", rows)
        report, by = self.build_and_check(damage)
        self.assertFalse(report["ok"])
        self.assertFalse(by["every game has exactly two team rows"])

    def test_a_final_game_with_no_statistics_is_found(self):
        def damage(store):
            store.upsert("team_games", [dict(r, has_stats=False) for r in store.team_games if r["game_id"] == "2025_05_KC_ARI"])
        _, by = self.build_and_check(damage)
        self.assertFalse(by["every final game has team statistics for both teams"])

    def test_turnover_margins_that_do_not_cancel_are_found(self):
        def damage(store):
            row = next(r for r in store.team_games if r["game_id"] == "2025_05_KC_ARI" and r["team"] == "KC")
            store.upsert("team_games", [dict(row, turnover_margin=row["turnover_margin"] + 1)])
        _, by = self.build_and_check(damage)
        self.assertFalse(by["a game's two turnover margins sum to zero"])

    def test_a_player_row_for_a_game_not_played_is_found(self):
        def damage(store):
            store.upsert("player_games", [dict(store.player_games[0], game_id="2025_08_BUF_KC")])
        _, by = self.build_and_check(damage)
        self.assertFalse(by["every player row belongs to a final game and one of its teams"])

    def test_an_injury_row_for_the_wrong_team_is_found(self):
        def damage(store):
            store.upsert("injuries", [dict(store.injuries[0], team="SEA")])
        _, by = self.build_and_check(damage)
        self.assertFalse(by["every injury row belongs to a game and one of its teams"])

    def test_a_file_edited_after_the_manifest_was_written_is_found(self):
        def damage(store):
            path = store.path("games")
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        _, by = self.build_and_check(damage)
        self.assertFalse(by["the manifest describes the files on disk"])


if __name__ == "__main__":
    unittest.main()
