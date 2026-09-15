"""Structural tests for web/js/tennis.js."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


class TennisBoardWebStructure(unittest.TestCase):
    """Tennis board web module structure."""

    def test_tennis_js_exports_render_function(self):
        """web/js/tennis.js exports renderTennisBoard."""
        root = Path(__file__).resolve().parent.parent
        tennis_js = root / "web" / "js" / "tennis.js"

        self.assertTrue(tennis_js.exists(), "web/js/tennis.js does not exist")

        content = tennis_js.read_text(encoding="utf-8")

        # Check for export
        self.assertIn("export", content)
        self.assertIn("renderTennisBoard", content)

    def test_tennis_js_imports_resolve(self):
        """All imports in web/js/tennis.js point to existing files."""
        root = Path(__file__).resolve().parent.parent
        tennis_js = root / "web" / "js" / "tennis.js"
        web_js = root / "web" / "js"

        content = tennis_js.read_text(encoding="utf-8")

        # Find all imports
        static_imports = re.findall(
            r'^\s*(?:import|export)\b[^;]*?\bfrom\s+["\'](\./[^"\']+)["\']',
            content, re.MULTILINE)
        dynamic_imports = re.findall(
            r'\bimport\(\s*["\'](\./[^"\']+)["\']\s*\)',
            content)

        all_imports = sorted(set(static_imports + dynamic_imports))

        missing = []
        for target in all_imports:
            if not (web_js / target).is_file():
                missing.append(target)

        self.assertEqual(missing, [],
                        f"tennis.js imports files that do not exist: {missing}")

    def test_tennis_js_contains_no_banned_words(self):
        """Tennis.js contains no banned customer language."""
        root = Path(__file__).resolve().parent.parent
        tennis_js = root / "web" / "js" / "tennis.js"

        content = tennis_js.read_text(encoding="utf-8")

        # Banned words (case-insensitive strings/comments)
        banned_patterns = [
            r"\b(?:edge|edges|guaranteed?|lock|sure\s+thing|can't?\s+lose)\b",
            r"\bwin[- ]probabilit\w*",
            r"\bmodel[- ]probabilit\w*",
            r"\bexpected[- ]value",
            r"\+\s*EV\b",
            r"\btrue\s+line\b",
        ]

        violations = []
        for pattern in banned_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                # Skip if in a negation context
                start = max(0, match.start() - 90)
                window = content[start:match.start()]
                if not re.search(
                    r"\b(no|not|none|never|nothing|without)\b",
                    window, re.IGNORECASE):
                    violations.append(f"Found {match.group()} at position {match.start()}")

        self.assertEqual(violations, [],
                        f"tennis.js contains banned language: {violations}")

    def test_tennis_js_notice_text_correct(self):
        """The notice in tennis.js matches the approved text."""
        root = Path(__file__).resolve().parent.parent
        tennis_js = root / "web" / "js" / "tennis.js"

        content = tennis_js.read_text(encoding="utf-8")

        expected_notice = (
            "Research only. No tennis picks until results grading is connected.")

        self.assertIn(expected_notice, content,
                     "Tennis.js does not contain the approved notice text")


if __name__ == "__main__":
    unittest.main()
