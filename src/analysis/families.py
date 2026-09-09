"""Family-aware agreement: how many INDEPENDENT systems landed on a pick.

WHY THIS MODULE EXISTS
-----------------------
docs/PRODUCT_DOCTRINE.md amendment 9: *agreement is family-aware, never a raw
system count.* The measured reason is on the record and it is not subtle --
the 8,811-genome sweep collapsed to 1,062 families and the single largest
family held 4,019 members. A count of "systems that agree" over a population
like that measures how many near-copies happen to be registered, not how much
independent evidence exists. Counting them as 4,019 confirmations would be
manufacturing confidence out of duplication.

So every count this module produces answers "how many mechanically DISTINCT
sources landed here", and it reports the raw system count beside it, always,
so the discount is auditable rather than an unexplained number the reader has
to take on faith.

WHAT THIS MODULE IS NOT
------------------------
`n_families` is a count of sources, not a probability, not a confidence, not
an edge, and not a reason a bet wins. No independent model probability exists
anywhere in this project (`edge_bps` is structurally null; see
`src.ledger.records`), and nothing here creates one. Four families agreeing is
four systems reading overlapping measurements of the same game -- it says the
case does not rest on one mechanism, and that is the entire claim.

THE TWO RELATIONS, AND WHY BOTH ARE NEEDED
-------------------------------------------
Two systems are in the same family when they are near-duplicates under EITHER
relation; a family is a connected component of the union of the two.

1. BEHAVIOURAL -- decision-set Jaccard >= `overlap.FAMILY_THRESHOLD` (0.8),
   computed over FORWARD decisions only. This is the same threshold and the
   same clustering `lifecycle.admit()` already uses to refuse a candidate that
   duplicates a retired family, reused rather than restated: two numbers that
   are meant to be the same number must be the same object, or they drift.
   Forward-only, per amendment 8 -- a replayed decision is a decision about
   history, and history is exactly where a similarity measure can be made to
   say whatever the person running it wants.

2. STRUCTURAL -- IDENTICAL signal feature sets. This is the relation that
   matters early, and the reason it exists is a small-n failure mode: with a
   handful of forward game-days behind them, two genomes reading the same
   measurements can look behaviourally distinct simply because their decision
   sets have not had room to diverge OR to coincide yet. Waiting for the
   behavioural relation to notice would mean publishing an inflated agreement
   count for exactly as long as the evidence is thinnest. Structural identity
   needs no sample at all, so it is the safer prior while n is small, and it
   costs nothing later: as decision sets grow, the behavioural relation can
   only ever merge MORE, never un-merge.

   Identity, not overlap. Two genomes sharing two of three features are not
   the same strategy, and using the 0.8 threshold here as well would have
   collapsed the registered population into near-nothing on a similarity
   measure that was never justified for feature sets. Identity is the one bar
   that needs no justification beyond itself.

   Routing deliberately does NOT split a structural family. Two genomes that
   read the same measurements and disagree only about which market to express
   the answer in (full game vs first five) are not two independent readings of
   the game; they are one reading, published twice. Over-merging is the safe
   direction for a confidence discount, and under-merging is the failure
   amendment 9 exists to prevent.

WHAT COUNTS AS A FORWARD DECISION, EXACTLY
-------------------------------------------
`record_provenance` in `FORWARD_RECORD_PROVENANCES` and `verdict == "play"`.
Both halves are load-bearing:

- `src.ledger.records` states the rule for the third value plainly: a record
  with `record_provenance is None` "carries no evidence either way -- it must
  never be read as pre-commitment confirmed". Treating such a row as forward
  because it is not marked replay would be inventing provenance, so it is
  excluded and COUNTED, and the count is returned.
- A `refused_thin` / `refused_stale` verdict is a decision NOT to bet. Folding
  refusals into a decision set would make two systems that refuse the same
  thin boards look like they agree about a bet neither one took.

THE UNSTAMPED ROWS ARE NOT A LEGACY TAIL -- THEY ARE BEING WRITTEN TODAY
-------------------------------------------------------------------------
An earlier revision of this docstring said all 818 unstamped rows "predate the
field". That was false, and it hid a live defect. Measured 2026-09-08 over the
1,852 decision rows in `evidence/decisions_v2.jsonl` (`record_provenance` x
`verdict`, whole file):

    (None, 'play')                     69
    (None, 'refused_thin')            495
    (None, 'refused_stale')           254
    ('live_pre_commencement', 'play') 909
    ('replay', 'play')                125

The 818 unstamped rows are two unrelated populations:

  * 69 `play` rows -- ledger positions 0-68, written 2026-08-31 to 2026-09-03.
    These are the genuine legacy rows, and they are exactly the "69 rows
    published before this fix" that `src.ledger.records` itself names.
  * 749 refusal rows, written from the first replay through
    2026-09-08T19:40:45Z -- that is, TODAY. NOT ONE refusal row in the ledger
    carries a provenance, at any date, from any system. 447 of them were
    written on 2026-09-07 and 2026-09-08, side by side with 666 stamped rows;
    252 on 2026-09-08 alone.

Root cause, in a file this module does not own: `src.engine.slate.run_slate`
computes the provenance correctly and hands it to `src.engine.analyze.analyze`,
which passes `recorded_utc`/`record_provenance` through to `play_records` and
OMITS BOTH when it builds `refusal_records`. So every refusal is written
unstamped, and with `recorded_utc` silently defaulted to `snapshot.t` -- which
is why an unstamped refusal's `recorded_utc` equals its `decision_utc` exactly.

It changes no number this module produces: a refusal is excluded by the verdict
half regardless of provenance, and every one of the 909 forward rows is a
`live_pre_commencement` `play`. It is recorded here because
`excluded_by_reason` attributes 749 rows to "provenance unknown" when the
honest reason is "the writer never stamps a refusal", and because a reader
watching that count shrink as the legacy rows age out would be waiting for
something that is not happening. It is growing.

WHY NOT `wagers.canonical_wager_id`
------------------------------------
`src.evolab.wagers.canonical_wager_id` is this codebase's canonical wager id
and it was the first thing checked, per the reuse rule. It does not fit these
records: it keys on `game_pk` and `side`, and a live `DecisionRecord` carries
neither -- `game_pk` is null on all 1,852 rows currently in
`evidence/decisions_v2.jsonl`, and `side` is not a field on the record at all
(it is hashed into `selection_id` by `src.board.ids.selection_id`). Passing
`game_pk=None` would raise; substituting a placeholder would silently fuse
every event in the file into one wager. So this module keys on the triple the
ledger itself already carries -- see `wager_id`.

Pure and offline: no network, no clock, no store. stdlib plus `overlap`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from src.evolab import overlap
from src.ledger.records import (
    RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT,
    RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT,
)

# RE-EXPORT, NOT A SECOND DECLARATION. `overlap.FAMILY_THRESHOLD` is the one
# place 0.8 is defined and justified (design section 2, and `lifecycle.admit`
# refuses re-entry of a retired family on the same number). Bound here only so
# a reader of this module can see which threshold the behavioural relation
# runs at without opening another file; `families()` never takes a threshold
# argument, because a threshold a caller can tune per call is a threshold that
# can be tuned until a slip shows the agreement count someone wanted.
FAMILY_THRESHOLD = overlap.FAMILY_THRESHOLD

# The structural relation is IDENTITY of feature sets, expressed as a Jaccard
# of exactly 1.0 so that `overlap.cluster_families` -- the codebase's one
# clustering implementation -- does both relations rather than this module
# growing a second one. n/n is exact in IEEE 754 for every n, so `>= 1.0` here
# admits set equality and nothing else; there is no float-tolerance question
# to get wrong.
STRUCTURAL_IDENTITY_THRESHOLD = 1.0

# Which `record_provenance` values are FORWARD evidence. `replay` is excluded
# because a replayed decision is a statement about history (amendment 8), and
# `None` is excluded because it is unknown, not forward -- see the module
# docstring. Both live values qualify: `live_post_commencement` is a weaker
# PRE-COMMITMENT claim than `live_pre_commencement`, but this module is
# measuring behavioural similarity between systems, not staking a bet, and a
# system's post-commencement decision is still its own genuine forward output.
FORWARD_RECORD_PROVENANCES = frozenset({
    RECORD_PROVENANCE_LIVE_PRE_COMMENCEMENT,
    RECORD_PROVENANCE_LIVE_POST_COMMENCEMENT,
})

# The one verdict that puts a wager into a system's decision set. Named here
# rather than inlined as a string so the "a refusal is not agreement" rule is
# visible at module level. (`src.ledger.records.VERDICTS` holds the full
# vocabulary; every other member of it is some flavour of standing down.)
PLAYED_VERDICT = "play"

# Family ids are labels for a clustering, not durable identities: they are
# built from the alphabetically first member so a human reading a frozen
# decision can look the family up by a real system id instead of decoding an
# opaque hash. A content hash of the membership was rejected for that reason
# alone -- it changes just as readily when membership changes, and tells the
# reader nothing when it does. The durable record is the MEMBER LIST, which
# every returned object carries.
FAMILY_ID_PREFIX = "fam_"

# What `Agreement.record_provenances` shows for a record whose
# `record_provenance` was never stamped. Spelled out rather than left as a
# bare `None` in the tuple so a rendered report says "unset" instead of
# printing nothing at all where a provenance should be -- the same reason
# every absence in this module carries a reason string.
UNSET_PROVENANCE_LABEL = "__unset__"

# --- basis: how a given system earned its place in a family ----------------
# Recorded per system and surfaced on every agreement count, because "this
# system is its own family" means two completely different things depending on
# which of these it was: tested and distinct, or never compared at all.
BASIS_BEHAVIOURAL_AND_STRUCTURAL = "behavioural_and_structural"
BASIS_STRUCTURAL_ONLY = "structural_only"      # no forward decisions yet
BASIS_BEHAVIOURAL_ONLY = "behavioural_only"    # genome structure unavailable
BASIS_UNCLUSTERABLE = "unclusterable"          # neither relation was computable

# --- absence kinds ---------------------------------------------------------
# Every gap says WHY. A named kind plus an English reason, never a silent
# default and never a zero standing in for "unknown".
ABSENCE_NO_FORWARD_DECISIONS = "no_forward_decisions"
ABSENCE_STRUCTURE_UNAVAILABLE = "structure_unavailable"
ABSENCE_NOT_COMPARABLE = "not_comparable"
ABSENCE_FAMILY_UNTESTED = "family_untested"


class FamilyError(RuntimeError):
    """Raised when family structure or agreement cannot be computed honestly.

    This module raises rather than returning a plausible-looking number in
    every case where the honest answer is unknown. A guessed agreement count
    is worse than no agreement count: it is indistinguishable from a measured
    one once it has been frozen onto a decision.
    """


@dataclass(frozen=True)
class Absence:
    """A named gap with a reason. `subject` is the system id the gap is about,
    or `"*"` when it applies to the whole clustering."""

    subject: str
    kind: str
    reason: str

    def to_dict(self) -> dict:
        return {"subject": self.subject, "kind": self.kind,
                "reason": self.reason}


# ---------------------------------------------------------------------------
# Wager identity
# ---------------------------------------------------------------------------

# The separator between the three parts of a wager id. A colon cannot appear
# in any of the three (an event id and a selection id are hex digests; a
# market key is drawn from `src.board.ids.MARKET_CATALOGUE`), so no
# concatenation collision is reachable -- the same reasoning `selection_id`
# itself gives for its \x1f separator, at a layer where readability in a log
# line is worth more than defence against a field that could contain one.
WAGER_ID_SEPARATOR = ":"


def wager_id(event_id, market_key, selection_id) -> str:
    """The id two systems must share to be said to have made the SAME decision.

    `(event_id, market_key, selection_id)` -- the triple the decision ledger
    already keys on. `selection_id` alone is not enough: it hashes
    (sport, market, side, subject, line) and deliberately carries no event, so
    every home moneyline in the league shares one selection id and clustering
    on it would fuse the whole slate into a single wager. `market_key` is
    redundant with `selection_id`'s own hash and is kept anyway: it costs
    nothing, it makes the id readable, and it means a future change to the
    selection-id scheme cannot silently merge two markets.

    Refuses an empty or missing part rather than producing a well-formed id
    with a hole in it -- a wager id is an identity, and an identity that is
    partly blank silently equates rows that are not equal.
    """
    parts = {"event_id": event_id, "market_key": market_key,
             "selection_id": selection_id}
    for name, value in parts.items():
        if value is None or not isinstance(value, str) or not value.strip():
            raise FamilyError(
                f"cannot build a wager id: {name}={value!r} is missing or "
                "empty. A wager id with a blank part would equate decisions "
                "that are not on the same bet")
    return WAGER_ID_SEPARATOR.join(
        (event_id.strip(), market_key.strip(), selection_id.strip()))


def _field(row, name, default=None):
    """`row.name` for a record object, `row[name]` for a plain dict.

    Same accessor `src.report.engine_bridge` uses, and for the same reason:
    callers hand this module either real `DecisionRecord`s (what
    `settle_slate.load_decisions` returns) or the raw ledger dicts (what
    `HashChainLedger.read()` returns), and neither should have to be converted
    into the other just to be counted.
    """
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def is_forward_play(record) -> bool:
    """True when `record` is a FORWARD decision to actually take a wager.

    Both halves matter and neither has a safe default -- see the module
    docstring's "what counts as a forward decision, exactly".
    """
    return (_field(record, "record_provenance") in FORWARD_RECORD_PROVENANCES
            and _field(record, "verdict") == PLAYED_VERDICT)


# ---------------------------------------------------------------------------
# Forward decision sets -- the behavioural relation's input
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ForwardSelections:
    """`{system_id: frozenset(wager_id)}` plus what was left out and why.

    The mapping is exactly `overlap`'s documented input shape, so it feeds
    `cluster_families` with no adaptation. The counts beside it exist because
    "this system has no forward decisions" and "this system's rows were all
    excluded as replay" produce the identical empty set, and a reader deciding
    how much to trust a family count needs to know which one happened.
    """

    selections: Mapping[str, "frozenset[str]"]
    absences: tuple = ()
    n_rows_seen: int = 0
    n_rows_forward: int = 0
    excluded_by_reason: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "selections": {k: sorted(v) for k, v in
                           sorted(self.selections.items())},
            "absences": [a.to_dict() for a in self.absences],
            "n_rows_seen": self.n_rows_seen,
            "n_rows_forward": self.n_rows_forward,
            "excluded_by_reason": dict(sorted(self.excluded_by_reason.items())),
        }


def forward_selections(records: Iterable, systems: Optional[Sequence[str]] = None
                       ) -> ForwardSelections:
    """Build `{system_id: frozenset(wager_id)}` from decision records.

    `systems`, when given, is the roster the clustering is about (typically
    `[s.id for s in REGISTERED_SYSTEMS]`). Every id in it appears in the
    result, with an empty set and a named absence when it made no forward
    play, and so does every id the records mention on a row that was excluded.
    That is the honest shape: a registered system that has never fired is a
    real member of the population with no behavioural evidence, and dropping
    it from the mapping would quietly shrink the denominator of every
    downstream statement about the population.
    """
    sets: dict[str, set] = {}
    excluded: dict[str, int] = {}
    # Every system id the records mention AT ALL, including on rows that were
    # excluded. A system whose every row was a replay is a system with no
    # forward evidence, and it must appear in the mapping saying exactly that
    # -- dropping it would let a population shrink silently between one report
    # and the next for reasons nobody can see.
    seen_systems: set = set()
    n_seen = 0
    n_forward = 0
    for record in records or ():
        n_seen += 1
        provenance = _field(record, "record_provenance")
        verdict = _field(record, "verdict")
        mentioned = _field(record, "system_id")
        if isinstance(mentioned, str) and mentioned:
            seen_systems.add(mentioned)
        if provenance not in FORWARD_RECORD_PROVENANCES:
            key = f"record_provenance={provenance!r}"
            excluded[key] = excluded.get(key, 0) + 1
            continue
        if verdict != PLAYED_VERDICT:
            key = f"verdict={verdict!r}"
            excluded[key] = excluded.get(key, 0) + 1
            continue
        system_id = _field(record, "system_id")
        if not system_id or not isinstance(system_id, str):
            raise FamilyError(
                f"a forward decision row carries system_id={system_id!r}; a "
                "decision that does not name the system that made it cannot "
                "be attributed to a family")
        n_forward += 1
        sets.setdefault(system_id, set()).add(wager_id(
            _field(record, "event_id"),
            _field(record, "market_key"),
            _field(record, "selection_id"),
        ))

    roster = set(sets) | seen_systems
    if systems is not None:
        roster |= {s for s in systems}
    selections = {s: frozenset(sets.get(s, ())) for s in sorted(roster)}

    absences = tuple(
        Absence(subject=s, kind=ABSENCE_NO_FORWARD_DECISIONS,
                reason="no forward decision with verdict 'play' in the "
                       "records supplied, so this system's decision set is "
                       "empty and the behavioural relation cannot compare it "
                       "to anything")
        for s, wagers in selections.items() if not wagers)
    return ForwardSelections(
        selections=selections, absences=absences, n_rows_seen=n_seen,
        n_rows_forward=n_forward, excluded_by_reason=excluded)


# ---------------------------------------------------------------------------
# Structural relation -- feature sets
# ---------------------------------------------------------------------------

def feature_set(genome) -> Optional["frozenset[str]"]:
    """The signal FEATURE set of one genome, or `None` when unavailable.

    Accepts a validated `src.evolab.genome.Genome` (anything carrying
    `.signals`), an already-extracted collection of feature names, or `None`
    for a system with no genome behind it at all -- the three null controls
    and the market-derived republishers in `REGISTERED_SYSTEMS` have no
    signals to compare, and neither does a system this module has never been
    told about.

    `None` in, `None` out: "no structure" is returned as an absence, never as
    an empty set.

    NOT because two empty sets would merge. They would not: `overlap.jaccard`
    returns 0.0 for two empty sets by explicit design ("two strategies that
    never bet cannot be said to overlap OR to differ"), so under the identity
    relation two unknown structures stay separate singletons. An earlier
    revision of this docstring claimed the merge as the reason, and the claim
    was simply wrong.

    The real corruption is quieter and worse than a merge. An empty feature
    set is a POSITIVE claim -- "this system reads no features at all" -- and
    `families()` would believe it: the system would land in `structured`, its
    `basis_of` would be recorded as `structural_only` or
    `behavioural_and_structural`, no `ABSENCE_STRUCTURE_UNAVAILABLE` would be
    emitted for it, and `Agreement.families_resting_on_absence` would stop
    flagging its family. `n_families` would not move by one; the record of WHY
    it is what it is would silently become false, and a family that nobody has
    ever been able to compare to anything would be published as one that was
    compared and found distinct. Turning an absence into a measurement is the
    exact class of corruption this project's doctrine forbids.

    Refusing to guess also keeps this function's correctness its own: resting
    on `jaccard`'s empty-set convention would make it hostage to an edge-case
    choice made one module away and changeable there without a thought for
    this caller.

    A bare `str` is refused rather than iterated: `frozenset("abc")` is
    `{'a','b','c'}`, a silent and very plausible caller mistake.
    """
    if genome is None:
        return None
    signals = getattr(genome, "signals", None)
    if signals is not None:
        features = set()
        for signal in signals:
            name = getattr(signal, "feature", None)
            if name is None and isinstance(signal, Mapping):
                name = signal.get("feature")
            if not name:
                raise FamilyError(
                    f"a signal on {genome!r} names no feature; a genome whose "
                    "signals cannot be read has unknown structure, and this "
                    "module will not guess one")
            features.add(str(name))
        return frozenset(features)
    if isinstance(genome, str):
        raise FamilyError(
            f"feature_set got the bare string {genome!r}. A string is "
            "iterable, so accepting it would build a feature set of single "
            "characters. Pass a Genome, or a collection of feature names")
    if isinstance(genome, (set, frozenset, list, tuple)):
        return frozenset(str(f) for f in genome)
    raise FamilyError(
        f"cannot read a feature set from {type(genome).__name__}; pass a "
        "Genome, a collection of feature names, or None for 'structure "
        "unavailable'")


# ---------------------------------------------------------------------------
# The clustering
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FamilyClustering:
    """The family structure of one population of systems.

    `families` is the union of the two relations, as connected components,
    ordered largest-first exactly as `overlap.cluster_families` orders its own
    output (descending size, then first member id) so a report can print "the
    largest family" without a second sort. `behavioural` and `structural` are
    the two component lists that were merged, kept so a reader can see WHICH
    relation put two systems together -- an agreement discount nobody can
    explain is an unexplained number, which amendment 9 exists to abolish.

    A singleton in `behavioural` or `structural` does NOT mean "compared and
    found distinct": a system that relation could not evaluate at all appears
    there as a singleton too, because the merge below needs every system to be
    present in both partitions. `basis_of` is the field that tells those two
    cases apart, and it is why the basis is recorded per system rather than
    left to be inferred from the shape of the components.
    """

    families: tuple = ()
    family_id_of: Mapping[str, str] = field(default_factory=dict)
    basis_of: Mapping[str, str] = field(default_factory=dict)
    behavioural: tuple = ()
    structural: tuple = ()
    absences: tuple = ()

    @property
    def n_families(self) -> int:
        return len(self.families)

    @property
    def n_systems(self) -> int:
        return len(self.family_id_of)

    def members(self, family_id: str) -> tuple:
        for members in self.families:
            if _family_id(members) == family_id:
                return members
        raise FamilyError(f"no family {family_id!r} in this clustering")

    def family_id(self, system_id: str) -> str:
        """The family `system_id` belongs to, or `FamilyError`.

        Never invents a family for an unknown system. A system this clustering
        has not seen might be a near-duplicate of half the population; calling
        it a family of its own would add exactly the phantom confirmation
        amendment 9 forbids.
        """
        try:
            return self.family_id_of[system_id]
        except KeyError:
            raise FamilyError(
                f"system {system_id!r} is not in this clustering, so its "
                "family is unknown. Rebuild the clustering with this system "
                "included -- it must not be counted as a family of its own on "
                "the strength of never having been compared") from None

    def to_dict(self) -> dict:
        return {
            "n_families": self.n_families,
            "n_systems": self.n_systems,
            "families": [{"family_id": _family_id(m), "members": list(m)}
                         for m in self.families],
            "family_id_of": dict(sorted(self.family_id_of.items())),
            "basis_of": dict(sorted(self.basis_of.items())),
            "behavioural_components": [list(m) for m in self.behavioural],
            "structural_components": [list(m) for m in self.structural],
            "absences": [a.to_dict() for a in self.absences],
        }


def _family_id(members: Sequence[str]) -> str:
    if not members:
        raise FamilyError("an empty family has no id and cannot exist")
    return f"{FAMILY_ID_PREFIX}{members[0]}"


def _merge_partitions(*partitions) -> list:
    """Connected components of the UNION of several partitions.

    Deliberately not a second clustering: there is no threshold here, no
    similarity function and no pairwise comparison of anything. The inputs are
    component lists `overlap.cluster_families` already produced; all this does
    is take the transitive closure of "these two were grouped together by at
    least one relation". Union-find because the merge must be transitive --
    A behaviourally with B, B structurally with C, and A, B, C are one family
    even though A and C were never related directly.

    Output ordering matches `overlap.cluster_families`: members sorted,
    families by descending size then first member.
    """
    members = sorted({m for part in partitions for group in part for m in group})
    parent = {m: m for m in members}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for part in partitions:
        for group in part:
            if not group:
                continue
            first = group[0]
            for other in group[1:]:
                ra, rb = find(first), find(other)
                if ra != rb:
                    parent[ra] = rb

    groups: dict = {}
    for m in members:
        groups.setdefault(find(m), []).append(m)
    out = [tuple(sorted(g)) for g in groups.values()]
    out.sort(key=lambda fam: (-len(fam), fam[0]))
    return out


def families(selections: Mapping[str, "frozenset[str]"],
             genomes: Optional[Mapping[str, object]] = None) -> FamilyClustering:
    """Cluster a population into families under BOTH relations, unioned.

    `selections` is `{system_id: frozenset(wager_id)}` -- `overlap`'s own
    documented input shape, which `forward_selections()` produces from decision
    records. `genomes` is `{system_id: Genome | collection of feature names |
    None}`; `None` for a system, or omitting it, means "structure unavailable"
    and is recorded as an absence, never treated as an empty feature set.

    There is no `threshold` parameter, on purpose. The behavioural relation
    runs at `overlap.FAMILY_THRESHOLD` and the structural relation at exact
    identity, and both of those numbers are pre-registered facts about the
    method (doctrine section 1.2) rather than knobs on a call site.
    """
    if selections is None:
        raise FamilyError(
            "families() needs a {system_id: frozenset(wager_id)} mapping; "
            "None is not an empty population, it is an unanswered question")
    genomes = dict(genomes or {})
    universe = sorted(set(selections) | set(genomes))
    if not universe:
        return FamilyClustering(
            absences=(Absence(subject="*", kind=ABSENCE_NOT_COMPARABLE,
                              reason="no systems were supplied, so there is "
                                     "no population to cluster"),))

    absences: list = []

    # -- behavioural: only systems with at least one forward decision can be
    # compared. A system with an empty decision set is not "distinct from
    # everything"; it is untested, and it enters the merge below as a
    # singleton so that the structural relation is its only chance to be
    # grouped -- which is the documented fallback, stated in basis_of.
    decided = {s: frozenset(selections.get(s) or ()) for s in universe}
    comparable = {s: w for s, w in decided.items() if w}
    behavioural = [tuple(g) for g in overlap.cluster_families(comparable)]
    behavioural += [(s,) for s in universe if s not in comparable]
    behavioural.sort(key=lambda fam: (-len(fam), fam[0]))

    # -- structural: identity of feature sets, run through the SAME clustering
    # at a threshold of 1.0 (see STRUCTURAL_IDENTITY_THRESHOLD).
    structured: dict = {}
    for system_id in universe:
        features = feature_set(genomes.get(system_id))
        if features is None:
            absences.append(Absence(
                subject=system_id, kind=ABSENCE_STRUCTURE_UNAVAILABLE,
                reason="no genome (or no feature set) was supplied for this "
                       "system, so its structure is unknown and the "
                       "structural relation cannot place it. Two systems "
                       "whose structure is unknown are NOT thereby similar"))
            continue
        structured[system_id] = features
    structural = [tuple(g) for g in overlap.cluster_families(
        structured, threshold=STRUCTURAL_IDENTITY_THRESHOLD)]
    structural += [(s,) for s in universe if s not in structured]
    structural.sort(key=lambda fam: (-len(fam), fam[0]))

    merged = _merge_partitions(behavioural, structural)

    family_id_of = {}
    for members in merged:
        fid = _family_id(members)
        for member in members:
            family_id_of[member] = fid

    basis_of = {}
    for system_id in universe:
        has_decisions = system_id in comparable
        has_structure = system_id in structured
        if has_decisions and has_structure:
            basis_of[system_id] = BASIS_BEHAVIOURAL_AND_STRUCTURAL
        elif has_structure:
            basis_of[system_id] = BASIS_STRUCTURAL_ONLY
        elif has_decisions:
            basis_of[system_id] = BASIS_BEHAVIOURAL_ONLY
        else:
            basis_of[system_id] = BASIS_UNCLUSTERABLE
            absences.append(Absence(
                subject=system_id, kind=ABSENCE_NOT_COMPARABLE,
                reason="no forward decisions AND no known structure, so "
                       "neither relation could compare this system to any "
                       "other. It is a family of one by absence of evidence, "
                       "not by evidence of distinctness"))
        if basis_of[system_id] == BASIS_STRUCTURAL_ONLY:
            absences.append(Absence(
                subject=system_id, kind=ABSENCE_NO_FORWARD_DECISIONS,
                reason="no forward decisions, so the behavioural relation "
                       "could not be computed for this system; its family "
                       "rests on structural identity alone"))

    absences.sort(key=lambda a: (a.subject, a.kind))
    return FamilyClustering(
        families=tuple(merged), family_id_of=family_id_of, basis_of=basis_of,
        behavioural=tuple(behavioural), structural=tuple(structural),
        absences=tuple(absences))


# ---------------------------------------------------------------------------
# Agreement on one selection
# ---------------------------------------------------------------------------

# The bases under which a family's separation from the rest of the population
# was actually TESTED. A family whose every member failed both comparisons is
# flagged on the agreement object: it may be a genuine distinct source, or it
# may be a near-duplicate nobody has been able to check yet, and a ranking
# that cannot tell those apart should at least say so out loud.
_FULLY_TESTED_BASES = frozenset({BASIS_BEHAVIOURAL_AND_STRUCTURAL})


@dataclass(frozen=True)
class Agreement:
    """How many distinct families -- and how many raw systems -- took one bet.

    DOCTRINE (amendment 9): ranking reads `n_families`. `n_systems` is carried
    beside it on every record, always, because a discount nobody can see is an
    unexplained number, and the whole reason this project can be trusted about
    a pick is that its arithmetic is inspectable. `family_ids` and
    `families_by_id` make the discount reproducible: a reader can see WHICH
    systems were folded together and check the call.

    This is a count of sources. It is not a probability, an edge, a confidence
    or a reason the bet wins.
    """

    event_id: str
    market_key: str
    selection_id: str
    n_systems: int
    n_families: int
    family_ids: tuple = ()
    systems: tuple = ()
    families_by_id: Mapping[str, tuple] = field(default_factory=dict)
    basis_by_system: Mapping[str, str] = field(default_factory=dict)
    families_resting_on_absence: tuple = ()
    record_provenances: tuple = ()
    n_records_seen: int = 0
    n_records_not_played: int = 0
    absences: tuple = ()

    @property
    def wager_id(self) -> str:
        return wager_id(self.event_id, self.market_key, self.selection_id)

    @property
    def n_systems_discounted(self) -> int:
        """How many raw systems the family discount removed from the count.
        Reported so the size of the discount is a visible number rather than
        something a reader has to subtract for themselves."""
        return self.n_systems - self.n_families

    def to_dict(self) -> dict:
        return {
            "wager_id": self.wager_id,
            "event_id": self.event_id,
            "market_key": self.market_key,
            "selection_id": self.selection_id,
            "n_families": self.n_families,
            "n_systems": self.n_systems,
            "n_systems_discounted": self.n_systems_discounted,
            "family_ids": list(self.family_ids),
            "systems": list(self.systems),
            "families_by_id": {k: list(v) for k, v in
                               sorted(self.families_by_id.items())},
            "basis_by_system": dict(sorted(self.basis_by_system.items())),
            "families_resting_on_absence":
                list(self.families_resting_on_absence),
            "record_provenances": list(self.record_provenances),
            "n_records_seen": self.n_records_seen,
            "n_records_not_played": self.n_records_not_played,
            "absences": [a.to_dict() for a in self.absences],
        }


def agreement(records: Iterable, clustering: FamilyClustering) -> Agreement:
    """Family-aware agreement for ONE selection.

    `records` are the decision records on a single
    `(event_id, market_key, selection_id)`; mixing selections raises, because
    an agreement count that spans two bets is a count of nothing. Repeated
    decisions by the same system across the night collapse to one system: a
    system that re-decided the same wager at three capture instants agreed
    with itself, which is not agreement.

    `clustering` is required and has no default. `n_families` cannot be
    derived from these records alone -- deriving it from them would mean
    counting distinct `system_id`s, which is precisely the raw system count
    amendment 9 abolishes. A caller with no clustering has no family-aware
    number, and should say so rather than be handed one.

    Only `verdict == "play"` records count; a refusal is a decision not to
    take the bet. `record_provenance` is NOT filtered here -- it is reported
    instead, on `record_provenances` -- because this function is called both
    on tonight's fresh candidates (whose provenance the writing caller sets,
    not `analyze()`) and on frozen history, and silently zeroing tonight's
    agreement count over a field the caller has not stamped yet would be a
    worse failure than showing the reader which provenances went into it.
    Forward-only filtering belongs to `forward_selections()`, which builds the
    clustering's behavioural input.
    """
    if clustering is None:
        raise FamilyError(
            "agreement() needs the family clustering the population was "
            "measured under. Counting distinct system ids instead is the raw "
            "system count doctrine amendment 9 forbids")
    rows = list(records or ())
    if not rows:
        raise FamilyError(
            "agreement() was given no records, so there is no selection to "
            "describe. An agreement of zero on an unnamed bet is not a "
            "measurement")

    keys = set()
    systems: dict[str, None] = {}
    provenances: dict = {}
    not_played = 0
    for row in rows:
        event_id = _field(row, "event_id")
        market_key = _field(row, "market_key")
        selection_id = _field(row, "selection_id")
        # Validates all three parts; raises on a blank one rather than
        # letting a half-identified row define the selection.
        wager_id(event_id, market_key, selection_id)
        keys.add((event_id, market_key, selection_id))
        provenances[_field(row, "record_provenance")] = None
        if _field(row, "verdict") != PLAYED_VERDICT:
            not_played += 1
            continue
        system_id = _field(row, "system_id")
        if not system_id or not isinstance(system_id, str):
            raise FamilyError(
                f"a record on this selection carries system_id={system_id!r}; "
                "a decision that does not name its system cannot be counted "
                "toward agreement")
        systems[system_id] = None

    if len(keys) != 1:
        raise FamilyError(
            "agreement() describes ONE selection, but these records span "
            f"{len(keys)}: {sorted(keys)!r}. Counting agreement across "
            "different bets would report a number about no bet at all")
    event_id, market_key, selection_id = next(iter(keys))

    ordered_systems = tuple(sorted(systems))
    families_by_id: dict = {}
    basis_by_system: dict = {}
    for system_id in ordered_systems:
        fid = clustering.family_id(system_id)   # raises on an unknown system
        families_by_id.setdefault(fid, []).append(system_id)
        basis_by_system[system_id] = clustering.basis_of.get(
            system_id, BASIS_UNCLUSTERABLE)

    absences: list = []
    resting: list = []
    for fid in sorted(families_by_id):
        members = clustering.members(fid)
        if not any(clustering.basis_of.get(m) in _FULLY_TESTED_BASES
                   for m in members):
            resting.append(fid)
            absences.append(Absence(
                subject=fid, kind=ABSENCE_FAMILY_UNTESTED,
                reason="no member of this family could be compared under both "
                       "relations, so its separation from the other families "
                       "counted here is untested. It raises the family count "
                       "on the strength of missing evidence, not on measured "
                       "distinctness"))

    if not ordered_systems:
        absences.append(Absence(
            subject=wager_id(event_id, market_key, selection_id),
            kind=ABSENCE_NOT_COMPARABLE,
            reason=f"all {not_played} record(s) on this selection carried a "
                   "verdict other than 'play', so no system took this bet"))

    return Agreement(
        event_id=event_id, market_key=market_key, selection_id=selection_id,
        n_systems=len(ordered_systems), n_families=len(families_by_id),
        family_ids=tuple(sorted(families_by_id)), systems=ordered_systems,
        families_by_id={k: tuple(v) for k, v in families_by_id.items()},
        basis_by_system=basis_by_system,
        families_resting_on_absence=tuple(resting),
        record_provenances=tuple(sorted(
            p for p in provenances if isinstance(p, str))) + (
            (UNSET_PROVENANCE_LABEL,) if None in provenances else ()),
        n_records_seen=len(rows), n_records_not_played=not_played,
        absences=tuple(absences))


def agreements_by_selection(records: Iterable, clustering: FamilyClustering
                            ) -> dict:
    """`{wager_id: Agreement}` over many selections at once.

    A convenience for reports and for the live audit in
    `tests/test_analysis_families.py`; it groups by the same triple `wager_id`
    keys on and calls `agreement()` per group, so it can never disagree with
    the single-selection answer.
    """
    grouped: dict = {}
    for row in records or ():
        key = wager_id(_field(row, "event_id"), _field(row, "market_key"),
                       _field(row, "selection_id"))
        grouped.setdefault(key, []).append(row)
    return {key: agreement(rows, clustering)
            for key, rows in sorted(grouped.items())}
