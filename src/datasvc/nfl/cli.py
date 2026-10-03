"""The `nfl` subcommands of the data service command line.

    python -m src.datasvc.cli nfl backfill --since 2021 [--player-since 2024] [--max-requests N]
    python -m src.datasvc.cli nfl backfill --seasons 2026,2025
    python -m src.datasvc.cli nfl update [--today YYYY-MM-DD]
    python -m src.datasvc.cli nfl status [--check]
    python -m src.datasvc.cli nfl matchup KC BUF [--season 2026 --week 5] [--as-of YYYY-MM-DD]
    python -m src.datasvc.cli nfl matchup --game-id 2026_05_TB_DAL

`src/datasvc/cli.py` calls `register` and nothing else from here; the UFC subcommands are not
touched. The handlers return the process exit code: 0 for success, 1 for a failed parity check,
2 for a source that blocked us (or an argument that names nothing).
"""

from __future__ import annotations

import json
from datetime import date

from src.datasvc.http import PoliteFetcher
from src.datasvc.nfl import features, matchup as matchup_mod, pipeline
from src.datasvc.nfl.store import NflStore


def _seasons(args) -> list:
    if args.seasons:
        return [int(s) for s in str(args.seasons).split(",") if s.strip()]
    return list(range(int(args.since), pipeline.current_season() + 1))


def _fetcher(args) -> PoliteFetcher:
    return PoliteFetcher(delay_s=args.delay, max_requests=args.max_requests)


def _print_summary(summary: dict) -> int:
    print(json.dumps({k: v for k, v in summary.items() if k not in ("errors", "per_season")}, indent=1))
    if summary["errors"]:
        print(f"{len(summary['errors'])} error(s); first: {summary['errors'][:5]}")
    return 0 if not (summary["stopped"] or "").startswith("source blocked") else 2


def cmd_backfill(args) -> int:
    summary = pipeline.backfill(_seasons(args), fetcher=_fetcher(args), player_since=args.player_since)
    return _print_summary(summary)


def cmd_update(args) -> int:
    today = date.fromisoformat(args.today) if args.today else None
    return _print_summary(pipeline.update(today, fetcher=_fetcher(args)))


def cmd_status(args) -> int:
    store = NflStore()
    print(json.dumps(pipeline.status(store), indent=1))
    if not args.check:
        return 0
    report = pipeline.check(store)
    print(json.dumps(report, indent=1))
    return 0 if report["ok"] else 1


def cmd_matchup(args) -> int:
    store = NflStore()
    try:
        if args.game_id:
            game_id = args.game_id
        elif args.a and args.b:
            game_id = matchup_mod.find_game(store, args.a, args.b, season=args.season, week=args.week)["game_id"]
        else:
            print("give two teams (nfl matchup KC BUF) or --game-id")
            return 2
        sheet = matchup_mod.matchup(store, game_id, as_of=args.as_of)
    except (features.UnknownGame, features.UnknownTeam, LookupError, ValueError) as exc:
        print(str(exc))
        return 2
    print(json.dumps(sheet, indent=1, default=str))
    return 0


def register(sport) -> None:
    """Add `nfl` and its subcommands to the data service's top-level subparsers."""
    nfl = sport.add_parser("nfl", help="NFL games, team and player statistics, injuries (nflverse, CC BY 4.0)")
    cmd = nfl.add_subparsers(dest="command", required=True)

    def fetch_flags(p):
        p.add_argument("--max-requests", type=int, default=None, help="stop cleanly after this many network requests")
        p.add_argument("--delay", type=float, default=0.35, help="seconds between requests (default 0.35)")

    b = cmd.add_parser("backfill", help="every season from --since (or the listed --seasons)")
    group = b.add_mutually_exclusive_group(required=True)
    group.add_argument("--since", type=int, help="first season, through the current one")
    group.add_argument("--seasons", help="comma-separated seasons")
    b.add_argument("--player-since", type=int, default=None,
                   help="keep the player file (the largest) to seasons from this year on")
    fetch_flags(b)
    b.set_defaults(func=cmd_backfill)

    u = cmd.add_parser("update", help="the current season's new weeks and the schedule")
    u.add_argument("--today", default=None, help="treat this date as today (YYYY-MM-DD)")
    fetch_flags(u)
    u.set_defaults(func=cmd_update)

    s = cmd.add_parser("status", help="record counts and freshness; --check also runs the parity checks")
    s.add_argument("--check", action="store_true", help="run the parity and referential checks on the files")
    s.set_defaults(func=cmd_status)

    m = cmd.add_parser("matchup", help="the fact sheet for one game")
    m.add_argument("a", nargs="?", help="a team (KC, Chiefs)")
    m.add_argument("b", nargs="?", help="the other team")
    m.add_argument("--game-id", default=None, help="a game id (2026_05_TB_DAL) instead of two teams")
    m.add_argument("--season", type=int, default=None)
    m.add_argument("--week", type=int, default=None)
    m.add_argument("--as-of", default=None, help="not later than the kickoff; default the kickoff")
    m.set_defaults(func=cmd_matchup)
