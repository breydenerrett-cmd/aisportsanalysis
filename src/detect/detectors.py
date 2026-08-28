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
                             UNPROVEN, register, surprise_score)
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
                evidence=UNPROVEN,
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
                evidence=HISTORICAL_CANDIDATE,
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
                sample="<20 IP", evidence=UNPROVEN)]

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
                evidence=UNPROVEN))
        return findings


class LineupHandedness(Detector):
    """Blocked until lineups are ingested. Declared rather than omitted."""

    name = "lineup_handedness"
    markets = ("h2h", "h2h_1st_5_innings", "totals_1st_5_innings")
    status = BLOCKED
    blocked_reason = (
        "starting lineups are not yet ingested, so the platoon composition "
        "facing each starter cannot be computed")

    def run(self, game):
        return []


def register_defaults():
    """The pre-registered family. Order is presentation only."""
    for detector in (ImpliedBullpenDisagreement(), BullpenWorkload(),
                     StaleBook(), StarterMismatch(), LineupHandedness()):
        register(detector)
