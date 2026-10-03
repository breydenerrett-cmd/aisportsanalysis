"""Command line for the data service.

    python -m src.datasvc.cli ufc backfill --since 2019 [--max-requests N] [--no-profiles]
    python -m src.datasvc.cli ufc backfill --years 2026,2025
    python -m src.datasvc.cli ufc update [--today YYYY-MM-DD]
    python -m src.datasvc.cli ufc status
    python -m src.datasvc.cli ufc matchup "Fighter A" "Fighter B" [--as-of YYYY-MM-DD]

    python -m src.datasvc.cli nfl backfill --since 2021 [--player-since 2024] [--max-requests N]
    python -m src.datasvc.cli nfl update [--today YYYY-MM-DD]
    python -m src.datasvc.cli nfl status [--check]
    python -m src.datasvc.cli nfl matchup KC BUF [--season 2026 --week 5] [--as-of YYYY-MM-DD]
    (the NFL handlers live in src/datasvc/nfl/cli.py)

Kept apart from src/cli.py so the data service can grow without touching
LineHound's own command line.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone

from src.datasvc.http import PoliteFetcher
from src.datasvc.nfl import cli as nfl_cli
from src.datasvc.ufc import pipeline
from src.datasvc.ufc.store import UfcStore


def _years(args) -> list:
    if args.years:
        return [int(y) for y in str(args.years).split(",") if y.strip()]
    first = int(args.since)
    return list(range(first, datetime.now(timezone.utc).year + 1))


def _fetcher(args) -> PoliteFetcher:
    return PoliteFetcher(delay_s=args.delay, max_requests=args.max_requests)


def cmd_backfill(args) -> int:
    summary = pipeline.backfill(_years(args), fetcher=_fetcher(args), stats=not args.no_stats,
                                odds=not args.no_odds, profiles=not args.no_profiles)
    print(json.dumps({k: v for k, v in summary.items() if k != "errors"}, indent=1))
    if summary["errors"]:
        print(f"{len(summary['errors'])} error(s); first: {summary['errors'][:5]}")
    return 0 if not (summary["stopped"] or "").startswith("source blocked") else 2


def cmd_update(args) -> int:
    today = date.fromisoformat(args.today) if args.today else None
    summary = pipeline.update(today, fetcher=_fetcher(args), profiles=not args.no_profiles)
    print(json.dumps({k: v for k, v in summary.items() if k != "errors"}, indent=1))
    if summary["errors"]:
        print(f"{len(summary['errors'])} error(s); first: {summary['errors'][:5]}")
    return 0 if not (summary["stopped"] or "").startswith("source blocked") else 2


def cmd_status(args) -> int:
    print(json.dumps(pipeline.status(), indent=1))
    return 0


def cmd_matchup(args) -> int:
    from src.datasvc import names
    from src.datasvc.ufc import fighters as fighters_mod
    from src.datasvc.ufc import matchup as matchup_mod
    store = UfcStore()
    index = fighters_mod.name_index(store.fighters)
    ids = []
    for query in (args.a, args.b):
        result = names.match(query, index)
        if result.best is None:
            label = "is ambiguous" if result.ambiguous else "was not found"
            print(f"'{query}' {label}. Candidates: {result.candidates}")
            return 2
        ids.append(result.best)
    sheet = matchup_mod.matchup(store, ids[0], ids[1], as_of=args.as_of)
    print(json.dumps(sheet, indent=1, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.datasvc.cli", description="LineHound data service")
    sport = parser.add_subparsers(dest="sport", required=True)
    ufc = sport.add_parser("ufc", help="UFC events, bouts, fighters, statistics and odds (ESPN, UFC.com)")
    cmd = ufc.add_subparsers(dest="command", required=True)

    def fetch_flags(p):
        p.add_argument("--max-requests", type=int, default=None, help="stop cleanly after this many network requests")
        p.add_argument("--delay", type=float, default=0.35, help="seconds between requests (default 0.35)")
        p.add_argument("--no-profiles", action="store_true", help="skip UFC.com career profiles")

    b = cmd.add_parser("backfill", help="every event of the given years")
    group = b.add_mutually_exclusive_group(required=True)
    group.add_argument("--since", type=int, help="first year, through the current year")
    group.add_argument("--years", help="comma-separated years")
    b.add_argument("--no-stats", action="store_true")
    b.add_argument("--no-odds", action="store_true")
    fetch_flags(b)
    b.set_defaults(func=cmd_backfill)

    u = cmd.add_parser("update", help="recent results and the next three weeks of cards")
    u.add_argument("--today", default=None)
    fetch_flags(u)
    u.set_defaults(func=cmd_update)

    s = cmd.add_parser("status", help="record counts and freshness")
    s.set_defaults(func=cmd_status)

    m = cmd.add_parser("matchup", help="the fact sheet for two fighters")
    m.add_argument("a")
    m.add_argument("b")
    m.add_argument("--as-of", default=None)
    m.set_defaults(func=cmd_matchup)
    nfl_cli.register(sport)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
