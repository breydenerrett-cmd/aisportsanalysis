"""The member "Gematria" base style: a member's hound that picks by the SAME engine and the SAME active rules as the house
Gematria Hound (src/hounds/user_gematria.py).

Pinned here, each one failing on the code before the style existed:

  the spec         validation of the style, the stamp, the fixed rule, every refusal, the published rule text
  the engine       a lock-time bet from a fixture board, the house runner's inputs reused (a parity check), a PASS on thin data,
                   on a sport with no store and on a team with no facts, nothing before the lock or after the start, no replay
  the kill switch  GEMATRIA_HOUND=off stops a member's Gematria hound exactly as it stops the house hound
  the price        never -200 or worse, from the spec down to the engine
  the evidence     the same Evidence payload the house hound's page reads, from the members' ledger, and the route that serves it
  the quiz         the "Gematria" personality exists, has its own art, and composes a working Gematria spec
  the words        "gematria" / "numerology" read as the style, "lucky numbers" still reads as the old condition
  the page         the builder's hooks live in the static page AND the studio skeleton, with the link to the house hound

No network and no real store: the runtime is the house runtime on synthetic facts and results (tests/test_gematria_hound.py's).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.hounds import user_defs, user_engine, user_engine_v2, user_gematria, user_spec
from src.hounds.english import parser, render
from src.hounds.gematria import decision as decision_mod
from src.hounds.gematria import rules as rules_mod, runtime as rt
from src.hounds.pack import base
from src.hounds.quiz import compose as quiz_compose, library as quiz_library
from tests._hounds_user_fixtures import hound as plain_hound
from tests.test_ai_hounds import NOW_AS, allsports_rows, allsports_stores, nba_rows, tennis_rows
from tests.test_gematria_hound import LENIENT, NBA_FACTS, StubSource, make_rules, season_games

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DATE = "2026-10-20"
UTC = timezone.utc
CLAIMS = (r"\bedge\b", r"\bproven\b", r"\bprofit", r"guarantee", r"sure thing", r"can'?t lose", r"beat the (book|market)",
          r"bet check", r"betcheck")


def gem_spec(**over) -> dict:
    raw = {"version": 2, "style": "gematria", "name": "Numbers Pup", "sports": ["NBA"], "max_bets_per_day": 2, "stake_units": 1.0}
    raw.update(over)
    return user_spec.validate_spec(raw)


def member(hid="u-gem1", created="2026-10-01T00:00:00Z", **over) -> dict:
    spec = gem_spec(**over)
    return {"id": hid, "spec": spec, "spec_hash": user_spec.spec_hash(spec), "created_at": created}


def runtime_factory(rules=None, source=None, facts=None):
    def make():
        return rt.GematriaRuntime(rules=rules or make_rules(**LENIENT), facts=facts or NBA_FACTS,
                                  source=source or StubSource(season_games()), ledger=None, now_fn=lambda: NOW_AS)
    return make


class SpecTests(unittest.TestCase):
    def test_the_style_validates_with_the_members_own_choices_and_the_fixed_rule(self):
        spec = gem_spec(sports=["NBA", "NHL"], max_bets_per_day=3, stake_units=2.0)
        self.assertEqual((spec["style"], spec["sports"], spec["max_bets_per_day"], spec["stake_units"]),
                         ("gematria", ["NBA", "NHL"], 3, 2.0))
        rule = spec["rules"][0]
        self.assertEqual((len(spec["rules"]), rule["markets"], rule["side"], rule["when"], rule["sports"]),
                         (1, ["moneyline"], "either", None, ["NBA", "NHL"]))
        self.assertEqual((spec["markets"], spec["lock_minutes"], spec["rank_by"]), (["moneyline"], 60, "earliest_lock"))

    def test_the_spec_is_stamped_with_the_active_rules_the_house_hound_runs_under(self):
        house = rules_mod.load()
        self.assertEqual(gem_spec()["gematria"], {"rules_version": house.version, "rules_hash": house.rules_hash})
        self.assertEqual(user_gematria.active_stamp(), gem_spec()["gematria"])

    def test_the_price_band_is_the_rules_band_and_never_reaches_minus_200(self):
        rule = gem_spec()["rules"][0]
        self.assertEqual((rule["price_min"], rule["price_max"]), tuple(rules_mod.load().decision.price_band))
        self.assertGreater(rule["price_min"], user_spec.MAX_FAVOURITE_PRICE)
        self.assertFalse(user_spec.beyond_cap(rule["price_min"]))

    def test_a_stored_spec_validates_again_unchanged_and_hashes_the_style_in(self):
        spec = gem_spec(sports=["NBA", "NHL"])
        self.assertEqual(user_spec.validate_spec(dict(spec)), spec)
        plain = user_spec.validate_spec({"version": 2, "name": "Plain Pup", "sports": ["NBA", "NHL"],
                                         "rules": [{**spec["rules"][0], "label": "Gematria"}]})
        self.assertNotIn("style", plain)
        self.assertNotEqual(user_spec.spec_hash(plain), user_spec.spec_hash(spec))      # same rule fields, different style

    def test_the_stamp_is_part_of_the_hash_and_a_made_up_stamp_is_refused(self):
        spec = gem_spec()
        forged = {**spec, "gematria": {"rules_version": "v1", "rules_hash": "0" * 64}}
        with self.assertRaises(user_spec.SpecError) as ctx:
            user_spec.validate_spec(forged)
        self.assertIn("gematria", ctx.exception.errors)
        other = dict(spec["gematria"], rules_version="v9")
        self.assertNotEqual(user_spec.rule_fields({**spec, "gematria": other}), user_spec.rule_fields(spec))

    def test_what_the_style_does_not_take_is_refused_with_a_reason(self):
        cases = {
            "lock_minutes": {"lock_minutes": 120},
            "markets": {"markets": ["total"]},
            "rank_by": {"rank_by": "longest_price"},
            "rules": {"rules": [{"sports": ["NBA"], "markets": ["moneyline"], "when": {"op": "all", "items": [{"id": "coin_flip", "pct": 50}]}}]},
            "style": {"style": "wizard"},
            "sports": {"sports": []},
        }
        for field, extra in cases.items():
            with self.subTest(field=field), self.assertRaises(user_spec.SpecError) as ctx:
                gem_spec(**extra)
            self.assertIn(field, ctx.exception.errors)

    def test_a_rules_hound_cannot_carry_a_gematria_stamp(self):
        with self.assertRaises(user_spec.SpecError) as ctx:
            user_spec.validate_spec({"version": 2, "name": "Plain Pup", "gematria": gem_spec()["gematria"],
                                     "rules": [{"sports": ["MLB"], "markets": ["moneyline"]}]})
        self.assertIn("gematria", ctx.exception.errors)

    def test_the_published_rule_says_what_runs_and_claims_nothing(self):
        spec = gem_spec(sports=["NBA", "NHL"])
        text = render.rule_text(spec)
        self.assertIn("house Gematria Hound", text)
        self.assertIn("never -200 or worse", text)
        self.assertIn("passes", text)
        self.assertIn("NBA and NHL moneylines", text)
        for pattern in CLAIMS:
            self.assertIsNone(re.search(pattern, text.lower()), pattern)
        self.assertEqual(user_spec.rule_text(spec), text)
        self.assertNotIn("it backs either side", text)       # the generic moneyline sentence is not what this hound does

    def test_the_builder_menu_lists_the_style_with_its_paragraph_and_the_house_hounds_link(self):
        styles = {s["value"]: s for s in user_spec.builder_menu()["styles"]}
        self.assertEqual(list(styles), ["rules", "gematria"])
        gem = styles["gematria"]
        self.assertEqual(gem["house_hound"]["href"], "hound.html?id=gematria")
        self.assertEqual(gem["fixed"]["lock_minutes"], 60)
        self.assertEqual(gem["fixed"]["markets"], ["moneyline"])
        self.assertGreater(len(gem["summary"].split()), 40)
        for pattern in CLAIMS:
            self.assertIsNone(re.search(pattern, gem["summary"].lower()), pattern)

    def test_a_diff_between_versions_names_the_style_and_the_rule(self):
        old, new = gem_spec(), gem_spec(sports=["NBA", "NHL"])
        whats = [c["what"] for c in render.diff_specs(old, new)]
        self.assertIn("Rules", whats)
        plain = user_spec.validate_spec({"version": 2, "name": "Numbers Pup", "sports": ["NBA"],
                                         "rules": [{"sports": ["NBA"], "markets": ["moneyline"]}]})
        self.assertIn("Style", [c["what"] for c in render.diff_specs(plain, old)])


class EngineCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = str(Path(self._tmp.name) / "members.jsonl")
        for target in ("urllib.request.urlopen", "socket.create_connection"):
            p = mock.patch(target, side_effect=AssertionError("a test reached for the network"))
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GEMATRIA_HOUND", None)

    def run_engine(self, hounds, rows=None, now=NOW_AS, factory=None, mode="live"):
        with mock.patch.object(user_gematria, "make_runtime", factory or runtime_factory()):
            return user_engine.run(DATE, hounds, rows if rows is not None else nba_rows(), ledger=self.ledger, now=now, mode=mode)

    def bets(self):
        return [json.loads(line) for line in Path(self.ledger).read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("kind") == user_engine.KIND_BET] if Path(self.ledger).exists() else []


class LockTimeBetTests(EngineCase):
    def test_a_member_gematria_hound_places_a_lock_time_bet_from_a_fixture_board(self):
        out = self.run_engine([member()])
        self.assertEqual((out["bets_written"], out["skipped"]), (1, {}))
        (row,) = self.bets()
        self.assertEqual((row["hound_id"], row["market"], row["side"], row["sport"]), ("u-gem1", "moneyline", "away", "NBA"))
        self.assertEqual(row["selection"], "Boston Celtics to win")
        self.assertEqual(row["lock_utc"], "2026-10-20T22:15:00Z")
        self.assertLess(row["recorded_utc"], row["start_utc"])
        self.assertEqual(row["price_average"], 100)
        self.assertTrue(row["paper_only"] and row["forward_only"])
        self.assertEqual(row["who_decided"], "rule")
        self.assertTrue(row["reason"].startswith("Gematria: the away side leads the count"))

    def test_the_bet_row_carries_the_rules_stamp_and_the_evidence_block(self):
        self.run_engine([member()])
        (row,) = self.bets()
        rules = make_rules(**LENIENT)
        self.assertEqual((row["rules_version"], row["rules_hash"]), (rules.version, rules.rules_hash))
        block = row["gematria"]
        self.assertEqual((block["rules_version"], block["rules_hash"]), (rules.version, rules.rules_hash))
        self.assertEqual(set(block["evidence"]), {"home", "away"})
        self.assertTrue(block["evidence"]["away"] and block["scores"]["away"] > block["scores"]["home"])
        self.assertGreaterEqual(block["margin"] * -1 if block["margin"] < 0 else block["margin"], block["threshold"])
        self.assertIn("confidence", row)

    def test_it_uses_the_house_runners_inputs_so_the_two_cannot_drift(self):
        """The same game through ``pack.base.build_context`` / ``lock_board`` on the house's Stores, weighed by the same runtime,
        gives the verdict the member's pass wrote."""
        runtime = runtime_factory()()
        house_stores = allsports_stores(nba_rows())
        ctx = base.build_context(house_stores, "nba1")
        house = runtime.weigh(ctx, base.lock_board(house_stores, ctx))
        self.run_engine([member()])
        (row,) = self.bets()
        self.assertTrue(house.verdict.is_bet)
        self.assertEqual((row["side"], row["price_average"]), (house.verdict.side, house.verdict.price))
        self.assertEqual(row["gematria"]["scores"], house.block["scores"])
        self.assertEqual(row["gematria"]["inputs_hash"], house.block["inputs_hash"])
        self.assertEqual(row["lock_utc"], base.iso(ctx.lock))

    def test_the_member_runs_the_active_rules_when_nothing_is_injected(self):
        self.assertEqual(user_gematria.make_runtime().rules.rules_hash, rules_mod.load().rules_hash)

    def test_a_second_pass_adds_nothing(self):
        self.run_engine([member()])
        again = self.run_engine([member()])
        self.assertEqual(again["bets_written"], 0)
        self.assertEqual(len(self.bets()), 1)

    def test_the_members_bets_a_day_cap_holds(self):
        rows = nba_rows("nba1") + allsports_rows("nba2", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=-120,
                                                 away_ml=100, spread=(-1.5, -110, -110), total=(221.5, -110, -110))
        out = self.run_engine([member(max_bets_per_day=1)], rows=rows)
        self.assertEqual(out["bets_written"], 1)
        self.assertEqual(out["skipped"].get("daily_limit"), 1)

    def test_the_stake_is_the_members(self):
        self.run_engine([member(stake_units=2.0)])
        (row,) = self.bets()
        self.assertEqual((row["stake_units"], row["units"]), (2.0, 2.0))

    def test_an_ordinary_hound_beside_it_is_untouched(self):
        plain = plain_hound("u-plain", sports=["NBA"], lock_minutes=120, side_rule="home", price_min=-199, price_max=400)
        out = self.run_engine([member(), plain], now=NOW_AS - timedelta(minutes=45))
        self.assertEqual(out["by_hound"], {"u-plain": 1})                    # 22:30 - 45 min: the gematria lock (22:15) is not here yet
        self.assertEqual(out["skipped"].get("not_locked_yet"), 1)


class TimingTests(EngineCase):
    def test_nothing_before_the_lock(self):
        out = self.run_engine([member()], now=NOW_AS - timedelta(hours=2))
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"not_locked_yet": 1}))

    def test_nothing_at_or_after_the_start(self):
        out = self.run_engine([member()], now=datetime(2026, 10, 20, 23, 15, tzinfo=UTC))
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"game_started": 1}))

    def test_a_hound_made_after_the_lock_does_not_bet_that_game(self):
        out = self.run_engine([member(created="2026-10-20T22:20:00Z")])
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"hound_created_after_lock": 1}))

    def test_a_replay_is_refused_like_the_house_hounds(self):
        out = self.run_engine([member()], mode="replay")
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {user_gematria.FORWARD_ONLY_CODE: 1}))

    def test_a_game_in_a_sport_the_member_did_not_pick_is_not_considered(self):
        out = self.run_engine([member(sports=["NHL"])])
        self.assertEqual((out["bets_written"], out["considered"]), (0, {}))


class PassTests(EngineCase):
    def test_thin_data_passes_with_the_engines_reason(self):
        thin = make_rules(**dict(LENIENT, min_milestones_per_side=999))
        out = self.run_engine([member()], factory=runtime_factory(rules=thin))
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"gematria_thin_data": 1}))

    def test_a_sport_with_no_stored_results_passes(self):
        unavailable = StubSource(season_games(), available=False)
        out = self.run_engine([member()], factory=runtime_factory(source=unavailable))
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"gematria_no_history": 1}))

    def test_tennis_has_no_results_store_so_the_real_source_passes_it(self):
        real = lambda: rt.GematriaRuntime(rules=make_rules(**LENIENT), facts=NBA_FACTS, ledger=None, now_fn=lambda: NOW_AS)
        out = self.run_engine([member(sports=["TENNIS"])], rows=tennis_rows(), factory=real)
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"gematria_no_history": 1}))

    def test_a_team_the_facts_layer_does_not_know_passes(self):
        rows = allsports_rows("nba9", "nba", "Seattle Supersonics", "Vancouver Grizzlies", title="NBA", home_ml=-120, away_ml=100,
                              spread=(-1.5, -110, -110), total=(221.5, -110, -110))
        out = self.run_engine([member()], rows=rows)
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"gematria_no_facts": 1}))

    def test_a_small_margin_passes(self):
        wide = make_rules(**dict(LENIENT, min_margin=500.0))
        out = self.run_engine([member()], factory=runtime_factory(rules=wide))
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"gematria_small_margin": 1}))


class NoMinus200Tests(EngineCase):
    def favourite_rows(self):
        return allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=210, away_ml=-250,
                              spread=(-1.5, -110, -110), total=(221.5, -110, -110))

    def test_a_pick_at_minus_250_is_never_made(self):
        out = self.run_engine([member()], rows=self.favourite_rows())
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"gematria_outside_band": 1}))
        self.assertEqual(self.bets(), [])

    def test_the_engine_re_checks_the_cap_even_if_the_decision_let_one_through(self):
        def leaky(sig, board, rules, *, history_available, teams_known):
            v = decision_mod.Verdict("bet", "bet", "forced", side="away", price=-250, margin=-9.0,
                                     scores={"home": 1.0, "away": 10.0})
            v.confidence = 3
            return v
        with mock.patch.object(decision_mod, "decide", leaky):
            out = self.run_engine([member()], rows=self.favourite_rows())
        self.assertEqual(out["bets_written"], 0)
        self.assertEqual(out["skipped"].get("price_cap"), 1)

    def test_no_price_band_the_style_can_carry_reaches_it(self):
        self.assertFalse(any(user_spec.beyond_cap(p) for p in (gem_spec()["rules"][0]["price_min"],)))
        with self.assertRaises(rules_mod.RulesError):
            make_rules(price_band=[-200, 400])


class KillSwitchTests(EngineCase):
    def test_off_stops_the_members_hound(self):
        for value in ("off", "0", "false", "no"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"GEMATRIA_HOUND": value}):
                out = self.run_engine([member()])
                self.assertEqual((out["bets_written"], out["skipped"]), (0, {user_gematria.OFF_CODE: 1}))
        self.assertEqual(self.bets(), [])

    def test_it_is_the_same_switch_the_house_hound_reads(self):
        from src.hounds import ai_runner
        for value, expected in (("off", False), ("", True), ("on", True)):
            env = {"GEMATRIA_HOUND": value}
            self.assertEqual(user_gematria.enabled(env), expected)
            self.assertEqual(ai_runner.gematria_on(env), expected)

    def test_on_by_default_and_back_on_after_off(self):
        self.assertEqual(self.run_engine([member()])["bets_written"], 1)

    def test_the_builders_preview_is_dark_while_it_is_off(self):
        games = user_engine.build_games(nba_rows(), near_date=DATE)
        with mock.patch.dict(os.environ, {"GEMATRIA_HOUND": "off"}), mock.patch.object(user_gematria, "make_runtime", runtime_factory()):
            out = user_gematria.preview(gem_spec(), games, DATE, NOW_AS)
        self.assertEqual((out["qualifying"], out["skipped"]), (0, {user_gematria.OFF_CODE: 1}))


class GenericPathsLeaveItAloneTests(EngineCase):
    """Ask, Unleash and the generic engine evaluate a hound's rules; this style's fixed rule must never be read as one."""

    def test_the_generic_engine_returns_nothing_for_the_style(self):
        games = user_engine.build_games(nba_rows(), near_date=DATE)
        spec = gem_spec()
        got = user_engine_v2.hound_candidates({"id": "u-gem1", "spec": spec, "created_at": None}, spec, games, None, DATE,
                                              mode="live", clock=lambda: NOW_AS, seen_ids=set(), game_pk_index=None,
                                              skipped=user_engine.Counter(), considered={})
        self.assertEqual(got, [])
        game = next(iter(games.values()))
        self.assertEqual(user_engine_v2.rule_candidates(spec["rules"][0], 0, spec, game, "moneyline", NOW_AS, NOW_AS, NOW_AS, DATE,
                                                        "seed", None, None, user_engine.Counter()), [])

    def test_a_drill_of_the_style_is_refused_as_forward_only(self):
        from src.hounds.interact import drill
        with self.assertRaises(drill.DrillError) as ctx:
            drill.drill(spec=gem_spec())
        self.assertEqual(ctx.exception.code, "gematria_forward_only")


class PreviewTests(EngineCase):
    def test_the_preview_weighs_todays_board_and_writes_nothing(self):
        games = user_engine.build_games(nba_rows(), near_date=DATE)
        with mock.patch.object(user_gematria, "make_runtime", runtime_factory()):
            out = user_gematria.preview(gem_spec(), games, DATE, NOW_AS)
        self.assertEqual((out["qualifying"], out["would_bet"], out["games_considered"]), (1, 1, 1))
        pick = out["picks"][0]
        self.assertEqual((pick["selection"], pick["side"], pick["market"], pick["locked"]), ("Boston Celtics to win", "away", "moneyline", True))
        self.assertFalse(Path(self.ledger).exists())


class EvidenceTests(EngineCase):
    def test_the_evidence_payload_has_the_shape_the_house_page_reads(self):
        self.run_engine([member()])
        payload = user_gematria.picks_for("u-gem1", ledger=self.ledger)
        self.assertTrue(payload["started"])
        self.assertEqual(payload["hound_id"], "u-gem1")
        (pick,) = payload["picks"]
        for key in ("event_id", "date", "sport", "start_utc", "away", "home", "selection", "side", "price", "result", "rules_version",
                    "scores", "margin", "threshold", "comparisons", "search_space", "matches", "history", "evidence"):
            self.assertIn(key, pick)
        self.assertEqual((pick["away"], pick["home"], pick["side"], pick["result"]), ("Boston Celtics", "New York Knicks", "away", None))
        self.assertTrue(pick["evidence"]["away"])
        self.assertTrue(payload["paper_only"])

    def test_before_the_first_pick_it_answers_empty_not_missing(self):
        payload = user_gematria.picks_for("u-gem1", ledger=self.ledger)
        self.assertEqual((payload["started"], payload["picks"]), (False, []))

    def test_another_hounds_bets_never_appear(self):
        self.run_engine([member(), member(hid="u-gem2", name="Other Pup")])
        self.assertEqual(len(user_gematria.picks_for("u-gem1", ledger=self.ledger)["picks"]), 1)
        self.assertEqual(len(user_gematria.picks_for("u-gem2", ledger=self.ledger)["picks"]), 1)
        self.assertEqual(user_gematria.picks_for("u-nobody", ledger=self.ledger)["picks"], [])

    def test_the_graded_result_joins_the_pick(self):
        from src.hounds import user_settle
        self.run_engine([member()])
        (row,) = self.bets()
        graded = {"kind": user_settle.KIND_GRADED, "bet_id": row["bet_id"], "hound_id": "u-gem1", "result": "WIN"}
        with open(self.ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(graded) + "\n")
        (pick,) = user_gematria.picks_for("u-gem1", ledger=self.ledger)["picks"]
        self.assertEqual(pick["result"], "WIN")

    def test_the_hounds_stats_definition_is_a_numerology_hound_so_its_page_shows_the_fold(self):
        d = user_defs.definition({"id": "u-gem1", "name": "Numbers Pup", "tagline": "", "owner_user_id": 1, "status": "running",
                                  "spec": gem_spec(), "created_at": "2026-10-01T00:00:00Z"})
        self.assertEqual((d["category"], d["kind"]), ("numerology", "user"))
        self.assertIn("coincidences", d["style"])
        self.assertIn("house Gematria Hound", d["rule_text"])
        other = user_defs.definition({"id": "u-p", "name": "Plain Pup", "tagline": "", "owner_user_id": 1, "status": "running",
                                      "spec": user_spec.validate_spec({"name": "Plain Pup", "sports": ["MLB"], "markets": ["moneyline"],
                                                                       "side_rule": "home", "price_min": -150, "price_max": 150,
                                                                       "min_books": 3, "max_bets_per_day": 2, "lock_minutes": 120}),
                                      "created_at": "2026-10-01T00:00:00Z"})
        self.assertEqual(other["category"], "mixed")


try:
    from fastapi import HTTPException, Response
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class EvidenceRouteTests(EngineCase):
    def setUp(self):
        super().setUp()
        from src.appstate import users as users_store
        self.db = Path(self._tmp.name) / "app.db"
        patches = [mock.patch.object(users_store, "db_path", lambda: self.db),
                   mock.patch.object(user_engine, "ledger_path", lambda p=None: p or self.ledger)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.owner = users_store.create_user("owner@example.com", status="active", db=self.db)

    def test_the_route_serves_a_members_gematria_hound_and_nothing_else(self):
        from api import hounds as api
        from src.hounds import user_store
        gem = user_store.create_hound(self.owner.id, gem_spec(name="Numbers Pup"))
        plain = user_store.create_hound(self.owner.id, {"name": "Plain Pup", "sports": ["MLB"], "markets": ["moneyline"],
                                                        "side_rule": "home", "price_min": -150, "price_max": 150, "min_books": 3,
                                                        "max_bets_per_day": 2, "lock_minutes": 120})
        self.assertEqual(gem["spec"]["style"], "gematria")
        got = api.gematria_picks(gem["id"], Response())
        self.assertEqual((got["hound_id"], got["started"], got["picks"]), (gem["id"], False, []))
        for hound_id in (plain["id"], "u-missing"):
            with self.assertRaises(HTTPException) as ctx:
                api.gematria_picks(hound_id, Response())
            self.assertEqual(ctx.exception.status_code, 404)

    def test_the_house_hound_is_still_served_by_the_house_view(self):
        from api import hounds as api
        got = api.gematria_picks("gematria", Response())
        self.assertEqual(got["hound_id"], "gematria")

    def test_a_kept_hound_runs_end_to_end_create_to_bet_to_evidence(self):
        from api import hounds as api
        from src.hounds import user_store
        gem = user_store.create_hound(self.owner.id, gem_spec(name="Numbers Pup"), now=datetime(2026, 10, 1, tzinfo=UTC))
        running = user_store.list_running()
        self.assertEqual([h["id"] for h in running], [gem["id"]])
        with mock.patch.object(user_gematria, "make_runtime", runtime_factory()):
            out = user_engine.run(DATE, running, nba_rows(), ledger=self.ledger, now=NOW_AS, mode="live")
        self.assertEqual(out["bets_written"], 1)
        (pick,) = api.gematria_picks(gem["id"], Response())["picks"]
        self.assertEqual(pick["selection"], "Boston Celtics to win")


class QuizTests(unittest.TestCase):
    def personality(self):
        return next(p for p in quiz_library.load()["personalities"] if p["id"] == "gematria")

    def test_the_gematria_card_is_in_the_library_and_the_library_still_validates(self):
        p = self.personality()
        self.assertEqual((p["name"], p["style"]), ("Gematria", "gematria"))
        self.assertEqual(p["pitch"], "Reads the numbers in names, dates and streaks. Bets when they line up.")
        self.assertEqual(quiz_library.validate_library(), [])
        shown = quiz_library.public_library()["personalities"]
        self.assertEqual([x["id"] for x in shown][-1], "gematria")
        self.assertNotIn("recipes", shown[-1])
        for pattern in CLAIMS + (r"\block\b",):
            self.assertIsNone(re.search(pattern, json.dumps(p).lower()), pattern)

    def test_the_card_has_its_own_hound_art(self):
        rows = quiz_library.load()["personalities"]
        mine = next(p for p in rows if p["id"] == "gematria")
        others = [p for p in rows if p["id"] != "gematria"]
        for key in ("breed", "coat", "bg", "color", "badge"):
            self.assertNotIn(mine[key], {p[key] for p in others}, key)
        self.assertEqual(mine["art"], {"breed": "bloodhound", "style": "elite", "body": "jersey", "number": 33})
        look = quiz_compose.compose({"personality": "gematria"})["look"]
        self.assertEqual((look["breed"], look["style"], look["body"], look["number"], look["coat"], look["bg"]),
                         ("bloodhound", "elite", "jersey", 33, "tan", "teal"))

    def test_a_chosen_hoodie_takes_the_jersey_number_off_so_the_look_stays_valid(self):
        from src.hounds.interact import look as look_mod
        look = quiz_compose.compose({"personality": "gematria", "look": {"accessory": "hoodie"}})["look"]
        self.assertIsNone(look.get("number"))
        look_mod.validate_look(look)
        look_mod.validate_look(quiz_compose.compose({"personality": "gematria"})["look"])

    def test_picking_it_composes_a_working_gematria_spec_with_the_members_choices(self):
        out = quiz_compose.compose({"personality": "gematria", "sports": ["NBA", "NHL"], "bets_per_day": 3, "stake": 2.0,
                                    "name": "Digit Dog"})
        spec = out["spec"]
        self.assertEqual((spec["style"], spec["name"], spec["sports"], spec["max_bets_per_day"], spec["stake_units"],
                          spec["lock_minutes"]), ("gematria", "Digit Dog", ["NBA", "NHL"], 3, 2.0, 60))
        self.assertEqual(user_spec.validate_spec(spec), spec)                  # exactly what Keep posts is valid
        self.assertEqual((out["personality"], out["breed"], out["rule_count"]), ("gematria", "bloodhound", 1))
        self.assertIn("house Gematria Hound", out["rule_cards"][0]["sentence"])
        self.assertEqual(out["rule_cards"][0]["conditions"], 0)

    def test_the_answers_that_would_change_its_rule_are_left_out_and_named(self):
        out = quiz_compose.compose({"personality": "gematria", "markets": ["moneyline", "total"], "timing": "early",
                                    "price_comfort": "plus", "archetypes": ["revenge_tour"], "quirks": ["full_moon"]})
        codes = [w["code"] for w in out["warnings"]]
        self.assertIn("gematria_moneyline", codes)
        self.assertEqual(codes.count("gematria_fixed"), 4)
        self.assertEqual((out["spec"]["lock_minutes"], out["spec"]["rules"][0]["when"], len(out["spec"]["rules"])), (60, None, 1))
        self.assertEqual(out["archetypes"], [])

    def test_default_sports_are_the_quizs_legacy_pair_and_a_name_is_suggested(self):
        out = quiz_compose.compose({"personality": "gematria"})
        self.assertEqual(out["spec"]["sports"], ["MLB", "NFL"])
        self.assertEqual(out["name_suggestions"][0], "Cipher")

    def test_the_english_box_can_ask_for_the_style_when_no_personality_was_picked(self):
        out = quiz_compose.compose({}, english_text="use gematria on soccer")
        self.assertEqual((out["spec"].get("style"), out["spec"]["sports"]), ("gematria", ["SOCCER"]))
        clash = quiz_compose.compose({"personality": "mystic"}, english_text="gematria")
        self.assertNotIn("style", clash["spec"])
        self.assertIn("style_conflict", [w["code"] for w in clash["warnings"]])

    def test_other_personalities_compose_exactly_as_before(self):
        spec = quiz_compose.compose({"personality": "chalk_eater", "markets": ["moneyline"]})["spec"]
        self.assertNotIn("style", spec)
        self.assertNotIn("gematria", spec)


class ParserTests(unittest.TestCase):
    def test_gematria_and_numerology_phrasing_reads_as_the_style(self):
        for text in ("gematria", "use gematria on NBA and NHL", "numerology hound for nfl", "a numerology style hound on soccer and tennis",
                     "I want the gematria style"):
            with self.subTest(text=text):
                out = parser.parse(text)
                self.assertEqual(out["spec"]["style"], "gematria")
                self.assertEqual(out["not_understood"], [])
                self.assertEqual(out["spec"]["rules"][0]["markets"], ["moneyline"])

    def test_it_reads_the_sports_the_bets_a_day_and_the_stake(self):
        out = parser.parse("Use gematria on NBA and NHL, max 3 bets a day, stake 2 units")
        spec = out["spec"]
        self.assertEqual((spec["sports"], spec["max_bets_per_day"], spec["stake_units"]), (["NBA", "NHL"], 3, 2.0))
        self.assertEqual(out["draft"]["style"], "gematria")
        self.assertIn("passes", " ".join(out["sentences"]))

    def test_any_sport_means_the_whole_menu(self):
        self.assertEqual(parser.parse("gematria any sport")["spec"]["sports"], list(user_spec.SPORTS))

    def test_no_sport_named_is_said_and_the_default_is_the_legacy_pair(self):
        out = parser.parse("gematria")
        self.assertEqual(out["spec"]["sports"], ["MLB", "NFL"])
        self.assertTrue(any("no sport was named" in a for a in out["assumed"]))

    def test_extra_rules_in_the_same_words_are_reported_not_used(self):
        out = parser.parse("gematria with home underdogs between +120 and +200")
        self.assertEqual(out["spec"]["style"], "gematria")
        self.assertTrue(any("one fixed rule" in n["reason"] for n in out["not_understood"]))
        self.assertIsNone(out["spec"]["rules"][0]["when"])

    def test_lucky_numbers_still_reads_as_the_old_date_number_condition(self):
        out = parser.parse("lucky numbers on moneylines")
        self.assertNotIn("style", out["spec"])
        self.assertEqual(out["spec"]["rules"][0]["when"]["items"][0]["id"], "numerology")


class PageHookTests(unittest.TestCase):
    """The builder lives in two homes: web/build-a-hound.html and the kennel studio (builder-skeleton.js). Every hook the
    script reads for the style picker must be in both; the same rule tests/test_kennel_page.py holds for the rest."""
    JS = (WEB / "js" / "hounds-build.js").read_text(encoding="utf-8")
    STATIC = (WEB / "build-a-hound.html").read_text(encoding="utf-8")
    SKELETON = (WEB / "js" / "builder-skeleton.js").read_text(encoding="utf-8")
    HOOKS = ("style-picker", "style-gematria", "style-explain", "style-house-link", "style-sports", "style-globals", "style-fixed")

    def test_the_script_reads_each_style_hook(self):
        for hook in self.HOOKS:
            self.assertIn(f'q("{hook}")', self.JS, hook)

    def test_each_hook_is_in_the_static_page_and_the_studio_skeleton(self):
        for hook in self.HOOKS:
            self.assertIn(f'data-hook="{hook}"', self.STATIC, hook)
            self.assertTrue(f'hook("{hook}"' in self.SKELETON or f'"data-hook": "{hook}"' in self.SKELETON, hook)

    def test_both_homes_link_the_house_gematria_hound_without_scripts(self):
        self.assertIn('data-hook="style-house-link" href="hound.html?id=gematria"', self.STATIC)
        self.assertIn('hook("style-house-link", { class: "bd-textlink", href: "hound.html?id=gematria"', self.SKELETON)

    def test_both_homes_start_the_gematria_panel_hidden_and_keep_the_cards_collapsed(self):
        self.assertRegex(self.STATIC, r'class="bd-gematria" data-hook="style-gematria" hidden')
        self.assertIn('hook("style-gematria", { class: "bd-gematria", hidden: true })', self.SKELETON)

    def test_the_page_sends_the_style_and_its_stamp_and_nothing_the_server_would_refuse(self):
        keys = re.search(r"const SPEC_KEYS = \[(.*?)\];", self.JS).group(1)
        for key in ("style", "gematria"):
            self.assertIn(f'"{key}"', keys)


if __name__ == "__main__":
    unittest.main()
