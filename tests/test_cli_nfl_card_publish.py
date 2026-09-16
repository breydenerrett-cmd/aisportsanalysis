"""tests/test_cli_nfl_card_publish.py

`cmd_card`'s NFL branch (src/cli.py) is a SEPARATE code path from
`src.report.nfl_card.publish_for_date` -- it prints the reason a reader
actually sees on the terminal and decides, from `args.dry_run`, whether the
ledger gets written at all. `tests/test_nfl_card_publish.py` covers the
function underneath; none of it ran the CLI's own branch, which is exactly
how two bugs sat there unnoticed:

  1. `result.get("published")` was falsy on a REAL, successful publish --
     `card_ledger.publish`'s success return deliberately carries no
     "published" key (see the failure-shape contract pinned in
     tests/test_nfl_card_publish.py) -- so the branch printed
     "no card: None" for a genuine STRONG pick.
  2. `--dry-run` was never read in the NFL branch at all: every "dry run"
     call published for real. Caught 2026-09-16 running the actual W-6
     forward-test verification command, which left a real row in
     evidence/cards_nfl_v1.jsonl.

Both are pinned here by calling `src.cli.cmd_card` itself -- the function a
terminal actually runs -- with every provider seam mocked (no network, no
disk) so this stays a fast unit test.
"""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest import mock

from src import cli


def _args(date_str="2026-09-17", dry_run=False):
    return argparse.Namespace(card_command="publish", sport="nfl",
                              date=date_str, dry_run=dry_run)


class CmdCardNFLBranchTests(unittest.TestCase):
    NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)

    def _entry_with_board(self, n_books=11):
        """A real, priced candidate: kickoff ahead, MIN_BOOKS+ quotes,
        a lopsided consensus -- the STRONG shape of tomorrow's real
        Lions @ Bills slate."""
        return [{
            "game_id": "2026_02_DET_BUF", "week": 2,
            "home_team": "Buffalo Bills", "away_team": "Detroit Lions",
            "home_code": "BUF", "away_code": "DET",
            "kickoff_utc": "2026-09-18T00:15:00Z", "neutral_site": False,
            "h2h_quotes": [
                {"book": f"book{i}", "home_price": -218, "away_price": 180,
                 "observed_utc": self.NOW.isoformat()}
                for i in range(n_books)
            ],
            "spread_quotes": [], "model": None,
            "grade": {"ready": True, "reasons": []},
        }]

    def test_a_real_publish_prints_the_pick_not_no_card_none(self):
        """Regression (bug 1): a genuine publish must never print
        "no card: None". Run against the pre-fix cli.py (the branch that
        trusted `result.get("published")`), this fails: the printed output
        contains "no card: None" instead of the bet.

        `nfl_slate.entries_for_date` is mocked with a kickoff far in the
        future (2026-09-18), so this needs no clock injection to stay
        true regardless of when it runs. `card_ledger._ledger` is mocked
        so the write never touches disk.
        """
        with mock.patch("src.pipeline.nfl_slate.entries_for_date",
                        return_value=self._entry_with_board()), \
             mock.patch("src.appstate.card_ledger._ledger") as mock_ledger_cls:
            mock_ledger = mock.MagicMock()
            mock_ledger.append.side_effect = lambda payload: dict(
                payload, row_hash="deadbeef", prev_hash="0" * 64)
            mock_ledger_cls.return_value = mock_ledger

            out = io.StringIO()
            with redirect_stdout(out):
                result = cli.cmd_card(_args(dry_run=False))

        text = out.getvalue()
        self.assertEqual(result, cli.EXIT_OK)
        self.assertNotIn("no card: None", text)
        self.assertIn("Take Buffalo Bills to win", text)
        self.assertIn("published: 1 pick(s)", text)
        mock_ledger.append.assert_called_once()

    def test_dry_run_prints_the_pick_and_writes_nothing(self):
        """Regression (bug 2): --dry-run must never reach the ledger. Run
        against the pre-fix cli.py (which called
        nfl_card.publish_for_date unconditionally, ignoring
        args.dry_run), this fails: mock_ledger.append is called even
        though dry_run=True -- which is exactly what happened for real
        against evidence/cards_nfl_v1.jsonl on 2026-09-16."""
        with mock.patch("src.pipeline.nfl_slate.entries_for_date",
                        return_value=self._entry_with_board()), \
             mock.patch("src.appstate.card_ledger._ledger") as mock_ledger_cls:
            mock_ledger_cls.return_value = mock.MagicMock()

            out = io.StringIO()
            with redirect_stdout(out):
                result = cli.cmd_card(_args(dry_run=True))

        text = out.getvalue()
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("Take Buffalo Bills to win", text)
        self.assertIn("--dry-run: nothing written.", text)
        mock_ledger_cls.return_value.append.assert_not_called()
        mock_ledger_cls.assert_not_called()

    def test_no_board_prints_the_honest_no_board_reason(self):
        """No entry carries a board (h2h_quotes empty on every entry) ->
        the CLI must print the "no priced board" wording, not "cleared the
        bar" and not a bare None."""
        entries = self._entry_with_board()
        entries[0]["h2h_quotes"] = []

        with mock.patch("src.pipeline.nfl_slate.entries_for_date",
                        return_value=entries):
            out = io.StringIO()
            with redirect_stdout(out):
                result = cli.cmd_card(_args(dry_run=True))

        text = out.getvalue()
        self.assertEqual(result, cli.EXIT_OK)
        self.assertIn("No priced board was available", text)
        self.assertNotIn("cleared the bar", text)
        self.assertNotIn("no card: None", text)


if __name__ == "__main__":
    unittest.main()
