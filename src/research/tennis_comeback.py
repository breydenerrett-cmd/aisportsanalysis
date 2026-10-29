"""Tennis comeback table: when the pre-match favourite loses set 1, how often do they still win the match?

Source: the free tennis-data.co.uk yearly files (ATP and WTA), saved by hand under
data/research/tennis_history/raw/ (see that folder's README). They are UNTRUSTED DATA: this module only reads
them as spreadsheets (openpyxl, or pandas for old .xls) and never executes, imports or extracts anything from
them. Zip members are read into memory, never written to disk.

What it measures (descriptive only -- it never claims an edge):
  * favourite = the player with the shorter closing price; their pre-match win probability is the de-vigged
    proportional probability from Pinnacle (PSW/PSL) when both are present, else the average (AvgW/AvgL);
  * cells = favourite probability band (5 percentage points) x best-of-3/best-of-5 x ATP/WTA;
  * per cell: n matches where the favourite lost set 1, how many they won, the Wilson 95% interval, the
    independent-sets model value (per-set p solved from each match's pre-match probability), and the minimum
    live American price worth taking = the observed rate at break-even plus a 3% margin.

Rows dropped, and counted: retirements, walkovers and anything not marked Completed; missing or ambiguous odds;
a pick-em (no favourite); unreadable set scores; a set-count that contradicts the best-of; and (sealed-data
guard) any row dated 2026-01-01..2026-08-27, with whole files for year 2026 skipped unread.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

SCHEMA = "tennis_comeback_table_v1"
BAND_PP = 5
Z95 = 1.959964
MARGIN = 0.03
MIN_N_FOR_PRICE = 30
SEALED_START = date(2026, 1, 1)
SEALED_END = date(2026, 8, 27)
MAX_MEMBER_BYTES = 60 * 1024 * 1024

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data" / "research" / "tennis_history" / "raw"
OUT_JSON = REPO / "evidence" / "tennis_comeback_table_v1.json"
OUT_MD = REPO / "docs" / "research" / "TENNIS_COMEBACK_TABLE.md"

HEADLINE_BANDS = {("ATP", 3): (60, 70, 80), ("WTA", 3): (60, 70, 80), ("ATP", 5): (70, 80)}


# ---------------------------------------------------------------- maths

def wilson(k: int, n: int, z: float = Z95):
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def match_prob(p: float, best_of: int) -> float:
    q = 1 - p
    if best_of == 3:
        return p * p * (1 + 2 * q)
    if best_of == 5:
        return p ** 3 * (1 + 3 * q + 6 * q * q)
    raise ValueError(best_of)


def solve_set_prob(m: float, best_of: int) -> float:
    """Per-set probability p such that the independent-sets match probability equals m (monotone: bisection)."""
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if match_prob(mid, best_of) < m:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def model_comeback(m: float, best_of: int) -> float:
    """P(win the match | lost set 1) under independent sets with the p implied by pre-match probability m."""
    p = solve_set_prob(m, best_of)
    return p * p if best_of == 3 else p ** 3 * (4 - 3 * p)


def american_from_decimal(d: float) -> int:
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def min_live_price(rate: float | None):
    """Break-even decimal payout 1/rate, plus a 3% margin on the payout: d = (1 + MARGIN) / rate."""
    if not rate or rate <= 0:
        return None
    d = (1 + MARGIN) / rate
    if d <= 1:
        return None
    return american_from_decimal(d)


def band_of(p: float):
    lo = int(math.floor(p * 100 / BAND_PP + 1e-9)) * BAND_PP
    return lo, lo + BAND_PP


# ---------------------------------------------------------------- reading (untrusted spreadsheets)

def _num(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _date(x):
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str):
        for f in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(x.strip(), f).date()
            except ValueError:
                pass
    return None


def _rows_from_workbook_bytes(data: bytes, name: str):
    """List of lower-cased-header dicts from every sheet; raises RuntimeError if the format can't be read."""
    out = []
    if name.lower().endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError as e:
            raise RuntimeError("openpyxl is not installed") from e
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            head = next(it, None)
            if not head:
                continue
            keys = [str(h).strip().lower() if h is not None else "" for h in head]
            for r in it:
                out.append({k: v for k, v in zip(keys, r) if k})
        wb.close()
        return out
    if name.lower().endswith(".xls"):
        try:
            import pandas as pd
            frames = pd.read_excel(io.BytesIO(data), sheet_name=None)
        except Exception as e:  # missing pandas/xlrd or corrupt file: reported, never fatal
            raise RuntimeError(f"cannot read .xls ({type(e).__name__}): needs pandas+xlrd") from e
        for df in frames.values():
            df.columns = [str(c).strip().lower() for c in df.columns]
            for rec in df.astype(object).where(df.notna(), None).to_dict("records"):
                out.append(rec)
        return out
    raise RuntimeError("unsupported member type")


def _tour_of(path: Path, root: Path):
    rel = [p.lower() for p in path.relative_to(root).parts]
    for part in rel:
        if part.startswith("atp"):
            return "ATP"
        if part.startswith("wta"):
            return "WTA"
    return None


def _year_of(name: str):
    m = re.search(r"(19|20)\d\d", name)
    return int(m.group(0)) if m else None


def load_raw(raw_dir: Path = RAW_DIR):
    """-> (rows, files, problems). rows are dicts with an added 'tour' and 'src_file'."""
    rows, files, problems = [], [], []
    raw_dir = Path(raw_dir)
    if not raw_dir.exists():
        return rows, files, [f"raw directory missing: {raw_dir}"]
    for path in sorted(p for p in raw_dir.rglob("*") if p.is_file()):
        low = path.name.lower()
        if low.endswith(".md") or low == ".gitkeep":
            continue
        tour = _tour_of(path, raw_dir)
        if tour is None:
            problems.append(f"{path.name}: filename/folder must start with atp or wta; skipped")
            continue
        year = _year_of(path.name)
        if year == 2026:
            problems.append(f"{path.name}: year 2026 file skipped unread (sealed-data guard)")
            continue
        blob = path.read_bytes()
        entry = {"file": path.relative_to(raw_dir).as_posix(), "tour": tour, "bytes": len(blob),
                 "sha256": hashlib.sha256(blob).hexdigest()}
        members = []
        if low.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                    for info in zf.infolist():
                        mname = info.filename
                        if mname.endswith("/") or ".." in mname or mname.startswith(("/", "\\")):
                            continue
                        if not mname.lower().endswith((".xlsx", ".xls")):
                            continue
                        if info.file_size > MAX_MEMBER_BYTES:
                            problems.append(f"{path.name}:{mname}: member too large; skipped")
                            continue
                        members.append((mname, zf.read(info)))
            except zipfile.BadZipFile:
                problems.append(f"{path.name}: not a valid zip; skipped")
                continue
        elif low.endswith((".xlsx", ".xls")):
            members.append((path.name, blob))
        else:
            problems.append(f"{path.name}: unsupported file type; skipped")
            continue
        n_before = len(rows)
        for mname, mbytes in members:
            if _year_of(mname) == 2026:
                problems.append(f"{path.name}:{mname}: year 2026 member skipped unread (sealed-data guard)")
                continue
            try:
                for r in _rows_from_workbook_bytes(mbytes, mname):
                    r["tour"] = tour
                    r["src_file"] = entry["file"]
                    rows.append(r)
            except Exception as e:
                problems.append(f"{path.name}:{mname}: unreadable ({e}); skipped")
        entry["rows"] = len(rows) - n_before
        files.append(entry)
    return rows, files, problems


# ---------------------------------------------------------------- cleaning

def _odds_pair(r):
    for src, w, l in (("PS", "psw", "psl"), ("Avg", "avgw", "avgl")):
        ow, ol = _num(r.get(w)), _num(r.get(l))
        if ow and ol and ow > 1 and ol > 1:
            return src, ow, ol
    return None, None, None


def clean_match(r):
    """One raw row -> (record | None, drop_reason | None)."""
    d = _date(r.get("date"))
    if d is None:
        return None, "no_date"
    if SEALED_START <= d <= SEALED_END:
        return None, "sealed_dates"
    txt = str(r.get("comment")).strip().lower() if r.get("comment") is not None else ""
    if txt != "completed":
        if txt.startswith(("retir", "walk", "w/o")) or txt in ("disqualified", "def"):
            return None, "retirement_or_walkover"
        return None, "not_marked_completed"
    best_of = _num(r.get("best of"))
    if best_of not in (3.0, 5.0):
        return None, "no_best_of"
    best_of = int(best_of)
    w1, l1 = _num(r.get("w1")), _num(r.get("l1"))
    if w1 is None or l1 is None or w1 == l1:
        return None, "no_set1_score"
    ws, ls = _num(r.get("wsets")), _num(r.get("lsets"))
    need = 2 if best_of == 3 else 3
    if ws is not None and ls is not None and (ws != need or ls >= need):
        return None, "set_count_contradicts_best_of"
    src, ow, ol = _odds_pair(r)
    if src is None:
        return None, "no_odds"
    iw, il = 1 / ow, 1 / ol
    pw = iw / (iw + il)
    if abs(pw - 0.5) < 1e-12:
        return None, "pick_em_no_favourite"
    fav_is_winner = pw > 0.5
    pf = pw if fav_is_winner else 1 - pw
    winner_won_set1 = w1 > l1
    fav_won_set1 = (fav_is_winner == winner_won_set1)
    return {"tour": r["tour"], "best_of": best_of, "pf": pf, "odds_src": src, "fav_won_set1": fav_won_set1,
            "fav_won_match": fav_is_winner, "date": d.isoformat()}, None


# ---------------------------------------------------------------- aggregation

def build_table(rows):
    drops: dict = {}
    cells: dict = {}
    kept = 0
    src_counts = {"PS": 0, "Avg": 0}
    for r in rows:
        rec, why = clean_match(r)
        if rec is None:
            drops[why] = drops.get(why, 0) + 1
            continue
        kept += 1
        src_counts[rec["odds_src"]] += 1
        lo, hi = band_of(rec["pf"])
        key = (rec["tour"], rec["best_of"], lo)
        c = cells.setdefault(key, {"matches": 0, "n": 0, "k": 0, "model_sum": 0.0, "pf_sum": 0.0})
        c["matches"] += 1
        if rec["fav_won_set1"]:
            continue
        c["n"] += 1
        c["k"] += 1 if rec["fav_won_match"] else 0
        c["model_sum"] += model_comeback(rec["pf"], rec["best_of"])
        c["pf_sum"] += rec["pf"]
    out = []
    for (tour, bo, lo), c in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        n, k = c["n"], c["k"]
        rate = k / n if n else None
        wl, wh = wilson(k, n)
        model = c["model_sum"] / n if n else None
        price_ok = n >= MIN_N_FOR_PRICE
        cell = {
            "tour": tour, "best_of": bo, "band": f"{lo}-{lo + BAND_PP}%", "band_lo_pp": lo,
            "matches": c["matches"], "n_lost_set1": n, "fav_lost_set1_share": (n / c["matches"]) if c["matches"] else None,
            "won_match": k, "rate": rate, "wilson95_lo": wl, "wilson95_hi": wh,
            "mean_prematch_prob": (c["pf_sum"] / n) if n else None,
            "independent_sets_model": model,
            "rate_minus_model_pp": ((rate - model) * 100) if n else None,
            "interval_excludes_model": (bool(model < wl or model > wh) if n else None),
            "direction": (None if not n else "below_model" if rate < model else "above_model"),
            "min_live_price_point": min_live_price(rate) if price_ok else None,
            "min_live_price_wilson_lo": min_live_price(wl) if price_ok else None,
            "n_floor_met": price_ok,
        }
        out.append(cell)
    return {"cells": out, "kept": kept, "drops": dict(sorted(drops.items())), "odds_source_counts": src_counts}


def novak_example(cells, pre_match_american=-300):
    """The Novak case: favourite at about -300 pre-match (raw implied 75%) then loses set 1. Illustration only:
    the quoted price is taken as a de-vigged 75% because a single American price carries no vig information."""
    imp = -pre_match_american / (-pre_match_american + 100)
    lo = band_of(imp)[0]
    rows = []
    for c in cells:
        if c["band_lo_pp"] == lo and c["tour"] == "ATP":
            rows.append(c)
    return {"pre_match_american": pre_match_american, "implied_prob": imp, "band": f"{lo}-{lo + BAND_PP}%", "cells": rows}


def summarise(cells):
    scored = [c for c in cells if c["n_floor_met"]]
    excl = [c for c in scored if c["interval_excludes_model"]]
    below = [c for c in excl if c["direction"] == "below_model"]
    above = [c for c in excl if c["direction"] == "above_model"]
    return {"cells_total": len(cells), "cells_n_ge_floor": len(scored), "n_floor": MIN_N_FOR_PRICE,
            "interval_excludes_model": len(excl), "excluded_below_model": len(below), "excluded_above_model": len(above),
            "expected_by_chance_at_5pct": round(0.05 * len(scored), 2)}


def headline(cells):
    sel = []
    for (tour, bo), bands in HEADLINE_BANDS.items():
        for lo in bands:
            hit = [c for c in cells if (c["tour"], c["best_of"], c["band_lo_pp"]) == (tour, bo, lo)]
            if hit:
                sel.append(hit[0])
    return sel


def build(raw_dir: Path = RAW_DIR, out_json: Path = OUT_JSON, out_md: Path = OUT_MD, write: bool = True):
    rows, files, problems = load_raw(raw_dir)
    table = build_table(rows)
    cells = table["cells"]
    result = {
        "schema": SCHEMA,
        "status": "ok" if cells else "no_input",
        "descriptive_only": True,
        "no_edge_claim": "Observed historical frequencies. Nothing here compares to any live price; no edge is claimed.",
        "method": {
            "favourite_probability": "proportional de-vig of Pinnacle PSW/PSL closing odds, else AvgW/AvgL",
            "bands": f"{BAND_PP} percentage points of favourite probability, 50-100%",
            "wilson": "95% Wilson score interval",
            "model": "independent sets; per-set p solved per match from its pre-match probability, then "
                     "P(win | lost set 1) = p^2 (best of 3) or p^3(4-3p) (best of 5), averaged over the cell",
            "min_live_price": f"decimal payout (1+{MARGIN})/rate, i.e. break-even plus a {int(MARGIN * 100)}% margin "
                              f"on the payout; shown only when n >= {MIN_N_FOR_PRICE}; second column uses the Wilson lower bound",
            "dropped": "retirements, walkovers and anything not marked Completed; see drops",
            "sealed_guard": "2026 files skipped unread; rows dated 2026-01-01..2026-08-27 dropped",
        },
        "inputs": files,
        "data_problems": problems,
        "matches_kept": table["kept"],
        "drops": table["drops"],
        "odds_source_counts": table["odds_source_counts"],
        "summary": summarise(cells),
        "headline": headline(cells),
        "novak_example": novak_example(cells),
        "cells": cells,
    }
    if write:
        out_json = Path(out_json)
        out_md = Path(out_md)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        out_md.write_text(render_md(result), encoding="utf-8")
    return result


# ---------------------------------------------------------------- report

def _pct(x):
    return "-" if x is None else f"{x * 100:.1f}%"


def _px(x):
    return "n/a (n too small)" if x is None else (f"+{x}" if x > 0 else str(x))


def _row(c):
    ci = "-" if c["wilson95_lo"] is None else f"{_pct(c['wilson95_lo'])} to {_pct(c['wilson95_hi'])}"
    mark = ""
    if c["interval_excludes_model"]:
        mark = " (outside model)"
    return (f"| {c['tour']} | best of {c['best_of']} | {c['band']} | {c['n_lost_set1']} | {_pct(c['rate'])} | {ci} | "
            f"{_pct(c['independent_sets_model'])}{mark} | {_px(c['min_live_price_point'])} | {_px(c['min_live_price_wilson_lo'])} |")


HEAD = ("| Tour | Format | Favourite before the match | Times fav lost set 1 (n) | Won the match anyway | "
        "95% range | Independent-sets model | Min live price (observed rate) | Min live price (cautious end) |\n"
        "|---|---|---|---|---|---|---|---|---|")


def render_md(r) -> str:
    L = ["# Tennis comeback table: favourite loses set 1, then what?", ""]
    if r["status"] != "ok":
        L += ["**No table was built: there were no usable input files.** Nothing below is a result.", "",
              "The yearly ATP and WTA spreadsheets from tennis-data.co.uk have to be saved by hand into "
              "`data/research/tennis_history/raw/` (see the README there), then run "
              "`python -m src.cli research tennis-comeback build`.", ""]
        for p in r["data_problems"]:
            L.append(f"- {p}")
        return "\n".join(L) + "\n"
    s = r["summary"]
    L += [
        "## In plain English", "",
        "Take every completed pro tennis match from the free tennis-data.co.uk history where we know the closing "
        "betting odds. Find the favourite (the player the market made more likely to win before the first ball). "
        "Look only at matches where that favourite then **lost the first set**. How often did they still win the match?", "",
        "We group favourites by how likely the market thought they were (in bands 5 points wide), and keep best-of-3 "
        "and best-of-5 matches, and men (ATP) and women (WTA), separate. For each group we show how many matches it "
        "is built on (n), the share the favourite won anyway, and a 95% range that says how much that share could "
        "move just from luck in a small group.", "",
        "We also show what a simple textbook model would say: if every set were an independent coin flip weighted so the "
        "favourite wins the match at the pre-match price, how often would they come back after losing set 1?", "",
        "**This is a history table, not a betting tip.** It does not look at any live price, so it cannot say any price "
        "is good value or that there is an edge. The 'minimum live price' columns only say: if the real comeback rate "
        "is what this history shows, a live price at least that generous would break even plus a 3% cushion. "
        "Small groups are shown but get no price. Where history and the model disagree, that is a description of the past, "
        "not a signal.", "",
        "## Headline rows", "", HEAD]
    L += [_row(c) for c in r["headline"]]
    L += ["", f"Rows missing here have no matches in that group. Full table below ({s['cells_total']} groups).", ""]
    ex = r["novak_example"]
    L += ["## The Novak example", "",
          f"A -300 favourite (about {_pct(ex['implied_prob'])} before the match, treated as already de-vigged) loses set 1 "
          f"of a best-of-5 (ATP band {ex['band']}):", ""]
    ex5 = [c for c in ex["cells"] if c["best_of"] == 5]
    ex3 = [c for c in ex["cells"] if c["best_of"] == 3]
    if ex5:
        c = ex5[0]
        L += [HEAD, _row(c), "",
              f"History says the favourite came back {_pct(c['rate'])} of the time (n={c['n_lost_set1']}). "
              f"A live price shorter than {_px(c['min_live_price_point'])} would be paying less than that history "
              f"plus the 3% cushion; this is a statement about the past table, not a recommendation.", ""]
    else:
        L += ["No best-of-5 group in that band in the data.", ""]
    if ex3:
        L += ["For comparison, the same favourite probability in best-of-3:", "", HEAD, _row(ex3[0]), ""]
    L += ["## Did anything stand out?", "",
          f"{s['cells_n_ge_floor']} groups have at least {s['n_floor']} matches. In {s['interval_excludes_model']} of them "
          f"the 95% range does not contain the independent-sets model "
          f"({s['excluded_below_model']} below the model, {s['excluded_above_model']} above). "
          f"With that many groups, about {s['expected_by_chance_at_5pct']} would be expected to miss by pure chance, "
          "so a few misses are not a finding. Groups are not independent (neighbouring bands share the same kind of match), "
          "and nothing here was corrected or tested as a pre-registered hypothesis. Treat the table as a description; "
          "any use as a signal would need its own pre-registered test on fresh data.", ""]
    L += ["## Full table (every group, wins and losses alike)", "", HEAD]
    L += [_row(c) for c in r["cells"]]
    L += ["", "## What was dropped", "",
          f"Matches kept: {r['matches_kept']}. Odds used: Pinnacle {r['odds_source_counts']['PS']}, average {r['odds_source_counts']['Avg']}.", ""]
    for k, v in r["drops"].items():
        L.append(f"- {k}: {v}")
    L += ["", "## Data problems", ""]
    L += [f"- {p}" for p in r["data_problems"]] or ["- none recorded"]
    L += ["", "## Method notes", ""]
    for k, v in r["method"].items():
        L.append(f"- {k}: {v}")
    return "\n".join(L) + "\n"
