"""The knobs a pack hound declares, and how a challenger changes them without a line of new code.

A pack hound is a Python class whose thresholds are module-level constants (``GAP = 0.020``). The
loop does not rewrite code. ``config/house_pack.json`` lists, per tunable hound, the constants a
challenger may change (``tunable``), each with a default, bounds and a step (docs/PREREG_LEARNING_LOOP.md
section 2b). A challenger is a dict of knob values; this module

  * validates it (names, type, bounds, the step grid, at most 2 knobs changed, at least 1);
  * GENERATES the published rule text by substituting each knob's ``renders`` (the exact strings of
    the champion's rule text that state it), so the words always say what the code does;
  * runs a hound's ``pick`` with those constants patched in for the length of one call only, under a
    lock, and restores them (``VersionedHound``). A hound that other hounds consult (an ensemble's
    voters) is never patched while they run: the patch exists only inside that hound's own wrapper;
  * says whether two knob sets are the same idea (``near_duplicate``).

A test (tests/test_hounds_learning_tunables.py) holds every declaration to the code: the module
attribute exists, its live value equals ``default``, the default lies on the grid inside the bounds,
each ``render`` of the default reproduces its ``literal``, and each literal is in the rule text.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from src.hounds.learning import rules

_PATCH_LOCK = threading.RLock()
_EPS = 1e-9


class TunableError(ValueError):
    """A knob set the declaration refuses. ``errors`` maps knob (or ``_``) to the reason."""

    def __init__(self, errors: Mapping[str, str]):
        self.errors = dict(errors)
        super().__init__("; ".join(f"{k}: {v}" for k, v in self.errors.items()))


@dataclass(frozen=True)
class Knob:
    name: str
    label: str
    kind: str                 # "int" | "float"
    default: float
    lo: float
    hi: float
    step: float
    renders: tuple            # ({"literal", "format", "scale"}, ...)

    def on_grid(self, value: float) -> bool:
        k = (value - self.lo) / self.step
        return abs(k - round(k)) < 1e-6

    def to_json(self) -> dict:
        return {"name": self.name, "label": self.label, "kind": self.kind, "default": self.default,
                "min": self.lo, "max": self.hi, "step": self.step}


@dataclass(frozen=True)
class TunableHound:
    hound_id: str
    name: str
    category: str
    module: str
    rule_text: str
    sports: tuple
    markets: tuple
    knobs: dict               # name -> Knob

    def defaults(self) -> dict:
        return {k.name: k.default for k in self.knobs.values()}


def config_path() -> Path:
    from src import paths
    return Path(paths.repo_root()) / "config" / "house_pack.json"


def load(path: Optional[Path] = None) -> dict:
    """``{hound_id: TunableHound}`` for every pack hound that declares ``tunable``."""
    p = Path(path) if path is not None else config_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for h in (data.get("hounds") or []) if isinstance(data, dict) else []:
        raw = h.get("tunable")
        if not raw:
            continue
        knobs = {}
        for k in raw:
            knobs[k["name"]] = Knob(
                name=k["name"], label=k.get("label") or k["name"], kind=k.get("kind") or "float",
                default=k["default"], lo=k["min"], hi=k["max"], step=k["step"],
                renders=tuple(dict(r) for r in k.get("renders") or ()))
        out[h["id"]] = TunableHound(
            hound_id=h["id"], name=h.get("name") or h["id"], category=h.get("category") or "mixed",
            module=h.get("module") or "", rule_text=h.get("rule_text") or "",
            sports=tuple(h.get("sports") or ()), markets=tuple(h.get("markets") or ()), knobs=knobs)
    return out


# ---- values -------------------------------------------------------------------------------------

def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _typed(knob: Knob, value: float):
    if knob.kind == "int":
        return int(round(value))
    return round(value, 6)


def full_values(hound: TunableHound, overrides: Optional[Mapping] = None) -> dict:
    """The declared defaults with ``overrides`` laid over them, typed."""
    out = {}
    for name, knob in hound.knobs.items():
        v = knob.default
        if overrides and name in overrides:
            v = overrides[name]
        out[name] = _typed(knob, float(v))
    return out


def validate(hound: TunableHound, champion_values: Mapping, proposed: Any) -> dict:
    """The full knob values of a challenger, or TunableError carrying every problem at once."""
    errors: dict = {}
    if not isinstance(proposed, Mapping) or not proposed:
        raise TunableError({"params": "must be an object of knob values"})
    for name in proposed:
        if name not in hound.knobs:
            errors[str(name)] = "is not a knob this hound declares"
    values = dict(champion_values)
    for name, knob in hound.knobs.items():
        if name not in proposed or name in errors:
            continue
        raw = _number(proposed[name])
        if raw is None:
            errors[name] = "must be a number"
            continue
        if knob.kind == "int" and abs(raw - round(raw)) > _EPS:
            errors[name] = "must be a whole number"
            continue
        if raw < knob.lo - _EPS or raw > knob.hi + _EPS:
            errors[name] = f"must be between {knob.lo:g} and {knob.hi:g}"
            continue
        if not knob.on_grid(raw):
            errors[name] = f"must be {knob.lo:g} plus a whole number of steps of {knob.step:g}"
            continue
        values[name] = _typed(knob, raw)
    if errors:
        raise TunableError(errors)
    changed = diff(champion_values, values)
    if not changed:
        raise TunableError({"params": "no knob differs from the champion's"})
    if len(changed) > rules.MAX_KNOBS_CHANGED:
        raise TunableError({"params": f"a challenger may change at most {rules.MAX_KNOBS_CHANGED} "
                                      f"knobs; this changes {len(changed)}"})
    return values


def diff(old: Mapping, new: Mapping) -> dict:
    """``{knob: [old, new]}`` for every knob whose value differs."""
    return {k: [old.get(k), new[k]] for k in new if abs(float(new[k]) - float(old.get(k, new[k]))) > _EPS}


def values_hash(values: Mapping) -> str:
    body = json.dumps({k: values[k] for k in sorted(values)}, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def near_duplicate(hound: TunableHound, a: Mapping, b: Mapping) -> bool:
    """Same idea: every knob within one step of the other's (prereg section 3, rule 8)."""
    for name, knob in hound.knobs.items():
        if abs(float(a.get(name, knob.default)) - float(b.get(name, knob.default))) > knob.step + _EPS:
            return False
    return True


# ---- the published words ---------------------------------------------------------------------------

def render(knob: Knob, value: float) -> list:
    """``[(literal, replacement)]`` for one knob at ``value``."""
    return [(r["literal"], r["format"].format(value * float(r.get("scale", 1)))) for r in knob.renders]


def rule_text(hound: TunableHound, values: Mapping) -> str:
    """The champion's declared rule text with each knob's strings replaced by its value. At the
    declared defaults this IS the declared text (a test pins it)."""
    text = hound.rule_text
    base = full_values(hound)
    for name, knob in hound.knobs.items():
        if abs(float(values.get(name, knob.default)) - float(base[name])) < _EPS:
            continue
        for old, new in render(knob, values[name]):
            text = text.replace(old, new)
    return text


# ---- running a hound with a challenger's values ----------------------------------------------------------

@contextmanager
def patched(module_name: str, values: Mapping, defaults: Mapping):
    """Set the module's constants to ``values`` for the length of the block, then put back exactly
    what was there. Under a lock: two patches never overlap."""
    mod = importlib.import_module(module_name)
    with _PATCH_LOCK:
        before = {name: getattr(mod, name) for name in values}
        try:
            for name, v in values.items():
                setattr(mod, name, v)
            yield mod
        finally:
            for name, v in before.items():
                setattr(mod, name, v)


class VersionedHound:
    """A pack hound running with a version's knob values, under an id of the caller's choice.

    Used for a champion version above 1 (``hound_id`` = the hound's own id, so its rows stay its
    own) and for a challenger (``hound_id`` = the challenger id). Everything but ``pick`` and the id
    is the base hound's. ``row_extra`` is stamped onto every bet row the runner writes."""

    def __init__(self, base, tunable: TunableHound, values: Mapping, *, hound_id: Optional[str] = None,
                 row_extra: Optional[Mapping] = None, min_lock=None):
        object.__setattr__(self, "_min_lock", min_lock)
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_tunable", tunable)
        object.__setattr__(self, "_values", dict(values))
        object.__setattr__(self, "id", hound_id or base.id)
        object.__setattr__(self, "row_extra", dict(row_extra or {}))

    def __getattr__(self, item):
        return getattr(self._base, item)

    def applies_to(self, sport: str) -> bool:
        return self._base.applies_to(sport)

    def accepts(self, ctx) -> bool:
        """Only games whose lock is at or after ``min_lock`` (a challenger's proposal time, a
        promotion's effective time): no game is bet by a version that did not exist at its lock."""
        return self._min_lock is None or ctx.lock >= self._min_lock

    def pick(self, board, ctx):
        with patched(self._tunable.module, self._values, self._tunable.defaults()):
            return self._base.pick(board, ctx)
