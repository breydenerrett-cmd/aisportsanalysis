"""`tennis results` says "skipped: key unauthorized" once and is not an error
when the BALLDONTLIE key is not entitled to the tennis feed (2026-10-16).

THE STORY
---------
scripts/daily_loop.sh runs `python3 -m src.cli tennis results --date
$YESTERDAY` as a read-only check that the results feed answers. The BALLDONTLIE
key has returned HTTP 401 for ATP/WTA results since the trial ended
(docs/reports/2026-09-21_WHERE_WE_ARE.md), so every daily run printed
`ERROR: balldontlie API returned HTTP 401` on stderr and the command exited
non-zero. That is a standing fact about a key, not news about the run, and nine
days of the same ERROR line taught everyone to ignore ERROR lines.

WHAT IS PINNED
--------------
  * a 401 or 403 from the transport raises TennisResultsUnauthorized, a
    subclass of TennisResultsError (so every existing handler still catches it)
    with the message unchanged;
  * every other failure (500, unreachable, bad JSON) stays a plain
    TennisResultsError and the command still prints ERROR and exits non-zero;
  * the command prints ONE line, on stdout, containing "skipped: key
    unauthorized", prints nothing on stderr, and exits 0;
  * the daily loop still runs the command guarded (`|| true`).
"""

from __future__ import annotations

import argparse
import io
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from src import cli
from src.providers import tennis_results as tr

ROOT = Path(__file__).resolve().parent.parent


def _args(date="2026-10-15"):
    return argparse.Namespace(tennis_command="results", date=date)


def _http_error(code):
    return urllib.error.HTTPError("https://example.invalid/x", code, "msg", {}, None)


class TheTransport(unittest.TestCase):
    def feed(self):
        return tr.BallDontLieFeed("a-key")

    def get(self, error):
        with mock.patch("urllib.request.urlopen", side_effect=error):
            return self.feed()._default_get_json("https://example.invalid/x", {})

    def test_401_and_403_are_unauthorized_with_the_message_unchanged(self):
        for code in (401, 403):
            with self.subTest(code):
                with self.assertRaises(tr.TennisResultsUnauthorized) as caught:
                    self.get(_http_error(code))
                self.assertEqual(str(caught.exception), f"balldontlie API returned HTTP {code}")

    def test_it_is_still_a_tennis_results_error_for_every_older_handler(self):
        self.assertTrue(issubclass(tr.TennisResultsUnauthorized, tr.TennisResultsError))
        with self.assertRaises(tr.TennisResultsError):
            self.get(_http_error(401))

    def test_no_other_failure_is_unauthorized(self):
        for error in (_http_error(500), _http_error(404), _http_error(429),
                      urllib.error.URLError("no route"), TimeoutError()):
            with self.subTest(repr(error)):
                with self.assertRaises(tr.TennisResultsError) as caught:
                    self.get(error)
                self.assertNotIsInstance(caught.exception, tr.TennisResultsUnauthorized)


class TheCommand(unittest.TestCase):
    def run_cli(self, error):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(tr, "results_for", side_effect=error), \
                redirect_stdout(out), redirect_stderr(err):
            code = cli.cmd_tennis(_args())
        return code, out.getvalue(), err.getvalue()

    def test_unauthorized_is_one_skipped_line_exit_zero_and_nothing_on_stderr(self):
        code, out, err = self.run_cli(tr.TennisResultsUnauthorized("balldontlie API returned HTTP 401"))
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("skipped: key unauthorized", lines[0])
        self.assertIn("2026-10-15", lines[0])
        self.assertNotIn("ERROR", out)

    def test_any_other_failure_is_still_an_error(self):
        code, out, err = self.run_cli(tr.TennisResultsError("balldontlie API returned HTTP 500"))
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ERROR: balldontlie API returned HTTP 500", err)
        self.assertNotIn("skipped", out)

    def test_a_missing_key_is_still_an_error_not_a_skip(self):
        code, _out, err = self.run_cli(tr.TennisResultsError("BALLDONTLIE_API_KEY is not set"))
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ERROR:", err)

    def test_a_working_feed_prints_its_results_as_before(self):
        outcome = {"rows": [], "provider": "balldontlie", "reason": None}
        out = io.StringIO()
        with mock.patch.object(tr, "results_for", return_value=outcome), redirect_stdout(out):
            code = cli.cmd_tennis(_args())
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("tennis results 2026-10-15 (provider: balldontlie)", out.getvalue())
        self.assertIn("0 result(s)", out.getvalue())


class TheDailyLoopStillGuardsIt(unittest.TestCase):
    def test_the_loop_runs_the_command_and_cannot_fail_on_it(self):
        text = (ROOT / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
        self.assertIn('python3 -m src.cli tennis results --date "$YESTERDAY" 2>&1) || true', text)


if __name__ == "__main__":
    unittest.main()
