"""Data coverage map: what usable n each store can support, BEFORE building.

WHY THIS EXISTS
---------------
Hypotheses here have died late for a reason that was knowable early:
lineup_vs_starter reached n=26 against a needed 100+, and M4 was capped at 308
games by F5 price coverage -- in both cases weeks of build preceded the moment
anyone counted what was on disk. This module makes that count the FIRST step.
`report()` audits every store by reading what already exists locally (never
fetching), and `expected_n` turns "games with the feature x price match x fire
rate" into a rough usable sample so a hypothesis can be rejected for data
poverty before a line of detector code is written.

WHY SEALED SEASONS ARE COUNTED BUT NOT READ
-------------------------------------------
Discovery data is 2023-2024 only; 2025 is tuning and 2026 is sealed. A coverage
map still has to say those files exist -- planning the tuning phase needs their
size -- so the audit reports them, but under a stricter rule than the discovery
seasons: per-file stores whose season is in the filename (the odds dirs) are
counted by raw LINE COUNT with the content never JSON-parsed, and mixed files
that interleave seasons (transactions, pitcher logs) have only their date/season
key examined to bucket the row. No outcome, price, or feature value from a
sealed season is ever interpreted here.

WHY PATHS ARE PARAMETERS
------------------------
Every reader takes its path (or a `root` directory) with the real on-disk
default, so tests audit a synthetic tempdir tree instead of stubbing readers --
the same file shapes the production run walks, at toy size.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.paths import historical_path
from src.pipeline import lineup_store

# The only seasons discovery may interpret. Everything else on disk is counted
# (existence is coverage information) but never parsed beyond its date key.
DISCOVERY_SEASONS = ("2023", "2024")

# Default share of feature-bearing games that also match to a usable price.
# 0.75 is the observed order of magnitude across the 2023-24 backfills -- the
# F5 market that capped M4 sat well below it, which is exactly the kind of
# surprise report() exists to surface per source.
DEFAULT_PRICE_MATCH_PCT = 0.75


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def expected_n(games_with_feature_pct, price_match_pct=DEFAULT_PRICE_MATCH_PCT,
               fire_rate=1.0, games=None, results_path=None):
    """Rough usable sample: games x feature x price match x fire rate, floored.

    All three rates are fractions in [0, 1] -- a rate outside that range is a
    caller bug and raises rather than silently producing a fantasy n. `games`
    defaults to the results-CSV game count over DISCOVERY_SEASONS; when that
    cannot be established (no CSV, no games), the answer is None, not a guess.

    The floor matters at the low end: lineup_vs_starter's n=26 would have been
    predicted here as a couple dozen, and "a couple dozen" must never round up
    into looking like it clears a 100+ requirement.
    """
    for name, value in (("games_with_feature_pct", games_with_feature_pct),
                        ("price_match_pct", price_match_pct),
                        ("fire_rate", fire_rate)):
        if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be a fraction in [0, 1], got {value!r}")
    if games is None:
        by_season = results_by_season(
            results_path if results_path is not None
            else historical_path("mlb_results.csv"))
        games = sum(by_season.get(s, 0) for s in DISCOVERY_SEASONS)
    if not games:
        return None
    return int(games * games_with_feature_pct * price_match_pct * fire_rate)


def _season_of(value):
    """'2023-05-03' / '2023' / 2023 -> '2023'; anything else -> None.

    None over a guess: a row whose date cannot be read as a 20xx season is
    counted as unknown rather than assigned to the nearest-looking year.
    """
    text = str(value or "")[:4]
    if len(text) == 4 and text.isdigit() and text.startswith("20"):
        return text
    return None


def jsonl_season_counts(path, keys=("season", "date")) -> dict:
    """Per-season data-row counts for one JSONL store.

    `keys` is the lookup order for the season -- pitcher logs carry an explicit
    "season", most stores only a "date". Rows marked {"empty": true} are
    coverage markers (the lineup-store convention), not data, and are counted
    separately; so are lines that fail to parse and rows with no readable
    season, because an audit that silently drops what it cannot classify is the
    silent-hole failure mode this module exists to prevent.
    """
    out = {"exists": False, "seasons": {}, "rows": 0, "markers": 0,
           "bad_lines": 0, "unknown_season": 0}
    target = Path(path)
    if not target.exists():
        return out
    out["exists"] = True
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                out["bad_lines"] += 1
                continue
            if not isinstance(row, dict):
                out["bad_lines"] += 1
                continue
            if row.get("empty"):
                out["markers"] += 1
                continue
            out["rows"] += 1
            season = None
            for key in keys:
                season = _season_of(row.get(key))
                if season:
                    break
            if season:
                out["seasons"][season] = out["seasons"].get(season, 0) + 1
            else:
                out["unknown_season"] += 1
    return out


def odds_event_counts(directory, parse_seasons=DISCOVERY_SEASONS) -> dict:
    """Events per season for an odds dir of mlb_<season>.jsonl files.

    The season comes from the FILENAME, so sealed seasons never need parsing:
    files outside `parse_seasons` are counted by raw line count with the
    content unread, and listed under "line_count_only" so the report can say
    the number means lines, not events. For parsed files a line is either a
    snapshot carrying an "events" list (odds_history) or one event per line
    (odds_first_five); both shapes are handled so one counter serves both dirs.
    """
    out = {"exists": False, "seasons": {}, "line_count_only": []}
    base = Path(directory)
    if not base.is_dir():
        return out
    out["exists"] = True
    for target in sorted(base.glob("mlb_*.jsonl")):
        season = _season_of(target.stem.split("_", 1)[-1])
        if season is None:
            continue
        count = 0
        with target.open(encoding="utf-8") as handle:
            if season in parse_seasons:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    events = row.get("events")
                    count += len(events) if isinstance(events, list) else 1
            else:
                for line in handle:
                    if line.strip():
                        count += 1
                out["line_count_only"].append(season)
        out["seasons"][season] = out["seasons"].get(season, 0) + count
    return out


def statcast_seasons(manifest_path) -> dict:
    """Pitch counts per season from the statcast manifest -- never the files.

    The manifest already carries per-window row counts, so the audit costs one
    small JSON read instead of decompressing 2.7M pitches.
    """
    out = {"exists": False, "seasons": {}, "windows": 0, "pitches": 0}
    target = Path(manifest_path)
    if not target.exists():
        return out
    out["exists"] = True
    try:
        manifest = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return out
    for window, info in (manifest.get("windows") or {}).items():
        season = _season_of(window)
        rows = info.get("rows") if isinstance(info, dict) else None
        rows = rows if isinstance(rows, int) else 0
        out["windows"] += 1
        out["pitches"] += rows
        if season:
            out["seasons"][season] = out["seasons"].get(season, 0) + rows
    return out


def results_by_season(csv_path) -> dict:
    """Games per season from the results CSV, read from the date column only."""
    target = Path(csv_path)
    if not target.exists():
        return {}
    seasons = {}
    with target.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            season = _season_of(row.get("date"))
            if season:
                seasons[season] = seasons.get(season, 0) + 1
    return seasons


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _entry(seasons, rows_or_games, coverage_pct, notes) -> dict:
    return {"seasons": seasons, "rows_or_games": rows_or_games,
            "coverage_pct": coverage_pct, "notes": notes}


def _discovery_pct(source_seasons, results_seasons):
    """Source rows / results games over the discovery seasons, as a percent.

    Deliberately unclipped: a value over 100 means duplicate rows or a join
    about to double count, and hiding that behind min() would defeat the audit.
    """
    want = sum(results_seasons.get(s, 0) for s in DISCOVERY_SEASONS)
    if not want:
        return None
    have = sum(source_seasons.get(s, 0) for s in DISCOVERY_SEASONS)
    return round(100.0 * have / want, 1)


def _count_notes(counts) -> str:
    bits = []
    if counts["markers"]:
        bits.append(f"{counts['markers']} empty markers")
    if counts["bad_lines"]:
        bits.append(f"{counts['bad_lines']} bad lines")
    if counts["unknown_season"]:
        bits.append(f"{counts['unknown_season']} rows with no season")
    sealed = sorted(s for s in counts["seasons"] if s not in DISCOVERY_SEASONS)
    if sealed:
        bits.append("sealed/tuning seasons counted by date key only: "
                    + ",".join(sealed))
    return "; ".join(bits)


def _jsonl_entry(path, results_seasons=None, keys=("season", "date")) -> dict:
    counts = jsonl_season_counts(path, keys=keys)
    if not counts["exists"]:
        return _entry({}, 0, None, f"missing: {path}")
    pct = (_discovery_pct(counts["seasons"], results_seasons)
           if results_seasons is not None else None)
    return _entry(counts["seasons"], counts["rows"], pct, _count_notes(counts))


def report(root=None) -> dict:
    """source name -> {seasons, rows_or_games, coverage_pct, notes}.

    Reads only what is on disk under `root` (default: the real historical
    dir); never fetches. coverage_pct is computed against results-CSV games
    over the discovery seasons where that comparison is meaningful (lineups,
    the two first-five stores) and left None where a denominator would be an
    invention (pitch counts, odds events, transactions).
    """
    base = Path(root) if root is not None else historical_path()
    results_seasons = results_by_season(base / "mlb_results.csv")
    out = {}

    sealed = sorted(s for s in results_seasons if s not in DISCOVERY_SEASONS)
    out["results_csv"] = _entry(
        results_seasons, sum(results_seasons.values()), None,
        ("also holds sealed/tuning seasons: " + ",".join(sealed)) if sealed
        else "")

    sc = statcast_seasons(base / "statcast" / "manifest.json")
    out["statcast"] = (_entry(sc["seasons"], sc["pitches"], None,
                              f"{sc['windows']} windows, from manifest only")
                       if sc["exists"]
                       else _entry({}, 0, None, "missing: statcast/manifest.json"))

    lineups_path = base / "lineups.jsonl"
    if lineups_path.exists():
        # read() dedups by game_pk and drops empty markers, so this is games,
        # not lines -- the same view every detector join sees.
        games = lineup_store.read(path=lineups_path)
        by_season = {}
        for row in games.values():
            season = _season_of(row.get("date"))
            if season:
                by_season[season] = by_season.get(season, 0) + 1
        per = ["{}: {}/{}".format(s, by_season.get(s, 0), results_seasons.get(s, 0))
               for s in DISCOVERY_SEASONS]
        out["lineups"] = _entry(by_season, len(games),
                                _discovery_pct(by_season, results_seasons),
                                "games vs results " + ", ".join(per))
    else:
        out["lineups"] = _entry({}, 0, None, f"missing: {lineups_path}")

    for name in ("odds_history", "odds_first_five"):
        oc = odds_event_counts(base / name)
        if not oc["exists"]:
            out[name] = _entry({}, 0, None, f"missing: {name}/")
            continue
        note = ("events per season"
                + ("; lines only (content unread) for: "
                   + ",".join(oc["line_count_only"]) if oc["line_count_only"]
                   else ""))
        pct = (_discovery_pct(oc["seasons"], results_seasons)
               if name == "odds_first_five" else None)
        out[name] = _entry(oc["seasons"], sum(oc["seasons"].values()), pct, note)

    out["first_five_results"] = _jsonl_entry(
        base / "first_five_results.jsonl", results_seasons=results_seasons)
    out["transactions"] = _jsonl_entry(base / "transactions.jsonl")
    out["pitcher_logs"] = _jsonl_entry(base / "pitcher_logs.jsonl")
    out["bullpen_log"] = _jsonl_entry(base / "bullpen_log.jsonl")
    return out


def format_report(rep=None, root=None) -> str:
    """The report as an aligned plain-text table, one source per line."""
    rep = rep if rep is not None else report(root=root)
    rows = [("source", "rows/games", "coverage", "seasons", "notes")]
    for name, entry in rep.items():
        seasons = " ".join(f"{s}:{entry['seasons'][s]}"
                           for s in sorted(entry["seasons"]))
        pct = ("" if entry["coverage_pct"] is None
               else f"{entry['coverage_pct']}%")
        rows.append((name, str(entry["rows_or_games"]), pct,
                     seasons or "-", entry["notes"] or ""))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = []
    for row in rows:
        cells = [row[i].ljust(widths[i]) for i in range(4)] + [row[4]]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)
