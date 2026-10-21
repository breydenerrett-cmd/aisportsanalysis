"""Unleash: start a member's hound betting TODAY, and show what it would have taken before it started.

(The button used to be the read-only "run-now preview", ``fire.py``. Owner request 2026-10-21: it starts the hound for
real, on paper, forward.)

THREE THINGS COME BACK, AND ONLY THE FIRST IS EVER WRITTEN

  picks    the bets on the hound's record for today's slate. If the hound has never bet (``already_running`` is
           false) this call places them: every game on today's board that has not reached its lock is evaluated NOW
           and the qualifying bets go through ``user_engine.run`` (``place_ahead=True``), the engine every member
           bet goes through, so the side rule, the price band, the minimum-books rule, the daily quota, the one
           bet per (hound, game, market) id, "never a game that has started" and the -200 cap are the engine's,
           line for line. The normal runner (src/hounds/user_runner.py) keeps the hound going from then on and
           finds these bets already written. A hound that has already bet is not started again: the call only
           shows the day.
  before   what the hound WOULD have taken today on games whose lock had already passed (in play, finished, or locked
           and waiting): "Before you unleashed. Not on its record." Each game is evaluated against the board as it
           stood at THAT game's lock, from the stored captures at or before the lock (the engine's replay mode, the
           same machinery as the Backtest) and never against anything later; a finished game shows
           "Would have won / lost" from the results store. It is computed into a throwaway ledger and returned in
           this response only. NOTHING in ``before`` or ``no_board`` is written to the hound's ledger, its record,
           its bankroll or the leaderboard.
  no_board games whose lock had passed and for which no capture exists at or before the lock: "no board saved for
           this game". Never a guess, and never a later board.

WHY THE TWO BUDGETS ARE SEPARATE. The "before" list is a hypothetical, so it takes up to ``max_bets_per_day`` of its
own and does not draw on (or give back to) the real day's quota. The real quota is the real ledger's, as always.

WHY A HOUND THAT HAS ALREADY BET IS ONLY SHOWN. It is already running; starting it again would be the early
placement the normal runner does at the lock anyway. For it, "before" is limited to games that locked before the
hound existed (this version's ``created_at``): a game the hound could have bet and passed on is not "before you
unleashed".

CONCURRENCY. One writer at a time in this process (``_write_lock``) and the process-wide heavy gate (the one the engine
pass takes), so a double tap, or a tap during the engine's own pass, cannot write a bet twice; the bet id makes a repeat
a no-op in any case.

Paper only. Nothing here is advice, and nothing talks to a book.
"""

from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime, timedelta
from typing import Callable, Iterable, Optional

from src.hounds import bankroll, user_engine, user_settle, user_spec
from src.hounds.interact import common, drill, fire, manual
from src.ledger.chain import HashChainLedger

BEFORE_LABEL = "Before you unleashed. Not on its record."
NO_BOARD_TEXT = "no board saved for this game"
EPOCH = "2000-01-01T00:00:00Z"            # the replay hound "existed" always: the engine's replay ignores creation anyway

_write_lock = threading.Lock()

_RESULT_WORDS = {"WIN": ("won", "Would have won"), "LOSS": ("lost", "Would have lost"),
                 "PUSH": ("push", "Would have pushed"), "VOID": ("void", "Would have been voided")}
_ROW_FIELDS = ("market", "event_id", "sport", "observed_utc") + user_engine._KEEP_FIELDS


class UnleashError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(message)


def _stake_units(row: dict) -> float:
    """Units staked on a bet row: the member dog's chosen stake, else one unit (the bankroll module's own rule)."""
    value = row.get("units")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < float(value) <= bankroll.MAX_STAKE_UNITS:
        return bankroll.FLAT_STAKE_UNITS
    return float(value)


def _slim_rows(rows: Iterable[dict]) -> list:
    """One slate's boards, trimmed to the fields the engine reads, held once for the three passes below."""
    return [{k: row[k] for k in _ROW_FIELDS if k in row} for row in rows]


def _utc(text) -> Optional[datetime]:
    return user_engine._utc(text)


def _view(row: dict, now: datetime) -> dict:
    """A bet row as the page draws it. Never the raw ledger row (it carries internal fields)."""
    units = _stake_units(row)
    commence = _utc(row["commence_time"])
    market = row["market"]
    return {
        "bet_id": row["bet_id"], "event_id": row["event_id"], "sport": row["sport"],
        "game": f"{row['away_team']} @ {row['home_team']}", "market": market,
        "market_label": fire.market_label(market, row["sport"]), "side": row["side"],
        "selection": row["selection"], "player": row.get("player"), "line": row.get("line"),
        "price_average": row["price"], "price_best": row["best_price"], "book": row.get("best_book"),
        "n_books": row["n_books"], "stake_units": units,
        "stake_usd": round(units * bankroll.params().unit_usd, 2),
        "start_utc": row["commence_time"], "lock_utc": row["lock_utc"], "reason": row.get("reason"),
        "started": bool(commence and now >= commence),
    }


def _before_item(row: dict, graded: Optional[dict], now: datetime) -> dict:
    item = _view(row, now)
    word = _RESULT_WORDS.get((graded or {}).get("result"))
    item["result"] = word[0] if word else None
    if word:
        item["state"], item["outcome"] = "finished", word[1]
    elif item["started"]:
        item["state"], item["outcome"] = "in_play", "In play, or the result is not in yet"
    else:
        item["state"], item["outcome"] = "locked", "Locked before you unleashed, not started yet"
    item["board_observed_utc"] = row.get("board_observed_utc")
    item["counted_in_record"] = False
    return item


def _sports_of(spec: dict) -> set:
    return set(spec["sports"])


def _day_games(rows: list, spec: dict, date: str) -> dict:
    """{event_id: GameBoards} for the hound's sports whose slate date is ``date``."""
    games = user_engine.build_games(rows, near_date=date)
    wanted = _sports_of(spec)
    return {eid: g for eid, g in games.items()
            if g.sport in wanted and g.commence is not None and user_engine.slate_date_of(g.commence) == date}


def _no_board(games: dict, spec: dict, now: datetime, skip: set, created: Optional[datetime]) -> list:
    """Locked games with no capture at or before their lock, in start order. A capture AFTER the lock is not a board
    for this purpose: using one would be the later data the "before" list promises never to touch."""
    out = []
    for eid, game in sorted(games.items(), key=lambda kv: (kv[1].commence, kv[0])):
        lock = game.commence - timedelta(minutes=spec["lock_minutes"])
        if lock > now or eid in skip:
            continue
        if created is not None and lock >= created:
            continue
        has = any(stamp <= lock for market in game.captures.values() for stamp in market)
        if not has:
            out.append({"event_id": eid, "game": f"{game.away_team} @ {game.home_team}", "sport": game.sport,
                        "start_utc": user_engine._iso(game.commence), "lock_utc": user_engine._iso(lock),
                        "started": now >= game.commence, "note": NO_BOARD_TEXT})
    return out


def _before_rows(date: str, hound: dict, rows: list, now: datetime, *, game_pk_index, facts, prop_rows,
                 mlb_results, nfl_results, allsports_results) -> tuple:
    """(bets, graded-by-bet-id) from a replay of today's slate into a THROWAWAY ledger. The directory is gone when the
    block ends, so nothing this builds can be read by the record, the bankroll or the leaderboard."""
    replay_hound = {"id": hound["id"], "spec": hound["spec"],
                    "spec_hash": hound.get("spec_hash") or user_spec.spec_hash(hound["spec"]), "created_at": EPOCH}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "before.jsonl")
        user_engine.run(date, [replay_hound], rows, ledger=path, now=now, mode="replay",
                        game_pk_index=game_pk_index, prop_rows=prop_rows, facts=facts)
        user_settle.settle(ledger=path, now=now, lookback_days=3, mlb_results=mlb_results,
                           nfl_results=nfl_results if nfl_results is not None else drill._local_nfl_results(),
                           close_fn=lambda _bet: None, game_pk_index=game_pk_index,
                           allsports_results=allsports_results)
        ledger_rows = HashChainLedger(path).read()
    bets = [r for r in ledger_rows if r.get("kind") == user_engine.KIND_BET]
    graded = {r["bet_id"]: r for r in ledger_rows if r.get("kind") == user_settle.KIND_GRADED}
    return bets, graded


def unleash(dog: common.Dog, owner_user_id: int, *, now: Optional[datetime] = None, rows: Optional[Iterable] = None,
            ledger: Optional[str] = None, game_pk_index: Optional[dict] = None, facts=None,
            prop_rows: Optional[Iterable] = None, mlb_results=None, nfl_results: Optional[Callable] = None,
            allsports_results=None, refresh_stats: Optional[Callable[[], object]] = None,
            manual_ledger: Optional[str] = None) -> dict:
    """Start the owner's hound today (once) and return the day. See the module docstring.

    ``rows`` (raw multibook rows of the slate), ``ledger``, ``game_pk_index``, ``facts``, ``prop_rows`` and the three
    result sources are the injection points; production leaves them unset and the stores are read."""
    now = now or common.now_utc()
    if dog.kind != common.KIND_USER or dog.hound is None or dog.owner_user_id != owner_user_id:
        raise UnleashError("not_found", "no such dog", 404)           # not-yours reads exactly like not-there
    if dog.status != "running":
        raise UnleashError("not_running", f"this dog is {dog.status}; only a running dog can be unleashed", 409)
    hound = dog.hound
    spec = hound["spec"]
    from src.pipeline import snapshots
    date = snapshots.official_date(common.iso(now))
    with _write_lock, fire._heavy():
        source = rows if rows is not None else user_engine.iter_rows(date, spec["sports"])
        slate_rows = _slim_rows(source)
        if user_spec.is_v2(spec) and facts is None:
            from src.hounds.user_facts import FactBook
            facts = FactBook.from_stores(date)
        index = game_pk_index if game_pk_index is not None else user_engine._load_game_pk_index()
        before_ids = {r["bet_id"] for r in user_engine.read_ledger(ledger)
                      if r.get("kind") == user_engine.KIND_BET and r.get("hound_id") == hound["id"]}
        already_running = bool(before_ids)
        wrote = 0
        if not already_running:
            engine_hound = {"id": hound["id"], "spec": spec,
                            "spec_hash": hound.get("spec_hash") or user_spec.spec_hash(spec),
                            "created_at": hound.get("created_at")}
            report = user_engine.run(date, [engine_hound], slate_rows, ledger=ledger, now=now, mode="live",
                                     game_pk_index=index, prop_rows=prop_rows, facts=facts, place_ahead=True)
            wrote = int(report.get("bets_written") or 0)
        after = [r for r in user_engine.read_ledger(ledger)
                 if r.get("kind") == user_engine.KIND_BET and r.get("hound_id") == hound["id"]]
        record_ids = {r["bet_id"] for r in after}
        today = sorted((r for r in after if r.get("slate_date") == date),
                       key=lambda r: (r["commence_time"], r["event_id"], user_engine.MARKET_ORDER.get(r["market"], 9)))
        picks = []
        for r in today:
            view = _view(r, now)
            view["placed_now"] = r["bet_id"] not in before_ids
            view["on_record"] = True
            picks.append(view)

        created = _utc(hound.get("created_at")) if already_running else None
        bets, graded = _before_rows(date, hound, slate_rows, now, game_pk_index=index, facts=facts,
                                    prop_rows=prop_rows, mlb_results=mlb_results, nfl_results=nfl_results,
                                    allsports_results=allsports_results)
        before = []
        for r in sorted(bets, key=lambda r: (r["commence_time"], r["event_id"], user_engine.MARKET_ORDER.get(r["market"], 9))):
            lock = _utc(r["lock_utc"])
            if r["bet_id"] in record_ids or lock is None or lock > now:
                continue                      # on the record already, or its lock has not come: not "before"
            if created is not None and lock >= created:
                continue
            before.append(_before_item(r, graded.get(r["bet_id"]), now))
        games = _day_games(slate_rows, spec, date)
        no_board = _no_board(games, spec, now, {b["event_id"] for b in before} | {p["event_id"] for p in picks},
                             created)
    if wrote and refresh_stats is None:
        try:
            from src.hounds import stats
            stats.refresh_async()
        except Exception:  # noqa: BLE001 -- the public numbers catch up on the next pass; the bets are written
            pass
    elif wrote:
        refresh_stats()
    others = _other_picks(dog, now, slate_rows if rows is not None else None, ledger, manual_ledger)
    ahead = sum(1 for g in games.values() if g.commence - timedelta(minutes=spec["lock_minutes"]) > now)
    placed = sum(1 for p in picks if p["placed_now"])
    return {
        "dog_id": dog.id, "dog_name": dog.name, "mode": "unleash", "as_of": common.iso(now), "date": date,
        "already_running": already_running, "started_now": placed > 0,
        "games_on_board": len(games), "games_ahead": ahead, "games_before": len(games) - ahead,
        "picks": picks, "placed_now": placed, "other_picks": others,
        "manual_remaining_today": manual.remaining_today(hound["id"], now, manual_ledger),
        "before": before, "before_label": BEFORE_LABEL, "no_board": no_board, "no_board_note": NO_BOARD_TEXT,
        "counted_in_record": False,
        "headline": _headline(dog.name, already_running, placed),
        "max_bets_per_day": spec["max_bets_per_day"],
        "paper_only": True, "not_advice": user_spec.NOT_ADVICE,
    }


WHY_NOT_PLACED = {
    "over_limit": "Over today's limit of {n} a day",
    "later_day": "On a later day",
    "at_lock": "Placed when it locks",
}


def _other_picks(dog: common.Dog, now: datetime, injected_rows: Optional[list], ledger: Optional[str],
                 manual_ledger: Optional[str]) -> list:
    """The picks the rule makes on the newest boards that are NOT on the record and were not placed here: over the day's
    limit, on a later day, or (for a hound that was already running) waiting for the runner at their lock. These are the
    ones the owner can add as MANUAL picks, one at a time or all at once (manual.py; they sit in their own ledger, apart
    from the record). Never fatal: a preview that cannot be built leaves the list empty, and the day view still shows.
    Classic rule dogs only: a rules (English) dog has no manual-pick path yet."""
    spec = dog.spec
    if user_spec.is_v2(spec):
        return []
    try:
        rows_for = (lambda _date, _sports: injected_rows) if injected_rows is not None else None
        games = fire.cached_games(spec["sports"], now, rows_for)
        preview = fire.fire_user(dog, now=now, games=games, ledger=ledger, other_live=lambda _own, _at: None)
        tickets = {t["bet_id"] for t in manual.tickets(dog.id, path=manual_ledger, now=now)}
        remaining = manual.remaining_today(dog.id, now, manual_ledger)
    except Exception:  # noqa: BLE001
        return []
    today = common.eastern_date(now)
    out = []
    for p in preview.get("picks", []):
        blocked = None
        if p["stale"]:
            blocked = f"the newest board is more than {user_engine.MAX_BOARD_AGE_MINUTES} minutes old"
        elif manual.manual_bet_id(dog.id, p["event_id"], p["market"]) in tickets:
            blocked = "already recorded as a manual pick"
        elif remaining <= 0:
            blocked = f"{manual.PER_DAY_LIMIT} manual picks a day is the limit"
        why = ("over_limit" if p.get("over_daily_limit") else "later_day" if p["day"] != today else "at_lock")
        units = bankroll.FLAT_STAKE_UNITS
        out.append({
            "event_id": p["event_id"], "game": p["game"], "sport": p["sport"], "market": p["market"],
            "market_label": p["market_label"], "side": p["side"], "selection": p["selection"], "line": p["line"],
            "price_average": p["price_average"], "stake_units": units,
            "stake_usd": round(units * bankroll.params().unit_usd, 2), "start_utc": p["start_utc"],
            "day_label": p["day_label"], "why_not_placed": why,
            "why_text": WHY_NOT_PLACED[why].format(n=dog.spec["max_bets_per_day"]),
            "can_record": blocked is None, "blocked": blocked})
    return out


def _headline(name: str, already_running: bool, placed: int) -> str:
    if already_running:
        return f"{name} is already running. Here is today."
    if placed:
        return f"{name} is betting today: {placed} {'pick' if placed == 1 else 'picks'} placed."
    return f"{name} is unleashed. Nothing on today's board fits its rule yet; it keeps watching and bets when a game does."
