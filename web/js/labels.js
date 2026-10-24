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
 * - Never invent a club name. A club abbreviation this table does not
 *   know comes back UNCHANGED. A book key it does not know is named from
 *   the key itself (bookLabelFallback) -- a spelling, never a fact.
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
  "betclic_fr": "Betclic (FR)",
  "betfair_ex_au": "Betfair Exchange (AU)",
  "betr_au": "Betr (AU)",
  "betright": "BetRight (AU)",
  "dabble_au": "Dabble (AU)",
  "sportsbet": "Sportsbet (AU)",
  "picklebet_au": "Picklebet (AU)",
  "playup": "PlayUp (AU)",
  "boombet": "BoomBet (AU)",
  "bet365_au": "bet365 (AU)",
  "ladbrokes_au": "Ladbrokes (AU)",
  "neds": "Neds (AU)",
  "pointsbetau": "PointsBet (AU)",
  "betfair_ex_eu": "Betfair Exchange (EU)",
  "betmgm": "BetMGM",
  "betonlineag": "BetOnline",
  "betrivers": "BetRivers",
  "betus": "BetUS",
  "bovada": "Bovada",
  "draftkings": "DraftKings",
  "fanatics": "Fanatics",
  "fanduel": "FanDuel",
  "leovegas_se": "LeoVegas (SE)",
  "lowvig": "LowVig",
  "mybookieag": "MyBookie",
  "onexbet": "1xBet",
  "pinnacle": "Pinnacle",
  "pmu_fr": "PMU (FR)",
  "sport888": "888sport",
  "tab": "TAB",
  "tabtouch": "TABtouch",
  "tipico_de": "Tipico (DE)",
  "unibet": "Unibet",
  "unibet_fr": "Unibet (FR)",
  "unibet_nl": "Unibet (NL)",
  "unibet_se": "Unibet (SE)",
  "williamhill": "William Hill",
  "williamhill_us": "Caesars",
  "winamax_de": "Winamax (DE)",
  "winamax_fr": "Winamax (FR)"
};

/**
 * "DE-VIGGED CONSENSUS" IN ENGLISH, IN ONE PLACE.
 *
 * The quantity is the books' average price with the bookmaker's cut taken
 * back out. Every surface in this app rendered that as some variant of
 * "de-vigged market-implied consensus", which is exact, and which the
 * owner's note on 2026-09-10 correctly described as a wall of random words
 * nobody knows the meaning of.
 *
 * The concept is not dropped -- it is the honest denominator behind every
 * price comparison this product makes, and hiding it would be worse than
 * naming it badly. It is renamed, once, here, so no two screens invent a
 * different plain-English phrase for the same number and the reader has to
 * learn it twice.
 *
 * FAIR_LABEL is the tight version for a table cell or a chip; FAIR_LONG is
 * for a section heading with room; FAIR_EXPLAINER is the sentence that
 * appears wherever the number is first shown on a screen.
 */
export const FAIR_LABEL = "FAIR PRICE";
export const FAIR_LONG = "FAIR PRICE ACROSS THE BOOKS";
export const FAIR_EXPLAINER =
  "The books' average price with their cut taken back out — what the market "
  + "really thinks the chances are. It is a measurement of the board, not a "
  + "forecast of who wins.";

/** "the fair price across 11 books", or without the count when unknown. */
export function fairPhrase(books) {
  const n = Number(books);
  return Number.isFinite(n) && n > 0
    ? `the fair price across ${n} books`
    : "the fair price across the books";
}

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

// Mirrors REGION_SUFFIXES in src/data/labels.py (the parity test does not
// compare these, so keep the two lists identical by hand).
const REGION_SUFFIXES = ["au", "uk", "eu", "us", "fr", "se", "de", "nl"];

/**
 * A readable name built from a raw book key the table does not know, so a
 * new book on the odds feed never breaks the page or CI. Mirror of
 * book_label_fallback in src/data/labels.py: "picklebet_au" ->
 * "Picklebet (AU)", "betright" -> "Betright". It is a spelling of the key,
 * not a fact about the book.
 */
export function bookLabelFallback(key) {
  if (!key) return key;
  const lowered = String(key).toLowerCase();
  let base = lowered;
  let suffix = null;
  const idx = lowered.lastIndexOf("_");
  if (idx > 0 && REGION_SUFFIXES.includes(lowered.slice(idx + 1))) {
    base = lowered.slice(0, idx);
    suffix = lowered.slice(idx + 1).toUpperCase();
  }
  const words = base
    .split("_")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
  return suffix ? `${words} (${suffix})` : words;
}

/**
 * Customer-facing label for a raw sportsbook provider key (the `book`
 * field the odds pipeline emits, e.g. "williamhill_us" -> "Caesars"). A
 * key the table does not know is named from the key by bookLabelFallback.
 * A falsy input comes back UNCHANGED.
 */
export function bookLabel(key) {
  if (!key) return key;
  const label = BOOK_LABELS[String(key).toLowerCase()];
  return label === undefined ? bookLabelFallback(key) : label;
}
