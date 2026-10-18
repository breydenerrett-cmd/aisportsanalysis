"""The referee: the only thing in the loop that can promote or retire a challenger.

It reads ledgers and writes events. It takes no instruction from any text a model wrote (a hypothesis
is copied into a lesson, never read for meaning), and nothing a proposal carries can reach it except a
spec that already passed the menu. Pre-registered in docs/PREREG_LEARNING_LOOP.md sections 5 to 8; the
numbers are in ``rules``.

ONE RUN, IN ORDER
-----------------
 1. Repair: finish any promotion that was written but not applied (a crash between the event and the
    user store), and write any lesson an ended challenger lacks.
 2. For each live challenger: close it as SUPERSEDED if its champion changed; build its pairing
    (``pairing.build``); evaluate every look it has newly reached, in order, each over exactly the
    first n_k slots (so the answer never depends on when the referee ran); record a ``look`` event;
    RETIRE it at the harm boundary or at "no win at 300"; EXPIRE it after 180 days with too few slots.
 3. For each calendar month that has ended and has not been batched: the Benjamini-Hochberg batch
    over every challenger examined that month (prereg section 7), then the caps, then promotion.
    Skipped entirely while the loop is paused (nothing is lost: the month is batched when it resumes).
 4. Write the lessons.

PROMOTION IS AN EVENT, THEN AN EFFECT. The ``promotion`` event is written first (``applied`` false for
a user hound, whose effect is a new version in the app database), then the effect, then
``promotion_applied``. A run that dies in between is finished by step 1 of the next run; the effect is
idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from src.hounds.learning import ledger as L
from src.hounds.learning import lessons, pairing, pause, rules, sequential as seq


class Referee:
    def __init__(self, scope: L.Scope, *, now: Optional[datetime] = None,
                 bets_for: Optional[Callable] = None, pairing_for: Optional[Callable] = None,
                 champion_current: Optional[Callable] = None,
                 apply_user_promotion: Optional[Callable] = None, paused: Optional[bool] = None,
                 kinds: tuple = ("pack", "user", "analyst")):
        """``bets_for(challenger)`` -> ``(champion_bets, challenger_bets)`` with closing-line values
        attached (``measure.BetSource.bets_for``); the pairing is built from them. An analyst prompt
        challenger has no bets: its caller passes ``pairing_for(challenger, state)`` -> a
        ``pairing.Pairing`` of per-game differences instead. ``champion_current(challenger, state)`` says whether
        the challenger's champion is still the version it was born under (default: the pack's version
        number; the user scope passes the app database's answer). ``apply_user_promotion(challenger,
        promotion_event)`` makes the user-store version and returns its new hound id."""
        self.scope = scope
        self.now = now or L.utc_now()
        self.bets_for = bets_for
        self.pairing_for = pairing_for
        self.champion_current = champion_current
        self.apply_user_promotion = apply_user_promotion
        self.kinds = tuple(kinds)       # which challengers THIS run examines; the monthly batch sees all
        self.paused = pause.is_paused(scope) if paused is None else paused
        self.log = L.log_for(scope)
        self.report = {"scope": scope.name, "looks": 0, "retired": 0, "promoted": 0, "undecided": 0,
                       "batches": [], "repaired": 0, "paused": self.paused}

    # ---- plumbing ----------------------------------------------------------------------------

    def _state(self) -> L.State:
        return L.read_state(self.scope)

    def _decide(self, c: L.Challenger, outcome: str, reason: str, *, look: Optional[dict] = None,
                bh: Optional[dict] = None, detail: str = "") -> dict:
        ev = self.log.append(L.K_DECISION, now=self.now, scope=self.scope.name, challenger_id=c.id,
                             hound_id=c.hound_id, outcome=outcome, reason=reason, detail=detail,
                             look_no=(look or {}).get("look_no"), bh=bh)
        key = {rules.OUTCOME_PROMOTED: "promoted", rules.OUTCOME_RETIRED: "retired",
               rules.OUTCOME_UNDECIDED: "undecided"}[outcome]
        self.report[key] += 1
        return ev

    def _lesson(self, c_id: str) -> None:
        st = self._state()
        c = st.challengers[c_id]
        if c.decision:
            lessons.write(self.scope, c, c.decision, lessons.best_look(c), now=self.now)

    def _close(self, c: L.Challenger, outcome: str, reason: str, **kw) -> None:
        self._decide(c, outcome, reason, **kw)
        self._lesson(c.id)

    # ---- step 1: repair -------------------------------------------------------------------------

    def _repair(self) -> None:
        st = self._state()
        for promo in st.unapplied_promotions():
            if promo.get("kind_of") != "user" or self.apply_user_promotion is None:
                continue
            c = st.challengers.get(promo.get("challenger_id"))
            if c is None:
                continue
            new_id = self.apply_user_promotion(c, promo)
            self.log.append(L.K_APPLIED, now=self.now, scope=self.scope.name,
                            challenger_id=c.id, new_hound_id=new_id)
            self.report["repaired"] += 1
        self.report["repaired"] += lessons.ensure(self.scope, self._state(), now=self.now)

    # ---- step 2: examine each live challenger --------------------------------------------------

    def _is_current(self, c: L.Challenger, st: L.State) -> bool:
        if self.champion_current is not None:
            return bool(self.champion_current(c, st))
        if c.kind in ("pack", "analyst"):
            return st.champion_version(c.hound_id) == c.parent_version
        return True

    def _pairing(self, c: L.Challenger, st: L.State) -> pairing.Pairing:
        if self.pairing_for is not None:
            made = self.pairing_for(c, st)
            if made is not None:
                return made
        champ_bets, chall_bets = self.bets_for(c)
        return pairing.build(champ_bets, chall_bets, since=L.parse(c.created_utc), as_of=self.now,
                             covered=st.coverage.get(c.id, set()))

    def _look_event(self, c, k, res, pr, vol, ok) -> dict:
        n = res.n_target
        sample = pr.slots[:n]
        return self.log.append(
            L.K_LOOK, now=self.now, scope=self.scope.name, challenger_id=c.id, hound_id=c.hound_id,
            look_no=k, look_date=sample[-1].date, month=sample[-1].date[:7],
            volume=vol, volume_ok=ok, excluded=pr.excluded, uncovered=pr.uncovered,
            pending=pr.pending, alpha=res.alpha, lower=res.lower, upper=res.upper,
            eligible=bool(res.crossed_better and ok), harm=bool(res.crossed_worse),
            champion_mean=_mean([s.champ for s in sample if s.champ is not None]),
            challenger_mean=_mean([s.chall for s in sample if s.chall is not None]),
            **res.stats.to_json())

    def _examine(self, c: L.Challenger) -> None:
        st = self._state()
        c = st.challengers[c.id]
        if not c.live:
            return
        if not self._is_current(c, st):
            self._close(c, rules.OUTCOME_UNDECIDED, "superseded")
            return
        pr = self._pairing(c, st)
        analyst = c.kind == "analyst"
        sizes = seq.look_sizes(analyst)
        done = {lk["look_no"] for lk in c.looks}
        for k in range(1, len(sizes) + 1):
            n = sizes[k - 1]
            if k in done:
                continue
            if len(pr.slots) < n:
                break
            if pr.dates_in(n) < rules.MIN_DATES_PER_LOOK:
                self.log.append(L.K_LOOK, now=self.now, scope=self.scope.name, challenger_id=c.id,
                                hound_id=c.hound_id, look_no=k, skipped="too_few_dates",
                                dates=pr.dates_in(n), n=n, eligible=False, harm=False,
                                look_date=pr.slots[n - 1].date, month=pr.slots[n - 1].date[:7])
                continue
            res = seq.evaluate_look(k, [(s.date, s.diff) for s in pr.slots[:n]], analyst=analyst)
            vol = pr.volume(n)
            ok = pairing.volume_ok_for(c.kind, vol)
            ev = self._look_event(c, k, res, pr, vol, ok)
            self.report["looks"] += 1
            c = self._state().challengers[c.id]
            if res.crossed_worse:
                self._close(c, rules.OUTCOME_RETIRED, "harm", look=ev,
                            detail=f"upper bound {res.upper:+.2f} is below zero")
                return
            if k == len(sizes) and not ev["eligible"]:
                self._close(c, rules.OUTCOME_RETIRED, "no_win_at_300", look=ev)
                return
        created = L.parse(c.created_utc)
        if len(pr.slots) < sizes[0] and self.now - created >= timedelta(days=rules.EXPIRY_DAYS):
            self._close(c, rules.OUTCOME_UNDECIDED, "expired")

    # ---- step 3: the monthly batch ----------------------------------------------------------------

    @staticmethod
    def _real_looks(c: L.Challenger) -> list:
        return [lk for lk in c.looks if not lk.get("skipped")]

    def _rep_look(self, c: L.Challenger, month: str) -> Optional[dict]:
        here = [lk for lk in self._real_looks(c) if lk.get("month") == month]
        if here:
            hit = [lk for lk in here if lk.get("eligible")]
            return hit[0] if hit else here[-1]
        elig = [lk for lk in self._real_looks(c) if lk.get("eligible")]
        return elig[-1] if elig else None

    def _months_to_batch(self, st: L.State) -> list:
        current = L.month_of(L.iso(self.now))
        months = set()
        for c in st.live():
            months.update(lk["month"] for lk in self._real_looks(c) if lk.get("month"))
        # A challenger the caps held back is "reconsidered next batch" (prereg section 7, rule 4): the
        # month after a batch that carried anyone is batched too, even if no look fell in it.
        for month, batch in st.batches.items():
            if batch.get("carried"):
                months.add(_next_month(month))
        return sorted(m for m in months if m < current and m not in st.batches)

    def _carried_before(self, st: L.State, month: str) -> set:
        prior = [m for m in st.batches if m < month]
        return set(st.batches[max(prior)].get("carried") or []) if prior else set()

    def _batch(self, month: str) -> None:
        st = self._state()
        carried_in = self._carried_before(st, month)
        family = {}
        for c in st.live():
            has_here = any(lk.get("month") == month for lk in self._real_looks(c))
            if not has_here and c.id not in carried_in:
                continue
            rep = self._rep_look(c, month)
            if rep is None:
                continue
            p = seq.adjusted_p(rep.get("p_better"))
            family[c.id] = {"p_adj": 1.0 if p is None else p, "look_no": rep["look_no"],
                            "p_better": rep.get("p_better"), "eligible": bool(rep.get("eligible")),
                            "n": rep.get("n"), "mean": rep.get("mean")}
        if not family:
            return
        rejected = seq.benjamini_hochberg({cid: f["p_adj"] for cid, f in family.items()}, rules.BH_Q)
        promoted, carried, retired = [], [], []
        order = sorted(family, key=lambda cid: (family[cid]["p_adj"], cid))
        month_now = L.month_of(L.iso(self.now))
        for cid in order:
            st = self._state()
            c = st.challengers[cid]
            f = family[cid]
            if not c.live:
                continue
            bh = {"month": month, "q": rules.BH_Q, "m": len(family), "p_adj": f["p_adj"],
                  "rejected": cid in rejected, "look_no": f["look_no"]}
            if cid in rejected and f["eligible"]:
                last = st.last_promotion_utc(c.lineage_key)
                if last is not None and self.now - last < timedelta(days=rules.PROMOTION_COOLDOWN_DAYS):
                    carried.append(cid)
                    continue
                if st.promotions_in_month(month_now) >= rules.MAX_PROMOTIONS_PER_MONTH:
                    carried.append(cid)
                    continue
                self._promote(c, f, bh)
                promoted.append(cid)
            elif f["eligible"] and f["look_no"] == len(seq.look_sizes(c.kind == "analyst")):
                self._close(c, rules.OUTCOME_RETIRED, "bh_failed_at_300", bh=bh,
                            look=next((lk for lk in c.looks if lk.get("look_no") == f["look_no"]), None))
                retired.append(cid)
        self.log.append(L.K_BATCH, now=self.now, scope=self.scope.name, month=month, q=rules.BH_Q,
                        family=family, rejected=rejected, promoted=promoted, carried=carried,
                        retired=retired)
        self.report["batches"].append({"month": month, "family": len(family), "rejected": rejected,
                                       "promoted": promoted, "carried": carried})

    def _promote(self, c: L.Challenger, f: dict, bh: dict) -> None:
        st = self._state()
        look = next((lk for lk in c.looks if lk.get("look_no") == f["look_no"]), None)
        from_version = c.parent_version
        to_version = from_version + 1
        promo = {
            "scope": self.scope.name, "challenger_id": c.id, "hound_id": c.hound_id,
            "lineage_key": c.lineage_key, "kind_of": c.kind, "from_version": from_version,
            "to_version": to_version, "p_adj": f["p_adj"], "look_no": f["look_no"],
            "n_paired": (look or {}).get("n"), "challenger_mean": (look or {}).get("challenger_mean"),
            "replaced_mean": (look or {}).get("champion_mean"), "effective_utc": L.iso(self.now),
            "parent_ref": c.parent_ref,
        }
        if c.kind == "pack":
            promo["params"] = dict(c.spec.get("values") or {})
            promo["applied"] = True
        elif c.kind == "analyst":
            promo["prompt"] = dict(c.spec)
            promo["applied"] = True
        else:
            promo["spec"] = dict(c.spec)
            promo["applied"] = False
        self.log.append(L.K_PROMOTION, now=self.now, **promo)
        self._decide(c, rules.OUTCOME_PROMOTED, "boundary_and_bh", look=look, bh=bh,
                     detail=f"promoted to version {to_version}")
        if c.kind == "user" and self.apply_user_promotion is not None:
            event = [p for p in self._state().promotions if p["challenger_id"] == c.id][-1]
            new_id = self.apply_user_promotion(c, event)
            self.log.append(L.K_APPLIED, now=self.now, scope=self.scope.name, challenger_id=c.id,
                            new_hound_id=new_id)
        self._lesson(c.id)
        for other in self._state().live():
            if other.lineage_key == c.lineage_key and other.id != c.id and other.kind == c.kind:
                self._close(other, rules.OUTCOME_UNDECIDED, "superseded")

    # ---- the run ------------------------------------------------------------------------------------

    def run(self) -> dict:
        self._repair()
        for c in list(self._state().live()):
            if c.kind in self.kinds:
                self._examine(c)
        if not self.paused:
            for month in self._months_to_batch(self._state()):
                self._batch(month)
        self.report["live"] = len(self._state().live())
        return self.report


def _next_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    return f"{year + (mon // 12):04d}-{(mon % 12) + 1:02d}"


def _mean(values) -> Optional[float]:
    values = list(values)
    return round(sum(values) / len(values), 4) if values else None
