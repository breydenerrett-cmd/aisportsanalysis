"""The NFL game packet: everything the analyst may know about one game, frozen.

THE SAME CONTRACT AS THE MLB AND UFC PACKETS, A THIRD SPORT
-----------------------------------------------------------
`src/analyst/packet.py` explains why a packet exists (self-contained, frozen and hashable, honest
about holes) and the path grammar the critic checks claims against. None of that changes here, and
the shapes the critic, the grader and the ledger read are the same on purpose: `game` (identity,
state, kickoff), `markets` keyed by slot id with each market's `options` (lean first) and each
option's `quotes` of `{book, price, captured_utc}`, `slots`, `missing`, `limits`. The helpers that
build a quote, an option and a market are the MLB packet's own (`packet._option` and friends), so
there is exactly one definition of "the lean", "the best quote" and the de-vigged consensus.

A `game` block (and no `bout`) is what makes the analyst treat a packet as the MLB kind: the case
against, declared calculations and the reader-word bans all follow from that one test
(`analyst.is_mlb_packet`), which is why this packet is built to pass it.

WHAT COMES FROM WHERE
---------------------
The teams, their form, rest, travel, quarterbacks, injuries and head to head come from
`src.datasvc.nfl.matchup.matchup(store, game_id, as_of=...)`, the NFL data service's own fact
sheet, which admits only games that finished (kickoff plus six hours) before `as_of`. The odds come
from `data/processed/odds_multibook.jsonl` rows the caller hands in (the loader in
`nfl_pilot.default_rows` streams them): one quote per book per market with the time it was
captured. This module adds no statistic of its own beyond rounding-free restructuring.

The schedule file's own market (`spread_line`, `total_line`, the moneylines) is NOT used. It is one
value per game that nflverse overwrites as the market moves, so for a game that is final it is the
closing line and for one that is not it carries no capture time. A price with no capture time
cannot be shown to precede the game, so the only prices in the packet are the multibook quotes.

NO FUTURE LEAKAGE, FIVE WAYS
----------------------------
1. Features are as of `min(built_at, kickoff)`. Nothing that finished after the packet was built
   can be in a form figure (a late game's packet must not see an early game's result that ended
   after the freeze), and nothing at or after kickoff can be either.
2. The game block is a whitelist (identity, state, kickoff, venue, teams). The final score a
   finished game carries never enters it.
3. A quote enters only when it was captured at or before `built_at` AND strictly before the start.
   The start is the EARLIER of the schedule's kickoff and the odds feed's `commence_time`, so a
   game moved earlier by the feed is cut off at the earlier time. A quote that cannot be dated is
   dropped.
4. The quarterback the schedule lists for the game is a projection recorded when the schedule was
   fetched. It is kept only when that fetch time (`fetched_utc`) is not after `built_at`; the
   store overwrites a changed row, so a later fetch cannot be taken back to `built_at` and the
   listing is left out, with a `missing` entry that says why. The injury report is gated the same
   way: any report row first fetched after `built_at` withdraws the whole team's report.
5. Observed temperature and wind are recorded at game time and are never read. Neither a weather
   forecast nor a roof state for the day is in the stores, so `missing` says weather is absent for
   a game played outdoors.

THE SLOTS
---------
`moneyline`: the two teams, the likelier side first.
`spread`: the two teams at the most-quoted number, the side with the higher margin-free
probability first. Each selection carries its own signed number ("LAC +3.5", "KC -3.5").
`total`: Over and Under the most-quoted number.

A slot exists only when both of its sides are quoted. Nothing is inferred and nothing is filled in.
No NFL player-prop or alternate-line price is stored anywhere, so no slot exists for one and
`missing` says so.

READING IT
----------
`how_to_read` is part of the packet. Which team a difference favours, what a window's games count
means and how a spread number is signed are facts about THIS packet's shape; the prompt cannot say
them and the packet is archived with every call.

Pure: no I/O of its own (it reads the store and the rows it is handed), no clock, no network, no
api/ import.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional, Sequence

from src.analyst import packet as base
from src.datasvc.nfl import features as feat
from src.datasvc.nfl import matchup as mu
from src.datasvc.nfl.timeutil import iso_utc, parse_instant
from src.sports import nfl_teams

PACKET_VERSION = "analyst_nfl_packet_v1"

SLOT_ORDER = ("moneyline", "spread", "total")

# The odds feed and the schedule must agree about which game a row is. A pair of clubs meets once
# in a season outside the playoffs, so "the same two clubs and a start within this long of the
# schedule's kickoff" is the game. A day and a half covers a Thursday game listed by UTC date and
# a flexed game, and keeps a rematch weeks later out.
EVENT_WINDOW = timedelta(hours=36)

# The schedule and the odds feed may disagree about the start by a minute or two of rounding; a
# bigger gap is worth saying in `missing` (the packet is cut off at the earlier one either way).
KICKOFF_DISAGREEMENT = timedelta(minutes=5)

# Scoring values and the margins they stack into. Facts of how football is scored, labelled as
# such, so a reader (and the critic's number check) can use "a field goal is three points" and
# talk about the key numbers 3 and 7 without any of them being a number from nowhere. No
# frequency of any margin is stated anywhere in the packet, because none is measured here.
SCORING = {"field_goal": 3, "touchdown": 6, "extra_point": 1, "two_point_conversion": 2, "safety": 2}
KEY_NUMBERS = [3, 6, 7, 10, 14]
REFERENCE_NOTE = (
    "scoring values and the margins they add up to: a field goal is 3, a touchdown 6, an extra point 1, "
    "a two-point conversion 2 and a safety 2, so final margins pile up on 3, 6, 7, 10 and 14. "
    "These are how the game is scored; the packet states no frequency for any margin"
)

# Roof types for which the weather cannot matter, as the schedule file spells them.
INDOOR_ROOFS = ("dome", "closed")

FORM_WINDOWS = ("last_3", "last_5", "season_to_date")
LAST_GAMES_SHOWN = 3

TEAM_BASIS = "games the data store holds as finished before this packet was built"
SCHEDULE_BASIS = "the published schedule, fixed before the game"
MATCHUP_BASIS = "the same finished games, both teams compared (home minus away)"

# Words in a store status mapped to the ledger's: a game "scheduled" in the store is "pending" to
# the analyst's publish rule (analyst.ledger.PUBLISHABLE_STATES). Any other status is passed
# through, so a game the store calls final or removed is never published.
_STATE = {"scheduled": "pending"}

_DROP_KEYS = frozenset({"player_id", "qb_id", "base_stadium_id", "venue_stadium_id", "last_game_id",
                        "game_id_of_last_game"})


class NflPacketError(ValueError):
    """The packet cannot be built for this game (no such game, no two clubs)."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _instant(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse_instant(value)
    except ValueError:
        return None


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return base._iso(moment)


def _scrub(node: Any) -> Any:
    """A copy with identifier keys dropped and every key made path-safe."""
    if isinstance(node, Mapping):
        return {base._clean_key(k): _scrub(v)
                for k, v in sorted(node.items(), key=lambda kv: str(kv[0]))
                if str(k) not in _DROP_KEYS}
    if isinstance(node, (list, tuple)):
        return [_scrub(v) for v in node]
    if isinstance(node, float) and not math.isfinite(node):
        return None
    return node


def _signed(line: float) -> str:
    """A spread number as written on a selection: +3.5, -3, +0."""
    return f"{line:+g}"


def event_codes(row: Mapping) -> tuple:
    """(away code, home code) of an odds-feed row, from the feed's club names; None for a club the
    NFL map does not know."""
    return nfl_teams.abbrev(row.get("away_team")), nfl_teams.abbrev(row.get("home_team"))


def rows_for_game(rows: Iterable[Mapping], away: str, home: str, kickoff: Optional[datetime]) -> list:
    """The odds-feed rows that are this game: NFL rows between these two clubs whose
    `commence_time` is within `EVENT_WINDOW` of the schedule's kickoff (any rows of the pair when
    the schedule has no kickoff). The one definition of "this game's rows", shared by the loader."""
    out = []
    for r in rows:
        if r.get("sport") != "nfl":
            continue
        if event_codes(r) != (away, home):
            continue
        if kickoff is not None:
            commence = _instant(r.get("commence_time"))
            if commence is None or abs(commence - kickoff) > EVENT_WINDOW:
                continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# the markets
# ---------------------------------------------------------------------------

def _books_on(groups: Mapping, chosen: Any) -> tuple:
    on = len(groups.get(chosen, ()))
    return on, sum(len(v) for v in groups.values()) - on


def _first_captured(rows: Sequence[Mapping], kind: str, cutoff: datetime,
                    start: Optional[datetime]) -> Optional[dict]:
    """Where the market stood the first time this store captured it, for a line-movement sentence.

    Per book the earliest eligible row; the line most books were on at their first capture. It is
    the first capture the store holds, which is not necessarily the opening line (books list at
    different times), and the packet says so in the field's name."""
    earliest: dict = {}
    for row in rows:
        seen = base._parse_utc(row.get("observed_utc") or row.get("ts"))
        if seen is None or seen > cutoff or (start is not None and seen >= start) or not row.get("book"):
            continue
        held = earliest.get(row["book"])
        if held is None or seen < held[0]:
            earliest[row["book"]] = (seen, row)
    groups: dict = {}
    for _book, (seen, row) in earliest.items():
        if kind == "spreads":
            home_line, away_line = base._clean_line(row.get("home_line")), base._clean_line(row.get("away_line"))
            if home_line is None or away_line is None or abs(home_line + away_line) > 1e-9:
                continue
            groups.setdefault(away_line, []).append(seen)
        else:
            line = base._clean_line(row.get("total"))
            if line is not None:
                groups.setdefault(line, []).append(seen)
    line = base._main_line(groups, prefer=0.0)
    if line is None:
        return None
    return {"line": line, "captured_utc": _iso(min(min(v) for v in groups.values())),
            "books": len(groups[line])}


def _moneyline(rows, away, home, cutoff, start) -> Optional[dict]:
    book_rows = base._latest_by_book([r for r in rows if r.get("market") in (None, "h2h")],
                                     cutoff=cutoff, first_pitch=start)
    book_rows = [r for r in book_rows
                 if base._price(r.get("away_price")) is not None
                 or base._price(r.get("home_price")) is not None]
    if not book_rows:
        return None
    qa, qh, fair_a = base._two_way(book_rows, "away_price", "home_price")
    if not qa or not qh:
        return None
    away_opt = base._option(away, "away", None, qa, fair_a)
    home_opt = base._option(home, "home", None, qh, None if fair_a is None else 1 - fair_a)
    return base._market("moneyline", "moneyline", f"{away} at {home} moneyline",
                        base._ordered(away_opt, home_opt))


def _spread(rows, away, home, cutoff, start) -> Optional[dict]:
    spreads = [r for r in rows if r.get("market") == "spreads"]
    book_rows = base._latest_by_book(spreads, cutoff=cutoff, first_pitch=start)
    groups: dict = {}
    for r in book_rows:
        hl, al = base._clean_line(r.get("home_line")), base._clean_line(r.get("away_line"))
        if hl is None or al is None or abs(hl + al) > 1e-9:
            continue
        groups.setdefault(hl, []).append(r)
    home_line = base._main_line(groups, prefer=0.0)
    if home_line is None:
        return None
    qa, qh, fair_a = base._two_way(groups[home_line], "away_price", "home_price")
    if not qa or not qh:
        return None
    away_line = -home_line
    away_opt = base._option(f"{away} {_signed(away_line)}", "away", away_line, qa, fair_a)
    home_opt = base._option(f"{home} {_signed(home_line)}", "home", home_line, qh,
                            None if fair_a is None else 1 - fair_a)
    on, other = _books_on(groups, home_line)
    context = {"books_on_this_number": on, "books_on_other_numbers": other}
    first = _first_captured(spreads, "spreads", cutoff, start)
    if first is not None:
        context.update({"away_number_first_captured": first["line"],
                        "first_captured_utc": first["captured_utc"],
                        "books_at_first_capture": first["books"]})
    return base._market("spread", "spread", f"{away} at {home} point spread",
                        base._ordered(away_opt, home_opt), context)


def _total(rows, away, home, cutoff, start) -> Optional[dict]:
    totals = [r for r in rows if r.get("market") == "totals"]
    book_rows = base._latest_by_book(totals, cutoff=cutoff, first_pitch=start)
    groups: dict = {}
    for r in book_rows:
        line = base._clean_line(r.get("total"))
        if line is not None:
            groups.setdefault(line, []).append(r)
    line = base._main_line(groups, prefer=0.0)
    if line is None:
        return None
    qo, qu, fair_o = base._two_way(groups[line], "over_price", "under_price")
    if not qo or not qu:
        return None
    over = base._option(f"Over {line:g}", "over", line, qo, fair_o)
    under = base._option(f"Under {line:g}", "under", line, qu, None if fair_o is None else 1 - fair_o)
    on, other = _books_on(groups, line)
    context = {"books_on_this_number": on, "books_on_other_numbers": other}
    first = _first_captured(totals, "totals", cutoff, start)
    if first is not None:
        context.update({"number_first_captured": first["line"],
                        "first_captured_utc": first["captured_utc"],
                        "books_at_first_capture": first["books"]})
    return base._market("total", "total", f"{away} at {home} game total points",
                        base._ordered(over, under), context)


# ---------------------------------------------------------------------------
# the team sections
# ---------------------------------------------------------------------------

def _window(w: Mapping) -> dict:
    """One form window, compacted: the games it rests on and the figures, no timestamps."""
    out = {k: w.get(k) for k in ("games", "wins", "losses", "ties", "points_for_per_game",
                                 "points_against_per_game", "margin_per_game")}
    for name in ("yards_per_play", "yards_per_play_allowed"):
        fig = w.get(name) or {}
        out[name] = {"value": fig.get("value"), "games": fig.get("games")}
    tm = w.get("turnover_margin") or {}
    out["turnover_margin"] = {"value": tm.get("value"), "games": tm.get("games"), "total": tm.get("total")}
    return out


def _last_games(block: Mapping) -> list:
    return [{"kickoff_utc": g.get("kickoff_utc"), "week": g.get("week"), "opponent": g.get("opponent"),
             "site": g.get("site"), "points_for": g.get("points_for"),
             "points_against": g.get("points_against"), "result": g.get("result"),
             "margin": g.get("margin")}
            for g in (block.get("last_games") or [])[:LAST_GAMES_SHOWN]]


def _qb(block: Mapping, game_fetched: Optional[datetime], cutoff: datetime,
        start: Optional[datetime]) -> tuple:
    """`(qb section, missing)`. The last finished game's starter is a result and always safe. The
    starter listed for THIS game is a projection stamped only by when the schedule was fetched; it
    is shown only if that fetch precedes the packet and the start."""
    qb = block.get("qb") or {}
    last = (qb.get("last_game") or {}).get("qb_name")
    this = qb.get("this_game") or {}
    missing = []
    out: dict = {"last_game_starter": last}
    team = block.get("team")
    if game_fetched is None:
        missing.append({"item": f"{team}.qb", "kind": "absent",
                        "reason": f"the schedule row has no readable fetch time, so the quarterback it lists "
                                  f"for {team} cannot be shown to precede this packet"})
    elif game_fetched > cutoff or (start is not None and game_fetched >= start):
        missing.append({"item": f"{team}.qb", "kind": "absent",
                        "reason": f"the schedule was fetched at {_iso(game_fetched)}, after this packet was "
                                  f"built, so the quarterback it lists for {team} is not used"})
    elif this.get("qb_name"):
        out["listed_for_this_game"] = {
            "name": this.get("qb_name"),
            "projected": bool(this.get("projected")),
            "listed_as_of_utc": _iso(game_fetched),
            "changed_since_last_game": this.get("changed_since_last_game"),
            "prior_starts_in_store": this.get("prior_starts_in_store"),
            "prior_starts_with_team": this.get("prior_starts_with_team"),
        }
    else:
        missing.append({"item": f"{team}.qb", "kind": "absent",
                        "reason": f"the schedule lists no starting quarterback for {team} yet"})
    return out, missing


def _injuries(store, block: Mapping, game: Mapping, cutoff: datetime) -> tuple:
    """`(injuries section or None, missing)`. The data layer decides what the report held as of
    `cutoff`; this adds the fetch-time gate (module docstring, way 4)."""
    team = block.get("team")
    inj = block.get("injuries") or {}
    rows = store.injuries_by_game_team().get((game["game_id"], team), ())
    late = [r for r in rows if (_instant(r.get("fetched_utc")) or cutoff) > cutoff]
    if late:
        return None, [{"item": f"{team}.injuries", "kind": "absent",
                       "reason": f"{len(late)} injury report row(s) for {team} were first fetched after this "
                                 "packet was built, and the store keeps only the newest version of a row, so "
                                 "the report as it stood at that time cannot be rebuilt"}]
    if not inj.get("available"):
        return None, [{"item": f"{team}.injuries", "kind": "absent",
                       "reason": str(inj.get("reason") or "no injury report for this team")}]
    skill = [{"name": s.get("name"), "position": s.get("position"), "report_status": s.get("report_status"),
              "practice_status": s.get("practice_status"), "injury": s.get("injury")}
             for s in inj.get("skill_players_listed") or []]
    out = {"report_week": inj.get("report_week"), "players_listed": inj.get("players_listed"),
           "totals": inj.get("totals"), "by_position_group": inj.get("by_position_group"),
           "skill_players_listed": skill, "newest_report_utc": inj.get("newest_report_utc"),
           "assumption": inj.get("assumption")}
    return out, []


def _team_values(store, block: Mapping, side: str, game: Mapping, cutoff: datetime,
                 start: Optional[datetime], game_fetched: Optional[datetime]) -> tuple:
    """`(values, missing)` for one club."""
    team = block["team"]
    missing: list = []
    form = {name: _window(block["form"][name]) for name in FORM_WINDOWS}
    in_season = block["form"]["season_to_date"].get("games") or 0
    if in_season == 0:
        missing.append({"item": f"{team}.season", "kind": "absent",
                        "reason": f"{team} has no finished game this season in the store"})
    for name, floor in (("last_3", 3), ("last_5", 5)):
        n = block["form"][name].get("games") or 0
        if 0 < n < floor:
            missing.append({"item": f"{team}.form.{name}", "kind": "thin",
                            "reason": f"{team} has only {n} finished game(s) in the store, so the {name} window "
                                      f"holds fewer than its {floor}"})
    if 0 < in_season < 3:
        missing.append({"item": f"{team}.form.season_to_date", "kind": "thin",
                        "reason": f"{team} has played only {in_season} game(s) this season, so its season figures "
                                  "rest on a very small sample"})
    for gap in block["sample"].get("scheduled_games_without_a_finished_result_before_this_game") or []:
        missing.append({"item": f"{team}.form", "kind": "thin",
                        "reason": f"an earlier game of {team} ({gap}) has no finished result in the store, so "
                                  "form is as of its last finished game"})
    for m in block.get("missing") or []:
        figure = str(m.get("figure") or "")
        if figure.startswith(("form", "injuries", "qb.this_game", "coach")):
            continue                      # form is judged above; injuries and the QB below; coach is not used
        missing.append({"item": f"{team}.{figure}", "kind": "absent", "reason": str(m.get("reason"))})
    qb, qb_missing = _qb(block, game_fetched, cutoff, start)
    injuries, inj_missing = _injuries(store, block, game, cutoff)
    missing += qb_missing + inj_missing
    rest = block.get("rest") or {}
    travel = block.get("travel") or {}
    values = {
        "team": team,
        "name": block.get("name"),
        "side": side,
        "record": {"season": block["record"]["season"]},
        "streak": block["streak"],
        "form": form,
        "last_three": _last_games(block),
        "rest": {k: rest.get(k) for k in ("days_since_last_game", "short_week", "coming_off_bye",
                                          "season_opener", "week_gap")},
        "travel": {k: travel.get(k) for k in ("miles_from_home_base", "time_zones_crossed", "direction",
                                              "kickoff_home_base_clock")},
        "qb": qb,
    }
    if injuries is not None:
        values["injuries"] = injuries
    return values, missing


def _differentials(sheet: Mapping) -> tuple:
    out = {}
    units: dict = {}
    for name, d in sheet["differentials"].items():
        out[name] = {"home": d["home"], "away": d["away"], "diff": d["diff"], "thin_sample": d["thin_sample"]}
        units.setdefault(name.rsplit(".", 1)[-1], d["unit"])
    return out, units


def _head_to_head(h2h: Mapping) -> dict:
    last = h2h.get("last_meeting")
    return {
        "meetings": h2h.get("meetings"), "home_team_wins": h2h.get("home_team_wins"),
        "away_team_wins": h2h.get("away_team_wins"), "ties": h2h.get("ties"),
        "average_margin_for_home_team": h2h.get("average_margin_for_home_team"),
        "last_meeting": None if not last else {
            k: last.get(k) for k in ("kickoff_utc", "season", "week", "home_team", "away_team",
                                     "home_score", "away_score", "winner")},
        "window": f"meetings since {(h2h.get('store_window') or {}).get('seasons', [None])[0]} only",
    }


# ---------------------------------------------------------------------------
# the packet
# ---------------------------------------------------------------------------

HOW_TO_READ = (
    "In sections.matchup.values.differentials a difference is home minus away, so a positive one means the "
    "home team has the larger number. head_to_head is written from the home team's side.",
    "A form window says how many games it rests on (games). last_3 and last_5 are the team's most recent "
    "finished games; season_to_date is this season only. yards_per_play is net yards per play and "
    "turnover_margin is takeaways minus giveaways per game; each states the games it rests on.",
    "A spread selection carries its own signed number: \"KC -3.5\" lays 3.5 points and \"LAC +3.5\" gets 3.5. "
    "The two selections of the spread are the two sides of one number. fair_probability is the market's "
    "probability with the bookmaker's margin divided out, averaged over the books that quoted both sides.",
    "first_captured fields give where the market stood the first time it was captured, which is not "
    "necessarily the opening line.",
    "A qb listed_for_this_game with projected true is the schedule's projection at listed_as_of_utc, not a "
    "confirmed starter. The injury report is the weekly team report as stored.",
    "figure_units says what each form figure measures. sections.reference.values holds scoring facts, "
    "not statistics.",
)


def _limits(store_start: Optional[int]) -> list:
    since = f" (it begins with the {store_start} season)" if store_start else ""
    return [
        "Only the moneyline, the point spread and the game total are analyzed, each at its most-quoted "
        "number. Alternate numbers, team totals, half and quarter markets and player props are not.",
        "Every quote is the newest one captured before this packet was built, with its capture time, from "
        "the books named; nothing was captured after the packet was built or after the start.",
        "Form, rest, travel and head to head cover only the games in the data store" + since + ". A window "
        "holds fewer games than it names early in a season, and each figure states how many it rests on.",
        "Weather forecasts, depth charts, snap counts, play-by-play detail, officials, coaching and "
        "scheme changes and news after the weekly injury report are not in the data.",
        "The starting quarterback is the one the schedule lists, a projection until the game is played. The "
        "injury report is the weekly team report; a player's importance is not measured.",
        "A neutral-site game has a nominal home team; its differentials still read home minus away.",
    ]


def build_packet(store, game_id: str, *, built_at: str, multibook_rows: Sequence[Mapping] = (),
                 cfg: Optional[Mapping] = None) -> dict:
    """One game's frozen fact packet. Deterministic in the store's contents and its arguments: no
    clock, no network, no write.

    `store` is a `src.datasvc.nfl.store.NflStore`. `built_at` is the ISO UTC moment the packet is
    built (the caller's clock). `multibook_rows` are odds-feed rows, unfiltered: this function keeps
    this game's NFL rows and applies the no-future rule itself. Raises `NflPacketError` for a game
    that is not in the store, and `ValueError` for a `built_at` that is not a time.
    """
    from src.analyst import config as config_mod

    cfg = dict(cfg) if cfg is not None else config_mod.DEFAULTS
    try:
        cutoff = parse_instant(built_at)
    except ValueError as exc:
        raise ValueError(f"built_at must be an ISO UTC time, got {built_at!r}") from exc
    game = store.game_by_id().get(str(game_id))
    if game is None:
        raise NflPacketError(f"no game {game_id!r} in the store")
    away, home = game.get("away_team"), game.get("home_team")
    if not away or not home or away == home:
        raise NflPacketError(f"game {game_id!r} does not name two different clubs")

    kickoff = _instant(game.get("kickoff_utc"))
    rows = rows_for_game(multibook_rows, away, home, kickoff)
    commence = [m for m in (_instant(r.get("commence_time")) for r in rows) if m is not None]
    starts = ([kickoff] if kickoff else []) + commence
    start = min(starts) if starts else None
    missing: list = []
    if kickoff is None:
        missing.append({"item": "game.kickoff", "kind": "absent",
                        "reason": "the schedule has no kickoff time for this game"
                                  + ("; the odds feed's start is used" if start else
                                     ", so nothing can be shown to precede it and it cannot be published")})
    elif commence and max(abs(c - kickoff) for c in commence) > KICKOFF_DISAGREEMENT:
        missing.append({"item": "game.kickoff", "kind": "thin",
                        "reason": f"the schedule says {_iso(kickoff)} and the odds feed says "
                                  f"{_iso(min(commence))}; the earlier is used to cut quotes off"})

    as_of = min(cutoff, start) if start is not None else cutoff
    sheet = mu.matchup(store, str(game_id), as_of=iso_utc(as_of))
    schedule = sheet["schedule"]
    game_fetched = _instant(game.get("fetched_utc"))

    sides = {}
    for side in ("away", "home"):
        values, gaps = _team_values(store, sheet[side], side, game, cutoff, start, game_fetched)
        sides[side] = values
        missing += gaps
    diffs, units = _differentials(sheet)
    for name, d in diffs.items():
        if d["diff"] is not None and d["thin_sample"]:
            missing.append({"item": f"matchup.{name}", "kind": "thin",
                            "reason": "one or both teams' windows hold fewer games than they name"})

    roof = game.get("roof")
    venue = {"stadium": game.get("stadium"), "roof": roof, "surface": game.get("surface"),
             "neutral_site": bool(game.get("neutral_site"))}
    if roof is None:
        missing.append({"item": "venue.roof", "kind": "absent",
                        "reason": "the schedule file gives no roof type for this stadium"})
    if roof not in INDOOR_ROOFS:
        missing.append({"item": "weather", "kind": "absent",
                        "reason": "no weather forecast is stored for NFL stadiums, and this game is not "
                                  "known to be played indoors"})
    if game.get("venue_check") not in (None, "ok"):
        missing.append({"item": "venue", "kind": "thin",
                        "reason": f"the schedule's venue for this game is flagged {game.get('venue_check')!r}"})

    status = game.get("status")
    game_block = {
        "game_id": str(game_id),
        "date": game.get("gameday"),
        "season": game.get("season"),
        "week": game.get("week"),
        "game_type": game.get("game_type"),
        "away": away, "home": home,
        "away_name": feat.team_name(away), "home_name": feat.team_name(home),
        "kickoff_utc": _iso(kickoff) if kickoff else (_iso(start) if start else None),
        "state": _STATE.get(status, status),
        "stadium": game.get("stadium"),
        "neutral_site": bool(game.get("neutral_site")),
    }

    # --- the markets -----------------------------------------------------------
    markets: dict = {}
    for built in (_moneyline(rows, away, home, cutoff, start),
                  _spread(rows, away, home, cutoff, start),
                  _total(rows, away, home, cutoff, start)):
        if built:
            markets[built["slot_id"]] = built
    stale_minutes = float(cfg.get("stale_quote_minutes", 180))
    labels = {"moneyline": "moneyline", "spread": "point spread", "total": "game total"}
    for slot_id in SLOT_ORDER:
        market = markets.get(slot_id)
        if market is None:
            missing.append({"item": slot_id, "kind": "absent",
                            "reason": f"no {labels[slot_id]} prices were captured before this analysis was built"})
            continue
        age = (cutoff - base._parse_utc(market["as_of"])).total_seconds() / 60.0
        if age > stale_minutes:
            missing.append({"item": slot_id, "kind": "stale",
                            "reason": f"the newest {labels[slot_id]} quote is {int(age)} minutes old"})
    missing.append({"item": "props", "kind": "absent",
                    "reason": "no NFL player-prop prices are captured, so no prop is analyzed"})
    markets = {k: markets[k] for k in SLOT_ORDER if k in markets}

    # --- the sections ----------------------------------------------------------
    as_of_text = _iso(as_of)
    sections = {
        "schedule": {"as_of": _iso(cutoff), "as_of_basis": SCHEDULE_BASIS, "values": {
            "season": schedule.get("season"), "week": schedule.get("week"),
            "game_type": schedule.get("game_type"), "gameday": schedule.get("gameday"),
            "weekday": schedule.get("weekday"), "kickoff_et": schedule.get("kickoff_et"),
            "time_window": schedule.get("time_window"), "primetime": schedule.get("primetime"),
            "divisional": schedule.get("divisional"), "neutral_site": schedule.get("neutral_site"),
            "venue": venue}},
        "away": {"as_of": as_of_text, "as_of_basis": TEAM_BASIS, "values": sides["away"]},
        "home": {"as_of": as_of_text, "as_of_basis": TEAM_BASIS, "values": sides["home"]},
        "matchup": {"as_of": as_of_text, "as_of_basis": MATCHUP_BASIS, "values": {
            "differentials": diffs, "head_to_head": _head_to_head(sheet["head_to_head"])}},
        "reference": {"as_of": None, "as_of_basis": REFERENCE_NOTE, "values": {
            "scoring": dict(SCORING), "key_numbers": list(KEY_NUMBERS)}},
    }
    sections = _scrub(sections)

    missing = sorted({(m["item"], m["kind"], m["reason"]): m for m in missing}.values(),
                     key=lambda m: (m["item"], m["kind"], m["reason"]))
    seasons = store.seasons()
    return {
        "packet_version": PACKET_VERSION,
        "built_at": _iso(cutoff),
        "game": game_block,
        "figure_units": dict(sorted(units.items())),
        "sections": sections,
        "markets": markets,
        "slots": [{"slot_id": sid, "market": m["market"], "label": m["label"],
                   "selections": [o["selection"] for o in m["options"]]}
                  for sid, m in markets.items()],
        "missing": missing,
        "limits": _limits(seasons[0] if seasons else None),
        "how_to_read": list(HOW_TO_READ),
    }


# ---------------------------------------------------------------------------
# lookups the critic, the grader and the ledger share (the MLB packet's own)
# ---------------------------------------------------------------------------

resolve_path = base.resolve_path
packet_hash = base.packet_hash
slot = base.slot
option = base.option
has_quote = base.has_quote
