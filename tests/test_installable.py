"""The app must be installable to a phone home screen.

WHY THIS FILE EXISTS
---------------------
The mobile WEB experience was already good -- a real bottom tab bar, a
fixed Bet Check field, per-view mobile compositions, 47 media queries. What
did not exist was any installable surface at all: no manifest, no icons,
and not one image file anywhere in web/. On top of that api/web.py's asset
allowlist REFUSED .webmanifest and .png outright, so a manifest could have
been committed and still 404'd on every request.

Two failure modes this pins, both silent:
  * a manifest that references icons the server will not serve
  * safe-area insets that need viewport-fit=cover to report anything, so
    the CSS looks right and does nothing on the device it was written for
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
MANIFEST = WEB / "manifest.webmanifest"
INDEX = WEB / "index.html"


class TheManifestIsValidAndServable(unittest.TestCase):

    def setUp(self):
        self.assertTrue(MANIFEST.is_file(), "web/manifest.webmanifest missing")
        self.data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_it_declares_what_a_browser_requires(self):
        for key in ("name", "start_url", "display", "icons"):
            self.assertIn(key, self.data)
        self.assertIn(self.data["display"], ("standalone", "fullscreen",
                                             "minimal-ui"))

    def test_it_has_both_required_icon_sizes(self):
        sizes = {i["sizes"] for i in self.data["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)

    def test_it_has_a_maskable_icon(self):
        """Android crops icons to a device-chosen shape. Without a maskable
        variant the launcher letterboxes ours inside a white circle."""
        purposes = {i.get("purpose", "any") for i in self.data["icons"]}
        self.assertTrue(any("maskable" in p for p in purposes),
                        "no maskable icon; Android will not use the mark as "
                        "the app's silhouette")

    def test_every_icon_it_names_actually_exists(self):
        missing = [i["src"] for i in self.data["icons"]
                   if not (WEB / i["src"]).is_file()]
        self.assertEqual([], missing,
                         f"the manifest points at icons that are not in the "
                         f"repo: {missing}")

    def test_every_icon_type_is_servable(self):
        """The allowlist in api/web.py is a real 404 -- a manifest naming a
        file type it refuses is a manifest that silently does not work."""
        from api.web import _ALLOWED_SUFFIXES
        refused = [i["src"] for i in self.data["icons"]
                   if Path(i["src"]).suffix not in _ALLOWED_SUFFIXES]
        self.assertEqual([], refused,
                         f"api/web.py will 404 these: {refused}")
        self.assertIn(".webmanifest", _ALLOWED_SUFFIXES,
                      "the manifest itself will 404")

    def test_scope_and_start_url_agree(self):
        """A start_url outside scope makes the installed app open in a
        browser tab instead of standalone."""
        self.assertTrue(self.data["start_url"].startswith(self.data["scope"]))


class TheShellDeclaresItself(unittest.TestCase):

    def setUp(self):
        self.html = INDEX.read_text(encoding="utf-8")

    def test_the_manifest_is_linked(self):
        self.assertIn('rel="manifest"', self.html)

    def test_apple_touch_icon_is_declared(self):
        """iOS reads only this one; it ignores the manifest's icon array."""
        self.assertIn('rel="apple-touch-icon"', self.html)

    def test_the_apple_icon_is_opaque(self):
        """iOS composites nothing behind an icon, so any transparency
        renders as a black notch. scripts/make_icons.py builds this one
        full-bleed with no chamfer for exactly that reason."""
        from scripts.make_icons import SIZES
        styles = {name: style for name, _size, style in SIZES}
        self.assertEqual("opaque", styles.get("apple-touch-icon.png"))

    def test_viewport_fit_cover_is_set(self):
        """env(safe-area-inset-*) reports 0 without it, so every inset rule
        in the CSS would compile fine and do nothing on the exact devices
        they exist for."""
        viewport = re.search(r'name="viewport"[^>]*content="([^"]+)"',
                             self.html)
        self.assertIsNotNone(viewport)
        self.assertIn("viewport-fit=cover", viewport.group(1))


class TheBottomBarClearsTheHomeIndicator(unittest.TestCase):

    def test_the_tab_bar_carries_the_inset(self):
        css = (WEB / "css" / "nav.css").read_text(encoding="utf-8")
        block = css.split(".tabbar {", 1)[1].split("}", 1)[0]
        self.assertIn("safe-area-inset-bottom", block,
                      "the fixed tab bar sits under the home indicator on a "
                      "notched phone")

    def test_the_padding_shorthand_does_not_undo_it(self):
        """`padding: 0 6px` AFTER `padding-bottom: env(...)` resets it to
        zero and the fix silently does nothing -- which is how it was
        written the first time."""
        css = (WEB / "css" / "nav.css").read_text(encoding="utf-8")
        block = css.split(".tabbar {", 1)[1].split("}", 1)[0]
        shorthand = block.find("padding:")
        longhand = block.find("padding-bottom:")
        self.assertGreater(longhand, shorthand,
                           "the padding shorthand comes after "
                           "padding-bottom and cancels the safe-area inset")

    def test_content_reserves_room_for_the_taller_bar(self):
        css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("safe-area-inset-bottom", css,
                      "page content does not account for the inset, so the "
                      "last rows sit under the bar")


class TheIconsMatchTheirGenerator(unittest.TestCase):
    """Committed binaries nobody can regenerate are binaries nobody dares
    change -- and the brand here is explicitly a placeholder pending
    trademark clearance, so these WILL be replaced."""

    def test_check_mode_passes(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "scripts/make_icons.py", "--check"],
            cwd=str(REPO), capture_output=True, text=True, timeout=120)
        self.assertEqual(
            0, result.returncode,
            f"icons differ from scripts/make_icons.py:\n{result.stdout}\n"
            f"{result.stderr}")


if __name__ == "__main__":
    unittest.main()
