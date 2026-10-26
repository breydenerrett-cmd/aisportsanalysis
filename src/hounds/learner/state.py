"""What the Learner proposed, what the owner applied, what the owner vetoed: one append-only, hash-chained log.

A PROPOSAL IS NEVER AN APPLY. ``learn.propose`` may append a ``learner_proposal`` row; only ``apply`` (an owner action, with the
card's ``basis``) appends the ``learner_applied`` row that changes how the hound bets. That is the Apprentice's review-then-apply
shape (``src/hounds/apprentice/learning.py``): the card carries a ``basis``, the apply recomputes nothing the owner has not seen,
and a card drawn against rules that have since changed is refused as stale.

THE RULES. The Learner starts with none (version 0: explore everything inside its price band). An applied proposal is a FOCUS:
a short list of segments (``features.segment_of``). From then on most of its bets are drawn from the focus and a fixed share
stays exploration, so it keeps collecting the evidence a later proposal needs and a lucky segment can be dropped again.

The log sits beside the bets ledger (the Fly volume in production, the same reason ``ai_defs.ledger_path`` gives).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

from src.ledger.chain import HashChainLedger

EVENTS_NAME = "learner_events_v1.jsonl"
KIND_PROPOSAL = "learner_proposal"
KIND_APPLIED = "learner_applied"
KIND_VETOED = "learner_vetoed"
MAX_FOCUS_SEGMENTS = 3


class StateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def events_path(ledger_file: str) -> str:
    return str(Path(ledger_file).parent / EVENTS_NAME)


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fold(rows: Sequence[Mapping]) -> dict:
    """``{version, focus, pending, proposals}`` from the events, in order. ``pending`` is the newest proposal that has been
    neither applied nor vetoed, and only if it was drawn against the rules version now in force."""
    version, focus = 0, []
    proposals: dict = {}
    closed: set = set()
    for r in rows:
        kind = r.get("kind")
        if kind == KIND_PROPOSAL:
            proposals[r["proposal_id"]] = r
        elif kind == KIND_APPLIED:
            closed.add(r["proposal_id"])
            version, focus = int(r["version"]), [tuple(s) for s in r["segments"]]
        elif kind == KIND_VETOED:
            closed.add(r["proposal_id"])
    pending = [p for pid, p in proposals.items() if pid not in closed and int(p["rules_version"]) == version]
    return {"version": version, "focus": focus, "pending": pending[-1] if pending else None, "proposals": proposals}


def read(path: str) -> dict:
    return fold(HashChainLedger(path).read())


def record_proposal(path: str, card: Mapping, *, now: Optional[datetime] = None) -> dict:
    """Append the card as a proposal. Refused if the card proposes nothing: an empty card is a message, not a record."""
    if card.get("nothing") or not card.get("segments"):
        raise StateError("nothing_to_record", "A card that proposes nothing is not recorded.")
    row = {"kind": KIND_PROPOSAL, "proposal_id": card["proposal_id"], "basis": card["basis"],
           "rules_version": card["rules_version"], "cutoff": card["cutoff"], "as_of": card["as_of"],
           "segments": [list(s) for s in card["segments"]], "card": dict(card), "written_utc": _now_iso(now)}
    return HashChainLedger(path).append(row)


def apply(path: str, proposal_id: str, basis: str, *, actor: str, now: Optional[datetime] = None) -> dict:
    """Make a pending proposal the Learner's focus. The caller must send the card's ``basis``; a proposal that is unknown,
    already closed, drawn against older rules or whose basis differs is refused. Never called by the learn step."""
    state = read(path)
    prop = state["proposals"].get(proposal_id)
    if prop is None:
        raise StateError("not_found", "No such proposal.")
    if prop["basis"] != basis:
        raise StateError("basis_mismatch", "That is not the card you were shown. Open the proposal again.")
    if state["pending"] is None or state["pending"]["proposal_id"] != proposal_id:
        raise StateError("proposal_stale", "That proposal is out of date or already decided. Open the current one.")
    segments = [tuple(s) for s in prop["segments"]][:MAX_FOCUS_SEGMENTS]
    row = {"kind": KIND_APPLIED, "proposal_id": proposal_id, "basis": basis, "version": state["version"] + 1,
           "segments": [list(s) for s in segments], "actor": actor, "written_utc": _now_iso(now)}
    return HashChainLedger(path).append(row)


def veto(path: str, proposal_id: str, *, actor: str, now: Optional[datetime] = None) -> dict:
    state = read(path)
    if proposal_id not in state["proposals"]:
        raise StateError("not_found", "No such proposal.")
    row = {"kind": KIND_VETOED, "proposal_id": proposal_id, "actor": actor, "written_utc": _now_iso(now)}
    return HashChainLedger(path).append(row)
