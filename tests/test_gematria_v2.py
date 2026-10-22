"""Gematria rules v2 (config/gematria/rules_v2.json, owner request 2026-10-22) and the server half of the visible analysis.

THE STORY. A member's Gematria hound answered Unleash with "Checked 60 games: 60 rule not met -> placed 0": rules v1 passed every game of a
sport with no stored results (64 of 82 on the day it was diagnosed) and every game of a season a few days old, and Unleash never reached the
Gematria style's games more than an hour from their start. v2 is calibrated on PICK RATE alone (research/rabbitszn/METHOD.md, "Rules v2:
pre-registration"). What this file holds:

  * the file: v2 loads, is the active one, v1 is byte-for-byte what it was, the -200 cap is a load-time error;
  * the pick rate: a fixture day lands in the pre-registered 2-to-5 range, and v1 on the same day picks nothing;
  * NO RESULTS ARE USED: planting results (after the lock, and where no store exists) changes no pick; the calibration script reads none;
  * the static fallback: thin counts and no stored results are scored, not passed; an unknown team is read by its name;
  * the noise-scaled margin: the same lead passes in a quiet game and fails in a loud one;
  * the day's ranking, the -200 cap and one side per game;
  * the analysis the page plays: every line is formatted from a value the engine computed, the payload is capped, picks come first.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.hounds import ai_defs, user_gematria
from src.hounds.gematria import decision as decision_mod
from src.hounds.gematria import facts as facts_mod
from src.hounds.gematria import history, rules as rules_mod, runtime as rt, signals as sig_mod
from src.hounds.interact import common, gematria_analysis as ga, unleash_why
from src.hounds.pack import base
from src.research import gematria as g
from tests.test_ai_hounds import allsports_rows, allsports_stores
from tests.test_gematria_hound import G, NBA_FACTS, StubSource, inputs_for, season_games

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc

V1_SHA = "c6f9c7bbefcd298e9053ed821653705ce09b3c314849f8ecccc21f31ca5f7711"      # rules_v1.json (LF bytes): frozen, never edited


def v2_dict() -> dict:
    return copy.deepcopy(json.loads((ROOT / "config" / "gematria" / "rules_v2.json").read_text(encoding="utf-8")))


def v2_rules(**decision) -> rules_mod.Rules:
    data = v2_dict()
    data["decision"].update(decision)
    return rules_mod.Rules.from_dict(data, raw_bytes=b"test-v2", source="test")


#: a natural fixture day: twelve famous fixtures, none of them in the facts layer, in a league with no stored results
MATCHES = [("Arsenal", "Chelsea"), ("Liverpool", "Everton"), ("Tottenham Hotspur", "West Ham United"), ("Manchester City", "Aston Villa"),
           ("Newcastle United", "Brighton and Hove Albion"), ("Fulham", "Brentford"), ("Leeds United", "Wolverhampton Wanderers"),
           ("Real Madrid", "Sevilla"), ("Barcelona", "Valencia"), ("Juventus", "Napoli"), ("AC Milan", "Inter Milan"),
           ("Bayern Munich", "Borussia Dortmund")]


def day_store(matches=MATCHES):
    rows = [allsports_rows(f"s{i}", "soccer", a, h, title="Fixture League", home_ml=-120 + (i % 3) * 10, away_ml=100 + (i % 2) * 15, draw=230)
            for i, (a, h) in enumerate(matches)]
    return allsports_stores(*rows)


def weigh_day(rules, source=None, matches=MATCHES):
    st = day_store(matches)
    run = rt.GematriaRuntime(rules=rules, source=source or StubSource([], available=False), ledger=None)
    out = []
    for i in range(len(matches)):
        ctx = base.build_context(st, f"s{i}")
        out.append((ctx, run.weigh(ctx, base.lock_board(st, ctx)), run))
    return out


# ---------------------------------------------------------------------------------------------------
# the file
# ---------------------------------------------------------------------------------------------------

class TheRulesFile(unittest.TestCase):
    def test_v2_is_the_active_file_and_stamps_its_own_hash(self):
        active = json.loads((ROOT / "config" / "gematria" / "active.json").read_text(encoding="utf-8"))
        self.assertEqual(active["rules"], "rules_v2.json")
        r = rules_mod.load()
        self.assertEqual((r.version, r.hound_version, r.hound_number, r.source), ("v2", "gematria-v2", 2, "rules_v2.json"))
        v1 = rules_mod.load("rules_v1.json")
        self.assertNotEqual(r.rules_hash, v1.rules_hash)           # the stamp on a bet row tells the two apart: v1's history stays v1's

    def test_v1_is_exactly_what_it_was(self):
        raw = (ROOT / "config" / "gematria" / "rules_v1.json").read_bytes().replace(chr(13).encode() + chr(10).encode(), chr(10).encode())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), V1_SHA)
        v1 = rules_mod.load("rules_v1.json")
        self.assertEqual((v1.rules_hash, v1.static_fallback, v1.name_only_teams, v1.decision.margin_mode, v1.decision.min_margin),
                         (V1_SHA, False, False, "fixed", 3.0))

    def test_what_v2_changes_and_what_it_does_not(self):
        v1, v2 = rules_mod.load("rules_v1.json"), rules_mod.load("rules_v2.json")
        self.assertEqual((v2.static_fallback, v2.name_only_teams, v2.decision.margin_mode), (True, True, "noise_scaled"))
        self.assertEqual((v2.decision.min_margin, v2.decision.min_z, v2.decision.max_search_imbalance, v2.decision.max_picks_per_day), (1.0, 1.0, 0.5, 5))
        for same in ("markets", "price_band", "lock_minutes", "min_milestones_per_side"):
            self.assertEqual(getattr(v1.decision, same), getattr(v2.decision, same), same)
        self.assertEqual((v2.ciphers, v2.special_numbers, v2.min_value, v2.max_value), (v1.ciphers, v1.special_numbers, v1.min_value, v1.max_value))
        for kind, weight in v1.kind_weights.items():
            self.assertEqual(v2.kind_weights[kind], weight, kind)
        self.assertEqual({k: v2.kind_weights[k] for k in rules_mod.STATIC_KINDS},
                         {"static_eq_date": 1.0, "static_eq_static": 0.5, "static_special_33_47": 1.0})

    def test_the_minus_200_cap_is_a_load_error_in_v2_too(self):
        data = v2_dict()
        data["decision"]["price_band"] = [-200, 400]
        with self.assertRaises(rules_mod.RulesError):
            rules_mod.Rules.from_dict(data)
        self.assertEqual(rules_mod.load("rules_v2.json").decision.price_band, (-199, 400))

    def test_static_fallback_needs_its_weights_and_a_margin_mode_must_be_known(self):
        data = v2_dict()
        del data["kind_weights"]["static_eq_date"]
        with self.assertRaises(rules_mod.RulesError):
            rules_mod.Rules.from_dict(data)
        data = v2_dict()
        data["decision"]["margin_mode"] = "vibes"
        with self.assertRaises(rules_mod.RulesError):
            rules_mod.Rules.from_dict(data)
        data = v2_dict()
        data["kind_weights"]["made_up"] = 1.0
        with self.assertRaises(rules_mod.RulesError):
            rules_mod.Rules.from_dict(data)

    def test_the_pre_registration_note_names_the_date_the_values_and_that_no_outcome_was_read(self):
        note = (ROOT / "research" / "rabbitszn" / "METHOD.md").read_text(encoding="utf-8")
        self.assertIn("## Rules v2: pre-registration", note)
        section = note[note.index("## Rules v2: pre-registration"):]
        self.assertIn("2026-10-22", section)
        self.assertIn("Outcomes consulted: none", section)
        d = rules_mod.load("rules_v2.json").decision
        for value in (f"`min_z` = **{d.min_z}**", f"**{d.min_margin}**", f"**{d.max_search_imbalance}**", f"**{d.max_picks_per_day}**"):
            self.assertIn(value, section)
        self.assertIn("rules_v2.json", section)


# ---------------------------------------------------------------------------------------------------
# the pick rate
# ---------------------------------------------------------------------------------------------------

class ThePickRate(unittest.TestCase):
    def test_a_fixture_day_lands_in_the_pre_registered_two_to_five_range(self):
        rules = rules_mod.load("rules_v2.json")
        weighed = weigh_day(rules)
        bets = [w for _c, w, _r in weighed if w.verdict.is_bet]
        self.assertGreaterEqual(len(bets), 2)
        self.assertLessEqual(min(len(bets), rules.decision.max_picks_per_day), 5)
        self.assertTrue(all(w.verdict.basis == "static" for _c, w, _r in weighed), "no stored results for the league: every game is read statically")

    def test_rules_v1_makes_no_pick_on_the_same_day(self):
        weighed = weigh_day(rules_mod.load("rules_v1.json"))
        codes = {w.verdict.code for _c, w, _r in weighed}
        self.assertFalse(any(w.verdict.is_bet for _c, w, _r in weighed))
        self.assertEqual(codes, {"no_history"})

    def test_every_pick_says_how_it_was_read_and_how_loud_the_game_was(self):
        for _ctx, w, _run in weigh_day(rules_mod.load("rules_v2.json")):
            if w.verdict.is_bet:
                self.assertEqual(w.block["basis"], "static")
                self.assertGreaterEqual(w.block["z"], rules_mod.load("rules_v2.json").decision.min_z)
                self.assertEqual(w.block["rules_version"], "v2")
                self.assertIn("static evidence", w.block["history"])

    def test_the_v1_block_is_unchanged_by_the_new_keys(self):
        st = allsports_stores(allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=-120, away_ml=100))
        ctx = base.build_context(st, "nba1")
        run = rt.GematriaRuntime(rules=rules_mod.load("rules_v1.json"), facts=NBA_FACTS, source=StubSource(season_games()), ledger=None)
        w = run.weigh(ctx, base.lock_board(st, ctx))
        self.assertNotIn("basis", w.block)
        self.assertNotIn("z", w.block)

    def test_the_calibration_script_prints_pick_counts_and_reads_no_outcome(self):
        src = (ROOT / "research" / "rabbitszn" / "v2_pick_rate.py").read_text(encoding="utf-8")
        for token in ("settle", "graded", "home_score", "away_score", "winner", "final_score", "results.csv", "ledger.csv", "mlb_results", "games.jsonl"):
            self.assertNotIn(token, src, token)
        self.assertIn("PICK COUNTS ONLY", src)


# ---------------------------------------------------------------------------------------------------
# no results
# ---------------------------------------------------------------------------------------------------

class NoResultIsUsed(unittest.TestCase):
    def planted(self, ctx):
        """Results for the very teams, including the game itself and everything after the lock: what a leak would look like."""
        h, a = g.normalize(ctx.home_name), g.normalize(ctx.away_name)
        day = ctx.start.date().isoformat()
        out = []
        for i in range(1, 12):
            out.append(history.Game(ctx.start - timedelta(days=i), (ctx.start - timedelta(days=i)).date().isoformat(), h, a, 100 + i, 90, regular=True))
        out.append(history.Game(ctx.start, day, h, a, 3, 0, regular=True))                                # the game itself, final
        out.append(history.Game(ctx.start + timedelta(hours=3), day, a, h, 7, 1, regular=True))          # after it
        return out

    def snapshot(self, weighed):
        return [(c.event_id, w.verdict.status, w.verdict.code, w.verdict.side, w.verdict.price, w.verdict.scores, w.verdict.z, w.block and w.block["inputs_hash"])
                for c, w, _r in weighed]

    def test_planting_results_where_no_store_exists_changes_no_pick(self):
        rules = rules_mod.load("rules_v2.json")
        plain = self.snapshot(weigh_day(rules))
        st = day_store()
        every = []
        for i in range(len(MATCHES)):
            every += self.planted(base.build_context(st, f"s{i}"))
        # a source that HAS the results but says the sport has no store (history unavailable): the static basis ignores all of them
        again = self.snapshot(weigh_day(rules, source=StubSource(every, available=False)))
        self.assertEqual(plain, again)
        self.assertTrue(any(row[1] == "bet" for row in plain))

    def test_results_at_or_after_the_cutoff_change_no_pick_even_when_the_store_exists(self):
        rules = rules_mod.load("rules_v2.json")
        st = day_store()
        late = []
        for i in range(len(MATCHES)):
            ctx = base.build_context(st, f"s{i}")
            h, a = g.normalize(ctx.home_name), g.normalize(ctx.away_name)
            cutoff = ctx.lock - history.FINISH_LAG
            for k in range(8):        # eight finished results, every one at or after the cutoff: none may count
                when = cutoff + timedelta(minutes=k)
                late.append(history.Game(when, when.date().isoformat(), h, a, 100 + k, 90, regular=True))
        empty = self.snapshot(weigh_day(rules, source=StubSource([], available=True)))
        planted = self.snapshot(weigh_day(rules, source=StubSource(late, available=True)))
        self.assertEqual(empty, planted)

    def test_the_static_world_reads_no_milestone(self):
        rules = rules_mod.load("rules_v2.json")
        inputs = sig_mod.GameInputs("2026-10-20", sig_mod.TeamInputs(NBA_FACTS.team("nba", "New York Knicks")),
                                    sig_mod.TeamInputs(NBA_FACTS.team("nba", "Boston Celtics")), None, False)
        sig = sig_mod.generate(inputs, rules)
        self.assertEqual(sig.basis, "static")
        allowed = {"own_name_eq_date", "static_eq_date", "static_eq_static", "static_special_33_47", "prime_link", "triangular_link"}
        for side in (sig.home, sig.away):
            self.assertTrue({e.kind for e in side.evidence} <= allowed, {e.kind for e in side.evidence})
            for e in side.evidence:
                for q in (e.a, e.b):
                    self.assertTrue(q is None or q.group != "milestone")


# ---------------------------------------------------------------------------------------------------
# the static fallback
# ---------------------------------------------------------------------------------------------------

class TheStaticFallback(unittest.TestCase):
    def inputs(self, home_games, away_games, rules, available=True):
        gi = inputs_for(home_games, away_games, rules)
        gi.history_available = available
        return gi

    def test_thin_counts_are_scored_not_passed(self):
        v1, v2 = rules_mod.load("rules_v1.json"), rules_mod.load("rules_v2.json")
        thin = [G("2026-10-19", "New York Knicks", "Brooklyn Nets", 100, 90, regular=True)]              # a season two days old: one game each
        thin_away = [G("2026-10-19", "Boston Celtics", "Miami Heat", 100, 90, regular=True)]
        board = {"markets": {"moneyline": {"sides": {"home": {"price_average": 110}, "away": {"price_average": 105}}}}}
        s1 = sig_mod.generate(self.inputs(thin, thin_away, v1), v1)
        self.assertEqual(decision_mod.decide(s1, board, v1, history_available=True, teams_known=True).code, "thin_data")
        s2 = sig_mod.generate(self.inputs(thin, thin_away, v2), v2)
        self.assertEqual(s2.basis, "static")
        verdict = decision_mod.decide(s2, board, v2, history_available=True, teams_known=True)
        self.assertNotIn(verdict.code, ("thin_data", "no_history"))
        self.assertEqual(verdict.basis, "static")

    def test_a_deep_season_keeps_the_season_basis(self):
        v2 = v2_rules(min_milestones_per_side=1)          # the fixture's season is short; the gate is what is being shown
        sig = sig_mod.generate(inputs_for(season_games(), season_games(), v2), v2)
        self.assertEqual(sig.basis, "season")
        self.assertGreaterEqual(min(sig.home.milestones, sig.away.milestones), 1)
        thin = sig_mod.generate(inputs_for(season_games(), season_games(), v2), rules_mod.load("rules_v2.json"))
        self.assertEqual(thin.basis, "static", "the same games under the shipped gate of 3 counts a side are too thin: read statically")

    def test_no_stored_results_is_scored_not_passed_as_no_history(self):
        board = {"markets": {"moneyline": {"sides": {"home": {"price_average": 110}, "away": {"price_average": 105}}}}}
        v1, v2 = rules_mod.load("rules_v1.json"), rules_mod.load("rules_v2.json")
        gi = sig_mod.GameInputs("2026-10-20", sig_mod.TeamInputs(NBA_FACTS.team("nba", "New York Knicks")),
                                sig_mod.TeamInputs(NBA_FACTS.team("nba", "Boston Celtics")), None, False)
        self.assertEqual(decision_mod.decide(None, board, v1, history_available=False, teams_known=True).code, "no_history")
        sig = sig_mod.generate(gi, v2)
        self.assertEqual(sig.basis, "static")
        self.assertNotEqual(decision_mod.decide(sig, board, v2, history_available=False, teams_known=True).code, "no_history")

    def test_a_team_the_facts_layer_does_not_hold_is_read_by_its_name(self):
        v1, v2 = rules_mod.load("rules_v1.json"), rules_mod.load("rules_v2.json")
        st = day_store()
        ctx = base.build_context(st, "s0")
        board = base.lock_board(st, ctx)
        w1 = rt.GematriaRuntime(rules=v1, source=StubSource([], available=False), ledger=None).weigh(ctx, board)
        self.assertEqual(w1.verdict.code, "no_history")
        w2 = rt.GematriaRuntime(rules=v2, source=StubSource([], available=False), ledger=None).weigh(ctx, board)
        self.assertIsNotNone(w2.signals)
        quantities = [q for q in sig_mod.static_quantities(w2.inputs, v2) if q.owner]
        self.assertEqual({q.group for q in quantities}, {"name"}, "only the name was read: nothing about the club was invented")
        self.assertEqual({q.qid.split(".")[2] for q in quantities}, {"name"})
        self.assertEqual({q.value for q in quantities if q.owner == "home"}, {g.cipher_value(ctx.home_name, c) for c in v2.ciphers})

    def test_two_ciphers_of_one_text_never_match_each_other(self):
        v2 = rules_mod.load("rules_v2.json")
        gi = sig_mod.GameInputs("2026-10-20", sig_mod.TeamInputs(NBA_FACTS.team("nba", "New York Knicks")),
                                sig_mod.TeamInputs(NBA_FACTS.team("nba", "Boston Celtics")), None, False)
        sig = sig_mod.generate(gi, v2)
        for side in (sig.home, sig.away):
            for e in side.evidence:
                if e.kind == "static_eq_static":
                    self.assertNotEqual(e.a.qid.rsplit(".", 1)[0], e.b.qid.rsplit(".", 1)[0], (e.a.qid, e.b.qid))

    def test_the_static_scores_swap_when_the_teams_do(self):
        v2 = rules_mod.load("rules_v2.json")
        a = sig_mod.TeamInputs(NBA_FACTS.team("nba", "New York Knicks"))
        b = sig_mod.TeamInputs(NBA_FACTS.team("nba", "Boston Celtics"))
        s1 = sig_mod.generate(sig_mod.GameInputs("2026-10-20", a, b, None, False), v2)
        s2 = sig_mod.generate(sig_mod.GameInputs("2026-10-20", b, a, None, False), v2)
        self.assertEqual((s1.home.score, s1.away.score), (s2.away.score, s2.home.score))
        self.assertEqual((s1.home.comparisons, s1.away.comparisons), (s2.away.comparisons, s2.home.comparisons))


# ---------------------------------------------------------------------------------------------------
# the noise-scaled margin, the cap, one side
# ---------------------------------------------------------------------------------------------------

def ev(weight, n):
    q = sig_mod.Quantity(f"q{n}", "name", f"item {n}", 10 + n)
    return sig_mod.Evidence("own_name_eq_date", q, None, 10 + n, weight)


def signals(home_weights, away_weights, basis="static"):
    home = sig_mod.SideSignals("home", comparisons=1000, milestones=5, evidence=[ev(w, i) for i, w in enumerate(home_weights)])
    away = sig_mod.SideSignals("away", comparisons=1000, milestones=5, evidence=[ev(w, 100 + i) for i, w in enumerate(away_weights)])
    home.score, away.score = sum(home_weights), sum(away_weights)
    return sig_mod.Signals(home, away, basis=basis)


BOARD = {"markets": {"moneyline": {"sides": {"home": {"price_average": 110, "price_best": 115, "book": "b", "book_count": 5},
                                              "away": {"price_average": 105, "price_best": 108, "book": "b", "book_count": 5}}}}}


class TheNoiseScaledMargin(unittest.TestCase):
    def test_the_same_lead_passes_in_a_quiet_game_and_fails_in_a_loud_one(self):
        rules = rules_mod.load("rules_v2.json")
        quiet = signals([2.0, 1.0], [0.0])                               # a lead of 3 over three matches in all
        loud = signals([1.0] * 8, [1.0] * 5)                             # the same lead of 3 over thirteen matches
        self.assertEqual(quiet.margin, loud.margin)
        self.assertGreater(quiet.z, rules.decision.min_z)
        self.assertLess(loud.z, rules.decision.min_z)
        v_quiet = decision_mod.decide(quiet, BOARD, rules, history_available=True, teams_known=True)
        v_loud = decision_mod.decide(loud, BOARD, rules, history_available=True, teams_known=True)
        self.assertEqual((v_quiet.code, v_quiet.side), ("bet", "home"))
        self.assertEqual(v_loud.code, "small_margin")
        self.assertIn("noise", v_loud.reason)

    def test_the_floor_still_applies_under_the_noise_scale(self):
        rules = rules_mod.load("rules_v2.json")
        tiny = signals([0.5], [0.0])                                     # z is 1.0 but the lead is under the floor of 1.0
        self.assertEqual(decision_mod.decide(tiny, BOARD, rules, history_available=True, teams_known=True).code, "small_margin")

    def test_the_noise_is_the_root_of_the_squared_weights(self):
        s = signals([3.0, 1.0], [2.0])
        self.assertAlmostEqual(s.noise_sd, (9 + 1 + 4) ** 0.5, places=5)
        self.assertAlmostEqual(s.z, abs(s.margin) / s.noise_sd, places=5)
        self.assertEqual(signals([], []).z, 0.0)

    def test_v1_stays_a_fixed_margin(self):
        v1 = rules_mod.load("rules_v1.json")
        sig = signals([2.5], [0.0], basis="season")
        self.assertEqual(decision_mod.decide(sig, BOARD, v1, history_available=True, teams_known=True).code, "small_margin")   # under 3.0
        sig = signals([3.5], [0.0], basis="season")
        self.assertEqual(decision_mod.decide(sig, BOARD, v1, history_available=True, teams_known=True).code, "bet")


class TheCapAndOneSide(unittest.TestCase):
    def board(self, home, away):
        return {"markets": {"moneyline": {"sides": {"home": {"price_average": home, "price_best": home, "book": "b", "book_count": 5},
                                                    "away": {"price_average": away, "price_best": away, "book": "b", "book_count": 5}}}}}

    def test_minus_200_or_worse_is_never_taken_and_the_other_side_is_not_taken_instead(self):
        rules = rules_mod.load("rules_v2.json")
        sig = signals([4.0], [0.0])                                      # the home side leads
        for price in (-200, -250, -450):
            v = decision_mod.decide(sig, self.board(price, 300), rules, history_available=True, teams_known=True)
            self.assertEqual((v.status, v.code, v.side), ("pass", "outside_band", "home"), price)
        v = decision_mod.decide(sig, self.board(-199, 170), rules, history_available=True, teams_known=True)
        self.assertEqual((v.code, v.price), ("bet", -199))

    def test_a_verdict_names_exactly_one_side(self):
        rules = rules_mod.load("rules_v2.json")
        for home, away in (([4.0], [0.0]), ([0.0], [4.0])):
            v = decision_mod.decide(signals(home, away), BOARD, rules, history_available=True, teams_known=True)
            self.assertIn(v.side, ("home", "away"))
            self.assertEqual(v.side, "home" if home[0] > away[0] else "away")

    def test_the_priced_dog_cap_holds_on_a_whole_day(self):
        for _c, w, _r in weigh_day(rules_mod.load("rules_v2.json")):
            if w.verdict.is_bet:
                self.assertGreater(w.verdict.price, -200)


# ---------------------------------------------------------------------------------------------------
# Unleash reaches the style, and ranks the day
# ---------------------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)


class StubWeigher:
    """Returns a prepared verdict per event; records how each game was asked for (``as_of``)."""

    def __init__(self, verdicts, rules):
        self.verdicts, self.asked = verdicts, []
        self.runtime = SimpleNamespace(rules=rules)

    def weigh(self, event_id, as_of=None):
        self.asked.append((event_id, as_of))
        start = NOW + timedelta(hours=6 if event_id != "soon" else 0, minutes=30 if event_id == "soon" else 0)
        ctx = SimpleNamespace(lock=start - timedelta(minutes=60), start=start, event_id=event_id)
        return ctx, {}, SimpleNamespace(verdict=self.verdicts[event_id], block={"rules_version": "v2"})


def bet(z, side="home"):
    return decision_mod.Verdict("bet", "bet", "x", side=side, price=110, margin=3.0, z=z)


class UnleashReachesTheGematriaStyle(unittest.TestCase):
    def setUp(self):
        self.spec = {"sports": ["NBA"], "lock_minutes": 60}
        self.hound = {"id": "h-1", "created_at": "2026-10-22T10:00:00Z"}
        self.games = {eid: SimpleNamespace(sport="NBA", commence=NOW + timedelta(hours=6 if eid != "soon" else 0, minutes=30 if eid == "soon" else 0),
                                           away_team="A", home_team="H") for eid in ("a", "b", "c", "soon")}
        patcher = mock.patch.object(user_gematria, "_candidate", lambda game, ctx, board, weighed, runtime: {"row_extra": {}, "side": weighed.verdict.side})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_it(self, weigher, **kw):
        from collections import Counter
        skipped = Counter()
        out = user_gematria.hound_candidates(self.hound, self.spec, self.games, "2026-10-22", mode="live", clock=lambda: NOW, seen_ids=set(),
                                             skipped=skipped, considered={}, weigher=weigher, **kw)
        return out, skipped

    def verdicts(self):
        return {"a": bet(1.2), "b": bet(3.4), "c": bet(2.1), "soon": bet(1.1)}

    def test_without_ahead_a_game_more_than_an_hour_out_is_not_weighed(self):
        w = StubWeigher(self.verdicts(), rules_mod.load("rules_v2.json"))
        out, skipped = self.run_it(w)
        self.assertEqual([c[2] for c in out], ["soon"])
        self.assertEqual(skipped["not_locked_yet"], 3)

    def test_with_ahead_every_open_game_is_weighed_now_and_ranked_by_z(self):
        w = StubWeigher(self.verdicts(), rules_mod.load("rules_v2.json"))
        out, skipped = self.run_it(w, ahead=True)
        self.assertEqual(skipped["not_locked_yet"], 0)
        out.sort(key=lambda c: c[0])                                      # the engine's own sort
        self.assertEqual([c[2] for c in out], ["b", "c", "a", "soon"])    # strongest case first
        self.assertTrue(all(c[6]["row_extra"].get("placed_ahead") for c in out if c[2] != "soon"))
        asked = dict(w.asked)
        self.assertEqual(asked["a"], NOW)                                 # weighed on the board standing now
        self.assertIsNone(asked["soon"])                                  # inside its window: the lock board, as always

    def test_rules_v1_under_ahead_keeps_the_earliest_first_order(self):
        w = StubWeigher(self.verdicts(), rules_mod.load("rules_v1.json"))
        out, _ = self.run_it(w, ahead=True)
        out.sort(key=lambda c: c[0])
        self.assertEqual(out[0][2], "soon")                               # lock order, not z

    def test_a_started_game_is_never_weighed_ahead_or_not(self):
        self.games["old"] = SimpleNamespace(sport="NBA", commence=NOW - timedelta(minutes=5), away_team="A", home_team="H")
        w = StubWeigher({**self.verdicts(), "old": bet(9.0)}, rules_mod.load("rules_v2.json"))
        out, skipped = self.run_it(w, ahead=True)
        self.assertNotIn("old", [c[2] for c in out])
        self.assertEqual(skipped["game_started"], 1)

    def test_the_engine_hands_place_ahead_to_the_style(self):
        src = (ROOT / "src" / "hounds" / "user_engine.py").read_text(encoding="utf-8")
        self.assertRegex(src, r"(?s)user_gematria\.hound_candidates\(.*?ahead=place_ahead")


class UnleashThroughTheEngine(unittest.TestCase):
    """The whole path: ``user_engine.run(place_ahead=True)`` for a member Gematria hound, before the lock."""

    def setUp(self):
        from tests.test_gematria_member_style import EngineCase
        self.case = EngineCase("run_engine")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def early(self):
        return datetime(2026, 10, 20, 21, 30, tzinfo=UTC)              # the board was captured 21:15Z; the game starts 23:15Z, its lock is 22:15Z

    def run_engine(self, **kw):
        from tests import test_gematria_member_style as M
        with mock.patch.object(user_gematria, "make_runtime", M.runtime_factory()):
            from src.hounds import user_engine
            return user_engine.run(M.DATE, [M.member()], M.nba_rows(), ledger=self.case.ledger, now=self.early(), mode="live", **kw)

    def test_before_this_fix_nothing_was_weighed_ahead(self):
        out = self.run_engine()                                          # the ordinary pass
        self.assertEqual(out["bets_written"], 0)
        self.assertEqual(out["skipped"].get("not_locked_yet"), 1)

    def test_unleash_weighs_the_game_now_and_the_bet_says_so(self):
        out = self.run_engine(place_ahead=True)
        self.assertEqual((out["bets_written"], out["skipped"]), (1, {}))
        (row,) = self.case.bets()
        self.assertTrue(row["placed_ahead"])
        self.assertEqual(row["recorded_utc"], "2026-10-20T21:30:00Z")
        self.assertLess(row["recorded_utc"], row["lock_utc"])
        self.assertLessEqual(row["board_observed_utc"], row["recorded_utc"], "no board from after the moment it was placed")
        self.assertGreater(row["price_average"], -200)

    def test_a_second_tap_adds_nothing_and_there_is_one_side_per_game(self):
        self.run_engine(place_ahead=True)
        again = self.run_engine(place_ahead=True)
        self.assertEqual(again["bets_written"], 0)
        rows = self.case.bets()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len({(r["event_id"], r["market"]) for r in rows}), 1)


class TheDayViewNamesTheRealReason(unittest.TestCase):
    """Until 2026-10-22 every game of a Gematria hound read "rule not met"."""

    def test_each_engine_code_has_its_own_bucket(self):
        spec = {"lock_minutes": 60}
        game = SimpleNamespace(commence=NOW + timedelta(hours=3))
        cases = {"no_history": "no_history", "no_facts": "no_facts", "thin_data": "thin_data", "uneven_search": "uneven_search",
                 "no_board": "too_few_books", "small_margin": "no_numbers", "outside_band": "price_band"}
        for code, bucket in cases.items():
            verdict = SimpleNamespace(is_bet=False, code=code, price=150)
            weigher = SimpleNamespace(weigh=lambda eid, as_of=None, v=verdict: (None, {}, SimpleNamespace(verdict=v)))
            self.assertEqual(unleash_why.gematria_bucket(weigher, "e", game, spec, NOW), bucket, code)
        heavy = SimpleNamespace(is_bet=False, code="outside_band", price=-260)
        self.assertEqual(unleash_why.gematria_bucket(SimpleNamespace(weigh=lambda *a, **k: (None, {}, SimpleNamespace(verdict=heavy))),
                                                     "e", game, spec, NOW), "price_cap")
        fit = SimpleNamespace(is_bet=True, code="bet", price=120)
        self.assertEqual(unleash_why.gematria_bucket(SimpleNamespace(weigh=lambda *a, **k: (None, {}, SimpleNamespace(verdict=fit))),
                                                     "e", game, spec, NOW), "fit")
        started = SimpleNamespace(commence=NOW - timedelta(minutes=1))
        self.assertEqual(unleash_why.gematria_bucket(None, "e", started, spec, NOW), "started")
        self.assertEqual(unleash_why.gematria_bucket(SimpleNamespace(weigh=lambda *a, **k: None), "e", game, spec, NOW), "no_board")

    def test_the_summary_is_one_line_of_reasons_and_never_the_old_blanket(self):
        from src.hounds.user_spec import SPORTS  # noqa: F401
        labels = dict(unleash_why.BUCKETS)
        for code in ("no_history", "thin_data", "uneven_search", "no_numbers", "too_few_books"):
            self.assertIn(code, labels)
        self.assertEqual(labels["no_numbers"], "numbers didn't line up")
        self.assertEqual(labels["too_few_books"], "too few books")


# ---------------------------------------------------------------------------------------------------
# the analysis payload
# ---------------------------------------------------------------------------------------------------

BIG_DAY = MATCHES + [("Roma", "Lazio"), ("Ajax", "PSV Eindhoven"), ("Celtic", "Rangers"), ("Benfica", "Porto"), ("Marseille", "Lyon")]


def analysis_payload(matches=BIG_DAY, limit=ga.MAX_GAMES):
    """A REAL analysis payload (the engine weighs a fixture day; ``gematria_analysis.build`` formats it): what the page is handed."""
    rules = rules_mod.load("rules_v2.json")
    weighed = weigh_day(rules, matches=matches)
    by_event = {c.event_id: (c, {}, w) for c, w, _r in weighed}

    class Stub:
        def __init__(self, games, runtime=None):
            self.games = games

        def weigh(self, event_id, as_of=None):
            return by_event[event_id]

    dog = common.Dog(id="gematria", kind=common.KIND_OTHER, name="Gematria Hound", status="running", root_id="gematria", forward_only=True)
    now = min(c.lock for c, _w, _r in weighed) - timedelta(hours=2)
    games = {c.event_id: SimpleNamespace(sport="SOCCER", commence=c.start) for c, _w, _r in weighed}
    with mock.patch.object(user_gematria, "Weigher", Stub):
        return ga.build(dog, now=now, games=games, runtime=SimpleNamespace(rules=rules), use_cache=False, limit=limit)


class TheAnalysisIsTheComputedEvidence(unittest.TestCase):
    def setUp(self):
        self.rules = rules_mod.load("rules_v2.json")
        self.weighed = weigh_day(self.rules, matches=BIG_DAY)
        self.dog = common.Dog(id="gematria", kind=common.KIND_OTHER, name="Gematria Hound", status="running", root_id="gematria", forward_only=True)
        by_event = {c.event_id: (c, {}, w) for c, w, _r in self.weighed}

        class Stub:
            def __init__(self, games, runtime=None):
                self.games = games

            def weigh(self, event_id, as_of=None):
                return by_event[event_id]

        patcher = mock.patch.object(user_gematria, "Weigher", Stub)
        patcher.start()
        self.addCleanup(patcher.stop)
        now = min(c.lock for c, _w, _r in self.weighed) - timedelta(hours=2)
        self.now = now
        self.games = {c.event_id: SimpleNamespace(sport="SOCCER", commence=c.start) for c, _w, _r in self.weighed}
        self.runtime = SimpleNamespace(rules=self.rules)

    def build(self, **kw):
        return ga.build(self.dog, now=self.now, games=self.games, runtime=self.runtime, use_cache=False, **kw)

    def test_the_gate_is_the_gematria_hounds_only(self):
        self.assertTrue(ga.is_gematria_dog(self.dog))
        other = common.Dog(id="ai_claude", kind=common.KIND_OTHER, name="x")
        self.assertFalse(ga.is_gematria_dog(other))
        self.assertFalse(ga.is_gematria_dog(None))
        with self.assertRaises(ga.NotGematria):
            ga.build(other, now=self.now, games={}, runtime=self.runtime)

    def test_the_payload_is_capped_with_picks_first_and_counts_what_was_left_out(self):
        out = self.build()
        self.assertEqual(out["weighed"], len(BIG_DAY))
        self.assertEqual(out["shown"], ga.MAX_GAMES)
        self.assertEqual(len(out["games"]), ga.MAX_GAMES)
        self.assertTrue(out["capped"])
        statuses = [e["status"] for e in out["games"]]
        self.assertEqual(statuses, sorted(statuses, key=lambda s: s != "bet"), "every pick comes before every pass")
        # the house hound is placed by the lock-time runner, earliest first, at most its rules' limit a day (2026-10-22 hardening:
        # the payload once ranked by z and called every candidate "Pick", more than the hound could place)
        starts = [e["start_utc"] for e in out["games"] if e["status"] == "bet"]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(out["ranked_by"], "start")
        self.assertEqual(out["candidates_total"], sum(1 for _c, w, _r in self.weighed if w.verdict.is_bet))
        self.assertEqual(out["picks_total"], min(out["candidates_total"], self.rules.decision.max_picks_per_day))
        self.assertLess(len(json.dumps(out)), 80_000, "the payload stays small")
        small = self.build(limit=3)
        self.assertEqual(small["shown"], 3)

    def test_every_line_is_formatted_from_a_value_the_engine_computed(self):
        out = self.build()
        by_event = {c.event_id: (c, w) for c, w, _r in self.weighed}
        for entry in out["games"]:
            ctx, w = by_event[entry["event_id"]]
            sig = w.signals
            lines = entry["lines"]
            ciphers = [l for l in lines if l["kind"] == "cipher"]
            self.assertTrue(ciphers)
            for l in ciphers:
                side_team = w.inputs.team(l["side"]).team
                text = dict(side_team.name_texts())[l["field"]]
                self.assertEqual(l["values"], {c: g.cipher_value(text, c) for c in self.rules.ciphers})
                self.assertEqual(l["text"], f"{text}: " + " · ".join(f"{c} {l['values'][c]}" for c in self.rules.ciphers))
            for side in ("home", "away"):
                shown = [l for l in lines if l["kind"] == "match" and l["side"] == side and not l.get("none")]
                self.assertEqual(len(shown), min(ga.MAX_MATCHES, len(sig.side(side).evidence)))
                for l, e in zip(shown, sig.side(side).evidence):
                    self.assertEqual((l["value"], l["weight"], l["evidence_kind"]), (e.value, round(e.weight, 3), e.kind))
                    self.assertIn(e.a.label, l["text"])
                    if e.b is not None:
                        self.assertIn(e.b.label, l["text"])
                if not sig.side(side).evidence:
                    self.assertTrue(any(l.get("none") and l["side"] == side for l in lines))
            score = next(l for l in lines if l["kind"] == "score")
            self.assertEqual(score["scores"], {"home": sig.home.score, "away": sig.away.score})
            self.assertEqual((score["margin"], score["z"]), (sig.margin, sig.z))
            decision = lines[-1]
            self.assertEqual(decision["kind"], "decision")
            self.assertEqual(decision["status"], "bet" if w.verdict.is_bet else "pass")
            if w.verdict.is_bet:
                self.assertIn(f"{w.verdict.price:+d}", decision["text"])
            else:
                self.assertIn(w.verdict.reason, decision["text"])

    def test_the_date_line_is_the_dates_real_numbers(self):
        out = self.build()
        nums = g.date_numbers(out["date_numbers"]["date"])
        for key, value in out["date_numbers"]["values"].items():
            self.assertEqual(value, nums[key])

    def test_a_repeat_is_identical_and_nothing_is_written(self):
        self.assertEqual(self.build(), self.build())

    def test_the_copy_makes_no_claim(self):
        out = self.build()
        self.assertIn("Experimental", out["copy"])
        blob = json.dumps(out).lower()
        for banned in ("proven", "guarantee", "bet check", " edge"):
            self.assertNotIn(banned, blob)


class TheRoute(unittest.TestCase):
    """The route is in api/hounds_interact.py; only checked when FastAPI is importable (the Linux CI image has none)."""

    def test_the_route_is_registered_and_refuses_a_hound_that_is_not_gematria(self):
        try:
            from fastapi.testclient import TestClient
            from api.app import app
        except Exception:  # noqa: BLE001
            self.skipTest("FastAPI is not importable here")
        client = TestClient(app)
        resp = client.get("/hounds/chalk_chihuahua/analysis")
        self.assertIn(resp.status_code, (404, 422))
        if resp.status_code == 422:
            self.assertEqual(resp.json()["detail"]["error"], "not_gematria")
        self.assertEqual(client.get("/hounds/definitely_not_a_hound/analysis").status_code, 404)

    def test_the_source_names_the_route_and_keeps_it_read_only(self):
        src = (ROOT / "api" / "hounds_interact.py").read_text(encoding="utf-8")
        self.assertRegex(src, r'@router\.get\("/hounds/\{hound_id\}/analysis"\)')
        block = src[src.index('"/hounds/{hound_id}/analysis"'):]
        block = block[:block.index("@router.post")]
        for word in ("ledger", "unleash.unleash", "manual."):
            self.assertNotIn(word, block)
        builder = (ROOT / "src" / "hounds" / "interact" / "gematria_analysis.py").read_text(encoding="utf-8")
        for word in ("ledger.append", "open(", "write_text", "HashChainLedger"):
            self.assertNotIn(word, builder)

    def test_the_kit_tells_the_page_which_hounds_to_stream(self):
        from src.hounds.interact import camp
        self.assertTrue(camp._is_gematria(common.Dog(id="gematria", kind=common.KIND_OTHER, name="G")))
        self.assertFalse(camp._is_gematria(common.Dog(id="ai_claude", kind=common.KIND_OTHER, name="C")))


if __name__ == "__main__":
    unittest.main()
