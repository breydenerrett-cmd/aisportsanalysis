"""Standing value scan: "where, if anywhere, is there predictive value?" as a table.

    python scripts/value_scan.py [--stdout] [--as-of YYYY-MM-DD]

READ-ONLY on every ledger and data store. It MEASURES; it changes no rule, no
gate, no threshold and no published record. It writes exactly one file,
`docs/VALUE_SCAN.md` (or prints it with --stdout).

WHAT IT READS
-------------
The repository's own card ledgers, through the project's own readers:
  * `card_ledger.latest_settled_rows_v2` (V2 public + shadows A/C/E): the NEWEST
    `card_settled` row per date is that date's whole record (re-entrant settle).
  * V1-style stores (V1 public, V1 shadow, NFL): the newest `card_settled` row per
    date, corrections folded on top (`card_ledger._apply_corrections`), each graded
    pick joined back to the PUBLISHED row it was graded against
    (`card_ledger._frozen_for_graded`, `_prop_pick_key`, `_total_pick_key`) to
    recover the market probability, our probability, the quote time and the sides.
  * `card_clv.measure_pick`, exactly as the product calls it, for closing-line
    value. It refuses every prop (PROP_NOT_MEASURED) and a stale or thin close; a
    refusal is reported as a refusal, never replaced by another number.
  * `effective_record._ledger_postseason_pks` / `_is_postseason_entry` for the
    postseason split (the project's own calendar rule; the results store, which
    holds the sealed window, is deliberately NOT opened).

POPULATIONS, NEVER POOLED
-------------------------
One row per (rule, market, entry class, season scope). Fills never enter a pick
row; postseason entries never enter a regular-season row; withdrawn and void
entries are counted and never staked.

THE VERDICT RULE (fixed, applied identically to every row)
----------------------------------------------------------
  n staked < 30                                      -> TOO FEW
  n >= 100 AND mean CLV > 0 AND lower end of the 95% interval of mean CLV > 0
          AND z vs market > 2                        -> CANDIDATE
  otherwise                                          -> NO EVIDENCE
A CANDIDATE is a hypothesis for a pre-registered forward test
(docs/PREREG_CARD_V2.md), never a reason to change a rule.

SEALED WINDOW
-------------
Nothing dated 2026-01-01..2026-08-27 is ever read. The card ledgers begin
2026-09-10, so the script asserts that no row in any ledger carries a date in the
window and exits 2 if one does, before writing anything.

Deterministic: the same ledgers give the same bytes, except the one "Generated"
line. Python standard library only.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEALED_START = "2026-01-01"
SEALED_END = "2026-08-27"
CLV_SINCE = "2026-09-01"          # first date any multibook row is requested from

MIN_N_STAKED = 30                  # below this: TOO FEW
MIN_N_CANDIDATE = 100
Z_CANDIDATE = 2.0
CI_Z = 1.96

VERDICT_TOO_FEW = "TOO FEW"
VERDICT_NO_EVIDENCE = "NO EVIDENCE"
VERDICT_CANDIDATE = "CANDIDATE"

RULE_ORDER = ("V1 public", "V1 shadow", "V2 public", "V2 shadow A",
              "V2 shadow C", "V2 shadow E", "NFL V1", "NFL V2")
MARKET_ORDER = ("moneyline", "run line", "hits prop", "total-bases prop", "other")
CLASS_ORDER = ("pick", "fill", "withdrawn")
SCOPE_ORDER = ("regular", "postseason")

WIN, LOSS, PUSH, VOID, UNRESOLVED = "WIN", "LOSS", "PUSH", "VOID", "UNRESOLVED"

# Which field each rule's "our probability" is read from (printed in the report).
OUR_PROBABILITY_FIELDS = {
    "V1 public": "game/total: model_probability; prop: probability",
    "V1 shadow": "game/total: model_probability; prop: probability",
    "V2 public": "our_probability_used (after the 0.038 markdown)",
    "V2 shadow A": "our_probability_used (after the 0.038 markdown)",
    "V2 shadow C": "our_probability_used (after the 0.038 markdown)",
    "V2 shadow E": "our_probability_used (after the 0.038 markdown)",
    "NFL V1": "model_probability (frozen null on every NFL pick)",
    "NFL V2": "model_probability (frozen null on every NFL pick)",
}
NFL_RULE_LABELS = {"NFL_CARD_V1": "NFL V1", "NFL_CARD_V2": "NFL V2"}


class SealedWindowError(RuntimeError):
    """A ledger row is dated inside the sealed research window."""


# ---------------------------------------------------------------------------
# Pure arithmetic: no disk, no project imports. Everything takes plain dicts.
# ---------------------------------------------------------------------------

def decimal_odds(price):
    """American odds -> decimal odds; None for anything that is not American."""
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p >= 100:
        return 1.0 + p / 100.0
    if p <= -100:
        return 1.0 + 100.0 / (-p)
    return None


def breakeven(price):
    """Probability at which the price breaks even (vig included)."""
    d = decimal_odds(price)
    return None if d is None else 1.0 / d


def units(price, result):
    """Profit in units at a flat 1u stake. Push, void, unresolved: 0."""
    if result == LOSS:
        return -1.0
    if result == WIN:
        d = decimal_odds(price)
        return None if d is None else d - 1.0
    return 0.0


def is_staked(entry):
    """A staked entry is a graded WIN or LOSS that is not withdrawn. Voids,
    pushes, unresolved and withdrawn entries are never staked."""
    return (entry.get("entry_class") != "withdrawn"
            and entry.get("result") in (WIN, LOSS)
            and decimal_odds(entry.get("price")) is not None)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def sample_sd(xs):
    xs = list(xs)
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def mean_se(xs):
    """(mean, standard error of the mean); se is None below two values."""
    xs = list(xs)
    if not xs:
        return None, None
    sd = sample_sd(xs)
    return sum(xs) / len(xs), (None if sd is None else sd / math.sqrt(len(xs)))


def total_units(entries):
    return sum(units(e.get("price"), e.get("result")) for e in entries if is_staked(e))


def roi(entries):
    s = [e for e in entries if is_staked(e)]
    return None if not s else total_units(s) / len(s)


def market_expected_units(entries):
    """Units the staked entries would earn if the frozen de-vigged market
    probability were exactly right: sum of p*d - 1 over entries that carry one."""
    out = 0.0
    n = 0
    for e in entries:
        p = e.get("p_mkt")
        d = decimal_odds(e.get("price"))
        if is_staked(e) and p is not None and d is not None:
            out += p * d - 1.0
            n += 1
    return (out if n else None), n


def z_vs_market(entries):
    """(z, wins, expected wins, n) with z = (wins - sum p) / sqrt(sum p(1-p)),
    over staked entries carrying a market probability. z None if no variance."""
    s = [e for e in entries if is_staked(e) and e.get("p_mkt") is not None]
    if not s:
        return None, 0, None, 0
    wins = sum(1 for e in s if e["result"] == WIN)
    exp = sum(e["p_mkt"] for e in s)
    var = sum(e["p_mkt"] * (1.0 - e["p_mkt"]) for e in s)
    if var <= 0:
        return None, wins, exp, len(s)
    return (wins - exp) / math.sqrt(var), wins, exp, len(s)


def brier_pair(entries):
    """Brier score of our probability and of the market's on the SAME staked
    entries (those carrying both), and the paired per-entry difference
    (ours minus market; positive = ours is worse) with its standard error."""
    s = [e for e in entries
         if is_staked(e) and e.get("p_our") is not None and e.get("p_mkt") is not None]
    if not s:
        return None
    ys = [1.0 if e["result"] == WIN else 0.0 for e in s]
    ours = [(e["p_our"] - y) ** 2 for e, y in zip(s, ys)]
    mkt = [(e["p_mkt"] - y) ** 2 for e, y in zip(s, ys)]
    diffs = [a - b for a, b in zip(ours, mkt)]
    d_mean, d_se = mean_se(diffs)
    return {"n": len(s), "ours": sum(ours) / len(s), "market": sum(mkt) / len(s),
            "diff": d_mean, "se": d_se}


def clv_summary(entries):
    """Closing-line value over the staked entries' `clv` measurements (the dict
    `card_clv.measure_pick` returned). Refusals are counted by named reason."""
    ok, refused = [], collections.Counter()
    for e in entries:
        if not is_staked(e):
            continue
        m = e.get("clv")
        if m is None:
            refused["NOT_ATTEMPTED"] += 1
        elif "clv_bps" in m:
            ok.append(m)
        else:
            refused[m.get("absence") or "UNKNOWN"] += 1
    pts = [m["clv_bps"] / 100.0 for m in ok]
    mu, se = mean_se(pts)
    lo = None if (mu is None or se is None) else mu - CI_Z * se
    hi = None if (mu is None or se is None) else mu + CI_Z * se
    beat = (sum(1 for m in ok if m.get("beats_close")) / len(ok)) if ok else None
    return {"n": len(ok), "mean": mu, "se": se, "lo": lo, "hi": hi, "beat": beat,
            "refused": dict(sorted(refused.items()))}


def verdict(n_staked, clv_mean, clv_lo, z):
    """The fixed rule. See the module docstring. Inputs are plain numbers or None."""
    if n_staked < MIN_N_STAKED:
        return VERDICT_TOO_FEW
    if (n_staked >= MIN_N_CANDIDATE
            and clv_mean is not None and clv_mean > 0
            and clv_lo is not None and clv_lo > 0
            and z is not None and z > Z_CANDIDATE):
        return VERDICT_CANDIDATE
    return VERDICT_NO_EVIDENCE


def summarize(entries):
    """Every column of one population row, from plain entry dicts."""
    staked = [e for e in entries if is_staked(e)]
    wins = sum(1 for e in staked if e["result"] == WIN)
    losses = len(staked) - wins
    with_mkt = [e for e in staked if e.get("p_mkt") is not None]
    with_our = [e for e in staked if e.get("p_our") is not None]
    exp_u, n_exp = market_expected_units(entries)
    z, _w, exp_w, n_z = z_vs_market(entries)
    clv = clv_summary(entries)
    out = {
        "n_entries": len(entries),
        "n_staked": len(staked), "wins": wins, "losses": losses,
        "pushes": sum(1 for e in entries if e.get("entry_class") != "withdrawn"
                      and e.get("result") == PUSH),
        "voids": sum(1 for e in entries if e.get("entry_class") != "withdrawn"
                     and e.get("result") == VOID),
        "unresolved": sum(1 for e in entries if e.get("entry_class") != "withdrawn"
                          and e.get("result") == UNRESOLVED),
        "units": total_units(entries), "roi": roi(entries),
        "mean_be": mean(breakeven(e["price"]) for e in staked),
        "mean_mkt": mean(e["p_mkt"] for e in with_mkt),
        "n_mkt": len(with_mkt),
        "mean_our": mean(e["p_our"] for e in with_our),
        "n_our": len(with_our),
        "exp_units": exp_u, "n_exp": n_exp,
        "exp_wins": exp_w, "z": z, "n_z": n_z,
        "brier": brier_pair(entries),
        "clv": clv,
        "withdrawn": sum(1 for e in entries if e.get("entry_class") == "withdrawn"),
        "withdrawn_tally": dict(sorted(collections.Counter(
            e.get("result") for e in entries if e.get("entry_class") == "withdrawn").items())),
    }
    out["verdict"] = verdict(out["n_staked"], clv["mean"], clv["lo"], z)
    return out


def market_label(raw):
    if raw == "moneyline":
        return "moneyline"
    if raw == "run_line":
        return "run line"
    if raw == "batter_hits":
        return "hits prop"
    if raw == "batter_total_bases":
        return "total-bases prop"
    return "other"


def group_populations(entries):
    """{(rule, market, class, scope): [entries]} -- never pooled across keys."""
    groups = collections.defaultdict(list)
    for e in entries:
        groups[(e["rule"], e["market"], e["entry_class"],
                "postseason" if e.get("postseason") else "regular")].append(e)
    return groups


def _sort_key(key):
    rule, market, cls, scope = key

    def pos(order, v):
        return order.index(v) if v in order else len(order)
    return (pos(RULE_ORDER, rule), pos(MARKET_ORDER, market),
            pos(CLASS_ORDER, cls), pos(SCOPE_ORDER, scope), str(key))


def passes_value_test(entry):
    """V2's G7 value test, read from two fields frozen on the entry:
    our_probability_used >= value_need. (Shadow A freezes no failed_gates, so the
    comparison of the two frozen numbers is the only mark it carries; on every
    store that does freeze G7_VALUE the two agree -- the report counts any
    disagreement.)"""
    p, need = entry.get("p_our"), entry.get("value_need")
    if p is None or need is None:
        return None
    return p >= need


def value_gate_comparison(entries):
    """Passed-vs-failed the value test on (win - market probability).
    Descriptive only. Welch standard error of the difference."""
    s = [e for e in entries
         if is_staked(e) and e.get("p_mkt") is not None
         and passes_value_test(e) is not None]
    passed = [e for e in s if passes_value_test(e)]
    failed = [e for e in s if not passes_value_test(e)]

    def side(es):
        if not es:
            return {"n": 0, "wins": 0, "losses": 0, "units": 0.0, "roi": None,
                    "win_minus_mkt": None, "values": []}
        vals = [(1.0 if e["result"] == WIN else 0.0) - e["p_mkt"] for e in es]
        w = sum(1 for e in es if e["result"] == WIN)
        return {"n": len(es), "wins": w, "losses": len(es) - w,
                "units": total_units(es), "roi": roi(es),
                "win_minus_mkt": sum(vals) / len(vals), "values": vals}
    a, b = side(passed), side(failed)
    diff = se = z = None
    if a["n"] >= 2 and b["n"] >= 2:
        va = sample_sd(a["values"]) ** 2
        vb = sample_sd(b["values"]) ** 2
        diff = a["win_minus_mkt"] - b["win_minus_mkt"]
        se = math.sqrt(va / a["n"] + vb / b["n"])
        z = (diff / se) if se > 0 else None
    for d in (a, b):
        d.pop("values")
    return {"passed": a, "failed": b, "diff": diff, "se": se, "z": z, "n": len(s)}


# ---------------------------------------------------------------------------
# Loading: project readers, read-only.
# ---------------------------------------------------------------------------

def _cl():
    from src.appstate import card_ledger
    return card_ledger


def _read_rows(path):
    from src.ledger.chain import HashChainLedger
    return HashChainLedger(path).read()


def _canon(rule, kind, merged, date, entry_class, *, p_our, extra=None):
    raw_market = merged.get("market")
    e = {
        "rule": rule, "date": date, "kind": kind,
        "market_raw": raw_market, "market": market_label(raw_market),
        "entry_class": entry_class,
        "price": merged.get("price"), "result": merged.get("result"),
        "ledger_units": merged.get("profit_units"),
        "side": merged.get("side"), "line": merged.get("line"),
        "p_our": p_our, "p_mkt": merged.get("market_probability"),
        "observed_utc": merged.get("observed_utc"),
        "first_pitch_utc": merged.get("first_pitch_utc"),
        "game_pk": merged.get("game_pk"), "game_id": merged.get("game_id"),
        "game_type": merged.get("game_type"),
        "event_id": merged.get("event_id"),
        "home_team": merged.get("home_team"), "away_team": merged.get("away_team"),
        "player": merged.get("player"), "sport": merged.get("sport") or "mlb",
        "reason": merged.get("reason") or merged.get("void_reason"),
        "value_need": None, "failed_gates": None, "price_class": None,
        "postseason": False,
    }
    if extra:
        e.update(extra)
    return e


def load_v1_style(path, rule_for_published=None, default_rule=None):
    """Entries of a V1-style store (V1 public, V1 shadow, NFL).

    Newest settled row per date, corrections folded, each graded pick joined to
    its own published row. Returns (entries, info)."""
    cl = _cl()
    rows = _read_rows(path)
    published_by_hash, published_by_date = {}, {}
    latest, corrections = {}, collections.defaultdict(list)
    dates = set()
    for row in rows:
        if row.get("date"):
            dates.add(row["date"])
        kind = row.get("kind")
        if kind == cl.KIND_PUBLISHED:
            published_by_hash[row.get("row_hash")] = row
            published_by_date[row.get("date")] = row
        elif kind == cl.KIND_SETTLED:
            latest[row.get("date")] = row
        elif kind == cl.KIND_CORRECTION:
            corrections[row.get("date")].append(row)
    entries = []
    for date in sorted(d for d in latest if d):
        row = latest[date]
        if date in corrections:
            row = cl._apply_corrections(row, corrections[date])
        pub = (published_by_hash.get(row.get("published_row_hash"))
               or published_by_date.get(date) or {})
        rule = (rule_for_published(pub.get("rule")) if rule_for_published
                else default_rule)
        frozen_props = {cl._prop_pick_key(p): p for p in (pub.get("prop_picks") or ())}
        frozen_totals = {cl._total_pick_key(p): p for p in (pub.get("total_picks") or ())}
        for scope, kind_name in (("picks", "game"), ("prop_picks", "prop"),
                                 ("total_picks", "total")):
            for g in row.get(scope) or ():
                if scope == "picks":
                    frozen = cl._frozen_for_graded(g, pub.get("picks") or ())
                elif scope == "prop_picks":
                    frozen = frozen_props.get(cl._prop_pick_key(g)) or {}
                else:
                    frozen = frozen_totals.get(cl._total_pick_key(g)) or {}
                merged = dict(frozen)
                merged.update(g)
                p_our = merged.get("probability") if kind_name == "prop" \
                    else merged.get("model_probability")
                cls = "fill" if merged.get("label") == "SPLIT" else "pick"
                entries.append(_canon(rule, kind_name, merged, date, cls, p_our=p_our))
    info = {"rows": len(rows), "settled_dates": sorted(d for d in latest if d),
            "dates": dates, "corrections": sum(len(v) for v in corrections.values())}
    return entries, info


def load_v2_style(path, rule):
    """Entries of a V2-style store (V2 public, shadows A/C/E)."""
    cl = _cl()
    rows = _read_rows(path)
    dates = {r["date"] for r in rows if r.get("date")}
    settled = sorted(cl.latest_settled_rows_v2(rows), key=lambda r: r.get("date") or "")
    entries = []
    for row in settled:
        date = row.get("date")
        for group, force_withdrawn in (("graded", False), ("withdrawn_graded", True)):
            for g in row.get(group) or ():
                withdrawn = force_withdrawn or bool(g.get("withdrawn"))
                cls = "withdrawn" if withdrawn else (g.get("entry_class") or "pick")
                kind = "prop" if g.get("kind") == "prop" else "game"
                entries.append(_canon(
                    rule, kind, g, date, cls, p_our=g.get("our_probability_used"),
                    extra={"value_need": g.get("value_need"),
                           "failed_gates": list(g.get("failed_gates") or ()),
                           "price_class": g.get("price_class")}))
    info = {"rows": len(rows), "settled_dates": sorted(r.get("date") for r in settled),
            "dates": dates, "corrections": 0}
    return entries, info


def check_sealed(dates):
    """Raise if any date falls inside the sealed research window."""
    bad = sorted(d for d in set(dates)
                 if isinstance(d, str) and SEALED_START <= d[:10] <= SEALED_END)
    if bad:
        raise SealedWindowError(
            "ledger rows dated inside the sealed window %s..%s: %s"
            % (SEALED_START, SEALED_END, ", ".join(bad[:10])))


def mark_postseason(entries):
    """Set `postseason` on MLB entries by the project's own rule: a frozen
    game_type other than R, or a game on a card dated inside the postseason
    calendar. NFL entries are never calendar-classified (that calendar is MLB's)."""
    from src.report import effective_record as er
    mlb = [e for e in entries if e.get("sport") == "mlb"]
    by_date = collections.defaultdict(list)
    for e in mlb:
        by_date[(e["rule"], e["date"])].append(e)
    # One synthetic history per store, so a prop (frozen game_type 'R') on a game
    # whose own game entry is 'F' is classified with it, as the product does.
    by_rule = collections.defaultdict(list)
    for (rule, date), es in by_date.items():
        by_rule[rule].append({"date": date, "graded": es})
    for rule, days in by_rule.items():
        pks = er._ledger_postseason_pks({"days": days})
        for day in days:
            for e in day["graded"]:
                e["postseason"] = bool(er._is_postseason_entry(e, pks))
    for e in entries:
        if e.get("sport") != "mlb":
            gt = e.get("game_type")
            e["postseason"] = bool(gt and gt != "R")


# ---------------------------------------------------------------------------
# Closing-line value through card_clv.measure_pick.
# ---------------------------------------------------------------------------

def _moment(text):
    if not text:
        return None
    try:
        t = _dt.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _load_event_map(path):
    """{game_pk(str): [(event_id, commence_dt)]} from the resolved rows of the
    project's event_game_map, keeping only rows whose commence_time is on or
    after CLV_SINCE (a cheap text test BEFORE parsing, so no sealed-window row is
    ever decoded)."""
    out = collections.defaultdict(list)
    p = Path(path)
    if not p.exists():
        return out
    with p.open("rb") as fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace")
            if '"commence_time": "2026-0' not in line and '"commence_time": "2026-1' not in line:
                continue
            row = json.loads(line)
            ct = str(row.get("commence_time") or "")
            if ct[:10] < CLV_SINCE or not row.get("resolved") or not row.get("event_id") \
                    or row.get("game_pk") is None:
                continue
            out[str(row["game_pk"])].append((row["event_id"], _moment(ct)))
    return out


def _resolve_mlb_event(entry, emap, tolerance_minutes=20):
    """The odds-feed event_id for an entry that froze none, by game_pk, accepted
    only when the event's commence time is within `tolerance_minutes` of the
    entry's own first pitch. No match leaves it None (card_clv then says NO_EVENT)."""
    if entry.get("event_id"):
        return entry["event_id"]
    fp = _moment(entry.get("first_pitch_utc"))
    best = None
    for event_id, ct in emap.get(str(entry.get("game_pk")), ()):
        if fp is None or ct is None:
            continue
        gap = abs((ct - fp).total_seconds()) / 60.0
        if gap <= tolerance_minutes and (best is None or gap < best[0]):
            best = (gap, event_id)
    return best[1] if best else None


def _resolve_nfl_event(entry, nfl_events, tolerance_minutes=60):
    """NFL entries freeze no event_id and carry no game_pk: join by the two full
    club names and first-pitch time against the NFL multibook events."""
    if entry.get("event_id"):
        return entry["event_id"]
    fp = _moment(entry.get("first_pitch_utc"))
    best = None
    for event_id, (home, away, ct) in nfl_events.items():
        if home != entry.get("home_team") or away != entry.get("away_team"):
            continue
        if fp is None or ct is None:
            continue
        gap = abs((ct - fp).total_seconds()) / 60.0
        if gap <= tolerance_minutes and (best is None or gap < best[0]):
            best = (gap, event_id)
    return best[1] if best else None


def attach_clv(entries, multibook_path, event_map_path):
    """Set entry['clv'] on every staked entry via card_clv.measure_pick."""
    from src.pipeline import snapshots
    from src.report import card_clv, clv
    staked = [e for e in entries if is_staked(e)]
    need_mlb = any(e["sport"] == "mlb" and e["kind"] != "prop" for e in staked)
    need_nfl = any(e["sport"] == "nfl" and e["kind"] != "prop" for e in staked)
    mlb_index, nfl_index, nfl_events = {}, {}, {}
    emap = collections.defaultdict(list)
    if need_mlb:
        rows = snapshots.read_multibook(path=multibook_path, since=CLV_SINCE)
        mlb_index = clv.pregame_index(rows)
        emap = _load_event_map(event_map_path)
    if need_nfl:
        rows = snapshots.read_multibook(path=multibook_path, sport="nfl", since=CLV_SINCE)
        nfl_index = clv.pregame_index(rows)
        for r in rows:
            ev = r.get("event_id")
            if ev and ev not in nfl_events:
                nfl_events[ev] = (r.get("home_team"), r.get("away_team"),
                                  _moment(r.get("commence_time")))
    for e in staked:
        pick = {"kind": "prop" if e["kind"] == "prop" else "game",
                "market": e["market_raw"], "price": e["price"], "side": e["side"],
                "line": e["line"], "observed_utc": e["observed_utc"],
                "market_probability": e["p_mkt"], "entry_class": e["entry_class"],
                "price_class": e.get("price_class")}
        if e["kind"] == "total":
            pick["market"] = "total"
        if e["sport"] == "nfl":
            pick["event_id"] = _resolve_nfl_event(e, nfl_events)
            e["clv"] = card_clv.measure_pick(pick, nfl_index)
        else:
            pick["event_id"] = _resolve_mlb_event(e, emap)
            e["clv"] = card_clv.measure_pick(pick, mlb_index)


# ---------------------------------------------------------------------------
# Whole scan.
# ---------------------------------------------------------------------------

def default_stores(evidence_dir=None):
    """[(rule_label, path, loader_name)] -- the project's own store constants."""
    cl = _cl()
    base = Path(evidence_dir) if evidence_dir else ROOT

    def path_of(const):
        return str(base / os.path.basename(const)) if evidence_dir else str(ROOT / const)
    return [
        ("V1 public", path_of(cl.CARD_STORE), "v1"),
        ("V1 shadow", path_of(cl.CARD_STORE_V1_SHADOW), "v1"),
        ("V2 public", path_of(cl.CARD_STORE_V2), "v2"),
        ("V2 shadow A", path_of(cl.CARD_STORE_V2_SHADOW_A), "v2"),
        ("V2 shadow C", path_of(cl.CARD_STORE_V2_SHADOW_C), "v2"),
        ("V2 shadow E", path_of(cl.CARD_STORE_V2_SHADOW_E), "v2"),
        ("NFL", path_of(cl.store_path("nfl")), "nfl"),
    ], path_of(cl.store_path("mma"))


def load_all(stores):
    """(entries, status) where status[label] = {"error": str|None, ...}."""
    entries, status, all_dates = [], {}, set()
    for label, path, loader in stores:
        try:
            if loader == "v1":
                es, info = load_v1_style(path, default_rule=label)
            elif loader == "nfl":
                es, info = load_v1_style(
                    path, rule_for_published=lambda r: NFL_RULE_LABELS.get(r, "NFL %s" % r))
            else:
                es, info = load_v2_style(path, label)
        except SealedWindowError:
            raise
        except Exception as exc:  # noqa: BLE001 -- an unreadable ledger is a row, not a crash
            status[label] = {"error": "unreadable: %s" % type(exc).__name__, "path": path}
            continue
        status[label] = {"error": None, "path": path, **info}
        all_dates |= info["dates"]
        entries.extend(es)
    check_sealed(all_dates)
    return entries, status


def read_ufc(path):
    """(published pick count, settled row count) of the UFC ledger, or an error string."""
    try:
        rows = _read_rows(path)
    except Exception as exc:  # noqa: BLE001
        return "unreadable: %s" % type(exc).__name__, None
    check_sealed(r.get("date") for r in rows)
    latest = {}
    settled = 0
    for r in rows:
        if r.get("kind") == "card_published":
            latest[r.get("date")] = r
        elif r.get("kind") == "card_settled":
            settled += 1
    picks = sum(len(r.get("picks") or ()) for r in latest.values())
    return picks, settled


def unit_mismatches(entries):
    """Staked entries whose recomputed flat-stake units differ from the ledger's
    own profit_units by more than rounding."""
    bad = 0
    for e in entries:
        if is_staked(e) and e.get("ledger_units") is not None:
            if abs(units(e["price"], e["result"]) - e["ledger_units"]) > 0.0006:
                bad += 1
    return bad


def run_scan(stores, ufc_path, *, as_of=None, multibook_path=None, event_map_path=None):
    entries, status = load_all(stores)
    if as_of:
        entries = [e for e in entries if e["date"] <= as_of]
    mark_postseason(entries)
    clv_error = None
    try:
        attach_clv(entries, multibook_path, event_map_path)
    except Exception as exc:  # noqa: BLE001 -- CLV unreadable: reported, not guessed
        clv_error = "unreadable: %s" % type(exc).__name__
        for e in entries:
            e["clv"] = {"absence": "CLV_STORE_" + clv_error.upper().replace(" ", "_").replace(":", "")}
    ufc = read_ufc(ufc_path)
    return {"entries": entries, "status": status, "ufc": ufc, "clv_error": clv_error,
            "as_of": as_of}


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------

def _f(x, fmt, none="-"):
    return none if x is None else format(x, fmt)


def _pm(a, b, fmt):
    if a is None:
        return "-"
    return format(a, fmt) + ("" if b is None else " +/- " + format(b, fmt.replace("+", "")))


def _our_cell(s):
    if s["n_our"] == 0:
        return "not recorded"
    cell = "%.3f" % s["mean_our"]
    if s["n_our"] < s["n_staked"]:
        cell += " (%d/%d)" % (s["n_our"], s["n_staked"])
    return cell


def _mkt_cell(s):
    if s["n_mkt"] == 0:
        return "not recorded"
    cell = "%.3f" % s["mean_mkt"]
    if s["n_mkt"] < s["n_staked"]:
        cell += " (%d/%d)" % (s["n_mkt"], s["n_staked"])
    return cell


def _refused_cell(clv):
    if not clv["refused"]:
        return "-"
    return ", ".join("%s x%d" % (k, v) for k, v in clv["refused"].items())


def build_rows(entries):
    groups = group_populations(entries)
    rows = []
    for key in sorted(groups, key=_sort_key):
        s = summarize(groups[key])
        s["key"] = key
        rows.append(s)
    return rows


def render(scan, now=None):
    entries = scan["entries"]
    status = scan["status"]
    rows = build_rows(entries)
    main_rows = [r for r in rows if r["n_staked"] > 0]
    idle_rows = [r for r in rows if r["n_staked"] == 0]
    for i, r in enumerate(main_rows, 1):
        r["id"] = "R%02d" % i
    dates = sorted({e["date"] for e in entries})
    out = []
    w = out.append

    w("# Value scan")
    w("")
    w("Generated: %s" % (now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    w("")
    w("Settled entries from %s to %s (%s)." % (
        dates[0] if dates else "-", dates[-1] if dates else "-",
        ("as of " + scan["as_of"]) if scan["as_of"] else "all settled dates"))
    w("Regenerate with `python scripts/value_scan.py`. Read-only on every ledger; the "
      "script changes no rule, gate, threshold or published record.")
    w("")
    w("## How to read this")
    w("")
    counts = collections.Counter(r["verdict"] for r in main_rows)
    w("**Verdict rule (fixed, identical for every row).** `TOO FEW` when n staked < 30. "
      "`CANDIDATE` only when n staked >= 100 AND mean closing-line value > 0 AND the lower end of "
      "its 95% interval (mean - 1.96 se) > 0 AND z vs the market > 2. Everything else is "
      "`NO EVIDENCE`. A row whose closing-line value cannot be measured (every prop) can never "
      "reach `CANDIDATE`.")
    w("")
    w("**Multiplicity.** This table has %d rows, each a different population. With about that many "
      "looks, one or two will look good by chance alone, and a z above 2 in one row is what "
      "chance produces. No row here is a reason to change a rule. Changing a rule needs a "
      "pre-registered test on forward data (`docs/PREREG_CARD_V2.md`). A `CANDIDATE` would only be "
      "a hypothesis to pre-register." % len(main_rows))
    w("")
    w("**Verdicts this run:** %s." % (", ".join("%s: %d" % (k, counts.get(k, 0)) for k in
                                                 (VERDICT_TOO_FEW, VERDICT_NO_EVIDENCE, VERDICT_CANDIDATE))))
    w("")
    w("Units are flat 1u per entry at the frozen price (pushes, voids, unresolved and withdrawn "
      "entries are never staked). ROI = units / n staked. Rows are never pooled across rule, "
      "market, entry class or season scope; postseason entries (the project's calendar rule, "
      "`effective_record._ledger_postseason_pks`) are their own rows, and fills never enter a "
      "pick row. z = (actual wins - market-expected wins) / sqrt(sum p(1-p)) using the de-vigged "
      "market probability frozen on each entry. Pu/Vo/Un = pushes / voids / unresolved (never staked). Where a column carries `(k/n)`, only k of the n "
      "staked entries record that number.")
    w("")

    w("## Ledgers read")
    w("")
    w("| Ledger | Status | Rows | Settled dates | First | Last | Corrections folded |")
    w("|---|---|---|---|---|---|---|")
    for label in ("V1 public", "V1 shadow", "V2 public", "V2 shadow A", "V2 shadow C",
                  "V2 shadow E", "NFL"):
        st = status.get(label)
        if st is None:
            continue
        if st["error"]:
            w("| %s | %s | - | - | - | - | - |" % (label, st["error"]))
        else:
            sd = st["settled_dates"]
            w("| %s | read | %d | %d | %s | %s | %d |" % (
                label, st["rows"], len(sd), sd[0] if sd else "-", sd[-1] if sd else "-",
                st["corrections"]))
    w("")
    w("Our-probability field read per rule: " + "; ".join(
        "%s = %s" % (k, v) for k, v in OUR_PROBABILITY_FIELDS.items()) + ".")
    w("")
    mism = unit_mismatches(entries)
    w("Integrity check: %d staked entries whose flat-stake units recomputed from price and result "
      "differ from the ledger's own profit_units by more than rounding." % mism)
    if scan.get("clv_error"):
        w("")
        w("Closing-line value: %s. Every CLV cell below is therefore a refusal, not a measurement."
          % scan["clv_error"])
    w("")

    w("## Population table (record against the market)")
    w("")
    w("| Row | Rule | Market | Class | Scope | n staked | W-L | Pu/Vo/Un | Units | ROI | "
      "Mean break-even | Mean market p | Mean our p | Exp. units if market right | z vs market | Verdict |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    unreadable = [(l, s["error"]) for l, s in status.items() if s["error"]]
    for r in main_rows:
        rule, market, cls, scope = r["key"]
        star = "*" if r["n_exp"] < r["n_staked"] else ""
        w("| %s | %s | %s | %s | %s | %d | %d-%d | %d/%d/%d | %s | %s | %s | %s | %s | %s%s | %s | %s |" % (
            r["id"], rule, market, cls, scope, r["n_staked"], r["wins"], r["losses"],
            r["pushes"], r["voids"], r["unresolved"],
            _f(r["units"], "+.2f"), _f(None if r["roi"] is None else 100 * r["roi"], "+.1f", "-") +
            ("%" if r["roi"] is not None else ""),
            _f(r["mean_be"], ".3f"), _mkt_cell(r), _our_cell(r),
            _f(r["exp_units"], "+.2f"), star, _f(r["z"], "+.2f"), r["verdict"]))
    for label, err in sorted(unreadable):
        w("| - | %s | - | - | - | - | - | - | - | - | - | - | - | - | - | %s |" % (label, err))
    w("")
    w("`*` expected units and z use only the staked entries that carry a market probability.")
    w("")

    w("## Population table (calibration and closing line)")
    w("")
    w("Brier score: ours and the market's on the same staked entries that carry both; "
      "difference = ours minus market (positive = ours worse), with the paired per-entry standard "
      "error. Closing-line value is `card_clv.measure_pick` unchanged: de-vigged close minus the "
      "break-even of the frozen price, in probability points; it refuses props always, and "
      "refuses a stale, thin or decision-board close, which is shown as a refusal.")
    w("")
    w("| Row | n w/ market p | Brier n | Brier ours | Brier market | Diff +/- se | CLV n | "
      "Mean CLV (pts) +/- se | CLV 95% low | Beat close | CLV refused (reason x n) |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in main_rows:
        b, c = r["brier"], r["clv"]
        if r["n_our"] == 0:
            brier_part = " | ".join(["not recorded"] * 4)
        elif b is None:
            brier_part = "0 | - | - | -"
        else:
            brier_part = " | ".join([str(b["n"]), "%.4f" % b["ours"], "%.4f" % b["market"],
                                     _pm(b["diff"], b["se"], "+.4f")])
        w("| %s | %d | %s | %s | %s | %s | %s | %s |" % (
            r["id"], r["n_mkt"], brier_part, c["n"],
            _pm(c["mean"], c["se"], "+.2f"), _f(c["lo"], "+.2f"),
            _f(None if c["beat"] is None else 100 * c["beat"], ".0f", "-") +
            ("%" if c["beat"] is not None else ""), _refused_cell(c)))
    w("")

    w("## Entries never staked")
    w("")
    w("Withdrawn entries and populations with no WIN or LOSS. Counted, never staked. "
      "The results shown for withdrawn entries are what they would have been; no unit is "
      "attributed to them.")
    w("")
    w("| Rule | Market | Class | Scope | Entries | Void | Push | Unresolved | Withdrawn (result if shown) |")
    w("|---|---|---|---|---|---|---|---|---|")
    any_idle = False
    for r in idle_rows:
        any_idle = True
        rule, market, cls, scope = r["key"]
        wt = ", ".join("%s x%d" % (k, v) for k, v in r["withdrawn_tally"].items()) or "-"
        w("| %s | %s | %s | %s | %d | %d | %d | %d | %s |" % (
            rule, market, cls, scope, r["n_entries"], r["voids"], r["pushes"], r["unresolved"], wt))
    if not any_idle:
        w("| (none) | | | | | | | | |")
    w("")

    out.extend(_value_gate_section(entries))
    out.extend(_cannot_measure_section(scan))
    return "\n".join(out) + "\n"


def _gate_lines(label, es):
    res = value_gate_comparison(es)
    lines = []
    p, f = res["passed"], res["failed"]
    lines.append("| %s | passed value test | %d | %d-%d | %s | %s | %s |" % (
        label, p["n"], p["wins"], p["losses"], _f(p["units"], "+.2f"),
        _f(None if p["roi"] is None else 100 * p["roi"], "+.1f") + ("%" if p["roi"] is not None else ""),
        _f(p["win_minus_mkt"], "+.3f")))
    lines.append("| %s | failed value test | %d | %d-%d | %s | %s | %s |" % (
        label, f["n"], f["wins"], f["losses"], _f(f["units"], "+.2f"),
        _f(None if f["roi"] is None else 100 * f["roi"], "+.1f") + ("%" if f["roi"] is not None else ""),
        _f(f["win_minus_mkt"], "+.3f")))
    lines.append("| %s | difference (passed - failed) | | | | | %s +/- %s, z %s |" % (
        label, _f(res["diff"], "+.3f"), _f(res["se"], ".3f"), _f(res["z"], "+.2f")))
    return lines


def _value_gate_section(entries):
    out = ["## V2 value gate", "",
           "Descriptive only. The value test is `our_probability_used >= value_need`, both frozen on "
           "the entry (G7). Within each rule, staked entries are split by whether they passed it and "
           "compared on win minus market probability (1 for a win, 0 for a loss, minus the frozen "
           "de-vigged market probability). Difference = passed minus failed; the standard error is "
           "Welch's. A negative difference means entries that passed did worse against the market "
           "than entries that failed. This is a question for a pre-registered forward test, not a "
           "reason to move the gate.", "",
           "| Population | Group | n | W-L | Units | ROI | Win - market p |",
           "|---|---|---|---|---|---|---|"]
    for rule in ("V2 shadow A", "V2 public"):
        base = [e for e in entries if e["rule"] == rule and e["entry_class"] != "withdrawn"]
        out.extend(_gate_lines(rule + ", regular season", [e for e in base if not e["postseason"]]))
        out.extend(_gate_lines(rule + ", regular + postseason", base))
        if rule == "V2 shadow A":
            # Picks only: the population the 2026-10-01 audit used (it left out
            # shadow A's one fill), so the two can be compared.
            out.extend(_gate_lines(rule + ", picks only, regular + postseason",
                                   [e for e in base if e["entry_class"] == "pick"]))
    # Disagreement with the frozen G7_VALUE flag, where the store freezes one.
    flagged = [e for e in entries if e["rule"] in ("V2 public", "V2 shadow C", "V2 shadow E")
               and e.get("failed_gates") is not None and passes_value_test(e) is not None]
    bad = sum(1 for e in flagged if passes_value_test(e) == ("G7_VALUE" in e["failed_gates"]))
    out += ["", "Check: on the stores that freeze a G7_VALUE flag (V2 public, shadows C and E), the "
            "two-number comparison disagrees with the frozen flag on %d of %d entries. Shadow A "
            "freezes no failed_gates (it is the band-only superset), so the comparison of the two "
            "frozen numbers is its only mark." % (bad, len(flagged)), ""]
    return out


def _cannot_measure_section(scan):
    entries = scan["entries"]
    out = ["## What cannot be measured and why", "",
           "Current counts from the ledgers, so it is visible when one becomes measurable.", ""]
    nfl = [e for e in entries if e["rule"].startswith("NFL")]
    nfl_staked = [e for e in nfl if is_staked(e)]
    out.append("- **NFL model probability not frozen.** %d of %d NFL entries carry our probability "
               "(staked: %d of %d). Our NFL calibration cannot be tested until this is nonzero."
               % (sum(1 for e in nfl if e["p_our"] is not None), len(nfl),
                  sum(1 for e in nfl_staked if e["p_our"] is not None), len(nfl_staked)))
    out.append("- **NFL observed time not frozen.** %d of %d NFL entries carry observed_utc "
               "(staked: %d of %d). Without it the closing-line comparison cannot rule out a "
               "decision board that is the closing board."
               % (sum(1 for e in nfl if e["observed_utc"]), len(nfl),
                  sum(1 for e in nfl_staked if e["observed_utc"]), len(nfl_staked)))
    ufc = scan["ufc"]
    if isinstance(ufc[0], str):
        out.append("- **UFC ungraded.** UFC ledger %s." % ufc[0])
    else:
        out.append("- **UFC ungraded.** %d picks published, %d settled rows. There is no UFC result "
                   "to measure." % (ufc[0], ufc[1]))
    props = [e for e in entries if e["kind"] == "prop" and is_staked(e)]
    prop_ok = sum(1 for e in props if e.get("clv") and "clv_bps" in e["clv"])
    by_mkt = collections.Counter(e["market"] for e in props)
    out.append("- **Prop closes absent.** %d staked prop entries, %d measurable against a close "
               "(card_clv refuses every prop: PROP_NOT_MEASURED). By market: %s."
               % (len(props), prop_ok, ", ".join("%s %d" % (k, v) for k, v in sorted(by_mkt.items())) or "none"))
    games = [e for e in entries if e["kind"] != "prop" and is_staked(e)]
    ok = sum(1 for e in games if e.get("clv") and "clv_bps" in e["clv"])
    refused = collections.Counter(
        (e["clv"].get("absence") if e.get("clv") else "NOT_ATTEMPTED")
        for e in games if not (e.get("clv") and "clv_bps" in e["clv"]))
    out.append("- **Game closes refused.** %d staked game entries, %d measured, refused: %s."
               % (len(games), ok, ", ".join("%s x%d" % (k, v) for k, v in sorted(refused.items())) or "none"))
    out.append("")
    out.append("Per rule: staked entries recording no probability of ours, no market probability, "
               "and VOID or UNRESOLVED entries (never staked).")
    out.append("")
    out.append("| Rule | Staked | No our p | No market p | VOID | UNRESOLVED | Withdrawn |")
    out.append("|---|---|---|---|---|---|---|")
    for rule in RULE_ORDER:
        es = [e for e in entries if e["rule"] == rule]
        if not es:
            continue
        st = [e for e in es if is_staked(e)]
        out.append("| %s | %d | %d | %d | %d | %d | %d |" % (
            rule, len(st), sum(1 for e in st if e["p_our"] is None),
            sum(1 for e in st if e["p_mkt"] is None),
            sum(1 for e in es if e["entry_class"] != "withdrawn" and e["result"] == VOID),
            sum(1 for e in es if e["entry_class"] != "withdrawn" and e["result"] == UNRESOLVED),
            sum(1 for e in es if e["entry_class"] == "withdrawn")))
    voids = collections.Counter(
        (e["rule"], e["market_raw"], (e.get("reason") or "(no reason recorded)")[:70])
        for e in entries if e["result"] == VOID and e["entry_class"] != "withdrawn")
    out.append("")
    out.append("VOID entries by reason (never staked):")
    out.append("")
    if voids:
        out.append("| Rule | Market | Reason | n |")
        out.append("|---|---|---|---|")
        for (rule, mk, reason), n in sorted(voids.items(), key=lambda kv: (str(kv[0]), kv[1])):
            out.append("| %s | %s | %s | %d |" % (rule, mk, reason.replace("|", "/"), n))
    else:
        out.append("None.")
    out.append("")
    return out


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Standing value scan (read-only).")
    ap.add_argument("--stdout", action="store_true",
                    help="print the report instead of writing docs/VALUE_SCAN.md")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD", default=None,
                    help="ignore entries dated after this day")
    ap.add_argument("--out", default=None, help="output path (default docs/VALUE_SCAN.md)")
    ap.add_argument("--evidence-dir", default=None,
                    help="read the card ledgers from this directory (default: the repository's)")
    ap.add_argument("--multibook", default=None, help="odds_multibook.jsonl path override")
    ap.add_argument("--event-map", default=None, help="event_game_map.jsonl path override")
    args = ap.parse_args(argv)

    stores, ufc_path = default_stores(args.evidence_dir)
    multibook = args.multibook or str(ROOT / "data" / "processed" / "odds_multibook.jsonl")
    event_map = args.event_map or str(ROOT / "data" / "processed" / "event_game_map.jsonl")
    try:
        scan = run_scan(stores, ufc_path, as_of=args.as_of,
                        multibook_path=multibook, event_map_path=event_map)
    except SealedWindowError as exc:
        sys.stderr.write("value_scan: refusing to continue: %s\n" % exc)
        return 2
    text = render(scan)
    if args.stdout:
        sys.stdout.write(text)
        return 0
    out = Path(args.out) if args.out else ROOT / "docs" / "VALUE_SCAN.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    sys.stdout.write("wrote %s\n" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
