"""Per-game dossier: everything known about one matchup, assembled once.

WHY THIS EXISTS SEPARATELY FROM THE DETECTORS
---------------------------------------------
Detectors ask narrow questions. Nearly all of them need the same expensive
inputs -- the starters' point-in-time records, tonight's lineup, the bullpen's
recent workload, the park, the weather, the prices. Letting each detector fetch
its own would mean twenty detectors making the same twenty calls, and would make
it impossible to state one information-time for the game as a whole.

So the dossier is built once per game, and detectors read from it. That also
enforces the point-in-time contract in a single place: everything in a dossier is
gathered as of `information_time`, and a detector physically cannot see past it
because it has no access to anything else.

EVERY FIELD IS OPTIONAL AND ABSENCE IS VISIBLE
----------------------------------------------
A missing lineup, an unannounced starter, no price on the board -- all normal,
all common, and none of them a reason to fail. Each section records whether it
was populated and why not, so the dashboard can show a gap as a gap rather than
rendering an empty box that looks like a zero.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.core import odds as odds_math
from src.data import parks
from src.pipeline import features as team_features
from src.pipeline import pitchers as pitcher_features


class Dossier:
    """One game, everything known about it, as of one instant."""

    def __init__(self, game, information_time=None):
        self.game = dict(game)
        self.information_time = information_time or datetime.now(timezone.utc)
        self.sections = {}
        self.gaps = {}

    # -- assembly ---------------------------------------------------------

    def add(self, name, data) -> None:
        self.sections[name] = data

    def miss(self, name, reason) -> None:
        """Record a section that could not be filled, and why.

        Named rather than skipped. A section that silently never appears is
        indistinguishable from one that was never attempted, and that ambiguity
        is how a broken data source survives for a month unnoticed.
        """
        self.gaps[name] = reason

    def get(self, name, default=None):
        return self.sections.get(name, default)

    @property
    def teams(self):
        return self.game.get("away_team"), self.game.get("home_team")

    def to_dict(self) -> dict:
        return {
            "game": self.game,
            "information_time": self.information_time.isoformat(),
            "sections": self.sections,
            "gaps": self.gaps,
        }


def build(game, store, pitcher_logs=None, prices=None, weather=None,
          lineups=None, bullpen=None, splits=None, matchups=None,
          travel=None, arsenals=None, news=None, matchup_depth=None,
          price_improvement=None, price_board=None, roster_events=None,
          information_time=None) -> Dossier:
    """Assemble one dossier from whatever sources are available."""
    dossier = Dossier(game, information_time=information_time)
    date = game.get("date")
    away, home = game.get("away_team"), game.get("home_team")

    # Team form, point-in-time and season-scoped by the same accessor the model
    # uses -- nothing here reaches across the off-season or into the future.
    if store:
        dossier.add("teams", team_features.matchup_features(store, away, home, date))
    else:
        dossier.miss("teams", "no historical results store")

    if pitcher_logs:
        dossier.add("starters", pitcher_features.matchup_pitcher_features(
            pitcher_logs, game.get("away_probable_id"),
            game.get("home_probable_id"), date))
    else:
        dossier.miss("starters", "no pitcher logs; run the pitcher log build")

    try:
        dossier.add("park", dict(parks.get_park(home), team=home))
    except parks.ParkError as exc:
        dossier.miss("park", str(exc))

    if weather:
        dossier.add("weather", weather)
    else:
        dossier.miss("weather", "weather not fetched for this slate")

    # What changed recently, as opposed to every other section, which describes
    # a steady state. A quiet stretch is a real answer and carries its own
    # sentence rather than rendering as missing data.
    # The best number on the board versus the de-vigged consensus. The
    # section carries its own label -- line-shopping value, never expected
    # value -- and a thin board carries its reason instead of a table.
    if price_improvement is not None:
        if price_improvement.get("skipped"):
            dossier.miss("price_improvement", price_improvement["skipped"])
        else:
            dossier.add("price_improvement", price_improvement)
    else:
        dossier.miss("price_improvement",
                     "no multi-book observations for this game yet")

    # The board itself -- one capture instant from the multi-book store, one
    # row per book -- as opposed to `price_improvement`, which is that board
    # summarised. Detectors that want to talk about the board read this, so
    # every count and every timestamp on the card traces to one selection
    # (src/analysis/prices.boards_by_matchup). Absent is recorded as a gap
    # rather than quietly substituting the per-game snapshot's book list: two
    # stores captured at two moments cannot describe one board.
    if price_board and price_board.get("quotes"):
        dossier.add("multibook_board", price_board)
    else:
        dossier.miss("multibook_board",
                     "no multi-book board captured for this game")

    # What changed since our own last look at the world: roster-watch events
    # for these two clubs on this date, each with its pre-event relevance.
    # The ONE section that is silent rather than named when it has nothing:
    # a gap here would print "no roster event fired between two polls" on
    # every card of every quiet slate, which is most cards on most days, and
    # a reader who is told nothing happened fifteen times stops reading the
    # time it did. The events themselves are already an exception report.
    if roster_events and roster_events.get("events"):
        dossier.add("what_changed", roster_events)

    if news is not None:
        if news.get("reason"):
            dossier.miss("news", news["reason"])
        else:
            dossier.add("news", news["teams"])
    else:
        dossier.miss("news", "roster news not fetched for this slate")

    if lineups:
        dossier.add("lineups", lineups)
    else:
        dossier.miss("lineups", "lineup not posted yet, or not fetched")

    # The unit-vs-specific-weakness decomposition, from the rebuilt pitch
    # store (src/analysis/matchup.py). An entry can carry its own reason for
    # not existing -- no posted lineup, no pitch store -- and that reason is
    # recorded as the gap, mirroring how news handles a quiet feed.
    if matchup_depth is not None:
        if matchup_depth.get("reason"):
            dossier.miss("matchup_depth", matchup_depth["reason"])
        else:
            dossier.add("matchup_depth", matchup_depth)
    else:
        dossier.miss("matchup_depth", "matchup depth not built for this slate")

    if bullpen:
        dossier.add("bullpen", bullpen)
    else:
        dossier.miss("bullpen", "bullpen workload not built")

    if arsenals:
        dossier.add("arsenals", arsenals)
    else:
        dossier.miss("arsenals", "pitch arsenals not built for this season")

    if travel:
        dossier.add("travel", travel)
    else:
        dossier.miss("travel", "travel load not computed")

    if splits:
        dossier.add("splits", splits)
    else:
        dossier.miss("splits", "pitcher platoon splits not fetched")

    if matchups:
        dossier.add("matchup_history", matchups)
    else:
        dossier.miss("matchup_history", "batter-vs-pitcher history not fetched")

    if prices:
        dossier.add("market", _market_section(prices))
    else:
        dossier.miss("market", "no prices on the board for this game")

    return dossier


def _market_section(prices) -> dict:
    """Prices with fair probabilities attached, per market.

    De-vigging happens here rather than in each detector, so no detector can
    accidentally compare a model number against a raw implied probability -- the
    error that systematically overstates every edge in the building.
    """
    section = {"markets": {}, "all_books": prices.get("all_books") or {}}
    for market, quote in (prices or {}).items():
        if market == "all_books":
            continue
        entry = dict(quote)
        away_price, home_price = quote.get("away_price"), quote.get("home_price")
        if away_price is not None and home_price is not None:
            try:
                fair_away, fair_home = odds_math.devig_two_way(away_price, home_price)
                entry["away_fair"] = round(fair_away, 4)
                entry["home_fair"] = round(fair_home, 4)
                entry["hold_pct"] = round(
                    odds_math.hold_percentage([away_price, home_price]), 3)
            except odds_math.OddsError as exc:
                entry["devig_error"] = str(exc)
        entry.setdefault("total", quote.get("total"))
        over, under = quote.get("over_price"), quote.get("under_price")
        if over is not None and under is not None:
            try:
                fair_over, fair_under = odds_math.devig_two_way(over, under)
                entry["over_fair"] = round(fair_over, 4)
                entry["under_fair"] = round(fair_under, 4)
            except odds_math.OddsError as exc:
                entry["devig_error"] = str(exc)
        section["markets"][market] = entry

    # The market's own opinion of the bullpens, which nobody computes. The
    # full-game price minus the first-five price is precisely the value the
    # market assigns to innings six through nine -- see detectors.
    full = section["markets"].get("h2h") or {}
    five = section["markets"].get("h2h_1st_5_innings") or {}
    if full.get("home_fair") is not None and five.get("home_fair") is not None:
        section["implied_bullpen_shift"] = round(
            full["home_fair"] - five["home_fair"], 4)
    return section
