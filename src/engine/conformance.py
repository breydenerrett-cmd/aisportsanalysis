"""The conformance suite a `system` must pass before registration.

docs/ARCHITECTURE_BETTING_ENGINE.md section 3 and docs/ENGINE_CONTRACT.md
section 5 define an `AnalysisSystem` by shape (id, version, spec_hash,
declared_markets, declared_inputs, min_grade, expected_selection_rate,
`propose(view) -> tuple`) but never by trust: nothing about the shape stops
a `propose()` implementation from reading a wall clock, from returning a
different answer on the second call, or from reaching for `getattr(view,
"board", None)` in a way that happens not to raise. This module is the gate
between "satisfies the Protocol" and "may be registered": five checks, run
against a system and a sample of `PriceBlindSnapshot`s, none of which the
system is told about in advance.

Checks
------
1. purity          -- same inputs -> identical output, twice, in this process.
2. price_blindness -- an instrumented snapshot proves no forbidden or
                       undeclared price-shaped name was ever reached for.
3. determinism     -- the same call, in a **separate process**, produces a
                       byte-identical hash of the proposals. Catches
                       anything purity-in-one-process cannot: import-order
                       dependent global state, non-reproducible hashing,
                       an accidental `random` seed drawn from the OS.
4. schema          -- every returned `Proposal` is well-typed and matches
                       `docs/ENGINE_CONTRACT.md` section 4.1's shape.
5. declared_inputs -- the feature names actually read (via `.features` and
                       `.differential()`) are a subset of
                       `system.declared_inputs`. A system that reads a
                       feature it never declared is exactly the failure
                       mode `docs/ARCHITECTURE_BETTING_ENGINE.md` section 4
                       guard 3 (registered clustering/feature provenance)
                       exists to catch before registration, not after.

Nothing here performs I/O itself except the one subprocess spawned for the
determinism check, and that subprocess is handed nothing but the sample
already in memory (serialised to JSON) plus an import path -- no network,
no disk beyond Python's own module import.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass, fields
from typing import Any, Iterable, Mapping

from src.engine.analyze import Proposal
from src.engine.snapshot import FORBIDDEN_PRICE_NAMES, PriceBlindSnapshot

_PROPOSAL_FIELD_NAMES = tuple(f.name for f in fields(Proposal))

# Calls an honest `propose()` must never make. Mirrors
# tests/test_engine_analyze.py::TestPurity's AST walk over `analyze()`
# itself, extended to arbitrary system code.
_FORBIDDEN_CALL_NAMES = frozenset({
    "open", "input", "eval", "exec", "urlopen", "request", "connect",
})
_FORBIDDEN_ATTR_CHAINS = frozenset({
    ("random", "random"), ("random", "randint"), ("random", "choice"),
    ("time", "time"), ("datetime", "now"), ("datetime", "utcnow"),
    ("os", "urandom"),
})


class ConformanceError(ValueError):
    """A conformance check was invoked with malformed inputs (a bug, not a
    failed check)."""


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    reasons: tuple


@dataclass(frozen=True, slots=True)
class ConformanceResult:
    system_id: str
    passed: bool
    checks: tuple  # tuple[CheckResult, ...]

    def to_dict(self) -> dict:
        return {
            "system_id": self.system_id,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "reasons": list(c.reasons)}
                for c in self.checks
            ],
        }


class _AccessLog:
    """Records every feature name a `propose()` call reached for, on the
    instrumented view handed to it. Shared by the features mapping and
    `.differential()` so both access paths are captured in one place."""

    def __init__(self) -> None:
        self.feature_names: set[str] = set()
        self.forbidden_touched: set[str] = set()

    def note_feature(self, name: str) -> None:
        self.feature_names.add(name)

    def note_differential(self, feature: str) -> None:
        self.feature_names.add("away_" + feature)
        self.feature_names.add("home_" + feature)

    def note_forbidden(self, name: str) -> None:
        self.forbidden_touched.add(name)


class _RecordingFeatures(dict):
    """A `dict` subclass so `PriceBlindSnapshot.differential()` (which calls
    plain `dict.get`) keeps working unmodified, while `__getitem__`/`get`
    still log every key a caller asks for."""

    def __init__(self, data: Mapping[str, float], log: _AccessLog):
        super().__init__(data)
        self._log = log

    def __getitem__(self, key):
        self._log.note_feature(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._log.note_feature(key)
        return super().get(key, default)


class InstrumentedSnapshot:
    """Wraps a real `PriceBlindSnapshot`, logging every attribute a caller
    reaches for. Delegates everything else unchanged -- including the real
    `__getattr__` refusal for `FORBIDDEN_PRICE_NAMES`, so price-blindness is
    enforced by the SAME mechanism a live system would hit, not a mock of it.
    """

    __slots__ = ("_inner", "_log")

    def __init__(self, inner: PriceBlindSnapshot, log: _AccessLog):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_log", log)

    def __getattr__(self, name):
        if name.lower() in FORBIDDEN_PRICE_NAMES:
            self._log.note_forbidden(name)
        # Delegate to the real object -- this raises the real, named
        # AttributeError for forbidden names; nothing here softens that.
        return getattr(self._inner, name)

    @property
    def features(self):
        return _RecordingFeatures(self._inner.features, self._log)

    def differential(self, feature: str):
        self._log.note_differential(feature)
        return self._inner.differential(feature)

    def books_for(self, market: str) -> int:
        return self._inner.books_for(market)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, default=str)


def _proposal_to_dict(p) -> dict:
    if isinstance(p, Proposal):
        return {f: getattr(p, f) for f in _PROPOSAL_FIELD_NAMES}
    # Not a Proposal instance at all -- schema check reports this; still
    # need a hashable representation for the determinism/purity checks.
    return {"__non_proposal__": repr(p)}


def _run_propose_multi(system, snapshots: Iterable[PriceBlindSnapshot],
                        *, instrumented: bool = False, log: "_AccessLog | None" = None):
    out = []
    for snap in snapshots:
        view = InstrumentedSnapshot(snap, log) if instrumented else snap
        for proposal in system.propose(view):
            out.append(_proposal_to_dict(proposal))
    return out


def _hash_proposals(rows: list) -> str:
    return hashlib.sha256(_canonical_json(rows).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Check 1: purity
# ---------------------------------------------------------------------------

def check_purity(system, snapshots: Iterable[PriceBlindSnapshot]) -> CheckResult:
    snapshots = tuple(snapshots)
    reasons: list = []
    ok = True

    try:
        first = _run_propose_multi(system, snapshots)
        second = _run_propose_multi(system, snapshots)
    except Exception as exc:  # noqa: BLE001 -- report, never crash the suite
        return CheckResult("purity", False,
                            (f"propose() raised on a plain call: {exc!r}",))

    h1, h2 = _hash_proposals(first), _hash_proposals(second)
    if h1 != h2:
        ok = False
        reasons.append(f"propose() produced different output on repeated "
                        f"calls with identical inputs: {h1} != {h2}")

    # No-I/O / no-wall-clock: an AST walk over propose()'s own source, same
    # discipline as tests/test_engine_analyze.py::TestPurity applies to
    # analyze() itself.
    src_reasons = _ast_purity_reasons(type(system))
    if src_reasons:
        ok = False
        reasons.extend(src_reasons)

    if ok:
        reasons.append("identical output on repeated calls; no forbidden "
                        "I/O or clock call found in propose() source")
    return CheckResult("purity", ok, tuple(reasons))


def _ast_purity_reasons(system_cls: type) -> list:
    import ast as _ast
    try:
        source = inspect.getsource(system_cls.propose)
    except (OSError, TypeError):
        return [f"{system_cls.__name__}.propose source unavailable for "
                "AST inspection -- cannot certify purity by static check"]
    source = textwrap.dedent(source)
    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return []
    reasons: list = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            fn = node.func
            if isinstance(fn, _ast.Name) and fn.id in _FORBIDDEN_CALL_NAMES:
                reasons.append(f"propose() calls forbidden {fn.id}()")
            if isinstance(fn, _ast.Attribute):
                base = fn.value
                if isinstance(base, _ast.Name):
                    if (base.id, fn.attr) in _FORBIDDEN_ATTR_CHAINS:
                        reasons.append(
                            f"propose() calls forbidden {base.id}.{fn.attr}()")
    return reasons


# ---------------------------------------------------------------------------
# Check 2: price-blindness
# ---------------------------------------------------------------------------

def check_price_blindness(system, snapshots: Iterable[PriceBlindSnapshot]) -> CheckResult:
    log = _AccessLog()
    try:
        _run_propose_multi(system, snapshots, instrumented=True, log=log)
    except AttributeError as exc:
        # A raised AttributeError naming a forbidden field is the mechanism
        # WORKING, not a system failure of this check by itself -- but it
        # means propose() tried to read a price, which IS the failure this
        # check exists to catch.
        return CheckResult(
            "price_blindness", False,
            (f"propose() attempted to read a price-shaped attribute and "
             f"raised: {exc!r}",))
    except Exception as exc:  # noqa: BLE001
        return CheckResult("price_blindness", False,
                            (f"propose() raised under instrumentation: {exc!r}",))

    if log.forbidden_touched:
        return CheckResult(
            "price_blindness", False,
            tuple(f"propose() reached for forbidden name {n!r}"
                  for n in sorted(log.forbidden_touched)))
    return CheckResult("price_blindness", True,
                        ("no forbidden price-shaped attribute was ever "
                         "reached for",))


# ---------------------------------------------------------------------------
# Check 3: determinism across process restarts
# ---------------------------------------------------------------------------

_RESTART_WORKER = """
import importlib
import json
import sys

payload = json.loads(sys.stdin.read())
module_name, attr_name = payload["factory"].split(":")
module = importlib.import_module(module_name)
factory = getattr(module, attr_name)
system = factory()

from src.engine.snapshot import PriceBlindSnapshot
from src.engine.conformance import _run_propose_multi, _hash_proposals

snapshots = [PriceBlindSnapshot(**kw) for kw in payload["snapshots"]]
rows = _run_propose_multi(system, snapshots)
print(_hash_proposals(rows))
"""


def check_determinism(system, snapshots: Iterable[PriceBlindSnapshot], *,
                       system_factory: str = None) -> CheckResult:
    """`system_factory` is `"module.path:callable_name"` -- a zero-argument
    callable that reconstructs an equivalent system. Without it, this check
    can only certify same-process determinism (still reported, but the
    reason names the limitation instead of silently upgrading the claim)."""
    snapshots = tuple(snapshots)
    in_process_hash = _hash_proposals(_run_propose_multi(system, snapshots))

    if system_factory is None:
        return CheckResult(
            "determinism", True,
            (f"in-process hash {in_process_hash} computed; no "
             "system_factory given, so cross-process restart was not "
             "exercised (pass system_factory='module:callable' to certify "
             "it)",))

    snap_payload = []
    for s in snapshots:
        snap_payload.append({
            "game_pk": s.game_pk, "t": s.t, "point_class": s.point_class,
            "features": dict(s.features),
            "available_markets": list(s.available_markets),
            "books_by_market": dict(s.books_by_market),
            "point_meta": None,
            "lineup_posted": s.lineup_posted,
            "assumption_exposure": dict(s.assumption_exposure),
            "fingerprint": s.fingerprint,
        })
    payload = {"factory": system_factory, "snapshots": snap_payload}
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RESTART_WORKER],
            input=_canonical_json(payload), capture_output=True, text=True,
            timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("determinism", False,
                            (f"subprocess restart failed to run: {exc!r}",))

    if proc.returncode != 0:
        return CheckResult(
            "determinism", False,
            (f"subprocess restart exited {proc.returncode}: "
             f"{proc.stderr.strip()[-2000:]}",))
    restart_hash = proc.stdout.strip()
    if restart_hash != in_process_hash:
        return CheckResult(
            "determinism", False,
            (f"restart hash {restart_hash!r} != in-process hash "
             f"{in_process_hash!r}",))
    return CheckResult("determinism", True,
                        (f"hash {in_process_hash} reproduced in a fresh "
                         "process",))


# ---------------------------------------------------------------------------
# Check 4: schema conformance
# ---------------------------------------------------------------------------

def check_schema(system, snapshots: Iterable[PriceBlindSnapshot]) -> CheckResult:
    reasons: list = []
    ok = True
    count = 0
    for snap in snapshots:
        try:
            proposals = tuple(system.propose(snap))
        except Exception as exc:  # noqa: BLE001
            return CheckResult("schema", False,
                                (f"propose() raised: {exc!r}",))
        for p in proposals:
            count += 1
            if not isinstance(p, Proposal):
                ok = False
                reasons.append(f"proposal {p!r} is not a Proposal instance")
                continue
            if not p.system_id or not isinstance(p.system_id, str):
                ok = False
                reasons.append(f"proposal has empty/non-str system_id: {p!r}")
            if not p.market_key or not isinstance(p.market_key, str):
                ok = False
                reasons.append(f"proposal has empty/non-str market_key: {p!r}")
            if p.side not in ("home", "away", "over", "under", "yes", "no"):
                ok = False
                reasons.append(f"proposal has unrecognised side {p.side!r}")
            if p.p_model is not None and not (0.0 <= p.p_model <= 1.0):
                ok = False
                reasons.append(
                    f"proposal p_model={p.p_model!r} out of [0, 1]")
    if ok:
        reasons.append(f"{count} proposal(s) all matched the Proposal schema")
    return CheckResult("schema", ok, tuple(reasons))


# ---------------------------------------------------------------------------
# Check 5: declared_inputs conformance
# ---------------------------------------------------------------------------

def check_declared_inputs(system, snapshots: Iterable[PriceBlindSnapshot]) -> CheckResult:
    declared = set(getattr(system, "declared_inputs", ()) or ())
    log = _AccessLog()
    try:
        _run_propose_multi(system, snapshots, instrumented=True, log=log)
    except Exception as exc:  # noqa: BLE001
        return CheckResult("declared_inputs", False,
                            (f"propose() raised under instrumentation: {exc!r}",))

    undeclared = sorted(n for n in log.feature_names if n not in declared)
    if undeclared:
        return CheckResult(
            "declared_inputs", False,
            tuple(f"propose() read feature {n!r}, which is not in "
                  f"declared_inputs={sorted(declared)}" for n in undeclared))
    return CheckResult(
        "declared_inputs", True,
        (f"every feature read ({sorted(log.feature_names)}) is in "
         f"declared_inputs",))


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------

CHECKS: tuple = (
    check_purity, check_price_blindness, check_schema, check_declared_inputs,
)


def run_conformance(system, snapshots: Iterable[PriceBlindSnapshot], *,
                     system_factory: str = None) -> ConformanceResult:
    """Run every registered conformance check against `system` over
    `snapshots`. Returns a result that is `passed` only if every check
    passed -- never a partial credit average."""
    snapshots = tuple(snapshots)
    if not snapshots:
        raise ConformanceError("run_conformance requires at least one "
                                "sample PriceBlindSnapshot")
    results = [check(system, snapshots) for check in CHECKS]
    results.append(check_determinism(system, snapshots,
                                      system_factory=system_factory))
    system_id = getattr(system, "id", type(system).__name__)
    return ConformanceResult(
        system_id=system_id,
        passed=all(r.passed for r in results),
        checks=tuple(results),
    )
