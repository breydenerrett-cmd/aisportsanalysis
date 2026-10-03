"""Historical results store: idempotent, resumable, and honest about coverage.

WHY THIS IS NOT JUST "WRITE THE BACKFILL TO A CSV"
--------------------------------------------------
A three-season backfill is roughly 7,000 games across ~560 dates. That run will be
interrupted -- a rate limit, a dropped connection, a closed laptop. Three properties make
the difference between infrastructure and a script you have to babysit:

1. IDEMPOTENT. Re-ingesting a date already stored must not duplicate rows. Games are keyed
   by game_pk, which the MLB API guarantees unique, so a re-run overwrites in place.

2. RESUMABLE. A run that dies halfway must be able to pick up where it stopped rather than
   starting over.

3. HONEST ABOUT COVERAGE. This is the subtle one. A date with zero stored games is
   ambiguous: it might be an off day (the All-Star break, a Monday in April) or a date that
   was never fetched. Those are completely different facts, and confusing them produces
   silent holes in a training set -- you believe you have a full season while a week is
   quietly missing.

   The fix is a MANIFEST that records every date actually attempted, separately from the
   games themselves. A date in the manifest with zero games genuinely had no baseball. A
   date absent from the manifest was never asked about. Without that distinction, a gap
   looks identical to an off day, and the model trains on a season with holes in it.

Storage is CSV for inspectability, keyed by game_pk. The manifest is a small JSON sidecar.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import date
from pathlib import Path
from typing import Mapping

from src.paths import historical_path
from src.providers import mlb

DEFAULT_STORE = historical_path("mlb_results.csv")
DEFAULT_MANIFEST = historical_path("mlb_results.manifest.json")

# Only genuinely final games are stored. Pending and cancelled games are counted in the
# manifest so coverage is accurate, but never enter the results table -- a partial score
# looks exactly like a final one and would corrupt the training set invisibly.
RESULT_COLUMNS = [
    "game_pk", "date", "start_time_utc", "venue", "game_type",
    "away_team", "home_team", "away_team_id", "home_team_id",
    "away_probable", "home_probable", "away_probable_id", "home_probable_id",
    "away_score", "home_score", "winner", "home_won",
    "total_runs", "run_differential",
    "double_header", "game_number",
]


class HistoryError(RuntimeError):
    """Raised when the historical store cannot be read or written."""


# ---------------------------------------------------------------------------
# Durable writes
# ---------------------------------------------------------------------------

def _atomic_write(target: Path, render) -> None:
    """Write via a temp file and one rename, so a crash cannot truncate the store.

    Both files here are rewritten whole on every flush. Writing in place means a
    process killed mid-write leaves a TRUNCATED results file next to a manifest
    that still claims those dates were fetched -- which is precisely the silent
    hole this module exists to prevent: coverage says the date is done, the rows
    are gone, and nothing ever asks again. `os.replace` is atomic on POSIX, so
    the file on disk is always either the old copy or the complete new one.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as handle:
            render(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def read_manifest(path=DEFAULT_MANIFEST) -> dict:
    """Load the record of which dates have actually been fetched.

    Returns a dict mapping ISO date -> {final, pending, cancelled, total}. An empty dict
    means nothing has been ingested, which is different from "the season had no games".
    """
    target = Path(path)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HistoryError(f"manifest at {target} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise HistoryError(f"manifest at {target} is not an object")
    return data.get("dates", data)


def write_manifest(dates: dict, path=DEFAULT_MANIFEST) -> str:
    target = Path(path)
    payload = {"dates": dict(sorted(dates.items()))}
    _atomic_write(
        target,
        lambda h: h.write(json.dumps(payload, indent=1, sort_keys=True)),
    )
    return str(target)


def fetched_dates(path=DEFAULT_MANIFEST) -> set:
    """Every date already attempted. Used to skip work on resume."""
    return set(read_manifest(path))


def unfinished_dates(path=DEFAULT_MANIFEST) -> set:
    """Dates fetched while at least one game had not finished yet.

    A date fetched at 9pm with a west-coast game still in the seventh is recorded
    with pending>0. Its final games are stored, the unfinished one is not, and the
    date is now in the manifest -- so a resume-based run considers it DONE and never
    looks again. The result is a permanent hole that is invisible in every coverage
    count, because the date is present and the missing game was never a row.

    Pending is the only retryable state. Postponed, cancelled, and suspended games
    are terminal for the date they were scheduled on (they reappear as a makeup on
    some other date), so treating those as unfinished would make resume re-fetch the
    same dates forever without ever converging.
    """
    manifest = read_manifest(path)
    return {d for d, entry in manifest.items() if (entry or {}).get("pending", 0)}


def stored_scope(entry: Mapping) -> frozenset:
    """Which gameTypes a manifest entry was stored under.

    Entries written before this was recorded carry no `game_types` key. They
    were all written by the only caller that existed, which passed
    `TRAINING_GAME_TYPES` -- so that is what an absent key means, and it is a
    fact about those runs rather than a guess.
    """
    recorded = (entry or {}).get("game_types")
    if recorded is None:
        return frozenset(mlb.TRAINING_GAME_TYPES)
    return frozenset(recorded)


def covers_scope(entry: Mapping, wanted) -> bool:
    """Is this date's stored scope wide enough for `wanted`?"""
    if wanted is None:          # None means "store everything"
        return False
    return frozenset(wanted) <= stored_scope(entry)


def no_games_scheduled(game_date, path=None):
    """Why `game_date` had no MLB game anyone could have staked on, or None.

    WHY THIS EXISTS (2026-10-03). 2026-10-02 was a league-wide off day between
    the Wild Card round and the Division Series. The engine slate correctly
    considered 0 games and recorded nothing; the next morning `engine settle`
    ("no paper wagers recorded") and `eod` ("no decisions were recorded")
    refused that date, the daily loop escalated both, and the job went red.
    The same happens on every off day between rounds, at the All-Star break
    and every day of the offseason. Those two commands ask this function
    before reporting a failure.

    POSITIVE EVIDENCE ONLY. A reason comes back only when this manifest says
    the schedule was read for the date and nothing is pending, and either it
    listed no game at all, or (when the date was read under the decisive
    scope, so every regular-season and postseason game would have been kept)
    every game it listed was of a type the store never keeps, such as the
    All-Star Game. A date the manifest has never seen, one with games still
    pending, one with any regular-season or postseason game -- cancelled ones
    included, since they were scheduled when a slate would have run -- or an
    unreadable manifest returns None, so a slate that never ran on a real game
    day still fails loudly.
    """
    try:
        entry = read_manifest(path if path is not None else DEFAULT_MANIFEST).get(str(game_date))
    except HistoryError:
        return None
    if not isinstance(entry, Mapping) or entry.get("pending"):
        return None
    total = entry.get("total")
    if total == 0:
        return f"the MLB schedule listed no games on {game_date}"
    if (isinstance(total, int) and total > 0 and covers_scope(entry, mlb.DECISIVE_GAME_TYPES)
            and entry.get("stored") == 0 and entry.get("skipped_game_type") == total):
        return (f"the MLB schedule listed only exhibition games on {game_date} "
                "(no regular-season or postseason game)")
    return None


def missing_dates(start, end, path=DEFAULT_MANIFEST,
                  include_unfinished: bool = True, game_types=None) -> list:
    """Dates in a range that still owe us results.

    This is the resume primitive: it answers "what is left to do" from durable state
    rather than from a counter held in memory by a run that may have died. Three kinds
    of date owe results -- one never fetched, one fetched too early while games
    were still in progress, and one fetched under a NARROWER gameType scope than
    the caller now wants. All three must come back or the missing games are lost
    silently; see `unfinished_dates`.

    SCOPE AWARENESS, ADDED 2026-09-23. A date ingested under
    `TRAINING_GAME_TYPES` recorded every postseason game it saw as
    `skipped_game_type` and then marked the date done. A later request for
    `DECISIVE_GAME_TYPES` would be told the date was already complete and the
    postseason rows would never arrive -- which is exactly what happened to the
    2025 backfill, where every October date was "complete" with zero postseason
    games in it and only `--no-resume` could recover them. `--no-resume` is a
    recovery tool: it re-fetches an entire range including dates that are
    genuinely finished. This makes resume correct instead, so the daily job
    heals the gap on its own.

    `game_types=None` keeps the pre-existing behaviour exactly: dates are judged
    on whether they were fetched at all, not on what was kept.
    """
    manifest = read_manifest(path)
    already = set(manifest)
    if include_unfinished:
        already -= unfinished_dates(path)
    if game_types is not None:
        already = {d for d in already
                   if covers_scope(manifest.get(d, {}), game_types)}
    return [d for d in mlb.iter_dates(start, end) if d not in already]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def read_results(path=DEFAULT_STORE) -> dict:
    """Load stored results keyed by game_pk."""
    target = Path(path)
    if not target.exists():
        return {}
    store = {}
    with target.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = row.get("game_pk")
            if not key:
                continue
            store[key] = {k: (v if v != "" else None) for k, v in row.items()}
    return store


def write_results(store: dict, path=DEFAULT_STORE) -> str:
    """Write the whole store, sorted by date then game_pk for a stable diff."""
    target = Path(path)
    rows = sorted(
        store.values(),
        key=lambda r: (r.get("date") or "", str(r.get("game_pk") or "")),
    )

    def render(handle):
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) for c in RESULT_COLUMNS})

    _atomic_write(target, render)
    return str(target)


def ingest_date(game_date, store: dict, manifest: dict, timeout: int = 20,
                game_types=mlb.TRAINING_GAME_TYPES) -> dict:
    """Fetch one date and merge it into the store. Idempotent by game_pk.

    `game_types` filters what is STORED, defaulting to regular season only.
    Spring training is excluded deliberately: split squads, minor-league rosters,
    pitchers on artificial pitch counts, and no competitive incentive make those
    games a different process wearing the same uniforms. They are still counted
    in the manifest so coverage stays honest about what the date contained.

    Mutates `store` and `manifest` in place and returns per-date counts.
    """
    result = mlb.fetch_results(game_date, timeout=timeout)
    day = result["date"]

    added = updated = skipped = 0
    for game in result["final"]:
        if game_types is not None and game.get("game_type") not in game_types:
            skipped += 1
            continue
        key = str(game["game_pk"])
        if key in store:
            updated += 1
        else:
            added += 1
        store[key] = {c: game.get(c) for c in RESULT_COLUMNS}

    manifest[day] = {
        "total": result["summary"]["total"],
        "final": result["summary"]["final"],
        "pending": result["summary"]["pending"],
        "cancelled": result["summary"]["cancelled"],
        "stored": added + updated,
        "skipped_game_type": skipped,
        # What this date was stored UNDER, so a later run wanting a wider
        # scope can tell "already done" from "done, but not for what you are
        # asking". Sorted for a stable manifest diff.
        "game_types": sorted(game_types) if game_types is not None else None,
    }
    return {"date": day, "added": added, "updated": updated,
            "skipped_game_type": skipped, **result["summary"]}


def ingest_range(start, end, store_path=DEFAULT_STORE,
                 manifest_path=DEFAULT_MANIFEST, timeout: int = 20,
                 resume: bool = True, on_date=None, flush_every: int = 10,
                 game_types=mlb.TRAINING_GAME_TYPES) -> dict:
    """Ingest a date range into the store, resumably.

    `game_types` is forwarded to `ingest_date` and defaults to
    `TRAINING_GAME_TYPES` (regular season only), which is what every caller
    got before this argument existed -- passing it changes no existing
    behaviour.

    PASS `mlb.DECISIVE_GAME_TYPES` TO STORE THE POSTSEASON. Until 2026-09-23
    this function could not, and the consequence was not theoretical: a
    postseason pick is modelled, priced, published and locked by the live
    card exactly like any other (nothing in the card path filters on
    `game_type`), and then graded VOID -- "no final score stored for this
    game" -- because the outcome never reached this store. Wild Card play
    begins 2026-09-29 (`docs/SEASON_END_PLAN.md`), so forward ingest wants
    the decisive set, and so does any backfill meant to make October
    gradeable or testable.

    `flush_every` writes partial progress to disk periodically. A long backfill that dies
    at date 400 of 560 should not lose the first 399 -- without periodic flushing the whole
    run is held in memory and an interruption discards all of it.

    A date that errors is recorded and skipped rather than aborting the run; one bad day
    should not cost hours of collection.
    """
    store = read_results(store_path)
    manifest = read_manifest(manifest_path)

    targets = (missing_dates(start, end, manifest_path,
                             game_types=game_types) if resume
               else list(mlb.iter_dates(start, end)))

    errors = []
    processed = 0
    for day in targets:
        try:
            summary = ingest_date(day, store, manifest, timeout=timeout,
                                  game_types=game_types)
        except mlb.MLBError as exc:
            errors.append({"date": day, "error": str(exc)})
            continue
        processed += 1
        if on_date is not None:
            on_date(summary)
        if flush_every and processed % flush_every == 0:
            write_results(store, store_path)
            write_manifest(manifest, manifest_path)

    write_results(store, store_path)
    write_manifest(manifest, manifest_path)

    return {
        "requested": len(list(mlb.iter_dates(start, end))),
        "attempted": len(targets),
        "skipped_already_done": len(list(mlb.iter_dates(start, end))) - len(targets),
        "processed": processed,
        "failed": len(errors),
        "errors": errors,
        "total_games_stored": len(store),
        "store_path": str(store_path),
        "manifest_path": str(manifest_path),
    }


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

def _season_envelopes(manifest: dict) -> dict:
    """First and last date that actually had baseball, per year.

    Used to tell a hole apart from a winter. A February date with no games is not
    evidence of anything; a July date with no games is a missing week.
    """
    envelopes = {}
    for day, entry in manifest.items():
        if not (entry or {}).get("total"):
            continue
        year = day[:4]
        first, last = envelopes.get(year, (day, day))
        envelopes[year] = (min(first, day), max(last, day))
    return envelopes


def gap_runs(manifest: dict) -> list:
    """Contiguous blocks of never-fetched dates inside the span, classified.

    251 loose dates tell you nothing. Eight runs with dates on them tell you which
    are winters nobody asked about and which are weeks of missing baseball.

    `in_season` means the run falls inside a year's played envelope, so those dates
    could hold real games and the run is a genuine hole. `between_seasons` means it
    sits outside every envelope -- almost certainly an off-season, but note the word
    almost: a season that OPENS abroad before the fetched window (the Tokyo and
    Seoul series) puts real regular-season games in a run this function will call
    between_seasons. `touches_season_start` / `touches_season_end` flag exactly that
    case so a boundary run is reviewed rather than assumed empty.
    """
    days = sorted(manifest)
    if not days:
        return []
    envelopes = _season_envelopes(manifest)

    runs, current = [], []
    for day in mlb.iter_dates(days[0], days[-1]):
        if day not in manifest:
            current.append(day)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    classified = []
    for run in runs:
        start, end = run[0], run[-1]
        in_season = any(first <= start <= last or first <= end <= last
                        or (start < first and end > last)
                        for first, last in envelopes.values())
        next_day = date.fromisoformat(end).toordinal() + 1
        after = date.fromordinal(next_day).isoformat()
        before = date.fromordinal(date.fromisoformat(start).toordinal() - 1).isoformat()
        classified.append({
            "start": start,
            "end": end,
            "days": len(run),
            "classification": "in_season" if in_season else "between_seasons",
            "touches_season_start": any(after == first for first, _ in
                                        envelopes.values()),
            "touches_season_end": any(before == last for _, last in
                                      envelopes.values()),
        })
    return classified


def quality_report(store_path=DEFAULT_STORE, manifest_path=DEFAULT_MANIFEST) -> dict:
    """Report what is actually in the store and, more importantly, what is not.

    Distinguishes a genuine off day from an unfetched gap using the manifest, which is the
    whole reason the manifest exists.
    """
    store = read_results(store_path)
    manifest = read_manifest(manifest_path)

    if not manifest:
        return {"games": len(store), "dates_fetched": 0, "note":
                "no manifest: coverage is unknown, not zero"}

    days = sorted(manifest)
    off_days = [d for d in days if manifest[d]["total"] == 0]
    played = [d for d in days if manifest[d]["total"] > 0]
    unresolved = [d for d in days
                  if manifest[d]["pending"] > 0 or manifest[d]["cancelled"] > 0]
    # Two very different kinds of unresolved. A pending game is a date fetched too
    # early and it will resolve on a re-fetch. A cancelled game is terminal for the
    # date it was scheduled on. Counting them together makes a fixable hole and a
    # permanent fact of the schedule look like the same problem.
    still_pending = [d for d in days if manifest[d].get("pending", 0) > 0]
    cancelled_only = [d for d in unresolved if d not in set(still_pending)]

    # Dates inside the fetched span that were never attempted are real holes.
    span_gaps = []
    if days:
        for day in mlb.iter_dates(days[0], days[-1]):
            if day not in manifest:
                span_gaps.append(day)
    runs = gap_runs(manifest)

    field_fill = {}
    for column in RESULT_COLUMNS:
        filled = sum(1 for row in store.values() if row.get(column) not in (None, ""))
        field_fill[column] = round(filled / len(store), 3) if store else 0.0

    home_wins = sum(1 for r in store.values() if str(r.get("home_won")) == "1")

    return {
        "games": len(store),
        "dates_fetched": len(days),
        "first_date": days[0] if days else None,
        "last_date": days[-1] if days else None,
        "dates_with_games": len(played),
        "off_days": len(off_days),
        "dates_with_unresolved_games": len(unresolved),
        "dates_still_pending": still_pending,
        "dates_cancelled_only": len(cancelled_only),
        "unfetched_gaps_in_span": span_gaps,
        "gap_count": len(span_gaps),
        "gap_runs": runs,
        "gap_days_in_season": sum(r["days"] for r in runs
                                  if r["classification"] == "in_season"),
        "gap_days_between_seasons": sum(r["days"] for r in runs
                                        if r["classification"] == "between_seasons"),
        "home_win_rate": round(home_wins / len(store), 4) if store else None,
        "field_fill": field_fill,
    }


def sanity_checks(store_path=DEFAULT_STORE) -> list:
    """Assertions about the data that should always hold. Returns violations.

    These catch corruption that a fill-rate report cannot: a tied final game, a winner that
    is neither team, a run differential that disagrees with the scores. Any violation means
    something upstream is wrong and the store should not be trusted.
    """
    store = read_results(store_path)
    problems = []

    for key, row in store.items():
        away, home = row.get("away_score"), row.get("home_score")
        if away is None or home is None:
            problems.append(f"{key}: stored final game is missing a score")
            continue
        try:
            away, home = int(away), int(home)
        except (TypeError, ValueError):
            problems.append(f"{key}: non-numeric score {row.get('away_score')!r}/"
                            f"{row.get('home_score')!r}")
            continue

        if away == home:
            problems.append(f"{key}: tied final score {away}-{home} (MLB has no ties)")

        winner = row.get("winner")
        expected = row.get("home_team") if home > away else row.get("away_team")
        if winner != expected:
            problems.append(f"{key}: winner {winner!r} disagrees with score "
                            f"{away}-{home} (expected {expected!r})")

        if row.get("total_runs") is not None:
            try:
                if int(row["total_runs"]) != away + home:
                    problems.append(f"{key}: total_runs {row['total_runs']} != "
                                    f"{away}+{home}")
            except (TypeError, ValueError):
                problems.append(f"{key}: non-numeric total_runs {row['total_runs']!r}")

        if row.get("run_differential") is not None:
            try:
                if int(row["run_differential"]) != abs(home - away):
                    problems.append(f"{key}: run_differential "
                                    f"{row['run_differential']} != |{home}-{away}|")
            except (TypeError, ValueError):
                problems.append(f"{key}: non-numeric run_differential")

        home_won = str(row.get("home_won"))
        if home_won not in ("0", "1"):
            problems.append(f"{key}: home_won is {home_won!r}, expected 0 or 1")
        elif (home_won == "1") != (home > away):
            problems.append(f"{key}: home_won={home_won} disagrees with score "
                            f"{away}-{home}")

    return problems
