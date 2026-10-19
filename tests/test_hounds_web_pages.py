"""The Hounds pages' shared checks, run for real (their own scripts, their own HTML) under node against a fake DOM.

  web/hounds.html         the model leaderboard (its behaviour is in tests/test_hounds_board_pages.py)
  web/hound.html?id=      one model (its behaviour is in tests/test_hounds_board_pages.py); the chart, the AI desk
                          sections and the first-visit warm-up are checked here
  web/build-a-hound.html  the build form (side rules, a live name-and-bio card), generated from /hounds/menu

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
                self.assertRegex(text, r"(?i)paper bets only", name)
                self.assertRegex(text, r"(?i)not (betting )?advice", name)
                self.assertIn("21+", text)
                self.assertIn("Gamble responsibly.", text)
                self.assertIn("1-800-GAMBLER", text)

    def test_the_leaderboard_and_the_model_page_say_it_once_in_one_disclosure_bar(self):
        for name in ("hounds.html", "hound.html"):
            html = HTML[name]
            text = visible(html)
            with self.subTest(page=name):
                self.assertEqual(len(re.findall(r'data-hook="paper-only-notice"', html)), 1)
                self.assertEqual(len(re.findall(r"(?i)paper bets only", text)), 1, text)
                self.assertEqual(len(re.findall(r"21\+", text)), 1, text)
                self.assertEqual(len(re.findall(r"(?i)not betting advice", text)), 1, text)
                self.assertEqual(len(re.findall(r"Gamble responsibly\.", text)), 1)
                # the bar is near the top: before the first section of the page
                self.assertLess(html.index('data-hook="paper-only-notice"'), html.index("<section"))
                self.assertNotIn('data-hook="not-advice"', html)

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
                self.assertNotRegex(body, r"(?i)\b(profit|guarantee[sd]?|win rate|sure thing|beat the market)\b")
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

    def test_the_landing_page_links_to_the_leaderboard_in_its_first_screen(self):
        landing = (WEB / "landing.html").read_text(encoding="utf-8")
        first = landing[landing.index('data-hook="lb-hero"'):landing.index('data-hook="hero"')]
        self.assertRegex(first, r'<a [^>]*href="hounds.html"[^>]*>View the leaderboard')
        self.assertRegex(first, r'<a [^>]*href="build-a-hound.html"[^>]*>Build a model')


class ThePagesAreServed(unittest.TestCase):
    def test_the_asset_route_serves_each_page_script_and_stylesheet(self):
        try:
            from api import web as api_web
        except ImportError:
            self.skipTest("FastAPI not installed")
        for rel, media in (("hounds.html", "html"), ("hound.html", "html"), ("build-a-hound.html", "html"),
                           ("css/hounds.css", "css"), ("js/hounds-page.js", "js"), ("js/hounds-detail.js", "js"),
                           ("js/hounds-build.js", "js"), ("js/hounds-core.js", "js"), ("js/hounds-chart.js", "js"),
                           ("js/hounds-board.js", "js"), ("js/hounds-tickets.js", "js"), ("js/landing-board.js", "js")):
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
                self.assertRegex(res.text.lower(), r"not (betting )?advice")
        self.assertEqual(client.get("/web/css/hounds.css").status_code, 200)


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
        self.assertIn("No graded live bets yet", out["final"]["empty"])
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
            q("cat", ".hd-modelhead .hd-typechip")])
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
        self.assertEqual(f["dis_title"], "Where the desk models disagree")
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
        self.assertIn("Based on 0 graded live bets. That is a small sample.", f["sample"])

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

    def test_the_leaderboard_says_it_is_warming_up_then_fills_in_when_the_server_is_ready(self):
        r = routes()
        r["/hounds"] = self.warming(hounds=[])
        r["/hounds/stream"] = self.warming(items=[])
        r["/hounds/graveyard"] = self.warming(hounds=[])
        switch = {"/hounds": [1, [200, F.leaderboard()]], "/hounds/stream": [1, [200, F.stream()]],
                  "/hounds/graveyard": [1, [200, F.graveyard()]]}
        out = run_page("hounds", routes=r, switchAfter=switch, captureInitial=[
            q("kinds", "[data-kind='warming']", "count"), q("board", "[data-hook='hounds-table']"),
            q("empty", "[data-hook='board-empty']", "count"), q("rows", "[data-hook='hounds-list'] .hd-tr", "count")],
            actions=[dict(do="fire_timers", wait=120)], queries=[
                q("kinds", "[data-kind='warming']", "count"), q("rows", "[data-hook='hounds-list'] .hd-tr", "count"),
                q("stream", "[data-hook='stream-list'] .hd-ticket", "count"), q("grave", "[data-hook='grave-cause']", "texts")])
        first = out["captures"]["initial"]
        self.assertEqual(first["kinds"], 3)                        # board, stream, graveyard each say so
        self.assertIn("warming up", first["board"])
        self.assertEqual(first["empty"], 0)                        # NOT "No models are running yet"
        self.assertEqual(first["rows"], 0)
        self.assertEqual(out["final"]["kinds"], 0)
        self.assertEqual(out["final"]["rows"], 12)
        self.assertEqual(out["final"]["stream"], 2)
        self.assertEqual(out["final"]["grave"], ["Retired by the owner.", "Went more than 25 units under."])
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
                              q("mono", "[data-hook='build-dog-card'] .hd-mono")]),
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
        self.assertEqual(out["captures"]["fade"]["mono"], "YD")          # an initials badge, no cartoon
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
