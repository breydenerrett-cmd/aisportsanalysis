"""`python -m src.cli situation ingest-postseasons | rest-vs-rhythm`.

    ingest-postseasons   fetch earlier postseasons from MLB's free Stats API into the display-only
                         store (`postseason_history.py`). Polite (a pause between requests) and
                         cached, so a second run costs nothing. It writes only its own directory:
                         never the results store, never a training population.
    rest-vs-rhythm       the first factor test (`rest_vs_rhythm.py`): the Division Series, the bye
                         club against the club that played the Wild Card round, 2015 to 2025. Reads
                         the results store and the display-only store, calls nothing.

Both are research and display commands. They change no card, pick, gate or published result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from src.situation import postseason_history, rest_vs_rhythm

EXIT_OK, EXIT_ERROR = 0, 2


def add_parser(sub) -> None:
    cmd = sub.add_parser("situation", help="the situation layer: earlier postseasons and the first factor test")
    inner = cmd.add_subparsers(dest="situation_command", required=True)
    ing = inner.add_parser("ingest-postseasons",
                           help="fetch earlier postseasons into the display-only store (never a training population)")
    ing.add_argument("--start", type=int, default=postseason_history.FIRST_SEASON, help="first season (default 2015)")
    ing.add_argument("--end", type=int, default=2025,
                     help="last season (default 2025). 2023 on is also in the results store; it is fetched too "
                          "for its standings (exact records) and as a check on the parser")
    ing.add_argument("--refresh", action="store_true", help="fetch again even where the response is cached")
    ing.add_argument("--root", default=None, help="write the store here instead of data/research/postseason_history")
    test = inner.add_parser("rest-vs-rhythm", help="rest versus rhythm in the Division Series, 2015 to 2025")
    test.add_argument("--json", dest="as_json", action="store_true", help="print the whole result as JSON")
    test.add_argument("--markdown", action="store_true", help="print the series table as Markdown")
    test.add_argument("--start", type=int, default=rest_vs_rhythm.FIRST_SEASON)
    test.add_argument("--end", type=int, default=rest_vs_rhythm.LAST_SEASON)
    test.add_argument("--root", default=None, help="read the display-only store from here")


def execute_ingest(*, start: int, end: int, refresh: bool = False, root: Optional[str] = None,
                   get_json: Optional[Callable] = None, cache: Optional[Path] = None,
                   sleep: Optional[Callable] = None, out: Callable = print) -> int:
    if end < start:
        out(f"ERROR: --end {end} is before --start {start}")
        return EXIT_ERROR
    kwargs = {}
    if get_json is not None:
        kwargs["get_json"] = get_json
    if sleep is not None:
        kwargs["sleep"] = sleep
    manifest = postseason_history.ingest(
        range(start, end + 1), Path(root) if root else None, cache=cache if cache is not None else
        postseason_history.cache_root(), refresh=refresh,
        on_season=lambda season, games, records: out(f"  {season}: {games} postseason games, "
                                                     f"{records} club records"),
        **kwargs)
    out(f"store: {manifest['games']} games and {manifest['season_records']} club records over "
        f"{len(manifest['seasons'])} seasons ({manifest['seasons'][0] if manifest['seasons'] else 'none'} to "
        f"{manifest['seasons'][-1] if manifest['seasons'] else 'none'})")
    for err in manifest.get("errors") or []:
        out(f"  FAILED {err['season']}: {err['error']}")
    return EXIT_ERROR if manifest.get("errors") and not manifest["games"] else EXIT_OK


def load_inputs(root: Optional[str] = None, main: Optional[list] = None) -> tuple:
    """`(postseason game rows, regular-season records)` from the results store and the display-only
    store. The results store wins where both hold a game. A club's regular-season record is the
    standings' (every game, including the opening series abroad that the results store starts
    after) where the display store holds it, else the club's own regular-season games."""
    if main is None:
        from src.pipeline import history
        main = list(history.read_results().values())
    held = postseason_history.load(Path(root) if root else None)
    by_pk = {str(g["game_pk"]): g for g in held.games}
    by_pk.update({str(g["game_pk"]): g for g in main if g.get("game_type") in ("F", "D", "L", "W")})
    records = rest_vs_rhythm.records_from_games(main)
    records.update({k: dict(v) for k, v in held.season_records.items()})
    return list(by_pk.values()), records


def execute_rest_vs_rhythm(*, start: int, end: int, as_json: bool = False, markdown: bool = False,
                           root: Optional[str] = None, loader: Optional[Callable] = None,
                           out: Callable = print) -> int:
    games, records = loader() if loader is not None else load_inputs(root)
    result = rest_vs_rhythm.run(games, records, seasons=tuple(range(start, end + 1)))
    if as_json:
        out(json.dumps(result, indent=2, sort_keys=True, default=str))
    elif markdown:
        for line in rest_vs_rhythm.render_markdown_table(result):
            out(line)
    else:
        for line in rest_vs_rhythm.render_text(result):
            out(line)
    return EXIT_OK


def main(args) -> int:
    if args.situation_command == "ingest-postseasons":
        return execute_ingest(start=args.start, end=args.end, refresh=args.refresh, root=args.root)
    return execute_rest_vs_rhythm(start=args.start, end=args.end, as_json=args.as_json,
                                  markdown=args.markdown, root=args.root)
