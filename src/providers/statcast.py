"""Baseball Savant arsenal leaderboards: pitch mix, and who can hit what.

WHY THE LEADERBOARDS AND NOT RAW PITCH DATA
-------------------------------------------
Raw Statcast is one row per pitch -- roughly 700,000 rows a season across 119
columns. Downloading and storing that to answer "what does he throw and who
handles it" is a lot of machinery for two numbers.

The arsenal leaderboards answer exactly those questions in two small requests:
about a thousand rows on the pitcher side, another thousand on the batter side,
each keyed by player and pitch type. Usage share, whiff rate and wOBA against,
per pitch, per player.

WHAT THIS MAKES POSSIBLE
------------------------
The matchup decomposition the project is built for, at pitch level:

    a starter who throws sliders half the time, against a lineup whose hitters
    are collectively helpless against sliders

Neither side of that is on a stat page anyone is reading, and both sides are one
join away once this data is on disk.

A LEAKAGE WARNING, SAME AS THE SPLITS
-------------------------------------
These are SEASON-TO-DATE aggregates. Fetched today they are point-in-time and
safe; applied to a game in June they include pitches thrown in July. Every
record is stamped with `as_of` for exactly that reason, and historical work must
rebuild these from pitch-level data rather than reusing today's file.

ON COLUMN SELECTION
-------------------
The full leaderboard carries twenty columns. Only the ones a detector actually
uses are kept, with provenance, rather than storing everything on the theory
that it might be handy -- an unused column is a column nobody validates.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.paths import historical_path

HOST = "https://baseballsavant.mlb.com"
# Savant rejects the stdlib default agent.
USER_AGENT = "Mozilla/5.0 (compatible; aisportsanalysis/0.1)"
DEFAULT_TIMEOUT = 60

DEFAULT_STORE = historical_path("arsenals")

# Minimum pitches for a leaderboard row. Savant's own floor; below it a "usage
# share" is a handful of pitches.
MIN_PITCHES = 50

PITCHER, BATTER = "pitcher", "batter"

# The columns a detector uses, and only those.
KEEP = ("player_id", "team_name_alt", "pitch_type", "pitch_name", "pitches",
        "pitch_usage", "pa", "ba", "slg", "woba", "est_woba", "whiff_percent",
        "k_percent", "hard_hit_percent")


class StatcastError(RuntimeError):
    """Raised when Savant cannot be reached or returns something unusable."""


def fetch_arsenal(season, side=PITCHER, min_pitches=MIN_PITCHES,
                  timeout=DEFAULT_TIMEOUT) -> list:
    """One season's arsenal leaderboard, as a list of dicts."""
    if side not in (PITCHER, BATTER):
        raise StatcastError(f"side must be pitcher or batter, got {side!r}")
    query = urllib.parse.urlencode({
        "type": side, "pitchType": "", "year": str(season), "team": "",
        "min": str(min_pitches), "csv": "true"})
    url = f"{HOST}/leaderboard/pitch-arsenal-stats?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # utf-8-sig, because the byte-order mark otherwise becomes part of
            # the first column NAME and silently shifts every field by one.
            raw = response.read().decode("utf-8-sig", "replace")
    except urllib.error.HTTPError as exc:
        raise StatcastError(f"Savant returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise StatcastError(f"could not reach Savant: {exc.reason}") from None

    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows:
        raise StatcastError(f"Savant returned no {side} rows for {season}")

    out = []
    for row in rows:
        record = {"name": row.get("last_name, first_name")}
        for column in KEEP:
            record[column] = _number(row.get(column))
        record["player_id"] = str(row.get("player_id") or "").strip()
        record["team"] = row.get("team_name_alt")
        record["pitch_type"] = row.get("pitch_type")
        record["pitch_name"] = row.get("pitch_name")
        out.append(record)
    return out


def _number(value):
    """Numbers as numbers, blanks as None. Never zero for missing."""
    if value in (None, "", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def build(season, store=DEFAULT_STORE, timeout=DEFAULT_TIMEOUT) -> dict:
    """Fetch both sides for a season and write them to disk with provenance."""
    target = Path(store)
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    report = {"season": str(season), "as_of": stamp, "store": str(target)}

    for side in (PITCHER, BATTER):
        rows = fetch_arsenal(season, side=side, timeout=timeout)
        payload = {"season": str(season), "side": side, "as_of": stamp,
                   "source": "baseballsavant pitch-arsenal-stats",
                   "min_pitches": MIN_PITCHES, "rows": rows}
        path = target / f"{side}_{season}.json"
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        report[f"{side}_rows"] = len(rows)
    return report


def read(season, side=PITCHER, store=DEFAULT_STORE) -> dict:
    """Load a stored leaderboard. Missing file is empty, not an error."""
    path = Path(store) / f"{side}_{season}.json"
    if not path.exists():
        return {"rows": [], "as_of": None, "season": str(season), "side": side}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StatcastError(f"{path} is not valid JSON") from exc


def by_player(payload) -> dict:
    """Group leaderboard rows by player id, sorted by usage share descending."""
    grouped = {}
    for row in payload.get("rows") or []:
        grouped.setdefault(str(row.get("player_id")), []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: -(r.get("pitch_usage") or 0))
    return grouped
