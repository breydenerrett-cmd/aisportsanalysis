"""The kennel-first pages (owner ruling 2026-10-20, chunk B): the hound page, the leaderboard, kennels, live and the graveyard.

  HOUND PAGE   a hero (big art, name, whose kennel, record with its bet count, paper bankroll, today's status); a visitor gets ONE
               button (Create your own hound) and the owner gets the three actions instead; four tabs (Overview, Tickets, Ask,
               Locker); every term a bettor calls jargon (units, yield, CLV, the referee's status) sits behind "How it's graded".
  LEADERBOARD  one ranked list across all kennels with the LINEHOUND kennel labelled as such, season chips, one primary button, a
               Graveyard link, the house kennel's desk links (the daily card, the record, the sample brief), a compact list with
               "All stats" for every column, and no Models/Kennels tabs.
  EVERY PAGE   compliance once, in the footer, with the tel: link; no second disclosure block; no emoji; one primary button.

Run for real under node against the pages' own HTML (tests/hounds_web_harness.mjs); the static checks need no node.
"""

from __future__ import annotations

import re
import unittest

from tests import hounds_web_fixtures as F
from tests import test_hounds_interact_web as IW
from tests.hounds_web_runner import HAS_NODE, WEB, run_page

q, hook = IW.q, IW.hook
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-⛿✀-➿⭐✅❌]")
PAGES = ["hound.html", "hounds.html", "kennels.html", "live.html", "graveyard.html"]


def html(name):
    return (WEB / name).read_text(encoding="utf-8")


def visible(src):
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", src, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", src))


class EveryPageSaysItsCompliancePartsOnce(unittest.TestCase):
    def test_the_footer_carries_the_line_once_with_a_tel_link(self):
        for name in PAGES:
            with self.subTest(page=name):
                src = html(name)
                foot = re.search(r"<footer.*?</footer>", src, flags=re.S).group(0)
                text = visible(foot)
                for part in ("21+", "Paper bets only, not advice", "Bet at your own risk", "Gamble responsibly.", "1-800-GAMBLER"):
                    self.assertIn(part, text, name)
                self.assertEqual(len(re.findall(r"tel:1-800-426-2537", src)), 1, name)
                self.assertEqual(len(re.findall(r"Gamble responsibly\.", visible(src))), 1, name)
                self.assertEqual(len(re.findall(r"21\+", visible(src))), 1, name)

    def test_no_second_disclosure_block_and_no_emoji(self):
        for name in PAGES:
            with self.subTest(page=name):
                src = html(name)
                self.assertNotIn("hd-disclosure", src, name)
                self.assertIsNone(EMOJI.search(visible(src)), name)

    def test_the_page_head_has_one_primary_button(self):
        for name in ("hounds.html", "kennels.html", "graveyard.html"):
            with self.subTest(page=name):
                main = re.search(r"<main.*?</main>", html(name), flags=re.S).group(0)
                self.assertEqual(len(re.findall(r'class="btn btn--primary', main)), 1, name)
                self.assertIn("Create your own hound", main)
        self.assertIn('href="quiz.html" data-hook="create-cta">Create your own hound', html("hound.html"))

    def test_no_dog_in_the_words_a_person_reads(self):
        for name in PAGES:
            with self.subTest(page=name):
                self.assertNotRegex(visible(html(name)), r"\b[Dd]ogs?\b", name)

    def test_bet_check_is_never_linked(self):
        for name in PAGES:
            self.assertNotRegex(html(name).lower(), r"bet ?check|betcheck", name)


class TheHoundPageMarkup(unittest.TestCase):
    SRC = html("hound.html")

    def test_four_tabs_in_this_order(self):
        tabs = re.findall(r'role="tab" data-tab="(\w+)"', self.SRC)
        self.assertEqual(tabs, ["overview", "tickets", "ask", "locker"])
        self.assertEqual(re.findall(r'data-tabpanel="(\w+)"', self.SRC), ["overview", "tickets", "ask", "locker"])

    def test_the_jargon_sits_behind_how_its_graded(self):
        graded = re.search(r'<details[^>]*data-hook="hound-graded".*?</details>', self.SRC, flags=re.S).group(0)
        self.assertIn("How it's graded", graded)
        for hk in ("hound-scoreboard", "hound-verdict", "hound-clv-chart", "hound-season"):
            self.assertIn(f'data-hook="{hk}"', graded, hk)
        above = self.SRC[:self.SRC.index('data-hook="hound-graded"')]
        for word in ("CLV", "Yield", "Units"):
            self.assertNotIn(word, visible(above), word)

    def test_the_owner_hooks_the_scripts_use_are_all_still_there(self):
        for hk in ("dog-rites", "dog-fire", "dog-ask", "dog-backtest", "dog-fans", "dog-locker", "dog-manual", "hound-actions", "hound-cta"):
            self.assertIn(f'data-hook="{hk}"', self.SRC, hk)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHoundPageHero(unittest.TestCase):
    def go(self, routes, **kw):
        return IW.page(routes, queries=[
            q("kennel", hook("hound-kennel")), q("kennel_house", hook("hound-kennel"), "attr", attr="data-house"),
            q("name", hook("hound-name")), q("record", hook("hero-record")), q("bank", hook("hero-bankroll")),
            q("line", hook("hound-record-line")), q("today", hook("hound-today-status")), q("today_key", hook("hound-today-status"), "attr", attr="data-today"),
            q("cta_hidden", hook("create-cta"), "hidden"), q("viewer", hook("hound-app"), "attr", attr="data-viewer"),
            q("menu", hook("dog-menu"), "exists"), q("buttons", f"{hook('dog-menu')} .btn", "texts"),
            q("note", hook("paper-only-notice"), "count"), q("tabs", "[role='tab']", "texts"),
        ], **kw)

    def test_a_visitor_sees_the_hero_and_one_button(self):
        routes = IW.dog_routes(owner=False, signed_in=False, kind="user")
        routes[f"/hounds/{IW.HID}"][1]["owner_display"] = "Handler 3F2A"
        out = self.go(routes, stored={})["final"]
        self.assertEqual(out["name"], "Closer")
        self.assertEqual(out["kennel"], "Handler 3F2A's kennel")
        self.assertEqual(out["kennel_house"], "0")
        self.assertRegex(out["record"], r"^\d+-\d+(-\d+)?$")
        self.assertRegex(out["line"], r"record, \d+ bets")          # the sample always sits beside the record
        self.assertRegex(out["bank"], r"^\$[\d,]+\.\d\d$")
        self.assertIn("paper bankroll", out["line"])
        self.assertIn(out["today_key"], ("open", "none", "idle", "waiting", "retired"))
        self.assertIn("Today", out["today"])
        self.assertIs(out["cta_hidden"], False)
        self.assertEqual(out["viewer"], "visitor")
        self.assertFalse(out["menu"])
        self.assertEqual(out["note"], 1)

    def test_a_house_hound_lives_in_the_linehound_kennel(self):
        routes = IW.dog_routes(owner=False, signed_in=False, kind="house")
        out = self.go(routes, stored={})["final"]
        self.assertEqual(out["kennel"], "LINEHOUND kennel")
        self.assertEqual(out["kennel_house"], "1")

    def test_the_owner_gets_the_three_actions_and_no_create_button(self):
        kit = IW.Payloads.kit(owner=True, signed_in=True, can_train=True, can_out_back=True)
        routes = IW.dog_routes(owner=True, signed_in=True, kind="user", kit=kit)
        out = self.go(routes)["final"]
        self.assertEqual(out["viewer"], "owner")
        self.assertIs(out["cta_hidden"], True)
        self.assertTrue(out["menu"])
        self.assertEqual(out["buttons"], ["Unleash", "Send to training", "Take them out back"])
        self.assertIn("Locker", out["tabs"])

    def test_the_tabs_a_visitor_sees_are_overview_and_tickets_plus_ask_when_real(self):
        routes = IW.dog_routes(owner=False, signed_in=False, kind="user")
        tabs = self.go(routes, stored={})["final"]["tabs"]
        self.assertEqual(tabs[:2], ["Overview", "Tickets"])
        self.assertNotIn("Backtest", tabs)
        self.assertNotIn("Rules", tabs)


class TheLeaderboardMarkup(unittest.TestCase):
    SRC = html("hounds.html")

    def test_one_ranked_list_no_tabs(self):
        self.assertNotIn("data-autotabs", self.SRC)
        self.assertNotIn("kennels-index", self.SRC)
        self.assertIn('data-hook="hounds-season"', self.SRC)           # the season chips
        self.assertIn('data-hook="view-toggle"', self.SRC)             # All stats
        self.assertIn('href="graveyard.html"', self.SRC)

    def test_the_house_kennel_is_labelled_and_leads_to_the_desk_pages(self):
        house = re.search(r'<section[^>]*data-hook="house-kennel".*?</section>', self.SRC, flags=re.S).group(0)
        self.assertIn("LINEHOUND kennel", house)
        for target in ("hounds.html?scope=house", "index.html#/today", "index.html#/record-card", "sample.html"):
            self.assertIn(f'href="{target}"', house, target)

    def test_the_old_picks_and_sample_pages_are_in_the_footer_too(self):
        foot = re.search(r"<footer.*?</footer>", self.SRC, flags=re.S).group(0)
        self.assertIn('href="sample.html"', foot)
        self.assertIn("index.html#/today", foot)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLeaderboardList(unittest.TestCase):
    def go(self, **kw):
        routes = {k: list(v) for k, v in F.routes().items()}
        return run_page("hounds", routes=routes, queries=[
            q("kennels", "[data-hook='row-kennel']", "texts"), q("houses", "[data-hook='row-kennel']", "attrs", attr="data-house"),
            q("view", hook("hounds-race"), "attr", attr="data-view"), q("toggle", hook("view-toggle")),
            q("inline", "[data-hook='row-bets-inline']", "texts"), q("tabs", "[role='tab']", "count"),
            q("filters", f"{hook('hounds-filter')} .hd-seg", "texts"), q("bankline", hook("bankroll-line")),
            q("heads", "[data-hook='leaderboard-table'] thead th", "texts"),
        ], **kw)

    def test_every_row_names_its_kennel_and_the_house_one_is_labelled(self):
        out = self.go()["final"]
        self.assertGreater(len(out["kennels"]), 5)
        self.assertIn("LINEHOUND kennel", out["kennels"])
        self.assertTrue(all(t == "LINEHOUND kennel" or t.endswith("kennel") or t for t in out["kennels"]))
        self.assertIn("1", out["houses"])
        self.assertEqual(out["tabs"], 0)

    def test_the_sample_sits_beside_every_record(self):
        out = self.go()["final"]
        self.assertTrue(out["inline"])
        self.assertTrue(all(re.fullmatch(r"\d+ bets?", t) for t in out["inline"]), out["inline"])

    def test_the_list_is_compact_until_all_stats_is_pressed(self):
        out = self.go(actions=[dict(do="click", sel=hook("view-toggle"), label="full",
                                    capture=[q("view", hook("hounds-race"), "attr", attr="data-view"), q("toggle", hook("view-toggle"))])])
        self.assertEqual(out["final"]["view"], "full")                 # the click ran
        self.assertEqual(out["captures"]["full"]["view"], "full")
        self.assertEqual(out["captures"]["full"]["toggle"], "Fewer stats")

    def test_the_filter_chips_say_following_and_the_house_kennel(self):
        chips = self.go()["final"]["filters"]
        self.assertTrue(chips[0].startswith("All hounds"))
        self.assertTrue(any(c.startswith("Following") for c in chips))
        self.assertTrue(any(c.startswith("LINEHOUND kennel") for c in chips))

    def test_scope_in_the_address_opens_the_house_filter(self):
        out = run_page("hounds", routes={k: list(v) for k, v in F.routes().items()}, search="?scope=house",
                       queries=[q("on", f"{hook('hounds-filter')} .hd-seg[aria-pressed='true']", "texts")])["final"]
        self.assertTrue(out["on"][0].startswith("LINEHOUND kennel"))

    def test_the_bankroll_line_is_one_short_line_with_the_paper_note(self):
        line = self.go()["final"]["bankline"]
        self.assertIn("$1,000", line)
        self.assertIn("Paper money, not advice.", line)
        self.assertNotRegex(line, r"unit")

    def test_the_old_kennels_tab_address_goes_to_the_kennels_page(self):
        js = (WEB / "js" / "hounds-page.js").read_text(encoding="utf-8")
        self.assertIn('params.get("tab") === "kennels"', js)
        self.assertIn('window.location.replace("kennels.html")', js)


class KennelsLiveAndGraveyardMarkup(unittest.TestCase):
    def test_kennels_leads_with_the_house_kennel_and_keeps_the_my_kennel_link(self):
        src = html("kennels.html")
        self.assertIn('data-hook="kennels-house"', src)
        self.assertIn("LINEHOUND kennel", src)
        self.assertIn('data-hook="kennels-mine"', src)
        self.assertIn('data-hook="kennels-index"', src)

    def test_the_graveyard_links_back_and_keeps_its_hooks(self):
        src = html("graveyard.html")
        for hk in ("graveyard-list", "graveyard-count", "graveyard-kennels", "graveyard-board"):
            self.assertIn(f'data-hook="{hk}"', src, hk)

    def test_live_says_live_and_keeps_its_hooks(self):
        src = html("live.html")
        self.assertIn('<h1 data-hook="live-title">Live</h1>', src)
        for hk in ("live-chips", "live-board", "live-status", "live-refresh", "paper-only-notice"):
            self.assertIn(f'data-hook="{hk}"', src, hk)


if __name__ == "__main__":
    unittest.main()
