"""The kennel-first landing page (web/landing.html, web/js/landing-home.js, web/css/landing-home.css), 2026-10-20.

The brief (docs/design/KENNEL_FIRST_BRIEF.md): the product is "create your own AI betting hound, then watch it bet, train it, show it
off, or take it out back". So the landing page is that sentence: a headline, one primary button ("Find your hound"), a text link ("Build
from a sentence"), a strip of real hounds, three steps, the founding line, and the footer. About a dozen words above the fold; the
compliance text once, in the shared footer; everything the page used to carry lives on web/desk.html (tests/test_landing_first_screen.py
and the other test_landing_* files pin that page).

Static half: the markup read as text. Behavioural half: landing-home.js run under node against a fake DOM built from the real markup and
the real leaderboard payload (tests/hounds_web_fixtures.py).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_page

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
HTML = (WEB / "landing.html").read_text(encoding="utf-8")
MARKUP = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
MAIN = re.search(r"<main>.*?</main>", MARKUP, re.S).group(0)
LANDING_JS = (WEB / "js" / "landing.js").read_text(encoding="utf-8")
HOME_JS = (WEB / "js" / "landing-home.js").read_text(encoding="utf-8")
CSS = (WEB / "css" / "landing-home.css").read_text(encoding="utf-8")


def visible(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", text).strip()


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def at(needle: str) -> int:
    i = MARKUP.find(needle)
    assert i >= 0, needle
    return i


class TheFirstScreen(unittest.TestCase):
    TITLE = "Create your own AI betting hound."

    def test_the_one_h1_is_the_headline_verbatim(self):
        h1 = re.search(r'<h1 class="kh__title" data-hook="kh-title">(.*?)</h1>', MARKUP, re.S)
        self.assertEqual(visible(h1.group(1)), self.TITLE)
        self.assertEqual(MARKUP.count("<h1"), 1)

    def test_about_a_dozen_words_sit_above_the_fold(self):
        hero = re.search(r'<section class="kh".*?</section>', MARKUP, re.S).group(0)
        copy = visible(re.sub(r'<div class="kh__cta">.*?</div>', "", hero, flags=re.S))
        self.assertLessEqual(len(copy.split()), 12, copy)

    def test_one_primary_button_and_one_text_link(self):
        self.assertEqual(MAIN.count("btn--primary"), 1)
        quiz = re.search(r'<a\b[^>]*data-hook="cta-kennel-quiz"[^>]*>(.*?)</a>', MAIN, re.S)
        self.assertEqual(visible(quiz.group(1)), "Find your hound")
        self.assertIn('href="quiz.html?start=1"', quiz.group(0))
        self.assertIn("btn--primary", quiz.group(0))
        build = re.search(r'<a\b[^>]*data-hook="cta-kennel-build"[^>]*>(.*?)</a>', MAIN, re.S)
        self.assertEqual(visible(build.group(1)), "Build from a sentence")
        self.assertIn('href="build-a-hound.html"', build.group(0))
        self.assertNotIn("btn", build.group(0))                    # a text link, not a button
        # data-hook starts with "cta", so landing.js's delegated listener counts both clicks
        self.assertIn("closest(\"[data-hook^='cta']\")", LANDING_JS)

    def test_the_funnel_hooks_still_exist_exactly_once_each(self):
        self.assertEqual(MARKUP.count('data-hook="cta-primary"'), 1)       # the free-account button in the bar (nav files are another lane's)
        for hook in ("cta-kennel-quiz", "cta-kennel-build"):
            self.assertEqual(MARKUP.count(f'data-hook="{hook}"'), 1, hook)

    def test_the_page_reads_in_order_hero_strip_steps_offer_footer(self):
        order = ['data-hook="landing-header"', 'data-hook="kennel-hero"', 'data-hook="kh-strip"', 'data-hook="landing-steps"',
                 'data-hook="kh-offer"', 'data-hook="landing-footer"']
        positions = [at(n) for n in order]
        self.assertEqual(positions, sorted(positions))


class TheStepsTheStripAndTheOffer(unittest.TestCase):
    def test_how_it_works_is_three_steps_create_watch_train_or_take_it_out_back(self):
        how = re.search(r'<section[^>]*data-hook="landing-steps".*?</section>', MARKUP, re.S).group(0)
        titles = [visible(t) for t in re.findall(r"<h3>(.*?)</h3>", how, re.S)]
        self.assertEqual(titles, ["Create it", "Watch it bet", "Train it or take it out back"])
        self.assertEqual(how.count('data-hook="how-step"'), 3)

    def test_the_strip_is_filled_by_a_script_and_the_markup_names_no_figure(self):
        strip = re.search(r'<section[^>]*data-hook="kh-strip".*?</section>', MARKUP, re.S).group(0)
        self.assertNotRegex(visible(strip), r"[+-]?\d")
        self.assertIn('href="hounds.html"', strip)
        self.assertIn("mountHome", LANDING_JS)
        self.assertIn('from "./landing-home.js"', LANDING_JS)
        self.assertIn('apiGet("/hounds")', HOME_JS)

    def test_the_founding_line_starts_hidden_and_comes_from_the_offer_endpoint_only(self):
        tag = re.search(r'<p class="kh-offer" data-hook="kh-offer"([^>]*)>', MARKUP).group(1)
        self.assertIn("hidden", tag)
        self.assertNotRegex(MAIN, r"\$\s?\d")                      # no price typed into the markup: no seat, no line
        self.assertIn("loadFoundingOffer", HOME_JS)
        self.assertIn("foundingOfferLine", HOME_JS)
        pricing = (WEB / "js" / "pricing.js").read_text(encoding="utf-8")
        self.assertIn('apiGet("/billing/offer")', pricing)


class TheRestMovedOrWasCut(unittest.TestCase):
    def test_nothing_the_old_page_carried_is_left_on_it(self):
        for gone in ('data-hook="hero-proof"', 'data-hook="pricing"', 'data-hook="faq"', 'data-hook="what-you-get"', 'data-hook="last-card"',
                     'data-hook="sports-covered"', 'data-hook="lb-board"', 'data-hook="lb-race"', 'data-hook="kennels-card"',
                     'data-hook="cta-bottom"'):
            self.assertNotIn(gone, MARKUP, gone)

    def test_the_footer_links_every_other_page_and_the_desk_pages_exist(self):
        footer = MARKUP.split('data-hook="landing-footer"')[1]
        for href in ("hounds.html", "kennels.html", "live.html", "learning.html", "desk.html", "sample.html", "desk.html#pricing", "desk.html#faq"):
            self.assertIn(f'href="{href}"', footer, href)
        desk = (WEB / "desk.html").read_text(encoding="utf-8")
        for anchor in ('id="pricing"', 'id="faq"'):
            self.assertIn(anchor, desk)
        self.assertIn('data-hook="landing-footer"', desk)

    def test_the_disclosure_is_said_once_in_the_shared_footer_not_in_the_body_copy(self):
        text = visible(MAIN).lower()
        self.assertNotRegex(text, r"paper bets only|21\+|not advice|bet at your own risk")
        self.assertIn('data-hook="disclaimer-host"', MARKUP)
        self.assertEqual(MARKUP.count('data-hook="disclaimer-host"'), 1)

    def test_the_copy_makes_no_claim_uses_no_toy_voice_no_emoji_and_never_mentions_bet_check(self):
        text = visible(MARKUP.split("<body", 1)[1]).lower()
        for pattern in (r"\block\b", r"can'?t lose", r"sure thing", r"free money", r"\bedge\b", r"\bprofit", r"guarantee", r"make money",
                        r"bet[\s-]*check", r"\bbeta\b", r"early access", r"waitlist", r"\bnew\b", r"coming soon"):
            self.assertIsNone(re.search(pattern, text), pattern)
        self.assertNotRegex(MARKUP, "[\U0001F300-\U0001FAFF☀-➿]")
        self.assertNotIn("<svg", MAIN)

    def test_every_in_page_link_target_exists_and_every_local_link_goes_to_a_real_page(self):
        ids = set(re.findall(r'\sid="([^"]+)"', MARKUP))
        for target in set(re.findall(r'href="#([^"]+)"', MARKUP)):
            self.assertIn(target, ids)
        for href in set(re.findall(r'href="([^"#?:]+\.html)', MARKUP)):
            self.assertTrue((WEB / href).is_file(), href)

    def test_the_stylesheet_loads_last_after_the_app_shell_css_and_every_animation_is_motion_guarded(self):
        links = re.findall(r'<link rel="stylesheet" href="(css/[^"]+)"', MARKUP)
        self.assertEqual(links[-1], "css/landing-home.css")
        self.assertLess(links.index("css/app.css"), links.index("css/landing.css"))
        guarded = CSS.split("@media (prefers-reduced-motion: no-preference)")
        self.assertEqual(len(guarded), 2)
        self.assertNotRegex(guarded[0], r"animation\s*:")
        self.assertIn("animation:", guarded[1])


class TheFunnelIsStillCounted(unittest.TestCase):
    def test_the_landing_page_sends_landing_view_and_counts_cta_clicks_and_keeps_the_first_touch(self):
        home = LANDING_JS.split("function bootHome()")[1]
        self.assertIn('trackFunnelEvent("landing_view", arrivalProperties())', home)
        self.assertIn("trackCtaClicks()", home)
        self.assertIn("captureFirstTouch()", home)

    def test_the_desk_page_sends_a_public_page_view_not_a_second_landing_view(self):
        desk_part = LANDING_JS.split("function boot()")[1].split("function bootHome()")[0]
        self.assertIn('trackPublicPageView("desk")', desk_part)
        self.assertNotIn('"landing_view"', desk_part)
        self.assertRegex(re.search(r'trackPublicPageView\("(.*?)"\)', desk_part).group(1), r"^[a-z0-9][a-z0-9-]{0,31}$")


def stored_offer(left=12, available=True, cents=1499, cap=50):
    return {"founding": {"price_cents": cents, "cap": cap, "taken": cap - left, "left": left, "reserved": 0, "available": available},
            "standard": {"price_cents": 1999}}


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStripRuns(unittest.TestCase):
    def routes(self, **over):
        r = {k: list(v) for k, v in F.routes().items()}
        r["/billing/offer"] = [200, stored_offer()]
        r.update(over)
        return r

    def page(self, routes=None, **kw):
        return run_page("landing_home", routes=self.routes() if routes is None else routes, **kw)

    QS = [q("n", "[data-hook='kh-hound']", "count"), q("names", "[data-hook='kh-name']", "texts"), q("rec", "[data-hook='kh-record']", "texts"),
          q("ret", "[data-hook='kh-return']", "texts"), q("links", ".kh-hound__link", "attrs", attr="href"),
          q("empty", "[data-hook='kh-strip-row'] .kh-strip__empty", "texts")]

    def test_the_strip_shows_the_hounds_the_leaderboard_ranks_first_with_record_and_bet_count(self):
        out = self.page(queries=self.QS)["final"]
        self.assertEqual(out["n"], 5)
        self.assertEqual(out["empty"], [])
        self.assertEqual(len(out["names"]), 5)
        for rec in out["rec"]:
            self.assertRegex(rec, r"^\d+-\d+(-\d+)? · \d+ bets?$")          # a record with its sample size, always
        for ret in out["ret"]:
            self.assertRegex(ret, r"return$")
        for link in out["links"]:
            self.assertTrue(link.startswith("hound.html?id="), link)

    def test_it_agrees_with_the_board_the_old_landing_page_showed(self):
        out = self.page(queries=self.QS + [q("ids", "[data-hook='kh-hound']", "attrs", attr="data-hound")])
        board = run_page("landing_board", routes={k: list(v) for k, v in F.routes().items()},
                         queries=[q("ids", "[data-hook='lb-board'] .lbrow", "attrs", attr="data-hound")])
        self.assertEqual(out["final"]["ids"], board["final"]["ids"])

    def test_with_no_answer_it_says_so_and_names_no_figure(self):
        routes = self.routes()
        del routes["/hounds"]
        out = self.page(routes=routes, queries=self.QS)["final"]
        self.assertEqual(out["n"], 0)
        self.assertEqual(out["empty"], ["The leaderboard is not answering right now."])

    def test_a_server_still_working_says_that_and_nothing_else(self):
        warming = {"hounds": [], "warming_up": True, "retry_after_seconds": 5, "message": "warming", "paper_only": True}
        out = self.page(routes=self.routes(**{"/hounds": [200, warming]}), queries=self.QS)["final"]
        self.assertEqual((out["n"], out["empty"]), (0, ["The leaderboard is warming up. Numbers in a few seconds."]))

    def test_a_board_with_nobody_ranked_yet_names_the_bar_not_a_figure_about_a_hound(self):
        board = F.leaderboard(True)
        board["hounds"] = []
        out = self.page(routes=self.routes(**{"/hounds": [200, board]}), queries=self.QS)["final"]
        self.assertEqual(out["n"], 0)
        self.assertIn("settled bets yet", out["empty"][0])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheFoundingLineRuns(unittest.TestCase):
    def line(self, offer):
        routes = {k: list(v) for k, v in F.routes().items()}
        if offer is not None:
            routes["/billing/offer"] = [200, offer]
        return run_page("landing_home", routes=routes, queries=[
            q("hidden", "[data-hook='kh-offer']", "hidden"), q("line", "[data-hook='kh-offer-line']")])["final"]

    def test_a_real_seat_shows_the_server_s_own_numbers(self):
        out = self.line(stored_offer(left=12))
        self.assertFalse(out["hidden"])
        self.assertEqual(out["line"], "Founding member: $14.99/mo for life · 12 of 50 left")

    def test_no_seat_no_line_and_never_a_guess(self):
        for name, offer in (("sold out", stored_offer(left=0, available=False)), ("a seat held mid-checkout", stored_offer(left=3, available=False)),
                            ("not configured", {"founding": None, "standard": {"price_cents": 1999}}),
                            ("malformed", {"founding": {"available": True, "price_cents": "x"}}), ("the endpoint is down", None)):
            with self.subTest(case=name):
                out = self.line(offer)
                self.assertTrue(out["hidden"])
                self.assertEqual(out["line"], "")


if __name__ == "__main__":
    unittest.main()
