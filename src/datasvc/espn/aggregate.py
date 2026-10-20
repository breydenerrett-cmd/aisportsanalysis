"""Season averages and per-game splits, aggregated from the stored box scores.

Everything here is computed from `games`, `team_games` and `player_games` (the append-only ESPN-fed
datasets, or any store with the same three datasets, such as the MLB statsapi box-score store). Nothing is
fetched and nothing is written.

POINT IN TIME. With `as_of=T` a game is used only if it was FINAL by T:

* `observed`      a version of the game that says "final" was observed at or before T (a forward capture:
                  we really knew then). The box score used is the newest version observed at or before T.
* `reconstructed` we only saw the game final after T (a backfill), but it started early enough that it
                  had certainly finished by T (start + a generous per-sport length, `FINAL_AFTER`). The
                  earliest stored box score is used. A backfill's `observed_utc` is the backfill time, so
                  without this rule every historical `as_of` would see nothing.

`strict=True` keeps only `observed` games. Games that started after T, or might still have been playing at
T, are never used. The result says how many games came from each basis, so a caller can see how much of a
past average is reconstructed. Without `as_of` every final game is used (newest box score versions).

VALUES. ESPN's stats are display strings and are not coerced at write time (docs/datasvc/ESPN_SCHEMA.md);
they are interpreted here, per key: a plain number ("46", "-3", "+6"), a ratio ("38-83", "11/19": made and
attempted), a clock ("33:12": minutes and seconds). Anything else is ignored. A key present in only some
games is averaged over the games that have it (`games` says how many); a percentage field is the mean of the
per-game percentages (use the ratio's `pct` for the volume-weighted one).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: How long after the scheduled start a game is certainly over. Generous on purpose: a game near the edge is
#: left out of a past average rather than risk counting one that was still being played.
FINAL_AFTER: Dict[str, timedelta] = {
    "basketball": timedelta(hours=3, minutes=30),
    "hockey": timedelta(hours=3, minutes=30),
    "football": timedelta(hours=4, minutes=30),
    "soccer": timedelta(hours=2, minutes=45),
    "baseball": timedelta(hours=5),
}
DEFAULT_FINAL_AFTER = timedelta(hours=5)

#: Split names understood by `team_summary` / `player_summary`. `last<N>` (last3, last5, last10 ...) is also valid.
BASE_SPLITS = ("all", "home", "away", "wins", "losses")
PLAYER_ONLY_SPLITS = ("starter", "bench")
DEFAULT_SPLITS = ("all", "home", "away", "wins", "losses", "last5", "last10")

_NUM = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_RATIO = re.compile(r"^(\d+)\s*[-/]\s*(\d+)$")
_CLOCK = re.compile(r"^(\d+):(\d{2})$")
_LAST = re.compile(r"^last(\d+)$")
_TS = "%Y-%m-%dT%H:%M:%SZ"


class BadSplit(ValueError):
    pass


def parse_value(value: Any) -> Optional[Tuple]:
    """('num', x) | ('ratio', made, att) | ('clock', seconds) | None for a value that is none of those."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return ("num", float(value))
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    if _NUM.match(text):
        return ("num", float(text))
    m = _RATIO.match(text)
    if m:
        return ("ratio", int(m.group(1)), int(m.group(2)))
    m = _CLOCK.match(text)
    if m:
        return ("clock", int(m.group(1)) * 60 + int(m.group(2)))
    return None


def _round(x: Optional[float], places: int = 4) -> Optional[float]:
    return None if x is None else round(x, places)


def _mmss(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


class _Acc:
    """One stat key over many games."""

    __slots__ = ("kind", "n", "total", "made", "att")

    def __init__(self, kind: str):
        self.kind, self.n, self.total, self.made, self.att = kind, 0, 0.0, 0, 0

    def add(self, parsed: Tuple) -> None:
        if parsed[0] != self.kind:
            return
        self.n += 1
        if self.kind == "num":
            self.total += parsed[1]
        elif self.kind == "clock":
            self.total += parsed[1]
        else:
            self.made += parsed[1]
            self.att += parsed[2]

    def out(self) -> dict:
        n = self.n
        if self.kind == "num":
            return {"kind": "num", "games": n, "total": _round(self.total), "avg": _round(self.total / n)}
        if self.kind == "clock":
            return {"kind": "clock", "games": n, "total_seconds": int(self.total),
                    "avg_seconds": _round(self.total / n, 2), "avg": _mmss(self.total / n)}
        return {"kind": "ratio", "games": n, "made": self.made, "att": self.att,
                "made_avg": _round(self.made / n), "att_avg": _round(self.att / n),
                "pct": _round(self.made / self.att) if self.att else None}


def summarize_stats(rows: Iterable[dict]) -> Dict[str, dict]:
    """{key: summary} over a list of flat {key: display value} dicts (one per game)."""
    accs: Dict[str, _Acc] = {}
    for stats in rows:
        for key, raw in (stats or {}).items():
            parsed = parse_value(raw)
            if parsed is None:
                continue
            acc = accs.get(key)
            if acc is None:
                acc = accs[key] = _Acc(parsed[0])
            acc.add(parsed)
    return {k: accs[k].out() for k in sorted(accs) if accs[k].n}


# -- which games, which box-score versions ------------------------------------------------------------------

def _ts(text: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.strptime(text, _TS)
    except (TypeError, ValueError):
        return None


def _group_versions(rows: Iterable[dict], key_fields: Sequence[str]) -> Dict[tuple, List[dict]]:
    out: Dict[tuple, List[dict]] = {}
    for r in rows:
        out.setdefault(tuple(str(r.get(f)) for f in key_fields), []).append(r)
    for versions in out.values():
        versions.sort(key=lambda r: r.get("observed_utc") or "")
    return out


def pick_version(versions: List[dict], as_of: Optional[str]) -> Tuple[Optional[dict], str]:
    """(row, how): the newest version observed by `as_of`, else the earliest version (reconstructed)."""
    if not versions:
        return None, "none"
    if as_of is None:
        return versions[-1], "newest"
    seen = [v for v in versions if (v.get("observed_utc") or "") <= as_of]
    if seen:
        return seen[-1], "observed"
    return versions[0], "reconstructed"


class Game:
    __slots__ = ("game_id", "date_utc", "home_id", "away_id", "home_score", "away_score", "season_type",
                 "basis", "row")

    def __init__(self, row: dict, basis: str):
        self.row, self.basis = row, basis
        self.game_id = str(row["game_id"])
        self.date_utc = row.get("date_utc") or ""
        self.home_id, self.away_id = str(row.get("home_id")), str(row.get("away_id"))
        self.home_score, self.away_score = row.get("home_score"), row.get("away_score")
        self.season_type = row.get("season_type")

    def result_for(self, team_id: str) -> Optional[str]:
        """'W' | 'L' | 'T' for `team_id`, or None when the score is unknown."""
        if self.home_score is None or self.away_score is None:
            return None
        if self.home_score == self.away_score:
            return "T"
        home_won = self.home_score > self.away_score
        return "W" if (team_id == self.home_id) == home_won else "L"


def season_types_filter(value: Any, family: str) -> Optional[set]:
    """None = every game. 'regular' (the default everywhere) drops preseason (ESPN type 1); 'all' keeps it;
    a number or a comma list keeps exactly those ESPN season types."""
    if value in (None, "", "all"):
        return None
    if value == "regular":
        return {2, 3} if family != "soccer" else None     # soccer types are league-season ids, not 1/2/3
    out = set()
    for part in str(value).split(","):
        try:
            out.add(int(part))
        except ValueError:
            raise BadSplit(f"season_type must be 'regular', 'all' or ESPN season type numbers, got {value!r}") from None
    return out


def classify_game(versions: List[dict], as_of: Optional[str], buffer: timedelta, strict: bool = False
                  ) -> Tuple[Optional[dict], str]:
    """(row, basis) for one game's versions: the final-state row to use and why it counts, or (None, reason).

    basis: 'all' (no as_of), 'observed', 'reconstructed'; reasons: 'not_final', 'after_as_of'."""
    finals = [v for v in versions if v.get("completed") and v.get("state") == "post"]
    if not finals:
        return None, "not_final"
    first_final = finals[0]
    if as_of is None:
        return finals[-1], "all"
    seen = [v for v in finals if (v.get("observed_utc") or "") <= as_of]
    if seen:
        return seen[-1], "observed"
    start, limit = _ts(first_final.get("date_utc")), _ts(as_of)
    if not strict and start is not None and limit is not None and start + buffer <= limit:
        return first_final, "reconstructed"
    return None, "after_as_of"


def eligible_games(store, league: str, family: str, *, season=None, as_of: Optional[str] = None,
                   season_type: Any = "regular", strict: bool = False) -> Tuple[Dict[str, Game], dict]:
    """The final games usable for a read, and counts (`observed`, `reconstructed`, `excluded_*`)."""
    wanted_types = season_types_filter(season_type, family)
    grouped = _group_versions(store.versions(league, "games", season), ("game_id",))
    buffer = FINAL_AFTER.get(family, DEFAULT_FINAL_AFTER)
    games: Dict[str, Game] = {}
    counts = {"observed": 0, "reconstructed": 0, "excluded_not_final": 0, "excluded_after_as_of": 0,
              "excluded_season_type": 0}
    for (gid,), versions in grouped.items():
        row, basis = classify_game(versions, as_of, buffer, strict)
        if row is None:
            counts["excluded_" + basis] += 1
            continue
        if wanted_types is not None and row.get("season_type") not in wanted_types:
            counts["excluded_season_type"] += 1
            continue
        games[gid] = Game(row, basis)
        if basis in ("observed", "reconstructed"):
            counts[basis] += 1
    return games, counts


# -- splits ---------------------------------------------------------------------------------------------------

def validate_split(split: str, *, player: bool = False) -> str:
    s = str(split or "all").lower()
    if s in BASE_SPLITS or _LAST.match(s) or (player and s in PLAYER_ONLY_SPLITS):
        return s
    raise BadSplit(f"unknown split {split!r}; use one of {', '.join(BASE_SPLITS + (PLAYER_ONLY_SPLITS if player else ()))} "
                   "or lastN (last5, last10)")


def _apply_split(items: List[dict], split: str) -> List[dict]:
    """`items` are dicts with game, home, result, date, starter (player rows); newest-first for lastN."""
    if split == "all":
        return list(items)
    if split == "home":
        return [i for i in items if i["home"]]
    if split == "away":
        return [i for i in items if not i["home"]]
    if split == "wins":
        return [i for i in items if i["result"] == "W"]
    if split == "losses":
        return [i for i in items if i["result"] == "L"]
    if split == "starter":
        return [i for i in items if i.get("starter") is True]
    if split == "bench":
        return [i for i in items if i.get("starter") is False]
    n = int(_LAST.match(split).group(1))
    return sorted(items, key=lambda i: (i["date"], i["game_id"]), reverse=True)[:n]


def _record(items: List[dict]) -> dict:
    w = sum(1 for i in items if i["result"] == "W")
    l = sum(1 for i in items if i["result"] == "L")
    t = sum(1 for i in items if i["result"] == "T")
    return {"wins": w, "losses": l, "ties": t}


def _chosen(versions: Dict[tuple, List[dict]], key: tuple, as_of: Optional[str], strict: bool) -> Optional[dict]:
    row, how = pick_version(versions.get(key, []), as_of)
    if row is None or (strict and how == "reconstructed"):
        return None
    return row


# -- team summaries -----------------------------------------------------------------------------------------------

def team_items(store, league: str, family: str, team_id: str, *, season=None, as_of=None,
               season_type="regular", strict=False, games: Optional[Dict[str, Game]] = None,
               counts: Optional[dict] = None) -> Tuple[List[dict], dict]:
    """One dict per final game of `team_id`: its box-score totals, the opponent's (what it allowed), result."""
    if games is None:
        games, counts = eligible_games(store, league, family, season=season, as_of=as_of,
                                       season_type=season_type, strict=strict)
    tg = _group_versions(store.versions(league, "team_games", season), ("game_id", "team_id"))
    items = []
    for gid, g in games.items():
        if team_id not in (g.home_id, g.away_id):
            continue
        opp_id = g.away_id if team_id == g.home_id else g.home_id
        mine = _chosen(tg, (gid, team_id), as_of, strict)
        if mine is None:
            continue
        theirs = _chosen(tg, (gid, opp_id), as_of, strict)
        is_home = team_id == g.home_id
        pf = g.home_score if is_home else g.away_score
        pa = g.away_score if is_home else g.home_score
        items.append({"game_id": gid, "date": g.date_utc, "home": is_home, "result": g.result_for(team_id),
                      "opponent_id": opp_id, "pf": pf, "pa": pa, "stats": mine.get("stats") or {},
                      "opp_stats": (theirs or {}).get("stats") or {}, "basis": g.basis})
    return items, counts or {}


def summarize_team(items: List[dict], split: str = "all") -> dict:
    sel = _apply_split(items, split)
    n = len(sel)
    pf = [i["pf"] for i in sel if i["pf"] is not None]
    pa = [i["pa"] for i in sel if i["pa"] is not None]
    both = [(i["pf"], i["pa"]) for i in sel if i["pf"] is not None and i["pa"] is not None]
    out = {"split": split, "games": n, **_record(sel),
           "points_for": {"total": sum(pf), "avg": _round(sum(pf) / len(pf)) if pf else None},
           "points_against": {"total": sum(pa), "avg": _round(sum(pa) / len(pa)) if pa else None},
           "margin_avg": _round(sum(a - b for a, b in both) / len(both)) if both else None,
           "stats": summarize_stats(i["stats"] for i in sel),
           "allowed": summarize_stats(i["opp_stats"] for i in sel)}
    if sel:
        dates = sorted(i["date"] for i in sel)
        out["first_game_utc"], out["last_game_utc"] = dates[0], dates[-1]
    return out


# -- player summaries -----------------------------------------------------------------------------------------------

def played(row: dict, family: str) -> bool:
    """Whether a player row is an appearance. Soccer rosters list the whole squad, so a bench player who did
    not come on has a row with zero appearances."""
    if row.get("did_not_play"):
        return False
    if family == "soccer":
        if row.get("starter") or row.get("subbed_in"):
            return True
        app = parse_value(((row.get("stats") or {}).get("all") or {}).get("appearances"))
        return bool(app and app[0] == "num" and app[1] >= 1)
    return True


def player_items(store, league: str, family: str, *, season=None, as_of=None, season_type="regular",
                 strict=False, player_id: Optional[str] = None, team_id: Optional[str] = None,
                 games: Optional[Dict[str, Game]] = None, counts: Optional[dict] = None
                 ) -> Tuple[Dict[str, List[dict]], dict]:
    """player_id -> one dict per appearance in a final game (stats by group, home/away, result, starter)."""
    if games is None:
        games, counts = eligible_games(store, league, family, season=season, as_of=as_of,
                                       season_type=season_type, strict=strict)
    rows = store.versions(league, "player_games", season)
    if player_id is not None:
        rows = [r for r in rows if str(r.get("player_id")) == str(player_id)]
    if team_id is not None:
        rows = [r for r in rows if str(r.get("team_id")) == str(team_id)]
    grouped = _group_versions(rows, ("game_id", "player_id"))
    out: Dict[str, List[dict]] = {}
    for (gid, pid), versions in grouped.items():
        g = games.get(gid)
        if g is None:
            continue
        row = _chosen(grouped, (gid, pid), as_of, strict)
        if row is None or not played(row, family):
            continue
        tid = str(row.get("team_id"))
        out.setdefault(pid, []).append({
            "game_id": gid, "date": g.date_utc, "home": tid == g.home_id, "result": g.result_for(tid),
            "team_id": tid, "name": row.get("player_name"), "position": row.get("position"),
            "starter": row.get("starter"), "groups": row.get("stats") or {}, "basis": g.basis})
    return out, counts or {}


def summarize_player(items: List[dict], split: str = "all") -> dict:
    sel = _apply_split(items, split)
    by_group: Dict[str, List[dict]] = {}
    for i in sel:
        for gname, stats in i["groups"].items():
            by_group.setdefault(gname, []).append(stats)
    newest = max(sel, key=lambda i: (i["date"], i["game_id"])) if sel else None
    out = {"split": split, "games": len(sel), **_record(sel),
           "starts": sum(1 for i in sel if i.get("starter") is True),
           "groups": {g: {"games": len(rows), "stats": summarize_stats(rows)} for g, rows in sorted(by_group.items())}}
    if newest:
        out.update(player_name=newest["name"], team_id=newest["team_id"], position=newest["position"],
                   last_game_utc=newest["date"])
    return out


def basis_counts(counts: dict) -> dict:
    keep = {k: v for k, v in counts.items() if v or k in ("observed", "reconstructed")}
    return keep
