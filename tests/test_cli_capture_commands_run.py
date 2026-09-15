"""The chain's `nfl capture` and `tennis capture` commands, run through main().

WHY THIS EXISTS
---------------
tests/test_cli_sport_commands.py proved the parser accepts `nfl capture` and
`tennis capture`. Nothing ran them. The first real capture slot (2026-09-15
04:48Z) then printed "argument should be a str ... not 'NoneType'" for NFL,
because the command passed placeholder arguments (done_path=None, capture={},
spend_guard=True, env={}) into nfl_capture.run, and printed "tennis capture:
completed" having captured nothing, because discovery had never run. Both
inside Thursday's first NFL capture window.

These tests call cli.main() with the pipeline functions patched, and assert
what the command actually hands them and what it does when discovery is empty.
No network, no real stores.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from src import cli


class NflCaptureCommandRuns(unittest.TestCase):
    def test_passes_no_placeholder_arguments(self):
        with mock.patch("src.pipeline.nfl_capture.run",
                        return_value={"due": [], "captured": False,
                                      "reason": "no phase due", "credits": 0}) as run:
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["nfl", "capture"])
        self.assertEqual(code, cli.EXIT_OK)
        args, kwargs = run.call_args
        self.assertEqual(args, ())
        # Every seam at its real default: none of the placeholders that broke
        # the first run may come back.
        for name in ("capture", "spend_guard", "done_path", "env", "games"):
            self.assertNotIn(name, kwargs)
        self.assertIn("0 phase(s) due", out.getvalue())
        self.assertIn("no phase due", out.getvalue())

    def test_logs_credits_after_a_real_capture(self):
        result = {"due": [("2026_02_DET_BUF", "t72h")], "captured": True, "credits": 3,
                  "summary": {"events": 16, "captured": 48, "multibook": 900}}
        with mock.patch("src.pipeline.nfl_capture.run", return_value=result), \
                mock.patch("src.providers.odds.quota",
                           return_value={"remaining": 21000, "last": 3}) as quota, \
                mock.patch("src.pipeline.creditlog.log") as log:
            with redirect_stdout(io.StringIO()):
                code = cli.main(["nfl", "capture"])
        self.assertEqual(code, cli.EXIT_OK)
        quota.assert_called_once()
        log.assert_called_once()
        args, kwargs = log.call_args
        self.assertEqual(args[:3], (21000, 3, "nfl_capture.run"))
        self.assertEqual(kwargs.get("budget_band"), "live_capture")


class NflCaptureUnconfiguredIsNotACapture(unittest.TestCase):
    def test_configured_false_marks_nothing_done(self):
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path

        from src.pipeline import nfl_capture

        now = datetime(2026, 9, 15, 5, 0, tzinfo=timezone.utc)
        games = [{"game_id": "2026_02_DET_BUF", "start_utc": "2026-09-18T00:15:00Z"}]

        class Allow:
            allowed = True
            reason = "ok"

        with tempfile.TemporaryDirectory() as folder:
            done = Path(folder) / "done.jsonl"
            result = nfl_capture.run(
                now=now, games=games, done_path=done,
                spend_guard=lambda *a, **k: Allow(),
                capture=lambda **k: {"captured": 0, "configured": False,
                                     "message": "no key"})
            self.assertFalse(result["captured"])
            self.assertIn("not configured", result["reason"])
            self.assertEqual(nfl_capture.load_done(done), set())


class NflSettleBuysNoScoresWithoutACard(unittest.TestCase):
    def test_no_published_card_means_no_scores_fetch(self):
        """The daily loop settles yesterday's NFL card every morning of the
        year; on the days with no card it must not buy scores."""
        import tempfile
        from pathlib import Path

        from src.report import nfl_card as nfl_card_report

        with tempfile.TemporaryDirectory() as folder:
            ledger = str(Path(folder) / "cards_nfl_v1.jsonl")
            with mock.patch("src.pipeline.nfl_slate.results_for_date") as fetch:
                result = nfl_card_report.settle_for_date("2026-09-14", path=ledger)
        self.assertIsNone(result)
        fetch.assert_not_called()


class TennisCaptureCommandRuns(unittest.TestCase):
    def test_discovers_first_when_no_active_keys(self):
        with mock.patch("src.pipeline.tennis_discovery.active_keys", return_value=[]), \
                mock.patch("src.pipeline.tennis_discovery.discover",
                           return_value={"keys": ["tennis_wta_sao_paulo"],
                                         "active_keys": ["tennis_wta_sao_paulo"],
                                         "written": 1}) as discover, \
                mock.patch("src.pipeline.tennis_capture.run",
                           return_value={"keys": ["tennis_wta_sao_paulo"], "captured": [],
                                         "skipped": {"tennis_wta_sao_paulo": "refused: PROBE_REQUIRED"},
                                         "credits": 0, "rows": 0}) as run:
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["tennis", "capture"])
        self.assertEqual(code, cli.EXIT_OK)
        discover.assert_called_once()
        run.assert_called_once()
        text = out.getvalue()
        self.assertIn("1 active tournament(s)", text)
        self.assertIn("skipped tennis_wta_sao_paulo", text)

    def test_skips_discovery_when_fresh_keys_exist(self):
        with mock.patch("src.pipeline.tennis_discovery.active_keys",
                        return_value=["tennis_wta_sao_paulo"]), \
                mock.patch("src.pipeline.tennis_discovery.discover") as discover, \
                mock.patch("src.pipeline.tennis_capture.run",
                           return_value={"keys": [], "captured": [], "skipped": {},
                                         "credits": 0, "rows": 0}):
            with redirect_stdout(io.StringIO()):
                code = cli.main(["tennis", "capture"])
        self.assertEqual(code, cli.EXIT_OK)
        discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
