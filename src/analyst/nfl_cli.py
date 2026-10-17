"""`python -m src.cli analyst pilot|grade|record --sport nfl`.

    pilot prepare   build the NFL packet and the exact request for one game (nfl_pilot.prepare)
    pilot check     the NFL checker over a response, recorded as an attempt (nfl_pilot.check)
    pilot publish   freeze it into evidence/analyst_pilot_nfl_v1.jsonl (nfl_pilot.publish)
    grade           grade a date's published NFL briefs from the NFL data store's final scores
    record          the NFL pilot's record by market family, its cost, and its ledger's integrity

There is no `run --sport nfl`: the NFL analyst has no API path. It exists only as the
supervised-session pilot (docs/AI_ANALYST.md, "The NFL brief"), so the briefs are written by a
Claude session from the exact request the API would send and published by the same pipeline.

`grade` and `record` read and write only the NFL pilot's stores. The MLB analyst's, the MLB pilot's
and the UFC analyst's records are different files and are never added to this one.

The scores come from the NFL data store (`data/datasvc/nfl/games.jsonl`), which the owner's
`python -m src.datasvc.cli nfl update` refreshes. This module fetches nothing: a finished game the
store has not been updated for grades UNRESOLVED, and `grade` says "no new result yet".

EXIT CODES: 0 ok, 2 error.
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional

from src.analyst import PILOT_LABEL, cli, ledger, nfl_grading, nfl_pilot
from src.analyst import config as config_mod

EXIT_OK, EXIT_ERROR = cli.EXIT_OK, cli.EXIT_ERROR


def execute_grade(date: str, *, store=None, now: Optional[Callable] = None, out: Callable = print,
                  store_path: Optional[str] = None) -> int:
    """Grade a date's published NFL briefs. Idempotent: a second run appends nothing."""
    store = store if store is not None else nfl_pilot.default_store()
    path = store_path or nfl_pilot.store_paths()["store"]
    counts = ledger.grade_date(date, nfl_grading.results_for(store, date), [], now=(now or cli._now)(),
                               path=path, grade_game=nfl_grading.grade_game)
    out(f"analyst grade {date} [nfl pilot]: published={counts['published']} graded={counts['graded']} "
        f"complete={counts['complete']} unchanged={counts['unchanged']}")
    for note in counts["notes"]:
        out(f"  {note}")
    return EXIT_OK


def _print_record(rec: Mapping, out: Callable) -> None:
    out(PILOT_LABEL)
    out(f"games published {rec['games_published']}, settled {rec['games_settled']}")
    for name, f in rec["families"].items():
        rate = "withheld" if f["win_rate"] is None else f"{f['win_rate'] * 100:.1f}%"
        out(f"  {name:11s} taken {f['taken']} (other side {f['taken_other_side']}), "
            f"passes {f['passes']}, graded {f['graded']} "
            f"(W{f['wins']} L{f['losses']} P{f['pushes']} V{f['voids']}), "
            f"unresolved {f['unresolved']}, win rate {rate}")


def execute_record(*, out: Callable = print, store_path: Optional[str] = None,
                   usage_path: Optional[str] = None, cfg: Optional[Mapping] = None) -> int:
    """The NFL pilot's record, its cost per day and its ledger's integrity."""
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    files = nfl_pilot.store_paths()
    store_path = store_path or files["store"]
    usage_path = usage_path or files["usage"]
    out("NFL SUPERVISED-SESSION BRIEFS (their own record; never added to the MLB or UFC records)")
    rec = ledger.record(path=store_path, min_graded=cfg["min_graded_for_rates"],
                        families=nfl_grading.FAMILIES)
    _print_record(rec, out)
    check = ledger.verify(store_path)
    out(f"nfl pilot ledger: {'OK' if check['ok'] else 'PROBLEM'} ({check['rows']} rows)")
    for problem in check["problems"]:
        out(f"  {problem}")
    usage = ledger.usage_by_day(usage_path)
    if usage:
        out("cost per day (estimates at list price from the tokens the operator reported):")
        for day in sorted(usage):
            u = usage[day]
            out(f"  {day}: {u['published']}/{u['games']} games published, "
                f"{u['input_tokens']} in / {u['output_tokens']} out tokens, ${u['cost_usd']:.2f}")
    return EXIT_OK if check["ok"] else EXIT_ERROR


def main(args) -> int:
    """Dispatch for `src.analyst.cli.main` when `--sport nfl`."""
    if args.analyst_command == "pilot":
        if args.pilot_command == "prepare":
            return nfl_pilot.prepare(args.date, args.game, scratch=args.scratch)
        if args.pilot_command == "check":
            return nfl_pilot.check(args.dir, args.response)
        return nfl_pilot.publish(args.dir, args.response, model=args.model, tokens_in=args.tokens_in,
                                 tokens_out=args.tokens_out, seconds=args.seconds,
                                 operator_minutes=args.operator_minutes, refresh=args.refresh)
    if args.analyst_command == "grade":
        return execute_grade(args.date)
    if args.analyst_command == "record":
        return execute_record()
    print("the NFL analyst has no `run`: it is the supervised-session pilot "
          "(python -m src.cli analyst pilot prepare --sport nfl ...)")
    return EXIT_ERROR
