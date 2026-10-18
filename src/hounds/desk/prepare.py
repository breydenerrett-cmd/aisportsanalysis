"""`prepare`: freeze one game's data for the desk and write nothing a subagent could be misled by.

REUSE, NOT A SECOND PACKET
--------------------------
The packet is built by the analyst's own code over the same stores and is byte for byte what
`python -m src.cli analyst pilot prepare` would build for the same inputs and the same `built_at`:

    baseball   `analyst.cli.default_loader` + `cli._packet`          (src/analyst/packet.py)
    football   `nfl_pilot` store + `nfl_packet.build_packet`          (src/analyst/nfl_packet.py)

Nothing is added to the packet. The odds feed's event id (what the referee joins on to measure the closing
price) is not in the packet, so it is read from the same price rows the packet was built from and kept in
`prepare.json` beside it.

WHAT PREPARE REFUSES
--------------------
What a publish would refuse, in the analyst's words (`ledger.publish_refusal`): a game that has started or
whose start is unknown, a game that is not pending, a game that prices no market. And two desk rules:

* a THIRD open game for the date. A run is at most `MAX_GAMES_PER_RUN` games; a packet goes stale (90
  minutes), so freezing a game that cannot be worked this run only wastes it;
* a folder that already has a prepared game in it. A request file is what a writer was given and is never
  rewritten; to freeze the game again, move the old folder aside first.

Prepare writes the packet, `prepare.json` (hashes, caps, event id and a token estimate per stage) and
NOTHING ELSE: request files are written by `session-plan`, as each stage's upstream becomes final.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.analyst import cli, ledger as analyst_ledger, nfl_packet, nfl_pilot, pilot
from src.analyst import config as config_mod
from src.analyst import packet as packet_mod
from src.hounds.desk import builder, ledger, roles, state

EXIT_OK, EXIT_ERROR = 0, 2


def _event_id(rows) -> Optional[str]:
    counter = Counter(r.get("event_id") for r in rows if r.get("event_id"))
    return counter.most_common(1)[0][0] if counter else None


def token_estimates(packet: Mapping) -> dict:
    """{stage: {"input": n, "output": m}} for every stage, plus the totals for the Desk and for the six
    personas. Estimates at JSON's ~3 characters a token: high on purpose, and not measurements."""
    per = {stage: {"input": builder.estimate_input_tokens(packet, role),
                   "output": builder.output_estimate(role)} for stage, role in roles.ROLES.items()}
    desk = sum(per[s]["input"] for s in roles.DESK_STAGES), sum(per[s]["output"] for s in roles.DESK_STAGES)
    persona = (sum(per[s]["input"] for s in roles.PERSONA_STAGES),
               sum(per[s]["output"] for s in roles.PERSONA_STAGES))
    return {"stages": per, "desk": {"input": desk[0], "output": desk[1]},
            "personas": {"input": persona[0], "output": persona[1]},
            "all": {"input": desk[0] + persona[0], "output": desk[1] + persona[1]},
            "basis": "high estimates from the request text and the schema limits; not measured"}


def _open_games(date: str, now: datetime, root: Optional[Path]) -> list:
    """Prepared, non-rehearsal games for `date` that can still be worked: not started, not fully published."""
    all_rows = ledger.rows(root) if ledger.path(root).exists() else []
    every_hound = {h["id"] for h in roles.HOUNDS}
    out = []
    for game in state.games_for_date(date, root):
        if game.meta.get("rehearsal"):
            continue
        start = analyst_ledger._utc(game.meta.get("start_utc"))
        if start is not None and now >= start:
            continue
        if every_hound <= ledger.published_hounds(all_rows, game.game_id):
            continue
        out.append(game)
    return out


def prepare(date: str, game: str, *, sport: str = "mlb", rehearsal: bool = False,
            cfg: Optional[Mapping] = None, loader: Optional[Callable] = None, store=None,
            rows: Optional[list] = None, now: Optional[Callable] = None, out: Callable = print,
            root: Optional[Path] = None) -> int:
    cfg = dict(cfg) if cfg is not None else config_mod.load()
    if sport not in roles.SPORTS:
        out(f"ERROR: --sport must be one of {list(roles.SPORTS)}")
        return EXIT_ERROR
    if "@" not in (game or ""):
        out("ERROR: --game must be AWAY@HOME, for example NYY@TB (football: HOU@JAX)")
        return EXIT_ERROR
    moment = (now or cli._now)()
    built_at = pilot._iso(moment)
    away_in, _, home_in = game.partition("@")
    event_id: Optional[str] = None

    if sport == "mlb":
        items = [i for i in (loader or cli.default_loader)(date)
                 if cli._matches(i["payload"]["advanced"]["game"], game)]
        if not items:
            out(f"no games found for {date} matching {game}")
            return EXIT_ERROR
        if len(items) > 1:
            out(f"ERROR: {len(items)} games match {game} on {date}; the desk handles one game at a time")
            return EXIT_ERROR
        packet = cli._packet(items[0], built_at, cfg)
        event_id = _event_id(items[0].get("multibook_rows") or [])
        game_ref = packet["game"].get("game_pk")
    else:
        store = store if store is not None else nfl_pilot.default_store()
        try:
            row = nfl_pilot.resolve_game(store, date, away_in.strip(), home_in.strip())
        except pilot.PilotError as exc:
            out(f"ERROR: {exc}")
            return EXIT_ERROR
        feed = rows if rows is not None else nfl_pilot.default_rows(row)
        packet = nfl_packet.build_packet(store, row["game_id"], built_at=built_at, multibook_rows=feed,
                                         cfg=cfg)
        event_id = _event_id(feed)
        game_ref = packet["game"]["game_id"]

    gid = packet["game"]["game_id"]
    why = analyst_ledger.publish_refusal(packet, moment, float(cfg["lock_lead_minutes"]))
    if why:
        out(f"SKIP {gid}: {why}")
        return EXIT_ERROR
    if not packet["markets"]:
        out(f"SKIP {gid}: the packet prices no market, so there is nothing to decide")
        return EXIT_ERROR

    folder = state.game_folder(sport, packet["game"]["date"], packet["game"]["away"],
                               packet["game"]["home"], root)
    if (folder / "prepare.json").exists():
        out(f"REFUSED {gid}: {folder} already holds a prepared game. A request file is what a writer was "
            "given and is never rewritten; move the folder aside, then prepare the game again.")
        return EXIT_ERROR
    if not rehearsal:
        open_games = _open_games(packet["game"]["date"], moment, root)
        if len(open_games) >= state.MAX_GAMES_PER_RUN:
            out(f"REFUSED {gid}: {len(open_games)} games are already open for {date} "
                f"({', '.join(g.game_id for g in open_games)}); a run is at most "
                f"{state.MAX_GAMES_PER_RUN} games. Publish or let them pass first.")
            return EXIT_ERROR

    digest = packet_mod.packet_hash(packet)
    estimates = token_estimates(packet)
    start_utc = analyst_ledger.start_utc(packet["game"])
    meta = {
        "sport": sport, "game_id": gid, "game_ref": game_ref, "date": packet["game"]["date"],
        "away": packet["game"]["away"], "home": packet["game"]["home"], "start_utc": start_utc,
        "built_at": packet["built_at"], "packet_hash": digest, "event_id": event_id,
        "prompt_version": roles.PROMPT_VERSION, "role_hashes": roles.role_hashes(),
        "token_estimates": estimates, "model": cfg["model"], "rehearsal": bool(rehearsal),
        "mode": pilot.MODE, "caps": {"games_per_run": state.MAX_GAMES_PER_RUN,
                                     "answers_per_run": state.MAX_ANSWERS_PER_RUN,
                                     "attempts_per_stage": state.MAX_ATTEMPTS},
        "packet_source": "analyst_loader" if sport == "mlb" else "nfl_store+odds_multibook",
    }
    folder.mkdir(parents=True, exist_ok=True)
    pilot._write_json(folder / "packet.json", packet)
    pilot._write_json(folder / "prepare.json", meta)
    out(f"PREPARED {gid}{' (REHEARSAL: cannot be published)' if rehearsal else ''}: packet {digest[:12]}, "
        f"{len(packet['slots'])} slots, {len(packet['missing'])} missing items, event id "
        f"{event_id or 'NOT FOUND (no closing-price comparison possible)'}")
    out(f"  folder: {folder}")
    first = estimates["stages"]["analyst_stats"]["input"]
    out(f"  request tokens (high estimates): a first-wave request ~{first}; the Desk's seven requests "
        f"~{estimates['desk']['input']} in, ~{estimates['desk']['output']} out; the six personas "
        f"~{estimates['personas']['input']} in, ~{estimates['personas']['output']} out")
    out(f"  next: python -m src.hounds.desk session-plan --date {date}")
    return EXIT_OK
