"""Static structural checks for web/ -- the zero-aesthetic reference client.

These tests never start a server and never import FastAPI; they read the
files under web/ as text and assert on their shape, the same "prove it
without running anything" spirit as tests/test_customer_language.py's
scan of src/analysis and src/report.

Covers this task's ACCEPTANCE checks:
  - every file under web/ parses (html.parser for .html; a plain read for
    .js/.md -- there is no JS parser in the stdlib, so JS files are
    scanned as text, which is enough for the checks below)
  - no `style="..."` attributes and no `<style>` block beyond the one
    allowed line in index.html's <head>
  - no color/font word in any class name (HTML class="..." or JS
    `class: "..."` object-literal values)
  - the Bet Check skeleton's data-hook markers appear, in the mandated
    order, in betcheck.js
  - the disclaimer hook is present in the app shell and referenced by the
    JS that renders it
  - no banned customer-facing vocabulary in any string literal under web/
"""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

HTML_FILES = sorted(WEB_DIR.glob("*.html"))
JS_FILES = sorted((WEB_DIR / "js").glob("*.js"))
ALL_TEXT_FILES = HTML_FILES + JS_FILES + sorted(WEB_DIR.glob("*.md"))

# The one CSS rule the task brief allows, verbatim, so a future edit can't
# quietly "add just one more small rule" next to it.
ALLOWED_STYLE_LINE = "[hidden]{display:none}"


class _ParseOnlyHTMLParser(HTMLParser):
    """Just walks the document; html.parser raises on malformed markup
    (mismatched/unterminated tags etc.), which is all this check needs --
    it does not need to inspect the parsed tree itself."""


class FilesExistAndParse(unittest.TestCase):
    def test_expected_files_present(self):
        self.assertTrue((WEB_DIR / "index.html").is_file())
        self.assertTrue((WEB_DIR / "README.md").is_file())
        for name in ("api.js", "dom.js", "meta.js", "today.js", "games.js",
                     "betcheck.js", "odds.js", "mybets.js", "main.js"):
            self.assertTrue((WEB_DIR / "js" / name).is_file(), name)

    def test_html_files_parse(self):
        for path in HTML_FILES:
            parser = _ParseOnlyHTMLParser()
            with self.subTest(file=path.name):
                parser.feed(path.read_text(encoding="utf-8"))
                parser.close()

    def test_js_files_are_readable_text(self):
        # No JS parser in the stdlib -- this only proves the files exist,
        # are valid UTF-8, and are non-empty; deeper JS correctness is out
        # of scope for a static structural check.
        for path in JS_FILES:
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.strip(), f"{path.name} is empty")


class NoAestheticDecisions(unittest.TestCase):
    """HARD RULES: no colors, no fonts, no layout styling, no CSS beyond
    the one allowed line."""

    STYLE_ATTR_RE = re.compile(r'\bstyle\s*=', re.IGNORECASE)
    STYLE_TAG_RE = re.compile(r'<style\b', re.IGNORECASE)
    STYLE_TAG_CONTENT_RE = re.compile(
        r'<style\b[^>]*>(.*?)</style>', re.IGNORECASE | re.DOTALL)

    def test_no_style_attributes_anywhere(self):
        for path in ALL_TEXT_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(
                self.STYLE_ATTR_RE.search(text),
                f"{path.relative_to(ROOT)} contains a style= attribute")

    def test_only_one_style_block_and_it_is_the_allowed_line(self):
        style_blocks = []
        for path in HTML_FILES:
            text = path.read_text(encoding="utf-8")
            style_blocks.extend(
                (path, m.group(1).strip())
                for m in self.STYLE_TAG_CONTENT_RE.finditer(text))
        self.assertEqual(
            len(style_blocks), 1,
            f"expected exactly one <style> block across web/, found: "
            f"{[(p.name, c) for p, c in style_blocks]}")
        _, content = style_blocks[0]
        self.assertEqual(content, ALLOWED_STYLE_LINE)

    def test_no_inline_css_files(self):
        self.assertEqual(list(WEB_DIR.rglob("*.css")), [],
                         "no .css files belong under web/ -- see HARD RULES")


class ClassNamingIsContentNotAppearance(unittest.TestCase):
    """BEM-ish class names are allowed ONLY as attachment points; the
    words themselves must describe content, never appearance."""

    # Deliberately NOT in this set: "slate" (the day's slate of games, a
    # baseball/product term used throughout docs/API_CONTRACTS.md and
    # docs/PRODUCT_DESIGN_HANDOFF.md -- not a color choice) and "board"
    # (the odds/price board, a domain noun). Both would otherwise
    # false-positive against a naive color-word scan.
    BANNED_COLOR_WORDS = {
        "red", "orange", "yellow", "green", "blue", "purple", "violet",
        "indigo", "pink", "black", "white", "gray", "grey", "teal",
        "navy", "maroon", "cyan", "magenta", "gold", "silver", "brown",
        "lime", "beige", "coral", "turquoise", "azure", "crimson",
        "amber", "charcoal", "ivory", "khaki", "lavender", "mint",
        "burgundy", "peach", "salmon", "olive", "plum",
    }
    BANNED_FONT_WORDS = {
        "bold", "italic", "serif", "sans", "mono", "monospace",
        "uppercase", "lowercase", "capitalize", "underline",
        "strikethrough", "rounded", "shadow", "gradient", "thin",
        "condensed", "narrow", "oblique", "font", "typeface", "weight",
        "large", "small", "tiny", "huge", "px", "rem", "em",
    }
    BANNED = BANNED_COLOR_WORDS | BANNED_FONT_WORDS

    HTML_CLASS_ATTR_RE = re.compile(r'class\s*=\s*"([^"]*)"')
    JS_CLASS_KEY_RE = re.compile(r'class\s*:\s*[`"\']([^`"\']*)[`"\']')

    def _tokens(self, class_value: str):
        # Split "bet-check-your-bet__fields" (or a space-separated
        # multi-class value) into lowercase word tokens on any non-letter
        # boundary -- BEM's `-`/`__` separators plus a plain space.
        for part in class_value.split():
            for token in re.split(r'[^a-zA-Z]+', part):
                if token:
                    yield token.lower()

    def test_no_banned_words_in_html_class_attributes(self):
        violations = []
        for path in HTML_FILES:
            text = path.read_text(encoding="utf-8")
            for m in self.HTML_CLASS_ATTR_RE.finditer(text):
                for token in self._tokens(m.group(1)):
                    if token in self.BANNED:
                        violations.append(f"{path.name}: class {m.group(1)!r} has {token!r}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_no_banned_words_in_js_class_values(self):
        violations = []
        for path in JS_FILES:
            text = path.read_text(encoding="utf-8")
            for m in self.JS_CLASS_KEY_RE.finditer(text):
                for token in self._tokens(m.group(1)):
                    if token in self.BANNED:
                        violations.append(f"{path.name}: class {m.group(1)!r} has {token!r}")
        self.assertEqual(violations, [], "\n".join(violations))


class BetCheckSkeletonOrder(unittest.TestCase):
    """A fixed skeleton is a trust mechanism (docs/PRODUCT_DESIGN_HANDOFF.md)
    -- YOUR BET -> SUPPORT -> COUNTERARGUMENT -> PRICES -> BOTTOM LINE,
    always in this order. Pinned against the data-hook markers rather than
    against rendered DOM output, since these view modules build the DOM
    programmatically rather than emitting static markup."""

    MANDATED_ORDER = [
        "bet-check-your-bet",
        "bet-check-support",
        "bet-check-counterargument",
        "bet-check-prices",
        "bet-check-bottom-line",
    ]

    def test_skeleton_hooks_present_in_mandated_order(self):
        source = (WEB_DIR / "js" / "betcheck.js").read_text(encoding="utf-8")
        positions = []
        for hook in self.MANDATED_ORDER:
            needle = f'"data-hook": "{hook}"'
            index = source.find(needle)
            self.assertGreaterEqual(index, 0, f"missing data-hook {hook!r} in betcheck.js")
            positions.append(index)
        self.assertEqual(
            positions, sorted(positions),
            "Bet Check data-hook markers are out of the mandated order: "
            + ", ".join(self.MANDATED_ORDER))

    def test_counterargument_never_rendered_as_composed_fallback_text(self):
        # counterargument_lines is contractually never empty (it renders
        # "No significant counterarguments found" itself -- docs/
        # API_CONTRACTS.md). This client must not additionally compose its
        # own fallback string for an empty case that cannot occur.
        source = (WEB_DIR / "js" / "betcheck.js").read_text(encoding="utf-8")
        self.assertNotIn("No significant counterarguments found", source)

    def test_recommendation_is_rendered_not_interpreted(self):
        source = (WEB_DIR / "js" / "betcheck.js").read_text(encoding="utf-8")
        self.assertIn("result.recommendation", source)


class DisclaimerAndStalenessHooksPresent(unittest.TestCase):
    def test_disclaimer_host_in_app_shell(self):
        index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-hook="disclaimer-host"', index_html)

    def test_disclaimer_hook_rendered_from_meta(self):
        meta_js = (WEB_DIR / "js" / "meta.js").read_text(encoding="utf-8")
        self.assertIn('"data-hook": "disclaimer"', meta_js)
        self.assertIn("/meta", meta_js)

    def test_disclaimer_always_mounted_by_router(self):
        main_js = (WEB_DIR / "js" / "main.js").read_text(encoding="utf-8")
        self.assertIn("renderDisclaimerFooter", main_js)
        # Mounted once during boot(), outside renderRoute() -- so it is
        # never cleared or skipped by a view swap.
        boot_body = main_js.split("function boot()")[1].split("function ")[0]
        self.assertIn("renderDisclaimerFooter", boot_body)

    def test_staleness_hook_used_by_multiple_views(self):
        for name in ("today.js", "games.js"):
            source = (WEB_DIR / "js" / name).read_text(encoding="utf-8")
            self.assertIn("renderStaleness", source, f"{name} should render staleness")


class NoBannedCustomerVocabulary(unittest.TestCase):
    """Same category of banned language as tests/test_customer_language.py,
    scanned across web/ as plain text rather than via ast (these are JS
    files, not Python) -- this client must never compose a claim the API
    itself would not make (see docs/API_CONTRACTS.md's vocabulary rules)."""

    HARD_BANNED = (
        (r"\+\s*EV\b", "+EV"),
        (r"\btrue\s+line\b", "true line"),
        (r"\btrue\s+probabilit", "true probability"),
        (r"\btrue\s+odds\b", "true odds"),
        (r"market'?s\s+true\s+read", "market's true read"),
        (r"\bfree\s+money\b", "free money"),
        (r"\ba\s+lock\b", "a lock"),
        (r"\bguaranteed?\s+win", "guaranteed win"),
        (r"\bsure\s+thing\b", "sure thing"),
        (r"\bcan'?t\s+lose\b", "can't lose"),
        (r"\bwin[- ]probabilit\w*", "win probability"),
    )

    def test_no_hard_banned_phrases(self):
        violations = []
        for path in ALL_TEXT_FILES:
            text = path.read_text(encoding="utf-8")
            for pattern, label in self.HARD_BANNED:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(f"{path.relative_to(ROOT)}: {label!r}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_no_inline_event_handler_attributes(self):
        # CSP-friendliness (task brief) as well as a vocabulary-adjacent
        # check: an inline `onclick="doSomething()"` string is exactly the
        # kind of ad hoc composed behavior this client avoids everywhere
        # else.
        pattern = re.compile(r'\bon[a-z]+\s*=\s*"', re.IGNORECASE)
        for path in HTML_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(text),
                              f"{path.name} has an inline event handler attribute")


if __name__ == "__main__":
    unittest.main()
