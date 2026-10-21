"""Fire now for ONE game: "would this dog back THIS game, and if not, why?" -- read only.

POST /hounds/{id}/fire with an optional {"event_id"} body answers for that event alone:

  picked: true    the dog's rule backs it: ``pick`` is the pick, ``reason`` the rule's own words
  picked: false   it does not: ``code`` is the engine's stable reason code, ``reason`` the sentence

THREE KINDS OF EVENT
--------------------
 * A game that has not started: the answer is the ordinary Fire now evaluation (``fire.fire``) read for that
   event, so it can never disagree with the full list.
 * A game already on the record: ``picked: true`` with ``recorded: true`` (the ticket is the pick).
 * A game that HAS STARTED and has in-play snapshots (the all-sports capture marks them ``in_play``; MLB and NFL
   rows after the start are the same thing): the dog's rule is evaluated on the NEWEST in-play board, so the
   price is the live price the books showed, not the pre-game one. This is a PREVIEW (``live: true``): the
   engine never writes a ticket at or after the start, and nothing here writes anything. A live price older than
   ``LIVE_FRESH_MINUTES`` is refused (``no_live_price``): a stale live price is worse than none.

Paper only; no answer here is advice.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.hounds import one_side
from src.hounds import user_engine as E
from src.hounds import user_spec
from src.hounds.interact import common, fire
from src.sports import catalog

LIVE_FRESH_MINUTES = 90

LIVE_CODES = {
    "no_live_price": "No live price is on file for this game: the newest stored price is from before the start.",
    "live_price_too_old": f"The newest live price is more than {LIVE_FRESH_MINUTES} minutes old, too old to use.",
    "game_over": "This game is past its live window, so there is no live price to read.",
    "not_eligible": "This hound does not bet that sport.",
    "unknown_event": "That game is not on the stored boards for this hound's sports.",
    "too_far_ahead": "That game is further ahead than this hound looks.",
    "not_firable_live": "Only hounds built by members are evaluated on a live price.",
}
V2_ORDER = ("outside_price_band", "conditions_not_met", "outside_line_range", "too_few_books", "price_cap",
            "board_too_old", "no_board_at_lock")


def _base(dog: common.Dog, event_id: str, now: datetime) -> dict:
    return {"event_id": event_id, "dog_id": dog.id, "dog_name": dog.name, "as_of": common.iso(now),
            "paper_only": True, "not_advice": user_spec.NOT_ADVICE, "picked": False, "live": False,
            "recorded": False, "pick": None, "picks": [], "code": None, "reason": "", "misses": [],
            "game": None, "sport": None, "league_title": None}


def _dates(now: datetime) -> list:
    """Eastern slate dates that can hold a game now live: yesterday (an overnight game), today, tomorrow."""
    today = datetime.fromisoformat(common.eastern_date(now))
    return [(today + timedelta(days=d)).date().isoformat() for d in (-1, 0, 1)]


def _live_game(spec_sports, event_id: str, now: datetime, rows_for: Optional[Callable]):
    """The event's GameBoards (pre-game AND in-play captures), or None when no stored row names it."""
    found = None
    for date in _dates(now):
        source = rows_for(date, spec_sports) if rows_for else E.iter_rows(date, spec_sports)
        found = E.build_event_game(source, event_id)
        if found is not None:
            return found
    return None


def _from_payload(payload: dict, event_id: str, out: dict) -> Optional[dict]:
    """The answer from the ordinary pre-game Fire now result, or None when the event is not in it."""
    for pick in payload.get("picks") or []:
        if pick["event_id"] == event_id:
            out.update({"picked": True, "pick": pick, "picks": [p for p in payload["picks"]
                                                                if p["event_id"] == event_id],
                        "reason": pick["reason"], "code": "pick", "game": pick["game"], "sport": pick.get("sport")})
            return out
    for ticket in payload.get("recorded") or []:
        if ticket["event_id"] == event_id:
            out.update({"picked": True, "recorded": True, "pick": ticket, "picks": [ticket], "code": "recorded",
                        "reason": "Already on this hound's record.", "game": ticket.get("game")})
            return out
    for game in payload.get("games") or []:
        if game["event_id"] == event_id:
            misses = [m for m in payload.get("closest_misses") or [] if m["event_id"] == event_id]
            marks = [m for m in game["markets"] if m["status"] == "miss"]
            marks.sort(key=lambda m: fire.MISS_TIER.get(m["code"], 9))
            first = marks[0] if marks else {"code": "rule_not_met", "why": "The rule did not fire."}
            out.update({"code": first["code"], "reason": first["why"], "game": game["game"],
                        "misses": marks, "closest_misses": misses})
            return out
    return None


def _live_label(game, market: str) -> str:
    return fire.market_label(market, game.sport)


def _live_pick(game, market: str, cand: dict, reason: str, commence: datetime, now: datetime) -> dict:
    return {"event_id": game.event_id, "game": fire._game_text(game), "sport": game.sport, "market": market,
            "market_label": _live_label(game, market), "side": cand["side"], "selection": cand["selection"],
            "line": cand["line"], "price_average": cand["price"], "price_best": cand["best_price"],
            "best_book": cand["best_book"], "n_books": cand["n_books"], "start_utc": E._iso(commence),
            "board_observed_utc": cand["board_observed_utc"],
            "board_age_minutes": round((now - E._utc(cand["board_observed_utc"])).total_seconds() / 60.0, 1),
            "live": True, "in_play": True, "reason": reason}


def _evaluate_live(dog: common.Dog, game, now: datetime, out: dict, slate_for: Optional[Callable]) -> dict:
    spec = dog.spec
    commence = game.commence
    out.update({"game": fire._game_text(game), "sport": game.sport, "live": True,
                "league_title": getattr(game, "league_title", None)})
    wanted = set(spec["sports"]) if not user_spec.is_v2(spec) else {s for r in spec["rules"] for s in r["sports"]}
    if game.sport not in wanted:
        out.update({"code": "not_eligible", "reason": LIVE_CODES["not_eligible"]})
        return out
    if now > commence + timedelta(hours=catalog.live_window_hours(game.sport)):
        out.update({"code": "game_over", "reason": LIVE_CODES["game_over"]})
        return out
    markets = list(spec["markets"])
    live_stamps = {}
    for market in markets:
        stamps = [t for t in game.captures.get(market, {}) if t >= commence and t <= now]
        if stamps:
            live_stamps[market] = max(stamps)
    if not live_stamps:
        out.update({"code": "no_live_price", "reason": LIVE_CODES["no_live_price"]})
        return out
    fresh = {m: t for m, t in live_stamps.items() if now - t <= timedelta(minutes=LIVE_FRESH_MINUTES)}
    if not fresh:
        out.update({"code": "live_price_too_old", "reason": LIVE_CODES["live_price_too_old"]})
        return out
    picks, misses = [], []
    if user_spec.is_v2(spec):
        from src.hounds import user_engine_v2 as V2
        from src.hounds import user_rules as R
        date = E.slate_date_of(commence)
        facts = None
        if game.sport in ("MLB", "NFL"):
            from src.hounds.interact import ask_eval
            facts = (slate_for or ask_eval.default_slate)(date, False).facts
        seed = dog.hound.get("spec_hash") or user_spec.spec_hash(spec)
        skipped: Counter = Counter()
        found = []
        for i, rule in enumerate(spec["rules"]):
            if game.sport not in rule["sports"]:
                continue
            for market in rule["markets"]:
                if R.market_kind(market) == "prop" or market not in fresh:
                    continue
                for cand in V2.rule_candidates(rule, i, spec, game, market, fresh[market], fresh[market], commence,
                                               date, seed, facts, None, skipped):
                    found.append((V2._sort_key(spec["rank_by"], cand, fresh[market], game.event_id, market, i),
                                  market, cand))
        found.sort(key=lambda item: item[0])
        # One side per game (src/hounds/one_side.py): the live answer shows what the engine would do.
        found = one_side.keep_first(found, lambda it: (game.event_id, it[1], it[2]["side"], it[2].get("player"),
                                                           it[2].get("line")))
        from src.hounds.interact import ask_eval
        for _k, market, cand in found:
            picks.append(_live_pick(game, market, cand, ask_eval._reason(spec, cand, market, date, E._iso(commence)),
                                    commence, now))
        for code in V2_ORDER:
            if skipped.get(code):
                fcode = ask_eval.V2_CODE[code]
                misses.append({"code": fcode, "why": ask_eval.V2_WHY[code], "market": "", "status": "miss"})
                break
        if not picks and not misses:
            misses.append({"code": "rule_not_met", "why": "The rule did not fire on the live price.",
                           "market": "", "status": "miss"})
    else:
        hound = dog.hound
        for market in markets:
            if market not in fresh:
                continue
            cand, code = E.evaluate(spec, game, market, fresh[market], commence)
            if cand is None:
                info = fire._explain(spec, game, market, fresh[market], code)
                misses.append({"code": code, "why": info["why"], "market": market, "status": "miss",
                               "gap": info.get("gap")})
                continue
            row = fire.pick_row(hound, game, market, cand, fresh[market], now, fresh[market], commence)
            picks.append(_live_pick(game, market, cand, row["reason"], commence, now))
    picks = one_side.keep_first(picks, lambda p: (p["event_id"], p["market"], p["side"], None, p.get("line")))
    if picks:
        out.update({"picked": True, "pick": picks[0], "picks": picks, "code": "pick", "reason": picks[0]["reason"]})
    else:
        misses.sort(key=lambda m: fire.MISS_TIER.get(m["code"], 9))
        first = misses[0]
        out.update({"code": first["code"], "reason": first["why"], "misses": misses})
    return out


def answer(dog: common.Dog, event_id: str, *, now: Optional[datetime] = None, rows_for: Optional[Callable] = None,
           slate_for: Optional[Callable] = None, ledger: Optional[str] = None, other_live=None,
           **fire_kw) -> dict:
    """The per-event Fire now answer. ``rows_for(date, sports)`` and ``slate_for(date, with_props)`` are the
    injection points (tests pass fixtures; production reads the stores)."""
    now = now or common.now_utc()
    out = _base(dog, event_id, now)
    kw = dict(fire_kw)
    if dog.kind == common.KIND_USER:
        # each firing path takes only its own seams (a house dog takes none of these)
        kw.update(ledger=ledger, other_live=other_live)
        if user_spec.is_v2(dog.spec):
            if slate_for is not None:
                kw["slate_for"] = slate_for
        elif rows_for is not None:
            kw["rows_for"] = rows_for
    payload = fire.fire(dog, now=now, **kw)
    if _from_payload(payload, event_id, out) is not None:
        return out
    if dog.kind != common.KIND_USER:
        out.update({"code": "unknown_event", "reason": LIVE_CODES["unknown_event"]})
        return out
    sports = sorted(set(dog.spec["sports"]) if not user_spec.is_v2(dog.spec)
                    else {s for r in dog.spec["rules"] for s in r["sports"]})
    game = _live_game(sports, event_id, now, rows_for)
    if game is None or game.commence is None:
        out.update({"code": "unknown_event", "reason": LIVE_CODES["unknown_event"]})
        return out
    if game.sport not in sports:
        out.update({"code": "not_eligible", "reason": LIVE_CODES["not_eligible"], "game": fire._game_text(game),
                    "sport": game.sport})
        return out
    if game.commence > now:
        out.update({"code": "too_far_ahead", "reason": LIVE_CODES["too_far_ahead"],
                    "game": fire._game_text(game), "sport": game.sport})
        return out
    return _evaluate_live(dog, game, now, out, slate_for)
