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
        # T13 cutover (2026-09-22): V1's ledger split at CUTOVER_DATE
        # (card.v1_store_path, docs/PREREG_CARD_V2.md R3), and this window
        # can straddle that boundary, so cmd_card now calls settle_recent
        # TWICE for mlb -- once against evidence/cards_v1.jsonl, once
        # against evidence/cards_v1_shadow.jsonl -- and sums the totals
        # (src.cli._cmd_card_settle_recent). Both calls share one
        # fetch_results closure (no double read of the results store).
        totals = {"dates_checked": 1, "settled": 1, "misses": []}
        with mock.patch("src.appstate.card_ledger.settle_recent",
                        return_value=totals) as mocked:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.cmd_card(_args(sport="mlb"))

        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(2, mocked.call_count)
        paths = {call.kwargs.get("path") for call in mocked.call_args_list}
        self.assertEqual(2, len(paths), "each call must target its own store")
        for call in mocked.call_args_list:
            self.assertEqual(call.kwargs.get("sport"), "mlb")
            self.assertIn("fetch_results", call.kwargs)
        self.assertIn("dates_checked=2", buf.getvalue())
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
