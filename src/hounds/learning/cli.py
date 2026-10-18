"""python -m src.hounds.learning ... : the operator's door to the house scope of the learning loop.

    status                        the live challengers, the champion versions, the pause, the latest scorecard
    verify                        walk every hash chain of both scopes
    coach-scorecard --hound ID    a pack hound's scorecard for the coach (JSON): record, knobs with their
                                  bounds, live challengers, the hound's last 10 lessons and its category's
    propose --hound ID --params '{"GAP": 0.03}' --hypothesis "..." --evidence a,b
                                  the pack door: creates a CHALLENGER (never a change); every guard of
                                  docs/PREREG_LEARNING_LOOP.md section 3 applies except the signature
    shadow [--date D]             run the live challengers on the boards of D (default: today and tomorrow, ET)
    settle                        grade the challengers' bets with the champions' own settler
    referee                       examine looks, batch the finished months, promote or retire
    scorecard                     store today's system scorecard and apply the auto-pause rule
    tick                          shadow + settle + referee + scorecard, the one command a slot can run
    resume --reason "..."         the owner turns the coach back on after an auto-pause
    lessons [--hound ID]          the lessons, newest first
    director-pack --month YYYY-MM the monthly request file for a frontier model's review (never auto-applied)

Every command is read-only except the ones that name a ledger above, and none can place a bet; the
engines the shadow runner uses refuse a game that has started and any price at -200 or worse.
No command here makes a model call.

TESTING SEAMS: ``--root DIR`` points the house scope's three ledgers at DIR, ``--champion-ledger PATH`` the
pack ledger, ``--coach-config PATH`` the kill switch, ``--now ISO`` the clock.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

from src.hounds.learning import ledger as L
from src.hounds.learning import lessons, pause, proposals, rules, tunables, views


def _scope(args, name: str = rules.SCOPE_HOUSE) -> L.Scope:
    if name == rules.SCOPE_USER:
        return L.Scope.user(Path(args.user_dir) if getattr(args, "user_dir", None) else None)
    return L.Scope.house(Path(args.root) if args.root else None)


def _now(args) -> datetime:
    return L.parse(args.now) if args.now else L.utc_now()


def _champion_ledger(args) -> str:
    from src.hounds import pack_run
    return args.champion_ledger or pack_run.ledger_path()


def _out(obj) -> None:
    print(json.dumps(obj, indent=1, sort_keys=True, default=str))


def _coach_on(args) -> bool:
    cfg = Path(args.coach_config) if args.coach_config else pause.config_path()
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("enabled") is True


def _dates(args, now: datetime) -> list:
    if args.date:
        return [args.date]
    from src.pipeline import snapshots
    stamp = lambda m: m.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    return [snapshots.official_date(stamp(now)), snapshots.official_date(stamp(now + timedelta(days=1)))]


def _stores(dates: Sequence[str]):
    from src.hounds.pack import base
    since = max(base.SEAL_FLOOR, base.day_before(min(dates), 8))
    until = (date.fromisoformat(max(dates)) + timedelta(days=2)).isoformat()
    return base.load_stores(since=since, until=until)


# ---- commands --------------------------------------------------------------------------------------

def cmd_status(args) -> int:
    scope = _scope(args)
    st = L.read_state(scope)
    _out({"scope": scope.name,
          "paused": pause.is_paused(scope),
          "live_challengers": [c.to_json() for c in st.live()],
          "champion_versions": {h: st.champion_version(h) for h in sorted({p["hound_id"] for p in st.promotions})},
          "promotions": len(st.promotions), "refusals": len(st.refusals),
          "latest_scorecard": (st.latest_scorecard() or {}).get("date")})
    return 0


def cmd_verify(args) -> int:
    reports = {name: L.chain_report(_scope(args, name)) for name in (rules.SCOPE_HOUSE, rules.SCOPE_USER)}
    ok = all(r["ok"] for r in reports.values())
    _out({"ok": ok, **reports})
    return 0 if ok else 1


def cmd_coach_scorecard(args) -> int:
    from src.hounds import stats
    book = stats.get_book()
    card = views.pack_coach_scorecard(args.hound, book, scope_map={rules.SCOPE_HOUSE: _scope(args),
                                                                    rules.SCOPE_USER: _scope(args, "user")})
    if card is None:
        print(f"no such hound: {args.hound}", file=sys.stderr)
        return 2
    _out(card)
    return 0


def cmd_propose(args) -> int:
    scope = _scope(args)
    try:
        params = json.loads(args.params)
    except ValueError:
        print("--params must be a JSON object, e.g. '{\"GAP\": 0.03}'", file=sys.stderr)
        return 2
    evidence = [e.strip() for e in (args.evidence or "").split(",") if e.strip()]
    state = L.read_state(scope)
    graded = proposals.pack_graded_count(args.hound, state.champion_version(args.hound), _champion_ledger(args))
    try:
        c = proposals.propose_pack(scope, args.hound, params, args.hypothesis, evidence, graded=graded,
                                   coach_on=_coach_on(args), now=_now(args), proposed_by=args.proposed_by)
    except proposals.ProposalError as exc:
        _out({"accepted": False, "code": exc.code, "message": str(exc)})
        return 1
    _out({"accepted": True, "challenger": c.to_json()})
    return 0


def cmd_shadow(args) -> int:
    from src.hounds.learning import shadow
    now = _now(args)
    dates = _dates(args, now)
    scope = _scope(args)
    if not shadow.pack_hounds(L.read_state(scope)):
        _out({"challengers": 0, "written": 0})
        return 0
    _out(shadow.run_pack(_stores(dates), dates, scope, now=now))
    return 0


def cmd_settle(args) -> int:
    from src.hounds.learning import shadow
    from src.ledger.chain import HashChainLedger
    scope = _scope(args)
    rows = [r for r in HashChainLedger(scope.challenger_bets).read() if r.get("kind") == "hound_bet"]
    if not rows:
        _out({"graded": 0, "pending": 0})
        return 0
    first, last = min(r["date"] for r in rows), max(r["date"] for r in rows)
    _out(shadow.settle_pack(_stores([first, last]), scope, now=_now(args)))
    return 0


def cmd_referee(args) -> int:
    from src.hounds.learning import runner
    _out(runner.run_referee(_scope(args), now=_now(args), champion_ledger=_champion_ledger(args),
                            kinds=("pack",)))
    return 0


def cmd_scorecard(args) -> int:
    from src.hounds import stats
    from src.hounds.learning import runner
    _out(runner.run_scorecard(_scope(args), now=_now(args), book=stats.get_book(),
                              champion_ledger=_champion_ledger(args)))
    return 0


def cmd_tick(args) -> int:
    cmd_shadow(args)
    cmd_settle(args)
    cmd_referee(args)
    if not args.skip_scorecard:
        cmd_scorecard(args)
    return 0


def cmd_resume(args) -> int:
    scope = _scope(args, args.scope)
    cfg = Path(args.coach_config) if args.coach_config else None
    _out(pause.resume(scope, args.reason, now=_now(args), config_file=cfg))
    return 0


def cmd_lessons(args) -> int:
    scope_map = {rules.SCOPE_HOUSE: _scope(args), rules.SCOPE_USER: _scope(args, "user")}
    _out(views.lessons_payload(scope_map, hound=args.hound, category=None, page=1, page_size=100))
    return 0


def cmd_director_pack(args) -> int:
    from src.hounds.learning import director
    return director.cmd(args)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m src.hounds.learning", description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="house scope directory (testing seam)")
    ap.add_argument("--user-dir", help="user scope directory (testing seam)")
    ap.add_argument("--champion-ledger", help="the pack ledger (testing seam)")
    ap.add_argument("--coach-config", help="the kill-switch file (testing seam)")
    ap.add_argument("--now", help="the clock, ISO UTC (testing seam)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    p = sub.add_parser("coach-scorecard")
    p.add_argument("--hound", required=True)
    p.set_defaults(fn=cmd_coach_scorecard)
    p = sub.add_parser("propose")
    p.add_argument("--hound", required=True)
    p.add_argument("--params", required=True)
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--proposed-by", default="coach")
    p.set_defaults(fn=cmd_propose)
    for name, fn in (("shadow", cmd_shadow), ("settle", cmd_settle), ("referee", cmd_referee),
                     ("scorecard", cmd_scorecard), ("tick", cmd_tick)):
        p = sub.add_parser(name)
        p.add_argument("--date")
        p.add_argument("--skip-scorecard", action="store_true")
        p.set_defaults(fn=fn)
    p = sub.add_parser("resume")
    p.add_argument("--reason", required=True)
    p.add_argument("--scope", choices=(rules.SCOPE_HOUSE, rules.SCOPE_USER), default=rules.SCOPE_HOUSE)
    p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("lessons")
    p.add_argument("--hound")
    p.set_defaults(fn=cmd_lessons)
    p = sub.add_parser("director-pack")
    p.add_argument("--month", required=True, help="YYYY-MM")
    p.add_argument("--out", help="where to write the request file (default: docs/director/YYYY-MM.request.md)")
    p.add_argument("--run-tests", action="store_true",
                   help="include the failures of the hounds' test modules (takes minutes)")
    p.set_defaults(fn=cmd_director_pack)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
