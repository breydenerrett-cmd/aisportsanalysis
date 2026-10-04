"""The one living business dashboard: docs/SURVIVAL_DASHBOARD.md.

Deterministic. Computes what the repo can know (days left, the cost table
and break-even, the public record by sport and market, the outreach funnel)
and prints what a person must supply (revenue until production's admin route
is read, the Claude cost) as UNKNOWN or "not set" rather than guessing.

Every customer count is read from docs/sales/outreach_queue.csv (schema v2),
counted by distinct lead_id over PERSON rows only: a channel post is a public
thread, not a human, and a person who was only queued has not been contacted,
so neither is a lead. A reply, a signup or a payment updates a person's row and
can never add one, and `outreach_batch.py add` refuses a handle that already
belongs to a lead, so no human is counted twice. A rate prints as
"n of d (pct)", says "no rate yet" from a zero denominator and "small sample"
under 30. The repository is public: nothing private is read or written here.

    python scripts/survival_dashboard.py            # writes the file
    python scripts/survival_dashboard.py --stdout   # prints it

Inputs: config/business.json (costs, offers, blockers, next actions, and the
optional `tester_activity` object the owner pastes from the product),
docs/sales/outreach_queue.csv (leads), docs/sales/pipeline.csv (payment
amounts, from `paid` events), the card ledgers through src.report.effective_record.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.appstate.testers import TESTER_ACCESS_TTL, TESTER_LIMIT  # noqa: E402  (needs the path line above)

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


def _rate(num: int, den: int) -> str:
    """`n of d (pct)`; `0 of 0 (no rate yet)` from a zero denominator; ", small sample"
    when the denominator is under MIN_N_FOR_A_RATE."""
    if den <= 0:
        return f"{num} of 0 (no rate yet)"
    text = f"{num} of {den} ({num / den * 100:.1f}%)"
    return text + (", small sample" if den < MIN_N_FOR_A_RATE else "")


def _count(value):
    """A whole number of at least zero, else None (a bool is not a count)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def tester_activity(config: dict) -> tuple:
    """(activity, problems). `activity` is None when config has no `tester_activity` object;
    otherwise as_of, the four counts (None when missing or not a whole number), the median
    hours (None when missing) and feature_users as an ordered {name: count}. The owner pastes
    this from the product's admin page; this script never calls production."""
    raw = config.get("tester_activity")
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["config tester_activity is not an object; ignored"]
    problems = []
    out = {"as_of": str(raw.get("as_of") or "").strip()}
    for key in ("testers_granted", "testers_in_window", "activated", "returning"):
        out[key] = _count(raw.get(key))
        if raw.get(key) is not None and out[key] is None:
            problems.append(f"config tester_activity.{key} is not a whole number; ignored")
    median = raw.get("median_hours_signup_to_activation")
    ok = isinstance(median, (int, float)) and not isinstance(median, bool) \
        and math.isfinite(median) and median >= 0
    out["median_hours_signup_to_activation"] = median if ok else None
    if median is not None and not ok:
        problems.append("config tester_activity.median_hours_signup_to_activation is not a number; ignored")
    features = raw.get("feature_users")
    out["feature_users"] = {}
    if isinstance(features, dict):
        for name, users in features.items():
            if _count(users) is None:
                problems.append(f"config tester_activity.feature_users[{name!r}] is not a whole number; ignored")
            else:
                out["feature_users"][str(name)] = users
    elif features is not None:
        problems.append("config tester_activity.feature_users is not an object; ignored")
    # Features the product cannot measure yet (no route serves them as the page a person
    # chose). Their 0 is not "nobody used it", so the table says so instead of printing it.
    unmeasured = raw.get("unmeasured_features")
    out["unmeasured_features"] = [str(n) for n in unmeasured] if isinstance(unmeasured, list) else []
    return out, problems


def _now(today: date, now_utc: str, now: datetime = None) -> datetime:
    """The clock the 7-day tester window is read against: the injected one, else the stamp the
    page is generated with, else midnight of `today`."""
    if now is not None:
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    try:
        return datetime.strptime(now_utc, "%Y-%m-%d %H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.combine(today, time(0, 0), tzinfo=timezone.utc)


def customer_section(q: dict, revenue_text: str, activity: dict = None) -> list:
    """The customer rows: always every row, zeros shown, each with a one-line definition."""
    from_product = lambda key: activity is not None and activity.get(key) is not None
    as_of = (activity or {}).get("as_of") or "an unstated date"
    if from_product("activated"):
        activated = f"{activity['activated']} (from the product, as of {as_of})"
        activated_def = ("Testers who opened real product content while signed in (a card, a game "
                         "breakdown, the props), not just signed in. Counted by the product.")
    else:
        activated = f"{q['activated']} (from the outreach log)"
        activated_def = "People with an `activated` entry in the outreach log."
    if from_product("returning"):
        returning = f"{activity['returning']} (from the product, as of {as_of})"
        returning_def = ("Activated testers who used it again 12 hours or more after their first "
                         "use. Counted by the product.")
    else:
        returning = "0 (not measured yet)"
        returning_def = ("Activated testers who used it again 12 hours or more after their first use; "
                         "needs `tester_activity` in config.")
    spam = f" ({q['replies_spam']} of them spam or irrelevant)" if q["replies_spam"] else ""
    out = ["| Measure | Value | What it counts |", "|---|---|---|"]
    out.append(f"| UNIQUE LEADS | {q['leads']} | People (not channel posts) who were sent a message, replied "
               "or signed up. Queued people nobody has contacted are not counted. |")
    out.append(f"| MESSAGES SENT | {q['sent']} | Rows of any kind with a send logged, so a thread posted "
               "counts here. |")
    out.append(f"| REPLIES | {q['replies']}{spam} | People with a reply logged. |")
    out.append(f"| POSITIVE REPLIES | {q['positive']} | People whose reply type is POSITIVE_INTEREST, "
               "SIGNED_UP, ACTIVE_TESTER or WOULD_PAY. |")
    out.append(f"| SIGNUPS | {q['signups']} | People with a signup logged. |")
    out.append(f"| ACTIVE TESTERS | {q['active_testers']} | People whose tester access was granted less than "
               f"{TESTER_ACCESS_TTL.days} days ago. |")
    out.append(f"| ACTIVATED USERS | {activated} | {activated_def} |")
    out.append(f"| RETURNING USERS | {returning} | {returning_def} |")
    out.append(f"| WOULD PAY | {q['would_pay_yes']} ({q['would_pay_no']} said no) | People who said yes to "
               "paying; the number who said no is beside it. |")
    out.append(f"| PAID USERS | {q['paid']} | People with a payment logged. |")
    out.append(f"| REVENUE | {revenue_text} | Revenue figures from `paid` events for those people; nothing is "
               "estimated. |")
    out.append("")
    out.append(f"- queued, not yet contacted: {q['queued']} (people in the queue with no message, reply or "
               "signup; not leads)")
    out.append(f"- channel posts made: {q['channel_posts_made']} (forum threads posted; a thread is not a "
               "human, so it is not a lead)")
    out.append("")
    out.append("| Rate | Value | Definition |")
    out.append("|---|---|---|")
    out.append(f"| Reply rate | {_rate(q['replied_after_sent'], q['sent_persons'])} | People sent a message "
               "who replied, of people sent a message. |")
    out.append(f"| Signup rate | {_rate(q['signups'], q['leads'])} | Signups of unique leads. |")
    out.append(f"| Activation rate | {_rate(q['activated'], q['signups'])} | Activated of signups, both from the "
               "outreach log so they are the same people. |")
    out.append(f"| Would-pay rate | {_rate(q['would_pay_yes'], q['would_pay_yes'] + q['would_pay_no'])} | "
               "Yes of everyone who answered yes or no. |")
    out.append(f"| Paid conversion | {_rate(q['paid'], q['leads'])} | Paid users of unique leads. |")
    if activity is not None:
        out.append("")
        out.append(f"### Tester activity (from the product, as of {as_of})")
        out.append("")
        granted = activity.get("testers_granted")
        window = activity.get("testers_in_window")
        median = activity.get("median_hours_signup_to_activation")
        out.append("- testers granted: " + (f"{granted} of {TESTER_LIMIT}" if granted is not None else "not stated"))
        out.append("- testers inside their 7 days: " + (str(window) if window is not None else "not stated"))
        out.append("- median hours from signup to activation: "
                   + (f"{median:g}" if median is not None else "not measured yet"))
        features = activity.get("feature_users") or {}
        if features:
            out.append("")
            out.append("| Feature | Testers who used it |")
            out.append("|---|---|")
            unmeasured = set(activity.get("unmeasured_features") or [])
            out.extend(f"| {name} | {'not measured yet' if name in unmeasured else users} |"
                       for name, users in features.items())
    return out


def render(config: dict, today: date, now_utc: str, queue_rows: list = None,
           pipeline_rows: list = None, record: list = None, now: datetime = None) -> str:
    from scripts import outreach_batch as ob
    deadline = date.fromisoformat(config["deadline"])
    costs = cost_summary(config)
    queue_rows, pipeline_rows, queue_note = _load_queue(queue_rows, pipeline_rows)
    q = ob.queue_counts(queue_rows, _now(today, now_utc, now), TESTER_ACCESS_TTL)
    revenue_total, revenue_unknown = ob.queue_revenue(queue_rows, pipeline_rows)
    activity, activity_problems = tester_activity(config)
    rev = config.get("revenue") or {}
    mrr = rev.get("mrr_usd") or 0.0
    paid = q["paid"]
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
    out.append(f"| MRR (config, manual: {rev.get('source') or 'no source stated'}) | {_money(mrr)} |")
    # Early-access testers are granted by hand from the admin page, and this
    # script never calls production: the row exists only when the owner has put
    # the count in config/business.json (`testers_granted`, an integer).
    testers = config.get("testers_granted")
    if isinstance(testers, int) and not isinstance(testers, bool):
        out.append(f"| Testers granted | {testers} of {TESTER_LIMIT} (config, owner-updated) |")
    out.append("| CAC | $0 spent on acquisition |")
    out.append(f"| Gap to break-even | {_money(max(costs['planning_total'] - mrr, 0.0))} per month |")
    out.append("")
    notes = []
    if queue_note:
        notes.append(queue_note)
    if q["duplicate_rows"]:
        notes.append(f"{q['duplicate_rows']} repeated lead_id row(s) in the queue were merged, not counted")
    cfg_paid = rev.get("paying_customers") or 0
    if cfg_paid > paid:
        notes.append(f"config says {cfg_paid} paying customer(s); only {paid} are in the queue "
                     "(log the rest with `paid`)")
    notes.extend(activity_problems)
    out.append("## Customer discovery")
    out.append("")
    out.append("Read from `docs/sales/outreach_queue.csv`, people only. A forum thread is a public post, not a "
               "human, and a queued person nobody has contacted is not a lead.")
    out.append("")
    out.extend(customer_section(q, revenue_text, activity))
    out.append("")
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
    # Basis is actual (an invoice or the account says so), estimated, or unknown. Nothing here is
    # read from an invoice unless its evidence says so; an amount is never promoted to "actual" by
    # a default in the code.
    out.append("| Item | Monthly | Basis | Kind | Evidence | Verdict | Note |")
    out.append("|---|---|---|---|---|---|---|")
    for c in config["costs_monthly"]:
        amount = _money(c["usd"]) + ("" if c["known"] or c["usd"] is None else " (est.)")
        basis = c.get("basis") or ("unknown" if c["usd"] is None else "actual" if c["known"] else "estimated")
        out.append(f"| {c['item']} | {amount} | {basis} | {c.get('kind') or ''} | {c.get('evidence') or ''} "
                   f"| {c['class']} | {c['note']} |")
    out.append("")
    individual = next((o for o in config.get("offers", []) if o.get("price_usd") == 19.99), None)
    if individual:
        net = individual["net_after_stripe_usd"]
        out.append(f"Contribution per paying subscriber: ${net:,.2f} a month (${individual['price_usd']:,.2f} "
                   "less Stripe's fees). No other cost rises with each subscriber: the analysis is written "
                   "once per game, not once per customer.")
    for label, text in (config.get("analyst_costs") or {}).items():
        out.append(f"- {label.replace('_', ' ')}: {text}")
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
    now = datetime.now(timezone.utc)
    now_utc = now.strftime("%Y-%m-%d %H:%MZ")
    text = render(config, today, now_utc, now=now)
    if args.stdout:
        sys.stdout.write(text + "\n")
    else:
        OUT.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
