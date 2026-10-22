"""The kennel page, the one navigation, the tabs and the motion rules (2026-10-19 usability pass).

Owner: "It's not clearly accessible to find a user's dogs in their kennel ... more minimalism and more fun animated UI."

  KENNEL PAGE   web/kennel.html + web/js/kennel.js, run for real under node: My kennel (signed in: a card per dog with its
                avatar, record, units, last pick, status and one-tap Unleash / Send to training / Take them out back (the burial) / Ask / Edit / Open; a "Build a dog" card; the
                empty state; the signed-out gate), a member's PUBLIC kennel (?u=, read only, a 0-bet dog included), and the
                studio drawer that reuses the builder's and the dog kit's modules.
  NAVIGATION    one component (web/js/nav.js + css/lhnav.css) on every page, right for signed in and signed out.
  TABS          the dog page's Overview / Tickets / Backtest / Ask / Locker room / Rules, and the leaderboard's Models / Kennels.
  MOTION        every animation sits inside prefers-reduced-motion: no-preference; a count-up ends on the exact text and
                does nothing at all when motion is reduced.

Skipped without node where a page is run; the static checks need none.
"""

from __future__ import annotations

import json
import re
import unittest

from src.hounds import user_spec
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page

TOKEN_KEY = "aisportsanalysis.invite_token"
SIGNED = dict(stored={TOKEN_KEY: "tok"})
PAGES = ("kennels.html", "live.html", "hounds.html", "hound.html", "build-a-hound.html", "learning.html", "kennel.html", "landing.html", "desk.html", "why-we-paused.html",
         "postseason.html", "sample.html", "index.html", "graveyard.html", "quiz.html", "room.html", "interview.html")
# owner ruling 2026-10-20 kennel-first: the static (signed-out) nav is Leaderboard, Live, Sign in and one primary "Make your first hound" button;
# a member's five places (My Kennel, Create, Live, Leaderboard, Account) are built by nav.js
LINKS = [("hounds.html", "Leaderboard"), ("live.html", "Live")]
MEMBER_LINKS = [("kennel.html", "My Kennel"), ("quiz.html", "Create"), ("live.html", "Live"), ("hounds.html", "Leaderboard")]


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def dog(did="u-1", name="Underdog Gus", wins=0, losses=0, bets=0, units=None, last=None, **over):
    out = {"id": did, "name": name, "tagline": "Barks at the books", "status": "running", "version_no": 1, "look": None,
           "sports": ["mlb"], "record": {"bets": bets, "wins": wins, "losses": losses, "pushes": 0, "units_average_price": units},
           "settled": wins + losses, "open_bets": 0, "new": bets == 0, "last_pick": last, "page_href": f"hound.html?id={did}",
           "retired": False, "builder_href": f"build-a-hound.html?from={did}",
           # the dog's paper account (src/hounds/bankroll.py): 1 unit is $10 of the shared $1,000, so units and % agree
           "bankroll": {"start": 1000.0, "current": 1000.0 + (units or 0.0) * 10, "pnl_usd": (units or 0.0) * 10,
                        "return_pct": units or 0.0, "units_total": units or 0.0, "bets": bets, "settled": wins + losses,
                        "small_sample": True, "small_sample_min": 20, "basis": "average_price"}}
    out.update(over)
    return out


def mine(dogs, handle="handler-21e8"):
    return [200, {"handle": handle, "display": "Handler 21E8", "dog_count": len([d for d in dogs if not d["retired"]]),
                  "dogs": dogs, "season": {"id": "s2", "label": "Season 2"}, "paper_only": True}]


def public(dogs, handle="handler-21e8"):
    return [200, {"handle": handle, "display": "Handler 21E8", "dog_count": len(dogs), "best": None, "dogs": dogs,
                  "season": {"id": "s2", "label": "Season 2"}, "paper_only": True}]


def kit(did="u-1", **over):
    out = {"dog_id": did, "kind": "user", "name": "Underdog Gus", "status": "running", "is_owner": True, "signed_in": True,
           "can_fire": True, "can_record_manual": True, "can_customize": True, "can_suggest": False, "look": None,
           "feedback": {"good": 0, "bad": 0, "notes": 0, "by_kind": {}, "by_target": {}, "suggestions": 0},
           "manual": {"limit_per_day": 5, "remaining_today": 5}, "builder_href": f"build-a-hound.html?from={did}", "paper_only": True}
    out.update(over)
    return out


# ---------------------------------------------------------------------------------------------------
# static: the navigation is the same component on every page
# ---------------------------------------------------------------------------------------------------

class EveryPageHasTheOneNavigation(unittest.TestCase):
    def test_each_page_carries_the_component_the_stylesheet_and_the_module(self):
        for name in PAGES:
            html = read(name)
            with self.subTest(page=name):
                self.assertEqual(html.count('class="lh-nav"'), 1)
                self.assertIn('href="css/lhnav.css"', html)
                self.assertIn('<script type="module" src="js/nav.js"></script>', html)
                self.assertNotIn('class="site-nav', html.split("<main")[0].split("<body")[1], "the old per-page nav is gone")

    def test_each_page_names_the_same_public_places_in_the_same_order(self):
        for name in PAGES:
            html = read(name)
            bar = re.search(r'<nav class="lh-nav__links".*?</nav>', html, re.S)
            self.assertIsNotNone(bar, name)
            found = re.findall(r'<a href="([^"]+)" data-nav="[a-z]+"[^>]*>([^<]+)</a>', bar.group(0))
            self.assertEqual(found, LINKS, name)

    def test_each_page_has_the_wordmark_and_a_signed_out_sign_in_in_the_markup(self):
        for name in PAGES:
            html = read(name)
            self.assertIn('data-hook="brand-mark"', html, name)
            self.assertRegex(html, r'<a class="lh-nav__signin" href="index.html#/signin" data-hook="nav-signin">Sign in</a>', name)

    def test_the_member_app_keeps_its_own_tab_bar_so_the_component_adds_none(self):
        self.assertIn('data-bottom="off"', read("index.html"))
        self.assertNotIn('data-bottom="off"', read("hounds.html"))

    def test_kennels_is_its_own_page_apart_from_the_leaderboard(self):
        html = read("kennels.html")
        self.assertIn('data-hook="kennels-index"', html)
        self.assertIn('<script type="module" src="js/kennels-index.js"></script>', html)
        self.assertNotIn("hounds-page.js", html)                     # no leaderboard on it
        self.assertIn('data-nav="leaderboard" aria-current="page"', html)      # # owner ruling 2026-10-20 kennel-first: Kennels is the Leaderboard's second view
        self.assertIn('href="kennel.html" data-hook="kennels-mine"', html)

    def test_the_landing_page_is_the_quiz_button_and_the_kennel_pages_are_one_footer_link_away(self):
        # kennel-first rebuild 2026-10-20: the kennels band is gone from the landing page; the footer links the kennel pages
        html = read("landing.html")
        self.assertNotIn('data-hook="kennels-card"', html)
        # owner ruling 2026-10-21 (kennel front): the landing is a welcome with exactly two choices, one of which opens the quiz
        self.assertRegex(html, r'<a class="kh-choice kh-choice--primary" href="quiz.html\?start=1" data-hook="cta-kennel-quiz">')
        footer = html.split('data-hook="landing-footer"')[1]
        for href in ("kennels.html", "hounds.html", "live.html", "learning.html", "desk.html"):
            self.assertIn(f'href="{href}"', footer)

    def test_the_landing_page_keeps_its_own_make_your_first_hound_button_in_the_bar(self):
        html = read("landing.html")
        # # owner ruling 2026-10-20 kennel-first: the bar's one primary button is "Make your first hound" (the quiz); landing keeps its own node and funnel hook
        self.assertRegex(html, r'<a class="lh-btn lh-btn--solid lh-btn--lg" href="quiz.html" data-hook="cta-primary" data-nav-extra>Make your first hound</a>')

    def test_the_quiz_and_the_builder_carry_no_button_in_their_bar(self):
        for name in ("quiz.html", "build-a-hound.html"):
            self.assertNotIn('data-hook="nav-cta"', read(name), name)

    def test_every_page_carries_the_canonical_nav_block(self):
        """scripts/apply_kennel_nav_block.py --check: the static nav of every page is the kennel-first shape."""
        import subprocess, sys
        proc = subprocess.run([sys.executable, str(WEB.parent / "scripts" / "apply_kennel_nav_block.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


# ---------------------------------------------------------------------------------------------------
# the navigation, run
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheNavigationRuns(unittest.TestCase):
    QS = [q("links", ".lh-nav__links a", "texts"), q("hrefs", ".lh-nav__links a", "attrs", attr="href"),
          q("current", ".lh-nav [aria-current='page']", "texts"),
          q("primaries", ".lh-nav .lh-btn--solid", "texts"), q("kennel_btn", "[data-hook='nav-mykennel']", "texts"),
          q("kennel_btn_href", "[data-hook='nav-mykennel']", "attr", attr="href"), q("kennel_btn_class", "[data-hook='nav-mykennel']", "attr", attr="class"),
          q("signin_class", "[data-hook='nav-signin']", "attr", attr="class"),
          q("tab_primary", "[data-hook='tab-mykennel']", "texts"), q("tab_primary_class", "[data-hook='tab-mykennel']", "attr", attr="class"),
          q("tab_order", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="data-nav"), q("signin", "[data-hook='nav-signin']", "count"),
          q("cta", "[data-hook='nav-cta']", "count"), q("cta_href", "[data-hook='nav-cta']", "attr", attr="href"), q("cta_class", "[data-hook='nav-cta']", "attr", attr="class"),
          q("account", "[data-hook='nav-account']", "count"), q("account_href", "[data-hook='nav-account']", "attr", attr="href"),
          q("tabs", "[data-hook='site-tabbar'] .lh-tab", "texts"), q("tabhrefs", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="href"),
          q("bars", ".lh-nav", "count"), q("area", "[data-hook='nav-account-area']", "attr", attr="data-signed-in")]

    def run_nav(self, **kw):
        kw.setdefault("page_html", "hounds.html")
        kw.setdefault("queries", self.QS)
        return run_page("nav", **kw)

    def test_signed_out_is_leaderboard_live_a_sign_in_link_and_one_big_make_your_first_hound_button(self):
        # owner ruling 2026-10-21 (kennel front): the visitor's one primary is "Make your first hound", with "Sign in" a quiet text link beside it
        f = self.run_nav()["final"]
        self.assertEqual(f["links"], [t for _, t in LINKS])
        self.assertEqual(f["hrefs"], [h for h, _ in LINKS])
        self.assertEqual((f["signin"], f["cta"], f["cta_href"], f["account"], f["bars"], f["area"]), (1, 1, "quiz.html", 0, 1, "false"))
        self.assertEqual(f["tabs"], ["Leaderboard", "Live", "Sign in", "Make your first hound"])
        self.assertEqual(f["tabhrefs"][-2:], ["index.html#/signin", "quiz.html"])
        self.assertEqual(f["primaries"], ["Make your first hound"])                                 # exactly one filled button in the bar
        self.assertNotIn("lh-btn", f["signin_class"])                                               # Sign in is a text link, not a button
        self.assertIn("lh-btn--lg", f["cta_class"])

    def test_signed_in_has_my_kennel_as_the_one_primary_button_and_the_other_places_quiet(self):
        # owner ruling 2026-10-21 (kennel front): "My Kennel doesn't stand out. It's the same size as Live / Leaderboard / Create."
        # My Kennel is the one big filled button top-right beside the Account avatar; Create, Live and Leaderboard are quiet text links on the left.
        f = self.run_nav(**SIGNED)["final"]
        self.assertEqual((f["signin"], f["cta"], f["account"], f["area"]), (0, 0, 1, "true"))
        self.assertEqual(f["links"], ["Create", "Live", "Leaderboard"])
        self.assertEqual(f["hrefs"], ["quiz.html", "live.html", "hounds.html"])
        self.assertEqual(f["primaries"], ["My Kennel"])                                           # the only filled button in the bar
        self.assertEqual((f["kennel_btn"], f["kennel_btn_href"]), (["My Kennel"], "kennel.html"))
        self.assertIn("lh-btn--solid", f["kennel_btn_class"])
        self.assertIn("lh-btn--lg", f["kennel_btn_class"])
        self.assertEqual(f["account_href"], "index.html#/account")
        # the phone tab bar is the same five with My Kennel the filled centre tab
        self.assertEqual(f["tabs"], ["Create", "Live", "My Kennel", "Leaderboard", "Account"])
        self.assertEqual(f["tab_order"][2], "mykennel")
        self.assertEqual(f["tab_primary"], ["My Kennel"])
        self.assertIn("lh-tab--primary", f["tab_primary_class"])
        self.assertEqual(f["tabhrefs"], ["quiz.html", "live.html", "kennel.html", "hounds.html", "index.html#/account"])

    def test_my_kennel_is_marked_current_on_the_kennel_page(self):
        f = self.run_nav(page_html="kennel.html", pathname="/web/kennel.html", **SIGNED)["final"]
        self.assertEqual(f["current"][0], "My Kennel")

    def test_the_bar_is_never_more_than_five_places(self):
        for kw in ({}, SIGNED):
            f = self.run_nav(**kw)["final"]
            self.assertLessEqual(len(f["links"]) + f["account"], 5)
            self.assertLessEqual(len(f["tabs"]), 5)

    def test_the_wordmark_goes_home_to_my_kennel_for_a_member_and_to_the_landing_page_for_a_visitor(self):
        qs = [q("home", ".lh-nav__brand", "attr", attr="href")]
        self.assertEqual(self.run_nav(queries=qs)["final"]["home"], "landing.html")
        self.assertEqual(self.run_nav(queries=qs, **SIGNED)["final"]["home"], "kennel.html")

    def test_the_current_place_follows_the_page_and_the_kennel_page_follows_its_query(self):
        # a member's bar names all four links; the visitor's has only Leaderboard and Live
        cases = [("hounds.html", "/web/hounds.html", "", ["Leaderboard"]), ("kennels.html", "/web/kennels.html", "", ["Leaderboard"]),
                 ("hound.html", "/web/hound.html", "?id=closer", ["Leaderboard"]), ("graveyard.html", "/web/graveyard.html", "", ["Leaderboard"]),
                 ("build-a-hound.html", "/web/build-a-hound.html", "", ["Create"]), ("quiz.html", "/web/quiz.html", "", ["Create"]),
                 ("learning.html", "/web/learning.html", "", ["My Kennel"]),          # the Training camp is part of My Kennel
                 ("live.html", "/web/live.html", "", ["Live"]), ("kennel.html", "/web/kennel.html", "?u=handler-1", ["Leaderboard"]),
                 ("kennel.html", "/web/kennel.html", "", ["My Kennel"])]
        for page, path, search, want in cases:
            with self.subTest(path=path, search=search):
                got = self.run_nav(page_html=page, pathname=path, search=search, **SIGNED)["final"]["current"]
                self.assertEqual(got, want)

    def test_the_old_data_current_keys_still_name_the_right_place(self):
        out = run_js('import { normalizePlace } from "./nav.js";\nconsole.log(JSON.stringify(["build", "camp", "kennels", "mykennel", "live"].map(normalizePlace)));')
        self.assertEqual(out, ["create", "mykennel", "leaderboard", "mykennel", "live"])

    def test_the_member_app_gets_no_bottom_bar(self):
        f = run_page("nav", page_html="index.html", queries=[q("tabs", "[data-hook='site-tabbar']", "count"),
                                                              q("bars", ".lh-nav", "count")])["final"]
        self.assertEqual((f["tabs"], f["bars"]), (0, 1))

    def test_the_landing_button_stays_in_the_bar_for_a_visitor_and_leaves_for_a_member(self):
        visitor = run_page("nav", page_html="landing.html", queries=[q("cta", ".lh-nav [data-hook='cta-primary']", "count"),
                                                                      q("default", ".lh-nav [data-hook='nav-cta']", "count")])["final"]
        member = run_page("nav", page_html="landing.html", **SIGNED, queries=[q("cta", ".lh-nav [data-hook='cta-primary']", "count")])["final"]
        self.assertEqual((visitor["cta"], visitor["default"], member["cta"]), (1, 0, 0))

    def test_a_member_who_opens_the_landing_page_is_sent_to_my_kennel(self):
        out = run_page("nav", page_html="landing.html", pathname="/web/landing.html", **SIGNED, queries=[q("bars", ".lh-nav", "count")])
        self.assertEqual(out["navigations"], ["kennel.html"])
        stay = run_page("nav", page_html="landing.html", pathname="/web/landing.html", search="?stay=1", **SIGNED, queries=[q("bars", ".lh-nav", "count")])
        self.assertEqual(stay["navigations"], [])
        visitor = run_page("nav", page_html="landing.html", pathname="/web/landing.html", queries=[q("bars", ".lh-nav", "count")])
        self.assertEqual(visitor["navigations"], [])

    def test_the_home_rule_sends_a_member_from_the_empty_app_shell_and_never_from_an_explicit_route(self):
        out = run_js(
            'import { memberHomeTarget as go } from "./home-route.js";\n'
            'const w = (signedIn, pathname, hash = "", search = "") => ({ signedIn, pathname, hash, search });\n'
            'console.log(JSON.stringify([go(w(true, "/web/index.html")), go(w(true, "/web/index.html", "#/")), go(w(true, "/web/index.html", "#/today")),\n'
            '  go(w(true, "/web/index.html", "#/record-card")), go(w(false, "/web/index.html")), go(w(true, "/web/landing.html")),\n'
            '  go(w(true, "/web/landing.html", "", "?stay=1")), go(w(true, "/web/hounds.html"))]));')
        self.assertEqual(out, ["kennel.html", "kennel.html", None, None, None, "kennel.html", None, None])


# ---------------------------------------------------------------------------------------------------
# the kennel page
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class MyKennel(unittest.TestCase):
    CARDS = "[data-hook='kennel-dog']"

    def page(self, routes, **kw):
        return run_page("kennel", routes=routes, **kw)

    def test_signed_out_is_asked_to_sign_in_or_to_see_the_leaderboard(self):
        out = self.page({}, queries=[q("gate", "[data-hook='kennel-signin']"), q("cards", self.CARDS, "count"),
                                      q("signin", "[data-hook='kennel-signin-link']", "attr", attr="href"),
                                      q("browse", "[data-hook='kennel-browse']", "attr", attr="href")])
        f = out["final"]
        self.assertIn("Sign in to see your hounds", f["gate"])      # # owner ruling 2026-10-20 kennel-first
        self.assertEqual((f["cards"], f["signin"], f["browse"]), (0, "index.html#/signin", "hounds.html"))
        self.assertEqual(out["gets"], [], "a visitor never asks for someone's kennel")

    def test_each_hound_is_a_card_with_its_numbers_status_and_the_one_tap_actions(self):
        dogs = [dog("u-1", "Underdog Gus", wins=3, losses=1, bets=4, units=1.8, last={"selection": "Red Sox ML", "result": "won"}),
                dog("u-2", "Totals Tina"), dog("u-3", "Slumpy", wins=0, losses=2, bets=2, units=-2.0, last={"selection": "Over 8", "result": "lost"})]
        out = self.page({"/hounds/kennels/mine": mine(dogs)}, **SIGNED, queries=[
            q("names", f"{self.CARDS} [data-hook='dog-name']", "texts"), q("records", "[data-hook='dog-record']", "texts"),
            q("bank", "[data-hook='dog-bankroll']", "texts"), q("ret", "[data-hook='dog-return']", "texts"),
            q("status", "[data-hook='dog-status']", "texts"),
            q("last", "[data-hook='dog-last']", "texts"), q("moods", self.CARDS, "attrs", attr="data-mood"),
            q("avatars", f"{self.CARDS} svg.dk-badge", "count"), q("avatar_moods", f"{self.CARDS} svg.dk-badge", "attrs", attr="data-mood"),
            q("fire", "[data-hook='dog-action-fire']", "count"), q("ask", "[data-hook='dog-action-ask']", "count"),
            q("edit", "[data-hook='dog-action-edit']", "count"), q("open", "[data-hook='dog-name']", "attrs", attr="href"),
            q("build_card", "[data-hook='kennel-build-card']", "count"), q("create", "[data-hook='kennel-build']", "attr", attr="href"),
            q("title", "[data-hook='kennel-title']"), q("sub", "[data-hook='kennel-sub']"), q("today", "[data-hook='dog-today']", "texts"),
            q("count_attr", "[data-hook='dog-bankroll']", "attrs", attr="data-count"),
            q("small", "[data-hook='dog-bankroll']", "attrs", attr="title")])
        f = out["final"]
        self.assertEqual(f["names"], ["Underdog Gus", "Totals Tina", "Slumpy"])
        self.assertEqual(f["records"], ["3-1", "0-0", "0-2"])
        self.assertEqual(f["bank"], ["$1,018", "$1,000", "$980"])                  # every dog starts with the same $1,000
        self.assertEqual(f["ret"], ["+1.8%", "0.0%", "-2.0%"])
        self.assertTrue(all(s.startswith("Ranked in full at") for s in f["small"]), f["small"])   # owner ruling 2026-10-20, complete-product positioning
        self.assertEqual(f["status"], ["Running", "Running", "Running"])      # owner rule 2026-10-21: no "New" badge; a dog with no bet yet is Running
        self.assertEqual(f["last"][0], "Last pick: Red Sox ML (won)")
        self.assertIn("No picks yet", f["last"][1])
        self.assertEqual(f["moods"], ["happy", "idle", "slump"])                    # a win wiggles, a loss slumps
        self.assertEqual((f["avatars"], f["avatar_moods"]), (3, ["happy", "idle", "slump"]))
        # # owner ruling 2026-10-20 kennel-first: the card offers Unleash, Send to training, Edit and Take them out back, nothing else; Create a hound is one quiet button
        self.assertEqual((f["fire"], f["ask"], f["edit"], f["build_card"], f["create"]), (3, 0, 3, 0, "quiz.html"))
        self.assertEqual(f["open"], ["hound.html?id=u-1", "hound.html?id=u-2", "hound.html?id=u-3"])
        self.assertEqual((f["title"], f["sub"]), ("My Kennel", "3 hounds"))
        self.assertEqual(f["today"], ["Nothing open right now", "Waiting on its first game", "Nothing open right now"])
        self.assertEqual(f["count_attr"], ["1", "1", "1"])                            # the figures count up when they enter view
        self.assertEqual(out["gets"][0].split("?")[0], "/hounds/kennels/mine")

    def test_a_zero_bet_dog_is_listed_with_its_status_and_no_new_badge(self):
        """Owner rule 2026-10-21 (docs/VOICE.md, complete-product positioning): no "new" or beta wording. A dog with no bet yet
        shows its status, Running, and the line under its avatar says it is waiting on its first game."""
        out = self.page({"/hounds/kennels/mine": mine([dog("u-d151fe52c7", "Jsmooth"), dog("u-fcc8e8c168", "Jsmooth27")])}, **SIGNED,
                        queries=[q("names", f"{self.CARDS} [data-hook='dog-name']", "texts"), q("status", "[data-hook='dog-status']", "texts"),
                                 q("keys", "[data-hook='dog-status']", "attrs", attr="data-status"),
                                 q("today", "[data-hook='dog-today']", "texts"), q("pills", f"{self.CARDS} .kn-pill", "texts")])
        f = out["final"]
        self.assertEqual(f["names"], ["Jsmooth", "Jsmooth27"])
        self.assertEqual(f["status"], ["Running", "Running"])
        self.assertEqual(f["keys"], ["running", "running"])
        self.assertEqual(f["today"], ["Waiting on its first game"] * 2)
        self.assertNotIn("New", f["pills"])
        self.assertFalse(re.search(r"new", " ".join(f["status"] + f["today"]), re.I))

    def test_the_new_badge_is_gone_from_the_card_code_and_its_style(self):
        self.assertNotIn('text: "New"', read("js/kennel.js"))
        self.assertNotIn('key: "new"', read("js/kennel.js"))
        self.assertNotIn('data-status="new"', read("css/studio.css"))

    def test_an_open_ticket_shows_a_live_pulse_dot_and_the_count(self):
        out = self.page({"/hounds/kennels/mine": mine([dog("u-1", wins=1, bets=2, units=0.5, open_bets=2, new=False)])}, **SIGNED,
                        queries=[q("status", "[data-hook='dog-status']"), q("dot", "[data-hook='dog-status'] .lh-live", "count")])
        self.assertEqual(out["final"], {"status": "2 open", "dot": 1})

    def test_no_hounds_is_an_empty_state_with_one_button_to_create_the_first(self):
        out = self.page({"/hounds/kennels/mine": mine([])}, **SIGNED, queries=[
            q("empty", "[data-hook='kennel-empty']"), q("cta", "[data-hook='kennel-empty-build']"), q("cards", self.CARDS, "count"),
            q("cta_href", "[data-hook='kennel-empty-build']", "attr", attr="href"), q("links", "[data-hook='kennel-grid'] .lh-btn", "count"), q("buttons", "[data-hook='kennel-grid'] button", "count"),
            q("build_card", "[data-hook='kennel-build-card']", "count"), q("tonight", "[data-hook='kennel-tonight']", "count"),
            q("camp", "[data-hook='kennel-camp']", "count"), q("make", "[data-hook='kennel-build']", "count")])
        f = out["final"]
        self.assertIn("No hounds yet", f["empty"])
        self.assertEqual(f["cta"], "Create your first hound")           # # owner ruling 2026-10-20 kennel-first
        self.assertEqual((f["cta_href"], f["links"], f["buttons"]), ("quiz.html", 1, 0), "one button, and it opens the quiz")
        self.assertEqual((f["cards"], f["build_card"], f["tonight"], f["camp"], f["make"]), (0, 0, 0, 0, 0))

    def test_a_new_member_with_no_hound_gets_the_welcome_and_the_same_one_button(self):
        out = self.page({"/hounds/kennels/mine": mine([])}, **SIGNED, search="?welcome=1", queries=[
            q("welcome", "[data-hook='kennel-welcome']"), q("cta", "[data-hook='kennel-welcome-build']"),
            q("cta_href", "[data-hook='kennel-welcome-build']", "attr", attr="href"), q("studio", "[data-hook='studio']", "hidden")])
        f = out["final"]
        self.assertIn("Welcome to your kennel", f["welcome"])
        self.assertEqual((f["cta"], f["cta_href"], f["studio"]), ("Create your first hound", "quiz.html", True))

    def test_a_retired_dog_is_set_apart_and_offers_a_copy_not_an_edit(self):
        dogs = [dog("u-1", "Live"), dog("u-2", "Old Timer", status="retired", retired=True)]
        out = self.page({"/hounds/kennels/mine": mine(dogs)}, **SIGNED, queries=[
            q("main", f"[data-hook='kennel-grid'] {self.CARDS}", "count"), q("retired", "[data-hook='kennel-retired-list'] summary"),
            q("copy", "[data-hook='dog-action-copy']", "attrs", attr="href"), q("edit", "[data-hook='dog-action-edit']", "count")])
        f = out["final"]
        self.assertEqual(f["main"], 1)
        self.assertEqual(f["retired"], "Retired (1)")
        self.assertEqual(f["copy"], ["build-a-hound.html?from=u-2"])
        self.assertEqual(f["edit"], 1)

    def test_a_lapsed_token_falls_back_to_the_sign_in_gate(self):
        out = self.page({"/hounds/kennels/mine": [401, {"detail": {"error": "unauthorized"}}]}, **SIGNED,
                        queries=[q("gate", "[data-hook='kennel-signin']", "count"), q("cards", self.CARDS, "count")])
        self.assertEqual(out["final"], {"gate": 1, "cards": 0})

    def test_the_page_never_prints_an_email_or_an_account_id(self):
        out = self.page({"/hounds/kennels/mine": mine([dog("u-1")])}, **SIGNED)
        self.assertNotRegex(out["text"], r"@\w+\.\w+")
        self.assertNotIn("owner_user_id", out["text"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class MyKennelIsTheHome(unittest.TestCase):
    """Owner ruling 2026-10-20 kennel-first: Tonight, today's status, the upgrade card only when earned, the camp and the graveyard."""
    OPEN_URL = "/hounds/u-1/bets?page=1&page_size=8&segment=forward&status=open"

    @staticmethod
    def tickets():
        return [200, {"items": [
            {"hound_id": "u-1", "game": "Mariners at Astros", "market": "total", "selection": "Over 8.5", "price": 105, "start_utc": "2099-01-01T23:10:00Z", "result": None},
            {"hound_id": "u-1", "game": "Yankees at Red Sox", "market": "moneyline", "selection": "Red Sox to win", "price": 135, "start_utc": "2099-01-01T19:05:00Z", "result": None}]}]

    def go(self, dogs, extra=None, **kw):
        routes = {"/hounds/kennels/mine": mine(dogs)}
        routes.update(extra or {})
        return run_page("kennel", routes=routes, **SIGNED, tz="UTC", **kw)

    def test_tonight_lists_the_open_tickets_soonest_lock_first_and_names_the_next_lock(self):
        out = self.go([dog("u-1", wins=1, bets=2, units=0.5, open_bets=2, new=False)], {self.OPEN_URL: self.tickets()}, settleMs=300, queries=[
            q("rows", "[data-hook='tonight-ticket']", "count"), q("picks", ".kn-tix__pick", "texts"), q("locks", ".kn-tix__lock", "texts"),
            q("next", "[data-hook='tonight-next']"), q("today", "[data-hook='dog-today']")])
        f = out["final"]
        self.assertEqual(f["rows"], 2)
        self.assertEqual([p.split(" ")[0] for p in f["picks"]], ["Red", "Over"])                     # 19:05 before 23:10
        self.assertRegex(f["next"], r"^Next lock 7:05 PM")
        self.assertRegex(f["today"], r"^2 open · next lock 7:05 PM")
        self.assertTrue(all(l.startswith("Locks ") for l in f["locks"]), f["locks"])

    def test_with_nothing_open_tonight_is_one_quiet_line_and_asks_for_no_tickets(self):
        out = self.go([dog("u-1")], queries=[q("quiet", "[data-hook='tonight-empty']"), q("rows", "[data-hook='tonight-ticket']", "count")])
        self.assertIn("Nothing open", out["final"]["quiet"])
        self.assertEqual(out["final"]["rows"], 0)
        self.assertFalse([g for g in out["gets"] if "status=open" in g], "no request for a hound with no open ticket")

    def test_tickets_that_cannot_be_read_leave_the_payloads_own_count(self):
        out = self.go([dog("u-1", wins=1, bets=2, units=0.5, open_bets=2, new=False)], settleMs=300, queries=[
            q("quiet", "[data-hook='tonight-empty']"), q("today", "[data-hook='dog-today']")])
        self.assertEqual((out["final"]["quiet"], out["final"]["today"]), ("2 open across your hounds.", "2 open"))

    def test_the_upgrade_card_shows_only_for_a_free_account_at_its_one_hound_with_the_real_founding_count(self):
        offer = [200, {"founding": {"price_cents": 1499, "cap": 50, "taken": 31, "left": 19, "reserved": 0, "available": True}, "standard": {"price_cents": 1999}}]
        free = {"/hounds/mine": [200, {"hounds": [], "plan": "free", "limit_running": 1}], "/billing/offer": offer}
        out = self.go([dog("u-1")], free, settleMs=300, queries=[q("card", "[data-hook='kennel-upgrade']", "count"), q("offer", "[data-hook='upgrade-offer']"),
                                                                    q("link", "[data-hook='upgrade-link']", "attr", attr="href")])
        self.assertEqual(out["final"]["card"], 1)
        self.assertEqual(out["final"]["offer"], "Founding member: $14.99/mo for life · 19 of 50 left")
        self.assertEqual(out["final"]["link"], "index.html#/billing")
        sold_out = dict(free, **{"/billing/offer": [200, {"founding": {"price_cents": 1499, "cap": 50, "taken": 50, "left": 0, "reserved": 0, "available": False},
                                                          "standard": {"price_cents": 1999}}]})
        out = self.go([dog("u-1")], sold_out, settleMs=300, queries=[q("offer", "[data-hook='upgrade-offer']")])
        self.assertEqual(out["final"]["offer"], "Member plan: $19.99/mo", "no scarcity wording once the seats are gone")

    def test_no_upgrade_card_for_a_member_for_an_empty_kennel_or_when_the_plan_is_unknown(self):
        paid = {"/hounds/mine": [200, {"hounds": [], "plan": "paid", "limit_running": 5}]}
        free = {"/hounds/mine": [200, {"hounds": [], "plan": "free", "limit_running": 1}]}
        count = [q("card", "[data-hook='kennel-upgrade']", "count")]
        for label, dogs, extra in (("paid", [dog("u-1")], paid), ("free, no hound", [], free), ("plan unknown", [dog("u-1")], {})):
            with self.subTest(case=label):
                self.assertEqual(self.go(dogs, extra, settleMs=300, queries=count)["final"]["card"], 0)

    def test_the_camp_and_the_graveyard_are_one_tap_from_my_kennel(self):
        out = self.go([dog("u-1")], queries=[q("camp", "[data-hook='kennel-camp-link']", "attr", attr="href"),
                                             q("grave", "[data-hook='kennel-graveyard-link']", "attr", attr="href"),
                                             q("public", "[data-hook='kennel-public-link']", "attr", attr="href")])
        self.assertEqual(out["final"], {"camp": "learning.html", "grave": "graveyard.html", "public": "kennel.html?u=handler-21e8"})


@unittest.skipUnless(HAS_NODE, "node not installed")
class APublicKennel(unittest.TestCase):
    CARDS = "[data-hook='kennel-dog']"

    def test_it_lists_the_members_public_dogs_read_only_including_a_zero_bet_dog(self):
        dogs = [dog("u-1", "Underdog Gus", wins=2, losses=1, bets=3, units=0.9), dog("u-2", "Totals Tina")]
        out = run_page("kennel", search="?u=handler-21e8", routes={"/hounds/kennels/handler-21e8": public(dogs)}, queries=[
            q("title", "[data-hook='kennel-title']"), q("eyebrow", "[data-hook='kennel-eyebrow']"), q("sub", "[data-hook='kennel-sub']"),
            q("names", f"{self.CARDS} [data-hook='dog-name']", "texts"), q("status", "[data-hook='dog-status']", "texts"),
            q("edit", "[data-hook='dog-action-edit']", "count"), q("fire", "[data-hook='dog-action-fire']", "count"),
            q("build_card", "[data-hook='kennel-build-card']", "count"), q("open", "[data-hook='dog-action-open']", "attrs", attr="href"),
            q("ask", "[data-hook='dog-action-ask']", "attrs", attr="href"), q("build", "[data-hook='kennel-build']", "count")])
        f = out["final"]
        self.assertEqual(f["title"], "Handler 21E8's kennel")
        self.assertEqual(f["names"], ["Underdog Gus", "Totals Tina"])
        self.assertEqual(f["status"], ["Running", "Running"])
        self.assertEqual((f["edit"], f["fire"], f["build_card"], f["build"]), (0, 0, 0, 0))     # nothing to change on someone else's dogs
        self.assertEqual(f["open"], ["hound.html?id=u-1", "hound.html?id=u-2"])
        self.assertEqual(f["ask"], ["hound.html?id=u-1&tab=ask", "hound.html?id=u-2&tab=ask"])
        self.assertIn("2 hounds", f["sub"])      # # owner ruling 2026-10-20 kennel-first
        self.assertEqual(out["document_title"] if "document_title" in out else out["title"], "Handler 21E8's kennel — LINEHOUND")
        self.assertEqual(out["gets"][0].split("?")[0], "/hounds/kennels/handler-21e8")

    def test_it_needs_no_sign_in(self):
        out = run_page("kennel", search="?u=handler-21e8", routes={"/hounds/kennels/handler-21e8": public([dog()])},
                       queries=[q("gate", "[data-hook='kennel-signin']", "count"), q("cards", self.CARDS, "count")])
        self.assertEqual(out["final"], {"gate": 0, "cards": 1})
        self.assertNotIn("Authorization", json.dumps(out["getCalls"]))

    def test_an_unknown_kennel_says_so_and_points_at_the_index(self):
        out = run_page("kennel", search="?u=nobody", routes={"/hounds/kennels/nobody": [404, {"detail": {"error": "not_found"}}]},
                       queries=[q("missing", "[data-hook='kennel-missing']"), q("cards", self.CARDS, "count")])
        self.assertIn("No kennel with that name", out["final"]["missing"])
        self.assertEqual(out["final"]["cards"], 0)

    def test_a_server_that_is_down_says_so_instead_of_an_empty_kennel(self):
        out = run_page("kennel", search="?u=handler-21e8", down=["/hounds/kennels/handler-21e8"],
                       queries=[q("state", "[data-hook='section-state']", "count"), q("cards", self.CARDS, "count")])
        self.assertEqual(out["final"], {"state": 1, "cards": 0})


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStudio(unittest.TestCase):
    MENU = json.loads(json.dumps(user_spec.builder_menu()))

    def routes(self, dogs, **over):
        r = {"/hounds/kennels/mine": mine(dogs), "/hounds/builder/menu": [200, self.MENU],
             "/hounds/mine": [200, {"hounds": [], "limit_running": 3}], "/hounds/u-1/kit": [200, kit("u-1")],
             "/hounds/u-1/ask": [200, {"greeting": ["Woof. Ask me about my bets."], "suggestions": ["Why that pick?"]}],
             "/hounds/u-1/manual": [200, {"tickets": [], "record": {}, "limit_per_day": 5}],
             "/hounds/u-1/bets?page=1&page_size=5&segment=forward": [200, {"items": [], "total": 0}],
             "POST /hounds/u-1/fire": [200, {"headline": "Nothing qualifies right now.", "picks": [], "closest_misses": [], "recorded": [],
                                              "notes": [], "preview_note": "Paper only.", "viewer_is_owner": True}],
             # the owner's Unleash (2026-10-21) STARTS the dog: POST /hounds/{id}/unleash, tests/test_unleash_web.py draws a full day
             "POST /hounds/u-1/unleash": [200, {"headline": "Underdog Gus is unleashed. Nothing on today's board fits its rule yet; it keeps watching and bets when a game does.",
                                                "picks": [], "before": [], "no_board": [], "games_on_board": 0, "placed_now": 0,
                                                "already_running": False, "before_label": "Before you unleashed. Not on its record.",
                                                "paper_only": True}]}
        r.update(over)
        return r

    def test_clicking_a_dogs_avatar_opens_the_studio_on_the_look_tab_with_the_locker_room(self):
        out = run_page("kennel", routes=self.routes([dog("u-1")]), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=200, capture=[
                q("hidden", "[data-hook='studio']", "hidden"), q("title", "[data-hook='studio-title']"),
                q("tabs", "[data-hook='studio-tabs'] [role='tab']", "texts"), q("selected", "[role='tab'][aria-selected='true']", "texts"),
                q("preview", "[data-hook='locker-preview'] svg.dk-badge", "count"), q("head_avatar", "[data-hook='studio-avatar'] svg", "count"),
                q("open_link", "[data-hook='studio-open']", "attr", attr="href"), q("look_panel", "[data-tabpanel='look']", "hidden"),
                q("rules_panel", "[data-tabpanel='rules']", "hidden")])])
        cap = out["captures"]["open"]
        self.assertEqual((cap["hidden"], cap["title"]), (False, "Underdog Gus"))
        self.assertEqual(cap["tabs"], ["Look", "Rules", "Unleash", "Backtest", "Ask", "Record"])
        self.assertEqual(cap["selected"], ["Look"])
        self.assertEqual((cap["preview"], cap["head_avatar"]), (1, 1))
        self.assertEqual(cap["open_link"], "hound.html?id=u-1")
        self.assertEqual((cap["look_panel"], cap["rules_panel"]), (False, True))

    def test_edit_opens_the_builder_inside_the_studio_with_the_advanced_cards_collapsed(self):
        dogs = [dog("u-1")]
        mine_dog = {"id": "u-1", "name": "Underdog Gus", "tagline": "Barks", "status": "running", "version_no": 1, "color": "mint", "badge": "crown",
                    "record": {"bets": 0, "wins": 0, "losses": 0, "pushes": 0}, "rule_sentences": ["MLB moneylines: it backs the underdog."]}
        from tests import _hounds_rules_fixtures as F
        mine_dog["spec"] = json.loads(json.dumps(user_spec.validate_spec(F.v2(name="Underdog Gus", rules=[F.rule(side="away", price_min=100)]))))
        routes = self.routes(dogs, **{"/hounds/mine": [200, {"hounds": [mine_dog], "limit_running": 3}],
                                      "POST /hounds/builder/preview": [200, {"qualifying": 0, "would_bet": 0, "picks": [], "sentences": [],
                                                                              "max_bets_per_day": 2, "paper_only": True}]})
        out = run_page("kennel", routes=routes, **SIGNED, settleMs=200, actions=[
            dict(do="click", sel="[data-hook='dog-action-edit']", label="edit", wait=500, capture=[
                q("hidden", "[data-hook='studio']", "hidden"), q("selected", "[role='tab'][aria-selected='true']", "texts"),
                q("builder", "[data-hook='studio-rules'] [data-hook='build-app']", "count"),
                q("title", "[data-hook='build-title']"), q("advanced", "[data-hook='rules-advanced']", "count"),
                q("advanced_open", "[data-hook='rules-advanced']", "attr", attr="open"), q("cards", "[data-hook='rule-card']", "count"),
                q("name", "[data-hook='f-name']", "value"), q("sentences", "[data-hook='rule-sentences']")])])
        cap = out["captures"]["edit"]
        self.assertEqual((cap["hidden"], cap["selected"]), (False, ["Rules"]))
        self.assertEqual(cap["builder"], 1)
        self.assertEqual(cap["title"], "Edit Underdog Gus")
        self.assertEqual((cap["advanced"], cap["advanced_open"]), (1, None), "Edit rules is closed until it is opened")
        self.assertEqual(cap["cards"], 1)                       # the cards exist (inside the closed details)
        self.assertEqual(cap["name"], "Underdog Gus")

    def test_a_second_rules_panel_in_one_visit_is_still_alive(self):
        """2026-10-20, a real member: the kennel studio built a fresh builder skeleton every time the Rules panel opened,
        but hounds-build.js binds its listeners once, to the first skeleton. So the second Rules panel of a visit (another
        dog, or New dog) was dead: typing left the counter at 0 / 600 and Read my strategy did nothing."""
        from tests import _hounds_rules_fixtures as F
        mine = []
        for i, name in ((1, "Underdog Gus"), (2, "Totals Tina")):
            d = {"id": f"u-{i}", "name": name, "tagline": "", "status": "running", "version_no": 1, "color": "mint", "badge": "crown",
                 "record": {"bets": 0, "wins": 0, "losses": 0, "pushes": 0}, "rule_sentences": ["MLB moneylines: it backs the underdog."]}
            d["spec"] = json.loads(json.dumps(user_spec.validate_spec(F.v2(name=name, rules=[F.rule(side="away", price_min=100)]))))
            mine.append(d)
        routes = self.routes([dog("u-1"), dog("u-2")], **{"/hounds/mine": [200, {"hounds": mine, "limit_running": 5}],
                                                         "POST /hounds/builder/preview": [200, {"qualifying": 0, "would_bet": 0, "picks": [],
                                                                                                 "sentences": [], "max_bets_per_day": 2,
                                                                                                 "paper_only": True}]})
        out = run_page("kennel", routes=routes, **SIGNED, settleMs=200, actions=[
            dict(do="click", sel="[data-hook='dog-action-edit']", index=0, label="first", wait=500),
            dict(do="click", sel="[data-hook='studio-close']", label="close", wait=200),
            dict(do="click", sel="[data-hook='dog-action-edit']", index=1, label="second", wait=500, capture=[
                q("builders", "[data-hook='build-app']", "count"), q("title", "[data-hook='build-title']")]),
            dict(do="set", sel="[data-hook='english-input']", value="bet road underdogs", label="typed", wait=100, capture=[
                q("count", "[data-hook='english-count']")])])
        self.assertEqual(out["captures"]["second"]["builders"], 1, "one builder on the page, moved, never a second copy")
        self.assertEqual(out["captures"]["second"]["title"], "Edit Totals Tina")
        self.assertEqual(out["captures"]["typed"]["count"], "18 / 600", "the second panel's builder answers typing")

    def test_unleash_opens_the_fire_tab_and_starts_the_hound_at_once(self):
        # owner request 2026-10-21: the owner's Unleash starts the dog (POST .../unleash), it is no longer the read-only preview (.../fire)
        out = run_page("kennel", routes=self.routes([dog("u-1")]), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-action-fire']", label="fire", wait=300, capture=[
                q("selected", "[role='tab'][aria-selected='true']", "texts"), q("headline", "[data-hook='unleash-headline']"),
                q("preview", "[data-hook='fire-headline']", "count")])])
        self.assertEqual(out["captures"]["fire"]["selected"], ["Unleash"])
        self.assertIn("Nothing on today's board fits its rule yet", out["captures"]["fire"]["headline"])
        self.assertEqual(out["captures"]["fire"]["preview"], 0)
        self.assertEqual([p["url"].split("/")[-2:] for p in out["posts"]], [["u-1", "unleash"]])

    def test_ask_opens_the_ask_tab_with_the_hounds_greeting(self):
        # # owner ruling 2026-10-20 kennel-first: Ask is a studio tab now, not a card button
        out = run_page("kennel", routes=self.routes([dog("u-1")]), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=120),
            dict(do="click", sel="[role='tab'][data-tab='ask']", label="ask", wait=300, capture=[
                q("selected", "[role='tab'][aria-selected='true']", "texts"), q("thread", "[data-hook='ask-thread']"),
                q("chips", "[data-hook='ask-chip']", "texts")])])
        cap = out["captures"]["ask"]
        self.assertEqual(cap["selected"], ["Ask"])
        self.assertIn("Ask me about my bets", cap["thread"])
        self.assertEqual(cap["chips"], ["Why that pick?"])

    def test_the_record_tab_shows_the_numbers_and_the_manual_picks_panel_stays_apart(self):
        out = run_page("kennel", routes=self.routes([dog("u-1", wins=3, losses=1, bets=4, units=1.8)]), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=120),
            dict(do="click", sel="[role='tab'][data-tab='record']", label="record", wait=300, capture=[
                q("stats", "[data-hook='studio-record-stats'] dd", "texts"), q("tickets", "[data-hook='studio-tickets']")])])
        cap = out["captures"]["record"]
        self.assertEqual(cap["stats"], ["3-1", "$1,018", "+1.8%", "4", "0"])
        self.assertIn("No tickets recorded yet", cap["tickets"])

    def test_closing_the_studio_hides_it_and_gives_the_page_back(self):
        out = run_page("kennel", routes=self.routes([dog("u-1")]), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", label="open", wait=120),
            dict(do="click", sel="[data-hook='studio-close']", label="close", wait=60, capture=[
                q("hidden", "[data-hook='studio']", "hidden"), q("scrim", "[data-hook='studio-scrim']", "hidden")])])
        self.assertEqual(out["captures"]["close"], {"hidden": True, "scrim": True})


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennelsIndex(unittest.TestCase):
    def test_every_kennel_is_a_card_that_opens_its_page(self):
        kennels = [{"handle": "handler-21e8", "display": "Handler 21E8", "dog_count": 2, "new_dogs": 2, "best": None, "href": "kennel.html?u=handler-21e8",
                    "dogs": [{"id": "u-1", "name": "A", "look": None}, {"id": "u-2", "name": "B", "look": None}]},
                   {"handle": "handler-0001", "display": "Handler 0001", "dog_count": 1, "new_dogs": 0, "href": "kennel.html?u=handler-0001",
                    "best": {"id": "u-3", "name": "Rex", "record": {"wins": 5, "losses": 2, "pushes": 0}, "settled": 7},
                    "dogs": [{"id": "u-3", "name": "Rex", "look": None}]}]
        out = run_page("kennels_index", routes={"/hounds/kennels": [200, {"kennels": kennels, "count": 2}]}, queries=[
            q("hrefs", "[data-hook='kennel-card']", "attrs", attr="href"), q("names", ".kn-kcard__name", "texts"),
            q("meta", ".kn-kcard__meta", "texts"), q("faces", ".kn-stack svg.dk-badge", "count"), q("count", "[data-hook='kennels-count']")])
        f = out["final"]
        self.assertEqual(f["hrefs"], ["kennel.html?u=handler-21e8", "kennel.html?u=handler-0001"])
        self.assertEqual(f["names"], ["Handler 21E8's kennel", "Handler 0001's kennel"])
        self.assertEqual(f["meta"], ["2 hounds · New: no bets yet", "1 hound · Best: Rex, 5-2"])   # owner ruling 2026-10-20 kennel-first: hound, not dog
        self.assertEqual((f["faces"], f["count"]), (3, "2 kennels"))

    def test_no_kennels_is_an_empty_state_with_a_build_link(self):
        out = run_page("kennels_index", routes={"/hounds/kennels": [200, {"kennels": [], "count": 0}]},
                       queries=[q("empty", "[data-hook='kennels-empty']"), q("cards", "[data-hook='kennel-card']", "count")])
        self.assertIn("No kennels yet", out["final"]["empty"])
        self.assertEqual(out["final"]["cards"], 0)

    def test_a_server_without_the_route_says_so(self):
        out = run_page("kennels_index", routes={}, queries=[q("state", "[data-hook='section-state']", "count")])
        self.assertEqual(out["final"]["state"], 1)


# ---------------------------------------------------------------------------------------------------
# the dog page's tabs and the leaderboard's two views
# ---------------------------------------------------------------------------------------------------

class TheDogPageTabs(unittest.TestCase):
    HTML = read("hound.html")

    def test_four_tabs_in_order_with_unleash_above_them(self):
        # owner ruling 2026-10-20 kennel-first: Overview, Tickets, Ask, Locker (Backtest moved under Ask, the rule into Overview)
        tabs = re.findall(r'role="tab" data-tab="([a-z]+)"', self.HTML)
        self.assertEqual(tabs, ["overview", "tickets", "ask", "locker"])
        self.assertLess(self.HTML.index('data-hook="dog-fire-section"'), self.HTML.index('data-hook="hound-tabs"'))
        self.assertIn(">Unleash<", self.HTML)
        self.assertNotIn(">Out back<", self.HTML)
        self.assertNotIn("Fire now", self.HTML)

    def test_every_section_sits_in_the_panel_it_belongs_to(self):
        def panel(name):
            m = re.search(rf'<div class="lh-tabpanel" data-tabpanel="{name}".*?(?=<div class="lh-tabpanel"|</main>)', self.HTML, re.S)
            return m.group(0)
        self.assertIn('data-hook="hound-scoreboard-section"', panel("overview"))      # behind "How it's graded"
        self.assertIn('data-hook="hound-chart-section"', panel("overview"))
        self.assertIn('data-hook="hound-verdict-section"', panel("overview"))
        self.assertIn('data-hook="hound-today-section"', panel("tickets"))
        self.assertIn('data-hook="hound-bets-section"', panel("tickets"))
        self.assertIn('data-hook="dog-manual-section"', panel("tickets"))
        self.assertIn('data-hook="dog-backtest-section"', panel("ask"))
        self.assertIn('data-hook="dog-ask-section"', panel("ask"))
        self.assertIn('data-hook="dog-locker-section"', panel("locker"))
        self.assertIn('data-hook="hound-rule-section"', panel("overview"))
        self.assertIn('data-hook="hound-lineage-section"', panel("overview"))

    def test_only_overview_is_visible_in_the_markup_and_the_owner_tabs_are_optional(self):
        self.assertEqual(len(re.findall(r'data-tabpanel="[a-z]+"[^>]* hidden>', self.HTML)), 3)
        self.assertRegex(self.HTML, r'data-tab="ask" aria-selected="false" data-optional')
        self.assertRegex(self.HTML, r'data-tab="locker" aria-selected="false" data-optional')

    def test_the_overview_panel_loads_with_skeletons_not_loading_words(self):
        self.assertEqual(self.HTML.count('class="lh-skel '), 4)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TabsRun(unittest.TestCase):
    PANELS = ["overview", "tickets", "ask", "locker"]            # owner ruling 2026-10-20 kennel-first: four tabs

    def panels_hidden(self):
        return [q(f"{p}", f"[data-tabpanel='{p}']", "hidden") for p in self.PANELS]

    def test_overview_first_and_a_click_swaps_the_panel(self):
        out = run_page("tabs", captureInitial=self.panels_hidden() + [q("selected", "[role='tab'][aria-selected='true']", "texts")], actions=[
            dict(do="click", sel="[data-tab='tickets']", label="tickets", capture=self.panels_hidden() + [q("selected", "[role='tab'][aria-selected='true']", "texts")])])
        first = out["captures"]["initial"]
        self.assertEqual([first[p] for p in self.PANELS], [False, True, True, True])
        self.assertEqual(first["selected"], ["Overview"])
        cap = out["captures"]["tickets"]
        self.assertEqual([cap[p] for p in self.PANELS], [True, False, True, True])
        self.assertEqual(cap["selected"], ["Tickets"])

    def test_a_tab_query_opens_that_tab(self):
        out = run_page("tabs", search="?id=closer&tab=tickets", queries=self.panels_hidden())
        self.assertEqual([out["final"][p] for p in self.PANELS], [True, False, True, True])

    def test_arrow_keys_move_between_the_shown_tabs(self):
        out = run_page("tabs", actions=[dict(do="key", sel="[data-tab='overview']", key="ArrowRight", label="right", capture=[
            q("selected", "[role='tab'][aria-selected='true']", "texts")]),
            dict(do="key", sel="[data-tab='tickets']", key="End", label="end", capture=[q("selected", "[role='tab'][aria-selected='true']", "texts")])])
        self.assertEqual(out["captures"]["right"]["selected"], ["Tickets"])
        self.assertEqual(out["captures"]["end"]["selected"], ["Tickets"])      # Ask and Locker stay hidden until the kit has something

    def test_the_owner_only_tabs_hide_until_their_panel_has_something(self):
        # the markup keeps every Ask / Locker room section hidden until the dog kit shows one; the tab follows it
        out = run_page("tabs", queries=[q("ask", "[data-tab='ask']", "hidden"), q("locker", "[data-tab='locker']", "hidden"),
                                         q("tickets", "[data-tab='tickets']", "hidden")])
        self.assertEqual((out["final"]["ask"], out["final"]["locker"], out["final"]["tickets"]), (True, True, False))

    def test_the_hound_page_has_four_tabs_and_the_leaderboard_has_none(self):
        # owner ruling 2026-10-20 kennel-first: the leaderboard's Models/Kennels tabs are gone (Kennels is its own page);
        # the hound page's tabs are Overview, Tickets, Ask and Locker.
        out = run_page("tabs", page_html="hound.html", captureInitial=[q("tabs", "[role='tab']", "texts"), q("tickets", "[data-tabpanel='tickets']", "hidden"),
                                                                       q("overview", "[data-tabpanel='overview']", "hidden")],
                       actions=[dict(do="click", sel="[data-tab='tickets']", label="t", capture=[
                           q("tickets", "[data-tabpanel='tickets']", "hidden"), q("overview", "[data-tabpanel='overview']", "hidden")])])
        first = out["captures"]["initial"]
        self.assertEqual(first["tabs"], ["Overview", "Tickets", "Ask", "Locker"])
        self.assertEqual((first["overview"], first["tickets"]), (False, True))
        self.assertEqual(out["captures"]["t"], {"tickets": False, "overview": True})
        board = read("hounds.html")
        self.assertNotIn("data-autotabs", board)
        self.assertNotIn("data-tabpanel", board)


# ---------------------------------------------------------------------------------------------------
# the builder keeps one set of hooks in both of its homes
# ---------------------------------------------------------------------------------------------------

class TheBuilderHasOneHookSet(unittest.TestCase):
    JS = read("js/hounds-build.js")
    STATIC = read("build-a-hound.html")
    SKELETON = read("js/builder-skeleton.js")
    # the shared navigation owns the sign-in link; the builder guards for its absence
    NAV_OWNED = {"nav-signin"}

    def hooks(self):
        return sorted(set(re.findall(r'\bq\("([a-z0-9-]+)"\)', self.JS)) - self.NAV_OWNED)

    def test_every_hook_the_builder_reads_is_in_the_static_page(self):
        for hook in self.hooks():
            self.assertIn(f'data-hook="{hook}"', self.STATIC, hook)

    def test_every_hook_the_builder_reads_is_in_the_studio_skeleton(self):
        for hook in self.hooks():
            self.assertTrue(f'hook("{hook}"' in self.SKELETON or f'"data-hook": "{hook}"' in self.SKELETON, hook)

    def test_the_skeleton_collapses_the_advanced_cards_too(self):
        self.assertIn('hook("rules-advanced"', self.SKELETON)
        self.assertNotRegex(self.SKELETON, r'rules-advanced"[^)]*open')


# ---------------------------------------------------------------------------------------------------
# the visual system the other pages inherit (owner ruling 2026-10-20 kennel-first)
# ---------------------------------------------------------------------------------------------------

class TheVisualSystemIsOneScaleAndOneAccent(unittest.TestCase):
    TOKENS = read("css/tokens.css")

    def test_every_spacing_step_sits_on_the_4_8_ladder(self):
        steps = [int(v) for v in re.findall(r"--sp-\d+:\s*(\d+)px;", self.TOKENS)]
        self.assertEqual(len(steps), 17, "the names are stable: --sp-1 to --sp-17")
        self.assertLessEqual(set(steps), {4, 8, 12, 16, 24, 32, 48, 64, 96}, sorted(set(steps)))

    def test_the_type_scale_is_the_hub_scale(self):
        sizes = {k: v for k, v in re.findall(r"--fs-(meta|small|body|lead|h3|h2|h1):\s*(\d+)px;", self.TOKENS)}
        self.assertEqual(sizes, {"meta": "13", "small": "15", "body": "17", "lead": "17", "h3": "22", "h2": "30", "h1": "48"})

    def test_the_primary_action_is_the_one_accent_and_its_text_is_dark_ink(self):
        self.assertIn("--accent: #2FD07A;", self.TOKENS)
        self.assertIn("--primary: var(--accent);", self.TOKENS)
        self.assertIn("--accent-ink:", self.TOKENS)
        components = read("css/components.css")
        primary = re.search(r"\.btn--primary \{.*?\}", components, re.S).group(0)
        self.assertIn("var(--accent-ink)", primary)
        self.assertIn("clip-path: none", primary)

    def test_the_nav_reads_the_accent_token_not_its_own_colour(self):
        self.assertIn("var(--accent, #2FD07A)", read("css/lhnav.css"))


# ---------------------------------------------------------------------------------------------------
# motion: reduced motion gets none of it
# ---------------------------------------------------------------------------------------------------

class EveryAnimationIsInsideNoPreference(unittest.TestCase):
    FILES = ("css/lh.css", "css/lhnav.css", "css/studio.css", "css/dog-kit.css")

    @staticmethod
    def outside_motion_blocks(css):
        """The stylesheet with every `@media (prefers-reduced-motion: no-preference) { ... }` block and every
        `@keyframes` block removed (brace-matched)."""
        out, i = [], 0
        pattern = re.compile(r"@media \(prefers-reduced-motion: no-preference\)\s*\{|@keyframes [\w-]+\s*\{")
        while True:
            m = pattern.search(css, i)
            if not m:
                out.append(css[i:])
                return "".join(out)
            out.append(css[i:m.start()])
            depth, j = 1, m.end()
            while depth and j < len(css):
                depth += {"{": 1, "}": -1}.get(css[j], 0)
                j += 1
            i = j

    def test_no_animation_runs_outside_a_no_preference_block(self):
        for name in self.FILES:
            css = re.sub(r"/\*.*?\*/", "", read(name), flags=re.S)
            rest = self.outside_motion_blocks(css)
            with self.subTest(file=name):
                self.assertNotRegex(rest, r"animation(-name)?\s*:", "an animation outside the no-preference block")

    def test_the_motion_blocks_exist_and_hold_the_animations(self):
        css = read("css/lh.css")
        self.assertIn("@media (prefers-reduced-motion: no-preference)", css)
        for needle in ("lh-shimmer", "lh-rise", "dk-bob", "dk-blink", "dk-wiggle", "dk-slump", "lh-ping"):
            self.assertIn(f"@keyframes {needle}", css)
        self.assertIn("@media (prefers-reduced-motion: no-preference)", read("css/lhnav.css"))
        self.assertIn("@media (prefers-reduced-motion: no-preference)", read("css/studio.css"))

    def test_the_old_chart_draw_in_is_still_gated(self):
        self.assertIn("@media (prefers-reduced-motion: no-preference)", read("css/hounds.css"))

    def test_the_pages_load_the_motion_script_and_it_loads_nothing_from_outside(self):
        for name in ("hounds.html", "hound.html", "build-a-hound.html", "kennel.html"):
            self.assertIn('<script type="module" src="js/fx.js"></script>', read(name), name)
        for name in ("js/fx.js", "js/tabs.js", "js/nav.js", "js/kennel.js", "js/kennels-index.js"):
            self.assertNotRegex(read(name), r"https?://(?!www\.w3\.org/2000/svg)", name)      # the SVG namespace is not a request


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheMotionScript(unittest.TestCase):
    def test_a_count_up_reads_the_number_in_the_text_and_keeps_its_shape(self):
        out = run_js('import { parseCount } from "./fx.js";\nconsole.log(JSON.stringify(["+1.80u", "-2.00u", "12", "3-1", "n/a", "1,204 bets", "+0.00u"].map(parseCount)));')
        self.assertEqual(out[0], {"prefix": "+", "value": 1.8, "decimals": 2, "suffix": "u", "neg": False})
        self.assertEqual(out[1]["value"], -2.0)
        self.assertEqual(out[2]["value"], 12)
        self.assertEqual(out[3]["value"], 3)
        self.assertIsNone(out[4])
        self.assertEqual(out[5]["value"], 1204)

    def test_reduced_motion_leaves_the_text_alone_and_bursts_nothing(self):
        out = run_js(
            'globalThis.window = { matchMedia: () => ({ matches: true }), innerWidth: 800, innerHeight: 600 };\n'
            'globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now() + 2000), 0);\n'
            'const { countUp, burst, reducedMotion } = await import("./fx.js");\n'
            'const el = { text: "+1.80u", attrs: {}, get textContent() { return this.text; }, set textContent(v) { this.text = v; },\n'
            '  getAttribute(k) { return this.attrs[k] ?? null; }, setAttribute(k, v) { this.attrs[k] = v; } };\n'
            'countUp(el);\nawait new Promise((r) => setTimeout(r, 30));\n'
            'console.log(JSON.stringify([reducedMotion(), el.text, burst(null)]));')
        self.assertEqual(out, [True, "+1.80u", 0])

    def test_with_motion_a_count_up_ends_on_the_exact_original_text(self):
        out = run_js(
            'globalThis.window = { matchMedia: () => ({ matches: false }) };\n'
            'globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now() + 5000), 0);\n'
            'const { countUp } = await import("./fx.js");\n'
            'const writes = [];\n'
            'const el = { text: "+1.80u", attrs: {}, get textContent() { return this.text; }, set textContent(v) { writes.push(v); this.text = v; },\n'
            '  getAttribute(k) { return this.attrs[k] ?? null; }, setAttribute(k, v) { this.attrs[k] = v; } };\n'
            'countUp(el, 700);\nawait new Promise((r) => setTimeout(r, 120));\n'
            'console.log(JSON.stringify([writes[0], writes[writes.length - 1], el.text, el.attrs["data-counted"]]));')
        self.assertEqual(out[0], "+0.00u")                                              # it started from zero
        self.assertEqual((out[1], out[2], out[3]), ("+1.80u", "+1.80u", "1"))           # and ended on the exact original text

    def test_a_count_up_never_runs_twice_on_one_element(self):
        out = run_js(
            'globalThis.window = { matchMedia: () => ({ matches: false }) };\n'
            'globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now() + 5000), 0);\n'
            'const { countUp } = await import("./fx.js");\n'
            'let sets = 0;\nconst el = { text: "+2.00u", attrs: {}, get textContent() { return this.text; }, set textContent(v) { sets++; this.text = v; },\n'
            '  getAttribute(k) { return this.attrs[k] ?? null; }, setAttribute(k, v) { this.attrs[k] = v; } };\n'
            'countUp(el); const first = sets; countUp(el); countUp(el);\nawait new Promise((r) => setTimeout(r, 30));\n'
            'console.log(JSON.stringify([first, sets <= first + 2]));')
        self.assertEqual(out[1], True)

    def test_a_dog_badge_carries_the_groups_and_mood_the_css_moves(self):
        out = run_js(
            'import { h } from "./hounds-core.js";\n'
            'globalThis.document = { createElement: () => ({}), createElementNS: (ns, t) => ({ tag: t, attrs: {}, kids: [], setAttribute(k, v) { this.attrs[k] = v; },\n'
            '  appendChild(c) { this.kids.push(c); return c; }, set textContent(v) {} }), createTextNode: (t) => t };\n'
            'const { dogBadge } = await import("./dog-avatar.js");\n'
            'const svg = dogBadge({ coat: "black" }, { mood: "happy" });\n'
            'const classes = []; const walk = (n) => { if (n && n.attrs && n.attrs.class) classes.push(n.attrs.class); (n.kids || []).forEach(walk); };\nwalk(svg);\n'
            'console.log(JSON.stringify([svg.attrs["data-mood"], classes]));')
        self.assertEqual(out[0], "happy")
        for c in ("dk-badge", "dk-body", "dk-head", "dk-eyes", "dk-ear dk-ear--l", "dk-ear dk-ear--r"):
            self.assertIn(c, out[1])


if __name__ == "__main__":
    unittest.main()
