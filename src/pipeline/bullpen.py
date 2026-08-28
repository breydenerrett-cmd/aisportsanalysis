"""Bullpen workload and availability, from boxscores.

WHY THIS IS WORTH ITS OWN PIPELINE
----------------------------------
Bullpens are where the full-game market and the first-five market diverge, and
they are the least-modelled unit in baseball betting. A starter's line is on
every screen; who threw 28 pitches last night and is therefore unavailable is on
none of them.

That asymmetry is the whole opportunity. The market prices bullpens in aggregate
-- "their pen is good" -- while availability is a nightly, knowable fact that
changes the actual quality of the unit taking the ball tonight by a lot.

WHY BOXSCORES AND NOT SEASON STATS
----------------------------------
Season bullpen ERA answers "is this pen good". It cannot answer "is their closer
available tonight", which is the question that moves a game. Only appearance-level
data does, so this reads boxscores and keeps a per-appearance log.

WHY AVAILABILITY IS INFERRED AND SAID TO BE
-------------------------------------------
Nobody publishes an availability list. What is published is who pitched, when,
and how much -- and the usage conventions that follow from it are strong and well
known: three straight days is close to unheard of, back-to-back after a heavy
outing is rare, a 40-pitch appearance usually costs the next day.

So availability here is a MODELLED LIKELIHOOD with the evidence attached, never a
fact. Each reliever carries the reason for his rating, so a reader can disagree
with the inference while still seeing the underlying usage.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from src.paths import historical_path
from src.providers import mlb

DEFAULT_LOG = historical_path("bullpen_log.jsonl")

# Usage conventions. Pre-registered from how bullpens are actually run, not
# fitted to anything.
HEAVY_OUTING_PITCHES = 30      # past this, a next-day appearance is unusual
BACK_TO_BACK_PITCHES = 20      # a light outing rarely costs the next day
MAX_CONSECUTIVE_DAYS = 3       # three straight is close to unheard of
WORKLOAD_WINDOW_DAYS = 7       # the horizon a manager actually thinks about

AVAILABLE = "available"
LIKELY_UNAVAILABLE = "likely_unavailable"
QUESTIONABLE = "questionable"


class BullpenError(RuntimeError):
    """Raised when bullpen data cannot be built or read."""


def _innings_to_float(value) -> float:
    """Innings-pitched thirds. '5.1' is five and one third, not five point one."""
    if value in (None, ""):
        return 0.0
    text = str(value).strip()
    if "." not in text:
        return float(text)
    whole, frac = text.split(".", 1)
    if frac not in ("0", "1", "2"):
        raise BullpenError(
            f"innings {value!r} has an impossible fraction; innings are recorded "
            "in thirds, so only .0, .1 and .2 are valid")
    return float(whole) + int(frac) / 3.0


def appearances_from_boxscore(box, game_date, game_pk) -> list:
    """Every pitcher who appeared in one game, with his workload."""
    out = []
    for side in ("away", "home"):
        team = (box.get("teams") or {}).get(side) or {}
        abbrev = ((team.get("team") or {}).get("abbreviation")
                  or (team.get("team") or {}).get("triCode"))
        players = team.get("players") or {}
        for person_id in team.get("pitchers") or []:
            player = players.get(f"ID{person_id}") or {}
            stats = ((player.get("stats") or {}).get("pitching")) or {}
            if not stats:
                continue
            out.append({
                "date": game_date,
                "game_pk": game_pk,
                "team": abbrev,
                "person_id": person_id,
                "name": (player.get("person") or {}).get("fullName"),
                "started": bool(stats.get("gamesStarted")),
                "innings": round(_innings_to_float(stats.get("inningsPitched")), 3),
                # Pitch count is the number a manager actually uses. Absent for
                # some older games, left None rather than guessed from innings.
                "pitches": stats.get("numberOfPitches") or stats.get("pitchesThrown"),
                "batters_faced": stats.get("battersFaced"),
                "earned_runs": stats.get("earnedRuns"),
                "strikeouts": stats.get("strikeOuts"),
                "walks": stats.get("baseOnBalls"),
                "hits": stats.get("hits"),
            })
    return out


def build_log(start_date, end_date, path=DEFAULT_LOG, resume=True,
              on_date=None, timeout=20) -> dict:
    """Fetch boxscores across a date range and append appearances.

    Resumable by date: a date already in the log is skipped, so an interrupted
    build continues rather than refetching.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    have = {row["date"] for row in read_log(path)} if resume else set()

    start, end = _to_date(start_date), _to_date(end_date)
    report = {"dates": 0, "skipped": 0, "games": 0, "appearances": 0, "failed": 0}
    day = start
    while day <= end:
        iso = day.isoformat()
        if iso in have:
            report["skipped"] += 1
            day += timedelta(days=1)
            continue
        try:
            games = mlb.fetch_schedule(iso, timeout=timeout)
        except mlb.MLBError:
            report["failed"] += 1
            day += timedelta(days=1)
            continue

        rows = []
        for game in games:
            pk = game.get("gamePk")
            if not pk or (game.get("status") or {}).get("codedGameState") != "F":
                continue
            try:
                box = mlb._get_json(f"game/{pk}/boxscore", {}, timeout=timeout)
            except mlb.MLBError:
                report["failed"] += 1
                continue
            rows.extend(appearances_from_boxscore(box, iso, pk))
            report["games"] += 1

        with target.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            # An explicit marker for a date with no games, so a genuine off-day is
            # distinguishable from a date that was never fetched.
            if not rows:
                handle.write(json.dumps({"date": iso, "empty": True}) + "\n")
        report["appearances"] += len(rows)
        report["dates"] += 1
        if on_date:
            on_date({"date": iso, "appearances": len(rows)})
        day += timedelta(days=1)

    report["path"] = str(target)
    return report


def read_log(path=DEFAULT_LOG) -> list:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise BullpenError(f"{target}:{number} is not valid JSON") from exc
    return rows


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


# ---------------------------------------------------------------------------
# Workload and availability
# ---------------------------------------------------------------------------

def team_workload(log, team, as_of_date, window=WORKLOAD_WINDOW_DAYS) -> dict:
    """One club's relief workload strictly before a date.

    Starters are excluded from the workload totals. A starter's outing says
    nothing about who is available out of the pen tonight, and folding him in
    would swamp the numbers that matter.
    """
    cutoff = _to_date(as_of_date)
    window_start = cutoff - timedelta(days=window)
    relievers = {}

    for row in log:
        if row.get("empty") or row.get("team") != team or row.get("started"):
            continue
        try:
            appeared = _to_date(row["date"])
        except (BullpenError, KeyError, ValueError):
            continue
        if not (window_start <= appeared < cutoff):
            continue
        entry = relievers.setdefault(row["person_id"], {
            "person_id": row["person_id"], "name": row.get("name"),
            "appearances": [], "innings": 0.0, "pitches": 0, "pitches_known": True,
        })
        entry["appearances"].append({
            "date": row["date"],
            "days_ago": (cutoff - appeared).days,
            "innings": row.get("innings") or 0.0,
            "pitches": row.get("pitches"),
        })
        entry["innings"] += row.get("innings") or 0.0
        if row.get("pitches") is None:
            entry["pitches_known"] = False
        else:
            entry["pitches"] += row["pitches"]

    for entry in relievers.values():
        entry["appearances"].sort(key=lambda a: a["days_ago"])
        entry["innings"] = round(entry["innings"], 2)
        entry.update(availability(entry["appearances"]))

    return {
        "team": team,
        "as_of": cutoff.isoformat(),
        "window_days": window,
        "relievers": sorted(relievers.values(), key=lambda r: -r["innings"]),
        "total_innings": round(sum(r["innings"] for r in relievers.values()), 2),
        "reliever_count": len(relievers),
    }


def availability(appearances) -> dict:
    """Modelled likelihood a reliever is available, with the reason attached.

    Never stated as a fact. Nobody publishes an availability list, so this is an
    inference from usage conventions -- and the reader gets the usage as well as
    the verdict so they can disagree with the inference.
    """
    if not appearances:
        return {"availability": AVAILABLE,
                "availability_reason": "has not pitched in the window"}

    yesterday = [a for a in appearances if a["days_ago"] == 1]
    two_days = [a for a in appearances if a["days_ago"] == 2]
    three_days = [a for a in appearances if a["days_ago"] == 3]

    consecutive = 0
    for day in (1, 2, 3):
        if any(a["days_ago"] == day for a in appearances):
            consecutive += 1
        else:
            break

    if consecutive >= MAX_CONSECUTIVE_DAYS:
        return {"availability": LIKELY_UNAVAILABLE,
                "availability_reason": (
                    f"pitched {consecutive} days in a row; a fourth straight is "
                    "close to unheard of")}

    if yesterday:
        pitches = yesterday[0].get("pitches")
        if pitches is None:
            return {"availability": QUESTIONABLE,
                    "availability_reason": (
                        "pitched yesterday; pitch count unavailable, so the "
                        "usual back-to-back read cannot be applied")}
        if pitches >= HEAVY_OUTING_PITCHES:
            return {"availability": LIKELY_UNAVAILABLE,
                    "availability_reason": (
                        f"threw {pitches} pitches yesterday; a next-day "
                        "appearance after that is unusual")}
        if two_days and pitches >= BACK_TO_BACK_PITCHES:
            return {"availability": QUESTIONABLE,
                    "availability_reason": (
                        f"pitched each of the last two days, {pitches} pitches "
                        "yesterday")}
        return {"availability": AVAILABLE,
                "availability_reason": (
                    f"pitched yesterday but only {pitches} pitches")}

    if two_days and three_days:
        return {"availability": AVAILABLE,
                "availability_reason": "rested yesterday after two straight days"}

    return {"availability": AVAILABLE,
            "availability_reason": f"last pitched {appearances[0]['days_ago']} days ago"}
