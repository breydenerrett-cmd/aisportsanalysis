"""The adapter: a Phase 1 replay stream reduced to a Phase 2B sweep feed.

NOTHING IN THIS MODULE IS EVIDENCE. It reads a store whose outcomes we already
own, inside the exploratory sandbox (docs/EVOLAB_DESIGN.md sections 11 and 15).
The forward ledger is the only arbiter this project has. Price improvement here
is line-shopping value; nothing in this file is EV and nothing is edge. The
late board is NOT a close -- it is a median ~85 minutes before first pitch, and
every row carries its own gap in minutes so nobody can forget that.

WHAT THIS MODULE IS FOR
-----------------------
`replay.py` serves WorldViews at decision points and deliberately exposes no
outcome. `sweep.py` wants the opposite shape: per game, ONE already-resolved
CONSENSUS_EXECUTION row -- price, de-vigged fair at the decision instant, the
same fair at the movement endpoint, the graded outcome, and the registry's
features -- because the enumerable sweep runs 11,000-odd genomes over ~4,800
games and cannot re-resolve execution per genome (design section 5: execution
is held identical across the whole population). `sweep.py`'s own docstring
says that reduction "lives wherever the caller wires the real engine in". This
is that place, and it is the only one.

WHY THE EARLY BOARD IS THE DECISION INSTANT
-------------------------------------------
Phase 0 measured a three-snapshots-a-day store: the ladder collapses to
EARLY_BOARD and LATE_BOARD (docs/EVOLAB_PHASE0_FEASIBILITY.md, and replay.py's
own amendment). Of those two, EARLY_BOARD is the one that leaves a movement
window: a decision taken at the LATE board has no later board to move to, so
its movement fitness would be identically zero -- not a null result, an
undefined one. Taking the early board as THE decision instant makes the
movement window (early -> late) exactly the quantity design section 6 calls
primary fitness, and it is the class present for the large majority of the
served universe. Games whose early and late boards collapse to one instant
(replay's `classify_points` emits only LATE_BOARD for those, so no board is
scored twice) have no window at all and are EXCLUDED AND COUNTED here rather
than given a fabricated one.

The movement endpoint is the LATE board and it is never called a close.
`late_gap_minutes` travels on every row and the manifest reports the
distribution, because "the fair moved this much between two boards a few hours
apart" is the honest claim and "the line moved to the close" is not.

THE OUTCOME JOIN, AND WHY IT IS A SECOND PASS
---------------------------------------------
The replay engine refuses to serve outcomes by design -- `ReplayGame` and
`WorldView` raise on outcome access, and the loader copies outcome fields out
of nothing. This adapter is the ONE sanctioned place an outcome joins, and it
joins after every decision is already fixed. That is not a convention here, it
is the module's structure:

  1. `resolve_decisions()` takes a `ReplayUniverse` and NOTHING ELSE. It has no
     outcome parameter, and the results store is not opened, imported, or
     reachable from it. It returns frozen `ResolvedDecision` rows.
  2. `decisions_digest()` hashes those rows. `build_feed` computes that digest
     BEFORE the outcome store is read, and stamps it on the manifest.
  3. `join_outcomes()` attaches `home_won` to already-resolved rows and can
     change nothing else, because a `ResolvedDecision` is frozen and every
     market field of the emitted `placebo.Game` is copied from it.

`tests/test_evolab_feed.py` pins that with the flip test replay's own digest
test is modelled on: invert EVERY outcome in the results store and the
decision digest, and every non-outcome field of every game, is byte-identical.

WHAT A CONSENSUS PRICE IS AND IS NOT
------------------------------------
CONSENSUS_EXECUTION resolves a de-vigged PROBABILITY, not a price -- a
consensus is the board's opinion and no book quoted it (replay.ExecutionQuote
says so in its own docstring). But `placebo.Game` needs an American number for
the confirmation ROI column (design section 6: outcome ROI is CONFIRMATION
fitness, never the search fitness). So the row carries the MEAN DECIMAL PAYOUT
across exactly the books that entered the consensus, converted back to
American: the board's average price, vig included, no book named and no best
price picked. It is not a takeable price and no result computed from it may be
reported as one; it exists so the confirmation column is computed against the
board rather than against a de-vigged fair, which would silently hand every
strategy the whole margin back.

EXCLUSIONS ARE COUNTED, NEVER DEFAULTED
---------------------------------------
A game with no early board, no late board, a consensus thinner than the book
floor, or no graded outcome is dropped and counted by reason. The manifest
carries the whole reconciliation from replay's served universe down to the fed
one, alongside replay's own manifest, so the feed's size is always readable as
an arithmetic statement rather than a number that appeared.

DETERMINISM
-----------
Same stores, same feed, byte for byte. Nothing here reads the clock or a
global RNG; every reduction is `math.fsum` over an explicitly sorted book list
(hazard H2), games are ordered by `placebo.real_world`'s stated rule, and the
world id is content-addressed from the resolved rows.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from src.core import odds as odds_math
from src.evolab import placebo, replay, sweep
from src.evolab.registry import DEFAULT_REGISTRY

# The results store, keyed by game_pk. Read ONCE, in the second pass, by
# `read_outcomes` alone -- the only function in this module that opens it.
DEFAULT_RESULTS_PATH = Path("data/historical/mlb_results.csv")

FEED_VERSION = "phase2b.feed.1.0.0"

# The decision instant. Not configurable: see the module docstring -- a
# decision at the late board has no later board, so its movement fitness is
# undefined rather than zero, and offering a knob here would let a run quietly
# choose the class that flatters it.
DECISION_POINT_CLASS = replay.EARLY_BOARD
MOVEMENT_ENDPOINT_CLASS = replay.LATE_BOARD

# Exclusion reasons, spelled once so the counters, the manifest and the tests
# cannot drift apart.
NO_EARLY_BOARD = "no_early_board"
NO_LATE_BOARD = "no_late_board"
THIN_CONSENSUS_AT_DECISION = "thin_consensus_at_decision"
UNPRICEABLE_AT_DECISION = "unpriceable_at_decision"
OUTCOME_ABSENT = "outcome_absent"
EXCLUSION_REASONS = (NO_EARLY_BOARD, NO_LATE_BOARD, THIN_CONSENSUS_AT_DECISION,
                     UNPRICEABLE_AT_DECISION, OUTCOME_ABSENT)

# NOT an exclusion: a row whose LATE board is too thin to de-vig honestly is
# kept with `home_fair_close=None`, which is exactly the case `sweep_world`
# already handles by skipping that game for movement rather than inventing an
# endpoint (see `ReplayFeed`'s docstring). Counted so the movement sample is
# never mistaken for the row count.
NO_MOVEMENT_ENDPOINT = "kept_without_movement_endpoint"

EVIDENCE_LABEL = replay.EVIDENCE_LABEL


class FeedError(RuntimeError):
    """Raised when a feed cannot be built honestly."""


# ---------------------------------------------------------------------------
# Pass 1 -- decisions. No outcome is reachable from anything below this line
# until `join_outcomes`.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedDecision:
    """One game's resolved CONSENSUS_EXECUTION decision. NO OUTCOME.

    Frozen for the reason `ReplayGame` is frozen: a row that can be edited
    after resolution is a row whose decision cannot be attributed to the board
    it was resolved from. The outcome join builds a NEW object (a
    `placebo.Game`) from this one and copies every market field across, so
    there is no path by which reading an outcome could alter a price.

    `late_gap_minutes` is carried honestly from replay: the movement endpoint
    is a board a median ~85 minutes before first pitch, and it is not a close.
    """

    game_pk: str
    season: int
    official_date: str
    commence_time: str
    away_team: str
    home_team: str
    decision_T: str
    decision_gap_minutes: float
    decision_books: int
    late_T: str
    late_gap_minutes: float
    late_books: int
    home_fair: float
    away_fair: float
    home_price: float
    away_price: float
    home_fair_late: object          # None when the late board is too thin
    features: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """A canonically ordered plain dict -- what the digest is taken over."""
        return {
            "game_pk": self.game_pk,
            "season": self.season,
            "official_date": self.official_date,
            "commence_time": self.commence_time,
            "away_team": self.away_team,
            "home_team": self.home_team,
            "decision_T": self.decision_T,
            "decision_point_class": DECISION_POINT_CLASS,
            "decision_gap_minutes": round(self.decision_gap_minutes, 6),
            "decision_books": self.decision_books,
            "late_T": self.late_T,
            "movement_endpoint_class": MOVEMENT_ENDPOINT_CLASS,
            "late_gap_minutes": round(self.late_gap_minutes, 6),
            "late_books": self.late_books,
            # repr, not a rounded float: the digest must change when the
            # resolved probability changes in its last bit.
            "home_fair": repr(self.home_fair),
            "away_fair": repr(self.away_fair),
            "home_price": repr(self.home_price),
            "away_price": repr(self.away_price),
            "home_fair_late": (None if self.home_fair_late is None
                               else repr(self.home_fair_late)),
            "features": {k: (None if v is None else repr(v))
                         for k, v in sorted(self.features.items())},
        }


def _canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str)


def _consensus_row(view, *, min_books):
    """(books, home_fair, away_fair, home_price, away_price) or None.

    The fairs come from `replay.execution_quote` in CONSENSUS_EXECUTION mode --
    the engine's own resolver, called rather than re-implemented, so this
    adapter cannot drift from the execution semantics design section 5 fixes.
    The prices are the mean DECIMAL payout over exactly the books that entered
    that consensus (see the module docstring for what that is and is not); the
    eligible set is recomputed here with the same filter the engine applies and
    the two counts are asserted equal, so a future change to either would fail
    loudly instead of pairing a six-book fair with a nine-book price.

    `math.fsum` over a sorted book list: correctly rounded and therefore
    order-invariant, the same guarantee `execution_quote` gives (hazard H2).
    """
    home_quote = replay.execution_quote(view, replay.H2H, "home",
                                        replay.CONSENSUS_EXECUTION)
    away_quote = replay.execution_quote(view, replay.H2H, "away",
                                        replay.CONSENSUS_EXECUTION)
    if not home_quote or not away_quote:
        return None
    if home_quote.books < min_books or away_quote.books < min_books:
        return None

    quotes = view.board.get(replay.H2H) or {}
    decimals = {"home": [], "away": []}
    for book in sorted(quotes):
        away_price = quotes[book].get("away_price")
        home_price = quotes[book].get("home_price")
        if away_price is None or home_price is None:
            continue
        try:
            odds_math.devig_two_way(away_price, home_price)
            decimals["away"].append(odds_math.american_to_decimal(away_price))
            decimals["home"].append(odds_math.american_to_decimal(home_price))
        except odds_math.OddsError:
            continue
    if len(decimals["home"]) != home_quote.books:
        raise FeedError(
            f"consensus book set disagrees for game {view.game_id} at "
            f"{view.board_meta.observed_utc}: the "
            f"engine de-vigged {home_quote.books} books and the price mean "
            f"found {len(decimals['home'])}. A fair over one book set and a "
            "price over another is not one decision")

    try:
        home_price = odds_math.decimal_to_american(
            math.fsum(decimals["home"]) / len(decimals["home"]))
        away_price = odds_math.decimal_to_american(
            math.fsum(decimals["away"]) / len(decimals["away"]))
    except odds_math.OddsError:
        return None
    return (home_quote.books, home_quote.consensus_probability,
            away_quote.consensus_probability, home_price, away_price)


def _features_for(game, registry) -> dict:
    """The registry's features for one game, both sides, straight from replay.

    A projection, never a computation: `sweep._differentials_by_feature` takes
    the home-minus-away difference itself, so an adapter that differenced here
    too would be a second, unreviewed opinion about what a differential is.
    """
    out = {}
    for feature in registry.features():
        for side in ("away", "home"):
            key = f"{side}_{feature}"
            out[key] = game.features.get(key)
    return out


def resolve_decisions(universe, *, registry=DEFAULT_REGISTRY,
                      min_books=replay.MIN_BOOKS):
    """(rows, exclusions) for one replay universe. NO OUTCOME PARAMETER.

    The signature is the guarantee: this function cannot see an outcome
    because nothing hands it one and it opens no store. Every row it returns is
    final before `build_feed` reads the results file at all.

    `min_books` may only RAISE the project's consensus floor
    (`prices.MIN_BOOKS`, which `replay.execution_quote` enforces itself); a
    lower value would be a floor this module claims and the engine does not
    apply, which is worse than no parameter.
    """
    if min_books < replay.MIN_BOOKS:
        raise FeedError(
            f"min_books={min_books} is below the project's consensus floor "
            f"{replay.MIN_BOOKS}; a consensus over fewer books is that "
            "handful's opinion, and replay.execution_quote refuses it anyway")

    exclusions = {reason: 0 for reason in EXCLUSION_REASONS}
    exclusions[NO_MOVEMENT_ENDPOINT] = 0
    rows = []
    for game in universe.games:
        points = dict(replay.classify_points(game))
        early = points.get(replay.EARLY_BOARD)
        late = points.get(replay.LATE_BOARD)
        if late is None:
            exclusions[NO_LATE_BOARD] += 1
            continue
        if early is None:
            # replay emits only LATE_BOARD when the two boards are the same
            # instant. That game has no movement window, and a window of zero
            # is not a measurement of no movement.
            exclusions[NO_EARLY_BOARD] += 1
            continue

        # The instant is passed as the datetime replay itself stored, and
        # every string below is read back off the WorldView -- one spelling of
        # an instant, the engine's own, so digests compare.
        decision_view = replay.world_view(game, early.observed,
                                          point_class=replay.EARLY_BOARD)
        resolved = _consensus_row(decision_view, min_books=min_books)
        if resolved is None:
            reason = (THIN_CONSENSUS_AT_DECISION
                      if len(decision_view.board.get(replay.H2H) or {})
                      else UNPRICEABLE_AT_DECISION)
            exclusions[reason] += 1
            continue
        books, home_fair, away_fair, home_price, away_price = resolved

        late_view = replay.world_view(game, late.observed,
                                      point_class=replay.LATE_BOARD)
        late_resolved = _consensus_row(late_view, min_books=min_books)
        if late_resolved is None:
            exclusions[NO_MOVEMENT_ENDPOINT] += 1
            home_fair_late = None
        else:
            home_fair_late = late_resolved[1]

        rows.append(ResolvedDecision(
            game_pk=game.game_pk,
            season=game.season,
            official_date=game.official_date,
            commence_time=decision_view.commence_time,
            away_team=game.away_team,
            home_team=game.home_team,
            decision_T=decision_view.board_meta.observed_utc,
            decision_gap_minutes=early.gap_minutes,
            decision_books=books,
            late_T=late_view.board_meta.observed_utc,
            late_gap_minutes=late.gap_minutes,
            late_books=len(late.quotes),
            home_fair=home_fair,
            away_fair=away_fair,
            home_price=home_price,
            away_price=away_price,
            home_fair_late=home_fair_late,
            features=_features_for(game, registry),
        ))
    return tuple(rows), exclusions


def decisions_digest(rows) -> str:
    """A sha256 over every resolved decision, in served order.

    Computed BEFORE the outcome store is opened and stamped on the manifest,
    so "the outcomes could not have influenced the decisions" is a number a
    reader can recompute rather than a claim they have to take.
    """
    payload = [row.to_dict() for row in rows]
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pass 2 -- the outcome join, after every decision is fixed and hashed
# ---------------------------------------------------------------------------

def read_outcomes(path=DEFAULT_RESULTS_PATH) -> dict:
    """{game_pk: home_won} from the results store. The ONLY outcome reader here.

    Ungraded rows are absent rather than False: a game with no decided winner
    contributes nothing, and a default would contribute a lie. Nothing else is
    read from the file -- not the score, not the total, not the date -- because
    the join key is the game and the only thing this module is allowed to learn
    is who won.
    """
    target = Path(path)
    if not target.exists():
        raise FeedError(
            f"results store missing: {target}. The feed refuses to emit a "
            "world of ungraded games rather than quietly grading none of them")
    out = {}
    with target.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            won = row.get("home_won")
            if won not in ("0", "1"):
                continue
            game_pk = str(row.get("game_pk") or "").strip()
            if not game_pk:
                continue
            out[game_pk] = won == "1"
    return out


def join_outcomes(rows, outcomes):
    """(games, exclusions): resolved rows plus their graded outcome.

    Structurally incapable of changing a decision: every market field of the
    emitted `placebo.Game` is copied from the frozen `ResolvedDecision`, and
    `home_fair` is passed explicitly so `make_game` does not re-de-vig and
    quietly produce a second, differently-derived probability.

    A game with no graded outcome is dropped, not carried ungraded: the sweep's
    confirmation column would silently shrink its own sample, and the
    reconciliation the manifest owes a reader would go missing.
    """
    exclusions = {OUTCOME_ABSENT: 0}
    games = []
    for row in rows:
        home_won = outcomes.get(row.game_pk)
        if home_won is None:
            exclusions[OUTCOME_ABSENT] += 1
            continue
        games.append(placebo.make_game(
            game_id=row.game_pk,
            date=row.official_date,
            season=row.season,
            home_team=row.home_team,
            away_team=row.away_team,
            home_price=row.home_price,
            away_price=row.away_price,
            home_won=bool(home_won),
            features=dict(row.features),
            home_fair=row.home_fair,
            home_fair_close=row.home_fair_late,
        ))
    return tuple(games), exclusions


# ---------------------------------------------------------------------------
# The manifest -- the reconciliation, stated as arithmetic
# ---------------------------------------------------------------------------

def _gap_summary(values) -> dict:
    """min / median / max of a gap distribution, or an empty dict.

    Reported because a single median would let "85 minutes" stand in for a
    distribution whose tail is what an honest reader would want.
    """
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    median = (ordered[mid] if n % 2
              else (ordered[mid - 1] + ordered[mid]) / 2.0)
    return {"n": n, "min_minutes": round(ordered[0], 3),
            "median_minutes": round(median, 3),
            "max_minutes": round(ordered[-1], 3)}


@dataclass(frozen=True)
class FeedManifest:
    """Provenance for the feed, carrying replay's own manifest through.

    Two provenances would be none, so this does not restate replay's fields --
    it nests the whole `ReplayManifest` and adds only what the reduction itself
    decided: which point class became the decision, which became the movement
    endpoint, what the consensus price is, the exclusion table, and the
    decision digest taken before any outcome was read.
    """

    feed_version: str
    decision_point_class: str
    movement_endpoint_class: str
    min_books: int
    n_games_fed: int
    games_by_season: dict
    replay_universe_size: int
    exclusions: dict
    reconciliation: str
    decision_digest: str
    decision_gap_minutes: dict
    movement_endpoint_gap_minutes: dict
    n_with_movement_endpoint: int
    consensus_price_definition: str
    outcome_join: str
    replay_manifest: dict
    evidence: str

    def to_dict(self) -> dict:
        return {
            "feed_version": self.feed_version,
            "decision_point_class": self.decision_point_class,
            "movement_endpoint_class": self.movement_endpoint_class,
            "min_books": self.min_books,
            "n_games_fed": self.n_games_fed,
            "games_by_season": {str(k): v for k, v
                                in sorted(self.games_by_season.items())},
            "replay_universe_size": self.replay_universe_size,
            "exclusions": dict(sorted(self.exclusions.items())),
            "reconciliation": self.reconciliation,
            "decision_digest": self.decision_digest,
            "decision_gap_minutes": self.decision_gap_minutes,
            "movement_endpoint_gap_minutes": self.movement_endpoint_gap_minutes,
            "n_with_movement_endpoint": self.n_with_movement_endpoint,
            "consensus_price_definition": self.consensus_price_definition,
            "outcome_join": self.outcome_join,
            "replay_manifest": self.replay_manifest,
            "evidence": self.evidence,
        }

    def fingerprint(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.to_dict()).encode("utf-8")).hexdigest()


CONSENSUS_PRICE_DEFINITION = (
    "home_price/away_price are the MEAN DECIMAL PAYOUT across exactly the "
    "books that entered the de-vigged consensus at the decision instant, "
    "converted back to American. A consensus is the board's opinion, not a "
    "price any book quoted: this number is the board's average price with the "
    "vig still in it, no book is named and no best price is picked, and it is "
    "not a takeable price. It feeds the CONFIRMATION outcome-ROI column only "
    "(design section 6); the search fitness is market-relative movement "
    "between the two boards. Nothing computed from it is EV or edge.")

OUTCOME_JOIN_NOTE = (
    "Outcomes join in a second pass, after every decision is resolved and "
    "hashed (decision_digest above). resolve_decisions() takes no outcome "
    "argument and opens no results store; read_outcomes() is the only reader "
    "and runs afterward. Flipping every outcome in the store leaves the "
    "decision digest and every market field byte-identical, which "
    "tests/test_evolab_feed.py asserts.")

MOVEMENT_ENDPOINT_NOTE = (
    "The movement endpoint is the LATE_BOARD observation and is NOT a close: "
    "replay measures it at a median ~85 minutes before first pitch, and every "
    "row carries its own late_gap_minutes with the distribution summarised "
    "above. 'De-vigged consensus movement between two boards hours apart' is "
    "the claim; 'movement to the close' is not.")


def _reconciliation(universe_size, n_rows, n_games, exclusions) -> str:
    parts = ", ".join(f"{reason} {exclusions.get(reason, 0)}"
                      for reason in EXCLUSION_REASONS)
    return (
        f"replay served {universe_size} games; {n_rows} resolved a "
        f"CONSENSUS_EXECUTION decision at the {DECISION_POINT_CLASS}; "
        f"{n_games} survived the outcome join. Excluded and counted: {parts}. "
        f"Kept without a movement endpoint (late board too thin to de-vig, "
        f"home_fair_close=None, skipped by movement fitness rather than "
        f"invented): {exclusions.get(NO_MOVEMENT_ENDPOINT, 0)}. "
        + MOVEMENT_ENDPOINT_NOTE)


def build_feed(seasons=replay.REPLAY_SEASONS, *, universe=None,
               registry=DEFAULT_REGISTRY, min_books=replay.MIN_BOOKS,
               results_path=DEFAULT_RESULTS_PATH, outcomes=None,
               world_id="REAL", **loader_kwargs) -> sweep.ReplayFeed:
    """The whole adapter: a replay universe in, a `sweep.ReplayFeed` out.

    The ORDER of the statements below is the correctness property, not a
    style: decisions are resolved and hashed, and only then is the outcome
    store read. `outcomes` is injectable so tests can flip every result
    without writing a file -- which is exactly how the invariance test proves
    that flipping them changes nothing upstream.

    Sealed dates and non-replay seasons are refused by `replay.load_universe`,
    before anything is read; nothing here bypasses that.
    """
    if universe is None:
        universe = replay.load_universe(seasons, registry=registry,
                                        **loader_kwargs)
    elif loader_kwargs:
        raise FeedError("pass either a loaded universe or loader arguments, "
                        "not both")

    rows, exclusions = resolve_decisions(universe, registry=registry,
                                         min_books=min_books)
    # Hashed HERE, before a single outcome has been read.
    digest = decisions_digest(rows)

    if outcomes is None:
        outcomes = read_outcomes(results_path)
    games, join_exclusions = join_outcomes(rows, outcomes)
    if not games:
        raise FeedError(
            "no game survived the reduction; a feed with no games is not a "
            "world. See the exclusion counts: "
            f"{dict(sorted({**exclusions, **join_exclusions}.items()))}")

    exclusions = dict(exclusions)
    exclusions.update(join_exclusions)

    world = placebo.real_world(games, world_id=world_id)
    by_season = {}
    for game in games:
        by_season[game.season] = by_season.get(game.season, 0) + 1
    kept_ids = {g.game_id for g in games}
    kept_rows = [r for r in rows if r.game_pk in kept_ids]

    manifest = FeedManifest(
        feed_version=FEED_VERSION,
        decision_point_class=DECISION_POINT_CLASS,
        movement_endpoint_class=MOVEMENT_ENDPOINT_CLASS,
        min_books=min_books,
        n_games_fed=len(games),
        games_by_season=by_season,
        replay_universe_size=len(universe.games),
        exclusions=exclusions,
        reconciliation=_reconciliation(len(universe.games), len(rows),
                                       len(games), exclusions),
        decision_digest=digest,
        decision_gap_minutes=_gap_summary(
            [r.decision_gap_minutes for r in kept_rows]),
        movement_endpoint_gap_minutes=_gap_summary(
            [r.late_gap_minutes for r in kept_rows]),
        n_with_movement_endpoint=sum(1 for r in kept_rows
                                     if r.home_fair_late is not None),
        consensus_price_definition=CONSENSUS_PRICE_DEFINITION,
        outcome_join=OUTCOME_JOIN_NOTE,
        replay_manifest=universe.manifest.to_dict(),
        evidence=EVIDENCE_LABEL,
    )
    return sweep.ReplayFeed(world=world, manifest=manifest)


def replay_provider(**kwargs):
    """A zero-argument `sweep.ReplayProvider` bound to these arguments.

    `run_sweep` calls its provider exactly once; this is the wiring, kept here
    so a caller never has to write a lambda that silently rebuilds the universe
    twice.
    """
    def provider() -> sweep.ReplayFeed:
        return build_feed(**kwargs)
    return provider
