"""`python -m src.cli store rotate` -- the CLI shim scripts/capture_slot.sh
and its three siblings actually run every slot (src/cli.py's `_cmd_store_
rotate`, src/pipeline/store_archive.py underneath it).

Runs `cli.main([...])` directly against a temp store, same pattern as
tests/test_cli_capture_commands_run.py -- no subprocess, no real data/
files. `AISPORTS_DATA_DIR` redirects `src.paths.processed_path`, which is
what `store_archive.ROTATABLE_STORES["odds_multibook"]["path"]` resolves
through, so pointing it at a temp dir is enough to keep this off the real
store without touching src.pipeline.store_archive's registry at all.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from src import cli


def _row(day: str, hour: int = 10) -> dict:
    return {"observed_utc": f"{day}T{hour:02d}:00:00.000000+00:00",
            "event_id": "e1", "book": "fanduel"}


def _write_rows(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8")


class StoreRotateCliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.hot = self.root / "processed" / "odds_multibook.jsonl"
        self._env_patch = mock.patch.dict(
            "os.environ", {"AISPORTS_DATA_DIR": str(self.root)})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def run_cli(self, *extra_args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["store", "rotate", "--store", "odds_multibook",
                             *extra_args])
        return code, out.getvalue()


class NoOpExitsClean(StoreRotateCliTestCase):
    def test_under_threshold_exits_ok(self):
        _write_rows(self.hot, [_row("2026-09-01")])
        code, out = self.run_cli(
            "--if-over-mb", "60", "--keep-days", "3",
            "--now", "2026-09-21T12:00:00+00:00")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("no-op", out)


class NegativeKeepDaysFailsClean(StoreRotateCliTestCase):
    """2026-09-21 review: rotate() now raises ValueError for a negative
    keep-window; before this fix it reached the cutoff arithmetic unchecked
    and this command crashed with an uncaught traceback instead of the same
    clean ESCALATE line every other failure path here prints."""

    def test_negative_keep_days_prints_escalate_not_a_traceback(self):
        _write_rows(self.hot, [_row("2026-09-21")] * 2000)  # over any small threshold
        code, out = self.run_cli(
            "--if-over-mb", "0.0001", "--keep-days", "-5",
            "--now", "2026-09-21T12:00:00+00:00")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ESCALATE", out)
        self.assertNotIn("Traceback", out)


class BlockedRotationWarns(StoreRotateCliTestCase):
    """2026-09-21 review: a hot file over threshold that cannot archive
    anything because the very first line is unparseable used to print an
    indistinguishable "no-op" -- exactly the state that then has no backstop
    except guard_staged_size's 75 MiB WARN. This command must say so."""

    def test_unparseable_leading_line_over_threshold_prints_warn(self):
        path = self.hot
        path.parent.mkdir(parents=True, exist_ok=True)
        garbage = "{not valid json\n"
        rows_json = "".join(
            json.dumps(_row("2026-09-01", hour=h), separators=(",", ":")) + "\n"
            for h in range(24))
        path.write_text(garbage + rows_json, encoding="utf-8")
        code, out = self.run_cli(
            "--if-over-mb", "0.00001", "--keep-days", "3",
            "--now", "2026-09-21T12:00:00+00:00")
        self.assertEqual(code, cli.EXIT_OK)  # a blocked no-op is not itself a failure
        self.assertIn("WARN", out)


if __name__ == "__main__":
    unittest.main()
