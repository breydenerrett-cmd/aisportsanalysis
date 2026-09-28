#!/usr/bin/env python3
"""A bounded evidence packet for ONE game, and a critic whose output is
machine-checked, not merely reviewed -- the first real demonstration Lane D
Part 3 asked for, corrected after Opus review failed the first sample
(`evidence/ai_analyst/REVIEW_2026-09-25_NYM-WSH.md`).

WHAT THE FIRST SAMPLE GOT WRONG, AND WHY THIS IS A REWRITE, NOT A PATCH
--------------------------------------------------------------------------
Two failures, both format-valid and both false:
  1. `case_against` called a score (0.0964) "one of the smaller" when it was
     the LARGEST of the three compared. Nothing had recomputed the ranking;
     the schema only checked that citations existed, never that the claim
     built from them was true.
  2. The central challenge named a specific pitcher (DJ Herz) drawn from an
     injury-transaction claim, while the model's own input carries no
     pitcher name at all -- an inference dressed as a finding, not a
     verified identity.

Both are the SAME defect: a critic finding is data that LOOKS checkable
(claim ids, source refs) while its actual prose asserts something nobody
recomputed. This version makes every number and every ranking a structured,
independently-recomputed fact rather than free prose citing sources next to
it. `validate_hard_limits` now raises on drift between what a finding SAYS
and what its own cited sources hold -- see `_validate_facts`,
`_validate_rankings`, `_validate_numbers_in_prose` below, and
`tests/test_ai_analyst.py`'s `FactCheckRegressionTests`, which replays the
0.0964 mistake byte for byte and requires it to be REJECTED.

WHAT THIS IS NOT
-----------------
Not a forecaster. Not a second model. Not a veto with authority over
anything published -- nothing in `src/report/`, `src/analysis/best_bets_card.py`
or `src/appstate/card_ledger.py` is imported, read, or touched by this file,
and Ranker Engine 2 stays gated exactly as every other lane leaves it. This
produces a REVIEW of one already-computed shadow recommendation. The review
is data. A human decides what to do with it.

WHY "SOURCED EVIDENCE" MEANS THE REPO'S OWN CAPTURED FEEDS, NOT A WEB SEARCH
-----------------------------------------------------------------------------
`src/providers/mlb_news.py`'s own docstring makes the argument this module
follows: a live web search made "tonight" can never be replayed against an
earlier point in time. So every claim here cites one of:

  * this repo's own captured model inputs (`models_by_game` in a shadow
    artifact -- what the model itself assumed, e.g. `away_sp_known`);
  * `src.providers.mlb_news.fetch` -- MLB's own free, dated transactions
    feed (`NewsError` on failure, never a guess);
  * `src.providers.mlb.fetch_games` -- MLB's own free schedule feed,
    including its `probablePitcher` hydration, for STARTER IDENTITY
    specifically (see STARTER IDENTITY below) -- a different, more
    authoritative source than the model's own `*_sp_known` flag, which
    only says whether THIS repo's pipeline found a starter, not who MLB's
    own schedule says is starting;
  * the market quotes already in the shadow artifact.

None of these is a paid call. No credential, no API key and no cost is
touched by anything in this file.

CLAIM SCHEMA
------------
`Claim` carries `claim_id`, `entity`, `event`, `text`, `source_ref`,
`published_at` (`None` when the source carries no publish time -- never
invented), `retrieved_at`, `status`
(`CONFIRMED`/`UNCONFIRMED`/`CONTRADICTED`/`STALE`/`UNRELATED`),
`uncertainty`, `intended_use`, `independent`, and `data` -- a FLAT dict of
the claim's own structured numbers (e.g. `{"home_sp_era": 3.6}`), keyed by
name exactly as the source stores them. `data` is what makes a `Fact` below
checkable by code instead of by re-reading prose.

STARTER IDENTITY (Part 3, requirement 3)
------------------------------------------
`starter_identity_claims` reads MLB's own schedule feed
(`mlb.fetch_games(date)`, the SAME free provider `scripts/
shadow_enumeration_run.py` already uses) and produces one `CONFIRMED` claim
per side when it lists a probable pitcher NAME and ID, and one `UNCONFIRMED`
claim when it does not. A `CriticFinding` that wants to attribute anything
to a NAMED pitcher must declare it through `pitcher_attribution`
(`{side, name, identity_claim_id}`); `validate_hard_limits` then requires
that claim to be CONFIRMED before allowing `CORRECT_INPUT` or `RECALCULATE`
-- an unconfirmed identity may only support `REQUEST_SCENARIO`.
`_validate_named_persons_are_attributed` additionally refuses any finding
that names a specific person (from a `mlb_news` claim or a probable-pitcher
claim) ANYWHERE in its free text without declaring that name through
`pitcher_attribution` -- the exact gap the first sample fell through, closed
structurally rather than by asking the critic to remember not to do it
again.

ACTION VOCABULARY (replaces the earlier VERDICTS)
----------------------------------------------------
Exactly one `action` per finding, from `ACTIONS`. Each carries its OWN typed
`action_payload` (`REQUIRED_ACTION_PAYLOAD_KEYS`), never a probability or a
gate threshold (`FORBIDDEN_FIELD_NAMES`, checked at runtime, not by
convention):

  * `CORRECT_INPUT` -- `{input_path, current_value, verified_value,
    source_claim_ids}`. Allowed only when at least one cited source claim
    is CONFIRMED, and `verified_value` (when numeric) must equal one of
    this finding's own verified `facts`.
  * `REQUEST_SCENARIO` -- `{scenario, inputs_varied, source_claim_ids}`. A
    request for the MODEL to recompute under a named scenario -- never a
    number the critic computed itself.
  * `COMPARE_MARKET` -- `{market, reason, source_claim_ids}`.
  * `RECALCULATE` -- `{reason, changed_input, source_claim_ids}`.
  * `NO_ADJUSTMENT` -- `{checked_claim_ids}`. A first-class success, not a
    fallback.

DETERMINISTIC FACT CHECK (Part 3 owner gate, item 2)
--------------------------------------------------------
`Fact(claim_id, field_path, value)`: `value` must equal
`claim.data[field_path]` for the named claim, checked by
`_validate_facts` -- not asserted, resolved. `Ranking(metric, subject_value,
compared_values, claimed_rank)`: `claimed_rank` (1 = highest) is
RECOMPUTED by `_validate_rankings` from `subject_value`/`compared_values`
and must match. `_validate_numbers_in_prose` then extracts every numeric
literal from `challenged_assumption`, `case_against`, `notes`,
`verified_assumptions`' own text, and `action_payload`'s free-text fields,
and refuses any number that is not traceable to a verified `Fact`, a
verified `Ranking` value, or the sealed `recommendation`'s own price/
probabilities. A mismatch anywhere raises `HardLimitViolation`.

HARD LIMITS (enforced by `validate_hard_limits`, not just asserted in prose)
-----------------------------------------------------------------------------
1. Invent a probability adjustment -- `FORBIDDEN_FIELD_NAMES` blocks any
   probability/threshold name from being the thing an action names as its
   `input_path`/`changed_input`/`inputs_varied` entry.
2. Alter a published record -- this module has no write access to anything
   published; `apply_critic` only ever ADDS a `finding` key beside an
   untouched `recommendation` echo.
3. Widen a threshold -- same `FORBIDDEN_FIELD_NAMES` check, gate parameter
   names included.
4. Silently replace the model's number -- `CriticFinding` carries no
   probability field at all; the one free-form numeric path
   (`CORRECT_INPUT.verified_value`) is tied back to a verified `Fact` by
   `_validate_correct_input_values_are_verified_facts`.

SESSION-ASSISTED, LABELLED AS SUCH
-----------------------------------
No standing budget for an autonomous LLM-critic API call in this lane. Every
`AnalystReport` this module produces carries `contribution_kind:
"session_assisted"` (`mark_session_assisted`, the one place that sets it) --
real analysis, explicitly NOT evidence of an unattended production agent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT_DIR = os.path.join("evidence", "ai_analyst")

# A packet this bounded is one a human reviewer can actually read in one
# sitting -- "bounded evidence packet for ONE game" in the task's own words.
# Not a tunable knob: raising it defeats the reason it exists.
MAX_CLAIMS = 25

CLAIM_STATUSES = ("CONFIRMED", "UNCONFIRMED", "CONTRADICTED", "STALE",
                  "UNRELATED")

# The owner's replacement vocabulary. ADJUSTMENT_REQUESTED /
# RECALCULATION_REQUESTED / ALTERNATE_MARKET_SUGGESTED are GONE -- do not
# resurrect them; every caller of this module must speak these five.
ACTIONS = ("CORRECT_INPUT", "REQUEST_SCENARIO", "COMPARE_MARKET",
          "RECALCULATE", "NO_ADJUSTMENT")

REQUIRED_ACTION_PAYLOAD_KEYS = {
    "CORRECT_INPUT": frozenset(
        {"input_path", "current_value", "verified_value", "source_claim_ids"}),
    "REQUEST_SCENARIO": frozenset(
        {"scenario", "inputs_varied", "source_claim_ids"}),
    "COMPARE_MARKET": frozenset({"market", "reason", "source_claim_ids"}),
    "RECALCULATE": frozenset(
        {"reason", "changed_input", "source_claim_ids"}),
    "NO_ADJUSTMENT": frozenset({"checked_claim_ids"}),
}

# Keys inside an action_payload that hold CLAIM IDS, not prose or field
# names -- excluded from both the forbidden-field-name check (an id is not
# a field name) and the numbers-in-prose scan (an id's digits are not an
# analytic claim).
_ID_LIST_KEYS = {"source_claim_ids", "checked_claim_ids", "inputs_varied"}

# action_payload keys that hold a NAME -- a market, a model-input field
# path -- rather than a sentence. Field names in this repo routinely carry
# digits with no analytic meaning (`home_sp_k9`, `home_sp_hr9`, a market
# called "f5"), so these are excluded from the numbers-in-prose scan the
# same way `_ID_LIST_KEYS` is: a name is not a claim, and a critic must not
# have to invent a `Fact` to justify a field NAME simply containing a
# digit. `reason`/`scenario` are the free-text explanation fields and are
# the only action_payload strings this scan actually checks.
_NAME_ONLY_KEYS = {"market", "input_path", "changed_input"}

# Gate/threshold and probability field names (best_bets_card.RuleParams and
# the candidate dict's own probability keys) -- duplicated here as a STRING
# check on purpose, not an import, so this module never has to import
# best_bets_card to do its job.
FORBIDDEN_FIELD_NAMES = {
    "probability", "our_probability", "p_home", "p_away",
    "market_probability", "score", "p_raw", "calibrated_probability",
    "worst_price", "best_price", "markdown", "base_edge",
    "main_market_floor", "main_our_floor", "plus_market_floor",
    "plus_our_floor", "disagreement_cap", "ceiling", "floor",
    "game_min_books", "fresh_seconds", "plus_money_subcap",
}


class HardLimitViolation(ValueError):
    """A `CriticFinding` failed a check `validate_hard_limits` runs. Raised,
    never silently corrected -- a critic output that violates this is a bug
    to fix in the critic step, not a value this module papers over."""


@dataclass(frozen=True)
class Claim:
    claim_id: str
    entity: str
    event: str
    text: str
    source_ref: str
    retrieved_at: str
    status: str
    uncertainty: str
    intended_use: str
    published_at: Optional[str] = None
    independent: bool = True
    # Flat {name: number} of this claim's own structured source data, so a
    # `Fact` can resolve `field_path` against something other than prose.
    # `None` (not `{}`) means "this claim carries no citable structured
    # number", which a `Fact` referencing it will correctly fail against.
    data: Optional[dict] = None

    def __post_init__(self):
        if self.status not in CLAIM_STATUSES:
            raise ValueError(f"unknown claim status: {self.status!r}")
        if not self.claim_id or not self.entity or not self.text:
            raise ValueError("claim_id, entity and text are required and "
                             "may never be blank")


@dataclass(frozen=True)
class ModelRecommendation:
    """A READ-ONLY echo of what the model already produced -- never built
    by this module."""
    game_id: str
    market: str
    side: str
    price: float
    our_probability: float
    market_probability: float
    source_artifact: str
    bet_sentence: str = ""


@dataclass(frozen=True)
class EvidencePacket:
    game_id: str
    date: str
    built_at: str
    recommendation: ModelRecommendation
    claims: tuple

    def __post_init__(self):
        if len(self.claims) > MAX_CLAIMS:
            raise ValueError(
                f"{len(self.claims)} claims exceeds MAX_CLAIMS={MAX_CLAIMS} "
                "-- a bounded packet for one game, not the whole slate")
        ids = [c.claim_id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate claim_id in one packet")


@dataclass(frozen=True)
class Fact:
    """One number, traced to one claim's own structured data.
    `_validate_facts` resolves `claim.data[field_path]` and requires it to
    equal `value` -- the citation is checked, not trusted."""
    claim_id: str
    field_path: str
    value: float


@dataclass(frozen=True)
class Ranking:
    """One comparison statement. `claimed_rank` (1 = highest) is RECOMPUTED
    by `_validate_rankings` from `subject_value` and `compared_values` --
    this is the structure that would have caught "one of the smaller
    scores" for what was actually the largest."""
    metric: str
    subject_value: float
    compared_values: tuple
    claimed_rank: int


@dataclass(frozen=True)
class CriticFinding:
    """The critic's checkable work product.

    `verified_assumptions`: (assumption text, verdict text, evidence
        claim_ids) triples.
    `challenged_assumption`: the model's STRONGEST assumption, named and
        argued against (task's own instruction: not the weakest).
    `case_against`: the strongest case AGAINST the recommendation --
        required even for `NO_ADJUSTMENT`, so "no adjustment" is never
        mistaken for "no case existed".
    `action` / `action_payload`: exactly one of `ACTIONS`, with the payload
        shape `REQUIRED_ACTION_PAYLOAD_KEYS[action]` demands.
    `facts` / `rankings`: the structured backing every number and every
        comparison in this finding's prose must resolve to
        (`validate_hard_limits`).
    `pitcher_attribution`: `{side, name, identity_claim_id}` or `None` --
        required before naming a specific person anywhere in this finding's
        text (see module docstring, STARTER IDENTITY).
    `contribution_kind`: `"session_assisted"` here, always --
        `mark_session_assisted` sets it so a caller cannot forget to.
    """
    game_id: str
    verified_assumptions: tuple
    challenged_assumption: str
    case_against: str
    action: str
    action_payload: dict
    facts: tuple = ()
    rankings: tuple = ()
    pitcher_attribution: Optional[dict] = None
    contribution_kind: str = "unset"
    notes: str = ""

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action: {self.action!r}")
        if not self.case_against.strip():
            raise ValueError(
                "case_against is required even for NO_ADJUSTMENT -- a "
                "refusal without a stated case is not checkable")


def mark_session_assisted(finding: CriticFinding) -> CriticFinding:
    """The ONE place `contribution_kind` is set. Uses `dataclasses.replace`
    rather than an `asdict`/kwargs round-trip -- `asdict` would recursively
    flatten the nested `Fact`/`Ranking` dataclasses inside `facts`/
    `rankings` into plain dicts, which `CriticFinding`'s constructor does
    not expect back."""
    return replace(finding, contribution_kind="session_assisted")


# ---------------------------------------------------------------------------
# Hard-limit validation. Every function below either resolves a citation
# against real data or recomputes a claim -- none of them trust the finding
# author's arithmetic.
# ---------------------------------------------------------------------------

def _numeric_equal(a, b, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _check_not_forbidden_field(name, label: str) -> None:
    if isinstance(name, str) and name in FORBIDDEN_FIELD_NAMES:
        raise HardLimitViolation(
            f"{label} names a probability/threshold field ({name!r}) -- a "
            "critic may name a MODEL INPUT to correct, vary or recompute "
            "from, never a probability or a gate threshold")


def _validate_action_payload_shape(finding: CriticFinding) -> None:
    required = REQUIRED_ACTION_PAYLOAD_KEYS[finding.action]
    payload = finding.action_payload
    if not isinstance(payload, dict):
        raise HardLimitViolation(f"{finding.action} action_payload must be "
                                 "a dict")
    if set(payload.keys()) != required:
        raise HardLimitViolation(
            f"{finding.action} action_payload must carry exactly "
            f"{sorted(required)}, got {sorted(payload.keys())}")


def _validate_no_forbidden_field_names(finding: CriticFinding) -> None:
    payload = finding.action_payload
    action = finding.action
    if action == "CORRECT_INPUT":
        _check_not_forbidden_field(payload["input_path"], "input_path")
    elif action == "RECALCULATE":
        _check_not_forbidden_field(payload["changed_input"], "changed_input")
    elif action == "REQUEST_SCENARIO":
        for name in payload["inputs_varied"]:
            _check_not_forbidden_field(name, "inputs_varied entry")


def _validate_source_claims_exist(packet: EvidencePacket,
                                  finding: CriticFinding) -> None:
    known_ids = {c.claim_id for c in packet.claims}
    id_key = ("checked_claim_ids" if finding.action == "NO_ADJUSTMENT"
             else "source_claim_ids")
    ids = finding.action_payload.get(id_key) or []
    if not ids:
        raise HardLimitViolation(
            f"{finding.action} requires at least one {id_key} entry -- a "
            "finding with no cited claim is not checkable")
    missing = [i for i in ids if i not in known_ids]
    if missing:
        raise HardLimitViolation(
            f"{id_key} cites unknown claim_id(s): {missing}")


def _validate_verified_assumptions_cite_real_claims(
        packet: EvidencePacket, finding: CriticFinding) -> None:
    known_ids = {c.claim_id for c in packet.claims}
    for i, triple in enumerate(finding.verified_assumptions):
        _assumption, _verdict, ids = triple
        missing = [x for x in ids if x not in known_ids]
        if missing:
            raise HardLimitViolation(
                f"verified_assumptions[{i}] cites unknown claim_id(s): "
                f"{missing}")


def _validate_correct_input_confirmed(packet: EvidencePacket,
                                      finding: CriticFinding) -> None:
    """CORRECT_INPUT's own hard limit: "Allowed only when the verified
    value comes from a CONFIRMED source claim." """
    if finding.action != "CORRECT_INPUT":
        return
    ids = finding.action_payload["source_claim_ids"]
    claims = {c.claim_id: c for c in packet.claims}
    if not any(claims[i].status == "CONFIRMED" for i in ids):
        raise HardLimitViolation(
            "CORRECT_INPUT requires at least one source_claim_ids entry "
            "whose claim status is CONFIRMED -- a correction may not rest "
            "solely on an unconfirmed or contradicted claim")


def _validate_correct_input_values_are_verified_facts(
        finding: CriticFinding) -> None:
    """HARD LIMIT 4 closes here for the one free-form numeric field this
    schema allows: `verified_value` must equal one of this finding's OWN
    `facts` -- never a number introduced only in the payload, unchecked.
    Scoped to `verified_value` alone, matching the owner's own wording
    ("Allowed only when the VERIFIED VALUE comes from a CONFIRMED source
    claim") -- `current_value` is the model's pre-existing number, already
    on record wherever the model itself stores it, not a new number this
    finding is asserting."""
    if finding.action != "CORRECT_INPUT":
        return
    value = finding.action_payload["verified_value"]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return
    fact_values = [f.value for f in finding.facts]
    if not any(_numeric_equal(value, fv) for fv in fact_values):
        raise HardLimitViolation(
            f"CORRECT_INPUT.verified_value={value!r} does not match any of "
            "this finding's own verified `facts` -- a correction cannot "
            "introduce a number that was never checked against its "
            "source")


def _validate_facts(packet: EvidencePacket, finding: CriticFinding) -> None:
    claims = {c.claim_id: c for c in packet.claims}
    for fact in finding.facts:
        claim = claims.get(fact.claim_id)
        if claim is None:
            raise HardLimitViolation(
                f"fact cites unknown claim_id {fact.claim_id!r}")
        data = claim.data or {}
        if fact.field_path not in data:
            raise HardLimitViolation(
                f"fact field_path {fact.field_path!r} is not present on "
                f"claim {fact.claim_id!r}'s structured data")
        if not _numeric_equal(data[fact.field_path], fact.value):
            raise HardLimitViolation(
                f"fact {fact.claim_id}.{fact.field_path} claims "
                f"{fact.value!r} but the source carries "
                f"{data[fact.field_path]!r}")


def _validate_rankings(finding: CriticFinding) -> None:
    """Recomputes every ranking's rank from its own numbers. This is the
    check that would have rejected the first sample's "one of the smaller
    scores" -- a claimed_rank is never taken on the critic's word."""
    for r in finding.rankings:
        ordered = sorted([r.subject_value, *r.compared_values], reverse=True)
        actual_rank = ordered.index(r.subject_value) + 1  # 1 = highest
        if actual_rank != r.claimed_rank:
            raise HardLimitViolation(
                f"ranking {r.metric!r} claims rank {r.claimed_rank} for "
                f"{r.subject_value!r} against {list(r.compared_values)!r}, "
                f"but the recomputed rank is {actual_rank} (1 = highest)")


# A number token that is NOT directly fused to a word character (letter,
# digit or underscore) on either side -- `(?<!\w)` / `(?!\w)` are what keep
# this from matching the "10" inside a field-name-shaped identifier like
# `last10` or `home_sp_k9` when a finding's prose explains what a field is
# CALLED rather than citing its value (the underscore matters: without it,
# `last10_run_diff_pg`'s trailing `_` would not block the match). A real
# cited value is always surrounded by spaces or punctuation, never fused
# into an identifier, so this loses nothing a genuine citation needs.
_NUMBER_RE = re.compile(r"(?<!\w)-?\d+\.\d+(?!\w)|(?<!\w)-?\d+(?!\w)")
# Tokens whose internal digits are IDENTIFIERS, not analytic numbers, and
# are stripped before the number scan runs: ISO dates, this project's
# game_id shape, and "claim_kind:12345" ids. A list marker like "1)" is
# stripped too -- enumeration, not a citation.
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_GAME_ID_RE = re.compile(r"\b[A-Za-z]{2,4}-[A-Za-z]{2,4}-\d{4}-\d{2}-\d{2}-\d+\b")
_CLAIM_ID_RE = re.compile(r"\b[a-z_]+:[A-Za-z0-9_:.]+\b")
# A genuine "1)"/"2)" enumeration marker is at most two digits and sits at
# a WORD boundary -- never preceded by a digit or a decimal point. The
# naive `(?<!\d)\d+\)` this replaced matched "7811)" inside "3.7811)" by
# starting right after the decimal point (not itself a digit), silently
# swallowing the back half of a real decimal number along with its closing
# parenthesis -- caught by `tests/test_ai_analyst.py`'s own citation of
# 3.7811 in a real finding. `\d{1,2}` plus the boundary keeps a marker from
# ever starting mid-number.
_LIST_MARKER_RE = re.compile(r"(?<![\w.])\d{1,2}\)")


def _strip_exempt_tokens(text: str) -> str:
    text = _GAME_ID_RE.sub(" ", text)
    text = _ISO_DATE_RE.sub(" ", text)
    text = _CLAIM_ID_RE.sub(" ", text)
    text = _LIST_MARKER_RE.sub(" ", text)
    return text


def _numbers_in_text(text: str) -> list:
    return _NUMBER_RE.findall(_strip_exempt_tokens(text or ""))


def _number_in_pool(literal: str, pool: Sequence[float]) -> bool:
    """Decimal-aware match: "0.0964" matches a pool value of
    0.09638901961434626 because ROUNDING THE POOL VALUE TO THE PROSE
    NUMBER'S OWN PRECISION -- 4 places here -- gives 0.0964. Comparing at
    full precision would reject every rounded-for-readability number in
    honest prose; comparing with a fixed tolerance would let an unrelated
    nearby number slip through. Matching at the writer's own stated
    precision does neither."""
    try:
        parsed = float(literal)
    except ValueError:
        return False
    decimals = len(literal.split(".")[1]) if "." in literal else 0
    return any(round(float(v), decimals) == parsed for v in pool
              if isinstance(v, (int, float)))


def _allowed_numbers(packet: EvidencePacket, finding: CriticFinding) -> list:
    pool = []
    for fact in finding.facts:
        pool.append(fact.value)
    for r in finding.rankings:
        pool.append(r.subject_value)
        pool.extend(r.compared_values)
    rec = packet.recommendation
    pool.extend(v for v in (rec.price, rec.our_probability,
                            rec.market_probability)
               if isinstance(v, (int, float)))
    return pool


def _gather_free_text(finding: CriticFinding) -> list:
    texts = [("challenged_assumption", finding.challenged_assumption),
            ("case_against", finding.case_against),
            ("notes", finding.notes)]
    for i, (assumption, verdict, _ids) in enumerate(finding.verified_assumptions):
        texts.append((f"verified_assumptions[{i}][0]", assumption))
        texts.append((f"verified_assumptions[{i}][1]", verdict))
    for key, value in (finding.action_payload or {}).items():
        if key in _ID_LIST_KEYS or key in _NAME_ONLY_KEYS:
            continue
        if isinstance(value, str):
            texts.append((f"action_payload.{key}", value))
    return texts


def _validate_numbers_in_prose(packet: EvidencePacket,
                               finding: CriticFinding) -> None:
    pool = _allowed_numbers(packet, finding)
    for label, text in _gather_free_text(finding):
        for literal in _numbers_in_text(text):
            if not _number_in_pool(literal, pool):
                raise HardLimitViolation(
                    f"{label} contains the number {literal!r}, which does "
                    "not match any verified fact, ranking value or the "
                    "sealed recommendation's own numbers -- every number in "
                    "a finding's prose must be traceable to something this "
                    "module recomputed, not merely cited alongside")


def _named_person_entities(packet: EvidencePacket) -> set:
    """Every specific PERSON name this packet's claims could support an
    attribution to -- a probable-pitcher claim's entity, or an mlb_news
    transaction's entity. Team/side labels ("home", "COL") are excluded;
    they are not the identity this gate protects."""
    names = set()
    for c in packet.claims:
        if c.claim_id.startswith("probable:") or c.claim_id.startswith("mlb_news:"):
            if c.entity and len(c.entity) >= 4:
                names.add(c.entity)
    return names


def _validate_named_persons_are_attributed(packet: EvidencePacket,
                                           finding: CriticFinding) -> None:
    """THE FIRST SAMPLE'S EXACT MISTAKE, closed structurally: a specific
    person's name may appear in a finding's free text ONLY when that same
    name is declared through `pitcher_attribution` -- which is what then
    triggers the CONFIRMED-identity gate below. Naming someone in prose
    without declaring the attribution is refused outright, so the identity
    rule cannot be bypassed by simply not filling in the field meant to
    carry it."""
    names = _named_person_entities(packet)
    if not names:
        return
    allowed = set()
    if finding.pitcher_attribution is not None:
        allowed.add(finding.pitcher_attribution.get("name"))
    for label, text in _gather_free_text(finding):
        for name in names:
            if name in allowed:
                continue
            if name in text:
                raise HardLimitViolation(
                    f"{label} names {name!r} without declaring it through "
                    "pitcher_attribution -- a specific person may only be "
                    "named through the gated attribution mechanism (module "
                    "docstring, STARTER IDENTITY); this is the exact defect "
                    "the 2026-09-25 Opus review found")


def _validate_identity_gate(packet: EvidencePacket,
                            finding: CriticFinding) -> None:
    attribution = finding.pitcher_attribution
    if attribution is None:
        return
    required = {"side", "name", "identity_claim_id"}
    if set(attribution.keys()) != required:
        raise HardLimitViolation(
            f"pitcher_attribution must carry exactly {sorted(required)}, "
            f"got {sorted(attribution.keys())}")
    claims = {c.claim_id: c for c in packet.claims}
    claim = claims.get(attribution["identity_claim_id"])
    if claim is None:
        raise HardLimitViolation(
            f"pitcher_attribution.identity_claim_id "
            f"{attribution['identity_claim_id']!r} is not in this packet")
    confirmed = claim.status == "CONFIRMED"
    if confirmed:
        claimed_name = (claim.data or {}).get("probable_name") or claim.entity
        if str(claimed_name).strip().lower() != str(attribution["name"]).strip().lower():
            raise HardLimitViolation(
                f"pitcher_attribution.name {attribution['name']!r} does not "
                f"match the CONFIRMED identity claim's own name "
                f"{claimed_name!r}")
    elif finding.action in ("CORRECT_INPUT", "RECALCULATE"):
        raise HardLimitViolation(
            f"pitcher_attribution.identity_claim_id resolves to a "
            f"{claim.status} claim, not CONFIRMED -- {finding.action} may "
            "not rest on an unconfirmed starter identity; the only "
            "allowed action naming this person is REQUEST_SCENARIO")


def validate_hard_limits(packet: EvidencePacket,
                         finding: CriticFinding) -> None:
    """Raises `HardLimitViolation` on the first check that fails. Called by
    `apply_critic` before it builds the report, and callable directly by a
    test that wants to prove a specific violation is CAUGHT."""
    _validate_action_payload_shape(finding)
    _validate_no_forbidden_field_names(finding)
    _validate_source_claims_exist(packet, finding)
    _validate_verified_assumptions_cite_real_claims(packet, finding)
    _validate_correct_input_confirmed(packet, finding)
    _validate_correct_input_values_are_verified_facts(finding)
    _validate_identity_gate(packet, finding)
    _validate_named_persons_are_attributed(packet, finding)
    _validate_facts(packet, finding)
    _validate_rankings(finding)
    _validate_numbers_in_prose(packet, finding)


def verify_and_report(packet: EvidencePacket, finding: CriticFinding) -> dict:
    """Every check `validate_hard_limits` runs, independently, each
    recorded PASS/FAIL rather than stopping at the first failure -- the
    owner's release gate asked for "a machine check file showing every
    fact and ranking verification PASS", which a single fail-fast
    exception cannot show. `apply_critic` still uses `validate_hard_limits`
    (fail-fast, for enforcement); this is the diagnostic companion written
    alongside a report.

    Each `Fact` and each `Ranking` gets its OWN row (`fact[i]`/
    `ranking[i]`), checked in isolation by re-running the same validator on
    a finding carrying only that one entry -- so one bad fact cannot hide
    whether the other nine were actually verified.
    """
    checks = []

    def record(label, fn):
        try:
            fn()
            checks.append({"check": label, "result": "PASS"})
        except HardLimitViolation as exc:
            checks.append({"check": label, "result": "FAIL",
                          "detail": str(exc)})

    record("action_payload_shape",
          lambda: _validate_action_payload_shape(finding))
    record("no_forbidden_field_names",
          lambda: _validate_no_forbidden_field_names(finding))
    record("source_claims_exist",
          lambda: _validate_source_claims_exist(packet, finding))
    record("verified_assumptions_cite_real_claims",
          lambda: _validate_verified_assumptions_cite_real_claims(
              packet, finding))
    record("correct_input_confirmed",
          lambda: _validate_correct_input_confirmed(packet, finding))
    record("correct_input_values_are_verified_facts",
          lambda: _validate_correct_input_values_are_verified_facts(finding))
    record("identity_gate", lambda: _validate_identity_gate(packet, finding))
    record("named_persons_are_attributed",
          lambda: _validate_named_persons_are_attributed(packet, finding))
    for i, fact in enumerate(finding.facts):
        record(f"fact[{i}] {fact.claim_id}#{fact.field_path}",
              lambda fact=fact: _validate_facts(
                  packet, replace(finding, facts=(fact,))))
    for i, r in enumerate(finding.rankings):
        record(f"ranking[{i}] {r.metric}",
              lambda r=r: _validate_rankings(replace(finding, rankings=(r,))))
    record("numbers_in_prose",
          lambda: _validate_numbers_in_prose(packet, finding))

    return {"all_passed": all(c["result"] == "PASS" for c in checks),
           "n_checks": len(checks), "checks": checks}


@dataclass(frozen=True)
class AnalystReport:
    """The final artifact: the sealed recommendation, the evidence it was
    checked against, and the critic's finding -- never merged into one
    number."""
    game_id: str
    date: str
    built_at: str
    recommendation: dict
    evidence: list
    finding: dict
    experimental_contribution: dict


def apply_critic(packet: EvidencePacket, finding: CriticFinding) -> AnalystReport:
    """Combine a packet and a finding into the artifact -- the ONLY
    function that produces an `AnalystReport`, so every report this module
    ever writes has passed `validate_hard_limits` first."""
    if finding.game_id != packet.game_id:
        raise HardLimitViolation(
            f"finding.game_id {finding.game_id!r} does not match "
            f"packet.game_id {packet.game_id!r}")
    validate_hard_limits(packet, finding)
    finding = mark_session_assisted(finding)
    return AnalystReport(
        game_id=packet.game_id,
        date=packet.date,
        built_at=packet.built_at,
        recommendation=asdict(packet.recommendation),
        evidence=[asdict(c) for c in packet.claims],
        finding=asdict(finding),
        experimental_contribution={
            "contribution_kind": finding.contribution_kind,
            "action": finding.action,
            "disclaimer": (
                "This is an experimental LLM/session contribution, logged "
                "separately from the model's own published or shadow "
                "output. It carries no authority over anything published "
                "and was never merged into `recommendation` above -- "
                "compare the two objects field by field to see that "
                "nothing here overwrote anything there."),
        },
    )


# ---------------------------------------------------------------------------
# Evidence gathering -- reads only, no writes, no paid call.
# ---------------------------------------------------------------------------

def recommendation_from_shadow_artifact(path: str, game_id: str
                                        ) -> ModelRecommendation:
    """One selection from a `scripts/shadow_enumeration_run.py` artifact,
    by `game_id`. Raises `LookupError` rather than guessing when the game
    is not among that artifact's selections."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    for row in payload.get("corrected_path", {}).get("selections", []):
        if row.get("game_id") == game_id:
            return ModelRecommendation(
                game_id=game_id, market=row.get("market") or "",
                side=row.get("side") or "",
                price=row.get("price"),
                our_probability=row.get("our_probability"),
                market_probability=row.get("market_probability"),
                source_artifact=path,
                bet_sentence=row.get("bet") or "")
    raise LookupError(
        f"{game_id!r} is not among {path!r}'s corrected_path.selections")


# The model-input fields this module surfaces per side, exactly as
# `model_inputs` names them -- kept structured (`Claim.data`) rather than
# only rendered into text, so a `Fact` can cite any one of them precisely.
_STARTER_STAT_SUFFIXES = (
    "known", "era", "whip", "k9", "bb9", "hr9", "fip", "k_bb_pct",
    "ip_per_start", "starts", "appearances", "innings", "days_rest",
    "recent_starts", "recent_era", "recent_ip_per_start", "thin")

# TEAM-level (not starter-specific) fields -- season aggregates and recent
# form. `strength.run_means`/`model_line` read ONLY the season aggregates
# (`*_runs_scored_pg`, `*_runs_allowed_pg`, `*_games_played`) -- a `grep` of
# `src/analysis/strength.py` for "last5"/"last10"/"streak" turns up nothing,
# so the recent-form fields below are captured on every model_input claim
# for citation, but a finding that treats them as something the MODEL
# weighed would be asserting something this repo's own model code does not
# do. Both sides' team stats on each side's claim, same reasoning as the
# bullpen rates just below -- the number is identical either way, and
# `_validate_facts` only cares that it resolves.
_TEAM_STAT_SUFFIXES = (
    "runs_scored_pg", "runs_allowed_pg", "run_diff_pg", "win_pct",
    "games_played", "last5_run_diff_pg", "last10_run_diff_pg",
    "last5_runs_scored_pg", "last10_runs_scored_pg", "streak")


def model_input_claims(path: str, game_id: str, *, retrieved_at: str
                       ) -> list:
    """Claims sourced from the run's OWN recorded model inputs
    (`board.models_by_game`) -- what the model itself assumed about
    starters, sample size and form."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    rec = (payload.get("board", {}).get("models_by_game") or {}).get(game_id)
    if not rec:
        return []
    inputs = rec.get("model_inputs") or {}
    claims = []
    for side in ("home", "away"):
        known = inputs.get(f"{side}_sp_known")
        team = rec.get(f"{side}_team")
        text = (
            f"{side} starter known to the model: {known}"
            + (f" (ERA {inputs.get(f'{side}_sp_era')}, "
               f"{inputs.get(f'{side}_sp_starts')} starts, "
               f"{inputs.get(f'{side}_sp_days_rest')} days rest)"
               if known else " -- no probable pitcher posted at capture "
               "time; the team's blended offence/defence rate stands in "
               "for the whole game (strength.run_means's own fallback, "
               "not this module's invention)"))
        data = {f"{side}_sp_{suf}": inputs.get(f"{side}_sp_{suf}")
               for suf in _STARTER_STAT_SUFFIXES}
        # Both bullpens, and both teams' full stat lines, on EACH side's
        # claim, so a comparison between them can cite either claim_id --
        # the number itself is identical either way, and `_validate_facts`
        # only cares that it resolves.
        data["home_bullpen_rate"] = inputs.get("home_bullpen_rate")
        data["away_bullpen_rate"] = inputs.get("away_bullpen_rate")
        for other_side in ("home", "away"):
            for suf in _TEAM_STAT_SUFFIXES:
                data[f"{other_side}_{suf}"] = inputs.get(f"{other_side}_{suf}")
        claims.append(Claim(
            claim_id=f"model_input:{game_id}:{side}_sp_known",
            entity=team or side, event="starter_known_to_model",
            text=text, source_ref=f"{path}#board.models_by_game.{game_id}"
                                  f".model_inputs.{side}_sp_known",
            retrieved_at=retrieved_at,
            # The CLAIM's status tracks whether a starter is actually
            # known, not merely whether the pipeline recorded a boolean --
            # `known is False` and `known is None` both mean "no confirmed
            # starter" and must both read as UNCONFIRMED.
            status="CONFIRMED" if known else "UNCONFIRMED",
            uncertainty=("model's own point-in-time capture; not a "
                        "probability, a boolean the pipeline recorded"),
            intended_use="verify the starter assumption behind the model's "
                        "probability",
            published_at=None, independent=True, data=data))
    return claims


_IL_DAYS_RE = re.compile(r"(\d+)-day")


def mlb_news_claims(*, start_date: str, end_date: str, teams: Sequence[str],
                    retrieved_at: str, intended_use: str) -> list:
    """Claims from MLB's own free transactions feed, filtered to the given
    club codes. `NewsError` (or any fetch failure) returns an EMPTY list,
    never a fabricated claim."""
    from src.providers import mlb_news

    try:
        rows = mlb_news.fetch(start_date, end_date)
    except Exception:  # noqa: BLE001 -- an unreachable feed is a gap, not
        # a reason to invent evidence in its place.
        return []
    claims = []
    for row in rows:
        if row.get("team") not in teams and row.get("to_team") not in teams \
                and row.get("from_team") not in teams:
            continue
        description = row.get("description") or ""
        il_match = _IL_DAYS_RE.search(description)
        data = {"il_days": int(il_match.group(1))} if il_match else None
        claims.append(Claim(
            claim_id=f"mlb_news:{row.get('transaction_id')}",
            entity=row.get("player") or row.get("team") or "unknown",
            event=row.get("category") or "transaction",
            text=description,
            source_ref=f"MLB transactions feed, transaction_id="
                       f"{row.get('transaction_id')}",
            published_at=row.get("filed_date") or row.get("date"),
            retrieved_at=retrieved_at,
            status="CONFIRMED",  # MLB's own record of its own transaction
            uncertainty="primary source (the league's own transaction "
                       "record); no independent confirmation sought",
            intended_use=intended_use, independent=True, data=data))
    return claims[:MAX_CLAIMS]


def market_claim(recommendation: ModelRecommendation, *, market_row: dict,
                 retrieved_at: str) -> Claim:
    """The market's own state, as a claim like any other."""
    data = {"best_price": market_row.get("best_price"),
            "books": market_row.get("books"),
            "market_implied_probability":
                market_row.get("market_implied_probability")}
    return Claim(
        claim_id=f"market:{recommendation.game_id}:{recommendation.side}",
        entity=recommendation.side, event="market_quote",
        text=(f"Best price {market_row.get('best_price')} at "
             f"{market_row.get('best_book')}, {market_row.get('books')} "
             f"books, implied probability "
             f"{market_row.get('market_implied_probability')}"),
        source_ref=f"shadow artifact quotes_by_game."
                   f"{recommendation.game_id}.{recommendation.side}",
        published_at=market_row.get("observed_utc"),
        retrieved_at=retrieved_at, status="CONFIRMED",
        uncertainty="a quote, not a forecast -- no uncertainty beyond "
                   "staleness, which G3 already governs",
        intended_use="anchor the recommendation's market_probability to "
                    "its own source", independent=True, data=data)


def _parse_game_id(game_id: str):
    """`(away_abbrev, home_abbrev, game_number)` from this project's own
    `gamepayload.game_id` shape (`AWAY-HOME-YYYY-MM-DD-N`)."""
    parts = game_id.split("-")
    away, home = parts[0], parts[1]
    game_number = int(parts[-1]) if parts[-1].isdigit() else 1
    return away, home, game_number


def starter_identity_claims(date: str, game_id: str, *, retrieved_at: str
                            ) -> list:
    """One CONFIRMED or UNCONFIRMED claim per side, from MLB's own schedule
    feed's `probablePitcher` hydration -- a DIFFERENT, more authoritative
    source than the model's own `*_sp_known` flag (which only says whether
    THIS repo's pipeline found a starter). A fetch failure or an unmatched
    game returns an empty list, never a guess."""
    from src.providers import mlb as mlb_provider

    away, home, game_number = _parse_game_id(game_id)
    try:
        games = mlb_provider.fetch_games(date)
    except Exception:  # noqa: BLE001 -- an unreachable schedule feed is a
        # gap, not a reason to invent a starter.
        return []
    match = None
    for g in games:
        if (g.get("away_team") == away and g.get("home_team") == home
                and (g.get("game_number") or 1) == game_number):
            match = g
            break
    if match is None:
        return []

    claims = []
    for side in ("home", "away"):
        name = match.get(f"{side}_probable")
        pid = match.get(f"{side}_probable_id")
        confirmed = name is not None and pid is not None
        claims.append(Claim(
            claim_id=f"probable:{game_id}:{side}",
            entity=name if confirmed else f"{side} starter unconfirmed",
            event="probable_pitcher",
            text=(f"MLB's schedule feed lists the {side} probable starter "
                 f"as {name} (id {pid})." if confirmed else
                 f"MLB's schedule feed carries no probable starter for the "
                 f"{side} side as of retrieval."),
            source_ref="MLB schedule feed (mlb.fetch_games, "
                      "hydrate=probablePitcher)",
            published_at=None, retrieved_at=retrieved_at,
            status="CONFIRMED" if confirmed else "UNCONFIRMED",
            uncertainty=("primary source -- the league's own "
                        "probable-pitcher listing" if confirmed else
                        "no probable pitcher posted for this side as of "
                        "retrieval; this is an absence, not a failed "
                        "lookup"),
            intended_use="verify starter identity before attributing "
                        "anything to a named pitcher",
            data=({"probable_id": pid, "probable_name": name}
                 if confirmed else None)))
    return claims


def build_evidence_packet(artifact_path: str, game_id: str, *,
                          news_window_days: int = 8,
                          include_identity_claims: bool = True
                          ) -> EvidencePacket:
    """Assembles the packet this module's demo runs against: the sealed
    recommendation, the model's own starter-known claims, MLB transactions
    for both clubs over the trailing window, the market's own quote, and
    (new) MLB's own probable-pitcher listing for starter identity. Bounded
    by `MAX_CLAIMS` (constructor-enforced)."""
    with open(artifact_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    date = payload.get("date")
    retrieved_at = datetime.now(timezone.utc).isoformat()

    recommendation = recommendation_from_shadow_artifact(artifact_path, game_id)
    claims = list(model_input_claims(artifact_path, game_id,
                                     retrieved_at=retrieved_at))

    quote_row = (payload.get("board", {}).get("quotes_by_game") or {}) \
        .get(game_id, {}).get(recommendation.side)
    if quote_row:
        claims.append(market_claim(recommendation, market_row=quote_row,
                                   retrieved_at=retrieved_at))

    if include_identity_claims:
        claims.extend(starter_identity_claims(date, game_id,
                                              retrieved_at=retrieved_at))

    away, home, _n = _parse_game_id(game_id)
    start = (datetime.fromisoformat(date + "T00:00:00+00:00")
            - timedelta(days=news_window_days))
    claims.extend(mlb_news_claims(
        start_date=start.date().isoformat(), end_date=date,
        teams=(away, home), retrieved_at=retrieved_at,
        intended_use="verify lineup/availability assumptions against "
                    "sourced evidence"))

    return EvidencePacket(game_id=game_id, date=date,
                          built_at=retrieved_at,
                          recommendation=recommendation,
                          claims=tuple(claims[:MAX_CLAIMS]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", required=True,
                    help="a scripts/shadow_enumeration_run.py output path")
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    packet = build_evidence_packet(args.artifact, args.game_id)
    print(json.dumps({"game_id": packet.game_id,
                      "recommendation": asdict(packet.recommendation),
                      "n_claims": len(packet.claims),
                      "claims": [asdict(c) for c in packet.claims]},
                     indent=2, default=str), file=sys.stderr)
    print("(packet built; this CLI does not write a CriticFinding -- see "
         "evidence/ai_analyst/ for the session-assisted demonstration and "
         "this module's own functions to build a new one)", file=sys.stderr)
    if args.dry_run:
        return 0
    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(
        args.out_dir, f"{packet.game_id}_{stamp}_evidence_packet.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({
            "game_id": packet.game_id, "date": packet.date,
            "built_at": packet.built_at,
            "recommendation": asdict(packet.recommendation),
            "claims": [asdict(c) for c in packet.claims],
        }, indent=2, default=str) + "\n")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
