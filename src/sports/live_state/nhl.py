"""NHL live game state from the league's own free Stats API (api-web.nhle.com): no key, no Odds API credit.

WHY THIS EXISTS (live hounds, phase L1, 2026-10-29)
----------------------------------------------------
The live board's score comes from ESPN (``src/sports/live_feed.py``) and says who leads and what period it is. The live
hounds that come next need the SITUATION: who is on a power play, whose net is empty, who is in goal and how he is playing
tonight, who has the points, how the shots stand. ESPN's hockey scoreboard carries none of it. The NHL's own API carries
all of it:

    /v1/score/now                       every game of the day in ONE request: state, period, clock, score, shots
    /v1/gamecenter/{id}/boxscore        one game: both teams' full names, skaters and goalies with tonight's stats
    /v1/gamecenter/{id}/play-by-play    one game: every event with its ``situationCode``

The first is read every 30 seconds. The other two are read for a LIVE or CRIT game at most every 60 seconds and at most
``MAX_REQUESTS_PER_PASS`` requests per pass (oldest read first, so a night of 16 games never starves one).

WHAT IS DERIVED, AND THE RULE FOR EVERY FIELD: unknown or contradictory is None, never a guess
-----------------------------------------------------------------------------------------------
  strength        the LATEST play's four digit ``situationCode`` = (away goalie, away skaters, home skaters, home goalie).
                  A goalie digit of 0 is an empty net. A side's EXTRA ATTACKER (a pulled goalie is replaced by a sixth
                  skater) is not a penalty advantage, so a power play is read from the skater counts AFTER taking that
                  attacker off: 6v5 with a pulled goalie is even strength with an empty net; 6v4 is a power play AND an
                  empty net. A code that is not four digits, has a goalie digit other than 0 or 1, has fewer than 3
                  skaters on a side, or has both nets empty is None. During an intermission and in a shootout there is no
                  strength (None). The latest play can be old: when the game clock has moved more than
                  ``MAX_PLAY_GAP_SECONDS`` past it in the same period the code might describe a power play that has
                  ended, so it is None. A power play that expires is only SEEN at the next event; the gap rule bounds
                  how long that can be wrong.
  goalies         per team, the goalie in net: the ``goalieInNetId`` of the latest shot (or goal) AGAINST that team, else
                  (no shot against yet tonight) the boxscore goalie with the most time on ice if exactly one has any.
                  An empty-net shot, a goalie who is not on the boxscore, or a net the situation code says is empty is
                  None. With his saves, shots against and save percentage tonight (None before the first shot).
  skaters         every skater on the boxscore: goals, assists, points, shots on goal, time on ice in seconds.
  goals_by_period counted from the play-by-play's goal events, and None unless the count equals that same document's own
                  score for both teams (a goal that landed between two reads would otherwise be filed under the wrong
                  period). Shootout attempts are not goals here.

THE STATE DICT (plain, JSON-safe; every key is always present)
--------------------------------------------------------------
  sport "NHL", source "nhl_api", game_id (str), state "upcoming"|"live"|"final"|"postponed"|None, game_state (the API's
  own FUT/PRE/LIVE/CRIT/FINAL/OFF), start_utc, period, period_type "REG"|"OT"|"SO", period_label "2nd"|"OT"|"2OT"|"SO",
  clock "8:14", seconds_remaining, clock_running, in_intermission,
  home / away {abbrev, name, score, sog},
  strength {code, away_skaters, home_skaters, pp_side "home"|"away"|None, pp_matchup "5v4"|None, empty_net "home"|"away"|None,
            as_of_period, as_of_time_remaining} | None,
  goalies {"home": {id, name, saves, shots_against, save_pct} | None, "away": ...} | None,
  skaters {"home": [{id, name, pos, g, a, p, sog, toi_s}], "away": [...]} | None,
  goals_by_period [{period, type, away, home}] | None,
  as_of, detail_as_of  (stamped by the store).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Iterable, Mapping, Optional

from src.hounds import live_scores as ls
from src.sports.live_state import names, store

SPORT = "NHL"
SCORE_URL = "https://api-web.nhle.com/v1/score/now"
BOX_URL = "https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore"
PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play"

SCORE_EVERY_SECONDS = 30.0               # one request for every game of the day
DETAIL_EVERY_SECONDS = 60.0              # boxscore + play-by-play for one live game
MAX_REQUESTS_PER_PASS = 21               # 1 score read + 10 games' (box, pbp); a night of 16 live games is served oldest-first
MAX_PLAY_GAP_SECONDS = 90                # see the module docstring: older than this and the strength is unknown
IDLE_EVERY_SECONDS = 300.0               # nothing live and nothing starting soon: look again in five minutes
LEAD_MINUTES = 25                        # a game this close to its start counts as "about to be live"

LIVE_STATES = ("LIVE", "CRIT")
FINAL_STATES = ("FINAL", "OFF")
UPCOMING_STATES = ("FUT", "PRE")
SHOT_KINDS = ("shot-on-goal", "goal")

# The place name each club's full name starts with, by abbreviation: the score read carries only the nickname
# ("Sharks"), the boxscore carries the place, and a game must be matchable from its FIRST read. The boxscore's own
# ``placeName`` overrides this the moment it is read, so a relocation is corrected by the API itself.
_PLACES = {
    "ANA": "Anaheim", "BOS": "Boston", "BUF": "Buffalo", "CGY": "Calgary", "CAR": "Carolina", "CHI": "Chicago",
    "COL": "Colorado", "CBJ": "Columbus", "DAL": "Dallas", "DET": "Detroit", "EDM": "Edmonton", "FLA": "Florida",
    "LAK": "Los Angeles", "MIN": "Minnesota", "MTL": "Montréal", "NSH": "Nashville", "NJD": "New Jersey",
    "NYI": "New York", "NYR": "New York", "OTT": "Ottawa", "PHI": "Philadelphia", "PIT": "Pittsburgh",
    "SJS": "San Jose", "SEA": "Seattle", "STL": "St. Louis", "TBL": "Tampa Bay", "TOR": "Toronto", "UTA": "Utah",
    "VAN": "Vancouver", "VGK": "Vegas", "WSH": "Washington", "WPG": "Winnipeg",
}


# ---------------------------------------------------------------------------
# small parsers
# ---------------------------------------------------------------------------

def _int(value) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _text(value) -> str:
    if isinstance(value, Mapping):
        value = value.get("default")
    return "" if value is None or isinstance(value, bool) else str(value).strip()


def mmss_to_seconds(value) -> Optional[int]:
    """"16:19" -> 979, "03:00" -> 180; anything else None."""
    parts = str(value or "").strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]) * 60 + int(parts[1])


def seconds_to_clock(seconds) -> Optional[str]:
    s = _int(seconds)
    return None if s is None or s < 0 else f"{s // 60}:{s % 60:02d}"


def period_label(number, period_type, regulation_periods) -> Optional[str]:
    """1 -> "1st", 4/OT -> "OT", 5/OT -> "2OT" (a playoff game), SO -> "SO"."""
    n, reg = _int(number), _int(regulation_periods) or 3
    kind = str(period_type or "").upper()
    if n is None or n < 1:
        return None
    if kind == "SO":
        return "SO"
    if kind == "OT" or n > reg:
        extra = n - reg
        return None if extra < 1 else ("OT" if extra == 1 else f"{extra}OT")
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def state_word(game_state, schedule_state=None) -> Optional[str]:
    gs = str(game_state or "").upper()
    sched = str(schedule_state or "OK").upper()
    if sched in ("PPD", "SUSP", "CNCL", "TBD"):
        return "postponed"
    if gs in LIVE_STATES:
        return "live"
    if gs in FINAL_STATES:
        return "final"
    if gs in UPCOMING_STATES:
        return "upcoming"
    return None


# ---------------------------------------------------------------------------
# strength from the situation code
# ---------------------------------------------------------------------------

def strength_from_code(code) -> Optional[dict]:
    """The strength a four digit situationCode describes, or None when the code cannot be right (see the module docstring).

    "1551" 5v5 · "1451" away is a man down: home power play 5v4 · "1541" away power play · "0651" away goalie pulled, a
    sixth skater: 6v5 EMPTY NET and no power play · "0641" 6v4: away power play AND an empty net · "1331" 3v3 overtime."""
    text = str(code if code is not None else "").strip()
    if len(text) != 4 or not text.isdigit():
        return None
    away_g, away_s, home_s, home_g = (int(c) for c in text)
    if away_g not in (0, 1) or home_g not in (0, 1) or (away_g == 0 and home_g == 0):
        return None
    away_eff = away_s - (1 if away_g == 0 else 0)          # a pulled goalie's replacement is an extra attacker, not a penalty gap
    home_eff = home_s - (1 if home_g == 0 else 0)
    if not (3 <= away_eff <= 5 and 3 <= home_eff <= 5):
        return None
    pp_side = "away" if away_eff > home_eff else "home" if home_eff > away_eff else None
    matchup = f"{max(away_eff, home_eff)}v{min(away_eff, home_eff)}" if pp_side else None
    return {"code": text, "away_skaters": away_s, "home_skaters": home_s, "pp_side": pp_side, "pp_matchup": matchup,
            "empty_net": "away" if away_g == 0 else "home" if home_g == 0 else None}


def _play_sort_key(play: Mapping):
    order = _int(play.get("sortOrder"))
    return (0, order) if order is not None else (1, _int(play.get("eventId")) or 0)


def latest_play(plays: Iterable[Mapping]) -> Optional[Mapping]:
    rows = [p for p in plays or [] if isinstance(p, Mapping)]
    return max(rows, key=_play_sort_key) if rows else None


def strength_now(pbp: Mapping, in_intermission: bool, period_type: str) -> Optional[dict]:
    """The strength at the latest play of a play-by-play document, with the intermission, shootout and gap rules applied."""
    if in_intermission or str(period_type or "").upper() == "SO":
        return None
    play = latest_play(pbp.get("plays"))
    if play is None:
        return None
    found = strength_from_code(play.get("situationCode"))
    if found is None:
        return None
    pdesc = play.get("periodDescriptor") or {}
    clock = pbp.get("clock") or {}
    play_left = mmss_to_seconds(play.get("timeRemaining"))
    now_left = _int(clock.get("secondsRemaining"))
    same_period = _int(pdesc.get("number")) == _int((pbp.get("periodDescriptor") or {}).get("number"))
    if not same_period or play_left is None or now_left is None:
        return None                                       # a play from another period, or a clock we cannot read: unknown
    if play_left - now_left > MAX_PLAY_GAP_SECONDS:
        return None
    found["as_of_period"] = _int(pdesc.get("number"))
    found["as_of_time_remaining"] = seconds_to_clock(play_left)
    return found


# ---------------------------------------------------------------------------
# the base layer (score read or boxscore header)
# ---------------------------------------------------------------------------

def _team_block(team: Mapping, side: str, full_name: Optional[str] = None) -> dict:
    abbrev = _text(team.get("abbrev")) or None
    if full_name is None and abbrev in _PLACES:
        nick = _text(team.get("commonName")) or _text(team.get("name"))
        full_name = f"{_PLACES[abbrev]} {nick}".strip() if nick else None
    return {"abbrev": abbrev, "name": full_name, "score": _int(team.get("score")), "sog": _int(team.get("sog")),
            "id": _int(team.get("id"))}


def full_name_of(team: Mapping) -> Optional[str]:
    """placeName + commonName from a boxscore / play-by-play team block ("San Jose" + "Sharks"), or None unless both are there."""
    place, common = _text(team.get("placeName")), _text(team.get("commonName"))
    return f"{place} {common}" if place and common else None


def base_from_game(doc: Mapping) -> Optional[dict]:
    """The base layer from ONE game object, which has the same shape in the score read's ``games`` list and in a
    boxscore / play-by-play document. None when the game has no id or no readable teams."""
    if not isinstance(doc, Mapping):
        return None
    gid = doc.get("id")
    away, home = doc.get("awayTeam"), doc.get("homeTeam")
    if gid is None or not isinstance(away, Mapping) or not isinstance(home, Mapping):
        return None
    pdesc = doc.get("periodDescriptor") if isinstance(doc.get("periodDescriptor"), Mapping) else {}
    clock = doc.get("clock") if isinstance(doc.get("clock"), Mapping) else {}
    number = _int(pdesc.get("number")) if pdesc else _int(doc.get("period"))
    ptype = str(pdesc.get("periodType") or "").upper() or None
    reg = _int(pdesc.get("maxRegulationPeriods")) or _int(doc.get("regPeriods")) or 3
    seconds = _int(clock.get("secondsRemaining"))
    state = state_word(doc.get("gameState"), doc.get("gameScheduleState"))
    live = state == "live"
    away_block = _team_block(away, "away", full_name_of(away))
    home_block = _team_block(home, "home", full_name_of(home))
    return {
        "sport": SPORT, "source": "nhl_api", "game_id": str(gid), "state": state, "game_state": str(doc.get("gameState") or "") or None,
        "start_utc": _text(doc.get("startTimeUTC")) or None,
        "period": number if live or state == "final" else None,
        "period_type": ptype if live or state == "final" else None,
        "period_label": period_label(number, ptype, reg) if live or state == "final" else None,
        "clock": seconds_to_clock(seconds) if live else None,
        "seconds_remaining": seconds if live else None,
        "clock_running": clock.get("running") if live and isinstance(clock.get("running"), bool) else None,
        "in_intermission": clock.get("inIntermission") if live and isinstance(clock.get("inIntermission"), bool) else None,
        "away": away_block, "home": home_block,
    }


def parse_score_now(doc: Mapping) -> list:
    """Every game of a /score/now document as a base dict (all states). A game that cannot be read is left out."""
    out = []
    for game in (doc.get("games") or []) if isinstance(doc, Mapping) else []:
        base = base_from_game(game)
        if base is not None:
            out.append(base)
    return out


# ---------------------------------------------------------------------------
# the detail layer (boxscore + play-by-play)
# ---------------------------------------------------------------------------

def _skaters(team_stats: Mapping) -> list:
    out = []
    for group in ("forwards", "defense"):
        for p in team_stats.get(group) or []:
            if not isinstance(p, Mapping) or p.get("playerId") is None:
                continue
            out.append({"id": _int(p.get("playerId")), "name": _text(p.get("name")) or None, "pos": _text(p.get("position")) or None,
                        "g": _int(p.get("goals")), "a": _int(p.get("assists")), "p": _int(p.get("points")),
                        "sog": _int(p.get("sog")), "toi_s": mmss_to_seconds(p.get("toi"))})
    return out


def _goalie_row(goalie: Mapping) -> dict:
    saves, against = _int(goalie.get("saves")), _int(goalie.get("shotsAgainst"))
    pct = round(saves / against, 3) if saves is not None and against else None
    return {"id": _int(goalie.get("playerId")), "name": _text(goalie.get("name")) or None, "saves": saves,
            "shots_against": against, "save_pct": pct}


def goalies_in_net(box: Mapping, plays: Iterable[Mapping], strength: Optional[Mapping]) -> dict:
    """{"home": row|None, "away": row|None}: see the module docstring. `strength` may be None (then the empty-net check is skipped)."""
    stats = box.get("playerByGameStats") or {}
    out = {}
    team_ids = {"home": _int((box.get("homeTeam") or {}).get("id")), "away": _int((box.get("awayTeam") or {}).get("id"))}
    ordered = sorted((p for p in plays or [] if isinstance(p, Mapping) and p.get("typeDescKey") in SHOT_KINDS), key=_play_sort_key)
    for side, other in (("home", "away"), ("away", "home")):
        roster = {_int(g.get("playerId")): g for g in (stats.get(f"{side}Team") or {}).get("goalies") or [] if isinstance(g, Mapping)}
        out[side] = None
        if strength and strength.get("empty_net") == side:
            continue
        against = [p for p in ordered if _int((p.get("details") or {}).get("eventOwnerTeamId")) == team_ids[other]
                   and team_ids[other] is not None]
        if against:
            gid = _int((against[-1].get("details") or {}).get("goalieInNetId"))
            if gid is not None and gid in roster:
                out[side] = _goalie_row(roster[gid])
            continue                                            # an empty-net shot or a goalie we cannot place: unknown
        busy = [(mmss_to_seconds(g.get("toi")) or 0, g) for g in roster.values()]
        busy = [(t, g) for t, g in busy if t > 0]
        if len(busy) == 1:
            out[side] = _goalie_row(busy[0][1])
        elif len(busy) > 1:
            top = max(t for t, _g in busy)
            leaders = [g for t, g in busy if t == top]
            out[side] = _goalie_row(leaders[0]) if len(leaders) == 1 else None
    return out


def goals_by_period(pbp: Mapping) -> Optional[list]:
    """[{period, type, away, home}] for each period played so far, or None when the goal events do not add up to the
    document's own score (see the module docstring)."""
    away_id, home_id = _int((pbp.get("awayTeam") or {}).get("id")), _int((pbp.get("homeTeam") or {}).get("id"))
    if away_id is None or home_id is None:
        return None
    current = _int((pbp.get("periodDescriptor") or {}).get("number")) or 0
    reg = _int((pbp.get("periodDescriptor") or {}).get("maxRegulationPeriods")) or 3
    tally: dict = {}
    for play in pbp.get("plays") or []:
        if not isinstance(play, Mapping) or play.get("typeDescKey") != "goal":
            continue
        pdesc = play.get("periodDescriptor") or {}
        n, kind = _int(pdesc.get("number")), str(pdesc.get("periodType") or "").upper()
        if n is None or kind == "SO":
            continue
        owner = _int((play.get("details") or {}).get("eventOwnerTeamId"))
        if owner not in (away_id, home_id):
            return None
        row = tally.setdefault(n, {"period": n, "type": "OT" if kind == "OT" or n > reg else "REG", "away": 0, "home": 0})
        row["away" if owner == away_id else "home"] += 1
    away_score, home_score = _int((pbp.get("awayTeam") or {}).get("score")), _int((pbp.get("homeTeam") or {}).get("score"))
    if away_score is None or home_score is None:
        return None
    if sum(r["away"] for r in tally.values()) != away_score or sum(r["home"] for r in tally.values()) != home_score:
        return None
    rows = []
    for n in range(1, max(current, max(tally, default=0)) + 1):
        rows.append(tally.get(n) or {"period": n, "type": "OT" if n > reg else "REG", "away": 0, "home": 0})
    return rows


def derive_detail(box: Mapping, pbp: Mapping) -> dict:
    """The detail layer from one boxscore and one play-by-play of the SAME game: {strength, goalies, skaters, goals_by_period, names}."""
    pdesc = pbp.get("periodDescriptor") or {}
    clock = pbp.get("clock") or {}
    in_intermission = bool(clock.get("inIntermission"))
    strength = strength_now(pbp, in_intermission, str(pdesc.get("periodType") or ""))
    stats = box.get("playerByGameStats") or {}
    return {
        "strength": strength,
        "goalies": goalies_in_net(box, pbp.get("plays"), strength),
        "skaters": {"home": _skaters(stats.get("homeTeam") or {}), "away": _skaters(stats.get("awayTeam") or {})},
        "goals_by_period": goals_by_period(pbp),
        "names": {"home": full_name_of(box.get("homeTeam") or {}), "away": full_name_of(box.get("awayTeam") or {})},
    }


# ---------------------------------------------------------------------------
# the read
# ---------------------------------------------------------------------------

def fetch_and_store(now: datetime, fetch_json: Callable[[str], dict], *, max_requests: int = MAX_REQUESTS_PER_PASS,
                    budget_left: Optional[Callable[[], bool]] = None) -> dict:
    """One NHL pass: the score read, then the detail reads that are due. Returns a small report. Nothing here raises for
    one bad request; a failed detail read keeps the old detail layer (which then ages out by itself)."""
    report = {"requests": 0, "games": 0, "live": 0, "detail_ok": [], "detail_failed": [], "active": False, "error": None}
    report["requests"] += 1
    try:
        doc = fetch_json(SCORE_URL)
    except Exception as exc:  # noqa: BLE001 -- the loop outlives any one bad read
        report["error"] = f"score: {type(exc).__name__}"
        return report
    bases = parse_score_now(doc)
    store.STATUS["nhl_last_read_utc"] = ls.iso(now)
    seen = set()
    for base in bases:
        seen.add(base["game_id"])
        names_here = {"home": base["home"].get("name"), "away": base["away"].get("name")}
        store.put_base(SPORT, base["game_id"], base, now, names=names_here)
    report["games"] = len(bases)
    live = [b for b in bases if b["state"] == "live"]
    report["live"] = len(live)
    horizon = LEAD_MINUTES * 60
    soon = [b for b in bases if b["state"] == "upcoming" and (ls.parse_utc(b["start_utc"]) is not None)
            and -3 * 3600 <= (ls.parse_utc(b["start_utc"]) - now).total_seconds() <= horizon]
    report["active"] = bool(live or soon)
    # a game we were tracking as live that the day's list no longer carries (the list rolls to the next day): ask it directly
    gone = [gid for gid in store.known_ids(SPORT) if gid not in seen and _tracked_live(gid, now)]
    wanted = [b["game_id"] for b in live] + gone
    wanted.sort(key=lambda gid: (store.detail_age(SPORT, gid, now) is not None, -(store.detail_age(SPORT, gid, now) or 0.0)))
    for gid in wanted:
        age = store.detail_age(SPORT, gid, now)
        if age is not None and 0 <= age < DETAIL_EVERY_SECONDS:
            continue
        if report["requests"] + 2 > max_requests or (budget_left is not None and not budget_left()):
            break
        report["requests"] += 2
        try:
            box = fetch_json(BOX_URL.format(gid=gid))
            pbp = fetch_json(PBP_URL.format(gid=gid))
            detail = derive_detail(box, pbp)
        except Exception as exc:  # noqa: BLE001
            report["detail_failed"].append(gid)
            report["error"] = f"detail {gid}: {type(exc).__name__}"
            continue
        detail_names = detail.pop("names")
        store.put_detail(SPORT, gid, detail, now, names=detail_names)
        if gid in gone:
            base = base_from_game(box)
            if base is not None:
                store.put_base(SPORT, gid, base, now, names=detail_names)
        report["detail_ok"].append(gid)
    return report


def _tracked_live(gid: str, now: datetime) -> bool:
    view = store.get(SPORT, gid, now)
    return bool(view and view.get("state") == "live")


# ---------------------------------------------------------------------------
# lookup and the snapshot row
# ---------------------------------------------------------------------------

def match(home_name: str, away_name: str, commence: Optional[datetime], games: Iterable[Mapping]) -> Optional[dict]:
    """The ONE game that fits both names in the same orientation and the start window, or None (see names.py)."""
    hits = []
    for game in games:
        if not names.within(commence, ls.parse_utc(game.get("start_utc")), names.NHL_WINDOW):
            continue
        if names.nhl_team_matches(home_name, game["home"]) and names.nhl_team_matches(away_name, game["away"]):
            hits.append(game)
    return hits[0] if len(hits) == 1 else None


def log_row(state: Mapping) -> dict:
    """The compact row the snapshot log keeps (short keys, only skaters who have a point or a shot)."""
    def team(block):
        return [block.get("abbrev"), block.get("score"), block.get("sog")]

    strength = state.get("strength") or {}
    goalies = state.get("goalies") or {}

    def goalie(row):
        return None if not row else [row.get("id"), row.get("saves"), row.get("shots_against")]

    skaters = state.get("skaters") or {}

    def active(rows):
        return [[s["id"], s["g"], s["a"], s["sog"]] for s in rows if (s.get("p") or 0) > 0 or (s.get("sog") or 0) > 0]

    return {"t": state.get("as_of"), "sp": SPORT, "id": state.get("game_id"), "st": state.get("state"),
            "p": state.get("period"), "pt": state.get("period_type"), "sr": state.get("seconds_remaining"),
            "im": state.get("in_intermission"), "a": team(state.get("away") or {}), "h": team(state.get("home") or {}),
            "str": None if not strength else [strength.get("code"), strength.get("pp_side"), strength.get("empty_net")],
            "gk": None if not goalies else {"h": goalie(goalies.get("home")), "a": goalie(goalies.get("away"))},
            "sk": None if not skaters else {"h": active(skaters.get("home") or []), "a": active(skaters.get("away") or [])},
            "gp": state.get("goals_by_period")}


def signature(row: Mapping):
    """What counts as a CHANGE for the log: everything in the row except the read time and the clock."""
    keys = ("sp", "id", "st", "p", "pt", "im", "a", "h", "str", "gk", "sk", "gp")
    return json.dumps({k: row.get(k) for k in keys}, sort_keys=True, separators=(",", ":"))


def is_live_row(row: Mapping) -> bool:
    return row.get("st") == "live"
