"""Discover which tennis tournaments The Odds API is pricing right now.

WHY THIS EXISTS
---------------
Tennis tournaments come and go throughout the year, and different ones are
active at different times. The /sports?all=true endpoint is free (0 credits)
and returns the full list of available sports, including tennis tournaments
keyed as "tennis_atp_china_open", "tennis_wta_us_open", etc. This module
discovers which tournaments are currently being priced, when they were last
observed, and whether they have outright/tournament-winner markets.

The store grows slowly because a real tournament is active for at most
a few weeks, and the endpoint is polled infrequently. Each observation
is a snapshot at one moment, and later observations replace earlier ones
from the same tournament key.

NO CREDIT LOGGING
-----------------
The /sports endpoint is free (0 credits), so there is nothing to log.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.paths import processed_path
from src.providers import odds as odds_provider

DEFAULT_PATH = processed_path("tennis_tournaments.jsonl")


def discover(*, fetch_sports=None, now=None, path=DEFAULT_PATH, env=None) -> dict:
    """Discover tennis tournaments The Odds API is pricing right now.

    fetch_sports: callable that returns a list of sports; defaults to
        odds.fetch_sports(all_sports=True, env=env)
    now: datetime for observed_utc; defaults to now
    path: JSONL file to append tournament rows to
    env: environment dict for the provider

    Returns:
        {"observed_utc": str, "keys": [str], "active_keys": [str], "written": n}

    On provider error:
        {"error": str, "written": 0} (no rows written)
    """
    if fetch_sports is None:
        fetch_sports = lambda: odds_provider.fetch_sports(all_sports=True, env=env)

    moment = now or datetime.now(timezone.utc)
    observed_utc = moment.isoformat()

    try:
        sports = fetch_sports()
    except Exception as exc:
        return {"error": str(exc), "written": 0}

    # Filter for tennis entries
    tennis_entries = [s for s in sports if isinstance(s, dict) and
                      s.get("key", "").startswith("tennis_")]

    # Ensure path parent exists
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Append each tennis entry as a row
    written = 0
    for entry in tennis_entries:
        row = {
            "observed_utc": observed_utc,
            "key": entry.get("key"),
            "title": entry.get("title"),
            "description": entry.get("description"),
            "group": entry.get("group"),
            "active": bool(entry.get("active")),
            "has_outrights": bool(entry.get("has_outrights")),
        }
        try:
            with open(target, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
            written += 1
        except OSError as exc:
            return {"error": f"failed to write row: {exc}", "written": written}

    # Collect all keys and active keys
    all_keys = [e.get("key") for e in tennis_entries if e.get("key")]
    active_keys = [e.get("key") for e in tennis_entries
                   if e.get("key") and e.get("active")]

    return {
        "observed_utc": observed_utc,
        "keys": all_keys,
        "active_keys": active_keys,
        "written": written,
    }


def latest(path=DEFAULT_PATH) -> list[dict]:
    """Return rows from the most recent observation only.

    If the file does not exist or is empty, returns [].
    """
    target = Path(path)
    if not target.exists():
        return []

    rows = []
    latest_observed = None

    try:
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    observed = row.get("observed_utc")
                    if latest_observed is None or observed == latest_observed:
                        latest_observed = observed
                        rows.append(row)
                    elif observed > latest_observed:
                        # New latest observation, discard earlier rows
                        latest_observed = observed
                        rows = [row]
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    return rows


def active_keys(path=DEFAULT_PATH, *, now=None, max_age_hours=36) -> list[str]:
    """Return active tournament keys from the newest observation.

    If no observation exists, or the newest is older than max_age_hours, returns [].
    """
    rows = latest(path)
    if not rows:
        return []

    # All rows from latest() are from the same observed_utc
    row = rows[0]
    observed_utc_str = row.get("observed_utc")
    if not observed_utc_str:
        return []

    try:
        observed_utc = datetime.fromisoformat(observed_utc_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return []

    moment = now or datetime.now(timezone.utc)
    age_seconds = (moment - observed_utc).total_seconds()
    max_age_seconds = max_age_hours * 3600

    if age_seconds > max_age_seconds:
        return []

    # Return keys from rows where active is True
    return [row.get("key") for row in rows if row.get("active")]
