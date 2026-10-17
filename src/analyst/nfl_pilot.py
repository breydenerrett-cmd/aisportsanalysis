"""The NFL supervised-session pilot: prepare, check, publish, into its own stores.

THE SAME FLOW AS THE MLB PILOT, ANOTHER SPORT, ANOTHER LEDGER
-------------------------------------------------------------
`src/analyst/pilot.py` explains the flow (a Claude session writes the answer from the exact request
the API would be sent; the same shape check, checker and ledger publish it) and the publication rule
(the first answer is the candidate; only a checker rejection earns another, at most twice). All of
that is used here as it is: the attempt record, the refusal to publish an unchecked, unlatest or
rerolled answer, the age limit on a packet, the rehearsal folder. What this module changes is
what is about football:

    prepare   build the NFL packet (nfl_packet.py) from the NFL data store and the odds store, and
              write packet.json, request.json and prepare.json. Refuses what a publish would
              refuse (a game that has kicked off, a game not pending, a game that prices no market).
    check     the NFL checker (nfl_analyst.verify) over a response, recorded as an attempt.
    publish   into `evidence/analyst_pilot_nfl_v1.jsonl`, with the NFL prompt identity.

THE NFL PILOT HAS ITS OWN STORES AND NOTHING HERE TOUCHES THE MLB ONES
----------------------------------------------------------------------
`evidence/analyst_pilot_nfl_v1.jsonl`, `evidence/analyst_pilot_nfl_usage_v1.jsonl` and
`evidence/analyst_pilot_nfl_packets_v1/`; prepared folders live under `evidence/analyst_pilot_nfl/`.
The MLB pilot's `evidence/analyst_pilot*` files are never read or written by this module, and every
ledger call below passes an explicit NFL path, because the ledger's own default is the main MLB
store. A test asserts neither is ever created. An NFL row is graded by `nfl_grading`, counted in its
own record, and never added to the MLB pilot's or the API analyst's.

WHAT A PUBLISH REFUSES, BEYOND THE MLB PILOT'S LIST
---------------------------------------------------
The same list, and also: a folder prepared for another sport, and a prompt or schema that has
changed since prepare. The kickoff rule is `ledger.publish_refusal`, the one place it lives: a game
whose kickoff is unknown, not pending, or at or before now cannot be published, and prepare asks it
first so a session is never spent on a game that cannot be published.

THE START THE QUOTES ARE CUT AT
-------------------------------
`nfl_packet` cuts quotes off at the EARLIER of the schedule's kickoff and the odds feed's start. The
publish rule above uses the packet's `kickoff_utc`, which is the schedule's. A game the feed moved
earlier than the schedule is therefore caught at packet time (quotes dropped, `missing` says so),
and the 90-minute packet age limit bounds how stale a published picture can be.

Nothing here calls the API or any model, and nothing here places a bet.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.analyst import analyst as analyst_mod
from src.analyst import cli, ledger, nfl_analyst, nfl_packet, pilot
from src.analyst import config as config_mod
from src.analyst import packet as packet_mod
from src.sports import nfl_teams

SPORT = "nfl"
MODE = pilot.MODE
PilotError = pilot.PilotError
EXIT_OK, EXIT_ERROR = pilot.EXIT_OK, pilot.EXIT_ERROR

PILOT_DIR = os.path.join("evidence", "analyst_pilot_nfl")
STORE = os.path.join("evidence", "analyst_pilot_nfl_v1.jsonl")
USAGE_STORE = os.path.join("evidence", "analyst_pilot_nfl_usage_v1.jsonl")
PACKET_DIR = os.path.join("evidence", "analyst_pilot_nfl_packets_v1")

# How far back the odds store is read for a game: a week's market is captured over about ten days,
# and reading further only costs time. The store is read one line at a time (snapshots.iter_multibook).
ODDS_LOOKBACK_DAYS = 14


def store_paths(root: Optional[Path] = None) -> dict:
    """Absolute paths of the NFL pilot's stores. `root` is the repo root (tests pass a temp folder)."""
    base = pilot._root(root)
    return {"store": str(base / STORE), "usage": str(base / USAGE_STORE),
            "packets": str(base / PACKET_DIR)}


def game_folder(date: str, away: str, home: str, root: Optional[Path] = None) -> Path:
    return pilot._root(root) / PILOT_DIR / f"{date}_{away.upper()}-{home.upper()}"


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def default_store():
    """The NFL data store on disk (data/datasvc/nfl). The only place this module reads it."""
    from src.datasvc.nfl.store import NflStore
    return NflStore()


def default_rows(game: Mapping) -> list:
    """This game's odds-feed rows, streamed one line at a time from the multibook store. The only
    place this module reads it."""
    from src.pipeline import snapshots

    away, home = game["away_team"], game["home_team"]
    kickoff = nfl_packet._instant(game.get("kickoff_utc"))
    since = ((kickoff - timedelta(days=ODDS_LOOKBACK_DAYS)).date().isoformat() if kickoff else None)
    return list(snapshots.iter_multibook(
        sport="nfl", since=since,
        keep=lambda row: bool(nfl_packet.rows_for_game([row], away, home, kickoff))))


def resolve_game(store, date: str, away: str, home: str) -> dict:
    """The store's game for `date` (the Eastern game date) between these clubs, or a PilotError
    that says what was not found. Club codes may be spelled any way `nfl_teams.abbrev` reads."""
    a, h = nfl_teams.abbrev(away), nfl_teams.abbrev(home)
    if a is None or h is None:
        bad = away if a is None else home
        raise PilotError(f"{bad!r} is not an NFL club code (for example HOU@JAX; the Rams are LA)")
    found = [g for g in store.games if g.get("gameday") == date and g.get("away_team") == a
             and g.get("home_team") == h and g.get("status") != "removed"]
    if not found:
        raise PilotError(f"no NFL game {a}@{h} on {date} in the data store")
    if len(found) > 1:
        raise PilotError(f"more than one game matches {a}@{h} on {date}; the pilot handles one game at a time")
    return found[0]


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def prepare(date: str, game: str, *, scratch: Optional[str] = None, cfg: Optional[Mapping] = None,
            store=None, rows: Optional[list] = None, now: Optional[Callable] = None,
            out: Callable = print, root: Optional[Path] = None) -> int:
    """Build the NFL packet the way a publish needs it and write the three files. Refuses what a
    publish would refuse, with the same words (`ledger.publish_refusal`).

    `store` and `rows` are injected by tests; left None they are read from disk, once."""
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    if "@" not in (game or ""):
        out("ERROR: --game must be AWAY@HOME, for example HOU@JAX")
        return EXIT_ERROR
    away, _, home = game.partition("@")
    store = store if store is not None else default_store()
    try:
        row = resolve_game(store, date, away.strip(), home.strip())
    except PilotError as exc:
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    moment = (now or cli._now)()
    built_at = pilot._iso(moment)
    feed = rows if rows is not None else default_rows(row)
    packet = nfl_packet.build_packet(store, row["game_id"], built_at=built_at, multibook_rows=feed, cfg=cfg)
    gid = packet["game"]["game_id"]
    why = ledger.publish_refusal(packet, moment, float(cfg["lock_lead_minutes"]))
    if why:
        out(f"SKIP {gid}: {why}")
        return EXIT_ERROR
    if not packet["markets"]:
        out(f"SKIP {gid}: the packet prices no market, so there is nothing to call")
        return EXIT_ERROR

    body = nfl_analyst.build_request(packet, cfg)
    estimate = analyst_mod.estimate_tokens(body["system"], body["messages"][0]["content"])
    digest = packet_mod.packet_hash(packet)
    rehearsal = scratch is not None
    folder = Path(scratch) if rehearsal else game_folder(
        packet["game"]["date"], packet["game"]["away"], packet["game"]["home"], root)
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "sport": SPORT, "game_id": gid, "date": packet["game"]["date"], "away": packet["game"]["away"],
        "home": packet["game"]["home"], "kickoff_utc": packet["game"]["kickoff_utc"],
        "built_at": packet["built_at"], "packet_hash": digest,
        "prompt_version": nfl_analyst.NFL_PROMPT_VERSION, "prompt_hash": nfl_analyst.prompt_hash(),
        "token_estimate": estimate, "model": cfg["model"],
        "slots": [s["slot_id"] for s in packet["slots"]], "missing_items": len(packet["missing"]),
        "rehearsal": rehearsal, "mode": MODE, "packet_source": "nfl_store+odds_multibook",
    }
    pilot._write_json(folder / "packet.json", packet)
    pilot._write_json(folder / "request.json", body)
    pilot._write_json(folder / "prepare.json", meta)
    out(f"PREPARED {gid}{' (REHEARSAL: cannot be published)' if rehearsal else ''}: packet "
        f"{digest[:12]}, {len(packet['slots'])} slots, {len(packet['missing'])} missing items, "
        f"request ~{estimate} input tokens (high estimate)")
    out(f"  folder: {folder}")
    out("  the session answers request.json and writes the JSON answer to a file, then:")
    out(f"  python -m src.cli analyst pilot check --sport nfl --dir {folder} --response <file>")
    if not rehearsal:
        age = cfg["pilot"]["max_packet_age_minutes"]
        out(f"  python -m src.cli analyst pilot publish --sport nfl --dir {folder} --response <file> "
            f"--model <name>   (within {age} minutes of now)")
    return EXIT_OK


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def _load_prepared(folder: str) -> pilot.Prepared:
    prepared = pilot.load_prepared(folder)
    if prepared.meta.get("sport") != SPORT:
        raise PilotError(f"{prepared.folder} was prepared for {prepared.meta.get('sport') or 'MLB'}, not "
                         "NFL; use the matching --sport")
    return prepared


def check(folder: str, response_path: str, *, out: Callable = print, now: Optional[Callable] = None) -> int:
    """`pilot check --sport nfl`: what publishing this response would keep and strike, recorded as an
    attempt in the prepared folder (the publication rule). It publishes nothing."""
    try:
        prepared = _load_prepared(folder)
        raw = pilot.read_response_bytes(response_path)
        response = pilot.parse_response(raw)
    except PilotError as exc:
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    report = pilot.evaluate(prepared.packet, response, verify=nfl_analyst.verify)
    out(f"CHECK {prepared.meta.get('game_id')}{' (rehearsal)' if prepared.meta.get('rehearsal') else ''}: "
        "nothing is published by this command")
    pilot.print_report(report, out)
    try:
        row, is_new = pilot.record_attempt(prepared.folder, prepared.meta["packet_hash"], raw, response,
                                           report, (now or cli._now)())
    except (PilotError, OSError) as exc:
        out(f"ERROR: the attempt could not be recorded, so this response cannot be published: {exc}")
        return EXIT_ERROR
    pilot.print_attempt(row, is_new, out)
    return EXIT_ERROR if report.shape_errors else EXIT_OK


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

def publish(folder: str, response_path: str, *, model: str, tokens_in=None, tokens_out=None,
            seconds=None, operator_minutes=None, refresh: bool = False,
            cfg: Optional[Mapping] = None, now: Optional[Callable] = None,
            out: Callable = print, root: Optional[Path] = None) -> int:
    """`pilot publish --sport nfl`: freeze a supervised-session response into the NFL pilot ledger,
    or refuse and say why. Every ledger call passes an explicit NFL path; no MLB store is touched."""
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    moment = (now or cli._now)()
    files = store_paths(root)
    try:
        if not isinstance(model, str) or not model.strip():
            raise PilotError("--model must name the model that wrote the answer")
        tokens_in, tokens_out = pilot._nonneg("tokens_in", tokens_in), pilot._nonneg("tokens_out", tokens_out)
        seconds = pilot._nonneg("seconds", seconds)
        operator_minutes = pilot._nonneg("operator_minutes", operator_minutes)
        prepared = _load_prepared(folder)
        meta, packet = prepared.meta, prepared.packet
        gid = packet["game"]["game_id"]
        if meta.get("rehearsal"):
            raise PilotError(f"{prepared.folder} is a rehearsal (prepared with --scratch) and cannot be "
                             "published; prepare the game again without --scratch")
        if (meta.get("prompt_version"), meta.get("prompt_hash")) != (nfl_analyst.NFL_PROMPT_VERSION,
                                                                      nfl_analyst.prompt_hash()):
            raise PilotError("the NFL analyst prompt or schema has changed since this game was prepared, so "
                             "the response answers a different request; prepare the game again")
        lead = float(cfg["lock_lead_minutes"])
        why = ledger.publish_refusal(packet, moment, lead)
        if why:
            raise PilotError(f"{gid}: {why}")
        built = ledger._utc(packet.get("built_at"))
        limit = float(cfg["pilot"]["max_packet_age_minutes"])
        if built is None:
            raise PilotError(f"{gid}: the packet does not say when it was built, so its age is unknown")
        age = (moment - built) / timedelta(minutes=1)
        if age > limit:
            raise PilotError(f"{gid}: the packet was built {age:.0f} minutes ago, more than the "
                             f"{limit:g}-minute limit (pilot.max_packet_age_minutes); prices and "
                             "injury reports may have moved. Prepare the game again")
        existing = ledger.latest_published(ledger.rows(files["store"])).get(gid)
        if existing and not refresh:
            raise PilotError(f"{gid}: already has a pilot row (v{existing['version']}); frozen unless "
                             "--refresh")
        raw = pilot.read_response_bytes(response_path)
        response = pilot.parse_response(raw)
        why, attempts = pilot.publication_refusal(prepared.folder, meta["packet_hash"], raw, response)
        if why:
            raise PilotError(f"{gid}: {why}")
        errors = analyst_mod.validate_output(response, packet)
        if errors:
            raise PilotError("the response fails the shape check, so nothing was published:\n  "
                             + "\n  ".join(errors))
    except PilotError as exc:
        out(f"REFUSED: {exc}")
        return EXIT_ERROR

    verified = nfl_analyst.verify(packet, response)
    run_id = uuid.uuid4().hex[:12]
    run = pilot.run_record(cfg, model=model.strip(), tokens_in=tokens_in, tokens_out=tokens_out,
                           seconds=seconds, operator_minutes=operator_minutes, run_id=run_id,
                           attempts=len(attempts))
    try:
        row, created = ledger.publish(
            packet, verified, now=moment, model=model.strip(), run=run, path=files["store"],
            packet_dir=files["packets"], lock_lead_minutes=lead, refresh=refresh,
            prompt_version=nfl_analyst.NFL_PROMPT_VERSION, system_prompt=nfl_analyst.NFL_SYSTEM_PROMPT,
            extra={"provenance": MODE, "mode": MODE, "sport": SPORT, "game_pk": gid,
                   "kickoff_utc": packet["game"]["kickoff_utc"], "attempts": len(attempts),
                   "attempt_hashes": [a["sha256"] for a in attempts]})
    except ledger.AnalystLedgerError as exc:
        out(f"REFUSED: {exc}")
        return EXIT_ERROR
    ledger.log_usage(
        date=packet["game"]["date"], game_id=gid, run_id=run_id,
        outcome="published" if created else "already_published", model=model.strip(),
        usage={"input_tokens": tokens_in or 0, "output_tokens": tokens_out or 0},
        cost_usd=run["cost_usd"] or 0.0, attempts=len(attempts), cfg=cfg, now=moment, path=files["usage"],
        extra={"mode": MODE, "sport": SPORT, "tokens_reported": tokens_in is not None and tokens_out is not None,
               "cost_basis": pilot.COST_BASIS, "seconds": seconds, "operator_minutes": operator_minutes,
               "calls": len(verified.calls), "struck": len(verified.struck)})
    cost = f", about ${run['cost_usd']:.3f} at list price" if run["cost_usd"] is not None else ""
    out(f"PUBLISHED (NFL pilot) {gid} v{row['version']}: {len(verified.calls)} calls, "
        f"{len(verified.struck)} struck, summary {verified.summary_status}{cost}, "
        f"hash {row['row_hash'][:12]}")
    return EXIT_OK
