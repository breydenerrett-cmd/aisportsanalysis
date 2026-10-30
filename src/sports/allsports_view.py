"""What is on right now, in every sport the program has prices for: the body of GET /sports/now.

READ ONLY, FROM STORED ROWS. Nothing here calls The Odds API (or any API); it reads the multibook store the
capture writes (src/pipeline/allsports_capture.py for the new families, the existing captures for MLB and
NFL) and, for an optional score, the all-sports scores store. A request therefore costs a file read, which
is remembered for `TTL_SECONDS` so a page and a chat panel opened together read the store once.

LIVE MEANS A RECENT IN-PLAY SNAPSHOT
------------------------------------
An event is live when its start has passed, it is still inside its family's live window, AND the newest
stored snapshot of it was taken after the start and no more than `LIVE_FRESH_MINUTES` ago. A game that
started three hours ago and was last priced before the start is NOT shown as live: the page would be
claiming a live price the program does not have.

EVERY EVENT CARRIES ITS BEST PRICES
-----------------------------------
`best_price_home` / `best_price_away` are the best single quote (highest payout) across the books on the
event's NEWEST snapshot, and `observed_utc` says when that was. A three-way event also carries
`best_price_draw`. They are what a book showed, not a recommendation.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping, Optional

from src.core import odds as odds_math
from src.sports import catalog, live_feed, live_state

TTL_SECONDS = 30.0
LIVE_FRESH_MINUTES = 90
UPCOMING_HOURS = 24
LOOKBACK_HOURS = 30            # how far back observations are read: a pre-game capture leads by at most ~1.1 days

_cache: dict = {}
_lock = threading.Lock()


def _parse(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _best(prices: Iterable) -> Optional[int]:
    best = None
    for p in prices:
        if isinstance(p, bool) or not isinstance(p, (int, float)) or abs(p) < 100:
            continue
        if best is None or odds_math.american_to_decimal(p) > odds_math.american_to_decimal(best):
            best = p
    return None if best is None else int(best)


def read_recent_rows(now: datetime, *, path=None, lookback_hours: int = LOOKBACK_HOURS) -> Iterable[Mapping]:
    """Moneyline rows of EVERY catalog family observed in the last `lookback_hours`, in one pass over the
    store (each family's text prefilter and window), as a generator."""
    from src.pipeline import snapshots
    since = (now - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d")
    wanted = {catalog.row_sport(c): since for c in catalog.family_codes()}
    path = path or snapshots.DEFAULT_MULTIBOOK_PATH
    for row in snapshots.iter_multibook_multi(path, since_by_sport=wanted):
        if row.get("market") in (None, "h2h"):
            yield row


def _family_of_row(row: Mapping) -> Optional[str]:
    return catalog.code_of_row_sport(row.get("sport") or "mlb")


def build_events(rows: Iterable[Mapping], now: datetime) -> dict:
    """{event_id: event dict} from moneyline rows: each event's NEWEST snapshot, its best prices, and its
    family. Rows with no event id, start or parseable observation time are skipped."""
    newest: dict = {}                    # event_id -> (observed, [rows at that instant], first row)
    for row in rows:
        if row.get("market") not in (None, "h2h"):
            continue                                    # spreads, totals: not the moneyline board
        event_id, start = row.get("event_id"), _parse(row.get("commence_time"))
        observed = _parse(row.get("observed_utc"))
        code = _family_of_row(row)
        if not event_id or start is None or observed is None or code is None or observed > now:
            continue
        held = newest.get(event_id)
        if held is None or observed > held[0]:
            newest[event_id] = (observed, [row], row)
        elif observed == held[0]:
            held[1].append(row)
            newest[event_id] = (held[0], held[1], row)
    out = {}
    for event_id, (observed, rows_at, last) in newest.items():
        start = _parse(last.get("commence_time"))
        code = _family_of_row(last)
        window = timedelta(hours=catalog.live_window_hours(code))
        in_window = start <= now < start + window
        fresh = now - observed <= timedelta(minutes=LIVE_FRESH_MINUTES)
        in_play = bool(in_window and observed >= start and fresh)
        league = last.get("league") or code
        out[event_id] = {
            "event_id": event_id, "family": code, "league": last.get("league"),
            "league_title": last.get("league_title") or catalog.label(code),
            "home": last.get("home_team"), "away": last.get("away_team"), "start_utc": _iso(start),
            "in_play": in_play, "best_price_home": _best(r.get("home_price") for r in rows_at),
            "best_price_away": _best(r.get("away_price") for r in rows_at),
            "best_price_draw": _best(r.get("draw_price") for r in rows_at),
            "n_books": len({r.get("book") for r in rows_at if r.get("book")}),
            "observed_utc": _iso(observed), "_start": start, "_in_window": in_window, "_league": league,
        }
    return out


def _with_score(event: dict, scores_index: Optional[Mapping], now: datetime) -> dict:
    """Attach `score` when the scores store has a reading for this event no older than the live window."""
    row = (scores_index or {}).get(event["event_id"])
    if row is None or row.get("home_score") is None or row.get("away_score") is None:
        return event
    if row.get("source"):
        return event        # a free-feed result (tennis, MMA) holds a 1-0 match-win marker, not a live score
    stamp = _parse(row.get("observed_utc"))
    if stamp is None or now - stamp > timedelta(hours=catalog.live_window_hours(event["family"]) + 1):
        return event
    done = bool(row.get("completed"))
    event["score"] = {"home": row["home_score"], "away": row["away_score"],
                      "detail": "Final" if done else "Live", "completed": done, "as_of": row.get("observed_utc")}
    return event


def _apply_feed(events: Mapping, now: datetime, answers: Optional[Mapping] = None) -> None:
    """Lay the live ESPN feed (src/sports/live_feed.py) over the events it covers, in place.

    The odds snapshot says a game is "live" only because it was priced after the start; it knows nothing about the
    game. The feed does. A fresh matched answer decides: live keeps the game on the board WITH its score, period and
    clock; final keeps it as a Final card for the rest of its window; postponed or cancelled takes it off the live list.
    No fresh answer for a covered game means a "Score delayed" marker, never a stored score from hours ago.
    `answers` is the injection point (tests); production asks the feed's cache."""
    if answers is None:
        answers = live_feed.answers_for(events.values(), now)
    for event_id, ans in answers.items():
        event = events.get(event_id)
        if event is None:
            continue
        state = ans.get("state")
        if state is None:
            event["_feed_unknown"] = True
            if event["in_play"] and ans.get("delayed"):
                event["score"] = {"home": None, "away": None, "detail": "Score delayed", "completed": False,
                                  "delayed": True, "as_of": None, "source": "espn"}
            continue
        event["_feed_known"] = True
        if state == "live":
            event["in_play"] = True
            event["score"] = ans["score"]
        elif state == "final":
            if event["_in_window"]:
                event["in_play"] = True              # shown on the board as a Final card until its window closes
                event["score"] = ans["score"]
            else:
                event["in_play"] = False
        elif state in ("postponed", "cancelled"):
            event["in_play"] = False
            event["_off"] = True
        elif state == "upcoming" and event["in_play"] and event["_in_window"]:
            event["in_play"] = False                 # priced after its listed start but the scoreboard says not started


def _apply_live_state(events: Mapping, now: datetime, states: Optional[Mapping] = None) -> None:
    """Put the one-line live state (src/sports/live_state: "2nd · 8:14 · SOG 18-11 · PP WSH", "Set 2 · 3-2 · Joint serving · up
    a break") on each NHL or tennis game that is in play, as `event["live_state"] = {line, sport, as_of}`.

    The lookup is the later phases' own (`live_state.state_for`): both names in the odds feed's orientation, exactly one game, the
    180 second stale guard. A game it cannot place gets NO key, and a failure here never touches the rest of the board; the page
    prints the line when it is there and nothing when it is not. `states` is the injection point (tests): {event_id: state dict}."""
    for event_id, event in events.items():
        if event.get("family") not in live_state.SPORTS or not event.get("in_play") or event.get("_off"):
            continue
        try:
            found = states.get(event_id) if states is not None else live_state.state_for(
                event["family"], event.get("home"), event.get("away"), event["_start"], now=now)
            view = live_state.public_view(found)
        except Exception:  # noqa: BLE001 -- the line is a nicety; the board stands without it
            continue
        if view:
            event["live_state"] = view


def _public(event: dict) -> dict:
    return {k: v for k, v in event.items() if not k.startswith("_") and k != "family"
            and not (k == "best_price_draw" and v is None)}


def sports_now(now: Optional[datetime] = None, *, rows: Optional[Iterable[Mapping]] = None,
               scores_index: Optional[Mapping] = None, path=None, feed_answers: Optional[Mapping] = None,
               live_states: Optional[Mapping] = None) -> dict:
    """GET /sports/now: {generated_utc, families: [{code, label, live, upcoming_24h, next_start_utc}]}.

    Families with nothing live and nothing upcoming are left out; the rest follow the catalog order, so MLB
    and NFL lead and the order never depends on which sport happens to be busy. `rows` and `scores_index`
    are the injection points (tests pass fixture rows; production reads the stores)."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    from_store = rows is None
    if rows is None:
        rows = read_recent_rows(now, path=path)
    if scores_index is None:
        try:
            from src.pipeline import allsports_scores
            scores_index = allsports_scores.load_index()
        except Exception:  # noqa: BLE001 -- a score is a nicety; the board stands without it
            scores_index = {}
    events = build_events(rows, now)
    if from_store:
        _remember_events(events, now)
    _apply_feed(events, now, feed_answers)
    _apply_live_state(events, now, live_states)
    horizon = now + timedelta(hours=UPCOMING_HOURS)
    families = []
    for code in catalog.family_codes():
        live, upcoming, future = [], [], []
        for event in events.values():
            if event["family"] != code:
                continue
            start = event["_start"]
            if event.get("_off"):
                continue
            if event["in_play"]:
                live.append(event if event.get("score") or event.get("_feed_known") or event.get("_feed_unknown")
                            else _with_score(event, scores_index, now))
            elif start > now:
                future.append(start)
                if start <= horizon:
                    upcoming.append(event)
        if not live and not upcoming and not future:
            continue
        live.sort(key=lambda e: (e["_start"], e["event_id"]))
        upcoming.sort(key=lambda e: (e["_start"], e["event_id"]))
        families.append({
            "code": code, "label": catalog.label(code),
            "live": [_public(e) for e in live], "upcoming_24h": [_public(e) for e in upcoming],
            "next_start_utc": _iso(min(future)) if future else None,
        })
    observed = [e["observed_utc"] for f in families for e in f["live"] + f["upcoming_24h"] if e.get("observed_utc")]
    fed = live_feed.last_fetched(now) if feed_answers is None else _newest_as_of(feed_answers)
    delayed = any(e.get("score", {}).get("delayed") for f in families for e in f["live"])
    return {"generated_utc": _iso(now), "families": families, "paper_only": True,
            "prices_observed_utc": max(observed) if observed else None,
            "scores": {"source": "espn", "updated_utc": _iso(fed) if fed else None,
                       "age_seconds": int((now - fed).total_seconds()) if fed else None,
                       "stale_after_seconds": int(live_feed.STALE_AFTER_SECONDS), "delayed": bool(delayed)}}


def _newest_as_of(answers: Mapping) -> Optional[datetime]:
    stamps = [_parse((a.get("score") or {}).get("as_of")) for a in answers.values()]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


_events_memo: dict = {}


def _remember_events(events: Mapping, now: datetime) -> None:
    with _lock:
        _events_memo["at"], _events_memo["events"] = time.monotonic(), events


def current_events() -> list:
    """The board's internal events for the live-feed loop to decide which leagues to read: the ones the last
    store read built (at most `2 * TTL_SECONDS` old), else a fresh read."""
    with _lock:
        at, events = _events_memo.get("at"), _events_memo.get("events")
    if events is not None and time.monotonic() - at < 2 * TTL_SECONDS:
        return list(events.values())
    now = datetime.now(timezone.utc)
    built = build_events(read_recent_rows(now), now)
    _remember_events(built, now)
    return list(built.values())


def cached_sports_now(now: Optional[datetime] = None) -> dict:
    """`sports_now` remembered for `TTL_SECONDS` (production reads only; tests call `sports_now`)."""
    key = "now"
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL_SECONDS:
            return hit[1]
    payload = sports_now(now)
    with _lock:
        _cache[key] = (time.monotonic(), payload)
    return payload


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _events_memo.clear()


def live_elsewhere(own_sports: Iterable[str], now: Optional[datetime] = None, *,
                   payload: Optional[Mapping] = None) -> dict:
    """Live games in families OTHER than `own_sports`: {"games": N, "families": [{code, label, games}],
    "text": "Live now in other sports: 5 games (tennis, cricket)."} (text is "" when none). `payload` is a
    ready `sports_now` body (tests); the default reads the cached one."""
    own = {str(s).upper() for s in own_sports}
    body = payload if payload is not None else cached_sports_now(now)
    families = [{"code": f["code"], "label": f["label"], "games": len(f["live"])}
                for f in body.get("families", []) if f["code"] not in own and f["live"]]
    games = sum(f["games"] for f in families)
    if not games:
        return {"games": 0, "families": [], "text": ""}
    names = ", ".join(f["label"].lower() for f in sorted(families, key=lambda f: -f["games"])[:4])
    more = len(families) - 4
    names += f" and {more} more" if more > 0 else ""
    return {"games": games, "families": families,
            "text": f"Live now in other sports: {games} {'game' if games == 1 else 'games'} ({names})."}
