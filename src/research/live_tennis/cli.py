"""`python -m src.cli research live-tennis capture | grade | report` (docs/PREREG_LIVE_TENNIS.md section 13).

    capture   one tick (default, exactly one iteration of the loop) or `--loop [--max-minutes N]`. OFF unless
              LIVE_TENNIS_TEST=on: with the switch off it makes no request, spends no credit and writes no row.
              `--plan` prints the switch, the caps, today's and this month's spend and the ledger counts, and
              makes no request at all.
    grade     writes references from stored boards and outcomes from the free ESPN scoreboard. No credit. `--dry-run`
              writes nothing.
    report    counts, coverage and credits always; effect statistics only past the pre-registered floors.
              `--json` prints the report as JSON; `--record-verdict` appends the verdict to the alpha registry once,
              for a final state only.

Paper only. Nothing here can place a bet.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

EXIT_OK, EXIT_ERROR = 0, 2


def add_parser(sub) -> None:
    research = sub.add_parser("research", help="research instruments (paper tests; never a customer surface)")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    live = research_sub.add_parser(
        "live-tennis", help="LIVE_TENNIS_V1 paper test: a Markov model vs the live tennis match-winner board "
                            "(docs/PREREG_LIVE_TENNIS.md); OFF unless LIVE_TENNIS_TEST=on")
    live_sub = live.add_subparsers(dest="live_tennis_command", required=True)
    tc = research_sub.add_parser(
        "tennis-comeback", help="history table: how often a favourite who loses set 1 still wins (tennis-data.co.uk files)")
    tc_sub = tc.add_subparsers(dest="tennis_comeback_command", required=True)
    tcb = tc_sub.add_parser("build", help="read data/research/tennis_history/raw/ and write the evidence JSON + doc")
    tcb.add_argument("--raw-dir", dest="raw_dir", default=None, help="override the raw files folder")

    tl = research_sub.add_parser(
        "tennis-live-cal", help="in-play calibration of tennis favourites from historical odds snapshots "
                                "(the paid pull is gated by TENNIS_CAL_PULL=on)")
    tl_sub = tl.add_subparsers(dest="tennis_live_cal_command", required=True)
    for name, text in (("plan", "print the snapshot schedule and credit cost; no requests"),
                       ("pull", "fetch and cache the planned snapshots (needs TENNIS_CAL_PULL=on; resumable)"),
                       ("build", "build the evidence JSON and doc from cached snapshots (no requests)")):
        tlp = tl_sub.add_parser(name, help=text)
        tlp.add_argument("--plan", dest="cal_plan", choices=("v1", "v2"), default="v1",
                         help="v1 (default, frozen) or v2 (early rounds, 15-minute cadence, separate cache)")

    capture = live_sub.add_parser("capture", help="one capture tick (or --loop); spends credits only when the switch is on")
    capture.add_argument("--loop", action="store_true", help="keep ticking until --max-minutes or the stop date")
    capture.add_argument("--max-minutes", dest="max_minutes", type=float, default=None,
                         help="with --loop, stop after this many minutes (default: run until stopped)")
    capture.add_argument("--plan", action="store_true",
                         help="print the switch, caps, spend and ledger counts; make no request, spend nothing")

    grade = live_sub.add_parser("grade", help="write references and outcomes (free: stored boards and ESPN)")
    grade.add_argument("--dry-run", dest="dry_run", action="store_true", help="count what would be written, write nothing")

    report = live_sub.add_parser("report", help="counts always; effect statistics only past the pre-registered floors")
    report.add_argument("--json", action="store_true", help="print the report as JSON")
    report.add_argument("--record-verdict", dest="record_verdict", action="store_true",
                        help="append the verdict to the alpha registry (once, final states only)")


def _line(report: dict) -> str:
    if report.get("off"):
        return "live tennis test is OFF (LIVE_TENNIS_TEST is not on): nothing requested, nothing spent, nothing written"
    if report.get("stopped"):
        return "stopped: " + "; ".join(report.get("errors") or ["past the stop date"])
    spent = sum(c["credits"] for c in report["calls"])
    return (f"{report['utc']} paired {report['paired']} armed {report['armed']} decisions {report['decisions']} "
            f"references {report['references']} calls {len(report['calls'])} credits {spent} "
            f"refused {len(report['refused'])} errors {len(report['errors'])}")


def _plan() -> int:
    from src.research.live_tennis import config, guard
    from src.research.live_tennis.ledger import PaperLedger

    now = datetime.now(timezone.utc)
    rows = guard.read_rows()
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    ledger = PaperLedger()
    from src.providers import odds

    print(f"switch {config.ENV_SWITCH}: {'ON' if config.switch_on() else 'OFF (default)'}")
    print(f"odds API key configured: {'yes' if odds.is_configured() else 'NO (set ODDS_API_KEY in .env or the environment)'}")
    print(f"caps: {config.DAILY_CREDIT_CAP}/day ({config.PREMATCH_DAILY_SUBCAP} pre-match), "
          f"{config.MONTHLY_CREDIT_CAP}/month, stop date {config.STOP_DATE}")
    print(f"spent today {guard.spent(rows, day=day, caller_prefix=config.CREDIT_CALLER)}, "
          f"this month {guard.spent(rows, month=month, caller_prefix=config.CREDIT_CALLER)}")
    print(f"ledger {ledger.path}: {len(ledger.rows())} rows; constants fingerprint {config.fingerprint()[:16]}")
    print("plan only: no request was made")
    return EXIT_OK


def main(args) -> int:
    if getattr(args, "research_command", None) == "tennis-comeback":
        from pathlib import Path

        from src.research import tennis_comeback as tc

        res = tc.build(raw_dir=Path(args.raw_dir) if args.raw_dir else tc.RAW_DIR)
        print(f"tennis-comeback: status {res['status']}, matches kept {res['matches_kept']}, "
              f"cells {len(res['cells'])}, problems {len(res['data_problems'])}")
        return EXIT_OK if res["status"] == "ok" else EXIT_ERROR
    if getattr(args, "research_command", None) == "tennis-live-cal":
        from src.research import live_tennis_calibration as cal

        return cal.main(args.tennis_live_cal_command, plan=getattr(args, "cal_plan", "v1"))
    command = args.live_tennis_command
    if command == "capture":
        from src.research.live_tennis import config

        if args.plan:
            return _plan()
        if not config.switch_on():
            print(_line({"off": True}))
            return EXIT_OK
        from src.providers import odds
        from src.research.live_tennis.runner import Runner

        if not odds.is_configured():
            print("the switch is on but ODDS_API_KEY is not configured (set it in .env or the environment): "
                  "nothing requested, nothing spent", file=sys.stderr)
            return EXIT_ERROR
        runner = Runner()
        if args.loop:
            runner.run_loop(max_minutes=args.max_minutes, on_tick=lambda rep: print(_line(rep), flush=True))
            return EXIT_OK
        print(_line(runner.tick()))
        return EXIT_OK

    if command == "grade":
        from src.providers import espn_tennis_results as espn
        from src.research.live_tennis import grade
        from src.research.live_tennis.ledger import PaperLedger, SnapshotStore

        ledger = PaperLedger()
        if not ledger.path.exists():
            print("no ledger yet: nothing to grade (no decision point has been captured)")
            return EXIT_OK
        now = datetime.now(timezone.utc)
        refs = grade.resolve_references(ledger, SnapshotStore(), now, write=not args.dry_run)
        outs = grade.settle(ledger, espn_json=espn.default_get_json, now=now, write=not args.dry_run)
        verb = "would write" if args.dry_run else "wrote"
        print(f"{verb} {refs['references']} reference(s), {refs['no_reference']} no_reference; {len(refs['pending'])} still pending")
        print(f"{verb} {outs['outcomes']} outcome(s); pending {outs['pending']}, unresolved {outs['unresolved']}, "
              f"not found {outs['not_found']}, errors {outs['errors']}")
        return EXIT_OK

    if command == "report":
        from src.research.live_tennis import report as report_mod

        built = report_mod.build()
        if args.json:
            print(json.dumps(built, indent=2, sort_keys=True, default=str))
        else:
            print(report_mod.render(built))
        if args.record_verdict:
            try:
                row = report_mod.record_verdict(built)
            except ValueError as exc:
                print(f"not recorded: {exc}", file=sys.stderr)
                return EXIT_ERROR
            print(f"recorded verdict {row['result']} for {row['id']}")
        return EXIT_OK

    print(f"unknown live-tennis command {command!r}", file=sys.stderr)
    return EXIT_ERROR
