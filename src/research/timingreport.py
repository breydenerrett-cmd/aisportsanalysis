"""The V3 timing report: accumulation status, and tables only past the floor.

THE READING RULE, ENFORCED IN CODE
----------------------------------
docs/RESEARCH_V3_TIMING.md: no class-level result is read before that class
holds 30 admitted events. This module is where that rule becomes mechanical:
below the floor a class reports COUNTS ONLY — how many events, how many
admissible, how many measurable — and the measurement objects are neither
aggregated nor returned. At or past the floor it produces the pre-registered
tables (leadlag.response_table, leadership_stability). There is no flag to
peek early; wanting one is the urge the rule exists to stop.

EVENT-TO-GAME JOINS
-------------------
lineup/probable events carry their game_pk; the game's start time and clubs
come from the results store. A transaction event names no game, so it maps
through the transactions store to its club and then to that club's first
game starting after the event interval's end — the game the information
could still have moved. Every unmappable event is counted with its reason,
never dropped silently.
"""

from __future__ import annotations

import csv

from pathlib import Path

from src.pipeline import news, rosterwatch, snapshots
from src.research import eventstudy, leadlag

RESULTS_PATH = Path("data/historical/mlb_results.csv")

CLASS_FLOOR = 30

# Frozen expected direction per class where the information has one: losing
# a listed starter or hitter weakens that side. Lineup postings and roster
# moves cut both ways, so they carry no frozen sign.
EXPECTED_SIGN = {
    "starter_scratch": None,   # side-dependent; resolved per event below
    "hitter_scratch": None,
    "lineup_posted": None,
    "transaction_first_seen": None,
}


def _games_by_pk(path=RESULTS_PATH) -> dict:
    out = {}
    if not Path(path).exists():
        return out
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[row.get("game_pk")] = row
    return out


def _multibook_rows():
    try:
        return snapshots.read_multibook()
    except Exception:  # noqa: BLE001 -- a missing store is an empty report
        return []


def report(store_dir=None, multibook_rows=None, games=None,
           transactions=None) -> dict:
    """Accumulation status per class; pre-registered tables past the floor."""
    all_events = (rosterwatch.events() if store_dir is None
                  else rosterwatch.events(store_dir))
    rows = _multibook_rows() if multibook_rows is None else multibook_rows
    by_pk = _games_by_pk() if games is None else games
    tx_rows = news.read() if transactions is None else transactions
    tx_team = {t.get("transaction_id"): t.get("team") for t in tx_rows}

    classes = {}
    for event in all_events:
        bucket = classes.setdefault(event["class"], {
            "events": 0, "admissible": 0, "measurable": 0,
            "unmappable": {}, "measured": []})
        bucket["events"] += 1
        if event.get("inadmissible"):
            continue
        bucket["admissible"] += 1

        game_pk = str(event.get("game_pk") or "")
        if not game_pk and event.get("transaction_id") is not None:
            team = tx_team.get(event["transaction_id"])
            game_pk = _next_game_for(team, event, by_pk)
            if game_pk is None:
                reason = ("transaction team unknown" if team is None
                          else "no upcoming stored game for the club")
                bucket["unmappable"][reason] = (
                    bucket["unmappable"].get(reason, 0) + 1)
                continue
        game = by_pk.get(game_pk)
        if not game:
            bucket["unmappable"]["game not in results store"] = (
                bucket["unmappable"].get("game not in results store", 0) + 1)
            continue

        quotes = _quotes_for_game(rows, game)
        measured = eventstudy.measure(
            {"interval": event["interval"]}, quotes,
            game_start=game.get("start_time_utc"))
        bucket["measurable"] += 1 if measured.get("excluded") is None else 0
        bucket["measured"].append(measured)

    out = {"floor": CLASS_FLOOR, "classes": {}}
    for name, bucket in sorted(classes.items()):
        entry = {
            "events": bucket["events"],
            "admissible": bucket["admissible"],
            "measurable": bucket["measurable"],
            "unmappable": bucket["unmappable"],
        }
        if bucket["admissible"] < CLASS_FLOOR:
            entry["status"] = (f"accumulating: {bucket['admissible']} of "
                               f"{CLASS_FLOOR} admitted events; no result "
                               "is read below the floor")
        else:
            entry["status"] = "at floor: pre-registered tables follow"
            entry["response_table"] = leadlag.response_table(
                bucket["measured"])
            entry["leadership_stability"] = leadlag.leadership_stability(
                bucket["measured"])
        out["classes"][name] = entry
    return out


def _quotes_for_game(rows, game) -> list:
    """This game's quotes only, matched by club abbreviation and date.

    The multibook store speaks the odds API's full club names and one date
    holds a whole slate; matching by translated abbreviation pair keeps a
    Reds event from being measured against the Padres' board.
    """
    from src.pipeline import slate as slate_mod

    away, home = game.get("away_team"), game.get("home_team")
    date = game.get("date")
    out = []
    for row in rows or []:
        if (row.get("commence_time") or "")[:10] != date:
            continue
        if slate_mod.team_abbrev_from_name(row.get("away_team") or "") != away:
            continue
        if slate_mod.team_abbrev_from_name(row.get("home_team") or "") != home:
            continue
        out.append({"ts": row.get("observed_utc"), "book": row.get("book"),
                    "away_price": row.get("away_price"),
                    "home_price": row.get("home_price")})
    out.sort(key=lambda q: q.get("ts") or "")
    return out


def _next_game_for(team, event, by_pk):
    """The club's first stored game starting after the event bracket ends."""
    if not team:
        return None
    end = event["interval"][1]
    best_pk, best_start = None, None
    for game_pk, game in by_pk.items():
        if team not in (game.get("away_team"), game.get("home_team")):
            continue
        start = game.get("start_time_utc") or ""
        if start and start > end and (best_start is None or start < best_start):
            best_pk, best_start = game_pk, start
    return best_pk


def format_report(result) -> str:
    lines = []
    for name, entry in result["classes"].items():
        lines.append(f"{name}: {entry['events']} events, "
                     f"{entry['admissible']} admissible, "
                     f"{entry['measurable']} measurable")
        lines.append(f"  {entry['status']}")
        for reason, count in (entry.get("unmappable") or {}).items():
            lines.append(f"  unmappable ({reason}): {count}")
    if not result["classes"]:
        lines.append("no events derived yet; the watch stores are young")
    return "\n".join(lines)
