"""An MLB off day is "nothing to settle", not a failure; a missed slate on a game day still is.

2026-10-02 was a league-wide off day between the Wild Card round and the Division Series.
The engine slate considered 0 games and recorded nothing. The next morning `engine settle`
("no paper wagers recorded") and `eod` ("no decisions were recorded") refused the date, the
daily loop printed two ESCALATE lines, and `scripts/escalations.py --check` failed both of
that day's runs. Both commands now ask `history.no_games_scheduled`, which answers only from
the results manifest's positive evidence (the schedule was read for the date, nothing is
pending, and it listed no regular-season or postseason game). Every other empty date is
refused exactly as before, with the same exit code, so the loop still escalates.

Everything here is injected: a temporary manifest, an empty wagers ledger, empty decision,
review and scorecard ledgers. No test reads the repository's real stores.
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import cli
from src import paths as paths_mod
from src.board import gamekey as gamekey_mod
from src.engine import settle_slate
from src.ledger import bridge as bridge_mod
from src.ledger import writer as writer_mod
from src.pipeline import history
from src.providers import mlb
from src.report import eod as eod_mod

DECISIVE = sorted(mlb.DECISIVE_GAME_TYPES)          # what history.ingest_date records
OFF_DAY = "2026-10-02"
GAME_DAY = "2026-10-03"


def _entry(total, *, stored=0, skipped=0, pending=0, cancelled=0, final=None, game_types=DECISIVE):
    row = {"total": total, "final": total - pending - cancelled if final is None else final,
           "pending": pending, "cancelled": cancelled, "stored": stored, "skipped_game_type": skipped}
    if game_types is not None:
        row["game_types"] = game_types
    return row


class TempManifest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.manifest = self.dir / "mlb_results.manifest.json"
        self.write_manifest({
            OFF_DAY: _entry(0),
            GAME_DAY: _entry(4, stored=4),
            "2025-07-15": _entry(1, skipped=1),                                # the All-Star Game only
            "2025-07-16": _entry(0, game_types=None),                         # an older entry, still an off day
            "2024-07-16": _entry(1, skipped=1, game_types=None),              # exhibition-only, regular scope
            "2026-09-12": _entry(15, stored=15, game_types=None),             # a regular-season day
            "2026-05-01": _entry(2, cancelled=2),                             # rained out: still scheduled
            "2026-09-30": _entry(4, pending=1, stored=3),                     # not finished
        })

    def write_manifest(self, dates):
        self.manifest.write_text(json.dumps({"dates": dates}), encoding="utf-8")


class NoGamesScheduled(TempManifest):
    def reason(self, day):
        return history.no_games_scheduled(day, path=self.manifest)

    def test_an_off_day_has_a_reason(self):
        self.assertEqual(self.reason(OFF_DAY), "the MLB schedule listed no games on 2026-10-02")
        self.assertIsNotNone(self.reason("2025-07-16"))

    def test_an_exhibition_only_day_counts_only_under_the_decisive_scope(self):
        self.assertIn("only exhibition games", self.reason("2025-07-15"))
        # read under the regular-season scope, a skipped game could have been a postseason one
        self.assertIsNone(self.reason("2024-07-16"))

    def test_any_scheduled_game_means_no_reason(self):
        for day in (GAME_DAY, "2026-09-12", "2026-05-01"):
            self.assertIsNone(self.reason(day), day)

    def test_unfinished_unknown_or_unreadable_dates_have_no_reason(self):
        self.assertIsNone(self.reason("2026-09-30"))                         # games pending
        self.assertIsNone(self.reason("2026-10-04"))                         # never read
        self.assertIsNone(history.no_games_scheduled(OFF_DAY, path=self.dir / "absent.json"))
        self.manifest.write_text("{not json", encoding="utf-8")
        self.assertIsNone(self.reason(OFF_DAY))

    def test_the_default_path_is_read_at_call_time(self):
        with mock.patch.object(history, "DEFAULT_MANIFEST", self.manifest):
            self.assertIsNotNone(history.no_games_scheduled(OFF_DAY))


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class EngineSettleOnAnOffDay(TempManifest):
    def setUp(self):
        super().setUp()
        for patch in (mock.patch.object(history, "DEFAULT_MANIFEST", self.manifest),
                      mock.patch.object(settle_slate, "PAPER_WAGERS_PATH", self.dir / "paper_wagers_v2.jsonl"),
                      mock.patch.object(settle_slate.gamekey, "load_map", return_value={})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_an_off_day_is_nothing_to_settle_and_exits_0(self):
        code, out, err = _run(["engine", "settle", "--date", OFF_DAY])
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("nothing to settle", out)
        self.assertIn("the MLB schedule listed no games on 2026-10-02", out)
        self.assertNotIn("ERROR", err)

    def test_a_game_day_without_wagers_still_fails_with_the_same_exit(self):
        code, out, err = _run(["engine", "settle", "--date", GAME_DAY])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("no paper wagers recorded for 2026-10-03", err)
        self.assertNotIn("nothing to settle", out)

    def test_a_date_the_manifest_never_read_still_fails(self):
        code, _, err = _run(["engine", "settle", "--date", "2026-10-04"])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("no paper wagers recorded", err)

    def test_the_library_still_refuses_with_a_settle_error(self):
        with self.assertRaises(settle_slate.SettleError) as ctx:
            settle_slate.run_settle(OFF_DAY)
        self.assertIsInstance(ctx.exception, settle_slate.NoWagersError)


class EodOnAnOffDay(TempManifest):
    def setUp(self):
        super().setUp()
        empty = self.dir / "ledgers"
        for patch in (mock.patch.object(history, "DEFAULT_MANIFEST", self.manifest),
                      mock.patch.object(bridge_mod, "V2_LEDGER_PATH", str(empty / "decisions.jsonl")),
                      mock.patch.object(writer_mod, "REVIEW_LEDGER_PATH", empty / "reviews.jsonl"),
                      mock.patch.object(writer_mod, "SCORECARD_LEDGER_PATH", empty / "scorecards.jsonl"),
                      mock.patch.object(paths_mod, "data_path", lambda *parts: Path(self.dir, "data", *parts)),
                      mock.patch.object(gamekey_mod, "events_for_date", return_value={})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_an_off_day_writes_nothing_and_exits_0(self):
        with mock.patch.object(eod_mod, "write_review") as write:
            code, out, err = _run(["eod", "--date", OFF_DAY])
        self.assertEqual(code, cli.EXIT_OK, err)
        self.assertIn("nothing to review", out)
        self.assertIn("no report written", out)
        write.assert_not_called()

    def test_a_game_day_without_decisions_still_refuses(self):
        docs = self.dir / "docs" / "eod"
        real = eod_mod.write_review

        def write_into_tmp(*args, **kwargs):
            kwargs.setdefault("docs_dir", docs)
            kwargs.setdefault("chain_path", str(self.dir / "eod_chain.jsonl"))
            return real(*args, **kwargs)

        with mock.patch.object(eod_mod, "write_review", side_effect=write_into_tmp):
            code, out, err = _run(["eod", "--date", GAME_DAY])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("no decisions were recorded", err)
        self.assertNotIn("nothing to review", out)
        self.assertFalse(docs.exists() and any(docs.iterdir()))


class TheDailyLoopStillEscalatesBoth(unittest.TestCase):
    """The fix is in the commands, so the loop's escalation on a non-zero exit is unchanged."""

    SCRIPT = (Path(__file__).resolve().parents[1] / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")

    def test_both_steps_escalate_on_a_non_zero_exit(self):
        self.assertIn('ESCALATE: engine settle failed for $YESTERDAY (exit $SETTLE_STATUS)', self.SCRIPT)
        self.assertIn('ESCALATE: eod self-review failed or refused for $YESTERDAY (exit $EOD_STATUS)', self.SCRIPT)


if __name__ == "__main__":
    unittest.main()
