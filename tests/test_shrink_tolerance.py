"""The shrink guard tolerates a re-serialisation and still refuses a real shrink
(2026-10-16).

THE STORY
---------
Every daily-loop run since 2026-10-07 ended
`ESCALATE: data/historical/arsenals/<file>.json would shrink N -> N-k bytes,
refusing` (k from 1 to 4) and exit 1. scripts/lib_shrink_guard.sh compares a
non-jsonl store by byte size against HEAD, which is right for the cache-restore
incident it was built for (4,993 rows became 119) and wrong for a store the
loop itself rewrites, where a float spelled 0.3 instead of 0.30 moves the file
a few bytes with every record intact. Nine red days later a real alarm would
have been indistinguishable from the noise.

THE RULE UNDER TEST (scripts/shrink_tolerance.py)
-------------------------------------------------
A byte shrink is tolerated ONLY when the staged file is smaller by less than
0.1% of HEAD's AND the record count is unchanged. Both byte counts and both
record counts are logged. A real shrink (one record fewer, or 0.1% or more of
the bytes), an unparseable file, a store whose records cannot be counted, a
missing helper, and every .jsonl (rows are counted exactly there) refuse as
before: restored from HEAD, unstaged, ESCALATE line unchanged.

These run the REAL guard under real bash against a throwaway git repository,
the same way tests/test_lib_shrink_guard.py does, and the real helper.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import shrink_tolerance as st
from tests.test_lib_shrink_guard import BASH, GUARD, _run

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "shrink_tolerance.py"
ARSENALS = "data/historical/arsenals/pitcher_2026.json"


def arsenals_text(rows, *, spelling="0.30", indent=None):
    """A store shaped like data/historical/arsenals/*.json, with `spelling` as
    the one float whose spelling a re-serialisation can change."""
    body = {
        "as_of": "2026-10-12T19:33:33.640453+00:00",
        "min_pitches": 50,
        "rows": [{"name": f"Player {i:04d}", "ba": 0.289, "est_woba": 0.343,
                  "pitch_type": "FF", "pitches": 1000.0 + i} for i in range(rows)],
        "season": 2026,
        "side": "pitcher",
    }
    text = json.dumps(body, sort_keys=True, indent=indent)
    return text.replace("0.343", spelling, 1) if spelling != "0.343" else text


class TheJudgement(unittest.TestCase):
    """The pure decision, on bytes."""

    def judge(self, head, staged):
        return st.judge(head.encode("utf-8"), staged.encode("utf-8"))

    def test_a_few_bytes_with_every_record_is_tolerated_and_says_both_counts(self):
        head = arsenals_text(400, spelling="0.3430")
        staged = arsenals_text(400, spelling="0.343")
        self.assertEqual(len(head) - len(staged), 1)
        ok, message = self.judge(head, staged)
        self.assertTrue(ok, message)
        self.assertIn(f"bytes {len(head)} -> {len(staged)}", message)
        self.assertIn("records 400 -> 400", message)
        self.assertIn("same record count", message)

    def test_one_to_four_bytes_are_all_tolerated(self):
        head = arsenals_text(400, spelling="0.34300000")
        for spelling in ("0.3430000", "0.343000", "0.34300", "0.3430"):
            with self.subTest(spelling):
                staged = arsenals_text(400, spelling=spelling)
                shrink = len(head) - len(staged)
                self.assertTrue(1 <= shrink <= 4, shrink)
                self.assertTrue(self.judge(head, staged)[0])

    def test_one_record_fewer_is_a_real_shrink_even_when_only_a_few_bytes(self):
        head = json.dumps({"rows": [{"a": 1}] * 3000 + [{}]})
        staged = json.dumps({"rows": [{"a": 1}] * 3000})
        self.assertLess((len(head) - len(staged)) / len(head), st.MAX_SHRINK_FRACTION)
        ok, message = self.judge(head, staged)
        self.assertFalse(ok)
        self.assertIn("records changed", message)
        self.assertIn("records 3001 -> 3000", message)

    def test_a_tenth_of_a_percent_of_the_bytes_is_a_real_shrink_with_every_record(self):
        head = json.dumps({"rows": [{"note": "x" * 100}] * 50})
        # one value emptied: about 2% of the file, every record still there
        staged = json.dumps({"rows": [{"note": "x" * 100}] * 49 + [{"note": ""}]})
        ok, message = self.judge(head, staged)
        self.assertFalse(ok)
        self.assertIn("0.1% or more", message)
        self.assertIn("records 50 -> 50", message)

    def test_the_boundary_is_exclusive_at_exactly_a_tenth_of_a_percent(self):
        head = "[" + ",".join(["1"] * 4999) + "]" + " " * 1001
        # head is 4999 ones + 4998 commas + 2 brackets + 1001 spaces = 11000 bytes
        self.assertEqual(len(head), 11000)
        exactly = head[:len(head) - 11]            # 11 bytes = 0.1% exactly
        under = head[:len(head) - 10]              # 10 bytes = 0.0909%
        self.assertFalse(self.judge(head, exactly)[0])
        self.assertTrue(self.judge(head, under)[0])

    def test_a_file_that_is_not_smaller_is_not_a_shrink(self):
        head = arsenals_text(10)
        self.assertTrue(self.judge(head, head)[0])
        self.assertTrue(self.judge(head, head + "\n")[0])

    def test_what_cannot_be_judged_is_refused(self):
        good = arsenals_text(400)
        cases = {
            "staged is not json": (good, good[:-3]),
            "head is not json": ("not json at all" * 100, "not json" * 99),
            "no list to count": (json.dumps({"a": "x" * 5000}), json.dumps({"a": "x" * 4999})),
            "a bare number": ("1" * 5000, "1" * 4999),
            "undecodable bytes": None,
        }
        for name, pair in cases.items():
            with self.subTest(name):
                if pair is None:
                    ok, message = st.judge(b"\xff\xfe" * 3000, b"\xff\xfe" * 2999)
                else:
                    ok, message = self.judge(*pair)
                self.assertFalse(ok, message)

    def test_the_count_is_schema_free(self):
        self.assertEqual(st.count_records([1, 2, 3]), 3)
        self.assertEqual(st.count_records({"rows": [1, 2], "x": [3], "y": 5}), 3)
        self.assertEqual(st.count_records({"rows": []}), 0)
        self.assertIsNone(st.count_records({"a": 1}))
        self.assertIsNone(st.count_records("text"))
        self.assertIsNone(st.count_records(None))

    def test_an_empty_head_is_never_divided_by_zero(self):
        ok, _message = st.judge(b"", b"")
        self.assertTrue(ok)

    def test_a_byte_order_mark_does_not_make_a_store_unreadable(self):
        head = b"\xef\xbb\xbf" + arsenals_text(400, spelling="0.3430").encode("utf-8")
        staged = arsenals_text(400, spelling="0.343").encode("utf-8")
        self.assertTrue(st.judge(head, staged)[0])


@unittest.skipUnless(BASH, "no usable POSIX bash found on this machine")
class TheGuardOnAThrowawayRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / "data/historical/arsenals").mkdir(parents=True)
        _run("git", "init", "-q", cwd=self.repo)
        _run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        _run("git", "config", "user.name", "Test", cwd=self.repo)
        shutil.copy(GUARD, self.repo / "lib_shrink_guard.sh")
        shutil.copy(HELPER, self.repo / "shrink_tolerance.py")

    def commit(self, rel, text):
        path = self.repo / rel
        path.write_text(text, encoding="utf-8", newline="\n")
        _run("git", "add", rel, cwd=self.repo)
        _run("git", "commit", "-q", "-m", "initial", cwd=self.repo)

    def stage(self, rel, text):
        (self.repo / rel).write_text(text, encoding="utf-8", newline="\n")
        _run("git", "add", rel, cwd=self.repo)

    def guard(self, *paths):
        script = ("set -uo pipefail\n"
                  f"export PATH=\"$(dirname '{sys.executable.replace(chr(92), '/')}'):$PATH\"\n"
                  "python3() { '" + sys.executable.replace("\\", "/") + "' \"$@\"; }\n"
                  ". ./lib_shrink_guard.sh\n"
                  f"guard_staged_no_shrink {' '.join(paths)}\n")
        done = _run(BASH, "-c", script, cwd=self.repo)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def staged(self):
        return set(_run("git", "diff", "--cached", "--name-only", cwd=self.repo).stdout.split())

    # -- the daily loop's red run -------------------------------------------

    def test_a_reserialisation_shrink_is_kept_staged_and_not_escalated(self):
        head = arsenals_text(400, spelling="0.3430")
        staged = arsenals_text(400, spelling="0.343")
        self.commit(ARSENALS, head)
        self.stage(ARSENALS, staged)
        out = self.guard(ARSENALS)
        self.assertNotIn("ESCALATE:", out)
        self.assertIn(ARSENALS, self.staged())
        self.assertEqual((self.repo / ARSENALS).read_text(encoding="utf-8"), staged)
        self.assertIn(f"NOTE: {ARSENALS} re-serialised, not shrunk, keeping it", out)
        self.assertIn(f"bytes {len(head)} -> {len(staged)}", out)
        self.assertIn("records 400 -> 400", out)

    def test_the_exact_daily_loop_shape_one_to_four_bytes(self):
        head = arsenals_text(450, spelling="0.34300000")
        for n, spelling in enumerate(("0.3430000", "0.343000", "0.34300", "0.3430"), start=1):
            with self.subTest(spelling):
                _run("git", "reset", "-q", "--hard", cwd=self.repo)
                self.commit(ARSENALS, head) if n == 1 else None
                self.stage(ARSENALS, arsenals_text(450, spelling=spelling))
                out = self.guard(ARSENALS)
                self.assertNotIn("ESCALATE:", out, out)
                self.assertIn(ARSENALS, self.staged())

    # -- a real shrink still refuses -----------------------------------------

    def refused(self, head, staged, *, rel=ARSENALS):
        self.commit(rel, head)
        self.stage(rel, staged)
        out = self.guard(rel)
        self.assertIn(f"ESCALATE: {rel} would shrink {len(head.encode())} -> "
                      f"{len(staged.encode())} bytes, refusing", out)
        self.assertNotIn(rel, self.staged())
        self.assertEqual((self.repo / rel).read_text(encoding="utf-8"), head,
                         "the worktree copy was not restored from HEAD")
        return out

    def test_a_dropped_record_refuses_even_when_only_a_few_bytes(self):
        head = json.dumps({"rows": [{"a": 1}] * 3000 + [{}]})
        out = self.refused(head, json.dumps({"rows": [{"a": 1}] * 3000}))
        self.assertIn("records changed", out)
        self.assertIn("records 3001 -> 3000", out)

    def test_a_shrink_of_a_tenth_of_a_percent_or_more_refuses_with_every_record(self):
        head = json.dumps({"rows": [{"note": "x" * 100}] * 50})
        staged = json.dumps({"rows": [{"note": "x" * 100}] * 49 + [{"note": ""}]})
        out = self.refused(head, staged)
        self.assertIn("0.1% or more", out)

    def test_the_cache_restore_incident_still_refuses(self):
        out = self.refused(arsenals_text(4993), arsenals_text(119))
        self.assertIn("records 4993 -> 119", out)

    def test_an_unparseable_staged_store_refuses(self):
        good = arsenals_text(400)
        self.refused(good, good[:-5])

    def test_a_store_with_nothing_to_count_refuses(self):
        self.refused(json.dumps({"a": "x" * 5000}), json.dumps({"a": "x" * 4999}),
                     rel="data/historical/matchup_pairs.json")

    def test_a_vanished_store_is_still_a_shrink_to_zero(self):
        self.commit(ARSENALS, arsenals_text(10))
        (self.repo / ARSENALS).unlink()
        _run("git", "add", "-A", cwd=self.repo)
        out = self.guard(ARSENALS)
        self.assertIn(f"ESCALATE: {ARSENALS} would shrink", out)
        self.assertIn("-> 0 bytes, refusing", out)

    def test_the_refusal_names_both_counts_on_a_line_that_is_not_an_alarm(self):
        head = json.dumps({"rows": [{"a": 1}] * 3000 + [{}]})
        out = self.refused(head, json.dumps({"rows": [{"a": 1}] * 3000}))
        detail = [ln for ln in out.splitlines() if "not tolerated" in ln]
        self.assertEqual(len(detail), 1)
        self.assertFalse(detail[0].startswith("ESCALATE:"))
        self.assertEqual(sum(1 for ln in out.splitlines() if ln.startswith("ESCALATE:")), 1)

    def test_a_missing_helper_fails_closed(self):
        (self.repo / "shrink_tolerance.py").unlink()
        head = arsenals_text(400, spelling="0.3430")
        self.refused(head, arsenals_text(400, spelling="0.343"))

    # -- rows are still counted exactly --------------------------------------

    def test_a_jsonl_store_never_goes_through_the_tolerance(self):
        rel = "data/historical/lineups.jsonl"
        head = "".join(f'{{"row":{i},"pad":"{"x" * 200}"}}\n' for i in range(500))
        staged = "".join(f'{{"row":{i},"pad":"{"x" * 200}"}}\n' for i in range(499))
        self.commit(rel, head)
        self.stage(rel, staged)
        out = self.guard(rel)
        self.assertIn(f"ESCALATE: {rel} would shrink 500 -> 499 rows, refusing", out)
        self.assertNotIn("NOTE:", out)

    def test_a_grown_store_is_silent(self):
        self.commit(ARSENALS, arsenals_text(10))
        self.stage(ARSENALS, arsenals_text(11))
        out = self.guard(ARSENALS)
        self.assertEqual(out.strip(), "")
        self.assertIn(ARSENALS, self.staged())


class TheScriptCommandLine(unittest.TestCase):
    def test_the_helper_exits_zero_when_tolerated_and_one_when_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _run("git", "init", "-q", cwd=repo)
            blobs = []
            for text in (arsenals_text(400, spelling="0.3430"),
                         arsenals_text(400, spelling="0.343"),
                         arsenals_text(399)):
                path = repo / "f.json"
                path.write_text(text, encoding="utf-8", newline="\n")
                blobs.append(_run("git", "hash-object", "-w", "f.json", cwd=repo).stdout.strip())
            ok = subprocess.run([sys.executable, str(HELPER), blobs[0], blobs[1]], cwd=str(repo),
                                capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stdout)
            self.assertEqual(len(ok.stdout.strip().splitlines()), 1)
            bad = subprocess.run([sys.executable, str(HELPER), blobs[0], blobs[2]], cwd=str(repo),
                                 capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1, bad.stdout)
            usage = subprocess.run([sys.executable, str(HELPER)], cwd=str(repo),
                                   capture_output=True, text=True)
            self.assertEqual(usage.returncode, 1)
            gone = subprocess.run([sys.executable, str(HELPER), "0" * 40, "1" * 40],
                                  cwd=str(repo), capture_output=True, text=True)
            self.assertEqual(gone.returncode, 1)


class TheWiring(unittest.TestCase):
    def test_the_guard_calls_the_helper_that_sits_beside_it(self):
        text = GUARD.read_text(encoding="utf-8")
        self.assertIn('shrink_tolerance.py', text)
        self.assertTrue((GUARD.parent / "shrink_tolerance.py").exists())

    def test_the_original_refusal_line_is_unchanged(self):
        text = GUARD.read_text(encoding="utf-8")
        self.assertIn('echo "ESCALATE: $path would shrink $head_n -> $staged_n $unit, refusing"', text)


if __name__ == "__main__":
    unittest.main()
