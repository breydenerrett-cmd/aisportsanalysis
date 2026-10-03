"""`python -m src.cli analyst run | grade | record`.

    run     for every game on a date (or one, with --game AWAY@HOME): build the
            packet, ask the model, verify, publish. `--dry-run` builds each
            packet and the exact request that WOULD be sent, prints a summary
            (the whole body with --print-request), calls nothing and writes
            nothing. A dry run needs no key: it makes no call.
    grade   grade a date's published games from the results the cards use.
    record  the record by market family, the cost per day, and the ledger's
            integrity check.

WITHOUT A KEY
-------------
`run` without ANTHROPIC_API_KEY prints `BLOCKED: <reason>` and exits 3 before
anything is built, called or written: no ledger row, no usage row, no packet
file. A BLOCKED run is therefore indistinguishable from a run that never
happened, which is the point: the daily job can carry the step safely before
the owner has created the key.

THE ORDER OF REFUSALS IS THE ORDER OF COST
------------------------------------------
Everything that can be decided without the model is decided first: a game
that has started, whose state is not pending, or that is already published and
frozen is skipped BEFORE the call, so the model is never paid to analyse a
game that cannot be published. The spend cap is checked before each call and
stops the whole run (exit 4) with a line saying so.

EXIT CODES: 0 ok, 2 error, 3 BLOCKED, 4 spend cap reached.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional

from src.analyst import analyst as analyst_mod
from src.analyst import config as config_mod
from src.analyst import critic, ledger, packet as packet_mod

EXIT_OK, EXIT_ERROR, EXIT_BLOCKED, EXIT_CAP = 0, 2, 3, 4

# After this many games in a row fail at the API (not malformed output: the
# API itself), the run stops instead of burning the slate on a dead key or an
# outage.
MAX_CONSECUTIVE_API_FAILURES = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def add_parser(sub) -> None:
    """Register `analyst` on the top-level CLI's subparsers."""
    cmd = sub.add_parser("analyst", help="the AI analyst: a model-written analysis "
                                         "of every game, frozen before first pitch")
    inner = cmd.add_subparsers(dest="analyst_command", required=True)
    run = inner.add_parser("run", help="analyse a date's games and publish before first pitch")
    run.add_argument("--date", required=True, help="YYYY-MM-DD")
    run.add_argument("--game", default=None, help="only this game, AWAY@HOME (e.g. NYY@TB)")
    run.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="build packets and the request that would be sent; call nothing, write nothing")
    run.add_argument("--print-request", dest="print_request", action="store_true",
                     help="with --dry-run, print the full request body as JSON")
    run.add_argument("--refresh", action="store_true",
                     help="publish a new version of a game already published (still before first pitch)")
    run.add_argument("--model-critic", dest="model_critic", action="store_true",
                     help="also run the optional model critic (a second call per game)")
    grade = inner.add_parser("grade", help="grade a date's published games")
    grade.add_argument("--date", required=True, help="YYYY-MM-DD")
    inner.add_parser("record", help="the record by market family, daily cost, ledger integrity")


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def default_loader(date: str) -> list:
    """Every game's payload and price rows, from the stores. The only place
    this module reads the schedule provider or disk."""
    from src.analyst import source

    slate = source.slate_payloads(date)
    games = [s["game"] for s in slate]
    rows = source.price_rows(date, games)
    boards = source.prop_board_for(date, {pk: r["batter_props"] for pk, r in rows.items()})
    through = source.stats_through(date)
    out = []
    for s in slate:
        pk = s["game"].get("game_pk")
        r = rows[pk]
        out.append({
            "payload": s["payload"],
            "multibook_rows": r["multibook"], "team_total_rows": r["team_totals"],
            "batter_prop_rows": r["batter_props"], "pitcher_prop_rows": r["pitcher_props"],
            "prop_board": boards.get(pk, []), "team_names": r["team_names"],
            "section_as_of": {"teams": through, "starters": through} if through else {},
        })
    return out


def _matches(game: Mapping, wanted: Optional[str]) -> bool:
    if not wanted:
        return True
    away, _, home = wanted.upper().partition("@")
    return (str(game.get("away_team") or "").upper() == away
            and str(game.get("home_team") or "").upper() == home)


def _packet(item: Mapping, built_at: str, cfg: Mapping) -> dict:
    return packet_mod.build_packet(
        item["payload"], built_at=built_at,
        multibook_rows=item.get("multibook_rows") or (),
        team_total_rows=item.get("team_total_rows") or (),
        batter_prop_rows=item.get("batter_prop_rows") or (),
        pitcher_prop_rows=item.get("pitcher_prop_rows") or (),
        prop_board=item.get("prop_board") or (),
        team_names=item.get("team_names"), section_as_of=item.get("section_as_of"), cfg=cfg)


refusal = ledger.publish_refusal


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def execute_run(date: str, *, game: Optional[str] = None, dry_run: bool = False,
                print_request: bool = False, refresh: bool = False,
                use_model_critic: Optional[bool] = None,
                env: Optional[Mapping] = None, http_post=None,
                loader: Optional[Callable] = None, now: Optional[Callable] = None,
                out: Callable = print, cfg: Optional[Mapping] = None,
                store_path: Optional[str] = None, usage_path: Optional[str] = None,
                packet_dir: Optional[str] = None) -> int:
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    clock = now or _now
    key = config_mod.api_key(env)
    if not dry_run and not key:
        out(f"BLOCKED: {config_mod.ENV_KEY} is not set, so the analyst cannot call the model. "
            "Nothing was built, sent or written. See docs/decisions/AI_ANALYST_ENABLE.md.")
        return EXIT_BLOCKED
    http = http_post or analyst_mod.urllib_post
    critic_on = cfg["model_critic"]["enabled"] if use_model_critic is None else use_model_critic
    items = [i for i in (loader or default_loader)(date)
             if _matches(i["payload"]["advanced"]["game"], game)]
    if not items:
        out(f"no games found for {date}" + (f" matching {game}" if game else ""))
        return EXIT_ERROR if game else EXIT_OK

    meter = analyst_mod.SpendMeter.from_config(cfg)
    run_id = uuid.uuid4().hex[:12]
    lead = float(cfg["lock_lead_minutes"])
    published = skipped = failed = 0
    api_failures = 0
    status = EXIT_OK
    existing = ledger.latest_published(ledger.rows(store_path))
    for item in items:
        moment = clock()
        built_at = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        packet = _packet(item, built_at, cfg)
        gid = packet["game"]["game_id"]
        why = refusal(packet, moment, lead)
        if why:
            out(f"SKIP {gid}: {why}")
            skipped += 1
            continue
        if not packet["markets"]:
            out(f"SKIP {gid}: the packet prices no market, so there is nothing to call")
            skipped += 1
            continue
        if gid in existing and not refresh:
            out(f"SKIP {gid}: already published (v{existing[gid]['version']}); frozen unless --refresh")
            skipped += 1
            continue
        digest = packet_mod.packet_hash(packet)
        body = analyst_mod.build_request(packet, cfg)
        est_in = analyst_mod.estimate_tokens(body["system"], body["messages"][0]["content"])
        price = cfg["price_per_million_usd"]
        worst = (est_in * price["input"] + cfg["max_output_tokens"] * price["output"]) / 1e6
        if dry_run:
            out(f"DRY RUN {gid}: packet {digest[:12]}, {len(packet['slots'])} slots, "
                f"{len(packet['missing'])} missing items, request ~{est_in} input tokens "
                f"(high estimate), worst case ${worst:.2f}; nothing sent, nothing written")
            out("  slots: " + ", ".join(s["slot_id"] for s in packet["slots"]))
            if print_request:
                out(json.dumps(body, indent=2, sort_keys=True))
            continue
        try:
            result = analyst_mod.analyze(packet, cfg, api_key=key, http_post=http, meter=meter)
            api_failures = 0
        except analyst_mod.SpendCapReached as exc:
            out(f"STOPPED: {exc}. {published} published before the stop; the rest were not analysed.")
            return EXIT_CAP
        except analyst_mod.MalformedOutput as exc:
            out(f"FAIL {gid}: the model's answer was rejected after {cfg['max_attempts']} "
                f"attempts: {exc}")
            ledger.log_usage(date=date, game_id=gid, run_id=run_id, outcome="rejected_malformed",
                             model=cfg["model"], usage=exc.usage,
                             cost_usd=analyst_mod.cost_usd(exc.usage, cfg),
                             attempts=cfg["max_attempts"], cfg=cfg, now=clock(), path=usage_path)
            failed += 1
            continue
        except analyst_mod.ModelRefused as exc:
            # a completed call, so it was billed: logged like any other spend
            out(f"FAIL {gid}: {exc}")
            ledger.log_usage(date=date, game_id=gid, run_id=run_id, outcome="model_refused",
                             model=cfg["model"], usage=exc.usage, cost_usd=exc.cost_usd,
                             attempts=1, cfg=cfg, now=clock(), path=usage_path)
            failed += 1
            continue
        except analyst_mod.AnalystError as exc:
            out(f"FAIL {gid}: {exc}")
            failed += 1
            api_failures += 1
            if api_failures >= MAX_CONSECUTIVE_API_FAILURES:
                out(f"STOPPED: {api_failures} games in a row failed at the API; not continuing.")
                return EXIT_ERROR
            continue

        verdict_json, mc_status = None, "off"
        usage, cost = dict(result.usage), result.cost_usd
        if critic_on:
            try:
                verdict_json, c_usage, c_cost = analyst_mod.run_model_critic(
                    packet, result.output, cfg, api_key=key, http_post=http, meter=meter)
                mc_status = "ran"
                cost += c_cost
                analyst_mod._add_usage(usage, c_usage)
            except analyst_mod.SpendCapReached as exc:
                mc_status = "did not run"
                out(f"NOTE {gid}: model critic skipped: {exc}")
            except analyst_mod.AnalystError as exc:
                mc_status = "did not run"
                out(f"NOTE {gid}: model critic did not run: {exc}")
        verified = critic.verify(packet, result.output, model_critic=verdict_json,
                                 model_critic_status=mc_status)
        try:
            row, created = ledger.publish(
                packet, verified, now=clock(), model=result.model,
                run={"run_id": run_id, "cost_usd": round(cost, 4), "usage": usage,
                     "attempts": result.attempts, "request_ids": result.request_ids},
                path=store_path, packet_dir=packet_dir, lock_lead_minutes=lead, refresh=refresh)
        except ledger.AnalystLedgerError as exc:
            out(f"REFUSED {gid}: {exc}")
            ledger.log_usage(date=date, game_id=gid, run_id=run_id, outcome="refused_at_publish",
                             model=result.model, usage=usage, cost_usd=cost,
                             attempts=result.attempts, cfg=cfg, now=clock(), path=usage_path)
            skipped += 1
            continue
        ledger.log_usage(date=date, game_id=gid, run_id=run_id,
                         outcome="published" if created else "already_published",
                         model=result.model, usage=usage, cost_usd=cost,
                         attempts=result.attempts, cfg=cfg, now=clock(), path=usage_path,
                         extra={"calls": len(verified.calls), "struck": len(verified.struck)})
        out(f"PUBLISHED {gid} v{row['version']}: {len(verified.calls)} calls, "
            f"{len(verified.struck)} struck, summary {verified.summary_status}, "
            f"${cost:.3f}, hash {row['row_hash'][:12]}")
        published += 1
    if dry_run:
        out(f"dry run over {len(items)} game(s); nothing sent, nothing written")
    else:
        out(f"run {run_id}: {published} published, {skipped} skipped, {failed} failed, "
            f"${meter.spent_usd:.3f} spent of ${meter.max_usd:.2f}")
    return EXIT_ERROR if failed and not published else status


# ---------------------------------------------------------------------------
# grade, record
# ---------------------------------------------------------------------------

def default_results(date: str) -> tuple:
    """(results by game_pk for `date`, that season's box rows)."""
    from src.pipeline import boxscores, history
    from src.paths import processed_path

    by_pk: dict = {}
    for row in (history.read_results() or {}).values():
        if str(row.get("date")) == date:
            pk = row.get("game_pk")
            for k in (pk, str(pk)):
                by_pk[k] = row
            try:
                by_pk[int(pk)] = row
            except (TypeError, ValueError):
                pass
    try:
        box = boxscores.read(processed_path(f"boxscores_{date[:4]}.jsonl"))
    except boxscores.BoxscoresError:
        box = []
    return by_pk, [r for r in box if str(r.get("date")) == date]


def execute_grade(date: str, *, results: Optional[Callable] = None,
                  now: Optional[Callable] = None, out: Callable = print,
                  store_path: Optional[str] = None) -> int:
    by_pk, box = (results or default_results)(date)
    counts = ledger.grade_date(date, by_pk, box, now=(now or _now)(), path=store_path)
    out(f"analyst grade {date}: published={counts['published']} graded={counts['graded']} "
        f"complete={counts['complete']} unchanged={counts['unchanged']}")
    for note in counts["notes"]:
        out(f"  {note}")
    return EXIT_OK


def execute_record(*, out: Callable = print, store_path: Optional[str] = None,
                   usage_path: Optional[str] = None, cfg: Optional[Mapping] = None) -> int:
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    rec = ledger.record(path=store_path, min_graded=cfg["min_graded_for_rates"])
    out(rec["label"])
    out(f"games published {rec['games_published']}, settled {rec['games_settled']}")
    for name, f in rec["families"].items():
        rate = "withheld" if f["win_rate"] is None else f"{f['win_rate'] * 100:.1f}%"
        out(f"  {name:11s} taken {f['taken']} (other side {f['taken_other_side']}), "
            f"passes {f['passes']}, graded {f['graded']} "
            f"(W{f['wins']} L{f['losses']} P{f['pushes']} V{f['voids']}), "
            f"unresolved {f['unresolved']}, win rate {rate}")
    check = ledger.verify(store_path)
    out(f"ledger: {'OK' if check['ok'] else 'PROBLEM'} ({check['rows']} rows)")
    for problem in check["problems"]:
        out(f"  {problem}")
    usage = ledger.usage_by_day(usage_path)
    if usage:
        out("cost per day (estimates from the usage the API returned):")
        for day in sorted(usage):
            u = usage[day]
            out(f"  {day}: {u['published']}/{u['games']} games published, "
                f"{u['input_tokens']} in / {u['output_tokens']} out tokens, ${u['cost_usd']:.2f}")
    return EXIT_OK if check["ok"] else EXIT_ERROR


def main(args) -> int:
    """Dispatch for `src.cli`."""
    if args.analyst_command == "run":
        return execute_run(args.date, game=args.game, dry_run=args.dry_run,
                           print_request=args.print_request, refresh=args.refresh,
                           use_model_critic=True if args.model_critic else None)
    if args.analyst_command == "grade":
        return execute_grade(args.date)
    return execute_record()
