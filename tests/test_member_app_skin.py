"""The member app (web/index.html) wears the same professional skin as the model pages.

WHY THIS FILE EXISTS
---------------------
On 2026-10-19 the leaderboard, model and landing pages were rebuilt as a sportsbook-style dark UI
(web/css/hounds.css). The app at web/index.html still used the older chamfered, italic-display look and read as
a different product; the owner asked whether the sign-in page was the "updated UI" and it was not. The skin is
web/css/member.css (shell, tokens, shared shapes) and web/css/member-screens.css (what each screen draws), both
scoped under `body.member-app` so no other page that shares screens.css changes.

These are static checks (no browser): the pieces are wired, the skin removes the old look instead of adding to
it, and nothing in it can make the page scroll sideways. The tablelabels.js behaviour is run under node when
node is installed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
SHELL_CSS = (WEB / "css" / "member.css").read_text(encoding="utf-8")
SCREEN_CSS = (WEB / "css" / "member-screens.css").read_text(encoding="utf-8")
BOTH = SHELL_CSS + "\n" + SCREEN_CSS
MAIN_JS = (WEB / "js" / "main.js").read_text(encoding="utf-8")
HAS_NODE = shutil.which("node") is not None


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def top_level_selectors(css: str):
    """Every selector list that starts a rule, including the ones inside @media blocks."""
    css = strip_comments(css)
    out = []
    for match in re.finditer(r"([^{}@]+)\{", css):
        text = match.group(1).strip()
        if text and not text.startswith("@"):
            out.append(text)
    return out


class TheSkinIsWired(unittest.TestCase):

    def test_the_page_opts_in_and_loads_both_files_in_order(self):
        self.assertRegex(INDEX, r'<body class="member-app">')
        order = [INDEX.index(f'href="css/{name}.css"') for name in ("screens", "card", "ufcfights", "member", "member-screens", "gotcha")]
        self.assertEqual(order, sorted(order), "member.css and member-screens.css load after every app sheet and before gotcha.css")

    def test_every_rule_is_scoped_to_the_member_app(self):
        for selector in top_level_selectors(BOTH):
            if selector.startswith(("media ", "from", "to")) or re.fullmatch(r"\d+%", selector):
                continue  # an @media condition the parser split off its @, or a keyframe step
            for part in selector.split(","):
                part = part.strip()
                if part.startswith("body.member-app"):
                    continue
                self.fail(f"unscoped selector would restyle other pages: {part!r}")

    def test_other_pages_do_not_load_the_skin(self):
        for name in ("landing.html", "hounds.html", "hound.html", "learning.html", "build-a-hound.html", "postseason.html", "sample.html"):
            html = (WEB / name).read_text(encoding="utf-8")
            self.assertNotIn("member.css", html, name)
            self.assertNotIn("member-screens.css", html, name)

    def test_the_app_bar_is_the_leaderboards_pattern(self):
        for hook in ("brand-mark", "product-name", "sport-level-host", "primary-nav", "primary-nav-mobile", "nav-signin", "news-host", "shell-clock"):
            self.assertIn(f'data-hook="{hook}"', INDEX, hook)
        self.assertIn('class="wordmark__mark"', INDEX)
        self.assertIn('href="#/signin"', INDEX)
        # section links sit in the app bar, not a 228px left rail
        self.assertLess(INDEX.index('class="appbar"'), INDEX.index('data-hook="primary-nav"'))
        self.assertLess(INDEX.index('data-hook="primary-nav"'), INDEX.index('data-hook="app-outlet"'))
        self.assertIn("mountAccount", MAIN_JS)
        self.assertIn("Account", MAIN_JS)


class TheOldLookIsGone(unittest.TestCase):
    """The member app no longer uses the chamfer or italic-display look on its main screens."""

    def test_the_chamfer_is_removed_everywhere_in_the_app(self):
        css = strip_comments(BOTH)
        self.assertRegex(css, r"body\.member-app \.shell \*:not\(\.wordmark__mark\):not\(\.wordmark__mark \*\) \{ clip-path: none; \}")
        self.assertIn("body.member-app .chamfer", css)
        self.assertNotIn("polygon(", css, "the skin draws no clipped corners of its own")
        # the app's own markup (index.html) carries no chamfer class
        self.assertNotRegex(INDEX, r'class="[^"]*\bchamfer\b')

    def test_no_italic_display_type_is_added_or_left_on_the_screens(self):
        css = strip_comments(BOTH)
        self.assertNotRegex(css, r"font-style:\s*italic")
        self.assertRegex(css, r"\.shell \*:not\(\.wordmark__text\):not\(\.wordmark__text \*\) \{ font-style: normal; \}")
        # headings are the body face, sentence case, no tracking
        self.assertRegex(css, r"\.shell h1,\s*body\.member-app \.shell h2")
        self.assertIn("--font-display: var(--font-body);", css)
        self.assertIn("--font-mono: var(--font-body);", css)

    def test_the_four_gameday_headlines_read_as_sentences(self):
        css = strip_comments(BOTH)
        self.assertIn(".gv2-hero__headline { text-transform: lowercase; }", css)
        self.assertIn(".gv2-hero__headline::first-letter { text-transform: uppercase; }", css)

    def test_the_hero_headline_and_price_figure_are_no_longer_posters(self):
        css = strip_comments(BOTH)
        sizes = [int(n) for n in re.findall(r"\.gv2-(?:hero__headline|price__figure) \{[^}]*font-size:\s*clamp\(\d+px,\s*[\d.]+vw,\s*(\d+)px\)", css)]
        self.assertTrue(sizes and max(sizes) <= 40, sizes)

    def test_the_palette_is_the_model_pages(self):
        for token in ("#0E1116", "#141920", "#1A2029", "#9AA3B2", "#3DDC84", "#FF6B7A", "#2FD07A"):
            self.assertIn(token, SHELL_CSS)
        self.assertIn("font-variant-numeric: tabular-nums", SHELL_CSS)

    def test_the_gradient_fills_are_flat(self):
        css = strip_comments(SCREEN_CSS)
        for pair in ("--money-2: #FF4D63;", "--v-money-2: #FF4D63;", "--live-2: #4FC3D9;", "--v-live-2: #4FC3D9;"):
            self.assertIn(pair, css)


class NothingMakesThePageScrollSideways(unittest.TestCase):

    def test_the_viewport_and_the_page_overflow_guard(self):
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1', INDEX)
        base = (WEB / "css" / "base.css").read_text(encoding="utf-8")
        self.assertRegex(base, r"html, body \{ overflow-x: hidden; \}")

    def test_no_fixed_width_wider_than_a_phone_outside_a_wide_media_query(self):
        css = strip_comments(BOTH)
        # drop every @media (min-width: ...) block, which cannot apply at 375px
        stripped = re.sub(r"@media \(min-width:[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
        for prop in ("min-width", "width"):
            for value in re.findall(rf"(?<![-\w]){prop}:\s*(\d+)px", stripped):
                self.assertLessEqual(int(value), 375, f"{prop}: {value}px can overflow a 375px phone")

    def test_wide_tables_stack_into_cards_under_640px(self):
        css = strip_comments(SCREEN_CSS)
        self.assertIn("@media (max-width: 639px)", css)
        self.assertIn("table[data-stackable] thead { display: none; }", css)
        self.assertIn("content: attr(data-label)", css)
        self.assertIn(".ov2-table-wrap, body.member-app .board-scroll { overflow-x: visible; }", css)
        self.assertIn("watchTables(main)", MAIN_JS)
        self.assertIn('import { watchTables } from "./tablelabels.js";', MAIN_JS)

    def test_the_app_bar_wraps_on_a_phone_and_the_section_links_move_to_the_tab_bar(self):
        css = strip_comments(SHELL_CSS)
        self.assertRegex(css, r"@media \(max-width: 899px\) \{[^@]*body\.member-app \.rail \{ display: none; \}")
        self.assertIn("flex-wrap: wrap", css)

    def test_the_notice_is_slim_on_a_phone(self):
        css = strip_comments(SHELL_CSS)
        self.assertIn("-webkit-line-clamp: 2", css)
        self.assertIn("body.member-app .news__count, body.member-app .news__nav { display: none; }", css)
        # still dismissible
        self.assertIn("news__dismiss", css)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TableLabelsRunUnderNode(unittest.TestCase):

    SCRIPT = r"""
import { labelTable, labelTables } from "%s";
function cell(tag, text) { const attrs = {}; return { tagName: tag, textContent: text,
  hasAttribute: (k) => k in attrs, setAttribute: (k, v) => { attrs[k] = v; }, attrs }; }
function row(cells) { return { children: cells }; }
const head = [cell("TH", "BET"), cell("TH", "PRICE"), cell("TH", "")];
const body = [row([cell("TD", "Over 6.0"), cell("TD", "-110"), cell("TD", "x")]), row([cell("TD", "Under 5"), cell("TD", "+100"), cell("TD", "y")])];
const tableAttrs = {};
const table = {
  querySelectorAll(sel) { return sel === "thead th" ? head : sel === "tbody tr" ? body : []; },
  setAttribute: (k, v) => { tableAttrs[k] = v; },
};
labelTable(table);
const out = body.map((r) => r.children.map((c) => c.attrs["data-label"] || null));
// a table with no header is left alone
const bare = { querySelectorAll: () => [], setAttribute: () => { throw new Error("must not mark a headless table"); } };
labelTable(bare);
labelTables(null);
console.log(JSON.stringify({ out, stackable: tableAttrs["data-stackable"] }));
"""

    def test_each_cell_gets_its_column_header(self):
        script = self.SCRIPT % (WEB / "js" / "tablelabels.js").as_uri()
        result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        import json
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data["out"], [["BET", "PRICE", None], ["BET", "PRICE", None]])
        self.assertEqual(data["stackable"], "true")


if __name__ == "__main__":
    unittest.main()
