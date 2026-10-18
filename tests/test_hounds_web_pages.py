"""The three Hounds pages, run for real (their own scripts, their own HTML) under node against a fake DOM.

  web/hounds.html         the race: chart, verdict-ordered leaderboard, stream, graveyard
  web/hound.html?id=      one hound: rule + Copy, verdict, charts, paged bets
  web/build-a-hound.html  the build form, generated from /hounds/menu

Skipped when node is not installed. Fixtures: tests/hounds_web_fixtures.py. Static checks (not-advice on
every page, no Bet Check, no external images) and "the pages are served" need no node.
"""

from __future__ import annotations

import copy
import re
import unittest
from pathlib import Path

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
                self.assertRegex(text, r"(?i)paper only, not advice", name)
                self.assertIn("21+", text)
                self.assertIn("1-800-GAMBLER", text)
                self.assertIn("not-advice", html)   # the data-hook the footer line carries

    def test_the_minus_200_cap_notice_is_static_on_the_build_page(self):
        text = visible(HTML["build-a-hound.html"])
        self.assertIn("Paper only. Your hound never places a real bet. The -200-or-worse cap is always on.", text)

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

    def test_the_landing_page_links_to_the_race_in_its_first_screen(self):
        landing = (WEB / "landing.html").read_text(encoding="utf-8")
        first = landing[landing.index('data-hook="hero"'):landing.index('data-hook="hero-wyg"')]
        self.assertRegex(first, r'<a [^>]*href="hounds.html"[^>]*>Watch the hounds race')


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
class TheLeaderboardIsOrderedByVerdictNotUnits(unittest.TestCase):
    def test_rows_follow_the_verdict_even_when_units_say_the_opposite(self):
        hs = [mk("rich", "Rich", "PAYING THE VIG", bets=60, units=+80.0),
              mk("mid", "Mid", "TOO EARLY", bets=8, units=+30.0),
              mk("flat", "Flat", "NO DIFFERENT FROM THE MARKET", bets=40, units=+10.0),
              mk("poor", "Poor", "BEATING THE CLOSE", bets=45, units=-25.0)]
        r = routes(**{"/hounds": [200, {"hounds": hs, "basis": "b", "as_of": "2026-10-24T23:00:00Z"}]})
        r["/hounds/series"] = [404, {}]
        out = run_page("hounds", routes=r, queries=[
            q("ids", "[data-hook='hounds-list'] .hd-row", "attrs", attr="data-hound"),
            q("chips", "[data-hook='hounds-list'] [data-hook='verdict-chip']", "texts")])
        self.assertEqual(out["final"]["ids"], ["poor", "flat", "mid", "rich"])
        self.assertEqual([re.sub(r"^\W+\s*", "", c) for c in out["final"]["chips"]],
                         ["BEATING THE CLOSE", "NO DIFFERENT FROM THE MARKET", "TOO EARLY", "PAYING THE VIG"])

    def test_the_page_says_so_and_shows_units_as_small_print(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("explainer", "[data-hook='units-explainer']"), q("units", "[data-hook='row-units']", "texts")])
        self.assertEqual(out["final"]["explainer"],
                         "Units over a few weeks are mostly luck. The verdict asks whether a hound beat the closing price, "
                         "using a test written before the race started.")
        self.assertTrue(out["final"]["units"])
        self.assertTrue(all(u.startswith("Units, small print:") or u == "Units: none yet" for u in out["final"]["units"]))

    def test_each_row_carries_the_fields_the_brief_asks_for(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("first", ".hd-row[data-hound='closer']"), q("spark", ".hd-row[data-hound='closer'] [data-hook='spark']", "count"),
            q("tick", ".hd-row[data-hound='closer'] [data-hook='verified']"), q("avatar", ".hd-row[data-hound='closer'] .hd-avatar", "count"),
            q("untick", ".hd-row[data-hound='rusty'] [data-hook='verified']", "count"),
            q("basis", "[data-hook='hounds-basis']")])
        row = out["final"]["first"]
        for needle in ("Closer", "Takes the price before it moves.", "BEATING THE CLOSE", "Forward record", "41 bets",
                       "Forward price vs the close (CLV)", "interval", "n=41", "Running", "verified", "Stats", "House hound"):
            self.assertIn(needle, row)
        self.assertEqual(out["final"]["spark"], 1)
        self.assertEqual(out["final"]["avatar"], 1)
        self.assertEqual(out["final"]["untick"], 0)     # an unverified hound has no tick
        self.assertIn("Basis: Forward results are paper bets", out["final"]["basis"])
        self.assertIn("Paper results only. Not advice.", out["final"]["basis"])   # the server's own line is shown

    def test_a_hound_with_no_line_yet_says_so_instead_of_drawing_a_flat_one(self):
        hs = [mk("new", "New", "TOO EARLY", bets=0, spark=[])]
        r = routes(**{"/hounds": [200, {"hounds": hs}]})
        r["/hounds/series"] = [200, {"series": {}}]
        out = run_page("hounds", routes=r, queries=[q("none", "[data-hook='spark-none']", "count")])
        self.assertEqual(out["final"]["none"], 1)

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

    def test_forward_is_the_headline_and_replay_is_a_separate_smaller_line(self):
        out = run_page("hounds", routes=routes(), queries=[
            q("fwd", ".hd-row[data-hound='closer'] [data-hook='forward-facts']"),
            q("replay", ".hd-row[data-hound='closer'] [data-hook='replay-line']"),
            q("none_fwd", ".hd-row[data-hound='rusty'] [data-hook='forward-facts']"),
            q("none_replay", ".hd-row[data-hound='rusty'] [data-hook='replay-line']")])
        self.assertIn("Forward record", out["final"]["fwd"])
        self.assertIn("41 bets", out["final"]["fwd"])
        self.assertNotIn("160 bets", out["final"]["fwd"])
        self.assertRegex(out["final"]["replay"], r"^replay \(rule written 2026-10-18, applied to earlier boards\)\s*:")
        self.assertIn("160 bets", out["final"]["replay"])
        self.assertIn("No forward bets yet", out["final"]["none_fwd"])
        self.assertIn("40 bets", out["final"]["none_replay"])
        css = (WEB / "css" / "hounds.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.hd-row__replay\s*\{[^}]*font-size:\s*13px")
        self.assertRegex(css, r"\.hd-row__facts dd\s*\{[^}]*font-size:\s*15px")

    def test_the_chart_defaults_to_replay_until_forward_data_exists_and_says_so(self):
        out = run_page("hounds", routes=routes(forward=False), captureInitial=[
            q("title", "[data-hook='hounds-chart-title']"),
            q("pressed", "[data-hook='hounds-segment'] .hd-seg", "attrs", attr="aria-pressed"),
            q("lines", "[data-hook='hounds-chart-panel'] .hd-line path", "count")],
            actions=[dict(do="click", sel="[data-hook='hounds-segment'] [data-segment='forward']", label="fwd",
                          capture=[q("title", "[data-hook='hounds-chart-title']"), q("empty", "[data-hook='chart-empty']")])])
        first = out["captures"]["initial"]
        self.assertEqual(first["pressed"], ["false", "true"])      # Forward | Replay: Replay pressed
        self.assertIn("Replay only for now", first["title"])
        self.assertIn("rule written 2026-10-18, applied to earlier boards", first["title"])
        self.assertIn("No forward results exist yet", first["title"])
        self.assertGreater(first["lines"], 0)
        self.assertIn("Forward results", out["captures"]["fwd"]["title"])
        self.assertIn("No forward results yet", out["captures"]["fwd"]["empty"])

    def test_with_forward_data_the_chart_defaults_to_forward_and_the_toggle_switches(self):
        out = run_page("hounds", routes=routes(forward=True), captureInitial=[
            q("title", "[data-hook='hounds-chart-title']"),
            q("pressed", "[data-hook='hounds-segment'] .hd-seg", "attrs", attr="aria-pressed")],
            actions=[dict(do="click", sel="[data-hook='hounds-segment'] [data-segment='replay']", label="rep",
                          capture=[q("title", "[data-hook='hounds-chart-title']")])])
        first = out["captures"]["initial"]
        self.assertEqual(first["pressed"], ["true", "false"])
        self.assertTrue(first["title"].startswith("Forward results"))
        self.assertTrue(out["captures"]["rep"]["title"].startswith("Replay results"))

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
        self.assertIn("Paper results. Units over a few weeks are mostly luck; the verdict below each hound is the test.",
                      out["final"]["label"])
        self.assertEqual(out["final"]["rows"], 7)                  # seven forward dates
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
        self.assertIn("14 settled", tip)
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
        self.assertIn("No hounds are racing yet", out["final"]["empty"])
        self.assertEqual(out["final"]["cta"], "build-a-hound.html")
        self.assertIn("No decisions yet", out["final"]["stream"])
        self.assertIn("Nobody has been retired yet", out["final"]["grave"])
        self.assertIn("No hounds yet, so there is nothing to draw", out["final"]["chart"])
        self.assertFalse([g for g in out["gets"] if g.startswith("/hounds/series")])
        self.assertIn("Basis: b", out["final"]["basis"])

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
        self.assertIn("Paper only. Not advice.", out["final"]["paper"])
        self.assertEqual(out["final"]["cta"], "build-a-hound.html")
        self.assertIn("Paper only, not advice", out["final"]["footer"])
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
        self.assertEqual(out["final"]["who"], ["Decided by: Rule", "Decided by: Model", "Decided by: Code"])
        self.assertEqual(out["final"]["items"], 3)

    def test_the_graveyard_lists_hounds_with_their_cause(self):
        out = run_page("hounds", routes=routes(), queries=[q("cause", "[data-hook='grave-cause']", "texts")])
        self.assertEqual(len(out["final"]["cause"]), 1)
        self.assertTrue(out["final"]["cause"][0].startswith("Cause: Retired by its builder"))


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
        self.assertEqual(out["final"]["btn"], "Copy rule")
        self.assertEqual(out["clipboard"], [rule])
        self.assertEqual(out["captures"]["copy"]["status"], "Copied.")
        self.assertEqual(out["final"]["from"], "build-a-hound.html?from=closer")

    def test_a_blocked_clipboard_says_so_and_does_not_claim_it_copied(self):
        out = self.page(clipboardFails=True, actions=[dict(do="click", sel="[data-hook='copy-rule']", label="copy",
                                                           capture=[q("status", "[data-hook='copy-status']")])])
        self.assertEqual(out["clipboard"], [])
        self.assertIn("Could not copy", out["captures"]["copy"]["status"])
        self.assertNotIn("Copied.", out["captures"]["copy"]["status"])

    def test_the_verdict_comes_with_its_plain_language_meaning_and_the_sample_size(self):
        out = self.page(queries=[q("chip", "[data-hook='verdict-chip']"), q("sentence", "[data-hook='verdict-sentence']"),
                                 q("meaning", "[data-hook='verdict-meaning']"), q("name", "[data-hook='hound-name']"),
                                 q("verdict", "[data-hook='hound-verdict']")])
        self.assertIn("BEATING THE CLOSE", out["final"]["chip"])
        self.assertIn("better than the closing prices", out["final"]["sentence"])
        self.assertIn("not a profit claim", out["final"]["meaning"])
        self.assertIn("Sample size: 41 settled forward bets. That is a small sample.", out["final"]["verdict"])
        self.assertEqual(out["final"]["name"], "Closer")
        self.assertEqual(out["title"], "Closer — LINEHOUND")

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
        self.assertEqual(out["final"]["units_lines"], ["avg", "rec"])
        self.assertEqual(out["final"]["clv_lines"], ["clv"])
        self.assertEqual(out["final"]["units_cols"], ["Date", "Average price (units)", "Recorded price (units)"])
        self.assertIn("Recorded and average price", out["final"]["note"])
        self.assertIn("closing price", out["final"]["clv_label"])

    def test_replay_only_hound_charts_replay_and_says_so(self):
        out = self.page(hid="rusty", queries=[q("title", "[data-hook='hound-chart-title']"),
                                              q("fwd", "[data-hook='forward-facts']"), q("rep", "[data-hook='replay-line']")])
        self.assertIn("Replay only for now", out["final"]["title"])
        self.assertIn("No forward bets yet", out["final"]["fwd"])
        self.assertIn("replay (rule written 2026-10-18, applied to earlier boards)", out["final"]["rep"])

    def test_bets_are_paged_with_a_clear_who_decided_and_accessible_results(self):
        out = self.page(captureInitial=[
            q("rows", "[data-hook='bets-table'] tbody tr", "count"),
            q("who", "[data-hook='bets-table'] tbody tr", "attrs", attr="data-who"),
            q("page", "[data-hook='bets-page']"), q("prev", "[data-hook='bets-prev']", "disabled"),
            q("heads", "[data-hook='bets-table'] thead th", "texts"),
            q("results", "[data-hook='bets-table'] .hd-result", "texts")],
            actions=[dict(do="click", sel="[data-hook='bets-next']", label="p2",
                          capture=[q("page", "[data-hook='bets-page']"), q("rows", "[data-hook='bets-table'] tbody tr", "count"),
                                   q("prev", "[data-hook='bets-prev']", "disabled")]),
                     dict(do="click", sel="[data-hook='bets-next']", label="p3",
                          capture=[q("rows", "[data-hook='bets-table'] tbody tr", "count"),
                                   q("next", "[data-hook='bets-next']", "disabled")])])
        self.assertEqual(out["captures"]["p2"]["page"], "Page 2 of 3 (45 bets)")
        self.assertEqual(out["captures"]["p2"]["rows"], 20)
        self.assertFalse(out["captures"]["p2"]["prev"])
        self.assertEqual(out["captures"]["p3"]["rows"], 5)
        self.assertTrue(out["captures"]["p3"]["next"])
        first = out["captures"]["initial"]
        self.assertEqual(first["page"], "Page 1 of 3 (45 bets)")
        self.assertEqual(first["rows"], 20)
        self.assertTrue(first["prev"])
        self.assertIn("Decided by", first["heads"])
        self.assertTrue(set(first["who"]) <= {"rule", "code", "model"})
        # colour is never the only cue: every result carries a word
        for text in first["results"]:
            self.assertRegex(text, r"(Win|Loss|Push|Void|Pending)")
        css = (WEB / "css" / "hounds.css").read_text(encoding="utf-8")
        for tone in ("win", "loss"):
            self.assertIn(f".hd-result--{tone}", css)

    def test_bets_with_no_bets_say_so_and_a_failed_bets_call_says_why(self):
        none = self.page(routes={"/hounds/closer": [200, dict(F.detail("closer"), bets=[])]},
                         queries=[q("e", "[data-hook='bets-empty']")])
        self.assertIn("No bets yet", none["final"]["e"])
        # a detail payload without bets[] falls back to /hounds/{id}/bets; here that endpoint is missing
        d = F.detail("closer")
        d.pop("bets")
        missing = self.page(routes={"/hounds/closer": [200, d]}, queries=[q("s", "[data-hook='hound-bets'] [data-hook='section-state']")])
        self.assertIn("not switched on yet", missing["final"]["s"])
        self.assertIn("/hounds/closer/bets", missing["gets"])
        # and when it is there, its rows are used
        ok = self.page(routes={"/hounds/closer": [200, d], "/hounds/closer/bets": [200, {"bets": F.bets("closer", 3)}]},
                       queries=[q("n", "[data-hook='bets-table'] tbody tr", "count")])
        self.assertEqual(ok["final"]["n"], 3)

    def test_a_retired_hound_shows_its_cause(self):
        d = F.detail("closer")
        d.update(status="retired", cause="Retired after 60 bets; the test could not separate it from the market.")
        out = self.page(routes={"/hounds/closer": [200, d]}, queries=[
            q("cause", "[data-hook='hound-cause']"), q("hidden", "[data-hook='hound-cause']", "hidden"),
            q("status", "[data-hook='hound-status']")])
        self.assertFalse(out["final"]["hidden"])
        self.assertIn("Retired. Cause: Retired after 60 bets", out["final"]["cause"])
        self.assertEqual(out["final"]["status"], "Retired")

    def test_a_running_hound_has_no_cause_box(self):
        out = self.page(queries=[q("hidden", "[data-hook='hound-cause']", "hidden")])
        self.assertTrue(out["final"]["hidden"])

    def test_unknown_hound_missing_id_and_down_server(self):
        gone = run_page("hound", routes=routes(), search="?id=nope", queries=[q("t", "[data-hook='hound-header']"),
                                                                              q("v", "[data-hook='hound-verdict-section']", "hidden")])
        self.assertIn("There is no hound with this id", gone["final"]["t"])
        self.assertTrue(gone["final"]["v"])
        noid = run_page("hound", routes=routes(), search="", queries=[q("t", "[data-hook='hound-header']")])
        self.assertIn("No hound was chosen", noid["final"]["t"])
        down = run_page("hound", routes=routes(), search="?id=closer", down=["/hounds/closer"],
                        queries=[q("t", "[data-hook='hound-header']")])
        self.assertIn("Could not reach this hound", down["final"]["t"])

    def test_series_missing_gives_an_honest_chart_state_and_the_rest_of_the_page_stays(self):
        r = routes()
        r.pop("/hounds/series")
        out = run_page("hound", routes=r, search="?id=closer", queries=[
            q("chart", "[data-hook='hound-units-chart']"), q("rule", "[data-hook='rule-text']", "texts"),
            q("rows", "[data-hook='bets-table'] tbody tr", "count")])
        self.assertIn("not switched on yet", out["final"]["chart"])
        self.assertTrue(out["final"]["rule"])
        self.assertEqual(out["final"]["rows"], 20)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheChartsRenderEmptyAndOnePointSeriesHonestly(unittest.TestCase):
    def detail_with_series(self, points):
        r = routes()
        r["/hounds/series"] = [200, {"series": {"closer": points}}]
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
        self.assertIn("No settled bets to draw yet", out["final"]["empty"])
        self.assertEqual(out["final"]["zero"], 0)      # no baseline drawn for a chart with nothing on it
        self.assertEqual(out["final"]["paths"], 0)
        self.assertIn("No CLV measured yet", out["final"]["clv_empty"])

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
        self.assertIn("No CLV measured yet", out["final"]["clv_empty"])
        self.assertEqual(out["final"]["paths"], 2)

    def test_the_leaderboard_chart_with_no_series_for_anyone_says_so(self):
        r = routes()
        r["/hounds/series"] = [200, {"series": {}}]
        out = run_page("hounds", routes=r, queries=[q("chart", "[data-hook='hounds-chart-panel']"),
                                                    q("zero", "[data-hook='chart-zero']", "count"),
                                                    q("rows", "[data-hound]", "count")])
        self.assertIn("No settled bets to draw yet", out["final"]["chart"])
        self.assertEqual(out["final"]["zero"], 0)
        self.assertGreater(out["final"]["rows"], 5)       # the leaderboard itself is unaffected


# ---------------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBuildPage(unittest.TestCase):
    ODD_MENU = {"sports": [{"id": "curling", "label": "Curling"}, {"id": "darts", "label": "Darts"}],
                "markets": [{"id": "outright", "label": "Outright"}],
                "side_rules": ["the loud one", {"id": "quiet", "label": "the quiet one"}],
                "price_band": {"min": -180, "max": 300}, "books": {"min": 2, "max": 6},
                "max_bets_per_day": {"min": 1, "max": 2}, "lock_minutes": [5, 45]}

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
            q("bets_max", "[data-hook='f-max-bets']", "attr", attr="max"),
            q("name_max", "[data-hook='f-name']", "attr", attr="maxlength"),
            q("tag_max", "[data-hook='f-tagline']", "attr", attr="maxlength"),
            q("counts", "[data-hook='name-count']")])
        self.assertEqual(out["final"]["sports"], ["Curling", "Darts"])
        self.assertEqual(out["final"]["markets"], ["Outright"])
        self.assertEqual(out["final"]["sides"], ["the loud one", "the quiet one"])
        self.assertEqual(out["final"]["lock"], ["5 minutes before the start", "45 minutes before the start"])
        self.assertEqual(out["final"]["pmin"], "-180")
        self.assertEqual(out["final"]["pmax"], "300")
        self.assertEqual(out["final"]["pmin_v"], "-180")
        self.assertEqual(out["final"]["books_max"], "6")
        self.assertEqual(out["final"]["bets_max"], "2")
        self.assertEqual(out["final"]["name_max"], "32")
        self.assertEqual(out["final"]["tag_max"], "80")
        self.assertEqual(out["final"]["counts"], "0 / 32")
        # the page's own HTML and script name no sport, market or rule
        for word in ("MLB", "NFL", "Moneyline", "moneyline", "underdog", "Underdog", "curling"):
            self.assertNotIn(word, HTML["build-a-hound.html"])
            self.assertNotIn(word, (WEB / "js" / "hounds-build.js").read_text(encoding="utf-8"), word)

    def test_a_missing_menu_gives_a_not_switched_on_sentence_and_no_form(self):
        r = routes()
        r.pop("/hounds/menu")
        out = self.build(routes=r, queries=[q("host", "[data-hook='build-form-host']"), q("form", "[data-hook='build-form']", "count"),
                                            q("preview_hidden", "[data-hook='build-preview']", "hidden"),
                                            q("notice", "[data-hook='paper-notice']")])
        self.assertIn("not switched on yet", out["final"]["host"])
        self.assertEqual(out["final"]["form"], 0)
        self.assertTrue(out["final"]["preview_hidden"])
        self.assertIn("The -200-or-worse cap is always on.", out["final"]["notice"])

    def test_the_hard_notice_is_on_the_page_with_the_form_present(self):
        out = self.build(queries=[q("notice", "[data-hook='paper-notice']")])
        self.assertIn("Paper only. Your hound never places a real bet. The -200-or-worse cap is always on.", out["final"]["notice"])
        self.assertIn("Paper only. Your hound never places a real bet. The -200-or-worse cap is always on.", out["text"])

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
        self.assertIn("Sign in to create a hound", out["final"]["gate"])
        self.assertEqual(out["final"]["early"], "index.html#/signup")
        self.assertEqual(out["final"]["signin"], "index.html#/signin")
        self.assertEqual(out["final"]["btn"], "Sign in to create your hound")
        self.assertTrue(out["final"]["disabled"])
        self.assertEqual(out["final"]["form"], 1)         # they can still play with the form and the preview
        self.assertEqual(out["posts"], [])
        self.assertNotIn("/hounds/mine", out["gets"])      # no account calls without a token

    def test_the_live_preview_follows_the_form_and_is_labelled_preview(self):
        out = self.build(
            queries=[q("label", "[data-hook='build-preview']"), q("text", "[data-hook='build-preview-text']")],
            actions=[
                dict(do="check", sel="[data-field='sport'] input", index=0),
                dict(do="check", sel="[data-field='market'] input", index=0),
                dict(do="check", sel="[data-field='side'] input", index=1, label="rule",
                     capture=[q("text", "[data-hook='build-preview-text']")]),
                dict(do="set", sel="[data-hook='f-name']", value="Pup", label="name",
                     capture=[q("count", "[data-hook='name-count']")])])
        self.assertIn("preview", out["final"]["label"].lower())
        self.assertIn("Preview, written by this page", out["final"]["label"])
        self.assertIn("Bet the favourite in moneyline (MLB)", out["captures"]["rule"]["text"])
        self.assertIn("never takes a price of -200 or worse", out["captures"]["rule"]["text"])
        self.assertEqual(out["captures"]["name"]["count"], "3 / 32")

    def test_signed_in_posts_the_spec_and_goes_to_the_new_hounds_page(self):
        r = routes()
        r["POST /hounds"] = [200, {"id": "pup-1", "name": "Pup"}]
        out = self.build(routes=r, stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="set", sel="[data-hook='f-name']", value="  Pup  "),
            dict(do="set", sel="[data-hook='f-tagline']", value="Fetches"),
            dict(do="check", sel="[data-field='sport'] input", index=0),
            dict(do="check", sel="[data-field='market'] input", index=0),
            dict(do="check", sel="[data-field='side'] input", index=0),
            dict(do="click", sel="[data-hook='build-submit']", label="go", wait=80)],
            queries=[q("limit", "[data-hook='limit-text']"), q("btn", "[data-hook='build-submit']")])
        self.assertEqual(len(out["posts"]), 1)
        body = out["posts"][0]["body"]
        self.assertEqual(out["posts"][0]["url"], "/hounds")
        self.assertEqual(out["posts"][0]["headers"]["Authorization"], "Bearer tok")
        self.assertEqual((body["name"], body["tagline"]), ("Pup", "Fetches"))
        self.assertEqual((body["sports"], body["markets"], body["side_rule"]), (["mlb"], ["moneyline"], "underdog"))
        self.assertEqual((body["price_min"], body["price_max"], body["min_books"]), (-200, 400, 1))
        self.assertEqual(out["navigations"], ["hound.html?id=pup-1"])
        self.assertEqual(out["final"]["limit"], "You have 0 of 3 hounds.")

    def test_the_three_hound_limit_is_shown_and_enforced_in_the_button(self):
        r = routes()
        r["/hounds/mine"] = [200, {"hounds": [{"id": i, "status": "running"} for i in "abc"]}]
        out = self.build(routes=r, stored={TOKEN_KEY: "tok"}, queries=[
            q("limit", "[data-hook='limit-text']"), q("btn", "[data-hook='build-submit']"),
            q("disabled", "[data-hook='build-submit']", "disabled")],
            actions=[dict(do="click", sel="[data-hook='build-submit']")])
        self.assertEqual(out["final"]["limit"], "You have 3 of 3 hounds.")
        self.assertEqual(out["final"]["btn"], "You already have 3 hounds")
        self.assertTrue(out["final"]["disabled"])
        self.assertEqual(out["posts"], [])
        signed_out = self.build(queries=[q("limit", "[data-hook='limit-text']")])
        self.assertEqual(signed_out["final"]["limit"], "Each person can have up to 3 hounds.")

    def test_problems_are_listed_and_nothing_is_posted_until_the_form_is_valid(self):
        out = self.build(stored={TOKEN_KEY: "tok"}, actions=[
            dict(do="click", sel="[data-hook='build-submit']", label="empty",
                 capture=[q("p", "[data-hook='build-problems']")]),
            dict(do="set", sel="[data-hook='f-name']", value="Pup"),
            dict(do="check", sel="[data-field='sport'] input", index=0),
            dict(do="check", sel="[data-field='market'] input", index=0),
            dict(do="check", sel="[data-field='side'] input", index=0),
            dict(do="set", sel="[data-hook='f-price-min']", value="-500"),
            dict(do="click", sel="[data-hook='build-submit']", label="cap",
                 capture=[q("p", "[data-hook='build-problems']")])])
        self.assertIn("Give your hound a name.", out["captures"]["empty"]["p"])
        self.assertIn("Choose at least one sport.", out["captures"]["empty"]["p"])
        self.assertIn("The lowest price must be between -200 and 400.", out["captures"]["cap"]["p"])
        self.assertEqual(out["posts"], [])

    def test_a_server_refusal_is_shown_verbatim_and_a_401_returns_to_the_gate(self):
        r = routes()
        r["POST /hounds"] = [422, {"detail": "price_min -250 is past the -200 cap"}]
        fill = [dict(do="set", sel="[data-hook='f-name']", value="Pup"),
                dict(do="check", sel="[data-field='sport'] input", index=0),
                dict(do="check", sel="[data-field='market'] input", index=0),
                dict(do="check", sel="[data-field='side'] input", index=0),
                dict(do="click", sel="[data-hook='build-submit']", label="go", wait=80)]
        refused = self.build(routes=r, stored={TOKEN_KEY: "tok"}, actions=fill,
                             queries=[q("e", "[data-hook='build-server-error']")])
        self.assertIn("price_min -250 is past the -200 cap", refused["final"]["e"])
        self.assertEqual(refused["navigations"], [])
        r["POST /hounds"] = [401, {"detail": "no"}]
        unauth = self.build(routes=r, stored={TOKEN_KEY: "stale"}, actions=fill,
                            queries=[q("gate", "[data-hook='build-gate']", "hidden")])
        self.assertFalse(unauth["final"]["gate"])
        r["POST /hounds"] = [200, {"ok": True}]
        no_id = self.build(routes=r, stored={TOKEN_KEY: "tok"}, actions=fill, queries=[q("m", "[data-hook='build-message']")])
        self.assertIn("did not say where it is", no_id["final"]["m"])
        self.assertEqual(no_id["navigations"], [])

    def test_from_prefills_the_form_from_the_hounds_spec(self):
        out = self.build(search="?from=closer", queries=[
            q("note", "[data-hook='build-from-note']"), q("note_hidden", "[data-hook='build-from-note']", "hidden"),
            q("pmin", "[data-hook='f-price-min']", "value"), q("pmax", "[data-hook='f-price-max']", "value"),
            q("books", "[data-hook='f-books']", "value"), q("lock", "[data-hook='f-lock']", "value"),
            q("preview", "[data-hook='build-preview-text']"), q("name", "[data-hook='f-name']", "value")])
        self.assertIn("/hounds/closer/spec", out["gets"])
        self.assertEqual((out["final"]["pmin"], out["final"]["pmax"], out["final"]["books"], out["final"]["lock"]),
                         ("-150", "250", "4", "30"))
        self.assertIn("Bet the underdog in moneyline (MLB)", out["final"]["preview"])
        self.assertIn("Pre-filled from that hound's rule", out["final"]["note"])
        self.assertEqual(out["final"]["name"], "")       # the builder names their own hound

    def test_a_spec_that_cannot_be_loaded_leaves_a_blank_form_and_says_so(self):
        r = routes()
        r.pop("/hounds/closer/spec")
        out = self.build(routes=r, search="?from=closer", queries=[q("note", "[data-hook='build-from-note']"),
                                                                    q("form", "[data-hook='build-form']", "count")])
        self.assertIn("the form is blank", out["final"]["note"])
        self.assertEqual(out["final"]["form"], 1)


if __name__ == "__main__":
    unittest.main()
