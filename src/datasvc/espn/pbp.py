"""Play-by-play: parsers (ESPN `summary` plays and drives, the NHL's own api-web feed) and a compact store.

STORAGE. One gzip file per league and season, `<league>/pbp_<season>.jsonl.gz`, plus an index
`<league>/pbp_<season>.index.jsonl`. A game is one gzip MEMBER (members concatenate into a valid gzip
file): a header line, then one JSON line per event. A game's member is appended once it is final; the
index line that makes it findable (byte offset and length, event count, sha256 of the events) is appended
after it. Nothing is rewritten. If a later fetch of the same game and source has different content (ESPN
patches plays for about a day), a new member and a new index line are appended and the older version stays;
an identical re-fetch writes nothing. A reader seeks to one member, so one game costs one small
decompression, not the season.

SOURCES. `espn` = the `plays` list (NBA, WNBA, NHL) or the `drives[*].plays` lists (college football) of
the box-score page `summary?event=<id>`, which the box-score pass already fetches: no extra request.
`nhle` = api-web.nhle.com `gamecenter/<id>/play-by-play` (NHL only; richer shot detail), stored under the
ESPN game id with the NHL game id in the header. Both are keyed by the ESPN `game_id`.

SIZE. ~7-11 KB of gzip per NBA/NHL/NCAAF game (see docs/datasvc/ESPN_SCHEMA.md for the measured season totals).
Nothing here is shipped in the web image (.dockerignore).

Event keys (short, because they repeat 300-500 times a game; gzip does the rest): n sequence, id play id,
per period, clk clock text, type/tid play type, txt description, team team id, as/hs away/home score after the
play, ts wall clock, sc scoring play, pts points, shoot shot attempt, att points attempted, pen penalty, to
turnover, x/y coordinates, ply athlete ids and plt their roles, str strength; football adds drive, off, down,
dist, yte (yards to end zone), edown/edist/eyte (after the play), yds, stype.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SOURCES = ("espn", "nhle")
_COORD_LIMIT = 2000        # ESPN uses about +-2.1e8 for "no coordinate"


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


# -- ESPN ------------------------------------------------------------------------------------------------------

def _espn_play(p: dict, index: int, drive_id: Optional[str] = None) -> dict:
    typ = p.get("type") or {}
    seq = _int(p.get("sequenceNumber"))
    ev = _put({"n": seq if seq is not None else index},
              id=_s(p.get("id")), per=_int((p.get("period") or {}).get("number")),
              clk=_s((p.get("clock") or {}).get("displayValue")), type=_s(typ.get("text")), tid=_s(typ.get("id")),
              txt=_s((p.get("text") or "").strip()), team=_s((p.get("team") or {}).get("id")),
              ts=_s(p.get("wallclock")))
    if p.get("awayScore") is not None:
        ev["as"], ev["hs"] = _int(p.get("awayScore")), _int(p.get("homeScore"))
    if p.get("scoringPlay"):
        ev["sc"] = 1
        if _int(p.get("scoreValue")):
            ev["pts"] = _int(p["scoreValue"])
    if p.get("shootingPlay"):
        ev["shoot"] = 1
    if _int(p.get("pointsAttempted")):
        ev["att"] = _int(p["pointsAttempted"])
    if p.get("isPenalty"):
        ev["pen"] = 1
    if p.get("isTurnover"):
        ev["to"] = 1
    xy = p.get("coordinate") or {}
    x, y = _int(xy.get("x")), _int(xy.get("y"))
    if x is not None and y is not None and abs(x) < _COORD_LIMIT and abs(y) < _COORD_LIMIT:
        ev["x"], ev["y"] = x, y
    ply, roles = [], []
    for part in p.get("participants") or []:
        pid = _s((part.get("athlete") or {}).get("id"))
        if pid:
            ply.append(pid)
            roles.append(_s(part.get("type")) or "")
    if ply:
        ev["ply"] = ply
        if any(roles):
            ev["plt"] = roles
    strength = p.get("strength") or {}
    if strength:
        _put(ev, str=_s(strength.get("abbreviation") or strength.get("text")))
    shot = p.get("shotInfo")
    if isinstance(shot, dict):
        flat = {k: v for k, v in shot.items() if isinstance(v, (str, int, float, bool))}
        if flat:
            ev["shot"] = flat
    # football
    start, end = p.get("start") or {}, p.get("end") or {}
    if start:
        _put(ev, down=_int(start.get("down")), dist=_int(start.get("distance")),
             yte=_int(start.get("yardsToEndzone")), off=_s((start.get("team") or {}).get("id")))
    if end:
        _put(ev, edown=_int(end.get("down")), edist=_int(end.get("distance")), eyte=_int(end.get("yardsToEndzone")))
    if _int(p.get("statYardage")):
        ev["yds"] = _int(p["statYardage"])
    if isinstance(p.get("scoringType"), dict):
        _put(ev, stype=_s(p["scoringType"].get("name") or p["scoringType"].get("displayName")))
    if drive_id:
        ev["drive"] = drive_id
    return ev


def espn_events(summary: dict) -> Tuple[List[dict], List[dict]]:
    """(plays, drives) from an ESPN `summary` payload. `drives` is empty except for football."""
    plays: List[dict] = []
    drives: List[dict] = []
    for i, p in enumerate(summary.get("plays") or []):
        if isinstance(p, dict):
            plays.append(_espn_play(p, i))
    block = summary.get("drives") or {}
    groups = []
    for key in ("previous", "current"):
        cur = block.get(key)
        groups.extend(cur if isinstance(cur, list) else ([cur] if isinstance(cur, dict) else []))
    for d in groups:
        did = _s(d.get("id"))
        drives.append(_put({"k": "drive"}, id=did, team=_s((d.get("team") or {}).get("id")),
                           result=_s(d.get("displayResult") or d.get("result")),
                           desc=_s(d.get("description")), yds=_int(d.get("yards")),
                           plays=_int(d.get("offensivePlays")), score=bool(d.get("isScore")),
                           start=_s((d.get("start") or {}).get("text")), end=_s((d.get("end") or {}).get("text")),
                           per=_int(((d.get("start") or {}).get("period") or {}).get("number")),
                           clk=_s(((d.get("start") or {}).get("clock") or {}).get("displayValue")),
                           elapsed=_s((d.get("timeElapsed") or {}).get("displayValue"))))
        for p in d.get("plays") or []:
            if isinstance(p, dict):
                plays.append(_espn_play(p, len(plays), did))
    plays.sort(key=lambda e: (e["n"], e.get("id") or ""))
    return plays, drives


# -- the NHL's own feed ----------------------------------------------------------------------------------------

def nhle_events(feed: dict) -> Tuple[List[dict], dict]:
    """(events, header extras) from api-web `gamecenter/<id>/play-by-play`. Event `d` is the feed's own
    `details` object (coordinates, shot type, shooter and goalie ids, scorer and assists, running shots);
    `roster` maps player id to [name, team id, position, sweater number]."""
    events = []
    for i, p in enumerate(feed.get("plays") or []):
        if not isinstance(p, dict):
            continue
        per = p.get("periodDescriptor") or {}
        ev = _put({"n": _int(p.get("sortOrder")) if _int(p.get("sortOrder")) is not None else i},
                  id=_s(p.get("eventId")), per=_int(per.get("number")), ptype=_s(per.get("periodType")),
                  clk=_s(p.get("timeInPeriod")), left=_s(p.get("timeRemaining")),
                  type=_s(p.get("typeDescKey")), tid=_s(p.get("typeCode")), sit=_s(p.get("situationCode")),
                  dside=_s(p.get("homeTeamDefendingSide")))
        details = p.get("details")
        if isinstance(details, dict) and details:
            ev["d"] = {k: v for k, v in details.items() if isinstance(v, (str, int, float, bool))}
            owner = ev["d"].get("eventOwnerTeamId")
            if owner is not None:
                ev["team"] = str(owner)
        events.append(ev)
    events.sort(key=lambda e: (e["n"], e.get("id") or ""))
    roster = {}
    for r in feed.get("rosterSpots") or []:
        pid = _s(r.get("playerId"))
        if pid:
            name = f"{(r.get('firstName') or {}).get('default', '')} {(r.get('lastName') or {}).get('default', '')}".strip()
            roster[pid] = [name, _s(r.get("teamId")), _s(r.get("positionCode")), r.get("sweaterNumber")]
    home, away = feed.get("homeTeam") or {}, feed.get("awayTeam") or {}
    extras = _put({"roster": roster}, nhle_game_id=_s(feed.get("id")), game_state=_s(feed.get("gameState")),
                  home_team_id=_s(home.get("id")), away_team_id=_s(away.get("id")),
                  home_abbrev=_s(home.get("abbrev")), away_abbrev=_s(away.get("abbrev")),
                  home_score=_int(home.get("score")), away_score=_int(away.get("score")),
                  game_date=_s(feed.get("gameDate")))
    return events, extras


# -- compact store -----------------------------------------------------------------------------------------------

def _line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(events: Iterable[dict], drives: Iterable[dict] = ()) -> str:
    digest = hashlib.sha256()
    for obj in list(events) + list(drives):
        digest.update(_line(obj).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


class PbpStore:
    """Append-only play-by-play files under an ESPN store root (data/datasvc/espn)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, league: str, season) -> Path:
        return self.root / league / f"pbp_{season}.jsonl.gz"

    def index_path(self, league: str, season) -> Path:
        return self.root / league / f"pbp_{season}.index.jsonl"

    def seasons(self, league: str) -> List[str]:
        d = self.root / league
        return sorted(p.name[len("pbp_"):-len(".index.jsonl")] for p in d.glob("pbp_*.index.jsonl")) if d.exists() else []

    def index(self, league: str, season) -> List[dict]:
        path = self.index_path(league, season)
        if not path.exists():
            return []
        out = []
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError as exc:
                        raise ValueError(f"{path}:{number}: not JSON: {exc}") from None
        return out

    def newest(self, league: str, season, game_id: str, source: str) -> Optional[dict]:
        best = None
        for row in self.index(league, season):
            if row["game_id"] == str(game_id) and row["source"] == source:
                if best is None or row["observed_utc"] >= best["observed_utc"]:
                    best = row
        return best

    def newest_by_game(self, league: str, season) -> Dict[Tuple[str, str], dict]:
        out: Dict[Tuple[str, str], dict] = {}
        for row in self.index(league, season):
            k = (row["game_id"], row["source"])
            if k not in out or row["observed_utc"] >= out[k]["observed_utc"]:
                out[k] = row
        return out

    def append_game(self, league: str, season, game_id: str, source: str, observed_utc: str,
                    events: List[dict], drives: Iterable[dict] = (), header: Optional[dict] = None) -> str:
        """'added' | 'versioned' | 'unchanged'. Writes the member, then its index line."""
        if source not in SOURCES:
            raise ValueError(f"unknown pbp source {source!r}")
        drives = list(drives)
        digest = content_hash(events, drives)
        old = self.newest(league, season, game_id, source)
        if old is not None and old["sha256"] == digest:
            return "unchanged"
        head = {"k": "game", "league": league, "game_id": str(game_id), "season": season, "source": source,
                "observed_utc": observed_utc, "events": len(events)}
        head.update(header or {})
        raw = "\n".join([_line(head)] + [_line(e) for e in events] + [_line(d) for d in drives]) + "\n"
        member = gzip.compress(raw.encode("utf-8"), compresslevel=9, mtime=0)
        path = self.path(league, season)
        path.parent.mkdir(parents=True, exist_ok=True)
        offset = path.stat().st_size if path.exists() else 0
        with path.open("ab") as handle:
            handle.write(member)
            handle.flush()
            os.fsync(handle.fileno())
        index_row = {"game_id": str(game_id), "source": source, "observed_utc": observed_utc, "offset": offset,
                     "length": len(member), "events": len(events), "drives": len(drives), "sha256": digest,
                     "raw_bytes": len(raw.encode("utf-8"))}
        with self.index_path(league, season).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_line(index_row) + "\n")
        return "added" if old is None else "versioned"

    def _member(self, league: str, season, row: dict) -> Tuple[dict, List[dict], List[dict]]:
        with self.path(league, season).open("rb") as handle:
            handle.seek(row["offset"])
            blob = handle.read(row["length"])
        header, events, drives = None, [], []
        for line in gzip.decompress(blob).decode("utf-8").splitlines():
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("k") == "game":
                header = obj
            elif obj.get("k") == "drive":
                drives.append(obj)
            else:
                events.append(obj)
        if header is None:
            raise ValueError(f"{self.path(league, season)}: member at {row['offset']} has no header")
        return header, events, drives

    def read(self, league: str, season, game_id: str, source: str, *, as_of: Optional[str] = None,
             allow_reconstructed: bool = False) -> Optional[dict]:
        """{header, events, drives, index} for a game: the newest version observed at or before `as_of`
        (newest overall without it). With `allow_reconstructed`, a game only seen after `as_of` falls back
        to its earliest version (the caller has decided the game was final by then)."""
        rows = [r for r in self.index(league, season) if r["game_id"] == str(game_id) and r["source"] == source]
        if not rows:
            return None
        rows.sort(key=lambda r: r["observed_utc"])
        if as_of is not None:
            seen = [r for r in rows if r["observed_utc"] <= as_of]
            if seen:
                pick = seen[-1]
            elif allow_reconstructed:
                pick = rows[0]
            else:
                return None
        else:
            pick = rows[-1]
        header, events, drives = self._member(league, season, pick)
        return {"header": header, "events": events, "drives": drives, "index": pick}

    def verify(self, league: str, season) -> List[str]:
        """Problems found re-reading every indexed member (empty list = parity holds)."""
        problems = []
        path = self.path(league, season)
        rows = self.index(league, season)
        if rows and not path.exists():
            return [f"{league} {season}: index lists {len(rows)} members but {path.name} is missing"]
        size = path.stat().st_size if path.exists() else 0
        for row in rows:
            tag = f"{league} {season} {row['source']} {row['game_id']}@{row['offset']}"
            if row["offset"] + row["length"] > size:
                problems.append(f"{tag}: member runs past the end of the file")
                continue
            try:
                header, events, drives = self._member(league, season, row)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{tag}: unreadable ({exc})")
                continue
            if len(events) != row["events"] or content_hash(events, drives) != row["sha256"]:
                problems.append(f"{tag}: content does not match its index line")
            if header.get("game_id") != row["game_id"] or header.get("source") != row["source"]:
                problems.append(f"{tag}: header disagrees with its index line")
        return problems

    def sizes(self, league: str) -> Dict[str, dict]:
        out = {}
        for season in self.seasons(league):
            gz = self.path(league, season)
            idx = self.index_path(league, season)
            rows = self.index(league, season)
            out[season] = {"games": len({(r["game_id"], r["source"]) for r in rows}), "members": len(rows),
                           "gz_bytes": gz.stat().st_size if gz.exists() else 0,
                           "index_bytes": idx.stat().st_size if idx.exists() else 0}
        return out
