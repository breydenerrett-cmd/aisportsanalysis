"""Run the house pack: build each game's board at its lock, ask every hound, append bet rows.

    python -m src.hounds.pack_run --date 2026-10-17            # forward: games whose lock has passed
                                                              # and whose start has not
    python -m src.hounds.pack_run --date 2026-10-12 --replay   # replay one day from captures
    python -m src.hounds.pack_run --from 2026-09-08 --to 2026-10-17 --replay
    python -m src.hounds.pack_run --verify                     # walk the ledger's hash chain

RULES THE RUNNER ENFORCES (whatever a hound returns)
----------------------------------------------------
* A row is written only for a game whose lock has passed. A FORWARD row is refused at or after the
  start; a REPLAY row is written only for a game that has started (it is about the past) and is
  labelled `segment: "replay"`.
* At most one bet per game per hound; at most 3 per hound per Eastern date, taken in lock order
  (ties: event_id). Rows already in the ledger count toward both.
* Idempotent per (hound_id, event_id, market): a second run appends nothing.
* The -200 rule: no selection whose board-average price is -200 or worse, ever. Every hound's own
  price band is applied too. A selection outside the band is a pass, not a reason to pick another.
* The selection's market must be on the board at lock.

Paper only. No row is a recommendation.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, List, Mapping, Optional, Sequence

from src.hounds import pack as pack_mod
from src.hounds.pack import base
from src.ledger.chain import HashChainLedger

LEDGER = os.path.join("evidence", "hounds_house_v1.jsonl")
KIND_BET = "hound_bet"
KIND_GRADED = "hound_graded"


def ledger_path(path: Optional[str] = None) -> str:
    if path:
        return path
    from src import paths

    return str(paths.repo_root() / LEDGER)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def events_for_dates(stores: base.Stores, dates: Iterable[str]) -> list:
    """[(lock, event_id, ctx)] for every MLB/NFL event whose start falls on one of `dates` (ET)."""
    wanted = set(dates)
    out = []
    for eid in stores.events:
        ctx = base.build_context(stores, eid)
        if ctx is None or ctx.date not in wanted:
            continue
        out.append((ctx.lock, eid, ctx))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def bet_row(hound, ctx: base.Context, board: Mapping, sel: base.Selection, *, segment: str,
            written: datetime) -> Optional[dict]:
    mb = (board.get("markets") or {}).get(sel.market)
    if not mb:
        return None
    info = mb["sides"].get(sel.side)
    if not info:
        return None
    if sel.market == "spread":
        line = mb["line"] if sel.side == "home" else -mb["line"]
    elif sel.market == "total":
        line = mb["line"]
    else:
        line = None
    return {
        "kind": KIND_BET, "pack": pack_mod.PACK_ID, "hound_id": hound.id, "date": ctx.date, "sport": ctx.sport,
        "event_id": ctx.event_id, "game_pk": ctx.game_pk if ctx.sport == "mlb" else None,
        "nfl_game_id": ctx.nfl_game_id if ctx.sport == "nfl" else None,
        "away": ctx.away_name, "home": ctx.home_name, "away_code": ctx.away, "home_code": ctx.home,
        "start_utc": base.iso(ctx.start), "lock_utc": base.iso(ctx.lock),
        "market": sel.market, "selection": base.selection_label(ctx, sel.market, sel.side, mb["line"]),
        "side": sel.side, "line": line, "market_line": mb["line"],
        "price_average": info["price_average"], "price_best": info["price_best"], "book": info["book"],
        "book_count": info["book_count"], "consensus_fair": info["fair"],
        "reason": sel.reason, "who_decided": hound.who_decided, "segment": segment,
        "stake": float(sel.stake), "score": sel.score, "written_utc": base.iso(written),
    }


def in_band(hound, price: int) -> bool:
    lo = max(base.PRICE_MIN, hound.band[0])
    hi = min(base.PRICE_MAX, hound.band[1])
    return lo <= price <= hi and price > -200


def choose(hound, board: Mapping, ctx: base.Context) -> Optional[base.Selection]:
    sels = hound.pick(board, ctx) or []
    if not sels:
        return None
    sel = sorted(sels, key=lambda s: (-s.score, s.market, s.side))[0]
    info = base.side_info(board, sel.market, sel.side)
    if info is None or not in_band(hound, info["price_average"]):
        return None
    return sel


def run(stores: base.Stores, dates: Sequence[str], *, replay: bool, now: datetime,
        path: Optional[str] = None, hounds: Optional[Sequence] = None,
        out: Callable = print) -> dict:
    """Ask every hound about every game on `dates`; append the bets. Returns counts."""
    led = HashChainLedger(ledger_path(path))
    existing = [r for r in led.read() if r.get("kind") == KIND_BET]
    taken_game = {(r["hound_id"], r["event_id"]) for r in existing}
    taken_key = {(r["hound_id"], r["event_id"], r["market"]) for r in existing}
    per_day: dict = {}
    for r in existing:
        per_day[(r["hound_id"], r["date"])] = per_day.get((r["hound_id"], r["date"]), 0) + 1
    hounds = tuple(hounds or pack_mod.PACK)
    counts = {"games": 0, "written": 0, "skipped_not_locked": 0, "skipped_started": 0, "passes": 0}
    for lock, eid, ctx in events_for_dates(stores, dates):
        if now < lock:
            counts["skipped_not_locked"] += 1
            continue
        if replay:
            if now < ctx.start:
                counts["skipped_not_locked"] += 1     # not started yet: that is the forward run's game
                continue
            segment = "replay"
        else:
            if now >= ctx.start:
                counts["skipped_started"] += 1
                continue
            segment = "forward"
        counts["games"] += 1
        board = base.lock_board(stores, ctx)
        for hound in hounds:
            if not hound.applies_to(ctx.sport):
                continue
            if (hound.id, eid) in taken_game or per_day.get((hound.id, ctx.date), 0) >= base.MAX_PER_DAY:
                continue
            sel = choose(hound, board, ctx)
            if sel is None:
                counts["passes"] += 1
                continue
            if (hound.id, eid, sel.market) in taken_key:
                continue
            row = bet_row(hound, ctx, board, sel, segment=segment, written=now)
            if row is None or row["price_average"] <= -200:
                continue
            led.append(row)
            taken_game.add((hound.id, eid))
            taken_key.add((hound.id, eid, sel.market))
            per_day[(hound.id, ctx.date)] = per_day.get((hound.id, ctx.date), 0) + 1
            counts["written"] += 1
    return counts


def date_range(first: str, last: str) -> List[str]:
    d0, d1 = date.fromisoformat(first), date.fromisoformat(last)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def verify(path: Optional[str] = None) -> tuple:
    res = HashChainLedger(ledger_path(path)).verify()
    return res.ok, res.rows_checked, res.broken_at_line, res.reason


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.hounds.pack_run", description=__doc__.splitlines()[0])
    ap.add_argument("--date")
    ap.add_argument("--from", dest="first")
    ap.add_argument("--to", dest="last")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--ledger")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)
    if args.verify:
        ok, n, line, reason = verify(args.ledger)
        print(f"{'OK' if ok else 'BROKEN'}: {n} rows checked" + ("" if ok else f"; first break line {line}: {reason}"))
        return 0 if ok else 1
    if args.date:
        dates = [args.date]
    elif args.first and args.last:
        dates = date_range(args.first, args.last)
    else:
        ap.error("give --date D or --from A --to B")
    for d in dates:
        if base.in_seal(d):
            print(f"refused: {d} is inside the SEALED window {base.SEAL_FIRST}..{base.SEAL_LAST}")
            return 2
    since = max(base.SEAL_FLOOR, base.day_before(min(dates), 8))
    until = (date.fromisoformat(max(dates)) + timedelta(days=2)).isoformat()
    stores = base.load_stores(since=since, until=until)
    counts = run(stores, dates, replay=args.replay, now=_now(), path=args.ledger)
    print(f"{'replay' if args.replay else 'forward'} {dates[0]}..{dates[-1]}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
