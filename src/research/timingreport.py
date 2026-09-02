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
through its own recorded club (rosterwatch writes it at first sighting) to
that club's first game starting after the event interval's end — the game the
information could still have moved. Every unmappable event is counted with its
reason, never dropped silently.

"NOT MAPPABLE YET" IS NOT "NOT MAPPABLE"
---------------------------------------
The results store holds games that have been PLAYED. Tonight's slate is not in
it, and will not be until settlement runs. So an event captured today about a
game tonight is not a broken join — it is a join waiting for the evening. The
report separates the two explicitly, because they demand opposite responses: a
pipeline that is merely young needs nothing, and one that is genuinely
mis-keying games needs fixing now, and reading either as the other wastes the
forward evidence this family is built on. The test is the results store's own
coverage horizon: an event whose MLB date lies past the last settled date is
awaiting settlement; one whose date the store already covers, yet whose game is
missing, is a defect and says so.

The older transaction rows carry no club at all — they were written before
rosterwatch recorded it. They are append-only evidence and are never rewritten,
so they stay permanently unmappable, and the report names them in exactly those
words rather than quietly folding them into a generic failure.
"""

from __future__ import annotations

import csv

from pathlib import Path

from src.pipeline import news, rosterwatch, snapshots, umpirewatch
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

# Unmappable reasons, named once so the report and its tests agree on the
# wording and nothing invents a near-duplicate key.
NOT_YET_PLAYED = "game not yet played (later than the last settled results date)"
GAME_MISSING = "game not in results store (its date IS settled; mapping defect)"
NO_RESULTS = "game not in results store (the results store holds no games)"
TEAM_NOT_RECORDED = ("transaction team not recorded (row predates club "
                     "capture; permanently unmappable, kept as history)")
TEAM_UNKNOWN = "transaction team unknown (the feed row named no club)"
CLUB_GAME_NOT_YET = ("club's next game not yet played (later than the last "
                     "settled results date)")
NO_UPCOMING = "no upcoming stored game for the club"


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
    """Accumulation status per class; pre-registered tables past the floor.

    THE CLASS LIST IS DATA-DRIVEN, NOT HARD-CODED HERE
    ---------------------------------------------------
    `classes` below is built purely from whatever `event["class"]` values
    show up in `all_events` -- there is no fixed roster of class names in
    this function. Admitting `docs/RESEARCH_V3_UMPIRE_CLASS.md`'s
    `umpire_crew_revealed` class (the amendment adding a 5th class to the
    family docs/RESEARCH_V3_TIMING.md froze at 4) is therefore just a second
    events source folded into the same stream, on the same terms as
    rosterwatch's four: a class with zero events today reports 0/30,
    accumulating, exactly like every other class did on its first day.
    """
    all_events = (rosterwatch.events() if store_dir is None
                  else rosterwatch.events(store_dir))
    all_events = all_events + (
        umpirewatch.events() if store_dir is None else umpirewatch.events(store_dir))
    rows = _multibook_rows() if multibook_rows is None else multibook_rows
    by_pk = _games_by_pk() if games is None else games
    tx_rows = news.read() if transactions is None else transactions
    tx_team = {t.get("transaction_id"): t.get("team") for t in tx_rows}
    settled_through = _settled_through(by_pk)

    classes = {}
    for event in all_events:
        bucket = classes.setdefault(event["class"], {
            "events": 0, "admissible": 0, "measurable": 0,
            "unmappable": {}, "excluded": {}, "measured": []})
        bucket["events"] += 1
        if event.get("inadmissible"):
            continue
        bucket["admissible"] += 1
        observed = snapshots.official_date(event["interval"][1])

        game_pk = str(event.get("game_pk") or "")
        if not game_pk and event.get("transaction_id") is not None:
            team = _transaction_team(event, tx_team)
            if team is None:
                _count(bucket["unmappable"],
                       TEAM_UNKNOWN if event.get("team_recorded")
                       else TEAM_NOT_RECORDED)
                continue
            game_pk = _next_game_for(team, event, by_pk)
            if game_pk is None:
                _count(bucket["unmappable"],
                       CLUB_GAME_NOT_YET if _unsettled(observed, settled_through)
                       else NO_UPCOMING)
                continue
        game = by_pk.get(game_pk)
        if not game:
            _count(bucket["unmappable"], _missing_game_reason(
                observed, settled_through))
            continue

        quotes = _quotes_for_game(rows, game)
        measured = eventstudy.measure(
            {"interval": event["interval"]}, quotes,
            game_start=game.get("start_time_utc"))
        # Carried through for src/research/timingtest.py, which needs the
        # mapped game's start time to place each event relative to the dense
        # capture window (docs/RESEARCH_V3_TIMING.md lines ~163-166) and to
        # compute a censoring time for events that never reach 50%-moved
        # before first pitch. eventstudy.measure() cannot know this itself --
        # the join to a game lives entirely in this module.
        measured["game_pk"] = game_pk
        measured["game_start_utc"] = game.get("start_time_utc")
        measured["game_date"] = game.get("date")
        # The event's own recorded bracket, verbatim -- ADDENDUM 2's fix for
        # the floor (RESEARCH_V3_TIMING.md ADDENDUM 2): the capture-spacing
        # floor is interval[1]-interval[0], the LITERAL poll spacing in force
        # at this one event, never inferred from distance-to-first-pitch.
        measured["event_interval"] = event.get("interval")
        # Additive, present only for classes that carry it (today: the
        # transaction feed's own move-type bucket) -- absent entirely for
        # every other class, which is how
        # src.research.timingtest.game_relevant tells "this event has no
        # relevance rule" from "this event failed the relevance rule".
        if "category" in event:
            measured["category"] = event.get("category")
        if event.get("transaction_id") is not None:
            measured["transaction_id"] = event.get("transaction_id")
        away, home = game.get("away_team"), game.get("home_team")
        if away or home:
            measured["matchup"] = f"{away}@{home}"
        if measured.get("excluded") is None:
            bucket["measurable"] += 1
        else:
            _count(bucket["excluded"], _exclusion_key(measured["excluded"]))
        bucket["measured"].append(measured)

    out = {"floor": CLASS_FLOOR, "settled_through": settled_through,
           "classes": {}}
    for name, bucket in sorted(classes.items()):
        entry = {
            "events": bucket["events"],
            "admissible": bucket["admissible"],
            "measurable": bucket["measurable"],
            "unmappable": bucket["unmappable"],
            "excluded": bucket["excluded"],
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
            # Only past the SAME admissible floor the tables above already
            # require -- never below it. src/research/timingtest.py applies
            # its own, stricter gate on top of this (the MEASURABLE count,
            # which is what the pre-registered hypothesis test actually
            # needs rows for) before it ever reads inside this list.
            entry["measured"] = bucket["measured"]
        out["classes"][name] = entry
    return out


def _count(counter, reason) -> None:
    counter[reason] = counter.get(reason, 0) + 1


def _settled_through(by_pk) -> str:
    """The last MLB date the results store actually covers, or "" if empty.

    This is the line between "not played yet" and "should be here and isn't".
    It is read off the store rather than from the wall clock on purpose: what
    matters is what settlement has ingested, not what day it happens to be.
    """
    return max((game.get("date") or "" for game in by_pk.values()), default="")


def _unsettled(observed, settled_through) -> bool:
    """Is this event's own MLB date past the results store's coverage?"""
    return bool(observed) and bool(settled_through) and observed > settled_through


def _missing_game_reason(observed, settled_through) -> str:
    if not settled_through:
        return NO_RESULTS
    return NOT_YET_PLAYED if _unsettled(observed, settled_through) else GAME_MISSING


def _transaction_team(event, tx_team):
    """The club a transaction event is about, from the event or the store.

    The event's own recorded club is authoritative — rosterwatch writes it at
    first sighting, from the same feed row that produced the id. The historical
    transactions store is only a fallback for rows written before that field
    existed; it is a join on a stable id, never a timestamp, so it cannot leak
    anything into the bracket.
    """
    return event.get("team") or tx_team.get(event.get("transaction_id"))


def _exclusion_key(reason) -> str:
    """Stable bucket name for a measurement exclusion.

    eventstudy names the exact book count in its message, which would scatter
    one recurring condition across a dozen near-identical keys.
    """
    if reason and reason.startswith("only "):
        return (f"fewer than {eventstudy.MIN_BOOKS} books quoted in the "
                f"{eventstudy.MAX_PRE_GAP_MINUTES} minutes before the event")
    return reason


def _quotes_for_game(rows, game) -> list:
    """This game's quotes only, matched by club abbreviation and MLB date.

    The multibook store speaks the odds API's full club names and one date
    holds a whole slate; matching by translated abbreviation pair keeps a
    Reds event from being measured against the Padres' board.

    Two canonicalisations, both learned the hard way and both silent when
    wrong — they drop a board rather than raise:

    * DATE. The odds feed's commence_time is UTC; MLB files a game under its
      EASTERN date. Slicing the first ten characters files every West Coast
      night game under tomorrow, so exactly the late slate — the one whose
      lineups post closest to our poll cadence — would find zero quotes.
      `snapshots.official_date` is the same conversion the price stores use.
    * CLUB. The MLB schedule says ATH and AZ where the odds feed's club names
      resolve to OAK and ARI, so the raw comparison dropped those two clubs'
      boards entirely (see `src/analysis/prices.matchup_key`, same lesson).
      Both sides go through `parks.canonical_team`.
    """
    from src.data import parks
    from src.pipeline import slate as slate_mod

    away = parks.canonical_team(game.get("away_team") or "")
    home = parks.canonical_team(game.get("home_team") or "")
    date = game.get("date")
    out = []
    for row in rows or []:
        if snapshots.official_date(row.get("commence_time")) != date:
            continue
        if parks.canonical_team(slate_mod.team_abbrev_from_name(
                row.get("away_team") or "") or "") != away:
            continue
        if parks.canonical_team(slate_mod.team_abbrev_from_name(
                row.get("home_team") or "") or "") != home:
            continue
        out.append({"ts": row.get("observed_utc"), "book": row.get("book"),
                    "away_price": row.get("away_price"),
                    "home_price": row.get("home_price")})
    out.sort(key=lambda q: q.get("ts") or "")
    return out


def _next_game_for(team, event, by_pk):
    """The club's first stored game starting after the event bracket ends.

    Canonical abbreviations on both sides: the transactions feed resolves the
    Athletics and Diamondbacks to OAK and ARI while the results store files
    them as ATH and AZ, so a raw comparison silently loses two clubs' events.
    """
    from src.data import parks

    if not team:
        return None
    team = parks.canonical_team(team)
    end = event["interval"][1]
    best_pk, best_start = None, None
    for game_pk, game in by_pk.items():
        if team not in (parks.canonical_team(game.get("away_team") or ""),
                        parks.canonical_team(game.get("home_team") or "")):
            continue
        start = game.get("start_time_utc") or ""
        if start and start > end and (best_start is None or start < best_start):
            best_pk, best_start = game_pk, start
    return best_pk


def format_report(result) -> str:
    settled = result.get("settled_through")
    lines = [f"results store settled through {settled}"
             if settled else "results store holds no games"]
    for name, entry in result["classes"].items():
        lines.append(f"{name}: {entry['events']} events, "
                     f"{entry['admissible']} admissible, "
                     f"{entry['measurable']} measurable")
        lines.append(f"  {entry['status']}")
        for reason, count in (entry.get("unmappable") or {}).items():
            lines.append(f"  unmappable ({reason}): {count}")
        for reason, count in (entry.get("excluded") or {}).items():
            lines.append(f"  mapped but excluded ({reason}): {count}")
    if not result["classes"]:
        lines.append("no events derived yet; the watch stores are young")
    return "\n".join(lines)
