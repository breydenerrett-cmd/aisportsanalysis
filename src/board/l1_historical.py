"""Projects the 2023-25 odds ARCHIVE into the same PriceObservation rows L1
projects live captures into, as a sibling `src.board.l1` calls -- never a
second output store, never a second record schema.

WHY THIS EXISTS
----------------
`engine slate --date DATE` prices a slate entirely off
`data/processed/l1_observations.jsonl`, which `src.board.l1.run()` builds
exclusively from the LIVE forward-capture stores (odds_multibook,
odds_snapshots, f5_close). The 2023-25 archive
(`data/historical/odds_history/mlb_20{23,24,25}.jsonl` and
`data/historical/odds_first_five/mlb_20{23,24,25}.jsonl`) is a completely
separate store, in a completely different row shape, read only by
`src.evolab.replay` -- so a historical date has zero L1 rows and the S8
preflight guard refuses it outright ("no price capture observed for that
date at all"). This module is the missing projector: it reads the archive's
own row shape and emits the exact same `PriceObservation`-shaped dicts
`src.board.project` already produces for live rows, so `src.board.l1.run()`
can fold both into ONE store through the SAME dedup/grading/game_pk
machinery.

THE ARCHIVE'S ROW SHAPE (verified against the real files, not assumed)
------------------------------------------------------------------------
`odds_history/mlb_<season>.jsonl`: one line per POLL, `{"events": [...],
"markets": [...], "requested_at": ..., "snapshot_at": ...}`. Each `events[]`
entry nests `bookmakers[].markets[].outcomes[]` (the raw Odds-API shape),
outcomes named by TEAM NAME for h2h and "Over"/"Under" (sharing one `point`)
for totals. Verified across all three season files: every line carries
`snapshot_at`; every h2h market's outcome names exactly match the event's
own `home_team`/`away_team`; the ONLY bookmaker-level market keys anywhere
in the store are `h2h` and `totals` -- **no `spreads` market exists in this
archive for any season**, so `spreads` is reported as archive-absent, never
silently produced as zero rows with no explanation.

`odds_first_five/mlb_<season>.jsonl`: one line per (event, poll) -- already
carries the resolved `game_pk` directly (this archive was itself built
against the schedule when captured), plus `data.bookmakers[]` in the same
nested shape, market keys `h2h_1st_5_innings` / `totals_1st_5_innings` only.

A SINGLE, CRITICAL FACT ABOUT THE `snapshot_at` / `requested_at` PAIR
------------------------------------------------------------------------
`odds_history` rows also carry `requested_at` -- when the archive tool
polled -- which is NOT when the book quoted. A far-future game's price does
not change between polls, so the archive tool re-serves the SAME
`snapshot_at` payload under dozens of different `requested_at` values
(measured: one 2023 game returned 23 rows sharing one `snapshot_at` across
23 different `requested_at` stamps a month apart). Treating `requested_at`
as `observed_utc` would fabricate a `observed_utc` value nobody ever
observed the book at -- decision-time-unsafe fabrication of exactly the
kind this project refuses everywhere else. **`observed_utc` is always
`snapshot_at`, and `requested_at` is never read as a timestamp anywhere in
this module.** The resulting duplicate (event, book, market, price,
snapshot_at) tuples across `requested_at` copies collapse for free through
`src.board.l1.run()`'s existing `observation_id`-keyed dedup (that hash
never includes `requested_at`), so this module does not need its own
pre-dedup pass.

HOW COARSE `snapshot_at` ACTUALLY IS (measured, not assumed)
------------------------------------------------------------
Per game, the archive holds about three polls a day; measured directly off
`mlb_2023.jsonl`, the closest two DISTINCT `snapshot_at` values for any
event are never less than ~177 minutes apart, median ~6 hours (matches
`src.evolab.replay`'s own measurement of the same store). `src.capture.
cadence.grade_from_gap` grades a gap <=20min B, <=2h C, else D -- so every
gap in this archive exceeds the C ceiling and every projected row's own
measured `known_at_grade` comes out D. This is COMPUTED here exactly the
way `src.board.l1._grades_for_store` computes it for a live store (the
measured gap to the previous DISTINCT timestamp in the SAME source), keyed
on `snapshot_at` instead of `observed_utc` because that is the field this
archive's raw rows actually carry -- never hand-set to "D" as a shortcut.
See `src.board.l1.run`'s per-source `cadence` report block for the actual
measured min/median/max gap on the season being backfilled.

WHAT MAKES AN ARCHIVE ROW UN-MISTAKABLE FOR A LIVE ONE
---------------------------------------------------------
`PriceObservation.source` is stamped `HISTORICAL_SOURCE` here
("odds_api_historical_archive"), never the live default ("odds_api") --
`src.board.l1.run` now takes the source label from each registered store
(`source_label`) rather than hard-coding one value for everything it
writes. `capture_id` for a row with no matched raw L0 payload (every row
here, since no raw capture exists for 2023-25) is prefixed
`historical_archive:`, distinct from the live backfill's `backfill:`
prefix. `l0_available` is `False` for the same reason it is for a
live-store backfill: no verbatim provider L0 payload exists to point at.
`is_close` is `False` for every row this module emits -- there is no
designated "closing line" concept in this archive (`src.evolab.replay`'s
own module docstring: the last pre-game poll is "NOT a close: median 85
minutes before first pitch"), so nothing here is stamped `is_close=True`
the way `f5_close.jsonl` is for live.

GAME_PK: THE SAME MAP, RESOLVED WITHOUT NETWORK
--------------------------------------------------
`src.board.l1.run()` resolves every row's `game_pk` the SAME way regardless
of source: a lookup into `data/processed/event_game_map.jsonl`
(`src.board.gamekey`'s store). This module never invents a second
resolution path or a second store -- it POPULATES THAT SAME STORE for
archive events, via `ensure_historical_event_map`, before `l1.run()` reads
it. `gamekey.resolve_event` calls the live MLB schedule API; that is wrong
(and unnecessary) for an already-played game, so this module resolves
against `data/historical/mlb_results.csv` instead -- the project's own
closed record of what actually happened, with a real `game_pk` and a real
`start_time_utc` per game, no network involved. Two paths, in order of
confidence:
  1. `odds_first_five` rows already carry the provider's OWN `game_pk`
     (that archive was built against the schedule when captured) -- looked
     up directly against `mlb_results.csv` BY game_pk. Unambiguous by
     construction.
  2. `odds_history` rows carry no `game_pk` at all -- resolved by matching
     (away, home, official date) against `mlb_results.csv`, exactly
     `gamekey.resolve_event`'s own algorithm (team-name normalization via
     `src.pipeline.slate.team_abbrev_from_name` + `src.data.parks.
     canonical_team`, +-1 day widening when the exact date matches
     nothing, nearest-`commence_time` tie-break, `ambiguous=True` with every
     candidate recorded for a genuine doubleheader -- never a silent pick).
Rows are written in `gamekey.resolve_event`'s own OUTPUT SHAPE
(`event_id`, `game_pk`, `resolved`, `ambiguous`, `candidates`,
`schedule_commence_time`, `reason`, ...) so `gamekey.load_map` /
`gamekey.game_pk_for_event` / `src.engine.glue.commence_time_for` read
these rows with zero code changes on their side -- `source` is stamped
`"mlb_results_csv"` (vs. live's `"mlb_schedule"`) purely for provenance;
nothing downstream branches on it. Idempotent the same way `gamekey.
build_map_for_date` is: an `event_id` already in the map is skipped unless
`force=True`.
"""

from __future__ import annotations

import csv
import json
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.board import gamekey as gamekey_module
from src.core.asof import game_pk_key
from src.data import parks
from src.paths import historical_path, processed_path
from src.pipeline import slate as slate_mod
from src.pipeline.snapshots import official_date

# The one thing that makes an archive-sourced PriceObservation impossible to
# mistake for a live one (see module docstring).
HISTORICAL_SOURCE = "odds_api_historical_archive"
HISTORICAL_MAP_SOURCE = "mlb_results_csv"
HISTORICAL_CAPTURE_PREFIX = "historical_archive"

# Every season this archive actually holds a file for (verified: `ls
# data/historical/odds_history/` / `odds_first_five/`). Not the replay lab's
# own (narrower) REPLAY_SEASONS -- this module serves the engine's real L1
# store, not the sandboxed evolab universe, and 2025 archive rows are just
# as real a capture as 2023-24's.
ARCHIVE_SEASONS = (2023, 2024, 2025)

ODDS_HISTORY_DIR = historical_path("odds_history")
ODDS_FIRST_FIVE_DIR = historical_path("odds_first_five")
RESULTS_CSV = historical_path("mlb_results.csv")

KIND_ODDS_HISTORY = "odds_history_archive"
KIND_ODDS_FIRST_FIVE = "odds_first_five_archive"
HISTORICAL_KINDS = (KIND_ODDS_HISTORY, KIND_ODDS_FIRST_FIVE)

# In-scope markets per the task brief (h2h, spreads, totals, F5 h2h) mapped
# onto what this archive can actually be asked to carry. `spreads` has no
# archive representation at all (see module docstring) -- named here so a
# caller can report "0, and here is why" rather than silently omitting it.
IN_SCOPE_MARKETS = ("h2h", "spreads", "totals", "h2h_1st_5_innings")
MARKET_NOT_IN_ARCHIVE = "spreads"


def historical_source_stores(seasons: Iterable[int]) -> list[dict]:
    """`src.board.l1.SOURCE_STORES`-shaped entries for each requested season
    -- one for the main-market archive, one for the first-five archive, both
    only added when the season's file actually exists on disk (a caller
    naming a season this worktree does not carry a file for gets an honest
    `present: False` in the report, never a crash)."""
    stores = []
    for season in sorted(set(int(s) for s in seasons)):
        stores.append({
            "name": f"odds_history_archive_{season}",
            "path": ODDS_HISTORY_DIR / f"mlb_{season}.jsonl",
            "kind": KIND_ODDS_HISTORY,
            "is_close": False,
            "season": season,
            "source_label": HISTORICAL_SOURCE,
            "timestamp_field": "snapshot_at",
        })
        stores.append({
            "name": f"odds_first_five_archive_{season}",
            "path": ODDS_FIRST_FIVE_DIR / f"mlb_{season}.jsonl",
            "kind": KIND_ODDS_FIRST_FIVE,
            "is_close": False,
            "season": season,
            "source_label": HISTORICAL_SOURCE,
            "timestamp_field": "snapshot_at",
        })
    return stores


# ---------------------------------------------------------------------------
# Row projection -- odds-api nested shape -> project.py's flat row contract
# ---------------------------------------------------------------------------

def _outcome_price(outcomes: list, name: str):
    for outcome in outcomes:
        if outcome.get("name") == name:
            return outcome.get("price")
    return None


def _h2h_flat_row(*, event_id, book, observed_utc, book_last_update,
                   outcomes, home_team, away_team,
                   provider_market_key) -> dict | None:
    home_price = _outcome_price(outcomes, home_team)
    away_price = _outcome_price(outcomes, away_team)
    if home_price is None or away_price is None:
        return None
    return {
        "event_id": event_id, "book": book, "observed_utc": observed_utc,
        "book_last_update": book_last_update, "game_pk": None,
        "home_price": home_price, "away_price": away_price,
        "provider_market_key": provider_market_key,
    }


def _totals_flat_row(*, event_id, book, observed_utc, book_last_update,
                      outcomes, market_key, provider_market_key) -> dict | None:
    over = next((o for o in outcomes if o.get("name") == "Over"), None)
    under = next((o for o in outcomes if o.get("name") == "Under"), None)
    if over is None or under is None:
        return None
    point = over.get("point")
    if point is None:
        point = under.get("point")
    if point is None:
        return None
    return {
        "event_id": event_id, "market_key": market_key, "book": book,
        "observed_utc": observed_utc, "book_last_update": book_last_update,
        "game_pk": None, "total": point,
        "over_price": over.get("price"), "under_price": under.get("price"),
        "provider_market_key": provider_market_key,
    }


def _project_h2h(flat: dict, *, market_key: str):
    from src.board.project import project_h2h_row
    return list(project_h2h_row(flat, market_key=market_key))


def _project_line(flat: dict):
    from src.board.project import project_line_market_row
    return project_line_market_row(flat)


def _project_one_market(*, kind_label, event_id, book, observed_utc,
                         book_last_update, outcomes, market_key,
                         home_team=None, away_team=None,
                         provider_market_key=None) -> tuple[list[dict], list[tuple]]:
    """One bookmaker's one market's outcomes -> (observations, refusals).

    Returns per-item refusals rather than raising, because one archive line
    covers MANY (event, book, market) combinations and one bad one must
    never hide every good one on the same line."""
    provider_market_key = provider_market_key or market_key
    if market_key == "h2h" or market_key == "h2h_1st_5_innings":
        flat = _h2h_flat_row(
            event_id=event_id, book=book, observed_utc=observed_utc,
            book_last_update=book_last_update, outcomes=outcomes,
            home_team=home_team, away_team=away_team,
            provider_market_key=provider_market_key)
        if flat is None:
            return [], [(f"{kind_label}_h2h_outcome_mismatch", {
                "event_id": event_id, "book": book, "market_key": market_key,
                "home_team": home_team, "away_team": away_team,
                "outcome_names": [o.get("name") for o in outcomes],
            })]
        return _project_h2h(flat, market_key=market_key), []

    if market_key == "totals" or market_key == "totals_1st_5_innings":
        flat = _totals_flat_row(
            event_id=event_id, book=book, observed_utc=observed_utc,
            book_last_update=book_last_update, outcomes=outcomes,
            market_key=market_key, provider_market_key=provider_market_key)
        if flat is None:
            return [], [(f"{kind_label}_totals_incomplete", {
                "event_id": event_id, "book": book, "market_key": market_key,
                "outcome_names": [o.get("name") for o in outcomes],
            })]
        return _project_line(flat), []

    # A market this archive's own survey (module docstring) never actually
    # produces (e.g. a hypothetical future "spreads" line) -- refused by
    # name rather than silently dropped or silently priced.
    return [], [(f"{kind_label}_market_not_in_scope:{market_key}", {
        "event_id": event_id, "book": book, "market_key": market_key,
    })]


def project_odds_history_row(row: Mapping[str, Any]) -> tuple[list[dict], list[tuple]]:
    """One `odds_history/mlb_<season>.jsonl` line (a poll, many events) ->
    (observations, refusals). `observed_utc` is ALWAYS this line's own
    `snapshot_at` -- see module docstring on why `requested_at` is never
    used. A line with no `snapshot_at` at all refuses EVERY market on it by
    name rather than guessing an instant nobody recorded."""
    observed_utc = row.get("snapshot_at")
    observations: list[dict] = []
    refusals: list[tuple] = []
    for event in row.get("events") or []:
        event_id = event.get("id")
        home_team = event.get("home_team")
        away_team = event.get("away_team")
        if not observed_utc:
            refusals.append(("historical_no_usable_timestamp", {
                "event_id": event_id, "store": "odds_history",
            }))
            continue
        for bookmaker in event.get("bookmakers") or []:
            book = bookmaker.get("key")
            for market in bookmaker.get("markets") or []:
                market_key = market.get("key")
                book_last_update = market.get("last_update") or bookmaker.get("last_update")
                obs, refused = _project_one_market(
                    kind_label="historical",
                    event_id=event_id, book=book, observed_utc=observed_utc,
                    book_last_update=book_last_update,
                    outcomes=market.get("outcomes") or [],
                    market_key=market_key, home_team=home_team,
                    away_team=away_team)
                observations.extend(obs)
                refusals.extend(refused)
    return observations, refusals


def project_odds_first_five_row(row: Mapping[str, Any]) -> tuple[list[dict], list[tuple]]:
    """One `odds_first_five/mlb_<season>.jsonl` line (one event, one poll) ->
    (observations, refusals). `observed_utc` is this line's own
    `snapshot_at` (verified present on every real row; still checked, never
    assumed)."""
    observed_utc = row.get("snapshot_at")
    event_id = row.get("event_id")
    data = row.get("data") or {}
    home_team = data.get("home_team")
    away_team = data.get("away_team")
    if not observed_utc:
        return [], [("historical_no_usable_timestamp", {
            "event_id": event_id, "store": "odds_first_five",
        })]
    observations: list[dict] = []
    refusals: list[tuple] = []
    for bookmaker in data.get("bookmakers") or []:
        book = bookmaker.get("key")
        for market in bookmaker.get("markets") or []:
            market_key = market.get("key")
            book_last_update = market.get("last_update") or bookmaker.get("last_update")
            obs, refused = _project_one_market(
                kind_label="historical_f5",
                event_id=event_id, book=book, observed_utc=observed_utc,
                book_last_update=book_last_update,
                outcomes=market.get("outcomes") or [],
                market_key=market_key, home_team=home_team,
                away_team=away_team)
            observations.extend(obs)
            refusals.extend(refused)
    return observations, refusals


# ---------------------------------------------------------------------------
# game_pk / commence_time resolution against mlb_results.csv -- no network
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _team_key(name: str | None) -> str | None:
    """Same two-step normalization `gamekey._team_key` uses (full club name
    -> abbreviation -> canonical alias), duplicated here in miniature rather
    than imported: it is six lines, and importing another module's
    underscore-prefixed helper would couple this module to gamekey's
    private internals rather than its public map contract."""
    if not isinstance(name, str) or not name.strip():
        return None
    abbrev = slate_mod.team_abbrev_from_name(name)
    candidate = abbrev if abbrev else name.strip().upper()
    canonical = parks.canonical_team(candidate)
    return canonical if canonical in parks.PARKS else None


def _parse_utc(value: str | None):
    if not value:
        return None
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_results_index(path: Path | str = RESULTS_CSV) -> dict:
    """`data/historical/mlb_results.csv` indexed two ways for the two
    resolution paths this module needs: `by_pk` (canonical game_pk string ->
    row) for `odds_first_five`'s embedded game_pk, and `by_team_date`
    ((away, home, date) -> [row, ...]) for `odds_history`'s team/date join.
    Both indexes are built off the SAME canonicalized abbreviations
    (`parks.canonical_team`) `_team_key` produces, so a spelling alias on
    either side (mlb_results.csv's "ATH"/"AZ" vs. the odds feed's "OAK"/
    "ARI"-style full names) can never silently fail to match."""
    by_pk: dict[str, dict] = {}
    by_team_date: dict[tuple, list] = {}
    target = Path(path)
    if not target.exists():
        return {"by_pk": by_pk, "by_team_date": by_team_date}
    with target.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pk = game_pk_key(row.get("game_pk"))
            if pk is None:
                continue
            away = parks.canonical_team(row.get("away_team", ""))
            home = parks.canonical_team(row.get("home_team", ""))
            entry = {
                "game_pk": pk, "date": row.get("date"),
                "start_time_utc": row.get("start_time_utc"),
                "away_team": away, "home_team": home,
            }
            by_pk[pk] = entry
            by_team_date.setdefault((away, home, row.get("date")), []).append(entry)
    return {"by_pk": by_pk, "by_team_date": by_team_date}


def _now_iso(now: datetime | None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def resolve_historical_by_pk(event_id: str, home_team: str, away_team: str,
                              commence_time: str, game_pk_hint: str,
                              results_index: Mapping, *,
                              now: datetime | None = None) -> dict:
    """`odds_first_five`'s own embedded `game_pk` -> a resolution row, by
    confirming it against `mlb_results.csv` (never trusted un-confirmed --
    a `game_pk` this project's own results file has never heard of is not
    resolved, it is refused with a reason)."""
    base = {
        "event_id": event_id, "home_team": home_team, "away_team": away_team,
        "commence_time": commence_time, "source": HISTORICAL_MAP_SOURCE,
        "resolved_utc": _now_iso(now),
    }
    pk = game_pk_key(game_pk_hint)
    entry = results_index["by_pk"].get(pk) if pk else None
    if entry is None:
        return {
            **base, "game_pk": None, "resolved": False, "ambiguous": False,
            "candidates": [], "schedule_commence_time": None,
            "reason": (f"odds_first_five's own game_pk {game_pk_hint!r} was "
                       "not found in data/historical/mlb_results.csv"),
        }
    return {
        **base, "game_pk": pk, "resolved": True, "ambiguous": False,
        "candidates": [], "schedule_commence_time": entry["start_time_utc"],
        "reason": None,
    }


def resolve_historical_by_team_date(event_id: str, home_team: str,
                                     away_team: str, commence_time: str,
                                     results_index: Mapping, *,
                                     now: datetime | None = None) -> dict:
    """`odds_history`'s (no embedded game_pk) events -> a resolution row,
    matched against `mlb_results.csv` by (away, home, official date), +-1
    day widened, nearest-`commence_time` tie-break -- the same algorithm
    `gamekey.resolve_event` runs against the live schedule API, run here
    against the closed historical record instead (see module docstring)."""
    base = {
        "event_id": event_id, "home_team": home_team, "away_team": away_team,
        "commence_time": commence_time, "source": HISTORICAL_MAP_SOURCE,
        "resolved_utc": _now_iso(now),
    }
    away_key = _team_key(away_team)
    home_key = _team_key(home_team)
    commence_dt = _parse_utc(commence_time)
    if not away_key or not home_key or commence_dt is None:
        return {
            **base, "game_pk": None, "resolved": False, "ambiguous": False,
            "candidates": [], "schedule_commence_time": None,
            "reason": (f"could not normalize team names or commence_time "
                       f"(away={away_team!r} home={home_team!r} "
                       f"commence_time={commence_time!r})"),
        }

    by_team_date = results_index["by_team_date"]
    center_date = official_date(commence_time)
    candidates = list(by_team_date.get((away_key, home_key, center_date), []))
    if not candidates:
        center_dt = _date.fromisoformat(center_date)
        for day in ((center_dt - timedelta(days=1)).isoformat(),
                    (center_dt + timedelta(days=1)).isoformat()):
            candidates.extend(by_team_date.get((away_key, home_key, day), []))

    if not candidates:
        return {
            **base, "game_pk": None, "resolved": False, "ambiguous": False,
            "candidates": [], "schedule_commence_time": None,
            "reason": (f"no mlb_results.csv game matched {away_key}@{home_key} "
                       f"within a day of {commence_time}"),
        }

    def _delta(entry: dict) -> float:
        start = _parse_utc(entry.get("start_time_utc"))
        return abs((start - commence_dt).total_seconds()) if start else float("inf")

    candidates.sort(key=_delta)
    best = candidates[0]
    ambiguous = len(candidates) > 1
    reason = None
    if ambiguous:
        reason = (f"{len(candidates)} mlb_results.csv games matched "
                  f"{away_key}@{home_key} (doubleheader) -- picked game_pk "
                  f"{best['game_pk']} by nearest commence_time")
    return {
        **base, "game_pk": best["game_pk"], "resolved": True,
        "ambiguous": ambiguous,
        "candidates": ([{"game_pk": c["game_pk"],
                         "start_time_utc": c["start_time_utc"]}
                        for c in candidates] if ambiguous else []),
        "schedule_commence_time": best["start_time_utc"], "reason": reason,
    }


def historical_events_for_season(season: int) -> dict[str, dict]:
    """Every distinct odds-archive event for `season`, across BOTH archive
    files, as `{event_id: {home_team, away_team, commence_time,
    game_pk_hint, store}}`. `game_pk_hint` is only ever set for
    `odds_first_five` events (the only archive that embeds one); an
    `odds_history` event's hint is `None` and is resolved by team/date
    instead (see `ensure_historical_event_map`)."""
    events: dict[str, dict] = {}

    history_path = ODDS_HISTORY_DIR / f"mlb_{season}.jsonl"
    for row in _read_jsonl(history_path):
        for event in row.get("events") or []:
            event_id = event.get("id")
            if not event_id or event_id in events:
                continue
            events[event_id] = {
                "home_team": event.get("home_team"),
                "away_team": event.get("away_team"),
                "commence_time": event.get("commence_time"),
                "game_pk_hint": None,
                "store": "odds_history",
            }

    f5_path = ODDS_FIRST_FIVE_DIR / f"mlb_{season}.jsonl"
    for row in _read_jsonl(f5_path):
        event_id = row.get("event_id")
        if not event_id or event_id in events:
            continue
        data = row.get("data") or {}
        events[event_id] = {
            "home_team": data.get("home_team"),
            "away_team": data.get("away_team"),
            "commence_time": data.get("commence_time") or row.get("commence_time"),
            "game_pk_hint": row.get("game_pk"),
            "store": "odds_first_five",
        }
    return events


def ensure_historical_event_map(
    seasons: Iterable[int], *,
    map_path: Path | str = gamekey_module.DEFAULT_MAP_PATH,
    results_csv: Path | str = RESULTS_CSV,
    now: datetime | None = None,
    force: bool = False,
) -> dict:
    """Resolve every archive event for `seasons` against `mlb_results.csv`
    and append new rows to `map_path` -- the SAME `event_game_map.jsonl`
    store `src.board.gamekey` owns, in that store's own row shape, so
    `gamekey.load_map`/`game_pk_for_event` and `src.engine.glue.
    commence_time_for` read them with zero changes on their side (module
    docstring). Idempotent: an `event_id` already in the map is skipped
    unless `force=True` -- the same discipline `gamekey.build_map_for_date`
    uses for the live map."""
    existing = gamekey_module.load_map(map_path)
    results_index = read_results_index(results_csv)

    report: dict[str, Any] = {
        "seasons": sorted(set(int(s) for s in seasons)),
        "map_path": str(map_path), "candidates": 0, "resolved": 0,
        "ambiguous": 0, "unresolved": 0, "skipped_already_mapped": 0,
        "rows_written": 0, "by_season": {},
    }
    new_rows: list[dict] = []
    for season in report["seasons"]:
        events = historical_events_for_season(season)
        season_report = {"candidates": len(events), "resolved": 0,
                         "ambiguous": 0, "unresolved": 0,
                         "skipped_already_mapped": 0, "rows_written": 0}
        report["candidates"] += len(events)
        for event_id in sorted(events):
            if event_id in existing and not force:
                season_report["skipped_already_mapped"] += 1
                report["skipped_already_mapped"] += 1
                continue
            meta = events[event_id]
            if meta["game_pk_hint"] is not None:
                entry = resolve_historical_by_pk(
                    event_id, meta["home_team"], meta["away_team"],
                    meta["commence_time"], meta["game_pk_hint"],
                    results_index, now=now)
            else:
                entry = resolve_historical_by_team_date(
                    event_id, meta["home_team"], meta["away_team"],
                    meta["commence_time"], results_index, now=now)
            if not entry["resolved"]:
                season_report["unresolved"] += 1
                report["unresolved"] += 1
            elif entry["ambiguous"]:
                season_report["ambiguous"] += 1
                report["ambiguous"] += 1
            else:
                season_report["resolved"] += 1
                report["resolved"] += 1
            new_rows.append(entry)
            season_report["rows_written"] += 1
        report["by_season"][str(season)] = season_report

    if new_rows:
        target = Path(map_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    report["rows_written"] = len(new_rows)
    return report
