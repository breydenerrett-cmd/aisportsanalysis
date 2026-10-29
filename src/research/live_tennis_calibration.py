"""In-play calibration of tennis favourites from The Odds API historical snapshots.

`python -m src.cli research tennis-live-cal {plan,pull,build}`

QUESTION (descriptive, not a strategy): when a pre-match tennis favourite drifts to a
longer price during the match, how often does that player still win, compared with what
the median market price at that moment implied?

WHAT THE DATA CAN AND CANNOT SAY
  * Snapshots are hourly and each is at least 5 minutes stale: these are not prices
    anyone could have bet.
  * Prices are MEDIANS across books, not the best price available.
  * The winner is read from the odds themselves (a side priced -1500 or shorter in the
    last snapshot where that happened). No such snapshot means "unsettled" and the event
    is left out. Never guessed. This selects against matches that vanish from the feed
    early, which is a bias the report states.
  * Events are clustered by tournament-day, so the true sample is smaller than the event
    count suggests.

Only 2024-2025 dates are planned. Any event commencing on or after 2026-01-01 is ignored
by `build` (sealed period).
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.odds import american_to_decimal, american_to_probability

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "research" / "tennis_live_cal" / "snapshots"
CREDIT_STORE = ROOT / "data" / "live" / "credit_log_live.jsonl"
EVIDENCE_PATH = ROOT / "evidence" / "tennis_live_calibration_v1.json"
DOC_PATH = ROOT / "docs" / "research" / "TENNIS_LIVE_CALIBRATION.md"

ENV_SWITCH = "TENNIS_CAL_PULL"
CALLER = "live_tennis_calibration.pull"
BUDGET_BAND = "live_odds"
REGIONS = "us,eu"
MARKETS = ["h2h"]
CREDITS_PER_SNAPSHOT = 20          # 10 per market per region x 2 regions x 1 market
ALREADY_SPENT = 40                 # the two probe snapshots
HARD_CREDIT_CAP = 3000
MAX_SNAPSHOTS = 145                # 145 x 20 = 2900
REMAINING_FLOOR = 80000
START_HOUR, END_HOUR = 10, 23      # local venue time, inclusive, hourly
SEALED_FROM = datetime(2026, 1, 1, tzinfo=timezone.utc)
SETTLE_PRICE = -1500
BANDS = (("-150..-101", -150, -101), ("+100..+149", 100, 149),
         ("+150..+249", 150, 249), ("+250 or longer", 250, 10 ** 9))
Z95 = 1.959963984540054

# (sport key, local date, fixed UTC offset in hours on that date, venue, round note).
# Offsets are written down (no tz database is guaranteed on every machine); each is the
# real offset on that date: BST +1, EDT -4, CEST +2, AEDT +11, PDT -7.
# Keys also seen elsewhere in this repo's stored data: wimbledon, us_open,
# aus_open_singles. The rest follow The Odds API naming and are UNVERIFIED until a pull
# succeeds (a wrong key fails with an error and costs nothing).
TOURNAMENT_DAYS = (
    ("tennis_atp_wimbledon", "2025-07-07", 1, "Wimbledon", "ATP round of 16"),
    ("tennis_wta_wimbledon", "2025-07-08", 1, "Wimbledon", "WTA quarter-finals"),
    ("tennis_atp_us_open", "2025-09-01", -4, "US Open", "ATP round of 16"),
    ("tennis_wta_us_open", "2025-09-02", -4, "US Open", "WTA quarter-finals"),
    ("tennis_atp_french_open", "2025-06-02", 2, "Roland Garros", "ATP round of 16"),
    ("tennis_wta_french_open", "2025-06-03", 2, "Roland Garros", "WTA quarter-finals"),
    ("tennis_atp_aus_open_singles", "2025-01-21", 11, "Australian Open", "ATP quarter-finals"),
    ("tennis_wta_aus_open_singles", "2025-01-22", 11, "Australian Open", "WTA semi-finals"),
    ("tennis_atp_indian_wells", "2025-03-12", -7, "Indian Wells Masters 1000", "ATP round of 16"),
    ("tennis_atp_madrid_open", "2025-04-30", 2, "Madrid Masters 1000", "ATP round of 16"),
)


# ------------------------------------------------------------------ plan

def plan_snapshots(days=TOURNAMENT_DAYS, cap=MAX_SNAPSHOTS):
    """Ordered list of snapshot dicts; whole days only, never more than `cap`."""
    out = []
    for sport, date, offset, venue, note in days:
        day = datetime.strptime(date, "%Y-%m-%d")
        if day.year not in (2024, 2025):
            raise ValueError(f"{date}: only 2024-2025 tournament days are allowed")
        block = []
        for hour in range(START_HOUR, END_HOUR + 1):
            local = day.replace(hour=hour)
            utc = (local - timedelta(hours=offset)).replace(tzinfo=timezone.utc)
            block.append({"sport": sport, "utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "local": local.strftime("%Y-%m-%d %H:%M"), "venue": venue, "note": note})
        if len(out) + len(block) > cap:
            break
        out.extend(block)
    return out


def cache_path(sport, utc, cache_dir=CACHE_DIR) -> Path:
    stamp = utc.replace("-", "").replace(":", "")
    return Path(cache_dir) / f"{sport}__{stamp}.json"


def cached_cost(cache_dir=CACHE_DIR) -> int:
    total = 0
    for path in Path(cache_dir).glob("*.json"):
        try:
            total += int((json.loads(path.read_text(encoding="utf-8")).get("usage") or {}).get("last") or 0)
        except (OSError, ValueError, TypeError):
            continue
    return total


def cmd_plan(cache_dir=CACHE_DIR, out=print) -> int:
    snaps = plan_snapshots()
    done = sum(1 for s in snaps if cache_path(s["sport"], s["utc"], cache_dir).exists())
    out(f"tennis-live-cal plan: {len(snaps)} snapshots, {len(snaps) * CREDITS_PER_SNAPSHOT} credits "
        f"({CREDITS_PER_SNAPSHOT} each, regions {REGIONS}, markets {','.join(MARKETS)})")
    out(f"cap: {MAX_SNAPSHOTS} snapshots = {MAX_SNAPSHOTS * CREDITS_PER_SNAPSHOT} credits; hard cap "
        f"{HARD_CREDIT_CAP} including {ALREADY_SPENT} already spent on probes; stop below {REMAINING_FLOOR} remaining")
    out(f"already cached: {done}; still to pull: {len(snaps) - done}")
    for sport, date, offset, venue, note in TOURNAMENT_DAYS:
        n = sum(1 for s in snaps if s["sport"] == sport and s["local"].startswith(date))
        out(f"  {date} {sport:<30} UTC{offset:+d} {venue} ({note}): {n} snapshots")
    return 0


# ------------------------------------------------------------------ pull

def _load_env():
    env = dict(os.environ)
    if not env.get("ODDS_API_KEY"):
        path = ROOT / ".env"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip("\"'"))
    return env


def run_pull(fetch=None, cache_dir=CACHE_DIR, credit_store=CREDIT_STORE, env=None, out=print,
             snapshots=None, log=None) -> int:
    """Pull planned snapshots not already cached. Returns a process exit code."""
    source = os.environ if env is None else env
    if (source.get(ENV_SWITCH) or "").strip().lower() != "on":
        out(f"{ENV_SWITCH} is not 'on': nothing requested, nothing spent")
        return 0
    if fetch is None:
        from src.providers import odds
        full_env = _load_env() if env is None else env
        if not odds.is_configured(full_env):
            out("ODDS_API_KEY is not configured: nothing requested")
            return 2

        def fetch(ts, sport):
            return odds.fetch_historical_odds(ts, markets=MARKETS, region=REGIONS, env=full_env, sport=sport)
    if log is None:
        from src.pipeline import creditlog
        log = creditlog.log
    snaps = plan_snapshots() if snapshots is None else snapshots
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    spent = ALREADY_SPENT + cached_cost(cache_dir)
    pulled = skipped = errors = consecutive = 0
    remaining = None
    for snap in snaps:
        path = cache_path(snap["sport"], snap["utc"], cache_dir)
        if path.exists():
            skipped += 1
            continue
        if spent + CREDITS_PER_SNAPSHOT > HARD_CREDIT_CAP:
            out(f"stop: next request would take total spend {spent + CREDITS_PER_SNAPSHOT} past the {HARD_CREDIT_CAP} cap")
            break
        if remaining is not None and remaining < REMAINING_FLOOR:
            out(f"stop: x-requests-remaining {remaining} is below {REMAINING_FLOOR}")
            break
        try:
            payload, usage = fetch(snap["utc"], snap["sport"])
        except Exception as exc:  # noqa: BLE001 -- one bad key/date must not stop a resumable pull
            errors += 1
            consecutive += 1
            out(f"error {snap['sport']} {snap['utc']}: {type(exc).__name__}: {exc}")
            if consecutive >= 3:
                out("stop: 3 consecutive errors")
                break
            continue
        consecutive = 0
        cost = usage.get("last")
        log(usage.get("remaining"), cost, CALLER, store=credit_store, budget_band=BUDGET_BAND)
        record = {"sport": snap["sport"], "requested": snap["utc"], "usage": usage, "payload": payload}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(path)
        pulled += 1
        spent += int(cost) if cost is not None else CREDITS_PER_SNAPSHOT
        remaining = usage.get("remaining")
        events = len((payload or {}).get("data") or [])
        out(f"pulled {snap['sport']} {snap['utc']}: {events} events, cost {cost}, remaining {remaining}, spend total {spent}")
    out(f"pull done: pulled {pulled}, already cached {skipped}, errors {errors}, spend total {spent} of {HARD_CREDIT_CAP}")
    return 0 if errors == 0 else 2


# ------------------------------------------------------------------ maths

def wilson(k, n, z=Z95):
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return max(0.0, centre - half), min(1.0, centre + half)


def prob_to_american(p):
    if p is None or not 0 < p < 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def median_prob(prices):
    """Median of American prices taken in implied-probability space; None if empty."""
    probs = [american_to_probability(p) for p in prices]
    return statistics.median(probs) if probs else None


def band_of(price):
    for name, lo, hi in BANDS:
        if lo <= price <= hi:
            return name
    return None


# ------------------------------------------------------------------ build

def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _h2h_prices(event):
    """{book_key: {team: price}} for two-way h2h markets only."""
    books = {}
    for book in event.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != "h2h":
                continue
            prices = {o.get("name"): o.get("price") for o in market.get("outcomes") or []
                      if isinstance(o.get("price"), (int, float)) and not isinstance(o.get("price"), bool)
                      and o.get("price") not in (0,)}
            if len(prices) == 2:
                books[book.get("key")] = prices
    return books


def load_snapshots(cache_dir=CACHE_DIR):
    snaps = []
    for path in sorted(Path(cache_dir).glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            ts = _parse((rec.get("payload") or {}).get("timestamp") or rec["requested"])
            snaps.append((ts, rec["sport"], (rec.get("payload") or {}).get("data") or []))
        except (OSError, ValueError, KeyError):
            continue
    snaps.sort(key=lambda s: s[0])
    return snaps


def _median_pair(books, a, b):
    pa = median_prob([x[a] for x in books.values() if a in x])
    pb = median_prob([x[b] for x in books.values() if b in x])
    if pa is None or pb is None:
        return None
    return pa, pb


def analyse_event(eid, home, away, commence, obs):
    """obs: [(snapshot_ts, books)] sorted. Returns the per-event record (never guesses)."""
    rec = {"event_id": eid, "home": home, "away": away, "commence": _stamp(commence), "status": None}
    pre = [(t, b) for t, b in obs if t < commence]
    live = [(t, b) for t, b in obs if t >= commence]
    if not pre:
        rec["status"] = "no_prematch_snapshot"
        return rec
    t0, books = pre[-1]
    pin = books.get("pinnacle")
    if pin and home in pin and away in pin:
        ph, pa = american_to_probability(pin[home]), american_to_probability(pin[away])
        rec["prematch_source"] = "pinnacle"
    else:
        pair = _median_pair(books, home, away)
        if pair is None:
            rec["status"] = "no_prematch_prices"
            return rec
        ph, pa = pair
        rec["prematch_source"] = "market_median"
    fair_h = ph / (ph + pa)
    if abs(fair_h - 0.5) < 1e-9:
        rec["status"] = "no_favourite"
        return rec
    fav, dog = (home, away) if fair_h > 0.5 else (away, home)
    rec.update(favourite=fav, underdog=dog, prematch_snapshot=_stamp(t0),
               prematch_fair_prob=round(max(fair_h, 1 - fair_h), 4))
    path = []
    for t, b in live:
        pair = _median_pair(b, fav, dog)
        if pair is None:
            continue
        pf, pd = pair
        path.append({"t": _stamp(t), "fav_price": prob_to_american(pf), "dog_price": prob_to_american(pd),
                     "fav_prob": pf, "dog_prob": pd})
    rec["inplay_snapshots"] = len(path)
    if not path:
        rec["status"] = "no_inplay"
        return rec
    winner = None
    for p in path:  # the LAST snapshot with a side at -1500 or shorter fixes the label
        if p["fav_price"] is not None and p["fav_price"] <= SETTLE_PRICE:
            winner = fav
        elif p["dog_price"] is not None and p["dog_price"] <= SETTLE_PRICE:
            winner = dog
    rec["winner"] = winner
    if winner is None:
        rec["status"] = "unsettled"
        return rec
    rec["status"] = "settled"
    longest = min(path, key=lambda p: p["fav_prob"])
    rec["longest_fav_price"] = longest["fav_price"]
    rec["longest_at"] = longest["t"]
    band = band_of(longest["fav_price"]) if longest["fav_price"] is not None else None
    rec["band"] = band
    if band:
        first = next(p for p in path if p["fav_price"] is not None and band_of(p["fav_price"]) == band)
        rec["first_hit"] = {
            "t": first["t"], "price": first["fav_price"],
            "implied_prob": american_to_probability(first["fav_price"]),
            "fair_prob": first["fav_prob"] / (first["fav_prob"] + first["dog_prob"]),
            "already_decided": first["dog_price"] is not None and first["dog_price"] <= SETTLE_PRICE}
        rec["fav_won"] = winner == fav
    return rec


def build_events(snaps):
    events = {}
    for ts, sport, data in snaps:
        for ev in data:
            try:
                commence = _parse(ev["commence_time"])
            except (KeyError, ValueError):
                continue
            if commence >= SEALED_FROM:
                continue
            slot = events.setdefault((sport, ev.get("id")), {
                "home": ev.get("home_team"), "away": ev.get("away_team"), "commence": commence, "obs": []})
            slot["obs"].append((ts, _h2h_prices(ev)))
    out = []
    for (sport, eid), s in sorted(events.items(), key=lambda kv: (kv[1]["commence"], str(kv[0]))):
        s["obs"].sort(key=lambda o: o[0])
        rec = analyse_event(eid, s["home"], s["away"], s["commence"], s["obs"])
        rec["sport"] = sport
        out.append(rec)
    return out


def band_table(records):
    rows = []
    for name, _, _ in BANDS:
        hits = [r for r in records if r.get("band") == name and r.get("first_hit")]
        n = len(hits)
        wins = sum(1 for r in hits if r["fav_won"])
        row = {"band": name, "n": n, "wins": wins, "win_rate": None, "wilson_95": [None, None],
               "mean_implied_prob": None, "calibration_gap": None, "gap_interval_excludes_zero": None,
               "mean_fair_prob": None, "flat_1u_roi": None, "first_hit_already_decided": 0}
        if n:
            lo, hi = wilson(wins, n)
            implied = sum(r["first_hit"]["implied_prob"] for r in hits) / n
            roi = sum((american_to_decimal(r["first_hit"]["price"]) - 1) if r["fav_won"] else -1.0
                      for r in hits) / n
            row.update(win_rate=wins / n, wilson_95=[lo, hi], mean_implied_prob=implied,
                       calibration_gap=wins / n - implied,
                       gap_interval_excludes_zero=bool(implied < lo or implied > hi),
                       mean_fair_prob=sum(r["first_hit"]["fair_prob"] for r in hits) / n,
                       flat_1u_roi=roi,
                       first_hit_already_decided=sum(1 for r in hits if r["first_hit"]["already_decided"]))
        rows.append(row)
    return rows


CAVEATS = [
    "Snapshots are hourly and at least 5 minutes stale; these are not prices you could have bet.",
    "Prices are medians across books, not the best price available.",
    "Winners are read from the odds (a side at -1500 or shorter); events with no such snapshot are unsettled and excluded.",
    "Implied probability includes the bookmaker margin, so the gap understates a fair-probability gap slightly.",
    "Events are clustered by tournament-day and bands overlap in time; four bands are looked at with no multiplicity correction.",
]


def run_build(cache_dir=CACHE_DIR, evidence_path=EVIDENCE_PATH, doc_path=DOC_PATH, out=print) -> int:
    snaps = load_snapshots(cache_dir)
    if not snaps:
        out("build: no cached snapshots; run pull first")
        return 2
    records = build_events(snaps)
    counts = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    result = {
        "version": "tennis_live_calibration_v1",
        "built_utc": _stamp(datetime.now(timezone.utc)),
        "snapshots": len(snaps), "events": len(records), "status_counts": counts,
        "tournament_days": sorted({(r["sport"], r["commence"][:10]) for r in records}),
        "bands": band_table(records), "events_detail": records, "caveats": CAVEATS,
    }
    result["tournament_days"] = [list(x) for x in result["tournament_days"]]
    evidence_path = Path(evidence_path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    doc_path = Path(doc_path)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(render_doc(result), encoding="utf-8")
    out(f"build: {len(snaps)} snapshots, {len(records)} events, {counts}; wrote {evidence_path} and {doc_path}")
    return 0


def _pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def render_doc(res) -> str:
    n_settled = res["status_counts"].get("settled", 0)
    banded = sum(b["n"] for b in res["bands"])
    lines = [
        "# Tennis in-play calibration (history, exploratory)",
        "",
        "This page looks at one question about past tennis matches: when the pre-match favourite "
        "fell behind in the betting during the match, how often did they still win, compared with what "
        "the market price at that moment said? It describes history. It is not a betting system.",
        "",
        "## How to read the numbers (please read first)",
        "",
        "- The prices come from hourly snapshots, and each snapshot is at least 5 minutes old when we see it. "
        "These are not prices you could actually have bet. In a live tennis match the price can move a lot in five minutes.",
        "- Each price is the middle (median) price across sportsbooks, not the best price available. A real bettor "
        "could do better or worse than that.",
        "- Winners are worked out from the odds themselves: a player counts as the winner if the last snapshot where "
        "someone was priced -1500 or shorter shows them as the heavy favourite. If no snapshot got that far, the match is "
        "marked unsettled and left out. We never guess a winner. This leaves out matches that dropped off the feed early.",
        "- Implied probability here includes the sportsbook's built-in margin, so it runs slightly high and the "
        "calibration gap runs slightly low. A margin-free version is in the data file as mean_fair_prob.",
        "",
        "## What was collected",
        "",
        f"- {res['snapshots']} snapshots across {len(res['tournament_days'])} tournament-days; {res['events']} matches seen.",
        f"- Match outcomes: {', '.join(f'{k} {v}' for k, v in sorted(res['status_counts'].items())) or 'none'}.",
        f"- {n_settled} matches were settled; {banded} produced a favourite price in one of the four bands below.",
        "",
    ]
    if banded < 100:
        lines += [f"**The sample is small ({banded} banded matches). Treat every number below as a rough "
                  "look, not a finding. The ranges are wide for a reason.**", ""]
    lines += [
        "## Results by price band",
        "",
        "A favourite is put in the band of the longest price they reached during the match. The numbers then use the "
        "FIRST time they hit that band. Win rate has a 95% Wilson range. Gap = win rate minus the average implied "
        "probability at that first moment. ROI is a flat 1-unit bet at that first-hit median price (not obtainable in practice). "
        "The last column counts first hits where the other player was already at -1500 or shorter, meaning the match was effectively over.",
        "",
        "| Band | Matches | Wins | Win rate (95% range) | Avg implied | Gap | ROI per 1u | Already decided |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in res["bands"]:
        rng = "n/a" if b["n"] == 0 else f"{_pct(b['win_rate'])} ({_pct(b['wilson_95'][0])} to {_pct(b['wilson_95'][1])})"
        gap = "n/a" if b["calibration_gap"] is None else f"{b['calibration_gap'] * 100:+.1f} pts"
        roi = "n/a" if b["flat_1u_roi"] is None else f"{b['flat_1u_roi'] * 100:+.1f}%"
        lines.append(f"| {b['band']} | {b['n']} | {b['wins']} | {rng} | {_pct(b['mean_implied_prob'])} | {gap} | {roi} | "
                     f"{b['first_hit_already_decided']} |")
    flagged = [b for b in res["bands"] if b["gap_interval_excludes_zero"]]
    lines += ["", "## What this does and does not show", ""]
    if flagged:
        lines.append("In " + ", ".join(b["band"] for b in flagged) + " the 95% range for the win rate does not include the "
                     "average implied probability. That is one exploratory result among four bands looked at, with matches "
                     "clustered inside a few tournament-days and stale median prices. It is a reason to write a pre-registered "
                     "test, not a reason to bet.")
    else:
        lines.append("In every band the 95% range for the win rate includes the average implied probability, so this data "
                     "shows no gap between what the market implied and what happened. That is not proof the prices are "
                     "right; with this sample it simply cannot tell.")
    lines += ["", "No edge is claimed. A real test needs a pre-registered plan, live prices you could actually bet, and a "
              "much larger sample.", ""]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ cli

def main(command, out=print) -> int:
    if command == "plan":
        return cmd_plan(out=out)
    if command == "pull":
        return run_pull(out=out)
    if command == "build":
        return run_build(out=out)
    print(f"unknown command {command}", file=sys.stderr)
    return 2
