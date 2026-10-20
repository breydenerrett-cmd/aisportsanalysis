"""Command line for the football-data history.

    python -m src.datasvc.cli soccer import --league epl --season 2025 --csv E0.csv     # a file you downloaded
    python -m src.datasvc.cli soccer fetch --league epl --from 2015 --to 2025 --i-have-permission
    python -m src.datasvc.cli soccer match --league epl [--season 2025] [--espn-root DIR]
    python -m src.datasvc.cli soccer odds --league epl --game-id 401878769
    python -m src.datasvc.cli soccer status

`fetch` refuses without --i-have-permission: the site's terms bar commercial and automated use (see the
docstring of src/datasvc/soccer/footballdata.py). Exit codes: 0 ok, 2 refused / bad argument.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.datasvc.espn.store import EspnStore
from src.datasvc.http import PoliteFetcher
from src.datasvc.soccer import footballdata as fd, match as matcher, service as svc


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_parser(prog: str = "datasvc soccer") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="football-data.co.uk results and odds")
    p.add_argument("thing", choices=("import", "fetch", "match", "odds", "status"))
    p.add_argument("--league", default="epl", help=", ".join(fd.LEAGUES))
    p.add_argument("--season", type=int, default=None, help="start year (2025 = 2025/26)")
    p.add_argument("--from", dest="first", type=int, default=fd.FIRST_SEASON)
    p.add_argument("--to", dest="last", type=int, default=None)
    p.add_argument("--csv", default=None)
    p.add_argument("--game-id", default=None)
    p.add_argument("--i-have-permission", action="store_true",
                   help="the operator has football-data.co.uk's permission for automated/commercial use")
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--max-requests", type=int, default=40)
    p.add_argument("--root", default=None, help="football-data store (default data/datasvc/footballdata)")
    p.add_argument("--espn-root", default=None, help="ESPN store to join against (default data/datasvc/espn)")
    return p


def run(argv: Optional[List[str]] = None, *, prog: str = "datasvc soccer") -> int:
    args = build_parser(prog).parse_args(argv)
    if args.league not in fd.LEAGUES and args.thing != "status":
        print(f"unknown league {args.league!r}; known: {', '.join(fd.LEAGUES)}")
        return 2
    store = fd.FootballDataStore(args.root) if args.root else fd.FootballDataStore()
    if args.thing == "import":
        if not (args.csv and args.season is not None):
            print("import needs --csv FILE and --season START_YEAR")
            return 2
        print(json.dumps(fd.import_csv(store, args.league, args.season, Path(args.csv), _now()), indent=1))
        store.write_manifest(args.league)
        return 0
    if args.thing == "fetch":
        if not args.i_have_permission:
            print(fd.TERMS_NOTICE)
            return 2
        last = args.last if args.last is not None else datetime.now(timezone.utc).year
        fetcher = PoliteFetcher(delay_s=args.delay, max_requests=args.max_requests)
        out = fd.fetch_range(store, fetcher, args.league, args.season or args.first, args.season or last,
                             accept_terms=True, observed_utc=_now())
        store.write_manifest(args.league)
        print(json.dumps(out, indent=1))
        return 0
    if args.thing == "match":
        espn = EspnStore(args.espn_root) if args.espn_root else EspnStore()
        rows = list(store.latest(args.league, "matches", args.season).values())
        if not rows:
            print(f"no {args.league} matches in the football-data store")
            return 2
        teams = {k[0]: v for k, v in espn.latest(args.league, "teams").items()}
        games = list(espn.latest(args.league, "games").values())
        joins, report = matcher.match(rows, games, teams)
        for j in joins:
            j["observed_utc"] = _now()
        store.append(args.league, "joins", joins)
        store.write_manifest(args.league)
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return 0
    if args.thing == "odds":
        if not args.game_id:
            print("odds needs --game-id (an ESPN game id)")
            return 2
        out = svc.SoccerHistoryService(store).for_game(args.league, args.game_id)
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0 if out.get("available") else 2
    status = {}
    for code in fd.LEAGUES:
        m = store.read_manifest(code)
        if m:
            status[code] = {n: f.get("records") for n, f in sorted((m.get("files") or {}).items())}
    print(json.dumps(status, indent=1))
    return 0


def register(sport) -> None:
    p = sport.add_parser("soccer", help="football-data.co.uk results + open/closing odds (gated; read the terms)",
                         add_help=False)
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=lambda a: run(a.rest, prog="datasvc soccer"))


def main(argv: Optional[List[str]] = None) -> int:
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
