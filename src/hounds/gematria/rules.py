"""The Gematria Hound's rules: weights, thresholds and the price band, read from a VERSIONED file.

WHY VERSIONED AND NEVER EDITED. The hound is graded in public. If a threshold could be nudged after a run of losses
the record would measure the nudging, not the rule. So a rules file (``config/gematria/rules_v1.json``) is frozen the
moment a pick is made under it; "improving the selection rules" means a NEW file (``rules_v2.json``), a new
``hound_version`` inside it, and one line changed in ``config/gematria/active.json``. Every bet row carries the
``rules_version`` and ``rules_hash`` it was made under, so a past pick can always be traced to the exact bytes.

``Rules.from_dict`` is strict on purpose: an unknown match kind or a missing weight is an error at load time, not a
silently-zero weight discovered after a season.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.research import gematria

KINDS = (
    "headline_milestone",       # THE post's headline: a count in this world that several other numbers also equal
    "milestone_eq_name",        # a count in the 'if this side wins' world equals a name's cipher value
    "milestone_eq_state",       # ... equals a team's state's order of statehood ("Georgia, the 4th state")
    "milestone_eq_date",        # ... equals a number of the game date (month+day+yy, day of year, digit sum ...)
    "milestone_eq_span",        # ... equals a span counted from a founding/admission date to the game
    "milestone_eq_fact_number", # ... equals a jersey number, area code or similar standing number of a team (when the facts hold one)
    "milestone_eq_count",       # ... equals a plain count that does not depend on the result (game number, meeting number)
    "milestone_eq_milestone",   # two counts in the same 'if this side wins' world are equal
    "prime_link",               # one number is the Nth prime of another ("67 = the 19th prime", 19 elsewhere)
    "triangular_link",          # one number is the Nth triangular number of another ("66 = 11th Tri #")
    "special_33_47",            # a count in that world is 33 or 47
    "own_name_eq_date",         # a side's own name value equals a number of the game date (no result needed)
)

DEFAULT_ACTIVE = "rules_v1.json"


class RulesError(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    markets: Tuple[str, ...] = ("moneyline",)
    min_margin: float = 3.0
    min_milestones_per_side: int = 3
    max_search_imbalance: float = 0.35
    price_band: Tuple[int, int] = (-199, 400)
    max_picks_per_day: int = 3
    lock_minutes: int = 60
    confidence_bands: Tuple[float, ...] = (6.0, 10.0, 15.0, 22.0)      # margin needed for confidence 2, 3, 4, 5 (1 below the first)
    counter_signal_ratio: float = 0.85                               # a losing side this close to the winner costs one point of confidence


@dataclass(frozen=True)
class Rules:
    version: str
    hound_version: str
    hound_number: int
    ciphers: Tuple[str, ...]
    cipher_weights: Dict[str, float]
    kind_weights: Dict[str, float]
    min_value: int
    max_value: int
    special_numbers: Tuple[int, ...]
    special_bonus: float
    span_units: Tuple[str, ...]
    span_inclusive: Tuple[bool, ...]
    decision: Decision
    evidence_top_n: int
    headline_min_support: int = 3
    rules_hash: str = ""
    source: str = ""

    @classmethod
    def from_dict(cls, data: dict, *, raw_bytes: Optional[bytes] = None, source: str = "") -> "Rules":
        try:
            kw = data["kind_weights"]
            missing = [k for k in KINDS if k not in kw]
            extra = [k for k in kw if k not in KINDS]
            if missing or extra:
                raise RulesError(f"kind_weights must name exactly the known kinds; missing {missing}, unknown {extra}")
            ciphers = tuple(data["ciphers"])
            for c in ciphers:
                if c not in gematria.CIPHERS:
                    raise RulesError(f"unknown cipher {c!r}")
            cw = {c: float(data["cipher_weights"][c]) for c in ciphers}
            for unit in data["span_units"]:
                if unit not in gematria.SPAN_UNITS:
                    raise RulesError(f"unknown span unit {unit!r}")
            d = data["decision"]
            band = d["price_band"]
            dec = Decision(markets=tuple(d["markets"]), min_margin=float(d["min_margin"]),
                           min_milestones_per_side=int(d["min_milestones_per_side"]),
                           max_search_imbalance=float(d["max_search_imbalance"]), price_band=(int(band[0]), int(band[1])),
                           max_picks_per_day=int(d["max_picks_per_day"]), lock_minutes=int(d["lock_minutes"]),
                           confidence_bands=tuple(float(x) for x in d.get("confidence_bands", (6.0, 10.0, 15.0, 22.0))),
                           counter_signal_ratio=float(d.get("counter_signal_ratio", 0.85)))
            if dec.price_band[0] <= -200:
                raise RulesError("the price band may never include -200 or worse")
            # Hashed with LF line endings: core.autocrlf turns the file CRLF on a Windows checkout, and the same rules
            # must carry the same hash there as in the Linux image (the committed bytes).
            digest = hashlib.sha256(raw_bytes.replace(b"\r\n", b"\n")).hexdigest() if raw_bytes is not None else ""
            return cls(version=str(data["version"]), hound_version=str(data["hound_version"]),
                       hound_number=int(data["hound_number"]), ciphers=ciphers,
                       cipher_weights=cw, kind_weights={k: float(v) for k, v in kw.items()},
                       min_value=int(data["min_value"]), max_value=int(data["max_value"]),
                       special_numbers=tuple(int(x) for x in data["special_numbers"]),
                       special_bonus=float(data["special_bonus"]), span_units=tuple(data["span_units"]),
                       span_inclusive=tuple(bool(x) for x in data["span_inclusive"]), decision=dec,
                       evidence_top_n=int(data["evidence_top_n"]),
                       headline_min_support=int(data.get("headline_min_support", 3)), rules_hash=digest, source=source)
        except KeyError as exc:
            raise RulesError(f"rules file is missing {exc}") from exc

    def in_range(self, value: int) -> bool:
        return self.min_value <= value <= self.max_value


def config_dir(root: Optional[Path] = None) -> Path:
    from src import paths

    return (Path(root) if root else Path(paths.repo_root())) / "config" / "gematria"


def active_file(root: Optional[Path] = None) -> str:
    try:
        data = json.loads((config_dir(root) / "active.json").read_text(encoding="utf-8"))
        return str(data.get("rules") or DEFAULT_ACTIVE)
    except (OSError, ValueError):
        return DEFAULT_ACTIVE


def load(name: Optional[str] = None, root: Optional[Path] = None) -> Rules:
    """Load a rules file by file name (default: the one ``active.json`` names)."""
    fname = name or active_file(root)
    if "/" in fname or "\\" in fname or ".." in fname:
        raise RulesError(f"not a rules file name: {fname!r}")
    path = config_dir(root) / fname
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise RulesError(f"cannot read {path}: {exc}") from exc
    return Rules.from_dict(data, raw_bytes=raw, source=fname)
