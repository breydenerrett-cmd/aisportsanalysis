"""The written read of one game (src/analysis/matchup_read.py).

Written 2026-10-03 after the owner called the matchup analysis "barely
analytical, just a couple of numbers". The read does the weighing the tables
left to the reader, in words, from the game payload alone.

THE CONTRACT THESE TESTS HOLD
-----------------------------
  * every factor has a unit test, including its thin-sample and missing-data
    paths, because a factor that silently uses stale or thin data is the
    failure the read exists to avoid;
  * every `evidence` path resolves in the payload, and a non-derived value
    equals what the payload holds at that path (so a sentence cannot cite a
    number the page does not carry);
  * the read never raises, never mutates the payload, and is deterministic;
  * the wording rules hold on every string the read emits: no em dashes, no
    "lock", no guarantee, no profit or edge claim, no win probability, no
    advice;
  * a golden test on frozen copies of 2026-10-03's four real payloads, so any
    change to wording or logic is a fixture diff a person has to accept
    (python3 scripts/regen_matchup_read_fixtures.py).
"""

from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from src.analysis import matchup_read as mr

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = [("CWS", "CLE"), ("ATL", "LAD"), ("NYY", "TB"), ("SD", "MIL")]


# ---------------------------------------------------------------------------
# A synthetic payload builder. `rich()` fires every factor; each test then
# changes only the thing it is about.
# ---------------------------------------------------------------------------

def starter(prefix, *, era=3.50, fip=3.50, whip=1.15, kbb=0.15, innings=150.0,
            hr9=1.0, ip=5.8, recent_era=3.50, recent_ip=5.8, recent_starts=3,
            known=True, thin=False):
    if not known:
        return {f"{prefix}_sp_known": False, f"{prefix}_sp_thin": True,
                f"{prefix}_sp_era": None, f"{prefix}_sp_fip": None,
                f"{prefix}_sp_innings": 0, f"{prefix}_sp_recent_starts": 0}
    return {f"{prefix}_sp_known": True, f"{prefix}_sp_thin": thin,
            f"{prefix}_sp_era": era, f"{prefix}_sp_fip": fip,
            f"{prefix}_sp_whip": whip, f"{prefix}_sp_k_bb_pct": kbb,
            f"{prefix}_sp_innings": innings, f"{prefix}_sp_hr9": hr9,
            f"{prefix}_sp_ip_per_start": ip, f"{prefix}_sp_recent_era": recent_era,
            f"{prefix}_sp_recent_ip_per_start": recent_ip,
            f"{prefix}_sp_recent_starts": recent_starts, f"{prefix}_sp_days_rest": 5,
            f"{prefix}_sp_starts": 25}


def batters(base_id, names):
    return [{"name": n, "order": i + 1, "person_id": base_id + i, "position": "X"}
            for i, n in enumerate(names)]


def vs_pitch(base_id, names, wobas, pa=60.0):
    out = {}
    for ptype, pname in (("FF", "4-Seam Fastball"), ("SL", "Slider")):
        out[ptype] = [{"player_id": str(base_id + i), "pa": pa,
                       "woba": wobas[i] + (0.02 if ptype == "FF" else -0.02),
                       "pitch_type": ptype, "pitch_name": pname, "batter": names[i]}
                      for i in range(9)]
    return out


AWAY_NAMES = [f"Away Hitter {i}" for i in range(1, 10)]
HOME_NAMES = [f"Home Hitter {i}" for i in range(1, 10)]


def lineup(base_id, names, wobas, advantaged=6, throws="L"):
    return {"batters": batters(base_id, names),
            "handedness": {"L": 3, "R": 5, "S": 1, "unknown": 0, "known": 9},
            "platoon_advantage": {"share": round(advantaged / 9, 3), "advantaged": advantaged,
                                  "known": 9, "counts": {}, "reason": None},
            "faces_starter_throwing": throws,
            "vs_pitch": vs_pitch(base_id, names, wobas)}


def arsenal(woba, pa=150.0):
    return [{"pitch_type": "FF", "pitch_name": "4-Seam Fastball", "pitch_usage": 60.0,
             "pitches": 600.0, "pa": pa, "woba": woba, "whiff_percent": 25.0},
            {"pitch_type": "SL", "pitch_name": "Slider", "pitch_usage": 40.0,
             "pitches": 400.0, "pa": pa, "woba": woba, "whiff_percent": 35.0}]


def teams(**over):
    base = {"away_games_played": 150, "home_games_played": 150,
            "away_runs_scored_pg": 4.6, "home_runs_scored_pg": 4.4,
            "away_runs_allowed_pg": 4.0, "home_runs_allowed_pg": 4.2,
            "away_run_diff_pg": 0.6, "home_run_diff_pg": 0.2,
            "away_win_pct": 0.56, "home_win_pct": 0.52,
            "away_last10_run_diff_pg": 0.6, "home_last10_run_diff_pg": 0.2,
            "away_last10_games": 10, "home_last10_games": 10,
            "away_last5_run_diff_pg": 0.6, "home_last5_run_diff_pg": 0.2,
            "away_rest_days": 1, "home_rest_days": 1, "either_sample_thin": False}
    base.update(over)
    return base


def pen(innings, count, unavailable=0, questionable=0):
    rel = ([{"availability": "likely_unavailable"}] * unavailable
           + [{"availability": "questionable"}] * questionable
           + [{"availability": "available"}] * max(count - unavailable - questionable, 0))
    return {"relievers": rel, "total_innings": innings, "reliever_count": count}


def plain():
    """`rich()` with both starters neutral, for tests about one starter factor."""
    p = rich()
    sec(p, "starters").update(starter("away"))
    sec(p, "starters").update(starter("home"))
    return p


def rich():
    # The away starter's ERA is far below his FIP, his last three starts are
    # bad, and he gives up homers, so every starter-level factor fires.
    away_st = starter("away", era=3.00, fip=3.90, whip=1.25, kbb=0.12, hr9=1.5,
                      recent_era=5.20)
    home_st = starter("home", era=3.20, fip=3.10, whip=1.05, kbb=0.20, hr9=0.8)
    starters = {**away_st, **home_st}
    return {
        "advanced": {
            "game": {"game_pk": 1, "date": "2026-10-03", "away_team": "BOS",
                     "home_team": "NYY", "away_probable": "Alan Away",
                     "home_probable": "Henry Home", "game_type": "R",
                     "detailed_state": "Scheduled", "away_score": None,
                     "home_score": None},
            "information_time": "2026-10-03T15:00:00+00:00",
            "gaps": {},
            "sections": {
                "teams": teams(),
                "starters": starters,
                "park": {"name": "Test Park", "roof": "open", "altitude_m": 10,
                         "orientation_deg": None},
                "weather": {"temp_f": 72.0, "wind_mph": 5.0, "wind_from_deg": 90,
                            "precip_probability_pct": 5, "hours_from_first_pitch": 0.5},
                "lineups": {"away": lineup(100, AWAY_NAMES,
                                            [0.36, 0.35, 0.34, 0.33, 0.32, 0.31, 0.30, 0.30, 0.29], 7),
                            "home": lineup(200, HOME_NAMES,
                                            [0.33, 0.33, 0.32, 0.31, 0.30, 0.30, 0.29, 0.29, 0.28], 4, "R")},
                "arsenals": {"away": arsenal(0.320), "home": arsenal(0.270)},
                "matchup_history": {
                    "away": {"usable": True, "total_at_bats": 90, "total_hits": 27,
                             "total_home_runs": 3, "aggregate_avg": 0.300,
                             "batters": [{"at_bats": 10, "name": "x"}] * 9},
                    "home": {"usable": True, "total_at_bats": 80, "total_hits": 16,
                             "total_home_runs": 1, "aggregate_avg": 0.200,
                             "batters": [{"at_bats": 9, "name": "y"}] * 9}},
                "bullpen": {"BOS": pen(14.0, 8, 3, 1), "NYY": pen(9.0, 7, 0, 1)},
                "travel": {"BOS": {"games_last_7": 6, "miles": 2400, "zones": 3,
                                   "eastward": True, "dense_stretch": True, "reason": None},
                           "NYY": {"games_last_7": 6, "miles": 0, "zones": 0,
                                   "eastward": False, "dense_stretch": False, "reason": None}},
                "splits": {"home": {"record": {"as_of": "2026-10-01T00:00:00+00:00"},
                                    "platoon": {"usable": True, "vs_left_ops": 0.700,
                                                "vs_right_ops": 0.600, "gap": 0.1,
                                                "weaker_against": "L", "vs_left_faced": 120,
                                                "vs_right_faced": 400}}},
                "price_improvement": {
                    "sides": {"away": {"consensus_probability": 0.42},
                              "home": {"consensus_probability": 0.58}},
                    "dispersion": {"books": 9}, "observed_utc": "2026-10-03T14:30:00+00:00"},
            },
        },
        "price_verdicts": {"away": {"fair_price": 138, "age_seconds": 600},
                           "home": {"fair_price": -138, "age_seconds": 600}},
        "read_inputs": {
            "results": {"through": "2026-10-02", "games": 2400},
            "league_runs_per_game": {"value": 4.5, "games": 2400},
            "park_factor": {"team": "NYY", "factor": 1.02, "raw_factor": 1.05,
                            "home_games": 80, "away_games": 79, "thin": False},
            "pitcher_logs": {"through": "2026-10-02"},
            "bullpen_log": {"through": "2026-10-02"},
        },
    }


def sec(p, name):
    return p["advanced"]["sections"][name]


def factor(read, key):
    for f in read["factors"]:
        if f["factor"] == key:
            return f
    return None


def missing_inputs(read):
    return {m["input"]: m for m in read["missing"]}


def all_evidence(read):
    out = []
    for f in read["factors"]:
        out += f["evidence"]
    out += read["run_environment"].get("evidence", [])
    out += read["market_view"].get("evidence", [])
    for w in read["what_would_change_it"]:
        out += w.get("evidence", [])
    return out


def all_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if k in ("path", "factor"):          # field paths and keys are not prose
                continue
            yield from all_strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from all_strings(v)


ALL_FACTORS = {"starting_pitching", "pitcher_regression", "pitcher_form", "hr_park",
               "arsenal_results", "pitch_mix", "platoon", "lineup_depth",
               "batter_vs_pitcher", "season_strength", "recent_form", "rest_travel",
               "bullpen", "park_weather"}

# Words and shapes the product forbids in anything a customer reads.
BANNED = [
    (r"—|–", "dash"),
    (r"\block\b", "lock"),
    (r"\bguarantee", "guarantee"),
    (r"\+\s*EV\b", "+EV"),
    (r"\bfree money\b", "free money"),
    (r"\bprofit", "profit"),
    (r"\bwin probabilit", "win probability"),
    (r"\bsure thing\b", "sure thing"),
    (r"\byou should\b", "advice"),
    (r"\bwe recommend\b", "advice"),
    (r"\b(?:take|bet on|play|pick) the (?:over|under|favou?rites?|underdogs?)\b", "advice"),
    (r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", "snake_case field name"),
]


def banned_hits(read):
    hits = []
    for text in all_strings(read):
        for pattern, label in BANNED:
            if re.search(pattern, text, re.I):
                hits.append(f"{label}: {text[:100]!r}")
        # "edge" only inside a negation
        for m in re.finditer(r"\bedges?\b", text, re.I):
            window = text[max(0, m.start() - 90):m.start()]
            if not re.search(r"\b(no|not|none|never|nothing|without)\b", window, re.I):
                hits.append(f"edge affirmed: {text[:100]!r}")
    return hits


# ---------------------------------------------------------------------------
# resolve_path, and the structural contract
# ---------------------------------------------------------------------------

class TheStructure(unittest.TestCase):
    def test_resolve_path_walks_dicts_and_list_indexes(self):
        node = {"a": {"b": [10, {"c": 7}]}}
        self.assertEqual(mr.resolve_path(node, "a.b.1.c"), (True, 7))
        self.assertEqual(mr.resolve_path(node, "a.b.0"), (True, 10))
        self.assertEqual(mr.resolve_path(node, "a.x"), (False, None))
        self.assertEqual(mr.resolve_path(node, "a.b.9"), (False, None))
        self.assertEqual(mr.resolve_path(node, "a.b.z"), (False, None))

    def test_a_rich_payload_fires_every_factor(self):
        read = mr.build_read(rich())
        self.assertEqual({f["factor"] for f in read["factors"]}, ALL_FACTORS)

    def test_the_read_has_every_top_level_part(self):
        read = mr.build_read(rich())
        for key in ("label", "as_of", "headline", "notices", "factors",
                    "run_environment", "market_view", "what_would_change_it", "missing"):
            self.assertIn(key, read)
        # The owner's word for these is "edges"; the product's own language
        # sweep forbids the word, so the key is "factors".
        self.assertNotIn("edges", read)

    def test_every_factor_has_the_documented_fields(self):
        for f in mr.build_read(rich())["factors"]:
            for key in ("factor", "favours", "size", "sentence", "evidence",
                        "confidence", "caveat"):
                self.assertIn(key, f, f["factor"])
            self.assertIn(f["size"], ("slight", "moderate", "large"))
            self.assertIn(f["confidence"], ("low", "medium", "high"))
            self.assertTrue(f["sentence"].strip())
            self.assertTrue(f["caveat"].strip(), f["factor"])
            self.assertTrue(f["evidence"], f["factor"])

    def test_factors_are_ranked_by_size_times_confidence(self):
        read = mr.build_read(rich())
        scores = [mr._SIZE_RANK[f["size"]] * mr._CONF_MULT[f["confidence"]]
                  for f in read["factors"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual([f["rank"] for f in read["factors"]],
                         list(range(1, len(scores) + 1)))

    def test_every_evidence_path_resolves_and_matches_the_payload(self):
        payload = rich()
        read = mr.build_read(payload)
        evidence = all_evidence(read)
        self.assertGreater(len(evidence), 40)
        for e in evidence:
            found, value = mr.resolve_path(payload, e["path"])
            self.assertTrue(found, f"unresolved: {e}")
            if not e.get("derived"):
                self.assertEqual(value, e["value"], e)

    def test_the_read_is_deterministic_and_leaves_the_payload_alone(self):
        payload = rich()
        before = copy.deepcopy(payload)
        first, second = mr.build_read(payload), mr.build_read(payload)
        self.assertEqual(first, second)
        self.assertEqual(payload, before)

    def test_the_read_is_json_serialisable(self):
        json.dumps(mr.build_read(rich()))

    def test_no_banned_wording_in_a_rich_read(self):
        self.assertEqual(banned_hits(mr.build_read(rich())), [])

    def test_the_read_never_raises_on_garbage(self):
        for junk in ({}, {"advanced": None}, {"advanced": {"sections": None}},
                     {"advanced": {"game": {"date": "not a date"}, "sections": {
                         "teams": {"away_run_diff_pg": "x"}, "starters": {"away_sp_known": True}}}},
                     {"advanced": {"sections": {"lineups": {"away": {"vs_pitch": "nope"}}}}}):
            with self.subTest(junk=junk):
                read = mr.build_read(junk)
                self.assertIn("headline", read)
                json.dumps(read)

    def test_a_factor_that_raises_is_reported_not_swallowed(self):
        def boom(ctx):
            raise RuntimeError("boom")
        with patch.object(mr, "_FACTORS", (boom,) + mr._FACTORS[1:]):
            read = mr.build_read(rich())
        errors = [m for m in read["missing"] if m["status"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("could not be computed", errors[0]["detail"])
        self.assertGreater(len(read["factors"]), 5)     # the rest still produced


# ---------------------------------------------------------------------------
# Starting pitching
# ---------------------------------------------------------------------------

class StartingPitching(unittest.TestCase):
    def test_a_large_gap_favours_the_better_starter(self):
        p = rich()
        sec(p, "starters").update(starter("away", fip=5.0, whip=1.4, kbb=0.08),)
        sec(p, "starters").update(starter("home", fip=3.0, whip=1.0, kbb=0.22))
        f = factor(mr.build_read(p), "starting_pitching")
        self.assertEqual(f["favours"], "NYY")
        self.assertEqual(f["size"], "large")
        self.assertIn("2.00 runs per nine", f["sentence"])
        self.assertIn("point the same way", f["sentence"])

    def test_the_size_steps_follow_the_fip_gap(self):
        for gap, expected in ((0.30, "slight"), (0.60, "moderate"), (1.10, "large")):
            p = rich()
            sec(p, "starters").update(starter("away", fip=3.0 + gap))
            sec(p, "starters").update(starter("home", fip=3.0))
            with self.subTest(gap=gap):
                self.assertEqual(factor(mr.build_read(p), "starting_pitching")["size"], expected)

    def test_a_gap_under_the_floor_favours_nobody(self):
        p = rich()
        sec(p, "starters").update(starter("away", fip=3.50))
        sec(p, "starters").update(starter("home", fip=3.40))
        f = factor(mr.build_read(p), "starting_pitching")
        self.assertEqual(f["favours"], "even")
        self.assertIn("does not separate", f["sentence"] + f["sentence"])

    def test_whip_and_strikeouts_disagreeing_discounts_one_step(self):
        p = rich()
        # Home is better on FIP by 0.6 but worse on WHIP and K-BB.
        sec(p, "starters").update(starter("away", fip=3.7, whip=1.0, kbb=0.25))
        sec(p, "starters").update(starter("home", fip=3.1, whip=1.3, kbb=0.10))
        f = factor(mr.build_read(p), "starting_pitching")
        self.assertEqual(f["size"], "slight")             # moderate, minus one
        self.assertIn("discounted a step", f["sentence"])

    def test_thin_innings_lower_the_confidence_and_say_so(self):
        p = rich()
        sec(p, "starters").update(starter("home", fip=3.0, innings=35.0, thin=True))
        f = factor(mr.build_read(p), "starting_pitching")
        self.assertEqual(f["confidence"], "low")
        self.assertTrue(f["down_weighted"])
        self.assertIn("thin sample", f["caveat"])

    def test_moderate_innings_give_medium_confidence(self):
        p = rich()
        sec(p, "starters").update(starter("home", innings=90.0))
        self.assertEqual(factor(mr.build_read(p), "starting_pitching")["confidence"], "medium")

    def test_full_innings_and_fresh_logs_give_high_confidence(self):
        self.assertEqual(factor(mr.build_read(rich()), "starting_pitching")["confidence"], "high")

    def test_stale_pitcher_logs_cap_the_confidence_at_medium(self):
        p = rich()
        p["read_inputs"]["pitcher_logs"]["through"] = "2026-09-07"
        read = mr.build_read(p)
        f = factor(read, "starting_pitching")
        self.assertEqual(f["confidence"], "medium")
        self.assertIn("pitcher logs end 2026-09-07, 26 days before this game", f["caveat"])
        self.assertEqual(missing_inputs(read)["Pitcher logs"]["status"], "stale")

    def test_one_missing_starter_carries_no_direction_and_names_the_gap(self):
        p = rich()
        sec(p, "starters").update(starter("away", known=False))
        sec(p, "arsenals")["away"] = arsenal(0.300)
        read = mr.build_read(p)
        f = factor(read, "starting_pitching")
        self.assertEqual(f["favours"], "even")
        self.assertEqual(f["confidence"], "low")
        self.assertIn("cannot be compared", f["sentence"])
        gap = missing_inputs(read)["Alan Away (starter line)"]
        # the pitch file shows he has thrown: the gap is ours, not a debut
        self.assertIn("1000 pitches", gap["detail"])
        self.assertIn("gap is in our log", gap["detail"])

    def test_a_missing_starter_with_no_pitch_data_says_nothing_can_be_said(self):
        p = rich()
        sec(p, "starters").update(starter("away", known=False))
        del sec(p, "arsenals")["away"]
        gap = missing_inputs(mr.build_read(p))["Alan Away (starter line)"]
        self.assertIn("nothing can be said", gap["detail"])

    def test_no_listed_probable_is_named_as_such(self):
        p = rich()
        sec(p, "starters").update(starter("away", known=False))
        p["advanced"]["game"]["away_probable"] = None
        gap = [m for m in mr.build_read(p)["missing"] if "starter line" in m["input"]][0]
        self.assertIn("no probable starter is listed", gap["detail"])

    def test_both_starters_missing_produces_no_pitching_factor(self):
        p = rich()
        sec(p, "starters").update(starter("away", known=False))
        sec(p, "starters").update(starter("home", known=False))
        del p["advanced"]["sections"]["arsenals"]
        for key in ("matchup_history", "lineups", "splits", "bullpen", "travel"):
            del p["advanced"]["sections"][key]
        sec(p, "teams").update(away_run_diff_pg=0.3, home_run_diff_pg=0.3)
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "starting_pitching"))
        self.assertIn("Neither probable starter", read["headline"])

    def test_no_starters_section_is_a_named_gap(self):
        p = rich()
        del p["advanced"]["sections"]["starters"]
        p["advanced"]["gaps"]["starters"] = "no pitcher logs; run the pitcher log build"
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "starting_pitching"))
        self.assertIn("no pitcher logs", missing_inputs(read)["Starting pitchers"]["detail"])


class PitcherRegression(unittest.TestCase):
    def test_era_far_below_fip_is_flagged_and_leans_to_the_other_club(self):
        p = plain()
        sec(p, "starters").update(starter("home", era=2.40, fip=3.40, innings=160.0))
        f = factor(mr.build_read(p), "pitcher_regression")
        self.assertEqual(f["favours"], "BOS")
        self.assertIn("1.00 below his FIP", f["sentence"])
        self.assertIn("160 innings", f["sentence"])

    def test_era_far_above_fip_leans_toward_his_own_club(self):
        p = plain()
        sec(p, "starters").update(starter("home", era=4.40, fip=3.40, innings=160.0))
        f = factor(mr.build_read(p), "pitcher_regression")
        self.assertEqual(f["favours"], "NYY")
        self.assertIn("lagged", f["sentence"])

    def test_a_gap_under_half_a_run_is_not_flagged(self):
        p = plain()
        sec(p, "starters").update(starter("home", era=3.20, fip=3.50))
        sec(p, "starters").update(starter("away", era=3.60, fip=3.90))
        self.assertIsNone(factor(mr.build_read(p), "pitcher_regression"))

    def test_below_the_innings_floor_it_is_not_flagged(self):
        p = plain()
        sec(p, "starters").update(starter("home", era=1.0, fip=3.4, innings=30.0))
        sec(p, "starters").update(starter("away", era=3.6, fip=3.9))
        self.assertIsNone(factor(mr.build_read(p), "pitcher_regression"))

    def test_both_flagged_in_opposite_directions_can_cancel(self):
        p = plain()
        sec(p, "starters").update(starter("away", era=2.5, fip=3.5, innings=160.0))
        sec(p, "starters").update(starter("home", era=2.5, fip=3.5, innings=160.0))
        f = factor(mr.build_read(p), "pitcher_regression")
        self.assertEqual(f["favours"], "even")

    def test_stale_logs_cap_its_confidence(self):
        p = plain()
        sec(p, "starters").update(starter("home", era=2.40, fip=3.40, innings=200.0))
        self.assertEqual(factor(mr.build_read(p), "pitcher_regression")["confidence"], "medium")
        p["read_inputs"]["pitcher_logs"]["through"] = "2026-09-01"
        f = factor(mr.build_read(p), "pitcher_regression")
        self.assertEqual(f["confidence"], "medium")
        self.assertIn("pitcher logs end 2026-09-01", f["caveat"])


class PitcherForm(unittest.TestCase):
    def test_a_recent_blowup_is_flagged_with_its_sample(self):
        p = plain()
        sec(p, "starters").update(starter("home", era=3.0, recent_era=5.0, recent_ip=5.0))
        f = factor(mr.build_read(p), "pitcher_form")
        self.assertEqual(f["favours"], "BOS")
        self.assertEqual(f["confidence"], "low")
        self.assertIn("3 starts, about 15 innings", f["sentence"])
        self.assertIn("small sample", f["sentence"])

    def test_direction_uses_both_starters_not_only_the_flagged_one(self):
        p = plain()
        # Home flagged (+2.0). Away is unflagged but much improved (-1.0).
        sec(p, "starters").update(starter("home", era=3.0, recent_era=5.0))
        sec(p, "starters").update(starter("away", era=4.0, recent_era=3.0))
        f = factor(mr.build_read(p), "pitcher_form")
        self.assertEqual(f["favours"], "BOS")
        # Net 3.0 in the away club's favour, from BOTH gaps.
        sec(p, "starters").update(starter("away", era=4.0, recent_era=6.0))
        f = factor(mr.build_read(p), "pitcher_form")
        self.assertEqual(f["favours"], "even")        # +2.0 and +2.0 cancel

    def test_shorter_outings_alone_flag_it(self):
        p = plain()
        sec(p, "starters").update(starter("home", ip=6.0, recent_ip=4.9))
        f = factor(mr.build_read(p), "pitcher_form")
        self.assertIn("shorter outings", f["sentence"])

    def test_fewer_than_three_starts_is_not_used(self):
        p = plain()
        sec(p, "starters").update(starter("home", era=3.0, recent_era=6.0, recent_starts=2))
        self.assertIsNone(factor(mr.build_read(p), "pitcher_form"))

    def test_stale_logs_say_the_three_are_not_the_latest(self):
        p = plain()
        sec(p, "starters").update(starter("home", era=3.0, recent_era=5.0))
        p["read_inputs"]["pitcher_logs"]["through"] = "2026-09-07"
        f = factor(mr.build_read(p), "pitcher_form")
        self.assertIn("not the latest three", f["caveat"])
        self.assertTrue(f["down_weighted"])


class HomeRunsAndPark(unittest.TestCase):
    def setUp(self):
        self.p = plain()
        sec(self.p, "starters").update(starter("away", hr9=1.5))
        sec(self.p, "starters").update(starter("home", hr9=0.8))

    def test_the_starter_who_allows_fewer_homers_is_favoured(self):
        f = factor(mr.build_read(self.p), "hr_park")
        self.assertEqual(f["favours"], "NYY")
        self.assertEqual(f["size"], "slight")
        self.assertIn("1.50 home runs per nine", f["sentence"])
        self.assertIn("park factor of 1.020 is close to neutral", f["sentence"])

    def test_a_homer_friendly_park_raises_the_size_one_step(self):
        self.p["read_inputs"]["park_factor"]["factor"] = 1.08
        self.assertEqual(factor(mr.build_read(self.p), "hr_park")["size"], "moderate")

    def test_a_pitcher_park_lowers_it_below_slight_to_slight_floor(self):
        self.p["read_inputs"]["park_factor"]["factor"] = 0.92
        f = factor(mr.build_read(self.p), "hr_park")
        self.assertEqual(f["size"], "slight")             # never disappears once flagged

    def test_altitude_raises_it(self):
        sec(self.p, "park")["altitude_m"] = 1580
        f = factor(mr.build_read(self.p), "hr_park")
        self.assertEqual(f["size"], "moderate")
        self.assertIn("1580 metres", f["sentence"])

    def test_a_thin_park_factor_is_not_used_to_move_the_size(self):
        self.p["read_inputs"]["park_factor"].update(thin=True, factor=1.10)
        f = factor(mr.build_read(self.p), "hr_park")
        self.assertEqual(f["size"], "slight")
        self.assertIn("thin games", f["sentence"])

    def test_a_missing_park_factor_is_said(self):
        self.p["read_inputs"]["park_factor"] = None
        self.assertIn("no park factor is available",
                      factor(mr.build_read(self.p), "hr_park")["sentence"])

    def test_a_small_gap_is_not_a_factor(self):
        sec(self.p, "starters").update(starter("away", hr9=1.0))
        sec(self.p, "starters").update(starter("home", hr9=0.9))
        self.assertIsNone(factor(mr.build_read(self.p), "hr_park"))

    def test_thin_innings_lower_confidence(self):
        sec(self.p, "starters").update(starter("away", hr9=1.5, innings=70.0))
        self.assertEqual(factor(mr.build_read(self.p), "hr_park")["confidence"], "low")


# ---------------------------------------------------------------------------
# Arsenals and pitch mix
# ---------------------------------------------------------------------------

class ArsenalResults(unittest.TestCase):
    def test_the_harder_to_hit_starter_is_favoured(self):
        p = rich()
        sec(p, "arsenals")["away"] = arsenal(0.340)
        f = factor(mr.build_read(p), "arsenal_results")
        self.assertEqual(f["favours"], "NYY")
        self.assertEqual(f["size"], "large")              # .340 against .270
        self.assertIn("0.270 wOBA over 300 plate appearances", f["sentence"])
        self.assertEqual(factor(mr.build_read(rich()), "arsenal_results")["size"], "moderate")

    def test_below_the_plate_appearance_floor_it_is_a_named_gap(self):
        p = rich()
        sec(p, "arsenals")["away"] = arsenal(0.300, pa=20.0)
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "arsenal_results"))
        self.assertEqual(missing_inputs(read)["Alan Away (pitch arsenal)"]["status"], "thin")

    def test_one_side_absent_is_a_named_gap_and_no_factor(self):
        p = rich()
        del sec(p, "arsenals")["home"]
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "arsenal_results"))
        self.assertIn("Henry Home (pitch arsenal)", missing_inputs(read))

    def test_no_arsenal_section_is_a_named_gap(self):
        p = rich()
        del p["advanced"]["sections"]["arsenals"]
        p["advanced"]["gaps"]["arsenals"] = "pitch arsenals not built for this season"
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "arsenal_results"))
        self.assertIn("Pitch arsenals", missing_inputs(read))

    def test_confidence_is_low_under_two_hundred_plate_appearances(self):
        p = rich()
        sec(p, "arsenals")["away"] = arsenal(0.320, pa=60.0)
        f = factor(mr.build_read(p), "arsenal_results")
        self.assertEqual(f["confidence"], "low")          # 120 PA each pitch type summed
        self.assertNotEqual(factor(mr.build_read(rich()), "arsenal_results")["confidence"], "low")

    def test_it_says_the_pitch_file_has_no_stated_date(self):
        self.assertIn("does not state", factor(mr.build_read(rich()), "arsenal_results")["caveat"])


class PitchMix(unittest.TestCase):
    def test_each_lineup_is_read_against_the_starter_it_faces(self):
        f = factor(mr.build_read(rich()), "pitch_mix")
        self.assertIn("The Red Sox lineup has run", f["sentence"])
        self.assertIn("The Yankees lineup has run", f["sentence"])
        self.assertIn("Henry Home throws", f["sentence"])      # away lineup faces home starter
        self.assertIn("Alan Away throws", f["sentence"])

    def test_no_lineup_means_no_pitch_mix(self):
        p = rich()
        del p["advanced"]["sections"]["lineups"]
        self.assertIsNone(factor(mr.build_read(p), "pitch_mix"))

    def test_no_arsenal_means_no_pitch_mix(self):
        p = rich()
        del p["advanced"]["sections"]["arsenals"]
        self.assertIsNone(factor(mr.build_read(p), "pitch_mix"))

    def test_one_side_only_names_the_other_as_missing(self):
        p = rich()
        del sec(p, "arsenals")["away"]
        read = mr.build_read(p)
        f = factor(read, "pitch_mix")
        self.assertIn("The Red Sox lineup has run", f["sentence"])
        self.assertNotIn("The Yankees lineup has run", f["sentence"])
        self.assertIn("the other lineup cannot be read", f["sentence"])
        self.assertIn("Yankees lineup against Alan Away (pitch mix)", missing_inputs(read))

    def test_a_thin_sample_is_low_confidence(self):
        p = rich()
        for side in ("away", "home"):
            for rows in sec(p, "lineups")[side]["vs_pitch"].values():
                for r in rows:
                    r["pa"] = 4.0
        f = factor(mr.build_read(p), "pitch_mix")
        self.assertEqual(f["confidence"], "low")

    def test_a_lineup_close_to_its_usual_line_is_not_a_direction(self):
        f = factor(mr.build_read(rich()), "pitch_mix")
        # The fixture's FF/SL rows differ by .02 either side of a .xx base and the
        # mix is 60/40, so each lineup sits within a hair of its own baseline.
        self.assertEqual(f["favours"], "even")


# ---------------------------------------------------------------------------
# Lineups
# ---------------------------------------------------------------------------

class Platoon(unittest.TestCase):
    def test_the_lineup_with_more_advantaged_hitters_is_favoured(self):
        f = factor(mr.build_read(rich()), "platoon")
        self.assertEqual(f["favours"], "BOS")             # 7 of 9 against 4 of 9
        self.assertEqual(f["size"], "moderate")           # a gap of .33
        p = rich()
        sec(p, "lineups")["away"]["platoon_advantage"]["share"] = 0.889   # 8 of 9
        self.assertEqual(factor(mr.build_read(p), "platoon")["size"], "large")
        self.assertIn("7 of 9 Red Sox hitters", f["sentence"])
        self.assertIn("who throws right-handed", f["sentence"])

    def test_the_starters_own_split_is_added_with_its_sample(self):
        f = factor(mr.build_read(rich()), "platoon")
        self.assertIn("120 batters faced", f["sentence"])
        self.assertIn("weaker against left-handed bats", f["sentence"])

    def test_one_posted_lineup_carries_no_comparison(self):
        p = rich()
        del sec(p, "lineups")["home"]
        read = mr.build_read(p)
        f = factor(read, "platoon")
        self.assertEqual(f["favours"], "even")
        self.assertEqual(f["confidence"], "low")
        self.assertIn("Only one lineup is posted", f["sentence"])
        self.assertIn("Yankees lineup", missing_inputs(read))

    def test_no_lineups_is_a_named_gap(self):
        p = rich()
        del p["advanced"]["sections"]["lineups"]
        p["advanced"]["gaps"]["lineups"] = "lineup not posted yet, or not fetched"
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "platoon"))
        self.assertIn("not posted", missing_inputs(read)["Lineups"]["detail"])

    def test_unknown_bat_sides_are_a_named_gap(self):
        p = rich()
        sec(p, "lineups")["away"]["platoon_advantage"] = {
            "share": None, "reason": "no handedness known for this lineup"}
        read = mr.build_read(p)
        self.assertIn("Red Sox platoon share", missing_inputs(read))

    def test_similar_lineups_say_so(self):
        p = rich()
        sec(p, "lineups")["home"]["platoon_advantage"]["share"] = 0.667
        f = factor(mr.build_read(p), "platoon")
        self.assertEqual(f["favours"], "even")
        self.assertIn("similar platoon picture", f["sentence"])


class LineupDepth(unittest.TestCase):
    def test_depth_is_derived_from_the_per_pitch_lines(self):
        f = factor(mr.build_read(rich()), "lineup_depth")
        self.assertEqual(f["favours"], "BOS")
        self.assertIn("slots one to four", f["sentence"])
        self.assertIn("slots five to nine", f["sentence"])
        self.assertTrue(all(e.get("derived") for e in f["evidence"]))

    def test_the_depth_section_is_preferred_when_the_pitch_store_built_it(self):
        p = rich()
        top = {"woba": 0.400, "pa": 500}
        bot = {"woba": 0.300, "pa": 600}
        sec(p, "matchup_depth")  if False else None
        p["advanced"]["sections"]["matchup_depth"] = {
            "away": {"concentration": {"top": top, "bottom": bot}},
            "home": {"concentration": {"top": {"woba": 0.320, "pa": 500},
                                       "bottom": {"woba": 0.315, "pa": 600}}}}
        f = factor(mr.build_read(p), "lineup_depth")
        self.assertIn("0.400 wOBA from slots one to four (500 plate appearances)", f["sentence"])
        self.assertIn("top-heavy", f["sentence"])

    def test_thin_plate_appearances_lower_confidence(self):
        p = rich()
        for side in ("away", "home"):
            for rows in sec(p, "lineups")[side]["vs_pitch"].values():
                for r in rows:
                    r["pa"] = 3.0
        self.assertEqual(factor(mr.build_read(p), "lineup_depth")["confidence"], "low")

    def test_a_lineup_with_no_measured_hitters_is_named(self):
        p = rich()
        sec(p, "lineups")["home"]["vs_pitch"] = {}
        read = mr.build_read(p)
        f = factor(read, "lineup_depth")
        self.assertIn("Only one lineup can be read", f["sentence"])
        self.assertIn("Yankees lineup depth", missing_inputs(read))

    def test_close_lineups_favour_neither(self):
        p = rich()
        sec(p, "lineups")["home"]["vs_pitch"] = copy.deepcopy(sec(p, "lineups")["away"]["vs_pitch"])
        for rows in sec(p, "lineups")["home"]["vs_pitch"].values():
            for i, r in enumerate(rows):
                r["player_id"] = str(200 + i)
        self.assertEqual(factor(mr.build_read(p), "lineup_depth")["favours"], "even")


class BatterVsPitcher(unittest.TestCase):
    def test_the_sample_is_stated_and_the_factor_is_down_weighted(self):
        f = factor(mr.build_read(rich()), "batter_vs_pitcher")
        self.assertIn("27 for 90 (0.300)", f["sentence"])
        self.assertIn("the most at-bats for any one being 10", f["sentence"])
        self.assertEqual(f["confidence"], "low")
        self.assertTrue(f["down_weighted"])
        self.assertEqual(f["size"], "slight")             # capped whatever the gap

    def test_a_big_gap_with_enough_at_bats_leans_but_stays_slight(self):
        f = factor(mr.build_read(rich()), "batter_vs_pitcher")
        self.assertEqual(f["favours"], "BOS")             # .300 against .200 on 90 and 80 AB

    def test_too_few_at_bats_never_leans(self):
        p = rich()
        sec(p, "matchup_history")["away"]["total_at_bats"] = 25
        self.assertEqual(factor(mr.build_read(p), "batter_vs_pitcher")["favours"], "even")

    def test_an_unusable_side_is_named_and_the_other_still_reads(self):
        p = rich()
        sec(p, "matchup_history")["home"] = None
        read = mr.build_read(p)
        f = factor(read, "batter_vs_pitcher")
        self.assertIn("no comparison", f["sentence"])
        self.assertIn("Yankees hitters against Alan Away", missing_inputs(read))

    def test_no_history_is_a_named_gap(self):
        p = rich()
        del p["advanced"]["sections"]["matchup_history"]
        p["advanced"]["gaps"]["matchup_history"] = "batter-vs-pitcher history not fetched"
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "batter_vs_pitcher"))
        self.assertIn("Batter against pitcher history", missing_inputs(read))


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

class SeasonStrength(unittest.TestCase):
    def test_sizes_follow_the_run_margin_gap(self):
        for away, home, expected, fav in ((0.6, 0.2, "slight", "BOS"),
                                           (0.9, 0.2, "moderate", "BOS"),
                                           (0.2, 1.4, "large", "NYY")):
            p = rich()
            sec(p, "teams").update(away_run_diff_pg=away, home_run_diff_pg=home)
            f = factor(mr.build_read(p), "season_strength")
            with self.subTest(away=away, home=home):
                self.assertEqual((f["size"], f["favours"]), (expected, fav))

    def test_a_gap_under_the_floor_favours_nobody(self):
        p = rich()
        sec(p, "teams").update(away_run_diff_pg=0.4, home_run_diff_pg=0.3)
        self.assertEqual(factor(mr.build_read(p), "season_strength")["favours"], "even")

    def test_games_played_is_the_confidence(self):
        p = rich()
        self.assertEqual(factor(mr.build_read(p), "season_strength")["confidence"], "high")
        sec(p, "teams").update(away_games_played=60)
        self.assertEqual(factor(mr.build_read(p), "season_strength")["confidence"], "medium")
        sec(p, "teams").update(away_games_played=20)
        self.assertEqual(factor(mr.build_read(p), "season_strength")["confidence"], "low")

    def test_a_thin_flag_forces_low(self):
        p = rich()
        sec(p, "teams")["either_sample_thin"] = True
        self.assertEqual(factor(mr.build_read(p), "season_strength")["confidence"], "low")

    def test_old_results_cap_it_at_medium_and_say_so(self):
        p = rich()
        p["read_inputs"]["results"]["through"] = "2026-09-23"
        f = factor(mr.build_read(p), "season_strength")
        self.assertEqual(f["confidence"], "medium")
        self.assertIn("results end 2026-09-23, 10 days before this game", f["caveat"])

    def test_a_postseason_game_says_the_rates_are_regular_season(self):
        p = rich()
        p["advanced"]["game"]["game_type"] = "D"
        read = mr.build_read(p)
        self.assertIn("division series", factor(read, "season_strength")["caveat"])
        self.assertTrue([n for n in read["notices"] if "division series" in n])

    def test_no_teams_section_is_a_named_gap(self):
        p = rich()
        del p["advanced"]["sections"]["teams"]
        p["advanced"]["gaps"]["teams"] = "no historical results store"
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "season_strength"))
        self.assertIn("Team records", missing_inputs(read))
        self.assertFalse(read["run_environment"]["available"])


class RecentForm(unittest.TestCase):
    def test_it_is_always_slight_and_low_confidence(self):
        p = rich()
        sec(p, "teams").update(away_last10_run_diff_pg=3.5, home_last10_run_diff_pg=-2.0)
        f = factor(mr.build_read(p), "recent_form")
        self.assertEqual((f["size"], f["confidence"]), ("slight", "low"))
        self.assertEqual(f["favours"], "BOS")
        self.assertIn("capped at slight", f["caveat"])

    def test_both_near_their_season_line_favours_nobody(self):
        f = factor(mr.build_read(rich()), "recent_form")
        self.assertEqual(f["favours"], "even")
        self.assertIn("Neither club is far", f["sentence"])

    def test_stale_results_are_named_in_the_caveat(self):
        p = rich()
        p["read_inputs"]["results"]["through"] = "2026-09-23"
        f = factor(mr.build_read(p), "recent_form")
        self.assertIn("newest in our records, not the newest played", f["caveat"])

    def test_one_clubs_missing_ten_game_line_is_a_named_gap(self):
        p = rich()
        sec(p, "teams")["home_last10_games"] = 0
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "recent_form"))
        self.assertEqual(missing_inputs(read)["Recent form"]["status"], "thin")


class RestAndTravel(unittest.TestCase):
    def test_the_lighter_travel_load_is_favoured(self):
        f = factor(mr.build_read(rich()), "rest_travel")
        self.assertEqual(f["favours"], "NYY")
        self.assertEqual(f["size"], "moderate")           # three flags against none
        self.assertIn("a dense stretch of games", f["sentence"])
        self.assertIn("3 time zones east", f["sentence"])
        self.assertEqual(f["confidence"], "low")
        self.assertIn("not tested", f["caveat"])

    def test_no_games_in_the_window_is_a_named_gap_not_a_zero(self):
        p = rich()
        for team in ("BOS", "NYY"):
            sec(p, "travel")[team] = {"team": team, "games_last_7": 0, "miles": None,
                                      "reason": "no games in the window to travel from"}
        p["read_inputs"]["results"]["through"] = "2026-09-23"
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "rest_travel"))
        gap = missing_inputs(read)["Red Sox travel"]
        self.assertIn("our results end 2026-09-23", gap["detail"])

    def test_stale_results_make_rest_days_a_named_gap(self):
        p = rich()
        sec(p, "teams").update(away_rest_days=10, home_rest_days=10)
        p["read_inputs"]["results"]["through"] = "2026-09-23"
        read = mr.build_read(p)
        gap = missing_inputs(read)["Days of rest"]
        self.assertEqual(gap["status"], "stale")
        self.assertIn("not a measured break", gap["detail"])
        f = factor(read, "rest_travel")
        self.assertNotIn("rest is 10 days", f["sentence"])

    def test_fresh_results_let_rest_into_the_sentence(self):
        f = factor(mr.build_read(rich()), "rest_travel")
        self.assertIn("rest is 1 days for the Red Sox and 1 for the Yankees", f["sentence"])

    def test_no_travel_section_is_a_named_gap(self):
        p = rich()
        del p["advanced"]["sections"]["travel"]
        p["advanced"]["gaps"]["travel"] = "travel load not computed"
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "rest_travel"))
        self.assertIn("Travel", missing_inputs(read))


class Bullpen(unittest.TestCase):
    def test_a_current_log_compares_the_two_pens(self):
        f = factor(mr.build_read(rich()), "bullpen")
        self.assertEqual(f["favours"], "NYY")             # 3 unavailable + 1 questionable against 1
        self.assertIn("14.0 relief innings in seven days across 8 pitchers", f["sentence"])
        self.assertIn("3 likely unavailable and 1 questionable", f["sentence"])

    def test_an_old_log_is_not_used_and_says_when_it_ends(self):
        p = rich()
        p["read_inputs"]["bullpen_log"]["through"] = "2026-09-06"
        for team in ("BOS", "NYY"):
            sec(p, "bullpen")[team] = pen(0.0, 0)
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "bullpen"))
        gap = missing_inputs(read)["Bullpen workload"]
        self.assertEqual(gap["status"], "stale")
        self.assertIn("our bullpen log ends 2026-09-06, 27 days before this game", gap["detail"])
        self.assertIn("0 relief outings", gap["detail"])

    def test_populated_rows_from_an_old_log_are_still_not_used(self):
        p = rich()
        p["read_inputs"]["bullpen_log"]["through"] = "2026-09-20"
        self.assertIsNone(factor(mr.build_read(p), "bullpen"))

    def test_an_unknown_log_age_is_not_trusted(self):
        p = rich()
        p["read_inputs"] = {}
        self.assertIsNone(factor(mr.build_read(p), "bullpen"))

    def test_equal_pens_favour_nobody(self):
        p = rich()
        sec(p, "bullpen")["BOS"] = pen(9.0, 7, 0, 1)
        self.assertEqual(factor(mr.build_read(p), "bullpen")["favours"], "even")

    def test_no_bullpen_section_is_a_named_gap(self):
        p = rich()
        del p["advanced"]["sections"]["bullpen"]
        p["advanced"]["gaps"]["bullpen"] = "bullpen workload not built"
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "bullpen"))
        self.assertIn("Bullpen workload", missing_inputs(read))


# ---------------------------------------------------------------------------
# Park and weather
# ---------------------------------------------------------------------------

class ParkAndWeather(unittest.TestCase):
    def test_a_fixed_roof_sets_the_weather_aside(self):
        p = rich()
        sec(p, "park")["roof"] = "fixed"
        f = factor(mr.build_read(p), "park_weather")
        self.assertIn("the roof is fixed, so the weather outside does not apply", f["sentence"])
        self.assertNotIn("forecast", f["sentence"])

    def test_a_retractable_roof_with_no_state_does_not_use_the_weather(self):
        p = rich()
        sec(p, "park")["roof"] = "retractable"
        read = mr.build_read(p)
        f = factor(read, "park_weather")
        self.assertIn("not on file, so the weather is not used", f["sentence"])
        self.assertIn("Roof state", missing_inputs(read))

    def test_a_hot_day_tilts_toward_runs_and_wind_direction_is_unreadable(self):
        p = rich()
        sec(p, "weather").update(temp_f=96.0, wind_mph=15.0)
        f = factor(mr.build_read(p), "park_weather")
        self.assertIn("warm air that carries the ball", f["sentence"])
        self.assertIn("direction we cannot read against this park", f["sentence"])
        self.assertIn("tilted toward runs", f["sentence"])
        self.assertIn("Park orientation is not on file", f["caveat"])
        self.assertEqual(f["favours"], "even")            # a park does not pick a side

    def test_a_cold_day_tilts_toward_pitchers(self):
        p = rich()
        sec(p, "weather")["temp_f"] = 45.0
        self.assertIn("tilted toward pitchers", factor(mr.build_read(p), "park_weather")["sentence"])

    def test_altitude_is_a_big_push(self):
        p = rich()
        sec(p, "park")["altitude_m"] = 1580
        f = factor(mr.build_read(p), "park_weather")
        self.assertEqual(f["size"], "moderate")
        self.assertIn("1580 metres", f["sentence"])

    def test_an_extreme_reading_is_flagged_for_a_check(self):
        p = rich()
        sec(p, "weather")["temp_f"] = 102.4
        self.assertIn("worth checking", factor(mr.build_read(p), "park_weather")["caveat"])

    def test_a_forecast_far_from_first_pitch_is_low_confidence(self):
        p = rich()
        sec(p, "weather")["hours_from_first_pitch"] = 7.0
        f = factor(mr.build_read(p), "park_weather")
        self.assertEqual(f["confidence"], "low")
        self.assertIn("7.0 hours from first pitch", f["caveat"])

    def test_rain_chance_is_reported(self):
        p = rich()
        sec(p, "weather")["precip_probability_pct"] = 60
        self.assertIn("60% chance of rain", factor(mr.build_read(p), "park_weather")["sentence"])

    def test_no_weather_is_a_named_gap_and_park_still_reads(self):
        p = rich()
        del p["advanced"]["sections"]["weather"]
        p["advanced"]["gaps"]["weather"] = "weather not fetched for this slate"
        read = mr.build_read(p)
        self.assertIn("Weather", missing_inputs(read))
        self.assertIsNotNone(factor(read, "park_weather"))

    def test_no_park_and_no_weather_is_a_named_gap(self):
        p = rich()
        del p["advanced"]["sections"]["weather"]
        del p["advanced"]["sections"]["park"]
        read = mr.build_read(p)
        self.assertIsNone(factor(read, "park_weather"))
        self.assertIn("Park and weather", missing_inputs(read))


# ---------------------------------------------------------------------------
# Run environment
# ---------------------------------------------------------------------------

class RunEnvironment(unittest.TestCase):
    def test_the_arithmetic_is_shown_step_by_step(self):
        env = mr.build_read(rich())["run_environment"]
        self.assertTrue(env["available"])
        self.assertIn("estimate", env["label"])
        self.assertIn("no track record", env["label"])
        text = "\n".join(env["arithmetic"])
        self.assertIn("League scoring: 4.50 runs per team per game over 2400 games", text)
        self.assertIn("offence", text)
        self.assertIn("run prevention", text)
        self.assertIn("home field credit", text)
        self.assertIn("park factor of 1.020", text)
        self.assertIn("standard error", text)

    def test_it_reuses_the_card_models_arithmetic(self):
        from src.analysis import strength
        p = rich()
        env = mr.build_read(p)["run_environment"]
        features = dict(sec(p, "teams"))
        features.update(sec(p, "starters"))
        features["park_factor"] = 1.02
        rm = strength.run_means(features, league_rpg=4.5)
        self.assertAlmostEqual(env["away"]["expected_runs"], round(rm["away_mean"], 2))
        self.assertAlmostEqual(env["home"]["expected_runs"], round(rm["home_mean"], 2))
        self.assertAlmostEqual(env["game"]["expected_total"],
                               round(rm["away_mean"] + rm["home_mean"], 2))

    def test_the_range_brackets_the_estimate(self):
        env = mr.build_read(rich())["run_environment"]
        for key in ("away", "home", "game"):
            row = env[key]
            self.assertLess(row["low"], row.get("expected_runs", row.get("expected_total")))
            self.assertGreater(row["high"], row.get("expected_runs", row.get("expected_total")))

    def test_the_leader_needs_a_clear_gap(self):
        env = mr.build_read(rich())["run_environment"]
        self.assertIn(env["leader"], ("BOS", "NYY", "even"))
        p = rich()
        sec(p, "teams").update(away_runs_scored_pg=4.4, home_runs_scored_pg=4.4,
                               away_runs_allowed_pg=4.2, home_runs_allowed_pg=4.2)
        sec(p, "starters").update(starter("away"), )
        sec(p, "starters").update(starter("home"))
        self.assertEqual(mr.build_read(p)["run_environment"]["leader"], "even")

    def test_a_missing_starter_falls_back_to_the_team_rate_and_says_so(self):
        p = rich()
        sec(p, "starters").update(starter("away", known=False))
        env = mr.build_read(p)["run_environment"]
        self.assertTrue(env["available"])
        self.assertIn("no starter line on file for Alan Away", "\n".join(env["arithmetic"]))

    def test_no_league_rate_means_no_estimate(self):
        p = rich()
        p["read_inputs"]["league_runs_per_game"] = {"value": None, "games": 0}
        read = mr.build_read(p)
        self.assertFalse(read["run_environment"]["available"])
        self.assertIn("no league run rate", read["run_environment"]["reason"])
        self.assertEqual(missing_inputs(read)["Run estimate"]["status"], "absent")

    def test_no_read_inputs_at_all_means_no_estimate_and_no_trusted_age(self):
        p = rich()
        del p["read_inputs"]
        read = mr.build_read(p)
        self.assertFalse(read["run_environment"]["available"])
        self.assertIn("Age of our data", missing_inputs(read))

    def test_weather_is_stated_to_be_outside_the_arithmetic(self):
        caveats = " ".join(mr.build_read(rich())["run_environment"]["caveats"])
        self.assertIn("Weather is not in this arithmetic", caveats)
        self.assertIn("Lineups are not in this arithmetic", caveats)

    def test_stale_inputs_are_named_in_the_caveats(self):
        p = rich()
        p["read_inputs"]["results"]["through"] = "2026-09-23"
        p["read_inputs"]["pitcher_logs"]["through"] = "2026-09-07"
        caveats = " ".join(mr.build_read(p)["run_environment"]["caveats"])
        self.assertIn("Our results end 2026-09-23", caveats)
        self.assertIn("Our pitcher logs end 2026-09-07", caveats)


# ---------------------------------------------------------------------------
# Market view
# ---------------------------------------------------------------------------

class MarketView(unittest.TestCase):
    def test_it_states_what_the_price_implies_with_the_book_count(self):
        mv = mr.build_read(rich())["market_view"]
        self.assertTrue(mv["available"])
        self.assertIn("Across 9 books the market makes the Yankees a 58.0% favourite", mv["sentences"][0])
        self.assertIn("a fair price of -138", mv["sentences"][0])
        self.assertEqual(mv["implied"]["home"]["probability"], 0.58)

    def test_agreement_is_called_agreement_and_not_a_verdict_on_the_price(self):
        p = rich()
        sec(p, "starters").update(starter("home", fip=2.5))
        sec(p, "teams").update(home_run_diff_pg=1.5, away_run_diff_pg=0.0)
        mv = mr.build_read(p)["market_view"]
        self.assertEqual(mv["agreement"], "agrees")
        self.assertIn("says nothing about whether the price is right", " ".join(mv["sentences"]))

    def test_disagreement_with_thin_inputs_is_more_likely_our_error(self):
        p = rich()
        # Lean toward the underdog (BOS) while several inputs are missing or stale.
        sec(p, "starters").update(starter("away", fip=2.8, whip=1.0, kbb=0.22),)
        sec(p, "starters").update(starter("home", fip=4.2, whip=1.3, kbb=0.10))
        del p["advanced"]["sections"]["lineups"]
        del p["advanced"]["sections"]["matchup_history"]
        p["read_inputs"]["results"]["through"] = "2026-09-23"
        p["read_inputs"]["pitcher_logs"]["through"] = "2026-09-07"
        p["read_inputs"]["bullpen_log"]["through"] = "2026-09-06"
        mv = mr.build_read(p)["market_view"]
        self.assertEqual(mv["agreement"], "disagrees")
        text = " ".join(mv["sentences"])
        self.assertIn("the likelier explanation is that our read is missing something", text)
        self.assertIn("not that the price is wrong", text)

    def test_disagreement_with_full_inputs_is_still_a_question_not_a_finding(self):
        p = rich()
        sec(p, "starters").update(starter("away", fip=2.8, whip=1.0, kbb=0.22),)
        sec(p, "starters").update(starter("home", fip=4.2, whip=1.3, kbb=0.10))
        mv = mr.build_read(p)["market_view"]
        self.assertEqual(mv["agreement"], "disagrees")
        self.assertIn("a question to check, not a finding", " ".join(mv["sentences"]))

    def test_a_balanced_read_declines_to_lean(self):
        p = rich()
        sec(p, "starters").update(starter("away", fip=3.5, whip=1.1, kbb=0.15))
        sec(p, "starters").update(starter("home", fip=3.5, whip=1.1, kbb=0.15))
        sec(p, "teams").update(away_run_diff_pg=0.3, home_run_diff_pg=0.3)
        for key in ("matchup_history", "arsenals", "lineups", "bullpen", "travel"):
            del p["advanced"]["sections"][key]
        mv = mr.build_read(p)["market_view"]
        self.assertEqual(mv["agreement"], "no lean")
        self.assertEqual(mv["lean"], "none")
        self.assertIn("the price is the better informed number", " ".join(mv["sentences"]))

    def test_no_board_is_said_plainly(self):
        p = rich()
        del p["advanced"]["sections"]["price_improvement"]
        read = mr.build_read(p)
        self.assertFalse(read["market_view"]["available"])
        self.assertEqual(read["market_view"]["agreement"], "no price")
        self.assertIn("Market price", missing_inputs(read))

    def test_an_old_board_says_how_old(self):
        p = rich()
        p["price_verdicts"]["home"]["age_seconds"] = 2700
        self.assertIn("45 minutes", " ".join(mr.build_read(p)["market_view"]["sentences"]))

    def test_the_research_note_is_always_there_and_claims_no_advantage(self):
        text = " ".join(mr.build_read(rich())["market_view"]["sentences"])
        self.assertIn("none held up as a betting advantage", text)


# ---------------------------------------------------------------------------
# What would change it, headline, missing, notices
# ---------------------------------------------------------------------------

class WhatWouldChangeIt(unittest.TestCase):
    def test_it_names_two_or_three_facts(self):
        items = mr.build_read(rich())["what_would_change_it"]
        self.assertTrue(2 <= len(items) <= 3)
        for item in items:
            self.assertTrue(item["fact"].endswith("."))
            self.assertTrue(item["because"])

    def test_a_posted_lineup_names_the_top_of_each_order(self):
        items = mr.build_read(rich())["what_would_change_it"]
        scratch = [i for i in items if "scratch" in i["fact"]][0]
        self.assertIn("Away Hitter 1", scratch["because"])
        self.assertIn("Home Hitter 3", scratch["because"])

    def test_an_unposted_lineup_carries_the_starters_platoon_split(self):
        p = rich()
        del p["advanced"]["sections"]["lineups"]
        items = mr.build_read(p)["what_would_change_it"]
        lineup = [i for i in items if "lineups" in i["fact"]][0]
        self.assertIn("Henry Home has been weaker against left-handed bats", lineup["because"])
        self.assertIn("120 and 400 batters faced", lineup["because"])

    def test_a_missing_starter_is_named_as_the_biggest_mover(self):
        p = rich()
        sec(p, "starters").update(starter("away", known=False))
        first = mr.build_read(p)["what_would_change_it"][0]
        self.assertIn("starting pitcher", first["fact"])
        self.assertIn("Alan Away has no line on file", first["because"])

    def test_a_retractable_roof_is_a_thing_that_would_change_it(self):
        p = rich()
        sec(p, "park")["roof"] = "retractable"
        facts = " ".join(i["fact"] for i in mr.build_read(p)["what_would_change_it"])
        self.assertIn("roof", facts)

    def test_an_open_park_names_the_forecast(self):
        facts = " ".join(i["fact"] for i in mr.build_read(rich())["what_would_change_it"])
        self.assertIn("forecast", facts)


class Headline(unittest.TestCase):
    def test_it_is_one_sentence_naming_the_top_factor(self):
        read = mr.build_read(rich())
        self.assertEqual(read["headline"].count(". "), 0)
        self.assertTrue(read["headline"].endswith("."))
        top = read["factors"][0]
        self.assertTrue(top["short"].rstrip(".") in read["headline"])

    def test_a_thin_top_factor_says_the_data_is_thin(self):
        p = rich()
        # Strip everything except a thin season comparison.
        for key in list(p["advanced"]["sections"]):
            if key not in ("teams", "price_improvement", "park"):
                del p["advanced"]["sections"][key]
        sec(p, "teams").update(away_games_played=20, away_run_diff_pg=1.5, home_run_diff_pg=0.1)
        read = mr.build_read(p)
        self.assertEqual(read["factors"][0]["confidence"], "low")
        self.assertTrue("data behind it is thin" in read["headline"]
                        or "No single factor" in read["headline"])

    def test_nothing_clear_is_a_valid_headline_and_names_what_is_missing(self):
        p = rich()
        for key in list(p["advanced"]["sections"]):
            if key != "teams":
                del p["advanced"]["sections"][key]
        sec(p, "teams").update(away_run_diff_pg=0.3, home_run_diff_pg=0.3)
        p["advanced"]["gaps"]["starters"] = "no pitcher logs"
        read = mr.build_read(p)
        self.assertIn("No single factor clearly separates the Red Sox and the Yankees", read["headline"])
        self.assertIn("a valid read", read["headline"])

    def test_a_missing_starter_leads_when_nothing_else_is_big(self):
        p = rich()
        sec(p, "starters").update(starter("away", known=False))
        for key in ("arsenals", "lineups", "matchup_history", "bullpen", "travel", "splits"):
            del p["advanced"]["sections"][key]
        sec(p, "teams").update(away_run_diff_pg=0.4, home_run_diff_pg=0.2)
        read = mr.build_read(p)
        self.assertIn("Henry Home has a pitching line on file", read["headline"])
        self.assertIn("Alan Away does not", read["headline"])

    def test_a_large_factor_beats_the_missing_starter_headline(self):
        p = rich()
        sec(p, "starters").update(starter("away", known=False))
        sec(p, "teams").update(away_run_diff_pg=-0.8, home_run_diff_pg=0.6)
        read = mr.build_read(p)
        self.assertIn("The Yankees have the better season run margin", read["headline"])
        self.assertIn("Alan Away has no pitching line on file", read["headline"])


class TheMissingList(unittest.TestCase):
    def test_stale_stores_are_named_with_their_dates(self):
        p = rich()
        p["read_inputs"]["results"]["through"] = "2026-09-23"
        p["read_inputs"]["pitcher_logs"]["through"] = "2026-09-07"
        m = missing_inputs(mr.build_read(p))
        self.assertIn("our results end 2026-09-23, 10 days before this game", m["Team results"]["detail"])
        self.assertIn("our pitcher logs end 2026-09-07, 26 days before this game", m["Pitcher logs"]["detail"])
        self.assertIn("14 or more days is not reliable", m["Pitcher logs"]["detail"])

    def test_fresh_stores_add_nothing(self):
        m = missing_inputs(mr.build_read(rich()))
        self.assertNotIn("Team results", m)
        self.assertNotIn("Pitcher logs", m)

    def test_an_old_platoon_split_is_named_stale(self):
        p = rich()
        sec(p, "splits")["home"]["record"]["as_of"] = "2026-09-08T20:37:59+00:00"
        m = missing_inputs(mr.build_read(p))
        self.assertEqual(m["Henry Home platoon split"]["status"], "stale")

    def test_gaps_the_payload_reports_are_carried_with_their_reasons(self):
        p = rich()
        del p["advanced"]["sections"]["splits"]
        p["advanced"]["gaps"].update(splits="pitcher platoon splits not fetched",
                                     standings="no standings snapshot stored for 2026-10-03")
        m = missing_inputs(mr.build_read(p))
        self.assertEqual(m["Pitcher platoon splits"]["detail"], "pitcher platoon splits not fetched")
        self.assertIn("no standings snapshot", m["League standings"]["detail"])

    def test_every_entry_is_plain_words(self):
        p = rich()
        p["read_inputs"]["results"]["through"] = "2026-09-23"
        for entry in mr.build_read(p)["missing"]:
            self.assertIn(entry["status"], ("absent", "stale", "thin", "error"))
            self.assertTrue(entry["input"] and entry["detail"])

    def test_a_duplicate_gap_is_listed_once(self):
        read = mr.build_read(rich())
        keys = [(m["input"], m["status"]) for m in read["missing"]]
        self.assertEqual(len(keys), len(set(keys)))


class Notices(unittest.TestCase):
    def test_a_game_already_under_way_says_the_read_is_pregame(self):
        p = rich()
        p["advanced"]["game"].update(detailed_state="In Progress", away_score=0, home_score=0)
        notes = mr.build_read(p)["notices"]
        self.assertTrue([n for n in notes if "under way" in n and "before first pitch" in n])

    def test_a_pregame_state_has_no_notice(self):
        p = rich()
        p["advanced"]["game"].update(detailed_state="Pre-Game", away_score=0, home_score=0)
        self.assertEqual(mr.build_read(p)["notices"], [])

    def test_a_scheduled_game_has_no_notice(self):
        self.assertEqual(mr.build_read(rich())["notices"], [])


# ---------------------------------------------------------------------------
# Golden: 2026-10-03's four real payloads
# ---------------------------------------------------------------------------

def _load(away, home):
    path = FIXTURES / f"matchup_read_2026-10-03_{away}_{home}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class GoldenReadsFor2026_10_03(unittest.TestCase):
    def test_the_fixtures_exist_and_are_real_payloads(self):
        for away, home in GOLDEN:
            p = _load(away, home)
            self.assertEqual(p["advanced"]["game"]["date"], "2026-10-03")
            self.assertEqual((p["advanced"]["game"]["away_team"], p["advanced"]["game"]["home_team"]),
                             (away, home))
            self.assertIn("read_inputs", p)

    def test_the_read_rebuilds_byte_for_byte_from_the_stored_payload(self):
        for away, home in GOLDEN:
            p = _load(away, home)
            stored = p.pop("read")
            with self.subTest(game=f"{away}@{home}"):
                self.assertEqual(mr.build_read(p), stored,
                                 "the read changed: run scripts/regen_matchup_read_fixtures.py "
                                 "and review the fixture diff")

    def test_every_evidence_path_resolves_in_each_real_payload(self):
        for away, home in GOLDEN:
            p = _load(away, home)
            read = p["read"]
            with self.subTest(game=f"{away}@{home}"):
                evidence = all_evidence(read)
                self.assertGreater(len(evidence), 10)
                for e in evidence:
                    found, value = mr.resolve_path(p, e["path"])
                    self.assertTrue(found, f"unresolved: {e}")
                    if not e.get("derived"):
                        self.assertEqual(value, e["value"], e)

    def test_no_real_read_has_an_error_entry_or_banned_wording(self):
        for away, home in GOLDEN:
            read = _load(away, home)["read"]
            with self.subTest(game=f"{away}@{home}"):
                self.assertEqual([m for m in read["missing"] if m["status"] == "error"], [])
                self.assertEqual(banned_hits(read), [])

    def test_every_real_read_names_its_stale_inputs(self):
        for away, home in GOLDEN:
            read = _load(away, home)["read"]
            m = missing_inputs(read)
            with self.subTest(game=f"{away}@{home}"):
                self.assertIn("our results end 2026-09-23", m["Team results"]["detail"])
                self.assertIn("our pitcher logs end 2026-09-07", m["Pitcher logs"]["detail"])
                self.assertEqual(m["Bullpen workload"]["status"], "stale")
                self.assertIn("Days of rest", m)

    def test_no_real_read_uses_the_stale_rest_or_the_empty_bullpen(self):
        for away, home in GOLDEN:
            read = _load(away, home)["read"]
            with self.subTest(game=f"{away}@{home}"):
                self.assertIsNone(factor(read, "bullpen"))
                self.assertIsNone(factor(read, "rest_travel"))

    def test_the_log_gaps_are_called_ours_where_the_pitch_file_shows_the_pitcher(self):
        m = missing_inputs(_load("ATL", "LAD")["read"])
        self.assertIn("gap is in our log", m["Dylan Dodd (starter line)"]["detail"])
        m = missing_inputs(_load("CWS", "CLE")["read"])
        self.assertIn("nothing can be said", m["Hagen Smith (starter line)"]["detail"])

    def test_the_game_in_progress_is_flagged_as_a_pregame_read(self):
        read = _load("CWS", "CLE")["read"]
        self.assertTrue([n for n in read["notices"] if "under way" in n])

    def test_the_starting_pitching_headlines_are_what_the_data_supports(self):
        self.assertIn("Drew Rasmussen (2.99 FIP) is the better starter than Gerrit Cole (3.86 FIP)",
                      _load("NYY", "TB")["read"]["headline"])
        self.assertIn("Jacob Misiorowski (2.31 FIP) is the better starter than Robbie Ray (4.88 FIP)",
                      _load("SD", "MIL")["read"]["headline"])
        for away, home in (("CWS", "CLE"), ("ATL", "LAD")):
            self.assertIn("does not, so the starting pitching matchup cannot be read",
                          _load(away, home)["read"]["headline"])

    def test_the_only_game_with_lineups_reads_them(self):
        read = _load("CWS", "CLE")["read"]
        keys = {f["factor"] for f in read["factors"]}
        self.assertTrue({"platoon", "lineup_depth", "pitch_mix", "batter_vs_pitcher"} <= keys)
        for away, home in (("ATL", "LAD"), ("NYY", "TB"), ("SD", "MIL")):
            keys = {f["factor"] for f in _load(away, home)["read"]["factors"]}
            self.assertFalse({"platoon", "lineup_depth", "pitch_mix"} & keys)

    def test_the_covered_roof_games_do_not_use_the_weather(self):
        tb = factor(_load("NYY", "TB")["read"], "park_weather")
        self.assertIn("the roof is fixed", tb["sentence"])
        mil = factor(_load("SD", "MIL")["read"], "park_weather")
        self.assertIn("not on file, so the weather is not used", mil["sentence"])

    def test_the_doc_holds_every_sentence_of_every_real_read_verbatim(self):
        doc = (Path(__file__).resolve().parent.parent / "docs" / "MATCHUP_READ.md"
               ).read_text(encoding="utf-8")
        for away, home in GOLDEN:
            read = _load(away, home)["read"]
            with self.subTest(game=f"{away}@{home}"):
                self.assertIn(read["headline"], doc)
                for f in read["factors"]:
                    self.assertIn(f["sentence"], doc)
                    self.assertIn(f["caveat"], doc)
                for line in read["run_environment"]["arithmetic"]:
                    self.assertIn(line, doc)
                for s in read["market_view"]["sentences"]:
                    self.assertIn(s, doc)
                for w in read["what_would_change_it"]:
                    self.assertIn(w["because"], doc)
                for m in read["missing"]:
                    self.assertIn(m["detail"], doc)
        generated = doc.split("<!-- READS:START -->")[1].split("<!-- READS:END -->")[0]
        self.assertNotIn("—", doc)
        self.assertNotIn("–", generated)

    def test_each_run_estimate_is_labelled_and_has_its_arithmetic(self):
        for away, home in GOLDEN:
            env = _load(away, home)["read"]["run_environment"]
            with self.subTest(game=f"{away}@{home}"):
                self.assertTrue(env["available"])
                self.assertIn("no track record", env["label"])
                self.assertGreaterEqual(len(env["arithmetic"]), 9)


# ---------------------------------------------------------------------------
# The route: the read is served under `read`, and never costs the page
# ---------------------------------------------------------------------------

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

if HAS_FASTAPI:
    from api import games as games_mod
    from src.providers import mlb
    from tests.test_api_games import _ResetEntriesCache, _schedule
else:
    # Linux CI has no FastAPI. The class below is skipped there, but its base must
    # still exist when the module is imported, or the whole module fails to load
    # (2026-10-03: CI reported tests.test_matchup_read as an import error).
    _ResetEntriesCache = unittest.TestCase


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRouteServesTheRead(_ResetEntriesCache):
    def test_the_game_payload_carries_the_read_and_its_inputs(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            payload = games_mod.get_game("2026-08-31", "BOS", "NYY")
        blob = json.loads(json.dumps(payload))
        self.assertIn("read", blob)
        self.assertIn("read_inputs", blob)
        read = blob["read"]
        self.assertTrue(read["headline"])
        self.assertIn("results", blob["read_inputs"])
        self.assertIn("league_runs_per_game", blob["read_inputs"])
        # every evidence path in the served read resolves in the served payload
        without = {k: v for k, v in blob.items() if k != "read"}
        for e in all_evidence(read):
            self.assertTrue(mr.resolve_path(without, e["path"])[0], e)

    def test_the_read_does_not_change_any_existing_part_of_the_payload(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            payload = games_mod.get_game("2026-08-31", "BOS", "NYY")
        for key in ("quick", "advanced", "freshness", "engine", "price_verdicts"):
            self.assertIn(key, payload)
        self.assertNotIn("read", payload["advanced"])
        self.assertNotIn("read", payload["quick"])

    def test_a_failing_read_costs_the_read_and_not_the_page(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
                patch.object(games_mod.matchup_read, "build_read", side_effect=RuntimeError("x")):
            payload = games_mod.get_game("2026-08-31", "BOS", "NYY")
        self.assertIsNone(payload["read"])
        self.assertIn("quick", payload)
        self.assertIn("advanced", payload)

    def test_an_unreadable_results_store_leaves_the_read_honest_about_its_age(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
                patch.object(games_mod.read_context, "build", side_effect=OSError("gone")), \
                patch.object(games_mod, "_read_inputs_cache",
                             games_mod.freshness.SingleFlightTTLCache(ttl_s=1.0)):
            payload = games_mod.get_game("2026-08-31", "BOS", "NYY")
        self.assertEqual(payload["read_inputs"], {})
        names = {m["input"] for m in payload["read"]["missing"]}
        self.assertIn("Age of our data", names)

    def test_a_game_with_no_stores_still_gets_a_complete_read(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            read = games_mod.get_game("2026-08-31", "BOS", "NYY")["read"]
        for key in ("headline", "factors", "run_environment", "market_view",
                    "what_would_change_it", "missing"):
            self.assertIn(key, read)


if __name__ == "__main__":
    unittest.main()
