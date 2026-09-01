"""Banned-vocabulary tripwire for docs/CONTENT_LANDING.md.

Applies the same scan `tests/test_customer_language.py` runs over
src/analysis and src/report to the draft landing-page content, so tout
vocabulary and fabricated-confidence language cannot ship in copy either.
"""

import pathlib
import re
import unittest

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENT_FILE = ROOT / "docs" / "CONTENT_LANDING.md"


def _violations_in(text, where):
    found = []
    for pattern, label in HARD_BANNED:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(f"{where}: hard-banned {label!r} in {text[:90]!r}")
    for pattern, label in NEGATION_ONLY:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            window = text[max(0, m.start() - 90):m.start()]
            if not NEGATORS.search(window):
                found.append(
                    f"{where}: {label!r} affirmed (no negation in the "
                    f"preceding window) in {text[:120]!r}")
    return found


class ContentLandingLanguageScan(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(CONTENT_FILE.exists(),
                         f"{CONTENT_FILE} not found")

    def test_no_banned_language_in_content_landing(self):
        text = CONTENT_FILE.read_text(encoding="utf-8")
        # Scan paragraph by paragraph (blank-line-separated blocks), the
        # markdown analogue of the source scanner's per-string-literal
        # scope — a soft-wrapped sentence spans several raw lines, and a
        # negator earlier in the same paragraph should still count.
        paragraphs = re.split(r"\n\s*\n", text)
        violations = []
        for idx, para in enumerate(paragraphs, start=1):
            violations.extend(
                _violations_in(para, f"docs/CONTENT_LANDING.md paragraph {idx}"))
        self.assertEqual(violations, [],
                         "banned customer language in landing content:\n"
                         + "\n".join(violations))

    def test_never_calls_price_improvement_ev(self):
        text = CONTENT_FILE.read_text(encoding="utf-8").lower()
        for banned in ("expected value", "roi", "pays for itself",
                       "beat the books"):
            self.assertNotIn(banned, text,
                             f"{banned!r} must never appear in landing copy")

    def test_late_move_never_called_clv(self):
        text = CONTENT_FILE.read_text(encoding="utf-8")
        # A disclaimer ("late_move is never described as ... CLV") is fine;
        # what's forbidden is late_move being AFFIRMED as CLV with no
        # negator between the two mentions.
        for m in re.finditer(r"late[_ ]move", text, re.IGNORECASE):
            window = text[m.start():m.start() + 200]
            clv_pos = window.upper().find("CLV")
            if clv_pos == -1:
                continue
            between = window[:clv_pos]
            self.assertTrue(
                NEGATORS.search(between),
                f"late_move linked to CLV with no negator in between: "
                f"{window[:120]!r}")


if __name__ == "__main__":
    unittest.main()
