"""The training screen's two choices (owner request 2026-10-27): FINE-TUNE and FULL REBUILD.

WHY THIS EXISTS. Send to training used to propose up to three NARROWING changes from a fixed menu (``training.propose``): drop a
sport, tighten a price band, one more book. Claude Haiku could only REORDER that menu, so every proposal was a small, careful
nudge, and nothing checked that the nudge was better than what the hound already had. The owner called them "bland and stupid".
Now the owner chooses:

  FINE-TUNE   a small change that must BEAT the current rule on a rehearsal. ``fine_tune`` tries a handful of single changes from
              the same closed menu (``retune.full_menu``: narrowing and widening), replays each on the captured boards with the
              same drill the Backtest tab runs, and offers the best one ONLY IF it beats the current rule by the measured gate
              below. If none does it says so plainly and offers the rebuild. It never shows a suggestion that is not better.
  FULL REBUILD  Claude rebuilds the rule set from the hound's whole record (``rebuild_ai``: parallel angles, code-enforced limits,
              rehearsal of every survivor, an analyst, a plain-talk explainer). It is a MAJOR change by construction (a measured
              distance from the current rule), and it costs real money, so it is limited per member per day and by a monthly
              spend guard (``rebuild_budget``).

Either one produces a PLAN, saved on the server; the page shows it with the before and after rehearsal and an Apply button, and
Apply (``apply_plan``) goes through the existing ``user_store.create_version``: the old version is retired with its record frozen
and the next version starts with an empty record. The page never sends a rule set: it sends a plan id, so a tick can only name
something the server itself produced and checked.

THE REHEARSAL IS HINDSIGHT, NEVER COUNTED. It is ``drill.drill`` over the last ``REPLAY_DAYS`` completed days of captured boards,
written to a throwaway ledger. The hound's record, the leaderboard and the learning loop never see it, and every card says so.

WHAT "BETTER" MEANS (``beats``), honestly. On the same window, the candidate must (1) have at least ``MIN_REPLAY_BETS`` graded bets
so a handful of games cannot decide it, (2) win ``MIN_UNITS_GAIN`` more units than the current rule at the average price,
(3) win ``MIN_PER_BET_GAIN`` more units per graded bet (so it is not simply betting more), and (4) keep at least ``KEEP_FRACTION`` of
the current rule's graded bets (so it is not "better" only because it stopped betting). Under ``drill.SMALL_N`` graded bets the card
says the sample is small. A rehearsal is not evidence about the future, and nothing here promises a result.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from src.hounds import user_rules, user_spec, user_store
from src.hounds.interact import common, rebuild_ai, rebuild_budget as budget, rites, training
from src.hounds.interact.rites import RiteError

logger = logging.getLogger("linehound.hounds.training_plans")

REPLAY_DAYS = 30                 # the longest window the drill allows (drill.DAYS_CHOICES)
MIN_REPLAY_BETS = 20
MIN_UNITS_GAIN = 1.0
MIN_PER_BET_GAIN = 0.02
KEEP_FRACTION = 0.5
MINOR_MAX_REPLAYS = 4            # single changes replayed per fine-tune (plus one combination of the best two)
MINOR_BUDGET_S = 60.0
REBUILD_MAX_REPLAYS = 8          # survivors replayed per rebuild (the analyst's result is replayed on top of these)
REBUILD_REPLAY_BUDGET_S = 100.0
RUNNERS_UP = 2
PLAN_TTL_S = 24 * 3600
JOB_TTL_S = 2 * 3600
PLAN_ID_LEN = 24

KIND_MINOR, KIND_REBUILD = "minor", "rebuild"
MODE_MINOR, MODE_REBUILD = "fine_tune", "rebuild"

REHEARSAL_LABEL = "Rehearsal (hindsight, not counted in the record)"
REHEARSAL_NOTE = ("A rehearsal replays the rules on games that already happened. It shows how a rule set behaved on those games; "
                  "it is not proof and says nothing certain about the games ahead. It is never added to a record or a ranking.")
HONESTY = ("Applying makes the next version of this hound and freezes the current version's record. The next version starts with an "
           "empty record. Nothing here promises a result. Paper money only.")


# ---------------------------------------------------------------------------
# the rehearsal and the gate
# ---------------------------------------------------------------------------

def numbers_of(summary: Optional[Mapping]) -> Optional[dict]:
    """The few figures of a drill result that the gate and the card use, or None when there is no result."""
    if not summary:
        return None
    rec = summary.get("record") or {}
    graded = int(rec.get("graded") or 0)
    units = round(float(summary.get("units_average_price") or 0.0), 2)
    return {"graded": graded, "wins": int(rec.get("wins") or 0), "losses": int(rec.get("losses") or 0),
            "pushes": int(rec.get("pushes") or 0), "units": units, "per_bet": round(units / graded, 3) if graded else 0.0}


def beats(base: Optional[Mapping], cand: Optional[Mapping]) -> bool:
    """The gate for "better than what it is now" (see the module docstring). Both must be real rehearsal numbers."""
    if not base or not cand:
        return False
    return (cand["graded"] >= MIN_REPLAY_BETS and cand["graded"] >= KEEP_FRACTION * base["graded"]
            and cand["units"] - base["units"] >= MIN_UNITS_GAIN and cand["per_bet"] - base["per_bet"] >= MIN_PER_BET_GAIN)


def default_replay(spec: Mapping, days: int, now: datetime) -> dict:
    """The Backtest drill for a rule set. Raises ``RiteError`` when the drill refuses (busy, forward-only style)."""
    from src.hounds.interact import drill
    try:
        return drill.drill(spec=dict(spec), days=days, now=now)
    except drill.DrillError as exc:
        raise RiteError("replay_" + exc.code, str(exc), exc.status) from None


def _replay_numbers(replay_fn: Callable, spec: Mapping, now: datetime) -> Optional[dict]:
    return numbers_of(replay_fn(spec, REPLAY_DAYS, now))


def rehearsal_block(base: Optional[Mapping], after: Optional[Mapping], *, days: int = REPLAY_DAYS) -> dict:
    n = (after or {}).get("graded", 0)
    small = n < 30
    return {"label": REHEARSAL_LABEL, "note": REHEARSAL_NOTE, "counted": False, "days": days, "before": base, "after": after,
            "small_sample": small,
            "sample_text": (f"{n} graded bets in the rehearsal" + (": a small sample, so treat it as a rough look." if small else "."))}


# ---------------------------------------------------------------------------
# plans (saved on the server) and jobs (the slow part runs in the background)
# ---------------------------------------------------------------------------

def default_plan_dir() -> Path:
    return budget.default_ledger_path().parent / "rebuild_plans"


class PlanStore:
    """A plan is one JSON file under the data directory, so a deploy between "show the plan" and "Apply" does not lose a rebuild
    that cost money. Files older than ``PLAN_TTL_S`` are pruned on save. A plan holds rule sets and plain text, never a key."""

    def __init__(self, directory=None, *, clock: Optional[Callable[[], float]] = None):
        self.dir = Path(directory) if directory is not None else None
        self._clock = clock or time.time

    def _dir(self) -> Path:
        return self.dir if self.dir is not None else default_plan_dir()

    def save(self, plan: Mapping) -> str:
        d = self._dir()
        d.mkdir(parents=True, exist_ok=True)
        now = self._clock()
        for f in d.glob("*.json"):
            try:
                if now - f.stat().st_mtime > PLAN_TTL_S:
                    f.unlink()
            except OSError:
                pass
        plan_id = uuid.uuid4().hex[:PLAN_ID_LEN]
        body = dict(plan, plan_id=plan_id, saved_at=now)
        tmp = d / f"{plan_id}.tmp"
        tmp.write_text(json.dumps(body, sort_keys=True, default=str), encoding="utf-8")
        os.replace(tmp, d / f"{plan_id}.json")
        return plan_id

    def load(self, plan_id: str) -> Optional[dict]:
        if not isinstance(plan_id, str) or not plan_id.isalnum() or len(plan_id) != PLAN_ID_LEN:
            return None
        try:
            body = json.loads((self._dir() / f"{plan_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return body if self._clock() - float(body.get("saved_at") or 0) <= PLAN_TTL_S else None

    def delete(self, plan_id: str) -> None:
        try:
            (self._dir() / f"{plan_id}.json").unlink()
        except OSError:
            pass


class JobBoard:
    """The slow steps (a rebuild takes a minute or two) run on a thread and the page polls. One running job per member."""

    def __init__(self):
        self._jobs: dict = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        for key in [k for k, j in self._jobs.items() if now - j["at"] > JOB_TTL_S]:
            self._jobs.pop(key, None)

    def start(self, user_id: int, hound_id: str, kind: str, work: Callable[[Callable[[str], None]], dict], *, background: bool = True) -> dict:
        now = time.time()
        with self._lock:
            self._prune(now)
            if any(j["user_id"] == user_id and j["state"] == "running" for j in self._jobs.values()):
                raise RiteError("job_running", "Another training step is still running for you. Wait for it to finish.", 409)
            job_id = uuid.uuid4().hex[:PLAN_ID_LEN]
            job = {"id": job_id, "user_id": user_id, "hound_id": hound_id, "kind": kind, "state": "running", "stage": "Starting",
                   "result": None, "error": None, "at": now}
            self._jobs[job_id] = job

        def progress(text: str) -> None:
            job["stage"] = str(text)[:120]

        def run() -> None:
            try:
                job["result"] = work(progress)
                job["state"] = "done"
            except RiteError as exc:
                job["error"] = {"code": exc.code, "message": str(exc), "status": exc.status, "extra": exc.extra}
                job["state"] = "failed"
            except Exception as exc:  # noqa: BLE001 -- a worker thread must always end in a state the page can read
                logger.warning("training job failed kind=%s error=%s", kind, type(exc).__name__)
                job["error"] = {"code": "job_failed", "message": "That step could not finish just now. Nothing was changed.",
                                "status": 500, "extra": {}}
                job["state"] = "failed"
        if background:
            threading.Thread(target=run, name=f"training-{kind}", daemon=True).start()
        else:
            run()
        return self.view(job)

    @staticmethod
    def view(job: Mapping) -> dict:
        return {"job_id": job["id"], "kind": job["kind"], "state": job["state"], "stage": job["stage"], "result": job["result"],
                "error": job["error"]}

    def get(self, job_id: str, user_id: int) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return self.view(job) if job is not None and job["user_id"] == user_id else None


_plans = PlanStore()
_jobs = JobBoard()


def plans() -> PlanStore:
    return _plans


def jobs() -> JobBoard:
    return _jobs


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------

def _bet_rows(bets: Sequence, spec: Mapping, rule_index: Mapping) -> list:
    out = []
    for b in bets:
        if b.result not in rites.SETTLED_RESULTS:
            continue
        out.append({"date": b.date, "sport": str(b.sport or "").upper(), "market": training.market_of(b), "side": b.side,
                    "line": b.line, "price": b.price_average if b.price_average is not None else b.price, "result": b.result,
                    "units": training._units_of(b),                                    # noqa: SLF001
                    "rule": rule_index.get(b.bet_id) if user_spec.is_v2(spec) else None})
    out.sort(key=lambda r: r["date"] or "")
    return out


def _change_lines(old: Mapping, new: Mapping) -> list:
    from src.hounds.english import render
    out = []
    for d in render.diff_specs(old, new)[:8]:
        out.append(f"{d['what']}: {d['before']} -> {d['after']}")
    return out


def _rule_after(spec: Mapping) -> str:
    return user_spec.rule_text(spec)


def _explain_caller(env, meter_ceiling: float, client, client_factory) -> Optional[rebuild_ai.Caller]:
    key = budget.api_key(env)
    if key is None or meter_ceiling <= 0:
        return None
    return rebuild_ai.Caller(key, rebuild_ai.Meter(meter_ceiling), client=client, client_factory=client_factory)


def _ceiling(ledger: budget.RebuildLedger, env, router_spend) -> float:
    left = budget.monthly_cap(env) - ledger.month_spend()
    headroom = budget.router_headroom(router_spend)
    return max(0.0, left if headroom is None else min(left, headroom))


def _basis(hound: Mapping) -> str:
    return training.proposal_basis(hound["id"], hound["spec"])


def _gate(dog, user_id, now, rows, ledger_path, db) -> tuple:
    return training._ready(dog, user_id, confirmed_required=False, confirmed=False, now=now, rows=rows,  # noqa: SLF001
                           ledger_path=ledger_path, db=db)


# ---------------------------------------------------------------------------
# FINE-TUNE
# ---------------------------------------------------------------------------

def _minor_candidates(spec: Mapping, analysis: Mapping) -> list:
    """The single changes worth replaying, best-supported first: the evidence-based narrowing changes (worst weak spot first), then the
    owner-style narrowing and widening changes in menu order. At most ``MINOR_MAX_REPLAYS``."""
    from src.hounds.interact import retune
    entries = retune.full_menu(spec, analysis, None)
    evidence = sorted((e for e in entries if e.get("segment")), key=lambda e: e["segment"]["units"])
    rest = [e for e in entries if not e.get("segment")]
    return (evidence + rest)[:MINOR_MAX_REPLAYS]


def fine_tune(dog, user_id: int, *, now: Optional[datetime] = None, rows=None, ledger_path=None, db=None, replay_fn: Optional[Callable] = None,
              env: Optional[Mapping] = None, client=None, client_factory=None, ledger: Optional[budget.RebuildLedger] = None,
              router_spend=None, store: Optional[PlanStore] = None, progress: Callable[[str], None] = lambda _t: None) -> dict:
    """A small change that beats the current rule on the rehearsal, or a plain "none did" (never a suggestion that is not better)."""
    dog, moment, rows, bets, hound, gate = _gate(dog, user_id, now, rows, ledger_path, db)
    spec = hound["spec"]
    if user_spec.is_gematria(spec):
        raise RiteError("gematria_forward_only", "A Gematria hound is forward-only, so a rehearsal cannot test a change to it.", 422)
    replay = replay_fn or default_replay
    analysis = training.analyse(bets, spec, training.rule_index_of(rows, dog.id))
    progress("Rehearsing the rules it has now")
    base = _replay_numbers(replay, spec, moment)
    ledger = ledger or budget.RebuildLedger()
    started = time.monotonic()
    tried, winners = 0, []
    for entry in _minor_candidates(spec, analysis):
        if time.monotonic() - started > MINOR_BUDGET_S:
            break
        applied = training._apply_entry(copy.deepcopy(dict(spec)), entry, "minor")          # noqa: SLF001
        if applied is None:
            continue
        progress(f"Rehearsing a small change ({tried + 1})")
        new_spec, change = applied
        tried += 1
        got = _replay_numbers(replay, new_spec, moment)
        if beats(base, got):
            winners.append({"spec": new_spec, "after": got, "changes": [change], "entry": entry})
    if len(winners) >= 2 and time.monotonic() - started <= MINOR_BUDGET_S:
        top = sorted(winners, key=lambda w: -(w["after"]["units"]))[:2]
        first = training._apply_entry(copy.deepcopy(dict(spec)), top[0]["entry"], "minor")  # noqa: SLF001
        second = training._apply_entry(first[0], top[1]["entry"], "minor") if first else None  # noqa: SLF001
        if first and second:
            both = _replay_numbers(replay, second[0], moment)
            if beats(base, both):
                winners.append({"spec": second[0], "after": both, "changes": [first[1], second[1]], "entry": None})
    card = {"kind": KIND_MINOR, "name": dog.name, "version_no": hound["version_no"], "tried": tried, "found": False,
            "basis": _basis(hound), "paper_only": True,
            "rehearsal": rehearsal_block(base, None), "rebuild_offer": True}
    if not winners:
        card["message"] = (f"None of the {tried} small change{'s' if tried != 1 else ''} it tried did better than the rules {dog.name} has now "
                           f"in a rehearsal on the last {REPLAY_DAYS} days, so there is nothing worth fine-tuning. "
                           "Fine-tune only offers a change that does better. A full rebuild changes much more, if you want to try it.")
        return card
    best = max(winners, key=lambda w: (w["after"]["units"], w["after"]["per_bet"]))
    facts = {"kind": KIND_MINOR, "days": REPLAY_DAYS, "before": base, "after": best["after"], "small_sample": best["after"]["graded"] < 30,
             "changes": _change_lines(spec, best["spec"])}
    ceiling = _ceiling(ledger, env, router_spend)
    explainer = _explain_caller(env, min(ceiling, 0.05), client, client_factory)
    progress("Writing it up in plain words")
    explanation = rebuild_ai.explain(explainer, facts)
    if explainer is not None and explainer.meter.calls:
        ledger.record(user_id=user_id, hound_id=dog.id, status="fine_tune_explain", calls=explainer.meter.calls,
                      cost_usd=explainer.meter.spent, input_tokens=explainer.meter.input_tokens, output_tokens=explainer.meter.output_tokens)
    public_changes = [{k: v for k, v in c.items() if k in ("id", "label", "old_text", "new_text", "why", "cid")} for c in best["changes"]]
    plan = {"kind": KIND_MINOR, "user_id": user_id, "hound_id": dog.id, "basis": _basis(hound), "choices": {
        "main": {"spec": best["spec"], "changes": public_changes, "after": best["after"], "label": "Fine-tune"}}}
    plan_id = (store or _plans).save(plan)
    card.update(found=True, plan_id=plan_id, explanation=explanation, changes=public_changes,
                rule_before=_rule_after(spec), rule_after=_rule_after(best["spec"]), diff=_diff(spec, best["spec"]),
                rehearsal=rehearsal_block(base, best["after"]), beats_current=True, honesty=HONESTY, rebuild_offer=False)
    return card


def _diff(old: Mapping, new: Mapping) -> list:
    from src.hounds.english import render
    return render.diff_specs(old, new)


# ---------------------------------------------------------------------------
# FULL REBUILD
# ---------------------------------------------------------------------------

def _stage_cost_worst(context: str, count: int) -> tuple:
    """``(worst-case dollars for the whole rebuild, estimated dollars for a typical one)`` from the real prompt size."""
    system = rebuild_ai.system_text(rebuild_ai.SYSTEM_PROMPT)
    in_angle = budget.token_estimate(system) + budget.token_estimate(context) + 300
    angle_model = rebuild_ai.MODEL
    worst_angles = count * (1 + rebuild_ai.ANGLE_RETRIES) * budget.worst_case_cost(angle_model, in_angle, rebuild_ai.MAX_TOKENS_ANGLE)
    in_analyst = in_angle + 1500 * count
    analyst_model = rebuild_ai.SYNTHESIS_MODEL if rebuild_ai.USE_SONNET_SYNTHESIS else rebuild_ai.MODEL
    worst = (worst_angles + budget.worst_case_cost(analyst_model, in_analyst, rebuild_ai.MAX_TOKENS_ANALYST)
             + budget.worst_case_cost(rebuild_ai.MODEL, 1500, rebuild_ai.MAX_TOKENS_EXPLAIN))
    return round(worst, 4), in_angle


def rank(base: Optional[Mapping], candidates: Sequence[Mapping]) -> list:
    """Candidates best first by the rehearsal: those with enough graded bets, most units then most units per bet; the rest after."""
    def key(c):
        n = c["replay"]
        return (n["graded"] >= MIN_REPLAY_BETS, n["units"], n["per_bet"])
    return sorted((c for c in candidates if c.get("replay")), key=key, reverse=True)


def full_rebuild(dog, user_id: int, *, paid: bool = False, now: Optional[datetime] = None, rows=None, ledger_path=None, db=None,
                 replay_fn: Optional[Callable] = None, env: Optional[Mapping] = None, client=None, client_factory=None,
                 ledger: Optional[budget.RebuildLedger] = None, router_spend=None, store: Optional[PlanStore] = None,
                 angle_count: Optional[int] = None, progress: Callable[[str], None] = lambda _t: None) -> dict:
    """The whole rebuild. Raises ``RiteError`` for a refusal (the limits, the key, an open ticket); otherwise returns the card."""
    dog, moment, rows, bets, hound, gate = _gate(dog, user_id, now, rows, ledger_path, db)
    spec = hound["spec"]
    if user_spec.is_gematria(spec) or user_spec.is_apprentice(spec):
        raise RiteError("rebuild_not_for_style", "That kind of hound has no rule set to rebuild: it follows its own fixed method.", 422)
    ledger = ledger or budget.RebuildLedger()
    replay = replay_fn or default_replay
    count = len(rebuild_ai.angles(angle_count))
    # the cheap refusals first: no key, today's limit, the month's spend, all BEFORE the rehearsal or any model
    try:
        budget.check(user_id, paid=paid, worst_cost=0.0, ledger=ledger, env=env, router_spend=router_spend)
    except budget.BudgetError as exc:
        raise RiteError(exc.code, str(exc), exc.status, **exc.extra) from None
    progress("Rehearsing the rules it has now")
    base_summary = replay(spec, REPLAY_DAYS, moment)
    base = numbers_of(base_summary)
    current = rebuild_ai.v2_of(spec)
    analysis = training.analyse(bets, spec, training.rule_index_of(rows, dog.id))
    context = rebuild_ai.build_context(name=dog.name, version_no=hound["version_no"], spec_v2=current, plain_rule=user_spec.rule_text(spec),
                                       bets=_bet_rows(bets, spec, training.rule_index_of(rows, dog.id)), analysis=analysis,
                                       baseline=base_summary)
    worst, _in_angle = _stage_cost_worst(context, count)
    try:
        used = budget.check(user_id, paid=paid, worst_cost=worst, ledger=ledger, env=env, router_spend=router_spend)
    except budget.BudgetError as exc:
        raise RiteError(exc.code, str(exc), exc.status, **exc.extra) from None
    meter = rebuild_ai.Meter(min(worst, _ceiling(ledger, env, router_spend)))
    caller = rebuild_ai.Caller(budget.api_key(env), meter, client=client, client_factory=client_factory)
    status = "ok"
    try:
        progress(f"{count} angles are rebuilding it at the same time")
        results = rebuild_ai.run_angles(caller, context, current, count)
        survivors, seen = [], {user_spec.spec_hash(current)}
        for r in results:
            if r["spec"] is None:
                continue
            h = user_spec.spec_hash(r["spec"])
            if h in seen:
                continue
            seen.add(h)
            survivors.append(dict(r, id=f"c{len(survivors) + 1}", hash=h))
        started = time.monotonic()
        replayed = []
        for c in survivors[:REBUILD_MAX_REPLAYS]:
            if time.monotonic() - started > REBUILD_REPLAY_BUDGET_S:
                break
            progress(f"Rehearsing candidate {c['id']} of {len(survivors)}")
            c["replay"] = _replay_numbers(replay, c["spec"], moment)
            c["rule_text"] = _rule_after(c["spec"])
            replayed.append(c)
        analyst_result = None
        if replayed:
            progress("The analyst is comparing them")
            analyst_result = rebuild_ai.run_analyst(caller, context, replayed, current)
            if analyst_result is not None:
                h = user_spec.spec_hash(analyst_result["spec"])
                existing = next((c for c in replayed if c["hash"] == h), None)
                if existing is not None:
                    existing["analyst_pick"] = True
                    analyst_result["candidate"] = existing
                elif h not in seen and time.monotonic() - started <= REBUILD_REPLAY_BUDGET_S:
                    node = {"angle": "analyst", "label": "Analyst's merge", "spec": analyst_result["spec"], "id": "analyst", "hash": h,
                            "summary": (analyst_result["reasons"] or [""])[0], "analyst_pick": True,
                            "replay": _replay_numbers(replay, analyst_result["spec"], moment), "rule_text": _rule_after(analyst_result["spec"])}
                    replayed.append(node)
                    analyst_result["candidate"] = node
        ranked = rank(base, replayed)
        if not ranked:
            status = "no_candidate"
            return {"kind": KIND_REBUILD, "found": False, "name": dog.name, "version_no": hound["version_no"], "paper_only": True,
                    "basis": _basis(hound), "usage": {"used_today": used["used_today"] + 1, "limit_per_day": used["limit_per_day"],
                                                      "left_today": max(0, used["left_today"] - 1)},
                    "message": ("The rebuild did not produce a rule set that passed the checks and could be rehearsed this time. "
                                "Fine-tune is still open. This counted as one of today's rebuilds."),
                    "rehearsal": rehearsal_block(base, None)}
        best = ranked[0]
        best_tied = next((c for c in ranked if c.get("analyst_pick") and c["replay"]["units"] >= best["replay"]["units"] - 0.5), best)
        best = best_tied
        facts = {"kind": KIND_REBUILD, "days": REPLAY_DAYS, "before": base, "after": best["replay"],
                 "small_sample": best["replay"]["graded"] < 30, "changes": _change_lines(spec, best["spec"])}
        progress("Writing it up in plain words")
        explanation = rebuild_ai.explain(caller, facts)
    finally:
        if meter.calls or meter.spent:
            ledger.record(user_id=user_id, hound_id=dog.id, status=status, calls=meter.calls, cost_usd=meter.spent,
                          input_tokens=meter.input_tokens, output_tokens=meter.output_tokens)
    choices = {c["id"]: {"spec": c["spec"], "after": c["replay"], "label": c["label"], "summary": c["summary"]} for c in ranked}
    plan = {"kind": KIND_REBUILD, "user_id": user_id, "hound_id": dog.id, "basis": _basis(hound), "main": best["id"], "choices": choices}
    plan_id = (store or _plans).save(plan)
    beats_now = bool(base and best["replay"]["graded"] >= MIN_REPLAY_BETS and best["replay"]["units"] > base["units"]
                     and best["replay"]["per_bet"] > base["per_bet"])
    ups = [c for c in ranked if c["id"] != best["id"]][:RUNNERS_UP]
    analyst_view = None
    if analyst_result is not None and analyst_result.get("candidate") is best:
        analyst_view = {k: analyst_result[k] for k in ("reasons", "cut", "added", "weak_spots")}
    return {"kind": KIND_REBUILD, "found": True, "plan_id": plan_id, "choice": best["id"], "name": dog.name, "version_no": hound["version_no"],
            "basis": _basis(hound), "explanation": explanation, "rule_before": _rule_after(spec), "rule_after": _rule_after(best["spec"]),
            "diff": _diff(spec, best["spec"]), "rehearsal": rehearsal_block(base, best["replay"]), "beats_current": beats_now,
            "analyst": analyst_view,
            "runners_up": [{"choice": c["id"], "label": c["label"], "rule_after": _rule_after(c["spec"]), "summary": c["summary"],
                            "after": c["replay"]} for c in ups],
            "usage": {"used_today": used["used_today"] + 1, "limit_per_day": used["limit_per_day"], "left_today": max(0, used["left_today"] - 1)},
            "honesty": HONESTY, "paper_only": True}


# ---------------------------------------------------------------------------
# APPLY
# ---------------------------------------------------------------------------

def apply_plan(dog, user_id: int, plan_id: str, *, choice: Optional[str] = None, basis: Optional[str] = None, now: Optional[datetime] = None,
               rows=None, ledger_path=None, db=None, store: Optional[PlanStore] = None) -> dict:
    """Make the version a saved plan describes. The plan, not the page, holds the rule set; it is re-checked here (the same gate
    that checked it when it was made) against the hound as it stands now."""
    store = store or _plans
    dog = rites.guard(dog, user_id)
    plan = store.load(plan_id)
    if plan is None or plan.get("user_id") != user_id or plan.get("hound_id") != dog.id:
        raise RiteError("plan_not_found", "That proposal is gone (it expires after a day). Start the step again; nothing was changed.", 404)
    live = user_store.get_hound(dog.id, db=db)
    if live is None or live["status"] == user_store.STATUS_RETIRED or (basis is not None and str(basis) != plan["basis"]) \
            or plan["basis"] != training.proposal_basis(dog.id, live["spec"]):
        raise training._stale(dog.name)                                                    # noqa: SLF001
    dog, moment, rows, bets, hound, gate = training._ready(dog, user_id, confirmed_required=False, confirmed=True, now=now, rows=rows,  # noqa: SLF001
                                                           ledger_path=ledger_path, db=db)
    key = choice or plan.get("main") or "main"
    picked = (plan.get("choices") or {}).get(key)
    if picked is None:
        raise RiteError("unknown_choice", "That is not one of the options on this proposal.", 422)
    spec = hound["spec"]
    if plan["kind"] == KIND_REBUILD:
        new_spec, why = rebuild_ai.vet_spec(picked["spec"], spec)
        if new_spec is None or rebuild_ai.too_similar(rebuild_ai.spec_distance(spec, new_spec)):
            raise RiteError("spec_invalid", "The rebuilt rules did not pass the checks, so nothing was changed.", 422)
        origin, mode, reason, label = user_store.ORIGIN_REBUILD, MODE_REBUILD, "full rebuild", "Full rebuild"
    else:
        new_spec = training._validated(picked["spec"])                                       # noqa: SLF001
        if new_spec is None or user_spec.spec_hash(new_spec) == user_spec.spec_hash(spec):
            raise RiteError("spec_invalid", "That change did not pass the checks, so nothing was changed.", 422)
        origin, mode, reason, label = user_store.ORIGIN_FINE_TUNE, MODE_MINOR, "fine-tune", "Fine-tune"
    analysis = training.analyse(bets, spec, training.rule_index_of(rows, dog.id))
    frozen = dict(analysis["overall"])
    diff = _diff(spec, new_spec)
    changes = [{"id": f"d{i}", "label": d["what"], "old_text": str(d["before"])[:240], "new_text": str(d["after"])[:240]} for i, d in enumerate(diff[:6])]
    event = {"kind": user_store.EVENT_TRAINED,
             "payload": {"name": hound["name"], "from_hound_id": dog.id, "from_version": hound["version_no"], "to_version": hound["version_no"] + 1,
                         "mode": mode, "settled": analysis["settled"], "origin": origin, "owner_chosen": True,
                         "record": {k: frozen[k] for k in ("wins", "losses", "pushes")}, "changes": changes,
                         "rehearsal": {"days": REPLAY_DAYS, "after": picked.get("after")},
                         "coach": {"source": "none", "status": "not_asked", "model": None, "cost_usd": 0.0, "reasons": [], "picks": [],
                                   "picks_applied": [], "cuts_examined": None}}}
    try:
        new = user_store.create_version(dog.id, new_spec, actor=f"owner:{user_id}", reason=reason, now=moment, db=db, coached_from=dog.id,
                                        event=event, origin=origin)
    except user_spec.SpecError as exc:
        raise RiteError("spec_invalid", "The new rules did not pass the checks, so nothing was changed.", 422, fields=exc.errors)
    except user_store.StoreError as exc:
        if exc.code == "retired":
            raise training._stale(dog.name, applied_elsewhere=True) from None              # noqa: SLF001
        raise RiteError(exc.code, str(exc), {"not_found": 404, "buried": 409}.get(exc.code, 400))
    store.delete(plan_id)
    training._tweaks_clear(dog.id)                                                             # noqa: SLF001
    logger.info("training plan applied hound=%s from_v=%s to_v=%s mode=%s", dog.id, hound["version_no"], new["version_no"], mode)
    return {
        "mode": mode, "light_adjustment": False, "origin": origin, "label": label, "lineage": user_store.ORIGIN_LABELS[origin],
        "headline": f"{dog.name} is back as version {new['version_no']}. Its record starts now.",
        "light_note": None, "changes": changes, "change_sentence": "; ".join(f"{c['label']}: {c['old_text']} -> {c['new_text']}" for c in changes),
        "diff": diff, "analysis": {"settled": analysis["settled"], "overall": analysis["overall"], "weak": []}, "coach": None, "diagnosis": None,
        "guidance": {"text": "", "source": "code", "ai_requested": False},
        "old": {"id": dog.id, "version_no": hound["version_no"], "record": frozen, "frozen": True},
        "new": {"id": new["id"], "version_no": new["version_no"], "coached_from": new["coached_from"], "origin": new.get("origin"),
                "trained_times": user_store.trained_count(new["root_id"], db=db), "page_href": f"hound.html?id={new['id']}",
                "record": {"wins": 0, "losses": 0, "pushes": 0, "bets": 0}},
        "next_training": f"It can train again after {training.MIN_NEW_SETTLED} settled bets on version {new['version_no']}.",
        "honesty": HONESTY, "paper_only": True}
