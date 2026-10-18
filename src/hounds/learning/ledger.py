"""Where a scope's ledgers live, the hash-chained event log, and the state folded from it.

EVERYTHING IS AN EVENT, STATE IS A FOLD
----------------------------------------
The loop keeps no mutable table. A proposal, a refusal, a look, a decision, a promotion, a daily
scorecard, a pause and a resume are each one appended row of a hash-chained JSONL file
(``HashChainLedger``: any edited or deleted row breaks every hash after it). What a challenger
"is" right now (live, promoted, retired), who the champion of a hound is, which proposals were
refused: all of it is ``fold(events)``, a pure function, so the state can be rebuilt on any machine
and a test can build one from a list of rows.

SCOPES (docs/PREREG_LEARNING_LOOP.md section 14)
------------------------------------------------
``house`` (pack hounds and the analyst prompt arm) keeps its ledgers in ``evidence/`` in the
repository. ``user`` (user-built hounds) keeps its ledgers beside the app database, on the API's
persistent volume, where the user hound ledger already lives. The two never write each other's
files. A ``Scope`` is just the four paths; tests build one over a temp directory.

NOTHING HERE DECIDES ANYTHING. It records, folds and verifies.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from src.hounds.learning import rules
from src.ledger.chain import HashChainLedger

LEDGER_VERSION = 1

# event kinds
K_PROPOSAL = "proposal"
K_REFUSED = "proposal_refused"
K_HELD = "round_held"
K_LOOK = "look"
K_DECISION = "decision"
K_PROMOTION = "promotion"
K_APPLIED = "promotion_applied"
K_SCORECARD = "scorecard"
K_PAUSE = "pause"
K_RESUME = "resume"
K_UNDO = "undo"

HOUSE_EVENTS = "hounds_learning_v1.jsonl"
HOUSE_BETS = "hounds_challengers_v1.jsonl"
HOUSE_LESSONS = "hounds_lessons_v1.jsonl"
USER_EVENTS = "hounds_learning_user_v1.jsonl"
USER_BETS = "hounds_challengers_user_v1.jsonl"
USER_LESSONS = "hounds_lessons_user_v1.jsonl"
PAUSE_FILE_USER = "hounds_coach_pause.json"


@dataclass(frozen=True)
class Scope:
    name: str
    events: Path
    challenger_bets: Path
    lessons: Path
    pause_file: Optional[Path] = None      # the user scope's pause state, beside the app database

    @staticmethod
    def house(root: Optional[Path] = None) -> "Scope":
        base = Path(root) if root is not None else None
        if base is None:
            from src.paths import evidence_path
            return Scope(rules.SCOPE_HOUSE, evidence_path(HOUSE_EVENTS), evidence_path(HOUSE_BETS),
                         evidence_path(HOUSE_LESSONS))
        return Scope(rules.SCOPE_HOUSE, base / HOUSE_EVENTS, base / HOUSE_BETS, base / HOUSE_LESSONS)

    @staticmethod
    def user(directory: Optional[Path] = None) -> "Scope":
        """Beside the user hound ledger (the app database's directory, or HOUNDS_USER_LEDGER's)."""
        if directory is None:
            from src.hounds import user_engine
            directory = Path(user_engine.ledger_path()).parent
        d = Path(directory)
        return Scope(rules.SCOPE_USER, d / USER_EVENTS, d / USER_BETS, d / USER_LESSONS,
                     d / PAUSE_FILE_USER)


def default_scopes() -> dict:
    return {rules.SCOPE_HOUSE: Scope.house(), rules.SCOPE_USER: Scope.user()}


# ---- time ----------------------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        out = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def month_of(value: Any) -> str:
    return str(value)[:7]


# ---- the log -----------------------------------------------------------------------------------------

class EventLog:
    """A hash-chained JSONL file of events. ``append`` stamps ``kind``, ``ledger_version`` and
    ``utc``; everything else is the caller's."""

    def __init__(self, path):
        self.path = Path(path)
        self._chain = HashChainLedger(self.path)

    def append(self, kind: str, *, now: Optional[datetime] = None, **fields) -> dict:
        row = {"kind": kind, "ledger_version": LEDGER_VERSION, "utc": iso(now or utc_now()),
               "paper_only": True}
        row.update(fields)
        return self._chain.append(row)

    def read(self) -> list:
        return self._chain.read()

    def verify(self):
        return self._chain.verify()


def log_for(scope: Scope) -> EventLog:
    return EventLog(scope.events)


def challenger_id_for(scope_name: str, hound_id: str, spec_hash: str, utc: str) -> str:
    return "c-" + hashlib.sha256(f"{scope_name}|{hound_id}|{spec_hash}|{utc}".encode()).hexdigest()[:10]


# ---- the fold -------------------------------------------------------------------------------------------

@dataclass
class Challenger:
    id: str
    scope: str
    kind: str                           # "user" | "pack" | "analyst"
    hound_id: str                       # the hound the proposal named
    lineage_key: str                    # user: root_id; pack: hound_id
    category: str
    parent_version: int                 # the champion version it was born under
    parent_ref: Optional[str]           # user: the champion's hound id at the time
    spec: dict                          # user: the full spec; pack/analyst: the knob values / prompt id
    spec_hash: str
    spec_diff: dict
    hypothesis: str
    evidence: list
    created_utc: str
    proposed_by: str = "coach"
    status: str = "live"                # live | promoted | retired | undecided
    ended_utc: Optional[str] = None
    outcome_reason: Optional[str] = None
    looks: list = field(default_factory=list)
    decision: Optional[dict] = None

    @property
    def live(self) -> bool:
        return self.status == "live"

    def to_json(self) -> dict:
        return {"id": self.id, "scope": self.scope, "kind": self.kind, "hound_id": self.hound_id,
                "category": self.category, "parent_version": self.parent_version,
                "parent_ref": self.parent_ref, "spec": self.spec, "spec_hash": self.spec_hash,
                "spec_diff": self.spec_diff, "hypothesis": self.hypothesis,
                "evidence": list(self.evidence), "created_utc": self.created_utc,
                "status": self.status, "ended_utc": self.ended_utc,
                "outcome_reason": self.outcome_reason, "looks": list(self.looks),
                "decision": self.decision}


@dataclass
class State:
    challengers: dict = field(default_factory=dict)       # id -> Challenger, proposal order
    refusals: list = field(default_factory=list)
    helds: list = field(default_factory=list)              # round_held rows
    promotions: list = field(default_factory=list)         # promotion rows, with 'applied' resolved
    undos: list = field(default_factory=list)
    scorecards: list = field(default_factory=list)         # the scorecard rows, oldest first
    pauses: list = field(default_factory=list)             # pause / resume rows, oldest first

    # ---- challengers
    def live(self) -> list:
        return [c for c in self.challengers.values() if c.live]

    def live_for(self, hound_id: str) -> list:
        return [c for c in self.live() if c.hound_id == hound_id]

    def for_hound(self, hound_id: str) -> list:
        return [c for c in self.challengers.values() if c.hound_id == hound_id]

    def ended(self, hound_id: Optional[str] = None) -> list:
        return [c for c in self.challengers.values() if not c.live
                and (hound_id is None or c.hound_id == hound_id)]

    # ---- proposals
    def last_allowance_use(self, lineage_key: str) -> Optional[datetime]:
        """The newest accepted proposal or held round of the lineage (what the 7-day rule counts)."""
        stamps = [parse(c.created_utc) for c in self.challengers.values()
                  if c.lineage_key == lineage_key]
        stamps += [parse(r.get("utc")) for r in self.helds if r.get("lineage_key") == lineage_key]
        stamps = [s for s in stamps if s is not None]
        return max(stamps) if stamps else None

    # ---- champions
    def promotions_for(self, hound_id: str) -> list:
        return [p for p in self.promotions if p.get("hound_id") == hound_id]

    def champion_version(self, hound_id: str) -> int:
        promos = self.promotions_for(hound_id)
        return max([int(p["to_version"]) for p in promos], default=1)

    def champion_params(self, hound_id: str) -> dict:
        """The knob values of a pack hound's current champion version ({} = the declared defaults)."""
        promos = sorted(self.promotions_for(hound_id), key=lambda p: int(p["to_version"]))
        return dict(promos[-1].get("params") or {}) if promos else {}

    def last_promotion_utc(self, hound_id: str) -> Optional[datetime]:
        stamps = [parse(p.get("utc")) for p in self.promotions_for(hound_id)]
        stamps = [s for s in stamps if s is not None]
        return max(stamps) if stamps else None

    def promotions_in_month(self, month: str) -> int:
        return sum(1 for p in self.promotions if month_of(p.get("utc")) == month)

    def unapplied_promotions(self) -> list:
        return [p for p in self.promotions if not p.get("applied")]

    # ---- pause
    def paused(self) -> bool:
        return bool(self.pauses) and self.pauses[-1]["kind"] == K_PAUSE

    def last_pause(self) -> Optional[dict]:
        return self.pauses[-1] if self.pauses else None

    def latest_scorecard(self) -> Optional[dict]:
        return self.scorecards[-1] if self.scorecards else None


def fold(events: Iterable[Mapping]) -> State:
    st = State()
    applied: dict = {}
    for ev in events:
        kind = ev.get("kind")
        if kind == K_PROPOSAL:
            c = Challenger(
                id=ev["challenger_id"], scope=ev["scope"], kind=ev["hound_kind"],
                hound_id=ev["hound_id"], lineage_key=ev.get("lineage_key") or ev["hound_id"],
                category=ev.get("category") or "mixed", parent_version=int(ev.get("parent_version") or 1),
                parent_ref=ev.get("parent_ref"), spec=dict(ev.get("spec") or {}),
                spec_hash=ev.get("spec_hash") or "", spec_diff=dict(ev.get("spec_diff") or {}),
                hypothesis=ev.get("hypothesis") or "", evidence=list(ev.get("evidence") or []),
                created_utc=ev["utc"], proposed_by=ev.get("proposed_by") or "coach")
            st.challengers[c.id] = c
        elif kind == K_REFUSED:
            st.refusals.append(dict(ev))
        elif kind == K_HELD:
            st.helds.append(dict(ev))
        elif kind == K_LOOK:
            c = st.challengers.get(ev.get("challenger_id"))
            if c is not None:
                c.looks.append(dict(ev))
        elif kind == K_DECISION:
            c = st.challengers.get(ev.get("challenger_id"))
            if c is not None and c.live:
                c.status = ev["outcome"]
                c.ended_utc = ev["utc"]
                c.outcome_reason = ev.get("reason")
                c.decision = dict(ev)
        elif kind == K_PROMOTION:
            st.promotions.append(dict(ev, applied=bool(ev.get("applied"))))
        elif kind == K_APPLIED:
            applied[ev.get("challenger_id")] = ev
        elif kind == K_UNDO:
            st.undos.append(dict(ev))
        elif kind == K_SCORECARD:
            st.scorecards.append(dict(ev))
        elif kind in (K_PAUSE, K_RESUME):
            st.pauses.append(dict(ev))
    for p in st.promotions:
        hit = applied.get(p.get("challenger_id"))
        if hit is not None:
            p["applied"] = True
            p["new_hound_id"] = hit.get("new_hound_id")
    return st


def read_state(scope: Scope) -> State:
    return fold(log_for(scope).read())


def chain_report(scope: Scope) -> dict:
    """Is every ledger of the scope's chain intact? (a missing file is an empty, valid chain)."""
    out = {}
    for label, path in (("events", scope.events), ("challenger_bets", scope.challenger_bets),
                        ("lessons", scope.lessons)):
        res = HashChainLedger(path).verify()
        out[label] = {"ok": bool(res.ok), "rows": res.rows_checked,
                      "broken_at_line": res.broken_at_line, "reason": res.reason}
    out["ok"] = all(v["ok"] for v in out.values())
    return out
