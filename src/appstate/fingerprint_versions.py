"""Versioned fingerprint bookkeeping.

WHY THIS IS A NEW MODULE, NOT AN EDIT TO card_ledger.py
--------------------------------------------------------
`src/appstate/card_ledger.py` is itself one of `V1_FINGERPRINT_FILES`.
Editing it to fix its own fingerprint bug would change the V1 fingerprint
and, under registration 11.2, restart the counted sample -- the exact
false-alarm failure mode this module exists to stop being invisible (see
`docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md` E3). So
`card_ledger.code_fingerprint` stays untouched, byte for byte, and
everything new lives here: a stable, checkout-independent method (V2), an
explicit record of which known fingerprint mismatches are verified as the
same content, and a classifier that keeps "the hash changed" and "the
sporting model changed" from ever being the same sentence.

THE TWO METHODS
----------------
V1 (`FingerprintMethod.V1_RAW_BYTES`) is `card_ledger.code_fingerprint`,
called through unmodified -- raw bytes, checkout-dependent, preserved
exactly because rows already published carry values computed this way.

V2 (`FingerprintMethod.V2_LF_NORMALIZED`) hashes the same file list with
the same path-binding framing, but collapses CRLF to LF first. The same
committed content then hashes the same on Windows and on Linux CI. Erratum
E3 names this as the fix; it is not applied to `code_fingerprint` itself
(that would be a V1_FINGERPRINT_FILES edit, the owner's call under 11.2),
so it lives here as a second, explicitly-versioned method instead.

A `VersionedFingerprint` always carries its `method` alongside its `value`,
so two stored fingerprints can never be compared without that mismatch
being visible -- see `classify_code_identity`, whose first check is exactly
this.

WHAT A FINGERPRINT CANNOT TELL YOU
------------------------------------
File hashes speak to file identity: did the bytes of a registered file
change. They say nothing about selection behaviour -- which candidates got
enumerated, which odds a pick was priced against, whether the model's
output changed. Those depend on runtime inputs (live odds, lineups) that no
fingerprinted file captures, so a fingerprint match does not prove
selection behaviour was unchanged, and a fingerprint mismatch does not
prove it changed either. `classify_selection_behavior` always answers
"cannot determine from fingerprints" for exactly this reason -- see its
docstring for why that is a feature, not a missing case.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence, Tuple

from src.appstate import card_ledger

# The two runtime artifacts registration 11.2 and section 10 already list
# alongside source files. Their bytes are a frozen PARAMETER/CALIBRATION
# state, not code -- worth identifying on their own so a caller can tell
# "the params file changed" apart from "some other registered file changed"
# without re-deriving it from the combined hash.
ARTIFACT_PATHS: Tuple[str, ...] = (
    "data/processed/card_v2_frozen_params.json",
    "data/processed/card_calibration.json",
)


class FingerprintMethod(str, Enum):
    """String-valued so a stored record (e.g. round-tripped through JSON)
    keeps a human-readable method tag instead of an opaque integer."""

    V1_RAW_BYTES = "v1_raw_bytes"
    V2_LF_NORMALIZED = "v2_lf_normalized"


def _normalize(data: bytes, method: FingerprintMethod) -> bytes:
    """The only difference between the two methods: V2 collapses CRLF to
    LF before anything is hashed. `\\r\\n` -> `\\n` is safe in one
    direction only (LF is never re-expanded), which is why this is not
    reversible and not meant to be -- it normalises TOWARD a canonical
    form, it does not model "what would this look like as CRLF"."""
    if method is FingerprintMethod.V2_LF_NORMALIZED:
        return data.replace(b"\r\n", b"\n")
    return data


def _file_identity(path: str, *, method: FingerprintMethod, root: Path) -> str:
    """sha256 of ONE file's bytes alone (normalised per `method`), with no
    path-name binding and no other file's bytes mixed in. This is the
    per-artifact identity in `VersionedFingerprint.artifacts` -- distinct in
    shape and in value from the combined multi-file `value`, so the two can
    never be confused for each other even by accident.
    """
    hasher = hashlib.sha256()
    try:
        data = (root / path).read_bytes()
    except OSError:
        hasher.update(b"<absent>")
    else:
        hasher.update(_normalize(data, method))
    return hasher.hexdigest()


def _combined_hash(paths: Sequence[str], *, method: FingerprintMethod,
                    root: Path) -> str:
    """`card_ledger.code_fingerprint`'s exact framing (path name + NUL +
    bytes + NUL, per path, in order) with the bytes normalised first. Kept
    as a private helper here -- V1 never calls this; it calls
    `card_ledger.code_fingerprint` directly so it cannot drift from what
    `publish_v2`/`publish_v1_shadow` actually stamp onto rows.
    """
    hasher = hashlib.sha256()
    for rel in paths:
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        try:
            data = (root / rel).read_bytes()
        except OSError:
            hasher.update(b"<absent>")
        else:
            hasher.update(_normalize(data, method))
        hasher.update(b"\0")
    return hasher.hexdigest()


@dataclass(frozen=True)
class ArtifactIdentity:
    """The identity of one runtime artifact (a frozen-params or calibration
    JSON file), computed alongside a `VersionedFingerprint` but never
    folded into it silently."""

    path: str
    method: FingerprintMethod
    value: str


@dataclass(frozen=True)
class VersionedFingerprint:
    """A fingerprint value that always knows how it was computed.

    `paths` is recorded too (not just `value`) so a classifier or a future
    reader can tell which registered list this came from without guessing
    from the hash alone.
    """

    value: str
    method: FingerprintMethod
    paths: Tuple[str, ...]
    artifacts: Tuple[ArtifactIdentity, ...] = ()

    def comparable_to(self, other: "VersionedFingerprint") -> bool:
        """Two fingerprints are only meaningfully comparable when they were
        computed with the same method -- a V1-vs-V2 comparison is a method
        change, not a content change, no matter what the two values are."""
        return self.method == other.method


def compute_fingerprint(
    paths: Sequence[str] = card_ledger.V2_FINGERPRINT_FILES,
    *, method: FingerprintMethod = FingerprintMethod.V1_RAW_BYTES,
    root: Optional[str] = None,
) -> VersionedFingerprint:
    """Compute a `VersionedFingerprint` over `paths` using `method`.

    V1 delegates to `card_ledger.code_fingerprint` unmodified, so it is
    guaranteed byte-for-byte identical to what publication actually stamps
    -- not a reimplementation that could quietly diverge from it.
    """
    base = Path(root) if root is not None else Path.cwd()
    if method is FingerprintMethod.V1_RAW_BYTES:
        value = card_ledger.code_fingerprint(paths, root=root)
    elif method is FingerprintMethod.V2_LF_NORMALIZED:
        value = _combined_hash(paths, method=method, root=base)
    else:  # pragma: no cover - FingerprintMethod is a closed enum
        raise ValueError(f"unknown fingerprint method: {method!r}")

    artifacts = tuple(
        ArtifactIdentity(
            path=path, method=method,
            value=_file_identity(path, method=method, root=base))
        for path in paths if path in ARTIFACT_PATHS
    )
    return VersionedFingerprint(value=value, method=method,
                                paths=tuple(paths), artifacts=artifacts)


def compute_v1(
    paths: Sequence[str] = card_ledger.V2_FINGERPRINT_FILES,
    *, root: Optional[str] = None,
) -> VersionedFingerprint:
    """The existing raw-bytes method, preserved and callable on its own."""
    return compute_fingerprint(paths, method=FingerprintMethod.V1_RAW_BYTES,
                                root=root)


def compute_v2(
    paths: Sequence[str] = card_ledger.V2_FINGERPRINT_FILES,
    *, root: Optional[str] = None,
) -> VersionedFingerprint:
    """The checkout-stable method: same framing, CRLF collapsed to LF."""
    return compute_fingerprint(paths, method=FingerprintMethod.V2_LF_NORMALIZED,
                                root=root)


def artifact_identity(
    path: str, *, method: FingerprintMethod = FingerprintMethod.V1_RAW_BYTES,
    root: Optional[str] = None,
) -> ArtifactIdentity:
    """Identity of a single runtime artifact, independent of any file list."""
    base = Path(root) if root is not None else Path.cwd()
    return ArtifactIdentity(path=path, method=method,
                             value=_file_identity(path, method=method,
                                                   root=base))


# ---------------------------------------------------------------------------
# The representation-only mapping. Data, not inference: every entry names
# the evidence that established the equivalence, per the task's own rule
# that this can never be asserted by fiat.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepresentationEquivalence:
    """A verified claim that two METHOD-V1 fingerprint VALUES over the same
    file list denote identical source content, despite differing bytes on
    disk (a line-ending-only difference between checkouts).
    """

    list_name: str
    method: FingerprintMethod
    values: Tuple[str, str]
    evidence: str


# docs/PREREG_CARD_V2.md section 16 records `8a641de0...` (method V1) as
# `code_fingerprint` for V2_FINGERPRINT_FILES "at this commit" (859176ba).
# This checkout's live V1 value is `0a5d8ad7...` instead -- three of the
# seven files (best_bets_card.py, card_v2.py, card_v2_frozen_params.json)
# sit as LF here rather than CRLF. The two values are recorded as the same
# content, not asserted: `git diff 859176ba HEAD` over the seven paths is
# empty (verified 2026-09-22), and
# `python scripts/fingerprint_diagnostic.py` independently reproduces the
# section-16 value under its `all_crlf` conversion and the live value under
# `as_checked_out` from that same committed content. See erratum E3.
REPRESENTATION_ONLY_EQUIVALENCES: Tuple[RepresentationEquivalence, ...] = (
    RepresentationEquivalence(
        list_name="V2_FINGERPRINT_FILES (code_fingerprint, registration 11.2)",
        method=FingerprintMethod.V1_RAW_BYTES,
        values=(
            "8a641de0ee76091972d482cc316b47924a474e063334d67056333513ee4d2061",
            "0a5d8ad7c671c04fadabf904280a9a21ec0b454eb3b59c779d8bea60d158988a",
        ),
        evidence=(
            "git diff 859176ba HEAD is empty over the seven "
            "V2_FINGERPRINT_FILES paths (verified 2026-09-22); "
            "scripts/fingerprint_diagnostic.py reproduces "
            "8a641de0...2061 under its all_crlf conversion and "
            "0a5d8ad7...988a under as_checked_out, both from the "
            "SAME committed content. See "
            "docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md E3."
        ),
    ),
)


@dataclass(frozen=True)
class KnownDiscrepancy:
    """A recorded, investigated fingerprint mismatch that is explicitly NOT
    a representation-only difference. Exists so "we have a mapping entry
    for this value" can never be misread as "safe to treat as the same
    content" -- some entries are recorded specifically to rule that out.
    """

    list_name: str
    method: FingerprintMethod
    recorded_value: str
    reason: str


# docs/PREREG_CARD_V2.md section 10 records `10f5cac7...` (method V1) as
# `v1_code_fingerprint` "at this commit" (859176ba). Erratum E4: that value
# does not reproduce from 859176ba's content under EITHER line-ending
# convention. It reproduces (CRLF) only when src/report/card.py and
# src/appstate/card_ledger.py are taken from 859176ba~1 -- the pre-commit
# revision of the two V1_FINGERPRINT_FILES members the registration commit
# itself edited. That is a real content difference between two revisions,
# not a checkout artifact, and must never be mapped as representation-only.
KNOWN_NON_REPRESENTATION_DISCREPANCIES: Tuple[KnownDiscrepancy, ...] = (
    KnownDiscrepancy(
        list_name="V1_FINGERPRINT_FILES (v1_code_fingerprint, section 10)",
        method=FingerprintMethod.V1_RAW_BYTES,
        recorded_value=(
            "10f5cac7191ff23d0afcebc1f3566c8e747b9e4286a1eacbbfd8be09bf1c92ee"),
        reason=(
            "Does not reproduce from 859176ba's content under any "
            "line-ending convention. Reproduces (CRLF) only when "
            "src/report/card.py and src/appstate/card_ledger.py are taken "
            "from 859176ba~1 -- the pre-commit revision of the two "
            "V1_FINGERPRINT_FILES members that commit itself modified. "
            "This pins a PRE-COMMIT state, a real two-file content "
            "difference, not a line-ending artifact. See "
            "docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md E4."
        ),
    ),
)


def _find_equivalence(
    value_a: str, value_b: str, *, method: FingerprintMethod,
) -> Optional[RepresentationEquivalence]:
    for entry in REPRESENTATION_ONLY_EQUIVALENCES:
        if entry.method == method and {value_a, value_b} == set(entry.values):
            return entry
    return None


def _find_known_discrepancy(
    value: str, *, method: FingerprintMethod,
) -> Optional[KnownDiscrepancy]:
    for entry in KNOWN_NON_REPRESENTATION_DISCREPANCIES:
        if entry.method == method and entry.recorded_value == value:
            return entry
    return None


# ---------------------------------------------------------------------------
# The four-way classifier.
# ---------------------------------------------------------------------------


class ChangeCategory(str, Enum):
    """The four categories the owner named. Category 4 is intentionally
    unreachable from `classify_code_identity` -- see that function and
    `classify_selection_behavior`."""

    METHOD_CHANGE = "fingerprint_method_change"
    REPRESENTATION_ONLY = "verified_representation_only_difference"
    REAL_CHANGE = "real_source_or_configuration_change"
    CANNOT_DETERMINE = "cannot_determine_from_fingerprints"


@dataclass(frozen=True)
class Classification:
    category: ChangeCategory
    detail: str


def classify_code_identity(
    old: VersionedFingerprint, new: VersionedFingerprint,
) -> Classification:
    """Classify a difference between two fingerprint records into whichever
    of the first three categories a file hash CAN speak to.

    This function can never return `ChangeCategory.CANNOT_DETERMINE`
    (selection behaviour / model inputs) -- that is `REAL_CHANGE`'s job to
    NOT claim. A file's bytes changing is visible here; whether that change
    altered which bets get picked is not, and folding that inference into
    this function's result is the exact conflation
    `docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md` warns against: "do
    NOT let a checksum-format change imply the sporting model changed."
    Ask `classify_selection_behavior` for that question instead -- it can
    only ever answer "cannot determine".
    """
    if old.method != new.method:
        return Classification(
            ChangeCategory.METHOD_CHANGE,
            detail=(
                f"old fingerprint used {old.method.value}, new used "
                f"{new.method.value}; values are not comparable across "
                "methods regardless of what they are"),
        )

    if old.value == new.value:
        return Classification(
            ChangeCategory.REPRESENTATION_ONLY,
            detail="fingerprints are byte-for-byte identical under the "
                   "same method; there is no difference to classify",
        )

    equivalence = _find_equivalence(old.value, new.value, method=old.method)
    if equivalence is not None:
        return Classification(ChangeCategory.REPRESENTATION_ONLY,
                               detail=equivalence.evidence)

    discrepancy = (_find_known_discrepancy(old.value, method=old.method)
                   or _find_known_discrepancy(new.value, method=old.method))
    if discrepancy is not None:
        return Classification(ChangeCategory.REAL_CHANGE,
                               detail=discrepancy.reason)

    return Classification(
        ChangeCategory.REAL_CHANGE,
        detail=(
            "fingerprint values differ under the same method and are not "
            "in the verified representation-only mapping "
            "(REPRESENTATION_ONLY_EQUIVALENCES); treat as a real source or "
            "configuration change until evidence (e.g. `git diff`) proves "
            "otherwise -- do not add a new mapping entry by fiat"),
    )


def classify_selection_behavior(
    old: Optional[VersionedFingerprint] = None,
    new: Optional[VersionedFingerprint] = None,
) -> Classification:
    """Category 4. Always returns `CANNOT_DETERMINE`.

    Selection behaviour (which candidates get enumerated, which odds a pick
    is priced against) and model inputs are not part of any fingerprinted
    file's bytes -- they depend on runtime data (live odds, lineups,
    schedules) that no file hash captures. A fingerprint match therefore
    does not prove selection behaviour was unchanged, and a mismatch does
    not prove it changed. This function accepts the same two-record shape
    as `classify_code_identity` for API symmetry, but ignores their values
    on purpose: there is no fingerprint comparison that could ever change
    this answer. Determining whether selection behaviour actually changed
    needs different evidence entirely -- e.g. a replay/backtest diff over
    the candidate enumeration, not a hash comparison.
    """
    return Classification(
        ChangeCategory.CANNOT_DETERMINE,
        detail=(
            "selection behaviour and model inputs are not observable from "
            "file fingerprints under any method; a fingerprint match or "
            "mismatch is not evidence either way. Do not infer a model "
            "change from a code_fingerprint change (or vice versa) -- that "
            "conflation is exactly what "
            "docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md warns "
            "against."),
    )


def classify_change(
    old: VersionedFingerprint, new: VersionedFingerprint,
    *, aspect: str = "code_identity",
) -> Classification:
    """Single entry point over both axes.

    `aspect="code_identity"` (default) answers "did a registered file's
    bytes change, and if so is it a verified representation-only
    difference": `classify_code_identity`.

    `aspect="selection_behavior"` answers "did the model's selection
    behaviour or inputs change": always `CANNOT_DETERMINE`, via
    `classify_selection_behavior`. Routing both questions through one
    function -- rather than letting a caller reuse a code-identity result
    for a selection-behaviour question -- is what keeps the two answers
    from being silently swapped.
    """
    if aspect == "code_identity":
        return classify_code_identity(old, new)
    if aspect == "selection_behavior":
        return classify_selection_behavior(old, new)
    raise ValueError(f"unknown aspect: {aspect!r}")
