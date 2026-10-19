"""Who the members are, how fit each one is, who may breed and who is culled (docs/PREREG_BREEDING.md
sections 2, 3 and 6).

FORWARD ONLY. ``tally`` counts a bet only when its bet row says ``segment: "forward"``; a replay row, or
a graded row whose bet was a replay, is never counted, and no hindsight ledger is ever opened. A bet is
SETTLED when its newest graded row says WIN, LOSS or PUSH (VOID and UNRESOLVED do not count). Rows dated
before the seal floor are dropped unread.

Pure given its inputs: the ledgers' rows come in as lists, so a test hands fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from src.hounds.breeding import rules

KIND_BET = "hound_bet"
KIND_GRADED = "hound_graded"
SEAL_FLOOR = "2026-08-28"          # src.hounds.pack.base.SEAL_FLOOR (a test pins the two equal)


@dataclass
class Tally:
    n: int = 0                     # settled forward bets
    m: int = 0                     # of them, with a measured closing-line value
    clv_sum: float = 0.0
    units_avg: float = 0.0         # units at the average price, summed
    wins: int = 0
    losses: int = 0
    pushes: int = 0

    def add(self, graded: Mapping) -> None:
        result = str(graded.get("result") or "").upper()
        if result not in rules.SETTLED_RESULTS:
            return
        self.n += 1
        if result == "WIN":
            self.wins += 1
        elif result == "LOSS":
            self.losses += 1
        else:
            self.pushes += 1
        units = graded.get("units_average_price")
        if isinstance(units, (int, float)) and not isinstance(units, bool):
            self.units_avg += float(units)
        clv = graded.get("clv_pts")
        if isinstance(clv, (int, float)) and not isinstance(clv, bool):
            self.m += 1
            self.clv_sum += float(clv)


def _bet_key(row: Mapping) -> tuple:
    return (row.get("hound_id"), row.get("event_id"), row.get("market"), row.get("selection"))


def tally(rows: Iterable[Mapping], *, by_version: bool) -> dict:
    """``{(hound_id, version): Tally}`` (champion ledger, ``by_version``) or ``{hound_id: Tally}``.

    A graded row finds its bet by ``bet_row_hash`` (what ``pack_settle`` writes), else by
    (hound, event, market, selection). The newest graded row of a bet replaces an earlier one."""
    bets: dict = {}            # bet key -> (group key)
    by_hash: dict = {}         # bet row_hash -> bet key
    graded: dict = {}          # bet key -> newest graded row
    for row in rows:
        kind = row.get("kind")
        if str(row.get("date") or "") < SEAL_FLOOR:
            continue
        if kind == KIND_BET:
            if str(row.get("segment") or "forward") != "forward":
                continue
            key = _bet_key(row)
            if by_version:
                try:
                    version = int(row.get("hound_version") or 1)
                except (TypeError, ValueError):
                    version = 1
                group = (row.get("hound_id"), version)
            else:
                group = row.get("hound_id")
            bets[key] = group
            if row.get("row_hash"):
                by_hash[row["row_hash"]] = key
        elif kind == KIND_GRADED:
            key = by_hash.get(row.get("bet_row_hash")) or _bet_key(row)
            graded[key] = row
    out: dict = {}
    for key, group in bets.items():
        t = out.setdefault(group, Tally())
        g = graded.get(key)
        if g is not None:
            t.add(g)
    return out


@dataclass
class Member:
    id: str                        # the hound id for a champion, the challenger id for a challenger
    hound_id: str                  # the family
    role: str                      # "champion" | "challenger" | "baby"
    version: int                   # the champion version (a challenger: the version it was born under)
    values: dict
    category: str = "mixed"
    generation: int = 0
    name: str = ""
    tally: Tally = field(default_factory=Tally)

    @property
    def n(self) -> int:
        return self.tally.n

    @property
    def clv_mean(self) -> Optional[float]:
        return self.tally.clv_sum / self.tally.m if self.tally.m else None

    @property
    def shrunk(self) -> float:
        m = self.tally.m
        if not m:
            return 0.0
        return (self.tally.clv_sum / m) * m / (m + rules.SHRINK_PRIOR_BETS)

    @property
    def units_per_bet(self) -> Optional[float]:
        return self.tally.units_avg / self.tally.n if self.tally.n else None

    @property
    def eligible(self) -> bool:
        return self.n >= rules.MIN_SETTLED_FOR_ELIGIBLE

    def ref(self) -> str:
        """A plain reference (``hound/v2`` or a challenger id) for a ledger row or an evidence list."""
        return f"{self.hound_id}/v{self.version}" if self.role == "champion" else self.id

    def to_json(self) -> dict:
        t = self.tally
        return {"id": self.id, "ref": self.ref(), "hound_id": self.hound_id, "name": self.name or self.hound_id,
                "role": self.role, "version": self.version, "generation": self.generation,
                "category": self.category, "values": dict(self.values),
                "settled": t.n, "need": rules.MIN_SETTLED_FOR_ELIGIBLE, "eligible": self.eligible,
                "record": {"w": t.wins, "l": t.losses, "p": t.pushes},
                "clv_measured": t.m,
                "clv_mean": None if self.clv_mean is None else round(self.clv_mean, 4),
                "shrunk_clv": round(self.shrunk, rules.FITNESS_DECIMALS),
                "units_per_bet": None if self.units_per_bet is None else round(self.units_per_bet, 4)}


def is_control(member: Member) -> bool:
    return member.hound_id in rules.CONTROL_IDS or member.id in rules.CONTROL_IDS \
        or member.category in rules.CONTROL_CATEGORIES


def build_members(tun_cfg: Mapping, state, champion_tallies: Mapping, challenger_tallies: Mapping,
                  *, generations: Optional[Mapping] = None, names: Optional[Mapping] = None) -> list:
    """Every member of every family: each tunable hound's current champion version and its LIVE pack
    challengers born under that version (``state`` is the house learning ledger's fold)."""
    from src.hounds.learning import tunables
    gens = generations or {}
    out = []
    for hid in sorted(tun_cfg):
        tun = tun_cfg[hid]
        version = state.champion_version(hid)
        out.append(Member(
            id=hid, hound_id=hid, role="champion", version=version,
            values=tunables.full_values(tun, state.champion_params(hid)), category=tun.category,
            generation=0, name=(names or {}).get(hid) or tun.name,
            tally=champion_tallies.get((hid, version)) or Tally()))
        for c in state.live():
            if c.kind != "pack" or c.hound_id != hid or c.parent_version != version:
                continue
            out.append(Member(
                id=c.id, hound_id=hid,
                role="baby" if c.proposed_by == rules.PROPOSED_BY else "challenger",
                version=c.parent_version, values=tunables.full_values(tun, (c.spec or {}).get("values")),
                category=tun.category, generation=int(gens.get(c.id, 0)),
                name=(names or {}).get(hid) or tun.name,
                tally=challenger_tallies.get(c.id) or Tally()))
    return out


def fitness_key(m: Member) -> tuple:
    """Sort key, best first: shrunk CLV (4 places), then units per settled bet at the average price,
    then the id."""
    upb = m.units_per_bet
    return (-round(m.shrunk, rules.FITNESS_DECIMALS), -(round(upb, 6) if upb is not None else 0.0), m.id)


def rank(members: Sequence[Member]) -> list:
    """The eligible members, best first."""
    return sorted((m for m in members if m.eligible), key=fitness_key)


def parent_pool(ranked: Sequence[Member]) -> list:
    return list(ranked[:rules.PARENT_POOL])


def cull_candidates(ranked: Sequence[Member]) -> list:
    """The bottom 2 eligible members with at least 40 settled bets and shrunk CLV below 0, worst first.
    Nothing when fewer than 4 are eligible. Controls and fun dogs never."""
    if len(ranked) < rules.CULL_MIN_ELIGIBLE:
        return []
    bottom = list(reversed(ranked[-rules.CULL_BOTTOM:]))
    return [m for m in bottom
            if m.n >= rules.CULL_MIN_SETTLED and round(m.shrunk, rules.FITNESS_DECIMALS) < rules.CULL_BELOW
            and not is_control(m)]


def best_relative(ranked: Sequence[Member], culled: Member) -> Member:
    """The best eligible member of the culled one's family other than itself (itself if none)."""
    for m in ranked:
        if m.hound_id == culled.hound_id and m.id != culled.id:
            return m
    return culled


def most_settled(members: Sequence[Member]) -> int:
    return max((m.n for m in members), default=0)
