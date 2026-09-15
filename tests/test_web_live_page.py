"""Tests for web/js/live.js"""

import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class LiveJSImports(unittest.TestCase):
    """live.js exports renderLive and all imports resolve."""

    def test_live_js_exports_render_live(self):
        """web/js/live.js exports a renderLive function."""
        live_js = ROOT / "web" / "js" / "live.js"
        self.assertTrue(live_js.exists(), f"{live_js} does not exist")

        content = live_js.read_text(encoding="utf-8")
        # Check for export declaration
        self.assertIn("export async function renderLive", content,
                     "live.js does not export renderLive")

    def test_live_js_contains_banner_notice(self):
        """web/js/live.js contains the banner sentence."""
        live_js = ROOT / "web" / "js" / "live.js"
        content = live_js.read_text(encoding="utf-8")

        # Banner should mention "internal testing" and "No alerts"
        self.assertIn("internal testing", content.lower(),
                     "live.js does not mention internal testing")
        self.assertIn("no alerts", content.lower(),
                     "live.js does not mention alerts")

    def test_live_js_contains_research_chip(self):
        """web/js/live.js contains 'research, not a pick' phrase."""
        live_js = ROOT / "web" / "js" / "live.js"
        content = live_js.read_text(encoding="utf-8")

        self.assertIn("research, not a pick", content.lower(),
                     "live.js does not contain 'research, not a pick'")

    def test_live_js_fetches_correct_api_endpoint(self):
        """web/js/live.js fetches from /live endpoint."""
        live_js = ROOT / "web" / "js" / "live.js"
        content = live_js.read_text(encoding="utf-8")

        self.assertIn("/live", content,
                     "live.js does not fetch from /live endpoint")

    def test_live_js_has_no_banned_customer_language(self):
        """live.js does not contain banned words."""
        live_js = ROOT / "web" / "js" / "live.js"
        content = live_js.read_text(encoding="utf-8")

        # Patterns for banned words (simplified from test_customer_language.py)
        banned = [
            (r"\bedge\b", "edge"),
            (r"\bwin[- ]probabilit", "win probability"),
            (r"\bmodel[- ]probabilit", "model probability"),
            (r"\bloc?ck\b", "lock"),
            (r"\bguarantee", "guarantee"),
            (r"\+\s*EV", "+EV"),
        ]

        violations = []
        for pattern, label in banned:
            # Exclude from docstrings and comments
            if re.search(pattern, content, re.IGNORECASE):
                # Check if it's in a comment or docstring
                lines = content.split("\n")
                for i, line in enumerate(lines, 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        # Simple heuristic: skip lines that look like comments
                        if not line.strip().startswith("//") and \
                           not line.strip().startswith("/*") and \
                           not line.strip().startswith("*"):
                            violations.append(
                                f"Line {i}: Contains {label!r}: {line.strip()[:80]}")

        self.assertEqual([], violations,
                        f"Banned language found in live.js:\n" + "\n".join(violations))


class LiveJSStructure(unittest.TestCase):
    """live.js has the correct structure."""

    def test_app_includes_live_router_with_paid_dependency(self):
        """api/app.py includes the live router with _authed_paid dependency."""
        app_py = ROOT / "api" / "app.py"
        content = app_py.read_text(encoding="utf-8")

        # Check for import
        self.assertIn("from api.live import router as live_router", content,
                     "app.py does not import live_router")

        # Check for registration with dependency
        self.assertIn("app.include_router(live_router, dependencies=_authed_paid)",
                     content,
                     "app.py does not register live_router with _authed_paid")


if __name__ == "__main__":
    unittest.main()
