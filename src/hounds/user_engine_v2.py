"""The rule-set half of the user-hound engine: candidates for version-2 specs, including player props.

This module is called by `user_engine.run` (and by the builder's read-only preview); the ledger,
the idempotent bet ids, the daily cap and every guard still live in `run`, so a version-2 hound is
held to exactly the same discipline as a version-1 one. What is added here:

PLAYER PROPS
------------
A prop board is built the way a game board is: from the newest capture at or before the lock, one
quote per book, the consensus line being the one the most books quote. Batter props come from
`data/processed/batter_props.jsonl` (hits, total bases, home runs, RBIs, runs scored, hits + runs +
RBIs) and pitcher strikeouts from `prop_prices.jsonl`; there are no NFL prop prices on file, so
props are MLB only. Prop boards are captured twice a game (a baseline 5 to 24 hours out and a gate
capture 0 to 2 hours out), so the board a lock sees can be hours old; `MAX_PROP_BOARD_AGE_MINUTES`
bounds that and the bet row records the board's age. The price a prop is graded at is the board
AVERAGE across the books quoting that side, exactly as for game markets, and the -200 cap applies.

ONE BET PER PLAYER PER MARKET PER GAME, ONE SIDE
------------------------------------------------
When a rule allows either side and both qualify, the one the hound's ranking prefers is kept (ties go
to the over). When two rules produce the same bet, the better-ranked candidate is kept, so a hound
never backs both sides of one line and never double-counts a bet across rules.

POINT IN TIME
-------------
Every condition is evaluated on a `Ctx` built from the board at lock and from `user_facts` (history
dated before the slate, forecasts observed before the lock). A condition with no data is "not met"
and is counted in the run's `skipped` tally by name (`unknown_rest_days`), so a silent gap shows up
as a number rather than as a quiet slate.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

from src.core import odds as odds_math
from src.hounds import one_side
from src.hounds import user_engine as E
from src.hounds import user_rules as R
from src.hounds import user_spec

# A prop's own price barely moves between the baseline and the gate capture unless something
# happened, so a smaller move than a game's counts as steam: one percentage point of implied
# probability on the picked side (props have no two-sided de-vig at most books).
MOVE_PROBABILITY_PROP = 0.01

BATTER_STORE = os.path.join("data", "processed", "batter_props.jsonl")
PITCHER_STORE = os.path.join("data", "processed", "prop_prices.jsonl")


# ---------------------------------------------------------------------------
# team codes
# ---------------------------------------------------------------------------

def team_code(name: Optional[str], sport: str) -> Optional[str]:
    if not name:
        return None
    if sport not in ("MLB", "NFL"):
        # An all-sports family (2026-10-19) has no club-code table: the team's own name is its identity,
        # which is all the any-sport conditions (role, steam, names, coin flip) read. The MLB/NFL-only
        # conditions that look a code up in a stats table cannot be chosen for these sports (user_rules).
        return str(name).strip() or None
    try:
        if sport == "NFL":
            from src.sports import nfl_teams
            return nfl_teams.abbrev(name)
        from src.hounds.pack.base import mlb_code
        from src.pipeline.slate import team_abbrev_from_name
        abbrev = team_abbrev_from_name(name)
        return mlb_code(abbrev) if abbrev else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# prop rows and boards
# ---------------------------------------------------------------------------

def prop_rows_from(row: Mapping) -> list:
    """One stored prop row -> zero, one or two slim single-side rows. The batter store has one row
    per side; the pitcher store has both prices on one row."""
    market = row.get("market")
    player, book = row.get("player"), row.get("book")
    if market not in R.PROP_MARKETS or not isinstance(player, str) or not player \
            or not isinstance(book, str) or not book:
        return []
    base = {"market": market, "player": player, "book": book, "home_team": row.get("home_team"),
            "away_team": row.get("away_team"), "commence_time": row.get("commence_time")}
    if "over_price" in row or "under_price" in row:
        line = E._number(row.get("point"))
        out = []
        for side, key in (("over", "over_price"), ("under", "under_price")):
            price = E._price(row.get(key))
            if line is not None and price is not None:
                out.append({**base, "line": line, "side": side, "price": price})
        return out
    line = E._number(row.get("line"))
    price = E._price(row.get("price"))
    side = str(row.get("side") or "").lower()
    if line is None or price is None or side not in ("over", "under"):
        return []
    return [{**base, "line": line, "side": side, "price": price}]


def _stream(path: str, prefilter: str) -> Iterable[dict]:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if prefilter not in line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def iter_prop_rows(date: str, *, root: Optional[str] = None) -> Iterable[dict]:
    """The stored prop rows of one slate date, streamed one at a time (the stores are tens of MB and
    the engine must never hold one whole). The prefilter is a plain substring test on the row's
    `game_date`, the same over-match-never-under-match rule the multibook reader uses."""
    from src import paths
    base = root or str(paths.repo_root())
    marker = f'"game_date": "{date}"'
    for rel, needs_market in ((BATTER_STORE, False), (PITCHER_STORE, True)):
        for row in _stream(os.path.join(base, rel), marker):
            if needs_market and row.get("market") != "pitcher_strikeouts":
                continue
            yield row


def add_prop_rows(games: dict, rows: Iterable[Mapping]) -> int:
    """Fold prop rows into `games` (creating an MLB `GameBoards` for an event with props but no
    game-market capture). Rows observed at or after their own start are dropped, as for game boards."""
    added = 0
    touched = set()
    for raw in rows:
        event_id = raw.get("event_id")
        observed, start = E._utc(raw.get("observed_utc")), E._utc(raw.get("commence_time"))
        if not event_id or observed is None or start is None or observed >= start:
            continue
        for slim in prop_rows_from(raw):
            game = games.get(event_id)
            if game is None:
                game = games[event_id] = E.GameBoards(event_id, "MLB")
            game.add_prop(slim["market"], observed, slim)
            touched.add(event_id)
            added += 1
    for event_id in touched:
        game = games[event_id]
        if game.commence is None:
            game.commence = game.commence_at(datetime.max.replace(tzinfo=timezone.utc))
    return added


def build_prop_boards(rows: Iterable[Mapping]) -> dict:
    """{player: board} for one capture's rows of one market. One quote per (book, line, side) (the
    last in file order); the consensus line is the one most books quote (ties go to the lower)."""
    by_player: dict = defaultdict(dict)
    for r in rows:
        by_player[r["player"]][(r["book"], r["line"], r["side"])] = r
    boards = {}
    for player, quotes in by_player.items():
        books_at: dict = defaultdict(set)
        for (book, line, _side) in quotes:
            books_at[line].add(book)
        line = sorted(books_at, key=lambda L: (-len(books_at[L]), L))[0]
        sides = {"over": [], "under": []}
        for (book, ln, side), r in sorted(quotes.items()):
            if ln == line:
                sides[side].append((book, r["price"]))
        if not (sides["over"] or sides["under"]):
            continue
        boards[player] = {"market": next(iter(quotes.values()))["market"], "player": player,
                          "line": line, "sides": sides, "n_books": len(books_at[line])}
    return boards


def prop_boards_at(game: "E.GameBoards", market: str, as_of: datetime) -> Optional[tuple]:
    """(observed, {player: board}) from the newest capture of `market` at or before `as_of`."""
    stamps = sorted((t for t in game.props.get(market, {}) if t <= as_of), reverse=True)
    for t in stamps:
        boards = build_prop_boards(game.props[market][t])
        if boards:
            return t, boards
    return None


def first_prop_board(game: "E.GameBoards", market: str, player: str, before: datetime) -> Optional[dict]:
    for t in sorted(game.props.get(market, {})):
        if t >= before:
            break
        board = build_prop_boards(r for r in game.props[market][t] if r["player"] == player).get(player)
        if board:
            return board
    return None


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------

def _implied(price: float) -> float:
    return 1.0 / odds_math.american_to_decimal(price)


def _avg_implied(book_prices: list) -> float:
    return _implied(E.average_price([p for _, p in book_prices]))


def _sort_key(rank_by: str, cand: Mapping, lock_utc: datetime, event_id: str, market: str, i: int) -> tuple:
    dec = odds_math.american_to_decimal(cand["price"])
    head = {"earliest_lock": (lock_utc,), "longest_price": (-dec,), "shortest_price": (dec,),
            "most_books": (-cand["n_books"],), "biggest_steam": (-(cand.get("steam_pts") or 0.0),)}[rank_by]
    return head + (lock_utc, event_id, E.MARKET_ORDER[market], cand.get("player") or "",
                   0 if cand["side"] in ("over", "home") else 1, i)


def _in_line_range(rule: Mapping, line: Optional[float]) -> bool:
    lo, hi = rule.get("line_min"), rule.get("line_max")
    if lo is None and hi is None:
        return True
    if line is None:
        return False
    return (lo is None or line >= lo - 1e-9) and (hi is None or line <= hi + 1e-9)


def _sides(rule_side: str, market: str) -> tuple:
    if rule_side != "either":
        return (rule_side,)
    return ("over", "under") if R.market_kind(market) in ("total", "prop") else ("home", "away")


def _game_ctx(spec: Mapping, game: "E.GameBoards", market: str, side: str, line, avg: int, n_books: int,
              date: str, commence: datetime, lock_utc: datetime, game_pk, seed: str, facts,
              role, move, player=None, pick_code=None) -> R.Ctx:
    home, away = team_code(game.home_team, game.sport), team_code(game.away_team, game.sport)
    if market in R.GAME_MARKETS and market != "total":
        pick_code = home if side == "home" else away
    opp = None
    if pick_code and pick_code == home:
        opp = away
    elif pick_code and pick_code == away:
        opp = home
    return R.Ctx(sport=game.sport, market=market, side=side, line=line, price=avg, n_books=n_books,
                 home_code=home, away_code=away, home_name=game.home_team or "", away_name=game.away_team or "",
                 pick_code=pick_code, opp_code=opp, player=player, role=role, move=move, date=date,
                 start=commence, lock=lock_utc, game_pk=game_pk, event_id=game.event_id, seed=seed,
                 facts=facts)


def _tally_unknown(skipped, unknown: list) -> None:
    for cid in sorted(set(unknown)):
        skipped[f"unknown_{cid}"] += 1


def rule_candidates(rule: Mapping, index: int, spec: Mapping, game: "E.GameBoards", market: str,
                    as_of: datetime, lock_utc: datetime, commence: datetime, date: str, seed: str, facts,
                    game_pk, skipped) -> list:
    """Every candidate one rule produces on one market of one game, at the board standing at `as_of`."""
    out: list = []
    if user_spec.is_gematria(spec):
        return out         # the Gematria style's fixed rule is not a rule to evaluate here (src/hounds/user_gematria.py)
    kind = R.market_kind(market)
    if kind == "prop":
        found = prop_boards_at(game, market, as_of)
        max_age = user_spec.MAX_PROP_BOARD_AGE_MINUTES
    else:
        found = game.board_at(market, as_of)
        max_age = E.MAX_BOARD_AGE_MINUTES
    if found is None:
        skipped["no_board_at_lock"] += 1
        return out
    observed, board = found
    age = (as_of - observed).total_seconds() / 60.0
    if age > max_age:
        skipped["board_too_old"] += 1
        return out

    if kind == "prop":
        for player, pb in sorted(board.items()):
            for side in _sides(rule["side"], market):
                prices = pb["sides"][side]
                if not prices:
                    continue
                if len(prices) < rule["min_books"]:
                    skipped["too_few_books"] += 1
                    continue
                avg = E.average_price([p for _, p in prices])
                if user_spec.beyond_cap(avg):
                    skipped["price_cap"] += 1
                    continue
                if not user_spec.in_band(avg, rule["price_min"], rule["price_max"]):
                    skipped["outside_price_band"] += 1
                    continue
                if not _in_line_range(rule, pb["line"]):
                    skipped["outside_line_range"] += 1
                    continue
                team = facts.player_team(player) if facts is not None else None
                move, steam = _prop_move(game, market, player, observed, side, prices)
                ctx = _game_ctx(spec, game, market, side, pb["line"], avg, len(prices), date, commence, lock_utc,
                                game_pk, seed, facts, None, move, player=player, pick_code=team)
                unknown: list = []
                if not R.evaluate_tree(rule.get("when"), ctx, unknown):
                    skipped["conditions_not_met"] += 1
                    _tally_unknown(skipped, unknown)
                    continue
                best, best_book = E.best_price(prices)
                noun = R.PROP_NOUN[market]
                out.append({
                    "side": side, "line": pb["line"], "price": avg, "best_price": best, "best_book": best_book,
                    "n_books": len(prices), "board_observed_utc": E._iso(observed), "board_age_minutes": round(age, 1),
                    "selection": f"{player} {side.title()} {pb['line']:g} {noun}", "player": player,
                    "rule_index": index, "steam_pts": steam})
        return out

    # a game market
    if board["n_books"] < rule["min_books"]:
        skipped["too_few_books"] += 1
        return out
    first = game.first_board(market, observed)
    open_board = first[1] if first else None
    fav = E.side_for_rule("favourite", market, board, None) if market != "total" else None
    for side in _sides(rule["side"], market):
        prices = board["sides"].get(side)
        if not prices:
            continue
        avg = E.average_price([p for _, p in prices])
        if user_spec.beyond_cap(avg):
            skipped["price_cap"] += 1
            continue
        if not user_spec.in_band(avg, rule["price_min"], rule["price_max"]):
            skipped["outside_price_band"] += 1
            continue
        if market == "spread":
            line = board["line"] if side == "home" else -board["line"]
            selection_line = board["line"]
        elif market == "total":
            line = selection_line = board["line"]
        else:
            line = selection_line = None
        if not _in_line_range(rule, line):
            skipped["outside_line_range"] += 1
            continue
        role = None if fav is None else ("favourite" if fav == side else "underdog")
        move = steam = None
        if open_board is not None:
            toward = E.movement(open_board, board)
            move = 0 if toward is None else (1 if toward == side else -1)
            try:
                steam = round(100.0 * (_avg_implied(board["sides"][side]) - _avg_implied(open_board["sides"][side])), 3)
            except (KeyError, ZeroDivisionError, odds_math.OddsError):
                steam = None
        ctx = _game_ctx(spec, game, market, side, line, avg, board["n_books"], date, commence, lock_utc,
                        game_pk, seed, facts, role, move)
        unknown = []
        if not R.evaluate_tree(rule.get("when"), ctx, unknown):
            skipped["conditions_not_met"] += 1
            _tally_unknown(skipped, unknown)
            continue
        best, best_book = E.best_price(prices)
        out.append({
            "side": side, "line": line, "price": avg, "best_price": best, "best_book": best_book,
            "n_books": board["n_books"], "board_observed_utc": E._iso(observed), "board_age_minutes": round(age, 1),
            "selection": E._selection_text(game, market, side, selection_line), "player": None,
            "rule_index": index, "steam_pts": steam})
    return out


def _prop_move(game, market, player, observed, side, prices) -> tuple:
    """(move, steam_pts) for a prop: +1 / -1 / 0 / None, and the points of implied probability the
    picked side's average price moved since the first capture. A moved line is a bigger move than any
    price: a higher line is the market moving toward the under, a lower one toward the over."""
    first = first_prop_board(game, market, player, observed)
    if first is None or not first["sides"][side]:
        return None, None
    now_board = build_prop_boards(r for r in game.props[market][observed] if r["player"] == player).get(player)
    if now_board is None:
        return None, None
    if now_board["line"] != first["line"]:
        toward_over = now_board["line"] < first["line"]
        toward = "over" if toward_over else "under"
        return (1 if toward == side else -1), None
    delta = _avg_implied(prices) - _avg_implied(first["sides"][side])
    steam = round(100.0 * delta, 3)
    if abs(delta) < MOVE_PROBABILITY_PROP:
        return 0, steam
    return (1 if delta > 0 else -1), steam


def hound_candidates(hound: Mapping, spec: Mapping, games: Mapping, facts, date: str, *, mode: str,
                     clock: Callable[[], datetime], seen_ids: set, game_pk_index: Optional[Mapping],
                     skipped, considered: dict, preview_now: Optional[datetime] = None,
                     ahead: bool = False, dropped: Optional[list] = None) -> list:
    """The ranked candidates of one version-2 hound on one slate date:
    [(sortkey, lock_utc, event_id, market, game, commence, cand, bet_id)], de-duplicated per bet and held to
    one side per game (the first in the hound's own rank order keeps the game's side slot, its total slot,
    and each player's stat slot).

    ``ahead`` (live mode, the Unleash button): a game not yet at its lock is evaluated now on the newest
    board instead of being skipped; a started game and a hound born after the lock are still skipped.
    ``dropped`` (a list) receives ``(item, code)`` for each candidate the one-side guard refused."""

    if user_spec.is_gematria(spec):
        return []          # a Gematria hound's picks come from src/hounds/user_gematria.py; its fixed rule is never read as a rule
    created = E._utc(hound.get("created_at"))
    seed = hound.get("spec_hash") or user_spec.spec_hash(spec)
    best: dict = {}
    for event_id, game in sorted(games.items()):
        wanted_sports = {s for r in spec["rules"] for s in r["sports"]}
        if game.sport not in wanted_sports or game.commence is None:
            continue
        commence = game.commence
        lock_utc = commence - timedelta(minutes=spec["lock_minutes"])
        as_of = lock_utc
        if preview_now is not None:
            as_of = min(lock_utc, preview_now)
        elif mode == "live":
            t = clock()
            if t >= commence:
                skipped["game_started"] += 1
                continue
            if t < lock_utc:
                if not ahead:
                    skipped["not_locked_yet"] += 1
                    continue
                as_of = t
            if created is not None and created > lock_utc:
                skipped["hound_created_after_lock"] += 1
                continue
        considered.setdefault(hound["id"], set()).add(event_id)
        game_pk = None
        if game_pk_index:
            entry = game_pk_index.get(event_id)
            game_pk = str(entry.get("game_pk")) if entry and entry.get("game_pk") is not None else None
        for i, rule in enumerate(spec["rules"]):
            if game.sport not in rule["sports"]:
                continue
            for market in rule["markets"]:
                for cand in rule_candidates(rule, i, spec, game, market, as_of, lock_utc, commence, date, seed,
                                            facts, game_pk, skipped):
                    key = market if not cand["player"] else f"{market}|{R.fold_player(cand['player'])}"
                    bet_id = E.bet_id_for(hound["id"], event_id, key)
                    if bet_id in seen_ids:
                        continue
                    item = (_sort_key(spec["rank_by"], cand, lock_utc, event_id, market, i), lock_utc,
                            event_id, market, game, commence, cand, bet_id)
                    kept = best.get(bet_id)
                    if kept is None or item[0] < kept[0]:
                        best[bet_id] = item
    # One side per game (src/hounds/one_side.py): in the hound's own rank order, the first candidate on a
    # game keeps its slot (side / total / one player's stat) and a later one that contradicts or repeats it
    # is dropped and counted. The ranking is the owner's ``rank_by``, never the better price afterwards.
    ranked = sorted(best.values(), key=lambda item: item[0])
    return one_side.keep_first(ranked, lambda it: (it[2], it[3], it[6]["side"], it[6].get("player"), it[6].get("line")),
                               skipped=skipped, hound_id=hound["id"], dropped=dropped)


# ---------------------------------------------------------------------------
# the read-only preview
# ---------------------------------------------------------------------------

def preview(spec: Mapping, games: Mapping, facts, date: str, now: datetime, *,
            game_pk_index: Optional[Mapping] = None) -> dict:
    """What a spec would bet on this slate, from the boards as they stand at `now` (a game that has
    not reached its lock is evaluated on the newest board, flagged `locked: false`). Writes nothing."""
    skipped: Counter = E.Counter()
    considered: dict = {}
    hound = {"id": "preview", "spec": spec, "created_at": None}
    ranked = hound_candidates(hound, spec, games, facts, date, mode="replay", clock=lambda: now,
                              seen_ids=set(), game_pk_index=game_pk_index, skipped=skipped,
                              considered=considered, preview_now=now)
    ranked.sort(key=lambda c: c[0])
    picks = []
    for position, (_k, lock_utc, event_id, market, game, commence, cand, _bet) in enumerate(ranked):
        picks.append({
            "event_id": event_id, "sport": game.sport, "market": market, "away_team": game.away_team,
            "home_team": game.home_team, "start_utc": E._iso(commence), "lock_utc": E._iso(lock_utc),
            "locked": now >= lock_utc, "selection": cand["selection"], "side": cand["side"],
            "line": cand["line"], "player": cand["player"], "price": cand["price"],
            "best_price": cand["best_price"], "n_books": cand["n_books"], "rule_index": cand["rule_index"],
            "would_bet": position < spec["max_bets_per_day"], "rank": position + 1})
    # "{n} of {m} games fit" (the reveal): n is the number of DIFFERENT games with at least one qualifying
    # pick, so a game that fits on a moneyline and on a total counts once. `qualifying` stays the number of
    # picks; the route adds the board size `m`.
    return {"date": date, "games_considered": len(considered.get("preview", ())),
            "games_fit": len({p["event_id"] for p in picks}),
            "qualifying": len(picks), "would_bet": min(len(picks), spec["max_bets_per_day"]),
            "max_bets_per_day": spec["max_bets_per_day"], "picks": picks,
            "skipped": dict(skipped)}


# ---------------------------------------------------------------------------
# a slate, built once, for the builder's preview
# ---------------------------------------------------------------------------

class Slate:
    """One date's boards, facts and game-key map, built once and shared by every preview of that date."""

    def __init__(self, date: str, games: dict, facts, game_pk_index: Optional[Mapping], with_props: bool):
        self.date, self.games, self.facts = date, games, facts
        self.game_pk_index, self.with_props = game_pk_index, with_props

    def newest_observed(self) -> Optional[str]:
        newest = None
        for game in self.games.values():
            for market in game.captures.values():
                for t in market:
                    newest = t if newest is None or t > newest else newest
        return E._iso(newest) if newest else None


def build_slate(date: str, sports: Iterable[str], *, with_props: bool, rows: Optional[Iterable] = None,
                prop_rows: Optional[Iterable] = None, facts=None, game_pk_index: Optional[Mapping] = None) -> Slate:
    """The boards of one slate date. Rows stream through the same windowed reader the engine uses, so
    building a slate holds the date's games and nothing else; the caller holds the process-wide build
    gate (the preview cache does, via `freshness.SingleFlightTTLCache`)."""
    sports = sorted({s.upper() for s in sports}) or list(user_spec.SPORTS)
    raw = rows if rows is not None else E.iter_rows(date, sports)
    all_games = E.build_games(raw, near_date=date)
    if with_props:
        add_prop_rows(all_games, prop_rows if prop_rows is not None else iter_prop_rows(date))
    games = {eid: g for eid, g in all_games.items()
             if g.commence is not None and E.slate_date_of(g.commence) == date}
    if facts is None:
        from src.hounds.user_facts import FactBook
        facts = FactBook.from_stores(date)
    if game_pk_index is None:
        game_pk_index = E._load_game_pk_index()
    return Slate(date, games, facts, game_pk_index, with_props)
