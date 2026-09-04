"""T-2h timing-normalization repair for F5 moneyline odds.

FROZEN RULE -- see docs/PREREG_F5_SNAPSHOT_RULE.md and
docs/F5_REPAIR_RELEASE_GATE.md. Implement exactly; do not reinterpret.

For each named game:

1. Anchor = ``start_time_utc`` from ``data/historical/mlb_results.csv``,
   joined by ``game_pk`` -- never the eventual actual first pitch.
2. Target instant = anchor - 2:00:00.
3. Query the provider's 5-minute snapshot grid for the point nearest the
   target. The returned snapshot must be genuinely pregame and land within
   +/-5 minutes of the target, or the game is ``PRIMARY_SNAPSHOT_UNAVAILABLE``.
4. Require >=5 valid books carrying ``h2h_1st_5_innings``.
5. A miss is a row, not a drop: every named game gets exactly one row in
   ``F5_RAW_HISTORY``, tagged ``snapshot_rule: "tminus2_v1"``, whether it
   priced or not.

NEVER SLIDE THE TARGET. A game whose nearest usable grid point is outside
tolerance is unavailable, not re-anchored to a more convenient time.

TWO LAYERS
----------
``F5_RAW_HISTORY`` (this module writes to it): the existing
``data/historical/odds_first_five/mlb_*.jsonl`` files, appended to, never
rewritten. Every row this module writes carries ``snapshot_rule:
"tminus2_v1"`` so it is distinguishable from the legacy fixed-wall-clock
rows already in those files.

``F5_TMINUS2_PRIMARY``: a derived view, rebuilt by ``build_primary_view``
from ``F5_RAW_HISTORY``, never independently written to.

NEVER BUY THE SAME TARGET TWICE. A manifest keyed by ``game_pk`` (the target
instant is a deterministic function of ``game_pk``, so one manifest entry
per game_pk is the same thing as one target timestamp) tracks every game
already attempted under this rule -- OK or UNAVAILABLE both count as
attempted -- so a resumed run costs nothing to re-touch. Check 7 (redefined
2026-09-04) additionally says: skip a game if a *compliant* T-2h observation
already exists anywhere in raw history under this rule; a non-compliant
prior attempt is not grounds to skip, but this module never produces a
non-compliant OK row in the first place, so in practice "already attempted"
and "already compliant-or-permanently-unavailable" coincide.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.paths import historical_path
from src.providers import odds as odds_provider

SNAPSHOT_RULE = "tminus2_v1"
MONEYLINE_MARKET = "h2h_1st_5_innings"
TARGET_LEAD = timedelta(hours=2)
GRID_TOLERANCE = timedelta(minutes=5)
MIN_BOOKS = 5

# One events lookup (~1 credit) plus one per-event odds call for a single
# market at HISTORICAL_MULTIPLIER (10) = ~11 credits/game. This is a
# pre-spend BOUND used only to decide whether to attempt the next game; the
# actual charge is always read from the provider's own response headers and
# is what `report["credits_spent"]` accumulates.
ESTIMATED_CREDITS_PER_GAME = 11

STORE = historical_path("odds_first_five")
RESULTS_CSV = historical_path("mlb_results.csv")


class TimingRuleError(RuntimeError):
    """Raised when the acquisition cannot proceed safely."""


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _parse_utc(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value)
    text = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(moment) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def target_instant(scheduled_first_pitch) -> datetime:
    """The T-2:00 target, before any grid-snapping. Never the actual first pitch."""
    anchor = _parse_utc(scheduled_first_pitch)
    if anchor is None:
        raise TimingRuleError("scheduled_first_pitch is required and must parse")
    return anchor - TARGET_LEAD


def deviation_minutes(query_target, snapshot_at) -> float | None:
    """|snapshot_at - query_target| in minutes, or None if either is missing."""
    target = _parse_utc(query_target)
    snap = _parse_utc(snapshot_at)
    if target is None or snap is None:
        return None
    return abs((snap - target).total_seconds()) / 60.0


# ---------------------------------------------------------------------------
# Compliance predicate -- the whole frozen rule in one place
# ---------------------------------------------------------------------------

def book_count(payload_data: dict, market: str = MONEYLINE_MARKET) -> int:
    """Count of UNIQUE bookmakers (by `key`) carrying `market` with at least
    one priced outcome.

    A bookmaker listing the market key with an empty outcomes list is not a
    valid book -- it carries no price and must not inflate the count that
    gates the >=5-book requirement. Deduplicated by book `key` rather than
    counted per row: a provider response that happened to list the same book
    twice must not double-count toward the >=5-book floor.
    """
    books = (payload_data or {}).get("bookmakers") or []
    keys = set()
    for book in books:
        for market_row in (book.get("markets") or []):
            if market_row.get("key") == market and (market_row.get("outcomes") or []):
                keys.add(book.get("key"))
                break
    return len(keys)


def classify(*, scheduled_first_pitch, query_target, snapshot_at,
             valid_book_count: int) -> tuple:
    """Apply the frozen rule. Returns (status, reason) -- reason is None for OK.

    Order: grid tolerance, then pregame, then book depth. Any one failing is
    enough to mark the game PRIMARY_SNAPSHOT_UNAVAILABLE; only one reason is
    ever recorded, in this precedence, so the reason string is deterministic.
    """
    if snapshot_at is None:
        return "PRIMARY_SNAPSHOT_UNAVAILABLE", "no_grid_point_within_tolerance"

    dev = deviation_minutes(query_target, snapshot_at)
    if dev is None or dev > GRID_TOLERANCE.total_seconds() / 60.0:
        return "PRIMARY_SNAPSHOT_UNAVAILABLE", "no_grid_point_within_tolerance"

    scheduled = _parse_utc(scheduled_first_pitch)
    snap = _parse_utc(snapshot_at)
    if scheduled is None or snap is None or not (snap < scheduled):
        return "PRIMARY_SNAPSHOT_UNAVAILABLE", "not_pregame"

    if valid_book_count < MIN_BOOKS:
        return "PRIMARY_SNAPSHOT_UNAVAILABLE", "fewer_than_5_books"

    return "OK", None


# ---------------------------------------------------------------------------
# Manifest -- never buy the same target twice
# ---------------------------------------------------------------------------

def _manifest_file(store=STORE) -> Path:
    return Path(store) / "manifest_tminus2.json"


def read_manifest(store=STORE) -> dict:
    target = _manifest_file(store)
    if not target.exists():
        return {"games": {}}
    data = json.loads(target.read_text(encoding="utf-8"))
    data.setdefault("games", {})
    return data


def write_manifest(manifest: dict, store=STORE) -> str:
    target = _manifest_file(store)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return str(target)


# ---------------------------------------------------------------------------
# Schedule join
# ---------------------------------------------------------------------------

def load_schedule(path=RESULTS_CSV) -> dict:
    """game_pk (str) -> row dict from mlb_results.csv. The join this whole
    rule depends on (§3 of the pre-reg): start_time_utc is the ONLY anchor."""
    import csv
    out = {}
    target = Path(path)
    if not target.exists():
        return out
    with target.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pk = (row.get("game_pk") or "").strip()
            if pk:
                out[pk] = row
    return out


# ---------------------------------------------------------------------------
# Fetch (provider seam -- injectable for tests)
# ---------------------------------------------------------------------------

def _events_at_instant(instant_iso, timeout=30):
    return odds_provider._get_json_with_usage(
        f"historical/sports/{odds_provider.SPORT}/events",
        {"apiKey": odds_provider.api_key(), "date": instant_iso},
        timeout=timeout)


def _event_odds_at_instant(instant_iso, event_id, timeout=30):
    return odds_provider._get_json_with_usage(
        f"historical/sports/{odds_provider.SPORT}/events/{event_id}/odds",
        {"apiKey": odds_provider.api_key(),
         "regions": odds_provider.DEFAULT_REGION,
         "markets": MONEYLINE_MARKET,
         "oddsFormat": odds_provider.ODDS_FORMAT,
         "date": instant_iso},
        timeout=timeout)


def _match_event(events, away_canon, home_canon):
    from src.pipeline import slate as slate_mod
    from src.data import parks

    def canon(abbrev):
        try:
            return parks.canonical_team(abbrev) if abbrev else abbrev
        except parks.ParkError:
            return abbrev

    for event in events:
        away = canon(slate_mod.team_abbrev_from_name(event.get("away_team")))
        home = canon(slate_mod.team_abbrev_from_name(event.get("home_team")))
        if away == away_canon and home == home_canon:
            return event
    return None


# ---------------------------------------------------------------------------
# Acquisition -- one game
# ---------------------------------------------------------------------------

def acquire_one(game_pk, schedule_row, *, events_fetch=None, odds_fetch=None,
                 timeout=30, now=None) -> dict:
    """Acquire (or record the miss for) one game under the frozen rule.

    Returns the F5_RAW_HISTORY row to append, plus a `_usage` list of every
    provider call's billing, so the caller can total credits without a
    second pass. Never raises for a provider-shaped miss (no matching event,
    not pregame, thin book, off-grid) -- those are `status:
    PRIMARY_SNAPSHOT_UNAVAILABLE` rows, not exceptions. Raises only on a
    genuine provider/connection failure so the caller can retry or stop.
    """
    from src.data import parks

    events_fetch = events_fetch or _events_at_instant
    odds_fetch = odds_fetch or _event_odds_at_instant

    scheduled_first_pitch = schedule_row.get("start_time_utc")
    target = target_instant(scheduled_first_pitch)
    target_iso = _iso(target)

    away_canon = parks.canonical_team(schedule_row.get("away_team", ""))
    home_canon = parks.canonical_team(schedule_row.get("home_team", ""))

    usage_calls = []

    base_row = {
        "game_pk": str(game_pk),
        "date": schedule_row.get("date"),
        "away_team": away_canon,
        "home_team": home_canon,
        "scheduled_first_pitch": scheduled_first_pitch,
        "actual_first_pitch": None,
        "query_instant": target_iso,
        "snapshot_rule": SNAPSHOT_RULE,
        "markets": [MONEYLINE_MARKET],
    }

    def _unavailable(reason):
        base_row.update({
            "event_id": None, "commence_time": None, "snapshot_at": None,
            "lead_time_hours": None, "book_count": 0, "data": None,
            "status": "PRIMARY_SNAPSHOT_UNAVAILABLE", "reason": reason,
        })
        base_row["_usage"] = usage_calls
        return base_row

    try:
        events_payload, events_usage = events_fetch(target_iso, timeout=timeout)
    except odds_provider.MarketsUnavailableAtDate:
        # Terminal and zero-cost (confirmed live, src/providers/odds.py):
        # a date before the market's own history begins 422s forever. Never
        # retried at another instant -- that would be sliding the target.
        usage_calls.append({"call": "events", "usage": {"remaining": None, "last": 0}})
        return _unavailable("markets_unavailable_at_date")
    usage_calls.append({"call": "events", "usage": events_usage})
    events = (events_payload.get("data") if isinstance(events_payload, dict)
              else events_payload) or []
    event = _match_event(events, away_canon, home_canon)

    if event is None:
        return _unavailable("no_matching_event")

    try:
        odds_payload, odds_usage = odds_fetch(target_iso, event["id"], timeout=timeout)
    except odds_provider.MarketsUnavailableAtDate:
        usage_calls.append({"call": "event_odds", "usage": {"remaining": None, "last": 0}})
        return _unavailable("markets_unavailable_at_date")
    usage_calls.append({"call": "event_odds", "usage": odds_usage})

    data = odds_payload.get("data") or {}
    snapshot_at = odds_payload.get("timestamp")
    n_books = book_count(data)
    status, reason = classify(
        scheduled_first_pitch=scheduled_first_pitch,
        query_target=target, snapshot_at=snapshot_at,
        valid_book_count=n_books)

    lead_time_hours = None
    sched = _parse_utc(scheduled_first_pitch)
    snap = _parse_utc(snapshot_at)
    if sched is not None and snap is not None:
        lead_time_hours = round((sched - snap).total_seconds() / 3600.0, 4)

    base_row.update({
        "event_id": event.get("id"),
        "commence_time": event.get("commence_time"),
        "snapshot_at": snapshot_at,
        "lead_time_hours": lead_time_hours,
        "book_count": n_books,
        "data": data,
        "status": status,
        "reason": reason,
    })
    base_row["_usage"] = usage_calls
    return base_row


# ---------------------------------------------------------------------------
# Store I/O
# ---------------------------------------------------------------------------

def _season_file(store, season) -> Path:
    return Path(store) / f"mlb_{season}.jsonl"


def append_raw_row(row: dict, store=STORE) -> str:
    """Append one row to the season file. F5_RAW_HISTORY is append-only:
    this never opens a file for anything but 'a'."""
    season = str(row["date"])[:4] if row.get("date") else "unknown"
    target = _season_file(store, season)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {k: v for k, v in row.items() if not k.startswith("_")}
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return str(target)


def read_raw_season(season, store=STORE) -> list:
    target = _season_file(store, season)
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Run -- bounded by a games list and a credit budget
# ---------------------------------------------------------------------------

def run(games, *, schedule=None, budget=None, store=STORE,
        events_fetch=None, odds_fetch=None, on_game=None, timeout=30) -> dict:
    """Acquire T-2h observations for a named list of game_pks.

    `games` is a list of game_pk (str/int). `schedule` defaults to loading
    mlb_results.csv; pass a dict to inject one in tests. Skips any game_pk
    already present in the manifest (never buy the same target twice).
    """
    schedule = schedule if schedule is not None else load_schedule()
    manifest = read_manifest(store)

    report = {"requested": len(games), "attempted": 0, "skipped_already_attempted": 0,
              "ok": 0, "unavailable": 0, "reason_counts": {},
              "credits_spent": 0, "credits_remaining": None,
              "stopped_early": None, "store": str(store), "rows": []}

    for game_pk in games:
        key = str(game_pk)
        if key in manifest["games"]:
            report["skipped_already_attempted"] += 1
            continue

        row_schedule = schedule.get(key)
        if row_schedule is None:
            row = {"game_pk": key, "date": None, "status":
                    "PRIMARY_SNAPSHOT_UNAVAILABLE",
                    "reason": "game_pk_missing_from_schedule",
                    "snapshot_rule": SNAPSHOT_RULE, "book_count": 0,
                    "snapshot_at": None, "query_instant": None,
                    "lead_time_hours": None, "scheduled_first_pitch": None,
                    "actual_first_pitch": None, "away_team": None,
                    "home_team": None, "event_id": None, "commence_time": None,
                    "data": None, "markets": [MONEYLINE_MARKET]}
            append_raw_row(row, store)
            manifest["games"][key] = {"status": row["status"], "reason": row["reason"]}
            write_manifest(manifest, store)
            report["attempted"] += 1
            report["unavailable"] += 1
            report["reason_counts"][row["reason"]] = (
                report["reason_counts"].get(row["reason"], 0) + 1)
            report["rows"].append(row)
            if on_game:
                on_game(row)
            continue

        # Cost check before spending, using the observed per-game rate once
        # there is one (the API is the authority on billing), else the
        # pre-spend bound above.
        observed_rate = (report["credits_spent"] / report["attempted"]
                         if report["attempted"] else ESTIMATED_CREDITS_PER_GAME)
        next_cost_estimate = max(ESTIMATED_CREDITS_PER_GAME, observed_rate)
        if budget is not None and report["credits_spent"] + next_cost_estimate > budget:
            report["stopped_early"] = (
                f"budget of {budget} credits would likely be exceeded by the "
                f"next game; {report['attempted']} games attempted so far and "
                "the run is resumable")
            return report

        row = acquire_one(key, row_schedule, events_fetch=events_fetch,
                          odds_fetch=odds_fetch, timeout=timeout)
        spent = sum((c["usage"].get("last") or 0) for c in row.get("_usage", []))
        report["credits_spent"] += spent
        remaining_values = [c["usage"].get("remaining") for c in row.get("_usage", [])
                            if c["usage"].get("remaining") is not None]
        if remaining_values:
            report["credits_remaining"] = remaining_values[-1]

        append_raw_row(row, store)
        manifest["games"][key] = {"status": row["status"], "reason": row.get("reason")}
        write_manifest(manifest, store)

        report["attempted"] += 1
        if row["status"] == "OK":
            report["ok"] += 1
        else:
            report["unavailable"] += 1
            report["reason_counts"][row["reason"]] = (
                report["reason_counts"].get(row["reason"], 0) + 1)
        clean_row = {k: v for k, v in row.items() if not k.startswith("_")}
        report["rows"].append(clean_row)
        if on_game:
            on_game(clean_row)

        if budget is not None and report["credits_spent"] >= budget:
            report["stopped_early"] = (
                f"budget of {budget} credits reached after "
                f"{report['attempted']} games attempted; run is resumable")
            return report

    return report


# ---------------------------------------------------------------------------
# F5_TMINUS2_PRIMARY -- derived view, rebuilt from F5_RAW_HISTORY
# ---------------------------------------------------------------------------

def _books_projection(data: dict) -> list:
    out = []
    for book in (data or {}).get("bookmakers") or []:
        for market_row in (book.get("markets") or []):
            if market_row.get("key") != MONEYLINE_MARKET:
                continue
            outcomes = market_row.get("outcomes") or []
            away_price = home_price = None
            for outcome in outcomes:
                name = outcome.get("name")
                if name == data.get("away_team"):
                    away_price = outcome.get("price")
                elif name == data.get("home_team"):
                    home_price = outcome.get("price")
            out.append({
                "key": book.get("key"),
                "last_update": book.get("last_update"),
                MONEYLINE_MARKET: {
                    "away_price": away_price,
                    "home_price": home_price,
                    "last_update": market_row.get("last_update"),
                },
            })
    return out


def build_primary_view(seasons, store=STORE) -> list:
    """Rebuild F5_TMINUS2_PRIMARY by filtering raw history to `snapshot_rule
    == tminus2_v1`, one row per game_pk (latest occurrence wins, matching
    the manifest's own never-buy-twice guarantee). Never hand-edited."""
    by_pk = {}
    for season in seasons:
        for row in read_raw_season(season, store):
            if row.get("snapshot_rule") != SNAPSHOT_RULE:
                continue
            data = row.get("data") or {}
            by_pk[row["game_pk"]] = {
                "game_pk": row["game_pk"],
                "date": row.get("date"),
                "away_team": row.get("away_team"),
                "home_team": row.get("home_team"),
                "scheduled_first_pitch": row.get("scheduled_first_pitch"),
                "actual_first_pitch": row.get("actual_first_pitch"),
                "query_instant": row.get("query_instant"),
                "snapshot_at": row.get("snapshot_at"),
                "lead_time_hours": row.get("lead_time_hours"),
                "book_count": row.get("book_count"),
                "books": _books_projection(data) if row.get("status") == "OK" else [],
                "status": row.get("status"),
                "reason": row.get("reason"),
                "snapshot_rule": row.get("snapshot_rule"),
            }
    return list(by_pk.values())


def write_primary_view(rows: list, path=None, store=STORE) -> str:
    target = Path(path) if path else Path(store) / "f5_tminus2_primary.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return str(target)
