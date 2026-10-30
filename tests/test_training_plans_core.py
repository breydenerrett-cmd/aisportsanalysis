"""Fine-tune and Full rebuild keep a hound's core (src/hounds/interact/training_plans.py, identity.py, rebuild_ai.py).

THE GAP (2026-10-29). Send to training learned that HOCKEYCHIEF is a hockey hound and stopped offering to drop NHL (tests/test_hounds_identity.py),
but its two siblings on the same screen still called the unprotected functions: Fine-tune's menu held ``drop_sport:NHL`` and a rebuilt rule set
could come back without a single NHL rule. Each test here pins one piece of closing it:

  FINE-TUNE   the menu and the analysis are the ones Send to training uses, so NHL is never tried, never rehearsed and never offered, even
              when a rehearsal would reward leaving it; a sport that is NOT core can still go
  REBUILD     a candidate (or the analyst's merge) that no longer bets the core is set aside BEFORE any rehearsal or ranking and counted in the
              no-candidate ``why`` in the owner's words; the model is told the core as a hard limit; the spec's own ``core`` list survives a rebuild
  APPLY       a plan saved before the lock existed cannot be applied if it drops the core

No model, no network: a fake client stands in for the SDK and a fake replay for the drill.
"""

from __future__ import annotations

import copy
import json

from src.hounds import user_spec, user_store
from src.hounds.interact import identity, rebuild_ai, rebuild_budget as budget, retune, training, training_plans as plans
from src.hounds.interact.rites import RiteError
from tests._hounds_rites_fixtures import NOW, rows_for
from tests.test_hounds_identity import NHL_BAD, SPORTS
from tests.test_training_plans import RULE_SET, Base, FakeClient, big_spec, fake_replay, stage_of, standard_responder, summary

CORE_LINE = "which this hound is built around"


def replay_that_pays_for(leaves_out):
    """A rehearsal fake that REWARDS any rule set missing ``leaves_out`` (30 graded bets, +2 units against a base of 40 at -4), and records the
    sports of every rule set it was asked to rehearse, so a test can say what was and was not tried."""
    seen: list = []

    def replay(spec, days, now):
        seen.append(list(spec["sports"]))
        return summary(30, 2.0, days=days) if leaves_out not in spec["sports"] else summary(40, -4.0, days=days)
    replay.seen = seen
    return replay


def replay_spy():
    """The ordinary fake rehearsal, recording the sports of every rule set it is asked about (the first is always the rules the hound has now)."""
    seen: list = []

    def replay(spec, days, now):
        seen.append(list(spec["sports"]))
        return fake_replay(spec, days, now)
    replay.seen = seen
    return replay


class HockeyBase(Base):
    """The production hound: named for hockey, bets NHL, tennis and MLB, and an NHL record bad enough to be a real weak spot (2-10)."""

    def setUp(self):
        super().setUp()
        self.hound_row = self.dog("HOCKEYCHIEF", sports=SPORTS)
        self.rows = rows_for(self.hound_row["id"], NHL_BAD)

    def assertUntouched(self):
        self.assertEqual(len(user_store.lineage(self.hound_row["id"], db=self.db)), 1, "no version was made")


class TheCoreHelpers(Base):
    CORE = {"sports": ["NHL"], "markets": ["total"], "source": "name"}

    def test_a_rule_set_that_still_names_the_sport_in_any_rule_keeps_it(self):
        old = {"sports": ["MLB", "NHL"], "markets": ["moneyline", "total"]}
        new = {"sports": ["NHL"], "markets": ["total"], "rules": []}
        self.assertEqual(identity.dropped_by(self.CORE, old, new), {"sports": [], "markets": []})

    def test_a_dropped_sport_and_a_dropped_market_are_both_named(self):
        old = {"sports": ["MLB", "NHL"], "markets": ["moneyline", "total"]}
        new = {"sports": ["MLB"], "markets": ["moneyline"]}
        got = identity.dropped_by(self.CORE, old, new)
        self.assertEqual(got, {"sports": ["NHL"], "markets": ["total"]})
        self.assertEqual(identity.dropped_names(got), ["NHL", "total"])

    def test_a_spec_with_only_rules_is_read_from_its_rules(self):
        new = {"rules": [{"sports": ["MLB"], "markets": ["moneyline"]}]}
        self.assertEqual(identity.dropped_by(self.CORE, {"sports": ["NHL", "MLB"], "markets": ["total"]}, new)["sports"], ["NHL"])

    def test_nothing_is_dropped_without_a_core_or_a_new_spec(self):
        old = {"sports": ["NHL"], "markets": ["total"]}
        self.assertEqual(identity.dropped_by(None, old, {"sports": ["MLB"]}), {"sports": [], "markets": []})
        self.assertEqual(identity.dropped_by(self.CORE, old, None), {"sports": [], "markets": []})

    def test_a_sport_the_hound_does_not_bet_today_cannot_be_dropped(self):
        self.assertEqual(identity.dropped_by({"sports": ["NHL"], "markets": []}, {"sports": ["MLB"]}, {"sports": ["TENNIS"]})["sports"], [])


class FineTuneKeepsTheCore(HockeyBase):
    def test_the_core_is_read_for_the_production_hound(self):
        dog, _moment, rows, bets, hound, _gate = plans._gate(self.dog_obj(), self.owner.id, NOW, self.rows, None, self.db)
        core, analysis = plans._read(dog, hound, bets, rows)
        self.assertEqual(core["sports"], ["NHL"])
        self.assertEqual(analysis["core"]["sports"], ["NHL"])
        self.assertIn("NHL", [h["key"] for h in analysis["held"] if h.get("reason") == "core"])        # NHL 2-10 is a real weak spot, held back
        self.assertNotIn("NHL", [w["key"] for w in analysis["weak"]])

    def test_the_menu_never_offers_to_drop_the_core_and_never_carries_the_do_nothing_item(self):
        hound = user_store.get_hound(self.hound_row["id"], db=self.db)
        analysis = training.analyse([], hound["spec"], {}, core=identity.identity_of(hound))
        cids = [e["cid"] for e in plans._minor_candidates(hound["spec"], analysis)]
        self.assertNotIn("drop_sport:NHL", cids)
        self.assertNotIn(retune.KEEP_CID, cids)
        self.assertIn("drop_sport:TENNIS", cids)
        # the same hound with no core read (what Fine-tune did until now) tries to drop NHL
        bare = [e["cid"] for e in plans._minor_candidates(hound["spec"], training.analyse([], hound["spec"], {}))]
        self.assertIn("drop_sport:NHL", bare)

    def test_a_rehearsal_that_rewards_leaving_nhl_out_cannot_make_fine_tune_leave_it_out(self):
        replay = replay_that_pays_for("NHL")
        card = self.fine(replay_fn=replay)
        self.assertFalse(card["found"])
        self.assertNotIn("plan_id", card)
        self.assertTrue(replay.seen)
        self.assertTrue(all("NHL" in sports for sports in replay.seen), replay.seen)             # not offered, and not even rehearsed
        self.assertEqual(list((self.dir / "plans").glob("*.json")) if (self.dir / "plans").exists() else [], [])

    def test_a_sport_that_is_not_core_can_still_be_dropped(self):
        replay = replay_that_pays_for("TENNIS")
        card = self.fine(replay_fn=replay)
        self.assertTrue(card["found"])
        spec = self.store.load(card["plan_id"])["choices"]["main"]["spec"]
        self.assertIn("NHL", spec["sports"])
        self.assertNotIn("TENNIS", spec["sports"])

    def test_the_hound_with_no_core_is_fine_tuned_as_before(self):
        """Rusty Pup (MLB and NFL, no sport word in its name) may still lose a sport: nothing is locked for a hound that is not for one."""
        rusty = self.dog("Rusty Pup Two", sports=["MLB", "NFL"], markets=["moneyline", "spread"], side_rule="underdog")
        self.assertEqual(identity.core_of(user_store.get_hound(rusty["id"], db=self.db)), [])
        hound = user_store.get_hound(rusty["id"], db=self.db)
        analysis = training.analyse([], hound["spec"], {}, core=identity.identity_of(hound))
        self.assertIn("drop_sport:NFL", [e["cid"] for e in plans._minor_candidates(hound["spec"], analysis)])


class RebuildKeepsTheCore(HockeyBase):
    def run_rebuild(self, responder=None, replay=None, **over):
        replay = replay or replay_spy()
        client = FakeClient(responder or standard_responder())
        card = plans.full_rebuild(self.dog_obj(), self.owner.id, client=client, **self.common(**dict({"replay_fn": replay}, **over)))
        return card, client, replay

    def test_every_version_that_drops_nhl_is_set_aside_before_any_rehearsal_and_counted(self):
        """The standard answers are 1 to 3 rules of MLB and NFL: none of them bets NHL."""
        card, client, replay = self.run_rebuild()
        self.assertFalse(card["found"])
        why = card["why"]
        self.assertEqual((why["tried"], why["core_dropped"], why["core_names"]), (6, 6, ["NHL"]))
        self.assertEqual((why["built"], why["rehearsed"], why["broke_checks"], why["too_close"]), (0, 0, 0, 0))
        self.assertIn(f"6 versions dropped NHL, {CORE_LINE}, so they were set aside.", why["lines"])
        self.assertTrue(2 <= len(why["lines"]) <= 4)
        self.assertEqual(len(replay.seen), 1, "only the rules it has now were rehearsed")
        self.assertEqual(sorted(stage_of(c) for c in client.calls), ["angle"] * rebuild_ai.ANGLE_COUNT, "no analyst, no write-up for nothing")
        # real money was spent, so the ledger has it, but it is not one of the day's rebuilds
        (row,) = self.ledger_book.rows()
        self.assertEqual(row["status"], budget.NO_CANDIDATE_STATUS)
        self.assertEqual(self.ledger_book.used_today(self.owner.id), 0)
        self.assertEqual(list((self.dir / "plans").glob("*.json")) if (self.dir / "plans").exists() else [], [])

    def test_a_version_that_keeps_nhl_is_rehearsed_and_ranked_and_the_rest_never_are(self):
        keeps = big_spec(4, max_bets_per_day=3)
        card, _client, replay = self.run_rebuild(standard_responder(per_angle={"timing": keeps}))
        self.assertTrue(card["found"])
        self.assertTrue(all("NHL" in sports for sports in replay.seen[1:]), replay.seen)         # [0] is the rules it has now
        self.assertGreaterEqual(len(replay.seen), 2)
        plan = self.store.load(card["plan_id"])
        for choice in plan["choices"].values():
            self.assertIn("NHL", choice["spec"]["sports"])
        self.assertNotIn("why", card)

    def test_dropping_a_sport_that_is_not_core_is_still_allowed(self):
        """The kept version drops TENNIS (and adds NFL): the hound is not built around tennis, so that is a rebuild like any other."""
        card, _client, _replay = self.run_rebuild(standard_responder(per_angle={"timing": big_spec(4, max_bets_per_day=3)}))
        self.assertTrue(card["found"])
        spec = self.store.load(card["plan_id"])["choices"][card["choice"]]["spec"]
        self.assertIn("NHL", spec["sports"])
        self.assertNotIn("TENNIS", spec["sports"])

    def test_the_analysts_merge_is_a_candidate_too_and_is_never_rehearsed_when_it_drops_the_core(self):
        merge = {"chosen": "merge", "spec_json": json.dumps(big_spec(3, max_bets_per_day=2)), "reasons": ["x"], "cut": [], "added": [], "weak_spots": []}
        card, client, replay = self.run_rebuild(standard_responder(per_angle={"timing": big_spec(4, max_bets_per_day=3)}, analyst=merge))
        self.assertTrue(card["found"])
        self.assertEqual(sum(1 for c in client.calls if stage_of(c) == "analyst"), 1)
        self.assertTrue(all("NHL" in sports for sports in replay.seen[1:]), replay.seen)
        self.assertNotIn(3, [len(self.store.load(card["plan_id"])["choices"][k]["spec"]["rules"]) for k in self.store.load(card["plan_id"])["choices"]])

    def test_the_model_is_told_the_core_as_a_hard_limit(self):
        _card, client, _replay = self.run_rebuild()
        angle = next(c for c in client.calls if stage_of(c) == "angle")
        self.assertIn("CORE (HARD LIMIT): this hound is built around NHL", angle["messages"][0]["content"])
        self.assertIn("MUST still bet it", angle["messages"][0]["content"])
        self.assertIn("CORE", angle["system"])

    def test_a_hound_with_no_core_is_told_nothing_about_one_and_loses_no_candidate(self):
        rusty = self.dog("Rusty Pup Two", sports=["MLB", "NFL"], markets=["moneyline", "spread"], side_rule="underdog")
        rows = rows_for(rusty["id"], [(14, dict(result="LOSS", side="away", price=180)), (4, dict(result="WIN", side="away", price=180)),
                                      (12, dict(result="WIN", side="home", price=110, sport="NFL")), (6, dict(result="LOSS", side="home", price=110, sport="NFL"))])
        client = FakeClient(standard_responder())
        card = plans.full_rebuild(self.resolve(rusty["id"]), self.owner.id, client=client, **self.common(rows=rows))
        self.assertTrue(card["found"])
        self.assertNotIn("CORE (HARD LIMIT)", next(c for c in client.calls if stage_of(c) == "angle")["messages"][0]["content"])

    def test_the_specs_own_core_list_survives_a_rebuild_and_the_model_cannot_set_one(self):
        base = big_spec(2, name="Core Pup", rules=[dict(r, label="") for r in RULE_SET[:2]])      # (a label like "mlb dogs" is blanked by the vet, not valid raw)
        current = user_spec.validate_spec(dict(base, core=["NFL"]))
        kept, why = rebuild_ai.vet_spec(dict(big_spec(3), core=["MLB"]), current)
        self.assertIsNone(why)
        self.assertEqual(kept["core"], ["NFL"])                                  # pinned to the hound's, not the model's
        bare, why = rebuild_ai.vet_spec(dict(big_spec(3), core=["MLB"]), user_spec.validate_spec(base))
        self.assertIsNone(why)
        self.assertNotIn("core", bare)                                           # the model cannot hand a hound an identity

    def test_the_why_lines_in_the_owners_words(self):
        one = plans.rebuild_why([{"spec": None, "refused": "core_dropped", "core_dropped": ["NHL"]}], [], [], days=30)
        self.assertEqual(one["lines"][:2], ["It tried 1 version of the rules.", f"1 version dropped NHL, {CORE_LINE}, so it was set aside."])
        self.assertEqual(one["core_dropped"], 1)
        two = plans.rebuild_why([{"spec": None, "refused": "core_dropped", "core_dropped": ["NHL", "total"]},
                                 {"spec": None, "refused": "core_dropped", "core_dropped": ["NHL"]}], [], [], days=30, analyst_core=["NHL"])
        self.assertEqual(two["core_dropped"], 3)                                 # two angles and the analyst's merge
        self.assertIn(f"3 versions dropped NHL and total, {CORE_LINE}, so they were set aside.", two["lines"])
        none = plans.rebuild_why([{"spec": None, "refused": "too_similar"}], [], [], days=30)
        self.assertEqual((none["core_dropped"], none["core_names"]), (0, []))
        self.assertNotIn(CORE_LINE, " ".join(none["lines"]))

    def test_a_core_drop_has_its_own_bucket(self):
        self.assertEqual(plans.refusal_kind(plans.CORE_REFUSAL), "core_dropped")


class ApplyRechecksTheCore(HockeyBase):
    def saved(self, sports):
        hound = user_store.get_hound(self.hound_row["id"], db=self.db)
        spec = copy.deepcopy(hound["spec"])
        spec["sports"] = sports
        plan = {"kind": plans.KIND_MINOR, "user_id": self.owner.id, "hound_id": hound["id"], "basis": plans._basis(hound),
                "choices": {"main": {"spec": spec, "after": None, "label": "Fine-tune"}}}
        return self.store.save(plan)

    def apply(self, plan_id):
        return plans.apply_plan(self.dog_obj(), self.owner.id, plan_id, now=NOW, rows=self.rows, db=self.db, store=self.store)

    def test_a_plan_saved_before_the_lock_that_drops_nhl_cannot_be_applied(self):
        with self.assertRaises(RiteError) as ctx:
            self.apply(self.saved(["MLB", "TENNIS"]))
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("core_dropped", 422))
        self.assertIn("NHL", str(ctx.exception))
        self.assertIn("HOCKEYCHIEF", str(ctx.exception))
        self.assertUntouched()

    def test_the_same_plan_without_the_core_loss_applies(self):
        out = self.apply(self.saved(["MLB", "NHL"]))
        self.assertEqual(out["new"]["page_href"], f"hound.html?id={out['new']['id']}")
        self.assertEqual(user_store.get_hound(out["new"]["id"], db=self.db)["spec"]["sports"], ["MLB", "NHL"])
