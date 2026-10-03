"""The stadiums NFL games are played in: coordinates and clocks, for travel features.

CITATION
--------
Coordinates are each stadium's latitude and longitude as printed in the infobox of its
Wikipedia article, rounded to four decimals (about 10 metres), entered by hand on
2026-10-03. They were NOT downloaded: the only network source this layer is allowed is
nflverse. The use here is distances of tens to thousands of miles, so a few hundred metres
would not matter; what would matter is a sign or digit slip, and
`tests/test_datasvc_nfl_venues.py` checks the table against well-known inter-city
distances (Kansas City to Seattle about 1,500 miles, New York to Los Angeles about 2,450)
and that every venue is in the right country and zone.

Keys are the schedule file's `stadium_id`. An id is stable across sponsor renamings
(`BUF00` is New Era Field and Highmark Stadium), so one row per id, the current name.
`MUN01` ("FC Bayern Munich Stadium", 2026) and `GER00` ("Allianz Arena", 2022 and 2024) are
the same building under two ids.

`zone` is a key of `timeutil.ZONES`.

COVERAGE
--------
Every stadium id that appears in `games.csv` for 2021 to 2026 (41 ids). A game at an id that
is not here has no travel figures; the features list that as missing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class Venue:
    stadium_id: str
    name: str
    city: str
    country: str
    lat: float
    lon: float
    zone: str


def _v(stadium_id, name, city, country, lat, lon, zone) -> Venue:
    return Venue(stadium_id, name, city, country, lat, lon, zone)


VENUES: Dict[str, Venue] = {v.stadium_id: v for v in (
    _v("ATL97", "Mercedes-Benz Stadium", "Atlanta", "US", 33.7554, -84.4010, "us_eastern"),
    _v("BAL00", "M&T Bank Stadium", "Baltimore", "US", 39.2780, -76.6227, "us_eastern"),
    _v("BOS00", "Gillette Stadium", "Foxborough", "US", 42.0909, -71.2643, "us_eastern"),
    _v("BUF00", "Highmark Stadium", "Orchard Park", "US", 42.7738, -78.7870, "us_eastern"),
    _v("CAR00", "Bank of America Stadium", "Charlotte", "US", 35.2258, -80.8528, "us_eastern"),
    _v("CHI98", "Soldier Field", "Chicago", "US", 41.8623, -87.6167, "us_central"),
    _v("CIN00", "Paycor Stadium", "Cincinnati", "US", 39.0954, -84.5160, "us_eastern"),
    _v("CLE00", "Huntington Bank Field", "Cleveland", "US", 41.5061, -81.6995, "us_eastern"),
    _v("DAL00", "AT&T Stadium", "Arlington", "US", 32.7473, -97.0945, "us_central"),
    _v("DEN00", "Empower Field at Mile High", "Denver", "US", 39.7439, -105.0201, "us_mountain"),
    _v("DET00", "Ford Field", "Detroit", "US", 42.3400, -83.0456, "us_eastern"),
    _v("FRA00", "Deutsche Bank Park", "Frankfurt", "DE", 50.0686, 8.6455, "central_europe"),
    _v("GER00", "Allianz Arena", "Munich", "DE", 48.2188, 11.6247, "central_europe"),
    _v("GNB00", "Lambeau Field", "Green Bay", "US", 44.5013, -88.0622, "us_central"),
    _v("HOU00", "NRG Stadium", "Houston", "US", 29.6847, -95.4107, "us_central"),
    _v("IND00", "Lucas Oil Stadium", "Indianapolis", "US", 39.7601, -86.1639, "us_eastern"),
    _v("JAX00", "EverBank Stadium", "Jacksonville", "US", 30.3239, -81.6373, "us_eastern"),
    _v("KAN00", "GEHA Field at Arrowhead Stadium", "Kansas City", "US", 39.0489, -94.4839, "us_central"),
    _v("LAX01", "SoFi Stadium", "Inglewood", "US", 33.9535, -118.3392, "us_pacific"),
    _v("LON00", "Wembley Stadium", "London", "GB", 51.5560, -0.2796, "uk"),
    _v("LON02", "Tottenham Hotspur Stadium", "London", "GB", 51.6043, -0.0664, "uk"),
    _v("MAD01", "Santiago Bernabeu Stadium", "Madrid", "ES", 40.4531, -3.6883, "central_europe"),
    _v("MEL00", "Melbourne Cricket Ground", "Melbourne", "AU", -37.8200, 144.9834, "au_victoria"),
    _v("MEX00", "Estadio Azteca", "Mexico City", "MX", 19.3029, -99.1505, "mexico"),
    _v("MIA00", "Hard Rock Stadium", "Miami Gardens", "US", 25.9580, -80.2389, "us_eastern"),
    _v("MIN01", "U.S. Bank Stadium", "Minneapolis", "US", 44.9738, -93.2575, "us_central"),
    _v("MUN01", "Allianz Arena", "Munich", "DE", 48.2188, 11.6247, "central_europe"),
    _v("NAS00", "Nissan Stadium", "Nashville", "US", 36.1665, -86.7713, "us_central"),
    _v("NOR00", "Caesars Superdome", "New Orleans", "US", 29.9511, -90.0812, "us_central"),
    _v("NYC01", "MetLife Stadium", "East Rutherford", "US", 40.8135, -74.0745, "us_eastern"),
    _v("PAR00", "Stade de France", "Saint-Denis", "FR", 48.9245, 2.3601, "central_europe"),
    _v("PHI00", "Lincoln Financial Field", "Philadelphia", "US", 39.9008, -75.1675, "us_eastern"),
    _v("PHO00", "State Farm Stadium", "Glendale", "US", 33.5276, -112.2626, "us_arizona"),
    _v("PIT00", "Acrisure Stadium", "Pittsburgh", "US", 40.4468, -80.0158, "us_eastern"),
    _v("RIO00", "Maracana Stadium", "Rio de Janeiro", "BR", -22.9121, -43.2302, "brazil"),
    _v("SAO00", "Arena Corinthians", "Sao Paulo", "BR", -23.5453, -46.4742, "brazil"),
    _v("SEA00", "Lumen Field", "Seattle", "US", 47.5952, -122.3316, "us_pacific"),
    _v("SFO01", "Levi's Stadium", "Santa Clara", "US", 37.4033, -121.9694, "us_pacific"),
    _v("TAM00", "Raymond James Stadium", "Tampa", "US", 27.9759, -82.5033, "us_eastern"),
    _v("VEG00", "Allegiant Stadium", "Las Vegas", "US", 36.0909, -115.1833, "us_pacific"),
    _v("WAS00", "Northwest Stadium", "Landover", "US", 38.9077, -76.8645, "us_eastern"),
)}


def venue(stadium_id: Optional[str]) -> Optional[Venue]:
    """The venue for a schedule `stadium_id`, or None when the id is blank or not in the table."""
    return VENUES.get(str(stadium_id)) if stadium_id else None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def miles_between(a: Optional[str], b: Optional[str]) -> Optional[float]:
    """Distance between two stadium ids in miles, 1 decimal; None when either is unknown."""
    va, vb = venue(a), venue(b)
    if va is None or vb is None:
        return None
    return round(haversine_miles(va.lat, va.lon, vb.lat, vb.lon), 1)


def home_stadium_ids(games: Iterable[dict]) -> Dict[Tuple[str, int], str]:
    """(team, season) -> the stadium id the team used for most of its home games that season.

    Neutral-site games do not count. Read from the schedule itself, which is public before
    the season starts, so using a season's own table for that season's games is not leakage.
    Games whose venue the schedule contradicts (`venue_check` is not `ok`) are skipped.
    """
    counts: Dict[Tuple[str, int], Dict[str, int]] = {}
    for g in games:
        if g.get("neutral_site") or not g.get("stadium_id") or g.get("venue_check", "ok") != "ok":
            continue
        key = (g["home_team"], int(g["season"]))
        counts.setdefault(key, {})
        counts[key][g["stadium_id"]] = counts[key].get(g["stadium_id"], 0) + 1
    return {k: sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for k, v in counts.items()}
