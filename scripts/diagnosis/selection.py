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
                "observed_utc": g.get("observed_utc"),
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
# Q2 on the replayed candidate pool (props)
# ---------------------------------------------------------------------------

def _pkey(r):
    return (r["date"], r["player"], r["market"], str(r["line"]), r["side"])


def dedupe_run_pool(P):
    """One row per (date, player, market, line, side): the last run instance
    before first pitch - 4h (the lock lead), else the first instance; plus
    whether the identity was EVER pick-eligible / a close call on any run."""
    by = defaultdict(list)
    for r in P:
        if r["source"] == "run":
            by[_pkey(r)].append(r)
    out = []
    for k, rs in by.items():
        rs.sort(key=lambda r: r["now"])
        fp = _dt(rs[0]["first_pitch_utc"])
        before = [r for r in rs if fp and _dt(r["now"]) <= fp - timedelta(hours=4)]
        rep = dict(before[-1] if before else rs[0])
        rep["ever_pick_eligible"] = any(not r["failed_gates"] for r in rs)
        rep["ever_close_call"] = any(r["failed_gates"] and bbc.is_fill_eligible(r["failed_gates"])
                                     for r in rs)
        rep["n_runs_seen"] = len(rs)
        out.append(rep)
    return out


def _validation(P):
    """How faithfully the replay reproduces the ledger: per publish run, the
    share of the ledger's prop close calls, and of prop entries FIRST shown at
    that run, that the replay produced with the identical price and our
    number."""
    pubs = published_rows()
    by_run = defaultdict(dict)
    for r in P:
        if r["source"] == "run":
            by_run[(r["date"], r["now"])][_pkey(r)] = r
    seen_first = set()
    tot = Counter()
    for row in pubs:
        now = _dt(row["published_utc"]).isoformat()
        rep = by_run.get((row["date"], now))
        if rep is None:
            continue
        for c in row.get("close_calls_not_shown") or []:
            if c.get("kind") != "prop":
                continue
            k = (row["date"], c["player"], c["market"], str(c["line"]), c["side"])
            tot["close_calls"] += 1
            m = rep.get(k)
            if m and m["price"] == c["price"] and abs((m["our_p"] or 0) - (c["our_probability"] or 0)) < 1e-6:
                tot["close_calls_matched_exact"] += 1
            elif m:
                tot["close_calls_matched_identity_only"] += 1
        for c in row.get("all_bets") or []:
            if c.get("kind") != "prop":
                continue
            k = (row["date"], c["player"], c["market"], str(c["line"]), c["side"])
            if k in seen_first:
                continue
            seen_first.add(k)
            tot["entries_first_shown"] += 1
            m = rep.get(k)
            if m and m["price"] == c["price"] and abs((m["our_p"] or 0) - (c["our_probability"] or 0)) < 1e-6:
                tot["entries_matched_exact"] += 1
                if (not m["failed_gates"]) == (c.get("entry_class") == "pick"):
                    tot["entries_matched_class"] += 1
            elif m:
                tot["entries_matched_identity_only"] += 1
    return dict(tot)


def section_pool():
    P = load_replay()
    res = {"_note": "Prop candidates rebuilt from local stores through the "
                    "registered code path (propboard.build -> most_likely[:200] "
                    "-> best_bets_card.failed_gates) at every actual publish "
                    "instant, and the pregame-close board. Graded from box "
                    "scores. Open window only (2026-09-03 onward)."}
    res["validation_vs_ledger"] = _validation(P)
    run = [_enrich_pool(r) for r in dedupe_run_pool(P)]
    run_wl = [r for r in run if r["result"] in ("WIN", "LOSS") and r["market_p"] is not None]
    pub = {}
    for e in ledger_entries():
        if e["kind"] == "prop":
            pub[(e["date"], e["who"], e["market"], str(e["line"]), e["side"])] = e["entry_class"]
    for r in run_wl:
        r["published_as"] = pub.get(_pkey(r), "not_published")
    order = [b for _, _, b in MM_EDGES]
    res["run_pool"] = {
        "n_identities": len(run), "n_graded_wl": len(run_wl),
        "by_v2_class": table(run_wl, lambda r: r["v2_class"]),
        "by_published_as": table(run_wl, lambda r: r["published_as"]),
        "hit_by_mm_all": table(run_wl, lambda r: mm_bucket(r["mm"]), order),
        "hit_by_mm_pick_eligible": table([r for r in run_wl if r["v2_class"] == "pick_eligible"],
                                         lambda r: mm_bucket(r["mm"]), order),
        "hit_by_mm_not_published": table([r for r in run_wl if r["published_as"] == "not_published"],
                                         lambda r: mm_bucket(r["mm"]), order),
        "hit_by_mm_and_market": table(run_wl, lambda r: f"{r['market']}|{mm_bucket(r['mm'])}"),
        "shrinkage_all": shrinkage(run_wl),
        "shrinkage_by_market": {m: shrinkage([r for r in run_wl if r["market"] == m])
                                for m in sorted({r["market"] for r in run_wl})},
        "shrinkage_mm_0_to_10": shrinkage([r for r in run_wl if 0 <= r["mm"] <= 0.10]),
        "shrinkage_not_published": shrinkage([r for r in run_wl if r["published_as"] == "not_published"]),
        "hit_by_price_band": table(run_wl, lambda r: price_band(r["price"])),
        "hit_by_side": table(run_wl, lambda r: f"{r['market']}|{r['side']}"),
        "fail_reasons": dict(Counter("+".join(r["failed_gates"]) or "none" for r in run_wl).most_common(15)),
    }

    close = [_enrich_pool(dict(r)) for r in P if r["source"] == "close"]
    close_wl = [r for r in close if r["result"] in ("WIN", "LOSS") and r["market_p"] is not None]
    fav = [r for r in close_wl if r["our_p"] > 0.5]
    res["close_board"] = {
        "_note": "both sides of every assessable contract on the newest pregame "
                 "quotes; analysis restricted to the side our number favours "
                 "(our_p > 0.5), the card's own candidate side (one row per contract).",
        "n_contract_sides_wl": len(close_wl), "n_model_favoured": len(fav),
        "hit_by_mm": table(fav, lambda r: mm_bucket(r["mm"]), order),
        "hit_by_mm_card_window": table([r for r in fav if r["date"] >= "2026-09-22"],
                                       lambda r: mm_bucket(r["mm"]), order),
        "hit_by_mm_and_market": table(fav, lambda r: f"{r['market']}|{mm_bucket(r['mm'])}"),
        "shrinkage_all": shrinkage(fav),
        "shrinkage_card_window": shrinkage([r for r in fav if r["date"] >= "2026-09-22"]),
        "shrinkage_pre_card_window": shrinkage([r for r in fav if r["date"] < "2026-09-22"]),
        "shrinkage_by_market": {m: shrinkage([r for r in fav if r["market"] == m])
                                for m in sorted({r["market"] for r in fav})},
        "shrinkage_by_pa_source": {m: shrinkage([r for r in fav if r["expected_pa_source"] == m])
                                   for m in sorted({str(r["expected_pa_source"]) for r in fav})
                                   if any(str(r["expected_pa_source"]) == m for r in fav)},
        "v2_gate_window_mm_4_to_10": summarise([r for r in fav if 0.04 <= r["mm"] <= 0.10]),
        "v2_pick_eligible_at_close": summarise([r for r in fav if r["v2_class"] == "pick_eligible"]),
        "market_only_calibration": _market_calibration(fav),
        "model_only_calibration": _model_calibration(fav),
        "log_loss": _logloss(fav),
    }

    # CLV: did the market move toward our number between decision and close?
    close_mkt = {_pkey(r): r["market_p"] for r in close if r["market_p"] is not None}
    clv_rows = []
    for r in run:
        cm = close_mkt.get(_pkey(r))
        if cm is None or r["market_p"] is None:
            continue
        clv_rows.append({"date": r["date"], "mm": r["mm"], "clv": cm - r["market_p"],
                         "v2_class": r["v2_class"], "market": r["market"]})
    if clv_rows:
        xs = [c["mm"] for c in clv_rows]
        ys = [c["clv"] for c in clv_rows]
        a, b = ols(xs, ys)
        lo, hi = cluster_bootstrap(clv_rows, lambda s: ols([c["mm"] for c in s], [c["clv"] for c in s])[1])
        res["clv"] = {
            "_definition": "clv = close de-vigged market p - decision-time de-vigged market p, "
                           "same contract and side. Positive = market moved toward our side.",
            "n": len(clv_rows), "slope_clv_on_mm": _r(b), "slope_ci95": [_r(lo), _r(hi)],
            "intercept": _r(a),
            "mean_clv_by_mm_bucket": {
                k: {"n": len(v), "mean_clv_pts": _r(100 * sum(v) / len(v), 2)}
                for k, v in sorted(_group(clv_rows, lambda c: mm_bucket(c["mm"]),
                                          lambda c: c["clv"]).items())},
            "mean_clv_by_v2_class": {
                k: {"n": len(v), "mean_clv_pts": _r(100 * sum(v) / len(v), 2)}
                for k, v in sorted(_group(clv_rows, lambda c: c["v2_class"],
                                          lambda c: c["clv"]).items())},
        }

    # What the score actually rewards: regress it on its ingredients over every
    # fill-eligible candidate (picks + close calls), all graded or not.
    sd_rows = [r for r in run if r["v2_class"] in ("pick_eligible", "close_call")
               and r["market_p"] is not None]
    if sd_rows:
        X, y = [], []
        for r in sd_rows:
            X.append([1.0, r["mm"], r["breakeven"] - r["market_p"], dec(r["price"])])
            y.append(bbc.score(r["our_p"], r["price"], bbc.V2))
        beta = _lstsq(X, y)
        mms = [x[1] for x in X]
        vg = [x[2] for x in X]
        res["score_drivers"] = {
            "_definition": "score = Kelly fraction on (our_p - 0.038) at the best price; "
                           "regressed on model-minus-market (mm), vig gap (breakeven - market) "
                           "and decimal odds over all fill-eligible replayed candidates",
            "n": len(sd_rows),
            "beta": {"intercept": _r(beta[0]), "mm": _r(beta[1]), "vig_gap": _r(beta[2]),
                     "decimal": _r(beta[3])},
            "corr_score_mm": _corr(mms, y), "corr_score_vig_gap": _corr(vg, y),
            "sd_mm_pts": _r(100 * (sum((m - sum(mms) / len(mms)) ** 2 for m in mms) / len(mms)) ** 0.5, 2),
            "sd_vig_gap_pts": _r(100 * (sum((m - sum(vg) / len(vg)) ** 2 for m in vg) / len(vg)) ** 0.5, 2),
        }

    # Hindsight: alternative ranking keys over the same pick-eligible pool.
    elig = [r for r in run_wl if r["v2_class"] == "pick_eligible"]
    res["ranking_keys_HINDSIGHT"] = _ranking_keys(elig)
    res["ranking_keys_all_fill_eligible_HINDSIGHT"] = _ranking_keys(
        [r for r in run_wl if r["v2_class"] in ("pick_eligible", "close_call")])
    return res


def _group(rows, keyfn, valfn):
    g = defaultdict(list)
    for r in rows:
        g[keyfn(r)].append(valfn(r))
    return g


def _market_calibration(rows):
    g = defaultdict(list)
    for r in rows:
        b = min(9, int(r["market_p"] * 10))
        g[b].append(r)
    return {f"{b/10:.1f}-{(b+1)/10:.1f}": {"n": len(v), "pred": _r(sum(r['market_p'] for r in v) / len(v)),
                                         "hit": _r(sum(r['won'] for r in v) / len(v))}
            for b, v in sorted(g.items())}


def _model_calibration(rows):
    g = defaultdict(list)
    for r in rows:
        b = min(9, int(r["our_p"] * 10))
        g[b].append(r)
    return {f"{b/10:.1f}-{(b+1)/10:.1f}": {"n": len(v), "pred": _r(sum(r['our_p'] for r in v) / len(v)),
                                         "hit": _r(sum(r['won'] for r in v) / len(v)),
                                         "market_pred": _r(sum(r['market_p'] for r in v) / len(v))}
            for b, v in sorted(g.items())}


def _logloss(rows):
    def ll(p, y):
        p = min(max(p, 1e-6), 1 - 1e-6)
        return -(math.log(p) if y else math.log(1 - p))
    n = len(rows)
    lm = sum(ll(r["market_p"], r["won"]) for r in rows) / n
    lo = sum(ll(r["our_p"], r["won"]) for r in rows) / n
    best = None
    for w10 in range(0, 11):
        w = w10 / 10
        l = sum(ll(r["market_p"] + w * (r["our_p"] - r["market_p"]), r["won"]) for r in rows) / n
        if best is None or l < best[1]:
            best = (w, l)
    return {"n": n, "market": _r(lm, 5), "ours": _r(lo, 5), "ours_minus_market": _r(lo - lm, 5),
            "best_blend_weight_on_ours_grid": best[0], "best_blend_logloss": _r(best[1], 5)}


def _ranking_keys(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["date"]].append(r)
    keys = {
        "score_desc_(the_rule)": lambda r: -(bbc.score(r["our_p"], r["price"], bbc.V2) or 0),
        "mm_asc_(least_disagreement)": lambda r: r["mm"],
        "market_p_desc_(likeliest_by_market)": lambda r: -r["market_p"],
        "our_p_desc_(likeliest_by_model)": lambda r: -r["our_p"],
        "price_desc_(longest_price)": lambda r: -r["price"],
        "vig_gap_asc_(cheapest_vig)": lambda r: r["breakeven"] - r["market_p"],
    }
    out = {}
    for name, kf in keys.items():
        for cap in (1, 3):
            sel = []
            for d, rs in by.items():
                seen = set()
                for r in sorted(rs, key=lambda r: (kf(r), r["player"], r["market"])):
                    if r["player"] in seen:
                        continue
                    seen.add(r["player"])
                    sel.append(r)
                    if len([x for x in sel if x["date"] == d]) >= cap:
                        break
            out[f"{name}|top{cap}"] = summarise(sel)
    out["all_pool"] = summarise(rows)
    return out


# ---------------------------------------------------------------------------
# Q5 moneylines
# ---------------------------------------------------------------------------

def _logit(p):
    return math.log(p / (1 - p))


def _sig(z):
    return 1 / (1 + math.exp(-z))


def ledger_game_candidates():
    """Every moneyline candidate the card saw (all_bets, withdrawn, close calls,
    ceiling_refused), one per game per date: the last instance before first
    pitch - 4h, else the first. Graded from linescores."""
    results = game_results()
    by = defaultdict(list)
    for row in published_rows():
        for src in ("all_bets", "close_calls_not_shown", "ceiling_refused", "withdrawn"):
            for c in row.get(src) or []:
                if c.get("kind") != "game":
                    continue
                by[(row["date"], c.get("game_id"))].append((row["published_utc"], src, c))
    out = []
    for (date, gid), items in by.items():
        items.sort(key=lambda t: t[0])
        c0 = items[0][2]
        fp = _dt(c0.get("first_pitch_utc") or c0.get("first_pitch"))
        before = [t for t in items if fp and _dt(t[0]) <= fp - timedelta(hours=4)]
        pu, src, c = before[-1] if before else items[0]
        res = results.get(str(c.get("game_pk")))
        g = cl.grade_pick(c, res or {})
        if g["result"] not in ("WIN", "LOSS"):
            continue
        mp, op = c.get("market_probability"), c.get("our_probability")
        if mp is None or op is None:
            continue
        out.append({
            "date": date, "game_id": gid, "side": c.get("side"), "home": c.get("side") == "home",
            "team": c.get("team_name"), "price": c["price"], "market_p": mp, "our_p": op,
            "mm": op - mp, "breakeven": implied(c["price"]),
            "won": g["result"] == "WIN", "profit": g["profit_units"],
            "ev_mkt": mp * dec(c["price"]) - 1, "src": src,
            # Frozen all_bets rows do not carry `calibrated` (not a V2 frozen
        # field); every published game entry was calibrated, so default True.
        "failed_gates": bbc.failed_gates(dict(c, observed_utc=_dt(c.get("observed_utc")),
                                              calibrated=c.get("calibrated", True)),
                                         now=_dt(pu), params=bbc.V2),
        })
    return out


def _wager_key(r):
    """decisions_v2 <-> paper_wagers_v2 join. `selection_id` is NOT unique
    (56 values over 5,152 wagers), so the join is on the decision's own
    identity: event, decision instant, system."""
    return (r.get("event_id"), r.get("decision_utc"), r.get("system_id"))


def _wager_index():
    return {_wager_key(r): r for r in _jsonl(os.path.join("evidence", "paper_wagers_v2.jsonl"))}


def section_moneyline():
    E = [e for e in ledger_entries() if e["kind"] == "game"]
    res = {}
    res["entries"] = [{k: e[k] for k in ("date", "who", "side", "price", "market_p", "our_p",
                                        "mm", "entry_class", "failed_gates", "won", "profit",
                                        "withdrawn")} for e in E]
    res["summary"] = {
        "all": summarise(E),
        "home_share": _r(sum(1 for e in E if e["home"]) / len(E), 3),
        "by_home": table(E, lambda e: "home" if e["home"] else "away"),
        "by_price_band": table(E, lambda e: price_band(e["price"])),
        "by_entry_class_gate": table(E, lambda e: f"{e['entry_class']}|{'+'.join(e['failed_gates']) or 'none'}"),
        "mean_mm_pts": _r(100 * sum(e["mm"] for e in E) / len(E), 2),
        "all_favourites_by_market": all(e["market_p"] > 0.5 for e in E),
        "all_negative_price": all(e["price"] < 0 for e in E),
    }
    frozen = json.load(open(os.path.join("data", "processed", "card_v2_frozen_params.json")))
    cal = frozen["moneyline_calibration"]
    a, b = cal["a"], cal["b"]
    res["frozen_calibration"] = {
        "a": a, "b": b, "fitted_on": "2025 (tuning season, frozen 2026-09-15)",
        "home_bump_at_raw_0.50_pts": _r(100 * (_sig(a) - 0.5), 2),
        "calibrated_home_at_raw": {str(p): _r(_sig(a + b * _logit(p))) for p in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65)},
        "_reading": "p_home = sigmoid(a + b*logit(raw)). b < 1 pulls every raw number "
                    "toward 0.5; a > 0 adds a constant home lean. Applied to p_home, so "
                    "an away side gets the lean subtracted.",
    }
    G = ledger_game_candidates()
    xs = [g["market_p"] for g in G]
    ys = [g["our_p"] for g in G]
    n = len(G)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    X = [[1.0, x, 1.0 if g["home"] else 0.0] for x, g in zip(xs, G)]
    beta = _lstsq(X, ys)
    resid = [y - (beta[0] + beta[1] * x + beta[2] * h[2]) for x, y, h in zip(xs, ys, X)]
    res["favoured_side_pool"] = {
        "_note": "every market-favoured moneyline side the card evaluated (the registered "
                 "path builds only that side), one per game per date, graded from linescores",
        "n": n, "corr_our_vs_market": _r(cov / (sx * sy)),
        "sd_market": _r(sx), "sd_ours": _r(sy),
        "ours_on_market_and_home": {"intercept": _r(beta[0]), "slope_market": _r(beta[1]),
                                    "home_coef_pts": _r(100 * beta[2], 2),
                                    "resid_sd_pts": _r(100 * math.sqrt(sum(r * r for r in resid) / n), 2)},
        "home_share": _r(sum(g["home"] for g in G) / n, 3),
        "mean_mm_pts_home": _r(100 * sum(g["mm"] for g in G if g["home"]) / max(1, sum(g["home"] for g in G)), 2),
        "mean_mm_pts_away": _r(100 * sum(g["mm"] for g in G if not g["home"]) / max(1, sum(not g["home"] for g in G)), 2),
        "hit_all": summarise(G),
        "hit_by_home": table(G, lambda g: "home" if g["home"] else "away"),
        "hit_by_mm": table(G, lambda g: mm_bucket(g["mm"]), [x for _, _, x in MM_EDGES]),
        "hit_by_gate_status": table(G, lambda g: (
            "pick_eligible" if not g["failed_gates"] else
            "close_call" if bbc.is_fill_eligible(g["failed_gates"]) else "hard_fail")),
        "hard_fail_reasons": dict(Counter("+".join(g["failed_gates"]) for g in G
                                          if g["failed_gates"] and not bbc.is_fill_eligible(g["failed_gates"])).most_common(8)),
        "shrinkage": shrinkage(G),
    }
    # The engine's own h2h decisions: provenance of p_model on the card's games.
    card_pks = {str(e["game_pk"]) for e in E}
    wagers = _wager_index()
    prov = Counter()
    prov_card = Counter()
    for d in _jsonl(DECISIONS):
        if d.get("market_key") != "h2h":
            continue
        w = wagers.get(_wager_key(d)) or {}
        prov[(d["verdict"], d["p_model_provenance"])] += 1
        if str(w.get("game_pk")) in card_pks:
            prov_card[(d["verdict"], d["p_model_provenance"])] += 1
    res["engine_decisions_h2h"] = {
        "_note": "evidence/decisions_v2.jsonl is the Stage-16 paper engine "
                 "(selection_rule TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1), a separate "
                 "pipeline. The public card (src/report/card_v2.py) never reads it.",
        "all_h2h_verdict_provenance": {f"{k[0]}|{k[1]}": v for k, v in prov.items()},
        "on_the_29_card_moneyline_games": {f"{k[0]}|{k[1]}": v for k, v in prov_card.items()},
    }
    return res


# ---------------------------------------------------------------------------
# Q6 close calls, ceiling, refusals, stale boards
# ---------------------------------------------------------------------------

def section_closecalls():
    batters = [r for r in box_rows() if r.get("type") == "batter"]
    box_index = cl._index_prop_box_rows(batters)
    captured = cl._box_captured_game_pks(box_rows())
    results = game_results()
    shown = set()
    for e in ledger_entries():
        shown.add((e["date"], e["who"], e["market"], str(e["line"]), e["side"]))
    by = defaultdict(list)
    for row in published_rows():
        for src in ("close_calls_not_shown", "ceiling_refused", "plus_money_dropped_by_subcap"):
            for c in row.get(src) or []:
                who = c.get("player") or c.get("team_name")
                k = (row["date"], who, c.get("market"), str(c.get("line")), c.get("side"))
                by[(src,) + k].append((row["published_utc"], c))
    rows = []
    for key, items in by.items():
        src, date = key[0], key[1]
        if key[1:] in shown:
            continue  # later published as a pick/fill: graded on the ledger already
        items.sort(key=lambda t: t[0])
        c = items[-1][1]
        fp = _dt(c.get("first_pitch_utc") or c.get("first_pitch"))
        before = [t for t in items if fp and _dt(t[0]) <= fp - timedelta(hours=4)]
        c = (before[-1] if before else items[0])[1]
        if c.get("kind") == "prop":
            g = cl.grade_prop_pick(c, box_index, box_captured_game_pks=captured)
        else:
            g = cl.grade_pick(c, results.get(str(c.get("game_pk"))) or {})
        if g["result"] not in ("WIN", "LOSS"):
            continue
        mp, op = c.get("market_probability"), c.get("our_probability")
        if mp is None or op is None:
            continue
        rows.append({"src": src, "date": date, "kind": c.get("kind"), "market": c.get("market"),
                     "price": c["price"], "market_p": mp, "our_p": op, "mm": op - mp,
                     "breakeven": implied(c["price"]), "won": g["result"] == "WIN",
                     "profit": g["profit_units"], "ev_mkt": mp * dec(c["price"]) - 1,
                     "books": c.get("books"),
                     "failed_gates": "+".join(c.get("failed_gates") or []) or "none"})
    res = {
        "_note": "Entries that were close calls (or ceiling-refused) on some publish run "
                 "and were NEVER published as a pick or fill that date; graded here at "
                 "their last pre-lock-window instance. Hindsight only.",
        "by_source": table(rows, lambda r: r["src"]),
        "close_calls_by_kind_gate": table([r for r in rows if r["src"] == "close_calls_not_shown"],
                                          lambda r: f"{r['kind']}|{r['failed_gates']}"),
        "close_calls_by_mm": table([r for r in rows if r["src"] == "close_calls_not_shown"],
                                   lambda r: mm_bucket(r["mm"]), [x for _, _, x in MM_EDGES]),
        "ceiling_refused_by_kind": table([r for r in rows if r["src"] == "ceiling_refused"],
                                         lambda r: f"{r['kind']}|{r['failed_gates']}"),
        "n_publish_rows_with_ceiling_refusal": sum(1 for r in published_rows() if r.get("ceiling_refused")),
        "n_publish_rows_with_subcap_drop": sum(1 for r in published_rows() if r.get("plus_money_dropped_by_subcap")),
        "n_publish_rows_stale_board": sum(1 for r in published_rows() if r.get("stale_board")),
    }
    # Engine refusals (separate pipeline): grade the paper h2h wagers by verdict.
    wagers = _wager_index()
    eng = []
    for d in _jsonl(DECISIONS):
        w = wagers.get(_wager_key(d))
        if not w or w.get("market_key") != "h2h" or not _open(w.get("date")):
            continue
        res_g = results.get(str(w.get("game_pk")))
        if not res_g or w.get("price_american") is None or w.get("side") not in ("home", "away"):
            continue
        won = (res_g["home_score"] > res_g["away_score"]) == (w["side"] == "home")
        if res_g["home_score"] == res_g["away_score"]:
            continue
        mp = d.get("consensus_fair")
        eng.append({"date": w["date"], "verdict": d["verdict"], "prov": d["p_model_provenance"],
                    "price": w["price_american"], "won": won,
                    "profit": profit(w["price_american"], won),
                    "market_p": mp, "breakeven": implied(w["price_american"]),
                    "ev_mkt": (mp * dec(w["price_american"]) - 1) if mp is not None else None,
                    "books": d.get("books_at_decision")})
    res["engine_h2h_by_verdict_SEPARATE_PIPELINE"] = table(eng, lambda r: f"{r['verdict']}|{r['prov']}")
    return res


# ---------------------------------------------------------------------------
# Q1 trace
# ---------------------------------------------------------------------------

def section_trace():
    E = ledger_entries()
    days = defaultdict(list)
    for e in E:
        days[e["date"]].append(e)
    rec = {d: (sum(e["won"] for e in es), sum(not e["won"] for e in es),
               round(sum(e["profit"] for e in es), 2)) for d, es in days.items()}
    three_oh = [d for d, (w, l, u) in rec.items() if w == 3 and l == 0]
    best = max(rec, key=lambda d: rec[d][2])
    worst = min(rec, key=lambda d: rec[d][2])
    chosen = {"winning_day": best, "losing_day": worst,
              "three_oh_day": three_oh[0] if three_oh else None}
    world = PropWorld()
    out = {"records_by_day": {d: list(v) for d, v in sorted(rec.items())},
           "three_oh_days": three_oh, "chosen": chosen, "traces": {}}
    pubs = published_rows()
    for label, date in chosen.items():
        if not date:
            continue
        runs = [r for r in pubs if r["date"] == date]
        run_summ = []
        funnel = Counter()
        for r in runs:
            now = _dt(r["published_utc"])
            cands = world.candidates(date, now)
            gate_first = Counter()
            for c in cands:
                f = bbc.failed_gates(c, now=now, params=bbc.V2)
                gate_first["+".join(f) if f else "PASS"] += 1
                for g in f:
                    funnel[g] += 1
            game_cc = sum(1 for c in r.get("close_calls_not_shown") or [] if c.get("kind") == "game")
            game_shown = sum(1 for c in r.get("all_bets") or [] if c.get("kind") == "game")
            run_summ.append({
                "published_utc": r["published_utc"],
                "prop_candidates_replayed": len(cands),
                "prop_pass_all_gates": gate_first.get("PASS", 0),
                "top_fail_patterns": dict(gate_first.most_common(5)),
                "ledger_n_picks": r.get("n_picks"), "ledger_n_fills": r.get("n_fills"),
                "ledger_all_bets": len(r.get("all_bets") or []),
                "ledger_close_calls_not_shown": len(r.get("close_calls_not_shown") or []),
                "ledger_game_close_calls": game_cc, "ledger_game_entries": game_shown,
                "ceiling_refused": len(r.get("ceiling_refused") or []),
            })
        graded = sorted(days[date], key=lambda e: (e["entry_class"] != "pick", -(e["score_calc"] or 0)))
        out["traces"][label] = {
            "date": date, "record": rec[date], "n_publish_runs": len(runs),
            "runs": run_summ,
            "gate_failure_counts_over_all_runs": dict(funnel.most_common()),
            "graded_entries": [{
                "entry_class": e["entry_class"], "withdrawn": e["withdrawn"], "who": e["who"],
                "market": e["market"], "line": e["line"], "side": e["side"], "price": e["price"],
                "books": e["books"], "market_p": _r(e["market_p"]), "our_p": _r(e["our_p"]),
                "mm_pts": _r(100 * e["mm"], 1), "score": _r(e["score_calc"]),
                "value_need": _r(e["value_need"]), "used": _r(e["used"]),
                "failed_gates": e["failed_gates"], "first_shown_run": e["first_shown_run"],
                "won": e["won"], "profit": e["profit"]} for e in graded],
        }
    return out


# ---------------------------------------------------------------------------
# Q4 addendum: best price vs the average of books, on published props
# ---------------------------------------------------------------------------

def section_pricing():
    """Every published prop entry: the price it was graded at (the BEST quote
    across books) against the mean of the books' own quotes for the same side
    at the same observation (newest quote per book at or before the entry's
    observed_utc)."""
    world = PropWorld()
    E = [e for e in ledger_entries() if e["kind"] == "prop"]
    rows = []
    for e in E:
        quotes = {}
        for r in world.rows_by_date.get(e["date"]) or []:
            if (r.get("player") != e["who"] or r.get("market") != e["market"]
                    or str(r.get("line")) != str(e["line"]) or r.get("side") != e["side"]):
                continue
            eo = _dt(e.get("observed_utc"))
            if eo is not None and r["_obs"] is not None and r["_obs"] > eo:
                continue
            held = quotes.get(r["book"])
            if held is None or r["_obs"] > held[0]:
                quotes[r["book"]] = (r["_obs"], r["price"])
        if not quotes:
            continue
        decs = [dec(p) for _, p in quotes.values()]
        mean_dec = sum(decs) / len(decs)
        rows.append({"date": e["date"], "entry_class": e["entry_class"], "won": e["won"],
                     "best_dec": dec(e["price"]), "mean_dec": mean_dec, "n_books": len(decs),
                     "profit_best": e["profit"],
                     "profit_mean": (mean_dec - 1.0) if e["won"] else -1.0})
    n = len(rows)
    return {
        "_note": "The ledger grades every entry at `price`, the BEST quote across books "
                 "(propboard.fair_and_best / opportunities best_price). This re-grades the "
                 "same published props at the mean of the books' quotes (decimal mean).",
        "n_props_priced": n,
        "mean_best_decimal": _r(sum(r["best_dec"] for r in rows) / n),
        "mean_avg_decimal": _r(sum(r["mean_dec"] for r in rows) / n),
        "units_at_best": _r(sum(r["profit_best"] for r in rows), 2),
        "units_at_mean_of_books": _r(sum(r["profit_mean"] for r in rows), 2),
        "by_class": {cls: {"n": len(s), "units_at_best": _r(sum(r["profit_best"] for r in s), 2),
                           "units_at_mean": _r(sum(r["profit_mean"] for r in s), 2)}
                     for cls, s in (("pick", [r for r in rows if r["entry_class"] == "pick"]),
                                    ("fill", [r for r in rows if r["entry_class"] == "fill"]))},
    }


# ---------------------------------------------------------------------------
# Q2 for 2024: the moneyline model rebuilt pre-game, frozen numbers, point-in-time
# ---------------------------------------------------------------------------

ODDS_2024 = os.path.join("data", "archive", "historical", "odds_history", "mlb_2024.jsonl.gz")
RESULTS_CSV = os.path.join("data", "historical", "mlb_results.csv")
PITCHER_LOGS = os.path.join("data", "historical", "pitcher_logs.jsonl")
BULLPEN_LOG = os.path.join("data", "historical", "bullpen_log.jsonl")


def _season_ok(date):
    """2023 (prior-season context) and 2024 only. Every other row -- 2025
    tuning, the sealed 2026 window, the 2026 forward window -- is dropped on
    its date column before any other field is kept."""
    d = str(date or "")[:4]
    return d in ("2023", "2024")


def _pregame_h2h_2024():
    """{event_id: {commence, home, away, quotes{book: (home_price, away_price)}}}
    from the newest archive poll strictly before each event's commence time.
    `snapshot_at` is the observation time (src/board/l1_historical.py)."""
    best = {}
    for poll in _jsonl(ODDS_2024):
        snap = _dt(poll.get("snapshot_at"))
        for ev in poll.get("events") or []:
            ct = _dt(ev.get("commence_time"))
            if ct is None or snap is None or snap >= ct or not _season_ok(ev["commence_time"]):
                continue
            held = best.get(ev["id"])
            if held is not None and held["snap"] >= snap:
                continue
            quotes = {}
            for bk in ev.get("bookmakers") or []:
                for m in bk.get("markets") or []:
                    if m.get("key") != "h2h":
                        continue
                    prices = {o["name"]: o["price"] for o in m.get("outcomes") or []}
                    hp, ap = prices.get(ev["home_team"]), prices.get(ev["away_team"])
                    if hp is not None and ap is not None:
                        quotes[bk["key"]] = (hp, ap)
            if quotes:
                best[ev["id"]] = {"snap": snap, "commence": ct, "home": ev["home_team"],
                                  "away": ev["away_team"], "quotes": quotes}
    return best


def section_y2024():
    import csv
    from src.analysis import calibrate, strength
    from src.pipeline import bullpen, features as features_mod
    from src.pipeline import slate as slate_mod

    store = {}
    with open(RESULTS_CSV, newline="", encoding="utf-8") as h:
        for row in csv.DictReader(h):
            if not _season_ok(row.get("date")):
                continue
            store[row["game_pk"]] = {k: (v if v != "" else None) for k, v in row.items()}
    logs = {}
    for r in _jsonl(PITCHER_LOGS):
        if not _season_ok(r.get("date")):
            continue
        logs.setdefault(str(r["person_id"]), []).append(r)
    for v in logs.values():
        v.sort(key=lambda a: a.get("date") or "")
    pen = [r for r in _jsonl(BULLPEN_LOG) if _season_ok(r.get("date"))]
    frozen = json.load(open(os.path.join("data", "processed", "card_v2_frozen_params.json")))
    mc = frozen["moneyline_calibration"]
    cal = calibrate.Calibration(mc["a"], mc["b"], mc["n"], mc["base_rate"])
    disp = frozen["DISPERSION"]

    tab = features_mod.build_training_table(store, min_date="2024-04-15", max_date="2024-12-31",
                                            pitcher_logs=logs, require_complete=True)
    rows = tab["rows"]
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    relief_cache = {}

    def relief(date):
        if date not in relief_cache:
            relief_cache[date] = {t: x.get("rate") for t, x in
                                  bullpen.relief_rates_by_team(pen, date).items() if x.get("rate")}
        return relief_cache[date]

    lines = {}
    for date, rs in by_date.items():
        league = strength.league_runs_per_game(rs)
        rel = relief(date)
        for r in rs:
            f = dict(r)
            f["away_bullpen_rate"] = rel.get(r["away_team"])
            f["home_bullpen_rate"] = rel.get(r["home_team"])
            try:
                ln = strength.model_line(f, league_rpg=league, dispersion=disp)
            except strength.StrengthError:
                continue
            lines[str(r["game_pk"])] = (cal.apply(ln["p_home"]), ln["p_home"])

    odds = _pregame_h2h_2024()
    # join events -> results by teams + start time within 6h
    by_teams = defaultdict(list)
    for pk, g in store.items():
        if not str(g.get("date") or "").startswith("2024"):
            continue
        by_teams[(g["away_team"], g["home_team"])].append(g)
    cands = []
    unmatched = 0
    for eid, ev in odds.items():
        a = slate_mod.team_abbrev_from_name(ev["away"])
        h = slate_mod.team_abbrev_from_name(ev["home"])
        match = None
        for g in by_teams.get((a, h), []):
            st = _dt(g.get("start_time_utc"))
            if st and abs((st - ev["commence"]).total_seconds()) < 6 * 3600:
                match = g
                break
        if match is None or str(match["game_pk"]) not in lines:
            unmatched += 1
            continue
        if match.get("away_score") is None or match.get("home_score") is None:
            continue
        p_home, p_home_raw = lines[str(match["game_pk"])]
        fair_home = []
        best = {"home": None, "away": None}
        for hp, ap in ev["quotes"].values():
            try:
                fh, _fa = odds_math.devig_two_way(hp, ap)
            except (odds_math.OddsError, ZeroDivisionError, ValueError):
                continue
            fair_home.append(fh)
            for side, pr in (("home", hp), ("away", ap)):
                if best[side] is None or dec(pr) > dec(best[side]):
                    best[side] = pr
        if len(fair_home) < 1:
            continue
        mh = sum(fair_home) / len(fair_home)
        home_won = int(match["home_score"]) > int(match["away_score"])
        for side in ("home", "away"):
            mp = mh if side == "home" else 1 - mh
            op = p_home if side == "home" else 1 - p_home
            price = best[side]
            won = home_won if side == "home" else not home_won
            c = {"kind": "game", "price": price, "market_probability": mp, "our_probability": op,
                 "books": len(fair_home), "observed_utc": ev["snap"], "has_started": False,
                 "calibrated": True}
            fails = bbc.failed_gates(c, now=ev["snap"], params=bbc.V2)
            fails = [f for f in fails if f != bbc.G3_STALE]  # archive polls ~3/day; G3 not evaluable
            cands.append({"date": match["date"], "side": side, "home": side == "home",
                          "price": price, "market_p": mp, "our_p": op, "mm": op - mp,
                          "breakeven": implied(price), "won": won, "profit": profit(price, won),
                          "ev_mkt": mp * dec(price) - 1, "books": len(fair_home),
                          "fav": mp > 0.5, "failed_gates": fails,
                          "v2": ("pick_eligible" if not fails else
                                 "close_call" if bbc.is_fill_eligible(fails) else "hard_fail")})
    fav = [c for c in cands if c["fav"]]
    six = [c for c in cands if c["books"] >= 6]
    order = [b for _, _, b in MM_EDGES]
    res = {
        "_note": "2024 (open season). Run model strength.model_line with the FROZEN 2025 "
                 "dispersion and Platt calibration, point-in-time features "
                 "(features.build_training_table: games strictly before each date), "
                 "relief rates strictly before each date, league runs/game from that "
                 "date's own slate (as the live path does). Market = mean de-vigged "
                 "h2h across books on the newest archive poll strictly before first "
                 "pitch; price = best across books. G3 is not evaluable on a ~3-poll/day "
                 "archive and is dropped. Not agent 1's method (unavailable to this agent).",
        "n_games_modelled": len(lines), "n_events_with_pregame_odds": len(odds),
        "unmatched_events": unmatched, "n_sides": len(cands),
        "training_table_skipped": tab.get("skipped"),
        "both_sides_hit_by_mm": table(cands, lambda c: mm_bucket(c["mm"]), order),
        "favourite_side_hit_by_mm": table(fav, lambda c: mm_bucket(c["mm"]), order),
        "shrinkage_both_sides": shrinkage(cands),
        "shrinkage_favourite_side": shrinkage(fav),
        "shrinkage_books_ge_6": shrinkage(six),
        "by_v2_class_both_sides_books_ge_6": table(six, lambda c: c["v2"]),
        "by_v2_class_favourite_side_books_ge_6": table([c for c in six if c["fav"]], lambda c: c["v2"]),
        "v2_pick_eligible_by_price_class": table([c for c in six if c["v2"] == "pick_eligible"],
                                                 lambda c: bbc.price_class(c["price"])),
        "home_fav_vs_away_fav": table(fav, lambda c: "home_fav" if c["home"] else "away_fav"),
        "g6_fail_share_main_band_favourites": {
            lab: {"n": len(s), "g6_fail_share": _r(sum(bbc.G6_FLOOR in c["failed_gates"] for c in s) / len(s), 3),
                  "fill_eligible_or_pick_share": _r(sum(c["v2"] != "hard_fail" for c in s) / len(s), 3)}
            for lab, s in (
                ("home_fav", [c for c in six if c["fav"] and c["home"] and -160 <= c["price"] <= -100]),
                ("away_fav", [c for c in six if c["fav"] and not c["home"] and -160 <= c["price"] <= -100]))
            if s},
        "log_loss_home_side": _logloss([c for c in cands if c["home"]]),
        "corr_our_market_home_side": _corr([c["market_p"] for c in cands if c["home"]],
                                           [c["our_p"] for c in cands if c["home"]]),
    }
    return res


def _corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return _r(cov / (sx * sy))


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
