"""Append-only odds snapshot capture. The history IS the data.

WHY THIS EXISTS AND WHY IT CANNOT WAIT
--------------------------------------
Results and stats can be backfilled from decades of archives. Line movement cannot.

There is no free source of "what was this price four hours before first pitch on a Tuesday
last April." Either you were recording at the time or that information is gone permanently.
Every day this job is not running is a day of market data that can never be recovered, which
makes this the one piece of infrastructure whose value depends entirely on starting early.

It also produces the single most important field in the whole project: the CLOSING LINE. Closing
line value -- whether picks were made at better prices than the market settled at -- converges
roughly ten times faster than ROI and is the standard by which this system will eventually be
judged. Every closing price captured now is a graded pick that becomes possible later.

DESIGN: APPEND-ONLY, NEVER MUTATE
---------------------------------
A snapshot is an observation at a moment. Observations are facts and are never edited, merged,
or de-duplicated in place. Storage is JSON Lines: one observation per line, appended, never
rewritten. A corrupt line costs one observation rather than the whole file, and a crashed run
leaves a truncated final line rather than a scrambled dataset.

Prices are never interpolated. If no observation exists for a window, that window is empty and
callers must handle the gap rather than receiving a plausible invention.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.core import odds as odds_math
from src.providers import odds as odds_provider

DEFAULT_SNAPSHOT_PATH = Path("data/processed/odds_snapshots.jsonl")

# A snapshot taken after first pitch is not a closing line -- the market has moved on to
# in-play pricing, which is a different product. This margin keeps late-arriving observations
# from being mistaken for the close.
CLOSING_GRACE_SECONDS = 0


class SnapshotError(RuntimeError):
    """Raised when snapshots cannot be captured, read, or interpreted."""


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def capture(env=None, path=DEFAULT_SNAPSHOT_PATH, timeout: int = 20,
            now=None) -> dict:
    """Fetch current odds and append one observation per game per market.

    Returns a summary. Never raises on a missing key -- an unconfigured system reports
    that and writes nothing, so this is safe to put on a schedule before setup is finished.
    """
    status = odds_provider.status(env)
    if not status["configured"]:
        return {
            "captured": 0, "events": 0, "written_to": None,
            "configured": False, "message": status["message"],
        }

    observed = _timestamp(now)
    try:
        payload = odds_provider.fetch_normalized(env=env, timeout=timeout)
    except odds_provider.OddsProviderError as exc:
        return {
            "captured": 0, "events": 0, "written_to": None,
            "configured": True, "error": str(exc),
        }

    rows = []
    for event in payload["events"]:
        for market_key, market in (event.get("markets") or {}).items():
            rows.append({
                "observed_utc": observed,
                "event_id": event.get("event_id"),
                "commence_time": event.get("commence_time"),
                "away_team": event.get("away_team"),
                "home_team": event.get("home_team"),
                "market": market_key,
                "book": market.get("book"),
                "prices": {k: v for k, v in market.items() if k not in ("book", "last_update")},
                "book_last_update": market.get("last_update"),
            })

    written = append(rows, path=path)
    return {
        "captured": written, "events": payload["event_count"],
        "written_to": str(path), "configured": True, "observed_utc": observed,
    }


def append(rows, path=DEFAULT_SNAPSHOT_PATH) -> int:
    """Append observations as JSON Lines. Never rewrites existing content."""
    if not rows:
        return 0
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return len(rows)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read(path=DEFAULT_SNAPSHOT_PATH, skip_corrupt: bool = True) -> list:
    """Read all observations.

    A truncated final line is the normal signature of a run killed mid-write. With
    `skip_corrupt` that costs one observation instead of the entire history, which is the
    right trade for an append-only log.
    """
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    with target.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                if skip_corrupt:
                    continue
                raise SnapshotError(f"corrupt snapshot on line {number} of {target}")
    return rows


def game_key(away_team, home_team, commence_time) -> tuple:
    """Identity for one scheduled game, stable across observations."""
    day = (commence_time or "")[:10]
    return (away_team, home_team, day)


def group_by_game(rows, market: str = "h2h") -> dict:
    """Bucket observations for one market by game, sorted oldest first."""
    grouped = {}
    for row in rows:
        if row.get("market") != market:
            continue
        key = game_key(row.get("away_team"), row.get("home_team"),
                       row.get("commence_time"))
        grouped.setdefault(key, []).append(row)
    for series in grouped.values():
        series.sort(key=lambda r: r.get("observed_utc") or "")
    return grouped


# ---------------------------------------------------------------------------
# Derived signals
# ---------------------------------------------------------------------------

def closing_observation(series, commence_time=None):
    """The last observation strictly BEFORE first pitch.

    Returns None when nothing was recorded before the game started. That is a real and common
    outcome -- a job that started mid-season has no closing line for earlier games -- and it
    must stay distinguishable from a captured close, because silently substituting the nearest
    available price would corrupt every CLV number computed from it.
    """
    if not series:
        return None
    start = commence_time or series[0].get("commence_time")
    if not start:
        return None
    try:
        cutoff = _parse(start)
    except SnapshotError:
        return None

    before = []
    for row in series:
        stamp = row.get("observed_utc")
        if not stamp:
            continue
        try:
            moment = _parse(stamp)
        except SnapshotError:
            continue
        if (cutoff - moment).total_seconds() > CLOSING_GRACE_SECONDS:
            before.append((moment, row))
    if not before:
        return None
    before.sort(key=lambda pair: pair[0])
    return before[-1][1]


def movement(series, side: str = "home_price") -> dict:
    """Opening price, closing price, and the drift between them for one side.

    `observations` counts how many times the market was actually sampled. A large move measured
    across two observations twelve hours apart is not the same evidence as the same move seen
    across twenty, and reporting the count keeps that distinction visible.
    """
    prices = []
    for row in series:
        value = (row.get("prices") or {}).get(side)
        if value is not None:
            prices.append((row.get("observed_utc"), value))
    if not prices:
        return {"observations": 0, "opening": None, "closing": None,
                "moved": None, "direction": None}

    opening_time, opening = prices[0]
    closing_time, closing = prices[-1]

    try:
        opening_prob = odds_math.american_to_probability(opening)
        closing_prob = odds_math.american_to_probability(closing)
        prob_shift = closing_prob - opening_prob
    except odds_math.OddsError:
        prob_shift = None

    return {
        "observations": len(prices),
        "opening": opening, "opening_utc": opening_time,
        "closing": closing, "closing_utc": closing_time,
        "moved": closing - opening,
        "implied_prob_shift": round(prob_shift, 6) if prob_shift is not None else None,
        "direction": "toward" if closing < opening else ("away" if closing > opening else "flat"),
    }


def closing_line_value(pick_price, closing_price) -> dict:
    """How much better the taken price was than where the market closed.

    Positive CLV means the bet was placed at a better number than the market settled on. This
    is the metric that judges the system long before ROI says anything reliable, because it
    measures whether real inefficiency was found rather than whether the coin landed right.

    Expressed two ways: in cents of American odds, and as the difference in implied probability,
    which is the comparable figure across favorites and underdogs.
    """
    pick_prob = odds_math.american_to_probability(pick_price)
    close_prob = odds_math.american_to_probability(closing_price)
    return {
        "pick_price": pick_price,
        "closing_price": closing_price,
        "cents": closing_price - pick_price,
        "prob_edge": round(close_prob - pick_prob, 6),
        "beat_close": close_prob > pick_prob,
    }


def coverage(rows) -> dict:
    """How complete the snapshot history is. Surfaces gaps rather than hiding them."""
    if not rows:
        return {"observations": 0, "games": 0, "with_closing": 0,
                "closing_rate": 0.0, "first_utc": None, "last_utc": None}

    grouped = group_by_game(rows)
    with_closing = sum(
        1 for series in grouped.values() if closing_observation(series) is not None
    )
    stamps = sorted(r["observed_utc"] for r in rows if r.get("observed_utc"))
    return {
        "observations": len(rows),
        "games": len(grouped),
        "with_closing": with_closing,
        "closing_rate": round(with_closing / len(grouped), 3) if grouped else 0.0,
        "first_utc": stamps[0] if stamps else None,
        "last_utc": stamps[-1] if stamps else None,
    }


def _timestamp(now=None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _parse(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise SnapshotError(f"timestamp must be a string, got {value!r}")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SnapshotError(f"could not parse timestamp {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
