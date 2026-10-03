"""Activation: what counts as a tester actually using LineHound, defined once.

THE OWNER'S RULE (2026-10-03)
--------------------------------
"Define ACTIVATED as a meaningful product action, not account creation...
Prefer an action that represents actual value consumption. Track time:
SIGNUP -> ACTIVATION." and "Track whether testers actually click/use:
moneylines, props, postseason forecasts, NFL, UFC, deep matchup analysis,
price comparison."

Until now the Testers table called a tester "activated" when their token was
first used. That is a sign-in. A person can sign in and close the tab. It stays
visible as `first_signin_at`; it is not activation.

THE TWO DEFINITIONS (the only place they are written)
-------------------------------------------------------
  VALUE ACTION   An authenticated request (a real access token, never an
                 anonymous visitor) that SUCCESSFULLY returned product content
                 for one of the FEATURES below. Recorded by the server, from the
                 route that served it, as a `page_view` event whose properties
                 carry `feature` (see `record_value_action`). Never from a
                 client message, never on a 4xx or 5xx, never on the public
                 record page.
  ACTIVATED      The user has at least one value action. `activated_at` is
                 the first one. Redeeming a token or creating an account is not.
  RETURNING      A value action at least RETURNING_AFTER (12 hours) after the
                 first. Equivalent to "last value action minus first is 12 hours
                 or more", which is how it is computed (no per-event scan).

THE FEATURE LABELS AND WHAT MEASURES THEM
-------------------------------------------
`feature` is the MOST SPECIFIC label for what was served. A card request for
sport=nfl is `nfl`, for sport=mma it is `ufc`, otherwise `card`; the surface
(`card`) and the sport are kept next to it in `surface` and `sport`, so one event
answers both "did they use NFL" and "which NFL page". Only the sport the route
actually SERVED counts: GET /games?sport=mma serves the MLB slate, so it is
`slate`, not `ufc`.

  route (what the web app calls)              label
  GET /card/{date}, GET /card                 card   (nfl / ufc by sport)
  GET /games/{date}                           slate  (nfl by sport)
  GET /game/{date}/{away}/{home}              matchup
  GET /props/{date}, GET /props               props
  GET /odds/{date}/{away}/{home}              prices
  GET /postseason                             postseason (public route: recorded
                                              only when a token is presented)

ROUTES THE WEB APP CALLS BUT THAT ARE DELIBERATELY NOT LABELLED. The page that
opens first after sign-in (#/today) fetches six routes at once, so a label on any
route a page fetches in the background would make every Today view look like use
of that feature, and every tester would have "used" everything. A route earns a
label only when the fetch is the page the person chose, or the one fetch that IS
that surface on a page:

  GET /today            the same slate GET /games/{date} serves, fetched by the
                        same page load; also fetched in the background by the
                        results page and the landing page. One label per
                        surface per page load, so it stays on /games/{date}.
  GET /odds/{date}      the price board. Fetched in the background by Today and
                        by the Matchups list as well as by the board page itself,
                        and the server cannot tell them apart. Tagging it would
                        make a Today view count as price comparison. Per-game
                        price comparison (/odds/{date}/{away}/{home}) is only
                        reached by clicking "open the full board", so it is the
                        measurable half of `prices`.
  GET /opportunities*   the moneyline board, but only ever fetched in the
                        background by the matchup grid on Today. No route serves
                        moneylines as the page the person chose, so `moneyline`
                        is not measurable yet (UNMEASURED_FEATURES).
  GET /changed/{date}, /daily*, /performance*, /live, /tennis/board, /my-bets,
  /digest, /onboarding, POST /betcheck: not in the fixed label set (Bet Check
  keeps its own BET_CHECK_RUN event).

An empty-but-successful answer (an off day's card, an empty prop board) counts:
the person opened the page and got the product's honest answer. The payload is
not inspected.

THE DATA, AND WHY THE READS ARE BOUNDED
------------------------------------------
Value actions are rows of `analytics_events` (kind page_view). The tester
report reads them with ONE grouped SQL query filtered by kind, by the tester
user hashes and by a known feature label, and returns at most
users x labels x distinct days rows. It never loads the events table into
Python (production has run out of memory on whole-table reads). Recording adds
exactly one insert to a request that already wrote one before this module.
"""

from __future__ import annotations

import statistics
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set

from src.appstate import events

# The fixed label set. Order is the order every report lists them in.
FEATURES = ("card", "matchup", "moneyline", "props", "prices", "postseason",
            "nfl", "ufc", "slate")

# The `sport` a route served -> the label that replaces its surface.
SPORT_FEATURES = {"nfl": "nfl", "mma": "ufc"}

# Labels at least one route can emit today (see the table above). The rest are
# reported as not measurable yet, so a zero is never mistaken for "nobody used it".
MEASURED_FEATURES = frozenset({"card", "matchup", "props", "prices", "postseason",
                               "nfl", "ufc", "slate"})
UNMEASURED_FEATURES = tuple(f for f in FEATURES if f not in MEASURED_FEATURES)

# RETURNING: a value action this long after the first one.
RETURNING_AFTER = timedelta(hours=12)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def feature_for(surface: str, sport: Optional[str] = None) -> str:
    """The label for a request that served `surface` content for `sport`: the
    sport's own label when it has one (nfl, ufc), else the surface."""
    if surface not in FEATURES:
        raise ValueError(f"unknown feature {surface!r}; must be one of {FEATURES}")
    return SPORT_FEATURES.get(sport or "", surface)


def value_properties(surface: str, sport: Optional[str] = "mlb") -> Dict[str, str]:
    """The three properties every value action carries."""
    return {"feature": feature_for(surface, sport), "surface": surface,
            "sport": sport or "mlb"}


def record_value_action(user_id, surface: str, *, route: str,
                        date: Optional[str] = None, sport: Optional[str] = "mlb",
                        at: Optional[str] = None, db=None) -> None:
    """Record one value action for an authenticated `user_id` (the RAW id).

    Call it only after the response body is built and only for an authenticated
    caller. Nothing here can fail the request: a bad label, a locked database or
    a full disk costs one missing data point (the same contract as
    events.record_event_safe, which does the write). A `None` user id records
    nothing, which is what keeps an anonymous visitor out.
    """
    if user_id is None:
        return
    try:
        props = {"route": route, "date": date}
        props.update(value_properties(surface, sport))
        # `at` and `db` are for tests and tools; a route passes neither.
        extra = {}
        if at is not None:
            extra["at"] = at
        if db is not None:
            extra["db"] = db
        events.record_event_safe(user_id, events.PAGE_VIEW, props, **extra)
    except Exception as exc:  # noqa: BLE001 -- must never raise into a route
        print(f"activation: could not record a value action for {surface!r}: {exc!r}",
              file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Reading (bounded SQL)
# ---------------------------------------------------------------------------

def _placeholders(count: int) -> str:
    return ",".join("?" * count)


def value_action_stats(user_hashes: Sequence[str], *, db=None) -> Dict[str, dict]:
    """hash -> {"first_at", "last_at", "features": {label: n}, "days": {dates}}
    for every hash that has at least one value action; hashes with none are
    absent.

    ONE query, grouped by (user, feature, UTC day), filtered by kind, by the
    given hashes and by a known label, so memory is bounded by users x labels x
    days and never by the size of the events table. `json_valid` guards the
    JSON read so a row with unreadable properties is skipped, not fatal. The
    day is the first ten characters of `at`, the same UTC-date rule
    api/funnel.py uses.
    """
    hashes = list(dict.fromkeys(user_hashes))
    if not hashes:
        return {}
    sql = f"""
        SELECT user_hash, feature, substr(at, 1, 10) AS day,
               COUNT(*) AS n, MIN(at) AS first_at, MAX(at) AS last_at
          FROM (SELECT user_hash, at,
                       CASE WHEN json_valid(properties_json)
                            THEN json_extract(properties_json, '$.feature') END AS feature
                  FROM analytics_events
                 WHERE kind = ? AND user_hash IN ({_placeholders(len(hashes))}))
         WHERE feature IN ({_placeholders(len(FEATURES))})
         GROUP BY user_hash, feature, substr(at, 1, 10)
    """
    params = [events.PAGE_VIEW, *hashes, *FEATURES]
    out: Dict[str, dict] = {}
    with events._connect(db) as conn:
        for row in conn.execute(sql, params):
            slot = out.setdefault(row["user_hash"], {
                "first_at": row["first_at"], "last_at": row["last_at"],
                "features": {}, "days": set()})
            if _before(row["first_at"], slot["first_at"]):
                slot["first_at"] = row["first_at"]
            if _before(slot["last_at"], row["last_at"]):
                slot["last_at"] = row["last_at"]
            slot["features"][row["feature"]] = (
                slot["features"].get(row["feature"], 0) + row["n"])
            slot["days"].add(row["day"])
    return out


def parse_iso(value) -> Optional[datetime]:
    """An aware UTC datetime from an ISO-8601 string, or None. A trailing Z and
    a missing offset (read as UTC) are both accepted."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _before(a: str, b: str) -> bool:
    pa, pb = parse_iso(a), parse_iso(b)
    if pa is None or pb is None:
        return a < b
    return pa < pb


# ---------------------------------------------------------------------------
# Per-user and aggregate summaries (pure)
# ---------------------------------------------------------------------------

def user_activity(stats: Optional[Mapping], *, account_created_at: Optional[str],
                  tester_granted_at: Optional[str],
                  first_signin_at: Optional[str]) -> dict:
    """One user's activation facts. `stats` is that user's entry from
    `value_action_stats` (None when they have no value action)."""
    first = stats["first_at"] if stats else None
    last = stats["last_at"] if stats else None
    hours = None
    returning = False
    first_dt, last_dt = parse_iso(first), parse_iso(last)
    created_dt = parse_iso(account_created_at)
    if first_dt and created_dt:
        # Never negative: an event stamped before the account existed is a
        # clock or backfill oddity, not a negative time to value.
        hours = round(max((first_dt - created_dt).total_seconds(), 0.0) / 3600.0, 2)
    if first_dt and last_dt:
        returning = (last_dt - first_dt) >= RETURNING_AFTER
    return {
        "account_created_at": account_created_at,
        "tester_granted_at": tester_granted_at,
        "first_signin_at": first_signin_at,
        "activated": first is not None,
        "activated_at": first,
        "hours_signup_to_activation": hours,
        "last_active_at": last,
        "active_days": len(stats["days"]) if stats else 0,
        "returning": returning,
        "features": dict(stats["features"]) if stats else {},
    }


def summarise(rows: Iterable[Mapping], *, internal_ids: Set[int],
              as_of: datetime) -> dict:
    """The aggregate behind GET /admin/activation, from tester rows that already
    carry `user_id`, `expires_at` and the per-user fields above.

    Contains no email and no user id. Users in `internal_ids` (our own test
    accounts) are counted only in `internal_excluded`.

      testers_granted    distinct non-internal testers ever granted access.
      testers_in_window  of those, the ones whose access window (the expiry of
                         their newest token) is still open at `as_of`.
      activated          of those, with at least one value action.
      returning          of those, with a value action 12 hours or more after
                         their first.
      median_hours_signup_to_activation
                         median of account creation to first value action over
                         the activated ones; null when nobody has activated.
      feature_users      for every label, how many of them used it (zero when
                         none, and zero for a label nothing can record yet: see
                         `unmeasured_features`).
    """
    counted: List[Mapping] = []
    internal = 0
    for row in rows:
        if row["user_id"] in internal_ids:
            internal += 1
        else:
            counted.append(row)
    in_window = 0
    for row in counted:
        expires = parse_iso(row.get("expires_at"))
        if expires is not None and expires > as_of:
            in_window += 1
    hours = [r["hours_signup_to_activation"] for r in counted
             if r.get("hours_signup_to_activation") is not None]
    return {
        "as_of": as_of.isoformat(),
        "testers_granted": len(counted),
        "testers_in_window": in_window,
        "activated": sum(1 for r in counted if r.get("activated")),
        "returning": sum(1 for r in counted if r.get("returning")),
        "median_hours_signup_to_activation": (
            round(statistics.median(hours), 2) if hours else None),
        "feature_users": {
            label: sum(1 for r in counted if (r.get("features") or {}).get(label, 0) > 0)
            for label in FEATURES},
        "internal_excluded": internal,
        "unmeasured_features": list(UNMEASURED_FEATURES),
    }
