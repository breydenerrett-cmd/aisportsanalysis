"""`python -m src.hounds.desk <command>`.

    prepare         freeze one game (at most 2 open games a run)
    session-plan    write the ready request files and print the jobs for subagents
    session-check   record and check every answer file waiting
    session-status  what is answered, checked and published
    check           record and check one answer file (the single-file form of session-check)
    publish         write bets, transcript and disagreement table for a date's games, or one folder
    grade           settle ungraded bets
    verify          walk the ledger's hash chain
    config          print, write or check config/desk_hounds.json

Exit codes: 0 ok, 2 error or refusal. Nothing here calls a model or the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

from src.analyst import cli as analyst_cli
from src.hounds.desk import grade as grade_mod
from src.hounds.desk import ledger, prepare as prepare_mod, publish as publish_mod
from src.hounds.desk import roles, session, state

EXIT_OK, EXIT_ERROR = 0, 2

CONFIG_PATH = "config/desk_hounds.json"


def config_text() -> str:
    return json.dumps(roles.config_document(), indent=2) + "\n"


def _root(args) -> Optional[Path]:
    return Path(args.root) if getattr(args, "root", None) else None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m src.hounds.desk",
                                 description="The AI Desk and persona hounds (paper only).")
    ap.add_argument("--root", default=None, help="repo root to read and write under (default: this repo)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare", help="freeze one game's data")
    p.add_argument("--date", required=True, help="YYYY-MM-DD (football: the Eastern game date)")
    p.add_argument("--game", required=True, help="AWAY@HOME, e.g. NYY@TB (football: LAC@KC)")
    p.add_argument("--sport", choices=roles.SPORTS, default="mlb")
    p.add_argument("--rehearsal", action="store_true",
                   help="mark the folder a rehearsal: it can be planned and checked, never published")

    for name, help_ in (("session-plan", "write ready request files and print the subagent jobs"),
                        ("session-check", "record and check every answer file waiting"),
                        ("session-status", "what is answered, checked and published")):
        q = sub.add_parser(name, help=help_)
        q.add_argument("--date", required=True)
        if name != "session-status":
            q.add_argument("--game", default=None, help="only this game, AWAY@HOME")
        if name == "session-plan":
            q.add_argument("--json", action="store_true",
                           help="print the jobs as one JSON object (for a scheduled task) instead of text")

    c = sub.add_parser("check", help="record and check one answer file")
    c.add_argument("--dir", required=True, help="the prepared game folder")
    c.add_argument("--stage", required=True, choices=roles.ALL_STAGES)
    c.add_argument("--response", required=True, help="the answer file")

    u = sub.add_parser("publish", help="publish final stages for a date's games, or one folder")
    g = u.add_mutually_exclusive_group(required=True)
    g.add_argument("--date")
    g.add_argument("--dir")
    u.add_argument("--model", required=True, help="the model id the subagents ran as, e.g. claude-sonnet-5-5")
    u.add_argument("--tokens-in", type=float, default=None)
    u.add_argument("--tokens-out", type=float, default=None)
    u.add_argument("--seconds", type=float, default=None)
    u.add_argument("--operator-minutes", type=float, default=None)

    r = sub.add_parser("grade", help="settle ungraded bets from stored results")
    r.add_argument("--date", default=None)

    sub.add_parser("verify", help="walk the ledger's hash chain")

    k = sub.add_parser("config", help="print, write or check config/desk_hounds.json")
    k.add_argument("--write", action="store_true")
    k.add_argument("--check", action="store_true")
    return ap


def run_config(args, out: Callable, root: Optional[Path]) -> int:
    target = state.root_of(root) / CONFIG_PATH
    text = config_text()
    if args.write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        out(f"wrote {target}")
        return EXIT_OK
    if args.check:
        try:
            held = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out(f"ERROR: {target} could not be read ({exc})")
            return EXIT_ERROR
        if held != roles.config_document():
            out(f"DIFFERENT: {target} is not what roles.py generates; run `config --write`")
            return EXIT_ERROR
        out("config/desk_hounds.json matches roles.py")
        return EXIT_OK
    out(text)
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None, *, out: Callable = print, now: Optional[Callable] = None,
         cfg=None, **seams) -> int:
    """`seams` are test injections: loader, store, rows (prepare), results, nfl_store (grade)."""
    args = build_parser().parse_args(argv)
    root = _root(args)
    cmd = args.command
    try:
        if cmd == "prepare":
            return prepare_mod.prepare(args.date, args.game, sport=args.sport, rehearsal=args.rehearsal,
                                       cfg=cfg, loader=seams.get("loader"), store=seams.get("store"),
                                       rows=seams.get("rows"), now=now, out=out, root=root)
        if cmd == "session-plan":
            if args.json:
                result = session.plan(args.date, cfg=cfg, now=now, out=lambda *_: None, root=root,
                                      only=args.game)
                out(json.dumps(session.plan_json(args.date, result), indent=2))
            else:
                session.plan(args.date, cfg=cfg, now=now, out=out, root=root, only=args.game)
            return EXIT_OK
        if cmd == "session-check":
            session.check_all(args.date, now=now, out=out, root=root, only=args.game)
            return EXIT_OK
        if cmd == "session-status":
            session.status(args.date, now=now, out=out, root=root)
            return EXIT_OK
        if cmd == "check":
            game = state.load(args.dir)
            result = session.check_answer(game, args.stage, args.response, now=now, out=out)
            return EXIT_ERROR if result == "refused" else EXIT_OK
        if cmd == "publish":
            kw = dict(model=args.model, tokens_in=args.tokens_in, tokens_out=args.tokens_out,
                      seconds=args.seconds, operator_minutes=args.operator_minutes, cfg=cfg, now=now,
                      out=out, root=root)
            if args.dir:
                return publish_mod.publish(state.load(args.dir), **kw)
            moment = (now or analyst_cli._now)()
            selected, _deferred, notes = session.select_games(args.date, moment, root)
            for note in notes:
                out(f"  note: {note}")
            if not selected:
                out(f"REFUSED: no open prepared game for {args.date}")
                return EXIT_ERROR
            codes = [publish_mod.publish(g, **kw) for g in selected]
            return EXIT_ERROR if any(codes) else EXIT_OK
        if cmd == "grade":
            return grade_mod.grade(date=args.date, results=seams.get("results"),
                                   nfl_store=seams.get("nfl_store"), now=now, out=out, root=root)
        if cmd == "verify":
            result = ledger.verify(root)
            out(f"ledger {ledger.path(root)}: " + ("chain ok" if result.ok else
                f"BROKEN at line {result.broken_at_line}: {result.reason}") + f" ({result.rows_checked} rows)")
            return EXIT_OK if result.ok else EXIT_ERROR
        if cmd == "config":
            return run_config(args, out, root)
    except state.DeskError as exc:
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
