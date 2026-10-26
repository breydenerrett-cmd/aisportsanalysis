"""The Learner as a house-pack hound: the thin adapter between ``pack_run`` and ``src/hounds/learner``.

Like the Gematria Hound it is NOT in ``pack.PACK`` (the 21 rule hounds and every replay path stay as they were), it shares the
AI hounds' config file (family ``learner``), ledger, sports gate and runner, and it asks no model: no key, no network, no cost.
It is ``forward_only``: its features include how long before the start it was placed, which a replay cannot honestly say.

HOW IT BETS. With no rules it EXPLORES: for each game at the lock it lists every (market, side) on the lock board whose
board-average price is inside its band (never -200 or worse) and takes ONE of them, chosen by a hash of (hound, game), so the same
game always draws the same bet and a rerun appends nothing. One bet per game is the runner's rule and the one-side-per-game rule
in one. The stake is small (``stake_units`` in the config) and the day's cap is ``max_per_day`` in the config (50).

The cap is applied by the runner in lock order, so on a day with more than 50 games the earliest games fill it; the later ones
are not bet at all, not sampled. That is a known bias, and the feature log records the start hour so the learn step can see it.

AFTER AN OWNER APPLIES A PROPOSAL (``learner.state``) the hound has a FOCUS: for ``1 - explore_share`` of games (again by hash) it
draws only from candidates inside a focus segment, and passes when there is none; for the rest it still explores. Nothing applies
itself: with no applied proposal the focus is empty and every game is exploration.

Every bet row carries ``learner_features`` (``learner.features``, frozen at placement), the feature version, the mode
(``explore`` or ``focus``) and the rules version in force.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, List, Mapping, Optional

from src.hounds import ai_defs
from src.hounds.learner import FAMILY, HOUND_ID, CATEGORY, EXPERIMENTAL_LINE
from src.hounds.learner import features as feat
from src.hounds.learner import state as lstate
from src.hounds.pack import base

DEFAULT_MAX_PER_DAY = 50
DEFAULT_STAKE = 0.25
DEFAULT_EXPLORE_SHARE = 0.25
ENV_FLAG = "LEARNER_HOUND"
OFF_VALUES = ("off", "0", "false", "no")
ON_VALUES = ("on", "1", "true", "yes")


def enabled(env: Optional[Mapping] = None) -> bool:
    """ON unless ``LEARNER_HOUND`` is explicitly off (the Gematria Hound's rule)."""
    import os

    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "").strip().lower() not in OFF_VALUES


def explicitly_on(env: Optional[Mapping] = None) -> bool:
    import os

    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "").strip().lower() in ON_VALUES


class LearnerSelection(base.Selection):
    """A ``Selection`` carrying the stamps ``pack_run.bet_row`` copies onto the bet row."""

    def __init__(self, market: str, side: str, score: float, reason: str, stake: float, row_extra: dict):
        super().__init__(market, side, score, reason, stake)
        self.row_extra = row_extra


class LearnerHound(base.Hound):
    forward_only = True
    who_decided = "rule"
    category = CATEGORY
    id = HOUND_ID

    def __init__(self, entry: Mapping, *, now_fn: Optional[Callable[[], datetime]] = None, events: Optional[str] = None,
                 stores: Optional[base.Stores] = None):
        self.id = str(entry.get("id") or HOUND_ID)
        self.name = str(entry.get("name") or "The Learner")
        self.tagline = str(entry.get("tagline") or EXPERIMENTAL_LINE)
        self.style = str(entry.get("style") or "starts with no rules and learns from its own record")
        self.sports = ai_defs.resolve_sports(entry)
        self.markets = tuple(entry.get("markets") or base.MARKETS)
        self.RULE = str(entry.get("rule_text") or "")
        lo, hi = entry.get("price_band") or (base.PRICE_MIN, base.PRICE_MAX)
        self.band = (int(lo), int(hi))
        self.max_per_day = int(entry.get("max_per_day") or DEFAULT_MAX_PER_DAY)
        self.stake = float(entry.get("stake_units") or DEFAULT_STAKE)
        self.explore_share = float(entry.get("explore_share", DEFAULT_EXPLORE_SHARE))
        self.family = FAMILY
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.stores = stores
        state = lstate.read(events) if events else lstate.fold([])
        self.rules_version, self.focus = state["version"], set(state["focus"])

    def bind(self, stores: base.Stores) -> "LearnerHound":
        self.stores = stores
        return self

    def markets_for(self, sport: str) -> tuple:
        return ai_defs.markets_for_sport(sport, self.markets)

    def _candidates(self, board: Mapping, ctx: base.Context) -> list:
        """[(market, side, features)] for every side on the lock board inside the band, in a fixed order."""
        from src.hounds import pack_run

        written = self.now_fn()
        quotes = (self.stores.quotes_by_event.get(ctx.event_id) if self.stores else None) or []
        out = []
        for market in self.markets_for(ctx.sport):
            if market not in (board.get("markets") or {}):
                continue
            opened = feat.open_market_board(quotes, market, lock=ctx.lock, start=ctx.start, sport=ctx.sport) if quotes else None
            for side in base.SIDES[market]:
                info = base.side_info(board, market, side)
                if info is None or not pack_run.in_band(self, info["price_average"]):
                    continue
                f = feat.build(ctx, board, market, side, written=written, open_market=opened)
                if f is not None:
                    out.append((market, side, f))
        return out

    def pick(self, board: Mapping, ctx: base.Context) -> List[base.Selection]:
        cands = self._candidates(board, ctx)
        if not cands:
            return []
        seed = base.seed_bytes(self.id, ctx.event_id)
        draw = int.from_bytes(seed[:8], "big") / 2.0 ** 64
        mode = "explore"
        if self.focus and draw >= self.explore_share:
            mode = "focus"
            cands = [c for c in cands if feat.segment_of(c[2]) in self.focus]
            if not cands:
                return []
        market, side, f = cands[int.from_bytes(seed[8:16], "big") % len(cands)]
        if mode == "explore":
            reason = (f"No rule yet: drew one of the {len(cands)} sides on the board inside its price band. "
                      "Small, and logged so it can learn from the result.")
        else:
            reason = (f"Rules v{self.rules_version}: drew from the segments the owner applied "
                      f"({len(self.focus)}), at {f['band']}. Small, and logged so it can keep learning.")
        extra = {"learner_features": f, "feature_version": feat.FEATURE_VERSION, "learner_mode": mode,
                 "rules_version": self.rules_version, "forward_only": True}
        if ctx.league and ctx.sport not in ("mlb", "nfl"):
            extra["league_title"] = ctx.league
        return [LearnerSelection(market, side, 1.0, reason, self.stake, extra)]
