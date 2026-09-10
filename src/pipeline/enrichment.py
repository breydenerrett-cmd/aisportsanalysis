"""Every store-backed input `briefing.build_slate` takes, loaded from disk.

WHY IT LIVES HERE AND NOT IN api/
----------------------------------
It lived in `api/games.py` as `_enrichment_inputs`, which was fine while the
web request path was the only caller. It stopped being fine on 2026-09-10,
when `src/cli.py`'s `card publish` needed the SAME inputs -- and could not
import them, because `src/` may never import from `api/`
(tests/test_api_boundary.py).

That is not a style problem. The card the CLI freezes into the public ledger
has to be the card the customer saw on the page. When the CLI built its
slate without these inputs it produced a DIFFERENT card for the same date --
measured: four picks against the API's three, because a missing arsenal
changed one game's starter features and flipped the model's agreement. A
receipts ledger that disagrees with the page it is receipts for is worse
than no ledger.

So there is one loader, here, and both callers use it.

TWO RULES, BOTH DELIBERATE
--------------------------
- NOTHING HERE TOUCHES THE NETWORK. The CLI briefing also fetches
  lineup-vs-pitcher history (one MLB call per hitter, ~200 per slate) and
  pitcher splits live; those are left out. A page render, and a card
  publish, read what the daily loop already wrote, or show the gap.
- EVERY INPUT IS ABSENT-SAFE. A missing or unreadable store yields None for
  that input, and `dossier.build` records the miss with a reason. A
  container built without data/historical/ behaves exactly as it did before
  this function existed.

Lineups are the one join with a type trap: `lineup_store.read()` keys by str
(it round-trips through JSON) and the schedule carries int game_pk, and
build_slate looks up by the schedule's value. The store's own docstring
records that this exact mismatch once silently matched nothing for weeks.
Re-keyed here on the schedule's value.
"""

from __future__ import annotations

from src.pipeline import (bullpen, lineup_store, lineups, matchup_history,
                          news, pitchers, standings, travel,
                          weather_capture)
from src.providers import statcast


def latest_weather_by_pk(rows, games) -> dict:
    """The newest captured forecast per game, reshaped to the reading
    `weather.extract_hour` returns -- which is the shape dossier.build and
    the weather detectors were written against.

    The capture store row is a superset of that reading (it adds park, roof,
    hours-to-first-pitch and the capture instant). Only the reading's own
    eight keys are handed on; `forecast_hour_utc` is the reading's
    `observed_utc`, and the row's `observed_utc` (when it was captured) is
    used only to pick the newest row. game_pk is compared as str on both
    sides: the schedule carries an int and the store round-trips through
    JSON, and a silent int/str mismatch here would just mean "no weather"
    with no error anywhere.
    """
    wanted = {str(g.get("game_pk")): g.get("game_pk")
              for g in games if g.get("game_pk") is not None}
    newest = {}
    for row in rows or ():
        key = str(row.get("game_pk"))
        if key not in wanted:
            continue
        stamp = row.get("observed_utc") or ""
        if key not in newest or stamp > (newest[key].get("observed_utc") or ""):
            newest[key] = row
    out = {}
    for key, row in newest.items():
        out[wanted[key]] = {
            "observed_utc": row.get("forecast_hour_utc"),
            "hours_from_first_pitch": row.get("forecast_hour_offset_hours"),
            "temp_f": row.get("temp_f"),
            "humidity_pct": row.get("humidity_pct"),
            "wind_mph": row.get("wind_mph"),
            "wind_from_deg": row.get("wind_from_deg"),
            "precip_probability_pct": row.get("precip_probability_pct"),
            "pressure_hpa": row.get("pressure_hpa"),
        }
    return out


def enrichment_inputs(games, date, store) -> dict:
    """Every store-backed `build_slate` input for one date's `games`."""
    inputs = {}

    logs = pitchers.read_logs()
    inputs["pitcher_logs"] = logs or None

    pens = {}
    try:
        pen_log = bullpen.read_log()
    except Exception:  # noqa: BLE001 -- a corrupt log is a gap, not a 500
        pen_log = []
    if pen_log:
        wanted = {t for g in games for t in (g.get("away_team"), g.get("home_team")) if t}
        for team in wanted:
            try:
                pens[team] = bullpen.team_workload(pen_log, team, date)
            except Exception:  # noqa: BLE001
                continue
    inputs["bullpen_by_team"] = pens or None

    stored = lineup_store.read()
    lineups_by_pk = {}
    for g in games:
        pk = g.get("game_pk")
        row = stored.get(str(pk)) if pk is not None else None
        if row:
            lineups_by_pk[pk] = row
    inputs["lineups_by_pk"] = lineups_by_pk or None
    inputs["handedness"] = lineups.read_handedness() or None

    trips = {}
    if store:
        for g in games:
            pk, home = g.get("game_pk"), g.get("home_team")
            if pk is None or not home:
                continue
            legs = {}
            for team in (g.get("away_team"), home):
                if not team:
                    continue
                try:
                    legs[team] = travel.travel_load(store, team, date, home)
                except Exception:  # noqa: BLE001
                    continue
            if legs:
                trips[pk] = legs
    inputs["travel_by_pk"] = trips or None

    inputs["weather_by_pk"] = latest_weather_by_pk(
        weather_capture.read(), games) or None

    # League position on THIS date, per club. The index is read once and
    # reused across the slate rather than re-read per game, and
    # `team_standing` never substitutes a different date for the one asked
    # for -- so a past game shows the table as it stood then. A club with no
    # snapshot comes back `found: False` with its own reason, which
    # dossier.build renders as a stated gap rather than a rank of zero.
    try:
        index = standings.read()
    except Exception:  # noqa: BLE001 -- an unreadable store is a gap, not a 500
        index = {}
    standings_by_pk = {}
    if index:
        for g in games:
            pk = g.get("game_pk")
            if pk is None:
                continue
            rows = {}
            for side in ("away", "home"):
                team = g.get(f"{side}_team")
                if not team:
                    continue
                try:
                    rows[side] = standings.team_standing(date, team, index=index)
                except Exception:  # noqa: BLE001
                    continue
            if rows:
                standings_by_pk[pk] = rows
    inputs["standings_by_pk"] = standings_by_pk or None

    # Batter-vs-pitcher history. The store is already keyed by game_pk in
    # exactly the shape build_slate wants, so this is a re-key onto the
    # schedule's own value and nothing more. Forward-only by design: the
    # vsPlayer endpoint returns CAREER totals with no as-of parameter (marked
    # LEAKY in src/model/pointintime.py), so a past date is never built after
    # the fact -- doing so would fold that day's own plate appearances into
    # its "history", which is the classic backtest that looks brilliant and
    # loses money.
    try:
        history_by_pk = matchup_history.read()
    except Exception:  # noqa: BLE001 -- an unreadable store is a gap, not a 500
        history_by_pk = {}
    matchups_by_pk = {}
    for g in games:
        pk = g.get("game_pk")
        row = history_by_pk.get(str(pk)) if pk is not None else None
        if row:
            matchups_by_pk[pk] = row
    inputs["matchups_by_pk"] = matchups_by_pk or None

    # Pitcher platoon splits, cached by "{person_id}:{season}". Reshaped here
    # into the per-game/per-side form build_slate takes, the same shape the
    # CLI briefing builds live -- `platoon_split` is pure, so deriving it on
    # read costs nothing and keeps one definition of the split.
    try:
        split_cache = lineups.read_splits()
    except Exception:  # noqa: BLE001
        split_cache = {}
    splits_by_pk = {}
    if split_cache:
        season = str(date)[:4]
        for g in games:
            pk = g.get("game_pk")
            if pk is None:
                continue
            per_side = {}
            for side, pid_key in (("away", "away_probable_id"),
                                  ("home", "home_probable_id")):
                pid = g.get(pid_key)
                record = split_cache.get(f"{pid}:{season}") if pid else None
                if not record:
                    continue
                try:
                    per_side[side] = {"record": record,
                                      "platoon": lineups.platoon_split(record)}
                except Exception:  # noqa: BLE001
                    continue
            if per_side:
                splits_by_pk[pk] = per_side
    inputs["splits_by_pk"] = splits_by_pk or None

    # Roster moves and injuries. The module was complete and the CLI has
    # ingested it every briefing run all along; the API simply never read
    # it, so every game reported "roster news not fetched" while the data
    # was a free endpoint away. READ ONLY here -- `news.ingest` is the daily
    # loop's job, and a page render must not fetch.
    try:
        news_rows = news.read()
    except Exception:  # noqa: BLE001 -- an unreadable store is a gap, not a 500
        news_rows = []
    news_by_pk = {}
    if news_rows:
        for g in games:
            pk = g.get("game_pk")
            if pk is None:
                continue
            try:
                news_by_pk[pk] = news.attach(g, news_rows, date)
            except Exception:  # noqa: BLE001
                continue
    inputs["news_by_pk"] = news_by_pk or None

    # Pitch arsenals, season-scoped, keyed by player. Same accessor the CLI
    # uses; a season with no store yields {} and the page states the gap.
    try:
        season_int = int(str(date)[:4])
        inputs["arsenals"] = statcast.by_player(
            statcast.read(season_int, statcast.PITCHER)) or None
        inputs["batter_arsenals"] = statcast.by_player(
            statcast.read(season_int, statcast.BATTER)) or None
    except Exception:  # noqa: BLE001 -- arsenals are enrichment, never a blocker
        inputs["arsenals"] = inputs["batter_arsenals"] = None

    return inputs
