"""What Ask runs when a question needs the dog's RULES, not its record: the boards now, the boards earlier today,
and the replay over past days. Read only. No model. Paper only.

WHY THIS MODULE EXISTS (owner's production test, 2026-10-19). A member dog with no recorded ticket was asked
"What bets would you have taken today pre market" and answered "I have not recorded a ticket yet, so there is
nothing to say about my bets". The dog was right about its record and wrong about the question: a dog with no
tickets still has a rule, and the rule can be run over today's boards. Three evaluations answer the three
questions people really ask:

  RIGHT NOW   the Fire now machinery (``fire.fire``: its 60-second board cache with the double check under the
              build gate, its rate limits at the route). A version-2 dog (one built from English rules, which is
              most members' dogs) could not be fired at all (``fire_user`` reads the version-1 spec fields and
              raised ``KeyError``); ``fire_v2`` below runs the engine's own rule-set candidates over the same boards
              and returns the SAME payload shape, so the Fire now button works for those dogs too.
  EARLIER     "what would you have taken today, pre market": every game on TODAY's slate, each judged on the board
              as it stood at that game's own decision time (``min(lock, now)``: the lock for a game whose placing
              time has passed, the newest board for one still ahead). The same point-in-time rule as the drill and the
              backtest, for a one-day window, today only, read only, and labelled hindsight: the boards were
              captured before the question was asked and the person can see how the games went.
  A WINDOW    ``drill.drill`` as it is (its half-hour cache, its one-drill-at-a-time slot); ``Busy`` carries the
              retry seconds when the slot is taken.

Nothing here writes a ledger row, an app-database row or a file that outlives the call.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.hounds import user_engine as E
from src.hounds import user_engine_v2 as V2
from src.hounds import user_rules, user_spec
from src.hounds.interact import common, drill, fire

SLATE_TTL_S = 60.0
MAX_TICKETS_SHOWN = 5

# The v2 engine tallies WHY a game produced no candidate under these names; the Fire now payload and the page speak
# in the v1 codes (``fire.MISS_TITLE``), so each is mapped, and the plain reason is worded here.
V2_CODE = {"outside_price_band": "outside_price_band", "conditions_not_met": "rule_not_met",
           "outside_line_range": "rule_not_met", "too_few_books": "too_few_books", "price_cap": "price_cap",
           "board_too_old": "board_too_old", "no_board_at_lock": "no_board_at_lock"}
V2_ORDER = ("outside_price_band", "conditions_not_met", "outside_line_range", "too_few_books", "price_cap",
            "board_too_old", "no_board_at_lock")
V2_WHY = {
    "outside_price_band": "The price on the board was outside the band my rule allows.",
    "conditions_not_met": "The price was in range, but one of my conditions did not hold for this game.",
    "outside_line_range": "The line was outside the range my rule allows.",
    "too_few_books": "Too few books were quoting it for my rule.",
    "price_cap": "It was -200 or worse, which I never take.",
    "board_too_old": "The newest board was too old to use.",
    "no_board_at_lock": "No board had been captured for it yet.",
}


class Busy(Exception):
    """The evaluation cannot run right now. ``kind`` is 'rate' (too many questions), 'drill' (the one slot is
    taken) or 'signin' (the replay is for signed-in visitors); ``retry_after`` is seconds, or None."""

    def __init__(self, kind: str, retry_after: Optional[int] = None):
        self.kind = kind
        self.retry_after = retry_after
        super().__init__(f"busy: {kind}")


# ---------------------------------------------------------------------------
# slates (version-2 dogs, and earlier today)
# ---------------------------------------------------------------------------

_slates: dict = {}
_slates_lock = threading.Lock()


def _with_props(spec: dict) -> bool:
    if not user_spec.is_v2(spec):
        return False
    return any(user_rules.market_kind(m) == "prop" for r in spec["rules"] for m in r["markets"])


def default_slate(date: str, with_props: bool):
    """One slate date's boards and facts, remembered for a minute and built under the process-wide build gate with a
    double check (the same herd guard as ``fire.cached_games``: twenty simultaneous questions read the store once)."""
    key = (date, bool(with_props))

    def fresh():
        with _slates_lock:
            hit = _slates.get(key)
            return hit[1] if hit and time.monotonic() - hit[0] < SLATE_TTL_S else None
    hit = fresh()
    if hit is not None:
        return hit
    with fire._heavy():
        hit = fresh()
        if hit is not None:
            return hit
        slate = V2.build_slate(date, user_spec.SPORTS, with_props=with_props)
        with _slates_lock:
            _slates[key] = (time.monotonic(), slate)
    return slate


def clear_cache() -> None:
    with _slates_lock:
        _slates.clear()


# ---------------------------------------------------------------------------
# candidates for one dog on one slate date, version 1 and version 2 alike
# ---------------------------------------------------------------------------

def _market_label(market: str, sport: str) -> str:
    if market == "spread" and sport == "MLB":
        return "Run line"
    return user_rules.MARKET_LABELS.get(market) or fire.market_label(market, sport)


def _candidates(dog: common.Dog, spec: dict, games: dict, facts, date: str, now: datetime, seen: set,
                skipped: Counter, misses: list, dropped: Optional[list] = None) -> list:
    """Ranked candidates [(key, lock, event_id, market, game, commence, cand, bet_id)] of the dog's rule over
    ``games`` at each game's decision time ``min(lock, now)``, and (version 1) a plain miss per market that
    produced none. A version-2 dog's misses are worked out per game by ``_v2_misses``."""
    if user_spec.is_v2(spec):
        hound = {"id": dog.id, "spec": spec, "created_at": None}
        ranked = V2.hound_candidates(hound, spec, games, facts, date, mode="replay", clock=lambda: now,
                                     seen_ids=seen, game_pk_index=None, skipped=skipped, considered={},
                                     preview_now=now, dropped=dropped)
        ranked.sort(key=lambda c: c[0])
        return ranked
    out = []
    for event_id, game in games.items():
        commence = game.commence
        lock_utc = commence - timedelta(minutes=spec["lock_minutes"])
        as_of = min(lock_utc, now)
        for market in spec["markets"]:
            if E.bet_id_for(dog.id, event_id, market) in seen:
                continue
            cand, code = E.evaluate(spec, game, market, as_of, commence)
            if cand is None:
                skipped[code] += 1
                found = game.board_at(market, as_of)
                info = (fire._explain(spec, game, market, found[0], code) if found is not None
                        else {"why": "No board has been captured for this market yet.", "gap": None})
                misses.append(fire._miss(game, market, code, info))
                continue
            out.append(((lock_utc, event_id, E.MARKET_ORDER[market]), lock_utc, event_id, market, game, commence,
                        cand, E.bet_id_for(dog.id, event_id, market)))
    out.sort(key=lambda c: c[0])
    return out


def _v2_misses(dog: common.Dog, spec: dict, games: dict, facts, date: str, now: datetime, seen: set,
               qualifying: set) -> list:
    """One miss per game a version-2 dog passed on: the engine is asked about that game alone, and the tally of
    reasons it gives is ranked nearest-first (a price just outside the band before a missing board)."""
    misses = []
    for event_id, game in games.items():
        if event_id in qualifying:
            continue
        skipped: Counter = Counter()
        found = _candidates(dog, spec, {event_id: game}, facts, date, now, seen, skipped, [])
        if found:
            continue
        code = next((c for c in V2_ORDER if skipped.get(c)), None)
        unknown = sorted(k[len("unknown_"):] for k in skipped if k.startswith("unknown_"))
        if code is None and not unknown:
            continue
        if code is None:
            why = "I did not have the data for one of my conditions (" + ", ".join(unknown).replace("_", " ") + ")."
            fire_code = "rule_not_met"
        else:
            why = V2_WHY[code]
            fire_code = V2_CODE[code]
            if code == "conditions_not_met" and unknown:
                why += " I did not have the data for " + ", ".join(unknown).replace("_", " ") + "."
        misses.append(fire._miss(game, "", fire_code, {"why": why, "gap": None}))
    return misses


def _reason(spec: dict, cand: dict, market: str, date: str, commence: str = "") -> str:
    row = {"side": cand["side"], "market": market, "selection": cand["selection"], "price": cand["price"],
           "n_books": cand["n_books"], "best_price": cand["best_price"], "best_book": cand["best_book"],
           "slate_date": date, "rule_index": cand.get("rule_index"), "commence_time": commence}
    return E.contract_fields(row, spec, "replay")["reason"]


def _checks(spec: dict, cand: dict, reason: str) -> list:
    checks = [{"label": "Board", "ok": True,
               "detail": f"{cand['n_books']} books quoting; the board used is {fire._hm(int(cand['board_age_minutes']))} "
                         "older than the decision time"},
              {"label": "Rule", "ok": True, "detail": reason}]
    if user_spec.is_v2(spec) and cand.get("rule_index") is not None:
        try:
            from src.hounds.english import render
            checks[1]["detail"] = render.rule_sentence(spec["rules"][cand["rule_index"]])
        except Exception:  # noqa: BLE001 -- the sentence is a courtesy; the reason line says the same
            pass
    checks.append({"label": "The -200 cap", "ok": True, "detail": f"{fire._fmt_price(cand['price'])} is not -200 or worse"})
    return checks


def _row(dog: common.Dog, spec: dict, item: tuple, now: datetime, date: str) -> dict:
    """The ledger row a version-2 pick would be, in the engine's own shape (``user_engine.run`` builds the same). The
    manual pick writes this row (plus its manual tags) to its own ledger; nothing else reads it."""
    _key, lock_utc, event_id, market, game, commence, cand, bet_id = item
    row = {
        "kind": E.KIND_BET, "ledger_version": E.LEDGER_VERSION, "paper_only": True,
        "bet_id": bet_id, "hound_id": dog.id,
        "spec_hash": (dog.hound or {}).get("spec_hash") or user_spec.spec_hash(spec),
        "sport": game.sport, "event_id": event_id, "game_pk": None, "slate_date": date,
        "commence_time": E._iso(commence), "away_team": game.away_team, "home_team": game.home_team,
        "market": market, "side": cand["side"], "line": cand["line"], "selection": cand["selection"],
        "price": cand["price"], "best_price": cand["best_price"], "best_book": cand["best_book"],
        "n_books": cand["n_books"], "lock_minutes": spec["lock_minutes"], "lock_utc": E._iso(lock_utc),
        "board_observed_utc": cand["board_observed_utc"], "board_age_minutes": cand["board_age_minutes"],
        "units": spec["stake_units"], "recorded_utc": E._iso(now), "provenance": "live",
        "player": cand.get("player"), "rule_index": cand["rule_index"], "stake_units": spec["stake_units"],
        "spec_version": user_spec.SPEC_VERSION_V2,
    }
    if game.league:
        row["league"] = game.league
        row["league_title"] = game.league_title
    row.update(E.contract_fields(row, spec, "live"))
    return row


def _pick(dog: common.Dog, spec: dict, item: tuple, now: datetime, date: str, over: bool,
          with_row: bool = False) -> dict:
    _key, lock_utc, event_id, market, game, commence, cand, _bet = item
    observed = E._utc(cand["board_observed_utc"])
    age = fire._minutes(now - observed) if observed else None
    reason = _reason(spec, cand, market, date, E._iso(commence))
    start_day = fire.day_of(commence)
    return {
        "event_id": event_id, "game": fire._game_text(game), "sport": game.sport, "market": market,
        "market_label": _market_label(market, game.sport), "side": cand["side"], "selection": cand["selection"],
        "line": cand["line"], "price_average": cand["price"], "price_best": cand["best_price"],
        "best_book": cand["best_book"], "n_books": cand["n_books"], "start_utc": E._iso(commence),
        "lock_utc": E._iso(lock_utc), "minutes_to_start": fire._minutes(commence - now),
        "placed_in_minutes": max(0, fire._minutes(lock_utc - now)), "before_lock": now < lock_utc,
        "decided_utc": E._iso(min(lock_utc, now)), "started": commence <= now,
        "board_observed_utc": cand["board_observed_utc"], "board_age_minutes": age,
        "stale": age is not None and age > E.MAX_BOARD_AGE_MINUTES and now < lock_utc,
        "slate_date": date, "day": start_day, "day_label": fire.day_label(start_day, now), "reason": reason,
        "rule": (user_spec.SIDE_LABELS.get(spec.get("side_rule")) or "my rules"), "over_daily_limit": over,
        "checks": _checks(spec, cand, reason), "player": cand.get("player"),
        "row": _row(dog, spec, item, now, date) if with_row and user_spec.is_v2(spec) else None,
    }


def _ledger_rows(dog_id: str, ledger: Optional[str]) -> list:
    try:
        return [r for r in E.read_ledger(ledger) if r.get("kind") == E.KIND_BET and r.get("hound_id") == dog_id]
    except Exception:  # noqa: BLE001 -- the record is a courtesy here; an unreadable ledger never blocks an answer
        return []


def _recorded_ticket(r: dict) -> dict:
    return {"event_id": r.get("event_id"), "game": f"{r.get('away_team')} @ {r.get('home_team')}",
            "market": r.get("market"), "market_label": _market_label(str(r.get("market")), str(r.get("sport"))),
            "selection": r.get("selection"), "price_average": r.get("price"), "recorded_utc": r.get("recorded_utc"),
            "start_utc": r.get("commence_time"), "kind": "rule", "side": r.get("side"),
            "line": r.get("line"), "player": r.get("player"), "sport": r.get("sport")}


def _dates(spec: dict, now: datetime) -> list:
    return fire.horizon_dates(spec["sports"], now)


# ---------------------------------------------------------------------------
# right now, version-2 dogs
# ---------------------------------------------------------------------------

def fire_v2(dog: common.Dog, *, now: Optional[datetime] = None, ledger: Optional[str] = None,
            slate_for: Optional[Callable] = None, other_live: Optional[Callable] = None,
            dropped: Optional[list] = None, with_rows: bool = False, **_ignored) -> dict:
    """``fire.fire_user`` for a dog built from English rules: the engine's own rule-set candidates over the newest
    stored boards of every upcoming game, in the Fire now payload shape. The daily limit counts the tickets the dog
    has already recorded for the slate date, in the engine's own order (earliest placing time first)."""
    now = now or common.now_utc()
    spec = dog.spec
    if other_live is None and slate_for is None:
        other_live = fire.default_other_live()          # the production path only; a test injects its own
    slate_for = slate_for or default_slate
    rows = _ledger_rows(dog.id, ledger)
    seen = {r["bet_id"] for r in rows}
    used: Counter = Counter(r["slate_date"] for r in rows)
    picks, misses, tickets = [], [], []
    started: list = []
    upcoming: list = []
    miss_counts: dict = {}
    looked = 0
    newest = None
    wanted = {s for r in spec["rules"] for s in r["sports"]}
    for date in _dates(spec, now):
        slate = slate_for(date, _with_props(spec))
        games = {}
        for event_id, game in slate.games.items():
            if game.commence is None or game.sport not in wanted:
                continue
            if game.commence <= now:
                started.append((fire._game_text(game), game.commence))
                continue
            if game.commence - now > timedelta(hours=fire.HORIZON_HOURS.get(game.sport, 36)):
                continue
            games[event_id] = game
            upcoming.append((fire._game_text(game), game.commence,
                             game.commence - timedelta(minutes=spec["lock_minutes"])))
        looked += len(games)
        skipped: Counter = Counter()
        ranked = _candidates(dog, spec, games, slate.facts, date, now, seen, skipped, [], dropped)
        position = 0
        for item in ranked:
            over = used[date] + position >= spec["max_bets_per_day"]
            position += 1
            pick = _pick(dog, spec, item, now, date, over, with_rows)
            # the hound's own order within the slate day (its ``rank_by``): the page's "what I'd play right now" reads it
            pick["rank_in_day"] = position - 1
            pick["rank_by"] = spec.get("rank_by")
            picks.append(pick)
            observed = E._utc(pick["board_observed_utc"])
            newest = observed if observed and (newest is None or observed > newest) else newest
        for code, n in skipped.items():
            miss_counts[V2_CODE.get(code, "rule_not_met")] = miss_counts.get(V2_CODE.get(code, "rule_not_met"), 0) + n
        qualifying = {item[2] for item in ranked}
        misses += _v2_misses(dog, spec, games, slate.facts, date, now, seen, qualifying)
    for r in rows:
        start = E._utc(r.get("commence_time"))
        if start is not None and start > now:
            tickets.append(_recorded_ticket(r))
    picks.sort(key=lambda p: (p["start_utc"], p["event_id"]))
    misses.sort(key=lambda m: (fire.MISS_TIER.get(m["code"], 9), m["start_utc"], m["event_id"]))
    notes = []
    if dog.status != "running":
        notes.append(f"This dog is {dog.status}; the live engine is not placing its tickets.")
    if any(p["over_daily_limit"] for p in picks):
        notes.append(f"The daily limit is {spec['max_bets_per_day']} ticket(s) a day, so the engine would stop "
                     "before the ones marked over the limit.")
    elsewhere = fire.other_sports_live(other_live, sorted(wanted), now, started, upcoming, bool(picks))
    return fire._payload(dog, now, picks, misses, tickets, miss_counts, looked, newest, notes, started, upcoming,
                         elsewhere)


# ---------------------------------------------------------------------------
# earlier today
# ---------------------------------------------------------------------------

HINDSIGHT_NOTE = ("Hindsight, not a ticket: each game is judged on the board as it stood at that game's own decision "
                  "time, but the boards were captured before you asked and you can see how the games went. "
                  "Nothing here is recorded or counted. Paper only, not advice.")


def earlier_user(dog: common.Dog, *, now: Optional[datetime] = None, slate_for: Optional[Callable] = None) -> dict:
    """What a member dog's rule would have taken on TODAY's slate, each game judged at its own decision time."""
    now = now or common.now_utc()
    spec = dog.spec
    slate_for = slate_for or default_slate
    date = common.eastern_date(now)
    slate = slate_for(date, _with_props(spec))
    wanted = {s for r in spec["rules"] for s in r["sports"]} if user_spec.is_v2(spec) else set(spec["sports"])
    games = {eid: g for eid, g in slate.games.items() if g.commence is not None and g.sport in wanted}
    skipped: Counter = Counter()
    misses: list = []
    ranked = _candidates(dog, spec, games, slate.facts, date, now, set(), skipped, misses)
    picks = []
    for position, item in enumerate(ranked):
        picks.append(_pick(dog, spec, item, now, date, position >= spec["max_bets_per_day"]))
    if user_spec.is_v2(spec):
        misses = _v2_misses(dog, spec, games, slate.facts, date, now, set(), {item[2] for item in ranked})
    misses.sort(key=lambda m: (fire.MISS_TIER.get(m["code"], 9), m["gap"] if m.get("gap") is not None else 1e9,
                               m["start_utc"], m["event_id"]))
    newest = max((E._utc(p["board_observed_utc"]) for p in picks if p["board_observed_utc"]), default=None)
    counts: dict = {}
    for m in misses:
        counts[m["code"]] = counts.get(m["code"], 0) + 1
    out = fire._payload(dog, now, picks, misses, [], counts, len(games), newest, [], [], [])
    return _earlier(out, date, now)


def _earlier(payload: dict, date: str, now: datetime) -> dict:
    payload.update({"mode": "earlier", "hindsight": True, "slate_date": date, "preview_note": HINDSIGHT_NOTE,
                    "slate": None,
                    "headline": (f"{len(payload['picks'])} {'pick' if len(payload['picks']) == 1 else 'picks'} would have "
                                 "qualified today, in hindsight." if payload["picks"] else
                                 "Nothing would have qualified today, in hindsight."),
                    "as_of": common.iso(now)})
    return payload


def earlier_house(dog: common.Dog, *, now: Optional[datetime] = None, stores=None) -> dict:
    """A pack dog's rule over today's games that have STARTED, each on the board at its own placing time: the pack
    runner's replay into a temporary ledger (the drill's machinery for a one-day window, today included)."""
    import os
    import tempfile
    from src.hounds import dials, pack_run
    from src.hounds.learning import champions
    from src.hounds.pack import base
    from src.ledger.chain import HashChainLedger
    now = now or common.now_utc()
    date = common.eastern_date(now)
    hound = champions.champion_versions((dog.house,), champions.events_path_beside(pack_run.ledger_path()))[0]
    with fire._heavy():
        if stores is None:
            stores = fire.default_stores(now)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "earlier.jsonl")
            counts = pack_run.run(stores, [date], replay=True, now=now, path=path, hounds=[hound],
                                  out=lambda *_a, **_k: None)
            rows = [r for r in HashChainLedger(path).read() if r.get("kind") == pack_run.KIND_BET]
    trigger = dials.TRIGGERS.get(dog.id, dials.GENERIC_TRIGGER)
    picks = []
    for r in sorted(rows, key=lambda r: (r["start_utc"], r["event_id"])):
        start = E._utc(r["start_utc"])
        day = fire.day_of(start)
        picks.append({
            "event_id": r["event_id"], "game": f"{r['away']} @ {r['home']}", "sport": str(r.get("sport") or "").upper(),
            "market": r["market"], "market_label": fire.market_label(r["market"], str(r.get("sport") or "").upper()),
            "side": r.get("side"), "selection": r["selection"], "line": r.get("line"),
            "price_average": r["price_average"], "price_best": r["price_best"], "best_book": r.get("book"),
            "n_books": r.get("book_count"), "start_utc": r["start_utc"], "lock_utc": r.get("lock_utc"),
            "before_lock": False, "started": True, "decided_utc": r.get("lock_utc"), "slate_date": r["date"],
            "day": day, "day_label": fire.day_label(day, now), "reason": r["reason"], "rule": trigger,
            "over_daily_limit": False, "checks": [], "row": None, "stale": False})
    out = fire._payload(dog, now, picks, [], [], {}, int(counts.get("games", 0)), None, [], [], [])
    out["passes"] = int(counts.get("passes", 0))
    out["trigger"] = trigger
    return _earlier(out, date, now)


def earlier_today(dog: common.Dog, *, now: Optional[datetime] = None, **inject) -> dict:
    if getattr(dog, "forward_only", False):
        from src.hounds import ai_defs
        raise fire.NotFirable(ai_defs.forward_only_message(dog.id))        # an AI hound is never replayed, not even over today
    if dog.kind == common.KIND_USER:
        return earlier_user(dog, now=now, **inject)
    if dog.kind == common.KIND_HOUSE:
        return earlier_house(dog, now=now, **inject)
    raise fire.NotFirable(f"{dog.name} cannot be run on demand: only the house pack and builder dogs run a rule")


# ---------------------------------------------------------------------------
# a window of past days
# ---------------------------------------------------------------------------

def backtest(dog: common.Dog, days: int, *, signed_in: bool, now: Optional[datetime] = None, **inject) -> dict:
    """``drill.drill`` for a dog and a window. A result the drill already remembers is free for anyone; running one
    is for signed-in visitors (it is the heaviest thing the site does). Raises ``Busy`` when the slot is taken."""
    hit = None if inject else drill.peek(dog, days, now)
    if hit is not None:
        return hit
    if not signed_in and not inject:
        raise Busy("signin")
    try:
        return drill.drill(days=days, dog=dog, now=now, **inject)
    except drill.DrillError as exc:
        if exc.code == "drill_busy":
            raise Busy("drill", exc.retry_after or drill.BUSY_RETRY_AFTER_S)
        raise
