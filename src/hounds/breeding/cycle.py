"""One breeding cycle, the breeding ledger, the auto-pause and the family tree (docs/PREREG_BREEDING.md).

ONE TICK, IN ORDER
------------------
 1. Record any cycle date that passed with no row and whose successor has begun (``missed``).
 2. Find the due cycle: the newest cycle date whose 12:00 UTC has passed. If it has a row, do nothing.
 3. Switched off (config/breeding.json) or paused: one ``skipped`` row, nothing else.
 4. Build the members and their forward fitness; nobody eligible: one ``skipped`` row
    ("no eligible parents: n/25 bets"), nothing else.
 5. Culls (bottom 2, at least 40 settled, shrunk CLV below 0, at least 4 eligible, never a control): a
    live challenger is retired through a ``decision`` event of the house learning ledger; a champion is
    never retired here, it gets a replacement litter instead.
 6. Litters, at most 2 attempts and 6 live babies: each baby goes through ``proposals.propose_pack``
    (every guard applies); a refusal is recorded, never worked around.
 7. The ``cycle`` row, then the auto-pause rule.

DRY RUN. ``tick(dry_run=True)`` computes the due cycle (or the next one) on the real ledgers, runs the
proposal door and the cull against a TEMPORARY COPY of the house learning ledgers, collects the rows it
would append, and writes nothing anywhere.

The world (ledgers, config, clock) comes in through ``World`` so a test builds one over a temp directory.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.hounds.breeding import cross, rules, select
from src.hounds.learning import ledger as L
from src.hounds.learning import rules as LR
from src.ledger.chain import HashChainLedger

CONFIG_ENV = "HOUNDS_BREEDING_CONFIG"


# ---- paths and switches ------------------------------------------------------------------------------

def config_path() -> Path:
    override = (os.environ.get(CONFIG_ENV) or "").strip()
    if override:
        return Path(override)
    from src import paths
    return Path(paths.repo_root()) / "config" / "breeding.json"


def ledger_path() -> Path:
    from src.paths import evidence_path
    return Path(evidence_path(rules.LEDGER_FILE))


def enabled(path: Optional[Path] = None) -> bool:
    """The owner's kill switch. Unreadable or missing is OFF (a broken flag never breeds)."""
    try:
        data = json.loads(Path(path or config_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("enabled") is True


# ---- cycle dates -----------------------------------------------------------------------------------------

def cycle_start(d: date) -> datetime:
    return datetime.combine(d, time(rules.CYCLE_HOUR_UTC, 0), tzinfo=timezone.utc)


def due_cycle(now: datetime) -> Optional[date]:
    """The newest cycle date whose 12:00 UTC is at or before ``now`` (None before the first)."""
    if now < cycle_start(rules.ANCHOR_DATE):
        return None
    days = (now.astimezone(timezone.utc).date() - rules.ANCHOR_DATE).days
    d = rules.ANCHOR_DATE + timedelta(days=days - days % rules.CADENCE_DAYS)
    if cycle_start(d) > now:
        d -= timedelta(days=rules.CADENCE_DAYS)
    return d


def next_cycle(now: datetime) -> date:
    d = due_cycle(now)
    return rules.ANCHOR_DATE if d is None else d + timedelta(days=rules.CADENCE_DAYS)


# ---- the breeding ledger ----------------------------------------------------------------------------------

class BreedLog:
    """The hash-chained breeding ledger, or (``dry``) a list that only collects what would be written."""

    def __init__(self, path, *, dry: bool = False):
        self.path = Path(path)
        self.dry = dry
        self._chain = HashChainLedger(self.path)
        self.pending: list = []

    def read(self) -> list:
        return self._chain.read() + list(self.pending)

    def append(self, kind: str, *, now: datetime, **fields) -> dict:
        row = {"kind": kind, "ledger_version": rules.LEDGER_VERSION, "utc": L.iso(now), "paper_only": True}
        row.update(fields)
        if self.dry:
            self.pending.append(row)
            return row
        return self._chain.append(row)

    def verify(self):
        return self._chain.verify()


@dataclass
class BreedState:
    cycles: dict = field(default_factory=dict)        # cycle date -> cycle row
    births: list = field(default_factory=list)
    refusals: list = field(default_factory=list)
    culls: list = field(default_factory=list)
    pauses: list = field(default_factory=list)

    @property
    def paused(self) -> bool:
        return bool(self.pauses) and self.pauses[-1]["kind"] == rules.K_PAUSE

    def generations(self) -> dict:
        return {b["challenger_id"]: int(b.get("generation") or 0) for b in self.births}


def fold(rows) -> BreedState:
    st = BreedState()
    for r in rows:
        k = r.get("kind")
        if k == rules.K_CYCLE:
            st.cycles.setdefault(str(r.get("cycle_date")), dict(r))
        elif k == rules.K_BIRTH:
            st.births.append(dict(r))
        elif k == rules.K_REFUSED:
            st.refusals.append(dict(r))
        elif k == rules.K_CULL:
            st.culls.append(dict(r))
        elif k in (rules.K_PAUSE, rules.K_RESUME):
            st.pauses.append(dict(r))
    return st


# ---- the world ---------------------------------------------------------------------------------------------

@dataclass
class World:
    scope: L.Scope                              # the house learning scope (its ledgers)
    champion_ledger: Path                       # evidence/hounds_house_v1.jsonl
    breed_ledger: Path
    config: Optional[Path] = None
    tun_cfg: Optional[Mapping] = None           # tunables.load() by default
    names: Optional[Mapping] = None

    @staticmethod
    def default() -> "World":
        from src.hounds import pack_run
        return World(scope=L.Scope.house(), champion_ledger=Path(pack_run.ledger_path()),
                     breed_ledger=ledger_path(), config=config_path())

    def tunables(self) -> dict:
        if self.tun_cfg is None:
            from src.hounds.learning import tunables
            self.tun_cfg = tunables.load()
        return dict(self.tun_cfg)


def _rows(path) -> list:
    p = Path(path)
    return HashChainLedger(p).read() if p.exists() else []


def members_of(world: World, state: L.State, breed: BreedState) -> list:
    champ = select.tally(_rows(world.champion_ledger), by_version=True)
    chall = select.tally(_rows(world.scope.challenger_bets), by_version=False)
    return select.build_members(world.tunables(), state, champ, chall,
                                generations=breed.generations(), names=world.names)


def graded_count(world: World, hound_id: str, version: int) -> int:
    """What the proposal door's 50-bet guard counts: forward graded bets of the champion version."""
    from src.hounds.learning import proposals
    if not Path(world.champion_ledger).exists():
        return 0
    return proposals.pack_graded_count(hound_id, version, world.champion_ledger)


def live_babies(state: L.State) -> list:
    return [c for c in state.live() if c.proposed_by == rules.PROPOSED_BY]


# ---- culling ------------------------------------------------------------------------------------------------

def retire_challenger(scope: L.Scope, member: select.Member, *, now: datetime, cycle_date: str) -> None:
    """The cull of a live challenger: a ``decision`` event (retired, ``breeding_cull``) and its lesson."""
    from src.hounds.learning import lessons
    L.log_for(scope).append(
        L.K_DECISION, now=now, scope=scope.name, challenger_id=member.id, hound_id=member.hound_id,
        outcome=LR.OUTCOME_RETIRED, reason=rules.CULL_REASON,
        detail=(f"breeding cycle {cycle_date}: bottom 2 of the eligible members, {member.n} settled forward "
                f"bets, shrunk CLV {member.shrunk:+.4f}"), look_no=None, bh=None)
    lessons.ensure(scope, L.read_state(scope), now=now)


# ---- the auto-pause -----------------------------------------------------------------------------------------

def bad_cycles(breed: BreedState, state: L.State) -> list:
    """The birth cycles (oldest first) with, for each, whether ALL its babies ended badly (HURT or TOO
    EARLY on the referee). A cycle with a baby not yet ended (or not found) is not bad."""
    by_cycle: dict = {}
    for b in breed.births:
        by_cycle.setdefault(str(b.get("cycle_date")), []).append(b["challenger_id"])
    out = []
    for d in sorted(by_cycle):
        verdicts = []
        for cid in by_cycle[d]:
            c = state.challengers.get(cid)
            verdicts.append(c is not None and (c.status, c.outcome_reason) in rules.BAD_ENDINGS)
        out.append((d, bool(verdicts) and all(verdicts)))
    return out


def should_pause(breed: BreedState, state: L.State) -> Optional[str]:
    cycles = bad_cycles(breed, state)
    last = cycles[-rules.PAUSE_AFTER_BAD_CYCLES:]
    if len(last) == rules.PAUSE_AFTER_BAD_CYCLES and all(bad for _d, bad in last):
        return (f"the last {rules.PAUSE_AFTER_BAD_CYCLES} birth cycles ({', '.join(d for d, _ in last)}) each "
                f"ended every baby as HURT or TOO EARLY on the referee")
    return None


def resume(world: World, reason: str, *, now: Optional[datetime] = None) -> dict:
    now = now or L.utc_now()
    log = BreedLog(world.breed_ledger)
    if not fold(log.read()).paused:
        return {"paused": False, "already": True}
    log.append(rules.K_RESUME, now=now, reason=str(reason)[:300])
    return {"paused": False, "already": False}


# ---- the cycle -------------------------------------------------------------------------------------------------

def _record_missed(log: BreedLog, breed: BreedState, now: datetime, due: Optional[date]) -> int:
    if due is None:
        return 0
    last = max((date.fromisoformat(d) for d in breed.cycles), default=None)
    start = rules.ANCHOR_DATE if last is None else last + timedelta(days=rules.CADENCE_DAYS)
    d, n = start, 0
    while d < due and n < rules.MAX_MISSED_ROWS:
        if d.isoformat() not in breed.cycles:
            log.append(rules.K_CYCLE, now=now, cycle_date=d.isoformat(), outcome=rules.OUTCOME_MISSED,
                       reason="no capture slot ran between this cycle date and the next")
            n += 1
        d += timedelta(days=rules.CADENCE_DAYS)
    return n


def _temp_scope(scope: L.Scope, tmp: Path) -> L.Scope:
    for src in (scope.events, scope.challenger_bets, scope.lessons):
        if Path(src).exists():
            shutil.copyfile(src, tmp / Path(src).name)
    return L.Scope(scope.name, tmp / Path(scope.events).name, tmp / Path(scope.challenger_bets).name,
                   tmp / Path(scope.lessons).name, None)


def tick(world: Optional[World] = None, *, now: Optional[datetime] = None, dry_run: bool = False,
         propose: Optional[Callable] = None) -> dict:
    """Run the due cycle (prereg section 1). ``propose`` replaces ``proposals.propose_pack`` (a test seam;
    same signature)."""
    world = world or World.default()
    now = now or L.utc_now()
    log = BreedLog(world.breed_ledger, dry=dry_run)
    breed = fold(log.read())
    due = due_cycle(now)
    report: dict = {"now": L.iso(now), "dry_run": dry_run, "next_cycle_utc": L.iso(cycle_start(next_cycle(now)))}
    if not dry_run:
        report["missed_recorded"] = _record_missed(log, breed, now, due)
        breed = fold(log.read())
    target = due if (due is not None and due.isoformat() not in breed.cycles) else None
    if target is None:
        if not dry_run:
            report.update(due=False, message=f"no cycle due; next at {report['next_cycle_utc']}")
            return report
        target = next_cycle(now)
        report["due"] = False
        report["note"] = "no cycle is due now; this dry run computes the next cycle on today's data"
    else:
        report["due"] = True
    cycle_date = target.isoformat()
    report["cycle_date"] = cycle_date

    if dry_run:
        with tempfile.TemporaryDirectory() as tmp:
            scope = _temp_scope(world.scope, Path(tmp))
            out = _run(world, scope, log, breed, now, cycle_date, propose)
    else:
        out = _run(world, world.scope, log, breed, now, cycle_date, propose)
    report.update(out)
    if dry_run:
        report["would_write"] = [{k: v for k, v in r.items() if k not in ("eligibility",)} for r in log.pending]
    return report


def _skip(log: BreedLog, now: datetime, cycle_date: str, reason: str, **extra) -> dict:
    log.append(rules.K_CYCLE, now=now, cycle_date=cycle_date, outcome=rules.OUTCOME_SKIPPED, reason=reason, **extra)
    return {"outcome": rules.OUTCOME_SKIPPED, "reason": reason}


def _run(world: World, scope: L.Scope, log: BreedLog, breed: BreedState, now: datetime, cycle_date: str,
         propose: Optional[Callable]) -> dict:
    if not enabled(world.config):
        return _skip(log, now, cycle_date, "disabled")
    if breed.paused:
        return _skip(log, now, cycle_date, "paused", pause_reason=breed.pauses[-1].get("reason"))

    state = L.read_state(scope)
    members = members_of(world, state, breed)
    table = [m.to_json() for m in sorted(members, key=lambda m: (-m.n, m.id))]
    ranked = select.rank(members)
    if not ranked:
        best = select.most_settled(members)
        return _skip(log, now, cycle_date,
                     f"no eligible parents: {best}/{rules.MIN_SETTLED_FOR_ELIGIBLE} bets",
                     eligibility=table)

    tun_cfg = world.tunables()
    # ---- culls
    culls, replacements = [], []
    for m in select.cull_candidates(ranked):
        if m.role == "champion":
            action = "replacement_proposed"
            replacements.append((m, select.best_relative(ranked, m)))
        else:
            action = "retired"
            retire_challenger(scope, m, now=now, cycle_date=cycle_date)
        log.append(rules.K_CULL, now=now, cycle_date=cycle_date, member=m.to_json(), action=action)
        culls.append({"id": m.id, "action": action})

    # ---- litters
    if propose is None:
        from src.hounds.learning import proposals
        propose = proposals.propose_pack
    from src.hounds.learning import proposals as P
    pool = select.parent_pool(ranked)
    litters = cross.plan(pool, replacements)
    rngs: dict = {}
    births, refused, attempts = [], [], 0
    cap_note = None
    for litter in litters:
        if attempts >= rules.MAX_LITTERS_PER_CYCLE:
            break
        state = L.read_state(scope)
        if len(live_babies(state)) >= rules.MAX_LIVE_BABIES:
            cap_note = f"{rules.MAX_LIVE_BABIES} live babies already: no litter attempted"
            break
        tun = tun_cfg.get(litter.hound_id)
        if tun is None:
            continue
        rng = rngs.setdefault(litter.hound_id, cross.rng_for(cycle_date, litter.hound_id))
        baby = cross.make_baby(tun, litter.parents, rng)
        generation = 1 + max(p.generation for p in litter.parents)
        attempts += 1
        common = dict(cycle_date=cycle_date, hound_id=litter.hound_id, litter=litter.kind,
                      generation=generation, values=baby.values, origin=baby.origin, mutation=baby.mutation,
                      parents=[{"ref": p.ref(), "id": p.id, "role": p.role, "version": p.version,
                                "generation": p.generation, "values": p.values, "settled": p.n,
                                "shrunk_clv": round(p.shrunk, rules.FITNESS_DECIMALS)} for p in litter.parents],
                      culled=(litter.culled.ref() if litter.culled is not None else None))
        champion_version = state.champion_version(litter.hound_id)
        try:
            c = propose(scope, litter.hound_id, dict(baby.values),
                        cross.hypothesis(baby, cycle_date, generation, litter.kind),
                        cross.evidence(baby, cycle_date, litter.culled),
                        graded=graded_count(world, litter.hound_id, champion_version),
                        coach_on=True, now=now, proposed_by=rules.PROPOSED_BY, tunable_cfg=tun_cfg)
        except P.ProposalError as exc:
            log.append(rules.K_REFUSED, now=now, code=exc.code, message=str(exc)[:300], **common)
            refused.append({"hound_id": litter.hound_id, "litter": litter.kind, "code": exc.code,
                            "message": str(exc)[:300]})
            continue
        log.append(rules.K_BIRTH, now=now, challenger_id=c.id, rule_text=(c.spec or {}).get("rule_text"),
                   spec_diff=c.spec_diff, **common)
        births.append({"challenger_id": c.id, "hound_id": litter.hound_id, "litter": litter.kind,
                       "generation": generation})

    pool_refs = [m.ref() for m in pool]
    log.append(rules.K_CYCLE, now=now, cycle_date=cycle_date, outcome=rules.OUTCOME_RAN,
               reason=cap_note or f"{len(births)} born, {len(refused)} refused, {len(culls)} culled",
               pool=pool_refs, births=[b["challenger_id"] for b in births], refused=len(refused),
               culls=culls, eligibility=table)
    out = {"outcome": rules.OUTCOME_RAN, "reason": cap_note or f"{len(births)} born, {len(refused)} refused, "
                                                            f"{len(culls)} culled",
           "pool": pool_refs, "births": births, "refused": refused,
           "culls": culls, "eligible": len(ranked)}
    if cap_note:
        out["note_cap"] = cap_note
    why = should_pause(fold(log.read()), L.read_state(scope))
    if why:
        log.append(rules.K_PAUSE, now=now, reason=why)
        out["paused"] = why
    return out


# ---- the family tree (GET /hounds/breeding) --------------------------------------------------------------------

def _challenger_record(tallies: Mapping, cid: str) -> dict:
    t = tallies.get(cid) or select.Tally()
    return {"w": t.wins, "l": t.losses, "p": t.pushes, "settled": t.n,
            "clv_mean": round(t.clv_sum / t.m, 4) if t.m else None,
            "units": round(t.units_avg, 2)}


def family_tree(world: Optional[World] = None, *, now: Optional[datetime] = None) -> dict:
    """The read-only payload: babies with parents, generation, knobs, status and record; culls; refusals;
    the recent cycles; the next cycle time; and the eligibility table (x/25 bets)."""
    world = world or World.default()
    now = now or L.utc_now()
    breed = fold(BreedLog(world.breed_ledger).read())
    state = L.read_state(world.scope)
    members = members_of(world, state, breed)
    chall = select.tally(_rows(world.scope.challenger_bets), by_version=False)
    babies = []
    for b in breed.births:
        c = state.challengers.get(b["challenger_id"])
        babies.append({
            "challenger_id": b["challenger_id"], "hound_id": b.get("hound_id"), "generation": b.get("generation"),
            "litter": b.get("litter"), "born_cycle": b.get("cycle_date"), "born_utc": b.get("utc"),
            "parents": [p.get("ref") for p in b.get("parents") or []], "values": b.get("values"),
            "mutation": b.get("mutation"), "rule_text": b.get("rule_text"),
            "status": c.status if c is not None else "unknown",
            "outcome_reason": c.outcome_reason if c is not None else None,
            "record": _challenger_record(chall, b["challenger_id"]),
            "hindsight": "none computed (any replay would be rehearsal, not counted)"})
    gens: dict = {}
    for m in members:
        if m.role != "baby":
            gens.setdefault(0, []).append(m.ref())
    for b in babies:
        gens.setdefault(int(b.get("generation") or 1), []).append(b["challenger_id"])
    nxt = next_cycle(now)
    last_cycles = sorted(breed.cycles.values(), key=lambda r: r.get("cycle_date") or "")[-20:]
    return {
        "as_of": L.iso(now), "enabled": enabled(world.config), "paused": breed.paused,
        "pause_reason": breed.pauses[-1].get("reason") if breed.paused else None,
        "next_cycle_date": nxt.isoformat(), "next_cycle_utc": L.iso(cycle_start(nxt)),
        "cadence_days": rules.CADENCE_DAYS,
        "generations": [{"generation": g, "members": sorted(gens[g])} for g in sorted(gens)],
        "babies": babies,
        "live_babies": sum(1 for b in babies if b["status"] == "live"),
        "culls": [{"cycle_date": r.get("cycle_date"), "utc": r.get("utc"), "action": r.get("action"),
                   "member": r.get("member")} for r in breed.culls],
        "refusals": [{"cycle_date": r.get("cycle_date"), "hound_id": r.get("hound_id"), "litter": r.get("litter"),
                      "code": r.get("code"), "message": r.get("message"),
                      "parents": [p.get("ref") for p in r.get("parents") or []]} for r in breed.refusals[-20:]],
        "cycles": [{"cycle_date": r.get("cycle_date"), "outcome": r.get("outcome"), "reason": r.get("reason"),
                    "births": r.get("births") or []} for r in last_cycles],
        "eligibility": [m.to_json() for m in sorted(members, key=lambda m: (-m.n, m.id))],
        "rules": {"eligible_after": rules.MIN_SETTLED_FOR_ELIGIBLE, "shrink_prior_bets": rules.SHRINK_PRIOR_BETS,
                  "parent_pool": rules.PARENT_POOL, "litters_per_cycle": rules.MAX_LITTERS_PER_CYCLE,
                  "max_live_babies": rules.MAX_LIVE_BABIES, "cull_min_settled": rules.CULL_MIN_SETTLED,
                  "mutation_probability": rules.MUTATION_PROBABILITY,
                  "fitness": "forward closing-line value only, shrunk toward 0 by sample size; never hindsight",
                  "promotion": "a baby is a challenger: only the referee's pre-registered paired test can promote it"},
        "paper_only": True,
    }
