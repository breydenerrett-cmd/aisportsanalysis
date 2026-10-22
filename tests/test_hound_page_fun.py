"""The hound page's fun pass (owner request 2026-10-21): "What I'd play right now", the feed, the ticket switch, filters and sorts.

SERVER HALF (plain Python, no FastAPI, no node): src/hounds/interact/right_now.py and contract.refine_bets.
  - the right-now pick uses only the current board and the hound's own rule: a started game and a -200 price never appear,
    the order is the hound's own rank order, the meter is rank-based and says it is not a win probability;
  - nothing fits -> the next game it will look at; the in-play setting is read defensively;
  - the voice is read off the persona or the rule.
PAGE HALF (the real page script under node, skipped without node): the card cycles with "Show me another", the empty state, the stake
  is at the viewer's unit size, every server string is escaped, the outcome filter and the sort go to the server, the Open | Settled switch,
  and the copy never says lock, guaranteed, edge, value, profit or the canine word.
"""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.hounds import contract
from src.hounds.interact import common, right_now
from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_js
from tests.test_hounds_interact_web import HID, Payloads, dog_routes, hook, page, q
from tests.test_hounds_interact_fire import NOW, dog_of

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"\block(ed|s)?\b|guarantee|\bedge\b|\bvalue\b|\bprofit|\bev\b|expected value|sure thing|bet check|beta", re.I)
DOG = re.compile(r"(?<![-_A-Za-z])[Dd]ogs?(?![-_A-Za-z])")


def pick(event, selection, price, minutes, rank=None, **over):
    start = NOW + timedelta(minutes=minutes)
    base = {"event_id": event, "game": f"Team {event} @ Other {event}", "sport": "MLB", "market": "moneyline",
            "market_label": "Moneyline", "side": "away", "selection": selection, "line": None, "price_average": price,
            "price_best": price, "best_book": "book_a", "n_books": 5, "start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "minutes_to_start": minutes, "day": "2026-10-20", "day_label": "Today", "stale": False, "board_age_minutes": 10,
            "over_daily_limit": False, "reason": "because", "player": None,
            "manual": {"can_record": True, "blocked": None}}
    if rank is not None:
        base["rank_in_day"] = rank
    base.update(over)
    return base


def payload(picks, games=None):
    return {"picks": picks, "games": games or [], "games_considered": len(picks), "viewer_is_owner": True,
            "manual_remaining_today": 5, "next_game": None, "live_elsewhere": None}


def build(picks, dog=None, **kw):
    return right_now.build(dog or dog_of(hid=HID), 1, now=NOW, payload=payload(picks, kw.get("games")))


class TheRightNowAnswer(unittest.TestCase):
    def test_a_game_that_started_and_a_price_of_minus_200_or_worse_never_appear(self):
        out = build([pick("a", "Started", +110, -30), pick("b", "Cap", -200, 60), pick("c", "Worse", -250, 60),
                     pick("d", "Fine", +130, 90), pick("e", "No price", None, 90)])
        self.assertEqual([c["selection"] for c in out["candidates"]], ["Fine"])
        self.assertTrue(all(c["price_average"] > -200 for c in out["candidates"]))

    def test_the_order_is_the_hounds_own_rank_and_the_meter_is_rank_based(self):
        out = build([pick("a", "Second", +150, 60, rank=1), pick("b", "First", +120, 120, rank=0), pick("c", "Third", +180, 30, rank=2)])
        self.assertEqual([c["selection"] for c in out["candidates"]], ["First", "Second", "Third"])
        self.assertEqual([c["fit"] for c in out["candidates"]], [100, 67, 33])
        self.assertEqual([c["rank"] for c in out["candidates"]], [1, 2, 3])
        self.assertIn("not a chance of winning", out["fit_definition"])
        self.assertNotRegex(json.dumps(out), r"win_prob|probability_of|\bedge\b|\bev\b")

    def test_a_classic_hound_ranks_by_the_earliest_game(self):
        out = build([pick("a", "Late", +150, 200), pick("b", "Early", +120, 40)])
        self.assertEqual([c["selection"] for c in out["candidates"]], ["Early", "Late"])
        self.assertEqual(out["rank_by"], "earliest_lock")

    def test_nothing_fits_names_the_next_game_and_when(self):
        game = {"event_id": "z", "game": "Mets @ Braves", "start_utc": (NOW + timedelta(hours=26)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        out = build([], games=[game])
        self.assertTrue(out["nothing"])
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["next_look"]["game"], "Mets @ Braves")
        self.assertEqual(out["next_look"]["starts_in_minutes"], 26 * 60)

    def test_nothing_and_no_games_has_no_next_look_but_still_answers(self):
        out = build([])
        self.assertTrue(out["nothing"])
        self.assertIsNone(out["next_look"])

    def test_the_in_play_setting_is_read_defensively(self):
        started = pick("a", "Live one", +140, -20, in_play=True)
        off = build([started, pick("b", "Pre", +120, 50)])
        self.assertEqual([c["selection"] for c in off["candidates"]], ["Pre"])
        self.assertFalse(off["bets_in_play"])
        dog = dog_of(hid=HID)
        dog.hound["spec"] = dict(dog.hound["spec"], bet_in_play=True)
        on = build([started, pick("b", "Pre", +120, 50)], dog=dog)
        self.assertTrue(on["bets_in_play"])
        self.assertIn("Live one", [c["selection"] for c in on["candidates"]])
        # a started game the engine did not mark in play is never offered, setting or not
        plain = build([pick("a", "Started", +140, -20)], dog=dog)
        self.assertEqual(plain["candidates"], [])
        self.assertFalse(right_now.bets_in_play({"bet_in_play": "yes"}))
        self.assertFalse(right_now.bets_in_play(None))

    def test_a_visitor_cannot_add_a_manual_pick_but_the_flag_is_the_servers(self):
        picks = [pick("a", "X", +120, 50, manual={"can_record": False, "blocked": "only the owner can record a manual pick"})]
        out = right_now.build(dog_of(hid=HID), None, now=NOW, payload=dict(payload(picks), viewer_is_owner=False))
        self.assertFalse(out["viewer_is_owner"])
        self.assertFalse(out["candidates"][0]["manual"]["can_record"])

    def test_the_real_fire_answer_flows_through(self):
        out = right_now.build(dog_of(hid=HID), 1, now=NOW, payload=Payloads.fire_payload(owner=True))
        self.assertEqual(len(out["candidates"]), 1)
        c = out["candidates"][0]
        self.assertEqual((c["selection"], c["price_average"], c["fit"]), ("Boston Red Sox to win", 120, 100))
        self.assertTrue(out["paper_only"])
        self.assertIn("21+", out["not_advice"])

    def test_the_voice_comes_from_the_persona_or_the_rule(self):
        house = common.Dog(id="x", kind=common.KIND_HOUSE, name="X")
        self.assertEqual(right_now.voice_key(house, {"vibe": "psychic"}), "mystic")
        self.assertEqual(right_now.voice_key(house, {"vibe": "chaos"}), "chaos")
        self.assertEqual(right_now.voice_key(house, None), "generic")
        under = dog_of(hid=HID)
        under.hound["spec"] = dict(under.hound["spec"], side_rule="underdog")
        self.assertEqual(right_now.voice_key(under), "underdog")
        chalk = dog_of(hid=HID)
        chalk.hound["spec"] = dict(chalk.hound["spec"], side_rule="favourite")
        self.assertEqual(right_now.voice_key(chalk), "chalk")
        for key in right_now.VOICES:
            self.assertIn(key, right_now.VOICE_LABELS)


class _Row:
    def __init__(self, result, units, price, date="2026-10-01"):
        self.result, self.units, self.price, self.price_average, self.date = result, units, price, price, date


class TheTicketFilterAndSort(unittest.TestCase):
    ROWS = [_Row("win", 1.2, 120), _Row("loss", -1.0, -110), _Row("win", 2.5, 250), _Row("push", 0.0, 100), _Row("loss", -2.0, 180),
            _Row("win", 0.9, -105)]

    def test_outcome_keeps_only_that_grade(self):
        for word, want in (("won", 3), ("lost", 2), ("push", 1)):
            self.assertEqual(len(contract.refine_bets(self.ROWS, word)), want, word)
        self.assertEqual(len(contract.refine_bets(self.ROWS, None)), 6)
        self.assertEqual(len(contract.refine_bets(self.ROWS, "nonsense")), 6)

    def test_sorts(self):
        wins = [r.units for r in contract.refine_bets(self.ROWS, None, "biggest_win")]
        self.assertEqual(wins[:3], [2.5, 1.2, 0.9])
        losses = [r.units for r in contract.refine_bets(self.ROWS, None, "biggest_loss")]
        self.assertEqual(losses[:2], [-2.0, -1.0])
        prices = [r.price for r in contract.refine_bets(self.ROWS, None, "price")]
        self.assertEqual(prices[:3], [250, 180, 120])
        self.assertEqual(contract.refine_bets(self.ROWS, None, "newest"), self.ROWS)

    def test_filter_and_sort_together(self):
        out = contract.refine_bets(self.ROWS, "won", "biggest_win")
        self.assertEqual([r.units for r in out], [2.5, 1.2, 0.9])


class TheCopyIsCleanAndLive(unittest.TestCase):
    FILES = ["hound-lines.js", "hound-rightnow.js", "hound-feed.js", "hound-hero.js", "hound-money.js"]

    def test_no_banned_word_in_the_new_modules_or_their_markup(self):
        for name in self.FILES:
            text = (WEB / "js" / name).read_text(encoding="utf-8")
            # the doc comments say what the copy may not do; only the strings a person reads are checked
            strings = re.findall(r'"([^"\n]{3,})"|`([^`\n]{3,})`', re.sub(r"/\*.*?\*/", "", text, flags=re.S))
            for a, b in strings:
                s = a or b
                if s.startswith(("data-", "hn-", "hh-", "hf-", "./", "now-")) or "=>" in s:
                    continue
                self.assertIsNone(BANNED.search(s), (name, s))
                self.assertIsNone(DOG.search(s), (name, s))
        html = (WEB / "hound.html").read_text(encoding="utf-8")
        card = html[html.index('data-hook="right-now"'):html.index("<!-- TABS")]
        self.assertIsNone(BANNED.search(re.sub(r"<!--.*?-->", "", card, flags=re.S)))
        self.assertEqual(html.count('data-hook="hound-footer"'), 1)
        self.assertNotIn("<script>", html.replace('<script type="module"', ""))

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_every_template_line_is_clean_and_stable(self):
        out = run_js("""import * as L from "%s";
const all = L.allTemplates();
const lines = [];
for (const v of L.VOICES) {
  lines.push(L.pickLine(v, { selection: "Boston Red Sox to win", priceText: "+120" }, "e1"));
  lines.push(L.nothingLine(v, { game: "A @ B", whenText: "starts in 2 h" }, "x"));
  lines.push(L.nothingLine(v, null, "x"));
  lines.push(L.settledLine(v, { result: "won", selection: "A", priceText: "+120", moneyText: "+$25" }, "k"));
  lines.push(L.settledLine(v, { result: "lost", selection: "A", priceText: "+120", moneyText: "-$25" }, "k"));
  lines.push(L.settledLine(v, { result: "push", selection: "A", priceText: "+120" }, "k"));
  lines.push(L.openLine(v, { selection: "A", priceText: "+120", game: "A @ B" }, "k"));
  lines.push(L.streakLine(v, "W", 3), L.streakLine(v, "L", 2));
  for (const f of [{ retired: true }, { streakKind: "W", streakLen: 4 }, { streakKind: "L", streakLen: 3 }, { open: 2 }, { graded: 0 }, { graded: 5 }]) lines.push(L.moodLine(v, f));
}
console.log(JSON.stringify({ all, lines, again: L.pickLine("chaos", { selection: "X", priceText: "+100" }, "e1") === L.pickLine("chaos", { selection: "X", priceText: "+100" }, "e1"),
  unknown: L.pickLine("nope", { selection: "X", priceText: "+100" }, "e1") === L.pickLine("generic", { selection: "X", priceText: "+100" }, "e1") }));
""" % (WEB / "js" / "hound-lines.js").as_uri())
        for text in out["all"] + out["lines"]:
            self.assertIsNone(BANNED.search(text), text)
            self.assertIsNone(DOG.search(text), text)
        self.assertTrue(out["again"] and out["unknown"])
        self.assertTrue(all(t.strip() for t in out["lines"]))


def now_route(candidates, **over):
    body = {"dog_id": HID, "dog_name": "Closer", "kind": "user", "as_of": "2026-10-20T21:30:00Z", "voice": "underdog",
            "voice_label": "Underdog hunter", "rank_by": "longest_price", "rank_words": "the longest price",
            "fit_definition": "How strongly the game fits this hound's own rule, by its place among the games that fit tonight. It is not a chance of winning.",
            "candidates": candidates, "nothing": not candidates, "games_considered": len(candidates), "bets_in_play": False,
            "viewer_is_owner": True, "manual_remaining_today": 5, "next_look": None, "next_game": None, "live_elsewhere": None,
            "paper_only": True, "not_advice": "Paper pick, not advice. 21+."}
    body.update(over)
    return body


def cand(n, selection, price=120, total=3, **over):
    base = {"event_id": f"e{n}", "market": "moneyline", "market_label": "Moneyline", "player": None, "game": f"Away{n} @ Home{n}",
            "sport": "MLB", "side": "away", "selection": selection, "line": None, "price_average": price, "price_best": price,
            "best_book": "b", "n_books": 5, "start_utc": "2026-10-21T23:10:00Z", "minutes_to_start": 100 + n, "day_label": "Today",
            "stale": False, "board_age_minutes": 10, "in_play": False, "over_daily_limit": False, "stake_units": 2.0, "rank": n,
            "of": total, "fit": round(100 * (total - n + 1) / total), "fit_text": "The top of the board" if n == 1 else f"Number {n} of {total} on its board",
            "lead": "", "reason": "because", "manual": {"can_record": True, "blocked": None}}
    base.update(over)
    return base


def with_now(body, **kw):
    r = dog_routes(**kw)
    r[f"/hounds/{HID}/right-now"] = [200, body]
    return r


NOW_Q = [q("quote", hook("now-quote")), q("sel", hook("now-selection")), q("price", hook("now-price")), q("stake", hook("now-stake")),
         q("start", hook("now-start")), q("count", hook("now-count")), q("hidden", hook("right-now"), "hidden"),
         q("paper", hook("now-paper")), q("fit", hook("now-meter"), "attr", attr="data-fit")]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRightNowCardOnThePage(unittest.TestCase):
    CANDS = [cand(1, "Boston Red Sox to win", 150), cand(2, "Chicago Cubs to win", 130), cand(3, "Over 8.5", 105)]

    def test_the_card_shows_the_top_pick_in_the_hounds_voice(self):
        f = page(with_now(now_route(self.CANDS)), queries=NOW_Q)["final"]
        self.assertFalse(f["hidden"])
        self.assertEqual((f["sel"], f["price"]), ("Boston Red Sox to win", "+150"))
        self.assertIn("Boston Red Sox to win at +150", f["quote"])
        self.assertIn("Starts in 1 h 41 min", f["start"])
        self.assertIn("Paper pick, not advice", f["paper"])
        self.assertIn("21+", f["paper"])
        self.assertEqual(f["count"], "1 of 3 that fit")

    def test_show_me_another_cycles_through_every_candidate_and_wraps(self):
        click = dict(do="click", sel=hook("now-another"))
        out = page(with_now(now_route(self.CANDS)), actions=[dict(click, label="a", capture=[q("sel", hook("now-selection"))]),
                                                              dict(click, label="b", capture=[q("sel", hook("now-selection"))]),
                                                              dict(click, label="c", capture=[q("sel", hook("now-selection"))])])
        seen = [out["captures"][k]["sel"] for k in "abc"]
        self.assertEqual(seen, ["Chicago Cubs to win", "Over 8.5", "Boston Red Sox to win"])

    def test_the_meter_is_labelled_how_sure_and_defined_as_not_a_win_chance(self):
        out = page(with_now(now_route(self.CANDS)), queries=[q("label", ".hn-meter__label"), q("def", hook("now-fit-def")), q("fit", hook("now-meter"), "attr", attr="data-fit"),
                                                             q("pips", ".hn-pip--on", "count")])
        f = out["final"]
        self.assertEqual(f["label"], "How sure it is")
        self.assertIn("not a win probability", f["def"])
        self.assertEqual((f["fit"], f["pips"]), ("100", 5))

    def test_the_card_never_shows_minus_200_or_worse_even_if_the_server_sent_one(self):
        bad = [cand(1, "Heavy favourite", -210), cand(2, "Exactly the cap", -200), cand(3, "Fine", 110)]
        out = page(with_now(now_route(bad)), queries=NOW_Q + [q("all", hook("now-bet"), "count")])
        f = out["final"]
        self.assertEqual(f["sel"], "Fine")
        self.assertEqual(f["all"], 1)
        self.assertIsNone(f["count"])        # one candidate: no "1 of N" line

    def test_the_empty_state_speaks_in_voice_and_names_the_next_game(self):
        nxt = {"game": "Mets @ Braves", "event_id": "z", "start_utc": "2026-10-22T23:10:00Z", "lock_utc": None,
               "locks_in_minutes": 90, "starts_in_minutes": 1500}
        out = page(with_now(now_route([], next_look=nxt)), queries=[q("nothing", hook("now-nothing")), q("next", hook("now-next")),
                                                                    q("bet", hook("now-bet"), "count"), q("another", hook("now-another"), "count"),
                                                                    q("add", hook("now-add"), "count"), q("paper", hook("now-paper"))])
        f = out["final"]
        self.assertIn("Mets @ Braves", f["nothing"])
        self.assertIn("starts in 25 h", f["nothing"])
        self.assertIn("1 h 30 min", f["next"])
        self.assertEqual((f["bet"], f["another"], f["add"]), (0, 0, 0))
        self.assertIn("Paper pick", f["paper"])

    def test_a_hound_with_no_rule_to_run_hides_the_card(self):
        r = dog_routes()
        r[f"/hounds/{HID}/right-now"] = [422, {"detail": {"error": "not_firable"}}]
        out = page(r, queries=[q("hidden", hook("right-now"), "hidden")])
        self.assertTrue(out["final"]["hidden"])

    def test_the_stake_is_at_the_viewers_unit_size(self):
        route = with_now(now_route(self.CANDS))
        from tests.hounds_web_runner import PIN_REFERENCE
        ten = page(route, queries=[q("stake", hook("now-stake"))], viewer=PIN_REFERENCE)["final"]["stake"]
        hundred = page(route, queries=[q("stake", hook("now-stake"))], viewer={"mode": "fixed", "unit_usd": 100, "pct": None, "start_usd": 10000})["final"]["stake"]
        pct = page(route, queries=[q("stake", hook("now-stake"))], viewer={"mode": "percent", "unit_usd": None, "pct": 2, "start_usd": 5000})["final"]["stake"]
        self.assertEqual((ten, hundred, pct), ("Stake $20", "Stake $200", "Stake 4% of bankroll"))

    def test_every_server_string_is_escaped(self):
        evil = '<img src=x onerror="alert(1)">'
        route = with_now(now_route([cand(1, evil, 120, game=f"<b>{evil}</b>", reason=evil, best_book=evil)], dog_name=evil, voice_label=evil))
        out = page(route, queries=NOW_Q + [q("imgs", "[data-hook='right-now'] img", "count"), q("bold", "[data-hook='right-now'] b", "count"),
                                           q("game", hook("now-game"))])
        f = out["final"]
        self.assertEqual(f["sel"], evil)
        self.assertEqual((f["imgs"], f["bold"]), (0, 0))
        self.assertIn("<b>", f["game"])

    def test_add_as_a_manual_pick_uses_the_existing_route_and_is_owner_only(self):
        out = page(with_now(now_route(self.CANDS)), actions=[dict(do="click", sel=hook("now-add"), wait=80, capture=[q("status", hook("now-status")), q("add", hook("now-add"), "count")])])
        self.assertEqual([p["url"] for p in out["posts"]], [f"/hounds/{HID}/manual"])
        self.assertEqual(out["posts"][0]["body"], {"event_id": "e1", "market": "moneyline"})
        self.assertIn("Added as a manual pick at +120", out["captures"]["0"]["status"])
        visitor = page(with_now(now_route(self.CANDS, viewer_is_owner=False)), queries=[q("add", hook("now-add"), "count")])
        self.assertEqual(visitor["final"]["add"], 0)

    def test_a_double_tap_on_add_posts_once(self):
        # the button is disabled synchronously, before the request is awaited, and removed once it succeeds: a second tap has nothing to hit.
        src = (WEB / "js" / "hound-rightnow.js").read_text(encoding="utf-8")
        handler = src[src.index('add.addEventListener("click"'):]
        self.assertLess(handler.index('add.setAttribute("disabled"'), handler.index("await post("))
        self.assertIn("clearNode(actions)", handler[:handler.index("} catch")])
        # and the server holds the line if two taps still arrive together: one manual ticket per hound, game and market
        from src.hounds.interact import manual
        self.assertEqual(manual.manual_bet_id("h", "e", "moneyline"), manual.manual_bet_id("h", "e", "moneyline"))

    def test_a_blocked_pick_says_why_and_a_second_side_is_left_to_the_server_guard(self):
        blocked = [cand(1, "X", 120, manual={"can_record": False, "blocked": "this hound already has the other side of this game"})]
        out = page(with_now(now_route(blocked)), queries=[q("add", hook("now-add"), "count"), q("why", hook("now-blocked"))])
        self.assertEqual(out["final"]["add"], 0)
        self.assertIn("already has the other side", out["final"]["why"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheHeroFeedAndTickets(unittest.TestCase):
    def test_the_hero_mood_line_is_in_the_hounds_voice_and_the_capital_row_exists(self):
        out = page(with_now(now_route([cand(1, "A", 120)], voice="chalk")), queries=[q("mood", hook("hound-mood")), q("spark", hook("hound-spark"), "count"),
                                                                                    q("change", hook("hound-change")), q("cap", hook("hound-capital"), "count")])
        f = out["final"]
        self.assertTrue(f["mood"])
        self.assertEqual((f["spark"], f["cap"]), (1, 1))
        self.assertRegex(f["change"], r"last 24 hours")

    def test_the_feed_is_real_tickets_only_and_dollars_are_at_the_viewers_size(self):
        route = with_now(now_route([cand(1, "A", 120)]))
        out10 = page(route, queries=[q("items", hook("feed-item"), "texts"), q("empty", hook("feed-empty"), "count")])["final"]
        out100 = page(route, queries=[q("items", hook("feed-item"), "texts")], viewer={"mode": "fixed", "unit_usd": 100, "pct": None, "start_usd": 10000})["final"]
        self.assertTrue(out10["items"], "the fixture hound has graded tickets")
        money10 = re.findall(r"[+-]\$[\d,.]+", " ".join(out10["items"]))
        money100 = re.findall(r"[+-]\$[\d,.]+", " ".join(out100["items"]))
        self.assertTrue(money10 and len(money10) == len(money100))
        self.assertNotEqual(money10, money100)
        self.assertTrue(all("on paper" in t for t in out10["items"] if re.search(r"[+-]\$", t)))

    def test_the_feed_says_so_when_the_hound_has_done_nothing(self):
        route = with_now(now_route([]))
        detail = route[f"/hounds/{HID}"][1]
        detail["bets"] = dict(detail["bets"], items=[], total=0)
        detail["open_bets"] = 0
        detail["form"] = dict(detail.get("form") or {}, streak=None)
        route[f"/hounds/{HID}/bets"] = [200, {"hound_id": HID, "items": [], "page": 1, "page_size": 20, "total": 0, "pages": 1}]
        out = page(route, queries=[q("empty", hook("feed-empty"))])
        self.assertIn("Nothing on the card yet", out["final"]["empty"])

    def test_the_switch_filter_and_sort_go_to_the_server(self):
        route = with_now(now_route([]))
        out = page(route, actions=[
            dict(do="click", sel="[data-hook='bets-outcome'] [data-outcome='won']", label="won", wait=80, capture=[
                q("pressed", "[data-hook='bets-outcome'] .hd-seg", "attrs", attr="aria-pressed")]),
            dict(do="set", sel=hook("bets-sort"), value="biggest_win", label="sort", wait=80),
            dict(do="click", sel="[data-hook='bets-outcome'] [data-outcome='lost']", label="lost", wait=80),
            dict(do="click", sel="[data-hook='bets-outcome'] [data-outcome='all']", label="all", wait=80)])
        bets = [u for u in out["gets"] if "/bets?" in u and "status=graded" in u]
        self.assertTrue(any("outcome=won" in u and "sort" not in u for u in bets), bets)
        self.assertTrue(any("outcome=won" in u and "sort=biggest_win" in u for u in bets), bets)
        self.assertTrue(any("outcome=lost" in u and "sort=biggest_win" in u for u in bets), bets)
        self.assertTrue(any("outcome" not in u and "sort=biggest_win" in u for u in bets), bets)
        self.assertEqual(out["captures"]["won"]["pressed"], ["false", "true", "false", "false"])
        # the first load asks with neither, as before
        self.assertTrue(any("outcome" not in u and "sort" not in u for u in bets))

    def test_open_or_settled_switch_shows_one_list_at_a_time(self):
        route = with_now(now_route([]))
        detail = route[f"/hounds/{HID}"][1]
        detail["open_bets"] = 2
        panes = [q("open", hook("hound-today-section"), "hidden"), q("done", hook("hound-bets-section"), "hidden"),
                 q("pressed", hook("tickets-switch") + " .hd-seg", "attrs", attr="aria-pressed"), q("labels", hook("tickets-switch") + " .hd-seg", "texts")]
        out = page(route, captureInitial=panes, actions=[dict(do="click", sel="[data-which='settled']", label="s", capture=panes)])
        first, then = out["captures"]["initial"], out["captures"]["s"]
        self.assertEqual((first["open"], first["done"]), (False, True))        # open tickets exist: the page opens on them
        self.assertEqual((then["open"], then["done"]), (True, False))
        self.assertTrue(first["labels"][0].startswith("Open") and "2" in first["labels"][0])

    def test_a_graded_ticket_shows_paper_dollars_at_the_viewers_unit(self):
        sel = [q("money", "[data-hook='card-money']", "texts")]
        ten = page(with_now(now_route([])), queries=sel)["final"]["money"]
        hundred = page(with_now(now_route([])), queries=sel, viewer={"mode": "fixed", "unit_usd": 100, "pct": None, "start_usd": 10000})["final"]["money"]
        self.assertTrue(ten and len(ten) == len(hundred))
        self.assertNotEqual(ten, hundred)


class TheMoneyHelper(unittest.TestCase):
    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_units_become_dollars_or_a_share_of_bankroll(self):
        out = run_js("""import { signedMoney } from "%s";
console.log(JSON.stringify([signedMoney(1.2, {mode:"fixed",unit_usd:25}), signedMoney(-1, {mode:"fixed",unit_usd:10}), signedMoney(0.91, {mode:"percent",pct:1}),
 signedMoney(null, {mode:"fixed",unit_usd:25}), signedMoney(0, {mode:"fixed",unit_usd:25})]));""" % (WEB / "js" / "hound-money.js").as_uri())
        self.assertEqual(out, ["+$30", "-$10", "+0.91% of bankroll", "", "$0"])


def _chrome_ready():
    try:
        from tests.test_no_horizontal_overflow import CHROME
    except Exception:           # noqa: BLE001 -- the overflow module needs nothing that is missing here; be safe
        return None
    return CHROME


@unittest.skipUnless(HAS_NODE and _chrome_ready(), "node and a Chrome/Chromium binary are needed")
class TheHoundPageFitsEveryWidth(unittest.TestCase):
    """The hound page, its right-now card (long names and a long game, three candidates) and every tab at 375, 390 and 1440."""
    WIDTHS = (375, 390, 1440)

    @classmethod
    def setUpClass(cls):
        import http.server
        import subprocess
        import threading
        from tests.test_no_horizontal_overflow import CHROME, HERE, make_handler
        api = {k: (s, b) for k, (s, b) in F.routes().items()}
        cls.hid = F.summaries()[0].id
        long_game = "The Extraordinarily Long-Named Visiting Club of Somewhere @ The Equally Long-Named Home Side of Elsewhere"
        cands = [cand(1, "The Extraordinarily Long-Named Visiting Club of Somewhere to win", 1450, total=3, game=long_game, reason="r " * 200),
                 cand(2, "Over 8.5", 105, game=long_game), cand(3, "Under 9.5", 110, game=long_game)]
        api[f"/hounds/{cls.hid}/right-now"] = (200, now_route(cands, voice_label="Underdog hunter"))
        cls.pages = [f"/web/hound.html?id={cls.hid}" + tab for tab in ("", "&tab=tickets", "&tab=rules", "&tab=record")]
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        proc = subprocess.run(["node", str(HERE / "overflow_widths.mjs"), CHROME, base, ",".join(str(w) for w in cls.WIDTHS)] + cls.pages,
                              capture_output=True, text=True, encoding="utf-8", timeout=420)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"overflow script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.results = json.loads(lines[-1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_measured_at_every_width_and_nothing_scrolls_sideways(self):
        self.assertEqual(len(self.results), len(self.WIDTHS) * len(self.pages))
        self.assertEqual({r["iw"] for r in self.results}, set(self.WIDTHS))
        for r in self.results:
            self.assertGreater(r["h"], 300, f"{r['path']} rendered almost nothing")
        bad = [r for r in self.results if r["sw"] > r["iw"] + 1]
        self.assertEqual(bad, [], "wider than the screen: " + json.dumps(bad, indent=1))



def _held(event, market, side, game, start_min=60, line=None, player=None):
    start = NOW + timedelta(minutes=start_min)
    return {"event_id": event, "market": market, "side": side, "line": line, "player": player, "game": game, "sport": "MLB",
            "start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ")}


class TheAnswerIsAlwaysFresh(unittest.TestCase):
    """Owner, 2026-10-22: "What would you bet right now?" must never answer with a bet the hound already holds."""

    def test_a_ticket_the_rule_already_placed_is_never_a_candidate(self):
        picks = [pick("a", "Placed already", +150, 60, rank=0, market="moneyline", side="away"),
                 pick("b", "Fresh", +120, 90, rank=1)]
        held = [_held("a", "moneyline", "away", "Team a @ Other a")]
        out = right_now.build(dog_of(hid=HID), 1, now=NOW, payload=payload(picks), held=held)
        self.assertEqual([c["selection"] for c in out["candidates"]], ["Fresh"])

    def test_the_owners_manual_pick_is_held_too(self):
        picks = [pick("a", "Manual already", +150, 60, rank=0), pick("b", "Fresh", +120, 90, rank=1)]
        held = right_now.held_positions([], [{"event_id": "a", "market": "moneyline", "side": "away", "game": "Team a @ Other a",
                                              "start_utc": picks[0]["start_utc"], "kind": "manual"}])
        out = right_now.build(dog_of(hid=HID), 1, now=NOW, payload=payload(picks), held=held)
        self.assertEqual([c["selection"] for c in out["candidates"]], ["Fresh"])

    def test_the_other_side_of_a_game_it_holds_is_never_offered_in_any_market(self):
        # holds the away moneyline; the home run line, the home moneyline and the away run line are all on that same game
        held = [_held("a", "moneyline", "away", "Team a @ Other a")]
        picks = [pick("a", "Home ML", +110, 60, rank=0, side="home"),
                 pick("a", "Home run line", +140, 60, rank=1, side="home", market="spread", line=-1.5),
                 pick("a", "Away run line", +160, 60, rank=2, side="away", market="spread", line=1.5),
                 pick("b", "Other game", +120, 90, rank=3)]
        out = right_now.build(dog_of(hid=HID), 1, now=NOW, payload=payload(picks), held=held)
        self.assertEqual([c["selection"] for c in out["candidates"]], ["Other game"])

    def test_a_total_on_a_game_it_holds_a_side_on_is_still_a_different_slot_but_one_card_per_game(self):
        picks = [pick("a", "Away ML", +130, 60, rank=0), pick("a", "Over 8.5", +105, 60, rank=1, market="total", side="over", line=8.5),
                 pick("b", "Next game", +120, 90, rank=2)]
        out = build(picks)
        # two markets on one game are two picks, but "Show me another" never lands on the same game twice
        self.assertEqual([c["selection"] for c in out["candidates"]], ["Away ML", "Next game"])
        self.assertEqual(len({c["event_id"] for c in out["candidates"]}), len(out["candidates"]))
        self.assertEqual([c["of"] for c in out["candidates"]], [2, 2])

    def test_with_nothing_fresh_it_says_nothing_and_names_the_next_game(self):
        picks = [pick("a", "Placed already", +150, 60)]
        game = {"event_id": "z", "game": "Mets @ Braves", "start_utc": (NOW + timedelta(hours=26)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        out = right_now.build(dog_of(hid=HID), 1, now=NOW, payload=payload(picks, games=[game]),
                              held=[_held("a", "moneyline", "away", "Team a @ Other a")])
        self.assertTrue(out["nothing"])
        self.assertEqual(out["next_look"]["game"], "Mets @ Braves")

    def test_the_hound_page_and_the_ask_answer_choose_the_same_pick(self):
        """One code path: the card and the chat can never disagree."""
        from src.hounds.interact import ask
        picks = [pick("a", "Placed already", +150, 60, rank=0), pick("b", "Fresh one", +120, 90, rank=1), pick("c", "Third", +125, 120, rank=2)]
        pay = payload(picks)
        pay["recorded"] = [_held("a", "moneyline", "away", "Team a @ Other a")]
        card = right_now.build(dog_of(hid=HID), 1, now=NOW, payload=pay)
        ctx = ask.AskContext(dog_id=HID, name="Closer", kind="user", spec=dog_of(hid=HID).spec, fire_fn=lambda: pay, now=NOW, is_owner=True)
        said = ask.answer("what would you bet right now", ctx)
        self.assertEqual(said["intent"], "picks_now")
        self.assertEqual(said["cards"][0]["selection"], card["candidates"][0]["selection"])
        self.assertEqual(said["cards"][0]["selection"], "Fresh one")
        self.assertNotIn("Placed already", said["answer"])

    def test_the_answer_never_lists_a_started_game_as_filler(self):
        from src.hounds.interact import ask
        started = pick("s", "Already underway", +150, -20, rank=0)
        pay = dict(payload([started]), slate={"line": "Tonight's games already started: Team s @ Other s (7:10 pm ET)."})
        ctx = ask.AskContext(dog_id=HID, name="Closer", kind="user", spec=dog_of(hid=HID).spec, fire_fn=lambda: pay, now=NOW)
        said = ask.answer("what would you bet right now", ctx)
        self.assertEqual(said["cards"], [])
        self.assertNotIn("Already underway", said["answer"])
        self.assertNotIn("Team s", said["answer"])
        self.assertNotIn("already started", said["answer"])


RAW_SPORT_KEYS = ("GRIDIRON", "BASKETBALL", "HOCKEY", "BASEBALL", "SOCCER", "TENNIS", "CRICKET", "RUGBY", "NCAAF", "NCAAB")
RAW_KEY = re.compile(r"\b(" + "|".join(RAW_SPORT_KEYS) + r")\b")        # case-sensitive: an ALL-CAPS internal key, never a word


class NoInternalSportKeyIsUserCopy(unittest.TestCase):
    """Owner, 2026-10-22: Ask said "GRIDIRON, NBA, WNBA and 4 more". Every sport reads through the label map."""

    def test_the_sport_phrase_uses_the_label_not_the_key(self):
        from src.hounds import user_spec
        text = user_spec.sports_phrase(["GRIDIRON", "NBA", "WNBA", "NHL", "MLB"])
        self.assertEqual(text, "CFL and UFL, NBA, WNBA and 2 more sports")
        self.assertEqual(user_spec.sports_phrase(["SOCCER"]), "Soccer")
        self.assertEqual(user_spec.sports_phrase(["MLB", "NFL"]), "MLB and NFL")
        for key in user_spec.SPORTS:
            self.assertIsNone(RAW_KEY.search(user_spec.sports_phrase([key])), key)
            self.assertIsNone(RAW_KEY.search(user_spec.sport_words(key)), key)

    def test_the_rule_text_and_every_ask_answer_for_a_hound_on_many_sports(self):
        from src.hounds import user_spec
        from src.hounds.interact import ask
        dog = dog_of(hid=HID, sports=["NFL", "GRIDIRON", "NBA", "WNBA", "NCAAB", "BASKETBALL", "NHL", "HOCKEY", "TENNIS", "CRICKET", "RUGBY", "SOCCER"])
        rule = user_spec.rule_text(dog.spec)
        self.assertIsNone(RAW_KEY.search(rule), rule)
        ctx = ask.AskContext(dog_id=HID, name="Closer", kind="user", spec=dog.spec, rule_text=rule, rule_english=rule,
                             summary={"sports": [s.lower() for s in dog.spec["sports"]]}, fire_fn=lambda: payload([]), now=NOW)
        for question in ("who are you", "what are your rules", "what would you bet right now", "how are you doing", "help"):
            said = ask.answer(question, ctx)
            blob = " ".join(said["lines"] + (said["details"] or {}).get("lines", []))
            self.assertIsNone(RAW_KEY.search(blob), (question, blob))

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_no_all_caps_sport_key_in_the_rendered_hound_page(self):
        from src.hounds import user_spec
        from src.hounds.interact import ask
        everything = list(user_spec.SPORTS)
        dog = dog_of(hid=HID, sports=everything)
        rule = user_spec.rule_text(dog.spec)
        routes = dog_routes()
        detail = routes[f"/hounds/{HID}"][1]
        detail["sports"] = [s.lower() for s in everything]
        detail["rule_text"] = rule
        ctx = ask.AskContext(dog_id=HID, name="Closer", kind="user", spec=dog.spec, rule_text=rule, rule_english=rule,
                             summary={"sports": [s.lower() for s in everything]}, fire_fn=lambda: payload([]), now=NOW)
        routes[f"/hounds/{HID}/ask"] = [200, {"dog_id": HID, "dog_name": "Closer", "greeting": ask.answer("who are you", ctx)["lines"],
                                              "suggestions": ask.suggestions(ctx), "warming": False}]
        routes[f"POST /hounds/{HID}/ask"] = [200, ask.answer("what are your rules", ctx)]
        out = page(routes, actions=[dict(do="set", sel=hook("ask-input"), value="what are your rules", wait=10),
                                    dict(do="click", sel=hook("ask-send"), wait=100)],
                   queries=[q("main", "main"), q("ask", hook("dog-ask")), q("header", hook("hound-header")), q("rule", hook("rule-text"))])
        f = out["final"]
        seen = " ".join(str(f.get(k) or "") for k in ("main", "ask", "header", "rule"))
        self.assertGreater(len(seen), 200)
        self.assertIsNone(RAW_KEY.search(seen), RAW_KEY.search(seen) and seen[max(0, RAW_KEY.search(seen).start() - 80):RAW_KEY.search(seen).end() + 40])
        # the same rendered text never says the canine word or "lock" (the hound page says hound, and "placing time")
        for rx in (DOG, re.compile(r"\block(ed|s)?\b", re.I)):
            m = rx.search(seen)
            self.assertIsNone(m, m and seen[max(0, m.start() - 80):m.end() + 40])


class EveryAskAnswerSaysHoundAndMakesNoClaim(unittest.TestCase):
    def test_no_answer_says_the_canine_word_or_a_banned_claim(self):
        from tests.test_hounds_interact_ask import PHRASINGS, context
        from src.hounds.interact import ask
        banned = re.compile(r"lock(ed|s)?|guarantee|edge|win(ning)? (probability|chance)|bet check", re.I)
        questions = [text for text, _intent in PHRASINGS] + ["help", "who are you", "what are your rules", "any tips", "banana"]
        for kind in ("user", "house"):
            for owner in (True, False):
                for text in questions:
                    said = ask.answer(text, context(name="Closer", kind=kind, is_owner=owner))
                    blob = " ".join(said["lines"] + (said.get("details") or {}).get("lines", []))
                    for rx in (DOG, banned):
                        m = rx.search(blob)
                        self.assertIsNone(m, (text, kind, m and blob[max(0, m.start() - 60):m.end() + 40]))


if __name__ == "__main__":
    unittest.main()
