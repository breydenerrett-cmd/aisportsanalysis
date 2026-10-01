"""api/meta.py: GET /meta -- called directly, same reasoning as
test_api_health.py's module docstring (no TestClient/HTTP layer here).
"""

from __future__ import annotations

import re
import unittest
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from src.analysis.disclaimers import BETA_DISCLAIMER


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class GetMetaTests(unittest.TestCase):
    def test_shape(self):
        from api.meta import get_meta
        data = get_meta()
        self.assertIn("version", data)
        self.assertIn("product", data)
        self.assertIn("disclaimer", data)
        self.assertIn("brand", data)

    def test_brand_is_the_working_brand_marked_temporary(self):
        """Per Brey's 2026-09-01 decision: LINEHOUND is a working brand,
        not a final legal/trademark name -- `temporary` must stay True
        until trademark/domain clearance completes and Brey says
        otherwise."""
        from api.meta import get_meta
        data = get_meta()
        self.assertEqual(data["brand"], {"name": "Linehound", "temporary": True})

    def test_disclaimer_matches_the_shared_accessor(self):
        from api.meta import get_meta
        data = get_meta()
        self.assertEqual(data["disclaimer"]["id"], "beta-v1")
        self.assertIs(data["disclaimer"]["temporary"], True)
        self.assertIs(data["disclaimer"]["requires_final_legal_review"], True)
        self.assertEqual(data["disclaimer"]["text"], BETA_DISCLAIMER)

    def test_product_one_liner_has_no_tout_vocabulary(self):
        from api.meta import PRODUCT_ONE_LINER
        text = PRODUCT_ONE_LINER.lower()
        for banned in ("+ev", "true line", "true probability", "true odds",
                       "free money", "guaranteed", "sure thing"):
            self.assertNotIn(banned, text)
        self.assertNotRegex(text, r"\ba\s+lock\b")
        # "edge"/"guarantee" may appear only negated -- here they are
        # negated ("not ... guarantees") or absent entirely.
        for m in re.finditer(r"\bedges?\b", text):
            window = text[max(0, m.start() - 40):m.start()]
            self.assertRegex(window, r"\b(no|not|never|nothing)\b")

    def test_version_falls_back_to_dev_when_git_unavailable(self):
        """Reimport-free check: _read_version() in isolation, with the
        subprocess call forced to fail the way a git-less built container
        (deploy/Dockerfile COPYs source, no .git dir) would fail it."""
        import api.meta as meta_mod
        with mock.patch.object(meta_mod.subprocess, "run",
                               side_effect=FileNotFoundError("no git")):
            self.assertEqual(meta_mod._read_version(), "dev")

    def test_version_falls_back_to_dev_on_nonzero_returncode(self):
        import api.meta as meta_mod

        class _FakeResult:
            returncode = 128
            stdout = ""

        with mock.patch.object(meta_mod.subprocess, "run",
                               return_value=_FakeResult()):
            self.assertEqual(meta_mod._read_version(), "dev")

    def test_version_uses_git_describe_output_when_available(self):
        import api.meta as meta_mod

        class _FakeResult:
            returncode = 0
            stdout = "v0.3.0-2-gabc1234\n"

        with mock.patch.object(meta_mod.subprocess, "run",
                               return_value=_FakeResult()):
            self.assertEqual(meta_mod._read_version(), "v0.3.0-2-gabc1234")

    def test_app_version_is_a_nonempty_string(self):
        """The module-level constant read once at import: whatever this
        checkout's real git state is, it must never be empty or the
        fallback string with no meaning attached."""
        from api.meta import APP_VERSION
        self.assertIsInstance(APP_VERSION, str)
        self.assertTrue(APP_VERSION)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class RecordIsBuiltOncePerLedgerState(unittest.TestCase):
    """/meta is on every page load; the landing page waits on it for the
    record and for the right button. Measured 5.7 to 10.2 s on the staging
    box on 2026-10-01 because every request re-read and re-verified every
    card ledger three times."""

    def setUp(self):
        from api import meta as meta_mod
        self.meta = meta_mod
        meta_mod.reset_record_cache_for_tests()
        self.addCleanup(meta_mod.reset_record_cache_for_tests)
        self.calls = 0
        for name, value in (("_effective_record", lambda: {"sports": {}}),
                            ("_research_counts", lambda: {}),
                            ("_card_record", self._card_record)):
            patcher = mock.patch.object(meta_mod, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _card_record(self):
        self.calls += 1
        return {"days": self.calls}

    def _signature(self, value):
        patcher = mock.patch.object(self.meta, "_ledger_signature", lambda: value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher

    def test_a_second_request_does_not_rebuild(self):
        self._signature(("state-1",))
        first = self.meta.get_meta()
        second = self.meta.get_meta()
        self.assertEqual(self.calls, 1)
        self.assertEqual(first["card_record"], second["card_record"])

    def test_a_changed_ledger_is_picked_up_on_the_next_request(self):
        state = {"sig": ("state-1",)}
        patcher = mock.patch.object(self.meta, "_ledger_signature", lambda: state["sig"])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(self.meta.get_meta()["card_record"], {"days": 1})
        state["sig"] = ("state-2",)          # a settlement was appended
        self.assertEqual(self.meta.get_meta()["card_record"], {"days": 2})
        self.assertEqual(len(self.meta._RECORD_PARTS), 1)   # no growth

    def test_the_signature_follows_the_real_ledger_files(self):
        import os
        import tempfile
        from src.appstate import card_ledger
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cards_v2.jsonl")
            open(path, "w").close()
            with mock.patch.object(card_ledger, "CARD_STORE_V2", path):
                before = self.meta._ledger_signature()
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write("{}" + chr(10))
                after = self.meta._ledger_signature()
        self.assertNotEqual(before, after)

    def test_billing_state_is_never_cached(self):
        self._signature(("state-1",))
        with mock.patch.object(self.meta, "_billing_summary", lambda: {"checkout": "off"}):
            self.assertEqual(self.meta.get_meta()["billing"]["checkout"], "off")
        with mock.patch.object(self.meta, "_billing_summary", lambda: {"checkout": "on"}):
            self.assertEqual(self.meta.get_meta()["billing"]["checkout"], "on")


if __name__ == "__main__":
    unittest.main()
