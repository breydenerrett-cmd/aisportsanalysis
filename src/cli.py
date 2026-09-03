"""Command line entry point.

Run with:  python -m src.cli <command> [args]

Every command fails safe. Missing configuration reports what to do and exits
non-zero; it never crashes with a stack trace and never prints a key.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.core import calibration
from src.data import parks
from src.paths import processed_path, raw_path
from src.capture import budget as budget_module
from src.capture import cadence as cadence_module
from src.pipeline import creditlog
from src.pipeline import slate as slate_pipeline
from src.providers import mlb
from src.providers import odds as odds_provider

DATA_RAW = raw_path()

EXIT_OK = 0
EXIT_NOT_CONFIGURED = 1
EXIT_ERROR = 2


def _load_dotenv(path=".env"):
    """Read .env into os.environ without adding a dependency.

    Values already in the environment win, so an explicit export is never
    silently overridden by a stale file.
    """
    import os
    env_file = Path(path)
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_status(args) -> int:
    """Report configuration and data-source availability."""
    status = odds_provider.status()
    print("aisportsanalysis -- status\n")
    print("  free sources (no key required)")
    print("    MLB Stats API   : schedule, probables, final results")
    print("    Open-Meteo      : temperature, wind, humidity\n")
    print("  odds provider")
    print(f"    provider        : {status['provider']}")
    print(f"    configured      : {status['configured']}")
    print(f"    markets         : {', '.join(status['markets'])}")
    print(f"    preferred book  : {status['default_book'] or '(first available)'}")
    if not status["configured"]:
        print(f"\n  {status['message']}")

    missing = parks.parks_missing_orientation()
    print(f"\n  park orientation  : {30 - len(missing)}/30 verified")
    if missing:
        print("    wind is collected but NOT applied as a model input until")
        print("    bearings are verified -- see docs/PARK_ORIENTATION.md")

    print("\n  model")
    print("    probability     : UNCALIBRATED -- no fitted model yet")
    print("    edge claims     : not available until calibration completes")
    return EXIT_OK if status["configured"] else EXIT_NOT_CONFIGURED


def cmd_credits(args) -> int:
    """Show odds API credit cost before scheduling anything."""
    estimate = odds_provider.estimate_credits()
    print("odds API credit estimate\n")
    print(f"  markets                  : {', '.join(estimate['markets'])}")
    print(f"  regions                  : {', '.join(estimate['regions'])}")
    print(f"  credits per call         : {estimate['credits_per_call']}")
    print(f"  calls/day at 15-min poll : {estimate['calls_per_day_at_15min']}")
    print(f"  credits/day              : {estimate['credits_per_day_at_15min']}")
    print(f"  free tier (monthly)      : {estimate['free_tier_monthly']}")
    print(f"  free tier lasts          : "
          f"{estimate['days_until_free_tier_exhausted']} days at that rate\n")
    print("  A 15-minute snapshot schedule exhausts the free tier in under two")
    print("  days. Line-movement capture needs either a paid tier or a much")
    print("  sparser schedule -- open, midpoint, and close.")

    row = creditlog.latest()
    print()
    if row is None:
        print("  credit log               : no rows yet (written by dense/"
              "prop_listing/prop_prices as they read the quota)")
    else:
        print(f"  latest logged balance    : {row.get('credits_remaining')} "
              f"remaining (used {row.get('credits_used_last')} last, via "
              f"{row.get('caller')}, at {row.get('utc')})")
    return EXIT_OK


def cmd_budget(args) -> int:
    """Credit envelope status, or (--probe) a single measured probe."""
    if getattr(args, "probe", None):
        family = args.probe
        print(f"budget --probe {family}: one bounded, real, 1-event fetch "
              f"against the odds provider -- src.capture.budget.probe_family. "
              f"Refuses to run twice per family per day and respects "
              f"CREDIT_FLOOR before spending anything.")
        result = budget_module.probe_family(family)
        print(f"  {result}")
        return EXIT_ERROR if not result.get("probed") else EXIT_OK

    status = budget_module.status()
    print("credit budget\n")
    print(f"  monthly allotment        : {status['monthly_allotment']} "
          f"(tier fact, src/providers/odds.py PRICING_TIERS)")
    print(f"  assumed reset            : {status['quota_reset_utc']} "
          f"({status['days_until_reset']} days; {status['reset_cycle_days']}-day "
          f"cycle assumption, not a verified billing date)")
    print(f"  daily envelope           : {status['daily_envelope']}")
    print(f"  credit floor             : {status['credit_floor']}")
    print(f"  remaining today          : {status['remaining_today']}")
    print(f"  spent today              : {status['spent_today']}")
    print(f"  envelope remaining today : {status['envelope_remaining_today']}")
    print(f"  drop order (v{status['drop_order_version']}, first-dropped -> "
          f"last-dropped): {', '.join(status['drop_order'])}")
    print(f"  non-droppable floor      : {status['non_droppable_family']}")
    print("\n  per-family measured cost")
    for name, info in sorted(status["families"].items()):
        if info["measured"]:
            print(f"    {name:26s} measured  {info['credits_per_event']} "
                  f"credit(s)/event  (as of {info['measured_utc']})")
        elif info.get("degenerate"):
            print(f"    {name:26s} provisional (degenerate probe) -- "
                  f"{info['credits_per_event']} credit(s)/event measured "
                  f"{info['measured_utc']}, but the payload was too thin to "
                  f"trust; still PROBE_REQUIRED, re-probe allowed today")
        else:
            print(f"    {name:26s} PROBE_REQUIRED -- unmeasured")
    return EXIT_OK


def cmd_cadence(args) -> int:
    """Cadence SLO: attempted/succeeded/longest gap/p95 gap per source."""
    date_str = args.date or datetime.now(timezone.utc).date().isoformat()
    result = cadence_module.write(date_str)
    print(f"cadence SLO for {date_str} ({result['written']} rows written to "
          f"{cadence_module.DEFAULT_SLO_STORE})\n")
    for name, slo in result["sources"].items():
        print(f"  {name:22s} attempted={slo['attempted']:3d}  "
              f"longest_gap_s={slo['longest_gap_seconds']}  "
              f"p95_gap_s={slo['p95_gap_seconds']}  grade={slo['grade']}")
    return EXIT_OK


def cmd_l1(args) -> int:
    """Backfill data/processed/l1_observations.jsonl from every price store.

    Deterministic and idempotent: a re-run over unchanged source stores
    writes zero new rows. Never drops a row silently -- anything declined is
    counted and reported with its reason.
    """
    from src.board import gamekey as gamekey_module
    from src.board import l1 as l1_module

    result = l1_module.run(since=args.since)
    print(f"L1 backfill -> {result['output_path']}\n")
    print("  per source store")
    for name, stats in result["by_source"].items():
        present = "present" if stats["present"] else "MISSING"
        print(f"    {name:16s} {present:8s} rows_seen={stats['rows_seen']:6d}  "
              f"observations={stats['observations_seen']:6d}  "
              f"written={stats['written']:6d}  "
              f"skipped_existing={stats['skipped_existing']:6d}  "
              f"refused={stats['refused']:4d}  raw_matched={stats['raw_matched']:4d}")

    print("\n  per market_key")
    for market_key, stats in sorted(result["by_market_key"].items()):
        print(f"    {market_key:24s} written={stats['written']:6d}")

    print(f"\n  totals: written={result['written']}  "
          f"skipped_existing={result['skipped_existing']}  "
          f"refused={result['refused']}  raw_matched={result['raw_matched']}")

    if result["refusals"]:
        print("\n  refusal reasons (never a silent drop)")
        for reason, count in sorted(result["refusals"].items()):
            print(f"    {count:6d}  {reason}")

    gp = result.get("game_pk") or {}
    print(f"\n  game_pk (S1, from {gamekey_module.DEFAULT_MAP_PATH})")
    print(f"    resolved={gp.get('resolved', 0):6d}  "
          f"ambiguous={gp.get('ambiguous', 0):6d}  "
          f"not_in_map={gp.get('not_in_map', 0):6d}  "
          f"map_null={gp.get('map_null', 0):6d}")

    return EXIT_OK


def cmd_gamekey(args) -> int:
    """Build/refresh data/processed/event_game_map.jsonl for a date range.

    `--date D` alone resolves just D. `--date START --end END` resolves
    every calendar date from START to END inclusive. Prints
    resolved/ambiguous/unresolved counts; never touches L1 itself (`l1
    --backfill` reads whatever this command has already written).
    """
    from src.board import gamekey as gamekey_module

    end = args.end or args.date
    report = gamekey_module.build_map_for_range(
        args.date, end, force=args.force)
    print(f"gamekey --date {args.date}"
          + (f" --end {end}" if end != args.date else "") + "\n")
    print(f"  map: {report['map_path']}")
    print(f"  candidates={report['candidates']:6d}  "
          f"resolved={report['resolved']:6d}  "
          f"ambiguous={report['ambiguous']:6d}  "
          f"unresolved={report['unresolved']:6d}  "
          f"skipped_already_mapped={report['skipped_already_mapped']:6d}  "
          f"rows_written={report['rows_written']:6d}")
    print("\n  per date")
    for day, day_report in sorted(report["by_date"].items()):
        print(f"    {day}  candidates={day_report['candidates']:4d}  "
              f"resolved={day_report['resolved']:4d}  "
              f"ambiguous={day_report['ambiguous']:4d}  "
              f"unresolved={day_report['unresolved']:4d}")
    return EXIT_OK


def cmd_statcast(args) -> int:
    """`statcast --catchup [--through DATE]`: extend the pitch-level store
    (`data/historical/statcast/`) from its manifest's last covered date
    through `--through` (default: yesterday, UTC). See
    `src.providers.statcast_pitches.catchup` for the full contract -- this
    is the forward cadence that keeps the six pitch-accumulator matchup
    features (`src.engine.features`) grading fresh instead of stale."""
    if not args.catchup:
        print("ERROR: statcast currently only supports --catchup",
              file=sys.stderr)
        return EXIT_ERROR

    from src.providers import statcast_pitches as sp

    def _on_window(info):
        if "error" in info:
            print(f"  FAILED  {info['window']}: {info['error']}")
        else:
            print(f"  fetched {info['window']}: {info['rows']:6d} rows")

    try:
        report = sp.catchup(through=args.through, on_window=_on_window)
    except sp.StatcastPitchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"statcast catchup -- last covered before: "
          f"{report['last_covered_before']}, through: {report['through']}")
    print(f"  windows fetched : {report['windows']}")
    print(f"  windows skipped : {report['skipped']} (already in manifest)")
    print(f"  windows failed  : {report['failed']}")
    print(f"  rows fetched    : {report['rows']}")
    if report["windows"] == 0 and report["failed"] == 0:
        print("  store already current through the target date")
    return EXIT_OK if report["failed"] == 0 else EXIT_ERROR


def cmd_slate(args) -> int:
    """Build a slate for one date and write it to CSV."""
    try:
        result = slate_pipeline.build_slate(
            args.date,
            include_weather=not args.no_weather,
            include_odds=not args.no_odds,
        )
    except (mlb.MLBError, slate_pipeline.SlateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    rows = result["rows"]
    if not rows:
        print(f"no games scheduled for {result['date']}")
        return EXIT_OK

    path = DATA_RAW / f"mlb_{result['date']}.csv"
    slate_pipeline.write_slate(rows, path)

    coverage = result["coverage"]
    print(f"slate {result['date']}: {coverage['games']} games -> {path}\n")

    states = {}
    for row in rows:
        states[row["state"]] = states.get(row["state"], 0) + 1
    print("  states     : " + ", ".join(f"{k}={v}" for k, v in sorted(states.items())))
    print(f"  analysable : {coverage['analysable']}/{coverage['games']} "
          "(moneyline priced)")

    print("\n  fill rates")
    for column in ("away_probable", "weather_temp_f", "weather_wind_from_deg",
                   "wind_effect", "ml_home_price", "rl_home_price",
                   "total_line"):
        rate = coverage["fill_rate"][column]
        print(f"    {column:<24} {rate * 100:5.1f}%")

    if result["warnings"]:
        shown = result["warnings"][:8]
        print(f"\n  warnings ({len(result['warnings'])})")
        for warning in shown:
            print(f"    - {warning}")
        if len(result["warnings"]) > len(shown):
            print(f"    ... and {len(result['warnings']) - len(shown)} more")

    if not result["odds_configured"]:
        print("\n  NOTE: no odds key, so no prices were fetched. The slate is")
        print("  schedule and weather only. Nothing was fabricated.")
    return EXIT_OK


def cmd_results(args) -> int:
    """Fetch results for a date and report what is genuinely final."""
    try:
        result = mlb.fetch_results(args.date)
    except mlb.MLBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    summary = result["summary"]
    print(f"results {result['date']}")
    print(f"  total     : {summary['total']}")
    print(f"  final     : {summary['final']}")
    print(f"  pending   : {summary['pending']}")
    print(f"  cancelled : {summary['cancelled']}\n")

    for game in result["final"]:
        print(f"  {game['away_team']:>4} {game['away_score']:>2} @ "
              f"{game['home_team']:<4} {game['home_score']:<2}  -> {game['winner']}")

    if summary["final"] == 0 and summary["total"] > 0:
        print("  no games are final yet -- nothing is gradeable for this date.")
    return EXIT_OK


def cmd_ingest(args) -> int:
    """Ingest a date range into the historical store. Idempotent and resumable."""
    from src.pipeline import history

    remaining = history.missing_dates(args.start, args.end)
    total = len(list(mlb.iter_dates(args.start, args.end)))
    if args.resume and not remaining:
        print(f"{args.start}..{args.end}: all {total} dates already ingested.")
        print("  pass --no-resume to re-fetch.")
        return EXIT_OK

    print(f"ingesting {args.start}..{args.end}  "
          f"({len(remaining) if args.resume else total} of {total} dates to fetch)")

    def progress(summary):
        print(f"  {summary['date']}  final={summary['final']:>2}  "
              f"pending={summary['pending']:>2}  cancelled={summary['cancelled']:>2}  "
              f"(+{summary['added']} new)")

    report = history.ingest_range(
        args.start, args.end, resume=args.resume,
        on_date=progress if args.verbose else None,
    )

    print(f"\n  attempted    : {report['attempted']}")
    print(f"  processed    : {report['processed']}")
    print(f"  skipped      : {report['skipped_already_done']} (already ingested)")
    print(f"  failed       : {report['failed']}")
    print(f"  games stored : {report['total_games_stored']}")
    print(f"  store        : {report['store_path']}")

    if report["errors"]:
        print(f"\n  {len(report['errors'])} date(s) failed and will be retried on resume:")
        for error in report["errors"][:5]:
            print(f"    {error['date']}: {error['error']}")
    return EXIT_OK


def cmd_boxscores(args) -> int:
    """Fetch per-game, per-player box lines into data/processed/boxscores_<yyyy>.jsonl.

    Idempotent and resumable by game_pk (see src.pipeline.boxscores). A
    single date (--date) or an inclusive range (--backfill START..END) --
    the range mode is meant for a resumable, rate-limited historical fill,
    not for routine daily use.
    """
    from src.pipeline import boxscores

    if args.backfill:
        try:
            start, end = args.backfill.split("..", 1)
        except ValueError:
            print("--backfill must be START..END, e.g. 2023-03-30..2023-11-01")
            return EXIT_ERROR

        def progress(report):
            print(f"  {report['date']}  games={report['games_written']:>2} "
                  f"written  skipped={report['games_skipped']:>2}  "
                  f"pitchers={report['pitcher_rows']:>3}  "
                  f"batters={report['batter_rows']:>3}"
                  + (f"  ERRORS={len(report['errors'])}" if report["errors"] else ""))

        totals = boxscores.ingest_range(start.strip(), end.strip(),
                                         on_date=progress)
        print(f"\n  dates          : {totals['dates']}")
        print(f"  games written  : {totals['games_written']}")
        print(f"  games skipped  : {totals['games_skipped']} (already stored)")
        print(f"  pitcher rows   : {totals['pitcher_rows']}")
        print(f"  batter rows    : {totals['batter_rows']}")
        print(f"  linescore rows : {totals['linescore_rows']}")
        if totals["errors"]:
            print(f"  {len(totals['errors'])} game(s) failed and will be "
                  "retried on resume:")
            for error in totals["errors"][:5]:
                print(f"    {error['date']} game_pk={error['game_pk']}: "
                      f"{error['error']}")
        return EXIT_OK

    day = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = boxscores.ingest_date(day)
    print(f"{report['date']}: {report['games_seen']} final game(s) seen, "
          f"{report['games_written']} written, "
          f"{report['games_skipped']} already stored")
    print(f"  pitcher rows: {report['pitcher_rows']}  "
          f"batter rows: {report['batter_rows']}  "
          f"linescore rows: {report['linescore_rows']}")
    print(f"  store: {report['path']}")
    if report["errors"]:
        print(f"  {len(report['errors'])} game(s) failed:")
        for error in report["errors"]:
            print(f"    game_pk={error['game_pk']}: {error['error']}")
    return EXIT_OK


def cmd_history(args) -> int:
    """Report coverage and integrity of the historical store."""
    from src.pipeline import history

    report = history.quality_report()
    if report.get("note"):
        print(f"historical store: {report['games']} games")
        print(f"  {report['note']}")
        return EXIT_OK

    print("historical results store\n")
    print(f"  games stored          : {report['games']}")
    print(f"  dates fetched         : {report['dates_fetched']}")
    print(f"  span                  : {report['first_date']} .. {report['last_date']}")
    print(f"  dates with games      : {report['dates_with_games']}")
    print(f"  genuine off days      : {report['off_days']}")
    pending = report.get("dates_still_pending") or []
    print(f"  dates still unresolved: {report['dates_with_unresolved_games']} "
          f"({report.get('dates_cancelled_only', 0)} cancelled/postponed - terminal, "
          f"{len(pending)} still pending - retryable)")
    print(f"  home win rate         : {report['home_win_rate']}")

    if pending:
        print("\n  dates fetched before their games finished (re-run ingest to close):")
        for day in pending[:10]:
            print(f"    {day}")

    if report["gap_count"]:
        print(f"\n  {report['gap_count']} date(s) inside the span were never fetched: "
              f"{report.get('gap_days_in_season', 0)} in-season, "
              f"{report.get('gap_days_between_seasons', 0)} between seasons.")
        print("  In-season runs are holes. Between-season runs are unproven, not "
              "proven empty.")
        print(f"\n    {'range':<25} {'days':>5}  {'classification':<16} note")
        for run in report.get("gap_runs", []):
            note = []
            if run["touches_season_start"]:
                note.append("abuts a season start - may contain an opening series")
            if run["touches_season_end"]:
                note.append("abuts a season end")
            span = (run["start"] if run["days"] == 1
                    else f"{run['start']}..{run['end']}")
            print(f"    {span:<25} {run['days']:>5}  {run['classification']:<16} "
                  f"{'; '.join(note)}")
    else:
        print("\n  no unfetched gaps inside the span.")

    problems = history.sanity_checks()
    if problems:
        print(f"\n  INTEGRITY FAILURES ({len(problems)}):")
        for problem in problems[:10]:
            print(f"    {problem}")
        return EXIT_ERROR
    print("  integrity checks: all passed")
    return EXIT_OK


def cmd_features(args) -> int:
    """Build the point-in-time training table from the historical store."""
    from src.pipeline import features, history

    store = history.read_results()
    if not store:
        print("historical store is empty -- run `ingest` first.", file=sys.stderr)
        return EXIT_ERROR

    table = features.build_training_table(
        store, min_date=args.start, max_date=args.end,
        require_complete=not args.include_thin,
    )

    print(f"training table from {len(store)} stored games\n")
    print(f"  labelled rows : {table['count']}")
    print(f"  span          : {table['first_date']} .. {table['last_date']}")
    print(f"  home base rate: {table['base_rate']}")
    print("\n  excluded")
    for reason, count in sorted(table["skipped"].items()):
        if count:
            print(f"    {reason:<16} {count}")

    if table["count"]:
        path = processed_path("training_table.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        import csv as _csv
        columns = list(table["rows"][0])
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = _csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(table["rows"])
        print(f"\n  written to    : {path}")
        print(f"  columns       : {len(columns)}")

    print("\n  Every feature is computed only from games strictly BEFORE each row's")
    print("  date. No model is fitted yet -- this is the input, not a prediction.")
    return EXIT_OK


def cmd_train(args) -> int:
    """Fit the probability model and evaluate it honestly."""
    from src.model import dataset, logistic
    from src.pipeline import features, history

    store = history.read_results()
    if not store:
        print("historical store is empty -- run `ingest` first.", file=sys.stderr)
        return EXIT_ERROR

    table = features.build_training_table(store)
    prep = dataset.prepare(table["rows"], strategy=args.missing)
    report = prep["report"]

    print(f"training data: {report['rows_kept']} rows, "
          f"{report['columns_kept']}/{report['columns_in']} features")
    if report["columns_dropped"]:
        print(f"  dropped columns (gaps): {', '.join(report['columns_dropped'])}")
    profile = report["dropped_date_profile"]
    if profile.get("biased"):
        print(f"  WARNING: the {profile['dropped']} dropped rows cluster in time "
              f"({profile['share_in_first_half']:.0%} in the first half of the "
              "season). This strategy introduces a temporal bias.")

    splits = dataset.time_split(prep)
    print("\n  splits (chronological, never random)")
    for name in ("train", "val", "test"):
        split = splits[name]
        print(f"    {name:<6} n={split['n']:<5} "
              f"{split['first_date']}..{split['last_date']}  "
              f"base={split['base_rate']}")

    scaler = dataset.fit_scaler(splits["train"]["matrix"])
    scaled = {k: dataset.apply_scaler(splits[k]["matrix"], scaler)
              for k in ("train", "val", "test")}
    labels = {k: splits[k]["labels"] for k in ("train", "val", "test")}

    print("\n  fitting...")
    model = logistic.fit(scaled["train"], labels["train"],
                         val_matrix=scaled["val"], val_labels=labels["val"])
    print(f"    epochs={model['epochs_run']} best_epoch={model['best_epoch']}")

    evaluate = "test" if args.test else "val"

    if evaluate == "test":
        from src.model import seal
        split = splits["test"]
        before = seal.status(split["first_date"], split["last_date"], split["n"])
        if before["burned"]:
            print(f"\n  *** SEALED SPLIT ALREADY BURNED ***")
            print(f"  {before['warning']}")
            print("  See docs/TEST_SPLIT_STATUS.md. Proceeding, but this number")
            print("  must NOT be reported as out-of-sample.")
        after = seal.record_evaluation(
            split["first_date"], split["last_date"], split["n"],
            reason=f"cli train --test (missing={args.missing})")
        print(f"\n  test split evaluations recorded: {after['evaluations']}")

    predictions = logistic.predict(model, scaled[evaluate])
    scores = calibration.score_all(predictions, labels[evaluate])
    baseline = calibration.baseline_base_rate(labels[evaluate])

    print(f"\n  {evaluate.upper()} SET (n={len(labels[evaluate])})")
    print(f"    model     log_loss={scores['log_loss']:.6f}  "
          f"brier={scores['brier']:.6f}  ece={scores['ece']:.4f}")
    print(f"    base rate log_loss={baseline['log_loss']:.6f}")
    print(f"    beats base rate: {scores['log_loss'] < baseline['log_loss']} "
          f"({baseline['log_loss'] - scores['log_loss']:+.6f})")
    print(f"    predicted {scores['mean_predicted']:.4f} vs "
          f"observed {scores['observed_rate']:.4f}")
    print(f"    range {min(predictions):.3f}..{max(predictions):.3f}")

    print("\n  top coefficients (scaled, + favours home)")
    for coefficient in logistic.coefficients(model, prep["features"])[:8]:
        print(f"    {coefficient['feature']:<28} {coefficient['weight']:+.4f}")

    path = processed_path("model.json")
    logistic.save(model, scaler, prep["features"], path, metadata={
        "trained_on": f"{splits['train']['first_date']}..{splits['train']['last_date']}",
        "rows": splits["train"]["n"],
        "missing_strategy": args.missing,
    })
    print(f"\n  saved to {path}")

    print("\n  WHAT THIS DOES NOT SHOW")
    print("  Beating a base rate is NOT beating the market. The market prices in")
    print("  starting pitchers, injuries, and lineups that this model never sees.")
    print("  Answering 'does this have edge' needs historical closing odds, which")
    print("  have not been acquired. No bet should be placed on this.")
    return EXIT_OK


def cmd_ledger(args) -> int:
    """Settle forward-ledger entries, and report what the ledger holds."""
    from src.pipeline import ledger
    from src.providers import mlb as mlb_provider

    if getattr(args, "action", None) == "verify":
        from src.ledger import bridge
        report = bridge.verify()
        status = report["v1_status"]
        if status == bridge.V1_UNTOUCHED:
            label = f"untouched ({report['v1_rows_current']} row(s))"
        elif status == bridge.V1_GREW:
            label = (f"GREW, OK ({report['v1_rows_recorded']} -> "
                     f"{report['v1_rows_current']} rows by pure append, "
                     "prefix byte-identical)")
        else:
            label = (f"TAMPERED ({report['v1_rows_current']} row(s) now; "
                     "no prefix of this file matches the hash recorded at "
                     "genesis -- the recorded region itself changed)")
        print(f"v1 ledger ({report['v1_path']}): {label}")
        print(f"  sha256 recorded={report['v1_sha256_recorded']}")
        print(f"  sha256 current ={report['v1_sha256_current']}")
        print(f"v2 chain ({report['v2_path']}): "
              f"{'ok' if report['v2_chain_ok'] else 'BROKEN'} "
              f"({report['v2_rows_checked']} row(s) checked)")
        if not report["v2_chain_ok"]:
            print(f"  broken at line {report['v2_broken_at_line']}: "
                  f"{report['v2_reason']}")
        return EXIT_OK if report["ok"] else EXIT_ERROR

    if args.status:
        report = ledger.status()
        print(f"forward ledger: {report['games_recorded']} game(s) across "
              f"{len(report['dates'])} date(s)")
        print(f"  settled {report['settled']}   pending {report['pending']}")
        print("  verdicts: " + ", ".join(
            f"{v} {k}" for k, v in sorted(report["verdicts"].items())))
        print(f"  actionable (flagged): {report['actionable']}")
        if report["first_recorded"]:
            print(f"  first {report['first_recorded'][:19]}   "
                  f"last {report['last_recorded'][:19]}")
        return EXIT_OK

    entries = ledger.read()
    pending = [r for r in ledger.recommendations(entries)
               if r["game_pk"] not in ledger.settlements(entries)]
    if not pending:
        print("nothing pending to settle.")
        return EXIT_OK

    # The closing price each settlement was graded against. It comes from the
    # snapshot store -- the same source the grading path uses -- and it goes ON
    # the settlement row, because CLV computed later from a ledger whose every
    # settlement says closing=null is not computable at all.
    from src.pipeline import snapshots
    snapshot_series = snapshots.group_by_game(snapshots.read())

    by_date = {}
    for row in pending:
        by_date.setdefault(row["date"], []).append(row)

    settled = 0
    unresolved = 0
    for game_date in sorted(by_date):
        try:
            games = {g["game_pk"]: g for g in mlb_provider.fetch_games(game_date)}
        except mlb_provider.MLBError as exc:
            print(f"  ({game_date}: {exc})")
            continue
        for row in by_date[game_date]:
            game = games.get(row["game_pk"])
            if not game or game.get("state") != "final":
                # Not a failure. A postponed or in-progress game is simply not
                # settleable yet, and writing a settlement now would freeze a
                # non-result into the record.
                unresolved += 1
                continue
            five = game.get("first_five") or {}
            closing, closing_reason = _settlement_closing(row, snapshot_series)
            ledger.settle(row["game_pk"], {
                "away_score": game.get("away_score"),
                "home_score": game.get("home_score"),
                "winner": game.get("winner"),
                "home_won": game.get("home_won"),
                "total_runs": game.get("total_runs"),
                "first_five": {
                    "complete": five.get("complete"),
                    "away_runs": five.get("away_runs"),
                    "home_runs": five.get("home_runs"),
                    "total_runs": five.get("total_runs"),
                    "winner": five.get("winner"),
                    "reason": five.get("reason"),
                },
            }, closing=closing, closing_reason=closing_reason)
            settled += 1

    print(f"settled {settled} game(s); {unresolved} not final yet")
    return EXIT_OK


def _settlement_closing(rec, snapshot_series):
    """(closing, reason) for one recommendation, from the snapshot store.

    The close is the last h2h observation strictly before first pitch -- the
    exact definition the grading path uses -- so a settlement and a grade can
    never disagree about what "closing" meant. When no such observation
    exists, closing is null and the reason says so explicitly.

    The row also carries how stale that close was: `book_stale_seconds` (None
    when the observation has no book_last_update -- unknown, never a
    flattering zero) and the `book_stale` flag, so a settlement priced off a
    book that had suspended its market before first pitch says so on its face.
    Settlement rows written before this existed simply lack the two fields;
    readers must read a missing field as "unknown", not as "fresh".
    """
    from src.pipeline import snapshots

    key = snapshots.game_key(rec.get("away_team"), rec.get("home_team"),
                             rec.get("commence_time"))
    series = snapshot_series.get(key)
    if not series:
        return None, "no snapshots recorded for this game"
    observation = snapshots.closing_observation(series, rec.get("commence_time"))
    if observation is None:
        return None, "no snapshot observed before first pitch"
    return {
        "market": "h2h",
        "book": observation.get("book"),
        "observed_utc": observation.get("observed_utc"),
        "book_last_update": observation.get("book_last_update"),
        "book_stale_seconds": observation.get("book_stale_seconds"),
        "book_stale": observation.get("book_stale"),
        "prices": observation.get("prices"),
    }, None


def cmd_closing_audit(args) -> int:
    """Read-only: per-market closing coverage over every settled game.

    Extends past an h2h-only check that used to IGNORE L14's
    `closing_backfill` rows entirely (re-deriving an h2h close from scratch
    every time regardless of whether one was already backfilled) into
    `grading.ledger_closing_coverage`'s four markets -- h2h, spreads,
    totals, first_five -- each checked against the store that actually
    captures it (h2h/spreads/totals share odds_snapshots.jsonl; first_five
    lives in the far sparser f5_close.jsonl). A backfilled close counts as
    RECORDED, not as freshly derivable, so the table reads honestly: what is
    already evidence on the ledger versus what a read-only lookup could
    still find.

    Nothing here writes to the ledger for any market. h2h is the only
    market with a backfill mechanism at all (`closing-backfill`); spreads,
    totals, and first_five stay dry-run numbers forever under this command
    -- see grading.ledger_closing_coverage's module note.
    """
    from src.pipeline import grading, ledger

    entries = ledger.read()
    settled = ledger.settlements(entries)
    if not settled:
        print("no settled games on record.")
        return EXIT_OK

    coverage = grading.ledger_closing_coverage(entries)

    print(f"closing audit -- per-market coverage over {len(settled)} settled game(s)")
    print(f"  {'market':<12}{'settled':>9}{'recorded':>10}{'derivable':>11}"
          f"{'not derivable':>15}")
    for market, c in coverage.items():
        not_derivable = sum(c["not_derivable"].values())
        print(f"  {market:<12}{c['settled']:>9}{c['with_closing']:>10}"
              f"{c['derivable_not_recorded']:>11}{not_derivable:>15}")

    print("\n  not derivable, by reason:")
    for market, c in coverage.items():
        if not c["not_derivable"]:
            continue
        print(f"    {market} (source: {c['source']}):")
        for reason, count in sorted(c["not_derivable"].items(), key=lambda kv: -kv[1]):
            print(f"      {count:>5}  {reason}")
    return EXIT_OK


def cmd_closing_backfill(args) -> int:
    """Append `closing_backfill` rows for settlements a market close can
    now be derived for -- see grading.find_backfillable_closings for the
    derivation rule (identical to closing-audit's, per market) and
    grading.read_backfills/effective_closing for the append/idempotence
    and reader-preference rules.

    `--market` (default h2h, unchanged from before L18) selects h2h,
    spreads, totals, or `all` three in one pass. h2h's null closes trace
    to the abbreviation join bug (commit 65f499a); spreads/totals have
    simply never had a writer for their close at all until this lane, so
    every one closing-audit calls derivable is a candidate the first time
    this runs. first_five is not offered -- separate, sparser store, a
    separate decision.

    Never rewrites or deletes a ledger row: --dry-run and a real run share
    the exact same computation, so a dry run cannot claim something the
    real run then fails to append, and a repeat real run appends 0 rows
    for a market already fully covered (a settlement already covered by a
    valid backfill for that market is skipped, not re-derived).
    """
    from src.pipeline import grading, ledger, snapshots

    markets = ("h2h", "spreads", "totals") if args.market == "all" else (args.market,)
    entries = ledger.read()
    snapshot_rows = snapshots.read()

    to_append_all = []
    for market in markets:
        if len(markets) > 1:
            print(f"\n== {market} ==")
        result = grading.find_backfillable_closings(entries, snapshot_rows, market=market)
        checked = (len(result["derivable"]) + len(result["not_derivable"])
                  + len(result["no_recommendation"]))

        print(f"closing backfill: {checked} settlement(s) checked "
              f"({len(result['already_backfilled'])} already backfilled)")
        print(f"  derivable      : {len(result['derivable'])}")
        for row in result["derivable"]:
            prices = (row["closing"].get("prices") or {})
            if market == "h2h":
                detail = (f"away={prices.get('away_price')} "
                         f"home={prices.get('home_price')}")
            else:
                detail = f"prices={prices}"
            print(f"    {row['game_pk']:>7}  {row['away_team']}@{row['home_team']} "
                  f"{row['date']}  {detail}")
        print(f"  not derivable  : {len(result['not_derivable'])}")
        for row in result["not_derivable"]:
            print(f"    {row['game_pk']:>7}  {row['away_team']}@{row['home_team']} "
                  f"{row['date']}  reason={row['reason']}")
        if result["no_recommendation"]:
            print(f"  no matching recommendation row found  : "
                  f"{len(result['no_recommendation'])}")
        to_append_all.extend(result["to_append"])

    if getattr(args, "dry_run", False):
        print(f"\ndry run -- 0 appended (would append {len(to_append_all)})")
        return EXIT_OK

    grading.append_ledger_rows(to_append_all, ledger.DEFAULT_LEDGER)
    print(f"\n{len(to_append_all)} appended")

    coverage = grading.ledger_closing_coverage(ledger.read())
    print("\nclosing coverage by market (original + backfill / settled):")
    for c_market, c in sorted(coverage.items(), key=lambda kv: str(kv[0])):
        print(f"  {c_market:<40} {c['with_closing']:>4}/{c['settled']:<4}"
              f"  (original {c['from_original']}, backfill {c['from_backfill']})")
    return EXIT_OK


def cmd_brief(args) -> int:
    """Build the slate briefing and write the dashboard."""
    from src.detect import detectors as detector_defs
    from src.pipeline import briefing, bullpen, history, lineups, pitchers, travel
    from src.pipeline import slate as slate_mod
    from src.providers import odds as odds_prov
    from src.report import dashboard

    season = args.date[:4]
    store = history.read_results()
    if not store:
        print("historical store is empty -- run `ingest` first.", file=sys.stderr)
        return EXIT_ERROR
    try:
        games = mlb.fetch_games(args.date)
    except mlb.MLBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    logs = pitchers.read_logs() or None
    prices = {}
    if odds_prov.is_configured() and not args.no_odds:
        try:
            payload = odds_prov.fetch_normalized()
            for event in payload["events"]:
                away = slate_mod.team_abbrev_from_name(event.get("away_team"))
                home = slate_mod.team_abbrev_from_name(event.get("home_team"))
                if away and home:
                    quote = dict(event.get("markets") or {})
                    quote["all_books"] = event.get("all_books") or {}
                    prices[(away, home)] = quote
        except odds_prov.OddsProviderError as exc:
            print(f"  (odds unavailable: {exc})")

        if args.f5:
            _add_first_five(prices, slate_mod, odds_prov)

    detector_defs.register_defaults()
    pen_log = bullpen.read_log()
    pens = {}
    if pen_log:
        wanted = {t for g in games for t in (g.get("away_team"), g.get("home_team")) if t}
        for team in wanted:
            pens[team] = bullpen.team_workload(pen_log, team, args.date)
    else:
        print("  (no bullpen log -- run `bullpen` to enable those detectors)")

    posted = {}
    hands = {}
    splits = {}
    matchups = {}
    try:
        posted = lineups.fetch_lineups(args.date)
    except mlb.MLBError as exc:
        print(f"  (lineups unavailable: {exc})")
    # Probable starters go into the same handedness lookup as the hitters: the
    # platoon composition of a lineup is meaningless without knowing which hand
    # it is facing.
    ids = [g[k] for g in games for k in ("away_probable_id", "home_probable_id")
           if g.get(k)]
    ids += [s["person_id"] for lu in posted.values()
            for side in ("away", "home") for s in lu[side]]
    if ids:
        hands = lineups.fetch_handedness(ids)
    print(f"  lineups posted for {len(posted)} of {len(games)} game(s)")

    for game in games:
        pk = game.get("game_pk")
        for side, pid_key in (("away", "away_probable_id"),
                              ("home", "home_probable_id")):
            pid = game.get(pid_key)
            if not pid:
                continue
            try:
                record = lineups.fetch_pitcher_splits(pid, season)
            except mlb.MLBError:
                continue
            splits.setdefault(pk, {})[side] = {
                "record": record, "platoon": lineups.platoon_split(record)}
        if pk in posted and not args.no_matchups:
            for side, opposing in (("away", "home"), ("home", "away")):
                pid = game.get(f"{side}_probable_id")
                if not pid:
                    continue
                matchups.setdefault(pk, {})[opposing] = lineups.lineup_vs_pitcher(
                    posted[pk][opposing], pid, handedness=hands)

    from src.providers import statcast
    arsenals = batter_arsenals = {}
    try:
        arsenals = statcast.by_player(statcast.read(season, "pitcher"))
        batter_arsenals = statcast.by_player(statcast.read(season, "batter"))
        if arsenals:
            print(f"  arsenals for {len(arsenals)} pitchers, "
                  f"{len(batter_arsenals)} hitters")
        else:
            print("  (no pitch arsenals -- run `arsenals` to enable pitch-mix)")
    except statcast.StatcastError as exc:
        print(f"  (arsenals unavailable: {exc})")

    # Roster news. Ingest is cheap and free, so the store is topped up on every
    # run rather than depending on a separate scheduled job having fired.
    news_by_pk = {}
    if not args.no_news:
        from src.pipeline import news as news_mod
        try:
            news_mod.ingest(
                (date.fromisoformat(args.date)
                 - timedelta(days=news_mod.WINDOW_DAYS + 1)).isoformat(),
                args.date)
        except Exception as exc:  # noqa: BLE001 -- news is enrichment, never a blocker
            print(f"  (news feed unavailable: {exc})")
        news_rows = news_mod.read()
        if news_rows:
            for game in games:
                news_by_pk[game.get("game_pk")] = news_mod.attach(
                    game, news_rows, args.date)
            moves = sum(len(v) for entry in news_by_pk.values()
                        for v in entry["teams"].values())
            print(f"  roster news: {moves} recent move(s) across the slate")

    trips = {}
    for game in games:
        home = game.get("home_team")
        if not home:
            continue
        trips[game.get("game_pk")] = {
            team: travel.travel_load(store, team, args.date, home)
            for team in (game.get("away_team"), home) if team}

    weather_by_pk = {}
    if not args.no_weather:
        try:
            from src.providers import weather as weather_prov
            targets = []
            for game in games:
                if not game.get("home_team") or not game.get("start_time_utc"):
                    continue
                try:
                    targets.append((game, parks.coordinates(game["home_team"])))
                except parks.ParkError:
                    continue
            if targets:
                # One batched request for the whole slate. Park-by-park is
                # fifteen calls against a rate-limited endpoint, and the retries
                # are what actually cost the wall-clock.
                payloads = weather_prov.fetch_many(
                    [coords for _, coords in targets],
                    targets[0][0]["start_time_utc"][:10])
                for (game, _), payload in zip(targets, payloads):
                    reading = weather_prov.extract_hour(
                        payload, game["start_time_utc"])
                    if reading:
                        weather_by_pk[game["game_pk"]] = reading
            print(f"  weather for {len(weather_by_pk)} of {len(games)} game(s)")
        except Exception as exc:  # weather is enrichment, never a blocker
            print(f"  (weather unavailable: {exc})")

    slate = briefing.build_slate(games, store, pitcher_logs=logs,
                                 travel_by_pk=trips, weather_by_pk=weather_by_pk,
                                 arsenals=arsenals, batter_arsenals=batter_arsenals,
                                 prices_by_matchup=prices, bullpen_by_team=pens,
                                 lineups_by_pk=posted, handedness=hands,
                                 splits_by_pk=splits, matchups_by_pk=matchups,
                                 news_by_pk=news_by_pk)
    if not args.no_ledger:
        from src.pipeline import ledger
        written = ledger.record_slate(slate)
        print(f"  ledger: {written['recorded']} entries appended "
              f"({', '.join(f'{v} {k}' for k, v in sorted(written['verdicts'].items()))})")

    path = dashboard.render(slate, args.out)
    flagged = sum(1 for g in slate["games"] if g["verdict"] == "flagged")
    cand = sum(1 for g in slate["games"] if g["verdict"] == "candidate")
    print(f"briefing for {args.date}: {len(slate['games'])} game(s), "
          f"{flagged} flagged, {cand} candidate")
    print(f"  {path}")
    print("  open it in a browser -- no server needed")
    return EXIT_OK


# The exact sentence a hypothetical pairing carries on its starter and lineup
# sections. It is a constant so the dashboard, the tests, and any future reader
# of the card are all looking at one string, not three near-copies of it.
HYPOTHETICAL_GAP = "hypothetical matchup: no posted lineup or probable exists"


def cmd_archive(args) -> int:
    """Index every briefing artifact on disk into one static page."""
    from src.report import archive

    result = archive.scan(args.dir, out_name=args.out)
    path = archive.render(args.dir, args.out)
    bad = sum(1 for r in result["records"] if r.get("unparseable"))
    print(f"archive of {args.dir}: {len(result['records'])} file(s), "
          f"{bad} unparseable")
    for name, reason in result.get("skipped") or []:
        print(f"  not indexed: {name} ({reason})")
    print(f"  {path}")
    print("  open it in a browser -- no server needed")
    return EXIT_OK


def _analyze_out_path(away, home, iso_date) -> str:
    """Where the analyze card is promised to land."""
    return f"artifacts/analyze_{away}_{home}_{iso_date}.html"


def _find_stored_game(store, away, home, iso_date):
    """The real game(s) for (away, home, date) in the results store, if any.

    Matching is on the exact ordered pairing: CIN @ NYM is not NYM @ CIN.
    Doubleheaders return both games, ordered by game number, and the caller
    analyses the first while naming that a second exists.
    """
    matches = [row for row in store.values()
               if row.get("date") == iso_date
               and row.get("away_team") == away
               and row.get("home_team") == home]
    matches.sort(key=lambda r: str(r.get("game_number") or ""))
    return matches


def cmd_analyze(args) -> int:
    """Analyse one arbitrary pairing -- historical or hypothetical.

    Same dossier, same detectors, same card as the slate briefing; the only
    difference is where the game comes from. A real game on the date is found
    in the historical results store and analysed with its own game_pk and
    probables; a pairing with no real game gets an honest hypothetical card
    whose starter and lineup sections carry HYPOTHETICAL_GAP instead of data.

    The given date is the information cutoff. Everything point-in-time (team
    form, starter logs, travel, bullpen workload) is computed strictly from
    what existed before it; sources that cannot be reconstructed as of that
    date (weather, odds, arsenals, news) are named gaps, never backfilled
    from the present.
    """
    from src.analysis import prices as prices_mod
    from src.detect import detectors as detector_defs
    from src.pipeline import briefing, bullpen, history, lineup_store, pitchers, travel
    from src.report import dashboard

    try:
        away = parks.canonical_team(args.away)
        home = parks.canonical_team(args.home)
        parks.get_park(away)
        park = parks.get_park(home)
    except parks.ParkError as exc:
        print(f"ERROR: unknown team abbreviation: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if away == home:
        print(f"ERROR: a team cannot play itself ({away} vs {home})",
              file=sys.stderr)
        return EXIT_ERROR

    iso = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        date.fromisoformat(iso)
    except ValueError:
        print(f"ERROR: invalid date {iso!r} -- expected YYYY-MM-DD",
              file=sys.stderr)
        return EXIT_ERROR

    store = history.read_results()
    if not store:
        print("historical store is empty -- run `ingest` first.", file=sys.stderr)
        return EXIT_ERROR

    matches = _find_stored_game(store, away, home, iso)
    hypothetical = not matches
    if hypothetical:
        # No real game exists for this pairing on this date. The card is built
        # anyway, and every section that would need a posting says so.
        game = {"game_pk": None, "date": iso, "away_team": away,
                "home_team": home, "venue": park.get("name"),
                "start_time_utc": None,
                "away_probable_id": None, "home_probable_id": None}
        print(f"{away} @ {home} on {iso}: no real game on this date -- "
              "building an honest hypothetical card")
    else:
        stored = matches[0]
        game = {"game_pk": stored.get("game_pk"), "date": iso,
                "away_team": away, "home_team": home,
                "venue": stored.get("venue"),
                "start_time_utc": stored.get("start_time_utc"),
                "away_probable": stored.get("away_probable"),
                "home_probable": stored.get("home_probable"),
                "away_probable_id": stored.get("away_probable_id"),
                "home_probable_id": stored.get("home_probable_id")}
        print(f"{away} @ {home} on {iso}: real game {game['game_pk']}")
        if len(matches) > 1:
            print(f"  doubleheader: {len(matches)} games that day; analysing "
                  f"game {stored.get('game_number') or 1}. Re-run against the "
                  "other game_pk is not supported yet.")

    logs = pitchers.read_logs() or None
    if logs is None:
        print("  (no pitcher logs -- starter section will carry a gap)")

    # Lineups come from the point-in-time lineup STORE, never a live fetch: a
    # lineup fetched today for a 2023 game is today's data wearing an old date.
    posted = {}
    if game["game_pk"]:
        lineup = lineup_store.read().get(str(game["game_pk"]))
        if lineup:
            posted[game["game_pk"]] = lineup

    # Bat/throw side is biographical, not time-varying, so the cache is safe
    # to use at any cutoff. Cache only -- no network call for a past date.
    hands = {}
    try:
        import json as json_mod
        from src.pipeline import lineups as lineups_mod
        cache = Path(lineups_mod.DEFAULT_HANDEDNESS)
        if cache.exists():
            hands = json_mod.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hands = {}

    trips = {game["game_pk"]: {
        team: travel.travel_load(store, team, iso, home)
        for team in (away, home)}}

    pens = {}
    pen_log = bullpen.read_log()
    if pen_log:
        for team in (away, home):
            pens[team] = bullpen.team_workload(pen_log, team, iso)

    # Registration is not idempotent (the registry doubles as the hypothesis
    # count), so an already-populated registry is used as-is.
    from src.detect import base as detect_base
    if not detect_base.registry():
        detector_defs.register_defaults()

    # The cutoff is the END of the given date: postings made on the date are
    # in scope, anything after it is not. The point-in-time accessors already
    # take only games strictly before `iso`; this records the claim.
    cutoff = datetime.fromisoformat(iso).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc)

    slate = briefing.build_slate(
        [game], store, pitcher_logs=logs,
        lineups_by_pk=posted, handedness=hands,
        travel_by_pk=trips, bullpen_by_team=pens or None,
        price_improvement_by_key=prices_mod.by_matchup(),
        information_time=cutoff)

    if hypothetical:
        # A hypothetical pairing has no probables and no lineup by definition.
        # Whatever the assembly recorded for those sections (a null-starter
        # computation, a generic "not posted" reason) is replaced with the one
        # honest sentence that explains WHY: the game does not exist.
        dossier = slate["games"][0]["dossier"]
        for section in ("starters", "lineups"):
            dossier.sections.pop(section, None)
            dossier.miss(section, HYPOTHETICAL_GAP)

    out = args.out or _analyze_out_path(away, home, iso)
    path = dashboard.render(slate, out)
    entry = slate["games"][0]
    print(f"  verdict: {entry['verdict']}")
    print(f"  {path}")
    print("  open it in a browser -- no server needed")
    return EXIT_OK


def _add_first_five(prices, slate_mod, odds_prov):
    """Attach first-five prices per game. Billed per event, so it is opt-in.

    Without these the implied-bullpen detector cannot fire at all: its whole
    input is the gap between the full-game and first-five prices.
    """
    wanted = ["h2h_1st_5_innings", "totals_1st_5_innings"]
    try:
        events = odds_prov.list_events()
    except odds_prov.OddsProviderError as exc:
        print(f"  (first-five unavailable: {exc})")
        return
    cost = odds_prov.estimate_event_credits(len(events), markets=wanted)
    print(f"  pricing first five for {len(events)} game(s): "
          f"{cost['credits_total']} credits")
    for event in events:
        away = slate_mod.team_abbrev_from_name(event.get("away_team"))
        home = slate_mod.team_abbrev_from_name(event.get("home_team"))
        if not (away and home) or (away, home) not in prices:
            continue
        try:
            record = odds_prov.normalize_event(
                odds_prov.fetch_event_odds(event["id"], markets=wanted))
        except odds_prov.OddsProviderError as exc:
            print(f"    {away} @ {home}: {exc}")
            continue
        prices[(away, home)].update(record.get("markets") or {})
        for market, quotes in (record.get("all_books") or {}).items():
            prices[(away, home)].setdefault("all_books", {})[market] = quotes


def cmd_scan(args) -> int:
    """Scan a slate for obvious mismatches. Most days the answer is no play.

    Two stages, because the market screen has to run against the market a game is
    routed to and first-five prices are billed per game. Stage one is free and runs
    on everything; stage two buys prices only for what survived.
    """
    from src.pipeline import history, mismatch, pitchers
    from src.pipeline import slate as slate_mod
    from src.providers import odds as odds_prov

    store = history.read_results()
    if not store:
        print("historical store is empty -- run `ingest` first.", file=sys.stderr)
        return EXIT_ERROR

    try:
        games = mlb.fetch_games(args.date)
    except mlb.MLBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not games:
        print(f"no games scheduled for {args.date}")
        return EXIT_OK

    logs = pitchers.read_logs()
    if not logs:
        print("  (no pitcher logs -- starter signal unavailable)")
        logs = None

    prepared = mismatch.build_scan_inputs(store, games, pitcher_logs=logs)
    result = mismatch.scan_slate(prepared)

    if result["candidates"] and not args.no_price:
        prices = _price_candidates(result["candidates"], slate_mod, odds_prov)
        if prices is not None:
            result = mismatch.finalize_slate(result, prices)

    print(f"mismatch scan for {args.date}\n")
    print(result["summary"])

    if args.verbose:
        print("\n  every game, with why it did or did not clear the bar:")
        for scan in result["scans"]:
            print(f"\n  {scan['away_team']:>4} @ {scan['home_team']:<4}  "
                  f"[{scan['verdict']}]")
            for reason in scan["reasons"]:
                if reason:
                    print(f"      - {reason}")

    if result["flagged"] and not args.no_log:
        from src.pipeline import scanlog
        logged = scanlog.log_flags(result)
        print(f"\n  logged {logged['logged']} flag(s) to {logged['path']}")

    if result["flagged"]:
        print("\n  These are candidates to look at, not recommendations. The "
              "thresholds are pre-registered guesses that have never been "
              "validated against a result.")
    return EXIT_OK


F5_MARKETS = ["h2h_1st_5_innings", "totals_1st_5_innings"]


def _price_candidates(candidates, slate_mod, odds_prov):
    """Buy prices for candidates only, on the market each was routed to.

    Returns a game_pk -> prices map, or None when pricing could not run at all.
    Restricting to candidates is what makes first-five pricing affordable: the
    per-event endpoint bills per game, so two candidates cost 4 credits where a
    whole slate would cost 32.
    """
    if not odds_prov.is_configured():
        print(f"  (not priced: {odds_prov.status()['message']})")
        return None

    try:
        events = odds_prov.list_events()
    except odds_prov.OddsProviderError as exc:
        print(f"  (not priced: {exc})")
        return None

    ids = {}
    for event in events:
        away = slate_mod.team_abbrev_from_name(event.get("away_team"))
        home = slate_mod.team_abbrev_from_name(event.get("home_team"))
        if away and home:
            ids[(away, home)] = event.get("id")

    f5 = [c for c in candidates if c["market"] == "first_five"]
    cost = odds_prov.estimate_event_credits(len(f5), markets=F5_MARKETS)
    print(f"  pricing {len(candidates)} candidate(s); "
          f"{cost['credits_total']} credits for {len(f5)} first-five lookup(s)\n")

    prices = {}
    for scan in candidates:
        event_id = ids.get((scan["away_team"], scan["home_team"]))
        if not event_id:
            # Named rather than skipped. A missing event is usually a team-code
            # mismatch between the two feeds, which has silently cost this project
            # data twice before.
            print(f"    {scan['away_team']} @ {scan['home_team']}: no matching "
                  "event in the odds feed, so it cannot be screened")
            continue
        wanted = F5_MARKETS if scan["market"] == "first_five" else ["h2h"]
        try:
            record = odds_prov.normalize_event(
                odds_prov.fetch_event_odds(event_id, markets=wanted))
        except odds_prov.OddsProviderError as exc:
            print(f"    {scan['away_team']} @ {scan['home_team']}: {exc}")
            continue

        key = ("h2h_1st_5_innings" if scan["market"] == "first_five"
               else "h2h")
        moneyline = record["markets"].get(key)
        if not moneyline:
            print(f"    {scan['away_team']} @ {scan['home_team']}: no "
                  f"{'first-five' if key != 'h2h' else 'full-game'} moneyline offered")
            continue
        prices[scan["game_pk"]] = moneyline

        total = record["markets"].get("totals_1st_5_innings")
        line = (f"    {scan['away_team']} @ {scan['home_team']}  F5 ml "
                f"[{moneyline['book']}] away {moneyline['away_price']:+d} "
                f"home {moneyline['home_price']:+d}")
        if total:
            line += (f"  |  F5 total {total['total']} over "
                     f"{total['over_price']:+d} under {total['under_price']:+d}")
        print(line)
    print()
    return prices


def cmd_scan_grade(args) -> int:
    """Settle logged mismatch flags against the first five innings of their games."""
    from src.pipeline import scanlog

    entries = scanlog.read_log()
    if not entries:
        print("no flags logged yet -- run `scan` on a slate first.")
        return EXIT_OK

    dates = sorted({e.get("date") for e in entries if e.get("date")})
    results = {}
    for day in dates:
        try:
            for game in mlb.fetch_games(day):
                results[game["game_pk"]] = game
        except mlb.MLBError as exc:
            print(f"  (could not fetch {day}: {exc})")

    settled = scanlog.settle(entries, results)
    result = scanlog.report(settled)

    counts = result["counts"]
    print(f"mismatch flags: {result['flags_logged']} logged over "
          f"{len(dates)} date(s)\n")
    print(f"  won {counts['won']}   lost {counts['lost']}   "
          f"pushed {counts['pushed']}   void {counts['void']}   "
          f"unresolved {counts['unresolved']}")

    if result["decided"]:
        print(f"\n  decided      {result['decided']}")
        print(f"  hit rate     {result['hit_rate']:.1%}")
        print(f"  mean implied {result['mean_implied']:.1%}"
              "   (conditional on no push, as the two-way price is)")
        print(f"  edge         {result['edge']:+.1%}")

    print(f"\n  VERDICT: {result['verdict']}")
    if result["verdict_detail"]:
        print(f"    {result['verdict_detail']}")

    if args.verbose:
        print("\n  every settled flag:")
        for record in settled["settled"]:
            five = record.get("first_five") or {}
            score = (f"{five.get('away_runs')}-{five.get('home_runs')}"
                     if five.get("away_runs") is not None else "--")
            print(f"    {record['date']}  {record['away_team']:>4} @ "
                  f"{record['home_team']:<4}  {record['side']:>4}  "
                  f"F5 {score:>5}  {record['outcome']}")
    return EXIT_OK


def cmd_predict(args) -> int:
    """Predict a slate and compare the model against the market."""
    from src.model import logistic
    from src.pipeline import history, pitchers, predict as predictor
    from src.pipeline import slate as slate_mod
    from src.providers import odds as odds_prov

    try:
        model = logistic.load(processed_path("model.json"))
    except logistic.ModelError as exc:
        print(f"ERROR: {exc}\n  run `train` first.", file=sys.stderr)
        return EXIT_ERROR

    store = history.read_results()
    if not store:
        print("historical store is empty -- run `ingest` first.", file=sys.stderr)
        return EXIT_ERROR

    try:
        games = mlb.fetch_games(args.date)
    except mlb.MLBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not games:
        print(f"no games scheduled for {args.date}")
        return EXIT_OK

    logs = pitchers.read_logs() if model["features"] and any(
        f.startswith(("away_sp", "home_sp", "diff_sp")) for f in model["features"]
    ) else None

    prices = {}
    if odds_prov.is_configured():
        try:
            payload = odds_prov.fetch_normalized()
            for event in payload["events"]:
                h2h = (event.get("markets") or {}).get("h2h")
                away = slate_mod.team_abbrev_from_name(event.get("away_team"))
                home = slate_mod.team_abbrev_from_name(event.get("home_team"))
                if h2h and away and home:
                    prices[(away, home)] = h2h
        except odds_prov.OddsProviderError as exc:
            print(f"  (odds unavailable: {exc})")

    result = predictor.predict_slate(model, store, games,
                                     pitcher_logs=logs, odds_by_matchup=prices)

    print(f"predictions for {args.date}: {result['count']} game(s), "
          f"{result['comparable_count']} with market prices\n")

    ordered = sorted(result["predictions"],
                     key=lambda p: p.get("disagreement_abs") or -1, reverse=True)
    for p in ordered:
        line = (f"  {p['away_team']:>4} @ {p['home_team']:<4}  "
                f"model home {p['home_probability']:.3f}")
        if p.get("comparable"):
            robust = p.get("robustness", {})
            flag = "" if robust.get("robust") else "  [de-vig methods disagree]"
            line += (f"   market {p['market_home_fair']:.3f}"
                     f"   gap {p['disagreement_home']:+.3f}"
                     f"  ({p['model_favours']}){flag}")
        else:
            line += "   (no market price)"
        print(line)

    if result["unusable"]:
        print(f"\n  {len(result['unusable'])} game(s) not predictable:")
        for u in result["unusable"][:5]:
            print(f"    {u.get('away_team','?')}@{u.get('home_team','?')}: "
                  f"{u.get('reason')}")

    if result["comparable_count"]:
        print(f"\n  mean |gap| {result['mean_disagreement']:.4f}   "
              f"largest {result['largest_disagreement']:.4f}   "
              f"robust across de-vig methods: {result['robust_count']}"
              f"/{result['comparable_count']}")

    check = result.get("ignorance_check", {})
    if check.get("checked"):
        print(f"\n  DIAGNOSTIC")
        print(f"    model spread  {check['model_spread']:.4f}   "
              f"market spread {check['market_spread']:.4f}   "
              f"ratio {check['spread_ratio']}")
        print(f"    corr(gap, market confidence) "
              f"{check['correlation_gap_vs_market_confidence']}")
        print(f"    ranking by disagreement meaningful: "
              f"{check['ranking_is_meaningful']}")
        if check.get("warning"):
            print(f"\n    *** {check['warning']}")

    if getattr(args, "log", False):
        from src.pipeline import grading
        check = result.get("ignorance_check", {})
        for p in result["predictions"]:
            p["ranking_was_meaningful"] = check.get("ranking_is_meaningful")
        logged = grading.log_predictions(
            result["predictions"],
            model_version=model.get("metadata", {}).get("trained_on"))
        print(f"\n  logged {logged['logged']} prediction(s) to {logged['path']}")
        print("  the log is append-only: these cannot be revised later.")

    print(f"\n  {result['warning']}")
    return EXIT_OK


def cmd_grade(args) -> int:
    """Settle logged predictions against final results and report CLV."""
    from src.pipeline import grading, history, snapshots

    entries = grading.deduplicate(grading.read_log())
    if not entries:
        print("no predictions logged yet -- run `predict --log` first.")
        return EXIT_OK

    settled = grading.settle(entries, history.read_results(),
                             snapshot_rows=snapshots.read())
    counts = settled["counts"]
    print(f"prediction log: {len(entries)} entries\n")
    print(f"  graded     : {counts['graded']}")
    print(f"  pending    : {counts['pending']}  (game not final yet)")
    print(f"  unresolved : {counts['unresolved']}")

    summary = grading.report(settled)
    if summary["n"] == 0:
        print(f"\n  {summary['note']}")
        return EXIT_OK

    print(f"\n  accuracy   : {summary['accuracy']}  (n={summary['n']})")
    print(f"  brier      : {summary['brier']}")
    print(f"\n  CLV (the primary metric)")
    print(f"    graded         : {summary['clv_n']}")
    if summary["clv_n"]:
        print(f"    beat the close : {summary['clv_beat_rate']}")
        print(f"    mean prob edge : {summary['clv_mean_prob_edge']}")
    if summary["clv_ungraded"]:
        print(f"    ungraded       : {summary['clv_ungraded']}")
        for reason, count in summary["clv_ungraded_reasons"].items():
            print(f"      {count}x {reason}")

    print(f"\n  VERDICT: {summary['verdict']}")
    print(f"  {summary['note']}")
    return EXIT_OK


def cmd_mybets_closing_backfill(args) -> int:
    """Fill closing-price fields on already-settled My Bets rows that
    predate the closing-price feature. One-time catch-up; settling a bet
    going forward already computes this at settle time
    (src.appstate.settlement.settle_saved_bets) and never needs backfill.
    A clean no-op when there is no app db, matching every other My-Bets
    entry point's rule that the research CLI must never create the product
    database just by running.
    """
    from src.appstate import savedbets, settlement
    from src.pipeline import snapshots

    db = savedbets.db_path()
    if not db.exists():
        print(f"no app db at {db}; nothing to backfill")
        return EXIT_OK

    report = settlement.backfill_closing_prices(snapshots.read(), db=db)
    print(f"checked {report['checked']} settled bet(s) missing a closing price")
    print(f"  filled  {report['filled']}")
    if report["ungraded_reasons"]:
        print("  could not compute a closing price for:")
        for reason, count in sorted(report["ungraded_reasons"].items()):
            print(f"    {count}x {reason}")
    return EXIT_OK


def cmd_daily(args) -> int:
    """The whole loop, in the order that keeps the evidence honest.

    Order matters and is not arbitrary:
      1. snapshot odds FIRST -- line movement cannot be backfilled, so a failure
         later in the run must not cost the observation.
      2. ingest yesterday's results, so grading has something to settle against.
      3. ingest yesterday's PITCHER logs, so today's starter features exist. Skip
         this and the mismatch scanner silently reports no play every day, because
         every starter looks like an unknown with no prior appearances.
      4. refresh bullpen appearances, which availability depends on.
      5. build today's briefing and append it to the FORWARD LEDGER. This is the
         only evidence in the project that cannot be corrupted by discipline
         failing, so it runs every day whether or not anything is flagged.
      6. settle whatever has finished, against results that were unknowable when
         the recommendation was written.
      7. grade the older prediction and flag logs.
      8. settle My Bets (the product's saved-bet outcomes) against the same
         results store -- a clean no-op if there is no app db on this
         machine, since this research loop must never bring the product
         database into existence just by running (see
         src.appstate.settlement.settle_saved_bets_if_app_db_exists).
      9. fetch yesterday's per-game, per-player box lines (free MLB Stats API,
         no odds credit) -- the substrate every batter and non-strikeout
         pitcher prop needs to ever be settled. Runs last and never fails the
         loop: box lines do not expire, so a missed fetch is picked up on the
         next day's run.

    Every step is independent. One failing does not abort the rest, because a
    missed grading run is recoverable and a missed snapshot is not.
    """
    from datetime import timedelta

    today = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.strptime(today, "%Y-%m-%d")
                 - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"daily loop for {today}\n")
    failures = []

    def step(number, name, fn):
        print(f"[{number}/9] {name}")
        try:
            fn()
        except Exception as exc:  # a step failing must not kill the loop
            failures.append((name, str(exc)))
            print(f"      FAILED: {exc}")
        print()

    # 1. Snapshot first. This is the only irreplaceable step.
    def do_snapshot():
        from src.pipeline import dense, snapshots
        # Free-schedule gate before the one paid call in the daily loop.
        # snapshots.capture() bills the whole-sport odds request the same
        # whether the slate has 15 games or zero, so a slate-less off-season
        # day would otherwise cost ~3 credits every day for nothing. dense's
        # hourly loop already gates on this same free check; the daily loop
        # did not. None (schedule unreachable) is NOT a skip -- missed
        # movement on a live day cannot be recovered, so unknown means spend.
        if dense.any_game_scheduled() is False:
            print("      skipped: no MLB games scheduled -- no paid capture "
                  "(off-season / dead day)")
            return
        result = snapshots.capture()
        if not result["configured"]:
            print(f"      skipped: {result['message']}")
        elif result.get("error"):
            raise RuntimeError(result["error"])
        else:
            print(f"      captured {result['captured']} observations "
                  f"across {result['events']} events")

    def do_ingest():
        from src.pipeline import history
        report = history.ingest_range(yesterday, yesterday)
        print(f"      {yesterday}: {report['processed']} date(s) processed, "
              f"{report['total_games_stored']} games in store")

    def do_pitchers():
        from src.pipeline import history, pitchers
        store = history.read_results()
        ids = pitchers.probable_pitcher_ids(store)
        report = pitchers.build_log_store(ids, today[:4])
        print(f"      {report['processed']} pitcher(s) fetched, "
              f"{report['pitchers_in_store']} in store, "
              f"{report['appearances']} appearances")

    def do_pen():
        from src.pipeline import bullpen
        report = bullpen.build_log(yesterday, yesterday)
        print(f"      {report['appearances']} appearance(s) from "
              f"{report['games']} game(s)")

    def do_brief():
        code = cmd_brief(argparse.Namespace(
            date=today, out="artifacts/briefing.html", no_odds=False,
            no_weather=False, no_matchups=False, no_news=False,
            no_ledger=False, f5=True))
        if code != EXIT_OK:
            raise RuntimeError("briefing step returned a non-zero exit")

    def do_settle():
        cmd_ledger(argparse.Namespace(status=False))

    def do_predict():
        from src.pipeline import grading
        code = cmd_predict(argparse.Namespace(date=today, log=True))
        if code != EXIT_OK:
            raise RuntimeError("prediction step returned a non-zero exit")

    def do_grade():
        cmd_grade(argparse.Namespace())
        print()
        cmd_scan_grade(argparse.Namespace(verbose=False))

    def do_settle_my_bets():
        from src.appstate import settlement
        from src.pipeline import history, snapshots
        report = settlement.settle_saved_bets_if_app_db_exists(
            history.read_results, snapshot_rows=snapshots.read())
        if report.get("skipped"):
            print(f"      skipped: {report['reason']}")
        else:
            print(f"      settled {report['settled']} bet(s) {report['counts']}, "
                  f"{report['unsettled']} still unsettled")

    def do_boxscores():
        # Free (keyless) MLB Stats API call, same host as every other
        # fetch_* in src.providers.mlb -- no odds credit involved. A fetch
        # failure here is exactly the shape "a missed grading run is
        # recoverable": box lines do not expire, so this is retried
        # automatically on tomorrow's run without any of them being lost --
        # it must never fail the daily loop over a slate that has no props
        # graded against it yet.
        from src.pipeline import boxscores
        report = boxscores.ingest_date(yesterday)
        print(f"      {yesterday}: {report['games_written']} game(s) written, "
              f"{report['games_skipped']} already stored, "
              f"{report['pitcher_rows']} pitcher / {report['batter_rows']} "
              f"batter rows")

    step(1, "capture odds snapshot (irreplaceable -- runs first)", do_snapshot)
    step(2, f"ingest results for {yesterday}", do_ingest)
    step(3, f"refresh pitcher logs for {today[:4]}", do_pitchers)
    step(4, f"refresh bullpen appearances for {yesterday}", do_pen)
    step(5, f"brief {today} and append to the forward ledger", do_brief)
    step(6, "settle finished games", do_settle)
    step(7, "grade settled predictions and flags", do_grade)
    step(8, "settle My Bets (product db, no-op if absent)", do_settle_my_bets)
    step(9, f"fetch box lines for {yesterday} (free, props substrate)",
         do_boxscores)

    if failures:
        print(f"loop finished with {len(failures)} failed step(s):")
        for name, error in failures:
            print(f"  {name}: {error}")
        return EXIT_ERROR
    print("loop finished cleanly.")
    return EXIT_OK


def cmd_dense(args) -> int:
    """Take a spaced series of snapshots while games are approaching.

    Meant for an hourly schedule. Four captures fifteen minutes apart tile one
    hour, and the run costs nothing on an hour with no game inside the window.
    """
    from src.pipeline import dense

    if args.estimate:
        cost = dense.estimate_daily_credits()
        print(f"{cost['credits_per_call']} credits per capture, "
              f"{cost['captures_per_hour']} per hour")
        print(f"  {cost['credits_per_day']} credits a day across "
              f"{cost['hours_of_baseball']} hours of baseball")
        print(f"  {cost['credits_per_month']} a month if it ran every day")
        return EXIT_OK

    from src.pipeline import rosterwatch
    result = dense.run(captures=args.captures, interval_minutes=args.interval,
                       window_minutes=args.window,
                       poll_hook=rosterwatch.poll)
    if result.get("skipped"):
        print(f"skipped: {result['skipped']}")
        if result.get("credits_remaining") is not None:
            print(f"  {result['credits_remaining']} credits remaining, "
                  f"floor is {result['floor']}")
        return EXIT_OK

    print(f"{result['captures']} capture(s), "
          f"{result['observations']} observations")
    for row in result["detail"]:
        note = f" ERROR: {row['error']}" if row.get("error") else ""
        print(f"  {row['at']}  {row['games_in_window']} game(s) in window, "
              f"{row['captured']} observations{note}")
    if result.get("stopped_early"):
        print(f"  stopped early: {result['stopped_early']}")
    close = result.get("close_capture")
    if close:
        if close.get("skipped"):
            print(f"  close-capture pass skipped: {close['skipped']}")
        else:
            print(f"  close-capture pass at {close['at']}: "
                  f"{close['captured']} observations (game within "
                  f"{dense.CLOSE_WINDOW_MINUTES} minutes of first pitch)")
    for miss in result.get("missed_windows") or []:
        print(f"  MISSED WINDOW: game at {miss['commence_time']} "
              f"{miss['reason']}")
    # The F5 miss-detector reached stdout for nobody: `run()` returned
    # `missed_f5_closes` and this block never printed it, so the one signal
    # that says the market-depth lane lost a closing line was invisible to
    # both the operator and the text scripts/forward_capture.sh greps.
    f5 = result.get("f5_closes") or {}
    for drop in f5.get("dropped") or []:
        print(f"  F5 BUDGET DROP: {_f5_game_label(drop)} {drop['reason']}")
    for miss in result.get("missed_f5_closes") or []:
        print(f"  MISSED F5 CLOSE: {_f5_game_label(miss)} {miss['reason']}")
    return EXIT_OK


def _f5_game_label(entry) -> str:
    """Name the game, not just the clock.

    Four games start at 22:40 on a normal card, so a bare timestamp does not
    identify which close was lost. Teams when the row has them, timestamp
    always -- never invented.
    """
    away, home = entry.get("away_team"), entry.get("home_team")
    who = f"{away} at {home} " if away and home else ""
    return f"{who}({entry.get('commence_time')}):"


def cmd_snapshot(args) -> int:
    """Capture one odds observation. Meant to run on a schedule.

    Line movement cannot be backfilled from free sources, so this is the one job whose value
    depends entirely on having started early. Every run that does not happen is market data
    that can never be recovered.
    """
    from src.pipeline import dense, snapshots

    # Same free-schedule gate the daily loop uses: never spend the paid
    # whole-sport capture on a day with zero games on the board. Unknown
    # (schedule endpoint down) still captures -- irreplaceable movement is
    # worth the credit; a confirmed empty slate is not.
    if dense.any_game_scheduled() is False:
        print("skipped: no MLB games scheduled -- no paid capture "
              "(off-season / dead day)")
        return EXIT_OK

    result = snapshots.capture()
    if not result["configured"]:
        print(f"not configured: {result['message']}", file=sys.stderr)
        return EXIT_NOT_CONFIGURED
    if result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return EXIT_ERROR

    print(f"captured {result['captured']} observations across "
          f"{result['events']} events at {result['observed_utc']}")
    print(f"  -> {result['written_to']}")

    history = snapshots.read()
    report = snapshots.coverage(history)
    print(f"\n  history: {report['observations']} observations, "
          f"{report['games']} games")
    print(f"  closing lines captured: {report['with_closing']}/{report['games']} "
          f"({report['closing_rate'] * 100:.0f}%)")
    if report["first_utc"]:
        print(f"  window: {report['first_utc'][:16]} .. {report['last_utc'][:16]}")
    return EXIT_OK


def cmd_movement(args) -> int:
    """Show line movement for everything captured so far."""
    from src.pipeline import snapshots

    history = snapshots.read()
    if not history:
        print("no snapshots recorded yet -- run `snapshot` to start capturing.")
        print("line movement cannot be backfilled, so start this early.")
        return EXIT_OK

    grouped = snapshots.group_by_game(history, market=args.market)
    if not grouped:
        print(f"no observations for market {args.market!r}")
        return EXIT_OK

    print(f"line movement ({args.market}, home side)\n")
    for (away, home, day), series in sorted(grouped.items(), key=lambda kv: kv[0][2]):
        move = snapshots.movement(series)
        closing = snapshots.closing_observation(series)
        close_note = "" if closing else "   [no close captured]"
        if move["observations"] < 2:
            print(f"  {day}  {away} @ {home}: "
                  f"{move['observations']} observation(s) -- not enough to show movement"
                  f"{close_note}")
            continue
        print(f"  {day}  {away} @ {home}")
        print(f"    open {move['opening']:>5}  ->  close {move['closing']:>5}  "
              f"({move['moved']:+d}, {move['direction']}, "
              f"{move['observations']} obs){close_note}")
    return EXIT_OK


def cmd_watch(args) -> int:
    """One rosterwatch poll (free MLB endpoints, zero odds credits).

    Run every 10-15 minutes; the poll cadence IS the timestamp resolution
    the V3 event brackets get, so a missed poll widens every bracket that
    spans it.
    """
    import json as json_mod
    from src.pipeline import rosterwatch

    if args.events:
        for event in rosterwatch.events():
            print(json_mod.dumps(event, sort_keys=True))
        return EXIT_OK

    report = rosterwatch.poll(game_date=args.date)
    for source in ("probables", "lineups", "transactions"):
        detail = report[source]
        print(f"  {source}: " + ("FAILED (skipped)" if detail is None else
                                 ", ".join(f"{k}={v}" for k, v in detail.items())))
    for error in report["errors"]:
        print(f"  ERROR {error['source']}: {error['error']}", file=sys.stderr)
    print(f"  -> {report['dir']}")
    # Partial capture is still capture; only a totally blind poll is an error.
    return EXIT_ERROR if len(report["errors"]) == 3 else EXIT_OK


def cmd_events(args) -> int:
    """Project InformationEvents from the free-environment watch/processed
    stores into data/processed/information_events.jsonl (packet W6). Pure
    diff over existing stores -- no new network calls -- and safe to run
    from scripts/capture_extras.sh: it never raises past this wrapper.
    """
    from src.board import events as board_events

    try:
        result = board_events.run(since=args.since)
    except Exception as exc:  # never fail the capture script
        print(f"  events: FAILED (skipped): {exc}", file=sys.stderr)
        return EXIT_OK
    print(f"  events: seen={result['seen']} written={result['written']}")
    for kind, count in sorted(result["by_kind"].items()):
        print(f"    {kind}: {count}")
    return EXIT_OK


def cmd_timing(args) -> int:
    """The V3 accumulation status; pre-registered tables only past the floor."""
    from src.research import timingreport

    result = timingreport.report()
    print(timingreport.format_report(result))
    for name, entry in result["classes"].items():
        table = entry.get("response_table")
        if table:
            import json as json_mod
            print(f"\n{name} response table:")
            print(json_mod.dumps(table, indent=2))

    if getattr(args, "test", False):
        import json as json_mod

        from src.research import timingtest

        print("\nprimary test (src/research/timingtest.py):")
        verdicts = timingtest.test_all(report_result=result)
        for name, verdict in verdicts.items():
            if verdict.get("status") == "below floor":
                print(f"\n{name}: below floor "
                      f"({verdict['measurable_events']}/{verdict['floor']} "
                      "measurable; not read)")
                continue
            print(f"\n{name}:")
            print(json_mod.dumps(verdict, indent=2, default=str))
    return EXIT_OK


def cmd_health(args) -> int:
    """Slate data-quality health: is today's collection actually collecting?

    Read-only over the stores; exits non-zero on anomalies so the data plane
    can grep-or-exit-code its way to an ESCALATE line.
    """
    from src.pipeline import health

    result = health.report(date=args.date)
    print(health.format_report(result))
    return EXIT_OK if result["healthy"] else EXIT_ERROR


def _load_system_import(spec: str):
    """`spec` is `"module.path:attr"`. `attr` may be an `AnalysisSystem`
    instance directly, or a zero-argument callable that returns one --
    tried in that order so a plain module-level instance needs no factory
    wrapper. Returns `(system, factory_spec_or_None)`: `factory_spec` is
    `spec` itself when `attr` was callable (so the determinism check can
    reconstruct it in a fresh process), else `None`."""
    import importlib
    if ":" not in spec:
        raise SystemExit(f"SYSTEM must be 'module.path:attr', got {spec!r}")
    module_name, attr_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    try:
        attr = getattr(module, attr_name)
    except AttributeError as exc:
        raise SystemExit(f"{module_name!r} has no attribute {attr_name!r}: "
                          f"{exc}") from None
    if callable(attr) and not hasattr(attr, "propose"):
        return attr(), spec
    return attr, None


def _synthetic_conformance_snapshots(system):
    """A small, self-contained sample of `PriceBlindSnapshot`s covering
    `system.declared_inputs`/`declared_markets` with plain synthetic values.
    Conformance checks purity/blindness/schema/declared-inputs shape, not
    a specific model output, so a fixed synthetic sample is sufficient and
    reproducible -- it never touches disk or the network."""
    from src.engine.snapshot import PriceBlindSnapshot

    declared_inputs = tuple(getattr(system, "declared_inputs", ()) or ())
    declared_markets = tuple(getattr(system, "declared_markets", ()) or ("h2h",))
    books_by_market = {m: 3 for m in declared_markets}
    snapshots = []
    for i, value in enumerate((0.0, 0.5, 1.0)):
        features = {name: value + 0.01 * i for name in declared_inputs}
        snapshots.append(PriceBlindSnapshot(
            game_pk=str(1000 + i), t=f"2026-04-{11 + i:02d}T20:00:00Z",
            point_class="LATE_BOARD", features=features,
            available_markets=declared_markets,
            books_by_market=books_by_market,
            lineup_posted=True,
        ))
    return snapshots


def cmd_engine(args) -> int:
    if args.engine_command == "conform":
        from src.engine.conformance import run_conformance

        system, factory_spec = _load_system_import(args.system)
        snapshots = _synthetic_conformance_snapshots(system)
        result = run_conformance(system, snapshots, system_factory=factory_spec)
        print(f"conformance: {result.system_id} "
              f"{'PASS' if result.passed else 'FAIL'}")
        for check in result.checks:
            status = "PASS" if check.passed else "FAIL"
            print(f"  [{status}] {check.name}")
            for reason in check.reasons:
                print(f"      {reason}")
        return EXIT_OK if result.passed else EXIT_ERROR

    if args.engine_command == "truncation":
        return _cmd_engine_truncation(args)

    if args.engine_command == "slate":
        return _cmd_engine_slate(args)

    if args.engine_command == "settle":
        return _cmd_engine_settle(args)

    if args.engine_command == "replay-one":
        return _cmd_engine_replay_one(args)

    raise SystemExit(f"unknown engine subcommand {args.engine_command!r}")


def _cmd_engine_slate(args) -> int:
    """S5: `engine slate --date DATE [--asof ISO8601] [--systems a,b,c]
    [--dry-run]`. See `src.engine.slate.run_slate`.

    S8: refuses before touching `run_slate` at all -- no board built, no
    decision written, no wager staked -- when `src.engine.preflight.check`
    finds either input too stale (docs/CHECKPOINT_PHASE0_2026-09-03.md S8
    point 2). This is the guard against the daily loop's unattended slate
    step quietly betting on a stale board or stale matchup features.
    """
    from src.engine import preflight

    freshness = preflight.check(args.date)
    if not freshness.ok:
        print(f"ERROR: engine slate --date {args.date} refused by the "
              f"pre-slate freshness guard ({freshness.mode} mode) -- no "
              "board built, nothing staked", file=sys.stderr)
        for reason in freshness.reasons:
            print(f"  ERROR: {reason}", file=sys.stderr)
        return EXIT_ERROR

    from src.engine import slate as engine_slate
    from src.engine.adapters.evolab_system import REGISTERED_SYSTEMS

    systems = REGISTERED_SYSTEMS
    if args.systems:
        wanted = set(args.systems.split(","))
        systems = tuple(s for s in REGISTERED_SYSTEMS if s.id in wanted)
        missing = wanted - {s.id for s in systems}
        if missing:
            print(f"ERROR: unknown system id(s) {sorted(missing)} -- "
                  f"registered ids: {[s.id for s in REGISTERED_SYSTEMS]}",
                  file=sys.stderr)
            return EXIT_ERROR

    try:
        report = engine_slate.run_slate(
            args.date, systems=systems, asof=args.asof, dry_run=args.dry_run)
    except engine_slate.SlateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    label = "PAPER" if not args.dry_run else "PAPER (dry-run, nothing written)"
    print(f"[{label}] engine slate --date {args.date}"
          + (f" --asof {args.asof}" if args.asof else "")
          + f" --systems {','.join(report.systems)}")
    print(f"  freshness guard mode: {freshness.mode}"
          + (" (today -- wall-clock now)" if freshness.mode == "LIVE"
             else " (past date -- measured against that date's own decision"
                  " time, not today's clock)"))
    print(f"  games considered    : {report.n_games_considered}")
    print(f"  games skipped       : {report.n_games_skipped}")
    for g in report.games:
        if g.skipped_reason:
            print(f"    skipped game={g.game_key}: {g.skipped_reason}")
    print(f"  decisions written   : {report.n_new_decisions} new, "
          f"{report.n_duplicate_decisions} already recorded")
    print(f"  adversary activity  : {report.n_vetoed} surviving record(s) "
          "carry a counterargument")
    print(f"  [PAPER] wagers placed: {report.n_new_wagers} new, "
          f"{report.n_duplicate_wagers} already placed")
    for g in report.games:
        for record in g.records:
            staked = " STAKED" if record.stake_units else ""
            print(f"    [{record.system_id}] {g.game_key} "
                  f"{record.market_key}/{record.selection_id} "
                  f"verdict={record.verdict} price={record.price_american} "
                  f"p_model={record.p_model} value_basis={record.value_basis} "
                  f"grade={record.known_at_grade}{staked}")
    print(f"  selection_rule      : {engine_slate.SELECTION_RULE}")
    return EXIT_OK


def _cmd_engine_settle(args) -> int:
    """S6a: `engine settle --date DATE`. See
    `src.engine.settle_slate.run_settle`."""
    from src.engine import settle_slate

    try:
        report = settle_slate.run_settle(args.date)
    except settle_slate.SettleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"[PAPER] engine settle --date {args.date}")
    print(f"  wagers considered   : {report.n_wagers_considered} "
          f"across {report.n_games} game(s)")
    for s in report.systems:
        print(f"  [{s.system_id}] settled {len(s.settled)} new "
              f"({s.duplicate} already settled)")
        for settled in s.settled:
            print(f"    [PAPER] {settled.bet.bet_id} "
                  f"{settled.bet.market_key}/{settled.bet.selection_id} "
                  f"price={settled.bet.price_american} "
                  f"outcome={settled.outcome} "
                  f"profit_units={settled.profit_units:+.4f}")
        print(f"    [PAPER] bankroll={s.bankroll:.2f} "
              f"roi_units={s.roi_units:.4f} "
              f"drawdown_max={s.drawdown_max:.2f}")
        v = s.scorecard_verdict
        print(f"    scorecard verdict   : "
              f"{'PROMOTE' if v.promote else 'REFUSE'} -- {'; '.join(v.reasons)}")
        if s.scorecard_absent:
            print(f"    scorecard absent    : "
                  f"{[a.field for a in s.scorecard_absent]}")
    return EXIT_OK


def _cmd_engine_replay_one(args) -> int:
    """S3 demonstration: `engine replay-one --season YEAR --game-pk PK
    [--point-class LATE_BOARD|EARLY_BOARD] [--system SYSTEM_ID]`. Runs ONE
    2023-24 replay decision through `analyze()` via the S3 replay driver
    (`src.engine.adapters.evolab_system.replay_decision`) and settles it
    against the ALREADY-KNOWN historical result -- this is a demonstration
    of the unified path, not the live slate runner (S5), which only ever
    operates on captured 2026 L1 prices."""
    from src.engine import glue as glue_module
    from src.engine.adapters.evolab_system import REGISTERED_SYSTEMS, replay_decision
    from src.engine.adversaries import DEFAULT_ADVERSARIES
    from src.evolab import replay as replay_module
    from src.accounts.paper import PaperBet, settle_bet
    from src.board.ids import MARKET_CATALOGUE
    from src.engine.settle_slate import load_mlb_results, load_first_five_results, \
        build_game_result

    universe = replay_module.load_universe([args.season])
    try:
        game = universe.get(args.game_pk)
    except replay_module.ReplayError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    points = [p for p in replay_module.decision_points([args.season], universe=universe)
              if p.game_pk == str(args.game_pk)]
    if args.point_class:
        points = [p for p in points if p.point_class == args.point_class]
    if not points:
        print(f"ERROR: no decision point for game_pk={args.game_pk} "
              f"season={args.season} point_class={args.point_class!r}",
              file=sys.stderr)
        return EXIT_ERROR
    point = points[-1]

    system = REGISTERED_SYSTEMS[0]
    if args.system:
        matches = [s for s in REGISTERED_SYSTEMS if s.id == args.system]
        if not matches:
            print(f"ERROR: unknown system id {args.system!r} -- registered: "
                  f"{[s.id for s in REGISTERED_SYSTEMS]}", file=sys.stderr)
            return EXIT_ERROR
        system = matches[0]

    adversaries = DEFAULT_ADVERSARIES if args.adversaries else ()
    analysis = replay_decision(system, game, point.T,
                               point_class=point.point_class,
                               adversaries=adversaries)

    print(f"engine replay-one --season {args.season} --game-pk {args.game_pk} "
          f"--point-class {point.point_class} --system {system.id}"
          + (" --adversaries" if args.adversaries else ""))
    print(f"  game                : {game.away_team} @ {game.home_team}, "
          f"official_date={game.official_date}, commence={game.commence_time}")
    print(f"  decision T          : {point.T} (gap_minutes={point.gap_minutes:.1f}, "
          f"books={point.books})")
    print(f"  records             : {len(analysis.records)}")

    results = load_mlb_results()
    f5_historical = load_first_five_results()
    result = build_game_result(game.game_pk, results, f5_historical, {})

    for record in analysis.records:
        print(f"  [{record.system_id}] verdict={record.verdict} "
              f"market={record.market_key} selection={record.selection_id} "
              f"price={record.price_american} p_model={record.p_model} "
              f"value_basis={record.value_basis} rating={record.rating} "
              f"known_at_grade={record.known_at_grade}")
        for c in record.counterarguments:
            print(f"    counterargument: {c}")
        if record.verdict != "play":
            continue
        if result is None:
            print(f"    [PAPER] no settlement -- no result found for "
                  f"game_pk={game.game_pk} in {load_mlb_results.__module__}'s "
                  "results store")
            continue
        settlement_rule = MARKET_CATALOGUE[record.market_key].settlement_rule
        side = _side_for_decision_record(record)
        bet = PaperBet(
            bet_id=f"replay-{game.game_pk}-{record.system_id}",
            system_id=record.system_id, market_key=record.market_key,
            selection_id=record.selection_id, side=side, line=record.line,
            price_american=record.price_american,
            settlement_rule=settlement_rule, game_pk=int(game.game_pk),
        )
        settled = settle_bet(bet, result)
        print(f"    [PAPER] settlement result={result} outcome={settled.outcome} "
              f"profit_units={settled.profit_units:+.4f} "
              "(replay demonstration only -- this bet is NOT written to any "
              "paper account ledger)")
    return EXIT_OK


def _side_for_decision_record(record) -> str:
    from src.board.ids import MARKET_CATALOGUE, selection_id as _sel_id
    spec = MARKET_CATALOGUE[record.market_key]
    for side in spec.sides:
        if _sel_id(sport="mlb", market_key=record.market_key, side=side,
                  line=record.line) == record.selection_id:
            return side
    raise ValueError(f"could not recover side for {record.selection_id!r}")


def _cmd_engine_truncation(args) -> int:
    """`engine truncation --date DATE --sample N --t-offset MINUTES`, wired
    to real data (packet W11): sample games from `DATE`'s L1 captures, run
    the truncation differential (`t` = `min(each game's own latest capture
    that day, commence_time - margin)`, per the first-pitch guard --
    bug #2 -- `t-2h` = `t - t_offset` minutes) with the registered trivial
    fallback system (see `src.engine.glue.TrivialAlwaysHomeSystem` -- no
    evolab-adapter genome can be wired honestly against odds-provider
    event_ids in this environment; see glue.py's module docstring) and the
    adversary roster, append a G4 `GateResult` record to
    `data/processed/gate_results.jsonl`, and print the differential report.
    Refuses honestly (non-zero exit, no record written) when the date has
    no captures at all, or when every captured game is in-play/unverifiable
    and therefore skipped.
    """
    from src.engine import glue as glue_module
    from src.engine.adversaries import DEFAULT_ADVERSARIES
    from src.engine.truncation import truncation_differential

    try:
        samples, skipped = glue_module.sample_truncation_inputs(
            args.date, args.sample, t_offset_minutes=args.t_offset,
            return_skipped=True)
    except glue_module.GlueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    systems = (glue_module.TrivialAlwaysHomeSystem(),)
    report = truncation_differential(
        samples, systems=systems, adversaries=DEFAULT_ADVERSARIES)

    print(f"engine truncation --date {args.date} --sample {args.sample} "
          f"--t-offset {args.t_offset}")
    print(f"  games sampled       : {report.sample_size} "
          f"(of {len(glue_module.games_captured_on(args.date))} captured "
          f"that day)")
    print(f"  games skipped       : {len(skipped)} (first-pitch guard: "
          "in-play or commence_time unverifiable)")
    for s in skipped:
        print(f"    skipped game={s.game}: {s.reason}")
    print(f"  diffs found         : {len(report.diffs)}")
    print(f"  leakage failures    : {len(report.leakage_failures)}")
    print(f"  gate                : {report.gate_result.gate} "
          f"{'PASS' if report.gate_result.passed else 'FAIL'}")
    for reason in report.gate_result.reasons:
        print(f"    {reason}")
    if report.leakage_failures:
        print("\n  leakage detail (never suppressed):")
        for d in report.leakage_failures:
            print(f"    game={d.game_pk} selection={d.selection_id} "
                  f"system={d.system_id} changed={list(d.changed_fields)}")

    record = {
        "written_utc": datetime.now(timezone.utc).isoformat(),
        "date": args.date,
        "sample_size": report.sample_size,
        "games": sorted(s.game_pk for s in samples),
        "games_skipped": [{"game": s.game, "reason": s.reason}
                           for s in skipped],
        "t_offset_minutes": args.t_offset,
        "systems": [s.id for s in systems],
        "adversaries": [a.id for a in DEFAULT_ADVERSARIES],
        "gate": report.gate_result.gate,
        "passed": report.gate_result.passed,
        "reasons": list(report.gate_result.reasons),
        "inputs_hash": report.gate_result.inputs_hash,
        "diff_count": len(report.diffs),
        "leakage_count": len(report.leakage_failures),
        "note": "first-pitch guard (bug #2) enforced: t = min(latest "
                "capture, commence_time - margin) per game, in-play games "
                "skipped. Earlier gate_results.jsonl rows for this same "
                "date/sample_size predate this guard and were computed "
                "in-play (t = latest capture with no commence_time check) "
                "-- they are left as-is, not rewritten, and should not be "
                "compared against this row as if they measured the same "
                "thing.",
    }
    out_path = processed_path("gate_results.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import json as json_module
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json_module.dumps(record, sort_keys=True) + "\n")
    print(f"\n  G4 gate record appended to {out_path}")

    return EXIT_OK if report.gate_result.passed else EXIT_ERROR


def _record_from_row(cls, row):
    """Reconstruct a frozen ledger dataclass from a JSON-decoded row,
    dropping any key the dataclass does not declare (e.g. a genesis row's
    `kind`, or a chain's own `prev_hash`/`row_hash` where the type has no
    such field)."""
    import dataclasses
    valid = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in row.items() if k in valid})


def cmd_eod(args) -> int:
    """`eod --date DATE`: build and write the end-of-day self-review from
    whatever stores exist (S7). No slate runner writes these stores yet
    (S5/S6, docs/CHECKPOINT_PHASE0_2026-09-03.md §5) -- this command reads
    them honestly, empty or not, and refuses rather than emitting an empty
    happy report when `DATE` has no recorded decisions.
    """
    from src.ledger.chain import HashChainLedger
    from src.ledger.records import AccountSummary, DecisionRecord, ReviewRecord, Scorecard
    from src.ledger.writer import REVIEW_LEDGER_PATH, SCORECARD_LEDGER_PATH
    from src.ledger.bridge import V2_LEDGER_PATH
    from src.paths import data_path
    from src.report import eod as eod_module

    date_str = args.date

    decision_rows = HashChainLedger(V2_LEDGER_PATH).read()
    decisions = [
        _record_from_row(DecisionRecord, row) for row in decision_rows
        if row.get("kind") != "genesis"
        and row.get("decision_utc", "").startswith(date_str)
    ]

    review_rows = HashChainLedger(str(REVIEW_LEDGER_PATH)).read()
    reviews = [
        _record_from_row(ReviewRecord,
                        dict(row, decision_key=tuple(row["decision_key"])))
        for row in review_rows
    ]

    scorecard_rows = HashChainLedger(str(SCORECARD_LEDGER_PATH)).read()
    scorecards = []
    for row in scorecard_rows:
        account = AccountSummary(**row["account"])
        scorecards.append(_record_from_row(Scorecard, dict(row, account=account)))

    accounts_dir = data_path("paper_accounts")
    accounts = []
    if accounts_dir.exists():
        for path in sorted(accounts_dir.glob("*.jsonl")):
            system_id = path.stem
            rows = HashChainLedger(path).read()
            accounts.append(eod_module.account_day_from_ledger_rows(
                system_id, rows, date_str))

    try:
        result = eod_module.write_review(date_str, accounts, decisions,
                                         reviews, scorecards)
    except eod_module.EodReviewError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    review = result["review"]
    print(f"eod --date {date_str}")
    print(f"  decisions           : {review.n_decisions} "
          f"({len(review.decisions_made)} play)")
    print(f"  vetoes              : {sum(v.count for v in review.vetoes)}")
    print(f"  settlements         : {len(review.settlements)} "
          f"({len(review.losing_settlements)} losses)")
    print(f"  price-vs-close      : {len(review.price_vs_close)} of "
          f"{review.n_reviewed} reviewed")
    print(f"  accounts            : {len(review.accounts)}")
    print(f"  report              : {result['path']}")
    return EXIT_OK


def cmd_calibration_demo(args) -> int:
    """Show the calibration metrics working on synthetic data.

    Included so the instruments can be inspected before there is a real model
    to measure -- the point being that they are built and verified first.
    """
    n = 1000
    # A well-calibrated predictor: says 0.6, wins 60% of the time.
    good = [0.6] * n
    outcomes = [1] * int(n * 0.6) + [0] * (n - int(n * 0.6))
    # An overconfident one: says 0.9 on the same games.
    overconfident = [0.9] * n

    print("calibration metrics -- synthetic demonstration\n")
    for label, preds in (("well-calibrated (says 0.60)", good),
                         ("overconfident (says 0.90)", overconfident)):
        scores = calibration.score_all(preds, outcomes)
        print(f"  {label}")
        print(f"    brier    {scores['brier']:.4f}")
        print(f"    log loss {scores['log_loss']:.4f}")
        print(f"    ECE      {scores['ece']:.4f}")
        print()

    print("  The overconfident model is WRONG in exactly the way that")
    print("  manufactures phantom edge: it would find value everywhere and")
    print("  bet into prices that are actually fair.\n")

    comparison = calibration.compare(good, [0.5] * n, outcomes)
    print(f"  model beats market : {comparison['model_beats_market']}")
    print(f"  log loss delta     : {comparison['log_loss_delta']:+.4f}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="MLB betting analysis -- free-data alpha",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="configuration and source availability")
    sub.add_parser("credits", help="odds API credit cost estimate")
    sub.add_parser("calibration-demo", help="show calibration metrics working")

    slate_cmd = sub.add_parser("slate", help="build a slate for one date")
    slate_cmd.add_argument("date", help="YYYY-MM-DD")
    slate_cmd.add_argument("--no-weather", action="store_true")
    slate_cmd.add_argument("--no-odds", action="store_true")

    results_cmd = sub.add_parser("results", help="results for one date")
    results_cmd.add_argument("date", help="YYYY-MM-DD")

    ingest_cmd = sub.add_parser("ingest", help="ingest results into the historical store")
    ingest_cmd.add_argument("start", help="YYYY-MM-DD")
    ingest_cmd.add_argument("end", help="YYYY-MM-DD")
    ingest_cmd.add_argument("--no-resume", dest="resume", action="store_false",
                            help="re-fetch dates already ingested")
    ingest_cmd.add_argument("--verbose", "-v", action="store_true")
    ingest_cmd.set_defaults(resume=True)

    boxscores_cmd = sub.add_parser(
        "boxscores", help="fetch per-game, per-player box lines (props "
                          "settlement substrate)")
    boxscores_cmd.add_argument("--date", default=None,
                               help="YYYY-MM-DD (defaults to today, UTC)")
    boxscores_cmd.add_argument("--backfill", default=None,
                               help="START..END, e.g. 2023-03-30..2023-11-01 "
                                    "(resumable; ignores --date)")

    sub.add_parser("history", help="coverage and integrity of the historical store")

    features_cmd = sub.add_parser("features",
                                  help="build the point-in-time training table")
    features_cmd.add_argument("--start", default=None, help="YYYY-MM-DD")
    features_cmd.add_argument("--end", default=None, help="YYYY-MM-DD")
    features_cmd.add_argument("--include-thin", action="store_true",
                              help="keep rows whose samples are too small for rates")

    train_cmd = sub.add_parser("train", help="fit and evaluate the probability model")
    train_cmd.add_argument("--missing", default="drop_columns",
                           choices=["drop_columns", "drop_rows"])
    train_cmd.add_argument("--test", action="store_true",
                           help="evaluate on the held-out TEST split (use once)")

    ledger_cmd = sub.add_parser("ledger",
        help="settle forward-ledger entries against results")
    ledger_cmd.add_argument("--status", action="store_true",
                            help="report what the ledger holds without settling")
    ledger_cmd.add_argument("action", nargs="?", choices=["verify"],
                            help="'verify': check the v1 ledger is untouched "
                                 "and the v2 hash chain is intact, then exit "
                                 "(does not settle anything)")

    sub.add_parser("closing-audit",
        help="read-only: per-market closing coverage (h2h, spreads, "
             "totals, first_five) over every settled game, backfill-aware "
             "(does not rewrite any ledger row)")

    backfill_cmd = sub.add_parser("closing-backfill",
        help="append closing_backfill rows for null-closing settlements "
             "now derivable from the snapshot store (never rewrites a "
             "ledger row; see closing-audit to preview without appending)")
    backfill_cmd.add_argument("--dry-run", action="store_true",
        help="list what would be appended without writing anything")
    backfill_cmd.add_argument("--market", choices=["h2h", "spreads", "totals", "all"],
        default="h2h",
        help="which market's close to backfill (default h2h, preserving "
             "pre-L18 behaviour); 'all' runs h2h, spreads, and totals in "
             "one pass. first_five is not offered here -- see closing-audit")

    brief_cmd = sub.add_parser("brief",
        help="build the slate briefing dashboard (static HTML, no server)")
    brief_cmd.add_argument("--date",
                           default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    brief_cmd.add_argument("--out", default="artifacts/briefing.html")
    brief_cmd.add_argument("--no-odds", action="store_true",
                           help="skip the odds call")
    brief_cmd.add_argument("--no-ledger", action="store_true",
                           help="do not append to the forward ledger")
    brief_cmd.add_argument("--no-weather", action="store_true",
                           help="skip the weather call")
    brief_cmd.add_argument("--no-matchups", action="store_true",
                           help="skip batter-vs-pitcher history (many calls)")
    brief_cmd.add_argument("--no-news", action="store_true",
                           help="skip the roster news and injured-list feed")
    brief_cmd.add_argument("--f5", action="store_true",
                           help="also price first-five per game (20 credits each) "
                                "-- enables the implied-bullpen detector")

    archive_cmd = sub.add_parser("archive",
        help="index every briefing artifact on disk (static HTML, no server)")
    archive_cmd.add_argument("--dir", default="artifacts",
                             help="directory of briefing artifacts to index")
    archive_cmd.add_argument("--out", default="artifacts/archive.html")

    analyze_cmd = sub.add_parser("analyze",
        help="analyse one arbitrary matchup -- historical or hypothetical")
    analyze_cmd.add_argument("--away", required=True,
                             help="away team abbreviation, e.g. CIN")
    analyze_cmd.add_argument("--home", required=True,
                             help="home team abbreviation, e.g. NYM")
    analyze_cmd.add_argument("--date", default=None,
                             help="YYYY-MM-DD information cutoff "
                                  "(defaults to today, UTC)")
    analyze_cmd.add_argument("--out", default=None,
                             help="output HTML path (defaults to "
                                  "artifacts/analyze_<away>_<home>_<date>.html)")

    scan_cmd = sub.add_parser("scan",
        help="scan a slate for obvious mismatches (usually: no play)")
    scan_cmd.add_argument("--date",
                          default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                          help="date to scan, YYYY-MM-DD")
    scan_cmd.add_argument("--verbose", action="store_true",
                          help="show why each game did or did not clear the bar")
    scan_cmd.add_argument("--no-log", action="store_true",
                          help="do not append flags to the immutable log")
    scan_cmd.add_argument("--no-price", action="store_true",
                          help="stop after the free talent stage; do not buy prices "
                               "for candidates")

    scan_grade_cmd = sub.add_parser("scan-grade",
        help="settle logged mismatch flags against first-five results")
    scan_grade_cmd.add_argument("--verbose", action="store_true",
                                help="list every settled flag")

    predict_cmd = sub.add_parser("predict",
                                 help="predict a slate and compare to the market")
    predict_cmd.add_argument("date", help="YYYY-MM-DD")
    predict_cmd.add_argument("--log", action="store_true",
                             help="append predictions to the immutable log")

    sub.add_parser("grade", help="settle logged predictions and report CLV")

    sub.add_parser("mybets-closing-backfill",
                   help="fill closing-price fields on already-settled My "
                        "Bets rows that predate the feature (one-time "
                        "catch-up; new settlements compute it automatically)")

    daily_cmd = sub.add_parser("daily", help="run the full daily loop")
    daily_cmd.add_argument("--date", default=None,
                           help="YYYY-MM-DD (defaults to today, UTC)")

    sub.add_parser("snapshot", help="capture one odds observation (run on a schedule)")
    dense_parser = sub.add_parser(
        "dense", help="spaced snapshots while games approach (hourly schedule)")
    dense_parser.add_argument("--captures", type=int, default=4,
                              help="captures in this run (default 4)")
    dense_parser.add_argument("--interval", type=int, default=15,
                              help="minutes between captures (default 15)")
    dense_parser.add_argument("--window", type=int, default=180,
                              help="minutes before first pitch to stay active (default 180)")
    dense_parser.add_argument("--estimate", action="store_true",
                              help="print the credit cost and exit without spending")

    movement_cmd = sub.add_parser("movement", help="show captured line movement")
    movement_cmd.add_argument("--market", default="h2h",
                              choices=["h2h", "spreads", "totals"])

    watch_cmd = sub.add_parser(
        "watch", help="poll probables/lineups/transactions for event timing "
                      "(free MLB endpoints; run every 10-15 minutes)")
    watch_cmd.add_argument("--date", default=None,
                          help="YYYY-MM-DD (defaults to today, UTC)")
    watch_cmd.add_argument("--events", action="store_true",
                          help="print derived graded events as JSONL "
                               "instead of polling")

    events_cmd = sub.add_parser(
        "events", help="project InformationEvents from the free-environment "
                       "watch/processed stores (packet W6; no network calls)")
    events_cmd.add_argument("--since", default=None, metavar="DATE",
                           help="only project rows observed on/after this "
                                "YYYY-MM-DD (UTC)")

    timing_cmd = sub.add_parser(
        "timing", help="V3 event accumulation status; tables "
                       "appear only past the 30-event class floor")
    timing_cmd.add_argument(
        "--test", action="store_true",
        help="run the pre-registered primary test (src/research/timingtest.py) "
             "for every class at/above the measurable-event floor; classes "
             "below it print 'below floor' and are never read")

    budget_cmd = sub.add_parser(
        "budget", help="credit envelope status (allotment, reset, spend, "
                       "per-family measured cost, drop order)")
    budget_cmd.add_argument(
        "--probe", default=None, metavar="FAMILY",
        help="perform exactly ONE 1-credit measured probe of FAMILY (real "
             "API call; only runs when explicitly invoked)")

    cadence_cmd = sub.add_parser(
        "cadence", help="cadence SLO from the stores' own poll timestamps "
                        "(attempted/succeeded/longest gap/p95 gap per day)")
    cadence_cmd.add_argument("--date", default=None,
                             help="YYYY-MM-DD (defaults to today, UTC)")

    health_cmd = sub.add_parser("health", help="slate data-quality health "
                                               "report (read-only; non-zero "
                                               "exit on anomalies)")
    health_cmd.add_argument("--date", default=None,
                            help="YYYY-MM-DD (defaults to today, UTC)")

    l1_cmd = sub.add_parser(
        "l1", help="backfill data/processed/l1_observations.jsonl "
                   "(PriceObservation rows) from every price store")
    l1_cmd.add_argument("--backfill", action="store_true",
                        help="project every row in every store (default "
                             "behavior; flag exists for explicitness)")
    l1_cmd.add_argument("--since", default=None, metavar="DATE",
                        help="only project rows observed on/after this "
                             "YYYY-MM-DD (UTC official date)")

    gamekey_cmd = sub.add_parser(
        "gamekey", help="build/refresh data/processed/event_game_map.jsonl "
                        "(event_id -> game_pk, S1)")
    gamekey_cmd.add_argument("--date", required=True, metavar="DATE",
                             help="YYYY-MM-DD (or the start of a range "
                                  "with --end)")
    gamekey_cmd.add_argument("--end", default=None, metavar="DATE",
                             help="YYYY-MM-DD, inclusive end of the range "
                                  "(defaults to --date, i.e. a single day)")
    gamekey_cmd.add_argument("--force", action="store_true",
                             help="re-resolve events already in the map "
                                  "instead of skipping them")

    statcast_cmd = sub.add_parser(
        "statcast", help="pitch-level Statcast store maintenance "
                         "(data/historical/statcast/)")
    statcast_cmd.add_argument("--catchup", action="store_true",
                              help="extend the store from the manifest's "
                                   "last covered date through --through "
                                   "(default: yesterday, UTC)")
    statcast_cmd.add_argument("--through", default=None, metavar="DATE",
                              help="YYYY-MM-DD, inclusive (default: "
                                   "yesterday, UTC)")

    engine_cmd = sub.add_parser(
        "engine", help="engine conformance and truncation-differential checks")
    engine_sub = engine_cmd.add_subparsers(dest="engine_command", required=True)

    engine_conform = engine_sub.add_parser(
        "conform", help="run the conformance suite against a system")
    engine_conform.add_argument(
        "system", metavar="SYSTEM",
        help="'module.path:attr' -- an AnalysisSystem instance, or a "
             "zero-argument callable that returns one")

    engine_truncation = engine_sub.add_parser(
        "truncation", help="run the truncation-differential leakage gate (G4)")
    engine_truncation.add_argument("--date", required=True, help="YYYY-MM-DD")
    engine_truncation.add_argument("--sample", type=int, default=10,
                                   help="number of games to sample")
    engine_truncation.add_argument(
        "--t-offset", type=int, default=120, dest="t_offset", metavar="MINUTES",
        help="minutes between t-2h and t (default 120, i.e. a true 2h "
             "window; the flag exists so other windows can be registered "
             "without renaming the concept)")

    engine_slate = engine_sub.add_parser(
        "slate", help="S5: analyze a date's slate through the registered "
                      "systems and place FLAT_1U paper wagers")
    engine_slate.add_argument("--date", required=True, help="YYYY-MM-DD")
    engine_slate.add_argument(
        "--asof", default=None, metavar="ISO8601",
        help="use this exact decision instant for every game instead of "
             "each game's own latest-capture-before-first-pitch default "
             "(still refused per-game if at/after commence_time)")
    engine_slate.add_argument(
        "--systems", default=None, metavar="a,b,c",
        help="comma-separated registered system ids to run (default: all "
             "of src.engine.adapters.evolab_system.REGISTERED_SYSTEMS)")
    engine_slate.add_argument(
        "--dry-run", action="store_true",
        help="run the full pipeline and print what WOULD be written, "
             "without writing any decision or wager")

    engine_settle = engine_sub.add_parser(
        "settle", help="S6a: settle a date's paper wagers from real "
                      "results and append Scorecards")
    engine_settle.add_argument("--date", required=True, help="YYYY-MM-DD")

    engine_replay_one = engine_sub.add_parser(
        "replay-one", help="S3 demonstration: one 2023-24 replay decision "
                           "through analyze(), settled against the known "
                           "historical result")
    engine_replay_one.add_argument("--season", type=int, required=True)
    engine_replay_one.add_argument("--game-pk", required=True, dest="game_pk")
    engine_replay_one.add_argument(
        "--point-class", default=None, choices=["EARLY_BOARD", "LATE_BOARD"])
    engine_replay_one.add_argument(
        "--system", default=None, metavar="SYSTEM_ID",
        help="registered system id (default: the trivial control)")
    engine_replay_one.add_argument(
        "--adversaries", action="store_true",
        help="run the registered DEFAULT_ADVERSARIES roster instead of none")

    eod_cmd = sub.add_parser(
        "eod", help="build and write the end-of-day self-review (S7)")
    eod_cmd.add_argument("--date", required=True, help="YYYY-MM-DD")

    return parser


COMMANDS = {
    "status": cmd_status,
    "credits": cmd_credits,
    "slate": cmd_slate,
    "results": cmd_results,
    "ingest": cmd_ingest,
    "boxscores": cmd_boxscores,
    "history": cmd_history,
    "features": cmd_features,
    "train": cmd_train,
    "brief": cmd_brief,
    "analyze": cmd_analyze,
    "archive": cmd_archive,
    "ledger": cmd_ledger,
    "closing-audit": cmd_closing_audit,
    "closing-backfill": cmd_closing_backfill,
    "scan": cmd_scan,
    "scan-grade": cmd_scan_grade,
    "predict": cmd_predict,
    "grade": cmd_grade,
    "mybets-closing-backfill": cmd_mybets_closing_backfill,
    "daily": cmd_daily,
    "health": cmd_health,
    "snapshot": cmd_snapshot,
    "dense": cmd_dense,
    "movement": cmd_movement,
    "watch": cmd_watch,
    "events": cmd_events,
    "timing": cmd_timing,
    "calibration-demo": cmd_calibration_demo,
    "budget": cmd_budget,
    "cadence": cmd_cadence,
    "l1": cmd_l1,
    "gamekey": cmd_gamekey,
    "statcast": cmd_statcast,
    "engine": cmd_engine,
    "eod": cmd_eod,
}


def main(argv=None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
