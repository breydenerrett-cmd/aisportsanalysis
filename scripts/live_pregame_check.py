"""Read-only pre-game context check for MLB (R16-L2).

WHY THIS EXISTS
----------------
`docs/LIVE_BETTING_SYSTEM.md` section 2.3 (D1, D2, D3) documents that the
shipped `live_window.pregame_context` returns a favourite of None for every
MLB game -- it reads a game shape `mlb.fetch_games()` never returns, and a
`prices.snapshot()` key that does not exist. This script is the acceptance
check for the fix: it prints, per game, exactly what a correct pre-game
context looks like, using the pure builder in
`src.pipeline.livefeed_mlb.build_pregame_context` -- the one place the fixed
logic lives (see that module's docstring for why it is not in
`live_window.py`).

NO PAID API CALL. The only network read is `mlb.fetch_games` (free, keyless,
MLB Stats API); every odds row and gamekey row is read from local stores
already on disk.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Same two lines every script in this directory carries: run directly, the
# repo root is not on sys.path and every src import fails.
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.board import gamekey  # noqa: E402
from src.paths import processed_path
from src.pipeline import livefeed_mlb, snapshots
from src.providers import mlb


def _load_odds_rows(date: str) -> list:
    """Every MLB moneyline multibook row whose commence_time falls on
    `date` (official ET date) -- pregame AND in-play both included; the
    builder itself filters to strictly-before-commence_time (D2)."""
    rows = snapshots.moneyline_rows(snapshots.read_multibook(sport="mlb"))
    return [r for r in rows if snapshots.official_date(r.get("commence_time")) == date]


def run(date: str, *, fetch_games=mlb.fetch_games, load_map=gamekey.load_map,
        load_odds_rows=_load_odds_rows, now=None) -> dict:
    """Build and return the pre-game context for one date. No printing here
    -- kept separate from `main` so a test can call this without capturing
    stdout."""
    games = fetch_games(date)
    odds_rows = load_odds_rows(date)
    gamekey_map = load_map()
    clock = now or datetime.now(timezone.utc)
    return livefeed_mlb.build_pregame_context(games, odds_rows, gamekey_map, clock)


def _fmt_prob(value):
    return "--" if value is None else f"{value:.3f}"


def render(context: dict) -> str:
    """One line per game, oldest game_pk-sorted for a stable, diffable
    output. Never reimplements the builder's logic -- purely presentational."""
    lines = []
    for game_pk in sorted(context, key=lambda pk: str(pk)):
        row = context[game_pk]
        matchup = f"{row.get('away_team')} @ {row.get('home_team')}"
        if row.get("usable"):
            favorite_team = (row.get("home_team") if row.get("favorite") == "home"
                              else row.get("away_team"))
            starter = (row.get("starter_ids") or {}).get(row.get("favorite"))
            lines.append(
                f"{game_pk}  {matchup}  favorite={favorite_team} "
                f"({row.get('favorite')}) prob={_fmt_prob(row.get('favorite_prob'))} "
                f"books={row.get('book_count')} "
                f"newest_quote={row.get('newest_quote_utc')} "
                f"starter={starter}  USABLE"
            )
        else:
            lines.append(
                f"{game_pk}  {matchup}  NOT USABLE -- {row.get('reason')}"
            )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only MLB pre-game context check (no paid API call).")
    parser.add_argument("--date", required=True, help="ET date, YYYY-MM-DD")
    parser.add_argument("--sport", default="mlb", choices=["mlb"],
                         help="only mlb is wired for this check")
    args = parser.parse_args(argv)

    context = run(args.date)
    output = render(context)
    print(output if output else f"no MLB games found for {args.date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
