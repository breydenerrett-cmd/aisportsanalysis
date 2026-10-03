"""No key may lose a record when a refreshed copy is promoted (2026-10-03,
review item 3).

THE DEFECT. "The copy has not shrunk" compared TOTALS. An empty answer from the
API for ONE pitcher replaces his whole season with an empty marker
(`pitchers.build_log_store` replaces every row a successful fetch covers), and
the store still grows overall because other pitchers gained rows, so the copy
was promoted and his season was gone. The bullpen and standings steps re-fetch
yesterday whole and have the same shape for a date.

THE RULE. A copy is checked KEY BY KEY against the committed one (a
pitcher-season, a date, a game, a player, as each store defines it). A key that
would lose a record keeps the UNION of the committed and refreshed records, so
the pitcher whose answer is missing one old start still gets his new starts.
Bookkeeping markers are not records: an empty-day marker never sits beside real
rows, and an answer that carried nothing never replaces the committed coverage
marker, so the next run asks again. What was kept is reported and logged.

Everything here runs against temp data roots and the fake Stats API
(tests/_fake_statsapi.py). No network.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import bullpen, display_refresh as dr, history, pitchers
from src.providers import mlb
from tests._fake_statsapi import raw_game
from tests.test_display_refresh import Base, NOW, YESTERDAY, _sha

TODAY = "2026-10-03"


def _appearance(pid, day, started=1, **extra):
    row = {"person_id": pid, "date": day, "season": day[:4], "games_started": started,
           "innings_pitched": 6.0, "earned_runs": 2, "runs": 2, "hits": 5, "walks": 1,
           "strikeouts": 6, "home_runs": 1, "batters_faced": 24, "pitches": 90}
    row.update(extra)
    return row


def _marker(pid, checked="2026-09-07T10:00:00+00:00", empty=False):
    return {"person_id": pid, "season": "2026", "date": None, "empty": empty, "checked_utc": checked}


def _split(day, game_type="R"):
    return {"date": day, "gameType": game_type}


def _dates(path, pid):
    return sorted(a["date"] for a in pitchers.read_logs(path).get(str(pid), []) if a.get("date"))


class TheEmptyAnswerForOnePitcherDoesNotWipeHisSeason(Base):
    """Through the real refresh, with the fake API answering."""

    def setUp(self):
        super().setUp()
        # Tonight's announced starters are 111 and 222; tomorrow's is 333, a
        # pitcher the store has never held.
        self.fake.schedule["2026-10-04"] = [
            raw_game(22, "2026-10-04", "ATL", "PHI", None, None, "D", final=False, away_sp=333)]
        self.path = self.hist / "pitcher_logs.jsonl"

    def season(self, pid, days):
        return [_appearance(pid, f"2026-09-{d:02d}") for d in days]

    def test_the_total_grows_and_his_season_is_still_there(self):
        pitchers.write_logs({"111": self.season(111, range(1, 21))}, self.path)      # 20 starts
        # 111's answer is EMPTY; 333 arrives with 25 starts, so the total grows.
        self.fake.game_logs = {111: [], 222: [_split("2026-09-26")],
                               333: [_split(f"2026-09-{d:02d}") for d in range(1, 26)]}
        report = self.run_refresh(only=["pitchers"])
        self.assertEqual(report["steps"]["pitchers"]["status"], "ok")
        stored = pitchers.read_logs(self.path)
        self.assertEqual(len([a for a in stored["333"] if a.get("date")]), 25, "the rest of the copy is promoted")
        self.assertEqual(_dates(self.path, 111), [f"2026-09-{d:02d}" for d in range(1, 21)],
                         "111's season must survive an empty answer")
        total_after = sum(len(v) for v in stored.values())
        self.assertGreater(total_after, 20, "the premise: the TOTAL did grow")

    def test_what_was_kept_is_reported_and_logged(self):
        pitchers.write_logs({"111": self.season(111, range(1, 21))}, self.path)
        self.fake.game_logs = {111: [], 333: [_split(f"2026-09-{d:02d}") for d in range(1, 26)]}
        report = self.run_refresh(only=["pitchers"])
        self.assertEqual(len(report["restored"]), 1, report["restored"])
        kept = report["restored"][0]
        self.assertEqual((kept["step"], kept["file"], kept["keys"], kept["rows"]),
                         ("pitchers", "pitcher_logs.jsonl", 1, 20))
        self.assertEqual(kept["examples"], ["111:2026"])
        self.assertTrue([line for line in self.log
                         if "kept committed records for 1 key(s) in pitcher_logs.jsonl" in line
                         and "111:2026" in line], self.log)

    def test_an_empty_answer_does_not_make_him_look_freshly_checked(self):
        committed = self.season(111, range(1, 6)) + [_marker(111, checked="2026-09-07T10:00:00+00:00")]
        pitchers.write_logs({"111": committed}, self.path)
        self.fake.game_logs = {111: [], 333: [_split("2026-09-02")]}
        self.run_refresh(only=["pitchers"])
        marker = pitchers.coverage_marker(pitchers.read_logs(self.path)["111"], "2026")
        self.assertEqual(marker["checked_utc"], "2026-09-07T10:00:00+00:00",
                         "his committed marker stands, so the next run asks again")

    def test_a_key_that_loses_one_old_start_still_gains_the_new_ones(self):
        pitchers.write_logs({"111": self.season(111, (1, 6, 11))}, self.path)
        # The answer drops the 6th (a record the feed no longer carries) and
        # adds the 27th.
        self.fake.game_logs = {111: [_split("2026-09-01"), _split("2026-09-11"), _split("2026-09-27")]}
        report = self.run_refresh(only=["pitchers"])
        self.assertEqual(_dates(self.path, 111),
                         ["2026-09-01", "2026-09-06", "2026-09-11", "2026-09-27"])
        marker = pitchers.coverage_marker(pitchers.read_logs(self.path)["111"], "2026")
        self.assertEqual(marker["checked_utc"], NOW.isoformat(), "an answer with records writes its own marker")
        self.assertEqual(report["restored"][0]["rows"], 1)

    def test_a_pitcher_who_lost_nothing_is_replaced_as_before(self):
        pitchers.write_logs({"111": self.season(111, (1, 6))}, self.path)
        self.fake.game_logs = {111: [{**_split("2026-09-01"), "ip": "7.0"}, _split("2026-09-06")]}
        report = self.run_refresh(only=["pitchers"])
        self.assertEqual(report["restored"], [])
        first = next(a for a in pitchers.read_logs(self.path)["111"] if a.get("date") == "2026-09-01")
        self.assertEqual(first["innings_pitched"], 7.0, "a corrected figure still lands")

    def test_other_seasons_are_untouched_by_a_loss_in_this_one(self):
        old = [_appearance(111, "2025-06-01"), _appearance(111, "2025-07-01")]
        pitchers.write_logs({"111": old + self.season(111, (1, 6))}, self.path)
        self.fake.game_logs = {111: []}
        self.run_refresh(only=["pitchers"])
        self.assertEqual(_dates(self.path, 111), ["2025-06-01", "2025-07-01", "2026-09-01", "2026-09-06"])


class TheBullpenAndStandingsDatesKeepTheirRecords(Base):
    """The bullpen and standings steps re-fetch yesterday whole. A blip on that
    one date must not blank it while other dates grow the total."""

    def test_a_blip_on_yesterdays_schedule_leaves_yesterdays_rows(self):
        row = {"date": YESTERDAY, "game_pk": 13, "team": "NYY", "person_id": 9013, "name": "Late Arm",
               "started": False, "innings": 1.0, "pitches": 15}
        with (self.hist / "bullpen_log.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        real = self.fake

        def flaky(path, params=None, timeout=None):
            if path == "schedule" and (params or {}).get("date") == YESTERDAY:
                raise mlb.MLBError("blip")
            return real(path, params, timeout)

        with mock.patch.object(mlb, "_get_json", flaky):
            report = self.run_refresh(only=["bullpen"])
        rows = bullpen.read_log(self.hist / "bullpen_log.jsonl")
        self.assertIn((YESTERDAY, 13, 9013), {(r["date"], r.get("game_pk"), r.get("person_id")) for r in rows})
        grew = len(rows) > 3
        self.assertTrue(grew, "the premise: other dates were fetched, so the total grew")
        self.assertEqual([r["keys"] for r in report["restored"]], [1])


class TheKeyedRepairPerStore(unittest.TestCase):
    """`_promote` directly, one store shape at a time: a copy that lacks a
    committed key is promoted with the key kept."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.hist = self.root / "historical"
        self.hist.mkdir()

    def write(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n": a Windows text-mode write would store CRLF and the
        # "repair left the committed bytes" check compares bytes.
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))

    def read(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def promote(self, name, work_rows, committed_rows, kind="strict"):
        dest, work = self.hist / name, self.root / ("work_" + name)
        self.write(dest, committed_rows)
        self.write(work, work_rows)
        return dr._promote(work, dest, kind), dest

    def appearance(self, day, pk, person):
        return {"date": day, "game_pk": pk, "team": "NYY", "person_id": person, "started": False,
                "innings": 1.0, "pitches": 12}

    # -- bullpen -----------------------------------------------------------

    def test_a_bullpen_date_the_copy_lacks_is_kept_while_new_dates_arrive(self):
        committed = [self.appearance("2026-09-01", 1, 7), self.appearance("2026-09-01", 1, 8),
                     self.appearance("2026-09-02", 2, 7), self.appearance("2026-09-02", 2, 9)]
        work = committed[:2] + [self.appearance("2026-09-03", 3, 7)]
        result, dest = self.promote("bullpen_log.jsonl", work, committed)
        self.assertTrue(result["promoted"], result)
        self.assertEqual(result["kept_committed"], {"keys": 1, "rows": 2, "examples": ["2026-09-02"]})
        dates = sorted((r["date"], r["person_id"]) for r in self.read(dest))
        self.assertEqual(dates, [("2026-09-01", 7), ("2026-09-01", 8), ("2026-09-02", 7),
                                 ("2026-09-02", 9), ("2026-09-03", 7)])

    def test_a_date_that_lost_one_game_keeps_it_beside_the_games_it_gained(self):
        committed = [self.appearance("2026-09-01", 1, 7), self.appearance("2026-09-01", 2, 8)]
        work = [self.appearance("2026-09-01", 1, 7), self.appearance("2026-09-01", 3, 9)]
        result, dest = self.promote("bullpen_log.jsonl", work, committed)
        self.assertTrue(result["promoted"], result)
        games = sorted(r["game_pk"] for r in self.read(dest))
        self.assertEqual(games, [1, 2, 3])

    def test_an_empty_day_marker_never_survives_next_to_real_rows(self):
        committed = [{"date": "2026-09-01", "empty": True}]          # fetched before the games ended
        work = [self.appearance("2026-09-01", 1, 7)]
        result, dest = self.promote("bullpen_log.jsonl", work, committed)
        self.assertTrue(result["promoted"], result)
        self.assertNotIn("kept_committed", result, "a marker is bookkeeping, never a lost record")
        self.assertEqual([bool(r.get("empty")) for r in self.read(dest)], [False])

    def test_an_empty_answer_for_a_date_with_rows_keeps_the_rows_and_no_marker(self):
        committed = [self.appearance("2026-09-01", 1, 7), self.appearance("2026-09-02", 2, 7)]
        work = [self.appearance("2026-09-01", 1, 7), {"date": "2026-09-02", "empty": True},
                self.appearance("2026-09-03", 3, 7)]
        result, dest = self.promote("bullpen_log.jsonl", work, committed)
        self.assertTrue(result["promoted"], result)
        sept2 = [r for r in self.read(dest) if r["date"] == "2026-09-02"]
        self.assertEqual([r.get("person_id") for r in sept2], [7])
        self.assertFalse(any(r.get("empty") for r in sept2))

    # -- standings ----------------------------------------------------------

    def test_a_standings_day_the_copy_lacks_is_kept(self):
        def row(day, team):
            return {"date": day, "team_abbrev": team, "captured_at": f"{day}T20:00:00+00:00", "wins": 1}
        committed = [row("2026-09-01", "NYY"), row("2026-09-01", "BOS"), row("2026-09-02", "NYY")]
        work = [row("2026-09-01", "NYY"), row("2026-09-01", "BOS"), row("2026-09-03", "NYY")]
        result, dest = self.promote("standings.jsonl", work, committed)
        self.assertTrue(result["promoted"], result)
        self.assertEqual(sorted((r["date"], r["team_abbrev"]) for r in self.read(dest)),
                         [("2026-09-01", "BOS"), ("2026-09-01", "NYY"), ("2026-09-02", "NYY"),
                          ("2026-09-03", "NYY")])

    # -- results and the manifest -------------------------------------------

    def test_a_game_the_results_copy_lacks_is_kept(self):
        def game(pk, day):
            return {c: None for c in history.RESULT_COLUMNS} | {
                "game_pk": str(pk), "date": day, "game_type": "R", "away_team": "NYY",
                "home_team": "BOS", "away_score": "3", "home_score": "2"}
        dest, work = self.hist / "mlb_results.csv", self.root / "work_results.csv"
        history.write_results({"1": game(1, "2026-09-01"), "2": game(2, "2026-09-02")}, dest)
        history.write_results({"1": game(1, "2026-09-01"), "3": game(3, "2026-09-03"),
                               "4": game(4, "2026-09-03")}, work)
        result = dr._promote(work, dest, "strict")
        self.assertTrue(result["promoted"], result)
        self.assertEqual(sorted(history.read_results(dest)), ["1", "2", "3", "4"])
        self.assertEqual(result["kept_committed"]["examples"], ["2"])

    def test_a_manifest_date_the_copy_lacks_is_kept(self):
        dest, work = self.hist / "mlb_results.manifest.json", self.root / "work_manifest.json"
        entry = {"total": 1, "final": 1, "pending": 0, "cancelled": 0}
        history.write_manifest({"2026-09-01": entry, "2026-09-02": entry}, dest)
        history.write_manifest({"2026-09-01": entry, "2026-09-03": entry}, work)
        result = dr._promote(work, dest, "manifest")
        self.assertTrue(result["promoted"], result)
        self.assertEqual(sorted(history.read_manifest(dest)), ["2026-09-01", "2026-09-02", "2026-09-03"])

    # -- the JSON caches ------------------------------------------------------

    def test_a_cache_key_the_copy_lacks_is_kept(self):
        dest, work = self.hist / "pitcher_splits.json", self.root / "work_splits.json"
        dest.write_text(json.dumps({"1:2026": {"a": 1}, "2:2026": {"a": 2}}), encoding="utf-8")
        work.write_text(json.dumps({"1:2026": {"a": 1}, "3:2026": {"a": 3}}), encoding="utf-8")
        result = dr._promote(work, dest, "strict")
        self.assertTrue(result["promoted"], result)
        self.assertEqual(sorted(json.loads(dest.read_text(encoding="utf-8"))), ["1:2026", "2:2026", "3:2026"])

    # -- arsenals: committed rows stand, no union (shares of one snapshot) -----

    def test_a_player_whose_arsenal_lost_a_pitch_keeps_the_committed_rows_not_a_union(self):
        def payload(rows):
            return json.dumps({"season": "2026", "side": "pitcher", "as_of": "x", "rows": rows}, sort_keys=True)
        ff = {"player_id": "1", "pitch_type": "FF", "pitch_usage": 60.0}
        sl = {"player_id": "1", "pitch_type": "SL", "pitch_usage": 40.0}
        new = {"player_id": "2", "pitch_type": "FF", "pitch_usage": 100.0}
        dest, work = self.hist / "arsenals" / "pitcher_2026.json", self.root / "work_arsenal.json"
        dest.parent.mkdir()
        dest.write_text(payload([ff, sl]), encoding="utf-8")
        work.write_text(payload([dict(ff, pitch_usage=100.0), new]), encoding="utf-8")
        result = dr._promote(work, dest, "arsenal")
        self.assertTrue(result["promoted"], result)
        rows = json.loads(dest.read_text(encoding="utf-8"))["rows"]
        one = sorted((r["pitch_type"], r["pitch_usage"]) for r in rows if r["player_id"] == "1")
        self.assertEqual(one, [("FF", 60.0), ("SL", 40.0)], "the committed rows, shares summing to 100")
        self.assertEqual(len([r for r in rows if r["player_id"] == "2"]), 1)

    # -- what is not repaired, and what cannot be ----------------------------

    def test_a_destination_with_no_keyed_repair_keeps_the_totals_rule(self):
        dest, work = self.hist / "something_else.jsonl", self.root / "work_something.jsonl"
        self.write(dest, [{"a": 1}, {"a": 2}])
        self.write(work, [{"a": 1}])
        result = dr._promote(work, dest, "strict")
        self.assertFalse(result["promoted"])
        self.assertIn("fewer rows", result["reason"])

    def test_a_copy_that_cannot_be_checked_is_not_promoted(self):
        dest, work = self.hist / "handedness.json", self.root / "work_hand.json"
        dest.write_text(json.dumps({"1": {"bats": "R"}}), encoding="utf-8")
        before = _sha(dest)
        work.write_text(json.dumps([1, 2, 3]), encoding="utf-8")            # valid JSON, wrong shape
        result = dr._promote(work, dest, "strict")
        self.assertFalse(result["promoted"])
        self.assertIn("could not check", result["reason"])
        self.assertEqual(_sha(dest), before)

    def test_an_unreadable_committed_copy_is_nothing_to_protect(self):
        dest, work = self.hist / "pitcher_splits.json", self.root / "work_splits2.json"
        dest.write_text("{broken", encoding="utf-8")
        work.write_text(json.dumps({"1:2026": {"a": 1}}), encoding="utf-8")
        self.assertTrue(dr._promote(work, dest, "strict")["promoted"])

    def test_a_repair_that_leaves_the_committed_bytes_is_reported_unchanged(self):
        committed = [self.appearance("2026-09-01", 1, 7)]
        result, dest = self.promote("bullpen_log.jsonl", [], committed)
        self.assertFalse(result["promoted"])
        self.assertEqual(result["reason"], "unchanged")
        self.assertEqual(result["kept_committed"]["keys"], 1)
        self.assertEqual(self.read(dest), committed)


if __name__ == "__main__":
    unittest.main()
