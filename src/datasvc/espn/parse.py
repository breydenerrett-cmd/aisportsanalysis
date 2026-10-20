"""Pure parsers: ESPN site-API JSON in, normalised rows out. No I/O, no clock (the caller passes `observed_utc`).

Values are kept as the source gives them. Counting stats are stored under their source key
(`totalRebounds`, `shotsOnTarget`), as the display string ESPN prints ("38-83", "46", "33:12"), never
coerced, because ESPN mixes ratios, clock times and counts in one field. Only scores, attendance and
ids are converted. A field the source omitted is absent from the row, never zero.

Row shapes are fixed in docs/datasvc/ESPN_SCHEMA.md.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::(\d{2}))?")


def norm_ts(text: Any) -> Optional[str]:
    """'2026-01-15T19:00Z' -> '2026-01-15T19:00:00Z' (None for anything that is not an ISO instant)."""
    m = _TS.match(str(text or ""))
    if not m:
        return None
    return f"{m.group(1)}T{m.group(2)}:{m.group(3) or '00'}Z"


def _int(value: Any) -> Optional[int]:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _s(value: Any) -> Optional[str]:
    return None if value in (None, "") else str(value)


def _put(row: dict, **fields) -> dict:
    row.update({k: v for k, v in fields.items() if v is not None})
    return row


# -- teams -----------------------------------------------------------------------------------------------

_ID_IN_LINK = re.compile(r"/id/(\d+)")


def athlete_id(ath: dict) -> Optional[str]:
    """The athlete's id: `id` when present, else the number in his player-card link (the injury feed omits `id`)."""
    if ath.get("id"):
        return str(ath["id"])
    for link in ath.get("links") or []:
        m = _ID_IN_LINK.search(str(link.get("href") or ""))
        if m:
            return m.group(1)
    return None


def teams(payload: dict, league: str, observed_utc: str) -> List[dict]:
    out = []
    for sport in payload.get("sports") or []:
        for lg in sport.get("leagues") or []:
            for entry in lg.get("teams") or []:
                t = entry.get("team") or entry
                if not t.get("id"):
                    continue
                logos = t.get("logos") or []
                out.append(_put({"league": league, "team_id": str(t["id"]), "observed_utc": observed_utc},
                                abbreviation=_s(t.get("abbreviation")), name=_s(t.get("name")),
                                location=_s(t.get("location")), display_name=_s(t.get("displayName")),
                                short_name=_s(t.get("shortDisplayName")), color=_s(t.get("color")),
                                alt_color=_s(t.get("alternateColor")),
                                logo=_s(logos[0].get("href")) if logos else _s(t.get("logo")),
                                is_active=t.get("isActive")))
    return out


# -- games (scoreboard) -------------------------------------------------------------------------------------

def _competitor(c: dict) -> dict:
    team = c.get("team") or {}
    return {"id": _s(team.get("id") or c.get("id")), "abbr": _s(team.get("abbreviation")),
            "name": _s(team.get("displayName")), "score": c.get("score"), "winner": c.get("winner")}


def games(payload: dict, league: str, observed_utc: str, day: Optional[str] = None) -> List[dict]:
    """One row per scoreboard event. Scores are absent until the game has started. `day` (YYYY-MM-DD) is the
    scoreboard date that listed it: ESPN's US-evening day, which can differ from the UTC date of the kickoff."""
    out = []
    for e in payload.get("events") or []:
        comps = e.get("competitions") or []
        if not comps or not e.get("id"):
            continue
        c = comps[0]
        status = (c.get("status") or e.get("status") or {})
        stype = status.get("type") or {}
        state = stype.get("state")
        home = away = None
        for x in c.get("competitors") or []:
            if x.get("homeAway") == "home":
                home = _competitor(x)
            elif x.get("homeAway") == "away":
                away = _competitor(x)
        if not home or not away or not home["id"] or not away["id"]:
            continue                     # an unresolved placeholder side (a tournament slot): not a game yet
        season = e.get("season") or {}
        venue = c.get("venue") or {}
        started = state in ("in", "post")
        row = {"league": league, "game_id": str(e["id"]), "observed_utc": observed_utc,
               "date_utc": norm_ts(c.get("date") or e.get("date")),
               "state": state or "unknown", "status": _s(stype.get("name")),
               "completed": bool(stype.get("completed")),
               "home_id": home["id"], "away_id": away["id"]}
        _put(row, season=_int(season.get("year")), season_type=_int(season.get("type")),
             season_slug=_s(season.get("slug")), period=_int(status.get("period")),
             neutral_site=c.get("neutralSite"), attendance=_int(c.get("attendance")) or None,
             venue=_s(venue.get("fullName")), venue_city=_s((venue.get("address") or {}).get("city")),
             home_abbr=home["abbr"], away_abbr=away["abbr"], home_name=home["name"], away_name=away["name"],
             home_score=_int(home["score"]) if started else None,
             away_score=_int(away["score"]) if started else None,
             home_winner=home["winner"] if stype.get("completed") else None,
             away_winner=away["winner"] if stype.get("completed") else None,
             note=_s(((c.get("notes") or [{}])[0]).get("headline")), scoreboard_date=day)
        odds = [_put({}, provider=_s((o.get("provider") or {}).get("name")), details=_s(o.get("details")),
                     over_under=o.get("overUnder"), spread=o.get("spread"))
                for o in (c.get("odds") or []) if isinstance(o, dict)]
        if odds:
            row["espn_odds"] = odds
        out.append(row)
    return out


# -- box scores (summary) -----------------------------------------------------------------------------------

def team_games(summary: dict, game: dict, observed_utc: str) -> List[dict]:
    """One row per team: its box-score team totals, as the source's display strings."""
    out = []
    for t in (summary.get("boxscore") or {}).get("teams") or []:
        team = t.get("team") or {}
        if not team.get("id"):
            continue
        side = t.get("homeAway")
        tid = str(team["id"])
        side = side or ("home" if tid == game.get("home_id") else "away" if tid == game.get("away_id") else None)
        stats = {s["name"]: s.get("displayValue") for s in t.get("statistics") or []
                 if s.get("name") and s.get("displayValue") not in (None, "")}
        row = {"league": game["league"], "game_id": game["game_id"], "team_id": tid,
               "observed_utc": observed_utc, "date_utc": game.get("date_utc"), "stats": stats}
        _put(row, season=game.get("season"), home_away=side,
             opponent_id=game.get("away_id") if side == "home" else game.get("home_id") if side == "away" else None,
             points=game.get("home_score") if side == "home" else game.get("away_score") if side == "away" else None,
             points_against=game.get("away_score") if side == "home" else game.get("home_score") if side == "away" else None)
        out.append(row)
    return out


def _player_row(game: dict, team_id: str, athlete: dict, observed_utc: str) -> dict:
    pos = athlete.get("position") or {}
    return _put({"league": game["league"], "game_id": game["game_id"], "player_id": str(athlete["id"]),
                 "team_id": team_id, "observed_utc": observed_utc, "date_utc": game.get("date_utc"),
                 "stats": {}},
                season=game.get("season"), player_name=_s(athlete.get("displayName") or athlete.get("fullName")),
                position=_s(pos.get("abbreviation")))


def player_games(summary: dict, game: dict, observed_utc: str) -> List[dict]:
    """One row per player. `stats` is {group: {key: display value}} (group 'all' where the source has none;
    football has one group per skill: passing, rushing ...). Soccer has no box-score players: its rows come
    from the match rosters (appearances, goals, shots ...), with `starter` and `subbed_in/out`."""
    box = summary.get("boxscore") or {}
    rows: Dict[tuple, dict] = {}
    for tp in box.get("players") or []:
        tid = str((tp.get("team") or {}).get("id") or "")
        if not tid:
            continue
        for grp in tp.get("statistics") or []:
            keys = grp.get("keys") or grp.get("names") or []
            gname = grp.get("name") or "all"
            for a in grp.get("athletes") or []:
                ath = a.get("athlete") or {}
                if not ath.get("id"):
                    continue
                row = rows.setdefault((tid, str(ath["id"])), _player_row(game, tid, ath, observed_utc))
                vals = a.get("stats") or []
                row["stats"][gname] = {k: v for k, v in zip(keys, vals) if v not in (None, "")}
                if a.get("starter") is not None:
                    row["starter"] = bool(a["starter"])
                if a.get("didNotPlay"):
                    row["did_not_play"] = True
                    if a.get("reason"):
                        row["dnp_reason"] = str(a["reason"])
    if not rows:
        for r in summary.get("rosters") or []:
            tid = str((r.get("team") or {}).get("id") or "")
            for a in r.get("roster") or []:
                ath = a.get("athlete") or {}
                if not tid or not ath.get("id"):
                    continue
                row = _player_row(game, tid, ath, observed_utc)
                row["stats"]["all"] = {s["name"]: s.get("displayValue") for s in a.get("stats") or []
                                       if s.get("name") and s.get("displayValue") not in (None, "")}
                _put(row, starter=a.get("starter"), subbed_in=a.get("subbedIn"), subbed_out=a.get("subbedOut"),
                     jersey=_s(a.get("jersey")))
                rows[(tid, row["player_id"])] = row
    return list(rows.values())


# -- standings ------------------------------------------------------------------------------------------------

def standings(payload: dict, league: str, observed_utc: str) -> List[dict]:
    """One row per team per group (conference/division), with ESPN's stat list as {name: display value}."""
    season = _int(((payload.get("season") or {}).get("year")))
    out: List[dict] = []

    def walk(node: dict, trail: List[str]) -> None:
        here = trail
        st = node.get("standings") or {}
        for entry in st.get("entries") or []:
            team = entry.get("team") or {}
            if not team.get("id"):
                continue
            stats = {s["name"]: s.get("displayValue") for s in entry.get("stats") or []
                     if s.get("name") and s.get("displayValue") not in (None, "")}
            row = {"league": league, "team_id": str(team["id"]), "group": " / ".join(here) or "league",
                   "observed_utc": observed_utc, "stats": stats}
            _put(row, season=_int((st.get("season"))) or season or 0, team_abbr=_s(team.get("abbreviation")),
                 team_name=_s(team.get("displayName")),
                 note=_s((entry.get("note") or {}).get("description")))
            out.append(row)
        for child in node.get("children") or []:
            label = child.get("name") or child.get("abbreviation")
            walk(child, here + [label] if label else here)

    walk(payload, [])
    return out


# -- injuries ----------------------------------------------------------------------------------------------------

def injuries(payload: dict, league: str, observed_utc: str) -> List[dict]:
    out = []
    for grp in payload.get("injuries") or []:
        tid = _s(grp.get("id"))
        for i in grp.get("injuries") or []:
            ath = i.get("athlete") or {}
            pid = athlete_id(ath)
            if not pid:
                continue
            team = ath.get("team") or {}
            details = i.get("details") or {}
            row = {"league": league, "team_id": tid or _s(team.get("id")) or "unknown",
                   "player_id": pid, "observed_utc": observed_utc,
                   "status": _s(i.get("status")) or "unknown"}
            _put(row, player_name=_s(ath.get("displayName")),
                 position=_s((ath.get("position") or {}).get("abbreviation")),
                 reported_utc=norm_ts(i.get("date")), comment=_s(i.get("shortComment")),
                 injury_type=_s(details.get("type")), injury_location=_s(details.get("location")),
                 injury_detail=_s(details.get("detail")), side=_s(details.get("side")),
                 return_date=_s(details.get("returnDate")))
            out.append(row)
    return out


# -- rosters -----------------------------------------------------------------------------------------------------

def roster(payload: dict, league: str, team_id: str, observed_utc: str) -> List[dict]:
    """Players on a team's roster. NBA/soccer: a flat athlete list; NHL/NFL: groups of {position, items}."""
    out = []
    flat: List[dict] = []
    for a in payload.get("athletes") or []:
        if "items" in a:
            flat.extend(a["items"])
        else:
            flat.append(a)
    for a in flat:
        if not a.get("id"):
            continue
        pos = a.get("position") or {}
        out.append(_put({"league": league, "team_id": str(team_id), "player_id": str(a["id"]),
                         "observed_utc": observed_utc},
                        name=_s(a.get("displayName") or a.get("fullName")), position=_s(pos.get("abbreviation")),
                        jersey=_s(a.get("jersey")), height_in=a.get("height"), weight_lb=a.get("weight"),
                        age=a.get("age"), birth_date=norm_ts(a.get("dateOfBirth")) and a["dateOfBirth"][:10],
                        experience_years=(a.get("experience") or {}).get("years"),
                        status=_s((a.get("status") or {}).get("name")),
                        country=_s((a.get("birthPlace") or {}).get("country"))))
    return out
