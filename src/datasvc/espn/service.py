"""The unified read API over the ESPN-fed stores: `EspnService`, also reachable as `DataClient.league(code)`.

Every capability answers one of the two shapes the rest of the data service uses:

    {"available": True,  "sport": <league>, "kind", "data", "meta"}
    {"available": False, "missing": [{"item", "reason"}, ...]}

Point-in-time: pass `as_of` (an ISO instant) and every row is read as the newest version WE had observed
at or before it. A game first fetched after `as_of` does not exist for that read; a score that only
arrived later is not shown. Without `as_of` the newest version is used. `meta` carries the newest
`observed_utc` of the rows read and says that the basis is OBSERVED (forward capture) for the day the
store began and RECONSTRUCTED for a backfill (`observed_utc` is then the backfill time, not the game time).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.datasvc import names
from src.datasvc.client import unavailable
from src.datasvc.espn import aggregate as agg, leagues as lg, pbp as pbp_mod
from src.datasvc.espn.store import ATTRIBUTION, EspnStore

CAPABILITIES = {
    "teams": "teams of the league (ids, abbreviations, names)",
    "players": "rosters (weekly snapshots) for pro leagues; search by name",
    "schedule": "games by date, season, team or status, with scores",
    "game": "one game with both teams' box score totals and, where stored, every player's line",
    "team_history": "a team's games, newest first, with its box-score totals",
    "player_history": "a player's box-score lines, newest first (pro leagues)",
    "standings": "standings snapshots by season and group",
    "injuries": "the injury report; as_of reads it as it stood then",
    "team_averages": "season averages per team (for and allowed), with splits; as_of uses only games final by then",
    "team_splits": "one team's season averages split home/away, wins/losses and last N games",
    "player_averages": "season averages per player (pro leagues), with splits; as_of uses only games final by then",
    "player_splits": "one player's season averages split home/away, wins/losses, starter/bench, last N games",
    "play_by_play": "every play of a completed game (NBA, NHL, NCAAF; NHL also from the league's own feed)",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _newest(rows: Sequence[dict]) -> Optional[str]:
    return max((r.get("observed_utc") or "" for r in rows), default="") or None


class EspnService:
    def __init__(self, store: Optional[EspnStore] = None, *, clock: Optional[Callable[[], str]] = None):
        self.store = store or EspnStore()
        self._clock = clock or _now_iso

    # -- plumbing ----------------------------------------------------------------------------------------

    def leagues(self) -> List[dict]:
        return [{"code": l.code, "title": l.title, "family": l.family, "has_players": l.players,
                 "has_injuries": l.injuries, "stored": self.store.league_dir(l.code).exists()}
                for l in lg.LEAGUES.values()]

    def capabilities(self, league: str) -> dict:
        L = lg.get(league)
        caps = {k: {"available": True, "via": v} for k, v in CAPABILITIES.items()}
        if not L.players:
            for k in ("players", "player_history"):
                caps[k] = {"available": False, "reason": f"player lines are not stored for {L.title} "
                                                         "(they are left out of the scheduled set to keep the repository and "
                                                         "web image small); team totals are"}
        if not L.injuries:
            caps["injuries"] = {"available": False, "reason": f"ESPN publishes no injury report for {L.title}"}
        if not L.players:
            for k in ("player_averages", "player_splits"):
                caps[k] = {"available": False, "reason": f"player lines are not stored for {L.title}"}
        if not L.pbp:
            caps["play_by_play"] = {"available": False, "reason": f"play-by-play is not stored for {L.title} "
                                    "(stored for NBA, NHL and NCAAF; `pbp` backfill can add it)"}
        return caps

    def _ok(self, league: str, kind: str, data: Any, rows: Sequence[dict], as_of: Optional[str], **meta) -> dict:
        m = {"source": "ESPN public site JSON", "attribution": ATTRIBUTION, "basis": "observed_utc is when LineHound "
             "fetched the row; a backfilled row's observed_utc is the backfill time", "built_utc": self._clock(),
             "as_of": as_of, "newest_observed_utc": _newest(rows)}
        m.update(meta)
        return {"available": True, "sport": league, "kind": kind, "data": data, "meta": m}

    def _league(self, league: str) -> lg.League:
        return lg.get(league)

    def _need(self, league: str, dataset: str, season=None) -> Optional[dict]:
        if not self.store.versions(league, dataset, season):
            return unavailable((dataset, f"the {league} {dataset} store holds no records"
                                         + (f" for season {season}" if season is not None else "")))
        return None

    def _team_id(self, league: str, value: str, as_of: Optional[str] = None) -> Tuple[Optional[str], Optional[dict]]:
        teams = {k[0]: v for k, v in self.store.latest(league, "teams", as_of=as_of).items()}
        v = str(value).strip()
        if v in teams:
            return v, None
        for tid, t in teams.items():
            if v.lower() == str(t.get("abbreviation", "")).lower():
                return tid, None
        people = {tid: [t.get("display_name"), t.get("name"), t.get("short_name"), t.get("location"),
                        f"{t.get('location', '')} {t.get('name', '')}"] for tid, t in teams.items()}
        res = names.match(v, {k: [n for n in ns if n] for k, ns in people.items()})
        if res.best:
            return res.best, None
        if res.ambiguous:
            return None, unavailable(("team", f"{value!r} fits several teams"),
                                     extra_items=[{"item": "candidates", "reason": "pass an id or abbreviation",
                                                   "candidates": [c[0] for c in res.candidates]}])
        return None, unavailable(("team", f"no {league} team matches {value!r}"))

    # -- capabilities --------------------------------------------------------------------------------------

    def teams(self, league: str, *, as_of: Optional[str] = None) -> dict:
        self._league(league)
        miss = self._need(league, "teams")
        if miss:
            return miss
        rows = sorted(self.store.latest(league, "teams", as_of=as_of).values(), key=lambda r: r.get("display_name") or "")
        return self._ok(league, "teams", rows, rows, as_of)

    def players(self, league: str, *, team: Optional[str] = None, search: Optional[str] = None,
                as_of: Optional[str] = None) -> dict:
        L = self._league(league)
        if not L.players:
            return unavailable(("players", self.capabilities(league)["players"]["reason"]))
        miss = self._need(league, "players")
        if miss:
            return miss
        rows = list(self.store.latest(league, "players", as_of=as_of).values())
        if team:
            tid, bad = self._team_id(league, team, as_of)
            if bad:
                return bad
            rows = [r for r in rows if r["team_id"] == tid]
        if search:
            res = names.match(search, {r["player_id"]: [r.get("name") or ""] for r in rows})
            keep = {c[0] for c in res.candidates}
            rows = [r for r in rows if r["player_id"] in keep]
        rows.sort(key=lambda r: (r["team_id"], r.get("name") or ""))
        return self._ok(league, "players", rows, rows, as_of)

    def schedule(self, league: str, *, date: Optional[str] = None, season: Optional[int] = None,
                 team: Optional[str] = None, status: Optional[str] = None, as_of: Optional[str] = None) -> dict:
        self._league(league)
        miss = self._need(league, "games", season)
        if miss:
            return miss
        rows = list(self.store.latest(league, "games", season, as_of).values())
        if date:
            rows = [r for r in rows if (r.get("scoreboard_date") or (r.get("date_utc") or "")[:10]) == date]
        if team:
            tid, bad = self._team_id(league, team, as_of)
            if bad:
                return bad
            rows = [r for r in rows if tid in (r["home_id"], r["away_id"])]
        if status:
            rows = [r for r in rows if r["state"] == status or r.get("status") == status]
        rows.sort(key=lambda r: (r.get("date_utc") or "", r["game_id"]))
        return self._ok(league, "schedule", rows, rows, as_of)

    def game(self, league: str, game_id: str, *, as_of: Optional[str] = None) -> dict:
        self._league(league)
        games = {k[0]: v for k, v in self.store.latest(league, "games", None, as_of).items()}
        g = games.get(str(game_id))
        if g is None:
            return unavailable(("game", f"no {league} game {game_id} observed" + (f" by {as_of}" if as_of else "")))
        season = g.get("season")
        tg = [r for k, r in self.store.latest(league, "team_games", season, as_of).items() if k[0] == g["game_id"]]
        pg = [r for k, r in self.store.latest(league, "player_games", season, as_of).items() if k[0] == g["game_id"]]
        missing = []
        if not tg:
            missing.append({"item": "team_games", "reason": "no box score observed yet"
                            + ("" if g["state"] == "post" else f" (game state: {g['state']})")})
        if not pg and self._league(league).players and tg:
            missing.append({"item": "player_games", "reason": "no player lines in the box score"})
        data = {"game": g, "team_games": sorted(tg, key=lambda r: r.get("home_away") or ""),
                "player_games": sorted(pg, key=lambda r: (r["team_id"], r.get("player_name") or ""))}
        out = self._ok(league, "game", data, [g] + tg + pg, as_of)
        if missing:
            out["meta"]["missing"] = missing
        return out

    def team_history(self, league: str, team: str, *, limit: int = 20, before: Optional[str] = None,
                     as_of: Optional[str] = None) -> dict:
        self._league(league)
        tid, bad = self._team_id(league, team, as_of)
        if bad:
            return bad
        games = {k[0]: v for k, v in self.store.latest(league, "games", None, as_of).items()}
        rows = []
        for (gid, t), r in self.store.latest(league, "team_games", None, as_of).items():
            if t != tid or gid not in games:
                continue
            if before and (r.get("date_utc") or "") >= before:
                continue
            rows.append(dict(r, game_state=games[gid]["state"]))
        rows.sort(key=lambda r: (r.get("date_utc") or "", r["game_id"]), reverse=True)
        if not rows:
            return unavailable(("team_games", f"no box scores observed for team {tid}"))
        return self._ok(league, "team_history", rows[:limit], rows, as_of, team_id=tid)

    def player_history(self, league: str, player_id: str, *, limit: int = 20, before: Optional[str] = None,
                       as_of: Optional[str] = None) -> dict:
        L = self._league(league)
        if not L.players:
            return unavailable(("player_games", self.capabilities(league)["player_history"]["reason"]))
        rows = [r for (gid, pid), r in self.store.latest(league, "player_games", None, as_of).items()
                if pid == str(player_id) and not (before and (r.get("date_utc") or "") >= before)]
        rows.sort(key=lambda r: (r.get("date_utc") or "", r["game_id"]), reverse=True)
        if not rows:
            return unavailable(("player_games", f"no lines observed for player {player_id}"))
        return self._ok(league, "player_history", rows[:limit], rows, as_of, player_id=str(player_id))

    def standings(self, league: str, *, season: Optional[int] = None, as_of: Optional[str] = None) -> dict:
        self._league(league)
        seasons = self.store.seasons(league, "standings")
        if not seasons:
            return unavailable(("standings", f"the {league} standings store holds no records"))
        pick = str(season) if season is not None else seasons[-1]
        if pick not in seasons:
            return unavailable(("standings", f"no standings stored for season {pick}"))
        allv = self.store.latest(league, "standings", pick, as_of)
        rows = sorted(allv.values(), key=lambda r: (r["group"], r.get("team_name") or "", r["team_id"]))
        if not rows:
            return unavailable(("standings", f"no standings observed for {pick}" + (f" by {as_of}" if as_of else "")))
        return self._ok(league, "standings", rows, rows, as_of, season=pick)

    def injuries(self, league: str, *, team: Optional[str] = None, as_of: Optional[str] = None,
                 include_cleared: bool = False) -> dict:
        L = self._league(league)
        if not L.injuries:
            return unavailable(("injuries", self.capabilities(league)["injuries"]["reason"]))
        miss = self._need(league, "injuries")
        if miss:
            return miss
        rows = list(self.store.latest(league, "injuries", None, as_of).values())
        if not include_cleared:
            rows = [r for r in rows if r.get("status") != "Cleared"]
        if team:
            tid, bad = self._team_id(league, team, as_of)
            if bad:
                return bad
            rows = [r for r in rows if r["team_id"] == tid]
        rows.sort(key=lambda r: (r["team_id"], r.get("player_name") or ""))
        return self._ok(league, "injuries", rows, rows, as_of)

    # -- season averages and splits (aggregated from the stored box scores) -------------------------------------

    # Team identity (id, abbreviation, name) is resolved against the newest teams rows even under `as_of`: a
    # backfill stamps teams with the backfill time, and a club's id and name are not an outcome.

    def _season_for(self, league: str, season: Optional[int], as_of: Optional[str]) -> Optional[str]:
        seasons = self.store.seasons(league, "games")
        if season is not None:
            return str(season) if str(season) in seasons else None
        if not seasons:
            return None
        if as_of:
            started = [s for s in seasons if any((r.get("date_utc") or "") <= as_of
                                                  for r in self.store.versions(league, "games", s))]
            return started[-1] if started else None
        return seasons[-1]

    def _basis_meta(self, games: Dict[str, "agg.Game"], counts: dict, season: str, season_type: Any,
                    as_of: Optional[str], strict: bool, family: str) -> dict:
        hours = agg.FINAL_AFTER.get(family, agg.DEFAULT_FINAL_AFTER).total_seconds() / 3600
        return {"season": season, "season_type": season_type, "strict": strict,
                "games_used": len(games), "game_basis": agg.basis_counts(counts),
                "final_after_hours": round(hours, 2),
                "point_in_time": ("as_of: only games final by then; `observed` = we saw it final by then, "
                                  "`reconstructed` = backfilled game old enough to have finished (earliest box score)"
                                  if as_of else "no as_of: every final game, newest box score versions")}

    def _sample(self, league: str, season: Optional[int], as_of: Optional[str], season_type: Any, strict: bool):
        """(family, season, games, counts, error) for an aggregate read."""
        L = self._league(league)
        pick = self._season_for(league, season, as_of)
        if pick is None:
            what = f"season {season}" if season is not None else (f"any season started by {as_of}" if as_of else "any season")
            return L.family, None, {}, {}, unavailable(("games", f"the {league} games store holds no data for {what}"))
        try:
            games, counts = agg.eligible_games(self.store, league, L.family, season=pick, as_of=as_of,
                                               season_type=season_type, strict=strict)
        except agg.BadSplit as exc:
            return L.family, pick, {}, {}, unavailable(("season_type", str(exc)))
        if not games:
            return L.family, pick, {}, counts, unavailable((
                "games", f"no final {league} games in season {pick}" + (f" by {as_of}" if as_of else "")
                + f" (season_type={season_type}; counts: {agg.basis_counts(counts)})"))
        return L.family, pick, games, counts, None

    @staticmethod
    def _split_arg(split: str, last: Optional[int], player: bool = False):
        if last is not None:
            if split not in ("all", f"last{int(last)}"):
                raise agg.BadSplit("pass either split or last, not both")
            split = f"last{int(last)}"
        return agg.validate_split(split, player=player)

    def team_averages(self, league: str, team: Optional[str] = None, *, season: Optional[int] = None,
                      split: str = "all", last: Optional[int] = None, as_of: Optional[str] = None,
                      season_type: Any = "regular", strict: bool = False) -> dict:
        """Season averages for one team (`team`) or every team (no `team`): record, points for/against and
        every box-score stat, plus what the opponents did against it (`allowed`)."""
        self._league(league)
        try:
            split = self._split_arg(split, last)
        except agg.BadSplit as exc:
            return unavailable(("split", str(exc)))
        tid = None
        if team:
            tid, bad = self._team_id(league, team)
            if bad:
                return bad
        family, pick, games, counts, err = self._sample(league, season, as_of, season_type, strict)
        if err:
            return err
        meta = self._basis_meta(games, counts, pick, season_type, as_of, strict, family)
        used = [g.row for g in games.values()]
        if tid:
            items, _ = agg.team_items(self.store, league, family, tid, season=pick, as_of=as_of, strict=strict,
                                      games=games, counts=counts)
            if not items:
                return unavailable(("team_games", f"no final box scores for team {tid} in season {pick}"
                                                  + (f" by {as_of}" if as_of else "")))
            return self._ok(league, "team_averages", dict(agg.summarize_team(items, split), team_id=tid), used, as_of, **meta)
        rows = []
        teams = {k[0]: v for k, v in self.store.latest(league, "teams").items()}
        ids = sorted({g.home_id for g in games.values()} | {g.away_id for g in games.values()})
        grouped = agg.group_team_games(self.store, league, pick)
        for t in ids:
            items, _ = agg.team_items(self.store, league, family, t, season=pick, as_of=as_of, strict=strict,
                                      games=games, counts=counts, grouped=grouped)
            if items:
                info = teams.get(t) or {}
                rows.append(dict(agg.summarize_team(items, split), team_id=t,
                                 team_abbr=info.get("abbreviation"), team_name=info.get("display_name")))
        rows.sort(key=lambda r: (r.get("team_name") or "", r["team_id"]))
        return self._ok(league, "team_averages", rows, used, as_of, **meta)

    def team_splits(self, league: str, team: str, *, season: Optional[int] = None,
                    splits: Sequence[str] = agg.DEFAULT_SPLITS, as_of: Optional[str] = None,
                    season_type: Any = "regular", strict: bool = False) -> dict:
        """One team's averages under several splits at once: {split: summary}."""
        self._league(league)
        try:
            names_ = [agg.validate_split(s) for s in splits]
        except agg.BadSplit as exc:
            return unavailable(("split", str(exc)))
        tid, bad = self._team_id(league, team)
        if bad:
            return bad
        family, pick, games, counts, err = self._sample(league, season, as_of, season_type, strict)
        if err:
            return err
        items, _ = agg.team_items(self.store, league, family, tid, season=pick, as_of=as_of, strict=strict,
                                  games=games, counts=counts)
        if not items:
            return unavailable(("team_games", f"no final box scores for team {tid} in season {pick}"
                                              + (f" by {as_of}" if as_of else "")))
        data = {s: agg.summarize_team(items, s) for s in names_}
        return self._ok(league, "team_splits", data, [g.row for g in games.values()], as_of, team_id=tid,
                        **self._basis_meta(games, counts, pick, season_type, as_of, strict, family))

    def _player_gate(self, league: str) -> Optional[dict]:
        L = self._league(league)
        if not L.players:
            return unavailable(("player_games", self.capabilities(league)["player_averages"]["reason"]))
        return None

    def player_averages(self, league: str, player_id: Optional[str] = None, *, team: Optional[str] = None,
                        season: Optional[int] = None, split: str = "all", last: Optional[int] = None,
                        min_games: int = 1, as_of: Optional[str] = None, season_type: Any = "regular",
                        strict: bool = False) -> dict:
        """Season averages for one player (`player_id`) or every player (optionally of one `team`)."""
        gate = self._player_gate(league)
        if gate:
            return gate
        try:
            split = self._split_arg(split, last, player=True)
        except agg.BadSplit as exc:
            return unavailable(("split", str(exc)))
        tid = None
        if team:
            tid, bad = self._team_id(league, team)
            if bad:
                return bad
        family, pick, games, counts, err = self._sample(league, season, as_of, season_type, strict)
        if err:
            return err
        by_player, _ = agg.player_items(self.store, league, family, season=pick, as_of=as_of, strict=strict,
                                        player_id=player_id, team_id=tid, games=games, counts=counts)
        meta = self._basis_meta(games, counts, pick, season_type, as_of, strict, family)
        used = [g.row for g in games.values()]
        if player_id is not None:
            items = by_player.get(str(player_id))
            if not items:
                return unavailable(("player_games", f"no appearances for player {player_id} in season {pick}"
                                                    + (f" by {as_of}" if as_of else "")))
            return self._ok(league, "player_averages", dict(agg.summarize_player(items, split), player_id=str(player_id)),
                            used, as_of, **meta)
        rows = []
        for pid, items in by_player.items():
            summary = agg.summarize_player(items, split)
            if summary["games"] >= max(1, int(min_games)):
                rows.append(dict(summary, player_id=pid))
        rows.sort(key=lambda r: (r.get("team_id") or "", r.get("player_name") or "", r["player_id"]))
        return self._ok(league, "player_averages", rows, used, as_of, min_games=int(min_games), **meta)

    def player_splits(self, league: str, player_id: str, *, season: Optional[int] = None,
                      splits: Sequence[str] = agg.DEFAULT_SPLITS + agg.PLAYER_ONLY_SPLITS,
                      as_of: Optional[str] = None, season_type: Any = "regular", strict: bool = False) -> dict:
        """One player's averages under several splits at once: {split: summary}."""
        gate = self._player_gate(league)
        if gate:
            return gate
        try:
            names_ = [agg.validate_split(s, player=True) for s in splits]
        except agg.BadSplit as exc:
            return unavailable(("split", str(exc)))
        family, pick, games, counts, err = self._sample(league, season, as_of, season_type, strict)
        if err:
            return err
        by_player, _ = agg.player_items(self.store, league, family, season=pick, as_of=as_of, strict=strict,
                                        player_id=player_id, games=games, counts=counts)
        items = by_player.get(str(player_id))
        if not items:
            return unavailable(("player_games", f"no appearances for player {player_id} in season {pick}"
                                                + (f" by {as_of}" if as_of else "")))
        data = {s: agg.summarize_player(items, s) for s in names_}
        return self._ok(league, "player_splits", data, [g.row for g in games.values()], as_of,
                        player_id=str(player_id), **self._basis_meta(games, counts, pick, season_type, as_of, strict, family))

    # -- play-by-play -----------------------------------------------------------------------------------------------

    def play_by_play(self, league: str, game_id: str, *, source: Optional[str] = None, as_of: Optional[str] = None,
                     period: Optional[int] = None, scoring_only: bool = False, strict: bool = False) -> dict:
        """Every play of a completed game from a stored source (`espn` by default; NHL also `nhle`).
        `as_of` returns the game only if it was final by then (same rule as the season averages) and the
        version of the plays observed by then."""
        L = self._league(league)
        if not L.pbp:
            return unavailable(("play_by_play", self.capabilities(league)["play_by_play"]["reason"]))
        all_versions = [v for v in self.store.versions(league, "games") if str(v["game_id"]) == str(game_id)]
        if not all_versions:
            return unavailable(("game", f"no {league} game {game_id} observed"))
        all_versions.sort(key=lambda r: r.get("observed_utc") or "")
        row, basis = agg.classify_game(all_versions, as_of, agg.FINAL_AFTER.get(L.family, agg.DEFAULT_FINAL_AFTER), strict)
        if row is None:
            why = {"not_final": "the game is not final yet", "after_as_of": f"the game was not final by {as_of}"}[basis]
            return unavailable(("play_by_play", f"{why}; play-by-play is stored for completed games only"))
        season = row.get("season", "unknown")
        pstore = pbp_mod.PbpStore(self.store.root)
        have = sorted({s for (gid, s) in pstore.newest_by_game(league, season) if gid == str(game_id)})
        if not have:
            return unavailable(("play_by_play", f"no play-by-play stored for {league} game {game_id} "
                                                "(`datasvc <league> pbp-fill` stores it)"))
        pick = source or ("espn" if "espn" in have else have[0])
        if pick not in have:
            return unavailable(("source", f"{pick!r} play-by-play is not stored for this game; stored: {have}"))
        got = pstore.read(league, season, str(game_id), pick, as_of=as_of, allow_reconstructed=(basis == "reconstructed"))
        if got is None:
            return unavailable(("play_by_play", f"no {pick} play-by-play observed by {as_of}"))
        events = got["events"]
        if period is not None:
            events = [e for e in events if e.get("per") == int(period)]
        if scoring_only:
            events = [e for e in events if e.get("sc") or e.get("type") == "goal"]
        data = {"game": row, "source": pick, "sources_available": have, "header": got["header"],
                "events": events, "drives": got["drives"], "n_events": len(events)}
        return self._ok(league, "play_by_play", data, [row, got["index"]], as_of, game_basis=basis,
                        pbp_observed_utc=got["index"]["observed_utc"], strict=strict)
