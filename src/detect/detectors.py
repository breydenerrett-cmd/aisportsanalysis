"""The pre-registered detector family.

Each detector here is one hypothesis. The registry IS the hypothesis count for
multiple-comparison correction, so adding one to this file is a research decision
and not a refactor -- searching for angles per game is forbidden precisely
because it makes the count unknowable.
"""

from __future__ import annotations

from src.core import odds as odds_math
from src.detect.base import (AWAY, BLOCKED, CONTEXT, DEBUNK, Detector, Finding,
                             HOME, HISTORICAL_CANDIDATE, NEITHER, SIGNAL,
                             TESTED_NULL, UNPROVEN, register, surprise_score)
from src.pipeline import bullpen as bullpen_mod

# Baselines. Each is a measured or stated league norm, not a fitted parameter.
# A detector needs one to say anything at all, so they live at module level where
# they are visible rather than buried in a method.
LEAGUE_FIP = 4.20
FIP_SPREAD = 0.75            # roughly one standard deviation across starters
LEAGUE_K_BB = 0.135
K_BB_SPREAD = 0.055
LEAGUE_RUN_DIFF_SPREAD = 0.85
# Measured 2026: the market's full-game minus first-five fair-probability gap.
# Until the backfill lands this is a placeholder spread and the detector says so.
BULLPEN_SHIFT_SPREAD = 0.020
# A book this far off the consensus fair probability is quotable value that
# requires no prediction at all.
BOOK_EDGE_THRESHOLD = 0.010
# A typical night leaves about one reliever down. Anything at or below that is
# context; a signal has to beat the ordinary state of a bullpen in August.
TYPICAL_UNAVAILABLE = 1
# A platoon gap this large is a real, visible weakness rather than sampling.
PLATOON_GAP_SPREAD = 0.090
# Minimum platoon gap worth a sentence, per metric. The OPS floor is the
# original; the wOBA floor was PRE-REGISTERED before any historical evaluation
# ran, by scaling rather than fitting: wOBA moves at roughly 0.42x OPS, and
# 0.080 * 0.42 ~= 0.034, rounded to 0.035. Fitting it to results would turn a
# threshold into a tuned parameter.
PLATOON_OPS_GAP = 0.080
PLATOON_WOBA_GAP = 0.035
# Under this many career at-bats, a batter-vs-pitcher line is noise.
THIN_AT_BATS = 20
LEAGUE_BATTING_AVG = 0.248
BATTING_AVG_SPREAD = 0.050
# MEASURED, not guessed: 1,552 team-games across 60 days of 2025. Three quarters
# involve no travel at all (a club mid-series does not move), and nonzero trips
# average 905 miles. Mean 215, standard deviation 496 across all team-games.
TRAVEL_SPREAD = 496.0
TRAVEL_BASELINE = 215.0
LONG_TRIP_MILES = 1200
# A club plays about six games a week, so six is normal rather than notable.
DENSE_BASELINE_GAMES = 6
HIGH_ALTITUDE_M = 900
LEAGUE_ALTITUDE_M = 150
LEAGUE_TEMP_F = 74.0
TEMP_NOTABLE_F = 14.0
STRONG_WIND_MPH = 15.0
LEAGUE_IP_PER_START = 5.30
IP_PER_START_SPREAD = 0.65

# Starts required before an innings-per-start average describes a pitcher.
#
# Without this, an opener with one start of one inning reads as 1.00 innings a
# start against a league 5.30 -- a surprise score of 6.6, the most extreme
# number on the slate, and completely meaningless. Five starts is the same
# principle already applied to platoon splits and batter-vs-pitcher history:
# below the floor the number is not a weaker signal, it is a different thing.
MIN_STARTS_FOR_EXPOSURE = 5
# A pitch thrown less than a third of the time is not what the lineup is
# preparing for, and reading a matchup off it overstates its role.
PRIMARY_PITCH_USAGE = 30.0
MIN_HITTERS_FOR_PITCH_READ = 5
LEAGUE_WOBA = 0.318
WOBA_SPREAD = 0.045


class ImpliedBullpenDisagreement(Detector):
    """The market's own bullpen opinion, against ours.

    THE IDEA
    --------
    A full-game price and a first-five price on the same team differ by exactly
    one thing: innings six through nine. So `full_game_fair - first_five_fair` is
    not a proxy for the market's bullpen view -- it IS that view, in probability
    units, published nightly and read by nobody.

    That makes it directly comparable to a bullpen read we can compute ourselves
    from who is actually available tonight. When the market says a club gains two
    points from its pen and its two highest-leverage arms both threw 30 pitches
    yesterday, those two statements are in tension, and the tension is the bet.

    WHY IT IS UNPROVEN AND LABELLED SO
    ----------------------------------
    The comparison is sound; the threshold is a guess. Whether a disagreement of
    this size predicts anything cannot be known until the historical first-five
    backfill lands, and the detector says that on every finding it emits.
    """

    name = "implied_bullpen_disagreement"
    markets = ("h2h", "h2h_1st_5_innings")
    status = UNPROVEN

    def run(self, game):
        market = game.get("market") or {}
        shift = market.get("implied_bullpen_shift")
        if shift is None:
            return []

        away, home = game.teams
        favoured = home if shift > 0 else away
        findings = [Finding(
            self.name, CONTEXT,
            f"The market gives {favoured} {abs(shift) * 100:.1f} points of win "
            f"probability from innings 6-9 — that gap between the full-game and "
            f"first-five prices is its bullpen opinion, stated in probability.",
            value=round(abs(shift), 4), baseline=0.0,
            surprise=surprise_score(abs(shift), 0.0, BULLPEN_SHIFT_SPREAD),
            side=HOME if shift > 0 else AWAY, evidence=UNPROVEN,
            detail={"implied_shift": shift})]

        pens = game.get("bullpen") or {}
        if not pens:
            return findings

        # Our own read: how much of each pen is likely unavailable tonight.
        strain = {}
        for team, workload in pens.items():
            if not workload:
                continue
            relievers = workload.get("relievers") or []
            if not relievers:
                continue
            out = [r for r in relievers
                   if r.get("availability") == bullpen_mod.LIKELY_UNAVAILABLE]
            strain[team] = {
                "unavailable": len(out),
                "arms": len(relievers),
                "innings": workload.get("total_innings"),
                "names": [r.get("name") for r in out],
            }

        if len(strain) != 2:
            return findings

        # The disagreement: the market favours a pen whose arms are gassed.
        favoured_strain = strain.get(favoured)
        other = home if favoured == away else away
        other_strain = strain.get(other)
        if not favoured_strain or not other_strain:
            return findings

        gap = favoured_strain["unavailable"] - other_strain["unavailable"]
        if gap > 0:
            names = ", ".join(n for n in favoured_strain["names"] if n)
            findings.append(Finding(
                self.name, SIGNAL,
                f"The market prices {favoured}'s bullpen as the better one "
                f"tonight, but {favoured_strain['unavailable']} of its arms are "
                f"likely unavailable against {other_strain['unavailable']} for "
                f"{other}"
                + (f" ({names})" if names else "") + ".",
                value=favoured_strain["unavailable"],
                baseline=other_strain["unavailable"],
                sample=f"{favoured_strain['arms']} relievers, 7-day window",
                surprise=float(gap),
                side=AWAY if favoured == home else HOME,
                market_relevance=(
                    "The full-game side is the one this argues against; the "
                    "first-five price is unaffected by it."),
                evidence=UNPROVEN,
                detail=strain))
        return findings


class BullpenWorkload(Detector):
    """Who is gassed, stated as usage rather than as a verdict."""

    name = "bullpen_workload"
    markets = ("h2h",)
    status = UNPROVEN

    def run(self, game):
        pens = game.get("bullpen") or {}
        findings = []
        for team, workload in pens.items():
            if not workload:
                continue
            relievers = workload.get("relievers") or []
            out = [r for r in relievers
                   if r.get("availability") == bullpen_mod.LIKELY_UNAVAILABLE]
            if not out:
                continue
            worst = max(out, key=lambda r: r.get("innings") or 0)
            # One arm down is a normal Tuesday. Emitting it as a signal with a
            # surprise of zero puts noise at the top of a ranked list and teaches
            # the reader to ignore the ranking, so it is demoted to context.
            unusual = len(out) > TYPICAL_UNAVAILABLE
            findings.append(Finding(
                self.name, SIGNAL if unusual else CONTEXT,
                f"{team} is down {len(out)} of {len(relievers)} relievers "
                f"tonight — {worst.get('name')} {worst.get('availability_reason')}.",
                value=len(out), baseline=float(TYPICAL_UNAVAILABLE),
                sample=f"{workload.get('window_days')}-day window",
                surprise=surprise_score(len(out), TYPICAL_UNAVAILABLE, 1.0),
                side=AWAY if team == game.teams[0] else HOME,
                market_relevance=(
                    "Affects the full game far more than the first five."),
                evidence=TESTED_NULL,
                detail={"unavailable": [r.get("name") for r in out],
                        "total_innings": workload.get("total_innings")}))
        return findings


class StaleBook(Detector):
    """A book off the consensus. Arithmetic, not prediction.

    This is the one finding on the page that requires no model and no hypothesis:
    if eleven books agree and one does not, the outlier is a better price, and
    that is true whether or not anything else here works.
    """

    name = "stale_book"
    markets = ("h2h",)
    status = HISTORICAL_CANDIDATE

    def run(self, game):
        market = game.get("market") or {}
        quotes = (market.get("all_books") or {}).get("h2h") or []
        if len(quotes) < 3:
            return []

        fairs = []
        for quote in quotes:
            try:
                away_fair, home_fair = odds_math.devig_two_way(
                    quote["away_price"], quote["home_price"])
            except (odds_math.OddsError, KeyError, TypeError):
                continue
            fairs.append((quote["book"], away_fair, home_fair, quote))
        if len(fairs) < 3:
            return []

        consensus_home = sum(f[2] for f in fairs) / len(fairs)
        findings = []
        for side, index, label in ((HOME, 2, game.teams[1]),
                                   (AWAY, 1, game.teams[0])):
            target = consensus_home if side is HOME else 1 - consensus_home
            best = min(fairs, key=lambda f: f[index])
            edge = target - best[index]
            if edge < BOOK_EDGE_THRESHOLD:
                continue
            price = best[3]["home_price" if side is HOME else "away_price"]
            findings.append(Finding(
                self.name, SIGNAL,
                f"{best[0]} has {label} at {price:+d}, which is {edge * 100:.1f} "
                f"points cheaper than the {len(fairs)}-book consensus. No "
                f"prediction required — it is the same bet at a better price.",
                value=round(best[index], 4), baseline=round(target, 4),
                sample=f"{len(fairs)} books",
                surprise=surprise_score(best[index], target, 0.010),
                side=side,
                market_relevance="Price execution, independent of any read on the game.",
                evidence=TESTED_NULL,
                detail={"book": best[0], "price": price,
                        "consensus": round(target, 4)}))
        return findings


class StarterMismatch(Detector):
    """The scanner's starter signal, expressed as a finding with its baseline."""

    name = "starter_mismatch"
    markets = ("h2h", "h2h_1st_5_innings")
    status = UNPROVEN

    def run(self, game):
        starters = game.get("starters") or {}
        away, home = game.teams
        if not starters.get("both_sp_known"):
            return []
        if starters.get("either_sp_thin"):
            return [Finding(
                self.name, DEBUNK,
                "One starter is under 20 innings this season. Any rate you see "
                "quoted for him tonight is small-sample noise, not a read.",
                sample="<20 IP", evidence=TESTED_NULL)]

        away_fip, home_fip = starters.get("away_sp_fip"), starters.get("home_sp_fip")
        if away_fip is None or home_fip is None:
            return []

        findings = []
        for team, fip, side in ((away, away_fip, AWAY), (home, home_fip, HOME)):
            score = surprise_score(fip, LEAGUE_FIP, FIP_SPREAD)
            if score is None or score < 1.0:
                continue
            better = fip < LEAGUE_FIP
            findings.append(Finding(
                self.name, SIGNAL,
                f"{team}'s starter is at {fip:.2f} FIP against a league average "
                f"of {LEAGUE_FIP:.2f} — {'well above' if better else 'well below'} "
                "an average major-league start.",
                value=fip, baseline=LEAGUE_FIP,
                sample=f"{starters.get(('away' if side is AWAY else 'home') + '_sp_innings')} IP",
                surprise=score, side=side if better else (HOME if side is AWAY else AWAY),
                market_relevance=(
                    "Concentrated in the first five; diluted over nine by the pen."),
                evidence=TESTED_NULL))
        return findings


class PlatoonMismatch(Detector):
    """A starter's platoon weakness against the lineup actually posted tonight.

    THIS IS THE MATCHUP DECOMPOSITION, MADE COMPUTABLE
    --------------------------------------------------
    The framing the project is built for is: decompose both sides into units and
    roles, then find where one side's strength meets the other's specific hole.
    Team-level data cannot express that. Two facts can:

      - this starter allows materially more to one handedness than the other
      - tonight's lineup is stacked with exactly that handedness

    Neither is remarkable alone. Together they are the sentence a knowledgeable
    bettor did not have.

    BOTH HALVES ARE SAMPLE-GATED
    ----------------------------
    A "platoon split" over 30 batters faced is a fortnight, not a tendency, and a
    lineup with three unknown hitters cannot be characterised. Either failure
    produces silence with a reason, never a number.
    """

    name = "platoon_mismatch"
    markets = ("h2h", "h2h_1st_5_innings", "totals_1st_5_innings")
    status = UNPROVEN

    def run(self, game):
        lineups = game.get("lineups") or {}
        splits = game.get("splits") or {}
        if not lineups or not splits:
            return []

        away, home = game.teams
        findings = []
        # A starter faces the OPPOSING lineup, so the pairings cross over.
        for pitcher_side, lineup_key, pitcher_team, batting_team, side in (
                ("away", "home", away, home, HOME),
                ("home", "away", home, away, AWAY)):
            split = (splits.get(pitcher_side) or {}).get("platoon")
            composition = (lineups.get(lineup_key) or {}).get("platoon_advantage")
            if not split or not split.get("usable") or not composition:
                continue
            share = composition.get("share")
            if share is None:
                continue

            weak_side = split["weaker_against"]
            # The lineup only exploits the weakness if it is stacked with the
            # handedness the pitcher struggles against.
            counts = composition.get("counts") or {}
            exploiting = counts.get(weak_side, 0) + counts.get("S", 0)
            known = composition.get("known") or 0
            if not known:
                continue
            exploit_share = exploiting / known
            # The same split can arrive on two scales: OPS from the live
            # statSplits fetch, wOBA from the rebuilt pitch-level store. The
            # gap floor and the quoted fields must follow the metric, or a
            # wOBA-scale gap would be judged against an OPS-scale bar and the
            # detector would fall silent on every historical game.
            metric = split.get("metric") or "ops"
            gap_floor = PLATOON_WOBA_GAP if metric == "woba" else PLATOON_OPS_GAP
            if exploit_share < 0.55 or split["gap"] < gap_floor:
                continue

            hand = "left-handed" if weak_side == "L" else "right-handed"
            if metric == "woba":
                allows = (f"allows a {split['vs_left_woba']:.3f} wOBA to "
                          f"lefties against {split['vs_right_woba']:.3f} to "
                          f"righties")
            else:
                allows = (f"allows {split['vs_left_ops']:.3f} OPS to lefties "
                          f"against {split['vs_right_ops']:.3f} to righties")
            findings.append(Finding(
                self.name, SIGNAL,
                f"{pitcher_team}'s starter {allows}, and "
                f"{batting_team} is starting {exploiting} of {known} {hand} "
                f"hitters against him tonight.",
                value=round(split["gap"], 3), baseline=0.0,
                sample=(f"{split['vs_left_faced']} BF vs L, "
                        f"{split['vs_right_faced']} vs R"),
                surprise=surprise_score(split["gap"], 0.0, PLATOON_GAP_SPREAD),
                side=side,
                market_relevance=(
                    "Concentrated in the first five, while the starter is still "
                    "in the game."),
                evidence=TESTED_NULL,
                detail={"exploit_share": round(exploit_share, 3), **split}))
        return findings


class ThinMatchupHistory(Detector):
    """Name the small samples a bettor is about to be shown somewhere else.

    Batter-versus-pitcher is the most quoted statistic in baseball betting and
    almost all of it is noise: a live check of one star hitter against one
    pitcher returned two at-bats. Telling a sharp bettor that the 4-for-8 he is
    looking at is eight at-bats is worth as much as handing him a new angle, and
    is the half of the product nobody else builds.
    """

    name = "thin_matchup_history"
    markets = ("h2h",)
    status = UNPROVEN

    def run(self, game):
        history = game.get("matchup_history") or {}
        findings = []
        for side_key, side in (("away", AWAY), ("home", HOME)):
            # lineup_vs_pitcher returns the aggregate WITH the per-hitter lines
            # nested under "batters". Reading the wrapper as a list is the shape
            # error safe_run caught on the first live run.
            entries = (history.get(side_key) or {}).get("batters") or []
            thin = [e for e in entries
                    if (e.get("at_bats") or 0) and e["at_bats"] < THIN_AT_BATS]
            if not thin:
                continue
            loud = max(thin, key=lambda e: (e.get("hits") or 0) / max(e["at_bats"], 1))
            aggregate = history.get(side_key) or {}
            findings.append(Finding(
                self.name, DEBUNK,
                f"{loud.get('name')} is "
                f"{loud.get('hits')}-for-{loud.get('at_bats')} lifetime against "
                f"tonight's starter. That is {loud['at_bats']} at-bat"
                f"{'' if loud['at_bats'] == 1 else 's'} — it will be quoted "
                "somewhere today and it means nothing.",
                value=loud.get("at_bats"), sample=f"{loud['at_bats']} AB",
                # A debunk has no side: it is a reason to discount a number, not
                # evidence for a team. Claiming one would be a false statement.
                side=NEITHER, evidence=UNPROVEN,
                market_relevance="Reason to discount a number, not to act on one.",
                detail={"thin_matchups": len(thin),
                        "lineup_total_at_bats": aggregate.get("total_at_bats"),
                        "lineup_reason": aggregate.get("reason")}))
        return findings


class LineupVsStarter(Detector):
    """The aggregate matchup history, on the rare occasions it is big enough.

    Nine individually meaningless samples occasionally add up to one that is not.
    That is the honest version of Jacob's ask -- treat literal batter-versus-
    pitcher as supporting evidence, gated hard, rather than as a read -- and it
    is why the aggregate is reported separately from the individual lines the
    sibling detector debunks.

    Live example: one lineup had 104 career at-bats against tonight's starter
    while another had 5. The first is worth a sentence; the second is noise, and
    the difference between them is the sample gate.
    """

    name = "lineup_vs_starter"
    markets = ("h2h", "h2h_1st_5_innings")
    status = UNPROVEN

    def run(self, game):
        history = game.get("matchup_history") or {}
        away, home = game.teams
        findings = []
        for side_key, team, side in (("away", away, AWAY), ("home", home, HOME)):
            aggregate = history.get(side_key) or {}
            if not aggregate.get("usable"):
                continue
            avg = aggregate.get("aggregate_avg")
            if avg is None:
                continue
            score = surprise_score(avg, LEAGUE_BATTING_AVG, BATTING_AVG_SPREAD)
            if score is None or score < 1.0:
                continue
            findings.append(Finding(
                self.name, SIGNAL,
                f"{team}'s posted lineup is {aggregate['total_hits']}-for-"
                f"{aggregate['total_at_bats']} ({avg:.3f}) against tonight's "
                f"starter across their careers, against a league average of "
                f"{LEAGUE_BATTING_AVG:.3f}. Unusually, that is a large enough "
                "sample to be worth a sentence.",
                value=avg, baseline=LEAGUE_BATTING_AVG,
                sample=f"{aggregate['total_at_bats']} AB",
                surprise=score,
                side=side if avg > LEAGUE_BATTING_AVG else (
                    HOME if side is AWAY else AWAY),
                market_relevance="Supporting evidence only, never a read on its own.",
                evidence=TESTED_NULL,
                detail={"home_runs": aggregate.get("total_home_runs"),
                        "strikeouts": aggregate.get("total_strikeouts")}))
        return findings


def _since(load) -> str:
    """Where and when they came from, tolerating a missing day count."""
    days = load.get("days_since_last_game")
    where = load.get("last_venue") or "their last game"
    if days is None:
        return f"since {where}"
    return f"since {where}, {days} day(s) ago"


class TravelLoad(Detector):
    """Distance flown, zones crossed, and schedule density.

    Free, computable from data already on disk, and on nobody's stat page --
    which is the argument for it. A club that flew 2,000 miles east overnight
    into the third city of a road trip is in a materially different state from
    the one whose bus ride was across town, and no line on any screen says so.

    The DIRECTION is reported because it is not symmetric: flying east shortens
    the night against the body clock. That is a fact about the trip. Whether it
    costs runs tonight is the hypothesis, and it is the detector's to fail.
    """

    name = "travel_load"
    markets = ("h2h", "totals")
    status = UNPROVEN

    def run(self, game):
        travel = game.get("travel") or {}
        away, home = game.teams
        findings = []
        for team, side in ((away, AWAY), (home, HOME)):
            load = travel.get(team)
            if not load or load.get("miles") is None:
                continue
            miles = load["miles"]

            # Distance and schedule density are two different claims about two
            # different quantities, and merging them produced a finding that
            # scored a HOME STAND as surprising: surprise is absolute distance
            # from a baseline, so zero miles against a 1,200-mile threshold came
            # out as 1.7. Each claim now carries its own value and baseline, and
            # distance is measured from zero so a short trip scores near zero.
            if miles >= LONG_TRIP_MILES:
                direction = "east" if load.get("eastward") else "west"
                zones = (f", crossing {load['zones']:.1f} time zones"
                         if load.get("zones", 0) >= 1 else "")
                findings.append(Finding(
                    self.name, SIGNAL,
                    # "SD flew 2,078 miles east from SD" is technically correct
                    # and reads as a typo. When the last venue is the club's own
                    # park, the English is "from home".
                    f"{team} flew {miles:,.0f} miles {direction} from "
                    f"{'home' if load.get('last_venue') == team else load['last_venue']}"
                    f"{zones}.",
                    value=miles, baseline=TRAVEL_BASELINE,
                    # .get, not [] -- every field on a travel load is optional
                    # by design, and a detector that raises on a missing one
                    # turns a partial record into a blocked finding.
                    sample=_since(load),
                    surprise=surprise_score(miles, TRAVEL_BASELINE, TRAVEL_SPREAD),
                    side=HOME if side is AWAY else AWAY,
                    market_relevance=(
                        "Applies to the whole game rather than to the starters."),
                    evidence=TESTED_NULL, detail=load))

            # A "dense stretch" that matches the baseline exactly is six games
            # in seven days, which is what a normal week looks like. Saying so
            # under a heading that promises something interesting spends the
            # reader's attention on nothing.
            if load.get("dense_stretch") and load["games_last_7"] > DENSE_BASELINE_GAMES:
                games = load["games_last_7"]
                findings.append(Finding(
                    self.name, CONTEXT,
                    f"{team} has played {games} games in seven days.",
                    value=float(games), baseline=float(DENSE_BASELINE_GAMES),
                    sample="7-day window",
                    surprise=surprise_score(games, DENSE_BASELINE_GAMES, 1.0),
                    side=NEITHER, evidence=TESTED_NULL, detail=load))
        return findings


class ParkAndWeather(Detector):
    """Run environment, where it is actually unusual.

    Weather has been collected by this project since the beginning and used by
    nothing. Most nights it says nothing worth reading, which is why it stays
    silent unless the park or the conditions are genuinely off the norm.

    Wind is deliberately NOT interpreted as helping or hurting: park orientation
    is unknown for all thirty parks, and a wrong bearing inverts a real effect.
    Reporting speed without direction is the honest half.
    """

    name = "park_and_weather"
    markets = ("totals", "totals_1st_5_innings")
    status = UNPROVEN

    def run(self, game):
        park = game.get("park") or {}
        weather = game.get("weather") or {}
        findings = []

        altitude = park.get("altitude_m")
        if altitude is not None and altitude >= HIGH_ALTITUDE_M:
            findings.append(Finding(
                self.name, SIGNAL,
                f"{park.get('name')} sits at {altitude:,} m, far above the "
                f"{LEAGUE_ALTITUDE_M:,} m of a typical park — the ball carries "
                "and the run environment is not the league's.",
                value=float(altitude), baseline=float(LEAGUE_ALTITUDE_M),
                surprise=surprise_score(altitude, LEAGUE_ALTITUDE_M, 250.0),
                side=NEITHER, evidence=UNPROVEN,
                market_relevance="Bears on the total, not on either side."))

        temp = weather.get("temp_f")
        if temp is not None and abs(temp - LEAGUE_TEMP_F) >= TEMP_NOTABLE_F:
            warmer = temp > LEAGUE_TEMP_F
            # The physics only runs one way, so the sentence has to. Printing
            # the cold-air explanation on a 94F night is the kind of detail that
            # makes a reader stop trusting everything else on the page.
            physics = ("Warm air is thinner and the ball carries further"
                       if warmer else
                       "Cold air is denser and the ball carries less")
            findings.append(Finding(
                self.name, SIGNAL,
                f"First pitch is forecast at {temp:.0f}F against a typical "
                f"{LEAGUE_TEMP_F:.0f}F. {physics}.",
                value=float(temp), baseline=float(LEAGUE_TEMP_F),
                surprise=surprise_score(temp, LEAGUE_TEMP_F, 12.0),
                side=NEITHER, evidence=UNPROVEN,
                market_relevance="Bears on the total."))

        wind = weather.get("wind_mph")
        if wind is not None and wind >= STRONG_WIND_MPH:
            findings.append(Finding(
                self.name, CONTEXT,
                f"Wind is forecast at {wind:.0f} mph. Its direction is NOT "
                "interpreted here: this park's orientation is unrecorded, and a "
                "wrong bearing would invert the effect rather than mute it.",
                value=float(wind), baseline=float(STRONG_WIND_MPH),
                side=NEITHER, evidence=BLOCKED))
        return findings


class BullpenExposure(Detector):
    """How much of tonight's game the bullpens will actually decide.

    The honest version of the third-time-through-order question without
    pitch-level data. A starter who averages five innings hands his pen four; one
    who averages six and a half hands them two and a half. Over a season that
    difference is the single largest driver of how far a full-game result can
    drift from the first-five result -- which is precisely the gap the
    implied-bullpen detector reads out of the market.

    So this is the input the market's own number should be compared against, and
    it is computed from the two starters' innings per start, which the pitcher
    features already carry.
    """

    name = "bullpen_exposure"
    markets = ("h2h", "h2h_1st_5_innings")
    status = UNPROVEN

    def run(self, game):
        starters = game.get("starters") or {}
        away, home = game.teams
        findings = []
        for prefix, team, side in (("away_", away, AWAY), ("home_", home, HOME)):
            per_start = starters.get(f"{prefix}sp_ip_per_start")
            if per_start is None:
                continue

            # Below the floor, say so instead of pretending to a read. A thin
            # sample producing an extreme average is the exact failure this
            # product is supposed to catch for the reader, so catching it in
            # our own output is not optional.
            starts = starters.get(f"{prefix}sp_starts")
            if starts is not None and starts < MIN_STARTS_FOR_EXPOSURE:
                findings.append(Finding(
                    self.name, DEBUNK,
                    f"{team}'s starter averages {per_start:.2f} innings across "
                    f"only {starts} start(s). That is too few to describe how "
                    f"long he goes \u2014 an opener or a first-time starter "
                    f"looks identical to a collapse at this sample size.",
                    value=per_start, baseline=LEAGUE_IP_PER_START,
                    sample=f"{starts} start(s)", surprise=None,
                    side=NEITHER, evidence=TESTED_NULL,
                    market_relevance=(
                        "No read either way; the bullpen exposure is unknown, "
                        "not unusual.")))
                continue

            score = surprise_score(per_start, LEAGUE_IP_PER_START, IP_PER_START_SPREAD)
            if score is None or score < 1.0:
                continue
            exposed = max(0.0, 9.0 - per_start)
            short = per_start < LEAGUE_IP_PER_START
            findings.append(Finding(
                self.name, SIGNAL,
                f"{team}'s starter averages {per_start:.2f} innings a start "
                f"against a league {LEAGUE_IP_PER_START:.2f}, so about "
                f"{exposed:.1f} innings of this game go to a bullpen "
                f"{'sooner' if short else 'later'} than usual.",
                value=per_start, baseline=LEAGUE_IP_PER_START,
                sample=f"{starters.get(prefix + 'sp_innings')} IP",
                surprise=score,
                # A short starter argues against his own side on the full game
                # while leaving the first five largely alone.
                side=(HOME if side is AWAY else AWAY) if short else side,
                market_relevance=(
                    "This is the quantity the market's full-game minus "
                    "first-five gap is pricing."),
                evidence=TESTED_NULL,
                detail={"innings_exposed_to_bullpen": round(exposed, 2)}))
        return findings


class PitchMixMismatch(Detector):
    """A starter's most-used pitch, against the lineup that actually faces it.

    THE DECOMPOSITION AT PITCH LEVEL
    --------------------------------
    This is the closest baseball gets to the example the project was described
    with -- a defence that is bad against one position, facing the player who
    exploits exactly that. Here it is a pitcher who throws one pitch half the
    time, against nine hitters whose measured performance against that pitch is
    collectively unusual.

    Both halves come from the same leaderboard, so they are directly comparable:
    usage share on the pitcher's side, wOBA against that pitch type on each
    hitter's side, weighted by how much of his own diet it is.

    WHY ONLY THE PRIMARY PITCH
    --------------------------
    A pitcher throwing five pitches has five hypotheses, and testing all of them
    on every game is how a family of forty detectors becomes a family of two
    hundred without anyone noticing. One pitch per starter -- the one he actually
    throws most -- keeps the hypothesis count equal to the detector count.
    """

    name = "pitch_mix_mismatch"
    markets = ("h2h", "h2h_1st_5_innings", "totals_1st_5_innings")
    status = UNPROVEN

    def run(self, game):
        arsenals = game.get("arsenals") or {}
        lineups = game.get("lineups") or {}
        if not arsenals or not lineups:
            return []

        away, home = game.teams
        findings = []
        for pitcher_side, lineup_key, pitcher_team, batting_team, side in (
                ("away", "home", away, home, HOME),
                ("home", "away", home, away, AWAY)):
            arsenal = arsenals.get(pitcher_side) or []
            if not arsenal:
                continue
            primary = arsenal[0]
            usage = primary.get("pitch_usage")
            if usage is None or usage < PRIMARY_PITCH_USAGE:
                continue

            batters = (lineups.get(lineup_key) or {}).get("vs_pitch") or {}
            rows = batters.get(primary.get("pitch_type")) or []
            if len(rows) < MIN_HITTERS_FOR_PITCH_READ:
                continue

            # Weight each hitter by how much of his own diet this pitch is, so a
            # hitter who barely sees it does not swing the lineup's number.
            weights = [r.get("pa") or 0 for r in rows]
            total = sum(weights)
            if not total:
                continue
            lineup_woba = sum((r.get("woba") or 0) * w
                              for r, w in zip(rows, weights)) / total

            score = surprise_score(lineup_woba, LEAGUE_WOBA, WOBA_SPREAD)
            if score is None or score < 1.0:
                continue
            strong = lineup_woba > LEAGUE_WOBA
            findings.append(Finding(
                self.name, SIGNAL,
                f"{pitcher_team}'s starter throws his "
                f"{primary.get('pitch_name', 'primary pitch').lower()} "
                f"{usage:.0f}% of the time, and {batting_team}'s posted lineup "
                f"is at a {lineup_woba:.3f} wOBA against that pitch — a league "
                f"average is {LEAGUE_WOBA:.3f}.",
                value=round(lineup_woba, 3), baseline=LEAGUE_WOBA,
                sample=f"{len(rows)} hitters, {int(total)} plate appearances",
                surprise=score,
                side=side if strong else (HOME if side is AWAY else AWAY),
                market_relevance=(
                    "Applies while the starter is in the game, so it bears on "
                    "the first five more than the full nine."),
                evidence=TESTED_NULL,
                detail={"pitch_type": primary.get("pitch_type"),
                        "usage": usage, "hitters": len(rows)}))
        return findings


def register_defaults():
    """The pre-registered family. Order is presentation only."""
    for detector in (ImpliedBullpenDisagreement(), BullpenWorkload(),
                     StaleBook(), StarterMismatch(), PlatoonMismatch(),
                     ThinMatchupHistory(), LineupVsStarter(), TravelLoad(),
                     ParkAndWeather(), BullpenExposure(), PitchMixMismatch()):
        register(detector)
