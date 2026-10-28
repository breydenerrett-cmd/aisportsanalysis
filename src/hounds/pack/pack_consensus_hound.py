"""Pack Consensus: bets a side only when two or more PROVEN hounds recorded the same side before it decided.

The rule book is ``docs/PREREG_PACK_HOUND.md`` (frozen 2026-10-28, before this file existed). Read it for the why;
this docstring is the map.

NOT PACK LEADER. ``pack_leader`` re-runs seven hand-picked hounds' rules on the board; any hound with no edge votes.
This hound never re-runs a rule. It reads other hounds' RECORDED TICKETS (forward bet rows in the house ledger and the
AI ledger) and asks, for each hound, whether its own graded forward bets beat the close: n >= ``MIN_BETS`` bets with a
measurable close, mean CLV > 0 and the lower bound of the date-clustered 95% interval > 0 (``pack_settle.clustered_ci``,
the machinery the /hounds payload uses). Only those hounds vote, and a lineage / rule family casts one vote.

POINT IN TIME. For a game dated D at decision instant T (the runner's ``now``):
  membership  graded rows with ``graded_utc`` <= T about bets dated strictly before D;
  votes       tickets with ``written_utc`` <= T and < the game's start. A ticket recorded after T is invisible.
FORWARD ONLY. ``forward_only`` makes ``pack_run`` refuse a replay: replaying would let today's record pick yesterday's
voters. Only ``segment: "forward"`` rows are read, for membership and for votes.

AN EMPTY PACK IS A STATE, SAID PLAINLY. With fewer than ``MIN_VOTERS`` qualifying families the hound bets nothing and
``status()`` says ``EMPTY_PACK_SENTENCE`` with the counts. The runner passes the status to the admin report.

Survivorship bias (voters are chosen BECAUSE their CLV was positive) is stated in the prereg, not solved here: the
forward gate on this hound's own bets is the defence. Paper only; no bet can be placed from here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from src.hounds import ai_defs
from src.hounds.pack import base

HOUND_ID = "pack_consensus"
FAMILY = "pack_consensus"
CATEGORY = "mixed"

MIN_BETS = 30                  # prereg section 2: smallest sample a date-clustered t interval is usable on
MIN_FAMILY_VOTES = 2           # prereg section 3: independent families that must back the same side
MIN_VOTERS = 3                 # prereg section 2: qualifying families before a pack exists at all
MAX_BETS_PER_DAY = base.MAX_PER_DAY
STAKE = 1.0
# Control / entertainment categories never vote (prereg section 2.3).
EXCLUDED_CATEGORIES = frozenset({"random", "simple", "esoteric", "numerology", "baseline"})
EXCLUDED_IDS = frozenset({"pack_leader", HOUND_ID})
# Hounds that share one signal count once (prereg section 4): steamy/contrary read one line move in opposite
# directions; professor_paws and totals_terrier both read the one house run model.
RULE_FAMILIES = {"steamy_setter": "line_movement", "contrary_corgi": "line_movement",
                 "professor_paws": "run_model", "totals_terrier": "run_model"}
MARKET_ORDER = ("moneyline", "spread", "total")
EMPTY_PACK_SENTENCE = "Not enough proven hounds yet to form a pack."


def _read(path: Optional[str]) -> List[dict]:
    if not path or not Path(path).exists():
        return []
    from src.ledger.chain import HashChainLedger

    return [r for r in HashChainLedger(path).iter_rows() if isinstance(r, dict)]


def _house_categories() -> Dict[str, str]:
    from src import paths

    try:
        data = json.loads((Path(paths.repo_root()) / "config" / "house_pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {h["id"]: str(h.get("category") or "") for h in data.get("hounds") or [] if h.get("id")}


def _ai_meta() -> Dict[str, dict]:
    return {e["id"]: e for e in ai_defs.entries(include_parked=True)}


def family_of(hound_id: str, ai_entries: Mapping[str, dict]) -> str:
    """The lineage / rule family a hound's vote counts under."""
    if hound_id in RULE_FAMILIES:
        return RULE_FAMILIES[hound_id]
    entry = ai_entries.get(hound_id)
    if entry and entry.get("family"):
        return "ai:" + str(entry["family"])
    return hound_id


def _is_forward(row: Mapping) -> bool:
    return row.get("segment") == "forward" and row.get("role") != "challenger"


ENV_FLAG = "PACK_CONSENSUS_HOUND"


def enabled(env: Optional[Mapping] = None) -> bool:
    """ON unless ``PACK_CONSENSUS_HOUND`` is explicitly off (the Learner's rule)."""
    import os

    source = env if env is not None else os.environ
    return str(source.get(ENV_FLAG) or "").strip().lower() not in ("off", "0", "false", "no")


class PackConsensusSelection(base.Selection):
    def __init__(self, market, side, score, reason, stake, row_extra):
        super().__init__(market, side, score, reason, stake)
        self.row_extra = row_extra


class PackConsensusHound(base.Hound):
    forward_only = True
    who_decided = "rule"
    category = CATEGORY
    id = HOUND_ID

    def __init__(self, entry: Optional[Mapping] = None, *, now_fn: Optional[Callable[[], datetime]] = None,
                 house_ledger: Optional[str] = None, ai_ledger: Optional[str] = None,
                 categories: Optional[Mapping[str, str]] = None, ai_entries: Optional[Mapping[str, dict]] = None,
                 rows: Optional[Sequence[Mapping]] = None):
        entry = entry or {}
        self.id = str(entry.get("id") or HOUND_ID)
        self.name = str(entry.get("name") or "Pack Consensus")
        self.tagline = str(entry.get("tagline") or "Only moves when the proven hounds agree.")
        self.style = str(entry.get("style") or "consensus of hounds with a closing-line record")
        self.sports = ai_defs.resolve_sports(entry) if entry else base.DEFAULT_SPORTS
        self.markets = tuple(entry.get("markets") or base.MARKETS)
        self.RULE = str(entry.get("rule_text") or "")
        lo, hi = entry.get("price_band") or (base.PRICE_MIN, base.PRICE_MAX)
        self.band = (int(lo), int(hi))
        self.max_per_day = int(entry.get("max_per_day") or MAX_BETS_PER_DAY)
        self.stake = STAKE
        self.family = FAMILY
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._house_ledger, self._ai_ledger = house_ledger, ai_ledger
        self._categories = categories
        self._ai_entries = ai_entries
        self._rows = list(rows) if rows is not None else None
        self._members: Dict[str, dict] = {}
        self.last_status: dict = {"formed": False, "sentence": EMPTY_PACK_SENTENCE, "voters": [], "families": 0}

    def bind(self, stores) -> "PackConsensusHound":
        return self

    def markets_for(self, sport: str) -> tuple:
        return ai_defs.markets_for_sport(sport, self.markets)

    # -- reading -------------------------------------------------------------------------------------------------
    def rows(self) -> List[dict]:
        if self._rows is None:
            from src.hounds import pack_run

            self._rows = (_read(self._house_ledger or pack_run.ledger_path())
                          + _read(self._ai_ledger or ai_defs.ledger_path()))
        return self._rows

    def _cats(self) -> Mapping[str, str]:
        if self._categories is None:
            cats = dict(_house_categories())
            cats.update({i: str(e.get("category") or "") for i, e in _ai_meta().items()})
            self._categories = cats
        return self._categories

    def _ai(self) -> Mapping[str, dict]:
        if self._ai_entries is None:
            self._ai_entries = _ai_meta()
        return self._ai_entries

    # -- membership (point in time) --------------------------------------------------------------------------------
    def members(self, day: str, as_of: datetime) -> dict:
        """{family: {"hounds": [ids], "n", "mean", "ci_low"}} of the families with a qualifying hound for a game dated ``day``."""
        key = f"{day}|{base.iso(as_of)}"
        if key in self._members:
            return self._members[key]
        from src.hounds import pack_settle

        cats = self._cats()
        by_hound: Dict[str, list] = {}
        for r in self.rows():
            if r.get("kind") != "hound_graded" or not _is_forward(r) or r.get("clv_pts") is None:
                continue
            hid = str(r.get("hound_id") or "")
            if not hid or hid in EXCLUDED_IDS or hid not in cats or cats[hid] in EXCLUDED_CATEGORIES:
                continue
            when = base.parse_utc(r.get("graded_utc"))
            if when is None or when > as_of or str(r.get("date") or "") >= day:
                continue
            by_hound.setdefault(hid, []).append((str(r["date"]), float(r["clv_pts"])))
        out: Dict[str, dict] = {}
        ai = self._ai()
        for hid, vals in sorted(by_hound.items()):
            if len(vals) < MIN_BETS:
                continue
            mean, lo, _hi, _g = pack_settle.clustered_ci(vals)
            if mean is None or lo is None or not (mean > 0 and lo > 0):
                continue
            fam = out.setdefault(family_of(hid, ai), {"hounds": [], "n": 0, "mean": None, "ci_low": None})
            fam["hounds"].append(hid)
            fam["n"] += len(vals)
            fam["mean"], fam["ci_low"] = round(mean, 3), round(lo, 3)
        self._members[key] = out
        return out

    # -- votes (point in time) -------------------------------------------------------------------------------------
    def votes(self, event_id: str, members: Mapping[str, dict], as_of: datetime,
              start: Optional[datetime]) -> Dict[tuple, Dict[str, set]]:
        """{(market, side): {family: {hound ids}}} from voters' forward tickets recorded at or before ``as_of``, before the start."""
        voter_family = {h: fam for fam, m in members.items() for h in m["hounds"]}
        out: Dict[tuple, Dict[str, set]] = {}
        for r in self.rows():
            if r.get("kind") != "hound_bet" or r.get("event_id") != event_id or not _is_forward(r):
                continue
            hid = str(r.get("hound_id") or "")
            if hid not in voter_family:
                continue
            written = base.parse_utc(r.get("written_utc"))
            if written is None or written > as_of or (start is not None and written >= start):
                continue
            out.setdefault((r.get("market"), r.get("side")), {}).setdefault(voter_family[hid], set()).add(hid)
        # A family whose members disagree on a market casts no vote there (prereg section 4).
        for (market, side), fams in list(out.items()):
            rival = out.get((market, base.other(side))) or {}
            for fam in [f for f in fams if f in rival]:
                del fams[fam]
        return {k: v for k, v in out.items() if v}

    def status(self, day: str, as_of: Optional[datetime] = None) -> dict:
        """The pack as it stands for games on ``day``: formed or not, who is in it, in plain words."""
        as_of = as_of or self.now_fn()
        members = self.members(day, as_of)
        voters = sorted(h for m in members.values() for h in m["hounds"])
        formed = len(members) >= MIN_VOTERS
        if formed:
            sentence = f"{len(voters)} proven hounds in the pack: {', '.join(voters)}."
        else:
            sentence = (f"{EMPTY_PACK_SENTENCE} {len(members)} of the {MIN_VOTERS} needed have a closing-line record "
                        f"(at least {MIN_BETS} measured bets, average beating the close with the lower bound above zero).")
        self.last_status = {"formed": formed, "sentence": sentence, "voters": voters, "families": len(members),
                            "day": day}
        return self.last_status

    # -- the hound -------------------------------------------------------------------------------------------------
    def pick(self, board: Mapping, ctx: base.Context) -> List[base.Selection]:
        as_of = self.now_fn()
        status = self.status(ctx.date, as_of)
        if not status["formed"]:
            return []
        members = self.members(ctx.date, as_of)
        votes = self.votes(ctx.event_id, members, as_of, ctx.start)
        backed: dict = {}
        for (market, side), fams in votes.items():
            if market in self.markets_for(ctx.sport) and market in (board.get("markets") or {}):
                backed[(market, side)] = fams
        # sides of the game the voters backed, to refuse a game they split on (one side per game)
        sides = {side for (market, side) in votes if side in ("home", "away")}
        if {"home", "away"} <= sides:
            return []
        cands = []
        for (market, side), fams in backed.items():
            if len(fams) < MIN_FAMILY_VOTES:
                continue
            if backed.get((market, base.other(side))):
                continue
            cands.append((-len(fams), MARKET_ORDER.index(market) if market in MARKET_ORDER else 9, market, side, fams))
        if not cands:
            return []
        cands.sort(key=lambda c: c[:4])
        _, _, market, side, fams = cands[0]
        info = base.side_info(board, market, side)
        if info is None:
            return []
        mb = board["markets"][market]
        label = base.selection_label(ctx, market, side, mb["line"])
        names = sorted(h for hs in fams.values() for h in hs)
        reason = (f"{len(fams)} independent proven hounds recorded {label} before the decision: {', '.join(names)}. "
                  f"Pack of {len(members)} families, each with a closing-line record.")
        extra = {"pack_voters": names, "pack_families": sorted(fams), "pack_size": len(members),
                 "forward_only": True}
        return [PackConsensusSelection(market, side, float(len(fams)), reason, self.stake, extra)]

