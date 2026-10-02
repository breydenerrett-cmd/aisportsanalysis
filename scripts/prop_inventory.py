"""Prop experiment inventory: what the repo can and cannot support, measured.

    python scripts/prop_inventory.py [--root DIR] [--since YYYY-MM-DD]
                                     [--raw-scan] [--json]
                                     [--statcast-manifest PATH]
                                     [--update-doc docs/PROP_EXPERIMENT_INVENTORY.md]

READ-ONLY. Measures INPUTS (is a market captured, how many books, how wide is
the margin, how many contracts can settle, what the data costs). It fits,
tunes and scores nothing, computes no win rate and no ROI, and writes only
what `--update-doc` is pointed at (the block between the two GENERATED
markers) or stdout. Python standard library plus the repo's own pure helpers
(`src.core.odds` for the de-vig and margin arithmetic, `src.analysis.prices`
for the six-book floor, `src.analysis.derivative_prices` for the two-way
booksum floor).

THE SEALED WINDOW
-----------------
Nothing dated 2026-01-01..2026-08-27 is parsed. Every store is read line by
line and each line is classified by the DATE TEXT of its date field, matched
by regular expression on the raw line, BEFORE any other field is looked at.
A line dated inside the window is counted (`sealed_skipped`) and dropped
unparsed; a line dated before `--since` but outside the window is counted and
dropped unparsed. The outcome store (`boxscores_2026.jsonl`) is read through
the same gate and only the key (game_pk, type, normalised name) of a surviving
row is kept: no stat value is read into any statistic here. The results csv
(`data/historical/mlb_results.csv`) is never opened. `evidence/` is never
opened.

DEFINITIONS (fixed here, used in every table)
---------------------------------------------
contract    one bettable two-way proposition: (event, market, player, line).
            The line is part of the identity.
board       per contract, only the quotes sharing the contract's NEWEST
            observation instant (the rule `src.analysis.prices.snapshot` and
            `derivative_prices` already use).
two-sided   a book that quoted both Over and Under at that instant with a
            combined raw implied probability of at least 0.98 (the repo's
            `derivative_prices.MIN_TWO_WAY_BOOKSUM`; a lower sum is two
            different bets mis-paired, not one market).
margin      raw booksum - 1 for one book's two-sided pair
            (`src.core.odds.margin`), in percent. hold is margin / booksum
            (`src.core.odds.hold_percentage`). Neither depends on the de-vig
            method. The fair probability of a contract, where one is shown,
            is the mean of the per-book proportional de-vig
            (`src.core.odds.devig_two_way`, default method) across the
            two-sided books, which is `prices.snapshot`'s method; the repo's
            floor for calling that a consensus is `prices.MIN_BOOKS` = 6.
eligible    a contract with at least one two-sided book on its board.
settleable  an eligible contract whose game maps to a game_pk
            (`event_game_map.jsonl`, resolved and unambiguous) and whose
            player has a row of the right type in the box store for that
            game. Presence of a row is all that is checked; the stat is not
            read.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import gzip
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import odds as odds_math  # noqa: E402
from src.analysis import prices as _prices  # noqa: E402
from src.analysis import derivative_prices as _dprices  # noqa: E402

SEALED_START = "2026-01-01"
SEALED_END = "2026-08-27"
WINDOW_START = "2026-09-10"

MIN_BOOKS = _prices.MIN_BOOKS                      # 6
MIN_TWO_WAY_BOOKSUM = _dprices.MIN_TWO_WAY_BOOKSUM  # 0.98
CLOSE_MINUTES = 90                                  # "closing board" lead
POSTSEASON_START = "2026-09-29"                     # postseason_config.CALENDAR
MONTHLY_ALLOWANCE = 100000

GEN_BEGIN = "<!-- GENERATED:prop_inventory BEGIN -->"
GEN_END = "<!-- GENERATED:prop_inventory END -->"

UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

class Family:
    def __init__(self, sport, name, market, store, subject, box_type,
                 settle_module, structural_lines_per_game, note=""):
        self.sport = sport
        self.name = name
        self.market = market                  # provider market key
        self.store = store                    # prop_prices | batter_props | None
        self.subject = subject
        self.box_type = box_type              # box-row type used to settle
        self.settle_module = settle_module
        self.structural = structural_lines_per_game
        self.note = note


FAMILIES = (
    Family("MLB", "pitcher strikeouts", "pitcher_strikeouts", "prop_prices",
           "pitcher", "pitcher",
           "src/board/settle_props.py PROP_STAT_RULES['pitcher_strikeouts'] -> 'k'; "
           "box rows from src/pipeline/boxscores.py", 2),
    Family("MLB", "pitcher outs", "pitcher_outs", None, "pitcher", "pitcher",
           "src/board/settle_props.py PROP_STAT_RULES['pitcher_outs'] -> 'outs'; "
           "box rows from src/pipeline/boxscores.py", 2),
    Family("MLB", "hits allowed", "pitcher_hits_allowed", None, "pitcher",
           "pitcher",
           "src/board/settle_props.py PROP_STAT_RULES['pitcher_hits_allowed'] -> 'h'; "
           "box rows from src/pipeline/boxscores.py", 2),
    Family("MLB", "earned runs", "pitcher_earned_runs", None, "pitcher",
           "pitcher",
           "src/board/settle_props.py PROP_STAT_RULES['pitcher_earned_runs'] -> 'er'; "
           "box rows from src/pipeline/boxscores.py", 2),
    Family("MLB", "batter hits", "batter_hits", "batter_props", "batter",
           "batter",
           "src/board/settle_props.py PROP_STAT_RULES['batter_hits'] -> 'h'; "
           "box rows from src/pipeline/boxscores.py", None),
    Family("MLB", "batter total bases", "batter_total_bases", "batter_props",
           "batter", "batter",
           "src/board/settle_props.py PROP_STAT_RULES['batter_total_bases'] -> "
           "'total_bases'; box rows from src/pipeline/boxscores.py", None),
    Family("NFL", "QB passing yards", "player_pass_yds", None, "qb", None,
           "none: no NFL player box-score fetch exists in src/ (no module "
           "reads passing, receiving or rushing yards)", 2),
    Family("NFL", "receptions", "player_receptions", None, "skill", None,
           "none: same", None),
    Family("NFL", "receiving yards", "player_reception_yds", None, "skill",
           None, "none: same", None),
    Family("NFL", "rushing yards", "player_rush_yds", None, "skill", None,
           "none: same", None),
)

# Documented provider market keys (https://the-odds-api.com/sports-odds-data/
# betting-markets.html, read 2026-10-01). Used only to say whether a family's
# key is one the provider documents; presence in a store is measured.
PROVIDER_DOCUMENTED = {
    "pitcher_strikeouts", "pitcher_outs", "pitcher_hits_allowed",
    "pitcher_earned_runs", "batter_hits", "batter_total_bases",
    "player_pass_yds", "player_receptions", "player_reception_yds",
    "player_rush_yds",
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

class Paths:
    def __init__(self, root, statcast_manifest=None):
        root = Path(root)
        self.root = root
        proc = root / "data" / "processed"
        hist = root / "data" / "historical"
        self.prop_prices = proc / "prop_prices.jsonl"
        self.prop_listing = proc / "prop_listing.jsonl"
        self.batter_props = proc / "batter_props.jsonl"
        self.batter_props_raw = proc / "batter_props_raw.jsonl"
        self.event_game_map = proc / "event_game_map.jsonl"
        self.boxscores = proc / "boxscores_2026.jsonl"
        self.credit_log = proc / "credit_log.jsonl"
        self.credit_log_live = root / "data" / "live" / "credit_log_live.jsonl"
        self.pitcher_logs = hist / "pitcher_logs.jsonl"
        self.bullpen_log = hist / "bullpen_log.jsonl"
        self.lineups = hist / "lineups.jsonl"
        self.handedness = hist / "handedness.json"
        self.arsenal_pitcher = hist / "arsenals" / "pitcher_2026.json"
        self.arsenal_batter = hist / "arsenals" / "batter_2026.json"
        self.statcast_manifest = (Path(statcast_manifest) if statcast_manifest
                                  else hist / "statcast" / "manifest.json")
        self.bdl_manifest = hist / "balldontlie" / "MANIFEST.json"
        self.bdl_nfl_dir = hist / "balldontlie" / "nfl"
        self.raw_dir = root / "data" / "raw" / "oddsapi"
        self.archive_box_dir = root / "data" / "archive" / "historical" / "boxscores"


# ---------------------------------------------------------------------------
# The dated line reader: the sealed window is decided on the RAW LINE
# ---------------------------------------------------------------------------

def in_sealed(day):
    return SEALED_START <= day <= SEALED_END


def _date_pattern(field):
    return re.compile(r'"%s"\s*:\s*"(\d{4}-\d{2}-\d{2})' % re.escape(field))


def _new_tally():
    return {"lines": 0, "parsed": 0, "sealed_skipped": 0, "pre_window": 0,
            "undated": 0, "unparseable": 0, "sealed_dates": []}


def read_dated(path, field, since=WINDOW_START):
    """(rows, tally). A line is classified by the date text of `field`
    BEFORE it is parsed. Sealed-window lines and lines before `since` are
    counted and never parsed. A missing store returns ([], tally with
    'missing': True)."""
    tally = _new_tally()
    path = Path(path)
    if not path.exists():
        tally["missing"] = True
        return [], tally
    pat = _date_pattern(field)
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            tally["lines"] += 1
            m = pat.search(line)
            if not m:
                tally["undated"] += 1
                continue
            day = m.group(1)
            if in_sealed(day):
                tally["sealed_skipped"] += 1
                if len(tally["sealed_dates"]) < 5:
                    tally["sealed_dates"].append(day)
                continue
            if day < since:
                tally["pre_window"] += 1
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                tally["unparseable"] += 1
                continue
            tally["parsed"] += 1
    return rows, tally


def date_span(path, field, since=WINDOW_START):
    """First/last date, lines at or after `since`, sealed lines skipped,
    from the date text only. NOTHING is parsed: a store that mixes sealed and
    forward rows (pitcher logs) is summarised without reading a stat."""
    tally = _new_tally()
    path = Path(path)
    if not path.exists():
        tally["missing"] = True
        return {"missing": True, "tally": tally}
    pat = _date_pattern(field)
    first = last = None
    since_lines = 0
    by_year = collections.Counter()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            tally["lines"] += 1
            m = pat.search(line)
            if not m:
                tally["undated"] += 1
                continue
            day = m.group(1)
            if in_sealed(day):
                tally["sealed_skipped"] += 1
                continue
            first = day if first is None or day < first else first
            last = day if last is None or day > last else last
            by_year[day[:4]] += 1
            if day >= since:
                since_lines += 1
    return {"first_unsealed": first, "last": last, "lines_since": since_lines,
            "by_year": dict(sorted(by_year.items())), "tally": tally}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def norm_name(name):
    """Accent- and punctuation-insensitive; nothing fuzzier (a wrong settle
    is invisible, a miss is not)."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().replace(".", "").replace("'", "").split())


def _parse_utc(text):
    if not text:
        return None
    try:
        return _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _median(values):
    return statistics.median(values) if values else None


def _quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _round(value, nd=2):
    return None if value is None else round(value, nd)


def _pct(num, den):
    return None if not den else round(100.0 * num / den, 1)


def _days(first, last):
    a = _dt.date.fromisoformat(first)
    b = _dt.date.fromisoformat(last)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += _dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Quotes -> contracts
# ---------------------------------------------------------------------------

def _quotes_prop_prices(rows, market):
    """One quote per side per row. A row with a missing side yields only the
    side present; the other stays absent (never zero)."""
    for r in rows:
        if r.get("market") != market:
            continue
        line = r.get("point")
        for side, key in (("Over", "over_price"), ("Under", "under_price")):
            price = r.get(key)
            if price is None:
                continue
            yield {"event": r.get("event_id"), "date": r.get("game_date"),
                   "commence": r.get("commence_time"),
                   "observed": r.get("observed_utc"), "player": r.get("player"),
                   "line": None if line is None else str(line),
                   "book": r.get("book"), "side": side, "price": price,
                   "home": r.get("home_team"), "away": r.get("away_team")}
        # a row with neither price still proves the book listed the player
        if r.get("over_price") is None and r.get("under_price") is None:
            yield {"event": r.get("event_id"), "date": r.get("game_date"),
                   "commence": r.get("commence_time"),
                   "observed": r.get("observed_utc"), "player": r.get("player"),
                   "line": None if line is None else str(line),
                   "book": r.get("book"), "side": None, "price": None,
                   "home": r.get("home_team"), "away": r.get("away_team")}


def _quotes_batter_props(rows, market):
    for r in rows:
        if r.get("market") != market:
            continue
        side = r.get("side")
        if side not in ("Over", "Under"):
            continue
        yield {"event": r.get("event_id"), "date": r.get("game_date"),
               "commence": r.get("commence_time"),
               "observed": r.get("observed_utc"), "player": r.get("player"),
               "line": None if r.get("line") is None else str(r.get("line")),
               "book": r.get("book"), "side": side, "price": r.get("price"),
               "home": r.get("home_team"), "away": r.get("away_team")}


def build_contracts(quotes):
    """Group quotes into contracts and keep only each contract's newest
    shared instant. Returns a list of contract dicts."""
    grouped = collections.defaultdict(list)
    for q in quotes:
        grouped[(q["event"], q["player"], q["line"])].append(q)
    contracts = []
    for (event, player, line), qs in grouped.items():
        newest = max(q["observed"] or "" for q in qs)
        by_book = collections.defaultdict(dict)
        for q in qs:
            if (q["observed"] or "") != newest:
                continue
            slot = by_book[q["book"]]
            if q["side"] is not None:
                slot[q["side"]] = q["price"]
            else:
                slot.setdefault("_listed", True)
        first = qs[0]
        two_sided = {}
        one_sided_books = []
        listed_only = []
        for book, sides in by_book.items():
            over, under = sides.get("Over"), sides.get("Under")
            if over is not None and under is not None:
                try:
                    booksum = odds_math.booksum([over, under])
                except (odds_math.OddsError, TypeError, ValueError):
                    continue
                if booksum < MIN_TWO_WAY_BOOKSUM:
                    continue
                two_sided[book] = (over, under)
            elif over is not None or under is not None:
                one_sided_books.append(book)
            else:
                listed_only.append(book)
        contracts.append({
            "event": event, "player": player, "line": line,
            "date": first["date"], "commence": first["commence"],
            "observed": newest, "books_any": len(by_book),
            "two_sided": two_sided, "one_sided": one_sided_books,
            "listed_only": listed_only,
        })
    return contracts


def contract_holds(contract):
    """Per two-sided book: (margin_pct, hold_pct)."""
    out = []
    for book, (over, under) in contract["two_sided"].items():
        out.append((odds_math.margin([over, under]) * 100.0,
                    odds_math.hold_percentage([over, under])))
    return out


def fair_over(contract):
    """Mean of per-book proportional de-vig; None with no two-sided book."""
    vals = []
    for over, under in contract["two_sided"].values():
        fo, _fu = odds_math.devig_two_way(over, under)
        vals.append(fo)
    return None if not vals else sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# Settlement index (presence only)
# ---------------------------------------------------------------------------

SLATE_UTC_OFFSET_HOURS = -4   # Eastern daylight time; no MLB first pitch falls
                              # between 04:00Z and 16:00Z, so the slate date
                              # of an event is its UTC commence time minus 4h.


def load_event_games(paths):
    """(event_id -> game_pk for resolved, unambiguous events,
        slate date -> set of every event_id on that slate, tally).
    Lines are gated on commence_time so no sealed-window event is parsed."""
    rows, tally = read_dated(paths.event_game_map, "commence_time", WINDOW_START)
    out = {}
    slate = collections.defaultdict(set)
    for r in rows:
        if r.get("resolved") and not r.get("ambiguous") and r.get("game_pk") is not None:
            out[r.get("event_id")] = int(r["game_pk"])
        moment = _parse_utc(r.get("commence_time"))
        if moment is not None and r.get("event_id"):
            day = (moment + _dt.timedelta(hours=SLATE_UTC_OFFSET_HOURS)).date().isoformat()
            slate[day].add(r["event_id"])
    return out, slate, tally


def load_box_keys(paths):
    """Set of (game_pk, type, normalised name) from the box store, read
    through the sealed gate. Only the key is kept, never a stat."""
    rows, tally = read_dated(paths.boxscores, "date", WINDOW_START)
    keys = collections.defaultdict(int)
    dates = set()
    for r in rows:
        t = r.get("type")
        if t not in ("pitcher", "batter"):
            continue
        keys[(r.get("game_pk"), t, norm_name(r.get("player_name")))] += 1
        if r.get("date"):
            dates.add(r["date"])
    return keys, dates, tally


# ---------------------------------------------------------------------------
# Per-family measurement
# ---------------------------------------------------------------------------

def measure_family(fam, contracts, rows_dates, event_games, box_keys,
                   box_dates, since, slate_by_date=None):
    out = {"sport": fam.sport, "family": fam.name, "market": fam.market,
           "store": fam.store, "settle_module": fam.settle_module,
           "provider_documents_key": fam.market in PROVIDER_DOCUMENTED}
    if fam.store is None or contracts is None:
        out["captured"] = False
        return out
    out["captured"] = True
    dates = sorted(d for d in rows_dates if d and d >= since)
    out["dates_since"] = len(dates)
    out["first_date"] = dates[0] if dates else None
    out["last_date"] = dates[-1] if dates else None
    out["missing_dates"] = ([d for d in _days(dates[0], dates[-1])
                             if d not in set(dates)] if dates else [])
    seen = [c for c in contracts if c["date"] and c["date"] >= since]
    # FINAL BOARD: a contract counts only if it is on its game's newest board
    # for this family. A line a book moved off (or withdrew) at the last
    # fetch is a different, stale contract and is counted apart.
    final_obs = {}
    for c in seen:
        if c["observed"] > final_obs.get(c["event"], ""):
            final_obs[c["event"]] = c["observed"]
    cs = [c for c in seen if c["observed"] == final_obs[c["event"]]]
    out["contracts_seen"] = len(seen)
    out["contracts_off_final_board"] = len(seen) - len(cs)
    out["contracts"] = len(cs)
    elig = [c for c in cs if c["two_sided"]]
    out["eligible"] = len(elig)
    events = {c["event"] for c in cs}
    out["games"] = len(events)

    per_date = collections.Counter(c["date"] for c in elig)
    games_per_date = collections.defaultdict(set)
    for c in elig:
        games_per_date[c["date"]].add(c["event"])
    out["lines_per_date_median"] = _median(list(per_date.values()))
    out["lines_per_date_min"] = min(per_date.values()) if per_date else None
    out["lines_per_date_max"] = max(per_date.values()) if per_date else None
    out["games_per_date_median"] = _median([len(v) for v in games_per_date.values()])

    ev_elig = collections.Counter(c["event"] for c in elig)
    ev_elig2 = collections.Counter(c["event"] for c in elig
                                   if len(c["two_sided"]) >= 2)
    ev_elig6 = collections.Counter(c["event"] for c in elig
                                   if len(c["two_sided"]) >= MIN_BOOKS)
    n_events = len(events) or 1
    out["lines_per_game_mean_ge1"] = _round(sum(ev_elig.values()) / n_events)
    out["lines_per_game_mean_ge2"] = _round(sum(ev_elig2.values()) / n_events)
    out["lines_per_game_mean_ge6"] = _round(sum(ev_elig6.values()) / n_events)
    # one contract per player-game (the registration's primary unit): count
    # distinct (event, player) among eligible contracts with >= 2 / >= 6 books
    for key, thr in (("ge2", 2), ("ge6", MIN_BOOKS)):
        pl = {(c["event"], c["player"]) for c in elig
              if len(c["two_sided"]) >= thr}
        out["players_per_game_mean_" + key] = _round(len(pl) / n_events)
        out["player_games_" + key] = len(pl)
    post_events = {c["event"] for c in cs if c["date"] >= POSTSEASON_START}
    out["postseason_games"] = len(post_events)
    for key, thr in (("ge1", 1), ("ge2", 2), ("ge6", MIN_BOOKS)):
        n = sum(1 for c in elig if c["date"] >= POSTSEASON_START
                and len(c["two_sided"]) >= thr)
        out["postseason_lines_per_game_mean_" + key] = (
            _round(n / len(post_events)) if post_events else None)

    out["books_any_median"] = _median([c["books_any"] for c in elig])
    out["two_sided_books_median"] = _median([len(c["two_sided"]) for c in elig])
    out["pct_ge2_two_sided"] = _pct(sum(1 for c in elig if len(c["two_sided"]) >= 2),
                                    len(elig))
    out["pct_ge6_two_sided"] = _pct(
        sum(1 for c in elig if len(c["two_sided"]) >= MIN_BOOKS), len(elig))

    # sides: of every (contract, book) with any price, how many one-sided
    n_two = sum(len(c["two_sided"]) for c in cs)
    n_one = sum(len(c["one_sided"]) for c in cs)
    out["book_quotes_two_sided"] = n_two
    out["book_quotes_one_sided"] = n_one
    out["pct_book_quotes_one_sided"] = _pct(n_one, n_one + n_two)
    one_by_book = collections.Counter(b for c in cs for b in c["one_sided"])
    out["one_sided_by_book"] = dict(one_by_book.most_common(5))
    out["contracts_with_no_two_sided_book"] = len(cs) - len(elig)

    margins, holds = [], []
    for c in elig:
        for m, h in contract_holds(c):
            margins.append(m)
            holds.append(h)
    out["hold_pairs"] = len(holds)
    if holds:
        out["margin_median_pct"] = _round(_median(margins), 2)
        out["margin_p25_pct"] = _round(_quantile(margins, 0.25), 2)
        out["margin_p75_pct"] = _round(_quantile(margins, 0.75), 2)
        out["hold_median_pct"] = _round(_median(holds), 2)
    else:
        for k in ("margin_median_pct", "margin_p25_pct", "margin_p75_pct",
                  "hold_median_pct"):
            out[k] = UNKNOWN
        out["hold_reason"] = ("no book quoted both sides of any contract in "
                              "this family; hold is not computed from one side")

    # lead time of each game's newest board
    newest_by_event = {}
    commence_by_event = {}
    for c in cs:
        if c["observed"] > newest_by_event.get(c["event"], ""):
            newest_by_event[c["event"]] = c["observed"]
        commence_by_event[c["event"]] = c["commence"]
    leads = []
    for ev, obs in newest_by_event.items():
        a, b = _parse_utc(commence_by_event[ev]), _parse_utc(obs)
        if a and b:
            leads.append((a - b).total_seconds() / 60.0)
    out["newest_board_lead_min_median"] = _round(_median(leads), 1)
    out["pct_games_newest_board_within_90"] = _pct(
        sum(1 for x in leads if 0 <= x <= CLOSE_MINUTES), len(leads))
    close_contracts = [c for c in elig if _lead_ok(c)]
    out["eligible_close_board_contracts"] = len(close_contracts)
    out["eligible_close_board_ge6"] = sum(
        1 for c in close_contracts if len(c["two_sided"]) >= MIN_BOOKS)

    # slate coverage: games with any eligible line / every game on those slates
    slate_days = [d for d in (slate_by_date or {}) if d >= since]
    slate_total = sum(len(slate_by_date[d]) for d in slate_days)
    slate_all = (set().union(*(slate_by_date[d] for d in slate_days))
                 if slate_days else set())
    captured_events = {c["event"] for c in elig}
    out["slate_games"] = slate_total
    out["slate_games_captured"] = len(captured_events & slate_all)
    out["slate_coverage_pct"] = _pct(len(captured_events & slate_all), slate_total)
    out["expected_lines_per_week_ge2_at_14"] = _round(
        out["lines_per_game_mean_ge2"] * 14, 0)
    out["expected_lines_per_week_ge2_at_28"] = _round(
        out["lines_per_game_mean_ge2"] * 28, 0)

    # settlement presence
    def settleable(c):
        pk = event_games.get(c["event"])
        if pk is None:
            return False
        return (pk, fam.box_type, norm_name(c["player"])) in box_keys
    sett = [c for c in elig if settleable(c)]
    out["settleable_eligible"] = len(sett)
    out["settleable_ge2"] = sum(1 for c in sett if len(c["two_sided"]) >= 2)
    out["settleable_ge6"] = sum(1 for c in sett if len(c["two_sided"]) >= MIN_BOOKS)
    out["settleable_games"] = len({c["event"] for c in sett})
    out["settleable_dates"] = len({c["date"] for c in sett})
    out["eligible_unmapped_event"] = sum(1 for c in elig
                                         if c["event"] not in event_games)
    out["eligible_no_box_row"] = sum(
        1 for c in elig if c["event"] in event_games and not settleable(c)
        and c["date"] in box_dates)
    out["eligible_box_not_yet_ingested_date"] = sum(
        1 for c in elig if c["date"] not in box_dates)
    return out


def _lead_ok(c):
    a, b = _parse_utc(c["commence"]), _parse_utc(c["observed"])
    if not (a and b):
        return False
    return 0 <= (a - b).total_seconds() / 60.0 <= CLOSE_MINUTES


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------

def credit_days(paths, since=WINDOW_START):
    rows, tally = read_dated(paths.credit_log, "utc", since)
    per_day = collections.OrderedDict()
    prev = None
    big = []
    for r in rows:
        rem = r.get("credits_remaining")
        day = (r.get("utc") or "")[:10]
        if rem is None:
            continue
        d = per_day.setdefault(day, {"rows": 0, "spend": 0, "last": None,
                                     "min_remaining": rem})
        d["rows"] += 1
        d["min_remaining"] = min(d["min_remaining"], rem)
        d["last"] = rem
        if prev is not None and rem < prev:
            step = prev - rem
            d["spend"] += step
            if step >= 1000:
                big.append((r.get("utc"), step, r.get("caller")))
        prev = rem
    return per_day, big, tally


def credit_summary(per_day):
    days = [(d, v["spend"]) for d, v in per_day.items()]
    spends = [s for _d, s in days]
    full = [s for _d, s in days if s >= 100]
    return {"days": len(days), "median": _median(spends),
            "median_active_days_ge100": _median(full),
            "min": min(spends) if spends else None,
            "max": max(spends) if spends else None,
            "days_under_100": [d for d, s in days if s < 100]}


def live_credit_days(paths, since=WINDOW_START):
    rows, tally = read_dated(paths.credit_log_live, "utc", since)
    per_day = collections.Counter()
    for r in rows:
        used = r.get("credits_used_last")
        if isinstance(used, int):
            per_day[(r.get("utc") or "")[:10]] += used
    return per_day, tally


def marker_credits(path, since, field="game_date", marker_test=None):
    """Billed credits per fetch from one store's marker rows (the store's own
    one-row-per-billed-fetch ledger)."""
    rows, tally = read_dated(path, field, since)
    fetches = []
    for r in rows:
        if marker_test(r) and r.get("credits_last") is not None:
            fetches.append(r)
    dist = collections.Counter(r["credits_last"] for r in fetches)
    per_day = collections.Counter()
    for r in fetches:
        per_day[r.get("game_date")] += r["credits_last"]
    return {"fetches": len(fetches), "distribution": dict(sorted(dist.items())),
            "credits": sum(r["credits_last"] for r in fetches),
            "days": len(per_day),
            "median_credits_per_day": _median(list(per_day.values())),
            "tally": tally}


# ---------------------------------------------------------------------------
# Feature stores
# ---------------------------------------------------------------------------

def feature_stores(paths, statcast_manifest_note=None):
    out = []
    for label, path, field, what in (
            ("pitcher game logs", paths.pitcher_logs, "date",
             "per pitcher per game: IP, ER, H, BB, K, BF, pitches"),
            ("bullpen log", paths.bullpen_log, "date",
             "per relief appearance"),
            ("posted lineups", paths.lineups, "date",
             "batting order per game with observed_utc"),
            ("box scores 2026 (settlement)", paths.boxscores, "date",
             "per player per game box lines")):
        s = date_span(path, field)
        out.append({"store": label,
                    "path": (path.relative_to(paths.root).as_posix()
                             if path.is_relative_to(paths.root) else str(path)),
                    "what": what, "span": s})
    # handedness: count only
    hand = paths.handedness
    hand_n = None
    if hand.exists():
        with open(hand, "r", encoding="utf-8") as fh:
            hand_n = fh.read().count('"bats"')
    out.append({"store": "handedness", "path": "data/historical/handedness.json",
                "what": "bats/throws per player id; static", "players": hand_n})
    for label, p in (("pitcher arsenal (season to date)", paths.arsenal_pitcher),
                     ("batter arsenal (season to date)", paths.arsenal_batter)):
        as_of = None
        if p.exists():
            with open(p, "r", encoding="utf-8") as fh:
                m = re.search(r'"as_of"\s*:\s*"([^"]+)"', fh.read(400))
                as_of = m.group(1) if m else None
        out.append({"store": label, "path": str(p.name), "as_of": as_of,
                    "present": p.exists(),
                    "what": "leaderboard snapshot, NOT point in time"})
    sc = paths.statcast_manifest
    if sc.exists():
        with open(sc, "r", encoding="utf-8") as fh:
            windows = list((json.load(fh).get("windows") or {}).keys())
        ends = sorted(w.split("..")[-1] for w in windows if ".." in w)
        out.append({"store": "Statcast pitches", "path": str(sc), "present": True,
                    "windows": len(windows),
                    "first_window": min(windows) if windows else None,
                    "last_window_end": ends[-1] if ends else None})
    else:
        out.append({"store": "Statcast pitches", "path": str(sc),
                    "present": False})
    return out


def nfl_player_data(paths):
    info = {"manifest_present": paths.bdl_manifest.exists(),
            "nfl_endpoints": {}, "files_on_disk": []}
    if paths.bdl_manifest.exists():
        with open(paths.bdl_manifest, "r", encoding="utf-8") as fh:
            man = json.load(fh)
        ep = collections.Counter(v.get("endpoint") for v in man.values()
                                 if v.get("sport") == "nfl")
        info["nfl_endpoints"] = dict(ep)
    if paths.bdl_nfl_dir.exists():
        info["files_on_disk"] = sorted(p.name for p in paths.bdl_nfl_dir.iterdir())
    return info


# ---------------------------------------------------------------------------
# Raw archive scan (optional): which market keys were ever returned
# ---------------------------------------------------------------------------

def raw_market_keys(paths):
    keys = collections.Counter()
    files = 0
    skipped_sealed = 0
    base = paths.raw_dir
    if not base.exists():
        return {"missing": True}
    for gz in sorted(base.glob("*/*/*/*.jsonl.gz")):
        try:
            day = "-".join(gz.parts[-4:-1])        # 2026/09/03 -> 2026-09-03
            day = day.replace("/", "-")
        except Exception:  # noqa: BLE001
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
            continue
        if in_sealed(day):
            skipped_sealed += 1
            continue
        files += 1
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                payload = rec.get("payload")
                events = payload if isinstance(payload, list) else [payload]
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    sport = ev.get("sport_key")
                    for b in ev.get("bookmakers") or []:
                        for m in b.get("markets") or []:
                            keys[(sport, m.get("key"))] += 1
    return {"files": files, "sealed_files_skipped": skipped_sealed,
            "keys": {"%s/%s" % k: v for k, v in sorted(keys.items(),
                                                       key=lambda kv: str(kv[0]))}}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_inventory(paths, since=WINDOW_START, raw_scan=False):
    inv = {"since": since, "sealed_window": [SEALED_START, SEALED_END],
           "stores": {}, "sealed_skipped": {}}

    pp_rows, t = read_dated(paths.prop_prices, "game_date", since)
    inv["stores"]["prop_prices"] = t
    bp_rows, t2 = read_dated(paths.batter_props, "game_date", since)
    inv["stores"]["batter_props"] = t2
    event_games, slate_by_date, t3 = load_event_games(paths)
    inv["stores"]["event_game_map"] = t3
    box_keys, box_dates, t4 = load_box_keys(paths)
    inv["stores"]["boxscores_2026"] = t4
    inv["box_dates"] = sorted(box_dates)

    families = []
    cache = {}
    for fam in FAMILIES:
        contracts = None
        dates = set()
        if fam.store == "prop_prices":
            contracts = build_contracts(_quotes_prop_prices(pp_rows, fam.market))
            dates = {r.get("game_date") for r in pp_rows
                     if r.get("market") == fam.market}
        elif fam.store == "batter_props":
            contracts = build_contracts(_quotes_batter_props(bp_rows, fam.market))
            dates = {r.get("game_date") for r in bp_rows
                     if r.get("market") == fam.market}
        row = measure_family(fam, contracts, dates, event_games, box_keys,
                             box_dates, since, slate_by_date)
        cache[fam.name] = row
        families.append(row)
    inv["families"] = families

    # which market keys appear in any prop store at all (for the NOT captured rows)
    seen = collections.Counter()
    for r in pp_rows:
        if r.get("market"):
            seen[r["market"]] += 1
    for r in bp_rows:
        if r.get("market"):
            seen[r["market"]] += 1
    inv["market_keys_in_prop_stores"] = dict(sorted(seen.items()))

    per_day, big, ct = credit_days(paths, since)
    inv["stores"]["credit_log"] = ct
    inv["credit_days"] = per_day
    inv["credit_big_steps"] = big
    inv["credit_summary"] = credit_summary(per_day)
    live, lt = live_credit_days(paths, since)
    inv["stores"]["credit_log_live"] = lt
    inv["credit_live_per_day"] = dict(sorted(live.items()))

    inv["marker_pitcher_k"] = marker_credits(
        paths.prop_prices, since,
        marker_test=lambda r: "market" not in r and r.get("poll"))
    inv["marker_batter"] = marker_credits(
        paths.batter_props_raw, since,
        marker_test=lambda r: r.get("poll"))

    inv["features"] = feature_stores(paths)
    inv["nfl_player_data"] = nfl_player_data(paths)
    if raw_scan:
        inv["raw_scan"] = raw_market_keys(paths)

    for name, tally in inv["stores"].items():
        inv["sealed_skipped"][name] = tally.get("sealed_skipped", 0)
    for f in inv["features"]:
        span = f.get("span")
        if span:
            inv["sealed_skipped"][f["store"]] = span["tally"].get("sealed_skipped", 0)
    return inv


# ---------------------------------------------------------------------------
# Cost model: documented rule, no network
# ---------------------------------------------------------------------------

# cost = (unique markets returned) x (regions), 1 credit each; empty
# responses are free. https://the-odds-api.com/liveapi/guides/v4/ (read
# 2026-10-01). The repo's own measured per-event costs (config/
# capture_families.json) agree: pitcher_props 1, batter_props 5 to 6.
def cost_per_game(n_markets, regions=1, snapshots=1):
    return n_markets * regions * snapshots


def fmt(v, nd=1, unit=""):
    if v is None:
        return UNKNOWN
    if isinstance(v, str):
        return v
    if isinstance(v, float):
        return ("%." + str(nd) + "f") % v + unit
    return str(v) + unit


def render_markdown(inv):
    L = []
    since = inv["since"]
    fams = inv["families"]

    L.append("### Table 1. Price availability, books and margin (since %s)" % since)
    L.append("")
    L.append("Captured families (final board of each game; see Definitions).")
    L.append("")
    L.append("| Family | Store | Capture dates (no capture on) | Slate coverage: games with a priced line / games on the slate | "
             "Eligible lines per slate (median, range) | Lines per game, mean (>=1 / >=2 / >=6 two-sided books) | "
             "Books quoting a line (median) | Two-sided books (median) | Lines with >=6 two-sided | "
             "One-sided book quotes | Margin % (median, IQR) | Hold % (median) | Lines moved off the final board |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for f in fams:
        if not f["captured"]:
            continue
        L.append("| %s %s | `%s` | %d dates, %s..%s (%s) | %d / %d (%s%%) | %s (%s-%s) | %s / %s / %s | %s | %s | %s%% | %s%% (%d of %d; %s) | %s (%s-%s) | %s | %d of %d |" % (
            f["sport"], f["family"], f["store"], f["dates_since"], f["first_date"], f["last_date"],
            ", ".join(f["missing_dates"]) or "none",
            f["slate_games_captured"], f["slate_games"], fmt(f["slate_coverage_pct"]),
            fmt(f["lines_per_date_median"], 0), fmt(f["lines_per_date_min"], 0),
            fmt(f["lines_per_date_max"], 0),
            fmt(f["lines_per_game_mean_ge1"]), fmt(f["lines_per_game_mean_ge2"]),
            fmt(f["lines_per_game_mean_ge6"]),
            fmt(f["books_any_median"]), fmt(f["two_sided_books_median"]),
            fmt(f["pct_ge6_two_sided"]), fmt(f["pct_book_quotes_one_sided"]),
            f["book_quotes_one_sided"], f["book_quotes_one_sided"] + f["book_quotes_two_sided"],
            ", ".join("%s %d" % kv for kv in f["one_sided_by_book"].items()) or "none",
            fmt(f["margin_median_pct"], 2), fmt(f["margin_p25_pct"], 2),
            fmt(f["margin_p75_pct"], 2), fmt(f["hold_median_pct"], 2),
            f["contracts_off_final_board"], f["contracts_seen"]))
    L.append("")
    L.append("Player-games with a priced line (one contract per player-game, the unit a paired comparison would use): " + "; ".join(
        "%s %s: %s per game with >=2 two-sided books (%d player-games), %s per game with >=6 (%d)" % (
            f["sport"], f["family"], fmt(f["players_per_game_mean_ge2"]), f["player_games_ge2"],
            fmt(f["players_per_game_mean_ge6"]), f["player_games_ge6"])
        for f in fams if f["captured"]))
    L.append("")
    L.append("Not captured (UNKNOWN for every price, book, margin and sample column):")
    L.append("")
    L.append("| Family | Market key | In any prop store | Provider documents the key |")
    L.append("|---|---|---|---|")
    for f in fams:
        if f["captured"]:
            continue
        L.append("| %s %s | `%s` | NO (0 rows in `prop_prices`, `batter_props`%s) | %s |" % (
            f["sport"], f["family"], f["market"],
            "; 0 raw responses in the archive" if "raw_scan" in inv else "",
            "yes" if f["provider_documents_key"] else "no"))
    L.append("")

    L.append("### Table 2. Closing-board feasibility, settleable sample, expected volume (since %s)" % since)
    L.append("")
    L.append("| Family | Median lead of each game's newest board (min before first pitch) | Games whose newest board is within 90 min | "
             "Eligible lines on a <=90 min board (of which >=6 two-sided books) | "
             "Settleable lines (eligible, box row present) | ... with >=2 two-sided | ... with >=6 | Settleable games | Settleable dates | "
             "Postseason games captured (lines / game, >=2 books) | Expected lines / week at 14 and 28 games (>=2 books) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for f in fams:
        if not f["captured"]:
            continue
        L.append("| %s %s | %s | %s%% | %d (%d) | %d | %d | %d | %d | %d | %d (%s) | %s / %s |" % (
            f["sport"], f["family"], fmt(f["newest_board_lead_min_median"]),
            fmt(f["pct_games_newest_board_within_90"]),
            f["eligible_close_board_contracts"], f["eligible_close_board_ge6"],
            f["settleable_eligible"], f["settleable_ge2"], f["settleable_ge6"],
            f["settleable_games"], f["settleable_dates"], f["postseason_games"],
            fmt(f["postseason_lines_per_game_mean_ge2"]),
            fmt(f["expected_lines_per_week_ge2_at_14"], 0), fmt(f["expected_lines_per_week_ge2_at_28"], 0)))
    L.append("")
    L.append("Settleable-line accounting (eligible lines on the final board that are NOT settleable, and why): " + "; ".join(
        "%s %s: %d eligible, %d no mapped game, %d on a date with no box rows yet, %d with a mapped game and date but no box row"
        % (f["sport"], f["family"], f["eligible"], f["eligible_unmapped_event"],
           f["eligible_box_not_yet_ingested_date"], f["eligible_no_box_row"])
        for f in fams if f["captured"]))
    L.append("")
    L.append("Box-score dates ingested in the forward store: %s" % (
        ", ".join(inv["box_dates"]) or "none"))
    L.append("")

    L.append("### Table 3. Odds API credits")
    L.append("")
    cs = inv["credit_summary"]
    L.append("Daily account spend from `data/processed/credit_log.jsonl` (sum of drops in `credits_remaining` between consecutive rows, "
             "attributed to the UTC day of the later row; rises are treated as a monthly reset and not counted): "
             "%s days since %s, median %s, median of days with spend >= 100 %s, min %s, max %s. Days under 100: %s."
             % (cs["days"], since, fmt(cs["median"], 0), fmt(cs["median_active_days_ge100"], 0),
                fmt(cs["min"], 0), fmt(cs["max"], 0), ", ".join(cs["days_under_100"]) or "none"))
    L.append("")
    L.append("| UTC day | log rows | credits spent | last credits_remaining |")
    L.append("|---|---|---|---|")
    for d, v in inv["credit_days"].items():
        L.append("| %s | %d | %d | %s |" % (d, v["rows"], v["spend"], v["last"]))
    L.append("")
    if inv["credit_big_steps"]:
        L.append("Single steps of 1,000 credits or more: " + "; ".join(
            "%s %d (%s)" % b for b in inv["credit_big_steps"]))
        L.append("")
    live = inv["credit_live_per_day"]
    L.append("In-play capture (`data/live/credit_log_live.jsonl`, 1 credit per logged call): %d days, %d credits in all; per day: %s"
             % (len(live), sum(live.values()),
                ", ".join("%s %d" % kv for kv in live.items()) or "none"))
    L.append("")
    for key, label in (("marker_pitcher_k", "Pitcher strikeouts (`prop_prices.jsonl` markers)"),
                       ("marker_batter", "Batter props, 6 markets per call (`batter_props_raw.jsonl` markers)")):
        m = inv[key]
        L.append("%s: %d billed fetches since %s, credits per fetch distribution %s, %d credits, median %s credits per capture day."
                 % (label, m["fetches"], since, json.dumps(m["distribution"]), m["credits"],
                    fmt(m["median_credits_per_day"], 0)))
    L.append("")
    L.append("**Cost model (documented rule: credits = unique markets returned x regions, 1 each; empty responses free).** "
             "Per game, per snapshot, one region unless stated. Weekly figures use 14 and 28 games a week (the 2 to 4 games a day of the "
             "postseason); NFL uses 16.")
    L.append("")
    L.append("| Closing-board capture | Markets | Credits / game / snapshot / region | Per week at 14 games | at 28 games | at 28 games, 2 regions | % of 100,000 monthly allowance (28 games, 1 region, x4.3 weeks) |")
    L.append("|---|---|---|---|---|---|---|")
    plans = (("MLB pitcher strikeouts", 1, 14, 28), ("MLB pitcher outs", 1, 14, 28),
             ("MLB hits allowed", 1, 14, 28), ("MLB earned runs", 1, 14, 28),
             ("MLB all four pitcher markets", 4, 14, 28),
             ("MLB batter hits", 1, 14, 28), ("MLB batter total bases", 1, 14, 28),
             ("MLB batter hits + total bases", 2, 14, 28),
             ("MLB six batter markets (today's gate call)", 6, 14, 28))
    for label, nm, g1, g2 in plans:
        c = cost_per_game(nm)
        L.append("| %s | %d | %d | %d | %d | %d | %.2f%% |" % (
            label, nm, c, c * g1, c * g2, c * g2 * 2, 100.0 * c * g2 * 4.3 / MONTHLY_ALLOWANCE))
    nfl_plans = (("NFL QB passing yards", 1), ("NFL four families (pass yds, receptions, receiving yds, rush yds)", 4))
    for label, nm in nfl_plans:
        c = cost_per_game(nm)
        L.append("| %s (16 games) | %d | %d | %d | n/a | %d | %.2f%% |" % (
            label, nm, c, c * 16, c * 16 * 2, 100.0 * c * 16 * 4.3 / MONTHLY_ALLOWANCE))
    L.append("")

    L.append("### Table 4. Feature and settlement stores (measured spans; no stat value read)")
    L.append("")
    L.append("| Store | Path | First unsealed date | Last date | Unsealed lines by year | Lines on or after %s | Sealed-window lines skipped unparsed |" % since)
    L.append("|---|---|---|---|---|---|---|")
    for f in inv["features"]:
        s = f.get("span")
        if s is None:
            continue
        if s.get("missing"):
            L.append("| %s | `%s` | %s | %s | %s | %s | %s |" % (f["store"], f["path"], UNKNOWN + " (store absent)", UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN))
        else:
            L.append("| %s | `%s` | %s | %s | %s | %d | %d |" % (
                f["store"], f["path"], s["first_unsealed"], s["last"],
                ", ".join("%s: %d" % kv for kv in s["by_year"].items()),
                s["lines_since"], s["tally"]["sealed_skipped"]))
    L.append("")
    for f in inv["features"]:
        if "span" in f:
            continue
        if f["store"] == "handedness":
            L.append("- handedness: %s players with bats/throws, static file." % fmt(f["players"], 0))
        elif f["store"] == "Statcast pitches":
            if f.get("present"):
                L.append("- Statcast pitch store (`%s`): %d windows, first window %s, last window ends %s." % (
                    f["path"], f["windows"], f["first_window"], f["last_window_end"]))
            else:
                L.append("- Statcast pitch store: manifest not found at `%s` in this checkout: %s." % (f["path"], UNKNOWN))
        else:
            L.append("- %s: present %s, as_of %s (%s)." % (f["store"], f["present"], fmt(f.get("as_of")), f["what"]))
    npd = inv["nfl_player_data"]
    L.append("- NFL player data: BALLDONTLIE manifest present %s; NFL endpoints in it: %s; files on disk in `data/historical/balldontlie/nfl/`: %s."
             % (npd["manifest_present"], json.dumps(npd["nfl_endpoints"]) or "none",
                ", ".join(npd["files_on_disk"]) or "none"))
    L.append("")
    if "raw_scan" in inv:
        rs = inv["raw_scan"]
        L.append("### Table 5. Market keys ever returned (raw archive, `data/raw/oddsapi/`)")
        L.append("")
        if rs.get("missing"):
            L.append("Raw archive not present: %s." % UNKNOWN)
        else:
            L.append("%d raw capture files opened (%d dated inside the sealed window skipped unopened)." % (
                rs["files"], rs["sealed_files_skipped"]))
            L.append("")
            L.append("| sport / market key | market occurrences in raw responses |")
            L.append("|---|---|")
            for k, v in rs["keys"].items():
                L.append("| %s | %d |" % (k, v))
        L.append("")
    L.append("### Table 6. Sealed-window accounting")
    L.append("")
    L.append("Lines dated %s..%s met while reading each store (all skipped, none parsed):" % (SEALED_START, SEALED_END))
    L.append("")
    L.append("| Store | Lines read | Sealed-window lines skipped | Lines before %s (not parsed) | Lines parsed |" % since)
    L.append("|---|---|---|---|---|")
    for name, t in inv["stores"].items():
        if t.get("missing"):
            L.append("| %s | store absent | - | - | - |" % name)
        else:
            L.append("| %s | %d | %d | %d | %d |" % (name, t["lines"], t["sealed_skipped"], t["pre_window"], t["parsed"]))
    L.append("")
    return "\n".join(L)


def update_doc(path, block):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if GEN_BEGIN not in text or GEN_END not in text:
        raise SystemExit("markers %r / %r not found in %s" % (GEN_BEGIN, GEN_END, path))
    head, rest = text.split(GEN_BEGIN, 1)
    _old, tail = rest.split(GEN_END, 1)
    new = head + GEN_BEGIN + "\n" + block + "\n" + GEN_END + tail
    path.write_text(new, encoding="utf-8", newline="\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--since", default=WINDOW_START)
    ap.add_argument("--raw-scan", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--statcast-manifest", default=None)
    ap.add_argument("--update-doc", default=None)
    args = ap.parse_args(argv)
    if args.since <= SEALED_END:
        raise SystemExit("--since must be after the sealed window end %s" % SEALED_END)
    paths = Paths(args.root, args.statcast_manifest)
    inv = build_inventory(paths, args.since, args.raw_scan)
    if args.json:
        print(json.dumps(inv, indent=1, sort_keys=True, default=str))
        return 0
    block = render_markdown(inv)
    if args.update_doc:
        update_doc(args.update_doc, block)
    else:
        print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
