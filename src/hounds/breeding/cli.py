"""python -m src.hounds.breeding ... : the breeding program's door (docs/PREREG_BREEDING.md).

    tick [--dry-run]          run the due cycle (a capture slot calls this); --dry-run computes it (or the
                              next one) on the real ledgers and writes nothing anywhere
    status                    the family tree payload (what GET /hounds/breeding serves)
    resume --reason "..."     the owner lifts an auto-pause
    verify                    walk the breeding ledger's hash chain

TESTING SEAMS: ``--root DIR`` puts the house learning ledgers and the breeding ledger under DIR,
``--champion-ledger PATH`` the pack ledger, ``--config PATH`` the kill switch, ``--now ISO`` the clock.
No command makes a model call or places a bet.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from src.hounds.breeding import cycle, rules
from src.hounds.learning import ledger as L


def _world(args) -> cycle.World:
    w = cycle.World.default()
    if args.root:
        root = Path(args.root)
        w.scope = L.Scope.house(root)
        w.breed_ledger = root / rules.LEDGER_FILE
    if args.champion_ledger:
        w.champion_ledger = Path(args.champion_ledger)
    if args.config:
        w.config = Path(args.config)
    return w


def _now(args):
    return L.parse(args.now) if args.now else None


def _out(obj) -> None:
    print(json.dumps(obj, indent=1, sort_keys=True, default=str))


def summary(report: dict) -> str:
    """One line for the capture slot's log."""
    if not report.get("due"):
        return f"breeding: {report.get('message') or 'no cycle due'}"
    head = f"breeding cycle {report.get('cycle_date')}: {report.get('outcome')} ({report.get('reason')})"
    births = ", ".join(b["challenger_id"] for b in report.get("births") or [])
    return head + (f"; born {births}" if births else "") + (
        f"; PAUSED: {report['paused']}" if report.get("paused") else "")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m src.hounds.breeding")
    ap.add_argument("--root")
    ap.add_argument("--champion-ledger")
    ap.add_argument("--config")
    ap.add_argument("--now")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--json", action="store_true")
    sub.add_parser("status")
    r = sub.add_parser("resume")
    r.add_argument("--reason", required=True)
    sub.add_parser("verify")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    world = _world(args)
    if args.cmd == "tick":
        report = cycle.tick(world, now=_now(args), dry_run=args.dry_run)
        if args.dry_run or args.json:
            _out(report)
        else:
            print(summary(report))
        return 0
    if args.cmd == "status":
        _out(cycle.family_tree(world, now=_now(args)))
        return 0
    if args.cmd == "resume":
        _out(cycle.resume(world, args.reason, now=_now(args)))
        return 0
    if args.cmd == "verify":
        res = cycle.BreedLog(world.breed_ledger).verify()
        _out({"ok": bool(res.ok), "rows": res.rows_checked, "broken_at_line": res.broken_at_line,
              "reason": res.reason})
        return 0 if res.ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
