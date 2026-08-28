"""Starting lineups, batter handedness, and pitcher platoon splits.

WHY LINEUPS ARE THE UNLOCK
--------------------------
Every signal in this project so far treats a club as one number. A lineup is the
club actually playing tonight, and it is where the matchup decomposition the
project is being built for becomes computable:

    "a starter allowing materially higher wOBA to left-handed hitters, against a
     lineup carrying six left-handed plate appearances"

Neither half of that sentence is available from team-level data. Both are here.

A LEAKAGE WARNING THAT MATTERS MORE THAN IT LOOKS
-------------------------------------------------
The splits endpoint returns SEASON-TO-DATE numbers. Fetched today, that is
exactly point-in-time and is safe. Fetched for a game in June while it is
August, it is the pitcher's *whole season* -- including the starts that had not
happened yet -- which is the single most effective way to build a backtest that
looks brilliant and loses money.

So every split record carries `as_of`, and `assert_point_in_time` refuses to hand
one to an evaluation of an earlier date. Historical splits must be reconstructed
from game logs instead, which is slower and correct.

WHY HANDEDNESS IS CACHED SEPARATELY
-----------------------------------
A hitter's handedness does not change during a season and a lineup does not
change during a night, so handedness is a small stable lookup while lineups are
volatile. Caching them together would mean re-fetching biographical data every
time a lineup is posted.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from src.paths import historical_path
from src.providers import mlb

DEFAULT_HANDEDNESS = historical_path("handedness.json")
DEFAULT_SPLITS = historical_path("pitcher_splits.json")

# Below this many batters faced a platoon split is not a split, it is a week.
MIN_BATTERS_FOR_SPLIT = 60

VS_LEFT, VS_RIGHT = "vs Left", "vs Right"
HOME_GAMES, AWAY_GAMES = "Home Games", "Away Games"

# League-average OPS allowed, used as the baseline a split is judged against.
# Stated here rather than computed per call so the number is visible and can be
# corrected in one place when the run environment moves.
LEAGUE_OPS_ALLOWED = 0.715


class LineupError(RuntimeError):
    """Raised when lineup or split data cannot be built or is used unsafely."""


# ---------------------------------------------------------------------------
# Lineups
# ---------------------------------------------------------------------------

def fetch_lineups(game_date, timeout=20) -> dict:
    """Posted lineups for one date, keyed by game_pk.

    An unposted lineup is absent rather than empty. Lineups drop a few hours
    before first pitch, so most of a day's slate has none for most of the day,
    and that is a normal state rather than a failure.
    """
    payload = mlb._get_json(
        "schedule", {"sportId": 1, "date": mlb._validate_date(game_date),
                     "hydrate": "lineups,probablePitcher"}, timeout=timeout)
    out = {}
    for entry in payload.get("dates") or []:
        for game in entry.get("games") or []:
            lineups = game.get("lineups") or {}
            away = lineups.get("awayPlayers") or []
            home = lineups.get("homePlayers") or []
            if not away and not home:
                continue
            out[game.get("gamePk")] = {
                "game_pk": game.get("gamePk"),
                "posted_at": datetime.now(timezone.utc).isoformat(),
                "away": [_player(p, order) for order, p in enumerate(away, 1)],
                "home": [_player(p, order) for order, p in enumerate(home, 1)],
            }
    return out


def _player(player, order) -> dict:
    return {
        "order": order,
        "person_id": player.get("id"),
        "name": player.get("fullName"),
        "position": ((player.get("primaryPosition") or {}).get("abbreviation")),
    }


# ---------------------------------------------------------------------------
# Handedness
# ---------------------------------------------------------------------------

def fetch_handedness(person_ids, cache_path=DEFAULT_HANDEDNESS, timeout=20) -> dict:
    """Bat side per player, cached. Switch hitters are 'S' and stay 'S'.

    A switch hitter is NOT resolved to the platoon-advantaged side here. That
    resolution depends on the pitcher and belongs to whoever is asking, and
    baking it in would quietly turn a fact into an assumption.
    """
    cache = _read_json(cache_path, {})
    missing = [str(p) for p in person_ids if p and str(p) not in cache]
    for chunk in _chunks(missing, 40):
        payload = mlb._get_json("people", {"personIds": ",".join(chunk)},
                                timeout=timeout)
        for person in payload.get("people") or []:
            cache[str(person.get("id"))] = {
                "name": person.get("fullName"),
                "bats": (person.get("batSide") or {}).get("code"),
                "throws": (person.get("pitchHand") or {}).get("code"),
            }
    if missing:
        _write_json(cache_path, cache)
    return cache


def lineup_handedness(lineup, handedness) -> dict:
    """How many left, right and switch hitters are in a posted lineup."""
    counts = {"L": 0, "R": 0, "S": 0, "unknown": 0}
    for slot in lineup or []:
        bats = (handedness.get(str(slot.get("person_id"))) or {}).get("bats")
        if bats in counts:
            counts[bats] += 1
        else:
            counts["unknown"] += 1
    counts["known"] = len(lineup or []) - counts["unknown"]
    return counts


def platoon_advantage_share(lineup, handedness, pitcher_throws) -> dict:
    """Share of the lineup with the platoon advantage against this starter.

    A switch hitter always has the advantage, which is the entire point of being
    one. Counting him as neutral would understate every lineup that carries them.
    """
    if pitcher_throws not in ("L", "R"):
        return {"share": None, "reason": "the starter's throwing hand is unknown"}
    counts = lineup_handedness(lineup, handedness)
    if not counts["known"]:
        return {"share": None, "reason": "no handedness known for this lineup"}
    opposite = "R" if pitcher_throws == "L" else "L"
    advantaged = counts[opposite] + counts["S"]
    return {
        "share": round(advantaged / counts["known"], 3),
        "advantaged": advantaged,
        "known": counts["known"],
        "counts": counts,
        "reason": None,
    }


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _read_json(path, default):
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LineupError(f"{target} is not valid JSON") from exc


def _write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Pitcher splits
# ---------------------------------------------------------------------------

def fetch_pitcher_splits(person_id, season, cache_path=DEFAULT_SPLITS,
                         timeout=20, refresh=False) -> dict:
    """Season-to-date platoon and home/road splits for one pitcher.

    Stamped with `as_of` because these are season-to-date: safe as a
    point-in-time read today, and a straight leak if applied to a game earlier
    in the same season. `assert_point_in_time` enforces that.
    """
    cache = _read_json(cache_path, {})
    key = f"{person_id}:{season}"
    if key in cache and not refresh:
        return cache[key]

    payload = mlb._get_json(
        "people/%s/stats" % person_id,
        {"stats": "statSplits", "sitCodes": "vl,vr,h,a",
         "group": "pitching", "season": season, "sportId": 1},
        timeout=timeout)

    # The endpoint returns several rows per description -- one per game type
    # plus a total. The largest batters-faced row is the season total, and
    # picking it by size avoids depending on undocumented row ordering.
    best = {}
    for block in payload.get("stats") or []:
        for split in block.get("splits") or []:
            description = (split.get("split") or {}).get("description")
            stat = split.get("stat") or {}
            faced = stat.get("battersFaced") or 0
            if description and faced >= (best.get(description, {})
                                         .get("batters_faced") or 0):
                best[description] = _split_row(stat)

    record = {"person_id": person_id, "season": str(season),
              "as_of": datetime.now(timezone.utc).isoformat(),
              "splits": best}
    cache[key] = record
    _write_json(cache_path, cache)
    return record


def _split_row(stat) -> dict:
    return {
        "batters_faced": stat.get("battersFaced"),
        "innings": stat.get("inningsPitched"),
        "avg": _float(stat.get("avg")),
        "ops": _float(stat.get("ops")),
        "strikeouts": stat.get("strikeOuts"),
        "walks": stat.get("baseOnBalls"),
        "home_runs": stat.get("homeRuns"),
    }


def _float(value):
    if value in (None, "", "-.--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def assert_point_in_time(record, as_of_date) -> None:
    """Refuse to use a season-to-date split for an earlier date.

    The failure this prevents is the most effective backtest-inflating bug there
    is: attaching a pitcher's whole-season platoon split to a game in June tells
    the model how he went on to perform. It is a hard error rather than a warning
    because a warning in a batch job is a line nobody reads.
    """
    stamped = record.get("as_of")
    if not stamped:
        raise LineupError("split record carries no as_of stamp and cannot be "
                          "checked for leakage")
    fetched = datetime.fromisoformat(stamped).date()
    target = as_of_date if isinstance(as_of_date, date) else date.fromisoformat(
        str(as_of_date))
    if target < fetched:
        raise LineupError(
            f"split was fetched on {fetched} and covers the whole season to that "
            f"date; using it for a game on {target} would leak results that had "
            "not happened yet. Reconstruct the split from game logs instead.")


def platoon_split(record) -> dict:
    """The vs-LHB minus vs-RHB gap, gated on sample.

    Returns `usable: False` with a reason rather than a number when either side
    is thin. Sixty batters faced is roughly two weeks; below that a "split" is a
    handful of at-bats wearing the costume of a tendency.
    """
    splits = (record or {}).get("splits") or {}
    left, right = splits.get(VS_LEFT) or {}, splits.get(VS_RIGHT) or {}
    left_faced = left.get("batters_faced") or 0
    right_faced = right.get("batters_faced") or 0

    if left_faced < MIN_BATTERS_FOR_SPLIT or right_faced < MIN_BATTERS_FOR_SPLIT:
        return {"usable": False,
                "reason": (f"only {left_faced} batters faced left-handed and "
                           f"{right_faced} right-handed; a platoon split needs "
                           f"at least {MIN_BATTERS_FOR_SPLIT} each side"),
                "vs_left_faced": left_faced, "vs_right_faced": right_faced}

    if left.get("ops") is None or right.get("ops") is None:
        return {"usable": False, "reason": "OPS allowed missing on one side"}

    gap = round(left["ops"] - right["ops"], 4)
    return {
        "usable": True,
        "vs_left_ops": left["ops"], "vs_right_ops": right["ops"],
        "gap": gap,
        "weaker_against": "L" if gap > 0 else "R",
        "vs_left_faced": left_faced, "vs_right_faced": right_faced,
        "reason": None,
    }


# ---------------------------------------------------------------------------
# Matchup history
# ---------------------------------------------------------------------------

def batter_vs_pitcher(batter_id, pitcher_id, timeout=20) -> dict:
    """Career line for one hitter against one pitcher.

    Returned with the at-bat count attached and never without it. The number is
    only interpretable next to its sample, and separating them is how a
    4-for-8 ends up on a screen looking like a read.
    """
    payload = mlb._get_json(
        f"people/{batter_id}/stats",
        {"stats": "vsPlayer", "opposingPlayerId": pitcher_id,
         "group": "hitting", "sportId": 1}, timeout=timeout)
    for block in payload.get("stats") or []:
        if (block.get("type") or {}).get("displayName") != "vsPlayerTotal":
            continue
        for split in block.get("splits") or []:
            stat = split.get("stat") or {}
            return {
                "at_bats": stat.get("atBats") or 0,
                "hits": stat.get("hits") or 0,
                "home_runs": stat.get("homeRuns") or 0,
                "strikeouts": stat.get("strikeOuts") or 0,
                "walks": stat.get("baseOnBalls") or 0,
                "avg": _float(stat.get("avg")),
                "ops": _float(stat.get("ops")),
            }
    return {"at_bats": 0, "hits": 0, "home_runs": 0, "strikeouts": 0,
            "walks": 0, "avg": None, "ops": None}


def lineup_vs_pitcher(lineup, pitcher_id, handedness=None, timeout=20) -> dict:
    """Every posted hitter against tonight's starter, plus the aggregate.

    The aggregate is the number worth reading: nine individually meaningless
    samples add up to one that is occasionally not, and the combined at-bat count
    is reported so the reader can see which case they are in.
    """
    entries, total_ab, total_hits, total_hr, total_k = [], 0, 0, 0, 0
    for slot in lineup or []:
        person_id = slot.get("person_id")
        if not person_id or not pitcher_id:
            continue
        try:
            line = batter_vs_pitcher(person_id, pitcher_id, timeout=timeout)
        except mlb.MLBError:
            continue
        entry = dict(line, name=slot.get("name"), order=slot.get("order"),
                     person_id=person_id)
        if handedness:
            entry["bats"] = (handedness.get(str(person_id)) or {}).get("bats")
        entries.append(entry)
        total_ab += line["at_bats"]
        total_hits += line["hits"]
        total_hr += line["home_runs"]
        total_k += line["strikeouts"]

    return {
        "batters": entries,
        "total_at_bats": total_ab,
        "total_hits": total_hits,
        "total_home_runs": total_hr,
        "total_strikeouts": total_k,
        "aggregate_avg": round(total_hits / total_ab, 3) if total_ab else None,
        # Stated rather than left for the reader to work out. Even summed across
        # a whole lineup this is usually too small to mean anything.
        "usable": total_ab >= MIN_LINEUP_AT_BATS,
        "reason": None if total_ab >= MIN_LINEUP_AT_BATS else (
            f"the whole lineup has only {total_ab} career at-bats against him; "
            f"a read needs at least {MIN_LINEUP_AT_BATS}"),
    }


# Even aggregated over nine hitters, matchup history is usually thin. This is
# the level at which the combined line stops being an anecdote.
MIN_LINEUP_AT_BATS = 60
