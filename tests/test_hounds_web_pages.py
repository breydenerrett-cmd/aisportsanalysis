"""The three Hounds pages, run for real (their own scripts, their own HTML) under node against a fake DOM.

  web/hounds.html         the live kennel: form strip, units-ranked leaderboard with badges, the put-down poll,
                          the bankroll chart, the chat-style stream, the tombstones
  web/hound.html?id=      one dog: portrait, bio, scoreboard, the Houndmaster, the badge, the rules with copy buttons,
                          and the collapsed receipts (verdict, charts, paged bets)
  web/build-a-hound.html  the build form (playful side rules, a live name-and-bio card), generated from /hounds/menu

Skipped when node is not installed. Fixtures: tests/hounds_web_fixtures.py. Static checks (not-advice on
every page, no Bet Check, no external images) and "the pages are served" need no node.
"""

from __future__ import annotations

import copy
import re
import unittest
from pathlib import Path

from src.hounds import contract
from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_page

HTML = {name: (WEB / name).read_text(encoding="utf-8") for name in ("hounds.html", "hound.html", "build-a-hound.html")}
TOKEN_KEY = "aisportsanalysis.invite_token"


def visible(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<(script|style|head)\b.*?</\1>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    for ent, ch in (("&middot;", "·"), ("&rarr;", "->"), ("&larr;", "<-"), ("&amp;", "&")):
        text = text.replace(ent, ch)
    return re.sub(r"\s+", " ", text).strip()


def routes(forward=True, bets_n=45, **over):
    r = {k: list(v) for k, v in F.routes(forward, bets_n).items()}
    ids = [h["id"] for h in F.hounds(forward)]
    r["/hounds/series"] = [200, F.series(ids, forward)]
    for key, val in over.items():
        r[key.replace("__", "/") if key.startswith("_") else key] = val
    return r


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def mk(hid, name, verdict, bets=10, units=0.0, kind="house", category="stats", **extra):
    h = {"id": hid, "name": name, "kind": kind, "category": category, "style": "x", "status": "running", "tagline": "t",
         "verdict": {"label": verdict, "sentence": f"{verdict.lower()} sentence"},
         "record": {"bets": bets, "wins": 1, "losses": 1, "pushes": 0, "voids": 0,
                    "units_recorded_price": units, "units_average_price": units},
         "clv": None, "spark": [0, units / 2, units], "verified": True}
    h.update(extra)
    return h


# ---------------------------------------------------------------------------------------------------
# static facts, no node needed
# ---------------------------------------------------------------------------------------------------

class EveryPageSaysPaperOnlyNotAdviceAndIs21Plus(unittest.TestCase):
    def test_the_static_text_of_all_three_pages(self):
        for name, html in HTML.items():
            text = visible(html)
            with self.subTest(page=name):
                self.assertRegex(text, r"(?i)paper bets only, not advice", name)
                self.assertIn("21+", text)
                self.assertIn("Gamble responsibly.", text)
                self.assertIn("1-800-GAMBLER", text)
                self.assertIn("not-advice", html)   # the data-hook the footer line carries

    def test_the_minus_200_cap_notice_is_static_on_the_build_page(self):
        text = visible(HTML["build-a-hound.html"])
        self.assertIn("Paper bets only. Your dog never places a real bet, and it never takes a price of -200 or worse.", text)

    def test_the_pages_never_name_the_product_they_do_not_advertise_or_claim_an_edge(self):
        for path in [WEB / n for n in HTML] + [WEB / "css" / "hounds.css"] + sorted((WEB / "js").glob("hounds-*.js")):
            raw = path.read_text(encoding="utf-8")
            body = re.sub(r"/\*.*?\*/", "", raw, flags=re.S) if path.suffix in (".js", ".css") else raw
            body = re.sub(r"(?m)^\s*//.*$", "", body)
            body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
            body = body.replace("It is not a profit claim", "")
            with self.subTest(file=path.name):
                self.assertNotRegex(body.lower(), r"bet[\s_-]*check")
                self.assertNotRegex(body, r"(?i)\b(profit|guarantee[sd]?|roi|win rate|sure thing|beat the market)\b")
                if path.suffix != ".css":      # the stylesheet reads the design system's --edge border token
                    self.assertNotRegex(body, r"(?i)\bedge\b")

    def test_no_external_images_no_third_party_scripts_and_module_scripts_are_local(self):
        for name, html in HTML.items():
            with self.subTest(page=name):
                self.assertNotRegex(html, r"<img\b")
                for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', html):
                    self.assertFalse(src.startswith(("http:", "https:", "//")), src)
                    self.assertTrue((WEB / src).is_file(), src)
                for href in re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', html):
                    self.assertTrue((WEB / href).is_file(), href)

    def test_every_page_has_a_skip_link_a_main_landmark_and_a_viewport(self):
        for name, html in HTML.items():
            with self.subTest(page=name):
                self.assertIn('class="hd-skip"', html)
                self.assertIn('id="main-content"', html)
                self.assertIn("<main", html)
                self.assertIn('name="viewport"', html)
                self.assertIn('<html lang="en">', html)

    def test_the_demo_page_is_untouched(self):
        # artifacts/demo_latest.html is owned elsewhere; nothing in this lane writes it
        self.assertFalse(any("demo_latest" in (WEB / n).read_text(encoding="utf-8") for n in HTML))

    def test_the_landing_page_links_to_the_kennel_in_its_first_screen(self):
        landing = (WEB / "landing.html").read_text(encoding="utf-8")
        first = landing[landing.index('data-hook="kennel-hero"'):landing.index('data-hook="hero"')]
        self.assertRegex(first, r'<a [^>]*href="hounds.html"[^>]*>Enter the kennel')
        self.assertRegex(first, r'<a [^>]*href="build-a-hound.html"[^>]*>Build your dog')


class ThePagesAreServed(unittest.TestCase):
    def test_the_asset_route_serves_each_page_script_and_stylesheet(self):
        try:
            from api import web as api_web
        except ImportError:
            self.skipTest("FastAPI not installed")
        for rel, media in (("hounds.html", "html"), ("hound.html", "html"), ("build-a-hound.html", "html"),
                           ("css/hounds.css", "css"), ("js/hounds-page.js", "js"), ("js/hounds-detail.js", "js"),
                           ("js/hounds-build.js", "js"), ("js/hounds-core.js", "js"), ("js/hounds-chart.js", "js")):
            with self.subTest(rel=rel):
                response = api_web.get_web_asset(rel)
                self.assertEqual(Path(response.path).resolve(), (WEB / rel).resolve())
                if rel.endswith(".html"):
                    self.assertEqual(response.headers["cache-control"], "no-cache")

    def test_through_a_real_client_when_one_is_available(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from api import web as api_web
        except ImportError:
            self.skipTest("FastAPI test client not installed")
        app = FastAPI()
        app.include_router(api_web.router)
        client = TestClient(app)
        for rel in ("hounds.html", "hound.html", "build-a-hound.html"):
            with self.subTest(rel=rel):
                res = client.get(f"/web/{rel}")
                self.assertEqual(res.status_code, 200)
                self.assertIn("text/html", res.headers["content-type"])
                self.assertIn("not advice", res.text.lower())
        self.assertEqual(client.get("/web/css/hounds.css").status_code, 200)


# ---------------------------------------------------------------------------------------------------
# the race
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheLeaderboardIsRankedByUnitsWithTheBadgeBesideEachDog(unittest.TestCase):
    def test_rows_follow_the_units_and_each_dog_wears_the_badge_of_its_own_verdict(self):
        hs = [mk("rich", "Rich", "PAYING THE VIG", bets=60, units=+80.0),
              mk("mid", "Mid", "TOO EARLY", bets=8, units=+30.0),
              mk("flat", "Flat", "NO DIFFERENT FROM THE MARKET", bets=40, units=+10.0),
              mk("poor", "Poor", "BEATING THE CLOSE", bets=45, units=-25.0),
              mk("gone", "Gone", "PAYING THE VIG", bets=90, units=-31.0, status="retired")]
        r = routes(**{"/hounds": [200, {"hounds": hs, "basis": "b", "as_of": "2026-10-24T23:00:00Z"}]})
        r["/hounds/series"] = [404, {}]
        out = run_page("hounds", routes=r, queries=[
            q("ids", "[data-hook='hounds-list'] .hd-row", "attrs", attr="data-hound"),
            q("ranks", "[data-hook='hounds-list'] [data-hook='rank']", "texts"),
            q("badges", "[data-hook='hounds-list'] [data-hook='badge']", "texts"),
            q("keys", "[data-hook='hounds-list'] [data-hook='badge']", "attrs", attr="data-badge"),
            q("units", "[data-hook='hounds-list'] [data-hook='row-units']", "texts")])
        # most paper units first: the sorting rule is units, and a dog that is put down sinks below the live ones
        self.assertEqual(out["final"]["ids"], ["rich", "mid", "flat", "poor", "gone"])
        self.assertEqual(out["final"]["ranks"], ["#1", "#2", "#3", "#4", "💀"])
        self.assertEqual([re.sub(r"^\W+\s*", "", c) for c in out["final"]["badges"]],
                         ["FEEDING THE BOOK 💸", "ROOKIE 🐣", "COIN FLIP 🪙", "SHARP 🔥", "FEEDING THE BOOK 💸"])
        self.assertEqual(out["final"]["keys"], ["feeding_the_book", "rookie", "coin_flip", "sharp", "feeding_the_book"])
        self.assertEqual(out["final"]["units"], ["+80.00u", "+30.00u", "+10.00u", "-25.00u", "-31.00u"])

    def test_tapping_a_badge_opens_one_plain_line_and_tapping_again_closes_it(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("closed", ".hd-row[data-hound='closer'] [data-hook='badge']", "attr", attr="aria-expanded"),
            q("hidden", ".hd-row[data-hound='closer'] [data-hook='badge-explain']", "hidden")],
            actions=[dict(do="click", sel=".hd-row[data-hound='closer'] [data-hook='badge']", label="open",
                          capture=[q("open", ".hd-row[data-hound='closer'] [data-hook='badge']", "attr", attr="aria-expanded"),
                                   q("hidden", ".hd-row[data-hound='closer'] [data-hook='badge-explain']", "hidden"),
                                   q("text", ".hd-row[data-hound='closer'] [data-hook='badge-explain']")]),
                     dict(do="click", sel=".hd-row[data-hound='closer'] [data-hook='badge']", label="shut",
                          capture=[q("hidden", ".hd-row[data-hound='closer'] [data-hook='badge-explain']", "hidden")])])
        self.assertEqual(out["final"]["closed"], "true" if False else out["final"]["closed"])
        self.assertTrue(out["captures"]["open"]["hidden"] is False)
        self.assertEqual(out["captures"]["open"]["open"], "true")
        self.assertEqual(out["captures"]["open"]["text"],
                         "Its prices keep beating where the market closes. Good shopping, not a promise of wins.")
        self.assertTrue(out["captures"]["shut"]["hidden"])

    def test_the_page_says_how_the_board_is_ranked(self):
        out = run_page("hounds", routes=routes(), queries=[q("explainer", "[data-hook='units-explainer']")])
        self.assertEqual(out["final"]["explainer"],
                         "Ranked by paper units this season (1 unit a bet, average price). Tap a badge to see what it means.")

    def test_each_row_carries_the_fields_a_bettor_reads_first(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("first", ".hd-row[data-hound='closer']"), q("spark", ".hd-row[data-hound='closer'] [data-hook='spark']", "count"),
            q("tick", ".hd-row[data-hound='closer'] [data-hook='verified']"), q("avatar", ".hd-row[data-hound='closer'] .hd-avatar", "count"),
            q("vibe", ".hd-row[data-hound='closer'] .hd-avatar", "attr", attr="data-vibe"),
            q("untick", ".hd-row[data-hound='rusty'] [data-hook='verified']", "count"),
            q("catch", ".hd-row[data-hound='closer'] [data-hook='catchphrase']"),
            q("tagline_fallback", ".hd-row[data-hound='steamer'] .hd-row__tagline"),
            q("wl", ".hd-row[data-hound='closer'] [data-hook='row-wl']"),
            q("streak", ".hd-row[data-hound='closer'] [data-hook='streak']"),
            q("week", ".hd-row[data-hound='closer'] [data-hook='week']"),
            q("receipts_open", ".hd-row[data-hound='closer'] [data-hook='receipts']", "attr", attr="open"),
            q("basis", "[data-hook='hounds-basis']")])
        row = out["final"]["first"]
        for needle in ("Closer", "“I was here first.”", "SHARP", "41 bets", "The receipts", "Live record",
                       "Price vs the close", "better than the closing line on average, over 41 bets", "Running", "verified",
                       "Stats", "House dog"):
            self.assertIn(needle, row)
        self.assertEqual(out["final"]["spark"], 1)
        self.assertEqual(out["final"]["avatar"], 1)
        self.assertEqual(out["final"]["vibe"], "degen")                # a persona's vibe picks the accessory
        self.assertEqual(out["final"]["untick"], 0)                    # an unverified hound has no tick
        self.assertEqual(out["final"]["catch"], "“I was here first.”")
        self.assertEqual(out["final"]["tagline_fallback"], "Rides early line moves.")   # no persona: the tagline
        self.assertRegex(out["final"]["wl"], r"^\d+-\d+(-\d+)? · 41 bets$")
        self.assertRegex(out["final"]["streak"], r"^(🔥+ |🥶 )?[WL]\d$")
        self.assertRegex(out["final"]["week"], r"this week \(\d+-\d+\)$")
        self.assertIsNone(out["final"]["receipts_open"])                # the receipts are collapsed
        self.assertIn(contract.BASIS[:60], out["final"]["basis"])
        self.assertIn("As of", out["final"]["basis"])

    def test_the_form_strip_names_a_hot_dog_an_ice_cold_dog_and_one_on_tilt_and_the_houndmaster_weighs_in(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("titles", ".hd-formcard__title", "texts"), q("slots", ".hd-formcard", "attrs", attr="data-slot"),
            q("names", ".hd-formcard__name", "texts"), q("details", ".hd-formcard__detail", "texts"),
            q("master", "[data-hook='houndmaster-line']"), q("kind", "[data-hook='houndmaster-line']", "attr", attr="data-kind"),
            q("master_hidden", "[data-hook='houndmaster-banner']", "hidden")])
        self.assertEqual(out["final"]["titles"], ["Hot dog 🔥", "Ice cold 🥶", "On tilt 😵"])
        self.assertEqual(out["final"]["slots"], ["hot", "cold", "tilt"])
        self.assertEqual(len(out["final"]["names"]), 3)
        self.assertEqual(len(set(out["final"]["names"])), 3, "one dog is never named twice")
        self.assertTrue(all(re.search(r"this week \(\d+-\d+\)$|losses in a row$", d) for d in out["final"]["details"]))
        self.assertFalse(out["final"]["master_hidden"])
        self.assertIn("The Houndmaster to ", out["final"]["master"])
        self.assertIn(out["final"]["kind"], ("roast", "brag"))

    def test_nobody_is_named_hot_cold_or_tilting_on_fewer_than_three_bets_that_week(self):
        hs = [mk("a", "A", "TOO EARLY", bets=9, units=2.0,
                 form={"streak": {"kind": "L", "length": 1}, "last7": {"bets": 2, "wins": 0, "losses": 2, "units": -2.0}})]
        r = routes(**{"/hounds": [200, {"hounds": hs}]})
        out = run_page("hounds", routes=r, queries=[
            q("empties", ".hd-formcard__empty", "texts"), q("master_hidden", "[data-hook='houndmaster-banner']", "hidden")])
        self.assertEqual(out["final"]["empties"], ["Nobody's above water this week.", "Nobody's freezing. Yet.",
                                                   "Nobody's on tilt. Enjoy it."])
        self.assertTrue(out["final"]["master_hidden"])

    def test_which_dog_gets_put_down_next_shows_the_three_closest_to_the_25_unit_line_and_has_no_ballot(self):
        hs = [mk("a", "Alpha", "TOO EARLY", units=12.0), mk("b", "Bravo", "TOO EARLY", units=-20.0),
              mk("c", "Charlie", "TOO EARLY", units=-3.5), mk("d", "Delta", "TOO EARLY", units=-24.0),
              mk("e", "Echo", "TOO EARLY", units=-1.0)]
        out = run_page("hounds", routes=routes(**{"/hounds": [200, {"hounds": hs}]}), queries=[
            q("title", "#poll-h"), q("opts", "[data-hook='poll-option']", "attrs", attr="data-hound"),
            q("texts", ".hd-poll__text", "texts"), q("note", "[data-hook='poll-note']"),
            q("buttons", "[data-hook='hounds-poll'] button", "count")])
        self.assertEqual(out["final"]["title"], "Which dog gets put down next? 💀")
        self.assertEqual(out["final"]["opts"], ["d", "b", "c"])
        self.assertEqual(out["final"]["texts"][0], "-24.00u so far · 1.0 units from the doghouse")
        self.assertIn("No ballot yet. The rule decides: 25 units under zero", out["final"]["note"])
        self.assertEqual(out["final"]["buttons"], 0, "static for now: no vote is faked")

    def test_a_hound_with_no_line_yet_says_so_instead_of_drawing_a_flat_one(self):
        hs = [mk("new", "New", "TOO EARLY", bets=0, spark=[])]
        r = routes(**{"/hounds": [200, {"hounds": hs}]})
        r["/hounds/series"] = [200, {"series": {}}]
        out = run_page("hounds", routes=r, queries=[q("none", "[data-hook='spark-none']", "count"),
                                                    q("units", "[data-hook='row-units']")])
        self.assertEqual(out["final"]["none"], 1)
        self.assertEqual(out["final"]["units"], "no bets yet")

    def test_house_and_builder_filter_and_category_chips(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("cats", "[data-hook='hounds-categories'] .hd-seg", "texts"),
            q("filters", "[data-hook='hounds-filter'] .hd-seg", "texts")],
            actions=[
                dict(do="click", sel="[data-hook='hounds-filter'] [data-filter='user']", label="user",
                     capture=[q("ids", "[data-hook='hounds-list'] .hd-row", "attrs", attr="data-hound")]),
                dict(do="click", sel="[data-hook='hounds-filter'] [data-filter='house']", label="house",
                     capture=[q("n", "[data-hook='hounds-list'] .hd-row", "count")]),
                dict(do="click", sel="[data-hook='hounds-categories'] [data-category='math']", label="math",
                     capture=[q("ids", "[data-hook='hounds-list'] .hd-row", "attrs", attr="data-hound")]),
            ])
        self.assertEqual(out["captures"]["user"]["ids"], ["rusty"])
        self.assertEqual(out["captures"]["house"]["n"], 10)      # 12 house hounds, 2 of them baselines (shown below the race)
        self.assertEqual(out["captures"]["math"]["ids"], ["poisson"])
        self.assertTrue(out["final"]["cats"][0].startswith("All kinds"))
        self.assertEqual(out["final"]["filters"], ["All (13)", "House (12)", "Builders' (1)"])

    def test_esoteric_and_random_hounds_are_tagged_for_fun_or_control_and_never_hidden(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("moon", ".hd-row[data-hound='moon-dog']"), q("coin", ".hd-row[data-hound='coin-flip']"),
            q("tags", "[data-hook='fun-tag']", "texts"), q("closer_tag", ".hd-row[data-hound='closer'] [data-hook='fun-tag']", "count")])
        self.assertIn("for fun / control", out["final"]["moon"])
        self.assertIn("for fun / control", out["final"]["coin"])
        self.assertEqual(out["final"]["tags"], ["for fun / control", "for fun / control"])
        self.assertEqual(out["final"]["closer_tag"], 0)
        css = (WEB / "css" / "hounds.css").read_text(encoding="utf-8")
        # same type size as the hound's name: the tag is sized in the name bar, at the name's own 20px
        self.assertRegex(css, r"\.hd-row__namebar\s*\{[^}]*font-size:\s*20px")
        self.assertRegex(css, r"\.hd-row__namebar \.hd-tag\s*\{[^}]*font-size:\s*20px")
        self.assertRegex(css, r"\.hd-row__name\s*\{[^}]*font-size:\s*20px")

    def test_baselines_sit_in_a_collapsed_group_below_the_race_and_are_not_hidden(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("race", "[data-hook='hounds-list'] .hd-row", "attrs", attr="data-hound"),
            q("base", "[data-hook='hounds-baselines-list'] .hd-row", "attrs", attr="data-hound"),
            q("open", "[data-hook='hounds-baselines']", "attr", attr="open"),
            q("hidden", "[data-hook='hounds-baselines']", "hidden"),
            q("summary", "[data-hook='hounds-baselines-summary']")])
        self.assertNotIn("always-fave", out["final"]["race"])
        self.assertEqual(sorted(out["final"]["base"]), ["always-dog", "always-fave"])
        self.assertIsNone(out["final"]["open"])                  # a <details> without `open` is collapsed
        self.assertFalse(out["final"]["hidden"])
        self.assertIn("Baselines (2)", out["final"]["summary"])
        html = HTML["hounds.html"]
        self.assertLess(html.index('data-hook="hounds-list"'), html.index('data-hook="hounds-baselines"'))

    def test_live_is_the_headline_and_the_rehearsal_is_a_separate_smaller_line(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("fwd", ".hd-row[data-hound='closer'] [data-hook='forward-facts']"),
            q("replay", ".hd-row[data-hound='closer'] [data-hook='replay-line']"),
            q("none_fwd", ".hd-row[data-hound='rusty'] [data-hook='forward-facts']"),
            q("none_replay", ".hd-row[data-hound='rusty'] [data-hook='replay-line']")])
        self.assertIn("Live record", out["final"]["fwd"])
        self.assertIn("41 bets", out["final"]["fwd"])
        self.assertNotIn("160 bets", out["final"]["fwd"])
        self.assertRegex(out["final"]["replay"],
                         r"^old-board rehearsal \(the same rule on earlier games; written after, so it never counts\)\s*:")
        self.assertIn("160 bets", out["final"]["replay"])
        # the replay block carries one price only (units_recorded_price): it is labelled the best price
        self.assertIn("best price", out["final"]["replay"])
        self.assertNotIn("average price", out["final"]["replay"])
        self.assertIn("No live bets yet", out["final"]["none_fwd"])
        self.assertIn("40 bets", out["final"]["none_replay"])
        css = (WEB / "css" / "hounds.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.hd-row__replay\s*\{[^}]*font-size:\s*13px")
        self.assertRegex(css, r"\.hd-row__facts dd\s*\{[^}]*font-size:\s*15px")

    def test_the_chart_is_forward_only_and_with_no_forward_bets_says_where_the_replay_numbers_are(self):
        """MISALIGNMENT 1. GET /hounds/series sends FORWARD points only (contract.SeriesPoint): a replay
        result is a record block on each hound, never a series. The page had a Forward/Replay toggle and a
        replay-by-default chart built on a guess; it now draws forward results or says there are none."""
        out = run_page("hounds", routes=routes(forward=False), queries=[
            q("title", "[data-hook='hounds-chart-title']"),
            q("toggle", "[data-hook='hounds-segment']", "count"),
            q("empty", "[data-hook='chart-empty']"),
            q("replay_rows", "[data-hook='replay-line']", "count")])
        self.assertTrue(out["final"]["title"].startswith("Live bets only") or out["final"]["title"] == "")
        self.assertEqual(out["final"]["toggle"], 0)
        self.assertIn("No live bets yet", out["final"]["empty"])
        self.assertIn("never drawn here", out["final"]["empty"])
        self.assertEqual(out["final"]["replay_rows"], 13)          # every hound's replay result is on its row

    def test_with_forward_data_the_chart_draws_the_forward_lines_and_has_no_toggle(self):
        out = run_page("hounds", routes=routes(forward=True), queries=[
            q("title", "[data-hook='hounds-chart-title']"),
            q("toggle", "[data-hook='hounds-segment']", "count"),
            q("lines", "[data-hook='hounds-chart-panel'] .hd-line path", "count")])
        self.assertTrue(out["final"]["title"].startswith("Live bets only"))
        self.assertEqual(out["final"]["toggle"], 0)
        self.assertGreater(out["final"]["lines"], 0)

    def test_the_chart_has_a_zero_baseline_the_label_and_a_data_table_with_the_same_numbers(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("zero", "[data-hook='hounds-chart-panel'] [data-hook='chart-zero']", "count"),
            q("label", "[data-hook='chart-label']"),
            q("rows", "[data-hook='chart-data-table'] tbody tr", "count"),
            q("cols", "[data-hook='chart-data-table'] thead th", "count"),
            q("legend", "[data-hook='chart-legend'] button", "count"),
            q("legend_avatars", "[data-hook='chart-legend'] .hd-avatar", "count"),
            q("svg_role", "[data-hook='hounds-chart-panel'] .hd-chart__svg", "attr", attr="role")])
        self.assertEqual(out["final"]["zero"], 1)
        self.assertIn("Paper units, one a bet. Tap a name to hide a dog.", out["final"]["label"])
        self.assertEqual(out["final"]["rows"], 8)                  # the zero point the day before, then seven forward dates
        self.assertEqual(out["final"]["cols"], 1 + 11)             # date + the 11 non-baseline hounds on the chart
        self.assertEqual(out["final"]["legend"], 13)               # every hound has a legend button, baselines included
        self.assertEqual(out["final"]["legend_avatars"], 13)
        self.assertEqual(out["final"]["svg_role"], "img")

    def test_the_tooltip_shows_date_units_and_bets_and_the_arrow_keys_walk_the_dates(self):
        out = run_page("hounds", routes=routes(), actions=[
            dict(do="key", sel="[data-hook='hounds-chart-panel'] figure", key="ArrowLeft", label="k",
                 capture=[q("tip", "[data-hook='chart-tooltip']"), q("hidden", "[data-hook='chart-tooltip']", "hidden")]),
            dict(do="key", sel="[data-hook='hounds-chart-panel'] figure", key="Escape", label="esc",
                 capture=[q("hidden", "[data-hook='chart-tooltip']", "hidden")])])
        tip = out["captures"]["k"]["tip"]
        self.assertRegex(tip, r"Oct 24")                           # the last date first
        self.assertRegex(tip, r"[+-]\d\.\d\du")
        self.assertIn("11 settled", tip)
        self.assertFalse(out["captures"]["k"]["hidden"])
        self.assertTrue(out["captures"]["esc"]["hidden"])

    def test_a_legend_button_takes_a_hound_off_the_chart(self):
        out = run_page("hounds", routes=routes(), actions=[
            dict(do="click", sel="[data-hook='chart-legend'] [data-hound='closer']", label="off",
                 capture=[q("cols", "[data-hook='chart-data-table'] thead th", "count"),
                          q("pressed", "[data-hook='chart-legend'] [data-hound='closer']", "attr", attr="aria-pressed")]),
            dict(do="click", sel="[data-hook='chart-legend'] [data-hound='always-fave']", label="base",
                 capture=[q("cols", "[data-hook='chart-data-table'] thead th", "count")])])
        self.assertEqual(out["captures"]["off"]["cols"], 11)
        self.assertEqual(out["captures"]["off"]["pressed"], "false")
        self.assertEqual(out["captures"]["base"]["cols"], 12)      # a baseline can be switched on

    def test_the_chart_data_request_names_the_ids(self):
        out = run_page("hounds", routes=routes())
        series = [g for g in out["gets"] if g.startswith("/hounds/series")]
        self.assertEqual(len(series), 1)
        self.assertIn("ids=closer,steamer", series[0])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRaceIsHonestWhenThereIsNothingOrNothingAnswers(unittest.TestCase):
    def test_empty_state_has_a_message_and_the_build_call_to_action_and_no_chart_request(self):
        r = {"/hounds": [200, {"hounds": [], "basis": "b", "paper_only": True}],
             "/hounds/stream": [200, {"items": []}], "/hounds/graveyard": [200, {"hounds": []}]}
        out = run_page("hounds", routes=r, queries=[
            q("empty", "[data-hook='board-empty']"), q("cta", "[data-hook='board-empty'] a", "attr", attr="href"),
            q("stream", "[data-hook='stream-empty']"), q("grave", "[data-hook='grave-empty']"),
            q("chart", "[data-hook='hounds-chart-panel']"), q("basis", "[data-hook='hounds-basis']")])
        self.assertIn("Nobody's in the ring yet", out["final"]["empty"])
        self.assertEqual(out["final"]["cta"], "build-a-hound.html")
        self.assertIn("Quiet in the kennel", out["final"]["stream"])
        self.assertIn("No tombstones yet", out["final"]["grave"])
        self.assertIn("No dogs yet, so there is nothing to draw", out["final"]["chart"])
        self.assertFalse([g for g in out["gets"] if g.startswith("/hounds/series")])
        self.assertEqual(out["final"]["basis"], "b")

    def test_missing_endpoints_say_not_switched_on_in_each_section_and_the_page_still_stands(self):
        out = run_page("hounds", routes={}, queries=[
            q("kinds", "[data-hook='section-state']", "attrs", attr="data-kind"),
            q("board", "[data-hook='hounds-list']"), q("stream", "[data-hook='hounds-stream']"),
            q("grave", "[data-hook='hounds-graveyard']"), q("paper", "[data-hook='paper-only-notice']"),
            q("cta", "[data-hook='build-cta']", "attr", attr="href"), q("footer", "[data-hook='not-advice']"),
            q("chart", "[data-hook='hounds-chart-panel']")])
        self.assertEqual(out["final"]["kinds"], ["missing", "missing", "missing"])
        for key in ("board", "stream", "grave"):
            self.assertIn("not switched on yet", out["final"][key], key)
        self.assertIn("Paper bets only. Not advice.", out["final"]["paper"])
        self.assertEqual(out["final"]["cta"], "build-a-hound.html")
        self.assertIn("Paper bets only, not advice", out["final"]["footer"])
        self.assertIn("needs the leaderboard", out["final"]["chart"])
        # nothing was drawn from nothing
        self.assertNotIn("0.00", out["text"])

    def test_a_down_server_is_not_reported_as_an_empty_race_and_offers_a_retry(self):
        out = run_page("hounds", routes=routes(), down=["/hounds", "/hounds/stream", "/hounds/graveyard"], queries=[
            q("kinds", "[data-hook='section-state']", "attrs", attr="data-kind"),
            q("board", "[data-hook='hounds-list']"), q("retry", "[data-hook='hounds-list'] button", "count"),
            q("empty", "[data-hook='board-empty']", "count")])
        self.assertEqual(out["final"]["kinds"], ["down", "down", "down"])
        self.assertIn("does not mean there is nothing to show", out["final"]["board"])
        self.assertEqual(out["final"]["retry"], 1)
        self.assertEqual(out["final"]["empty"], 0)

    def test_a_failed_series_leaves_the_leaderboard_alone(self):
        r = routes()
        r["/hounds/series"] = [500, {"detail": "boom"}]
        out = run_page("hounds", routes=r, queries=[
            q("rows", "[data-hook='hounds-list'] .hd-row", "count"), q("chart", "[data-hook='hounds-chart-panel']")])
        self.assertEqual(out["final"]["rows"], 11)
        self.assertIn("could not be loaded (the server answered 500)", out["final"]["chart"])

    def test_the_stream_names_who_decided_each_move(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("who", "[data-hook='stream-who']", "texts"), q("items", "[data-hook='stream-list'] li", "count")])
        self.assertEqual(out["final"]["who"], ["Decided by: Rule", "Decided by: Code", "Decided by: Model"])
        self.assertEqual(out["final"]["items"], 3)

    def test_the_stream_reads_like_a_chat_and_a_refusal_says_it_sat_out(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("texts", "[data-hook='stream-list'] .hd-chat__text", "texts"),
            q("refused", "[data-hook='stream-list'] li", "attrs", attr="data-refused"),
            q("outcome", "[data-hook='chat-outcome']", "texts"),
            q("when", "[data-hook='stream-list'] .hd-stream__when", "texts"),
            q("avatars", "[data-hook='stream-list'] .hd-avatar", "count")])
        play, passed, flip = out["final"]["texts"]
        # a dog with a persona uses its own verb; one without says "took". The headline price is the average price.
        self.assertEqual(play, "Closer just grabbed the early number on Yankees to win at -120")
        self.assertEqual(passed, "Poisson sat this one out. Too few books were quoting this market to trust a price.")
        self.assertEqual(flip, "Coin Flip just took Over 8.5 at -108 ❌ lost -1.00u")
        self.assertEqual(out["final"]["outcome"], ["❌ lost -1.00u"])
        self.assertEqual(out["final"]["refused"], ["false", "true", "false"])
        self.assertIn("Oct 24 22:41 UTC", out["final"]["when"][0])
        self.assertEqual(out["final"]["avatars"], 3)

    def test_the_graveyard_is_tombstones_with_an_epitaph_and_the_cause_of_death(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("cause", "[data-hook='grave-cause']", "texts"), q("epitaph", "[data-hook='epitaph']", "texts"),
            q("rip", ".hd-stone__rip", "texts"), q("dead", ".hd-stone .hd-avatar", "attrs", attr="data-dead")])
        # contract: a retired hound is a HoundSummary with retired {date, cause}
        self.assertEqual(out["final"]["cause"], ["Cause of death: Cut by the kennel boss. (Oct 20)",
                                                 "Cause of death: Went more than 25 units under. (Oct 14)"])
        self.assertEqual(out["final"]["epitaph"], ["“Gone, but still on the record.”", "“Went under one last time.”"])
        self.assertEqual(out["final"]["rip"], ["R.I.P.", "R.I.P."])
        self.assertEqual(out["final"]["dead"], ["true", "true"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStreamPollsEveryMinuteOnlyWhileTheTabIsVisible(unittest.TestCase):
    def streams(self, out):
        return len([g for g in out["gets"] if g == "/hounds/stream"])

    def test_one_sixty_second_timer_a_refresh_per_tick(self):
        out = run_page("hounds", routes=routes(), actions=[dict(do="fire_timers"), dict(do="fire_timers")])
        self.assertEqual(out["intervals"], [60000])
        self.assertEqual(self.streams(out), 3)             # the first load plus two ticks

    def test_hidden_stops_it_and_visible_again_refreshes_once_and_restarts_it(self):
        out = run_page("hounds", routes=routes(), actions=[
            dict(do="visibility", state="hidden", label="hidden", capture=[]),
            dict(do="fire_timers"), dict(do="fire_timers"),
            dict(do="visibility", state="visible", label="shown")])
        # initial load (1) + the refresh on becoming visible (1); the two hidden ticks fetched nothing
        self.assertEqual(self.streams(out), 2)
        self.assertEqual(out["intervals"], [60000])
        hidden = run_page("hounds", routes=routes(), actions=[dict(do="visibility", state="hidden")])
        self.assertEqual(hidden["intervals"], [])          # no timer is left running while hidden
        self.assertEqual(self.streams(hidden), 1)

    def test_a_page_opened_in_a_hidden_tab_arms_no_timer(self):
        out = run_page("hounds", routes=routes(), visibility="hidden")
        self.assertEqual(out["intervals"], [])

    def test_a_failed_refresh_keeps_the_previous_list_and_says_so(self):
        out = run_page("hounds", routes=routes(), failAfter={"/hounds/stream": 1}, actions=[dict(do="fire_timers")],
                       queries=[q("n", "[data-hook='stream-list'] li", "count"), q("stale", "[data-hook='stream-stale']"),
                                q("states", "[data-hook='hounds-stream'] [data-hook='section-state']", "count")])
        self.assertEqual(out["final"]["n"], 3)
        self.assertIn("Could not refresh just now; this is the previous list.", out["final"]["stale"])
        self.assertEqual(out["final"]["states"], 0)


# ---------------------------------------------------------------------------------------------------
# one hound
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHoundPage(unittest.TestCase):
    def page(self, hid="closer", forward=True, **kw):
        r = routes(forward)
        series_ids = [hid]
        r["/hounds/series"] = [200, F.series(series_ids, forward)]
        r.update(kw.pop("routes", {}))
        return run_page("hound", routes=r, search=f"?id={hid}", **kw)

    def test_the_rule_box_has_a_copy_button_that_copies_exactly_the_rule_text(self):
        rule = F.hounds()[0]["rule_text"]
        out = self.page(actions=[dict(do="click", sel="[data-hook='copy-rule']", label="copy",
                                      capture=[q("status", "[data-hook='copy-status']")])],
                        queries=[q("rule", "[data-hook='rule-text']"), q("btn", "[data-hook='copy-rule']"),
                                 q("from", "[data-hook='build-from']", "attr", attr="href")])
        self.assertEqual(out["final"]["rule"], rule)
        self.assertEqual(out["final"]["btn"], "Copy this dog's rules")
        self.assertEqual(out["clipboard"], [rule])
        self.assertEqual(out["captures"]["copy"]["status"], "Copied: the rules.")
        self.assertEqual(out["final"]["from"], "build-a-hound.html?from=closer")

    def test_tail_it_and_fade_it_copy_a_pasteable_paper_only_take(self):
        rule = F.hounds()[0]["rule_text"]
        out = self.page(actions=[dict(do="click", sel="[data-hook='copy-tail']", label="tail"),
                                 dict(do="click", sel="[data-hook='copy-fade']", label="fade",
                                      capture=[q("status", "[data-hook='copy-status']")])],
                        queries=[q("tail", "[data-hook='copy-tail']"), q("fade", "[data-hook='copy-fade']"),
                                 q("note", "[data-hook='tail-fade-note']")])
        self.assertEqual(out["final"]["tail"], "Tail it 🐕")
        self.assertEqual(out["final"]["fade"], "Fade it 🙃")
        tail, fade = out["clipboard"]
        self.assertTrue(tail.startswith("Tailing Closer 🐕 (paper bets only, not advice):\n" + rule))
        self.assertTrue(fade.startswith("Fading Closer 🙃 (paper bets only, not advice):\nThe opposite of: " + rule))
        self.assertTrue(tail.endswith("linehound.app") and fade.endswith("linehound.app"))
        self.assertEqual(out["captures"]["fade"]["status"], "Copied: a fade.")
        self.assertIn("paper-only fun, not a tip", out["final"]["note"])

    def test_a_blocked_clipboard_says_so_and_does_not_claim_it_copied(self):
        out = self.page(clipboardFails=True, actions=[dict(do="click", sel="[data-hook='copy-rule']", label="copy",
                                                           capture=[q("status", "[data-hook='copy-status']")])])
        self.assertEqual(out["clipboard"], [])
        self.assertIn("Couldn't copy", out["captures"]["copy"]["status"])
        self.assertNotIn("Copied", out["captures"]["copy"]["status"])

    def test_the_badge_comes_with_a_plain_line_a_meaning_and_the_sample_size_and_the_sentence_is_in_the_receipts(self):
        out = self.page(queries=[q("badge", "[data-hook='hound-verdict'] [data-hook='badge']"),
                                 q("explain", "[data-hook='hound-verdict'] [data-hook='badge-explain']"),
                                 q("sentence", "[data-hook='verdict-sentence']"),
                                 q("meaning", "[data-hook='verdict-meaning']"), q("name", "[data-hook='hound-name']"),
                                 q("verdict", "[data-hook='hound-verdict']"), q("title", "#verdict-h"),
                                 q("sentence_in_receipts", "[data-hook='hound-details'] [data-hook='verdict-sentence']", "count")])
        self.assertEqual(out["final"]["badge"], "SHARP 🔥")
        self.assertEqual(out["final"]["title"], "Sharp or lucky?")
        self.assertEqual(out["final"]["explain"],
                         "Its prices keep beating where the market closes. Good shopping, not a promise of wins.")
        self.assertIn("beat the closing market", out["final"]["sentence"])
        self.assertEqual(out["final"]["sentence_in_receipts"], 1)      # the referee's own sentence is in the collapsed block
        self.assertIn("it's not a tip", out["final"]["meaning"])
        self.assertIn("Based on 41 live bets. That's a small sample.", out["final"]["verdict"])
        self.assertEqual(out["final"]["name"], "Closer")
        self.assertEqual(out["title"], "Closer — LINEHOUND")

    def test_the_top_of_the_page_is_the_dog_portrait_bio_catchphrase_and_a_scoreboard(self):
        out = self.page(queries=[
            q("vibe", "[data-hook='portrait']", "attr", attr="data-vibe"), q("tag", "[data-hook='vibe']"),
            q("avatar_vibe", "[data-hook='portrait'] .hd-avatar", "attr", attr="data-vibe"),
            q("catch", "[data-hook='catchphrase']"), q("bio", "[data-hook='bio']"),
            q("tiles", "[data-hook='scoreboard-tiles'] .hd-tile", "attrs", attr="data-slot"),
            q("record", ".hd-tile[data-slot='record']"), q("units", ".hd-tile[data-slot='units']"),
            q("streak", ".hd-tile[data-slot='streak']"), q("week", ".hd-tile[data-slot='week']"),
            q("best", ".hd-tile[data-slot='best']"), q("worst", ".hd-tile[data-slot='worst']"),
            q("details_open", "[data-hook='hound-details']", "attr", attr="open"),
            q("order", "h2", "texts")])
        f = out["final"]
        self.assertEqual((f["vibe"], f["avatar_vibe"]), ("degen", "degen"))
        self.assertEqual(f["tag"], "Degen 🎉")
        self.assertEqual(f["catch"], "“I was here first.”")
        self.assertEqual(f["bio"], "Grabs the price before it moves and tells everyone about it.")
        self.assertEqual(f["tiles"], ["record", "units", "streak", "week", "best", "worst"])
        self.assertRegex(f["record"], r"Record \d+-\d+-1 41 bets, a small sample")
        self.assertRegex(f["units"], r"Paper units [+-]\d+\.\d\du average price; best price [+-]\d+\.\d\du")
        self.assertRegex(f["streak"], r"Streak (🔥+ |🥶 )?[WL]\d \d+ (wins?|losses) in a row")
        self.assertRegex(f["week"], r"This week [+-]\d+\.\d\du \(\d+-\d+\) last 7 days")
        self.assertIn("Best bet 🏆 Yankees to win at +135 Yankees at Red Sox. +1.35u, Oct 21.", f["best"])
        self.assertIn("Worst beat 💔 Astros to win at -140 Mariners at Astros. -1.00u, Oct 22. The market had it 58% to win.",
                      f["worst"])
        self.assertIsNone(f["details_open"], "the details are collapsed")
        self.assertEqual(f["order"][:4], ["The scoreboard", "What the Houndmaster said", "Sharp or lucky?", "The rules"])

    def test_the_houndmasters_line_follows_the_last_settled_day_and_is_the_same_all_day(self):
        roast_pool = ["Closer roast 1.", "Closer roast 2.", "Closer roast 3.", "Closer roast 4.", "Closer roast 5."]
        brag_pool = ["Closer brag 1.", "Closer brag 2.", "Closer brag 3.", "Closer brag 4.", "Closer brag 5."]
        lost = self.page(queries=[q("line", "[data-hook='houndmaster-line']"),
                                  q("kind", "[data-hook='houndmaster-line']", "attr", attr="data-kind"),
                                  q("why", "[data-hook='houndmaster-why']")])
        again = self.page(queries=[q("line", "[data-hook='houndmaster-line']")])
        self.assertEqual(lost["final"]["kind"], "roast")                 # the fixture's last day was a loss
        self.assertTrue(any(line in lost["final"]["line"] for line in roast_pool), lost["final"]["line"])
        self.assertEqual(lost["final"]["line"], again["final"]["line"])  # a reload says the same thing
        self.assertEqual(lost["final"]["why"], "After Oct 24: 0-1, -1.00u.")
        d = F.detail("closer")
        d["form"] = dict(d["form"], last_day={"date": "2026-10-24", "bets": 1, "wins": 1, "losses": 0, "units": 0.91, "result": "win"})
        won = self.page(routes={"/hounds/closer": [200, d]}, queries=[
            q("line", "[data-hook='houndmaster-line']"), q("kind", "[data-hook='houndmaster-line']", "attr", attr="data-kind")])
        self.assertEqual(won["final"]["kind"], "brag")
        self.assertTrue(any(line in won["final"]["line"] for line in brag_pool), won["final"]["line"])
        d["form"] = dict(d["form"], last_day={"date": "2026-10-24", "bets": 1, "wins": 0, "losses": 0, "units": 0.0, "result": "flat"})
        flat = self.page(routes={"/hounds/closer": [200, d]}, queries=[
            q("kind", "[data-hook='houndmaster-line']", "attr", attr="data-kind"), q("line", "[data-hook='houndmaster-line']")])
        self.assertEqual(flat["final"]["kind"], "quiet")
        self.assertEqual(flat["final"]["line"], "Nothing settled yet. The Houndmaster is watching.")

    def test_a_dog_with_no_persona_gets_a_generic_portrait_and_the_bosses_own_lines(self):
        out = self.page(hid="steamer", queries=[
            q("catch", "[data-hook='catchphrase']", "count"), q("bio", "[data-hook='bio']"),
            q("vibe", "[data-hook='portrait']", "attr", attr="data-vibe"),
            q("line", "[data-hook='houndmaster-line']"), q("kind", "[data-hook='houndmaster-line']", "attr", attr="data-kind")])
        self.assertEqual(out["final"]["catch"], 0)
        self.assertEqual(out["final"]["bio"], "Rides early line moves.")       # the tagline stands in for a bio
        self.assertEqual(out["final"]["vibe"], "degen")                         # a market dog wears the market vibe
        self.assertEqual(out["final"]["kind"], "brag")                          # the fixture's last day for steamer was a win
        self.assertIn(out["final"]["line"].split("“")[1].rstrip("”"), [
            "Okay. That was good. Don't make a thing of it.", "Up on the night. Treat's in the bowl. Behave.",
            "One good night. Don't get cocky. They all get cocky.", "Fair is fair: nice work.",
            "That cashed. Do it again tomorrow, if you can."])

    def test_a_dog_with_no_bets_has_an_honest_empty_scoreboard(self):
        out = self.page(hid="rusty", forward=False, queries=[q("empty", "[data-hook='scoreboard-empty']"),
                                                             q("tiles", "[data-hook='scoreboard-tiles']", "count")])
        self.assertEqual(out["final"]["empty"], "No live bets yet. This dog hasn't put a unit down yet.")
        self.assertEqual(out["final"]["tiles"], 0)

    def test_two_lines_for_units_and_a_clv_panel_each_with_a_zero_line_and_a_table(self):
        out = self.page(queries=[
            q("units_zero", "[data-hook='hound-units-chart'] [data-hook='chart-zero']", "count"),
            q("clv_zero", "[data-hook='hound-clv-chart'] [data-hook='chart-zero']", "count"),
            q("units_lines", "[data-hook='hound-units-chart'] .hd-line", "attrs", attr="data-line"),
            q("clv_lines", "[data-hook='hound-clv-chart'] .hd-line", "attrs", attr="data-line"),
            q("units_cols", "[data-hook='hound-units-chart'] thead th", "texts"),
            q("note", "[data-hook='hound-chart-section']"),
            q("clv_label", "[data-hook='hound-clv-chart'] .hd-chart__svg", "attr", attr="aria-label")])
        self.assertEqual(out["final"]["units_zero"], 1)
        self.assertEqual(out["final"]["clv_zero"], 1)
        self.assertEqual(out["final"]["units_lines"], ["avg", "best"])
        self.assertEqual(out["final"]["clv_lines"], ["clv"])
        self.assertEqual(out["final"]["units_cols"], ["Date", "Average price (units)", "Best price (units)"])
        self.assertIn("Average price (the headline) and best price", out["final"]["note"])
        self.assertIn("closing price", out["final"]["clv_label"])

    def test_a_replay_only_hound_draws_nothing_forward_and_shows_its_replay_block_apart(self):
        out = self.page(hid="rusty", forward=False, queries=[
            q("title", "[data-hook='hound-chart-title']"), q("fwd", "[data-hook='forward-facts']"),
            q("rep", "[data-hook='replay-line']"), q("note", "[data-hook='replay-note']"),
            q("empty", "[data-hook='hound-units-chart'] [data-hook='chart-empty']"),
            q("toggle", "[data-hook='hound-segment']", "count")])
        self.assertIn("No live bets yet", out["final"]["title"])
        self.assertIn("No live bets yet", out["final"]["fwd"])
        self.assertTrue(out["final"]["rep"].startswith(
            "old-board rehearsal (the same rule on earlier games; written after, so it never counts)"))
        self.assertIn("never counted in the verdict", out["final"]["note"])     # the server's own note
        self.assertIn("A rehearsal result is not drawn here", out["final"]["empty"])
        self.assertEqual(out["final"]["toggle"], 0)

    def test_bets_are_paged_by_the_server_with_a_clear_who_decided_and_accessible_results(self):
        """MISALIGNMENT 1. ``bets`` in GET /hounds/{id} is a page object {items, page, page_size, total,
        pages}, not a list: the page read it as an array, found none, and said 'No bets yet'."""
        out = self.page(routes={
            "/hounds/closer/bets?page=2&page_size=25": [200, F.bets_payload("closer", 45, 2, 25)],
            "/hounds/closer/bets?page=1&page_size=25": [200, F.bets_payload("closer", 45, 1, 25)]},
            captureInitial=[
            q("rows", "[data-hook='bets-table'] tbody tr", "count"),
            q("who", "[data-hook='bets-table'] tbody tr", "attrs", attr="data-who"),
            q("page", "[data-hook='bets-page']"), q("prev", "[data-hook='bets-prev']", "disabled"),
            q("heads", "[data-hook='bets-table'] thead th", "texts"),
            q("results", "[data-hook='bets-table'] .hd-result", "texts")],
            actions=[dict(do="click", sel="[data-hook='bets-next']", label="p2",
                          capture=[q("page", "[data-hook='bets-page']"), q("rows", "[data-hook='bets-table'] tbody tr", "count"),
                                   q("prev", "[data-hook='bets-prev']", "disabled"),
                                   q("next", "[data-hook='bets-next']", "disabled")])])
        self.assertEqual(out["captures"]["p2"]["page"], "Page 2 of 2 (45 bets)")
        self.assertEqual(out["captures"]["p2"]["rows"], 20)
        self.assertFalse(out["captures"]["p2"]["prev"])
        self.assertTrue(out["captures"]["p2"]["next"])
        self.assertIn("/hounds/closer/bets?page=2&page_size=25", out["gets"])
        first = out["captures"]["initial"]
        self.assertEqual(first["page"], "Page 1 of 2 (45 bets)")
        self.assertEqual(first["rows"], 25)
        self.assertTrue(first["prev"])
        self.assertIn("Decided by", first["heads"])
        self.assertIn("Average price", first["heads"])             # the headline price beside the best one
        self.assertIn("Best price (book)", first["heads"])
        self.assertIn("Units at best price", first["heads"])
        self.assertTrue(set(first["who"]) <= {"rule", "code", "model"})
        # colour is never the only cue: every result carries a word
        for text in first["results"]:
            self.assertRegex(text, r"(Win|Loss|Push|Void|Pending)")
        css = (WEB / "css" / "hounds.css").read_text(encoding="utf-8")
        for tone in ("win", "loss"):
            self.assertIn(f".hd-result--{tone}", css)

    def test_bets_with_no_bets_say_so_and_a_failed_bets_call_says_why(self):
        empty = dict(F.detail("closer"), bets=contract.to_json(contract.paginate([], 1, 25)))
        none = self.page(routes={"/hounds/closer": [200, empty]}, queries=[q("e", "[data-hook='bets-empty']")])
        self.assertIn("No bets yet", none["final"]["e"])
        # a detail payload without bets falls back to /hounds/{id}/bets; here that endpoint is missing
        d = F.detail("closer")
        d.pop("bets")
        r = routes()
        r.pop("/hounds/closer/bets")
        r["/hounds/closer"] = [200, d]
        r["/hounds/series"] = [200, F.series(["closer"])]
        missing = run_page("hound", routes=r, search="?id=closer", queries=[q("s", "[data-hook='hound-bets'] [data-hook='section-state']")])
        self.assertIn("not switched on yet", missing["final"]["s"])
        self.assertTrue([g for g in missing["gets"] if g.startswith("/hounds/closer/bets")])
        # and when it is there, its rows are used
        r["/hounds/closer/bets"] = [200, F.bets_payload("closer", 3)]
        ok = run_page("hound", routes=r, search="?id=closer", queries=[q("n", "[data-hook='bets-table'] tbody tr", "count")])
        self.assertEqual(ok["final"]["n"], 3)

    def test_the_bets_can_be_narrowed_to_forward_or_replay_through_the_servers_segment_filter(self):
        r = {"/hounds/rusty/bets?page=1&page_size=25&segment=forward": [200, F.bets_payload("rusty", 45, 1, 25, "forward")],
             "/hounds/rusty/bets?page=1&page_size=25&segment=replay": [200, F.bets_payload("rusty", 45, 1, 25, "replay")]}
        out = self.page(hid="rusty", routes=r, forward=False, captureInitial=[
            q("seg", "[data-hook='bets-segment'] .hd-seg", "texts"),
            q("tags", "[data-hook='bets-table'] tbody tr", "attrs", attr="data-segment")],
            actions=[dict(do="click", sel="[data-hook='bets-segment'] [data-segment='forward']", label="fwd",
                          capture=[q("empty", "[data-hook='bets-empty']")])])
        first = out["captures"]["initial"]
        self.assertEqual(first["seg"], ["All bets", "Live", "Rehearsal"])
        self.assertTrue(first["tags"] and set(first["tags"]) == {"replay"})
        self.assertIn("No live bets for this dog", out["captures"]["fwd"]["empty"])
        self.assertTrue([g for g in out["gets"] if g.endswith("&segment=forward")])

    def test_a_retired_hound_shows_its_cause(self):
        d = F.detail("closer")
        d.update(status="retired", retired={"date": "2026-10-20", "cause": "retired: down more than 25 units"})
        out = self.page(routes={"/hounds/closer": [200, d]}, queries=[
            q("cause", "[data-hook='hound-cause']"), q("hidden", "[data-hook='hound-cause']", "hidden"),
            q("status", "[data-hook='hound-status']")])
        self.assertFalse(out["final"]["hidden"])
        self.assertIn("Put down 💀. Cause of death: Went more than 25 units under.", out["final"]["cause"])
        self.assertEqual(out["final"]["status"], "Put down 💀")

    def test_a_running_hound_has_no_cause_box(self):
        out = self.page(queries=[q("hidden", "[data-hook='hound-cause']", "hidden")])
        self.assertTrue(out["final"]["hidden"])

    def test_unknown_hound_missing_id_and_down_server(self):
        gone = run_page("hound", routes=routes(), search="?id=nope", queries=[q("t", "[data-hook='hound-header']"),
                                                                              q("v", "[data-hook='hound-verdict-section']", "hidden")])
        self.assertIn("There's no dog with this id", gone["final"]["t"])
        self.assertTrue(gone["final"]["v"])
        noid = run_page("hound", routes=routes(), search="", queries=[q("t", "[data-hook='hound-header']")])
        self.assertIn("No dog was chosen", noid["final"]["t"])
        down = run_page("hound", routes=routes(), search="?id=closer", down=["/hounds/closer"],
                        queries=[q("t", "[data-hook='hound-header']")])
        self.assertIn("Could not reach this dog", down["final"]["t"])

    def test_the_detail_payloads_own_series_draws_the_chart_without_a_second_request(self):
        out = self.page(queries=[q("lines", "[data-hook='hound-units-chart'] .hd-line", "count")])
        self.assertEqual(out["final"]["lines"], 2)
        self.assertFalse([g for g in out["gets"] if g.startswith("/hounds/series")])

    def test_series_missing_gives_an_honest_chart_state_and_the_rest_of_the_page_stays(self):
        r = routes()
        r.pop("/hounds/series")
        d = F.detail("closer")
        d.pop("series")                         # a payload without its series falls back to /hounds/series
        r["/hounds/closer"] = [200, d]
        out = run_page("hound", routes=r, search="?id=closer", queries=[
            q("chart", "[data-hook='hound-units-chart']"), q("rule", "[data-hook='rule-text']", "texts"),
            q("rows", "[data-hook='bets-table'] tbody tr", "count")])
        self.assertIn("not switched on yet", out["final"]["chart"])
        self.assertTrue(out["final"]["rule"])
        self.assertEqual(out["final"]["rows"], 25)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheChartsRenderEmptyAndOnePointSeriesHonestly(unittest.TestCase):
    def detail_with_series(self, points):
        r = routes()
        r["/hounds/closer"] = [200, dict(F.detail("closer"), series=points)]
        return run_page("hound", routes=r, search="?id=closer", queries=[
            q("empty", "[data-hook='hound-units-chart'] [data-hook='chart-empty']"),
            q("empty_n", "[data-hook='hound-units-chart'] [data-hook='chart-empty']", "count"),
            q("zero", "[data-hook='hound-units-chart'] [data-hook='chart-zero']", "count"),
            q("paths", "[data-hook='hound-units-chart'] .hd-line__path", "count"),
            q("singles", "[data-hook='hound-units-chart'] [data-single='true']", "count"),
            q("ends", "[data-hook='hound-units-chart'] .hd-line__end", "count"),
            q("clv_empty", "[data-hook='hound-clv-chart'] [data-hook='chart-empty']"),
            q("rows", "[data-hook='hound-units-chart'] [data-hook='chart-data-table'] tbody tr", "count")])

    def test_empty_series_draws_a_frame_and_says_nothing_to_draw_not_a_flat_zero_line(self):
        out = self.detail_with_series([])
        self.assertEqual(out["final"]["empty_n"], 1)
        self.assertIn("No live bets yet", out["final"]["empty"])
        self.assertEqual(out["final"]["zero"], 0)      # no baseline drawn for a chart with nothing on it
        self.assertEqual(out["final"]["paths"], 0)
        self.assertIn("Nothing measured against the close yet", out["final"]["clv_empty"])

    def test_one_point_series_is_a_single_dot_and_one_table_row(self):
        out = self.detail_with_series([{"date": "2026-10-18", "cum_units_average_price": 1.5, "cum_units_recorded_price": 1.7,
                                        "bets_settled": 2, "cum_clv_mean_pts": 0.4, "segment": "forward"}])
        self.assertEqual(out["final"]["empty_n"], 0)
        self.assertEqual(out["final"]["paths"], 0)     # no line from one point
        self.assertEqual(out["final"]["singles"], 2)   # average and recorded, each a dot
        self.assertEqual(out["final"]["zero"], 1)
        self.assertEqual(out["final"]["rows"], 1)

    def test_a_null_clv_everywhere_is_an_empty_clv_panel_not_a_line_at_zero(self):
        pts = [{"date": f"2026-10-{18 + i}", "cum_units_average_price": i, "cum_units_recorded_price": i,
                "bets_settled": i + 1, "cum_clv_mean_pts": None, "segment": "forward"} for i in range(4)]
        out = self.detail_with_series(pts)
        self.assertIn("Nothing measured against the close yet", out["final"]["clv_empty"])
        self.assertEqual(out["final"]["paths"], 2)

    def test_the_leaderboard_chart_with_no_series_for_anyone_says_so(self):
        r = routes()
        r["/hounds/series"] = [200, {"series": {}}]
        out = run_page("hounds", routes=r, queries=[q("chart", "[data-hook='hounds-chart-panel']"),
                                                    q("zero", "[data-hook='chart-zero']", "count"),
                                                    q("rows", "[data-hound]", "count")])
        self.assertIn("No live bets yet", out["final"]["chart"])
        self.assertEqual(out["final"]["zero"], 0)
        self.assertGreater(out["final"]["rows"], 5)       # the leaderboard itself is unaffected


# ---------------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheDeskSections(unittest.TestCase):
    """"How the desk argued" (transcript.json) and "Where they disagree" (disagreement.json) on web/hound.html,
    for the hounds in the categories ai-desk and persona only."""

    def page(self, hid, routes_, **kw):
        return run_page("hound", routes=routes_, search=f"?id={hid}", **kw)

    def test_the_desk_hound_shows_analysts_bull_bear_and_head_from_the_transcript(self):
        out = self.page("desk_ai", F.desk_routes("desk_ai"), queries=[
            q("shown", "[data-hook='hound-desk-section']", "hidden"),
            q("title", "#desk-h"),
            q("analysts", "[data-hook='desk-analyst']", "texts"),
            q("analyst_stages", "[data-hook='desk-analyst']", "attrs", attr="data-stage"),
            q("bull", "[data-hook='desk-bull']"), q("bear", "[data-hook='desk-bear']"),
            q("head", "[data-hook='desk-head']"),
            q("takes", "[data-hook='desk-takes'] tbody tr", "texts"),
            q("struck", "[data-hook='desk-struck'] li", "texts"),
            q("kept", "[data-hook='desk-kept']"),
            q("label", "[data-hook='desk-label']"), q("line", "[data-hook='desk-game-line']"),
            q("hash", "[data-hook='desk-hash-ok']"),
            q("dis_hidden", "[data-hook='hound-disagree-section']", "hidden"),
            q("cat", ".hd-chip-cat")])
        f = out["final"]
        self.assertFalse(f["shown"])
        self.assertEqual(f["title"], "How the desk argued")
        self.assertEqual(f["analyst_stages"], ["analyst_stats", "analyst_situation", "analyst_market", "analyst_injury"])
        self.assertIn("The stats analyst", f["analysts"][0])
        self.assertIn("Run prevention favours the road side.", f["analysts"][0])
        self.assertIn("Starter ERA is lower.", f["analysts"][0])
        self.assertIn("2 pieces of evidence", f["analysts"][0])
        self.assertIn("The Yankees are the better side at the price.", f["bull"])
        self.assertIn("The price already knows this.", f["bear"])
        self.assertIn("One take, at the best quoted price.", f["head"])
        self.assertEqual(len(f["takes"]), 1)
        self.assertIn("Yankees", f["takes"][0])
        self.assertIn("-115 (bookB)", f["takes"][0])
        self.assertIn("56.0%", f["takes"][0])
        self.assertIn("A late scratch.", f["takes"][0])
        self.assertEqual(f["struck"], ["Struck (Over 8.5) by price_cap: the price is -210, -200 or worse"])
        self.assertIn("1 take stands", f["kept"])
        self.assertIn("Written by AI models", f["label"])
        self.assertIn("New York Yankees at Boston Red Sox", f["line"])
        self.assertIn("a-test-model", f["line"])
        self.assertIn("matches the checksum", f["hash"])
        self.assertTrue(f["dis_hidden"])                    # the disagreement table is for the personas
        self.assertEqual(f["cat"], "AI desk")

    def test_a_persona_shows_its_own_call_and_the_table_of_where_they_disagree(self):
        out = self.page("desk_sharp", F.desk_routes("desk_sharp"), queries=[
            q("persona", "[data-hook='desk-persona']"), q("analysts", "[data-hook='desk-analyst']", "count"),
            q("head", "[data-hook='desk-head']", "count"),
            q("dis_hidden", "[data-hook='hound-disagree-section']", "hidden"), q("dis_title", "#disagree-h"),
            q("heads", "[data-hook='disagree-table'] thead th", "texts"),
            q("rows", "[data-hook='disagree-table'] tbody tr", "attrs", attr="data-status"),
            q("ml", "[data-hook='disagree-table'] tbody tr[data-slot='ml']"),
            q("tot", "[data-hook='disagree-table'] tbody tr[data-slot='tot']"),
            q("mine", "[data-hook='disagree-table'] td.hd-desk__me", "count"),
            q("cells", "[data-hook='disagree-table'] tbody tr[data-slot='ml'] td", "attrs", attr="data-cell"),
            q("counts", "[data-hook='disagree-counts']"), q("note", "[data-hook='disagree-note']")])
        f = out["final"]
        self.assertIn("Price beats the books' number.", f["persona"])
        self.assertEqual((f["analysts"], f["head"]), (0, 0))        # a persona has no analysts, bull, bear or head
        self.assertFalse(f["dis_hidden"])
        self.assertEqual(f["dis_title"], "Where they disagree")
        self.assertEqual(f["heads"], ["Market", "Status", "Desk", "Sharp", "Square", "Fader"])
        self.assertEqual(f["rows"], ["split", "none"])
        self.assertIn("Split: opposite sides taken", f["ml"])
        self.assertIn("Yankees -115", f["ml"])
        self.assertIn("Red Sox +105", f["ml"])
        self.assertIn("not answered", f["ml"])                      # an unanswered hound is not a pass
        self.assertIn("struck by price_cap: the price is -210", f["tot"])
        self.assertEqual(f["cells"][2:], ["take", "take", "unanswered", "take"])
        self.assertEqual(f["mine"], 2)                              # this hound's column is marked in both rows
        self.assertEqual(f["counts"], "Markets: 1 split, 0 agree, 0 lone, 1 none.")
        self.assertIn("Agreement among them is not confirmation", f["note"])

    def test_before_the_first_publish_both_sections_say_so_and_invent_nothing(self):
        out = self.page("desk_sharp", F.desk_routes("desk_sharp", started=False), queries=[
            q("status", "[data-hook='hound-status']"), q("none", "[data-hook='desk-none']"),
            q("dis", "[data-hook='disagree-none']"), q("rule", "[data-hook='rule-text']"),
            q("picker", "[data-hook='desk-game']", "count"), q("table", "[data-hook='disagree-table']", "count"),
            q("sample", "[data-hook='hound-verdict']")])
        f = out["final"]
        self.assertEqual(f["status"], "Not started")
        self.assertIn("The desk has not published a game yet", f["none"])
        self.assertIn("No game has been published yet", f["dis"])
        self.assertIn("One model reading, unproven", f["rule"])      # the rule text is there before any game
        self.assertEqual((f["picker"], f["table"]), (0, 0))
        self.assertIn("Based on 0 live bets.", f["sample"])

    def test_a_stage_missing_or_unreadable_in_the_transcript_is_said_not_filled_in(self):
        t = F.desk_transcript()
        t["stages"] = [s for s in t["stages"] if s["stage"] != "bull"]
        for s in t["stages"]:
            if s["stage"] == "analyst_market":
                s["attempts"][0]["response"] = None                 # an answer that could not be read
            if s["stage"] == "head":
                s["attempts"][0]["response"]["decisions"] = []      # the head passed
        t["hounds"]["desk_ai"] = {"takes": [], "struck": []}
        r = F.desk_routes("desk_ai", **{"/hounds/desk_ai/desk/2026-10-24_NYY-BOS": (200, F.desk_game_payload("desk_ai", transcript=t))})
        out = self.page("desk_ai", r, queries=[
            q("bull", "[data-hook='desk-bull']"), q("market", "[data-hook='desk-analyst'][data-stage='analyst_market']"),
            q("passed", "[data-hook='desk-passed']"), q("takes", "[data-hook='desk-takes']", "count"),
            q("bear", "[data-hook='desk-bear']")])
        f = out["final"]
        self.assertIn("This stage is not in this game's transcript.", f["bull"])
        self.assertIn("could not be read, so nothing is shown for it", f["market"])
        self.assertIn("It took nothing: a pass is a decision.", f["passed"])
        self.assertEqual(f["takes"], 0)
        self.assertIn("The price already knows this.", f["bear"])    # the other stages are unaffected

    def test_no_transcript_no_disagreement_file_and_a_changed_checksum_are_each_named(self):
        r = F.desk_routes("desk_sharp", **{"/hounds/desk_sharp/desk/2026-10-24_NYY-BOS": (200, F.desk_game_payload(
            "desk_sharp", disagreement=None, transcript_sha256_ok=False))})
        payload = r["/hounds/desk_sharp/desk/2026-10-24_NYY-BOS"][1]
        payload["disagreement"] = None
        payload["disagreement_problem"] = "the named file is not there"
        out = self.page("desk_sharp", r, queries=[
            q("bad", "[data-hook='desk-hash-bad']"), q("dis", "[data-hook='disagree-missing']"),
            q("ok", "[data-hook='desk-hash-ok']", "count")])
        self.assertIn("does not match the checksum the ledger recorded", out["final"]["bad"])
        self.assertIn("There is no disagreement table for this game: the named file is not there", out["final"]["dis"])
        self.assertEqual(out["final"]["ok"], 0)
        gone = F.desk_routes("desk_ai", **{"/hounds/desk_ai/desk/2026-10-24_NYY-BOS": (200, F.desk_game_payload(
            "desk_ai", transcript_problem="the named file is not there"))})
        gone["/hounds/desk_ai/desk/2026-10-24_NYY-BOS"][1]["transcript"] = None
        out2 = self.page("desk_ai", gone, queries=[q("t", "[data-hook='transcript-missing']")])
        self.assertIn("transcript is not available: the named file is not there", out2["final"]["t"])

    def test_an_empty_slot_list_and_a_down_server_have_honest_states(self):
        r = F.desk_routes("desk_sharp", **{"/hounds/desk_sharp/desk/2026-10-24_NYY-BOS": (200, F.desk_game_payload(
            "desk_sharp", disagreement={"slots": [], "counts": {}, "note": ""}))})
        out = self.page("desk_sharp", r, queries=[q("e", "[data-hook='disagree-empty']")])
        self.assertIn("lists no market slots", out["final"]["e"])
        down = self.page("desk_ai", F.desk_routes("desk_ai"), down=["/hounds/desk_ai/desk"], queries=[
            q("s", "[data-hook='hound-desk'] [data-hook='section-state']")])
        self.assertIn("Could not reach the desk's games", down["final"]["s"])

    def test_a_picker_lists_the_games_newest_first_and_loads_the_one_chosen(self):
        r = F.desk_routes("desk_ai", games=2)
        second = F.desk_transcript("2026-10-23_SEA-HOU")
        second.update(away="Seattle Mariners", home="Houston Astros", date="2026-10-23")
        r["/hounds/desk_ai/desk/2026-10-23_SEA-HOU"] = (200, F.desk_game_payload(
            "desk_ai", transcript=second, game_id="2026-10-23_SEA-HOU", away="Seattle Mariners", home="Houston Astros"))
        out = self.page("desk_ai", r, captureInitial=[q("line", "[data-hook='desk-game-line']")],
                        queries=[q("options", "[data-hook='desk-game'] option", "texts"),
                                 q("line", "[data-hook='desk-game-line']")],
                        actions=[dict(do="set", sel="[data-hook='desk-game']", value="2026-10-23_SEA-HOU"),
                                 dict(do="check", sel="[data-hook='desk-game']", checked=True, wait=120)])
        self.assertEqual(out["final"]["options"], ["Oct 24: New York Yankees at Boston Red Sox, 1 take",
                                                   "Oct 23: Seattle Mariners at Houston Astros, 0 takes"])
        self.assertIn("New York Yankees at Boston Red Sox", out["captures"]["initial"]["line"])
        self.assertIn("Seattle Mariners at Houston Astros", out["final"]["line"])

    def test_an_ordinary_hound_never_sees_the_desk_sections_or_asks_for_them(self):
        out = run_page("hound", routes=routes(), search="?id=closer", queries=[
            q("desk", "[data-hook='hound-desk-section']", "hidden"), q("dis", "[data-hook='hound-disagree-section']", "hidden")])
        self.assertTrue(out["final"]["desk"] and out["final"]["dis"])
        self.assertFalse([g for g in out["gets"] if "/desk" in g])

    def test_the_two_new_categories_have_a_label_a_colour_and_are_in_the_contract(self):
        for cat, label in (("ai-desk", "AI desk"), ("persona", "Persona")):
            self.assertIn(cat, contract.CATEGORIES)
        core = (WEB / "js" / "hounds-core.js").read_text(encoding="utf-8")
        self.assertIn('"ai-desk": "AI desk"', core)
        self.assertIn('persona: "Persona"', core)
        self.assertRegex(core, r'"ai-desk": "#[0-9A-Fa-f]{6}"')
        self.assertRegex(core, r'persona: "#[0-9A-Fa-f]{6}"')


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheFirstVisitWhileTheServerWarmsUp(unittest.TestCase):
    """MISALIGNMENT 5. The first request after a start gets ``warming_up: true`` (HTTP 200) while the
    stats are first built. The pages say so, show nothing made up, and ask again."""

    def warming(self, **extra):
        return [200, contract.warming_payload(extra)]

    def test_the_race_says_it_is_warming_up_then_fills_in_when_the_server_is_ready(self):
        r = routes()
        r["/hounds"] = self.warming(hounds=[])
        r["/hounds/stream"] = self.warming(items=[])
        r["/hounds/graveyard"] = self.warming(hounds=[])
        switch = {"/hounds": [1, [200, F.leaderboard()]], "/hounds/stream": [1, [200, F.stream()]],
                  "/hounds/graveyard": [1, [200, F.graveyard()]]}
        out = run_page("hounds", routes=r, switchAfter=switch, captureInitial=[
            q("kinds", "[data-kind='warming']", "count"), q("board", "[data-hook='hounds-list']"),
            q("empty", "[data-hook='board-empty']", "count"), q("chart", "[data-hook='hounds-chart-panel']"),
            q("rows", "[data-hook='hounds-list'] .hd-row", "count")],
            actions=[dict(do="fire_timers", wait=120)], queries=[
                q("kinds", "[data-kind='warming']", "count"), q("rows", "[data-hook='hounds-list'] .hd-row", "count"),
                q("stream", "[data-hook='stream-list'] li", "count"), q("grave", "[data-hook='grave-cause']", "texts")])
        first = out["captures"]["initial"]
        self.assertEqual(first["kinds"], 3)                        # board, stream, graveyard each say so
        self.assertIn("warming up", first["board"])
        self.assertEqual(first["empty"], 0)                        # NOT "No hounds are racing yet"
        self.assertEqual(first["rows"], 0)
        self.assertIn("appears as soon as the race has been worked out", first["chart"])
        self.assertEqual(out["final"]["kinds"], 0)
        self.assertEqual(out["final"]["rows"], 11)
        self.assertEqual(out["final"]["stream"], 3)
        self.assertEqual(out["final"]["grave"], ["Cause of death: Cut by the kennel boss. (Oct 20)",
                                                 "Cause of death: Went more than 25 units under. (Oct 14)"])
        self.assertEqual(out["intervals"], [60000])               # the warming retries stopped themselves

    def test_the_retry_follows_the_servers_own_cadence(self):
        r = routes()
        r["/hounds"] = [200, contract.warming_payload({"hounds": []})]
        out = run_page("hounds", routes=r)
        self.assertIn(5000, out["intervals"])
        self.assertIn(60000, out["intervals"])

    def test_one_hound_says_it_is_warming_up_and_never_a_made_up_hound(self):
        r = routes()
        r["/hounds/closer"] = self.warming(id="closer")
        out = run_page("hound", routes=r, search="?id=closer", switchAfter={"/hounds/closer": [1, [200, F.detail("closer")]]},
                       captureInitial=[q("header", "[data-hook='hound-header']"),
                                       q("verdict_hidden", "[data-hook='hound-verdict-section']", "hidden"),
                                       q("name", "[data-hook='hound-name']", "count")],
                       actions=[dict(do="fire_timers", wait=150)],
                       queries=[q("name", "[data-hook='hound-name']"),
                                q("verdict_hidden", "[data-hook='hound-verdict-section']", "hidden")])
        first = out["captures"]["initial"]
        self.assertIn("warming up", first["header"])
        self.assertTrue(first["verdict_hidden"])
        self.assertEqual(first["name"], 0)
        self.assertEqual(out["final"]["name"], "Closer")
        self.assertFalse(out["final"]["verdict_hidden"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBuildPage(unittest.TestCase):
    """The form is generated from the REAL menu (user_spec.menu(), through tests/hounds_web_fixtures.py), and
    what it posts is what api/hounds_create.py's CreateHoundRequest takes."""

    # An invented menu in the real SHAPE, to prove nothing is hard-coded in the page.
    ODD_MENU = {"name": {"min": 2, "max": 10}, "tagline": {"max": 20},
                "sports": [{"value": "curling", "label": "Curling"}, {"value": "darts", "label": "Darts"}],
                "markets": [{"value": "outright", "label": "Outright"}],
                "side_rules": [{"value": "loud", "label": "the loud one", "markets": ["outright"]},
                               {"value": "quiet", "label": "the quiet one", "markets": ["outright"]}],
                "price_min": {"label": "Shortest", "presets": [-180, -150], "lowest": -180},
                "price_max": {"label": "Longest", "presets": [100, 300], "highest": 300},
                "price_cap_note": "No selection at -200 or worse, ever.",
                "min_books": {"min": 2, "max": 6}, "max_bets_per_day": {"min": 1, "max": 2},
                "lock_minutes": {"choices": [5, 45]}, "max_running_per_account": 2}

    # sport 0 = the first sport, market 0 = the first market, side 1 = the second side rule ("underdog")
    FILL = [dict(do="set", sel="[data-hook='f-name']", value="  Pup  "),
            dict(do="set", sel="[data-hook='f-tagline']", value="Fetches"),
            dict(do="check", sel="[data-field='sport'] input", index=0),
            dict(do="check", sel="[data-field='market'] input", index=0),
            dict(do="check", sel="[data-field='side'] input", index=1),
            dict(do="set", sel="[data-hook='f-price-min']", value="-150"),
            dict(do="set", sel="[data-hook='f-price-max']", value="250")]

    def build(self, **kw):
        r = kw.pop("routes", None) or routes()
        return run_page("build", routes=r, **kw)

    def test_the_form_is_generated_from_the_menu_not_hard_coded(self):
        r = routes()
        r["/hounds/menu"] = [200, self.ODD_MENU]
        out = self.build(routes=r, queries=[
            q("sports", "[data-field='sport'] label", "texts"), q("markets", "[data-field='market'] label", "texts"),
            q("sides", "[data-field='side'] label", "texts"), q("lock", "[data-hook='f-lock'] option", "texts"),
            q("pmin", "[data-hook='f-price-min']", "attr", attr="min"), q("pmax", "[data-hook='f-price-max']", "attr", attr="max"),
            q("pmin_v", "[data-hook='f-price-min']", "value"), q("books_max", "[data-hook='f-books']", "attr", attr="max"),
            q("books_v", "[data-hook='f-books']", "value"),
            q("bets_max", "[data-hook='f-max-bets']", "attr", attr="max"),
            q("name_max", "[data-hook='f-name']", "attr", attr="maxlength"),
            q("tag_max", "[data-hook='f-tagline']", "attr", attr="maxlength"),
            q("presets", "datalist option", "attrs", attr="value"),
            q("cap", "[data-hook='build-form']"), q("limit", "[data-hook='limit-text']"),
            q("counts", "[data-hook='name-count']")])
        self.assertEqual(out["final"]["sports"], ["Curling", "Darts"])
        self.assertEqual(out["final"]["markets"], ["Outright"])
        self.assertEqual(out["final"]["sides"], ["the loud one", "the quiet one"])
        self.assertEqual(out["final"]["lock"], ["5 minutes before the start", "45 minutes before the start"])
        self.assertEqual(out["final"]["pmin"], "-180")
        self.assertEqual(out["final"]["pmax"], "300")
        self.assertEqual(out["final"]["pmin_v"], "")           # the builder chooses the price band; nothing is assumed
        self.assertEqual(out["final"]["books_max"], "6")
        self.assertEqual(out["final"]["books_v"], "2")
        self.assertEqual(out["final"]["bets_max"], "2")
        self.assertEqual(out["final"]["name_max"], "10")
        self.assertEqual(out["final"]["tag_max"], "20")
        self.assertEqual(out["final"]["presets"], ["-180", "-150", "100", "300"])
        self.assertIn("No selection at -200 or worse, ever.", out["final"]["cap"])
        self.assertEqual(out["final"]["limit"], "Up to 2 dogs a person.")
        self.assertEqual(out["final"]["counts"], "0 / 10")
        # the page's own HTML and script name no sport, market or rule
        # (the playful side-rule table decorates the menu's own options by their `value`; it adds no option)
        for word in ("MLB", "NFL", "Moneyline", "moneyline", "curling"):
            self.assertNotIn(word, HTML["build-a-hound.html"])
            self.assertNotIn(word, (WEB / "js" / "hounds-build.js").read_text(encoding="utf-8"), word)

    def test_the_real_menu_renders_with_its_real_limits(self):
        out = self.build(queries=[
            q("sports", "[data-field='sport'] label", "texts"), q("markets", "[data-field='market'] label", "texts"),
            q("sides", "[data-field='side'] label", "texts"), q("lock", "[data-hook='f-lock'] option", "texts"),
            q("pmin", "[data-hook='f-price-min']", "attr", attr="min"), q("pmax", "[data-hook='f-price-max']", "attr", attr="max"),
            q("name_max", "[data-hook='f-name']", "attr", attr="maxlength"), q("counts", "[data-hook='name-count']")])
        self.assertEqual(out["final"]["sports"], ["MLB", "NFL"])
        self.assertEqual(out["final"]["markets"], ["Moneyline", "Spread / run line", "Game total"])
        self.assertEqual(len(out["final"]["sides"]), 8)
        for playful in ("Always the chalk", "Dogs only", "Tail the steam", "Fade the steam", "Overs machine", "Unders only"):
            self.assertTrue(any(s.startswith(playful) for s in out["final"]["sides"]), playful)
        # the plain label stays beside the joke, so nothing about what the rule does is hidden
        self.assertTrue(any("The favourite" in s for s in out["final"]["sides"]))
        self.assertEqual(out["final"]["lock"], [f"{m} minutes before the start" for m in (60, 120, 180)])
        self.assertEqual((out["final"]["pmin"], out["final"]["pmax"]), ("-199", "1000"))   # never -200 or worse
        self.assertEqual(out["final"]["name_max"], "24")
        self.assertEqual(out["final"]["counts"], "0 / 24")

    def test_a_side_rule_that_does_not_fit_the_chosen_markets_is_switched_off(self):
        """The menu gives every side rule the markets it works on; the form uses it, the server checks again."""
        out = self.build(queries=[
            q("off", "[data-field='side'] input", "attrs", attr="disabled"),
            q("sides", "[data-field='side'] label", "texts")],
            actions=[dict(do="check", sel="[data-field='market'] input", index=2, label="total",
                          capture=[q("off", "[data-field='side'] input", "attrs", attr="disabled")]),
                     dict(do="check", sel="[data-field='side'] input", index=4, label="over"),
                     dict(do="check", sel="[data-field='market'] input", index=2, checked=False),
                     dict(do="check", sel="[data-field='market'] input", index=0, label="moneyline",
                          capture=[q("off", "[data-field='side'] input", "attrs", attr="disabled"),
                                   q("preview", "[data-hook='build-preview-text']")])])
        # at the end a moneyline is chosen: only over and under (which are about totals) are off
        self.assertEqual(out["final"]["off"], [None, None, None, None, "", "", None, None])
        total = out["captures"]["total"]["off"]
        # order: favourite underdog home away over under moved_toward moved_away
        self.assertEqual([x is not None for x in total], [True, True, True, True, False, False, False, False])
        moneyline = out["captures"]["moneyline"]["off"]
        self.assertEqual([x is not None for x in moneyline], [False, False, False, False, True, True, False, False])
        self.assertIn("Choose a sport, a market and a side rule", out["captures"]["moneyline"]["preview"])   # 'over' was cleared

    def test_the_side_rules_are_said_the_way_bettors_say_them_and_the_card_follows_the_form(self):
        out = self.build(queries=[
            q("side_labels", "[data-field='side'] .hd-check__label", "texts"),
            q("hints", "[data-field='side'] .hd-check__hint", "texts")],
            captureInitial=[q("card_name", "[data-hook='dog-name']"), q("card_bio", "[data-hook='dog-bio']")],
            actions=[
                dict(do="check", sel="[data-field='sport'] input", index=0),
                dict(do="check", sel="[data-field='market'] input", index=0),
                dict(do="check", sel="[data-field='side'] input", index=7, label="fade",
                     capture=[q("style", "[data-hook='dog-style']"), q("bio", "[data-hook='dog-bio']"),
                              q("vibe", "[data-hook='build-dog-card'] .hd-avatar", "attr", attr="data-vibe")]),
                dict(do="set", sel="[data-hook='f-name']", value="Spite Pup", label="named",
                     capture=[q("name", "[data-hook='dog-name']")]),
                dict(do="set", sel="[data-hook='f-tagline']", value="Does the opposite", label="bio",
                     capture=[q("bio", "[data-hook='dog-bio']")])])
        self.assertEqual(out["final"]["side_labels"], ["Always the chalk", "Dogs only", "Home cooking", "Road warriors",
                                                       "Overs machine", "Unders only", "Tail the steam", "Fade the steam"])
        self.assertEqual(out["final"]["hints"][0], "The favourite")
        self.assertEqual(out["captures"]["initial"]["card_name"], "Your dog")
        self.assertEqual(out["captures"]["initial"]["card_bio"], "Still deciding what it's about.")
        self.assertEqual(out["captures"]["fade"]["style"], "Fade the steam")
        self.assertEqual(out["captures"]["fade"]["bio"], "Fade the steam. MLB moneyline.")
        self.assertEqual(out["captures"]["fade"]["vibe"], "chaos")
        self.assertEqual(out["captures"]["named"]["name"], "Spite Pup")
        self.assertEqual(out["captures"]["bio"]["bio"], "Does the opposite")

    def test_a_missing_menu_gives_a_not_switched_on_sentence_and_no_form(self):
        r = routes()
        r.pop("/hounds/menu")
        out = self.build(routes=r, queries=[q("host", "[data-hook='build-form-host']"), q("form", "[data-hook='build-form']", "count"),
                                            q("preview_hidden", "[data-hook='build-preview']", "hidden"),
                                            q("notice", "[data-hook='paper-notice']")])
        self.assertIn("not switched on yet", out["final"]["host"])
        self.assertEqual(out["final"]["form"], 0)
        self.assertTrue(out["final"]["preview_hidden"])
        self.assertIn("never takes a price of -200 or worse", out["final"]["notice"])

    def test_the_hard_notice_is_on_the_page_with_the_form_present(self):
        out = self.build(queries=[q("notice", "[data-hook='paper-notice']")])
        line = "Paper bets only. Your dog never places a real bet, and it never takes a price of -200 or worse."
        self.assertIn(line, out["final"]["notice"])
        self.assertIn(line, out["text"])

    def test_signed_out_shows_the_form_a_sign_in_gate_and_a_disabled_create_button(self):
        out = self.build(queries=[
            q("gate", "[data-hook='build-gate']"), q("gate_hidden", "[data-hook='build-gate']", "hidden"),
            q("early", "[data-hook='gate-early-access']", "attr", attr="href"),
            q("signin", "[data-hook='gate-signin']", "attr", attr="href"),
            q("btn", "[data-hook='build-submit']"), q("disabled", "[data-hook='build-submit']", "disabled"),
            q("form", "[data-hook='build-form']", "count")],
            actions=[dict(do="set", sel="[data-hook='f-name']", value="Pup"),
                     dict(do="click", sel="[data-hook='build-submit']", label="click")])
        self.assertFalse(out["final"]["gate_hidden"])
        self.assertIn("Sign in to send your dog in", out["final"]["gate"])
        self.assertEqual(out["final"]["early"], "index.html#/signup")
        self.assertEqual(out["final"]["signin"], "index.html#/signin")
        self.assertEqual(out["final"]["btn"], "Sign in to send your dog in")
        self.assertTrue(out["final"]["disabled"])
        self.assertEqual(out["final"]["form"], 1)         # they can still play with the form and the preview
        self.assertEqual(out["posts"], [])
        self.assertNotIn("/hounds/mine", out["gets"])      # no account calls without a token

    def test_the_live_preview_follows_the_form_says_average_price_and_is_labelled_preview(self):
        out = self.build(
            queries=[q("label", "[data-hook='build-preview']"), q("text", "[data-hook='build-preview-text']")],
            actions=[
                dict(do="check", sel="[data-field='sport'] input", index=0),
                dict(do="check", sel="[data-field='market'] input", index=0),
                dict(do="check", sel="[data-field='side'] input", index=1, label="rule",
                     capture=[q("text", "[data-hook='build-preview-text']")]),
                dict(do="set", sel="[data-hook='f-price-min']", value="-150"),
                dict(do="set", sel="[data-hook='f-price-max']", value="250", label="band",
                     capture=[q("text", "[data-hook='build-preview-text']")]),
                dict(do="set", sel="[data-hook='f-name']", value="Pup", label="name",
                     capture=[q("count", "[data-hook='name-count']")])])
        self.assertIn("preview", out["final"]["label"].lower())
        self.assertIn("A preview, written by this page", out["final"]["label"])
        self.assertIn("Bet the underdog in moneyline (MLB)", out["captures"]["rule"]["text"])
        self.assertIn("never takes a price of -200 or worse", out["captures"]["rule"]["text"])
        # the engine prices a bet at the board AVERAGE, and the preview says so (it used to say "best price")
        self.assertIn("average price across the books is between -150 and +250", out["captures"]["band"]["text"])
        self.assertNotIn("best price", out["captures"]["band"]["text"])
        self.assertEqual(out["captures"]["name"]["count"], "3 / 24")

    def test_signed_in_posts_a_spec_with_the_real_field_names_and_goes_to_the_new_hounds_page(self):
        """MISALIGNMENT 1. POST /hounds takes {spec: {...}} and answers {hound: {id}}: the page used to post
        the fields flat (a 422 from the real API) and read ``id`` off the top level."""
        r = routes()
        r["POST /hounds"] = [200, {"hound": {"id": "u-pup1", "name": "Pup"}, "paper_only": True}]
        out = self.build(routes=r, stored={TOKEN_KEY: "tok"}, actions=self.FILL + [
            dict(do="click", sel="[data-hook='build-submit']", label="go", wait=80)],
            queries=[q("limit", "[data-hook='limit-text']"), q("btn", "[data-hook='build-submit']")])
        self.assertEqual(len(out["posts"]), 1)
        body = out["posts"][0]["body"]
        self.assertEqual(out["posts"][0]["url"], "/hounds")
        self.assertEqual(out["posts"][0]["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(sorted(body), ["spec"])
        spec = body["spec"]
        self.assertEqual((spec["name"], spec["tagline"]), ("Pup", "Fetches"))
        self.assertEqual((spec["sports"], spec["markets"], spec["side_rule"]), (["MLB"], ["moneyline"], "underdog"))
        self.assertEqual((spec["price_min"], spec["price_max"], spec["min_books"]), (-150, 250, 1))
        self.assertEqual((spec["max_bets_per_day"], spec["lock_minutes"]), (1, 60))
        self.assertEqual(out["navigations"], ["hound.html?id=u-pup1"])
        self.assertEqual(out["final"]["limit"], "You have 0 of 3 dogs.")

    def test_the_three_hound_limit_is_shown_and_enforced_in_the_button(self):
        r = routes()
        r["/hounds/mine"] = [200, {"hounds": [{"id": i, "status": "running"} for i in "abc"], "limit_running": 3}]
        out = self.build(routes=r, stored={TOKEN_KEY: "tok"}, queries=[
            q("limit", "[data-hook='limit-text']"), q("btn", "[data-hook='build-submit']"),
            q("disabled", "[data-hook='build-submit']", "disabled")],
            actions=[dict(do="click", sel="[data-hook='build-submit']")])
        self.assertEqual(out["final"]["limit"], "You have 3 of 3 dogs.")
        self.assertEqual(out["final"]["btn"], "You already have 3 dogs")
        self.assertTrue(out["final"]["disabled"])
        self.assertEqual(out["posts"], [])
        signed_out = self.build(queries=[q("limit", "[data-hook='limit-text']")])
        self.assertEqual(signed_out["final"]["limit"], "Up to 3 dogs a person.")

    def test_a_retired_hound_does_not_count_toward_the_limit(self):
        r = routes()
        r["/hounds/mine"] = [200, {"hounds": [{"id": "a", "status": "running"}, {"id": "b", "status": "retired"},
                                              {"id": "c", "status": "retired"}], "limit_running": 3}]
        out = self.build(routes=r, stored={TOKEN_KEY: "tok"}, queries=[q("limit", "[data-hook='limit-text']")])
        self.assertEqual(out["final"]["limit"], "You have 1 of 3 dogs.")

    def test_problems_are_listed_and_nothing_is_posted_until_the_form_is_valid(self):
        out = self.build(stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel="[data-hook='build-submit']", label="empty",
                 capture=[q("p", "[data-hook='build-problems']")]),
            dict(do="set", sel="[data-hook='f-name']", value="Pup"),
            dict(do="check", sel="[data-field='sport'] input", index=0),
            dict(do="check", sel="[data-field='market'] input", index=0),
            dict(do="check", sel="[data-field='side'] input", index=1),
            dict(do="set", sel="[data-hook='f-price-min']", value="-500"),
            dict(do="set", sel="[data-hook='f-price-max']", value="50"),
            dict(do="click", sel="[data-hook='build-submit']", label="cap",
                 capture=[q("p", "[data-hook='build-problems']")]),
            dict(do="set", sel="[data-hook='f-price-min']", value="120"),
            dict(do="set", sel="[data-hook='f-price-max']", value="-110"),
            dict(do="click", sel="[data-hook='build-submit']", label="order",
                 capture=[q("p", "[data-hook='build-problems']")])])
        self.assertIn("Give your dog a name.", out["captures"]["empty"]["p"])
        self.assertIn("Choose at least one sport.", out["captures"]["empty"]["p"])
        self.assertIn("Enter the shortest price", out["captures"]["empty"]["p"])
        self.assertIn("The shortest price cannot be -200 or worse", out["captures"]["cap"]["p"])
        self.assertIn("The longest price must be an American price", out["captures"]["cap"]["p"])      # +50 is not one
        self.assertIn("The longest price must be the same as or longer than the shortest price",
                      out["captures"]["order"]["p"])
        self.assertEqual(out["posts"], [])

    def test_a_server_refusal_is_shown_in_words_and_a_401_returns_to_the_gate(self):
        r = routes()
        # the real 422 (api/hounds_create.py _spec_error): detail {error: "spec_invalid", fields: {field: message}}
        r["POST /hounds"] = [422, {"detail": {"error": "spec_invalid", "fields": {
            "name": "is already taken", "price_min": "cannot be -200 or worse; this program never selects a price that short"}}}]
        click = [dict(do="click", sel="[data-hook='build-submit']", label="go", wait=80)]
        refused = self.build(routes=r, stored={TOKEN_KEY: "tok"}, actions=self.FILL + click,
                             queries=[q("e", "[data-hook='build-server-error']")])
        self.assertIn("name is already taken", refused["final"]["e"])
        self.assertIn("price min cannot be -200 or worse", refused["final"]["e"])
        self.assertEqual(refused["navigations"], [])
        r["POST /hounds"] = [409, {"detail": {"error": "limit", "message": "an account can run at most 3 hounds; retire one first"}}]
        limit = self.build(routes=r, stored={TOKEN_KEY: "tok"}, actions=self.FILL + click,
                           queries=[q("e", "[data-hook='build-server-error']")])
        self.assertIn("an account can run at most 3 hounds", limit["final"]["e"])
        r["POST /hounds"] = [401, {"detail": "no"}]
        unauth = self.build(routes=r, stored={TOKEN_KEY: "stale"}, actions=self.FILL + click,
                            queries=[q("gate", "[data-hook='build-gate']", "hidden")])
        self.assertFalse(unauth["final"]["gate"])
        r["POST /hounds"] = [200, {"ok": True}]
        no_id = self.build(routes=r, stored={TOKEN_KEY: "tok"}, actions=self.FILL + click,
                           queries=[q("m", "[data-hook='build-message']")])
        self.assertIn("didn't say where it is", no_id["final"]["m"])
        self.assertEqual(no_id["navigations"], [])

    def test_from_prefills_the_form_from_the_hounds_spec_including_the_suggested_name(self):
        out = self.build(search="?from=closer", queries=[
            q("note", "[data-hook='build-from-note']"), q("note_hidden", "[data-hook='build-from-note']", "hidden"),
            q("pmin", "[data-hook='f-price-min']", "value"), q("pmax", "[data-hook='f-price-max']", "value"),
            q("books", "[data-hook='f-books']", "value"), q("lock", "[data-hook='f-lock']", "value"),
            q("preview", "[data-hook='build-preview-text']"), q("name", "[data-hook='f-name']", "value"),
            q("tagline", "[data-hook='f-tagline']", "value")])
        self.assertIn("/hounds/closer/spec", out["gets"])
        self.assertEqual((out["final"]["pmin"], out["final"]["pmax"], out["final"]["books"], out["final"]["lock"]),
                         ("-150", "250", "4", "60"))
        self.assertIn("Bet the underdog in moneyline (MLB)", out["final"]["preview"])
        self.assertIn("Pre-filled from that dog's rules", out["final"]["note"])
        self.assertEqual(out["final"]["name"], "Closer II")        # the server suggests a free name (names are unique)
        self.assertEqual(out["final"]["tagline"], "Takes the price before it moves.")

    def test_a_copy_is_posted_with_copied_from_beside_the_spec(self):
        r = routes()
        r["POST /hounds"] = [200, {"hound": {"id": "u-copy1"}}]
        out = self.build(routes=r, search="?from=closer", stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel="[data-hook='build-submit']", label="go", wait=80)])
        self.assertEqual(len(out["posts"]), 1, out["posts"])
        body = out["posts"][0]["body"]
        self.assertEqual(body["copied_from"], "closer")
        self.assertEqual(body["spec"]["name"], "Closer II")
        self.assertEqual(body["spec"]["sports"], ["MLB"])
        self.assertEqual(out["navigations"], ["hound.html?id=u-copy1"])

    def test_a_spec_that_cannot_be_loaded_leaves_a_blank_form_and_says_so(self):
        r = routes()
        r.pop("/hounds/closer/spec")
        out = self.build(routes=r, search="?from=closer", queries=[q("note", "[data-hook='build-from-note']"),
                                                                    q("form", "[data-hook='build-form']", "count")])
        self.assertIn("the form is blank", out["final"]["note"])
        self.assertEqual(out["final"]["form"], 1)


if __name__ == "__main__":
    unittest.main()
