"""A UFC store built from the REAL ESPN responses saved in tests/fixtures/espn_mma.

Every row here comes out of the data layer's own parsers (`schedule.parse_event`/`parse_status`,
`fightstats.parse_competitor_statistics`, `odds.parse_odds`, `fighters.parse_athlete`) run on
a saved response, never typed by hand, so the golden read in tests/test_ufc_read_golden.py is the
read of what ESPN actually served on 2026-09-26 and 2026-10-03:

  * UFC Fight Night 2026-09-26 (event 600061266): twelve bouts, three of them with both fighters'
    statistics and DraftKings prices, including the five-round main event, Raul Rosas Jr. (5088844)
    against Raoni Barcelos (3075570), won by TKO in round 5 (bout 401911630);
  * UFC 332 (event 600061182), fourteen scheduled bouts, one of them with a saved price list and both
    athletes' records: Marvin Vettori (4001851) against Ismail Naurdiev (4412813), bout 401912275.

What the fixtures do not hold is a fighter's earlier fights, so a fighter's history in this store
is the bouts above and nothing else. That is exactly the thin situation the read has to be honest about.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from src.datasvc.ufc import fightstats, fighters, odds, schedule
from src.datasvc.ufc.store import UfcStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_mma"
FETCHED = "2026-10-03T18:00:00Z"
SOURCE = "https://example.test/espn-fixture"
NOW = datetime(2026, 10, 3, 19, 0, tzinfo=timezone.utc)

UPCOMING_BOUT = "401912275"                 # Vettori v Naurdiev, UFC 332
MAIN_EVENT_0926 = "401911630"               # Rosas Jr. v Barcelos
VETTORI, NAURDIEV = "4001851", "4412813"
ROSAS, BARCELOS = "5088844", "3075570"

STATS = (("401911630", "3075570"), ("401911630", "5088844"), ("401914466", "3922491"),
         ("401914466", "4339130"), ("401924683", "5060467"), ("401924683", "5369427"))
ODDS = (("401911630", "odds_401911630.json", "scoreboard_2026-09-26.json"),
        ("401914466", "odds_401914466.json", "scoreboard_2026-09-26.json"),
        ("401924683", "odds_401924683.json", "scoreboard_2026-09-26.json"),
        (UPCOMING_BOUT, "odds_401912275_upcoming.json", "scoreboard_2026-10-03.json"))


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _status_file(bout_id: str) -> str:
    original = f"competition_{bout_id}_status.json"
    return original if (FIXTURES / original).exists() else f"w1_status_{bout_id}.json"


def _scoreboard_names(*scoreboards: str) -> Dict[str, dict]:
    out = {}
    for name in scoreboards:
        for event in load(name)["events"]:
            for comp in event["competitions"]:
                for c in comp["competitors"]:
                    summary = ((c.get("records") or [{}])[0]).get("summary") or ""
                    parts = summary.split("-")
                    record = None
                    if len(parts) == 3 and all(p.isdigit() for p in parts):
                        record = {"wins": int(parts[0]), "losses": int(parts[1]), "draws": int(parts[2])}
                    out[c["id"]] = {"name": c["athlete"]["displayName"], "record": record}
    return out


def build(root: Path) -> UfcStore:
    store = UfcStore(Path(root))
    events, bouts = [], []

    # the 2026-09-26 card, with a status for every bout that has a saved one
    event, rows = schedule.parse_event(load("event_600061266.json"), fetched_utc=FETCHED, source_url=SOURCE)
    for bout in rows:
        status_name = _status_file(bout["bout_id"])
        if (FIXTURES / status_name).exists():
            bout.update(schedule.parse_status(load(status_name)))
    event["status"] = schedule.derive_event_status(b["status"] for b in rows)
    events.append(event)
    bouts += rows

    # UFC 332: every bout is scheduled (the one saved scheduled status stands for them all)
    scheduled = schedule.parse_status(load("w1_status_scheduled_401912278.json"))
    event, rows = schedule.parse_event(load("event_600061182.json"), fetched_utc=FETCHED, source_url=SOURCE)
    for bout in rows:
        bout.update(scheduled)
    event["status"] = "scheduled"
    events.append(event)
    bouts += rows
    store.upsert("events", events)
    store.upsert("bouts", bouts)

    by_id = {b["bout_id"]: b for b in bouts}
    stats = []
    for bout_id, fighter_id in STATS:
        stats.append(fightstats.parse_competitor_statistics(
            load(f"competitor_{bout_id}_{fighter_id}_statistics.json"), bout=by_id[bout_id], fighter_id=fighter_id,
            fetched_utc=FETCHED, source_url=SOURCE))
    store.upsert("fight_stats", stats)

    names = _scoreboard_names("scoreboard_2026-09-26.json", "scoreboard_2026-10-03.json")
    rows = []
    for bout_id, odds_file, scoreboard in ODDS:
        bout = by_id[bout_id]
        people = {fid: names[fid] for fid in (bout["fighter_a_id"], bout["fighter_b_id"])}
        rows += odds.parse_odds(load(odds_file), bout=bout, fetched_utc=FETCHED, source_url=SOURCE, fighters=people)
    store.upsert("odds", rows)

    people = []
    for fid in (VETTORI, NAURDIEV):
        people.append(fighters.parse_athlete(load(f"athlete_{fid}.json"), load(f"athlete_{fid}_records.json"),
                                             fetched_utc=FETCHED, source_url=SOURCE))
    parsed = {p["fighter_id"] for p in people}
    in_store = {fid for b in bouts for fid in (b["fighter_a_id"], b["fighter_b_id"])}
    for fid, info in sorted(names.items()):
        if fid in parsed or fid not in in_store:
            continue
        people.append({"fighter_id": fid, "name": info["name"], "record": info["record"], "source_url": SOURCE,
                       "fetched_utc": FETCHED, "aliases": []})
    store.upsert("fighters", people)
    return store


def golden_sheets(store: UfcStore) -> dict:
    """The two sheets the golden reads are built from."""
    from src.datasvc.ufc import matchup
    return {
        # a real upcoming bout: real records, physical attributes and prices, and no earlier fights in the fixtures
        "vettori_v_naurdiev_upcoming": matchup.matchup(store, VETTORI, NAURDIEV, now=NOW),
        # the 2026-09-26 main event as it stands afterwards: each fighter's one fight on file is this one,
        # with real statistics, a real result and a real closing price; a thin sample on both sides
        "rosas_v_barcelos_afterwards": matchup.matchup(store, ROSAS, BARCELOS, "2026-10-03", now=NOW),
    }

