"""The supervised-session pilot: the analyst's answer written in a Claude session, published by the
same pipeline.

WHY IT EXISTS
-------------
The MLB analyst (docs/AI_ANALYST.md) has never published a row: it needs an API key the owner has
not added. The owner approved a pilot in the meantime. A supervised session writes the model's
answer from the EXACT request the API call would have sent, and everything after that is the
pipeline that already exists: `validate_output` (shape), `critic.verify` (every evidence path and
value checked against the packet, a TAKE at -200 or worse struck), `ledger.publish` (hash-chained,
refused for a game that has started) and the grader. Nothing here is a second pipeline. What it adds
is honesty about provenance, three commands and a separate set of files.

    prepare   build the packet exactly as a run does, refuse what a run would refuse, and write
              packet.json, request.json (the body the API would be sent) and prepare.json.
    check     validate and run the checker on a response file against the saved packet; print,
              per call, kept or struck and why. Publishes nothing. Works on a rehearsal folder.
    publish   reload the saved packet, prove it is the one prepared, refuse what must be refused,
              then validate, verify and publish into the PILOT stores.

THE PILOT HAS ITS OWN STORES AND NOTHING WRITES THE MAIN ONES
-------------------------------------------------------------
`evidence/analyst_pilot_v1.jsonl`, `evidence/analyst_pilot_usage_v1.jsonl` and
`evidence/analyst_pilot_packets_v1/`. A row written here says how it was made (`provenance`,
`run.mode`: "session_assisted") and is graded by the same code, but it is a separate chain with a
separate record: a session-written brief is not the API analyst, and the two are never added
together. Every ledger call in this module passes an explicit pilot path, because the ledger's own
default is the main store; a test asserts the main store is never created.

WHAT A PUBLISH REFUSES
----------------------
* a rehearsal folder (`prepare --scratch`): practice must never reach a reader;
* a packet file that is not the packet prepared (its hash must match prepare.json), or a prompt that
  has changed since prepare (the response answered a different request);
* a game that has started or whose first pitch is unknown (`ledger.publish_refusal`, the one place
  that rule lives);
* a packet built more than `pilot.max_packet_age_minutes` (config/analyst.json, 90) before now:
  prices move and lineups post, and what is frozen must be the picture a reader could have had;
* a game that already has a pilot row, unless `--refresh` (the ledger still refuses a graded one);
* a response that fails the shape check, with every reason listed. A response that passes the shape
  check but fails the truth check is NOT refused: it is published with the failing calls struck to
  PASS, exactly as the API path does, because that is the record of what the model said.

THE COST FIGURE IS AN ESTIMATE AT LIST PRICE
--------------------------------------------
A session is not billed per token. When the operator reports tokens, the row carries tokens times the
list prices in config/analyst.json and says so (`cost_basis`). It is what the same call would cost
through the API, not what anyone paid; with no token counts there is no figure, never a guess.
`seconds` and `operator_minutes` are what the operator reports, kept so the pilot can say what a
brief costs in time.

Nothing here calls the API, a deployed host or any model, and nothing here places a bet.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from src import paths
from src.analyst import analyst as analyst_mod
from src.analyst import cli, critic, ledger
from src.analyst import config as config_mod
from src.analyst import packet as packet_mod

MODE = "session_assisted"

# The pilot's files, beside the main analyst's under evidence/ (the image copies evidence/ whole).
PILOT_DIR = os.path.join("evidence", "analyst_pilot")
STORE = os.path.join("evidence", "analyst_pilot_v1.jsonl")
USAGE_STORE = os.path.join("evidence", "analyst_pilot_usage_v1.jsonl")
PACKET_DIR = os.path.join("evidence", "analyst_pilot_packets_v1")

COST_BASIS = ("estimate at list price: the reported tokens times the per-million prices in "
              "config/analyst.json; not a bill")

FILES = ("packet.json", "request.json", "prepare.json")

EXIT_OK, EXIT_ERROR = cli.EXIT_OK, cli.EXIT_ERROR


class PilotError(RuntimeError):
    """A refusal. The message is printed as is; nothing was published."""


def _root(root: Optional[Path]) -> Path:
    return Path(root) if root is not None else paths.repo_root()


def store_paths(root: Optional[Path] = None) -> dict:
    """Absolute paths of the pilot's stores. `root` is the repo root (tests pass a temp folder)."""
    base = _root(root)
    return {"store": str(base / STORE), "usage": str(base / USAGE_STORE),
            "packets": str(base / PACKET_DIR)}


def game_folder(date: str, away: str, home: str, root: Optional[Path] = None) -> Path:
    return _root(root) / PILOT_DIR / f"{date}_{away.upper()}-{home.upper()}"


def _write_json(target: Path, value: Mapping) -> None:
    """Keys are NOT sorted: `validate_output` reads the order of the packet's `markets` as the slot
    order, so a packet reloaded with its keys sorted would reject a correct answer. The hash is over
    the canonical form and does not care."""
    target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _read_json(target: Path, what: str):
    try:
        return json.loads(Path(target).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PilotError(f"{what} not found: {target}") from None
    except (OSError, ValueError) as exc:
        raise PilotError(f"{what} could not be read as JSON: {target} ({exc})") from None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def _packet_from_client(client, date: str, game: str, moment: datetime, built_at: str, cfg: Mapping,
                        out: Callable):
    """(packet, data-service facts) from `DataClient`, or (None, None) after printing the refusal.

    The data service builds the packet with the analyst's own code over the same stores
    (src/datasvc/mlb/service.py), so for the same inputs and the same `built_at` these are the same
    bytes as the loader path; tests/test_datasvc_mlb_pilot.py pins that by comparing packet hashes.
    The refusals say what the loader path says.
    """
    from src.datasvc.client import DataError

    away, _, home = game.upper().partition("@")
    try:
        result = client.mlb_service().packet(date, away, home, built_at=built_at, cfg=cfg, now=moment)
    except DataError as exc:
        out(f"ERROR: {exc.message}")
        return None, None
    if not result["available"]:
        first = (result.get("missing") or [{}])[0]
        if first.get("code") == "not_found":
            out(f"no games found for {date} matching {game}")
        elif first.get("code") == "ambiguous":
            out(f"ERROR: more than one game matches {game} on {date}; the pilot handles one game at a time")
        else:
            out(f"ERROR: the data service has no packet for {game} on {date}: {first.get('reason')}")
        return None, None
    meta = result["meta"]
    return result["data"], {"packet_source": "data_client", "data_version": meta["data_version"]}


def prepare(date: str, game: str, *, scratch: Optional[str] = None, cfg: Optional[Mapping] = None,
            loader: Optional[Callable] = None, now: Optional[Callable] = None,
            out: Callable = print, root: Optional[Path] = None, client=None) -> int:
    """Build the packet the way a run does and write the three files. Refuses what a run refuses,
    with the same words, because a session must not be spent on a game that cannot be published.

    `client` (a `src.datasvc.client.DataClient`) makes the data service the packet's source in place of
    the analyst's loader: the same packet bytes, plus `packet_source` and the packet's `data_version`
    in prepare.json. Left None nothing changes. Naming both `loader` and `client` is a mistake and refused.
    """
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    if "@" not in (game or ""):
        out("ERROR: --game must be AWAY@HOME, for example NYY@TB")
        return EXIT_ERROR
    if client is not None and loader is not None:
        out("ERROR: give the pilot one packet source, a loader or a data client, not both")
        return EXIT_ERROR
    source_facts: dict = {}
    if client is not None:
        moment = (now or cli._now)()
        built_at = _iso(moment)
        packet, source_facts = _packet_from_client(client, date, game, moment, built_at, cfg, out)
        if packet is None:
            return EXIT_ERROR
    else:
        items = [i for i in (loader or cli.default_loader)(date)
                 if cli._matches(i["payload"]["advanced"]["game"], game)]
        if not items:
            out(f"no games found for {date} matching {game}")
            return EXIT_ERROR
        if len(items) > 1:
            out(f"ERROR: {len(items)} games match {game} on {date}; the pilot handles one game at a time")
            return EXIT_ERROR
        moment = (now or cli._now)()
        built_at = _iso(moment)
        packet = cli._packet(items[0], built_at, cfg)
    gid = packet["game"]["game_id"]
    why = ledger.publish_refusal(packet, moment, float(cfg["lock_lead_minutes"]))
    if why:
        out(f"SKIP {gid}: {why}")
        return EXIT_ERROR
    if not packet["markets"]:
        out(f"SKIP {gid}: the packet prices no market, so there is nothing to call")
        return EXIT_ERROR

    body = analyst_mod.build_request(packet, cfg)
    estimate = analyst_mod.estimate_tokens(body["system"], body["messages"][0]["content"])
    digest = packet_mod.packet_hash(packet)
    rehearsal = scratch is not None
    folder = Path(scratch) if rehearsal else game_folder(
        packet["game"]["date"], packet["game"]["away"], packet["game"]["home"], root)
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "game_id": gid, "date": packet["game"]["date"], "away": packet["game"]["away"],
        "home": packet["game"]["home"], "first_pitch_utc": packet["game"]["first_pitch_utc"],
        "built_at": packet["built_at"], "packet_hash": digest,
        "prompt_version": analyst_mod.PROMPT_VERSION, "prompt_hash": ledger.prompt_hash(),
        "token_estimate": estimate, "model": cfg["model"],
        "slots": [s["slot_id"] for s in packet["slots"]], "missing_items": len(packet["missing"]),
        "rehearsal": rehearsal, "mode": MODE,
        **source_facts,
    }
    _write_json(folder / "packet.json", packet)
    _write_json(folder / "request.json", body)
    _write_json(folder / "prepare.json", meta)
    out(f"PREPARED {gid}{' (REHEARSAL: cannot be published)' if rehearsal else ''}: packet "
        f"{digest[:12]}, {len(packet['slots'])} slots, {len(packet['missing'])} missing items, "
        f"request ~{estimate} input tokens (high estimate)")
    out(f"  folder: {folder}")
    out("  the session answers request.json and writes the JSON answer to a file, then:")
    out(f"  python -m src.cli analyst pilot check --dir {folder} --response <file>")
    if not rehearsal:
        age = cfg["pilot"]["max_packet_age_minutes"]
        out(f"  python -m src.cli analyst pilot publish --dir {folder} --response <file> --model <name>"
            f"   (within {age} minutes of now)")
    return EXIT_OK


# ---------------------------------------------------------------------------
# loading a prepared folder and a response
# ---------------------------------------------------------------------------

@dataclass
class Prepared:
    folder: Path
    meta: dict
    packet: dict


def load_prepared(folder: str) -> Prepared:
    """The folder's packet and prepare.json, with the packet proven to be the one prepared."""
    base = Path(folder)
    meta = _read_json(base / "prepare.json", "prepare.json")
    packet = _read_json(base / "packet.json", "packet.json")
    if not isinstance(meta, Mapping) or not isinstance(packet, Mapping):
        raise PilotError(f"{base}: prepare.json and packet.json must be JSON objects")
    digest = packet_mod.packet_hash(packet)
    if digest != meta.get("packet_hash"):
        raise PilotError(f"the packet in {base} is not the packet that was prepared "
                         f"(hash {digest[:12]}, prepare.json says {str(meta.get('packet_hash'))[:12]}); "
                         "prepare the game again")
    return Prepared(base, dict(meta), dict(packet))


_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.S)


def load_response(path: str) -> dict:
    """The response file as a JSON object. A markdown fence around it is tolerated (a session
    often writes one); anything else that is not JSON is an error."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise PilotError(f"response file could not be read: {path} ({exc.strerror or exc})") from None
    fenced = _FENCE.match(text)
    try:
        value = json.loads(fenced.group(1) if fenced else text)
    except ValueError as exc:
        raise PilotError(f"the response is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise PilotError("the response is not a JSON object")
    return value


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

@dataclass
class CallReport:
    slot_id: str
    verdict: str
    selection: str
    kept: bool
    problems: list = field(default_factory=list)
    downgrades: list = field(default_factory=list)


@dataclass
class CheckReport:
    shape_errors: list
    calls: list = field(default_factory=list)
    summary_status: Optional[str] = None
    summary_problems: list = field(default_factory=list)
    verified: object = None

    @property
    def kept(self) -> int:
        return sum(1 for c in self.calls if c.kept)

    @property
    def struck(self) -> int:
        return sum(1 for c in self.calls if not c.kept)


def evaluate(packet: Mapping, response: Mapping) -> CheckReport:
    """The pipeline's own validation and checker over a response, as a report. The same two calls
    the API path makes; nothing is decided here."""
    errors = analyst_mod.validate_output(response, packet)
    if errors:
        return CheckReport(shape_errors=errors)
    verified = critic.verify(packet, response)
    struck = {s["slot_id"]: s["problems"] for s in verified.struck}
    report = CheckReport(shape_errors=[], summary_status=verified.summary_status,
                         summary_problems=list(verified.summary_problems), verified=verified)
    for original, published in zip(response["calls"], verified.calls):
        sid = original["slot_id"]
        report.calls.append(CallReport(
            slot_id=sid, verdict=original["verdict"], selection=str(original["selection"]),
            kept=sid not in struck, problems=list(struck.get(sid, [])),
            downgrades=list((published.get("verification") or {}).get("downgrades") or [])))
    return report


def print_report(report: CheckReport, out: Callable) -> None:
    if report.shape_errors:
        out(f"REJECTED: the response fails the shape check ({len(report.shape_errors)} problems); "
            "nothing could be checked further")
        for e in report.shape_errors:
            out(f"  {e}")
        return
    for c in report.calls:
        line = f"  {c.slot_id}: {c.verdict} {c.selection}: "
        if c.kept:
            out(line + "kept" + (f" ({'; '.join(c.downgrades)})" if c.downgrades else ""))
        else:
            out(line + "STRUCK, published as a PASS")
            for p in c.problems:
                out(f"      {p}")
    out(f"  summary: {report.summary_status}" + ("".join(f"\n      {p}" for p in report.summary_problems)))
    out(f"totals: {len(report.calls)} calls, {report.kept} kept, {report.struck} struck")


def check(folder: str, response_path: str, *, out: Callable = print) -> int:
    """`pilot check`: what publishing this response would keep and strike. Writes nothing."""
    try:
        prepared = load_prepared(folder)
        response = load_response(response_path)
    except PilotError as exc:
        out(f"ERROR: {exc}")
        return EXIT_ERROR
    report = evaluate(prepared.packet, response)
    out(f"CHECK {prepared.meta.get('game_id')}{' (rehearsal)' if prepared.meta.get('rehearsal') else ''}: "
        "nothing is published by this command")
    print_report(report, out)
    return EXIT_ERROR if report.shape_errors else EXIT_OK


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

def _nonneg(name: str, value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise PilotError(f"{name} must be a number of at least 0")
    return value


def run_record(cfg: Mapping, *, model: str, tokens_in, tokens_out, seconds, operator_minutes,
               run_id: str) -> dict:
    """The row's `run`: how this brief was made, and what it would have cost at list price."""
    estimate = None
    if tokens_in is not None and tokens_out is not None:
        estimate = round(analyst_mod.cost_usd(
            {"input_tokens": int(tokens_in), "output_tokens": int(tokens_out)}, cfg), 4)
    return {"mode": MODE, "run_id": run_id, "model": model,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "cost_usd": estimate, "cost_basis": COST_BASIS,
            "price_per_million_usd": dict(cfg["price_per_million_usd"]),
            "seconds": seconds, "operator_minutes": operator_minutes, "attempts": 1}


def publish(folder: str, response_path: str, *, model: str, tokens_in=None, tokens_out=None,
            seconds=None, operator_minutes=None, refresh: bool = False,
            cfg: Optional[Mapping] = None, now: Optional[Callable] = None,
            out: Callable = print, root: Optional[Path] = None) -> int:
    """`pilot publish`: freeze a supervised-session response into the PILOT ledger, or refuse and
    say why. Every ledger call passes an explicit pilot path; the main stores are never touched."""
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    moment = (now or cli._now)()
    files = store_paths(root)
    try:
        if not isinstance(model, str) or not model.strip():
            raise PilotError("--model must name the model that wrote the answer")
        tokens_in, tokens_out = _nonneg("tokens_in", tokens_in), _nonneg("tokens_out", tokens_out)
        seconds, operator_minutes = _nonneg("seconds", seconds), _nonneg("operator_minutes", operator_minutes)
        prepared = load_prepared(folder)
        meta, packet = prepared.meta, prepared.packet
        gid = packet["game"]["game_id"]
        if meta.get("rehearsal"):
            raise PilotError(f"{prepared.folder} is a rehearsal (prepared with --scratch) and cannot be "
                             "published; prepare the game again without --scratch")
        if (meta.get("prompt_version"), meta.get("prompt_hash")) != (analyst_mod.PROMPT_VERSION,
                                                                      ledger.prompt_hash()):
            raise PilotError("the analyst prompt or schema has changed since this game was prepared, so "
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
                             "lineups may have moved. Prepare the game again")
        existing = ledger.latest_published(ledger.rows(files["store"])).get(gid)
        if existing and not refresh:
            raise PilotError(f"{gid}: already has a pilot row (v{existing['version']}); frozen unless "
                             "--refresh")
        response = load_response(response_path)
        errors = analyst_mod.validate_output(response, packet)
        if errors:
            raise PilotError("the response fails the shape check, so nothing was published:\n  "
                             + "\n  ".join(errors))
    except PilotError as exc:
        out(f"REFUSED: {exc}")
        return EXIT_ERROR

    verified = critic.verify(packet, response)
    run_id = uuid.uuid4().hex[:12]
    run = run_record(cfg, model=model.strip(), tokens_in=tokens_in, tokens_out=tokens_out,
                     seconds=seconds, operator_minutes=operator_minutes, run_id=run_id)
    try:
        row, created = ledger.publish(
            packet, verified, now=moment, model=model.strip(), run=run, path=files["store"],
            packet_dir=files["packets"], lock_lead_minutes=lead, refresh=refresh,
            prompt_version=analyst_mod.PROMPT_VERSION, extra={"provenance": MODE, "mode": MODE})
    except ledger.AnalystLedgerError as exc:
        out(f"REFUSED: {exc}")
        return EXIT_ERROR
    ledger.log_usage(
        date=packet["game"]["date"], game_id=gid, run_id=run_id,
        outcome="published" if created else "already_published", model=model.strip(),
        usage={"input_tokens": tokens_in or 0, "output_tokens": tokens_out or 0},
        cost_usd=run["cost_usd"] or 0.0, attempts=1, cfg=cfg, now=moment, path=files["usage"],
        extra={"mode": MODE, "tokens_reported": tokens_in is not None and tokens_out is not None,
               "cost_basis": COST_BASIS, "seconds": seconds, "operator_minutes": operator_minutes,
               "calls": len(verified.calls), "struck": len(verified.struck)})
    cost = f", about ${run['cost_usd']:.3f} at list price" if run["cost_usd"] is not None else ""
    out(f"PUBLISHED (pilot) {gid} v{row['version']}: {len(verified.calls)} calls, "
        f"{len(verified.struck)} struck, summary {verified.summary_status}{cost}, "
        f"hash {row['row_hash'][:12]}")
    return EXIT_OK
