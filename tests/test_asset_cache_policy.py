"""The shell revalidates; the modules get a short window. Both on purpose.

WHY THIS FILE EXISTS
--------------------
This policy has now been wrong in both directions, and neither failure was
caught by a test.

TOO LOOSE (2026-09-07): with no explicit policy the browser cached js/css
heuristically off Last-Modified and served a stale web/js/motion.js beside
freshly deployed HTML. The fix was `no-cache` on everything.

TOO TIGHT (2026-09-10): `no-cache` means revalidate EVERY asset on EVERY
load, and this app has no build step -- roughly thirty separate ES module
files plus stylesheets. On the staging container, served one at a time by a
single shared CPU, the first API call did not fire until 2.9 seconds after
navigation, while the API calls themselves returned in about 150ms. The page
was not waiting on data; it was waiting to be allowed to ask for it.

The settlement is asymmetric on purpose and that asymmetry is the thing worth
protecting: the SHELL decides the route table and must never be a version
behind, so it still revalidates every time. The MODULES get a deliberately
short window.

What is pinned here is the shape of that trade, not the exact number. A
future change may tune 30 seconds. It must not make the shell cacheable, and
it must not make the modules immutable -- the first ships a stale route
table, the second ships stale code with no way to recover but a hard reload,
and neither would fail any other test in this repo.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "api" / "web.py").read_text(
    encoding="utf-8")


def _directive(name):
    match = re.search(rf"{name}\s*=\s*\{{[^}}]*?\"Cache-Control\":\s*([^}}]+)\}}",
                      SOURCE, re.S)
    return match.group(1).strip() if match else None


class TheShellIsNeverAVersionBehind(unittest.TestCase):

    def test_the_shell_revalidates_every_time(self):
        value = _directive("_SHELL_HEADERS")
        self.assertIsNotNone(value, "_SHELL_HEADERS no longer sets Cache-Control")
        self.assertIn("no-cache", value,
                      "the app shell decides the route table; a cached shell "
                      "beside redeployed modules is the 2026-09-07 bug")

    def test_html_is_served_as_a_shell_not_an_asset(self):
        """landing.html is a whole page. If it took the module window a
        reader could get a thirty-second-old marketing page, and worse, the
        app shell served through the catch-all route would be cacheable."""
        self.assertRegex(
            SOURCE, r"endswith\(\"\.html\"\)",
            "the asset route no longer distinguishes HTML from modules")


class TheModulesGetAShortWindow(unittest.TestCase):

    def test_a_window_exists(self):
        value = _directive("_ASSET_HEADERS")
        self.assertIsNotNone(value)
        self.assertIn("max-age", value,
                      "modules are back to revalidating every load; that is "
                      "thirty round trips before any JavaScript runs")

    def test_the_window_is_short(self):
        match = re.search(r"_ASSET_MAX_AGE_S\s*=\s*(\d+)", SOURCE)
        self.assertIsNotNone(match, "_ASSET_MAX_AGE_S is not a literal")
        seconds = int(match.group(1))
        self.assertGreater(seconds, 0,
                           "a zero window is no-cache wearing a max-age hat")
        self.assertLessEqual(
            seconds, 300,
            "the window is how long a reader can be served stale code after a "
            "deploy. Minutes, not hours -- there are no fingerprinted asset "
            "URLs to recover with.")

    def test_the_modules_are_not_immutable(self):
        value = _directive("_ASSET_HEADERS") or ""
        self.assertNotIn(
            "immutable", value,
            "immutable is only safe with fingerprinted URLs, which this "
            "repo has no build step to produce; a reader would be stuck on "
            "stale code until they hard-reloaded")


if __name__ == "__main__":
    unittest.main()
