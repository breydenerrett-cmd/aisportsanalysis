"""Run the pre-registered INFO_TIMING_V1 measurement once (docs/PREREG_INFO_TIMING.md).

    python scripts/info_timing_measure.py            # the one registered run
    python scripts/info_timing_measure.py --print    # print an existing artifact

Writes data/research/info_timing/info_timing_result.json and refuses to
overwrite it. Reads no outcome. Every price is a forward capture dated
2026-09-08..2026-10-15; sealed lines are discarded by their date text before
parsing (src.research.info_timing).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.pipeline import rosterwatch  # noqa: E402
from src.research import alpha_registry  # noqa: E402
from src.research import info_timing as it  # noqa: E402

PREREG = os.path.join(ROOT, "docs", "PREREG_INFO_TIMING.md")
REG_ID = "INFO_TIMING:lineup_post_first_capture_clv:hitter_props"
OUT_DIR = os.path.join(ROOT, "data", "research", "info_timing")
OUT = os.path.join(OUT_DIR, "info_timing_result.json")
UNITS_OUT = os.path.join(OUT_DIR, "info_timing_units.jsonl")

P = {
    "watch": os.path.join(ROOT, "data", "watch", "lineups_watch.jsonl"),
    "results": os.path.join(ROOT, "data", "historical", "mlb_results.csv"),
    "event_map": os.path.join(ROOT, "data", "processed", "event_game_map.jsonl"),
    "props": os.path.join(ROOT, "data", "processed", "batter_props.jsonl"),
    "processed": os.path.join(ROOT, "data", "processed"),
    "lineups": os.path.join(ROOT, "data", "historical", "lineups.jsonl"),
    "handedness": os.path.join(ROOT, "data", "historical", "handedness.json"),
    "raw": os.path.join(ROOT, "data", "raw", "oddsapi"),
}


def freeze_check():
    raw = open(PREREG, "rb").read().replace(b"\r\n", b"\n")
    sha = hashlib.sha256(raw).hexdigest()
    rows = [r for r in alpha_registry.read_all()
            if r.get("id") == REG_ID and r.get("kind") == "hypothesis"]
    if len(rows) != 1 or sha not in (rows[0].get("note") or ""):
        raise SystemExit(f"FREEZE CHECK FAILED: sha256 {sha} not on the registration row")
    return sha


def prepare_events(results, by_event, bad_pk, pk_events):
    """Admissible, joinable lineup_posted events, and the exclusion counts."""
    markers, by_game = rosterwatch._split_rows(P["watch"])  # noqa: SLF001
    raw_events = rosterwatch._lineup_events(P["watch"])  # noqa: SLF001
    excl = Counter()
    events = []
    odds_commence_earlier = 0
    for ev in raw_events:
        pk = ev["game_pk"]
        g = results.get(int(pk))
        if g is None:
            excl["NO_GAME_IN_RESULTS"] += 1
            continue
        if not it.in_window(g["date"]):
            excl["OUT_OF_WINDOW"] += 1
            continue
        it.assert_allowed_date(g["date"])
        if ev["inadmissible"]:
            excl["INADMISSIBLE_FIRST_SIGHTING"] += 1
            continue
        if g["double_header"] != "N" or str(pk) in bad_pk:
            excl["AMBIGUOUS_EVENT"] += 1
            continue
        evs = pk_events.get(str(pk)) or set()
        if len(evs) != 1:
            excl["NO_EVENT_MAP"] += 1
            continue
        event_id = next(iter(evs))
        mrow = by_event[event_id]
        starts = [t for t in (it.parse_t(g["start"]),
                              it.parse_t(mrow.get("schedule_commence_time"))) if t]
        if not starts:
            excl["NO_FIRST_PITCH"] += 1
            continue
        fp = min(starts)
        oc = it.parse_t(mrow.get("commence_time"))
        if oc is not None and (fp - oc).total_seconds() > 300:
            odds_commence_earlier += 1
        t_start, t_end = (it.parse_t(x) for x in ev["interval"])
        if t_end >= fp:
            excl["POSTED_AFTER_FIRST_PITCH"] += 1
            continue
        side = ev["detail"]["side"]
        row = next((r for r in by_game.get(pk, []) if r["fetched_utc"] == ev["interval"][1]), None)
        ids = [int(x) for x in (row or {}).get(f"{side}_lineup") or []]
        if len(set(ids)) != it.LINEUP_SIZE or len(ids) != it.LINEUP_SIZE:
            excl["PARTIAL_LINEUP"] += 1
            continue
        events.append({
            "game_pk": int(pk), "side": side, "date": g["date"],
            "game_type": g["game_type"], "team": g[side],
            "opp_side": it.OTHER[side], "event_id": event_id,
            "map_teams": (mrow.get("away_team"), mrow.get("home_team")),
            "t_start": t_start, "t_info": t_end, "first_pitch": fp,
            "ids": ids,
        })
    return events, excl, odds_commence_earlier


def run():
    sha = freeze_check()
    results = it.read_results(P["results"])
    by_event, bad_pk, pk_events = it.read_event_map(P["event_map"])
    events, excl, odds_earlier = prepare_events(results, by_event, bad_pk, pk_events)
    wanted = {e["event_id"] for e in events}

    hist, lineup_names = it.read_lineup_history(P["lineups"], results)
    id_to_name = {int(k): v.get("name") for k, v in
                  json.load(open(P["handedness"], encoding="utf-8")).items() if v.get("name")}
    for pid, n in lineup_names.items():
        id_to_name.setdefault(pid, n)
    names_idx = it.name_index(id_to_name)

    props = it.read_props(P["props"], wanted)
    games, teams = it.read_game_lines(it.multibook_paths(P["processed"]), wanted)

    units, status = [], Counter()
    batter_refusals = Counter()

    def add(unit_base, res):
        status[(unit_base["market"], unit_base["rule"], res["status"])] += 1
        u = dict(unit_base)
        u.update(res)
        units.append(u)

    # ---- R1: posted batter -> Over ------------------------------------
    for e in events:
        ev_props = props.get(e["event_id"]) or {}
        players = sorted({k[0] for k in ev_props})
        matched, refused = it.match_posted(e["ids"], id_to_name, players)
        batter_refusals.update(refused.values())
        batter_refusals["MATCHED"] += len(matched)
        for pid, player in sorted(matched.items()):
            for key in sorted(k for k in ev_props if k[0] == player):
                series = it.build_series(ev_props[key], e["first_pitch"])
                res = it.measure(series, "Over", t_info=e["t_info"], t_pre=e["t_start"],
                                 first_pitch=e["first_pitch"], min_books=it.PROP_MIN_BOOKS,
                                 min_booksum=it.PROP_MIN_BOOKSUM)
                add({"rule": "R1", "market": key[1], "player": player, "line": key[2],
                     "side": "Over", "date": e["date"], "game_type": e["game_type"],
                     "event_key": f"{e['game_pk']}:{e['side']}",
                     "t_info": e["t_info"].isoformat()}, res)

    # ---- R2: quoted batter in neither posted lineup -> Under -------------
    by_pk = defaultdict(dict)
    for e in events:
        by_pk[e["game_pk"]][e["side"]] = e
    r2_status = Counter()
    for pk, sides in sorted(by_pk.items()):
        if set(sides) != {"away", "home"}:
            r2_status["ONE_SIDE_ONLY"] += 1
            continue
        a, h = sides["away"], sides["home"]
        t_both = max(a["t_info"], h["t_info"])
        t_pre = min(a["t_start"], h["t_start"])
        ev_props = props.get(a["event_id"]) or {}
        quoted = sorted({k[0] for k, inst in ev_props.items()
                         if any(t is not None and t <= t_both
                                for t in (it.parse_t(s) for s in inst))})
        lo = it.left_out(quoted, a["ids"] + h["ids"], names_idx)
        r2_status.update(lo.values())
        for player, st in sorted(lo.items()):
            if st != "R2":
                continue
            for key in sorted(k for k in ev_props if k[0] == player):
                series = it.build_series(ev_props[key], a["first_pitch"])
                res = it.measure(series, "Under", t_info=t_both, t_pre=t_pre,
                                 first_pitch=a["first_pitch"], min_books=it.PROP_MIN_BOOKS,
                                 min_booksum=it.PROP_MIN_BOOKSUM)
                add({"rule": "R2", "market": key[1], "player": player, "line": key[2],
                     "side": "Under", "date": a["date"], "game_type": a["game_type"],
                     "event_key": f"{pk}:both", "t_info": t_both.isoformat()}, res)

    # ---- R3: a regular rested -> opponent / Under ------------------------
    r3_status = Counter()
    k_absent_dist = Counter()
    for e in events:
        tset = teams.get(e["event_id"]) or set()
        if tset and tset != {e["map_teams"]}:
            r3_status["SIDE_MISMATCH"] += 1
            continue
        reg = it.regulars(hist, e["team"], e["date"])
        if reg is None:
            r3_status["NO_HISTORY"] += 1
            continue
        k_absent = len(reg - set(e["ids"]))
        k_absent_dist[k_absent] += 1
        if k_absent == 0:
            r3_status["NO_DIRECTION"] += 1
            continue
        r3_status["DIRECTION"] += 1
        g = games.get(e["event_id"]) or {"moneyline": {}, "run_line": {}, "total": {}}
        base = {"rule": "R3", "player": None, "date": e["date"], "game_type": e["game_type"],
                "event_key": f"{e['game_pk']}:{e['side']}", "t_info": e["t_info"].isoformat(),
                "k_absent": k_absent}
        fp = e["first_pitch"]
        series = it.build_series(g["moneyline"], fp)
        res = it.measure(series, e["opp_side"], t_info=e["t_info"], t_pre=e["t_start"],
                         first_pitch=fp, min_books=it.GAME_MIN_BOOKS)
        add(dict(base, market="moneyline", line=None, side=e["opp_side"]), res)
        for market, side, prefer in (("run_line", e["opp_side"], lambda L: L),
                                     ("total", "Under", lambda L: L)):
            by_line = it.build_series(g[market], fp)
            line = it.pick_line(by_line, side, lambda bl: sorted(bl), t_info=e["t_info"],
                                min_books=it.GAME_MIN_BOOKS, prefer=prefer)
            if line is None:
                add(dict(base, market=market, line=None, side=side), {"status": "NO_ENTRY_CAPTURE"})
                continue
            series = [(t, bl.get(line, {})) for t, bl in by_line]
            res = it.measure(series, side, t_info=e["t_info"], t_pre=e["t_start"],
                             first_pitch=fp, min_books=it.GAME_MIN_BOOKS)
            if res["status"] == "NO_LATER_CAPTURE":
                entry_t = next(t for t, bl in by_line if t > e["t_info"] and
                               it.consensus(bl.get(line, {}), side, min_books=it.GAME_MIN_BOOKS))
                later_other = any(
                    t > entry_t and any(it.consensus(b, side, min_books=it.GAME_MIN_BOOKS)
                                        for L, b in bl.items() if L != line)
                    for t, bl in by_line)
                if later_other:
                    res = dict(res, status="LINE_ABSENT_AT_CLOSE")
            # run line: the opponent's own line value, for the record
            shown = (line if side == "home" else -line) if market == "run_line" else line
            add(dict(base, market=market, line=shown, side=side), res)

    # ---- Coverage and cadence (every admissible joinable posting) --------
    prop_lags, game_lags, lead, width = [], [], [], []
    prop_lags_captured_games = []
    prop_cad, game_cad = [], []
    for e in events:
        fp, ti = e["first_pitch"], e["t_info"]
        lead.append(it.minutes(ti, fp))
        width.append(it.minutes(e["t_start"], ti))
        p_inst = sorted({it.parse_t(s) for k in (props.get(e["event_id"]) or {})
                         for s in props[e["event_id"]][k]} - {None})
        p_inst = [t for t in p_inst if t < fp]
        g = games.get(e["event_id"]) or {}
        g_inst = sorted({it.parse_t(s) for m in ("moneyline", "run_line", "total")
                         for s in (g.get(m) or {})} - {None})
        g_inst = [t for t in g_inst if t < fp]
        pl = next((it.minutes(ti, t) for t in p_inst if t > ti), None)
        gl = next((it.minutes(ti, t) for t in g_inst if t > ti), None)
        prop_lags.append(pl)
        game_lags.append(gl)
        if p_inst:
            prop_lags_captured_games.append(pl)
        win = [t for t in p_inst if it.minutes(t, fp) <= it.CADENCE_WINDOW_MIN]
        if len(win) >= 2:
            prop_cad.append(it.median_gap(win))
        win = [t for t in g_inst if it.minutes(t, fp) <= it.CADENCE_WINDOW_MIN]
        if len(win) >= 2:
            game_cad.append(it.median_gap(win))

    raw = it.raw_capture_instants(P["raw"])
    proc_prop_inst = sorted({it.parse_t(s) for ev in props.values() for k in ev for s in ev[k]} - {None})
    proc_game_inst = sorted({it.parse_t(s) for ev in games.values()
                             for m in ("moneyline", "run_line", "total") for s in ev[m]} - {None})

    # ---- Summaries ------------------------------------------------------
    ok = [u for u in units if u["status"] == "OK"]
    hitter = [u for u in ok if u["market"] in it.PROP_MARKETS]
    groups = {"hitter_props_pooled": hitter}
    for m in it.PROP_MARKETS + it.GAME_MARKETS:
        groups[m] = [u for u in ok if u["market"] == m]
    for r in ("R1", "R2"):
        groups[f"hitter_props_{r}"] = [u for u in hitter if u["rule"] == r]
    groups["hitter_props_regular_season"] = [u for u in hitter if u["game_type"] == "R"]
    groups["hitter_props_postseason"] = [u for u in hitter if u["game_type"] != "R"]
    summary = {}
    for name, rows in groups.items():
        summary[name] = {k: it.summarize(rows, k) for k in ("m1", "m2", "m2_best", "pre_move")}
        summary[name]["lag_min"] = it.quantiles([u["lag_min"] for u in rows])
        summary[name]["close_to_pitch_min"] = it.quantiles([u["close_to_pitch_min"] for u in rows])

    verdict = it.decide(summary["hitter_props_pooled"]["m1"], summary["hitter_props_pooled"]["m2"])
    out = {
        "registration": REG_ID, "freeze_sha256": sha, "window": [it.WINDOW_FIRST, it.WINDOW_LAST],
        "verdict": verdict, "registry_result": it.REGISTRY_RESULT[verdict],
        "events": {"admissible_joinable": len(events), "excluded": dict(excl),
                   "by_side_dates": len({e["date"] for e in events}),
                   "odds_commence_earlier_than_mlb_by_5min": odds_earlier},
        "coverage": {
            "prop_capture_after_post": it.lag_coverage(prop_lags, len(events)),
            "prop_capture_after_post_games_with_any_prop_capture":
                it.lag_coverage(prop_lags_captured_games, len(prop_lags_captured_games)),
            "game_line_capture_after_post": it.lag_coverage(game_lags, len(events)),
            "post_to_first_pitch_min": it.quantiles(lead),
            "bracket_width_min": it.quantiles(width),
            "prop_cadence_median_gap_min_last_6h": it.quantiles(prop_cad),
            "game_cadence_median_gap_min_last_6h": it.quantiles(game_cad),
        },
        "raw_reconciliation": {
            "prop_instants": len(proc_prop_inst),
            "prop_instants_with_raw_event_envelope_5min": it.share_matched(proc_prop_inst, raw["event"]),
            "game_instants": len(proc_game_inst),
            "game_instants_with_raw_featured_envelope_5min": it.share_matched(proc_game_inst, raw["featured"]),
            "raw_event_envelopes": len(raw["event"]), "raw_featured_envelopes": len(raw["featured"]),
        },
        "unit_status": {"|".join(map(str, k)): v for k, v in sorted(status.items())},
        "r1_batter_matching": dict(batter_refusals),
        "r2_player_status": dict(r2_status),
        "r3_event_status": dict(r3_status),
        "r3_k_absent_distribution": {str(k): v for k, v in sorted(k_absent_dist.items())},
        "summary": summary,
    }
    return out, units


def describe():
    """Post-run, DESCRIPTIVE only (added after the registered run; changes no
    registered number): how many prop captures each joinable posting had after
    it, and how many each game had in total. Prints; writes nothing."""
    results = it.read_results(P["results"])
    by_event, bad_pk, pk_events = it.read_event_map(P["event_map"])
    events, _, _ = prepare_events(results, by_event, bad_pk, pk_events)
    props = it.read_props(P["props"], {e["event_id"] for e in events})
    after, per_game = Counter(), {}
    for e in events:
        inst = sorted({t for k in (props.get(e["event_id"]) or {})
                       for t in (it.parse_t(s) for s in props[e["event_id"]][k])
                       if t is not None and t < e["first_pitch"]})
        per_game[e["event_id"]] = len(inst)
        after[sum(1 for t in inst if t > e["t_info"])] += 1
    print("joinable postings by number of pre-pitch prop captures after the posting:",
          dict(sorted(after.items())))
    print("joinable games by number of pre-pitch prop captures in total:",
          dict(sorted(Counter(per_game.values()).items())))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    ap.add_argument("--describe", action="store_true",
                    help="post-run descriptive capture counts; writes nothing")
    args = ap.parse_args(argv)
    if args.print:
        print(open(OUT, encoding="utf-8").read())
        return 0
    if args.describe:
        return describe()
    if os.path.exists(OUT):
        print(f"REFUSED: {OUT} exists; one registered run.")
        return 2
    out, units = run()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, default=str)
        fh.write("\n")
    with open(UNITS_OUT, "w", encoding="utf-8", newline="\n") as fh:
        for u in units:
            if u["status"] != "OK":
                continue  # exclusions are counted in the artifact's unit_status
            fh.write(json.dumps(u, sort_keys=True, default=str) + "\n")
    s = out["summary"]["hitter_props_pooled"]
    print("verdict:", out["verdict"])
    print("hitter M1:", s["m1"]); print("hitter M2:", s["m2"])
    print("coverage props:", out["coverage"]["prop_capture_after_post"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
