"""Grade a member's real, logged bets through the SAME settle path the hounds' paper tickets use.

THE BRIDGE. Each gradable LEG of a lesson is written as a bet row (the engine's own ``hound_user_bet`` shape) into a
separate hash-chained ledger, ``hounds_lessons_v1.jsonl`` beside the other ledgers. ``user_settle.settle`` then grades
it with the card ledger's grader against the results stores, exactly as it grades a hound's ticket, and the live fast
loop (src/hounds/live_settle.py) settles it too (its "lessons" label), without a "your bet settled" alert. That ledger is
read by NOTHING in the stats, the leaderboard, the referee or the learning loop: a member's real bet can never reach
any hound's paper record, because the rows are not in a file those readers open (the same trick as manual.py).

WHAT CAN BE GRADED. A leg needs the game's identity from OUR board (event id, teams, start, slate date) and a market
the grader knows: moneyline, spread and total, MLB batter/pitcher props and NBA/NHL props. A leg we cannot grade (a
typed game, an NFL prop: there is no player-stat grader for the NFL) stays open, and the ticket's own settled status
from a screenshot is the only word on it (``model.derive``). A parlay with one graded LOST leg is lost at once; otherwise
it waits until every leg is known (``calc.ticket_outcome``: one winning leg is never a winning parlay).

THE GRADER'S WORD IS AN EVENT. ``sync`` appends a ``grader`` event to the lesson; if the ticket's own status
disagrees, ``model.derive`` flags the lesson disputed. Nothing is overwritten and nothing is guessed.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.hounds import user_engine, user_rules
from src.hounds.apprentice import calc, model, store
from src.ledger.chain import HashChainLedger

LEDGER_NAME = "hounds_lessons_v1.jsonl"
ENV_LEDGER = "HOUNDS_LESSONS_LEDGER"
KIND_BET = user_engine.KIND_BET
KIND_GRADED = "hound_user_graded"
_RESULT = {"WIN": calc.WON, "LOSS": calc.LOST, "PUSH": calc.PUSH, "VOID": calc.VOID}
GAME_SIDES = {"moneyline": ("home", "away"), "spread": ("home", "away"), "total": ("over", "under")}


def ledger_path(path: Optional[str] = None) -> str:
    if path:
        return path
    override = (os.environ.get(ENV_LEDGER) or "").strip()
    return override or str(Path(user_engine.ledger_path()).with_name(LEDGER_NAME))


def leg_bet_id(lesson_id: str, i: int) -> str:
    return f"L:{lesson_id}:{i}"


def gradable(leg: Mapping) -> bool:
    """Can the existing grader settle this leg? (identity from the board, a market it knows, a side, a line when needed)"""
    if not all(leg.get(k) for k in ("event_id", "sport", "away_team", "home_team", "commence_time", "slate_date")):
        return False
    market, side = leg.get("market"), leg.get("side")
    if market in GAME_SIDES:
        return side in GAME_SIDES[market] and (market == "moneyline" or leg.get("line") is not None)
    prop = market in user_rules.PROP_STATS or (market in user_rules.ALLSPORTS_PROP_MARKETS and leg["sport"] in ("NBA", "NHL"))
    return bool(prop and leg.get("player") and leg.get("line") is not None and side in ("over", "under"))


def mirror_row(lesson: Mapping, i: int, leg: Mapping, now: datetime) -> dict:
    return {"kind": KIND_BET, "ledger_version": user_engine.LEDGER_VERSION, "paper_only": True, "lesson": True,
            "bet_id": leg_bet_id(lesson["id"], i), "hound_id": lesson["hound_root"], "sport": leg["sport"],
            "event_id": leg["event_id"], "game_pk": leg.get("game_pk"), "slate_date": leg["slate_date"],
            "commence_time": leg["commence_time"], "away_team": leg["away_team"], "home_team": leg["home_team"],
            "market": leg["market"], "side": leg["side"], "line": leg.get("line"), "selection": leg["selection"],
            "player": leg.get("player"), "price": leg["price"], "best_price": leg["price"], "best_book": lesson["book"],
            "n_books": 1, "units": 1, "stake_units": 1.0, "recorded_utc": user_engine._iso(now), "provenance": "lesson"}


def publish(lessons, *, path: Optional[str] = None, now: Optional[datetime] = None) -> int:
    """Write a mirror row for every gradable leg not yet in the mirror ledger. Idempotent. Returns rows added."""
    from datetime import timezone
    now = now or datetime.now(timezone.utc)
    ledger = HashChainLedger(ledger_path(path))
    have = {r["bet_id"] for r in ledger.read() if r.get("kind") == KIND_BET}
    added = 0
    for lesson, _events in lessons:
        for i, leg in enumerate(lesson["legs"]):
            bid = leg_bet_id(lesson["id"], i)
            if bid not in have and gradable(leg):
                ledger.append(mirror_row(lesson, i, leg, now))
                have.add(bid)
                added += 1
    return added


def settle_pending(now: Optional[datetime] = None, *, path: Optional[str] = None, **kwargs) -> Optional[dict]:
    """The slow path: ``user_settle.settle`` over the mirror ledger (the fast loop does the same on its own schedule).
    Never raises: results that cannot be read leave the legs open, which is the honest state."""
    from src.hounds import user_settle
    target = ledger_path(path)
    if not Path(target).exists():
        return None
    try:
        return user_settle.settle(ledger=target, now=now, alert=False, **kwargs)
    except Exception:  # noqa: BLE001
        return None


def graded_legs(path: Optional[str] = None) -> dict:
    """{leg bet id: {"result", "clv_pts", "close_price", "reason"}} for every leg the grader has settled."""
    out = {}
    for r in HashChainLedger(ledger_path(path)).read():
        if r.get("kind") == KIND_GRADED and r.get("result") in _RESULT:
            out[r["bet_id"]] = {"result": _RESULT[r["result"]], "clv_pts": r.get("clv_pts"),
                                "close_price": r.get("close_price"), "reason": r.get("reason")}
    return out


def decide(lesson: Mapping, graded: Mapping) -> Optional[dict]:
    """The grader's event for one lesson from the graded legs, or None while it cannot be decided."""
    results = []
    for i, leg in enumerate(lesson["legs"]):
        g = graded.get(leg_bet_id(lesson["id"], i))
        results.append(g["result"] if g else None)
    out = calc.ticket_outcome(results, [leg["price"] for leg in lesson["legs"]], lesson["stake"], None)
    if out["result"] == calc.PENDING:
        return None
    data = {"leg_results": results, "payout": out["payout"], "needs_confirmation": out["needs_confirmation"],
            "leg_clv": [(graded.get(leg_bet_id(lesson["id"], i)) or {}).get("clv_pts") for i in range(len(results))],
            "leg_close": [(graded.get(leg_bet_id(lesson["id"], i)) or {}).get("close_price") for i in range(len(results))]}
    if out["result"] == calc.VOID:
        return {"state": model.VOID, "data": data}
    data["result"] = out["result"]
    return {"state": model.SETTLED, "data": data}


def sync(hound_root: str, owner_id: int, *, path: Optional[str] = None, now: Optional[datetime] = None, run_settle: bool = False,
         settle_kwargs: Optional[dict] = None, db=None) -> dict:
    """Publish open legs, optionally settle, and append the grader's word for every lesson it can now decide.
    Idempotent: a lesson the grader already decided the same way gets no second event."""
    pairs = store.lessons_for(hound_root, db=db)
    published = publish(pairs, path=path, now=now)
    if run_settle and published is not None:
        settle_pending(now, path=path, **(settle_kwargs or {}))
    graded = graded_legs(path)
    appended = 0
    for lesson, events in pairs:
        if any(e["source"] == "grader" and e["state"] in model.TERMINAL for e in events):
            continue
        ev = decide(lesson, graded)
        if ev is None:
            continue
        if store.append_event(lesson["id"], owner_id, "grader", ev["state"], ev["data"], now=now, db=db) is not None:
            appended += 1
    return {"published": published, "graded_events": appended}
