"""Run the live challengers in SHADOW, on the same games at the same prices as their champions.

THE PAIR MUST SEE THE SAME WORLD
--------------------------------
A comparison is only worth its pairing. So a challenger is not run by code of its own: it is run by
the champion's own engine, handed the challenger as one more hound.

  * pack hounds: ``pack_run.run`` (the board at each game's lock, the -200 rule, the price band, the
    daily cap, one bet per game) with a ``tunables.VersionedHound`` whose id is the challenger's and
    whose knob values are the challenger's;
  * user hounds: ``user_engine.run`` (the board at lock, the band, the -200 cap, the minimum books,
    the quota) with the challenger's spec as the hound's spec.

The rows go to the scope's CHALLENGER ledger (never a public source) and carry
``role: "challenger"``, ``challenger_id``, ``parent_hound_id`` and ``parent_version``. Settlement
reuses the champion's settler (``pack_settle.settle`` / ``user_settle.settle``) over that ledger, so
a challenger bet is graded by the same code and the same results as a champion's.

FORWARD ONLY. The engines refuse a row at or after the start; ``min_lock`` (pack) and ``created_at``
(user) keep a challenger from betting a game whose lock came before its proposal. There is no replay
mode here, and the pack call below is always ``replay=False``.

Nothing here decides anything; the referee reads these rows later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable, Mapping, Optional, Sequence

from src.hounds.learning import ledger as L
from src.hounds.learning import rules, tunables


def role_fields(c: L.Challenger) -> dict:
    return {"role": rules.ROLE_CHALLENGER, "challenger_id": c.id, "parent_hound_id": c.hound_id,
            "parent_version": c.parent_version}


# ---- pack --------------------------------------------------------------------------------------

def pack_hounds(state: L.State, *, tun_cfg: Optional[Mapping] = None, registry: Optional[Mapping] = None) -> list:
    """The live pack challengers as hounds the pack runner can ask. A challenger whose champion
    has since changed version is skipped (the referee closes it)."""
    from src.hounds import pack as pack_mod
    cfg = tun_cfg if tun_cfg is not None else tunables.load()
    reg = registry if registry is not None else pack_mod.BY_ID
    out = []
    for c in state.live():
        if c.kind != "pack" or c.hound_id not in reg or c.hound_id not in cfg:
            continue
        if state.champion_version(c.hound_id) != c.parent_version:
            continue
        values = tunables.full_values(cfg[c.hound_id], c.spec.get("values"))
        out.append(tunables.VersionedHound(
            reg[c.hound_id], cfg[c.hound_id], values, hound_id=c.id,
            row_extra=dict(role_fields(c), params=values), min_lock=L.parse(c.created_utc)))
    return out


def record_coverage(scope: L.Scope, covered: Mapping, *, now: datetime) -> int:
    """Append ONE ``shadow_coverage`` event holding only the event ids not yet recorded for each
    challenger (a run every 15 minutes must not write 96 rows a day). Returns how many ids were new."""
    state = L.read_state(scope)
    fresh = {}
    for cid, ids in covered.items():
        new = sorted(set(map(str, ids)) - state.coverage.get(cid, set()))
        if new:
            fresh[cid] = new
    if fresh:
        L.log_for(scope).append(L.K_COVERAGE, now=now, scope=scope.name, covered=fresh)
    return sum(len(v) for v in fresh.values())


def pack_covered(stores, dates: Sequence[str], hounds: Sequence, *, now: datetime) -> dict:
    """Per challenger, the games it was in a position to bet at ``now``: lock passed, not started, its
    sport, and its own start floor."""
    from src.hounds import pack_run
    out = {h.id: set() for h in hounds}
    for lock, eid, ctx in pack_run.events_for_dates(stores, dates):
        if not (lock <= now < ctx.start):
            continue
        for h in hounds:
            if h.applies_to(ctx.sport) and h.accepts(ctx):
                out[h.id].add(eid)
    return out


def run_pack(stores, dates: Sequence[str], scope: L.Scope, *, now: datetime,
             tun_cfg: Optional[Mapping] = None, registry: Optional[Mapping] = None) -> dict:
    """Ask every live pack challenger about every game on ``dates``; append its rows (forward)."""
    from src.hounds import pack_run
    hounds = pack_hounds(L.read_state(scope), tun_cfg=tun_cfg, registry=registry)
    if not hounds:
        return {"challengers": 0, "written": 0}
    counts = pack_run.run(stores, dates, replay=False, now=now, path=str(scope.challenger_bets),
                          hounds=hounds, out=lambda *_a, **_k: None)
    counts["challengers"] = len(hounds)
    counts["covered_new"] = record_coverage(scope, pack_covered(stores, dates, hounds, now=now), now=now)
    return counts


def settle_pack(stores, scope: L.Scope, *, now: datetime) -> dict:
    from src.hounds import pack_settle
    return pack_settle.settle(stores, now=now, path=str(scope.challenger_bets))


# ---- user --------------------------------------------------------------------------------------

def user_hounds(state: L.State) -> list:
    """The live user challengers as hound dicts for ``user_engine.run``."""
    out = []
    for c in state.live():
        if c.kind != "user":
            continue
        out.append({"id": c.id, "spec": dict(c.spec), "spec_hash": c.spec_hash, "created_at": c.created_utc,
                    "row_extra": role_fields(c)})
    return out


def run_user(scope: L.Scope, dates: Iterable[str], *, now: datetime,
             rows_for: Optional[Callable[[str, set], Iterable]] = None,
             multibook_path: Optional[str] = None, game_pk_index: Optional[Mapping] = None) -> dict:
    """One shadow pass of the user challengers over ``dates``. ``rows_for(date, sports)`` yields the
    day's raw multibook rows (default: this server's own odds store, streamed)."""
    from src.hounds import user_engine
    hounds = user_hounds(L.read_state(scope))
    report = {"challengers": len(hounds), "written": 0, "by_date": []}
    if not hounds:
        return report
    sports = {s for h in hounds for s in h["spec"]["sports"]}
    seen: dict = {}
    index = game_pk_index if game_pk_index is not None else user_engine._load_game_pk_index()
    for date in dates:
        rows = (rows_for(date, sports) if rows_for is not None
                else user_engine.iter_rows(date, sports, multibook_path=multibook_path))
        out = user_engine.run(date, hounds, rows, ledger=str(scope.challenger_bets), now=now,
                              mode="live", game_pk_index=index)
        report["by_date"].append({k: out[k] for k in ("date", "games_seen", "bets_written", "skipped")})
        report["written"] += out["bets_written"]
        for cid, ids in out["considered"].items():
            seen.setdefault(cid, set()).update(ids)
    report["covered_new"] = record_coverage(scope, seen, now=now)
    return report


def settle_user(scope: L.Scope, *, now: datetime, **kwargs) -> dict:
    from src.hounds import user_settle
    return user_settle.settle(ledger=str(scope.challenger_bets), now=now, **kwargs)
