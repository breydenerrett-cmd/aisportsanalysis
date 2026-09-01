"""Banned-vocabulary tripwire for the customer-facing content docs:
docs/CONTENT_LANDING.md, docs/RETENTION_EMAILS.md, docs/ACQUISITION_ASSETS.md,
docs/FIRST_CUSTOMER_PLAYBOOK.md.

Applies the same scan `tests/test_customer_language.py` runs over
src/analysis and src/report to every draft content package, so tout
vocabulary and fabricated-confidence language cannot ship in copy of any
kind -- landing page, retention email, outreach script, or the operational
playbook that quotes/sends all three alike.
"""

import pathlib
import re
import unittest

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENT_FILE = ROOT / "docs" / "CONTENT_LANDING.md"
RETENTION_EMAILS_FILE = ROOT / "docs" / "RETENTION_EMAILS.md"
ACQUISITION_ASSETS_FILE = ROOT / "docs" / "ACQUISITION_ASSETS.md"
FIRST_CUSTOMER_PLAYBOOK_FILE = ROOT / "docs" / "FIRST_CUSTOMER_PLAYBOOK.md"


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


class RetentionAndAcquisitionLanguageScan(unittest.TestCase):
    """The same tripwire, extended to the retention-email and
    founding-user-acquisition drafts (this task's own deliverables) --
    outreach scripts and email copy are exactly as customer-facing as the
    landing page, and get no vocabulary exemption for being shorter or
    less formal.
    """

    FILES = (RETENTION_EMAILS_FILE, ACQUISITION_ASSETS_FILE,
             FIRST_CUSTOMER_PLAYBOOK_FILE)

    def test_files_exist(self):
        for path in self.FILES:
            self.assertTrue(path.exists(), f"{path} not found")

    def test_no_banned_language(self):
        violations = []
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            # Same paragraph-scoped scan as ContentLandingLanguageScan --
            # see that class's comment for why paragraph, not line or file.
            paragraphs = re.split(r"\n\s*\n", text)
            for idx, para in enumerate(paragraphs, start=1):
                violations.extend(
                    _violations_in(para, f"{path.name} paragraph {idx}"))
        self.assertEqual(violations, [],
                         "banned customer language in retention/acquisition "
                         "content:\n" + "\n".join(violations))

    def test_never_calls_price_improvement_ev(self):
        for path in self.FILES:
            text = path.read_text(encoding="utf-8").lower()
            for banned in ("expected value", "roi", "pays for itself",
                           "beat the books"):
                self.assertNotIn(banned, text,
                                 f"{banned!r} must never appear in "
                                 f"{path.name}")

    def test_late_move_never_called_clv(self):
        # Same rule as ContentLandingLanguageScan.test_late_move_never_called_clv,
        # applied to all three docs -- none currently mentions late_move,
        # but the check stays live so a future edit that adds one is caught
        # the same way it would be in CONTENT_LANDING.md.
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"late[_ ]move", text, re.IGNORECASE):
                window = text[m.start():m.start() + 200]
                clv_pos = window.upper().find("CLV")
                if clv_pos == -1:
                    continue
                between = window[:clv_pos]
                self.assertTrue(
                    NEGATORS.search(between),
                    f"{path.name}: late_move linked to CLV with no negator "
                    f"in between: {window[:120]!r}")


if __name__ == "__main__":
    unittest.main()
