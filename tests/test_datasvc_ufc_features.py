"""src/datasvc/ufc/features.py: leakage-free fighter features.

No network and no real data: every test builds a synthetic store in a temporary
directory through `UfcStore.upsert`, with records shaped exactly as
docs/datasvc/UFC_SCHEMA.md says. `build_store` below is shared by the matchup and
API test modules, so the three modules test one world.

THE SYNTHETIC WORLD
-------------------
Five fighters, twelve completed bouts over 2025-2026, one cancelled bout, and a
scheduled card with odds:

  bout  date        a vs b       winner method          secs  class
  9001  2025-01-18  101 v 103    101    KO_TKO           120  Middleweight
  9002  2025-03-08  102 v 103    102    DEC_UNANIMOUS    900  Middleweight
  9003  2025-04-26  101 v 104    104    SUB              480  Middleweight
  9004  2025-06-14  102 v 105    102    KO_TKO           360  Welterweight
  9005  2025-08-02  103 v 104    103    DEC_SPLIT        900  Middleweight
  9006  2025-09-20  101 v 105    101    DEC_UNANIMOUS    900  Middleweight   (no statistics rows)
  9007  2025-11-08  104 v 105    none   NC                90  Welterweight
  9008  2026-01-24  102 v 104    102    SUB              200  Welterweight
  9009  2026-03-14  101 v 102    102    DEC_UNANIMOUS   1500  Welterweight   (5 rounds)
  9010  2026-05-02  103 v 105    103    DQ               150  Middleweight
  9011  2026-06-13  101 v 104    101    DEC_UNANIMOUS    900  Welterweight
  9012  2026-08-08  102 v 103    103    SUB              720  Welterweight
  9013  2026-04-04  101 v 103    -      (cancelled)
  9101  2026-10-10  101 v 102    scheduled main event, 5 rounds, with odds
  9102  2026-10-10  104 v 105    scheduled prelim, no odds

Fighter 101's four fights with statistics (9001, 9003, 9009, 9011) are built so
every figure is a round number, checked by hand in `HandCheckedRates`. 9003 has no
control time in 101's row, so the control figure has a smaller sample than the rest.
9004 has a row for 102 only and 9005 for 103 only, so "defence needs the opponent's
row" is exercised from both sides.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.datasvc import names
from src.datasvc.ufc import features
from src.datasvc.ufc.store import UfcStore

FETCHED = "2026-10-03T12:00:00Z"
SOURCE = "https://example.test/synthetic"

# The statistic names of the contract (ESPN's camel case), turned into the snake case the
# fight_stats rows use.
ESPN_STATS = (
    "knockDowns totalStrikesAttempted totalStrikesLanded sigStrikesAttempted sigStrikesLanded "
    "sigDistanceHeadStrikesAttempted sigDistanceHeadStrikesLanded sigDistanceBodyStrikesAttempted "
    "sigDistanceBodyStrikesLanded sigDistanceLegStrikesAttempted sigDistanceLegStrikesLanded "
    "sigClinchBodyStrikesAttempted sigClinchBodyStrikesLanded sigClinchHeadStrikesAttempted "
    "sigClinchHeadStrikesLanded sigClinchLegStrikesAttempted sigClinchLegStrikesLanded "
    "sigGroundHeadStrikesAttempted sigGroundHeadStrikesLanded sigGroundBodyStrikesAttempted "
    "sigGroundBodyStrikesLanded sigGroundLegStrikesAttempted sigGroundLegStrikesLanded "
    "takedownsAttempted takedownsLanded takedownsSlams takedownAccuracy targetBreakdownHead "
    "targetBreakdownBody targetBreakdownLeg posBreakdownDistance posBreakdownClinch "
    "posBreakdownGround advances advanceToHalfGuard advanceToSide advanceToMount advanceToBack "
    "reversals submissions slamRate timeInControl wallclock").split()


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


STAT_FIELDS = tuple(snake(n) for n in ESPN_STATS)

FIGHTERS = [
    # id, name, dob, height_in, reach_in, stance, weight_class, (wins, losses, draws)
    ("101", "Alex Archer", "1992-04-10", 72.0, 74.0, "Orthodox", "Welterweight", (12, 4, 0)),
    ("102", "Ben Brawler", "1989-11-02", 70.0, 71.0, "Southpaw", "Welterweight", (9, 3, 1)),
    ("103", "Cal Clinch", "1995-02-14", 73.0, 76.0, "Orthodox", "Middleweight", (8, 2, 0)),
    ("104", "Dan Silva", "1990-07-30", 71.0, 72.0, "Orthodox", "Welterweight", (15, 6, 0)),
    ("105", "Eli Silva", "1998-12-01", 69.0, 70.0, "Switch", "Welterweight", (6, 1, 0)),
]

# bout_id, date_utc, a, b, winner, method, end_round, end_clock_s, weight_class, scheduled_rounds
COMPLETED = [
    ("9001", "2025-01-18T22:00Z", "101", "103", "101", "KO_TKO", 1, 120, "Middleweight", 3),
    ("9002", "2025-03-08T22:00Z", "102", "103", "102", "DEC_UNANIMOUS", 3, 300, "Middleweight", 3),
    ("9003", "2025-04-26T22:00Z", "101", "104", "104", "SUB", 2, 180, "Middleweight", 3),
    ("9004", "2025-06-14T22:00Z", "102", "105", "102", "KO_TKO", 2, 60, "Welterweight", 3),
    ("9005", "2025-08-02T22:00Z", "103", "104", "103", "DEC_SPLIT", 3, 300, "Middleweight", 3),
    ("9006", "2025-09-20T22:00Z", "101", "105", "101", "DEC_UNANIMOUS", 3, 300, "Middleweight", 3),
    ("9007", "2025-11-08T22:00Z", "104", "105", None, "NC", 1, 90, "Welterweight", 3),
    ("9008", "2026-01-24T22:00Z", "102", "104", "102", "SUB", 1, 200, "Welterweight", 3),
    ("9009", "2026-03-14T22:00Z", "101", "102", "102", "DEC_UNANIMOUS", 5, 300, "Welterweight", 5),
    ("9010", "2026-05-02T22:00Z", "103", "105", "103", "DQ", 1, 150, "Middleweight", 3),
    ("9011", "2026-06-13T22:00Z", "101", "104", "101", "DEC_UNANIMOUS", 3, 300, "Welterweight", 3),
    ("9012", "2026-08-08T22:00Z", "102", "103", "103", "SUB", 3, 120, "Welterweight", 3),
]

DETAIL = {"KO_TKO": "Punch", "SUB": "Guillotine Choke"}

# Statistics: (bout_id, fighter_id) -> sparse spec. sig=(landed, attempted), td=(landed,
# attempted), kd, sub (submission attempts), ctrl (seconds in control), pos={position:
# (head, body, leg) landed}.
STATS = {
    ("9001", "101"): dict(sig=(30, 40), kd=2, td=(0, 0), sub=0, ctrl=0,
                          pos={"distance": (20, 4, 1), "clinch": (3, 1, 0), "ground": (1, 0, 0)}),
    ("9001", "103"): dict(sig=(6, 20), kd=0, td=(0, 1), sub=0, ctrl=5),
    ("9002", "102"): dict(sig=(40, 90), kd=0, td=(4, 6), sub=0, ctrl=400),
    ("9002", "103"): dict(sig=(35, 80), kd=0, td=(0, 2), sub=1, ctrl=30),
    ("9003", "101"): dict(sig=(20, 40), kd=0, td=(1, 2), sub=1, ctrl=None,
                          pos={"distance": (12, 2, 0), "clinch": (3, 1, 0), "ground": (2, 0, 0)}),
    ("9003", "104"): dict(sig=(34, 50), kd=1, td=(2, 2), sub=4, ctrl=200),
    ("9004", "102"): dict(sig=(30, 50), kd=1, td=(3, 4), sub=0, ctrl=150),     # 105 has no row
    ("9005", "103"): dict(sig=(50, 100), kd=0, td=(1, 3), sub=0, ctrl=100),    # 104 has no row
    ("9007", "104"): dict(sig=(5, 10), kd=0, td=(0, 0), sub=0, ctrl=0),
    ("9007", "105"): dict(sig=(6, 12), kd=0, td=(0, 1), sub=0, ctrl=0),
    ("9008", "102"): dict(sig=(10, 20), kd=0, td=(2, 2), sub=1, ctrl=60),
    ("9008", "104"): dict(sig=(4, 12), kd=0, td=(0, 1), sub=0, ctrl=0),
    ("9009", "101"): dict(sig=(100, 200), kd=0, td=(2, 8), sub=1, ctrl=324,
                          pos={"distance": (60, 10, 5), "clinch": (10, 5, 0), "ground": (8, 2, 0)}),
    ("9009", "102"): dict(sig=(80, 120), kd=2, td=(3, 6), sub=2, ctrl=400),
    ("9010", "103"): dict(sig=(5, 10), kd=0, td=(0, 0), sub=0, ctrl=0),
    ("9010", "105"): dict(sig=(3, 8), kd=0, td=(0, 0), sub=0, ctrl=0),
    ("9011", "101"): dict(sig=(50, 120), kd=0, td=(3, 5), sub=2, ctrl=180,
                          pos={"distance": (30, 6, 2), "clinch": (4, 2, 0), "ground": (4, 2, 0)}),
    ("9011", "104"): dict(sig=(30, 60), kd=0, td=(0, 1), sub=0, ctrl=20),
    ("9012", "102"): dict(sig=(45, 100), kd=0, td=(0, 3), sub=0, ctrl=50),
    ("9012", "103"): dict(sig=(50, 90), kd=1, td=(2, 2), sub=3, ctrl=120),
}

UFCCOM_101 = {
    "fighter_id": "101", "ufc_slug": "alex-archer", "source_url": "https://example.test/athlete/alex-archer",
    "fetched_utc": FETCHED,
    "sig_strikes_landed_per_min": 9.99, "sig_strike_accuracy": 0.99, "takedown_avg_per_15": 9.9,
    "record_text": "12-4-0 (W-L-D)",
}

FUTURE_START = "2026-10-10T21:00Z"
MAIN_EVENT_START = "2026-10-10T23:00Z"


def _stat_row(bout_id: str, fighter_id: str, opponent_id: str, event_id: str, date_utc: str, spec: dict) -> dict:
    row = {name: None for name in STAT_FIELDS}
    sig = spec.get("sig")
    if sig:
        row["sig_strikes_landed"], row["sig_strikes_attempted"] = sig
    td = spec.get("td")
    if td:
        row["takedowns_landed"], row["takedowns_attempted"] = td
    if spec.get("kd") is not None:
        row["knock_downs"] = spec["kd"]
    if spec.get("sub") is not None:
        row["submissions"] = spec["sub"]
    if spec.get("ctrl") is not None:
        row["time_in_control"] = spec["ctrl"]
    for position, cells in (spec.get("pos") or {}).items():
        for target, value in zip(("head", "body", "leg"), cells):
            row[f"sig_{position}_{target}_strikes_landed"] = value
    row.update({
        "bout_id": bout_id, "fighter_id": fighter_id, "opponent_id": opponent_id, "event_id": event_id,
        "date_utc": date_utc, "stats_complete": spec.get("ctrl", 0) is not None,
        "source_url": SOURCE, "fetched_utc": FETCHED})
    return row


def odds_row(**overrides) -> dict:
    row = {
        "bout_id": "9101", "event_id": "7013", "provider_id": "100", "provider": "DraftKings",
        "a_ml_open": -150, "a_ml_close": None, "a_ml_current": -170,
        "b_ml_open": 130, "b_ml_close": None, "b_ml_current": 145,
        "rounds_total": 4.5, "over_open": -120, "over_close": None, "over_current": -110,
        "under_open": 100, "under_close": None, "under_current": -110,
        "method_odds": {
            "open": {"a": {"ko_tko_dq": 300, "submission": 800, "decision": 350},
                     "b": {"ko_tko_dq": 450, "submission": 900, "decision": 400}},
            "close": None},
        "spread_raw": None, "orientation": "verified", "is_closing": False,
        "source_url": SOURCE, "fetched_utc": FETCHED,
    }
    row.update(overrides)
    return row


def build_store(root: Path, *, before: str = None, odds: list = None, profiles: bool = True) -> UfcStore:
    """The synthetic world as a UfcStore on disk.

    `before` drops every bout (and its statistics) starting at or after that instant,
    which is how the leakage tests build "the world as it was": features computed
    from the full store as of t must equal features computed from this truncated one.
    """
    store = UfcStore(Path(root))
    cut = features.parse_instant(before) if before else None

    def kept(date_utc):
        return cut is None or features.parse_instant(date_utc) < cut

    fighters = []
    for fid, name, dob, h, r, stance, wc, (w, l, d) in FIGHTERS:
        fighters.append({
            "fighter_id": fid, "name": name, "first_name": name.split()[0], "last_name": name.split()[-1],
            "nickname": None, "dob": dob, "height_in": h, "reach_in": r, "weight_lb": None, "stance": stance,
            "weight_class": wc, "citizenship": None, "active": True,
            "record": {"wins": w, "losses": l, "draws": d}, "espn_slug": name.lower().replace(" ", "-"),
            "aliases": [names.normalise(name)], "source_url": SOURCE, "fetched_utc": FETCHED})
    store.upsert("fighters", fighters)

    bouts, events, stats = [], [], []
    for n, (bid, date_utc, a, b, winner, method, rnd, clock, wc, rounds) in enumerate(COMPLETED, 1):
        if not kept(date_utc):
            continue
        eid = f"70{n:02d}"
        bouts.append({
            "bout_id": bid, "event_id": eid, "date_utc": date_utc, "match_number": 1,
            "card_segment": "main", "card_segment_raw": "main", "weight_class": wc,
            "scheduled_rounds": rounds, "description": f"{rounds} Rnd", "status": "final",
            "fighter_a_id": a, "fighter_b_id": b, "winner_id": winner, "result_method": method,
            "result_method_raw": method.lower(), "result_detail": DETAIL.get(method), "result_target": None,
            "end_round": rnd, "end_time_s": float(clock), "fight_time_s": float((rnd - 1) * 300 + clock),
            "status_url": SOURCE, "source_url": SOURCE, "fetched_utc": FETCHED})
        events.append({
            "event_id": eid, "name": f"Synthetic Fight Night {n}", "short_name": f"SFN {n}",
            "date_utc": date_utc, "season": int(date_utc[:4]), "status": "final", "venue_id": None,
            "bout_ids": [bid], "source_url": SOURCE, "fetched_utc": FETCHED})
        for fid, opp in ((a, b), (b, a)):
            spec = STATS.get((bid, fid))
            if spec:
                stats.append(_stat_row(bid, fid, opp, eid, date_utc, spec))

    if kept("2026-04-04T22:00Z"):
        bouts.append({
            "bout_id": "9013", "event_id": "7014", "date_utc": "2026-04-04T22:00Z", "match_number": 1,
            "card_segment": "main", "card_segment_raw": "main", "weight_class": "Middleweight",
            "scheduled_rounds": 3, "description": "3 Rnd", "status": "canceled", "fighter_a_id": "101",
            "fighter_b_id": "103", "winner_id": None, "result_method": None, "result_method_raw": None,
            "result_detail": None, "result_target": None, "end_round": None, "end_time_s": None,
            "fight_time_s": None, "status_url": SOURCE, "source_url": SOURCE, "fetched_utc": FETCHED})
        events.append({
            "event_id": "7014", "name": "Synthetic Cancelled Night", "short_name": "SCN",
            "date_utc": "2026-04-04T22:00Z", "season": 2026, "status": "canceled", "venue_id": None,
            "bout_ids": ["9013"], "source_url": SOURCE, "fetched_utc": FETCHED})

    if kept(FUTURE_START):
        for bid, date_utc, a, b, number, segment, wc, rounds in (
                ("9101", MAIN_EVENT_START, "101", "102", 1, "main", "Welterweight", 5),
                ("9102", FUTURE_START, "104", "105", 5, "prelims", "Welterweight", 3)):
            bouts.append({
                "bout_id": bid, "event_id": "7013", "date_utc": date_utc, "match_number": number,
                "card_segment": segment, "card_segment_raw": segment, "weight_class": wc,
                "scheduled_rounds": rounds, "description": f"{rounds} Rnd", "status": "scheduled",
                "fighter_a_id": a, "fighter_b_id": b, "winner_id": None, "result_method": None,
                "result_method_raw": None, "result_detail": None, "result_target": None, "end_round": None,
                "end_time_s": None, "fight_time_s": None, "status_url": SOURCE, "source_url": SOURCE,
                "fetched_utc": FETCHED})
        events.append({
            "event_id": "7013", "name": "Synthetic Championship Night", "short_name": "SCN 13",
            "date_utc": FUTURE_START, "season": 2026, "status": "scheduled", "venue_id": None,
            "bout_ids": ["9101", "9102"], "source_url": SOURCE, "fetched_utc": FETCHED})

    store.upsert("bouts", bouts)
    store.upsert("events", events)
    store.upsert("fight_stats", stats)
    store.upsert("odds", [odds_row()] if odds is None else odds)
    if profiles:
        store.upsert("ufccom_profiles", [dict(UFCCOM_101)])
    return store


class StoreCase(unittest.TestCase):
    """A synthetic store per test class, built once (the world is read-only)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = build_store(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def f(self, fighter_id, as_of):
        return features.features_as_of(self.store, fighter_id, as_of)

    def fig(self, fighter_id, as_of, name):
        return self.f(fighter_id, as_of)["figures"][name]


AS_OF = "2026-07-01"        # after 9011, before 9012: fighter 101 has five fights


class InstantParsing(unittest.TestCase):
    def test_espn_spelling_and_the_usual_forms(self):
        utc = timezone.utc
        for text, expected in (
                ("2026-09-27T00:00Z", datetime(2026, 9, 27, 0, 0, tzinfo=utc)),
                ("2026-09-27T21:30:15Z", datetime(2026, 9, 27, 21, 30, 15, tzinfo=utc)),
                ("2026-09-27 21:30", datetime(2026, 9, 27, 21, 30, tzinfo=utc)),
                ("2026-09-27T21:30:15.250Z", datetime(2026, 9, 27, 21, 30, 15, 250000, tzinfo=utc)),
                ("2026-06-13T18:00-04:00", datetime(2026, 6, 13, 22, 0, tzinfo=utc)),
                ("2026-06-14T03:30+0530", datetime(2026, 6, 13, 22, 0, tzinfo=utc))):
            self.assertEqual(features.parse_instant(text), expected, text)

    def test_a_bare_date_is_the_start_of_that_day_in_utc(self):
        self.assertEqual(features.parse_instant("2026-06-13"), datetime(2026, 6, 13, tzinfo=timezone.utc))
        self.assertEqual(features.parse_instant(date(2026, 6, 13)), datetime(2026, 6, 13, tzinfo=timezone.utc))

    def test_a_naive_datetime_is_utc_and_an_aware_one_is_converted(self):
        self.assertEqual(features.parse_instant(datetime(2026, 6, 13, 22, 0)),
                         datetime(2026, 6, 13, 22, 0, tzinfo=timezone.utc))
        eastern = timezone(timedelta(hours=-4))
        self.assertEqual(features.parse_instant(datetime(2026, 6, 13, 18, 0, tzinfo=eastern)),
                         datetime(2026, 6, 13, 22, 0, tzinfo=timezone.utc))

    def test_garbage_is_a_value_error(self):
        for bad in ("tomorrow", "2026-13-01", "2026-02-30", "2026-06-13T25:00Z", "", 20260613, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                features.parse_instant(bad)


class LeakageRule(StoreCase):
    """The most important property of the module."""

    def test_a_bout_on_the_as_of_date_does_not_count_and_the_next_day_it_does(self):
        # 9011 starts 2026-06-13T22:00Z. A bare date is the start of the day.
        on_the_day = self.f("101", "2026-06-13")
        self.assertEqual(on_the_day["record"]["fights"], 4)
        self.assertEqual(on_the_day["record"]["last_fight_utc"], "2026-03-14T22:00:00Z")
        self.assertEqual(self.f("101", "2026-06-14")["record"]["fights"], 5)

    def test_a_bout_starting_at_the_as_of_instant_does_not_count(self):
        self.assertEqual(self.f("101", "2026-06-13T22:00Z")["record"]["fights"], 4)
        self.assertEqual(self.f("101", "2026-06-13T22:00:01Z")["record"]["fights"], 5)

    def test_later_bouts_never_count_however_late_the_as_of(self):
        self.assertEqual(self.f("102", "2026-08-01")["record"]["fights"], 4)
        self.assertEqual(self.f("102", "2026-08-09")["record"]["fights"], 5)
        # the scheduled bout has no result, so it never counts even long after its date
        self.assertEqual(self.f("102", "2031-01-01")["record"]["fights"], 5)

    def test_the_as_of_can_be_given_as_a_date_or_datetime_object(self):
        self.assertEqual(self.f("101", date(2026, 6, 13))["record"]["fights"], 4)
        self.assertEqual(self.f("101", datetime(2026, 6, 14, tzinfo=timezone.utc))["record"]["fights"], 5)

    def test_features_equal_those_of_a_world_that_ends_before_the_as_of(self):
        """Metamorphic proof: delete every bout at or after t and nothing changes.

        If any figure (the strength-of-schedule one included) peeked at a later bout,
        features from the full world and from the truncated one would differ. Tried at
        every bout start, the second before it, and a day after the last result.
        """
        starts = sorted({b[1] for b in COMPLETED} | {"2026-04-04T22:00Z", FUTURE_START})
        cut_points = set()
        for s in starts:
            inst = features.parse_instant(s)
            cut_points.update({s, features.iso_utc(inst - timedelta(seconds=1)), features.iso_utc(inst + timedelta(days=1))})
        for cut in sorted(cut_points):
            with tempfile.TemporaryDirectory() as tmp:
                past = build_store(Path(tmp), before=cut)
                for fid, *_ in FIGHTERS:
                    full = features.features_as_of(self.store, fid, cut)
                    truncated = features.features_as_of(past, fid, cut)
                    self.assertEqual(full, truncated, f"fighter {fid} as of {cut} saw a bout from its future")

    def test_strength_of_schedule_uses_the_opponents_record_at_the_time_of_the_fight(self):
        sos = self.f("101", AS_OF)["strength_of_schedule_by_fight"]
        against_105 = [d for d in sos if d["bout_id"] == "9006"][0]
        # 105 had lost once (9004) before 9006; later it was NC'd and lost again, and is 0-3 now.
        self.assertEqual(against_105["opponent_record_then"], {"wins": 0, "losses": 1, "draws": 0, "no_contests": 0})
        later = self.f("105", "2026-10-10")["record"]
        self.assertEqual((later["wins"], later["losses"], later["no_contests"]), (0, 3, 1))
        # and the same entry is unchanged by a later as_of
        again = [d for d in self.f("101", "2026-10-10")["strength_of_schedule_by_fight"] if d["bout_id"] == "9006"][0]
        self.assertEqual(again, against_105)

    def test_the_opponents_record_stops_before_the_fight_itself(self):
        """102 beat 105 in 9004 and 101 beat 105 in 9006; neither win counts when measuring that same fight."""
        sos = {d["bout_id"]: d for d in self.f("105", "2026-10-10")["strength_of_schedule_by_fight"]}
        self.assertEqual(sos["9004"]["opponent_record_then"]["wins"], 1)       # 102's 9002 win only, not 9004
        self.assertEqual(sos["9004"]["opponent_win_rate"], 1.0)
        # 101 before 9006: won 9001, lost 9003. Not the 9006 win itself, nor 9009/9011 which came later.
        self.assertEqual(sos["9006"]["opponent_record_then"], {"wins": 1, "losses": 1, "draws": 0, "no_contests": 0})

    def test_ufccom_career_figures_never_reach_any_figure(self):
        baseline = self.f("101", AS_OF)
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp))
            changed = dict(UFCCOM_101, sig_strikes_landed_per_min=0.01, sig_strike_accuracy=0.01)
            store.upsert("ufccom_profiles", [changed])
            other = features.features_as_of(store, "101", AS_OF)
        self.assertEqual(other["figures"], baseline["figures"])
        self.assertNotEqual(other["ufccom_career"]["figures"], baseline["ufccom_career"]["figures"])


class HandCheckedRates(StoreCase):
    """Fighter 101 as of 2026-07-01: five fights, four with statistics (9006 has none).

    The four are 9001 (120 s), 9003 (480 s), 9009 (1500 s) and 9011 (900 s): 3000 s,
    exactly 50 minutes. Every expected number below is arithmetic done by hand on the
    STATS table, not a call into the code under test.
    """

    def test_experience_and_results(self):
        r = self.f("101", AS_OF)
        self.assertEqual(r["record"]["fights"], 5)
        self.assertEqual((r["record"]["wins"], r["record"]["losses"], r["record"]["draws"],
                          r["record"]["no_contests"]), (3, 2, 0, 0))
        self.assertEqual(r["record"]["wins_by_method"], {"ko_tko": 1, "submission": 0, "decision": 2,
                                                          "dq": 0, "other": 0, "unknown": 0})
        self.assertEqual(r["record"]["losses_by_method"], {"ko_tko": 0, "submission": 1, "decision": 1,
                                                            "dq": 0, "other": 0, "unknown": 0})
        figs = r["figures"]
        self.assertEqual(figs["win_rate"]["value"], 0.6)                       # 3 / 5
        self.assertEqual(figs["finish_rate"]["value"], 0.2)                    # 1 finishing win / 5
        self.assertEqual(figs["been_finished_rate"]["value"], 0.2)             # 1 finishing loss / 5
        self.assertAlmostEqual(figs["finish_share_of_wins"]["value"], 1 / 3, places=4)
        self.assertEqual(figs["finished_share_of_losses"]["value"], 0.5)       # 1 of 2
        self.assertEqual(figs["distance_rate"]["value"], 0.6)                  # 9006, 9009, 9011
        self.assertEqual(figs["average_fight_time_s"]["value"], 780)           # (120+480+900+1500+900)/5
        self.assertEqual(figs["ufc_fights"]["value"], 5)
        self.assertEqual(figs["ufc_fights"]["minutes"], 65.0)

    def test_striking_rates_and_their_samples(self):
        figs = self.f("101", AS_OF)["figures"]
        landed = figs["sig_strikes_landed_per_min"]       # (30+20+100+50) / 50 min
        self.assertEqual((landed["value"], landed["fights"], landed["minutes"]), (4.0, 4, 50.0))
        self.assertEqual((landed["num"], landed["den"]), (200, 50))
        absorbed = figs["sig_strikes_absorbed_per_min"]   # (6+34+80+30) / 50 min
        self.assertEqual((absorbed["value"], absorbed["fights"], absorbed["minutes"]), (3.0, 4, 50.0))
        self.assertEqual(figs["sig_strike_accuracy"]["value"], 0.5)           # 200 / 400
        self.assertEqual(figs["sig_strike_defence"]["value"], 0.4)            # 1 - 150/250
        self.assertEqual((figs["sig_strike_defence"]["num"], figs["sig_strike_defence"]["den"]), (150, 250))

    def test_position_and_target_shares_come_from_the_landed_counts(self):
        figs = self.f("101", AS_OF)["figures"]
        # distance 25+14+75+38, clinch 4+4+15+6, ground 1+2+10+6, out of 200 landed
        self.assertEqual(figs["sig_strike_share_distance"]["value"], 0.76)
        self.assertEqual(figs["sig_strike_share_clinch"]["value"], 0.145)
        self.assertEqual(figs["sig_strike_share_ground"]["value"], 0.095)
        # head 157, body 35, leg 8 out of 200
        self.assertEqual(figs["sig_strike_share_head"]["value"], 0.785)
        self.assertEqual(figs["sig_strike_share_body"]["value"], 0.175)
        self.assertEqual(figs["sig_strike_share_leg"]["value"], 0.04)
        for group in (("distance", "clinch", "ground"), ("head", "body", "leg")):
            self.assertAlmostEqual(sum(figs[f"sig_strike_share_{k}"]["value"] for k in group), 1.0, places=9)
        self.assertEqual(figs["sig_strike_share_distance"]["fights"], 4)

    def test_grappling_rates(self):
        figs = self.f("101", AS_OF)["figures"]
        self.assertEqual(figs["takedowns_landed_per_15"]["value"], 1.8)       # 6 / 50 * 15
        self.assertEqual(figs["takedown_accuracy"]["value"], 0.4)             # 6 / 15
        self.assertEqual(figs["takedown_defence"]["value"], 0.5)              # 1 - 5/10
        self.assertEqual(figs["submission_attempts_per_15"]["value"], 1.2)    # 4 / 50 * 15
        self.assertEqual(figs["knockdowns_landed_per_15"]["value"], 0.6)      # 2 / 50 * 15
        self.assertEqual(figs["knockdowns_suffered_per_15"]["value"], 0.9)    # 3 / 50 * 15

    def test_control_time_has_a_smaller_sample_because_one_row_lacks_it(self):
        ctrl = self.fig("101", AS_OF, "control_time_share")
        # 9001 (0 s), 9009 (324 s), 9011 (180 s) over 120 + 1500 + 900 = 2520 s; 9003 has no control time
        self.assertEqual((ctrl["value"], ctrl["fights"], ctrl["minutes"]), (0.2, 3, 42.0))
        self.assertEqual((ctrl["num"], ctrl["den"]), (504, 2520))
        self.assertEqual(self.fig("101", AS_OF, "sig_strikes_landed_per_min")["fights"], 4)

    def test_a_fight_with_no_statistics_at_all_is_named_in_the_sample(self):
        sample = self.f("101", AS_OF)["sample"]
        self.assertEqual(sample["fights"], 5)
        self.assertEqual(sample["fights_with_own_stats"], 4)
        self.assertEqual(sample["fights_without_any_stats"], ["9006"])

    def test_figures_use_summed_numerators_over_summed_minutes_not_an_average_of_rates(self):
        """9001 alone is 15.0 strikes/min and 9009 alone is 4.0; the career rate is 4.0, not 9.5."""
        figs = self.f("101", AS_OF)["figures"]
        self.assertEqual(figs["sig_strikes_landed_per_min"]["value"], 4.0)

    def test_streak_and_last_three(self):
        r = self.f("101", AS_OF)
        self.assertEqual(r["streak"], {"type": "win", "length": 1})
        self.assertEqual([(x["bout_id"], x["result"], x["method"]) for x in r["last_three"]],
                         [("9011", "win", "DEC_UNANIMOUS"), ("9009", "loss", "DEC_UNANIMOUS"),
                          ("9006", "win", "DEC_UNANIMOUS")])
        self.assertEqual(r["last_three"][0]["opponent_name"], "Dan Silva")

    def test_a_streak_counts_consecutive_matching_results_and_a_no_contest_breaks_it(self):
        self.assertEqual(self.f("102", "2026-03-01")["streak"], {"type": "win", "length": 3})      # 9002, 9004, 9008
        self.assertEqual(self.f("105", "2026-10-10")["streak"], {"type": "loss", "length": 1})     # NC, then DQ loss
        self.assertEqual(self.f("104", "2025-12-01")["streak"], {"type": "no_contest", "length": 1})

    def test_days_since_the_last_fight(self):
        self.assertEqual(self.fig("101", AS_OF, "days_since_last_fight")["value"], 17)   # 2026-06-13T22:00 -> 07-01 00:00
        self.assertEqual(self.fig("101", "2026-06-14", "days_since_last_fight")["value"], 0)

    def test_age_height_reach_and_stance(self):
        r = self.f("101", AS_OF)
        # 2026-07-01 minus 1992-04-10 is 12,500 days: 12,500 / 365.2425 = 34.22 years
        self.assertEqual(r["figures"]["age_years"]["value"], 34.22)
        self.assertEqual(r["figures"]["height_in"]["value"], 72.0)
        self.assertEqual(r["figures"]["reach_in"]["value"], 74.0)
        self.assertEqual(r["physical"]["stance"], "Orthodox")

    def test_weight_classes_and_the_most_recent_change(self):
        wc = self.f("101", AS_OF)["weight_classes"]
        self.assertEqual(wc["current"], "Welterweight")
        self.assertEqual({e["weight_class"]: e["fights"] for e in wc["fought"]}, {"Middleweight": 3, "Welterweight": 2})
        self.assertEqual(wc["most_recent_change"], {
            "from": "Middleweight", "to": "Welterweight", "date_utc": "2026-03-14T22:00:00Z",
            "bout_id": "9009", "direction": "down"})
        before_the_move = self.f("101", "2026-02-01")["weight_classes"]
        self.assertEqual(before_the_move["current"], "Middleweight")
        self.assertIsNone(before_the_move["most_recent_change"])

    def test_strength_of_schedule(self):
        sos = self.fig("101", AS_OF, "strength_of_schedule")
        # opponents' win rate at the time: 103 and 104 had no earlier fight (no rate), 105 was 0-1 -> 0.0,
        # 102 was 3-0 -> 1.0, 104 was 1-2 with one NC -> 1/3.  mean(0.0, 1.0, 1/3)
        self.assertAlmostEqual(sos["value"], 4 / 9, places=4)
        self.assertEqual(sos["fights"], 3)
        self.assertEqual(sos["opponents_without_history"], 2)
        by_fight = {d["bout_id"]: d for d in self.f("101", AS_OF)["strength_of_schedule_by_fight"]}
        self.assertIsNone(by_fight["9001"]["opponent_win_rate"])
        self.assertIsNone(by_fight["9003"]["opponent_win_rate"])
        self.assertEqual(by_fight["9006"]["opponent_win_rate"], 0.0)
        self.assertEqual(by_fight["9009"]["opponent_win_rate"], 1.0)
        self.assertEqual(by_fight["9011"]["opponent_record_then"], {"wins": 1, "losses": 2, "draws": 0, "no_contests": 1})
        self.assertAlmostEqual(by_fight["9011"]["opponent_win_rate"], 1 / 3, places=4)

    def test_output_is_plain_json_and_deterministic(self):
        r = self.f("101", AS_OF)
        self.assertEqual(json.loads(json.dumps(r)), r)
        self.assertEqual(self.f("101", AS_OF), r)


class DefenceNeedsTheOpponentsRow(StoreCase):
    def test_landed_and_absorbed_have_different_samples_when_one_row_is_missing(self):
        """9005 has a row for 103 only. For 104 it adds to what he absorbed, not to what he landed."""
        r = self.f("104", "2026-10-10")
        landed, absorbed = r["figures"]["sig_strikes_landed_per_min"], r["figures"]["sig_strikes_absorbed_per_min"]
        # landed: 9003 (34), 9007 (5), 9008 (4), 9011 (30) over 480+90+200+900 = 1670 s
        self.assertEqual((landed["fights"], landed["num"]), (4, 73))
        self.assertAlmostEqual(landed["minutes"], 27.83, places=2)
        # absorbed: 9003 (20), 9005 (50), 9007 (6), 9008 (10), 9011 (50) over 2570 s
        self.assertEqual((absorbed["fights"], absorbed["num"]), (5, 136))
        self.assertAlmostEqual(absorbed["value"], 136 / (2570 / 60), places=4)

    def test_the_other_side_of_the_same_bout_is_the_mirror_image(self):
        """103 has the row in 9005; it adds to what 103 landed and not to what he absorbed."""
        r = self.f("103", "2026-10-10")
        landed, absorbed = r["figures"]["sig_strikes_landed_per_min"], r["figures"]["sig_strikes_absorbed_per_min"]
        # fights 9001, 9002, 9005, 9010, 9012 have own rows; 9005 lacks 104's row
        self.assertEqual(landed["fights"], 5)
        self.assertEqual(absorbed["fights"], 4)

    def test_defence_is_missing_not_guessed_when_no_opponent_row_exists(self):
        """102 as of 2025-07-01 has 9002 (opponent row exists) and 9004 (105 has no row)."""
        early = self.f("102", "2025-07-01")["figures"]["sig_strike_defence"]
        self.assertEqual((early["fights"], early["num"], early["den"]), (1, 35, 80))     # only 9002
        self.assertAlmostEqual(early["value"], 1 - 35 / 80, places=4)

    def test_a_fighter_whose_every_opponent_row_is_missing_has_no_defence(self):
        """105 as of 2025-07-01: one fight (9004) with no row of its own; 102's row exists."""
        r = self.f("105", "2025-07-01")
        self.assertIsNone(r["figures"]["sig_strikes_landed_per_min"]["value"])
        self.assertIn("none of the 1 fight(s)", r["figures"]["sig_strikes_landed_per_min"]["reason"])
        absorbed = r["figures"]["sig_strikes_absorbed_per_min"]
        self.assertEqual((absorbed["value"], absorbed["fights"]), (5.0, 1))             # 30 landed in 6 minutes
        # defence needs 102's attempted count too, and 102's row has it
        self.assertAlmostEqual(r["figures"]["sig_strike_defence"]["value"], 1 - 30 / 50, places=4)
        missing = {m["figure"] for m in r["missing"]}
        self.assertIn("sig_strikes_landed_per_min", missing)
        self.assertIn("sig_strike_accuracy", missing)
        self.assertNotIn("sig_strikes_absorbed_per_min", missing)

    def test_opponents_with_no_attempts_leave_defence_undefined_with_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp))
            rows = [r for r in store.fight_stats if (r["bout_id"], r["fighter_id"]) in {("9001", "103")}]
            for r in rows:
                r["takedowns_attempted"] = 0
                r["takedowns_landed"] = 0
            store.upsert("fight_stats", rows)
            r = features.features_as_of(store, "101", "2025-02-01")
        fig = r["figures"]["takedown_defence"]
        self.assertIsNone(fig["value"])
        self.assertIn("opponents attempted no takedowns", fig["reason"])
        self.assertIn("takedown_defence", {m["figure"] for m in r["missing"]})


class MissingData(StoreCase):
    def test_a_fighter_with_no_fights_yet_has_every_statistic_missing_and_says_why(self):
        r = self.f("101", "2025-01-01")
        self.assertEqual(r["record"]["fights"], 0)
        self.assertEqual(r["figures"]["ufc_fights"]["value"], 0)          # zero fights is a value, not a gap
        missing = {m["figure"]: m["reason"] for m in r["missing"]}
        self.assertNotIn("ufc_fights", missing)
        for name in ("win_rate", "finish_rate", "sig_strikes_landed_per_min", "sig_strike_defence",
                     "takedown_accuracy", "control_time_share", "strength_of_schedule",
                     "days_since_last_fight", "average_fight_time_s", "sig_strike_share_distance"):
            self.assertIn(name, missing)
            self.assertIn("no UFC fights in the store before as_of", missing[name])
        self.assertEqual(r["streak"], {"type": None, "length": 0})
        self.assertEqual(r["last_three"], [])
        self.assertIsNone(r["weight_classes"]["current"])
        # facts that do not depend on fights are still there
        self.assertEqual(r["figures"]["height_in"]["value"], 72.0)

    def test_every_none_figure_is_listed_and_every_listed_figure_is_none(self):
        for fid in ("101", "102", "103", "104", "105"):
            for as_of in ("2025-01-01", "2025-07-01", "2026-10-10"):
                r = self.f(fid, as_of)
                none_figures = {k for k, v in r["figures"].items() if v["value"] is None}
                listed = {m["figure"] for m in r["missing"]}
                self.assertEqual(none_figures, listed & set(r["figures"]), (fid, as_of))
                for m in r["missing"]:
                    self.assertTrue(m["reason"], (fid, as_of, m))

    def test_a_cancelled_bout_before_the_as_of_is_reported_not_counted(self):
        r = self.f("101", AS_OF)
        self.assertEqual(r["record"]["fights"], 5)
        self.assertEqual(r["sample"]["skipped"]["started_without_result"],
                         [{"bout_id": "9013", "date_utc": "2026-04-04T22:00Z", "status": "canceled"}])

    def test_a_career_record_and_ufccom_profile_are_labelled_and_missing_ones_are_listed(self):
        r = self.f("101", AS_OF)
        career = r["career_record_incl_non_ufc"]
        self.assertEqual((career["wins"], career["losses"], career["draws"]), (12, 4, 0))
        self.assertTrue(career["includes_non_ufc"])
        self.assertFalse(career["as_of_safe"])
        ufccom = r["ufccom_career"]
        self.assertEqual(ufccom["label"], "UFC.com career figures")
        self.assertFalse(ufccom["as_of_safe"])
        self.assertEqual(ufccom["ufc_slug"], "alex-archer")
        self.assertEqual(ufccom["figures"]["sig_strikes_landed_per_min"], 9.99)
        self.assertNotIn("fighter_id", ufccom["figures"])
        no_profile = self.f("102", AS_OF)
        self.assertIsNone(no_profile["ufccom_career"])
        self.assertIn("ufccom_career", {m["figure"] for m in no_profile["missing"]})

    def test_a_fighter_who_is_only_in_the_bouts_still_gets_bout_figures(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp))
            store.write("fighters", [f for f in store.fighters if f["fighter_id"] != "101"])
            r = features.features_as_of(store, "101", AS_OF)
        self.assertEqual(r["record"]["fights"], 5)
        self.assertIsNone(r["name"])
        for key in ("age_years", "height_in", "reach_in"):
            self.assertIsNone(r["figures"][key]["value"])
            self.assertIn("not in the fighters file", r["figures"][key]["reason"])
        self.assertIsNone(r["career_record_incl_non_ufc"])

    def test_a_missing_date_of_birth_is_a_missing_age_not_a_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp))
            fighter = dict(store.fighter_by_id()["101"], dob=None)
            store.upsert("fighters", [fighter])
            r = features.features_as_of(store, "101", AS_OF)
        self.assertIsNone(r["figures"]["age_years"]["value"])
        self.assertIn("no date of birth", r["figures"]["age_years"]["reason"])

    def test_an_unknown_fighter_is_refused_and_a_bad_as_of_is_a_value_error(self):
        with self.assertRaises(features.UnknownFighter):
            self.f("999", AS_OF)
        with self.assertRaises(ValueError):
            self.f("101", "next tuesday")
        with self.assertRaises(ValueError):
            self.f("101", None)


class ResultClassification(unittest.TestCase):
    """Edge cases of what counts as a result, on tiny stores."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = UfcStore(Path(self.tmp.name))

    def put(self, bouts, stats=()):
        base = {"event_id": "e", "match_number": 1, "status": "final", "weight_class": "Lightweight",
                "scheduled_rounds": 3, "winner_id": None, "result_method": None, "end_round": 3,
                "end_time_s": 300.0, "fight_time_s": 900.0, "source_url": SOURCE, "fetched_utc": FETCHED}
        self.store.upsert("bouts", [dict(base, **b) for b in bouts])
        self.store.upsert("fight_stats", list(stats))

    def feats(self, fid="1", as_of="2027-01-01"):
        return features.features_as_of(self.store, fid, as_of)

    def test_a_draw_is_a_result_with_no_winner(self):
        self.put([
            {"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
             "result_method": "DRAW"},
            {"bout_id": "b2", "date_utc": "2026-02-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "3",
             "winner_id": "1", "result_method": "KO_TKO", "fight_time_s": 100.0}])
        r = self.feats()
        self.assertEqual((r["record"]["wins"], r["record"]["draws"], r["record"]["fights"]), (1, 1, 2))
        self.assertEqual(r["figures"]["win_rate"]["value"], 0.5)
        self.assertEqual(r["figures"]["distance_rate"]["value"], 0.5)     # the draw went to the scorecards
        self.assertEqual(r["figures"]["finish_rate"]["value"], 0.5)

    def test_a_no_contest_counts_as_a_fight_but_not_in_the_win_rate_or_finish_rates(self):
        self.put([
            {"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
             "result_method": "NC", "fight_time_s": 60.0},
            {"bout_id": "b2", "date_utc": "2026-02-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "3",
             "winner_id": "3", "result_method": "KO_TKO", "fight_time_s": 100.0}])
        r = self.feats()
        self.assertEqual((r["record"]["fights"], r["record"]["no_contests"], r["record"]["losses"]), (2, 1, 1))
        self.assertEqual(r["figures"]["win_rate"]["value"], 0.0)
        self.assertEqual(r["figures"]["been_finished_rate"]["value"], 1.0)     # 1 finish in the 1 decided fight
        self.assertEqual(r["figures"]["been_finished_rate"]["fights"], 1)

    def test_a_final_bout_with_no_winner_and_no_known_result_is_left_out_and_reported(self):
        self.put([
            {"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2"},
            {"bout_id": "b2", "date_utc": "2026-02-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "3",
             "winner_id": "1", "result_method": "SUB", "fight_time_s": 100.0}])
        r = self.feats()
        self.assertEqual(r["record"]["fights"], 1)
        self.assertEqual(r["sample"]["skipped"]["started_without_result"][0]["bout_id"], "b1")
        self.assertEqual(r["sample"]["skipped"]["started_without_result"][0]["status"], "final")

    def test_contradictory_results_are_left_out_rather_than_read_one_way(self):
        self.put([
            {"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
             "winner_id": "9", "result_method": "KO_TKO"},              # winner is neither fighter
            {"bout_id": "b2", "date_utc": "2026-02-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "3",
             "winner_id": "1", "result_method": "NC"}])                 # a winner in a no contest
        self.assertEqual(self.feats()["record"]["fights"], 0)

    def test_a_bout_with_no_start_time_is_never_assumed_to_be_in_the_past(self):
        self.put([{"bout_id": "b1", "date_utc": None, "fighter_a_id": "1", "fighter_b_id": "2",
                   "winner_id": "1", "result_method": "KO_TKO"}])
        r = self.feats()
        self.assertEqual(r["record"]["fights"], 0)
        self.assertEqual(r["sample"]["skipped"]["no_start_time"], ["b1"])

    def test_a_win_with_no_recorded_method_counts_as_a_win_and_drops_out_of_method_figures(self):
        self.put([
            {"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
             "winner_id": "1", "result_method": None},
            {"bout_id": "b2", "date_utc": "2026-02-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "3",
             "winner_id": "1", "result_method": "KO_TKO", "fight_time_s": 100.0}])
        r = self.feats()
        self.assertEqual(r["record"]["wins"], 2)
        self.assertEqual(r["record"]["wins_by_method"]["unknown"], 1)
        self.assertEqual(r["figures"]["finish_rate"]["value"], 1.0)
        self.assertEqual(r["figures"]["finish_rate"]["fights"], 1)

    def test_unknown_fight_time_drops_the_fight_from_rates_but_not_from_the_record(self):
        self.put([{"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
                   "winner_id": "1", "result_method": "DEC_UNANIMOUS", "fight_time_s": None}],
                 stats=[{"bout_id": "b1", "fighter_id": "1", "opponent_id": "2", "sig_strikes_landed": 50,
                         "sig_strikes_attempted": 100}])
        r = self.feats()
        self.assertEqual(r["record"]["fights"], 1)
        self.assertIsNone(r["figures"]["sig_strikes_landed_per_min"]["value"])
        self.assertEqual(r["figures"]["sig_strike_accuracy"]["value"], 0.5)     # a ratio needs no clock
        self.assertIsNone(r["figures"]["average_fight_time_s"]["value"])

    def test_a_statistics_row_that_is_all_nulls_is_not_statistics(self):
        """ESPN had no numbers for the bout, so ingestion may write a row of nulls: the bout is not covered."""
        bout = {"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
                "winner_id": "1", "result_method": "DEC_UNANIMOUS"}
        empty = {"sig_strikes_landed": None, "sig_strikes_attempted": None, "knock_downs": None,
                 "takedowns_landed": None, "stats_complete": False, "date_utc": "2026-01-01T00:00Z",
                 "source_url": SOURCE, "fetched_utc": FETCHED, "event_id": "e"}
        self.put([bout], stats=[dict(empty, bout_id="b1", fighter_id="1", opponent_id="2"),
                                dict(empty, bout_id="b1", fighter_id="2", opponent_id="1")])
        r = self.feats()
        self.assertEqual((r["sample"]["fights_with_own_stats"], r["sample"]["fights_with_opponent_stats"]), (0, 0))
        self.assertEqual(r["sample"]["fights_without_any_stats"], ["b1"])
        self.assertIsNone(r["figures"]["sig_strikes_landed_per_min"]["value"])
        # one real number makes it statistics
        self.store.upsert("fight_stats", [dict(empty, bout_id="b1", fighter_id="1", opponent_id="2",
                                               sig_strikes_landed=10, sig_strikes_attempted=20)])
        r = self.feats()
        self.assertEqual((r["sample"]["fights_with_own_stats"], r["sample"]["fights_with_opponent_stats"]), (1, 0))
        self.assertEqual(r["sample"]["fights_without_any_stats"], [])
        self.assertEqual(r["figures"]["sig_strike_accuracy"]["value"], 0.5)

    def test_a_fight_can_be_put_in_a_set(self):
        self.put([{"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
                   "winner_id": "1", "result_method": "KO_TKO"}])
        fights = features.completed_fights(self.store, "1", "2027-01-01")
        self.assertEqual(len({*fights}), 1)

    def test_statistics_in_espn_spelling_or_with_bad_values_are_read_safely(self):
        self.put([{"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
                   "winner_id": "1", "result_method": "DEC_UNANIMOUS", "fight_time_s": 900.0}],
                 stats=[
                     {"bout_id": "b1", "fighter_id": "1", "opponent_id": "2",
                      "sigStrikesLanded": 30, "sigStrikesAttempted": 60, "knockdowns": 1,
                      "takedownsLanded": True, "takedownsAttempted": "5", "submissions": -1}])
        r = self.feats()["figures"]
        self.assertEqual(r["sig_strikes_landed_per_min"]["value"], 2.0)       # 30 in 15 minutes, camel case
        self.assertEqual(r["knockdowns_landed_per_15"]["value"], 1.0)         # the squashed spelling
        self.assertIsNone(r["takedowns_landed_per_15"]["value"])              # bool is not a count
        self.assertIsNone(r["takedown_accuracy"]["value"])                    # a string is not a count
        self.assertIsNone(r["submission_attempts_per_15"]["value"])           # a negative is not a count

    def test_a_weight_class_change_to_a_class_not_in_the_table_has_unknown_direction(self):
        self.put([
            {"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
             "winner_id": "1", "result_method": "KO_TKO", "weight_class": "Lightweight"},
            {"bout_id": "b2", "date_utc": "2026-02-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "3",
             "winner_id": "1", "result_method": "KO_TKO", "weight_class": "Catchweight"},
            {"bout_id": "b3", "date_utc": "2026-03-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "4",
             "winner_id": "1", "result_method": "KO_TKO", "weight_class": None}])
        wc = self.feats()["weight_classes"]
        self.assertEqual(wc["most_recent_change"]["direction"], "unknown")
        self.assertEqual(wc["fights_without_weight_class"], 1)

    def test_a_womens_class_change_has_a_direction(self):
        self.put([
            {"bout_id": "b1", "date_utc": "2026-01-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "2",
             "winner_id": "1", "result_method": "KO_TKO", "weight_class": "Women's Flyweight"},
            {"bout_id": "b2", "date_utc": "2026-02-01T00:00Z", "fighter_a_id": "1", "fighter_b_id": "3",
             "winner_id": "1", "result_method": "KO_TKO", "weight_class": "Women's Bantamweight"}])
        self.assertEqual(self.feats()["weight_classes"]["most_recent_change"]["direction"], "up")


if __name__ == "__main__":
    unittest.main()
