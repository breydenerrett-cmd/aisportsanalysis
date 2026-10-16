"""Loss diagnosis 01: where the prop probability estimates go wrong, and which way.

Research only. Reads stores, prices props through the card's own code path
(`src.analysis.propboard.build` -> `playerprops.price_prop`), scores them
against box-score outcomes, and writes small JSON/markdown outputs under
`data/research/loss_diagnosis/`. Edits no model file, no store, no ledger.

Run:
    python3 scripts/diagnosis/estimate_error.py            # everything
    python3 scripts/diagnosis/estimate_error.py --part published
    python3 scripts/diagnosis/estimate_error.py --part pool
    python3 scripts/diagnosis/estimate_error.py --part hist --season 2024

Evidence rules honoured here:
* 2026-01-01..2026-08-27 is sealed. `_ee_common` drops sealed rows on their
  date before any other field is read; the 2026 box store raises on one.
* 2025 is used only in sections labelled TUNING-ONLY.
* Every 2026 forward probability uses box rows strictly before the slate
  date and prop quotes observed strictly before the event's commence time.
  Two disclosed hindsights: the batting slot is the POSTED lineup as stored
  (a live card may price before it posts), and the opposing starter is the
  results file's probable id (first-pitch starter).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _ee_common as C  # noqa: E402

sys.path.insert(0, C.ROOT)
os.chdir(C.ROOT)

from src.analysis import playerprops, propboard  # noqa: E402
from src.appstate import card_ledger  # noqa: E402
from src.board import gamekey  # noqa: E402
from src.core import odds as odds_math  # noqa: E402
from src.report import props as props_mod  # noqa: E402

OUT_DIR = C.p("data", "research", "loss_diagnosis")
MARKETS = ("batter_hits", "batter_total_bases", "batter_runs_scored")
STAT = {"batter_hits": "h", "batter_total_bases": "total_bases",
        "batter_runs_scored": "r"}
FROZEN = json.load(open(C.p("data", "processed", "card_v2_frozen_params.json"),
                        encoding="utf-8"))
SLOT25 = {int(k): float(v) for k, v in FROZEN["slot_plate_appearances"].items()}
RHO25 = float(FROZEN["RHO"])
MARKDOWN = 0.038

TABLES = []   # (title, markdown) in order; written to estimate_error_tables.md


def emit(title, header, rows, note=None):
    lines = [f"### {title}", ""]
    if note:
        lines += [note, ""]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    text = "\n".join(lines) + "\n"
    TABLES.append(text)
    print(text)


@contextlib.contextmanager
def pa_regression(value):
    old = playerprops.PA_REGRESSION
    playerprops.PA_REGRESSION = float(value)
    try:
        yield
    finally:
        playerprops.PA_REGRESSION = old


def _safe_price(**kw):
    try:
        return playerprops.price_prop(**kw)["probability"]
    except playerprops.PropError:
        return None


def over_y(market, line, box_row):
    v = box_row.get(STAT[market])
    if v is None:
        return None
    return int(float(v) > float(line))


# ---------------------------------------------------------------------------
# Context shared by the 2026 parts
# ---------------------------------------------------------------------------

class Ctx2026:
    def __init__(self):
        box = C.load_box_2026()
        self.batters = [r for r in box if r.get("type") == "batter"]
        self.pitchers = [r for r in box if r.get("type") == "pitcher"]
        self.by_name = props_mod._by_name(self.batters)
        self.box_by_game_name = {}
        self.box_dates_by_name = defaultdict(set)
        for r in self.batters:
            self.box_by_game_name[(str(r["game_pk"]), r.get("player_name"))] = r
            self.box_dates_by_name[r.get("player_name")].add(str(r["date"])[:10])
        self.results = {k: v for k, v in C.load_results().items()
                        if str(v.get("date", ""))[:4] == "2026"}
        self.lineups = [r for r in C.load_lineups() if str(r["date"])[:4] == "2026"]
        self.slot_by_game_pid = {}
        self.slots_by_date_name = defaultdict(dict)
        for row in self.lineups:
            for side in ("away", "home"):
                for i, b in enumerate(row.get(side) or [], start=1):
                    try:
                        slot = int(b.get("order") or i)
                    except (TypeError, ValueError):
                        slot = i
                    if b.get("person_id") is not None:
                        self.slot_by_game_pid[(str(row["game_pk"]), int(b["person_id"]))] = slot
                    if b.get("name") and 1 <= slot <= 9:
                        self.slots_by_date_name[str(row["date"])[:10]][b["name"]] = slot
        self.hand = C.load_handedness()
        self.event_map = gamekey.load_map(C.p("data", "processed", "event_game_map.jsonl"))
        # 2025 rows (TUNING-ONLY covariates): pitcher hits/BF and batter lines.
        self.p25 = defaultdict(lambda: [0, 0])
        self.b25_by_name = defaultdict(list)
        for r in C.load_box_archive(2025):
            if r.get("type") == "pitcher" and r.get("player_id") is not None:
                acc = self.p25[int(r["player_id"])]
                acc[0] += int(r.get("h") or 0)
                acc[1] += int(r.get("batters_faced") or 0)
            elif r.get("type") == "batter" and r.get("player_name"):
                self.b25_by_name[r["player_name"]].append(r)
        self._league_cache = {}

    def league(self, date):
        if date not in self._league_cache:
            hist = [r for r in self.batters if str(r["date"])[:10] < date]
            self._league_cache[date] = playerprops.league_rates(hist) if hist else None
        return self._league_cache[date]

    def starter_prior_fwd(self, pid, date):
        if not hasattr(self, "_p_idx"):
            self._p_idx = defaultdict(list)
            for r in self.pitchers:
                if r.get("player_id") is not None:
                    self._p_idx[int(r["player_id"])].append(
                        (str(r["date"])[:10], int(r.get("h") or 0), int(r.get("batters_faced") or 0)))
        h = bf = 0
        for d, hh, b in self._p_idx.get(pid, ()):
            if d < date:
                h += hh
                bf += b
        return (h, bf) if bf > 0 else None

    def opp_starter(self, game_pk, batter_side):
        res = self.results.get(int(game_pk)) if game_pk is not None else None
        if not res or batter_side not in ("home", "away"):
            return None
        raw = res.get("home_probable_id" if batter_side == "away" else "away_probable_id")
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    def game_type(self, game_pk):
        res = self.results.get(int(game_pk)) if game_pk is not None else None
        return (res or {}).get("game_type")


def starter_cols(ctx, game_pk, side, date, league_hit):
    pid = ctx.opp_starter(game_pk, side)
    out = {"starter_id": pid, "starter_throws": None, "f_fwd": None, "f_25fwd": None,
           "st_fwd": None, "st_25fwd": None}
    if pid is None:
        return out
    out["starter_throws"] = (ctx.hand.get(str(pid)) or {}).get("throws")
    fwd = ctx.starter_prior_fwd(pid, date)
    h25, bf25 = ctx.p25.get(pid, [0, 0])
    comb = ((fwd[0] if fwd else 0) + h25, (fwd[1] if fwd else 0) + bf25)
    out["st_fwd"] = fwd
    out["st_25fwd"] = comb if comb[1] > 0 else None
    if fwd:
        out["f_fwd"] = playerprops.pitcher_hit_factor(fwd[0], fwd[1], league_hit)
    if comb[1] > 0:
        out["f_25fwd"] = playerprops.pitcher_hit_factor(comb[0], comb[1], league_hit)
    return out


# ---------------------------------------------------------------------------
# Part 1: the published, graded props
# ---------------------------------------------------------------------------

def published_props():
    hist = card_ledger.history_v2(path=C.p("evidence", "cards_v2.jsonl"), limit=None)
    out = []
    for day in hist["days"]:
        for e in day["graded"]:
            if e.get("kind") != "prop":
                continue
            out.append(dict(e, date=day["date"]))
    return out


def price_bucket(price):
    if price is None:
        return "n/a"
    if price >= 100:
        return "+100 or longer"
    if price >= -120:
        return "-120 to -100"
    if price >= -140:
        return "-140 to -121"
    return "-160 to -141"


def games_bucket(g):
    if g is None:
        return "n/a"
    return "15-19" if g < 20 else ("20-24" if g < 25 else "25+")


def slot_bucket(s):
    if s is None:
        return "not in stored lineup"
    return "1-3" if s <= 3 else ("4-6" if s <= 6 else "7-9")


def pa_bucket(pa):
    if pa is None:
        return "no box row"
    return "<=3" if pa <= 3 else ("4" if pa == 4 else "5+")


def bias_table(rows, keyfn, pkey, ykey="y", mkey=None, order=None):
    groups = defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    keys = order or sorted(groups, key=str)
    table = []
    for k in keys:
        g = groups.get(k)
        if not g:
            continue
        n = len(g)
        mp = C.mean(r[pkey] for r in g)
        hr = C.mean(r[ykey] for r in g)
        row = [k, n, C.fmt(mp), C.fmt(hr), C.pts(mp - hr)]
        if mkey:
            mm = C.mean(r[mkey] for r in g)
            row += [C.fmt(mm), C.pts(mm - hr)]
        table.append(row)
    return table


def reliability(rows, pkey, ykey="y", edges=(0.0, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 1.0001)):
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = [r for r in rows if lo <= r[pkey] < hi]
        if not g:
            continue
        mp = C.mean(r[pkey] for r in g)
        hr = C.mean(r[ykey] for r in g)
        out.append([f"{lo:.2f}-{min(hi, 1):.2f}", len(g), C.fmt(mp), C.fmt(hr), C.pts(mp - hr)])
    return out


def score_block(rows, arms, ykey="y"):
    table = []
    for name, key in arms:
        b = C.mean(C.brier(r[key], r[ykey]) for r in rows)
        l = C.mean(C.ll(r[key], r[ykey]) for r in rows)
        table.append([name, len(rows), C.fmt(b, 4), C.fmt(l, 4), C.pts(C.mean(r[key] - r[ykey] for r in rows))])
    return table


def paired(rows, a, b, ykey="y", metric="ll"):
    f = C.ll if metric == "ll" else C.brier
    return C.clustered_boot(rows, lambda r: f(r[a], r[ykey]) - f(r[b], r[ykey]))


def run_published(ctx, pool_index=None):
    raw = published_props()
    graded = [e for e in raw if e.get("result") in ("WIN", "LOSS")]
    rows = []
    for e in graded:
        pk = str(e.get("game_pk"))
        box = ctx.box_by_game_name.get((pk, e.get("player")))
        side = box.get("side") if box else None
        lg = ctx.league(e["date"])
        st = starter_cols(ctx, e.get("game_pk"), side, e["date"], lg["hit"] if lg else None) if lg else {}
        slot = ctx.slot_by_game_pid.get((pk, int(box["player_id"]))) if box else None
        rows.append({
            "date": e["date"], "market": e["market"], "side": e["side"], "line": e["line"],
            "player": e["player"], "game_pk": pk, "price": e["price"],
            "our": float(e["our_probability"]), "used": float(e["our_probability_used"]),
            "mkt": float(e["market_probability"]), "be": float(e["breakeven"]),
            "y": 1 if e["result"] == "WIN" else 0, "profit": float(e.get("profit_units") or 0),
            "season_games": e.get("season_games"), "src": e.get("expected_pa_source"),
            "lineup_posted": bool(e.get("lineup_posted")), "entry_class": e.get("entry_class"),
            "slot": slot, "home_away": side or "no box row", "pa": box.get("pa") if box else None,
            "game_type": ctx.game_type(e.get("game_pk")) or "n/a",
            "throws": st.get("starter_throws") or "unknown", "f_25fwd": st.get("f_25fwd"),
        })
    n_void = sum(1 for e in raw if e.get("result") == "VOID")
    n_unres = sum(1 for e in raw if e.get("result") == "UNRESOLVED")
    profit = sum(r["profit"] for r in rows)
    wins = sum(r["y"] for r in rows)
    emit("P0. Published graded props: population",
         ["graded W/L", "wins", "losses", "units", "void", "unresolved", "dates"],
         [[len(rows), wins, len(rows) - wins, C.fmt(profit, 2, True), n_void, n_unres,
           len({r['date'] for r in rows})]],
         note="Source: `card_ledger.history_v2(path='evidence/cards_v2.jsonl')`, kind == prop.")

    emit("P1. Published props: scores, ours vs market (same bets)",
         ["arm", "n", "Brier", "log loss", "mean p minus hit rate (pts)"],
         score_block(rows, [("our_probability", "our"), ("our_probability_used (minus 0.038)", "used"),
                            ("market de-vigged", "mkt"), ("breakeven of price taken", "be")]))
    d_ll = paired(rows, "our", "mkt", metric="ll")
    d_br = paired(rows, "our", "mkt", metric="brier")
    d_bias = C.clustered_boot(rows, lambda r: r["our"] - r["y"])
    d_mbias = C.clustered_boot(rows, lambda r: r["mkt"] - r["y"])
    emit("P2. Published props: paired differences, date-clustered bootstrap (2,000, seed 20261016)",
         ["quantity", "point", "95% low", "95% high"],
         [["log loss ours minus market (nats, + = ours worse)", C.fmt(d_ll[0], 4, True), C.fmt(d_ll[1], 4, True), C.fmt(d_ll[2], 4, True)],
          ["Brier ours minus market", C.fmt(d_br[0], 4, True), C.fmt(d_br[1], 4, True), C.fmt(d_br[2], 4, True)],
          ["bias ours (p minus hit), pts", C.pts(d_bias[0]), C.pts(d_bias[1]), C.pts(d_bias[2])],
          ["bias market (p minus hit), pts", C.pts(d_mbias[0]), C.pts(d_mbias[1]), C.pts(d_mbias[2])]])
    emit("P3. Published props: reliability of our_probability",
         ["our p bin", "n", "mean our p", "hit rate", "bias pts"], reliability(rows, "our"))
    emit("P3b. Published props: reliability of market probability (same bets)",
         ["market p bin", "n", "mean market p", "hit rate", "bias pts"], reliability(rows, "mkt"))
    H = ["group", "n", "mean our p", "hit rate", "our bias pts", "mean market p", "market bias pts"]
    dims = [
        ("market", lambda r: r["market"]),
        ("side", lambda r: r["side"]),
        ("market x side x line", lambda r: f"{r['market']} {r['side']} {r['line']}"),
        ("price bucket", lambda r: price_bucket(r["price"])),
        ("season_games bucket", lambda r: games_bucket(r["season_games"])),
        ("expected_pa_source", lambda r: r["src"]),
        ("lineup_posted", lambda r: r["lineup_posted"]),
        ("batting slot (stored lineup)", lambda r: slot_bucket(r["slot"])),
        ("home/away", lambda r: r["home_away"]),
        ("opposing starter throws", lambda r: r["throws"]),
        ("entry_class", lambda r: r["entry_class"]),
        ("game type (R regular, D/F/L/W post)", lambda r: "R" if r["game_type"] == "R" else ("post" if r["game_type"] != "n/a" else "n/a")),
        ("actual PA in the game", lambda r: pa_bucket(r["pa"])),
    ]
    for name, fn in dims:
        emit(f"P4. Published props: bias by {name}", H, bias_table(rows, fn, "our", mkey="mkt"))
    # starter quality tercile (2025 + forward-window hits/BF, TUNING-ONLY 2025 input)
    fs = sorted(r["f_25fwd"] for r in rows if r["f_25fwd"] is not None)
    if len(fs) >= 9:
        t1, t2 = fs[len(fs) // 3], fs[2 * len(fs) // 3]

        def terc(r):
            f = r["f_25fwd"]
            if f is None:
                return "unknown"
            return "low (stingy)" if f < t1 else ("mid" if f < t2 else "high (hittable)")
        emit("P4. Published props: bias by opposing-starter hit factor tercile (2025+fwd H/BF; 2025 TUNING-ONLY input)",
             H, bias_table(rows, terc, "our", mkey="mkt"))
    # Over/Under t-style check
    for sd in ("Over", "Under"):
        g = [r for r in rows if r["side"] == sd]
        b = C.clustered_boot(g, lambda r: r["our"] - r["y"])
        mb = C.clustered_boot(g, lambda r: r["our"] - r["mkt"])
        emit(f"P5. Published {sd}s: our bias and our-minus-market gap, clustered 95%",
             ["quantity", "n", "point pts", "low", "high"],
             [["our p minus hit", len(g), C.pts(b[0]), C.pts(b[1]), C.pts(b[2])],
              ["our p minus market p", len(g), C.pts(mb[0]), C.pts(mb[1]), C.pts(mb[2])]])
    return rows


# ---------------------------------------------------------------------------
# Part 2: the full 2026 forward candidate pool, rebuilt
# ---------------------------------------------------------------------------

def pregame_rows_by_date():
    by_date = defaultdict(list)
    n_all = n_post = n_sealed = 0
    for r in C.iter_jsonl(C.p("data", "processed", "batter_props.jsonl")):
        n_all += 1
        d = r.get("game_date")
        if C.is_sealed(d):
            n_sealed += 1
            continue
        if r.get("market") not in MARKETS:
            continue
        obs, start = C.parse_utc(r.get("observed_utc")), C.parse_utc(r.get("commence_time"))
        if obs is None or start is None or obs >= start:
            n_post += 1
            continue
        by_date[d].append(r)
    return by_date, {"rows_read": n_all, "dropped_not_strictly_pregame": n_post,
                     "sealed_rows_seen": n_sealed}


def pa_dists_from_lineups(lineup_rows, box_rows):
    """{slot: {n: share}} of actual PA for listed starters."""
    box = {(str(r["game_pk"]), int(r["player_id"])): r for r in box_rows
           if r.get("type") == "batter" and r.get("player_id") is not None}
    counts = defaultdict(lambda: defaultdict(int))
    for row in lineup_rows:
        for side in ("away", "home"):
            for i, b in enumerate(row.get(side) or [], start=1):
                if b.get("person_id") is None:
                    continue
                br = box.get((str(row["game_pk"]), int(b["person_id"])))
                if br is None:
                    continue
                try:
                    slot = int(b.get("order") or i)
                except (TypeError, ValueError):
                    continue
                counts[slot][int(br.get("pa") or 0)] += 1
    out = {}
    for slot, c in counts.items():
        tot = sum(c.values())
        out[slot] = {n: k / tot for n, k in sorted(c.items())}
    return out


def mixture_p(base_kw, dist):
    tot = 0.0
    for n, w in dist.items():
        if n <= 0:
            continue
        v = _safe_price(**dict(base_kw, expected_pa=float(n)))
        if v is None:
            return None
        tot += w * v
    return tot


def build_pool(ctx, pa_dist_24):
    by_date, qcounts = pregame_rows_by_date()
    rows = []
    census = defaultdict(int)
    for date in sorted(by_date):
        C.guard(date)
        if date > "2026-10-15":
            continue
        lg = ctx.league(date)
        if lg is None:
            census["no league history (first box date)"] += 1
            continue
        slots = dict(ctx.slots_by_date_name.get(date, {}))
        b_slot = propboard.build(by_date[date], date=date, batters_by_name=ctx.by_name,
                                 league=lg, slots_by_player=slots)
        b_avg = propboard.build(by_date[date], date=date, batters_by_name=ctx.by_name,
                                league=lg, slots_by_player={})
        for reason, k in b_slot["refused"].items():
            census["refused: " + reason[:50]] += k
        avg_p = {(c["event_id"], c["player"], c["market"], c["line"]): c["probability"]
                 for c in b_avg["contracts"] if c["side"] == "Over"}
        by_key = defaultdict(dict)
        for c in b_slot["contracts"]:
            by_key[(c["event_id"], c["player"], c["market"], c["line"])][c["side"]] = c
        for key, sides in by_key.items():
            over = sides.get("Over")
            under = sides.get("Under")
            if over is None:
                census["no Over side quoted"] += 1
                continue
            ev, player, market, line = key
            pk = gamekey.game_pk_for_event(ev, ctx.event_map)
            if pk is None:
                census["event not mapped to game_pk"] += 1
                continue
            box = ctx.box_by_game_name.get((str(pk), player))
            if box is None:
                census["no box row in that game (DNP / void)" if date not in ctx.box_dates_by_name.get(player, ())
                       else "box row on date but other game_pk"] += 1
                continue
            y = over_y(market, line, box)
            if y is None:
                census["no outcome field"] += 1
                continue
            prior = propboard._prior_lines(ctx.by_name.get(player) or [], date)
            slot = slots.get(player)
            base = dict(market=market, line=line, batter_lines=prior, league=lg)
            pr = playerprops.price_prop(**base, batting_slot=slot)
            if abs(pr["probability"] - over["probability"]) > 1e-12:
                census["MISMATCH vs propboard.build"] += 1
            side = box.get("side")
            st = starter_cols(ctx, pk, side, date, lg["hit"])
            actual_slot = ctx.slot_by_game_pid.get((str(pk), int(box["player_id"])))
            r = {
                "date": date, "game_pk": str(pk), "event_id": ev, "player": player, "h_count": int(box.get("h") or 0),
                "market": market, "line": line, "y": y, "pa": int(box.get("pa") or 0),
                "home_away": side, "game_type": ctx.game_type(pk) or "n/a",
                "slot": slot, "actual_slot": actual_slot, "src": pr["expected_pa_source"],
                "expected_pa": pr["expected_pa"], "season_games": over["season_games"],
                "pa_sample": pr["batter_pa_sample"], "hit_rate": pr["batter_hit_rate"],
                "league_hit": lg["hit"], "league_pa_per_game": None,
                "p_card": over["probability"], "p_avg": avg_p.get(key),
                "mkt": over["market_probability"], "books": over["books"],
                "price_over": over["price"], "price_under": under["price"] if under else None,
                "throws": st["starter_throws"], "f_fwd": st["f_fwd"], "f_25fwd": st["f_25fwd"],
                "bats": (ctx.hand.get(str(box.get("player_id"))) or {}).get("bats"),
            }
            # Counterfactuals (all point-in-time except where named ORACLE / RETRO)
            r["p_slot25"] = _safe_price(**base, batting_slot=slot, slot_table=SLOT25)
            r["p_rho25"] = _safe_price(**base, batting_slot=slot, rho=RHO25)
            r["p_rho0"] = _safe_price(**base, batting_slot=slot, rho=0.0)
            r["p_oracle_pa"] = (_safe_price(**base, expected_pa=float(r["pa"])) if r["pa"] > 0 else 0.0)
            if slot is not None and slot in pa_dist_24:
                r["p_mix24"] = mixture_p(dict(base, batting_slot=slot), pa_dist_24[slot])
            else:
                own = defaultdict(int)
                for g in prior:
                    own[int(g.get("pa") or 0)] += 1
                tot = sum(own.values())
                r["p_mix24"] = mixture_p(base, {n: k / tot for n, k in own.items()}) if tot else None
            for tag, stt in (("fwd", st["st_fwd"]), ("25fwd", st["st_25fwd"])):
                if stt:
                    r[f"p_st_{tag}"] = _safe_price(**base, batting_slot=slot,
                                                   pitcher_hits_allowed=stt[0], pitcher_batters_faced=stt[1])
                else:
                    r[f"p_st_{tag}"] = r["p_card"]
            with pa_regression(400):
                r["p_k400"] = _safe_price(**base, batting_slot=slot)
            with pa_regression(800):
                r["p_k800"] = _safe_price(**base, batting_slot=slot)
            with pa_regression(100):
                r["p_k100"] = _safe_price(**base, batting_slot=slot)
            p25lines = [g for g in ctx.b25_by_name.get(player, [])]
            r["p_hist25"] = _safe_price(**dict(base, batter_lines=p25lines + prior), batting_slot=slot)
            census["scored"] += 1
            rows.append(r)
    return rows, dict(census), qcounts


def run_pool(ctx, pub_rows):
    box24 = C.load_box_archive(2024)
    lu24 = [r for r in C.load_lineups() if str(r["date"])[:4] == "2024"]
    pa24 = pa_dists_from_lineups(lu24, box24)
    pa26 = pa_dists_from_lineups(ctx.lineups, ctx.batters)
    rows, census, qcounts = build_pool(ctx, pa24)
    emit("Q0. Forward pool rebuild: census", ["item", "count"],
         [[k, v] for k, v in sorted(qcounts.items())] + [[k, v] for k, v in sorted(census.items())],
         note="Pre-game quotes only (observed_utc < commence_time); hits/total bases/runs; "
              "one row per (event, player, market, line), Over probability.")
    # --- reproduction check against the published bets
    idx = {}
    for r in rows:
        idx[(r["date"], r["game_pk"], r["player"], r["market"], float(r["line"]))] = r
    matched = exact = 0
    diffs = []
    for b in pub_rows:
        r = idx.get((b["date"], b["game_pk"], b["player"], b["market"], float(b["line"])))
        if r is None:
            continue
        matched += 1
        p_over = r["p_card"] if b["src"] == "batting_slot" else r["p_avg"]
        if p_over is None:
            continue
        mine = p_over if b["side"] == "Over" else 1 - p_over
        diffs.append(abs(mine - b["our"]))
        if abs(mine - b["our"]) < 0.0006:
            exact += 1
    emit("Q0b. Instrument check: rebuilt probability vs the published our_probability",
         ["published graded props", "found in rebuilt pool", "within 0.0006 (rounding)", "median abs diff", "max abs diff"],
         [[len(pub_rows), matched, exact, C.fmt(sorted(diffs)[len(diffs) // 2] if diffs else None, 4),
           C.fmt(max(diffs) if diffs else None, 4)]],
         note="Published numbers are rounded to 4 dp. A miss means the live store differed at publish time "
              "(late box rows, lineup not yet posted) or the bet's game is not in the rebuilt pool.")

    # --- calibration on the pool, Over side, with market
    mk = [r for r in rows if r["mkt"] is not None]
    emit("Q1. Pool (all priced contracts, Over side): scores, model vs market",
         ["arm", "n", "Brier", "log loss", "mean p minus hit rate (pts)"],
         score_block(mk, [("model as card (slot if posted, else season avg)", "p_card"),
                          ("market de-vigged (last pre-game)", "mkt")]))
    d = paired(mk, "p_card", "mkt")
    db = paired(mk, "p_card", "mkt", metric="brier")
    emit("Q2. Pool: paired model minus market, date-clustered bootstrap",
         ["quantity", "point", "95% low", "95% high", "dates"],
         [["log loss (nats, + = model worse)", C.fmt(d[0], 4, True), C.fmt(d[1], 4, True), C.fmt(d[2], 4, True), len({r['date'] for r in mk})],
          ["Brier", C.fmt(db[0], 4, True), C.fmt(db[1], 4, True), C.fmt(db[2], 4, True), ""]])
    for m, line in sorted({(r["market"], float(r["line"])) for r in mk}):
        g = [r for r in mk if r["market"] == m and float(r["line"]) == line]
        if len(g) < 100:
            continue
        dd = paired(g, "p_card", "mkt")
        bb = C.clustered_boot(g, lambda r: r["p_card"] - r["y"])
        mb = C.clustered_boot(g, lambda r: r["mkt"] - r["y"])
        emit(f"Q3. Pool {m} over {line}",
             ["n", "hit rate", "model mean p", "model bias pts [95%]", "market bias pts [95%]", "LL model-market [95%]"],
             [[len(g), C.fmt(C.mean(r['y'] for r in g)), C.fmt(C.mean(r['p_card'] for r in g)),
               f"{C.pts(bb[0])} [{C.pts(bb[1])}, {C.pts(bb[2])}]",
               f"{C.pts(mb[0])} [{C.pts(mb[1])}, {C.pts(mb[2])}]",
               f"{C.fmt(dd[0], 4, True)} [{C.fmt(dd[1], 4, True)}, {C.fmt(dd[2], 4, True)}]"]])
        emit(f"Q3r. Pool {m} over {line}: reliability (model)", ["model p bin", "n", "mean p", "hit rate", "bias pts"],
             reliability(g, "p_card", edges=(0, .2, .3, .4, .5, .55, .6, .65, .7, .75, 1.0001)))
    H = ["group", "n", "mean model p", "hit rate", "model bias pts", "mean market p", "market bias pts"]
    hits05 = [r for r in mk if r["market"] == "batter_hits" and float(r["line"]) == 0.5]
    tb05 = [r for r in mk if r["market"] == "batter_total_bases" and float(r["line"]) == 0.5]
    tb15 = [r for r in mk if r["market"] == "batter_total_bases" and float(r["line"]) == 1.5]
    pool_dims = [
        ("PA source", lambda r: r["src"]),
        ("stored-lineup slot", lambda r: slot_bucket(r["slot"])),
        ("season_games bucket", lambda r: games_bucket(r["season_games"]) if r["season_games"] >= 15 else "<15"),
        ("home/away", lambda r: r["home_away"]),
        ("game type", lambda r: "R" if r["game_type"] == "R" else "post"),
        ("opposing starter throws", lambda r: r["throws"] or "unknown"),
        ("platoon (bats vs throws)", lambda r: ("same" if r["bats"] == r["throws"] else ("switch" if r["bats"] == "S" else "opposite")) if r["bats"] and r["throws"] else "unknown"),
        ("actual PA", lambda r: pa_bucket(r["pa"])),
    ]
    for label, grp in (("hits over 0.5", hits05), ("total bases over 0.5", tb05), ("total bases over 1.5", tb15)):
        for name, fn in pool_dims:
            emit(f"Q4. Pool {label}: bias by {name}", H, bias_table(grp, fn, "p_card", mkey="mkt"))

    # --- selection: bias on the side the model prefers, by model-minus-market gap
    sided = []
    for r in mk:
        for sd in ("Over", "Under"):
            pm = r["p_card"] if sd == "Over" else 1 - r["p_card"]
            mm = r["mkt"] if sd == "Over" else 1 - r["mkt"]
            price = r["price_over"] if sd == "Over" else r["price_under"]
            if price is None:
                continue
            y = r["y"] if sd == "Over" else 1 - r["y"]
            sided.append(dict(r, side=sd, ps=pm, ms=mm, ys=y, price=price,
                              be=odds_math.american_to_probability(price)))
    def gapb(s):
        g = s["ps"] - s["ms"]
        for lo, lab in ((0.10, ">+10"), (0.06, "+6..+10"), (0.03, "+3..+6"), (0.0, "0..+3"),
                        (-0.03, "-3..0"), (-0.06, "-6..-3"), (-1, "<-6")):
            if g > lo:
                return lab
        return "<-6"
    order = [">+10", "+6..+10", "+3..+6", "0..+3", "-3..0", "-6..-3", "<-6"]
    emit("Q5. Pool, both sides: hit rate by model-minus-market gap (the selection effect)",
         ["gap (pts)", "n", "mean model p", "hit rate", "model bias pts", "mean market p", "market bias pts"],
         bias_table(sided, gapb, "ps", ykey="ys", mkey="ms", order=order))
    for sd in ("Over", "Under"):
        emit(f"Q5{sd[0]}. Pool, {sd} side only: by gap",
             ["gap (pts)", "n", "mean model p", "hit rate", "model bias pts", "mean market p", "market bias pts"],
             bias_table([s for s in sided if s["side"] == sd], gapb, "ps", ykey="ys", mkey="ms", order=order))
    # card-like gate emulation on the pool (last pre-game best price; season_games >= 15)
    def card_like(s):
        price = s["price"]
        if not (-160 <= price <= -100):
            return False
        need = s["be"] + 0.010 * (odds_math.american_to_decimal(price) / odds_math.american_to_decimal(-160))
        return (s["ms"] > 0.5 and s["ps"] > 0.5 and abs(s["ps"] - s["ms"]) <= 0.10
                and s["season_games"] >= 15 and not (s["ms"] > s["be"]))
    cl = [s for s in sided if card_like(s)]
    pick_like = [s for s in cl if s["ps"] - MARKDOWN >= s["be"] + 0.010 * (odds_math.american_to_decimal(s["price"]) / odds_math.american_to_decimal(-160))]
    rows_t = []
    for label, g in (("card-eligible (G4,G5,G6,G8,G10,G13 emulated)", cl),
                     ("... and passes G7 value test (pick-like)", pick_like)):
        if not g:
            continue
        b = C.clustered_boot(g, lambda s: s["ps"] - s["ys"])
        mb = C.clustered_boot(g, lambda s: s["ms"] - s["ys"])
        roi = C.mean(s["ys"] * (odds_math.american_to_decimal(s["price"]) - 1) - (1 - s["ys"]) for s in g)
        rows_t.append([label, len(g), C.fmt(C.mean(s['ps'] for s in g)), C.fmt(C.mean(s['ys'] for s in g)),
                       f"{C.pts(b[0])} [{C.pts(b[1])}, {C.pts(b[2])}]", f"{C.pts(mb[0])} [{C.pts(mb[1])}, {C.pts(mb[2])}]",
                       C.fmt(roi, 3, True)])
    emit("Q6. Pool: card-like selection emulated at the last pre-game price",
         ["subset", "n", "mean model p", "hit rate", "model bias pts [95%]", "market bias pts [95%]", "flat-stake ROI/bet"], rows_t)

    run_decomposition(rows, pub_rows, pa24, pa26, label="2026 forward pool")
    return rows, pa24, pa26


# ---------------------------------------------------------------------------
# Part 3: decomposition
# ---------------------------------------------------------------------------

VARIANTS = [
    ("p_slot25", "slot table: 2025 frozen fit instead of V1 table (OOS, point-in-time)"),
    ("p_mix24", "PA as a distribution (2024 slot PA distribution, or own prior PA counts)"),
    ("p_oracle_pa", "ORACLE: expected PA = actual PA (diagnostic only)"),
    ("p_rho25", "rho 0.05885 (2025 frozen) instead of 0.05065"),
    ("p_rho0", "rho 0 (plain binomial)"),
    ("p_st_fwd", "opposing starter factor, forward-window H/BF"),
    ("p_st_25fwd", "opposing starter factor, 2025 + forward H/BF (2025 TUNING-ONLY input)"),
    ("p_k100", "PA_REGRESSION 100 (trust own rate more)"),
    ("p_k400", "PA_REGRESSION 400 (shrink harder)"),
    ("p_k800", "PA_REGRESSION 800"),
    ("p_hist25", "batter rate from 2025 + 2026-forward lines (2025 TUNING-ONLY input)"),
]


def run_decomposition(rows, pub_rows, pa24, pa26, label):
    # PA level: stored-lineup starters
    tab = []
    for s in range(1, 10):
        d24, d26 = pa24.get(s, {}), pa26.get(s, {})
        m24 = sum(n * w for n, w in d24.items()) if d24 else None
        m26 = sum(n * w for n, w in d26.items()) if d26 else None
        le3_26 = sum(w for n, w in d26.items() if n <= 3) if d26 else None
        le2_26 = sum(w for n, w in d26.items() if n <= 2) if d26 else None
        tab.append([s, C.fmt(playerprops.SLOT_PLATE_APPEARANCES[s]), C.fmt(SLOT25[s]), C.fmt(m24), C.fmt(m26),
                    C.fmt(le3_26), C.fmt(le2_26)])
    emit(f"D1. {label}: expected PA by slot, V1 table (used live) vs 2025 frozen vs actual",
         ["slot", "V1 table (live)", "2025 frozen", "2024 actual mean", "this sample actual mean", "this sample share <=3 PA", "this sample share <=2 PA"], tab,
         note="Actual = listed starters in `data/historical/lineups.jsonl` joined to box PA (pinch-hit removals included).")
    # PA error on pool rows
    for src in ("batting_slot", "season_average"):
        g = [r for r in rows if r["src"] == src]
        if not g:
            continue
        emit(f"D2. {label} ({src}): assumed vs actual PA",
             ["n", "mean expected PA", "mean actual PA", "error (exp-act)", "share actual < expected-1", "share actual <=2"],
             [[len(g), C.fmt(C.mean(r['expected_pa'] for r in g)), C.fmt(C.mean(r['pa'] for r in g)),
               C.fmt(C.mean(r['expected_pa'] - r['pa'] for r in g), 3, True),
               C.fmt(C.mean(1 if r['pa'] < r['expected_pa'] - 1 else 0 for r in g)),
               C.fmt(C.mean(1 if r['pa'] <= 2 else 0 for r in g))]])
    # Per-PA rate calibration (hits): weighted regression of excess hits on predicted excess
    g = [r for r in rows if r["market"] == "batter_hits" and float(r["line"]) == 0.5 and r["pa"] > 0]
    rate_tab = []
    for lo, hi, lab in ((0, 80, "40-79 PA"), (80, 120, "80-119 PA"), (120, 10**6, "120+ PA")):
        gg = [r for r in g if lo <= r["pa_sample"] < hi]
        if not gg:
            continue
        sx = sum(((r["hit_rate"] - r["league_hit"]) * r["pa"]) ** 2 for r in gg)
        sxy = sum((r["hit_rate"] - r["league_hit"]) * r["pa"] * (_hits(r) - r["league_hit"] * r["pa"]) for r in gg)
        pred = sum(r["hit_rate"] * r["pa"] for r in gg) / sum(r["pa"] for r in gg)
        act = sum(_hits(r) for r in gg) / sum(r["pa"] for r in gg)
        rate_tab.append([lab, len(gg), C.fmt(pred, 4), C.fmt(act, 4), C.pts(pred - act, 2),
                         C.fmt(sxy / sx if sx else None, 2)])
    emit(f"D3. {label}: per-PA hit rate, predicted vs actual (hits rows, PA>0)",
         ["prior PA sample", "n", "pred hit/PA", "actual hit/PA", "level error pts", "slope actual-on-pred deviation (1 = right shrinkage)"],
         rate_tab, note="Slope < 1: the batter's own deviation from league is over-trusted; > 1: over-shrunk.")
    # Variant table: mean p change vs card, bias, log loss, on pool and on published bets
    for (m, line) in (("batter_hits", 0.5), ("batter_total_bases", 0.5), ("batter_total_bases", 1.5)):
        gg = [r for r in rows if r["market"] == m and float(r["line"]) == line]
        if not gg:
            continue
        base_ll = C.mean(C.ll(r["p_card"], r["y"]) for r in gg)
        tab = [["card (as published)", len(gg), "0.0", C.pts(C.mean(r['p_card'] - r['y'] for r in gg)), C.fmt(base_ll, 4), ""]]
        for key, desc in VARIANTS:
            vv = [r for r in gg if r.get(key) is not None]
            if not vv:
                continue
            dl = C.clustered_boot(vv, lambda r: C.ll(r["p_card"], r["y"]) - C.ll(r[key], r["y"]))
            tab.append([desc, len(vv), C.pts(C.mean(r[key] - r["p_card"] for r in vv)),
                        C.pts(C.mean(r[key] - r["y"] for r in vv)), C.fmt(C.mean(C.ll(r[key], r["y"]) for r in vv), 4),
                        f"{C.fmt(dl[0], 4, True)} [{C.fmt(dl[1], 4, True)}, {C.fmt(dl[2], 4, True)}]"])
        emit(f"D4. {label}, {m} over {line}: counterfactual components (Over probability)",
             ["variant", "n", "mean shift vs card (pts)", "bias after (pts)", "log loss", "LL gain vs card [95%] (+ = better)"], tab)


def _hits(r):
    # hits rows: y is over 0.5; actual hits count is needed for the rate table
    return r.get("h_count", r["y"])


# ---------------------------------------------------------------------------
# Part 4: historical seasons (2024 out-of-sample; 2025 TUNING-ONLY)
# ---------------------------------------------------------------------------

def run_hist(season, pa24):
    if season not in (2023, 2024, 2025):
        raise ValueError(season)
    tag = "TUNING-ONLY " if season == 2025 else ""
    box = C.load_box_archive(season)
    results = {k: v for k, v in C.load_results().items() if str(v.get("date", ""))[:4] == str(season)}
    lineups = [r for r in C.load_lineups() if str(r["date"])[:4] == str(season)]
    slot_map = {}
    for row in lineups:
        for side in ("away", "home"):
            for i, b in enumerate(row.get(side) or [], start=1):
                if b.get("person_id") is not None:
                    try:
                        slot_map[(int(row["game_pk"]), int(b["person_id"]))] = int(b.get("order") or i)
                    except (TypeError, ValueError):
                        pass
    hand = C.load_handedness()
    plogs = [r for r in C.load_pitcher_logs([season]) if r.get("person_id") is not None]
    p_by = defaultdict(list)
    for r in plogs:
        if r.get("hits") is None or r.get("batters_faced") is None:
            continue
        p_by[int(r["person_id"])].append((str(r["date"])[:10], int(r["hits"]), int(r["batters_faced"])))
    batters = [r for r in box if r.get("type") == "batter"]
    by_date = defaultdict(list)
    seen = set()
    for r in batters:
        d = str(r.get("date") or "")[:10]
        if d[:4] != str(season):
            continue
        g = results.get(int(r["game_pk"])) if r.get("game_pk") is not None else None
        if g is None or g.get("game_type") != "R":
            continue
        k = (r["game_pk"], r.get("player_id"))
        if k in seen:
            continue
        seen.add(k)
        by_date[d].append(r)
    dates = sorted(by_date)
    out = {}
    # Two regimes: FULL season-to-date history; SHORT history that starts on Aug 28 (the
    # live 2026 store's shape), scored from Sep 15, with the card's 15-game gate.
    for regime in ("full", "short"):
        start_hist = f"{season}-08-28" if regime == "short" else f"{season}-01-01"
        score_from = f"{season}-09-15" if regime == "short" else f"{season}-08-15"
        hist = defaultdict(list)
        lg_sums = {"pa": 0, "h": 0, "doubles": 0, "triples": 0, "hr": 0, "r": 0, "rbi": 0}
        rows = []
        for d in dates:
            if d >= score_from and lg_sums["pa"] > 0:
                league = playerprops.league_rates([dict(lg_sums)])
                for r in by_date[d]:
                    pid = r.get("player_id")
                    prior = hist.get(pid, [])
                    slot = slot_map.get((int(r["game_pk"]), int(pid))) if pid is not None else None
                    if slot is None:
                        continue   # starters only: the priced pool is mostly listed starters
                    if regime == "short" and len(prior) < 15:
                        continue
                    if season == 2025:
                        slot_used = None
                    else:
                        slot_used = slot
                    g = results[int(r["game_pk"])]
                    side = r.get("side")
                    raw = g.get("home_probable_id" if side == "away" else "away_probable_id")
                    try:
                        spid = int(float(raw))
                    except (TypeError, ValueError):
                        spid = None
                    st = None
                    if spid is not None and spid in p_by:
                        hh = sum(x[1] for x in p_by[spid] if x[0] < d)
                        bf = sum(x[2] for x in p_by[spid] if x[0] < d)
                        st = (hh, bf) if bf > 0 else None
                    pa = int(r.get("pa") or 0)
                    for m, line in (("batter_hits", 0.5), ("batter_total_bases", 0.5), ("batter_total_bases", 1.5)):
                        base = dict(market=m, line=line, batter_lines=prior, league=league)
                        try:
                            pr = playerprops.price_prop(**base, batting_slot=slot_used)
                        except playerprops.PropError:
                            continue
                        y = over_y(m, line, r)
                        if y is None:
                            continue
                        row = {"date": d, "market": m, "line": line, "y": y, "pa": pa, "slot": slot,
                               "src": pr["expected_pa_source"], "expected_pa": pr["expected_pa"],
                               "season_games": len(prior), "pa_sample": pr["batter_pa_sample"],
                               "hit_rate": pr["batter_hit_rate"], "league_hit": league["hit"],
                               "h_count": int(r.get("h") or 0), "home_away": side,
                               "throws": (hand.get(str(spid)) or {}).get("throws") if spid else None,
                               "p_card": pr["probability"]}
                        row["p_slot25"] = _safe_price(**base, batting_slot=slot_used, slot_table=SLOT25)
                        row["p_rho25"] = _safe_price(**base, batting_slot=slot_used, rho=RHO25)
                        row["p_rho0"] = _safe_price(**base, batting_slot=slot_used, rho=0.0)
                        row["p_oracle_pa"] = _safe_price(**base, expected_pa=float(pa)) if pa > 0 else 0.0
                        if slot_used is not None and slot_used in pa24 and season != 2024:
                            row["p_mix24"] = mixture_p(dict(base, batting_slot=slot_used), pa24[slot_used])
                        else:
                            own = defaultdict(int)
                            for gg in prior:
                                own[int(gg.get("pa") or 0)] += 1
                            tot = sum(own.values())
                            row["p_mix24"] = mixture_p(base, {n: k / tot for n, k in own.items()}) if tot else None
                        row["p_st_fwd"] = (_safe_price(**base, batting_slot=slot_used, pitcher_hits_allowed=st[0],
                                                       pitcher_batters_faced=st[1]) if st else pr["probability"])
                        with pa_regression(100):
                            row["p_k100"] = _safe_price(**base, batting_slot=slot_used)
                        with pa_regression(400):
                            row["p_k400"] = _safe_price(**base, batting_slot=slot_used)
                        with pa_regression(800):
                            row["p_k800"] = _safe_price(**base, batting_slot=slot_used)
                        rows.append(row)
            for r in by_date[d]:
                if d >= start_hist:
                    hist[r.get("player_id")].append(r)
                    for f in lg_sums:
                        lg_sums[f] += int(r.get(f) or 0)
        out[regime] = rows
        lab = f"{tag}{season} {regime}-history regime (listed starters, regular season, scored from {score_from})"
        tab = []
        for (m, line) in (("batter_hits", 0.5), ("batter_total_bases", 0.5), ("batter_total_bases", 1.5)):
            gg = [r for r in rows if r["market"] == m and r["line"] == line]
            if not gg:
                continue
            b = C.clustered_boot(gg, lambda r: r["p_card"] - r["y"])
            tab.append([f"{m} over {line}", len(gg), C.fmt(C.mean(r['p_card'] for r in gg)),
                        C.fmt(C.mean(r['y'] for r in gg)), f"{C.pts(b[0])} [{C.pts(b[1])}, {C.pts(b[2])}]",
                        C.fmt(C.mean(C.ll(r['p_card'], r['y']) for r in gg), 4)])
        emit(f"H1. {lab}: calibration of the card's model", ["market", "n", "mean p", "hit rate", "bias pts [95%]", "log loss"], tab)
        for (m, line) in (("batter_hits", 0.5), ("batter_total_bases", 0.5), ("batter_total_bases", 1.5)):
            gg = [r for r in rows if r["market"] == m and r["line"] == line]
            emit(f"H2. {lab}, {m} over {line}: reliability", ["p bin", "n", "mean p", "hit rate", "bias pts"],
                 reliability(gg, "p_card", edges=(0, .2, .3, .4, .5, .55, .6, .65, .7, .75, 1.0001)))
        hh = [r for r in rows if r["market"] == "batter_hits"]
        emit(f"H3. {lab}, hits over 0.5: bias by slot", ["slot", "n", "mean p", "hit rate", "bias pts"],
             bias_table(hh, lambda r: slot_bucket(r["slot"]), "p_card"))
        emit(f"H3b. {lab}, hits over 0.5: bias by opposing starter throws", ["throws", "n", "mean p", "hit rate", "bias pts"],
             bias_table(hh, lambda r: r["throws"] or "unknown", "p_card"))
        pa_tab = {}
        for r in hh:
            pa_tab.setdefault(r["slot"], []).append(r["pa"])
        run_decomposition(rows, [], pa24, {s: _dist(v) for s, v in pa_tab.items()}, label=lab)
    return out


def _dist(values):
    c = defaultdict(int)
    for v in values:
        c[v] += 1
    tot = sum(c.values())
    return {n: k / tot for n, k in c.items()}


# ---------------------------------------------------------------------------
# Part 5: shrink toward market (retrospective)
# ---------------------------------------------------------------------------

def fit_lambda(rows, pkey, mkey, ykey):
    best = None
    for i in range(0, 101):
        lam = i / 100
        l = C.mean(C.ll(r[mkey] + lam * (r[pkey] - r[mkey]), r[ykey]) for r in rows)
        if best is None or l < best[1]:
            best = (lam, l)
    return best


def run_shrink(pool_rows, pub_rows):
    mk = [r for r in pool_rows if r["mkt"] is not None]
    lam_pool, _ = fit_lambda(mk, "p_card", "mkt", "y")
    lam_pub, _ = fit_lambda(pub_rows, "our", "mkt", "y")
    tab = []
    for name, lam in (("as published (lambda 1, raw our_probability)", 1.0),
                      ("our_probability_used (raw minus 0.038)", None),
                      (f"lambda fitted on forward pool = {lam_pool:.2f} (RETROSPECTIVE)", lam_pool),
                      (f"lambda fitted on published bets = {lam_pub:.2f} (RETROSPECTIVE, in-sample)", lam_pub),
                      ("market only (lambda 0)", 0.0)):
        ev = []
        pp = []
        for r in pub_rows:
            q = r["used"] if lam is None else r["mkt"] + lam * (r["our"] - r["mkt"])
            dec = odds_math.american_to_decimal(r["price"])
            ev.append(q * dec - 1)
            pp.append(q)
        tab.append([name, len(pub_rows), C.fmt(C.mean(pp)), C.fmt(sum(ev), 2, True), C.fmt(C.mean(ev), 4, True),
                    sum(1 for e in ev if e > 0)])
    realized = sum(r["profit"] for r in pub_rows)
    emit("S1. Published props: expected units under each estimate (RETROSPECTIVE, not a promise)",
         ["estimate", "bets", "mean p", "expected units", "EV per bet", "bets with EV > 0"], tab,
         note=f"Realized: {realized:+.2f} units on the same {len(pub_rows)} bets; hit rate "
              f"{C.mean(r['y'] for r in pub_rows):.3f}; mean breakeven {C.mean(r['be'] for r in pub_rows):.3f}.")
    return lam_pool, lam_pub


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="all", choices=("all", "published", "pool", "hist"))
    ap.add_argument("--season", type=int, default=None)
    args = ap.parse_args(argv)
    os.makedirs(OUT_DIR, exist_ok=True)
    pa24 = None
    if args.part in ("all", "published", "pool"):
        ctx = Ctx2026()
        pub = run_published(ctx)
        if args.part in ("all", "pool"):
            pool, pa24, _ = run_pool(ctx, pub)
            # decomposition on the published bets themselves
            idx = {(r["date"], r["game_pk"], r["player"], r["market"], float(r["line"])): r for r in pool}
            joined = []
            for b in pub:
                r = idx.get((b["date"], b["game_pk"], b["player"], b["market"], float(b["line"])))
                if r is None:
                    continue
                sgn = 1 if b["side"] == "Over" else -1
                j = dict(b)
                base = r["p_card"] if b["src"] == "batting_slot" else r["p_avg"]
                if base is None:
                    continue
                for key, _desc in VARIANTS:
                    if r.get(key) is not None:
                        j["d_" + key] = sgn * (r[key] - r["p_card"])
                j["mkt_close"] = r["mkt"] if b["side"] == "Over" else (1 - r["mkt"] if r["mkt"] is not None else None)
                joined.append(j)
            tab = []
            for key, desc in VARIANTS:
                vals = [j["d_" + key] for j in joined if ("d_" + key) in j]
                if vals:
                    tab.append([desc, len(vals), C.pts(C.mean(vals), 2)])
            cl = [j for j in joined if j.get("mkt_close") is not None]
            tab.append(["market at publish -> market at last pre-game quote (side)", len(cl),
                        C.pts(C.mean(j["mkt_close"] - j["mkt"] for j in cl), 2)])
            emit("D5. Published bets: how each component would have moved OUR side probability",
                 ["component", "bets matched", "mean shift (pts, side probability)"], tab,
                 note="Negative = the correction lowers our number on the side we bet. "
                      "Last row: closing-line movement on the bets (negative = market moved against us).")
            run_shrink(pool, pub)
    if args.part in ("all", "hist"):
        if pa24 is None:
            box24 = C.load_box_archive(2024)
            lu24 = [r for r in C.load_lineups() if str(r["date"])[:4] == "2024"]
            pa24 = pa_dists_from_lineups(lu24, box24)
        seasons = [args.season] if args.season else [2024, 2025]
        for s in seasons:
            run_hist(s, pa24)
    suffix = args.part if args.part != "hist" or not args.season else f"hist_{args.season}"
    with open(os.path.join(OUT_DIR, f"estimate_error_tables_{suffix}.md"), "w", encoding="utf-8") as fh:
        fh.write("# Generated by scripts/diagnosis/estimate_error.py --part " + args.part +
                 (f" --season {args.season}" if args.season else "") + "\n\n")
        fh.write("\n".join(TABLES))


if __name__ == "__main__":
    main()
