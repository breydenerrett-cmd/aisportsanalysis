"""The league registry. Adding a league is adding an entry here; the ingest is the same code.

`path` is ESPN's "<sport>/<league>" (site.api.espn.com/apis/site/v2/sports/<path>/...).
`groups` is the scoreboard `groups` filter (college: 80 = all FBS, 50 = all Division I) and
`limit` the scoreboard page size. `players` says whether per-player box scores are stored for
the league by default: off for college, where one season of player rows is ~100 MB.
`injuries` says whether ESPN publishes a league-wide injuries report for it.
"""

from __future__ import annotations

from typing import Dict, NamedTuple, Optional, Tuple


class League(NamedTuple):
    code: str
    path: str
    title: str
    family: str                    # basketball | hockey | football | soccer
    groups: Optional[str] = None
    limit: int = 400
    players: bool = True
    injuries: bool = True
    teams_limit: int = 1000


LEAGUES: Dict[str, League] = {l.code: l for l in (
    League("nba", "basketball/nba", "NBA", "basketball"),
    League("wnba", "basketball/wnba", "WNBA", "basketball"),
    League("nhl", "hockey/nhl", "NHL", "hockey"),
    League("ncaaf", "football/college-football", "NCAA football (FBS)", "football", groups="80",
           players=False),
    League("ncaab", "basketball/mens-college-basketball", "NCAA men's basketball (D1)", "basketball",
           groups="50", players=False, injuries=False),
    League("ncaaw", "basketball/womens-college-basketball", "NCAA women's basketball (D1)", "basketball",
           groups="50", players=False, injuries=False),
    League("epl", "soccer/eng.1", "English Premier League", "soccer", injuries=False),
    League("laliga", "soccer/esp.1", "La Liga", "soccer", injuries=False),
    League("bundesliga", "soccer/ger.1", "Bundesliga", "soccer", injuries=False),
    League("seriea", "soccer/ita.1", "Serie A", "soccer", injuries=False),
    League("ligue1", "soccer/fra.1", "Ligue 1", "soccer", injuries=False),
    League("mls", "soccer/usa.1", "MLS", "soccer", injuries=False),
    League("ucl", "soccer/uefa.champions", "UEFA Champions League", "soccer", injuries=False),
)}

# The leagues the scheduled refresh keeps current (cheap: a handful of requests each per pass).
DEFAULT_REFRESH: Tuple[str, ...] = ("nba", "nhl", "ncaaf", "ncaab", "epl")

SITE = "https://site.api.espn.com/apis/site/v2/sports/"
V2 = "https://site.api.espn.com/apis/v2/sports/"


def get(code: str) -> League:
    try:
        return LEAGUES[str(code).lower()]
    except KeyError:
        raise KeyError(f"unknown league {code!r}; known: {', '.join(sorted(LEAGUES))}") from None
