"""Glue between the pack runner and the signal engine: build a game's inputs at the lock, decide, and keep the decision log.

THE KILL SWITCH. ``GEMATRIA_HOUND=off`` (also ``0``/``false``/``no``) removes the hound from every pass; anything else, or
nothing, leaves it ON. That is the default in code. Whether the API process's loop is running at all is the owner's call:
the loop starts when ``AI_HOUNDS=on`` or ``GEMATRIA_HOUND=on`` is set explicitly (``ai_runner.start_loop``), so a laptop, a
test client and staging never start it by accident.

THE DECISION LOG (``gematria_decisions_v1.jsonl``, hash-chained, beside the AI bets ledger) holds one row per game the hound
actually weighed, bet or pass, with both scores, the margin, the search size and the rules stamp. A game is weighed once:
the inputs are fixed at the lock, so asking again could only give the same answer. Games it cannot weigh at all (no stored
results for the sport, an unknown team, no board yet) are NOT logged: they are not decisions, and logging every tennis match
every fifteen minutes would bury the ones that are.

NO POST-LOCK INFORMATION. The history is cut at ``ctx.lock - FINISH_LAG`` (``history.Disk``), the board is the lock board
(``base.lock_board``), and the runner refuses a forward bet at or after the start. Nothing here reads a clock to decide
anything; ``now_fn`` only stamps the row.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional

from src.hounds.gematria import HOUND_ID, decision as decision_mod
from src.hounds.gematria import facts as facts_mod
from src.hounds.gematria import history, rules as rules_mod
from src.hounds.gematria import signals as sig_mod
from src.hounds.pack import base

ENV_FLAG = "GEMATRIA_HOUND"
OFF_VALUES = ("off", "0", "false", "no")
ON_VALUES = ("on", "1", "true", "yes")
KIND_DECISION = "gematria_decision"
DECISIONS_NAME = "gematria_decisions_v1.jsonl"


def enabled(env: Optional[Mapping] = None) -> bool:
    """ON unless ``GEMATRIA_HOUND`` is explicitly off."""
    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "").strip().lower() not in OFF_VALUES


def explicitly_on(env: Optional[Mapping] = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "").strip().lower() in ON_VALUES


def decisions_path(ledger_file: str) -> str:
    """The decision log sits beside the bets ledger it belongs to (the Fly volume in production)."""
    return str(Path(ledger_file).parent / DECISIONS_NAME)


def _inputs_hash(g: sig_mod.GameInputs) -> str:
    """A fingerprint of what the generator read, so a stored decision can be checked against a recomputation."""
    def team(t: sig_mod.TeamInputs) -> dict:
        s = t.state
        return {"texts": t.team.texts, "state_order": t.team.state_order,
                "anchors": [(a.what, a.date, a.precision) for a in t.team.anchors],
                "state": None if s is None else s.__dict__}

    body = {"date": g.date, "home": team(g.home), "away": team(g.away),
            "series": None if g.series is None else g.series.__dict__, "history": g.history_available}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


class Weighed:
    """One game's full result: the verdict, the signals and the evidence block that goes on a bet row."""

    def __init__(self, verdict: decision_mod.Verdict, signals: Optional[sig_mod.Signals], block: Optional[dict]):
        self.verdict, self.signals, self.block = verdict, signals, block


class GematriaRuntime:
    def __init__(self, *, rules: Optional[rules_mod.Rules] = None, facts: Optional[facts_mod.FactsBook] = None,
                 source=None, ledger=None, now_fn: Optional[Callable[[], datetime]] = None):
        self.rules = rules or rules_mod.load()
        self.facts = facts or facts_mod.load()
        self.source = source or history.Disk(canonical=self.facts.canonical_name)
        self.ledger = ledger                                   # a HashChainLedger, or None (a replay writes nothing)
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.decided: Dict[str, dict] = {}
        if ledger is not None:
            for row in ledger.iter_rows():
                if row.get("kind") == KIND_DECISION and row.get("hound_id") == HOUND_ID:
                    self.decided[row["event_id"]] = row

    # -- inputs -----------------------------------------------------------------------------------

    def inputs(self, ctx: base.Context) -> sig_mod.GameInputs:
        past = self.source.past(ctx)
        home_t = self.facts.team(ctx.sport, ctx.home_name)
        away_t = self.facts.team(ctx.sport, ctx.away_name)
        home_in, away_in = sig_mod.TeamInputs(home_t), sig_mod.TeamInputs(away_t)
        series = None
        if past.available and past.home_id and past.away_id:
            home_in.state = history.team_state(past.games, past.home_id)
            away_in.state = history.team_state(past.games, past.away_id)
            series = history.head_to_head(past.games, past.home_id, past.away_id)
        return sig_mod.GameInputs(date=ctx.date, home=home_in, away=away_in, series=series,
                                  history_available=past.available, scope=past.scope)

    # -- weighing ---------------------------------------------------------------------------------

    def weigh(self, ctx: base.Context, board: Mapping) -> Weighed:
        g = self.inputs(ctx)
        known = bool(g.home.team.known and g.away.team.known)
        sig = sig_mod.generate(g, self.rules) if (g.history_available and known) else None
        verdict = decision_mod.decide(sig, board, self.rules, history_available=g.history_available, teams_known=known)
        block = None
        if sig is not None:
            n = self.rules.evidence_top_n
            block = {
                "rules_version": self.rules.version, "rules_hash": self.rules.rules_hash,
                "hound_version": self.rules.hound_version,
                "teams": {"home": ctx.home_name, "away": ctx.away_name},
                "scores": {"home": sig.home.score, "away": sig.away.score}, "margin": verdict.margin,
                "threshold": self.rules.decision.min_margin,
                "comparisons": {"home": sig.home.comparisons, "away": sig.away.comparisons},
                "search_space": sig.home.comparisons + sig.away.comparisons,
                "milestones": {"home": sig.home.milestones, "away": sig.away.milestones},
                "matches": {"home": len(sig.home.evidence), "away": len(sig.away.evidence)},
                "kind_counts": {"home": sig.home.kind_counts(), "away": sig.away.kind_counts()},
                "evidence": {"home": [e.to_dict() for e in sig.home.evidence[:n]],
                             "away": [e.to_dict() for e in sig.away.evidence[:n]]},
                "price": verdict.price, "side": verdict.side, "confidence": verdict.confidence, "history": g.scope,
                "inputs_hash": _inputs_hash(g),
            }
        return Weighed(verdict, sig, block)

    # -- the log ------------------------------------------------------------------------------------

    def has_decision(self, event_id: str) -> bool:
        return event_id in self.decided

    def persist(self, ctx: base.Context, w: Weighed) -> Optional[dict]:
        """Log a weighed game once. Games that were never decidable are not logged (``decision.NEVER_LOGGED``)."""
        if self.ledger is None or w.verdict.code in decision_mod.NEVER_LOGGED or ctx.event_id in self.decided:
            return self.decided.get(ctx.event_id)
        b = w.block or {}
        row = {
            "kind": KIND_DECISION, "hound_id": HOUND_ID, "event_id": ctx.event_id, "date": ctx.date, "sport": ctx.sport,
            "away": ctx.away_name, "home": ctx.home_name, "start_utc": base.iso(ctx.start), "lock_utc": base.iso(ctx.lock),
            "decided": "bet" if w.verdict.is_bet else "pass", "code": w.verdict.code, "reason": w.verdict.reason,
            "side": w.verdict.side, "price": w.verdict.price, "scores": b.get("scores"), "margin": w.verdict.margin,
            "comparisons": b.get("comparisons"), "milestones": b.get("milestones"),
            "rules_version": self.rules.version, "rules_hash": self.rules.rules_hash,
            "hound_version": self.rules.hound_version, "inputs_hash": b.get("inputs_hash"),
            "written_utc": base.iso(self.now_fn()),
        }
        written = self.ledger.append(row)
        self.decided[ctx.event_id] = written
        return written
