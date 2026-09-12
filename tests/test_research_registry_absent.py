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
