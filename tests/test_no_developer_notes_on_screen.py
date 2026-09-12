"""No developer note may render as customer-facing text.

THE DEFECT
----------
web/js/betcheck.js rendered a chip reading **"NEVER EMPTY BY CONSTRUCTOR"**
on the live site, under section 04 COUNTERARGUMENT. That is one developer's
note to another about an invariant in the function that draws it. A reader
has no idea what a constructor is and no reason to care.

Found 2026-09-12 by opening the deployed site and filling in the Bet Check
form -- not by any test, and not by reading the code, because in the source
it sits on a line that looks exactly like every other label.

WHAT THIS SCANS
---------------
Only strings that REACH A READER: the `text:` of an element or chip. Comments
and identifiers are where this vocabulary belongs and are deliberately left
alone.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

# Vocabulary that belongs in source and never on a screen. Each entry is the
# word plus why a reader cannot use it.
#
# MATCHED ON WORD BOUNDARIES. The first draft matched substrings and flagged
# "fi(nan)cial", "unannou(nan)ced" and "INDEPE(nden)T" -- a scanner that
# cries wolf gets switched off, which is worse than no scanner.
#
# "null" is deliberately NOT here. A "null baseline" is this product's own
# statistical vocabulary for a control system that bets at random, it appears
# on the performance surfaces on purpose, and banning it would force real
# domain language off the page to satisfy a lint.
DEVELOPER_WORDS = (
    ("constructor", "a code concept, not a fact about the bet"),
    ("by construction", "an argument about the code, not about the game"),
    ("invariant", "internal jargon"),
    ("undefined", "a programming value"),
    ("typeerror", "an exception class"),
    ("traceback", "a stack trace"),
    ("payload", "how the data travelled, not what it says"),
    ("endpoint", "plumbing"),
    ("api response", "plumbing"),
    ("todo", "an unfinished note"),
    ("fixme", "an unfinished note"),
    ("lorem ipsum", "filler that shipped"),
)

# `text:` values -- the strings el() and block() put in front of a reader.
TEXT_VALUE = re.compile(r"""(?:^|[\s{,])text:\s*(["'`])(.*?)\1""", re.S)

# `${...}` is an interpolation: the VALUE lands on screen, not the expression.
# Leaving them in flagged every `${payload.checked_games}` in the repo as
# though the word "payload" were being shown to a reader.
INTERPOLATION = re.compile(r"\$\{[^}]*\}")


def _rendered_strings(path: Path):
    """(line number, string) for every literal handed to a `text:` field.

    Interpolated expressions are stripped first -- only the words a reader
    actually sees are scanned.
    """
    source = path.read_text(encoding="utf-8")
    for match in TEXT_VALUE.finditer(source):
        line_no = source.count("\n", 0, match.start()) + 1
        yield line_no, INTERPOLATION.sub(" ", match.group(2))


class NoDeveloperVocabularyOnScreen(unittest.TestCase):
    def test_no_rendered_string_speaks_to_a_developer(self):
        offenders = []
        for path in sorted(WEB_JS.glob("*.js")):
            for line_no, text in _rendered_strings(path):
                lowered = text.lower()
                for word, why in DEVELOPER_WORDS:
                    if re.search(rf"\b{re.escape(word)}\b", lowered):
                        offenders.append(
                            f"{path.name}:{line_no}: {word!r} ({why}) "
                            f"in {text[:70]!r}")
        self.assertEqual(
            offenders, [],
            "developer vocabulary rendered to a reader:\n"
            + "\n".join(offenders))

    def test_the_scanner_actually_finds_rendered_strings(self):
        """Guard against the scan silently matching nothing.

        A regex that stops matching turns this file green forever while
        checking nothing, which is worse than not having it.
        """
        found = list(_rendered_strings(WEB_JS / "betcheck.js"))
        self.assertGreater(len(found), 20,
                           "the text: scan found almost nothing -- it has "
                           "probably stopped matching")

    def test_the_scanner_would_catch_the_original_defect(self):
        """The exact string that shipped, run through the same check."""
        shipped = "NEVER EMPTY BY CONSTRUCTOR"
        hits = [w for w, _why in DEVELOPER_WORDS if w in shipped.lower()]
        self.assertTrue(hits, "the word list would have missed the defect "
                              "it was written for")


if __name__ == "__main__":
    unittest.main()
