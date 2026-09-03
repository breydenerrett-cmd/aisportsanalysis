"""The L1 backfill: project every existing price store into PriceObservation rows.

WHY THIS EXISTS
----------------
docs/ARCHITECTURE_BETTING_ENGINE.md section 3 names L1 as "PriceObservation /
InformationEvent partitions ... deterministic projection of L0" and section 8
gate G0 requires the projection to reproduce the legacy stores row for row.
Nothing before this module ever wrote a PriceObservation to disk -- every
price this project has captured lives only in the pre-catalogue shapes
(odds_multibook.jsonl, odds_snapshots.jsonl, f5_close.jsonl). This module
reads all of them and every raw L0 capture under data/raw/oddsapi/**, and
projects the union into ONE append-only store, data/processed/l1_observations.jsonl.

DETERMINISM AND IDEMPOTENCY
----------------------------
Every emitted row carries an `observation_id`: sha256 of the fields that
identify ONE fact from ONE source row (source store name, sport, event_id,
market_key, selection_id, book, observed_utc, price_american), truncated to
20 hex characters. Two runs over the same inputs produce the same ids, so a
re-run against unmodified source stores writes zero new rows -- `run()` loads
every id already on disk before projecting a single row and skips anything
it has already written.

RAW-FIRST
---------
Per S6 / gate G0, a row is only as good as its source: when a raw L0 capture
(data/raw/oddsapi/<yyyy>/<mm>/<dd>/<capture_id>.jsonl.gz) can be matched to
the observation being projected -- same event, book, market, side, and a
`captured_utc` within `RAW_MATCH_WINDOW_SECONDS` of the processed row's
`observed_utc` -- the row is stamped `l0_available=True` and carries that
capture's id. No raw file exists for this worktree's captures (see report),
so every row backfilled here is stamped `l0_available=False`, which is
exactly the S6 contract: never quote a backfilled row as byte-reproducible
from provider L0 when no verbatim L0 was actually found.

GRADE, NOT ASSERTED
--------------------
Per guard 1 / F10, `known_at_grade` is never assigned from a schedule. It is
computed the same way src/capture/cadence.py computes it: the gap between an
observation's own `observed_utc` and the previous DISTINCT `observed_utc`
seen in the SAME source store, run through `cadence.grade_from_gap`. A
store's very first observed instant has no prior gap to measure, so it is
stamped grade D rather than assumed.

WHAT THIS MODULE VALIDATED AGAINST THE REAL STORES (not left an assumption)
----------------------------------------------------------------------------
`src/board/project.py`'s `project_line_market_row` docstring flagged its
field-name assumptions as unverified. Reading the actual
odds_snapshots.jsonl rows found two things that assumption got wrong for the
real data, both fixed in project.py rather than reshaping the data:
  1. spreads rows carry a PER-SIDE line (`home_line`/`away_line`), not one
     line shared by both sides -- home_line=-1.5 next to away_line=+1.5 in
     the same row. Folding one onto the other would hash the wrong
     selection_id for one side.
  2. totals rows key their shared line as `total`, not `point` or `line`.
Both are additive fixes (project_line_market_row now checks per-side keys
first, and accepts `total` as a third common-line alias) -- the existing
fixture-driven tests in tests/test_board_project.py are untouched and still
pass.

The odds_snapshots.jsonl row shape itself nests its market fields one level
down, under `prices` (`{"market": "spreads", "prices": {"home_line": ...}}`),
which is a store-shape fact rather than a projection-identity fact, so it is
flattened here (`_flatten_snapshot_row`) before handing the row to
project_line_market_row -- project.py's contract stays "flat row in".
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.board import gamekey
from src.board.project import project_h2h_row, project_line_market_row
from src.board.record import RecordValidationError, price_observation_from_dict
from src.capture.cadence import grade_from_gap
from src.core.asof import game_pk_key
from src.paths import processed_path, raw_path

OUTPUT_PATH = processed_path("l1_observations.jsonl")
RAW_ROOT = raw_path("oddsapi")
# S1 (docs/CHECKPOINT_PHASE0_2026-09-03.md): the event_id -> game_pk map
# `python3 -m src.cli gamekey --date DATE` builds. L1 READS this store; it
# never resolves against the schedule itself (see gamekey.py's own module
# docstring on why resolution is a separate, network-touching step kept out
# of the backfill's own code path).
EVENT_GAME_MAP_PATH = gamekey.DEFAULT_MAP_PATH

# How close a raw capture's own `captured_utc` must land to a processed row's
# `observed_utc` to be considered the SAME capture. The raw write happens
# inside the same provider call that produces the payload later stamped with
# `observed_utc` by the caller (snapshots.capture()), so the two clocks are
# expected to be seconds apart, never minutes.
RAW_MATCH_WINDOW_SECONDS = 120

_DEFAULT_SPORT = "mlb"
_DEFAULT_REGION = "us"
_DEFAULT_SOURCE = "odds_api"

# Every source store this backfill knows how to read, and how each one's
# rows are shaped. `market_key` is the market a row's shape implies when the
# row itself does not carry one (legacy h2h-only stores); `is_close` marks a
# store as belonging to the sealed close partition per design-data-first.md.
SOURCE_STORES = (
    {
        "name": "odds_multibook",
        "path": processed_path("odds_multibook.jsonl"),
        "kind": "multibook",
        "is_close": False,
    },
    {
        "name": "odds_snapshots",
        "path": processed_path("odds_snapshots.jsonl"),
        "kind": "snapshot",
        "is_close": False,
    },
    {
        "name": "f5_close",
        "path": processed_path("f5_close.jsonl"),
        "kind": "h2h_flat",
        "is_close": True,
    },
    # closing_*.jsonl stores are named in the task brief but do not exist yet
    # in any tracked data directory this backfill can see; they are
    # discovered by glob below so a future closing_* store is picked up
    # without a code change, rather than hardcoded here as a store that
    # cannot currently be read.
)


class RefusalReport:
    """Rows this backfill saw but declined to write, with why."""

    def __init__(self) -> None:
        self.by_reason: dict[str, int] = {}
        self.examples: dict[str, list[dict]] = {}

    def add(self, reason: str, row: dict, max_examples: int = 3) -> None:
        self.by_reason[reason] = self.by_reason.get(reason, 0) + 1
        bucket = self.examples.setdefault(reason, [])
        if len(bucket) < max_examples:
            bucket.append(row)

    @property
    def total(self) -> int:
        return sum(self.by_reason.values())


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _discover_closing_stores(processed_dir: Path) -> list[dict]:
    """`closing_*.jsonl` stores named in the task brief -- none exist in this
    worktree's tracked data (checked: `data/processed/closing_*.jsonl` has no
    matches), so this is a glob, not a hardcoded list, and correctly yields
    nothing here rather than claiming a source that isn't there."""
    found = []
    if not processed_dir.exists():
        return found
    for path in sorted(processed_dir.glob("closing_*.jsonl")):
        found.append({
            "name": path.stem,
            "path": path,
            "kind": "h2h_flat",
            "is_close": True,
        })
    return found


def _flatten_snapshot_row(row: Mapping[str, Any]) -> dict:
    """odds_snapshots.jsonl nests its market fields one level down, under
    `prices` (see src/pipeline/snapshots.py `capture`: `"prices": {k: v for
    k, v in market.items() if k not in ("book", "last_update")}`). Flattened
    here so project.py's projectors keep their flat-row contract."""
    flat = {k: v for k, v in row.items() if k != "prices"}
    flat.update(row.get("prices") or {})
    flat.setdefault("market_key", row.get("market", "h2h"))
    return flat


def _observation_id(source_name: str, obs: Mapping[str, Any]) -> str:
    parts = (
        source_name,
        obs["sport"],
        obs["event_id"],
        obs["market_key"],
        obs["selection_id"],
        obs["book"],
        obs["observed_utc"],
        str(obs["price_american"]),
    )
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:20]


def _project_source_row(source: dict, row: dict) -> tuple[list[dict], str | None]:
    """One raw source-store row -> (observations, refusal_reason_or_None)."""
    kind = source["kind"]
    try:
        if kind == "multibook":
            if row.get("market") in (None, "h2h"):
                return list(project_h2h_row(row, market_key="h2h")), None
            flat = dict(row)
            flat["market_key"] = row["market"]
            return project_line_market_row(flat), None

        if kind == "snapshot":
            market = row.get("market", "h2h")
            flat = _flatten_snapshot_row(row)
            if market == "h2h":
                return list(project_h2h_row(flat, market_key="h2h")), None
            return project_line_market_row(flat), None

        if kind == "h2h_flat":
            market = row.get("market", "h2h")
            return list(project_h2h_row(row, market_key=market)), None

        return [], f"unknown_source_kind:{kind}"
    except KeyError as exc:
        return [], f"missing_field:{exc.args[0]}"
    except (TypeError, ValueError) as exc:
        return [], f"malformed_row:{type(exc).__name__}"


def _row_date(row: Mapping[str, Any]) -> str | None:
    stamp = row.get("observed_utc")
    if not isinstance(stamp, str) or len(stamp) < 10:
        return None
    return stamp[:10]


def _parse_iso(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _grades_for_store(rows: Iterable[dict]) -> dict[str, str]:
    """Per guard 1 (F10): grade is computed from the MEASURED gap between an
    observation's own `observed_utc` and the previous distinct `observed_utc`
    seen in the same store -- never asserted from an assumed schedule. The
    very first instant in a store has no prior gap to measure and is graded D
    rather than guessed."""
    stamps = sorted({r["observed_utc"] for r in rows if r.get("observed_utc")})
    grade_by_stamp: dict[str, str] = {}
    previous = None
    for stamp in stamps:
        if previous is None:
            grade_by_stamp[stamp] = "D"
        else:
            gap = (_parse_iso(stamp) - _parse_iso(previous)).total_seconds()
            grade_by_stamp[stamp] = grade_from_gap(max(gap, 0.0))
        previous = stamp
    return grade_by_stamp


# ---------------------------------------------------------------------------
# Raw L0 matching
# ---------------------------------------------------------------------------

def _iter_raw_files(raw_root: Path, day: str) -> list[Path]:
    if not day:
        return []
    try:
        year, month, dom = day.split("-")
    except ValueError:
        return []
    day_dir = raw_root / year / month / dom
    if not day_dir.exists():
        return []
    return sorted(day_dir.glob("*.jsonl.gz"))


def _load_raw_capture(path: Path) -> dict | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            line = handle.readline()
        return json.loads(line) if line.strip() else None
    except (OSError, json.JSONDecodeError):
        return None


def _raw_outcomes(payload: Any, event_id: str, book: str, provider_market_key: str):
    """Yield outcome dicts from a raw (pre-normalization) provider payload
    matching one event/book/market. Provider shape: a list of event dicts,
    each `{"id", "bookmakers": [{"key", "last_update",
    "markets": [{"key", "outcomes": [{"name", "price", "point"}]}]}]}`."""
    events = payload if isinstance(payload, list) else [payload]
    for event in events:
        if not isinstance(event, dict) or event.get("id") != event_id:
            continue
        for bookmaker in event.get("bookmakers") or []:
            if bookmaker.get("key") != book:
                continue
            for market in bookmaker.get("markets") or []:
                if market.get("key") != provider_market_key:
                    continue
                for outcome in market.get("outcomes") or []:
                    yield outcome, bookmaker.get("last_update")


_OUTCOME_NAME_BY_SIDE = {"over": "Over", "under": "Under", "yes": "Yes", "no": "No"}


def _match_raw(obs: dict, raw_root: Path) -> tuple[bool, str | None]:
    """Best-effort raw-first match. Returns (l0_available, capture_id).

    Untested against a real captured payload in this worktree -- no raw file
    exists here to try it against (see the run report) -- so this path is
    exercised only by the synthetic fixture in tests/test_board_l1.py, built
    from the documented Odds-API bookmaker/market/outcome shape
    (docs/COLLECTION_POLICY.md's raw-layer section) rather than a captured
    sample. Flagged as not verified against a real payload in the report.
    """
    day = _row_date(obs)
    observed = _parse_iso(obs["observed_utc"]) if obs.get("observed_utc") else None
    if observed is None:
        return False, None
    for candidate_day in {day, (observed - timedelta(days=1)).date().isoformat()}:
        for path in _iter_raw_files(raw_root, candidate_day):
            capture_id = path.stem.split(".")[0]
            try:
                captured_stamp = capture_id.split("-")[0]
                captured_at = datetime.strptime(
                    captured_stamp, "%Y%m%dT%H%M%SZ"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if abs((captured_at - observed).total_seconds()) > RAW_MATCH_WINDOW_SECONDS:
                continue
            record = _load_raw_capture(path)
            if not record:
                continue
            side_name = obs["side"]
            want_name = _OUTCOME_NAME_BY_SIDE.get(side_name)
            for outcome, _last_update in _raw_outcomes(
                record.get("payload"), obs["event_id"], obs["book"],
                obs["provider_market_key"],
            ):
                name = outcome.get("name")
                if want_name is not None and name != want_name:
                    continue
                # home/away sides are named by team in the raw payload, not
                # by side keyword, and this projector does not carry team
                # names to compare against -- so for home/away the outcome
                # name is not checked, only the price (below).
                if outcome.get("price") == obs["price_american"]:
                    return True, capture_id
    return False, None


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def _existing_ids(output_path: Path) -> set[str]:
    ids = set()
    for row in _read_jsonl(output_path):
        oid = row.get("observation_id")
        if oid:
            ids.add(oid)
    return ids


def run(
    since: str | None = None,
    output_path: Path | str = OUTPUT_PATH,
    raw_root: Path | str = RAW_ROOT,
    sport: str = _DEFAULT_SPORT,
    region: str = _DEFAULT_REGION,
    sources: list[dict] | None = None,
    game_map_path: Path | str | None = EVENT_GAME_MAP_PATH,
) -> dict:
    """Project every source store into `output_path`, appending only rows
    whose `observation_id` is not already present. Returns a report: counts
    per source store, per market_key, rows written/skipped, and a refusal
    breakdown by reason -- never a silent drop.

    `sources` overrides SOURCE_STORES (plus the closing_* glob) -- used by
    tests to point at fixture files instead of the real data directory; the
    default (None) is production behavior.

    `game_map_path` points at the event_id -> game_pk store `gamekey.py`
    builds (S1); pass `None` to skip the lookup entirely (e.g. a caller that
    deliberately wants every row's game_pk left null). A row's own
    `observation_id` never depends on its resolved game_pk (see
    `_observation_id`'s field list) -- game_pk is a join fact about the
    event, not part of what makes one price observation the observation it
    is -- so a map built AFTER some rows are already on disk does not
    retroactively update them; a full backfill re-run (fresh `output_path`)
    is how an already-written store picks up a newer map.
    """
    output_path = Path(output_path)
    raw_root = Path(raw_root)
    existing_ids = _existing_ids(output_path)
    game_map = gamekey.load_map(game_map_path) if game_map_path else {}

    stores = (list(sources) if sources is not None
              else list(SOURCE_STORES) + _discover_closing_stores(output_path.parent))

    report: dict[str, Any] = {
        "since": since,
        "output_path": str(output_path),
        "by_source": {},
        "by_market_key": {},
        "written": 0,
        "skipped_existing": 0,
        "refused": 0,
        "refusals": {},
        "raw_matched": 0,
        # S1: how many written observations got a real game_pk. "ambiguous"
        # rows DO carry a game_pk (the nearest-commence_time best guess --
        # see gamekey.resolve_event) but are counted separately so this
        # report never hides the uncertainty. "not_in_map" means
        # `gamekey --date` was never run for this event's date; "map_null"
        # means it was run and genuinely could not resolve the event
        # (gamekey.py's own `reason` field on that row says why).
        "game_pk": {"resolved": 0, "ambiguous": 0, "not_in_map": 0,
                    "map_null": 0},
    }
    refusals = RefusalReport()

    new_lines: list[str] = []
    for source in stores:
        path = Path(source["path"])
        source_name = source["name"]
        source_stats = {
            "rows_seen": 0, "observations_seen": 0, "written": 0,
            "skipped_existing": 0, "refused": 0, "raw_matched": 0,
            "path": str(path), "present": path.exists(),
        }
        report["by_source"][source_name] = source_stats
        if not path.exists():
            continue

        all_rows = _read_jsonl(path)
        grade_by_stamp = _grades_for_store(all_rows)

        for row in all_rows:
            source_stats["rows_seen"] += 1
            day = _row_date(row)
            if since is not None and (day is None or day < since):
                continue

            observations, reason = _project_source_row(source, row)
            if reason is not None:
                refusals.add(reason, row)
                source_stats["refused"] += 1
                report["refused"] += 1
                continue

            for obs in observations:
                source_stats["observations_seen"] += 1
                obs = dict(obs)
                obs.setdefault("sport", sport)
                observed_utc = obs.get("observed_utc")
                obs["known_at"] = observed_utc
                obs["known_at_grade"] = grade_by_stamp.get(observed_utc, "D")
                obs["region"] = region
                obs["source"] = _DEFAULT_SOURCE
                obs["venue_kind"] = "sportsbook"
                obs["is_close"] = bool(source["is_close"])
                obs["limit_observed"] = None

                map_entry = game_map.get(str(obs.get("event_id")))
                if map_entry is None:
                    obs["game_pk"] = None
                    report["game_pk"]["not_in_map"] += 1
                elif map_entry.get("game_pk") is None:
                    obs["game_pk"] = None
                    report["game_pk"]["map_null"] += 1
                else:
                    # `PriceObservation.game_pk` is `int | None` by its own
                    # contract (matching `boxscores_*.jsonl`/
                    # `mlb_results.csv`'s on-disk convention) -- a LEAF
                    # field, not a join key, so it stores a native int here
                    # rather than the canonical join-key string
                    # (`src.core.asof.game_pk_key`) every comparison against
                    # `event_game_map.jsonl`'s `game_pk` column goes through.
                    # Routing the raw map value through that same helper
                    # first (then back to int) means an old row on disk
                    # written before S1's string normalization and a new one
                    # written after it both land here identically, instead
                    # of this being the one write site that has to remember
                    # its own ad hoc coercion.
                    obs["game_pk"] = int(game_pk_key(map_entry["game_pk"]))
                    if map_entry.get("ambiguous"):
                        report["game_pk"]["ambiguous"] += 1
                    else:
                        report["game_pk"]["resolved"] += 1

                l0_available, raw_capture_id = _match_raw(obs, raw_root)
                obs["l0_available"] = l0_available
                if l0_available:
                    obs["capture_id"] = raw_capture_id
                    source_stats["raw_matched"] += 1
                    report["raw_matched"] += 1
                else:
                    obs["capture_id"] = f"backfill:{source_name}:{observed_utc}"

                obs_id = _observation_id(source_name, obs)
                if obs_id in existing_ids:
                    source_stats["skipped_existing"] += 1
                    report["skipped_existing"] += 1
                    continue

                obs["observation_id"] = obs_id
                try:
                    price_observation_from_dict(
                        {k: v for k, v in obs.items() if k != "observation_id"}
                    )
                except RecordValidationError as exc:
                    refusals.add(f"invalid_record:{exc}", obs)
                    source_stats["refused"] += 1
                    report["refused"] += 1
                    continue

                market_key = obs["market_key"]
                report["by_market_key"].setdefault(
                    market_key, {"written": 0, "skipped_existing": 0, "refused": 0}
                )
                report["by_market_key"][market_key]["written"] += 1

                existing_ids.add(obs_id)
                new_lines.append(json.dumps(obs, separators=(",", ":"), sort_keys=True))
                source_stats["written"] += 1
                report["written"] += 1

    if new_lines:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as handle:
            for line in new_lines:
                handle.write(line + "\n")

    report["refusals"] = dict(refusals.by_reason)
    report["refusal_examples"] = refusals.examples
    return report
