"""Mismatch scanner: find games where the talent gap is obvious, and stay quiet otherwise.

WHY THIS EXISTS, AND WHY IT IS NOT THE MODEL
--------------------------------------------
Everything else in this repository optimises one objective: estimate a probability,
compare it to the de-vigged market, act on the difference. That is expected-value
betting, and it is a legitimate system. It is not the system this project is being
built for.

The stated approach is different in kind:

    "trying to find bets that have good value or EV isn't necessarily a part of
     the strat"

    "we're just trying to find clear advantages that other people aren't finding"

and, decisively, the counter-example:

    "there's a game today with Yamamoto versus Chris Sale and that's just a great
     pitching matchup against both teams and you just don't know what's gonna
     happen and it's -115 ml ... but like if the pitching matchup was super
     different and we had a superstar on one team and not on the other"

Read carefully, that rules out the EV frame twice over. Two aces at -115 is exactly
where an EV model has the most to say -- a near-coin-flip price is where a small
probability difference produces the largest edge estimate. It is rejected anyway,
because the reason for rejection is not the price. It is that the OUTCOME IS
UNPREDICTABLE. Ace against ace is a high-variance game whatever the number says.

So this module scores a different quantity. Not "is this priced wrong" but
"is the difference between these two teams large enough to see without a model".
Those are close to opposites. A gap that is obvious is usually well priced; the
EV frame would discard it for that very reason. Here the price only matters as a
check that the gap has not been blown out to the point where nothing is left.

THE DEFAULT ANSWER IS NO PLAY
-----------------------------
    "slate looks ass"

A day with nothing on it is the normal case, not a failure of the scanner. Most
major-league games are between two roughly major-league teams and are genuinely
close to coin flips; that is what a hundred and thirty years of competitive balance
engineering produces. A scanner that finds something every day is not detecting
mismatches, it is detecting noise and calling it a signal.

`scan_slate` therefore reports `no_play` as a first-class verdict with reasons,
and a clean empty slate is a correct, complete result.

WHY FIRST FIVE INNINGS IS A NAMED MARKET HERE
---------------------------------------------
    "there is value on like the over under runs in the first five innings"

This is not an arbitrary preference, and the mechanism is worth stating because it
determines where a starter mismatch should be expressed:

A starting pitcher throws roughly five to six innings. Over a full nine-inning game
his contribution is diluted by two to four innings of bullpen -- and bullpens are
far more alike across teams than starters are. So a large starter gap is largest
in innings one through five and shrinks after that. Betting a starter mismatch on
the full-game line is betting it through a layer of noise that has nothing to do
with the reason for the bet.

The scanner therefore routes a starter-driven mismatch to F5 and a roster-driven
one to the full game, and says which and why.

WHAT THIS MODULE DOES NOT CLAIM
-------------------------------
Every threshold below is set from stated baseball reasoning BEFORE seeing whether it
would have made money. None is tuned against a backtest, and none may be. They are
pre-registered here in the same spirit as docs/VALIDATION_CRITERIA.md, and the calls
are logged so they can be graded forward on games that have not been played.

An obvious mismatch is not a profitable bet. It is a candidate for a human to look
at. The scanner's output is a shortlist and a reason, never a recommendation to
stake money.
"""

from __future__ import annotations

from src.core import odds as odds_math
from src.pipeline import features as team_features_mod
from src.pipeline import pitchers as pitchers_mod

# ---------------------------------------------------------------------------
# Pre-registered thresholds. Set from baseball reasoning, never from results.
# ---------------------------------------------------------------------------

# A full run of FIP per nine innings. Starter FIP across a season spans roughly
# 2.80 at the top to 5.20 at replacement level, so one run is about a third of the
# entire league range -- the difference between a rotation's best and its worst.
# That is the scale of "a superstar on one team and not on the other". Half a run
# is a real difference that requires a model to trust; this deliberately is not it.
OBVIOUS_FIP_GAP = 1.00

# K-BB% is the most stable starter rate at small samples, which is why the charter
# named it. Ten percentage points separates an ace from a back-end starter.
OBVIOUS_K_BB_GAP = 0.10

# Below this, a starter is good enough that the game is unpredictable regardless of
# who he is facing. When BOTH starters clear it the game is suppressed outright --
# this is the Yamamoto/Sale rule, and it fires before any gap is considered.
STRONG_FIP = 3.50

# One run per game of run differential is roughly the distance between a playoff
# team and a seller at the deadline. Visible in a standings table.
OBVIOUS_RUN_DIFF_GAP = 1.00

# Past this de-vigged price the market has already made the mismatch its headline.
# There is nothing left that "other people aren't finding". Note this is a screen
# on the MARKET ALONE -- no model probability is involved, so it is not an edge test.
ALREADY_PRICED_PROB = 0.65

# A gap computed from a handful of starts is small-sample luck. Mirrors the
# suppression thresholds the feature builders already enforce.
MIN_INNINGS = pitchers_mod.MIN_INNINGS_FOR_RATES
MIN_TEAM_GAMES = team_features_mod.MIN_GAMES_FOR_RATES

# How many independent signals must agree before a game is flagged. One signal is
# an observation; two pointing the same way is what "obvious" means.
MIN_AGREEING_SIGNALS = 2


class MismatchError(RuntimeError):
    """Raised when a game cannot be scanned."""


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

NO_PLAY = "no_play"
CANDIDATE = "candidate"
FLAGGED = "flagged"
INSUFFICIENT_DATA = "insufficient_data"

MARKET_F5 = "first_five_totals"
MARKET_FULL = "full_game"


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------

def _signed(value, favours_home_when_negative=True):
    """Turn a home-minus-away difference into (side, magnitude).

    The feature builders emit `diff_*` as home minus away. For ERA-like metrics
    lower is better, so a negative difference favours the home side; for rate
    metrics where higher is better the sense inverts. Getting this backwards would
    flag the wrong team every single time and nothing would throw, so the direction
    is a named argument rather than an inline sign.
    """
    if value is None:
        return None, None
    if value == 0:
        return None, 0.0
    home_favoured = (value < 0) if favours_home_when_negative else (value > 0)
    return ("home" if home_favoured else "away"), abs(value)


def starter_signal(pitcher_features) -> dict:
    """Is the starting pitching matchup lopsided, and which way?

    Returns a dict that always explains itself. `side` is None whenever the signal
    does not fire, and `reason` says why -- unknown starter, thin sample, both aces,
    or simply too close.
    """
    result = {"signal": "starters", "side": None, "magnitude": None,
              "fires": False, "reason": None, "detail": {}}

    if not pitcher_features.get("both_sp_known"):
        result["reason"] = "a probable starter is unannounced or has no prior appearances"
        return result
    if pitcher_features.get("either_sp_thin"):
        result["reason"] = (
            f"a starter has fewer than {MIN_INNINGS:.0f} prior innings this season; "
            "his rates are small-sample noise")
        return result

    away_fip = pitcher_features.get("away_sp_fip")
    home_fip = pitcher_features.get("home_sp_fip")
    result["detail"] = {"away_sp_fip": away_fip, "home_sp_fip": home_fip}

    if away_fip is None or home_fip is None:
        result["reason"] = "FIP unavailable for one starter"
        return result

    # THE YAMAMOTO/SALE RULE. Two good starters make an unpredictable game whatever
    # the gap between them is, so this fires before the gap is even measured.
    if away_fip <= STRONG_FIP and home_fip <= STRONG_FIP:
        result["reason"] = (
            f"both starters are strong (FIP {away_fip:.2f} and {home_fip:.2f}, "
            f"both under {STRONG_FIP:.2f}) -- a good pitching matchup on both sides "
            "is exactly the game whose outcome you cannot call")
        result["detail"]["both_strong"] = True
        return result

    fip_side, fip_gap = _signed(pitcher_features.get("diff_sp_fip"),
                               favours_home_when_negative=True)
    k_side, k_gap = _signed(pitcher_features.get("diff_sp_k_bb_pct"),
                            favours_home_when_negative=False)
    result["detail"].update({"fip_gap": fip_gap, "k_bb_gap": k_gap})

    fip_fires = fip_gap is not None and fip_gap >= OBVIOUS_FIP_GAP
    k_fires = k_gap is not None and k_gap >= OBVIOUS_K_BB_GAP

    if not (fip_fires or k_fires):
        result["reason"] = (
            f"starters are close (FIP gap {fip_gap:.2f}, needs {OBVIOUS_FIP_GAP:.2f})"
            if fip_gap is not None else "no usable starter gap")
        return result

    # Both rates firing in opposite directions is not an obvious mismatch, it is a
    # disagreement between two measurements of the same thing.
    if fip_fires and k_fires and fip_side != k_side:
        result["reason"] = "FIP and K-BB% disagree about which starter is better"
        return result

    result["side"] = fip_side if fip_fires else k_side
    result["magnitude"] = fip_gap if fip_fires else k_gap
    result["fires"] = True
    parts = []
    if fip_fires:
        parts.append(f"FIP gap {fip_gap:.2f}")
    if k_fires:
        parts.append(f"K-BB% gap {k_gap * 100:.1f} points")
    result["reason"] = f"clear starter edge to {result['side']} ({', '.join(parts)})"
    return result


def roster_signal(team_features) -> dict:
    """Is one club simply the better team, by a margin visible in the standings?"""
    result = {"signal": "roster", "side": None, "magnitude": None,
              "fires": False, "reason": None, "detail": {}}

    away_rd = team_features.get("away_run_diff_pg")
    home_rd = team_features.get("home_run_diff_pg")
    result["detail"] = {"away_run_diff_pg": away_rd, "home_run_diff_pg": home_rd}

    if away_rd is None or home_rd is None:
        result["reason"] = (
            f"a team has played fewer than {MIN_TEAM_GAMES} games this season; "
            "its run differential is not yet a rate")
        return result

    gap = home_rd - away_rd
    side, magnitude = _signed(gap, favours_home_when_negative=False)
    result["detail"]["run_diff_gap"] = magnitude

    if magnitude is None or magnitude < OBVIOUS_RUN_DIFF_GAP:
        result["reason"] = (
            f"teams are close on run differential (gap {magnitude:.2f}, "
            f"needs {OBVIOUS_RUN_DIFF_GAP:.2f})" if magnitude is not None
            else "no usable run differential")
        return result

    result["side"] = side
    result["magnitude"] = magnitude
    result["fires"] = True
    result["reason"] = (
        f"clear roster edge to {side} ({magnitude:.2f} runs per game of "
        "differential between them)")
    return result


def market_screen(away_price, home_price, side) -> dict:
    """Has the market already made this mismatch its headline?

    This is NOT an expected-value test. No model probability enters it. It asks one
    question: is the favourite already so short that the gap everyone can see has
    been fully charged for. That is the operational reading of "advantages that
    other people aren't finding".
    """
    result = {"signal": "market", "fires": False, "reason": None, "detail": {}}
    if away_price is None or home_price is None:
        result["reason"] = "no moneyline available to screen against"
        return result

    try:
        fair = odds_math.devig_two_way(float(away_price), float(home_price))
    except (ValueError, TypeError) as exc:
        result["reason"] = f"moneyline could not be de-vigged: {exc}"
        return result

    away_fair, home_fair = fair
    result["detail"] = {"away_fair_prob": round(away_fair, 4),
                        "home_fair_prob": round(home_fair, 4)}
    if side is None:
        result["reason"] = "no side to screen"
        return result

    favoured = home_fair if side == "home" else away_fair
    result["detail"]["side_fair_prob"] = round(favoured, 4)

    if favoured >= ALREADY_PRICED_PROB:
        result["reason"] = (
            f"the market already prices {side} at {favoured:.1%} -- this mismatch "
            "is not one other people are missing")
        return result

    result["fires"] = True
    result["reason"] = (
        f"the market has {side} at only {favoured:.1%} despite the gap above")
    return result


# ---------------------------------------------------------------------------
# Where to express a mismatch
# ---------------------------------------------------------------------------

def route_market(starter, roster) -> dict:
    """Decide which market a fired mismatch belongs in, and say why.

    The routing is mechanical, not a preference. A starter gap lives in innings one
    through five and is diluted by bullpens after that, so it belongs on the first-five
    line. A roster gap applies for all nine innings and belongs on the full game.
    """
    if starter["fires"] and not roster["fires"]:
        return {
            "market": MARKET_F5,
            "why": (
                "the gap is in the starting pitching, and a starter is only in the "
                "game for about five innings -- expressing it over nine dilutes it "
                "through two to four innings of bullpen, which is the part of a "
                "roster that varies least between clubs"),
        }
    if roster["fires"] and not starter["fires"]:
        return {
            "market": MARKET_FULL,
            "why": ("the gap is roster-wide rather than in the starters, so it "
                    "applies across all nine innings"),
        }
    return {
        "market": MARKET_F5,
        "why": ("both the starter and the roster gap point the same way; the first "
                "five is where the two overlap most cleanly, with the starter "
                "advantage still on the mound"),
    }


# ---------------------------------------------------------------------------
# Per-game scan
# ---------------------------------------------------------------------------

def scan_game(game, team_feats, pitcher_feats) -> dict:
    """Stage one: score one game on talent alone, and decide which market it belongs in.

    NO PRICE ENTERS THIS FUNCTION. That is deliberate and it is not a simplification --
    it resolves a circularity that a single-stage scanner cannot escape.

    The market screen has to run against the market the game is actually routed to. A
    starter mismatch routed to the first five must be screened on the first-five price,
    because a first-five line IS a starter line and is priced as one: measured live on
    27 Aug 2026, both flagged games' F5 prices de-vigged SHORTER than their full-game
    prices, and one of them passed a screen on the full game that it would have failed
    on the market it was being sent to.

    But first-five prices are billed per event, so pricing every game to find out costs
    sixteen times what pricing the candidates costs. You cannot afford to price
    everything, and you cannot screen correctly until you know the routing.

    Splitting the stages resolves it. Talent and routing are free and run on everything;
    the price is fetched only for what survives, and only for the market it was routed
    to. `candidate` is therefore an honest intermediate state, not a weaker verdict --
    it means "this cleared the talent bar and has not been priced yet".
    """
    starter = starter_signal(pitcher_feats or {})
    roster = roster_signal(team_feats or {})

    record = {
        "game_pk": game.get("game_pk"),
        "date": game.get("date"),
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "verdict": NO_PLAY,
        "side": None,
        "market": None,
        "signals": {"starters": starter, "roster": roster},
        "reasons": [],
    }

    agreeing = [s for s in (starter, roster) if s["fires"]]
    sides = {s["side"] for s in agreeing}

    if not agreeing:
        record["reasons"] = [starter["reason"], roster["reason"]]
        record["summary"] = "nothing obvious: " + "; ".join(
            r for r in record["reasons"] if r)
        return record

    if len(sides) > 1:
        record["reasons"] = [
            "the starter edge and the roster edge favour opposite teams, so neither "
            "is a clear advantage",
            starter["reason"], roster["reason"]]
        record["summary"] = "signals contradict each other"
        return record

    side = sides.pop()

    if len(agreeing) < MIN_AGREEING_SIGNALS:
        # One signal firing alone is an observation, not something anyone would call
        # obvious at a glance. It is reported so a human can look, and it is NOT a
        # candidate -- the bar is deliberately above "one number is big".
        record["side"] = side
        record["reasons"] = [agreeing[0]["reason"],
                             "only one signal fires; the other says: "
                             + (starter if roster["fires"] else roster)["reason"]]
        record["summary"] = f"single signal to {side}, below the bar for obvious"
        return record

    routing = route_market(starter, roster)
    record.update({
        "verdict": CANDIDATE,
        "side": side,
        "market": routing["market"],
        "reasons": [starter["reason"], roster["reason"], routing["why"]],
    })
    record["summary"] = (
        f"{side} has a clear advantage on both starter and roster; belongs on the "
        f"{_market_label(routing['market'])}, not yet priced")
    return record


def _market_label(market) -> str:
    return "first five" if market == MARKET_F5 else "full game"


def apply_market_screen(scan, away_price, home_price) -> dict:
    """Stage two: screen a candidate against the price of the market it was routed to.

    The caller is responsible for passing the RIGHT prices -- first-five prices for an
    F5-routed candidate, full-game prices otherwise. Passing full-game prices for an F5
    candidate is the exact defect this split exists to fix, so the market the prices
    came from is recorded on the result and can be checked.

    Returns a new dict; the input scan is not mutated, so an unpriced candidate stays
    readable next to its priced outcome.
    """
    result = dict(scan)
    result["signals"] = dict(scan["signals"])

    if scan["verdict"] != CANDIDATE:
        return result

    screen = market_screen(away_price, home_price, scan["side"])
    screen["priced_market"] = scan["market"]
    result["signals"]["market"] = screen
    result["reasons"] = list(scan["reasons"]) + [screen["reason"]]

    if not screen["fires"]:
        result["verdict"] = NO_PLAY
        result["summary"] = screen["reason"]
        return result

    result["verdict"] = FLAGGED
    result["summary"] = (
        f"{scan['side']} has a clear advantage on both starter and roster, and the "
        f"{_market_label(scan['market'])} market has not blown it out")
    return result


# ---------------------------------------------------------------------------
# Slate scan
# ---------------------------------------------------------------------------

def scan_slate(games) -> dict:
    """Stage one across a whole day, reporting the honest total including zero.

    `games` is a list of dicts already carrying `team_features` and `pitcher_features`
    -- assembling those is the caller's job so this stays a pure function of
    point-in-time inputs and is trivially testable.

    Returns candidates, not flags. Nothing here is priced; call `finalize_slate` with
    prices for the routed markets to reach a flagged verdict.
    """
    scans = [scan_game(g, g.get("team_features"), g.get("pitcher_features"))
             for g in games]
    candidates = [s for s in scans if s["verdict"] == CANDIDATE]
    return {
        "games_scanned": len(scans),
        "candidates": candidates,
        "flagged": [],
        "scans": scans,
        "priced": False,
        "verdict": CANDIDATE if candidates else NO_PLAY,
        "summary": _slate_summary(len(scans), candidates, priced=False),
    }


def finalize_slate(result, prices_by_game) -> dict:
    """Stage two across a slate: screen each candidate on its own routed market.

    `prices_by_game` maps game_pk to {"away_price", "home_price"} for the market that
    candidate was routed to. A candidate with no entry stays a candidate rather than
    being flagged or discarded -- an unavailable price is a missing screen, and a
    missing screen is not a pass.
    """
    finalized = []
    for scan in result["scans"]:
        prices = (prices_by_game or {}).get(scan.get("game_pk"))
        if scan["verdict"] != CANDIDATE or not prices:
            finalized.append(scan)
            continue
        finalized.append(apply_market_screen(
            scan, prices.get("away_price"), prices.get("home_price")))

    flagged = [s for s in finalized if s["verdict"] == FLAGGED]
    candidates = [s for s in finalized if s["verdict"] == CANDIDATE]
    return {
        "games_scanned": len(finalized),
        "candidates": candidates,
        "flagged": flagged,
        "scans": finalized,
        "priced": True,
        "verdict": FLAGGED if flagged else NO_PLAY,
        "summary": _slate_summary(len(finalized), flagged, priced=True,
                                  unpriced=len(candidates)),
    }


def _slate_summary(n, hits, priced, unpriced=0) -> str:
    if not n:
        return "no games on this date"
    noun = "flagged" if priced else "candidate(s)"
    if not hits:
        # This is the expected outcome on most days, and it is stated as a result
        # rather than as an apology. A scanner that finds something daily is
        # measuring noise.
        tail = (f" {unpriced} cleared the talent bar but could not be priced."
                if unpriced else "")
        return (
            f"No play. {n} games scanned, none with an advantage obvious enough to "
            "act on. Most days look like this -- two roughly major-league teams "
            f"playing a close game is the normal state of a major-league slate.{tail}")
    lines = [f"{len(hits)} of {n} games {noun}."]
    for scan in hits:
        lines.append(
            f"  {scan['away_team']} @ {scan['home_team']}: {scan['side']} "
            f"({_market_label(scan['market'])}) -- "
            f"{scan['signals']['starters']['reason']}")
    if priced and unpriced:
        lines.append(f"  ({unpriced} more cleared the talent bar but could not be "
                     "priced, so they are neither flagged nor cleared)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_scan_inputs(store, games, pitcher_logs=None, odds_by_matchup=None) -> list:
    """Attach point-in-time features and prices to each game, ready for scan_slate.

    Kept separate from scan_slate so the scoring stays a pure function of its inputs
    and can be tested without a data store. Features come from the same builders the
    model uses, so a scan of a past date sees only what was knowable on that morning.
    """
    prepared = []
    fip_constant = None
    if pitcher_logs is not None and games:
        latest = max((g.get("date") or "" for g in games), default="2100-01-01")
        fip_constant = pitchers_mod.league_fip_constant(pitcher_logs, latest)

    for game in games:
        row = dict(game)
        row["team_features"] = team_features_mod.matchup_features(
            store, game.get("away_team"), game.get("home_team"), game.get("date"))
        if pitcher_logs is not None:
            row["pitcher_features"] = pitchers_mod.matchup_pitcher_features(
                pitcher_logs, game.get("away_probable_id"),
                game.get("home_probable_id"), game.get("date"),
                fip_constant=fip_constant)
        else:
            row["pitcher_features"] = {}
        prices = (odds_by_matchup or {}).get(
            (game.get("away_team"), game.get("home_team")))
        if prices:
            row["ml_away_price"] = prices.get("away_price")
            row["ml_home_price"] = prices.get("home_price")
        prepared.append(row)
    return prepared
