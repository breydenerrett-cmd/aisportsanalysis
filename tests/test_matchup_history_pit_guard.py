"""Every scheduled caller of matchup_history.build must pass TODAY only.

WHY THIS FILE EXISTS SEPARATELY
--------------------------------
`src/pipeline/matchup_history.py` reads the MLB vsPlayer endpoint, which
returns CAREER batter-vs-pitcher totals with no as-of parameter --
`src/model/pointintime.py` marks it LEAKY for exactly that reason. Fetching it
for a date whose games have already been played bakes those games' own plate
appearances into what the store calls their "history", so a decision made
later reads an input contaminated by the outcome it is trying to predict.

The rule is therefore: scheduled callers build TODAY, never yesterday, never a
backfill range. Both `scripts/daily_loop.sh` and `scripts/forward_capture.sh`
document that rule in prose beside the call.

Prose is not a guard. An adversarial verifier mutated
`matchup_history.build('$TODAY')` to `build('$YESTERDAY')` in
`scripts/forward_capture.sh` and the entire test suite stayed green -- the
leak the comments warn about was completely unguarded. This file is that
guard.

It is a text scan, which is a weak form of test, but a shell script offers no
other seam, and the specific dangerous edit is exactly the one a text scan
catches. It asserts the *shape* of every call rather than a whole-file
checksum, so ordinary edits to these scripts do not fail it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Every script that runs on a schedule and calls matchup_history.build.
# Adding a new scheduled caller means adding it here -- that is deliberate
# friction on a call with a known leak.
SCHEDULED_CALLERS = (
    "scripts/daily_loop.sh",
    "scripts/forward_capture.sh",
)

# `matchup_history.build(<arg>)`, capturing whatever was passed.
BUILD_CALL = re.compile(r"matchup_history\.build\(\s*([^)]*?)\s*\)")

# The only argument a scheduled caller may pass. The shell variable is
# interpolated into a python -c heredoc, so it appears literally as '$TODAY'.
ALLOWED_ARGS = {"'$TODAY'", '"$TODAY"'}

# Argument shapes that are a point-in-time leak if they ever appear.
FORBIDDEN_SUBSTRINGS = ("YESTERDAY", "START", "BACKFILL", "RANGE", "catchup")


class MatchupHistoryIsTodayOnlyTests(unittest.TestCase):
    def _sources(self):
        for rel in SCHEDULED_CALLERS:
            path = REPO / rel
            self.assertTrue(path.exists(), f"{rel} is missing")
            yield rel, path.read_text(encoding="utf-8", errors="replace")

    def test_every_scheduled_caller_actually_calls_build(self):
        """Guards the guard: if a rename silently removed these calls, the
        rest of this file would pass vacuously."""
        for rel, text in self._sources():
            self.assertTrue(
                BUILD_CALL.search(text),
                f"{rel} no longer calls matchup_history.build -- either the "
                "call moved (update SCHEDULED_CALLERS) or this file has "
                "stopped guarding anything")

    def test_no_scheduled_caller_builds_anything_but_today(self):
        """The mutation that survived: build('$TODAY') -> build('$YESTERDAY').

        vsPlayer returns career totals with no as-of parameter, so building a
        date whose games are already final folds those games into their own
        history.
        """
        for rel, text in self._sources():
            for arg in BUILD_CALL.findall(text):
                self.assertIn(
                    arg, ALLOWED_ARGS,
                    f"{rel} calls matchup_history.build({arg}) -- scheduled "
                    "callers may pass only $TODAY. The vsPlayer endpoint "
                    "returns CAREER totals with no as-of parameter, so any "
                    "past date bakes that date's own plate appearances into "
                    "what the store calls its history")

    def test_no_scheduled_caller_names_a_past_or_range_argument(self):
        """Catches the leak in shapes the exact-match test above would miss --
        a renamed variable, a catchup helper, a start/end pair."""
        for rel, text in self._sources():
            for arg in BUILD_CALL.findall(text):
                upper = arg.upper()
                for bad in FORBIDDEN_SUBSTRINGS:
                    self.assertNotIn(
                        bad.upper(), upper,
                        f"{rel}: matchup_history.build({arg}) names {bad!r}, "
                        "which reads as a past date or a range. This endpoint "
                        "is forward-only by design")

    def test_the_leak_reasoning_stays_next_to_the_call(self):
        """The comment is not the guard, but it is why the next person does
        not delete the guard. Both scripts must keep stating it."""
        for rel, text in self._sources():
            lowered = text.lower()
            self.assertIn("career", lowered,
                          f"{rel} no longer explains that vsPlayer returns "
                          "career totals -- restore the reasoning beside the "
                          "call")
            self.assertTrue(
                "as-of" in lowered or "as of" in lowered,
                f"{rel} no longer states that the endpoint has no as-of "
                "parameter")


if __name__ == "__main__":
    unittest.main()
