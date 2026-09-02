/**
 * MLB club display names and sportsbook customer-facing labels.
 *
 * WHY THIS FILE EXISTS
 * -------------------------------------------------------------------
 * The API emits the club abbreviations this file's sibling
 * `teamcolors.js` is keyed on (see docs/API_CONTRACTS.md's slate rows)
 * and raw sportsbook provider keys -- the `book` field in
 * data/processed/odds_multibook.jsonl, e.g. "williamhill_us". Neither
 * is a string a customer should read as-is. design/linehound-v2/
 * RECONCILED_CONTRACT_CURRENT_HEAD.md rates the display names below as
 * safe static presentation derivations (class C) -- public identity
 * data, not analysis -- so, exactly like `teamcolors.js`'s palette,
 * they live here as a static table instead of something the API
 * computes or a view guesses at.
 *
 * SINGLE SOURCE OF TRUTH
 * -------------------------------------------------------------------
 * src/data/labels.py carries the identical two maps for the Python
 * side. TEAM_NAMES and BOOK_LABELS below are written JSON-literal-shaped
 * on purpose -- double-quoted keys and values only, no trailing comma,
 * no comments inside the braces -- so tests/test_labels.py can lift each
 * object literal's exact source text, parse it as JSON, and assert it
 * against the Python dicts. That is the same drift risk
 * tests/test_evidence_labels_unified.py exists to catch on the Python
 * side alone; across a language boundary there is no shared object to
 * point two names at, so the test compares parsed data instead. Do not
 * reformat these two blocks without re-running that test.
 *
 * RULES THAT COME WITH IT
 * -------------------------------------------------------------------
 * - Never invent a name or a label. An abbreviation or provider key
 *   this table does not know returns UNCHANGED from the helpers below
 *   -- a fabricated label is worse than an ugly raw string.
 * - These are presentation only. They carry no odds, no verdict, no
 *   status -- exactly like team color, this is identity data.
 */

// JSON-literal-shaped -- see the module docstring. Keys match every
// abbreviation `teamcolors.js`'s TEAMS table knows, including the ATH/AZ
// spellings this API emits (ATH = the Athletics, who MLB now lists with
// no city prefix -- see src/data/parks.py's ALIASES comment; AZ = the
// Diamondbacks).
export const TEAM_NAMES = {
  "ATH": { "city": "", "name": "Athletics", "full": "Athletics" },
  "ATL": { "city": "Atlanta", "name": "Braves", "full": "Atlanta Braves" },
  "AZ": { "city": "Arizona", "name": "Diamondbacks", "full": "Arizona Diamondbacks" },
  "BAL": { "city": "Baltimore", "name": "Orioles", "full": "Baltimore Orioles" },
  "BOS": { "city": "Boston", "name": "Red Sox", "full": "Boston Red Sox" },
  "CHC": { "city": "Chicago", "name": "Cubs", "full": "Chicago Cubs" },
  "CIN": { "city": "Cincinnati", "name": "Reds", "full": "Cincinnati Reds" },
  "CLE": { "city": "Cleveland", "name": "Guardians", "full": "Cleveland Guardians" },
  "COL": { "city": "Colorado", "name": "Rockies", "full": "Colorado Rockies" },
  "CWS": { "city": "Chicago", "name": "White Sox", "full": "Chicago White Sox" },
  "DET": { "city": "Detroit", "name": "Tigers", "full": "Detroit Tigers" },
  "HOU": { "city": "Houston", "name": "Astros", "full": "Houston Astros" },
  "KC": { "city": "Kansas City", "name": "Royals", "full": "Kansas City Royals" },
  "LAA": { "city": "Los Angeles", "name": "Angels", "full": "Los Angeles Angels" },
  "LAD": { "city": "Los Angeles", "name": "Dodgers", "full": "Los Angeles Dodgers" },
  "MIA": { "city": "Miami", "name": "Marlins", "full": "Miami Marlins" },
  "MIL": { "city": "Milwaukee", "name": "Brewers", "full": "Milwaukee Brewers" },
  "MIN": { "city": "Minnesota", "name": "Twins", "full": "Minnesota Twins" },
  "NYM": { "city": "New York", "name": "Mets", "full": "New York Mets" },
  "NYY": { "city": "New York", "name": "Yankees", "full": "New York Yankees" },
  "PHI": { "city": "Philadelphia", "name": "Phillies", "full": "Philadelphia Phillies" },
  "PIT": { "city": "Pittsburgh", "name": "Pirates", "full": "Pittsburgh Pirates" },
  "SD": { "city": "San Diego", "name": "Padres", "full": "San Diego Padres" },
  "SEA": { "city": "Seattle", "name": "Mariners", "full": "Seattle Mariners" },
  "SF": { "city": "San Francisco", "name": "Giants", "full": "San Francisco Giants" },
  "STL": { "city": "St. Louis", "name": "Cardinals", "full": "St. Louis Cardinals" },
  "TB": { "city": "Tampa Bay", "name": "Rays", "full": "Tampa Bay Rays" },
  "TEX": { "city": "Texas", "name": "Rangers", "full": "Texas Rangers" },
  "TOR": { "city": "Toronto", "name": "Blue Jays", "full": "Toronto Blue Jays" },
  "WSH": { "city": "Washington", "name": "Nationals", "full": "Washington Nationals" }
};

// JSON-literal-shaped -- see the module docstring. Keys are the raw
// provider values the `book` field carries in
// data/processed/odds_multibook.jsonl; values are the name the
// customer-facing sportsbook actually goes by (williamhill_us is the
// Caesars Sportsbook feed key; betonlineag/mybookieag/betus/lowvig strip
// the odds-API suffixing convention down to the book's real name).
export const BOOK_LABELS = {
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
  "williamhill_us": "Caesars"
};

/**
 * Display name for a club abbreviation. `form` selects "full" (default,
 * e.g. "San Diego Padres"), "city" (e.g. "San Diego"), or "name" (e.g.
 * "Padres"). An abbreviation this table does not know -- or a falsy
 * input -- comes back UNCHANGED: never invent a name for an
 * unrecognized code.
 */
export function teamName(abbr, form = "full") {
  if (!abbr) return abbr;
  const entry = TEAM_NAMES[String(abbr).toUpperCase()];
  if (!entry) return abbr;
  if (form === "city") return entry.city;
  if (form === "name") return entry.name;
  return entry.full;
}

/**
 * Customer-facing label for a raw sportsbook provider key (the `book`
 * field the odds pipeline emits, e.g. "williamhill_us" -> "Caesars"). A
 * key this table does not know -- or a falsy input -- comes back
 * UNCHANGED: never invent a book name.
 */
export function bookLabel(key) {
  if (!key) return key;
  const label = BOOK_LABELS[String(key).toLowerCase()];
  return label === undefined ? key : label;
}
