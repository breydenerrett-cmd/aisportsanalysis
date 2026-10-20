"""src/pipeline/allsports_free_results.py: ESPN tennis and MMA results into the all-sports scores store, and the
member-dog settlement that reads them.

Recorded ESPN responses (tests/fixtures/espn_results/, trimmed from real fetches of 2026-10-19/20) and synthetic
cards built to ESPN's shapes; injected fetchers; every store is a temp file. Nothing touches the network or the
real stores (the forward-store guard in tests/__init__.py would raise).
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.datasvc import http
from src.hounds import user_engine as eng
from src.hounds import user_settle as st
from src.pipeline import allsports_free_results as F
from src.pipeline import allsports_scores as S
from src.providers import espn_mma_results as espn
from src.providers import espn_tennis_results as E
from src.sports import catalog
from tests._allsports_fixtures import config, read_jsonl
from tests._hounds_user_fixtures import BOOKS, DATE, EVENT, T_LOCK, board_rows, hound, utc
from tests.test_espn_mma_results import ALPHA, BRAVO, FETCHED, Server, sbout, serve_synth

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_results"
NOW = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)


def doc(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def multibook_rows(event_id, home, away, start, *, sport="tennis", league="tennis_atp_test", observed=None):
    rows = board_rows(observed or T_LOCK, event_id=event_id, home=home, away=away, start=start, sport=sport,
                      moneyline=[(b, -140, 120) for b in BOOKS])
    if sport == "tennis":
        for r in rows:
            r["league"], r["league_title"] = league, "ATP Test"
    return rows


def write_multibook(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")


def espn_doc(*matches):
    """A minimal ESPN-shaped tennis scoreboard. Each match: (id, start, status, (name_a, name_b), winner, sets)."""
    comps = []
    for match_id, start, status, players, winner, sets in matches:
        state = {"STATUS_FINAL": "post", "STATUS_RETIRED": "post", "STATUS_WALKOVER": "post",
                 "STATUS_IN_PROGRESS": "in"}.get(status, "pre")
        competitors = []
        for order, name in enumerate(players, start=1):
            side = "a" if order == 1 else "b"
            competitors.append({
                "id": f"p{match_id}{order}", "type": "athlete", "order": order,
                "winner": (winner == side) if winner else False,
                "linescores": [{"value": float(s[order - 1])} for s in sets],
                "athlete": {"displayName": name, "fullName": name}})
        comps.append({"id": str(match_id), "date": start, "startDate": start,
                      "status": {"period": len(sets), "type": {"name": status, "state": state,
                                                               "completed": state == "post"}},
                      "competitors": competitors, "round": {"displayName": "Round 1"}})
    return {"leagues": [{"name": "ATP"}], "events": [{
        "id": "999-2026", "name": "Test Open", "date": "2026-10-19T04:00Z",
        "groupings": [{"grouping": {"displayName": "Men's Singles"}, "competitions": comps}]}]}


class FakeFeed:
    """An EspnTennisFeed whose scoreboards are fixed documents; counts the dates it was asked for."""

    def __init__(self, atp=None, wta=None, error=None):
        self.docs = {"atp": atp or {"events": []}, "wta": wta or {"events": []}}
        self.error = error
        self.calls = []

    def build(self):
        def get_json(url):
            self.calls.append(url)
            if self.error:
                raise self.error
            tour = url.split("/tennis/")[1].split("/")[0]
            return self.docs[tour]
        return E.EspnTennisFeed(get_json=get_json, sleep=lambda s: None, now=lambda: NOW)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.multibook = str(self.dir / "multibook.jsonl")
        self.store = str(self.dir / "scores.jsonl")
        self.config = config()

    def put(self, *events):
        rows = []
        for ev in events:
            rows += multibook_rows(*ev[:4], **(ev[4] if len(ev) > 4 else {}))
        write_multibook(self.multibook, rows)

    def run_free(self, feed=None, now=NOW, **kw):
        kw.setdefault("env", {})
        return F.run(now=now, config=self.config, multibook_path=self.multibook, store_path=self.store,
                     tennis_feed=feed.build() if hasattr(feed, "build") else feed, **kw)

    def scores(self):
        return [r for r in read_jsonl(self.store) if r["kind"] == "score"]

    def polls(self):
        return [r for r in read_jsonl(self.store) if r["kind"] == "free_poll"]


# ---------------------------------------------------------------------------
# tennis: matching the odds feed's players to ESPN's
# ---------------------------------------------------------------------------

class TennisAgainstTheRealFixtures(Base):
    """The trimmed real 2026-10-19 ATP and WTA scoreboards."""

    def feed(self):
        return FakeFeed(atp=doc("tennis_atp_scoreboard_2026-10-19.json"),
                        wta=doc("tennis_wta_scoreboard_2026-10-19.json"))

    def test_the_odds_feeds_spellings_match_and_grade(self):
        self.put(
            ("e-cina", "Jaume Munar", "Federico Cina", "2026-10-19T10:05:00Z"),          # ESPN a=Cina, b=Munar won
            ("e-mann", "Adrian Mannarino", "Aleksandar Vukic", "2026-10-19T08:05:00Z"),   # a won
            ("e-kuku", "Stefanos Sakellaridis", "Mikhail Kukushkin", "2026-10-19T14:40:00Z"),   # a=Kukushkin won
            ("e-jacq", "Kyrian Jacquet", "Michael Mmoh", "2026-10-19T10:30:00Z"),         # retired after set one
            ("e-eala", "Alexandra Eala", "Diane Parry", "2026-10-19T11:35:00Z"),
        )
        # one WTA/ATP-style event that is not in the fixture: never graded
        result = self.run_free(self.feed())
        info = result["families"]["TENNIS"]
        self.assertEqual((info["events"], info["matched"], info["graded"]), (5, 4, 4))
        by_id = {r["event_id"]: r for r in self.scores()}
        self.assertEqual(by_id["e-cina"]["outcome"], "home")                 # Munar, listed second by ESPN
        self.assertEqual((by_id["e-cina"]["home_score"], by_id["e-cina"]["away_score"]), (1.0, 0.0))
        self.assertEqual(by_id["e-mann"]["outcome"], "home")
        self.assertEqual(by_id["e-kuku"]["outcome"], "away")
        self.assertEqual(by_id["e-jacq"]["outcome"], "home")
        self.assertIn("retirement after 1 completed set", by_id["e-jacq"]["evidence"]["rule"])
        self.assertNotIn("e-eala", by_id)                     # Eala's match is in the WTA fixture, not here
        self.assertEqual(info["unmatched"][0]["event_id"], "e-eala")      # not in the trimmed ATP/WTA slice

    def test_names_match_through_accents_reversed_order_and_initials(self):
        self.put(
            ("e1", "Munar, Jaume".replace(",", ""), "Federico Cina", "2026-10-19T10:05:00Z"),     # "Munar Jaume"
            ("e2", "A. Mannarino", "Vukić Aleksandar", "2026-10-19T08:05:00Z"),                   # initial; reversed+accent
            ("e3", "Mikhail Kukushkin", "Stefanos Sakellaridis", "2026-10-19T14:40:00Z"),
        )
        self.run_free(self.feed())
        got = {r["event_id"]: (r["outcome"], r["evidence"]["matched_by"]) for r in self.scores()}
        self.assertEqual(got["e1"][0], "home")
        self.assertIn("0.97", got["e1"][1])
        self.assertEqual(got["e2"][0], "home")
        self.assertIn("0.9", got["e2"][1])
        self.assertEqual(got["e3"][0], "home")
        self.assertIn("1", got["e3"][1])

    def test_a_retirement_before_a_set_completes_is_a_void_row_with_the_rule_named(self):
        self.put(("e-void", "Haruka Kaji", "Taylah Preston", "2026-10-17T05:50:00Z"))
        self.run_free(self.feed(), now=datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc))
        (row,) = self.scores()
        self.assertEqual((row["completed"], row["outcome"], row["home_score"], row["away_score"]),
                         (True, None, None, None))
        self.assertIn("retired before a set was completed", row["void_reason"])
        grade = S.grade_bet({"sport": "TENNIS", "market": "moneyline", "side": "home",
                             "commence_time": "2026-10-17T05:50:00Z"}, row, NOW)
        self.assertEqual(grade["result"], "VOID")
        self.assertIn("retired before a set was completed", grade["reason"])

    def test_a_match_still_being_played_or_not_started_writes_nothing(self):
        # the fixture's in-progress match is scheduled 2026-10-20T04:45Z; give the event that start
        self.put(("e-live", "Oleksandra Oliynykova", "Mary Stoiana", "2026-10-20T04:45:00Z"))
        result = self.run_free(self.feed(), now=datetime(2026, 10, 20, 5, 30, tzinfo=timezone.utc))
        self.assertEqual(self.scores(), [])
        self.assertEqual(result["families"]["TENNIS"]["pending"], 1)

    def test_an_event_espn_does_not_cover_is_unmatched_and_writes_nothing(self):
        self.put(("e-challenger", "Some Challenger Player", "Another Challenger Player", "2026-10-19T09:00:00Z",
                  {"league": "tennis_atp_challenger"}))
        result = self.run_free(self.feed())
        self.assertEqual(self.scores(), [])
        self.assertEqual(result["families"]["TENNIS"]["unmatched"][0]["reason"],
                         "no ESPN match with both names near the start time")


class TennisMatchingRules(Base):
    START = "2026-10-20T00:30:00Z"

    def run_with(self, home, away, *matches, start=None, **kw):
        self.put(("ev", home, away, start or self.START))
        feed = FakeFeed(atp=espn_doc(*matches))
        return self.run_free(feed, **kw)

    def final(self, match_id="m1", players=("Jannik Sinner", "Carlos Alcaraz"), winner="a", start=None,
              sets=((6, 4), (6, 3)), status="STATUS_FINAL"):
        return (match_id, start or "2026-10-20T00:30Z", status, players, winner, sets)

    def test_both_orientations_map_the_winner_to_the_right_side(self):
        self.run_with("Jannik Sinner", "Carlos Alcaraz", self.final(winner="a"))
        self.assertEqual(self.scores()[0]["outcome"], "home")
        os.remove(self.store)
        self.run_with("Carlos Alcaraz", "Jannik Sinner", self.final(winner="a"))
        self.assertEqual(self.scores()[0]["outcome"], "away")

    def test_one_name_matching_is_not_enough(self):
        result = self.run_with("Jannik Sinner", "Someone Else", self.final())
        self.assertEqual(self.scores(), [])
        self.assertEqual(len(result["families"]["TENNIS"]["unmatched"]), 1)

    def test_a_different_player_with_the_same_surname_does_not_match(self):
        self.run_with("Mischa Zverev", "Carlos Alcaraz", self.final(players=("Alexander Zverev", "Carlos Alcaraz")))
        self.assertEqual(self.scores(), [])

    def test_two_espn_matches_that_fit_the_same_pair_are_ambiguous_and_grade_nothing(self):
        result = self.run_with("Jannik Sinner", "Carlos Alcaraz", self.final("m1"), self.final("m2", winner="b"))
        self.assertEqual(self.scores(), [])
        self.assertIn("ambiguous", result["families"]["TENNIS"]["unmatched"][0]["reason"])

    def test_a_rematch_far_from_the_start_time_is_not_confused_for_this_one(self):
        self.run_with("Jannik Sinner", "Carlos Alcaraz", self.final("old", start="2026-10-12T10:00Z", winner="b"),
                      self.final("new"))
        (row,) = self.scores()
        self.assertEqual((row["outcome"], row["evidence"]["espn_match_id"]), ("home", "new"))

    def test_only_a_match_within_48_hours_of_the_odds_start_is_considered(self):
        self.run_with("Jannik Sinner", "Carlos Alcaraz", self.final(start="2026-10-17T10:00Z"))
        self.assertEqual(self.scores(), [])

    def test_a_walkover_is_a_void_row(self):
        self.run_with("Jannik Sinner", "Carlos Alcaraz", self.final(status="STATUS_WALKOVER", sets=()))
        (row,) = self.scores()
        self.assertIsNone(row["outcome"])
        self.assertIn("walkover", row["void_reason"])

    def test_a_final_with_no_winner_flagged_is_never_graded(self):
        result = self.run_with("Jannik Sinner", "Carlos Alcaraz", self.final(winner=None))
        self.assertEqual(self.scores(), [])
        self.assertEqual(result["families"]["TENNIS"]["unresolved"], 1)

    def test_the_row_is_in_the_scores_store_shape_and_names_its_evidence(self):
        self.run_with("Jannik Sinner", "Carlos Alcaraz", self.final())
        (row,) = self.scores()
        for key in ("kind", "observed_utc", "sport_key", "event_id", "commence_time", "home_team", "away_team",
                    "completed", "home_score", "away_score", "outcome", "scores", "last_update"):
            self.assertIn(key, row)
        self.assertEqual((row["event_id"], row["sport_key"], row["source"]), ("ev", "tennis_atp_test", "espn_tennis"))
        self.assertEqual(row["completed_utc"], "2026-10-20T06:00:00Z")
        self.assertEqual(row["completed_utc_basis"], "observed")
        self.assertEqual(row["evidence"]["espn_players"], ["Jannik Sinner", "Carlos Alcaraz"])
        self.assertEqual(S.load_index(self.store)["ev"]["outcome"], "home")


class TennisRun(Base):
    START = "2026-10-20T00:30:00Z"

    def feed(self, **kw):
        return FakeFeed(atp=espn_doc(("m1", "2026-10-20T00:30Z", "STATUS_FINAL", ("Jannik Sinner", "Carlos Alcaraz"),
                                      "a", ((6, 4), (6, 3)))), **kw)

    def setUp(self):
        super().setUp()
        self.put(("ev", "Jannik Sinner", "Carlos Alcaraz", self.START))

    def test_a_run_writes_the_result_and_a_poll_row_and_spends_no_credit(self):
        result = self.run_free(self.feed())
        self.assertEqual((result["rows"], result["credits"]), (1, 0))
        self.assertEqual([r["kind"] for r in read_jsonl(self.store)], ["score", "free_poll"])
        poll = self.polls()[0]
        self.assertEqual((poll["family"], poll["events"], poll["graded"], poll["written"]), ("TENNIS", 1, 1, 1))

    def test_a_resolved_event_is_not_asked_about_again(self):
        feed = self.feed()
        self.run_free(feed)
        asked = len(feed.calls)
        self.run_free(feed, now=NOW + timedelta(hours=3))
        self.assertEqual(len(feed.calls), asked)
        self.assertEqual(len(self.scores()), 1)

    def test_the_poll_interval_holds_a_second_run_off(self):
        feed = FakeFeed(atp=espn_doc())                                 # ESPN lists nothing for this event yet
        self.run_free(feed)
        first = len(feed.calls)
        again = self.run_free(feed, now=NOW + timedelta(minutes=20))
        self.assertEqual(len(feed.calls), first)
        self.assertIn("minutes ago", again["families"]["TENNIS"]["skipped"])
        self.run_free(feed, now=NOW + timedelta(hours=2))
        self.assertGreater(len(feed.calls), first)

    def test_plan_only_fetches_and_writes_nothing(self):
        feed = self.feed()
        result = self.run_free(feed, plan_only=True)
        self.assertEqual((feed.calls, read_jsonl(self.store)), ([], []))
        self.assertEqual(result["families"]["TENNIS"]["events"], 1)

    def test_the_kill_switch_stops_it(self):
        feed = self.feed()
        result = self.run_free(feed, env={"ALLSPORTS_CAPTURE": "0"})
        self.assertEqual(result["halt"], "disabled")
        self.assertEqual((feed.calls, read_jsonl(self.store)), ([], []))

    def test_an_espn_failure_writes_no_result_and_records_the_error(self):
        feed = self.feed(error=E.EspnTennisError("ESPN tennis scoreboard answered HTTP 503"))
        result = self.run_free(feed)
        self.assertEqual(self.scores(), [])
        self.assertIn("503", result["families"]["TENNIS"]["errors"][0])
        self.assertIn("503", self.polls()[0]["errors"][0])

    def test_the_store_is_append_only(self):
        with open(self.store, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "score", "event_id": "other", "completed": True, "home_score": 1.0,
                                 "away_score": 0.0, "commence_time": "x", "scores": None}) + "\n")
        before = Path(self.store).read_bytes()
        self.run_free(self.feed())
        self.assertTrue(Path(self.store).read_bytes().startswith(before))

    def test_a_changed_result_is_a_new_row_and_the_newest_wins(self):
        self.run_free(self.feed())
        flipped = self.feed()
        flipped.docs["atp"] = espn_doc(("m1", "2026-10-20T00:30Z", "STATUS_FINAL",
                                        ("Jannik Sinner", "Carlos Alcaraz"), "b", ((4, 6), (3, 6))))
        # drop the earlier row's completed flag from the index so the event is asked about again
        rows = [r for r in read_jsonl(self.store)]
        rows[0]["completed"] = False
        Path(self.store).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        self.run_free(flipped, now=NOW + timedelta(hours=3))
        self.assertEqual(len(self.scores()), 2)
        self.assertEqual(S.load_index(self.store)["ev"]["outcome"], "away")

    def test_events_too_new_or_too_old_are_not_looked_for(self):
        self.put(("fresh", "Jannik Sinner", "Carlos Alcaraz", iso(NOW - timedelta(minutes=5))),
                 ("old", "Jannik Sinner", "Carlos Alcaraz", iso(NOW - timedelta(days=6))),
                 ("future", "Jannik Sinner", "Carlos Alcaraz", iso(NOW + timedelta(hours=3))))
        result = self.run_free(self.feed(), plan_only=True)
        self.assertEqual(result["families"]["TENNIS"]["events"], 0)

    def test_the_other_sports_in_the_store_are_ignored(self):
        rows = multibook_rows("nba1", "Boston Celtics", "New York Knicks", "2026-10-20T00:30:00Z", sport="nba")
        rows += multibook_rows("mlb1", "Boston Red Sox", "Seattle Mariners", "2026-10-20T00:30:00Z", sport=None)
        write_multibook(self.multibook, rows)
        result = self.run_free(self.feed(), plan_only=True)
        self.assertEqual((result["families"]["TENNIS"]["events"], result["families"]["MMA"]["events"]), (0, 0))

    def test_the_odds_api_poll_never_spends_credits_on_a_free_results_family(self):
        done = [{"kind": "phase", "sport_key": "tennis_atp_us_open", "event_id": "ev", "phase": "t2h",
                 "commence_utc": self.START},
                {"kind": "phase", "sport_key": "basketball_nba", "event_id": "n1", "phase": "t2h",
                 "commence_utc": self.START}]
        cap = catalog.capture_config(self.config)
        keys = S.keys_to_poll(done, [], NOW, cap, self.config)
        self.assertEqual([k for k, _ in keys], ["basketball_nba"])


# ---------------------------------------------------------------------------
# MMA through the real ESPN provider, over recorded and synthetic cards
# ---------------------------------------------------------------------------

class MmaCase(Base):
    EVENT_ID = "600060773"
    NOW = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)

    def setUp(self):
        super().setUp()
        self.server = Server()
        self.cache = self.dir / "raw"

    def provider(self):
        fetcher = http.PoliteFetcher(cache_dir=self.cache, delay_s=0.0, opener=self.server,
                                     sleep=lambda s: None, now_iso=lambda: FETCHED)
        return espn.EspnMmaResultsProvider(fetcher)

    def serve_real_card(self):
        from src.datasvc.ufc import espn_urls
        self.server.serve(espn_urls.scoreboard("2026-10-17"), doc("mma_scoreboard_2026-10-17_trimmed.json"))
        event = doc("mma_event_600060773_trimmed.json")
        self.server.serve(espn_urls.event(self.EVENT_ID), event)
        for comp in event["competitions"]:
            self.server.serve(espn_urls.competition_status(self.EVENT_ID, comp["id"]),
                              doc(f"mma_status_{comp['id']}.json"))
        # a day with no UFC card (read when a name is not on the first scoreboard)
        self.server.serve(espn_urls.scoreboard("2026-10-16"), {"leagues": [], "events": []})

    def mma_event(self, event_id, home, away, start):
        return (event_id, home, away, start, {"sport": "mma", "league": None})

    def put_mma(self, *events):
        rows = []
        for event_id, home, away, start, _kw in events:
            rows += board_rows(T_LOCK, event_id=event_id, home=home, away=away, start=start, sport="mma",
                               moneyline=[(b, -140, 120) for b in BOOKS])
        write_multibook(self.multibook, rows)

    def go(self, **kw):
        return F.run(now=self.NOW, env={}, config=self.config, multibook_path=self.multibook,
                     store_path=self.store, mma_provider=self.provider(), families=("MMA",), **kw)


class MmaRealFixtures(MmaCase):
    """Six bouts of the real UFC Fight Night of 2026-10-17 (ESPN event 600060773) against the odds feed's names."""

    CARD = [("b-yo", "Cody Chovancek", "Su Young You"), ("b-cu", "Louis Jourdain", "Timothy Cuamba"),
            ("b-ch", "Mackenzie Stiller", "Katlyn Chookagian"), ("b-bl", "Erin Blanchfield", "Jasmine Jasudavicius"),
            ("b-bu", "Joaquin Buckley", "Mike Malott"), ("b-ba", "Marc-Andre Barriault", "Kyle Daukaus")]
    WINNER = {"b-yo": "away", "b-cu": "away", "b-ch": "away", "b-bl": "away", "b-bu": "away", "b-ba": "home"}

    def setUp(self):
        super().setUp()
        self.serve_real_card()
        events = [self.mma_event(i, h, a, "2026-10-17T21:00:00Z") for i, h, a in self.CARD]
        # a non-UFC bout on the same date and a bout of a card ESPN does not list at all
        events += [self.mma_event("b-ksw", "Dario Bellandi", "Aldo Pereira", "2026-10-17T16:00:00Z")]
        self.put_mma(*events)

    def test_every_ufc_bout_resolves_by_name_and_grades(self):
        result = self.go()
        info = result["families"]["MMA"]
        self.assertEqual((info["events"], info["matched"], info["graded"], info["void"]), (7, 6, 6, 0))
        got = {r["event_id"]: r["outcome"] for r in self.scores()}
        self.assertEqual(got, self.WINNER)

    def test_confirmed_aliases_bridge_the_three_spellings_the_odds_feed_gets_wrong(self):
        self.go()
        evidence = {r["event_id"]: r["evidence"]["basis"] for r in self.scores()}
        for event_id in ("b-yo", "b-cu", "b-ch"):
            self.assertIn("confirmed alias", evidence[event_id], event_id)

    def test_a_bout_of_another_promotion_is_unmatched_and_writes_nothing(self):
        info = self.go()["families"]["MMA"]
        self.assertEqual([u["event_id"] for u in info["unmatched"]], ["b-ksw"])
        self.assertNotIn("b-ksw", {r["event_id"] for r in self.scores()})

    def test_rows_hold_the_espn_ids_and_status_they_came_from(self):
        self.go()
        row = [r for r in self.scores() if r["event_id"] == "b-bl"][0]
        self.assertEqual((row["source"], row["completed"], row["home_score"], row["away_score"]),
                         ("espn_mma", True, 0.0, 1.0))
        self.assertEqual(row["evidence"]["provider_event_id"], self.EVENT_ID)
        self.assertEqual(row["evidence"]["provider_fight_id"], "401897729")
        self.assertIn("decision", row["evidence"]["raw_status"])
        self.assertEqual(row["completed_utc"], "2026-10-20T06:00:00Z")

    def test_a_second_run_does_not_crawl_the_card_again_for_bouts_already_resolved(self):
        self.go()
        asked = len(self.server.requests)
        self.NOW = self.NOW + timedelta(hours=2)
        self.go()
        # only the unmatched non-UFC bout is still waiting: it re-reads the two scoreboards, never the event
        # document or a bout status
        later = self.server.requests[asked:]
        self.assertTrue(later)
        self.assertTrue(all("scoreboard" in url for url in later), later)
        self.assertEqual(len(self.scores()), 6)

    def test_an_espn_outage_for_a_date_records_the_error_and_grades_nothing(self):
        from src.datasvc.ufc import espn_urls
        self.server.routes[http.canonical_url(espn_urls.scoreboard("2026-10-17"))] = (503, b"")
        info = self.go()["families"]["MMA"]
        self.assertEqual(self.scores(), [])
        self.assertTrue(info["errors"])

    def test_an_inferred_replacement_is_not_trusted_without_the_alias(self):
        # Without the confirmed alias the grader reads Chookagian's ESPN name (Cerminara) as a replacement
        # opponent: it must be HELD, never written as a void.
        saved = dict(espn.CONFIRMED_ALIASES)
        try:
            del espn.CONFIRMED_ALIASES["katlyn chookagian"]
            info = self.go()["families"]["MMA"]
        finally:
            espn.CONFIRMED_ALIASES.clear()
            espn.CONFIRMED_ALIASES.update(saved)
        self.assertNotIn("b-ch", {r["event_id"] for r in self.scores()})
        held = [u for u in info["unmatched"] if u["event_id"] == "b-ch"]
        self.assertTrue(held)


class MmaResultKinds(MmaCase):
    """Synthetic ESPN cards for the result kinds the recorded night did not contain."""

    def card(self, **bout_kw):
        serve_synth(self.server, "9000", [sbout("b1", ALPHA, BRAVO, **bout_kw)], day="2026-10-17",
                    date="2026-10-17T21:00Z")
        self.server.serve(__import__("src.datasvc.ufc.espn_urls", fromlist=["x"]).scoreboard("2026-10-16"),
                          {"leagues": [], "events": []})
        self.put_mma(self.mma_event("syn", "Alpha One", "Bravo Two", "2026-10-17T21:00:00Z"))
        return self.go()["families"]["MMA"]

    def test_a_decision_win_for_the_home_fighter(self):
        self.card(winner="a", result="decision---unanimous")
        self.assertEqual(self.scores()[0]["outcome"], "home")

    def test_a_draw_is_a_void_row(self):
        info = self.card(winner=None, result="draw")
        (row,) = self.scores()
        self.assertEqual((info["void"], row["outcome"], row["home_score"]), (1, None, None))
        self.assertIn("draw", row["void_reason"])
        grade = S.grade_bet({"sport": "MMA", "market": "moneyline", "side": "home",
                             "commence_time": "2026-10-17T21:00:00Z"}, row, self.NOW)
        self.assertEqual(grade["result"], "VOID")

    def test_a_no_contest_is_a_void_row(self):
        self.card(winner=None, result="no-contest")
        self.assertIn("no contest", self.scores()[0]["void_reason"])

    def test_a_bout_espn_calls_canceled_is_a_void_row(self):
        self.card(status="STATUS_CANCELED")
        self.assertIn("cancelled", self.scores()[0]["void_reason"])

    def test_a_bout_not_final_writes_nothing(self):
        for status in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_POSTPONED"):
            with self.subTest(status=status):
                self.setUp()
                self.card(status=status, winner="a")
                self.assertEqual(self.scores(), [])

    def test_a_replacement_opponent_is_held_not_voided(self):
        serve_synth(self.server, "9000", [sbout("b9", ALPHA, ("301", "Replacement Guy"), winner="a",
                                                result="submission")], day="2026-10-17", date="2026-10-17T21:00Z")
        from src.datasvc.ufc import espn_urls
        self.server.serve(espn_urls.scoreboard("2026-10-16"), {"leagues": [], "events": []})
        self.put_mma(self.mma_event("syn", "Alpha One", "Bravo Two", "2026-10-17T21:00:00Z"))
        info = self.go()["families"]["MMA"]
        self.assertEqual(self.scores(), [])
        self.assertIn("not trusted", info["unmatched"][0]["reason"])


# ---------------------------------------------------------------------------
# the member dog's bet, settled from the free feeds
# ---------------------------------------------------------------------------

class SettlesTennisAndMma(Base):
    """user_settle.settle over bets the engine wrote on tennis and MMA, with results from this module's rows."""

    START = "2026-10-20T23:10:00Z"
    FINAL = utc("2026-10-21T04:00:00Z")
    LATE = utc("2026-10-24T00:00:00Z")           # past 72 hours from the start

    def setUp(self):
        super().setUp()
        self.ledger = str(self.dir / "hounds.jsonl")

    def bet(self, sport_code, sport_row, league, home, away, **over):
        rows = multibook_rows(EVENT, home, away, self.START, sport=sport_row, league=league)
        eng.run(DATE, [hound(sports=[sport_code], **over)], rows, ledger=self.ledger,
                now=utc("2026-10-20T21:10:00Z"))

    def graded(self):
        return [r for r in eng.read_ledger(self.ledger) if r["kind"] == st.KIND_GRADED]

    def settle(self, now):
        return st.settle(ledger=self.ledger, now=now, close_fn=lambda b: None,
                         allsports_results=S.load_index(self.store))

    def tennis_result(self, winner, *, status="STATUS_FINAL", sets=((6, 4), (6, 3))):
        self.put((EVENT, "Jannik Sinner", "Carlos Alcaraz", self.START))
        feed = FakeFeed(atp=espn_doc(("m1", "2026-10-20T23:10Z", status, ("Jannik Sinner", "Carlos Alcaraz"),
                                      winner, sets)))
        self.run_free(feed, now=utc("2026-10-21T03:30:00Z"))

    def test_the_menu_now_offers_tennis_and_mma(self):
        from src.hounds import user_spec
        self.assertIn("TENNIS", user_spec.SPORTS)
        self.assertIn("MMA", user_spec.SPORTS)

    def test_a_tennis_underdog_win(self):
        self.bet("TENNIS", "tennis", "tennis_atp_test", "Jannik Sinner", "Carlos Alcaraz",
                 price_min=100, price_max=250)                       # the away dog at +120
        self.tennis_result("b")
        report = self.settle(self.FINAL)
        self.assertEqual(report["graded"], 1)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"]), ("WIN", 1.2))

    def test_a_tennis_underdog_loss(self):
        self.bet("TENNIS", "tennis", "tennis_atp_test", "Jannik Sinner", "Carlos Alcaraz",
                 price_min=100, price_max=250)
        self.tennis_result("a")
        self.settle(self.FINAL)
        self.assertEqual((self.graded()[0]["result"], self.graded()[0]["profit_units"]), ("LOSS", -1.0))

    def test_an_early_retirement_voids_the_bet_with_the_reason(self):
        self.bet("TENNIS", "tennis", "tennis_atp_test", "Jannik Sinner", "Carlos Alcaraz",
                 price_min=100, price_max=250)
        self.tennis_result("a", status="STATUS_RETIRED", sets=((3, 1),))
        self.settle(self.FINAL)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"]), ("VOID", 0.0))
        self.assertIn("retired before a set was completed", g["reason"])

    def test_a_retirement_after_a_set_counts_for_the_player_who_advanced(self):
        self.bet("TENNIS", "tennis", "tennis_atp_test", "Jannik Sinner", "Carlos Alcaraz",
                 price_min=100, price_max=250)
        self.tennis_result("b", status="STATUS_RETIRED", sets=((4, 6), (1, 3)))
        self.settle(self.FINAL)
        self.assertEqual(self.graded()[0]["result"], "WIN")

    def test_an_unmatched_match_never_grades_and_voids_after_72_hours(self):
        self.bet("TENNIS", "tennis", "tennis_atp_test", "Jannik Sinner", "Carlos Alcaraz",
                 price_min=100, price_max=250)
        self.put((EVENT, "Jannik Sinner", "Carlos Alcaraz", self.START))
        self.run_free(FakeFeed(atp=espn_doc(("m1", "2026-10-20T23:10Z", "STATUS_FINAL",
                                             ("Rafael Nadal", "Roger Federer"), "a", ((6, 0), (6, 0))))),
                      now=utc("2026-10-21T03:30:00Z"))
        self.assertEqual(self.scores(), [])
        report = self.settle(self.FINAL)
        self.assertEqual((report["graded"], report["pending"]), (0, 1))
        self.settle(self.LATE)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"]), ("VOID", 0.0))
        self.assertIn("results feed", g["reason"])
        self.assertIn("72", g["reason"])

    def test_mma_decision_and_draw(self):
        for event_bouts, expect in (({"winner": "b", "result": "kotko"}, "WIN"), ({"winner": None, "result": "draw"}, "VOID")):
            with self.subTest(expect=expect):
                self.setUp()
                self.bet("MMA", "mma", None, "Alpha One", "Bravo Two", price_min=100, price_max=250)
                server = Server()
                serve_synth(server, "9000", [sbout("b1", ALPHA, BRAVO, **event_bouts)], day="2026-10-20",
                            date="2026-10-20T23:10Z")
                from src.datasvc.ufc import espn_urls
                server.serve(espn_urls.scoreboard("2026-10-19"), {"leagues": [], "events": []})
                write_multibook(self.multibook, [dict(r, event_id=EVENT) for r in board_rows(
                    T_LOCK, event_id=EVENT, home="Alpha One", away="Bravo Two", start=self.START, sport="mma",
                    moneyline=[(b, -140, 120) for b in BOOKS])])
                fetcher = http.PoliteFetcher(cache_dir=self.dir / "raw", delay_s=0.0, opener=server,
                                             sleep=lambda s: None, now_iso=lambda: FETCHED)
                F.run(now=utc("2026-10-21T03:30:00Z"), env={}, config=self.config, multibook_path=self.multibook,
                      store_path=self.store, mma_provider=espn.EspnMmaResultsProvider(fetcher), families=("MMA",))
                self.settle(self.FINAL)
                self.assertEqual(self.graded()[0]["result"], expect)


class CatalogAndWiring(unittest.TestCase):
    def test_tennis_and_mma_settle_from_free_results_and_are_on_the_dog_menu(self):
        for code in ("TENNIS", "MMA"):
            fam = catalog.family(code)
            self.assertEqual(fam["settles"], "free_results", code)
            self.assertTrue(fam["dog_menu"], code)
            self.assertTrue(fam["scores_verified"], code)
            self.assertIn("ESPN", fam["settles_note"], code)
        self.assertEqual(F.free_families(), ("TENNIS", "MMA"))

    def test_boxing_and_other_stay_off_the_menu(self):
        for code in ("BOXING", "OTHER"):
            self.assertFalse(catalog.family(code)["dog_menu"], code)

    def test_a_free_result_row_is_never_shown_as_a_live_score(self):
        from src.sports import allsports_view
        event = {"event_id": "ev", "family": "TENNIS"}
        row = {"event_id": "ev", "home_score": 1.0, "away_score": 0.0, "completed": True,
               "observed_utc": "2026-10-20T05:50:00Z", "source": "espn_tennis"}
        self.assertNotIn("score", allsports_view._with_score(dict(event), {"ev": row}, NOW))
        plain = dict(row)
        del plain["source"]
        self.assertIn("score", allsports_view._with_score(dict(event), {"ev": plain}, NOW))

    def test_the_cli_scores_command_runs_the_free_results_too(self):
        from unittest import mock
        from src import cli
        with mock.patch("src.pipeline.allsports_scores.run", return_value={
                "keys": [], "polled": [], "credits": 0, "rows": 0, "skipped": {}, "halt": None}), \
                mock.patch("src.pipeline.allsports_free_results.run", return_value={
                    "families": {"TENNIS": {"events": 2, "matched": 1, "graded": 1, "void": 0, "unmatched": [1],
                                            "written": 1, "errors": [], "skipped": None}}}) as free:
            code = cli.main(["allsports", "scores", "--plan"])
        self.assertEqual(code, cli.EXIT_OK)
        free.assert_called_once_with(plan_only=True)


if __name__ == "__main__":
    unittest.main()
