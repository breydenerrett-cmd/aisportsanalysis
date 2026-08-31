"""The candidate funnel: a pre-registered hypothesis in minutes, not modules.

WHY THIS EXISTS
---------------
V1 spent days of bespoke engineering per detector; V2 spent a module per
hypothesis. Both meant the marginal hypothesis was expensive, so few were
asked, and the ones that were asked carried sunk cost that made them hard to
kill. With the matchup matrix built once (src/research/matrix.py), a serious
lineup-shaped hypothesis is now a SPEC -- a plain dict naming a feature, a
threshold and a mechanism -- and this module runs the whole discipline over it
in one batch pass: feasibility, a 2023 screen, a 2024 replication, the
falsification battery, and the family correction.

THE FUNNEL GATES SPENDING, NEVER THE DENOMINATOR
------------------------------------------------
Read this before trusting any number below. The early levels exist to stop
WORK -- no point running the battery on a hypothesis the data cannot power, or
replicating one that showed nothing on the screen. They do NOT shrink the
multiple-comparison family. Every spec that enters run() is counted in the
Benjamini-Hochberg denominator, including the ones that died at level 0 with
no p-value at all (those enter at p = 1.0: they were hypotheses that were
looked at, and a look is a look). Gating the denominator on early screens
would be p-hacking with extra steps -- "we only corrected for the survivors"
is exactly the move the family file in src/model/family.py exists to prevent.

WHAT A SPEC IS
--------------
{name, market, feature, side_rule, threshold, min_sample, effect_floor,
 mechanism, direction} -- validated hard, because a silently-misread spec is a
hypothesis nobody actually stated. `mechanism` must be non-empty prose: no
rationale, no test. A hypothesis that cannot say WHY the market should misprice
this feature is a data-dredge with a name.

SIGN CONVENTION (side_rule "back_advantaged")
---------------------------------------------
The matrix carries each feature per side: away_<feature> describes the AWAY
lineup's matchup, home_<feature> the home lineup's. The game-level signal is

    value = away_<feature> - home_<feature>   (away minus home, always)

so a POSITIVE value means the away side holds more of the feature and the
funnel identifies AWAY as the advantaged side; negative, HOME. |value| >=
threshold to fire; either side None means no selection (None over guess --
half a differential is not a differential). `direction` decides WHO GETS
BACKED: "positive" backs the advantaged side, "negative" backs the other one
(the market-overrates-it hypothesis). The flip happens at construction, in
one place, so every spec's graded hypothesis reads identically -- the backed
side beats its implied -- and the battery's positive-effect fatal rules apply
to all specs without a per-direction seam.

WHY THE PRICE JOIN IS IMPORTED, NOT REWRITTEN
---------------------------------------------
Selections are priced through the same helpers src/model/selections.py uses:
canonical team spellings on both ends, list-valued (away, home, date) keys,
and _resolve_pair's three-hour commence-time gate. That join once silently
priced 55% of matched games from the NEXT game's odds; the fix lives in one
place and is reused here rather than re-implemented.

Every statistic clusters by date via src/model/discovery.py -- selections on
one slate are correlated, and an unclustered p here would poison the family
correction downstream.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.data import parks
from src.model import discovery
from src.model import family
from src.model import selections
from src.pipeline import backfill
from src.pipeline import history
from src.research import battery
from src.research import coverage
from src.research import matrix
from src.research import scoreboard

# The matrix columns a spec may name: the numeric per-side features, base name
# only (the away_/home_ prefixes are the funnel's to apply). A typo'd feature
# would otherwise surface as 0% coverage -- indistinguishable from honest data
# poverty -- so unknown names are rejected at validation instead.
NUMERIC_FEATURES = ("lineup_platoon_share", "starter_platoon_gap",
                    "lineup_vs_primary_pitch", "primary_pitch_share",
                    "top_minus_bottom",
                    # Registered 2026-08-31 with the V5 pre-registration,
                    # after their point-in-time injection tests and the
                    # coverage measurement (velocity 55%/75%, groundball
                    # 60%/85% both-sides by season) -- never before a
                    # family that uses them exists on paper.
                    "starter_velocity_gap", "starter_groundball_share")

# An INTERACTION feature is two base features joined by "*": the per-side
# value is their product, computed on each side before the away-minus-home
# differential is taken. The matrix already cross-joins every per-side
# feature against what that side actually faces tonight (away_* features
# describe the away lineup against the HOME starter), so a product is the
# "unit versus specific weakness" construction directly: a big one-handed
# lineup share times a big opposing-starter platoon gap is a lineup built to
# exploit tonight's exact weakness, and a NEGATIVE component flips the
# product's sign exactly as the mechanism says it should (a "weakness" that
# is really a strength counts against the side, not for it). Both components
# must answer on both sides or the signal is None -- half an interaction is
# not an interaction.
INTERACTION_SEPARATOR = "*"

# The only construction rules a spec may name today. Tuples, not strings, so
# adding a rule is a visible edit here rather than a stringly-typed drive-by.
MARKETS = ("h2h",)
SIDE_RULES = ("back_advantaged",)
DIRECTIONS = ("positive", "negative")

# The 2023 screen judges on roughly half the data, so it gets a fraction of
# min_sample rather than all of it; 0.4 leaves slack for coverage that is not
# split evenly across the two seasons.
SCREEN_SAMPLE_FRACTION = 0.4

# Replication demands the 2024 effect keep at least half the floor in the
# hypothesized direction. Half, not the full floor: a real effect measured
# twice will wobble, and demanding the full floor twice over would kill true
# positives for the crime of variance.
REPLICATION_FLOOR_FRACTION = 0.5

# The funnel is a discovery instrument: the screen season and the replication
# season, in that order, and nothing else. 2025-26 are tuning/sealed.
DISCOVERY_SEASONS = (2023, 2024)

STATUSES = ("blocked_coverage", "screen_dead", "no_replication",
            "killed_by_battery", "underpowered", "failed_fdr", "candidate")

# The wider graded sample runs at half the spec threshold. Half, not less:
# far-below-threshold rows are a different population and would let a
# spurious "contradiction" kill a real effect; just-below-threshold rows are
# the honest control for a dose spike.
DIAGNOSTIC_FRACTION = 0.5


class FunnelError(RuntimeError):
    """Raised when a spec, a registration or a run cannot proceed honestly."""


# ---------------------------------------------------------------------------
# Spec validation and family registration
# ---------------------------------------------------------------------------

def validate_spec(spec) -> dict:
    """A normalized copy of one spec, or FunnelError.

    Hard validation because a spec is a pre-registered hypothesis: a field
    silently coerced or defaulted is a hypothesis nobody actually wrote down.
    """
    if not isinstance(spec, dict):
        raise FunnelError(f"a spec must be a dict, got {type(spec).__name__}")
    missing = [k for k in ("name", "market", "feature", "side_rule",
                           "threshold", "min_sample", "effect_floor",
                           "mechanism", "direction") if k not in spec]
    if missing:
        raise FunnelError(f"spec is missing {missing}")

    name = spec["name"]
    if not isinstance(name, str) or not name.strip():
        raise FunnelError("spec name must be a non-empty string")
    if spec["market"] not in MARKETS:
        raise FunnelError(f"spec {name!r}: market must be one of {MARKETS}, "
                          f"got {spec['market']!r}")
    feature = spec["feature"]
    if not isinstance(feature, str):
        raise FunnelError(f"spec {name!r}: feature must be a string")
    parts = feature.split(INTERACTION_SEPARATOR)
    if len(parts) == 2:
        bad = [p for p in parts if p not in NUMERIC_FEATURES]
        if bad:
            raise FunnelError(
                f"spec {name!r}: interaction component(s) {bad} are not "
                f"numeric matrix columns; expected {NUMERIC_FEATURES}")
        if parts[0] == parts[1]:
            raise FunnelError(
                f"spec {name!r}: an interaction of a feature with itself is "
                "a squared single feature wearing a costume; name the single "
                "feature and its own threshold instead")
    elif feature not in NUMERIC_FEATURES:
        raise FunnelError(
            f"spec {name!r}: feature {feature!r} is not a numeric "
            f"matrix column; expected one of {NUMERIC_FEATURES} (base name, "
            "no away_/home_ prefix) or two of them joined by "
            f"'{INTERACTION_SEPARATOR}'")
    if spec["side_rule"] not in SIDE_RULES:
        raise FunnelError(f"spec {name!r}: side_rule must be one of "
                          f"{SIDE_RULES}, got {spec['side_rule']!r}")
    if spec["direction"] not in DIRECTIONS:
        raise FunnelError(f"spec {name!r}: direction must be one of "
                          f"{DIRECTIONS}, got {spec['direction']!r}")
    threshold = spec["threshold"]
    if not _numeric(threshold) or not threshold > 0:
        raise FunnelError(f"spec {name!r}: threshold must be a number > 0 "
                          "(at 0 the fired side is undefined)")
    min_sample = spec["min_sample"]
    if not isinstance(min_sample, int) or isinstance(min_sample, bool) \
            or min_sample < 1:
        raise FunnelError(f"spec {name!r}: min_sample must be an int >= 1")
    effect_floor = spec["effect_floor"]
    if not _numeric(effect_floor) or not effect_floor > 0:
        raise FunnelError(f"spec {name!r}: effect_floor must be a number > 0")
    mechanism = spec["mechanism"]
    if not isinstance(mechanism, str) or not mechanism.strip():
        raise FunnelError(
            f"spec {name!r}: mechanism is required and non-empty -- a "
            "hypothesis with no stated reason the market should misprice "
            "this feature does not get tested")

    return {"name": name.strip(), "market": spec["market"],
            "feature": spec["feature"], "side_rule": spec["side_rule"],
            "threshold": float(threshold), "min_sample": min_sample,
            "effect_floor": float(effect_floor),
            "mechanism": mechanism.strip(), "direction": spec["direction"]}


def _validated_family(specs) -> list:
    out = [validate_spec(s) for s in specs]
    names = [s["name"] for s in out]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        # The correction and the report both key by name; two hypotheses
        # sharing one would silently merge into a single family slot.
        raise FunnelError(f"duplicate spec names: {dupes}")
    return out


def register_family(specs, path, now=None, note=None) -> dict:
    """Freeze the exploratory family to a JSON file, before any result exists.

    Mirrors src/model/family.register: once written, the file IS the count.
    Re-registering the identical family returns the stored payload;
    re-registering a different one raises, because changing the family changes
    every correction computed from it -- that change must be a visible diff,
    never an overwrite.
    """
    target = Path(path)
    validated = _validated_family(specs)
    payload = {
        "registered_at": (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc).isoformat(),
        "specs": validated,
        "count": len(validated),
        "fdr_q": family.FDR_Q,
        "note": note,
    }
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FunnelError(f"{target} is not valid JSON") from exc
        if existing.get("specs") != validated:
            added = [s["name"] for s in validated
                     if s not in existing.get("specs", [])]
            removed = [s["name"] for s in existing.get("specs", [])
                       if s not in validated]
            raise FunnelError(
                f"a family of {existing.get('count')} specs was registered at "
                f"{target} on {existing.get('registered_at')} and this call "
                f"has {len(validated)}. Added or changed: {added or 'none'}. "
                f"Removed or changed: {removed or 'none'}. Re-register "
                "deliberately, with the old file deleted in the same commit.")
        return existing
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=1, sort_keys=True),
                      encoding="utf-8")
    return payload


# ---------------------------------------------------------------------------
# Selection construction (one place, shared by every level)
# ---------------------------------------------------------------------------

def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _side_value(row, prefix, feature):
    """One side's value: the column itself, or the interaction product.

    A product with a missing component is None, never a guess -- an
    interaction half-known is not known at all.
    """
    parts = feature.split(INTERACTION_SEPARATOR)
    if len(parts) == 2:
        first, second = row.get(prefix + parts[0]), row.get(prefix + parts[1])
        if not _numeric(first) or not _numeric(second):
            return None
        return first * second
    value = row.get(prefix + feature)
    return value if _numeric(value) else None


def _signal(row, feature):
    """away minus home, or None when either side cannot answer.

    The sign convention documented at module top lives here and only here.
    """
    away = _side_value(row, "away_", feature)
    home = _side_value(row, "home_", feature)
    if away is None or home is None:
        return None
    return away - home


def _selections_for(spec, rows, price_index, results, season,
                    fraction=1.0) -> list:
    """Graded selections for one spec over one season's matrix rows.

    `fraction` scales the firing threshold. The funnel grades a WIDER sample
    at half the spec threshold purely for the battery's dose diagnostics --
    without sub-threshold graded rows, the dose-response check that killed M3
    has no band below the threshold to contradict a spike and is structurally
    disarmed. Rows carry "selected" so the wider sample can never leak into
    the levels' own measurements.

    The join is selections.py's, imported: canonical spellings on both ends of
    the (away, home, date) key, and _resolve_pair breaking series ties by the
    game's own start time inside the three-hour gate. Season is stamped from
    the caller's declaration, never derived from the date -- the battery
    docstring explains why that call is not this module's to make.
    """
    out = []
    threshold = spec["threshold"] * fraction
    for row in rows:
        value = _signal(row, spec["feature"])
        if value is None or abs(value) < threshold:
            continue
        # Direction is resolved HERE, once: a "positive" spec backs the side
        # the signal favours, a "negative" spec backs the other one. After
        # this line every spec's hypothesis reads the same way -- the backed
        # side beats its implied -- so the battery's fatal rules, which are
        # written for a positive effect, apply to every spec without a sign
        # seam anyone has to remember downstream.
        advantaged = "away" if value > 0 else "home"
        if spec["direction"] == "positive":
            side = advantaged
        else:
            side = "home" if advantaged == "away" else "away"

        key = (parks.canonical_team(row.get("away_team") or ""),
               parks.canonical_team(row.get("home_team") or ""),
               row.get("date"))
        pair = selections._resolve_pair(price_index.get(key), row)
        # Same acceptance rule as selections.build: no pair, or a pair whose
        # open and close are one observation, prices nothing.
        if not pair or not pair.get("distinct"):
            continue
        # Graded against the CLOSE, deliberately. Every matrix feature is a
        # posted-lineup function, and lineups usually post inside the six-hour
        # recommendation lead -- grading lineup-built selections against the
        # earlier price would credit the selection with information the price
        # had not seen yet, manufacturing effect out of timing. The close
        # (median 84 minutes out) is the sharpest benchmark on file; a real
        # effect measured against it is smaller and honest. Residual risk --
        # a lineup posting inside the close gap -- is documented in
        # docs/RESEARCH-notes and is exactly the V3 information-timing
        # question, never this module's shortcut.
        grading = selections._fair(pair["close"]["bookmakers"],
                                   pair["home_team"], pair["away_team"])
        if not grading:
            continue

        home_won = selections._label(
            (results.get(str(row.get("game_pk"))) or {}).get("home_won"))
        if home_won is None:
            continue  # unresolved games are skipped, never guessed

        picked_home = side == "home"
        price = grading["home_price"] if picked_home else grading["away_price"]
        price_key = "home_price" if picked_home else "away_price"
        # Every book tied at the best price, not just whichever the API
        # listed first: leave-one-book-out has to remove the rows a book
        # actually carried, ties included.
        at_best = sorted({q["book"] for q in grading["quotes"]
                          if q[price_key] == price and q["book"]})
        out.append({
            "game_pk": str(row.get("game_pk")),
            "date": row.get("date"),
            "season": season,
            "side": side,
            "team": row.get(side + "_team"),
            "book": at_best[0] if at_best else None,
            "books_at_best": at_best,
            "price": price,
            "implied": round(grading["home_fair"] if picked_home
                             else grading["away_fair"], 5),
            "won": bool(home_won) if picked_home else not home_won,
            # The battery's dose: signal magnitude, direction-free.
            "dose": round(abs(value), 6),
            "selected": abs(value) >= spec["threshold"],
        })
    return out


def _dose_edges(selected, threshold) -> list:
    """Band edges for the dose check: the sub-threshold band, then quartiles.

    The spec threshold is always an edge, so "the band just below the
    threshold" is a real band rather than an artifact of quartiles computed
    over selected rows that all cleared it.
    """
    doses = sorted(r["dose"] for r in selected)
    if not doses:
        return None
    edges = [threshold * DIAGNOSTIC_FRACTION, threshold]
    for q in (0.5,):
        edges.append(doses[int((len(doses) - 1) * q)])
    edges.append(doses[-1])
    out = []
    for edge in edges:
        if not out or edge > out[-1]:
            out.append(edge)
    return out if len(out) >= 3 else [threshold * DIAGNOSTIC_FRACTION,
                                      threshold, doses[-1]]


def _measure(rows):
    """(n, effect, clustered p) for graded selections; None below n=1."""
    n = len(rows)
    if not n:
        return 0, None, None
    diff_rows = [dict(r, _diff=(1.0 if r["won"] else 0.0) - r["implied"])
                 for r in rows]
    effect = sum(r["_diff"] for r in diff_rows) / n
    return n, round(effect, 5), round(
        discovery.clustered_two_sided_p(effect, diff_rows), 6)


# ---------------------------------------------------------------------------
# The funnel
# ---------------------------------------------------------------------------

def run(specs, seasons=DISCOVERY_SEASONS, *, family_path=None,
        matrix_rows=None, price_pairs=None, results=None, started="",
        finished="", notes="", scoreboard_path=scoreboard.DEFAULT_STORE) -> list:
    """Run every spec through the funnel; one result row per spec, spec order.

    seasons is (screen, replication) and must be the discovery pair -- the
    guard is structural, same as matrix.py's: no argument value may put sealed
    data one call away. `matrix_rows` ({season: iterable of matrix rows}),
    `price_pairs` ({season: backfill.price_pair output}) and `results`
    (game_pk -> results row) are injectable seams for tests; defaults read the
    real stores. `started`/`finished` are the caller's timestamps -- this
    module never invents one (the scoreboard docstring owns that rule).
    `scoreboard_path=None` skips recording.

    Row: {name, status, level_reached, n_2023, effect_2023, n_pooled,
    effect_pooled, p_pooled, q_pass, battery_fatal, notes} plus the FDR
    bookkeeping (p_fdr, fdr_family_size, fdr_threshold) and per-level extras.
    q_pass reports the FDR-and-floor gate for EVERY spec -- a battery-killed
    spec can carry q_pass=True and stay dead, because the battery and the
    correction answer different questions.
    """
    validated = _validated_family(specs)

    # Pre-registration is enforced at run time, not merely offered: the specs
    # this run evaluates must BE the frozen family, byte for byte. Without
    # this check, register_family is a ceremony -- anyone could register one
    # list and run another, and the FDR denominator would describe a family
    # that was never actually tested. family_path=None is for unit tests of
    # the machinery itself and says so loudly in the output rows.
    if family_path is not None:
        target = Path(family_path)
        if not target.exists():
            raise FunnelError(
                f"no registered family at {target}; register_family first -- "
                "evaluation before registration is the thing this module "
                "exists to prevent")
        frozen = json.loads(target.read_text(encoding="utf-8"))
        if frozen.get("specs") != validated:
            raise FunnelError(
                f"the specs handed to run() differ from the family frozen at "
                f"{target} ({frozen.get('registered_at')}); evaluate exactly "
                "what was registered, or re-register deliberately")

    if tuple(seasons) != DISCOVERY_SEASONS:
        raise FunnelError(f"seasons must be {DISCOVERY_SEASONS} "
                          f"(screen, replication); got {tuple(seasons)}")
    screen_season, rep_season = seasons

    if matrix_rows is None:
        matrix_rows = {s: list(matrix.read(s).values()) for s in seasons}
    rows_by_season = {s: list(matrix_rows.get(s) or []) for s in seasons}
    if price_pairs is None:
        price_pairs = {s: backfill.price_pair(s) for s in seasons}
    index_by_season = {s: selections.index_price_pairs(price_pairs.get(s) or {})
                       for s in seasons}
    if results is None:
        results = history.read_results()

    out = []
    for spec in validated:
        out.append(_run_spec(spec, rows_by_season, index_by_season, results,
                             screen_season, rep_season))

    _apply_fdr(validated, out, registered=family_path is not None)

    if scoreboard_path is not None:
        statuses = [row["status"] for row in out]
        scoreboard.record({
            "started": started, "finished": finished,
            "hypotheses_screened": len(out),
            # blocked_coverage is not a kill: that hypothesis was never
            # tested, only found unaffordable, and counting it as killed
            # would flatter a run that merely lacked data.
            "hypotheses_killed": sum(
                1 for s in statuses if s in ("screen_dead", "no_replication",
                                             "killed_by_battery",
                                             "failed_fdr")),
            "hypotheses_replicated": sum(
                1 for row in out if row["level_reached"] >= 3),
            "survivors": statuses.count("candidate"),
            "credits_spent": 0,  # the funnel reads local stores only
            "notes": notes,
        }, path=scoreboard_path)
    return out


def _run_spec(spec, rows_by_season, index_by_season, results,
              screen_season, rep_season) -> dict:
    row = {"name": spec["name"], "status": None, "level_reached": 0,
           "n_2023": None, "effect_2023": None, "p_2023": None,
           "n_2024": None, "effect_2024": None,
           "n_pooled": None, "effect_pooled": None, "p_pooled": None,
           "q_pass": False, "battery_fatal": None, "notes": "",
           "expected_n": None}
    # Direction was resolved when the selections were built (the backed side
    # is flipped for "negative" specs), so from here every hypothesis reads
    # "the backed side beats its implied" and the expected effect is positive.


    # LEVEL 0 -- feasibility, before any join runs. Coverage is games where
    # BOTH sides answer (half a differential is not a differential); the fire
    # rate is measured on those, and expected_n turns the product into a
    # usable-sample forecast the way coverage.py's docstring prescribes.
    all_rows = [r for season_rows in rows_by_season.values()
                for r in season_rows]
    games = len(all_rows)
    signals = [_signal(r, spec["feature"]) for r in all_rows]
    covered = [v for v in signals if v is not None]
    fired = [v for v in covered if abs(v) >= spec["threshold"]]
    feature_pct = (len(covered) / games) if games else 0.0
    fire_rate = (len(fired) / len(covered)) if covered else 0.0
    expected = coverage.expected_n(feature_pct, fire_rate=fire_rate,
                                   games=games)
    row["expected_n"] = expected
    if expected is None or expected < spec["min_sample"]:
        row["status"] = "blocked_coverage"
        row["notes"] = (f"expected n {expected} < min_sample "
                        f"{spec['min_sample']} (coverage "
                        f"{feature_pct:.1%}, fire rate {fire_rate:.1%} over "
                        f"{games} matrix games)")
        return row

    # LEVEL 1 -- the screen, on the screen season ONLY. The replication
    # season stays unread until the screen earns it, so a dead idea costs one
    # season's join and nothing more. The join runs once at HALF the
    # threshold; the level judges only the rows that actually fired, and the
    # sub-threshold remainder exists solely so the battery's dose-response
    # check has a below-threshold band to contradict a spike with.
    row["level_reached"] = 1
    screen_wide = _selections_for(spec, rows_by_season[screen_season],
                                  index_by_season[screen_season], results,
                                  screen_season, fraction=DIAGNOSTIC_FRACTION)
    screen = [r for r in screen_wide if r["selected"]]
    n_screen, effect_screen, p_screen = _measure(screen)
    row["n_2023"], row["effect_2023"], row["p_2023"] = (
        n_screen, effect_screen, p_screen)
    floor_n = SCREEN_SAMPLE_FRACTION * spec["min_sample"]
    if n_screen < floor_n:
        row["status"] = "screen_dead"
        row["notes"] = (f"{n_screen} screen selections is under "
                        f"{SCREEN_SAMPLE_FRACTION} x min_sample = "
                        f"{floor_n:.0f}")
        return row
    if effect_screen <= 0:
        row["status"] = "screen_dead"
        row["notes"] = (f"screen effect {effect_screen:+.5f} is not in the "
                        f"hypothesized {spec['direction']} direction")
        return row

    # LEVEL 2 -- replication on the held-out season, same construction.
    row["level_reached"] = 2
    rep_wide = _selections_for(spec, rows_by_season[rep_season],
                               index_by_season[rep_season], results,
                               rep_season, fraction=DIAGNOSTIC_FRACTION)
    rep = [r for r in rep_wide if r["selected"]]
    n_rep, effect_rep, _ = _measure(rep)
    row["n_2024"], row["effect_2024"] = n_rep, effect_rep
    rep_floor = REPLICATION_FLOOR_FRACTION * spec["effect_floor"]
    if effect_rep is None or effect_rep < rep_floor:
        row["status"] = "no_replication"
        row["notes"] = ("no replication selections" if effect_rep is None else
                        f"replication effect {effect_rep:+.5f} is under half "
                        f"the effect floor in the {spec['direction']} "
                        "direction (a sign flip counts)")
        return row

    # LEVEL 3 -- the falsification battery on the pooled sample. Pooling is
    # legitimate HERE because both seasons already showed the effect
    # independently; the battery's own season_split still gets the final say.
    row["level_reached"] = 3
    pooled = screen + rep
    pooled_wide = screen_wide + rep_wide
    n_pooled, effect_pooled, p_pooled = _measure(pooled)
    row["n_pooled"], row["effect_pooled"], row["p_pooled"] = (
        n_pooled, effect_pooled, p_pooled)

    # The battery judges the SELECTIONS; its dose checks see the wider graded
    # sample with the spec threshold as an explicit band edge, so the band
    # just below the threshold genuinely exists. Bands above the threshold
    # come from the selected rows' own quartiles.
    dose_edges = _dose_edges(pooled, spec["threshold"])
    verdict = battery.run(pooled, effect_floor=spec["effect_floor"],
                          dose_key="dose", dose_rows=pooled_wide,
                          dose_bands=dose_edges)
    row["battery_fatal"] = list(verdict["fatal"])
    if not verdict["survives"]:
        row["status"] = "killed_by_battery"
        row["notes"] = "fatal: " + ", ".join(verdict["fatal"])
        return row
    if not verdict.get("ran"):
        # survives=True with ran=False is a battery that never checked
        # anything -- the sample was under the battery's own floor. Promoting
        # on that would be promoting on zero falsification, which is the exact
        # hole a reviewer found in the first draft of this module.
        row["status"] = "underpowered"
        row["notes"] = ("pooled sample is under the battery's minimum; "
                        "survival would be vacuous, so this is not a candidate")
        return row

    # Provisional only -- the family correction across ALL specs decides
    # whether this survives, and that cannot happen inside a single spec.
    row["status"] = "candidate"
    row["notes"] = "battery survived; pending the family correction"
    return row


def _apply_fdr(validated, out, registered=False) -> None:
    """Benjamini-Hochberg across the FULL family, then the final verdicts.

    The denominator is len(specs), full stop. A spec that died before
    producing a pooled p enters at p = 1.0 -- it can never survive, but it
    still pays its share of the correction, because it was looked at. This is
    the one invariant the funnel exists to protect; see the module docstring.
    """
    for row in out:
        row["p_fdr"] = row["p_pooled"] if row["p_pooled"] is not None else 1.0
        row["fdr_family_size"] = len(validated)
        row["registered"] = registered
    corrected = {e["name"]: e for e in family.benjamini_hochberg(
        [{"name": r["name"], "p": r["p_fdr"]} for r in out], q=family.FDR_Q)}
    by_name = {s["name"]: s for s in validated}
    for row in out:
        entry = corrected[row["name"]]
        row["fdr_threshold"] = entry["threshold"]
        spec = by_name[row["name"]]
        # Direction was already resolved at selection construction (a
        # "negative" spec backs the other side), so every spec's confirmed
        # effect is positive by convention here.
        row["q_pass"] = bool(
            entry["survives_fdr"] and row["effect_pooled"] is not None
            and row["effect_pooled"] >= spec["effect_floor"])
        if row["status"] == "candidate" and not row["q_pass"]:
            row["status"] = "failed_fdr"
            row["notes"] = (
                f"battery survived but p {row['p_fdr']} vs BH threshold "
                f"{entry['threshold']} over the full family of "
                f"{len(validated)}, or pooled effect "
                f"{row['effect_pooled']:+.5f} under the floor "
                f"{spec['effect_floor']}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _cell(value, kind=""):
    if value is None:
        return "-"
    if kind == "effect":
        return f"{value:+.4f}"
    if kind == "p":
        return f"{value:.4g}"
    if kind == "yn":
        return "yes" if value else "no"
    if kind == "list":
        return ",".join(value) if value else "-"
    return str(value)


def format_table(rows) -> str:
    """The funnel's results as one aligned plain-text table."""
    table = [("name", "status", "lvl", "n_2023", "eff_2023", "n_pool",
              "eff_pool", "p_pool", "q_pass", "battery_fatal", "notes")]
    for row in rows:
        table.append((
            _cell(row.get("name")), _cell(row.get("status")),
            _cell(row.get("level_reached")), _cell(row.get("n_2023")),
            _cell(row.get("effect_2023"), "effect"),
            _cell(row.get("n_pooled")),
            _cell(row.get("effect_pooled"), "effect"),
            _cell(row.get("p_pooled"), "p"),
            _cell(row.get("q_pass"), "yn"),
            _cell(row.get("battery_fatal"), "list"),
            row.get("notes") or ""))
    widths = [max(len(r[i]) for r in table) for i in range(10)]
    lines = []
    for r in table:
        cells = [r[i].ljust(widths[i]) for i in range(10)] + [r[10]]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)
