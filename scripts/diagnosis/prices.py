"""Loss diagnosis 03 -- what the prices say about the public MLB card (V2).

Reads only local stores; no network, no clock (the "now" of every number is
the stores' own content). Writes small JSON outputs under
data/research/loss_diagnosis/ and prints the markdown tables that
docs/research/loss_diagnosis/03_prices.md quotes.

    python3 scripts/diagnosis/prices.py            # every section
    python3 scripts/diagnosis/prices.py --section clv

SEALED WINDOW: 2026-01-01..2026-08-27 is never read for outcomes. Every
outcome reader below drops a row whose date falls in that window BEFORE any
other field of the row is touched (`_sealed`). Odds rows are filtered the
same way. 2025 is not used at all. 2024 (open) and 2026-08-28 onward are the
only outcome windows.

Population: the graded V2 card -- the newest `card_settled` row per date in
evidence/cards_v2.jsonl, entries with result WIN or LOSS (178 on
2026-10-16: 97-81, -1.416 units). Picks and fills are both counted on the
public record, so both are measured here, and split.

Price vocabulary (never "edge"):
  be_lock   breakeven of the graded price (vig included).
  p_lock    the entry's own frozen `market_probability`: de-vigged consensus
            at the quote instant.
  p_close   de-vigged consensus at the last capture before first pitch on the
            exact selection (same line), strictly after the quote instant.
  CLV (pts) = 100 * (p_close - be_lock). Positive = the closing market rates
            our side more likely than the price we were graded at needs.
  move (pts) = 100 * (p_close - p_lock): consensus drift toward our side.
  premium (pts) = 100 * (be_lock - p_lock): what the graded price charged
            over the lock consensus. G13 forces this >= 0 on every entry.
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.core import odds as om  # noqa: E402
from src.data.labels import TEAM_NAMES  # noqa: E402
from src.model.discovery import clustered_bootstrap  # noqa: E402

OUT_DIR = os.path.join(ROOT, "data", "research", "loss_diagnosis")
CARDS = os.path.join(ROOT, "evidence", "cards_v2.jsonl")
DECISIONS = os.path.join(ROOT, "evidence", "decisions_v2.jsonl")
PROPS = os.path.join(ROOT, "data", "processed", "batter_props.jsonl")
MULTIBOOK = os.path.join(ROOT, "data", "processed", "odds_multibook.jsonl")
MULTIBOOK_ARCHIVE = os.path.join(ROOT, "data", "processed", "archive", "odds_multibook")
EVENT_MAP = os.path.join(ROOT, "data", "processed", "event_game_map.jsonl")
BOX_2026 = os.path.join(ROOT, "data", "processed", "boxscores_2026.jsonl")
RESULTS = os.path.join(ROOT, "data", "historical", "mlb_results.csv")
ODDS_2024 = os.path.join(ROOT, "data", "archive", "historical", "odds_history", "mlb_2024.jsonl.gz")

SEAL_FIRST, SEAL_LAST = "2026-01-01", "2026-08-27"
OPEN_2026 = "2026-08-28"
PROP_MARKETS = ("batter_hits", "batter_total_bases", "batter_runs_scored")
PROP_MIN_TWO_SIDED = 2          # propboard.MIN_BOOKS
PROP_MIN_BOOKSUM = 0.98         # propboard.MIN_TWO_WAY_BOOKSUM
GAME_MIN_BOOKS = 6              # prices.MIN_BOOKS / V2 game_min_books
MATCH_TOLERANCE_S = 180         # quote instant vs store instant
FLAT_PTS = 0.5                  # |move| below this is "flat"


def _sealed(day) -> bool:
    d = str(day or "")[:10]
    return SEAL_FIRST <= d <= SEAL_LAST


def _t(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def be(price):
    try:
        return om.american_to_probability(price)
    except (om.OddsError, TypeError, ValueError):
        return None


def dec(price):
    try:
        return om.american_to_decimal(price)
    except (om.OddsError, TypeError, ValueError):
        return None


def cents(price):
    """American odds on a continuous line: -105 -> -5, +105 -> +5."""
    if price is None:
        return None
    return price + 100.0 if price < 0 else price - 100.0


def prob_to_american(p):
    try:
        return om.probability_to_american(p)
    except Exception:
        return None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def fmt(x, nd=2, signed=True):
    if x is None:
        return "n/a"
    return (f"{x:+.{nd}f}" if signed else f"{x:.{nd}f}")


def boot(rows, key, resamples=2000):
    """Date-clustered 95% interval on the mean of `key` (discovery.py)."""
    use = [r for r in rows if r.get(key) is not None]
    if not use:
        return None, None, None
    m = mean([r[key] for r in use])
    ci = clustered_bootstrap(use, lambda s: mean([r[key] for r in s]), resamples=resamples)
    return m, ci.get("low"), ci.get("high")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_cards():
    return [json.loads(line) for line in open(CARDS, encoding="utf-8")]


def graded_entries(rows=None):
    rows = rows if rows is not None else load_cards()
    latest = {}
    for r in rows:
        if r.get("kind") == "card_settled":
            latest[r["date"]] = r          # file order == chain order
    out = []
    for date, r in sorted(latest.items()):
        for g in r.get("graded") or ():
            if g.get("result") not in ("WIN", "LOSS"):
                continue
            e = dict(g)
            e["date"] = date
            out.append(e)
    return out


def refused_candidates(rows=None, taken_keys=frozenset()):
    """Every close call the card showed nobody (`close_calls_not_shown`) on
    any publish of a date, one per selection (the newest observation that is
    still before first pitch), excluding anything that was graded."""
    rows = rows if rows is not None else load_cards()
    best = {}
    for r in rows:
        if r.get("kind") != "card_published":
            continue
        for c in r.get("close_calls_not_shown") or ():
            k = (r["date"],) + sel_key(c)
            if k[1:] in taken_keys:
                continue
            obs, fp = _t(c.get("observed_utc")), _t(c.get("first_pitch_utc"))
            if obs is None or fp is None or obs >= fp:
                continue
            held = best.get(k)
            if held is None or obs > _t(held["observed_utc"]):
                e = dict(c)
                e["date"] = r["date"]
                best[k] = e
    return list(best.values())


def first_published(rows=None):
    """{(date,)+sel_key: earliest published_utc of a card row showing it
    (pick or fill in all_bets, or a close call)}."""
    rows = rows if rows is not None else load_cards()
    out = {}
    for r in rows:
        if r.get("kind") != "card_published":
            continue
        pub = r.get("published_utc")
        for e in list(r.get("all_bets") or ()) + list(r.get("close_calls_not_shown") or ()):
            k = (r["date"],) + sel_key(e)
            if k not in out or pub < out[k]:
                out[k] = pub
    return out


def sel_key(e):
    return (str(e.get("game_pk")), e.get("market"), e.get("player"),
            None if e.get("line") is None else float(e.get("line")),
            e.get("side"))


def event_map():
    by_pk = defaultdict(list)
    by_event = {}
    for line in open(EVENT_MAP, encoding="utf-8"):
        d = json.loads(line)
        if not d.get("resolved") or d.get("game_pk") is None:
            continue
        by_pk[str(d["game_pk"])].append(d)
        by_event[d["event_id"]] = str(d["game_pk"])
    return by_pk, by_event


def event_for(entry, by_pk):
    cands = by_pk.get(str(entry.get("game_pk"))) or []
    if not cands:
        return None
    fp = _t(entry.get("first_pitch_utc"))
    if fp is None or len(cands) == 1:
        return cands[0]["event_id"]
    return min(cands, key=lambda d: abs((_t(d["commence_time"]) - fp).total_seconds()))["event_id"]


class PropIndex:
    """{(event_id, player, market, line): {instant: {book: {side: price}}}}"""

    def __init__(self, markets=PROP_MARKETS, first_day="2026-09-15", last_day="2026-12-31"):
        self.q = defaultdict(lambda: defaultdict(dict))
        self.lu = {}
        self.commence = {}
        for line in open(PROPS, encoding="utf-8"):
            d = json.loads(line)
            gd = d.get("game_date") or ""
            if _sealed(gd) or gd < first_day or gd > last_day:
                continue
            if d.get("market") not in markets:
                continue
            try:
                ln = float(d.get("line"))
            except (TypeError, ValueError):
                continue
            k = (d["event_id"], d["player"], d["market"], ln)
            inst = d["observed_utc"]
            self.q[k][inst].setdefault(d["book"], {})[d["side"]] = d["price"]
            self.lu[(k, inst, d["book"])] = d.get("book_last_update")
            self.commence[d["event_id"]] = d.get("commence_time")

    def series(self, key):
        """[(datetime, instant_str, {book: {side: price}})] sorted."""
        s = self.q.get(key) or {}
        return sorted(((_t(i), i, b) for i, b in s.items()), key=lambda x: x[0])


class GameIndex:
    """h2h only: {event_id: {instant: {book: {"home": p, "away": p}}}}"""

    def __init__(self, first_day="2026-08-28"):
        self.q = defaultdict(lambda: defaultdict(dict))
        self.lu = {}
        self.commence = {}
        self.teams = {}
        paths = sorted(glob.glob(os.path.join(MULTIBOOK_ARCHIVE, "*.jsonl.gz"))) + [MULTIBOOK]
        for path in paths:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    d = json.loads(line)
                    if d.get("market") not in (None, "h2h"):
                        continue
                    obs = d.get("observed_utc") or ""
                    if _sealed(obs) or obs[:10] < first_day:
                        continue
                    if d.get("home_price") is None or d.get("away_price") is None:
                        continue
                    ev = d["event_id"]
                    self.q[ev][obs][d["book"]] = {"home": d["home_price"], "away": d["away_price"]}
                    self.lu[(ev, obs, d["book"])] = d.get("book_last_update")
                    self.commence[ev] = d.get("commence_time")
                    self.teams[ev] = (d.get("away_team"), d.get("home_team"))

    def series(self, ev):
        s = self.q.get(ev) or {}
        return sorted(((_t(i), i, b) for i, b in s.items()), key=lambda x: x[0])


# ---------------------------------------------------------------------------
# One board, one side
# ---------------------------------------------------------------------------

OTHER = {"Over": "Under", "Under": "Over", "home": "away", "away": "home"}


def board(books, side, *, prop):
    """Consensus, best, average and vig for `side` on one instant's books.
    Prop boards follow propboard.fair_and_best (two-sided, booksum >= 0.98);
    game boards follow prices.snapshot (any valid two-sided quote)."""
    other = OTHER[side]
    fairs, raws, rows = [], [], []
    any_side = 0
    for book, sides in (books or {}).items():
        mine, theirs = sides.get(side), sides.get(other)
        if mine is not None:
            any_side += 1
        if mine is None or theirs is None:
            continue
        a, b = be(mine), be(theirs)
        if a is None or b is None:
            continue
        if prop and a + b < PROP_MIN_BOOKSUM:
            continue
        try:
            fair_mine, _ = om.devig_two_way(mine, theirs)
        except (om.OddsError, ZeroDivisionError):
            continue
        fairs.append(fair_mine)
        raws.append(a)
        rows.append((book, mine, theirs, a + b - 1.0))
    if not rows:
        return {"two_sided": 0, "books_any": len(books or {}), "side_quoted": any_side}
    best_row = max(rows, key=lambda r: (dec(r[1]), r[0]))
    best_books = sorted(r[0] for r in rows if r[1] == best_row[1])
    return {
        "two_sided": len(rows),
        "books_any": len(books or {}),
        "side_quoted": any_side,
        "fair": sum(fairs) / len(fairs),
        "best_price": best_row[1],
        "best_books": best_books,
        "best_overround": best_row[3],
        "avg_raw": sum(raws) / len(raws),
        "avg_price": prob_to_american(sum(raws) / len(raws)),
        "mean_overround": sum(r[3] for r in rows) / len(rows),
        "prices": {r[0]: r[1] for r in rows},
        "other_prices": {r[0]: r[2] for r in rows},
    }


def _nearest(series, when, tol=MATCH_TOLERANCE_S):
    best = None
    for t, inst, books in series:
        dt = abs((t - when).total_seconds())
        if dt <= tol and (best is None or dt < best[0]):
            best = (dt, t, inst, books)
    return best


# ---------------------------------------------------------------------------
# Measurement of one entry
# ---------------------------------------------------------------------------

def measure(entry, pidx, gidx, by_pk):
    kind = entry.get("kind")
    prop = kind == "prop"
    side = entry.get("side")
    price = entry.get("price")
    out = {
        "date": entry["date"], "kind": kind, "market": entry.get("market"),
        "side": side, "price": price, "price_class": entry.get("price_class"),
        "entry_class": entry.get("entry_class"), "books": entry.get("books"),
        "result": entry.get("result"), "profit": entry.get("profit_units"),
        "withdrawn": bool(entry.get("withdrawn")),
        "player": entry.get("player"), "team_name": entry.get("team_name"),
        "line": entry.get("line"), "game_pk": entry.get("game_pk"),
        "failed_gates": entry.get("failed_gates") or [],
        "p_lock": entry.get("market_probability"),
        "our_p": entry.get("our_probability"),
        "our_p_used": entry.get("our_probability_used"),
        "be_lock": be(price),
        "quote_utc": entry.get("observed_utc"),
        "expected_pa_source": entry.get("expected_pa_source"),
        "locked_at": entry.get("locked_at"),
        "first_pitch_utc": entry.get("first_pitch_utc"),
        "absence": None,
    }
    if side not in OTHER or price is None or out["be_lock"] is None:
        out["absence"] = "NO_SIDE_OR_PRICE"
        return out
    out["premium_pts"] = 100 * (out["be_lock"] - out["p_lock"]) if out["p_lock"] is not None else None
    obs = _t(entry.get("observed_utc"))
    locked = _t(entry.get("locked_at"))
    fp = _t(entry.get("first_pitch_utc"))
    out["quote_age_at_lock_min"] = ((locked - obs).total_seconds() / 60.0) if (locked and obs) else None
    ref = locked or obs
    out["hours_before_fp"] = ((fp - ref).total_seconds() / 3600.0) if (fp and ref) else None
    out["quote_hours_before_fp"] = ((fp - obs).total_seconds() / 3600.0) if (fp and obs) else None

    ev = event_for(entry, by_pk)
    out["event_id"] = ev
    if ev is None:
        out["absence"] = "NO_EVENT"
        return out
    if prop:
        series = pidx.series((ev, entry.get("player"), entry.get("market"), float(entry.get("line"))))
        commence = _t(pidx.commence.get(ev))
    else:
        series = [(t, i, b) for t, i, b in gidx.series(ev)]
        commence = _t(gidx.commence.get(ev))
    if not series:
        out["absence"] = "SELECTION_NOT_IN_STORE"
        return out
    cutoff = min(x for x in (fp, commence) if x is not None)
    out["captures_total"] = len(series)
    # lock board -- the quote instant, reconstructed
    hit = _nearest(series, obs) if obs else None
    if hit is None:
        out["absence"] = "QUOTE_INSTANT_NOT_IN_STORE"
        return out
    _dt, t_lock, inst_lock, books_lock = hit
    bl = board(books_lock, side, prop=prop)
    out["lock_two_sided"] = bl.get("two_sided")
    out["lock_books_any"] = bl.get("books_any")
    if bl.get("two_sided"):
        out["lock_fair_rebuilt"] = bl["fair"]
        out["lock_best_rebuilt"] = bl["best_price"]
        out["lock_best_books"] = bl["best_books"]
        out["lock_avg_price"] = bl["avg_price"]
        out["lock_avg_raw"] = bl["avg_raw"]
        out["lock_best_overround"] = bl["best_overround"]
        out["lock_mean_overround"] = bl["mean_overround"]
        out["price_matches_best"] = (bl["best_price"] == price)
        out["fair_matches"] = (out["p_lock"] is not None and abs(bl["fair"] - out["p_lock"]) < 0.0011)
        # price at our book on the other side -> that book's own two-way hold
        lu = (pidx.lu if prop else gidx.lu)
        key0 = ((ev, entry.get("player"), entry.get("market"), float(entry.get("line"))) if prop else ev)
        ages = []
        for b in bl["best_books"]:
            upd = _t(lu.get((key0, inst_lock, b)))
            if upd is not None:
                ages.append((t_lock - upd).total_seconds() / 60.0)
        out["best_book_update_age_min"] = min(ages) if ages else None
    # open = first capture of the selection
    t_open, _i, books_open = series[0]
    bo = board(books_open, side, prop=prop)
    out["p_open"] = bo.get("fair")
    out["open_hours_before_lock"] = (t_lock - t_open).total_seconds() / 3600.0
    # Was the graded price still on the board when a reader could first see
    # the entry (its first publish) and when it was frozen (locked_at)? The
    # newest capture at or before each moment; if no capture is newer than
    # the quote itself, the store knows nothing newer and says so.
    first_pub = _t(entry.get("_first_published_utc"))
    out["first_published_utc"] = entry.get("_first_published_utc")
    for tag, moment in (("pub", first_pub), ("lock", locked)):
        if moment is None:
            continue
        prior = [x for x in series if x[0] <= moment]
        if not prior or prior[-1][0] <= t_lock:
            out[f"newer_capture_before_{tag}"] = False
            continue
        bp = board(prior[-1][2], side, prop=prop)
        out[f"newer_capture_before_{tag}"] = True
        if bp.get("two_sided"):
            out[f"p_at_{tag}"] = bp["fair"]
            out[f"best_at_{tag}"] = bp["best_price"]
            out[f"avail_cents_at_{tag}"] = cents(bp["best_price"]) - cents(price)
            out[f"drift_pts_at_{tag}"] = 100 * (bp["fair"] - out["p_lock"]) if out["p_lock"] is not None else None
        else:
            out[f"side_gone_at_{tag}"] = True
    # hindsight: best price at any book on any capture from the quote to first pitch
    best_any = price
    for t, inst, books in [x for x in series if x[0] >= t_lock and x[0] < cutoff]:
        b = board(books, side, prop=prop)
        if b.get("two_sided") and dec(b["best_price"]) > dec(best_any):
            best_any = b["best_price"]
    out["hindsight_best_price"] = best_any
    later = [x for x in series if x[0] > t_lock and x[0] < cutoff]
    min_books = PROP_MIN_TWO_SIDED if prop else GAME_MIN_BOOKS
    traj = []
    for t, inst, books in later:
        b = board(books, side, prop=prop)
        if b.get("two_sided", 0) >= min_books:
            traj.append((t, b))
    out["later_captures"] = len(later)
    out["later_usable"] = len(traj)
    if not traj:
        out["absence"] = "NO_LATER_QUOTE" if not later else "LATER_BOARD_THIN"
        return out
    t_close, bc = traj[-1]
    out["close_lead_min"] = (cutoff - t_close).total_seconds() / 60.0
    out["close_after_quote_h"] = (t_close - t_lock).total_seconds() / 3600.0
    out["p_close"] = bc["fair"]
    out["close_two_sided"] = bc["two_sided"]
    out["close_best_price"] = bc["best_price"]
    out["close_avg_price"] = bc["avg_price"]
    out["clv_pts"] = 100 * (bc["fair"] - out["be_lock"])
    out["move_pts"] = 100 * (bc["fair"] - out["p_lock"]) if out["p_lock"] is not None else None
    out["clv_best_close_pts"] = 100 * (be(bc["best_price"]) - out["be_lock"])
    fair_close_price = prob_to_american(bc["fair"])
    out["cents_vs_close_fair"] = cents(price) - cents(fair_close_price) if fair_close_price else None
    # first later usable capture
    out["p_next"] = traj[0][1]["fair"]
    out["next_after_quote_h"] = (traj[0][0] - t_lock).total_seconds() / 3600.0
    favs = [100 * (b["fair"] - out["p_lock"]) for _, b in traj] if out["p_lock"] is not None else []
    out["max_fav_pts"] = max(favs) if favs else None
    out["max_adv_pts"] = min(favs) if favs else None
    # same book: the book(s) holding the best price at the quote
    sb = []
    for b in (out.get("lock_best_books") or []):
        last = None
        for t, inst, books in later:
            p = (books.get(b) or {}).get(side)
            if p is not None:
                last = p
        if last is not None:
            sb.append(last)
    if sb:
        p_same = max(sb, key=dec)
        out["same_book_close_price"] = p_same
        out["clv_same_book_pts"] = 100 * (be(p_same) - out["be_lock"])
        out["cents_same_book"] = cents(price) - cents(p_same)
    else:
        out["same_book_close_price"] = None
    return out


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def units_at(rows, price_key=None, prob_key=None):
    """Realised units if each row had been graded at a different price
    (price_key) or at a fair price 1/p (prob_key)."""
    tot, n = 0.0, 0
    for r in rows:
        if price_key:
            d = dec(r.get(price_key))
        else:
            p = r.get(prob_key)
            d = (1.0 / p) if p else None
        if d is None:
            continue
        n += 1
        tot += (d - 1.0) if r["result"] == "WIN" else -1.0
    return tot, n


def record(rows):
    w = sum(r["result"] == "WIN" for r in rows)
    l = sum(r["result"] == "LOSS" for r in rows)
    u = sum(r["profit"] or 0 for r in rows)
    return w, l, u


def seg_table(rows, segfun, title, metric="clv_pts", extra_metric="move_pts"):
    groups = defaultdict(list)
    for r in rows:
        groups[segfun(r)].append(r)
    lines = [f"**{title}**", "",
             "| segment | n graded | W-L | units | n CLV | mean CLV pts [95% CI] | mean move pts [95% CI] | beat close % |",
             "|---|---|---|---|---|---|---|---|"]
    for k in sorted(groups, key=lambda x: str(x)):
        g = groups[k]
        w, l, u = record(g)
        m = [r for r in g if r.get(metric) is not None]
        c, lo, hi = boot(m, metric)
        mv, mlo, mhi = boot(m, extra_metric)
        beat = (100 * sum(r[metric] > 0 for r in m) / len(m)) if m else None
        lines.append(f"| {k} | {len(g)} | {w}-{l} | {u:+.2f} | {len(m)} | {fmt(c)} [{fmt(lo)}, {fmt(hi)}] | "
                     f"{fmt(mv)} [{fmt(mlo)}, {fmt(mhi)}] | {fmt(beat, 0, False)} |")
    return "\n".join(lines)


def hours_bin(r):
    h = r.get("hours_before_fp")
    if h is None:
        return "unknown"
    return "a <2h" if h < 2 else "b 2-4h" if h < 4 else "c 4-12h" if h < 12 else "d >=12h"


def books_bin(r):
    b = r.get("books")
    if b is None:
        return "unknown"
    return f"{b:02d}" if b <= 4 else "05-06" if b <= 6 else "07+"


def age_bin(r):
    a = r.get("quote_age_at_lock_min")
    if a is None:
        return "no lock stamp"
    return "a <=5m" if a <= 5 else "b 5-60m" if a <= 60 else "c 1-6h" if a <= 360 else "d >6h"


def market_label(r):
    return r["market"]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def section_clv(meas, out):
    n = len(meas)
    measurable = [r for r in meas if r.get("clv_pts") is not None]
    ab = Counter(r["absence"] for r in meas if r.get("clv_pts") is None)
    print("## 1. Closing-line value\n")
    print(f"Graded entries: {n}. Measurable against a later quote: {len(measurable)} "
          f"({100*len(measurable)/n:.1f}%). Absences: {dict(ab)}\n")
    # instrument check
    rebuilt = [r for r in meas if r.get("lock_best_rebuilt") is not None]
    pm = sum(bool(r.get("price_matches_best")) for r in rebuilt)
    fm = sum(bool(r.get("fair_matches")) for r in rebuilt)
    print(f"Instrument check: quote instant rebuilt for {len(rebuilt)}/{n}; graded price == best "
          f"two-sided price at that instant on {pm}/{len(rebuilt)}; frozen market_probability "
          f"== rebuilt consensus (+-0.0011) on {fm}/{len(rebuilt)}.\n")
    by_kind = defaultdict(list)
    for r in meas:
        by_kind[r["kind"]].append(r)
    print("| kind | graded | measurable | % |\n|---|---|---|---|")
    for k, g in sorted(by_kind.items()):
        m = sum(r.get("clv_pts") is not None for r in g)
        print(f"| {k} | {len(g)} | {m} | {100*m/len(g):.1f} |")
    print()
    c, lo, hi = boot(measurable, "clv_pts")
    mv, mlo, mhi = boot(measurable, "move_pts")
    pr, plo, phi = boot(measurable, "premium_pts")
    print(f"**Headline (all measurable, n={len(measurable)}):** CLV {fmt(c)} pts [{fmt(lo)}, {fmt(hi)}]; "
          f"consensus move {fmt(mv)} pts [{fmt(mlo)}, {fmt(mhi)}]; premium paid at lock {fmt(pr)} pts "
          f"[{fmt(plo)}, {fmt(phi)}].\n")
    for key, label in (("clv_same_book_pts", "same-book CLV (book that held the best price at the quote, its last later quote)"),
                       ("cents_same_book", "same-book cents (our price minus that book's last later price; + = we beat it)"),
                       ("cents_vs_close_fair", "cents vs the closing de-vigged fair price"),
                       ("clv_best_close_pts", "vs best price on the closing board (pts)")):
        m, l2, h2 = boot(measurable, key)
        nn = sum(r.get(key) is not None for r in measurable)
        print(f"- {label}: {fmt(m)} [{fmt(l2)}, {fmt(h2)}] (n={nn})")
    print()
    for kind in ("prop", "game"):
        leads = sorted(r["close_lead_min"] for r in measurable if r["kind"] == kind)
        if leads:
            print(f"- closing capture lead before first pitch, {kind}: median {statistics.median(leads):.0f} min "
                  f"(range {leads[0]:.0f}-{leads[-1]:.0f}); within 90 min on {sum(x <= 90 for x in leads)}/{len(leads)}")
    tight = [r for r in measurable if r["close_lead_min"] <= 90]
    c9, l9, h9 = boot(tight, "clv_pts")
    print(f"- robustness, closes within 90 min of first pitch only (clv.py's CLOSING_LEAD_STALE_SECONDS): "
          f"CLV {fmt(c9)} [{fmt(l9)}, {fmt(h9)}] (n={len(tight)})\n")
    for fn, title in ((market_label, "By market"), (lambda r: f"{r['market']} {r['side']}", "By market and side"),
                      (lambda r: r["price_class"], "By price class"),
                      (lambda r: r["entry_class"], "By entry class (pick vs fill)"),
                      (hours_bin, "By hours before first pitch at lock"),
                      (books_bin, "By number of books at lock (entry `books`)"),
                      (lambda r: f"{r['kind']} {hours_bin(r)}", "By kind x hours before first pitch")):
        print(seg_table(meas, fn, title))
        print()
    # representativeness of the measurable prop subset
    props = [r for r in meas if r["kind"] == "prop"]
    pm_ = [r for r in props if r.get("clv_pts") is not None]
    pn_ = [r for r in props if r.get("clv_pts") is None]
    print("**Is the measurable prop subset representative?**\n")
    print("| prop subset | n | W-L | units | mean price | mean hours before fp | mean books | mean premium pts | share fills |")
    print("|---|---|---|---|---|---|---|---|---|")
    for lab, g in (("measurable", pm_), ("not measurable", pn_)):
        w, l, u = record(g)
        print(f"| {lab} | {len(g)} | {w}-{l} | {u:+.2f} | {mean([r['price'] for r in g]):.1f} | "
              f"{fmt(mean([r.get('hours_before_fp') for r in g]), 1, False)} | {mean([r['books'] for r in g]):.2f} | "
              f"{fmt(mean([r.get('premium_pts') for r in g]))} | {100*sum(r['entry_class']=='fill' for r in g)/max(1,len(g)):.0f}% |")
    print()
    out["clv"] = {"n": n, "measurable": len(measurable), "absences": dict(ab),
                  "clv_pts": [c, lo, hi], "move_pts": [mv, mlo, mhi], "premium_pts": [pr, plo, phi],
                  "price_matches_best": [pm, len(rebuilt)], "fair_matches": [fm, len(rebuilt)]}


def section_trajectory(meas, refused_meas, out):
    print("## 2. Where the market goes after we bet\n")

    def cls(r):
        m = r.get("move_pts")
        if m is None:
            return None
        return "toward us" if m > FLAT_PTS else "against us" if m < -FLAT_PTS else "flat"

    def pre(r):
        if r.get("p_open") is None or r.get("p_lock") is None or r.get("open_hours_before_lock", 0) <= 0.01:
            return None
        return 100 * (r["p_lock"] - r["p_open"])

    print("| population | n with later quote | toward us | flat | against us | mean move pts [95% CI] | "
          "mean move to next capture | mean max favourable | mean max adverse | mean pre-quote move (open->quote) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    res = {}
    for lab, pop in (("taken (graded) props", [r for r in meas if r["kind"] == "prop"]),
                     ("taken (graded) moneylines", [r for r in meas if r["kind"] == "game"]),
                     ("refused close calls, props", [r for r in refused_meas if r["kind"] == "prop"]),
                     ("refused close calls, moneylines", [r for r in refused_meas if r["kind"] == "game"])):
        m = [r for r in pop if r.get("move_pts") is not None]
        if not m:
            print(f"| {lab} | 0 | | | | | | | | |")
            continue
        c = Counter(cls(r) for r in m)
        mv, lo, hi = boot(m, "move_pts")
        nxt = mean([100 * (r["p_next"] - r["p_lock"]) for r in m if r.get("p_next") is not None])
        pres = [pre(r) for r in m]
        print(f"| {lab} | {len(m)} | {c['toward us']} ({100*c['toward us']/len(m):.0f}%) | {c['flat']} | "
              f"{c['against us']} ({100*c['against us']/len(m):.0f}%) | {fmt(mv)} [{fmt(lo)}, {fmt(hi)}] | "
              f"{fmt(nxt)} | {fmt(mean([r.get('max_fav_pts') for r in m]))} | {fmt(mean([r.get('max_adv_pts') for r in m]))} | "
              f"{fmt(mean(pres))} (n={sum(p is not None for p in pres)}) |")
        res[lab] = {"n": len(m), "classes": dict(c), "move": [mv, lo, hi]}
    print()
    # taken minus refused, date-clustered (resample dates; both populations together)
    for kind in ("prop", "game"):
        pool = ([dict(r, _grp="t") for r in meas if r["kind"] == kind and r.get("move_pts") is not None]
                + [dict(r, _grp="r") for r in refused_meas if r["kind"] == kind and r.get("move_pts") is not None])

        def diff(sample):
            a = [r["move_pts"] for r in sample if r["_grp"] == "t"]
            b = [r["move_pts"] for r in sample if r["_grp"] == "r"]
            return (mean(a) - mean(b)) if a and b else None
        if pool:
            ci = clustered_bootstrap(pool, diff)
            print(f"- taken minus refused consensus move, {kind}: {fmt(diff(pool))} pts [{fmt(ci.get('low'))}, {fmt(ci.get('high'))}]")
            res[f"taken_minus_refused_{kind}"] = [diff(pool), ci.get("low"), ci.get("high")]
    rc = [r for r in refused_meas if r.get("clv_pts") is not None]
    c, lo, hi = boot(rc, "clv_pts")
    pr, plo, phi = boot([r for r in refused_meas if r.get("premium_pts") is not None], "premium_pts")
    print(f"- refused close calls: CLV {fmt(c)} [{fmt(lo)}, {fmt(hi)}] (n={len(rc)}); premium at their quote {fmt(pr)} [{fmt(plo)}, {fmt(phi)}]")
    tp = [r for r in meas if r["kind"] == "prop" and r.get("open_hours_before_lock") is not None]
    first = sum(r["open_hours_before_lock"] <= 0.01 for r in tp)
    tpm = [r for r in tp if r.get("move_pts") is not None]
    firstm = sum(r["open_hours_before_lock"] <= 0.01 for r in tpm)
    print(f"- props: the graded quote is the selection's FIRST capture in the store on {first}/{len(tp)} graded props "
          f"({firstm}/{len(tpm)} of the measurable ones), so pre-quote drift is mostly unmeasurable for props.\n")
    print(seg_table([r for r in meas if r["kind"] == "prop"],
                    lambda r: f"{r.get('expected_pa_source')}",
                    "Taken props by plate-appearance source at the quote (season_average = lineup not yet used)"))
    print()
    print(seg_table([r for r in refused_meas if r["kind"] == "prop"],
                    lambda r: f"{r.get('expected_pa_source')}",
                    "Refused prop close calls by plate-appearance source (no results: W-L columns are empty by construction)"))
    print()
    # chase vs fade: does the pre-quote move predict the post-quote move?
    print("**Pre-quote drift vs post-quote drift (taken entries with an earlier capture: moneylines only):**\n")
    print("| pre-quote move | n | mean post move pts | W-L | units |\n|---|---|---|---|---|")
    groups = defaultdict(list)
    for r in meas:
        p = pre(r)
        if p is None or r.get("move_pts") is None:
            continue
        groups["a market already moved toward us (>+0.5)" if p > FLAT_PTS else
               "c market had moved against us (<-0.5)" if p < -FLAT_PTS else "b flat"].append(r)
    for k in sorted(groups):
        g = groups[k]
        w, l, u = record(g)
        print(f"| {k} | {len(g)} | {fmt(mean([r['move_pts'] for r in g]))} | {w}-{l} | {u:+.2f} |")
    print()
    # graded outcome by post move direction (does the market's move predict our result?)
    print("**Result by direction of the post-quote move (taken, measurable):**\n")
    print("| move | n | W-L | hit % | units | mean price |\n|---|---|---|---|---|---|")
    g2 = defaultdict(list)
    for r in meas:
        c = cls(r)
        if c:
            g2[c].append(r)
    for k in ("toward us", "flat", "against us"):
        g = g2.get(k, [])
        if not g:
            continue
        w, l, u = record(g)
        print(f"| {k} | {len(g)} | {w}-{l} | {100*w/len(g):.1f} | {u:+.2f} | {mean([r['price'] for r in g]):.0f} |")
    print()
    out["trajectory"] = res


def section_vig(meas, out):
    print("## 3. Vig, book choice and the price we were graded at\n")
    rows = meas
    by = defaultdict(list)
    for r in rows:
        by[r["market"]].append(r)
    by["ALL"] = list(rows)
    print("| market | n | premium vs lock consensus pts | best-book two-way hold % | mean board hold % | "
          "graded price vs board average (cents) | graded price == best at quote |")
    print("|---|---|---|---|---|---|---|")
    for k in sorted(by, key=lambda x: (x == "ALL", x)):
        g = by[k]
        cents_avg = mean([cents(r["price"]) - cents(r["lock_avg_price"]) for r in g if r.get("lock_avg_price") is not None])
        pm = [r for r in g if r.get("price_matches_best") is not None]
        print(f"| {k} | {len(g)} | {fmt(mean([r.get('premium_pts') for r in g]))} | "
              f"{fmt(100*mean([r.get('lock_best_overround') for r in g]) if mean([r.get('lock_best_overround') for r in g]) is not None else None, 2, False)} | "
              f"{fmt(100*mean([r.get('lock_mean_overround') for r in g]) if mean([r.get('lock_mean_overround') for r in g]) is not None else None, 2, False)} | "
              f"{fmt(cents_avg, 1)} | {sum(bool(r['price_matches_best']) for r in pm)}/{len(pm)} |")
    print()
    # decomposition
    w, l, actual = record(rows)
    n = len(rows)
    fair_u, fair_n = units_at(rows, prob_key="p_lock")
    avg_rows = [r for r in rows if r.get("lock_avg_price") is not None]
    avg_u, avg_n = units_at(avg_rows, price_key="lock_avg_price")
    act_avg_sub = sum(r["profit"] for r in avg_rows)
    hind = [r for r in rows if r.get("hindsight_best_price") is not None]
    hind_u, hind_n = units_at(hind, price_key="hindsight_best_price")
    act_hind_sub = sum(r["profit"] for r in hind)
    exp_lock = sum(r["p_lock"] * (dec(r["price"]) - 1) - (1 - r["p_lock"]) for r in rows if r.get("p_lock") is not None)
    cl = [r for r in rows if r.get("p_close") is not None]
    exp_close = sum(r["p_close"] * (dec(r["price"]) - 1) - (1 - r["p_close"]) for r in cl)
    act_cl = sum(r["profit"] for r in cl)
    exp_close_fair = sum(r["p_close"] * (1 / r["p_lock"] - 1) - (1 - r["p_close"]) for r in cl if r.get("p_lock"))
    wins_exp_lock = sum(r["p_lock"] for r in rows if r.get("p_lock") is not None)
    be_sum = sum(r["be_lock"] for r in rows)
    print("**Decomposition of the record (all 178 graded entries unless stated):**\n")
    print("| quantity | units | note |\n|---|---|---|")
    print(f"| actual, at the graded price | {actual:+.2f} | {w}-{l}, n={n} |")
    print(f"| same results at the lock consensus fair price (no vig) | {fair_u:+.2f} | n={fair_n}; the pick quality the lock market would have paid for |")
    print(f"| vig cost actually paid (actual minus fair) | {actual - fair_u:+.2f} | |")
    print(f"| same results at the board AVERAGE price at the quote | {avg_u:+.2f} | n={avg_n} (actual on that subset {act_avg_sub:+.2f}) |")
    print(f"| HINDSIGHT: same results at the best price any book showed from the quote to first pitch | {hind_u:+.2f} | n={hind_n} (actual on that subset {act_hind_sub:+.2f}); retrospective, not takeable |")
    print(f"| market-expected units at the graded price, lock consensus | {exp_lock:+.2f} | what the lock market expected these bets to return |")
    print(f"| market-expected units at the graded price, closing consensus | {exp_close:+.2f} | n={len(cl)} (actual on that subset {act_cl:+.2f}) |")
    print(f"| expected wins at lock consensus vs actual wins | {wins_exp_lock:.1f} vs {w} | breakeven wins at graded prices {be_sum:.1f} |")
    print()
    # win-count CI against market expectation (date-clustered)
    for r in rows:
        r["_win_minus_plock"] = (1.0 if r["result"] == "WIN" else 0.0) - (r["p_lock"] or 0)
        r["_win_minus_be"] = (1.0 if r["result"] == "WIN" else 0.0) - r["be_lock"]
    m1, lo1, hi1 = boot(rows, "_win_minus_plock")
    m2, lo2, hi2 = boot(rows, "_win_minus_be")
    print(f"Hit rate minus lock consensus probability: {fmt(100*m1)} pts [{fmt(100*lo1)}, {fmt(100*hi1)}] per bet; "
          f"hit rate minus breakeven of the graded price: {fmt(100*m2)} pts [{fmt(100*lo2)}, {fmt(100*hi2)}].\n")
    # by market
    print("| market | n | W-L | actual units | at lock fair | vig cost | market-expected (lock) | hit % | mean p_lock % | mean breakeven % |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(by, key=lambda x: (x == "ALL", x)):
        g = by[k]
        w_, l_, u_ = record(g)
        fu, _ = units_at(g, prob_key="p_lock")
        el = sum(r["p_lock"] * (dec(r["price"]) - 1) - (1 - r["p_lock"]) for r in g)
        print(f"| {k} | {len(g)} | {w_}-{l_} | {u_:+.2f} | {fu:+.2f} | {u_-fu:+.2f} | {el:+.2f} | {100*w_/len(g):.1f} | "
              f"{100*mean([r['p_lock'] for r in g]):.1f} | {100*mean([r['be_lock'] for r in g]):.1f} |")
    print()
    out["vig"] = {"actual": actual, "fair": fair_u, "avg": [avg_u, avg_n, act_avg_sub],
                  "hindsight_best": [hind_u, hind_n, act_hind_sub], "expected_lock": exp_lock,
                  "expected_close": [exp_close, len(cl), act_cl], "hit_minus_plock": [m1, lo1, hi1],
                  "hit_minus_be": [m2, lo2, hi2]}


def section_stale(meas, out):
    print("## 4. Stale and thin boards\n")
    for fn, title in ((books_bin, "Books at lock (entry `books`)"),
                      (lambda r: ("1-2 books" if (r.get("books") or 0) <= 2 else "3+ books"), "Thin (1-2 books) vs 3+"),
                      (age_bin, "Quote age at lock (locked_at minus quote instant)"),
                      (lambda r: ("G3_STALE fill" if "G3_STALE" in r["failed_gates"] else "fresh (no G3)"), "Card's own staleness gate"),
                      (lambda r: ("thin or stale" if ((r.get("books") or 0) <= 2 or (r.get("quote_age_at_lock_min") or 0) > 60
                                                      or "G3_STALE" in r["failed_gates"]) else "fresh multi-book"),
                       "Thin-or-stale vs fresh multi-book (3+ books, quote <=60m old at lock, no G3)"),
                      (lambda r: ("best book updated >30m before capture" if (r.get("best_book_update_age_min") or 0) > 30
                                  else "best book updated <=30m" if r.get("best_book_update_age_min") is not None else "unknown"),
                       "Age of the best book's own last update at the quote")):
        print(seg_table(meas, fn, title))
        print()
    pub = [r for r in load_cards() if r.get("kind") == "card_published"]
    stale_flags = Counter(bool(r.get("stale_board")) for r in pub)
    pcs = Counter()
    for line in open(DECISIONS, encoding="utf-8"):
        d = json.loads(line)
        pcs[d.get("point_class")] += 1
    # Was the graded price still there when a reader could act / when it froze?
    print("**Was the graded price still on the board? (newest capture at or before the moment, newer than the quote)**\n")
    print("| moment | kind | n entries | n with a newer capture | graded price still available (best >= graded) | "
          "mean cents best-now minus graded | mean consensus drift since quote pts | side no longer two-sided |")
    print("|---|---|---|---|---|---|---|---|")
    for tag, label in (("pub", "first publish"), ("lock", "lock (locked_at)")):
        for kind in ("prop", "game"):
            g = [r for r in meas if r["kind"] == kind]
            newer = [r for r in g if r.get(f"newer_capture_before_{tag}")]
            av = [r for r in newer if r.get(f"avail_cents_at_{tag}") is not None]
            still = sum(r[f"avail_cents_at_{tag}"] >= 0 for r in av)
            gone = sum(bool(r.get(f"side_gone_at_{tag}")) for r in newer)
            print(f"| {label} | {kind} | {len(g)} | {len(newer)} | {still}/{len(av)} | "
                  f"{fmt(mean([r[f'avail_cents_at_{tag}'] for r in av]), 1)} | "
                  f"{fmt(mean([r.get(f'drift_pts_at_{tag}') for r in av]))} | {gone} |")
    print()
    fp_gap = [((_t(r["first_published_utc"]) - _t(r["quote_utc"])).total_seconds() / 60.0, r["kind"])
              for r in meas if r.get("first_published_utc") and r.get("quote_utc")]
    for kind in ("prop", "game"):
        xs = sorted(x for x, k in fp_gap if k == kind)
        if xs:
            print(f"- quote age at first publish, {kind}: median {statistics.median(xs):.0f} min, "
                  f">60 min on {sum(x > 60 for x in xs)}/{len(xs)}, negative (quote after first publish) on {sum(x < 0 for x in xs)}")
    print()
    print(f"`stale_board` on {len(pub)} published V2 card rows: {dict(stale_flags)} (never set). "
          f"`point_class` on evidence/decisions_v2.jsonl ({sum(pcs.values())} rows, the paper-system ledger, not the card): {dict(pcs)}. "
          "A field with one value cannot predict anything; neither is joinable to the card's entries.\n")
    out["stale"] = {"stale_board": dict(stale_flags), "point_class": dict(pcs)}


def section_moneyline(meas, out):
    print("## 5. Moneyline sanity (all graded moneylines)\n")
    ml = [r for r in meas if r["kind"] == "game"]
    print("| date | team | side | fav/dog | entry | books | price | p_lock % | breakeven % | p_close % | move pts | CLV pts | same-book close | result |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(ml, key=lambda r: r["date"]):
        fav = "fav" if r["price"] < 0 else "dog"
        print(f"| {r['date']} | {r['team_name']} | {r['side']} | {fav} | {r['entry_class']} | {r['books']} | {r['price']:+d} | "
              f"{100*r['p_lock']:.1f} | {100*r['be_lock']:.1f} | {fmt(100*r['p_close'] if r.get('p_close') else None, 1, False)} | "
              f"{fmt(r.get('move_pts'))} | {fmt(r.get('clv_pts'))} | {r.get('same_book_close_price') if r.get('same_book_close_price') is not None else 'n/a'} | {r['result']} |")
    print()
    print("| group | n | W-L | units | n CLV | mean CLV pts | mean move pts |\n|---|---|---|---|---|---|---|")
    groups = defaultdict(list)
    for r in ml:
        groups[f"{r['side']} {'favourite' if r['price'] < 0 else 'underdog'}"].append(r)
        groups["ALL"].append(r)
    for k in sorted(groups, key=lambda x: (x == "ALL", x)):
        g = groups[k]
        w, l, u = record(g)
        m = [r for r in g if r.get("clv_pts") is not None]
        print(f"| {k} | {len(g)} | {w}-{l} | {u:+.2f} | {len(m)} | {fmt(mean([r['clv_pts'] for r in m]))} | {fmt(mean([r['move_pts'] for r in m]))} |")
    print()
    m, lo, hi = boot([r for r in ml if r.get("clv_pts") is not None], "clv_pts")
    print(f"Moneyline CLV, date-clustered: {fmt(m)} pts [{fmt(lo)}, {fmt(hi)}].\n")
    out["moneyline"] = {"n": len(ml), "clv": [m, lo, hi]}


# ---------------------------------------------------------------------------
# Section 6 -- the market as a forecaster
# ---------------------------------------------------------------------------

def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def logloss(ps, ys):
    eps = 1e-6
    return -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)) for p, y in zip(ps, ys)) / len(ps)


def calib_table(ps, ys, bins=(0, .3, .4, .45, .5, .55, .6, .65, .7, .8, 1.01)):
    lines = ["| forecast band | n | mean forecast % | observed % |", "|---|---|---|---|"]
    for lo, hi in zip(bins[:-1], bins[1:]):
        sel = [(p, y) for p, y in zip(ps, ys) if lo <= p < hi]
        if not sel:
            continue
        lines.append(f"| {lo:.2f}-{min(hi,1):.2f} | {len(sel)} | {100*mean([p for p,_ in sel]):.1f} | {100*mean([y for _,y in sel]):.1f} |")
    return "\n".join(lines)


def box_batters(first=OPEN_2026, last="2026-12-31"):
    out = {}
    pks = set()
    for line in open(BOX_2026, encoding="utf-8"):
        d = json.loads(line)
        day = d.get("date") or ""
        if _sealed(day) or day < first or day > last:
            continue                      # sealed rows dropped before any other field is read
        pks.add(str(d.get("game_pk")))
        if d.get("type") == "batter":
            out[(str(d["game_pk"]), d.get("player_name"))] = d
    return out, pks


def results_by_pk(first, last):
    out = {}
    with open(RESULTS, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            day = row["date"]
            if _sealed(day) or day < first or day > last:
                continue
            out[row["game_pk"]] = row
    return out


def section_baseline(meas, out):
    print("## 6. Market-efficiency baseline (open windows only)\n")
    by_pk, by_event = event_map()
    box, pks = box_batters()
    res = {}
    # props 2026-08-28 onward
    pidx = PropIndex(markets=("batter_hits", "batter_total_bases"), first_day=OPEN_2026, last_day="2026-10-15")
    groups = defaultdict(lambda: ([], []))
    unmatched = 0
    for key, inst in pidx.q.items():
        ev, player, market, line = key
        commence = _t(pidx.commence.get(ev))
        pk = by_event.get(ev)
        if commence is None or pk is None:
            continue
        pre = sorted(((_t(i), b) for i, b in inst.items() if _t(i) < commence), key=lambda x: x[0])
        boards = [board(b, "Over", prop=True) for _, b in pre]
        boards = [b for b in boards if b.get("two_sided", 0) >= PROP_MIN_TWO_SIDED]
        if not boards:
            continue
        row = box.get((pk, player))
        if row is None:
            unmatched += 1
            continue
        stat = row.get("h") if market == "batter_hits" else row.get("total_bases")
        if stat is None:
            continue
        y = 1 if stat > line else 0
        g = groups[f"{market} {line}"]
        g[0].append(boards[-1]["fair"])
        g[1].append(y)
    print(f"Props: de-vigged consensus Over probability at the last pre-game capture (>= {PROP_MIN_TWO_SIDED} two-sided books), "
          f"games 2026-08-28..2026-10-15, joined to box scores by (game_pk, player name) as settlement does; {unmatched} contracts had no box row.\n")
    print("| contract | n | base rate % | Brier market | Brier base rate | Brier skill vs base rate % | log loss market | log loss base rate |")
    print("|---|---|---|---|---|---|---|---|")
    for k in sorted(groups):
        ps, ys = groups[k]
        if len(ps) < 30:
            continue
        br = mean(ys)
        bm, bb = brier(ps, ys), brier([br] * len(ys), ys)
        print(f"| {k} | {len(ps)} | {100*br:.1f} | {bm:.4f} | {bb:.4f} | {100*(1-bm/bb):.2f} | {logloss(ps, ys):.4f} | {logloss([br]*len(ys), ys):.4f} |")
        res[k] = {"n": len(ps), "brier": bm, "brier_base": bb}
    print()
    for k in ("batter_hits 0.5", "batter_total_bases 1.5"):
        if k in groups and len(groups[k][0]) >= 30:
            print(f"Calibration, {k} (market consensus):\n")
            print(calib_table(*groups[k]))
            print()
    # our model vs the market on the very entries we bet
    print("**Our number vs the market's on the 178 graded entries (selected side; outcome = WIN):**\n")
    print("| population | n | Brier market (p_lock) | Brier ours raw | Brier ours marked down | ours minus market [95% CI] | mean p_lock % | mean ours % | hit % |")
    print("|---|---|---|---|---|---|---|---|---|")
    for lab, pop in (("all", meas), ("props", [r for r in meas if r["kind"] == "prop"]),
                     ("moneylines", [r for r in meas if r["kind"] == "game"])):
        pop = [r for r in pop if r.get("p_lock") is not None and r.get("our_p") is not None]
        ys = [1.0 if r["result"] == "WIN" else 0.0 for r in pop]
        bm = brier([r["p_lock"] for r in pop], ys)
        bo = brier([r["our_p"] for r in pop], ys)
        bu = brier([r["our_p_used"] for r in pop], ys)
        for r, y in zip(pop, ys):
            r["_brier_diff"] = (r["our_p"] - y) ** 2 - (r["p_lock"] - y) ** 2
        d, lo, hi = boot(pop, "_brier_diff")
        print(f"| {lab} | {len(pop)} | {bm:.4f} | {bo:.4f} | {bu:.4f} | {fmt(d, 4)} [{fmt(lo, 4)}, {fmt(hi, 4)}] | "
              f"{100*mean([r['p_lock'] for r in pop]):.1f} | {100*mean([r['our_p'] for r in pop]):.1f} | {100*mean(ys):.1f} |")
    print()
    # moneylines: 2026-08-28 onward (multibook) and 2024 (odds_history)
    gidx = GameIndex(first_day=OPEN_2026)
    results = results_by_pk(OPEN_2026, "2026-12-31")
    ps, ys = [], []
    for ev, inst in gidx.q.items():
        commence = _t(gidx.commence.get(ev))
        pk = by_event.get(ev)
        row = results.get(pk) if pk else None
        if commence is None or row is None or row.get("home_won") not in ("0", "1"):
            continue
        pre = sorted(((_t(i), b) for i, b in inst.items() if _t(i) < commence), key=lambda x: x[0])
        boards = [board(b, "home", prop=False) for _, b in pre]
        boards = [b for b in boards if b.get("two_sided", 0) >= GAME_MIN_BOOKS]
        if not boards:
            continue
        ps.append(boards[-1]["fair"])
        ys.append(int(row["home_won"]))
    ml_lines = []
    if ps:
        br = mean(ys)
        ml_lines.append(("moneyline home, 2026-08-28..", len(ps), br, brier(ps, ys), brier([br] * len(ys), ys),
                         logloss(ps, ys), logloss([br] * len(ys), ys)))
        res["ml_2026"] = {"n": len(ps), "brier": brier(ps, ys)}
    p24, y24 = moneyline_2024()
    if p24:
        br = mean(y24)
        ml_lines.append(("moneyline home, 2024 season", len(p24), br, brier(p24, y24), brier([br] * len(y24), y24),
                         logloss(p24, y24), logloss([br] * len(y24), y24)))
        res["ml_2024"] = {"n": len(p24), "brier": brier(p24, y24)}
    print("| moneyline sample | n | home win % | Brier market | Brier base rate | skill % | log loss market | log loss base |")
    print("|---|---|---|---|---|---|---|---|")
    for lab, n, br, bm, bb, lm, lb in ml_lines:
        print(f"| {lab} | {n} | {100*br:.1f} | {bm:.4f} | {bb:.4f} | {100*(1-bm/bb):.2f} | {lm:.4f} | {lb:.4f} |")
    print()
    if p24:
        print("Calibration, 2024 moneyline home (closing consensus):\n")
        print(calib_table(p24, y24))
        print()
    out["baseline"] = res


def _nick(full):
    for abbr, d in TEAM_NAMES.items():
        if d["full"] == full or full.endswith(d["name"]):
            return abbr
    return None


def moneyline_2024():
    """2024 closing consensus (last of the archive's daily snapshots before
    commence, >= 6 books) against 2024 results joined on date + teams."""
    alias = {"OAK": "ATH", "ARI": "AZ", "CHW": "CWS", "WAS": "WSH"}
    results = {}
    with open(RESULTS, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row["date"].startswith("2024") or row["game_type"] != "R":
                continue
            a = alias.get(row["away_team"], row["away_team"])
            h = alias.get(row["home_team"], row["home_team"])
            results.setdefault((row["start_time_utc"][:13], a, h), row)
    last = {}
    with gzip.open(ODDS_2024, "rt", encoding="utf-8") as fh:
        for line in fh:
            snap = json.loads(line)
            for e in snap.get("events") or ():
                commence = _t(e.get("commence_time"))
                books = {}
                ts = None
                for b in e.get("bookmakers") or ():
                    for m in b.get("markets") or ():
                        if m.get("key") != "h2h":
                            continue
                        pr = {o["name"]: o["price"] for o in m.get("outcomes") or ()}
                        if e["home_team"] in pr and e["away_team"] in pr:
                            books[b["key"]] = {"home": pr[e["home_team"]], "away": pr[e["away_team"]]}
                            t = _t(m.get("last_update") or b.get("last_update"))
                            ts = t if ts is None or (t and t > ts) else ts
                if not books or commence is None or ts is None or ts >= commence:
                    continue
                k = (e["commence_time"], e["home_team"], e["away_team"])
                if k not in last or ts > last[k][0]:
                    last[k] = (ts, books)
    ps, ys = [], []
    for (commence, home, away), (ts, books) in last.items():
        b = board(books, "home", prop=False)
        if b.get("two_sided", 0) < GAME_MIN_BOOKS:
            continue
        a_ab, h_ab = _nick(away), _nick(home)
        row = None
        c = _t(commence)
        for dh in (0, -1, 1):
            hour = (c.replace(minute=0, second=0, microsecond=0)
                    .timestamp() + dh * 3600)
            key = (datetime.fromtimestamp(hour, timezone.utc).strftime("%Y-%m-%dT%H"), a_ab, h_ab)
            row = results.get(key)
            if row:
                break
        if row is None or row.get("home_won") not in ("0", "1"):
            continue
        ps.append(b["fair"])
        ys.append(int(row["home_won"]))
    return ps, ys


# ---------------------------------------------------------------------------
# Section 7 -- hindsight rules
# ---------------------------------------------------------------------------

def section_rules(meas, out):
    print("## 7. Price-side rules, applied in hindsight (HINDSIGHT -- not a result)\n")
    rules = [
        ("baseline (as graded)", lambda r: True),
        ("min 3 books", lambda r: (r.get("books") or 0) >= 3),
        ("min 4 books", lambda r: (r.get("books") or 0) >= 4),
        ("quote <=60m old at lock", lambda r: r.get("quote_age_at_lock_min") is not None and r["quote_age_at_lock_min"] <= 60),
        ("no G3_STALE fills", lambda r: "G3_STALE" not in r["failed_gates"]),
        ("picks only (no fills)", lambda r: r["entry_class"] == "pick"),
        (">=2h before first pitch at lock", lambda r: (r.get("hours_before_fp") or 0) >= 2),
        ("<4h before first pitch at lock", lambda r: r.get("hours_before_fp") is not None and r["hours_before_fp"] < 4),
        ("premium paid <=2 pts", lambda r: r.get("premium_pts") is not None and r["premium_pts"] <= 2.0),
        ("moneylines only", lambda r: r["kind"] == "game"),
        ("props only", lambda r: r["kind"] == "prop"),
    ]
    print("| rule | n kept | W-L | units | ROI % | n CLV | mean CLV pts [95% CI] | units if graded at hindsight best |")
    print("|---|---|---|---|---|---|---|---|")
    res = {}
    for name, f in rules:
        g = [r for r in meas if f(r)]
        if not g:
            continue
        w, l, u = record(g)
        m = [r for r in g if r.get("clv_pts") is not None]
        c, lo, hi = boot(m, "clv_pts")
        hb, _ = units_at([r for r in g if r.get("hindsight_best_price") is not None], price_key="hindsight_best_price")
        print(f"| {name} | {len(g)} | {w}-{l} | {u:+.2f} | {100*u/len(g):+.1f} | {len(m)} | {fmt(c)} [{fmt(lo)}, {fmt(hi)}] | {hb:+.2f} |")
        res[name] = {"n": len(g), "w": w, "l": l, "units": u, "clv": [c, lo, hi]}
    print()
    out["rules"] = res


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", default="all",
                    choices=["all", "clv", "trajectory", "vig", "stale", "moneyline", "baseline", "rules"])
    args = ap.parse_args(argv)
    cards = load_cards()
    graded = graded_entries(cards)
    taken = {sel_key(e) for e in graded}
    refused = refused_candidates(cards, taken)
    by_pk, _ = event_map()
    pidx = PropIndex()
    gidx = GameIndex()
    fp_map = first_published(cards)
    for e in graded + refused:
        e["_first_published_utc"] = fp_map.get((e["date"],) + sel_key(e))
    meas = [measure(e, pidx, gidx, by_pk) for e in graded]
    refused_meas = [measure(dict(e, result=None, profit_units=None), pidx, gidx, by_pk) for e in refused]
    w, l, u = record(meas)
    print(f"# Loss diagnosis 03 -- prices (generated by scripts/diagnosis/prices.py)\n")
    print(f"Population: {len(meas)} graded V2 entries, {w}-{l}, {u:+.3f} units; "
          f"{len(refused_meas)} refused close calls (deduplicated, never graded).\n")
    out = {"population": {"n": len(meas), "w": w, "l": l, "units": u, "refused": len(refused_meas)}}
    s = args.section
    if s in ("all", "clv"):
        section_clv(meas, out)
    if s in ("all", "trajectory"):
        section_trajectory(meas, refused_meas, out)
    if s in ("all", "vig"):
        section_vig(meas, out)
    if s in ("all", "stale"):
        section_stale(meas, out)
    if s in ("all", "moneyline"):
        section_moneyline(meas, out)
    if s in ("all", "baseline"):
        section_baseline(meas, out)
    if s in ("all", "rules"):
        section_rules(meas, out)
    os.makedirs(OUT_DIR, exist_ok=True)
    if s == "all":
        with open(os.path.join(OUT_DIR, "prices_summary.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, default=str, sort_keys=True)
        keep = ("date", "kind", "market", "side", "price", "price_class", "entry_class", "books", "result",
                "profit", "player", "team_name", "line", "game_pk", "p_lock", "be_lock", "premium_pts",
                "quote_age_at_lock_min", "hours_before_fp", "absence", "price_matches_best", "fair_matches",
                "lock_avg_price", "lock_best_overround", "p_open", "p_close", "close_lead_min", "clv_pts",
                "move_pts", "same_book_close_price", "clv_same_book_pts", "cents_same_book",
                "hindsight_best_price", "best_book_update_age_min", "our_p", "our_p_used",
                "quote_utc", "locked_at", "first_pitch_utc", "first_published_utc", "event_id",
                "avail_cents_at_pub", "avail_cents_at_lock", "drift_pts_at_pub", "drift_pts_at_lock",
                "lock_two_sided", "close_two_sided", "failed_gates", "withdrawn")
        with open(os.path.join(OUT_DIR, "prices_entries.jsonl"), "w", encoding="utf-8") as fh:
            for r in meas:
                fh.write(json.dumps({k: r.get(k) for k in keep}, default=str, sort_keys=True) + "\n")


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)

    def flush(self):
        for st in self.streams:
            st.flush()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "prices_tables.md"), "w", encoding="utf-8") as _fh:
            _orig = sys.stdout
            sys.stdout = _Tee(_orig, _fh)
            try:
                main([])
            finally:
                sys.stdout = _orig
    else:
        main()
