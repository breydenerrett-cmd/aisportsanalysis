#!/usr/bin/env python3
"""Per-player pitcher-log freshness audit: is today's slate's starter data
actually there, not just "did the store's maximum date look recent".

WHY THIS EXISTS
----------------
The 2026-09-22 incident ("0 pitchers fetched" for five straight daily runs
since 2026-09-19) was invisible to a check that only reads the store's own
maximum date, because the store's maximum date is a property of WHICHEVER
pitcher happened to start most recently among everyone ever cached -- it
does not say whether TODAY's actual starters are covered. A store holding
25,000 old rows and missing every one of today's ten probable pitchers
still has a "recent-looking" maximum date if even one bullpen arm anywhere
in the league happened to pitch yesterday.

This audit instead reads the SLATE for a given date -- the FINAL games
`src.pipeline.history` already stores, which name their own probable
pitchers -- and checks, per player, whether the specific appearance that
slate implies is actually in `pitcher_logs.jsonl`. "Zero fetched" is not
inherently a failure (a game that finished ten minutes ago has not been
refreshed yet, by construction); it IS a failure once a refresh has run
AFTER the game finished and the appearance is still missing.

WHAT IS DISTINGUISHED (task 6's own five questions)
----------------------------------------------------
  * JOB EXECUTED    -- has ANY refresh (`checked_utc` marker,
                        `src.pipeline.pitchers` refresh mode) run at all
                        since the target date?
  * FETCH SUCCEEDED  -- among pitchers whose marker was refreshed since the
                        target date, how many actually ended up with the
                        appearance vs. still missing it?
  * SOURCE COVERAGE  -- does the source of truth itself (mlb_results.csv,
                        FINAL games only) even name a probable pitcher for
                        this game? A game with neither side's probable id
                        recorded is a different, upstream gap.
  * RESTORED-COPY COVERAGE -- is this pitcher in the local pitcher_logs.jsonl
                        AT ALL for this season (whatever this environment's
                        actions/cache restored), independent of whether the
                        one appearance this slate needs is present?
  * MODEL-INPUT FRESHNESS -- would `pitchers.appearances_before` (the exact
                        function every real consumer -- `src.detect.dossier`,
                        `src.pipeline.predict`, `src.pipeline.mismatch` --
                        calls) actually see the appearance as of the day
                        after the game? Re-derived through the real library
                        function rather than a raw dict lookup, so a
                        regression in the read path is caught here too, not
                        only in the write path this audit is nominally about.

Deterministic, local-store reads only (mlb_results.csv, pitcher_logs.jsonl)
-- no network call, matching every other scripts/*_audit.py in this repo.
Respects AISPORTS_DATA_DIR the same way src.paths already does everywhere
else; nothing here reads a second, audit-specific data root.

EXIT CODES: 0 clean, 1 an ESCALATE finding (a real, actionable gap).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.pipeline import history, pitchers  # noqa: E402


def _yesterday_utc() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _slate_pitchers(results: dict, target_date: str) -> list:
    """[(person_id, game_pk)] for every probable pitcher on FINAL games dated
    `target_date`, plus a count of FINAL games missing a probable id on
    either side (the SOURCE COVERAGE gap, reported separately)."""
    entries = []
    source_gaps = 0
    for row in results.values():
        if row.get("date") != target_date:
            continue
        saw_one = False
        for key in ("away_probable_id", "home_probable_id"):
            pid = row.get(key)
            if pid not in (None, ""):
                entries.append((str(pid), row.get("game_pk"),
                                row.get("start_time_utc")))
                saw_one = True
        if not saw_one:
            source_gaps += 1
    return entries, source_gaps


# A nine-inning game runs about three hours. Six is a deliberately generous
# upper bound covering extra innings and rain delays: after it, a game that
# started at `start_time_utc` is certainly final.
GAME_LENGTH_UPPER_BOUND_HOURS = 6.0


def _game_certainly_final_at(start_time_utc, target_date: str):
    """The instant after which this game is certainly over.

    From the game's OWN start time when the results row carries one --
    every real row does, `start_time_utc` being a column of
    `mlb_results.csv`.

    The fallback, for a row without one, is midnight UTC the day after the
    slate date. That is deliberately the SAME boundary the old calendar-day
    string comparison drew: with no start time there is no better
    information, and moving the line without it would trade a known
    behaviour for a guess. The correction applies where the evidence to
    correct it exists.
    """
    parsed = _parse_utc(start_time_utc)
    if parsed is not None:
        return parsed + timedelta(hours=GAME_LENGTH_UPPER_BOUND_HOURS)
    return datetime.fromisoformat(target_date).replace(
        tzinfo=timezone.utc) + timedelta(days=1)


def _parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def audit(results: dict, logs: dict, target_date: str, now: datetime) -> dict:
    """Pure over injected `results`/`logs` dicts -- no I/O of its own, so a
    test can hand it a synthetic fixture instead of the real (large,
    gitignored) stores. `main()` below is the only caller that reads them
    from disk."""
    season = target_date[:4]

    entries, source_gaps = _slate_pitchers(results, target_date)
    seen = set()
    rows = []
    for pid, game_pk, start_time_utc in entries:
        if pid in seen:
            continue
        seen.add(pid)

        existing = logs.get(pid, [])
        restored_copy_ok = bool(existing)
        marker = pitchers.coverage_marker(existing, season)
        checked_utc = marker.get("checked_utc") if marker else None
        # CORRECTED 2026-09-23. This was
        #     str(checked_utc)[:10] > target_date
        # -- a calendar-day STRING comparison, wrong in both directions.
        #
        # Too lenient, and this is the one that matters: a refresh that ran
        # at 23:50Z on the game's own day, minutes after an afternoon game
        # went final, compared equal rather than greater, so a KNOWN-missing
        # completed appearance was reported PENDING and the audit exited 0
        # calling it healthy. That is exactly the "must not label coverage
        # healthy" condition this script exists to enforce.
        #
        # Too strict the other way: a check at 00:05Z counted as "after" a
        # 23:05Z night game that was still in the fourth inning.
        #
        # Both go away by comparing real timestamps against the instant the
        # game is certainly over, taken from the game's own start time.
        checked_dt = _parse_utc(checked_utc)
        final_at = _game_certainly_final_at(start_time_utc, target_date)
        checked_after_game = checked_dt is not None and checked_dt >= final_at

        real_appearance = any(
            a.get("date") == target_date and not a.get("empty") for a in existing)

        # Model-input freshness: re-derive through the actual function every
        # real consumer calls, as of the day after the game -- not a raw
        # dict lookup, so a regression in appearances_before itself would
        # also show up here.
        as_of = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
        prior = pitchers.appearances_before(logs, pid, as_of)
        model_sees_it = any(a.get("date") == target_date for a in prior)

        if real_appearance and model_sees_it:
            status = "FRESH"
        elif not restored_copy_ok:
            status = "NEVER_CAPTURED"
        elif not checked_after_game:
            status = "PENDING"
        else:
            status = "MISSING_AFTER_REFRESH"

        rows.append({
            "person_id": pid, "game_pk": game_pk,
            "restored_copy_ok": restored_copy_ok,
            "checked_utc": checked_utc,
            "checked_after_game": checked_after_game,
            "real_appearance": real_appearance,
            "model_sees_it": model_sees_it,
            "status": status,
        })

    # JOB EXECUTED / FETCH SUCCEEDED, aggregate: any refresh at all since the
    # target date, and how it did among the pitchers it actually touched.
    job_executed = any(r["checked_after_game"] for r in rows)
    touched = [r for r in rows if r["checked_after_game"]]
    fetch_succeeded = sum(1 for r in touched if r["real_appearance"])

    return {
        "target_date": target_date,
        "as_of_now": now.astimezone(timezone.utc).isoformat(),
        "slate_pitchers": len(rows),
        "source_coverage_gaps": source_gaps,
        "job_executed_since_target": job_executed,
        "fetch_succeeded": fetch_succeeded,
        "fetch_attempted": len(touched),
        "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=None,
                    help="slate date to audit, YYYY-MM-DD (default: yesterday UTC, "
                         "since a FINAL game needs a day to have completed)")
    args = ap.parse_args(argv)
    target_date = args.date or _yesterday_utc()
    now = datetime.now(timezone.utc)

    results = history.read_results()
    logs = pitchers.read_logs()
    result = audit(results, logs, target_date, now)
    rows = result["rows"]

    print(f"pitcher-log freshness audit for slate {target_date} "
         f"(as of {result['as_of_now']})")
    print(f"  slate probable pitchers: {result['slate_pitchers']}")
    print(f"  source coverage gaps (FINAL game, no probable id either side): "
         f"{result['source_coverage_gaps']}")
    print(f"  job executed since target date (any refresh checked_after_game): "
         f"{result['job_executed_since_target']}")
    print(f"  fetch succeeded: {result['fetch_succeeded']}/{result['fetch_attempted']} "
         f"of the pitchers a post-game refresh actually touched")
    print()

    by_status = {}
    for row in rows:
        by_status.setdefault(row["status"], []).append(row)

    for status in ("FRESH", "PENDING", "NEVER_CAPTURED", "MISSING_AFTER_REFRESH"):
        group = by_status.get(status, [])
        print(f"  {status}: {len(group)}")

    findings = []
    for row in by_status.get("MISSING_AFTER_REFRESH", []):
        findings.append(
            f"pitcher {row['person_id']} (game_pk={row['game_pk']}): a refresh "
            f"ran after {target_date}'s game finished (checked_utc="
            f"{row['checked_utc']}) and the completed appearance is STILL "
            f"missing from pitcher_logs.jsonl -- required input, nothing is "
            f"retrieving it.")
    for row in by_status.get("NEVER_CAPTURED", []):
        findings.append(
            f"pitcher {row['person_id']} (game_pk={row['game_pk']}) has NO rows "
            f"at all in pitcher_logs.jsonl for season {target_date[:4]} -- the "
            f"refresh job has never processed this pitcher.")

    if result["source_coverage_gaps"]:
        print()
        print(f"  NOTE: {result['source_coverage_gaps']} FINAL game(s) on "
             f"{target_date} carry no probable-pitcher id on either side in "
             f"mlb_results.csv -- an upstream source gap, not a "
             f"pitcher_logs.jsonl freshness failure, reported separately and "
             f"never counted toward the pitcher rows above.")

    if findings:
        print()
        for message in findings:
            print(f"ESCALATE: {message}")
        return 1

    print()
    print("no actionable gap: every slate pitcher is either fresh, or has not "
         "yet had a post-game refresh cycle (not a failure).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
