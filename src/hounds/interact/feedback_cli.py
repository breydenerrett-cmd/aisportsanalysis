"""`python -m src.cli hounds feedback-digest|feedback-resolve`: the Good call / Bad call loop's owner commands.

The WHY, the day, the file and the backlog rules are in ``feedback_digest.py``. This file only parses arguments and prints.
No network, no model, no paid API; the email is off unless ``FEEDBACK_DIGEST_TO`` is set (and Resend is configured).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from src.hounds.interact import feedback_digest as fd
from src.hounds.interact import store

EXIT_OK, EXIT_ERROR = 0, 2


def add_parser(sub) -> None:
    cmd = sub.add_parser("hounds", help="hounds: the owner's feedback digest and fix notices")
    inner = cmd.add_subparsers(dest="hounds_command", required=True)
    d = inner.add_parser("feedback-digest", help="summarise a day of Good call / Bad call votes and chips, per hound and per chip")
    d.add_argument("--date", required=True, help="the Pacific day, YYYY-MM-DD (midnight to midnight)")
    d.add_argument("--backlog", action="store_true",
                   help="also file each new flagged issue in docs/BACKLOG.md (same chip twice on one hound, or any note)")
    d.add_argument("--backlog-file", dest="backlog_file", default=None, help="append here instead of docs/BACKLOG.md")
    d.add_argument("--out-dir", dest="out_dir", default=None, help="write the markdown here instead of the owner-output folder")
    d.add_argument("--no-email", dest="no_email", action="store_true", help="never send the opt-in email, even when it is configured")
    d.add_argument("--db", default=None, help="app database to read (default: the app database)")
    r = inner.add_parser("feedback-resolve", help="say a flagged issue is fixed; the members who voted see it on their next visit")
    r.add_argument("--id", required=True, help="the feedback id on the backlog line, e.g. FB-1A2B3C4D")
    r.add_argument("--note", required=True, help="what was fixed, in a sentence the member will read")
    r.add_argument("--db", default=None, help="app database (default: the app database)")
    a = inner.add_parser("add-sports", help="give a member hound more sports as a NEW VERSION (old version and record untouched)")
    a.add_argument("--id", required=True, help="the hound's current version id, e.g. u-f000af253e")
    a.add_argument("--sports", required=True, help="comma list of sport codes (nba,nhl,nfl,ncaaf,...) or 'all'")
    a.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the new rule and the notes; write nothing")
    a.add_argument("--db", default=None, help="app database (default: the app database)")


def digest(args, *, out: Callable = print, now: Optional[datetime] = None) -> int:
    db = Path(args.db) if args.db else None
    try:
        result = fd.build(args.date, db=db)
    except ValueError:
        out(f"ERROR: --date must be YYYY-MM-DD, got {args.date!r}")
        return EXIT_ERROR
    path = fd.save(result, Path(args.out_dir) if args.out_dir else None)
    out(f"saved {path}")
    if args.backlog:
        filed = fd.file_issues(result, path=Path(args.backlog_file) if args.backlog_file else None, db=db, now=now)
        out(f"backlog {filed['path']}: {len(filed['added'])} added, {len(filed['skipped'])} already there")
    if not args.no_email:
        sent = fd.email_digest(result)
        if sent:
            out("email: " + ", ".join(sent))
    out(fd.render(result))
    return EXIT_OK


def resolve(args, *, out: Callable = print, now: Optional[datetime] = None) -> int:
    try:
        done = store.resolve_issue(args.id.strip().upper(), args.note, now=now, db=Path(args.db) if args.db else None)
    except store.FeedbackError as exc:
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    out(f"resolved {done['feedback_id']}: {done['voters']} {'member' if done['voters'] == 1 else 'members'} will see "
        f"\"Fixed: {done['note']}\" on their next visit")
    return EXIT_OK


def add_sports_cmd(args, *, out: Callable = print) -> int:
    from src.hounds import add_sports, user_spec, user_store
    try:
        res = add_sports.apply(args.id.strip(), args.sports, dry_run=args.dry_run, db=Path(args.db) if args.db else None)
    except (add_sports.AddSportsError, user_spec.SpecError, user_store.StoreError) as exc:
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    out(("DRY RUN (nothing written): " if res["dry_run"] else "") + "adds " + ", ".join(res["added"]))
    for code, why in res["skipped"]:
        out(f"skipped {code}: {why}")
    for note in res["notes"]:
        out(f"note: {note}")
    out(f"rule: {res['sentence']}")
    if res["new_id"]:
        out(f"new version {res['new_id']} (the old version {res['old_id']} is retired with its record intact)")
    return EXIT_OK


def main(args, *, out: Callable = print) -> int:
    command = getattr(args, "hounds_command", None)
    if command == "feedback-digest":
        return digest(args, out=out)
    if command == "feedback-resolve":
        return resolve(args, out=out)
    if command == "add-sports":
        return add_sports_cmd(args, out=out)
    out(f"unknown hounds subcommand: {command}")
    return EXIT_ERROR
