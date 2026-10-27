"""Tonight, the signed-in home, and the guided flow around it (approved plan docs/HOUND_LOOP_PLAN.md, phase 4).

Runs web/tonight.html's real script under node against payload fixtures, plus the pure model and the tab bar.

  HOME        a member's open tickets (soonest lock first, times in the viewer's zone), last night's recap, the games the hounds are checking,
              the top hounds' tickets with Open hound / Copy it; a visitor is asked to sign in.
  CAP         a ticket at -200 or worse never shows.
  EMPTY       every empty state names a next step that is a real page.
  FAILURE     one section failing leaves the rest, and says so with a way to try again.
  PROMPTS     after creating a hound (Backtest 30 days, Unleash), after a settled loss (Ask why, Retune), after viewing a hound (Copy it).
  TAB BAR     Tonight, Hounds, My Kennel, Live, Account; Create is a + button in My Kennel and on Hounds; old deep links still exist.
  COPY        no banned word, no undefined, the legal line.
"""

from __future__ import annotations

import re
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests.test_kennel_page import SIGNED, dog, mine

BAD_TEXT = re.compile(r"undefined|NaN|\bnull\b|\[object|Infinity")
BANNED = re.compile(r"(?<![-_A-Za-z])dogs?(?![-_A-Za-z])|\bbeta\b|\bnew\b|nothing cleared the bar|\bedge\b|\bprofit|guarantee|bet ?check", re.I)
NOW = "2026-10-26T18:00:00Z"
OPEN_URL = "/hounds/{}/bets?page=1&page_size=8&segment=forward&status=open"
GRADED_URL = "/hounds/{}/bets?page=1&page_size=20&segment=forward&status=graded&sort=newest"


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def hook(h, **kw):
    return q(kw.pop("name", h), f"[data-hook='{h}']", **kw)


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def ticket(sel="Cubs ML", game="Cubs at Brewers", start="2026-10-26T23:10:00Z", result=None, price=120, **over):
    t = {"event_id": f"ev-{sel}", "market": "h2h", "selection": sel, "game": game, "price": price, "price_average": price, "start_utc": start,
         "result": result, "status": "OPEN" if result is None else "GRADED", "verdict": "play", "refused": False, "who_decided": "rule",
         "reason": "Inside the price band."}
    t.update(over)
    return t


def now_payload(mlb_games=2, nba_games=0):
    def ev(i, away, home, start):
        return {"event_id": f"e{i}", "away": away, "home": home, "start_utc": start, "in_play": False}
    fams = []
    mlb = [ev(1, "Cubs", "Brewers", "2026-10-26T23:10:00Z"), ev(2, "Dodgers", "Padres", "2026-10-27T02:10:00Z")][:mlb_games]
    fams.append({"code": "MLB", "label": "MLB", "live": [], "upcoming_24h": mlb, "next_start_utc": "2026-10-27T23:10:00Z"})
    if nba_games:
        fams.append({"code": "NBA", "label": "NBA", "live": [], "upcoming_24h": [ev(9, "Celtics", "Knicks", "2026-10-26T23:30:00Z")], "next_start_utc": "2026-10-26T23:30:00Z"})
    return {"generated_utc": NOW, "families": fams, "paper_only": True}


SEASON = {"sports": [
    {"code": "MLB", "label": "MLB", "in_season": True, "games_7d": 3, "phase": "postseason", "chip": "MLB · postseason · 3 games", "reason": ""},
    {"code": "NBA", "label": "NBA", "in_season": True, "games_7d": 58, "phase": None, "chip": "NBA · 58 games coming up", "reason": ""},
    {"code": "TENNIS", "label": "Tennis", "in_season": False, "games_7d": 0, "phase": None, "chip": "Tennis · no games this week", "reason": "Out of season."}]}


def board(kind="house"):
    p = F.leaderboard()
    for h in p["hounds"]:
        h["kind"] = kind
    return p


def routes(dogs=None, open_rows=None, graded=None, now=None, season=SEASON, kind="house", top_open=True):
    dogs = dogs if dogs is not None else [dog("u-1", "Underdog Gus", wins=2, losses=1, bets=3, units=0.4, open_bets=2)]
    r = {"/hounds/kennels/mine": mine(dogs), "/sports/now": [200, now or now_payload()], "/sports/season": [200, season], "/hounds": [200, board(kind)]}
    for d in dogs:
        r[OPEN_URL.format(d["id"])] = [200, {"items": open_rows if open_rows is not None else [ticket("Cubs ML"), ticket("Over 8.5", game="Dodgers at Padres", start="2026-10-27T02:10:00Z", price=-110)]}]
        r[GRADED_URL.format(d["id"])] = [200, {"items": graded if graded is not None else []}]
    if top_open:
        for h in F.leaderboard()["hounds"]:
            r[OPEN_URL.format(h["id"])] = [200, {"items": [ticket(f"{h['name']} pick", game=f"Game of {h['name']}", start="2026-10-26T22:05:00Z")]}]
    return r


YESTERDAY_2_1 = [ticket("Won A", result="win", start="2026-10-25T23:00:00Z", game="A at B"), ticket("Won B", result="win", start="2026-10-25T22:00:00Z", game="C at D"),
                 ticket("Lost C", result="loss", start="2026-10-25T21:00:00Z", game="E at F")]
YESTERDAY_WINS = [t for t in YESTERDAY_2_1 if t["result"] == "win"]


def page(r=None, **kw):
    kw.setdefault("queries", [])
    return run_page("tonight", routes=r if r is not None else routes(), now=NOW, tz="UTC", settleMs=250, **SIGNED if kw.pop("signed", True) else {}, **kw)


QS = [hook("tonight-next"), hook("next-primary", mode="attr", attr="href", name="primary_href"), hook("next-primary", name="primary_text"),
      hook("next-secondary", mode="attr", attr="href", name="secondary_href"), hook("next-secondary", name="secondary_text"),
      q("mine", "[data-hook='tonight-list'] [data-hook='tonight-ticket']", "texts"),
      q("recap", "[data-hook='recap-line']", "texts"), q("checking", "[data-hook='checking-game']", "texts"),
      q("top", "[data-hook='top-list'] [data-hook='tonight-ticket']", "texts"),
      q("app", "[data-hook='tonight-app']")]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHome(unittest.TestCase):
    def test_a_visitor_is_asked_to_sign_in_or_to_see_the_hounds(self):
        out = page(signed=False, queries=[hook("tonight-signin", mode="count"), hook("tonight-signin-link", mode="attr", attr="href", name="signin"),
                                           hook("tonight-browse", mode="attr", attr="href", name="browse"), hook("tonight-body", mode="hidden")])
        f = out["final"]
        self.assertEqual((f["tonight-signin"], f["signin"], f["browse"], f["tonight-body"]), (1, "index.html#/signin", "hounds.html", True))
        self.assertEqual(out["gets"], [])                       # nothing is asked of the server for a visitor

    def test_open_tickets_come_soonest_first_with_price_and_a_lock_in_the_viewers_zone(self):
        f = page(queries=QS)["final"]
        self.assertEqual(len(f["mine"]), 2)
        self.assertIn("Cubs ML", f["mine"][0])
        self.assertIn("Moneyline +120", f["mine"][0])
        self.assertIn("Locks Today 11:10 PM", f["mine"][0])
        self.assertIn("Locks Tomorrow 2:10 AM", f["mine"][1])    # 02:10Z on the 27th, the viewer's tomorrow
        self.assertIn("-110", f["mine"][1])
        self.assertIn("Underdog Gus", f["mine"][0])

    def test_the_zone_is_the_viewers_not_utc(self):
        f = run_page("tonight", routes=routes(), now=NOW, tz="America/Los_Angeles", settleMs=250, **SIGNED, queries=QS)["final"]
        self.assertIn("Locks Today 4:10 PM", f["mine"][0])

    def test_a_ticket_at_minus_200_or_worse_never_shows(self):
        rows = [ticket("Cubs ML"), ticket("Heavy chalk", price=-210, game="X at Y"), ticket("Old rule", price=-150, game="Z at W", beyond_cap=True), ticket("Edge of cap", price=-200, game="P at Q")]
        f = page(routes(open_rows=rows), queries=QS)["final"]
        self.assertEqual(len(f["mine"]), 1)
        joined = f["app"]
        for word in ("Heavy chalk", "Old rule", "Edge of cap", "-210"):
            self.assertNotIn(word, joined)

    def test_the_recap_says_what_the_hound_did_last_night_and_a_loss_offers_ask_why_and_retune(self):
        out = page(routes(graded=YESTERDAY_2_1), queries=QS + [hook("recap-ask", mode="attr", attr="href", name="ask"), hook("recap-retune", mode="attr", attr="href", name="retune"),
                                                              hook("recap-record", mode="attr", attr="href", name="rec")])
        f = out["final"]
        self.assertEqual(f["recap"], ["Underdog Gus went 2-1 last night"])
        self.assertEqual((f["ask"], f["retune"]), ("kennel.html?dog=u-1&tab=ask", "kennel.html?dog=u-1&tab=rules"))
        self.assertEqual(f["rec"], "record.html?id=u-1")
        # a loss makes the page's ONE primary prompt Ask why, with Retune beside it
        self.assertEqual((f["primary_text"], f["primary_href"]), ("Ask why", "kennel.html?dog=u-1&tab=ask"))
        self.assertEqual((f["secondary_text"], f["secondary_href"]), ("Retune", "kennel.html?dog=u-1&tab=rules"))

    def test_a_clean_night_has_no_ask_why(self):
        f = page(routes(graded=YESTERDAY_WINS), queries=QS + [hook("recap-ask", mode="count", name="ask")])["final"]
        self.assertEqual(f["recap"], ["Underdog Gus went 2-0 last night"])
        self.assertEqual(f["ask"], 0)
        self.assertEqual(f["primary_text"], "See Underdog Gus's record")      # tickets are open: check a record while they play

    def test_games_being_checked_are_listed_with_their_lock_and_which_hounds_cover_them(self):
        f = page(queries=QS)["final"]
        self.assertEqual(len(f["checking"]), 2)
        self.assertIn("Cubs at Brewers", f["checking"][0])
        self.assertIn("Locks Today 11:10 PM", f["checking"][0])
        self.assertIn("Underdog Gus", f["checking"][0])

    def test_top_hounds_tickets_have_open_hound_and_copy_it_for_a_members_hound_and_only_open_for_a_house_hound(self):
        users = page(routes(kind="user"), queries=[q("opens", "[data-hook='top-open']", "attrs", attr="href"), q("copies", "[data-hook='top-copy']", "attrs", attr="href"),
                                                   q("sub", "[data-hook='tonight-ticket-sub']", "texts")])["final"]
        self.assertTrue(users["opens"] and len(users["opens"]) == len(users["copies"]))
        self.assertTrue(all(h.startswith("hound.html?id=") for h in users["opens"]))
        self.assertTrue(all(h.startswith("build-a-hound.html?from=") for h in users["copies"]))
        self.assertTrue(any("settled" in s for s in users["sub"]))                       # the record, with its sample size
        house = page(routes(kind="house"), queries=[q("opens", "[data-hook='top-open']", "count"), q("copies", "[data-hook='top-copy']", "count")])["final"]
        self.assertGreater(house["opens"], 0)
        self.assertEqual(house["copies"], 0)                                              # a house hound has no spec to hand out

    def test_a_small_sample_is_called_out(self):
        out = run_js('import { recordLine } from "./tonight-model.js";' + chr(10) +
                     'console.log(JSON.stringify([recordLine({ record: { bets: 5, wins: 3, losses: 2 } }), recordLine({ record: { bets: 40, wins: 22, losses: 18 } }), recordLine({})]));')
        self.assertEqual(out, ["3-2 · 5 settled · small sample", "22-18 · 40 settled", "No settled bets yet"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class EveryEmptyStateNamesANextStep(unittest.TestCase):
    def test_no_hound_at_all_the_one_prompt_is_make_your_first_hound(self):
        out = page(routes(dogs=[]), queries=QS + [q("sections", "[data-hook='tonight-mine-section']", "hidden")])
        f = out["final"]
        self.assertEqual((f["primary_text"], f["primary_href"]), ("Make your first hound", "quiz.html"))
        self.assertEqual(f["secondary_href"], "hounds.html")
        self.assertTrue(f["sections"])                                  # no "your tickets" box with nothing to put in it

    def test_nothing_open_offers_a_backtest_and_the_rules_editor(self):
        out = page(routes(dogs=[dog("u-1", "Underdog Gus", bets=0)], open_rows=[]), queries=QS + [
            hook("mine-backtest", mode="attr", attr="href", name="bt"), hook("mine-rules", mode="attr", attr="href", name="rules"), hook("tonight-mine-empty", name="empty")])
        f = out["final"]
        self.assertIn("Nothing open", f["empty"])
        self.assertEqual((f["bt"], f["rules"]), ("kennel.html?dog=u-1&tab=backtest", "kennel.html?dog=u-1&tab=rules"))
        self.assertEqual((f["primary_text"], f["primary_href"]), ("Backtest 30 days", "kennel.html?dog=u-1&tab=backtest"))
        self.assertEqual(f["secondary_href"], "hounds.html")

    def test_no_games_tonight_says_which_sport_and_offers_to_add_the_best_other_one(self):
        quiet = {"generated_utc": NOW, "families": [{"code": "MLB", "label": "MLB", "live": [], "upcoming_24h": [], "next_start_utc": "2026-10-27T23:10:00Z"}]}
        out = page(routes(now=quiet), queries=[hook("tonight-checking-empty", name="empty"), hook("checking-add", mode="attr", attr="href", name="add"), hook("checking-add", name="add_text"),
                                               hook("checking-live", mode="attr", attr="href", name="live")])
        f = out["final"]
        self.assertIn("No games tonight in MLB.", f["empty"])
        self.assertIn("The next MLB game is Tomorrow 11:10 PM", f["empty"])
        self.assertIn("NBA · 58 games coming up", f["empty"])
        self.assertEqual((f["add"], f["add_text"], f["live"]), ("kennel.html?dog=u-1&tab=rules", "Add NBA", "live.html"))

    def test_no_top_hound_tickets_links_to_the_hounds(self):
        out = page(routes(top_open=False), queries=[hook("tonight-top-empty", name="empty"), hook("top-browse", mode="attr", attr="href", name="href")])
        self.assertIn("no open tickets", out["final"]["empty"])
        self.assertEqual(out["final"]["href"], "hounds.html")

    def test_nothing_settled_yet_links_to_a_hound_to_copy(self):
        out = page(routes(dogs=[dog("u-1", "Fresh Fido", bets=0)]), queries=[hook("tonight-recap-empty", name="empty"), hook("recap-find", mode="attr", attr="href", name="href")])
        self.assertEqual(out["final"]["href"], "hounds.html")
        self.assertIn("Nothing settled yet", out["final"]["empty"])

    def test_a_section_that_fails_says_so_and_the_rest_still_load(self):
        r = routes()
        r["/sports/now"] = [500, {"detail": "down"}]
        out = page(r, queries=QS + [q("failed", "[data-hook='tonight-checking'] [data-hook='section-retry']", "count")])
        f = out["final"]
        self.assertEqual(f["failed"], 1)
        self.assertEqual(len(f["mine"]), 2)
        self.assertIn("Could not load tonight's games", f["app"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureModel(unittest.TestCase):
    def js(self, body, tz="UTC"):
        return run_js('import * as M from "./tonight-model.js";' + chr(10) + body, tz=tz)

    def test_the_recap_day_is_the_viewers_day(self):
        # 03:00Z on the 26th is 8 PM on the 25th in Los Angeles; with it being 9 AM on the 26th there, that was "last night"
        body = ('const dogs = [{ id: "a", name: "A" }];' + chr(10) +
                'const g = { a: [{ result: "win", start_utc: "2026-10-26T03:00:00Z" }, { result: "loss", start_utc: "2026-10-26T04:00:00Z" }] };' + chr(10) +
                'const r = M.recapRows(dogs, g, Date.parse("2026-10-26T16:00:00Z"));' + chr(10) +
                'console.log(JSON.stringify([r.gap, r.word, r.rows[0].wins, r.rows[0].losses, M.recapSentence(r.rows[0], r.word)]));')
        self.assertEqual(self.js(body, tz="America/Los_Angeles"), [1, "last night", 1, 1, "A went 1-1 last night"])
        # the same tickets in UTC: both on the 26th, so it was "earlier today" at 16:00Z
        self.assertEqual(self.js(body, tz="UTC")[:2], [0, "earlier today"])

    def test_nothing_older_than_three_days_is_a_recap(self):
        body = ('console.log(JSON.stringify(M.recapRows([{ id: "a", name: "A" }], { a: [{ result: "win", start_utc: "2026-10-20T03:00:00Z" }] }, Date.parse("2026-10-26T16:00:00Z"))));')
        self.assertIsNone(self.js(body))

    def test_a_voided_ticket_is_not_a_win_or_a_loss(self):
        body = ('const r = M.recapRows([{ id: "a", name: "A" }], { a: [{ result: "void", start_utc: "2026-10-25T20:00:00Z" }, { result: "push", start_utc: "2026-10-25T21:00:00Z" }] }, Date.parse("2026-10-26T16:00:00Z"));' + chr(10) +
                'console.log(JSON.stringify([r.rows[0].settled, M.recapSentence(r.rows[0], r.word)]));')
        self.assertEqual(self.js(body), [1, "A went 0-0-1 last night"])

    def test_tonight_ends_at_five_in_the_morning_the_viewers_clock(self):
        body = ('const t = (iso) => new Date(M.tonightEnd(Date.parse(iso))).toISOString();' + chr(10) +
                'console.log(JSON.stringify([t("2026-10-26T18:00:00Z"), t("2026-10-27T02:00:00Z")]));')
        self.assertEqual(self.js(body), ["2026-10-27T05:00:00.000Z", "2026-10-27T05:00:00.000Z"])

    def test_a_game_after_tonight_is_not_tonight_but_is_named_as_the_next_one(self):
        body = ('const fam = [{ code: "MLB", label: "MLB", live: [], upcoming_24h: [{ event_id: "x", away: "A", home: "B", start_utc: "2026-10-27T17:00:00Z" }] }];' + chr(10) +
                'const r = M.checkingGames(fam, [{ id: "d", name: "D", sports: ["mlb"] }], Date.parse("2026-10-26T18:00:00Z"));' + chr(10) +
                'console.log(JSON.stringify([r.games.length, r.later.MLB, r.sports]));')
        self.assertEqual(self.js(body), [0, "2026-10-27T17:00:00Z", ["MLB"]])

    def test_a_sport_no_hound_bets_is_not_checked(self):
        body = ('const fam = [{ code: "NBA", label: "NBA", live: [], upcoming_24h: [{ event_id: "x", away: "A", home: "B", start_utc: "2026-10-26T23:00:00Z" }] }];' + chr(10) +
                'console.log(JSON.stringify(M.checkingGames(fam, [{ id: "d", name: "D", sports: ["mlb"] }], Date.parse("2026-10-26T18:00:00Z")).games));')
        self.assertEqual(self.js(body), [])

    def test_the_suggested_sport_is_in_season_has_games_and_is_not_already_bet(self):
        body = ('console.log(JSON.stringify([M.suggestSport(' + str(SEASON).replace("True", "true").replace("False", "false").replace("None", "null") + ', [{ id: "d", sports: ["mlb"] }]),' +
                ' M.suggestSport({ sports: [{ code: "TENNIS", in_season: false, games_7d: 0 }] }, [{ id: "d", sports: ["mlb"] }]), M.suggestSport(null, [])]));')
        a, b, c = self.js(body)
        self.assertEqual((a["code"], a["games"]), ("NBA", 58))
        self.assertIsNone(b)
        self.assertIsNone(c)

    def test_the_next_step_always_points_at_a_page_that_exists(self):
        body = ('const d = [{ id: "u-1", name: "Gus" }];' + chr(10) +
                'const lost = { word: "last night", rows: [{ dog: d[0], wins: 0, losses: 2, pushes: 0, settled: 2 }] };' + chr(10) +
                'console.log(JSON.stringify([M.nextStep({ dogs: [] }), M.nextStep({ dogs: d, recap: lost, openCount: 3 }), M.nextStep({ dogs: d, openCount: 0 }), M.nextStep({ dogs: d, openCount: 2 })]));')
        steps = self.js(body)
        self.assertEqual([s["key"] for s in steps], ["create", "lost", "idle", "open"])
        for step in steps:
            for link in (step["primary"], step["secondary"]):
                self.assertTrue((WEB / link["href"].split("?")[0]).exists(), link)
        self.assertEqual(steps[1]["primary"]["href"], "kennel.html?dog=u-1&tab=ask")

    def test_the_cap_filter_keeps_plays_only(self):
        body = ('console.log(JSON.stringify(M.keepTickets([{ price: -199 }, { price: -200 }, { price: -250 }, { price: 150 }, { price: 120, beyond_cap: true }, { price: 130, refused: true }, {}]).map((t) => t.price)));')
        self.assertEqual(self.js(body), [-199, 150, None])


@unittest.skipUnless(HAS_NODE, "node not installed")
class NextStepsAtTheEndOfEveryFlow(unittest.TestCase):
    def test_after_creating_a_hound_the_builder_says_backtest_30_days_then_unleash(self):
        from tests import test_hounds_builder_web as B
        text = "bet home underdogs between +120 and +200 when they're on 2+ days rest. max 2 bets a day"
        r = B.base_routes(**{"POST /hounds/english": [200, B.english_answer(text)], "POST /hounds": [200, {"hound": {"id": "u-x", "name": "Pup Test"}}]})
        out = B.build(r, **SIGNED, actions=[
            dict(do="set", sel="[data-hook='english-input']", value=text), dict(do="click", sel="[data-hook='english-go']", wait=300)]
            + B.StepThreeAndSaving.NAME + [dict(do="click", sel="[data-color='mint']", wait=30), dict(do="click", sel="[data-badge='bolt']", wait=30),
                                 dict(do="click", sel="[data-hook='build-submit']", wait=200)],
            queries=[q("bt", "[data-hook='next-backtest']", "attr", attr="href"), q("bt_text", "[data-hook='next-backtest']"),
                     q("un", "[data-hook='next-unleash']", "attr", attr="href"), q("see", "[data-hook='new-dog-link']", "attr", attr="href")])
        f = out["final"]
        self.assertEqual((f["bt"], f["bt_text"], f["un"]), ("kennel.html?dog=u-x&tab=backtest", "Backtest 30 days", "kennel.html?dog=u-x&tab=fire"))
        self.assertIn("u-x", f["see"])

    def test_after_a_settled_loss_the_studios_record_offers_ask_why_and_retune(self):
        from tests.test_hound_sheet import BET_URL, OPEN_URL as SHEET_OPEN, StudioHelpers, rows
        helper = type("H", (StudioHelpers,), {})()
        lost = rows(2, 0)                                           # settled losses
        out = helper.sheet(dogs=[dog("u-1", "Underdog Gus", wins=0, losses=2, bets=2)], extra={BET_URL: [200, {"items": lost, "total": 2}]}, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", wait=300, label="open", capture=[q("n", "[data-hook='studio-loss-next']", "count"), q("ask", "[data-hook='studio-ask-why']"),
                                                                                              q("retune", "[data-hook='studio-retune']")]),
            dict(do="click", sel="[data-hook='studio-ask-why']", wait=200, label="ask", capture=[q("sel", "[role='tab'][aria-selected='true']", "texts")]),
            dict(do="click", sel="[role='tab'][data-tab='record']", wait=200, label="back"),
            dict(do="click", sel="[data-hook='studio-retune']", wait=300, label="retune", capture=[q("sel", "[role='tab'][aria-selected='true']", "texts")])])
        c = out["captures"]
        self.assertEqual((c["open"]["n"], c["open"]["ask"], c["open"]["retune"]), (1, "Ask why", "Retune"))
        self.assertEqual(c["ask"]["sel"], ["Ask"])
        self.assertEqual(c["retune"]["sel"], ["Rules"])

    def test_a_win_as_the_latest_settled_ticket_has_no_loss_prompt(self):
        from tests.test_hound_sheet import BET_URL, StudioHelpers, rows
        helper = type("H", (StudioHelpers,), {})()
        won = rows(2, 0)
        for t in won:
            t["result"], t["units"] = "win", 0.9
        out = helper.sheet(dogs=[dog("u-1", "Underdog Gus", wins=2, losses=0, bets=2)], extra={BET_URL: [200, {"items": won, "total": 2}]}, actions=[
            dict(do="click", sel="[data-hook='dog-avatar']", wait=300, label="open", capture=[q("n", "[data-hook='studio-loss-next']", "count")])])
        self.assertEqual(out["captures"]["open"]["n"], 0)

    def test_after_viewing_a_members_hound_that_is_not_yours_the_primary_button_is_copy_it(self):
        from tests import test_hounds_interact_web as _IW
        routes_ = _IW.dog_routes(owner=False, signed_in=False, kind="user")
        out = _IW.page(routes_, stored={}, queries=[q("copy_hidden", "[data-hook='copy-cta']", "hidden"), q("copy_href", "[data-hook='copy-cta']", "attr", attr="href"),
                                        q("copy", "[data-hook='copy-cta']"), q("create_class", "[data-hook='create-cta']", "attr", attr="class")])
        f = out["final"]
        self.assertIs(f["copy_hidden"], False)
        self.assertEqual(f["copy"], "Copy this hound")
        self.assertTrue(f["copy_href"].startswith("build-a-hound.html?from="))
        self.assertNotIn("btn--primary", f["create_class"])          # one primary: Copy leads, Create steps back

    def test_a_house_hound_or_your_own_has_no_copy_button(self):
        from tests import test_hounds_interact_web as _IW
        for kw in (dict(owner=False, signed_in=False, kind="house"), dict(owner=True, signed_in=True, kind="user")):
            with self.subTest(**kw):
                out = _IW.page(_IW.dog_routes(**kw), stored={} if not kw["signed_in"] else None, queries=[q("copy_hidden", "[data-hook='copy-cta']", "hidden")])
                self.assertIs(out["final"]["copy_hidden"], True)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheTabBar(unittest.TestCase):
    QS = [q("tabs", "[data-hook='site-tabbar'] .lh-tab", "texts"), q("hrefs", "[data-hook='site-tabbar'] .lh-tab", "attrs", attr="href"),
          q("current", "[data-hook='site-tabbar'] [aria-current='page']", "texts"), q("links", ".lh-nav__links a", "texts"),
          q("primary", "[data-hook='site-tabbar'] .lh-tab--primary", "texts")]

    def nav(self, page_html, path, **kw):
        return run_page("nav", page_html=page_html, pathname=f"/web/{page_html}", queries=self.QS, **kw)["final"]

    def test_a_member_gets_tonight_hounds_my_kennel_live_account_and_no_create(self):
        f = self.nav("tonight.html", "", **SIGNED)
        self.assertEqual(f["tabs"], ["Tonight", "Hounds", "My Kennel", "Live", "Account"])
        self.assertEqual(f["hrefs"], ["tonight.html", "hounds.html", "kennel.html", "live.html", "index.html#/account"])
        self.assertEqual((f["current"], f["primary"]), (["Tonight"], ["My Kennel"]))
        self.assertEqual(f["links"], ["Tonight", "Hounds", "Live"])
        self.assertNotIn("Create", f["tabs"] + f["links"])

    def test_the_desktop_bar_and_the_phone_bar_name_the_same_places(self):
        f = self.nav("hounds.html", "", **SIGNED)
        self.assertEqual([t for t in f["tabs"] if t not in ("My Kennel", "Account")], f["links"] + [])
        self.assertEqual(f["current"], ["Hounds"])

    def test_every_place_lights_on_its_own_page(self):
        for page_html, want in (("tonight.html", "Tonight"), ("hounds.html", "Hounds"), ("kennel.html", "My Kennel"), ("live.html", "Live"),
                                ("record.html", "Hounds"), ("quiz.html", "My Kennel"), ("build-a-hound.html", "My Kennel")):
            with self.subTest(page=page_html):
                self.assertEqual(self.nav(page_html, "", **SIGNED)["current"], [want])

    def test_the_visitors_bar_keeps_its_one_button(self):
        f = self.nav("hounds.html", "")
        self.assertEqual(f["tabs"], ["Hounds", "Live", "Sign in", "Make your first hound"])

    def test_create_is_a_plus_button_in_my_kennel_and_on_hounds(self):
        k = run_page("kennel", routes={"/hounds/kennels/mine": mine([dog()])}, **SIGNED, queries=[q("t", "[data-hook='kennel-build']"), q("h", "[data-hook='kennel-build']", "attr", attr="href")])
        self.assertEqual(k["final"], {"t": "+ Create a hound", "h": "quiz.html"})
        self.assertIn('data-hook="build-cta" aria-label="Create a hound">+ Create a hound</a>', read("hounds.html"))
        self.assertIn('href="quiz.html" data-hook="build-cta"', read("hounds.html"))

    def test_old_deep_links_keep_working(self):
        for name in ("quiz.html", "build-a-hound.html", "kennel.html", "hounds.html", "hound.html", "live.html", "record.html", "kennels.html", "learning.html", "graveyard.html", "index.html", "landing.html"):
            self.assertTrue((WEB / name).exists(), name)
        out = run_js('import { normalizePlace, highlight } from "./nav.js";' + chr(10) + 'console.log(JSON.stringify(["leaderboard", "kennels", "create", "build", "camp", "signin"].map((k) => highlight(normalizePlace(k)))));')
        self.assertEqual(out, ["hounds", "hounds", "mykennel", "mykennel", "mykennel", "account"])
        # an old page that still says data-current="leaderboard" lights Hounds
        f = run_page("nav", page_html="hounds.html", pathname="/web/hounds.html", queries=self.QS, **SIGNED)["final"]
        self.assertEqual(f["current"], ["Hounds"])

    def test_the_stylesheet_still_draws_five_columns_on_a_phone(self):
        css = read("css/lhnav.css")
        self.assertIn("grid-template-columns: repeat(5, 1fr)", css)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCopy(unittest.TestCase):
    def test_no_banned_word_no_undefined_on_a_full_page(self):
        out = page(routes(graded=YESTERDAY_2_1, kind="user"), queries=[q("app", "[data-hook='tonight-app']")])
        text = out["final"]["app"]
        self.assertNotRegex(text, BAD_TEXT)
        self.assertNotRegex(text, BANNED)
        for word in ("profit", "edge", "guarantee", "lock of", "sure thing"):
            self.assertNotIn(word, text.lower())

    def test_the_static_page_is_clean_and_carries_the_legal_line_and_no_inline_script(self):
        html = read("tonight.html")
        visible = re.sub(r"<!--.*?-->", "", html, flags=re.S)
        visible = re.sub(r"<[^>]+>", " ", visible)
        self.assertNotRegex(visible, BANNED)
        self.assertIn("21+", html)
        self.assertIn("1-800-GAMBLER", html)
        self.assertIn("Paper", html)
        scripts = re.findall(r"<script\b[^>]*>", html)
        self.assertTrue(scripts and all('type="module"' in s and "src=" in s for s in scripts), scripts)
        self.assertIn('data-current="tonight"', html)

    def test_the_page_follows_the_canonical_nav_block_and_loads_its_own_files(self):
        html = read("tonight.html")
        self.assertIn('<script type="module" src="js/nav.js"></script>', html)
        self.assertIn('href="css/lhnav.css"', html)
        self.assertTrue((WEB / "css" / "tonight.css").exists())
        self.assertTrue((WEB / "js" / "tonight.js").exists() and (WEB / "js" / "tonight-model.js").exists())


if __name__ == "__main__":
    unittest.main()
