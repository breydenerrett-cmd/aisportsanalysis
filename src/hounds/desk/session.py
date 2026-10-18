"""The session runner: what a parent Claude Code session hands to subagents, and how answers come back.

THE LOOP A PARENT RUNS (docs/BRIEF_RUNBOOK.md, "Desk and persona hounds")
-------------------------------------------------------------------------
    prepare       once per game (at most 2 games a run)
    session-plan  writes every ready request file and prints the jobs: one request, one subagent
    ...           the parent starts one FOREGROUND Sonnet subagent per job, all of a wave in one message;
                  each reads only its request file and writes only its answer file
    session-check records every answer file present as an attempt, runs the checker, prints rejections
    ...           repeat plan / subagents / check until `session-plan` says every stage is final
    publish       writes the bets, the transcript and the disagreement table
    session-status  shows where everything stands at any time

WHY A PLAN STEP AND A CHECK STEP INSTEAD OF A RUNNER THAT CALLS MODELS
----------------------------------------------------------------------
No API key exists and none is used: the parent session spawns the subagents (the same arrangement as
src/analyst/pilot.py and docs/BRIEF_RUNBOOK.md). This module only prepares files, reads files and prints
instructions. It calls no model, opens no socket and starts no process.

THE CAPS (pre-registered, enforced here)
----------------------------------------
* at most `state.MAX_GAMES_PER_RUN` games (2): the earliest two open games; the rest are listed as deferred;
* at most `state.MAX_ANSWERS_PER_RUN` subagent answers (30) over the run, counting every attempt already
  recorded for the selected games plus the jobs just planned. A Desk game is 7 requests, a persona set is 6,
  so two games are 26 answers and leave 4 re-answers; a plan that would pass 30 is cut in wave order and
  says what it left out.

WHAT THE SUBAGENT IS TOLD
-------------------------
Only to read one file and write one file. It is given no hint about which way to lean, and a re-answer's
only extra input is the checker's rejection lines, which are already inside its request file.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.analyst import cli, config as config_mod, ledger as analyst_ledger, pilot
from src.hounds.desk import checks, ledger, roles, state

SUBAGENT_PROMPT = (
    "Read only the file {request}. It is a request: its `system` field is your instructions and its "
    "`messages[0].content` is the data and the task. Answer exactly as it instructs, as one JSON object that "
    "matches `output_config.format.schema`. Write ONLY that JSON object (no markdown, no commentary) to the "
    "file {answer}. Use no other file, no search, no tool other than reading that one file and writing that "
    "one file, and no knowledge from outside the request. Reply \"done\" when the file is written.")

# The packet is valid for 90 minutes at publish; a plan warns once this many minutes of it are gone, so a
# parent that is slow knows to stop starting waves.
PACKET_AGE_WARN_MINUTES = 60


def _age_minutes(game: "state.Game", moment: datetime) -> Optional[float]:
    built = analyst_ledger._utc(game.meta.get("built_at"))
    return None if built is None else (moment - built).total_seconds() / 60.0


def select_games(date: str, moment: datetime, root: Optional[Path] = None, only: Optional[str] = None) -> tuple:
    """`(selected, deferred, notes)`: the open games of `date`, earliest first, cut at the games cap."""
    all_rows = ledger.rows(root)
    every = {h["id"] for h in roles.HOUNDS}
    open_games, notes = [], []
    for game in state.games_for_date(date, root):
        if only and f"{game.meta['away']}@{game.meta['home']}".upper() != only.upper():
            continue
        start = analyst_ledger._utc(game.meta.get("start_utc"))
        if start is not None and moment >= start:
            notes.append(f"{game.game_id}: started at {game.meta.get('start_utc')}; nothing can be published")
            continue
        if every <= ledger.published_hounds(all_rows, game.game_id):
            notes.append(f"{game.game_id}: every hound is published")
            continue
        open_games.append(game)
    return open_games[:state.MAX_GAMES_PER_RUN], open_games[state.MAX_GAMES_PER_RUN:], notes


def answer_present(game: "state.Game", stage: str, attempt: int) -> bool:
    return game.answer_file(stage, attempt).exists()


def plan(date: str, *, cfg: Optional[Mapping] = None, now: Optional[Callable] = None,
         out: Callable = print, root: Optional[Path] = None, only: Optional[str] = None) -> dict:
    """Write every ready request and print the jobs. Returns {"jobs": [...], "unchecked": [...],
    "final": bool, "selected": [...]} for the caller and the tests."""
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    moment = (now or cli._now)()
    selected, deferred, notes = select_games(date, moment, root, only)
    result = {"jobs": [], "unchecked": [], "final": False, "selected": selected, "deferred": deferred}
    out(f"SESSION PLAN {date}: {len(selected)} open game(s)"
        + (f", {len(deferred)} deferred (a run is at most {state.MAX_GAMES_PER_RUN} games)" if deferred else ""))
    for note in notes:
        out(f"  note: {note}")
    for g in deferred:
        out(f"  deferred: {g.game_id} ({g.meta['away']}@{g.meta['home']}); plan it in the next run")
    if not selected:
        out("  nothing to do: there is no open prepared game for this date. Run `prepare` first.")
        return result
    used = sum(state.attempts_recorded(g) for g in selected)
    budget = state.MAX_ANSWERS_PER_RUN - used
    out(f"  answers used so far {used} of {state.MAX_ANSWERS_PER_RUN}")
    for g in selected:
        age = _age_minutes(g, moment)
        flag = f"; packet built {age:.0f} min ago" + (" (publish needs it within 90)" if age and age >= PACKET_AGE_WARN_MINUTES else "") \
            if age is not None else ""
        out(f"  game {g.game_id} {g.meta['away']}@{g.meta['home']} starts {g.meta.get('start_utc')}"
            + (" [REHEARSAL: cannot be published]" if g.meta.get("rehearsal") else "") + flag)

    candidates = []
    for stage in roles.WAVE_ORDER:
        for g in selected:
            st = g.state(stage)
            if st["state"] != state.TODO:
                continue
            n = st["next_attempt"]
            if answer_present(g, stage, n):
                result["unchecked"].append({"game": g, "stage": stage, "attempt": n})
                continue
            request = g.ensure_request(stage, cfg)
            candidates.append({"game": g, "stage": stage, "attempt": n, "request": request,
                               "answer": g.answer_file(stage, n)})
    cut = candidates[max(budget, 0):]
    jobs = candidates[:max(budget, 0)]
    result["jobs"] = jobs

    if result["unchecked"]:
        out("ANSWER FILES WAITING TO BE CHECKED (run session-check): "
            + ", ".join(f"{u['game'].game_id}:{u['stage']}_a{u['attempt']}" for u in result["unchecked"]))
    if jobs:
        out(f"JOBS: {len(jobs)}. One foreground Sonnet subagent per job; start the jobs of a wave together.")
        for i, job in enumerate(jobs, 1):
            g, stage = job["game"], job["stage"]
            role = roles.ROLES[stage]
            est = g.meta.get("token_estimates", {}).get("stages", {}).get(stage, {}).get("input")
            wave = 1 if not role.needs else (2 if stage in ("bull", "bear") else 3)
            out(f"  JOB {i}: {g.game_id} {stage} (wave {wave}, attempt {job['attempt']} of "
                f"{state.MAX_ATTEMPTS}{', ~%d tokens in' % est if est else ''})")
            out(f"    request: {job['request']}")
            out(f"    answer:  {job['answer']}")
        out("SUBAGENT PROMPT (fill in the two paths for each job):")
        out("  " + SUBAGENT_PROMPT.format(request="<request>", answer="<answer>"))
    if cut:
        out(f"CUT BY THE ANSWER CAP: {len(cut)} job(s) left out so the run stays at "
            f"{state.MAX_ANSWERS_PER_RUN} answers: "
            + ", ".join(f"{c['game'].game_id}:{c['stage']}" for c in cut))

    finals = all(g.state(s)["state"] in state.FINAL for g in selected for s in roles.ALL_STAGES)
    blocked = [(g.game_id, s) for g in selected for s in roles.ALL_STAGES
               if g.state(s)["state"] == state.BLOCKED]
    result["final"] = finals
    if finals:
        out("EVERY STAGE IS FINAL. Next: python -m src.hounds.desk publish --date " + date
            + " --model <model id of the subagents>")
    elif not jobs and not result["unchecked"] and not cut:
        out(f"waiting on stages that are not final: {blocked[:6]}")
    elif jobs or result["unchecked"]:
        out("NEXT: when the subagents are done, run: python -m src.hounds.desk session-check --date " + date
            + "; then run session-plan again (later waves and re-answers appear as earlier ones finish).")
    return result


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def _unreadable(raw: bytes, why: str) -> tuple:
    """A response the checker cannot read is a rejected attempt, not a refusal: it is an answer, it earned
    its attempt, and the rejection line says what was wrong."""
    return {"unreadable": True, "sha256": hashlib.sha256(raw).hexdigest()}, \
        pilot.CheckReport(shape_errors=[why])


def check_answer(game: "state.Game", stage: str, response_path, *, now: Optional[Callable] = None,
                 out: Callable = print) -> str:
    """Record one answer file as an attempt and print the check. Returns "recorded", "already recorded"
    or "refused"."""
    role = roles.ROLES[stage]
    st = game.state(stage)
    moment = (now or cli._now)()
    try:
        raw = pilot.read_response_bytes(str(response_path))
    except pilot.PilotError as exc:
        out(f"ERROR {game.game_id} {stage}: {exc}")
        return "refused"
    first_hash = game.first_request_hash(stage)
    try:
        response = pilot.parse_response(raw)
        parsed = True
    except pilot.PilotError as exc:
        response, report_for_bad = _unreadable(raw, str(exc))
        parsed = False
    if first_hash is not None:
        for row in pilot.read_attempts(game.stage_dir(stage), first_hash):
            if row.get("sha256") == pilot._sha256(raw) or (parsed and row.get("content_sha256")
                                                          == pilot._content_sha256(response)):
                out(f"{game.game_id} {stage}: attempt {row['attempt']} of {state.MAX_ATTEMPTS}: this answer "
                    "was already recorded; it counts once")
                return "already recorded"
    if st["state"] != state.TODO:
        why = {"blocked": f"it waits for {st.get('waiting_for')}",
               "clean": "its latest attempt was not rejected, so another answer is a reroll",
               "exhausted": f"{state.MAX_ATTEMPTS} attempts are recorded"}[st["state"]]
        out(f"REFUSED {game.game_id} {stage}: this stage cannot take an answer now: {why}. The file is left "
            "where it is and is not recorded.")
        return "refused"
    if first_hash is None or not game.request_file(stage, st["next_attempt"]).exists():
        out(f"REFUSED {game.game_id} {stage}: no request has been written for attempt {st['next_attempt']}; "
            "run session-plan first")
        return "refused"
    stage_check = (checks.StageCheck(report=report_for_bad) if not parsed
                   else checks.check_stage(game.packet, response, role))
    out(f"CHECK {game.game_id} {stage} (attempt {st['next_attempt']}): nothing is published by this command")
    checks.print_check(stage_check, out)
    stage_dir = game.stage_dir(stage)
    stage_dir.mkdir(parents=True, exist_ok=True)
    row, is_new = pilot.record_attempt(stage_dir, first_hash, raw, response, stage_check.report, moment)
    pilot.print_attempt(row, is_new, out)
    return "recorded"


def check_all(date: str, *, now: Optional[Callable] = None, out: Callable = print,
              root: Optional[Path] = None, only: Optional[str] = None) -> int:
    """Check every answer file waiting for a stage's next attempt, across the selected games. Stages are
    visited in wave order, so an answer that finalises an upstream stage is recorded before a downstream
    stage's answer is considered. Returns how many answers were recorded."""
    moment = (now or cli._now)()
    selected, _deferred, _notes = select_games(date, moment, root, only)
    recorded = 0
    if not selected:
        out(f"no open prepared game for {date}")
        return 0
    for stage in roles.WAVE_ORDER:
        for g in selected:
            st = g.state(stage)
            if st["state"] != state.TODO:
                continue
            n = st["next_attempt"]
            if answer_present(g, stage, n):
                if check_answer(g, stage, g.answer_file(stage, n), now=now, out=out) == "recorded":
                    recorded += 1
    out(f"recorded {recorded} answer(s). Run session-plan for what comes next.")
    return recorded


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def status_rows(game: "state.Game") -> list:
    rows = []
    for stage in roles.ALL_STAGES:
        st = game.state(stage)
        last = st.get("last") or {}
        rows.append({
            "stage": stage, "state": st["state"], "attempts": st["attempts"],
            "kept": last.get("kept"), "struck": last.get("struck"),
            "rejected": bool(last.get("rejected")) if last else None,
            "waiting_for": st.get("waiting_for"),
            "answer_waiting": (st["state"] == state.TODO and answer_present(game, stage, st["next_attempt"])),
        })
    return rows


def status(date: str, *, now: Optional[Callable] = None, out: Callable = print,
           root: Optional[Path] = None) -> dict:
    """Print answered / checked / published for every prepared game of `date`."""
    moment = (now or cli._now)()
    games = state.games_for_date(date, root)
    all_rows = ledger.rows(root)
    bets = [r for r in all_rows if r.get("kind") == ledger.KIND_BET]
    summary = {"games": []}
    out(f"SESSION STATUS {date}: {len(games)} prepared game(s); ledger {ledger.path(root)} "
        f"({len(all_rows)} rows)")
    for g in games:
        age = _age_minutes(g, moment)
        pub = ledger.published_hounds(all_rows, g.game_id)
        out(f"game {g.game_id} {g.meta['away']}@{g.meta['home']} ({g.meta.get('sport', 'mlb')}) starts "
            f"{g.meta.get('start_utc')}" + (f"; packet {age:.0f} min old" if age is not None else "")
            + ("; REHEARSAL" if g.meta.get("rehearsal") else ""))
        for r in status_rows(g):
            mark = {"clean": "checked, clean", "exhausted": "checked, rejected, no attempts left",
                    "todo": ("answered, waiting to be checked" if r["answer_waiting"] else
                             ("rejected, answer again" if r["rejected"] else "waiting for an answer")),
                    "blocked": f"blocked on {r['waiting_for']}"}[r["state"]]
            counts = f" kept {r['kept']} struck {r['struck']}" if r["kept"] is not None else ""
            out(f"  {r['stage']:<18} attempts {r['attempts']}/{state.MAX_ATTEMPTS}  {mark}{counts}")
        mine = [b for b in bets if b.get("game_id") == g.game_id]
        out(f"  published hounds: {', '.join(sorted(pub)) or 'none'}; TAKEs on the ledger: {len(mine)}")
        summary["games"].append({"game_id": g.game_id, "rows": status_rows(g), "published": sorted(pub),
                                 "bets": len(mine)})
    chain = ledger.verify(root)
    out(f"ledger chain: {'ok' if chain.ok else 'BROKEN at line %s: %s' % (chain.broken_at_line, chain.reason)}"
        f" ({chain.rows_checked} rows)")
    summary["chain_ok"] = chain.ok
    return summary
