"""The one living business dashboard: docs/SURVIVAL_DASHBOARD.md.

Deterministic. Computes what the repo can know (days left, the cost table
and break-even, the public record by sport and market, the outreach funnel)
and prints what a person must supply (revenue until production's admin route
is read, the Claude cost) as UNKNOWN or "not set" rather than guessing.

Every funnel count is read from docs/sales/outreach_queue.csv, one row per
LEAD, counted by distinct lead_id: a reply, a signup or a payment updates a
lead's row and can never add a lead, so no person is counted twice. A rate is
printed only from a non-zero denominator.

    python scripts/survival_dashboard.py            # writes the file
    python scripts/survival_dashboard.py --stdout   # prints it

Inputs: config/business.json (costs, offers, blockers, next actions),
docs/sales/outreach_queue.csv (leads), docs/sales/pipeline.csv (payment
amounts, from `paid` events), the card ledgers through src.report.effective_record.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "config" / "business.json"
PIPELINE = ROOT / "docs" / "sales" / "pipeline.csv"
QUEUE = ROOT / "docs" / "sales" / "outreach_queue.csv"
OUT = ROOT / "docs" / "SURVIVAL_DASHBOARD.md"

STAGES = ("sent", "replied", "demo", "trial", "paid", "lost")


def _money(value) -> str:
    return "UNKNOWN" if value is None else f"${value:,.2f}"


def cost_summary(config: dict) -> dict:
    known = sum(c["usd"] for c in config["costs_monthly"] if c["usd"] is not None and c["known"])
    estimated = sum(c["usd"] for c in config["costs_monthly"] if c["usd"] is not None and not c["known"])
    unknown = [c["item"] for c in config["costs_monthly"] if c["usd"] is None]
    planning = known + estimated + (config.get("claude_planning_assumption_usd") or 0.0)
    return {"known": known, "estimated": estimated, "unknown_items": unknown,
            "infra_total": known + estimated, "planning_total": planning}


def break_even(total: float, offers: list) -> list:
    return [(o["name"], o["price_usd"], math.ceil(total / o["net_after_stripe_usd"]))
            for o in offers]


def pipeline_counts(path: Path = PIPELINE) -> dict:
    """Leads, and where each one stands NOW.

    The pipeline file is an append-only history: `outreach_batch.py reply`
    adds a new row when a target moves from sent to replied to paid. So a
    lead is a distinct target, its stage is the stage on its LAST row, and
    its revenue is the revenue on that row. Counting rows would have shown 23
    leads for 20 people after three replies, and a lower conversion rate than
    the true one. `rows` is the number of distinct targets; `reached` counts
    every target that ever reached a stage (a paid customer also replied)."""
    latest: dict = {}
    reached = {s: set() for s in STAGES}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                target = " ".join((row.get("target") or "").casefold().split())
                if not target:
                    continue
                latest[target] = row
                stage = (row.get("stage") or "").strip().lower()
                if stage in reached:
                    reached[stage].add(target)
    counts = {s: 0 for s in STAGES}
    revenue = 0.0
    for row in latest.values():
        stage = (row.get("stage") or "").strip().lower()
        if stage in counts:
            counts[stage] += 1
        try:
            revenue += float(row.get("revenue") or 0)
        except ValueError:
            pass
    return {"rows": len(latest), "counts": counts, "revenue": revenue,
            "reached": {s: len(names) for s, names in reached.items()}}


MIN_N_FOR_A_RATE = 30


def _fig(fig) -> str:
    if not fig or not (fig.get("n_staked") or fig.get("wins") or fig.get("losses")):
        return "nothing graded"
    units = fig.get("profit_units") or 0.0
    staked = fig.get("n_staked") or 0
    # The sample size leads, and a rate is printed only where it could mean
    # something: "ROI +92.6%" off one NFL pick and "+41.7%" off six UFC picks
    # were both on this page, each flattering and neither a measurement. The
    # floor is the one docs/VALUE_SCAN.md uses for TOO FEW.
    record = f"n={staked}: {fig.get('wins', 0)}-{fig.get('losses', 0)}, {units:+.2f}u"
    if staked < MIN_N_FOR_A_RATE:
        return f"{record} (too few for a rate)"
    return f"{record}, ROI {units / staked * 100:+.1f}%"


def record_lines() -> list:
    lines = []
    try:
        from src.report import effective_record
        sports = effective_record.build().get("sports") or {}
    except Exception as exc:  # the dashboard must still render
        return [f"- record unavailable: {type(exc).__name__}: {exc}"]
    for sport, snap in sports.items():
        for role in ("current", "previous"):
            cohort = (snap or {}).get(role)
            if not cohort:
                continue
            span = cohort.get("date_span") or {}
            when = f"{span.get('first')}..{span.get('last')}" if span else "no dates"
            label = cohort.get("label") or cohort.get("rule_id") or role
            lines.append(f"- **{sport.upper()} {role}** ({label}; {when}): {_fig(cohort)}")
            for market, fig in sorted((cohort.get("market_breakdown") or {}).items()):
                if fig and (fig.get("n_staked") or 0) > 0:
                    lines.append(f"  - {market}: {_fig(fig)}")
            fills = cohort.get("fills")
            if fills and (fills.get("n_staked") or 0) > 0:
                lines.append(f"  - fills (shown apart, never counted): {_fig(fills)}")
            post = cohort.get("postseason")
            if post and (post.get("n_staked") or 0) > 0:
                lines.append(f"  - postseason (graded, not counted): {_fig(post)}")
    return lines or ["- no ledgers found"]


def savings(config: dict) -> list:
    """(item, usd, label) for each costs_monthly item that carries a `saving_usd`."""
    return [(c["item"], c["saving_usd"], c.get("saving_label") or "see the note in the costs table")
            for c in config["costs_monthly"] if c.get("saving_usd") is not None]


def _action(config: dict, key: str) -> str:
    return (config.get(key) or "").strip() or "not set"


def _load_queue(queue_rows, pipeline_rows) -> tuple:
    """(queue_rows, pipeline_rows, note). Tests inject both; production reads the files."""
    from scripts import outreach_batch as ob
    note = ""
    if queue_rows is None:
        try:
            queue_rows = ob.read_queue(QUEUE, must_exist=False)
        except ob.OutreachError as exc:
            queue_rows, note = [], f"queue unreadable: {exc}"
        if not QUEUE.exists():
            note = "docs/sales/outreach_queue.csv not found; run `python scripts/outreach_batch.py seed`"
    if pipeline_rows is None:
        pipeline_rows = ob.read_pipeline(PIPELINE)[1]
    return queue_rows, pipeline_rows, note


def render(config: dict, today: date, now_utc: str, queue_rows: list = None,
           pipeline_rows: list = None, record: list = None) -> str:
    from scripts import outreach_batch as ob
    deadline = date.fromisoformat(config["deadline"])
    costs = cost_summary(config)
    queue_rows, pipeline_rows, queue_note = _load_queue(queue_rows, pipeline_rows)
    q = ob.queue_counts(queue_rows)
    revenue_total, revenue_unknown = ob.queue_revenue(queue_rows, pipeline_rows)
    rev = config.get("revenue") or {}
    mrr = rev.get("mrr_usd") or 0.0
    paid = q["paid"]
    if q["sent"]:
        conv = f"{paid / q['sent'] * 100:.1f}% ({paid} of {q['sent']} leads sent)"
    else:
        conv = "n/a (no lead has been sent a message yet)"
    saves = savings(config)
    out = []
    out.append("# LineHound survival dashboard")
    out.append("")
    out.append(f"Generated {now_utc} by `scripts/survival_dashboard.py`. Edit `config/business.json` "
               "and log outreach with `scripts/outreach_batch.py`, not this file.")
    out.append("")
    out.append("| | |")
    out.append("|---|---|")
    out.append(f"| Days until {deadline.isoformat()} | **{(deadline - today).days}** |")
    out.append(f"| Current monthly burn (known + estimated infrastructure) | {_money(costs['infra_total'])} |")
    out.append(f"| Current monthly burn incl. Claude at the planning assumption | {_money(costs['planning_total'])} "
               f"(unknown: {', '.join(costs['unknown_items']) or 'none'}) |")
    if saves:
        total = sum(usd for _, usd, _ in saves)
        listing = "; ".join(f"{item}: {_money(usd)} ({label})" for item, usd, label in saves)
        out.append(f"| Identified monthly savings (not yet realised) | {_money(total)}: {listing} |")
    else:
        out.append("| Identified monthly savings (not yet realised) | none identified "
                   "(no costs_monthly item has a saving_usd) |")
    if paid == 0:
        revenue_text = "none logged (no `paid` lead in the queue)"
    elif revenue_unknown and not revenue_total:
        revenue_text = f"UNKNOWN ({revenue_unknown} payment(s) logged without a revenue figure)"
    elif revenue_unknown:
        revenue_text = (f"{_money(revenue_total)} plus {revenue_unknown} payment(s) logged "
                        "without a revenue figure")
    else:
        revenue_text = _money(revenue_total)
    out.append(f"| Revenue (payments logged in the queue) | {revenue_text} |")
    out.append(f"| MRR (config, manual: {rev.get('source') or 'no source stated'}) | {_money(mrr)} |")
    out.append(f"| Unique leads | {q['leads']} |")
    out.append(f"| Messages sent | {q['sent']} |")
    auto = f" (plus {q['auto_replies']} auto-reply, not counted)" if q["auto_replies"] else ""
    out.append(f"| Replies | {q['replies']}{auto} |")
    out.append(f"| Signups | {q['signups']} |")
    out.append(f"| Active users | {q['activated']} |")
    out.append(f"| People who said they would pay | {q['would_pay']} |")
    cfg_paid = rev.get("paying_customers") or 0
    stale = f" (config says {cfg_paid}; they are not in the queue, log them with `paid`)" if cfg_paid > paid else ""
    out.append(f"| Paid customers | {paid}{stale} |")
    out.append(f"| Conversion rate (paid / leads sent) | {conv} |")
    out.append("| CAC | $0 spent on acquisition |")
    out.append(f"| Gap to break-even | {_money(max(costs['planning_total'] - mrr, 0.0))} per month |")
    out.append("")
    notes = []
    if queue_note:
        notes.append(queue_note)
    if q["duplicate_rows"]:
        notes.append(f"{q['duplicate_rows']} repeated lead_id row(s) in the queue were merged, not counted")
    out.extend(f"> {n}" for n in notes)
    if notes:
        out.append("")
    out.append("## Milestones (first timestamp of each, UTC)")
    out.append("")
    out.extend(f"- {line}" for line in ob.milestone_lines(queue_rows))
    out.append("")
    out.append("## Current sports")
    out.append("")
    out.extend(f"- {s}" for s in config.get("active_sports", []))
    out.append("")
    out.append("## Performance by market (counted picks; never pooled) and CLV")
    out.append("")
    out.extend(record if record is not None else record_lines())
    out.append("")
    out.append("Closing-line value: see `docs/VALUE_SCAN.md` (the standing measurement; no CLV figure "
               "is computed or copied here). No rule here has evidence of an edge.")
    out.append("")
    out.extend(f"- {item}" for item in config.get("record_reading", []))
    out.append("")
    out.append("## Production health and capture cost")
    out.append("")
    out.append(f"- Production health: {(config.get('production_health') or '').strip() or 'see docs/audit'}")
    out.append(f"- Capture cost: {(config.get('capture_cost') or '').strip() or 'see docs/audit'}")
    out.append("")
    out.append("## Top 3 blockers")
    out.append("")
    out.extend(f"{n}. {item}" for n, item in enumerate(config.get("top_blockers", [])[:3], start=1))
    out.append("")
    out.append("## Next actions")
    out.append("")
    out.append(f"- **Owner:** {_action(config, 'next_owner_action')}")
    out.append(f"- **Customer:** {_action(config, 'next_customer_action')}")
    out.append(f"- **Product:** {_action(config, 'next_product_action')}")
    out.append(f"- **Model:** {_action(config, 'next_research_action')}")
    out.append("")
    out.append("## What survival requires")
    out.append("")
    for name, price, n in break_even(costs["infra_total"], config["offers"]):
        out.append(f"- Infrastructure only ({_money(costs['infra_total'])}): {n} x {name} at ${price:,.2f}")
    for name, price, n in break_even(costs["planning_total"], config["offers"]):
        out.append(f"- Everything incl. Claude ({_money(costs['planning_total'])}): {n} x {name} at ${price:,.2f}")
    out.append("")
    out.append("## Costs and the kill list")
    out.append("")
    out.append("| Item | Monthly | Verdict | Note |")
    out.append("|---|---|---|---|")
    for c in config["costs_monthly"]:
        amount = _money(c["usd"]) + ("" if c["known"] or c["usd"] is None else " (est.)")
        out.append(f"| {c['item']} | {amount} | {c['class']} | {c['note']} |")
    out.append("")
    rest = config.get("top_blockers", [])[3:]
    for title, items in (("Product errors", config.get("product_errors", [])),
                         ("Other blockers", rest), ("Today's execution", config.get("today", []))):
        if not items:
            continue
        out.append(f"## {title}")
        out.append("")
        out.extend(f"- {item}" for item in items)
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--today", default=None, help="YYYY-MM-DD (tests)")
    args = parser.parse_args(argv)
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    text = render(config, today, now_utc)
    if args.stdout:
        sys.stdout.write(text + "\n")
    else:
        OUT.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
