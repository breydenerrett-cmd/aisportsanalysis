"""Travel, rest and schedule load, derived from the schedule itself.

WHY THIS IS FREE AND NOBODY USES IT
-----------------------------------
Nothing here needs a new data source. Every park's latitude and longitude is
already stored, and the results store already knows where each club played on
each day. The distance a team flew last night, the time zones it crossed and how
many games it has played in the last week all fall straight out of that.

It goes unused because it is not on any stat page. That is the argument for
computing it: a fact that is knowable, relevant, and absent from the screens
everyone else is looking at is exactly the kind this project exists to surface.

WHAT IS ASSERTED AND WHAT IS NOT
--------------------------------
That a club flew 2,400 miles overnight and crossed three time zones is a FACT,
computed from where it actually played. That this costs it runs tonight is a
HYPOTHESIS, and one this module does not make -- it reports the load and leaves
the effect to a detector that can be tested and can fail.

Eastward travel is flagged separately because the direction is not symmetric:
flying east shortens the night against the body clock, and that asymmetry is
well established in the circadian literature even where its size in baseball is
not. The flag is a fact about direction, not a claim about magnitude.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from src.data import parks

EARTH_RADIUS_MILES = 3958.8

# Rough time-zone width in degrees of longitude. Real zone boundaries are
# political and ragged; longitude is the honest approximation and is labelled as
# one rather than dressed up as a lookup.
DEGREES_PER_ZONE = 15.0

# A trip worth mentioning. Below this the flight is a bus ride in disguise.
LONG_TRIP_MILES = 1200

# Games in a window that constitutes a heavy stretch.
DENSE_WINDOW_DAYS = 7
DENSE_GAME_COUNT = 6


class TravelError(RuntimeError):
    """Raised when travel cannot be computed."""


def great_circle_miles(a, b) -> float:
    """Distance between two (lat, lon) pairs."""
    lat1, lon1 = (math.radians(x) for x in a)
    lat2, lon2 = (math.radians(x) for x in b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return round(2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h))), 1)


def _venue_of(row, team):
    """Which park a club played in on a given row, by which side it batted."""
    if row.get("home_team") == team:
        return row.get("home_team")
    if row.get("away_team") == team:
        return row.get("home_team")
    return None


def team_schedule(store, team, as_of_date, window=DENSE_WINDOW_DAYS) -> list:
    """A club's games strictly before a date, most recent last.

    Reads only games already played, so nothing here can see tonight's result --
    the same point-in-time discipline the feature builders enforce.
    """
    cutoff = _to_date(as_of_date)
    start = cutoff - timedelta(days=window + 1)
    rows = store.values() if isinstance(store, dict) else store
    played = []
    for row in rows:
        if team not in (row.get("home_team"), row.get("away_team")):
            continue
        try:
            when = _to_date(row.get("date"))
        except TravelError:
            continue
        if start <= when < cutoff:
            played.append({"date": when.isoformat(), "venue": _venue_of(row, team),
                           "was_home": row.get("home_team") == team})
    played.sort(key=lambda r: r["date"])
    return played


def travel_load(store, team, as_of_date, tonight_venue) -> dict:
    """Distance flown into tonight's park, zones crossed, and recent density.

    Every field is None with a reason when it cannot be computed, rather than
    zero. Zero miles is a real and different statement from "we do not know
    where they were".
    """
    played = team_schedule(store, team, as_of_date)
    result = {
        "team": team, "games_last_7": len(played),
        "miles": None, "zones": None, "eastward": None,
        "last_venue": None, "days_since_last_game": None,
        "dense_stretch": len(played) >= DENSE_GAME_COUNT,
        "reason": None,
    }

    if not played:
        result["reason"] = "no games in the window to travel from"
        return result

    last = played[-1]
    result["last_venue"] = last["venue"]
    result["days_since_last_game"] = (
        _to_date(as_of_date) - _to_date(last["date"])).days

    try:
        origin = parks.coordinates(last["venue"])
        destination = parks.coordinates(tonight_venue)
    except parks.ParkError as exc:
        result["reason"] = str(exc)
        return result

    result["miles"] = great_circle_miles(origin, destination)
    # Longitude difference, not a timezone database. Named as an approximation.
    result["zones"] = round(abs(destination[1] - origin[1]) / DEGREES_PER_ZONE, 1)
    result["eastward"] = destination[1] > origin[1]
    result["long_trip"] = result["miles"] >= LONG_TRIP_MILES
    return result


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise TravelError(f"date must be ISO format, got {value!r}") from exc
