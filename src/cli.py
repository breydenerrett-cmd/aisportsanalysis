"""Command line entry point.

Run with:  python -m src.cli <command> [args]

Every command fails safe. Missing configuration reports what to do and exits
non-zero; it never crashes with a stack trace and never prints a key.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.core import calibration
from src.data import parks
from src.paths import processed_path, raw_path
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
    return EXIT_OK


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
    print(f"  dates still unresolved: {report['dates_with_unresolved_games']}")
    print(f"  home win rate         : {report['home_win_rate']}")

    if report["gap_count"]:
        print(f"\n  WARNING: {report['gap_count']} date(s) inside the span were never "
              "fetched.")
        print("  These are holes, not off days. Re-run ingest to fill them:")
        for day in report["unfetched_gaps_in_span"][:10]:
            print(f"    {day}")
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


def cmd_scan(args) -> int:
    """Scan a slate for obvious mismatches. Most days the answer is no play."""
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
        print("  (no pitcher logs -- starter signal unavailable; "
              "run `pitchers` first)")
        logs = None

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

    prepared = mismatch.build_scan_inputs(store, games, pitcher_logs=logs,
                                          odds_by_matchup=prices)
    result = mismatch.scan_slate(prepared)

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

    if result["flagged"] and args.price_first_five:
        _price_flagged_first_five(result["flagged"], args.date)

    if result["flagged"]:
        print("\n  These are candidates to look at, not recommendations. The "
              "thresholds are pre-registered guesses that have never been "
              "validated against a result.")
    return EXIT_OK


def _price_flagged_first_five(flagged, game_date) -> None:
    """Fetch first-five prices for flagged games only.

    Deliberately restricted to flagged games. The per-event endpoint bills per game,
    so pricing a whole slate's first five costs sixteen times what pricing two flagged
    games costs, and would exhaust a free month in under two days. This is where the
    scanner's silence pays for itself.
    """
    from src.pipeline import slate as slate_mod
    from src.providers import odds as odds_prov

    if not odds_prov.is_configured():
        print(f"\n  (first-five pricing skipped: {odds_prov.status()['message']})")
        return

    try:
        events = odds_prov.list_events()
    except odds_prov.OddsProviderError as exc:
        print(f"\n  (first-five pricing unavailable: {exc})")
        return

    by_matchup = {}
    for event in events:
        away = slate_mod.team_abbrev_from_name(event.get("away_team"))
        home = slate_mod.team_abbrev_from_name(event.get("home_team"))
        if away and home:
            by_matchup[(away, home)] = event.get("id")

    wanted = ["h2h_1st_5_innings", "totals_1st_5_innings"]
    cost = odds_prov.estimate_event_credits(len(flagged), markets=wanted)
    print(f"\n  first-five prices ({cost['credits_total']} credits for "
          f"{len(flagged)} game(s), {cost['credits_per_event']} each):")

    for scan in flagged:
        key = (scan["away_team"], scan["home_team"])
        event_id = by_matchup.get(key)
        if not event_id:
            # Named rather than skipped. A missing event is usually a team-code
            # mismatch between the two feeds, which has silently cost this project
            # data twice before.
            print(f"    {scan['away_team']} @ {scan['home_team']}: "
                  "no matching event in the odds feed")
            continue
        try:
            record = odds_prov.normalize_event(
                odds_prov.fetch_event_odds(event_id, markets=wanted))
        except odds_prov.OddsProviderError as exc:
            print(f"    {scan['away_team']} @ {scan['home_team']}: {exc}")
            continue

        ml = record["markets"].get("h2h_1st_5_innings")
        total = record["markets"].get("totals_1st_5_innings")
        print(f"    {scan['away_team']} @ {scan['home_team']}  (scan likes "
              f"{scan['side']})")
        if ml:
            print(f"      F5 moneyline [{ml['book']}]  away {ml['away_price']:+d}  "
                  f"home {ml['home_price']:+d}")
        else:
            print("      F5 moneyline: not offered")
        if total:
            print(f"      F5 total     [{total['book']}]  {total['total']}  "
                  f"over {total['over_price']:+d}  under {total['under_price']:+d}")
        else:
            print("      F5 total: not offered")


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


def cmd_daily(args) -> int:
    """The whole loop, in the order that keeps the evidence honest.

    Order matters and is not arbitrary:
      1. snapshot odds FIRST -- line movement cannot be backfilled, so a failure
         later in the run must not cost the observation.
      2. ingest yesterday's results, so grading has something to settle against.
      3. predict today and log, capturing the price at prediction time.
      4. grade whatever has settled.

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
        print(f"[{number}/4] {name}")
        try:
            fn()
        except Exception as exc:  # a step failing must not kill the loop
            failures.append((name, str(exc)))
            print(f"      FAILED: {exc}")
        print()

    # 1. Snapshot first. This is the only irreplaceable step.
    def do_snapshot():
        from src.pipeline import snapshots
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

    def do_predict():
        from src.pipeline import grading
        code = cmd_predict(argparse.Namespace(date=today, log=True))
        if code != EXIT_OK:
            raise RuntimeError("prediction step returned a non-zero exit")

    def do_grade():
        cmd_grade(argparse.Namespace())

    step(1, "capture odds snapshot (irreplaceable -- runs first)", do_snapshot)
    step(2, f"ingest results for {yesterday}", do_ingest)
    step(3, f"predict and log {today}", do_predict)
    step(4, "grade settled predictions", do_grade)

    if failures:
        print(f"loop finished with {len(failures)} failed step(s):")
        for name, error in failures:
            print(f"  {name}: {error}")
        return EXIT_ERROR
    print("loop finished cleanly.")
    return EXIT_OK


def cmd_snapshot(args) -> int:
    """Capture one odds observation. Meant to run on a schedule.

    Line movement cannot be backfilled from free sources, so this is the one job whose value
    depends entirely on having started early. Every run that does not happen is market data
    that can never be recovered.
    """
    from src.pipeline import snapshots

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

    scan_cmd = sub.add_parser("scan",
        help="scan a slate for obvious mismatches (usually: no play)")
    scan_cmd.add_argument("--date",
                          default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                          help="date to scan, YYYY-MM-DD")
    scan_cmd.add_argument("--verbose", action="store_true",
                          help="show why each game did or did not clear the bar")
    scan_cmd.add_argument("--price-first-five", action="store_true",
                          help="fetch first-five prices for flagged games only "
                               "(spends credits per flagged game)")

    predict_cmd = sub.add_parser("predict",
                                 help="predict a slate and compare to the market")
    predict_cmd.add_argument("date", help="YYYY-MM-DD")
    predict_cmd.add_argument("--log", action="store_true",
                             help="append predictions to the immutable log")

    sub.add_parser("grade", help="settle logged predictions and report CLV")

    daily_cmd = sub.add_parser("daily", help="run the full daily loop")
    daily_cmd.add_argument("--date", default=None,
                           help="YYYY-MM-DD (defaults to today, UTC)")

    sub.add_parser("snapshot", help="capture one odds observation (run on a schedule)")

    movement_cmd = sub.add_parser("movement", help="show captured line movement")
    movement_cmd.add_argument("--market", default="h2h",
                              choices=["h2h", "spreads", "totals"])

    return parser


COMMANDS = {
    "status": cmd_status,
    "credits": cmd_credits,
    "slate": cmd_slate,
    "results": cmd_results,
    "ingest": cmd_ingest,
    "history": cmd_history,
    "features": cmd_features,
    "train": cmd_train,
    "scan": cmd_scan,
    "predict": cmd_predict,
    "grade": cmd_grade,
    "daily": cmd_daily,
    "snapshot": cmd_snapshot,
    "movement": cmd_movement,
    "calibration-demo": cmd_calibration_demo,
}


def main(argv=None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
