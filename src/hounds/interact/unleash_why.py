"""Why Unleash took what it took, game by game: the per-reason summary under the Unleash button.

THE STORY. On 2026-10-21 a member tapped Unleash on a hound and read "Checked 60 games - Nothing to lock yet", which
says nothing about WHY. A person who taps a button has to be able to see, for every game on the board, whether it was
taken, already held, or passed over and for which one reason. This module classifies each game of today's slate into
exactly one bucket, by asking the SAME engine code the bets go through (``user_engine_v2.hound_candidates`` /
``user_engine.evaluate``) with a fresh counter per game, so the summary can never disagree with the bets.

ONE REASON PER GAME. A game fails several tests at once (wrong price AND too few books). The one shown is the test the
game got FURTHEST through (``_DEPTH``): "the rule was not met" beats "price outside the band" beats "too few books" beats
"no board". That is the honest answer to "how close was it".

THE GEMATRIA STYLE IS BROKEN DOWN TOO (2026-10-22). Until then ``game_code`` answered "rule_not_met" for every game of a Gematria hound
(the house engine's own verdict was not asked), so a member read "Checked 60 games: 60 rule not met". The Gematria engine has its own
reasons and each is a bucket here: ``no_history`` / ``no_facts`` / ``thin_data`` / ``uneven_search`` (it could not compare the sides),
``no_numbers`` (it could, and the numbers did not line up), ``too_few_books`` (no moneyline board with enough books), the price buckets.

Nothing here writes a bet, reads a store, or talks to a book.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Mapping, Optional

from src.hounds import user_engine as E
from src.hounds import user_spec

# Furthest-through first. A higher number means the game passed more tests before it failed.
_DEPTH = {
    "conditions_not_met": 90, "rule_has_no_side": 90, "rule_not_met": 90,
    "outside_line_range": 80, "outside_price_band": 70, "price_cap": 60, "too_few_books": 50,
    "live_price_too_old": 45, "board_too_old": 40, "no_live_board": 30, "no_board_at_lock": 20, "game_started": 10,
}

# code -> (bucket, plain words). The bucket is what the page counts; several codes share one.
_BUCKET = {
    "conditions_not_met": "rule_not_met", "rule_has_no_side": "rule_not_met", "rule_not_met": "rule_not_met",
    "outside_line_range": "rule_not_met",
    "outside_price_band": "price_band", "price_cap": "price_cap", "too_few_books": "too_few_books",
    "live_price_too_old": "live_price_too_old", "board_too_old": "board_too_old",
    "no_live_board": "no_live_board", "no_board_at_lock": "no_board", "game_started": "started",
}

# Display order = the order a reader would ask the questions in.
BUCKETS = (
    ("on_record", "already on its record"),
    ("started", "already started"),
    ("not_in_sports", "not in its sports"),
    ("waits_lock", "waiting for its check time (no fresh board yet)"),
    ("no_board", "no board saved for it"),
    ("no_history", "no stored results for its sport"),
    ("no_facts", "teams it holds no facts for"),
    ("thin_data", "too few counts to compare"),
    ("uneven_search", "sides too uneven to compare"),
    ("board_too_old", "board too old"),
    ("no_live_board", "no live price yet"),
    ("live_price_too_old", "live price too old"),
    ("too_few_books", "too few books"),
    ("price_cap", "priced -200 or worse (never bet)"),
    ("price_band", "price outside its band"),
    ("no_numbers", "numbers didn't line up"),
    ("rule_not_met", "rule not met"),
    ("over_limit", "over its daily limit"),
    ("one_side", "other side already held"),
    ("fit_not_taken", "fit but not taken"),
)
_LABEL = dict(BUCKETS)


def game_code(hound: Mapping, spec: Mapping, game, now: datetime, date: str, facts, index) -> str:
    """The engine's verdict for ONE game right now: ``"fit"`` or the furthest-through reason code."""
    wanted = {s for r in spec["rules"] for s in r["sports"]} if user_spec.is_v2(spec) else set(spec["sports"])
    if game.sport not in wanted:
        return "not_in_sports"
    if user_spec.is_gematria(spec):
        return "rule_not_met"             # the house engine's own verdict is not broken down per game
    probe = {"id": hound["id"], "spec": spec, "created_at": hound.get("created_at")}
    skipped: Counter = Counter()
    if user_spec.is_v2(spec):
        from src.hounds import user_engine_v2 as v2
        cands = v2.hound_candidates(probe, spec, {game.event_id: game}, facts, date, mode="live", clock=lambda: now,
                                    seen_ids=set(), game_pk_index=index, skipped=skipped, considered={}, ahead=True)
        if cands:
            return "fit"
    else:
        commence = game.commence
        lock = commence - timedelta(minutes=spec["lock_minutes"])
        born = E._utc(hound.get("created_at"))
        for market in spec["markets"]:
            # the engine's own rule: a hound that existed at the lock is priced at the lock, one born after it is priced now
            eval_game, as_of = game, (now if now < lock or (born is not None and born > lock) else lock)
            if now >= commence:
                eval_game, code = E.live_game(game, spec, now)
                if eval_game is None:
                    skipped[code] += 1
                    continue
                as_of = now
            cand, reason = E.evaluate(spec, eval_game, market, as_of, commence)
            if cand is not None:
                return "fit"
            skipped[reason] += 1
    codes = [c for c in skipped if c in _DEPTH]
    return max(codes, key=lambda c: _DEPTH[c]) if codes else "rule_not_met"


#: the Gematria engine's decision codes -> the buckets above
_GEM_BUCKET = {"no_history": "no_history", "no_facts": "no_facts", "thin_data": "thin_data", "uneven_search": "uneven_search",
               "no_board": "too_few_books", "small_margin": "no_numbers", "outside_band": "price_band"}


def gematria_bucket(weigher, event_id: str, game, spec: Mapping, now: datetime) -> str:
    """The bucket of ONE game for a Gematria hound: ``"fit"`` or one of ``_GEM_BUCKET`` (asked of the house engine itself)."""
    if game.commence is None or now >= game.commence:
        return "started"
    lock = game.commence - timedelta(minutes=spec["lock_minutes"])
    got = weigher.weigh(event_id, as_of=now if now < lock else None)
    if got is None:
        return "no_board"
    verdict = got[2].verdict
    if verdict.is_bet:
        return "fit"
    if verdict.code == "outside_band" and isinstance(verdict.price, int) and verdict.price <= -200:
        return "price_cap"
    return _GEM_BUCKET.get(verdict.code, "rule_not_met")


def band_text(spec: Mapping) -> str:
    """The price band in words, when every rule shares one (else a generic phrase)."""
    bands = {(r["price_min"], r["price_max"]) for r in spec["rules"]} if user_spec.is_v2(spec) \
        else {(spec["price_min"], spec["price_max"])}
    if len(bands) != 1:
        return "price outside its band"
    lo, hi = next(iter(bands))
    fmt = lambda p: f"{p:+d}"        # noqa: E731
    return f"price outside {fmt(lo)} to {fmt(hi)}"


def summarise(spec: Mapping, games: Mapping, hound: Mapping, now: datetime, date: str, *, facts, index,
              on_record: set, placed_events: set, per_day_taken: int) -> dict:
    """{checked, placed, counts: [{code, label, count}], text, by_event}.

    ``on_record``: event ids the hound already holds a ticket on today; ``placed_events``: the subset placed by this tap."""
    counts: Counter = Counter()
    by_event: dict = {}
    full = per_day_taken >= spec["max_bets_per_day"]
    gem = None
    if user_spec.is_gematria(spec):
        from src.hounds import user_gematria
        gem = user_gematria.Weigher(games)
    for eid, game in games.items():
        if eid in on_record:
            bucket = "on_record"
        elif gem is not None:
            code = gematria_bucket(gem, eid, game, spec, now)
            bucket = ("over_limit" if full else "one_side") if code == "fit" else code
        else:
            code = game_code(hound, spec, game, now, date, facts, index)
            if code == "fit":
                bucket = "over_limit" if full else "one_side"
            elif code == "not_in_sports":
                bucket = code
            else:
                bucket = _BUCKET.get(code, "rule_not_met")
                lock = game.commence - timedelta(minutes=spec["lock_minutes"])
                if bucket in ("no_board", "board_too_old") and now < lock:
                    # Far-off games are captured every few hours, so no board is fresh enough to bet on yet. The runner
                    # checks them at their lock on the board standing then; this is waiting, not a rejection.
                    bucket = "waits_lock"
        counts[bucket] += 1
        by_event[eid] = bucket
    labels = dict(_LABEL, price_band=band_text(spec))
    rows = [{"code": code, "label": labels[code], "count": counts[code]} for code, _ in BUCKETS if counts[code]]
    placed = len(placed_events)
    n = len(games)
    parts = " · ".join(f"{r['count']} {r['label']}" for r in rows)
    if n == 0:
        text = "No games on today's board in its sports yet"
    else:
        text = f"{n} checked" + (f": {parts}" if parts else "")
    return {"checked": n, "placed": placed, "counts": rows, "text": text, "by_event": by_event}


def next_check(spec: Mapping, games: Mapping, now: datetime, held: set) -> Optional[dict]:
    """The next game the runner WILL check: the earliest lock still ahead among games the hound does not hold."""
    best = None
    for eid, game in games.items():
        if eid in held or game.commence is None:
            continue
        lock = game.commence - timedelta(minutes=spec["lock_minutes"])
        if lock > now and (best is None or (lock, eid) < (best[0], best[1])):
            best = (lock, eid, game)
    if best is None:
        return None
    lock, eid, game = best
    return {"event_id": eid, "game": f"{game.away_team} @ {game.home_team}", "sport": game.sport,
            "when_utc": E._iso(lock), "start_utc": E._iso(game.commence),
            "what": f"its rule is checked {spec['lock_minutes']} minutes before the start"}
