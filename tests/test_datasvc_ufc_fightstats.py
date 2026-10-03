"""Per-fight statistics (src/datasvc/ufc/fightstats.py): parser, field map, fetching.

No network. Parsers run on the saved ESPN responses in tests/fixtures/espn_mma (the
`competitor_*_statistics*` files and the `w3_` captures); fetching goes through a fake
fetcher that serves those files by URL, plus a real PoliteFetcher over a scripted opener
for the cache behaviour (a 404 is cached, a recent bout is refreshed).

Every claim the module docstring makes about what a statistic means is re-checked here
against all 22 saved payloads, so a wrong claim fails a test instead of misleading a reader.
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
from src.datasvc.ufc import espn_urls, fightstats

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_mma"
FETCHED = "2026-10-03T18:00:00Z"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def bout_from_scoreboard(name, comp_id, status=None):
    """A bouts.jsonl-shaped record: order 1 is fighter a, order 2 is fighter b."""
    for event in load(name)["events"]:
        for comp in event["competitions"]:
            if comp["id"] == comp_id:
                by_order = {c["order"]: c for c in comp["competitors"]}
                winners = [c["id"] for c in comp["competitors"] if c.get("winner")]
                mapped = {"STATUS_FINAL": "final", "STATUS_SCHEDULED": "scheduled"}
                return {"bout_id": comp["id"], "event_id": event["id"], "date_utc": comp["date"],
                        "status": status or mapped[comp["status"]["type"]["name"]],
                        "fighter_a_id": by_order[1]["id"], "fighter_b_id": by_order[2]["id"],
                        "winner_id": winners[0] if winners else None}
    raise KeyError(comp_id)


def bout_from_event(name, comp_id, status="final"):
    """The same record from a core-API event (competitions embedded, status is a $ref)."""
    event = load(name)
    for comp in event["competitions"]:
        if comp["id"] == comp_id:
            by_order = {c["order"]: c for c in comp["competitors"]}
            return {"bout_id": comp["id"], "event_id": event["id"], "date_utc": comp["date"], "status": status,
                    "fighter_a_id": by_order[1]["id"], "fighter_b_id": by_order[2]["id"]}
    raise KeyError(comp_id)


SB_2026 = "scoreboard_2026-09-26.json"

# (payload file, bout source, bout id, fighter id): every saved statistics payload.
PAYLOADS = [
    ("competitor_223077_2335718_statistics_2016.json", "scoreboard_2016-07-09.json", "223077", "2335718"),
    ("competitor_401911630_3075570_statistics.json", SB_2026, "401911630", "3075570"),
    ("competitor_401911630_5088844_statistics.json", SB_2026, "401911630", "5088844"),
    ("competitor_401914466_3922491_statistics.json", SB_2026, "401914466", "3922491"),
    ("competitor_401914466_4339130_statistics.json", SB_2026, "401914466", "4339130"),
    ("competitor_401924683_5060467_statistics.json", SB_2026, "401924683", "5060467"),
    ("competitor_401924683_5369427_statistics.json", SB_2026, "401924683", "5369427"),
    ("w3_competitor_151885_2335464_statistics_2005.json", "w3_scoreboard_2005-04-16.json", "151885", "2335464"),
    ("w3_competitor_152100_2335298_statistics_2009.json", "w3_scoreboard_2009-07-11.json", "152100", "2335298"),
    ("w3_competitor_157813_2335659_statistics_2011.json", "w3_scoreboard_2011-04-30.json", "157813", "2335659"),
    ("w3_competitor_192588_2335639_statistics_2014.json", "w3_scoreboard_2014-04-26.json", "192588", "2335639"),
    ("w3_competitor_236217_2335639_statistics_2017.json", "w3_scoreboard_2017-07-29.json", "236217", "2335639"),
    ("w3_competitor_236217_2509290_statistics_2017.json", "w3_scoreboard_2017-07-29.json", "236217", "2509290"),
    ("w3_competitor_243591_2611557_statistics_2018.json", "w3_scoreboard_2018-04-07.json", "243591", "2611557"),
    ("w3_competitor_266329_2611557_statistics_2019.json", "w3_scoreboard_2019-09-07.json", "266329", "2611557"),
    ("w3_competitor_267839_3332412_statistics_2019.json", "w3_scoreboard_2019-09-07.json", "267839", "3332412"),
    ("w3_competitor_401499752_2506250_statistics_2022.json", "w3_scoreboard_2022-12-10.json", "401499752", "2506250"),
    ("w3_competitor_401499752_4273399_statistics_2022.json", "w3_scoreboard_2022-12-10.json", "401499752", "4273399"),
    ("w3_competitor_401632019_2335718_statistics_2024.json", "w3_scoreboard_2024-04-13.json", "401632019", "2335718"),
    ("w3_competitor_401799532_5077131_statistics_2025.json", "w3_scoreboard_2025-07-19.json", "401799532", "5077131"),
    ("w3_competitor_401877162_5362337_statistics_2026_06.json", "w3_event_600059467.json", "401877162", "5362337"),
]
PLACEHOLDER = ("w3_competitor_401912275_4412813_statistics_upcoming.json", "scoreboard_2026-10-03.json",
               "401912275", "4412813")


def bout_of(source, comp_id, status=None):
    return (bout_from_event(source, comp_id) if "event" in source and "scoreboard" not in source
            else bout_from_scoreboard(source, comp_id, status))


def parse_payload(entry, status=None):
    name, source, comp_id, fighter_id = entry
    bout = bout_of(source, comp_id, status)
    return fightstats.parse_competitor_statistics(load(name), bout=bout, fighter_id=fighter_id,
                                                  fetched_utc=FETCHED, source_url="https://example.test/" + name)


def raw_values(payload):
    return {s["name"]: s["value"] for c in payload["splits"]["categories"] for s in c["stats"]}


def camel_to_snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


# The 43 statistic names ESPN sends on a 2026 bout, as listed in docs/datasvc/UFC_SCHEMA.md.
CONTRACT_NAMES = """knockDowns totalStrikesAttempted totalStrikesLanded sigStrikesAttempted sigStrikesLanded
sigDistanceHeadStrikesAttempted sigDistanceHeadStrikesLanded sigDistanceBodyStrikesAttempted
sigDistanceBodyStrikesLanded sigDistanceLegStrikesAttempted sigDistanceLegStrikesLanded
sigClinchBodyStrikesAttempted sigClinchBodyStrikesLanded sigClinchHeadStrikesAttempted
sigClinchHeadStrikesLanded sigClinchLegStrikesAttempted sigClinchLegStrikesLanded
sigGroundHeadStrikesAttempted sigGroundHeadStrikesLanded sigGroundBodyStrikesAttempted
sigGroundBodyStrikesLanded sigGroundLegStrikesAttempted sigGroundLegStrikesLanded takedownsAttempted
takedownsLanded takedownsSlams takedownAccuracy targetBreakdownHead targetBreakdownBody
targetBreakdownLeg posBreakdownDistance posBreakdownClinch posBreakdownGround advances
advanceToHalfGuard advanceToSide advanceToMount advanceToBack reversals submissions slamRate
timeInControl wallclock""".split()

# Raoni Barcelos in the 2026-09-26 main event (bout 401911630), typed out by hand from the
# saved payload so the parser is not graded against itself.
BARCELOS = {
    "knockdowns": 0, "total_strikes_attempted": 303, "total_strikes_landed": 198,
    "sig_strikes_attempted": 223, "sig_strikes_landed": 127,
    "sig_distance_head_strikes_attempted": 167, "sig_distance_head_strikes_landed": 81,
    "sig_distance_body_strikes_attempted": 39, "sig_distance_body_strikes_landed": 33,
    "sig_distance_leg_strikes_attempted": 3, "sig_distance_leg_strikes_landed": 3,
    "sig_clinch_body_strikes_attempted": 1, "sig_clinch_body_strikes_landed": 1,
    "sig_clinch_head_strikes_attempted": 12, "sig_clinch_head_strikes_landed": 8,
    "sig_clinch_leg_strikes_attempted": 0, "sig_clinch_leg_strikes_landed": 0,
    "sig_ground_head_strikes_attempted": 1, "sig_ground_head_strikes_landed": 1,
    "sig_ground_body_strikes_attempted": 0, "sig_ground_body_strikes_landed": 0,
    "sig_ground_leg_strikes_attempted": 0, "sig_ground_leg_strikes_landed": 0,
    "takedowns_attempted": 22, "takedowns_landed": 9, "takedowns_slams": 0, "takedown_accuracy": 0.409,
    "sig_head_accuracy": 0.5, "sig_body_accuracy": 0.85, "sig_leg_accuracy": 1.0,
    "sig_distance_accuracy": 0.56, "sig_clinch_accuracy": 0.692, "sig_ground_accuracy": 1.0,
    "advances": 0, "advance_to_half_guard": 0, "advance_to_side": 0, "advance_to_mount": 0,
    "advance_to_back": 0, "reversals": 0, "submission_attempts": 5, "slam_rate": 0.0,
    "control_time_s": 381, "wallclock_epoch_s": 1790501928,
}
BARCELOS_UNITS = {"takedown_accuracy": "ratio_0_1", "sig_head_accuracy": "ratio_0_1",
                  "sig_body_accuracy": "ratio_0_1", "sig_leg_accuracy": "ratio_0_1",
                  "sig_distance_accuracy": "ratio_0_1", "sig_clinch_accuracy": "ratio_0_1",
                  "sig_ground_accuracy": "ratio_0_1", "slam_rate": "ratio_0_1",
                  "control_time_s": "seconds", "wallclock_epoch_s": "epoch_seconds"}


class FixtureFetcher:
    """Duck-types PoliteFetcher: serves payloads by canonical URL and records every call."""

    def __init__(self, routes=None, *, missing=(), errors=None, fetched=None):
        canon = http.canonical_url
        self.routes = {canon(u): p for u, p in (routes or {}).items()}
        self.missing = {canon(u) for u in missing}
        self.errors = {canon(u): e for u, e in (errors or {}).items()}
        self.fetched = {canon(u): s for u, s in (fetched or {}).items()}
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
        return self.fetched.get(http.canonical_url(url), FETCHED)


def stats_url(bout, fighter_id):
    return espn_urls.competitor_statistics(bout["event_id"], bout["bout_id"], fighter_id)


def retarget(payload, fighter_id):
    """The placeholder payload as ESPN would serve it for another fighter of the same bout."""
    out = copy.deepcopy(payload)
    out["$ref"] = re.sub(r"/competitors/\d+/", f"/competitors/{fighter_id}/", out["$ref"])
    return out


class StatMapTests(unittest.TestCase):
    def test_it_covers_exactly_the_43_statistics_of_a_2026_payload(self):
        sent = set(raw_values(load("competitor_401911630_3075570_statistics.json")))
        self.assertEqual(len(sent), 43)
        self.assertEqual(set(fightstats.STAT_MAP), sent)
        self.assertEqual(set(fightstats.STAT_MAP), set(CONTRACT_NAMES))

    def test_every_statistic_of_every_payload_is_mapped(self):
        for name, *_ in PAYLOADS + [PLACEHOLDER]:
            with self.subTest(name):
                self.assertLessEqual(set(raw_values(load(name))), set(fightstats.STAT_MAP))

    def test_fields_are_unique_snake_case_with_a_known_unit_and_role(self):
        fields = [s.field for s in fightstats.STAT_MAP.values()]
        self.assertEqual(len(fields), len(set(fields)))
        for espn_name, stat in fightstats.STAT_MAP.items():
            self.assertRegex(stat.field, r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
            self.assertIn(stat.unit, fightstats.UNITS)
            self.assertIn(fightstats.ROLE_OF[espn_name], fightstats.ROLES)
            self.assertTrue(fightstats.NOTE_OF[espn_name])
        self.assertEqual(set(fightstats.ROLE_OF), set(fightstats.STAT_MAP))
        self.assertEqual(set(fightstats.NOTE_OF), set(fightstats.STAT_MAP))
        self.assertEqual(fightstats.FIELDS, tuple(fields))

    def test_an_entry_unpacks_as_field_and_unit(self):
        field, unit = fightstats.STAT_MAP["timeInControl"]
        self.assertEqual((field, unit), ("control_time_s", "seconds"))
        self.assertEqual(fightstats.STAT_MAP["knockDowns"], ("knockdowns", "count"))
        self.assertEqual(fightstats.STAT_MAP["slamRate"].unit, "ratio_0_1")
        for entry in fightstats.STAT_MAP.values():
            self.assertEqual(len(entry), 2)

    def test_field_names_follow_the_espn_name_except_the_documented_renames(self):
        renamed = {
            "knockDowns": "knockdowns", "submissions": "submission_attempts", "timeInControl": "control_time_s",
            "wallclock": "wallclock_epoch_s",
            "targetBreakdownHead": "sig_head_accuracy", "targetBreakdownBody": "sig_body_accuracy",
            "targetBreakdownLeg": "sig_leg_accuracy", "posBreakdownDistance": "sig_distance_accuracy",
            "posBreakdownClinch": "sig_clinch_accuracy", "posBreakdownGround": "sig_ground_accuracy",
        }
        for espn_name, stat in fightstats.STAT_MAP.items():
            with self.subTest(espn_name):
                self.assertEqual(stat.field, renamed.get(espn_name, camel_to_snake(espn_name)))

    def test_units(self):
        ratios = {"takedownAccuracy", "targetBreakdownHead", "targetBreakdownBody", "targetBreakdownLeg",
                  "posBreakdownDistance", "posBreakdownClinch", "posBreakdownGround", "slamRate"}
        for espn_name, stat in fightstats.STAT_MAP.items():
            role = fightstats.ROLE_OF[espn_name]
            with self.subTest(espn_name):
                if espn_name in ratios:
                    self.assertEqual((stat.unit, role), ("ratio_0_1", "ratio"))
                elif espn_name == "timeInControl":
                    self.assertEqual((stat.unit, role), ("seconds", "measure"))
                elif espn_name == "wallclock":
                    self.assertEqual((stat.unit, role), ("epoch_seconds", "metadata"))
                else:
                    self.assertEqual((stat.unit, role), ("count", "measure"))
        self.assertEqual(fightstats.METADATA_FIELDS, ("wallclock_epoch_s",))
        self.assertEqual(len(fightstats.MEASURE_FIELDS), 42)
        self.assertEqual(fightstats.ESPN_OF["sig_head_accuracy"], "targetBreakdownHead")


class ParseOne2026Fixture(unittest.TestCase):
    ENTRY = ("competitor_401911630_3075570_statistics.json", SB_2026, "401911630", "3075570")

    def setUp(self):
        self.row = parse_payload(self.ENTRY)

    def test_every_statistic_has_its_exact_value_and_unit(self):
        self.assertEqual(set(BARCELOS), set(fightstats.FIELDS))
        for field, expected in BARCELOS.items():
            with self.subTest(field):
                self.assertEqual(self.row[field], expected)
                unit = BARCELOS_UNITS.get(field, "count")
                stat = next(s for s in fightstats.STAT_MAP.values() if s.field == field)
                self.assertEqual(stat.unit, unit)
                # whole-number units come out as ints, ratios as floats
                self.assertIs(type(self.row[field]), float if unit == "ratio_0_1" else int)

    def test_identity_fields(self):
        row = self.row
        self.assertEqual((row["bout_id"], row["fighter_id"], row["event_id"]), ("401911630", "3075570", "600061266"))
        self.assertEqual(row["opponent_id"], "5088844")
        self.assertEqual(row["date_utc"], "2026-09-27T00:00Z")
        self.assertIs(row["stats_complete"], True)
        self.assertEqual(row["stats_missing"], [])
        self.assertEqual(row["unmapped_stats"], {})
        self.assertEqual(row["fetched_utc"], FETCHED)
        self.assertEqual(row["source_url"], "https://example.test/competitor_401911630_3075570_statistics.json")

    def test_the_value_is_read_not_the_rounded_display_value(self):
        raw = {s["name"]: s for s in load(self.ENTRY[0])["splits"]["categories"][0]["stats"]}
        self.assertEqual(raw["targetBreakdownBody"]["displayValue"], "1")
        self.assertEqual(raw["targetBreakdownBody"]["value"], 0.85)
        self.assertEqual(self.row["sig_body_accuracy"], 0.85)
        self.assertEqual(raw["takedownAccuracy"]["displayValue"], "0.41")
        self.assertEqual(self.row["takedown_accuracy"], 0.409)

    def test_the_row_is_json_stable(self):
        text = json.dumps(self.row, sort_keys=True)
        self.assertEqual(json.loads(text), self.row)

    def test_wallclock_is_the_instant_espn_displays(self):
        raw = {s["name"]: s for s in load(self.ENTRY[0])["splits"]["categories"][0]["stats"]}
        shown = datetime.fromtimestamp(self.row["wallclock_epoch_s"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(shown, raw["wallclock"]["displayValue"])
        self.assertEqual(shown, "2026-09-27T09:38:48Z")

    def test_the_other_fighter_of_each_2026_bout_has_the_first_as_opponent(self):
        for comp, a, b in (("401911630", "5088844", "3075570"), ("401914466", "4339130", "3922491"),
                           ("401924683", "5369427", "5060467")):
            bout = bout_from_scoreboard(SB_2026, comp)
            self.assertEqual((bout["fighter_a_id"], bout["fighter_b_id"]), (a, b))
            for fighter, opponent in ((a, b), (b, a)):
                with self.subTest(comp=comp, fighter=fighter):
                    entry = next(e for e in PAYLOADS if e[2] == comp and e[3] == fighter)
                    row = parse_payload(entry)
                    self.assertEqual((row["fighter_id"], row["opponent_id"]), (fighter, opponent))

    def test_a_second_fighter_exactly_where_the_counts_are_not_zero(self):
        # Montel Jackson, 2026-09-26: two knockdowns, one submission attempt, a KO win in round 2.
        row = parse_payload(("competitor_401914466_4339130_statistics.json", SB_2026, "401914466", "4339130"))
        self.assertEqual((row["knockdowns"], row["submission_attempts"], row["takedowns_landed"]), (2, 1, 0))
        self.assertEqual((row["sig_strikes_landed"], row["sig_strikes_attempted"], row["control_time_s"]), (31, 56, 13))
        self.assertEqual(row["opponent_id"], "3922491")


class OlderPayloads(unittest.TestCase):
    def test_2016_is_missing_only_the_wallclock_and_says_so(self):
        entry = PAYLOADS[0]
        row = parse_payload(entry)
        self.assertIsNone(row["wallclock_epoch_s"])
        self.assertIs(row["stats_complete"], False)
        self.assertEqual(row["stats_missing"], ["wallclock_epoch_s"])
        present = [f for f in fightstats.FIELDS if f != "wallclock_epoch_s"]
        self.assertTrue(all(row[f] is not None for f in present))
        self.assertEqual(len(present), 42)
        # Jim Miller beat Takanori Gomi at UFC 200 (event 400818923); order 1 is Miller.
        self.assertEqual((row["fighter_id"], row["opponent_id"], row["event_id"]), ("2335718", "2354524", "400818923"))
        self.assertEqual(row["date_utc"], "2016-07-09T22:30Z")
        self.assertEqual((row["takedowns_landed"], row["sig_strikes_landed"], row["sig_strikes_attempted"]), (1, 8, 26))

    def test_the_wallclock_arrives_in_2026_and_only_then(self):
        complete = {}
        for entry in PAYLOADS:
            row = parse_payload(entry)
            complete[entry[0]] = row["stats_complete"]
            self.assertEqual(row["stats_missing"], [] if row["stats_complete"] else ["wallclock_epoch_s"])
        wanted = {name for name, *_ in PAYLOADS if "statistics.json" in name or "2026_06" in name}
        self.assertEqual({n for n, ok in complete.items() if ok}, wanted)
        self.assertEqual(len(wanted), 7)          # six 2026-09-26 payloads and the 2026-06-20 one
        self.assertEqual(sum(1 for ok in complete.values() if not ok), 14)

    def test_control_time_reads_zero_before_2018_even_when_there_was_control(self):
        # Takedowns landed or ground strikes thrown, and ESPN still says 0 seconds of control.
        for name in ("w3_competitor_152100_2335298_statistics_2009.json",     # Lesnar, 1 takedown landed
                     "w3_competitor_157813_2335659_statistics_2011.json",     # St-Pierre, 2
                     "w3_competitor_192588_2335639_statistics_2014.json",     # Jones, 3
                     "competitor_223077_2335718_statistics_2016.json",        # Miller, 1 and 18 ground strikes
                     "w3_competitor_236217_2335639_statistics_2017.json"):    # Jones, 17 ground head strikes
            with self.subTest(name):
                entry = next(e for e in PAYLOADS if e[0] == name)
                row = parse_payload(entry)
                self.assertEqual(row["control_time_s"], 0)
                self.assertTrue(row["takedowns_landed"] > 0 or row["sig_ground_head_strikes_attempted"] > 0)

    def test_control_time_is_recorded_from_2018(self):
        by_bout = {}
        for entry in PAYLOADS:
            date = bout_of(entry[1], entry[2])["date_utc"]
            if date >= "2018-04-07":
                by_bout.setdefault(entry[2], []).append(parse_payload(entry)["control_time_s"])
        self.assertEqual(len(by_bout), 10)        # 10 of the 16 fought bouts are from 2018-04-07 on
        for bout, times in by_bout.items():
            with self.subTest(bout):
                self.assertTrue(any(t > 0 for t in times), times)
        khabib = parse_payload(next(e for e in PAYLOADS if e[0].startswith("w3_competitor_243591")))
        self.assertEqual(khabib["control_time_s"], 633)

    def test_slams_and_their_rate_in_the_one_payload_where_there_are_any(self):
        row = parse_payload(next(e for e in PAYLOADS if e[0].startswith("w3_competitor_243591")))
        self.assertEqual((row["takedowns_slams"], row["takedowns_attempted"], row["takedowns_landed"]), (2, 15, 6))
        self.assertEqual(row["slam_rate"], 0.133)
        self.assertEqual(round(2 / 15, 3), 0.133)
        others = [parse_payload(e)["takedowns_slams"] for e in PAYLOADS if not e[0].startswith("w3_competitor_243591")]
        self.assertEqual(others, [0] * 20)


class WhatTheStatisticsMean(unittest.TestCase):
    """The docstring's claims, checked on every saved payload."""

    @classmethod
    def setUpClass(cls):
        cls.rows = {entry[0]: parse_payload(entry) for entry in PAYLOADS}
        cls.raw = {entry[0]: load(entry[0]) for entry in PAYLOADS}

    def landed_attempted(self, row, positions, targets):
        landed = sum(row[f"sig_{p}_{t}_strikes_landed"] for p in positions for t in targets)
        attempted = sum(row[f"sig_{p}_{t}_strikes_attempted"] for p in positions for t in targets)
        return landed, attempted

    def test_the_nine_position_by_target_counts_add_up_to_the_significant_strikes(self):
        for name, row in self.rows.items():
            with self.subTest(name):
                landed, attempted = self.landed_attempted(row, ("distance", "clinch", "ground"), ("head", "body", "leg"))
                self.assertEqual((landed, attempted), (row["sig_strikes_landed"], row["sig_strikes_attempted"]))

    def test_landed_never_exceeds_attempted_and_total_strikes_include_the_significant_ones(self):
        for name, row in self.rows.items():
            with self.subTest(name):
                self.assertLessEqual(row["sig_strikes_landed"], row["sig_strikes_attempted"])
                self.assertLessEqual(row["total_strikes_landed"], row["total_strikes_attempted"])
                self.assertLessEqual(row["takedowns_landed"], row["takedowns_attempted"])
                self.assertGreaterEqual(row["total_strikes_attempted"], row["sig_strikes_attempted"])
                self.assertGreaterEqual(row["total_strikes_landed"], row["sig_strikes_landed"])

    def test_the_target_and_position_breakdowns_are_accuracies(self):
        for name, row in self.rows.items():
            for field, positions, targets in (
                    ("sig_head_accuracy", ("distance", "clinch", "ground"), ("head",)),
                    ("sig_body_accuracy", ("distance", "clinch", "ground"), ("body",)),
                    ("sig_leg_accuracy", ("distance", "clinch", "ground"), ("leg",)),
                    ("sig_distance_accuracy", ("distance",), ("head", "body", "leg")),
                    ("sig_clinch_accuracy", ("clinch",), ("head", "body", "leg")),
                    ("sig_ground_accuracy", ("ground",), ("head", "body", "leg"))):
                landed, attempted = self.landed_attempted(row, positions, targets)
                if attempted:
                    with self.subTest(name=name, field=field):
                        self.assertAlmostEqual(row[field], landed / attempted, delta=0.0011)

    def test_they_are_not_shares_of_the_strikes_thrown(self):
        row = self.rows["competitor_401911630_3075570_statistics.json"]
        landed, attempted = self.landed_attempted(row, ("distance", "clinch", "ground"), ("head",))
        self.assertEqual((landed, attempted), (90, 180))
        self.assertEqual(row["sig_head_accuracy"], 0.5)
        head_share = attempted / row["sig_strikes_attempted"]
        self.assertAlmostEqual(head_share, 0.807, places=3)
        self.assertGreater(abs(row["sig_head_accuracy"] - head_share), 0.3)
        # the three target accuracies would add to 1 if they were shares; they add to 2.35
        total = row["sig_head_accuracy"] + row["sig_body_accuracy"] + row["sig_leg_accuracy"]
        self.assertAlmostEqual(total, 2.35, places=3)

    def test_the_rounding_quirk_is_one_thousandth(self):
        # 25 landed of 46 attempted at distance is 0.5435; ESPN reports 0.544 (double rounding).
        row = self.rows["competitor_401914466_4339130_statistics.json"]
        landed, attempted = self.landed_attempted(row, ("distance",), ("head", "body", "leg"))
        self.assertEqual((landed, attempted), (25, 46))
        self.assertEqual(row["sig_distance_accuracy"], 0.544)
        self.assertEqual(round(landed / attempted, 3), 0.543)

    def test_takedown_accuracy_and_slam_rate_are_ratios_of_the_counts(self):
        for name, row in self.rows.items():
            with self.subTest(name):
                if row["takedowns_attempted"]:
                    self.assertAlmostEqual(row["takedown_accuracy"], row["takedowns_landed"] / row["takedowns_attempted"], delta=0.0011)
                    self.assertAlmostEqual(row["slam_rate"], row["takedowns_slams"] / row["takedowns_attempted"], delta=0.0011)

    def test_a_zero_denominator_ratio_is_not_reliable(self):
        """ESPN reports 0.0 for 0 of 0 in 24 of 26 cases and 1.0 in two: recompute from the counts."""
        reported = []
        for name, row in self.rows.items():
            for field, positions, targets in (
                    ("sig_head_accuracy", ("distance", "clinch", "ground"), ("head",)),
                    ("sig_body_accuracy", ("distance", "clinch", "ground"), ("body",)),
                    ("sig_leg_accuracy", ("distance", "clinch", "ground"), ("leg",)),
                    ("sig_distance_accuracy", ("distance",), ("head", "body", "leg")),
                    ("sig_clinch_accuracy", ("clinch",), ("head", "body", "leg")),
                    ("sig_ground_accuracy", ("ground",), ("head", "body", "leg"))):
                if self.landed_attempted(row, positions, targets)[1] == 0:
                    reported.append((name, field, row[field]))
            for field, attempts in (("takedown_accuracy", "takedowns_attempted"), ("slam_rate", "takedowns_attempted")):
                if row[attempts] == 0:
                    reported.append((name, field, row[field]))
        self.assertEqual(len(reported), 26)
        self.assertEqual(sum(1 for r in reported if r[2] == 0.0), 24)
        self.assertEqual({(r[0], r[1]) for r in reported if r[2] == 1.0},
                         {("w3_competitor_401799532_5077131_statistics_2025.json", "sig_clinch_accuracy"),
                          ("w3_competitor_401877162_5362337_statistics_2026_06.json", "sig_ground_accuracy")})

    def test_safe_ratio_is_none_without_attempts(self):
        self.assertEqual(fightstats.safe_ratio(9, 22), 9 / 22)
        self.assertIsNone(fightstats.safe_ratio(0, 0))
        self.assertIsNone(fightstats.safe_ratio(None, 5))
        self.assertEqual(fightstats.safe_ratio(0, 5), 0.0)

    def test_advances_are_the_sum_of_the_four_advance_to_counts(self):
        for name, row in self.rows.items():
            with self.subTest(name):
                self.assertEqual(row["advances"], sum(row[f"advance_to_{p}"] for p in ("half_guard", "side", "mount", "back")))
        self.assertEqual(self.rows["w3_competitor_266329_2611557_statistics_2019.json"]["advances"], 5)

    def test_control_time_is_the_seconds_behind_the_m_ss_display(self):
        for name, payload in self.raw.items():
            stat = next(s for s in payload["splits"]["categories"][0]["stats"] if s["name"] == "timeInControl")
            minutes, seconds = stat["displayValue"].split(":")
            with self.subTest(name):
                self.assertEqual(int(minutes) * 60 + int(seconds), self.rows[name]["control_time_s"])

    def test_every_count_is_a_whole_number(self):
        for name, payload in self.raw.items():
            for stat_name, value in raw_values(payload).items():
                if fightstats.STAT_MAP[stat_name].unit == "ratio_0_1":
                    continue
                with self.subTest(name=name, stat=stat_name):
                    self.assertEqual(value, int(value))

    def test_both_fighters_carry_the_same_wallclock_and_it_is_hours_after_the_fight(self):
        for comp in ("401911630", "401914466", "401924683"):
            stamps = {parse_payload(e)["wallclock_epoch_s"] for e in PAYLOADS if e[2] == comp}
            self.assertEqual(len(stamps), 1, comp)
        # Bout 401924683's play-by-play ends at 01:14:57Z on 2026-09-27; the statistics are stamped 08:14:50Z.
        details = load("competition_401924683_details.json")
        last = max(item["wallclock"] for item in details["items"])
        self.assertEqual(last, "2026-09-27T01:14:57Z")
        stamp = parse_payload(next(e for e in PAYLOADS if e[2] == "401924683"))["wallclock_epoch_s"]
        shown = datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(shown, "2026-09-27T08:14:50Z")

    def test_submissions_are_attempts_not_successful_submissions(self):
        # A KO win's loser has 5 (so it is not "submissions won"), and the play-by-play of two
        # bouts lists as many Submission Attempt events as the statistic.
        barcelos = self.rows["competitor_401911630_3075570_statistics.json"]
        self.assertEqual(barcelos["submission_attempts"], 5)
        status = load("competition_401911630_status.json")
        self.assertEqual(status["result"]["name"], "kotko")
        for comp, attempts, knockdowns in (("401924683", 2, 0), ("401914466", 1, 2)):
            events = [i["type"]["text"] for i in load(f"competition_{comp}_details.json")["items"]]
            rows = [self.rows[e[0]] for e in PAYLOADS if e[2] == comp]
            with self.subTest(comp):
                self.assertEqual(events.count("Submission Attempt"), attempts)
                self.assertEqual(sum(r["submission_attempts"] for r in rows), attempts)
                self.assertEqual(events.count("Knockdown"), knockdowns)
                self.assertEqual(sum(r["knockdowns"] for r in rows), knockdowns)


class GuardsAndEdges(unittest.TestCase):
    ENTRY = PAYLOADS[1]

    def parse(self, payload, bout=None, fighter_id="3075570"):
        bout = bout or bout_from_scoreboard(SB_2026, "401911630")
        return fightstats.parse_competitor_statistics(payload, bout=bout, fighter_id=fighter_id,
                                                      fetched_utc=FETCHED, source_url="u")

    def test_espn_serves_zeros_not_a_404_for_a_bout_that_has_not_been_fought(self):
        payload = load(PLACEHOLDER[0])
        values = raw_values(payload)
        self.assertEqual(len(values), 42)
        self.assertEqual(set(values.values()), {0.0})
        self.assertNotIn("wallclock", values)

    def test_a_bout_that_has_not_been_fought_is_refused(self):
        payload = load(PLACEHOLDER[0])
        for status in ("scheduled", "canceled", "postponed"):
            bout = bout_from_scoreboard(PLACEHOLDER[1], PLACEHOLDER[2], status)
            with self.subTest(status), self.assertRaises(ValueError):
                fightstats.parse_competitor_statistics(payload, bout=bout, fighter_id=PLACEHOLDER[3],
                                                       fetched_utc=FETCHED, source_url="u")

    def test_in_progress_and_unknown_status_are_parsed(self):
        for status in ("in_progress", "unknown", None):
            bout = bout_from_scoreboard(SB_2026, "401911630")
            bout["status"] = status
            self.assertEqual(self.parse(load(self.ENTRY[0]), bout)["sig_strikes_landed"], 127)

    def test_the_placeholder_is_recognised_as_one(self):
        bout = bout_from_scoreboard(PLACEHOLDER[1], PLACEHOLDER[2], "final")
        row = fightstats.parse_competitor_statistics(load(PLACEHOLDER[0]), bout=bout, fighter_id=PLACEHOLDER[3],
                                                     fetched_utc=FETCHED, source_url="u")
        self.assertTrue(fightstats.is_placeholder(row))
        self.assertFalse(row["stats_complete"])
        for entry in PAYLOADS:
            self.assertFalse(fightstats.is_placeholder(parse_payload(entry)), entry[0])

    def test_the_placeholder_is_still_recognised_when_a_zero_over_zero_ratio_reads_one(self):
        payload = load(PLACEHOLDER[0])
        for stat in payload["splits"]["categories"][0]["stats"]:
            if stat["name"] == "posBreakdownClinch":
                stat["value"] = 1.0                       # ESPN does this for 0 of 0 in a few real payloads
        bout = bout_from_scoreboard(PLACEHOLDER[1], PLACEHOLDER[2], "final")
        row = fightstats.parse_competitor_statistics(payload, bout=bout, fighter_id=PLACEHOLDER[3],
                                                     fetched_utc=FETCHED, source_url="u")
        self.assertEqual(row["sig_clinch_accuracy"], 1.0)
        self.assertTrue(fightstats.is_placeholder(row))
        self.assertEqual(len(fightstats.COUNT_FIELDS), 34)
        self.assertNotIn("slam_rate", fightstats.COUNT_FIELDS)
        self.assertIn("control_time_s", fightstats.COUNT_FIELDS)

    def test_all_zero_with_a_wallclock_is_a_real_row(self):
        bout = bout_from_scoreboard(SB_2026, "401911630")
        payload = load(PLACEHOLDER[0])
        payload["$ref"] = load(self.ENTRY[0])["$ref"]
        payload["splits"]["categories"][0]["stats"].append({"name": "wallclock", "value": 1790501928.0})
        row = self.parse(payload, bout)
        self.assertTrue(row["stats_complete"])
        self.assertFalse(fightstats.is_placeholder(row))

    def test_a_fighter_who_is_not_in_the_bout_is_an_error(self):
        with self.assertRaises(ValueError):
            self.parse(load(self.ENTRY[0]), fighter_id="9999999")

    def test_a_payload_for_another_fighter_bout_or_event_is_an_error(self):
        payload = load(self.ENTRY[0])
        with self.assertRaises(ValueError):                       # this fighter's payload, the opponent's id
            self.parse(payload, fighter_id="5088844")
        other_bout = bout_from_scoreboard(SB_2026, "401914466")
        with self.assertRaises(ValueError):                       # another bout of the same card
            self.parse(payload, bout=other_bout, fighter_id="3922491")
        wrong_event = dict(bout_from_scoreboard(SB_2026, "401911630"), event_id="1")
        with self.assertRaises(ValueError):
            self.parse(payload, bout=wrong_event)

    def test_a_payload_without_a_ref_is_not_checked(self):
        payload = load(self.ENTRY[0])
        del payload["$ref"]
        self.assertEqual(self.parse(payload)["opponent_id"], "5088844")

    def test_an_unknown_statistic_is_kept_not_dropped(self):
        payload = load(self.ENTRY[0])
        payload["splits"]["categories"][0]["stats"].append({"name": "newStat", "value": 7.0, "displayValue": "7"})
        row = self.parse(payload)
        self.assertEqual(row["unmapped_stats"], {"newStat": 7})
        self.assertTrue(row["stats_complete"])

    def test_a_missing_or_unreadable_value_is_null_and_listed(self):
        payload = load(self.ENTRY[0])
        stats = payload["splits"]["categories"][0]["stats"]
        for stat in stats:
            if stat["name"] == "knockDowns":
                del stat["value"]                                 # only the displayValue is left: not read
            if stat["name"] == "reversals":
                stat["value"] = "n/a"
            if stat["name"] == "advances":
                stat["value"] = True
        row = self.parse(payload)
        self.assertEqual([row["knockdowns"], row["reversals"], row["advances"]], [None, None, None])
        self.assertEqual(row["stats_missing"], ["knockdowns", "advances", "reversals"])
        self.assertIs(row["stats_complete"], False)

    def test_no_splits_at_all_gives_a_row_of_nulls(self):
        row = self.parse({"$ref": load(self.ENTRY[0])["$ref"]})
        self.assertEqual(len(row["stats_missing"]), 43)
        self.assertTrue(all(row[f] is None for f in fightstats.FIELDS))
        self.assertFalse(fightstats.is_placeholder(row))

    def test_a_conflicting_duplicate_is_an_error_and_an_identical_one_is_not(self):
        payload = load(self.ENTRY[0])
        stats = payload["splits"]["categories"][0]["stats"]
        stats.append({"name": "knockDowns", "value": 0.0})
        self.assertEqual(self.parse(payload)["knockdowns"], 0)
        stats.append({"name": "knockDowns", "value": 3.0})
        with self.assertRaises(ValueError):
            self.parse(payload)

    def test_dates_parse_in_espns_form(self):
        parse = fightstats._parse_utc
        self.assertEqual(parse("2026-09-27T00:00Z"), datetime(2026, 9, 27, tzinfo=timezone.utc))
        self.assertEqual(parse("2026-09-27T00:00:05Z"), datetime(2026, 9, 27, 0, 0, 5, tzinfo=timezone.utc))
        self.assertEqual(parse("2026-09-27T02:00:00+02:00"), datetime(2026, 9, 27, tzinfo=timezone.utc))
        self.assertEqual(parse("2026-09-27"), datetime(2026, 9, 27, tzinfo=timezone.utc))
        self.assertIsNone(parse("soon"))
        self.assertIsNone(parse(None))
        self.assertIsNone(parse("2026-13-45T00:00Z"))          # shaped like a date, is not one
        self.assertIsNone(parse("2026-09-27T25:00Z"))

    def test_a_now_that_is_not_a_date_is_an_error_not_a_silent_choice(self):
        bout = bout_from_scoreboard(SB_2026, "401911630")
        with self.assertRaises(ValueError):
            fightstats.fetch_bout_stats(FixtureFetcher(), bout, now="yesterday")


class FetchBoutStats(unittest.TestCase):
    def setUp(self):
        self.bout = bout_from_scoreboard(SB_2026, "401911630")          # fighter a 5088844, b 3075570
        self.payloads = {fid: load(next(e for e in PAYLOADS if e[2] == "401911630" and e[3] == fid)[0])
                         for fid in ("5088844", "3075570")}
        self.routes = {stats_url(self.bout, fid): p for fid, p in self.payloads.items()}

    def test_both_fighters_a_first_with_the_urls_and_fetch_time_recorded(self):
        fetcher = FixtureFetcher(self.routes, fetched={stats_url(self.bout, "5088844"): "2026-10-03T01:00:00Z"})
        rows = fightstats.fetch_bout_stats(fetcher, self.bout, now="2026-12-01T00:00:00Z")
        self.assertEqual([r["fighter_id"] for r in rows], ["5088844", "3075570"])
        self.assertEqual([r["opponent_id"] for r in rows], ["3075570", "5088844"])
        self.assertEqual([c["url"] for c in fetcher.calls], [stats_url(self.bout, "5088844"), stats_url(self.bout, "3075570")])
        self.assertTrue(fetcher.calls[0]["url"].endswith("/competitors/5088844/statistics/0"))
        self.assertEqual([r["source_url"] for r in rows], [c["url"] for c in fetcher.calls])
        self.assertEqual([r["fetched_utc"] for r in rows], ["2026-10-03T01:00:00Z", FETCHED])
        self.assertEqual(rows[1]["sig_strikes_landed"], 127)

    def test_an_old_bout_is_read_once_and_a_recent_one_is_refreshed(self):
        old = FixtureFetcher(self.routes)
        fightstats.fetch_bout_stats(old, self.bout, now="2026-12-01T00:00:00Z")
        self.assertEqual([c["max_age_s"] for c in old.calls], [None, None])
        recent = FixtureFetcher(self.routes)
        fightstats.fetch_bout_stats(recent, self.bout, now="2026-09-28T00:00:00Z")
        self.assertEqual([c["max_age_s"] for c in recent.calls], [fightstats.RECENT_MAX_AGE_S] * 2)
        tuned = FixtureFetcher(self.routes)
        fightstats.fetch_bout_stats(tuned, self.bout, now="2026-09-28T00:00:00Z", recent_max_age_s=60)
        self.assertEqual([c["max_age_s"] for c in tuned.calls], [60, 60])
        edge = FixtureFetcher(self.routes)               # exactly four days after the bout is still recent
        fightstats.fetch_bout_stats(edge, self.bout, now="2026-10-01T00:00:00Z")
        self.assertEqual(edge.calls[0]["max_age_s"], fightstats.RECENT_MAX_AGE_S)
        past = FixtureFetcher(self.routes)
        fightstats.fetch_bout_stats(past, self.bout, now="2026-10-01T00:00:01Z")
        self.assertIsNone(past.calls[0]["max_age_s"])

    def test_a_bout_with_an_unreadable_date_counts_as_recent(self):
        fetcher = FixtureFetcher(self.routes)
        fightstats.fetch_bout_stats(fetcher, dict(self.bout, date_utc=None), now="2026-12-01T00:00:00Z")
        self.assertEqual(fetcher.calls[0]["max_age_s"], fightstats.RECENT_MAX_AGE_S)

    def test_a_404_produces_no_row_for_that_fighter(self):
        url_a, url_b = stats_url(self.bout, "5088844"), stats_url(self.bout, "3075570")
        one = FixtureFetcher({url_b: self.payloads["3075570"]}, missing=[url_a])
        rows = fightstats.fetch_bout_stats(one, self.bout, now="2026-12-01T00:00:00Z")
        self.assertEqual([r["fighter_id"] for r in rows], ["3075570"])
        both = FixtureFetcher(missing=[url_a, url_b])
        self.assertEqual(fightstats.fetch_bout_stats(both, self.bout, now="2026-12-01T00:00:00Z"), [])
        self.assertEqual(len(both.calls), 2)

    def test_other_fetch_problems_propagate(self):
        url_a = stats_url(self.bout, "5088844")
        for error in (http.FetchError(url_a, 500, "request failed"), http.SourceBlocked(url_a, 200, "browser check"),
                      http.RequestCapReached(url_a, None, "cap")):
            with self.subTest(type(error).__name__), self.assertRaises(http.FetchError) as caught:
                fightstats.fetch_bout_stats(FixtureFetcher(errors={url_a: error}), self.bout)
            self.assertIs(caught.exception, error)

    def test_a_bout_known_to_be_unfinished_costs_no_request(self):
        for status in ("scheduled", "in_progress", "canceled", "postponed"):
            fetcher = FixtureFetcher()
            bout = dict(self.bout, status=status)
            self.assertEqual(fightstats.fetch_bout_stats(fetcher, bout), [])
            self.assertEqual(fetcher.calls, [], status)

    def test_a_bout_of_missing_or_unknown_status_is_read(self):
        # e.g. a minimal bout record; the placeholder check, not the status, protects against zeros
        for status in ("final", "unknown", None):
            fetcher = FixtureFetcher(self.routes)
            rows = fightstats.fetch_bout_stats(fetcher, dict(self.bout, status=status), now="2026-12-01T00:00:00Z")
            self.assertEqual(len(rows), 2, status)
        minimal = {k: v for k, v in self.bout.items() if k != "status"}
        self.assertEqual(len(fightstats.fetch_bout_stats(FixtureFetcher(self.routes), minimal, now="2026-12-01T00:00:00Z")), 2)
        unposted = bout_from_scoreboard(PLACEHOLDER[1], PLACEHOLDER[2], "final")
        unposted.pop("status")
        placeholder = load(PLACEHOLDER[0])
        routes = {stats_url(unposted, "4412813"): placeholder, stats_url(unposted, "4001851"): retarget(placeholder, "4001851")}
        self.assertEqual(fightstats.fetch_bout_stats(FixtureFetcher(routes), unposted, now="2026-10-04T00:00:00Z"), [])

    def test_a_live_bout_can_be_read_on_request(self):
        fetcher = FixtureFetcher(self.routes)
        rows = fightstats.fetch_bout_stats(fetcher, dict(self.bout, status="in_progress"), skip_unfinished=False)
        self.assertEqual(len(rows), 2)

    def test_a_final_bout_whose_statistics_are_not_posted_yet_gives_no_rows(self):
        bout = bout_from_scoreboard(PLACEHOLDER[1], PLACEHOLDER[2], "final")      # a_id 4001851, b_id 4412813
        placeholder = load(PLACEHOLDER[0])
        routes = {stats_url(bout, "4412813"): placeholder, stats_url(bout, "4001851"): retarget(placeholder, "4001851")}
        fetcher = FixtureFetcher(routes)
        self.assertEqual(fightstats.fetch_bout_stats(fetcher, bout, now="2026-10-04T00:00:00Z"), [])
        self.assertEqual(len(fetcher.calls), 2)

    def test_one_placeholder_next_to_a_real_payload_keeps_both_rows(self):
        # A fighter can honestly have done nothing; only a bout of all placeholders is "not posted".
        placeholder = load(PLACEHOLDER[0])
        placeholder["$ref"] = self.payloads["5088844"]["$ref"]        # as if ESPN had served it for this fighter
        routes = {stats_url(self.bout, "5088844"): placeholder, stats_url(self.bout, "3075570"): self.payloads["3075570"]}
        rows = fightstats.fetch_bout_stats(FixtureFetcher(routes), self.bout, now="2026-12-01T00:00:00Z")
        self.assertEqual(len(rows), 2)

    def test_a_payload_for_the_wrong_bout_is_not_accepted(self):
        routes = {stats_url(self.bout, "5088844"): self.payloads["3075570"], stats_url(self.bout, "3075570"): self.payloads["3075570"]}
        with self.assertRaises(ValueError):
            fightstats.fetch_bout_stats(FixtureFetcher(routes), self.bout)


class StoredThroughTheUfcStore(unittest.TestCase):
    def test_rows_save_under_their_key_and_a_refetch_changes_nothing(self):
        from src.datasvc.ufc.store import UfcStore
        bout = bout_from_scoreboard(SB_2026, "401911630")
        payloads = {fid: load(next(e for e in PAYLOADS if e[2] == "401911630" and e[3] == fid)[0])
                    for fid in ("5088844", "3075570")}
        routes = {stats_url(bout, fid): p for fid, p in payloads.items()}
        with tempfile.TemporaryDirectory() as tmp:
            store = UfcStore(Path(tmp))
            rows = fightstats.fetch_bout_stats(FixtureFetcher(routes), bout, now="2026-12-01T00:00:00Z")
            self.assertEqual(store.upsert("fight_stats", rows), {"added": 2, "updated": 0, "unchanged": 0, "total": 2})
            later = FixtureFetcher(routes, fetched={u: "2026-10-10T00:00:00Z" for u in routes})
            again = fightstats.fetch_bout_stats(later, bout, now="2026-12-01T00:00:00Z")
            self.assertEqual(store.upsert("fight_stats", again), {"added": 0, "updated": 0, "unchanged": 2, "total": 2})
            self.assertEqual(sorted(store.stats_for()), [("401911630", "3075570"), ("401911630", "5088844")])
            self.assertEqual(store.stats_for()[("401911630", "3075570")]["sig_strikes_landed"], 127)
            self.assertEqual(store.newest("fight_stats"), "2026-09-27T00:00Z")
            # saving then loading loses nothing: ints stay ints, nulls stay null, the lists survive
            self.assertEqual(store.load("fight_stats")[0]["stats_missing"], [])
            self.assertIsInstance(store.load("fight_stats")[0]["control_time_s"], int)


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
    """The cache behaviour fetch_bout_stats relies on, through PoliteFetcher itself."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bout = bout_from_scoreboard(SB_2026, "401911630")
        self.urls = [stats_url(self.bout, "5088844"), stats_url(self.bout, "3075570")]

    def fetcher(self, opener, stamp):
        return http.PoliteFetcher(cache_dir=Path(self.tmp.name), opener=opener, sleep=lambda s: None,
                                  delay_s=0, now_iso=lambda: stamp)

    def test_a_404_is_cached_for_an_old_bout_and_asked_again_for_a_recent_one(self):
        opener = ScriptedOpener({u: [(404, b"")] * 3 for u in self.urls})
        fetcher = self.fetcher(opener, "2020-01-01T00:00:00Z")        # the cached 404 is very old
        self.assertEqual(fightstats.fetch_bout_stats(fetcher, self.bout, now="2026-12-01T00:00:00Z"), [])
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(fightstats.fetch_bout_stats(fetcher, self.bout, now="2026-12-01T00:00:00Z"), [])
        self.assertEqual(len(opener.calls), 2)                        # old bout: the 404 stands, nothing asked
        self.assertEqual(fightstats.fetch_bout_stats(fetcher, self.bout, now="2026-09-28T00:00:00Z"), [])
        self.assertEqual(len(opener.calls), 4)                        # recent bout: the stale 404 is asked again

    def test_posted_statistics_replace_an_earlier_404_for_a_recent_bout(self):
        body = (FIXTURES / "competitor_401911630_5088844_statistics.json").read_bytes()
        other = (FIXTURES / "competitor_401911630_3075570_statistics.json").read_bytes()
        opener = ScriptedOpener({self.urls[0]: [(404, b""), (200, body)], self.urls[1]: [(404, b""), (200, other)]})
        fetcher = self.fetcher(opener, "2020-01-01T00:00:00Z")
        self.assertEqual(fightstats.fetch_bout_stats(fetcher, self.bout, now="2026-09-28T00:00:00Z"), [])
        rows = fightstats.fetch_bout_stats(fetcher, self.bout, now="2026-09-28T00:00:00Z")
        self.assertEqual([r["fighter_id"] for r in rows], ["5088844", "3075570"])
        self.assertEqual(rows[0]["fetched_utc"], "2020-01-01T00:00:00Z")
        self.assertEqual(rows[1]["control_time_s"], 381)


if __name__ == "__main__":
    unittest.main()
