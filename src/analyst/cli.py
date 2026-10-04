"""`python -m src.cli analyst run | grade | record | compare`.

    run     for every game on a date (or one, with --game AWAY@HOME): build the
            packet, ask the model, verify, publish. `--dry-run` builds each
            packet and the exact request that WOULD be sent, prints a summary
            (the whole body with --print-request), calls nothing and writes
            nothing. A dry run needs no key: it makes no call.
    grade   grade a date's published games from the results the cards use.
    record  the record by market family, the cost per day, and the ledger's
            integrity check.
    compare arm A against arm B (docs/SITUATION_LAYER.md): per sport and market
            family, counts, results, units and calibration, rates withheld under
            30 graded calls. Reads two ledgers, calls nothing, costs nothing.
    pilot   prepare | check | publish: the supervised-session path (src/analyst/pilot.py).
            A Claude session writes the answer from the exact request the API would be
            sent; the same validation, checker and ledger publish it, into SEPARATE pilot
            stores, labelled as written in a supervised session. `grade` and `record`
            also cover the pilot's rows (under their own heading) once its store exists.

`--sport ufc` (run, grade and record all take it; `--sport mlb` is the default and is
everything in this file) hands the same arguments to `ufc_cli.py`: the UFC analyst has its
own packet, prompt, ledger and record and shares only the model call, the spend meter and
the critic with this one. `--game AWAY@HOME` is MLB's selector and `--event ID` UFC's; each
sport refuses the other's.

TWO ARMS, ONE SWITCH
--------------------
Arm A is the analyst that has always run. Arm B is the same analyst plus the situation layer
(`src/situation/`, `situation_arm.py`), frozen into its own ledger. `config/analyst.json`
`situation_arm.enabled` (off by default) makes `run` run both arms game by game; `--arm A|B|both`
overrides it for one run. With the switch off and no `--arm`, this module does exactly what it
did before arm B existed: same prompt, same packet, same ledger, same lines.

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
stops the whole run (exit 4) with a line saying so. One meter covers both arms.

EXIT CODES: 0 ok, 2 error, 3 BLOCKED, 4 spend cap reached.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.analyst import analyst as analyst_mod
from src.analyst import config as config_mod
from src.analyst import critic, ledger, packet as packet_mod
from src.analyst import situation_arm

EXIT_OK, EXIT_ERROR, EXIT_BLOCKED, EXIT_CAP = 0, 2, 3, 4

# `--sport` on run, grade and record. mlb is the default and is everything below this line;
# ufc hands the same arguments to src/analyst/ufc_cli.py.
SPORTS = ("mlb", "ufc")

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
    run.add_argument("--sport", choices=SPORTS, default="mlb",
                     help="mlb (default) or ufc: ufc analyses the date's UFC events "
                          "(src/analyst/ufc_cli.py), with its own ledger and record")
    run.add_argument("--date", required=True, help="YYYY-MM-DD")
    run.add_argument("--game", default=None, help="only this game, AWAY@HOME (e.g. NYY@TB); MLB only")
    run.add_argument("--event", default=None,
                     help="only this event id (--sport ufc), e.g. 600061182; it must be dated --date")
    run.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="build packets and the request that would be sent; call nothing, write nothing")
    run.add_argument("--print-request", dest="print_request", action="store_true",
                     help="with --dry-run, print the full request body as JSON")
    run.add_argument("--refresh", action="store_true",
                     help="publish a new version of a game already published (still before first pitch)")
    run.add_argument("--model-critic", dest="model_critic", action="store_true",
                     help="also run the optional model critic (a second call per game)")
    run.add_argument("--arm", choices=situation_arm.ARM_CHOICES, default=None,
                     help="A (matchup statistics, the analyst as it has always run), B (the same plus the "
                          "situation layer, its own ledger) or both. Default: the config switch "
                          "situation_arm.enabled, which is off, so A only")
    grade = inner.add_parser("grade", help="grade a date's published games")
    grade.add_argument("--sport", choices=SPORTS, default="mlb", help="mlb (default) or ufc")
    grade.add_argument("--date", required=True, help="YYYY-MM-DD")
    grade.add_argument("--arm", choices=situation_arm.ARM_CHOICES, default=None,
                       help="which arm's ledger to grade. Default: A, and B too when its ledger exists")
    record = inner.add_parser("record", help="the record by market family, daily cost, ledger integrity")
    record.add_argument("--sport", choices=SPORTS, default="mlb", help="mlb (default) or ufc")
    record.add_argument("--arm", choices=("A", "B"), default="A", help="which arm's record to print (default A)")
    pilot = inner.add_parser("pilot", help="the supervised-session pilot: prepare, check, publish "
                                           "(MLB only; its own stores)")
    pilot_sub = pilot.add_subparsers(dest="pilot_command", required=True)
    prep = pilot_sub.add_parser("prepare", help="build the packet and the exact request for one game")
    prep.add_argument("--date", required=True, help="YYYY-MM-DD")
    prep.add_argument("--game", required=True, help="AWAY@HOME (e.g. NYY@TB)")
    prep.add_argument("--scratch", default=None,
                      help="write to this folder instead and mark it a rehearsal (it can be checked, "
                           "never published)")
    chk = pilot_sub.add_parser("check", help="validate and run the checker on a response; publishes nothing")
    chk.add_argument("--dir", required=True, help="the prepared folder")
    chk.add_argument("--response", required=True, help="the JSON answer the session wrote")
    pub = pilot_sub.add_parser("publish", help="freeze a response into the pilot ledger")
    pub.add_argument("--dir", required=True, help="the prepared folder")
    pub.add_argument("--response", required=True, help="the JSON answer the session wrote")
    pub.add_argument("--model", required=True, help="the model that wrote the answer, as the session names it")
    pub.add_argument("--tokens-in", dest="tokens_in", type=int, default=None)
    pub.add_argument("--tokens-out", dest="tokens_out", type=int, default=None)
    pub.add_argument("--seconds", type=float, default=None, help="how long the answer took")
    pub.add_argument("--operator-minutes", dest="operator_minutes", type=float, default=None,
                     help="operator time spent on this game")
    pub.add_argument("--refresh", action="store_true",
                     help="publish a new version of a game that already has a pilot row")
    compare = inner.add_parser("compare", help="arm A against arm B, by sport and market family")
    compare.add_argument("--sport", choices=("mlb", "ufc", "all"), default="all")
    compare.add_argument("--json", dest="as_json", action="store_true", help="print the report as JSON")


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


def _packet(item: Mapping, built_at: str, cfg: Mapping, situation: Optional[Mapping] = None) -> dict:
    return packet_mod.build_packet(
        item["payload"], built_at=built_at,
        multibook_rows=item.get("multibook_rows") or (),
        team_total_rows=item.get("team_total_rows") or (),
        batter_prop_rows=item.get("batter_prop_rows") or (),
        pitcher_prop_rows=item.get("pitcher_prop_rows") or (),
        prop_board=item.get("prop_board") or (),
        team_names=item.get("team_names"), section_as_of=item.get("section_as_of"), cfg=cfg,
        situation=situation)


def _item_id(item: Mapping) -> str:
    advanced = (item.get("payload") or {}).get("advanced") or {}
    return str(advanced.get("game_id") or "unknown game")


refusal = ledger.publish_refusal


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@dataclass
class _ArmRun:
    """One arm of one run: its prompt and files, and the games it has already frozen."""
    arm: situation_arm.Arm
    store_path: Optional[str]
    usage_path: Optional[str]
    packet_dir: Optional[str]
    existing: dict


def _arm_runs(names, *, store_path, usage_path, packet_dir, arm_b_paths) -> list:
    """The arms a run makes. Arm A's files are the `*_path` arguments (None is the real default,
    as it has always been); arm B's are `arm_b_paths` (`store`, `usage`, `packet_dir`) or its own
    defaults beside arm A's."""
    runs = []
    for name in names:
        arm = situation_arm.mlb_arm(name)
        if name == situation_arm.ARM_A:
            files = (store_path, usage_path, packet_dir)
        else:
            b = dict(arm_b_paths or {})
            files = (b.get("store") or arm.abs_store(), b.get("usage") or arm.abs_usage(),
                     b.get("packet_dir") or arm.abs_packet_dir())
        runs.append(_ArmRun(arm, *files, existing=ledger.latest_published(ledger.rows(files[0]))))
    return runs


def _log_usage(run: _ArmRun, extra: Optional[Mapping] = None, **kw) -> None:
    """The cost row. Arm A's rows are what they have always been; arm B's say `arm: "B"`."""
    if run.arm.name != situation_arm.ARM_A:
        extra = dict(extra or {}, arm=run.arm.name)
    if extra:
        kw["extra"] = extra
    ledger.log_usage(path=run.usage_path, **kw)


def execute_run(date: str, *, game: Optional[str] = None, dry_run: bool = False,
                print_request: bool = False, refresh: bool = False,
                use_model_critic: Optional[bool] = None,
                env: Optional[Mapping] = None, http_post=None,
                loader: Optional[Callable] = None, now: Optional[Callable] = None,
                out: Callable = print, cfg: Optional[Mapping] = None,
                store_path: Optional[str] = None, usage_path: Optional[str] = None,
                packet_dir: Optional[str] = None, arm: Optional[str] = None,
                situation_for: Optional[Callable] = None,
                arm_b_paths: Optional[Mapping] = None) -> int:
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    clock = now or _now
    key = config_mod.api_key(env)
    if not dry_run and not key:
        out(f"BLOCKED: {config_mod.ENV_KEY} is not set, so the analyst cannot call the model. "
            "Nothing was built, sent or written. See docs/decisions/AI_ANALYST_ENABLE.md.")
        return EXIT_BLOCKED
    try:
        names = situation_arm.selected_arms(arm, cfg)
    except ValueError as exc:
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    http = http_post or analyst_mod.urllib_post
    critic_on = cfg["model_critic"]["enabled"] if use_model_critic is None else use_model_critic
    items = [i for i in (loader or default_loader)(date)
             if _matches(i["payload"]["advanced"]["game"], game)]
    if not items:
        out(f"no games found for {date}" + (f" matching {game}" if game else ""))
        return EXIT_ERROR if game else EXIT_OK

    arm_runs = _arm_runs(names, store_path=store_path, usage_path=usage_path, packet_dir=packet_dir,
                         arm_b_paths=arm_b_paths)
    if situation_for is None and any(r.arm.situation for r in arm_runs):
        from src.analyst import source
        situation_for = source.mlb_situation_provider()
    meter = analyst_mod.SpendMeter.from_config(cfg)
    run_id = uuid.uuid4().hex[:12]
    lead = float(cfg["lock_lead_minutes"])
    counts = {r.arm.name: {"published": 0, "skipped": 0, "failed": 0} for r in arm_runs}
    api_failures = 0
    status = EXIT_OK
    for item in items:
        # Both arms take the same game one straight after the other, so the two are frozen minutes
        # apart: a game that starts between them is refused by arm B as arm A would have been.
        for run in arm_runs:
            tag, count = run.arm.tag, counts[run.arm.name]
            moment = clock()
            built_at = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            situation = None
            if run.arm.situation:
                try:
                    situation = situation_for(item)
                except Exception as exc:  # noqa: BLE001 -- arm B never takes arm A down
                    out(f"{tag}SKIP {_item_id(item)}: the situation could not be built "
                        f"({type(exc).__name__}: {exc})")
                    count["skipped"] += 1
                    continue
            packet = _packet(item, built_at, cfg, situation)
            gid = packet["game"]["game_id"]
            why = refusal(packet, moment, lead)
            if why:
                out(f"{tag}SKIP {gid}: {why}")
                count["skipped"] += 1
                continue
            if not packet["markets"]:
                out(f"{tag}SKIP {gid}: the packet prices no market, so there is nothing to call")
                count["skipped"] += 1
                continue
            if gid in run.existing and not refresh:
                out(f"{tag}SKIP {gid}: already published (v{run.existing[gid]['version']}); frozen unless --refresh")
                count["skipped"] += 1
                continue
            digest = packet_mod.packet_hash(packet)
            body = analyst_mod.build_request(packet, cfg, system_prompt=run.arm.system_prompt)
            est_in = analyst_mod.estimate_tokens(body["system"], body["messages"][0]["content"])
            price = cfg["price_per_million_usd"]
            worst = (est_in * price["input"] + cfg["max_output_tokens"] * price["output"]) / 1e6
            if dry_run:
                out(f"{tag}DRY RUN {gid}: packet {digest[:12]}, {len(packet['slots'])} slots, "
                    f"{len(packet['missing'])} missing items, request ~{est_in} input tokens "
                    f"(high estimate), worst case ${worst:.2f}; nothing sent, nothing written")
                out("  slots: " + ", ".join(s["slot_id"] for s in packet["slots"]))
                if situation is not None:
                    out(f"  situation: {len(situation['factors'])} facts, {len(situation['missing'])} missing")
                if print_request:
                    out(json.dumps(body, indent=2, sort_keys=True))
                continue
            try:
                result = analyst_mod.analyze(packet, cfg, api_key=key, http_post=http, meter=meter,
                                             system_prompt=run.arm.system_prompt)
                api_failures = 0
            except analyst_mod.SpendCapReached as exc:
                published = sum(c["published"] for c in counts.values())
                out(f"STOPPED: {exc}. {published} published before the stop; the rest were not analysed.")
                return EXIT_CAP
            except analyst_mod.MalformedOutput as exc:
                out(f"{tag}FAIL {gid}: the model's answer was rejected after {cfg['max_attempts']} "
                    f"attempts: {exc}")
                _log_usage(run, date=date, game_id=gid, run_id=run_id, outcome="rejected_malformed",
                           model=cfg["model"], usage=exc.usage,
                           cost_usd=analyst_mod.cost_usd(exc.usage, cfg),
                           attempts=cfg["max_attempts"], cfg=cfg, now=clock())
                count["failed"] += 1
                continue
            except analyst_mod.ModelRefused as exc:
                # a completed call, so it was billed: logged like any other spend
                out(f"{tag}FAIL {gid}: {exc}")
                _log_usage(run, date=date, game_id=gid, run_id=run_id, outcome="model_refused",
                           model=cfg["model"], usage=exc.usage, cost_usd=exc.cost_usd,
                           attempts=1, cfg=cfg, now=clock())
                count["failed"] += 1
                continue
            except analyst_mod.AnalystError as exc:
                out(f"{tag}FAIL {gid}: {exc}")
                count["failed"] += 1
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
                    out(f"{tag}NOTE {gid}: model critic skipped: {exc}")
                except analyst_mod.AnalystError as exc:
                    mc_status = "did not run"
                    out(f"{tag}NOTE {gid}: model critic did not run: {exc}")
            verified = critic.verify(packet, result.output, model_critic=verdict_json,
                                     model_critic_status=mc_status)
            try:
                row, created = ledger.publish(
                    packet, verified, now=clock(), model=result.model,
                    run={"run_id": run_id, "cost_usd": round(cost, 4), "usage": usage,
                         "attempts": result.attempts, "request_ids": result.request_ids},
                    path=run.store_path, packet_dir=run.packet_dir, lock_lead_minutes=lead,
                    refresh=refresh, prompt_version=run.arm.prompt_version,
                    system_prompt=run.arm.system_prompt if run.arm.situation else None,
                    extra=run.arm.extra)
            except ledger.AnalystLedgerError as exc:
                out(f"{tag}REFUSED {gid}: {exc}")
                _log_usage(run, date=date, game_id=gid, run_id=run_id, outcome="refused_at_publish",
                           model=result.model, usage=usage, cost_usd=cost,
                           attempts=result.attempts, cfg=cfg, now=clock())
                count["skipped"] += 1
                continue
            _log_usage(run, extra={"calls": len(verified.calls), "struck": len(verified.struck)},
                       date=date, game_id=gid, run_id=run_id,
                       outcome="published" if created else "already_published",
                       model=result.model, usage=usage, cost_usd=cost,
                       attempts=result.attempts, cfg=cfg, now=clock())
            out(f"{tag}PUBLISHED {gid} v{row['version']}: {len(verified.calls)} calls, "
                f"{len(verified.struck)} struck, summary {verified.summary_status}, "
                f"${cost:.3f}, hash {row['row_hash'][:12]}")
            count["published"] += 1
    published = sum(c["published"] for c in counts.values())
    skipped = sum(c["skipped"] for c in counts.values())
    failed = sum(c["failed"] for c in counts.values())
    if dry_run:
        out(f"dry run over {len(items)} game(s); nothing sent, nothing written")
    else:
        out(f"run {run_id}: {published} published, {skipped} skipped, {failed} failed, "
            f"${meter.spent_usd:.3f} spent of ${meter.max_usd:.2f}")
        if len(arm_runs) > 1:
            out("  " + "; ".join(f"arm {n}: {c['published']} published, {c['skipped']} skipped, {c['failed']} failed"
                                  for n, c in counts.items()))
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


def _pilot_store(store_path: Optional[str], pilot_store: Optional[str]) -> Optional[str]:
    """The pilot's store when it exists, else None. An injected main store (a test, a rehearsal)
    means the real pilot store is left alone unless one was injected too."""
    if pilot_store is None and store_path is not None:
        return None
    from src.analyst import pilot
    target = pilot_store or pilot.store_paths()["store"]
    return target if Path(target).exists() else None


def execute_grade(date: str, *, results: Optional[Callable] = None,
                  now: Optional[Callable] = None, out: Callable = print,
                  store_path: Optional[str] = None, arm: Optional[str] = None,
                  arm_b_store: Optional[str] = None, pilot_store: Optional[str] = None) -> int:
    """Grade a date. Arm A always (unless `arm` is B); arm B too when asked for or when its ledger
    exists: grading costs nothing and an arm that is not graded is an arm that cannot be compared.
    The supervised-session pilot's rows are graded too once its store exists (same code, its own file)."""
    by_pk, box = (results or default_results)(date)
    clock = (now or _now)()
    b_store = arm_b_store or situation_arm.mlb_arm(situation_arm.ARM_B).abs_store()
    wanted ={None: (situation_arm.ARM_A,) + ((situation_arm.ARM_B,) if Path(b_store).exists() else ()),
              "A": (situation_arm.ARM_A,), "B": (situation_arm.ARM_B,),
              "both": situation_arm.ARMS}[arm]
    for name in wanted:
        path = store_path if name == situation_arm.ARM_A else b_store
        counts = ledger.grade_date(date, by_pk, box, now=clock, path=path)
        label = "" if name == situation_arm.ARM_A else f" [arm {name}]"
        out(f"analyst grade {date}{label}: published={counts['published']} graded={counts['graded']} "
            f"complete={counts['complete']} unchanged={counts['unchanged']}")
        for note in counts["notes"]:
            out(f"  {note}")
    pilot_path = _pilot_store(store_path, pilot_store) if arm != "B" else None
    if pilot_path:
        counts = ledger.grade_date(date, by_pk, box, now=clock, path=pilot_path)
        out(f"analyst grade {date} [pilot]: published={counts['published']} graded={counts['graded']} "
            f"complete={counts['complete']} unchanged={counts['unchanged']}")
        for note in counts["notes"]:
            out(f"  {note}")
    return EXIT_OK


def _print_record(rec: Mapping, out: Callable, label: Optional[str] = None) -> None:
    out(label or rec["label"])
    out(f"games published {rec['games_published']}, settled {rec['games_settled']}")
    for name, f in rec["families"].items():
        rate = "withheld" if f["win_rate"] is None else f"{f['win_rate'] * 100:.1f}%"
        out(f"  {name:11s} taken {f['taken']} (other side {f['taken_other_side']}), "
            f"passes {f['passes']}, graded {f['graded']} "
            f"(W{f['wins']} L{f['losses']} P{f['pushes']} V{f['voids']}), "
            f"unresolved {f['unresolved']}, win rate {rate}")


def execute_record(*, out: Callable = print, store_path: Optional[str] = None,
                   usage_path: Optional[str] = None, cfg: Optional[Mapping] = None,
                   arm: str = situation_arm.ARM_A, pilot_store: Optional[str] = None) -> int:
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    if arm == situation_arm.ARM_B:
        spec = situation_arm.mlb_arm(arm)
        store_path = store_path or spec.abs_store()
        usage_path = usage_path or spec.abs_usage()
        out("ARM B: the analyst plus the situation layer (docs/SITUATION_LAYER.md)")
    rec = ledger.record(path=store_path, min_graded=cfg["min_graded_for_rates"])
    _print_record(rec, out)
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
    ok = check["ok"]
    pilot_path = _pilot_store(store_path, pilot_store) if arm == situation_arm.ARM_A else None
    if pilot_path:
        # Its own heading, its own chain check, never added to the record above.
        from src.analyst import PILOT_LABEL
        out("")
        out("SUPERVISED-SESSION BRIEFS (a separate record; never added to the one above)")
        _print_record(ledger.record(path=pilot_path, min_graded=cfg["min_graded_for_rates"]), out,
                      label=PILOT_LABEL)
        pcheck = ledger.verify(pilot_path)
        out(f"pilot ledger: {'OK' if pcheck['ok'] else 'PROBLEM'} ({pcheck['rows']} rows)")
        for problem in pcheck["problems"]:
            out(f"  {problem}")
        ok = ok and pcheck["ok"]
    return EXIT_OK if ok else EXIT_ERROR


def main(args) -> int:
    """Dispatch for `src.cli`."""
    if args.analyst_command == "compare":
        from src.analyst import compare
        return compare.execute_compare(sport=args.sport, as_json=args.as_json)
    if getattr(args, "sport", "mlb") == "ufc":
        from src.analyst import ufc_cli     # lazy: ufc_cli imports this module
        return ufc_cli.main(args)
    if args.analyst_command == "pilot":
        from src.analyst import pilot       # lazy: pilot imports this module
        if args.pilot_command == "prepare":
            return pilot.prepare(args.date, args.game, scratch=args.scratch)
        if args.pilot_command == "check":
            return pilot.check(args.dir, args.response)
        return pilot.publish(args.dir, args.response, model=args.model, tokens_in=args.tokens_in,
                             tokens_out=args.tokens_out, seconds=args.seconds,
                             operator_minutes=args.operator_minutes, refresh=args.refresh)
    if getattr(args, "event", None):
        print("--event is for --sport ufc; for MLB use --game AWAY@HOME")
        return EXIT_ERROR
    if args.analyst_command == "run":
        return execute_run(args.date, game=args.game, dry_run=args.dry_run,
                           print_request=args.print_request, refresh=args.refresh,
                           use_model_critic=True if args.model_critic else None, arm=args.arm)
    if args.analyst_command == "grade":
        return execute_grade(args.date, arm=args.arm)
    return execute_record(arm=args.arm)
