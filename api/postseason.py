"""GET /postseason -- the public MLB postseason page's data.

PUBLIC, NO AUTH, mounted beside /meta in api/app.py and never in the paid
group: this is the free top-of-funnel page, so a signed-out visitor has to
be able to read it. It carries no pick, no price and nothing from a
customer's account; every number is a model estimate with the caveat the
builder attaches (src/report/postseason_page.py).

SAME DIVISION OF LABOUR AS THE OTHER ROUTES: this file only wires inputs to
the pure builder and caches the answer. The one thing it adds beyond reading
the stores on disk is a bounded top-up from the MLB schedule feed:

  * results: the daily job ingests finals once a day, so an evening game is
    not in the store until the next morning. A visitor looking at a series
    after tonight's game should not see last night's score, so the postseason
    dates the store has not covered are fetched and merged in memory (never
    written to disk).
  * standings: the field is seeded from the final regular-season standings.
    When the store on disk has no snapshot from after the season ended, the
    final table is fetched once and held in memory.
  * announced starters: the next few days' schedule, which is where
    announced probables live. Without it every future starter is TBD.
  * fresh pitcher logs: the stored pitcher logs can be days old, and a
    starter's numbers count in an estimate only when they are current. For each
    identified pitcher whose stored numbers are not current the builder asks
    for his game log once, via `mlb.fetch_pitcher_game_log` (the very function
    the daily job stores from, so the rows have the stored shape). At most
    `MAX_FRESH_PITCHER_FETCHES` new requests per build; a pitcher past the cap
    is simply not current. Answers are remembered per (pitcher, baseball date)
    for the life of the process; a failed request never fails the build.

All four are best-effort. A failed fetch leaves the stores as they are and the
builder's own staleness guard decides whether the page can still be called
current.

NEVER A 500. The builder returns an honest-absence payload for a field it
cannot determine; anything it raises is caught here and answered with the
same shape. A "not available" answer is never cached as the page: it is raised
inside the cached build, so the last good page keeps being served (flagged
stale) and the unavailable payload, with its plain reason, goes out only when
there is no good page at all. Cached with the stale-while-revalidate helper the other routes
use (src/appstate/freshness.py): one rebuild in flight, last-good served
flagged stale, and a rebuild that just failed is not retried for 30 seconds
so a persistent fault cannot turn every request into a slow build.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from typing import Optional

from fastapi import APIRouter, Header

from api.auth import optional_user_id
from src.analysis import postseason_config as pc
from src.appstate import activation, freshness
from src.pipeline import history
from src.pipeline import standings as standings_store
from src.providers import mlb
from src.report import postseason_page

router = APIRouter()

CACHE_KEY = ("postseason",)

# A rebuild prices a couple of dozen matchups and makes a handful of schedule
# calls; five minutes is fresh enough for a page that changes once a game.
POSTSEASON_CACHE_TTL_S = 300.0
# Past the TTL the last good page is served at once, flagged stale, while one
# background rebuild runs. Bounded: past this a caller waits for the rebuild.
POSTSEASON_STALE_WINDOW_S = 1800.0
# After a failed build, do not start another for this long.
FAILURE_BACKOFF_S = 30.0
# How many days of schedule to look ahead for announced starters (from the day
# before the baseball date; see `postseason_page.upcoming_games`). The schedule
# names starters well ahead of a game, and a starter it has already named must
# not be replaced by a projected one: 7 covers a whole Division Series.
SCHEDULE_DAYS_AHEAD = 7
# Never fetch more than this many NEW result dates in one build. Dates that
# are over (before today, nothing pending) are remembered for the life of the
# process, so a steady-state build fetches today only. The cap covers a cold
# start late in October against a store that stopped in September.
MAX_TOPUP_DATES = 45
# Never make more than this many NEW pitcher game-log requests in one build.
MAX_FRESH_PITCHER_FETCHES = 24

_cache = freshness.SingleFlightTTLCache(
    ttl_s=POSTSEASON_CACHE_TTL_S, stale_while_revalidate_s=POSTSEASON_STALE_WINDOW_S)
_failure_lock = threading.Lock()
_last_failure_at = None
# The builder's own "not available" payload from the most recent failed build,
# so the route can answer with its plain reason when there is no good page to
# fall back on. Cleared by any build that does not end that way.
_last_unavailable = None
_memo_lock = threading.Lock()
_settled_days: dict = {}
_final_standings = None
# {(pitcher_id, baseball_date): rows}: a pitcher's game log, fetched once per
# baseball date for the life of the process (entries of other dates are dropped
# as the date moves on).
_fresh_logs_memo: dict = {}

ABSENT_REASON = ("The postseason page could not be built right now. "
                 "Check back in a few minutes.")


class BuildUnavailable(Exception):
    """The builder answered `available: false`. Raised inside the cached build
    so a "not available" answer is never stored as the page: the cache serves
    the last good page (flagged stale) instead."""


def reset_cache_for_tests() -> None:
    global _last_failure_at, _final_standings, _last_unavailable
    _cache._entries.clear()
    _cache._locks.clear()
    _cache._refreshing.clear()
    with _failure_lock:
        _last_failure_at = None
        _last_unavailable = None
    with _memo_lock:
        _settled_days.clear()
        _final_standings = None
        _fresh_logs_memo.clear()


# -- inputs ---------------------------------------------------------------

def _day_results(day: str, today: str) -> dict:
    """One date's results from the feed. A date before today with nothing
    pending can never change again, so it is fetched once per process."""
    with _memo_lock:
        hit = _settled_days.get(day)
    if hit is not None:
        return hit
    result = mlb.fetch_results(day)
    if day < today and not result["summary"]["pending"]:
        with _memo_lock:
            _settled_days[day] = result
    return result


def _topup_results(store: dict, manifest: dict, now: datetime):
    """(store, results_through): the on-disk results plus every date after
    the last one the store fully covers, fetched from the schedule feed and
    merged IN MEMORY. Returns copies; nothing is written to disk.

    The store in a deployed image is whatever the repository held when the
    image was built, which can be days behind (production is deployed by
    hand). So the top-up starts the day after the store's own coverage ends,
    not at the first postseason date: the last regular-season games feed the
    team numbers too."""
    store = dict(store)
    manifest = dict(manifest)
    # The baseball date, not the UTC one: from 8 pm Eastern the UTC date is
    # already tomorrow, and the schedule files tonight's games under today.
    today = postseason_page.baseball_date(now)
    first = pc.CALENDAR["wild_card"]["start"]
    decisive = sorted(mlb.DECISIVE_GAME_TYPES)
    wanted = set(postseason_page.ROUND_BY_GAME_TYPE) | {"R"}
    if today >= first:
        covered = postseason_page.results_through_from_manifest(manifest, mlb.DECISIVE_GAME_TYPES)
        start = first if covered is None else (
            datetime.fromisoformat(covered).date() + timedelta(days=1)).isoformat()
        fetched = 0
        for day in mlb.iter_dates(start, today):
            with _memo_lock:
                known = day in _settled_days
            if not known:
                if fetched >= MAX_TOPUP_DATES:
                    break
                fetched += 1
            try:
                result = _day_results(day, today)
            except Exception:  # noqa: BLE001 -- best effort, see module docstring
                # A date that could not be read ends the top-up: coverage must
                # not claim a later date while an earlier one is missing.
                break
            for game in result["final"]:
                if game.get("game_type") in wanted:
                    store[str(game["game_pk"])] = {c: game.get(c) for c in history.RESULT_COLUMNS}
            manifest[result["date"]] = {"pending": result["summary"]["pending"],
                                        "game_types": decisive}
    through = postseason_page.results_through_from_manifest(manifest, mlb.DECISIVE_GAME_TYPES)
    return store, through


def _topup_standings(stored: dict, now: datetime) -> dict:
    """The standings on disk, plus the final regular-season snapshot from the
    feed when the store does not hold one. In memory only.

    Without a final snapshot the builder cannot seed the field and the whole
    page is "not available". A deployed image carries the repository's copy
    of the store, which stopped before the season ended."""
    global _final_standings

    def fetch_once(season, date=None):
        # The finished season's table never changes: one request per process.
        global _final_standings
        with _memo_lock:
            memo = _final_standings
        if memo is None:
            memo = mlb.fetch_standings(season, date=date)
            if memo:
                with _memo_lock:
                    _final_standings = memo
        return memo

    return postseason_page.with_final_standings(
        stored, now, fetch_once, mlb.parse_standings)


def _fresh_fetcher(now: datetime):
    """The builder's `fresh_pitcher_logs` for one build: this season's game log
    of one pitcher from the feed (`mlb.fetch_pitcher_game_log`, the ingest's
    own normalised rows), memoised per (pitcher, baseball date) and capped at
    `MAX_FRESH_PITCHER_FETCHES` new requests. See
    `postseason_page.capped_pitcher_fetcher`."""
    day = postseason_page.baseball_date(now)
    season = day[:4]
    return postseason_page.capped_pitcher_fetcher(
        lambda pid: mlb.fetch_pitcher_game_log(pid, season),
        cap=MAX_FRESH_PITCHER_FETCHES, memo=_fresh_logs_memo, day=day, lock=_memo_lock)


def _build_payload() -> dict:
    now = datetime.now(timezone.utc)
    store = history.read_results()
    manifest = history.read_manifest()
    store, through = _topup_results(store, manifest, now)
    fetcher = _fresh_fetcher(now)
    try:
        return postseason_page.build(
            now, results_store=store,
            standings=_topup_standings(standings_store.read(), now),
            probables=postseason_page.upcoming_games(
                now, mlb.fetch_games, SCHEDULE_DAYS_AHEAD), results_through=through,
            fresh_pitcher_logs=fetcher)
    finally:
        fetcher.report()


def _guarded_build() -> dict:
    global _last_failure_at, _last_unavailable
    with _failure_lock:
        recent = (_last_failure_at is not None
                  and time.monotonic() - _last_failure_at < FAILURE_BACKOFF_S)
    if recent:
        raise RuntimeError("postseason build failed moments ago; not retrying yet")
    try:
        payload = _build_payload()
        if not payload.get("available"):
            # Not a page: raise so the cache keeps (and serves, flagged stale)
            # the last good one. The route answers with this payload only when
            # there is no good page at all.
            with _failure_lock:
                _last_unavailable = payload
            raise BuildUnavailable(payload.get("detail") or payload.get("reason") or "unavailable")
        with _failure_lock:
            _last_unavailable = None
        return payload
    except BuildUnavailable:
        with _failure_lock:
            _last_failure_at = time.monotonic()
        raise
    except Exception:
        with _failure_lock:
            _last_failure_at = time.monotonic()
            _last_unavailable = None
        raise


# -- route ----------------------------------------------------------------

@router.get("/postseason")
def get_postseason(authorization: Optional[str] = Header(default=None)) -> dict:
    """The page's data: series state and chances, game-by-game forecasts,
    pennant and World Series odds, `as_of`, the model note and the caveats.
    `available: false` with a `reason` when the field cannot be set.

    Public: no token is required and none changes the answer. When a valid
    token IS presented (a signed-in tester opening the page; the web client
    attaches the stored token to every request) and the page was served, the
    visit is recorded as a `postseason` value action (src/appstate/
    activation.py). An anonymous visitor, a bad token and the unavailable
    answer record nothing."""
    try:
        payload, meta = _cache.get(CACHE_KEY, _guarded_build)
    except Exception as exc:  # noqa: BLE001 -- never a 500; see module docstring
        print(f"postseason build failed: {exc!r}", file=sys.stderr, flush=True)
        with _failure_lock:
            last = _last_unavailable
        if last is not None:
            # No good page to fall back on: answer with the builder's own
            # plain reason. Its internal detail goes to stderr, not to the
            # public response.
            out = dict(last)
            detail = out.pop("detail", None)
            if detail:
                print(f"postseason unavailable: {detail}", file=sys.stderr, flush=True)
            return out
        return postseason_page.unavailable(ABSENT_REASON, datetime.now(timezone.utc))
    out = dict(payload)
    out.pop("detail", None)
    out["freshness"] = {k: meta.get(k) for k in ("served_at", "built_at", "stale", "stale_reason")}
    activation.record_value_action(optional_user_id(authorization), "postseason",
                                   route="/postseason")
    return out
