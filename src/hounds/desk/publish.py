"""`publish`: turn a game's final stages into ledger rows, a transcript and a disagreement table.

WHAT A PUBLISH REFUSES (the analyst pilot's list, plus two)
-----------------------------------------------------------
* a rehearsal folder (`prepare --rehearsal`);
* a game that has started or whose start is unknown (`analyst.ledger.publish_refusal`, the one place that
  rule lives), and a packet built more than `pilot.max_packet_age_minutes` (90) before now;
* a game prepared under a prompt, schema or role text that has changed since (`prepare.json` holds every
  role's hash);
* a hound already published for the game (frozen; there is no refresh);
* a stage whose recorded attempts break the publication rule (`pilot.publication_refusal`: an attempt file
  that is not the bytes that were hashed, a reroll after a clean attempt, a fourth attempt). A hound whose
  decision stage is not final yet is SKIPPED, not published, and not counted as a pass.

WHAT A PUBLISH WRITES, IN THIS ORDER
------------------------------------
1. `transcript.json` (or `transcript_N.json` for a later batch): every stage's every attempt, the
   checker's verdict on each, the code risk manager's strikes, and the final decisions, for the page that
   shows "how the desk argued". Never rewritten.
2. `disagreement.json` (or `_N`): the table of where the hounds split.
3. Definition rows for any hound not yet registered (the first publish IS registration; there is no replay).
4. One `hound_bet` row per TAKE that survived code and the checker, for each published hound.
5. One `desk_game` row naming the hounds published, the packet hash and the transcript's sha256.

A hound that took nothing is published with no bet rows: a pass is a decision, and the `desk_game` row says
it was made.

THE DESK WITHOUT A DECISION
---------------------------
If the desk head's final answer cannot be read at all (a shape failure on every attempt), the Desk has no
decision to publish and passes the game; the transcript says why. Struck TAKEs are passes.

Nothing here calls a model, a network or a bet-placement system. Paper only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.analyst import analyst as analyst_mod
from src.analyst import cli, config as config_mod, grading, ledger as analyst_ledger, pilot
from src.hounds.desk import disagree, ledger, roles, state

EXIT_OK, EXIT_ERROR = 0, 2

PREREG = "docs/PREREG_DESK_HOUNDS.md"


def prereg_sha256(root: Optional[Path] = None) -> Optional[str]:
    """sha256 of the pre-registration with line endings normalised, so the value does not depend on the
    machine's checkout settings. None when the file is not there (a test's temp root)."""
    target = state.root_of(root) / PREREG
    try:
        text = target.read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return None
    return hashlib.sha256(text).hexdigest()


def _iso(moment: datetime) -> str:
    return pilot._iso(moment)


def _stage_record(game: "state.Game", stage: str) -> dict:
    """Everything one stage did, for the transcript: every attempt's parsed answer, the checker's verdict on
    it, and which attempt is final."""
    role = roles.ROLES[stage]
    st = game.state(stage)
    attempts = []
    for row in game.attempts(stage):
        try:
            _raw, response = game.attempt_response(stage, row["attempt"])
        except pilot.PilotError:
            response = None
        attempts.append({
            "attempt": row["attempt"], "utc": row["utc"], "sha256": row["sha256"],
            "kept": row.get("kept"), "struck": row.get("struck"), "rejected": row.get("rejected"),
            "summary_status": row.get("summary_status"), "rejection_lines": row.get("rejection_lines"),
            "response": response})
    return {"stage": stage, "title": role.title, "kind": role.kind, "state": st["state"],
            "final_attempt": st["attempts"] if st["state"] in state.FINAL else None,
            "request_sha256": game.first_request_hash(stage), "prompt_hash": role.prompt_hash(),
            "attempts": attempts}


def _decision_of(game: "state.Game", stage: str) -> Optional["checks.StageCheck"]:
    """The final check of a decision stage, or None when its final attempt could not be read."""
    result = game.final_check(stage)
    if result is None or result.report.shape_errors:
        return None
    return result


def _per_hound_view(game: "state.Game") -> dict:
    """{hound_id: None | {"takes": [...], "struck": [...]}} for every hound, from final decision stages only."""
    view = {}
    for h in roles.HOUNDS:
        stage = h["decision_stage"]
        if game.state(stage)["state"] not in state.FINAL:
            view[h["id"]] = None
            continue
        result = _decision_of(game, stage)
        if result is None:
            view[h["id"]] = {"takes": [], "struck": [], "unreadable": True}
            continue
        view[h["id"]] = {
            "takes": [{"slot_id": t.slot_id, "selection": t.selection, "price": t.price_best,
                       "book": t.book, "probability": t.probability} for t in result.risk_kept
                      if t.slot_id not in {c["slot_id"] for c in result.critic_struck}],
            "struck": [{"slot_id": s.slot_id, "selection": s.selection, "rule": s.rule, "reason": s.reason}
                       for s in result.risk_struck]
            + [{"slot_id": c["slot_id"], "selection": None, "rule": "checker",
                "reason": "; ".join(c["problems"])[:300]} for c in result.critic_struck]}
    return view


def _next_name(folder: Path, stem: str) -> str:
    if not (folder / f"{stem}.json").exists():
        return f"{stem}.json"
    k = 2
    while (folder / f"{stem}_{k}.json").exists():
        k += 1
    return f"{stem}_{k}.json"


def publish(game: "state.Game", *, model: str, tokens_in=None, tokens_out=None, seconds=None,
            operator_minutes=None, cfg: Optional[Mapping] = None, now: Optional[Callable] = None,
            out: Callable = print, root: Optional[Path] = None) -> int:
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    moment = (now or cli._now)()
    meta, packet = game.meta, game.packet
    gid = game.game_id
    try:
        if not isinstance(model, str) or not model.strip():
            raise state.DeskError("--model must name the model that wrote the answers")
        for name, value in (("tokens_in", tokens_in), ("tokens_out", tokens_out), ("seconds", seconds),
                            ("operator_minutes", operator_minutes)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or value < 0):
                raise state.DeskError(f"{name} must be a number of at least 0")
        if meta.get("rehearsal"):
            raise state.DeskError(f"{game.folder} is a rehearsal and cannot be published; prepare the game "
                                  "again without --rehearsal")
        if (meta.get("prompt_version"), meta.get("role_hashes")) != (roles.PROMPT_VERSION, roles.role_hashes()):
            raise state.DeskError("a desk prompt, schema or role text has changed since this game was "
                                  "prepared, so the answers answer different requests; prepare the game "
                                  "again")
        lead = float(cfg["lock_lead_minutes"])
        why = analyst_ledger.publish_refusal(packet, moment, lead)
        if why:
            raise state.DeskError(f"{gid}: {why}")
        built = analyst_ledger._utc(packet.get("built_at"))
        limit = float(cfg["pilot"]["max_packet_age_minutes"])
        if built is None:
            raise state.DeskError(f"{gid}: the packet does not say when it was built, so its age is unknown")
        age = (moment - built) / timedelta(minutes=1)
        if age > limit:
            raise state.DeskError(f"{gid}: the packet was built {age:.0f} minutes ago, more than the "
                                  f"{limit:g}-minute limit (pilot.max_packet_age_minutes); prices and "
                                  "lineups may have moved. Move the folder aside and prepare the game again")
        # the publication rule, proven against the saved bytes, for every stage that has attempts
        for stage in roles.ALL_STAGES:
            attempts = game.attempts(stage)
            if not attempts:
                continue
            raw, response = game.attempt_response(stage, len(attempts))
            reason, _ = pilot.publication_refusal(game.stage_dir(stage), game.first_request_hash(stage),
                                                  raw, response)
            if reason:
                raise state.DeskError(f"{gid} {stage}: {reason}")
    except (state.DeskError, pilot.PilotError) as exc:
        out(f"REFUSED: {exc}")
        return EXIT_ERROR

    all_rows = ledger.rows(root)
    done = ledger.published_hounds(all_rows, gid)
    view = _per_hound_view(game)
    todo = [h for h in roles.HOUNDS if h["id"] not in done and view[h["id"]] is not None]
    skipped = [h["id"] for h in roles.HOUNDS if h["id"] not in done and view[h["id"]] is None]
    if not todo:
        out(f"REFUSED: {gid}: no hound has a final decision that is not already published"
            + (f" (waiting on: {', '.join(skipped)})" if skipped else ""))
        return EXIT_ERROR

    folder = game.folder
    # 1. the transcript and the table
    table = disagree.build(packet, view)
    transcript_name = _next_name(folder, "transcript")
    table_name = _next_name(folder, "disagreement")
    published_utc = _iso(moment)
    transcript = {
        "game_id": gid, "sport": meta.get("sport", "mlb"), "date": meta["date"],
        "away": meta["away"], "home": meta["home"], "start_utc": meta["start_utc"],
        "built_at": meta["built_at"], "published_utc": published_utc, "packet_hash": meta["packet_hash"],
        "prompt_version": roles.PROMPT_VERSION, "model": model.strip(),
        "label": ("Written by AI models from the data on this page. Unproven. Paper only, not advice."),
        "stages": [_stage_record(game, s) for s in roles.ALL_STAGES if game.attempts(s)],
        "hounds": {h["id"]: view[h["id"]] for h in roles.HOUNDS},
        "disagreement": table,
    }
    # Written as BYTES: the hash must be of exactly what is on disk, and a text-mode write on Windows
    # would turn each newline into a carriage return and newline after the hash was taken.
    text = (json.dumps(transcript, indent=2) + "\n").encode("utf-8")
    (folder / transcript_name).write_bytes(text)
    (folder / table_name).write_bytes((json.dumps(table, indent=2) + "\n").encode("utf-8"))
    transcript_sha = hashlib.sha256(text).hexdigest()

    # 2. registration (the first publish), then the rows
    ledger.register(root, published_utc, prereg_sha256(root))
    chain = ledger.chain(root)
    counts = {}
    for h in todo:
        stage = h["decision_stage"]
        result = _decision_of(game, stage)
        n_attempts = game.state(stage)["attempts"]
        bets = []
        if result is not None:
            struck_ids = {c["slot_id"] for c in result.critic_struck}
            bets = [t for t in result.risk_kept if t.slot_id not in struck_ids]
        for taken in bets:
            spec = grading.spec_for(packet["markets"][taken.slot_id], taken.selection)
            chain.append(ledger.bet_row(
                hound_id=h["id"], taken=taken, meta=meta, spec=spec, published_utc=published_utc,
                packet_hash=meta["packet_hash"], transcript=f"{folder.name}/{transcript_name}",
                transcript_sha256=transcript_sha, stage=stage, attempts=n_attempts, model=model.strip(),
                prompt_hash=roles.hound_prompt_hash(h["id"])))
        counts[h["id"]] = {"takes": len(bets), "attempts": n_attempts,
                           "decision_readable": result is not None}
    run = {"model": model.strip(), "tokens_in": tokens_in, "tokens_out": tokens_out, "seconds": seconds,
           "operator_minutes": operator_minutes, "mode": pilot.MODE,
           "answers": state.attempts_recorded(game)}
    if tokens_in is not None and tokens_out is not None:
        run["cost_usd"] = round(analyst_mod.cost_usd(
            {"input_tokens": int(tokens_in), "output_tokens": int(tokens_out)}, cfg), 4)
        run["cost_basis"] = pilot.COST_BASIS
    chain.append({
        "kind": ledger.KIND_GAME, "game_id": gid, "date": meta["date"], "sport": meta.get("sport", "mlb"),
        "event_id": meta.get("event_id"), "away": meta["away"], "home": meta["home"],
        "start_utc": meta["start_utc"], "lock_utc": meta["built_at"], "published_utc": published_utc,
        "packet_hash": meta["packet_hash"], "hounds": counts, "skipped": skipped,
        "transcript": f"{folder.name}/{transcript_name}", "transcript_sha256": transcript_sha,
        "disagreement": f"{folder.name}/{table_name}", "disagreement_counts": table["counts"],
        "prompt_version": roles.PROMPT_VERSION, "run": run, "segment": "forward"})
    total = sum(c["takes"] for c in counts.values())
    out(f"PUBLISHED {gid}: {len(todo)} hound(s), {total} TAKE(s); transcript {transcript_name}, "
        f"table {table_name}; split {table['counts']['split']}, agree {table['counts']['agree']}, "
        f"lone {table['counts']['lone']}")
    for hid, c in counts.items():
        out(f"  {hid}: {c['takes']} TAKE(s)" + ("" if c["decision_readable"] else " (no readable decision: passed)"))
    if skipped:
        out(f"  not published (no final decision yet): {', '.join(skipped)}")
    return EXIT_OK
