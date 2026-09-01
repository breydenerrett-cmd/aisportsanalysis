"""Static structural checks for web/ -- the customer client.

These tests never start a server and never import FastAPI; they read the
files under web/ as text and assert on their shape, the same "prove it
without running anything" spirit as tests/test_customer_language.py's
scan of src/analysis and src/report.

HISTORY OF THIS CONTRACT: until 2026-09-01 this file enforced web/ as a
"zero-aesthetic reference client" (no CSS files, no style attributes, no
color/font words in class names). That phase ended when the frozen
LINEHOUND v1 design landed in design/linehound-v1 (commit 9c63710) with
Brey's directive to implement it into this client -- a design system IS
colors, fonts, spacing and motion, so the zero-aesthetic classes were
retired here on purpose, in the open, not routed around. What survives
is everything that was never about styling:

  - every file under web/ parses and the expected modules exist
  - the Bet Check skeleton's data-hook markers appear in the mandated
    order (a trust mechanism, not a layout choice)
  - the disclaimer and staleness hooks stay wired
  - the admin token never leaves sessionStorage or rides in a URL
  - no banned customer-facing vocabulary anywhere under web/
  - one source of truth for the price; funnel/signup wiring intact

The frozen canvases in design/linehound-v1 are the visual contract now;
HANDOFF_README.md's six product-integrity rules bind the implementation
and several of them are enforced below where a static scan can.
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


class _ParseOnlyHTMLParser(HTMLParser):
    """Just walks the document; html.parser raises on malformed markup
    (mismatched/unterminated tags etc.), which is all this check needs --
    it does not need to inspect the parsed tree itself."""


class FilesExistAndParse(unittest.TestCase):
    def test_expected_files_present(self):
        self.assertTrue((WEB_DIR / "index.html").is_file())
        self.assertTrue((WEB_DIR / "landing.html").is_file())
        self.assertTrue((WEB_DIR / "admin.html").is_file())
        self.assertTrue((WEB_DIR / "README.md").is_file())
        for name in ("api.js", "dom.js", "meta.js", "today.js", "games.js",
                     "betcheck.js", "odds.js", "mybets.js", "main.js",
                     "signup.js", "landing.js", "pricing.js", "admin.js"):
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


class BetCheckSkeletonOrder(unittest.TestCase):
    """A fixed skeleton is a trust mechanism (docs/PRODUCT_DESIGN_HANDOFF.md,
    reaffirmed by design/linehound-v1/HANDOFF_README.md)
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

    # "guaranteed win" and "win probability" are checked negation-only:
    # docs/CONTENT_LANDING.md's approved copy legitimately SAYS these
    # phrases -- negated -- to state the product's own honesty rule ("No
    # guaranteed wins", "we do not publish a win probability"). A blanket
    # ban would forbid the client from ever stating the rule it exists to
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
        # CSP-friendliness: an inline `onclick="doSomething()"` string is
        # exactly the kind of ad hoc composed behavior this client avoids
        # everywhere else. Styling moved into CSS with the design system;
        # behavior stays in the modules.
        pattern = re.compile(r'\bon[a-z]+\s*=\s*"', re.IGNORECASE)
        for path in HTML_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(text),
                              f"{path.name} has an inline event handler attribute")


class LandingIntegrityTests(unittest.TestCase):
    """web/landing.html: the public marketing page. The frozen Landing
    canvas (design/linehound-v1) owns STRUCTURE and copy now, so the old
    structural pins (hero variants, section hooks, FAQ element counts)
    were retired with the zero-aesthetic phase. What this class keeps is
    integrity that survives any redesign."""

    def setUp(self):
        self.html = (WEB_DIR / "landing.html").read_text(encoding="utf-8")
        self.landing_js = (WEB_DIR / "js" / "landing.js").read_text(encoding="utf-8")
        self.signup_js = (WEB_DIR / "js" / "signup.js").read_text(encoding="utf-8")
        self.pricing_js = (WEB_DIR / "js" / "pricing.js").read_text(encoding="utf-8")

    def test_landing_never_implies_a_pick_exists(self):
        # Ranker Engine 2 stays gated -- the landing page must never imply
        # a recommendation exists, even in marketing copy.
        self.assertNotIn("we recommend", self.html.lower())

    def test_no_self_funding_or_ev_framing(self):
        text = self.html.lower()
        for banned in ("expected value", "roi", "pays for itself",
                       "beat the books"):
            self.assertNotIn(banned, text)

    def test_any_displayed_price_matches_the_single_pricing_source(self):
        # pricing.js's BETA_TIER is the one source of truth for the price.
        # The frozen canvas shows the number in markup, which is fine --
        # but every dollar figure that looks like the subscription price
        # must EQUAL the module's price_display, so the two can never
        # drift apart silently.
        display = re.search(r'price_display\s*:\s*"([^"]+)"', self.pricing_js)
        self.assertIsNotNone(display, "pricing.js must define price_display")
        canonical = re.search(r"\d+\.\d{2}", display.group(1))
        self.assertIsNotNone(canonical, "price_display should carry a $X.XX amount")
        # Only cents-bearing amounts are price-shaped ("$0" in a free-offer
        # line, or a "$40" example, is not the subscription price and is
        # left alone). Any $X.XX in the markup must be THE price.
        for m in re.finditer(r"\$\s*(\d+\.\d{2})", self.html):
            self.assertEqual(
                m.group(1), canonical.group(0),
                f"landing.html shows ${m.group(1)} but pricing.js says "
                f"${canonical.group(0)} -- one source of truth for the price")

    def test_pricing_module_price_is_a_single_constant(self):
        self.assertIn("price_cents", self.pricing_js)
        self.assertIn("price_display", self.pricing_js)

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

    def test_disclaimer_footer_present_and_reuses_the_shared_renderer(self):
        self.assertIn('data-hook="disclaimer-host"', self.html)
        self.assertIn("renderDisclaimerFooter", self.landing_js)


class SignupRouteWiredIntoMainTests(unittest.TestCase):
    def setUp(self):
        self.main_js = (WEB_DIR / "js" / "main.js").read_text(encoding="utf-8")

    def test_signup_routes_imported_and_dispatched(self):
        self.assertIn('from "./signup.js"', self.main_js)
        self.assertIn("renderSignup(main)", self.main_js)
        self.assertIn("renderSignupComplete(main, query)", self.main_js)
        self.assertIn('route === "signup"', self.main_js)


class AdminViewStructureTests(unittest.TestCase):
    """web/admin.html + web/js/admin.js: the ops dashboard over
    api/admin.py, api/funnel.py, api/support.py -- admin-token handling
    rules, on top of the generic vocabulary checks every web/ file gets
    from the classes above."""

    def setUp(self):
        self.html = (WEB_DIR / "admin.html").read_text(encoding="utf-8")
        self.js = (WEB_DIR / "js" / "admin.js").read_text(encoding="utf-8")

    def test_token_kept_in_sessionstorage_never_localstorage(self):
        # The admin token is the one credential in this client that can
        # read every user's email and change support state -- it must use
        # the shorter-lived store, and this file must never actually READ
        # OR WRITE it via localStorage (mentioning the word in a docstring,
        # to explain the choice, is fine -- an actual `window.localStorage`
        # call is not).
        self.assertIn("window.sessionStorage", self.js)
        self.assertNotIn("window.localStorage", self.js)

    def test_token_sent_as_header_never_built_into_a_url(self):
        self.assertIn("X-Admin-Token", self.js)
        # No fetch/URL construction concatenates the token into a path or
        # querystring anywhere in this file (e.g. `?token=`, or a template
        # literal splicing the token itself, or the function that reads
        # it, into a request path/URL).
        self.assertNotRegex(self.js, r"[?&]token=")
        self.assertNotRegex(self.js, r"\$\{[^}]*[Tt]oken[^}]*\}")
        # And it is never sent as an Authorization bearer -- that header is
        # web/js/api.js's separate invite-token contract, not this one
        # (mentioning the word in a comment, to say so, is fine; setting
        # the header itself is not).
        self.assertNotIn('headers["Authorization"]', self.js)
        self.assertNotIn("headers['Authorization']", self.js)

    def test_distinguishes_401_and_404_as_separate_states(self):
        self.assertIn('"admin-auth-invalid"', self.js)
        self.assertIn('"admin-auth-disabled"', self.js)
        self.assertIn("err.status === 404", self.js)
        self.assertIn("err.status === 401", self.js)

    def test_store_health_reasons_rendered_verbatim(self):
        # No template literal wraps/paraphrases `reason` -- it is appended
        # as its own list item text, unmodified.
        self.assertIn("list.appendChild(el(\"li\", { text: reason }))", self.js)

    def test_support_status_change_posts_to_documented_route(self):
        self.assertIn("/admin/support/${id}/status", self.js)


class LandingVocabularyScan(unittest.TestCase):
    """The fuller scan tests/test_content_language.py runs over
    docs/CONTENT_LANDING.md (HARD_BANNED outright, NEGATION_ONLY unless
    negated nearby) -- applied here to web/landing.html itself.
    NoBannedCustomerVocabulary above already covers the narrower
    web/-wide HARD_BANNED-only list; this adds the NEGATION_ONLY half
    (edge/guaranteed/win-probability/etc.) that class does not check."""

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
