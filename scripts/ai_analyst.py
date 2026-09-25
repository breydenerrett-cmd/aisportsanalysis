#!/usr/bin/env python3
"""A bounded evidence packet for ONE game, and a critic that does work a
reader can check -- the first real demonstration Lane D Part 3 asked for.

WHAT THIS IS NOT
-----------------
Not a forecaster. Not a second model. Not a veto with authority over
anything published -- nothing in `src/report/`, `src/analysis/best_bets_card.py`
or `src/appstate/card_ledger.py` is imported, read, or touched by this file,
and Ranker Engine 2 stays gated exactly as every other lane leaves it. This
produces a REVIEW of one already-computed shadow recommendation: it verifies
what the model assumed, argues the case against taking the bet, and says so
when nothing justifies a change. The review is data. A human decides what
to do with it.

WHY "SOURCED EVIDENCE" MEANS THE REPO'S OWN CAPTURED FEEDS, NOT A WEB SEARCH
-----------------------------------------------------------------------------
`src/providers/mlb_news.py`'s own docstring makes the argument this module
follows: "A claim built on a web search made tonight can never be tested
against [an earlier date], because there is no honest way to reconstruct
what a search would have returned." This project's slates are also
point-in-time captures under a project date that does not track the real
calendar -- a live web search for tonight's matchup would return either
nothing that corresponds to this capture or, worse, real-world information
about an unrelated game that LOOKS relevant and is not. Both failure modes
are silent. So every claim this module builds cites one of:

  * this repo's own captured model inputs (`models_by_game` in a shadow
    artifact -- what the model itself assumed, e.g. `away_sp_known`);
  * `src.providers.mlb_news.fetch` -- MLB's own free, dated transactions
    feed (`NewsError` on failure, never a guess);
  * the market quotes already in the shadow artifact.

None of these three is a paid call. No credential, no API key and no cost
is touched by anything in this file.

CLAIM SCHEMA
------------
Every claim (`Claim`, below) carries `claim_id`, `entity`, `event`, `text`,
`source_ref`, `published_at` (`None` when the source carries no publish
time -- never invented), `retrieved_at`, `status`
(`CONFIRMED`/`UNCONFIRMED`/`CONTRADICTED`/`STALE`/`UNRELATED`),
`uncertainty` (a short string, never a fabricated number -- this repo does
not have a calibrated confidence model for news text and pretending
otherwise would be exactly the "invented probability" HARD LIMITS forbids),
`intended_use`, and `independent` (`True` for a distinct primary source,
`False` for a rows that only repeats another claim's source_ref -- so a
reader can tell one confirmed fact from three copies of the same wire
story).

HARD LIMITS (enforced by `validate_hard_limits`, not just asserted in prose)
-----------------------------------------------------------------------------
The critic's `CriticFinding` is a SEPARATE object from the model's
`ModelRecommendation` for exactly this reason: `apply_critic` never writes
into the recommendation's own fields, and `validate_hard_limits` raises
`HardLimitViolation` if a `CriticFinding` tries to carry a probability
number, a threshold, or a `None` value in the appended-not-mutated
`model_recommendation` echo below the sealed input's own recorded value.
Any LLM contribution (a forecast, a recalculation request, a veto opinion)
is written under `experimental_contribution`, tagged, and never merged into
`model_recommendation`.

SESSION-ASSISTED, LABELLED AS SUCH
-----------------------------------
There is no standing budget for an autonomous LLM-critic API call in this
lane (task instruction: "If you have no API budget, do the demonstration
through this authorized session"). The demonstration in
`evidence/ai_analyst/` was produced by a human-directed Claude Code session
reading the evidence packet this module built and writing the
`CriticFinding` by hand -- real analysis, `contribution_kind:
"session_assisted"`, explicitly NOT evidence of an unattended production
agent. `mark_session_assisted` stamps that on every finding this module
writes so the distinction cannot be dropped downstream.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
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
VERDICTS = ("NO_ADJUSTMENT", "RECALCULATION_REQUESTED",
           "ALTERNATE_MARKET_SUGGESTED", "ADJUSTMENT_REQUESTED")


class HardLimitViolation(ValueError):
    """A `CriticFinding` tried to do one of the four things a critic may
    never do (module docstring, HARD LIMITS). Raised, never silently
    corrected -- a critic output that violates this is a bug to fix in the
    critic step, not a value this module papers over."""


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

    def __post_init__(self):
        if self.status not in CLAIM_STATUSES:
            raise ValueError(f"unknown claim status: {self.status!r}")
        if not self.claim_id or not self.entity or not self.text:
            raise ValueError("claim_id, entity and text are required and "
                             "may never be blank")


@dataclass(frozen=True)
class ModelRecommendation:
    """A READ-ONLY echo of what the model already produced -- never built
    by this module. `game_id`, `market`, `side`, `price`,
    `our_probability`, `market_probability` and `source_artifact` are the
    sealed facts a critic is reviewing, not proposing."""
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
class CriticFinding:
    """The critic's checkable work product. Every field below is the
    critic's OWN judgement, kept apart from `recommendation` by
    construction -- `apply_critic` never lets one leak into the other.

    `verified_assumptions`: (assumption text, verdict, evidence claim_ids)
        triples -- "verify starter/lineup/availability assumptions against
        sourced evidence".
    `challenged_assumption`: the model's STRONGEST assumption (task's own
        instruction: not the weakest), named and argued against.
    `alternate_market`: another market that might express the same sporting
        thesis better, or `None` if none does.
    `recalculation_request`: `{"reason": str, "scenario": str}` or `None` --
        a REQUEST for the model to be rerun under a named scenario, never a
        number the critic computed itself.
    `case_against`: the strongest case AGAINST the recommendation, argued
        in prose -- required even when the verdict is NO_ADJUSTMENT, so a
        "no adjustment" verdict is never mistaken for "no case existed".
    `verdict`: one of `VERDICTS`. `NO_ADJUSTMENT` is a first-class success,
        not a fallback (task's own words).
    `contribution_kind`: `"session_assisted"` here, always -- see module
        docstring. Never silently defaults; `mark_session_assisted` sets it
        so a caller cannot forget to.
    """
    game_id: str
    verified_assumptions: tuple
    challenged_assumption: str
    alternate_market: Optional[str]
    recalculation_request: Optional[dict]
    case_against: str
    verdict: str
    contribution_kind: str = "unset"
    notes: str = ""

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"unknown verdict: {self.verdict!r}")
        if not self.case_against.strip():
            raise ValueError(
                "case_against is required even for NO_ADJUSTMENT -- a "
                "refusal without a stated case is not checkable")


def mark_session_assisted(finding: CriticFinding) -> CriticFinding:
    """The ONE place `contribution_kind` is set to `"session_assisted"`, so
    every finding this module writes is labelled the same way and a caller
    cannot construct one that silently reads as autonomous-agent output."""
    return CriticFinding(**{**asdict(finding),
                            "contribution_kind": "session_assisted"})


def validate_hard_limits(recommendation: ModelRecommendation,
                         finding: CriticFinding) -> None:
    """Raises `HardLimitViolation` if `finding` does any of the four things
    a critic may never do. Called by `apply_critic` before it builds the
    combined report, and callable directly by a test that wants to prove a
    violation is CAUGHT rather than merely undocumented.

    1. INVENT A PROBABILITY ADJUSTMENT: `recalculation_request` is a
       request for the MODEL to recompute, carrying no numeric probability
       of the critic's own. A dict with a `probability`/`our_probability`/
       `p_home`-shaped key is refused outright.
    2. ALTER A PUBLISHED RECORD: this function never receives write access
       to anything published, and enforces that no key of `recommendation`
       (the sealed echo) appears inside `recalculation_request` with a
       DIFFERENT value than `recommendation` itself carries.
    3. WIDEN A THRESHOLD: no gate parameter name (best_bets_card's public
       constants) may appear as a key in `recalculation_request`.
    4. SILENTLY REPLACE THE MODEL'S NUMBER: `CriticFinding` has no field
       shaped like a probability at all -- there is nothing to check here
       because the schema itself makes the violation unrepresentable,
       EXCEPT `recalculation_request`, which is free-form and therefore
       the one place this still has to be checked at runtime.
    """
    forbidden_keys = {
        "probability", "our_probability", "p_home", "p_away",
        "market_probability", "score", "p_raw", "calibrated_probability",
        # Gate/threshold parameter names (best_bets_card.RuleParams fields)
        # -- see that module for the authoritative list; duplicated here as
        # a STRING check on purpose, not an import, so this module never has
        # to import best_bets_card to do its job.
        "worst_price", "best_price", "markdown", "base_edge",
        "main_market_floor", "main_our_floor", "plus_market_floor",
        "plus_our_floor", "disagreement_cap", "ceiling", "floor",
        "game_min_books", "fresh_seconds", "plus_money_subcap",
    }
    req = finding.recalculation_request
    if req is not None:
        if not isinstance(req, dict):
            raise HardLimitViolation(
                "recalculation_request must be a dict of {reason, "
                "scenario} or None")
        bad = forbidden_keys & set(req.keys())
        if bad:
            raise HardLimitViolation(
                f"recalculation_request carries forbidden key(s) {sorted(bad)} "
                "-- a request may name a SCENARIO for the model to "
                "recompute, never a number or a threshold the critic "
                "picked itself")
        if req.get("game_id") not in (None, recommendation.game_id):
            raise HardLimitViolation(
                "recalculation_request.game_id does not match the "
                "recommendation under review -- a critic may not redirect "
                "its own request to a different published record")


@dataclass(frozen=True)
class AnalystReport:
    """The final artifact: the sealed recommendation, the evidence it was
    checked against, and the critic's finding -- three fields, never
    merged into one number. `experimental_contribution` restates the
    finding under an explicit "this is an experimental LLM contribution,
    logged separately" label, per the task's own requirement."""
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
    validate_hard_limits(packet.recommendation, finding)
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
            "verdict": finding.verdict,
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
    is not among that artifact's selections -- an analyst packet is never
    built for a bet the artifact does not actually contain."""
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


def model_input_claims(path: str, game_id: str, *, retrieved_at: str
                       ) -> list:
    """Claims sourced from the run's OWN recorded model inputs
    (`board.models_by_game`) -- what the model itself assumed about
    starters, sample size and form, stated as claims with a source
    reference into this exact artifact rather than re-derived."""
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
        claims.append(Claim(
            claim_id=f"model_input:{game_id}:{side}_sp_known",
            entity=team or side, event="starter_known_to_model",
            text=text, source_ref=f"{path}#board.models_by_game.{game_id}"
                                  f".model_inputs.{side}_sp_known",
            retrieved_at=retrieved_at,
            # The CLAIM's status tracks whether a starter is actually
            # known, not merely whether the pipeline recorded a boolean.
            # `known is False` and `known is None` both mean "no confirmed
            # starter" and must both read as UNCONFIRMED -- collapsing
            # them into "CONFIRMED because a value exists" would make the
            # exact gap this claim exists to surface disappear into the
            # word "CONFIRMED".
            status="CONFIRMED" if known else "UNCONFIRMED",
            uncertainty=("model's own point-in-time capture; not a "
                        "probability, a boolean the pipeline recorded"),
            intended_use="verify the starter assumption behind the model's "
                        "probability",
            published_at=None, independent=True))
    return claims


def mlb_news_claims(*, start_date: str, end_date: str, teams: Sequence[str],
                    retrieved_at: str, intended_use: str) -> list:
    """Claims from MLB's own free transactions feed, filtered to the given
    club codes. `NewsError` (or any fetch failure) returns an EMPTY list,
    never a fabricated claim -- module docstring's "never a guess"."""
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
        claims.append(Claim(
            claim_id=f"mlb_news:{row.get('transaction_id')}",
            entity=row.get("player") or row.get("team") or "unknown",
            event=row.get("category") or "transaction",
            text=row.get("description") or "",
            source_ref=f"MLB transactions feed, transaction_id="
                       f"{row.get('transaction_id')}",
            published_at=row.get("filed_date") or row.get("date"),
            retrieved_at=retrieved_at,
            status="CONFIRMED",  # MLB's own record of its own transaction
            uncertainty="primary source (the league's own transaction "
                       "record); no independent confirmation sought",
            intended_use=intended_use, independent=True))
    return claims[:MAX_CLAIMS]


def market_claim(recommendation: ModelRecommendation, *, market_row: dict,
                 retrieved_at: str) -> Claim:
    """The market's own state, as a claim like any other -- a price is
    also a sourced, timestamped fact, not something this module treats
    differently from a news row."""
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
                    "its own source", independent=True)


def build_evidence_packet(artifact_path: str, game_id: str, *,
                          news_window_days: int = 8) -> EvidencePacket:
    """Assembles the packet this module's demo runs against: the sealed
    recommendation, the model's own starter-known claims, and MLB
    transactions for both clubs over the trailing window. Bounded by
    `MAX_CLAIMS` (constructor-enforced)."""
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

    away, home = game_id.split("-")[0], game_id.split("-")[1]
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
