"""Seasons: a date window over the forward bets (config/seasons.json, src/hounds/seasons.py).

Owner decision 2026-10-19: the leaderboard mixed models that began on Aug 31, on Sep 9 and on Oct 18, so a 1-0
model showed +94% ROI and could top the board. Season 2 (Oct 18 on) is the default view, Season 1 and all-time
stay one click away, nothing is deleted, and a model needs 10 settled bets in the view to be ranked.

What this file holds the server to:
  * the window: both ends inclusive, a bet on the boundary day lands on the right side, replay bets are never in
    a season's forward figures, and the seasons add up to all-time;
  * the SAME summarize code path produces the windowed figures (no forked math), while the referee's verdict,
    status and retirement stay all-time;
  * ranking: 10 settled bets (win, loss or push) in the view; open and void bets do not count; ranked models
    come first in the server's order;
  * the routes: the default is the newest season, ``?season=`` takes s1 / s2 / all (anything else is a 422), the
    bet list defaults to every bet and takes the same filter, and every payload says which season it is;
  * the saved copy is kept per season and a cold start answers the season that was asked for;
  * the digest names only ranked models as hottest or coldest when any are ranked.

No FastAPI needed except for the route classes, which skip without it (Linux CI has none).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import digest as digest_mod, seasons, stats
from src.hounds.ledgers import Bet, Sources
from tests import _hounds_fixtures as F

if HAS_FASTAPI:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.hounds import router


DEFN = {"id": "h", "name": "H", "tagline": "t", "kind": "house", "category": "stats", "style": "x",
        "sports": ["mlb"], "markets": ["h2h"], "rule_text": "r"}


def bet(day, result, *, price=100, segment="forward", stamp=None, hid="h"):
    """A bet at +100 (a win is +1.0 unit, a loss -1.0) on slate date ``day``; ``result`` None is an open ticket."""
    return Bet(hound_id=hid, segment=segment, date=day, decision_utc=stamp or f"{day}T15:00:00+00:00",
               result=result, price=price, bet_id=f"{hid}-{day}-{result}-{segment}-{stamp or ''}")


def seasoned(bets, season):
    return stats.summarize_window(DEFN, bets, {}, "2026-10-19", season, full=stats.summarize(DEFN, bets, {}, "2026-10-19"))


# ---------------------------------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------------------------------

class TheSeasonConfig(unittest.TestCase):
    def test_the_shipped_config_is_the_owners_decision(self):
        raw = json.loads(seasons.config_path().read_text(encoding="utf-8"))
        self.assertEqual(raw, [
            {"id": "s1", "label": "Season 1", "start": "2026-08-31", "end": "2026-10-17"},
            {"id": "s2", "label": "Season 2", "start": "2026-10-18", "end": None}])
        self.assertEqual(seasons.ids(), ["s1", "s2"])
        self.assertEqual(seasons.default_id(), "s2")

    def test_both_ends_are_inclusive_and_a_boundary_day_lands_on_one_side(self):
        for day, season, want in (
                ("2026-10-17", "s1", True), ("2026-10-17", "s2", False),
                ("2026-10-18", "s2", True), ("2026-10-18", "s1", False),
                ("2026-08-31", "s1", True), ("2026-08-30", "s1", False), ("2026-08-30", "s2", False),
                ("2027-03-01", "s2", True), ("2027-03-01", "s1", False),
                ("2026-10-18T03:00:00Z", "s2", True),            # a timestamp is read by its date
                ("", "s2", False), (None, "s1", False), ("junk", "s2", False),
                ("2026-08-30", "all", True), ("", "all", True)):
            with self.subTest(day=day, season=season):
                self.assertIs(seasons.in_window(day, season), want)

    def test_resolve_defaults_to_the_newest_season_and_rejects_the_unknown(self):
        self.assertEqual(seasons.resolve(None), "s2")
        self.assertEqual(seasons.resolve(""), "s2")
        self.assertEqual(seasons.resolve("  "), "s2")
        self.assertEqual(seasons.resolve("S1"), "s1")
        self.assertEqual(seasons.resolve("all"), "all")
        self.assertIsNone(seasons.resolve("s3"))
        self.assertIsNone(seasons.resolve("2026"))

    def test_a_missing_or_broken_config_falls_back_to_the_same_two_seasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "seasons.json"
            for text in (None, "not json", "[]", '{"id": "s1"}', '[{"id": "x", "start": "nope"}]'):
                if text is not None:
                    bad.write_text(text, encoding="utf-8")
                with self.subTest(text=text), mock.patch.object(seasons, "config_path", lambda: bad):
                    self.assertEqual(seasons.ids(), ["s1", "s2"])
                    self.assertTrue(seasons.in_window("2026-10-18", "s2"))

    def test_the_meta_block_names_the_season_and_the_ranking_bar(self):
        meta = seasons.meta("s2")
        self.assertEqual((meta["id"], meta["label"], meta["start"], meta["end"]), ("s2", "Season 2", "2026-10-18", None))
        self.assertEqual((meta["default"], meta["min_ranked_bets"], meta["all_time"]), ("s2", 10, False))
        self.assertEqual([x["id"] for x in meta["available"]], ["s1", "s2", "all"])
        self.assertTrue(seasons.meta("all")["all_time"])


# ---------------------------------------------------------------------------------------------------
# the math
# ---------------------------------------------------------------------------------------------------

class TheWindowedFigures(unittest.TestCase):
    def setUp(self):
        self.bets = [
            bet("2026-10-15", "win"), bet("2026-10-16", "loss"), bet("2026-10-17", "win"),     # Season 1, last day included
            bet("2026-10-18", "loss", stamp="2026-10-18T15:00:00+00:00"),                      # Season 2, first day included
            bet("2026-10-18", "loss", stamp="2026-10-18T18:00:00+00:00"),
            bet("2026-10-19", "win"),
            bet("2026-10-19", None),                                                           # an open ticket
            bet("2026-10-18", "win", segment="replay"),                                        # a rehearsal inside the window
            bet("2026-10-10", "loss", segment="replay"),
        ]
        self.all = stats.summarize(DEFN, self.bets, {}, "2026-10-19")
        self.s1 = seasoned(self.bets, "s1")
        self.s2 = seasoned(self.bets, "s2")

    def test_each_season_counts_only_its_own_forward_bets(self):
        r1, r2 = self.s1.summary.record, self.s2.summary.record
        self.assertEqual((r1.bets, r1.wins, r1.losses, r1.units_recorded_price), (3, 2, 1, 1.0))
        self.assertEqual((r2.bets, r2.wins, r2.losses, r2.units_recorded_price), (3, 1, 2, -1.0))

    def test_replay_bets_are_in_no_forward_figure_and_the_seasons_add_up_to_all_time(self):
        full = self.all.summary.record
        self.assertEqual(full.bets, 6)                                             # the two replay rows are not forward bets
        self.assertEqual(self.s1.summary.record.bets + self.s2.summary.record.bets, full.bets)
        self.assertEqual(round(self.s1.summary.record.units_recorded_price + self.s2.summary.record.units_recorded_price, 4),
                         full.units_recorded_price)
        self.assertEqual(self.all.summary.replay.bets, 2)                          # replay is its own block, all-time
        self.assertEqual(self.s2.summary.replay.bets, 2)

    def test_the_all_time_view_is_the_original_object_not_a_second_calculation(self):
        data = stats.with_seasons(self.all, DEFN, self.bets, {}, "2026-10-19")
        self.assertIs(data.view("all"), data)
        self.assertEqual(data.view("s2").summary.record, self.s2.summary.record)
        self.assertIs(data.view("not-a-season"), data)                              # an unknown id never breaks a page

    def test_the_form_block_is_windowed_too(self):
        self.assertEqual(self.s2.summary.form["last10"], ["L", "L", "W"])
        self.assertEqual(self.s1.summary.form["last10"], ["W", "L", "W"])
        self.assertEqual(self.s2.summary.form["streak"], {"kind": "W", "length": 1})
        self.assertEqual(self.s2.summary.form["last_day"]["date"], "2026-10-19")
        self.assertEqual(self.s1.summary.form["last_day"]["date"], "2026-10-17")

    def test_open_tickets_belong_to_the_season_of_their_date(self):
        self.assertEqual((self.s1.summary.open_bets, self.s2.summary.open_bets, self.all.summary.open_bets), (0, 1, 1))

    def test_the_series_and_the_ticket_list_are_windowed(self):
        self.assertEqual([p.date for p in self.s2.series], ["2026-10-17", "2026-10-18", "2026-10-19"])
        self.assertEqual([p.date for p in self.s1.series], ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17"])
        self.assertEqual(self.s2.series[-1].cum_units_recorded_price, -1.0)
        s2_dates = sorted({b.date for b in self.s2.bets})
        self.assertEqual(s2_dates, ["2026-10-18", "2026-10-19"])
        self.assertEqual(sum(1 for b in self.s2.bets if b.segment == "replay"), 1)  # the dated-in-window rehearsal row only

    def test_the_referee_stays_all_time(self):
        for view in (self.s1, self.s2):
            self.assertEqual(view.summary.verdict.label, self.all.summary.verdict.label)
            self.assertEqual(view.summary.verdict.sentence, self.all.summary.verdict.sentence)
            self.assertEqual(view.summary.verdict.n, self.all.summary.verdict.n)
            self.assertEqual((view.summary.status, view.summary.retired, view.summary.verified),
                             (self.all.summary.status, self.all.summary.retired, self.all.summary.verified))
            self.assertEqual((view.summary.first_bet_utc, view.summary.last_bet_utc),
                             (self.all.summary.first_bet_utc, self.all.summary.last_bet_utc))

    def test_a_model_with_nothing_in_the_window_has_an_empty_record_not_a_missing_one(self):
        only_old = [bet("2026-09-01", "win"), bet("2026-09-02", "loss")]
        view = seasoned(only_old, "s2")
        self.assertEqual((view.summary.record.bets, view.summary.settled, view.summary.ranked, view.summary.open_bets), (0, 0, False, 0))
        self.assertIsNone(view.summary.form)
        self.assertEqual(view.series, [])
        self.assertEqual(view.summary.verdict.label, stats.summarize(DEFN, only_old, {}, "2026-10-19").summary.verdict.label)


class TheRankingBar(unittest.TestCase):
    def view(self, bets):
        return seasoned(bets, "s2").summary

    def days(self, n, result="win"):
        return [bet(f"2026-10-{18 + i // 3:02d}", result, stamp=f"2026-10-{18 + i // 3:02d}T{10 + i % 3}:00:00+00:00") for i in range(n)]

    def test_ten_settled_bets_rank_a_model_and_nine_do_not(self):
        self.assertEqual(seasons.MIN_RANKED_BETS, 10)
        nine, ten = self.view(self.days(9)), self.view(self.days(10))
        self.assertEqual((nine.settled, nine.ranked), (9, False))
        self.assertEqual((ten.settled, ten.ranked), (10, True))

    def test_pushes_count_but_open_and_void_tickets_do_not(self):
        rows = self.days(8) + [bet("2026-10-19", "push"), bet("2026-10-19", "void"), bet("2026-10-19", None), bet("2026-10-19", None)]
        s = self.view(rows)
        self.assertEqual((s.settled, s.ranked, s.open_bets), (9, False, 2))
        s = self.view(rows + [bet("2026-10-19", "push")])
        self.assertEqual((s.settled, s.ranked), (10, True))

    def test_a_one_and_oh_start_is_a_record_not_a_rank(self):
        s = self.view([bet("2026-10-18", "win", price=400)])
        self.assertEqual((s.record.bets, s.record.wins, s.settled, s.ranked), (1, 1, 1, False))
        self.assertGreater(s.record.units_recorded_price, 0)                       # the units exist; the page just does not rank on them

    def test_the_bar_is_per_view_so_a_veteran_can_be_ranked_all_time_and_warming_in_season_2(self):
        rows = [bet(f"2026-09-{d:02d}", "win") for d in range(1, 21)] + [bet("2026-10-18", "loss")]
        self.assertTrue(seasoned(rows, "s1").summary.ranked)
        self.assertFalse(seasoned(rows, "s2").summary.ranked)
        self.assertTrue(stats.summarize(DEFN, rows, {}, "2026-10-19").summary.ranked)


# ---------------------------------------------------------------------------------------------------
# the book, the routes and the saved copy, on the synthetic world
# ---------------------------------------------------------------------------------------------------

class WorldBase(unittest.TestCase):
    """The synthetic world (tests/_hounds_fixtures.py) under a test seasons file that puts the world's bets on
    both sides of a boundary: Season 1 ends 2026-09-30 and Season 2 starts 2026-10-01, the day of alpha's
    three settled bets, charlie's and the user hound's. Delta's only bet (2026-09-20) is Season 1's."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src = F.make_world(root / "world")
        cfg = root / "seasons.json"
        cfg.write_text(json.dumps([
            {"id": "s1", "label": "Season 1", "start": "2026-08-31", "end": "2026-09-30"},
            {"id": "s2", "label": "Season 2", "start": "2026-10-01", "end": None}]), encoding="utf-8")
        self.snapshot = root / "volume" / "hounds_public_cache.json"
        self._patches = [
            mock.patch.object(seasons, "config_path", lambda: cfg),
            mock.patch.dict(os.environ, {stats.ENV_SNAPSHOT_PATH: str(self.snapshot)}),
            mock.patch.object(Sources, "default", staticmethod(lambda: self.src))]
        for p in self._patches:
            p.start()
        stats.clear_cache()
        self.book = stats.get_book(self.src)

    def tearDown(self):
        stats.clear_cache()
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


class TheBookPerSeason(WorldBase):
    def rec(self, hid, season):
        return self.book.hounds[hid].view(season).summary.record

    def test_alphas_three_settled_bets_are_season_2s_and_deltas_one_is_season_1s(self):
        self.assertEqual((self.rec("alpha", "s2").bets, self.rec("alpha", "s1").bets, self.rec("alpha", "all").bets), (3, 0, 3))
        self.assertEqual((self.rec("delta", "s2").bets, self.rec("delta", "s1").bets, self.rec("delta", "all").bets), (0, 1, 1))

    def test_a_rehearsal_dated_inside_a_season_is_not_in_that_seasons_forward_record(self):
        # charlie's replay loss is dated 2026-09-28 (Season 1) and its forward win 2026-10-01 (Season 2)
        self.assertEqual((self.rec("charlie", "s1").bets, self.rec("charlie", "s2").bets), (0, 1))
        self.assertEqual(self.book.hounds["charlie"].view("s1").summary.replay.bets, 1)   # still reported, apart

    def test_every_season_and_all_time_sum_to_the_same_forward_bets(self):
        for hid in self.book.hounds:
            with self.subTest(hid=hid):
                parts = sum(self.rec(hid, s).bets for s in ("s1", "s2"))
                self.assertEqual(parts, self.rec(hid, "all").bets)

    def test_the_default_leaderboard_view_changes_the_numbers_the_all_time_view_keeps(self):
        s2 = {s.id: s for s in stats.leaderboard(self.book, "s2")}
        al = {s.id: s for s in stats.leaderboard(self.book, "all")}
        self.assertEqual(s2["delta"].record.bets, 0)
        self.assertEqual(al["delta"].record.bets, 1)
        self.assertEqual(s2["delta"].verdict.label, al["delta"].verdict.label)

    def test_ranked_models_come_first_in_the_servers_order(self):
        with mock.patch.object(seasons, "MIN_RANKED_BETS", 2):
            stats.clear_cache()
            book = stats.get_book(self.src)
        order = stats.leaderboard(book, "s2")
        flags = [s.ranked for s in order]
        self.assertIn(True, flags)
        self.assertEqual(flags, sorted(flags, reverse=True), "a model that is not ranked sits above one that is")
        self.assertEqual([s.id for s in order if s.ranked], ["alpha"])


class TheSavedCopyIsKeyedBySeason(WorldBase):
    def test_the_file_holds_one_leaderboard_and_one_series_per_season_and_all_time(self):
        self.assertTrue(stats.write_snapshot(self.book))
        snap = json.loads(self.snapshot.read_text(encoding="utf-8"))
        self.assertEqual(snap["version"], stats.SNAPSHOT_VERSION)
        self.assertEqual(sorted(snap["views"]), ["all", "s1", "s2"])
        for sid, view in snap["views"].items():
            self.assertEqual(view["leaderboard"]["season"]["id"], sid)
            self.assertEqual(view["series"]["season"]["id"], sid)

    def test_each_season_reads_back_its_own_numbers(self):
        stats.write_snapshot(self.book)

        def bets(season, hid):
            payload = stats.saved_payload("leaderboard", season=season)
            return next(h for h in payload["hounds"] if h["id"] == hid)["record"]["bets"]

        self.assertEqual((bets("s2", "alpha"), bets("s1", "alpha"), bets("all", "alpha")), (3, 0, 3))
        self.assertEqual((bets("s2", "delta"), bets("s1", "delta"), bets("all", "delta")), (0, 1, 1))
        # a caller that never heard of seasons (the share page) keeps its all-time numbers
        self.assertEqual(bets(None, "delta"), 1)

    def test_a_season_the_copy_does_not_hold_is_not_answered_from_another(self):
        stats.write_snapshot(self.book)
        self.assertIsNone(stats.saved_payload("leaderboard", season="s9"))
        self.assertIsNone(stats.saved_payload("series", ids=["alpha"], season="s9"))

    def test_the_series_copy_follows_the_season_too(self):
        stats.write_snapshot(self.book)
        s2 = stats.saved_payload("series", ids=["alpha", "delta"], season="s2")["series"]
        s1 = stats.saved_payload("series", ids=["alpha", "delta"], season="s1")["series"]
        self.assertEqual((len(s2["alpha"]), len(s2["delta"])), (2, 0))
        self.assertEqual((len(s1["alpha"]), len(s1["delta"])), (0, 2))

    def test_an_old_format_copy_is_ignored_not_misread(self):
        stats.write_snapshot(self.book)
        data = json.loads(self.snapshot.read_text(encoding="utf-8"))
        old = {**{k: v for k, v in data.items() if k != "views"}, "version": 1,
               "leaderboard": data["views"]["all"]["leaderboard"], "series": data["views"]["all"]["series"]}
        self.snapshot.write_text(json.dumps(old), encoding="utf-8")
        self.assertIsNone(stats.load_snapshot())
        self.snapshot.write_text(json.dumps({**data, "views": [1]}), encoding="utf-8")
        self.assertIsNone(stats.load_snapshot())


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoutes(WorldBase):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def get(self, url, status=200):
        r = self.client.get(url)
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def hound(self, body, hid):
        return next(h for h in body["hounds"] if h["id"] == hid)

    def test_the_default_is_the_newest_season(self):
        body = self.get("/hounds")
        self.assertEqual(body["season"]["id"], "s2")
        self.assertEqual(body["season"]["label"], "Season 2")
        self.assertEqual(self.hound(body, "alpha")["record"]["bets"], 3)
        self.assertEqual(self.hound(body, "delta")["record"]["bets"], 0)
        self.assertEqual(self.get("/hounds?season=s2"), body)
        self.assertEqual(self.get("/hounds?season="), body)

    def test_season_1_and_all_time_are_one_parameter_away(self):
        s1, al = self.get("/hounds?season=s1"), self.get("/hounds?season=all")
        self.assertEqual((s1["season"]["id"], al["season"]["id"]), ("s1", "all"))
        self.assertEqual((self.hound(s1, "alpha")["record"]["bets"], self.hound(s1, "delta")["record"]["bets"]), (0, 1))
        self.assertEqual((self.hound(al, "alpha")["record"]["bets"], self.hound(al, "delta")["record"]["bets"]), (3, 1))

    def test_an_unknown_season_is_a_422_on_every_route(self):
        for url in ("/hounds?season=s3", "/hounds/alpha?season=zzz", "/hounds/alpha/bets?season=zzz", "/hounds/series?ids=alpha&season=zzz"):
            with self.subTest(url=url):
                self.get(url, status=422)

    def test_each_hound_summary_says_whether_it_is_ranked_and_on_how_many_settled_bets(self):
        alpha = self.hound(self.get("/hounds"), "alpha")
        self.assertEqual((alpha["settled"], alpha["ranked"]), (3, False))

    def test_the_verdict_badge_is_the_same_in_every_view_and_carries_its_all_time_count(self):
        labels = {self.hound(self.get(f"/hounds?season={s}"), "alpha")["verdict"]["label"] for s in ("s1", "s2", "all")}
        self.assertEqual(len(labels), 1)
        ns = {self.hound(self.get(f"/hounds?season={s}"), "alpha")["verdict"]["n"] for s in ("s1", "s2", "all")}
        self.assertEqual(len(ns), 1)

    def test_one_hound_defaults_to_season_2_and_takes_the_same_parameter(self):
        d2, d1, da = (self.get(f"/hounds/alpha{q}") for q in ("", "?season=s1", "?season=all"))
        self.assertEqual((d2["season"]["id"], d1["season"]["id"], da["season"]["id"]), ("s2", "s1", "all"))
        self.assertEqual((d2["record"]["bets"], d1["record"]["bets"], da["record"]["bets"]), (3, 0, 3))
        self.assertEqual((len(d2["series"]), len(d1["series"])), (2, 0))
        self.assertEqual((d2["bets"]["total"], d1["bets"]["total"]), (5, 0))

    def test_the_bet_list_defaults_to_every_bet_and_a_season_narrows_it(self):
        self.assertEqual(self.get("/hounds/delta/bets")["total"], 1)                 # no season: the whole record
        self.assertEqual(self.get("/hounds/delta/bets?season=s2")["total"], 0)
        self.assertEqual(self.get("/hounds/delta/bets?season=s1")["total"], 1)
        self.assertEqual(self.get("/hounds/delta/bets?season=all")["total"], 1)
        alpha = self.get("/hounds/alpha/bets?season=s2&segment=forward")
        self.assertEqual(alpha["total"], 4)                                          # three graded and one open
        self.assertTrue(all(b["date"] >= "2026-10-01" for b in alpha["items"]))
        self.assertEqual(self.get("/hounds/alpha/bets?season=s2&status=open")["total"], 1)
        self.assertEqual(self.get("/hounds/delta/bets")["season"]["id"], "all")

    def test_the_series_route_follows_the_season(self):
        s2 = self.get("/hounds/series?ids=alpha,delta")
        s1 = self.get("/hounds/series?ids=alpha,delta&season=s1")
        self.assertEqual(s2["season"]["id"], "s2")
        self.assertEqual((len(s2["series"]["alpha"]), len(s2["series"]["delta"])), (2, 0))
        self.assertEqual((len(s1["series"]["alpha"]), len(s1["series"]["delta"])), (0, 2))

    def test_a_cold_start_answers_from_the_copy_of_the_season_asked_for(self):
        stats.write_snapshot(self.book)
        stats._CACHE["book"] = None
        stats._BG.update(error=None, failed_at=0.0, thread=None)
        with mock.patch.object(stats, "refresh_async", return_value=True):
            default = self.get("/hounds")
            s1 = self.get("/hounds?season=s1")
            series = self.get("/hounds/series?ids=delta&season=s1")
        self.assertIs(default["stale"], True)
        self.assertEqual((default["season"]["id"], self.hound(default, "delta")["record"]["bets"]), ("s2", 0))
        self.assertEqual((s1["season"]["id"], self.hound(s1, "delta")["record"]["bets"]), ("s1", 1))
        self.assertEqual(len(series["series"]["delta"]), 2)

    def test_a_cold_start_with_no_copy_is_warming_and_still_names_the_season(self):
        stats._CACHE["book"] = None
        stats._BG.update(error=None, failed_at=0.0, thread=None)
        with mock.patch.object(stats, "refresh_async", return_value=True):
            body = self.get("/hounds?season=s1")
        self.assertIs(body["warming_up"], True)
        self.assertEqual(body["season"]["id"], "s1")


# ---------------------------------------------------------------------------------------------------
# the digest
# ---------------------------------------------------------------------------------------------------

def d_hound(hid, name, wins, losses, units, ranked):
    return {"id": hid, "name": name, "category": "stats", "ranked": ranked,
            "verdict": {"label": "TOO EARLY"}, "record": {"bets": wins + losses, "wins": wins, "losses": losses,
                                                          "units_average_price": units, "units_recorded_price": units}}


class TheDigestNamesRankedModelsWhenThereAreAny(unittest.TestCase):
    def test_a_hot_start_on_a_few_bets_is_not_named_hottest_while_a_ranked_model_exists(self):
        hounds = [d_hound("a", "Newcomer", 3, 0, 4.5, False), d_hound("b", "Veteran", 8, 5, 2.0, True),
                  d_hound("c", "Slump", 2, 9, -6.0, True), d_hound("d", "Rookie Cold", 0, 3, -3.0, False)]
        post = digest_mod.build_post({"hounds": hounds, "as_of": "2026-10-30"})
        self.assertIn("Hottest dog: Veteran 8-5 season, +2.0u", post)
        self.assertIn("Ice cold: Slump 2-9 season, -6.0u", post)
        self.assertNotIn("Newcomer", post)
        self.assertNotIn("Rookie Cold", post)

    def test_with_nobody_ranked_the_whole_race_is_considered_as_before(self):
        hounds = [d_hound("a", "Newcomer", 3, 0, 4.5, False), d_hound("d", "Rookie Cold", 0, 3, -3.0, False)]
        post = digest_mod.build_post({"hounds": hounds, "as_of": "2026-10-20"})
        self.assertIn("Hottest dog: Newcomer 3-0 season, +4.5u", post)
        self.assertIn("Ice cold: Rookie Cold 0-3 season, -3.0u", post)

    def test_an_old_payload_with_no_ranked_flag_behaves_as_it_always_did(self):
        hounds = [{k: v for k, v in d_hound("a", "Old Faithful", 5, 2, 3.0, True).items() if k != "ranked"}]
        self.assertIn("Hottest dog: Old Faithful", digest_mod.build_post({"hounds": hounds, "as_of": "2026-10-20"}))

    def test_the_last_seven_days_window_uses_the_same_ranked_pool(self):
        hounds = [d_hound("a", "Newcomer", 3, 0, 4.5, False), d_hound("b", "Veteran", 8, 5, 2.0, True)]
        window = {"a": {"wins": 3, "losses": 0, "units": 3.0}, "b": {"wins": 4, "losses": 2, "units": 1.0}}
        post = digest_mod.build_post({"hounds": hounds, "as_of": "2026-10-30"}, window=window)
        self.assertIn("Hottest dog: Veteran 4-2 last 7 days, +1.0u", post)


if __name__ == "__main__":
    unittest.main()
