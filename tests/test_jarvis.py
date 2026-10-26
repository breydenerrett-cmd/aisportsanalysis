"""Jarvis, the owner's pre-game briefing (src/jarvis, api/jarvis.py): the owner rulings, pinned.

Every store is a temp file; no network, no paid API, no model call (the clock is injected). The stories pinned here:

  * a row observed AFTER the as-of time is never read (price, lineup or model), and the control run that DOES include it
    shows the test can fail;
  * nothing at -200 or worse is ever offered, including when only the AVERAGE price is that short;
  * one side per game: singles keep one side, a parlay never has two legs from one game;
  * every probability says EXPERIMENTAL until its source is registered as calibrated;
  * every published pick is filed with source "jarvis" and the real publish time, once;
  * no profit claims, no "Bet Check", the 21+ / 1-800-GAMBLER line is present;
  * "no data" where a store has nothing; a prop for a player not in the posted lineup is left out.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi import HTTPException
    HAS_FASTAPI = True
except ImportError:  # CI's no-FastAPI run
    HAS_FASTAPI = False

from src.hounds.apprentice import store
from src.jarvis import board as bd
from src.jarvis import brief, context
from src.jarvis import cli as jarvis_cli

T0 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)      # the open capture
T1 = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)      # the current capture
AS_OF = datetime(2026, 10, 26, 18, 30, tzinfo=timezone.utc)
LATE = datetime(2026, 10, 26, 19, 0, tzinfo=timezone.utc)    # after AS_OF
NOW = datetime(2026, 10, 26, 18, 31, tzinfo=timezone.utc)
DATE = "2026-10-26"
BOOKS = ["b1", "b2", "b3", "b4", "b5", "b6"]

E1 = {"event_id": "e1", "away_team": "Milwaukee Brewers", "home_team": "Tampa Bay Rays", "commence_time": "2026-10-27T00:10:00Z"}
E2 = {"event_id": "e2", "away_team": "New York Yankees", "home_team": "Boston Red Sox", "commence_time": "2026-10-26T23:10:00Z"}
E3 = {"event_id": "e3", "away_team": "Los Angeles Dodgers", "home_team": "San Diego Padres", "commence_time": "2026-10-26T23:40:00Z"}


def stamp(moment):
    return moment.isoformat().replace("+00:00", "Z")


def mb(event, when, book, market=None, **prices):
    row = {"observed_utc": stamp(when), "event_id": event["event_id"], "commence_time": event["commence_time"],
           "home_team": event["home_team"], "away_team": event["away_team"], "book": book,
           "book_last_update": stamp(when)}
    if market:
        row["market"] = market
    row.update(prices)
    return row


def board(event, when, *, ml=None, spread=None, total=None):
    """``ml``: {book: (home, away)}, default every book -110/-110. spread: (home_line, {book or "*": (home, away)})."""
    rows = []
    for book in BOOKS:
        home, away = (ml or {}).get(book, (-110, -110))
        rows.append(mb(event, when, book, home_price=home, away_price=away))
    if spread:
        line, prices = spread
        for book in BOOKS:
            home, away = prices.get(book, prices["*"])
            rows.append(mb(event, when, book, "spreads", home_line=str(line), home_price=home,
                           away_line=str(-line), away_price=away))
    if total:
        line, prices = total
        for book in BOOKS:
            over, under = prices.get(book, prices["*"])
            rows.append(mb(event, when, book, "totals", total=str(line), over_price=over, under_price=under))
    return rows


def lines(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


class JarvisCase(unittest.TestCase):
    """A temp data root with two playable games and one whose favourite is too short."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for sub in ("data/processed", "data/watch", "evidence", "app"):
            (self.root / sub).mkdir(parents=True)
        env = {"AISPORTS_DATA_DIR": str(self.root / "data"), "JARVIS_EVIDENCE_DIR": str(self.root / "evidence"),
               "JARVIS_DIR": str(self.root / "app" / "jarvis"), "APP_DB_PATH": str(self.root / "app" / "app.db")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = self.root / "app" / "app.db"
        self.multibook = self.root / "data" / "processed" / "odds_multibook.jsonl"
        self.rows = self.default_rows()
        self.props = self.default_props()
        self.keep_lineups_file = False
        self.write_all()

    # ---- fixtures -------------------------------------------------------

    def default_rows(self):
        rows = []
        # E1: away +105 at b6 beats a -110/-110 market; the home spread is a heavy favourite (banned), the away side pays
        rows += board(E1, T0, ml={"b6": (-125, 112)}, spread=(1.5, {"*": (-230, 190), "b4": (-230, 200)}),
                      total=(8.5, {"*": (-110, -110), "b5": (104, -125)}))
        rows += board(E1, T1, ml={"b6": (-125, 105)}, spread=(1.5, {"*": (-230, 190), "b4": (-230, 200)}),
                      total=(8.5, {"*": (-110, -110), "b5": (104, -125)}))
        # E2: b5 offered the Yankees at +115 at the open and has since come in; home +108 at b6 beats a -110/-110 market now
        rows += board(E2, T0, ml={"b5": (-135, 115)})
        rows += board(E2, T1, ml={"b6": (108, -128)})
        # E3: best price -190 but the AVERAGE is -200 or worse; -190 alone would pass a best-price-only check
        rows += board(E3, T1, ml={"b1": (-190, 170), **{b: (-215, 180) for b in BOOKS[1:]}})
        return rows

    def default_props(self):
        out = []
        for player in ("Player A", "Ghost Hitter"):
            for book in BOOKS:
                over, under = (-105, -115) if book == "b6" else (-125, 105)
                for side, price in (("Over", over), ("Under", under)):
                    out.append({"away_team": E1["away_team"], "book": book, "book_last_update": stamp(T1), "commence_time": E1["commence_time"],
                                "event_id": "e1", "game_date": DATE, "home_team": E1["home_team"], "line": "0.5", "market": "batter_hits",
                                "observed_utc": stamp(T1), "player": player, "price": price, "selection": f"{player}:{side}", "side": side})
        return out

    def watch(self, name, rows):
        with (self.root / "data" / "watch" / f"{name}_watch.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(lines(rows))

    def write_all(self):
        self.multibook.write_text(lines(self.rows), encoding="utf-8")
        (self.root / "data/processed/batter_props.jsonl").write_text(lines(self.props), encoding="utf-8")
        (self.root / "data/processed/event_game_map.jsonl").write_text(lines([
            {"event_id": "e1", "game_pk": "900001", "resolved": True, "ambiguous": False, "resolved_utc": stamp(T0)}]), encoding="utf-8")
        (self.root / "data/processed/boxscores_2026.jsonl").write_text(lines(
            [{"player_id": 10 + i, "player_name": n} for i, n in enumerate(["Player A", "Player B"])]
            + [{"player_id": 1, "player_name": "Away Starter"}, {"player_id": 2, "player_name": "Home Starter"}]), encoding="utf-8")
        if not self.keep_lineups_file:
            for name in ("lineups", "probables", "umpires", "transactions"):
                (self.root / "data" / "watch" / f"{name}_watch.jsonl").write_text("", encoding="utf-8")
            self.watch("probables", [{"game_pk": 900001, "away_probable_id": 1, "home_probable_id": 2, "fetched_utc": stamp(T0)}])
            self.watch("lineups", [{"game_pk": 900001, "away_lineup": [10, 11], "home_lineup": [12, 13], "fetched_utc": stamp(T1)}])
            self.watch("umpires", [{"game_pk": 900001, "home_plate_umpire": "Crew Chief", "observed_utc": stamp(T1), "crew": []}])
            self.watch("transactions", [{"team": "MIL", "player": "Some Reliever", "category": "il_placement", "transaction_id": 1,
                                         "first_seen_utc": stamp(T1 - timedelta(hours=5)), "player_id": 99}])
        (self.root / "data/processed/weather_forecast.jsonl").write_text(lines([{
            "game_pk": 900001, "observed_utc": stamp(T1), "temp_f": 70.0, "wind_mph": 5.0, "wind_from_deg": 10,
            "precip_probability_pct": 0, "roof": "open"}]), encoding="utf-8")

    def build(self, as_of=AS_OF, now=NOW, **kw):
        self.write_all()
        return brief.build_briefing(DATE, as_of, now=now, multibook_path=self.multibook, **kw)

    def all_prices(self, b):
        prices = []
        for item in b["singles"] + b["parlays"]:
            for leg in (item["legs"] if item["kind"] == "parlay" else [item]):
                prices += [leg["best_price"], leg["average_price"], leg["max_acceptable_price"]]
        return prices


class FrozenKnowledge(JarvisCase):
    def test_a_price_captured_after_the_as_of_time_is_ignored(self):
        before = self.build(AS_OF)
        self.rows.append(mb(E2, LATE, "b2", home_price=125, away_price=-145))
        self.rows.append(mb(E1, LATE, "b2", home_price=118, away_price=-138))
        after = self.build(AS_OF)
        self.assertNotIn(125, [s["best_price"] for s in after["singles"]])
        self.assertNotIn(118, [s["best_price"] for s in after["singles"]])
        self.assertEqual(before["inputs"]["game_quotes_read"], after["inputs"]["game_quotes_read"])
        self.assertEqual(before["singles"], after["singles"])

    def test_control_the_same_row_is_read_when_the_as_of_time_allows_it(self):
        """If this fails the freeze test above proves nothing: the late row must be able to matter."""
        base = self.build(AS_OF)
        self.rows.append(mb(E2, LATE, "b2", home_price=125, away_price=-145))
        later_as_of = LATE + timedelta(minutes=5)
        later = self.build(later_as_of, now=later_as_of + timedelta(minutes=1))
        self.assertGreater(later["inputs"]["game_quotes_read"], base["inputs"]["game_quotes_read"])
        self.assertIn(125, [s["best_price"] for s in later["singles"]])

    def test_a_lineup_posted_after_the_as_of_time_is_not_context(self):
        self.watch("lineups", [{"game_pk": 900001, "away_lineup": [10], "home_lineup": [12], "fetched_utc": stamp(LATE)}])
        names = context.player_names()
        early = context.game_context(E1, "900001", AS_OF, names)
        late = context.game_context(E1, "900001", LATE + timedelta(minutes=1), names)
        self.assertEqual([s["id"] for s in early["lineups"]["away"]], [10, 11])
        self.assertEqual([s["id"] for s in late["lineups"]["away"]], [10])

    def test_a_game_that_has_started_by_the_as_of_time_is_left_out(self):
        started = datetime(2026, 10, 26, 23, 20, tzinfo=timezone.utc)
        b = brief.build_briefing(DATE, started, now=started, multibook_path=self.multibook)
        self.assertNotIn("e2", [g["event_id"] for g in b["games"]])

    def test_a_model_forecast_dated_the_game_day_is_not_known_the_night_before(self):
        row = {"date": DATE, "model": "POSTSEASON_PAGE_V1", "round": "World Series",
               "next_game": {"away": "MIL", "home": "TB", "date": DATE, "home_chance": 0.9, "number": 3,
                             "starter_input_class": "CONFIRMED_CURRENT"}}
        path = self.root / "evidence" / "postseason_forecasts.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertIsNone(context.postseason_home_chance(E1, AS_OF))
        row["date"] = "2026-10-25"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.assertEqual(context.postseason_home_chance(E1, AS_OF)["home_probability"], 0.9)

    def test_the_as_of_time_cannot_be_in_the_future(self):
        with self.assertRaises(ValueError):
            brief.build_briefing(DATE, NOW + timedelta(hours=2), now=NOW, multibook_path=self.multibook)


class NoMinusTwoHundred(JarvisCase):
    def test_nothing_at_minus_200_or_worse_is_offered_anywhere(self):
        b = self.build()
        self.assertTrue(b["singles"])
        self.assertTrue(all(p > -200 for p in self.all_prices(b)), self.all_prices(b))
        self.assertGreater(b["excluded"].get("price_at_the_ban", 0), 0)

    def test_a_best_price_that_passes_but_an_average_that_does_not_is_still_banned(self):
        b = self.build()
        self.assertNotIn("e3", [s["event_id"] for s in b["singles"]])
        rows = bd.read_game_rows(DATE, AS_OF, "mlb", self.multibook)
        sels = [s for s in bd.all_selections(bd.board_at(rows, AS_OF))
                if s["event_id"] == "e3" and s["side"] == "home" and s["market"] == "moneyline"]
        self.assertEqual(sels[0]["best_price"], -190)
        self.assertLessEqual(sels[0]["average_price"], -200)
        self.assertFalse(bd.price_allowed(sels[0]["best_price"], sels[0]["average_price"]))

    def test_the_maximum_acceptable_price_is_clamped_short_of_the_ban(self):
        self.assertEqual(bd.max_price(0.5, 0.01), 102)
        self.assertEqual(bd.max_price(0.9, 0.01), -199)
        self.assertEqual(bd.max_price(0.99, 0.01), -199)
        for p in (0.3, 0.45, 0.5, 0.6, 0.7, 0.85):
            price = bd.max_price(p, 0.01)
            self.assertGreaterEqual(bd.expected_value(p, price), 0.01 - 1e-9, (p, price))

    def test_a_spread_favourite_at_minus_230_is_never_a_pick(self):
        b = self.build()
        for s in b["singles"]:
            self.assertFalse(s["sport_market"] == "spread" and s["side"] == "home")


class OneSidePerGame(JarvisCase):
    def test_singles_never_hold_two_sides_of_one_game(self):
        b = self.build()
        sides = {}
        for s in b["singles"]:
            if s["sport_market"] in ("moneyline", "spread"):
                sides.setdefault(s["event_id"], []).append(s["side"])
        for event, taken in sides.items():
            self.assertEqual(len(taken), 1, f"{event}: the away moneyline and the away run line are one position, not two")

    def test_keep_first_drops_the_opposite_side_and_the_redundant_one(self):
        def rec(market, side, line, ev):
            return {"event_id": "e1", "market": market, "side": side, "line": line, "player": None, "ev": ev, "books": 8,
                    "observed": T1, "fair_spread": 0.01, "fair_all": None, "model": None, "home_team": "H", "away_team": "A",
                    "commence_time": E1["commence_time"]}
        eligible = [rec("moneyline", "home", None, 0.05), rec("spread", "away", -1.5, 0.04), rec("total", "over", 8.5, 0.03),
                    rec("total", "under", 8.5, 0.02)]
        kept, shown, dropped = brief.choose_singles(eligible, {}, AS_OF)
        self.assertEqual([(r["market"], r["side"]) for r in kept], [("moneyline", "home"), ("total", "over")])
        self.assertEqual(len(dropped), 2)

    def test_a_parlay_takes_one_leg_per_game(self):
        b = self.build()
        self.assertTrue(b["parlays"], b.get("parlay_note"))
        for p in b["parlays"]:
            self.assertEqual(len(p["legs"]), 2)
            self.assertEqual(len({leg["event_id"] for leg in p["legs"]}), 2)
        self.assertLessEqual(len(b["parlays"]), 2)

    def test_a_one_game_slate_has_no_parlay_and_says_why(self):
        self.rows = [r for r in self.rows if r["event_id"] == "e1"]
        b = self.build()
        self.assertEqual(b["parlays"], [])
        self.assertIn("one game", b["parlay_note"])


class ExperimentalLabel(JarvisCase):
    def test_every_pick_says_experimental_today(self):
        b = self.build()
        for item in b["singles"] + b["parlays"]:
            self.assertEqual(item["label"], "EXPERIMENTAL")
        self.assertIn("EXPERIMENTAL", brief.render(b))

    def test_a_source_registered_as_calibrated_drops_the_label(self):
        with mock.patch.object(brief, "CALIBRATED_SOURCES", frozenset({"consensus"})):
            b = self.build()
        consensus = [s for s in b["singles"] if s["probability_source"] == "consensus"]
        self.assertTrue(consensus)
        self.assertTrue(all(s["label"] == "calibrated" for s in consensus))

    def test_a_model_far_from_the_market_caps_confidence_at_low(self):
        row = {"date": "2026-10-25", "model": "POSTSEASON_PAGE_V1", "round": "World Series",
               "next_game": {"away": "MIL", "home": "TB", "date": DATE, "home_chance": 0.30, "number": 3,
                             "starter_input_class": "CONFIRMED_CURRENT"}}
        (self.root / "evidence" / "postseason_forecasts.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        b = self.build()
        ml = [s for s in b["singles"] if s["event_id"] == "e1" and s["sport_market"] == "moneyline"]
        self.assertTrue(ml)
        self.assertEqual(ml[0]["probability_source"], "model")
        self.assertEqual(ml[0]["confidence"], "LOW")
        self.assertAlmostEqual(ml[0]["probability"], 0.70, places=2)


class RealOdds(JarvisCase):
    def test_a_pick_shows_best_average_books_capture_time_and_a_max_price(self):
        b = self.build()
        ml = next(s for s in b["singles"] if s["sport_market"] == "moneyline" and s["event_id"] == "e1")
        self.assertEqual((ml["best_price"], ml["best_book"], ml["books"]), (105, "b6", 6))
        self.assertIsNotNone(ml["average_price"])
        self.assertEqual(ml["captured_utc"], "2026-10-26T18:00:00Z")
        self.assertRegex(ml["captured"], r"^\[\[w:2026-10-26T18:00:00Z\]\]$")
        self.assertIsNotNone(ml["max_acceptable_price"])
        self.assertLess(ml["break_even"], ml["probability"])
        self.assertIn(ml["confidence"], ("HIGH", "MEDIUM", "LOW"))

    def test_consensus_leaves_the_best_price_book_out(self):
        rows = bd.read_game_rows(DATE, AS_OF, "mlb", self.multibook)
        sels = bd.all_selections(bd.board_at(rows, AS_OF))
        away = next(s for s in sels if s["event_id"] == "e1" and s["market"] == "moneyline" and s["side"] == "away")
        self.assertEqual(away["other_books"], 5)
        self.assertAlmostEqual(away["fair"], 0.5, places=3)          # five books at -110/-110; b6's +105 is not in it

    def test_a_vanished_edge_is_listed_with_open_and_now(self):
        b = self.build()
        gone = [v for v in b["vanished_edges"] if v["label_text"] == "New York Yankees moneyline"]
        self.assertEqual(len(gone), 1)
        self.assertEqual(gone[0]["open"]["best_price"], 115)
        self.assertEqual(gone[0]["now"]["best_price"], -110)
        self.assertEqual(gone[0]["now"]["why_not"], "ev_below_floor")
        self.assertIn("moved", gone[0]["what_happened"])
        still = [v for v in b["vanished_edges"] if v["label_text"] == "Milwaukee Brewers moneyline"]
        self.assertEqual(still, [], "an edge that is still a pick has not vanished")

    def test_thin_markets_are_left_out_and_counted(self):
        self.props = [r for r in self.props if r["book"] in ("b1", "b2")]
        b = self.build()
        self.assertEqual([s for s in b["singles"] if s["player"]], [])
        self.assertGreater(b["excluded"].get("thin_market", 0), 0)

    def test_an_implausibly_good_consensus_quote_is_not_a_pick(self):
        self.rows.append(mb(E2, T1, "b2", home_price=500, away_price=-700))     # one wild quote against five -110s
        b = self.build()
        self.assertNotIn(500, [s["best_price"] for s in b["singles"]])


class ContextFromStoredData(JarvisCase):
    def test_context_comes_only_from_the_watch_files_and_says_no_data_otherwise(self):
        b = self.build()
        g1 = next(g for g in b["games"] if g["event_id"] == "e1")["context"]
        self.assertEqual(g1["probables"]["home"]["name"], "Home Starter")
        self.assertTrue(g1["lineups_posted"])
        self.assertEqual(g1["umpire"], "Crew Chief")
        self.assertEqual(g1["weather"]["temp_f"], 70.0)
        self.assertEqual(g1["transactions"][0]["player"], "Some Reliever")
        self.assertEqual(g1["injuries"], "no data")
        g2 = next(g for g in b["games"] if g["event_id"] == "e2")["context"]
        self.assertIsNone(g2["game_pk"])
        self.assertIn("game_pk", " ".join(g2["missing"]))
        self.assertIn("no data", brief.render(b))

    def test_a_prop_for_a_player_not_in_the_posted_lineup_is_left_out(self):
        b = self.build()
        players = [s["player"] for s in b["singles"] if s["player"]]
        self.assertIn("Player A", players)
        self.assertNotIn("Ghost Hitter", players)
        self.assertGreater(b["excluded"].get("not_in_posted_lineup", 0), 0)

    def test_without_posted_lineups_a_prop_is_low_confidence_and_says_so(self):
        self.keep_lineups_file = True
        self.write_all()
        (self.root / "data" / "watch" / "lineups_watch.jsonl").write_text("", encoding="utf-8")
        b = brief.build_briefing(DATE, AS_OF, now=NOW, multibook_path=self.multibook)
        props = [s for s in b["singles"] if s["player"]]
        self.assertTrue(props)
        self.assertTrue(all(p["confidence"] == "LOW" for p in props))
        self.assertTrue(any("not posted" in line for p in props for line in p["reasons"]))


class PaperOnlyWording(JarvisCase):
    def test_no_profit_claims_no_bet_check_and_the_help_line_is_there(self):
        b = self.build()
        text = brief.render(b)
        self.assertIn("1-800-GAMBLER", text)
        self.assertIn("21+", text)
        self.assertIn("Paper bets only", text)
        for banned in ("bet check", "guarantee", "sure thing", "profit", " lock"):
            self.assertNotIn(banned, text.lower())
        self.assertNotIn("bet check", json.dumps(b).lower())

    def test_each_pick_has_reasons_how_it_could_lose_and_what_to_avoid(self):
        b = self.build()
        for item in b["singles"] + b["parlays"]:
            for key in ("reasons", "could_lose", "avoid"):
                self.assertTrue(item[key], (item["label_text"], key))

    def test_times_are_tokens_in_the_json_and_pacific_in_the_text(self):
        b = self.build()
        self.assertRegex(b["headline"], r"\[\[w:2026-10-26T18:30:00Z\]\]")
        text = brief.resolve_tokens(brief.render(b))
        self.assertNotIn("[[w:", text)
        self.assertIn("Mon Oct 26 11:30 AM PT", text)
        self.assertEqual(brief.pacific_text(datetime(2026, 12, 1, 20, 0, tzinfo=timezone.utc)), "Tue Dec 1 12:00 PM PT")

    def test_a_board_that_does_not_exist_is_not_reported_as_nothing_cleared(self):
        self.write_all()
        b = brief.build_briefing("2026-10-30", AS_OF, now=NOW, multibook_path=self.multibook)
        self.assertEqual(b["status"], "no_board")
        self.assertIn("no priced pre-game board", b["headline"])


class FilingWithTheApprentice(JarvisCase):
    def test_every_published_pick_is_filed_once_with_the_real_publish_time(self):
        b = self.build()
        brief.file_picks(b, now=NOW, db=self.db)
        recs = store.recommendations(db=self.db)
        self.assertEqual(len(recs), len(b["singles"]) + len(b["parlays"]))
        self.assertTrue(all(r["source"] == "jarvis" and r["recommended_utc"] == bd.iso(NOW) for r in recs))
        self.assertTrue(all(item["recommendation_id"] for item in b["singles"] + b["parlays"]))
        parlay = next(r for r in recs if len(r["legs"]) == 2)
        self.assertEqual(len({leg["event_id"] for leg in parlay["legs"]}), 2)
        for key in ("event_id", "market", "side", "line", "price", "selection", "sport"):
            self.assertIn(key, recs[0]["legs"][0])

    def test_running_it_again_files_nothing_new_and_keeps_the_first_time(self):
        first = brief.file_picks(self.build(), now=NOW, db=self.db)
        later = brief.file_picks(self.build(), now=NOW + timedelta(hours=1), db=self.db)
        self.assertEqual(len(store.recommendations(db=self.db)), len(first["filed"]))
        self.assertTrue(all(f["status"] == "already_filed" for f in later["filed"]))
        self.assertTrue(all(f["published_utc"] == bd.iso(NOW) for f in later["filed"]))

    def test_the_apprentice_grade_a_needs_the_recommendation_to_come_first(self):
        from src.hounds.apprentice import model
        b = brief.file_picks(self.build(), now=NOW, db=self.db)
        rec = store.get_recommendation(b["singles"][0]["recommendation_id"], db=self.db)
        leg = dict(rec["legs"][0])
        lesson = {"bettor": "Brey", "placed_utc": bd.iso(NOW + timedelta(minutes=5)), "legs": [leg]}
        rec_one_leg = {**rec, "legs": [leg]}
        self.assertEqual(model.evidence_grade(lesson, rec_one_leg)[0], "A")
        early = {**lesson, "placed_utc": bd.iso(NOW - timedelta(minutes=5))}
        self.assertEqual(model.evidence_grade(early, rec_one_leg)[0], "B")


class Cli(JarvisCase):
    def args(self, **kw):
        base = dict(date=DATE, as_of=stamp(AS_OF), sport="mlb", no_file=False, as_json=False,
                    out_dir=str(self.root / "out"), db=str(self.db))
        base.update(kw)
        return Namespace(**base)

    def run_cli(self, **kw):
        self.write_all()
        out = []
        code = jarvis_cli.execute(self.args(**kw), out=out.append, now=NOW)
        return code, "\n".join(out)

    def test_it_prints_in_pacific_saves_the_json_and_files(self):
        code, text = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("PT", text)
        self.assertNotIn("[[w:", text)
        saved = json.loads(next((self.root / "out").glob(f"{DATE}__latest.json")).read_text(encoding="utf-8"))
        self.assertEqual(saved["schema"], "jarvis_briefing_v1")
        self.assertTrue(saved["published"])
        self.assertTrue(store.recommendations(db=self.db))

    def test_the_dry_run_writes_and_files_nothing(self):
        code, _ = self.run_cli(no_file=True)
        self.assertEqual(code, 0)
        self.assertFalse((self.root / "out").exists())
        self.assertFalse(self.db.exists())

    def test_a_bad_date_or_time_is_an_error(self):
        self.assertEqual(self.run_cli(date="26-10-2026")[0], 2)
        self.assertEqual(self.run_cli(as_of="not a time")[0], 2)

    def test_the_command_is_registered(self):
        from src import cli
        args = cli.build_parser().parse_args(["jarvis", "brief", "--date", DATE, "--as-of", stamp(AS_OF)])
        self.assertEqual((args.command, args.jarvis_command, args.date), ("jarvis", "brief", DATE))
        self.assertIn("jarvis", cli.COMMANDS)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class OwnerApi(JarvisCase):
    def test_the_routes_use_the_one_admin_gate(self):
        from api import auth, jarvis
        gates = {dep.call for route in jarvis.router.routes for dep in route.dependant.dependencies}
        self.assertIn(auth._require_admin, gates)
        self.assertEqual({r.path for r in jarvis.router.routes}, {"/admin/jarvis/brief"})
        self.assertIs(jarvis._require_admin, auth._require_admin)

    def test_it_is_mounted_in_the_app(self):
        from api.app import app
        self.assertIn("/admin/jarvis/brief", app.openapi()["paths"])

    def test_get_is_a_404_until_a_briefing_exists_then_returns_it(self):
        from api import jarvis
        with self.assertRaises(HTTPException) as ctx:
            jarvis.get_brief(DATE, _admin=None)
        self.assertEqual(ctx.exception.status_code, 404)
        b = self.build()
        brief.save(b)
        self.assertEqual(jarvis.get_brief(DATE, _admin=None)["as_of"], b["as_of"])
        with self.assertRaises(HTTPException) as bad:
            jarvis.get_brief("tomorrow", _admin=None)
        self.assertEqual(bad.exception.status_code, 422)

    def test_post_refuses_a_future_as_of(self):
        from api import jarvis
        future = stamp(datetime.now(timezone.utc) + timedelta(days=1))
        with self.assertRaises(HTTPException) as ctx:
            jarvis.post_brief(jarvis.BriefBody(date=DATE, as_of=future), _admin=None, _limit=None)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_post_builds_files_and_saves(self):
        from api import jarvis
        self.write_all()
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        with mock.patch.object(bd, "default_multibook_path", return_value=self.multibook),                 mock.patch.object(jarvis, "datetime", Frozen):
            result = jarvis.post_brief(jarvis.BriefBody(date=DATE, as_of=stamp(AS_OF)), _admin=None, _limit=None)
        self.assertTrue(result["published"])
        self.assertTrue(store.recommendations(db=self.db))
        self.assertTrue(brief.load_latest(DATE))


if __name__ == "__main__":
    unittest.main()
