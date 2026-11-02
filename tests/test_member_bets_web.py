"""Log a bet, the member's own bet log (web/js/member-bets.js), run for real under node against the fake DOM of tests/hounds_web_harness.mjs.

WHAT IS PINNED (docs/plans/MEMBER_BET_LOG.md, UI worker)
  * a "Log a bet" button on every Live board row (data-hook live-log-bet), beside "Send a hound";
  * the panel opens with the sides for a moneyline, a total and a spread (spread and total only when the board has them), the
    price filled from GET /me/bets/price and still editable (empty plus a hint when the board has none), the stake defaulting to the
    member's last one, "In play" on a game that has started, and a signed-out visitor asked to sign in;
  * a save posts the right body, a good save says so and links to My bets, a refusal shows the server's sentence word for word;
  * a hound's ticket ("Why this bet") has "Log this bet", which opens the same panel with the hound's side, line and price;
  * the kennel's My bets tab (?tab=mybets): open bets first (Remove only when the server says can_void), settled with result, units,
    closing price and "vs close", then bets not on our board, the record line, and the "Log a bet by hand" form that posts to
    /me/bets/manual;
  * the copy never says edge, lock, beta, new, paper, promise or CLV.

Skipped when node is not installed (the static checks need none).
"""

from __future__ import annotations

import json
import re
import unittest

from tests import test_kennel_page as kennel_tests
from tests.hounds_web_runner import HAS_NODE, WEB, run_page
from tests.test_live_board import FIXTURE, LA, NOW

TOKEN_KEY = "aisportsanalysis.invite_token"
STAKE_KEY = "linehound.member_bet_stake"
SIGNED = dict(stored={TOKEN_KEY: "tok"})
JS = (WEB / "js" / "member-bets.js").read_text(encoding="utf-8")
CSS = (WEB / "css" / "hounds.css").read_text(encoding="utf-8")

EVENT = "hoc-1"                         # Boston Bruins at Toronto Maple Leafs, upcoming
LIVE_EVENT = "soc-1"                    # Fulham at Brighton, in play
SIDES_SEL = "[data-hook='log-bet-side']"


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def price_url(event, market, side):
    return f"/me/bets/price?event_id={event}&market={market}&side={side}"


def board_prices(event=EVENT, spread=True, total=True):
    """The routes for a game whose board has a spread (home -1.5) and a total (6.5), a moneyline price for each side."""
    r = {price_url(event, "moneyline", "away"): [200, {"price": 105, "line": None, "n_books": 6}],
         price_url(event, "moneyline", "home"): [200, {"price": -125, "line": None, "n_books": 6}]}
    if spread:
        r[price_url(event, "spread", "home")] = [200, {"price": -110, "line": -1.5, "n_books": 5}]
        r[price_url(event, "spread", "away")] = [200, {"price": -108, "line": 1.5, "n_books": 5}]
    if total:
        r[price_url(event, "total", "over")] = [200, {"price": -112, "line": 6.5, "n_books": 5}]
        r[price_url(event, "total", "under")] = [200, {"price": -104, "line": 6.5, "n_books": 5}]
    return r


def live(routes=None, **kw):
    r = {"/sports/now": [200, FIXTURE]}
    r.update(routes or {})
    kw.setdefault("now", NOW)
    kw.setdefault("tz", LA)
    kw.setdefault("pathname", "/web/live.html")
    return run_page("live", routes=r, **kw)


def open_panel(event=EVENT, routes=None, then=(), capture=None, **kw):
    """Sign in, open the Log a bet panel on one row, then run `then`."""
    actions = [dict(do="click", sel=f"[data-hook='live-log-bet'][data-event='{event}']", label="open", wait=150, capture=capture)]
    actions += list(then)
    kw.setdefault("stored", {TOKEN_KEY: "tok"})
    return live(routes if routes is not None else board_prices(event), actions=actions, **kw)


def done(out, label="open"):
    return out["captures"][label]


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheLiveBoard(unittest.TestCase):
    def test_every_row_has_a_log_a_bet_button_beside_send_a_hound(self):
        out = live(**SIGNED, queries=[q("rows", "[data-hook='live-row']", "count"), q("log", "[data-hook='live-log-bet']", "count"),
                                      q("send", "[data-hook='live-send']", "count"), q("words", "[data-hook='live-log-bet']", "texts"),
                                      q("both", ".lv-row__acts [data-hook='live-send']", "count")])
        f = out["final"]
        self.assertGreater(f["rows"], 5)
        self.assertEqual(f["log"], f["rows"])
        self.assertEqual(f["send"], f["rows"])
        self.assertEqual(set(f["words"]), {"Log a bet"})
        self.assertEqual(f["both"], f["rows"], "Send a hound sits beside Log a bet in the row's actions")

    def test_the_two_buttons_share_one_tray(self):
        out = open_panel(then=[dict(do="click", sel=f"[data-hook='live-send'][data-event='{EVENT}']", label="swap", wait=150)],
                         capture=[q("trays", "[data-hook='live-tray']", "count"), q("panel", "[data-hook='log-bet-panel']", "count"),
                                  q("logOpen", f"[data-hook='live-log-bet'][data-event='{EVENT}']", "attr", attr="aria-expanded")])
        self.assertEqual(done(out), {"trays": 1, "panel": 1, "logOpen": "true"})
        # a tap on Send a hound swaps the tray's content and leaves one tray
        out = open_panel(then=[dict(do="click", sel=f"[data-hook='live-send'][data-event='{EVENT}']", label="swap", wait=150,
                                    capture=[q("trays", "[data-hook='live-tray']", "count"), q("panel", "[data-hook='log-bet-panel']", "count"),
                                             q("logOpen", f"[data-hook='live-log-bet'][data-event='{EVENT}']", "attr", attr="aria-expanded"),
                                             q("sendOpen", f"[data-hook='live-send'][data-event='{EVENT}']", "attr", attr="aria-expanded")])])
        self.assertEqual(out["captures"]["swap"], {"trays": 1, "panel": 0, "logOpen": "false", "sendOpen": "true"})

    def test_the_panel_opens_with_the_sides_for_a_moneyline_a_total_and_a_spread(self):
        out = open_panel(capture=[q("sides", SIDES_SEL, "texts"), q("markets", SIDES_SEL, "attrs", attr="data-market"),
                                  q("game", "[data-hook='log-bet-game']"), q("inplay", "[data-hook='log-bet-inplay']", "count")])
        c = done(out)
        self.assertEqual(c["game"], "Boston Bruins at Toronto Maple Leafs")
        self.assertEqual(c["sides"], ["Boston Bruins to win", "Toronto Maple Leafs to win", "Boston Bruins +1.5", "Toronto Maple Leafs -1.5",
                                      "Over 6.5", "Under 6.5"])
        self.assertEqual(c["markets"], ["moneyline"] * 2 + ["spread"] * 2 + ["total"] * 2)
        self.assertEqual(c["inplay"], 0, "an upcoming game is not in play")

    def test_a_market_the_board_does_not_have_is_not_offered(self):
        out = open_panel(routes=board_prices(spread=False, total=True), capture=[q("sides", SIDES_SEL, "texts")])
        self.assertEqual(done(out)["sides"], ["Boston Bruins to win", "Toronto Maple Leafs to win", "Over 6.5", "Under 6.5"])
        out = open_panel(routes=board_prices(spread=False, total=False), capture=[q("sides", SIDES_SEL, "texts")])
        self.assertEqual(done(out)["sides"], ["Boston Bruins to win", "Toronto Maple Leafs to win"])

    def test_the_price_is_prefilled_from_the_board_and_stays_editable(self):
        out = open_panel(then=[dict(do="click", sel=f"{SIDES_SEL}[data-market='moneyline'][data-side='away']", label="pick", wait=150, capture=[
            q("price", "[data-hook='log-bet-price']", "value"), q("hint", "[data-hook='log-bet-price-hint']"),
            q("pressed", SIDES_SEL, "attrs", attr="aria-pressed")]),
            dict(do="set", sel="[data-hook='log-bet-price']", value="+110", label="edit", capture=[q("price", "[data-hook='log-bet-price']", "value")])])
        pick = out["captures"]["pick"]
        self.assertEqual(pick["price"], "105")
        self.assertIn("6 books", pick["hint"])
        self.assertEqual(pick["pressed"][0], "true")
        self.assertEqual(out["captures"]["edit"]["price"], "+110")
        gets = [g for g in out["gets"] if g.startswith("/me/bets/price")]
        self.assertIn(price_url(EVENT, "moneyline", "away"), gets)

    def test_a_side_with_no_board_price_leaves_the_field_empty_with_a_hint(self):
        routes = board_prices()
        routes[price_url(EVENT, "moneyline", "home")] = [200, {"price": None, "line": None, "n_books": 0}]
        out = open_panel(routes=routes, then=[dict(do="click", sel=f"{SIDES_SEL}[data-market='moneyline'][data-side='home']", label="pick", wait=150, capture=[
            q("price", "[data-hook='log-bet-price']", "value"), q("hint", "[data-hook='log-bet-price-hint']")])])
        pick = out["captures"]["pick"]
        self.assertEqual(pick["price"], "")
        self.assertIn("Type the price you got", pick["hint"])

    def test_a_game_in_play_says_so(self):
        out = open_panel(event=LIVE_EVENT, routes={}, capture=[q("pill", "[data-hook='log-bet-inplay']"), q("sides", SIDES_SEL, "texts")])
        self.assertEqual(done(out)["pill"], "In play")
        self.assertEqual(done(out)["sides"], ["Fulham to win", "Brighton and Hove Albion to win"], "a moneyline is always offered")

    def test_the_stake_defaults_to_the_last_one_the_member_used_else_one(self):
        ask = [q("stake", "[data-hook='log-bet-stake']", "value")]
        self.assertEqual(done(open_panel(capture=ask))["stake"], "1")
        self.assertEqual(done(open_panel(capture=ask, stored={TOKEN_KEY: "tok", STAKE_KEY: "2.5"}))["stake"], "2.5")
        self.assertEqual(done(open_panel(capture=ask, stored={TOKEN_KEY: "tok", STAKE_KEY: "junk"}))["stake"], "1")

    def test_a_signed_out_visitor_is_asked_to_sign_in(self):
        out = live(stored={}, actions=[dict(do="click", sel=f"[data-hook='live-log-bet'][data-event='{EVENT}']", label="open", wait=100, capture=[
            q("prompt", "[data-hook='log-bet-panel'] [data-hook='signin-prompt']"), q("save", "[data-hook='log-bet-save']", "count")])])
        self.assertIn("Sign in to log a bet on Boston Bruins at Toronto Maple Leafs.", done(out)["prompt"])
        self.assertEqual(done(out)["save"], 0)
        self.assertEqual([g for g in out["gets"] if g.startswith("/me/bets")], [])

    def test_a_save_posts_the_right_body_and_links_to_my_bets(self):
        routes = board_prices()
        routes["POST /me/bets"] = [200, {"id": "mb-1", "selection": "Over 6.5", "price": -112, "status": "open"}]
        out = open_panel(routes=routes, then=[
            dict(do="click", sel=f"{SIDES_SEL}[data-market='total'][data-side='over']", wait=150),
            dict(do="set", sel="[data-hook='log-bet-stake']", value="2"),
            dict(do="set", sel="[data-hook='log-bet-note']", value="  early number  "),
            dict(do="click", sel="[data-hook='log-bet-save']", label="save", wait=150, capture=[
                q("done", "[data-hook='log-bet-done']"), q("href", "[data-hook='log-bet-mybets-link']", "attr", attr="href"),
                q("form", "[data-hook='log-bet-form']", "exists")])])
        self.assertEqual(out["posts"], [{"url": "/me/bets", "method": "POST", "headers": out["posts"][0]["headers"],
                                         "body": {"event_id": EVENT, "market": "total", "side": "over", "stake_units": 2.0, "line": 6.5,
                                                  "price": -112.0, "note": "early number"}}])
        c = out["captures"]["save"]
        self.assertEqual(c["done"], "Logged: Over 6.5 at -112. See your bets .")
        self.assertEqual(c["href"], "kennel.html?tab=mybets")
        self.assertFalse(c["form"])
        self.assertEqual(out["storedAfter"][STAKE_KEY], "2", "the next panel starts at the stake just used")

    def test_a_typed_price_and_a_moneyline_post_without_a_line(self):
        routes = board_prices()
        routes["POST /me/bets"] = [200, {"id": "mb-2", "selection": "Boston Bruins to win", "price": 120}]
        out = open_panel(routes=routes, then=[
            dict(do="click", sel=f"{SIDES_SEL}[data-market='moneyline'][data-side='away']", wait=150),
            dict(do="set", sel="[data-hook='log-bet-price']", value="+120"),
            dict(do="click", sel="[data-hook='log-bet-save']", wait=150)])
        self.assertEqual(out["posts"][0]["body"], {"event_id": EVENT, "market": "moneyline", "side": "away", "stake_units": 1.0, "price": 120.0})

    def test_a_refusal_shows_the_servers_sentence_word_for_word(self):
        sentence = "You can only back one side of a game: you already have Toronto Maple Leafs to win."
        routes = board_prices()
        routes["POST /me/bets"] = [409, {"detail": sentence}]
        out = open_panel(routes=routes, then=[
            dict(do="click", sel=f"{SIDES_SEL}[data-market='moneyline'][data-side='away']", wait=150),
            dict(do="click", sel="[data-hook='log-bet-save']", label="save", wait=150, capture=[
                q("error", "[data-hook='log-bet-error']"), q("hidden", "[data-hook='log-bet-error']", "hidden"),
                q("save_disabled", "[data-hook='log-bet-save']", "disabled"), q("done", "[data-hook='log-bet-done']", "count")])])
        c = out["captures"]["save"]
        self.assertEqual(c["error"], sentence)
        self.assertFalse(c["hidden"])
        self.assertFalse(c["save_disabled"], "the member can fix it and try again")
        self.assertEqual(c["done"], 0)

    def test_saving_without_a_side_asks_for_one_and_posts_nothing(self):
        out = open_panel(then=[dict(do="click", sel="[data-hook='log-bet-save']", label="save", wait=100, capture=[q("error", "[data-hook='log-bet-error']")])])
        self.assertEqual(out["captures"]["save"]["error"], "Pick a side first.")
        self.assertEqual(out["posts"], [])

    def test_a_stake_out_of_range_is_caught_before_the_server(self):
        out = open_panel(then=[dict(do="click", sel=f"{SIDES_SEL}[data-market='moneyline'][data-side='away']", wait=100),
                               dict(do="set", sel="[data-hook='log-bet-stake']", value="50"),
                               dict(do="click", sel="[data-hook='log-bet-save']", label="save", wait=100, capture=[q("error", "[data-hook='log-bet-error']")])])
        self.assertIn("between 0.25 and 10 units", out["captures"]["save"]["error"])
        self.assertEqual(out["posts"], [])


def ticket(**over):
    t = {"event_id": EVENT, "sport": "hockey", "game": "Boston Bruins at Toronto Maple Leafs", "market": "total", "selection": "Over 6.5",
         "line": "6.5", "price": -110, "price_average": -112, "result": None, "status": "OPEN", "date": "2026-10-20",
         "start_utc": "2026-10-20T23:00:00Z", "reason": "The total is short of its fair number."}
    t.update(over)
    return t


def card(t, routes=None, then=(), **kw):
    r = {"/test/ticket": [200, t]}
    r.update(routes or {})
    kw.setdefault("stored", {TOKEN_KEY: "tok"})
    return run_page("ticket", routes=r, now=NOW, actions=list(then), **kw)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheTicketButton(unittest.TestCase):
    def open(self, t, **kw):
        return card(t, then=[dict(do="click", sel="[data-hook='ticket-log-bet']", label="open", wait=150, capture=[
            q("sides", SIDES_SEL, "texts"), q("pressed", SIDES_SEL, "attrs", attr="aria-pressed"), q("price", "[data-hook='log-bet-price']", "value"),
            q("hint", "[data-hook='log-bet-price-hint']"), q("expanded", "[data-hook='ticket-log-bet']", "attr", attr="aria-expanded")])], **kw)

    def test_the_button_is_in_the_why_this_bet_fold(self):
        out = card(ticket(), queries=[q("inside", "[data-hook='card-why'] [data-hook='ticket-log-bet']", "texts")])
        self.assertEqual(out["final"]["inside"], ["Log this bet"])

    def test_it_opens_the_panel_with_the_hounds_side_line_and_price(self):
        out = self.open(ticket())
        c = done(out)
        self.assertEqual(c["sides"], ["Over 6.5", "Under 6.5"])
        self.assertEqual(c["pressed"], ["true", "false"])
        self.assertEqual(c["price"], "-112")
        self.assertEqual(c["expanded"], "true")
        self.assertEqual([g for g in out["gets"] if g.startswith("/me/bets/price")], [], "the hound's own price is used, not the board's")

    def test_a_save_posts_the_hounds_bet(self):
        out = card(ticket(), routes={"POST /me/bets": [200, {"id": "mb-3", "selection": "Over 6.5", "price": -112}]}, then=[
            dict(do="click", sel="[data-hook='ticket-log-bet']", wait=100), dict(do="click", sel="[data-hook='log-bet-save']", wait=150)])
        self.assertEqual(out["posts"][0]["body"], {"event_id": EVENT, "market": "total", "side": "over", "stake_units": 1.0, "line": 6.5, "price": -112.0})

    def test_a_spread_ticket_reads_its_side_from_the_pick(self):
        t = ticket(market="spread", selection="Toronto Maple Leafs -1.5", line="-1.5", price_average=-105)
        c = done(self.open(t))
        self.assertEqual(c["sides"], ["Boston Bruins +1.5", "Toronto Maple Leafs -1.5"])
        self.assertEqual(c["pressed"], ["false", "true"])
        self.assertEqual(c["price"], "-105")

    def test_a_moneyline_ticket(self):
        t = ticket(market="moneyline", selection="Boston Bruins to win", line=None, price_average=110)
        c = done(self.open(t))
        self.assertEqual(c["sides"], ["Boston Bruins to win", "Toronto Maple Leafs to win"])
        self.assertEqual(c["pressed"], ["true", "false"])
        self.assertEqual(c["price"], "110")

    def test_a_graded_ticket_or_one_without_a_game_has_no_button(self):
        for t in (ticket(result="win", status="GRADED"), ticket(event_id=None)):
            with self.subTest(t=t.get("result") or "no event"):
                out = card(t, queries=[q("n", "[data-hook='ticket-log-bet']", "count")])
                self.assertEqual(out["final"]["n"], 0)


def bet(bid, status="open", **over):
    out = {"id": bid, "kind": "board", "status": status, "sport": "NHL", "game": "Boston Bruins at Toronto Maple Leafs", "event_id": EVENT,
           "market": "total", "side": "over", "selection": "Over 6.5", "line": 6.5, "price": -112, "stake_units": 1.0, "live": False,
           "in_play": False, "note": None, "placed_utc": "2026-10-20T15:00:00Z", "start_utc": "2026-10-20T23:00:00Z", "result": None,
           "units": None, "close_price": None, "clv_pts": None, "reason": None, "score": None, "can_void": False}
    out.update(over)
    return out


BETS = {
    "bets": [
        bet("mb-open", can_void=True),
        bet("mb-live", selection="Fulham to win", price=310, in_play=True, live=True, game="Fulham at Brighton and Hove Albion"),
        bet("mb-win", status="settled", result="WIN", units=1.5, stake_units=1.0, close_price=-120, clv_pts=1.2, selection="Boston Bruins to win", price=150),
        bet("mb-loss", status="settled", result="LOSS", units=-2.0, stake_units=2.0, close_price=-105, clv_pts=-0.4, selection="Under 8.5", price=-105),
        bet("mb-hand", kind="manual", status="unmatched", event_id=None, game="Local derby", selection="Home to win", price=200, can_void=True, start_utc=None),
        bet("mb-gone", status="removed"),
    ],
    "record": {"w": 1, "l": 1, "p": 0, "void": 0, "units": -0.5, "stake_units": 3.0, "clv_mean": 0.4, "n_clv": 2},
    "open": 3,
}


def kennel(search="?tab=mybets", bets=BETS, routes=None, then=(), **kw):
    r = {"/hounds/kennels/mine": kennel_tests.mine([kennel_tests.dog("u-1")]), "/me/bets": [200, bets]}
    r.update(routes or {})
    kw.setdefault("stored", {TOKEN_KEY: "tok"})
    return run_page("kennel", routes=r, search=search, pathname="/web/kennel.html", actions=list(then), **kw)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheMyBetsTab(unittest.TestCase):
    def test_the_deep_link_opens_the_tab_and_lists_open_settled_and_unmatched_in_that_order(self):
        out = kennel(queries=[q("tabs", "[data-hook='kennel-pagetabs'] [role='tab']", "texts"), q("selected", "[data-hook='kennel-pagetabs'] [aria-selected='true']"),
                              q("tabs_hidden", "[data-hook='kennel-pagetabs']", "hidden"), q("panel_hidden", "[data-hook='kennel-mybets']", "hidden"),
                              q("hounds_hidden", "[data-hook='kennel-hounds-panel']", "hidden"),
                              q("open", "[data-hook='mybets-open-list'] [data-hook='mybets-pick']", "texts"),
                              q("settled", "[data-hook='mybets-settled-list'] [data-hook='mybets-pick']", "texts"),
                              q("unmatched", "[data-hook='mybets-unmatched-list'] [data-hook='mybets-pick']", "texts"),
                              q("all", "[data-hook='mybets-bet']", "attrs", attr="data-id")])
        f = out["final"]
        self.assertEqual(f["tabs"], ["My hounds", "My bets"])
        self.assertEqual(f["selected"], "My bets")
        self.assertFalse(f["tabs_hidden"])
        self.assertFalse(f["panel_hidden"])
        self.assertTrue(f["hounds_hidden"])
        self.assertEqual(f["open"], ["Over 6.5 -112", "Fulham to win +310"])
        self.assertEqual(f["settled"], ["Boston Bruins to win +150", "Under 8.5 -105"])
        self.assertEqual(f["unmatched"], ["Home to win +200"])
        self.assertEqual(f["all"], ["mb-open", "mb-live", "mb-win", "mb-loss", "mb-hand"], "a removed bet is not listed")
        hooks = out["hooks"]
        self.assertLess(hooks.index("mybets-open-list"), hooks.index("mybets-settled-list"))
        self.assertLess(hooks.index("mybets-settled-list"), hooks.index("mybets-unmatched-list"))
        self.assertLess(hooks.index("mybets-unmatched-list"), hooks.index("mybets-manual"), "the by-hand form is at the bottom")

    def test_the_record_line_reads_like_a_hound_cards(self):
        out = kennel(queries=[q("record", "[data-hook='mybets-record']"), q("cls", "[data-hook='mybets-recordbox']", "attr", attr="class"),
                              q("label", "[data-hook='mybets-recordbox'] dt", "texts")])
        self.assertEqual(out["final"]["record"], "1-1-0, -0.5 units")
        self.assertIn("kn-stats", out["final"]["cls"])
        out = kennel(bets={**BETS, "record": {"w": 12, "l": 7, "p": 1, "units": 4.26}})
        self.assertIn("12-7-1, +4.3 units", out["text"])

    def test_a_settled_bet_shows_result_units_closing_price_and_vs_close(self):
        out = kennel(queries=[q("results", "[data-hook='mybets-result']", "texts"), q("units", "[data-hook='mybets-units']", "texts"),
                              q("close", "[data-hook='mybets-close']", "texts"), q("vs", "[data-hook='mybets-vsclose']", "texts")])
        f = out["final"]
        self.assertEqual(f["results"], ["Won", "Lost"])
        self.assertEqual(f["units"], ["+1.5 units", "-2.0 units"])
        self.assertEqual(f["close"], ["Closed -120", "Closed -105"])
        self.assertEqual(f["vs"], ["vs close +1.2 pts", "vs close -0.4 pts"])
        self.assertNotRegex(out["text"], r"CLV")

    def test_a_game_in_play_says_so(self):
        out = kennel(queries=[q("pills", "[data-hook='mybets-inplay']", "texts")])
        self.assertEqual(out["final"]["pills"], ["In play"])

    def test_remove_shows_only_when_the_server_says_can_void(self):
        out = kennel(queries=[q("rows", "[data-hook='mybets-bet']", "attrs", attr="data-id"), q("removes", "[data-hook='mybets-remove']", "count"),
                              q("labels", "[data-hook='mybets-remove']", "texts"), q("aria", "[data-hook='mybets-remove']", "attrs", attr="aria-label")])
        self.assertEqual(out["final"]["removes"], 2)          # mb-open and mb-hand; not the one in play, not the settled ones
        self.assertEqual(out["final"]["labels"], ["Remove", "Remove"])
        self.assertEqual(out["final"]["aria"], ["Remove Over 6.5 -112", "Remove Home to win +200"])
        out = kennel(bets={**BETS, "bets": [bet("mb-live", in_play=True), bet("mb-win", status="settled", result="WIN", units=1.0, can_void=False)]},
                     queries=[q("removes", "[data-hook='mybets-remove']", "count")])
        self.assertEqual(out["final"]["removes"], 0)

    def test_remove_deletes_the_bet_and_redraws_the_list(self):
        after = {**BETS, "bets": [b for b in BETS["bets"] if b["id"] != "mb-open"]}
        out = kennel(routes={"DELETE /me/bets/mb-open": [200, {**bet("mb-open", status="removed")}]},
                     then=[dict(do="click", sel="[data-hook='mybets-remove']", label="remove", wait=200)],
                     switchAfter={"/me/bets": [1, [200, after]]},
                     queries=[q("ids", "[data-hook='mybets-bet']", "attrs", attr="data-id")])
        self.assertEqual([(p["method"], p["url"]) for p in out["posts"]], [("DELETE", "/me/bets/mb-open")])
        self.assertNotIn("mb-open", out["final"]["ids"])

    def test_a_refused_remove_shows_the_servers_sentence(self):
        sentence = "That game has started, so the bet stays on your record."
        out = kennel(routes={"DELETE /me/bets/mb-open": [409, {"detail": sentence}]},
                     then=[dict(do="click", sel="[data-hook='mybets-remove']", wait=150)], queries=[q("status", "[data-hook='mybets-status']")])
        self.assertEqual(out["final"]["status"], sentence)

    def test_an_empty_log_says_how_to_start(self):
        out = kennel(bets={"bets": [], "record": {"w": 0, "l": 0, "p": 0, "units": 0.0}, "open": 0},
                     queries=[q("empty", "[data-hook='mybets-empty']"), q("record", "[data-hook='mybets-record']"), q("form", "[data-hook='mybets-manual']", "exists")])
        self.assertIn("You have not logged a bet yet", out["final"]["empty"])
        self.assertEqual(out["final"]["record"], "0-0-0, 0.0 units")
        self.assertTrue(out["final"]["form"])

    def test_without_the_deep_link_the_hounds_show_and_the_tab_loads_on_a_tap(self):
        out = kennel(search="", captureInitial=[q("panel_hidden", "[data-hook='kennel-mybets']", "hidden"), q("hounds_hidden", "[data-hook='kennel-hounds-panel']", "hidden"),
                                                q("dogs", "[data-hook='kennel-dog']", "count"), q("bets", "[data-hook='mybets-bet']", "count")],
                     then=[dict(do="click", sel="[data-tab='mybets']", label="tap", wait=200, capture=[
                         q("panel_hidden", "[data-hook='kennel-mybets']", "hidden"), q("bets", "[data-hook='mybets-bet']", "count")])])
        self.assertEqual(out["captures"]["initial"], {"panel_hidden": True, "hounds_hidden": False, "dogs": 1, "bets": 0})
        self.assertEqual(out["captures"]["tap"], {"panel_hidden": False, "bets": 5})
        self.assertEqual([g for g in out["gets"] if g == "/me/bets"], ["/me/bets"], "the list is read when the tab opens, not before")

    def test_a_public_kennel_has_no_tabs(self):
        out = run_page("kennel", routes={"/hounds/kennels/handler-1": kennel_tests.public([kennel_tests.dog("u-1")], handle="handler-1")},
                       search="?u=handler-1&tab=mybets", pathname="/web/kennel.html", stored={TOKEN_KEY: "tok"},
                       queries=[q("tabs_hidden", "[data-hook='kennel-pagetabs']", "hidden"), q("dogs", "[data-hook='kennel-dog']", "count")])
        self.assertTrue(out["final"]["tabs_hidden"])
        self.assertEqual(out["final"]["dogs"], 1)
        self.assertEqual([g for g in out["gets"] if g.startswith("/me/")], [])

    def test_a_signed_out_visitor_gets_the_kennel_as_it_was(self):
        out = run_page("kennel", routes={}, search="?tab=mybets", pathname="/web/kennel.html", stored={},
                       queries=[q("tabs_hidden", "[data-hook='kennel-pagetabs']", "hidden")])
        self.assertTrue(out["final"]["tabs_hidden"])
        self.assertEqual([g for g in out["gets"] if g.startswith("/me/")], [])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheByHandForm(unittest.TestCase):
    FILL = [dict(do="set", sel="[data-hook='manual-sport']", value="NHL"), dict(do="set", sel="[data-hook='manual-game']", value="  Local derby, Reds at Blues "),
            dict(do="set", sel="[data-hook='manual-side']", value="Reds +1.5"), dict(do="set", sel="[data-hook='manual-price']", value="+150"),
            dict(do="set", sel="[data-hook='manual-stake']", value="0.5"), dict(do="set", sel="[data-hook='manual-note']", value="from a friend")]

    def test_the_sport_list_is_the_sports_the_site_carries(self):
        out = kennel(queries=[q("values", "[data-hook='manual-sport'] option", "attrs", attr="value"), q("labels", "[data-hook='manual-sport'] option", "texts")])
        self.assertIn("NHL", out["final"]["values"])
        self.assertIn("SOCCER", out["final"]["values"])
        self.assertNotIn("UFC", out["final"]["values"])
        self.assertIn("Soccer", out["final"]["labels"])

    def test_it_posts_to_the_manual_route(self):
        manual = bet("mb-new", kind="manual", status="unmatched", event_id=None, game="Local derby, Reds at Blues", selection="Reds +1.5", price=150, can_void=True)
        out = kennel(routes={"POST /me/bets/manual": [200, manual]}, then=self.FILL + [dict(do="click", sel="[data-hook='manual-save']", label="save", wait=200)])
        self.assertEqual([(p["method"], p["url"]) for p in out["posts"]], [("POST", "/me/bets/manual")])
        self.assertEqual(out["posts"][0]["body"], {"sport": "NHL", "game_text": "Local derby, Reds at Blues", "side_text": "Reds +1.5",
                                                   "stake_units": 0.5, "price": 150.0, "note": "from a friend"})
        self.assertEqual(out["storedAfter"][STAKE_KEY], "0.5")
        self.assertGreaterEqual(len([g for g in out["gets"] if g == "/me/bets"]), 2, "the list is read again after a save")

    def test_the_price_and_the_note_are_optional(self):
        out = kennel(routes={"POST /me/bets/manual": [200, bet("mb-n", kind="manual", status="unmatched")]},
                     then=[dict(do="set", sel="[data-hook='manual-game']", value="Local derby"), dict(do="set", sel="[data-hook='manual-side']", value="Reds"),
                           dict(do="click", sel="[data-hook='manual-save']", wait=200)])
        self.assertEqual(out["posts"][0]["body"], {"sport": out["posts"][0]["body"]["sport"], "game_text": "Local derby", "side_text": "Reds", "stake_units": 1.0})

    def test_a_refusal_shows_the_servers_sentence(self):
        sentence = "Describe the game in 120 characters or fewer."
        out = kennel(routes={"POST /me/bets/manual": [400, {"detail": sentence}]}, then=self.FILL + [dict(do="click", sel="[data-hook='manual-save']", label="save", wait=200, capture=[
            q("status", "[data-hook='manual-status']"), q("game", "[data-hook='manual-game']", "value")])])
        self.assertEqual(out["captures"]["save"]["status"], sentence)
        self.assertEqual(out["captures"]["save"]["game"], "  Local derby, Reds at Blues ", "what the member typed is still there to fix")


class TheWordsAndTheLayout(unittest.TestCase):
    BANNED = re.compile(r"\b(edge|lock|locks|locked|beta|new|paper|promise|clv)\b", re.I)

    def strings(self, source):
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        source = re.sub(r"(?m)^\s*//.*$", "", source)
        return re.findall(r'"([^"\n]*)"|`([^`\n]*)`', source)

    def test_no_member_copy_uses_a_banned_word(self):
        for name in ("member-bets.js",):
            for pair in self.strings((WEB / "js" / name).read_text(encoding="utf-8")):
                text = "".join(pair)
                with self.subTest(text=text):
                    self.assertIsNone(self.BANNED.search(text), text)
        for path in ("kennel.html",):
            html = (WEB / path).read_text(encoding="utf-8")
            html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
            block = html[html.index('data-hook="kennel-pagetabs"'):html.index('data-hook="kennel-gate"')]
            self.assertIsNone(self.BANNED.search(re.sub(r"<[^>]+>", " ", block)))

    def test_the_styles_exist_for_every_class_the_panel_draws(self):
        classes = {c for m in re.findall(r'class: "([^"]*)"', JS) for c in m.split() if c.startswith("mb-")}
        self.assertGreater(len(classes), 20)
        for cls in sorted(classes) + ["mb-panel", "mb-input", "mb-side", "mb-save", "mb-remove"]:
            with self.subTest(cls=cls):
                self.assertIn(f".{cls}", CSS)

    def test_fields_are_sixteen_pixels_and_buttons_forty_four_tall(self):
        self.assertRegex(CSS, r"\.mb-input \{[^}]*min-height: 44px[^}]*font[^}]*font-size: 16px")
        self.assertRegex(CSS, r"\.mb-side \{[^}]*min-height: 44px")
        self.assertRegex(CSS, r"\.mb-save, \.mb-open, \.mb-remove \{ min-height: 44px; \}")
        self.assertIn("box-sizing: border-box", CSS[CSS.index(".mb-input {"):CSS.index(".mb-input:focus")])


if __name__ == "__main__":
    unittest.main()
