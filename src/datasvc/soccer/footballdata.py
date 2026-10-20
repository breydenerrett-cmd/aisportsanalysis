"""football-data.co.uk: results, match statistics and bookmaker odds (open and closing) for the big-5 leagues.

TERMS (checked 2026-10-20, https://www.football-data.co.uk/data.php). The data is free, but the site states
that its use is intended for private individuals only, and NOT for commercial or data-training products, nor for
automated bots, scrapers or AI. LineHound is a commercial product and this module is a client, so:

* nothing here runs against the site unless the operator passes the explicit acknowledgement
  (`accept_terms=True` / `--i-have-permission`), and the default CLI path refuses with this notice;
* `import_csv` takes a file the operator downloaded themselves, which is a manual private download;
* the store is git-ignored and not shipped in the web image (the repository is public, and the site's
  data may not be redistributed): `data/datasvc/footballdata/` stays on the machine that built it.

Getting written permission from the site (the data page links a contact form) is the clean way to turn the
fetch path on for the product; until then the free-source answer for soccer odds is our own forward capture
(The Odds API, already scheduled) and ESPN's `espn_odds` field on each game.

LAYOUT. One CSV per league and season: `mmz4281/<yy><yy+1>/<DIV>.csv` (E0 English Premier League, SP1 La Liga,
I1 Serie A, D1 Bundesliga, F1 Ligue 1). Odds columns: `<BOOK>H/D/A` pre-closing ("open": collected a few days
before the match, weekly), `<BOOK>CH/CD/CA` closing (since 2019/20), over/under 2.5 `<BOOK>>2.5` and
`<BOOK><2.5`, Asian handicap line `AHh`/`AHCh` and prices `<BOOK>AHH/AHA`. Only the books in `BOOKS` are kept
(Bet365, Pinnacle, William Hill, Betfair Exchange, market maximum and average): a row is ~0.6 KB, not 3.
Pinnacle's feed is stale from 2025-07-23 on (the site says so), and its columns are often blank.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from src.datasvc.espn.store import EspnStore
from src.datasvc.http import FetchError, NotFound, PoliteFetcher
from src.paths import data_path

#: league code -> (football-data division, title)
LEAGUES: Dict[str, Tuple[str, str]] = {
    "epl": ("E0", "English Premier League"),
    "laliga": ("SP1", "La Liga"),
    "seriea": ("I1", "Serie A"),
    "bundesliga": ("D1", "Bundesliga"),
    "ligue1": ("F1", "Ligue 1"),
}
BASE = "https://www.football-data.co.uk/mmz4281/"
FIRST_SEASON = 2015

#: kept bookmaker prefixes; the value is the name stored. Older files call the market maximum/average
#: BbMx/BbAv and Pinnacle P; they map onto the same names.
BOOKS: Dict[str, str] = {"B365": "B365", "PS": "PS", "P": "PS", "WH": "WH", "BFE": "BFE",
                         "Max": "Max", "BbMx": "Max", "Avg": "Avg", "BbAv": "Avg"}

TERMS_NOTICE = (
    "football-data.co.uk states its data is for private individuals only, not for commercial or data-training "
    "products, bots, scrapers or AI (data.php, checked 2026-10-20). LineHound is a commercial product, so this "
    "fetch is refused unless the operator has the site's permission and passes --i-have-permission. "
    "Import a file you downloaded yourself with `soccer import --csv FILE` instead.")


class TermsNotAccepted(RuntimeError):
    pass


ATTRIBUTION = ("Results, match statistics and odds: football-data.co.uk (private-use data; not redistributed "
               "by LineHound; the local store is untracked).")


class FootballDataStore(EspnStore):
    """Versioned store of normalised matches and their joins to ESPN game ids (same append-only rules)."""

    datasets = {"matches": (("league", "match_id"), True),
                "joins": (("league", "match_id"), True)}
    default_dir = data_path("datasvc", "footballdata")
    attribution = ATTRIBUTION


# -- names, dates, numbers --------------------------------------------------------------------------------------

def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_url(league: str, start_year: int) -> str:
    return f"{BASE}{season_code(start_year)}/{LEAGUES[league][0]}.csv"


def parse_date(text: str) -> Optional[str]:
    """'15/08/2025' or '15/08/25' -> '2025-08-15' (None when it is not a date)."""
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", text or "")
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000 if y < 80 else 1900
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def uk_to_utc(day: Optional[str], clock: Optional[str]) -> Optional[str]:
    """UK local kickoff -> UTC (BST from the last Sunday of March to the last Sunday of October, 01:00 UTC).
    The files give no timezone; the site's times are UK time, and that is an ASSUMPTION for the other leagues
    (so the result is `kickoff_utc_est`, used only as a tie-breaker)."""
    if not day or not clock or not re.match(r"^\d{1,2}:\d{2}$", clock):
        return None
    y, mo, d = (int(x) for x in day.split("-"))
    hh, mm = (int(x) for x in clock.split(":"))
    local = datetime(y, mo, d, hh, mm)
    start = datetime.combine(_last_sunday(y, 3), datetime.min.time()) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(y, 10), datetime.min.time()) + timedelta(hours=1)
    bst = start <= local - timedelta(hours=1) < end
    return (local - timedelta(hours=1 if bst else 0)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(text) -> Optional[float]:
    try:
        v = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _int(text) -> Optional[int]:
    v = _num(text)
    return None if v is None else int(v)


def _pick(rec: Dict[str, str], *cols: str) -> Optional[str]:
    for col in cols:
        value = rec.get(col)
        if value not in (None, ""):
            return value
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


# -- odds columns -------------------------------------------------------------------------------------------------

def _book(prefix: str) -> Optional[str]:
    return BOOKS.get(prefix)


def _odds(record: Dict[str, str]) -> dict:
    """{market: {book: {'open': [...], 'close': [...]}}} from one CSV row, kept books only."""
    out: Dict[str, dict] = {}

    def put(market: str, book: str, when: str, values: List[Optional[float]]) -> None:
        if all(v is not None for v in values):
            out.setdefault(market, {}).setdefault(book, {})[when] = values

    for prefix, name in BOOKS.items():
        # 1X2: BOOK + H/D/A (open) and BOOK + CH/CD/CA (closing)
        for when, tag in (("open", ""), ("close", "C")):
            put("1x2", name, when, [_num(record.get(f"{prefix}{tag}{s}")) for s in "HDA"])
            put("ou25", name, when, [_num(record.get(f"{prefix}{tag}>2.5")), _num(record.get(f"{prefix}{tag}<2.5"))])
        # Asian handicap prices: BOOK + AHH/AHA (open), BOOK + CAHH/CAHA (closing)
        for when, tag in (("open", ""), ("close", "C")):
            put("ah", name, when, [_num(record.get(f"{prefix}{tag}AHH")), _num(record.get(f"{prefix}{tag}AHA"))])
    for when, cols in (("open", ("AHh", "BbAHh")), ("close", ("AHCh",))):
        line = _num(_pick(record, *cols))
        if line is not None:
            out.setdefault("ah", {})[f"line_{when}"] = line
    return out


STAT_COLUMNS = {"HS": "shots_home", "AS": "shots_away", "HST": "sot_home", "AST": "sot_away", "HC": "corners_home",
                "AC": "corners_away", "HF": "fouls_home", "AF": "fouls_away", "HY": "yellow_home",
                "AY": "yellow_away", "HR": "red_home", "AR": "red_away"}


def parse_csv(text: str, league: str, start_year: int, observed_utc: str) -> List[dict]:
    """Normalised match rows from one season file. Blank and undated rows are skipped; nothing is invented."""
    div = LEAGUES[league][0]
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    rows: List[dict] = []
    seen: Dict[str, int] = {}
    for rec in reader:
        day = parse_date(rec.get("Date"))
        home, away = (rec.get("HomeTeam") or "").strip(), (rec.get("AwayTeam") or "").strip()
        if not (day and home and away):
            continue
        base = f"{div}-{day}-{_slug(home)}-{_slug(away)}"
        seen[base] = seen.get(base, 0) + 1
        match_id = base if seen[base] == 1 else f"{base}-{seen[base]}"
        row = {"league": league, "season": start_year, "match_id": match_id, "div": rec.get("Div") or div,
               "date": day, "home": home, "away": away, "observed_utc": observed_utc}
        clock = (rec.get("Time") or "").strip()
        if clock:
            row["time_uk"] = clock
            est = uk_to_utc(day, clock)
            if est:
                row["kickoff_utc_est"] = est
        for dst, cols in (("ft_home", ("FTHG", "HG")), ("ft_away", ("FTAG", "AG")),
                          ("ht_home", ("HTHG",)), ("ht_away", ("HTAG",))):
            value = _int(_pick(rec, *cols))
            if value is not None:
                row[dst] = value
        for dst, cols in (("ft_result", ("FTR", "Res")), ("ht_result", ("HTR",))):
            value = (_pick(rec, *cols) or "").strip()
            if value in ("H", "D", "A"):
                row[dst] = value
        if (rec.get("Referee") or "").strip():
            row["referee"] = rec["Referee"].strip()
        stats = {dst: _int(rec.get(src)) for src, dst in STAT_COLUMNS.items() if _int(rec.get(src)) is not None}
        if stats:
            row["stats"] = stats
        odds = _odds(rec)
        if odds:
            row["odds"] = odds
        rows.append(row)
    return rows


# -- fetching (gated) and importing ---------------------------------------------------------------------------

def fetch_season(fetcher: PoliteFetcher, league: str, start_year: int, *, accept_terms: bool,
                 max_age_s: Optional[float] = None) -> Optional[str]:
    """The CSV text, or None when the season file does not exist. Refuses unless the operator accepted the terms."""
    if not accept_terms:
        raise TermsNotAccepted(TERMS_NOTICE)
    try:
        return fetcher.get_text(season_url(league, start_year), max_age_s=max_age_s)
    except NotFound:
        return None


def ingest(store: FootballDataStore, league: str, start_year: int, text: str, observed_utc: str) -> dict:
    rows = parse_csv(text, league, start_year, observed_utc)
    counts = store.append(league, "matches", rows)
    return {"league": league, "season": start_year, "rows": len(rows), **counts}


def import_csv(store: FootballDataStore, league: str, start_year: int, path: Path, observed_utc: str) -> dict:
    """Load a season file the operator downloaded themselves."""
    return ingest(store, league, start_year, Path(path).read_text(encoding="utf-8-sig"), observed_utc)


def fetch_range(store: FootballDataStore, fetcher: PoliteFetcher, league: str, first: int, last: int, *,
                accept_terms: bool, observed_utc: str) -> List[dict]:
    if not accept_terms:
        raise TermsNotAccepted(TERMS_NOTICE)
    out = []
    for year in range(first, last + 1):
        try:
            text = fetch_season(fetcher, league, year, accept_terms=True)
        except FetchError as exc:
            out.append({"league": league, "season": year, "error": str(exc)})
            continue
        out.append(ingest(store, league, year, text, observed_utc) if text else
                   {"league": league, "season": year, "rows": 0, "missing": True})
    return out
