"""INFO_TIMING_V1: does a posted lineup move the market afterwards?

Pure measurement code for ONE pre-registered paper study,
`docs/PREREG_INFO_TIMING.md` (committed before this file existed). If this
module and that document ever disagree, the document wins and this module is
wrong.

WHAT IS MEASURED
----------------
For each admissible `lineup_posted` event (`src.pipeline.rosterwatch`), the
contracts the posting favours (R1 posted batter: hits / total-bases Over; R2
quoted batter in neither posted lineup: Under; R3 a regular rested: opponent
moneyline, opponent run line, total Under), two numbers in probability points:

  M1 = 100 * (fair_close - fair_entry)        drift toward the favoured side
  M2 = 100 * (fair_close - avg_raw_entry)     CLV at the board AVERAGE price

`entry` is the first valid capture strictly after the information time and
strictly before first pitch; `close` is the last valid capture strictly before
first pitch and strictly after the entry. Nothing here reads an outcome: no
score, no hit, no settlement. Best-price CLV is computed as a descriptive
number and is PRICE IMPROVEMENT from line shopping, never edge.

POINT-IN-TIME
-------------
Every price row at or after first pitch is dropped where the series is built
(`build_series`), the entry is strictly after `t_info`, and `measure` asserts
both. Lineup history for R3 is strictly before the game date. Any date inside
2026-01-01..2026-08-27 raises `SealedDataError`; the stream readers discard an
out-of-window raw line by its date text BEFORE parsing it.
"""

from __future__ import annotations

import csv
import glob
import gzip
import io
import json
import math
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

from src.core import odds as om
from src.model.discovery import clustered_bootstrap

# ---------------------------------------------------------------------------
# Registered constants (PREREG sections 1, 3, 4, 5, 7). Never tuned.
# ---------------------------------------------------------------------------

WINDOW_FIRST = "2026-09-08"
WINDOW_LAST = "2026-10-15"
SEAL_FIRST = "2026-01-01"
SEAL_LAST = "2026-08-27"
HISTORY_FIRST = "2026-08-28"

PROP_MARKETS = ("batter_hits", "batter_total_bases")
GAME_MARKETS = ("moneyline", "run_line", "total")
PROP_MIN_BOOKS = 2
PROP_MIN_BOOKSUM = 0.98
GAME_MIN_BOOKS = 6
RUN_LINE_ABS = 1.5

REG_LAST_N = 10
REG_MIN_STARTS = 7
LINEUP_SIZE = 9

RESAMPLES = 2000
SEED = 20261016
MIN_UNITS = 30
MIN_DATES = 5

COVERAGE_MINUTES = (30, 60, 120)
CADENCE_WINDOW_MIN = 360
RAW_MATCH_SECONDS = 300

OTHER = {"Over": "Under", "Under": "Over", "home": "away", "away": "home"}

VERDICT_SUPPORTED = "SUPPORTED"
VERDICT_NOT_SUPPORTED = "NOT SUPPORTED"
VERDICT_NOT_MEASURABLE = "NOT MEASURABLE"
REGISTRY_RESULT = {VERDICT_SUPPORTED: "candidate",
                   VERDICT_NOT_SUPPORTED: "null",
                   VERDICT_NOT_MEASURABLE: "below_floor"}


class SealedDataError(RuntimeError):
    """A date inside the sealed window (or 2025) reached the harness."""


def assert_allowed_date(day) -> str:
    d = str(day or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        raise SealedDataError(f"unparseable date {day!r}")
    if d.startswith("2025") or SEAL_FIRST <= d <= SEAL_LAST:
        raise SealedDataError(f"{d} is sealed or tuning-only; refused")
    return d


def in_window(day) -> bool:
    d = str(day or "")[:10]
    return WINDOW_FIRST <= d <= WINDOW_LAST


def parse_t(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def minutes(a, b) -> float:
    """b - a in minutes."""
    return (b - a).total_seconds() / 60.0


# ---------------------------------------------------------------------------
# Names (PREREG section 3)
# ---------------------------------------------------------------------------

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def norm_name(name) -> str:
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    for ch in ".'-":
        s = s.replace(ch, " ")
    parts = s.split()
    while parts and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


def name_index(id_to_name: dict) -> dict:
    """{normalised name: set(person ids)} over every known id."""
    out = defaultdict(set)
    for pid, name in id_to_name.items():
        n = norm_name(name)
        if n:
            out[n].add(int(pid))
    return out


# ---------------------------------------------------------------------------
# Consensus and one unit's measurement (PREREG section 5)
# ---------------------------------------------------------------------------

def _raw(price):
    try:
        return om.american_to_probability(price)
    except (om.OddsError, TypeError, ValueError):
        return None


def consensus(books: dict, side: str, *, min_books: int, min_booksum=None):
    """Favoured-side consensus on one capture's books, or None if invalid.

    `books` = {book: {side: american price}}. A book counts only with both
    sides quoted (and, for props, raw implied probabilities summing to at
    least `min_booksum`). Returns fair (mean de-vigged), avg_raw (mean raw
    implied, the break-even of the average price) and best_raw (lowest raw
    implied, the best price's break-even), plus the book count.
    """
    other = OTHER[side]
    fairs, raws = [], []
    for book in sorted(books or {}):
        sides = books[book] or {}
        mine, theirs = sides.get(side), sides.get(other)
        if mine is None or theirs is None:
            continue
        a, b = _raw(mine), _raw(theirs)
        if a is None or b is None:
            continue
        if min_booksum is not None and a + b < min_booksum:
            continue
        try:
            fair, _ = om.devig_two_way(mine, theirs)
        except (om.OddsError, ZeroDivisionError, ValueError):
            continue
        fairs.append(fair)
        raws.append(a)
    if len(fairs) < min_books:
        return None
    return {"fair": sum(fairs) / len(fairs), "avg_raw": sum(raws) / len(raws),
            "best_raw": min(raws), "n_books": len(fairs)}


def build_series(instants: dict, first_pitch) -> list:
    """[(datetime, books)] sorted, with every capture at/after first pitch dropped."""
    out = []
    for stamp, books in (instants or {}).items():
        t = parse_t(stamp)
        if t is None or first_pitch is None or t >= first_pitch:
            continue
        out.append((t, books))
    out.sort(key=lambda x: x[0])
    return out


def measure(series, side, *, t_info, t_pre, first_pitch, min_books,
            min_booksum=None) -> dict:
    """One unit. `series` from `build_series` (already pre-pitch only)."""
    valid = []
    for t, books in series:
        if t >= first_pitch:
            continue  # belt and braces: build_series already dropped these
        c = consensus(books, side, min_books=min_books, min_booksum=min_booksum)
        if c is not None:
            valid.append((t, c))
    entry = next(((t, c) for t, c in valid if t > t_info), None)
    if entry is None:
        return {"status": "NO_ENTRY_CAPTURE"}
    close = valid[-1]
    if close[0] <= entry[0]:
        return {"status": "NO_LATER_CAPTURE",
                "lag_min": minutes(t_info, entry[0])}
    assert t_info < entry[0] < close[0] < first_pitch
    pre = None
    if t_pre is not None:
        pre = next(((t, c) for t, c in reversed(valid) if t <= t_pre), None)
    e, k = entry[1], close[1]
    return {
        "status": "OK",
        "entry_utc": entry[0].isoformat(), "close_utc": close[0].isoformat(),
        "lag_min": minutes(t_info, entry[0]),
        "close_to_pitch_min": minutes(close[0], first_pitch),
        "entry_books": e["n_books"], "close_books": k["n_books"],
        "fair_entry": e["fair"], "fair_close": k["fair"],
        "m1": 100.0 * (k["fair"] - e["fair"]),
        "m2": 100.0 * (k["fair"] - e["avg_raw"]),
        "m2_best": 100.0 * (k["fair"] - e["best_raw"]),
        "pre_move": (100.0 * (e["fair"] - pre[1]["fair"]) if pre else None),
    }


def pick_line(series, side, candidates_for, *, t_info, min_books, prefer):
    """For game lines whose contract is a line value: at the first capture
    after t_info where some candidate line is valid, the line with the most
    valid books (ties broken by `prefer`, a sort key: smaller wins). Returns
    the line or None."""
    for t, by_line in series:
        if t <= t_info:
            continue
        counts = []
        for line in candidates_for(by_line):
            c = consensus(by_line[line], side, min_books=min_books)
            if c is not None:
                counts.append((-c["n_books"], prefer(line), line))
        if counts:
            counts.sort()
            return counts[0][2]
    return None


# ---------------------------------------------------------------------------
# Rules (PREREG section 4)
# ---------------------------------------------------------------------------

def regulars(history: list, team: str, game_date: str):
    """Players with >= REG_MIN_STARTS starts in `team`'s last REG_LAST_N games
    strictly before `game_date` (history dated >= HISTORY_FIRST), or None if
    the team has fewer than REG_LAST_N such games.

    `history` = [{"date", "game_pk", "team", "ids": [...]}]."""
    assert_allowed_date(game_date)
    games = [h for h in history
             if h["team"] == team and HISTORY_FIRST <= h["date"] < game_date]
    for h in games:
        assert_allowed_date(h["date"])
    games.sort(key=lambda h: (h["date"], h["game_pk"]))
    if len(games) < REG_LAST_N:
        return None
    counts = defaultdict(int)
    for h in games[-REG_LAST_N:]:
        for pid in set(h["ids"]):
            counts[pid] += 1
    return {pid for pid, n in counts.items() if n >= REG_MIN_STARTS}


def match_posted(posted_ids, id_to_name, prop_players):
    """{person id: prop player string} for posted ids, plus refusals.

    A normalised name shared by two posted ids is AMBIGUOUS_NAME for both."""
    by_norm = defaultdict(list)
    for pid in posted_ids:
        by_norm[norm_name(id_to_name.get(pid, ""))].append(pid)
    props_by_norm = defaultdict(list)
    for p in prop_players:
        props_by_norm[norm_name(p)].append(p)
    matched, refused = {}, {}
    for pid in posted_ids:
        n = norm_name(id_to_name.get(pid, ""))
        if not n:
            refused[pid] = "NO_NAME"
        elif len(by_norm[n]) > 1 or len(props_by_norm.get(n, [])) > 1:
            refused[pid] = "AMBIGUOUS_NAME"
        elif props_by_norm.get(n):
            matched[pid] = props_by_norm[n][0]
        else:
            refused[pid] = "NO_PROP_QUOTED"
    return matched, refused


def left_out(prop_players, posted_all_ids, names_idx):
    """R2: {prop player: status}. "R2" when the name maps to exactly one known
    person id that is in neither posted lineup; else the refusal cause."""
    out = {}
    posted = set(posted_all_ids)
    for p in prop_players:
        ids = names_idx.get(norm_name(p), set())
        if not ids:
            out[p] = "NAME_UNMATCHED"
        elif len(ids) > 1:
            out[p] = "AMBIGUOUS_NAME"
        elif next(iter(ids)) in posted:
            out[p] = "POSTED"
        else:
            out[p] = "R2"
    return out


# ---------------------------------------------------------------------------
# Summary statistics and the verdict (PREREG sections 5-7)
# ---------------------------------------------------------------------------

def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def cluster_se(rows, key):
    """Date-cluster-robust standard error of the mean (CR0)."""
    vals = [(r["date"], r[key]) for r in rows if r.get(key) is not None]
    n = len(vals)
    if n < 2:
        return None
    m = sum(v for _, v in vals) / n
    by = defaultdict(float)
    for d, v in vals:
        by[d] += v - m
    if len(by) < 2:
        return None
    return math.sqrt(sum(s * s for s in by.values())) / n


def summarize(rows, key) -> dict:
    use = [r for r in rows if r.get(key) is not None]
    out = {"n": len(use), "n_dates": len({r["date"] for r in use}),
           "n_events": len({r["event_key"] for r in use}),
           "mean": _mean([r[key] for r in use]), "low": None, "high": None,
           "se": cluster_se(use, key), "mde": None}
    if out["se"] is not None:
        out["mde"] = 2.8 * out["se"]
    if use:
        ci = clustered_bootstrap(use, lambda s: _mean([r[key] for r in s]),
                                 resamples=RESAMPLES, seed=SEED)
        out["low"], out["high"] = ci.get("low"), ci.get("high")
    return out


def decide(m1: dict, m2: dict) -> str:
    """The registered rule, literally (PREREG section 7)."""
    if (m2["n"] < MIN_UNITS or m2["n_dates"] < MIN_DATES
            or m2["low"] is None or m2["high"] is None):
        return VERDICT_NOT_MEASURABLE
    if m2["low"] > 0 and m1["mean"] is not None and m1["mean"] > 0:
        return VERDICT_SUPPORTED
    return VERDICT_NOT_SUPPORTED


def quantiles(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None

    def q(p):
        i = (len(xs) - 1) * p
        lo, hi = math.floor(i), math.ceil(i)
        return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)
    return {"n": len(xs), "min": xs[0], "q25": q(0.25), "median": q(0.5),
            "q75": q(0.75), "max": xs[-1]}


def lag_coverage(lags, n_events):
    """`lags` = minutes to first capture per event (None = none before pitch)."""
    got = [x for x in lags if x is not None]
    out = {"events": n_events, "with_capture": len(got),
           "none_before_pitch": n_events - len(got),
           "lag_quantiles": quantiles(got)}
    for m in COVERAGE_MINUTES:
        out[f"within_{m}"] = sum(1 for x in got if x <= m)
    return out


def median_gap(times):
    ts = sorted(times)
    gaps = [minutes(a, b) for a, b in zip(ts, ts[1:])]
    return quantiles(gaps)["median"] if gaps else None


# ---------------------------------------------------------------------------
# Stream readers (sealed lines discarded by their date text before parsing)
# ---------------------------------------------------------------------------

_DATE_RE = {
    "game_date": re.compile(r'"game_date"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
    "observed_utc": re.compile(r'"observed_utc"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
    "date": re.compile(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
    "commence_time": re.compile(r'"commence_time"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
}


def _line_date(line, field):
    m = _DATE_RE[field].search(line)
    return m.group(1) if m else None


def _keep(day, first, last) -> bool:
    if day is None:
        return False
    if day.startswith("2025") or SEAL_FIRST <= day <= SEAL_LAST:
        return False
    return first <= day <= last


def read_results(path):
    """{game_pk: {date, start, game_type, away, home, double_header}} for
    in-window and history dates. The raw line's date (second column) is tested
    before the line is parsed; score columns are never kept."""
    out = {}
    with open(path, encoding="utf-8", newline="") as fh:
        header = next(csv.reader([fh.readline()]))
        idx = {k: header.index(k) for k in ("game_pk", "date", "start_time_utc",
                                            "game_type", "away_team",
                                            "home_team", "double_header")}
        for line in fh:
            parts = line.split(",", 2)
            if len(parts) < 3 or not _keep(parts[1], HISTORY_FIRST, WINDOW_LAST):
                continue
            row = next(csv.reader(io.StringIO(line)))
            out[int(row[idx["game_pk"]])] = {
                "date": assert_allowed_date(row[idx["date"]]),
                "start": row[idx["start_time_utc"]] or None,
                "game_type": row[idx["game_type"]],
                "away": row[idx["away_team"]], "home": row[idx["home_team"]],
                "double_header": row[idx["double_header"]],
            }
    return out


def read_event_map(path):
    """(event_id -> map row, refused game_pks, game_pk -> [event ids])."""
    by_event, bad_pk = {}, set()
    pk_events = defaultdict(set)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not _keep(_line_date(line, "commence_time"), HISTORY_FIRST, "2026-10-16"):
                continue
            d = json.loads(line)
            if d.get("ambiguous"):
                bad_pk.add(str(d.get("game_pk")))
                for c in d.get("candidates") or ():
                    bad_pk.add(str(c.get("game_pk")))
                continue
            if not d.get("resolved") or d.get("game_pk") is None:
                continue
            by_event[d["event_id"]] = d
            pk_events[str(d["game_pk"])].add(d["event_id"])
    for pk, evs in pk_events.items():
        if len(evs) > 1:
            bad_pk.add(pk)
    return by_event, bad_pk, pk_events


def read_props(path, wanted_events):
    """{event_id: {(player, market, line): {stamp: {book: {side: price}}}}}"""
    out = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not _keep(_line_date(line, "game_date"), WINDOW_FIRST, WINDOW_LAST):
                continue
            d = json.loads(line)
            if d.get("market") not in PROP_MARKETS or d.get("event_id") not in wanted_events:
                continue
            assert_allowed_date(d["game_date"])
            try:
                ln = float(d.get("line"))
            except (TypeError, ValueError):
                continue
            if d.get("side") not in ("Over", "Under") or d.get("price") is None:
                continue
            key = (d["player"], d["market"], ln)
            out[d["event_id"]][key][d["observed_utc"]].setdefault(d["book"], {})[d["side"]] = d["price"]
    return out


def multibook_paths(processed_dir):
    arch = sorted(glob.glob(os.path.join(processed_dir, "archive", "odds_multibook", "*.jsonl.gz")))
    return arch + [os.path.join(processed_dir, "odds_multibook.jsonl")]


def read_game_lines(paths, wanted_events):
    """{event_id: {"moneyline": {stamp: {book: {"home","away"}}},
                   "run_line": {stamp: {(side, line): {book: {...}}}} -> stored as
                   {stamp: {line_key: {book: {side: price}}}},
                   "total": {stamp: {total: {book: {"Over","Under"}}}}},
       teams: {event_id: (away, home)}}"""
    out = defaultdict(lambda: {"moneyline": defaultdict(dict),
                               "run_line": defaultdict(lambda: defaultdict(dict)),
                               "total": defaultdict(lambda: defaultdict(dict))})
    teams = {}
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not _keep(_line_date(line, "observed_utc"), "2026-09-07", "2026-10-16"):
                    continue
                d = json.loads(line)
                ev = d.get("event_id")
                if ev not in wanted_events:
                    continue
                stamp, book, market = d["observed_utc"], d["book"], d.get("market")
                teams.setdefault(ev, set()).add((d.get("away_team"), d.get("home_team")))
                if market is None or market == "h2h":
                    if d.get("home_price") is not None and d.get("away_price") is not None:
                        out[ev]["moneyline"][stamp][book] = {"home": d["home_price"], "away": d["away_price"]}
                elif market == "spreads":
                    try:
                        hl, al = float(d["home_line"]), float(d["away_line"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if abs(hl) != RUN_LINE_ABS or hl != -al:
                        continue
                    if d.get("home_price") is None or d.get("away_price") is None:
                        continue
                    # one contract per home line value; sides "home"/"away"
                    out[ev]["run_line"][stamp][hl][book] = {"home": d["home_price"], "away": d["away_price"]}
                elif market == "totals":
                    try:
                        tot = float(d["total"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if d.get("over_price") is None or d.get("under_price") is None:
                        continue
                    out[ev]["total"][stamp][tot][book] = {"Over": d["over_price"], "Under": d["under_price"]}
    return out, teams


def read_lineup_history(path, results):
    """[{date, game_pk, team, ids}] from lineups.jsonl, dated >= HISTORY_FIRST
    and <= WINDOW_LAST, plus {person id: name} from every non-sealed row."""
    hist, names = [], {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            day = _line_date(line, "date")
            if day is None or day.startswith("2025") or SEAL_FIRST <= day <= SEAL_LAST:
                continue
            d = json.loads(line)
            if d.get("empty"):
                continue
            for side in ("away", "home"):
                for p in d.get(side) or ():
                    if p.get("person_id") is not None and p.get("name"):
                        names.setdefault(int(p["person_id"]), p["name"])
            if not (HISTORY_FIRST <= day <= WINDOW_LAST):
                continue
            g = results.get(int(d["game_pk"]))
            if g is None:
                continue
            for side in ("away", "home"):
                ids = [int(p["person_id"]) for p in d.get(side) or () if p.get("person_id") is not None]
                if ids:
                    hist.append({"date": day, "game_pk": int(d["game_pk"]),
                                 "team": g[side], "ids": ids})
    return hist, names


def raw_capture_instants(raw_root):
    """{"event": [datetimes], "featured": [datetimes]} from envelope headers."""
    out = {"event": [], "featured": []}
    pat_t = re.compile(r'"captured_utc"\s*:\s*"([^"]+)"')
    pat_k = re.compile(r'"kind"\s*:\s*"([^"]+)"')
    for month in ("09", "10"):
        for path in sorted(glob.glob(os.path.join(raw_root, "2026", month, "*", "*.jsonl.gz"))):
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    head = line[:200]
                    mt, mk = pat_t.search(head), pat_k.search(head)
                    if not mt or not mk:
                        continue
                    if not _keep(mt.group(1)[:10], "2026-09-07", "2026-10-16"):
                        continue
                    if mk.group(1) in out:
                        out[mk.group(1)].append(parse_t(mt.group(1)))
    for k in out:
        out[k].sort()
    return out


def share_matched(instants, raw_sorted, tol_s=RAW_MATCH_SECONDS):
    """Share of `instants` with a raw envelope within tol_s seconds."""
    import bisect
    if not instants:
        return None
    hit = 0
    for t in instants:
        i = bisect.bisect_left(raw_sorted, t)
        for j in (i - 1, i):
            if 0 <= j < len(raw_sorted) and abs((raw_sorted[j] - t).total_seconds()) <= tol_s:
                hit += 1
                break
    return hit / len(instants)
