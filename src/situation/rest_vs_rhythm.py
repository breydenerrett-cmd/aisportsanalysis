"""The first factor test: rest versus rhythm in the Division Series.

THE QUESTION (stated in `docs/research/SITUATION_REST_VS_RHYTHM_DIVISION_SERIES.md` before any
outcome was read)
-----------------------------------------------------------------------------------------
In a Division Series between a club that had a BYE (it did not play the Wild Card round) and a club
that PLAYED it, does the bye club do worse than its regular-season strength and home field predict
(rest costs rhythm), or better (rest helps), or the same? "Momentum over rest" is the first of
those; the conventional view is the second; the null is that neither matters beyond what the
standings already say.

THE DESIGN, IN ONE PARAGRAPH
----------------------------
For every Division Series in the data, 2015 to 2025, where exactly one club had a bye (a series
with two rested clubs, as the Wild Card game's single-game format produced for the other two
division winners, or two clubs that played, as in 2020, has no contrast and is excluded and
listed): record the bye club's Game 1 result and its series result. Compare each with what the two
clubs' regular-season win rates and home field predict, game by game for Game 1 and through the
whole best-of-five for the series. The prediction is a plain log5 on regular-season win rate with
a home-field edge (`HOME_FIELD_WIN_RATE`, fixed in advance) and the series' own home pattern, so it
credits the bye club for being the better club and for hosting. What is left over, observed minus
expected wins, is the measured effect of rest. A two-sided exact test (the Poisson-binomial
distribution of the number of bye-club wins if every game or series is won with its predicted
probability) says how surprising the left-over is.

WHAT THE SAMPLE CAN AND CANNOT DO
---------------------------------
Twenty-eight series. The number of bye-club series wins has a standard deviation of roughly 2.6
under the null, so only a swing of about eighteen points in series win probability would reach
p = 0.05. A null here means "this sample could not see an effect of ordinary size", never "rest
does not matter". `summary.detectable` states the number for the sample actually run.

NO PRICE IS INVENTED. The market's price for each Game 1 is joined from `prices` when one is
supplied; none is for any 2015 to 2025 series, because our closing moneylines exist for 2026 only,
and the report says so instead of leaving a column of blanks. The first series that can carry a
price is the 2026 Division Series.

Pure given the rows it is handed: no I/O, no clock. The CLI (`cli.py`) loads the stores.
"""

from __future__ import annotations

import math
from itertools import product
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.data import parks
from src.situation import series as ser

# The home win rate between two equal clubs, fixed before any postseason outcome was read. It is the
# regular-season home win rate of the three seasons the results store holds, 2023 to 2025
# (.521, .522 and .543 over 7,285 games, .529 together), rounded; the earlier seasons' regular
# seasons are not in the data here and were not measured. One number for every game of every season,
# so that no season's own result chooses its own yardstick. (A first draft said 0.54 and called it
# the recent seasons' round figure; it was checked against the store before any outcome was read and
# did not match, so it was changed.)
HOME_FIELD_WIN_RATE = 0.53

FIRST_SEASON, LAST_SEASON = 2015, 2025
# Games of a best-of-five hosted by the club with home field (2-2-1): games 1, 2 and 5.
HOME_PATTERN = (True, True, False, False, True)
DS_WINS_NEEDED = 3
SIGNIFICANCE = 0.05
# The one sensitivity run, declared before the numbers: both clubs' win rates pulled this far back
# toward .500 before the prediction. An assumption, labelled as one; the primary result uses none.
SENSITIVITY_SHRINK = 1.0 / 3.0


# ---------------------------------------------------------------------------
# the yardstick
# ---------------------------------------------------------------------------

def log5(pa: float, pb: float) -> float:
    """The chance club A beats club B on neutral ground, from their win rates (Bill James's log5)."""
    if not (0.0 < pa < 1.0 and 0.0 < pb < 1.0):
        raise ValueError(f"win rates must be strictly between 0 and 1, got {pa} and {pb}")
    return (pa - pa * pb) / (pa + pb - 2.0 * pa * pb)


def with_home_field(p_neutral: float, home: bool, h: float = HOME_FIELD_WIN_RATE) -> float:
    """The chance the club wins a game, given its neutral-ground chance and whether it is at home.
    The home edge is applied to the odds: two equal clubs give the home one `h`."""
    odds = p_neutral / (1.0 - p_neutral)
    factor = h / (1.0 - h)
    odds = odds * factor if home else odds / factor
    return odds / (1.0 + odds)


def series_win_probability(p_by_game: Sequence[float], wins_needed: int = DS_WINS_NEEDED) -> float:
    """The chance club X wins a series, first to `wins_needed`, if it wins game i with probability
    `p_by_game[i]` independently. Exact: the open (wins, losses) states are carried game by game and
    a series stops counting the moment either club has the wins, so a game that would not be played
    is never in the sum. Needs enough games to decide any series (five for a best-of-five)."""
    if len(p_by_game) < 2 * wins_needed - 1:
        raise ValueError(f"{len(p_by_game)} games cannot decide a first-to-{wins_needed} series")
    open_states = {(0, 0): 1.0}
    won_series = 0.0
    for p in p_by_game:
        nxt: dict = {}
        for (mine, theirs), prob in open_states.items():
            for won, chance in ((1, p), (0, 1.0 - p)):
                m, t, q = mine + won, theirs + (1 - won), prob * chance
                if m == wins_needed:
                    won_series += q
                elif t == wins_needed:
                    continue
                else:
                    nxt[(m, t)] = nxt.get((m, t), 0.0) + q
        open_states = nxt
    return won_series


def poisson_binomial_pmf(ps: Sequence[float]) -> List[float]:
    """P(X = k), k = 0..n, for X the number of successes among independent trials with chances `ps`."""
    pmf = [1.0]
    for p in ps:
        nxt = [0.0] * (len(pmf) + 1)
        for k, mass in enumerate(pmf):
            nxt[k] += mass * (1.0 - p)
            nxt[k + 1] += mass * p
        pmf = nxt
    return pmf


def two_sided_p(ps: Sequence[float], observed: int) -> float:
    """The exact two-sided p-value for `observed` successes: twice the smaller tail, capped at one."""
    pmf = poisson_binomial_pmf(ps)
    lower = sum(pmf[: observed + 1])
    upper = sum(pmf[observed:])
    return min(1.0, 2.0 * min(lower, upper))


# ---------------------------------------------------------------------------
# the records and the pairs
# ---------------------------------------------------------------------------

def _canon(team: Any) -> str:
    try:
        return parks.canonical_team(team)
    except parks.ParkError:
        return str(team or "").strip().upper()


def records_from_games(rows: Iterable[Mapping]) -> Dict[Tuple[int, str], dict]:
    """Each club's regular-season record per season from regular-season game rows."""
    out: Dict[Tuple[int, str], dict] = {}
    seen = set()
    for row in rows:
        if row.get("game_type") != ser.REGULAR:
            continue
        pk = str(row.get("game_pk") or "")
        if pk and pk in seen:
            continue
        seen.add(pk)
        a, h = ser.runs_of(row)
        d = ser.row_date(row)
        if a is None or h is None or a == h or d is None:
            continue
        season = int(d[:4])
        away, home = _canon(row.get("away_team")), _canon(row.get("home_team"))
        for team, won in ((away, a > h), (home, h > a)):
            rec = out.setdefault((season, team), {"wins": 0, "losses": 0})
            rec["wins" if won else "losses"] += 1
    return out


def _normalized(rows: Iterable[Mapping]) -> list:
    out = {}
    for row in rows:
        if row.get("game_type") not in ser.POSTSEASON_TYPES or ser.row_date(row) is None:
            continue
        copy = dict(row)
        copy["away_team"], copy["home_team"] = _canon(row.get("away_team")), _canon(row.get("home_team"))
        out[str(row.get("game_pk") or id(row))] = copy
    return list(out.values())


def _win_pct(records: Mapping, season: int, team: str) -> Optional[float]:
    rec = records.get((season, team))
    if not rec or rec.get("wins") is None or rec.get("losses") is None:
        return None
    n = rec["wins"] + rec["losses"]
    return rec["wins"] / n if n else None


def qualifying_series(games: Iterable[Mapping], records: Mapping, *, seasons: Sequence[int]) -> tuple:
    """`(pairs, excluded)`: every Division Series in `seasons` and what became of it.

    A series qualifies when exactly one club had a bye and the other played the Wild Card round, the
    series is complete and both clubs have a regular-season record. Everything else is in
    `excluded` with its reason (`both_rested`, `both_played`, `round_incomplete`, `series_open`,
    `no_record`), so nothing leaves the sample unseen.
    """
    rows = _normalized(games)
    all_series = ser.build_series(rows)
    pairs, excluded = [], []
    for s in all_series:
        if s.game_type != "D" or s.season not in seasons:
            continue
        a, b = s.teams
        status = {t: ser.bye_or_played(all_series, t, s.season, "D") for t in s.teams}
        label = f"{s.season} {a}-{b}"
        if not s.complete:
            excluded.append({"series": label, "season": s.season, "reason": "series_open"})
            continue
        kinds = sorted(k for k, _ in status.values())
        if "unknown" in kinds:
            excluded.append({"series": label, "season": s.season, "reason": "round_incomplete"})
            continue
        if kinds == ["bye", "bye"]:
            excluded.append({"series": label, "season": s.season, "reason": "both_rested"})
            continue
        if kinds == ["played", "played"]:
            excluded.append({"series": label, "season": s.season, "reason": "both_played"})
            continue
        bye = next(t for t, (k, _) in status.items() if k == "bye")
        played = next(t for t, (k, _) in status.items() if k == "played")
        pb, pp = _win_pct(records, s.season, bye), _win_pct(records, s.season, played)
        if pb is None or pp is None:
            excluded.append({"series": label, "season": s.season, "reason": "no_record"})
            continue
        first = s.games[0]
        bye_home_g1 = first["home_team"] == bye
        wins = s.wins
        wc = status[played][1]
        pairs.append({
            "season": s.season, "bye": bye, "played": played, "series": label,
            "bye_win_pct": pb, "played_win_pct": pp,
            "g1_game_pk": first.get("game_pk"), "g1_date": ser.row_date(first), "g1_bye_home": bye_home_g1,
            "g1_score": {first["away_team"]: ser.runs_of(first)[0], first["home_team"]: ser.runs_of(first)[1]},
            "bye_won_g1": ser.winner_of(first) == bye,
            "series_score": {bye: wins[bye], played: wins[played]}, "series_games": s.length,
            "bye_won_series": s.winner == bye,
            "played_round": {"won": wc.winner == played, "games": wc.length,
                             "score": {t: wc.wins[t] for t in wc.teams}, "ended": wc.last_date,
                             "opponent": next(t for t in wc.teams if t != played)},
        })
    pairs.sort(key=lambda p: (p["season"], p["series"]))
    return pairs, excluded


# ---------------------------------------------------------------------------
# expectation and test
# ---------------------------------------------------------------------------

def _shrunk(p: float, shrink: float) -> float:
    return 0.5 + (1.0 - shrink) * (p - 0.5)


def expected_for(pair: Mapping, h: float = HOME_FIELD_WIN_RATE, shrink: float = 0.0) -> dict:
    """What the standings and home field predict for the bye club in one series.

    `shrink` pulls both clubs' win rates that fraction of the way back toward .500 first. The primary
    test uses none: a record is taken at face value. The sensitivity run uses `SENSITIVITY_SHRINK`
    because a record is a noisy measure of strength and the clubs with byes are the ones with the
    best records, so an unshrunk record overstates their edge and a result that says "the bye clubs
    underperformed" is partly a result about that overstatement."""
    neutral = log5(_shrunk(pair["bye_win_pct"], shrink), _shrunk(pair["played_win_pct"], shrink))
    # The club that hosted game 1 hosts games 1, 2 and 5, as it has in every format since 2014.
    pattern = HOME_PATTERN if pair["g1_bye_home"] else tuple(not x for x in HOME_PATTERN)
    p_games = [with_home_field(neutral, home, h) for home in pattern]
    return {"neutral": neutral, "p_game_1": p_games[0], "p_games": p_games,
            "p_series": series_win_probability(p_games)}


def _arm(ps: Sequence[float], observed: int) -> dict:
    n = len(ps)
    expected = sum(ps)
    sd = math.sqrt(sum(p * (1.0 - p) for p in ps))
    return {
        "n": n, "observed": observed, "expected": round(expected, 3), "excess": round(observed - expected, 3),
        "observed_rate": round(observed / n, 4) if n else None,
        "expected_rate": round(expected / n, 4) if n else None,
        "excess_points": round(100.0 * (observed - expected) / n, 2) if n else None,
        "p_two_sided": round(two_sided_p(ps, observed), 4) if n else None,
        "sd_wins": round(sd, 3),
        # the smallest difference in win probability, in points, that would reach p < .05 if the
        # observed figure were this far from the expectation (a normal approximation, for scale)
        "detectable_points": round(100.0 * 1.96 * sd / n, 1) if n else None,
    }


def evaluate(pairs: Sequence[Mapping], *, prices: Optional[Mapping] = None,
             h: float = HOME_FIELD_WIN_RATE, shrink: float = 0.0) -> dict:
    """The test, over the qualifying pairs. Pure."""
    prices = prices or {}
    rows = []
    g1_ps, s_ps, g1_obs, s_obs = [], [], 0, 0
    for pair in pairs:
        exp = expected_for(pair, h, shrink)
        g1_ps.append(exp["p_game_1"])
        s_ps.append(exp["p_series"])
        g1_obs += 1 if pair["bye_won_g1"] else 0
        s_obs += 1 if pair["bye_won_series"] else 0
        price = prices.get(pair.get("g1_game_pk")) or prices.get(str(pair.get("g1_game_pk")))
        rows.append(dict(pair, expected_g1=round(exp["p_game_1"], 4), expected_series=round(exp["p_series"], 4),
                         price=price))
    priced = sum(1 for r in rows if r["price"])
    by_season: Dict[int, dict] = {}
    for r in rows:
        s = by_season.setdefault(r["season"], {"series": 0, "bye_g1_wins": 0, "bye_series_wins": 0})
        s["series"] += 1
        s["bye_g1_wins"] += 1 if r["bye_won_g1"] else 0
        s["bye_series_wins"] += 1 if r["bye_won_series"] else 0
    return {
        "series": rows,
        "summary": {
            "n_series": len(rows),
            "game_1": _arm(g1_ps, g1_obs),
            "series": _arm(s_ps, s_obs),
            "by_season": {k: by_season[k] for k in sorted(by_season)},
            "prices": {"series_with_a_price": priced, "of": len(rows),
                       "note": ("closing moneylines exist in our stores for 2026 only; no series in 2015 to 2025 "
                                "has one") if not priced else "prices joined where supplied"},
            "home_field_win_rate": h,
        },
    }


def verdict(summary: Mapping) -> str:
    """One honest sentence about the result, chosen by the pre-registered rule: p below .05 on the
    series result is a finding in the direction it points; anything else is a null, and says how
    big an effect the sample could have seen."""
    s = summary["series"]
    if s["n"] == 0:
        return "There were no qualifying series, so there is no result."
    if s["p_two_sided"] < SIGNIFICANCE:
        way = ("fewer" if s["excess"] < 0 else "more")
        return (f"The bye clubs won {way} series than their records and home field predicted "
                f"({s['observed']} against {s['expected']:.1f} expected over {s['n']}, p = {s['p_two_sided']}).")
    return (f"A null result: the bye clubs won {s['observed']} of {s['n']} series against {s['expected']:.1f} "
            f"expected from their records and home field (p = {s['p_two_sided']}). A sample this size could "
            f"only have seen a swing of about {s['detectable_points']} points a series, so it cannot rule out "
            "a smaller effect in either direction.")


def run(games: Iterable[Mapping], records: Mapping, *, seasons: Sequence[int] = tuple(range(FIRST_SEASON, LAST_SEASON + 1)),
        prices: Optional[Mapping] = None) -> dict:
    """Pair, exclude and evaluate. `games` are postseason game rows (the results store's and the
    display store's together), `records` each club's regular-season record per season."""
    pairs, excluded = qualifying_series(games, records, seasons=seasons)
    result = evaluate(pairs, prices=prices)
    held = sorted({p["season"] for p in pairs} | {e["season"] for e in excluded})
    sens = evaluate(pairs, shrink=SENSITIVITY_SHRINK)["summary"]
    result.update(excluded=excluded, seasons_requested=list(seasons), seasons_with_series=held,
                  seasons_without=[s for s in seasons if s not in held],
                  sensitivity={"shrink_toward_500": round(SENSITIVITY_SHRINK, 4),
                               "game_1": sens["game_1"], "series": sens["series"]},
                  verdict=verdict(result["summary"]))
    return result


# ---------------------------------------------------------------------------
# words
# ---------------------------------------------------------------------------

def _score(pair: Mapping, key: str) -> str:
    s = pair[key]
    a, b = pair["bye"], pair["played"]
    if key == "g1_score":
        return f"{s.get(a)}-{s.get(b)}"
    return f"{s[a]}-{s[b]}"


def table_rows(result: Mapping) -> List[dict]:
    """One flat row per qualifying series, for the table in the write-up and the CLI."""
    out = []
    for p in result["series"]:
        wc = p["played_round"]
        verb = "won" if wc["won"] else "lost"
        out.append({
            "season": p["season"], "bye": p["bye"], "played": p["played"],
            "played_round": (f"{verb} its Wild Card game" if wc["games"] == 1 else
                             f"{verb} the Wild Card Series {max(wc['score'].values())}-{min(wc['score'].values())}"),
            "g1": ("bye club won" if p["bye_won_g1"] else "bye club lost") + f" {_score(p, 'g1_score')}"
                  + (" at home" if p["g1_bye_home"] else " on the road"),
            "series": ("bye club won" if p["bye_won_series"] else "bye club lost") + f" {_score(p, 'series_score')}",
            "expected_g1": p["expected_g1"], "expected_series": p["expected_series"],
            "price": "none" if not p["price"] else str(p["price"]),
        })
    return out


def render_markdown_table(result: Mapping) -> List[str]:
    lines = ["| Season | Bye club | Played the Wild Card | Game 1 | Series | Expected G1 | Expected series | Price |",
             "|---|---|---|---|---|---|---|---|"]
    for r in table_rows(result):
        lines.append(f"| {r['season']} | {r['bye']} | {r['played']} ({r['played_round']}) | {r['g1']} | "
                     f"{r['series']} | {r['expected_g1']:.3f} | {r['expected_series']:.3f} | {r['price']} |")
    return lines


def render_text(result: Mapping) -> List[str]:
    s = result["summary"]
    lines = [f"Rest versus rhythm, Division Series {result['seasons_requested'][0]} to "
             f"{result['seasons_requested'][-1]}: {s['n_series']} series with one club on a bye and one that played "
             "the Wild Card round."]
    if result["seasons_without"]:
        lines.append("  no Division Series in the data for: " + ", ".join(str(x) for x in result["seasons_without"]))
    for e in result["excluded"]:
        lines.append(f"  left out: {e['series']} ({e['reason']})")
    lines.append("")
    for r in table_rows(result):
        lines.append(f"  {r['season']} {r['bye']} (bye) v {r['played']} ({r['played_round']}): G1 {r['g1']}; "
                     f"series {r['series']}; expected G1 {r['expected_g1']:.3f}, series {r['expected_series']:.3f}; "
                     f"price {r['price']}")
    lines.append("")
    for label, key in (("Game 1", "game_1"), ("Series", "series")):
        a = s[key]
        lines.append(f"{label}: the bye club won {a['observed']} of {a['n']} ({a['observed_rate']}); "
                     f"expected {a['expected']} ({a['expected_rate']}); excess {a['excess']:+} wins "
                     f"({a['excess_points']:+} points); two-sided p = {a['p_two_sided']}")
    sens = result["sensitivity"]
    lines.append(f"Sensitivity (records pulled {sens['shrink_toward_500']:.2f} of the way back to .500): "
                 f"Game 1 excess {sens['game_1']['excess']:+} wins (p = {sens['game_1']['p_two_sided']}), "
                 f"series excess {sens['series']['excess']:+} wins (p = {sens['series']['p_two_sided']})")
    lines.append(f"Price: {s['prices']['series_with_a_price']} of {s['prices']['of']} series have one. "
                 f"{s['prices']['note']}.")
    lines.append("")
    lines.append(result["verdict"])
    return lines
