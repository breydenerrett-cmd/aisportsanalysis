"""A missing research registry is an absence, never a zero.

On 2026-09-12 the staging demo told every visitor "0 pre-registered
research ideas have been tested" and "0 hypotheses pre-registered ... zero
surviving". The deployed image had no data/research/ directory, and
`public_research_counts` walked a file that did not exist and counted
nothing. Zero is a claim about the research programme; the truth was that
the container could not see it.

Three layers, each pinned here: the registry raises on a missing file,
/meta serves nulls (which the pages read as "leave the fallback copy"),
and src.analysis falls back to its last-known figures with `source`
saying so.
"""

from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path

from src.research import alpha_registry
# Imported here, BEFORE any test patches the registry path: src.analysis
# computes its counts once at import, and the first import of it happening
# inside a patched window handed every later test module the last-known
# fallback (caught by tests/test_research_count_is_computed.py failing only
# when run after this file).
from src import analysis  # noqa: F401


class TheRegistryRaisesOnAMissingFile(unittest.TestCase):

    def test_public_counts_raise_rather_than_report_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "alpha_registry.jsonl"
            with self.assertRaises(FileNotFoundError):
                alpha_registry.public_research_counts(missing)

    def test_an_empty_but_present_file_is_genuinely_zero(self):
        """The distinction the fix rests on: a file with no rows IS zero."""
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "alpha_registry.jsonl"
            empty.write_text("", encoding="utf-8")
            counts = alpha_registry.public_research_counts(empty)
        self.assertEqual(counts["hypotheses"], 0)
        self.assertEqual(counts["read"], 0)


class AWithdrawnVerdictIsNotARead(unittest.TestCase):
    """V3:transaction_first_seen carries a "withdrawn" verdict whose own
    note says no result was read -- below its floor, still accumulating.
    `public_research_counts` counted it as read (37) because a verdict row
    existed; an independent review caught it on 2026-09-12. The rule is
    the one `total_searched` already applies: NOT_READ_RESULTS are not
    reads."""

    def _registry(self, tmp, verdict_result):
        path = Path(tmp) / "alpha_registry.jsonl"
        alpha_registry.register({
            "kind": "hypothesis", "id": "T1:x:h2h", "family": "T1",
            "market": "h2h", "sport": "mlb",
            "registered_utc": "2026-09-01T00:00:00+00:00",
            "data_window": {"discovery": "2026-08", "replication": None,
                            "sealed_untouched": True},
            "alpha_declared": 0.05, "source_doc": "docs/x.md",
        }, path)
        if verdict_result is not None:
            alpha_registry.record_verdict({
                "kind": "verdict", "id": "T1:x:h2h", "read_utc": "2026-09-02",
                "result": verdict_result}, path)
        return path

    def test_withdrawn_and_below_floor_count_as_pending(self):
        for result in sorted(alpha_registry.NOT_READ_RESULTS):
            with tempfile.TemporaryDirectory() as tmp:
                counts = alpha_registry.public_research_counts(self._registry(tmp, result))
            self.assertEqual((counts["read"], counts["pending"]), (0, 1), result)

    def test_a_null_verdict_is_a_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts = alpha_registry.public_research_counts(self._registry(tmp, "null"))
        self.assertEqual((counts["read"], counts["pending"]), (1, 0))

    def test_no_verdict_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts = alpha_registry.public_research_counts(self._registry(tmp, None))
        self.assertEqual((counts["read"], counts["pending"]), (0, 1))

    def test_the_real_registry_agrees_with_total_searched_on_what_was_read(self):
        """The two readers of the same file must agree on the read count for
        hypothesis rows, whatever the file holds tonight."""
        registry = alpha_registry.AlphaRegistry(None)
        latest = registry._latest_verdict_results()  # noqa: SLF001
        expected = sum(
            1 for row in registry._iter_raw()  # noqa: SLF001
            if row.get("kind") == "hypothesis"
            and latest.get(row.get("id")) is not None
            and latest.get(row.get("id")) not in alpha_registry.NOT_READ_RESULTS)
        self.assertEqual(alpha_registry.public_research_counts()["read"], expected)


class TheCallersTreatItAsUnknown(unittest.TestCase):

    def setUp(self):
        self._real = alpha_registry.DEFAULT_PATH
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        alpha_registry.DEFAULT_PATH = Path(self._tmp.name) / "missing.jsonl"
        self.addCleanup(setattr, alpha_registry, "DEFAULT_PATH", self._real)

    def test_meta_serves_nulls_not_zeros(self):
        try:
            from api import meta
        except ImportError:  # pragma: no cover - CI installs no fastapi
            self.skipTest("fastapi not installed")
        counts = meta._research_counts()
        self.assertIsNone(counts["hypotheses"])
        self.assertIsNone(counts["read"])
        self.assertIsNone(counts["surviving"])

    def test_analysis_falls_back_to_last_known_and_says_so(self):
        from src import analysis
        counts = analysis.research_counts()
        self.assertEqual(counts["source"], "last_known")
        self.assertEqual(counts["read"], analysis._LAST_KNOWN_HYPOTHESES)
        self.assertGreater(counts["read"], 0)


class TheImageCarriesTheRegistry(unittest.TestCase):
    """The deployment gap itself: deploy/Dockerfile must COPY the registry
    and .dockerignore must let it into the build context."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_dockerfile_copies_the_registry(self):
        text = (self.ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY data/research/alpha_registry.jsonl data/research/alpha_registry.jsonl", text)

    def test_dockerignore_admits_it(self):
        text = (self.ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("!data/research/", text)
        self.assertIn("!data/research/alpha_registry.jsonl", text)


if __name__ == "__main__":
    unittest.main()
