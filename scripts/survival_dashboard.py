"""The one living business dashboard: docs/SURVIVAL_DASHBOARD.md.

Deterministic. Computes what the repo can know (days left, the cost table
and break-even, the public record by sport and market, the sales pipeline
counts) and prints what a person must supply (revenue until production's
admin route is read, the Claude cost) as UNKNOWN rather than guessing.

    python scripts/survival_dashboard.py            # writes the file
    python scripts/survival_dashboard.py --stdout   # prints it

Inputs: config/business.json (costs, offers, blockers, today's queue),
docs/sales/pipeline.csv (leads), the card ledgers through
src.report.effective_record.
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
    counts = {s: 0 for s in STAGES}
    revenue = 0.0
    rows = 0
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if not (row.get("target") or "").strip():
                    continue
                rows += 1
                stage = (row.get("stage") or "").strip().lower()
                if stage in counts:
                    counts[stage] += 1
                try:
                    revenue += float(row.get("revenue") or 0)
                except ValueError:
                    pass
    return {"rows": rows, "counts": counts, "revenue": revenue}


def _fig(fig) -> str:
    if not fig or not (fig.get("n_staked") or fig.get("wins") or fig.get("losses")):
        return "nothing graded"
    units = fig.get("profit_units") or 0.0
    staked = fig.get("n_staked") or 0
    roi = f"{units / staked * 100:+.1f}%" if staked else "n/a"
    return f"{fig.get('wins', 0)}-{fig.get('losses', 0)}, {units:+.2f}u, ROI {roi} (n={staked})"


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


def render(config: dict, today: date, now_utc: str) -> str:
    deadline = date.fromisoformat(config["deadline"])
    costs = cost_summary(config)
    pipe = pipeline_counts()
    rev = config.get("revenue") or {}
    mrr = rev.get("mrr_usd") or 0.0
    leads = pipe["rows"]
    paid = max(pipe["counts"]["paid"], rev.get("paying_customers") or 0)
    conv = f"{paid / leads * 100:.1f}%" if leads else "n/a (no leads yet)"
    out = []
    out.append("# LineHound survival dashboard")
    out.append("")
    out.append(f"Generated {now_utc} by `scripts/survival_dashboard.py`. Edit `config/business.json` "
               "and `docs/sales/pipeline.csv`, not this file.")
    out.append("")
    out.append("| | |")
    out.append("|---|---|")
    out.append(f"| Days until {deadline.isoformat()} | **{(deadline - today).days}** |")
    out.append(f"| Monthly cost (known + estimated infrastructure) | {_money(costs['infra_total'])} |")
    out.append(f"| Monthly cost incl. Claude at the planning assumption | {_money(costs['planning_total'])} "
               f"(unknown: {', '.join(costs['unknown_items']) or 'none'}) |")
    out.append(f"| Revenue (MRR) | {_money(mrr)} |")
    out.append(f"| Paying customers | {paid} |")
    out.append(f"| Trials | {max(pipe['counts']['trial'], rev.get('trials') or 0)} |")
    out.append(f"| Leads contacted | {leads} (replied {pipe['counts']['replied']}, demo {pipe['counts']['demo']}, lost {pipe['counts']['lost']}) |")
    out.append(f"| Lead to paid conversion | {conv} |")
    out.append("| CAC | $0 spent on acquisition |")
    out.append(f"| Gap to break-even | {_money(max(costs['planning_total'] - mrr, 0.0))} per month |")
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
    out.append("## Active sports")
    out.append("")
    out.extend(f"- {s}" for s in config.get("active_sports", []))
    out.append("")
    out.append("## Public record by sport and market (counted picks; never pooled)")
    out.append("")
    out.extend(record_lines())
    out.append("")
    out.append("No rule here has evidence of an edge. Closing-line value and calibration: "
               "see `docs/audit/` for the latest loss diagnosis.")
    out.append("")
    for title, key in (("Product errors", "product_errors"), ("Top blockers", "top_blockers"),
                       ("Today's execution", "today")):
        out.append(f"## {title}")
        out.append("")
        out.extend(f"- {item}" for item in config.get(key, []))
        out.append("")
    out.append(f"**Next customer action:** {config.get('next_customer_action', '')}")
    out.append("")
    out.append(f"**Next research action:** {config.get('next_research_action', '')}")
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
