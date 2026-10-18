"""Champion / challenger for the AI analyst's brief prompt (docs/PREREG_LEARNING_LOOP.md section 12).

THE SAME STRUCTURE AS THE HOUNDS, ON THE ANALYST'S PROMPT TEXT
--------------------------------------------------------------
The MLB brief prompt (``analyst.SYSTEM_PROMPT``, ``PROMPT_VERSION``) is the CHAMPION. A coach may PROPOSE
a challenger: a whole alternative prompt text, a written hypothesis, and the evidence it read. The
challenger runs in SHADOW on the champion's own FROZEN packets, game by game: same packet, same game,
the answer saved to a challenger store and never published, never shown. It is promoted only by the
same referee (``src/hounds/learning/referee.py``) on GRADED calls: paired by game, the value of a game is
the paper units of its TAKE calls at their published prices (a PASS is 0), looks at 150, 225, 300, 375
and 450 paired games, the same alpha spending, the same monthly Benjamini-Hochberg family as every
other challenger, one live analyst challenger at a time. A promotion changes which prompt text the next
run uses, as a new prompt version; the champion's published rows are never touched.

NO MODEL CALL HAPPENS HERE UNLESS YOU TYPE ``shadow --confirm-spend``. ``propose``, ``grade``,
``referee`` and ``status`` never call a model. ``shadow`` without the flag (or with ``--dry-run``) builds
and prices the requests and sends nothing. The shadow run goes through ``analyst.analyze`` (the spend
cap, the schema, the retries), ``critic.verify`` (the same deterministic checker the champion's answer
passes) and ``ledger.publish`` (which refuses a game that has started), so a challenger's answer is
produced under exactly the champion's rules and is only ever written to its own store.

WHERE THINGS LIVE
-----------------
  the prompt text      evidence/analyst_prompts/<sha256[:16]>.txt   (content addressed; never overwritten)
  the challenger store evidence/analyst_prompt_challengers/<challenger id>/{analyst_v1.jsonl, usage.jsonl, packets/}
  proposals, looks, promotions   the house scope's learning ledger (``kind: "analyst"``)

Only MLB is covered. The NFL and UFC analysts have their own prompts and ledgers and are not wired in.

    python -m src.analyst.prompt_arm status
    python -m src.analyst.prompt_arm propose --prompt-file p.txt --hypothesis "..." --evidence a,b
    python -m src.analyst.prompt_arm shadow --date 2026-11-02 [--dry-run | --confirm-spend]
    python -m src.analyst.prompt_arm grade --date 2026-11-02
    python -m src.analyst.prompt_arm referee
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from src import paths
from src.analyst import analyst as analyst_mod
from src.analyst import config as config_mod
from src.analyst import critic
from src.analyst import ledger as analyst_ledger
from src.hounds.learning import ledger as L
from src.hounds.learning import pairing, pause, proposals, rules
from src.hounds.learning.referee import Referee

SPORT = "mlb"
HOUND_ID = "analyst_prompt:mlb"
CATEGORY = "analyst"
PROMPT_DIR = Path("evidence") / "analyst_prompts"
CHALLENGER_DIR = Path("evidence") / "analyst_prompt_challengers"
MIN_GRADED_GAMES = 50                  # the champion prompt's own record must exist first (as for hounds)
PROMPT_MIN_CHARS, PROMPT_MAX_CHARS = 500, 60000
REQUIRED_PHRASES = ("TAKE_OTHER_SIDE", "-200", "Reply with one JSON object")
SIMILAR_RATIO = 0.98                   # a challenger this close to the champion (or a recent loser) is a repeat
EXIT_OK, EXIT_REFUSED, EXIT_BLOCKED = 0, 1, 3


# ---- prompt files ---------------------------------------------------------------------------------------

def sha_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_prompt(text: str, root: Optional[Path] = None) -> tuple:
    """Write the prompt content-addressed; returns ``(sha256, repo-relative path)``. Never overwrites a
    different text (a hash collision is not a thing here, but a truncated write would be)."""
    base = Path(root) if root is not None else paths.repo_root()
    sha = sha_of(text)
    rel = PROMPT_DIR / f"{sha[:16]}.txt"
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_text(encoding="utf-8") != text:
            raise ValueError(f"{rel} exists with different content")
    else:
        target.write_text(text, encoding="utf-8")
    return sha, rel.as_posix()


def read_prompt(spec: Mapping, root: Optional[Path] = None) -> str:
    """The text a challenger or a promotion names, verified against its hash. Raises, never guesses."""
    base = Path(root) if root is not None else paths.repo_root()
    text = (base / spec["prompt_file"]).read_text(encoding="utf-8")
    if sha_of(text) != spec["sha256"]:
        raise ValueError(f"{spec['prompt_file']} is not the prompt whose hash was recorded")
    return text


# ---- the champion --------------------------------------------------------------------------------------------

def champion(sport: str = SPORT, *, scope: Optional[L.Scope] = None, root: Optional[Path] = None) -> tuple:
    """``(prompt text, prompt_version or None)``. With no promotion on record this is the shipped prompt
    and ``None`` (the row then carries ``analyst.PROMPT_VERSION`` exactly as it always has). After a
    promotion, the promoted text and a version label naming the challenger that earned it. A promoted
    prompt whose file is missing or altered RAISES: a run must never publish under the wrong prompt."""
    scope = scope or L.Scope.house(Path(root) / "evidence" if root is not None else None)
    try:
        state = L.read_state(scope)
    except Exception:  # noqa: BLE001 -- see below
        # An unreadable registry cannot tell us a prompt was promoted; the run proceeds with the shipped
        # prompt and its rows say so (PROMPT_VERSION). `verify` and the scorecard report the broken chain.
        return analyst_mod.SYSTEM_PROMPT, None
    promos = state.promotions_for(HOUND_ID)
    if not promos or sport != SPORT:
        return analyst_mod.SYSTEM_PROMPT, None
    last = max(promos, key=lambda p: int(p["to_version"]))
    spec = last["prompt"]
    return read_prompt(spec, root), f"{analyst_mod.PROMPT_VERSION}+{last['challenger_id']}"


def champion_sha(state: L.State, root: Optional[Path] = None) -> str:
    promos = state.promotions_for(HOUND_ID)
    if promos:
        return max(promos, key=lambda p: int(p["to_version"]))["prompt"]["sha256"]
    return sha_of(analyst_mod.SYSTEM_PROMPT)


def champion_text(state: L.State, root: Optional[Path] = None) -> str:
    promos = state.promotions_for(HOUND_ID)
    if promos:
        return read_prompt(max(promos, key=lambda p: int(p["to_version"]))["prompt"], root)
    return analyst_mod.SYSTEM_PROMPT


# ---- proposing -------------------------------------------------------------------------------------------------

def _similar(a: str, b: str) -> bool:
    if a == b:
        return True
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return m.quick_ratio() >= SIMILAR_RATIO and m.ratio() >= SIMILAR_RATIO


def graded_games(store: Optional[str], prompt_version: Optional[str]) -> int:
    """Games published under the champion prompt that have a graded row."""
    rows = analyst_ledger.rows(store)
    graded = analyst_ledger.latest_graded(rows)
    want = prompt_version or analyst_mod.PROMPT_VERSION
    return sum(1 for pub in analyst_ledger.latest_published(rows).values()
               if pub.get("prompt_version") == want and pub["row_hash"] in graded)


def propose(scope: L.Scope, prompt_text: str, hypothesis, evidence, *, graded: int, coach_on: bool,
            now: datetime, root: Optional[Path] = None, proposed_by: str = "coach") -> L.Challenger:
    """Create an analyst-prompt challenger, under the same guards as a hound's (prereg section 3) plus
    the arm's own: one live at a time, the prompt must keep the structural phrases the schema and the
    checker rely on, and it may not be a near-copy of the champion, a live challenger or a recent loser."""
    try:
        proposals._switch_guard(scope, coach_on=coach_on)
        state = L.read_state(scope)
        proposals._record_and_rate_guard(state, graded=graded, lineage_key=HOUND_ID, now=now)
        if len([c for c in state.live() if c.kind == "analyst"]) >= rules.ANALYST_MAX_LIVE:
            raise proposals.ProposalError("too_many_live", "one analyst prompt challenger may be live at a time", 409)
        if len(state.live()) >= rules.MAX_LIVE_PER_SCOPE:
            raise proposals.ProposalError("system_full", f"the scope already has {rules.MAX_LIVE_PER_SCOPE} live challengers", 409)
        text = proposals.clean_text(hypothesis, "hypothesis", rules.HYPOTHESIS_MIN, rules.HYPOTHESIS_MAX)
        refs = proposals.clean_evidence(evidence)
        if not isinstance(prompt_text, str) or not PROMPT_MIN_CHARS <= len(prompt_text) <= PROMPT_MAX_CHARS:
            raise proposals.ProposalError("bad_prompt", f"the prompt must be {PROMPT_MIN_CHARS} to {PROMPT_MAX_CHARS} characters", 422)
        missing = [p for p in REQUIRED_PHRASES if p not in prompt_text]
        if missing:
            raise proposals.ProposalError("bad_prompt", f"the prompt must keep these phrases the checker relies on: {missing}", 422)
        champ_text = champion_text(state, root)
        if _similar(prompt_text, champ_text):
            raise proposals.ProposalError("near_duplicate", "this prompt is the champion's, or too close to it, to be a challenger", 409)
        for c in state.live():
            if c.kind == "analyst" and c.spec.get("sha256") == sha_of(prompt_text):
                raise proposals.ProposalError("near_duplicate", f"this is the live challenger {c.id}", 409)
        for c in proposals.retired_recent(state, HOUND_ID, now):
            try:
                lost = read_prompt(c.spec, root)
            except (OSError, ValueError, KeyError):
                lost = None
            if c.spec.get("sha256") == sha_of(prompt_text) or (lost is not None and _similar(prompt_text, lost)):
                raise proposals.ProposalError("retired_repeat", f"too close to challenger {c.id}, retired {c.ended_utc[:10]} "
                                              f"({c.outcome_reason})", 409)
    except proposals.ProposalError as exc:
        proposals._record_refusal(scope, exc, hound_id=HOUND_ID, lineage_key=HOUND_ID, now=now, proposed_by=proposed_by)
        raise
    sha, rel = store_prompt(prompt_text, root)
    spec = {"sha256": sha, "prompt_file": rel, "chars": len(prompt_text), "sport": SPORT}
    diff = {"prompt": [champion_sha(state)[:12], sha[:12]]}
    return proposals._make(scope, kind="analyst", hound_id=HOUND_ID, lineage_key=HOUND_ID, category=CATEGORY,
                           parent_version=state.champion_version(HOUND_ID), parent_ref=None, spec=spec,
                           spec_hash=sha, spec_diff=diff, hypothesis=text, evidence=refs, now=now,
                           proposed_by=proposed_by)


# ---- the challenger's store ---------------------------------------------------------------------------------------

def challenger_paths(cid: str, root: Optional[Path] = None) -> dict:
    base = (Path(root) if root is not None else paths.repo_root()) / CHALLENGER_DIR / cid
    return {"store": str(base / "analyst_v1.jsonl"), "usage": str(base / "usage.jsonl"),
            "packets": str(base / "packets")}


# ---- shadow running (the only step that can call a model) ----------------------------------------------------------------

def shadow_date(date: str, scope: L.Scope, *, now: datetime, cfg: Mapping, key: Optional[str],
                champion_store: Optional[str] = None, dry_run: bool = False, root: Optional[Path] = None,
                http_post=None, analyze: Optional[Callable] = None, out: Callable = print) -> dict:
    """Answer the champion's frozen packets of ``date`` under the live challenger's prompt, into the
    challenger's own store. ``analyze`` is the seam tests replace with a fake; the default is
    ``analyst.analyze`` (spend cap, schema, retries). Nothing is published anywhere else."""
    state = L.read_state(scope)
    live = [c for c in state.live() if c.kind == "analyst"]
    report = {"date": date, "challengers": len(live), "answered": 0, "skipped": 0, "failed": 0, "dry_run": dry_run}
    if not live:
        out("no live analyst prompt challenger")
        return report
    c = live[0]
    prompt = read_prompt(c.spec, root)
    cpaths = challenger_paths(c.id, root)
    mine = analyst_ledger.latest_published(analyst_ledger.rows(cpaths["store"]))
    meter = analyst_mod.SpendMeter.from_config(cfg)
    run_id = uuid.uuid4().hex[:12]
    lead = float(cfg["lock_lead_minutes"])
    analyze = analyze or analyst_mod.analyze
    for gid, pub in sorted(analyst_ledger.latest_published(analyst_ledger.rows(champion_store)).items()):
        if pub["date"] != date or gid in mine:
            continue
        try:
            packet = analyst_ledger.read_packet(pub, root=root)
        except Exception as exc:  # noqa: BLE001 -- a missing frozen packet is skipped, never rebuilt
            out(f"SKIP {gid}: the champion's frozen packet cannot be read ({type(exc).__name__})")
            report["skipped"] += 1
            continue
        why = analyst_ledger.publish_refusal(packet, now, lead)
        if why:
            out(f"SKIP {gid}: {why}")
            report["skipped"] += 1
            continue
        if dry_run:
            body = analyst_mod.build_request(packet, cfg, system_prompt=prompt)
            est = analyst_mod.estimate_tokens(body["system"], body["messages"][0]["content"])
            out(f"DRY RUN {gid}: challenger {c.id}, request ~{est} input tokens; nothing sent, nothing written")
            continue
        try:
            result = analyze(packet, cfg, api_key=key, http_post=http_post or analyst_mod.urllib_post,
                             meter=meter, system_prompt=prompt)
        except analyst_mod.SpendCapReached as exc:
            out(f"STOPPED: {exc}")
            break
        except analyst_mod.AnalystError as exc:
            out(f"FAIL {gid}: {exc}")
            report["failed"] += 1
            continue
        verified = critic.verify(packet, result.output)
        try:
            row, _created = analyst_ledger.publish(
                packet, verified, now=now, model=result.model,
                run={"run_id": run_id, "cost_usd": round(result.cost_usd, 4), "usage": dict(result.usage),
                     "attempts": result.attempts, "request_ids": result.request_ids},
                path=cpaths["store"], packet_dir=cpaths["packets"], lock_lead_minutes=lead,
                prompt_version=f"challenger:{c.id}", system_prompt=prompt,
                extra={"role": rules.ROLE_CHALLENGER, "challenger_id": c.id, "arm": "C",
                       "parent_prompt_version": c.parent_version, "champion_row_hash": pub["row_hash"]})
        except analyst_ledger.AnalystLedgerError as exc:
            out(f"REFUSED {gid}: {exc}")
            report["skipped"] += 1
            continue
        analyst_ledger.log_usage(path=cpaths["usage"], date=date, game_id=gid, run_id=run_id, outcome="published",
                                 model=result.model, usage=result.usage, cost_usd=result.cost_usd,
                                 attempts=result.attempts, cfg=cfg, now=now, extra={"challenger_id": c.id})
        out(f"ANSWERED {gid} under challenger {c.id}: {len(verified.calls)} calls, saved to the challenger store only")
        report["answered"] += 1
    return report


def grade_date(date: str, scope: L.Scope, *, now: datetime, results: Optional[Callable] = None,
               root: Optional[Path] = None, out: Callable = print) -> dict:
    """Grade the live challengers' stored answers with the champion's own grader. No model call."""
    from src.analyst import cli as analyst_cli
    by_pk, box = (results or analyst_cli.default_results)(date)
    state = L.read_state(scope)
    report = {}
    for c in [x for x in state.challengers.values() if x.kind == "analyst"]:
        p = challenger_paths(c.id, root)
        if not Path(p["store"]).exists():
            continue
        report[c.id] = analyst_ledger.grade_date(date, by_pk, box, now=now, path=p["store"])
        out(f"graded {c.id} {date}: {report[c.id]['graded']} graded, {report[c.id]['complete']} complete")
    return report


# ---- the referee's view: paired games -----------------------------------------------------------------------------------------

def game_value(pub: Mapping, graded: Optional[Mapping], corrections: Mapping) -> Optional[float]:
    """Paper units of a game's TAKE calls at their published prices; None when it made no TAKE (a
    PASS-only game is 0 in the pair). Unresolved and void calls add 0."""
    calls = analyst_ledger.effective_calls(graded, corrections)
    total, takes = 0.0, 0
    for call in pub.get("calls") or []:
        if call.get("verdict") not in ("TAKE", "TAKE_OTHER_SIDE"):
            continue
        takes += 1
        g = calls.get(call["slot_id"]) or {}
        if g.get("result") in ("WIN", "LOSS", "PUSH"):
            total += float(g.get("profit_units") or 0.0)
    return round(total, 4) if takes else None


def pairing_for(c: L.Challenger, state: L.State, *, champion_store: Optional[str] = None,
                root: Optional[Path] = None) -> pairing.Pairing:
    """Paired games of the champion prompt and a challenger: both published and both GRADED COMPLETE.
    A game the challenger never answered is uncovered (excluded, not a free pass); a game not yet fully
    graded is pending and the prefix stops before it, so 'the first n games' never change."""
    champ_rows = analyst_ledger.rows(champion_store)
    chall_rows = analyst_ledger.rows(challenger_paths(c.id, root)["store"])
    champ_pubs, chall_pubs = analyst_ledger.latest_published(champ_rows), analyst_ledger.latest_published(chall_rows)
    champ_graded, chall_graded = analyst_ledger.latest_graded(champ_rows), analyst_ledger.latest_graded(chall_rows)
    champ_corr, chall_corr = analyst_ledger.corrections_for(champ_rows), analyst_ledger.corrections_for(chall_rows)
    since = L.parse(c.created_utc)
    out = pairing.Pairing()
    final, pending_locks = [], []
    for gid, cp in champ_pubs.items():
        first_pitch = cp.get("first_pitch_utc") or ""
        started = L.parse(first_pitch)
        if started is None or since is None or started < since:
            continue
        hp = chall_pubs.get(gid)
        if hp is None:
            out.uncovered += 1
            continue
        cg, hg = champ_graded.get(cp["row_hash"]), chall_graded.get(hp["row_hash"])
        if not (cg and cg.get("complete") and hg and hg.get("complete")):
            pending_locks.append(first_pitch)
            out.pending += 1
            continue
        cv, hv = game_value(cp, cg, champ_corr), game_value(hp, hg, chall_corr)
        if cv is None and hv is None:
            continue                                  # both passed: not a slot
        final.append(pairing.Slot(event_id=gid, market="game", date=str(cp["date"])[:10], lock=first_pitch,
                                  champ=cv, chall=hv, diff=(hv or 0.0) - (cv or 0.0)))
    final.sort(key=lambda s: (s.lock, s.event_id))
    if pending_locks:
        cut = min(pending_locks)
        kept = [s for s in final if s.lock < cut]
        out.after_cut = len(final) - len(kept)
        final = kept
    out.slots = final
    return out


def run_referee(scope: L.Scope, *, now: datetime, champion_store: Optional[str] = None,
                root: Optional[Path] = None) -> dict:
    return Referee(scope, now=now, pairing_for=lambda c, st: pairing_for(c, st, champion_store=champion_store, root=root),
                   kinds=("analyst",)).run()


# ---- CLI ---------------------------------------------------------------------------------------------------------------------

def _scope(args) -> L.Scope:
    return L.Scope.house(Path(args.root) / "evidence" if args.root else None)


def _now(args) -> datetime:
    return L.parse(args.now) if args.now else L.utc_now()


def _coach_on(args) -> bool:
    cfg = Path(args.coach_config) if args.coach_config else pause.config_path()
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("enabled") is True


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.analyst.prompt_arm", description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="repository root for evidence/ (testing seam)")
    ap.add_argument("--coach-config", help="the kill-switch file (testing seam)")
    ap.add_argument("--now", help="the clock, ISO UTC (testing seam)")
    ap.add_argument("--store", help="the champion's analyst ledger (testing seam)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("propose")
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--evidence", required=True)
    p = sub.add_parser("shadow")
    p.add_argument("--date", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--confirm-spend", action="store_true",
                   help="actually call the model (spends money, capped by config/analyst.json)")
    p = sub.add_parser("grade")
    p.add_argument("--date", required=True)
    sub.add_parser("referee")
    args = ap.parse_args(argv)
    scope, now = _scope(args), _now(args)
    root = Path(args.root) if args.root else None

    if args.cmd == "status":
        st = L.read_state(scope)
        text, version = champion(scope=scope, root=root)
        print(json.dumps({"champion_prompt": version or analyst_mod.PROMPT_VERSION, "chars": len(text),
                          "live": [c.to_json() for c in st.live() if c.kind == "analyst"],
                          "promotions": [p for p in st.promotions if p.get("kind_of") == "analyst"]},
                         indent=1, sort_keys=True, default=str))
        return EXIT_OK
    if args.cmd == "propose":
        text = Path(args.prompt_file).read_text(encoding="utf-8")
        state = L.read_state(scope)
        _t, version = champion(scope=scope, root=root)
        try:
            c = propose(scope, text, args.hypothesis, [e.strip() for e in args.evidence.split(",") if e.strip()],
                        graded=graded_games(args.store, version), coach_on=_coach_on(args), now=now, root=root)
        except proposals.ProposalError as exc:
            print(json.dumps({"accepted": False, "code": exc.code, "message": str(exc)}))
            return EXIT_REFUSED
        print(json.dumps({"accepted": True, "challenger": c.to_json()}, indent=1, sort_keys=True))
        return EXIT_OK
    if args.cmd == "shadow":
        cfg = config_mod.load()
        key = config_mod.api_key(None)
        dry = args.dry_run or not args.confirm_spend
        if not dry and not key:
            print(f"BLOCKED: {config_mod.ENV_KEY} is not set; nothing was sent.")
            return EXIT_BLOCKED
        if dry and not args.dry_run:
            print("No --confirm-spend: running as a dry run (nothing is sent to a model).")
        print(json.dumps(shadow_date(args.date, scope, now=now, cfg=cfg, key=key, champion_store=args.store,
                                     dry_run=dry, root=root)))
        return EXIT_OK
    if args.cmd == "grade":
        grade_date(args.date, scope, now=now, root=root)
        return EXIT_OK
    if args.cmd == "referee":
        print(json.dumps(run_referee(scope, now=now, champion_store=args.store, root=root), sort_keys=True))
        return EXIT_OK
    return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
