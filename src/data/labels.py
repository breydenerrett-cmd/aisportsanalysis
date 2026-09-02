"""MLB club display names and sportsbook customer-facing labels.

WHY THIS FILE EXISTS
---------------------------------------------------------------------------
The API emits club abbreviations (see docs/API_CONTRACTS.md's slate rows,
and src/data/parks.py's ALIASES for the spellings different sources use)
and raw sportsbook provider keys -- the `book` field in
data/processed/odds_multibook.jsonl, e.g. "williamhill_us". Neither is a
string a customer should read as-is. design/linehound-v2/
RECONCILED_CONTRACT_CURRENT_HEAD.md rates the display names below as safe
static presentation derivations (class C) -- public identity data, not
analysis -- so they live here as a static table, the Python-side twin of
web/js/labels.js.

SINGLE SOURCE OF TRUTH
---------------------------------------------------------------------------
web/js/labels.js carries the identical two maps for the client. There is
no runtime import across that language boundary, so the two are kept
identical by test instead: tests/test_labels.py parses labels.js's exact
JSON-literal-shaped object-literal source and asserts it equals
TEAM_NAMES / BOOK_LABELS below. Edit both files together; the parity test
fails loudly if they drift, the same way
tests/test_evidence_labels_unified.py polices a single-object drift risk
on the Python side alone.

RULES THAT COME WITH IT
---------------------------------------------------------------------------
- Never invent a name or a label. An abbreviation or provider key this
  table does not know returns UNCHANGED from the helpers below -- a
  fabricated label is worse than an ugly raw string.
- These are presentation only. They carry no odds, no verdict, no status
  -- exactly like team color, this is identity data.
"""

from __future__ import annotations

# Keys match every abbreviation web/js/teamcolors.js's TEAMS table knows,
# including the ATH/AZ spellings this API emits (ATH = the Athletics, who
# MLB now lists with no city prefix -- see src/data/parks.py's ALIASES
# comment; AZ = the Diamondbacks).
TEAM_NAMES = {
    "ATH": {"city": "", "name": "Athletics", "full": "Athletics"},
    "ATL": {"city": "Atlanta", "name": "Braves", "full": "Atlanta Braves"},
    "AZ": {"city": "Arizona", "name": "Diamondbacks", "full": "Arizona Diamondbacks"},
    "BAL": {"city": "Baltimore", "name": "Orioles", "full": "Baltimore Orioles"},
    "BOS": {"city": "Boston", "name": "Red Sox", "full": "Boston Red Sox"},
    "CHC": {"city": "Chicago", "name": "Cubs", "full": "Chicago Cubs"},
    "CIN": {"city": "Cincinnati", "name": "Reds", "full": "Cincinnati Reds"},
    "CLE": {"city": "Cleveland", "name": "Guardians", "full": "Cleveland Guardians"},
    "COL": {"city": "Colorado", "name": "Rockies", "full": "Colorado Rockies"},
    "CWS": {"city": "Chicago", "name": "White Sox", "full": "Chicago White Sox"},
    "DET": {"city": "Detroit", "name": "Tigers", "full": "Detroit Tigers"},
    "HOU": {"city": "Houston", "name": "Astros", "full": "Houston Astros"},
    "KC": {"city": "Kansas City", "name": "Royals", "full": "Kansas City Royals"},
    "LAA": {"city": "Los Angeles", "name": "Angels", "full": "Los Angeles Angels"},
    "LAD": {"city": "Los Angeles", "name": "Dodgers", "full": "Los Angeles Dodgers"},
    "MIA": {"city": "Miami", "name": "Marlins", "full": "Miami Marlins"},
    "MIL": {"city": "Milwaukee", "name": "Brewers", "full": "Milwaukee Brewers"},
    "MIN": {"city": "Minnesota", "name": "Twins", "full": "Minnesota Twins"},
    "NYM": {"city": "New York", "name": "Mets", "full": "New York Mets"},
    "NYY": {"city": "New York", "name": "Yankees", "full": "New York Yankees"},
    "PHI": {"city": "Philadelphia", "name": "Phillies", "full": "Philadelphia Phillies"},
    "PIT": {"city": "Pittsburgh", "name": "Pirates", "full": "Pittsburgh Pirates"},
    "SD": {"city": "San Diego", "name": "Padres", "full": "San Diego Padres"},
    "SEA": {"city": "Seattle", "name": "Mariners", "full": "Seattle Mariners"},
    "SF": {"city": "San Francisco", "name": "Giants", "full": "San Francisco Giants"},
    "STL": {"city": "St. Louis", "name": "Cardinals", "full": "St. Louis Cardinals"},
    "TB": {"city": "Tampa Bay", "name": "Rays", "full": "Tampa Bay Rays"},
    "TEX": {"city": "Texas", "name": "Rangers", "full": "Texas Rangers"},
    "TOR": {"city": "Toronto", "name": "Blue Jays", "full": "Toronto Blue Jays"},
    "WSH": {"city": "Washington", "name": "Nationals", "full": "Washington Nationals"},
}

# Keys are the raw provider values the `book` field carries in
# data/processed/odds_multibook.jsonl; values are the name the
# customer-facing sportsbook actually goes by (williamhill_us is the
# Caesars Sportsbook feed key; betonlineag/mybookieag/betus/lowvig strip
# the odds-API suffixing convention down to the book's real name).
BOOK_LABELS = {
    "betmgm": "BetMGM",
    "betonlineag": "BetOnline",
    "betrivers": "BetRivers",
    "betus": "BetUS",
    "bovada": "Bovada",
    "draftkings": "DraftKings",
    "fanatics": "Fanatics",
    "fanduel": "FanDuel",
    "lowvig": "LowVig",
    "mybookieag": "MyBookie",
    "williamhill_us": "Caesars",
}


def team_name(abbr, form: str = "full"):
    """Display name for a club abbreviation. `form` selects "full"
    (default, e.g. "San Diego Padres"), "city" (e.g. "San Diego"), or
    "name" (e.g. "Padres"). An abbreviation this table does not know --
    or a falsy input -- comes back UNCHANGED: never invent a name for an
    unrecognized code."""
    if not abbr:
        return abbr
    entry = TEAM_NAMES.get(str(abbr).upper())
    if entry is None:
        return abbr
    return entry[form if form in ("city", "name") else "full"]


def book_label(key):
    """Customer-facing label for a raw sportsbook provider key (the
    `book` field the odds pipeline emits, e.g. "williamhill_us" ->
    "Caesars"). A key this table does not know -- or a falsy input --
    comes back UNCHANGED: never invent a book name."""
    if not key:
        return key
    label = BOOK_LABELS.get(str(key).lower())
    return key if label is None else label
