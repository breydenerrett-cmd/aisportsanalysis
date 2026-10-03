"""Odds (src/datasvc/ufc/odds.py): parser, orientation, fetching.

No network. The parser runs on the saved ESPN odds responses in tests/fixtures/espn_mma
(four DraftKings bouts of 2026 and the `w3_` captures of 2019 to 2025, 38 provider rows in 9
bouts, plus five bouts with an empty odds list); the bout records are built from the
scoreboard fixtures with competitor `order` 1 as fighter a, so the answer to "which side is
fighter a" never comes from the odds being tested. Fetching goes through a fake fetcher
serving those files by URL, and through a real PoliteFetcher over a scripted opener for the
cache behaviour.
"""
import copy
import email.message
import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.datasvc import http
from src.datasvc.ufc import espn_urls, odds

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_mma"
FETCHED = "2026-10-03T18:00:00Z"
SRC = "https://example.test/odds"

# (odds fixture, scoreboard fixture, bout id, provider rows)
ODDS = [
    ("odds_401911630.json", "scoreboard_2026-09-26.json", "401911630", 1),
    ("odds_401914466.json", "scoreboard_2026-09-26.json", "401914466", 1),
    ("odds_401924683.json", "scoreboard_2026-09-26.json", "401924683", 1),
    ("odds_401912275_upcoming.json", "scoreboard_2026-10-03.json", "401912275", 1),
    ("w3_odds_401499752_draw_2022.json", "w3_scoreboard_2022-12-10.json", "401499752", 8),
    ("w3_odds_266329_2019.json", "w3_scoreboard_2019-09-07.json", "266329", 6),
    ("w3_odds_401320793_2021.json", "w3_scoreboard_2021-07-10.json", "401320793", 6),
    ("w3_odds_401632019_2024.json", "w3_scoreboard_2024-04-13.json", "401632019", 12),
    ("w3_odds_401799532_2025.json", "w3_scoreboard_2025-07-19.json", "401799532", 2),
]
# Bouts whose odds list is empty: 2016 (UFC 200), 2017 (UFC 214, the no contest), 2018-04, 2019-03, 2019-06.
EMPTY = [
    ("odds_223077_2016.json", "scoreboard_2016-07-09.json", "223077"),
    ("w3_odds_236217_nc_2017.json", "w3_scoreboard_2017-07-29.json", "236217"),
    ("w3_odds_243591_2018.json", "w3_scoreboard_2018-04-07.json", "243591"),
    ("w3_odds_260896_2019_03.json", "w3_scoreboard_2019-03-02.json", "260896"),
    ("w3_odds_263613_2019_06.json", "w3_scoreboard_2019-06-08.json", "263613"),
]


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def competition(scoreboard, comp_id):
    for event in load(scoreboard)["events"]:
        for comp in event["competitions"]:
            if comp["id"] == comp_id:
                return event, comp
    raise KeyError(comp_id)


def bout_of(scoreboard, comp_id, status=None):
    """A bouts.jsonl-shaped record: order 1 is fighter a, order 2 is fighter b."""
    event, comp = competition(scoreboard, comp_id)
    by_order = {c["order"]: c for c in comp["competitors"]}
    winners = [c["id"] for c in comp["competitors"] if c.get("winner")]
    mapped = {"STATUS_FINAL": "final", "STATUS_SCHEDULED": "scheduled"}
    return {"bout_id": comp["id"], "event_id": event["id"], "date_utc": comp["date"],
            "status": status or mapped[comp["status"]["type"]["name"]],
            "fighter_a_id": by_order[1]["id"], "fighter_b_id": by_order[2]["id"],
            "winner_id": winners[0] if winners else None}


def fighters_of(scoreboard, comp_id):
    """id -> fighter record (name only), as the fighters worker's store would hold them."""
    _, comp = competition(scoreboard, comp_id)
    return {c["id"]: {"name": c["athlete"]["displayName"]} for c in comp["competitors"]}


def athlete_id(ref):
    return re.search(r"/athletes/(\d+)", ref["$ref"]).group(1)


def parse(odds_name, scoreboard, comp_id, *, status=None, fighters=False, page=None, bout=None):
    bout = bout or bout_of(scoreboard, comp_id, status)
    return odds.parse_odds(page if page is not None else load(odds_name), bout=bout, fetched_utc=FETCHED,
                           source_url=SRC, fighters=fighters_of(scoreboard, comp_id) if fighters else None)


def without_athlete_refs(page):
    page = copy.deepcopy(page)
    for item in page["items"]:
        for side in ("homeAthleteOdds", "awayAthleteOdds"):
            item[side].pop("athlete", None)
    return page


def by_provider(rows):
    return {r["provider_id"]: r for r in rows}


class FixtureFetcher:
    """Duck-types PoliteFetcher: serves payloads by canonical URL and records every call."""

    def __init__(self, routes=None, *, missing=(), errors=None, fetched=None, cached=True):
        canon = http.canonical_url
        self.routes = {canon(u): p for u, p in (routes or {}).items()}
        self.missing = {canon(u) for u in missing}
        self.errors = {canon(u): e for u, e in (errors or {}).items()}
        self.fetched = {canon(u): s for u, s in (fetched or {}).items()}
        self.cached = cached
        self.calls = []

    def get_json(self, url, *, use_cache=True, max_age_s=None):
        canon = http.canonical_url(url)
        self.calls.append({"url": canon, "use_cache": use_cache, "max_age_s": max_age_s})
        if canon in self.errors:
            raise self.errors[canon]
        if canon in self.missing:
            raise http.NotFound(canon, 404, "not found")
        if canon not in self.routes:
            raise AssertionError(f"unexpected request: {canon}")
        return copy.deepcopy(self.routes[canon])

    def fetched_utc(self, url):
        if not self.cached:
            return None
        return self.fetched.get(http.canonical_url(url), FETCHED)


def odds_url(bout):
    return espn_urls.competition_odds(bout["event_id"], bout["bout_id"])


# Expected rows of the four DraftKings bouts, typed from the saved responses. Prices are
# (open, close, current); the upcoming bout has no close. Side a is the competitor with order 1.
M = ("ko_tko_dq", "submission", "decision")
EXPECTED = {
    # Raul Rosas Jr. (a, home, favourite) beat Raoni Barcelos (b, away): UFC Fight Night, 2026-09-26, main event
    "401911630": dict(
        a="5088844", b="3075570", status="final", details="R. Rosas Jr. -142", total=3.5,
        a_ml=(-205, -142, -142), b_ml=(170, 120, 120), over=(-180, -175, -175), under=(140, 135, 135),
        a_methods=dict(zip(M, [(550, 700, 700), (300, 350, 350), (190, 200, 200)])),
        b_methods=dict(zip(M, [(500, 450, 450), (1400, 1100, 1100), (300, 275, 275)])),
        spread=dict(spread=-5.5,
                    home=dict(spreadOdds=120.0, open=("-5.5", "+100"), close=("-5.5", "+120"), current=("-5.5", "+120")),
                    away=dict(spreadOdds=-160.0, open=("+5.5", "-135"), close=("+5.5", "-160"), current=("+5.5", "-160")))),
    # Montel Jackson (a, home, favourite) beat Ricky Simon (b, away)
    "401914466": dict(
        a="4339130", b="3922491", status="final", details="M. Jackson -230", total=2.5,
        a_ml=(-180, -230, -230), b_ml=(150, 190, 190), over=(-188, -220, -220), under=(145, 170, 170),
        a_methods=dict(zip(M, [(250, 240, 240), (900, 1100, 1100), (155, 140, 140)])),
        b_methods=dict(zip(M, [(900, 1100, 1100), (1700, 2000, 2000), (250, 275, 275)])),
        spread=dict(spread=-3.5,
                    home=dict(spreadOdds=-115.0, open=("-3.5", "-105"), close=("-3.5", "-115"), current=("-3.5", "-115")),
                    away=dict(spreadOdds=-115.0, open=("+3.5", "-130"), close=("+3.5", "-115"), current=("+3.5", "-115")))),
    # Luis Hernandez (a, home, favourite) beat Sedriques Dumas (b, away)
    "401924683": dict(
        a="5369427", b="5060467", status="final", details="L. Hernandez -230", total=1.5,
        a_ml=(-238, -230, -230), b_ml=(195, 190, 190), over=(175, 190, 190), under=(-230, -250, -250),
        a_methods=dict(zip(M, [(215, 215, 215), (150, 150, 150), (1000, 1000, 1000)])),
        b_methods=dict(zip(M, [(300, 300, 300), (1200, 1200, 1200), (1100, 1100, 1100)])),
        spread=dict(spread=-5.5,
                    home=dict(spreadOdds=-210.0, open=("-5.5", "-210"), close=("-5.5", "-210"), current=("-5.5", "-210")),
                    away=dict(spreadOdds=155.0, open=("+5.5", "+155"), close=("+5.5", "+155"), current=("+5.5", "+155")))),
    # UFC 332, tonight (2026-10-03): Marvin Vettori (a, home, UNDERDOG) vs Ismail Naurdiev (b, away, favourite)
    "401912275": dict(
        a="4001851", b="4412813", status="scheduled", details="I. Naurdiev -135", total=2.5,
        a_ml=(105, None, 114), b_ml=(-125, None, -135), over=(-210, None, -245), under=(160, None, 185),
        a_methods=dict(zip(M, [(1000, None, 1200), (850, None, 1000), (200, None, 180)])),
        b_methods=dict(zip(M, [(250, None, 275), (2000, None, 2000), (185, None, 175)])),
        spread=dict(spread=3.5,
                    home=dict(spreadOdds=-165.0, open=("+3.5", "-160"), current=("+3.5", "-165")),
                    away=dict(spreadOdds=125.0, open=("-3.5", "+120"), current=("-3.5", "+125")))),
}


def phases(row, prefix):
    """(open, close, current) of a row's `<prefix>_open|close|current` fields."""
    return tuple(row[f"{prefix}_{p}"] for p in ("open", "close", "current"))


class DraftKingsFieldByField(unittest.TestCase):
    def check(self, comp_id):
        want = EXPECTED[comp_id]
        odds_name, scoreboard = next((o, s) for o, s, c, _ in ODDS if c == comp_id)
        rows = parse(odds_name, scoreboard, comp_id)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["bout_id"], row["event_id"]), (comp_id, bout_of(scoreboard, comp_id)["event_id"]))
        self.assertEqual((row["provider_id"], row["provider"]), ("100", "DraftKings"))
        self.assertEqual(row["orientation"], "verified")
        self.assertEqual(row["a_side"], "home")
        self.assertEqual(phases(row, "a_ml"), want["a_ml"])
        self.assertEqual(phases(row, "b_ml"), want["b_ml"])
        self.assertEqual(row["rounds_total"], want["total"])
        self.assertEqual(phases(row, "rounds_total"), (want["total"], want["total"] if want["status"] == "final" else None, want["total"]))
        self.assertEqual(phases(row, "over"), want["over"])
        self.assertEqual(phases(row, "under"), want["under"])
        self.assertEqual(phases(row, "draw"), (None, None, None))
        for side, key in (("a", "a_methods"), ("b", "b_methods")):
            self.assertEqual(set(row["method_odds"][side]), set(M))
            for method, prices in want[key].items():
                with self.subTest(side=side, method=method):
                    got = row["method_odds"][side][method]
                    self.assertEqual((got["open"], got["close"], got["current"]), prices)
        self.assertEqual(row["is_closing"], want["status"] == "final")
        self.assertFalse(row["in_play"])
        self.assertEqual(row["details"], want["details"])
        self.assertEqual(row["props_url"], f"https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/"
                                           f"{row['event_id']}/competitions/{comp_id}/odds/100/propBets")
        self.assertEqual((row["source_url"], row["fetched_utc"]), (SRC, FETCHED))
        # the spread is kept as ESPN gave it: item-level number, then each side's own blocks
        spread = want["spread"]
        raw = row["spread_raw"]
        self.assertEqual(raw["spread"], spread["spread"])
        for side in ("home", "away"):
            self.assertEqual(raw[side]["spreadOdds"], spread[side]["spreadOdds"])
            for phase in ("open", "close", "current"):
                if phase in spread[side]:
                    self.assertEqual((raw[side][phase]["pointSpread"], raw[side][phase]["spread"]), spread[side][phase])
                else:
                    self.assertNotIn(phase, raw[side])
        # ESPN's raw sides are always kept, and a/b are the same numbers re-labelled
        home, away = row["sides_raw"]["home"], row["sides_raw"]["away"]
        self.assertEqual((home["athlete_id"], away["athlete_id"]), (want["a"], want["b"]))
        self.assertEqual((home["ml_open"], home["ml_close"], home["ml_current"]), want["a_ml"])
        self.assertEqual((away["ml_open"], away["ml_close"], away["ml_current"]), want["b_ml"])
        self.assertEqual(home["method_odds"], row["method_odds"]["a"])
        self.assertEqual(away["method_odds"], row["method_odds"]["b"])

    def test_rosas_vs_barcelos_a_completed_main_event(self):
        self.check("401911630")

    def test_jackson_vs_simon_a_completed_bout(self):
        self.check("401914466")

    def test_hernandez_vs_dumas_a_completed_bout(self):
        self.check("401924683")

    def test_vettori_vs_naurdiev_the_upcoming_bout_has_no_close(self):
        self.check("401912275")

    def test_open_close_and_current_are_three_different_things(self):
        row = parse(*[x for x in ODDS if x[2] == "401911630"][0][:3])[0]
        self.assertEqual((row["a_ml_open"], row["a_ml_close"], row["a_ml_current"]), (-205, -142, -142))
        self.assertNotEqual(row["a_ml_open"], row["a_ml_close"])
        self.assertEqual(row["a_ml_close"], row["a_ml_current"])      # a final bout: current is the close

    def test_the_favourite_is_not_always_home_and_the_prices_follow_the_fighter(self):
        # UFC 332: the home side is the underdog; fighter a (order 1) is that underdog.
        row = parse(*[x for x in ODDS if x[2] == "401912275"][0][:3])[0]
        self.assertGreater(row["a_ml_current"], 0)
        self.assertLess(row["b_ml_current"], 0)
        self.assertTrue(row["sides_raw"]["away"]["favorite"])
        self.assertFalse(row["sides_raw"]["home"]["favorite"])


class IsClosing(unittest.TestCase):
    def test_completed_bout_versus_the_upcoming_one(self):
        completed = parse("odds_401924683.json", "scoreboard_2026-09-26.json", "401924683")[0]
        upcoming = parse("odds_401912275_upcoming.json", "scoreboard_2026-10-03.json", "401912275")[0]
        self.assertTrue(completed["is_closing"])
        self.assertFalse(upcoming["is_closing"])
        self.assertEqual(completed["a_ml_close"], completed["a_ml_current"])
        self.assertIsNone(upcoming["a_ml_close"])
        self.assertIsNone(upcoming["rounds_total_close"])

    def test_it_is_the_state_of_the_bout_when_fetched_that_decides(self):
        page = load("odds_401924683.json")
        as_scheduled = parse(None, "scoreboard_2026-09-26.json", "401924683", status="scheduled", page=page)[0]
        as_live = parse(None, "scoreboard_2026-09-26.json", "401924683", status="in_progress", page=page)[0]
        self.assertFalse(as_scheduled["is_closing"] or as_live["is_closing"])

    def test_an_in_play_feed_is_never_a_closing_line(self):
        rows = by_provider(parse(*[x for x in ODDS if x[2] == "401632019"][0][:3]))
        self.assertTrue(rows["59"]["in_play"])
        self.assertFalse(rows["59"]["is_closing"])
        self.assertTrue(rows["40"]["is_closing"])


class OrientationFromTheAthleteRefs(unittest.TestCase):
    def test_every_row_of_every_fixture_is_verified_against_the_competitor_order(self):
        total = 0
        for odds_name, scoreboard, comp_id, expected_rows in ODDS:
            bout = bout_of(scoreboard, comp_id)
            page = load(odds_name)
            rows = parse(odds_name, scoreboard, comp_id)
            self.assertEqual(len(rows), expected_rows, odds_name)
            for item, row in zip(page["items"], rows):
                total += 1
                home, away = athlete_id(item["homeAthleteOdds"]["athlete"]), athlete_id(item["awayAthleteOdds"]["athlete"])
                self.assertEqual({home, away}, {bout["fighter_a_id"], bout["fighter_b_id"]})
                with self.subTest(odds_name, provider=row["provider"]):
                    self.assertEqual(row["orientation"], "verified")
                    self.assertEqual(row["a_side"], "home" if home == bout["fighter_a_id"] else "away")
                    self.assertEqual(row["orientation_basis"], "athlete_ref")
        self.assertEqual(total, 38)

    def test_home_was_order_one_in_every_fixture_but_nothing_relies_on_it(self):
        rows = [r for odds_name, sb, comp, _ in ODDS for r in parse(odds_name, sb, comp)]
        self.assertEqual(len(rows), 38)
        self.assertEqual({r["a_side"] for r in rows}, {"home"})
        # including two bouts where home was the underdog (so not "home = favourite"):
        for comp in ("401912275", "401499752"):
            for row in [r for r in rows if r["bout_id"] == comp and r["sides_raw"]["home"]["favorite"] is not None]:
                self.assertFalse(row["sides_raw"]["home"]["favorite"], (comp, row["provider"]))
        # and the 2022 main event was a draw, so it was not "home = winner" either
        self.assertIsNone(bout_of("w3_scoreboard_2022-12-10.json", "401499752")["winner_id"])

    def test_swapping_which_fighter_is_a_swaps_the_answer(self):
        for odds_name, scoreboard, comp_id, _ in ODDS:
            bout = bout_of(scoreboard, comp_id)
            flipped = dict(bout, fighter_a_id=bout["fighter_b_id"], fighter_b_id=bout["fighter_a_id"])
            same = parse(odds_name, scoreboard, comp_id, bout=bout)
            swapped = parse(odds_name, scoreboard, comp_id, bout=flipped)
            for one, two in zip(same, swapped):
                with self.subTest(odds_name, provider=one["provider"]):
                    self.assertEqual((one["a_side"], two["a_side"]), ("home", "away"))
                    for phase in ("open", "close", "current"):
                        self.assertEqual(one[f"a_ml_{phase}"], two[f"b_ml_{phase}"])
                        self.assertEqual(one[f"b_ml_{phase}"], two[f"a_ml_{phase}"])
                    if one["method_odds"]:
                        self.assertEqual(one["method_odds"]["a"], two["method_odds"]["b"])
                        self.assertEqual(one["method_odds"]["b"], two["method_odds"]["a"])

    def test_swapping_what_espn_calls_home_and_away_does_not_change_a_and_b(self):
        for odds_name, scoreboard, comp_id, _ in ODDS:
            page = load(odds_name)
            swapped = copy.deepcopy(page)
            for item in swapped["items"]:
                item["homeAthleteOdds"], item["awayAthleteOdds"] = item["awayAthleteOdds"], item["homeAthleteOdds"]
            for one, two in zip(parse(odds_name, scoreboard, comp_id, page=page),
                                parse(odds_name, scoreboard, comp_id, page=swapped)):
                with self.subTest(odds_name, provider=one["provider"]):
                    self.assertEqual((one["a_side"], two["a_side"]), ("home", "away"))
                    for phase in ("open", "close", "current"):
                        self.assertEqual(one[f"a_ml_{phase}"], two[f"a_ml_{phase}"])
                        self.assertEqual(one[f"b_ml_{phase}"], two[f"b_ml_{phase}"])
                    self.assertEqual(one["method_odds"], two["method_odds"])
                    self.assertEqual(one["sides_raw"]["home"], two["sides_raw"]["away"])

    def test_the_favourite_won_wherever_a_favourite_and_a_winner_exist(self):
        """Three fields of ESPN's own data agree: the flagged favourite, its athlete ref, the result.

        28 rows of 7 bouts, and the favourite won every time, so this cannot separate two
        orientation rules by itself (there is no upset in the samples); it shows the refs, the
        flags and the results are consistent with each other.
        """
        checked = 0
        for odds_name, scoreboard, comp_id, _ in ODDS:
            winner = bout_of(scoreboard, comp_id)["winner_id"]
            for item in load(odds_name)["items"]:
                flagged = [athlete_id(item[s]["athlete"]) for s in ("homeAthleteOdds", "awayAthleteOdds")
                           if item[s].get("favorite") is True]
                if winner and len(flagged) == 1:
                    checked += 1
                    self.assertEqual(flagged[0], winner, (odds_name, item["provider"]["name"]))
        self.assertEqual(checked, 28)

    def test_one_athlete_ref_is_enough(self):
        page = load("odds_401924683.json")
        del page["items"][0]["awayAthleteOdds"]["athlete"]
        row = parse(None, "scoreboard_2026-09-26.json", "401924683", page=page)[0]
        self.assertEqual((row["orientation"], row["orientation_basis"], row["a_side"]), ("verified", "athlete_ref", "home"))
        page = load("odds_401924683.json")
        del page["items"][0]["homeAthleteOdds"]["athlete"]
        row = parse(None, "scoreboard_2026-09-26.json", "401924683", page=page)[0]
        self.assertEqual((row["orientation"], row["a_side"], row["a_ml_current"]), ("verified", "home", -230))


class OrientationFromTheName(unittest.TestCase):
    def test_the_favourites_name_agrees_with_the_refs_on_every_row_that_has_details(self):
        agreed = 0
        for odds_name, scoreboard, comp_id, _ in ODDS:
            for row in parse(odds_name, scoreboard, comp_id, fighters=True):
                with self.subTest(odds_name, provider=row["provider"]):
                    self.assertEqual(row["orientation"], "verified")
                    if row["details"]:
                        agreed += 1
                        self.assertEqual(row["orientation_basis"], "athlete_ref+details_name")
                    else:
                        self.assertEqual(row["orientation_basis"], "athlete_ref")
        self.assertEqual(agreed, 37)         # the 38th row (Sugarhouse, 2024) has no `details`

    def test_without_athlete_refs_the_name_settles_it_with_the_same_answer(self):
        verified = unknown = 0
        for odds_name, scoreboard, comp_id, _ in ODDS:
            page = load(odds_name)
            with_refs = parse(odds_name, scoreboard, comp_id, page=page)
            by_name = parse(odds_name, scoreboard, comp_id, page=without_athlete_refs(page), fighters=True)
            for one, two in zip(with_refs, by_name):
                with self.subTest(odds_name, provider=one["provider"]):
                    if one["details"]:
                        verified += 1
                        self.assertEqual((two["orientation"], two["orientation_basis"]), ("verified", "details_name"))
                        self.assertEqual(two["a_side"], one["a_side"])
                        self.assertEqual(phases(two, "a_ml"), phases(one, "a_ml"))
                        self.assertEqual(phases(two, "b_ml"), phases(one, "b_ml"))
                    else:
                        unknown += 1
                        self.assertEqual(two["orientation"], "unknown")
        self.assertEqual((verified, unknown), (37, 1))

    def test_a_row_with_no_details_and_no_refs_stays_unknown(self):
        rows = by_provider(parse(None, "w3_scoreboard_2024-04-13.json", "401632019",
                                 page=without_athlete_refs(load("w3_odds_401632019_2024.json")), fighters=True))
        sugarhouse = rows["41"]
        self.assertIsNone(sugarhouse["details"])
        self.assertEqual((sugarhouse["orientation"], sugarhouse["orientation_basis"]), ("unknown", "undetermined"))

    def test_a_typographic_minus_and_even_money_in_details_are_read(self):
        page = without_athlete_refs(load("odds_401924683.json"))
        page["items"][0]["details"] = "L. Hernandez " + chr(0x2212) + "230"
        row = parse(None, "scoreboard_2026-09-26.json", "401924683", page=page, fighters=True)[0]
        self.assertEqual((row["orientation"], row["a_side"]), ("verified", "home"))
        # an even-money favourite: both sides +100/-100 would be ambiguous, one side at +100 is not
        page = without_athlete_refs(load("odds_401924683.json"))
        item = page["items"][0]
        item["details"] = "L. Hernandez EVEN"
        item["homeAthleteOdds"]["current"]["moneyLine"] = {"american": "+100"}
        item["homeAthleteOdds"]["moneyLine"] = 100
        row = parse(None, "scoreboard_2026-09-26.json", "401924683", page=page, fighters=True)[0]
        self.assertEqual((row["orientation"], row["a_side"], row["a_ml_current"]), ("verified", "home", 100))

    def test_the_short_name_matcher(self):
        match = odds._short_matches
        self.assertTrue(match(["r", "rosas", "jr"], ["raul", "rosas", "jr"]))
        self.assertTrue(match(["j", "yoo"], ["joo", "sang", "yoo"]))            # a multi-word first name
        self.assertTrue(match(["d", "du", "plessis"], ["dricus", "du", "plessis"]))
        self.assertTrue(match(["rongzhu"], ["rongzhu"]))                       # a mononym, in full
        self.assertTrue(match(["ismail", "naurdiev"], ["ismail", "naurdiev"]))
        self.assertFalse(match(["r", "rosas", "jr"], ["raul", "rosas"]))        # the suffix matters
        self.assertFalse(match(["x", "rosas", "jr"], ["raul", "rosas", "jr"]))  # wrong initial
        self.assertFalse(match(["r", "rosas"], ["rosas"]))                     # nothing before the surname
        self.assertFalse(match([], ["raul"]))
        self.assertFalse(match(["r", "rosas"], []))


class OrientationThatCannotBeSettled(unittest.TestCase):
    ODDS_NAME, SCOREBOARD, COMP = "odds_401924683.json", "scoreboard_2026-09-26.json", "401924683"

    def rows(self, page=None, **kw):
        return parse(self.ODDS_NAME, self.SCOREBOARD, self.COMP, page=page, **kw)

    def assert_unknown(self, row, basis=None):
        self.assertEqual(row["orientation"], "unknown")
        self.assertIsNone(row["a_side"])
        for field in ("a_ml_open", "a_ml_close", "a_ml_current", "b_ml_open", "b_ml_close", "b_ml_current", "method_odds"):
            self.assertIsNone(row[field], field)
        if basis:
            self.assertEqual(row["orientation_basis"], basis)

    def test_no_refs_and_no_fighters_gives_unknown_but_keeps_the_raw_prices(self):
        row = self.rows(without_athlete_refs(load(self.ODDS_NAME)))[0]
        self.assert_unknown(row, "undetermined")
        home, away = row["sides_raw"]["home"], row["sides_raw"]["away"]
        self.assertEqual((home["ml_open"], home["ml_close"], home["ml_current"]), (-238, -230, -230))
        self.assertEqual((away["ml_open"], away["ml_close"], away["ml_current"]), (195, 190, 190))
        self.assertEqual(home["method_odds"]["ko_tko_dq"], {"open": 215, "close": 215, "current": 215})
        self.assertIsNone(home["athlete_id"])
        # the rest of the row is still read
        self.assertEqual((row["rounds_total"], row["over_current"], row["under_current"]), (1.5, 190, -250))
        self.assertEqual(row["spread_raw"]["spread"], -5.5)

    def test_an_athlete_who_is_not_in_the_bout_is_unknown(self):
        bout = dict(bout_of(self.SCOREBOARD, self.COMP), fighter_a_id="1", fighter_b_id="2")
        self.assert_unknown(self.rows(bout=bout)[0], "athlete_ref_not_in_bout")
        one_wrong = dict(bout_of(self.SCOREBOARD, self.COMP), fighter_b_id="2")
        self.assert_unknown(self.rows(bout=one_wrong)[0], "athlete_ref_not_in_bout")

    def test_the_same_athlete_on_both_sides_is_unknown(self):
        page = load(self.ODDS_NAME)
        page["items"][0]["awayAthleteOdds"]["athlete"] = page["items"][0]["homeAthleteOdds"]["athlete"]
        self.assert_unknown(self.rows(page)[0], "athlete_ref_same_on_both_sides")

    def test_refs_and_the_name_in_details_that_disagree_are_unknown(self):
        names = fighters_of(self.SCOREBOARD, self.COMP)
        a, b = bout_of(self.SCOREBOARD, self.COMP)["fighter_a_id"], bout_of(self.SCOREBOARD, self.COMP)["fighter_b_id"]
        swapped = {a: names[b], b: names[a]}                       # as if the fighter store had them the other way round
        row = odds.parse_odds(load(self.ODDS_NAME), bout=bout_of(self.SCOREBOARD, self.COMP), fetched_utc=FETCHED,
                              source_url=SRC, fighters=swapped)[0]
        self.assert_unknown(row, "athlete_ref_vs_details_conflict")

    def test_an_ambiguous_name_settles_nothing_by_itself_and_does_not_veto_the_refs(self):
        a, b = "5369427", "5060467"
        both_hernandez = {a: {"name": "Luis Hernandez"}, b: {"name": "Lena Hernandez"}}      # "L. Hernandez" fits both
        bout = bout_of(self.SCOREBOARD, self.COMP)
        with_refs = odds.parse_odds(load(self.ODDS_NAME), bout=bout, fetched_utc=FETCHED, source_url=SRC, fighters=both_hernandez)[0]
        self.assertEqual((with_refs["orientation"], with_refs["orientation_basis"]), ("verified", "athlete_ref"))
        no_refs = odds.parse_odds(without_athlete_refs(load(self.ODDS_NAME)), bout=bout, fetched_utc=FETCHED,
                                  source_url=SRC, fighters=both_hernandez)[0]
        self.assert_unknown(no_refs, "undetermined")

    def test_a_favourite_flag_that_contradicts_the_price_in_details_is_not_trusted(self):
        page = without_athlete_refs(load(self.ODDS_NAME))
        item = page["items"][0]
        item["homeAthleteOdds"]["favorite"], item["awayAthleteOdds"]["favorite"] = False, True
        self.assert_unknown(self.rows(page, fighters=True)[0], "undetermined")

    def test_a_price_in_details_that_matches_neither_side_is_not_trusted(self):
        page = without_athlete_refs(load(self.ODDS_NAME))
        page["items"][0]["details"] = "L. Hernandez -999"
        self.assert_unknown(self.rows(page, fighters=True)[0], "undetermined")

    def test_fighters_that_are_not_in_the_store_settle_nothing(self):
        row = self.rows(without_athlete_refs(load(self.ODDS_NAME)), fighters=False)[0]
        self.assert_unknown(row)
        partial = odds.parse_odds(without_athlete_refs(load(self.ODDS_NAME)), bout=bout_of(self.SCOREBOARD, self.COMP),
                                  fetched_utc=FETCHED, source_url=SRC, fighters={"5369427": {"name": "Luis Hernandez"}})[0]
        self.assertEqual(partial["orientation"], "verified")       # one of the two is enough to name the favourite
        self.assertEqual(partial["a_side"], "home")

    def test_names_are_matched_through_aliases_and_plain_strings(self):
        bout = bout_of(self.SCOREBOARD, self.COMP)
        fighters = {"5369427": {"name": "Someone Else", "aliases": ["luis hernandez"]}, "5060467": "Sedriques Dumas"}
        row = odds.parse_odds(without_athlete_refs(load(self.ODDS_NAME)), bout=bout, fetched_utc=FETCHED,
                              source_url=SRC, fighters=fighters)[0]
        self.assertEqual((row["orientation"], row["a_side"]), ("verified", "home"))

    def test_a_bout_without_fighter_ids_is_unknown(self):
        bout = {"bout_id": self.COMP, "event_id": "600061266", "status": "final"}
        self.assert_unknown(self.rows(bout=bout)[0])


class OtherEras(unittest.TestCase):
    def test_2022_a_draw_with_eight_providers_that_each_send_only_the_current_line(self):
        rows = by_provider(parse(*[x for x in ODDS if x[2] == "401499752"][0][:3]))
        self.assertEqual(set(rows), {"50", "52", "45", "1004", "55", "48", "53", "36"})
        for row in rows.values():
            self.assertEqual((row["a_ml_open"], row["a_ml_close"], row["b_ml_open"], row["b_ml_close"]), (None,) * 4)
            self.assertIsNone(row["spread_raw"])
            self.assertIsNone(row["method_odds"])
            self.assertIsNone(row["props_url"])
            self.assertEqual(row["orientation"], "verified")
        # fighter a (order 1) is Jan Blachowicz, the home underdog; b is Magomed Ankalaev
        self.assertEqual((rows["50"]["provider"], rows["50"]["a_ml_current"], rows["50"]["b_ml_current"]), ("BetfairSportsbook", 250, -400))
        self.assertEqual(rows["50"]["details"], "M. Ankalaev -400")
        self.assertIsNone(rows["50"]["rounds_total"])
        consensus, pointsbet = rows["1004"], rows["48"]
        self.assertEqual((consensus["a_ml_current"], consensus["b_ml_current"]), (277, -347))
        self.assertEqual((consensus["rounds_total"], consensus["over_current"], consensus["under_current"]), (3.5, -103, -127))
        self.assertEqual((pointsbet["a_ml_current"], pointsbet["b_ml_current"]), (260, -333))
        self.assertEqual((pointsbet["rounds_total"], pointsbet["over_current"], pointsbet["under_current"]), (2.5, -149, 115))
        self.assertEqual(rows["52"]["provider"], "Caesars Sportsbook (CO)")
        self.assertEqual(rows["45"]["provider"], "Caesars Sportsbook (NJ)")

    def test_2019_six_providers_and_betradars_draw_price(self):
        rows = by_provider(parse(*[x for x in ODDS if x[2] == "266329"][0][:3]))
        self.assertEqual(set(rows), {"1001", "37", "38", "1004", "36", "32"})
        # a is Khabib Nurmagomedov (home, order 1), b is Dustin Poirier
        self.assertEqual((rows["1001"]["provider"], rows["1001"]["a_ml_current"], rows["1001"]["b_ml_current"]), ("Bet365", -460, 350))
        self.assertEqual((rows["1001"]["rounds_total"], rows["1001"]["over_current"], rows["1001"]["under_current"]), (3.5, -125, 100))
        self.assertEqual((rows["37"]["a_ml_current"], rows["37"]["b_ml_current"], rows["37"]["draw_current"]), (-490, 340, 8000))
        self.assertEqual((rows["37"]["over_current"], rows["37"]["under_current"]), (-140, 110))
        self.assertEqual((rows["1004"]["a_ml_current"], rows["1004"]["b_ml_current"]), (-530, 410))
        self.assertEqual((rows["38"]["a_ml_current"], rows["38"]["b_ml_current"]), (-550, 380))
        self.assertEqual((rows["36"]["a_ml_current"], rows["36"]["b_ml_current"]), (-440, 340))
        self.assertEqual((rows["32"]["a_ml_current"], rows["32"]["b_ml_current"]), (-500, 380))
        self.assertTrue(all(r["draw_current"] is None for k, r in rows.items() if k != "37"))

    def test_2021_six_providers(self):
        rows = by_provider(parse(*[x for x in ODDS if x[2] == "401320793"][0][:3]))
        self.assertEqual(set(rows), {"38", "45", "1004", "48", "51", "36"})
        # a is Dustin Poirier (home, order 1), b is Conor McGregor
        self.assertEqual((rows["38"]["a_ml_current"], rows["38"]["b_ml_current"]), (-125, 105))
        self.assertEqual((rows["45"]["a_ml_current"], rows["45"]["b_ml_current"]), (-130, 110))
        self.assertEqual((rows["51"]["a_ml_current"], rows["51"]["b_ml_current"]), (-128, 100))     # "+100" is a price
        self.assertEqual((rows["1004"]["rounds_total"], rows["1004"]["over_current"], rows["1004"]["under_current"]), (2.5, 108, -144))
        self.assertEqual((rows["48"]["over_current"], rows["48"]["under_current"]), (105, -135))

    def test_2024_twelve_providers_one_live_one_without_moneylines(self):
        rows = by_provider(parse(*[x for x in ODDS if x[2] == "401632019"][0][:3]))
        self.assertEqual(set(rows), {"1001", "50", "52", "45", "57", "1004", "40", "58", "59", "41", "53", "36"})
        self.assertEqual([r["provider_id"] for r in rows.values() if r["in_play"]], ["59"])
        live = rows["59"]
        self.assertEqual(live["provider"], "ESPN Bet - Live Odds")
        self.assertEqual((live["a_ml_current"], live["b_ml_current"]), (-3000, 700))      # King Green, who won, at -3000
        self.assertEqual(rows["40"]["a_ml_current"], -185)                                # against -175 to -210 pre-fight
        self.assertEqual((rows["40"]["a_ml_open"], rows["40"]["b_ml_open"], rows["40"]["b_ml_current"]), (-185, 154, 154))
        self.assertEqual((rows["40"]["over_open"], rows["40"]["under_open"], rows["40"]["over_current"]), (-130, 100, -130))
        sugarhouse = rows["41"]
        self.assertEqual(sugarhouse["orientation"], "verified")
        self.assertTrue(all(sugarhouse[f"{s}_ml_{p}"] is None for s in "ab" for p in ("open", "close", "current")))
        self.assertEqual((sugarhouse["rounds_total"], sugarhouse["over_open"], sugarhouse["under_open"]), (2.5, -128, -103))
        espn = rows["58"]
        self.assertEqual((espn["rounds_total"], espn["over_current"], espn["under_current"]), (2.5, None, None))
        self.assertEqual((espn["a_ml_open"], espn["a_ml_current"], espn["b_ml_current"]), (-200, -200, 170))

    def test_2025_the_line_moved_between_open_and_close_and_methods_come_in_some_blocks_only(self):
        rows = by_provider(parse(*[x for x in ODDS if x[2] == "401799532"][0][:3]))
        self.assertEqual(set(rows), {"58", "59"})
        espn, live = rows["58"], rows["59"]
        self.assertEqual(phases(espn, "a_ml"), (-800, -450, -450))
        self.assertEqual(phases(espn, "b_ml"), (500, 325, 325))
        # the total went from 3.0 to 2.5: the open prices belong to the 3.0 line, not to `rounds_total`
        self.assertEqual(phases(espn, "rounds_total"), (3.0, 2.5, 2.5))
        self.assertEqual(espn["rounds_total"], 2.5)
        self.assertEqual(phases(espn, "over"), (200, 160, 160))
        self.assertEqual(phases(espn, "under"), (-275, -225, -225))
        self.assertEqual(espn["method_odds"]["a"]["ko_tko_dq"], {"open": None, "close": -135, "current": -135})
        self.assertEqual(espn["method_odds"]["b"]["decision"], {"open": None, "close": 1600, "current": 1600})
        self.assertEqual(live["method_odds"]["a"]["ko_tko_dq"], {"open": -135, "close": None, "current": -125})
        self.assertEqual(phases(live, "a_ml"), (-800, None, -550))
        self.assertTrue(live["in_play"] and not live["is_closing"])
        self.assertTrue(espn["is_closing"] and not espn["in_play"])

    def test_empty_odds_lists_give_no_rows_for_the_five_old_bouts(self):
        for odds_name, scoreboard, comp_id in EMPTY:
            with self.subTest(odds_name):
                page = load(odds_name)
                self.assertEqual((page["count"], page["items"]), (0, []))
                self.assertEqual(parse(odds_name, scoreboard, comp_id), [])
        self.assertEqual(odds.parse_odds(None, bout=bout_of(*EMPTY[0][1:]), fetched_utc=FETCHED, source_url=SRC), [])
        self.assertEqual(odds.parse_odds({}, bout=bout_of(*EMPTY[0][1:]), fetched_utc=FETCHED, source_url=SRC), [])

    def test_a_bare_list_of_items_is_accepted_and_a_repeated_provider_keeps_the_first(self):
        items = load("odds_401924683.json")["items"]
        first = copy.deepcopy(items[0])
        second = copy.deepcopy(items[0])
        second["awayAthleteOdds"]["moneyLine"] = 999
        second["awayAthleteOdds"]["current"]["moneyLine"] = {"american": "+999"}
        rows = odds.parse_odds([first, second], bout=bout_of("scoreboard_2026-09-26.json", "401924683"),
                               fetched_utc=FETCHED, source_url=SRC)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["b_ml_current"], 190)

    def test_the_provider_id_falls_back_to_the_items_own_ref(self):
        page = load("odds_401924683.json")
        del page["items"][0]["provider"]["id"]
        self.assertEqual(parse(None, "scoreboard_2026-09-26.json", "401924683", page=page)[0]["provider_id"], "100")
        page["items"][0]["$ref"] = "x"
        self.assertEqual(parse(None, "scoreboard_2026-09-26.json", "401924683", page=page), [])


class ReadingThePrices(unittest.TestCase):
    def test_american_price_forms(self):
        read = odds._american
        self.assertEqual([read("+195"), read("-238"), read(190.0), read(-230), read("  +100 ")], [195, -238, 190, -230, 100])
        self.assertEqual([read("EVEN"), read("even"), read(chr(0x2212) + "150")], [100, 100, -150])
        for bad in (None, "", "abc", "+50", -99, 0, "0", True, float("nan"), 150.5, "OFF"):
            self.assertIsNone(read(bad), bad)

    def test_price_nodes_and_lines(self):
        self.assertEqual(odds._price({"american": "+195", "decimal": 2.95}), 195)
        self.assertEqual(odds._price({"alternateDisplayValue": "-110"}), -110)
        self.assertIsNone(odds._price({}))
        self.assertIsNone(odds._price(None))
        self.assertEqual(odds._line({"american": "2.5", "alternateDisplayValue": "2.5"}), 2.5)
        self.assertEqual(odds._line({"value": 3.5, "american": "3.5"}), 3.5)
        self.assertEqual(odds._line(1.5), 1.5)
        for bad in (None, {}, "n/a", 0, {"american": "x"}, True):
            self.assertIsNone(odds._line(bad), bad)

    def test_every_american_price_agrees_with_the_decimal_price_espn_sends_beside_it(self):
        checked = 0

        def walk(node, where):
            nonlocal checked
            if isinstance(node, dict):
                if "american" in node and "decimal" in node and where[-1] not in ("total",):
                    american = int(str(node["american"]).replace("+", ""))
                    decimal = 1 + american / 100 if american > 0 else 1 + 100 / -american
                    self.assertAlmostEqual(node["decimal"], decimal, delta=0.011, msg=(where, node))
                    self.assertEqual(odds._price(node), american)
                    checked += 1
                for key, value in node.items():
                    walk(value, where + [key])
            elif isinstance(node, list):
                for value in node:
                    walk(value, where)

        for odds_name, *_ in ODDS:
            walk(load(odds_name), [odds_name])
        self.assertEqual(checked, 232)      # price nodes in the nine bouts, every one agreeing with its decimal

    def test_the_top_level_prices_equal_the_current_block_so_the_fallback_is_safe(self):
        compared = 0
        for odds_name, *_ in ODDS:
            for item in load(odds_name)["items"]:
                current = item.get("current") or {}
                if "overOdds" in item and current.get("over"):
                    compared += 1
                    self.assertEqual(item["overOdds"], float(current["over"]["american"]))
                    self.assertEqual(item["underOdds"], float(current["under"]["american"]))
                if "overUnder" in item and current.get("total"):
                    self.assertEqual(item["overUnder"], float(current["total"]["american"]))
                for side in ("homeAthleteOdds", "awayAthleteOdds"):
                    ml = (item[side].get("current") or {}).get("moneyLine")
                    if ml and "moneyLine" in item[side]:
                        compared += 1
                        self.assertEqual(float(item[side]["moneyLine"]), float(ml["american"]))
        self.assertGreater(compared, 70)

    def test_the_top_level_values_are_used_when_the_current_block_is_missing(self):
        page = load("odds_401924683.json")
        item = page["items"][0]
        del item["current"]
        del item["homeAthleteOdds"]["current"]
        del item["awayAthleteOdds"]["current"]
        row = parse(None, "scoreboard_2026-09-26.json", "401924683", page=page)[0]
        self.assertEqual((row["a_ml_current"], row["b_ml_current"]), (-230, 190))
        self.assertEqual((row["over_current"], row["under_current"], row["rounds_total_current"]), (190, -250, 1.5))
        self.assertEqual(row["rounds_total"], 1.5)

    def test_the_line_and_its_prices_are_kept_per_phase(self):
        page = load("odds_401924683.json")
        page["items"][0]["open"]["total"] = {"alternateDisplayValue": "2.5", "american": "2.5"}
        row = parse(None, "scoreboard_2026-09-26.json", "401924683", page=page)[0]
        self.assertEqual((row["rounds_total_open"], row["rounds_total_close"], row["rounds_total_current"]), (2.5, 1.5, 1.5))
        self.assertEqual(row["rounds_total"], 1.5)
        self.assertEqual(row["over_open"], 175)               # priced at the 2.5 line, not at rounds_total

    def test_every_row_has_the_same_fields_and_integer_prices(self):
        rows = [r for odds_name, sb, comp, _ in ODDS for r in parse(odds_name, sb, comp)]
        keys = set(rows[0])
        contract = {"bout_id", "event_id", "provider_id", "provider", "a_ml_open", "a_ml_close", "a_ml_current",
                    "b_ml_open", "b_ml_close", "b_ml_current", "rounds_total", "over_open", "over_close", "over_current",
                    "under_open", "under_close", "under_current", "method_odds", "spread_raw", "orientation",
                    "is_closing", "source_url", "fetched_utc"}
        self.assertLessEqual(contract, keys)
        for row in rows:
            self.assertEqual(set(row), keys)
            self.assertIn(row["orientation"], ("verified", "unknown"))
            for field in keys:
                if re.match(r"^(a|b)_ml_|^(over|under|draw)_", field):
                    self.assertTrue(row[field] is None or type(row[field]) is int, (field, row[field]))
            json.dumps(row)                                    # JSON-ready

    def test_the_prop_bets_link_is_recorded_not_followed(self):
        rows = [r for odds_name, sb, comp, _ in ODDS for r in parse(odds_name, sb, comp)]
        with_props = [r for r in rows if r["props_url"]]
        # the four DraftKings items of 2026 and the two ESPN BET items of 2025; none before
        self.assertEqual(sorted((r["bout_id"], r["provider_id"]) for r in with_props),
                         [("401799532", "58"), ("401799532", "59"), ("401911630", "100"), ("401912275", "100"),
                          ("401914466", "100"), ("401924683", "100")])
        for row in with_props:
            self.assertEqual(row["props_url"], f"https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/"
                                               f"{row['event_id']}/competitions/{row['bout_id']}/odds/{row['provider_id']}/propBets")
        self.assertEqual(len(rows) - len(with_props), 32)


class FetchBoutOdds(unittest.TestCase):
    def setUp(self):
        self.bout = bout_of("scoreboard_2026-09-26.json", "401924683")          # final, date 2026-09-27T00:00Z
        self.url = odds_url(self.bout)
        self.page = load("odds_401924683.json")

    def test_a_final_bout_uses_the_odds_url_and_the_cache(self):
        fetcher = FixtureFetcher({self.url: self.page}, fetched={self.url: "2026-10-03T01:00:00Z"})
        rows = odds.fetch_bout_odds(fetcher, self.bout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.url, "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/600061266/competitions/401924683/odds")
        self.assertEqual(fetcher.calls, [{"url": self.url, "use_cache": True, "max_age_s": None}])
        self.assertEqual((rows[0]["source_url"], rows[0]["fetched_utc"]), (self.url, "2026-10-03T01:00:00Z"))
        self.assertEqual(rows[0]["a_ml_close"], -230)

    def test_an_upcoming_bout_is_read_with_a_max_age_so_the_prices_refresh(self):
        bout = bout_of("scoreboard_2026-10-03.json", "401912275")
        fetcher = FixtureFetcher({odds_url(bout): load("odds_401912275_upcoming.json")})
        rows = odds.fetch_bout_odds(fetcher, bout)
        self.assertEqual(fetcher.calls, [{"url": odds_url(bout), "use_cache": True, "max_age_s": odds.LIVE_MAX_AGE_S}])
        self.assertEqual((rows[0]["a_ml_current"], rows[0]["is_closing"]), (114, False))
        tuned = FixtureFetcher({odds_url(bout): load("odds_401912275_upcoming.json")})
        odds.fetch_bout_odds(tuned, bout, live_max_age_s=60)
        self.assertEqual(tuned.calls[0]["max_age_s"], 60)
        for status in ("in_progress", "unknown", None):
            fetcher = FixtureFetcher({odds_url(bout): load("odds_401912275_upcoming.json")})
            odds.fetch_bout_odds(fetcher, dict(bout, status=status))
            self.assertEqual(fetcher.calls[0]["max_age_s"], odds.LIVE_MAX_AGE_S, status)

    def test_a_copy_fetched_before_the_bout_could_have_finished_is_read_again(self):
        # date 2026-09-27T00:00Z + 8 h: a copy older than 08:00Z may be a pre-fight one
        for fetched, expect_cache in (("2026-09-26T20:00:00Z", False), ("2026-09-27T07:59:59Z", False),
                                      ("2026-09-27T08:00:00Z", True), ("2026-10-03T01:00:00Z", True)):
            fetcher = FixtureFetcher({self.url: self.page}, fetched={self.url: fetched})
            odds.fetch_bout_odds(fetcher, self.bout)
            with self.subTest(fetched):
                self.assertEqual(fetcher.calls[0]["use_cache"], expect_cache)
                self.assertIsNone(fetcher.calls[0]["max_age_s"])
        tuned = FixtureFetcher({self.url: self.page}, fetched={self.url: "2026-09-27T08:00:00Z"})
        odds.fetch_bout_odds(tuned, self.bout, settle_s=3600)
        self.assertTrue(tuned.calls[0]["use_cache"])
        tuned = FixtureFetcher({self.url: self.page}, fetched={self.url: "2026-09-27T00:30:00Z"})
        odds.fetch_bout_odds(tuned, self.bout, settle_s=3600)
        self.assertFalse(tuned.calls[0]["use_cache"])

    def test_dates_parse_in_espns_form_and_an_impossible_one_is_not_a_date(self):
        parse_utc = odds._parse_utc
        self.assertEqual(parse_utc("2026-09-27T00:00Z"), datetime(2026, 9, 27, tzinfo=timezone.utc))
        self.assertEqual(parse_utc("2026-09-27T02:00:00+02:00"), datetime(2026, 9, 27, tzinfo=timezone.utc))
        self.assertEqual(parse_utc("2026-10-03T18:00:00Z"), datetime(2026, 10, 3, 18, tzinfo=timezone.utc))
        for bad in (None, "", "soon", "2026-13-45T00:00Z", "2026-09-27T25:00Z"):
            self.assertIsNone(parse_utc(bad), bad)
        # an unreadable bout date means "cannot tell when it ended": a normal read, never a crash
        fetcher = FixtureFetcher({self.url: self.page}, fetched={self.url: "2026-09-26T20:00:00Z"})
        odds.fetch_bout_odds(fetcher, dict(self.bout, date_utc="2026-13-45T00:00Z"))
        self.assertTrue(fetcher.calls[0]["use_cache"])

    def test_nothing_cached_or_no_date_means_a_normal_read(self):
        fetcher = FixtureFetcher({self.url: self.page}, cached=False)
        odds.fetch_bout_odds(fetcher, self.bout)
        self.assertTrue(fetcher.calls[0]["use_cache"])
        fetcher = FixtureFetcher({self.url: self.page}, fetched={self.url: "2026-09-26T20:00:00Z"})
        odds.fetch_bout_odds(fetcher, dict(self.bout, date_utc=None))
        self.assertTrue(fetcher.calls[0]["use_cache"])

    def test_an_empty_list_is_a_valid_empty_result(self):
        bout = bout_of("scoreboard_2016-07-09.json", "223077")
        fetcher = FixtureFetcher({odds_url(bout): load("odds_223077_2016.json")})
        self.assertEqual(odds.fetch_bout_odds(fetcher, bout), [])
        self.assertEqual(len(fetcher.calls), 1)

    def test_a_404_gives_no_rows(self):
        fetcher = FixtureFetcher(missing=[self.url])
        self.assertEqual(odds.fetch_bout_odds(fetcher, self.bout), [])

    def test_a_browser_check_and_other_problems_propagate(self):
        for error in (http.SourceBlocked(self.url, 200, "browser check"), http.FetchError(self.url, 500, "failed"),
                      http.RequestCapReached(self.url, None, "cap")):
            with self.subTest(type(error).__name__), self.assertRaises(http.FetchError) as caught:
                odds.fetch_bout_odds(FixtureFetcher(errors={self.url: error}), self.bout)
            self.assertIs(caught.exception, error)

    def test_more_than_one_page_is_followed_up_to_the_cap(self):
        bout = bout_of("w3_scoreboard_2022-12-10.json", "401499752")
        full = load("w3_odds_401499752_draw_2022.json")
        pages = {}
        for number, chunk in enumerate((full["items"][:3], full["items"][3:6], full["items"][6:]), start=1):
            pages[number] = dict(full, items=chunk, pageIndex=number, pageCount=3)
        url = odds_url(bout)
        routes = {url: pages[1], url + "?page=2": pages[2], url + "?page=3": pages[3]}
        fetcher = FixtureFetcher(routes)
        rows = odds.fetch_bout_odds(fetcher, bout)
        self.assertEqual([c["url"] for c in fetcher.calls], [url, url + "?page=2", url + "?page=3"])
        self.assertEqual(len(rows), 8)
        capped = FixtureFetcher(routes)
        self.assertEqual(len(odds.fetch_bout_odds(capped, bout, max_pages=2)), 6)
        self.assertEqual(len(capped.calls), 2)
        missing_second = FixtureFetcher({url: pages[1]}, missing=[url + "?page=2"])
        self.assertEqual(len(odds.fetch_bout_odds(missing_second, bout)), 3)

    def test_a_garbage_page_count_is_one_page(self):
        page = dict(self.page, pageCount="many")
        fetcher = FixtureFetcher({self.url: page})
        self.assertEqual(len(odds.fetch_bout_odds(fetcher, self.bout)), 1)
        self.assertEqual(len(fetcher.calls), 1)

    def test_the_fighters_are_passed_through_for_the_name_check(self):
        stripped = without_athlete_refs(self.page)
        fetcher = FixtureFetcher({self.url: stripped})
        names = fighters_of("scoreboard_2026-09-26.json", "401924683")
        rows = odds.fetch_bout_odds(fetcher, self.bout, fighters=names)
        self.assertEqual((rows[0]["orientation"], rows[0]["orientation_basis"]), ("verified", "details_name"))
        none = odds.fetch_bout_odds(FixtureFetcher({self.url: stripped}), self.bout)
        self.assertEqual(none[0]["orientation"], "unknown")


class StoredThroughTheUfcStore(unittest.TestCase):
    def test_rows_save_under_bout_and_provider_and_a_refetch_changes_nothing(self):
        from src.datasvc.ufc.store import UfcStore
        bout = bout_of("w3_scoreboard_2024-04-13.json", "401632019")
        url = odds_url(bout)
        with tempfile.TemporaryDirectory() as tmp:
            store = UfcStore(Path(tmp))
            first = odds.fetch_bout_odds(FixtureFetcher({url: load("w3_odds_401632019_2024.json")}), bout)
            self.assertEqual(store.upsert("odds", first), {"added": 12, "updated": 0, "unchanged": 0, "total": 12})
            later = FixtureFetcher({url: load("w3_odds_401632019_2024.json")}, fetched={url: "2026-10-10T00:00:00Z"})
            self.assertEqual(store.upsert("odds", odds.fetch_bout_odds(later, bout)),
                             {"added": 0, "updated": 0, "unchanged": 12, "total": 12})
            by_bout = store.odds_for_bout()
            self.assertEqual(sorted(r["provider_id"] for r in by_bout["401632019"]),
                             sorted(["1001", "50", "52", "45", "57", "1004", "40", "58", "59", "41", "53", "36"]))
            stored = {r["provider_id"]: r for r in store.load("odds")}
            self.assertEqual(stored["59"]["in_play"], True)
            self.assertIsNone(stored["41"]["a_ml_current"])
            self.assertEqual(stored["40"]["method_odds"], None)
            self.assertEqual(stored["40"]["a_ml_open"], -185)
            # "unchanged" means the content is the same; the newer record still replaces the older whole
            self.assertEqual(store.newest("odds"), "2026-10-10T00:00:00Z")

    def test_a_line_that_moved_is_an_update_not_a_duplicate(self):
        from src.datasvc.ufc.store import UfcStore
        bout = bout_of("scoreboard_2026-10-03.json", "401912275")
        page = load("odds_401912275_upcoming.json")
        with tempfile.TemporaryDirectory() as tmp:
            store = UfcStore(Path(tmp))
            store.upsert("odds", odds.parse_odds(page, bout=bout, fetched_utc="2026-10-03T12:00:00Z", source_url=SRC))
            moved = copy.deepcopy(page)
            moved["items"][0]["homeAthleteOdds"]["current"]["moneyLine"] = {"american": "+120"}
            moved["items"][0]["homeAthleteOdds"]["moneyLine"] = 120
            counts = store.upsert("odds", odds.parse_odds(moved, bout=bout, fetched_utc="2026-10-03T13:00:00Z", source_url=SRC))
            self.assertEqual(counts, {"added": 0, "updated": 1, "unchanged": 0, "total": 1})
            self.assertEqual(store.load("odds")[0]["a_ml_current"], 120)
            self.assertEqual(store.load("odds")[0]["a_ml_open"], 105)         # the open price is kept as it was


class ScriptedOpener:
    """An opener for PoliteFetcher that answers from a script and counts the calls."""

    class Response:
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

    def __init__(self, answers):
        self.answers = {http.canonical_url(u): list(a) for u, a in answers.items()}
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        status, body = self.answers[request.full_url].pop(0)
        return self.Response(status, body)


class WithTheRealFetcher(unittest.TestCase):
    """The cache behaviour fetch_bout_odds relies on, through PoliteFetcher itself."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bout = bout_of("scoreboard_2026-09-26.json", "401924683")
        self.url = odds_url(self.bout)
        self.body = (FIXTURES / "odds_401924683.json").read_bytes()
        self.stamp = {"now": "2026-09-26T20:00:00Z"}

    def fetcher(self, opener):
        return http.PoliteFetcher(cache_dir=Path(self.tmp.name), opener=opener, sleep=lambda s: None,
                                  delay_s=0, now_iso=lambda: self.stamp["now"])

    def test_a_pre_fight_copy_is_replaced_once_and_then_the_closing_copy_stays(self):
        opener = ScriptedOpener({self.url: [(200, self.body)] * 4})
        fetcher = self.fetcher(opener)
        # read at 20:00Z the evening before, while the bout was still scheduled (cached under max_age)
        scheduled = dict(self.bout, status="scheduled")
        odds.fetch_bout_odds(fetcher, scheduled)
        self.assertEqual(len(opener.calls), 1)
        # the bout is final; the cached copy predates 08:00Z, so it is read again (and stamped after 08:00Z)
        self.stamp["now"] = "2026-09-27T10:00:00Z"
        rows = odds.fetch_bout_odds(fetcher, self.bout)
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(rows[0]["fetched_utc"], "2026-09-27T10:00:00Z")
        # now the closing copy is trusted: no more requests, however often it is asked for
        for _ in range(3):
            odds.fetch_bout_odds(fetcher, self.bout)
        self.assertEqual(len(opener.calls), 2)

    def test_an_upcoming_bouts_stale_copy_is_read_again_and_a_fresh_one_is_not(self):
        bout = dict(self.bout, status="scheduled")
        opener = ScriptedOpener({self.url: [(200, self.body)] * 3})
        self.stamp["now"] = "2020-01-01T00:00:00Z"                       # a copy from years ago
        fetcher = self.fetcher(opener)
        odds.fetch_bout_odds(fetcher, bout)
        self.assertEqual(len(opener.calls), 1)
        self.stamp["now"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        odds.fetch_bout_odds(fetcher, bout)                              # older than 30 minutes: read again
        self.assertEqual(len(opener.calls), 2)
        odds.fetch_bout_odds(fetcher, bout)                              # just fetched: served from the cache
        self.assertEqual(len(opener.calls), 2)

    def test_an_empty_list_is_cached_like_any_other_page(self):
        empty = (FIXTURES / "odds_223077_2016.json").read_bytes()
        bout = bout_of("scoreboard_2016-07-09.json", "223077")
        opener = ScriptedOpener({odds_url(bout): [(200, empty)] * 2})
        self.stamp["now"] = "2026-10-03T12:00:00Z"
        fetcher = self.fetcher(opener)
        for _ in range(3):
            self.assertEqual(odds.fetch_bout_odds(fetcher, bout), [])
        self.assertEqual(len(opener.calls), 1)


if __name__ == "__main__":
    unittest.main()
