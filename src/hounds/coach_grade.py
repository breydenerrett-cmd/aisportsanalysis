"""Grades for the coach report card, computed by code (docs/COACH_REPORT_CARD.md). No model is asked anything.

TWO GRADES, ONE ENGINE. Both reuse the house pack's own machinery so a suggestion is judged by exactly the code
and prices that judge a hound: ``pack_run.run`` (board at the lock, the -200 rule, the price band, the daily
cap, one bet per game), ``tunables.VersionedHound`` (a hound running with a set of knob values) and
``pack_settle.settle`` (results, closing line, units at the board-average price, CLV).

  HINDSIGHT   the 30 days BEFORE the suggestion. Both value sets are replayed over the stored boards into a
              TEMP ledger (the real ledgers are never opened for writing) and settled. It is instant and it is
              labelled hindsight everywhere because the coach could see that period: it is not evidence.
  FORWARD     from the suggestion's recorded time on. Both value sets run in SHADOW on new boards, forward only
              (never a replay), into ``evidence/hounds_coach_shadow_v1.jsonl``, and settle as games finish.

BOTH SIDES RUN IN SHADOW. The real champion's bets live in another ledger; comparing against them would turn
every game the shadow runner missed (a skipped slot) into a "pass" by the suggestion. Running the champion's
values beside it puts both in the same world: a missed game is missed by both, so it is no slot at all.

THE DECISION RULE is written in docs/COACH_REPORT_CARD.md BEFORE this code: a SLOT is a game one of the two sides
bet and every bet made has settled; ``d`` = suggested units minus champion units on it (a pass is 0); TOO EARLY
under ``MIN_SLOTS`` slots or ``MIN_DATES`` slate dates, else HELPED / HURT / NO DIFFERENCE by whether the 90%
date-clustered bootstrap interval of the mean of ``d`` lies wholly above, wholly below, or around zero. Nothing
here feeds the referee.
"""

from __future__ import annotations

import os
import random
import tempfile
from datetime import datetime, timedelta
from typing import Callable, Iterable, Mapping, Optional

from src.hounds import coach_card as C
from src.hounds import pack as pack_mod
from src.hounds import pack_run, pack_settle
from src.hounds.pack import base
from src.hounds.learning import tunables
from src.ledger.chain import HashChainLedger

HINDSIGHT_DAYS = 30
FORWARD_MAX_DAYS = 60            # a suggestion is followed this long, then its last grade stands
MIN_SLOTS = 20
MIN_DATES = 3
BOOTSTRAP_RESAMPLES = 2000
INTERVAL_LEVEL = 0.90

LABEL_HELPED = "HELPED"
LABEL_HURT = "HURT"
LABEL_NONE = "NO DIFFERENCE"
LABEL_EARLY = "TOO EARLY"
LABELS = (LABEL_HELPED, LABEL_HURT, LABEL_NONE, LABEL_EARLY)

SETTLED = ("WIN", "LOSS", "PUSH")
SIDES = ("champion", "suggested")


def shadow_id(issue: int, side: str) -> str:
    return f"coach-{issue}-{side}"


# ---- reading a ledger into per-side tables ---------------------------------------------------------------------

def side_tables(path, issue_ids: Optional[Iterable[str]] = None) -> dict:
    """``{hound_id: {event_id: (bet_row, graded_row or None)}}`` from a pack-shaped ledger. A later graded
    row for the same bet replaces an earlier one (a late void re-graded), as ``pack_settle`` does."""
    keep = set(issue_ids) if issue_ids is not None else None
    bets, graded = {}, {}
    for r in HashChainLedger(path).read():
        hid = r.get("hound_id")
        if keep is not None and hid not in keep:
            continue
        if r.get("kind") == pack_run.KIND_BET:
            bets[(hid, r["event_id"], r["market"], r["selection"])] = r
        elif r.get("kind") == pack_run.KIND_GRADED:
            graded[(hid, r["event_id"], r["market"], r["selection"])] = r
    out: dict = {}
    for key, bet in bets.items():
        out.setdefault(key[0], {})[key[1]] = (bet, graded.get(key))
    return out


def _units(entry) -> Optional[float]:
    if entry is None:
        return 0.0
    _bet, g = entry
    if g is None or g.get("result") not in SETTLED:
        return None
    u = g.get("units_average_price")
    return float(u) if isinstance(u, (int, float)) and not isinstance(u, bool) else None


def side_stats(table: Mapping) -> dict:
    """One side's record: bets, W-L-P, void, pending, units at the average price, mean CLV on measurable bets."""
    wins = losses = pushes = voids = pending = 0
    units, clvs = 0.0, []
    for bet, g in table.values():
        result = g.get("result") if g else None
        if result == "WIN":
            wins += 1
        elif result == "LOSS":
            losses += 1
        elif result == "PUSH":
            pushes += 1
        elif result in ("VOID", "UNRESOLVED"):
            voids += 1
        else:
            pending += 1
        if result in SETTLED:
            u = g.get("units_average_price")
            if isinstance(u, (int, float)) and not isinstance(u, bool):
                units += float(u)
            if isinstance(g.get("clv_pts"), (int, float)) and not isinstance(g.get("clv_pts"), bool):
                clvs.append(float(g["clv_pts"]))
    return {"bets": len(table), "wins": wins, "losses": losses, "pushes": pushes, "voids": voids,
            "pending": pending, "units": round(units, 4),
            "clv_mean": round(sum(clvs) / len(clvs), 4) if clvs else None, "clv_n": len(clvs)}


# ---- the pairing and the rule ------------------------------------------------------------------------------------

def slots_of(champion: Mapping, suggested: Mapping) -> dict:
    """``{"slots": [{event_id, date, d, c, s}], "pending": n, "excluded": n, "both": [...]}`` for two sides'
    tables. A slot is a game either side bet; it is final only when every bet made on it has settled."""
    slots, both, pending, excluded = [], [], 0, 0
    for eid in sorted(set(champion) | set(suggested)):
        c_entry, s_entry = champion.get(eid), suggested.get(eid)
        entries = [e for e in (c_entry, s_entry) if e is not None]
        results = [(e[1] or {}).get("result") for e in entries]
        if any(r is None for r in results):
            pending += 1
            continue
        if any(r not in SETTLED for r in results):
            excluded += 1
            continue
        c_u, s_u = _units(c_entry), _units(s_entry)
        if c_u is None or s_u is None:
            excluded += 1
            continue
        ref = entries[0][0]
        slot = {"event_id": eid, "date": str(ref.get("date"))[:10], "c": c_u, "s": s_u, "d": s_u - c_u}
        slots.append(slot)
        if c_entry is not None and s_entry is not None:
            c_clv, s_clv = c_entry[1].get("clv_pts"), s_entry[1].get("clv_pts")
            slot["clv_d"] = (s_clv - c_clv) if isinstance(c_clv, (int, float)) and isinstance(s_clv, (int, float)) else None
            both.append(slot)
    return {"slots": slots, "pending": pending, "excluded": excluded, "both": both}


def interval(slots: list, seed: int, *, resamples: int = BOOTSTRAP_RESAMPLES,
             level: float = INTERVAL_LEVEL) -> Optional[tuple]:
    """The mean of ``d`` and its date-clustered percentile-bootstrap interval, or None with under 2 dates.
    Dates are resampled with replacement and every slot of a drawn date is taken together; the generator is
    seeded (the issue number) so a re-run gives the same answer."""
    by_date: dict = {}
    for s in slots:
        by_date.setdefault(s["date"], []).append(s["d"])
    dates = sorted(by_date)
    if len(dates) < 2 or not slots:
        return None
    rng = random.Random(seed)
    g = len(dates)
    means = []
    for _ in range(resamples):
        total, count = 0.0, 0
        for _ in range(g):
            ds = by_date[dates[rng.randrange(g)]]
            total += sum(ds)
            count += len(ds)
        means.append(total / count)
    means.sort()
    tail = (1.0 - level) / 2.0
    lo = means[int(round(tail * (resamples - 1)))]
    hi = means[int(round((1.0 - tail) * (resamples - 1)))]
    return sum(s["d"] for s in slots) / len(slots), lo, hi


def decide(slots: list, seed: int) -> dict:
    """The forward label and the numbers behind it (docs/COACH_REPORT_CARD.md, "The forward decision rule")."""
    n = len(slots)
    dates = len({s["date"] for s in slots})
    out = {"n_paired": n, "n_dates": dates, "mean_d": None, "ci_low": None, "ci_high": None}
    if n < MIN_SLOTS or dates < MIN_DATES:
        out["label"] = LABEL_EARLY
        return out
    found = interval(slots, seed)
    if found is None:
        out["label"] = LABEL_EARLY
        return out
    mean, lo, hi = found
    out.update(mean_d=round(mean, 4), ci_low=round(lo, 4), ci_high=round(hi, 4))
    out["label"] = LABEL_HELPED if lo > 0 else LABEL_HURT if hi < 0 else LABEL_NONE
    return out


def compare(champion: Mapping, suggested: Mapping, seed: int) -> dict:
    """The pairing, the per-side records and the forward-style label for two tables."""
    paired = slots_of(champion, suggested)
    slots = paired["slots"]
    clv_ds = [s["clv_d"] for s in paired["both"] if s.get("clv_d") is not None]
    out = {
        "champion": side_stats(champion), "suggested": side_stats(suggested),
        "units_diff": round(sum(s["d"] for s in slots), 4),
        "pending_slots": paired["pending"], "excluded_slots": paired["excluded"],
        "both_bet": {"games": len(paired["both"]),
                     "units_diff": round(sum(s["d"] for s in paired["both"]), 4),
                     "clv_diff": round(sum(clv_ds) / len(clv_ds), 4) if clv_ds else None,
                     "clv_n": len(clv_ds)},
    }
    out.update(decide(slots, seed))
    return out


# ---- the hounds --------------------------------------------------------------------------------------------------

def make_hound(row: Mapping, side: str, registry: Mapping, tun_cfg: Mapping, *, min_lock=None):
    hid = row["hound"]
    values = row["champion_values"] if side == "champion" else row["suggested_values"]
    extra = {"role": "coach_practice", "coach_issue": row["issue"], "coach_side": side,
             "parent_hound_id": hid, "params": dict(values)}
    return tunables.VersionedHound(registry[hid], tun_cfg[hid], values, hound_id=shadow_id(row["issue"], side),
                                   row_extra=extra, min_lock=min_lock)


def _noop(*_a, **_k):
    return None


# ---- hindsight -----------------------------------------------------------------------------------------------------

def hindsight_window(row: Mapping) -> tuple:
    recorded = C.parse(row["recorded_utc"])
    last = base.eastern_date(recorded)
    return base.day_before(last, HINDSIGHT_DAYS), last


def stores_need_for_hindsight(row: Mapping) -> str:
    """The earliest odds date the hindsight replay needs (the runner's own 8-day lookback before it)."""
    first, _last = hindsight_window(row)
    return max(base.SEAL_FLOOR, base.day_before(first, 8))


def grade_hindsight(row: Mapping, stores, *, now: datetime, registry: Mapping, tun_cfg: Mapping) -> dict:
    """Both value sets over the 30 days before the suggestion, replayed into a temp ledger and settled.
    Returns the fields of a ``coach_graded_hindsight`` row. The real ledgers are never touched."""
    recorded = C.parse(row["recorded_utc"])
    first, last = hindsight_window(row)
    dates = [d for d in pack_run.date_range(first, last) if d >= base.SEAL_FLOOR and not base.in_seal(d)]
    hounds = [make_hound(row, s, registry, tun_cfg) for s in SIDES]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "hindsight.jsonl")
        pack_run.run(stores, dates, replay=True, now=recorded, path=path, hounds=hounds, out=_noop)
        pack_settle.settle(stores, now=now, path=path)
        tables = side_tables(path)
    cmp = compare(tables.get(shadow_id(row["issue"], "champion"), {}),
                  tables.get(shadow_id(row["issue"], "suggested"), {}), seed=int(row["issue"]))
    for key in ("label", "mean_d", "ci_low", "ci_high"):
        cmp.pop(key, None)           # a hindsight window is never given a verdict or an interval
    return dict(cmp, hindsight=True, window_first=first, window_last=last, window_days=HINDSIGHT_DAYS,
                status="ok")


# ---- forward --------------------------------------------------------------------------------------------------------

# The fan lane is graded by this same code (docs/COACH_REPORT_CARD.md, "The fan lane"). Each followed tip costs
# two shadow hounds on every forward pass, and the slot has a 100 s budget, so only the newest tips are followed
# live; an older one keeps its last grade. The coach's own suggestions are never trimmed (there are a few a week).
FAN_FOLLOWED_MAX = 120


def active_for_forward(card: C.Card, now: datetime) -> list:
    out, fans = [], []
    for issue, row in sorted(card.gradable().items()):
        when = C.parse(row.get("recorded_utc"))
        if when is not None and now - when <= timedelta(days=FORWARD_MAX_DAYS):
            (fans if issue in card.fans else out).append(row)
    fans.sort(key=lambda r: (str(r.get("recorded_utc") or ""), r["issue"]))
    return sorted(out + fans[-FAN_FOLLOWED_MAX:], key=lambda r: r["issue"])


def run_forward(rows: list, stores, paths: C.Paths, *, now: datetime, registry: Mapping, tun_cfg: Mapping) -> dict:
    """Ask both sides of every followed suggestion about the games open now (lock passed, not started)."""
    hounds = []
    for row in rows:
        if row["hound"] not in registry or row["hound"] not in tun_cfg:
            continue
        lock_floor = C.parse(row["recorded_utc"])
        hounds.extend(make_hound(row, s, registry, tun_cfg, min_lock=lock_floor) for s in SIDES)
    if not hounds:
        return {"hounds": 0, "written": 0}
    today = base.eastern_date(now)
    dates = [today, (datetime.fromisoformat(today) + timedelta(days=1)).date().isoformat()]
    counts = pack_run.run(stores, dates, replay=False, now=now, path=str(paths.shadow), hounds=hounds, out=_noop)
    counts["hounds"] = len(hounds)
    return counts


def forward_fields(row: Mapping, tables: Mapping) -> dict:
    issue = int(row["issue"])
    out = compare(tables.get(shadow_id(issue, "champion"), {}), tables.get(shadow_id(issue, "suggested"), {}),
                  seed=issue)
    return dict(out, since_utc=row["recorded_utc"])


_COMPARE_KEYS = ("champion", "suggested", "units_diff", "label", "n_paired", "n_dates", "mean_d", "ci_low",
                 "ci_high", "both_bet", "pending_slots", "excluded_slots")


def changed(prev: Optional[Mapping], fields: Mapping) -> bool:
    return prev is None or any(prev.get(k) != fields.get(k) for k in _COMPARE_KEYS)


# ---- the daily job ----------------------------------------------------------------------------------------------------

def grade_all(paths: C.Paths, *, now: datetime, registry: Optional[Mapping] = None,
              tun_cfg: Optional[Mapping] = None, loader: Optional[Callable] = None,
              deadline: Optional[float] = None, clock: Callable = None, say: Callable = print) -> dict:
    """Hindsight for every suggestion that has none, then one forward pass and settle for every followed
    suggestion, appending a ``coach_graded_forward`` row where the numbers moved. Idempotent: a re-run in the
    same minute appends nothing. ``deadline`` (a ``clock()`` value) stops it between stages."""
    import time
    clock = clock or time.monotonic
    registry = registry if registry is not None else pack_mod.BY_ID
    tun_cfg = tun_cfg if tun_cfg is not None else tunables.load()
    loader = loader or (lambda since, until: base.load_stores(since=since, until=until))
    card = C.load(paths)
    todo_hind = [r for i, r in sorted(card.gradable().items()) if i not in card.hindsight]
    follow = active_for_forward(card, now)
    result = {"hindsight": 0, "forward_rows": 0, "forward_written": 0, "stopped": None}
    if not todo_hind and not follow:
        return result

    today = base.eastern_date(now)
    since = base.day_before(today, 8)
    for r in todo_hind:
        since = min(since, stores_need_for_hindsight(r))
    until = (datetime.fromisoformat(today) + timedelta(days=2)).date().isoformat()
    stores = loader(since, until)

    for r in todo_hind:
        if deadline is not None and clock() > deadline:
            result["stopped"] = "time budget before hindsight"
            return result
        try:
            if r["hound"] not in registry or r["hound"] not in tun_cfg:
                raise KeyError(f"{r['hound']} is not a tunable pack hound in this build")
            fields = grade_hindsight(r, stores, now=now, registry=registry, tun_cfg=tun_cfg)
        except Exception as exc:  # noqa: BLE001 -- recorded once so one bad suggestion is not retried every slot
            fields = {"hindsight": True, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}
            say(f"  hindsight #{r['issue']}: error {fields['error']}")
        C.append(paths, C.K_HINDSIGHT, now=now, issue=r["issue"], hound=r["hound"], **fields)
        result["hindsight"] += 1

    if follow:
        if deadline is not None and clock() > deadline:
            result["stopped"] = "time budget before forward"
            return result
        counts = run_forward(follow, stores, paths, now=now, registry=registry, tun_cfg=tun_cfg)
        result["forward_written"] = counts.get("written", 0)
        if paths.shadow.exists():
            pack_settle.settle(stores, now=now, path=str(paths.shadow))
            tables = side_tables(paths.shadow)
            card = C.load(paths)
            for row in follow:
                fields = forward_fields(row, tables)
                if changed(card.forward.get(row["issue"]), fields):
                    C.append(paths, C.K_FORWARD, now=now, issue=row["issue"], hound=row["hound"],
                             date=C.iso(now)[:10], **fields)
                    result["forward_rows"] += 1
    return result
