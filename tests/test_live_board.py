"""The live board, "What's on" (web/live.html + web/js/live-board.js), and the places that point at it.

Static checks need no node: the page is in the shared navigation (and the navigation names it on every page), the footer keeps 21+,
the 1-800-GAMBLER link and "paper only / bet at your own risk" and is styled by a stylesheet the page loads, no script tag is inline
(the page opens from file://), nothing names Bet Check, and nothing claims an advantage. The run checks use the real page script under
node against the fake DOM of tests/hounds_web_harness.mjs, with the fixture tests/fixtures/sports_now.json standing in for
GET /sports/now (the contract the backend is building): the fixture renders, LIVE comes before the next 24 hours, times are in the
viewer's zone, an empty sport says when the next game is, the board refreshes every 60 seconds and keeps its last board when a
refresh fails, and "Send a hound" asks a signed-out visitor to sign in and runs the existing out-back route for a member.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, WEB, run_page

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sports_now.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
TOKEN_KEY = "aisportsanalysis.invite_token"
NOW = "2026-10-19T23:30:00Z"            # the fixture's own clock
LA = "America/Los_Angeles"              # October 19, 2026 at 23:30Z is 4:30 PM PDT

HTML = (WEB / "live.html").read_text(encoding="utf-8")
JS = (WEB / "js" / "live-board.js").read_text(encoding="utf-8")
CSS = (WEB / "css" / "live.css").read_text(encoding="utf-8")


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def hook(name):
    return f"[data-hook='{name}']"


def board(routes=None, **kw):
    r = {"/sports/now": [200, FIXTURE]}
    r.update(routes or {})
    kw.setdefault("now", NOW)
    kw.setdefault("tz", LA)
    kw.setdefault("pathname", "/web/live.html")
    return run_page("live", routes=r, **kw)


def strip_comments(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


class TheFixtureMatchesTheContract(unittest.TestCase):
    """The shape GET /sports/now is being built to: if the fixture drifts, the page tests below test nothing."""

    def test_families_and_rows_have_the_contract_fields(self):
        self.assertIn("generated_utc", FIXTURE)
        self.assertGreaterEqual(len(FIXTURE["families"]), 5)
        row_keys = {"event_id", "league_title", "home", "away", "start_utc", "in_play", "best_price_home", "best_price_away"}
        seen = set()
        for fam in FIXTURE["families"]:
            self.assertEqual(set(fam) - {"code", "label", "live", "upcoming_24h", "next_start_utc"}, set())
            for kind, in_play in (("live", True), ("upcoming_24h", False)):
                for ev in fam[kind]:
                    self.assertTrue(row_keys <= set(ev), ev)
                    self.assertEqual(ev["in_play"], in_play, ev["event_id"])
                    self.assertNotIn(ev["event_id"], seen)
                    seen.add(ev["event_id"])

    def test_it_holds_the_cases_the_page_must_handle(self):
        fams = {f["code"]: f for f in FIXTURE["families"]}
        self.assertTrue(any(f["live"] for f in fams.values()))
        self.assertTrue(any(not f["live"] and f["upcoming_24h"] for f in fams.values()))
        self.assertTrue(any(not f["live"] and not f["upcoming_24h"] and f["next_start_utc"] for f in fams.values()), "an empty sport with a next game")
        self.assertTrue(any(not f["live"] and not f["upcoming_24h"] and not f["next_start_utc"] for f in fams.values()), "an empty sport with none")
        scores = [type(ev.get("score")).__name__ for f in fams.values() for ev in f["live"]]
        self.assertTrue({"dict", "str", "NoneType"} <= set(scores), "a score as an object, as a string and absent")


class TheLivePageIsPartOfTheSite(unittest.TestCase):
    def test_the_shared_navigation_names_live_on_every_page_that_has_it(self):
        pages = [p for p in sorted(WEB.glob("*.html")) if 'class="lh-nav"' in p.read_text(encoding="utf-8")]
        self.assertGreaterEqual(len(pages), 12)
        for path in pages:
            html = path.read_text(encoding="utf-8")
            with self.subTest(page=path.name):
                self.assertRegex(html, r'<a href="live.html" data-nav="live"[^>]*>Live</a>')
        nav_js = (WEB / "js" / "nav.js").read_text(encoding="utf-8")
        self.assertIn('{ key: "live", label: "Live", href: "live.html" }', nav_js)      # owner ruling 2026-10-20 kennel-first

    def test_the_page_marks_itself_current_and_loads_the_navigation(self):
        self.assertIn('data-current="live"', HTML)
        self.assertIn('data-nav="live" aria-current="page"', HTML)
        self.assertIn('<script type="module" src="js/nav.js"></script>', HTML)
        self.assertIn('href="css/lhnav.css"', HTML)

    def test_the_phone_tab_bar_has_room_for_five(self):
        # # owner ruling 2026-10-20 kennel-first: My Kennel, Create, Live, Leaderboard, Account
        css = (WEB / "css" / "lhnav.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: repeat(5, 1fr)", css)

    def test_the_footer_keeps_21_plus_the_helpline_and_paper_only(self):
        foot = re.search(r"<footer[^>]*>(.*?)</footer>", HTML, re.S)
        self.assertIsNotNone(foot)
        text = " ".join(re.sub(r"<[^>]+>", " ", foot.group(1)).split())
        self.assertIn("21+", text)
        self.assertIn("Paper bets only", text)
        self.assertIn("own risk", text)
        self.assertRegex(foot.group(1), r'<a href="tel:1-800-426-2537"[^>]*>1-800-GAMBLER</a>')

    def test_the_paper_only_line_is_static_text_near_the_top(self):
        # compliance is said once, in the footer (above); next to the prices there is one short line (owner ruling 2026-10-20 kennel-first)
        main = HTML.split("<main")[1]
        self.assertRegex(main.split("</header>")[1][:600], r"Best price any book quoted when the board was read\. In-play prices move fast\. Paper picks only\.")

    def test_the_footer_is_styled_by_a_stylesheet_the_page_loads(self):
        links = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', HTML)
        # this page uses the hub pages' static footer (.hd-foot, css/hounds.css); had it mounted the shared one it would need css/app.css
        if 'data-hook="disclaimer-host"' in HTML:
            self.assertIn("css/app.css", links)
        self.assertIn("css/hounds.css", links)
        self.assertIn(".hd-foot", (WEB / "css" / "hounds.css").read_text(encoding="utf-8"))
        self.assertIn("css/live.css", links)
        for href in links:
            self.assertTrue((WEB / href).is_file(), href)

    def test_it_opens_from_a_file_no_inline_script_no_external_asset(self):
        self.assertNotRegex(HTML, r"<script(?![^>]*\bsrc=)[^>]*>")
        self.assertNotRegex(HTML, r'(src|href)="https?://')
        self.assertNotRegex(HTML, r"<img\b")

    def test_it_never_names_bet_check_and_claims_no_advantage(self):
        for name, raw in (("live.html", HTML), ("live-board.js", JS), ("live.css", CSS)):
            body = strip_comments(raw)
            self.assertNotRegex(body.lower(), r"bet[\s_-]*check", name)
            self.assertNotRegex(body, r"(?i)\b(profit|guarantee[sd]?|roi|win rate|sure thing|beat the market|edge|expected value|\+ev)\b", name)

    def test_the_dog_page_links_the_board_when_there_is_no_game(self):
        fire_js = strip_comments((WEB / "js" / "dog-fire.js").read_text(encoding="utf-8"))
        self.assertIn('href: "live.html"', fire_js)
        self.assertIn("See what's on in every sport", fire_js)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBoardRenders(unittest.TestCase):
    def test_the_fixture_renders_live_first_then_the_next_24_hours(self):
        out = board(queries=[
            q("chips", hook("live-chip"), "texts"), q("pressed", "[data-hook='live-chip'][aria-pressed='true']", "texts"),
            q("sections", ".lv-section__title", "texts"),
            q("live_n", hook("live-live-count")), q("up_n", hook("live-upcoming-count")),
            q("live_rows", "[data-hook='live-live-list'] [data-hook='live-row']", "count"),
            q("up_rows", "[data-hook='live-upcoming-list'] [data-hook='live-row']", "count"),
            q("status", hook("live-status"))])
        self.assertFalse(out.get("crashed"), out.get("crashed"))
        f = out["final"]
        live = sum(len(x["live"]) for x in FIXTURE["families"])
        up = sum(len(x["upcoming_24h"]) for x in FIXTURE["families"])
        self.assertEqual(f["sections"], ["Live now", "Next 24 hours"])
        self.assertEqual((f["live_rows"], f["up_rows"]), (live, up))
        self.assertEqual((f["live_n"], f["up_n"]), (str(live), str(up)))
        self.assertTrue(f["chips"][0].startswith("All"))
        self.assertEqual(f["pressed"], [f["chips"][0]])
        labels = {x["label"] for x in FIXTURE["families"]}
        self.assertEqual({re.sub(r"\s*\d+$", "", c) for c in f["chips"][1:]}, labels)
        self.assertIn("Board as of 4:30 PM PDT", f["status"])
        self.assertIn("refreshes every minute", f["status"])
        text = out["text"]
        self.assertLess(text.index("Live now"), text.index("Next 24 hours"))

    def test_a_row_shows_both_sides_the_league_the_prices_and_the_viewers_clock(self):
        out = board(queries=[
            q("row", "[data-event='soc-1'][data-hook='live-row']"), q("up", "[data-event='soc-4'][data-hook='live-row']"),
            q("score", "[data-event='soc-1'] [data-hook='live-score']", "texts"), q("pill", "[data-event='soc-1'] [data-hook='live-pill']"),
            q("prices", "[data-event='soc-1'] .lv-price", "texts"), q("names", "[data-event='soc-1'] .lv-team__name", "texts"),
            q("when", "[data-event='soc-4'] [data-hook='live-when']"), q("strwhen", "[data-event='soc-2'] .lv-detail")])
        f = out["final"]
        self.assertIn("English Premier League", f["row"])
        self.assertEqual(f["names"], ["Fulham", "Brighton and Hove Albion"])          # away on top, home under it
        self.assertEqual(f["prices"], ["+310", "-135"])
        self.assertEqual(f["score"], ["0", "1"])
        self.assertEqual(f["pill"], "Live")
        self.assertIn("Started 3:45 PM", f["row"])                                       # 22:45Z in Los Angeles
        self.assertEqual(f["when"], "6:30 PM · in 2 h")                                  # 01:30Z the next day is 6:30 PM PDT today
        self.assertEqual(f["strwhen"], "0-0, 31'")                                       # a string score is shown as the server wrote it
        self.assertIn("Send a hound", f["row"])  # owner ruling 2026-10-20 kennel-first

    def test_the_same_board_in_another_zone_shows_that_zones_clock(self):
        out = board(tz="Europe/London", queries=[q("when", "[data-event='soc-4'] [data-hook='live-when']")])
        # 23:30Z is already 12:30 AM on the 20th in London, so 01:30Z is 2:30 AM the same day there (and 6:30 PM the day before in Los Angeles)
        self.assertEqual(out["final"]["when"], "2:30 AM · in 2 h")

    def test_a_missing_price_says_so_and_a_row_never_shows_not_reported(self):
        data = json.loads(json.dumps(FIXTURE))
        data["families"][0]["live"][0]["best_price_away"] = None
        out = board({"/sports/now": [200, data]}, queries=[q("prices", "[data-event='soc-1'] .lv-price", "texts")])
        self.assertEqual(out["final"]["prices"], ["no price", "-135"])

    def test_a_sport_chip_shows_only_that_sport_and_writes_the_address(self):
        out = board(actions=[dict(do="click", sel="[data-hook='live-chip'][data-family='tennis']", label="tennis", wait=60)], queries=[
            q("rows", "[data-hook='live-row']", "attrs", attr="data-family"), q("pressed", "[data-hook='live-chip'][aria-pressed='true']", "texts"),
            q("league_tag", ".lv-family", "count")])
        f = out["final"]
        self.assertEqual(set(f["rows"]), {"tennis"})
        self.assertEqual(len(f["rows"]), 7)
        self.assertEqual(len(f["pressed"]), 1)
        self.assertTrue(f["pressed"][0].startswith("Tennis"))
        self.assertEqual(f["league_tag"], 0)                                              # the sport tag is only for the All view
        self.assertEqual(out["replaced"], ["live.html?sport=tennis"])

    def test_the_all_view_tags_each_row_with_its_sport(self):
        out = board(queries=[q("tags", ".lv-family", "texts")])
        self.assertIn("Tennis", out["final"]["tags"])
        self.assertIn("Soccer", out["final"]["tags"])

    def test_a_sport_in_the_address_opens_on_it_and_an_unknown_one_falls_back_to_all(self):
        out = board(search="?sport=hockey", queries=[q("rows", "[data-hook='live-row']", "attrs", attr="data-family")])
        self.assertEqual(set(out["final"]["rows"]), {"hockey"})
        out = board(search="?sport=curling", queries=[q("rows", "[data-hook='live-row']", "count"), q("pressed", "[data-hook='live-chip'][aria-pressed='true']", "texts")])
        self.assertGreater(out["final"]["rows"], 10)
        self.assertTrue(out["final"]["pressed"][0].startswith("All"))

    def test_an_empty_sport_says_when_the_next_game_is(self):
        out = board(actions=[dict(do="click", sel="[data-hook='live-chip'][data-family='football']", label="f", wait=60)], queries=[q("empty", hook("live-empty"))])
        # 2026-10-22T00:15Z is Wednesday 5:15 PM in Los Angeles
        self.assertEqual(out["final"]["empty"], "Nothing on in Football right now. Next: Wed 5:15 PM.")

    def test_an_empty_sport_with_no_known_next_game_does_not_invent_one(self):
        out = board(actions=[dict(do="click", sel="[data-hook='live-chip'][data-family='cricket']", label="c", wait=60)], queries=[q("empty", hook("live-empty"))])
        self.assertEqual(out["final"]["empty"], "Nothing on in Cricket right now.")

    def test_a_sport_with_games_to_come_but_none_live_says_so_in_the_live_section(self):
        out = board(actions=[dict(do="click", sel="[data-hook='live-chip'][data-family='hockey']", label="h", wait=60)], queries=[
            q("live_empty", hook("live-live-empty")), q("rows", "[data-hook='live-upcoming-list'] [data-hook='live-row']", "count")])
        self.assertEqual(out["final"]["live_empty"], "Nothing live in Hockey right now.")
        self.assertEqual(out["final"]["rows"], 1)

    def test_a_long_list_is_capped_and_the_rest_is_one_tap_away(self):
        data = json.loads(json.dumps(FIXTURE))
        fam = data["families"][0]
        fam["upcoming_24h"] = [dict(fam["upcoming_24h"][0], event_id=f"many-{i}", start_utc=f"2026-10-20T{(i % 20) + 1:02d}:00:00Z") for i in range(30)]
        out = board({"/sports/now": [200, data]}, actions=[dict(do="click", sel="[data-hook='live-chip'][data-family='soccer']", label="s", wait=60)],
                    queries=[q("rows", "[data-hook='live-upcoming-list'] [data-hook='live-row']", "count"), q("more", hook("live-upcoming-more"))],
                    captureInitial=[])
        self.assertEqual(out["final"]["rows"], 20)
        self.assertEqual(out["final"]["more"], "Show 10 more")
        out = board({"/sports/now": [200, data]}, actions=[dict(do="click", sel="[data-hook='live-chip'][data-family='soccer']", label="s", wait=60),
                                                         dict(do="click", sel="[data-hook='live-upcoming-more']", label="m", wait=60)],
                    queries=[q("rows", "[data-hook='live-upcoming-list'] [data-hook='live-row']", "count")])
        self.assertEqual(out["final"]["rows"], 30)

    def test_the_board_is_not_there_message_when_the_server_has_no_route(self):
        out = board({"/sports/now": [404, {"detail": "Not Found"}]}, queries=[q("err", hook("live-error"))])
        self.assertIn("not switched on yet", out["final"]["err"])

    def test_a_visitor_gets_a_way_to_sign_in_not_a_dead_end(self):
        # rebuild QA 2026-10-21: signed out, Live (a visitor nav place) said "Loading the board..." above "The live board
        # needs you to be signed in." with no link anywhere on the page
        out = board({"/sports/now": [401, {"detail": "Not signed in"}]},
                    queries=[q("err", hook("live-error")), q("link", f"{hook('live-error')} a", "attr", attr="href"),
                             q("status", hook("live-status"))])
        self.assertIn("signed-in members", out["final"]["err"])
        self.assertEqual(out["final"]["link"], "index.html#/signin")
        self.assertNotIn("Loading", out["final"]["status"] or "")

    def test_an_old_board_says_how_old_and_that_prices_may_have_moved(self):
        out = board(now="2026-10-19T23:52:00Z", queries=[q("status", hook("live-status"))])
        self.assertIn("22 min old, so prices may have moved", out["final"]["status"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBoardRefreshesItself(unittest.TestCase):
    def test_it_polls_every_60_seconds_and_a_tick_reads_the_board_again(self):
        out = board(actions=[dict(do="fire_timers", label="tick", wait=80)])
        self.assertEqual(out["intervals"], [60000])
        self.assertEqual(len([g for g in out["gets"] if g.endswith("/sports/now")]), 2)

    def test_a_hidden_page_does_not_poll(self):
        out = board(visibility="hidden", actions=[dict(do="fire_timers", label="tick", wait=60)])
        self.assertEqual(len([g for g in out["gets"] if g.endswith("/sports/now")]), 1)

    def test_a_failed_refresh_keeps_the_last_board_and_says_so(self):
        out = board({}, failAfter={"/sports/now": 1}, actions=[dict(do="fire_timers", label="tick", wait=80)], queries=[
            q("rows", "[data-hook='live-row']", "count"), q("note", hook("live-refresh-note")), q("hidden", hook("live-refresh-note"), "hidden")])
        f = out["final"]
        self.assertGreater(f["rows"], 10)
        self.assertFalse(f["hidden"])
        self.assertIn("did not go through", f["note"])

    def test_a_refresh_after_recovery_clears_the_note(self):
        out = board({}, switchAfter={"/sports/now": [1, [200, FIXTURE]]}, failAfter={}, actions=[dict(do="fire_timers", label="tick", wait=80)],
                    queries=[q("hidden", hook("live-refresh-note"), "hidden")])
        self.assertTrue(out["final"]["hidden"])

    def test_the_refresh_button_reads_the_board_now(self):
        out = board(actions=[dict(do="click", sel=hook("live-refresh"), label="r", wait=80)])
        self.assertEqual(len([g for g in out["gets"] if g.endswith("/sports/now")]), 2)


DOG = {"id": "u-1", "name": "Plus Money Pete", "status": "running", "page_href": "hound.html?id=u-1", "look": None}
RETIRED = {"id": "u-2", "name": "Old Rex", "status": "retired", "page_href": "hound.html?id=u-2"}


def fire_answer(**over):
    out = {"dog_id": "u-1", "headline": "1 pick qualifies on the latest stored boards.", "games_considered": 4,
           "picks": [{"event_id": "soc-4", "market": "moneyline", "market_label": "Moneyline", "selection": "Seattle Sounders FC to win",
                      "game": "Portland Timbers at Seattle Sounders FC", "price_average": -105, "price_best": -102, "n_books": 6, "reason": "Inside its price band."}],
           "closest_misses": [{"event_id": "ten-5", "game": "Holger Rune at Casper Ruud", "market_label": "Moneyline", "code": "price",
                               "title": "Price too short", "why": "Casper Ruud is at -150, past its limit."}],
           "preview_note": "A preview is not a ticket.", "notes": []}
    out.update(over)
    return out


@unittest.skipUnless(HAS_NODE, "node not installed")
class SendADog(unittest.TestCase):
    SEND = "[data-event='{}'] [data-hook='live-send']"

    def test_a_signed_out_visitor_is_asked_to_sign_in_and_nothing_is_requested(self):
        out = board(actions=[dict(do="click", sel=self.SEND.format("soc-4"), label="send", wait=80)], queries=[
            q("tray", "[data-event='soc-4'] [data-hook='live-tray']"), q("href", "[data-event='soc-4'] [data-hook='signin-prompt'] a", "attr", attr="href"),
            q("expanded", self.SEND.format("soc-4"), "attr", attr="aria-expanded")])
        f = out["final"]
        self.assertIn("Sign in to send one of your hounds at Portland Timbers at Seattle Sounders FC", f["tray"])
        self.assertEqual(f["href"], "index.html#/signin")
        self.assertEqual(f["expanded"], "true")
        self.assertFalse([g for g in out["gets"] if "/hounds/" in g])
        self.assertEqual(out["posts"], [])

    def test_a_second_tap_closes_the_tray(self):
        sel = self.SEND.format("soc-4")
        out = board(actions=[dict(do="click", sel=sel, wait=60), dict(do="click", sel=sel, wait=60)], queries=[q("tray", "[data-hook='live-tray']", "count")])
        self.assertEqual(out["final"]["tray"], 0)

    def test_a_member_sees_their_dogs_and_a_retired_one_is_left_out(self):
        routes = {"/hounds/camp/mine": [200, {"dogs": [DOG, RETIRED], "count": 2}]}
        out = board(routes, stored={TOKEN_KEY: "tok"}, actions=[dict(do="click", sel=self.SEND.format("soc-4"), wait=100)], queries=[
            q("dogs", hook("live-dog"), "texts"), q("ask", ".lv-tray__ask")])
        self.assertEqual(out["final"]["dogs"], ["Plus Money Pete Running"])
        self.assertEqual(out["final"]["ask"], "Send which hound at Portland Timbers at Seattle Sounders FC?")
        self.assertEqual(out["posts"], [])                                                # choosing is not firing

    def test_a_member_with_no_dog_is_pointed_at_the_builder(self):
        routes = {"/hounds/camp/mine": [200, {"dogs": [], "count": 0}]}
        out = board(routes, stored={TOKEN_KEY: "tok"}, actions=[dict(do="click", sel=self.SEND.format("soc-4"), wait=100)], queries=[
            q("none", hook("live-no-dogs")), q("href", "[data-hook='live-no-dogs'] a", "attr", attr="href")])
        self.assertIn("no running hound", out["final"]["none"])
        self.assertEqual(out["final"]["href"], "quiz.html")

    def test_sending_a_dog_calls_the_existing_out_back_route_and_reports_its_pick_on_that_game(self):
        routes = {"/hounds/camp/mine": [200, {"dogs": [DOG], "count": 1}], "POST /hounds/u-1/fire": [200, fire_answer()]}
        out = board(routes, stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel=self.SEND.format("soc-4"), wait=100), dict(do="click", sel=hook("live-dog"), wait=150)], queries=[
            q("result", hook("live-result")), q("kind", ".lv-result__line", "attr", attr="data-kind"), q("full", ".lv-full summary"),
            q("open", "[data-event='soc-4'] a.btn", "attr", attr="href")])
        self.assertEqual([p["url"].split("/")[-3:] for p in out["posts"]], [["hounds", "u-1", "fire"]])
        f = out["final"]
        self.assertIn("Plus Money Pete would back Seattle Sounders FC to win (Moneyline).", f["result"])
        self.assertIn("Average price -105", f["result"])
        self.assertEqual(f["kind"], "pick")
        self.assertEqual(f["full"], "Everything Plus Money Pete returned")
        self.assertEqual(f["open"], "hound.html?id=u-1")

    def test_a_dog_that_passed_on_the_game_says_why(self):
        routes = {"/hounds/camp/mine": [200, {"dogs": [DOG], "count": 1}], "POST /hounds/u-1/fire": [200, fire_answer()]}
        out = board(routes, stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel=self.SEND.format("ten-5"), wait=100), dict(do="click", sel=hook("live-dog"), wait=150)], queries=[
            q("result", hook("live-result")), q("kind", ".lv-result__line", "attr", attr="data-kind")])
        self.assertIn("Plus Money Pete passes on this one.", out["final"]["result"])
        self.assertIn("Price too short.", out["final"]["result"])
        self.assertEqual(out["final"]["kind"], "miss")

    def test_a_game_the_answer_does_not_mention_is_not_made_up(self):
        routes = {"/hounds/camp/mine": [200, {"dogs": [DOG], "count": 1}], "POST /hounds/u-1/fire": [200, fire_answer()]}
        out = board(routes, stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel=self.SEND.format("hoc-1"), wait=100), dict(do="click", sel=hook("live-dog"), wait=150)], queries=[
            q("result", hook("live-result")), q("kind", ".lv-result__line", "attr", attr="data-kind")])
        self.assertIn("Plus Money Pete did not return this game.", out["final"]["result"])
        self.assertEqual(out["final"]["kind"], "none")

    def test_a_failed_send_says_so_and_lets_them_pick_again(self):
        routes = {"/hounds/camp/mine": [200, {"dogs": [DOG], "count": 1}], "POST /hounds/u-1/fire": [429, {"detail": "slow down"}]}
        out = board(routes, stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel=self.SEND.format("soc-4"), wait=100), dict(do="click", sel=hook("live-dog"), wait=150)], queries=[
            q("err", hook("live-send-error"))])
        self.assertIn("a lot of tries", out["final"]["err"])

    def test_an_open_tray_survives_a_refresh(self):
        routes = {"/hounds/camp/mine": [200, {"dogs": [DOG], "count": 1}]}
        out = board(routes, stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel=self.SEND.format("soc-4"), wait=100), dict(do="fire_timers", label="tick", wait=100)], queries=[
            q("dogs", hook("live-dog"), "count"), q("expanded", self.SEND.format("soc-4"), "attr", attr="aria-expanded")])
        self.assertEqual(out["final"]["dogs"], 1)
        self.assertEqual(out["final"]["expanded"], "true")

    def test_the_copy_around_it_says_nothing_is_placed(self):
        routes = {"/hounds/camp/mine": [200, {"dogs": [DOG], "count": 1}]}
        out = board(routes, stored={TOKEN_KEY: "tok"}, actions=[dict(do="click", sel=self.SEND.format("soc-4"), wait=100)], queries=[q("tray", hook("live-tray"))])
        self.assertIn("Nothing is placed", out["final"]["tray"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheDogPageNoGames(unittest.TestCase):
    """The dog page's "Out back" panel (web/js/dog-fire.js renderFireResult) with no pick: the server's own next-game and live-elsewhere
    words, and a link to the live board. The route and the page come from tests/test_hounds_interact_web.py."""

    def fire(self, owner=False, **over):
        """The panel with no pick, as the visitor's read-only preview (POST /fire) and as the owner's real Unleash (POST /unleash):
        both carry the same ``next_game`` / ``live_elsewhere`` words, so the same expectations hold for both."""
        from tests.test_hounds_interact_web import Payloads, dog_routes, hook as dhook, page as dog_page, unleash_day
        payload = Payloads.fire_payload()
        payload.update(picks=[], recorded=[], closest_misses=[], headline="No upcoming game on the stored boards for this dog's sports.")
        payload.update(over)
        if owner:
            routes = dog_routes(unleash_payload=unleash_day(picks=[], placed_now=0, before=[], headline="Nothing on today's board fits yet.",
                                                            **{k: v for k, v in over.items() if k in ("next_game", "live_elsewhere")}))
        else:
            routes = dog_routes(owner=False, fire_payload=payload)
        return dog_page(routes, actions=[dict(do="click", sel=dhook("fire-btn"), wait=120)], queries=[
            q("block", "[data-hook='dog-fire'] [data-hook='fire-elsewhere']"), q("next", "[data-hook='dog-fire'] [data-hook='fire-next-game']"),
            q("elsewhere", "[data-hook='dog-fire'] [data-hook='fire-live-elsewhere']"),
            q("href", "[data-hook='dog-fire'] [data-hook='fire-live-link']", "attr", attr="href"), q("count", "[data-hook='dog-fire'] [data-hook='fire-live-link']", "count")])

    def test_no_pick_shows_the_servers_words_and_a_link_to_the_live_board(self):
        for owner in (False, True):
            f = self.fire(owner=owner, next_game="Next game it can bet: Thursday 7:00 PM ET.",
                          live_elsewhere="Live now in other sports: Tennis 4, Soccer 3.")["final"]
            self.assertEqual(f["next"], "Next game it can bet: Thursday 7:00 PM ET.", owner)
            self.assertEqual(f["elsewhere"], "Live now in other sports: Tennis 4, Soccer 3.", owner)
            self.assertEqual(f["href"], "live.html", owner)
            self.assertIn("See what's on in every sport", f["block"])

    def test_a_server_that_sends_neither_still_gets_the_link(self):
        for owner in (False, True):
            f = self.fire(owner=owner)["final"]
            self.assertEqual(f["href"], "live.html", owner)
            self.assertIsNone(f["next"])
            self.assertIsNone(f["elsewhere"])

    def test_a_dog_with_a_pick_does_not_get_the_block(self):
        from tests.test_hounds_interact_web import Payloads, dog_routes, hook as dhook, page as dog_page
        payload = Payloads.fire_payload()
        self.assertTrue(payload["picks"], "the standard fire fixture has a pick")
        out = dog_page(dog_routes(owner=False, fire_payload=payload), actions=[dict(do="click", sel=dhook("fire-btn"), wait=100)],
                       queries=[q("count", "[data-hook='dog-fire'] [data-hook='fire-live-link']", "count")])
        self.assertEqual(out["final"]["count"], 0)
        own = dog_page(dog_routes(), actions=[dict(do="click", sel=dhook("fire-btn"), wait=120)],
                       queries=[q("count", "[data-hook='dog-fire'] [data-hook='fire-live-link']", "count")])
        self.assertEqual(own["final"]["count"], 0, "the owner's day with a pick has no empty-day block either")


if __name__ == "__main__":
    unittest.main()
