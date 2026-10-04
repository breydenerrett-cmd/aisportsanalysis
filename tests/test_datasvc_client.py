"""src/datasvc/client.py: DataClient over the UFC and NFL stores, offline and injected.

FastAPI is not needed (the client is stdlib, which is the point: LineHound's own code can use it where
the Linux CI has no web framework). The stores are the synthetic worlds of the feature tests built in a
temporary directory; the clock is pinned; MLB is a recording stub here (its own tests are
tests/test_datasvc_mlb_service.py).

What is pinned:
  * every capability answers one of two shapes, and a capability with no usable data says why;
  * the client calls the SAME domain functions as the HTTP routes (the packet's `data` is
    `ufc.matchup.matchup` / `nfl.matchup.matchup` output, not a re-derivation);
  * the packet's `meta`: ids and provider ids, units, sources with their basis, coverage and stale
    flags, missing reasons and a `data_version` that is a hash of the files;
  * fifty repeated reads of an unchanged store open no file; a changed store invalidates, and a file
    that keeps changing during a build is "unavailable", never a mix of two versions.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.datasvc import client as core
from src.datasvc.client import DataClient, DataError
from src.datasvc.nfl import matchup as nfl_matchup
from src.datasvc.ufc import matchup as ufc_matchup
from tests import _nfl_world as W
from tests.test_datasvc_mlb_service import counting_opens
from tests.test_datasvc_nfl_features import G
from tests.test_datasvc_ufc_features import build_store

UFC_NOW = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
NFL_NOW = datetime(2025, 10, 20, 12, 0, tzinfo=timezone.utc)


class Recording:
    """Stands in for MlbService: records what the client forwards."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return {"available": True, "sport": "mlb", "kind": name, "data": {}, "meta": {}}
        return call


class Worlds(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.ufc_dir, self.nfl_dir = self.root / "ufc", self.root / "nfl"
        self.ufc_store = build_store(self.ufc_dir)
        self.ufc_store.write_manifest()
        self.nfl_store = W.build_world(self.nfl_dir)
        self.nfl_store.write_manifest(extra={"coverage": {"seasons": [2024, 2025]}})
        self.mlb = Recording()
        self.client = DataClient(ufc=self.ufc_dir, nfl=self.nfl_dir, mlb=self.mlb, clock=lambda: UFC_NOW)
        self.nfl_client = DataClient(ufc=self.ufc_dir, nfl=self.nfl_dir, mlb=self.mlb, clock=lambda: NFL_NOW)


def assert_unavailable(case, result, item=None):
    case.assertEqual(set(result), {"available", "missing"}, result)
    case.assertIs(result["available"], False)
    case.assertTrue(result["missing"])
    for entry in result["missing"]:
        case.assertTrue(entry["item"] and entry["reason"], entry)
    if item:
        case.assertIn(item, [m["item"] for m in result["missing"]])


class Capabilities(Worlds):
    NAMES = {"schedule", "game", "participants", "history", "features", "availability", "quotes", "matchup"}

    def test_every_sport_names_every_capability(self):
        for sport in ("ufc", "nfl", "mlb"):
            self.assertEqual(set(self.client.capabilities(sport)), self.NAMES, sport)

    def test_a_capability_a_sport_does_not_have_says_why_and_the_call_agrees(self):
        self.assertFalse(self.client.capabilities("ufc")["availability"]["available"])
        out = self.client.availability("ufc")
        assert_unavailable(self, out, "availability")
        self.assertIn("injury", out["missing"][0]["reason"])
        assert_unavailable(self, self.client.availability("mlb"), "availability")
        assert_unavailable(self, self.client.features("mlb", "x"), "features")
        for sport, caps in core.CAPABILITIES.items():
            for name, entry in caps.items():
                self.assertEqual("reason" in entry, not entry["available"], (sport, name))

    def test_an_unknown_sport_is_the_callers_mistake(self):
        with self.assertRaises(DataError) as ctx:
            self.client.schedule("curling")
        self.assertEqual(ctx.exception.status, 422)


class Ufc(Worlds):
    def test_schedule_filters_and_pages_like_the_route(self):
        out = self.client.schedule("ufc", year=2026, status="final", limit=2)
        self.assertTrue(out["available"])
        self.assertEqual(out["sport"], "ufc")
        self.assertEqual(out["page"]["count"], 2)
        self.assertTrue(out["page"]["next_cursor"])
        dates = [e["date_utc"] for e in out["data"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertTrue(all(e["status"] == "final" for e in out["data"]))
        nxt = self.client.schedule("ufc", year=2026, status="final", limit=2, cursor=out["page"]["next_cursor"])
        self.assertFalse({e["event_id"] for e in out["data"]} & {e["event_id"] for e in nxt["data"]})

    def test_upcoming_has_the_booked_card_with_current_odds(self):
        out = self.client.schedule("ufc", upcoming=True)
        self.assertEqual([e["event_id"] for e in out["data"]], ["7013"])
        main = out["data"][0]["bouts"][0]
        self.assertEqual(main["odds"]["moneyline"]["current"]["a"], -170)
        self.assertEqual(main["fighter_a"]["name"], "Alex Archer")

    def test_a_bad_filter_is_a_422_not_an_empty_answer(self):
        for kwargs in ({"status": "bogus"}, {"colour": "red"}):
            with self.assertRaises(DataError) as ctx:
                self.client.schedule("ufc", **kwargs)
            self.assertEqual(ctx.exception.status, 422)

    def test_game_event_and_bout(self):
        event = self.client.game("ufc", event_id="7013")
        self.assertEqual([b["bout_id"] for b in event["data"]["bouts"]], ["9101", "9102"])
        bout = self.client.game("ufc", bout_id="9101")
        self.assertEqual(bout["data"]["odds"][0]["a_ml_current"], -170)
        with self.assertRaises(DataError):
            self.client.game("ufc", event_id="7013", bout_id="9101")

    def test_an_unknown_id_is_unavailable_and_names_nobody(self):
        for out in (self.client.game("ufc", event_id="nope"), self.client.game("ufc", bout_id="nope"),
                    self.client.history("ufc", "nope"), self.client.features("ufc", "nope")):
            assert_unavailable(self, out, "lookup")
            self.assertNotIn("data", out)

    def test_participants_search_finds_one_and_reports_a_tie_with_its_candidates(self):
        found = self.client.participants("ufc", search="archer")
        self.assertEqual(found["data"]["match"]["fighter_id"], "101")
        tie = self.client.participants("ufc", search="silva")
        assert_unavailable(self, tie, "lookup")
        candidates = [m for m in tie["missing"] if m["item"] == "candidates"][0]["candidates"]
        self.assertEqual({c["fighter_id"] for c in candidates}, {"104", "105"})
        assert_unavailable(self, self.client.participants("ufc", search="zzzzzz"), "lookup")

    def test_history_is_newest_first_and_includes_the_booked_bout(self):
        out = self.client.history("ufc", "101")
        self.assertEqual(out["data"][0]["bout_id"], "9101")                 # the booked main event
        self.assertEqual(out["data"][0]["result"], None)                   # no result invented for it
        self.assertEqual([r["bout_id"] for r in out["data"][:4]], ["9101", "9011", "9013", "9009"])
        self.assertEqual(out["data"][2]["status"], "canceled")             # a cancelled bout is shown as one
        dates = [r["date_utc"] for r in out["data"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_features_are_as_of_and_leak_nothing_after(self):
        before = self.client.features("ufc", "101", as_of="2026-03-01")
        after = self.client.features("ufc", "101", as_of="2026-07-01")
        self.assertEqual(before["data"]["as_of"][:10], "2026-03-01")
        self.assertEqual(after["data"]["as_of"][:10], "2026-07-01")
        self.assertNotEqual(before["data"]["figures"], after["data"]["figures"])   # 9009 and 9011 happened between

    def test_quotes_are_the_bouts_odds_labelled_not_as_of_safe(self):
        out = self.client.quotes("ufc", bout_id="9101")
        self.assertEqual(out["data"]["odds"]["provider"], "DraftKings")
        self.assertFalse(out["data"]["odds"]["as_of_safe"])
        self.assertEqual(out["data"]["basis"], core.RECONSTRUCTED)
        assert_unavailable(self, self.client.quotes("ufc", bout_id="9102"), "lookup")   # no odds row for it

    def test_the_packet_is_the_matchup_sheet_the_route_serves(self):
        out = self.client.matchup("ufc", a="101", b="102")
        direct = ufc_matchup.matchup(self.ufc_store, "101", "102", None, now=UFC_NOW)
        direct["resolved"] = out["data"]["resolved"]
        self.assertEqual(out["data"], direct)

    def test_packet_meta_carries_ids_units_sources_basis_coverage_and_missing(self):
        out = self.client.matchup("ufc", a="archer", b="102")
        meta = out["meta"]
        self.assertEqual((meta["sport"], meta["kind"]), ("ufc", "matchup_packet"))
        self.assertEqual((meta["ids"]["fighter_a_id"], meta["ids"]["fighter_b_id"], meta["ids"]["bout_id"]),
                         ("101", "102", "9101"))
        self.assertEqual(meta["ids"]["provider_ids"]["espn"]["competition"], "9101")
        self.assertEqual(meta["ids"]["provider_ids"]["ufc_com_slug"]["a"], "alex-archer")
        self.assertEqual(meta["units"]["reach"], "inches")
        self.assertEqual(meta["datasets"]["odds"]["basis"], core.RECONSTRUCTED)
        self.assertEqual(meta["datasets"]["fighters"]["basis"], core.SINGLE_VALUE)
        self.assertIn("close", meta["datasets"]["odds"]["basis_note"])
        for dataset in meta["datasets"].values():
            self.assertTrue(dataset["source"] and dataset["basis"] and dataset["basis_note"])
            self.assertTrue(dataset["version"])
        self.assertEqual(meta["built_utc"], "2026-10-03T15:00:00Z")          # our clock, only for the build
        self.assertEqual(meta["observed_utc"], self.ufc_store_manifest()["generated_utc"])
        self.assertIsNone(meta["source_updated_utc"])
        self.assertTrue(meta["source_updated_utc_reason"])
        self.assertEqual(meta["missing"], [{"item": m.get("figure") or m.get("item"), **{
            k: v for k, v in m.items() if k not in ("figure", "item")}} for m in out["data"]["missing"]])
        self.assertTrue(meta["data_version"].startswith("dv1-"))

    def ufc_store_manifest(self):
        import json
        return json.loads((self.ufc_dir / "MANIFEST.json").read_text(encoding="utf-8"))

    def test_a_dataset_the_sheet_needs_but_cannot_read_makes_the_whole_packet_unavailable(self):
        (self.ufc_dir / "odds.jsonl").write_text("{not json}\n", encoding="utf-8")
        out = self.client.matchup("ufc", a="101", b="102")
        assert_unavailable(self, out, "odds")
        self.assertIn("could not be read", out["missing"][0]["reason"])


class Nfl(Worlds):
    def test_schedule_game_and_the_packet(self):
        out = self.nfl_client.schedule("nfl", season=2025, team="KC", status="final", limit=3)
        self.assertEqual(out["page"]["count"], 3)
        self.assertTrue(all("KC" in (g["home_team"], g["away_team"]) for g in out["data"]))
        game = self.nfl_client.game("nfl", game_id=G["g05"])
        self.assertEqual(len(game["data"]["team_games"]), 2)
        packet = self.nfl_client.matchup("nfl", game_id=G["g14"])
        direct = nfl_matchup.matchup(self.nfl_store, G["g14"], None, now=NFL_NOW)
        direct["resolved"] = packet["data"]["resolved"]
        self.assertEqual(packet["data"], direct)

    def test_participants_teams_roster_and_a_player_by_name(self):
        teams = self.nfl_client.participants("nfl")
        self.assertEqual([t["team"] for t in teams["data"]], ["ARI", "BUF", "KC", "SEA"])
        roster = self.nfl_client.participants("nfl", team="KC")
        self.assertIn("00-KCWR1", [p["player_id"] for p in roster["data"]["players"]])
        assert_unavailable(self, self.nfl_client.participants("nfl", search="zzzzzz"), "lookup")

    def test_history_and_availability(self):
        history = self.nfl_client.history("nfl", "00-KCWR1")
        self.assertTrue(history["data"])
        self.assertTrue(all(r["player_id"] == "00-KCWR1" for r in history["data"]))
        injuries = self.nfl_client.availability("nfl", team="KC")
        self.assertTrue(injuries["data"])
        self.assertTrue(all(r["team"] == "KC" for r in injuries["data"]))

    def test_closing_lines_are_one_value_per_game_and_say_so(self):
        out = self.nfl_client.quotes("nfl", game_id=G["g03"])               # final, with the schedule file's market
        self.assertEqual(out["data"]["status"], "final")
        self.assertFalse(out["data"]["market"]["as_of_safe"])
        self.assertEqual(out["data"]["basis"], core.SINGLE_VALUE)
        self.assertIn("ONE value per game", out["data"]["basis_note"])
        self.assertIn("Never an as-of-date price", out["data"]["market"]["note"])

    def test_a_game_with_no_market_is_unavailable_with_the_reason(self):
        out = self.nfl_client.quotes("nfl", game_id=G["g05"])               # no market in the schedule file
        assert_unavailable(self, out, "lookup")
        self.assertIn("no spread, total or moneyline", out["missing"][0]["reason"])

    def test_packet_meta_says_how_each_datasets_history_was_obtained(self):
        meta = self.nfl_client.matchup("nfl", game_id=G["g14"])["meta"]
        self.assertEqual(meta["datasets"]["games"]["basis"], core.SINGLE_VALUE)
        self.assertIn("ONE value per game", meta["datasets"]["games"]["basis_note"])
        self.assertIn("projection", meta["datasets"]["games"]["basis_note"])
        self.assertEqual(meta["datasets"]["team_games"]["basis"], core.RECONSTRUCTED)
        self.assertEqual(meta["datasets"]["injuries"]["basis"], core.OBSERVED)
        self.assertIn("nflverse", meta["attribution"])
        self.assertEqual(meta["ids"]["game_id"], G["g14"])
        self.assertEqual(meta["ids"]["provider_ids"]["nflverse"]["game_id"], G["g14"])
        self.assertEqual(meta["coverage"]["manifest"], {"seasons": [2024, 2025]})

    def test_a_team_pair_resolves_to_the_game_and_an_unknown_team_is_unavailable(self):
        out = self.nfl_client.matchup("nfl", a="Chiefs", b="Bills", season=2025, week=8)
        self.assertEqual(out["data"]["game"]["game_id"], G["g14"])
        assert_unavailable(self, self.nfl_client.matchup("nfl", a="Chiefs", b="Zorgons"), "lookup")


class EmptyAndStale(Worlds):
    def test_a_store_with_no_files_is_unavailable_naming_the_file(self):
        empty = DataClient(ufc=self.root / "nowhere", nfl=self.root / "nowhere2", mlb=self.mlb, clock=lambda: UFC_NOW)
        for out in (empty.schedule("ufc"), empty.schedule("nfl"), empty.matchup("ufc", a="1", b="2"),
                    empty.availability("nfl")):
            assert_unavailable(self, out)
            self.assertIn("absent", out["missing"][0]["reason"])

    def test_stale_datasets_are_flagged_with_their_age_and_the_limit(self):
        later = DataClient(ufc=self.ufc_dir, nfl=self.nfl_dir, mlb=self.mlb,
                           clock=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc))
        meta = later.matchup("ufc", a="101", b="102")["meta"]
        self.assertIn("events", meta["coverage"]["stale_datasets"])
        self.assertTrue(meta["datasets"]["events"]["stale"])
        self.assertGreater(meta["datasets"]["events"]["age_days"], meta["datasets"]["events"]["allowed_age_days"])
        # the newest finished card in the world is 2026-08-08: twelve days later it is within the 21 allowed
        soon = DataClient(ufc=self.ufc_dir, nfl=self.nfl_dir, mlb=self.mlb,
                          clock=lambda: datetime(2026, 8, 20, tzinfo=timezone.utc))
        fresh = soon.matchup("ufc", a="101", b="102")["meta"]
        self.assertEqual(fresh["coverage"]["stale_datasets"], [])
        self.assertFalse(fresh["datasets"]["events"]["stale"])

    def test_nfl_stale_flag_follows_the_clock_too(self):
        later = DataClient(ufc=self.ufc_dir, nfl=self.nfl_dir, mlb=self.mlb,
                           clock=lambda: datetime(2026, 6, 1, tzinfo=timezone.utc))
        meta = later.matchup("nfl", game_id=G["g14"])["meta"]
        self.assertIn("games", meta["coverage"]["stale_datasets"])
        self.assertFalse(self.nfl_client.matchup("nfl", game_id=G["g14"])["meta"]["coverage"]["stale_datasets"])

    def test_an_unreadable_dataset_is_unavailable_and_remembered_not_reparsed(self):
        (self.nfl_dir / "games.jsonl").write_text("{broken\n", encoding="utf-8")
        first = self.nfl_client.schedule("nfl")
        assert_unavailable(self, first, "games")
        with counting_opens() as opens:
            for _ in range(5):
                assert_unavailable(self, self.nfl_client.schedule("nfl"), "games")
        self.assertEqual(opens["n"], 0)


class Versions(Worlds):
    def test_data_version_is_a_hash_of_the_files_and_the_same_bytes_give_the_same_version(self):
        one = self.client.matchup("ufc", a="101", b="102")["meta"]
        copy = self.root / "ufc_copy"
        shutil.copytree(self.ufc_dir, copy)
        two = DataClient(ufc=copy, nfl=self.nfl_dir, mlb=self.mlb, clock=lambda: UFC_NOW).matchup(
            "ufc", a="101", b="102")["meta"]
        self.assertEqual(one["data_version"], two["data_version"])           # content-hashed via the manifest
        self.assertEqual({f["kind"] for f in self.client._holders["ufc"].snapshot().version["files"].values()
                          if f["kind"] != "absent"}, {"content_hash_from_manifest"})

    def test_without_a_manifest_the_version_is_per_machine_and_says_so(self):
        (self.ufc_dir / "MANIFEST.json").unlink()
        holder = self.client._holders["ufc"]
        holder.set_root(self.ufc_dir)
        kinds = {f["kind"] for f in holder.snapshot().version["files"].values() if f["kind"] != "absent"}
        self.assertEqual(kinds, {"size_and_mtime_on_this_machine"})

    def test_a_changed_file_changes_the_version_and_the_answer(self):
        before = self.client.matchup("ufc", a="101", b="102")
        self.ufc_store.upsert("fighters", [dict(self.ufc_store.load("fighters")[0], name="Alexander Archer",
                                                aliases=["alexander archer", "alex archer"], fetched_utc="2026-10-03T14:00:00Z")])
        self.ufc_store.write_manifest()
        after = self.client.matchup("ufc", a="101", b="102")
        self.assertNotEqual(before["meta"]["data_version"], after["meta"]["data_version"])
        self.assertEqual(before["data"]["a"]["name"], "Alex Archer")
        self.assertEqual(after["data"]["a"]["name"], "Alexander Archer")

    def test_fifty_reads_of_an_unchanged_store_open_no_file_and_reload_nothing(self):
        holder = self.client._holders["ufc"]
        warm = self.client.matchup("ufc", a="101", b="102")
        self.client.schedule("ufc")
        self.client.history("ufc", "101")
        reloads = holder.reloads
        with counting_opens() as opens:
            for _ in range(50):
                again = self.client.matchup("ufc", a="101", b="102")
                self.client.schedule("ufc", year=2026)
                self.client.history("ufc", "101", limit=5)
        self.assertEqual(opens["n"], 0, opens["paths"])
        self.assertEqual(holder.reloads, reloads)
        self.assertEqual(again["meta"]["data_version"], warm["meta"]["data_version"])
        self.assertEqual(again["data"], warm["data"])

    def test_a_version_bump_mid_sequence_gives_internally_consistent_packets(self):
        results = []
        for i in range(30):
            if i == 15:
                self.ufc_store.upsert("fighters", [dict(self.ufc_store.load("fighters")[0], name="Alexander Archer",
                                                        aliases=["alex archer"], fetched_utc="2026-10-03T14:00:00Z")])
                self.ufc_store.write_manifest()
            out = self.client.matchup("ufc", a="101", b="102")
            results.append((out["meta"]["data_version"], out["data"]["a"]["name"],
                            out["data"]["features"]["a"]["name"]))
        versions = {v for v, _, _ in results}
        self.assertEqual(len(versions), 2)
        for version in versions:
            self.assertEqual(len({(n1, n2) for v, n1, n2 in results if v == version}), 1)
        self.assertEqual({(n1, n2) for v, n1, n2 in results if v == results[0][0]}, {("Alex Archer", "Alex Archer")})
        self.assertEqual({(n1, n2) for v, n1, n2 in results if v == results[-1][0]},
                         {("Alexander Archer", "Alexander Archer")})

    def test_files_that_never_stop_changing_are_unavailable_never_a_mixed_packet(self):
        holder = self.client._holders["nfl"]
        ticks = []
        real = holder._file_signature

        def moving():
            ticks.append(1)
            (name, mtime, size), *rest = real()
            return ((name, (mtime or 0) + len(ticks), size), *rest)

        holder._file_signature = moving
        client = DataClient(ufc=self.ufc_dir, nfl=holder, mlb=self.mlb, clock=lambda: NFL_NOW)
        out = client.matchup("nfl", game_id=G["g14"])
        assert_unavailable(self, out, "snapshot")
        strict = DataClient(ufc=self.ufc_dir, nfl=holder, mlb=self.mlb, clock=lambda: NFL_NOW, strict=True)
        with self.assertRaises(DataError) as ctx:
            strict.matchup("nfl", game_id=G["g14"])
        self.assertEqual(ctx.exception.status, 503)


class Isolation(Worlds):
    def test_a_caller_that_edits_its_answer_does_not_edit_the_shared_store(self):
        out = self.nfl_client.game("nfl", game_id=G["g05"])
        out["data"]["game"]["home_team"] = "EDITED"
        out["data"]["team_games"].clear()
        again = self.nfl_client.game("nfl", game_id=G["g05"])
        self.assertNotEqual(again["data"]["game"]["home_team"], "EDITED")
        self.assertEqual(len(again["data"]["team_games"]), 2)
        listing = self.client.schedule("ufc")
        listing["data"][0]["name"] = "EDITED"
        self.assertNotEqual(self.client.schedule("ufc")["data"][0]["name"], "EDITED")


class MlbIsForwarded(Worlds):
    def test_the_mlb_capabilities_go_through_the_mlb_service_with_the_clients_clock(self):
        self.client.schedule("mlb", date="2026-10-03")
        self.client.matchup("mlb", date="2026-10-03", away="NYY", home="TB", built_at="2026-10-03T18:00:00Z")
        self.client.quotes("mlb", date="2026-10-03", away="NYY", home="TB")
        self.client.history("mlb", "543037")
        names = [c[0] for c in self.mlb.calls]
        self.assertEqual(names, ["games", "packet", "quotes", "pitcher_history"])
        self.assertEqual(self.mlb.calls[1][2]["built_at"], "2026-10-03T18:00:00Z")
        self.assertEqual(self.mlb.calls[1][2]["now"], UFC_NOW)


if __name__ == "__main__":
    unittest.main()
