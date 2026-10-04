"""The refresh that keeps the request-time stores current (2026-10-03).

Everything here runs against a temp data root and a fake of the MLB Stats API
installed at the single network seam (tests/_fake_statsapi.py). No network, no
sleeping, no repo data touched.

WHAT IS PINNED, AND WHY EACH IS WORTH PINNING
---------------------------------------------
  - a stale committed copy comes out current, postseason included
  - the postseason is STORED but never becomes a TRAINING row (the reason the
    default ingest scope is regular-season-only)
  - a failure of any kind leaves the committed copy exactly as it was: API
    down, a step that raises, a copy that shrank
  - yesterday's bullpen rows are replaced, not duplicated (a late game)
  - standings are not requested for dates after the regular season
  - the work directory never survives, and nothing outside historical/ is read
    or written (watch/processed/evidence are sentinel-checked)
  - the container guard only runs a refresh when a core store is stale, never
    twice inside the minimum gap, and is OFF unless asked for
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import (bullpen, display_refresh as dr, features, history, lineups,
                          pitchers, standings, store_freshness as sf)
from src.providers import mlb, mlb_news, statcast
from tests._fake_statsapi import FakeStatsApi, raw_game

NOW = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)   # 12:00 Eastern, 2026-10-03
TODAY, YESTERDAY = "2026-10-03", "2026-10-02"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): _sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def _schedule() -> dict:
    return {
        "2026-09-22": [raw_game(1, "2026-09-22", "NYY", "BOS", 3, 2, "R", away_sp=111, home_sp=222)],
        "2026-09-23": [raw_game(2, "2026-09-23", "SD", "LAD", 1, 5, "R", away_sp=333, home_sp=444)],
        "2026-09-25": [raw_game(3, "2026-09-25", "NYY", "BOS", 4, 1, "R", away_sp=111, home_sp=222)],
        "2026-09-27": [raw_game(4, "2026-09-27", "LAD", "SD", 2, 0, "R", away_sp=222, home_sp=333)],
        "2026-09-29": [raw_game(11, "2026-09-29", "NYY", "BOS", 3, 1, "F", away_sp=111, home_sp=222)],
        "2026-09-30": [raw_game(12, "2026-09-30", "NYY", "BOS", 2, 5, "F", away_sp=222, home_sp=111)],
        "2026-10-01": [raw_game(13, "2026-10-01", "NYY", "BOS", 6, 2, "F", away_sp=111, home_sp=222)],
        # today: not played yet
        "2026-10-03": [raw_game(21, "2026-10-03", "ATL", "PHI", None, None, "D", final=False,
                                away_sp=111, home_sp=222)],
    }


def _game_logs() -> dict:
    return {
        111: [{"date": "2026-09-22", "gameType": "R"}, {"date": "2026-09-25", "gameType": "R"},
              {"date": "2026-09-29", "gameType": "F"}],
        222: [{"date": "2026-09-26", "gameType": "R"}, {"date": "2026-09-30", "gameType": "F"}],
        333: [{"date": "2026-09-23", "gameType": "R"}],
        444: [],
    }


def _fake(**overrides) -> FakeStatsApi:
    regular_season = [(datetime(2026, 9, 9) + timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(0, 19)]                     # 09-09 .. 09-27
    args = dict(schedule=_schedule(), game_logs=_game_logs(), standings_dates=regular_season)
    args.update(overrides)
    return FakeStatsApi(**args)


def seed_root(root: Path) -> Path:
    """A STALE committed copy, shaped like the repo's on 2026-10-03."""
    hist = root / "historical"
    hist.mkdir(parents=True)
    columns = history.RESULT_COLUMNS

    def row(pk, date, away, home, a, h, gtype):
        values = dict(game_pk=str(pk), date=date, game_type=gtype, away_team=away, home_team=home,
                      away_score=str(a), home_score=str(h), winner=away if a > h else home,
                      home_won="1" if h > a else "0", total_runs=str(a + h),
                      run_differential=str(abs(a - h)), away_probable_id="111",
                      home_probable_id="222")
        return {c: values.get(c) for c in columns}

    store = {"1": row(1, "2026-09-22", "NYY", "BOS", 3, 2, "R"),
             "2": row(2, "2026-09-23", "SD", "LAD", 1, 5, "R"),
             "900": row(900, "2025-10-05", "NYY", "BOS", 4, 3, "D")}   # a backfilled 2025 postseason game
    history.write_results(store, hist / "mlb_results.csv")
    entry = {"total": 1, "final": 1, "pending": 0, "cancelled": 0, "stored": 1, "skipped_game_type": 0}
    history.write_manifest({"2026-09-22": entry, "2026-09-23": entry}, hist / "mlb_results.manifest.json")

    pitchers.write_logs({
        "111": [{"person_id": 111, "date": "2026-09-07", "season": "2026", "games_started": 1,
                 "innings_pitched": 6.0, "earned_runs": 2, "runs": 2, "hits": 5, "walks": 1,
                 "strikeouts": 6, "home_runs": 1, "batters_faced": 24, "pitches": 90},
                {"person_id": 111, "season": "2026", "date": None, "empty": False,
                 "checked_utc": "2026-09-07T10:00:00+00:00"}]}, hist / "pitcher_logs.jsonl")
    (hist / "bullpen_log.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in [
            {"date": "2026-09-05", "game_pk": 5, "team": "NYY", "person_id": 77, "name": "Old Arm",
             "started": False, "innings": 1.0, "pitches": 12},
            {"date": "2026-09-06", "empty": True}]) + "\n", encoding="utf-8")
    (hist / "standings.jsonl").write_text(json.dumps(
        {"date": "2026-09-08", "season": "2026", "team_abbrev": "NYY", "team_id": 147,
         "captured_at": "2026-09-08T20:00:00+00:00", "wins": 80, "losses": 60}) + "\n", encoding="utf-8")
    (hist / "lineups.jsonl").write_text(json.dumps(
        {"date": YESTERDAY, "game_pk": 13, "observed_utc": "2026-10-02T20:00:00+00:00",
         "away": [{"person_id": 5001, "order": 1, "name": "A", "position": "CF"}],
         "home": [{"person_id": 5002, "order": 1, "name": "B", "position": "SS"}]}) + "\n",
        encoding="utf-8")
    (hist / "handedness.json").write_text("{}", encoding="utf-8")
    (hist / "pitcher_splits.json").write_text("{}", encoding="utf-8")
    (hist / "transactions.jsonl").write_text(json.dumps(
        {"transaction_id": 1, "date": "2026-09-08", "filed_date": "2026-09-08"}) + "\n", encoding="utf-8")
    (hist / "arsenals").mkdir()
    for side in ("pitcher", "batter"):
        (hist / "arsenals" / f"{side}_2026.json").write_text(json.dumps(
            {"as_of": "2026-09-08T20:00:00+00:00", "season": "2026", "side": side,
             "rows": [{"player_id": 1}]}), encoding="utf-8")

    # Sentinels in the trees this module must never open.
    for sub in ("watch", "processed"):
        (root / sub).mkdir()
        (root / sub / "sentinel.jsonl").write_text('{"k": 1}\n', encoding="utf-8")
    return root


class Base(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = seed_root(Path(self._tmp.name))
        self.hist = self.root / "historical"
        sf.reset_cache_for_tests()
        self.fake = _fake()
        patches = [
            mock.patch.object(mlb, "_get_json", self.fake),
            mock.patch.object(statcast, "fetch_arsenal",
                              side_effect=lambda season, side="pitcher", **kw: [{"player_id": 1}, {"player_id": 2}]),
            mock.patch.object(mlb_news, "fetch", side_effect=lambda start, end=None, **kw: [
                {"transaction_id": 2, "date": "2026-10-01", "filed_date": "2026-10-01",
                 "category": "IL", "team": "NYY", "player": "X"}]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        self.log = []

    def run_refresh(self, **kw):
        kw.setdefault("now", NOW)
        kw.setdefault("clock", lambda: 0.0)
        kw.setdefault("log", self.log.append)
        return dr.refresh(self.root, **kw)

    def freshness(self):
        sf.reset_cache_for_tests()
        return sf.report(self.root, NOW)


class TheStaleCopyComesOutCurrent(Base):

    def test_every_core_store_is_stale_before_and_current_after(self):
        before = self.freshness()
        self.assertEqual(set(before["core_stale"]),
                         {"mlb_results", "pitcher_logs", "bullpen_log", "standings"})
        report = self.run_refresh()
        self.assertIsNone(report["skipped_reason"])
        after = self.freshness()
        self.assertEqual(after["core_stale"], [], after["stores"])
        for name in ("results", "bullpen", "pitchers", "standings"):
            self.assertEqual(report["steps"][name]["status"], "ok", report["steps"][name])

    def test_results_hold_the_postseason_and_say_so_in_the_manifest(self):
        self.run_refresh()
        store = history.read_results(self.hist / "mlb_results.csv")
        types = {r["game_pk"]: r["game_type"] for r in store.values()}
        self.assertEqual(types["11"], "F")
        self.assertEqual(types["13"], "F")
        self.assertEqual(types["4"], "R")
        manifest = history.read_manifest(self.hist / "mlb_results.manifest.json")
        self.assertEqual(manifest["2026-10-01"]["game_types"], sorted(mlb.DECISIVE_GAME_TYPES))
        # today is still being played: fetched, but NOT yet counted as covered
        self.assertEqual(manifest[TODAY]["pending"], 1)
        self.assertEqual(sf.report(self.root, NOW)["stores"]["mlb_results"]["through"], YESTERDAY)

    def test_the_postseason_never_becomes_a_training_row(self):
        """THE RULE. The store gains postseason games; the training table must
        not. A 2025 postseason game was already in the seed, and the new 2026
        wild-card games arrive on top of it."""
        self.run_refresh()
        store = history.read_results(self.hist / "mlb_results.csv")
        stored_types = {r["game_type"] for r in store.values()}
        self.assertEqual(stored_types, {"R", "F", "D"})
        table = features.build_training_table(store, require_complete=False)
        self.assertEqual({store[str(r["game_pk"])]["game_type"] for r in table["rows"]}, {"R"})
        self.assertEqual(table["skipped"]["not_training_game_type"], 4)  # pk 900, 11, 12, 13
        # and opting in is explicit, never a side effect
        everything = features.build_training_table(store, require_complete=False, game_types=None)
        self.assertEqual(everything["count"], table["count"] + 4)

    def test_postseason_pitcher_starts_are_stored_once_and_tagged(self):
        self.run_refresh()
        logs = pitchers.read_logs(self.hist / "pitcher_logs.jsonl")
        rows = [a for a in logs["111"] if a.get("date")]
        post = [a for a in rows if a["date"] == "2026-09-29"]
        self.assertEqual(len(post), 1, "the API's aggregate 'P' type must not double a start")
        self.assertEqual(post[0]["game_type"], "F")
        gameplay = [c for c in self.fake.calls if c[0] == "people/111/stats"
                    and c[1].get("stats") == "gameLog"]
        self.assertTrue(gameplay)
        for _, params in gameplay:
            self.assertNotIn("P", params["gameType"].split(","))

    def test_the_fip_constant_ignores_postseason_appearances(self):
        regular = {"1": [{"person_id": 1, "date": "2026-06-01", "season": "2026",
                          "innings_pitched": 600.0, "earned_runs": 270, "home_runs": 70,
                          "walks": 200, "strikeouts": 600}]}
        with_post = {"1": regular["1"] + [{"person_id": 1, "date": "2026-10-01", "season": "2026",
                                           "game_type": "D", "innings_pitched": 400.0,
                                           "earned_runs": 20, "home_runs": 1, "walks": 1,
                                           "strikeouts": 900}]}
        self.assertEqual(pitchers.league_fip_constant(regular, "2026-12-01"),
                         pitchers.league_fip_constant(with_post, "2026-12-01"))

    def test_bullpen_covers_the_postseason_through_yesterday(self):
        self.run_refresh()
        rows = bullpen.read_log(self.hist / "bullpen_log.jsonl")
        by_date = {}
        for r in rows:
            by_date.setdefault(r["date"], []).append(r)
        self.assertIn("2026-09-29", by_date)          # a wild-card game
        self.assertTrue(any(not r.get("empty") for r in by_date["2026-09-29"]))
        self.assertIn(YESTERDAY, by_date)
        self.assertNotIn(TODAY, by_date)
        # the old row survives untouched
        self.assertEqual(by_date["2026-09-05"][0]["name"], "Old Arm")

    def test_standings_stop_at_the_last_regular_season_date(self):
        self.run_refresh()
        asked = sorted(p["date"] for path, p in self.fake.calls if path == "standings")
        self.assertTrue(asked)
        self.assertLessEqual(max(asked), "2026-09-27")
        self.assertEqual(sf.report(self.root, NOW)["stores"]["standings"]["through"], "2026-09-27")

    def test_splits_handedness_arsenals_and_transactions_are_topped_up(self):
        report = self.run_refresh()
        splits = json.loads((self.hist / "pitcher_splits.json").read_text(encoding="utf-8"))
        self.assertEqual(set(splits), {"111:2026", "222:2026"})
        hands = json.loads((self.hist / "handedness.json").read_text(encoding="utf-8"))
        self.assertEqual(set(hands), {"5001", "5002"})
        arsenal = json.loads((self.hist / "arsenals" / "pitcher_2026.json").read_text(encoding="utf-8"))
        self.assertTrue(arsenal["as_of"].startswith(datetime.now(timezone.utc).strftime("%Y")))
        self.assertEqual(len(arsenal["rows"]), 2)
        self.assertEqual(report["steps"]["transactions"]["written"], 1)

    def test_a_second_run_changes_nothing_that_is_covered(self):
        self.run_refresh()
        first = _tree(self.hist)
        calls_after_first = len(self.fake.calls)
        self.run_refresh()
        second = _tree(self.hist)
        # results/standings/bullpen/lineups are byte-identical; only stores that
        # are season-to-date by nature (pitcher markers, splits, arsenals,
        # handedness stamps) are allowed to be re-stamped.
        for name in ("mlb_results.csv", "standings.jsonl", "lineups.jsonl", "matchup_history.jsonl"):
            if name in first:
                self.assertEqual(first[name], second[name], name)
        self.assertGreater(calls_after_first, 0)


class NeverAWorseStoreThanTheOneItStartedWith(Base):

    def test_an_unreachable_api_leaves_every_byte_alone(self):
        before = _tree(self.root)
        self.fake.reachable = False
        report = self.run_refresh()
        self.assertIn("unreachable", report["skipped_reason"])
        self.assertEqual(before, _tree(self.root))
        self.assertFalse((self.root / ".refresh_work").exists())
        # and it cost one probe, not the budget
        self.assertEqual(len(self.fake.calls), 1)

    def test_a_step_that_raises_keeps_its_committed_copy_and_the_rest_still_run(self):
        original = _sha(self.hist / "mlb_results.csv")
        with mock.patch.object(history, "ingest_range", side_effect=RuntimeError("disk on fire")):
            report = self.run_refresh()
        self.assertEqual(report["steps"]["results"]["status"], "failed")
        self.assertIn("disk on fire", report["steps"]["results"]["error"])
        self.assertEqual(_sha(self.hist / "mlb_results.csv"), original)
        self.assertEqual(report["steps"]["standings"]["status"], "ok")
        self.assertFalse((self.root / ".refresh_work").exists())

    def test_a_season_the_api_answers_with_nothing_is_never_replaced_by_an_empty_marker(self):
        """An API hiccup that answers every game log with nothing would replace
        a starter's whole season with an empty marker. The committed season
        wins. (Until 2026-10-03 the whole copy was refused when the TOTAL
        shrank; that let a loss through whenever other pitchers grew the total,
        see tests/test_display_refresh_keys.py. Now the key keeps its records
        and the rest of the copy is promoted.)"""
        # 111 is tonight's announced starter, so he WILL be re-fetched; he has a
        # real season on file, so an empty answer would be a visible loss.
        season = [{"person_id": 111, "date": f"2026-{m:02d}-{d:02d}", "season": "2026",
                   "games_started": 1, "innings_pitched": 5.0, "earned_runs": 1}
                  for m in range(4, 10) for d in range(1, 29)]
        pitchers.write_logs({"111": season}, self.hist / "pitcher_logs.jsonl")
        self.fake.game_logs = {}          # every log now comes back empty
        report = self.run_refresh(only=["pitchers"])
        self.assertEqual(report["steps"]["pitchers"]["fetched"], 2)       # it did try
        stored = pitchers.read_logs(self.hist / "pitcher_logs.jsonl")
        self.assertEqual([a["date"] for a in stored["111"] if a.get("date")],
                         [a["date"] for a in season])
        self.assertEqual([r["keys"] for r in report["restored"]], [1])
        self.assertEqual(report["restored"][0]["rows"], len(season))

    def test_promote_refuses_a_shrunk_or_unparseable_copy_directly(self):
        work, dest = self.root / "w.jsonl", self.hist / "bullpen_log.jsonl"
        full = dest.read_text(encoding="utf-8")
        work.write_text(full.splitlines()[0] + "\n", encoding="utf-8")        # one row fewer
        result = dr._promote(work, dest, "strict")
        self.assertFalse(result["promoted"])
        self.assertIn("fewer rows", result["reason"])
        self.assertEqual(dest.read_text(encoding="utf-8"), full)

        bad = self.root / "w.json"
        bad.write_text("{not json", encoding="utf-8")
        result = dr._promote(bad, self.hist / "handedness.json", "strict")
        self.assertFalse(result["promoted"])
        self.assertIn("does not parse", result["reason"])

        grown = self.root / "g.jsonl"
        grown.write_text(full + json.dumps({"date": "2026-09-07", "empty": True}) + "\n", encoding="utf-8")
        self.assertTrue(dr._promote(grown, dest, "strict")["promoted"])

    def test_only_historical_is_written_and_no_work_directory_survives(self):
        sentinels = {k: v for k, v in _tree(self.root).items()
                     if k.startswith(("watch", "processed"))}
        self.run_refresh()
        after = _tree(self.root)
        self.assertEqual(sentinels, {k: v for k, v in after.items()
                                     if k.startswith(("watch", "processed"))})
        self.assertFalse((self.root / ".refresh_work").exists())
        # `raw/` (git-ignored, reproducible) holds the fetch layer's cache of
        # answers that can never change again (src/pipeline/refresh_fetch.py);
        # nothing else under it, and nothing outside it besides historical.
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ["historical", "processed", "raw", "watch"])
        self.assertEqual([p.name for p in (self.root / "raw").iterdir()], ["mlb_statsapi_cache"])
        leftovers = [p for p in self.hist.rglob("*") if p.name.endswith((".tmp", ".refresh.tmp"))]
        self.assertEqual(leftovers, [])

    def test_a_deadline_promotes_the_progress_made_and_resumes_next_time(self):
        ticks = {"n": 0}

        def clock():                # every look at the clock costs 40 "seconds"
            ticks["n"] += 1
            return ticks["n"] * 40.0

        report = self.run_refresh(max_seconds=270.0, clock=clock)
        self.assertIsNone(report["skipped_reason"])
        # whatever finished is promoted and sound; whatever did not is simply kept
        statuses = {name: step["status"] for name, step in report["steps"].items()}
        self.assertTrue(set(statuses.values()) <= {"ok", "skipped", "failed"}, statuses)
        self.assertFalse((self.root / ".refresh_work").exists())
        for name in ("mlb_results.csv", "pitcher_logs.jsonl", "bullpen_log.jsonl"):
            self.assertIsNone(dr._validate(self.hist / name), name)
        # an unhurried second run finishes the job
        self.run_refresh()
        self.assertEqual(self.freshness()["core_stale"], [])


class YesterdayIsRefetchedWhole(Base):

    def test_a_game_that_was_in_progress_at_the_last_fetch_is_not_lost_or_doubled(self):
        # The log holds ONE of yesterday's rows (the fetch near midnight saw one
        # game finished). Yesterday has two finals now, and the one the log had
        # is the same game (pk 31): the row is REPLACED by the final one, not
        # kept beside it. (It used to name a game, pk 13, that the feed no
        # longer lists for that date; a committed record the re-fetch does not
        # return is kept since 2026-10-03, see tests/test_display_refresh_keys.py.)
        partial = {"date": YESTERDAY, "game_pk": 31, "team": "NYY", "person_id": 9031,
                   "name": "Late Arm", "started": False, "innings": 1.0, "pitches": 15}
        with (self.hist / "bullpen_log.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(partial, sort_keys=True) + "\n")
        self.fake.schedule[YESTERDAY] = [
            raw_game(31, YESTERDAY, "NYY", "BOS", 3, 1, "D"),
            raw_game(32, YESTERDAY, "LAD", "SD", 2, 1, "D")]
        self.run_refresh(only=["bullpen"])
        rows = [r for r in bullpen.read_log(self.hist / "bullpen_log.jsonl") if r["date"] == YESTERDAY]
        self.assertEqual(sorted({r["game_pk"] for r in rows}), [31, 32])
        self.assertNotIn("Late Arm", {r.get("name") for r in rows})
        self.assertEqual(len(rows), len({(r["game_pk"], r["person_id"]) for r in rows}), "duplicated rows")


class TheReportStaysHonestAboutWhatItDidNotDo(Base):

    def test_unknown_steps_are_refused_by_the_cli(self):
        self.assertEqual(dr.main(["--root", str(self.root), "--only", "nope"]), 2)

    def test_check_mode_fetches_nothing(self):
        with mock.patch("builtins.print") as printed:
            self.assertEqual(dr.main(["--root", str(self.root), "--check"]), 0)
        self.assertEqual(self.fake.calls, [])
        payload = json.loads(printed.call_args[0][0])
        self.assertIn("mlb_results", payload["core_stale"])


class TheContainerGuard(unittest.TestCase):

    def test_off_unless_an_interval_is_configured(self):
        self.assertEqual(dr.guard_interval_seconds({}), 0.0)
        self.assertEqual(dr.guard_interval_seconds({dr.ENV_GUARD_INTERVAL: "garbage"}), 0.0)
        self.assertEqual(dr.guard_interval_seconds({dr.ENV_GUARD_INTERVAL: "3600"}), 3600.0)
        self.assertIsNone(dr.start_background_guard(env={}))

    def test_a_tick_runs_a_refresh_only_when_a_core_store_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = seed_root(Path(tmp))
            sf.reset_cache_for_tests()
            calls = []
            decision = dr.guard_tick(now=NOW, root=root, child=lambda r: calls.append(r) or {"exit": 0, "result": "ok"})
            self.assertTrue(decision["ran"])
            self.assertIn("mlb_results", decision["core_stale"])
            self.assertEqual(len(calls), 1)

    def test_a_tick_waits_out_the_minimum_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = seed_root(Path(tmp))
            sf.reset_cache_for_tests()
            calls = []
            decision = dr.guard_tick(now=NOW, root=root, last_run_at=1000.0, clock=lambda: 1000.0 + 60,
                                     child=lambda r: calls.append(r) or {})
            self.assertFalse(decision["ran"])
            self.assertEqual(calls, [])
            later = dr.guard_tick(now=NOW, root=root, last_run_at=1000.0,
                                  clock=lambda: 1000.0 + dr.GUARD_MIN_GAP_S + 1,
                                  child=lambda r: calls.append(r) or {"exit": 0, "result": "ok"})
            self.assertTrue(later["ran"])

    def test_a_current_store_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = seed_root(Path(tmp))
            hist = root / "historical"
            # make every core store current
            day = "2026-10-02"
            history.write_manifest({day: {"total": 0, "final": 0, "pending": 0, "cancelled": 0}},
                                   hist / "mlb_results.manifest.json")
            (hist / "bullpen_log.jsonl").write_text(json.dumps({"date": day, "empty": True}) + "\n", encoding="utf-8")
            (hist / "standings.jsonl").write_text(json.dumps({"date": day, "team_abbrev": "NYY"}) + "\n", encoding="utf-8")
            (hist / "pitcher_logs.jsonl").write_text(json.dumps(
                {"person_id": 1, "season": "2026", "date": None, "empty": True,
                 "checked_utc": "2026-10-03T10:00:00+00:00"}) + "\n", encoding="utf-8")
            sf.reset_cache_for_tests()
            calls = []
            decision = dr.guard_tick(now=NOW, root=root, child=lambda r: calls.append(r) or {})
            self.assertFalse(decision["ran"], decision)
            self.assertEqual(calls, [])

    def test_the_child_command_is_capped_and_bounded(self):
        seen = {}

        def runner(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return mock.Mock(returncode=0, stdout="display refresh: through x\n")

        out = dr._run_child("/tmp/data", runner=runner)
        self.assertEqual(out["exit"], 0)
        self.assertIn("--max-memory-mb", seen["cmd"])
        self.assertIn("--max-seconds", seen["cmd"])
        self.assertGreater(seen["kw"]["timeout"], dr.GUARD_CHILD_SECONDS)

    def test_a_hung_child_is_reported_not_raised(self):
        import subprocess

        def runner(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)

        self.assertIn("killed", dr._run_child(None, runner=runner)["result"])


if __name__ == "__main__":
    unittest.main()
