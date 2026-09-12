"""Does any book even offer `batter_stolen_bases`, and who?

THE QUESTION, AND WHY IT COMES BEFORE ANY SPEND
-------------------------------------------------
docs/DECISION_PROP_CAPTURE_SPEND.md (owner approved, 2026-09-12) called this
"probe-then-capture": batter_props.py can now request `batter_stolen_bases`
alongside its six measured markets (STOLEN_BASES=1, off by default -- see
that flag's docstring in src/pipeline/batter_props.py), but nothing should
capture it on a schedule until two things are actually known -- does the
provider list this market at all, and if so, how many books quote it and how
thin is the payload. Both are unmeasured. This script measures them, once,
for the smallest possible spend, and reports; it decides nothing and starts
no ongoing capture on its own.

WHAT THIS SPENDS
-----------------
Two calls: `list_events` (free -- the /events endpoint costs 0 credits) to
find one pre-game event with enough lead time that its markets have not
started thinning near first pitch, then ONE fetch of THAT event asking for
`batter_stolen_bases` and nothing else -- one market, the account's default
single region, so the worst case is a handful of credits (see
WORST_CASE_CREDITS below) and the measured cost, once the response headers
are read, is almost certainly less. Every credit-relevant read
(preflight quota, the priced fetch, postflight quota) is logged through
`pipeline.creditlog` under the PROBE band (`src.capture.budget.PROBE`), the
same band `budget.probe_family` uses for exactly this reason: this spend
must never be misread as LIVE_CAPTURE and count against the 900/day
envelope `batter_props.run` is gated by.

WHAT THIS DOES NOT DO
-----------------------
It writes NO row to any capture store -- not `data/processed/batter_props*`,
not `config/capture_families.json`. This is a feasibility read, the same
line `src/pipeline/prop_listing.py`'s own module docstring draws for the
pitcher-strikeouts listing audit: whether a market is LISTED is not a price
history, and recording one here would make this probe an unapproved capture
surface wearing a probe's label. The only artefact is a JSON report under
`evidence/`, exactly like every other probe script in this directory.

It never runs on a schedule. `scripts/reachability_audit.py`'s
DECLARED_MANUAL_SCRIPTS carries this file with the same reasoning every
other probe script in that list gets: a probe answers one question a human
is currently asking, and a probe on a schedule is a probe nobody reads.

NOT EXECUTED BY THIS CHANGE. Zero live credits spent by writing this file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture import budget as budget_module  # noqa: E402
from src.pipeline import creditlog  # noqa: E402
from src.providers import odds as odds_provider  # noqa: E402

CALLER = "probe_stolen_bases"
MARKET = "batter_stolen_bases"
MARKETS = (MARKET,)

# Same margin `budget.probe_family` uses and the same reason: a probe against
# an event whose commence_time has already passed or is about to returns a
# payload thinned by books pulling their lines as the game starts, which
# would misreport "not offered" for a market a book simply pulled early.
MIN_LEAD_MINUTES = budget_module.PROBE_MIN_LEAD_MINUTES

# One market, one region -- the account's default billing shape for a
# per-event fetch is markets x regions, so the honest worst case here is 1
# credit. Padded to 3 so a provider quirk (a market billed at more than 1
# credit, or a second region sneaking in from ODDS_API_REGION) still trips
# the floor/envelope guards below rather than silently exceeding them --
# still "a handful of credits", never the multi-market batter_props shape.
WORST_CASE_CREDITS = 3


def _load_dotenv(path) -> None:
    """Same reader every probe script in this directory uses: values already
    exported win, nothing printed."""
    env_file = Path(path)
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _eligible_event(listed, now, min_lead_minutes=MIN_LEAD_MINUTES):
    """The earliest listed event at least `min_lead_minutes` from first
    pitch, ties broken by event id -- deterministic, matching
    `budget.probe_family`'s own selection rule and for the same reason: a
    probe against a near-live or already-started event measures a thinning
    payload, not the market's real availability."""
    earliest_start = now + timedelta(minutes=min_lead_minutes)
    eligible = []
    for event in listed or []:
        commence = event.get("commence_time")
        if not commence:
            continue
        try:
            when = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= earliest_start:
            eligible.append((when, event))
    if not eligible:
        return None
    eligible.sort(key=lambda pair: (pair[0], pair[1].get("id") or ""))
    return eligible[0][1]


def _shape(payload) -> dict:
    """Which books quote MARKET, and how thin each one's ladder is.

    Absence is the finding, not filled with a guess: a book missing from
    `books_offering` did not quote this market in this response, full stop
    -- the same "never invent a price" rule src/providers/odds.py states for
    itself in its own module docstring.
    """
    offering = []
    for book in (payload or {}).get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != MARKET:
                continue
            outcomes = market.get("outcomes") or []
            players = sorted({o.get("description") for o in outcomes if o.get("description")})
            offering.append({
                "book": book.get("key"),
                "last_update": market.get("last_update"),
                "outcome_count": len(outcomes),
                "player_count": len(players),
            })
            break
    all_books = sorted({b.get("key") for b in (payload or {}).get("bookmakers") or []})
    return {
        "books_seen_total": len(all_books),
        "books_seen": all_books,
        "books_offering_market": [b["book"] for b in offering],
        "offered": bool(offering),
        "detail": offering,
    }


def run(out_path, env_file) -> dict:
    _load_dotenv(env_file)

    status = odds_provider.status()
    if not status.get("configured"):
        raise SystemExit(f"skipped: {status.get('message')}")

    quota = odds_provider.quota()
    remaining = quota.get("remaining")
    creditlog.log(remaining, quota.get("last"), CALLER + ".preflight",
                  budget_band=budget_module.PROBE)
    if remaining is None:
        raise SystemExit("refusing to probe: could not read the credit balance")
    if remaining - WORST_CASE_CREDITS <= budget_module.CREDIT_FLOOR:
        raise SystemExit(f"skipped: credit floor (remaining={remaining}, "
                          f"floor={budget_module.CREDIT_FLOOR})")
    envelope_left = budget_module.status().get("envelope_remaining_today")
    print(f"credits remaining: {remaining}  envelope left: {envelope_left}  "
          f"worst case: {WORST_CASE_CREDITS}")
    # The PROBE band does not draw against LIVE_CAPTURE's envelope (see this
    # module's own docstring) -- this check is belt-and-braces visibility,
    # not a gate `can_spend` would apply, and it never blocks the probe.
    if envelope_left is not None and WORST_CASE_CREDITS > envelope_left:
        print(f"note: worst case ({WORST_CASE_CREDITS}) exceeds envelope_left "
              f"({envelope_left}) -- proceeding anyway: this spends under the "
              f"PROBE band, not LIVE_CAPTURE, per this script's own docstring")

    now = datetime.now(timezone.utc)
    listed = odds_provider.list_events()  # free
    event = _eligible_event(listed, now)
    if event is None:
        raise SystemExit(
            f"no event with commence_time at least {MIN_LEAD_MINUTES} "
            f"minute(s) out ({len(listed or [])} event(s) listed); spent nothing")

    # THE MOST LIKELY NEGATIVE ANSWER (fixed 2026-09-12 -- a checker caught
    # this crashing instead of reporting it). If the provider does not
    # recognize `batter_stolen_bases` as a market key at all, the per-event
    # endpoint 422s the WHOLE request before any bookmaker payload comes
    # back (src/providers/odds.py's `_get_json_with_usage`: any HTTP 422
    # other than HISTORICAL_MARKETS_UNAVAILABLE_AT_DATE raises
    # OddsProviderError("...check the markets")) -- there is no payload for
    # `_shape` to inspect, so its offered=False path (a valid key nobody
    # quotes) never runs and this is a different finding, not the same one.
    # Related, and the reason this matters beyond the probe itself: per
    # STOLEN_BASES_ENV_SWITCH's own docstring in batter_props.py, setting
    # STOLEN_BASES=1 against this exact outcome would 422 EVERY batter-prop
    # fetch of the night, losing the six measured markets bundled alongside
    # it too -- not merely failing to add a seventh. Caught here so the
    # probe still writes evidence/ and prints the finding instead of a
    # traceback with nothing on disk.
    provider_error = None
    try:
        payload, usage = odds_provider.fetch_event_odds_with_usage(
            event.get("id"), markets=MARKETS)
    except odds_provider.OddsProviderError as exc:
        provider_error = str(exc)
        payload = None
        usage = {"remaining": None, "last": None}
        shape = {"books_seen_total": 0, "books_seen": [],
                 "books_offering_market": [], "offered": False, "detail": []}
    else:
        creditlog.log(usage.get("remaining"), usage.get("last"), CALLER + ".odds",
                      budget_band=budget_module.PROBE)
        shape = _shape(payload)

    report = {
        "caller": CALLER,
        "market": MARKET,
        "event_id": event.get("id"),
        "commence_time": (payload or {}).get("commence_time") or event.get("commence_time"),
        "home_team": (payload or {}).get("home_team") or event.get("home_team"),
        "away_team": (payload or {}).get("away_team") or event.get("away_team"),
        "billed": usage.get("last"),
        "remaining_before": remaining,
        "remaining_after": usage.get("remaining"),
        **shape,
    }
    if provider_error is not None:
        report["provider_rejected_market"] = True
        report["provider_error"] = provider_error

    after = odds_provider.quota()
    creditlog.log(after.get("remaining"), after.get("last"), CALLER + ".postflight",
                  budget_band=budget_module.PROBE)
    report["credits_spent_measured"] = (
        remaining - after["remaining"] if after.get("remaining") is not None else None)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")

    if provider_error is not None:
        print(f"NOT OFFERED: {MARKET} -- the provider rejected the market "
              f"entirely, before any book could be checked ({provider_error})")
    elif shape["offered"]:
        print(f"OFFERED: {MARKET} quoted by {len(shape['books_offering_market'])}/"
              f"{shape['books_seen_total']} book(s): "
              f"{', '.join(shape['books_offering_market'])}")
    else:
        print(f"NOT OFFERED: {MARKET} absent from all {shape['books_seen_total']} "
              f"book(s) seen on event {event.get('id')}")
    print(f"credits spent (measured): {report['credits_spent_measured']}")
    print(f"report written to {out_path}")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="evidence/probe_stolen_bases.json")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    run(args.out, args.env_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
