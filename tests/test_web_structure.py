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

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

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
        self.assertTrue((WEB_DIR / "landing.html").is_file())
        self.assertTrue((WEB_DIR / "README.md").is_file())
        for name in ("api.js", "dom.js", "meta.js", "today.js", "games.js",
                     "betcheck.js", "odds.js", "mybets.js", "main.js",
                     "signup.js", "landing.js", "pricing.js"):
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
        (r"\bsure\s+thing\b", "sure thing"),
        (r"\bcan'?t\s+lose\b", "can't lose"),
    )

    # "guaranteed win" and "win probability" moved out of HARD_BANNED (added
    # by this task, for web/landing.html): docs/CONTENT_LANDING.md's
    # approved copy legitimately SAYS these phrases -- negated -- to state
    # the product's own honesty rule ("No guaranteed wins", "we do not
    # publish a win probability"). A blanket ban with no negation exception
    # would forbid the client from ever stating the rule it exists to
    # enforce. Checked the same way tests/test_customer_language.py checks
    # NEGATION_ONLY phrases: banned unless a negator appears in the
    # preceding text.
    NEGATION_ONLY_WEB = (
        (r"\bguaranteed?\s+win", "guaranteed win"),
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

    def test_no_unnegated_guaranteed_win_or_win_probability(self):
        violations = []
        for path in ALL_TEXT_FILES:
            text = path.read_text(encoding="utf-8")
            for pattern, label in self.NEGATION_ONLY_WEB:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    window = text[max(0, m.start() - 90):m.start()]
                    if not NEGATORS.search(window):
                        violations.append(
                            f"{path.relative_to(ROOT)}: {label!r} affirmed "
                            f"(no negation in the preceding window)")
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


class LandingPageStructureTests(unittest.TestCase):
    """web/landing.html: the public, standalone marketing page. Structural
    checks only -- copy correctness against docs/CONTENT_LANDING.md is the
    job of LandingVocabularyScan below and of a human diff review, not this
    class."""

    def setUp(self):
        self.html = (WEB_DIR / "landing.html").read_text(encoding="utf-8")
        self.landing_js = (WEB_DIR / "js" / "landing.js").read_text(encoding="utf-8")
        self.signup_js = (WEB_DIR / "js" / "signup.js").read_text(encoding="utf-8")
        self.pricing_js = (WEB_DIR / "js" / "pricing.js").read_text(encoding="utf-8")

    def test_hero_variant_one_is_rendered_others_are_comments(self):
        self.assertIn('data-hook="hero"', self.html)
        self.assertIn("Every claim, checkable.", self.html)
        # The other two hypothesis headlines must be present (per this
        # task's brief) but only inside an HTML comment, never rendered.
        for other_headline in ("We publish our losses too.",
                               "Find the better price. See the arithmetic."):
            self.assertIn(other_headline, self.html)
            pos = self.html.find(other_headline)
            comment_open = self.html.rfind("<!--", 0, pos)
            comment_close = self.html.rfind("-->", 0, pos)
            self.assertGreater(comment_open, comment_close,
                               f"{other_headline!r} is not inside an open HTML comment")

    def test_how_it_works_covers_every_documented_surface(self):
        for hook in ("how-it-works-today", "how-it-works-game",
                     "how-it-works-bet-check", "how-it-works-odds",
                     "how-it-works-what-changed"):
            self.assertIn(f'data-hook="{hook}"', self.html)

    def test_bet_check_never_gets_a_composed_recommendation(self):
        # Ranker Engine 2 stays gated -- the landing page must never imply
        # a pick exists, even in marketing copy.
        self.assertIn("permanently empty", self.html)
        self.assertNotIn("we recommend", self.html.lower())

    def test_price_improvement_two_branch_framing_present_and_equal_weight(self):
        self.assertIn('data-hook="price-improvement-branch-win"', self.html)
        self.assertIn('data-hook="price-improvement-branch-loss"', self.html)
        # Same list, same element shape -- not one a heading and the other
        # a footnote (docs/CONTENT_LANDING.md section 4's hard constraint).
        branch_list = re.search(
            r'<ul data-hook="price-improvement-two-branch">.*?</ul>',
            self.html, re.DOTALL)
        self.assertIsNotNone(branch_list)
        self.assertEqual(branch_list.group(0).count("<li"), 2)

    def test_price_improvement_never_names_a_book_or_shows_self_funding_math(self):
        text = self.html.lower()
        for banned in ("draftkings", "fanduel", "betmgm", "caesars",
                       "pointsbet", "expected value", "roi",
                       "pays for itself", "beat the books"):
            self.assertNotIn(banned, text)

    def test_faq_uses_native_details_summary_elements(self):
        faq_section = re.search(
            r'<section data-view="faq".*?</section>', self.html, re.DOTALL).group(0)
        self.assertGreaterEqual(faq_section.count("<details"), 10)
        self.assertEqual(faq_section.count("<details"), faq_section.count("<summary"))

    def test_pricing_section_has_a_single_source_host_no_hardcoded_number(self):
        pricing_section = re.search(
            r'<section data-view="pricing".*?</section>', self.html, re.DOTALL).group(0)
        self.assertIn('data-hook="pricing-host"', pricing_section)
        # The number lives in pricing.js's BETA_TIER, not typed into markup
        # a second time -- see that module's docstring.
        self.assertNotRegex(pricing_section, r"\$\s*\d")

    def test_landing_and_signup_share_the_one_pricing_source(self):
        for source in (self.landing_js, self.signup_js):
            self.assertIn('from "./pricing.js"', source)
            self.assertIn("BETA_TIER", source)
            self.assertIn('"data-price"', source)

    def test_pricing_module_price_is_a_single_constant(self):
        self.assertIn("price_cents", self.pricing_js)
        self.assertIn("price_display", self.pricing_js)

    def test_cta_links_into_the_signup_view(self):
        self.assertIn('href="index.html#/signup"', self.html)
        self.assertIn('data-hook="cta-primary"', self.html)
        self.assertIn('data-hook="cta-signup"', self.html)

    def test_disclaimer_footer_present_and_reuses_the_shared_renderer(self):
        self.assertIn('data-hook="disclaimer-host"', self.html)
        self.assertIn("renderDisclaimerFooter", self.landing_js)
        self.assertIn('from "./meta.js"', self.landing_js)

    def test_landing_view_tracked_via_the_public_funnel_endpoint(self):
        self.assertIn("trackFunnelEvent", self.landing_js)
        self.assertIn("landing_view", self.landing_js)

    def test_signup_started_tracked_when_the_signup_view_mounts(self):
        self.assertIn("trackFunnelEvent", self.signup_js)
        self.assertIn("signup_started", self.signup_js)

    def test_signup_flow_codes_against_the_documented_contract(self):
        # {user_id, checkout|waitlisted} -- both branches handled, plus the
        # honest "not yet open" state for a 404 (api/signup.py may not be
        # live in every environment this client runs against).
        self.assertIn("result.checkout.checkout_url", self.signup_js)
        self.assertIn('result.status === "waitlisted"', self.signup_js)
        self.assertIn("signup is not yet open", self.signup_js.lower())

    def test_signup_complete_shows_token_with_copy_instructions_and_app_link(self):
        self.assertIn("renderSignupComplete", self.signup_js)
        # JS builds this attribute via dom.js's el() object-literal shape
        # ("data-hook": "...") rather than an HTML attribute string.
        self.assertIn('"data-hook": "signup-token"', self.signup_js)
        self.assertIn("index.html#/today", self.signup_js)


class SignupRouteWiredIntoMainTests(unittest.TestCase):
    def setUp(self):
        self.main_js = (WEB_DIR / "js" / "main.js").read_text(encoding="utf-8")

    def test_signup_routes_imported_and_dispatched(self):
        self.assertIn('from "./signup.js"', self.main_js)
        self.assertIn("renderSignup(main)", self.main_js)
        self.assertIn("renderSignupComplete(main, query)", self.main_js)
        self.assertIn('route === "signup"', self.main_js)


class LandingVocabularyScan(unittest.TestCase):
    """The fuller scan tests/test_content_language.py runs over
    docs/CONTENT_LANDING.md (HARD_BANNED outright, NEGATION_ONLY unless
    negated nearby) -- applied here to web/landing.html itself, since this
    task's ACCEPTANCE asks that the rendered page be checked too, not just
    its source markdown. NoBannedCustomerVocabulary above already covers
    the narrower web/-wide HARD_BANNED-only list; this adds the
    NEGATION_ONLY half (edge/guaranteed/win-probability/etc.) that class
    does not check."""

    def test_no_banned_language_in_landing_html(self):
        text = (WEB_DIR / "landing.html").read_text(encoding="utf-8")
        paragraphs = re.split(r"\n\s*\n", text)
        violations = []
        for idx, para in enumerate(paragraphs, start=1):
            for pattern, label in HARD_BANNED:
                if re.search(pattern, para, re.IGNORECASE):
                    violations.append(f"landing.html block {idx}: hard-banned {label!r}")
            for pattern, label in NEGATION_ONLY:
                for m in re.finditer(pattern, para, re.IGNORECASE):
                    window = para[max(0, m.start() - 90):m.start()]
                    if not NEGATORS.search(window):
                        violations.append(
                            f"landing.html block {idx}: {label!r} affirmed "
                            f"(no negation nearby) in {para[:120]!r}")
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
