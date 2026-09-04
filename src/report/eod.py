"""The end-of-day self-review: `build_review` (pure) + `write_review` (thin writer).

WHY THIS EXISTS
-----------------
docs/CHECKPOINT_PHASE0_2026-09-03.md §5 S7: "A deterministic report: decisions,
vetoes, settlements, CLV where a close exists, fitness deltas, what the
engine did not know (assumption exposure), written to docs/eod/ and the
chain." No slate runner exists yet (S5/S6 are still ahead of this), so this
module is built against explicit inputs a future runner will assemble:
`AccountDay` snapshots (one per system, replayed from that system's own
hash-chained ledger up to and including the report date -- see
`account_day_from_ledger_rows`), the day's `DecisionRecord`s, whatever
`ReviewRecord`s exist, and whatever `Scorecard`s exist (for the fitness-delta
section).

EVERY NUMBER TRACEABLE, NO NARRATIVE WITHOUT ONE
--------------------------------------------------
`build_review` never invents a sentence that is not backed by a field on one
of its inputs. Where evidence for a section is genuinely absent (no prior
Scorecard to diff against, no captured close on a decision, zero decisions of
a given verdict), the report says so explicitly instead of omitting the
section or filling it with a placeholder that reads as a real finding.

DETERMINISM
------------
`build_review`/`render_markdown` take no clock, no randomness, and no
environment: given the same inputs, the same bytes come out every time. The
report's `date` field is the caller-supplied date string, never
`datetime.now()`. `write_review` is the one place a clock or the filesystem
enters -- it is a thin wrapper that renders, writes the file, and appends one
summary row to its own hash chain.

LOSERS ARE ALWAYS SHOWN
--------------------------
The "Losing bets" section is never omitted, never filtered out because it
looks bad, and never truncated the way a "top N" table might be -- every
settlement whose outcome was a loss appears there, full stop.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from src.board.settle import LOSS, PUSH, VOID, WIN
from src.core import calibration as calibration_module
from src.factory.scorecard import (
    CalibrationReport,
    _CALIBRATION_ELIGIBLE_PROVENANCE,
    build_calibration_report,
    decision_key_for,
)
from src.ledger.chain import HashChainLedger
from src.ledger.records import DecisionRecord, ReviewRecord, Scorecard
from src.paths import evidence_path, repo_root

EOD_REVIEW_LEDGER_PATH = evidence_path("eod_reviews_v2.jsonl")

REFUSAL_VERDICTS = (
    "no_play", "market_unavailable", "refused_stale", "refused_thin",
    "refused_grade", "refused_sample", "refused_regime", "refused_friction",
)


class EodReviewError(ValueError):
    """The end-of-day review could not be built or written honestly."""


# ---------------------------------------------------------------------------
# Per-account replay
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SettlementSummary:
    system_id: str
    bet_id: str
    market_key: str
    selection_id: str
    price_american: int
    outcome: str
    profit_units: float


@dataclass(frozen=True, slots=True)
class AccountDay:
    """One system's paper account, replayed from its own hash-chained ledger
    rows (`src.accounts.paper.PaperAccount._record_settlement`'s own output
    shape) up to and including `day`. `settlements` holds only the rows
    whose own `day` equals this one."""

    system_id: str
    day: str
    starting_bankroll: float
    bankroll: float
    peak: float
    drawdown_current: float
    drawdown_max: float
    roi_units: float
    n_settled: int
    n_wins: int
    n_losses: int
    n_pushes: int
    n_voids: int
    total_staked_units: float
    total_profit_units: float
    settlements: tuple  # tuple[SettlementSummary, ...], this day only


def account_day_from_ledger_rows(system_id: str, rows: Sequence[Mapping],
                                  day: str,
                                  starting_bankroll: float = 1000.0) -> AccountDay:
    """Replay `rows` (as read from that system's `HashChainLedger`, in
    append order) into the account's state as of the end of `day`. Rows
    whose own `day` is after the report date are ignored -- this is a
    point-in-time snapshot, not the account's current live state."""
    bankroll = starting_bankroll
    peak = starting_bankroll
    drawdown_max = 0.0
    n_settled = n_wins = n_losses = n_pushes = n_voids = 0
    total_staked = total_profit = 0.0
    todays: list = []

    for row in rows:
        row_day = row.get("day")
        if row_day is None or row_day > day:
            continue
        outcome = row["outcome"]
        n_settled += 1
        if outcome == WIN:
            n_wins += 1
        elif outcome == LOSS:
            n_losses += 1
        elif outcome == PUSH:
            n_pushes += 1
        elif outcome == VOID:
            n_voids += 1
        if outcome not in (PUSH, VOID):
            total_staked += row["stake_units"]
        total_profit += row["profit_units"]
        bankroll += row["profit_units"]
        peak = max(peak, bankroll)
        drawdown_max = max(drawdown_max, peak - bankroll)
        if row_day == day:
            todays.append(SettlementSummary(
                system_id=row.get("system_id", system_id),
                bet_id=row["bet_id"], market_key=row["market_key"],
                selection_id=row["selection_id"],
                price_american=row["price_american"], outcome=outcome,
                profit_units=row["profit_units"],
            ))

    roi_units = (total_profit / total_staked) if total_staked > 0 else 0.0
    return AccountDay(
        system_id=system_id, day=day, starting_bankroll=starting_bankroll,
        bankroll=bankroll, peak=peak, drawdown_current=peak - bankroll,
        drawdown_max=drawdown_max, roi_units=roi_units, n_settled=n_settled,
        n_wins=n_wins, n_losses=n_losses, n_pushes=n_pushes, n_voids=n_voids,
        total_staked_units=total_staked, total_profit_units=total_profit,
        settlements=tuple(sorted(todays, key=lambda s: s.bet_id)),
    )


# ---------------------------------------------------------------------------
# Review structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DecisionSummary:
    event_id: str
    market_key: Optional[str]
    selection_id: Optional[str]
    price_american: Optional[int]
    edge_bps: Optional[int]
    known_at_grade: str
    thesis: Optional[str]
    # N2/honesty fix (2026-09-04): every decision line names WHERE its
    # p_model (or lack of one) came from -- `edge_bps` alone cannot say
    # whether a null `edge_bps` means "model_derived but no edge found" or
    # "structurally impossible to compute one for this provenance"; a
    # reader must never have to guess which.
    p_model_provenance: str


@dataclass(frozen=True, slots=True)
class VetoGroup:
    verdict: str
    count: int
    reasons: tuple  # distinct refusal_reason strings, sorted


@dataclass(frozen=True, slots=True)
class PriceVsClose:
    event_id: str
    market_key: str
    selection_id: str
    price_american: int
    close_price: int
    cents: float
    prob_edge: float
    beat_close: bool


@dataclass(frozen=True, slots=True)
class AssumptionExposureItem:
    event_id: str
    known_at_grade: str
    assumption_exposure: Mapping


@dataclass(frozen=True, slots=True)
class ScorecardDelta:
    system_id: str
    current_window: str
    previous_window: Optional[str]
    deltas: Mapping  # {field: (previous, current, delta)}; empty if no prior


@dataclass(frozen=True, slots=True)
class EodReview:
    date: str
    n_decisions: int
    decisions_made: tuple  # tuple[DecisionSummary, ...], verdict == "play"
    vetoes: tuple  # tuple[VetoGroup, ...]
    grade_cd_share: float  # share of decisions with known_at_grade in C/D
    settlements: tuple  # tuple[SettlementSummary, ...], all accounts, today
    losing_settlements: tuple  # tuple[SettlementSummary, ...], always shown
    accounts: tuple  # tuple[AccountDay, ...]
    n_reviewed: int  # decision/review pairs found at all
    price_vs_close: tuple  # tuple[PriceVsClose, ...]
    scorecard_deltas: tuple  # tuple[ScorecardDelta, ...]
    assumption_exposure_items: tuple  # tuple[AssumptionExposureItem, ...]
    # N2/honesty fix: {provenance: count} over EVERY decision recorded today
    # (play and refusal alike), so a reader sees at a glance how many of
    # today's decisions could ever have contributed an edge/calibration
    # claim (model_derived) versus how many structurally could not.
    provenance_counts: Mapping  # {p_model_provenance: count}
    # docs/PREREG_CALIBRATED_PROBABILITY.md §4/§6: one CalibrationReport per
    # eligible p_model_provenance (model_derived, market_derived) with any
    # decision/review pairs at all -- computed over the FULL decision
    # history handed in as `calibration_decisions` (today's decision volume
    # alone can never clear the >=500-pair, >=9-cluster floor), never
    # gating anything, and never published with a real score below that
    # floor (CalibrationReport.sufficient is False; every score is None).
    calibration_reports: tuple  # tuple[CalibrationReport, ...]
    # ADDITIVE (loss post-mortem, 2026-09-04): pre-rendered markdown from
    # `src.review.postmortem.render_section`, appended verbatim as the report's
    # last section. Defaults to "" so every existing caller and every stored
    # report is byte-identical to before; nothing in this module computes it,
    # and nothing else in the review depends on it.
    postmortem_section: str = ""


_SCORECARD_DELTA_FIELDS = (
    "n_decisions", "n_independent_clusters", "logloss_vs_market", "brier",
    "realized_return", "avg_odds_decimal", "clv_bps_mean", "cscv_pbo",
    "spa_p", "battery_verdict", "effective_tests",
)


def build_review(
    date: str,
    accounts: Sequence[AccountDay],
    decisions: Sequence[DecisionRecord],
    reviews: Sequence[ReviewRecord],
    scorecards: Sequence[Scorecard],
    *,
    calibration_decisions: Optional[Sequence[DecisionRecord]] = None,
    postmortem_section: str = "",
) -> EodReview:
    """Build the deterministic end-of-day self-review for `date`.

    Refuses (`EodReviewError`) when `decisions` is empty -- a day with zero
    recorded decisions has nothing to report, and a report that renders
    anyway would be an empty happy report standing in for an honest refusal.

    `calibration_decisions` (docs/PREREG_CALIBRATED_PROBABILITY.md §4/§6),
    when given, is the FULL decision history (not just `date`'s) the
    calibration section is computed over -- one day's decision volume can
    never clear the >=500-pair, >=9-cluster floor on its own. Defaults to
    `decisions` (today only) for a caller with no fuller history to offer,
    which will almost always report INSUFFICIENT SAMPLE -- an honest
    result, not a bug.
    """
    if not decisions:
        raise EodReviewError(
            f"refusing to build an EOD review for {date}: no decisions "
            "were recorded for this date"
        )

    decisions_made = tuple(sorted(
        (DecisionSummary(
            event_id=d.event_id, market_key=d.market_key,
            selection_id=d.selection_id, price_american=d.price_american,
            edge_bps=d.edge_bps, known_at_grade=d.known_at_grade,
            thesis=d.thesis, p_model_provenance=d.p_model_provenance,
        ) for d in decisions if d.verdict == "play"),
        key=lambda s: s.event_id,
    ))

    veto_groups: dict = {}
    for d in decisions:
        if d.verdict not in REFUSAL_VERDICTS:
            continue
        bucket = veto_groups.setdefault(d.verdict, {"count": 0, "reasons": set()})
        bucket["count"] += 1
        if d.refusal_reason:
            bucket["reasons"].add(d.refusal_reason)
    vetoes = tuple(sorted(
        (VetoGroup(verdict=v, count=b["count"], reasons=tuple(sorted(b["reasons"])))
         for v, b in veto_groups.items()),
        key=lambda g: g.verdict,
    ))

    n_cd = sum(1 for d in decisions if d.known_at_grade in ("C", "D"))
    grade_cd_share = n_cd / len(decisions)

    provenance_counts: dict = {}
    for d in decisions:
        provenance_counts[d.p_model_provenance] = (
            provenance_counts.get(d.p_model_provenance, 0) + 1)

    settlements = tuple(sorted(
        (s for account in accounts for s in account.settlements),
        key=lambda s: (s.system_id, s.bet_id),
    ))
    losing_settlements = tuple(s for s in settlements if s.outcome == LOSS)

    by_key = {decision_key_for(d): d for d in decisions}
    n_reviewed = 0
    price_vs_close: list = []
    for review in reviews:
        decision = by_key.get(review.decision_key)
        if decision is None:
            continue
        n_reviewed += 1
        close_price = (review.market_path or {}).get("close_price")
        if close_price is None or decision.price_american is None:
            continue
        from src.pipeline import snapshots as _snapshots
        value = _snapshots.closing_line_value(decision.price_american, close_price)
        price_vs_close.append(PriceVsClose(
            event_id=decision.event_id, market_key=decision.market_key,
            selection_id=decision.selection_id,
            price_american=decision.price_american, close_price=close_price,
            cents=value["cents"], prob_edge=value["prob_edge"],
            beat_close=value["beat_close"],
        ))
    price_vs_close = tuple(sorted(price_vs_close, key=lambda p: p.event_id))

    # N5/N6 fix: an EOD report FOR `date` must never treat a scorecard
    # window AFTER `date` as "current" (this project's real settle history
    # ran 2026-09-02 before 2026-08-31, so the naive "sort rows by window,
    # take the last" published a 2026-08-31 report whose delta read
    # "2026-08-31 -> 2026-09-02", pulling in a LATER date's numbers as if
    # they were this date's), and a correction row appended for a window
    # that already has one (B4's per-system fix, applied without rewriting
    # ledger history) must supersede the earlier row for that SAME window,
    # never be averaged or duplicated with it. `scorecards` arrives in the
    # chain's own append order, so "last row seen for a window" IS "most
    # recently corrected" by construction.
    by_system: dict = {}
    for sc in scorecards:
        if sc.window > date:
            continue
        by_system.setdefault(sc.system_id, {})[sc.window] = sc
    deltas: list = []
    for system_id, by_window in by_system.items():
        windows_sorted = sorted(by_window)  # distinct windows, chronological
        current = by_window[windows_sorted[-1]]
        previous = (by_window[windows_sorted[-2]]
                   if len(windows_sorted) >= 2 else None)
        field_deltas = {}
        if previous is not None:
            for field_name in _SCORECARD_DELTA_FIELDS:
                prev_value = getattr(previous, field_name)
                curr_value = getattr(current, field_name)
                delta = (curr_value - prev_value) if isinstance(
                    curr_value, (int, float)) and isinstance(
                    prev_value, (int, float)) else None
                field_deltas[field_name] = (prev_value, curr_value, delta)
        deltas.append(ScorecardDelta(
            system_id=system_id, current_window=current.window,
            previous_window=previous.window if previous else None,
            deltas=field_deltas,
        ))
    scorecard_deltas = tuple(sorted(deltas, key=lambda d: d.system_id))

    assumption_items = tuple(sorted(
        (AssumptionExposureItem(event_id=d.event_id,
                                known_at_grade=d.known_at_grade,
                                assumption_exposure=d.assumption_exposure)
         for d in decisions if d.assumption_exposure),
        key=lambda a: a.event_id,
    ))

    calibration_pool = (calibration_decisions if calibration_decisions
                       is not None else decisions)
    calibration_provenances = sorted(
        {d.p_model_provenance for d in calibration_pool}
        & _CALIBRATION_ELIGIBLE_PROVENANCE
    )
    calibration_reports = tuple(
        build_calibration_report(calibration_pool, reviews, provenance=p)
        for p in calibration_provenances
    )

    return EodReview(
        date=date, n_decisions=len(decisions), decisions_made=decisions_made,
        vetoes=vetoes, grade_cd_share=grade_cd_share, settlements=settlements,
        losing_settlements=losing_settlements,
        accounts=tuple(sorted(accounts, key=lambda a: a.system_id)),
        n_reviewed=n_reviewed, price_vs_close=price_vs_close,
        scorecard_deltas=scorecard_deltas,
        assumption_exposure_items=assumption_items,
        provenance_counts=provenance_counts,
        calibration_reports=calibration_reports,
        postmortem_section=postmortem_section or "",
    )


# ---------------------------------------------------------------------------
# Rendering (deterministic)
# ---------------------------------------------------------------------------

def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(review: EodReview) -> str:
    lines = [f"# End-of-day self-review -- {review.date}", ""]

    lines.append(f"Decisions recorded: {review.n_decisions}")
    lines.append(f"Share driven by grade C/D: {_fmt(review.grade_cd_share)}")
    prov_str = ", ".join(
        f"{k}={v}" for k, v in sorted(review.provenance_counts.items()))
    lines.append(f"p_model_provenance breakdown: {prov_str or '(none)'}")
    lines.append(
        "  (only model_derived decisions can carry a non-null edge_bps or "
        "feed a calibration/economic claim -- none, placeholder and "
        "market_derived structurally cannot)"
    )
    lines.append("")

    lines.append("## Decisions made, and why")
    if not review.decisions_made:
        lines.append("No `play` verdicts today.")
    for d in review.decisions_made:
        lines.append(
            f"- {d.event_id} {d.market_key}/{d.selection_id} "
            f"price={d.price_american} edge_bps={d.edge_bps} "
            f"p_model_provenance={d.p_model_provenance} "
            f"grade={d.known_at_grade}: {d.thesis or '(no thesis recorded)'}"
        )
    lines.append("")

    lines.append("## Adversary vetoes by cause")
    if not review.vetoes:
        lines.append("No refused/no-play verdicts today.")
    for v in review.vetoes:
        reasons = "; ".join(v.reasons) if v.reasons else "(no refusal_reason recorded)"
        lines.append(f"- {v.verdict}: {v.count} -- {reasons}")
    lines.append("")

    lines.append("## Settlements")
    if not review.settlements:
        lines.append("No settlements today.")
    for s in review.settlements:
        lines.append(
            f"- [{s.system_id}] {s.bet_id} {s.market_key}/{s.selection_id} "
            f"price={s.price_american} outcome={s.outcome} "
            f"profit_units={_fmt(s.profit_units)}"
        )
    lines.append("")

    # Losers are always shown -- this section is never omitted or filtered.
    lines.append("## Losing bets")
    if not review.losing_settlements:
        lines.append("No losing bets settled today.")
    for s in review.losing_settlements:
        lines.append(
            f"- [{s.system_id}] {s.bet_id} {s.market_key}/{s.selection_id} "
            f"price={s.price_american} profit_units={_fmt(s.profit_units)}"
        )
    lines.append("")

    lines.append("## Price vs. close")
    lines.append(
        f"{len(review.price_vs_close)} of {review.n_reviewed} reviewed "
        "decision(s) had a captured close."
    )
    for p in review.price_vs_close:
        lines.append(
            f"- {p.event_id} {p.market_key}/{p.selection_id}: "
            f"taken={p.price_american} close={p.close_price} "
            f"cents={_fmt(p.cents)} prob_edge={_fmt(p.prob_edge)} "
            f"beat_close={p.beat_close}"
        )
    lines.append("")

    lines.append("## Accounts")
    if not review.accounts:
        lines.append("No paper accounts reported today.")
    for a in review.accounts:
        lines.append(
            f"- {a.system_id}: bankroll={_fmt(a.bankroll)} "
            f"roi_units={_fmt(a.roi_units)} "
            f"drawdown_current={_fmt(a.drawdown_current)} "
            f"drawdown_max={_fmt(a.drawdown_max)} "
            f"n_settled={a.n_settled} (w{a.n_wins}/l{a.n_losses}/"
            f"p{a.n_pushes}/v{a.n_voids})"
        )
    lines.append("")

    lines.append("## Fitness deltas")
    if not review.scorecard_deltas:
        lines.append("No scorecards available.")
    for sd in review.scorecard_deltas:
        if sd.previous_window is None:
            lines.append(
                f"- {sd.system_id} ({sd.current_window}): no prior "
                "scorecard to diff against."
            )
            continue
        lines.append(f"- {sd.system_id}: {sd.previous_window} -> {sd.current_window}")
        for field_name, (prev, curr, delta) in sd.deltas.items():
            delta_str = _fmt(delta) if delta is not None else "n/a"
            lines.append(f"    {field_name}: {_fmt(prev)} -> {_fmt(curr)} ({delta_str})")
    lines.append("")

    lines.append("## Calibration (docs/PREREG_CALIBRATED_PROBABILITY.md §4)")
    if not review.calibration_reports:
        lines.append(
            "No model_derived or market_derived decision exists yet -- "
            "nothing to measure."
        )
    for cr in review.calibration_reports:
        lines.append(f"### provenance={cr.provenance}")
        if not cr.sufficient:
            lines.append(
                f"INSUFFICIENT SAMPLE: {cr.n_pairs} decision/review pair(s) "
                f"(need >= {cr.required_pairs}) across {cr.n_clusters} "
                f"independent 7-day cluster(s) (need >= "
                f"{cr.required_clusters}). No calibration claim published."
            )
            continue
        lines.append(
            f"n_pairs={cr.n_pairs} n_clusters={cr.n_clusters} "
            f"log_loss={_fmt(cr.log_loss)} brier={_fmt(cr.brier)} "
            f"ece={_fmt(cr.ece)} max_ce={_fmt(cr.max_ce)} "
            f"mean_predicted={_fmt(cr.mean_predicted)} "
            f"observed_rate={_fmt(cr.observed_rate)}"
        )
        lines.append(
            "Baselines -- de-vigged consensus on these games: delta="
            f"{_fmt(cr.baseline_market_delta_log_loss)}; "
            f"base_rate: log_loss={_fmt(cr.baseline_base_rate_log_loss)} "
            f"brier={_fmt(cr.baseline_base_rate_brier)}; "
            f"Phase 2A 2024 reference (context only, not a live comparison): "
            f"log_loss={cr.baseline_phase2a_log_loss} "
            f"brier={cr.baseline_phase2a_brier}"
        )
        lines.append("Reliability, fixed-width bins:")
        lines.append(calibration_module.format_reliability_curve(
            cr.reliability_fixed_width))
        lines.append("Reliability, equal-count (decile) bins:")
        lines.append(calibration_module.format_reliability_curve(
            cr.reliability_equal_count))
    lines.append("")

    lines.append("## What the engine did not know")
    if not review.assumption_exposure_items:
        lines.append("No decision today recorded a non-empty assumption_exposure.")
    for item in review.assumption_exposure_items:
        lines.append(f"- {item.event_id} (grade {item.known_at_grade}):")
        for key in sorted(item.assumption_exposure):
            lines.append(f"    {key}: {item.assumption_exposure[key]}")
    lines.append("")

    if review.postmortem_section:
        lines.append(review.postmortem_section.rstrip("\n"))
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The thin writer
# ---------------------------------------------------------------------------

def write_review(
    date: str,
    accounts: Sequence[AccountDay],
    decisions: Sequence[DecisionRecord],
    reviews: Sequence[ReviewRecord],
    scorecards: Sequence[Scorecard],
    *,
    docs_dir: Optional[Path] = None,
    chain_path: Optional[str] = None,
    calibration_decisions: Optional[Sequence[DecisionRecord]] = None,
    postmortem_section: str = "",
) -> dict:
    """Build, render, write `docs/eod/DATE.md`, and append a summary row to
    the EOD review chain. Raises `EodReviewError` (writes nothing) when
    `date` has no decisions -- the CLI is expected to let that propagate as
    an honest refusal rather than catching it into an empty report."""
    review = build_review(date, accounts, decisions, reviews, scorecards,
                          calibration_decisions=calibration_decisions,
                          postmortem_section=postmortem_section)
    markdown = render_markdown(review)

    target_dir = Path(docs_dir) if docs_dir is not None else repo_root() / "docs" / "eod"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{date}.md"
    out_path.write_text(markdown, encoding="utf-8")

    report_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    ledger = HashChainLedger(chain_path or str(EOD_REVIEW_LEDGER_PATH))
    chain_row = ledger.append({
        "date": date,
        "report_sha256": report_sha256,
        "report_path": str(out_path),
        "n_decisions": review.n_decisions,
        "n_play": len(review.decisions_made),
        "n_vetoes": sum(v.count for v in review.vetoes),
        "n_settlements": len(review.settlements),
        "n_losses": len(review.losing_settlements),
        "n_accounts": len(review.accounts),
        "grade_cd_share": review.grade_cd_share,
        "provenance_counts": dict(review.provenance_counts),
        "calibration_sufficient": {
            cr.provenance: cr.sufficient for cr in review.calibration_reports
        },
    })

    return {"review": review, "markdown": markdown, "path": str(out_path),
            "chain_row": chain_row}
