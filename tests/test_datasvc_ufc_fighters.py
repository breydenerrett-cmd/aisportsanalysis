"""ESPN athletes as fighter records: parsing, aliases and name matching, the eventlog, and the fetchers.

No network. The fetcher is the real `PoliteFetcher` with an opener that serves saved fixtures by URL
(a URL nobody registered fails the test instead of going out), so 404s, browser checks and the request
cap come from the real code paths. Every expected value below was read off the saved JSON, not copied
from the parser's output.
"""
import copy
import email.message
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from src.datasvc import http, names
from src.datasvc.ufc import espn_urls, fighters
from src.datasvc.ufc.store import UfcStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_mma"
NOW = "2026-10-03T18:00:00Z"


def fixture_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()


class _Response:
    def __init__(self, status, body):
        self.status = status
        self._body = body
        message = email.message.Message()
        message["content-type"] = "application/json"
        self.headers = message

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ServedOpener:
    """Serves bodies by canonical URL and records every call."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def serve(self, url, body=b"{}", *, status=200):
        self.routes[http.canonical_url(url)] = (status, body)

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected request (no network in tests): {url}")
        status, body = self.routes[url]
        if status == 200:
            return _Response(200, body)
        raise urllib.error.HTTPError(url, status, "err", email.message.Message(), io.BytesIO(b""))


CHALLENGE = b"<html><title>Just a moment...</title><body>Checking your browser before accessing</body></html>"


def make_fetcher(cache_dir, opener, *, now_iso=lambda: NOW, **kw):
    return http.PoliteFetcher(cache_dir=Path(cache_dir), opener=opener, sleep=lambda s: None,
                              now_iso=now_iso, **kw)


def parse(athlete_file, records_file=None):
    return fighters.parse_athlete(fixture_json(athlete_file),
                                  fixture_json(records_file) if records_file else None,
                                  fetched_utc=NOW, source_url="https://example.test/athlete")


# Every fighter fixture, parsed once; the name-matching tests run against this whole set.
def _all_fighters():
    return [
        parse("athlete_4412813.json", "athlete_4412813_records.json"),
        parse("athlete_4001851.json", "athlete_4001851_records.json"),
        parse("w2_athlete_5450121.json", "w2_athlete_5450121_records.json"),
        parse("w2_athlete_5088844.json"),
        parse("w2_athlete_4274796.json"),
        parse("w2_athlete_2447641.json"),
        parse("w2_athlete_3154389.json"),
        parse("w2_athlete_5345639.json"),
        parse("w2_athlete_2335447.json", "w2_athlete_2335447_records.json"),
        parse("w2_athlete_4054605.json"),
    ]


class ParseAthleteFields(unittest.TestCase):
    def test_ismail_naurdiev_field_by_field(self):
        self.assertEqual(parse("athlete_4412813.json", "athlete_4412813_records.json"), {
            "fighter_id": "4412813", "name": "Ismail Naurdiev", "first_name": "Ismail", "last_name": "Naurdiev",
            "nickname": "The Austrian Wonderboy", "dob": "1996-08-18", "height_in": 70.0, "reach_in": 74.0,
            "weight_lb": 185.0, "stance": "Orthodox", "weight_class": "Middleweight", "citizenship": "Morocco",
            "active": True, "record": {"wins": 25, "losses": 8, "draws": 0, "no_contests": 0},
            "espn_slug": "ismail-naurdiev", "aliases": ["ismail naurdiev", "i naurdiev"],
            "source_url": "https://example.test/athlete", "fetched_utc": NOW,
        })

    def test_marvin_vettori_field_by_field(self):
        self.assertEqual(parse("athlete_4001851.json", "athlete_4001851_records.json"), {
            "fighter_id": "4001851", "name": "Marvin Vettori", "first_name": "Marvin", "last_name": "Vettori",
            "nickname": "The Italian Dream", "dob": "1993-09-20", "height_in": 72.0, "reach_in": 74.0,
            "weight_lb": 186.0, "stance": "Southpaw", "weight_class": "Middleweight", "citizenship": "Italy",
            "active": True, "record": {"wins": 19, "losses": 10, "draws": 1, "no_contests": 0},
            "espn_slug": "marvin-vettori", "aliases": ["marvin vettori", "m vettori"],
            "source_url": "https://example.test/athlete", "fetched_utc": NOW,
        })

    def test_the_record_has_exactly_the_contract_fields(self):
        contract = {"fighter_id", "name", "first_name", "last_name", "nickname", "dob", "height_in", "reach_in",
                    "weight_lb", "stance", "weight_class", "citizenship", "active", "record", "espn_slug", "aliases"}
        record = parse("athlete_4412813.json")
        self.assertEqual(set(record), contract | {"source_url", "fetched_utc"})
        self.assertEqual(tuple(record), fighters.FIGHTER_FIELDS)

    def test_a_record_with_no_records_json_is_null_not_zero(self):
        self.assertIsNone(parse("athlete_4412813.json")["record"])

    def test_ESPN_zero_for_reach_and_dash_for_stance_are_null(self):
        # Lucas Armand: "reach": 0.0 and "stance": {"id": "0", "text": "--"}, "displayReach" absent.
        armand = fixture_json("w2_athlete_5450121.json")
        self.assertEqual((armand["reach"], armand["stance"]["text"]), (0.0, "--"))
        record = parse("w2_athlete_5450121.json", "w2_athlete_5450121_records.json")
        self.assertIsNone(record["reach_in"])
        self.assertIsNone(record["stance"])
        # what ESPN does have for him is kept
        self.assertEqual((record["name"], record["nickname"], record["dob"], record["height_in"],
                          record["weight_lb"], record["weight_class"], record["citizenship"], record["active"]),
                         ("Lucas Armand", "Do or Die", "1995-10-26", 76.0, 264.0, "Heavyweight", "USA", True))
        self.assertEqual(record["record"], {"wins": 6, "losses": 0, "draws": 0, "no_contests": 0})

    def test_a_mononym_has_no_last_name_and_one_alias(self):
        record = parse("w2_athlete_3154389.json")
        self.assertNotIn("lastName", fixture_json("w2_athlete_3154389.json"))
        self.assertEqual((record["name"], record["first_name"], record["last_name"]),
                         ("Alatengheili", "Alatengheili", None))
        self.assertEqual(record["aliases"], ["alatengheili"])
        self.assertEqual(record["nickname"], "The Mongolian Knight")

    def test_an_absent_nickname_is_null_and_a_half_inch_reach_survives(self):
        record = parse("w2_athlete_5345639.json")
        self.assertNotIn("nickname", fixture_json("w2_athlete_5345639.json"))
        self.assertIsNone(record["nickname"])
        self.assertEqual((record["last_name"], record["reach_in"], record["height_in"]), ("Akylbek Uulu", 66.5, 67.0))
        self.assertEqual(record["aliases"], ["ilimbek akylbek uulu", "i akylbek uulu"])

    def test_a_suffix_stays_in_the_names_and_never_becomes_an_alias_of_its_own(self):
        record = parse("w2_athlete_5088844.json")
        self.assertEqual((record["name"], record["last_name"], record["espn_slug"]),
                         ("Raul Rosas Jr.", "Rosas Jr.", "raul-rosas-jr"))
        self.assertEqual(record["nickname"], "El Niño Problema")      # stored as ESPN spells it
        self.assertEqual(record["aliases"], ["raul rosas jr", "r rosas jr"])
        self.assertEqual((record["dob"], record["stance"], record["weight_lb"]), ("2004-10-08", "Switch", 136.0))

    def test_accents_are_kept_in_the_name_and_folded_in_the_aliases(self):
        record = parse("w2_athlete_4274796.json")
        self.assertEqual((record["name"], record["last_name"], record["espn_slug"]),
                         ("Roberto Soldić", "Soldić", "roberto-soldic"))
        self.assertEqual(record["aliases"], ["roberto soldic", "r soldic"])
        self.assertEqual((record["dob"], record["citizenship"], record["weight_class"]),
                         ("1995-01-25", "Croatia", "Welterweight"))

    def test_active_is_stored_as_ESPN_says_even_when_the_fighter_is_retired(self):
        # Jose Aldo is "Retired" on UFC.com (saved page) and active: true here.
        self.assertIs(parse("w2_athlete_2447641.json")["active"], True)
        self.assertEqual(parse("w2_athlete_2447641.json")["name"], "José Aldo")

    def test_an_inactive_fighter_and_a_no_contest_in_the_record(self):
        record = parse("w2_athlete_2335447.json", "w2_athlete_2335447_records.json")
        self.assertIs(record["active"], False)
        self.assertEqual(record["record"], {"wins": 34, "losses": 11, "draws": 0, "no_contests": 1})

    def test_a_womens_weight_class_keeps_its_prefix(self):
        self.assertEqual(parse("w2_athlete_4054605.json")["weight_class"], "Women's Flyweight")


class ParseAthleteMissingData(unittest.TestCase):
    def athlete(self):
        return copy.deepcopy(fixture_json("athlete_4412813.json"))

    def parse_variant(self, athlete, records=None):
        return fighters.parse_athlete(athlete, records, fetched_utc=NOW, source_url="u")

    def test_absent_keys_and_unusable_values_are_all_null(self):
        athlete = self.athlete()
        del athlete["dateOfBirth"]
        del athlete["weightClass"]
        athlete["height"] = 0.0
        athlete["reach"] = -1
        athlete["weight"] = "n/a"
        athlete["stance"] = {"id": "0", "text": ""}
        athlete["citizenship"] = "--"
        athlete["nickname"] = "  "
        athlete["active"] = "yes"
        record = self.parse_variant(athlete)
        for key in ("dob", "weight_class", "height_in", "reach_in", "weight_lb", "stance", "citizenship",
                    "nickname", "active"):
            self.assertIsNone(record[key], key)
        self.assertEqual(record["name"], "Ismail Naurdiev")          # the rest is untouched

    def test_a_placeholder_or_impossible_birth_date_is_null(self):
        for value in ("0001-01-01T00:00Z", "1996-02-30T07:00Z", "not a date", "", None):
            athlete = self.athlete()
            athlete["dateOfBirth"] = value
            self.assertIsNone(self.parse_variant(athlete)["dob"], value)

    def test_the_birth_date_is_the_date_part_as_ESPN_gives_it(self):
        athlete = self.athlete()
        athlete["dateOfBirth"] = "1995-01-25T08:00Z"
        self.assertEqual(self.parse_variant(athlete)["dob"], "1995-01-25")

    def test_records_without_an_overall_item_give_no_record(self):
        records = fixture_json("athlete_4412813_records.json")
        records["items"][0]["name"], records["items"][0]["type"] = "home", "home"
        self.assertIsNone(self.parse_variant(self.athlete(), records)["record"])
        self.assertIsNone(self.parse_variant(self.athlete(), {"items": []})["record"])
        self.assertIsNone(self.parse_variant(self.athlete(), {})["record"])

    def test_the_summary_is_the_fallback_when_the_stats_are_unusable(self):
        records = fixture_json("athlete_4412813_records.json")
        records["items"][0]["stats"] = [{"name": "wins", "value": 25.5}]
        self.assertEqual(self.parse_variant(self.athlete(), records)["record"],
                         {"wins": 25, "losses": 8, "draws": 0})
        records["items"][0]["summary"] = "garbage"
        records["items"][0]["displayValue"] = "garbage"
        self.assertIsNone(self.parse_variant(self.athlete(), records)["record"])

    def test_no_contests_is_only_present_when_the_records_carry_it(self):
        records = fixture_json("athlete_4412813_records.json")
        records["items"][0]["stats"] = [s for s in records["items"][0]["stats"] if s["name"] != "noContests"]
        self.assertEqual(self.parse_variant(self.athlete(), records)["record"], {"wins": 25, "losses": 8, "draws": 0})

    def test_an_athlete_without_an_id_is_an_error(self):
        athlete = self.athlete()
        del athlete["id"]
        with self.assertRaises(ValueError):
            self.parse_variant(athlete)
        with self.assertRaises(ValueError):
            self.parse_variant({})
        with self.assertRaises(ValueError):
            self.parse_variant(None)

    def test_the_name_falls_back_to_first_and_last(self):
        athlete = self.athlete()
        del athlete["displayName"]
        del athlete["fullName"]
        self.assertEqual(self.parse_variant(athlete)["name"], "Ismail Naurdiev")


class Aliases(unittest.TestCase):
    def test_initials_are_joined_and_split_so_sources_that_disagree_still_meet(self):
        athlete = {"id": "1", "displayName": "TJ Dillashaw", "fullName": "TJ Dillashaw", "firstName": "TJ",
                   "lastName": "Dillashaw", "shortName": "T. Dillashaw"}
        self.assertEqual(fighters.alias_forms(athlete), ["tj dillashaw", "t j dillashaw", "t dillashaw"])
        dotted = {"id": "2", "displayName": "T.J. Dillashaw"}
        self.assertEqual(fighters.alias_forms(dotted), ["t j dillashaw", "tj dillashaw"])

    def test_collapse_initials(self):
        self.assertEqual(fighters.collapse_initials("t j dillashaw"), "tj dillashaw")
        self.assertEqual(fighters.collapse_initials("c b dollaway"), "cb dollaway")
        self.assertEqual(fighters.collapse_initials("i naurdiev"), "i naurdiev")      # a lone initial stays
        self.assertEqual(fighters.collapse_initials("jose a silva"), "jose a silva")

    def test_no_fighter_has_a_bare_last_name_as_an_alias(self):
        for fighter in _all_fighters():
            if not fighter["last_name"]:
                continue
            bare = names.normalise(fighter["last_name"])
            self.assertNotIn(bare, fighter["aliases"], fighter["name"])
            for alias in fighter["aliases"]:
                self.assertGreaterEqual(len(alias.split()), 2, (fighter["name"], alias))

    def test_aliases_are_normalised_and_unique(self):
        for fighter in _all_fighters():
            self.assertEqual(fighter["aliases"], list(dict.fromkeys(fighter["aliases"])))
            for alias in fighter["aliases"]:
                self.assertEqual(alias, names.normalise(alias))


class NameIndexAndMatching(unittest.TestCase):
    def setUp(self):
        self.fighters = _all_fighters()
        self.index = fighters.name_index(self.fighters)

    def best(self, query):
        return names.match(query, self.index).best

    def test_the_index_maps_each_id_to_its_aliases(self):
        self.assertEqual(len(self.index), 10)
        self.assertEqual(self.index["4412813"], ["ismail naurdiev", "i naurdiev"])
        self.assertEqual(self.index["4274796"], ["roberto soldic", "r soldic"])

    def test_an_exact_name_is_a_perfect_match(self):
        result = names.match("Ismail Naurdiev", self.index)
        self.assertEqual(result.best, "4412813")
        self.assertEqual(result.candidates[0][2], 1.0)
        self.assertEqual(self.best("Marvin Vettori"), "4001851")

    def test_a_last_name_alone_finds_the_fighter(self):
        for query, fid in (("Naurdiev", "4412813"), ("Vettori", "4001851"), ("Rosas", "5088844"),
                           ("Aldo", "2447641"), ("Soldic", "4274796"), ("Armand", "5450121"),
                           ("Akylbek Uulu", "5345639"), ("Alatengheili", "3154389")):
            self.assertEqual(self.best(query), fid, query)

    def test_an_accented_query_matches_with_or_without_the_accent(self):
        for query in ("Roberto Soldić", "Roberto Soldic", "SOLDIĆ", "r. soldić"):
            self.assertEqual(self.best(query), "4274796", query)
        for query in ("José Aldo", "Jose Aldo", "jose  aldo"):
            self.assertEqual(self.best(query), "2447641", query)

    def test_a_suffix_may_be_left_out_or_included(self):
        for query in ("Raul Rosas Jr.", "Raul Rosas", "Rosas Jr", "R. Rosas Jr."):
            self.assertEqual(self.best(query), "5088844", query)

    def test_an_ambiguous_last_name_names_both_and_picks_nobody(self):
        result = names.match("Silva", self.index)
        self.assertIsNone(result.best)
        self.assertTrue(result.ambiguous)
        self.assertEqual({c[0] for c in result.candidates}, {"2335447", "4054605"})
        self.assertEqual(self.best("Anderson Silva"), "2335447")
        self.assertEqual(self.best("Natalia Silva"), "4054605")
        self.assertEqual(self.best("N. Silva"), "4054605")

    def test_an_unknown_name_matches_nobody(self):
        result = names.match("Conor McGregor", self.index)
        self.assertEqual((result.best, result.ambiguous), (None, False))

    def test_the_index_is_rebuilt_from_the_name_fields_when_aliases_are_missing(self):
        bare = {"fighter_id": "9", "name": "José Aldo", "first_name": "José", "last_name": "Aldo"}
        self.assertEqual(fighters.name_index([bare]), {"9": ["jose aldo"]})

    def test_a_record_without_an_id_is_skipped(self):
        self.assertEqual(fighters.name_index([{"name": "No Id"}, {"fighter_id": " ", "name": "Blank"}]), {})


class EventlogParsing(unittest.TestCase):
    UFC_FIRST_PAGE = [
        ("600061182", "401912275", False), ("600055175", "401830357", True), ("600053795", "401767027", True),
        ("600044733", "401720687", True), ("401189213", "276819", True), ("401131741", "271260", True),
        ("401122133", "266595", True), ("401098398", "260175", True),
    ]

    def test_the_ufc_bouts_of_the_first_page_in_ESPNs_order(self):
        self.assertEqual(fighters.eventlog_bouts(fixture_json("athlete_4412813_eventlog.json")), self.UFC_FIRST_PAGE)

    def test_only_the_upcoming_bout_is_unplayed(self):
        bouts = fighters.eventlog_bouts(fixture_json("athlete_4412813_eventlog.json"))
        self.assertEqual([b for b in bouts if not b[2]], [("600061182", "401912275", False)])

    def test_other_promotions_are_left_out_by_default_and_available_on_request(self):
        page = fixture_json("athlete_4412813_eventlog.json")        # 25 entries: 8 UFC, 17 other
        everything = fighters.eventlog_bouts(page, league=None)
        other = fighters.eventlog_bouts(page, league="other")
        self.assertEqual((len(everything), len(other)), (25, 17))
        self.assertIn(("600043454", "401715270", True), other)
        self.assertNotIn(("600043454", "401715270", True), self.UFC_FIRST_PAGE)
        self.assertEqual([b for b in everything if b in other or b in self.UFC_FIRST_PAGE], everything)
        self.assertEqual(set(other) & set(self.UFC_FIRST_PAGE), set())

    def test_a_whole_career_in_one_page(self):
        page = fixture_json("w2_athlete_4412813_eventlog_limit200.json")
        self.assertEqual(page["events"]["pageCount"], 1)
        self.assertEqual(len(fighters.eventlog_bouts(page, league=None)), 34)
        self.assertEqual(fighters.eventlog_bouts(page), self.UFC_FIRST_PAGE)

    def test_a_fighter_with_mostly_ufc_fights(self):
        page = fixture_json("athlete_4001851_eventlog.json")        # 25 entries: 19 UFC, 6 other
        self.assertEqual(len(fighters.eventlog_bouts(page)), 19)
        self.assertEqual(len(fighters.eventlog_bouts(page, league=None)), 25)

    def test_entries_that_cannot_be_read_are_skipped_and_duplicates_listed_once(self):
        ref = lambda event, comp: {  # noqa: E731
            "event": {"$ref": f"http://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{event}?lang=en"},
            "competition": {"$ref": f"http://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{event}/competitions/{comp}?lang=en"},
            "played": True}
        page = {"events": {"items": [
            ref("1", "10"), ref("1", "10"), ref("2", "20"),
            {"event": {"$ref": "http://x/leagues/ufc/events/3"}, "played": True},             # no competition
            {"competition": {"$ref": "http://x/competitions/4"}, "played": True},              # no event
            {"event": {"$ref": "not a ref"}, "competition": {"$ref": "http://x/competitions/5"}},
            "junk", None,
            {**ref("6", "60"), "played": None},
        ]}}
        self.assertEqual(fighters.eventlog_bouts(page), [("1", "10", True), ("2", "20", True), ("6", "60", False)])

    def test_empty_and_malformed_input_give_an_empty_list(self):
        for bad in (None, {}, [], {"events": None}, {"events": {}}, {"events": {"items": None}}, "x"):
            self.assertEqual(fighters.eventlog_bouts(bad), [])


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.opener = ServedOpener()
        self.fetcher = make_fetcher(self.tmp.name, self.opener)

    def serve_fighter(self, fid, athlete_file, records_file=None):
        self.opener.serve(espn_urls.athlete(fid), fixture_bytes(athlete_file))
        if records_file:
            self.opener.serve(espn_urls.athlete_records(fid), fixture_bytes(records_file))

    def test_fetch_fighter_returns_the_parsed_record_from_two_requests(self):
        self.serve_fighter("4412813", "athlete_4412813.json", "athlete_4412813_records.json")
        fighter = fighters.fetch_fighter(self.fetcher, "4412813")
        self.assertEqual(fighter, fighters.parse_athlete(
            fixture_json("athlete_4412813.json"), fixture_json("athlete_4412813_records.json"),
            fetched_utc=NOW, source_url=espn_urls.athlete("4412813")))
        self.assertEqual(fighter["record"], {"wins": 25, "losses": 8, "draws": 0, "no_contests": 0})
        self.assertEqual(self.opener.calls, [http.canonical_url(espn_urls.athlete("4412813")),
                                             http.canonical_url(espn_urls.athlete_records("4412813"))])

    def test_without_records_it_is_one_request_and_a_null_record(self):
        self.serve_fighter("4412813", "athlete_4412813.json")
        fighter = fighters.fetch_fighter(self.fetcher, "4412813", with_records=False)
        self.assertIsNone(fighter["record"])
        self.assertEqual(len(self.opener.calls), 1)

    def test_a_404_on_the_records_alone_still_returns_the_athlete(self):
        self.serve_fighter("4412813", "athlete_4412813.json")
        self.opener.serve(espn_urls.athlete_records("4412813"), status=404)
        fighter = fighters.fetch_fighter(self.fetcher, "4412813")
        self.assertEqual((fighter["name"], fighter["record"]), ("Ismail Naurdiev", None))

    def test_an_athlete_404_is_raised_as_not_found(self):
        self.opener.serve(espn_urls.athlete("9999999"), status=404)
        with self.assertRaises(http.NotFound):
            fighters.fetch_fighter(self.fetcher, "9999999")

    def test_a_response_for_a_different_athlete_is_an_error(self):
        self.opener.serve(espn_urls.athlete("4412813"), fixture_bytes("athlete_4001851.json"))
        with self.assertRaises(ValueError):
            fighters.fetch_fighter(self.fetcher, "4412813")

    def test_fetched_utc_is_the_older_of_the_two_pages(self):
        stamps = iter(["2026-10-03T18:00:00Z", "2026-10-03T19:30:00Z"])
        fetcher = make_fetcher(self.tmp.name + "/second", self.opener, now_iso=lambda: next(stamps))
        self.serve_fighter("4412813", "athlete_4412813.json", "athlete_4412813_records.json")
        self.assertEqual(fighters.fetch_fighter(fetcher, "4412813")["fetched_utc"], "2026-10-03T18:00:00Z")

    def test_max_age_makes_a_stale_cached_fighter_refetch(self):
        self.serve_fighter("4412813", "athlete_4412813.json")
        fighters.fetch_fighter(self.fetcher, "4412813", with_records=False)
        fighters.fetch_fighter(self.fetcher, "4412813", with_records=False)
        self.assertEqual(len(self.opener.calls), 1)                     # second read came from the cache
        fighters.fetch_fighter(self.fetcher, "4412813", with_records=False, max_age_s=60)
        self.assertEqual(len(self.opener.calls), 2)                     # the cached copy is long past 60 s


class FetchBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.opener = ServedOpener()
        self.fetcher = make_fetcher(self.tmp.name, self.opener)
        for fid, athlete, records in (("4412813", "athlete_4412813.json", "athlete_4412813_records.json"),
                                      ("4001851", "athlete_4001851.json", "athlete_4001851_records.json")):
            self.opener.serve(espn_urls.athlete(fid), fixture_bytes(athlete))
            self.opener.serve(espn_urls.athlete_records(fid), fixture_bytes(records))

    def test_one_404_is_reported_in_the_result_and_the_batch_carries_on(self):
        self.opener.serve(espn_urls.athlete("9999999"), status=404)
        batch = fighters.fetch_fighters(self.fetcher, ["4412813", "9999999", "4001851"])
        self.assertEqual([f["fighter_id"] for f in batch.fighters], ["4412813", "4001851"])
        self.assertEqual(len(batch.failed), 1)
        self.assertEqual({k: batch.failed[0][k] for k in ("fighter_id", "kind", "status")},
                         {"fighter_id": "9999999", "kind": "not_found", "status": 404})
        self.assertEqual(batch.not_found, ["9999999"])
        self.assertIn("9999999", batch.failed[0]["message"])

    def test_ids_are_fetched_once_each_and_blanks_are_skipped(self):
        batch = fighters.fetch_fighters(self.fetcher, ["4412813", 4412813, " ", "", "4001851", "4412813"])
        self.assertEqual([f["fighter_id"] for f in batch.fighters], ["4412813", "4001851"])
        self.assertEqual(batch.failed, [])
        self.assertEqual(len(self.opener.calls), 4)

    def test_a_server_error_for_one_fighter_is_reported_and_the_rest_still_arrive(self):
        self.opener.serve(espn_urls.athlete("7"), status=500)
        batch = fighters.fetch_fighters(self.fetcher, ["7", "4412813"])
        self.assertEqual([f["fighter_id"] for f in batch.fighters], ["4412813"])
        self.assertEqual((batch.failed[0]["fighter_id"], batch.failed[0]["kind"], batch.failed[0]["status"]),
                         ("7", "error", 500))
        self.assertEqual(batch.not_found, [])

    def test_a_bad_payload_for_one_fighter_is_reported(self):
        self.opener.serve(espn_urls.athlete("8"), fixture_bytes("athlete_4001851.json"))   # id 4001851, asked 8
        batch = fighters.fetch_fighters(self.fetcher, ["8", "4412813"])
        self.assertEqual([f["fighter_id"] for f in batch.fighters], ["4412813"])
        self.assertEqual((batch.failed[0]["fighter_id"], batch.failed[0]["kind"]), ("8", "bad_response"))

    def test_a_browser_check_stops_the_batch(self):
        self.opener.serve(espn_urls.athlete("5"), CHALLENGE)
        self.opener.serve(espn_urls.athlete("4001851"), fixture_bytes("athlete_4001851.json"))
        with self.assertRaises(http.SourceBlocked):
            fighters.fetch_fighters(self.fetcher, ["4412813", "5", "4001851"])
        self.assertNotIn(http.canonical_url(espn_urls.athlete("4001851")), self.opener.calls)

    def test_a_403_is_a_refusal_not_a_missing_page_and_stops_the_batch(self):
        self.opener.serve(espn_urls.athlete("6"), status=403)
        with self.assertRaises(http.FetchError) as caught:
            fighters.fetch_fighters(self.fetcher, ["6", "4412813"])
        self.assertEqual(caught.exception.status, 403)
        self.assertNotIn(http.canonical_url(espn_urls.athlete("4412813")), self.opener.calls)

    def test_the_request_cap_stops_the_batch_and_a_rerun_resumes_from_the_cache(self):
        capped = make_fetcher(self.tmp.name, self.opener, max_requests=3)
        with self.assertRaises(http.RequestCapReached):
            fighters.fetch_fighters(capped, ["4412813", "4001851"])      # needs 4 requests, has 3
        before = len(self.opener.calls)
        self.assertEqual(before, 3)
        resumed = make_fetcher(self.tmp.name, self.opener)
        batch = fighters.fetch_fighters(resumed, ["4412813", "4001851"])
        self.assertEqual([f["fighter_id"] for f in batch.fighters], ["4412813", "4001851"])
        self.assertEqual(len(self.opener.calls) - before, 1)            # only the one page it never got

    def test_a_batch_result_round_trips_through_the_fighters_store(self):
        batch = fighters.fetch_fighters(self.fetcher, ["4412813", "4001851"])
        store = UfcStore(Path(self.tmp.name) / "ufc")
        self.assertEqual(store.upsert("fighters", batch.fighters), {"added": 2, "updated": 0, "unchanged": 0, "total": 2})
        self.assertEqual(store.upsert("fighters", batch.fighters)["unchanged"], 2)
        self.assertEqual(store.fighter_by_id()["4412813"]["record"]["wins"], 25)


class FetchEventlog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.opener = ServedOpener()
        self.fetcher = make_fetcher(self.tmp.name, self.opener)

    def test_a_whole_career_comes_back_from_one_request(self):
        self.opener.serve(espn_urls.athlete_eventlog("4412813"), fixture_bytes("w2_athlete_4412813_eventlog_limit200.json"))
        self.assertEqual(fighters.fetch_eventlog_bouts(self.fetcher, "4412813"), EventlogParsing.UFC_FIRST_PAGE)
        self.assertEqual(len(self.opener.calls), 1)

    def test_a_paged_answer_is_followed_to_the_last_page(self):
        # ESPN answering the 200-entry request with page 1 of 2 (25 per page), as the saved default fixture does.
        self.opener.serve(espn_urls.athlete_eventlog("4412813"), fixture_bytes("athlete_4412813_eventlog.json"))
        self.opener.serve(espn_urls.athlete_eventlog("4412813", limit=25) + "&page=2",
                          fixture_bytes("w2_athlete_4412813_eventlog_page2.json"))
        everything = fighters.fetch_eventlog_bouts(self.fetcher, "4412813", league=None)
        self.assertEqual(everything, fighters.eventlog_bouts(fixture_json("w2_athlete_4412813_eventlog_limit200.json"),
                                                             league=None))
        self.assertEqual(len(everything), 34)
        self.assertEqual(len(self.opener.calls), 2)

    def test_paged_answer_with_ufc_only_still_gets_the_ufc_bouts(self):
        self.opener.serve(espn_urls.athlete_eventlog("4412813"), fixture_bytes("athlete_4412813_eventlog.json"))
        self.opener.serve(espn_urls.athlete_eventlog("4412813", limit=25) + "&page=2",
                          fixture_bytes("w2_athlete_4412813_eventlog_page2.json"))
        self.assertEqual(fighters.fetch_eventlog_bouts(self.fetcher, "4412813"), EventlogParsing.UFC_FIRST_PAGE)

    def test_max_pages_limits_how_far_it_follows(self):
        self.opener.serve(espn_urls.athlete_eventlog("4412813"), fixture_bytes("athlete_4412813_eventlog.json"))
        fighters.fetch_eventlog_bouts(self.fetcher, "4412813", max_pages=1)
        self.assertEqual(len(self.opener.calls), 1)

    def test_an_eventlog_404_is_raised(self):
        self.opener.serve(espn_urls.athlete_eventlog("9999999"), status=404)
        with self.assertRaises(http.NotFound):
            fighters.fetch_eventlog_bouts(self.fetcher, "9999999")


if __name__ == "__main__":
    unittest.main()
