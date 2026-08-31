"""Placebo-world generators -- Evolution Lab design section 7.

NOTHING THIS MODULE PRODUCES IS EVIDENCE. A placebo world is a fiction built
for one purpose: to measure how much apparent edge our own search process
manufactures from data known to contain none. A fitness computed on a placebo
world is a statement about the search, never about baseball and never about a
bet. Placebo output may not be promoted, scored, or written outside
`data/research/evolab/`.

WHAT A PLACEBO WORLD IS
-----------------------
A generator takes a real dataset and a seed and returns a null world: the same
games, the same calendar, the same prices, with ONE claimed relationship
broken. Everything the search can exploit to overfit -- slate sizes, price
dispersion, date and team clustering, feature autocorrelation -- has to
survive the surgery, because the ceiling we report is the maximum our search
reaches in worlds that still afford it every one of those handles.

THE DESIGN HAZARD, STATED ONCE AND GUARDED IN EVERY GENERATOR
-------------------------------------------------------------
**A placebo world that is EASIER than reality understates the ceiling.**
"Easier" means structurally impoverished: fewer games per day, a narrower
price band, destroyed clustering, feature vectors that no longer autocorrelate
-- anything that gives the placebo search fewer handles to manufacture
apparent edge than the real search had. The placebo maxima then come out too
low, the 95th-percentile ceiling comes out too low, and a worthless strategy
clears it and looks significant. That failure is silent: nothing crashes, the
numbers look fine, and the conclusion is wrong.

So every generator here is paired with a test asserting the structure it
claims to preserve -- exactly, where exact preservation is possible (P1 and P5
preserve every price to the bit; P3 preserves the multiset of feature vectors
to the bit) and within stated sampling error otherwise.

The mirror-image hazard is a world that is *trivially easy to find edge in*
because the surgery broke something it should not have. P1 is the honest
example and is documented at the generator: permuting outcomes also detaches
outcome from PRICE, so in a P1 world a rule that selects on any
price-correlated feature can post enormous apparent returns that are an
artifact of the generator rather than of the search. That is why P5 exists and
is weighted most: it breaks nothing about the market at all.

DETERMINISM
-----------
Same world plus same seed yields an identical world, always. Every generator
draws from `random.Random(seed)` only -- never the global RNG -- and iterates
in a stable, explicitly sorted order, so dict iteration order can never leak
into a result. Each world records its generator, seed and parameters so any
number can be reproduced from the record alone (design section 11).
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Mapping, Sequence

from src.core import odds as odds_math

# Generator ids, as in the design's section 7 table.
P1 = "P1"
P2 = "P2"
P3 = "P3"
P4 = "P4"
P5 = "P5"
REAL = "REAL"

# Default number of replicate worlds per generator (design section 7).
DEFAULT_REPLICATES = 10

# Feature-name prefixes that attribute a feature to one side of the game.
# This matches `src/research/matrix.py` ("home_starter_velocity_gap",
# "away_lineup_platoon_share", ...). A feature matching neither prefix is
# game-level (park, weather, slate) and is never moved between teams.
HOME_PREFIX = "home_"
AWAY_PREFIX = "away_"


class PlaceboError(ValueError):
    """Raised when a world cannot be built honestly."""


@dataclass(frozen=True)
class Game:
    """One game as the lab sees it: identity, calendar, market, outcome, features.

    `home_fair` is the DE-VIGGED market probability for the home side at the
    decision point -- the market's own claim, and the only thing P5 asserts is
    true. `home_fair_close` is the same quantity at the true close when it is
    known, carried so movement fitness (design section 6) can run on a placebo
    world; no generator here invents it and no generator may read it as an
    outcome.

    `day_index` is the chronological position of this game's DAY within its
    world. It exists because P4 resamples days with replacement: in a P4 world
    a date can appear twice and dates do not ascend, so `date` is provenance
    and `day_index` is chronology. Anything that groups or orders by `date`
    is wrong for P4 worlds; group and order by `day_index`.
    """

    game_id: str
    date: str                      # official Eastern date, "YYYY-MM-DD"
    season: int
    day_index: int
    home_team: str
    away_team: str
    home_price: float              # American odds on the home side
    away_price: float
    home_fair: float               # de-vigged market probability, home side
    home_won: bool | None          # None = ungraded; never guessed
    features: Mapping[str, float | None] = field(default_factory=dict)
    home_fair_close: float | None = None
    source_game_id: str | None = None   # set when this row is a copy (P4)

    @property
    def origin(self) -> str:
        """The real game this row came from (itself, unless it is a copy)."""
        return self.source_game_id or self.game_id


@dataclass(frozen=True)
class World:
    """A dataset plus the provenance needed to reproduce it exactly.

    `games` is in canonical world order (chronological by `day_index`, then by
    `game_id`). That order IS the world's chronology -- see `Game.day_index`.
    """

    world_id: str
    generator: str
    seed: int | None
    games: tuple[Game, ...]
    source_world_id: str | None = None
    params: Mapping[str, object] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def n_games(self) -> int:
        return len(self.games)

    @property
    def n_days(self) -> int:
        return len({g.day_index for g in self.games})

    def days(self) -> list[tuple[int, tuple[Game, ...]]]:
        """Games grouped by `day_index`, ascending. The world's chronology."""
        return _group_days(self.games)


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------

def make_game(
    game_id: str,
    date: str,
    season: int,
    home_team: str,
    away_team: str,
    home_price: float,
    away_price: float,
    home_won: bool | None,
    features: Mapping[str, float | None] | None = None,
    *,
    home_fair: float | None = None,
    home_fair_close: float | None = None,
    devig_method: str = "proportional",
    day_index: int = 0,
) -> Game:
    """Build a `Game`, de-vigging the two-way price when `home_fair` is absent.

    The de-vig is `src.core.odds.devig_two_way` -- the same routine the rest of
    the project scores with. A placebo world that de-vigged differently from
    the live model would be measuring a different market.
    """
    if home_fair is None:
        fair_home, _fair_away = odds_math.devig_two_way(
            home_price, away_price, method=devig_method)
        home_fair = fair_home
    if not 0.0 < home_fair < 1.0:
        raise PlaceboError(
            f"{game_id}: de-vigged home probability {home_fair!r} is not in (0, 1)")
    return Game(
        game_id=str(game_id),
        date=str(date),
        season=int(season),
        day_index=int(day_index),
        home_team=str(home_team),
        away_team=str(away_team),
        home_price=float(home_price),
        away_price=float(away_price),
        home_fair=float(home_fair),
        home_won=None if home_won is None else bool(home_won),
        features=dict(features or {}),
        home_fair_close=None if home_fair_close is None else float(home_fair_close),
    )


def real_world(games: Iterable[Game], world_id: str = "REAL") -> World:
    """Wrap real games as the source world, assigning `day_index` by date.

    Ordering is explicit: dates ascending, then `game_id` ascending inside a
    date. Nothing downstream may depend on the order the caller happened to
    supply, and no generator may depend on dict iteration order.
    """
    games = list(games)
    if not games:
        raise PlaceboError("a world needs at least one game")
    ids = [g.game_id for g in games]
    if len(set(ids)) != len(ids):
        raise PlaceboError("duplicate game_id in source world")
    dates = sorted({g.date for g in games})
    rank = {d: i for i, d in enumerate(dates)}
    ordered = tuple(
        sorted(
            (replace(g, day_index=rank[g.date], source_game_id=g.origin) for g in games),
            key=lambda g: (g.day_index, g.game_id),
        )
    )
    return World(
        world_id=world_id,
        generator=REAL,
        seed=None,
        games=ordered,
        source_world_id=None,
        params={"n_games": len(ordered), "n_days": len(dates)},
    )


def _group_days(games: Sequence[Game]) -> list[tuple[int, tuple[Game, ...]]]:
    buckets: dict[int, list[Game]] = defaultdict(list)
    for g in games:
        buckets[g.day_index].append(g)
    return [
        (d, tuple(sorted(buckets[d], key=lambda g: g.game_id)))
        for d in sorted(buckets)
    ]


def _world_id(generator: str, source_world_id: str | None, seed: int,
              params: Mapping[str, object]) -> str:
    payload = json.dumps(
        {"generator": generator, "source": source_world_id,
         "seed": seed, "params": params},
        sort_keys=True, default=str,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"{generator}-s{seed}-{digest}"


def _rebuilt(source: World, generator: str, seed: int, games: Sequence[Game],
             params: Mapping[str, object], notes: Sequence[str] = ()) -> World:
    ordered = tuple(sorted(games, key=lambda g: (g.day_index, g.game_id)))
    return World(
        world_id=_world_id(generator, source.world_id, seed, params),
        generator=generator,
        seed=seed,
        games=ordered,
        source_world_id=source.world_id,
        params=dict(params),
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------
# shared primitive: the stationary (Politis-Romano) bootstrap
# --------------------------------------------------------------------------

def stationary_bootstrap_blocks(n: int, block_length: float,
                                rng: random.Random,
                                length: int | None = None) -> list[tuple[int, int]]:
    """Politis-Romano stationary bootstrap, as (start, run_length) blocks.

    Blocks start at a uniformly drawn position, have geometric length with mean
    `block_length`, and wrap around the end of the series -- the wrap is what
    keeps the resampled series stationary, which is the property that lets us
    bootstrap a dependent series at all. The final block is truncated to land
    exactly on `length`.

    This is the shared primitive: P4 expands these blocks into game-days, and
    `spa.py` sums over them with prefix sums, so the two can never disagree
    about what "a block" means or draw differently from the same seed.
    """
    if n <= 0:
        raise PlaceboError("stationary bootstrap needs a non-empty series")
    if block_length <= 0:
        raise PlaceboError("block_length must be positive")
    want = n if length is None else int(length)
    if want <= 0:
        raise PlaceboError("bootstrap length must be positive")
    p = min(1.0, 1.0 / float(block_length))
    blocks: list[tuple[int, int]] = []
    filled = 0
    while filled < want:
        start = rng.randrange(n)
        run = 1
        while filled + run < want and rng.random() >= p:
            run += 1
        blocks.append((start, run))
        filled += run
    return blocks


def stationary_bootstrap_indices(n: int, block_length: float,
                                 rng: random.Random,
                                 length: int | None = None) -> list[int]:
    """The same draw as `stationary_bootstrap_blocks`, expanded to indices."""
    return [
        (start + i) % n
        for start, run in stationary_bootstrap_blocks(n, block_length, rng, length)
        for i in range(run)
    ]


# --------------------------------------------------------------------------
# P1 -- within-date outcome permutation
# --------------------------------------------------------------------------

def p1_outcome_permutation(world: World, seed: int, *,
                           price_band_width: float | None = None) -> World:
    """P1: permute outcomes among the games of a date.

    PRESERVES EXACTLY: the daily slate (which games, how many, on which date),
    every price, every feature vector on its own game, the number of home wins
    on each date.
    BREAKS: feature -> outcome.

    KNOWN LIMITATION, NOT A BUG -- P1 ALSO BREAKS PRICE -> OUTCOME.
    Permuting outcomes within a date hands a heavy favourite a random game's
    result, so in a P1 world the favourite wins at the date's base rate rather
    than at its price. Any rule whose selection correlates with the price can
    therefore post huge apparent returns in P1 that come from the generator,
    not from the search. Read as a ceiling, that inflates P1 and makes it
    conservative; read as a null it is simply not a null for price-sensitive
    rules. P5 is the generator that keeps the market intact, and it is the one
    to weight when the two disagree.

    `price_band_width` is the honest patch when you want it: permute within
    (date, de-vigged-probability band) instead of within date alone, which
    keeps market calibration approximately intact at the cost of smaller
    permutation groups. Off by default because section 7 specifies within-date.

    Ungraded games (`home_won is None`) are excluded from the permutation and
    stay ungraded. Their outcome is not known, so it is not permuted and never
    invented.
    """
    rng = random.Random(seed)
    out: list[Game] = []
    groups: dict[tuple, list[Game]] = defaultdict(list)
    for day_index, games in world.days():
        for g in games:
            if g.home_won is None:
                out.append(g)
                continue
            band = (int(g.home_fair / price_band_width)
                    if price_band_width else 0)
            groups[(day_index, band)].append(g)

    for key in sorted(groups):
        members = groups[key]
        outcomes = [g.home_won for g in members]
        rng.shuffle(outcomes)
        for game, outcome in zip(members, outcomes):
            out.append(replace(game, home_won=outcome))

    params = {"price_band_width": price_band_width,
              "n_permutation_groups": len(groups)}
    return _rebuilt(world, P1, seed, out, params, notes=(
        "P1 breaks price -> outcome as well as feature -> outcome; "
        "price-sensitive rules can post generator artifacts here.",
    ))


# --------------------------------------------------------------------------
# P2 -- team-identity permutation, consistent within a season
# --------------------------------------------------------------------------

def _derangement(items: Sequence[str], rng: random.Random,
                 attempts: int = 100) -> dict[str, str]:
    """A permutation with no fixed point, or the identity for a single item.

    Fixed points are teams that keep their own features, i.e. games where the
    generator broke nothing. Drawing a derangement removes that dilution; the
    rotation fallback keeps the function total for tiny team sets.
    """
    n = len(items)
    if n < 2:
        return {t: t for t in items}
    for _ in range(attempts):
        shuffled = list(items)
        rng.shuffle(shuffled)
        if all(a != b for a, b in zip(items, shuffled)):
            return dict(zip(items, shuffled))
    rotated = list(items[1:]) + [items[0]]
    return dict(zip(items, rotated))


def _side_features(features: Mapping[str, float | None], prefix: str) -> dict:
    return {k: v for k, v in features.items() if k.startswith(prefix)}


def _game_level_features(features: Mapping[str, float | None],
                         home_prefix: str, away_prefix: str) -> dict:
    return {k: v for k, v in features.items()
            if not k.startswith(home_prefix) and not k.startswith(away_prefix)}


def p2_team_permutation(world: World, seed: int, *,
                        home_prefix: str = HOME_PREFIX,
                        away_prefix: str = AWAY_PREFIX) -> World:
    """P2: permute which team's characteristics a game shows, within a season.

    PRESERVES EXACTLY: every price, every outcome, every team label, the
    calendar, and the per-team distribution of feature blocks (each team's
    blocks all still appear, in their own order, wearing another team's
    jersey). The market's calibration is therefore bit-identical to reality.
    BREAKS: feature -> team attribution, hence feature -> outcome through the
    team.

    THE HAZARD THIS IS BUILT AROUND: the price must stay attached to the team
    that actually played and to the outcome that actually happened. The
    tempting implementation -- rename the teams and let price and outcome ride
    along with the new name -- puts a favourite's price on a game the favourite
    did not play. That world is not a null at all: it contains a real,
    trivially findable mispricing (fade the "favourite" and win half the time
    at plus money), and its maxima measure that artifact instead of our search.
    It also detaches the decision price from its own close, so the
    market-relative movement fitness of section 6 collapses to noise -- which
    would push the ceiling DOWN and let a worthless strategy clear it. So the
    permutation is applied to the feature->team map only: labels, prices and
    outcomes never move.

    A team with no home (or away) games in a season lends nothing; the game
    keeps its own block for that side and the fact is recorded in `notes`.
    """
    rng = random.Random(seed)
    by_season: dict[int, list[Game]] = defaultdict(list)
    for g in world.games:
        by_season[g.season].append(g)

    out: list[Game] = []
    notes: list[str] = []
    perms: dict[int, dict[str, str]] = {}

    for season in sorted(by_season):
        games = sorted(by_season[season], key=lambda g: (g.day_index, g.game_id))
        teams = sorted({g.home_team for g in games} | {g.away_team for g in games})
        perm = _derangement(teams, rng)
        perms[season] = perm

        home_pool: dict[str, list[dict]] = defaultdict(list)
        away_pool: dict[str, list[dict]] = defaultdict(list)
        for g in games:
            home_pool[g.home_team].append(_side_features(g.features, home_prefix))
            away_pool[g.away_team].append(_side_features(g.features, away_prefix))

        home_seen: dict[str, int] = defaultdict(int)
        away_seen: dict[str, int] = defaultdict(int)
        for g in games:
            hi = home_seen[g.home_team]
            home_seen[g.home_team] += 1
            ai = away_seen[g.away_team]
            away_seen[g.away_team] += 1

            donor_home = perm[g.home_team]
            donor_away = perm[g.away_team]
            hpool = home_pool.get(donor_home) or []
            apool = away_pool.get(donor_away) or []
            if hpool:
                # Index mapping, not random draw: the i-th home game of a team
                # takes the i-th home block of its donor, so the donor's own
                # sequence -- and any autocorrelation in it -- survives.
                hblock = hpool[hi % len(hpool)]
            else:
                hblock = _side_features(g.features, home_prefix)
                notes.append(f"season {season}: {donor_home} had no home games; "
                             f"{g.game_id} kept its own home block")
            if apool:
                ablock = apool[ai % len(apool)]
            else:
                ablock = _side_features(g.features, away_prefix)
                notes.append(f"season {season}: {donor_away} had no away games; "
                             f"{g.game_id} kept its own away block")

            merged = _game_level_features(g.features, home_prefix, away_prefix)
            merged.update(hblock)
            merged.update(ablock)
            out.append(replace(g, features=merged))

    params = {
        "home_prefix": home_prefix,
        "away_prefix": away_prefix,
        "permutations": {str(s): perms[s] for s in sorted(perms)},
    }
    return _rebuilt(world, P2, seed, out, params, notes=tuple(notes[:20]))


# --------------------------------------------------------------------------
# P3 -- signal date-shift
# --------------------------------------------------------------------------

def p3_date_shift(world: World, seed: int, *, k_days: int | None = None,
                  min_shift_days: int = 7, max_shift_days: int = 60) -> World:
    """P3: advance every feature vector by ~k game-days, cyclically within season.

    PRESERVES EXACTLY: the multiset of feature vectors in each season (a cyclic
    rotation drops nothing and duplicates nothing), every price, every outcome,
    the calendar and the slate. Feature autocorrelation survives because the
    sequence is rotated, not reshuffled.
    BREAKS: feature <-> game alignment.

    The shift is measured in GAME-DAYS, not calendar days, so off-days and the
    All-Star break cannot silently turn a 10-day shift into a 3-game shift. The
    rotation is cyclic within a season: shifting off the front of the season
    would either drop games (shrinking the slate, an "easier" world) or reach
    into another season (mixing eras). The cost is exactly one discontinuity
    per season at the wrap seam, which is recorded and is the smallest
    achievable defect.

    A shift of 0 would return the real world dressed as a placebo; it is
    forced to at least one game-day.
    """
    rng = random.Random(seed)
    by_season: dict[int, list[Game]] = defaultdict(list)
    for g in world.games:
        by_season[g.season].append(g)

    out: list[Game] = []
    shifts: dict[int, int] = {}
    notes: list[str] = []

    for season in sorted(by_season):
        games = sorted(by_season[season], key=lambda g: (g.day_index, g.game_id))
        day_list = sorted({g.day_index for g in games})
        n_days = len(day_list)
        n = len(games)
        if n_days < 2:
            notes.append(f"season {season}: only {n_days} game-day; not shifted")
            shifts[season] = 0
            out.extend(games)
            continue

        if k_days is None:
            hi = min(max_shift_days, n_days - 1)
            lo = min(min_shift_days, hi)
            k = rng.randint(lo, hi) if hi >= lo else 1
        else:
            k = int(k_days)
        k %= n_days
        if k == 0:
            k = 1
        shifts[season] = k

        cut_day = day_list[k]
        offset = sum(1 for g in games if g.day_index < cut_day)
        if offset % n == 0:
            offset = 1
        for i, g in enumerate(games):
            donor = games[(i + offset) % n]
            out.append(replace(g, features=dict(donor.features)))

    params = {"k_days": k_days, "min_shift_days": min_shift_days,
              "max_shift_days": max_shift_days,
              "shift_by_season": {str(s): shifts[s] for s in sorted(shifts)}}
    return _rebuilt(world, P3, seed, out, params, notes=tuple(notes[:20]))


# --------------------------------------------------------------------------
# P4 -- stationary block bootstrap over game-days
# --------------------------------------------------------------------------

def p4_block_bootstrap(world: World, seed: int, *,
                       block_days: float = 7.0) -> World:
    """P4: resample whole game-days with a stationary block bootstrap.

    PRESERVES: temporal dependence and streaks inside a block, and every day's
    internal structure exactly -- a resampled day is a bit-for-bit copy of a
    real day, with its features, prices and outcomes still attached to each
    other. The number of game-days is preserved exactly.
    BREAKS: long-range structure across blocks.

    Whole days move together on purpose. Resampling GAMES would shatter the
    daily slate, break the date clustering our uncertainty is computed on, and
    give the placebo search a cleaner, more independent world than reality --
    the "easier world" failure this module is built to avoid.

    A day can be drawn more than once. Copies get a unique `game_id`
    (`origin@position`) while `source_game_id` and `date` keep the provenance,
    and `day_index` -- not `date` -- carries the new chronology. Total game
    count can differ slightly from the real world because slates differ in
    size; that is recorded in `params`.
    """
    rng = random.Random(seed)
    days = world.days()
    n_days = len(days)
    picks = stationary_bootstrap_indices(n_days, block_days, rng)

    out: list[Game] = []
    for position, pick in enumerate(picks):
        _source_day, games = days[pick]
        for g in games:
            out.append(replace(
                g,
                game_id=f"{g.origin}@{position}",
                source_game_id=g.origin,
                day_index=position,
            ))

    params = {"block_days": block_days, "n_days": n_days,
              "n_games": len(out), "n_games_source": world.n_games,
              "distinct_days_drawn": len(set(picks))}
    return _rebuilt(world, P4, seed, out, params)


# --------------------------------------------------------------------------
# P5 -- market-truth resampling (the sharpest null)
# --------------------------------------------------------------------------

def p5_market_truth(world: World, seed: int, *,
                    resample_ungraded: bool = False) -> World:
    """P5: redraw each outcome from the de-vigged market probability.

    PRESERVES EXACTLY: every price, every de-vigged probability, every feature
    vector, every team label, the calendar and the slate -- the entire world
    except which side won.
    ASSERTS EXACTLY ONE THING: the market's implied probability is correct.

    This is the sharpest null in the set and the one to weight most. It is the
    only generator that leaves the market intact, so it has no artifact of the
    P1 kind: a P5 world is exactly a world in which the market is perfectly
    calibrated and nothing else has changed. Apparent edge found there is
    definitionally a search artifact, and the expected outcome ROI of ANY
    strategy in a P5 world is exactly minus the vig it pays -- there is no
    selection of games, however clever, that changes that.

    Ungraded games stay ungraded unless `resample_ungraded` is set, so a P5
    world does not quietly acquire outcomes the real world never had (which
    would enlarge the sample and make the world easier than reality).
    """
    rng = random.Random(seed)
    out: list[Game] = []
    drawn = 0
    for g in world.games:      # world order is canonical and stable
        if g.home_won is None and not resample_ungraded:
            out.append(g)
            continue
        drawn += 1
        out.append(replace(g, home_won=rng.random() < g.home_fair))
    params = {"resample_ungraded": resample_ungraded, "n_outcomes_drawn": drawn}
    return _rebuilt(world, P5, seed, out, params)


# --------------------------------------------------------------------------
# registry and suite
# --------------------------------------------------------------------------

GENERATORS: dict[str, Callable[..., World]] = {
    P1: p1_outcome_permutation,
    P2: p2_team_permutation,
    P3: p3_date_shift,
    P4: p4_block_bootstrap,
    P5: p5_market_truth,
}

GENERATOR_IDS: tuple[str, ...] = (P1, P2, P3, P4, P5)


def generate(generator_id: str, world: World, seed: int, **params) -> World:
    """Dispatch to a generator by id. Unknown ids raise rather than default."""
    try:
        fn = GENERATORS[generator_id]
    except KeyError:
        raise PlaceboError(
            f"unknown generator {generator_id!r}; "
            f"known: {', '.join(GENERATOR_IDS)}") from None
    return fn(world, seed, **params)


def placebo_suite(world: World, *, replicates: int = DEFAULT_REPLICATES,
                  base_seed: int = 0,
                  generator_ids: Sequence[str] = GENERATOR_IDS,
                  params: Mapping[str, Mapping[str, object]] | None = None):
    """Yield `replicates` worlds per generator (50 by default, design section 7).

    Seeds are derived deterministically from `base_seed`, the generator id and
    the replicate index, so the suite is reproducible from `base_seed` alone
    and no two generators share a seed stream.
    """
    params = params or {}
    for gid in generator_ids:
        for i in range(replicates):
            seed = _derive_seed(base_seed, gid, i)
            yield generate(gid, world, seed, **dict(params.get(gid, {})))


def _derive_seed(base_seed: int, generator_id: str, index: int) -> int:
    payload = f"{base_seed}:{generator_id}:{index}".encode("utf-8")
    return int(hashlib.sha1(payload).hexdigest()[:8], 16)


# --------------------------------------------------------------------------
# small diagnostics used by the tests and by ceiling reporting
# --------------------------------------------------------------------------

def home_win_rate(world: World) -> float | None:
    """Realised home win rate over graded games, or None if none are graded."""
    graded = [g for g in world.games if g.home_won is not None]
    if not graded:
        return None
    return sum(1 for g in graded if g.home_won) / len(graded)


def mean_home_fair(world: World) -> float | None:
    """Mean de-vigged market probability over graded games."""
    graded = [g for g in world.games if g.home_won is not None]
    if not graded:
        return None
    return sum(g.home_fair for g in graded) / len(graded)


def calibration_error(world: World) -> float | None:
    """Realised home win rate minus mean de-vigged market probability.

    This is the AGGREGATE calibration only, and it is deliberately paired with
    `price_outcome_alignment` below: P1 preserves this number exactly while
    destroying the thing it appears to measure, because permuting outcomes
    within a date leaves the day's home-win count untouched. Aggregate
    calibration is necessary and nowhere near sufficient.
    """
    rate = home_win_rate(world)
    mean_fair = mean_home_fair(world)
    if rate is None or mean_fair is None:
        return None
    return rate - mean_fair


def price_outcome_alignment(world: World) -> float | None:
    """Mean de-vigged home probability on home wins minus on home losses.

    The diagnostic that actually detects a broken market: positive means the
    market's price still tracks who won. In a real world and in P2, P3, P4 and
    P5 worlds this is materially positive, because the outcome never leaves the
    price it was quoted against. In a P1 world it collapses toward zero, which
    is the documented cost of permuting outcomes and the reason a
    price-sensitive rule can manufacture returns there.

    Returns None when either group is empty.
    """
    won = [g.home_fair for g in world.games if g.home_won is True]
    lost = [g.home_fair for g in world.games if g.home_won is False]
    if not won or not lost:
        return None
    return sum(won) / len(won) - sum(lost) / len(lost)
