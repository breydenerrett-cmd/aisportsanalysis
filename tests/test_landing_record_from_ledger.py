"""The landing page's record sentence reads the ledger, not a typed figure.

On 2026-09-12 web/landing.html said "2 wins, 1 loss. A second night has
graded since -- 9 picks, 7 wins, 2 losses. Across both: 9 wins, 3 losses."
True that morning; wrong the morning after the next settlement, on the page
whose pitch is that it counts honestly. The research count drifted the same
way (tests/test_research_count_is_computed.py). GET /meta now carries
`card_record` from src/appstate/card_ledger.record(), landing.js fills the
hook, and the markup's no-JS fallback names NO figure -- a sentence with no
number in it cannot go stale.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class TheLandingFallbackNamesNoFigure(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / "landing.html").read_text(encoding="utf-8")

    def test_the_hook_exists_once(self):
        self.assertEqual(self.html.count('data-hook="card-record"'), 1)

    def test_the_fallback_carries_no_running_total(self):
        fallback = re.search(r'data-hook="card-record"[^>]*>([^<]*)<', self.html)
        self.assertIsNotNone(fallback)
        text = fallback.group(1)
        self.assertNotRegex(text, r"\d", f"a figure in the no-JS fallback goes stale: {text!r}")
        self.assertIn("record page", text.lower())

    def test_no_typed_running_record_survives_anywhere_on_the_page(self):
        """The exact shape that drifted: "N wins, M losses" outside the
        first-night sentence (which is a dated historical fact)."""
        body = re.sub(r"<!--.*?-->", " ", self.html, flags=re.S)
        body = re.sub(r"<script\b.*?</script>", " ", body, flags=re.S)
        body = re.sub(r"<[^>]+>", " ", body)
        hits = [m.group(0) for m in re.finditer(r"\b\d+ wins?, \d+ loss(?:es)?\b", body)]
        self.assertEqual(hits, ["2 wins, 1 loss"],
                         "a running record is typed into the page; it belongs on /meta")


class LandingJsFillsItFromMeta(unittest.TestCase):
    def setUp(self):
        self.js = (WEB / "js" / "landing.js").read_text(encoding="utf-8")

    def test_it_reads_the_hook_and_meta(self):
        body = self.js.split("async function fillCardRecord(")[1].split("\nfunction ")[0]
        self.assertIn("[data-hook='card-record']", body)
        self.assertIn("meta.card_record", body)
        self.assertIn("fetchMeta()", body)

    def test_boot_calls_it(self):
        boot = self.js.split("function boot() {")[1]
        self.assertIn("fillCardRecord();", boot)

    def test_the_sentence_refuses_partial_records(self):
        """A null from /meta (unreadable ledger) must leave the fallback:
        the guard has to check every figure it prints, and days >= 1."""
        body = self.js.split("export function recordSentence(")[1].split("\n}\n")[0]
        for field in ("rec.wins", "rec.losses", "rec.days"):
            self.assertIn(f'typeof {field} !== "number"', body)
        self.assertIn("rec.days < 1", body)
        self.assertIn("return null", body)

    def test_the_sentence_reports_losses_and_voids(self):
        body = self.js.split("export function recordSentence(")[1].split("\n}\n")[0]
        self.assertIn('"losses"', body)
        self.assertIn('"voids"', body)
        self.assertIn('"pushes"', body)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class MetaServesTheLedgerRecord(unittest.TestCase):
    def test_meta_carries_the_ledgers_own_numbers(self):
        from api import meta as meta_api
        from src.appstate import card_ledger
        payload = meta_api.get_meta()
        rec = card_ledger.record()
        # profit_units added 2026-09-22 for the landing hero's proof panel.
        self.assertEqual(payload["card_record"],
                         {k: rec.get(k) for k in
                          ("days", "wins", "losses", "pushes", "voids", "profit_units")})

    def test_meta_never_guesses_when_the_ledger_is_unreadable(self):
        from api import meta as meta_api
        with mock.patch("src.appstate.card_ledger.record",
                        side_effect=RuntimeError("gone")):
            payload = meta_api.get_meta()
        self.assertEqual(payload["card_record"],
                         {"days": None, "wins": None, "losses": None,
                          "pushes": None, "voids": None, "profit_units": None})


if __name__ == "__main__":
    unittest.main()
