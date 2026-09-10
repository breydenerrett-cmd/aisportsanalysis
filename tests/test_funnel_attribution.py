"""Where a visitor came from, and which button they pressed.

WHY THIS FILE EXISTS
---------------------
The funnel recorded two things: somebody arrived, and somebody later
reached the signup form. Nothing in between and nothing about origin -- no
UTM, no referrer, no CTA-click event. The landing page carries FIVE calls
to action, four with identical copy pointing at the same destination, so
"which button works" was unanswerable. That is the single question the page
exists to answer and every copy decision depends on it.
docs/CONVERSION_INSTRUMENTATION_AUDIT.md specified this fix and it was
never built.

THE BUG THAT WOULD HAVE MADE THE FIX WORTHLESS
-----------------------------------------------
`GET /` 307-redirects to /web/landing.html and DROPPED THE QUERY STRING.
Every campaign link anyone will ever share points at the bare origin --
linehound.app/?utm_source=reddit -- so web/js/landing.js read an empty
window.location.search and wrote an unattributed landing view.

The whole feature would have shipped, passed its tests, and silently
measured nothing: every visitor an organic one, on the exact metric the
outreach plan is steered by. Found by sending a real UTM link at a running
server and reading the row it wrote (`properties_json` came back `{}`), not
by reading the code -- which is the only way this class of bug is ever
found.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LANDING_JS = REPO / "web" / "js" / "landing.js"
APP_PY = REPO / "api" / "app.py"


def _code(path):
    """Comments stripped -- both files now document this incident by name."""
    text = path.read_text(encoding="utf-8")
    out, in_block, in_doc = [], False, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("/*"):
            in_block = True
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("//") or s.startswith("*") or s.startswith("#"):
            continue
        if s.startswith('"""') and path.suffix == ".py":
            in_doc = not in_doc or s.count('"""') > 1 and not in_doc
            continue
        out.append(line)
    return "\n".join(out)


class TheRedirectCarriesTheCampaign(unittest.TestCase):

    def test_root_redirect_preserves_the_query_string(self):
        code = _code(APP_PY)
        block = code.split("def root_redirect", 1)
        self.assertEqual(2, len(block), "root_redirect not found")
        body = block[1].split("def ", 1)[0]
        self.assertIn("request.url.query", body,
                      "GET / drops the query string, so every UTM link "
                      "arrives stripped and reads as organic traffic")
        self.assertNotIn('url="/web/landing.html"', body,
                         "the redirect target is still a bare constant")

    def test_it_still_redirects_to_the_landing_page(self):
        """The query fix must not have changed where it points."""
        code = _code(APP_PY)
        body = code.split("def root_redirect", 1)[1].split("def ", 1)[0]
        self.assertIn("/web/landing.html", body)
        self.assertIn("307", body)


class ArrivalIsAttributed(unittest.TestCase):

    def setUp(self):
        self.code = _code(LANDING_JS)

    def test_landing_view_carries_properties(self):
        self.assertTrue(
            re.search(r'trackFunnelEvent\("landing_view",\s*\w+', self.code),
            "landing_view is still posted with no properties, so it is an "
            "unattributed tally")

    def test_utm_and_referrer_are_captured(self):
        for key in ("utm_source", "utm_medium", "utm_campaign"):
            self.assertIn(key, self.code)
        self.assertIn("referrer", self.code.lower())

    def test_only_the_referrer_host_is_stored(self):
        """"Came from reddit" is the whole question; the specific thread
        somebody was reading is none of our business."""
        self.assertIn(".host", self.code,
                      "the full referring URL is being stored rather than "
                      "just its host")

    def test_our_own_host_is_not_recorded_as_a_referral(self):
        """An internal navigation is not a referral, and would otherwise be
        the most common 'source' in the table."""
        self.assertIn("window.location.host", self.code,
                      "same-origin referrers are not filtered out")

    def test_utm_values_are_length_capped(self):
        """A crafted link must not be able to stuff the events table."""
        self.assertIn("UTM_MAX_LENGTH", self.code)
        self.assertIn("slice(0, UTM_MAX_LENGTH)", self.code)

    def test_no_cookie_or_fingerprint(self):
        for banned in ("document.cookie", "localStorage", "canvas",
                       "fingerprint"):
            self.assertNotIn(
                banned, self.code,
                f"landing.js references {banned!r}; attribution here is "
                f"limited to what the arriving URL and the browser's own "
                f"referrer header already say")


class CtaClicksAreAttributed(unittest.TestCase):

    def setUp(self):
        self.code = _code(LANDING_JS)

    def test_a_cta_click_event_is_fired(self):
        self.assertIn('trackFunnelEvent("cta_click"', self.code)

    def test_it_is_delegated_so_new_buttons_are_covered(self):
        """A per-button listener means the next CTA someone adds is
        invisible until somebody remembers to wire it."""
        self.assertIn("closest(\"[data-hook^='cta']\")", self.code)

    def test_it_never_swallows_the_navigation(self):
        """An analytics call must not be able to eat a click on the button
        that makes us money."""
        block = self.code.split("function trackCtaClicks", 1)[1] \
                         .split("\n}", 1)[0]
        self.assertNotIn("preventDefault", block)
        self.assertNotIn("stopPropagation", block)

    def test_the_recorded_cta_is_the_data_hook_not_free_text(self):
        """Bounded cardinality, and a compromised client cannot fill the
        table with junk."""
        block = self.code.split("function trackCtaClicks", 1)[1] \
                         .split("\n}", 1)[0]
        self.assertIn("getAttribute(\"data-hook\")", block)
        self.assertNotIn("textContent", block)


class EveryCtaGoesWhereItPromises(unittest.TestCase):
    """All four "Try 3 Bet Checks free" buttons pointed at #/signup -- an
    email form -- and `#/betcheck` appeared ZERO times on the page. The one
    offer the page makes was the one thing no button on it delivered.
    docs/CONVERSION_INSTRUMENTATION_AUDIT.md flagged this and it was never
    fixed."""

    def setUp(self):
        self.html = (REPO / "web" / "landing.html").read_text(encoding="utf-8")
        self.links = re.findall(
            r'<a[^>]*href="([^"]+)"[^>]*data-hook="(cta[^"]*)"[^>]*>([^<]*)<',
            self.html)

    def test_the_page_links_to_the_free_check_at_all(self):
        self.assertIn("#/betcheck", self.html,
                      "the landing page never links to the free Bet Check "
                      "it spends four buttons advertising")

    def test_bet_check_buttons_go_to_bet_check(self):
        wrong = [(hook, href) for href, hook, text in self.links
                 if "bet check" in text.lower() and "betcheck" not in href]
        self.assertEqual(
            [], wrong,
            f"CTAs promising a Bet Check point somewhere else: {wrong}")

    def test_the_paid_cta_still_goes_to_signup(self):
        """Fixing the free-check buttons must not have swept the one button
        that is actually meant to start a subscription."""
        signup = [hook for href, hook, _t in self.links if "signup" in href]
        self.assertTrue(signup,
                        "no CTA on the page leads to signup any more")


class TheServerAcceptsIt(unittest.TestCase):

    def test_cta_click_is_a_known_event_kind(self):
        from src.appstate import events
        self.assertIn(events.CTA_CLICK, events.EVENT_KINDS)

    def test_it_is_postable_by_an_anonymous_visitor(self):
        """It happens before any authenticated identity exists, so there is
        no server-side moment that could record it instead."""
        # CI runs this suite WITHOUT api/requirements.txt -- fastapi
        # lives only in api/'s dependencies (tests/test_api_boundary.py
        # exists to prove src/ never needs it). Skip rather than error,
        # so the api-less job stays green and still runs everything else
        # in this file.
        try:
            import fastapi  # noqa: F401
        except ImportError:
            self.skipTest('fastapi is not installed in this job')
        from api import funnel
        from src.appstate import events
        self.assertIn(events.CTA_CLICK, funnel.PUBLIC_FUNNEL_KINDS)

    def test_the_public_allowlist_stays_narrow(self):
        """Three kinds, all genuinely pre-identity. Anything else belongs
        server-recorded."""
        # CI runs this suite WITHOUT api/requirements.txt -- fastapi
        # lives only in api/'s dependencies (tests/test_api_boundary.py
        # exists to prove src/ never needs it). Skip rather than error,
        # so the api-less job stays green and still runs everything else
        # in this file.
        try:
            import fastapi  # noqa: F401
        except ImportError:
            self.skipTest('fastapi is not installed in this job')
        from api import funnel
        from src.appstate import events
        self.assertEqual(
            {events.LANDING_VIEW, events.SIGNUP_STARTED, events.CTA_CLICK},
            set(funnel.PUBLIC_FUNNEL_KINDS))


if __name__ == "__main__":
    unittest.main()
