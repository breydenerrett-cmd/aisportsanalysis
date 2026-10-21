"""The AI hounds: house-pack hounds whose decision is a language model's, asked once per game at the lock.

They are NOT in ``pack.PACK``. The 21 rule hounds are pure functions of (board, context) and can be replayed
over any day; an AI hound makes a paid network call and must never be replayed (``ai_defs`` says why). Keeping
them in their own registry means every existing replay path (the drill, Ask's "earlier today", the coach's
hindsight, the learning loop's shadow) cannot reach one by accident, and the one that could be handed one by
hand (``pack_run.run(replay=True, hounds=[...])``) refuses it by name (``forward_only``).

HOW ONE GAME GOES
-----------------
``pack_run.run`` walks the day's games in lock order and asks each hound in turn. For an AI hound:

  1. ``accepts`` is False when this (hound, game) already has a DECISION row: a model is asked about a game at
     most once, so a pass is final and a restart never asks again.
  2. ``pick`` builds the point-in-time packet (``ai_packet``), asks the router for a strict-JSON answer and
     writes the decision row (bet or pass, with provider, model, latency, cost) to the decision log BEFORE
     anything else, so even a pass the runner never sees is on the record.
  3. A "bet" becomes a ``Selection`` only if the market is on the lock board and the side's average price is in
     the hound's band (never -200 or worse). The runner then applies its own price band, the one-bet-per-game
     rule and the daily cap again, and writes the paper bet with the provider and model on the row.
  4. ANY failure (no key, over a cap, cooling down, timeout, an invalid answer twice) is a PASS with the reason
     in the decision row. Nothing is ever back-filled, retried later or guessed.

THE COUNCIL HOUND asks no model. It reads the answers the model hounds already logged for the same game and
bets only when enough of them returned a valid answer (``min_members``) and a strict majority of those backed
the same side. It exists in the code and the config but is PARKED (``enabled: false``) until a second model is
switched on: with one model there is nothing to take a majority of.

Stdlib plus the repo; no network of its own (the router owns that).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from src.ai import decision as decision_mod
from src.ai.router import Router
from src.hounds import ai_defs, ai_packet
from src.hounds.pack import base

MARKET_ORDER = ("moneyline", "spread", "total")      # a tie between agreeing markets goes to the earlier one
KIND_DECISION = "ai_decision"
ATTEMPT_DETAIL_CHARS = 160


@dataclass
class AISelection(base.Selection):
    """A ``Selection`` that carries the stamps ``pack_run.bet_row`` copies onto the bet row (provider, model,
    confidence, the decision row's hash...). A rule hound's Selection has none, so its rows are unchanged."""
    row_extra: dict = field(default_factory=dict)


@dataclass
class Opinion:
    """What one hound said about one game, whatever the outcome."""
    hound_id: str
    event_id: str
    status: str                        # "bet" | "pass" | "failed"
    code: str                          # model_bet | model_pass | outside_band | market_not_on_board | no_answer | council_*
    market: Optional[str] = None
    side: Optional[str] = None
    confidence: Optional[int] = None
    reason: str = ""
    eligible: bool = False             # a bet that can actually be placed (on the board, in the price band)
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    cost_usd: float = 0.0
    detail: str = ""
    decision_hash: Optional[str] = None

    @classmethod
    def from_row(cls, row: Mapping) -> "Opinion":
        status = {"bet": "bet", "pass": "pass"}.get(row.get("decided"), "failed")
        if row.get("code") in ("no_answer", "not_available"):
            status = "failed"
        return cls(hound_id=row["hound_id"], event_id=row["event_id"], status=status, code=str(row.get("code") or ""),
                   market=row.get("market"), side=row.get("side"), confidence=row.get("confidence"),
                   reason=str(row.get("reason") or ""), eligible=bool(row.get("eligible")),
                   provider=row.get("provider"), model=row.get("model"), latency_ms=row.get("latency_ms"),
                   cost_usd=float(row.get("cost_usd") or 0.0), detail=str(row.get("detail") or ""),
                   decision_hash=row.get("row_hash"))


# ---------------------------------------------------------------------------
# the council (pure)
# ---------------------------------------------------------------------------

def council_decision(opinions: Sequence[Opinion], min_members: int) -> Opinion:
    """The council's own opinion from its members' (unlabelled; ``hound_id``/``event_id`` are filled by the
    caller). A member counts only if it returned a VALID answer (bet or pass); one that failed is not counted
    for or against. Bets only when ``min_members`` or more counted and a strict majority of the counted
    backed the same side."""
    counted = [o for o in opinions if o.status in ("bet", "pass")]
    base_op = Opinion(hound_id="", event_id="", status="pass", code="council_quorum", provider="council")
    if len(counted) < min_members:
        base_op.detail = f"{len(counted)} valid answers, need {min_members}"
        return base_op
    backers = [o for o in counted if o.status == "bet" and o.eligible and o.side and o.market]
    votes = Counter(o.side for o in backers)
    if not votes:
        base_op.code, base_op.detail = "council_no_majority", f"0 of {len(counted)} backed a bet"
        return base_op
    side, n = votes.most_common(1)[0]
    if n * 2 <= len(counted):
        base_op.code, base_op.detail = "council_no_majority", f"best side had {n} of {len(counted)}"
        return base_op
    agreeing = [o for o in backers if o.side == side]
    markets = Counter(o.market for o in agreeing)
    top = max(markets.values())
    market = next(m for m in MARKET_ORDER if markets.get(m) == top)
    chosen = [o for o in agreeing if o.market == market]
    confidence = max(1, min(5, round(sum(int(o.confidence or 1) for o in agreeing) / len(agreeing))))
    base_op.status, base_op.code, base_op.eligible = "bet", "council_majority", True
    base_op.market, base_op.side, base_op.confidence = market, side, confidence
    base_op.model = ",".join(sorted({str(o.model) for o in agreeing if o.model}))
    base_op.reason = f"{n} of {len(counted)} models back the {side} side; {len(chosen)} chose the {market}."
    base_op.detail = f"members: {','.join(sorted(o.hound_id for o in counted))}"
    return base_op


# ---------------------------------------------------------------------------
# the runtime shared by every AI hound in a pass
# ---------------------------------------------------------------------------

class AIRuntime:
    """Everything an AI hound needs that a rule hound does not: the router, the decision log, the stores for
    this pass, an optional news source. One per pass; ``bind`` gives it the stores the runner loaded."""

    def __init__(self, router: Router, decisions_ledger, *, now_fn: Optional[Callable[[], datetime]] = None,
                 news_fn=None, min_council_members: int = 3):
        self.router = router
        self.ledger = decisions_ledger
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.news_fn = news_fn
        self.min_council_members = min_council_members
        self.stores: Optional[base.Stores] = None
        self.members: List[str] = []                     # model hound ids, in registry order (the council reads these)
        self.decided: Dict[tuple, dict] = {}
        for row in self.ledger.iter_rows():
            if row.get("kind") == KIND_DECISION:
                self.decided[(row["hound_id"], row["event_id"])] = row

    def bind(self, stores: base.Stores) -> "AIRuntime":
        self.stores = stores
        return self

    def has_decision(self, hound_id: str, event_id: str) -> bool:
        return (hound_id, event_id) in self.decided

    # -- persistence ----------------------------------------------------------

    def persist(self, op: Opinion, ctx: base.Context, *, packet_hash: Optional[str] = None,
                attempts: Sequence = ()) -> Opinion:
        row = {
            "kind": KIND_DECISION, "pack": ai_defs.PACK_ID, "segment": "forward", "hound_id": op.hound_id,
            "event_id": op.event_id, "date": ctx.date, "sport": ctx.sport, "away": ctx.away_name, "home": ctx.home_name,
            "start_utc": base.iso(ctx.start), "lock_utc": base.iso(ctx.lock),
            "decided": "bet" if op.status == "bet" else "pass", "code": op.code, "eligible": op.eligible,
            "market": op.market, "side": op.side, "confidence": op.confidence, "reason": op.reason,
            "provider": op.provider, "model": op.model, "latency_ms": op.latency_ms, "cost_usd": op.cost_usd,
            "prompt_version": decision_mod.PROMPT_VERSION, "packet_hash": packet_hash, "detail": op.detail,
            "attempts": [{"provider": a.provider, "status": a.status, "detail": (a.detail or "")[:ATTEMPT_DETAIL_CHARS]}
                         for a in attempts],
            "written_utc": base.iso(self.now_fn()),
        }
        written = self.ledger.append(row)
        op.decision_hash = written["row_hash"]
        self.decided[(op.hound_id, op.event_id)] = written
        return op

    # -- asking ---------------------------------------------------------------

    def opinion(self, hound: "AIHound", board: Mapping, ctx: base.Context) -> Opinion:
        memo = ctx.cache.setdefault("ai_opinions", {})
        if hound.id in memo:
            return memo[hound.id]
        prior = self.decided.get((hound.id, ctx.event_id))
        op = Opinion.from_row(prior) if prior else self._ask(hound, board, ctx)
        memo[hound.id] = op
        return op

    def _ask(self, hound: "AIHound", board: Mapping, ctx: base.Context) -> Opinion:
        quotes = (self.stores.quotes_by_event.get(ctx.event_id) if self.stores else None) or []
        packet = ai_packet.build_packet(ctx, board, quotes, news_fn=self.news_fn)
        system, user = ai_packet.render_prompt(packet)
        ans = self.router.ask(system, user, schema=decision_mod.DECISION_SCHEMA, validator=decision_mod.check_decision,
                              providers=hound.providers or None, purpose=f"{hound.id}:{ctx.event_id}")
        digest = ai_packet.packet_hash(packet)
        op = Opinion(hound_id=hound.id, event_id=ctx.event_id, status="failed", code="no_answer",
                     provider=ans.provider, model=ans.model, latency_ms=ans.latency_ms, cost_usd=ans.cost_usd,
                     detail=ans.reason)
        if ans.ok and ans.output:
            out = ans.output
            op.market, op.side, op.confidence, op.reason = out.get("market"), out.get("side"), out["confidence"], out["reason"]
            op.detail = ""
            if out["decision"] == "pass":
                op.status, op.code = "pass", "model_pass"
            else:
                info = base.side_info(board, out["market"], out["side"])
                if info is None:
                    op.status, op.code = "pass", "market_not_on_board"
                    op.detail = f"the model chose {out['market']} {out['side']}, which is not on the lock board"
                elif not hound.price_ok(info["price_average"]):
                    op.status, op.code = "pass", "outside_band"
                    op.detail = f"average price {info['price_average']} is outside the allowed band (never -200 or worse)"
                else:
                    op.status, op.code, op.eligible = "bet", "model_bet", True
        return self.persist(op, ctx, packet_hash=digest, attempts=ans.attempts)

    def member_opinions(self, ctx: base.Context) -> List[Opinion]:
        """The model hounds' logged answers for this game (from this pass's memo, else the decision log)."""
        memo = ctx.cache.get("ai_opinions", {})
        out = []
        for hid in self.members:
            op = memo.get(hid)
            if op is None:
                row = self.decided.get((hid, ctx.event_id))
                op = Opinion.from_row(row) if row else None
            if op is not None:
                out.append(op)
        return out


# ---------------------------------------------------------------------------
# the hounds
# ---------------------------------------------------------------------------

class AIHound(base.Hound):
    """One model hound, built from an entry in ``config/ai_hounds.json``."""

    forward_only = True
    who_decided = "model"
    category = ai_defs.CATEGORY

    def __init__(self, entry: Mapping, runtime: AIRuntime):
        self.runtime = runtime
        self.id = str(entry["id"])
        self.name = str(entry.get("name") or self.id)
        self.tagline = str(entry.get("tagline") or "")
        self.style = str(entry.get("style") or "")
        self.sports = tuple(entry.get("sports") or ("mlb", "nfl"))
        self.markets = tuple(entry.get("markets") or base.MARKETS)
        self.RULE = str(entry.get("rule_text") or "")
        lo, hi = entry.get("price_band") or (base.PRICE_MIN, base.PRICE_MAX)
        self.band = (int(lo), int(hi))
        self.providers = list(entry.get("providers") or [])
        self.family = str(entry.get("family") or "")

    def price_ok(self, price: int) -> bool:
        from src.hounds import pack_run

        return pack_run.in_band(self, price)

    def accepts(self, ctx: base.Context) -> bool:
        return not self.runtime.has_decision(self.id, ctx.event_id)

    def pick(self, board: Mapping, ctx: base.Context) -> List[base.Selection]:
        op = self.runtime.opinion(self, board, ctx)
        return self._selection(op)

    def _selection(self, op: Opinion) -> List[base.Selection]:
        if op.status != "bet" or not op.eligible:
            return []
        extra = {"ai_hound": True, "provider": op.provider, "model": op.model, "confidence": op.confidence,
                 "latency_ms": op.latency_ms, "cost_usd": op.cost_usd, "prompt_version": decision_mod.PROMPT_VERSION,
                 "decision_hash": op.decision_hash, "forward_only": True}
        return [AISelection(op.market, op.side, float(op.confidence or 1), op.reason, 1.0, row_extra=extra)]


class CouncilHound(AIHound):
    """Bets only on a strict majority of the model hounds' valid answers (see ``council_decision``)."""

    def pick(self, board: Mapping, ctx: base.Context) -> List[base.Selection]:
        memo = ctx.cache.setdefault("ai_opinions", {})
        if self.id in memo:
            return self._selection(memo[self.id])
        op = council_decision(self.runtime.member_opinions(ctx), self.runtime.min_council_members)
        op.hound_id, op.event_id = self.id, ctx.event_id
        if op.status == "bet":
            info = base.side_info(board, op.market, op.side)
            if info is None:
                op.status, op.code, op.eligible, op.detail = "pass", "market_not_on_board", False, "the majority's market is not on the lock board"
            elif not self.price_ok(info["price_average"]):
                op.status, op.code, op.eligible, op.detail = "pass", "outside_band", False, f"average price {info['price_average']} is outside the allowed band"
        self.runtime.persist(op, ctx)
        memo[self.id] = op
        return self._selection(op)


def build_hounds(runtime: AIRuntime, config_path=None) -> tuple:
    """The running AI hounds, model hounds first and the council (if enabled) last, so its members' answers
    exist by the time it reads them. A parked entry (``enabled: false``) is not built."""
    entries = ai_defs.entries(config_path)
    cfg = ai_defs.load_config(config_path)
    runtime.min_council_members = int((cfg.get("council") or {}).get("min_members", runtime.min_council_members))
    models = [AIHound(e, runtime) for e in entries if e.get("family") != "council"]
    councils = [CouncilHound(e, runtime) for e in entries if e.get("family") == "council"]
    runtime.members = [h.id for h in models]
    return tuple(models + councils)
