"""`python -m src.cli jarvis brief --date YYYY-MM-DD [--as-of ISO]`: print the owner's pre-game briefing.

It prints the briefing in Pacific time, writes the JSON to the owner-output folder (``brief.output_dir``: beside the
app database, the Fly volume in production) and files every pick through the Apprentice recommendation store, so a
run is a PUBLICATION. ``--no-file`` is the dry run: it prints and writes nothing to the ledger. Reads stored files
only: no network, no paid API, no model call.
"""

from __future__ import annotations

import json
from datetime import date as date_cls
from pathlib import Path
from typing import Callable, Optional

from src.jarvis import board as bd
from src.jarvis import brief

EXIT_OK, EXIT_ERROR = 0, 2


def add_parser(sub) -> None:
    cmd = sub.add_parser("jarvis", help="Jarvis: the owner's paper-only pre-game briefing")
    inner = cmd.add_subparsers(dest="jarvis_command", required=True)
    b = inner.add_parser("brief", help="build, print, save and file the briefing for one date")
    b.add_argument("--date", required=True, help="the game date (Eastern), YYYY-MM-DD")
    b.add_argument("--as-of", dest="as_of", default=None,
                   help="ISO time the briefing is frozen at (default: now); rows observed after it are never read")
    b.add_argument("--sport", default="mlb", help="sport key in the stored boards (default mlb; others have no watch-file context)")
    b.add_argument("--no-file", dest="no_file", action="store_true",
                   help="dry run: print only; do not save the JSON or file recommendations")
    b.add_argument("--json", dest="as_json", action="store_true", help="print the JSON instead of the text")
    b.add_argument("--out-dir", dest="out_dir", default=None, help="write the JSON here instead of the owner-output folder")
    b.add_argument("--db", default=None, help="apprentice/app database to file into (default: the app database)")


def execute(args, *, out: Callable = print, now=None) -> int:
    try:
        date_cls.fromisoformat(args.date)
    except ValueError:
        out(f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}")
        return EXIT_ERROR
    as_of = None
    if args.as_of:
        as_of = bd.parse_time(args.as_of)
        if as_of is None:
            out(f"ERROR: --as-of must be an ISO time with a zone, got {args.as_of!r}")
            return EXIT_ERROR
    try:
        result = brief.build_briefing(args.date, as_of, sport=args.sport, now=now)
    except ValueError as exc:
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    code = EXIT_OK
    if not args.no_file:
        try:
            brief.file_picks(result, now=now, db=Path(args.db) if args.db else None)
        except Exception as exc:  # noqa: BLE001 -- say plainly that nothing was published
            out(f"ERROR: the picks could not be filed ({exc}); this briefing is NOT published")
            code = EXIT_ERROR
        path = brief.save(result, Path(args.out_dir) if args.out_dir else None)
        out(f"saved {path}")
    out(json.dumps(result, indent=2, sort_keys=True, default=str) if args.as_json
        else brief.resolve_tokens(brief.render(result)))
    return code


def main(args) -> int:
    if getattr(args, "jarvis_command", None) == "brief":
        return execute(args)
    print(f"unknown jarvis subcommand: {getattr(args, 'jarvis_command', None)}")
    return EXIT_ERROR
