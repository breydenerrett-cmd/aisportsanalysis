"""Canonical performance matrix: "where are we actually good?" as one table.

    python scripts/performance_matrix.py [--stdout] [--as-of YYYY-MM-DD]

READ-ONLY on every ledger and data store. It MEASURES; it changes no rule, no
gate, no threshold and no published record. It writes exactly one file,
`docs/PERFORMANCE_MATRIX.md` (or prints it with --stdout).

WHAT IT IS
----------
One row per (SPORT, MARKET, RULE, MODEL, VISIBILITY), VISIBILITY being
public / shadow / paper. Entry class (pick / fill) and season scope (regular /
postseason) are part of the row key too, so nothing is ever pooled across
them. Every required market family has a row, or a `MISSING` row that names
why (fixed vocabulary, `MISSING_REASONS`).

REUSE, NOT A FORK
-----------------
All arithmetic (units, ROI, z against the de-vigged market probability, the
closing-line summary, the Brier pair, the verdict) is `scripts/value_scan.py`'s,
imported and called. Closing-line value is the project's own: `card_clv.
measure_pick` for card, shadow and UFC rows, `clv.measure_decision` for paper
rows (with a stale close refused exactly as `card_clv` refuses it, so the two
are comparable). Nothing here recomputes a statistic those functions own.

THE VERDICT RULE (fixed, applied identically to every row; stated once in the
document): n staked < 30 -> TOO FEW; n >= 100 AND mean CLV > 0 AND lower end of
the 95% interval of mean CLV > 0 AND z vs market > 2 -> CANDIDATE; otherwise NO
EVIDENCE. Baseline rows (CONTROL, MARKET_REFERENCE) get the same rule and a
visible BASELINE label.

SEALED WINDOW
-------------
Nothing dated 2026-01-01..2026-08-27 is read. The matrix reads only 2026-09-10
onward (the first card-ledger date). Paper stores are filtered by their date
field on the RAW LINE before a row is parsed; a paper account or wager row
dated inside the sealed window raises SealedWindowError (exit 2, nothing
written). Decision rows dated inside it are skipped unparsed. The results store
(`data/historical/mlb_results.csv`) is never opened.

AMBIGUOUS JOINS STOP THE RUN
----------------------------
A settled paper bet joins to its wager by (system_id, bet_id) and to its
decision by the five-field key (event_id, system_id, market_key, selection_id,
decision_utc). A shadow decision joins to its settlement by row hash. If any of
those keys is not unique the script raises AmbiguousJoinError (exit 3, nothing
written) and says which key; it never picks one.

Deterministic: the same inputs give the same bytes, except the one "Generated"
line. Python standard library only.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import value_scan as vs  # noqa: E402  (path set up above)

WINDOW_START = "2026-09-10"            # first card-ledger date; nothing earlier is read

VIS_PUBLIC, VIS_SHADOW, VIS_PAPER = "public", "shadow", "paper"
VIS_ORDER = (VIS_PUBLIC, VIS_SHADOW, VIS_PAPER)

WIN, LOSS, PUSH, VOID, UNRESOLVED = vs.WIN, vs.LOSS, vs.PUSH, vs.VOID, vs.UNRESOLVED

# --- MISSING vocabulary (fixed) ----------------------------------------------
NEVER_PUBLISHED = "NEVER_PUBLISHED"
PUBLISHED_UNGRADED = "PUBLISHED_UNGRADED"
PUBLISHED_NOT_STAKED = "PUBLISHED_NOT_STAKED"
NO_CLOSING_LINE_CAPTURED = "NO_CLOSING_LINE_CAPTURED"
NO_PROBABILITY_FROZEN = "NO_PROBABILITY_FROZEN"
MISSING_REASONS = {
    NEVER_PUBLISHED: "no entry for this market exists in any ledger of this visibility",
    PUBLISHED_UNGRADED: "entries exist but none graded WIN or LOSS (void, push, unresolved or withdrawn only)",
    PUBLISHED_NOT_STAKED: "shown as analysis flags with no stake, price rule or grade",
    NO_CLOSING_LINE_CAPTURED: "graded entries exist but no closing line was captured for them",
    NO_PROBABILITY_FROZEN: "graded entries exist but no per-entry probability is frozen on them",
}

BASELINE_CONTROL = "BASELINE: CONTROL"
BASELINE_MARKET_REFERENCE = "BASELINE: MARKET REFERENCE"
FORWARD_TEST_LABEL = "FORWARD_TEST"

# Required families: (name, sport, market label). The market label is the one
# `market_for` produces.
FAMILIES = (
    ("MLB moneyline", "mlb", "moneyline"),
    ("MLB run line", "mlb", "run line"),
    ("MLB totals", "mlb", "totals"),
    ("MLB first-five (F5)", "mlb", "F5 moneyline"),
    ("MLB pitcher props", "mlb", "pitcher props"),
    ("MLB hitter props: hits", "mlb", "hits prop"),
    ("MLB hitter props: total bases", "mlb", "total-bases prop"),
    ("MLB hitter props: runs scored", "mlb", "runs-scored prop"),
    ("NFL sides", "nfl", "moneyline"),
    ("NFL totals", "nfl", "totals"),
    ("NFL player props", "nfl", "player props"),
    ("UFC sides", "mma", "moneyline"),
)
EXTRA_FAMILIES = (
    ("MLB in-play moneyline (not a required family)", "mlb", "in-play moneyline"),
)
FAMILY_OF = {(sport, market): name for name, sport, market in FAMILIES + EXTRA_FAMILIES}

CARD_VISIBILITY = {
    "V1 public": VIS_PUBLIC, "V2 public": VIS_PUBLIC, "NFL V1": VIS_PUBLIC,
    "NFL V2": VIS_PUBLIC, "UFC V1": VIS_PUBLIC,
    "V1 shadow": VIS_SHADOW, "V2 shadow A": VIS_SHADOW, "V2 shadow C": VIS_SHADOW,
    "V2 shadow E": VIS_SHADOW,
}
STORE_VISIBILITY = dict(CARD_VISIBILITY, NFL=VIS_PUBLIC, UFC=VIS_PUBLIC)
CARD_RULE_ORDER = ("V1 public", "V2 public", "NFL V1", "NFL V2", "UFC V1",
                   "V1 shadow", "V2 shadow A", "V2 shadow C", "V2 shadow E")
CARD_MODEL = {
    "V1 public": "V1 model",
    "V1 shadow": "V1 model",
    "V2 public": "our_probability_used (0.038 markdown)",
    "V2 shadow A": "our_probability_used (0.038 markdown)",
    "V2 shadow C": "our_probability_used (0.038 markdown)",
    "V2 shadow E": "our_probability_used (0.038 markdown)",
    "NFL V1": "none frozen (market p only)",
    "NFL V2": "none frozen (market p only)",
    "UFC V1": "none frozen (market p only; price = average of books)",
}
PAPER_RULE = "paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1"
MVS_RULE = "MLB_VALUE_SHADOW_V1"
MVS_MODEL = "none frozen (other-books consensus is the market p)"
LIVE_MODEL = "none frozen"

PRE_COMMENCEMENT = "live_pre_commencement"


class AmbiguousJoinError(RuntimeError):
    """A join key that must be unique matched more than one row."""


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def market_for(sport, kind, raw):
    """The matrix's market label for a raw market string."""
    raw = raw or ""
    if kind == "total" or raw in ("total", "totals"):
        return "totals"
    if raw in ("moneyline", "h2h"):
        return "moneyline"
    if raw in ("run_line", "spreads"):
        return "run line"
    if raw in ("h2h_1st_5_innings", "first_five"):
        return "F5 moneyline"
    if raw == "batter_hits":
        return "hits prop"
    if raw == "batter_total_bases":
        return "total-bases prop"
    if raw == "batter_runs_scored":
        return "runs-scored prop"
    if raw.startswith("pitcher_"):
        return "pitcher props"
    if kind == "prop":
        return "player props" if sport != "mlb" else "other prop"
    return raw or "other"


def family_for(sport, market):
    return FAMILY_OF.get((sport, market))


def new_entry(**kw):
    """The canonical entry shape (the one `vs.summarize` reads)."""
    base = {
        "rule": None, "date": None, "kind": "game", "market_raw": None, "market": None,
        "entry_class": "pick", "price": None, "result": None, "ledger_units": None,
        "side": None, "line": None, "p_our": None, "p_mkt": None,
        "observed_utc": None, "first_pitch_utc": None, "game_pk": None, "game_id": None,
        "game_type": None, "event_id": None, "home_team": None, "away_team": None,
        "player": None, "sport": "mlb", "reason": None, "value_need": None,
        "failed_gates": None, "price_class": None, "postseason": False,
        "vis": None, "model": None, "baseline": None, "family": None,
        "clv_basis": "card", "sort_hint": "",
    }
    base.update(kw)
    return base


def label_entries(entries):
    """Fill the matrix's extra keys, then set `market` and `family` on every
    entry from its raw market."""
    defaults = new_entry()
    for e in entries:
        for k, v in defaults.items():
            e.setdefault(k, v)
    for e in entries:
        e["market"] = market_for(e["sport"], e["kind"], e["market_raw"])
        e["family"] = family_for(e["sport"], e["market"])


# ---------------------------------------------------------------------------
# Dated line reader: the sealed window is decided on the raw line
# ---------------------------------------------------------------------------

def read_dated(path, field, since=WINDOW_START):
    """(rows, tally) for a JSONL store, archive aware.

    A line is classified by the date text of `field` BEFORE it is parsed. Lines
    dated before `since` are counted and never parsed. Lines dated inside the
    sealed window are never parsed either; their dates land in
    tally['sealed_dates'] so the caller can refuse or skip."""
    from src.pipeline import store_archive
    pat = re.compile(r'"%s"\s*:\s*"(\d{4}-\d{2}-\d{2})' % re.escape(field))
    tally = {"lines": 0, "in_window": 0, "pre_window": 0, "undated": 0,
             "unparseable": 0, "sealed_dates": [],
             "pre_window_by_month": collections.Counter()}
    rows = []
    if not store_archive.exists(path):
        return rows, tally
    for line in store_archive.iter_lines(path):
        if not line.strip():
            continue
        tally["lines"] += 1
        m = pat.search(line)
        if not m:
            tally["undated"] += 1
            continue
        d = m.group(1)
        if vs.SEALED_START <= d <= vs.SEALED_END:
            tally["sealed_dates"].append(d)
            continue
        if d < since:
            tally["pre_window"] += 1
            tally["pre_window_by_month"][d[:7]] += 1
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            tally["unparseable"] += 1
            continue
        tally["in_window"] += 1
    return rows, tally


def _refuse_sealed(tally, label):
    if tally["sealed_dates"]:
        raise vs.SealedWindowError(
            "%s holds rows dated inside the sealed window %s..%s: %s"
            % (label, vs.SEALED_START, vs.SEALED_END,
               ", ".join(sorted(set(tally["sealed_dates"]))[:10])))


# ---------------------------------------------------------------------------
# Cards: V1, V2, shadows, NFL, UFC
# ---------------------------------------------------------------------------

def scan_published(path):
    """What a card store's PUBLISHED rows carried (counts only, no results)."""
    out = {"rows": 0, "markets": collections.Counter(), "rows_with_total_picks": 0,
           "rows_with_prop_picks": 0, "totals_paused_true": 0}
    try:
        rows = vs._read_rows(path)
    except Exception:  # noqa: BLE001 -- an unreadable store is reported by load_all
        return out
    vs.check_sealed(r.get("date") for r in rows)
    for r in rows:
        if r.get("kind") != "card_published":
            continue
        out["rows"] += 1
        if r.get("total_picks"):
            out["rows_with_total_picks"] += 1
        if r.get("prop_picks"):
            out["rows_with_prop_picks"] += 1
        if r.get("totals_paused") is True:
            out["totals_paused_true"] += 1
        for scope in ("picks", "prop_picks", "total_picks", "fills", "withdrawn"):
            for g in r.get(scope) or ():
                if isinstance(g, dict):
                    kind = "total" if scope == "total_picks" else (
                        "prop" if scope == "prop_picks" or g.get("kind") == "prop" else "game")
                    sport = g.get("sport") or "mlb"
                    out["markets"][(sport, market_for(sport, kind, g.get("market")))] += 1
    return out


def load_cards(evidence_dir):
    """(entries, status, published) for every card store, UFC included."""
    stores, ufc_path = vs.default_stores(evidence_dir)
    entries, status = vs.load_all(stores)
    for e in entries:
        e["vis"] = CARD_VISIBILITY.get(e["rule"], VIS_SHADOW)
        e["model"] = CARD_MODEL.get(e["rule"], "unknown")
        if e["rule"] in ("V1 public", "V1 shadow"):
            e["model"] += (" (probability)" if e["kind"] == "prop" else " (model_probability)")
        e["clv_basis"] = "card"
    published = {}
    for label, path, _loader in stores:
        published[label] = scan_published(path)
    # UFC: V1-style store; vs.read_ufc only counts it, here its settled picks are read.
    try:
        ufc_entries, info = vs.load_v1_style(ufc_path, default_rule="UFC V1")
        vs.check_sealed(info["dates"])
        status["UFC"] = {"error": None, "path": ufc_path, **info}
        for e in ufc_entries:
            e["vis"] = VIS_PUBLIC
            e["model"] = CARD_MODEL["UFC V1"]
            e["clv_basis"] = "card (consensus price)"
            e["event_id"] = e.get("event_id") or e.get("game_id")
        entries.extend(ufc_entries)
        published["UFC"] = scan_published(ufc_path)
    except vs.SealedWindowError:
        raise
    except Exception as exc:  # noqa: BLE001
        status["UFC"] = {"error": "unreadable: %s" % type(exc).__name__, "path": ufc_path}
    return entries, status, published


# ---------------------------------------------------------------------------
# Shadow stores outside the cards: MLB value shadow, in-play candidates
# ---------------------------------------------------------------------------

def _read_plain(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def load_mvs(mvs_dir):
    """MLB value shadow v1 decisions joined to their settlements by row hash.

    Returns (entries, info). `fair_probability` is the other-books de-vigged
    consensus; it is the MARKET probability here (p_mkt), never our model's."""
    entries, info = [], {"arms": {}, "scan_only": {}}
    d = Path(mvs_dir)
    if not d.is_dir():
        return entries, info
    arms = sorted({p.name[:-len("_decisions.jsonl")] for p in d.glob("*_decisions.jsonl")})
    for p in sorted(d.glob("*_scans.jsonl")):
        arm = p.name[:-len("_scans.jsonl")]
        if arm not in arms:
            info["scan_only"][arm] = len(_read_plain(p))
    for arm in arms:
        decisions = [r for r in _read_plain(d / (arm + "_decisions.jsonl"))
                     if r.get("kind") == "decision"]
        settled = [r for r in _read_plain(d / (arm + "_settled.jsonl"))
                   if r.get("kind") == "settled"]
        vs.check_sealed(r.get("date") for r in decisions + settled)
        by_hash = collections.defaultdict(list)
        for s in settled:
            by_hash[s.get("decision_row_hash")].append(s)
        dec_hash = collections.Counter(r.get("row_hash") for r in decisions)
        dup = [h for h, n in dec_hash.items() if n > 1]
        if dup:
            raise AmbiguousJoinError(
                "MLB value shadow %s: decision row_hash not unique (%s)" % (arm, dup[0]))
        dup = [h for h, v in by_hash.items() if len(v) > 1]
        if dup:
            raise AmbiguousJoinError(
                "MLB value shadow %s: more than one settlement for decision %s" % (arm, dup[0]))
        n_settled = 0
        for r in decisions:
            if r.get("date") is None or r["date"] < WINDOW_START:
                continue
            s = (by_hash.get(r.get("row_hash")) or [None])[0]
            if s is None:
                continue
            n_settled += 1
            raw = r.get("market")
            raw = "run_line" if raw == "spreads" else raw
            entries.append(new_entry(
                rule="%s %s" % (MVS_RULE, arm), date=r["date"],
                kind="prop" if str(raw).startswith("batter_") else "game",
                market_raw=raw, price=r.get("price"), result=s.get("result"),
                ledger_units=s.get("profit_units"), side=r.get("side"),
                line=r.get("line"), p_mkt=r.get("fair_probability"),
                observed_utc=r.get("quote_observed_utc"),
                first_pitch_utc=r.get("first_pitch_utc"), game_pk=r.get("game_pk"),
                game_id=r.get("game_pk"), event_id=r.get("event_id"),
                home_team=r.get("home_team"), away_team=r.get("away_team"),
                player=r.get("player"), sport="mlb", reason=s.get("reason"),
                vis=VIS_SHADOW, model=MVS_MODEL, sort_hint=arm))
        info["arms"][arm] = {"decisions": len(decisions), "settled": n_settled}
    return entries, info


def load_live(path):
    """In-play candidates, from their settlement rows alone (price, side,
    result and profit are on the settlement row; no join is needed)."""
    entries = []
    rows = [r for r in _read_plain(path) if r.get("kind") == "live_settled"]
    vs.check_sealed(r.get("date") for r in rows)
    for r in rows:
        if r.get("date") is None or r["date"] < WINDOW_START:
            continue
        entries.append(new_entry(
            rule="live %s" % r.get("rule_id"), date=r["date"], kind="game",
            market_raw="moneyline_inplay", price=r.get("price"), result=r.get("result"),
            ledger_units=r.get("profit_units"), side=r.get("side"),
            game_id=r.get("game_id"), sport=r.get("sport") or "mlb",
            vis=VIS_SHADOW, model=LIVE_MODEL, entry_class="candidate",
            clv_basis="none"))
    for e in entries:
        e["market_label_override"] = "in-play moneyline"
    return entries


def read_f5_flags(path):
    """Count of F5 'flagged' recommendations on the Analyzer forward ledger.
    No stake, no price rule, no grade: counted, never staked."""
    out = {"flagged": 0, "flagged_in_window": 0, "first": None, "last": None}
    if not Path(path).exists():
        return out
    rows = [r for r in vs._read_rows(path)
            if r.get("kind") == "recommendation" and r.get("market") == "first_five"
            and r.get("verdict") == "flagged"]
    vs.check_sealed(r.get("date") for r in rows)
    dates = sorted(r["date"] for r in rows if r.get("date"))
    out["flagged"] = len(rows)
    out["flagged_in_window"] = sum(1 for d in dates if d >= WINDOW_START)
    out["first"], out["last"] = (dates[0], dates[-1]) if dates else (None, None)
    return out


# ---------------------------------------------------------------------------
# Paper engine
# ---------------------------------------------------------------------------

PAPER_OUTCOMES = {"win": WIN, "loss": LOSS, "push": PUSH, "void": VOID}
_SPORT_TAG = re.compile(r"price-store sport tag: ([a-z]+)")
_DECISION_KEYS = ("event_id", "system_id", "market_key", "selection_id", "decision_utc",
                  "line", "price_american", "consensus_fair", "p_model",
                  "p_model_provenance", "record_provenance", "verdict",
                  "books_at_decision", "friction", "book")


def _system_class(system_id):
    from src.report import engine_bridge
    return engine_bridge.system_class(system_id)


def _baseline_label(cls):
    return {"CONTROL": BASELINE_CONTROL,
            "MARKET_REFERENCE": BASELINE_MARKET_REFERENCE}.get(cls)


def load_paper(accounts_dir, wagers_path, decisions_path):
    """(entries, inventory) for the paper engine.

    Settlement store: `<accounts_dir>/<system_id>.jsonl`, one hash-chained
    ledger per system, written by `src.engine.settle_slate.run_settle`. Each
    settled bet joins to its wager by (system_id, bet_id) and to its frozen
    decision by the five-field key. Only decisions stamped
    `live_pre_commencement` are kept (doctrine section 6: no replays, no
    unstamped rows); the rest are counted by name, never silently dropped."""
    inv = {
        "accounts": {}, "wagers": {}, "decisions": {},
        "excluded_pre_window_rows": 0, "excluded_pre_window_by_month": collections.Counter(),
        "excluded_provenance": collections.Counter(),
        "unjoined": 0, "unknown_outcome": 0, "price_mismatch": 0,
        "settled_in_window": 0, "kept": 0,
        "unsettled_by_date": collections.Counter(), "unsettled_samples": {},
        "wagers_by_date": collections.Counter(),
        "decision_table": collections.Counter(), "seen_markets": set(),
        "void_non_mlb": collections.Counter(),
        "forward_systems": set(), "forward_systems_with_p_model": 0,
    }
    acct_rows = []
    adir = Path(accounts_dir)
    files = sorted(adir.glob("*.jsonl")) if adir.is_dir() else []
    for f in files:
        rows, tally = read_dated(f, "day")
        _refuse_sealed(tally, "paper account %s" % f.name)
        inv["accounts"][f.stem] = tally
        inv["excluded_pre_window_rows"] += tally["pre_window"]
        inv["excluded_pre_window_by_month"].update(tally["pre_window_by_month"])
        for r in rows:
            if r.get("kind") == "genesis" or "bet_id" not in r:
                continue
            r.setdefault("system_id", f.stem)
            acct_rows.append(r)
    wag_rows, wtally = read_dated(wagers_path, "date")
    _refuse_sealed(wtally, "paper wager ledger")
    inv["wagers"] = wtally
    wag_rows = [r for r in wag_rows if "bet_id" in r]
    wag_key = collections.defaultdict(list)
    for r in wag_rows:
        wag_key[(r.get("system_id"), r.get("bet_id"))].append(r)
        inv["seen_markets"].add(market_for("mlb", "game", r.get("market_key")))
        inv["wagers_by_date"][r.get("date")] += 1
    for k, v in wag_key.items():
        if len(v) > 1:
            raise AmbiguousJoinError("paper wager key (system_id, bet_id) not unique: %s" % (k,))
    acct_key = collections.Counter((r["system_id"], r["bet_id"]) for r in acct_rows)
    for k, n in acct_key.items():
        if n > 1:
            raise AmbiguousJoinError("paper account row (system_id, bet_id) not unique: %s" % (k,))

    dec_rows, dtally = read_dated(decisions_path, "decision_utc")
    inv["decisions"] = dtally
    dec_key = collections.defaultdict(list)
    for r in dec_rows:
        if "decision_utc" not in r:
            continue
        cls = _system_class(r.get("system_id"))
        inv["decision_table"][(cls, market_for("mlb", "game", r.get("market_key")),
                               r.get("verdict") or "none", "decisions")] += 1
        if cls == "FORWARD_TEST":
            inv["forward_systems"].add(r.get("system_id"))
            if r.get("p_model") is not None:
                inv["forward_systems_with_p_model"] += 1
        key = (r.get("event_id"), r.get("system_id"), r.get("market_key"),
               r.get("selection_id"), r.get("decision_utc"))
        dec_key[key].append({k: r.get(k) for k in _DECISION_KEYS})
    settled_keys = set()
    entries = []
    for a in sorted(acct_rows, key=lambda r: (r["day"], r["system_id"], r["bet_id"])):
        inv["settled_in_window"] += 1
        sk = (a["system_id"], a["bet_id"])
        settled_keys.add(sk)
        w = (wag_key.get(sk) or [None])[0]
        if w is None:
            inv["unjoined"] += 1
            continue
        dkey = (w.get("event_id"), a["system_id"], w.get("market_key"),
                w.get("selection_id"), w.get("decision_utc"))
        ds = dec_key.get(dkey) or []
        if len(ds) > 1:
            raise AmbiguousJoinError(
                "decision five-field key not unique (%d rows): %s" % (len(ds), dkey))
        if not ds:
            inv["unjoined"] += 1
            continue
        dec = ds[0]
        cls = _system_class(a["system_id"])
        mk = market_for("mlb", "game", a.get("market_key"))
        if (dec.get("price_american") != a.get("price_american")
                or w.get("price_american") != a.get("price_american")):
            inv["price_mismatch"] += 1
        outcome = PAPER_OUTCOMES.get(str(a.get("outcome")).lower())
        if outcome is None:
            inv["unknown_outcome"] += 1
            continue
        prov = dec.get("record_provenance") or "unstamped"
        inv["decision_table"][(cls, mk, dec.get("verdict") or "none", "settled")] += 1
        if prov != PRE_COMMENCEMENT:
            inv["excluded_provenance"][(cls, mk, prov)] += 1
            continue
        inv["decision_table"][(cls, mk, "kept", "kept")] += 1
        sport = "mlb"
        void_reason = a.get("void_reason")
        if void_reason:
            m = _SPORT_TAG.search(void_reason)
            if m:
                sport = m.group(1)
                inv["void_non_mlb"][sport] += 1
        p_model = dec.get("p_model")
        p_our = (p_model if p_model is not None
                 and dec.get("p_model_provenance") != "placeholder" else None)
        entries.append(new_entry(
            rule=PAPER_RULE, date=a["day"], kind="game",
            market_raw=a.get("market_key"), price=a.get("price_american"),
            result=outcome, ledger_units=a.get("profit_units"),
            side=w.get("side"), line=w.get("line"), p_our=p_our,
            p_mkt=dec.get("consensus_fair"), observed_utc=w.get("decision_utc"),
            game_pk=w.get("game_pk"), game_id=w.get("game_pk"),
            event_id=w.get("event_id"), sport=sport, reason=void_reason,
            vis=VIS_PAPER, model=a["system_id"], baseline=_baseline_label(cls),
            clv_basis="paper", sort_hint="%d|%s" % (
                {"FORWARD_TEST": 0, "MARKET_REFERENCE": 1, "CONTROL": 2}.get(cls, 3),
                a["system_id"]),
            entry_class="pick", price_class=None, _decision=dec,
            _sys_class=cls))
    inv["kept"] = len(entries)
    for (sid, bet_id), w in sorted(((k, v[0]) for k, v in wag_key.items()),
                                   key=lambda kv: (kv[1]["date"], kv[0])):
        if (sid, bet_id) not in settled_keys:
            inv["unsettled_by_date"][w["date"]] += 1
            inv["unsettled_samples"].setdefault(w["date"], set()).add(w.get("game_pk"))
        inv["decision_table"][(_system_class(sid), market_for("mlb", "game", w.get("market_key")),
                               "wager", "wagers")] += 1
    return entries, inv


def attach_clv_paper(entries, multibook_path):
    """CLV for staked paper entries through `clv.measure_decision`, with a stale
    close refused (as `card_clv` refuses it) so paper and card CLV are the same
    measurement. F5 has no closing-board shape in `clv.MARKET_SHAPES`; that
    refusal is the project's own (MARKET_NOT_CAPTURED)."""
    from src.pipeline import snapshots
    from src.report import clv
    staked = [e for e in entries if vs.is_staked(e)]
    try:
        rows = snapshots.read_multibook(path=multibook_path, since=vs.CLV_SINCE)
        index = clv.pregame_index(rows)
    except Exception as exc:  # noqa: BLE001 -- unreadable: reported, never guessed
        for e in staked:
            e["clv"] = {"absence": "CLV_STORE_UNREADABLE_%s" % type(exc).__name__.upper()}
        return
    for e in staked:
        m = clv.measure_decision(e["_decision"], index)
        if m.get("clv_bps") is not None:
            if m.get("closing_lead_stale"):
                e["clv"] = {"absence": "CLOSE_STALE"}
            else:
                e["clv"] = {"clv_bps": m["clv_bps"], "beats_close": m["clv_bps"] > 0}
        else:
            e["clv"] = {"absence": m.get("absence") or "UNKNOWN"}


def attach_clv_ufc(entries, multibook_path):
    """UFC: `card_clv.measure_pick` against the MMA pre-game index. The picks
    freeze no observed_utc, so a closing board that is the decision board
    cannot be ruled out (same as NFL)."""
    from src.pipeline import snapshots
    from src.report import card_clv, clv
    staked = [e for e in entries if vs.is_staked(e)]
    if not staked:
        return
    try:
        rows = snapshots.read_multibook(path=multibook_path, sport="mma", since=vs.CLV_SINCE)
        index = clv.pregame_index(rows)
    except Exception as exc:  # noqa: BLE001
        for e in staked:
            e["clv"] = {"absence": "CLV_STORE_UNREADABLE_%s" % type(exc).__name__.upper()}
        return
    for e in staked:
        pick = {"kind": "game", "market": "moneyline", "price": e["price"],
                "side": e["side"], "line": e["line"], "observed_utc": e["observed_utc"],
                "market_probability": e["p_mkt"], "entry_class": e["entry_class"],
                "price_class": None, "event_id": e["event_id"]}
        e["clv"] = card_clv.measure_pick(pick, index)


def mark_paper_postseason(entries):
    """The project's calendar rule on paper entries: `vs.mark_postseason` where
    a game id exists, and the postseason calendar by date where none does."""
    mlb = [e for e in entries if e["sport"] == "mlb"]
    vs.mark_postseason(mlb)
    try:
        from src.analysis import postseason_config as pc
        first, last = pc.REGULAR_SEASON_ENDS, pc.CALENDAR["world_series"]["end"]
    except Exception:  # noqa: BLE001
        return
    for e in mlb:
        if e.get("game_pk") is None and first < e["date"] <= last:
            e["postseason"] = True


# ---------------------------------------------------------------------------
# Matrix assembly
# ---------------------------------------------------------------------------

def load_sources(evidence_dir=None, accounts_dir=None, multibook=None, event_map=None,
                 as_of=None):
    """Read every store once. Returns a `sources` dict for `build_matrix`."""
    ev = Path(evidence_dir) if evidence_dir else ROOT / "evidence"
    acc = Path(accounts_dir) if accounts_dir else ROOT / "data" / "paper_accounts"
    multibook = str(multibook or ROOT / "data" / "processed" / "odds_multibook.jsonl")
    event_map = str(event_map or ROOT / "data" / "processed" / "event_game_map.jsonl")

    card_entries, status, published = load_cards(evidence_dir)
    mvs_entries, mvs_info = load_mvs(ev / "mlb_value_shadow_v1")
    live_entries = load_live(ev / "live_candidates_v1.jsonl")
    paper_entries, paper_inv = load_paper(
        acc, ev / "paper_wagers_v2.jsonl", ev / "decisions_v2.jsonl")
    f5 = read_f5_flags(ev / "forward_ledger.jsonl")

    if as_of:
        card_entries = [e for e in card_entries if e["date"] <= as_of]
        mvs_entries = [e for e in mvs_entries if e["date"] <= as_of]
        live_entries = [e for e in live_entries if e["date"] <= as_of]
        paper_entries = [e for e in paper_entries if e["date"] <= as_of]

    # Card, MVS: postseason, then CLV through value_scan (props refused, NFL by names).
    vs.mark_postseason(card_entries)
    vs.mark_postseason(mvs_entries)
    vs.mark_postseason(live_entries)
    clv_error = None
    ufc = [e for e in card_entries if e["sport"] == "mma"]
    others = [e for e in card_entries if e["sport"] != "mma"] + mvs_entries
    try:
        vs.attach_clv(others, multibook, event_map)
    except Exception as exc:  # noqa: BLE001
        clv_error = "unreadable: %s" % type(exc).__name__
        for e in others:
            e["clv"] = {"absence": "CLV_STORE_" + clv_error.upper().replace(" ", "_").replace(":", "")}
    attach_clv_ufc(ufc, multibook)
    for e in live_entries:
        if vs.is_staked(e):
            e["clv"] = {"absence": "IN_PLAY_NO_CLOSING_LINE"}
    mark_paper_postseason(paper_entries)
    attach_clv_paper(paper_entries, multibook)

    entries = card_entries + mvs_entries + live_entries + paper_entries
    label_entries(entries)
    for e in live_entries:
        e["market"] = e.pop("market_label_override", e["market"])
        e["family"] = family_for(e["sport"], e["market"])
    return {"entries": entries, "status": status, "published": published,
            "mvs": mvs_info, "paper": paper_inv, "f5": f5, "clv_error": clv_error,
            "as_of": as_of}


def row_key(e):
    return (e["sport"], e["market"], e["vis"], e["rule"], e["entry_class"],
            "postseason" if e.get("postseason") else "regular", e["model"])


def calibration(entries):
    """Mean frozen probability vs observed win rate over staked entries that
    carry a frozen probability of their own; None if none does. The gap is
    predicted minus observed; `se` is sqrt(sum p(1-p)) / n, the standard error
    of the observed rate if those probabilities were exactly right."""
    s = [e for e in entries if vs.is_staked(e) and e.get("p_our") is not None]
    if not s:
        return None
    n = len(s)
    pred = sum(e["p_our"] for e in s) / n
    obs = sum(1 for e in s if e["result"] == WIN) / n
    var = sum(e["p_our"] * (1.0 - e["p_our"]) for e in s)
    return {"n": n, "pred": pred, "obs": obs, "gap": pred - obs,
            "se": math.sqrt(var) / n}


def _family_index(name):
    names = [f[0] for f in FAMILIES + EXTRA_FAMILIES]
    return names.index(name) if name in names else len(names)


def _row_sort(row):
    e = row["sample"]
    rule_pos = CARD_RULE_ORDER.index(e["rule"]) if e["rule"] in CARD_RULE_ORDER else len(CARD_RULE_ORDER)
    return (_family_index(row["family"]) if row["family"] else 999, row["market"],
            VIS_ORDER.index(e["vis"]), rule_pos, e["sort_hint"], e["rule"],
            vs.CLASS_ORDER.index(e["entry_class"]) if e["entry_class"] in vs.CLASS_ORDER else 9,
            row["scope"], e["model"])


def build_rows(entries):
    """(rows, idle): one row per key with at least one staked entry; `idle` are
    the keys with none (they feed the never-staked table and MISSING reasons)."""
    groups = collections.defaultdict(list)
    for e in entries:
        groups[row_key(e)].append(e)
    rows, idle = [], []
    for key, es in groups.items():
        s = vs.summarize(es)
        dates = sorted(e["date"] for e in es if vs.is_staked(e))
        row = {"key": key, "sport": key[0], "market": key[1], "vis": key[2],
               "rule": key[3], "cls": key[4], "scope": key[5], "model": key[6],
               "family": es[0]["family"], "sample": es[0], "s": s,
               "cal": calibration(es), "n_entries": len(es),
               "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
               "n_dates": len(set(dates)), "baseline": es[0]["baseline"],
               "clv_basis": es[0]["clv_basis"], "entries": es}
        (rows if s["n_staked"] > 0 else idle).append(row)
    rows.sort(key=_row_sort)
    idle.sort(key=_row_sort)
    return rows, idle


def _tally(entries, key):
    c = collections.Counter(key(e) for e in entries)
    return ", ".join("%s x%d" % (k, v) for k, v in sorted(c.items(), key=lambda kv: str(kv[0])))


def _seen_markets(sources, vis, sport):
    seen = set()
    for label, pub in sources["published"].items():
        if STORE_VISIBILITY.get(label) == vis:
            for (sp, mk), n in pub["markets"].items():
                if sp == sport and n:
                    seen.add(mk)
    for e in sources["entries"]:
        if e["vis"] == vis and e["sport"] == sport:
            seen.add(e["market"])
    if vis == VIS_PAPER and sport == "mlb":
        seen |= {m for m in sources["paper"]["seen_markets"]}
    return sorted(seen)


def missing_row(fam, sport, market, vis, sources):
    """The MISSING row for a (family, visibility) cell with no staked entry."""
    ents = [e for e in sources["entries"] if e["family"] == fam and e["vis"] == vis]
    extra = []
    if ents:
        token = PUBLISHED_UNGRADED
        reasons = collections.Counter(
            (e.get("reason") or "").strip()[:70] for e in ents if e.get("reason"))
        detail = "%d entries recorded, none staked (%s)" % (
            len(ents), _tally(ents, lambda e: "withdrawn" if e["entry_class"] == "withdrawn"
                              else e["result"]))
        if reasons:
            detail += "; reasons: " + "; ".join("%s x%d" % (k, v) for k, v in
                                                sorted(reasons.items()))
        detail += "; rules: " + ", ".join(sorted({e["rule"] for e in ents}))
    elif fam == "MLB first-five (F5)" and vis == VIS_PUBLIC and sources["f5"]["flagged"]:
        f5 = sources["f5"]
        token = PUBLISHED_NOT_STAKED
        detail = ("%d F5 'flagged' recommendations on the Analyzer forward ledger "
                  "(evidence/forward_ledger.jsonl, %s..%s; %d dated on or after %s) carry a "
                  "side and snapshot prices but no stake, no price rule and no grade"
                  % (f5["flagged"], f5["first"], f5["last"], f5["flagged_in_window"],
                     WINDOW_START))
    else:
        token = NEVER_PUBLISHED
        seen = _seen_markets(sources, vis, sport)
        detail = "no %s %s entry of this market in any ledger read; %s ledgers hold only: %s" % (
            sport.upper(), vis, vis, ", ".join(seen) if seen else "nothing")
        if market == "totals":
            pubs = [p for lbl, p in sources["published"].items()
                    if STORE_VISIBILITY.get(lbl) == vis and
                    (lbl.startswith("NFL") == (sport == "nfl")) and
                    (lbl.startswith("UFC") == (sport == "mma"))]
            if pubs:
                detail += ("; published card rows with a total pick: %d of %d; "
                           "totals_paused true on %d" % (
                               sum(p["rows_with_total_picks"] for p in pubs),
                               sum(p["rows"] for p in pubs),
                               sum(p["totals_paused_true"] for p in pubs)))
            for arm, n in sorted(sources["mvs"]["scan_only"].items()):
                if vis == VIS_SHADOW and sport == "mlb":
                    detail += "; MLB value shadow arm %s has %d scan rows and no decision" % (arm, n)
        if market == "player props" and sport == "nfl":
            pubs = [p for lbl, p in sources["published"].items() if lbl.startswith("NFL")]
            detail += "; published NFL card rows with a prop pick: %d of %d" % (
                sum(p["rows_with_prop_picks"] for p in pubs), sum(p["rows"] for p in pubs))
    return {"family": fam, "sport": sport, "market": market, "vis": vis,
            "reason": token, "detail": detail}


def build_matrix(sources):
    entries = sources["entries"]
    rows, idle = build_rows(entries)
    fam_rows = collections.OrderedDict()
    missing = []
    for fam, sport, market in FAMILIES:
        by_vis = {v: [r for r in rows if r["family"] == fam and r["vis"] == v]
                  for v in VIS_ORDER}
        cells = []
        for v in VIS_ORDER:
            if by_vis[v]:
                cells.extend(by_vis[v])
            else:
                m = missing_row(fam, sport, market, v, sources)
                missing.append(m)
                cells.append(m)
        fam_rows[fam] = cells
    for fam, sport, market in EXTRA_FAMILIES:
        fam_rows[fam] = [r for r in rows if r["family"] == fam]
    other = [r for r in rows if r["family"] is None]
    n = 0
    for fam, cells in fam_rows.items():
        for c in cells:
            n += 1
            c["id"] = "M%03d" % n if "reason" in c else "R%03d" % n
    for c in other:
        n += 1
        c["id"] = "R%03d" % n
    real = [r for r in rows]
    return {"rows": real, "idle": idle, "families": fam_rows, "other": other,
            "missing": missing, "sources": sources,
            "integrity": integrity(entries)}


def integrity(entries):
    bad = collections.Counter()
    for e in entries:
        if vs.is_staked(e) and e.get("ledger_units") is not None:
            if abs(vs.units(e["price"], e["result"]) - e["ledger_units"]) > 0.0006:
                bad[(e["vis"], e["rule"] if e["vis"] != VIS_PAPER else "paper")] += 1
    return {"mismatches": sum(bad.values()), "by_source": dict(bad),
            "checked": sum(1 for e in entries
                           if vs.is_staked(e) and e.get("ledger_units") is not None)}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _pct(x):
    return "-" if x is None else format(100 * x, "+.1f") + "%"


def cell_clv(r):
    s, c = r["s"], r["s"]["clv"]
    if r["s"]["n_staked"] == 0:
        return "-"
    if c["n"] == 0:
        refused = ", ".join("%s x%d" % (k, v) for k, v in c["refused"].items())
        return "none measured (%s) [%s]" % (refused or "nothing attempted", r["clv_basis"])
    if c["n"] == 1 or c["se"] is None:
        return "%+.2f, n=1 of %d, no interval [%s]" % (c["mean"], s["n_staked"], r["clv_basis"])
    return "%+.2f [%+.2f, %+.2f] n=%d of %d [%s]" % (
        c["mean"], c["lo"], c["hi"], c["n"], s["n_staked"], r["clv_basis"])


def cell_z(r):
    s = r["s"]
    if s["z"] is None:
        return "-"
    cell = "%+.2f" % s["z"]
    if s["n_z"] < s["n_staked"]:
        cell += " (%d/%d)" % (s["n_z"], s["n_staked"])
    return cell


def cell_cal(r):
    c = r["cal"]
    if c is None:
        return NO_PROBABILITY_FROZEN
    src = "market's own p" if r["baseline"] == BASELINE_MARKET_REFERENCE else "own p"
    return "%s: pred %.3f, obs %.3f, gap %+.3f (se %.3f), n=%d" % (
        src, c["pred"], c["obs"], c["gap"], c["se"], c["n"])


def cell_brier(r):
    if r["baseline"] == BASELINE_MARKET_REFERENCE and r["cal"] is not None:
        return "identical to market by construction"
    b = r["s"]["brier"]
    if r["cal"] is None or b is None:
        return "-"
    return "%+.4f +/- %.4f (n=%d)" % (b["diff"], b["se"], b["n"]) if b["se"] is not None \
        else "%+.4f (n=%d)" % (b["diff"], b["n"])


def cell_span(r):
    if r["first"] is None:
        return "-"
    f, l = r["first"][5:], r["last"][5:]
    return "%s" % f if f == l else "%s..%s (%dd)" % (f, l, r["n_dates"])


def cell_verdict(r):
    v = r["s"]["verdict"]
    if v == vs.VERDICT_TOO_FEW:
        v = "TOO FEW (n=%d)" % r["s"]["n_staked"]
    if r["baseline"]:
        v += " [%s]" % r["baseline"]
    return v


def _esc(text):
    return str(text).replace("|", "/")


def render_row(r):
    s = r["s"]
    scope = "" if r["scope"] == "regular" else " / postseason"
    label = "%s / %s%s" % (r["rule"], r["cls"], scope)
    model = r["model"] if not r["baseline"] else "%s [%s]" % (r["model"], r["baseline"])
    cells = [r["id"], r["market"], _esc(label), _esc(model), r["vis"], str(s["n_staked"]),
             "%d-%d-%d-%d" % (s["wins"], s["losses"], s["pushes"], s["voids"]),
             vs._f(s["units"], "+.2f"), _pct(s["roi"]), _esc(cell_clv(r)), cell_z(r),
             _esc(cell_cal(r)), cell_brier(r), cell_span(r), _esc(cell_verdict(r))]
    return "| " + " | ".join(cells) + " |"


def render_missing(m):
    return ("| %s | %s | none | - | %s | 0 | - | - | - | - | - | - | - | - | **MISSING** %s |"
            % (m["id"], m["market"], m["vis"], m["reason"]))


TABLE_HEAD = (
    "| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | "
    "Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | "
    "Span | Verdict |",
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def _grid_cell(cells, vis):
    mine = [c for c in cells if c["vis"] == vis]
    if mine and "reason" in mine[0]:
        return "MISSING %s" % mine[0]["reason"]
    if not mine:
        return "-"
    verdicts = collections.Counter(c["s"]["verdict"] for c in mine)
    best = max(c["s"]["n_staked"] for c in mine)
    return "%d row(s), largest n=%d; %s" % (
        len(mine), best, ", ".join("%s %d" % (k, v) for k, v in sorted(verdicts.items())))


def render(matrix, now=None):
    src = matrix["sources"]
    rows = matrix["rows"]
    out = []
    w = out.append
    counts = collections.Counter(r["s"]["verdict"] for r in rows)
    dates = sorted({e["date"] for e in src["entries"]})
    w("# Performance matrix")
    w("")
    w("Generated: %s" % (now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    w("")
    w("Settled entries from %s to %s (%s). Regenerate with `python scripts/performance_matrix.py`. "
      "Read-only on every ledger; the script changes no rule, gate, threshold or published record. "
      "Only dates from %s onward are read; the sealed window %s..%s is never opened."
      % (dates[0] if dates else "-", dates[-1] if dates else "-",
         ("as of " + src["as_of"]) if src["as_of"] else "all settled dates",
         WINDOW_START, vs.SEALED_START, vs.SEALED_END))
    w("")
    w("## How to read this")
    w("")
    w("**Verdict rule (fixed, stated once, applied identically to every row, baselines included).** "
      "`TOO FEW` when n staked < %d. `CANDIDATE` only when n staked >= %d AND mean closing-line value "
      "> 0 AND the lower end of its 95%% interval (mean - %.2f se) > 0 AND z vs the market > %g. "
      "Everything else is `NO EVIDENCE`. A row whose closing-line value cannot be measured can never "
      "reach `CANDIDATE`. A `CANDIDATE` would be a hypothesis for a pre-registered forward test "
      "(`docs/PREREG_CARD_V2.md`), never a reason to change a rule."
      % (vs.MIN_N_STAKED, vs.MIN_N_CANDIDATE, vs.CI_Z, vs.Z_CANDIDATE))
    w("")
    n_real = len(rows)
    w("**Multiplicity.** This matrix has %d measured rows and %d MISSING rows, each a different "
      "population. With about %d looks, one or two will look good by chance alone, and a z above 2 in "
      "a row is what chance produces. The rows also overlap: V1 public, V2 public and the V2 shadows "
      "often hold the same games, and the paper systems bet the same games on the same sides (the "
      "FORWARD_TEST systems are near-duplicate genomes), so the rows are not independent looks and the "
      "count overstates how many separate tests were run. No row here is a reason to change a rule. "
      "Changing a rule needs a pre-registered test on forward data."
      % (n_real, len(matrix["missing"]), n_real))
    w("")
    high = [r for r in rows if r["s"]["z"] is not None and abs(r["s"]["z"]) > vs.Z_CANDIDATE]
    w("**Rows with |z| above %g: %d.** %s Chance alone puts roughly one row in twenty past 2 in either "
      "direction; a row that does is not a result unless it is also CANDIDATE under the rule above, "
      "and a baseline row that does is a property of the sample." % (
          vs.Z_CANDIDATE, len(high),
          "; ".join("%s (%s %s, %s, n=%d, z %+.2f%s)" % (
              r["id"], r["market"], r["vis"], r["model"] if r["vis"] == VIS_PAPER else r["rule"],
              r["s"]["n_staked"], r["s"]["z"],
              ", " + r["baseline"] if r["baseline"] else "") for r in high) + "." if high
          else "None."))
    w("")
    w("**Verdicts this run (measured rows):** %s. **MISSING rows:** %d."
      % (", ".join("%s: %d" % (k, counts.get(k, 0)) for k in
                   (vs.VERDICT_TOO_FEW, vs.VERDICT_NO_EVIDENCE, vs.VERDICT_CANDIDATE)),
         len(matrix["missing"])))
    w("")
    w("**Baselines are not models.** Rows labelled `BASELINE: CONTROL` take a fixed side with no "
      "information (always home, always under); rows labelled `BASELINE: MARKET REFERENCE` republish "
      "the board's own de-vigged consensus (their probability IS the price). They exist to say what "
      "no-information and the-market-itself earn. A control or market-reference row that looks good is "
      "variance or a property of the sample (for example, over and under totals mirror each other), "
      "never a result for a model.")
    w("")
    w("**Units** are flat 1u per entry at the frozen price. Pushes, voids, unresolved and withdrawn "
      "entries are never staked (W-L-P-V counts wins, losses, pushes, voids; N staked = W + L). ROI = "
      "units / n staked. Rows are never pooled across rule, market, entry class, season scope, model or "
      "visibility; fills never enter a pick row; postseason entries are their own rows (the project's "
      "calendar rule). z = (wins - market-expected wins) / sqrt(sum p(1-p)) with the de-vigged market "
      "probability frozen on each entry. Where `(k/n)` appears only k of n staked entries carry it. "
      "`MISSING` names why a cell is empty, from a fixed vocabulary: %s." % "; ".join(
          "`%s` = %s" % (k, v) for k, v in MISSING_REASONS.items()))
    w("")
    w("### Rows are not all measured the same way")
    w("")
    w("- **Closing-line value (CLV)** is the de-vigged close minus the break-even of the frozen price, in "
      "probability points. It subtracts a de-vigged close from a price that still carries the book's "
      "margin, so it is biased negative by roughly half the hold before any line has moved. Card, "
      "shadow and UFC rows use `card_clv.measure_pick` (refuses props always, refuses a stale or thin "
      "close and a decision-board close). Paper rows use `clv.measure_decision` at the price taken "
      "(best on the board at the decision) with a close older than 90 minutes refused, which is "
      "`card_clv`'s rule. Props, F5 and in-play have no closing board and are refused. Tags `[card]`, "
      "`[paper]` show which.")
    w("- **Market probability behind z** differs by source: cards freeze the de-vigged probability at "
      "the quoted price's board; paper rows use the decision's `consensus_fair` (mean de-vigged "
      "probability across books at the decision); MLB value shadow rows use the other books' "
      "de-vigged consensus (power or proportional, as each decision froze it). Two z values from different sources are not the same test.")
    w("- **Calibration** exists only where a per-entry probability of the row's own is frozen on the "
      "entry: V1 and V2 card rows, and paper MARKET_REFERENCE rows (whose probability is the market's "
      "own). Paper CONTROLs freeze a placeholder 0.5 (not a model number, so not used) and paper "
      "FORWARD_TEST systems freeze none; NFL and UFC picks freeze none. Rows with none print "
      "`%s` and no number. Gap = mean predicted - observed win rate; se = sqrt(sum p(1-p))/n under "
      "the row's own probabilities. Brier compares ours with the market's on the same entries "
      "(positive = ours worse)." % NO_PROBABILITY_FROZEN)
    spans = []
    for label in ("V1 public", "V1 shadow", "V2 public", "V2 shadow A", "NFL", "UFC"):
        st = src["status"].get(label)
        if st and not st["error"] and st["settled_dates"]:
            spans.append("%s %s..%s" % (label, st["settled_dates"][0][5:], st["settled_dates"][-1][5:]))
    paper_days = sorted({e["date"] for e in src["entries"] if e["vis"] == VIS_PAPER})
    if paper_days:
        spans.append("paper %s..%s" % (paper_days[0][5:], paper_days[-1][5:]))
    w("- **Windows differ.** Settled dates by ledger: %s. A ROI gap between two rows can be a "
      "different set of days." % ", ".join(spans))
    w("- **Price basis differs.** Card prices are the frozen quote at publication; UFC prices are the "
      "average across books; paper prices are the best price on the board at the decision. Paper "
      "`spreads` and `totals` pool every line a system bet (-1.5, +1.5, 7.5, 8.5 ...); card run lines "
      "are single -1.5/+1.5 picks.")
    w("")

    # Coverage grid
    w("## Coverage grid (family by visibility)")
    w("")
    w("| Family | public | shadow | paper |")
    w("|---|---|---|---|")
    for fam, sport, market in FAMILIES:
        cells = matrix["families"][fam]
        w("| %s | %s | %s | %s |" % (fam, *[_esc(_grid_cell(cells, v)) for v in VIS_ORDER]))
    w("")

    # Per-family tables
    w("## The matrix")
    w("")
    for fam, cells in matrix["families"].items():
        w("### %s" % fam)
        w("")
        if not cells:
            w("No entries.")
            w("")
            continue
        w(TABLE_HEAD[0])
        w(TABLE_HEAD[1])
        for c in cells:
            w(render_missing(c) if "reason" in c else render_row(c))
        miss = [c for c in cells if "reason" in c]
        if miss:
            w("")
            for m in miss:
                w("- **%s** (%s, %s) `%s`: %s." % (m["id"], m["market"], m["vis"],
                                                 m["reason"], _esc(m["detail"])))
        w("")
    if matrix["other"]:
        w("### Rows outside the required families")
        w("")
        w(TABLE_HEAD[0])
        w(TABLE_HEAD[1])
        for r in matrix["other"]:
            w(render_row(r))
        w("")

    out.extend(_paper_inventory(matrix))
    out.extend(_never_staked(matrix))
    out.extend(_ledgers(matrix))
    out.extend(_conclusions(matrix))
    return "\n".join(out) + "\n"


def _paper_inventory(matrix):
    src = matrix["sources"]
    inv = src["paper"]
    out = ["## Paper engine inventory", ""]
    out.append("Stores read: decisions `evidence/decisions_v2.jsonl` (hot file plus archive segments "
               "through `src/pipeline/store_archive.py`; %d lines, %d dated %s or later, %d dated "
               "before it and skipped unparsed, %d dated inside the sealed window and skipped "
               "unparsed), wagers `evidence/paper_wagers_v2.jsonl` (%d lines, %d in window), and the "
               "settlement store `data/paper_accounts/<system_id>.jsonl` written by "
               "`src.engine.settle_slate.run_settle` (one hash-chained ledger per system, %d files)."
               % (inv["decisions"].get("lines", 0), inv["decisions"].get("in_window", 0), WINDOW_START,
                  inv["decisions"].get("pre_window", 0), len(inv["decisions"].get("sealed_dates", [])),
                  inv["wagers"].get("lines", 0), inv["wagers"].get("in_window", 0),
                  len(inv["accounts"])))
    out.append("")
    settled = inv["settled_in_window"]
    out.append("**The wagers are settled.** %d settled account rows dated %s or later; %d joined to a "
               "wager and a decision (both joins unique); %d kept as live pre-commencement entries. "
               "Excluded by name: %s. Account rows dated before the window and not read: %d (%s)."
               % (settled, WINDOW_START, settled - inv["unjoined"] - inv["unknown_outcome"],
                  inv["kept"],
                  ("; ".join("%s %s %s x%d" % (c, m, p, n) for (c, m, p), n in
                             sorted(inv["excluded_provenance"].items())) or "no provenance exclusions")
                  + ("; %d unjoined" % inv["unjoined"] if inv["unjoined"] else ""),
                  inv["excluded_pre_window_rows"],
                  ", ".join("%s: %d" % (k, v) for k, v in
                            sorted(inv["excluded_pre_window_by_month"].items())) or "none"))
    if any(k < "2026" for k in inv["excluded_pre_window_by_month"]):
        out.append("")
        out.append("Some of those pre-window account rows carry a 2023 date (control systems); they "
                   "sit inside the 2026 paper stores and are not read. They are an anomaly in the "
                   "store, listed here so nobody finds them by accident.")
    out.append("")
    out.append("Only decisions stamped `%s` count. A `replay` decision was recorded after its own "
               "game's first pitch, so it is hindsight and is excluded (doctrine section 6)." %
               PRE_COMMENCEMENT)
    out.append("")
    if inv["unsettled_by_date"]:
        out.append("**Wagers with no settlement row** (the settle step refuses a whole date while any "
                   "wagered game lacks a result, `run_settle` in `src/engine/settle_slate.py`): "
                   + "; ".join(
                       "%s: %d of %d wagers%s" % (
                           d, n, inv["wagers_by_date"].get(d, n),
                           " (the whole date)" if n == inv["wagers_by_date"].get(d, n) else "")
                       for d, n in sorted(inv["unsettled_by_date"].items()))
                   + ". These are not in any row above, so the paper record omits those days "
                   "entirely.")
        out.append("")
    if inv["void_non_mlb"]:
        out.append("**Non-MLB wagers voided by design:** " + ", ".join(
            "%s x%d" % (k, v) for k, v in sorted(inv["void_non_mlb"].items())) +
            " (the pre-2026-09-21 engine built MLB boards from every sport; such wagers settle VOID "
            "and are never staked).")
        out.append("")
    out.append("**Decision, wager and settlement counts by class and market** (window; a decision is "
               "a candidate, a wager is the top-ranked play per system per game, a settled row is a "
               "wager with an account entry):")
    out.append("")
    out.append("| System class | Market | Decisions | play | refused | Wagers | Settled rows | "
               "Kept as entries |")
    out.append("|---|---|---|---|---|---|---|---|")
    table = inv["decision_table"]
    keys = sorted({(c, m) for (c, m, _v, k) in table if k != "kept"})
    for cls, mk in keys:
        dec = sum(n for (c, m, v, k), n in table.items() if c == cls and m == mk and k == "decisions")
        play = table.get((cls, mk, "play", "decisions"), 0)
        wag = table.get((cls, mk, "wager", "wagers"), 0)
        sett = sum(n for (c, m, v, k), n in table.items() if c == cls and m == mk and k == "settled")
        kept = table.get((cls, mk, "kept", "kept"), 0)
        out.append("| %s | %s | %d | %d | %d | %d | %d | %d |" % (
            cls, mk, dec, play, dec - play, wag, sett, kept))
    out.append("")
    ft = sorted(inv["forward_systems"])
    out.append("**FORWARD_TEST systems:** %d distinct systems with decisions in window; `p_model` is "
               "frozen on %d of their decisions (provenance `none`), so no FORWARD_TEST row has a "
               "calibration. CONTROL decisions freeze a placeholder 0.5; MARKET_REFERENCE decisions "
               "freeze the board consensus as `p_model` (provenance `market_derived`)."
               % (len(ft), inv["forward_systems_with_p_model"]))
    out.append("")
    out.append("**Not measurable for paper:** CLV on F5 (the multibook store has no F5 closing-board "
               "shape; `clv.MARKET_SHAPES` knows h2h, spreads, totals); calibration for every "
               "FORWARD_TEST and CONTROL row; any prop (the paper engine registers h2h, spreads, "
               "totals and F5 only).")
    out.append("")
    return out


def _never_staked(matrix):
    out = ["## Entries counted and never staked", "",
           "Withdrawn entries and entries with no WIN or LOSS (void, push, unresolved), by "
           "visibility, rule, market and class. Counted, never staked; the results shown for "
           "withdrawn entries are what they would have been and no unit is attributed to them.", "",
           "| Vis | Sport | Market | Rule | Class | Entries | Void | Push | Unresolved | Withdrawn (result) |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    groups = collections.defaultdict(list)
    for e in matrix["sources"]["entries"]:
        label = e["_sys_class"] if e["vis"] == VIS_PAPER else e["rule"]
        if e["entry_class"] == "withdrawn" or e["result"] in (VOID, PUSH, UNRESOLVED):
            groups[(e["vis"], e["sport"], e["market"], label, e["entry_class"])].append(e)
    if not groups:
        out.append("| (none) | | | | | | | | | |")
    for key in sorted(groups, key=lambda k: tuple(str(x) for x in k)):
        es = groups[key]
        wd = collections.Counter(e["result"] for e in es if e["entry_class"] == "withdrawn")
        out.append("| %s | %s | %s | %s | %s | %d | %d | %d | %d | %s |" % (
            *key, len(es),
            sum(1 for e in es if e["entry_class"] != "withdrawn" and e["result"] == VOID),
            sum(1 for e in es if e["entry_class"] != "withdrawn" and e["result"] == PUSH),
            sum(1 for e in es if e["entry_class"] != "withdrawn" and e["result"] == UNRESOLVED),
            ", ".join("%s x%d" % (k, v) for k, v in sorted(wd.items())) or "-"))
    out.append("")
    return out


def _ledgers(matrix):
    src = matrix["sources"]
    integ = matrix["integrity"]
    out = ["## Ledgers read and integrity", "",
           "| Ledger | Status | Rows | Settled dates | First | Last | Corrections folded |",
           "|---|---|---|---|---|---|---|"]
    for label in ("V1 public", "V1 shadow", "V2 public", "V2 shadow A", "V2 shadow C",
                  "V2 shadow E", "NFL", "UFC"):
        st = src["status"].get(label)
        if st is None:
            continue
        if st["error"]:
            out.append("| %s | %s | - | - | - | - | - |" % (label, st["error"]))
        else:
            sd = st["settled_dates"]
            out.append("| %s | read | %d | %d | %s | %s | %d |" % (
                label, st["rows"], len(sd), sd[0] if sd else "-", sd[-1] if sd else "-",
                st["corrections"]))
    mvs = src["mvs"]
    for arm, d in sorted(mvs["arms"].items()):
        out.append("| MLB value shadow %s | read | %d decisions | %d settled | - | - | 0 |" % (
            arm, d["decisions"], d["settled"]))
    out.append("")
    if src.get("clv_error"):
        out.append("Closing-line value: %s. Every card CLV cell is therefore a refusal, not a "
                   "measurement." % src["clv_error"])
        out.append("")
    out.append("Integrity check: %d of %d staked entries (all visibilities) have flat-stake units "
               "recomputed from price and result differing from the ledger's own profit_units by more "
               "than rounding%s." % (integ["mismatches"], integ["checked"],
                                      (" (" + ", ".join("%s %s x%d" % (v, r, n) for (v, r), n in
                                                        sorted(integ["by_source"].items())) + ")")
                                      if integ["by_source"] else ""))
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Closing section: from the table only
# ---------------------------------------------------------------------------

def _range(xs, fmt):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "n/a"
    lo, hi = min(xs), max(xs)
    return format(lo, fmt) if lo == hi else "%s to %s" % (format(lo, fmt), format(hi, fmt))


def _conclusions(matrix):
    rows = matrix["rows"]
    out = ["## What this says about where to build", ""]

    out.append("**1. Which families have enough data to say anything (n >= 30), and what they say.** "
               "Counted from rows with n staked >= %d. A row is one rule, class, scope and model; the "
               "ranges below run across those rows and are never pooled." % vs.MIN_N_STAKED)
    out.append("")
    enough = [r for r in rows if r["s"]["n_staked"] >= vs.MIN_N_STAKED and r["family"]]
    by_family = collections.OrderedDict()
    for r in enough:
        by_family.setdefault(r["family"], []).append(r)
    if not by_family:
        out.append("- No family has a row with n >= %d." % vs.MIN_N_STAKED)
    for fam, rs in by_family.items():
        vis = collections.Counter(r["vis"] for r in rs)
        clv_rows = [r for r in rs if r["s"]["clv"]["n"] >= 2]
        verdicts = collections.Counter(r["s"]["verdict"] for r in rs)
        n_base = sum(1 for r in rs if r["baseline"])
        n_neg = sum(1 for r in clv_rows if r["s"]["clv"]["mean"] < 0)
        out.append(
            "- **%s**: %d row(s) (%s%s). ROI %s; z vs market %s; CLV measured (n >= 2) on %d of them, "
            "mean %s pts, negative on %d of %d; verdicts %s." % (
                fam, len(rs), ", ".join("%s %d" % (k, v) for k, v in sorted(vis.items())),
                ("; %d of them baseline, not a model" % n_base) if n_base else "",
                _range([100 * r["s"]["roi"] for r in rs if r["s"]["roi"] is not None], "+.1f") + "%",
                _range([r["s"]["z"] for r in rs], "+.2f"), len(clv_rows),
                _range([r["s"]["clv"]["mean"] for r in clv_rows], "+.2f"), n_neg, len(clv_rows),
                ", ".join("%s %d" % (k, v) for k, v in sorted(verdicts.items()))))
    n_cand = sum(1 for r in rows if r["s"]["verdict"] == vs.VERDICT_CANDIDATE)
    all_clv = [r for r in rows if r["s"]["clv"]["n"] >= 2]
    out.append("- Across every row with CLV measured on at least 2 entries (%d rows, any n staked): mean "
               "CLV is positive on %d and has a 95%% interval entirely above zero on %d. CLV is biased "
               "negative by about half the hold, so a negative mean alone is not a finding either." % (
                   len(all_clv), sum(1 for r in all_clv if r["s"]["clv"]["mean"] > 0),
                   sum(1 for r in all_clv if r["s"]["clv"]["lo"] is not None
                       and r["s"]["clv"]["lo"] > 0)))
    thin = [fam for fam, _s, _m in FAMILIES if fam not in by_family]
    out.append("- %d row(s) are CANDIDATE. Families with no row at n >= %d: %s." % (
        n_cand, vs.MIN_N_STAKED, ", ".join(thin) if thin else "none"))
    out.append("")

    out.append("**2. Families the product sells today but cannot measure, and the one missing field "
               "or capture that would make each measurable.** A family counts as sold when it has a "
               "public row, or a public MISSING cell whose reason is PUBLISHED_UNGRADED or "
               "PUBLISHED_NOT_STAKED.")
    out.append("")
    public = [r for r in rows if r["vis"] == VIS_PUBLIC]
    lines = []
    for fam, sport, market in FAMILIES:
        pr = [r for r in public if r["family"] == fam]
        if not pr:
            continue
        no_clv = all(r["s"]["clv"]["n"] == 0 for r in pr)
        some_clv = any(r["s"]["clv"]["n"] > 0 for r in pr)
        no_p = all(r["cal"] is None for r in pr)
        nstk = sum(r["s"]["n_staked"] for r in pr)
        if market in ("hits prop", "total-bases prop") and no_clv:
            lines.append("- **%s** (%d staked across %d public row(s)): no closing price, because "
                         "`card_clv` refuses every prop. Missing capture: a closing prop board per "
                         "player and line, from at least %d books, within 90 minutes of first pitch."
                         % (fam, nstk, len(pr), _min_books()))
        elif sport == "nfl" and no_p:
            lines.append("- **%s** (%d staked): no model probability and no observed time are frozen on "
                         "the pick, so neither calibration nor closing-line value can be tested "
                         "(the closing-line check cannot rule out a decision board that is the closing "
                         "board). Missing field: `observed_utc` on the pick for CLV; `model_probability` "
                         "for calibration." % (fam, nstk))
        elif sport == "mma":
            lines.append("- **%s** (n=%d staked, TOO FEW): the sample is the blocker, not a field. CLV "
                         "measured on %d; `observed_utc` is not frozen on the pick. Missing field: "
                         "`observed_utc` (so a decision board that is the close can be ruled out); "
                         "n >= 30 settled bouts." % (fam, nstk, sum(r["s"]["clv"]["n"] for r in pr)))
        elif market == "moneyline" and some_clv:
            refused = collections.Counter()
            for r in pr:
                refused.update(r["s"]["clv"]["refused"])
            lines.append("- **%s**: measurable, partly. CLV refused on %d staked entries (%s). "
                         "Missing capture: a closing board within 90 minutes of first pitch for every "
                         "game." % (fam, sum(refused.values()),
                                    ", ".join("%s x%d" % (k, v) for k, v in sorted(refused.items()))))
        else:
            lines.append("- **%s** (%d staked across %d public row(s), n < %d each): CLV measured on "
                         "%d. The sample is the blocker; no field is missing."
                         % (fam, nstk, len(pr), vs.MIN_N_STAKED,
                            sum(r["s"]["clv"]["n"] for r in pr)))
    for m in matrix["missing"]:
        if m["vis"] != VIS_PUBLIC:
            continue
        if m["reason"] == PUBLISHED_UNGRADED and "runs scored" in m["family"]:
            lines.append("- **%s**: published but never graded (%s). Missing: a grade. The settlement "
                         "rule was added after these entries were written and the VOID rows stand "
                         "(see `docs/audit/2026-10-01/LOSS_DIAGNOSIS.md`); CLV would also be refused "
                         "(prop)." % (m["family"], _esc(m["detail"])))
        if m["reason"] == PUBLISHED_NOT_STAKED:
            lines.append("- **%s**: shown as flags only (%s). Missing: a frozen side, price and stake "
                         "rule on the flag, so it can be graded; F5 has no closing-board shape for "
                         "CLV." % (m["family"], _esc(m["detail"])))
    out.extend(lines or ["- None."])
    out.append("")

    out.append("**3. The owner's hypothesis: props may be a better modelling opportunity than "
               "moneylines.** Descriptive, not a finding. Probability quality relative to price is the "
               "paired Brier difference against the market's own frozen probability (ours minus market; "
               "positive = ours worse), from card and shadow rows with n >= 30.")
    out.append("")
    lines = _hypothesis_lines(rows)
    out.extend("- " + ln for ln in lines)
    out.append("")
    return out


def _min_books():
    try:
        from src.report import clv
        return clv.MIN_BOOKS
    except Exception:  # noqa: BLE001
        return 6


def _hypothesis_lines(rows):
    cand = [r for r in rows if r["vis"] in (VIS_PUBLIC, VIS_SHADOW)
            and r["s"]["brier"] is not None and r["s"]["brier"]["n"] >= vs.MIN_N_STAKED
            and r["family"] in ("MLB moneyline", "MLB hitter props: hits",
                                "MLB hitter props: total bases")]
    groups = {"moneyline": [], "props": []}
    for r in cand:
        groups["moneyline" if r["family"] == "MLB moneyline" else "props"].append(r)

    def desc(rs):
        return "; ".join("%s %s n=%d %s%s" % (
            r["rule"], r["market"], r["s"]["brier"]["n"], format(r["s"]["brier"]["diff"], "+.4f"),
            "" if r["s"]["brier"]["se"] is None else " (se %.4f)" % r["s"]["brier"]["se"])
            for r in rs) or "none"
    lines = []
    lines.append("Moneyline rows (n >= 30): %s." % desc(groups["moneyline"]))
    lines.append("Prop rows (n >= 30): %s." % desc(groups["props"]))
    sig = [r for r in cand if r["s"]["brier"]["se"]
           and r["s"]["brier"]["diff"] < -vs.CI_Z * r["s"]["brier"]["se"]]
    better = [r for r in cand if r["s"]["brier"]["diff"] < 0]
    lines.append("Of %d such rows, %d have ours better than the market (negative difference) and %d "
                 "have that difference more than %.2f se below zero." % (
                     len(cand), len(better), len(sig), vs.CI_Z))
    lines.append("Closing price: moneyline CLV is measured on part of the sample; prop CLV is "
                 "never measured (no closing prop board), so for props nothing says whether the "
                 "price taken beat the close.")
    lines.append("Paper: FORWARD_TEST and CONTROL rows freeze no model probability and no paper row "
                 "covers a prop, so paper cannot speak to props or to probability quality; "
                 "MARKET_REFERENCE rows are the market itself.")
    ns = [r["s"]["brier"]["n"] for r in cand]
    lines.append("What the data can say: the Brier differences above, per row, with their standard "
                 "errors. What it cannot say: whether props are the better opportunity. Hit rate and "
                 "ROI at the price taken are not probability quality relative to price; the rows "
                 "carry n = %s over a few weeks of games and share days and games with each other." % (
                     "%d to %d" % (min(ns), max(ns)) if ns else "none"))
    return lines[:8]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Canonical performance matrix (read-only).")
    ap.add_argument("--stdout", action="store_true",
                    help="print the report instead of writing docs/PERFORMANCE_MATRIX.md")
    ap.add_argument("--as-of", metavar="YYYY-MM-DD", default=None,
                    help="ignore entries dated after this day")
    ap.add_argument("--out", default=None, help="output path (default docs/PERFORMANCE_MATRIX.md)")
    ap.add_argument("--evidence-dir", default=None,
                    help="read the ledgers from this directory (default: the repository's)")
    ap.add_argument("--accounts-dir", default=None,
                    help="paper account ledgers directory (default data/paper_accounts)")
    ap.add_argument("--multibook", default=None, help="odds_multibook.jsonl path override")
    ap.add_argument("--event-map", default=None, help="event_game_map.jsonl path override")
    args = ap.parse_args(argv)
    try:
        sources = load_sources(args.evidence_dir, args.accounts_dir, args.multibook,
                               args.event_map, args.as_of)
    except vs.SealedWindowError as exc:
        sys.stderr.write("performance_matrix: refusing to continue: %s\n" % exc)
        return 2
    except AmbiguousJoinError as exc:
        sys.stderr.write("performance_matrix: ambiguous join, stopping: %s\n" % exc)
        return 3
    text = render(build_matrix(sources))
    if args.stdout:
        sys.stdout.write(text)
        return 0
    out = Path(args.out) if args.out else ROOT / "docs" / "PERFORMANCE_MATRIX.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    sys.stdout.write("wrote %s\n" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
