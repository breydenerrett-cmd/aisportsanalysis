"""Tests for src/pipeline/ledger.py.

The ledger is the only evidence in this project that cannot be corrupted by
discipline failing, so the tests are about that property and nothing else:
settlement must never touch the recommendation it settles, the information time
must be when the inputs were gathered rather than when the file was written, and
a declined game must be as recorded as a chosen one.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.detect import base
from src.detect import dossier as dossier_mod
from src.pipeline import ledger


def game(verdict="no_play", game_pk=1, findings=(), gaps=None,
         market=None, lineups=None, info_time=None):
    d = dossier_mod.Dossier(
        {"game_pk": game_pk, "away_team": "BOS", "home_team": "NYY",
         "date": "2026-08-28", "start_time_utc": "2026-08-28T23:05:00Z"},
        information_time=info_time)
    if market is not None:
        d.add("market", market)
    if lineups is not None:
        d.add("lineups", lineups)
    for name, reason in (gaps or {}).items():
        d.miss(name, reason)
    return {"dossier": d, "findings": list(findings), "verdict": verdict,
            "side": "home", "market": "first_five", "summary": "x"}


def slate(*games):
    return {"date": "2026-08-28", "games": list(games), "notes": []}


class TestWhatIsRecorded(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ledger.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_declined_games_are_recorded_too(self):
        # A strategy whose whole point is skipping most days cannot be described
        # without the days it skipped.
        ledger.record_slate(slate(game("no_play"), game("market_unavailable", 2)),
                            path=self.path)
        recorded = ledger.recommendations(path=self.path)
        self.assertEqual({r["verdict"] for r in recorded},
                         {"no_play", "market_unavailable"})

    def test_every_book_is_kept_not_the_chosen_one(self):
        # Which price was actually available is part of what the system knew,
        # and one quote cannot answer "could we have got that number".
        market = {"markets": {}, "all_books": {"h2h": [
            {"book": "a", "away_price": 150, "home_price": -170},
            {"book": "b", "away_price": 155, "home_price": -175}]}}
        ledger.record_slate(slate(game(market=market)), path=self.path)
        entry = ledger.recommendations(path=self.path)[0]
        self.assertEqual(len(entry["books"]["h2h"]), 2)

    def test_the_reasons_behind_a_verdict_survive(self):
        finding = base.Finding("d", base.SIGNAL, "because of this",
                               value=1, baseline=0, surprise=2.0)
        ledger.record_slate(slate(game(findings=[finding])), path=self.path)
        entry = ledger.recommendations(path=self.path)[0]
        self.assertEqual(entry["findings"][0]["claim"], "because of this")
        self.assertEqual(entry["findings"][0]["detector"], "d")

    def test_an_unposted_lineup_is_recorded_as_a_fact_with_its_reason(self):
        # A pick made before lineups post is a different pick from one made
        # after, and a ledger that cannot tell them apart cannot support the
        # timing question at all.
        ledger.record_slate(
            slate(game(gaps={"lineups": "not posted yet"})), path=self.path)
        status = ledger.recommendations(path=self.path)[0]["lineup_status"]
        self.assertFalse(status["posted"])
        self.assertEqual(status["reason"], "not posted yet")

    def test_a_posted_lineup_records_who_was_in_it(self):
        lineups = {"away": {"batters": [{"person_id": 1}, {"person_id": 2}],
                            "handedness": {"L": 1, "R": 1}},
                   "home": {"batters": [{"person_id": 3}], "handedness": {}}}
        ledger.record_slate(slate(game(lineups=lineups)), path=self.path)
        status = ledger.recommendations(path=self.path)[0]["lineup_status"]
        self.assertTrue(status["posted"])
        self.assertEqual(status["away"], [1, 2])

    def test_gaps_are_recorded_so_a_verdict_can_be_audited(self):
        ledger.record_slate(slate(game(gaps={"weather": "not fetched"})),
                            path=self.path)
        self.assertIn("weather",
                      ledger.recommendations(path=self.path)[0]["gaps"])


class TestInformationTime(unittest.TestCase):
    """The moment the inputs were gathered, not the moment the file was written."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ledger.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_it_comes_from_the_dossier_not_the_write(self):
        gathered = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        written = gathered + timedelta(minutes=4)
        ledger.record_slate(slate(game(info_time=gathered)), path=self.path,
                            recorded_at=written)
        entry = ledger.recommendations(path=self.path)[0]
        self.assertEqual(entry["information_time"], gathered.isoformat())
        self.assertEqual(entry["recorded_at"], written.isoformat())

    def test_a_slow_run_does_not_grant_itself_hindsight(self):
        gathered = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        ledger.record_slate(slate(game(info_time=gathered)), path=self.path,
                            recorded_at=gathered + timedelta(minutes=30))
        entry = ledger.recommendations(path=self.path)[0]
        self.assertLess(entry["information_time"], entry["recorded_at"])


class TestSettlementNeverRewrites(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ledger.jsonl"
        ledger.record_slate(slate(game(verdict="flagged")), path=self.path)

    def tearDown(self):
        self.dir.cleanup()

    def original_line(self):
        return Path(self.path).read_text(encoding="utf-8").splitlines()[0]

    def test_the_recommendation_line_is_byte_identical_after_settling(self):
        before = self.original_line()
        ledger.settle(1, {"winner": "NYY"}, path=self.path)
        self.assertEqual(self.original_line(), before)

    def test_a_settlement_is_its_own_line(self):
        ledger.settle(1, {"winner": "NYY"}, path=self.path)
        lines = Path(self.path).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["kind"], ledger.SETTLEMENT)

    def test_a_later_settlement_supersedes_an_earlier_one(self):
        # Legitimate when a later fetch fills a closing price that was missing.
        ledger.settle(1, {"winner": "NYY"}, path=self.path)
        ledger.settle(1, {"winner": "NYY"}, closing={"home_price": -170},
                      path=self.path)
        self.assertIsNotNone(
            ledger.settlements(path=self.path)[1]["closing"])

    def test_status_counts_settled_against_pending(self):
        ledger.settle(1, {"winner": "NYY"}, path=self.path)
        report = ledger.status(self.path)
        self.assertEqual(report["settled"], 1)
        self.assertEqual(report["pending"], 0)


class TestDeduplication(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ledger.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_the_earliest_recommendation_wins(self):
        # A re-run later in the day carries a price closer to first pitch, which
        # is better for reasons that have nothing to do with the system.
        early = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        ledger.record_slate(slate(game(verdict="no_play")), path=self.path,
                            recorded_at=early)
        ledger.record_slate(slate(game(verdict="flagged")), path=self.path,
                            recorded_at=early + timedelta(hours=6))
        kept = ledger.recommendations(path=self.path)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["verdict"], "no_play")

    def test_both_lines_remain_on_disk(self):
        # Deduplication is a reading rule, not a writing one. The file is the
        # record and nothing is ever removed from it.
        ledger.record_slate(slate(game()), path=self.path)
        ledger.record_slate(slate(game()), path=self.path)
        self.assertEqual(len(ledger.read(self.path)), 2)


class TestIO(unittest.TestCase):

    def test_a_missing_ledger_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ledger.read(Path(tmp) / "none.jsonl"), [])

    def test_a_corrupt_line_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.jsonl"
            path.write_text('{"kind":"recommendation"}\nnope\n', encoding="utf-8")
            with self.assertRaises(ledger.LedgerError) as ctx:
                ledger.read(path)
            self.assertIn(":2", str(ctx.exception))

    def test_the_ledger_lives_in_evidence_not_under_data(self):
        # data/ is gitignored because it is reproducible. A forward record is
        # the opposite: nobody can reconstruct it afterwards at any cost.
        self.assertEqual(Path(ledger.DEFAULT_LEDGER).parent.name, "evidence")


if __name__ == "__main__":
    unittest.main()
