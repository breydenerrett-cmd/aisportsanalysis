#!/usr/bin/env python3
"""Loss diagnosis, agent 2: WHAT IS GUIDING SELECTION on the public V2 card,
and is the selection rule itself the problem?

READ-ONLY with respect to every model, card and ledger file. It imports the
registered code path (`src.analysis.best_bets_card`, `src.analysis.propboard`,
`src.report.props`, `src.appstate.card_ledger`) and calls it unmodified; it
writes only under `data/research/loss_diagnosis/`.

EVIDENCE RULES ENFORCED HERE
----------------------------
* SEALED 2026-01-01..2026-08-27: every outcome-bearing row (box score,
  linescore, results CSV row, ledger row) is date-checked by `_open()` BEFORE
  any outcome field is touched; a sealed date is dropped, never read.
* 2025 is not read at all by this script.
* 2024 (open) is read only by `section_2024` for the moneyline rebuild.
* Every number below is RETROSPECTIVE on already-graded entries. Any rule
  change it evaluates is HINDSIGHT and is labelled so in the output.

Usage (from the repo root):
    python3 scripts/diagnosis/selection.py all          # everything
    python3 scripts/diagnosis/selection.py replay       # rebuild prop pool cache
    python3 scripts/diagnosis/selection.py ledger       # Q3/Q4/Q5/Q6 on the ledger
    python3 scripts/diagnosis/selection.py pool         # Q2 on the replayed pool
    python3 scripts/diagnosis/selection.py trace        # Q1 three-date trace
    python3 scripts/diagnosis/selection.py y2024        # Q2 2024 moneyline rebuild
"""

from __future__ import annotations

import gzip
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
os.chdir(REPO)

from src.analysis import best_bets_card as bbc  # noqa: E402
from src.analysis import playerprops, propboard  # noqa: E402
from src.appstate import card_ledger as cl  # noqa: E402
from src.core import odds as odds_math  # noqa: E402

OUT_DIR = os.path.join("data", "research", "loss_diagnosis")
CARD_STORE = os.path.join("evidence", "cards_v2.jsonl")
BOX_STORE = os.path.join("data", "processed", "boxscores_2026.jsonl")
PROP_STORE = os.path.join("data", "processed", "batter_props.jsonl")
EVENT_MAP = os.path.join("data", "processed", "event_game_map.jsonl")
LINEUP_STORE = os.path.join("data", "historical", "lineups.jsonl")
LINEUP_WATCH = os.path.join("data", "watch", "lineups_watch.jsonl")
DECISIONS = os.path.join("evidence", "decisions_v2.jsonl")
SHADOW_ENUM_DIR = os.path.join("evidence", "shadow_enumeration")
REPLAY_CACHE = os.path.join(OUT_DIR, "prop_replay_pool.jsonl.gz")

SEED = 20261016
SEALED_LO, SEALED_HI = "2026-01-01", "2026-08-27"
POOL_FIRST_DATE = "2026-09-03"   # first prop-quote date in the store (open window)


# ---------------------------------------------------------------------------
# Sealed-window guard
# ---------------------------------------------------------------------------

def _open(date) -> bool:
    """True for an OPEN date. 2025 is refused too (tuning-only; not needed)."""
    d = str(date or "")[:10]
    if not d:
        return False
    if SEALED_LO <= d <= SEALED_HI:
        return False
    if d.startswith("2025"):
        return False
    return True


def _dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _jsonl(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


# ---------------------------------------------------------------------------
# Statistics helpers (stdlib only)
# ---------------------------------------------------------------------------

def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (centre - half, centre + half)


def dec(price):
    return odds_math.american_to_decimal(price)


def implied(price):
    return odds_math.american_to_probability(price)


def profit(price, won):
    return (dec(price) - 1.0) if won else -1.0


def summarise(bets, key_won="won", key_profit="profit"):
    """Record, hit rate, units, ROI, mean market p, mean breakeven, excess."""
    n = len(bets)
    if not n:
        return {"n": 0}
    w = sum(1 for b in bets if b[key_won])
    units = sum(b[key_profit] for b in bets)
    mkt = [b["market_p"] for b in bets if b.get("market_p") is not None]
    be = [b["breakeven"] for b in bets if b.get("breakeven") is not None]
    ev_mkt = [b["ev_mkt"] for b in bets if b.get("ev_mkt") is not None]
    lo, hi = wilson(w, n)
    out = {
        "n": n, "wins": w, "losses": n - w,
        "hit": round(w / n, 4), "hit_ci95": [round(lo, 3), round(hi, 3)],
        "units": round(units, 2), "roi_pct": round(100 * units / n, 1),
        "mean_market_p": round(sum(mkt) / len(mkt), 4) if mkt else None,
        "mean_breakeven": round(sum(be) / len(be), 4) if be else None,
        "hit_minus_market": (round(w / n - sum(mkt) / len(mkt), 4) if mkt else None),
        "expected_units_at_market": round(sum(ev_mkt), 2) if ev_mkt else None,
    }
    if mkt and len(mkt) == n:
        var = sum(b["market_p"] * (1 - b["market_p"]) for b in bets)
        out["z_vs_market"] = round((w - sum(mkt)) / math.sqrt(var), 2) if var > 0 else None
    return out


def ols(xs, ys):
    """(intercept, slope) of y on x."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return (my, None)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    return (my - b * mx, b)


def ols0(xs, ys):
    """Slope of y on x through the origin."""
    sxx = sum(x * x for x in xs)
    return sum(x * y for x, y in zip(xs, ys)) / sxx if sxx else None


def cluster_bootstrap(rows, stat_fn, cluster_key="date", B=2000, seed=SEED):
    """Percentile 95% CI of stat_fn over date-clustered resamples."""
    rng = random.Random(seed)
    by = defaultdict(list)
    for r in rows:
        by[r[cluster_key]].append(r)
    keys = sorted(by)
    vals = []
    for _ in range(B):
        sample = []
        for _k in keys:
            sample.extend(by[keys[rng.randrange(len(keys))]])
        try:
            v = stat_fn(sample)
        except (ZeroDivisionError, TypeError):
            v = None
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return (None, None)
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1])


def shrinkage(rows, xkey="mm"):
    """Regression of realised-minus-market on the model-minus-market gap.

    `k0`: through-origin slope -- the blend weight w in
          p_true = market + w * (ours - market). 1 = our gap is fully real,
          0 = our gap carries nothing, < 0 = our gap points the wrong way.
    `a, b`: with an intercept (a absorbs any constant bias of the market
          number on this slice, e.g. favourite-longshot or vig asymmetry).
    """
    xs = [r[xkey] for r in rows]
    ys = [(1.0 if r["won"] else 0.0) - r["market_p"] for r in rows]
    k0 = ols0(xs, ys)
    a, b = ols(xs, ys)
    lo0, hi0 = cluster_bootstrap(
        rows, lambda s: ols0([r[xkey] for r in s],
                             [(1.0 if r["won"] else 0.0) - r["market_p"] for r in s]))
    lob, hib = cluster_bootstrap(
        rows, lambda s: ols([r[xkey] for r in s],
                            [(1.0 if r["won"] else 0.0) - r["market_p"] for r in s])[1])
    return {"n": len(rows), "days": len({r["date"] for r in rows}),
            "k_through_origin": _r(k0), "k_ci95": [_r(lo0), _r(hi0)],
            "intercept": _r(a), "slope": _r(b), "slope_ci95": [_r(lob), _r(hib)],
            "mean_gap": _r(sum(xs) / len(xs)),
            "mean_realised_minus_market": _r(sum(ys) / len(ys))}


def _r(x, d=4):
    return None if x is None else round(x, d)


def permutation_test(rows, label_key, value_key, n_perm=10000, strata_key=None,
                     seed=SEED):
    """Two-sided p for mean(value | label) - mean(value | not label).

    With `strata_key`, labels are shuffled WITHIN each stratum (date), so a
    day effect cannot masquerade as a pick/fill effect.
    """
    rng = random.Random(seed)

    def diff(labels):
        a = [r[value_key] for r, l in zip(rows, labels) if l]
        b = [r[value_key] for r, l in zip(rows, labels) if not l]
        if not a or not b:
            return 0.0
        return sum(a) / len(a) - sum(b) / len(b)

    labels = [bool(r[label_key]) for r in rows]
    obs = diff(labels)
    if strata_key:
        groups = defaultdict(list)
        for i, r in enumerate(rows):
            groups[r[strata_key]].append(i)
    hits = 0
    for _ in range(n_perm):
        if strata_key:
            perm = labels[:]
            for idx in groups.values():
                vals = [labels[i] for i in idx]
                rng.shuffle(vals)
                for i, v in zip(idx, vals):
                    perm[i] = v
        else:
            perm = labels[:]
            rng.shuffle(perm)
        if abs(diff(perm)) >= abs(obs) - 1e-12:
            hits += 1
    return {"observed_diff": round(obs, 4), "p_two_sided": round((hits + 1) / (n_perm + 1), 4),
            "n_perm": n_perm, "stratified_by": strata_key}


# ---------------------------------------------------------------------------
# Outcomes: box scores and linescores, open window only
# ---------------------------------------------------------------------------

_BOX = None


def box_rows():
    """Every box row on an OPEN date (the 2026 store starts 2026-08-30)."""
    global _BOX
    if _BOX is None:
        _BOX = [r for r in _jsonl(BOX_STORE) if _open(r.get("date"))]
    return _BOX


def game_results():
    """{str(game_pk): {away_score, home_score, date}} from linescores."""
    out = {}
    for r in box_rows():
        if r.get("type") != "linescore":
            continue
        inn = r.get("innings") or []
        if not inn:
            continue
        a = sum(int(i.get("away_runs") or 0) for i in inn)
        h = sum(int(i.get("home_runs") or 0) for i in inn)
        out[str(r["game_pk"])] = {"away_score": a, "home_score": h, "date": r["date"]}
    return out


# ---------------------------------------------------------------------------
# The published ledger: graded entries
# ---------------------------------------------------------------------------

def published_rows():
    rows = [r for r in _jsonl(CARD_STORE) if r.get("kind") == "card_published"
            and _open(r.get("date"))]
    rows.sort(key=lambda r: (r["date"], r["published_utc"]))
    return rows


def _ident(e):
    return (e.get("player_id") or e.get("game_id") or e.get("game_pk"),
            e.get("market"), str(e.get("line")), e.get("side"))


def ledger_entries():
    """Every graded WIN/LOSS entry (withdrawn included, flagged), with the
    derived fields every section below reads."""
    pubs = published_rows()
    first_shown = {}
    run_index = defaultdict(int)
    for row in pubs:
        run_index[row["date"]] += 1
        for e in (row.get("all_bets") or []):
            k = (row["date"],) + _ident(e)
            if k not in first_shown:
                first_shown[k] = (row["published_utc"], run_index[row["date"]])
    hist = cl.history_v2(path=CARD_STORE, limit=None)
    out = []
    for day in hist["days"]:
        if not _open(day["date"]):
            continue
        for g in day["graded"]:
            if g.get("result") not in ("WIN", "LOSS"):
                continue
            price = g["price"]
            mp = g.get("market_probability")
            op = g.get("our_probability")
            be = implied(price)
            fs = first_shown.get((day["date"],) + _ident(g))
            fs_utc = _dt(fs[0]) if fs else None
            obs = _dt(g.get("observed_utc"))
            locked = _dt(g.get("locked_at"))
            fp = _dt(g.get("first_pitch_utc") or g.get("first_pitch"))
            e = {
                "date": day["date"],
                "entry_class": g.get("entry_class"),
                "withdrawn": bool(g.get("withdrawn")),
                "kind": g.get("kind"),
                "market": g.get("market"),
                "side": g.get("side"),
                "line": g.get("line"),
                "who": g.get("player") or g.get("team_name"),
                "price": price,
                "price_class": g.get("price_class"),
                "books": g.get("books"),
                "market_p": mp,
                "our_p": op,
                "mm": (op - mp) if (op is not None and mp is not None) else None,
                "gap": g.get("gap"),
                "breakeven": be,
                "vig_gap": (be - mp) if mp is not None else None,
                "used": g.get("our_probability_used"),
                "value_need": g.get("value_need"),
                "score": g.get("score"),
                "score_calc": bbc.score(op, price, bbc.V2) if op is not None else None,
                "failed_gates": list(g.get("failed_gates") or []),
                "won": g["result"] == "WIN",
                "profit": g.get("profit_units") or 0.0,
                "ev_mkt": (mp * dec(price) - 1.0) if mp is not None else None,
                "ev_ours_used": ((g.get("our_probability_used") or 0) * dec(price) - 1.0),
                "expected_pa_source": g.get("expected_pa_source"),
                "home": (g.get("side") == "home") if g.get("kind") == "game" else None,
                "first_shown_utc": fs[0] if fs else None,
                "first_shown_run": fs[1] if fs else None,
                "age_at_first_show_min": (((fs_utc - obs).total_seconds() / 60.0)
                                          if (fs_utc and obs) else None),
                "age_at_lock_min": (((locked - obs).total_seconds() / 60.0)
                                    if (locked and obs) else None),
                "lead_at_observed_h": (((fp - obs).total_seconds() / 3600.0)
                                       if (fp and obs) else None),
                "game_pk": g.get("game_pk"),
            }
            out.append(e)
    return out


# ---------------------------------------------------------------------------
# Prop candidate replay (the registered path, unmodified, at each publish run)
# ---------------------------------------------------------------------------

class PropWorld:
    """Every local store the live prop path reads, loaded once."""

    def __init__(self):
        from src.report import props as props_mod
        self.props_mod = props_mod
        self.rows_by_date = defaultdict(list)
        for r in _jsonl(PROP_STORE):
            d = r.get("game_date")
            if not d or d < POOL_FIRST_DATE or not _open(d):
                continue
            r["_obs"] = _dt(r.get("observed_utc"))
            self.rows_by_date[d].append(r)
        batters = [r for r in box_rows() if r.get("type") == "batter"]
        self.batters = batters
        self.by_name = props_mod._by_name(batters)
        self.event_map = {}
        for r in _jsonl(EVENT_MAP):
            if r.get("event_id") is not None:
                self.event_map[str(r["event_id"])] = r
        self.lineups = {}
        for r in _jsonl(LINEUP_STORE):
            if r.get("empty") or not r.get("game_pk"):
                continue
            if not _open(r.get("date")):
                continue
            self.lineups[str(r["game_pk"])] = r
        # First time each (game_pk, side) lineup was seen non-empty.
        self.posted = {}
        for r in _jsonl(LINEUP_WATCH):
            if "game_pk" not in r:
                continue
            t = _dt(r.get("fetched_utc"))
            for side in ("away", "home"):
                if r.get(f"{side}_lineup"):
                    k = (str(r["game_pk"]), side)
                    if k not in self.posted or t < self.posted[k]:
                        self.posted[k] = t
        self._league = {}

    def league(self, date):
        if date not in self._league:
            hist = [r for r in self.batters if str(r.get("date") or "")[:10] < date]
            self._league[date] = playerprops.league_rates(hist) if hist else None
        return self._league[date]

    def slots(self, date, now=None):
        """Batting slots posted by `now` (point-in-time via the watch log);
        `now=None` means every posted lineup (pregame-final)."""
        out = {}
        for pk, entry in self.lineups.items():
            if str(entry.get("date") or "")[:10] != date:
                continue
            for side in ("away", "home"):
                if now is not None:
                    t = self.posted.get((pk, side))
                    if t is None or t > now:
                        continue
                for index, batter in enumerate(entry.get(side) or [], start=1):
                    name = batter.get("name")
                    try:
                        slot = int(batter.get("order") or index)
                    except (TypeError, ValueError):
                        slot = index
                    if name and 1 <= slot <= 9:
                        out[name] = slot
        return out

    def first_pitch(self, event_id):
        row = self.event_map.get(str(event_id)) or {}
        return row.get("schedule_commence_time") or row.get("commence_time"), row.get("game_pk")

    def board(self, date, *, now=None, before_commence=False, slots_now="pit"):
        """propboard.build on quotes observed by `now` (or strictly before each
        game's own commence time when `before_commence`)."""
        rows = self.rows_by_date.get(date) or []
        if now is not None:
            rows = [r for r in rows if r["_obs"] is not None and r["_obs"] <= now]
        if before_commence:
            keep = []
            for r in rows:
                ct = _dt(r.get("commence_time"))
                if ct is not None and r["_obs"] is not None and r["_obs"] < ct:
                    keep.append(r)
            rows = keep
        league = self.league(date)
        if not rows or not league:
            return []
        slots = self.slots(date, now if slots_now == "pit" else None)
        built = propboard.build(rows, date=date, batters_by_name=self.by_name,
                                league=league, slots_by_player=slots)
        return built["contracts"]

    def candidates(self, date, now):
        """`card_v2._build_prop_candidates` reproduced over local stores: the
        top-200 most-likely contracts (props.board_for_date limit=MAX_LIMIT,
        `_public` rounding), joined to a game_pk/first pitch, unstarted."""
        contracts = self.board(date, now=now)
        likely = propboard.most_likely(contracts)[: self.props_mod.MAX_LIMIT]
        out = []
        for c0 in likely:
            c = self.props_mod._public(c0)
            fp, pk = self.first_pitch(c.get("event_id"))
            if pk is None or fp is None:
                continue
            fpd = _dt(fp)
            if fpd is None or fpd <= now:
                continue
            out.append({
                "kind": "prop", "game_id": None, "game_pk": pk,
                "player_id": c.get("player"), "player": c.get("player"),
                "price": c.get("price"), "market_probability": c.get("market_probability"),
                "our_probability": c.get("probability"), "books": c.get("books"),
                "observed_utc": _dt(c.get("observed_utc")), "has_started": False,
                "calibrated": True, "first_pitch": fp, "first_pitch_utc": fp,
                "season_games": c.get("season_games"),
                "lineup_posted": c.get("expected_pa_source") == "batting_slot",
                "expected_pa_source": c.get("expected_pa_source"),
                "bet_sentence": f"{c.get('player')} {c.get('market')} {c.get('line')}",
                "market": c.get("market"), "side": c.get("side"), "line": c.get("line"),
                "game_type": "R",
            })
        return out


def grade_prop(c, box_index, captured):
    g = cl.grade_prop_pick(c, box_index, box_captured_game_pks=captured)
    return g.get("result")


def build_replay():
    """Replay the prop candidate pool at every actual publish instant of every
    graded date, plus the pregame-close board for 2026-09-03..2026-10-15.
    Writes REPLAY_CACHE (gzip jsonl)."""
    world = PropWorld()
    batters = [r for r in box_rows() if r.get("type") == "batter"]
    box_index = cl._index_prop_box_rows(batters)
    captured = cl._box_captured_game_pks(box_rows())
    pubs = published_rows()
    graded_dates = sorted({e["date"] for e in ledger_entries()})
    runs = defaultdict(list)
    for row in pubs:
        if row["date"] in graded_dates:
            runs[row["date"]].append(row)
    os.makedirs(OUT_DIR, exist_ok=True)
    n_out = 0
    with gzip.open(REPLAY_CACHE, "wt", encoding="utf-8") as fh:
        # (A) the card-run pool: every candidate at every publish run.
        for date in graded_dates:
            for run_no, row in enumerate(runs[date], start=1):
                now = _dt(row["published_utc"])
                cands = world.candidates(date, now)
                for c in cands:
                    fails = bbc.failed_gates(c, now=now, params=bbc.V2)
                    res = grade_prop(c, box_index, captured)
                    fh.write(json.dumps(_pool_row(c, fails, res, date, "run",
                                                  run_no=run_no, now=now)) + "\n")
                    n_out += 1
            print(f"replay runs {date}: {len(runs[date])} runs", file=sys.stderr)
        # (B) the pregame-close board, both sides of every assessable contract.
        d = datetime.fromisoformat(POOL_FIRST_DATE).date()
        last = datetime.fromisoformat("2026-10-15").date()
        while d <= last:
            date = d.isoformat()
            contracts = world.board(date, before_commence=True, slots_now="final")
            for c0 in contracts:
                if c0.get("market_probability") is None:
                    continue
                fp, pk = world.first_pitch(c0.get("event_id"))
                c = dict(c0)
                c.update({"kind": "prop", "game_pk": pk, "player_id": c0.get("player"),
                          "our_probability": c0.get("probability"),
                          "observed_utc": _dt(c0.get("observed_utc")),
                          "first_pitch_utc": fp, "first_pitch": fp,
                          "has_started": False, "calibrated": True})
                fpd = _dt(fp)
                now = (fpd - timedelta(minutes=1)) if fpd else c["observed_utc"]
                fails = bbc.failed_gates(c, now=now, params=bbc.V2) if now else ["NO_TIME"]
                res = grade_prop(c, box_index, captured) if pk is not None else "UNRESOLVED"
                fh.write(json.dumps(_pool_row(c, fails, res, date, "close")) + "\n")
                n_out += 1
            print(f"close board {date}: {len(contracts)} contracts", file=sys.stderr)
            d += timedelta(days=1)
    print(f"wrote {n_out} rows to {REPLAY_CACHE}", file=sys.stderr)


def _pool_row(c, fails, res, date, source, run_no=None, now=None):
    return {
        "source": source, "date": date, "run": run_no,
        "now": now.isoformat() if now else None,
        "player": c.get("player"), "market": c.get("market"), "line": c.get("line"),
        "side": c.get("side"), "price": c.get("price"), "books": c.get("books"),
        "market_p": c.get("market_probability"), "our_p": c.get("our_probability"),
        "season_games": c.get("season_games"),
        "expected_pa_source": c.get("expected_pa_source"),
        "observed_utc": (c["observed_utc"].isoformat() if isinstance(c.get("observed_utc"), datetime)
                         else c.get("observed_utc")),
        "first_pitch_utc": c.get("first_pitch_utc"), "game_pk": c.get("game_pk"),
        "failed_gates": fails, "result": res,
    }


def load_replay():
    if not os.path.exists(REPLAY_CACHE):
        build_replay()
    return list(_jsonl(REPLAY_CACHE))


def _enrich_pool(r):
    """Derived fields for a replayed pool row (W/L rows only are analysed)."""
    price = r["price"]
    r["breakeven"] = implied(price)
    r["mm"] = (r["our_p"] - r["market_p"]) if r["market_p"] is not None else None
    r["won"] = r["result"] == "WIN"
    r["profit"] = profit(price, r["won"])
    r["ev_mkt"] = r["market_p"] * dec(price) - 1.0 if r["market_p"] is not None else None
    r["price_class"] = bbc.price_class(price)
    fails = set(r["failed_gates"])
    if not fails:
        r["v2_class"] = "pick_eligible"
    elif bbc.is_fill_eligible(r["failed_gates"]):
        r["v2_class"] = "close_call"
    else:
        r["v2_class"] = "hard_fail"
    return r


# ---------------------------------------------------------------------------
# Bucketing helpers
# ---------------------------------------------------------------------------

MM_EDGES = [(-1.0, 0.0, "<0"), (0.0, 0.02, "0-2"), (0.02, 0.04, "2-4"),
            (0.04, 0.06, "4-6"), (0.06, 0.08, "6-8"), (0.08, 0.10, "8-10"),
            (0.10, 1.0, ">10")]


def mm_bucket(x):
    for lo, hi, name in MM_EDGES:
        if lo <= x < hi:
            return name
    return ">10" if x >= 0.10 else "<0"


def price_band(p):
    if p <= -140:
        return "a:-160..-140"
    if p <= -120:
        return "b:-139..-120"
    if p < 0:
        return "c:-119..-100"
    if p <= 150:
        return "d:+100..+150"
    return "e:+151..+250"


def books_bucket(b):
    if b is None:
        return "?"
    if b <= 2:
        return "2"
    if b <= 4:
        return "3-4"
    if b <= 6:
        return "5-6"
    return "7+"


def table(rows, keyfn, order=None):
    groups = defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    keys = order or sorted(groups, key=str)
    return {str(k): summarise(groups[k]) for k in keys if k in groups}


def md_table(d, cols=("n", "wins", "losses", "hit", "mean_market_p", "hit_minus_market",
                      "mean_breakeven", "units", "roi_pct", "expected_units_at_market")):
    lines = ["| stratum | " + " | ".join(cols) + " |",
             "|---|" + "---:|" * len(cols)]
    for k, v in d.items():
        lines.append(f"| {k} | " + " | ".join(
            "" if v.get(c) is None else str(v.get(c)) for c in cols) + " |")
    return "\n".join(lines)


def _shortfall(e):
    need = bbc.value_need(e["price"], bbc.V2)
    return max(0.0, need - bbc.marked_down(e["our_p"], bbc.V2))


def published_order(entries):
    """Within each day: picks by score (desc), then fills by the close-call
    order (fewest failed checks, smallest shortfall, score)."""
    by = defaultdict(list)
    for e in entries:
        by[e["date"]].append(e)
    out = {}
    for d, es in by.items():
        picks = sorted([e for e in es if e["entry_class"] == "pick"],
                       key=lambda e: -(e["score_calc"] or 0))
        fills = sorted([e for e in es if e["entry_class"] == "fill"],
                       key=lambda e: (len(e["failed_gates"]), _shortfall(e),
                                      -(e["score_calc"] or 0)))
        out[d] = picks + fills
    return out


# ---------------------------------------------------------------------------
# Q2-Q6 on the published ledger
# ---------------------------------------------------------------------------

def section_ledger():
    E = ledger_entries()
    shown = [e for e in E if not e["withdrawn"]]
    res = {"_note": "RETROSPECTIVE on graded entries 2026-09-22..2026-10-15. "
                    "`all_178` includes the 17 graded entries that were withdrawn "
                    "after being shown (the brief's 97-81); record_v2 excludes them."}
    res["headline"] = {
        "all_178": summarise(E),
        "excluding_withdrawn": summarise(shown),
        "by_entry_class_and_withdrawn": table(
            E, lambda e: f"{e['entry_class']}|{'withdrawn' if e['withdrawn'] else 'shown'}"),
        "by_entry_class": table(E, lambda e: e["entry_class"]),
        "by_price_class": table(E, lambda e: e["price_class"]),
        "by_kind_market": table(E, lambda e: f"{e['kind']}|{e['market']}"),
        "by_class_kind": table(E, lambda e: f"{e['entry_class']}|{e['kind']}|{e['price_class']}"),
        "fills_by_failed_gate": table([e for e in E if e["entry_class"] == "fill"],
                                      lambda e: "+".join(e["failed_gates"]) or "none"),
        "by_price_band": table(E, lambda e: price_band(e["price"])),
        "by_books": table(E, lambda e: books_bucket(e["books"]), ["2", "3-4", "5-6", "7+"]),
        "by_prop_side": table([e for e in E if e["kind"] == "prop"],
                              lambda e: f"{e['entry_class']}|{e['side']}"),
        "by_pa_source": table([e for e in E if e["kind"] == "prop"],
                              lambda e: f"{e['entry_class']}|{e['expected_pa_source']}"),
    }

    # Q2 on published entries
    order = [b for _, _, b in MM_EDGES]
    res["q2_published"] = {
        "hit_by_model_minus_market": table(E, lambda e: mm_bucket(e["mm"]), order),
        "hit_by_model_minus_market_picks": table(
            [e for e in E if e["entry_class"] == "pick"], lambda e: mm_bucket(e["mm"]), order),
        "hit_by_model_minus_market_fills": table(
            [e for e in E if e["entry_class"] == "fill"], lambda e: mm_bucket(e["mm"]), order),
        "hit_by_gap_vs_breakeven": table(
            E, lambda e: mm_bucket(e["gap"]), order),
        "shrinkage_all": shrinkage(E),
        "shrinkage_props": shrinkage([e for e in E if e["kind"] == "prop"]),
        "shrinkage_picks": shrinkage([e for e in E if e["entry_class"] == "pick"]),
        "shrinkage_fills": shrinkage([e for e in E if e["entry_class"] == "fill"]),
        "score_terciles": _score_terciles([e for e in E if e["entry_class"] == "pick"]),
    }

    # Q3 picks vs fills
    for e in E:
        e["is_pick"] = e["entry_class"] == "pick"
        e["excess"] = (1.0 if e["won"] else 0.0) - e["market_p"]
    res["q3"] = {
        "means": {
            cls: {
                "n": len(s),
                "mean_price": _r(sum(e["price"] for e in s) / len(s), 1),
                "mean_decimal": _r(sum(dec(e["price"]) for e in s) / len(s), 3),
                "mean_market_p": _r(sum(e["market_p"] for e in s) / len(s)),
                "mean_our_p": _r(sum(e["our_p"] for e in s) / len(s)),
                "mean_mm": _r(sum(e["mm"] for e in s) / len(s)),
                "mean_breakeven": _r(sum(e["breakeven"] for e in s) / len(s)),
                "mean_vig_gap": _r(sum(e["vig_gap"] for e in s) / len(s)),
                "mean_books": _r(sum(e["books"] for e in s) / len(s), 2),
                "share_game": _r(sum(1 for e in s if e["kind"] == "game") / len(s), 3),
                "share_plus_money": _r(sum(1 for e in s if e["price"] > 0) / len(s), 3),
                "share_under": _r(sum(1 for e in s if e["side"] == "Under") / len(s), 3),
                "hit": _r(sum(e["won"] for e in s) / len(s)),
                "expected_hit_at_market": _r(sum(e["market_p"] for e in s) / len(s)),
                "expected_hit_at_our_raw": _r(sum(e["our_p"] for e in s) / len(s)),
                "units": _r(sum(e["profit"] for e in s), 2),
                "expected_units_at_market": _r(sum(e["ev_mkt"] for e in s), 2),
                "luck_units": _r(sum(e["profit"] - e["ev_mkt"] for e in s), 2),
            }
            for cls, s in (("pick", [e for e in E if e["is_pick"]]),
                           ("fill", [e for e in E if not e["is_pick"]]))
        },
        "strata": {
            "kind": table(E, lambda e: f"{e['kind']}|{e['entry_class']}"),
            "price_band": table(E, lambda e: f"{price_band(e['price'])}|{e['entry_class']}"),
            "mm_bucket": table(E, lambda e: f"{mm_bucket(e['mm'])}|{e['entry_class']}"),
            "books": table(E, lambda e: f"{books_bucket(e['books'])}|{e['entry_class']}"),
            "props_only_price_band": table([e for e in E if e["kind"] == "prop"],
                                           lambda e: f"{price_band(e['price'])}|{e['entry_class']}"),
        },
        "permutation_profit_unstratified": permutation_test(E, "is_pick", "profit"),
        "permutation_profit_by_date": permutation_test(E, "is_pick", "profit", strata_key="date"),
        "permutation_excess_hit_by_date": permutation_test(E, "is_pick", "excess", strata_key="date"),
        "permutation_props_only_profit_by_date": permutation_test(
            [e for e in E if e["kind"] == "prop"], "is_pick", "profit", strata_key="date"),
        "permutation_props_only_excess_by_date": permutation_test(
            [e for e in E if e["kind"] == "prop"], "is_pick", "excess", strata_key="date"),
        "logit_excess_on_mm_and_class": _excess_regression(E),
    }

    # Q4 volume and vig
    days = defaultdict(list)
    for e in E:
        days[e["date"]].append(e)
    per_day = [len(v) for v in days.values()]
    q4 = {
        "days": len(days),
        "bets_per_day_mean": _r(sum(per_day) / len(per_day), 2),
        "bets_per_day_dist": dict(sorted(Counter(per_day).items())),
        "mean_price": _r(sum(e["price"] for e in E) / len(E), 1),
        "mean_breakeven": _r(sum(e["breakeven"] for e in E) / len(E)),
        "mean_market_p": _r(sum(e["market_p"] for e in E) / len(E)),
        "mean_vig_gap_pts": _r(100 * sum(e["vig_gap"] for e in E) / len(E), 2),
        "vig_cost_units_total_at_market": _r(sum(e["ev_mkt"] for e in E), 2),
        "vig_cost_units_per_bet": _r(sum(e["ev_mkt"] for e in E) / len(E), 4),
        "realised_hit": _r(sum(e["won"] for e in E) / len(E)),
    }
    ordered = published_order(E)
    caps = {}
    for cap in (1, 2, 3, 5, 99):
        sel = [e for es in ordered.values() for e in es[:cap]]
        caps[str(cap)] = summarise(sel)
    q4["volume_cap_rank_order_HINDSIGHT"] = caps
    ordered_c = {d: sorted(es, key=lambda e: (e["first_shown_utc"] or "", es.index(e)))
                 for d, es in ordered.items()}
    caps_c = {}
    for cap in (1, 2, 3, 5):
        sel = [e for es in ordered_c.values() for e in es[:cap]]
        caps_c[str(cap)] = summarise(sel)
    q4["volume_cap_chronological_HINDSIGHT"] = caps_c
    rules = {
        "as_published": E,
        "plus_money_only": [e for e in E if e["price"] > 0],
        "drop_plus_money": [e for e in E if e["price"] < 0],
        "props_no_worse_than_-115_(games_kept)": [
            e for e in E if not (e["kind"] == "prop" and e["price"] < -115)],
        "props_no_worse_than_-115_only_props": [
            e for e in E if e["kind"] == "prop" and e["price"] >= -115],
        "moneylines_only": [e for e in E if e["kind"] == "game"],
        "props_only": [e for e in E if e["kind"] == "prop"],
        "drop_total_bases": [e for e in E if e["market"] != "batter_total_bases"],
        "fills_only": [e for e in E if e["entry_class"] == "fill"],
        "picks_only": [e for e in E if e["entry_class"] == "pick"],
        "mm_le_0.06": [e for e in E if e["mm"] <= 0.06],
        "mm_gt_0.06": [e for e in E if e["mm"] > 0.06],
        "breakeven_le_0.56": [e for e in E if e["breakeven"] <= 0.56],
        "books_ge_3": [e for e in E if (e["books"] or 0) >= 3],
        "hits_overs_only": [e for e in E if e["market"] == "batter_hits" and e["side"] == "Over"],
        "unders_only": [e for e in E if e["side"] == "Under"],
    }
    q4["alternative_rules_HINDSIGHT"] = {k: summarise(v) for k, v in rules.items()}

    thin_be = [e for e in E if e["used"] < e["breakeven"]]
    thin_56 = [e for e in E if e["used"] < 0.56]
    q4["thin_edges"] = {
        "_definition": "used = our_probability_used (raw minus 0.038 markdown). "
                       "`below_own_breakeven`: the system's own marked-down number "
                       "says the bet loses money at its own price.",
        "below_own_breakeven": summarise(thin_be),
        "below_own_breakeven_by_class_gate": dict(Counter(
            f"{e['entry_class']}|{'+'.join(e['failed_gates']) or 'none'}" for e in thin_be)),
        "below_0.56": summarise(thin_56),
        "below_0.56_by_class_gate": dict(Counter(
            f"{e['entry_class']}|{'+'.join(e['failed_gates']) or 'none'}" for e in thin_56)),
        "raw_our_p_below_own_breakeven": summarise([e for e in E if e["our_p"] < e["breakeven"]]),
        "ev_at_own_used_number_units": _r(sum(e["ev_ours_used"] for e in E), 2),
        "ev_at_own_raw_number_units": _r(sum(e["our_p"] * dec(e["price"]) - 1 for e in E), 2),
    }
    res["q4"] = q4

    # Q6 staleness / single-book on the published set
    res["q6_published"] = {
        "by_age_at_first_show_min": table(
            [e for e in E if e["age_at_first_show_min"] is not None],
            lambda e: ("a:<=30" if e["age_at_first_show_min"] <= 30 else
                       "b:30-60" if e["age_at_first_show_min"] <= 60 else
                       "c:60-180" if e["age_at_first_show_min"] <= 180 else "d:>180")),
        "by_age_at_lock_min": table(
            [e for e in E if e["age_at_lock_min"] is not None],
            lambda e: ("a:<=30" if e["age_at_lock_min"] <= 30 else
                       "b:30-60" if e["age_at_lock_min"] <= 60 else
                       "c:60-180" if e["age_at_lock_min"] <= 180 else "d:>180")),
        "by_hours_before_first_pitch_of_quote": table(
            [e for e in E if e["lead_at_observed_h"] is not None],
            lambda e: ("a:<=4h" if e["lead_at_observed_h"] <= 4 else
                       "b:4-8h" if e["lead_at_observed_h"] <= 8 else
                       "c:8-16h" if e["lead_at_observed_h"] <= 16 else "d:>16h")),
        "props_by_books": table([e for e in E if e["kind"] == "prop"],
                                lambda e: str(e["books"])),
        "worst_10_by_ev_mkt": [
            {k: e[k] for k in ("date", "entry_class", "who", "market", "line", "side",
                               "price", "books", "market_p", "our_p", "won",
                               "age_at_first_show_min")}
            for e in sorted(E, key=lambda e: e["ev_mkt"])[:10]],
    }
    res["entries"] = [{k: v for k, v in e.items()} for e in E]
    return res


def _score_terciles(picks):
    s = sorted(picks, key=lambda e: e["score_calc"] or 0)
    n = len(s)
    if n < 3:
        return {}
    cut = [s[: n // 3], s[n // 3: 2 * n // 3], s[2 * n // 3:]]
    return {f"t{i+1}_low_to_high_score": summarise(c) for i, c in enumerate(cut)}


def _excess_regression(E):
    """OLS of realised-minus-market on [is_pick, mm, decimal]: is the pick/fill
    gap explained by the model gap or the price?"""
    X = [[1.0, 1.0 if e["is_pick"] else 0.0, e["mm"], dec(e["price"])] for e in E]
    y = [e["excess"] for e in E]
    beta = _lstsq(X, y)
    names = ["intercept", "is_pick", "mm", "decimal_odds"]

    def fit(sample):
        Xs = [[1.0, 1.0 if e["is_pick"] else 0.0, e["mm"], dec(e["price"])] for e in sample]
        return _lstsq(Xs, [e["excess"] for e in sample])

    rng = random.Random(SEED)
    by = defaultdict(list)
    for e in E:
        by[e["date"]].append(e)
    keys = sorted(by)
    boots = []
    for _ in range(1000):
        smp = []
        for _k in keys:
            smp.extend(by[keys[rng.randrange(len(keys))]])
        try:
            boots.append(fit(smp))
        except ZeroDivisionError:
            pass
    ci = {}
    for j, nm in enumerate(names):
        vals = sorted(b[j] for b in boots)
        ci[nm] = [_r(vals[int(0.025 * len(vals))]), _r(vals[int(0.975 * len(vals)) - 1])]
    return {nm: {"beta": _r(b), "ci95_date_bootstrap": ci[nm]} for nm, b in zip(names, beta)}


def _lstsq(X, y):
    """Normal equations, Gauss-Jordan (small k)."""
    k = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * yy for r, yy in zip(X, y)) for i in range(k)]
    M = [A[i] + [b[i]] for i in range(k)]
    for c in range(k):
        piv = max(range(c, k), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            raise ZeroDivisionError
        M[c], M[piv] = M[piv], M[c]
        for r in range(k):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [a - f * bb for a, bb in zip(M[r], M[c])]
    return [M[i][k] / M[i][i] for i in range(k)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "all"
    if cmd == "replay":
        build_replay()
        return 0
    sections = {name[len("section_"):]: fn for name, fn in globals().items()
                if name.startswith("section_") and callable(fn)}
    todo = sorted(sections) if cmd == "all" else [cmd]
    results = {}
    for name in todo:
        if name not in sections:
            print(f"unknown section {name}; have {sorted(sections)}", file=sys.stderr)
            return 2
        results[name] = sections[name]()
        path = os.path.join(OUT_DIR, f"selection_{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(results[name], fh, indent=1, sort_keys=True, default=str)
        print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
