"""Command line for the ESPN-fed leagues.

    python -m src.cli datasvc nba refresh [--min-age-minutes 180] [--max-requests N]
    python -m src.cli datasvc all refresh --min-age-minutes 180        # the default scheduled set
    python -m src.cli datasvc ncaab backfill --from 2025-11-01 --to 2026-03-31
    python -m src.cli datasvc nhl schedule --date 2026-01-15 [--as-of ISO]
    python -m src.cli datasvc nba box --game-id 401810433
    python -m src.cli datasvc epl standings | injuries | teams | players --team ARS | status | check
    python -m src.cli datasvc nhl averages [--team BUF] [--split home|away|wins|losses|last10] [--as-of ISO]
    python -m src.cli datasvc nba averages --players [--team ORL] [--min-games 3]     # or --player-id ID
    python -m src.cli datasvc nhl splits --team BUF      # home/away, wins/losses, last 5/10 side by side
    python -m src.cli datasvc nba refresh --pbp          # also store play-by-play for completed games
    python -m src.cli datasvc nhl pbp-fill --limit 50    # play-by-play for stored games that lack it
    python -m src.cli datasvc nhl pbp --game-id 401891776 [--source nhle] [--scoring-only]

The same commands are reachable as `python -m src.datasvc.cli espn <league> <thing>`. `src.cli datasvc ufc|nfl ...`
forwards to the UFC and NFL commands. Exit codes: 0 ok, 1 a failed parity check, 2 a blocked source or a
bad argument.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import List, Optional

from src.datasvc.espn import leagues as lg, pipeline, service as svc
from src.datasvc.espn.store import EspnStore
from src.datasvc.http import PoliteFetcher

THINGS = ("refresh", "backfill", "teams", "players", "schedule", "box", "history", "standings", "injuries",
          "status", "check", "averages", "splits", "pbp", "pbp-fill")


def build_parser(prog: str = "datasvc") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="ESPN-fed league data (NBA, NHL, college, soccer)")
    p.add_argument("league", help="a league code (%s) or 'all' (the scheduled set)" % ", ".join(sorted(lg.LEAGUES)))
    p.add_argument("thing", choices=THINGS)
    p.add_argument("--date", default=None, help="YYYY-MM-DD (schedule filter; refresh treats it as today)")
    p.add_argument("--from", dest="start", default=None, help="backfill first day")
    p.add_argument("--to", dest="end", default=None, help="backfill last day (default today)")
    p.add_argument("--season", type=int, default=None)
    p.add_argument("--team", default=None, help="team id, abbreviation or name")
    p.add_argument("--player-id", default=None)
    p.add_argument("--search", default=None, help="player name search")
    p.add_argument("--game-id", default=None)
    p.add_argument("--as-of", default=None, help="ISO instant (YYYY-MM-DDTHH:MM:SSZ): read as observed by then")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--max-requests", type=int, default=None, help="stop cleanly after this many network requests")
    p.add_argument("--delay", type=float, default=0.35, help="seconds between requests")
    p.add_argument("--min-age-minutes", type=float, default=0, help="refresh: skip if refreshed more recently")
    p.add_argument("--force", action="store_true")
    p.add_argument("--rosters", dest="rosters", action="store_true", default=None, help="refresh rosters now")
    p.add_argument("--no-rosters", dest="rosters", action="store_false")
    p.add_argument("--days-back", type=int, default=2)
    p.add_argument("--days-ahead", type=int, default=2)
    p.add_argument("--no-box", action="store_true", help="backfill: scoreboards only")
    p.add_argument("--root", default=None, help="store directory (default data/datasvc/espn)")
    p.add_argument("--split", default="all", help="averages: all, home, away, wins, losses, starter, bench, lastN")
    p.add_argument("--last", type=int, default=None, help="averages: only the last N games (same as --split lastN)")
    p.add_argument("--players", action="store_true", help="averages: player lines instead of team lines")
    p.add_argument("--min-games", type=int, default=1, help="averages --players: smallest sample listed")
    p.add_argument("--season-type", default="regular", help="averages: regular (default), all, or ESPN type numbers")
    p.add_argument("--strict", action="store_true", help="averages --as-of: only games we saw final by then")
    p.add_argument("--pbp", dest="with_pbp", action="store_true", help="refresh/backfill: store play-by-play too")
    p.add_argument("--source", default=None, choices=("espn", "nhle"), help="pbp: which stored source to read/fill")
    p.add_argument("--period", type=int, default=None, help="pbp: one period only")
    p.add_argument("--scoring-only", action="store_true", help="pbp: scoring plays only")
    return p


def _codes(league: str) -> List[str]:
    return list(lg.DEFAULT_REFRESH) if league == "all" else [lg.get(league).code]


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, default=str, ensure_ascii=False))


def _summary(s: dict) -> int:
    _print({k: v for k, v in s.items() if k != "errors"})
    if s["errors"]:
        print(f"{len(s['errors'])} error(s); first: {s['errors'][:3]}")
    return 2 if (s.get("stopped") or "").startswith("source blocked") else 0


def run(argv: Optional[List[str]] = None, *, prog: str = "datasvc") -> int:
    args = build_parser(prog).parse_args(argv)
    store = EspnStore(args.root) if args.root else EspnStore()
    try:
        codes = _codes(args.league)
    except KeyError as exc:
        print(str(exc))
        return 2
    code = 0
    if args.thing in ("refresh", "backfill"):
        for c in codes:
            fetcher = PoliteFetcher(delay_s=args.delay, max_requests=args.max_requests)
            if args.thing == "refresh":
                s = pipeline.refresh(c, store=store, fetcher=fetcher,
                                     today=date.fromisoformat(args.date) if args.date else None,
                                     days_back=args.days_back, days_ahead=args.days_ahead,
                                     min_age_minutes=args.min_age_minutes, force=args.force, rosters=args.rosters,
                                     pbp=args.with_pbp)
            else:
                if not args.start:
                    print("backfill needs --from YYYY-MM-DD")
                    return 2
                s = pipeline.backfill(c, date.fromisoformat(args.start),
                                      date.fromisoformat(args.end) if args.end else date.today(),
                                      store=store, fetcher=fetcher, box=not args.no_box, pbp=args.with_pbp)
            code = max(code, _summary(s))
        return code
    if args.thing == "pbp-fill":
        for c in codes:
            fetcher = PoliteFetcher(delay_s=args.delay, max_requests=args.max_requests)
            code = max(code, _summary(pipeline.fill_pbp(
                c, store=store, fetcher=fetcher, season=args.season, limit=args.limit,
                sources=(args.source,) if args.source else ("espn", "nhle"))))
        return code
    if args.thing == "status":
        _print(pipeline.status(store, None if args.league == "all" else codes))
        return 0
    if args.thing == "check":
        report = pipeline.check(store, None if args.league == "all" else codes)
        _print(report)
        return 0 if report["ok"] else 1
    if args.league == "all":
        print("this command needs one league")
        return 2
    service = svc.EspnService(store)
    c = codes[0]
    if args.thing == "teams":
        out = service.teams(c, as_of=args.as_of)
    elif args.thing == "players":
        out = service.players(c, team=args.team, search=args.search, as_of=args.as_of)
    elif args.thing == "schedule":
        out = service.schedule(c, date=args.date, season=args.season, team=args.team, as_of=args.as_of)
    elif args.thing == "box":
        if not args.game_id:
            print("box needs --game-id")
            return 2
        out = service.game(c, args.game_id, as_of=args.as_of)
    elif args.thing == "history":
        if args.player_id:
            out = service.player_history(c, args.player_id, limit=args.limit, as_of=args.as_of)
        elif args.team:
            out = service.team_history(c, args.team, limit=args.limit, as_of=args.as_of)
        else:
            print("history needs --team or --player-id")
            return 2
    elif args.thing == "averages":
        common = dict(season=args.season, as_of=args.as_of, season_type=args.season_type, strict=args.strict)
        if args.players or args.player_id:
            out = service.player_averages(c, args.player_id, team=args.team, split=args.split, last=args.last,
                                          min_games=args.min_games, **common)
        else:
            out = service.team_averages(c, args.team, split=args.split, last=args.last, **common)
    elif args.thing == "splits":
        common = dict(season=args.season, as_of=args.as_of, season_type=args.season_type, strict=args.strict)
        if args.player_id:
            out = service.player_splits(c, args.player_id, **common)
        elif args.team:
            out = service.team_splits(c, args.team, **common)
        else:
            print("splits needs --team or --player-id")
            return 2
    elif args.thing == "pbp":
        if not args.game_id:
            print("pbp needs --game-id")
            return 2
        out = service.play_by_play(c, args.game_id, source=args.source, as_of=args.as_of, period=args.period,
                                   scoring_only=args.scoring_only, strict=args.strict)
    elif args.thing == "standings":
        out = service.standings(c, season=args.season, as_of=args.as_of)
    else:
        out = service.injuries(c, team=args.team, as_of=args.as_of)
    _print(out)
    return 0 if out.get("available") else 2


def register(sport) -> None:
    """Add `espn <league> <thing>` to the data service's top-level subparsers (src/datasvc/cli.py)."""
    p = sport.add_parser("espn", help="ESPN-fed leagues: NBA, NHL, college football/basketball, soccer",
                         add_help=False)
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=lambda a: run(a.rest, prog="datasvc espn"))


def main(argv: Optional[List[str]] = None) -> int:
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
