"""Fire now: "What would you bet right now?" -- a dog's CURRENT rule over the LATEST stored boards.

READ ONLY. Nothing here writes a ledger row, an app-database row or a file. It is the engine's own evaluation,
asked about the boards as they stand now instead of at the dog's usual placing time:

  user dog   ``user_engine.evaluate`` (the function the live engine runs for every bet) is called with the
             newest stored capture of each market, so the side rule, the price band, the -200 cap and the
             minimum-books rule are the engine's, line for line. What this module adds is an explanation of
             the answer: which check passed or failed, and by how much.
  house dog  ``pack_run.choose`` (the pack runner's selection, band and -200 rule) over a board built at this
             instant from the same stores the runner reads, with the champion version's knob values.

A PREVIEW IS NOT A TICKET. The real ticket is written at the dog's usual placing time with the board then; a
preview taken earlier can differ. Each pick says when the real one would be placed, how old its board is, and
whether that board is too old to record a manual pick from.

"NOTHING QUALIFIES" COMES WITH THE CLOSEST MISSES: every game the dog looked at and did not take, ranked by how
near it came (a price just outside the band before a market with too few books), each with the numbers.

Paper only. No pick here is advice.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.core import odds as odds_math
from src.hounds import one_side, user_engine, user_spec
from src.hounds.interact import common

MAX_MISSES = 6
HORIZON_HOURS = {"MLB": 36, "NFL": 24 * 5}
STORES_TTL_S = 300.0
STARTED_KEEP = timedelta(hours=12)       # how long after first pitch a started game is still NAMED

MARKET_LABEL = {"moneyline": "Moneyline", "spread": "Spread", "total": "Total"}
MISS_TITLE = {
    "outside_price_band": "Priced outside the band",
    "too_few_books": "Too few books quoting",
    "rule_has_no_side": "The rule has no side to back",
    "price_cap": "Past the -200 cap",
    "no_board_at_lock": "No board captured yet",
    "rule_not_met": "The rule did not fire",
    "not_eligible": "Not eligible for this game",
    "board_too_old": "Board too old",
}
# closer-first ordering of the reasons a game can be missed: a near price beats a missing board
MISS_TIER = {"outside_price_band": 1, "too_few_books": 2, "rule_has_no_side": 3, "price_cap": 4,
             "rule_not_met": 5, "not_eligible": 6, "board_too_old": 7, "no_board_at_lock": 8}

PREVIEW_NOTE = ("A preview on the newest stored boards. The hound's real ticket is written at its usual "
                "placing time with the board then, so it can differ. Paper only, not advice.")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _fmt_price(p) -> str:
    if p is None:
        return "n/a"
    p = int(round(p))
    return f"+{p}" if p > 0 else str(p)


def _prob(american: float) -> float:
    return 1.0 / odds_math.american_to_decimal(american)


def _points(a: float, b: float) -> float:
    """Gap between two American prices in percentage points of implied win probability."""
    return round(abs(_prob(a) - _prob(b)) * 100.0, 1)


def _minutes(delta) -> int:
    return int(round(delta.total_seconds() / 60.0))


def _hm(minutes: int) -> str:
    minutes = max(0, int(minutes))
    if minutes < 90:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours >= 48:
        return f"{hours // 24} days"
    return f"{hours} h {rest:02d} min" if rest else f"{hours} h"


def _band_text(spec) -> str:
    return f"{_fmt_price(spec['price_min'])} to {_fmt_price(spec['price_max'])}"


def market_label(market: str, sport: str) -> str:
    if market == "spread" and sport == "MLB":
        return "Run line"
    return MARKET_LABEL.get(market, market.title())


def _game_text(game) -> str:
    return f"{game.away_team} @ {game.home_team}"


# ---------------------------------------------------------------------------
# days in the viewer's terms (Eastern time: the sport's own clock)
# ---------------------------------------------------------------------------

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _eastern():
    from src.data.eastern import eastern
    return eastern()


def day_of(moment: datetime) -> str:
    """The Eastern calendar date (YYYY-MM-DD) of a start time."""
    return moment.astimezone(_eastern()).date().isoformat()


def clock_et(moment: datetime) -> str:
    """'8:10 pm ET'."""
    local = moment.astimezone(_eastern())
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'} ET"


def day_label(date: str, now: datetime) -> str:
    """'Today', 'Tomorrow', a weekday name inside the next six days, else 'Oct 29' (Eastern dates)."""
    today = datetime.fromisoformat(day_of(now))
    target = datetime.fromisoformat(date)
    gap = (target - today).days
    if gap == 0:
        return "Today"
    if gap == 1:
        return "Tomorrow"
    if gap == -1:
        return "Yesterday"
    if 1 < gap < 7:
        return WEEKDAYS[target.weekday()]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[target.month - 1]} {target.day}"


def _games_text(items: list) -> str:
    return ", ".join(f"{game} ({clock_et(start)})" for game, start in items)


def slate_view(now: datetime, started: list, upcoming: list, other_live: Optional[dict] = None) -> dict:
    """What is on the board TODAY in the viewer's terms, so a list that starts on Thursday is never read as
    "not looking at tonight's games" (owner, 2026-10-20).

    ``started`` is [(game, start)] for games already under way; ``upcoming`` is [(game, start, lock)] for games
    ahead. Only games whose EASTERN date is today count as today's. ``line`` is the sentence to say first:
      started, nothing left today  "Tonight's games already started: A @ B (8:10 pm ET). Next games I can bet: Thursday."
      nothing on the board today   "No games today. Next slate: Thursday."
      some started, some ahead     "Already started today: ... Still ahead today: 2 games."
    and a game inside the dog's placing window (its lock has passed, the game has not started) is named too.

    NEXT GAME AND OTHER SPORTS (2026-10-19): when nothing is on today, the line also names the NEXT game in
    the dog's sports ("Next game: A @ B (Thursday, 7:10 pm ET)"), and, when ``other_live`` (a
    ``src.sports.allsports_view.live_elsewhere`` answer) shows games live in OTHER sports, adds "Live now in
    other sports: 5 games (tennis, cricket)." so an empty board for the dog's own sports is never a dead end.
    ``next_game`` and ``other_live`` are also returned as fields for every state."""
    today = day_of(now)
    today_started = sorted([(g, s) for g, s in started if day_of(s) == today], key=lambda t: t[1])
    today_ahead = [(g, s, k) for g, s, k in upcoming if day_of(s) == today]
    later = sorted([(g, s) for g, s, _k in upcoming if day_of(s) > today], key=lambda t: t[1])
    in_window = sorted([(g, s) for g, s, k in upcoming if k is not None and k <= now and s > now], key=lambda t: t[1])
    next_date = day_of(later[0][1]) if later else None
    next_label = day_label(next_date, now) if next_date else None
    next_game = None
    if later:
        n_game, n_start = later[0]
        next_game = {"game": n_game, "start_utc": common.iso(n_start), "start_et": clock_et(n_start),
                     "day_label": next_label, "text": f"{n_game} ({clock_et(n_start)})"}
    nxt = (f"Next games I can bet: {next_label}." if next_label else "No later games are on the stored boards yet.")
    if today_started and not today_ahead:
        state = "started"
        word = "Tonight's" if now.astimezone(_eastern()).hour >= 17 else "Today's"
        line = f"{word} games already started: {_games_text(today_started)}. {nxt}"
    elif today_started:
        state = "open"
        line = (f"Already started today: {_games_text(today_started)}. Still ahead today: "
                f"{len(today_ahead)} {'game' if len(today_ahead) == 1 else 'games'}.")
    elif today_ahead:
        state, line = "open", ""
    else:
        state = "none"
        line = (f"No games today. Next slate: {next_label}. Next game: {next_game['text']}." if next_label
                else "No games today, and none are on the stored boards yet.")
        if other_live and other_live.get("games"):
            line += " " + other_live["text"]
    if in_window:
        line = (line + " " if line else "") + f"Inside my placing window now: {_games_text(in_window)}."
    day_counts: dict = {}
    for _g, s, _k in upcoming:
        d = day_of(s)
        day_counts[d] = day_counts.get(d, 0) + 1
    return {
        "today": today, "today_state": state, "line": line,
        "started": [{"game": g, "start_utc": common.iso(s), "start_et": clock_et(s)} for g, s in today_started],
        "in_window": [{"game": g, "start_utc": common.iso(s), "start_et": clock_et(s)} for g, s in in_window],
        "next_day": next_date, "next_day_label": next_label, "next_game": next_game,
        "other_live": other_live if other_live and other_live.get("games") and state == "none" else None,
        "days": [{"date": d, "label": day_label(d, now), "games": n} for d, n in sorted(day_counts.items())],
    }


def default_other_live():
    """The production answer to "what is live in other sports": the stored rows, through the cached board."""
    from src.sports import allsports_view
    return lambda own, at: allsports_view.live_elsewhere(own, at)


def other_sports_live(other_live: Optional[Callable], own_sports, now: datetime, started: list,
                      upcoming: list, have_picks: bool = False) -> Optional[dict]:
    """``other_live(own_sports, now)`` whenever the dog has NO pick, else None. (The slate sentence names other
    sports only when nothing at all is on today for the dog; ``slate_view`` decides that. The separate
    ``live_elsewhere`` field is given on any empty result.) Never fatal: a board that cannot be read is simply
    not mentioned."""
    if other_live is None or have_picks:
        return None
    try:
        return other_live(own_sports, now)
    except Exception:  # noqa: BLE001
        return None


def next_game_line(now: datetime, upcoming: list) -> Optional[str]:
    """'Next game: Thu 5:15 PM — Yankees at Red Sox' for the earliest game still ahead (Eastern time), or None."""
    ahead = sorted([(s, g) for g, s, _k in upcoming if s > now], key=lambda t: t[0])
    if not ahead:
        return None
    start, game = ahead[0]
    local = start.astimezone(_eastern())
    hour = local.hour % 12 or 12
    clock = f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
    return f"Next game: {WEEKDAYS[local.weekday()][:3]} {clock} \u2014 {game.replace(' @ ', ' at ')}"


def _heavy():
    """The process-wide one-heavy-build-at-a-time gate the engine and the stats build use."""
    try:
        from src.appstate import freshness
        return freshness._gated_build()
    except Exception:  # noqa: BLE001
        import contextlib
        return contextlib.nullcontext()


# ---------------------------------------------------------------------------
# the boards (user dogs)
# ---------------------------------------------------------------------------

_games_cache: dict = {}
_games_lock = threading.Lock()


def horizon_dates(sports, now: datetime) -> list:
    """Eastern slate dates that can hold a game starting soon: today, then tomorrow (MLB), then up to four
    more days when the dog bets the NFL (its games are scheduled days ahead)."""
    first = common.eastern_date(now)
    span = 4 if "NFL" in set(sports) else 1
    base = datetime.fromisoformat(first)
    return [(base + timedelta(days=i)).date().isoformat() for i in range(span + 1)]


def load_games(sports, now: datetime, rows_for: Optional[Callable] = None) -> dict:
    """{event_id: GameBoards} for games that have not started (plus those that started in the last 12 hours,
    which callers only NAME), from the stored multibook captures.

    ``rows_for(date, sports)`` is the injection point (tests pass fixture rows); production streams the store
    one slate at a time through ``user_engine.iter_rows`` and keeps only the engine's slim fields."""
    games: dict = {}
    for date in horizon_dates(sports, now):
        source = rows_for(date, sports) if rows_for else user_engine.iter_rows(date, sports)
        for event_id, game in user_engine.build_games(source, near_date=date).items():
            if game.commence is None:
                continue
            if game.commence <= now:
                # A game that has STARTED is never bet, but the payload names it (the owner read a list that
                # began on Thursday as "not looking at tonight's games", 2026-10-20), so a recent one is kept.
                if now - game.commence > STARTED_KEEP:
                    continue
            elif game.commence - now > timedelta(hours=HORIZON_HOURS.get(game.sport, 36)):
                continue
            games.setdefault(event_id, game)
    return games


def cached_games(sports, now: datetime, rows_for: Optional[Callable] = None) -> dict:
    """``load_games`` remembered for a minute per sport set, so a page and a chat panel opened together read
    the store once. Tests (which pass ``rows_for``) are never cached."""
    if rows_for is not None:
        return load_games(sports, now, rows_for)
    key = tuple(sorted(sports))

    def fresh():
        with _games_lock:
            hit = _games_cache.get(key)
            return hit[1] if hit and time.monotonic() - hit[0] < 60.0 else None
    hit = fresh()
    if hit is not None:
        return hit
    with _heavy():
        # DOUBLE-CHECKED. Twenty simultaneous unsigned "Fire now" taps all missed the
        # cache above and queued on the gate, and each then ran its own full load
        # (red team 2026-10-19). Whoever waited re-reads the cache the builder filled.
        hit = fresh()
        if hit is not None:
            return hit
        games = load_games(sports, now)
        with _games_lock:
            _games_cache[key] = (time.monotonic(), games)
    return games


def clear_cache() -> None:
    with _games_lock:
        _games_cache.clear()
    with _stores_lock:
        _stores_cache.clear()


# ---------------------------------------------------------------------------
# explaining one (game, market) for a user dog
# ---------------------------------------------------------------------------

def _newest_capture(game, market: str, now: datetime) -> Optional[datetime]:
    stamps = [t for t in game.captures.get(market, {}) if t <= now]
    return max(stamps) if stamps else None


def _side_name(game, market: str, side: str, board) -> str:
    if market == "total":
        return f"{side.title()} {board['line']:g}"
    team = game.home_team if side == "home" else game.away_team
    if market == "spread":
        line = board["line"] if side == "home" else -board["line"]
        return f"{team} {line:+g}"
    return f"{team} to win"


def _explain(spec, game, market: str, observed: datetime, code: str) -> dict:
    """The numbers behind a miss: {'why', 'gap', 'detail'}. The CODE is the engine's; this only words it."""
    found = game.board_at(market, observed)
    if found is None:
        return {"why": "No board has been captured for this market yet.", "gap": None}
    _t, board = found
    n_books = board["n_books"]
    if code == "too_few_books":
        short = spec["min_books"] - n_books
        return {"why": f"{n_books} {'book is' if n_books == 1 else 'books are'} quoting this "
                       f"{market_label(market, game.sport).lower()}; your rule needs at least {spec['min_books']}.",
                "gap": float(short), "unit": "books"}
    open_board = None
    if spec["side_rule"].startswith("market_moved"):
        first = game.first_board(market, observed)
        open_board = first[1] if first else None
    side = user_engine.side_for_rule(spec["side_rule"], market, board, open_board)
    if code == "rule_has_no_side":
        rule = spec["side_rule"]
        if rule.startswith("market_moved"):
            if open_board is None:
                why = "There is only one capture of this game so far, so there is no line move to follow."
            else:
                why = ("The line has not moved since the first capture (it takes a changed number, or about half "
                       "a point of win probability), so there is no side to follow.")
        elif rule in ("favourite", "underdog"):
            why = "Both sides are priced the same, so there is no favourite or underdog."
        else:
            why = "This market has no side the rule can back."
        return {"why": why, "gap": None}
    if side is None:
        return {"why": "No side to price.", "gap": None}
    prices = [p for _b, p in board["sides"][side]]
    avg = user_engine.average_price(prices)
    name = _side_name(game, market, side, board)
    if code == "price_cap":
        return {"why": f"{name} is {_fmt_price(avg)} on the board, which is {_points(avg, user_spec.MAX_FAVOURITE_PRICE)} "
                       f"points of win probability past the {_fmt_price(user_spec.MAX_FAVOURITE_PRICE)} cap that is always on.",
                "gap": _points(avg, user_spec.MAX_FAVOURITE_PRICE), "unit": "points", "price_average": avg,
                "selection": name}
    if code == "outside_price_band":
        dec = odds_math.american_to_decimal(avg)
        too_short = dec < odds_math.american_to_decimal(spec["price_min"])
        limit = spec["price_min"] if too_short else spec["price_max"]
        gap = _points(avg, limit)
        direction = "shorter than" if too_short else "longer than"
        return {"why": f"{name} is {_fmt_price(avg)} on the board, {direction} your band of {_band_text(spec)}: "
                       f"{gap} points of win probability from the nearest limit, {_fmt_price(limit)}.",
                "gap": gap, "unit": "points", "price_average": avg, "selection": name,
                "band_limit": limit}
    return {"why": MISS_TITLE.get(code, code), "gap": None}


def _checks(spec, cand: dict, game, market: str) -> list:
    """The checks a pick passed, in the order the engine applies them, each with its number."""
    return [
        {"label": "Board", "ok": True,
         "detail": f"{cand['n_books']} books quoting; newest capture is {_hm(int(cand['board_age_minutes']))} old"},
        {"label": "Minimum books", "ok": True, "detail": f"{cand['n_books']} quoting, rule needs {spec['min_books']}"},
        {"label": "Side rule", "ok": True, "detail": f"{user_spec.SIDE_LABELS[spec['side_rule']]}: {cand['selection']}"},
        {"label": "Price band", "ok": True,
         "detail": f"{_fmt_price(cand['price'])} is inside {_band_text(spec)}"},
        {"label": "The -200 cap", "ok": True, "detail": f"{_fmt_price(cand['price'])} is not -200 or worse"},
    ]


def _recorded_index(hound_id: str, ledger: Optional[str]) -> tuple:
    """({(event_id, market): row}, {slate_date: count}) of the dog's own recorded rule tickets."""
    rows = [r for r in user_engine.read_ledger(ledger)
            if r.get("kind") == user_engine.KIND_BET and r.get("hound_id") == hound_id]
    return ({(r["event_id"], r["market"]): r for r in rows},
            _count_by(rows, "slate_date"))


def _count_by(rows, key) -> dict:
    out: dict = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


def pick_row(hound: dict, game, market: str, cand: dict, observed: datetime, now: datetime,
             lock_utc: datetime, commence: datetime, *, mode: str = "live") -> dict:
    """The ledger row this pick would be, in the engine's own shape (``user_engine.run`` builds the same).
    The manual pick writes this row (plus its manual tags) to its own ledger."""
    spec = hound["spec"]
    slate = user_engine.slate_date_of(commence)
    row = {
        "kind": user_engine.KIND_BET, "ledger_version": user_engine.LEDGER_VERSION, "paper_only": True,
        "bet_id": user_engine.bet_id_for(hound["id"], game.event_id, market), "hound_id": hound["id"],
        "spec_hash": hound.get("spec_hash") or user_spec.spec_hash(spec),
        "sport": game.sport, "event_id": game.event_id, "game_pk": None, "slate_date": slate,
        "commence_time": user_engine._iso(commence), "away_team": game.away_team, "home_team": game.home_team,
        "market": market, "side": cand["side"], "line": cand["line"], "selection": cand["selection"],
        "price": cand["price"], "best_price": cand["best_price"], "best_book": cand["best_book"],
        "n_books": cand["n_books"], "lock_minutes": spec["lock_minutes"], "lock_utc": user_engine._iso(lock_utc),
        "board_observed_utc": cand["board_observed_utc"], "board_age_minutes": cand["board_age_minutes"],
        "units": 1, "recorded_utc": user_engine._iso(now), "provenance": mode,
    }
    row.update(user_engine.contract_fields(row, spec, mode))
    return row


# ---------------------------------------------------------------------------
# fire: user dog
# ---------------------------------------------------------------------------

def fire_user(dog: common.Dog, *, now: Optional[datetime] = None, games: Optional[dict] = None,
              ledger: Optional[str] = None, rows_for: Optional[Callable] = None,
              other_live: Optional[Callable] = None) -> dict:
    """The dog's current rule over the newest stored boards. See the module docstring.

    ``other_live(own_sports, now)`` answers "what is live in other sports" (default on the production path:
    ``src.sports.allsports_view.live_elsewhere`` over the stored rows; with injected ``games`` or
    ``rows_for`` no default is used, so a test never reads the real store)."""
    now = now or common.now_utc()
    hound = dog.hound
    spec = hound["spec"]
    if other_live is None and games is None and rows_for is None:
        other_live = default_other_live()
    if games is None:
        games = cached_games(spec["sports"], now, rows_for)
    recorded, per_date = _recorded_index(hound["id"], ledger)
    picks, misses, tickets = [], [], []
    miss_counts: dict = {}
    looked = 0
    newest = None
    started: list = []
    upcoming: list = []
    for event_id, game in sorted(games.items(), key=lambda kv: (kv[1].commence, kv[0])):
        if game.sport not in spec["sports"] or game.commence is None:
            continue
        if game.commence <= now:
            started.append((_game_text(game), game.commence))
            continue
        lock_utc = game.commence - timedelta(minutes=spec["lock_minutes"])
        upcoming.append((_game_text(game), game.commence, lock_utc))
        game_looked = False
        for market in spec["markets"]:
            if (event_id, market) in recorded:
                row = recorded[(event_id, market)]
                tickets.append({"event_id": event_id, "game": _game_text(game), "market": market,
                                "market_label": market_label(market, game.sport), "selection": row["selection"],
                                "price_average": row["price"], "recorded_utc": row["recorded_utc"],
                                "start_utc": row["commence_time"], "kind": "rule"})
                game_looked = True
                continue
            observed = _newest_capture(game, market, now)
            if observed is None:
                miss_counts["no_board_at_lock"] = miss_counts.get("no_board_at_lock", 0) + 1
                misses.append(_miss(game, market, "no_board_at_lock",
                                    {"why": "No board has been captured for this market yet.", "gap": None}))
                continue
            game_looked = True
            newest = observed if newest is None or observed > newest else newest
            # the engine's own evaluation, as of the newest capture (so its freshness cap is about the data,
            # not about how long ago that capture was: the age is reported, and gates a manual pick, below)
            cand, code = user_engine.evaluate(spec, game, market, observed, game.commence)
            if cand is None:
                miss_counts[code] = miss_counts.get(code, 0) + 1
                misses.append(_miss(game, market, code, _explain(spec, game, market, observed, code)))
                continue
            age = _minutes(now - observed)
            cand = dict(cand, board_age_minutes=float(age))
            stale = age > user_engine.MAX_BOARD_AGE_MINUTES
            row = pick_row(hound, game, market, cand, observed, now, lock_utc, game.commence)
            picks.append({
                "event_id": event_id, "game": _game_text(game), "sport": game.sport, "market": market,
                "market_label": market_label(market, game.sport), "side": cand["side"],
                "selection": cand["selection"], "line": cand["line"], "price_average": cand["price"],
                "price_best": cand["best_price"], "best_book": cand["best_book"], "n_books": cand["n_books"],
                "start_utc": user_engine._iso(game.commence), "lock_utc": user_engine._iso(lock_utc),
                "minutes_to_start": _minutes(game.commence - now),
                "placed_in_minutes": max(0, _minutes(lock_utc - now)),
                "before_lock": now < lock_utc, "board_observed_utc": cand["board_observed_utc"],
                "board_age_minutes": age, "stale": stale, "slate_date": row["slate_date"],
                "day": day_of(game.commence), "day_label": day_label(day_of(game.commence), now),
                "reason": row["reason"], "rule": user_spec.SIDE_LABELS[spec["side_rule"]],
                "checks": _checks(spec, cand, game, market), "row": row,
            })
        if game_looked:
            looked += 1
    # one side per game (src/hounds/one_side.py): the engine would not write the second, so the preview does not show it
    picks = one_side.keep_first(picks, lambda p: (p["event_id"], p["market"], p["side"], None, p.get("line")))
    # the engine keeps the first ``max_bets_per_day`` of a slate date in lock order: say which would be cut
    seen = dict(per_date)
    for pick in sorted(picks, key=lambda p: (p["lock_utc"], p["event_id"], user_engine.MARKET_ORDER[p["market"]])):
        used = seen.get(pick["slate_date"], 0)
        pick["over_daily_limit"] = used >= spec["max_bets_per_day"]
        if not pick["over_daily_limit"]:
            seen[pick["slate_date"]] = used + 1
    notes = []
    if dog.status != "running":
        notes.append(f"This hound is {dog.status}; the live engine is not placing its tickets.")
    if any(p["stale"] for p in picks):
        notes.append(f"A board older than {user_engine.MAX_BOARD_AGE_MINUTES} minutes is flagged: its prices may "
                     "have moved, and the live engine skips a game with no newer board at placing time.")
    if any(p["over_daily_limit"] for p in picks):
        notes.append(f"The daily limit is {spec['max_bets_per_day']} ticket(s) a day, so the engine would stop "
                     "before the ones marked over the limit.")
    misses.sort(key=lambda m: (MISS_TIER.get(m["code"], 9), m["gap"] if m["gap"] is not None else 1e9,
                               m["start_utc"], m["event_id"]))
    elsewhere = other_sports_live(other_live, spec["sports"], now, started, upcoming, bool(picks))
    return _payload(dog, now, picks, misses, tickets, miss_counts, looked, newest, notes, started, upcoming,
                    elsewhere)


def _miss(game, market: str, code: str, info: dict) -> dict:
    return {"event_id": game.event_id, "game": _game_text(game), "market": market,
            "market_label": market_label(market, game.sport), "code": code,
            "title": MISS_TITLE.get(code, code), "why": info["why"], "gap": info.get("gap"),
            "unit": info.get("unit"), "start_utc": user_engine._iso(game.commence),
            "selection": info.get("selection")}


def _payload(dog: common.Dog, now: datetime, picks: list, misses: list, tickets: list, miss_counts: dict,
             looked: int, newest, notes: list, started: Optional[list] = None,
             upcoming: Optional[list] = None, other_live: Optional[dict] = None) -> dict:
    nothing = not picks
    slate = slate_view(now, started or [], upcoming or [], other_live)
    # The two lines the page reads on an empty result (2026-10-19 contract): the next game in the dog's sports
    # and what is live in other sports, as plain strings; None when the dog has a pick or there is nothing to say.
    next_game_text = None if picks else next_game_line(now, upcoming or [])
    elsewhere_text = None
    if not picks and other_live and other_live.get("games"):
        elsewhere_text = str(other_live.get("text") or "").rstrip(".") or None
    if picks:
        headline = (f"{len(picks)} {'pick qualifies' if len(picks) == 1 else 'picks qualify'} on the latest stored boards.")
    elif looked == 0 and not tickets:
        headline = "No upcoming game on the stored boards for this hound's sports."
    elif tickets and not misses:
        headline = "Nothing new qualifies right now. The tickets below are already on the record."
    else:
        headline = "Nothing qualifies right now."
    return {
        "dog_id": dog.id, "dog_name": dog.name, "kind": dog.kind, "mode": "preview",
        "as_of": common.iso(now), "newest_board_utc": common.iso(newest) if newest else None,
        "games_considered": looked, "picks": picks, "recorded": tickets,
        "closest_misses": misses[:MAX_MISSES], "miss_counts": miss_counts, "nothing_qualifies": nothing,
        "games": _by_game(picks, tickets, misses),
        "next_game": next_game_text, "live_elsewhere": elsewhere_text,
        "headline": headline, "notes": notes, "preview_note": PREVIEW_NOTE, "slate": slate,
        "paper_only": True, "not_advice": user_spec.NOT_ADVICE,
    }


def _by_game(picks: list, tickets: list, misses: list) -> list:
    """Every game the dog looked at, with what it did about each market: the chat answer to "why didn't you
    bet that one" reads this, not the six closest misses."""
    games: dict = {}

    def row(item) -> dict:
        return games.setdefault(item["event_id"], {"event_id": item["event_id"], "game": item["game"],
                                                     "start_utc": item["start_utc"], "markets": []})
    for p in picks:
        row(p)["markets"].append({"market": p["market"], "status": "pick", "selection": p["selection"],
                                  "price_average": p["price_average"], "why": p["reason"], "code": "pick"})
    for t in tickets:
        row(t)["markets"].append({"market": t["market"], "status": "recorded", "selection": t["selection"],
                                  "price_average": t["price_average"], "why": "Already on the dog's record.",
                                  "code": "recorded"})
    for m in misses:
        row(m)["markets"].append({"market": m["market"], "status": "miss", "code": m["code"], "why": m["why"],
                                  "selection": m.get("selection"), "gap": m.get("gap")})
    return sorted(games.values(), key=lambda g: (g["start_utc"], g["event_id"]))


# ---------------------------------------------------------------------------
# fire: house dog
# ---------------------------------------------------------------------------

_stores_cache: dict = {}
_stores_lock = threading.Lock()


def default_stores(now: datetime):
    """The pack runner's stores, loaded for this moment and remembered for five minutes. Read once under the
    process-wide heavy gate, like the daily pack run and the coach grade."""
    from src.hounds.pack import base

    def fresh():
        with _stores_lock:
            hit = _stores_cache.get("stores")
            return hit[1] if hit and time.monotonic() - hit[0] < STORES_TTL_S else None
    hit = fresh()
    if hit is not None:
        return hit
    since = max(base.SEAL_FLOOR, base.day_before(common.eastern_date(now), 8))
    until = (datetime.fromisoformat(common.eastern_date(now)) + timedelta(days=6)).date().isoformat()
    with _heavy():
        hit = fresh()                    # double-checked: see cached_games
        if hit is not None:
            return hit
        stores = base.load_stores(since=since, until=until)
        with _stores_lock:
            _stores_cache["stores"] = (time.monotonic(), stores)
    return stores


def _house_recorded(hound_id: str) -> set:
    try:
        from src.hounds import ledgers, pack_run
        return {(r.get("event_id"), r.get("market")) for r in ledgers.jsonl_rows(pack_run.ledger_path())
                if r.get("kind") == pack_run.KIND_BET and r.get("hound_id") == hound_id}
    except Exception:  # noqa: BLE001 -- the flag is a courtesy; a preview never fails over it
        return set()


def fire_house(dog: common.Dog, *, now: Optional[datetime] = None, stores=None,
               recorded: Optional[set] = None) -> dict:
    """A pack dog's current rule (its champion version's knob values) over the newest stored boards."""
    from src.hounds import pack_run
    from src.hounds.learning import champions
    from src.hounds.pack import base
    now = now or common.now_utc()
    stores = stores if stores is not None else default_stores(now)
    pack_hound = champions.champion_versions(
        (dog.house,), champions.events_path_beside(pack_run.ledger_path()))[0]
    taken = recorded if recorded is not None else _house_recorded(dog.id)
    from src.hounds import dials
    trigger = dials.TRIGGERS.get(dog.id, dials.GENERIC_TRIGGER)
    picks, misses, tickets = [], [], []
    miss_counts: dict = {}
    looked = 0
    newest = None
    events = []
    started: list = []
    for eid, ev in stores.events.items():
        start = base.resolve_start(ev)           # cheap: skip a finished or far-off game before building its context
        if start is None:
            continue
        if start <= now:
            if now - start <= STARTED_KEEP and str(ev.get("sport")).upper() in HORIZON_HOURS \
                    and pack_hound.applies_to(str(ev.get("sport"))):
                started.append((f"{ev.get('away_name')} @ {ev.get('home_name')}", start))
            continue
        if start - now > timedelta(hours=HORIZON_HOURS.get(str(ev.get("sport")).upper(), 36)):
            continue
        ctx = base.build_context(stores, eid)
        if ctx is None:
            continue
        events.append((ctx.start, eid, ctx))
    events.sort(key=lambda t: (t[0], t[1]))
    upcoming = [(f"{c.away_name} @ {c.home_name}", st, c.lock) for st, _eid, c in events
                if pack_hound.applies_to(c.sport)]
    started.sort(key=lambda t: t[1])
    for start, eid, ctx in events:
        if not pack_hound.applies_to(ctx.sport):
            continue
        accepts = getattr(pack_hound, "accepts", None)
        game_text = f"{ctx.away_name} @ {ctx.home_name}"
        if accepts is not None and not accepts(ctx):
            miss_counts["not_eligible"] = miss_counts.get("not_eligible", 0) + 1
            misses.append(_house_miss(ctx, game_text, "", "not_eligible",
                                      f"{dog.name} does not bet this game: it is outside the games this dog is built for.", None))
            continue
        quotes = stores.quotes_by_event.get(eid) or []
        seen_times = [q["observed"] for q in quotes if q["observed"] <= now and q["observed"] < ctx.start]
        board = base.build_board(quotes, at=now, start=ctx.start, sport=ctx.sport)
        if not board.get("markets"):
            miss_counts["no_board_at_lock"] = miss_counts.get("no_board_at_lock", 0) + 1
            misses.append(_house_miss(ctx, game_text, "", "no_board_at_lock",
                                      "No recent board with enough books is stored for this game.", None))
            continue
        looked += 1
        observed = max(seen_times) if seen_times else None
        newest = observed if observed and (newest is None or observed > newest) else newest
        age = _minutes(now - observed) if observed else None
        sels = pack_hound.pick(board, ctx) or []
        sel = pack_run.choose(pack_hound, board, ctx)
        if sel is not None:
            row = pack_run.bet_row(pack_hound, ctx, board, sel, segment="forward", written=now)
            if row is None:
                continue
            if (eid, sel.market) in taken:
                tickets.append({"event_id": eid, "game": game_text, "market": sel.market,
                                "market_label": market_label(sel.market, ctx.sport.upper()),
                                "selection": row["selection"], "price_average": row["price_average"],
                                "start_utc": row["start_utc"], "recorded_utc": None, "kind": "rule"})
                continue
            band = pack_hound.band
            picks.append({
                "event_id": eid, "game": game_text, "sport": ctx.sport.upper(), "market": sel.market,
                "market_label": market_label(sel.market, ctx.sport.upper()), "side": sel.side,
                "selection": row["selection"], "line": row["line"], "price_average": row["price_average"],
                "price_best": row["price_best"], "best_book": row["book"], "n_books": row["book_count"],
                "start_utc": row["start_utc"], "lock_utc": row["lock_utc"],
                "minutes_to_start": _minutes(ctx.start - now),
                "placed_in_minutes": max(0, _minutes(ctx.lock - now)), "before_lock": now < ctx.lock,
                "board_observed_utc": common.iso(observed) if observed else None,
                "board_age_minutes": age, "stale": age is not None and age > user_engine.MAX_BOARD_AGE_MINUTES,
                "day": day_of(ctx.start), "day_label": day_label(day_of(ctx.start), now),
                "slate_date": row["date"], "reason": row["reason"], "rule": trigger,
                "over_daily_limit": False, "row": None,
                "checks": [
                    {"label": "Rule", "ok": True, "detail": row["reason"]},
                    {"label": "Price band", "ok": True,
                     "detail": f"{_fmt_price(row['price_average'])} is inside {_fmt_price(max(base.PRICE_MIN, band[0]))} "
                               f"to {_fmt_price(min(base.PRICE_MAX, band[1]))}"},
                    {"label": "The -200 cap", "ok": True, "detail": "not -200 or worse"},
                ]})
            continue
        if sels:
            top = sorted(sels, key=lambda s: (-s.score, s.market, s.side))[0]
            info = base.side_info(board, top.market, top.side)
            if info is not None:
                lo, hi = max(base.PRICE_MIN, pack_hound.band[0]), min(base.PRICE_MAX, pack_hound.band[1])
                avg = info["price_average"]
                limit = lo if avg < lo else hi
                gap = _points(avg, limit)
                miss_counts["outside_price_band"] = miss_counts.get("outside_price_band", 0) + 1
                label = base.selection_label(ctx, top.market, top.side, (board["markets"][top.market] or {}).get("line"))
                misses.append(_house_miss(
                    ctx, game_text, top.market, "outside_price_band",
                    f"The rule liked {label} but it is {_fmt_price(avg)} on the board, outside this dog's band of "
                    f"{_fmt_price(lo)} to {_fmt_price(hi)}: {gap} points of win probability from the nearest limit, {_fmt_price(limit)}.",
                    gap))
                continue
        miss_counts["rule_not_met"] = miss_counts.get("rule_not_met", 0) + 1
        misses.append(_house_miss(ctx, game_text, "", "rule_not_met",
                                  f"{dog.name} bets when {trigger}. That is not the case here.", None))
    notes = ["The pack runner takes at most one bet a game and three a day per dog; those caps apply to the real tickets."]
    if any(p["stale"] for p in picks):
        notes.append("A board older than 75 minutes is flagged: its prices may have moved.")
    misses.sort(key=lambda m: (MISS_TIER.get(m["code"], 9), m["gap"] if m["gap"] is not None else 1e9,
                               m["start_utc"], m["event_id"]))
    return _payload(dog, now, picks, misses, tickets, miss_counts, looked, newest, notes, started, upcoming)


def _house_miss(ctx, game_text: str, market: str, code: str, why: str, gap) -> dict:
    return {"event_id": ctx.event_id, "game": game_text, "market": market,
            "market_label": market_label(market, ctx.sport.upper()) if market else "",
            "code": code, "title": MISS_TITLE.get(code, code), "why": why, "gap": gap,
            "unit": "points" if gap is not None else None, "start_utc": common.iso(ctx.start), "selection": None}


# ---------------------------------------------------------------------------

def fire(dog: common.Dog, *, now: Optional[datetime] = None, **kw) -> dict:
    """Fire any dog that can be fired; ``None``-free: an unsupported kind raises ``NotFirable``."""
    if dog.kind == common.KIND_USER:
        if user_spec.is_v2(dog.spec):
            # A dog built from English rules has no ``side_rule``/``price_min``: ``fire_user`` read them and raised
            # ``KeyError`` (a 500 from the Fire now button and a dead end in Ask). Same payload, the rule-set engine.
            from src.hounds.interact import ask_eval
            return ask_eval.fire_v2(dog, now=now, **kw)
        return fire_user(dog, now=now, **kw)
    if dog.kind == common.KIND_HOUSE:
        return fire_house(dog, now=now, **kw)
    raise NotFirable(f"{dog.name} cannot be fired: only the house pack and builder dogs run a rule on demand")


class NotFirable(ValueError):
    pass
