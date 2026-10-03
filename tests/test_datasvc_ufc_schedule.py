"""The UFC schedule module: events, bouts and results from ESPN's MMA JSON.

No network. A real `PoliteFetcher` is given a fake opener that serves the saved ESPN
responses (tests/fixtures/espn_mma) by canonical URL, built with `espn_urls`, so a
request count here is a count of requests that would have reached ESPN and the cache
behaves as it does in production. Statuses of the completed card and the other
`w1_*` files are real responses captured on 2026-10-03; the synthetic events used
for the window and dropped-bout tests are built to the same shape.
"""
import email.message
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.datasvc import http
from src.datasvc.ufc import espn_urls, schedule
from src.datasvc.ufc.store import DEFAULT_DIR, UfcStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_mma"

COMPLETED = "600061266"      # UFC Fight Night: Rosas Jr. vs. Barcelos, 12 bouts, all final
SCHEDULED = "600061182"      # UFC 332, 14 bouts, none fought yet
UFC_200 = "400818923"        # 2016, 12 bouts, one no contest
UFC_100 = "400252542"        # 2009, 11 bouts
CANCELED = "401219517"       # 2020, cancelled, one placeholder bout
FETCHED = "2026-10-03T18:00:00Z"
SOURCE = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/x"


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()


def fixture(name):
    return json.loads(fixture_bytes(name).decode("utf-8"))


def completed_status_file(bout_id):
    """The saved status of a bout of the completed card (three original, nine w1_)."""
    original = f"competition_{bout_id}_status.json"
    return original if (FIXTURES / original).exists() else f"w1_status_{bout_id}.json"


def parse(name, **kw):
    return schedule.parse_event(fixture(name), fetched_utc=FETCHED, source_url=SOURCE, **kw)


# ---------------------------------------------------------------------------------
# a fake ESPN and a fetcher in front of it
# ---------------------------------------------------------------------------------

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
    """Serves bodies by canonical URL and records every request that reaches it."""

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


class Stamp:
    """The fetcher's `now_iso`: what a fetched copy is stamped with. `aged` makes the
    copies fetched from now on look that old to the freshness rules; `fresh` resets."""

    def __init__(self):
        self.moment = datetime.now(timezone.utc)

    def __call__(self):
        return self.moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def aged(self, seconds):
        self.moment = datetime.now(timezone.utc) - timedelta(seconds=seconds)

    def fresh(self):
        self.moment = datetime.now(timezone.utc)


def serve_completed_card(server):
    event = fixture_bytes(f"event_{COMPLETED}.json")
    server.serve(espn_urls.event(COMPLETED), event)
    for comp in json.loads(event)["competitions"]:
        server.serve(espn_urls.competition_status(COMPLETED, comp["id"]),
                     fixture_bytes(completed_status_file(comp["id"])))


def serve_scheduled_card(server):
    event = fixture_bytes(f"event_{SCHEDULED}.json")
    scheduled = fixture_bytes("w1_status_scheduled_401912278.json")
    server.serve(espn_urls.event(SCHEDULED), event)
    for comp in json.loads(event)["competitions"]:
        server.serve(espn_urls.competition_status(SCHEDULED, comp["id"]), scheduled)


def serve_canceled_event(server):
    server.serve(espn_urls.event(CANCELED), fixture_bytes(f"w1_event_{CANCELED}.json"))
    server.serve(espn_urls.competition_status(CANCELED, "401219545"),
                 fixture_bytes("w1_status_canceled_401219545.json"))


_STATES = {"STATUS_SCHEDULED": ("pre", False), "STATUS_IN_PROGRESS": ("in", False),
           "STATUS_FINAL": ("post", True), "STATUS_CANCELED": ("post", False)}


def make_status(name="STATUS_SCHEDULED", *, period=0, clock=0.0, result=None):
    state, completed = _STATES[name]
    doc = {"clock": clock, "displayClock": "-", "period": period,
           "type": {"id": "1", "name": name, "state": state, "completed": completed,
                    "description": name, "detail": name, "shortDetail": name},
           "result": {}}
    if result:
        doc["result"] = {"id": 1, "name": result, "displayName": result, "shortDisplayName": result}
    return doc


def make_event(event_id, date_utc, bouts, *, status_name="STATUS_SCHEDULED", season=2026,
               winners=None, with_status=True):
    """An ESPN-shaped event. `bouts` is [(bout_id, match_number, fighter_a, fighter_b)]."""
    winners = winners or {}
    base = "http://sports.core.api.espn.com/v2/sports/mma/leagues/ufc"
    comps = []
    for bout_id, match, a, b in sorted(bouts, key=lambda t: -t[1]):    # ESPN: last fight first
        comps.append({
            "$ref": f"{base}/events/{event_id}/competitions/{bout_id}?lang=en&region=us",
            "id": bout_id, "description": "3 Rnd (5-5-5)", "date": date_utc,
            "type": {"id": "970", "text": "Bantamweight", "abbreviation": "Bantamweight"},
            "competitors": [{"id": b, "order": 2, "winner": winners.get(bout_id) == b},
                            {"id": a, "order": 1, "winner": winners.get(bout_id) == a}],
            "status": {"$ref": f"{base}/events/{event_id}/competitions/{bout_id}/status?lang=en&region=us"},
            "format": {"regulation": {"periods": 3, "displayName": "Round", "slug": "round", "clock": 300.0}},
            "matchNumber": match,
            "cardSegment": {"id": "173", "description": "Main Card", "name": "main"},
        })
    state, completed = _STATES[status_name]
    doc = {"$ref": f"{base}/events/{event_id}?lang=en&region=us", "id": event_id, "date": date_utc,
           "name": f"Synthetic {event_id}", "shortName": "UFC Fight Night",
           "season": {"$ref": f"{base}/seasons/{season}?lang=en&region=us"},
           "venues": [{"$ref": f"{base}/venues/77?lang=en&region=us"}], "competitions": comps}
    if with_status:
        doc["status"] = {"type": {"id": "1", "name": status_name, "state": state, "completed": completed,
                                  "description": "x", "detail": "x", "shortDetail": "x"}}
    return doc


def make_list(event_ids):
    return {"count": len(event_ids), "pageIndex": 1, "pageSize": 1000, "pageCount": 1,
            "items": [{"$ref": f"http://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{i}?lang=en&region=us"}
                      for i in event_ids]}


def serve_synthetic(server, event, statuses):
    """Serve an event and a status per bout id (`statuses` maps bout id -> status document)."""
    server.serve(espn_urls.event(event["id"]), event)
    for bout_id, doc in statuses.items():
        server.serve(espn_urls.competition_status(event["id"], bout_id), doc)


def snapshot(*roots):
    out = []
    for root in roots:
        root = Path(root)
        if root.exists():
            out.extend((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file())
    return out


class CrawlCase(unittest.TestCase):
    """A fetcher with an empty cache in a temp dir, in front of a fake ESPN."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = Server()
        self.stamp = Stamp()
        self.fetcher = http.PoliteFetcher(cache_dir=Path(self.tmp.name) / "raw", delay_s=0.0,
                                          opener=self.server, sleep=lambda s: None, now_iso=self.stamp)

    def requests_during(self, call):
        before = len(self.server.requests)
        result = call()
        return result, self.server.requests[before:]


# ---------------------------------------------------------------------------------
# the season list
# ---------------------------------------------------------------------------------

class SeasonListTests(CrawlCase):
    def test_the_2026_list_gives_52_distinct_string_ids(self):
        self.server.serve(espn_urls.season_events(2026), fixture_bytes("season_events_2026.json"))
        ids = schedule.list_season_events(self.fetcher, 2026)
        self.assertEqual(len(ids), 52)
        self.assertEqual(len(set(ids)), 52)
        self.assertTrue(all(isinstance(i, str) and i.isdigit() for i in ids))
        self.assertEqual(ids[0], "600057024")
        self.assertIn(COMPLETED, ids)
        self.assertIn(SCHEDULED, ids)

    def test_the_2016_list(self):
        self.server.serve(espn_urls.season_events(2016), fixture_bytes("season_events_2016.json"))
        ids = schedule.list_season_events(self.fetcher, 2016)
        self.assertEqual(len(ids), 41)
        self.assertEqual(ids[0], "400832048")
        self.assertIn(UFC_200, ids)

    def test_every_page_of_a_long_list_is_read_and_a_repeated_id_counts_once(self):
        page1 = make_list(["1", "2"])
        page1["pageCount"] = 2
        page2 = make_list(["2", "3"])
        page2["pageIndex"], page2["pageCount"] = 2, 2
        self.server.serve(espn_urls.season_events(2026), page1)
        self.server.serve(espn_urls.season_events(2026) + "&page=2", page2)
        self.assertEqual(schedule.list_season_events(self.fetcher, 2026), ["1", "2", "3"])
        self.assertEqual(len(self.server.requests), 2)

    def test_a_year_with_no_events_is_an_empty_list(self):
        # what ESPN answers for 2027 today: pageCount 0, not a 404
        self.server.serve(espn_urls.season_events(2027), {"count": 0, "pageIndex": 1, "pageSize": 1000,
                                                          "pageCount": 0, "items": []})
        self.assertEqual(schedule.list_season_events(self.fetcher, 2027), [])
        self.assertEqual(len(self.server.requests), 1)

    def test_a_cached_list_is_not_asked_for_again_unless_it_is_old(self):
        self.server.serve(espn_urls.season_events(2026), make_list(["1"]))
        self.stamp.aged(7200)
        schedule.list_season_events(self.fetcher, 2026)
        self.stamp.fresh()
        schedule.list_season_events(self.fetcher, 2026)                       # any cached copy will do
        self.assertEqual(len(self.server.requests), 1)
        schedule.list_season_events(self.fetcher, 2026, max_age_s=3600)       # two hours old: too old
        self.assertEqual(len(self.server.requests), 2)
        schedule.list_season_events(self.fetcher, 2026, max_age_s=3600)       # now fresh
        self.assertEqual(len(self.server.requests), 2)


# ---------------------------------------------------------------------------------
# parse_event
# ---------------------------------------------------------------------------------

class ParseCompletedEvent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.event, cls.bouts = parse(f"event_{COMPLETED}.json")
        cls.by_id = {b["bout_id"]: b for b in cls.bouts}

    def test_the_event_record(self):
        e = self.event
        self.assertEqual(e["event_id"], COMPLETED)
        self.assertEqual(e["name"], "UFC Fight Night: Rosas Jr. vs. Barcelos")
        self.assertEqual(e["short_name"], "UFC Fight Night")
        self.assertEqual(e["date_utc"], "2026-09-26T21:00Z")
        self.assertEqual(e["season"], 2026)
        self.assertEqual((e["status"], e["status_raw"]), ("final", "STATUS_FINAL"))
        self.assertEqual(e["venue_id"], "6176")
        self.assertEqual((e["source_url"], e["fetched_utc"]), (SOURCE, FETCHED))

    def test_twelve_bouts_ordered_by_match_number_main_event_first(self):
        self.assertEqual(len(self.bouts), 12)
        self.assertEqual([b["match_number"] for b in self.bouts], list(range(1, 13)))
        self.assertEqual(self.event["bout_ids"], [b["bout_id"] for b in self.bouts])
        self.assertEqual(self.event["bout_ids"][0], "401911630")       # the five-round main event
        self.assertEqual(self.event["bout_ids"][-1], "401914472")      # the first prelim
        self.assertEqual(len(set(self.event["bout_ids"])), 12)

    def test_card_segments_map_and_keep_the_raw_name(self):
        for bout in self.bouts:
            if bout["match_number"] <= 5:
                self.assertEqual((bout["card_segment"], bout["card_segment_raw"]), ("main", "main"))
            else:
                self.assertEqual((bout["card_segment"], bout["card_segment_raw"]), ("prelims", "prelims1"))

    def test_fighters_come_from_order_not_from_list_position(self):
        # ESPN lists the order 2 competitor first for this bout.
        raw = [c for c in fixture(f"event_{COMPLETED}.json")["competitions"] if c["id"] == "401914469"][0]
        self.assertEqual([c["order"] for c in raw["competitors"]], [2, 1])
        bout = self.by_id["401914469"]
        self.assertEqual((bout["fighter_a_id"], bout["fighter_b_id"]), ("4063869", "3154389"))
        self.assertEqual(bout["winner_id"], "3154389")           # b won
        main = self.by_id["401911630"]
        self.assertEqual((main["fighter_a_id"], main["fighter_b_id"], main["winner_id"]),
                         ("5088844", "3075570", "5088844"))      # a won

    def test_every_bout_has_two_fighters_and_one_winner_among_them(self):
        for bout in self.bouts:
            self.assertNotEqual(bout["fighter_a_id"], bout["fighter_b_id"])
            self.assertIn(bout["winner_id"], (bout["fighter_a_id"], bout["fighter_b_id"]))

    def test_weight_class_rounds_and_description(self):
        main = self.by_id["401911630"]
        self.assertEqual((main["weight_class"], main["scheduled_rounds"], main["description"]),
                         ("Bantamweight", 5, "5 Rnd (5-5-5-5-5)"))
        overtime = self.by_id["401914464"]
        self.assertEqual((overtime["weight_class"], overtime["scheduled_rounds"], overtime["description"]),
                         ("Women's Strawweight", 4, "3 Rnd + OT (5-5-5-5)"))
        light = self.by_id["401914467"]
        self.assertEqual((light["weight_class"], light["scheduled_rounds"]), ("Light Heavyweight", 3))

    def test_bout_dates_and_urls(self):
        main = self.by_id["401911630"]
        self.assertEqual(main["date_utc"], "2026-09-27T00:00Z")
        self.assertEqual(self.by_id["401914472"]["date_utc"], "2026-09-26T21:00Z")
        self.assertEqual(main["status_url"], espn_urls.competition_status(COMPLETED, "401911630"))
        self.assertEqual((main["source_url"], main["fetched_utc"], main["event_id"]), (SOURCE, FETCHED, COMPLETED))

    def test_no_result_is_known_yet(self):
        for bout in self.bouts:
            self.assertEqual(bout["status"], "unknown")
            for field in ("status_raw", "result_method", "result_method_raw", "result_detail",
                          "result_target", "end_round", "end_time_s", "fight_time_s"):
                self.assertIsNone(bout[field], field)

    def test_no_title_bout_on_this_card(self):
        self.assertFalse(any(b["title_bout"] for b in self.bouts))
        self.assertTrue(all(b["bout_types"] == [] for b in self.bouts))


class ParseScheduledEvent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.event, cls.bouts = parse(f"event_{SCHEDULED}.json")
        cls.by_id = {b["bout_id"]: b for b in cls.bouts}

    def test_the_event_is_scheduled_with_fourteen_bouts(self):
        e = self.event
        self.assertEqual((e["event_id"], e["name"], e["short_name"]), (SCHEDULED, "UFC 332: Silva vs. Wang", "UFC 332"))
        self.assertEqual((e["status"], e["status_raw"]), ("scheduled", "STATUS_SCHEDULED"))
        self.assertEqual((e["date_utc"], e["season"], e["venue_id"]), ("2026-10-03T20:00Z", 2026, "3093"))
        self.assertEqual(len(self.bouts), 14)
        self.assertEqual([b["match_number"] for b in self.bouts], list(range(1, 15)))

    def test_all_three_segments_are_mapped(self):
        counts = {}
        for bout in self.bouts:
            counts[bout["card_segment"]] = counts.get(bout["card_segment"], 0) + 1
        self.assertEqual(counts, {"main": 5, "prelims": 4, "early_prelims": 5})
        early = self.by_id["401907089"]
        self.assertEqual((early["card_segment"], early["card_segment_raw"], early["match_number"]),
                         ("early_prelims", "prelims2", 14))

    def test_nobody_has_won_yet(self):
        self.assertTrue(all(b["winner_id"] is None for b in self.bouts))

    def test_fighters_and_the_title_bout(self):
        main = self.by_id["401912278"]
        self.assertEqual((main["fighter_a_id"], main["fighter_b_id"]), ("4054605", "4215200"))
        self.assertEqual((main["weight_class"], main["scheduled_rounds"]), ("Women's Flyweight", 5))
        self.assertTrue(main["title_bout"])
        self.assertEqual(main["bout_types"], ["UFC Women's Flyweight Title"])
        self.assertEqual(sum(1 for b in self.bouts if b["title_bout"]), 1)
        # order 2 listed first for 401927906: a is the order 1 competitor
        self.assertEqual((self.by_id["401927906"]["fighter_a_id"], self.by_id["401927906"]["fighter_b_id"]),
                         ("4895760", "4684470"))


class ParseOtherCards(unittest.TestCase):
    def test_a_2016_card_a_no_contest_has_no_winner_and_title_bouts_are_flagged(self):
        event, bouts = parse(f"w1_event_{UFC_200}.json")
        by_id = {b["bout_id"]: b for b in bouts}
        self.assertEqual((event["season"], event["status"], event["venue_id"]), (2016, "final", "5060"))
        self.assertEqual(len(bouts), 12)
        self.assertIsNone(by_id["225282"]["winner_id"])                  # Lesnar v Hunt, no contest
        self.assertEqual(sum(1 for b in bouts if b["winner_id"] is None), 1)
        self.assertEqual({b["bout_id"] for b in bouts if b["title_bout"]}, {"223055", "223295"})
        self.assertEqual(by_id["223055"]["bout_types"], ["UFC Interim Featherweight Title"])
        counts = {}
        for bout in bouts:
            counts[bout["card_segment"]] = counts.get(bout["card_segment"], 0) + 1
        self.assertEqual(counts, {"main": 5, "prelims": 4, "early_prelims": 3})

    def test_a_2009_card_parses_the_same_way(self):
        event, bouts = parse(f"w1_event_{UFC_100}.json")
        self.assertEqual((event["season"], event["name"], len(bouts)), (2009, "UFC 100: Lesnar vs. Mir 2", 11))
        self.assertEqual(event["bout_ids"][0], "151918")                 # match number 1
        self.assertEqual({b["bout_id"] for b in bouts if b["title_bout"]}, {"152102", "152100"})
        self.assertTrue(all(b["winner_id"] for b in bouts))

    def test_a_cancelled_card_with_placeholder_fighters(self):
        event, bouts = parse(f"w1_event_{CANCELED}.json")
        self.assertEqual((event["status"], event["status_raw"], event["season"]), ("canceled", "STATUS_CANCELED", 2020))
        self.assertEqual(event["bout_ids"], ["401219545"])
        bout = bouts[0]
        self.assertIsNone(bout["description"])                           # ESPN sent ""
        self.assertIsNone(bout["weight_class"])                          # the competition has no type
        self.assertEqual((bout["scheduled_rounds"], bout["match_number"], bout["card_segment"]), (5, 1, "main"))
        self.assertEqual((bout["fighter_a_id"], bout["fighter_b_id"]), ("2431356", "4402367"))
        self.assertIsNone(bout["winner_id"])


class ParseEventEdgeCases(unittest.TestCase):
    def test_a_bare_competition_gives_nulls_not_errors(self):
        doc = {"id": "7", "competitions": [{"id": "70"}]}
        event, bouts = schedule.parse_event(doc, fetched_utc=FETCHED, source_url=SOURCE)
        self.assertEqual((event["status"], event["status_raw"], event["season"], event["venue_id"]),
                         ("unknown", None, None, None))
        self.assertEqual(event["bout_ids"], ["70"])
        bout = bouts[0]
        for field in ("date_utc", "match_number", "card_segment", "card_segment_raw", "weight_class",
                      "scheduled_rounds", "description", "fighter_a_id", "fighter_b_id", "winner_id"):
            self.assertIsNone(bout[field], field)
        self.assertEqual(bout["status_url"], espn_urls.competition_status("7", "70"))
        self.assertEqual(bout["bout_types"], [])

    def test_bouts_without_a_match_number_come_last_in_the_order_given(self):
        doc = {"id": "7", "competitions": [{"id": "1"}, {"id": "2", "matchNumber": 2},
                                           {"id": "3", "matchNumber": 1}, {"id": "4"}]}
        event, _ = schedule.parse_event(doc, fetched_utc=FETCHED, source_url=SOURCE)
        self.assertEqual(event["bout_ids"], ["3", "2", "1", "4"])

    def test_an_unknown_card_segment_is_kept_lower_case(self):
        doc = {"id": "7", "competitions": [{"id": "1", "cardSegment": {"name": "Prelims3"}}]}
        _, bouts = schedule.parse_event(doc, fetched_utc=FETCHED, source_url=SOURCE)
        self.assertEqual((bouts[0]["card_segment"], bouts[0]["card_segment_raw"]), ("prelims3", "Prelims3"))

    def test_the_venue_falls_back_to_the_first_competition_that_names_one(self):
        doc = {"id": "7", "competitions": [{"id": "1"}, {"id": "2", "venue": {"id": "55"}}]}
        event, _ = schedule.parse_event(doc, fetched_utc=FETCHED, source_url=SOURCE)
        self.assertEqual(event["venue_id"], "55")

    def test_a_competition_with_no_id_is_skipped_and_the_season_may_be_a_year_object(self):
        doc = {"id": "7", "season": {"year": 2020, "type": 2}, "competitions": [{"matchNumber": 1}, {"id": "2"}]}
        event, bouts = schedule.parse_event(doc, fetched_utc=FETCHED, source_url=SOURCE)
        self.assertEqual((event["season"], event["bout_ids"], len(bouts)), (2020, ["2"], 1))

    def test_two_winners_flagged_name_nobody_and_a_missing_order_uses_list_position(self):
        doc = {"id": "7", "competitions": [{"id": "1", "competitors": [
            {"id": "10", "winner": True}, {"id": "11", "winner": True}]}]}
        _, bouts = schedule.parse_event(doc, fetched_utc=FETCHED, source_url=SOURCE)
        self.assertEqual((bouts[0]["fighter_a_id"], bouts[0]["fighter_b_id"], bouts[0]["winner_id"]),
                         ("10", "11", None))

    def test_a_competition_listed_twice_is_one_bout(self):
        doc = {"id": "7", "competitions": [{"id": "1", "matchNumber": 2}, {"id": "2", "matchNumber": 1},
                                           {"id": "1", "matchNumber": 2}]}
        event, bouts = schedule.parse_event(doc, fetched_utc=FETCHED, source_url=SOURCE)
        self.assertEqual((event["bout_ids"], len(bouts)), (["2", "1"], 2))

    def test_a_document_with_no_id_is_refused(self):
        with self.assertRaises(ValueError):
            schedule.parse_event({"competitions": []}, fetched_utc=FETCHED, source_url=SOURCE)
        with self.assertRaises(ValueError):
            schedule.parse_event([], fetched_utc=FETCHED, source_url=SOURCE)


# ---------------------------------------------------------------------------------
# parse_status
# ---------------------------------------------------------------------------------

class ParseStatusTests(unittest.TestCase):
    def check(self, name, **expected):
        got = schedule.parse_status(fixture(name))
        for key, value in expected.items():
            self.assertEqual(got[key], value, f"{name}: {key}")
        return got

    def test_submission_in_round_one_at_0_57_is_57_seconds(self):
        self.check("competition_401924683_status.json", status="final", status_raw="STATUS_FINAL",
                   result_method="SUB", result_method_raw="submission", result_detail="Guillotine Choke",
                   result_target="head", end_round=1, end_time_s=57.0, fight_time_s=57.0)

    def test_ko_in_round_two_at_2_39_is_459_seconds(self):
        self.check("competition_401914466_status.json", result_method="KO_TKO", result_method_raw="kotko",
                   result_detail="Punch", end_round=2, end_time_s=159.0, fight_time_s=459.0)

    def test_ko_in_round_five_at_1_38_is_1298_seconds_and_a_missing_detail_is_null(self):
        self.check("competition_401911630_status.json", result_method="KO_TKO", end_round=5,
                   end_time_s=98.0, fight_time_s=1298.0, result_detail=None, result_target=None)

    def test_unanimous_split_and_majority_decisions(self):
        self.check("w1_status_401914471.json", result_method="DEC_UNANIMOUS",
                   result_method_raw="decision---unanimous", end_round=3, end_time_s=300.0, fight_time_s=900.0)
        self.check("w1_status_401914469.json", result_method="DEC_SPLIT",
                   result_method_raw="decision---split", end_round=3, fight_time_s=900.0)
        self.check("w1_status_225281.json", result_method="DEC_MAJORITY",
                   result_method_raw="decision---majority", end_round=5, end_time_s=300.0, fight_time_s=1500.0)

    def test_the_older_cards_use_the_same_names(self):
        self.check("w1_status_151971.json", result_method="DEC_UNANIMOUS")      # 2009
        self.check("w1_status_151928.json", result_method="DEC_SPLIT")          # 2009
        self.check("w1_status_224457.json", result_method="DEC_UNANIMOUS")      # 2016

    def test_draw_no_contest_and_disqualification(self):
        self.check("w1_status_401265459.json", result_method="DRAW", result_method_raw="draw",
                   end_round=5, fight_time_s=1500.0)
        self.check("w1_status_225282.json", result_method="NC", result_method_raw="no-contest", fight_time_s=900.0)
        self.check("w1_status_401914465.json", result_method="DQ", result_method_raw="dq",
                   end_round=1, end_time_s=139.0, fight_time_s=139.0)

    def test_a_2016_stoppage_in_round_three(self):
        self.check("w1_status_226660.json", result_method="KO_TKO", result_detail="Punches",
                   end_round=3, end_time_s=138.0, fight_time_s=738.0)

    def test_a_scheduled_bout_has_a_status_and_nothing_else(self):
        got = self.check("w1_status_scheduled_401912278.json", status="scheduled", status_raw="STATUS_SCHEDULED")
        for field in ("result_method", "result_method_raw", "result_detail", "result_target",
                      "end_round", "end_time_s", "fight_time_s"):
            self.assertIsNone(got[field], field)       # period 0 and clock 0.0 are not an end

    def test_a_cancelled_bout(self):
        got = self.check("w1_status_canceled_401219545.json", status="canceled", status_raw="STATUS_CANCELED")
        self.assertIsNone(got["fight_time_s"])

    def test_a_bout_in_progress_has_no_end_yet(self):
        doc = make_status("STATUS_IN_PROGRESS", period=2, clock=157.0)
        got = schedule.parse_status(doc)
        self.assertEqual(got["status"], "in_progress")
        self.assertEqual((got["end_round"], got["end_time_s"], got["fight_time_s"]), (None, None, None))

    def test_every_result_name_seen_maps_and_an_unseen_one_is_other_with_the_raw_name_kept(self):
        seen = {"kotko": "KO_TKO", "submission": "SUB", "decision---unanimous": "DEC_UNANIMOUS",
                "decision---split": "DEC_SPLIT", "decision---majority": "DEC_MAJORITY", "dq": "DQ",
                "no-contest": "NC", "draw": "DRAW"}
        for raw, method in seen.items():
            got = schedule.parse_status(make_status("STATUS_FINAL", period=1, clock=10.0, result=raw))
            self.assertEqual((got["result_method"], got["result_method_raw"]), (method, raw), raw)
        self.assertEqual(set(seen), set(schedule.RESULT_METHODS))
        self.assertTrue(set(seen.values()) <= set(schedule.METHODS))
        odd = schedule.parse_status(make_status("STATUS_FINAL", period=2, clock=10.0, result="tko---surprise"))
        self.assertEqual((odd["result_method"], odd["result_method_raw"]), ("OTHER", "tko---surprise"))
        self.assertEqual(odd["fight_time_s"], 310.0)

    def test_the_result_name_is_matched_ignoring_case_but_kept_as_sent(self):
        got = schedule.parse_status(make_status("STATUS_FINAL", period=1, clock=5.0, result="KOTKO"))
        self.assertEqual((got["result_method"], got["result_method_raw"]), ("KO_TKO", "KOTKO"))

    def test_a_final_bout_without_a_result_has_a_null_method_not_other(self):
        got = schedule.parse_status(make_status("STATUS_FINAL", period=1, clock=5.0))
        self.assertEqual((got["result_method"], got["result_method_raw"]), (None, None))
        self.assertEqual(got["fight_time_s"], 5.0)

    def test_final_with_no_period_or_clock_leaves_the_timing_null(self):
        doc = make_status("STATUS_FINAL", period=0, clock=0.0, result="submission")
        got = schedule.parse_status(doc)
        self.assertEqual((got["end_round"], got["end_time_s"], got["fight_time_s"]), (None, None, None))
        doc = make_status("STATUS_FINAL", period=2, clock=0.0, result="submission")
        del doc["clock"]
        got = schedule.parse_status(doc)
        self.assertEqual((got["end_round"], got["end_time_s"], got["fight_time_s"]), (2, None, None))

    def test_status_names_and_the_state_fallback(self):
        cases = [({"name": "STATUS_POSTPONED", "state": "post", "completed": False}, "postponed"),
                 ({"name": "STATUS_CANCELLED"}, "canceled"),
                 ({"name": "STATUS_END_PERIOD", "state": "in", "completed": False}, "in_progress"),
                 ({"name": "STATUS_DELAYED", "state": "pre"}, "scheduled"),
                 ({"name": "STATUS_FORFEIT", "state": "post", "completed": True}, "final"),
                 ({"name": "STATUS_ABANDONED", "state": "post", "completed": False}, "unknown"),
                 ({"name": "STATUS_SOMETHING_NEW"}, "unknown")]
        for block, expected in cases:
            self.assertEqual(schedule.parse_status({"type": block})["status"], expected, block)
        self.assertEqual(schedule.parse_status({})["status"], "unknown")
        self.assertEqual(schedule.parse_status(None)["status"], "unknown")


class DeriveEventStatusTests(unittest.TestCase):
    def test_rules(self):
        d = schedule.derive_event_status
        self.assertEqual(d(["final", "final"]), "final")
        self.assertEqual(d(["scheduled", "scheduled"]), "scheduled")
        self.assertEqual(d(["final", "in_progress", "scheduled"]), "in_progress")
        self.assertEqual(d(["final", "scheduled"]), "in_progress")             # under way between bouts
        self.assertEqual(d(["final", "final", "canceled"]), "final")           # cancelled bouts are ignored
        self.assertEqual(d(["canceled", "canceled"]), "canceled")
        self.assertEqual(d(["postponed", "postponed"]), "postponed")
        self.assertEqual(d(["scheduled", "canceled"]), "scheduled")
        self.assertEqual(d([]), "unknown")
        self.assertEqual(d(["unknown", "final"]), "unknown")


# ---------------------------------------------------------------------------------
# crawl_event
# ---------------------------------------------------------------------------------

class CrawlEventTests(CrawlCase):
    def setUp(self):
        super().setUp()
        serve_completed_card(self.server)

    def test_cold_cache_costs_one_request_for_the_event_and_one_per_bout(self):
        report = {}
        (event, bouts), requests = self.requests_during(
            lambda: schedule.crawl_event(self.fetcher, COMPLETED, report=report))
        self.assertEqual(len(bouts), 12)
        self.assertEqual(len(requests), 1 + len(bouts))
        self.assertEqual(self.fetcher.stats["requests"], 13)
        self.assertEqual(len(set(requests)), 13)
        self.assertEqual(report, {})                       # nothing missing, nothing unmapped

    def test_warm_cache_of_a_final_event_costs_exactly_one_request(self):
        first = schedule.crawl_event(self.fetcher, COMPLETED)
        (second, requests) = self.requests_during(lambda: schedule.crawl_event(self.fetcher, COMPLETED))
        self.assertEqual(requests, [espn_urls.event(COMPLETED)])
        self.assertEqual(second, first)
        self.assertEqual(self.server.count(), 14)

    def test_refresh_final_asks_for_every_status_again(self):
        schedule.crawl_event(self.fetcher, COMPLETED)
        _, requests = self.requests_during(lambda: schedule.crawl_event(self.fetcher, COMPLETED, refresh_final=True))
        self.assertEqual(len(requests), 13)

    def test_a_young_enough_cached_event_is_not_asked_for_again(self):
        schedule.crawl_event(self.fetcher, COMPLETED)
        _, requests = self.requests_during(lambda: schedule.crawl_event(self.fetcher, COMPLETED, max_age_s=3600))
        self.assertEqual(requests, [])

    def test_the_event_and_bouts_are_complete_and_ordered(self):
        event, bouts = schedule.crawl_event(self.fetcher, COMPLETED)
        self.assertEqual((event["status"], event["date_utc"], event["bout_ids"]),
                         ("final", "2026-09-26T21:00Z", [b["bout_id"] for b in bouts]))
        self.assertEqual([b["match_number"] for b in bouts], list(range(1, 13)))
        self.assertTrue(all(b["status"] == "final" and b["status_raw"] == "STATUS_FINAL" for b in bouts))
        self.assertTrue(all(b["result_method"] and b["end_round"] and b["fight_time_s"] for b in bouts))
        self.assertEqual({event["fetched_utc"]} | {b["fetched_utc"] for b in bouts}, {self.stamp()})

    def test_methods_and_fight_times_of_the_whole_card(self):
        _, bouts = schedule.crawl_event(self.fetcher, COMPLETED)
        by_id = {b["bout_id"]: b for b in bouts}
        counts = {}
        for bout in bouts:
            counts[bout["result_method"]] = counts.get(bout["result_method"], 0) + 1
        self.assertEqual(counts, {"KO_TKO": 6, "SUB": 2, "DQ": 1, "DEC_UNANIMOUS": 2, "DEC_SPLIT": 1})
        times = {"401914472": 62.0, "401914470": 254.0, "401914467": 707.0, "401914468": 547.0,
                 "401914464": 499.0, "401914465": 139.0, "401914466": 459.0, "401911630": 1298.0,
                 "401924683": 57.0, "401914469": 900.0, "401911631": 900.0, "401914471": 900.0}
        self.assertEqual({k: b["fight_time_s"] for k, b in by_id.items()}, times)
        for bout in bouts:       # a fight never lasts longer than the rounds it was scheduled for
            self.assertLessEqual(bout["fight_time_s"], bout["scheduled_rounds"] * 300.0)
            self.assertEqual(bout["status_url"], espn_urls.competition_status(COMPLETED, bout["bout_id"]))
        self.assertEqual(by_id["401914465"]["result_method"], "DQ")
        self.assertEqual(by_id["401914465"]["winner_id"], "5345639")

    def test_a_bout_whose_status_is_missing_stays_unknown_and_is_listed(self):
        self.server.serve(espn_urls.competition_status(COMPLETED, "401914470"), b"", status=404)
        report = {}
        event, bouts = schedule.crawl_event(self.fetcher, COMPLETED, report=report)
        missing = [b for b in bouts if b["bout_id"] == "401914470"][0]
        self.assertEqual((missing["status"], missing["result_method"], missing["fight_time_s"]), ("unknown", None, None))
        self.assertEqual(report["status_not_found"], ["401914470"])
        self.assertEqual(event["status"], "final")         # the event's own status still says final

    def test_an_unseen_result_name_is_other_and_listed(self):
        doc = fixture("w1_status_401914470.json")
        doc["result"]["name"] = "tko---surprise"
        self.server.serve(espn_urls.competition_status(COMPLETED, "401914470"), doc)
        report = {}
        _, bouts = schedule.crawl_event(self.fetcher, COMPLETED, report=report)
        bout = [b for b in bouts if b["bout_id"] == "401914470"][0]
        self.assertEqual((bout["result_method"], bout["result_method_raw"]), ("OTHER", "tko---surprise"))
        self.assertEqual(report["unmapped_results"], [["401914470", "tko---surprise"]])

    def test_a_final_bout_with_a_decisive_method_and_no_winner_is_listed(self):
        event = fixture(f"event_{COMPLETED}.json")
        for comp in event["competitions"]:
            if comp["id"] == "401914470":
                for competitor in comp["competitors"]:
                    competitor["winner"] = False
        self.server.serve(espn_urls.event(COMPLETED), event)
        report = {}
        schedule.crawl_event(self.fetcher, COMPLETED, report=report)
        self.assertEqual(report["final_without_winner"], ["401914470"])

    def test_a_missing_event_raises_not_found(self):
        self.server.serve(espn_urls.event("1"), b"", status=404)
        with self.assertRaises(http.NotFound):
            schedule.crawl_event(self.fetcher, "1")

    def test_an_event_with_no_status_of_its_own_takes_it_from_its_bouts(self):
        bouts = [("1", 1, "10", "11"), ("2", 2, "12", "13")]
        doc = make_event("8000", "2026-10-01T20:00Z", bouts, with_status=False, winners={"1": "10", "2": "13"})
        serve_synthetic(self.server, doc, {"1": make_status("STATUS_FINAL", period=1, clock=30.0, result="kotko"),
                                           "2": make_status("STATUS_FINAL", period=3, clock=300.0,
                                                            result="decision---unanimous")})
        event, _ = schedule.crawl_event(self.fetcher, "8000")
        self.assertEqual((event["status"], event["status_raw"]), ("final", None))

        doc = make_event("8001", "2026-10-01T20:00Z", bouts, with_status=False)
        serve_synthetic(self.server, doc, {"1": make_status("STATUS_FINAL", period=1, clock=30.0, result="kotko"),
                                           "2": make_status("STATUS_SCHEDULED")})
        event, _ = schedule.crawl_event(self.fetcher, "8001")
        self.assertEqual(event["status"], "in_progress")

    def test_a_status_the_event_gives_is_trusted_over_its_bouts(self):
        doc = make_event("8002", "2026-10-01T20:00Z", [("1", 1, "10", "11")], status_name="STATUS_IN_PROGRESS")
        serve_synthetic(self.server, doc, {"1": make_status("STATUS_FINAL", period=1, clock=30.0, result="kotko")})
        event, _ = schedule.crawl_event(self.fetcher, "8002")
        self.assertEqual(event["status"], "in_progress")

    def test_crawl_writes_nothing_to_disk_except_through_the_store_when_asked(self):
        guarded = snapshot(DEFAULT_DIR)          # the tracked dataset directory
        event, bouts = schedule.crawl_event(self.fetcher, COMPLETED)
        self.assertEqual(snapshot(DEFAULT_DIR), guarded)
        self.assertEqual({p.name for p in Path(self.tmp.name).iterdir()}, {"raw"})      # only the fetcher's cache
        store_dir = Path(self.tmp.name) / "ufc"
        store = UfcStore(store_dir)
        self.assertFalse(store_dir.exists())
        counts_e = store.upsert("events", [event])
        counts_b = store.upsert("bouts", bouts)
        self.assertEqual((counts_e["added"], counts_b["added"], counts_b["total"]), (1, 12, 12))
        self.assertEqual({p.name for p in store_dir.iterdir()}, {"events.jsonl", "bouts.jsonl"})
        self.assertEqual(snapshot(DEFAULT_DIR), guarded)
        again = store.upsert("bouts", schedule.crawl_event(self.fetcher, COMPLETED)[1])
        self.assertEqual((again["added"], again["updated"], again["unchanged"]), (0, 0, 12))

    def test_a_recrawl_changes_nothing_but_the_fetch_time(self):
        first_event, first_bouts = schedule.crawl_event(self.fetcher, COMPLETED)
        self.stamp.moment += timedelta(hours=3)                      # the event is read again, later
        event, bouts = schedule.crawl_event(self.fetcher, COMPLETED)
        self.assertNotEqual(event["fetched_utc"], first_event["fetched_utc"])
        strip = lambda rows: [{k: v for k, v in r.items() if k != "fetched_utc"} for r in rows]    # noqa: E731
        self.assertEqual(strip([event]), strip([first_event]))
        self.assertEqual(strip(bouts), strip(first_bouts))
        store = UfcStore(Path(self.tmp.name) / "ufc")
        store.upsert("events", [first_event])
        store.upsert("bouts", first_bouts)
        self.assertEqual(store.upsert("events", [event])["unchanged"], 1)
        self.assertEqual(store.upsert("bouts", bouts)["unchanged"], 12)

    def test_records_survive_the_store_and_feed_its_indexes(self):
        event, bouts = schedule.crawl_event(self.fetcher, COMPLETED)
        store = UfcStore(Path(self.tmp.name) / "ufc")
        store.upsert("events", [event])
        store.upsert("bouts", bouts)
        fresh = UfcStore(Path(self.tmp.name) / "ufc")
        self.assertEqual(fresh.event_by_id()[COMPLETED]["bout_ids"], event["bout_ids"])
        self.assertEqual(fresh.bout_by_id()["401924683"]["result_method"], "SUB")
        self.assertEqual([b["bout_id"] for b in fresh.bouts_by_fighter()["5369427"]], ["401924683"])
        self.assertEqual(fresh.newest("bouts"), "2026-09-27T00:00Z")
        self.assertEqual(fresh.newest("events"), "2026-09-26T21:00Z")


class MinimalFetcher:
    """A fetcher that only has `get_json` and a cache: no `fetched_utc`, no stats."""

    def __init__(self, server):
        self.server = server
        self.cache = {}
        self.requests = 0

    def get_json(self, url, *, use_cache=True, max_age_s=None):
        url = http.canonical_url(url)
        if use_cache and url in self.cache:
            return self.cache[url]
        self.requests += 1
        status, body = self.server.routes[url]
        if status == 404:
            raise http.NotFound(url, 404, "not found")
        self.cache[url] = json.loads(body.decode("utf-8"))
        return self.cache[url]


class MinimalFetcherTests(unittest.TestCase):
    """The crawl must not depend on `fetched_utc`: the request counts hold for any fetcher with a cache."""

    def setUp(self):
        self.server = Server()
        serve_completed_card(self.server)
        self.server.serve(espn_urls.season_events(2026), make_list([COMPLETED]))
        self.fetcher = MinimalFetcher(self.server)

    def test_cold_then_warm_request_counts_of_a_final_event(self):
        event, bouts = schedule.crawl_event(self.fetcher, COMPLETED)
        self.assertEqual((self.fetcher.requests, len(bouts)), (13, 12))
        again = schedule.crawl_event(self.fetcher, COMPLETED)
        self.assertEqual(self.fetcher.requests, 14)                   # exactly one more: the event detail
        strip = lambda rows: [{k: v for k, v in r.items() if k != "fetched_utc"} for r in rows]    # noqa: E731
        self.assertEqual((strip([again[0]]), strip(again[1])), (strip([event]), strip(bouts)))

    def test_a_finished_event_costs_nothing_in_a_season_crawl_once_cached(self):
        schedule.crawl_season(self.fetcher, 2026)
        before = self.fetcher.requests
        events, bouts = schedule.crawl_season(self.fetcher, 2026)
        self.assertEqual(self.fetcher.requests - before, 1)           # only the season list is read again
        self.assertEqual((len(events), len(bouts)), (1, 12))

    def test_upcoming_works_and_a_dropped_bout_is_found_through_known_bouts(self):
        v1 = make_event("9100", "2026-10-10T20:00Z", DroppedBoutTests.BOUTS)
        v2 = make_event("9100", "2026-10-10T20:00Z", DroppedBoutTests.BOUTS[:1] + DroppedBoutTests.BOUTS[2:])
        status = {b[0]: make_status() for b in DroppedBoutTests.BOUTS}
        self.server.serve(espn_urls.season_events(2026), make_list(["9100"]))
        serve_synthetic(self.server, v1, status)
        _, first = schedule.crawl_upcoming(self.fetcher, TODAY)
        self.assertEqual(len(first), 3)
        serve_synthetic(self.server, v2, status)
        _, second = schedule.crawl_upcoming(self.fetcher, TODAY, max_age_s=0, known_bouts=first)
        self.assertEqual({b["bout_id"]: b["status"] for b in second},
                         {"91001": "scheduled", "91002": "canceled", "91003": "scheduled"})


class CrawlScheduledAndCanceledEvents(CrawlCase):
    def test_a_scheduled_card_has_scheduled_bouts_and_no_result(self):
        serve_scheduled_card(self.server)
        (event, bouts), requests = self.requests_during(lambda: schedule.crawl_event(self.fetcher, SCHEDULED))
        self.assertEqual(len(requests), 15)
        self.assertEqual((event["status"], len(bouts)), ("scheduled", 14))
        for bout in bouts:
            self.assertEqual((bout["status"], bout["status_raw"], bout["winner_id"], bout["result_method"],
                              bout["fight_time_s"]), ("scheduled", "STATUS_SCHEDULED", None, None, None))
        # nothing is final, so a second crawl asks for everything again
        _, again = self.requests_during(lambda: schedule.crawl_event(self.fetcher, SCHEDULED))
        self.assertEqual(len(again), 15)

    def test_a_cancelled_card(self):
        serve_canceled_event(self.server)
        event, bouts = schedule.crawl_event(self.fetcher, CANCELED)
        self.assertEqual((event["status"], bouts[0]["status"], bouts[0]["status_raw"]),
                         ("canceled", "canceled", "STATUS_CANCELED"))
        self.assertEqual(bouts[0]["fighter_a_id"], "2431356")


# ---------------------------------------------------------------------------------
# crawl_season
# ---------------------------------------------------------------------------------

class CrawlSeasonTests(CrawlCase):
    def setUp(self):
        super().setUp()
        serve_completed_card(self.server)
        serve_scheduled_card(self.server)
        serve_canceled_event(self.server)
        # One list that stands in for a season; the events carry their own dates.
        self.server.serve(espn_urls.season_events(2026), make_list([SCHEDULED, CANCELED, COMPLETED]))

    def test_every_event_of_the_list_in_date_order(self):
        report = {}
        events, bouts = schedule.crawl_season(self.fetcher, 2026, report=report)
        self.assertEqual([e["event_id"] for e in events], [CANCELED, COMPLETED, SCHEDULED])
        self.assertEqual(len(bouts), 1 + 12 + 14)
        self.assertEqual(report["events_listed"], 3)
        self.assertEqual(sorted(report["events_crawled"]), sorted([CANCELED, COMPLETED, SCHEDULED]))
        # bouts follow their event, main event first
        self.assertEqual([b["event_id"] for b in bouts], [CANCELED] + [COMPLETED] * 12 + [SCHEDULED] * 14)

    def test_since_and_until_pick_events_by_their_utc_day(self):
        events, bouts = schedule.crawl_season(self.fetcher, 2026, since="2026-01-01")
        self.assertEqual([e["event_id"] for e in events], [COMPLETED, SCHEDULED])
        events, _ = schedule.crawl_season(self.fetcher, 2026, until=date(2020, 12, 31))
        self.assertEqual([e["event_id"] for e in events], [CANCELED])
        events, _ = schedule.crawl_season(self.fetcher, 2026, since="2026-09-26", until="2026-09-26")
        self.assertEqual([e["event_id"] for e in events], [COMPLETED])           # both ends inclusive
        events, _ = schedule.crawl_season(self.fetcher, 2026, since=datetime(2026, 10, 3, 23, 0), until="2026-10-03")
        self.assertEqual([e["event_id"] for e in events], [SCHEDULED])

    def test_events_outside_the_dates_cost_one_request_each_and_no_statuses(self):
        _, requests = self.requests_during(lambda: schedule.crawl_season(self.fetcher, 2026, until="2020-12-31"))
        self.assertEqual(len(requests), 1 + 3 + 1)           # the list, three event documents, one status
        self.assertEqual(self.server.count(f"/events/{COMPLETED}/competitions/"), 0)
        self.assertEqual(self.server.count(f"/events/{SCHEDULED}/competitions/"), 0)

    def test_a_finished_event_costs_nothing_on_a_second_run(self):
        schedule.crawl_season(self.fetcher, 2026)
        _, requests = self.requests_during(lambda: schedule.crawl_season(self.fetcher, 2026))
        self.assertFalse([u for u in requests if COMPLETED in u])
        # the list, the cancelled and the scheduled event documents, and their statuses (none is final)
        self.assertEqual(len(requests), 1 + 1 + 1 + 1 + 14)

    def test_max_age_keeps_events_that_are_not_final_for_a_while(self):
        schedule.crawl_season(self.fetcher, 2026, max_age_s=3600)
        _, requests = self.requests_during(lambda: schedule.crawl_season(self.fetcher, 2026, max_age_s=3600))
        self.assertEqual(requests, [])

    def test_an_event_that_is_gone_is_listed_and_skipped(self):
        self.server.serve(espn_urls.season_events(2026), make_list(["5", COMPLETED]))
        self.server.serve(espn_urls.event("5"), b"", status=404)
        report = {}
        events, _ = schedule.crawl_season(self.fetcher, 2026, report=report)
        self.assertEqual([e["event_id"] for e in events], [COMPLETED])
        self.assertEqual(report["events_not_found"], ["5"])

    def test_stored_bouts_that_left_a_card_come_back_canceled_from_a_season_crawl_too(self):
        known = [{"bout_id": "gone", "event_id": SCHEDULED, "status": "scheduled", "fighter_a_id": "1",
                  "fighter_b_id": "2"},
                 {"bout_id": "done", "event_id": COMPLETED, "status": "final", "winner_id": "1"}]
        events, bouts = schedule.crawl_season(self.fetcher, 2026, since="2026-10-03", known_bouts=known)
        self.assertEqual([e["event_id"] for e in events], [SCHEDULED])
        gone = [b for b in bouts if b["bout_id"] == "gone"]
        self.assertEqual([(b["status"], b["status_raw"]) for b in gone], [("canceled", schedule.DROPPED_STATUS_RAW)])
        self.assertEqual(len(bouts), 15)

    def test_an_event_with_no_date_is_crawled_only_when_the_dates_are_unbounded(self):
        doc = make_event("8100", "2026-01-01T20:00Z", [("1", 1, "10", "11")])
        del doc["date"]
        serve_synthetic(self.server, doc, {"1": make_status()})
        self.server.serve(espn_urls.season_events(2027), make_list(["8100"]))
        events, _ = schedule.crawl_season(self.fetcher, 2027)
        self.assertEqual([e["event_id"] for e in events], ["8100"])
        events, _ = schedule.crawl_season(self.fetcher, 2027, since="2026-01-01")
        self.assertEqual(events, [])           # no date, so it cannot be shown to be inside the dates


# ---------------------------------------------------------------------------------
# crawl_upcoming
# ---------------------------------------------------------------------------------

TODAY = date(2026, 10, 3)


class CrawlUpcomingTests(CrawlCase):
    """Five synthetic events around 2026-10-03; a window of 3 days back and 21 forward."""

    def setUp(self):
        super().setUp()
        final = make_status("STATUS_FINAL", period=1, clock=60.0, result="kotko")
        self.old = make_event("9001", "2026-09-26T20:00Z", [("90011", 1, "1", "2"), ("90012", 2, "3", "4")],
                              status_name="STATUS_FINAL", winners={"90011": "1", "90012": "3"})
        self.yesterday = make_event("9002", "2026-10-02T20:00Z", [("90021", 1, "5", "6"), ("90022", 2, "7", "8")],
                                    status_name="STATUS_FINAL", winners={"90021": "5", "90022": "8"})
        self.tonight = make_event("9003", "2026-10-03T20:00Z",
                                  [("90031", 1, "9", "10"), ("90032", 2, "11", "12"), ("90033", 3, "13", "14")])
        self.next = make_event("9004", "2026-10-17T20:00Z", [("90041", 1, "15", "16"), ("90042", 2, "17", "18")])
        self.far = make_event("9005", "2027-03-06T20:00Z", [("90051", 1, "19", "20"), ("90052", 2, "21", "22")])
        scheduled = make_status()
        serve_synthetic(self.server, self.old, {"90011": final, "90012": final})
        serve_synthetic(self.server, self.yesterday, {"90021": final, "90022": final})
        serve_synthetic(self.server, self.tonight, {"90031": scheduled, "90032": scheduled, "90033": scheduled})
        serve_synthetic(self.server, self.next, {"90041": scheduled, "90042": scheduled})
        serve_synthetic(self.server, self.far, {"90051": scheduled, "90052": scheduled})
        self.server.serve(espn_urls.season_events(2026), make_list(["9001", "9002", "9003", "9004", "9005"]))

    def crawl(self, **kw):
        return schedule.crawl_upcoming(self.fetcher, TODAY, **kw)

    def test_the_window_holds_yesterday_today_and_the_next_three_weeks(self):
        report = {}
        events, bouts = self.crawl(report=report)
        self.assertEqual([e["event_id"] for e in events], ["9002", "9003", "9004"])
        self.assertEqual(len(bouts), 2 + 3 + 2)
        self.assertEqual([e["status"] for e in events], ["final", "scheduled", "scheduled"])
        self.assertEqual(report["events_listed"], 5)

    def test_events_outside_the_window_cost_a_document_each_and_no_statuses(self):
        _, requests = self.requests_during(self.crawl)
        self.assertEqual(self.server.count("/events/9001/competitions/"), 0)
        self.assertEqual(self.server.count("/events/9005/competitions/"), 0)
        self.assertEqual(len(requests), 1 + 5 + 2 + 3 + 2)       # list, five documents, statuses of three events

    def test_a_second_run_inside_the_age_costs_nothing(self):
        self.crawl()
        _, requests = self.requests_during(self.crawl)
        self.assertEqual(requests, [])

    def test_old_copies_are_read_again_but_final_ones_and_far_ones_in_time_are_not(self):
        self.stamp.aged(2 * 86400)                    # everything fetched so far looks two days old
        self.crawl()
        self.stamp.fresh()
        _, requests = self.requests_during(lambda: self.crawl(max_age_s=3600))
        self.assertEqual(self.server.count("/events/9001"), 1)                     # final, outside: never again
        self.assertEqual(self.server.count("/events/9002"), 1 + 2)                 # final: kept, statuses kept
        self.assertEqual(self.server.count("/events/9003"), 2 * (1 + 3))           # scheduled: read again
        self.assertEqual(self.server.count("/events/9004"), 2 * (1 + 2))
        self.assertEqual(self.server.count("/events/9005"), 1)                     # far away and only 2 days old
        self.assertEqual(len(requests), 1 + 4 + 3)                                 # list, tonight, next week

    def test_a_far_event_is_looked_at_again_once_its_copy_is_older_than_far_max_age(self):
        self.stamp.aged(2 * 86400)
        self.crawl()
        self.stamp.fresh()
        self.crawl(max_age_s=3600, far_max_age_s=86400)
        self.assertEqual(self.server.count("/events/9005"), 2)
        self.assertEqual(self.server.count("/events/9005/competitions/"), 0)

    def test_the_lookback_decides_whether_the_card_from_a_week_ago_is_included(self):
        events, _ = self.crawl(lookback_days=10)
        self.assertEqual([e["event_id"] for e in events], ["9001", "9002", "9003", "9004"])
        events, _ = self.crawl(lookback_days=0)
        self.assertEqual([e["event_id"] for e in events], ["9003", "9004"])
        events, _ = self.crawl(days=0)
        self.assertEqual([e["event_id"] for e in events], ["9002", "9003"])

    def test_today_may_be_a_string_or_a_datetime(self):
        a = schedule.crawl_upcoming(self.fetcher, "2026-10-03")[0]
        b = schedule.crawl_upcoming(self.fetcher, datetime(2026, 10, 3, 5, 30, tzinfo=timezone.utc))[0]
        self.assertEqual([e["event_id"] for e in a], [e["event_id"] for e in b])

    def test_a_window_inside_one_year_reads_only_that_years_list(self):
        self.server.serve(espn_urls.season_events(2027), make_list(["9005"]))
        events, _ = schedule.crawl_upcoming(self.fetcher, date(2027, 3, 1), days=21)
        self.assertEqual([e["event_id"] for e in events], ["9005"])
        self.assertEqual((self.server.count("dates=2027"), self.server.count("dates=2026")), (1, 0))

    def test_a_window_across_new_year_reads_both_lists_and_keeps_each_event_once(self):
        december = make_event("9007", "2026-12-31T20:00Z", [("90071", 1, "1", "2")])
        january = make_event("9008", "2027-01-03T20:00Z", [("90081", 1, "3", "4")])
        for doc in (december, january):
            serve_synthetic(self.server, doc, {doc["competitions"][0]["id"]: make_status()})
        self.server.serve(espn_urls.season_events(2026), make_list(["9007"]))
        self.server.serve(espn_urls.season_events(2027), make_list(["9008", "9007"]))     # listed twice
        report = {}
        events, bouts = schedule.crawl_upcoming(self.fetcher, date(2027, 1, 2), days=5, report=report)
        self.assertEqual([e["event_id"] for e in events], ["9007", "9008"])
        self.assertEqual(len(bouts), 2)
        self.assertEqual((self.server.count("dates=2026"), self.server.count("dates=2027")), (1, 1))
        self.assertEqual(report["events_listed"], 2)
        self.assertEqual(self.server.count("/events/9007"), 2)          # one document, one status

    def test_a_missing_list_for_the_next_year_is_listed_not_fatal(self):
        december = make_event("9007", "2026-12-31T20:00Z", [("90071", 1, "1", "2")])
        serve_synthetic(self.server, december, {"90071": make_status()})
        self.server.serve(espn_urls.season_events(2026), make_list(["9007"]))
        self.server.serve(espn_urls.season_events(2027), b"", status=404)
        report = {}
        events, _ = schedule.crawl_upcoming(self.fetcher, date(2026, 12, 30), days=21, report=report)
        self.assertEqual([e["event_id"] for e in events], ["9007"])
        self.assertEqual(report["season_lists_not_found"], [2027])
        with self.assertRaises(http.NotFound):                      # asked for directly, it still raises
            schedule.list_season_events(self.fetcher, 2027)

    def test_a_browser_check_or_the_request_cap_stops_the_crawl(self):
        page = b"<html><title>Just a moment...</title>Checking your browser</html>"
        self.server.serve(espn_urls.season_events(2026), page)
        with self.assertRaises(http.SourceBlocked):
            schedule.crawl_upcoming(self.fetcher, TODAY)
        capped = http.PoliteFetcher(cache_dir=Path(self.tmp.name) / "capped", delay_s=0.0, opener=self.server,
                                    sleep=lambda s: None, max_requests=3)
        self.server.serve(espn_urls.season_events(2026), make_list(["9001", "9002", "9003", "9004", "9005"]))
        with self.assertRaises(http.RequestCapReached):
            schedule.crawl_upcoming(capped, TODAY)
        self.assertEqual(capped.stats["requests"], 3)

    def test_a_season_list_is_refreshed_when_old_and_a_new_event_is_picked_up(self):
        self.stamp.aged(86400)
        self.crawl()
        self.stamp.fresh()
        self.server.serve(espn_urls.season_events(2026), make_list(["9001", "9002", "9003", "9004", "9005", "9006"]))
        self.server.serve(espn_urls.event("9006"), make_event("9006", "2026-10-05T20:00Z", [("90061", 1, "1", "2")]))
        self.server.serve(espn_urls.competition_status("9006", "90061"), make_status())
        events, _ = self.crawl()
        self.assertEqual([e["event_id"] for e in events], ["9002", "9003", "9006", "9004"])       # by date


class DroppedBoutTests(CrawlCase):
    """Bouts are cancelled and replaced in the final week; a bout that leaves a card must not stay scheduled."""

    BOUTS = [("91001", 1, "1", "2"), ("91002", 2, "3", "4"), ("91003", 3, "5", "6")]

    def setUp(self):
        super().setUp()
        self.scheduled = {b[0]: make_status() for b in self.BOUTS}
        self.v1 = make_event("9100", "2026-10-10T20:00Z", self.BOUTS)
        self.v2 = make_event("9100", "2026-10-10T20:00Z", [b for b in self.BOUTS if b[0] != "91002"])
        self.server.serve(espn_urls.season_events(2026), make_list(["9100"]))

    def test_a_bout_dropped_from_an_upcoming_card_comes_back_canceled(self):
        serve_synthetic(self.server, self.v1, self.scheduled)
        self.stamp.aged(86400)
        events, bouts = schedule.crawl_upcoming(self.fetcher, TODAY)
        self.assertEqual([b["bout_id"] for b in bouts], ["91001", "91002", "91003"])
        self.assertEqual({b["status"] for b in bouts}, {"scheduled"})

        serve_synthetic(self.server, self.v2, {k: v for k, v in self.scheduled.items() if k != "91002"})
        self.stamp.fresh()
        report = {}
        events, bouts = schedule.crawl_upcoming(self.fetcher, TODAY, report=report)
        self.assertEqual(events[0]["bout_ids"], ["91001", "91003"])
        by_id = {b["bout_id"]: b for b in bouts}
        self.assertEqual(sorted(by_id), ["91001", "91002", "91003"])
        gone = by_id["91002"]
        self.assertEqual((gone["status"], gone["status_raw"]), ("canceled", schedule.DROPPED_STATUS_RAW))
        self.assertEqual((gone["fighter_a_id"], gone["fighter_b_id"], gone["event_id"]), ("3", "4", "9100"))
        self.assertEqual((gone["match_number"], gone["weight_class"], gone["scheduled_rounds"]), (2, "Bantamweight", 3))
        for field in ("winner_id", "result_method", "result_method_raw", "end_round", "fight_time_s"):
            self.assertIsNone(gone[field], field)
        self.assertEqual({by_id["91001"]["status"], by_id["91003"]["status"]}, {"scheduled"})
        self.assertEqual(report["dropped"], ["91002"])
        self.assertEqual(events[0]["status"], "scheduled")

    def test_the_dropped_bout_replaces_the_stored_scheduled_one(self):
        serve_synthetic(self.server, self.v1, self.scheduled)
        self.stamp.aged(86400)
        _, first = schedule.crawl_upcoming(self.fetcher, TODAY)
        store = UfcStore(Path(self.tmp.name) / "ufc")
        store.upsert("bouts", first)
        serve_synthetic(self.server, self.v2, {k: v for k, v in self.scheduled.items() if k != "91002"})
        self.stamp.fresh()
        _, second = schedule.crawl_upcoming(self.fetcher, TODAY)
        counts = store.upsert("bouts", second)
        self.assertEqual((counts["added"], counts["updated"], counts["unchanged"]), (0, 1, 2))
        self.assertEqual(store.bout_by_id()["91002"]["status"], "canceled")

    def test_stored_bouts_find_the_dropped_bout_when_the_cache_is_gone(self):
        serve_synthetic(self.server, self.v1, self.scheduled)
        _, first = schedule.crawl_upcoming(self.fetcher, TODAY)
        # a new machine: empty raw cache, ESPN now serves the card without the bout
        server = Server()
        serve_synthetic(server, self.v2, {k: v for k, v in self.scheduled.items() if k != "91002"})
        server.serve(espn_urls.season_events(2026), make_list(["9100"]))
        fetcher = http.PoliteFetcher(cache_dir=Path(self.tmp.name) / "raw2", delay_s=0.0, opener=server,
                                     sleep=lambda s: None)
        _, without = schedule.crawl_upcoming(fetcher, TODAY)
        self.assertEqual([b["bout_id"] for b in without], ["91001", "91003"])
        _, bouts = schedule.crawl_upcoming(fetcher, TODAY, known_bouts=iter(first))
        self.assertEqual([(b["bout_id"], b["status"]) for b in bouts],
                         [("91001", "scheduled"), ("91003", "scheduled"), ("91002", "canceled")])

    def test_a_bout_that_was_fought_is_never_turned_into_a_cancellation(self):
        serve_synthetic(self.server, self.v2, {k: v for k, v in self.scheduled.items() if k != "91002"})
        fought = {"bout_id": "91002", "event_id": "9100", "status": "final", "winner_id": "3",
                  "result_method": "SUB", "fighter_a_id": "3", "fighter_b_id": "4"}
        has_a_winner = {"bout_id": "91009", "event_id": "9100", "status": "unknown", "winner_id": "7"}
        elsewhere = {"bout_id": "92001", "event_id": "9200", "status": "scheduled"}
        _, bouts = schedule.crawl_upcoming(self.fetcher, TODAY, known_bouts=[fought, has_a_winner, elsewhere])
        self.assertEqual([b["bout_id"] for b in bouts], ["91001", "91003"])

    def test_crawl_event_finds_dropped_bouts_through_the_refreshed_cache_too(self):
        serve_synthetic(self.server, self.v1, self.scheduled)
        schedule.crawl_event(self.fetcher, "9100")
        serve_synthetic(self.server, self.v2, {k: v for k, v in self.scheduled.items() if k != "91002"})
        _, bouts = schedule.crawl_event(self.fetcher, "9100")
        self.assertEqual([(b["bout_id"], b["status"]) for b in bouts],
                         [("91001", "scheduled"), ("91003", "scheduled"), ("91002", "canceled")])

    def test_a_dropped_bout_stays_canceled_on_later_runs_that_know_it(self):
        serve_synthetic(self.server, self.v1, self.scheduled)
        self.stamp.aged(86400)
        schedule.crawl_upcoming(self.fetcher, TODAY)
        serve_synthetic(self.server, self.v2, {k: v for k, v in self.scheduled.items() if k != "91002"})
        self.stamp.fresh()
        _, second = schedule.crawl_upcoming(self.fetcher, TODAY)
        _, third = schedule.crawl_upcoming(self.fetcher, TODAY, known_bouts=second)       # served from the cache
        self.assertEqual({b["bout_id"]: b["status"] for b in third},
                         {"91001": "scheduled", "91002": "canceled", "91003": "scheduled"})

    def test_a_bout_that_comes_back_on_the_card_is_scheduled_again(self):
        serve_synthetic(self.server, self.v2, {k: v for k, v in self.scheduled.items() if k != "91002"})
        canceled = {"bout_id": "91002", "event_id": "9100", "status": "canceled",
                    "status_raw": schedule.DROPPED_STATUS_RAW}
        _, bouts = schedule.crawl_upcoming(self.fetcher, TODAY, known_bouts=[canceled])
        self.assertEqual({b["bout_id"]: b["status"] for b in bouts}["91002"], "canceled")
        serve_synthetic(self.server, self.v1, self.scheduled)
        self.stamp.fresh()
        _, bouts = schedule.crawl_upcoming(self.fetcher, TODAY, max_age_s=0, known_bouts=[canceled])
        self.assertEqual({b["bout_id"]: b["status"] for b in bouts}, {k: "scheduled" for k in ("91001", "91002", "91003")})


if __name__ == "__main__":
    unittest.main()
