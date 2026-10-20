"""Command line for the MLB statsapi box-score layer (forward only; the sealed window is enforced).

    python -m src.cli datasvc mlbbox refresh [--date D] [--min-age-minutes 180] [--max-requests N]
    python -m src.cli datasvc mlbbox schedule --date 2026-10-20
    python -m src.cli datasvc mlbbox box --game-id 849815
    python -m src.cli datasvc mlbbox history --team NYY | --player-id 660271
    python -m src.cli datasvc mlbbox averages [--team NYY] [--players] [--split home] [--as-of ISO]
    python -m src.cli datasvc mlbbox splits --team NYY | --player-id ID
    python -m src.cli datasvc mlbbox status | check

Exit codes: 0 ok, 1 failed parity check, 2 a blocked source, a sealed-window refusal or a bad argument.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import List, Optional

from src.datasvc.http import PoliteFetcher
from src.datasvc.mlb import box_service, seal, statsapi

THINGS = ("refresh", "schedule", "box", "history", "averages", "splits", "status", "check")


def build_parser(prog: str = "datasvc mlbbox") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="MLB statsapi box scores and player game lines (forward only)")
    p.add_argument("thing", choices=THINGS)
    p.add_argument("--date", default=None, help="YYYY-MM-DD (refresh: treat as today; schedule: the day)")
    p.add_argument("--team", default=None)
    p.add_argument("--player-id", default=None)
    p.add_argument("--game-id", default=None)
    p.add_argument("--season", type=int, default=None)
    p.add_argument("--split", default="all")
    p.add_argument("--last", type=int, default=None)
    p.add_argument("--players", action="store_true")
    p.add_argument("--min-games", type=int, default=1)
    p.add_argument("--season-type", default="regular")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--as-of", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--max-requests", type=int, default=None)
    p.add_argument("--delay", type=float, default=0.35)
    p.add_argument("--min-age-minutes", type=float, default=0)
    p.add_argument("--force", action="store_true")
    p.add_argument("--days-back", type=int, default=1)
    p.add_argument("--days-ahead", type=int, default=1)
    p.add_argument("--root", default=None, help="store directory (default data/datasvc)")
    return p


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, default=str, ensure_ascii=False))


def run(argv: Optional[List[str]] = None, *, prog: str = "datasvc mlbbox") -> int:
    args = build_parser(prog).parse_args(argv)
    store = statsapi.MlbBoxStore(args.root) if args.root else statsapi.MlbBoxStore()
    if args.thing == "refresh":
        try:
            today = date.fromisoformat(args.date) if args.date else None
        except ValueError:
            print(f"--date must be YYYY-MM-DD, got {args.date!r}")
            return 2
        s = statsapi.refresh(store=store, fetcher=PoliteFetcher(delay_s=args.delay, max_requests=args.max_requests),
                             today=today, days_back=args.days_back, days_ahead=args.days_ahead,
                             min_age_minutes=args.min_age_minutes, force=args.force)
        _print({k: v for k, v in s.items() if k != "errors"})
        if s["errors"]:
            print(f"{len(s['errors'])} error(s); first: {s['errors'][:3]}")
        stopped = s.get("stopped") or ""
        return 2 if stopped.startswith(("source blocked", "sealed window")) else 0
    if args.thing == "status":
        _print(statsapi.status(store))
        return 0
    if args.thing == "check":
        report = statsapi.check(store)
        _print(report)
        return 0 if report["ok"] else 1
    svc = box_service.MlbBoxService(store)
    common = dict(season=args.season, as_of=args.as_of, season_type=args.season_type, strict=args.strict)
    if args.thing == "schedule":
        out = svc.schedule("mlb", date=args.date, team=args.team, season=args.season, as_of=args.as_of)
    elif args.thing == "box":
        if not args.game_id:
            print("box needs --game-id")
            return 2
        out = svc.game("mlb", args.game_id, as_of=args.as_of)
    elif args.thing == "history":
        if args.player_id:
            out = svc.player_history("mlb", args.player_id, limit=args.limit, as_of=args.as_of)
        elif args.team:
            out = svc.team_history("mlb", args.team, limit=args.limit, as_of=args.as_of)
        else:
            print("history needs --team or --player-id")
            return 2
    elif args.thing == "averages":
        if args.players or args.player_id:
            out = svc.player_averages("mlb", args.player_id, team=args.team, split=args.split, last=args.last,
                                      min_games=args.min_games, **common)
        else:
            out = svc.team_averages("mlb", args.team, split=args.split, last=args.last, **common)
    else:
        if args.player_id:
            out = svc.player_splits("mlb", args.player_id, **common)
        elif args.team:
            out = svc.team_splits("mlb", args.team, **common)
        else:
            print("splits needs --team or --player-id")
            return 2
    _print(out)
    return 0 if out.get("available") else 2


def register(sport) -> None:
    p = sport.add_parser("mlbbox", help="MLB statsapi box scores and player lines, forward only (sealed window enforced)",
                         add_help=False)
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=lambda a: run(a.rest, prog="datasvc mlbbox"))


def main(argv: Optional[List[str]] = None) -> int:
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
