"""tests/test_cli_card_settle_recent.py

`card settle --recent` (src/cli.py, R-2026-09-19) is the CLI surface
scripts/daily_loop.sh now calls instead of one single-shot `--date
$YESTERDAY`. This pins the CLI wiring itself -- dispatch by sport, the
printed counts-only-plus-reasons format, and the `--date`-nor-`--recent`
error -- separately from `src.appstate.card_ledger.settle_recent` and
`src.report.nfl_card.settle_recent`, which tests/test_card_ledger_
settle_recent.py and tests/test_nfl_card_publish.py already cover. Every
provider seam here is mocked; nothing touches the network, the real clock,
or evidence/cards_*.jsonl.
"""

from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from src import cli


def _args(sport="nfl", date=None, recent=True):
    return argparse.Namespace(card_command="settle", sport=sport, rule="v1",
                              date=date, recent=recent)


class CmdCardSettleRecentDispatchTests(unittest.TestCase):
    def test_recent_dispatches_to_nfl_settle_recent_and_prints_counts_and_misses(self):
        totals = {
            "dates_checked": 2, "settled": 1,
            "misses": [{"date": "2026-09-17",
                       "reason": "results feed returned no final score yet "
                                "for any of this date's 1 pick(s)"}],
        }
        with mock.patch("src.report.nfl_card.settle_recent",
                        return_value=totals) as mocked:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.cmd_card(_args(sport="nfl"))

        mocked.assert_called_once_with()
        self.assertEqual(code, cli.EXIT_OK)
        out = buf.getvalue()
        self.assertIn("dates_checked=2", out)
        self.assertIn("settled=1", out)
        self.assertIn("misses=1", out)
        self.assertIn("MISS 2026-09-17: results feed returned no final "
                      "score yet", out)

    def test_recent_dispatches_to_mlb_card_ledger_settle_recent(self):
        totals = {"dates_checked": 1, "settled": 1, "misses": []}
        with mock.patch("src.appstate.card_ledger.settle_recent",
                        return_value=totals) as mocked:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.cmd_card(_args(sport="mlb"))

        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(mocked.call_args.kwargs.get("sport"), "mlb")
        self.assertIn("fetch_results", mocked.call_args.kwargs)
        self.assertIn("dates_checked=1", buf.getvalue())
        self.assertIn("misses=0", buf.getvalue())

    def test_recent_for_an_unwired_sport_errors_without_crashing(self):
        """tennis is a valid --sport choice for publish/settle generally
        (src.sports.keys()) but has no card ledger settle_recent path yet
        ('tennis when it exists' -- owner directive 2026-09-19). --recent
        must refuse loudly, not silently no-op or crash."""
        code = cli.cmd_card(_args(sport="tennis"))
        self.assertEqual(code, cli.EXIT_ERROR)

    def test_settle_without_date_or_recent_is_a_clean_error(self):
        code = cli.cmd_card(_args(sport="mlb", date=None, recent=False))
        self.assertEqual(code, cli.EXIT_ERROR)


if __name__ == "__main__":
    unittest.main()
