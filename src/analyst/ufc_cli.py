"""`python -m src.cli analyst run | grade | record --sport ufc`.

    run     for every bout of a date's UFC events (or of one event, with --event ID):
            build the packet, ask the model, verify, publish. `--dry-run` builds each
            packet and the exact request that WOULD be sent, prints its size, its slot
            count and its worst-case cost, calls nothing and writes nothing (the whole
            body with --print-request). A dry run needs no key: it makes no call.
    grade   grade a date's published bouts from the data layer's results.
    record  the record by market family, the cost per day, and the ledger's integrity.

The MLB commands are `src/analyst/cli.py` and are not touched by this module; `--sport`
defaults to mlb there and only `--sport ufc` comes here.

WITHOUT A KEY
-------------
`run` without ANTHROPIC_API_KEY prints `BLOCKED: <reason>` and exits 3 before anything is
loaded, built, called or written: no ledger row, no usage row, no packet file. The same
key as the MLB analyst; nothing new for the owner to create.

THE ORDER OF REFUSALS IS THE ORDER OF COST
------------------------------------------
Everything that can be decided without the model is decided first: a bout that has
started, whose scheduled start is unknown, whose state is not "scheduled", that prices no
market, whose fighters the store cannot name, or that is already published and frozen is
skipped BEFORE the call, so the model is never paid to analyse a bout that cannot be
published. The spend cap is checked before each call and stops the whole run (exit 4).

BOUTS ARE TAKEN EARLIEST START FIRST
------------------------------------
A card's segments start hours apart and a bout is refused at its scheduled start, so the
earliest bouts are analysed first (main event first within a segment). A run that begins
close to the first bout publishes what it can, in the order that loses the least.

A DATE IS AN EVENT'S DATE
-------------------------
`--date` selects the events whose start, in UTC, falls on that date; every bout of such an
event carries that date in the ledger, including main-card bouts that start after
midnight UTC. `grade --date` uses the same date.

EXIT CODES: 0 ok, 2 error, 3 BLOCKED, 4 spend cap reached.
"""

from __future__ import annotations

import json
import uuid
from datetime import timezone
from typing import Callable, Mapping, Optional

from src.analyst import analyst as analyst_mod
from src.analyst import config as config_mod
from src.analyst import ufc_analyst, ufc_ledger, ufc_packet
from src.analyst.cli import (EXIT_BLOCKED, EXIT_CAP, EXIT_ERROR, EXIT_OK,
                             MAX_CONSECUTIVE_API_FAILURES, _now)
from src.datasvc.ufc import features as feat


def _print(line: str) -> None:
    """`print`, except that a console that cannot encode a fighter's name (a Windows code
    page meeting a name with a diacritic) gets it with a question mark instead of a
    traceback. Only what is shown is changed; the packet, the ledger and every file keep
    the real name."""
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def _event_date(event: Mapping) -> Optional[str]:
    """The UTC date an event starts on, or None when the store has no readable start."""
    moment = feat.instant(event.get("date_utc"))
    return moment.date().isoformat() if moment else None


def default_loader(date: str, event: Optional[str] = None) -> list:
    """`[{"store", "bout_id", "event_id"}]` for the date's events (or one event), earliest
    start first and the main event first within a start. The only place this module reads
    the data layer's files."""
    from src.datasvc.ufc.store import UfcStore

    store = UfcStore()
    events = store.events
    if event:
        chosen = [e for e in events if str(e.get("event_id")) == str(event)]
        if not chosen:
            raise LookupError(f"no event {event!r} in the UFC store")
        dated = _event_date(chosen[0])
        if dated != date:
            raise ValueError(f"event {event!r} is dated {dated or 'unknown'}, not {date}")
    else:
        chosen = [e for e in events if _event_date(e) == date]
    bouts = store.bout_by_id()
    items = []
    for e in chosen:
        for bid in e.get("bout_ids") or []:
            bout = bouts.get(bid)
            start = feat.bout_start(bout) if bout else None
            number = (bout or {}).get("match_number")
            items.append(((start is None, start.isoformat() if start else "",
                           number if isinstance(number, int) else 10 ** 6, str(bid)),
                          {"store": store, "bout_id": bid, "event_id": e.get("event_id")}))
    return [item for _key, item in sorted(items, key=lambda pair: pair[0])]


def _title(packet: Mapping) -> str:
    bout = packet["bout"]
    return f"{bout['fighter_a']['name']} vs {bout['fighter_b']['name']}"


def _unnamed(packet: Mapping) -> list:
    bout = packet["bout"]
    return [side for side in ("a", "b") if not bout[f"fighter_{side}"].get("name_known")]


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def execute_run(date: str, *, event: Optional[str] = None, dry_run: bool = False,
                print_request: bool = False, refresh: bool = False,
                use_model_critic: Optional[bool] = None,
                env: Optional[Mapping] = None, http_post=None,
                loader: Optional[Callable] = None, now: Optional[Callable] = None,
                out: Callable = _print, cfg: Optional[Mapping] = None,
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
    try:
        items = list((loader or default_loader)(date, event))
    except (OSError, ValueError, LookupError) as exc:
        out(f"ERROR: could not load the UFC card for {date}: {exc}")
        return EXIT_ERROR
    if not items:
        out(f"no UFC bouts found for {date}" + (f" in event {event}" if event else ""))
        return EXIT_ERROR if event else EXIT_OK

    meter = analyst_mod.SpendMeter.from_config(cfg)
    run_id = uuid.uuid4().hex[:12]
    lead = float(cfg["lock_lead_minutes"])
    price = cfg["price_per_million_usd"]
    published = skipped = failed = api_failures = 0
    dry = {"bouts": 0, "slots": 0, "tokens": 0, "worst": 0.0}
    existing = ufc_ledger.latest_published(ufc_ledger.rows(store_path))
    for item in items:
        moment = clock()
        built_at = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            packet = ufc_packet.build_packet(item["store"], item["bout_id"], built_at=built_at, cfg=cfg)
        except ufc_packet.UfcPacketError as exc:
            out(f"SKIP {item['bout_id']}: {exc}")
            skipped += 1
            continue
        bid = packet["bout"]["bout_id"]
        who = f"{bid} {_title(packet)}"
        why = ufc_ledger.publish_refusal(packet, moment, lead)
        if why:
            out(f"SKIP {who}: {why}")
            skipped += 1
            continue
        if not packet["markets"]:
            out(f"SKIP {who}: the packet prices no market, so there is nothing to call")
            skipped += 1
            continue
        if bid in existing and not refresh:
            out(f"SKIP {who}: already published (v{existing[bid]['version']}); frozen unless --refresh")
            skipped += 1
            continue
        unnamed = _unnamed(packet)
        if unnamed and not dry_run:
            out(f"SKIP {who}: the store has no name for fighter {' and '.join(s.upper() for s in unnamed)}, "
                "so a published analysis could not say who is fighting")
            skipped += 1
            continue
        digest = ufc_packet.packet_hash(packet)
        body = ufc_analyst.build_request(packet, cfg)
        est_in = analyst_mod.estimate_tokens(body["system"], body["messages"][0]["content"])
        worst = (est_in * price["input"] + cfg["max_output_tokens"] * price["output"]) / 1e6
        if dry_run:
            chars = len(analyst_mod.packet_json(packet))
            out(f"DRY RUN {who}: packet {digest[:12]} ({chars} characters), {len(packet['slots'])} slots, "
                f"{len(packet['missing'])} missing items, request ~{est_in} input tokens "
                f"(high estimate), worst case ${worst:.2f}; nothing sent, nothing written")
            out("  slots: " + ", ".join(s["slot_id"] for s in packet["slots"]))
            if unnamed:
                out(f"  NOTE: no name is stored for fighter {' and '.join(s.upper() for s in unnamed)}; a real "
                    "run skips this bout until the data store has them")
            if print_request:
                out(json.dumps(body, indent=2, sort_keys=True))
            dry["bouts"] += 1
            dry["slots"] += len(packet["slots"])
            dry["tokens"] += est_in
            dry["worst"] += worst
            continue
        try:
            result = ufc_analyst.analyze(packet, cfg, api_key=key, http_post=http, meter=meter)
            api_failures = 0
        except analyst_mod.SpendCapReached as exc:
            out(f"STOPPED: {exc}. {published} published before the stop; the rest were not analysed.")
            return EXIT_CAP
        except analyst_mod.MalformedOutput as exc:
            out(f"FAIL {who}: the model's answer was rejected after {cfg['max_attempts']} "
                f"attempts: {exc}")
            ufc_ledger.log_usage(date=date, bout_id=bid, run_id=run_id, outcome="rejected_malformed",
                                 model=cfg["model"], usage=exc.usage,
                                 cost_usd=analyst_mod.cost_usd(exc.usage, cfg),
                                 attempts=cfg["max_attempts"], cfg=cfg, now=clock(), path=usage_path)
            failed += 1
            continue
        except analyst_mod.ModelRefused as exc:
            # a completed call, so it was billed: logged like any other spend
            out(f"FAIL {who}: {exc}")
            ufc_ledger.log_usage(date=date, bout_id=bid, run_id=run_id, outcome="model_refused",
                                 model=cfg["model"], usage=exc.usage, cost_usd=exc.cost_usd,
                                 attempts=1, cfg=cfg, now=clock(), path=usage_path)
            failed += 1
            continue
        except analyst_mod.AnalystError as exc:
            out(f"FAIL {who}: {exc}")
            failed += 1
            api_failures += 1
            if api_failures >= MAX_CONSECUTIVE_API_FAILURES:
                out(f"STOPPED: {api_failures} bouts in a row failed at the API; not continuing.")
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
                out(f"NOTE {who}: model critic skipped: {exc}")
            except analyst_mod.AnalystError as exc:
                mc_status = "did not run"
                out(f"NOTE {who}: model critic did not run: {exc}")
        verified = ufc_analyst.verify(packet, result.output, model_critic=verdict_json,
                                      model_critic_status=mc_status)
        try:
            row, created = ufc_ledger.publish(
                packet, verified, now=clock(), model=result.model,
                run={"run_id": run_id, "cost_usd": round(cost, 4), "usage": usage,
                     "attempts": result.attempts, "request_ids": result.request_ids},
                path=store_path, packet_dir=packet_dir, lock_lead_minutes=lead, refresh=refresh)
        except ufc_ledger.UfcLedgerError as exc:
            out(f"REFUSED {who}: {exc}")
            ufc_ledger.log_usage(date=date, bout_id=bid, run_id=run_id, outcome="refused_at_publish",
                                 model=result.model, usage=usage, cost_usd=cost,
                                 attempts=result.attempts, cfg=cfg, now=clock(), path=usage_path)
            skipped += 1
            continue
        ufc_ledger.log_usage(date=date, bout_id=bid, run_id=run_id,
                             outcome="published" if created else "already_published",
                             model=result.model, usage=usage, cost_usd=cost,
                             attempts=result.attempts, cfg=cfg, now=clock(), path=usage_path,
                             extra={"calls": len(verified.calls), "struck": len(verified.struck)})
        out(f"PUBLISHED {who} v{row['version']}: {len(verified.calls)} calls, "
            f"{len(verified.struck)} struck, summary {verified.summary_status}, "
            f"${cost:.3f}, hash {row['row_hash'][:12]}")
        published += 1
    if dry_run:
        cap = cfg["spend_cap"]["max_usd_per_run"]
        out(f"dry run over {dry['bouts']} bout(s) of {len(items)}: {dry['slots']} slots, "
            f"~{dry['tokens']} input tokens, worst case ${dry['worst']:.2f} "
            f"(a run stops at its ${cap:.2f} cap); nothing sent, nothing written")
    else:
        out(f"run {run_id}: {published} published, {skipped} skipped, {failed} failed, "
            f"${meter.spent_usd:.3f} spent of ${meter.max_usd:.2f}")
    return EXIT_ERROR if failed and not published else EXIT_OK


# ---------------------------------------------------------------------------
# grade, record
# ---------------------------------------------------------------------------

def default_results(date: str) -> dict:
    """{bout_id: bout record} from the data layer's store."""
    from src.datasvc.ufc.store import UfcStore

    return UfcStore().bout_by_id()


def execute_grade(date: str, *, results: Optional[Callable] = None,
                  now: Optional[Callable] = None, out: Callable = _print,
                  store_path: Optional[str] = None) -> int:
    bouts = (results or default_results)(date)
    counts = ufc_ledger.grade_date(date, bouts, now=(now or _now)(), path=store_path)
    out(f"analyst grade --sport ufc {date}: published={counts['published']} graded={counts['graded']} "
        f"complete={counts['complete']} unchanged={counts['unchanged']}")
    for note in counts["notes"]:
        out(f"  {note}")
    return EXIT_OK


def execute_record(*, out: Callable = _print, store_path: Optional[str] = None,
                   usage_path: Optional[str] = None, cfg: Optional[Mapping] = None) -> int:
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    rec = ufc_ledger.record(path=store_path, min_graded=cfg["min_graded_for_rates"])
    out(rec["label"])
    out(f"bouts published {rec['bouts_published']}, settled {rec['bouts_settled']}")
    for name, f in rec["families"].items():
        rate = "withheld" if f["win_rate"] is None else f"{f['win_rate'] * 100:.1f}%"
        out(f"  {name:12s} taken {f['taken']} (other side {f['taken_other_side']}), "
            f"passes {f['passes']}, graded {f['graded']} "
            f"(W{f['wins']} L{f['losses']} P{f['pushes']} V{f['voids']}), "
            f"unresolved {f['unresolved']}, win rate {rate}")
    check = ufc_ledger.verify(store_path)
    out(f"ledger: {'OK' if check['ok'] else 'PROBLEM'} ({check['rows']} rows)")
    for problem in check["problems"]:
        out(f"  {problem}")
    usage = ufc_ledger.usage_by_day(usage_path)
    if usage:
        out("cost per day (estimates from the usage the API returned):")
        for day in sorted(usage):
            u = usage[day]
            out(f"  {day}: {u['published']}/{u['games']} bouts published, "
                f"{u['input_tokens']} in / {u['output_tokens']} out tokens, ${u['cost_usd']:.2f}")
    return EXIT_OK if check["ok"] else EXIT_ERROR


def main(args) -> int:
    """Dispatch for `src.analyst.cli.main` when `--sport ufc`."""
    if getattr(args, "game", None):
        _print("--game is for MLB (AWAY@HOME); for UFC use --event ID")
        return EXIT_ERROR
    if args.analyst_command == "run":
        return execute_run(args.date, event=getattr(args, "event", None), dry_run=args.dry_run,
                           print_request=args.print_request, refresh=args.refresh,
                           use_model_critic=True if args.model_critic else None)
    if args.analyst_command == "grade":
        return execute_grade(args.date)
    return execute_record()
