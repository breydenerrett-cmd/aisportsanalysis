"""The pre-registered hypothesis family, and the correction it requires.

WHY THIS FILE EXISTS BEFORE ANY RESULT DOES
-------------------------------------------
Eleven detectors across four markets at two threshold variants is eighty-eight
hypotheses, not eleven. Test eighty-eight things at the usual bar and four or
five come back excellent by chance alone -- and they will be the four or five
that get built into a product, because nobody remembers the eighty-three that
did not.

The only defence is to fix the count BEFORE looking. That is what this module
is: a written-down list of exactly what will be tested, frozen to a file, with
a correction that takes the size of the list as its input.

Searching for angles per game is forbidden for the same reason. It is not that
per-game search is unprincipled in itself; it is that it makes the denominator
unknowable, and an unknowable denominator makes every p-value in the project
meaningless.

WHY BENJAMINI-HOCHBERG AND NOT BONFERRONI
-----------------------------------------
Bonferroni controls the chance of ANY false positive, which is the right target
when a single false claim is catastrophic. Here it is not: this is a screening
problem where several detectors are expected to be real, and the detectors are
correlated -- a starter's FIP and his innings per start move together. Bonferroni
on eighty-eight correlated tests would reject almost everything real.

Benjamini-Hochberg controls the expected PROPORTION of discoveries that are
false, which is the quantity that actually matters when the output is a
shortlist. At q = 0.10, one in ten survivors is expected to be noise, and that
is stated rather than hidden.

EFFECT SIZE IS A SEPARATE GATE
------------------------------
Significance answers "is this distinguishable from zero", which on 7,000 games
it will be for effects far too small to bet. A detector must clear both.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.detect.base import BLOCKED
from src.paths import evidence_path

DEFAULT_REGISTRATION = evidence_path("hypothesis_family.json")

# Expected proportion of survivors that are false. Stated rather than hidden:
# at 0.10, one in ten detectors that clears this is expected to be noise.
FDR_Q = 0.10

# Below this, an effect is real and not worth acting on. In closing-line-value
# terms, one percentage point of probability is roughly the vig on a single bet.
MIN_EFFECT = 0.010


class FamilyError(RuntimeError):
    """Raised when the family is registered or read incorrectly."""


def enumerate_family(detectors) -> list:
    """Every hypothesis the family contains: detector x market.

    Threshold variants are NOT enumerated here, and that is deliberate: a
    detector whose threshold is tuned on the tuning split contributes one
    hypothesis to the confirmation family, not one per candidate threshold. The
    tuning itself happens on a separate split whose results are never reported as
    out-of-sample, which is what makes that legitimate.
    """
    out = []
    for detector in sorted(detectors.values(), key=lambda d: d.name):
        if detector.status == BLOCKED:
            continue
        for market in detector.markets or ("h2h",):
            out.append({"detector": detector.name, "market": market})
    return out


def register(detectors, path=DEFAULT_REGISTRATION, now=None, note=None) -> dict:
    """Freeze the family to disk. Refuses to silently change a registration.

    Once written, the file is the count. Adding a detector afterwards is a
    research decision that must be visible in a diff, so re-registering a
    different family raises rather than overwriting.
    """
    target = Path(path)
    family = enumerate_family(detectors)
    payload = {
        "registered_at": (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc).isoformat(),
        "hypotheses": family,
        "count": len(family),
        "fdr_q": FDR_Q,
        "min_effect": MIN_EFFECT,
        "note": note,
    }

    if target.exists():
        existing = read(path)
        if existing["hypotheses"] != family:
            added = [h for h in family if h not in existing["hypotheses"]]
            removed = [h for h in existing["hypotheses"] if h not in family]
            raise FamilyError(
                f"the family was registered on {existing['registered_at']} with "
                f"{existing['count']} hypotheses and this call has "
                f"{len(family)}. Added: {added or 'none'}. Removed: "
                f"{removed or 'none'}. Changing the family changes every "
                "correction computed from it -- re-register deliberately, with "
                "the old file deleted in the same commit.")
        return existing

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=1, sort_keys=True),
                      encoding="utf-8")
    return payload


def read(path=DEFAULT_REGISTRATION) -> dict:
    target = Path(path)
    if not target.exists():
        raise FamilyError(
            f"no hypothesis family registered at {target}. Register it before "
            "running any evaluation -- a correction computed against a count "
            "chosen afterwards is not a correction.")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FamilyError(f"{target} is not valid JSON") from exc


# ---------------------------------------------------------------------------
# Correction
# ---------------------------------------------------------------------------

def benjamini_hochberg(results, q=FDR_Q) -> list:
    """Which results survive FDR control, at the stated false-discovery rate.

    `results` is an iterable of dicts carrying `p` and anything else. Returns
    the same dicts with `survives_fdr`, `rank` and `threshold` attached, sorted
    by p ascending, so a caller can report the WHOLE family rather than only the
    winners -- publishing only survivors is how a family of eighty-eight becomes
    a claim about four.
    """
    ordered = sorted(results, key=lambda r: r["p"])
    n = len(ordered)
    if not n:
        return []

    # Find the largest rank whose p-value falls under its own threshold, then
    # accept everything up to it. Accepting each independently is the classic
    # implementation error and rejects real effects.
    cutoff_rank = 0
    for rank, result in enumerate(ordered, start=1):
        if result["p"] <= q * rank / n:
            cutoff_rank = rank

    out = []
    for rank, result in enumerate(ordered, start=1):
        entry = dict(result)
        entry["rank"] = rank
        entry["threshold"] = round(q * rank / n, 6)
        entry["survives_fdr"] = rank <= cutoff_rank
        out.append(entry)
    return out


def apply_gates(results, q=FDR_Q, min_effect=MIN_EFFECT) -> dict:
    """FDR and the effect-size floor together, with the whole family reported.

    A result must clear BOTH. On seven thousand games a trivially small effect
    is easily distinguishable from zero, and significance alone would promote it.
    """
    corrected = benjamini_hochberg(results, q=q)
    for entry in corrected:
        effect = abs(entry.get("effect") or 0.0)
        entry["clears_effect"] = effect >= min_effect
        entry["passes"] = bool(entry["survives_fdr"] and entry["clears_effect"])

    passed = [e for e in corrected if e["passes"]]
    return {
        "family_size": len(corrected),
        "q": q,
        "min_effect": min_effect,
        "passed": passed,
        "all": corrected,
        "expected_false_among_passed": round(q * len(passed), 2),
        "summary": (
            f"{len(passed)} of {len(corrected)} hypotheses cleared both gates. "
            f"At q={q}, about {q * len(passed):.1f} of those are expected to be "
            "noise." if passed else
            f"None of {len(corrected)} hypotheses cleared both gates."),
    }
