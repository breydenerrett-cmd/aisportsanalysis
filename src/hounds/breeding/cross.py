"""A baby's knobs: crossover on the grid, a one-step mutation, and the litter plan
(docs/PREREG_BREEDING.md sections 3 and 4).

DETERMINISTIC. Every draw comes from ``rng_for(cycle_date, hound_id)``, one stream per family, in a fixed
order: for a pair, one crossover draw per knob in name order, then the mutation draw, then (if it
mutates) the knob draw and the direction draw. A single-parent baby skips the crossover and the mutation
draws and always mutates. A crossover that copies either parent exactly is forced to mutate (its
mutation draw is still consumed, so the stream stays aligned).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from src.hounds.breeding import rules
from src.hounds.breeding.select import Member

_EPS = 1e-9


def rng_for(cycle_date: str, hound_id: str) -> random.Random:
    return random.Random(f"breeding|{cycle_date}|{hound_id}")


def _typed(knob, value: float):
    if knob.kind == "int":
        return int(round(value))
    return round(value, 6)


def grid_index(knob, value: float) -> int:
    return int(round((float(value) - knob.lo) / knob.step))


def on_grid_value(knob, index: int):
    return _typed(knob, knob.lo + index * knob.step)


def same(a: Mapping, b: Mapping) -> bool:
    return set(a) == set(b) and all(abs(float(a[k]) - float(b[k])) < _EPS for k in a)


def crossover(tun, a: Mapping, b: Mapping, rng: random.Random) -> tuple:
    """``(values, origin)``: each knob from A (draw below 0.5) or B. ``origin`` maps knob -> "A"/"B"."""
    values, origin = {}, {}
    for name in sorted(tun.knobs):
        knob = tun.knobs[name]
        if rng.random() < rules.CROSSOVER_PROBABILITY:
            values[name], origin[name] = _typed(knob, a[name]), "A"
        else:
            values[name], origin[name] = _typed(knob, b[name]), "B"
    return values, origin


def mutate(tun, values: Mapping, rng: random.Random) -> tuple:
    """``(new values, {"knob", "from", "to"})``: one knob, chosen uniformly in name order, one step up or
    down (a draw); a step that would leave the bounds goes the other way."""
    names = sorted(tun.knobs)
    name = names[rng.randrange(len(names))]
    knob = tun.knobs[name]
    direction = 1 if rng.random() < 0.5 else -1
    idx = grid_index(knob, values[name])
    top = grid_index(knob, knob.hi)
    new_idx = idx + direction * rules.MUTATION_STEPS
    if new_idx < 0 or new_idx > top:
        new_idx = idx - direction * rules.MUTATION_STEPS
    new_idx = max(0, min(top, new_idx))
    out = dict(values)
    out[name] = on_grid_value(knob, new_idx)
    return out, {"knob": name, "from": values[name], "to": out[name]}


@dataclass
class Baby:
    hound_id: str
    values: dict
    origin: dict                   # knob -> "A" | "B" (a single parent: all "A")
    mutation: Optional[dict]
    parents: tuple                 # (Member, ...) one or two


def make_baby(tun, parents: Sequence[Member], rng: random.Random) -> Baby:
    if len(parents) == 2:
        a, b = parents
        values, origin = crossover(tun, a.values, b.values, rng)
        coin = rng.random() < rules.MUTATION_PROBABILITY
        clone = same(values, a.values) or same(values, b.values)
        mutation = None
        if coin or clone:
            values, mutation = mutate(tun, values, rng)
        return Baby(tun.hound_id, values, origin, mutation, (a, b))
    (a,) = parents
    values, mutation = mutate(tun, dict(a.values), rng)
    return Baby(tun.hound_id, values, {k: "A" for k in sorted(tun.knobs)}, mutation, (a,))


@dataclass
class Litter:
    hound_id: str
    kind: str                      # "pair" | "single" | "replacement"
    parents: tuple                 # Members
    culled: Optional[Member] = None
    extra: dict = field(default_factory=dict)


def plan(pool: Sequence[Member], replacements: Sequence[tuple] = ()) -> list:
    """The litters in order: one per family of the pool, in the order of its best member's rank (two
    or more in the pool: a pair of its two best; one: a single parent), then the cull replacements
    ``(culled, best_relative)``."""
    out, seen = [], []
    for m in pool:
        if m.hound_id in seen:
            continue
        seen.append(m.hound_id)
        fam = [x for x in pool if x.hound_id == m.hound_id]
        if len(fam) >= 2:
            out.append(Litter(m.hound_id, "pair", (fam[0], fam[1])))
        else:
            out.append(Litter(m.hound_id, "single", (fam[0],)))
    for culled, relative in replacements:
        out.append(Litter(culled.hound_id, "replacement", (relative,), culled=culled))
    return out


def hypothesis(baby: Baby, cycle_date: str, generation: int, kind: str) -> str:
    """The code-written reason on the proposal. Only the hound id and plain words: no knob names (some
    contain league abbreviations the public text filter reserves) and no ids or dates (they are in the
    evidence references)."""
    if len(baby.parents) == 2:
        from_a = sum(1 for v in baby.origin.values() if v == "A")
        from_b = len(baby.origin) - from_a
        body = (f"Breeding cycle: a cross of two relatives of {baby.hound_id} ranked on forward closing-line "
                f"value only, generation {generation}; {from_a} knob(s) from the better parent, {from_b} "
                f"from the other")
    elif kind == "replacement":
        body = (f"Breeding cycle: a replacement for a culled member of {baby.hound_id}, made from its best "
                f"relative ranked on forward closing-line value only, generation {generation}")
    else:
        body = (f"Breeding cycle: a variant of a top-ranked member of {baby.hound_id} ranked on forward "
                f"closing-line value only, generation {generation}")
    if baby.mutation:
        body += "; one knob moved one step"
    return body + ". It starts at 0-0 and only the referee can promote it."


def evidence(baby: Baby, cycle_date: str, culled: Optional[Member] = None) -> list:
    refs = [f"breeding:{cycle_date}"] + [f"parent:{p.ref()}" for p in baby.parents]
    if culled is not None:
        refs.append(f"culled:{culled.ref()}")
    return refs
