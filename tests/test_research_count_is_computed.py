"""One claim, one number, read from the registry.

WHY THIS FILE EXISTS
---------------------
The count of pre-registered hypotheses appeared in four places at three
different values:

  web/js/today.js       "27 hypotheses pre-registered ... zero surviving"
  web/js/betcheck.js    "Twenty-seven pre-registered hypotheses"  (a second,
                        independently worded copy)
  web/landing.html      "25 distinct ideas ... (35 counting every variant)",
                        twice
  the registry           40

So a prospect read one number on the page that sold them the subscription
and a different number the first time they opened the app. On a product
whose entire pitch is that it counts honestly, and whose customer-facing
copy is otherwise policed by two separate language tripwires.

The old constant defended itself in a comment: "Static constant, not
tonight's count" -- true, and exactly why it drifted. A number nobody
expects to change is a number nobody re-checks. The registry IS the closed
record.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"

# Files a customer reads. Not the whole tree: design mockups and docs are
# allowed to carry historical figures.
CUSTOMER_FACING = [
    WEB / "landing.html",
    WEB / "index.html",
    WEB / "js" / "today.js",
    WEB / "js" / "betcheck.js",
    WEB / "js" / "landing.js",
    WEB / "js" / "performance.js",
    WEB / "js" / "games.js",
]

# Spelled-out forms count too -- betcheck.js used "Twenty-seven", which no
# digit-based scan would ever have found.
WORD_NUMBERS = (
    "twenty-five", "twenty-six", "twenty-seven", "twenty-eight",
    "thirty-five", "forty", "forty-two",
)


def _prose(path):
    """Source with comments stripped. Every file here now documents this
    incident by name, quoting the old numbers, so a raw scan would fail on
    the explanation of the fix."""
    text = path.read_text(encoding="utf-8")
    out, in_block = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("/*", "<!--")):
            in_block = True
        if in_block:
            if "*/" in s or "-->" in s:
                in_block = False
            continue
        if s.startswith("//") or s.startswith("*"):
            continue
        out.append(line)
    return "\n".join(out)


class TheRegistryIsTheSource(unittest.TestCase):

    def test_the_helper_reads_the_registry(self):
        from src.research import alpha_registry
        counts = alpha_registry.public_research_counts()
        self.assertIsInstance(counts["hypotheses"], int)
        self.assertIsInstance(counts["surviving"], int)
        self.assertGreater(counts["hypotheses"], 0,
                           "the registry reports no hypotheses at all")

    def test_it_agrees_with_the_registry_test_suite(self):
        """tests/test_alpha_registry.py independently asserts the count.
        These two must not be able to disagree."""
        from src.research import alpha_registry
        counts = alpha_registry.public_research_counts()
        searched = alpha_registry.total_searched()
        self.assertEqual(searched["hypotheses"], counts["hypotheses"])

    def test_meta_serves_it(self):
        # CI runs this suite WITHOUT api/requirements.txt -- fastapi
        # lives only in api/'s dependencies (tests/test_api_boundary.py
        # exists to prove src/ never needs it). Skip rather than error,
        # so the api-less job stays green and still runs everything else
        # in this file.
        try:
            import fastapi  # noqa: F401
        except ImportError:
            self.skipTest('fastapi is not installed in this job')
        from api import meta as meta_api
        payload = meta_api.get_meta()
        self.assertIn("research", payload)
        self.assertIn("hypotheses", payload["research"])

    def test_meta_never_guesses_when_the_registry_is_unreadable(self):
        """/meta is hit on every page load and must not 500 because a file
        moved -- and must not invent a number either."""
        from unittest import mock
        # CI runs this suite WITHOUT api/requirements.txt -- fastapi
        # lives only in api/'s dependencies (tests/test_api_boundary.py
        # exists to prove src/ never needs it). Skip rather than error,
        # so the api-less job stays green and still runs everything else
        # in this file.
        try:
            import fastapi  # noqa: F401
        except ImportError:
            self.skipTest('fastapi is not installed in this job')
        from api import meta as meta_api
        with mock.patch("src.research.alpha_registry.public_research_counts",
                        side_effect=RuntimeError("gone")):
            payload = meta_api.get_meta()
        self.assertIsNone(payload["research"]["hypotheses"])


class ThePythonConstantsReadTheRegistryToo(unittest.TestCase):
    """The JS side was fixed first and the Python side kept drifting.

    On 2026-09-12 one Bet Check result said "41 pre-registered hypotheses"
    in block 07 (registry, via GET /meta) and "27 pre-registered hypotheses
    across four families" in block 10 (src/analysis/__init__.py's typed
    constant, via the bottom line's no-edge record). Same page, two counts.
    Five customer sentences read those constants: the Bet Check bottom line,
    the synthesis note, the Ranker banner, the dashboard and the archive.
    """

    def test_the_count_is_the_registry_count(self):
        from src import analysis
        from src.research import alpha_registry
        self.assertTrue(analysis.COUNTS_FROM_REGISTRY,
                        "src.analysis fell back to its last-known figures")
        self.assertEqual(analysis.HYPOTHESES_TESTED,
                         alpha_registry.public_research_counts()["hypotheses"])

    def test_the_family_count_is_the_registry_family_count(self):
        from src import analysis
        from src.research import alpha_registry
        families = {r.get("family") for r in alpha_registry.read_all()
                    if r.get("kind") == "hypothesis" and r.get("family")}
        self.assertEqual(analysis.HYPOTHESIS_FAMILIES, len(families))

    def test_the_words_match_the_numbers(self):
        from src import analysis
        self.assertEqual(analysis.HYPOTHESES_TESTED_WORD,
                         analysis.number_word(analysis.HYPOTHESES_TESTED).capitalize())
        self.assertEqual(analysis.HYPOTHESIS_FAMILIES_WORD,
                         analysis.number_word(analysis.HYPOTHESIS_FAMILIES))

    def test_number_words(self):
        from src.analysis import number_word
        self.assertEqual(number_word(4), "four")
        self.assertEqual(number_word(20), "twenty")
        self.assertEqual(number_word(27), "twenty-seven")
        self.assertEqual(number_word(41), "forty-one")
        self.assertEqual(number_word(100), "100")

    def test_the_last_known_fallback_is_not_stale(self):
        """The fallback is only for a container with no data/ tree, but a
        stale fallback is the old bug waiting for that container."""
        from src import analysis
        from src.research import alpha_registry
        self.assertEqual(analysis._LAST_KNOWN_HYPOTHESES,
                         alpha_registry.public_research_counts()["hypotheses"],
                         "bump _LAST_KNOWN_HYPOTHESES in src/analysis/__init__.py")

    def test_the_bet_check_bottom_line_carries_the_registry_count(self):
        from src import analysis
        from src.analysis import betcheck
        self.assertIn(f"{analysis.HYPOTHESES_TESTED} pre-registered",
                      betcheck._NO_EDGE_DISCLAIMER)
        self.assertIn(f"across {analysis.HYPOTHESIS_FAMILIES_WORD} families",
                      betcheck._NO_EDGE_DISCLAIMER)


class NoCustomerFileHardcodesIt(unittest.TestCase):

    def test_no_spelled_out_counts_in_customer_prose(self):
        offenders = []
        for path in CUSTOMER_FACING:
            if not path.is_file():
                continue
            prose = _prose(path).lower()
            for word in WORD_NUMBERS:
                if re.search(rf"{word}\s+(pre-registered|hypothes|distinct)",
                             prose):
                    offenders.append(f"{path.name}: {word!r}")
        self.assertEqual(
            [], offenders,
            "a hypothesis count is spelled out in customer copy; read it "
            "from GET /meta's `research` block instead (meta.js's "
            "fillResearchCount, or landing.js's fillResearchCounts)")

    def test_no_numeric_count_asserted_next_to_the_claim(self):
        """A digit immediately before "hypotheses pre-registered" or
        "pre-registered hypotheses" is the exact shape that drifted."""
        offenders = []
        pattern = re.compile(
            r"\b\d{1,3}\b[^.<>\n]{0,40}?(hypothes\w*\s+pre-registered"
            r"|pre-registered\s+hypothes\w*|distinct\s+(research\s+)?"
            r"(ideas|hypothes\w*))", re.IGNORECASE)
        for path in CUSTOMER_FACING:
            if not path.is_file():
                continue
            for match in pattern.finditer(_prose(path)):
                # The landing page's no-JS fallback is allowed, but only
                # inside the hook that landing.js overwrites.
                context = _prose(path)[max(0, match.start() - 120):match.end()]
                if 'data-hook="research-count"' in context:
                    continue
                offenders.append(f"{path.name}: {match.group(0)[:60]!r}")
        self.assertEqual(
            [], offenders,
            "a hypothesis count is hardcoded beside the claim it describes")

    def test_the_landing_fallback_matches_the_registry(self):
        """The no-JS fallback is real copy a visitor can read. It is allowed
        to be a literal -- it is not allowed to be a WRONG literal."""
        from src.research import alpha_registry
        expected = str(alpha_registry.public_research_counts()["hypotheses"])
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        fallbacks = re.findall(
            r'data-hook="research-count"[^>]*>([^<]*)<', html)
        self.assertTrue(fallbacks, "landing.html has no research-count hook")
        for value in fallbacks:
            self.assertEqual(
                expected, value.strip(),
                "landing.html's no-JS fallback count disagrees with the "
                "registry")


if __name__ == "__main__":
    unittest.main()
