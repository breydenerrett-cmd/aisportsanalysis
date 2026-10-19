"""The breeding program (docs/PREREG_BREEDING.md): forward-only selection with shrinkage, the eligibility
threshold, crossover on the grid, the one-step mutation, litter caps, culling (never a control), the kill
switch and the auto-pause, determinism by seed, the hash-chained ledger, the "no eligible parents" path,
the dry run that writes nothing, the route and its mount order, and the family-tree render under node.

Hermetic: every ledger, the breeding switch and the coach switch live in a temp directory."""

from __future__ import annotations

import json
import os
import random
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from src.hounds.breeding import cross, cycle, rules, select
from src.hounds.learning import ledger as L
from src.hounds.learning import proposals, tunables
from tests import _breeding_fixtures as F

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover - the Linux CI image has no FastAPI
    HAS_FASTAPI = False

ROOT = Path(__file__).resolve().parents[1]
PREREG = (ROOT / "docs" / "PREREG_BREEDING.md").read_text(encoding="utf-8")
TUN = tunables.load()
CYCLE = date(2026, 10, 30)          # a cycle date whose seed breeds an accepted baby in the pair fixture


def at(d: date, hours: int = 1):
    return cycle.cycle_start(d) + timedelta(hours=hours)


class Hermetic(unittest.TestCase):
    """A temp root, and the coach switch pointed at a temp file (pause.is_paused reads it)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        coach = self.root / "coach.json"
        coach.write_text('{"enabled": true}', encoding="utf-8")
        self._env = mock.patch.dict(os.environ, {"HOUNDS_COACH_CONFIG": str(coach)})
        self._env.start()
        self.w = F.world(self.root / "w")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def pair_world(self, champ_n=60, chall_n=30):
        F.write_bets(self.w.champion_ledger, "professor_paws", champ_n, clv=0.5)
        F.propose_live(self.w.scope, "c-1", "professor_paws", {"GAP": 0.03, "SHRINK": 0.3})
        F.write_bets(self.w.scope.challenger_bets, "c-1", chall_n, clv=0.8)


def member(mid, hound="professor_paws", n=30, clv=0.5, units=0.1, role="challenger", values=None, gen=0,
           category=None, m=None):
    t = select.Tally(n=n, m=n if m is None else m, clv_sum=clv * (n if m is None else m), units_avg=units * n)
    tun = TUN.get(hound)
    vals = values or (tun.defaults() if tun else {})
    return select.Member(id=mid, hound_id=hound, role=role, version=1, values=vals,
                         category=category or (tun.category if tun else "random"), generation=gen, tally=t)


# ---- the pre-registration -------------------------------------------------------------------------------

class ThePreregistration(unittest.TestCase):
    def test_every_number_in_the_code_is_stated_in_the_prereg(self):
        self.assertIn("2026-10-21", PREREG)
        self.assertEqual(rules.ANCHOR_DATE, date(2026, 10, 21))
        for needle in ("**3** days", "12:00 UTC", "n >= **25**", "(m + 50)", "**top 4**", "below **0.5**",
                       "**one step**", "At most **2** litters", "At most **6** live babies",
                       "at least **4** members", "**bottom 2**", "n >= **40**", "shrunk CLV < **0**",
                       "last **3** birth cycles", "at most 10 per tick", "120 seconds"):
            self.assertIn(needle, PREREG, needle)
        self.assertEqual((rules.CADENCE_DAYS, rules.CYCLE_HOUR_UTC, rules.MIN_SETTLED_FOR_ELIGIBLE,
                          rules.SHRINK_PRIOR_BETS, rules.PARENT_POOL, rules.MUTATION_PROBABILITY,
                          rules.MUTATION_STEPS, rules.MAX_LITTERS_PER_CYCLE, rules.MAX_LIVE_BABIES,
                          rules.CULL_MIN_ELIGIBLE, rules.CULL_BOTTOM, rules.CULL_MIN_SETTLED, rules.CULL_BELOW,
                          rules.PAUSE_AFTER_BAD_CYCLES, rules.MAX_MISSED_ROWS),
                         (3, 12, 25, 50, 4, 0.5, 1, 2, 6, 4, 2, 40, 0.0, 3, 10))
        for cid in rules.CONTROL_IDS:
            self.assertIn(f"`{cid}`", PREREG)

    def test_the_seal_floor_is_the_packs(self):
        from src.hounds.pack import base
        self.assertEqual(select.SEAL_FLOOR, base.SEAL_FLOOR)

    def test_the_kill_switch_ships_enabled_as_a_plain_boolean(self):
        cfg = json.loads((ROOT / "config" / "breeding.json").read_text(encoding="utf-8"))
        self.assertIs(cfg["enabled"], True)

    def test_the_capture_slot_runs_it_after_the_learning_tick_capped_and_never_failing(self):
        text = (ROOT / "scripts" / "capture_slot.sh").read_text(encoding="utf-8")
        line = "timeout 120 python3 -m src.hounds.breeding tick 2>&1 | tail -n 6 | sed 's/^/  /' || true"
        self.assertEqual(text.count("python3 -m src.hounds.breeding"), 1)
        self.assertIn(line, text)
        self.assertLess(text.index("python3 -m src.hounds.learning tick"), text.index(line))


# ---- selection: forward only, shrinkage, eligibility --------------------------------------------------------

class Selection(Hermetic):
    def test_selection_counts_forward_settled_bets_only_and_never_replay(self):
        path = self.root / "led.jsonl"
        F.write_bets(path, "professor_paws", 10, clv=1.0)
        F.write_bets(path, "professor_paws", 50, clv=9.0, segment="replay", tag="r")
        F.write_bets(path, "professor_paws", 4, result="VOID", tag="v")
        F.write_bets(path, "professor_paws", 3, graded=False, tag="p")
        F.write_bets(path, "professor_paws", 5, clv=1.0, start_day=date(2026, 8, 1), tag="s")   # sealed
        t = select.tally(F.breed_rows(cycle.World(self.w.scope, path, path)), by_version=True)
        got = t[("professor_paws", 1)]
        self.assertEqual((got.n, got.m), (10, 10))
        self.assertAlmostEqual(got.clv_sum, 10.0)

    def test_a_replay_graded_row_cannot_settle_a_forward_bet_and_the_newest_grade_wins(self):
        path = self.root / "led.jsonl"
        F.write_bets(path, "professor_paws", 2, clv=1.0, result="LOSS", units=-1.0)
        rows = F.breed_rows(cycle.World(self.w.scope, path, path))
        bet = rows[0]
        from src.ledger.chain import HashChainLedger
        HashChainLedger(path).append({"kind": "hound_graded", "hound_id": "professor_paws", "date": bet["date"],
                                      "event_id": bet["event_id"], "market": "moneyline", "selection": "Home ML",
                                      "segment": "forward", "bet_row_hash": bet["row_hash"], "result": "WIN",
                                      "units_average_price": 0.9, "clv_pts": 2.0})
        t = select.tally(HashChainLedger(path).read(), by_version=True)[("professor_paws", 1)]
        self.assertEqual((t.wins, t.losses), (1, 1))
        self.assertAlmostEqual(t.clv_sum, 3.0)

    def test_versions_are_kept_apart(self):
        path = self.root / "led.jsonl"
        F.write_bets(path, "professor_paws", 7, clv=1.0)
        F.write_bets(path, "professor_paws", 3, clv=-1.0, version=2, tag="v2")
        t = select.tally(F.breed_rows(cycle.World(self.w.scope, path, path)), by_version=True)
        self.assertEqual(t[("professor_paws", 1)].n, 7)
        self.assertEqual(t[("professor_paws", 2)].n, 3)

    def test_shrinkage_toward_zero_by_sample_size(self):
        self.assertAlmostEqual(member("a", n=25, clv=1.2).shrunk, 1.2 * 25 / 75)
        self.assertAlmostEqual(member("a", n=150, clv=1.0).shrunk, 0.75)
        self.assertEqual(member("a", n=30, clv=1.0, m=0).shrunk, 0.0)
        # a small sample with a bigger mean ranks below a big sample with a smaller one
        small, big = member("small", n=25, clv=1.2), member("big", n=200, clv=0.6)
        self.assertEqual([m.id for m in select.rank([small, big])], ["big", "small"])

    def test_eligibility_threshold_is_25_settled_forward_bets(self):
        self.assertFalse(member("a", n=24).eligible)
        self.assertTrue(member("a", n=25).eligible)
        self.assertEqual(select.rank([member("a", n=24, clv=5.0)]), [])

    def test_ties_break_on_units_per_bet_then_id(self):
        a = member("b-id", n=30, clv=0.5, units=0.2)
        b = member("a-id", n=30, clv=0.5, units=0.1)
        c = member("c-id", n=30, clv=0.5, units=0.1)
        self.assertEqual([m.id for m in select.rank([c, b, a])], ["b-id", "a-id", "c-id"])

    def test_members_are_the_tunable_champions_and_their_live_challengers(self):
        self.pair_world()
        F.propose_live(self.w.scope, "c-old", "professor_paws", {"GAP": 0.035}, parent_version=1)
        F.decide(self.w.scope, "c-old", "retired", "harm", "2026-10-02T00:00:00Z")
        ms = cycle.members_of(self.w, L.read_state(self.w.scope), cycle.BreedState())
        ids = {m.id for m in ms}
        self.assertEqual({m.id for m in ms if m.role == "champion"}, set(TUN))
        self.assertIn("c-1", ids)
        self.assertNotIn("c-old", ids)
        self.assertNotIn("coin_flip_collie", ids)


# ---- crossover and mutation ----------------------------------------------------------------------------------

class CrossoverAndMutation(unittest.TestCase):
    def test_crossover_takes_each_knob_from_a_parent_on_the_grid_within_bounds(self):
        for hid, tun in TUN.items():
            rnd = random.Random(hid)
            for i in range(40):
                a = {k: cross.on_grid_value(kn, rnd.randint(0, cross.grid_index(kn, kn.hi)))
                     for k, kn in tun.knobs.items()}
                b = {k: cross.on_grid_value(kn, rnd.randint(0, cross.grid_index(kn, kn.hi)))
                     for k, kn in tun.knobs.items()}
                vals, origin = cross.crossover(tun, a, b, cross.rng_for(f"2026-11-{i % 28 + 1:02d}", hid))
                for k, kn in tun.knobs.items():
                    self.assertIn(vals[k], (a[k], b[k]))
                    self.assertEqual(vals[k], a[k] if origin[k] == "A" else b[k])
                    self.assertTrue(kn.lo - 1e-9 <= vals[k] <= kn.hi + 1e-9)
                    self.assertTrue(kn.on_grid(vals[k]))

    def test_mutation_moves_exactly_one_knob_one_step_and_stays_in_bounds(self):
        for hid, tun in TUN.items():
            for i in range(30):
                rng = cross.rng_for(f"seed-{i}", hid)
                start = {k: (kn.lo if i % 3 == 0 else kn.hi if i % 3 == 1 else kn.default)
                         for k, kn in tun.knobs.items()}
                start = {k: cross.on_grid_value(tun.knobs[k], cross.grid_index(tun.knobs[k], v))
                         for k, v in start.items()}
                out, mut = cross.mutate(tun, start, rng)
                changed = [k for k in out if abs(out[k] - start[k]) > 1e-9]
                self.assertEqual(changed, [mut["knob"]])
                kn = tun.knobs[mut["knob"]]
                self.assertAlmostEqual(abs(out[mut["knob"]] - start[mut["knob"]]), kn.step, places=6)
                self.assertTrue(kn.lo - 1e-9 <= out[mut["knob"]] <= kn.hi + 1e-9 and kn.on_grid(out[mut["knob"]]))

    def test_a_single_parent_always_mutates_and_a_clone_is_forced_to(self):
        tun = TUN["professor_paws"]
        p = member("p", values={"GAP": 0.02, "SHRINK": 0.5})
        for i in range(20):
            baby = cross.make_baby(tun, (p,), cross.rng_for(f"d{i}", "professor_paws"))
            self.assertIsNotNone(baby.mutation)
            self.assertFalse(cross.same(baby.values, p.values))
        twin = member("q", values={"GAP": 0.02, "SHRINK": 0.5})
        for i in range(20):
            baby = cross.make_baby(tun, (p, twin), cross.rng_for(f"d{i}", "professor_paws"))
            self.assertFalse(cross.same(baby.values, p.values))

    def test_mutation_happens_about_half_the_time_on_distinct_parents(self):
        tun = TUN["professor_paws"]
        a, b = member("a", values={"GAP": 0.02, "SHRINK": 0.3}), member("b", values={"GAP": 0.04, "SHRINK": 0.7})
        n = sum(1 for i in range(400)
                if cross.make_baby(tun, (a, b), cross.rng_for(f"x{i}", "professor_paws")).mutation)
        # clones (both knobs from one parent: half the crossovers) are forced, so about 0.5 + 0.5 * 0.5
        self.assertTrue(260 <= n <= 340, n)

    def test_the_same_seed_gives_the_same_baby_and_seeds_differ(self):
        tun = TUN["professor_paws"]
        a, b = member("a", values={"GAP": 0.02, "SHRINK": 0.3}), member("b", values={"GAP": 0.04, "SHRINK": 0.7})
        one = cross.make_baby(tun, (a, b), cross.rng_for("2026-10-21", "professor_paws"))
        two = cross.make_baby(tun, (a, b), cross.rng_for("2026-10-21", "professor_paws"))
        self.assertEqual((one.values, one.origin, one.mutation), (two.values, two.origin, two.mutation))
        seen = {json.dumps(cross.make_baby(tun, (a, b), cross.rng_for(f"2026-10-{d:02d}", "professor_paws")).values,
                           sort_keys=True) for d in range(1, 29)}
        self.assertGreater(len(seen), 1)

    def test_the_hypothesis_passes_the_proposal_text_filter_for_every_tunable_hound(self):
        for hid, tun in TUN.items():
            p = member("p", hound=hid)
            q = member("q", hound=hid)
            for parents, kind in (((p, q), "pair"), ((p,), "single"), ((p,), "replacement")):
                baby = cross.make_baby(tun, parents, cross.rng_for("2026-10-21", hid))
                text = cross.hypothesis(baby, "2026-10-21", 3, kind)
                self.assertEqual(proposals.clean_text(text, "hypothesis", 20, 400), text)
                self.assertEqual(proposals.clean_evidence(cross.evidence(baby, "2026-10-21", p)),
                                 cross.evidence(baby, "2026-10-21", p))

    def test_pairs_stay_within_one_family_one_litter_per_family(self):
        pool = [member("pp-1", "professor_paws"), member("tt-1", "totals_terrier"),
                member("pp-2", "professor_paws"), member("pp-3", "professor_paws")]
        plan = cross.plan(pool)
        self.assertEqual([(lt.hound_id, lt.kind, [p.id for p in lt.parents]) for lt in plan],
                         [("professor_paws", "pair", ["pp-1", "pp-2"]), ("totals_terrier", "single", ["tt-1"])])


# ---- culling ---------------------------------------------------------------------------------------------------

class Culling(unittest.TestCase):
    def test_bottom_two_with_40_bets_and_negative_shrunk_clv(self):
        ranked = select.rank([member("a", clv=1.0, n=50), member("b", clv=0.5, n=50),
                              member("c", clv=-0.2, n=40), member("d", clv=-0.5, n=60)])
        self.assertEqual([m.id for m in select.cull_candidates(ranked)], ["d", "c"])

    def test_thresholds_39_bets_or_a_zero_score_is_not_culled(self):
        ranked = select.rank([member("a", clv=1.0, n=50), member("b", clv=0.5, n=50),
                              member("c", clv=0.0, n=60), member("d", clv=-0.5, n=39)])
        self.assertEqual(select.cull_candidates(ranked), [])

    def test_fewer_than_four_eligible_culls_nobody(self):
        ranked = select.rank([member("a", clv=1.0, n=50), member("c", clv=-2.0, n=60), member("d", clv=-0.5, n=60)])
        self.assertEqual(select.cull_candidates(ranked), [])

    def test_controls_and_fun_dogs_are_never_culled(self):
        ms = [member("a", clv=1.0, n=50), member("b", clv=0.5, n=50)]
        for i, cid in enumerate(rules.CONTROL_IDS):
            ms.append(member(cid, hound=cid, clv=-3.0 - i, n=100, category="random"))
        ms.append(member("odd", hound="kelly_kelpie", clv=-9.0, n=100, category="esoteric"))
        self.assertEqual(select.cull_candidates(select.rank(ms)), [])


# ---- the cycle ------------------------------------------------------------------------------------------------------

class TheCycle(Hermetic):
    def test_cycle_dates_and_the_first_slot_after_noon(self):
        self.assertIsNone(cycle.due_cycle(F.utc("2026-10-21T11:59:00Z")))
        self.assertEqual(cycle.due_cycle(F.utc("2026-10-21T12:00:00Z")), date(2026, 10, 21))
        self.assertEqual(cycle.due_cycle(F.utc("2026-10-23T23:00:00Z")), date(2026, 10, 21))
        self.assertEqual(cycle.due_cycle(F.utc("2026-10-24T11:00:00Z")), date(2026, 10, 21))
        self.assertEqual(cycle.due_cycle(F.utc("2026-10-24T12:30:00Z")), date(2026, 10, 24))
        self.assertEqual(cycle.next_cycle(F.utc("2026-10-19T09:00:00Z")), date(2026, 10, 21))

    def test_no_eligible_parents_logs_one_skipped_row_and_does_nothing(self):
        F.write_bets(self.w.champion_ledger, "professor_paws", 7)
        rep = cycle.tick(self.w, now=at(rules.ANCHOR_DATE))
        self.assertEqual(rep["reason"], "no eligible parents: 7/25 bets")
        rows = F.breed_rows(self.w)
        self.assertEqual([(r["kind"], r["outcome"]) for r in rows], [("cycle", "skipped")])
        self.assertTrue(rows[0]["eligibility"])
        self.assertFalse(Path(self.w.scope.events).exists())
        # a later slot the same day does nothing
        cycle.tick(self.w, now=at(rules.ANCHOR_DATE, 5))
        self.assertEqual(len(F.breed_rows(self.w)), 1)

    def test_nothing_before_the_first_cycle(self):
        rep = cycle.tick(self.w, now=F.utc("2026-10-19T13:00:00Z"))
        self.assertFalse(rep["due"])
        self.assertEqual(F.breed_rows(self.w), [])

    def test_missed_cycle_dates_are_recorded(self):
        cycle.tick(self.w, now=at(date(2026, 10, 30)))
        rows = F.breed_rows(self.w)
        self.assertEqual([(r["cycle_date"], r["outcome"]) for r in rows],
                         [("2026-10-21", "missed"), ("2026-10-24", "missed"), ("2026-10-27", "missed"),
                          ("2026-10-30", "skipped")])

    def test_kill_switch_off_or_unreadable_skips(self):
        off = F.world(self.root / "off", enabled=False)
        F.write_bets(off.champion_ledger, "professor_paws", 60)
        rep = cycle.tick(off, now=at(rules.ANCHOR_DATE))
        self.assertEqual(rep["reason"], "disabled")
        self.assertFalse(cycle.enabled(self.root / "missing.json"))

    def test_a_baby_is_born_through_the_proposal_door_with_both_parents_recorded(self):
        self.pair_world()
        rep = cycle.tick(self.w, now=at(CYCLE))
        self.assertEqual(len(rep["births"]), 1, rep)
        born = [r for r in F.breed_rows(self.w) if r["kind"] == "birth"][0]
        self.assertEqual(sorted(p["ref"] for p in born["parents"]), ["c-1", "professor_paws/v1"])
        self.assertEqual(born["generation"], 1)
        c = L.read_state(self.w.scope).challengers[born["challenger_id"]]
        self.assertEqual((c.proposed_by, c.status, c.kind), ("breeding", "live", "pack"))
        self.assertEqual(c.spec["values"], born["values"])
        for k, kn in TUN["professor_paws"].knobs.items():
            self.assertTrue(kn.on_grid(born["values"][k]))

    def test_the_cycle_is_deterministic_given_the_seed(self):
        outs = []
        for name in ("a", "b"):
            w = F.world(self.root / name)
            F.write_bets(w.champion_ledger, "professor_paws", 60, clv=0.5)
            F.propose_live(w.scope, "c-1", "professor_paws", {"GAP": 0.03, "SHRINK": 0.3})
            F.write_bets(w.scope.challenger_bets, "c-1", 30, clv=0.8)
            cycle.tick(w, now=at(CYCLE))
            outs.append([{k: r[k] for k in ("kind", "values", "origin", "mutation", "challenger_id") if k in r}
                         for r in F.breed_rows(w)])
        self.assertEqual(outs[0], outs[1])

    def test_a_refusal_by_the_guards_is_recorded_not_worked_around(self):
        self.pair_world(champ_n=30)      # champion has 30 graded bets: rule 3.3 needs 50
        rep = cycle.tick(self.w, now=at(CYCLE))
        self.assertEqual(rep["births"], [])
        self.assertEqual({r["code"] for r in rep["refused"]}, {"not_enough_bets"})
        kinds = [r["kind"] for r in F.breed_rows(self.w)]
        self.assertIn("birth_refused", kinds)
        refused = L.read_state(self.w.scope).refusals
        self.assertEqual(refused[-1]["proposed_by"], "breeding")

    def test_at_most_two_attempts_per_cycle(self):
        calls = []

        def fake(scope, hid, params, hyp, ev, **kw):
            calls.append(hid)
            raise proposals.ProposalError("x", "refused in test")
        for hid in ("professor_paws", "totals_terrier", "relief_retriever", "steamy_setter"):
            F.write_bets(self.w.champion_ledger, hid, 30, clv=0.5, tag=hid)
        cycle.tick(self.w, now=at(rules.ANCHOR_DATE), propose=fake)
        self.assertEqual(len(calls), rules.MAX_LITTERS_PER_CYCLE)

    def test_six_live_babies_stop_every_litter(self):
        for i in range(6):
            F.propose_live(self.w.scope, f"b-{i}", "professor_paws", {"GAP": 0.02 + 0.005 * (i % 4)},
                           proposed_by="breeding")
        F.write_bets(self.w.champion_ledger, "totals_terrier", 30, clv=0.5)
        called = []
        rep = cycle.tick(self.w, now=at(rules.ANCHOR_DATE),
                         propose=lambda *a, **k: called.append(1))
        self.assertEqual(called, [])
        self.assertIn("6 live babies", rep["reason"])

    def test_culling_retires_a_challenger_and_proposes_a_replacement_for_a_champion(self):
        F.write_bets(self.w.champion_ledger, "professor_paws", 60, clv=1.0, tag="a")
        F.write_bets(self.w.champion_ledger, "totals_terrier", 60, clv=0.8, tag="b")
        F.write_bets(self.w.champion_ledger, "steamy_setter", 60, clv=-0.5, tag="c")
        F.propose_live(self.w.scope, "c-bad", "professor_paws", {"GAP": 0.035})
        F.write_bets(self.w.scope.challenger_bets, "c-bad", 45, clv=-1.0)
        seen = []

        def fake(scope, hid, params, hyp, ev, **kw):
            seen.append((hid, ev))
            raise proposals.ProposalError("near_duplicate", "test")
        rep = cycle.tick(self.w, now=at(rules.ANCHOR_DATE), propose=fake)
        self.assertEqual(sorted(c["id"] for c in rep["culls"]), ["c-bad", "steamy_setter"])
        st = L.read_state(self.w.scope)
        self.assertEqual((st.challengers["c-bad"].status, st.challengers["c-bad"].outcome_reason),
                         ("retired", "breeding_cull"))
        self.assertTrue(any(r.get("challenger_id") == "c-bad"
                            for r in F.breed_rows(cycle.World(self.w.scope, self.w.scope.lessons,
                                                              self.w.scope.lessons))))
        actions = {r["member"]["id"]: r["action"] for r in F.breed_rows(self.w) if r["kind"] == "cull"}
        self.assertEqual(actions, {"c-bad": "retired", "steamy_setter": "replacement_proposed"})
        # litters: the pool's two families first (2 attempts), so the replacement waits for the cap
        self.assertEqual(len(seen), 2)

    def test_a_member_culled_this_cycle_is_not_a_parent_this_cycle(self):
        """Prereg section 12: with exactly 4 eligible, the culled bottom 2 leave the pool."""
        for hid, clv in (("professor_paws", 1.0), ("totals_terrier", 0.8), ("steamy_setter", -0.5),
                         ("relief_retriever", -0.7)):
            F.write_bets(self.w.champion_ledger, hid, 60, clv=clv, tag=hid)
        seen = []

        def fake(scope, hid, params, hyp, ev, **kw):
            seen.append(ev)
            raise proposals.ProposalError("x", "test")
        rep = cycle.tick(self.w, now=at(rules.ANCHOR_DATE), propose=fake)
        self.assertEqual(rep["pool"], ["professor_paws/v1", "totals_terrier/v1"])
        self.assertEqual(sorted(c["id"] for c in rep["culls"]), ["relief_retriever", "steamy_setter"])
        parents = [r for ev in seen for r in ev if r.startswith("parent:")]
        self.assertEqual(parents, ["parent:professor_paws/v1", "parent:totals_terrier/v1"])
        self.assertIn("## 12. Clarification, 2026-10-19", PREREG)

    def test_auto_pause_after_three_birth_cycles_that_all_ended_badly_then_resume(self):
        log = cycle.BreedLog(self.w.breed_ledger)
        endings = [("retired", "harm"), ("undecided", "expired"), ("retired", "harm")]
        for i, (outcome, reason) in enumerate(endings):
            cid = f"b-{i}"
            F.propose_live(self.w.scope, cid, "professor_paws", {"GAP": 0.03}, proposed_by="breeding")
            log.append(rules.K_BIRTH, now=F.utc("2026-10-21T13:00:00Z"), cycle_date=f"2026-10-2{i}",
                       challenger_id=cid, generation=1, parents=[])
        st = L.read_state(self.w.scope)
        self.assertIsNone(cycle.should_pause(cycle.fold(log.read()), st))     # all three still live
        for i, (outcome, reason) in enumerate(endings[:2]):
            F.decide(self.w.scope, f"b-{i}", outcome, reason, "2027-03-01T00:00:00Z")
        self.assertIsNone(cycle.should_pause(cycle.fold(log.read()), L.read_state(self.w.scope)))
        F.decide(self.w.scope, "b-2", "retired", "breeding_cull", "2027-03-01T00:00:00Z")
        self.assertIsNone(cycle.should_pause(cycle.fold(log.read()), L.read_state(self.w.scope)))

        w2 = F.world(self.root / "w2")
        log2 = cycle.BreedLog(w2.breed_ledger)
        for i, (outcome, reason) in enumerate(endings):
            cid = f"z-{i}"
            F.propose_live(w2.scope, cid, "professor_paws", {"GAP": 0.03}, proposed_by="breeding")
            F.decide(w2.scope, cid, outcome, reason, "2027-03-01T00:00:00Z")
            log2.append(rules.K_BIRTH, now=F.utc("2026-10-21T13:00:00Z"), cycle_date=f"2026-10-2{i}",
                        challenger_id=cid, generation=1, parents=[])
        self.assertIsNotNone(cycle.should_pause(cycle.fold(log2.read()), L.read_state(w2.scope)))
        log2.append(rules.K_PAUSE, now=F.utc("2027-03-01T00:00:00Z"), reason="test")
        F.write_bets(w2.champion_ledger, "professor_paws", 60)
        rep = cycle.tick(w2, now=at(date(2027, 3, 2)))
        self.assertEqual(rep["reason"], "paused")
        self.assertEqual(cycle.resume(w2, "owner says go", now=F.utc("2027-03-03T00:00:00Z"))["already"], False)
        self.assertFalse(cycle.fold(log2.read()).paused)

    def test_the_ledger_is_a_hash_chain_and_append_only(self):
        self.pair_world()
        cycle.tick(self.w, now=at(CYCLE))
        res = cycle.BreedLog(self.w.breed_ledger).verify()
        self.assertTrue(res.ok)
        lines = Path(self.w.breed_ledger).read_text(encoding="utf-8").splitlines()
        tampered = lines[:]
        tampered[0] = tampered[0].replace('"missed"', '"ran"')
        Path(self.w.breed_ledger).write_text("\n".join(tampered) + "\n", encoding="utf-8")
        self.assertFalse(cycle.BreedLog(self.w.breed_ledger).verify().ok)

    def test_a_dry_run_writes_nothing_anywhere(self):
        self.pair_world()
        before = {p: Path(p).read_bytes() for p in (self.w.scope.events, self.w.scope.challenger_bets,
                                                    self.w.champion_ledger)}
        rep = cycle.tick(self.w, now=at(CYCLE), dry_run=True)
        self.assertTrue(rep["dry_run"])
        self.assertEqual(len(rep["births"]), 1)
        self.assertTrue(any(r["kind"] == "birth" for r in rep["would_write"]))
        self.assertFalse(Path(self.w.breed_ledger).exists())
        for p, data in before.items():
            self.assertEqual(Path(p).read_bytes(), data)

    def test_a_dry_run_before_any_cycle_computes_the_next_one(self):
        F.write_bets(self.w.champion_ledger, "professor_paws", 3)
        rep = cycle.tick(self.w, now=F.utc("2026-10-19T15:00:00Z"), dry_run=True)
        self.assertEqual((rep["due"], rep["cycle_date"], rep["reason"]),
                         (False, "2026-10-21", "no eligible parents: 3/25 bets"))
        self.assertFalse(Path(self.w.breed_ledger).exists())

    def test_the_family_tree_payload(self):
        self.pair_world()
        cycle.tick(self.w, now=at(CYCLE))
        tree = cycle.family_tree(self.w, now=at(CYCLE, 2))
        self.assertEqual(tree["next_cycle_date"], "2026-11-02")
        self.assertEqual(len(tree["babies"]), 1)
        baby = tree["babies"][0]
        self.assertEqual((baby["status"], baby["generation"], baby["record"]["settled"]), ("live", 1, 0))
        self.assertEqual([g["generation"] for g in tree["generations"]], [0, 1])
        elig = {e["ref"]: e for e in tree["eligibility"]}
        self.assertEqual((elig["professor_paws/v1"]["settled"], elig["professor_paws/v1"]["need"]), (60, 25))
        self.assertIn(baby["challenger_id"], elig)          # the baby is a member now, at 0/25
        self.assertEqual(elig[baby["challenger_id"]]["settled"], 0)
        json.dumps(tree)

    def test_the_cli_status_and_verify_run_on_a_temp_root(self):
        from src.hounds.breeding import cli
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["--root", str(self.root / "cli"), "--champion-ledger", str(self.root / "none.jsonl"),
                             "--config", str(self.w.config), "--now", "2026-10-21T13:00:00Z", "tick"])
        self.assertEqual(code, 0)
        self.assertIn("no eligible parents: 0/25 bets", buf.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--root", str(self.root / "cli"), "verify"]), 0)


# ---- the route --------------------------------------------------------------------------------------------------

class TheRouteOrder(unittest.TestCase):
    """api/app.py's include order, read as text (FastAPI-free)."""

    def test_breeding_is_mounted_before_the_hounds_catch_all(self):
        text = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("from api.hounds_breeding import router as hounds_breeding_router", text)
        self.assertLess(text.index("app.include_router(hounds_breeding_router)"),
                        text.index("app.include_router(hounds_router)"))

    def test_the_route_file_declares_only_a_get(self):
        text = (ROOT / "api" / "hounds_breeding.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/hounds/breeding")', text)
        self.assertNotRegex(text, r"@router\.(post|put|delete|patch)")


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoute(Hermetic):
    def test_get_breeding_is_the_tree_and_not_a_hound_called_breeding(self):
        from fastapi.testclient import TestClient
        from api.app import app
        import api.hounds_breeding as route
        self.pair_world()
        cycle.tick(self.w, now=at(CYCLE))
        route._MEMO.clear()
        with mock.patch.object(cycle.World, "default", staticmethod(lambda: self.w)):
            res = TestClient(app).get("/hounds/breeding")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIn("eligibility", body)
        self.assertEqual(len(body["babies"]), 1)
        self.assertEqual(res.headers["cache-control"], "public, max-age=60")
        route._MEMO.clear()


# ---- the render module under node -------------------------------------------------------------------------------

from tests.hounds_web_runner import HAS_NODE, run_js  # noqa: E402


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRender(Hermetic):
    def payload(self):
        self.pair_world()
        cycle.tick(self.w, now=at(CYCLE))
        tree = cycle.family_tree(self.w, now=at(CYCLE, 2))
        tree["refusals"].append({"cycle_date": "2026-10-30", "hound_id": "totals_terrier", "litter": "single",
                                 "code": "near_duplicate", "message": "<script>alert(1)</script>", "parents": ["x"]})
        return json.loads(json.dumps(tree))

    def test_render_generations_links_chips_countdown_and_bars(self):
        tree = self.payload()
        now_ms = int(at(CYCLE, 2).timestamp() * 1000)
        src = (
            'import { renderBreeding, breedingHtml, countdownText, statusChip } from "./breeding.js";\n'
            f"const payload = {json.dumps(tree)};\n"
            "const box = { innerHTML: '' };\n"
            f"const got = await renderBreeding(box, {{ get: async (u) => {{ if (u !== '/hounds/breeding') throw 1; "
            f"return payload; }}, now: () => {now_ms}, timer: false }});\n"
            "const failed = { innerHTML: '' };\n"
            "await renderBreeding(failed, { get: async () => { throw new Error('down'); }, timer: false });\n"
            "console.log(JSON.stringify({ html: box.innerHTML, ok: got === payload, failed: failed.innerHTML,\n"
            f"  cd: countdownText(payload.next_cycle_utc, {now_ms}), past: countdownText(payload.next_cycle_utc, 9e15),\n"
            "  chips: [statusChip('live'), statusChip('retired','harm'), statusChip('undecided','expired'),\n"
            "          statusChip('retired','breeding_cull'), statusChip('promoted')].map(c => c.label) }));\n")
        out = run_js(src)
        html = out["html"]
        self.assertTrue(out["ok"])
        self.assertIn("Breeding program", html)
        self.assertEqual(len(re.findall(r'data-hook="brd-gen"', html)), 2)
        baby = tree["babies"][0]
        self.assertIn(f'data-id="{baby["challenger_id"]}"', html)
        self.assertIn("parents: c-1 + professor_paws/v1 &rarr; born 2026-10-30", html)
        self.assertIn("IN SHADOW", html)
        self.assertIn("60/25 bets", html)
        self.assertIn("0/25 bets", html)
        self.assertIn('role="progressbar"', html)
        self.assertIn("Next cycle in 2d 22h 0m", html)
        self.assertEqual(out["cd"], "2d 22h 0m")
        self.assertEqual(out["past"], "due at the next capture slot")
        self.assertEqual(out["chips"], ["IN SHADOW", "HURT", "TOO EARLY", "CULLED", "PROMOTED"])
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Not advice", html)
        self.assertIn("could not be read right now", out["failed"])

    def test_the_empty_state_says_what_happens_until_25_bets(self):
        src = ('import { breedingHtml } from "./breeding.js";\n'
               "console.log(JSON.stringify(breedingHtml({enabled: true, paused: false, babies: [], generations: "
               "[{generation: 0, members: ['professor_paws/v1']}], eligibility: [{ref: 'professor_paws/v1', "
               "name: 'Professor Paws', role: 'champion', settled: 7, need: 25, eligible: false}], culls: [], "
               "cycles: [{cycle_date: '2026-10-21', outcome: 'skipped', reason: 'no eligible parents: 7/25 bets'}], "
               "next_cycle_utc: '2026-10-24T12:00:00Z'}, Date.parse('2026-10-21T13:00:00Z'))));\n")
        html = run_js(src)
        self.assertIn("No babies yet", html)
        self.assertIn("7/25 bets", html)
        self.assertIn("no eligible parents: 7/25 bets", html)
        self.assertIn("Nobody has been culled", html)


if __name__ == "__main__":
    unittest.main()
