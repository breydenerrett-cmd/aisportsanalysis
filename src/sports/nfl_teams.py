"""NFL team map and abbreviation resolver.

WHY THIS EXISTS: every NFL identifier in this app -- team name (from the odds
feed), abbreviation (from nflverse data), and nickname -- needs a single map so
name variations ("LA Rams" vs "L.A. Rams", historical names like "Washington
Football Team", and provider quirks) can resolve to a canonical code without
hardcoding those rules in every module that touches a team. The map also proves
the team roster is complete: a game that mentions a team not here fails a
validity check, not silently.
"""


# 32 NFL teams: (nflverse_code, odds_api_full_name, nickname)
# nflverse_code is the stable identifier used in schedule CSVs and team stats.
# odds_api_full_name is what The Odds API calls the team (from their feed).
# nickname is the colloquial short name ("Bills", not "Buffalo Bills").
TEAMS = (
    ("ARI", "Arizona Cardinals", "Cardinals"),
    ("ATL", "Atlanta Falcons", "Falcons"),
    ("BAL", "Baltimore Ravens", "Ravens"),
    ("BUF", "Buffalo Bills", "Bills"),
    ("CAR", "Carolina Panthers", "Panthers"),
    ("CHI", "Chicago Bears", "Bears"),
    ("CIN", "Cincinnati Bengals", "Bengals"),
    ("CLE", "Cleveland Browns", "Browns"),
    ("DAL", "Dallas Cowboys", "Cowboys"),
    ("DEN", "Denver Broncos", "Broncos"),
    ("DET", "Detroit Lions", "Lions"),
    ("GB", "Green Bay Packers", "Packers"),
    ("HOU", "Houston Texans", "Texans"),
    ("IND", "Indianapolis Colts", "Colts"),
    ("JAX", "Jacksonville Jaguars", "Jaguars"),
    ("KC", "Kansas City Chiefs", "Chiefs"),
    ("LA", "Los Angeles Rams", "Rams"),
    ("LAC", "Los Angeles Chargers", "Chargers"),
    ("LV", "Las Vegas Raiders", "Raiders"),
    ("MIA", "Miami Dolphins", "Dolphins"),
    ("MIN", "Minnesota Vikings", "Vikings"),
    ("NE", "New England Patriots", "Patriots"),
    ("NO", "New Orleans Saints", "Saints"),
    ("NYG", "New York Giants", "Giants"),
    ("NYJ", "New York Jets", "Jets"),
    ("PHI", "Philadelphia Eagles", "Eagles"),
    ("PIT", "Pittsburgh Steelers", "Steelers"),
    ("SEA", "Seattle Seahawks", "Seahawks"),
    ("SF", "San Francisco 49ers", "49ers"),
    ("TB", "Tampa Bay Buccaneers", "Buccaneers"),
    ("TEN", "Tennessee Titans", "Titans"),
    ("WAS", "Washington Commanders", "Commanders"),
)

# Build lookup tables from TEAMS
# Code lookup is case-insensitive, so keys are uppercase
_TEAMS_BY_CODE = {code.upper(): (full_name, short_name) for code, full_name, short_name in TEAMS}
# Name lookups use lowercase keys for case-insensitive matching
_TEAMS_BY_FULL_NAME = {full_name.lower(): code for code, full_name, _ in TEAMS}
_TEAMS_BY_SHORT_NAME = {short_name.lower(): code for code, _, short_name in TEAMS}

# Aliases: alternate names that might appear in the odds feed or historical data
# This map normalizes variations so a single canonical name can resolve to a code.
# Keys are normalized (lowercase, no punctuation, single spaces) for matching.
_ALIASES_RAW = {
    "LA Rams": "LA",
    "L.A. Rams": "LA",
    "LAR": "LA",
    "St. Louis Rams": "LA",
    "LA Chargers": "LAC",
    "L.A. Chargers": "LAC",
    "San Diego Chargers": "LAC",
    "Washington Football Team": "WAS",
    "WSH": "WAS",
    "Oakland Raiders": "LV",
    "JAC": "JAX",
}

# Normalize alias keys for case-insensitive, punctuation-insensitive matching
def _normalize_for_lookup(text):
    """Normalize text for alias lookup."""
    normalized = text.lower().replace(".", "").replace(",", "").replace("(", "").replace(")", "")
    return " ".join(normalized.split())

ALIASES = {_normalize_for_lookup(alias_name): code for alias_name, code in _ALIASES_RAW.items()}

# All codes in sorted order for roster validation
ALL_CODES = tuple(sorted(code for code, _, _ in TEAMS))


def abbrev(name):
    """Resolve a team name (any form) to its nflverse code.

    Accepts exact code, full name, short name, or any registered alias.
    Case-insensitive; punctuation and extra spaces are ignored.

    Args:
        name: Team identifier in any form.

    Returns:
        nflverse code (e.g. "BUF") if found, None otherwise.
    """
    if name is None:
        return None

    # Normalize: lowercase, strip whitespace, remove punctuation
    normalized = _normalize_for_lookup(str(name).strip())

    # Try exact code match (case-insensitive)
    normalized_upper = normalized.upper()
    if normalized_upper in _TEAMS_BY_CODE:
        return normalized_upper

    # Try full name match
    if normalized in _TEAMS_BY_FULL_NAME:
        return _TEAMS_BY_FULL_NAME[normalized]

    # Try short name match
    if normalized in _TEAMS_BY_SHORT_NAME:
        return _TEAMS_BY_SHORT_NAME[normalized]

    # Try aliases
    if normalized in ALIASES:
        return ALIASES[normalized]

    return None


def full_name(code):
    """Get the full team name for a nflverse code.

    Args:
        code: nflverse team code (e.g. "BUF").

    Returns:
        Full team name (e.g. "Buffalo Bills") or None if code is unknown.
    """
    if code is None:
        return None

    code_upper = str(code).upper()
    if code_upper in _TEAMS_BY_CODE:
        return _TEAMS_BY_CODE[code_upper][0]

    return None


def short_name(code):
    """Get the nickname for a nflverse code.

    Args:
        code: nflverse team code (e.g. "BUF").

    Returns:
        Nickname (e.g. "Bills") or None if code is unknown.
    """
    if code is None:
        return None

    code_upper = str(code).upper()
    if code_upper in _TEAMS_BY_CODE:
        return _TEAMS_BY_CODE[code_upper][1]

    return None
