"""The Gematria Hound as a house-pack hound: the thin adapter between ``pack_run`` and ``src/hounds/gematria``.

Like the AI hounds it is NOT in ``pack.PACK`` (the 21 rule hounds' registry and every replay path stay exactly as they were)
and it is ``forward_only``: it weighs a game once, at the game's lock, from lock-time inputs. The only replay it has is the
diagnostic in ``research/rabbitszn/replay.py``, which writes no bets and is labelled in-sample.

Its config lives beside the AI hounds' in ``config/ai_hounds.json`` (family ``gematria``), so the public race, the hound
page, the sports gate (``ai_defs.resolve_sports``: the whole dog menu) and the bets ledger are the ones the AI hounds already
use. Its bets are graded by ``pack_settle`` exactly like theirs: MLB and NFL from their stores, every other family from the
all-sports scores store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Mapping, Optional

from src.hounds import ai_defs
from src.hounds.gematria import HOUND_ID, CATEGORY, EXPERIMENTAL_LINE
from src.hounds.gematria import runtime as rt
from src.hounds.pack import base

FAMILY = "gematria"


@dataclass
class GematriaSelection(base.Selection):
    """A ``Selection`` carrying the stamps ``pack_run.bet_row`` copies onto the bet row (the evidence, the rules version)."""
    row_extra: dict = field(default_factory=dict)


class GematriaHound(base.Hound):
    forward_only = True
    who_decided = "rule"
    category = CATEGORY
    id = HOUND_ID

    def __init__(self, entry: Mapping, runtime: rt.GematriaRuntime):
        self.runtime = runtime
        self.id = str(entry.get("id") or HOUND_ID)
        self.name = str(entry.get("name") or "Gematria Hound")
        self.tagline = str(entry.get("tagline") or EXPERIMENTAL_LINE)
        self.style = str(entry.get("style") or "numerology")
        self.sports = ai_defs.resolve_sports(entry)
        self.markets = tuple(runtime.rules.decision.markets)
        self.RULE = str(entry.get("rule_text") or "")
        self.band = tuple(runtime.rules.decision.price_band)
        self.max_per_day = int(runtime.rules.decision.max_picks_per_day)
        self.family = FAMILY

    def markets_for(self, sport: str) -> tuple:
        return ai_defs.markets_for_sport(sport, self.markets)

    def accepts(self, ctx: base.Context) -> bool:
        """False once this game has a decision row: it is weighed once, at the lock."""
        return not self.runtime.has_decision(ctx.event_id)

    def pick(self, board: Mapping, ctx: base.Context) -> List[base.Selection]:
        w = self.runtime.weigh(ctx, board)
        row = self.runtime.persist(ctx, w)
        if not w.verdict.is_bet or w.block is None:
            return []
        # ``hound_version`` is the INTEGER the lineage page reads (src/hounds/learning); the readable label is in the evidence block.
        extra = {"gematria": w.block, "rules_version": self.runtime.rules.version,
                 "rules_hash": self.runtime.rules.rules_hash, "hound_version": self.runtime.rules.hound_number,
                 "confidence": w.verdict.confidence, "forward_only": True, "decision_hash": (row or {}).get("row_hash")}
        if ctx.league and ctx.sport not in ("mlb", "nfl"):
            extra["league_title"] = ctx.league
        return [GematriaSelection("moneyline", w.verdict.side, abs(w.verdict.margin), w.verdict.reason, 1.0, row_extra=extra)]
