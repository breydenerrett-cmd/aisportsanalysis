"""A member Gematria hound can be trained within its OWN parameter space (owner request 2026-10-28: "chalk city ... members can't coach or
rebuild it"). Every test here fails on the code before the knobs existed.

  THE KNOBS      price band, lead, ciphers narrow the house rules and never widen them or reach -200; they are part of the spec hash,
                 stamped on every bet row and said in the published rule; an untuned hound is byte-for-byte what it was
  THE ENGINE     a tuned hound's own band vetoes the favourite an untuned hound beside it backs; one pass, two tunings, no leak; a
                 rehearsal (and only a rehearsal) may replay a Gematria hound; signals are computed once per cipher set
  FINE-TUNE      Gematria hounds are accepted, candidates are valid Gematria specs, the anti-chalk options lead the menu for a
                 favourite-heavy record, the same gate and explainer, and a plan can never change the kind of hound
  FULL REBUILD   the same pipeline with its own prompts and checks: a candidate that names another style, a rule list, an unknown knob
                 or -200 is refused whole, a too-small change is sent back once, the survivors are rehearsed together
  ADD SPORTS     widens the sports and keeps every knob

A fake replay stands in for the drill and a fake client for the SDK: nothing here reaches the network or reads a live store.
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from src.hounds import add_sports, user_engine, user_gematria as G, user_settle, user_spec, user_store
from src.hounds.interact import common, drill, gematria_training as GT, rebuild_ai, rites, training, training_plans as plans
from src.hounds.interact.rites import RiteError
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for
from tests.test_ai_hounds import NOW_AS, allsports_rows, nba_rows
from tests.test_gematria_hound import LENIENT, make_rules
from tests.test_gematria_member_style import DATE, EngineCase, gem_spec, member, runtime_factory
from tests.test_training_plans import ENV, FakeClient, GOOD_EXPLAIN, Base as PlanBase, stage_of, summary

UTC = timezone.utc


def tuned(tuning, **over):
    """A Gematria spec with the member's knobs laid over the active stamp."""
    return gem_spec(gematria=dict(G.active_stamp(), tuning=tuning), **over)


def tuned_member(tuning, hid="u-gem2", **over):
    return member(hid=hid, gematria=dict(G.active_stamp(), tuning=tuning), **over)


def favourite_rows():
    """The Celtics are the side the numbers back (as in every engine fixture here) and they are -160 favourites."""
    return allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=140, away_ml=-160,
                          spread=(-1.5, -110, -110), total=(221.5, -110, -110))


# ---------------------------------------------------------------------------------------------------------------
class TheKnobs(unittest.TestCase):
    def test_a_tuned_spec_validates_hashes_differently_and_untuned_is_unchanged(self):
        plain = gem_spec(sports=["NBA", "NHL"])
        spec = tuned({"price_min": -150}, sports=["NBA", "NHL"])
        self.assertEqual(spec["gematria"]["tuning"], {"price_min": -150})
        self.assertNotEqual(user_spec.spec_hash(spec), user_spec.spec_hash(plain))
        self.assertNotIn("tuning", plain["gematria"])
        self.assertEqual(user_spec.validate_spec(dict(spec)), spec)                          # a stored spec validates again unchanged
        self.assertEqual(set(plain["gematria"]), {"rules_version", "rules_hash"})

    def test_the_derived_rule_carries_the_members_band(self):
        rule = tuned({"price_min": -150, "price_max": 250})["rules"][0]
        self.assertEqual((rule["price_min"], rule["price_max"]), (-150, 250))

    def test_each_knob_is_checked_and_minus_200_is_never_reachable(self):
        bad = {"price_min": -200, "price_max": 401, "min_margin": 99, "min_margin_text": 1, "min_z": -1, "min_z_big": 1, "ciphers": ["EO"],
               "ciphers_unknown": ["EO", "XX"]}
        for tuning in ({"price_min": -200}, {"price_min": -250}, {"price_min": 50}, {"price_max": 401}, {"min_margin": 99}, {"min_margin": True},
                       {"min_z": -1}, {"min_z": 9}, {"ciphers": ["EO"]}, {"ciphers": ["EO", "XX"]}, {"ciphers": "EO,FR"}, {"nope": 1},
                       {"price_min": 300, "price_max": 150}, "price_min"):
            with self.subTest(tuning=tuning), self.assertRaises(user_spec.SpecError) as ctx:
                tuned(tuning)
            self.assertIn("gematria", ctx.exception.errors)
        self.assertIsNotNone(bad)

    def test_the_knobs_only_narrow_the_house_rules(self):
        house = make_rules()
        wide = G.tuned_rules(house, {"price_min": -199, "price_max": 400, "min_margin": 0.5, "min_z": 0.0})
        self.assertEqual(wide.decision.price_band, house.decision.price_band)
        self.assertGreaterEqual(wide.decision.min_margin, house.decision.min_margin)       # never under the house floor
        narrow = G.tuned_rules(house, {"price_min": -150, "price_max": 250, "min_margin": 9.0, "ciphers": ["FR", "EO"]})
        self.assertEqual(narrow.decision.price_band, (-150, 250))
        self.assertEqual(narrow.decision.min_margin, 9.0)
        self.assertEqual(narrow.ciphers, ("EO", "FR"))
        self.assertEqual(set(narrow.cipher_weights), {"EO", "FR"})
        self.assertEqual(house.decision.price_band, (-199, 400))                            # the house rules object is never touched

    def test_the_published_rule_names_the_members_settings(self):
        text = user_spec.rule_text(tuned({"price_min": -150, "ciphers": ["EO", "FR"]}, sports=["NBA"]))
        self.assertIn("between -150 and", text)
        self.assertIn("its own settings for the price band and the ciphers it reads (EO, FR)", text)
        self.assertIn("never -200 or worse", text)
        plain = user_spec.rule_text(gem_spec())
        self.assertNotIn("its own settings", plain)
        self.assertIn("It runs the house Gematria Hound's rules", plain)

    def test_a_diff_between_a_tuned_and_an_untuned_hound_names_the_knobs(self):
        from src.hounds.english import render
        old, new = gem_spec(), tuned({"price_min": -150, "min_margin": 3.0})
        got = {c["what"]: (c["before"], c["after"]) for c in render.diff_specs(old, new)}
        self.assertIn("Price band", got)
        self.assertTrue(got["Price band"][1].startswith("-150 to"))
        self.assertEqual(got["Lead needed"][1].split(" and ")[0], "at least 3")


# ---------------------------------------------------------------------------------------------------------------
class TheEngine(EngineCase):
    def test_a_tuned_price_band_vetoes_the_favourite_an_untuned_hound_beside_it_backs(self):
        rows = favourite_rows()
        plain = member("u-plain")
        stayoff = tuned_member({"price_min": -150})
        out = self.run_engine([plain, stayoff], rows=rows)
        self.assertEqual(out["by_hound"], {"u-plain": 1})
        self.assertEqual(out["skipped"].get("gematria_outside_band"), 1)
        (row,) = self.bets()
        self.assertEqual((row["hound_id"], row["price_average"]), ("u-plain", -160))

    def test_plus_money_only_passes_on_the_same_board_it_just_refused_a_favourite(self):
        out = self.run_engine([tuned_member({"price_min": 100})])
        self.assertEqual((out["bets_written"], out["skipped"]), (1, {}))                       # the standard fixture backs a +100 side
        (row,) = self.bets()
        self.assertEqual(row["price_average"], 100)

    def test_a_higher_lead_passes_a_game_the_house_lead_takes(self):
        """The decision itself, on a game that leads by 3: the house floor (0.5) backs it, a member's floor of 4 passes it. (The engine
        fixture leads by 16, more than any knob can ask for, so the decision is exercised directly.)"""
        from src.hounds.gematria import decision as decision_mod, signals as sig_mod
        house = make_rules(**LENIENT)
        sig = sig_mod.Signals(home=sig_mod.SideSignals("home", score=5.0, comparisons=10, milestones=5),
                              away=sig_mod.SideSignals("away", score=2.0, comparisons=10, milestones=5))
        side = {"price_average": 110, "price_best": 112, "book": "b", "book_count": 5, "fair": 0.47}
        board = {"markets": {"moneyline": {"line": None, "books": 5, "sides": {"home": side, "away": dict(side, price_average=-130)}}}}
        args = dict(history_available=True, teams_known=True)
        self.assertTrue(decision_mod.decide(sig, board, house, **args).is_bet)
        stricter = decision_mod.decide(sig, board, G.tuned_rules(house, {"min_margin": 4.0}), **args)
        self.assertEqual((stricter.is_bet, stricter.code), (False, "small_margin"))

    def test_the_bet_row_says_which_settings_it_was_made_under(self):
        self.run_engine([tuned_member({"price_max": 150}), member("u-plain")])
        rows = {r["hound_id"]: r for r in self.bets()}
        self.assertEqual(rows["u-gem2"]["tuning"], {"price_max": 150})
        self.assertNotIn("tuning", rows["u-plain"])

    def test_two_tunings_in_one_pass_never_leak_into_each_other(self):
        out = self.run_engine([tuned_member({"price_min": 100}, hid="u-a"), tuned_member({"price_min": -150}, hid="u-b"), member("u-c")],
                              rows=favourite_rows())
        self.assertEqual(out["by_hound"], {"u-c": 1})

    def test_the_analysis_and_why_paths_take_the_tuning_too(self):
        from src.hounds.interact import unleash_why
        spec = tuned({"price_min": -150}, sports=["NBA"])
        weigher = G.Weigher({}, runtime=runtime_factory()())
        self.assertEqual(weigher.runtime_for(G.tuning_of(spec)).rules.decision.price_band[0], -150)
        self.assertIs(weigher.runtime_for(None), weigher.runtime)
        self.assertTrue(callable(unleash_why.gematria_bucket))

    def test_signals_are_computed_once_per_cipher_set_however_many_tunings_read_them(self):
        calls = []

        class Counting(rt_cls()):
            def prepare(self, ctx, *, known_at=None):
                calls.append(1)
                return super().prepare(ctx, known_at=known_at)

        base_rt = runtime_factory()()
        counting = Counting(rules=base_rt.rules, facts=base_rt.facts, source=base_rt.source, ledger=None, now_fn=lambda: NOW_AS)
        games = user_engine.build_games(nba_rows(), near_date=DATE)
        weigher = G.Weigher(games, runtime=counting)
        eid = next(iter(games))
        for tuning in (None, {"price_min": -150}, {"min_margin": 2.0}, {"ciphers": ["EO", "FR"]}):
            weigher.weigh(eid, tuning=tuning)
        self.assertEqual(len(calls), 2)                                                          # the full cipher set once, EO+FR once


def rt_cls():
    from src.hounds.gematria import runtime as rt
    return rt.GematriaRuntime


class TheRehearsal(EngineCase):
    def test_only_a_hound_marked_as_a_rehearsal_is_replayed(self):
        refused = self.run_engine([member()], mode="replay")
        self.assertEqual((refused["bets_written"], refused["skipped"]), (0, {G.FORWARD_ONLY_CODE: 1}))
        replayed = self.run_engine([{**member(), "rehearsal": True}], mode="replay")
        self.assertEqual(replayed["bets_written"], 1)
        (row,) = self.bets()
        self.assertEqual((row["side"], row["price_average"]), ("away", 100))
        self.assertLess(row["recorded_utc"], row["start_utc"])

    def test_a_rehearsal_applies_the_members_tuning(self):
        out = self.run_engine([{**tuned_member({"price_min": -150}), "rehearsal": True}], mode="replay", rows=favourite_rows())
        self.assertEqual((out["bets_written"], out["skipped"].get("gematria_outside_band")), (0, 1))

    def test_the_public_backtest_still_refuses_a_gematria_hound(self):
        spec = gem_spec(sports=["NBA"])
        with self.assertRaises(drill.DrillError) as ctx:
            drill.drill(spec=dict(spec), days=7, now=NOW)
        self.assertEqual(ctx.exception.code, "gematria_forward_only")
        dog = common.Dog(id="u-x", kind=common.KIND_USER, name="Numbers Pup", hound={"id": "u-x", "spec": spec}, owner_user_id=1)
        with self.assertRaises(drill.DrillError) as ctx:
            drill.drill(dog=dog, days=7, now=NOW)
        self.assertEqual(ctx.exception.code, "gematria_forward_only")

    def test_one_pass_rehearses_the_current_rule_and_every_candidate(self):
        now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        specs = [gem_spec(sports=["NBA"]), tuned({"price_min": 110}, sports=["NBA"]), tuned({"price_max": -110}, sports=["NBA"])]
        with mock.patch.object(G, "make_runtime", runtime_factory()), mock.patch.object(user_settle, "settle", lambda **k: None), \
                mock.patch.object(user_engine, "ledger_path", lambda p=None: p or self.ledger):
            out = drill.drill_many(specs=specs, days=7, now=now, rows_by_date={DATE: nba_rows()}, mlb_results={}, nfl_results=lambda d: {},
                                   game_pk_index={})
        self.assertEqual([o["record"]["bets"] for o in out], [1, 0, 0])                         # the current rule bets; both tightenings pass

    def test_a_rehearsal_summary_is_per_spec_and_never_counted(self):
        self.assertTrue(plans.default_replay_many)
        self.assertEqual(plans.days_for(gem_spec()), plans.REPLAY_DAYS_GEMATRIA)
        self.assertEqual(plans.days_for(user_spec.validate_spec({"version": 2, "name": "Plain Pup", "rules": [{"sports": ["MLB"], "markets": ["moneyline"]}]})),
                         plans.REPLAY_DAYS)


# ---------------------------------------------------------------------------------------------------------------
CHALKY = [(9, dict(result="LOSS", side="home", price=-170, sport="NBA")), (4, dict(result="WIN", side="home", price=-170, sport="NBA")),
          (3, dict(result="WIN", side="away", price=120, sport="NBA"))]
PLUS = [(8, dict(result="LOSS", side="away", price=130, sport="NBA")), (6, dict(result="WIN", side="away", price=150, sport="NBA"))]


def gem_replay(good=lambda t: t.get("price_min", -199) >= -150):
    """The current rule: 40 graded bets at -6 units. A candidate for which ``good(tuning)`` holds: 30 bets at +2. Every other: the current numbers."""
    def replay(spec, days, now):
        tuning = G.tuning_of(spec) or {}
        if tuning and good(tuning):
            return summary(30, 2.0, days=days)
        return summary(40, -6.0, days=days)
    return replay


class GemBase(PlanBase):
    """The training fixtures with a Gematria hound in place of the rule-set one."""

    ledger_rows = CHALKY

    def setUp(self):
        super().setUp()
        self.hound_row = user_store.create_hound(self.owner.id, {"version": 2, "style": "gematria", "name": "Numbers Pup",
                                                                 "sports": ["NBA", "NHL"], "max_bets_per_day": 3, "stake_units": 1.0})
        self.rows = rows_for(self.hound_row["id"], self.ledger_rows)
        self.rebuild_calls = []


class GematriaFineTune(GemBase):
    def test_a_gematria_hound_is_fine_tuned_not_refused(self):
        card = self.fine(replay_fn=gem_replay())
        self.assertTrue(card["found"], card.get("message"))
        plan = self.store.load(card["plan_id"])
        spec = plan["choices"]["main"]["spec"]
        self.assertTrue(user_spec.is_gematria(spec))
        self.assertEqual(spec["gematria"]["rules_hash"], self.hound_row["spec"]["gematria"]["rules_hash"])
        self.assertEqual(card["rehearsal"]["days"], plans.REPLAY_DAYS_GEMATRIA)
        self.assertEqual((card["rehearsal"]["before"]["units"], card["rehearsal"]["after"]["units"]), (-6.0, 2.0))
        self.assertTrue(card["beats_current"])
        self.assertIn("Price band", [d["what"] for d in card["diff"]])
        self.assertFalse(card["rehearsal"]["counted"])

    def test_the_best_change_applies_as_a_gematria_version_with_the_knobs(self):
        card = self.fine(replay_fn=gem_replay())
        out = plans.apply_plan(self.dog_obj(), self.owner.id, card["plan_id"], now=NOW, rows=self.rows, db=self.db, store=self.store)
        new = user_store.get_hound(out["new"]["id"], db=self.db)
        self.assertEqual((new["version_no"], new["origin"]), (2, user_store.ORIGIN_FINE_TUNE))
        self.assertTrue(user_spec.is_gematria(new["spec"]))
        self.assertGreaterEqual(new["spec"]["gematria"]["tuning"]["price_min"], -150)
        self.assertEqual(out["undo"]["to_version"], 1)

    def test_a_favourite_heavy_record_puts_the_anti_chalk_options_first(self):
        spec = self.hound_row["spec"]
        bets = rites.forward_bets(self.hound_row["id"], self.rows)
        chalk = GT.chalk_report(bets)
        self.assertTrue(chalk["chalk"])
        self.assertEqual((chalk["bets"], chalk["favourites"], chalk["heavy"]), (16, 13, 13))
        entries = GT.menu(spec, training.analyse(bets, spec, {}), bets)
        self.assertEqual([e["cid"] for e in entries[:2]], ["price_floor:-150", "price_floor:100"])
        built = [training._apply_entry(copy.deepcopy(dict(spec)), e, "minor") for e in entries[:2]]        # noqa: SLF001
        self.assertEqual([b[0]["gematria"]["tuning"]["price_min"] for b in built], [-150, 100])
        self.assertIn("favourites", entries[0]["why"])

    def test_the_card_says_how_it_leans(self):
        card = self.fine(replay_fn=gem_replay())
        self.assertTrue(card["chalk"]["chalk"])
        self.assertIn("13 of its 16 bets were on favourites", card["chalk"]["text"])

    def test_the_anti_chalk_options_are_still_on_the_menu_for_a_plus_money_hound_but_do_not_lead(self):
        self.rows = rows_for(self.hound_row["id"], PLUS)
        bets = rites.forward_bets(self.hound_row["id"], self.rows)
        self.assertFalse(GT.chalk_report(bets)["chalk"])
        entries = GT.menu(self.hound_row["spec"], training.analyse(bets, self.hound_row["spec"], {}), bets)
        cids = [e["cid"] for e in entries]
        self.assertNotIn(cids[0], ("price_floor:-150", "price_floor:100"))
        self.assertIn("price_floor:-150", cids)

    def test_every_menu_entry_is_a_valid_gematria_spec_that_never_reaches_minus_200(self):
        spec = tuned({"price_min": -150, "min_margin": 2.0, "ciphers": ["EO", "FR", "RO"]}, sports=["NBA", "NHL"])
        bets = rites.forward_bets(self.hound_row["id"], self.rows)
        entries = GT.menu(spec, training.analyse(bets, spec, {}), bets)
        self.assertTrue(entries)
        for entry in entries:
            cand = entry["build"](copy.deepcopy(dict(spec)))
            valid = user_spec.validate_spec(cand["spec"], taken_names=())
            self.assertTrue(user_spec.is_gematria(valid), entry["cid"])
            self.assertGreater(valid["rules"][0]["price_min"], user_spec.MAX_FAVOURITE_PRICE)
        self.assertIn("loosen:price_min", [e["cid"] for e in entries])                            # and the ways back toward the house rules

    def test_nothing_better_is_nothing_offered_and_the_chalk_is_still_said(self):
        flat = lambda spec, days, now: summary(40, -6.0, days=days)                               # noqa: E731
        card = self.fine(replay_fn=flat)
        self.assertFalse(card["found"])
        self.assertTrue(card["rebuild_offer"])
        self.assertIn("leans on favourites", card["message"])
        self.assertIn("None of the", card["message"])

    def test_the_candidates_share_one_pass_when_a_batch_replay_exists(self):
        seen = []

        def many(specs, days, now):
            seen.append((len(specs), days))
            return [gem_replay()(sp, days, now) for sp in specs]
        single = mock.Mock(side_effect=gem_replay())
        card = plans.fine_tune(self.dog_obj(), self.owner.id, client=FakeClient(lambda kw: GOOD_EXPLAIN),
                               **self.common(replay_fn=single, replay_many_fn=many))
        self.assertTrue(card["found"])
        self.assertEqual(seen[0][1], plans.REPLAY_DAYS_GEMATRIA)
        self.assertGreater(seen[0][0], 3)                                                         # the current rule and the candidates, together
        self.assertLessEqual(seen[0][0], plans.GEMATRIA_MAX_REPLAYS + 1)
        self.assertEqual(len(seen), 1)

    def test_a_saved_plan_that_would_change_the_kind_of_hound_is_refused(self):
        card = self.fine(replay_fn=gem_replay())
        plan = self.store.load(card["plan_id"])
        plain = user_spec.validate_spec({"version": 2, "name": "Numbers Pup", "rules": [{"sports": ["NBA"], "markets": ["moneyline"]}]})
        plan["choices"]["main"]["spec"] = plain
        bad_id = self.store.save({k: v for k, v in plan.items() if k not in ("plan_id", "saved_at")})
        with self.assertRaises(RiteError) as ctx:
            plans.apply_plan(self.dog_obj(), self.owner.id, bad_id, now=NOW, rows=self.rows, db=self.db, store=self.store)
        self.assertEqual(ctx.exception.code, "spec_invalid")
        self.assertEqual(len(user_store.lineage(self.hound_row["id"], db=self.db)), 1)

    def test_an_ordinary_hound_can_not_be_turned_into_a_gematria_one_by_a_plan(self):
        plain_row = self.dog("Plain Pup", sports=["MLB"])
        rows = rows_for(plain_row["id"], [(6, dict(result="LOSS", side="away", price=180)), (6, dict(result="WIN", side="away", price=180))])
        dog = common.resolve(plain_row["id"])
        card = plans.fine_tune(dog, self.owner.id, client=FakeClient(lambda kw: GOOD_EXPLAIN),
                               **self.common(rows=rows, replay_fn=lambda sp, d, n: summary(40, -4.0, days=d) if sp.get("max_bets_per_day") != 1 else summary(30, 2.0, days=d)))
        plan = self.store.load(card["plan_id"])
        plan["choices"]["main"]["spec"] = gem_spec(sports=["MLB"])
        bad_id = self.store.save({k: v for k, v in plan.items() if k not in ("plan_id", "saved_at")})
        with self.assertRaises(RiteError) as ctx:
            plans.apply_plan(dog, self.owner.id, bad_id, now=NOW, rows=rows, db=self.db, store=self.store)
        self.assertEqual(ctx.exception.code, "spec_invalid")


# ---------------------------------------------------------------------------------------------------------------
def gem_angle_of(kw) -> str:
    text = kw["messages"][0]["content"]
    return next((a[0] for a in GT.GEM_ANGLES if f"YOUR ANGLE: {a[1]}." in text), "?")


BIG = {"sports": ["NBA"], "max_bets_per_day": 2, "stake_units": 1.0, "tuning": {"price_min": -150, "min_margin": 2.0, "ciphers": ["EO", "FR"]}}


def gem_responder(per_angle=None, analyst=None):
    per_angle = per_angle or {}

    def responder(kw):
        stage = stage_of(kw)
        if stage == "angle":
            a = gem_angle_of(kw)
            spec = per_angle.get(a, BIG)
            return {"summary": f"{a} angle rebuild", "spec_json": json.dumps(spec)}
        if stage == "analyst":
            return analyst if analyst is not None else {"chosen": "merge", "spec_json": json.dumps(dict(BIG, max_bets_per_day=1)),
                                                       "reasons": ["Fewer clearer bets"], "cut": ["favourites"], "added": ["a lead"],
                                                       "weak_spots": ["the sample is small"]}
        return GOOD_EXPLAIN
    return responder


class GematriaRebuild(GemBase):
    def gem_rebuild(self, responder=None, **over):
        client = FakeClient(responder or gem_responder())
        card = plans.full_rebuild(self.dog_obj(), self.owner.id, client=client, **self.common(replay_fn=gem_replay(lambda t: True), **over))
        return card, client

    def test_a_gematria_hound_is_rebuilt_not_refused(self):
        card, client = self.gem_rebuild()
        self.assertTrue(card["found"], card)
        self.assertTrue(card["chalk"]["chalk"])
        plan = self.store.load(card["plan_id"])
        self.assertTrue(plan["choices"])
        for choice in plan["choices"].values():
            self.assertTrue(user_spec.is_gematria(choice["spec"]))
            self.assertEqual(choice["spec"]["gematria"]["rules_hash"], self.hound_row["spec"]["gematria"]["rules_hash"])
            self.assertEqual(choice["spec"]["name"], "Numbers Pup")
        self.assertIn("Gematria hound", client.calls[0]["system"])
        self.assertIn("price_min", client.calls[0]["messages"][0]["content"])
        self.assertEqual(card["explanation"]["source"], "ai")
        self.assertEqual(card["rehearsal"]["days"], plans.REPLAY_DAYS_GEMATRIA)

    def test_a_hockey_named_gematria_hound_is_told_its_core(self):
        """The rule-set rebuild has told the model the core since 2026-10-29; the Gematria designer gets the same line (rebuild_ai.core_lines)."""
        self.hound_row = user_store.create_hound(self.owner.id, {"version": 2, "style": "gematria", "name": "Hockey Numbers",
                                                                 "sports": ["NBA", "NHL"], "max_bets_per_day": 3, "stake_units": 1.0})
        self.rows = rows_for(self.hound_row["id"], self.ledger_rows)
        _card, client = self.gem_rebuild()
        self.assertIn("CORE (HARD LIMIT): this hound is built around NHL", client.calls[0]["messages"][0]["content"])

    def test_a_gematria_hound_with_no_core_is_told_nothing_about_one(self):
        _card, client = self.gem_rebuild()
        self.assertNotIn("CORE (HARD LIMIT)", client.calls[0]["messages"][0]["content"])

    def test_the_rebuild_applies_as_a_gematria_version(self):
        card, _client = self.gem_rebuild()
        out = plans.apply_plan(self.dog_obj(), self.owner.id, card["plan_id"], now=NOW, rows=self.rows, db=self.db, store=self.store)
        new = user_store.get_hound(out["new"]["id"], db=self.db)
        self.assertEqual((new["version_no"], new["origin"]), (2, user_store.ORIGIN_REBUILD))
        self.assertTrue(user_spec.is_gematria(new["spec"]))
        self.assertIn("tuning", new["spec"]["gematria"])

    def test_survivors_are_rehearsed_together_in_one_batch(self):
        batches = []

        def many(specs, days, now):
            batches.append(len(specs))
            return [gem_replay(lambda t: True)(sp, days, now) for sp in specs]
        card, _c = self.gem_rebuild(replay_many_fn=many)
        self.assertTrue(card["found"])
        self.assertEqual(len(batches), 1)

    def test_a_candidate_that_names_another_style_a_rule_list_or_an_unknown_knob_is_refused_whole(self):
        cur = rebuild_ai.v2_of(self.hound_row["spec"])
        cases = {
            "style": {"style": "rules", "sports": ["NBA"]},
            "knob": dict(BIG, tuning={"price_min": -150, "magic": 3}),
            "extra key": dict(BIG, bankroll=100),
            "-200": dict(BIG, tuning={"price_min": -200}),
            "one cipher": dict(BIG, tuning={"ciphers": ["EO"]}),
            "no sports": dict(BIG, sports=[]),
            "text": "not json",
            "list": [1, 2],
        }
        for label, raw in cases.items():
            with self.subTest(label=label):
                spec, why = GT.vet(raw, cur)
                self.assertIsNone(spec)
                self.assertTrue(why)

    def test_vet_builds_from_the_current_spec_so_the_kind_name_and_stamp_cannot_move(self):
        cur = rebuild_ai.v2_of(self.hound_row["spec"])
        echo = dict(BIG, style="gematria", name="Evil", color="gold", rules=[{"sports": ["MLB"], "markets": ["spread"]}])   # derived fields are ignored
        spec, why = GT.vet(json.dumps(echo), cur)
        self.assertIsNone(why)
        self.assertEqual((spec["name"], spec["color"], spec["style"]), ("Numbers Pup", cur["color"], "gematria"))
        self.assertEqual(spec["rules"][0]["markets"], ["moneyline"])
        self.assertEqual(spec["sports"], ["NBA"])
        self.assertEqual(spec["gematria"]["tuning"], BIG["tuning"])
        self.assertEqual({k: v for k, v in spec["gematria"].items() if k != "tuning"}, {k: v for k, v in cur["gematria"].items() if k != "tuning"})

    def test_a_rule_list_with_no_gematria_style_is_not_a_gematria_hounds_answer(self):
        cur = rebuild_ai.v2_of(self.hound_row["spec"])
        spec, why = GT.vet(dict(BIG, rules=[{"sports": ["MLB"], "markets": ["spread"]}]), cur)
        self.assertIsNone(spec)
        self.assertIn("stays a Gematria hound", why)

    def test_a_tweak_is_sent_back_once_and_dropped_if_it_stays_a_tweak(self):
        tweak = dict(BIG, tuning={"min_margin": 2.0}, sports=["NBA", "NHL"], max_bets_per_day=3)
        card, client = self.gem_rebuild(gem_responder(per_angle={a[0]: tweak for a in GT.GEM_ANGLES}))
        self.assertFalse(card["found"])                                                         # nothing passed the checks
        angle_calls = [c for c in client.calls if stage_of(c) == "angle"]
        self.assertEqual(len(angle_calls), 2 * len(GT.angles()))                                # every angle was sent back once
        self.assertIn("a rebuild must differ by at least", angle_calls[-1]["messages"][0]["content"])

    def test_the_distance_counts_what_the_hound_comes_to_not_how_it_is_spelled(self):
        base = self.hound_row["spec"]
        explicit_house = tuned({"price_min": -199, "price_max": 400}, sports=["NBA", "NHL"], max_bets_per_day=3)
        self.assertEqual(GT.distance(base, explicit_house)["points"], 0)
        far = GT.vet(BIG, base)[0]
        d = GT.distance(base, far)
        self.assertFalse(GT.too_similar(d))
        self.assertGreaterEqual(d["areas"], 3)
        self.assertTrue(GT.too_similar(GT.distance(base, GT.vet(dict(BIG, sports=["NBA", "NHL"], max_bets_per_day=3, tuning={"min_margin": 2.0}), base)[0])))


# ---------------------------------------------------------------------------------------------------------------
class AddSportsToAGematriaHound(RitesCase):
    def test_the_sports_widen_and_every_knob_is_kept(self):
        row = user_store.create_hound(self.owner.id, {"version": 2, "style": "gematria", "name": "Numbers Pup", "sports": ["NBA"], "max_bets_per_day": 3,
                                                      "stake_units": 2.0, "gematria": dict(G.active_stamp(), tuning={"price_min": -150, "min_z": 1.5})})
        out = add_sports.apply(row["id"], "NHL,MLB", db=self.db)
        new = user_store.get_hound(out["new_id"], db=self.db)
        self.assertEqual(new["spec"]["sports"], ["MLB", "NBA", "NHL"])
        self.assertEqual(new["spec"]["gematria"]["tuning"], {"min_z": 1.5, "price_min": -150})
        self.assertEqual((new["spec"]["max_bets_per_day"], new["spec"]["stake_units"]), (3, 2.0))
        self.assertTrue(user_spec.is_gematria(new["spec"]))
        self.assertEqual(new["version_no"], 2)
        self.assertEqual(out["added"], ["NHL", "MLB"])

    def test_all_adds_every_sport_on_the_menu_and_a_sport_it_already_plays_is_skipped(self):
        row = user_store.create_hound(self.owner.id, {"version": 2, "style": "gematria", "name": "Numbers Pup", "sports": ["NBA"], "max_bets_per_day": 3,
                                                      "stake_units": 1.0})
        out = add_sports.apply(row["id"], "all", dry_run=True, db=self.db)
        self.assertEqual(set(out["spec"]["sports"]), set(user_spec.SPORTS))
        self.assertNotIn("NBA", out["added"])
        self.assertIn(("NBA", "already on the hound"), out["skipped"])
        with self.assertRaises(add_sports.AddSportsError):
            add_sports.plan({"spec": row["spec"]}, "NBA")


if __name__ == "__main__":
    unittest.main()
