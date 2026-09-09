"""Historical posted-lineup store: resumable, per-date cached, honest about off-days.

WHY POSTED LINEUPS NEED THEIR OWN STORE
---------------------------------------
The rebuilt detectors reason about the nine hitters actually sent out, not the
club in aggregate, and they need that for PAST games. `lineups.fetch_lineups`
returns the posted lineup for any historical date -- the schedule hydrate keeps
it -- but two full seasons is ~370 dates of network calls, and a run that long
WILL be interrupted. So lineups are fetched once per date and appended to a
JSONL store, exactly the shape `bullpen.build_log` already proved out.

WHY THE EMPTY MARKER IS NOT OPTIONAL
------------------------------------
A date with no rows is ambiguous: an off-day, or a date the build never reached.
Those are different facts, and confusing them puts silent holes in the backtest
while looking like complete coverage. Every attempted date therefore writes
something -- lineup rows, or an explicit {"date", "empty": true} marker -- so
absence from the file always means "never fetched" and nothing else.

WHY HANDEDNESS IS EXTENDED HERE
-------------------------------
The detectors read lineups next to bat sides. Handedness is biographical and
stable, so the cheap move is to collect every person_id the build saw and top up
the shared handedness cache once at the end, rather than per date or -- worse --
at detector time, when a network call would be a surprise.

WHY `refresh` EXISTS, AND WHY PLAIN `resume` WAS SILENTLY LOSING GAMES
----------------------------------------------------------------------
`resume=True` was written for the historical backfill, where a date is a
CLOSED fact: every lineup of 2023-06-01 had posted years before the build
reached it, so "this date is already in the store" and "this date is complete"
were the same statement, and skipping the date was exactly right.

They are not the same statement for a date still in progress. Lineups drop in
waves through the afternoon, so the first pass over TODAY stores whatever has
posted by then, marks the date covered, and every later pass skips it -- and
the games that posted afterwards are never collected, not that evening and not
the next morning either, because by then the date is "already covered" too.
Measured on this repo 2026-09-08: the store held 10 of the day's 15 games, and
those 5 were unreachable by any subsequent `build` call. `daily_loop.sh`'s own
docstring had predicted the shape of this ("a lineup posted after this step
runs ... never becomes coverage") without anyone noticing it was already
happening.

`refresh` names the dates the caller knows are still moving. Those are
re-fetched even when covered, and the append is decided PER GAME rather than
per date, so a refresh costs one schedule request and writes only what is
genuinely new. The historical backfill passes nothing and behaves exactly as
before.

A refresh appends a game already stored only when the fetched card is STRICTLY
MORE COMPLETE (more filled batting-order slots) than the stored one -- the case
where a pass caught a game mid-posting, with the home nine up and the away side
still blank. A same-size CHANGE (a late scratch) is deliberately NOT appended:
`data/watch/lineups_watch.jsonl` is this project's change log for lineups and
already brackets every edit with the poll that saw it, whereas rewriting a
posted lineup here would silently change the input a published research row was
computed from. Rejected alternative: append every observed difference and let
`read()` take the last row. It is one line shorter and it makes an already-
frozen row non-reproducible, which costs more than a scratch does.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from src.paths import data_path, evidence_path, historical_path
from src.pipeline import lineups
from src.providers import mlb

DEFAULT_STORE = historical_path("lineups.jsonl")

# The two stores `slate_due` reads. Named here rather than passed in by every
# caller so the shell scripts that call it stay one line long and cannot drift
# apart on which files the question is asked of.
#
# `lineups_watch.jsonl` and not this module's own store, deliberately: the
# watch store is COMMITTED (data/watch is staged by every capture pass) while
# data/historical is git-ignored and reaches a runner only through a cache, so
# asking the watch store gives the same answer on a fresh checkout as on a
# long-lived one. `decisions_v2.jsonl` is committed for the same reason.
LINEUPS_WATCH_PATH = data_path("watch", "lineups_watch.jsonl")
DECISIONS_PATH = evidence_path("decisions_v2.jsonl")

# Light throttle between dates. The schedule endpoint is cheap, but ~370 dates
# back to back is exactly the shape of traffic that gets a client rate-limited.
THROTTLE_SECONDS = 0.3


class LineupStoreError(RuntimeError):
    """Raised when the lineup store cannot be built or read."""


def _iso_date(value) -> str:
    return value.isoformat() if isinstance(value, date) else str(value).strip()


def _filled_slots(row) -> int:
    """How many batting-order slots of a stored/fetched card carry a player.

    The completeness measure a refresh compares on. Counting SLOTS rather than
    truthiness of the two lists is what makes a half-posted card (one side up,
    the other still blank) rank below the same game once both sides land.
    """
    return sum(1 for side in ("away", "home")
               for slot in (row.get(side) or []) if slot.get("person_id"))


def build(dates, path=DEFAULT_STORE, resume=True, refresh=(), on_date=None,
          fetch=lineups.fetch_lineups, fetch_handedness=lineups.fetch_handedness,
          sleep=time.sleep, timeout=20) -> dict:
    """Fetch posted lineups for each date and append them to the store.

    Resumable by date: a date already present in the store (as rows or as an
    empty marker) is skipped, so an interrupted build continues rather than
    refetching. `refresh` overrides that skip for the dates a caller knows are
    still filling in -- see the module docstring for why a date being PRESENT
    and a date being COMPLETE are the same statement only for a closed
    historical date. `fetch`, `fetch_handedness` and `sleep` are injected so
    tests run without the network or the wait.

    The report distinguishes the two ways a game reaches the store, because
    they mean different things operationally: `games` counts every row this
    call appended, and `topped_up` counts the subset that landed on a date the
    store already covered -- exactly the games a plain `resume` pass would have
    lost. A run whose `topped_up` is persistently zero on a live date is either
    a slate where nothing posted late or a cadence that is not running.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # One read, two indexes: which dates were ever ATTEMPTED (the resume
    # question) and how complete each stored game already is (the per-game
    # top-up question). Reading the store twice for these would double the
    # cost of the one part of this function that is not a network call.
    covered: set = set()
    stored: dict = {}
    for row in _read_rows(path):
        iso = row.get("date")
        if iso:
            covered.add(iso)
        if row.get("empty") or not row.get("game_pk"):
            continue
        key = (iso, str(row["game_pk"]))
        stored[key] = max(stored.get(key, 0), _filled_slots(row))
    if not resume:
        covered = set()

    refresh_dates = {_iso_date(value) for value in refresh or ()}

    report = {"dates": 0, "skipped": 0, "games": 0, "failed": 0,
              "topped_up": 0, "refreshed": 0}
    person_ids = set()
    throttled = False
    for value in dates:
        iso = _iso_date(value)
        already_covered = iso in covered
        if already_covered and iso not in refresh_dates:
            report["skipped"] += 1
            continue
        if throttled:
            sleep(THROTTLE_SECONDS)
        throttled = True
        try:
            day = fetch(iso, timeout=timeout)
        except mlb.MLBError:
            # A failed date is left ABSENT, not marked empty -- absent means
            # "never fetched", and a rerun with resume=True will retry it.
            report["failed"] += 1
            continue

        rows = []
        for game_pk in sorted(day):
            record = day[game_pk]
            row = {"date": iso, "game_pk": game_pk,
                   "away": record.get("away") or [],
                   "home": record.get("home") or []}
            # WHEN we saw this card, recorded only when the fetcher told us.
            # Never stamped from a local clock on a path that did not observe
            # the fetch: a made-up observation time is worse than none, and
            # this field is what makes "the store went stale" answerable at
            # all -- before it existed, a store frozen at 10:00Z and a store
            # refreshed all afternoon were byte-for-byte indistinguishable.
            if record.get("posted_at"):
                row["observed_utc"] = record["posted_at"]
            key = (iso, str(game_pk))
            if key not in stored:
                rows.append(row)
                stored[key] = _filled_slots(row)
            elif _filled_slots(row) > stored[key]:
                rows.append(row)
                stored[key] = _filled_slots(row)
                report["topped_up"] += 1

        with target.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            # The marker answers "was this date ever attempted", so it is
            # written once, on the first attempt. A refresh pass that finds
            # nothing new writes nothing: a second marker would say only that
            # the cadence ran, which the run log already says.
            if not day and not already_covered:
                handle.write(json.dumps({"date": iso, "empty": True}) + "\n")

        for row in rows:
            for side in ("away", "home"):
                for slot in row[side]:
                    if slot.get("person_id"):
                        person_ids.add(slot["person_id"])
        covered.add(iso)
        report["dates"] += 1
        report["games"] += len(rows)
        if already_covered:
            report["refreshed"] += 1
        if on_date:
            on_date({"date": iso, "games": len(rows)})

    # One top-up at the end rather than per date: fetch_handedness skips ids
    # already cached and batches the rest in chunks itself.
    if person_ids:
        fetch_handedness(sorted(person_ids), timeout=timeout)
    report["person_ids"] = len(person_ids)
    report["path"] = str(target)
    return report


def read(path=DEFAULT_STORE) -> dict:
    """Stored lineups keyed by game_pk. Empty markers are coverage, not games.

    Keys are str, not the int JSON preserved from the schedule: the results
    store round-trips game_pk through CSV, so its keys come back as str, and a
    join between the two stores must agree on type or it silently matches
    nothing (this exact str/int mismatch once silently broke a since-deleted
    bullpen-grading module -- it always found zero matches and nobody noticed).

    LAST ROW WINS, and that is the point: `build`'s refresh path appends a
    second row for a game only when the fetched card is strictly more complete
    than the stored one, so the last row for a game_pk is always the fullest
    card the store has seen. Reading it back in file order therefore resolves a
    half-posted card to its completed self without any dedup pass here.
    """
    return {str(row["game_pk"]): row for row in _read_rows(path)
            if not row.get("empty") and row.get("game_pk")}


def covered_dates(path=DEFAULT_STORE) -> set:
    """Every date the build actually attempted, off-days included."""
    return {row.get("date") for row in _read_rows(path) if row.get("date")}


def slate_due(watch_path=LINEUPS_WATCH_PATH,
              decisions_path=DECISIONS_PATH) -> dict:
    """Has a complete posted lineup landed since the last frozen decision set?

    The gate the intraday cadence runs on. Genomes refuse until a lineup posts
    (`eligibility.require_lineup`), so the moment a lineup lands is the moment
    a genome's answer can change -- and until one does, another slate pass can
    only re-freeze what the last one already said. Without a gate, a capture
    cadence would append a full decision set (hundreds of null-baseline rows on
    a 15-game slate) every slot, all day, carrying no new information.

    Returns `{"due", "reason", "newest_lineup_utc", "last_decision_utc"}`.
    `reason` is a sentence for the run log either way: a pass that did not run
    must say what it was waiting on, the same way a genome that stands down
    says NO_LINEUP rather than going silent.

    STATELESS ON PURPOSE. It keeps no marker of its own and reads only stores
    that are committed, so a fresh runner and a long-lived checkout reach the
    same verdict. A marker file would have to live under a git-ignored path,
    which on a fresh Actions checkout reads as "never ran" and would make this
    fire on every single slot -- the exact failure it exists to prevent.

    A missing or unreadable store answers "not due" with that as the reason.
    Refusing to run an extra pass is the safe direction: the scheduled 10:00Z
    and afternoon passes are unaffected either way, so a false SKIP costs one
    optional pass while a false RUN costs a ledger full of duplicate rows.

    BOTH SIDES REQUIRED. A card with the home nine up and the away side still
    blank does not satisfy `require_lineup` (`build_snapshot` derives
    `lineup_posted` from both `home_lineup` AND `away_lineup` being present as
    of `t`), so counting it here would fire a pass that cannot decide anything.
    """
    newest_lineup = ""
    for row in _iter_jsonl(watch_path):
        if row.get("poll") or not row.get("game_pk"):
            continue
        if not (row.get("home_lineup") and row.get("away_lineup")):
            continue
        seen = row.get("observed_utc") or row.get("fetched_utc") or ""
        if seen > newest_lineup:
            newest_lineup = seen

    # `recorded_utc` -- the instant a pass actually WROTE -- not
    # `decision_utc`, which is the instant the decision was made AS OF and can
    # sit hours earlier than the write (src.engine.slate.decision_time_for_game
    # picks the latest capture before first pitch). Comparing a lineup sighting
    # against `decision_utc` would keep re-firing passes for a set already
    # frozen.
    last_decision = ""
    for row in _iter_jsonl(decisions_path):
        recorded = row.get("recorded_utc") or ""
        if recorded > last_decision:
            last_decision = recorded

    if not newest_lineup:
        reason = "no game has a complete posted lineup yet"
    elif newest_lineup > last_decision:
        reason = ("newest complete posted lineup %s is newer than the last "
                  "frozen decision set %s"
                  % (newest_lineup, last_decision or "(none)"))
    else:
        reason = ("no lineup has posted since the last frozen decision set %s"
                  % last_decision)
    return {"due": bool(newest_lineup) and newest_lineup > last_decision,
            "reason": reason,
            "newest_lineup_utc": newest_lineup or None,
            "last_decision_utc": last_decision or None}


def _iter_jsonl(path):
    """Rows of a JSONL store, tolerating absence and a torn last line.

    Deliberately NOT `_read_rows`, which raises `LineupStoreError` on a bad
    line: that is right for this module's own store (a corrupt lineup row is a
    bug worth stopping for) and wrong for `slate_due`, which reads two stores
    it does not own and whose job is to answer a scheduling question without
    ever being the reason a capture pass fails.
    """
    target = Path(path)
    if not target.exists():
        return
    try:
        handle = target.open(encoding="utf-8")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _read_rows(path) -> list:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise LineupStoreError(f"{target}:{number} is not valid JSON") from exc
    return rows
