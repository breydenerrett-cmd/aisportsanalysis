"""Guards Brey's 2026-09-01 branding decision: "Use LINEHOUND anywhere a
temporary customer-facing brand is required ... Do not buy/register the
final domain or make irreversible legal branding decisions until
trademark/domain clearance is completed."

This test only checks that the OLD placeholder ("[WORKING TITLE]") is gone
from customer-facing surfaces -- it does not assert LINEHOUND is a
permanent name (it explicitly is not; see api/meta.py's `brand.temporary`
and each doc's top-of-file working-brand note) and it does not touch
research/evidence docs or legal disclaimer copy, which stay name-neutral
by design (src/analysis/disclaimers.py, docs/RESEARCH_*, docs/RESULTS_*,
docs/EVOLAB_*, docs/COMMAND_CENTER.md) -- rebranding those before
trademark/domain clearance is exactly what this decision forbids.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PLACEHOLDER = "WORKING TITLE"

# Customer-facing surfaces this task branded -- see the task brief's SWEEP
# list. Anything not listed here (research/evidence docs, legal copy) is
# deliberately out of scope, per BOUNDARIES.
WEB_FILES = [
    REPO_ROOT / "web" / "index.html",
    REPO_ROOT / "web" / "landing.html",
]
CONTENT_DOCS = [
    REPO_ROOT / "docs" / "CONTENT_LANDING.md",
    REPO_ROOT / "docs" / "RETENTION_EMAILS.md",
    REPO_ROOT / "docs" / "ACQUISITION_ASSETS.md",
]


class NoLeftoverPlaceholderTests(unittest.TestCase):
    def test_web_html_has_no_working_title_placeholder(self):
        for path in WEB_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(PLACEHOLDER, text,
                              f"{path} still has the old placeholder")

    def test_content_docs_have_no_working_title_placeholder(self):
        for path in CONTENT_DOCS:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(PLACEHOLDER, text,
                              f"{path} still has the old placeholder")

    def test_web_carries_the_working_brand(self):
        for path in WEB_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertIn("LINEHOUND", text, f"{path} does not name the working brand")

    def test_content_docs_note_the_working_brand_is_temporary(self):
        # Every branded doc must say up front that this is temporary and
        # pending clearance -- so nobody downstream mistakes LINEHOUND for
        # a cleared, final name.
        for path in CONTENT_DOCS:
            text = path.read_text(encoding="utf-8")
            self.assertIn("pending trademark/domain clearance", text,
                          f"{path} is missing the temporary-brand note")


if __name__ == "__main__":
    unittest.main()
