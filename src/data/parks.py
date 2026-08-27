"""MLB ballpark reference data: coordinates, roof status, and orientation.

WHAT IS AND IS NOT POPULATED HERE
---------------------------------
Coordinates are populated and are accurate to roughly the stadium footprint --
close enough for a weather lookup, which is all they are used for.

`orientation_deg` is deliberately None for every park.

That field is the compass bearing from home plate toward center field, and it
is what turns a raw wind direction into the only wind fact that affects a
baseball game: is it blowing out, in, or across? Without it, wind speed is
decorative -- you cannot tell a 15 mph gale blowing in from a 15 mph gale
blowing out, and they have opposite effects on run scoring.

It is left None rather than estimated because a wrong bearing is worse than no
bearing: it would flip the sign of a real effect and the model would confidently
apply a backwards adjustment. Filling it is a bounded, verifiable task -- see
`docs/PARK_ORIENTATION.md` for the method.

The classification machinery below is complete and tested. The moment bearings
are filled in, wind becomes a live model input with no further code changes.
"""

from __future__ import annotations

# Wind within this many degrees of the home-plate-to-center-field axis counts
# as blowing straight out or straight in. Outside it, the wind is crossing and
# has little effect on carry distance.
STRAIGHT_ARC_DEGREES = 45.0


class ParkError(ValueError):
    """Raised when a park lookup or wind classification cannot be completed."""


# team_abbrev -> park facts.
#   lat/lon        : decimal degrees, for weather lookups
#   altitude_m     : meters above sea level; matters for carry (see Coors)
#   roof           : "open", "retractable", or "fixed"
#   orientation_deg: bearing home plate -> center field, 0 = N, 90 = E.
#                    None until verified. See module docstring.
PARKS = {
    # --- AL East ---------------------------------------------------------
    "BAL": {"name": "Oriole Park at Camden Yards", "lat": 39.2839, "lon": -76.6217,
            "altitude_m": 10, "roof": "open", "orientation_deg": None},
    "BOS": {"name": "Fenway Park", "lat": 42.3467, "lon": -71.0972,
            "altitude_m": 6, "roof": "open", "orientation_deg": None},
    "NYY": {"name": "Yankee Stadium", "lat": 40.8296, "lon": -73.9262,
            "altitude_m": 16, "roof": "open", "orientation_deg": None},
    "TB":  {"name": "Tropicana Field", "lat": 27.7683, "lon": -82.6534,
            "altitude_m": 5, "roof": "fixed", "orientation_deg": None},
    "TOR": {"name": "Rogers Centre", "lat": 43.6414, "lon": -79.3894,
            "altitude_m": 91, "roof": "retractable", "orientation_deg": None},

    # --- AL Central ------------------------------------------------------
    "CWS": {"name": "Rate Field", "lat": 41.8299, "lon": -87.6338,
            "altitude_m": 180, "roof": "open", "orientation_deg": None},
    "CLE": {"name": "Progressive Field", "lat": 41.4962, "lon": -81.6852,
            "altitude_m": 200, "roof": "open", "orientation_deg": None},
    "DET": {"name": "Comerica Park", "lat": 42.3390, "lon": -83.0485,
            "altitude_m": 183, "roof": "open", "orientation_deg": None},
    "KC":  {"name": "Kauffman Stadium", "lat": 39.0517, "lon": -94.4803,
            "altitude_m": 230, "roof": "open", "orientation_deg": None},
    "MIN": {"name": "Target Field", "lat": 44.9817, "lon": -93.2776,
            "altitude_m": 254, "roof": "open", "orientation_deg": None},

    # --- AL West ---------------------------------------------------------
    "HOU": {"name": "Daikin Park", "lat": 29.7572, "lon": -95.3555,
            "altitude_m": 12, "roof": "retractable", "orientation_deg": None},
    "LAA": {"name": "Angel Stadium", "lat": 33.8003, "lon": -117.8827,
            "altitude_m": 48, "roof": "open", "orientation_deg": None},
    # The Athletics' home venue is in flux (Sacramento, pending Las Vegas).
    # Verify before trusting this row for any season after 2025.
    # MLB now lists this club as "Athletics" (abbreviation ATH) with no city
    # prefix. Home venue is in flux -- Sacramento, pending Las Vegas -- so
    # verify this row before trusting it for any season after 2025.
    "OAK": {"name": "Sutter Health Park", "lat": 38.5802, "lon": -121.5133,
            "altitude_m": 8, "roof": "open", "orientation_deg": None,
            "verify": "temporary venue; confirm before use"},
    "SEA": {"name": "T-Mobile Park", "lat": 47.5914, "lon": -122.3325,
            "altitude_m": 5, "roof": "retractable", "orientation_deg": None},
    "TEX": {"name": "Globe Life Field", "lat": 32.7473, "lon": -97.0847,
            "altitude_m": 175, "roof": "retractable", "orientation_deg": None},

    # --- NL East ---------------------------------------------------------
    "ATL": {"name": "Truist Park", "lat": 33.8907, "lon": -84.4677,
            "altitude_m": 305, "roof": "open", "orientation_deg": None},
    "MIA": {"name": "loanDepot park", "lat": 25.7781, "lon": -80.2197,
            "altitude_m": 3, "roof": "retractable", "orientation_deg": None},
    "NYM": {"name": "Citi Field", "lat": 40.7571, "lon": -73.8458,
            "altitude_m": 3, "roof": "open", "orientation_deg": None},
    "PHI": {"name": "Citizens Bank Park", "lat": 39.9061, "lon": -75.1665,
            "altitude_m": 6, "roof": "open", "orientation_deg": None},
    "WSH": {"name": "Nationals Park", "lat": 38.8730, "lon": -77.0074,
            "altitude_m": 8, "roof": "open", "orientation_deg": None},

    # --- NL Central ------------------------------------------------------
    "CHC": {"name": "Wrigley Field", "lat": 41.9484, "lon": -87.6553,
            "altitude_m": 182, "roof": "open", "orientation_deg": None},
    "CIN": {"name": "Great American Ball Park", "lat": 39.0975, "lon": -84.5069,
            "altitude_m": 149, "roof": "open", "orientation_deg": None},
    "MIL": {"name": "American Family Field", "lat": 43.0280, "lon": -87.9712,
            "altitude_m": 193, "roof": "retractable", "orientation_deg": None},
    "PIT": {"name": "PNC Park", "lat": 40.4469, "lon": -80.0057,
            "altitude_m": 223, "roof": "open", "orientation_deg": None},
    "STL": {"name": "Busch Stadium", "lat": 38.6226, "lon": -90.1928,
            "altitude_m": 141, "roof": "open", "orientation_deg": None},

    # --- NL West ---------------------------------------------------------
    "ARI": {"name": "Chase Field", "lat": 33.4455, "lon": -112.0667,
            "altitude_m": 331, "roof": "retractable", "orientation_deg": None},
    "COL": {"name": "Coors Field", "lat": 39.7559, "lon": -104.9942,
            "altitude_m": 1580, "roof": "open", "orientation_deg": None},
    "LAD": {"name": "Dodger Stadium", "lat": 34.0739, "lon": -118.2400,
            "altitude_m": 159, "roof": "open", "orientation_deg": None},
    "SD":  {"name": "Petco Park", "lat": 32.7076, "lon": -117.1570,
            "altitude_m": 4, "roof": "open", "orientation_deg": None},
    "SF":  {"name": "Oracle Park", "lat": 37.7786, "lon": -122.3893,
            "altitude_m": 3, "roof": "open", "orientation_deg": None},
}

# Teams whose roof can be closed. Wind should never be applied as a model input
# for these parks without knowing the roof state for that specific game.
ROOFED_TEAMS = frozenset(
    abbrev for abbrev, park in PARKS.items() if park["roof"] != "open"
)

# The same franchise is abbreviated differently across sources, and a mismatch
# fails silently -- the park lookup misses and weather quietly goes blank for
# that team all season. Verified against the MLB Stats API team list: it emits
# "ATH" and "AZ" where odds feeds and historical data commonly use "OAK" and
# "ARI". Every alias resolves to a canonical key in PARKS.
ALIASES = {
    "ATH": "OAK",   # Athletics -- MLB dropped the city prefix
    "AZ": "ARI",    # Arizona Diamondbacks
    "ARZ": "ARI",
    "CHW": "CWS",   # White Sox appear as both
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "KCR": "KC",
    "WAS": "WSH",
    "LOS": "LAD",
    "ANA": "LAA",
}


def canonical_team(team_abbrev: str) -> str:
    """Resolve any known abbreviation spelling to this table's canonical key."""
    if not isinstance(team_abbrev, str):
        raise ParkError(f"team abbreviation must be a string, got {team_abbrev!r}")
    key = team_abbrev.strip().upper()
    return ALIASES.get(key, key)


def get_park(team_abbrev: str) -> dict:
    """Look up a park by team abbreviation. Raises rather than returning None."""
    key = canonical_team(team_abbrev)
    if key not in PARKS:
        raise ParkError(
            f"unknown team abbreviation {team_abbrev!r}; "
            f"expected one of {', '.join(sorted(PARKS))}"
        )
    return dict(PARKS[key])


def coordinates(team_abbrev: str):
    """Return (lat, lon) for a team's home park."""
    park = get_park(team_abbrev)
    return park["lat"], park["lon"]


def has_roof(team_abbrev: str) -> bool:
    """True if the park can be enclosed, making wind potentially irrelevant."""
    return get_park(team_abbrev)["roof"] != "open"


def orientation(team_abbrev: str):
    """Bearing from home plate toward center field, or None if unverified."""
    return get_park(team_abbrev)["orientation_deg"]


def parks_missing_orientation():
    """Every park still lacking a verified bearing. Drives the coverage report."""
    return sorted(k for k, v in PARKS.items() if v["orientation_deg"] is None)


# ---------------------------------------------------------------------------
# Wind classification
# ---------------------------------------------------------------------------

def classify_wind(park_orientation_deg, wind_from_deg,
                  arc: float = STRAIGHT_ARC_DEGREES):
    """Classify wind relative to the park axis as 'out', 'in', or 'cross'.

    Args:
        park_orientation_deg: bearing home plate -> center field (0 = N).
        wind_from_deg: meteorological wind direction, i.e. the direction the
            wind is coming FROM. This is what weather APIs report, and getting
            it backwards inverts every classification.
        arc: half-width of the cone counted as straight out or straight in.

    Returns:
        "out"   -- wind blows from home plate toward center field, helping carry
        "in"    -- wind blows from center field toward home plate, killing carry
        "cross" -- neither, and largely irrelevant to run scoring
        None    -- park orientation is unverified, so no claim can be made

    Returning None rather than guessing is the entire point. An unverified park
    yields no wind signal instead of a coin-flip one.
    """
    if park_orientation_deg is None:
        return None
    park_deg = _validate_bearing(park_orientation_deg, "park orientation")
    wind_deg = _validate_bearing(wind_from_deg, "wind direction")
    if not (0.0 < arc <= 90.0):
        raise ParkError(f"arc must be in (0, 90], got {arc!r}")

    # Wind FROM home plate's side blows out toward center field. That means the
    # wind's origin bearing sits opposite the park axis.
    blowing_out_from = (park_deg + 180.0) % 360.0

    if _angular_distance(wind_deg, blowing_out_from) <= arc:
        return "out"
    if _angular_distance(wind_deg, park_deg) <= arc:
        return "in"
    return "cross"


def wind_effect(team_abbrev: str, wind_from_deg, wind_mph=None,
                roof_closed=None):
    """Full wind read for a game, including roof handling.

    Returns a dict with `direction`, `applicable`, and `reason`. When wind
    cannot be applied -- unverified park, closed roof, unknown roof state --
    `applicable` is False and `reason` says why, so a report can explain the
    blank instead of silently dropping the field.
    """
    park = get_park(team_abbrev)

    if park["roof"] != "open":
        if roof_closed is None:
            return {"direction": None, "applicable": False,
                    "reason": f"{park['name']} has a {park['roof']} roof and the "
                              "roof state for this game is unknown"}
        if roof_closed:
            return {"direction": None, "applicable": False,
                    "reason": f"roof closed at {park['name']}"}

    if park["orientation_deg"] is None:
        return {"direction": None, "applicable": False,
                "reason": f"orientation for {park['name']} is not verified; "
                          "wind cannot be classified"}

    direction = classify_wind(park["orientation_deg"], wind_from_deg)
    return {
        "direction": direction,
        "applicable": direction in ("out", "in"),
        "reason": "crosswind has little effect on carry"
                  if direction == "cross" else f"wind blowing {direction}",
        "wind_mph": wind_mph,
    }


def _angular_distance(a: float, b: float) -> float:
    """Smallest angle between two bearings, always in [0, 180]."""
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _validate_bearing(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParkError(f"{label} must be numeric, got {value!r}")
    v = float(value)
    if v != v:
        raise ParkError(f"{label} must not be NaN")
    if not (0.0 <= v <= 360.0):
        raise ParkError(f"{label} must be between 0 and 360 degrees, got {v!r}")
    return v % 360.0
