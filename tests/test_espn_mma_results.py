"""Tests for the ESPN result source (src/providers/espn_mma_results.py), its
wiring into `ufc autograde`, and the 2026-09-22 / 2026-09-26 reproduction.

No network. A real `PoliteFetcher` (temp cache, no delay) sits in front of a fake
opener that serves the saved ESPN responses by canonical URL, so a request count
here is a count of requests that would have reached ESPN. Every ledger and
results path is a temp path; nothing reads or writes the real stores.

Fixtures (tests/fixtures/espn_mma/), all real ESPN responses unless marked:
  * 2026-09-26, UFC Fight Night Rosas Jr. vs Barcelos (event 600061266, 12 bouts,
    all final): scoreboard_2026-09-26.json, event_600061266.json, statuses
    (3 `competition_*_status.json`, 9 `w1_status_*.json`).
  * 2026-09-22, Contender Series season 10 week 7 (event 600060738, 5 bouts, all
    final), captured live 2026-10-03T19:32Z: w5_scoreboard_2026-09-22.json,
    w5_event_600060738.json, w5_status_*.json.
  * 2026-10-03, UFC 332 (event 600061182, 14 bouts, none fought when captured):
    scoreboard_2026-10-03.json, event_600061182.json and the scheduled status
    w1_status_scheduled_401912278.json. The "once ESPN marks them final" variant
    is built from these by flipping winner flags and statuses (marked SYNTHETIC).
  * w5_athlete_5060505.json: ESPN's athlete record for "Mick Parkin".
Synthetic cards (marked in code) cover the result kinds ESPN has not produced
since the fixtures were taken.
"""

from __future__ import annotations

import contextlib
import copy
import email.message
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src import cli
from src.appstate import card_ledger
from src.datasvc import http
from src.datasvc.ufc import espn_urls, fighters, schedule
from src.pipeline import ufc_autograde as ag
from src.pipeline import ufc_results
from src.providers import espn_mma_results as espn
from src.report import ufc_card as ufc_report

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_mma"
D0922, D0926, D1003 = "2026-09-22", "2026-09-26", "2026-10-03"
FETCHED = "2026-10-04T04:30:00Z"
AFTER_0926 = datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc)
AFTER_1003 = datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc)

EV0926, EV0922, EV1003 = "600061266", "600060738", "600061182"

# The published picks of the real ledger (evidence/cards_mma_v1.jsonl), copied so
# no test ever reads it: (game_id, home, away, side picked, locked price, bout start).
PICKS = {
    D0922: [
        ("3acf", "Piero Guaylupo", "Callum Connor", "home", -116.47, "2026-09-22T23:40:00Z"),
        ("a3a8", "Emilio Quissua", "Damian Piwowarczyk", "away", -134.93, "2026-09-22T22:00:00Z"),
    ],
    D0926: [
        ("1a8d", "Robert Bryczek", "Rodolfo Vieira", "away", -170.54, "2026-09-26T23:15:00Z"),
        ("b2fd", "Christian Edwards", "Rodolfo Bellato", "away", -178.46, "2026-09-26T22:50:00Z"),
        ("d19d", "Raoni Barcelos", "Raul Rosas Jr", "away", -161.59, "2026-09-26T20:30:00Z"),
        ("511f", "Sedriques Dumas", "Mickey Gall", "away", -144.75, "2026-09-26T20:30:00Z"),
        ("57b6", "Ailin Perez", "Norma Dumont", "home", -143.32, "2026-09-26T20:30:00Z"),
    ],
    D1003: [
        ("e3ca", "Imanol Rodriguez", "Alden Coria", "home", -142.63, "2026-10-03T23:40:00Z"),
        ("2239", "Johnny Walker", "Michael Parkin", "home", -116.17, "2026-10-03T21:40:00Z"),
        ("4a46", "Marvin Vettori", "Ismail Naurdiev", "away", -138.49, "2026-10-03T20:30:00Z"),
    ],
}
# What a person typed on 2026-10-01 (data/historical/ufc_results.jsonl).
HAND = {
    D0922: [("Piero Guaylupo vs Callum Connor", "win", "Piero Guaylupo"),
            ("Damian Piwowarczyk vs Emilio Quissua", "win", "Damian Piwowarczyk")],
    D0926: [("Rodolfo Vieira vs Robert Bryczek", "win", "Rodolfo Vieira"),
            ("Christian Edwards vs Rodolfo Bellato", "win", "Christian Edwards"),
            ("Raul Rosas Jr vs Raoni Barcelos", "win", "Raul Rosas Jr"),
            ("Mickey Gall vs Sedriques Dumas", "cancelled", None),
            ("Ailin Perez vs Norma Dumont", "win", "Ailin Perez")],
}


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()


def fixture(name):
    return json.loads(fixture_bytes(name).decode("utf-8"))


# ---------------------------------------------------------------------------
# a fake ESPN in front of a real PoliteFetcher
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body
        self.headers = email.message.Message()
        self.headers["content-type"] = "application/json"

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Server:
    """Serves bodies by canonical URL and records every request that reaches it.
    A URL the test did not serve is a loud failure: an unexpected request."""

    def __init__(self):
        self.routes = {}
        self.requests = []

    def serve(self, url, body, status=200):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.routes[http.canonical_url(url)] = (status, body)

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requests.append(url)
        if url not in self.routes:
            raise AssertionError(f"the test did not serve {url}")
        status, body = self.routes[url]
        return FakeResponse(status, body)

    def count(self, fragment=""):
        return sum(1 for url in self.requests if fragment in url)


def empty_scoreboard():
    return {"leagues": [{"id": "3321", "name": "Ultimate Fighting Championship"}],
            "events": [], "provider": {"id": "100"}}


def completed_status_file(bout_id):
    original = f"competition_{bout_id}_status.json"
    return original if (FIXTURES / original).exists() else f"w1_status_{bout_id}.json"


def serve_0926(server):
    server.serve(espn_urls.scoreboard(D0926), fixture_bytes("scoreboard_2026-09-26.json"))
    event = fixture_bytes(f"event_{EV0926}.json")
    server.serve(espn_urls.event(EV0926), event)
    for comp in json.loads(event)["competitions"]:
        server.serve(espn_urls.competition_status(EV0926, comp["id"]),
                     fixture_bytes(completed_status_file(comp["id"])))


def serve_0922(server):
    server.serve(espn_urls.scoreboard(D0922), fixture_bytes("w5_scoreboard_2026-09-22.json"))
    event = fixture_bytes(f"w5_event_{EV0922}.json")
    server.serve(espn_urls.event(EV0922), event)
    for comp in json.loads(event)["competitions"]:
        server.serve(espn_urls.competition_status(EV0922, comp["id"]),
                     fixture_bytes(f"w5_status_{comp['id']}.json"))


# ---------------------------------------------------------------------------
# SYNTHETIC ESPN-shaped cards: every result kind, built to the real shapes
# ---------------------------------------------------------------------------

_STATES = {"STATUS_SCHEDULED": ("pre", False), "STATUS_IN_PROGRESS": ("in", False),
           "STATUS_FINAL": ("post", True), "STATUS_CANCELED": ("post", False),
           "STATUS_POSTPONED": ("pre", False)}


def _type(name):
    state, completed = _STATES[name]
    return {"id": "1", "name": name, "state": state, "completed": completed,
            "description": name, "detail": name, "shortDetail": name}


def sbout(bout_id, a, b, *, status="STATUS_FINAL", winner=None, result=None,
          period=3, clock=300.0, board_winner="same", board_ids=None):
    """One synthetic bout. a, b = (athlete id, name). `winner`: "a" / "b" / None.
    `board_winner` / `board_ids` make the scoreboard differ from the event."""
    return {"id": bout_id, "a": a, "b": b, "status": status, "winner": winner,
            "result": result, "period": period, "clock": clock,
            "board_winner": winner if board_winner == "same" else board_winner,
            "board_ids": board_ids}


def synth_board(event_id, bouts, date="2026-09-26T21:00Z", name="Synthetic Fight Night"):
    comps = []
    for bout in bouts:
        ids = bout["board_ids"] or (bout["a"], bout["b"])
        entries = []
        for order, (side, (aid, aname)) in enumerate((("a", ids[0]), ("b", ids[1])), start=1):
            entries.append({
                "id": aid, "uid": f"s:3301~a:{aid}", "type": "athlete", "order": order,
                "winner": bout["board_winner"] == side,
                "athlete": {"fullName": aname, "displayName": aname,
                            "shortName": aname[0] + ". " + aname.split()[-1]}})
        comps.append({"id": bout["id"], "date": date, "competitors": entries,
                      "status": {"type": _type(bout["status"])}})
    return {"leagues": [{"id": "3321", "name": "Ultimate Fighting Championship"}],
            "events": [{"id": event_id, "name": name, "date": date,
                        "status": {"type": _type("STATUS_FINAL")}, "competitions": comps}]}


def synth_event(event_id, bouts, date="2026-09-26T21:00Z", name="Synthetic Fight Night"):
    base = "http://sports.core.api.espn.com/v2/sports/mma/leagues/ufc"
    comps = []
    for number, bout in enumerate(bouts, start=1):
        comps.append({
            "$ref": f"{base}/events/{event_id}/competitions/{bout['id']}?lang=en&region=us",
            "id": bout["id"], "date": date, "description": "3 Rnd (5-5-5)",
            "type": {"id": "970", "text": "Bantamweight"},
            "competitors": [
                {"id": bout["a"][0], "order": 1, "winner": bout["winner"] == "a"},
                {"id": bout["b"][0], "order": 2, "winner": bout["winner"] == "b"}],
            "status": {"$ref": f"{base}/events/{event_id}/competitions/{bout['id']}/status?lang=en&region=us"},
            "format": {"regulation": {"periods": 3}}, "matchNumber": number,
            "cardSegment": {"id": "173", "description": "Main Card", "name": "main"}})
    return {"$ref": f"{base}/events/{event_id}?lang=en&region=us", "id": event_id, "date": date,
            "name": name, "shortName": "UFC Fight Night",
            "season": {"$ref": f"{base}/seasons/2026?lang=en&region=us"},
            "venues": [{"$ref": f"{base}/venues/77?lang=en&region=us"}],
            "status": {"type": _type("STATUS_FINAL")}, "competitions": comps}


def synth_status(bout):
    doc = {"clock": bout["clock"] if bout["status"] == "STATUS_FINAL" else 0.0,
           "displayClock": "-", "period": bout["period"] if bout["status"] == "STATUS_FINAL" else 0,
           "type": _type(bout["status"]), "result": {}}
    if bout["result"]:
        doc["result"] = {"id": 1, "name": bout["result"], "displayName": bout["result"]}
    return doc


def serve_synth(server, event_id, bouts, *, day="2026-09-26", date="2026-09-26T21:00Z",
                board_day=None):
    """Serve a synthetic card: its scoreboard under `board_day` (default `day`)."""
    server.serve(espn_urls.scoreboard(board_day or day), synth_board(event_id, bouts, date))
    server.serve(espn_urls.event(event_id), synth_event(event_id, bouts, date))
    for bout in bouts:
        server.serve(espn_urls.competition_status(event_id, bout["id"]), synth_status(bout))


ALPHA, BRAVO = ("101", "Alpha One"), ("102", "Bravo Two")
SYNTH_PICK = [("s1", "Alpha One", "Bravo Two", "home", -150.0, "2026-09-26T20:00:00Z")]


# ---------------------------------------------------------------------------
# base case: temp ledger, temp results, a fetcher over the fake ESPN
# ---------------------------------------------------------------------------

class CardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = Server()
        self.cache = Path(self.tmp.name) / "raw"
        self.fetcher = self.new_fetcher()
        self.ledger = str(Path(self.tmp.name) / "cards_mma.jsonl")
        self.results = Path(self.tmp.name) / "ufc_results.jsonl"

    def new_fetcher(self, opener=None, **kw):
        return http.PoliteFetcher(cache_dir=self.cache, delay_s=0.0, opener=opener or self.server,
                                  sleep=lambda s: None, now_iso=lambda: FETCHED, **kw)

    def provider(self, **kw):
        return espn.EspnMmaResultsProvider(self.fetcher, **kw)

    def publish(self, date, picks, ledger=None):
        card = {"date": date, "sport": "mma", "rule": ufc_report.RULE_ID, "count": len(picks),
                "picks": [{
                    "game_id": gid, "rank": i + 1, "sport": "mma", "home_team": home,
                    "away_team": away, "side": side,
                    "team": home if side == "home" else away, "market": "moneyline",
                    "line": None, "price": price, "book": "consensus",
                    "market_probability": 0.6, "model_probability": None,
                    "label": "FAVOURITE", "bet": "test", "why": ["test"],
                    "kickoff_utc": start, "first_pitch_utc": start, "experimental": True,
                } for i, (gid, home, away, side, price, start) in enumerate(picks)]}
        card_ledger.publish(card, now=(AFTER_0926 - timedelta(days=5)).isoformat(),
                            path=ledger or self.ledger, sport="mma")

    def grade(self, date, *, now=AFTER_0926, provider=None, **kw):
        return ag.autograde_date(date, provider or self.provider(), now=now,
                                 ledger_path=self.ledger, results_path=self.results, **kw)

    def hand(self, date, rows=None):
        for fight, outcome, winner in (rows if rows is not None else HAND[date]):
            ufc_results.record_result(date=date, fight=fight, winner=winner, outcome=outcome,
                                      entered_by="hand", now=AFTER_0926, path=self.results)

    def settle(self, date, now=AFTER_0926):
        return ufc_report.settle_for_date(date, now=now, path=self.ledger,
                                          results_path=self.results)

    def synth_run(self, bouts, *, picks=SYNTH_PICK, aliases=None, **serve_kw):
        """Grade one synthetic card from scratch; returns (decisions, provider)."""
        self.publish(D0926, picks)
        serve_synth(self.server, "9000", bouts, **serve_kw)
        provider = self.provider(aliases=aliases) if aliases is not None else self.provider()
        return self.grade(D0926, provider=provider), provider


# ---------------------------------------------------------------------------
# the scoreboard parser
# ---------------------------------------------------------------------------

class ParseScoreboard(unittest.TestCase):
    def test_real_scoreboard_gives_every_bout_with_names_ids_and_winner_flags(self):
        board = espn.parse_scoreboard(fixture("scoreboard_2026-09-26.json"))
        self.assertEqual(len(board), 12)
        self.assertEqual({b.event_id for b in board}, {EV0926})
        rosas = next(b for b in board if b.bout_id == "401911630")
        self.assertEqual({f.fighter_id for f in rosas.fighters}, {"3075570", "5088844"})
        self.assertEqual({f.name for f in rosas.fighters}, {"Raoni Barcelos", "Raul Rosas Jr."})
        self.assertEqual([f.fighter_id for f in rosas.fighters if f.winner], ["5088844"])
        self.assertEqual(rosas.status_name, "STATUS_FINAL")

    def test_aliases_come_from_the_data_layer_and_fold_punctuation(self):
        board = espn.parse_scoreboard(fixture("scoreboard_2026-09-26.json"))
        rosas = next(f for b in board for f in b.fighters if f.fighter_id == "5088844")
        self.assertIn("raul rosas jr", rosas.aliases)
        self.assertIn("raul rosas jr", espn.people_index(board)["5088844"])

    def test_scoreboard_with_nobody_scheduled_gives_no_bouts(self):
        self.assertEqual(espn.parse_scoreboard(empty_scoreboard()), [])

    def test_junk_documents_give_no_bouts_and_never_raise(self):
        for doc in (None, [], {}, {"events": None}, {"events": [None, 3, {"id": "1"}]},
                    {"events": [{"id": "1", "competitions": [None, {"competitors": []}]}]}):
            with self.subTest(doc=doc):
                self.assertEqual(espn.parse_scoreboard(doc), [])

    def test_a_competitor_with_no_name_is_kept_but_can_never_match_by_name(self):
        board = espn.parse_scoreboard({"events": [{"id": "1", "competitions": [{
            "id": "2", "competitors": [{"id": "10", "order": 1, "athlete": {}},
                                       {"id": "11", "order": 2, "athlete": {"displayName": "--"}}]}]}]})
        (bout,) = board
        self.assertEqual([f.name for f in bout.fighters], ["", ""])
        self.assertEqual(espn.people_index(board), {"10": [], "11": []})
        self.assertIsNone(espn.resolve_name("Anyone", espn.people_index(board)).fighter_id)


# ---------------------------------------------------------------------------
# one crawled bout -> one ProviderFight (pure)
# ---------------------------------------------------------------------------

class FightFromBout(unittest.TestCase):
    def bout(self, **kw):
        base = {"bout_id": "b1", "event_id": "9", "status": "final", "status_raw": "STATUS_FINAL",
                "fighter_a_id": "101", "fighter_b_id": "102", "winner_id": "101",
                "result_method": "KO_TKO", "result_method_raw": "kotko",
                "result_detail": "Punches", "end_round": 2, "end_time_s": 61.0,
                "fetched_utc": FETCHED}
        base.update(kw)
        return base

    def scoreboard_bout(self, winner=None, ids=("101", "102")):
        return espn.ScoreBout(
            event_id="9", event_name="x", bout_id="b1", status_name="STATUS_FINAL",
            fighters=tuple(espn.ScoreFighter(
                fighter_id=fid, name=name, aliases=(name.lower(),), order=order,
                winner=(fid == winner) if winner else False)
                for order, (fid, name) in enumerate(zip(ids, ("Alpha One", "Bravo Two")), 1)))

    def fight(self, bout=None, board="default", **kw):
        board = self.scoreboard_bout() if board == "default" else board
        return espn.fight_from_bout({"event_id": "9"}, bout or self.bout(**kw), board)

    def test_a_final_win_carries_both_ids_both_names_and_the_winner(self):
        f = self.fight()
        self.assertEqual((f.status, f.outcome, f.winner, f.winner_id),
                         (ag.STATUS_FINAL, "win", "Alpha One", "101"))
        self.assertEqual((f.fighter1, f.fighter2, f.fighter1_id, f.fighter2_id),
                         ("Alpha One", "Bravo Two", "101", "102"))
        self.assertEqual((f.provider, f.event_id, f.fight_id, f.fetched_utc),
                         ("espn", "9", "b1", FETCHED))
        self.assertEqual(f.raw_status, "STATUS_FINAL result=kotko R2 1:01 (Punches)")

    def test_without_a_scoreboard_entry_the_bout_has_ids_but_no_names(self):
        f = self.fight(board=None)
        self.assertEqual((f.fighter1, f.fighter2, f.winner), ("", "", None))
        self.assertEqual((f.fighter1_id, f.winner_id, f.outcome), ("101", "101", "win"))

    def test_draw_and_no_contest_need_no_winner_and_a_matching_method(self):
        draw = self.fight(winner_id=None, result_method="DRAW", result_method_raw="draw",
                          result_detail=None, end_time_s=300.0, end_round=3)
        self.assertEqual((draw.outcome, draw.winner_id), ("draw", ""))
        nc = self.fight(winner_id=None, result_method="NC", result_method_raw="no-contest")
        self.assertEqual(nc.outcome, "no_contest")

    def test_no_winner_without_a_marker_or_a_winner_on_a_draw_has_no_outcome(self):
        self.assertIsNone(self.fight(winner_id=None, result_method=None,
                                     result_method_raw=None).outcome)
        self.assertIsNone(self.fight(winner_id=None, result_method="OTHER",
                                     result_method_raw="mystery").outcome)
        contradictory = self.fight(result_method="DRAW", result_method_raw="draw")
        self.assertIsNone(contradictory.outcome)
        self.assertIn("a winner is flagged on a bout ESPN calls DRAW", contradictory.raw_status)

    def test_status_mapping(self):
        for state, raw, expected in (
                ("scheduled", "STATUS_SCHEDULED", ag.STATUS_PENDING),
                ("in_progress", "STATUS_IN_PROGRESS", ag.STATUS_PENDING),
                ("postponed", "STATUS_POSTPONED", ag.STATUS_PENDING),
                ("unknown", None, ag.STATUS_PENDING),
                ("canceled", "STATUS_CANCELED", ag.STATUS_CANCELLED),
                ("final", "STATUS_FINAL", ag.STATUS_FINAL)):
            with self.subTest(state=state):
                f = self.fight(status=state, status_raw=raw, winner_id=None, result_method=None,
                               result_method_raw=None, result_detail=None, end_round=None,
                               end_time_s=None)
                self.assertEqual(f.status, expected)

    def test_a_bout_the_data_layer_says_vanished_from_the_card_is_pending_never_cancelled(self):
        f = self.fight(status="canceled", status_raw=schedule.DROPPED_STATUS_RAW,
                       winner_id=None, result_method=None, result_method_raw=None,
                       result_detail=None, end_round=None, end_time_s=None)
        self.assertEqual((f.status, f.outcome), (ag.STATUS_PENDING, None))
        self.assertIn("not an ESPN status", f.raw_status)

    def test_a_scoreboard_naming_other_fighters_holds_a_final_bout(self):
        f = self.fight(board=self.scoreboard_bout(ids=("101", "777")))
        self.assertEqual((f.status, f.outcome), (ag.STATUS_PENDING, None))
        self.assertIn("HELD", f.raw_status)

    def test_a_scoreboard_flagging_the_other_winner_holds_a_final_bout(self):
        f = self.fight(board=self.scoreboard_bout(winner="102"))
        self.assertEqual((f.status, f.outcome), (ag.STATUS_PENDING, None))
        self.assertIn("HELD", f.raw_status)

    def test_a_scoreboard_that_agrees_or_has_flagged_nobody_does_not_hold(self):
        for board in (self.scoreboard_bout(winner="101"), self.scoreboard_bout()):
            self.assertEqual(self.fight(board=board).outcome, "win")

    def test_the_clock_is_shown_as_minutes_and_seconds(self):
        self.assertEqual(espn.raw_status_of(self.bout(end_round=5, end_time_s=98.0,
                                                      result_detail=None)),
                         "STATUS_FINAL result=kotko R5 1:38")
        self.assertEqual(espn.raw_status_of(self.bout(status="scheduled", status_raw="STATUS_SCHEDULED",
                                                      result_method_raw=None, result_detail=None,
                                                      end_round=None, end_time_s=None)),
                         "STATUS_SCHEDULED")


# ---------------------------------------------------------------------------
# names: names.match on both fighters, accents, and the refusal to guess
# ---------------------------------------------------------------------------

class NameMatching(CardCase):
    def people(self, name):
        return espn.people_index(espn.parse_scoreboard(fixture(name)))

    def test_accents_fold_in_both_directions(self):
        board = espn.people_index(espn.parse_scoreboard(fixture("w5_scoreboard_2026-09-22.json")))
        # ESPN spells "Norbert Növényi Jr."; the odds feed does not use the accents.
        self.assertEqual(espn.resolve_name("Norbert Novenyi Jr", board).fighter_id, "4588646")
        self.assertEqual(espn.resolve_name("Norbert Növényi Jr.", board).fighter_id, "4588646")
        # ESPN spells "Roberto Soldić"; a feed that kept the accent still matches a plain one.
        card = self.people("scoreboard_2026-10-03.json")
        self.assertEqual(espn.resolve_name("Roberto Soldic", card).fighter_id, "4274796")
        self.assertEqual(espn.resolve_name("Roberto Soldić", card).fighter_id, "4274796")
        plain = {"1": ["imanol rodriguez"]}
        self.assertEqual(espn.resolve_name("Imanol Rodríguez", plain).fighter_id, "1")

    def test_punctuation_and_case_fold(self):
        board = self.people("scoreboard_2026-09-26.json")        # ESPN: "Raul Rosas Jr."
        for spelled in ("Raul Rosas Jr", "RAUL ROSAS JR.", "raul  rosas jr"):
            self.assertEqual(espn.resolve_name(spelled, board).fighter_id, "5088844", spelled)

    def test_a_pick_with_accented_names_is_graded_end_to_end(self):
        # REAL data: Contender Series bout 401891542, Norbert Növényi Jr. beat Theo Haig.
        self.publish(D0922, [("n1", "Norbert Novenyi Jr", "Theo Haig", "home", -120.0,
                              "2026-09-22T23:00:00Z")])
        serve_0922(self.server)
        (d,) = self.grade(D0922, now=AFTER_0926)
        self.assertEqual((d.action, d.outcome, d.winner),
                         (ag.ACTION_RECORD, "win", "Norbert Novenyi Jr"))
        self.assertEqual(d.provenance["provider_fight_id"], "401891542")
        self.assertIn("'Norbert Novenyi Jr' = ESPN 'Norbert Növényi Jr.'", d.provenance["basis"])

    def test_two_athletes_with_one_name_are_refused_not_guessed(self):
        people = {"1": ["michael johnson"], "2": ["michael johnson"], "3": ["other one"]}
        found = espn.resolve_name("Michael Johnson", people)
        self.assertTrue(found.ambiguous)
        self.assertIsNone(found.fighter_id)
        self.assertEqual({c[0] for c in found.candidates}, {"1", "2"})

    def test_an_ambiguous_name_grades_nothing_and_says_which_athletes(self):
        bouts = [sbout("b1", ("1", "Michael Johnson"), ("2", "Other One"), winner="a"),
                 sbout("b2", ("3", "Michael Johnson"), ("4", "Third Man"), winner="b")]
        (d,), _ = self.synth_run(bouts, picks=[
            ("s1", "Michael Johnson", "Other One", "home", -150.0, "2026-09-26T20:00:00Z")])
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertIn("ambiguous", d.reason)
        self.assertIn("names.match", d.reason)
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_a_surname_shared_by_two_athletes_is_refused(self):
        people = {"1": ["anderson silva"], "2": ["thiago silva"]}
        self.assertTrue(espn.resolve_name("Silva", people).ambiguous)

    def test_a_different_first_name_is_not_a_match(self):
        board = self.people("scoreboard_2026-10-03.json")
        found = espn.resolve_name("Michael Parkin", board)           # ESPN: "Mick Parkin"
        self.assertIsNone(found.fighter_id)
        self.assertFalse(found.ambiguous)
        self.assertEqual(found.via, "none")

    def test_espn_own_athlete_record_does_not_tie_michael_to_mick(self):
        # Why CONFIRMED_ALIASES exists: not even `fighters.alias_forms` bridges it.
        record = fighters.parse_athlete(fixture("w5_athlete_5060505.json"), None,
                                        fetched_utc="2026-10-03T19:33:10Z", source_url="x")
        self.assertEqual((record["name"], record["first_name"]), ("Mick Parkin", "Mick"))
        self.assertNotIn("michael parkin", record["aliases"])

    def test_the_confirmed_alias_is_keyed_to_an_athlete_id_and_carries_evidence(self):
        alias = espn.CONFIRMED_ALIASES["michael parkin"]
        self.assertEqual((alias.espn_athlete_id, alias.espn_name), ("5060505", "Mick Parkin"))
        self.assertIn("UFC 332", alias.evidence)
        self.assertIn("Walker", alias.evidence)

    def test_a_confirmed_alias_resolves_only_when_that_athlete_is_on_the_card(self):
        card = self.people("scoreboard_2026-10-03.json")
        self.assertEqual(
            espn.resolve_name("Michael Parkin", card, espn.CONFIRMED_ALIASES).fighter_id, "5060505")
        self.assertEqual(
            espn.resolve_name("Michael Parkin", card, espn.CONFIRMED_ALIASES).via, "confirmed alias")
        elsewhere = self.people("scoreboard_2026-09-26.json")        # athlete 5060505 not on it
        self.assertIsNone(
            espn.resolve_name("Michael Parkin", elsewhere, espn.CONFIRMED_ALIASES).fighter_id)

    def test_a_confirmed_alias_that_collides_with_another_athlete_is_ambiguous(self):
        people = {"5060505": ["mick parkin"], "999": ["michael parkin"]}
        found = espn.resolve_name("Michael Parkin", people, espn.CONFIRMED_ALIASES)
        self.assertTrue(found.ambiguous)
        self.assertIsNone(found.fighter_id)


# ---------------------------------------------------------------------------
# every result kind, through the real crawl and the real autograder
# ---------------------------------------------------------------------------

class ResultKinds(CardCase):
    def run_kind(self, **bout_kw):
        (d,), provider = self.synth_run([sbout("b1", ALPHA, BRAVO, **bout_kw)])
        return d, provider

    def test_win_by_the_picked_fighter(self):
        d, _ = self.run_kind(winner="a", result="decision---unanimous")
        self.assertEqual((d.action, d.outcome, d.winner), (ag.ACTION_RECORD, "win", "Alpha One"))
        self.assertEqual(self.settle(D0926)["wins"], 1)

    def test_loss_for_the_picked_fighter_records_the_other_as_winner(self):
        d, _ = self.run_kind(winner="b", result="kotko", period=2, clock=61.0)
        self.assertEqual((d.action, d.outcome, d.winner), (ag.ACTION_RECORD, "win", "Bravo Two"))
        row = self.settle(D0926)
        self.assertEqual((row["wins"], row["losses"], row["voids"]), (0, 1, 0))
        self.assertEqual(row["profit_units"], -1.0)

    def test_every_decisive_method_with_a_flagged_winner_is_a_win(self):
        for method in ("kotko", "submission", "decision---unanimous", "decision---split",
                       "decision---majority", "dq", "some-new-method-espn-invents"):
            with self.subTest(method=method):
                self.setUp()
                d, _ = self.run_kind(winner="a", result=method)
                self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "win"))

    def test_draw_is_void(self):
        d, _ = self.run_kind(winner=None, result="draw")
        self.assertEqual((d.action, d.outcome, d.winner), (ag.ACTION_RECORD, "draw", None))
        row = self.settle(D0926)
        self.assertEqual((row["voids"], row["profit_units"]), (1, 0.0))

    def test_no_contest_is_void(self):
        d, _ = self.run_kind(winner=None, result="no-contest")
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "no_contest"))
        self.assertEqual(self.settle(D0926)["voids"], 1)

    def test_a_bout_espn_calls_canceled_is_void(self):
        d, _ = self.run_kind(status="STATUS_CANCELED")
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "cancelled"))
        self.assertEqual(self.settle(D0926)["voids"], 1)

    def test_a_bout_not_final_is_never_graded(self):
        for status in ("STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_POSTPONED"):
            with self.subTest(status=status):
                self.setUp()
                d, _ = self.run_kind(status=status, winner="a")      # a flag on an unfinished bout
                self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
                self.assertIn("not final", d.reason)
                self.assertIn(status, d.reason)
                self.assertEqual(ufc_results.read_all(self.results), [])

    def test_final_with_no_winner_and_no_recognised_marker_is_left_for_a_person(self):
        for result in (None, "technical-draw-or-whatever"):
            with self.subTest(result=result):
                self.setUp()
                d, _ = self.run_kind(winner=None, result=result)
                self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
                self.assertIn("no winner and no recognised", d.reason)

    def test_a_winner_flagged_on_a_bout_espn_calls_a_draw_is_left_for_a_person(self):
        d, _ = self.run_kind(winner="a", result="draw")
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)

    def test_scoreboard_and_event_document_disagreeing_on_the_winner_holds_the_bout(self):
        d, _ = self.run_kind(winner="a", result="kotko", board_winner="b")
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertIn("HELD", d.reason)

    def test_scoreboard_and_event_document_listing_different_fighters_holds_the_bout(self):
        d, _ = self.run_kind(winner="a", result="kotko", board_ids=(ALPHA, ("777", "Replacement Guy")))
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)

    def test_a_scoreboard_that_has_not_flagged_the_winner_yet_does_not_hold_the_bout(self):
        # ESPN's core API is the source of the result; a lagging scoreboard says nothing.
        d, _ = self.run_kind(winner="a", result="kotko", board_winner=None)
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "win"))

    def test_a_dropped_bout_record_is_never_used_the_replacement_bout_decides(self):
        # Run 1 caches the card with Alpha vs Bravo still to come. ESPN then replaces
        # the opponent: the old bout leaves the card (the data layer reports it as
        # `dropped_from_event`, a marker that is ours, not ESPN's) and a new bout exists.
        self.publish(D0926, SYNTH_PICK)
        serve_synth(self.server, "9000", [sbout("b1", ALPHA, BRAVO, status="STATUS_SCHEDULED")])
        self.grade(D0926, dry_run=True)
        serve_synth(self.server, "9000", [
            sbout("b9", ALPHA, ("301", "Replacement Guy"), winner="a", result="submission")])
        provider = self.provider()
        (d,) = self.grade(D0926, provider=provider)
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "cancelled"))
        self.assertEqual(d.provenance["provider_fight_id"], "b9")        # not the dropped b1
        self.assertTrue(any("bout b1 was dropped from event 9000" in n for n in provider.notes),
                        provider.notes)

    def test_a_published_bout_that_vanished_with_no_replacement_waits_for_a_person(self):
        # Alpha and Bravo are both gone from the card and nobody replaced them.
        self.publish(D0926, SYNTH_PICK)
        other = [("201", "Echo Five"), ("202", "Foxtrot Six")]
        serve_synth(self.server, "9000", [sbout("b1", ALPHA, BRAVO, status="STATUS_SCHEDULED"),
                                          sbout("b2", *other, winner="a", result="kotko")])
        self.grade(D0926, dry_run=True)
        serve_synth(self.server, "9000", [sbout("b2", *other, winner="a", result="kotko")])
        self.server.serve(espn_urls.scoreboard("2026-09-25"), empty_scoreboard())
        (d,) = self.grade(D0926)
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_a_published_fighter_in_a_different_final_bout_voids_the_pick(self):
        bouts = [sbout("b9", ALPHA, ("301", "Replacement Guy"), winner="b", result="submission")]
        (d,), _ = self.synth_run(bouts)
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "cancelled"))
        self.assertIn("published pairing did not happen", d.reason)
        self.assertEqual(d.provenance["provider_fight_id"], "b9")
        self.assertEqual(self.settle(D0926)["voids"], 1)

    def test_the_replacement_waits_while_its_bout_is_not_final(self):
        bouts = [sbout("b9", ALPHA, ("301", "Replacement Guy"), status="STATUS_SCHEDULED")]
        (d,), _ = self.synth_run(bouts)
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)

    def test_both_published_fighters_in_other_bouts_voids_the_pick(self):
        bouts = [sbout("b1", ALPHA, ("301", "Replacement One"), winner="a", result="kotko"),
                 sbout("b2", BRAVO, ("302", "Replacement Two"), winner="b", result="kotko")]
        (d,), _ = self.synth_run(bouts)
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "cancelled"))

    def test_a_spelling_variant_of_the_missing_opponent_is_not_called_a_replacement(self):
        bouts = [sbout("b1", ALPHA, ("102", "Bravo Twoo"), winner="a", result="kotko")]
        (d,), _ = self.synth_run(bouts)
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertIn("looks like a spelling", d.reason)
        self.assertIn("by hand", d.reason)


# ---------------------------------------------------------------------------
# a pick with no matching bout, and which days are read
# ---------------------------------------------------------------------------

class NoMatchingBout(CardCase):
    def test_no_ufc_event_on_the_day_or_the_day_before_is_unresolved_and_says_so(self):
        self.publish(D0926, SYNTH_PICK)
        self.server.serve(espn_urls.scoreboard(D0926), empty_scoreboard())
        self.server.serve(espn_urls.scoreboard("2026-09-25"), empty_scoreboard())
        (d,) = self.grade(D0926)
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertIn("no bout for either published fighter", d.reason)
        self.assertIn("scoreboard 2026-09-26: 0 event(s)", d.reason)
        self.assertIn("scoreboard 2026-09-25: 0 event(s)", d.reason)
        self.assertEqual(self.server.count("/events/"), 0)         # nothing to crawl
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_neither_fighter_on_the_card_is_not_proof_of_a_cancellation(self):
        self.publish(D0926, [("s1", "Nobody Here", "Also Absent", "home", -150.0,
                              "2026-09-26T20:00:00Z")])
        serve_0926(self.server)
        self.server.serve(espn_urls.scoreboard("2026-09-25"), empty_scoreboard())
        (d,) = self.grade(D0926)
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertEqual(self.server.count("/events/"), 0)         # no event holds either fighter

    def test_a_pick_on_a_card_listed_under_the_day_before_is_found_there(self):
        # A main-card bout after midnight UTC: the ledger date is the 4th, ESPN lists the
        # event under the 3rd.
        self.publish("2026-10-04", [("s1", "Alpha One", "Bravo Two", "home", -150.0,
                                     "2026-10-04T02:30:00Z")])
        bouts = [sbout("b1", ALPHA, BRAVO, winner="a", result="kotko")]
        self.server.serve(espn_urls.scoreboard("2026-10-04"), empty_scoreboard())
        serve_synth(self.server, "9000", bouts, day="2026-10-03", date="2026-10-03T20:00Z")
        (d,) = self.grade("2026-10-04", now=AFTER_1003 + timedelta(hours=1))
        self.assertEqual((d.action, d.outcome), (ag.ACTION_RECORD, "win"))
        self.assertEqual([u.rsplit("=", 1)[-1] for u in self.server.requests
                          if "scoreboard" in u], ["20261004", "20261003"])

    def test_the_day_before_is_not_read_when_every_pick_is_on_the_days_scoreboard(self):
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)
        self.grade(D0926)
        self.assertEqual(self.server.count("scoreboard"), 1)
        self.assertEqual(self.server.count("20260925"), 0)

    def test_only_events_that_hold_a_published_fighter_are_crawled(self):
        self.publish(D0926, [("s1", "Alpha One", "Bravo Two", "home", -150.0,
                              "2026-09-26T20:00:00Z")])
        bouts = [sbout("b1", ALPHA, BRAVO, winner="a", result="kotko")]
        serve_synth(self.server, "9000", bouts)
        # a second event the same day, with 15 bouts nobody published
        big = [sbout(f"x{i}", (str(500 + 2 * i), f"Name{i} Left"), (str(501 + 2 * i), f"Name{i} Right"),
                     winner="a", result="kotko") for i in range(15)]
        board = synth_board("9000", bouts)
        board["events"].append(synth_board("9001", big)["events"][0])
        self.server.serve(espn_urls.scoreboard(D0926), board)
        (d,) = self.grade(D0926)
        self.assertEqual(d.action, ag.ACTION_RECORD)
        self.assertEqual(self.server.count("/events/9001"), 0)
        self.assertEqual(self.server.count("/events/9000"), 2)     # the event + its one bout

    def test_a_malformed_date_is_a_clear_provider_error(self):
        with self.assertRaises(ag.ProviderError):
            self.provider().fetch_for_bouts("26/09/2026", [], now=AFTER_0926)


# ---------------------------------------------------------------------------
# a result a person entered is never overwritten; disagreements are reported
# ---------------------------------------------------------------------------

class HandEnteredResults(CardCase):
    def setUp(self):
        super().setUp()
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)

    def test_a_hand_entered_result_is_never_overwritten_and_a_disagreement_is_reported(self):
        # The person typed Barcelos; ESPN says Rosas Jr. won.
        wrong = [("Raul Rosas Jr vs Raoni Barcelos", "win", "Raoni Barcelos")]
        self.hand(D0926, wrong)
        before = self.results.read_bytes()
        decisions = self.grade(D0926)
        by_fight = {d.bout.fight: d for d in decisions}
        clash = by_fight["Raoni Barcelos vs Raul Rosas Jr"]
        self.assertEqual(clash.action, ag.ACTION_DISAGREE)
        self.assertIn("espn DISAGREES", clash.reason)
        self.assertIn("Raoni Barcelos", clash.reason)             # what is on file
        self.assertIn("Raul Rosas Jr", clash.reason)              # what ESPN says
        self.assertEqual((clash.outcome, clash.winner), ("win", "Raul Rosas Jr"))
        self.assertEqual(clash.existing["winner"], "Raoni Barcelos")
        self.assertEqual(clash.provenance["provider_fight_id"], "401911630")
        # the hand row is untouched; no automatic row for this bout was added
        rows = ufc_results.read_all(self.results)
        self.assertEqual(self.results.read_bytes()[:len(before)], before)
        self.assertEqual([r for r in rows if "Rosas" in r["fight"]], [rows[0]])
        found = ufc_results.result_for_fight(D0926, "Raoni Barcelos", "Raul Rosas Jr",
                                             path=self.results)
        self.assertEqual((found["winner"], found["entered_by"]), ("Raoni Barcelos", "hand"))
        # every OTHER pick, which had no row, was still graded
        self.assertEqual(sum(1 for d in decisions if d.action == ag.ACTION_RECORD), 4)
        self.assertEqual(len(rows), 1 + 4)

    def test_a_disagreement_changes_nothing_in_a_dry_run_either(self):
        self.hand(D0926, [("Raul Rosas Jr vs Raoni Barcelos", "win", "Raoni Barcelos")])
        before = self.results.read_bytes()
        decisions = self.grade(D0926, dry_run=True)
        self.assertEqual(sum(1 for d in decisions if d.action == ag.ACTION_DISAGREE), 1)
        self.assertEqual(self.results.read_bytes(), before)

    def test_a_hand_result_espn_agrees_with_is_skipped_with_espns_reason(self):
        self.hand(D0926)
        decisions = self.grade(D0926)
        self.assertEqual({d.action for d in decisions}, {ag.ACTION_SKIP})
        self.assertTrue(all("espn agrees" in d.reason for d in decisions))
        self.assertEqual(len(ufc_results.read_all(self.results)), 5)

    def test_a_hand_entered_void_that_espn_contradicts_is_a_disagreement(self):
        # Raul Rosas Jr vs Raoni Barcelos really happened; a person typed "cancelled".
        self.hand(D0926, [("Raul Rosas Jr vs Raoni Barcelos", "cancelled", None)])
        (clash,) = [d for d in self.grade(D0926) if d.action == ag.ACTION_DISAGREE]
        self.assertEqual(clash.outcome, "win")

    def test_an_earlier_automatic_row_is_never_overwritten_by_a_later_espn_change(self):
        self.grade(D0926)
        n = len(ufc_results.read_all(self.results))
        # ESPN now (say) flags the other fighter on that bout: a correction after final.
        bout = fixture("event_600061266.json")
        flipped = copy.deepcopy(bout)
        for comp in flipped["competitions"]:
            if comp["id"] == "401911630":
                for c in comp["competitors"]:
                    c["winner"] = not c["winner"]
        self.server.serve(espn_urls.event(EV0926), flipped)
        board = fixture("scoreboard_2026-09-26.json")
        for comp in board["events"][0]["competitions"]:
            if comp["id"] == "401911630":
                for c in comp["competitors"]:
                    c["winner"] = not c["winner"]
        self.server.serve(espn_urls.scoreboard(D0926), board)
        decisions = self.grade(D0926)
        self.assertEqual([d.action for d in decisions if d.action != ag.ACTION_SKIP],
                         [ag.ACTION_DISAGREE])
        self.assertEqual(len(ufc_results.read_all(self.results)), n)


class Provenance(CardCase):
    def test_automatic_rows_carry_the_source_the_espn_bout_id_and_the_fetch_time(self):
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)
        self.grade(D0926)
        rows = {r["fight"]: r for r in ufc_results.read_all(self.results)}
        self.assertEqual(len(rows), 5)
        rosas = rows["Raoni Barcelos vs Raul Rosas Jr"]
        self.assertEqual(rosas["entered_by"], "auto:espn")
        self.assertEqual(rosas["provider"], "espn")
        self.assertEqual(rosas["provider_event_id"], EV0926)
        self.assertEqual(rosas["provider_fight_id"], "401911630")
        self.assertEqual(rosas["fetched_utc"], FETCHED)
        self.assertEqual(rosas["raw_status"], "STATUS_FINAL result=kotko R5 1:38")
        self.assertIn("'Raul Rosas Jr' = ESPN 'Raul Rosas Jr.' (athlete 5088844, names.match)",
                      rosas["basis"])
        self.assertEqual((rosas["outcome"], rosas["winner"]), ("win", "Raul Rosas Jr"))
        for row in rows.values():
            self.assertEqual((row["provider"], row["entered_by"]), ("espn", "auto:espn"))
            self.assertTrue(row["provider_fight_id"].isdigit())
            self.assertEqual(row["provider_event_id"], EV0926)

    def test_the_replaced_fighter_row_names_the_replacement_bout(self):
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)
        self.grade(D0926)
        row = next(r for r in ufc_results.read_all(self.results) if "Gall" in r["fight"])
        self.assertEqual((row["outcome"], row["winner"]), ("cancelled", None))
        self.assertEqual(row["provider_fight_id"], "401924683")     # Dumas vs Hernandez
        self.assertIn("fighter replaced", row["basis"])

    def test_the_fetch_time_is_the_time_espn_was_read_not_the_time_of_the_run(self):
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)
        self.grade(D0926, now=AFTER_0926 + timedelta(days=30))
        self.assertEqual({r["fetched_utc"] for r in ufc_results.read_all(self.results)}, {FETCHED})


# ---------------------------------------------------------------------------
# freshness, cost, and the offline replay
# ---------------------------------------------------------------------------

class FreshnessAndCost(CardCase):
    def test_a_card_costs_one_scoreboard_one_event_and_one_status_per_bout(self):
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)
        self.grade(D0926, dry_run=True)
        self.assertEqual(len(self.server.requests), 1 + 1 + 12)
        self.assertEqual(self.server.count("scoreboard"), 1)

    def test_the_contender_series_card_costs_seven_requests(self):
        self.publish(D0922, PICKS[D0922])
        serve_0922(self.server)
        self.grade(D0922, dry_run=True)
        self.assertEqual(len(self.server.requests), 1 + 1 + 5)

    def test_a_second_run_rereads_the_scoreboard_and_event_but_not_final_statuses(self):
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)
        self.grade(D0926, dry_run=True)
        before = len(self.server.requests)
        self.grade(D0926, dry_run=True)
        self.assertEqual(len(self.server.requests) - before, 2)

    def test_statuses_that_are_not_final_are_rerequested_every_run(self):
        self.publish(D0926, SYNTH_PICK)
        serve_synth(self.server, "9000", [sbout("b1", ALPHA, BRAVO, status="STATUS_SCHEDULED")])
        self.grade(D0926, dry_run=True)
        before = len(self.server.requests)
        self.grade(D0926, dry_run=True)
        self.assertEqual(len(self.server.requests) - before, 3)    # scoreboard, event, status

    def test_offline_replays_a_saved_grading_with_no_request(self):
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)
        live = self.grade(D0926, dry_run=True)

        def refuse(request, timeout=None):
            raise AssertionError("an offline run reached the network")
        offline_fetcher = self.new_fetcher(opener=refuse, max_requests=0)
        replay = ag.autograde_date(
            D0926, espn.EspnMmaResultsProvider(offline_fetcher, live=False), now=AFTER_0926,
            dry_run=True, ledger_path=self.ledger, results_path=self.results)
        self.assertEqual([(d.bout.fight, d.action, d.outcome, d.winner) for d in replay],
                         [(d.bout.fight, d.action, d.outcome, d.winner) for d in live])

    def test_offline_on_a_cold_cache_fails_clearly_and_records_nothing(self):
        self.publish(D0926, PICKS[D0926])
        cold = http.PoliteFetcher(cache_dir=Path(self.tmp.name) / "cold", opener=self.server,
                                  max_requests=0, sleep=lambda s: None)
        with self.assertRaises(ag.ProviderError) as ctx:
            ag.autograde_date(D0926, espn.EspnMmaResultsProvider(cold, live=False), now=AFTER_0926,
                              ledger_path=self.ledger, results_path=self.results)
        self.assertIn("offline", str(ctx.exception))
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_a_browser_check_stops_the_run_and_nothing_is_recorded(self):
        self.publish(D0926, PICKS[D0926])
        self.server.serve(espn_urls.scoreboard(D0926), b"<html>Checking your browser</html>")
        with self.assertRaises(ag.ProviderError) as ctx:
            self.grade(D0926)
        self.assertIn("browser check", str(ctx.exception))
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_the_request_cap_stops_the_run_and_nothing_is_recorded(self):
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)
        self.fetcher = self.new_fetcher(max_requests=5)
        with self.assertRaises(ag.ProviderError) as ctx:
            self.grade(D0926)
        self.assertIn("request cap", str(ctx.exception))
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_an_unreachable_espn_is_a_provider_error_and_nothing_is_recorded(self):
        self.publish(D0926, PICKS[D0926])

        def down(request, timeout=None):
            raise urllib.error.URLError("no route")
        self.fetcher = self.new_fetcher(opener=down)
        with self.assertRaises(ag.ProviderError) as ctx:
            self.grade(D0926)
        self.assertIn("scoreboard", str(ctx.exception))
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_a_pick_whose_bout_has_not_started_makes_no_request_at_all(self):
        self.publish(D0926, [("s1", "Alpha One", "Bravo Two", "home", -150.0,
                              "2026-09-26T20:00:00Z")])
        (d,) = self.grade(D0926, now=datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(d.action, ag.ACTION_UNRESOLVED)
        self.assertIn("not yet fought", d.reason)
        self.assertEqual(self.server.requests, [])


# ---------------------------------------------------------------------------
# the 2026-09-22 and 2026-09-26 reproduction (real ESPN responses)
# ---------------------------------------------------------------------------

# pick -> (hand winner / "void", what the 2026-10-01 audit recorded of the bout,
#          ESPN's method text we expect on the same bout)
AUDIT = {
    "Piero Guaylupo vs Callum Connor": ("Piero Guaylupo", "unanimous decision",
                                        "result=decision---unanimous R3 5:00"),
    "Emilio Quissua vs Damian Piwowarczyk": ("Damian Piwowarczyk", "TKO round 1",
                                             "result=kotko R1 4:55"),
    "Robert Bryczek vs Rodolfo Vieira": ("Rodolfo Vieira", "unanimous decision",
                                         "result=decision---unanimous R3 5:00"),
    "Christian Edwards vs Rodolfo Bellato": ("Christian Edwards", "TKO round 3",
                                             "result=kotko R3 1:47"),
    "Raoni Barcelos vs Raul Rosas Jr": ("Raul Rosas Jr", "KO round 5", "result=kotko R5 1:38"),
    "Sedriques Dumas vs Mickey Gall": ("void", "bout did not happen: Gall replaced by Hernandez",
                                       "result=submission R1 0:57"),
    "Ailin Perez vs Norma Dumont": ("Ailin Perez", "unanimous decision",
                                    "result=decision---unanimous R3 5:00"),
}


class ReplayOfTheSevenHandGradedPicks(CardCase):
    def setUp(self):
        super().setUp()
        for date in (D0922, D0926):
            self.publish(date, PICKS[date])
        serve_0922(self.server)
        serve_0926(self.server)

    def test_verify_reproduces_every_hand_entered_result_and_writes_nothing(self):
        for date in (D0922, D0926):
            self.hand(date)
            self.settle(date)                      # already settled, exactly as in production
        before = self.results.read_bytes()
        seen = {}
        for date in (D0922, D0926):
            self.assertEqual(self.grade(date), [])             # a normal run leaves settled picks alone
            for d in self.grade(date, verify=True):
                seen[d.bout.fight] = d
        self.assertEqual(set(seen), set(AUDIT))
        for fight, (hand, audit_text, espn_text) in AUDIT.items():
            d = seen[fight]
            self.assertEqual(d.action, ag.ACTION_SKIP, (fight, d.reason))
            self.assertIn("espn agrees", d.reason, fight)
            self.assertIn(espn_text, d.provenance["raw_status"], fight)
            if hand == "void":
                self.assertEqual(d.existing["outcome"], "cancelled")
                self.assertIn("fighter replaced", d.provenance["basis"])
                self.assertEqual(d.provenance["provider_fight_id"], "401924683")
            else:
                self.assertEqual(d.existing["winner"], hand)
                self.assertIn(f"{hand} won", d.reason)
        self.assertEqual(self.results.read_bytes(), before)    # verify wrote nothing
        self.assertEqual(len(ufc_results.read_all(self.results)), 7)

    def test_espn_alone_grades_the_seven_picks_exactly_as_the_hand_did(self):
        manual_ledger = str(Path(self.tmp.name) / "manual_cards.jsonl")
        manual_results = Path(self.tmp.name) / "manual_results.jsonl"
        for date in (D0922, D0926):
            self.publish(date, PICKS[date], ledger=manual_ledger)
            for fight, outcome, winner in HAND[date]:
                ufc_results.record_result(date=date, fight=fight, winner=winner, outcome=outcome,
                                          entered_by="hand", now=AFTER_0926, path=manual_results)
            decisions = self.grade(date)
            self.assertTrue(all(d.action == ag.ACTION_RECORD for d in decisions),
                            [(d.bout.fight, d.reason) for d in decisions])

        def settled(ledger, results):
            return {date: ufc_report.settle_for_date(date, now=AFTER_0926, path=ledger,
                                                     results_path=results)
                    for date in (D0922, D0926)}
        auto = settled(self.ledger, self.results)
        manual = settled(manual_ledger, manual_results)

        def view(row):
            return [(p["game_id"], p["result"], p["profit_units"], p.get("reason"))
                    for p in row["picks"]]
        for date in (D0922, D0926):
            self.assertEqual(view(auto[date]), view(manual[date]))
            for key in ("wins", "losses", "voids", "unresolved", "profit_units"):
                self.assertEqual(auto[date][key], manual[date][key], (date, key))
        self.assertEqual((sum(auto[d]["wins"] for d in auto), sum(auto[d]["losses"] for d in auto),
                          sum(auto[d]["voids"] for d in auto)), (5, 1, 1))
        self.assertAlmostEqual(sum(auto[d]["profit_units"] for d in auto), 2.5027, places=4)
        self.assertEqual(len(ufc_results.read_all(self.results)), 7)
        self.assertEqual({r["entered_by"] for r in ufc_results.read_all(self.results)}, {"auto:espn"})

    def test_every_bout_resolves_to_exactly_one_espn_bout(self):
        ids = {}
        for date in (D0922, D0926):
            for d in self.grade(date, dry_run=True):
                self.assertEqual(d.action, ag.ACTION_RECORD, (d.bout.fight, d.reason))
                ids[d.bout.fight] = d.provenance["provider_fight_id"]
        self.assertEqual(ids, {
            "Piero Guaylupo vs Callum Connor": "401921411",
            "Emilio Quissua vs Damian Piwowarczyk": "401921412",
            "Robert Bryczek vs Rodolfo Vieira": "401911631",
            "Christian Edwards vs Rodolfo Bellato": "401914467",
            "Raoni Barcelos vs Raul Rosas Jr": "401911630",
            "Sedriques Dumas vs Mickey Gall": "401924683",
            "Ailin Perez vs Norma Dumont": "401914471"})


# ---------------------------------------------------------------------------
# tonight: the 2026-10-03 card (UFC 332)
# ---------------------------------------------------------------------------

TONIGHT = {"Marvin Vettori vs Ismail Naurdiev": "401912275",
           "Johnny Walker vs Michael Parkin": "401912274",
           "Imanol Rodriguez vs Alden Coria": "401912276"}


def serve_1003(server, *, final=None, mutate=None):
    """UFC 332 as saved (all 14 bouts scheduled). `final` = {bout id: winner athlete id}
    flips those bouts to final in the scoreboard, the event document and the status
    document -- SYNTHETIC, built from the real shapes, to show what grading looks like
    once ESPN marks them final. `mutate(board, event)` may edit both documents last."""
    final = final or {}
    board = fixture("scoreboard_2026-10-03.json")
    event = fixture(f"event_{EV1003}.json")
    scheduled = fixture_bytes("w1_status_scheduled_401912278.json")
    for comp in board["events"][0]["competitions"]:
        if comp["id"] in final:
            comp["status"] = {"clock": 300.0, "period": 3, "type": _type("STATUS_FINAL")}
            for c in comp["competitors"]:
                c["winner"] = c["id"] == final[comp["id"]]
    for comp in event["competitions"]:
        if comp["id"] in final:
            for c in comp["competitors"]:
                c["winner"] = c["id"] == final[comp["id"]]
    if mutate is not None:
        mutate(board, event)
    server.serve(espn_urls.scoreboard(D1003), board)
    server.serve(espn_urls.event(EV1003), event)
    for comp in event["competitions"]:
        if comp["id"] in final:
            doc = {"clock": 300.0, "displayClock": "5:00", "period": 3, "type": _type("STATUS_FINAL"),
                   "result": {"id": 262, "name": "decision---unanimous"}}
            server.serve(espn_urls.competition_status(EV1003, comp["id"]), doc)
        else:
            server.serve(espn_urls.competition_status(EV1003, comp["id"]), scheduled)


# athlete ids: Vettori 4001851, Naurdiev 4412813, Walker 3146944, Parkin 5060505,
# Rodriguez 5289578, Coria 5099732
FINAL_1003 = {"401912275": "4412813", "401912274": "5060505", "401912276": "5289578"}


class TonightsCard(CardCase):
    def setUp(self):
        super().setUp()
        self.publish(D1003, PICKS[D1003])

    def test_the_three_picks_match_three_bouts_by_name_before_they_are_final(self):
        serve_1003(self.server)
        decisions = self.grade(D1003, now=AFTER_1003, dry_run=True)
        self.assertEqual({d.bout.fight for d in decisions}, set(TONIGHT))
        for d in decisions:
            # Not "neither published fighter" and not "ambiguous": each pick found its
            # one bout, and is waiting only because ESPN has not called it final.
            self.assertEqual(d.action, ag.ACTION_UNRESOLVED, d.bout.fight)
            self.assertIn("provider status is not final (STATUS_SCHEDULED)", d.reason, d.bout.fight)
        self.assertEqual(self.server.count("scoreboard"), 1)
        self.assertEqual(self.server.count("20261002"), 0)
        self.assertEqual(len(self.server.requests), 1 + 1 + 14)

    def test_once_espn_marks_the_bouts_final_one_command_grades_all_three(self):
        serve_1003(self.server, final=FINAL_1003)
        decisions = self.grade(D1003, now=AFTER_1003)
        got = {d.bout.fight: d for d in decisions}
        self.assertEqual(set(got), set(TONIGHT))
        for fight, bout_id in TONIGHT.items():
            self.assertEqual(got[fight].action, ag.ACTION_RECORD, (fight, got[fight].reason))
            self.assertEqual(got[fight].provenance["provider_fight_id"], bout_id)
            self.assertEqual(got[fight].provenance["provider_event_id"], EV1003)
        self.assertEqual(got["Marvin Vettori vs Ismail Naurdiev"].winner, "Ismail Naurdiev")
        self.assertEqual(got["Johnny Walker vs Michael Parkin"].winner, "Michael Parkin")
        self.assertEqual(got["Imanol Rodriguez vs Alden Coria"].winner, "Imanol Rodriguez")
        self.assertIn("confirmed alias",
                      got["Johnny Walker vs Michael Parkin"].provenance["basis"])
        self.assertEqual({r["entered_by"] for r in ufc_results.read_all(self.results)}, {"auto:espn"})
        row = self.settle(D1003, now=AFTER_1003)
        self.assertEqual((row["wins"], row["losses"], row["voids"], row["unresolved"]), (2, 1, 0, 0))
        by_game = {p["game_id"]: p["result"] for p in row["picks"]}
        self.assertEqual(by_game, {"e3ca": "WIN", "2239": "LOSS", "4a46": "WIN"})

    def test_grading_is_per_bout_and_resumable_as_the_card_goes_on(self):
        partial = {"401912275": "4412813"}                       # only the first prelim is over
        serve_1003(self.server, final=partial)
        first = {d.bout.fight: d for d in self.grade(D1003, now=AFTER_1003)}
        self.assertEqual(first["Marvin Vettori vs Ismail Naurdiev"].action, ag.ACTION_RECORD)
        self.assertEqual(first["Johnny Walker vs Michael Parkin"].action, ag.ACTION_UNRESOLVED)
        self.assertEqual(len(ufc_results.read_all(self.results)), 1)
        self.settle(D1003, now=AFTER_1003)                       # settles one, leaves two open
        serve_1003(self.server, final=FINAL_1003)
        second = {d.bout.fight: d for d in self.grade(D1003, now=AFTER_1003 + timedelta(hours=1))}
        self.assertEqual(sorted(d.action for d in second.values()),
                         sorted([ag.ACTION_RECORD, ag.ACTION_RECORD]))
        self.assertEqual(len(ufc_results.read_all(self.results)), 3)

    def test_without_the_confirmed_alias_the_parkin_pick_waits_for_a_person_and_says_how(self):
        serve_1003(self.server, final=FINAL_1003)
        provider = self.provider(aliases={})
        got = {d.bout.fight: d for d in self.grade(D1003, now=AFTER_1003, provider=provider)}
        self.assertEqual(got["Marvin Vettori vs Ismail Naurdiev"].action, ag.ACTION_RECORD)
        self.assertEqual(got["Imanol Rodriguez vs Alden Coria"].action, ag.ACTION_RECORD)
        parkin = got["Johnny Walker vs Michael Parkin"]
        self.assertEqual(parkin.action, ag.ACTION_UNRESOLVED)
        self.assertIn("Mick Parkin", parkin.reason)
        self.assertIn("looks like a spelling", parkin.reason)
        self.assertIn("CONFIRMED_ALIASES", parkin.reason)
        self.assertEqual(len(ufc_results.read_all(self.results)), 2)

    def test_the_alias_does_not_rescue_a_pairing_when_walker_fought_someone_else(self):
        # SYNTHETIC: ESPN's Walker fights "Some Other Man" (athlete 999), not Mick Parkin
        # (athlete 5060505), and wins. The alias is keyed to 5060505, who is no longer on
        # the card, so "Michael Parkin" cannot be resolved: the published pairing did not
        # happen and the pick is void -- never a win or loss against the wrong man.
        def swap_opponent(board, event):
            for comp in board["events"][0]["competitions"]:
                if comp["id"] == "401912274":
                    comp["competitors"][1]["id"] = "999"
                    comp["competitors"][1]["athlete"]["displayName"] = "Some Other Man"
                    comp["competitors"][1]["athlete"]["fullName"] = "Some Other Man"
            for comp in event["competitions"]:
                if comp["id"] == "401912274":
                    comp["competitors"][1]["id"] = "999"
        serve_1003(self.server, final={"401912274": "5060505"}, mutate=swap_opponent)
        got = {d.bout.fight: d for d in self.grade(D1003, now=AFTER_1003)}
        walker = got["Johnny Walker vs Michael Parkin"]
        self.assertEqual((walker.action, walker.outcome, walker.winner),
                         (ag.ACTION_RECORD, "cancelled", None))
        self.assertIn("fighter replaced", walker.provenance["basis"])
        self.assertNotIn("confirmed alias", walker.provenance["basis"])

    def test_a_card_that_is_all_scheduled_leaves_the_store_untouched(self):
        serve_1003(self.server)
        self.grade(D1003, now=AFTER_1003)
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_the_command_for_tonight_runs_through_the_cli(self):
        # `python -m src.cli ufc autograde --date 2026-10-03`, nothing else, with the
        # clock set to after the card and ESPN (synthetically) final on all three bouts.
        serve_1003(self.server, final=FINAL_1003)
        code, out, err = run_cli(
            ["ufc", "autograde", "--date", D1003, "--ledger-path", self.ledger,
             "--results-path", str(self.results)], fetcher=self.fetcher, now=AFTER_1003)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("RECORDED  "), 3)
        self.assertIn("card settle --sport mma --date 2026-10-03", out)
        self.assertEqual(len(ufc_results.read_all(self.results)), 3)


# ---------------------------------------------------------------------------
# the CLI
# ---------------------------------------------------------------------------

def run_cli(argv, *, fetcher, now=None, stdout=None):
    """`cli.main(argv)` with ESPN's fetcher replaced (no real request is possible), the
    clock optionally fixed, and `.env` never loaded (a real key must not be reachable
    from a test). Returns (exit code, stdout text, stderr text); the patched
    `make_fetcher` is `run_cli.made`."""
    out, err = stdout or io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(cli, "_load_dotenv"))
        run_cli.made = stack.enter_context(
            mock.patch.object(espn, "make_fetcher", return_value=fetcher))
        if now is not None:
            clock = stack.enter_context(mock.patch.object(ag, "datetime", wraps=datetime))
            clock.now.return_value = now
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        code = cli.main(argv)
    return code, (out.getvalue() if hasattr(out, "getvalue") else ""), err.getvalue()


class AutogradeCli(CardCase):
    def setUp(self):
        super().setUp()
        self.publish(D0926, PICKS[D0926])
        serve_0926(self.server)

    def run_cli(self, *extra, date=D0926, fetcher=None, stdout=None, now=None):
        code, out, err = run_cli(
            ["ufc", "autograde", "--date", date, "--ledger-path", self.ledger,
             "--results-path", str(self.results), *extra],
            fetcher=fetcher or self.fetcher, now=now, stdout=stdout)
        self.made = run_cli.made
        return code, out, err

    def test_espn_is_the_default_source(self):
        code, out, _ = self.run_cli("--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(self.made.called)
        self.assertEqual(out.count("WOULD RECORD"), 5)
        self.assertIn("dry run -- nothing written", out)
        self.assertIn("provider': 'espn'", out)
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_a_real_run_records_with_espn_provenance_then_a_second_run_skips(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(out.count("RECORDED  "), 5)
        self.assertIn("card settle --sport mma", out)
        rows = ufc_results.read_all(self.results)
        self.assertEqual({r["provider"] for r in rows}, {"espn"})
        _, out2, _ = self.run_cli()
        self.assertIn("5 skipped", out2)
        self.assertIn("0 disagree", out2)
        self.assertEqual(len(ufc_results.read_all(self.results)), 5)

    def test_verify_audits_settled_picks_writes_nothing_and_exits_zero_when_all_agree(self):
        self.hand(D0926)
        self.settle(D0926)
        before = self.results.read_bytes()
        code, out, _ = self.run_cli("--verify")
        self.assertEqual(code, 0)
        self.assertIn("verify 2026-09-26 against espn", out)
        self.assertEqual(out.count("SKIPPED"), 5)
        self.assertEqual(out.count("espn agrees"), 5)
        self.assertIn("5 skipped, 0 disagree", out)
        self.assertEqual(self.results.read_bytes(), before)

    def test_a_disagreement_is_loud_and_exits_non_zero_with_nothing_changed(self):
        self.hand(D0926, [("Raul Rosas Jr vs Raoni Barcelos", "win", "Raoni Barcelos")])
        before = self.results.read_bytes()
        code, out, err = self.run_cli("--verify")
        self.assertEqual(code, 2)
        self.assertIn("DISAGREES (nothing changed)", out)
        self.assertIn("1 disagree", out)
        self.assertIn("ATTENTION", err)
        self.assertEqual(self.results.read_bytes(), before)

    def test_fixture_alone_still_means_balldontlie(self):
        fixture_path = Path(__file__).parent / "fixtures" / "ufc_autograde" / "bdl_mma_docs_shape_2026-09-26.json"
        code, out, _ = self.run_cli("--fixture", str(fixture_path), "--dry-run")
        self.assertEqual(code, 0)
        self.assertFalse(self.made.called)
        self.assertIn("balldontlie", out)

    def test_fixture_with_the_espn_source_is_refused(self):
        code, _, err = self.run_cli("--source", "espn", "--fixture", "whatever.json")
        self.assertEqual(code, 2)
        self.assertIn("BALLDONTLIE", err)

    def test_offline_needs_the_espn_source(self):
        fixture_path = Path(__file__).parent / "fixtures" / "ufc_autograde" / "bdl_mma_docs_shape_2026-09-26.json"
        code, _, err = self.run_cli("--offline", "--fixture", str(fixture_path))
        self.assertEqual(code, 2)
        self.assertIn("--offline", err)

    def test_balldontlie_stays_selectable_and_blocks_cleanly_without_a_key(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            code, _, err = self.run_cli("--source", "balldontlie", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", err)
        self.assertFalse(self.made.called)

    def test_offline_and_cache_dir_reach_the_fetcher(self):
        self.run_cli("--offline", "--cache-dir", str(self.cache), "--dry-run")
        self.made.assert_called_once_with(str(self.cache), offline=True)

    def test_offline_on_a_cold_cache_is_blocked_with_a_clear_message(self):
        cold = http.PoliteFetcher(cache_dir=Path(self.tmp.name) / "cold", max_requests=0)
        code, _, err = self.run_cli("--offline", "--dry-run", fetcher=cold)
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", err)
        self.assertIn("offline", err)

    def test_espn_unreachable_is_blocked_and_records_nothing(self):
        def down(request, timeout=None):
            raise urllib.error.URLError("no route")
        code, _, err = self.run_cli(fetcher=self.new_fetcher(opener=down))
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", err)
        self.assertEqual(ufc_results.read_all(self.results), [])

    def test_a_console_that_cannot_print_an_accent_does_not_crash_the_run(self):
        # Windows' cp1252 console has no c-acute; ESPN's "Roberto Soldić" must not
        # crash a run that has already written its rows.
        picks = [("s1", "Roberto Soldic", "Khaos Williams", "home", -150.0, "2026-10-03T20:00:00Z")]
        self.ledger = str(Path(self.tmp.name) / "cards_accent.jsonl")
        self.publish(D1003, picks)
        serve_1003(self.server, final={"401917345": "4274796"})
        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
        code, _, _ = self.run_cli("--dry-run", date=D1003, stdout=console, now=AFTER_1003)
        self.assertEqual(code, 0)
        # ESPN's spelling reached the printed provenance with the unprintable letter
        # replaced, instead of raising UnicodeEncodeError.
        self.assertIn(b"ESPN 'Roberto Soldi?'", raw.getvalue())
        self.assertIn(b"WOULD RECORD  Roberto Soldic vs Khaos Williams", raw.getvalue())


if __name__ == "__main__":
    unittest.main()
