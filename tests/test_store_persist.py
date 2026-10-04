"""Persisting the refreshed MLB stores to git without losing a row (2026-10-04).

THE CLAIM UNDER TEST: the union of the committed copy and the refreshed copy
keeps a record that only git holds, updates a record the provider corrected,
keeps a record that only the refreshed copy holds, and never writes a copy that
is missing a record the other side has.

Hermetic: "git" is a dict of bytes behind the injectable `reader`, the disk is a
temp directory, nothing is fetched.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import bullpen, display_refresh as dr, history, pitchers, store_persist as sp
from tests.test_display_refresh import seed_root


def jsonl(rows):
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)


def arm(day, pk, pid, innings=1.0):
    return {"date": day, "game_pk": pk, "team": "NYY", "person_id": pid, "name": f"Arm {pid}",
            "started": False, "innings": innings, "pitches": 15}


class Base(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.head_root = seed_root(base / "head")           # what git holds
        self.disk_root = seed_root(base / "disk")           # what the runner has on disk
        self.head = self.head_root / "historical"
        self.disk = self.disk_root / "historical"

    def reader(self, name):
        path = self.head / name
        return path.read_bytes() if path.exists() else None

    def union(self, prefer="disk", **kw):
        return sp.union_stores(self.disk_root, reader=self.reader, prefer=prefer, season="2026", **kw)

    def action(self, report, name):
        return next(r for r in report["stores"] if r["file"] == name)


class ARowOnlyGitHoldsSurvives(Base):

    def test_bullpen_a_git_only_date_survives_a_disk_copy_that_lacks_it(self):
        # git: the committed September rows plus a postseason date the cache never saw
        (self.head / "bullpen_log.jsonl").write_text(jsonl([
            arm("2026-09-05", 5, 77), {"date": "2026-09-06", "empty": True},
            arm("2025-10-05", 900, 1), arm("2025-10-05", 900, 2)]), encoding="utf-8")
        # disk (an Actions-cache copy): the same September rows plus new days
        (self.disk / "bullpen_log.jsonl").write_text(jsonl([
            arm("2026-09-05", 5, 77), {"date": "2026-09-06", "empty": True},
            arm("2026-10-01", 13, 9013), arm("2026-10-02", 14, 9014)]), encoding="utf-8")
        report = self.union()
        self.assertEqual(self.action(report, "bullpen_log.jsonl")["action"], "merged")
        keys = {(r["date"], r.get("game_pk"), r.get("person_id"))
                for r in bullpen.read_log(self.disk / "bullpen_log.jsonl")}
        self.assertIn(("2025-10-05", 900, 1), keys, "the row only git held is still there")
        self.assertIn(("2025-10-05", 900, 2), keys)
        self.assertIn(("2026-10-02", 14, 9014), keys, "and so is the row only the refresh held")
        self.assertIn(("2026-09-05", 5, 77), keys)

    def test_results_a_git_only_game_survives(self):
        # the seed holds game 900 (a 2025 postseason game) on both sides; the
        # cache copy has lost it
        rows = history.read_results(self.disk / "mlb_results.csv")
        rows.pop("900")
        rows["5"] = {**rows["1"], "game_pk": "5", "date": "2026-09-24"}
        history.write_results(rows, self.disk / "mlb_results.csv")
        report = self.union()
        self.assertEqual(self.action(report, "mlb_results.csv")["action"], "merged")
        merged = history.read_results(self.disk / "mlb_results.csv")
        self.assertEqual({"1", "2", "5", "900"}, set(merged))

    def test_pitcher_logs_a_git_only_pitcher_survives(self):
        head_logs = pitchers.read_logs(self.head / "pitcher_logs.jsonl")
        head_logs["777"] = [{"person_id": 777, "date": "2025-10-03", "season": "2025", "games_started": 1,
                             "innings_pitched": 6.0, "earned_runs": 1}]
        pitchers.write_logs(head_logs, self.head / "pitcher_logs.jsonl")
        self.union()
        self.assertEqual([a["date"] for a in pitchers.read_logs(self.disk / "pitcher_logs.jsonl")["777"]],
                         ["2025-10-03"])

    def test_a_store_absent_on_disk_is_restored_from_git(self):
        (self.disk / "transactions.jsonl").unlink()
        report = self.union()
        self.assertEqual(self.action(report, "transactions.jsonl")["action"], "restored from committed copy")
        self.assertEqual((self.disk / "transactions.jsonl").read_bytes(),
                         (self.head / "transactions.jsonl").read_bytes())


class ACorrectionIsUpdatedNotDuplicated(Base):

    def write_pair(self, head_innings, disk_innings):
        (self.head / "bullpen_log.jsonl").write_text(jsonl([arm("2026-10-01", 13, 9013, head_innings),
                                                            arm("2026-09-30", 12, 9012)]), encoding="utf-8")
        (self.disk / "bullpen_log.jsonl").write_text(jsonl([arm("2026-10-01", 13, 9013, disk_innings),
                                                            arm("2026-10-02", 14, 9014)]), encoding="utf-8")

    def rows(self):
        return {(r["date"], r["person_id"]): r for r in bullpen.read_log(self.disk / "bullpen_log.jsonl")}

    def test_the_refreshed_copy_wins_a_record_both_sides_hold(self):
        self.write_pair(head_innings=1.0, disk_innings=2.0)          # the provider corrected it
        self.union(prefer="disk")
        rows = self.rows()
        self.assertEqual(rows[("2026-10-01", 9013)]["innings"], 2.0, "the correction landed")
        self.assertEqual(len([k for k in rows if k[0] == "2026-10-01"]), 1, "not duplicated")
        self.assertIn(("2026-09-30", 9012), rows, "git-only row kept")
        self.assertIn(("2026-10-02", 9014), rows, "disk-only row kept")

    def test_pitcher_start_corrected_upstream_is_updated(self):
        head = {"111": [{"person_id": 111, "date": "2026-09-25", "season": "2026", "games_started": 1,
                         "innings_pitched": 6.0, "earned_runs": 2},
                        {"person_id": 111, "date": "2026-09-01", "season": "2026", "games_started": 1,
                         "innings_pitched": 5.0, "earned_runs": 3}]}
        disk = {"111": [{"person_id": 111, "date": "2026-09-25", "season": "2026", "games_started": 1,
                         "innings_pitched": 7.0, "earned_runs": 2}]}      # corrected; lost the 09-01 start
        pitchers.write_logs(head, self.head / "pitcher_logs.jsonl")
        pitchers.write_logs(disk, self.disk / "pitcher_logs.jsonl")
        self.union(prefer="disk")
        merged = {a["date"]: a for a in pitchers.read_logs(self.disk / "pitcher_logs.jsonl")["111"] if a.get("date")}
        self.assertEqual(merged["2026-09-25"]["innings_pitched"], 7.0)
        self.assertIn("2026-09-01", merged, "the start only git held is back")

    def test_results_a_corrected_score_is_updated(self):
        rows = history.read_results(self.disk / "mlb_results.csv")
        rows["1"] = {**rows["1"], "away_score": "9"}
        history.write_results(rows, self.disk / "mlb_results.csv")
        self.union(prefer="disk")
        self.assertEqual(history.read_results(self.disk / "mlb_results.csv")["1"]["away_score"], "9")

    def test_prefer_head_an_old_cache_cannot_overwrite_what_git_knows(self):
        """An OLD cache is restored over the checkout: it has the old value of a
        record git has since corrected, and one row git never got."""
        self.write_pair(head_innings=2.0, disk_innings=1.0)     # git has the corrected 2.0; the cache the old 1.0
        self.union(prefer="head")
        rows = self.rows()
        self.assertEqual(rows[("2026-10-01", 9013)]["innings"], 2.0, "git's value stands")
        self.assertIn(("2026-10-02", 9014), rows, "the cache-only row is kept")
        self.assertIn(("2026-09-30", 9012), rows)


class NothingIsEverWrittenThatLosesARecord(Base):

    def test_the_merge_holds_every_record_of_both_sides(self):
        head_rows = [arm("2026-09-01", 1, 1), arm("2026-09-01", 1, 2), arm("2026-09-02", 2, 3)]
        disk_rows = [arm("2026-09-02", 2, 3), arm("2026-09-03", 3, 4), arm("2026-09-03", 3, 5)]
        (self.head / "bullpen_log.jsonl").write_text(jsonl(head_rows), encoding="utf-8")
        (self.disk / "bullpen_log.jsonl").write_text(jsonl(disk_rows), encoding="utf-8")
        for prefer in ("disk", "head"):
            self.union(prefer=prefer)
            merged = {(r["game_pk"], r["person_id"]) for r in bullpen.read_log(self.disk / "bullpen_log.jsonl")}
            self.assertEqual(merged, {(1, 1), (1, 2), (2, 3), (3, 4), (3, 5)}, prefer)

    def test_a_merge_that_would_still_lose_a_record_is_refused_and_the_disk_is_untouched(self):
        (self.head / "bullpen_log.jsonl").write_text(jsonl([arm("2026-09-01", 1, 1)]), encoding="utf-8")
        (self.disk / "bullpen_log.jsonl").write_text(jsonl([arm("2026-09-03", 3, 4)]), encoding="utf-8")
        before = (self.disk / "bullpen_log.jsonl").read_bytes()
        real = dr.KEYED_STORES["bullpen_log.jsonl"]
        seen = {"n": 0}

        def blind_merge_honest_check(work, committed):
            seen["n"] += 1
            return None if seen["n"] == 1 else real(work, committed)   # the merge forgets; the check does not

        with mock.patch.dict(dr.KEYED_STORES, {"bullpen_log.jsonl": blind_merge_honest_check}):
            report = self.union()
        self.assertEqual(self.action(report, "bullpen_log.jsonl")["action"], "refused")
        self.assertIn("bullpen_log.jsonl", report["refused"])
        self.assertEqual((self.disk / "bullpen_log.jsonl").read_bytes(), before)

    def test_an_unparseable_committed_copy_is_not_merged_in(self):
        (self.head / "pitcher_splits.json").write_text("{ not json", encoding="utf-8")
        before = (self.disk / "pitcher_splits.json").read_bytes()
        report = self.union()
        self.assertEqual(self.action(report, "pitcher_splits.json")["action"], "refused")
        self.assertEqual((self.disk / "pitcher_splits.json").read_bytes(), before)

    def test_a_second_union_changes_nothing(self):
        (self.head / "bullpen_log.jsonl").write_text(jsonl([arm("2026-09-01", 1, 1)]), encoding="utf-8")
        (self.disk / "bullpen_log.jsonl").write_text(jsonl([arm("2026-09-03", 3, 4)]), encoding="utf-8")
        self.union()
        settled = (self.disk / "bullpen_log.jsonl").read_bytes()
        again = self.union()
        self.assertEqual(self.action(again, "bullpen_log.jsonl")["action"], "unchanged")
        self.assertEqual((self.disk / "bullpen_log.jsonl").read_bytes(), settled)

    def test_no_work_directory_survives_and_nothing_else_under_the_root_is_touched(self):
        sentinel = self.disk_root / "watch" / "sentinel.jsonl"
        before = sentinel.read_bytes()
        self.union()
        self.assertFalse((self.disk_root / ".union_work").exists())
        self.assertEqual(sentinel.read_bytes(), before)


class ArsenalsAreSnapshotsNotUnions(Base):

    def write(self, root, as_of, ids):
        (root / "arsenals" / "pitcher_2026.json").write_text(json.dumps(
            {"as_of": as_of, "season": "2026", "side": "pitcher",
             "rows": [{"player_id": i, "pitch_type": "FF"} for i in ids]}), encoding="utf-8")

    def test_the_later_snapshot_wins_whole_with_no_double_count(self):
        self.write(self.head, "2026-09-08T20:00:00+00:00", [1, 2])
        self.write(self.disk, "2026-10-04T10:00:00+00:00", [2, 3])
        self.union(prefer="disk")
        rows = json.loads((self.disk / "arsenals" / "pitcher_2026.json").read_text(encoding="utf-8"))["rows"]
        self.assertEqual(sorted(r["player_id"] for r in rows), [2, 3])

    def test_an_older_snapshot_on_disk_gives_way_to_the_committed_one(self):
        self.write(self.head, "2026-10-04T10:00:00+00:00", [1, 2])
        self.write(self.disk, "2026-09-08T20:00:00+00:00", [9])
        self.union(prefer="disk")
        rows = json.loads((self.disk / "arsenals" / "pitcher_2026.json").read_text(encoding="utf-8"))["rows"]
        self.assertEqual(sorted(r["player_id"] for r in rows), [1, 2])


class TheStageListNamesOnlyWhatDiffersFromGit(Base):

    def test_only_changed_stores_are_listed_and_a_matching_one_is_not(self):
        (self.disk / "bullpen_log.jsonl").write_text(
            (self.head / "bullpen_log.jsonl").read_text(encoding="utf-8") + jsonl([arm("2026-10-02", 14, 9014)]),
            encoding="utf-8")
        self.union()
        listed = sp.differing_from_head(self.disk_root, reader=self.reader, season="2026")
        self.assertEqual(listed, ["bullpen_log.jsonl"])

    def test_line_endings_alone_are_not_a_difference(self):
        text = (self.head / "bullpen_log.jsonl").read_bytes().replace(b"\r\n", b"\n")
        (self.head / "bullpen_log.jsonl").write_bytes(text)
        (self.disk / "bullpen_log.jsonl").write_bytes(text.replace(b"\n", b"\r\n"))
        self.assertEqual(sp.differing_from_head(self.disk_root, reader=self.reader, season="2026"), [])


class TheCliNeverFailsTheCaller(Base):

    def test_an_unreadable_root_exits_zero_and_prints_no_path(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch.object(sp, "git_reader", return_value=lambda name: None):
            code = sp.main(["persist", "--root", str(Path(self._tmp.name) / "nowhere")])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "")

    def test_persist_prints_repo_relative_paths_for_the_loop_to_stage(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        (self.disk / "bullpen_log.jsonl").write_text(
            (self.head / "bullpen_log.jsonl").read_text(encoding="utf-8") + jsonl([arm("2026-10-02", 14, 9014)]),
            encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch.object(sp, "git_reader", return_value=self.reader):
            code = sp.main(["persist", "--root", str(self.disk_root)])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().split(), ["data/historical/bullpen_log.jsonl"])


if __name__ == "__main__":
    unittest.main()
