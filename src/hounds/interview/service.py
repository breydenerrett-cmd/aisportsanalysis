"""The operations the API calls. No FastAPI here: the routes are thin, and this runs in the no-FastAPI test harness.

  start     open an interview (a free account already at its dog limit gets the upgrade refusal here, before any
            assistant money is spent, and again at `confirm`, inside the creating transaction)
  show      the current state of an interview for its owner
  answer    one topic's answer (re-answering a topic replaces it)
  resolve   one clarification option
  review    the confirmation screen: plain-English summary, can't-automate list, hash. Saves nothing.
  confirm   the person said yes: create the hound through `user_store.create_hound`, write the strategy record and any
            claimed history, close the interview. Confirming twice returns the same record and makes no second hound.

Every function takes the clock, the database and (for answers) the router as arguments, so a test fakes all three.
Ownership is checked on every call: another account's interview id reads exactly like a missing one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from src.hounds import user_defs, user_spec, user_store
from src.hounds.interview import derive as D
from src.hounds.interview import extract as X
from src.hounds.interview import machine as M
from src.hounds.interview import record as REC
from src.hounds.interview import store as S
from src.hounds.interview.machine import InterviewError


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def active_dogs(user_id: int, *, db: Optional[Path] = None) -> int:
    """Dogs the free tier counts: everything not retired or buried (running and benched)."""
    return sum(1 for h in user_store.list_for_owner(user_id, db=db)
               if h["status"] not in (user_store.STATUS_RETIRED, user_store.STATUS_BURIED))


def check_free_limit(user_id: int, *, free: bool, db: Optional[Path] = None) -> None:
    """The free account's one-dog limit, as the same refusal the create path gives."""
    if free and active_dogs(user_id, db=db) >= user_spec.FREE_MAX_ACTIVE_PER_ACCOUNT:
        raise user_store.StoreError("upgrade_required", user_store.FREE_LIMIT_MESSAGE)


def _load(user_id: int, sid: str, *, db: Optional[Path]) -> dict:
    row = S.get_session(sid, db=db)
    if row is None or row["user_id"] != user_id:
        raise InterviewError("not_found", "That interview was not found.")
    return row


def _present(row: Mapping, extra: Optional[dict] = None, *, edit: Optional[str] = None) -> dict:
    out = {"id": row["id"], **M.view(row["state"], edit), "paper_only": True, "not_advice": user_spec.NOT_ADVICE}
    if extra:
        out.update(extra)
    return out


def _save(row: Mapping, state: dict, now: datetime, *, db: Optional[Path]) -> dict:
    try:
        rev = S.save_session(row["id"], state, row["rev"], now, db=db)
    except S.Conflict:
        raise InterviewError("conflict", "That interview changed in another window. Reload it and try again.")
    return {**row, "state": state, "rev": rev}


def start(user_id: int, *, free: bool, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    check_free_limit(user_id, free=free, db=db)
    moment = _now(now)
    state = M.new_state()
    M.log_next(state)
    row = S.create_session(user_id, state, moment, db=db)
    return _present(row)


def show(user_id: int, sid: str, *, edit: Optional[str] = None, db: Optional[Path] = None) -> dict:
    return _present(_load(user_id, sid, db=db), edit=edit)


def make_reader(router, state: Mapping):
    return X.HaikuReader(router, calls_used=int(state.get("calls", 0))) if router is not None else None


def answer(user_id: int, sid: str, topic_id: str, payload: Mapping, *, router=None, now: Optional[datetime] = None,
           db: Optional[Path] = None) -> dict:
    moment = _now(now)
    row = _load(user_id, sid, db=db)
    state = row["state"]
    M.apply_answer(state, topic_id, dict(payload or {}), reader=make_reader(router, state), today=moment.date())
    row = _save(row, state, moment, db=db)
    return _present(row)


def resolve(user_id: int, sid: str, clarification_id: str, option_id: str, *, now: Optional[datetime] = None,
            db: Optional[Path] = None) -> dict:
    moment = _now(now)
    row = _load(user_id, sid, db=db)
    state = row["state"]
    M.apply_resolution(state, clarification_id, option_id)
    row = _save(row, state, moment, db=db)
    return _present(row)


def _ready(row: Mapping) -> dict:
    derived = D.derive(row["state"])
    if not derived["complete"] or derived["spec"] is None:
        raise InterviewError("not_ready", "The interview is not finished yet.")
    return derived


def _named_spec(derived: Mapping, name: str, tagline: str, user_id: int, *, db: Optional[Path]) -> dict:
    """The spec with the person's name, run through the same validator every form post goes through."""
    raw = {**derived["spec"], "name": name, "tagline": tagline}
    return user_spec.validate_spec(raw, taken_names=user_store.taken_names(db=db))


def review(user_id: int, sid: str, name: str, tagline: str = "", *, now: Optional[datetime] = None,
           db: Optional[Path] = None) -> dict:
    """The confirmation screen. SpecError carries the menu's reasons (a taken or refused name)."""
    moment = _now(now)
    row = _load(user_id, sid, db=db)
    derived = _ready(row)
    spec = _named_spec(derived, (name or "").strip(), (tagline or "").strip(), user_id, db=db)
    out = REC.review(row["state"], derived, spec, record_id="(not saved)", interview_id=row["id"],
                     owner_display=user_defs.owner_display(user_id), today=moment.date())
    out["id"] = row["id"]
    return out


def confirm(user_id: int, sid: str, name: str, *, tagline: str = "", freeze_hash: Optional[str] = None,
            acknowledge_unsupported: bool = False, free: bool, now: Optional[datetime] = None, db: Optional[Path] = None) -> dict:
    """Create the hound and write the record. `freeze_hash` is what the person was shown; a different one means the
    answers changed under them, and nothing is saved."""
    moment = _now(now)
    row = _load(user_id, sid, db=db)
    if row["status"] == S.STATUS_CONFIRMED:
        existing = S.record_for_session(sid, db=db)
        if existing is not None:
            return _confirmed(existing, already=True, db=db)
    if row["status"] != S.STATUS_OPEN:
        raise InterviewError("closed", "This interview is finished.")
    derived = _ready(row)
    # a hound that checks nothing would bet every game in its sports; and one that cannot check part of what the person
    # described must be confirmed knowing that. Both are enforced here, not only on the page.
    if not REC.has_condition(derived):
        raise InterviewError("nothing_checkable", REC.NOTHING_CHECKABLE)
    if derived["cant_automate"] and acknowledge_unsupported is not True:
        raise InterviewError("acknowledge_required", REC.ACK_REQUIRED)
    spec = _named_spec(derived, (name or "").strip(), (tagline or "").strip(), user_id, db=db)
    shown = REC.review(row["state"], derived, spec, record_id="(not saved)", interview_id=sid,
                       owner_display=user_defs.owner_display(user_id), today=moment.date())
    if freeze_hash is not None and freeze_hash != shown["freeze_hash"]:
        raise InterviewError("changed", "The strategy changed since you reviewed it. Review it again before confirming.")
    # the existing create path: the free limit is applied inside its transaction (StoreError upgrade_required)
    try:
        hound = user_store.create_hound(user_id, spec, free_tier=free, now=moment, db=db)
    except user_store.StoreError:
        # a second tap that lost the race: the first one may already have made the hound and closed the interview
        existing = S.record_for_session(sid, db=db)
        if existing is not None:
            return _confirmed(existing, already=True, db=db)
        raise
    record = REC.build_record(row["state"], derived, hound["spec"], record_id=S.new_record_id(), interview_id=sid,
                              owner_display=user_defs.owner_display(user_id), status=REC.STATUS_SHADOW,
                              effective_date=moment.date())
    state = row["state"]
    state["status"] = "confirmed"
    hist = (state["answers"].get("history") or {}).get("history")
    try:
        S.confirm_session(sid, row["rev"], state, record=record, hound_id=hound["id"], user_id=user_id, now=moment,
                          history_rows=hist["rows"] if hist else None, history_rejected=hist["rejected"] if hist else None, db=db)
    except Exception as exc:
        # the hound exists but its record could not be written: take the hound back rather than leave one with no record
        try:
            user_store.retire_hound(hound["id"], by="system", reason="interview record could not be saved", now=moment, db=db)
        except Exception:  # noqa: BLE001 -- the original failure is the one to report
            pass
        if isinstance(exc, S.Conflict):
            # two confirms at once: the other one won. Hand back what it made, or say so plainly.
            existing = S.record_for_session(sid, db=db)
            if existing is not None:
                return _confirmed(existing, already=True, db=db)
            raise InterviewError("conflict", "That interview changed in another window. Reload it and try again.")
        raise
    return _confirmed(S.get_record(record["id"], db=db), hound=hound, already=False, db=db)


def _confirmed(stored: Mapping, *, hound: Optional[Mapping] = None, already: bool, db: Optional[Path]) -> dict:
    record = stored["record"]
    hist = S.claimed_history(stored["id"], db=db)
    return {"record": record, "record_id": stored["id"], "hound_id": stored["hound_id"], "hound": hound,
            "already": already, "freeze_hash": record["freeze_hash"],
            "claimed_history": {k: hist[k] for k in ("label", "summary")} if hist else None,
            "summary": REC.summary_lines(record), "cant_automate": record["cant_automate"],
            "paper_only": True, "not_advice": user_spec.NOT_ADVICE}


def record_view(user_id: int, record_id: str, *, db: Optional[Path] = None) -> dict:
    """A confirmed record for its owner, with any claimed history under its own label and never merged into a record."""
    stored = S.get_record(record_id, db=db)
    if stored is None or stored["user_id"] != user_id:
        raise InterviewError("not_found", "That strategy record was not found.")
    hist = S.claimed_history(record_id, db=db)
    return {"record": stored["record"], "hound_id": stored["hound_id"], "claimed_history": hist,
            "paper_only": True, "not_advice": user_spec.NOT_ADVICE}
