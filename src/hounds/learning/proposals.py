"""A proposal: the only thing a model can do, and everything that can stop it.

A coach submission creates a CHALLENGER, never a champion (docs/PREREG_LEARNING_LOOP.md sections 1
and 3). This module is the pure guard-and-record step shared by the two doors:

  * the signed API door for user hounds (``user_coach.submit`` verifies the signature, the one-use
    key, the opt-in and the kill switch, validates the spec against the menu, then calls
    ``propose_user`` here);
  * the operator CLI for pack hounds (``python -m src.hounds.learning propose``), which calls
    ``propose_pack``.

Both return the new ``Challenger`` and have appended exactly one ``proposal`` event; on a refusal
they raise ``ProposalError`` (stable ``code``, HTTP-ish ``status``) after appending a
``proposal_refused`` event, so the monthly review can see what the coach tried. A refusal because
the coach is switched off or paused writes nothing: it never reached the guards.

The order of the guards is the prereg's section 3, and it is the order a reader would want the
cheap ones in: switch, record, rate, caps, text, spec, repeats.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional, Sequence

from src.hounds import user_spec
from src.hounds.learning import ledger as L
from src.hounds.learning import pause, rules, tunables

_TEXT_RE = re.compile(r"^[A-Za-z0-9 .,'!?&()/+:%\-;=<>_]*$")
# What evidence references look like: a scorecard field path or a lesson/challenger id.
_REF_RE = re.compile(r"^[A-Za-z0-9_.:\[\]\-/ ]+$")

NOT_RECORDED = ("coach_disabled", "paused")


class ProposalError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(message)


# ---- text -----------------------------------------------------------------------------------------

def clean_text(value: Any, field: str, lo: int, hi: int) -> str:
    if not isinstance(value, str):
        raise ProposalError("bad_text", f"{field} must be text")
    text = " ".join(value.split())
    if len(text) < lo:
        raise ProposalError("bad_text", f"{field} must be at least {lo} characters")
    if len(text) > hi:
        raise ProposalError("bad_text", f"{field} must be {hi} characters or fewer")
    if not _TEXT_RE.match(text):
        raise ProposalError("bad_text", f"{field} uses characters that are not allowed")
    problem = user_spec.text_problem(text)
    if problem:
        raise ProposalError("bad_text", f"{field} {problem}")
    return text


def clean_evidence(value: Any) -> list:
    if not isinstance(value, (list, tuple)):
        raise ProposalError("bad_evidence", "evidence must be a list of references")
    out = []
    for ref in value:
        if not isinstance(ref, str) or not ref.strip() or len(ref) > rules.EVIDENCE_REF_MAX \
                or not _REF_RE.match(ref):
            raise ProposalError("bad_evidence", "each evidence reference must be a short plain "
                                                "scorecard field or lesson id")
        out.append(ref.strip())
    if not rules.EVIDENCE_MIN <= len(out) <= rules.EVIDENCE_MAX:
        raise ProposalError("bad_evidence", f"give {rules.EVIDENCE_MIN} to {rules.EVIDENCE_MAX} "
                                            f"evidence references")
    return out


# ---- the shared guards ------------------------------------------------------------------------------

def _record_refusal(scope: L.Scope, exc: ProposalError, *, hound_id: str, lineage_key: str,
                    now: datetime, proposed_by: str) -> None:
    if exc.code in NOT_RECORDED:
        return
    L.log_for(scope).append(L.K_REFUSED, now=now, scope=scope.name, hound_id=hound_id,
                            lineage_key=lineage_key, code=exc.code, message=str(exc)[:300],
                            proposed_by=proposed_by)


def _switch_guard(scope: L.Scope, *, coach_on: bool) -> None:
    if not coach_on:
        raise ProposalError("coach_disabled", "the Houndmaster is switched off", 503)
    if pause.is_paused(scope):
        raise ProposalError("paused", "the learning loop paused itself; the owner must resume it", 503)


def _record_and_rate_guard(state: L.State, *, graded: int, lineage_key: str, now: datetime) -> None:
    if graded < rules.MIN_GRADED_BEFORE_PROPOSAL:
        raise ProposalError(
            "not_enough_bets", f"this version has {graded} graded bets; a challenger needs at least "
            f"{rules.MIN_GRADED_BEFORE_PROPOSAL} so the record it competes against exists", 409)
    last = state.last_allowance_use(lineage_key)
    window = timedelta(days=rules.PROPOSAL_COOLDOWN_DAYS)
    if last is not None and now - last < window:
        wait = window - (now - last)
        raise ProposalError("too_soon", f"one proposal per hound per {rules.PROPOSAL_COOLDOWN_DAYS} days; "
                            f"next possible in {wait.days}d {wait.seconds // 3600}h", 429)


def _caps_guard(state: L.State, *, lineage_key: str) -> None:
    if len([c for c in state.live() if c.lineage_key == lineage_key]) >= rules.MAX_LIVE_PER_HOUND:
        raise ProposalError("too_many_live", f"a hound may have at most {rules.MAX_LIVE_PER_HOUND} live "
                            f"challengers; wait for one to be decided", 409)
    if len(state.live()) >= rules.MAX_LIVE_PER_SCOPE:
        raise ProposalError("system_full", f"the system may run at most {rules.MAX_LIVE_PER_SCOPE} live "
                            f"challengers in this scope; wait for one to be decided", 409)


def retired_recent(state: L.State, lineage_key: str, now: datetime) -> list:
    """Challengers of the lineage that LOST or never won (outcome retired) in the dedupe window."""
    window = timedelta(days=rules.DEDUPE_DAYS)
    out = []
    for c in state.challengers.values():
        if c.lineage_key != lineage_key or c.status != rules.OUTCOME_RETIRED:
            continue
        ended = L.parse(c.ended_utc)
        if ended is not None and now - ended <= window:
            out.append(c)
    return out


# ---- user specs: distance -----------------------------------------------------------------------------

def user_near_duplicate(a: Mapping, b: Mapping) -> bool:
    """The same idea? sports, markets, side rule equal; price band ends within 0.10 decimal odds;
    min_books and max_bets_per_day within 1 (prereg section 3, rule 8)."""
    if list(a["sports"]) != list(b["sports"]) or list(a["markets"]) != list(b["markets"]):
        return False
    if a["side_rule"] != b["side_rule"]:
        return False
    for key in ("price_min", "price_max"):
        if abs(user_spec.price_decimal(a[key]) - user_spec.price_decimal(b[key])) > rules.NEAR_PRICE_DECIMAL + 1e-9:
            return False
    return (abs(a["min_books"] - b["min_books"]) <= rules.NEAR_COUNT
            and abs(a["max_bets_per_day"] - b["max_bets_per_day"]) <= rules.NEAR_COUNT)


def user_frozen_problems(old: Mapping, new: Mapping) -> list:
    out = []
    if new["lock_minutes"] != old["lock_minutes"]:
        out.append("lock_minutes cannot change in a challenger (the pair must lock at the same instant)")
    return out


def user_spec_diff(old: Mapping, new: Mapping) -> dict:
    return {k: [old[k], new[k]] for k in user_spec.RULE_FIELDS if old[k] != new[k]}


# ---- the two doors ------------------------------------------------------------------------------------

def _make(scope: L.Scope, *, kind: str, hound_id: str, lineage_key: str, category: str,
          parent_version: int, parent_ref: Optional[str], spec: dict, spec_hash: str, spec_diff: dict,
          hypothesis: str, evidence: list, now: datetime, proposed_by: str) -> L.Challenger:
    stamp = L.iso(now)
    cid = L.challenger_id_for(scope.name, hound_id, spec_hash, stamp)
    L.log_for(scope).append(
        L.K_PROPOSAL, now=now, scope=scope.name, challenger_id=cid, hound_kind=kind,
        hound_id=hound_id, lineage_key=lineage_key, category=category, parent_version=parent_version,
        parent_ref=parent_ref, spec=spec, spec_hash=spec_hash, spec_diff=spec_diff,
        hypothesis=hypothesis, evidence=evidence, proposed_by=proposed_by)
    return L.read_state(scope).challengers[cid]


def propose_user(scope: L.Scope, hound: Mapping, new_spec: Mapping, hypothesis: Any, evidence: Any,
                 *, graded: int, coach_on: bool = True, now: Optional[datetime] = None,
                 proposed_by: str = "coach") -> L.Challenger:
    """A challenger for a user hound. ``new_spec`` is ALREADY validated by ``user_spec.validate_spec``
    and by the coach's narrowing check; this adds the loop's own guards and records the proposal."""
    now = now or L.utc_now()
    lineage = hound["root_id"]
    try:
        _switch_guard(scope, coach_on=coach_on)
        state = L.read_state(scope)
        _record_and_rate_guard(state, graded=graded, lineage_key=lineage, now=now)
        _caps_guard(state, lineage_key=lineage)
        text = clean_text(hypothesis, "hypothesis", rules.HYPOTHESIS_MIN, rules.HYPOTHESIS_MAX)
        refs = clean_evidence(evidence)
        problems = user_frozen_problems(hound["spec"], new_spec)
        if problems:
            raise ProposalError("frozen_field", "; ".join(problems))
        if user_spec.spec_hash(new_spec) == hound["spec_hash"] or user_near_duplicate(hound["spec"], new_spec):
            raise ProposalError("near_duplicate", "this is the champion's own rule, or too close to it, "
                                "to be a challenger", 409)
        for c in state.live():
            if c.lineage_key == lineage and user_near_duplicate(c.spec, new_spec):
                raise ProposalError("near_duplicate", f"too close to the live challenger {c.id}", 409)
        for c in retired_recent(state, lineage, now):
            if user_near_duplicate(c.spec, new_spec):
                raise ProposalError(
                    "retired_repeat", f"too close to challenger {c.id}, retired {c.ended_utc[:10]} "
                    f"({c.outcome_reason}); a failed idea is not tried again for "
                    f"{rules.DEDUPE_DAYS} days", 409)
    except ProposalError as exc:
        _record_refusal(scope, exc, hound_id=hound["id"], lineage_key=lineage, now=now,
                        proposed_by=proposed_by)
        raise
    return _make(scope, kind="user", hound_id=hound["id"], lineage_key=lineage,
                 category="mixed", parent_version=int(hound.get("version_no") or 1),
                 parent_ref=hound["id"], spec=dict(new_spec), spec_hash=user_spec.spec_hash(new_spec),
                 spec_diff=user_spec_diff(hound["spec"], new_spec), hypothesis=text, evidence=refs,
                 now=now, proposed_by=proposed_by)


def record_held(scope: L.Scope, hound: Mapping, *, reason: str, now: Optional[datetime] = None) -> None:
    """A round that kept the champion as it is: it uses the 7-day allowance (the old door's rule)."""
    L.log_for(scope).append(L.K_HELD, now=now or L.utc_now(), scope=scope.name, hound_id=hound["id"],
                            lineage_key=hound["root_id"], reason=str(reason)[:200])


def champion_values_pack(tunable: tunables.TunableHound, state: L.State) -> dict:
    return tunables.full_values(tunable, state.champion_params(tunable.hound_id))


def propose_pack(scope: L.Scope, hound_id: str, params: Any, hypothesis: Any, evidence: Any,
                 *, graded: int, coach_on: bool = True, now: Optional[datetime] = None,
                 proposed_by: str = "coach", tunable_cfg: Optional[Mapping] = None) -> L.Challenger:
    """A challenger for a pack hound: knob values inside the hound's declared menu."""
    now = now or L.utc_now()
    cfg = tunable_cfg if tunable_cfg is not None else tunables.load()
    try:
        _switch_guard(scope, coach_on=coach_on)
        tun = cfg.get(hound_id)
        if tun is None:
            raise ProposalError("not_tunable", f"{hound_id} declares no tunable knobs", 422)
        state = L.read_state(scope)
        _record_and_rate_guard(state, graded=graded, lineage_key=hound_id, now=now)
        _caps_guard(state, lineage_key=hound_id)
        text = clean_text(hypothesis, "hypothesis", rules.HYPOTHESIS_MIN, rules.HYPOTHESIS_MAX)
        refs = clean_evidence(evidence)
        champ = champion_values_pack(tun, state)
        try:
            values = tunables.validate(tun, champ, params)
        except tunables.TunableError as exc:
            raise ProposalError("params_invalid", str(exc), 422)
        if tunables.near_duplicate(tun, champ, values):
            raise ProposalError("near_duplicate", "within one step of the champion on every knob", 409)
        for c in state.live():
            if c.lineage_key == hound_id and tunables.near_duplicate(tun, c.spec.get("values") or {}, values):
                raise ProposalError("near_duplicate", f"too close to the live challenger {c.id}", 409)
        for c in retired_recent(state, hound_id, now):
            if tunables.near_duplicate(tun, c.spec.get("values") or {}, values):
                raise ProposalError(
                    "retired_repeat", f"too close to challenger {c.id}, retired {c.ended_utc[:10]} "
                    f"({c.outcome_reason}); a failed idea is not tried again for "
                    f"{rules.DEDUPE_DAYS} days", 409)
    except ProposalError as exc:
        _record_refusal(scope, exc, hound_id=hound_id, lineage_key=hound_id, now=now,
                        proposed_by=proposed_by)
        raise
    spec = {"values": values, "rule_text": tunables.rule_text(tun, values)}
    return _make(scope, kind="pack", hound_id=hound_id, lineage_key=hound_id, category=tun.category,
                 parent_version=state.champion_version(hound_id), parent_ref=None, spec=spec,
                 spec_hash=tunables.values_hash(values), spec_diff=tunables.diff(champ, values),
                 hypothesis=text, evidence=refs, now=now, proposed_by=proposed_by)


def pack_bets(hound_id: str, version: int, ledger_path) -> list:
    """The pack hound's bets of one champion VERSION (a row without ``hound_version`` is version 1)."""
    from src.hounds import ledgers
    bets, _defs = ledgers.pack_ledger_rows(ledger_path)
    return [b for b in bets if b.hound_id == hound_id and b.hound_version == int(version)]


def pack_graded_count(hound_id: str, version: int, ledger_path) -> int:
    """Forward graded bets of the pack hound's champion version."""
    return sum(1 for b in pack_bets(hound_id, version, ledger_path)
               if b.segment == "forward" and b.graded)
