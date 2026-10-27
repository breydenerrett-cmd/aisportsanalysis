"""`python -m src.cli announce`: the owner's one-time member announcements (src/appstate/announcements.py).

    announce --user 12 --kind kennel_fire [--steps-file F] [--db PATH]   write one (steps default to config/announcements/<kind>_steps.json)
    announce --list [--user 12]                                          every announcement and whether it was seen
    announce --find-user u-f000af253e                                    print the owner's user id (and name) of a hound

No network, no model. Nothing here is a member route: members can only read and dismiss.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from src import paths
from src.appstate import announcements

EXIT_OK, EXIT_ERROR = 0, 2


def default_steps_path(kind: str) -> Path:
    return paths.repo_root() / "config" / "announcements" / f"{kind}_steps.json"


def add_parser(sub) -> None:
    cmd = sub.add_parser("announce", help="one-time member announcements: create, list, find a hound's owner")
    cmd.add_argument("--user", type=int, default=None, help="the member's user id")
    cmd.add_argument("--kind", default=None, help=f"one of {', '.join(announcements.KINDS)}")
    cmd.add_argument("--steps-file", dest="steps_file", default=None, help="JSON list of the what's-new lines (default: config/announcements/<kind>_steps.json)")
    cmd.add_argument("--list", dest="list_all", action="store_true", help="list announcements (with --user: that member's)")
    cmd.add_argument("--find-user", dest="find_user", default=None, help="print the owner user id of this hound id")
    cmd.add_argument("--db", default=None, help="app database (default: the app database)")


def main(args, *, out: Callable = print) -> int:
    db = Path(args.db) if args.db else None
    if args.find_user:
        from src.hounds import user_store
        hound = user_store.get_hound(args.find_user.strip(), db=db)
        if hound is None:
            out(f"ERROR: no hound {args.find_user}")
            return EXIT_ERROR
        out(f"user_id {hound['owner_user_id']}  (hound {hound['id']}, {hound['name']}, status {hound['status']})")
        for v in user_store.lineage(hound["id"], db=db):            # an edit retires a version: show which one is current
            out(f"  v{v['version_no']}  {v['id']}  {v['status']}  sports {','.join(v['spec'].get('sports') or [])}")
        return EXIT_OK
    if args.list_all:
        rows = announcements.list_all(user_id=args.user, db=db)
        for r in rows:
            out(f"{r['id']}  user {r['user_id']}  {r['kind']}  created {r['created_utc']}  "
                + (f"seen {r['seen_utc']}" if r["seen_utc"] else "UNSEEN"))
        if not rows:
            out("no announcements")
        return EXIT_OK
    if args.user is None or not args.kind:
        out("ERROR: --user and --kind are required (or use --list / --find-user)")
        return EXIT_ERROR
    path = Path(args.steps_file) if args.steps_file else default_steps_path(args.kind)
    try:
        steps = json.loads(path.read_text(encoding="utf-8"))
        row = announcements.add(args.user, args.kind, steps, db=db)
    except (OSError, ValueError) as exc:      # AnnouncementError and bad JSON are both ValueErrors
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    out(f"announcement {row['id']} for user {row['user_id']} ({row['kind']}, {len(row['steps'])} steps) will show on their next page load")
    return EXIT_OK
