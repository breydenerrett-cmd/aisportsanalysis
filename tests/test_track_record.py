"""The track record payload (src/hounds/track_record.py) and its route (GET /hounds/{id}/record).

The builder and its words need no FastAPI (Linux CI has none); the route tests skip without it. The page that draws the payload is
tests/test_track_record_web.py.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import ledgers, stats, track_record as tr
from src.hounds.contract import BetRow
from src.hounds.ledgers import Sources
from tests import _hounds_fixtures as F

NOW = datetime(2026, 10, 20, 20, 0, 0, tzinfo=timezone.utc)
BANNED = re.compile(r"(?<![-_A-Za-z])dogs?(?![-_A-Za-z])|\bbeta\b|\bnew\b|nothing cleared the bar|\bedge\b|\bprofit|guarantee", re.I)


def defn(kind="house", hid="d", name="Dee"):
    return {"id": hid, "name": name, "tagline": "", "kind": kind, "category": "stats", "style": "t", "sports": ["mlb", "nba"],
            "markets": ["h2h"], "rule_text": "r"}


def bet(i, result, *, hid="d", sport="mlb", market="h2h", side="home", price=-110, avg=None, date="2026-10-01", segment="forward",
        game="Yankees at Red Sox", selection=None, reason="", start="2026-10-01T23:00:00Z", **kw):
    if selection is None:
        selection = {"home": "Red Sox moneyline", "away": "Yankees moneyline", "over": "Over 8.5", "under": "Under 8.5"}[side]
    return ledgers.Bet(hound_id=hid, bet_id=f"b{hid}{i}", date=date, event_id=f"E{hid}{i}", market_key=market, side=side, price=price,
                       price_average=avg if avg is not None else price, result=result, units=None, sport=sport, segment=segment,
                       game_text=game, selection_text=selection, reason=reason, start_utc=start,
                       recorded_utc=start.replace("23:00", "18:00"), **kw)


def data_of(bets, d=None):
    d = d or defn()
    return stats.with_seasons(stats.summarize(d, bets, {}, "2026-10-19", now=NOW), d, bets, {}, "2026-10-19")


def lots():
    """24 settled bets: MLB home favourites mostly win, NBA away underdogs mostly lose; plus one open, one stale and one replay."""
    out = []
    for i in range(12):
        out.append(bet(i, "win" if i % 4 else "loss", sport="mlb", side="home", price=-130, date=f"2026-10-{1 + i:02d}"))
    for i in range(12):
        out.append(bet(100 + i, "loss" if i % 4 else "win", sport="nba", side="away", price=140, game="Celtics at Lakers",
                       selection="Celtics moneyline", date=f"2026-10-{1 + i:02d}", reason="fits the rule"))
    out.append(bet(200, None, date="2026-10-19", start="2026-10-20T23:30:00Z"))                      # open: starts tonight
    out.append(bet(201, None, date="2026-10-10", start="2026-10-10T23:00:00Z"))                      # stale: waiting on a grade
    out.append(bet(300, "win", segment="replay", date="2026-10-05"))                                 # hindsight: never counted
    return out


class TheBuilder(unittest.TestCase):
    def setUp(self):
        self.p = tr.build(data_of(lots()).view("all"), as_of="2026-10-19", now=NOW)

    def test_the_header_counts_only_settled_forward_bets(self):
        h = self.p["header"]
        self.assertEqual((h["wins"], h["losses"], h["pushes"], h["settled"]), (9 + 3, 3 + 9, 0, 24))
        self.assertEqual(h["record_text"], "12-12")
        self.assertAlmostEqual(h["roi_pct"], round(h["units"] / 24 * 100, 1))
        self.assertFalse(h["small_sample"])
        self.assertEqual(h["units_basis"], "average_price")

    def test_open_and_stale_tickets_are_apart_and_the_replay_is_nowhere(self):
        self.assertEqual((self.p["open_total"], self.p["waiting_total"]), (1, 1))
        self.assertEqual(self.p["open"][0]["status"], "OPEN")
        self.assertEqual(self.p["waiting"][0]["status"], "UNGRADED")
        self.assertEqual(self.p["tickets_total"], 24)
        self.assertTrue(all(t["result"] in ("win", "loss", "push") for t in self.p["tickets"]))
        self.assertEqual(sum(d["wins"] + d["losses"] + d["pushes"] for d in self.p["calendar"]), 24)

    def test_the_curve_and_the_calendar_add_up_to_the_header(self):
        self.assertAlmostEqual(self.p["curve"][-1]["units"], self.p["header"]["units"], places=1)
        self.assertAlmostEqual(sum(d["units"] for d in self.p["calendar"]), self.p["header"]["units"], places=1)
        for d in self.p["calendar"]:
            self.assertEqual(d["result"], "win" if d["units"] > 0 else "loss" if d["units"] < 0 else "flat")

    def test_clv_is_left_out_when_there_is_none_and_never_zero(self):
        self.assertIsNone(self.p["header"]["clv"])
        withclv = [bet(i, "win" if i % 2 else "loss", clv_measurable=True, clv_pts=1.5, checkable=True) for i in range(6)]
        p = tr.build(data_of(withclv).view("all"), now=NOW)
        clv = p["header"]["clv"]          # whatever the referee decides is measurable: a present value is real, an absent one is None
        self.assertTrue(clv is None or (clv["n"] > 0 and isinstance(clv["mean_pts"], float)))

    def test_the_streak_is_the_summarys_own(self):
        streak = self.p["header"]["streak"]
        self.assertIn(streak["kind"], ("W", "L"))
        self.assertGreaterEqual(streak["length"], 1)

    def test_the_five_cuts_come_in_order_each_with_a_plain_line(self):
        self.assertEqual([g["group"] for g in self.p["breakdowns"]], ["sport", "market", "band", "role", "venue"])
        sport = self.p["breakdowns"][0]
        self.assertEqual({r["key"] for r in sport["rows"]}, {"MLB", "NBA"})
        self.assertIn("What's working: MLB", sport["line"])
        self.assertIn("What's not: NBA", sport["line"])
        venue = self.p["breakdowns"][4]
        self.assertEqual({r["key"] for r in venue["rows"]}, {"home", "away"})          # inferred from the selection and the game
        for g in self.p["breakdowns"]:
            self.assertTrue(g["line"])

    def test_a_thin_cut_says_only_n_bets_and_draws_no_conclusion(self):
        bets = [bet(i, "win", sport="mlb") for i in range(10)] + [bet(50 + i, "loss", sport="nba", side="away", game="Celtics at Lakers",
                                                                       selection="Celtics moneyline") for i in range(3)]
        p = tr.build(data_of(bets).view("all"), now=NOW)
        sport = p["breakdowns"][0]
        nba = next(r for r in sport["rows"] if r["key"] == "NBA")
        self.assertTrue(nba["thin"])
        self.assertIn("NBA bets (only 3 bets)", sport["line"])
        self.assertNotIn("What's not: NBA", sport["line"])
        self.assertTrue(p["header"]["small_sample"])
        self.assertIn("Only 13 bets settled", p["header"]["sample_note"])

    def test_all_thin_says_so_in_one_sentence(self):
        line = tr.plain_line([{"label": "A", "n": 2, "wins": 1, "losses": 1, "pushes": 0, "units": 0.2, "thin": True},
                              {"label": "B", "n": 1, "wins": 0, "losses": 1, "pushes": 0, "units": -1.0, "thin": True}], "sport")
        self.assertIn("Only 3 bets", line)
        self.assertIn("too few to say", line)
        self.assertNotIn("What's working", line)
        self.assertEqual(tr.plain_line([], "sport"), "No settled bets in this cut yet.")

    def test_a_single_cut_has_nothing_to_compare(self):
        p = tr.build(data_of([bet(i, "win") for i in range(6)]).view("all"), now=NOW)
        self.assertIn("nothing to compare yet", p["breakdowns"][0]["line"])

    def test_every_ticket_carries_its_why_when_one_was_stored(self):
        whys = {t["reason"] for t in self.p["tickets"]}
        self.assertIn("fits the rule", whys)
        self.assertIn("", whys)

    def test_a_ticket_at_minus_200_or_worse_is_tagged_not_hidden(self):
        p = tr.build(data_of([bet(1, "win", price=-250, avg=-250), bet(2, "loss", price=-110)]).view("all"), now=NOW)
        tags = {t["price"]: t["beyond_cap"] for t in p["tickets"]}
        self.assertEqual(tags, {-250: True, -110: False})
        self.assertEqual(p["tickets_total"], 2)           # still in the honest record

    def test_the_ticket_list_is_capped_and_says_how_many_there_are(self):
        many = [bet(i, "win" if i % 2 else "loss", date=f"2026-0{1 + i // 120 % 9}-{1 + i % 28:02d}") for i in range(tr.TICKET_CAP + 20)]
        p = tr.build(data_of(many).view("all"), now=NOW)
        self.assertEqual((p["tickets_total"], p["tickets_shown"]), (tr.TICKET_CAP + 20, tr.TICKET_CAP))

    def test_nothing_the_builder_writes_is_a_banned_word_or_a_forecast(self):
        strings = []

        def walk(x):
            if isinstance(x, str):
                strings.append(x)
            elif isinstance(x, dict):
                for k, v in x.items():
                    if k != "reason":
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(self.p)
        for text in strings:
            self.assertIsNone(BANNED.search(text), text)
        self.assertTrue(self.p["paper_only"])
        self.assertIn("never counted", self.p["hindsight_note"])
        self.assertTrue(self.p["not_advice"])

    def test_the_payload_is_json(self):
        json.dumps(self.p, allow_nan=False)

    def test_an_empty_hound_has_an_honest_empty_record(self):
        p = tr.build(data_of([]).view("all"), now=NOW)
        self.assertEqual((p["header"]["settled"], p["header"]["roi_pct"], p["header"]["record_text"]), (0, None, "0-0"))
        self.assertEqual((p["tickets"], p["open"], p["calendar"], p["curve"]), ([], [], [], []))
        self.assertTrue(all(g["line"] == "No settled bets in this cut yet." for g in p["breakdowns"]))


class SideInference(unittest.TestCase):
    def row(self, selection, game, market="h2h"):
        return BetRow(hound_id="x", date="2026-10-01", game=game, market=market, selection=selection)

    def test_home_away_over_under(self):
        self.assertEqual(tr.infer_side(self.row("Red Sox moneyline", "Yankees at Red Sox")), "home")
        self.assertEqual(tr.infer_side(self.row("Yankees -1.5 run line", "Yankees @ Red Sox", "spreads")), "away")
        self.assertEqual(tr.infer_side(self.row("Over 8.5", "A at B", "totals")), "over")
        self.assertEqual(tr.infer_side(self.row("Under 220.5", "A at B", "totals")), "under")
        self.assertEqual(tr.infer_side(self.row("home moneyline", "")), "home")

    def test_an_unreadable_row_has_no_side_rather_than_a_guess(self):
        self.assertIsNone(tr.infer_side(self.row("Some pick", "")))
        self.assertIsNone(tr.infer_side(self.row("Cubs moneyline", "Yankees at Red Sox")))


class Compare(unittest.TestCase):
    def summaries(self):
        a = data_of([bet(i, "win" if i % 2 else "loss", hid="a") for i in range(10)], defn("house", "a", "A")).summary
        b = data_of([bet(i, "win", hid="b") for i in range(5)], defn("house", "b", "B")).summary
        c = data_of([bet(i, "loss", hid="c") for i in range(5)], defn("user", "c", "C")).summary
        none = data_of([], defn("house", "z", "Z")).summary
        return [a, b, c, none]

    def test_the_hound_is_left_out_and_empty_hounds_do_not_count(self):
        s = self.summaries()
        out = tr.compare_block(s, "a", tr._line_of(s[0]), {"label": "All-time"})
        self.assertEqual(out["house_pack"]["hounds"], 1)                    # only b: a is me, z has no bets, c is a member's
        self.assertEqual(out["leaderboard"]["hounds"], 2)                   # b and c
        self.assertEqual(out["period"], "All-time")
        self.assertGreater(out["house_pack"]["roi_pct"], out["leaderboard"]["roi_pct"])

    def test_with_nobody_else_there_is_no_comparison(self):
        s = self.summaries()
        self.assertIsNone(tr.compare_block([s[0]], "a", None, None))
        self.assertIsNone(tr.compare_block([s[0], s[3]], "a", None, None))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Route(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.hounds import router
        cls._tmp = tempfile.TemporaryDirectory()
        src = F.make_world(Path(cls._tmp.name))
        cls._patch = mock.patch.object(Sources, "default", staticmethod(lambda: src))
        cls._patch.start()
        stats.clear_cache()
        stats.get_book(src)
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()
        stats.clear_cache()
        cls._tmp.cleanup()

    def test_a_house_hound_has_a_record(self):
        r = self.client.get("/hounds/alpha/record")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["hound"]["id"], "alpha")
        self.assertTrue(body["hound"]["is_house"])
        self.assertEqual(body["season"]["id"], "all")
        self.assertEqual(body["header"]["settled"], 3)
        self.assertIs(body["paper_only"], True)
        self.assertEqual([g["group"] for g in body["breakdowns"]], ["sport", "market", "band", "role", "venue"])
        self.assertIsNotNone(body["compare"])

    def test_a_member_hound_has_one_too(self):
        r = self.client.get("/hounds/u-1/record?season=all")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["hound"]["is_house"])

    def test_unknown_hound_and_bad_season(self):
        self.assertEqual(self.client.get("/hounds/nobody/record").status_code, 404)
        self.assertEqual(self.client.get("/hounds/alpha/record?season=zzz").status_code, 422)


if __name__ == "__main__":
    unittest.main()
