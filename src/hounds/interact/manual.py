"""The owner's manual pick: "Record it as a manual pick".

A MANUAL TICKET IS NOT THE DOG'S TICKET. The dog's rule record is the hash-chained user ledger the engine
writes (``user_engine.ledger_path()``) and the public stats read. A manual pick goes to a SEPARATE ledger
beside it (``hounds_manual_v1.jsonl``), which nothing in the stats, the leaderboard, the referee or the
learning loop reads. So a manual pick can never reach the dog's record, its verdict, its CLV, or its rank:
there is no filter to forget, because the rows are not in the file those readers open.

It is graded the same way: the rows are the engine's own bet rows (``kind`` ``hound_user_bet``, plus
``manual: true``), and ``user_settle.settle`` is pointed at the manual ledger, so the card ledger's grader, the
same results store and the same two prices (average = headline, best = small print) decide the result.

THE RULES (each is a refusal with a stable code, and each has a test):
  * only the dog's OWNER, and only a RUNNING user dog;
  * the pick must be one the dog's rule would make right now (the same ``fire_user`` evaluation: side rule,
    price band, minimum books, and the -200 cap that is not a setting);
  * the game must not have started, and the board the price comes from must be fresh (75 minutes, the
    engine's own limit): no recording a price off a stale capture;
  * one manual ticket per dog per game and market, and none on a game the rule ticket already covers;
  * one side per game (src/hounds/one_side.py): never the other side of a game the dog already holds, in the
    dog's rule ledger OR in the manual ledger, and never a second ticket on the same side;
  * 5 a day per dog, counted from the ledger itself (the Eastern date it was recorded);
  * paper only: the row says so and nothing is placed anywhere.

The server recomputes the price from the stored board. The client sends only WHICH pick (game and market),
never a price.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from src.hounds import one_side, user_engine, user_rules, user_spec
from src.hounds.contract import ticket_status
from src.hounds.interact import ask_eval, common, fire
from src.ledger.chain import HashChainLedger

LEDGER_NAME = user_engine.MANUAL_LEDGER_NAME      # one name, read by the engine's one-side guard too
ENV_LEDGER = user_engine.MANUAL_LEDGER_ENV
PER_DAY_LIMIT = 5
SETTLE_EVERY_S = 600.0

NOTE_COUNTED = "Manual picks are kept apart. They are never counted in the dog's rule record or on the leaderboard."

_write_lock = threading.Lock()
_settle_state = {"at": 0.0}


class ManualError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(message)


def ledger_path(path: Optional[str] = None) -> str:
    """Beside the user ledger (so a test that moves one moves the other), or HOUNDS_MANUAL_LEDGER."""
    if path:
        return path
    override = (os.environ.get(ENV_LEDGER) or "").strip()
    if override:
        return override
    return str(Path(user_engine.ledger_path()).with_name(LEDGER_NAME))


def read_all(path: Optional[str] = None) -> list:
    return HashChainLedger(ledger_path(path)).read()


def _split(rows, hound_id: Optional[str] = None) -> tuple:
    bets = [r for r in rows if r.get("kind") == user_engine.KIND_BET and (hound_id is None or r.get("hound_id") == hound_id)]
    graded = {r["bet_id"]: r for r in rows if r.get("kind") == "hound_user_graded"}
    return bets, graded


def recorded_today(hound_id: str, now: datetime, path: Optional[str] = None) -> int:
    today = common.eastern_date(now)
    bets, _ = _split(read_all(path), hound_id)
    n = 0
    for r in bets:
        when = user_engine._utc(r.get("recorded_utc"))
        if when is not None and common.eastern_date(when) == today:
            n += 1
    return n


def remaining_today(hound_id: str, now: datetime, path: Optional[str] = None) -> int:
    return max(0, PER_DAY_LIMIT - recorded_today(hound_id, now, path))


def manual_bet_id(hound_id: str, event_id: str, market: str, player: Optional[str] = None) -> str:
    """One manual ticket per dog per game and market; a player prop is one per player too (the same key the rule engine
    uses for its own bet id, so a game with two players' props can carry both). No player: the id every older ticket has."""
    who = user_rules.fold_player(str(player)) if player else ""
    return "m-" + hashlib.sha256(f"manual|{hound_id}|{event_id}|{market}{'|' + who if who else ''}".encode()).hexdigest()[:20]


def _same_player(a, b) -> bool:
    fa = user_rules.fold_player(str(a)) if a else ""
    fb = user_rules.fold_player(str(b)) if b else ""
    return fa == fb


def rule_picks(dog: common.Dog, now: datetime, *, games: Optional[dict] = None, rule_ledger: Optional[str] = None,
               rows_for: Optional[Callable] = None, slate_for: Optional[Callable] = None,
               dropped: Optional[list] = None) -> dict:
    """The picks the dog's rule makes on the newest stored boards, each with the ledger ``row`` it would be: the SAME
    evaluation the Unleash button and the Fire panel draw, for either kind of dog.

    A classic dog (side rule + price band) runs ``fire.fire_user``; a dog built from English rules (version 2, the
    kind most members' dogs are) runs ``ask_eval.fire_v2``, the rule-set engine's own candidates. Until 2026-10-21
    only the first existed here, so the manual pick on an English-rules dog's card answered with a 500 (``fire_user``
    reads fields only a classic spec has). ``dropped`` collects what the one-side-per-game guard removed."""
    if user_spec.is_v2(dog.spec):
        return ask_eval.fire_v2(dog, now=now, ledger=rule_ledger, slate_for=slate_for,
                                other_live=lambda _own, _at: None, dropped=dropped, with_rows=True)
    return fire.fire_user(dog, now=now, games=games, ledger=rule_ledger, rows_for=rows_for,
                          other_live=lambda _own, _at: None, dropped=dropped)


def _dropped_code(dropped: Optional[list], event_id: str, market: str, player: Optional[str]) -> Optional[str]:
    """The one-side code that removed (event, market[, player]) from the picks, or None."""
    for item, code in dropped or []:
        if isinstance(item, dict):
            e, m, who = item["event_id"], item["market"], item.get("player")
        else:                                           # a version-2 candidate tuple
            e, m, who = item[2], item[3], item[6].get("player")
        if e == event_id and m == market and _same_player(who, player):
            return code
    return None


def _owner_stamp(user_id: int) -> str:
    return hashlib.sha256(f"manual-owner:{user_id}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------

def record(dog: common.Dog, user_id: int, event_id: str, market: str, *, now: Optional[datetime] = None,
           games: Optional[dict] = None, ledger: Optional[str] = None, rule_ledger: Optional[str] = None,
           rows_for: Optional[Callable] = None, player: Optional[str] = None, slate_for: Optional[Callable] = None,
           preview: Optional[dict] = None, dropped: Optional[list] = None) -> dict:
    """Record one manual ticket, or raise ``ManualError``. See the module docstring for every refusal.

    ``player`` names the player of a prop pick (a game can carry several). ``preview``/``dropped`` are the picks
    ``rule_picks`` already worked out (a batch computes them once for all its picks); ``slate_for`` is the version-2
    boards seam, as in ``ask_eval.fire_v2``."""
    now = now or common.now_utc()
    if dog.kind != common.KIND_USER or dog.hound is None:
        raise ManualError("not_a_builder_dog", "manual picks are for dogs people built", 403)
    if dog.owner_user_id != user_id:
        raise ManualError("not_owner", "only the owner can record a manual pick", 403)
    if dog.status != "running":
        raise ManualError("not_running", f"this dog is {dog.status}; manual picks need a running dog", 409)
    if market not in user_spec.MARKETS:
        raise ManualError("market_invalid", "pick a market this dog bets", 422)
    path = ledger_path(ledger)
    if recorded_today(dog.id, now, path) >= PER_DAY_LIMIT:
        raise ManualError("rate_limited", f"{PER_DAY_LIMIT} manual picks a day is the limit for one dog", 429)
    v2 = user_spec.is_v2(dog.spec)
    if preview is None:
        # the dog's own evaluation, on the newest stored boards: the same function the preview shows
        dropped = []
        preview = rule_picks(dog, now, games=games, rule_ledger=rule_ledger, rows_for=rows_for, slate_for=slate_for,
                             dropped=dropped)
    if v2:
        # a version-2 preview leaves out what the rule ledger already holds, so look there for the plain answer
        key = market if not player else f"{market}|{user_rules.fold_player(str(player))}"
        rule_bet = user_engine.bet_id_for(dog.id, event_id, key)
        on_record = any(r.get("kind") == user_engine.KIND_BET and r.get("bet_id") == rule_bet
                        for r in user_engine.read_ledger(rule_ledger))
    else:
        on_record = any(t["event_id"] == event_id and t["market"] == market for t in preview["recorded"])
    if on_record:
        raise ManualError("already_on_record", "the dog's own rule already has a ticket on that game and market", 409)
    pick = next((p for p in preview["picks"] if p["event_id"] == event_id and p["market"] == market
                 and _same_player(p.get("player"), player)), None)
    if pick is None:
        code = _dropped_code(dropped, event_id, market, player)
        if code is not None:                        # the pick exists, but a better-ranked one on this game holds its slot
            raise ManualError("not_a_pick", "one side per game: " + one_side.reason_text(code), 422)
        raise ManualError("not_a_pick", "the dog's rule would not make that pick on the latest boards", 422)
    commence = user_engine._utc(pick["start_utc"])
    if commence is None or now >= commence:
        raise ManualError("game_started", "that game has started; no manual pick can be recorded on it", 409)
    observed = user_engine._utc(pick.get("board_observed_utc"))
    limit = (user_spec.MAX_PROP_BOARD_AGE_MINUTES if user_rules.market_kind(market) == "prop"
             else user_engine.MAX_BOARD_AGE_MINUTES)
    if pick["stale"] or (v2 and observed is not None and (now - observed).total_seconds() / 60.0 > limit):
        raise ManualError("board_too_old",
                          f"the newest board for that game is more than {limit} "
                          "minutes old; wait for the next capture", 409)
    row = dict(pick["row"])
    if user_spec.beyond_cap(row["price"]):          # belt and braces: the cap is not a setting
        raise ManualError("price_cap", "that price is -200 or worse; the cap is always on", 422)
    row.update({
        "bet_id": manual_bet_id(dog.id, event_id, market, player), "manual": True, "provenance": "manual",
        "segment": "manual", "who_decided": "owner", "lock_utc": user_engine._iso(now),
        "recorded_utc": user_engine._iso(now), "manual_by": _owner_stamp(user_id),
        "reason": ("Manual pick by the owner. The dog's rule makes the same pick on the latest board: "
                   + pick["reason"]),
    })
    with _write_lock:                                 # re-checked under the lock: two taps cannot both pass
        store = HashChainLedger(path)
        existing = store.read()
        bets, _ = _split(existing, dog.id)
        if any(b["bet_id"] == row["bet_id"] for b in bets):
            raise ManualError("already_on_record", "you already recorded a manual pick on that game and market", 409)
        # One side per game, against everything the dog holds on that game: the rule ledger (the engine's own
        # tickets) and the manual ledger. Re-read under the lock, like the checks above.
        held = one_side.Book.from_rows(list(user_engine.read_ledger(rule_ledger)) + list(existing))
        clash = held.refusal_for_row(row)
        if clash is not None:
            raise ManualError(clash, one_side.reason_text(clash), 409)
        today = common.eastern_date(now)
        used = sum(1 for b in bets if (user_engine._utc(b.get("recorded_utc")) is not None
                                       and common.eastern_date(user_engine._utc(b["recorded_utc"])) == today))
        if used >= PER_DAY_LIMIT:
            raise ManualError("rate_limited", f"{PER_DAY_LIMIT} manual picks a day is the limit for one dog", 429)
        store.append(row)
    return ticket_view(row, None, now=now)


# ---------------------------------------------------------------------------
# recording many at once (the Unleash panel's "Add the other N as manual picks")
# ---------------------------------------------------------------------------

MAX_BATCH = 40
_SKIP_WORDS = {
    "game_started": "game already started",
    "not_a_pick": "no longer fits the rule on the latest board",
    "board_too_old": "board too old",
    "rate_limited": f"daily limit of {PER_DAY_LIMIT} manual picks reached",
    "price_cap": "priced -200 or worse",
}


def _skip_reason(exc: ManualError) -> str:
    """The words for a refusal. Known codes have fixed words; a code this module does not know (a guard added on another
    branch) speaks for itself: its own message is the reason. The one-side-per-game codes are named as that rule."""
    if exc.code == "already_on_record":
        return "already on its record" if "own rule" in str(exc) else "already recorded as a manual pick"
    if exc.code in one_side.REASONS:
        return "one side per game: " + str(exc)
    if str(exc).startswith("one side per game: "):          # a pick the rule's own ranking left out (code stays not_a_pick)
        return str(exc)
    return _SKIP_WORDS.get(exc.code) or str(exc)


def _batch_games(dog: common.Dog, now: datetime, slate_for: Optional[Callable]) -> dict:
    """{event_id: game} the dog's boards hold, for naming a started game plainly. A classic dog reads the cached
    multibook boards; a version-2 dog the same slates ``fire_v2`` reads."""
    if not user_spec.is_v2(dog.spec):
        return fire.cached_games(dog.spec["sports"], now)
    slate_for = slate_for or ask_eval.default_slate
    out: dict = {}
    for date in ask_eval._dates(dog.spec, now):
        out.update(slate_for(date, ask_eval._with_props(dog.spec)).games)
    return out


def record_batch(dog: common.Dog, user_id: int, picks: list, *, now: Optional[datetime] = None,
                 games: Optional[dict] = None, ledger: Optional[str] = None, rule_ledger: Optional[str] = None,
                 rows_for: Optional[Callable] = None, slate_for: Optional[Callable] = None) -> dict:
    """Record every listed pick that ``record`` accepts, in ONE request, and say what was skipped and why.

    Nothing is re-implemented here: each pick goes through ``record`` (the owner, running, fresh board, the rule would
    make it, the game has not started, once per game and market, five a day, and any guard added to ``record``), and a
    ``ManualError`` becomes a counted skip. So a started game is never added, a second tap adds nothing (the first
    tap's tickets are "already recorded"), and the rule that decides one side per game stays in one place.
    The boards are read once for the whole batch, and so is the rule's evaluation (``rule_picks``), for a classic dog
    and for a dog built from English rules alike. A pick the one-side-per-game guard removed from the list says so
    ("one side per game: ...") instead of "no longer fits the rule"."""
    now = now or common.now_utc()
    if dog.kind != common.KIND_USER or dog.hound is None:
        raise ManualError("not_a_builder_dog", "manual picks are for dogs people built", 403)
    if dog.owner_user_id != user_id:
        raise ManualError("not_owner", "only the owner can record a manual pick", 403)
    if dog.status != "running":
        raise ManualError("not_running", f"this dog is {dog.status}; manual picks need a running dog", 409)
    seen, wanted = set(), []
    for item in picks or []:
        key = (str((item or {}).get("event_id") or "").strip(), str((item or {}).get("market") or "").strip(),
               user_rules.fold_player(str((item or {}).get("player") or "")))
        if not key[0] or not key[1]:
            raise ManualError("pick_invalid", "each pick needs an event_id and a market", 422)
        if key not in seen:
            seen.add(key)
            wanted.append((key[0], key[1], str((item or {}).get("player") or "").strip() or None))
    if not wanted:
        raise ManualError("no_picks", "send at least one pick", 422)
    if len(wanted) > MAX_BATCH:
        raise ManualError("too_many", f"at most {MAX_BATCH} picks in one request", 422)
    if games is None and rows_for is None:
        games = _batch_games(dog, now, slate_for)
    dropped: list = []
    preview = rule_picks(dog, now, games=games if not user_spec.is_v2(dog.spec) else None, rule_ledger=rule_ledger,
                         rows_for=rows_for, slate_for=slate_for, dropped=dropped)
    added, results, reasons = [], [], {}
    for event_id, market, player in wanted:
        game = (games or {}).get(event_id)
        if game is not None and game.commence is not None and now >= game.commence:
            word = _SKIP_WORDS["game_started"]            # said plainly: a started game is not in the preview at all
            reasons.setdefault(word, {"code": "game_started", "reason": word, "count": 0})["count"] += 1
            results.append({"event_id": event_id, "market": market, "player": player, "status": "skipped",
                            "code": "game_started", "reason": word})
            continue
        try:
            ticket = record(dog, user_id, event_id, market, now=now, games=games, ledger=ledger,
                            rule_ledger=rule_ledger, rows_for=rows_for, player=player, slate_for=slate_for,
                            preview=preview, dropped=dropped)
        except ManualError as exc:
            word = _skip_reason(exc)
            reasons.setdefault(word, {"code": exc.code, "reason": word, "count": 0})["count"] += 1
            results.append({"event_id": event_id, "market": market, "player": player, "status": "skipped",
                            "code": exc.code, "reason": word})
            continue
        added.append(ticket)
        results.append({"event_id": event_id, "market": market, "player": player, "status": "added",
                        "code": None, "reason": None})
    skipped = len(wanted) - len(added)
    line = f"Added {len(added)}"
    if skipped:
        line += f" · skipped {skipped} (" + ", ".join(
            f"{r['count']} {r['reason']}" if len(reasons) > 1 or r["count"] != skipped else r["reason"]
            for r in reasons.values()) + ")"
    return {"requested": len(wanted), "added": len(added), "skipped": skipped, "reasons": list(reasons.values()),
            "results": results, "tickets": added, "line": line,
            "remaining_today": remaining_today(dog.id, now, ledger)}


# ---------------------------------------------------------------------------
# reading and settling
# ---------------------------------------------------------------------------

def ticket_view(bet: dict, graded: Optional[dict], *, now: Optional[datetime] = None) -> dict:
    result = (graded or {}).get("result")
    status = ticket_status(result.lower() if result else None, bet.get("commence_time"), bet.get("slate_date"), now)
    word = {"WIN": "WON", "LOSS": "LOST", "PUSH": "PUSH", "VOID": "VOID"}.get(result or "", None)
    return {
        "kind": "manual", "bet_id": bet["bet_id"], "hound_id": bet["hound_id"], "date": bet["slate_date"],
        "game": f"{bet['away_team']} @ {bet['home_team']}", "market": bet["market"], "selection": bet["selection"],
        "line": bet.get("line"), "price_average": bet["price"], "price_best": bet["best_price"],
        "book": bet.get("best_book"), "book_count": bet.get("n_books"), "start_utc": bet["commence_time"],
        "recorded_utc": bet["recorded_utc"], "reason": bet.get("reason"),
        "status": word or ("UNGRADED" if status == "UNGRADED" else "PENDING"), "result": result,
        "units_average_price": (graded or {}).get("units_average_price"),
        "units_best_price": (graded or {}).get("units_best_price"),
        "clv_pts": (graded or {}).get("clv_pts"), "counted_in_record": False,
    }


def tickets(hound_id: str, *, path: Optional[str] = None, now: Optional[datetime] = None) -> list:
    bets, graded = _split(read_all(path), hound_id)
    out = [ticket_view(b, graded.get(b["bet_id"]), now=now) for b in bets]
    out.sort(key=lambda t: (t["recorded_utc"], t["bet_id"]), reverse=True)
    return out


def record_summary(items: list) -> dict:
    """The manual record, apart: graded counts and units at the average price (the headline price)."""
    wins = sum(1 for t in items if t["result"] == "WIN")
    losses = sum(1 for t in items if t["result"] == "LOSS")
    pushes = sum(1 for t in items if t["result"] == "PUSH")
    voids = sum(1 for t in items if t["result"] == "VOID")
    units = sum(t["units_average_price"] for t in items if isinstance(t.get("units_average_price"), (int, float))
                and t["result"] in ("WIN", "LOSS", "PUSH"))
    return {"tickets": len(items), "graded": wins + losses + pushes, "wins": wins, "losses": losses,
            "pushes": pushes, "voids": voids, "open": sum(1 for t in items if t["result"] is None),
            "units_average_price": round(units, 4), "note": NOTE_COUNTED}


def settle_manual(*, now: Optional[datetime] = None, ledger: Optional[str] = None, **kwargs) -> dict:
    """Grade the manual tickets whose games are final, with the same grader the dogs' tickets use."""
    from src.hounds import user_settle
    return user_settle.settle(ledger=ledger_path(ledger), now=now, **kwargs)


def maybe_settle(now: Optional[datetime] = None, *, ledger: Optional[str] = None, force: bool = False,
                 **kwargs) -> Optional[dict]:
    """``settle_manual`` at most every ten minutes, and only when a manual ticket's game could be final. It is
    called when a page reads the manual tickets (and by the engine pass), so a manual ticket grades without a
    second scheduler. Never raises: a results store that cannot be read leaves the ticket ungraded."""
    now = now or common.now_utc()
    if not force and time.monotonic() - _settle_state["at"] < SETTLE_EVERY_S:
        return None
    path = ledger_path(ledger)
    if not Path(path).exists():
        return None
    bets, graded = _split(read_all(path))
    waiting = [b for b in bets if b["bet_id"] not in graded
               and (user_engine._utc(b["commence_time"]) or now) + timedelta(hours=2) <= now]
    if not waiting and not force:
        return None
    _settle_state["at"] = time.monotonic()
    try:
        return settle_manual(now=now, ledger=ledger, **kwargs)
    except Exception:  # noqa: BLE001 -- ungraded is the honest state when the results cannot be read
        return None
