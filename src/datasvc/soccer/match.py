"""Join football-data.co.uk matches to ESPN game ids by date and team name.

The two sources share no id. A football-data match has a date (local), a home and an away name ("Man City",
"Nott'm Forest", "Ath Madrid"); an ESPN game has a UTC kickoff and team rows with several names (display name
"Manchester City", short name "Man City", location, abbreviation). The join is one-to-one and conservative:

1. NAMES. For every football-data match, candidate ESPN games are those within one day of its date. A candidate
   scores each side by token overlap (a token equals, or is a prefix of at least three letters of, a token
   of one of the team's names: "man" fits "manchester", "ein" fits "eintracht"). Accepted when both sides score
   >= 0.75 (method `names`), or when one side scores >= 0.9 and no other candidate fits that side as well
   (method `one_side`: the other club's name was something like "Wolves" that no token rule links).
   Pairs are taken best-first, so one ESPN game is never given to two matches.
2. ALIAS. Names confirmed in step 1 are remembered (football-data name -> ESPN team id, by majority). A match
   left over is joined when both of its names resolve to ESPN teams that played each other, in that order,
   within three days (a postponement), method `alias`.
3. A seed table covers the spellings no rule can reach (`SEED_ALIASES`).

Everything else is reported as unmatched with the reason; nothing is guessed. The result rows
(`joins` dataset: league, match_id, game_id, method, score, day gap) are appended to the store, so a better
mapping later is a new version, not a rewrite.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from src.datasvc import names

STOP = frozenset({"fc", "cf", "afc", "ac", "as", "sc", "ssc", "sv", "vfb", "vfl", "fsv", "tsg", "rcd", "ud", "us",
                  "cd", "ca", "sd", "rc", "ogc", "aj", "og", "de", "la", "le", "el", "the", "club", "calcio",
                  "1", "04", "05", "08", "09", "78", "96", "98", "1846", "1899", "1900", "1907"})

#: football-data spelling -> a name ESPN uses for the same club. Only spellings no token rule reaches.
SEED_ALIASES: Dict[str, str] = {
    "Ath Madrid": "Atletico Madrid", "Ath Bilbao": "Athletic Club", "Sp Gijon": "Sporting Gijon",
    "La Coruna": "Deportivo La Coruna", "Espanol": "Espanyol", "Vallecano": "Rayo Vallecano",
    "Celta": "Celta Vigo", "Betis": "Real Betis", "Sociedad": "Real Sociedad", "Alaves": "Deportivo Alaves",
    "Inter": "Internazionale", "Verona": "Hellas Verona", "Chievo": "Chievo Verona",
    "M'gladbach": "Borussia Monchengladbach", "Ein Frankfurt": "Eintracht Frankfurt",
    "FC Koln": "Cologne", "Fortuna Dusseldorf": "Fortuna Dusseldorf", "Hertha": "Hertha Berlin",
    "Mainz": "Mainz 05", "Paris SG": "Paris Saint-Germain", "St Etienne": "Saint-Etienne",
    "Man City": "Manchester City", "Man United": "Manchester United", "Spurs": "Tottenham Hotspur",
    "Nott'm Forest": "Nottingham Forest", "Wolves": "Wolverhampton Wanderers", "West Brom": "West Bromwich Albion",
    "Leicester": "Leicester City", "Norwich": "Norwich City", "Cardiff": "Cardiff City", "Swansea": "Swansea City",
    "Hull": "Hull City", "Stoke": "Stoke City", "Huddersfield": "Huddersfield Town", "Brighton": "Brighton & Hove Albion",
    "Newcastle": "Newcastle United", "West Ham": "West Ham United", "Leeds": "Leeds United",
    "Bournemouth": "AFC Bournemouth", "Tottenham": "Tottenham Hotspur",
}


def _tokens(name: Optional[str]) -> List[str]:
    return [t for t in names.tokens(name) if t not in STOP]


def _token_fit(f: str, e: str) -> float:
    if f == e:
        return 1.0
    if min(len(f), len(e)) >= 3 and (e.startswith(f) or f.startswith(e)):
        return 0.8
    return 0.0


def name_score(fd_name: str, espn_names: Iterable[str]) -> float:
    """0..1: how well a football-data name fits any of a team's ESPN names (every football-data token must fit)."""
    ft = _tokens(fd_name)
    if not ft:
        return 0.0
    best = 0.0
    for candidate in espn_names:
        et = _tokens(candidate)
        if not et:
            continue
        score = sum(max(_token_fit(f, e) for e in et) for f in ft) / len(ft)
        # a football-data name that is a strict subset still fits ("Leeds" -> "Leeds United"); a shared
        # first word alone does not ("Man United" -> "Manchester City" shares only "man")
        best = max(best, score)
    return round(best, 4)


def team_names(team: dict) -> List[str]:
    return [n for n in (team.get("display_name"), team.get("short_name"), team.get("location"), team.get("name"),
                        team.get("abbreviation")) if n]


def _day(text: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


class Index:
    """ESPN games (final or not) with their team names, for one league and a date range."""

    def __init__(self, games: Iterable[dict], teams: Dict[str, dict]):
        games = list(games)
        teams = dict(teams)
        # the teams endpoint lists current clubs only: a relegated club's name still comes from its games
        for g in games:
            for side in ("home", "away"):
                tid = g.get(f"{side}_id")
                if tid and tid not in teams:
                    teams[tid] = {"display_name": g.get(f"{side}_name"), "abbreviation": g.get(f"{side}_abbr")}
        self.teams = teams
        self.names = {tid: team_names(t) for tid, t in teams.items()}
        self.games = [g for g in games if _day(g.get("date_utc"))]
        self.by_day: Dict[date, List[dict]] = {}
        for g in self.games:
            self.by_day.setdefault(_day(g["date_utc"]), []).append(g)

    def window(self, day: date, span: int) -> List[dict]:
        out = []
        for offset in range(-span, span + 1):
            out.extend(self.by_day.get(date.fromordinal(day.toordinal() + offset), []))
        return out

    def side_score(self, fd_name: str, team_id: str) -> float:
        return name_score(fd_name, self.names.get(team_id, []))


def match(fd_rows: List[dict], espn_games: Iterable[dict], espn_teams: Dict[str, dict],
          *, seed: Optional[Dict[str, str]] = None) -> Tuple[List[dict], dict]:
    """(joins, report). `fd_rows` are normalised football-data matches (one league), `espn_games` the latest
    version of each ESPN game, `espn_teams` {team_id: team row}."""
    index = Index(espn_games, espn_teams)
    seed = SEED_ALIASES if seed is None else seed
    seeded_names: Dict[str, str] = {}
    for fd_name, espn_name in seed.items():
        ids = [tid for tid, nm in index.names.items() if name_score(espn_name, nm) >= 1.0]
        if len(ids) == 1:
            seeded_names[fd_name] = ids[0]
    used: Dict[str, str] = {}
    joins: Dict[str, dict] = {}
    unmatched: Dict[str, str] = {}

    def row_day(r: dict) -> Optional[date]:
        return _day(r.get("date"))

    # ---- pass 1: names -------------------------------------------------------------------------------------------
    proposals: List[Tuple[float, int, str, dict, dict, float, float, str]] = []
    for r in fd_rows:
        d = row_day(r)
        if d is None:
            continue
        cands = []
        for g in index.window(d, 1):
            hs = index.side_score(r["home"], g["home_id"])
            as_ = index.side_score(r["away"], g["away_id"])
            cands.append((g, hs, as_, abs((_day(g["date_utc"]) - d).days)))
        for g, hs, as_, gap in cands:
            if hs >= 0.75 and as_ >= 0.75:
                proposals.append((hs + as_, -gap, "names", r, g, hs, as_, ""))
                continue
            for side, score, other in (("home", hs, as_), ("away", as_, hs)):
                if score >= 0.9:
                    rivals = [c for c in cands if c[0] is not g and (c[1] if side == "home" else c[2]) >= score]
                    if not rivals:
                        proposals.append((score + other * 0.5, -gap, "one_side", r, g, hs, as_, side))
    proposals.sort(key=lambda p: (-p[0], -p[1], p[3]["match_id"]))
    taken_games: set = set()
    for total, neg_gap, method, r, g, hs, as_, _side in proposals:
        if r["match_id"] in joins or g["game_id"] in taken_games:
            continue
        taken_games.add(g["game_id"])
        joins[r["match_id"]] = _join(r, g, method, round(total, 4), -neg_gap)

    # ---- pass 2: aliases learned from pass 1 ---------------------------------------------------------------------
    votes: Dict[str, Counter] = {}
    by_id = {g["game_id"]: g for g in index.games}
    fd_by_id = {r["match_id"]: r for r in fd_rows}
    for mid, j in joins.items():
        g, r = by_id[j["game_id"]], fd_by_id[mid]
        votes.setdefault(r["home"], Counter())[g["home_id"]] += 1
        votes.setdefault(r["away"], Counter())[g["away_id"]] += 1

    def resolve(fd_name: str) -> Optional[str]:
        v = votes.get(fd_name)
        if v:
            top = v.most_common(2)
            if len(top) == 1 or top[0][1] > top[1][1]:
                return top[0][0]
        if fd_name in seeded_names:
            return seeded_names[fd_name]
        scored = sorted(((index.side_score(fd_name, tid), tid) for tid in index.names), reverse=True)
        if scored and scored[0][0] >= 0.9 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            return scored[0][1]
        return None

    for r in fd_rows:
        if r["match_id"] in joins:
            continue
        d = row_day(r)
        if d is None:
            unmatched[r["match_id"]] = "no usable date"
            continue
        h, a = resolve(r["home"]), resolve(r["away"])
        if not h or not a:
            unmatched[r["match_id"]] = f"no ESPN team for {r['home'] if not h else r['away']!r}"
            continue
        opts = [g for g in index.window(d, 3) if g["home_id"] == h and g["away_id"] == a and g["game_id"] not in taken_games]
        if len(opts) == 1:
            taken_games.add(opts[0]["game_id"])
            joins[r["match_id"]] = _join(r, opts[0], "alias", 0.0, abs((_day(opts[0]["date_utc"]) - d).days))
        elif not opts:
            unmatched[r["match_id"]] = "no ESPN game between those clubs within 3 days"
        else:
            unmatched[r["match_id"]] = f"{len(opts)} ESPN games fit"

    # a join whose final scores disagree is wrong whatever the names say: drop it and say so
    disagreements = []
    for mid in list(joins):
        g, r = by_id[joins[mid]["game_id"]], fd_by_id[mid]
        have = (g.get("home_score"), g.get("away_score"), r.get("ft_home"), r.get("ft_away"))
        if None not in have and have[:2] != have[2:]:
            disagreements.append({"match_id": mid, "fd": list(have[2:]), "espn": list(have[:2]), "game_id": g["game_id"]})
            unmatched[mid] = f"scores disagree with ESPN game {g['game_id']}"
            del joins[mid]
    own_names = {nm for names_ in index.names.values() for nm in names_}
    methods = Counter(j["method"] for j in joins.values())
    matched_games = {j["game_id"] for j in joins.values()}
    lo = min((row_day(r) for r in fd_rows if row_day(r)), default=None)
    hi = max((row_day(r) for r in fd_rows if row_day(r)), default=None)
    in_range = [g for g in index.games if lo and hi and lo.toordinal() - 1 <= _day(g["date_utc"]).toordinal() <= hi.toordinal() + 1]
    report = {"football_data_matches": len(fd_rows), "matched": len(joins),
              "match_rate": round(len(joins) / len(fd_rows), 4) if fd_rows else None,
              "methods": dict(methods), "unmatched": len(unmatched), "score_disagreements": disagreements[:15],
              "scores_checked": sum(1 for mid, j in joins.items() if by_id[j["game_id"]].get("home_score") is not None
                                    and fd_by_id[mid].get("ft_home") is not None),
              "unmatched_examples": [{"match_id": k, "why": v} for k, v in sorted(unmatched.items())[:15]],
              "espn_games_in_range": len(in_range),
              "espn_games_without_a_match": sum(1 for g in in_range if g["game_id"] not in matched_games),
              "learned_aliases": {n: dict(c) for n, c in sorted(votes.items()) if len(c) == 1 and n not in own_names}}
    return list(joins.values()), report


def _join(r: dict, g: dict, method: str, score: float, gap: int) -> dict:
    return {"league": r["league"], "season": r["season"], "match_id": r["match_id"], "game_id": g["game_id"],
            "method": method, "score": score, "day_gap": gap, "fd_date": r["date"],
            "espn_date_utc": g.get("date_utc"), "fd_home": r["home"], "fd_away": r["away"],
            "espn_home": g.get("home_name"), "espn_away": g.get("away_name")}
