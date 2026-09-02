"""The alpha registry -- the cross-family, cross-time search-spend ledger.

NOT `src/evolab/registry.py`. That module is a per-feature SIGN
pre-registration store (freezes a mechanism's direction before any search
touches it, so a genome can never screen-then-flip). This module is a
different object entirely: it is the append-only ledger of every
REGISTERED HYPOTHESIS, SWEEP and AUDIT this project has ever spent, across
every family, so that "how much have we already searched, on what data,
against what outcome" has one honest answer instead of living scattered
across `docs/RESEARCH_*.md` prose. See `docs/ALPHA_REGISTRY_DESIGN.md` for
the design decisions this module implements (cited as D1-D4 below), and
`docs/ALPHA_REGISTRY_MIGRATION_REPORT.md` for the reconciliation of what the
source documents actually contained against what this module could load
honestly (nulls, disagreements, and all).

WHY THIS EXISTS (D1 rationale)
-------------------------------
Per-family BH-FDR and per-sweep SPA/CSCV/placebo ceilings each control error
WITHIN their own scope. Nothing accumulated search effort ACROSS families and
sweeps over calendar time before this module. At scale that gap is a
belief-manufacturing risk: a nightly cycle could re-spend evidence a prior
family already paid for. This registry is the one ledger that answers that
question, honestly, including when the honest answer is "we don't know" (a
null field) rather than a guess.

ROW SCHEMA (D2, verbatim from the design note)
-----------------------------------------------
Two row shapes, one JSONL file, one row per event, never rewritten:

    {kind: "hypothesis" | "sweep" | "audit",
     id, family, spec_id (secondary grouping key), market, sport: "mlb",
     registered_utc, data_window: {discovery, replication, sealed_untouched},
     direction, feature_expr_hash (semantic hash v0, see below),
     alpha_declared (family q, or the sweep's placebo-ceiling threshold_pct),
     status: "registered", source_doc, code_hash}

    {kind: "verdict", id, read_utc, result: "null" | "false_positive" |
     "candidate" | "survivor" | "audit", p, effect, ci, battery_version,
     within_sweep: {spa_p, pbo, placebo_pct} (sweep verdicts only),
     forward_window: {start, n, pending: true|false}}

Two additions this migration made, both flagged rather than hidden:

- `migrated_utc` is stamped on every row written by the migration script
  (never by `register()`/`record_verdict()` when called freshly) so a reader
  can tell "when the family said this happened" (`registered_utc`, `read_utc`
  -- copied from the source doc, NEVER today's date) apart from "when this
  ledger learned about it" (`migrated_utc` -- always the migration run time).
- `sweep` rows carry one extra field the generic schema above does not list:
  `candidates_evaluated` (D1: "Evolab Phase 2B is ONE registry entry of kind
  `sweep` with `candidates_evaluated = 8811`"). It is the sweep's internal
  multiplicity, charged once, never expanded into per-genome hypothesis rows.

APPEND-ONLY (enforced, not just documented)
--------------------------------------------
`register()` refuses a second row for an `id` already carrying a
hypothesis/sweep/audit row. `record_verdict()` refuses a second verdict for
an `id` that already has one, and refuses a verdict for an `id` with no
registered row at all. Neither function can rewrite or delete a line. A
correction to an already-verdicted unit (see V2's M4 CI correction,
`docs/RESULTS_V2.md`) is a NEW id (e.g. `<id>-correction-<date>`), never an
edit of the old row -- exactly the discipline `docs/RESULTS_V2.md` itself
follows by leaving the superseded number in place rather than overwriting it.

SEMANTIC HASH v0 (D3)
----------------------
`semantic_hash_v0(atoms, grid=None)` takes an iterable of atoms, each either
a 4-tuple `(feature, operator, market, direction)` or a 5-tuple with a
trailing numeric `threshold`, and returns a sha256 hex digest over the
SORTED, DEDUPED set of atoms with any threshold snapped to the nearest value
in `grid` (or left as-is if `grid` is falsy). Order of the input atoms never
affects the hash (they are collected into a `set` first); a threshold that
buckets to a different grid point than another run's threshold produces a
different hash even if every other field matches. This is an explicit floor
on honesty, not a ceiling (D3): it catches exact-mechanism duplicates across
families, nothing more. Correlation between genuinely different hashes is
out of scope here (Appendix B of the design note) and is deferred by design.

Per-family grid source, recorded here because D3 requires it to live in this
docstring rather than only in a migration script that will eventually stop
being read:

- **V1** (`evidence/hypothesis_family.json`): each hypothesis is a bare
  (detector, market) pair with no pre-registered numeric threshold anywhere
  in the frozen registration artifact. Atoms hash on
  `(detector, "flag_present", market, None)` -- 4-tuples, no threshold, no
  grid. (`min_effect: 0.01` in that file is an EVALUATION-time FDR effect
  floor, not a feature-defining threshold, and is not part of the hash.)
- **V2** (`docs/RESEARCH_V2.md`, prose only -- no structured registration
  file exists for this family): each M-test's operative cutoffs (M1's
  1pp/2pp fade thresholds, M3's deviation bands) are swept as POST-
  registration robustness checks in `docs/RESULTS_V2.md`, not values fixed
  at pre-registration. Atoms hash on `(feature, operator, market, direction)`
  4-tuples with no threshold and no grid, same shape as V1.
- **V4** (`data/research/family_v4_exploratory.json`) and **V5**
  (`data/research/family_v5_stuff.json`): each spec's `threshold` field is
  already a single frozen scalar -- "the pooled p70 of |signal| from feature
  distributions only" (`docs/RESEARCH_CATALOGUE.md`), fixed once at
  registration and never swept. The grid for these two families is the
  IDENTITY grid: one point per feature, equal to that feature's own declared
  threshold, so bucketing is a no-op for values from the registration file
  and only starts doing work if some other value is compared against it.
- **V3** (`docs/RESEARCH_V3_TIMING.md`, `docs/RESEARCH_V3_UMPIRE_CLASS.md`):
  every class shares one primary hypothesis template with no per-class
  numeric threshold (the floor and quality gates are family-wide constants,
  not part of the hypothesis atom). Atoms hash on
  `(class_name, "median_reaction_exceeds_floor", market, direction)`, no
  threshold, no grid. `market` is left `None` for every V3 row -- see the
  migration report for why a value was not guessed.
- **Phase 2B sweep** and the **Elo audit**: neither is a hypothesis in the
  BH-FDR sense, so neither carries a `feature_expr_hash` atom set in the
  same way; both hash a single descriptive atom
  (`family_name, "sweep"|"audit", market, None`) purely so the field is never
  null, with no numeric threshold and no grid.

CONSUMPTION (D4)
-----------------
`total_searched(market=None, data_window=None)` is what a new family's
pre-registration doc and the falsification battery are expected to cite
("searched before this family: N units, K sweeps, on these windows") per the
design note's Decision 4. `market` filters on exact string match against a
row's `market` field. `data_window` filters on exact string match against
EITHER `data_window.discovery` OR `data_window.replication` -- substring or
range matching is deliberately not implemented, so a caller cannot silently
over- or under-count by passing a window string that partially overlaps one
recorded on disk.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "data" / "research" / "alpha_registry.jsonl"

# kinds that occupy the "registered unit" namespace (share one id-space with
# their own verdict rows); "verdict" is the second row shape (D2).
REGISTRATION_KINDS = ("hypothesis", "sweep", "audit")
_REGISTRATION_KIND_SET = set(REGISTRATION_KINDS)
VALID_RESULTS = ("null", "false_positive", "candidate", "survivor", "audit")

REQUIRED_REGISTRATION_FIELDS = (
    "kind", "id", "family", "market", "sport", "registered_utc",
    "data_window", "alpha_declared", "source_doc",
)
REQUIRED_VERDICT_FIELDS = ("kind", "id", "read_utc", "result")


class AppendOnlyError(ValueError):
    """Raised when a caller tries to rewrite an existing id in the ledger."""


def utcnow_iso() -> str:
    """The one place `migrated_utc`/provenance timestamps come from."""
    return datetime.now(timezone.utc).isoformat()


def git_blob_hash(path) -> Optional[str]:
    """sha1 content hash identical to `git hash-object <path>`, no subprocess.

    Used to populate `code_hash` for a family whose source doc did not
    already record one, by hashing the implementing module's current
    on-disk content. Returns None if `path` does not exist as a file --
    None-over-guess applies to code provenance too.
    """
    p = Path(path)
    if not p.is_file():
        return None
    data = p.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def _normalize_atom(atom: Sequence[Any]) -> Tuple[Any, Any, Any, Any, Optional[float]]:
    if len(atom) == 4:
        feature, operator, market, direction = atom
        threshold = None
    elif len(atom) == 5:
        feature, operator, market, direction, threshold = atom
    else:
        raise ValueError(
            f"atom must be a 4-tuple (feature, operator, market, direction) or a "
            f"5-tuple with a trailing numeric threshold; got {len(atom)} "
            f"elements: {atom!r}"
        )
    if threshold is not None:
        threshold = float(threshold)
    return (feature, operator, market, direction, threshold)


def _bucket_threshold(threshold: Optional[float], grid: Optional[Sequence[float]]) -> Optional[float]:
    """Snap `threshold` to the nearest point in `grid`; identity if no grid."""
    if threshold is None:
        return None
    if not grid:
        return threshold
    return min(grid, key=lambda g: abs(g - threshold))


def semantic_hash_v0(atoms: Iterable[Sequence[Any]], grid: Optional[Sequence[float]] = None) -> str:
    """D3's v0 semantic hash: sha256 over the sorted, deduped, bucketed atom set.

    `atoms` is any iterable of 4- or 5-element sequences (see
    `_normalize_atom`). The result is independent of input order and of
    duplicate atoms; a numeric threshold is bucketed to the nearest value in
    `grid` before hashing (identity if `grid` is falsy), so two runs whose
    raw thresholds differ but land in the same bucket hash identically, and
    a threshold that lands outside every declared bucket hashes differently
    from one that lands inside it.
    """
    bucketed: Set[Tuple[Any, Any, Any, Any, Optional[float]]] = set()
    for atom in atoms:
        feature, operator, market, direction, threshold = _normalize_atom(atom)
        bucketed.add((feature, operator, market, direction, _bucket_threshold(threshold, grid)))
    canonical = sorted(bucketed, key=lambda t: json.dumps(t, sort_keys=True, default=str))
    payload = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _matches_window(data_window: Optional[dict], requested: str) -> bool:
    if not data_window:
        return False
    return requested in (data_window.get("discovery"), data_window.get("replication"))


class AlphaRegistry:
    """One append-only JSONL ledger. See the module docstring for the schema."""

    def __init__(self, path: Optional[Any] = None):
        self.path = Path(path) if path is not None else DEFAULT_PATH

    # -- reading -----------------------------------------------------------

    def _iter_raw(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)

    def read_all(self) -> List[dict]:
        """Every row, in file order, exactly as stored. No filtering, no mutation."""
        return list(self._iter_raw())

    def _registered_ids(self) -> Set[str]:
        return {row["id"] for row in self._iter_raw() if row.get("kind") in _REGISTRATION_KIND_SET}

    def _verdict_ids(self) -> Set[str]:
        return {row["id"] for row in self._iter_raw() if row.get("kind") == "verdict"}

    # -- writing (append-only) ----------------------------------------------

    def register(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Append one hypothesis/sweep/audit row. Refuses a duplicate id."""
        row = dict(row)
        kind = row.get("kind")
        if kind not in _REGISTRATION_KIND_SET:
            raise ValueError(
                f"register() row['kind'] must be one of {REGISTRATION_KINDS}, got {kind!r}"
            )
        row_id = row.get("id")
        if not row_id:
            raise ValueError("register() row requires a non-empty 'id'")
        missing = [f for f in REQUIRED_REGISTRATION_FIELDS if f not in row]
        if missing:
            raise ValueError(f"register() row is missing required fields: {missing}")
        if row_id in self._registered_ids():
            raise AppendOnlyError(
                f"id {row_id!r} is already registered -- the ledger is append-only; "
                "nothing may rewrite or delete a row"
            )
        row.setdefault("status", "registered")
        row.setdefault("migrated_utc", None)
        self._append(row)
        return row

    def record_verdict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Append one verdict row for an id already registered. Refuses a
        duplicate verdict and a verdict with no matching registered row."""
        row = dict(row)
        if row.get("kind") != "verdict":
            raise ValueError("record_verdict() row['kind'] must be 'verdict'")
        row_id = row.get("id")
        if not row_id:
            raise ValueError("record_verdict() row requires a non-empty 'id'")
        missing = [f for f in REQUIRED_VERDICT_FIELDS if f not in row]
        if missing:
            raise ValueError(f"record_verdict() row is missing required fields: {missing}")
        if row.get("result") not in VALID_RESULTS:
            raise ValueError(f"record_verdict() row['result'] must be one of {VALID_RESULTS}")
        if row_id not in self._registered_ids():
            raise ValueError(
                f"id {row_id!r} has no registered hypothesis/sweep/audit row -- "
                "a verdict requires prior registration"
            )
        if row_id in self._verdict_ids():
            raise AppendOnlyError(
                f"id {row_id!r} already has a verdict -- the ledger is append-only; "
                f"a correction is a NEW id (e.g. {row_id!r} + '-correction-<date>'), "
                "never a rewrite of the existing verdict"
            )
        row.setdefault("migrated_utc", None)
        self._append(row)
        return row

    def _append(self, row: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str))
            fh.write("\n")

    # -- reading, aggregated --------------------------------------------------

    def total_searched(self, market: Optional[str] = None,
                        data_window: Optional[str] = None) -> Dict[str, Any]:
        """D4's accounting read: how much has already been searched.

        Returns
        {"hypotheses": int, "sweeps": int, "sweep_candidates": int,
         "audits": int, "by_family": {family: {"hypotheses", "sweeps", "audits"}}}
        counting only registration rows (hypothesis/sweep/audit), never
        verdict rows, and never double-counting a sweep's internal
        `candidates_evaluated` into the `hypotheses` bucket (D1).
        """
        counts: Dict[str, Any] = {
            "hypotheses": 0, "sweeps": 0, "sweep_candidates": 0, "audits": 0,
            "by_family": {},
        }
        for row in self._iter_raw():
            kind = row.get("kind")
            if kind not in _REGISTRATION_KIND_SET:
                continue
            if market is not None and row.get("market") != market:
                continue
            if data_window is not None and not _matches_window(row.get("data_window"), data_window):
                continue
            family = row.get("family") or "UNKNOWN"
            bucket = counts["by_family"].setdefault(
                family, {"hypotheses": 0, "sweeps": 0, "audits": 0}
            )
            if kind == "hypothesis":
                counts["hypotheses"] += 1
                bucket["hypotheses"] += 1
            elif kind == "sweep":
                counts["sweeps"] += 1
                bucket["sweeps"] += 1
                candidates = row.get("candidates_evaluated")
                if isinstance(candidates, (int, float)):
                    counts["sweep_candidates"] += candidates
            elif kind == "audit":
                counts["audits"] += 1
                bucket["audits"] += 1
        return counts


# ---------------------------------------------------------------------------
# Module-level convenience API (operates on DEFAULT_PATH unless `path` is
# given -- tests pass a temp-dir path; production callers pass nothing).
# ---------------------------------------------------------------------------

def register(row: Dict[str, Any], path: Optional[Any] = None) -> Dict[str, Any]:
    return AlphaRegistry(path).register(row)


def record_verdict(row: Dict[str, Any], path: Optional[Any] = None) -> Dict[str, Any]:
    return AlphaRegistry(path).record_verdict(row)


def total_searched(market: Optional[str] = None, data_window: Optional[str] = None,
                    path: Optional[Any] = None) -> Dict[str, Any]:
    return AlphaRegistry(path).total_searched(market=market, data_window=data_window)


def read_all(path: Optional[Any] = None) -> List[dict]:
    return AlphaRegistry(path).read_all()
