"""Send to training: three speed fixes that must return what the slow code returned (docs/audit/2026-10-29/TRAINING_SPEED.md).

Each group pins EQUALITY of the output before and after on a realistic fixture; none of them pins a time.

  A  BATCH REBUILD   a Full rebuild of an ordinary hound rehearses its surviving candidates in ONE pass (``drill.drill_many``) instead of one
                     drill each. The card, the saved plan and the ``why`` counts are the ones the one-at-a-time rebuild gave; every spec in
                     the batch gets the numbers a drill of it alone gets (its own bets, its own daily limit).
  C  OWN-SPORT SLATE the slate Send to training / Fire now reads is built for the hound's own sports, not all seventeen. The games the hound
                     sees, and so every number built from them, are the same; the cache is keyed on the sport set and is bounded.
  D  CLOSING SCAN    the closing-odds scan tests the event id as TEXT before ``json.loads``. The rows it keeps are the rows it kept; a line the
                     text cannot decide (spaced JSON, an escaped id, no id) is still parsed. The prefilter may only ever over-match.

No FastAPI, no network, no model: fake SDK client, injected rehearsals or fixture boards.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from src.hounds import boards, user_engine, user_engine_v2, user_spec
from src.hounds.interact import ask_eval, common, drill, rebuild_ai, training_plans as plans
from src.hounds.interact.rites import RiteError
from src.hounds.user_facts import FactBook
from src.pipeline import snapshots
from tests._hounds_rites_fixtures import rows_for
from tests._hounds_user_fixtures import BOOKS, board_rows, result_row, spec_dict, utc
from tests.test_training_plans import Base, FakeClient, big_spec, standard_responder, summary
from tests.test_training_plans_core import HockeyBase


# ---------------------------------------------------------------------------------------------------------------
# A  the batch rebuild
# ---------------------------------------------------------------------------------------------------------------

def varied_replay(spec, days, now):
    """A rehearsal fake whose numbers differ per rule set (so the ranking is not a tie), as a pure function of the spec."""
    k = int(user_spec.spec_hash(spec)[:8], 16)
    graded = 18 + k % 30
    return summary(graded, round(((k >> 5) % 1500) / 100.0 - 5.0, 2), wins=graded // 2 + k % 3, days=days)


DISTINCT = {"mix": big_spec(1, max_bets_per_day=2), "price": big_spec(2, max_bets_per_day=3), "situation": big_spec(2, max_bets_per_day=1),
            "cut": big_spec(1, max_bets_per_day=3, stake_units=2.0), "timing": big_spec(3, max_bets_per_day=2),
            "volume": big_spec(3, max_bets_per_day=3, lock_minutes=60)}


def merge_of(spec):
    return {"chosen": "merge", "spec_json": json.dumps(spec), "reasons": ["More rules cover more of the games"], "cut": ["one rule"],
            "added": ["four rules"], "weak_spots": ["the sample is small"]}


class Recorder:
    """The two ways to rehearse, both counting what they were asked: one spec at a time, and a batch that is the same function over the list."""

    def __init__(self, fn=varied_replay):
        self.fn, self.single, self.batches = fn, [], []

    def one(self, spec, days, now):
        self.single.append(user_spec.spec_hash(spec))
        return self.fn(spec, days, now)

    def many(self, specs, days, now):
        self.batches.append([user_spec.spec_hash(sp) for sp in specs])
        return [self.fn(sp, days, now) for sp in specs]


def settle(card, store):
    """The card with its random plan id taken out, and the plan it saved (the choices a later Apply would read)."""
    plan = store.load(card["plan_id"]) if card.get("plan_id") else None
    out = {k: v for k, v in card.items() if k != "plan_id"}
    return out, (None if plan is None else {k: v for k, v in plan.items() if k not in ("plan_id", "saved_at")})


class Rebuilds:
    """Mixin for a ``Base`` case: the same rebuild, once with only a single-spec rehearsal (the old path) and once with a batch rehearsal beside it
    (production's)."""

    def go(self, responder, *, batch: bool, dog=None, rows=None):
        rec = Recorder()
        store = plans.PlanStore(self.dir / ("batch" if batch else "single"))
        over = {"replay_fn": rec.one, "store": store}
        if batch:
            over["replay_many_fn"] = rec.many
        if rows is not None:
            over["rows"] = rows
        card = plans.full_rebuild(dog or self.dog_obj(), self.owner.id, paid=True, client=FakeClient(responder), **self.common(**over))
        return card, store, rec

    def both(self, responder, **kw):
        slow = self.go(responder, batch=False, **kw)
        # the same day's spend must not leak between the two runs: a fresh ledger for the second
        self.ledger_book = type(self.ledger_book)(self.dir / "rebuilds2.jsonl", clock=lambda: self.clock[0])
        fast = self.go(responder, batch=True, **kw)
        return slow, fast

    def assertSameRebuild(self, slow, fast):
        (card_a, store_a, rec_a), (card_b, store_b, rec_b) = slow, fast
        self.assertEqual(settle(card_a, store_a), settle(card_b, store_b))
        # the old path rehearsed [base, c1..cn, (merge)] one by one; the new one rehearses base, then the c's together, then the merge alone
        self.assertEqual(rec_a.batches, [])
        n = len(rec_b.batches[0]) if rec_b.batches else 0
        self.assertEqual(rec_b.single[:1] + (rec_b.batches[0] if rec_b.batches else []) + rec_b.single[1:], rec_a.single)
        return n



class BatchRebuildEqualsOneAtATime(Rebuilds, Base):
    def test_six_distinct_candidates_and_a_merge_give_the_same_card_and_plan(self):
        merge = merge_of(big_spec(4, max_bets_per_day=2, stake_units=0.5))
        slow, fast = self.both(standard_responder(per_angle=DISTINCT, analyst=merge))
        n = self.assertSameRebuild(slow, fast)
        self.assertEqual(n, 6, "all six candidates went through the one pass")
        self.assertEqual(len(fast[2].batches), 1)
        self.assertEqual(len(fast[2].single), 2, "the rules it has now and the analyst's merge are the only single rehearsals left")
        self.assertTrue(fast[0]["found"])
        self.assertTrue(fast[0]["runners_up"])

    def test_the_ranking_the_runners_up_and_the_analysts_pick_are_unchanged(self):
        # the merge repeats the 'cut' candidate: it is not rehearsed again, it is marked the analyst's pick
        merge = merge_of(DISTINCT["cut"])
        slow, fast = self.both(standard_responder(per_angle=DISTINCT, analyst=merge))
        self.assertSameRebuild(slow, fast)
        self.assertEqual(fast[0]["analyst"] is not None, slow[0]["analyst"] is not None)
        self.assertEqual([r["label"] for r in fast[0]["runners_up"]], [r["label"] for r in slow[0]["runners_up"]])
        self.assertEqual(fast[0]["choice"], slow[0]["choice"])
        self.assertEqual(len(fast[2].single), 1, "a merge that repeats a rehearsed candidate costs no second rehearsal")

    def test_a_repeated_angle_is_one_candidate_in_both_paths(self):
        """The standard answers repeat (price, situation and volume are the same rule set): the survivors are de-duplicated before the batch."""
        slow, fast = self.both(standard_responder())
        n = self.assertSameRebuild(slow, fast)
        self.assertLess(n, rebuild_ai.ANGLE_COUNT)
        self.assertEqual(len(set(fast[2].batches[0])), n)

    def test_a_candidate_the_rules_check_threw_away_is_not_in_the_batch_and_the_counts_do_not_change(self):
        bad = dict(DISTINCT["mix"], max_bets_per_day=3)
        bad["rules"] = [dict(DISTINCT["mix"]["rules"][0], price_min=-250)]               # -200 or worse: refused whole
        answers = dict(DISTINCT, mix=bad, cut=copy.deepcopy(DISTINCT["timing"]))
        slow, fast = self.both(standard_responder(per_angle=answers, analyst=merge_of(big_spec(4, max_bets_per_day=2))))
        self.assertSameRebuild(slow, fast)
        self.assertLessEqual(len(fast[2].batches[0]), rebuild_ai.ANGLE_COUNT - 1, "the angle the checks refused is not rehearsed")

    def test_nothing_survives_gives_the_same_why_and_asks_for_no_batch(self):
        refuse = {a[0]: dict(DISTINCT[a[0]], rules=[dict(DISTINCT[a[0]]["rules"][0], price_min=-250)]) for a in rebuild_ai.ANGLES[:rebuild_ai.ANGLE_COUNT]}
        slow, fast = self.both(standard_responder(per_angle=refuse))
        (card_a, _s, rec_a), (card_b, _s2, rec_b) = slow, fast
        self.assertFalse(card_a["found"])
        self.assertEqual(settle(card_a, slow[1]), settle(card_b, fast[1]))
        self.assertEqual(card_a["why"], card_b["why"])
        self.assertEqual(rec_b.batches, [], "no survivor, no batch")
        self.assertEqual(len(rec_b.single), 1)

    def test_a_refused_batch_refuses_the_rebuild_like_a_refused_single_drill(self):
        def busy(*_a):
            raise RiteError("replay_drill_busy", "another drill is running; try again in a moment", 429)

        def attempt(**over):
            ledger = type(self.ledger_book)(self.dir / f"refused_{len(over)}.jsonl", clock=lambda: self.clock[0])
            with self.assertRaises(RiteError) as ctx:
                plans.full_rebuild(self.dog_obj(), self.owner.id, client=FakeClient(standard_responder(per_angle=DISTINCT)),
                                   **self.common(ledger=ledger, **over))
            return ctx.exception.code, ledger.used_today(self.owner.id), len(ledger.rows())
        calls = [0]

        def busy_after_base(spec, days, now):
            calls[0] += 1
            if calls[0] > 1:
                busy()
            return varied_replay(spec, days, now)
        single = attempt(replay_fn=busy_after_base)
        batch = attempt(replay_fn=varied_replay, replay_many_fn=busy)
        self.assertEqual(single, batch)
        self.assertEqual(batch[0], "replay_drill_busy")


class BatchesStayWithinTheMemoryCap(Rebuilds, Base):
    """The rows a pass holds grow with the SPORTS in it (3 sports: 138 MB for one rule set or seven; all 17: 479 MB), so a rebuild whose candidates
    spread over many sports is rehearsed in runs of at most ``REBUILD_BATCH_MAX_SPORTS`` sports. Same candidates, same order, same numbers."""

    def test_rule_sets_over_the_same_few_sports_are_one_run_and_one_pass(self):
        specs = [{"sports": ["MLB", "NHL", "TENNIS"]}, {"sports": ["MLB"]}, {"sports": ["NHL", "TENNIS"]}] * 3
        self.assertEqual(plans.sport_groups(specs), [specs])

    def test_a_run_is_cut_only_when_the_next_rule_set_would_pass_the_cap_and_order_is_kept(self):
        specs = [{"sports": ["A", "B"]}, {"sports": ["B", "C"]}, {"sports": ["D", "E"]}, {"sports": ["A"]}, {"sports": ["F", "G", "H", "I"]}]
        got = plans.sport_groups(specs, cap=4)
        self.assertEqual([len(g) for g in got], [2, 2, 1])                                                # A,B,C | D,E,A | F,G,H,I
        self.assertEqual([s for g in got for s in g], specs, "every rule set, once, in its order")
        for g in got:
            self.assertLessEqual(len({x for s in g for x in s["sports"]}), 4)

    def test_a_rule_set_over_the_cap_alone_is_a_run_of_its_own(self):
        wide = {"sports": [f"S{i}" for i in range(12)]}
        self.assertEqual(plans.sport_groups([{"sports": ["A"]}, wide, {"sports": ["A"]}], cap=8), [[{"sports": ["A"]}], [wide], [{"sports": ["A"]}]])

    def test_it_reads_the_spec_out_of_a_candidate(self):
        cands = [{"spec": {"sports": ["A", "B"]}}, {"spec": {"sports": ["C"]}}]
        self.assertEqual(plans.sport_groups(cands, lambda c: c["spec"], cap=2), [[cands[0]], [cands[1]]])

    def test_a_rebuild_cut_into_several_passes_gives_the_same_card_and_plan(self):
        merge = merge_of(big_spec(4, max_bets_per_day=2, stake_units=0.5))
        responder = standard_responder(per_angle=DISTINCT, analyst=merge)
        slow = self.go(responder, batch=False)
        self.ledger_book = type(self.ledger_book)(self.dir / "rebuilds3.jsonl", clock=lambda: self.clock[0])
        with mock.patch.object(plans, "REBUILD_BATCH_MAX_SPORTS", 1):
            fast = self.go(responder, batch=True)
        self.assertGreater(len(fast[2].batches), 1, "one sport at a time: the rule sets were cut into several passes")
        self.assertEqual(settle(slow[0], slow[1]), settle(fast[0], fast[1]))
        self.assertEqual(rec_all(fast[2]), rec_all(slow[2]))

    def test_a_pass_that_has_used_up_the_budget_is_the_last(self):
        responder = standard_responder(per_angle=DISTINCT)
        with mock.patch.object(plans, "REBUILD_BATCH_MAX_SPORTS", 1), mock.patch.object(plans, "REBUILD_REPLAY_BUDGET_S", -1.0):
            card, _store, rec = self.go(responder, batch=True)
        self.assertEqual(len(rec.batches), 1, "the one-at-a-time loop stops at the budget; so does the loop over passes (after the first)")
        self.assertTrue(card["found"])


def rec_all(rec):
    """Every rule set a Recorder was asked to rehearse, in the order it was asked."""
    return sorted(rec.single + [h for b in rec.batches for h in b])


class BatchRebuildKeepsTheCore(HockeyBase):
    """HOCKEYCHIEF (NHL core): candidates that drop NHL are set aside BEFORE the batch is built; the counts in the no-candidate ``why`` hold."""

    def run_both(self, responder):
        out = []
        for name, batch in (("single", False), ("batch", True)):
            rec = Recorder()
            self.ledger_book = type(self.ledger_book)(self.dir / f"rebuilds_{name}.jsonl", clock=lambda: self.clock[0])
            store = plans.PlanStore(self.dir / name)
            over = {"replay_fn": rec.one, "store": store}
            if batch:
                over["replay_many_fn"] = rec.many
            card = plans.full_rebuild(self.dog_obj(), self.owner.id, paid=True, client=FakeClient(responder), **self.common(**over))
            out.append((card, store, rec))
        return out

    def test_every_candidate_drops_nhl_so_no_batch_and_the_same_why_counts(self):
        (a, sa, ra), (b, sb, rb) = self.run_both(standard_responder())
        self.assertFalse(a["found"])
        self.assertEqual(a["why"], b["why"])
        self.assertEqual((b["why"]["core_dropped"], b["why"]["rehearsed"]), (a["why"]["core_dropped"], 0))
        self.assertEqual(rb.batches, [])
        self.assertEqual(settle(a, sa), settle(b, sb))

    def test_only_the_candidates_that_keep_nhl_are_in_the_batch(self):
        keeps = {"timing": big_spec(4, max_bets_per_day=3), "volume": big_spec(4, max_bets_per_day=2, stake_units=0.5)}
        (a, sa, ra), (b, sb, rb) = self.run_both(standard_responder(per_angle=dict(DISTINCT, **keeps)))
        self.assertTrue(a["found"])
        self.assertEqual(settle(a, sa), settle(b, sb))
        self.assertEqual(len(rb.batches), 1)
        self.assertEqual(len(rb.batches[0]), len(keeps), "the four angles that dropped NHL never reached the rehearsal")


# the real drill: a batch gives each spec what a drill of it alone gives -----------------------------------------------

DAYS = [f"2026-10-{d:02d}" for d in range(12, 19)]                      # the seven completed days before NOW_DRILL
NOW_DRILL = utc("2026-10-19T12:00:00Z")


def fixture_week():
    """Seven slate dates, five MLB games a day, each with an open and a lock board, prices spread from heavy favourites to +180 dogs, and a
    result for every game: enough that the specs below bet different games, hit their daily limits and win and lose differently."""
    rows_by_date, index, results = {}, {}, {}
    pk = 900000
    for d, date in enumerate(DAYS):
        rows = []
        for g in range(5):
            pk += 1
            event = f"evt{d}{g}"
            home, away = f"Home {d}{g}", f"Away {d}{g}"
            start = f"{date}T23:10:00Z"
            dog_price = 105 + 18 * ((d + g) % 5)                      # +105 .. +177
            fav_price = -(dog_price + 20)
            rows += board_rows(f"{date}T19:55:00Z", event_id=event, home=home, away=away, start=start,
                               moneyline=[(b, fav_price + 5, dog_price - 5) for b in BOOKS])
            rows += board_rows(f"{date}T21:05:00Z", event_id=event, home=home, away=away, start=start,
                               moneyline=[(b, fav_price, dog_price) for b in BOOKS])
            index[event] = {"game_pk": str(pk)}
            home_wins = (d * 5 + g) % 3 != 0
            results[str(pk)] = result_row(pk, date, "AWY", "HOM", 2 if home_wins else 6, 5 if home_wins else 3)
        rows_by_date[date] = rows
    return rows_by_date, index, results


def week_specs():
    def v1(**kw):
        return spec_dict(**kw)
    v2 = {"version": 2, "name": "Two Rules", "tagline": "", "max_bets_per_day": 3, "stake_units": 1.0, "lock_minutes": 120, "rank_by": "earliest_lock",
          "rules": [{"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": 100, "price_max": 150, "min_books": 3, "when": None},
                    {"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": -150, "price_max": -110, "min_books": 3, "when": None}]}
    return [v1(max_bets_per_day=2), v1(max_bets_per_day=1), v1(side_rule="favourite", price_min=-190, price_max=-100, max_bets_per_day=3),
            v1(price_min=140, price_max=250, max_bets_per_day=5), v1(sports=["NFL"], markets=["moneyline"]), v2]


class BatchDrillEqualsSingleDrills(unittest.TestCase):
    """THE DRILL UNDER THE BATCH. ``drill.drill_many`` must hand each spec exactly what ``drill.drill`` of it alone hands (``rehearsal=True``, the
    call ``training_plans.default_replay`` makes), including the record, the units, every pick and the day-by-day table."""

    def setUp(self):
        drill.clear_cache()
        self.addCleanup(drill.clear_cache)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_user_v1.jsonl")
        patch = mock.patch.object(user_engine, "ledger_path", lambda p=None: p or self.ledger)
        patch.start()
        self.addCleanup(patch.stop)
        facts = mock.patch("src.hounds.user_facts.FactBook.from_stores", classmethod(lambda cls, date, **k: FactBook()))
        facts.start()
        self.addCleanup(facts.stop)
        self.rows_by_date, self.index, self.results = fixture_week()

    def inject(self):
        return dict(rows_by_date=self.rows_by_date, mlb_results=self.results, nfl_results=lambda d: {}, game_pk_index=self.index)

    def test_each_spec_in_the_batch_gets_what_a_drill_of_it_alone_gets(self):
        specs = week_specs()
        many = drill.drill_many(specs=copy.deepcopy(specs), days=7, now=NOW_DRILL, **self.inject())
        self.assertEqual(len(many), len(specs))
        bets = []
        for spec, got in zip(specs, many):
            one = drill.drill(spec=copy.deepcopy(spec), days=7, now=NOW_DRILL, rehearsal=True, **self.inject())
            for key in got:
                self.assertEqual(got[key], one[key], f"{key} differs for {spec.get('name')} / {spec.get('side_rule')}")
            self.assertEqual(plans.numbers_of(got), plans.numbers_of(one))
            bets.append(got["record"]["bets"])
        self.assertGreater(len(set(bets)), 2, f"the fixture must make the specs bet differently: {bets}")
        self.assertGreater(max(bets), 5)
        self.assertEqual(many[4]["record"]["bets"], 0, "a spec that bets a sport with no games places nothing, in the batch too")

    def test_the_daily_limit_is_each_hounds_own_in_the_batch(self):
        one, three = spec_dict(max_bets_per_day=1), spec_dict(max_bets_per_day=3)
        got = drill.drill_many(specs=[one, three], days=7, now=NOW_DRILL, **self.inject())
        per_day_one = {d["date"]: d["bets"] for d in got[0]["by_day"]}
        per_day_three = {d["date"]: d["bets"] for d in got[1]["by_day"]}
        self.assertTrue(all(n <= 1 for n in per_day_one.values()))
        self.assertTrue(any(n > 1 for n in per_day_three.values()), "the second spec was not held to the first one's limit")

    def test_the_order_in_the_batch_does_not_change_a_specs_numbers(self):
        specs = week_specs()
        forward = drill.drill_many(specs=copy.deepcopy(specs), days=7, now=NOW_DRILL, **self.inject())
        backward = drill.drill_many(specs=copy.deepcopy(specs[::-1]), days=7, now=NOW_DRILL, **self.inject())
        self.assertEqual([plans.numbers_of(s) for s in forward], [plans.numbers_of(s) for s in backward[::-1]])

    def test_the_whole_rebuild_over_real_drills_is_the_same_batched_or_not(self):
        """The production wiring end to end: ``full_rebuild`` with real drills on the fixture week, single against batch."""
        inject = self.inject()

        def one(spec, days, now):
            return drill.drill(spec=dict(spec), days=days, now=NOW_DRILL, rehearsal=True, **inject)

        def many(specs, days, now):
            return drill.drill_many(specs=[dict(sp) for sp in specs], days=days, now=NOW_DRILL, **inject)
        outs = []
        for batch in (False, True):
            case = _RealRebuild("setUp")
            case.setUp()
            self.addCleanup(case.tearDown)
            outs.append(case.rebuild(one, many if batch else None))
        (card_a, plan_a), (card_b, plan_b) = outs
        self.maxDiff = None
        self.assertTrue(card_a["found"], card_a.get("why"))
        self.assertEqual(card_a, card_b)
        self.assertEqual(plan_a, plan_b)


class _RealRebuild(Base):
    """A rebuild over the fixture week with six distinct angle answers; returns the card and the plan with the random id removed."""

    def rebuild(self, one, many):
        self.store = plans.PlanStore(self.dir / ("b" if many else "s"))
        self.hound_row = self.dog("Rusty Pup Twin", sports=["MLB"], markets=["moneyline"], side_rule="underdog", price_min=100, price_max=250)
        self.rows = rows_for(self.hound_row["id"], [(14, dict(result="LOSS", side="away", price=180)), (4, dict(result="WIN", side="away", price=180))])
        with mock.patch.object(common, "now_utc", lambda: NOW_DRILL):
            card = plans.full_rebuild(self.dog_obj(), self.owner.id, paid=True, client=FakeClient(standard_responder(per_angle=_MLB_ANGLES)),
                                      **self.common(replay_fn=one, replay_many_fn=many, now=NOW_DRILL))
        plan = self.store.load(card["plan_id"]) if card.get("plan_id") else None
        own = ("plan_id", "basis", "hound_id", "saved_at")             # what names the hound of THIS case; two cases make two hounds
        card = {k: v for k, v in card.items() if k not in own}
        return card, (None if plan is None else {k: v for k, v in plan.items() if k not in own})


def _mlb(price_min, price_max, side="either", per_day=3, lock=120):
    return {"version": 2, "rules": [{"sports": ["MLB"], "markets": ["moneyline"], "side": side, "price_min": price_min, "price_max": price_max,
                                     "min_books": 3, "when": None}],
            "max_bets_per_day": per_day, "stake_units": 1.0, "lock_minutes": lock, "rank_by": "earliest_lock"}


_MLB_ANGLES = {"mix": _mlb(100, 150), "price": _mlb(140, 250, per_day=2), "situation": _mlb(-150, -105, per_day=2),
               "cut": _mlb(100, 180, per_day=1), "timing": _mlb(110, 250, lock=60), "volume": _mlb(-200, 250, per_day=5)}


# ---------------------------------------------------------------------------------------------------------------
# C  the slate for the hound's own sports
# ---------------------------------------------------------------------------------------------------------------

class SlateCacheIsKeyedOnTheSportSet(unittest.TestCase):
    def setUp(self):
        ask_eval.clear_cache()
        self.addCleanup(ask_eval.clear_cache)
        self.calls = []

        def build(date, sports, **kw):
            self.calls.append((date, sorted(sports), kw.get("with_props")))
            return SimpleNamespace(date=date, sports=sorted(sports))
        patch = mock.patch.object(ask_eval.V2, "build_slate", build)
        patch.start()
        self.addCleanup(patch.stop)

    def everything(self):
        return sorted(user_spec.SPORTS)

    def test_a_hound_that_bets_three_sports_builds_three_not_all_of_them(self):
        slate = ask_eval.default_slate("2026-10-29", False, ("NHL", "TENNIS", "MLB"))
        self.assertEqual(self.calls, [("2026-10-29", ["MLB", "NHL", "TENNIS"], False)])
        self.assertEqual(slate.sports, ["MLB", "NHL", "TENNIS"])
        self.assertLess(len(self.calls[0][1]), len(user_spec.SPORTS))

    def test_the_same_sports_in_any_order_or_case_are_one_cache_entry(self):
        a = ask_eval.default_slate("2026-10-29", False, ["nhl", "mlb"])
        b = ask_eval.default_slate("2026-10-29", False, ("MLB", "NHL", "MLB"))
        self.assertIs(a, b)
        self.assertEqual(len(self.calls), 1)

    def test_a_request_for_some_of_the_sports_of_a_remembered_slate_is_answered_from_it(self):
        wide = ask_eval.default_slate("2026-10-29", False, ("MLB", "NHL", "TENNIS"))
        for narrower in (("MLB",), ("NHL", "TENNIS"), ("TENNIS", "MLB", "NHL")):
            self.assertIs(ask_eval.default_slate("2026-10-29", False, narrower), wide)
        self.assertEqual(len(self.calls), 1, "the variants of a rule that drop a sport cost nothing")

    def test_a_request_no_remembered_slate_covers_goes_wide_once_and_everything_after_reads_that(self):
        narrow = ask_eval.default_slate("2026-10-29", False, ("MLB", "NHL", "TENNIS"))
        wide = ask_eval.default_slate("2026-10-29", False, ("MLB", "NFL"))
        self.assertEqual([c[1] for c in self.calls], [["MLB", "NHL", "TENNIS"], self.everything()], "the second build is the all-sports one")
        self.assertIsNot(narrow, wide)
        for sports in (("MLB", "NFL"), ("NBA",), ("MLB", "NHL", "TENNIS"), ("GRIDIRON", "NCAAF", "MLB"), None):
            self.assertIs(ask_eval.default_slate("2026-10-29", False, sports), wide, sports)
        self.assertEqual(len(self.calls), 2, "at most two builds a minute per date, however many sport sets ask")
        self.assertEqual(len(ask_eval._slates), 1, "the narrow slate the wide one replaced is not kept beside it")                 # noqa: SLF001

    def test_no_sports_means_all_of_them_as_before_and_naming_all_of_them_is_the_same_entry(self):
        a = ask_eval.default_slate("2026-10-29", False)
        b = ask_eval.default_slate("2026-10-29", False, tuple(user_spec.SPORTS))
        c = ask_eval.default_slate("2026-10-29", False, ())
        d = ask_eval.default_slate("2026-10-29", False, ("MLB",))
        self.assertTrue(a is b is c is d)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1], self.everything())

    def test_a_narrow_slate_never_answers_a_request_for_every_sport(self):
        ask_eval.default_slate("2026-10-29", False, ("MLB", "NHL", "TENNIS"))
        everything = ask_eval.default_slate("2026-10-29", False)
        self.assertEqual(everything.sports, self.everything())
        self.assertEqual(len(self.calls), 2)

    def test_another_date_or_props_is_its_own_slate_and_does_not_widen(self):
        ask_eval.default_slate("2026-10-29", False, ("MLB",))
        ask_eval.default_slate("2026-10-30", False, ("NHL",))
        ask_eval.default_slate("2026-10-29", True, ("NHL",))
        self.assertEqual([c[1] for c in self.calls], [["MLB"], ["NHL"], ["NHL"]])

    def test_the_cache_does_not_grow_without_bound(self):
        for i in range(ask_eval.SLATE_CACHE_MAX * 3):
            ask_eval.default_slate(f"2026-11-{i % 28 + 1:02d}", i % 2 == 0, ("MLB", "NHL", "TENNIS"))
        self.assertLessEqual(len(ask_eval._slates), ask_eval.SLATE_CACHE_MAX)           # noqa: SLF001

    def test_a_slate_older_than_the_minute_is_built_again(self):
        ask_eval.default_slate("2026-10-29", False, ("MLB", "NHL", "TENNIS"))
        for key, (stamp, slate) in list(ask_eval._slates.items()):                          # noqa: SLF001
            ask_eval._slates[key] = (stamp - ask_eval.SLATE_TTL_S - 1, slate)               # noqa: SLF001
        ask_eval.default_slate("2026-10-29", False, ("MLB", "NHL", "TENNIS"))
        self.assertEqual([c[1] for c in self.calls], [["MLB", "NHL", "TENNIS"]] * 2, "an expired slate is not a reason to go wide")
        self.assertEqual(len(ask_eval._slates), 1, "the stale entry was replaced, not kept beside the new one")           # noqa: SLF001


def multi_sport_store(path, date="2026-10-20"):
    """A multibook store of one slate date in compact JSON as the writer writes it: MLB (no sport field), NHL, NBA and TENNIS games, two
    captures each, so a hound that bets only MLB and NHL has the other two sports' games sitting in the file."""
    rows = []

    def game(event, sport, home, away, dog, fav, start="23:10:00"):
        for stamp in ("19:55:00", "21:05:00"):
            for book in BOOKS:
                row = {"observed_utc": f"{date}T{stamp}+00:00", "event_id": event, "commence_time": f"{date}T{start}Z", "home_team": home,
                       "away_team": away, "book": book, "book_last_update": f"{date}T{stamp}Z", "home_price": fav, "away_price": dog}
                if sport:
                    row.update(sport=sport, league=f"x_{sport}", league_title=sport.upper())
                rows.append(row)
    game("m1", None, "Seattle Mariners", "Boston Red Sox", 120, -140)
    game("m2", None, "Texas Rangers", "Houston Astros", 150, -180, "23:40:00")
    game("h1", "nhl", "Boston Bruins", "New York Rangers", 135, -155)
    game("h2", "nhl", "Colorado Avalanche", "Vegas Golden Knights", 110, -130, "02:00:00")
    game("b1", "nba", "Boston Celtics", "Miami Heat", 160, -190)
    game("t1", "tennis", "Player A", "Player B", 125, -145)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    return rows


def v2_dog(sports=("MLB", "NHL")):
    spec = user_spec.validate_spec({"version": 2, "name": "Two Sports", "tagline": "", "max_bets_per_day": 3, "stake_units": 1.0, "lock_minutes": 120,
                                    "rank_by": "earliest_lock",
                                    "rules": [{"sports": [s], "markets": ["moneyline"], "side": "either", "price_min": 100, "price_max": 250,
                                               "min_books": 3, "when": None} for s in sports]})
    hound = {"id": "u-two", "spec": spec, "spec_hash": user_spec.spec_hash(spec), "created_at": "2026-01-01T00:00:00Z", "owner_user_id": 7,
             "status": "running", "name": "Two Sports", "tagline": "", "root_id": "u-two"}
    return common.Dog(id="u-two", kind=common.KIND_USER, name="Two Sports", hound=hound, owner_user_id=7, status="running", root_id="u-two")


class OwnSportSlateGivesTheSameAnswer(unittest.TestCase):
    """The hound sees only its own sports' games (``earlier_user`` and ``fire_v2`` filter to them), so a slate built for those sports alone must
    give the identical payload. Run over a real store file through the real readers (one-pass reader for 3+ sports, per-sport readers for 1 or 2)."""

    DATE_NOW = utc("2026-10-20T20:00:00Z")

    def setUp(self):
        ask_eval.clear_cache()
        self.addCleanup(ask_eval.clear_cache)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "odds_multibook.jsonl")
        multi_sport_store(self.path)
        real = user_engine_v2.build_slate

        def build(date, sports, **kw):
            self.built.append(sorted(sports))
            kw.update(facts=FactBook(), game_pk_index={})
            return real(date, sports, **kw)
        self.built = []
        for p in (mock.patch.object(snapshots, "DEFAULT_MULTIBOOK_PATH", self.path), mock.patch.object(ask_eval.V2, "build_slate", build)):
            p.start()
            self.addCleanup(p.stop)

    def compare(self, dog):
        every = lambda date, with_props: ask_eval.default_slate(date, with_props)          # the old call: no sports given, so all of them
        old = ask_eval.earlier_user(dog, now=self.DATE_NOW, slate_for=every)
        ask_eval.clear_cache()
        del self.built[:]
        new = ask_eval.earlier_user(dog, now=self.DATE_NOW)
        return old, new

    def test_earlier_today_is_identical_for_a_two_sport_hound_and_reads_only_its_sports(self):
        dog = v2_dog(("MLB", "NHL"))
        old, new = self.compare(dog)
        self.assertEqual(old, new)
        self.assertGreater(len(new["picks"]), 0, "the fixture must give the hound something to pick")
        self.assertEqual(self.built, [["MLB", "NHL"]])
        self.assertEqual({p["sport"] for p in new["picks"]} - {"MLB", "NHL"}, set())

    def test_identical_for_a_one_sport_and_a_three_sport_hound(self):
        for sports, expect in ((("NHL",), ["NHL"]), (("MLB", "NHL", "TENNIS"), ["MLB", "NHL", "TENNIS"])):
            with self.subTest(sports=sports):
                old, new = self.compare(v2_dog(sports))
                self.assertEqual(old, new)
                self.assertEqual(self.built, [expect])

    def test_a_run_of_rule_variants_with_different_sports_is_two_builds_at_most_and_every_answer_is_the_same(self):
        """Send to training reads the board once per variant of the rule, and the variants bet different sports (drop one, add one). The first
        read builds only the hound's sports; one that adds a sport goes wide once; the rest read what is there."""
        variants = [("MLB", "NHL", "TENNIS"), ("MLB", "NHL"), ("NHL",), ("MLB",), ("MLB", "NHL", "NBA"), ("TENNIS", "NBA"), ("MLB", "NHL", "TENNIS")]
        every = lambda date, with_props: ask_eval.default_slate(date, with_props)
        old = []
        for sports in variants:
            ask_eval.clear_cache()
            old.append(ask_eval.earlier_user(v2_dog(sports), now=self.DATE_NOW, slate_for=every))
        ask_eval.clear_cache()
        del self.built[:]
        new = [ask_eval.earlier_user(v2_dog(sports), now=self.DATE_NOW) for sports in variants]
        self.assertEqual(old, new)
        self.assertEqual(len(self.built), 2, self.built)
        self.assertEqual(self.built[0], ["MLB", "NHL", "TENNIS"])
        self.assertEqual(self.built[1], sorted(user_spec.SPORTS), "the variant that added NBA widened the read once")

    def test_the_games_themselves_are_the_games_of_the_all_sports_slate_in_those_sports(self):
        wide = user_engine_v2.build_slate("2026-10-20", user_spec.SPORTS, with_props=False)            # the builder itself, past the cache
        narrow = user_engine_v2.build_slate("2026-10-20", ("MLB", "NHL", "TENNIS"), with_props=False)
        want = {eid: g for eid, g in wide.games.items() if g.sport in ("MLB", "NHL", "TENNIS")}
        self.assertEqual(sorted(want), sorted(narrow.games))
        for eid, g in want.items():
            n = narrow.games[eid]
            self.assertEqual((n.sport, n.commence, n.home_team, n.away_team), (g.sport, g.commence, g.home_team, g.away_team))
            self.assertEqual({m: sorted(c) for m, c in n.captures.items()}, {m: sorted(c) for m, c in g.captures.items()})
            for market, caps in g.captures.items():
                for stamp, row in caps.items():
                    self.assertEqual(n.captures[market][stamp], row)
        self.assertNotIn("b1", narrow.games)
        self.assertIn("b1", wide.games)

    def test_fire_now_for_a_version_two_hound_is_identical_too(self):
        dog = v2_dog(("MLB", "NHL"))
        now = utc("2026-10-20T20:00:00Z")
        every = lambda date, with_props: ask_eval.default_slate(date, with_props)
        old = ask_eval.fire_v2(dog, now=now, slate_for=every, other_live=lambda _own, _at: None)
        ask_eval.clear_cache()
        del self.built[:]
        new = ask_eval.fire_v2(dog, now=now, other_live=lambda _own, _at: None)
        self.assertEqual(old, new)
        self.assertGreater(len(new["picks"]), 0)
        self.assertTrue(all(b == ["MLB", "NHL"] for b in self.built), self.built)

    def test_a_seam_a_caller_injects_is_called_exactly_as_before(self):
        seen = []

        def seam(date, with_props):
            seen.append((date, with_props))
            return user_engine_v2.build_slate(date, ["MLB", "NHL"], with_props=with_props, facts=FactBook(), game_pk_index={})
        ask_eval.earlier_user(v2_dog(("MLB", "NHL")), now=self.DATE_NOW, slate_for=seam)
        self.assertEqual(seen, [("2026-10-20", False)])

    def test_a_stand_in_for_default_slate_is_still_called_with_two_arguments(self):
        seen = []

        def stand_in(date, with_props):
            seen.append((date, with_props))
            return user_engine_v2.build_slate(date, ["MLB", "NHL"], with_props=with_props, facts=FactBook(), game_pk_index={})
        with mock.patch.object(ask_eval, "default_slate", stand_in):
            ask_eval.earlier_user(v2_dog(("MLB", "NHL")), now=self.DATE_NOW)
        self.assertEqual(seen, [("2026-10-20", False)])


# ---------------------------------------------------------------------------------------------------------------
# D  the closing-odds scan
# ---------------------------------------------------------------------------------------------------------------

class CountingLoads:
    """Wraps ``json.loads`` inside snapshots and counts the calls."""

    def __init__(self):
        self.n = 0
        self.real = json.loads

    def __call__(self, *a, **k):
        self.n += 1
        return self.real(*a, **k)

    def __enter__(self):
        self.patch = mock.patch.object(snapshots.json, "loads", self)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()


def closing_store(path):
    """A store of 300 events, 6 lines each, a few events of interest, and every awkward line shape the scan must still read exactly."""
    lines = []
    wanted = {"w1", "w2", "w3", "w4"}

    def row(event, observed, **extra):
        out = {"observed_utc": observed, "event_id": event, "commence_time": "2026-10-20T23:10:00Z", "home_team": "H", "away_team": "A",
               "book": "fanduel", "book_last_update": observed, "home_price": -140, "away_price": 120}
        out.update(extra)
        return out
    for n in range(300):
        for k, stamp in enumerate(("2026-10-20T18:00:00+00:00", "2026-10-20T19:00:00+00:00", "2026-10-20T20:00:00+00:00",
                                   "2026-10-20T21:00:00+00:00", "2026-10-20T22:00:00+00:00", "2026-10-20T23:30:00+00:00")):
            event = f"e{n:04d}" if n >= 4 else f"w{n + 1}"
            lines.append(json.dumps(row(event, stamp, book=("fanduel", "draftkings", "betmgm")[k % 3]), separators=(",", ":")))
    # spaced JSON (a fixture writer's default), for a wanted and an unwanted event
    lines.append(json.dumps(row("w1", "2026-10-20T20:30:00+00:00", book="caesars")))
    lines.append(json.dumps(row("e0100", "2026-10-20T20:30:00+00:00", book="caesars")))
    # an escaped event id: the text says w1, the row says w1
    lines.append('{"observed_utc":"2026-10-20T20:45:00+00:00","event_id":"w\\u0031","commence_time":"2026-10-20T23:10:00Z","home_team":"H","away_team":"A",'
                 '"book":"pointsbet","home_price":-150,"away_price":130}')
    # no event id at all, a null event id, an unterminated one, a different sport's row for a wanted id, and junk
    lines.append(json.dumps({"observed_utc": "2026-10-20T20:46:00+00:00", "book": "x"}, separators=(",", ":")))
    lines.append(json.dumps(row(None, "2026-10-20T20:47:00+00:00"), separators=(",", ":")))
    lines.append('{"observed_utc":"2026-10-20T20:48:00+00:00","event_id":"w2')
    lines.append(json.dumps(row("w3", "2026-10-20T20:49:00+00:00", sport="nhl"), separators=(",", ":")))
    lines.append("not json at all")
    lines.append("")
    # an id that merely CONTAINS a wanted id, and a wanted id that appears in another field's text
    lines.append(json.dumps(row("w1x", "2026-10-20T20:50:00+00:00"), separators=(",", ":")))
    lines.append(json.dumps(row("e0200", "2026-10-20T20:51:00+00:00", book="w1"), separators=(",", ":")))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return wanted, len(lines)


class ClosingScanTextPrefilter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "odds_multibook.jsonl")
        self.wanted, self.total = closing_store(self.path)

    def old(self, **kw):
        wanted = self.wanted
        return list(snapshots.iter_multibook(self.path, sport=None, keep=lambda r: r.get("event_id") in wanted, **kw))

    def new(self, **kw):
        return list(snapshots.iter_multibook(self.path, sport=None, event_ids=self.wanted, **kw))

    def test_the_rows_kept_are_the_rows_the_parse_then_test_kept(self):
        self.assertEqual(self.new(), self.old())
        self.assertEqual(self.new(since="2026-10-20"), self.old(since="2026-10-20"))
        self.assertGreater(len(self.new()), 20)

    def test_it_agrees_with_the_keep_predicate_given_beside_it(self):
        both = list(snapshots.iter_multibook(self.path, sport=None, event_ids=self.wanted, keep=lambda r: r.get("book") != "caesars"))
        self.assertEqual(both, [r for r in self.old() if r.get("book") != "caesars"])

    def test_the_awkward_lines_are_still_read(self):
        got = self.new()
        books = {r["book"] for r in got}
        self.assertIn("caesars", books, "spaced JSON is parsed, not skipped")
        self.assertIn("pointsbet", books, "an escaped event id is parsed, not skipped")
        self.assertTrue(any(r.get("sport") == "nhl" and r["event_id"] == "w3" for r in got))
        self.assertNotIn("w1x", {r["event_id"] for r in got})
        self.assertNotIn("e0200", {r["event_id"] for r in got}, "a wanted id in another field's text is not the event id")
        self.assertEqual({r["event_id"] for r in got}, self.wanted)

    def test_most_lines_are_never_parsed(self):
        with CountingLoads() as old:
            self.old()
        with CountingLoads() as new:
            self.new()
        self.assertGreaterEqual(old.n, self.total - 2)
        self.assertLess(new.n, 0.2 * old.n, (new.n, old.n))

    def test_an_empty_wanted_set_reads_nothing(self):
        with CountingLoads() as n:
            got = list(snapshots.iter_multibook(self.path, sport=None, event_ids=set()))
        self.assertEqual((got, n.n), ([], 0))

    def test_no_event_ids_given_is_the_old_behaviour(self):
        every = list(snapshots.iter_multibook(self.path, sport=None))
        self.assertEqual(len(every), self.total - 3)                         # all but the blank, junk and cut lines
        self.assertEqual(every, list(snapshots.iter_multibook(self.path, sport=None, event_ids=None)))

    def bets(self):
        def bet(event, side, price, book="fanduel", decision="2026-10-20T21:10:00+00:00"):
            return SimpleNamespace(event_id=event, market_key="h2h", side=side, line=None, decision_utc=decision, price=price, book=book,
                                   checkable=None, verified=None, avg_price=None, avg_books=0)
        return [bet("w1", "home", -140), bet("w2", "away", 120, "draftkings"), bet("w3", "home", -140), bet("w4", "away", 999),
                bet("nowhere", "home", -110), bet(None, "home", -110)]

    def test_the_scan_gives_the_same_index_teams_and_bet_facts_as_before(self):
        real = snapshots.iter_multibook

        def before(path, **kw):                     # what scan called before: no event ids, the keep predicate after the parse
            ids = kw.pop("event_ids", None)
            kw["keep"] = lambda r: r.get("event_id") in ids
            return real(path, **kw)
        new_bets, old_bets = self.bets(), self.bets()
        with CountingLoads() as fast:
            index_new, teams_new = boards.scan(new_bets, self.path, since="2026-10-20")
        with mock.patch.object(snapshots, "iter_multibook", before), CountingLoads() as slow:
            index_old, teams_old = boards.scan(old_bets, self.path, since="2026-10-20")
        self.assertEqual(index_new, index_old)
        self.assertEqual(teams_new, teams_old)
        self.assertEqual([vars(b) for b in new_bets], [vars(b) for b in old_bets])
        self.assertTrue(any(b.checkable for b in new_bets), "the fixture must make some bet checkable")
        self.assertLess(fast.n, 0.2 * slow.n)

    def test_a_scan_with_no_checkable_bet_reads_nothing_and_returns_what_it_returned(self):
        bets = [SimpleNamespace(event_id=None, market_key="h2h", side="home", line=None, decision_utc=None, price=None, book=None,
                                checkable=None, verified=None, avg_price=None, avg_books=0)]
        with CountingLoads() as n:
            index, teams = boards.scan(bets, self.path)
        self.assertEqual((teams, n.n), ({}, 0))
        self.assertEqual(index, boards.clv.pregame_index([]))


if __name__ == "__main__":
    unittest.main()
