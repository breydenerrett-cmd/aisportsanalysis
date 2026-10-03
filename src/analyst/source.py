"""Where the analyst's inputs come from: the same stores the game page reads.

This is the only module in the package that touches disk or the schedule
provider. Everything it returns is plain data handed to `packet.build_packet`,
so the packet itself stays pure and testable.

It reads nothing the product does not already read. The game payload is built
by the same domain path `api/games.py` uses (`briefing.build_slate` over the
same enrichment inputs, serialised by `gamepayload.build_advanced_view`); the
prices come from the multi-book, derivative and prop stores; the repo's own
player-prop board supplies the model probability on a prop. No Odds API call
is made here: those stores are filled by the capture jobs.

STORES ARE STREAMED. Production has run out of memory on whole-store reads
(odds_multibook is ~38 MB, batter_props ~68 MB). Every store below is read one
line at a time with a cheap text prefilter on the event id; the parsed row is
then checked exactly, so the prefilter may only ever over-match.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping, Optional

from src.analysis import gamepayload
from src.paths import processed_path
from src.pipeline import (batter_props, briefing, derivative_markets, enrichment,
                          history, snapshots, store_archive)
from src.providers import mlb

PITCHER_PROP_STORE = processed_path("prop_prices.jsonl")


def _canon(team) -> str:
    return snapshots._canonical_club(team)


def slate_payloads(date: str, *, fetch_games: Callable = mlb.fetch_games,
                   now: Optional[datetime] = None) -> list:
    """[{"payload": {"advanced": ...}, "game": {...}}] for one date, in
    schedule order. Raises `mlb.MLBError` when the schedule is unreachable."""
    now = now or datetime.now(timezone.utc)
    games = fetch_games(date)
    store = history.read_results()
    inputs = enrichment.enrichment_inputs(games, date, store)
    inputs.setdefault("date", date)
    slate = briefing.build_slate(games, store, **inputs)
    out = []
    for entry in slate["games"]:
        advanced = gamepayload.build_advanced_view(entry, now=now)
        out.append({"payload": {"advanced": advanced}, "game": advanced["game"]})
    return out


def stats_through(date: str, store: Optional[Mapping] = None) -> Optional[str]:
    """The newest game date in the results store strictly before `date`: the
    as-of date of every team and starter stat built from it."""
    store = history.read_results() if store is None else store
    days = [str(r.get("date")) for r in store.values()
            if r.get("date") and str(r.get("date")) < date]
    return max(days) if days else None


def _iter_rows(path, needles: Iterable[str], *, since: Optional[str] = None):
    wanted = tuple(needles)
    if not wanted or not store_archive.exists(path):
        return
    for line in store_archive.iter_lines(path, since=since):
        if not any(n in line for n in wanted):
            continue
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def price_rows(date: str, games: Iterable[Mapping], *,
               multibook_path=None, derivative_path=None,
               batter_path=None, pitcher_path=None) -> dict:
    """{game_pk: {"multibook": [...], "team_totals": [...], "batter_props": [...],
    "pitcher_props": [...], "team_names": {...}}} for the slate.

    A game is matched in the multi-book store by its canonical (away, home,
    official date), then every other store is read by that game's event id.
    A game with no multi-book rows has no event id, so it has no props or team
    totals either, and the packet says so in `missing`. Both halves of a
    doubleheader are left unpriced for the reason given in the loop below.
    """
    games = list(games)
    wanted = {}
    doubleheaders = set()
    for g in games:
        key = (_canon(g.get("away_team")), _canon(g.get("home_team")), date)
        if key in wanted:
            doubleheaders.add(key)
        wanted[key] = g
    since, until = snapshots.window_for_date(date)
    by_pk: dict = {g.get("game_pk"): {"multibook": [], "team_totals": [],
                                       "batter_props": [], "pitcher_props": [],
                                       "team_names": {}, "event_id": None}
                   for g in games}
    events: dict = {}
    path = multibook_path or snapshots.DEFAULT_MULTIBOOK_PATH
    for row in snapshots.iter_multibook(path, since=since, until=until):
        key = snapshots.game_key(row.get("away_team"), row.get("home_team"),
                                 row.get("commence_time"))
        game = wanted.get(key)
        if game is None:
            continue
        if key in doubleheaders:
            # The price feed names a game by its two clubs and start time, and
            # the two halves of a doubleheader share both clubs and a date.
            # Pooling their rows would hand each packet a mix of two events'
            # quotes, so neither half is priced: no packet is better than a
            # wrong one, and the run skips them with "prices no market".
            continue
        slot = by_pk[game.get("game_pk")]
        slot["multibook"].append(row)
        events.setdefault(game.get("game_pk"), Counter())[row.get("event_id")] += 1
        slot["team_names"] = {"away": row.get("away_team"), "home": row.get("home_team")}
    event_to_pk = {}
    for pk, counter in events.items():
        event_id = counter.most_common(1)[0][0]
        by_pk[pk]["event_id"] = event_id
        if event_id:
            event_to_pk[event_id] = pk
    needles = list(event_to_pk)
    for key, store, dest in (
            ("team_totals", derivative_path or derivative_markets.PROCESSED_STORE, "team_totals"),
            ("batter_props", batter_path or batter_props.PROCESSED_STORE, "batter_props"),
            ("pitcher_props", pitcher_path or PITCHER_PROP_STORE, "pitcher_props")):
        for row in _iter_rows(store, needles, since=since):
            pk = event_to_pk.get(row.get("event_id"))
            if pk is None:
                continue
            if key == "team_totals" and row.get("market") != "team_totals":
                continue
            by_pk[pk][dest].append(row)
    return by_pk


def mlb_situation_provider(*, results: Optional[Iterable[Mapping]] = None,
                           covered_dates: Optional[Iterable[str]] = None,
                           history_loader: Optional[Callable] = None) -> Callable:
    """A callable `item -> situation record` for arm B, reading the stores once on first use.

    It reads what the game page reads (the results store) plus two things only the situation layer
    needs: the ingest manifest, to know which days between the newest stored game and this one are
    confirmed fetched, and the display-only postseason history (earlier Octobers), which extends the
    long-memory facts and nothing else. A missing history is an empty one. `results`,
    `covered_dates` and `history_loader` are the test seams; production passes none.
    """
    from src.situation import mlb as situation_mlb
    from src.situation import postseason_history

    state: dict = {}

    def provider(item: Mapping) -> dict:
        if not state:
            rows = list(results) if results is not None else list(history.read_results().values())
            if covered_dates is not None:
                covered = set(covered_dates)
            else:
                manifest = history.read_manifest()
                covered = {d for d, entry in manifest.items() if not (entry or {}).get("pending")}
            held = (history_loader or postseason_history.load)()
            state.update(rows=rows, covered=covered, extra=list(held.games), records=dict(held.season_records))
        game = ((item.get("payload") or {}).get("advanced") or {}).get("game") or {}
        return situation_mlb.situation_for_game(
            game, state["rows"], extra_games=state["extra"], season_records=state["records"],
            covered_dates=state["covered"])

    return provider


def prop_board_for(date: str, batter_rows_by_pk: Mapping) -> dict:
    """{game_pk: [contract, ...]} from the repo's own prop board, built from
    only that game's prop rows. Failure is a missing board, never an error:
    the packet falls back to a deterministic order and says nothing was
    model-ranked."""
    from src.report import props as props_mod

    out: dict = {}
    for pk, rows in batter_rows_by_pk.items():
        if not rows:
            out[pk] = []
            continue
        try:
            board = props_mod.board_for_date(date, limit=props_mod.MAX_LIMIT, prop_rows=rows)
        except Exception:  # noqa: BLE001 -- a board gap must not stop the analysis
            out[pk] = []
            continue
        out[pk] = list(board.get("contracts") or []) + list(board.get("long_shots") or [])
    return out
