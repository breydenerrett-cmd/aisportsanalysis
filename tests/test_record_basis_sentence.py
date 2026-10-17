"""The MLB record page states its basis in one sentence and shows the withdrawn
count beside the totals (2026-10-16, docs/research/loss_diagnosis/00_SYNTHESIS.md
facts 5 and 8, change 4).

THE DEFECT
----------
The same ledger could be read as "97-81" (every graded entry, 17 withdrawn
picks among them) or "16-17" (regular-season MAIN picks, the postseason shown
as "not counted"), and grading is at the best two-sided price although the
owner's 2026-09-21 ruling asked for the board average. Nothing on the page said
which. Now the server sends one sentence (`record_basis`) and the page draws it
verbatim under the totals, with the withdrawn count as a tile beside them.

WHAT IS PINNED
--------------
  * api/card.py's sentence says all three facts: best price on markets quoted on
    both sides, postseason not counted, withdrawn counted separately; it is ONE
    sentence in plain words (the site-wide wording sweeps pass);
  * GET /card/record (MLB v2) carries it and keeps `withdrawn` from the ledger;
  * the page, run under node, draws the sentence exactly once and a WITHDRAWN
    tile with the payload's own number; with no `record_basis` or no
    `withdrawn` in the payload it draws neither (honest absence); the V1 shadow
    record and other sports never get the tile.

Route tests skip where FastAPI is absent; node tests skip without node.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_customer_language import _violations_in
from tests.test_example_accounts_page import HARNESS, HISTORY, JS, RECORD
from tests.test_no_nothing_clears_the_bar import BANNED_JARGON, BANNED_PHRASES, _normalise

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

if HAS_FASTAPI:
    from api import card as card_api

SENTENCE = ("Each pick is graded at the best price any book offered for it when we quoted it, "
            "on markets that had a price on both sides; postseason games are not counted, and "
            "withdrawn picks are counted separately and are not in these totals.")


class TheSentence(unittest.TestCase):
    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def setUp(self):
        self.text = card_api.RECORD_BASIS_SENTENCE

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_it_is_the_agreed_sentence(self):
        self.assertEqual(self.text, SENTENCE)

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_it_says_the_three_things(self):
        lowered = self.text.lower()
        self.assertIn("best price", lowered)
        self.assertIn("both sides", lowered)
        self.assertIn("postseason games are not counted", lowered)
        self.assertIn("withdrawn picks are counted separately", lowered)

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_it_is_one_sentence_in_plain_words(self):
        self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", self.text)), 1, self.text)
        for dash in (chr(0x2014), chr(0x2013), "--"):
            self.assertNotIn(dash, self.text)
        normal = _normalise(self.text)
        for phrase in BANNED_PHRASES + BANNED_JARGON:
            self.assertNotIn(phrase, normal, phrase)
        self.assertEqual(_violations_in(self.text, "record basis"), [])


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRouteCarriesIt(unittest.TestCase):
    def setUp(self):
        card_api.reset_public_cache_for_tests()
        self.addCleanup(card_api.reset_public_cache_for_tests)

    def record(self, **kwargs):
        return card_api.get_card_record(sport="mlb", **kwargs)

    def test_the_default_mlb_record_carries_the_sentence_and_the_withdrawn_count(self):
        payload = self.record()
        self.assertEqual(payload["rule"], "v2")
        self.assertEqual(payload["record_basis"], SENTENCE)
        self.assertIsInstance(payload["withdrawn"], int)
        self.assertGreaterEqual(payload["withdrawn"], 0)

    def test_the_withdrawn_count_is_the_ledgers_not_a_second_count(self):
        from src.appstate import card_ledger
        self.assertEqual(self.record()["withdrawn"], card_ledger.record_v2()["withdrawn"])

    def test_other_sports_and_the_shadow_rule_carry_no_basis_sentence(self):
        for kwargs in ({"sport": "mma"}, {"sport": "nfl"}):
            with self.subTest(**kwargs):
                card_api.reset_public_cache_for_tests()
                self.assertNotIn("record_basis", card_api.get_card_record(**kwargs))
        card_api.reset_public_cache_for_tests()
        self.assertNotIn("record_basis", card_api.get_card_record(sport="mlb", rule="v1"))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ThePageDrawsIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        marker = '  out.hasHost = hook(container, "record-accounts-host").length;'
        assert marker in HARNESS
        extra = (marker + '\n  out.basisTexts = hook(container, "record-basis").map((n) => n.textContent);'
                 '\n  out.pageText = text(container);')
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS.replace(marker, extra), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def page(self, record, *, options=None):
        scenario = {"kind": "page", "record": record, "history": HISTORY,
                    "accounts": {"accounts": []}, "options": options or {}, "money": [0]}
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name,
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2500:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def test_the_sentence_is_drawn_once_verbatim(self):
        out = self.page(dict(RECORD, record_basis=SENTENCE, withdrawn=17))
        self.assertEqual(out["basisTexts"], [SENTENCE])
        self.assertEqual(out["pageText"].count(SENTENCE), 1)

    def test_the_withdrawn_count_is_a_tile_beside_the_totals(self):
        out = self.page(dict(RECORD, record_basis=SENTENCE, withdrawn=17))
        text = out["pageText"]
        self.assertIn("WITHDRAWN (NOT COUNTED)", text)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        at = lines.index("WITHDRAWN (NOT COUNTED)")
        self.assertIn("17", lines[at - 1:at + 2])
        # beside the totals: the same tile row as the record's other figures
        self.assertLess(abs(at - lines.index("DAYS SETTLED")), 4, lines[at - 4:at + 4])

    def test_zero_withdrawn_is_shown_as_zero_when_the_server_measured_it(self):
        out = self.page(dict(RECORD, record_basis=SENTENCE, withdrawn=0))
        self.assertIn("WITHDRAWN (NOT COUNTED)", out["pageText"])

    def test_no_sentence_and_no_count_from_an_older_server_draws_neither(self):
        out = self.page(dict(RECORD))
        self.assertEqual(out["basisTexts"], [])
        self.assertNotIn("WITHDRAWN (NOT COUNTED)", out["pageText"])
        self.assertNotIn("withdrawn picks are counted separately", out["pageText"])

    def test_a_blank_sentence_draws_nothing(self):
        out = self.page(dict(RECORD, record_basis="   ", withdrawn=3))
        self.assertEqual(out["basisTexts"], [])

    def test_the_old_rule_record_gets_no_withdrawn_tile(self):
        out = self.page(dict(RECORD, rule="v1", withdrawn=5), options={"rule": "v1"})
        self.assertNotIn("WITHDRAWN (NOT COUNTED)", out["pageText"])


class TheSourceKeepsToTheRules(unittest.TestCase):
    """No node needed: the page source draws the server's sentence and does
    not compose a basis of its own."""

    def setUp(self):
        self.js = (Path(__file__).resolve().parent.parent / "web" / "js" / "cardrecord.js"
                   ).read_text(encoding="utf-8")

    def test_the_page_reads_record_basis_and_writes_no_sentence_of_its_own(self):
        self.assertIn("record.record_basis", self.js)
        self.assertNotIn("best price any book offered", self.js)

    def test_the_tile_is_gated_on_a_measured_number(self):
        self.assertIn('typeof record.withdrawn === "number"', self.js)


if __name__ == "__main__":
    unittest.main()
