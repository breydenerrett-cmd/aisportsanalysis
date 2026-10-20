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
PAGES = ("kennels.html", "live.html", "hounds.html", "hound.html", "build-a-hound.html", "learning.html", "kennel.html", "landing.html", "why-we-paused.html",
         "postseason.html", "sample.html", "index.html", "graveyard.html")
LINKS = [("hounds.html", "Leaderboard"), ("kennels.html", "Kennels"), ("live.html", "Live"), ("quiz.html", "Build"),
         ("learning.html", "Training camp")]


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

    def test_each_page_names_the_same_five_places_in_the_same_order(self):
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
            self.assertRegex(html, r'<a class="lh-btn lh-btn--(solid|soft)" href="index.html#/signin" data-hook="nav-signin">Sign in</a>', name)

    def test_the_member_app_keeps_its_own_tab_bar_so_the_component_adds_none(self):
        self.assertIn('data-bottom="off"', read("index.html"))
        self.assertNotIn('data-bottom="off"', read("hounds.html"))

    def test_kennels_is_its_own_page_apart_from_the_leaderboard(self):
        html = read("kennels.html")
        self.assertIn('data-hook="kennels-index"', html)
        self.assertIn('<script type="module" src="js/kennels-index.js"></script>', html)
        self.assertNotIn("hounds-page.js", html)                     # no leaderboard on it
        self.assertIn('data-nav="kennels" aria-current="page"', html)
        self.assertIn('href="kennel.html" data-hook="kennels-mine"', html)

    def test_the_landing_page_has_a_big_kennels_card(self):
        html = read("landing.html")
        # round 2 (2026-10-19): the band is "build your dog" with a primary build button; the kennels are one ghost button away
        self.assertRegex(html, r'<a class="btn btn--primary" href="build-a-hound.html" data-hook="kennels-card-build">Build a hound</a>')   # owner ruling 2026-10-20, complete-product positioning
        self.assertRegex(html, r'<a class="btn btn--ghost" href="kennels.html" data-hook="kennels-card-browse">Browse the kennels</a>')
        self.assertRegex(html, r'href="kennel.html" data-hook="kennels-card-mine">Your kennel</a>')

    def test_the_landing_page_keeps_its_early_access_button_in_the_bar(self):
        html = read("landing.html")
        self.assertRegex(html, r'<a class="btn btn--primary"[^>]*data-hook="cta-primary"[^>]*data-nav-extra[^>]*>Create free account</a>')
        self.assertIn('href="index.html#/signin?create=1" data-hook="cta-primary"', html)


# ---------------------------------------------------------------------------------------------------
# the navigation, run
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheNavigationRuns(unittest.TestCase):
    QS = [q("links", ".lh-nav__links a", "texts"), q("hrefs", ".lh-nav__links a", "attrs", attr="href"),
          q("current", ".lh-nav__links a[aria-current='page']", "texts"), q("signin", "[data-hook='nav-signin']", "count"),
          q("mykennel", "[data-hook='nav-mykennel']", "count"), q("account", "[data-hook='nav-account']", "count"),
          q("tabs", "[data-hook='site-tabbar'] .lh-tab", "texts"), q("tabhrefs", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="href"),
          q("bars", ".lh-nav", "count"), q("area", "[data-hook='nav-account-area']", "attr", attr="data-signed-in")]

    def run_nav(self, **kw):
        kw.setdefault("page_html", "hounds.html")
        kw.setdefault("queries", self.QS)
        return run_page("nav", **kw)

    def test_signed_out_shows_sign_in_and_no_account_menu(self):
        f = self.run_nav()["final"]
        self.assertEqual(f["links"], [t for _, t in LINKS])
        self.assertEqual(f["hrefs"], [h for h, _ in LINKS])
        self.assertEqual((f["signin"], f["mykennel"], f["account"], f["bars"], f["area"]), (1, 0, 0, 1, "false"))
        self.assertEqual(f["tabs"], ["Board", "Kennels", "Live", "Build", "Camp", "Sign in"])
        self.assertEqual(f["tabhrefs"][-1], "index.html#/signin")

    def test_signed_in_shows_my_kennel_and_the_account_menu(self):
        out = self.run_nav(**SIGNED, queries=self.QS + [
            q("menu_hidden", "[data-hook='nav-menu']", "hidden"), q("menu", "[data-hook='nav-menu'] [role='menuitem']", "texts"),
            q("menu_hrefs", "[data-hook='nav-menu'] a", "attrs", attr="href"), q("expanded", "[data-hook='nav-account']", "attr", attr="aria-expanded")])
        f = out["final"]
        self.assertEqual((f["signin"], f["mykennel"], f["account"], f["area"]), (0, 1, 1, "true"))
        self.assertEqual(f["menu"], ["My kennel", "Change password", "Sign out"])
        self.assertEqual(f["menu_hrefs"], ["kennel.html", "index.html#/signin?password=1"])
        self.assertEqual((f["menu_hidden"], f["expanded"]), (True, "false"))
        self.assertEqual(f["tabs"], ["Board", "Kennels", "Live", "Build", "Camp", "Mine"])
        self.assertEqual(f["tabhrefs"][-1], "kennel.html")

    def test_the_account_button_opens_the_menu_and_sign_out_posts_and_forgets_the_token(self):
        out = run_page("nav", page_html="hounds.html", **SIGNED, routes={"POST /auth/logout": [200, {"ok": True}]}, actions=[
            dict(do="click", sel="[data-hook='nav-account']", label="open", capture=[
                q("hidden", "[data-hook='nav-menu']", "hidden"), q("expanded", "[data-hook='nav-account']", "attr", attr="aria-expanded")]),
            dict(do="click", sel="[data-hook='menu-signout']", label="out", wait=80)])
        self.assertEqual(out["captures"]["open"], {"hidden": False, "expanded": "true"})
        self.assertEqual([p["url"].split("/")[-2:] for p in out["posts"]], [["auth", "logout"]])
        self.assertNotIn(TOKEN_KEY, out["storedAfter"])

    def test_the_current_place_follows_the_page_and_the_kennel_page_follows_its_query(self):
        cases = [("hounds.html", "/web/hounds.html", "", ["Leaderboard"]), ("kennels.html", "/web/kennels.html", "", ["Kennels"]),
                 ("hound.html", "/web/hound.html", "?id=closer", ["Leaderboard"]), ("build-a-hound.html", "/web/build-a-hound.html", "", ["Build"]),
                 ("learning.html", "/web/learning.html", "", ["Training camp"]), ("live.html", "/web/live.html", "", ["Live"]), ("kennel.html", "/web/kennel.html", "?u=handler-1", ["Kennels"])]
        for page, path, search, want in cases:
            with self.subTest(path=path, search=search):
                got = self.run_nav(page_html=page, pathname=path, search=search)["final"]["current"]
                self.assertEqual(got, want)

    def test_my_kennel_is_current_on_the_kennel_page_without_a_handle(self):
        f = self.run_nav(page_html="kennel.html", pathname="/web/kennel.html", **SIGNED, queries=self.QS + [
            q("mk", "[data-hook='nav-mykennel']", "attr", attr="aria-current")])["final"]
        self.assertEqual(f["mk"], "page")

    def test_the_member_app_gets_no_bottom_bar(self):
        f = run_page("nav", page_html="index.html", queries=[q("tabs", "[data-hook='site-tabbar']", "count"),
                                                              q("bars", ".lh-nav", "count")])["final"]
        self.assertEqual((f["tabs"], f["bars"]), (0, 1))

    def test_the_landing_cta_stays_in_the_bar_for_a_visitor_and_leaves_for_a_member(self):
        visitor = run_page("nav", page_html="landing.html", queries=[q("cta", ".lh-nav [data-hook='cta-primary']", "count")])["final"]
        member = run_page("nav", page_html="landing.html", **SIGNED, queries=[q("cta", ".lh-nav [data-hook='cta-primary']", "count")])["final"]
        self.assertEqual((visitor["cta"], member["cta"]), (1, 0))


# ---------------------------------------------------------------------------------------------------
# the kennel page
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class MyKennel(unittest.TestCase):
    CARDS = "[data-hook='kennel-dog']"

    def page(self, routes, **kw):
        return run_page("kennel", routes=routes, **kw)

    def test_signed_out_is_asked_to_sign_in_or_to_browse_kennels(self):
        out = self.page({}, queries=[q("gate", "[data-hook='kennel-signin']"), q("cards", self.CARDS, "count"),
                                      q("signin", "[data-hook='kennel-signin-link']", "attr", attr="href"),
                                      q("browse", "[data-hook='kennel-browse']", "attr", attr="href")])
        f = out["final"]
        self.assertIn("Sign in to see your dogs", f["gate"])
        self.assertEqual((f["cards"], f["signin"], f["browse"]), (0, "index.html#/signin", "kennels.html"))
        self.assertEqual(out["gets"], [], "a visitor never asks for someone's kennel")

    def test_each_dog_is_a_card_with_its_numbers_status_and_four_one_tap_actions(self):
        dogs = [dog("u-1", "Underdog Gus", wins=3, losses=1, bets=4, units=1.8, last={"selection": "Red Sox ML", "result": "won"}),
                dog("u-2", "Totals Tina"), dog("u-3", "Slumpy", wins=0, losses=2, bets=2, units=-2.0, last={"selection": "Over 8", "result": "lost"})]
        out = self.page({"/hounds/kennels/mine": mine(dogs)}, **SIGNED, queries=[
            q("names", f"{self.CARDS} [data-hook='dog-name']", "texts"), q("records", "[data-hook='dog-record']", "texts"),
            q("bank", "[data-hook='dog-bankroll']", "texts"), q("ret", "[data-hook='dog-return']", "texts"),
            q("status", "[data-hook='dog-status']", "texts"),
            q("last", "[data-hook='dog-last']", "texts"), q("moods", self.CARDS, "attrs", attr="data-mood"),
            q("avatars", f"{self.CARDS} svg.dk-badge", "count"), q("avatar_moods", f"{self.CARDS} svg.dk-badge", "attrs", attr="data-mood"),
            q("fire", "[data-hook='dog-action-fire']", "count"), q("ask", "[data-hook='dog-action-ask']", "count"),
            q("edit", "[data-hook='dog-action-edit']", "count"), q("open", "[data-hook='dog-action-open']", "attrs", attr="href"),
            q("build_card", "[data-hook='kennel-build-card']", "count"), q("title", "[data-hook='kennel-title']"),
            q("count_attr", "[data-hook='dog-bankroll']", "attrs", attr="data-count"),
            q("small", "[data-hook='dog-bankroll']", "attrs", attr="title")])
        f = out["final"]
        self.assertEqual(f["names"], ["Underdog Gus", "Totals Tina", "Slumpy"])
        self.assertEqual(f["records"], ["3-1", "0-0", "0-2"])
        self.assertEqual(f["bank"], ["$1,018", "$1,000", "$980"])                  # every dog starts with the same $1,000
        self.assertEqual(f["ret"], ["+1.8%", "0.0%", "-2.0%"])
        self.assertTrue(all(s.startswith("Ranked in full at") for s in f["small"]), f["small"])   # owner ruling 2026-10-20, complete-product positioning
        self.assertEqual(f["status"], ["Running", "New", "Running"])
        self.assertEqual(f["last"][0], "Last pick: Red Sox ML (won)")
        self.assertIn("No picks yet", f["last"][1])
        self.assertEqual(f["moods"], ["happy", "idle", "slump"])                    # a win wiggles, a loss slumps
        self.assertEqual((f["avatars"], f["avatar_moods"]), (3, ["happy", "idle", "slump"]))
        self.assertEqual((f["fire"], f["ask"], f["edit"], f["build_card"]), (3, 3, 3, 1))
        self.assertEqual(f["open"], ["hound.html?id=u-1", "hound.html?id=u-2", "hound.html?id=u-3"])
        self.assertEqual(f["title"], "My kennel")
        self.assertEqual(f["count_attr"], ["1", "1", "1"])                            # the figures count up when they enter view
        self.assertEqual(out["gets"][0].split("?")[0], "/hounds/kennels/mine")

    def test_a_zero_bet_dog_is_listed_and_flagged_new_not_hidden(self):
        out = self.page({"/hounds/kennels/mine": mine([dog("u-d151fe52c7", "Jsmooth"), dog("u-fcc8e8c168", "Jsmooth27")])}, **SIGNED,
                        queries=[q("names", f"{self.CARDS} [data-hook='dog-name']", "texts"), q("status", "[data-hook='dog-status']", "texts")])
        self.assertEqual(out["final"]["names"], ["Jsmooth", "Jsmooth27"])
        self.assertEqual(out["final"]["status"], ["New", "New"])

    def test_an_open_ticket_shows_a_live_pulse_dot_and_the_count(self):
        out = self.page({"/hounds/kennels/mine": mine([dog("u-1", wins=1, bets=2, units=0.5, open_bets=2, new=False)])}, **SIGNED,
                        queries=[q("status", "[data-hook='dog-status']"), q("dot", "[data-hook='dog-status'] .lh-live", "count")])
        self.assertEqual(out["final"], {"status": "2 open", "dot": 1})

    def test_no_dogs_is_an_empty_state_that_sends_you_to_the_builder(self):
        out = self.page({"/hounds/kennels/mine": mine([])}, **SIGNED, queries=[
            q("empty", "[data-hook='kennel-empty']"), q("cta", "[data-hook='kennel-empty-build']"), q("cards", self.CARDS, "count"),
            q("build_card", "[data-hook='kennel-build-card']", "count")])
        f = out["final"]
        self.assertIn("No dogs yet", f["empty"])
        self.assertEqual(f["cta"], "Build your first dog")
        self.assertEqual((f["cards"], f["build_card"]), (0, 0))

    def test_the_empty_state_button_opens_the_studio_on_the_rules_tab(self):
        out = self.page({"/hounds/kennels/mine": mine([])}, **SIGNED, actions=[
            dict(do="click", sel="[data-hook='kennel-empty-build']", label="open", wait=120, capture=[
                q("hidden", "[data-hook='studio']", "hidden"), q("title", "[data-hook='studio-title']"),
                q("hidden_tabs", "[data-hook='studio-tabs'] [role='tab']", "attrs", attr="hidden")])])
        cap = out["captures"]["open"]
        self.assertEqual((cap["hidden"], cap["title"]), (False, "New dog"))
        # Look, Rules, Unleash, Backtest, Ask, Record: a new dog has only the Rules tab, so the other five hide
        self.assertEqual(cap["hidden_tabs"], ["", None, "", "", "", ""])

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
        self.assertEqual(f["status"], ["Running", "New"])
        self.assertEqual((f["edit"], f["fire"], f["build_card"], f["build"]), (0, 0, 0, 0))     # nothing to change on someone else's dogs
        self.assertEqual(f["open"], ["hound.html?id=u-1", "hound.html?id=u-2"])
        self.assertEqual(f["ask"], ["hound.html?id=u-1&tab=ask", "hound.html?id=u-2&tab=ask"])
        self.assertIn("2 dogs", f["sub"])
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
                                              "notes": [], "preview_note": "Paper only.", "viewer_is_owner": True}]}
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

    def test_fire_now_opens_the_fire_tab_and_fires_at_once(self):
        out = run_page("kennel", routes=self.routes([dog("u-1")]), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-action-fire']", label="fire", wait=300, capture=[
                q("selected", "[role='tab'][aria-selected='true']", "texts"), q("headline", "[data-hook='fire-headline']")])])
        self.assertEqual(out["captures"]["fire"]["selected"], ["Unleash"])
        self.assertEqual(out["captures"]["fire"]["headline"], "Nothing qualifies right now.")
        self.assertEqual([p["url"].split("/")[-2:] for p in out["posts"]], [["u-1", "fire"]])

    def test_ask_opens_the_ask_tab_with_the_dogs_greeting(self):
        out = run_page("kennel", routes=self.routes([dog("u-1")]), **SIGNED, actions=[
            dict(do="click", sel="[data-hook='dog-action-ask']", label="ask", wait=300, capture=[
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
        self.assertEqual(f["meta"], ["2 dogs · New: no bets yet", "1 dog · Best: Rex, 5-2"])
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

    def test_six_tabs_in_order_with_unleash_above_them(self):
        tabs = re.findall(r'role="tab" data-tab="([a-z]+)"', self.HTML)
        self.assertEqual(tabs, ["overview", "tickets", "backtest", "ask", "locker", "rules"])
        self.assertLess(self.HTML.index('data-hook="dog-fire-section"'), self.HTML.index('data-hook="hound-tabs"'))
        self.assertIn(">Unleash<", self.HTML)
        self.assertNotIn(">Out back<", self.HTML)
        self.assertNotIn("Fire now", self.HTML)

    def test_every_section_sits_in_the_panel_it_belongs_to(self):
        def panel(name):
            m = re.search(rf'<div class="lh-tabpanel" data-tabpanel="{name}".*?(?=<div class="lh-tabpanel"|</main>)', self.HTML, re.S)
            return m.group(0)
        self.assertIn('data-hook="hound-scoreboard-section"', panel("overview"))
        self.assertIn('data-hook="hound-chart-section"', panel("overview"))
        self.assertIn('data-hook="hound-verdict-section"', panel("overview"))
        self.assertIn('data-hook="hound-today-section"', panel("tickets"))
        self.assertIn('data-hook="hound-bets-section"', panel("tickets"))
        self.assertIn('data-hook="dog-manual-section"', panel("tickets"))
        self.assertIn('data-hook="dog-backtest-section"', panel("backtest"))
        self.assertIn('data-hook="dog-ask-section"', panel("ask"))
        self.assertIn('data-hook="dog-locker-section"', panel("locker"))
        self.assertIn('data-hook="hound-rule-section"', panel("rules"))
        self.assertIn('data-hook="hound-lineage-section"', panel("rules"))

    def test_only_overview_is_visible_in_the_markup_and_the_owner_tabs_are_optional(self):
        self.assertEqual(len(re.findall(r'data-tabpanel="[a-z]+"[^>]* hidden>', self.HTML)), 5)
        self.assertRegex(self.HTML, r'data-tab="backtest" aria-selected="false" data-optional')
        self.assertRegex(self.HTML, r'data-tab="ask" aria-selected="false" data-optional')
        self.assertRegex(self.HTML, r'data-tab="locker" aria-selected="false" data-optional')

    def test_the_overview_panel_loads_with_skeletons_not_loading_words(self):
        self.assertEqual(self.HTML.count('class="lh-skel '), 4)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TabsRun(unittest.TestCase):
    PANELS = ["overview", "tickets", "backtest", "ask", "locker", "rules"]

    def panels_hidden(self):
        return [q(f"{p}", f"[data-tabpanel='{p}']", "hidden") for p in self.PANELS]

    def test_overview_first_and_a_click_swaps_the_panel(self):
        out = run_page("tabs", captureInitial=self.panels_hidden() + [q("selected", "[role='tab'][aria-selected='true']", "texts")], actions=[
            dict(do="click", sel="[data-tab='tickets']", label="tickets", capture=self.panels_hidden() + [q("selected", "[role='tab'][aria-selected='true']", "texts")])])
        first = out["captures"]["initial"]
        self.assertEqual([first[p] for p in self.PANELS], [False, True, True, True, True, True])
        self.assertEqual(first["selected"], ["Overview"])
        cap = out["captures"]["tickets"]
        self.assertEqual([cap[p] for p in self.PANELS], [True, False, True, True, True, True])
        self.assertEqual(cap["selected"], ["Tickets"])

    def test_a_tab_query_opens_that_tab(self):
        out = run_page("tabs", search="?id=closer&tab=rules", queries=self.panels_hidden())
        self.assertEqual([out["final"][p] for p in self.PANELS], [True, True, True, True, True, False])

    def test_arrow_keys_move_between_the_shown_tabs(self):
        out = run_page("tabs", actions=[dict(do="key", sel="[data-tab='overview']", key="ArrowRight", label="right", capture=[
            q("selected", "[role='tab'][aria-selected='true']", "texts")]),
            dict(do="key", sel="[data-tab='tickets']", key="End", label="end", capture=[q("selected", "[role='tab'][aria-selected='true']", "texts")])])
        self.assertEqual(out["captures"]["right"]["selected"], ["Tickets"])
        self.assertEqual(out["captures"]["end"]["selected"], ["Rules"])

    def test_the_owner_only_tabs_hide_until_their_panel_has_something(self):
        # the markup keeps every Ask / Locker room section hidden until the dog kit shows one; the tab follows it
        out = run_page("tabs", queries=[q("ask", "[data-tab='ask']", "hidden"), q("locker", "[data-tab='locker']", "hidden"),
                                         q("rules", "[data-tab='rules']", "hidden")])
        self.assertEqual((out["final"]["ask"], out["final"]["locker"], out["final"]["rules"]), (True, True, False))

    def test_the_leaderboard_has_a_models_tab_and_a_kennels_tab(self):
        out = run_page("tabs", page_html="hounds.html", captureInitial=[q("tabs", "[role='tab']", "texts"), q("kennels", "[data-tabpanel='kennels']", "hidden"),
                                                                         q("models", "[data-tabpanel='models']", "hidden")],
                       actions=[dict(do="click", sel="[data-tab='kennels']", label="k", capture=[
                           q("kennels", "[data-tabpanel='kennels']", "hidden"), q("models", "[data-tabpanel='models']", "hidden")])])
        first = out["captures"]["initial"]
        self.assertEqual(first["tabs"], ["Models", "Kennels"])
        self.assertEqual((first["models"], first["kennels"]), (False, True))
        self.assertEqual(out["captures"]["k"], {"kennels": False, "models": True})
        out = run_page("tabs", page_html="hounds.html", search="?tab=kennels", queries=[q("kennels", "[data-tabpanel='kennels']", "hidden")])
        self.assertFalse(out["final"]["kennels"])


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
