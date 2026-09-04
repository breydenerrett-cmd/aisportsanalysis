"""The loss post-mortem: what happened, where it turned, and which of three
things it was -- computed from real play-by-play, never from vibes.

WHAT THIS IS FOR
-----------------
Settlement (`src.engine.settle_slate`) records win/loss and nothing about
why; the EOD report lists losers as bare lines. This module answers the
owner's question -- "if it hits great, and if not, why does it think it lost
that bet, what were the pivots in the game" -- from the game's own record
(`src.pipeline.gameflow`, MLB's free play-by-play and win-probability
series) joined to what the engine actually claimed at decision time
(`DecisionRecord`) and what settlement observed (`ReviewRecord`).

A POST-MORTEM IS A DESCRIPTION, NEVER EVIDENCE FOR A STRATEGY CHANGE
----------------------------------------------------------------------
docs/RESEARCH_CATALOGUE.md T8 records "no rescue by threshold change" as a
standing rule of this project, and it applies here with full force. Nothing
in this module returns, recommends, or implies a parameter value. A
post-mortem is written AFTER the outcome is known, on the games we happened
to lose, with the outcome in hand -- it is the single most overfittable
artifact this system can produce, and the only safe use of it is
description. `suggest_research` emits QUESTIONS to prespecify and test on
held-out data, never adjustments; `_REFUSED_SUGGESTION_TERMS` is a hard
guard that stops a threshold-shaped sentence from being emitted at all.

THE WIN CONTROL IS NOT OPTIONAL
---------------------------------
A post-mortem process pointed only at losses manufactures exactly one story:
our reasoning was fine, we were unlucky. `build_postmortems` therefore runs
the SAME classifier over won bets, and `summarize` reports the verdict
distribution for losses beside the distribution for wins. A verdict class
that appears at the same rate in wins as in losses is measuring the games we
bet, not the bets we lost, and the summary says so in those words.

NEVER FABRICATE A WIN-PROBABILITY NUMBER
------------------------------------------
The pivot is measured on MLB's own win-probability series when, and only
when, the bet settles on the full-game winner that series predicts AND the
API served one. Otherwise the pivot is measured on a documented,
deterministic run-margin proxy (`PIVOT_METRIC_RUN_MARGIN`, defined in
`_margin_series`) and every rendering of it carries the word "proxy". There
is no third path where a probability gets modelled, interpolated, or
borrowed from a similar game.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from src.core.asof import game_pk_key

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

VERDICT_REASONING_WRONG = "REASONING_WRONG"
VERDICT_INFORMATION_MISSING = "INFORMATION_MISSING"
VERDICT_VARIANCE = "VARIANCE"

VERDICTS = (VERDICT_REASONING_WRONG, VERDICT_INFORMATION_MISSING,
            VERDICT_VARIANCE)

# Why a VARIANCE verdict was reachable. The distinction matters enormously
# and collapsing it would be dishonest:
#   mechanism_confirmed      -- the decision named checkable claims, the game
#                               upheld every one of them, and the result went
#                               the other way anyway. Real variance.
#   no_falsifiable_mechanism -- the decision named NO checkable claim, so
#                               nothing about it could be refuted by any game
#                               ever played. The loss carries zero
#                               information about the reasoning. This is a
#                               statement about the thesis, not an
#                               exoneration of it.
QUALIFIER_MECHANISM_CONFIRMED = "mechanism_confirmed"
QUALIFIER_NO_FALSIFIABLE_MECHANISM = "no_falsifiable_mechanism"

PIVOT_METRIC_WIN_PROBABILITY = "win_probability"
PIVOT_METRIC_RUN_MARGIN = "run_margin_proxy"

# A pattern needs this many losses before it is called a pattern at all, and
# it must also cover this share of losses AND appear at least this many times
# more often among losses than among the won control. One game is an
# anecdote; two games sharing a property is a coincidence with a name.
MIN_PATTERN_N = 3
MIN_PATTERN_SHARE = 0.25
MIN_PATTERN_LIFT = 2.0

# Words that turn a research question into a parameter change. A suggestion
# containing any of them is dropped and replaced by a refusal line -- T8's
# "no rescue by threshold change", enforced rather than remembered.
_REFUSED_SUGGESTION_TERMS = (
    "threshold", "raise the", "lower the", "increase the", "decrease the",
    "tighten", "loosen", "stake more", "stake less", "bet more", "bet less",
    "filter out", "stop betting", "cutoff",
)


class PostMortemError(ValueError):
    """A post-mortem could not be built honestly."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pivot:
    """The single play that moved the game most against our selection."""

    metric: str  # PIVOT_METRIC_*
    metric_reason: str  # why this metric and not the other
    inning: Optional[int]
    half: Optional[str]
    outs_before: Optional[int]
    bases_before: Optional[str]
    batter_name: Optional[str]
    pitcher_name: Optional[str]
    event: Optional[str]
    description: Optional[str]
    before: Optional[float]
    after: Optional[float]
    swing: Optional[float]  # signed, negative = against our selection
    pitcher_was_starter: Optional[bool]


@dataclass(frozen=True)
class HalfInningPivot:
    """The half-inning that moved the game most against our selection.

    A single play understates a blowout: a five-run inning arrives as five
    separate plate appearances, none of them individually the largest swing
    in the game. This aggregates the same signed swing over each (inning,
    half) so the report can name the inning as well as the play.
    """

    inning: Optional[int]
    half: Optional[str]
    metric: str
    before: Optional[float]
    after: Optional[float]
    swing: Optional[float]
    runs_scored: Optional[int]


@dataclass(frozen=True)
class GameShape:
    """What happened, and when it stopped being in doubt."""

    home_team: Optional[str]
    away_team: Optional[str]
    home_score: Optional[int]
    away_score: Optional[int]
    n_plays: int
    lead_changes: int
    decided_inning: Optional[int]
    decided_half: Optional[str]
    decided_basis: str  # which series the "decided" call was read off
    wp_available: bool


@dataclass(frozen=True)
class PostMortem:
    decision_key: tuple
    system_id: str
    market_key: str
    side: str
    line: Optional[float]
    game_pk: Optional[str]
    settled: str  # win|loss|push|void
    thesis: str
    thesis_outcome: str  # from the ReviewRecord: CONFIRMED|REFUTED|UNTESTED|VARIANCE
    flow_available: bool
    shape: Optional[GameShape]
    pivot: Optional[Pivot]
    half_inning_pivot: Optional[HalfInningPivot]
    verdict: Optional[str]
    verdict_qualifier: Optional[str]
    verdict_basis: tuple  # the facts the rule fired on, in order
    limitations: tuple  # what this post-mortem could NOT determine
    signatures: tuple  # corpus-level pattern keys; never read per game


# ---------------------------------------------------------------------------
# Metric series
# ---------------------------------------------------------------------------

def _as_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _our_side_is_home(side: str) -> Optional[bool]:
    if side == "home":
        return True
    if side == "away":
        return False
    return None


def _wp_series(plays: Sequence[Mapping], side: str) -> Optional[list]:
    """`[(play, before, after, swing)]` on MLB's own win-probability series.

    MLB serves `homeTeamWinProbability` as the probability AFTER the play and
    `homeTeamWinProbabilityAdded` as that play's own delta (verified against a
    real game: 46.4 after a leadoff single with added -3.6, from an even 50.0
    start). `before` is therefore `after - added` -- read off the API's two
    numbers, never reconstructed from a model.

    Returns None when this bet does not settle on the full-game winner, or
    when the API served no probability for a play, so the caller falls back to
    the labelled proxy instead of quietly mixing sources.
    """
    is_home = _our_side_is_home(side)
    if is_home is None:
        return None
    out = []
    for play in plays:
        after_home = play.get("home_win_prob")
        added_home = play.get("home_win_prob_added")
        if after_home is None or added_home is None:
            return None
        after = after_home if is_home else 1.0 - after_home
        swing = added_home if is_home else -added_home
        out.append((play, after - swing, after, swing))
    return out or None


def _margin_series(plays: Sequence[Mapping], settlement_rule: str, side: str,
                   line) -> Optional[list]:
    """`[(play, before, after, swing)]` on the documented run-margin proxy.

    THE PROXY, STATED IN FULL. `after` is how far our selection is from
    losing, in runs, immediately after the play; positive means our side is
    currently winning the bet. It is a pure function of the score the game's
    own play-by-play records, with no model in it anywhere:

      h2h, side=home   -> home_score - away_score
      h2h, side=away   -> away_score - home_score
      h2h_1st_5        -> the same, but frozen after the 5th inning, because
                          nothing after the 5th can change how that bet settles
      totals, under L  -> L - (home_score + away_score)
      totals, over L   -> (home_score + away_score) - L

    `swing` is the change across one play: the runs that play scored, signed
    for our side. This is NOT a win probability and is never rendered as one;
    it cannot say "41% -> 78%", only "up 2 -> down 1". That is the honest
    price of the API not serving a probability for this market or this game.
    """
    total_market = settlement_rule.startswith("totals")
    if total_market and line is None:
        return None
    if not total_market and _our_side_is_home(side) is None:
        return None

    out = []
    previous = None
    for play in plays:
        home = play.get("home_score_after")
        away = play.get("away_score_after")
        if home is None or away is None:
            return None
        if settlement_rule == "h2h_1st_5" and (play.get("inning") or 0) > 5:
            value = previous if previous is not None else 0.0
        elif total_market:
            total = home + away
            value = (line - total) if side == "under" else (total - line)
        else:
            value = (home - away) if side == "home" else (away - home)
        value = float(value)
        before = previous if previous is not None else _opening_margin(
            settlement_rule, side, line)
        out.append((play, before, value, value - before))
        previous = value
    return out or None


def _opening_margin(settlement_rule: str, side: str, line) -> float:
    """The proxy's value before the first pitch: 0-0, nobody out."""
    if settlement_rule.startswith("totals"):
        return float(line) if side == "under" else -float(line)
    return 0.0


def _pivot_from(series, plays, game_row, metric, reason) -> Optional[Pivot]:
    """The play with the most negative swing. Ties break to the LATER play.

    Two plays that moved the game equally far against us are not equally
    decisive: the later one had less game left to undo it. The tie-break is
    stated here so the choice is reproducible rather than incidental to list
    order.
    """
    if not series:
        return None
    worst = None
    for index, (play, before, after, swing) in enumerate(series):
        if swing is None:
            continue
        if worst is None or swing < worst[3] or (
                swing == worst[3] and index > worst[4]):
            worst = (play, before, after, swing, index)
    if worst is None or worst[3] >= 0:
        # Nothing ever moved against this selection. Real, and worth saying
        # out loud rather than inventing a "least good" moment.
        return None
    play, before, after, swing, _ = worst
    starter_id = (game_row.get("home_starter_id") if play.get("half") == "top"
                  else game_row.get("away_starter_id"))
    return Pivot(
        metric=metric, metric_reason=reason,
        inning=play.get("inning"), half=play.get("half"),
        outs_before=play.get("outs_before"),
        bases_before=play.get("bases_before"),
        batter_name=play.get("batter_name"),
        pitcher_name=play.get("pitcher_name"),
        event=play.get("event"), description=play.get("description"),
        before=before, after=after, swing=swing,
        pitcher_was_starter=(None if starter_id is None
                             else play.get("pitcher_id") == starter_id),
    )


def _half_inning_pivot_from(series, metric) -> Optional[HalfInningPivot]:
    """The (inning, half) with the most negative TOTAL swing. Later wins ties."""
    if not series:
        return None
    order = []
    agg: dict = {}
    for play, before, after, swing in series:
        key = (play.get("inning"), play.get("half"))
        if key not in agg:
            agg[key] = {"before": before, "after": after, "swing": 0.0,
                        "runs": 0}
            order.append(key)
        agg[key]["after"] = after
        agg[key]["swing"] += (swing or 0.0)
        agg[key]["runs"] += (play.get("rbi") or 0)
    worst_key = None
    for index, key in enumerate(order):
        if worst_key is None or agg[key]["swing"] < agg[worst_key[0]]["swing"] or (
                agg[key]["swing"] == agg[worst_key[0]]["swing"]
                and index > worst_key[1]):
            worst_key = (key, index)
    if worst_key is None or agg[worst_key[0]]["swing"] >= 0:
        return None
    key = worst_key[0]
    return HalfInningPivot(
        inning=key[0], half=key[1], metric=metric,
        before=agg[key]["before"], after=agg[key]["after"],
        swing=agg[key]["swing"], runs_scored=agg[key]["runs"])


# ---------------------------------------------------------------------------
# Game shape
# ---------------------------------------------------------------------------

def _game_shape(game_row: Mapping, plays: Sequence[Mapping]) -> GameShape:
    home_final = game_row.get("home_score_final")
    away_final = game_row.get("away_score_final")

    lead_changes = 0
    previous_sign = 0
    for play in plays:
        home = play.get("home_score_after")
        away = play.get("away_score_after")
        if home is None or away is None:
            continue
        sign = (home > away) - (home < away)
        if sign != 0 and previous_sign != 0 and sign != previous_sign:
            lead_changes += 1
        if sign != 0:
            previous_sign = sign

    decided_inning = decided_half = None
    basis = "not determined"
    if home_final is not None and away_final is not None and home_final != away_final:
        winner_home = home_final > away_final
        wp_ok = all(p.get("home_win_prob") is not None for p in plays) and plays
        if wp_ok:
            basis = ("MLB win probability: the last play after which the "
                     "winner's own win probability never fell below 50% again")
            series = [(p, (p["home_win_prob"] if winner_home
                           else 1.0 - p["home_win_prob"])) for p in plays]
            threshold = 0.5
        else:
            basis = ("run margin (proxy): the last play after which the "
                     "winner's lead never returned to level or behind")
            series = []
            for p in plays:
                home = p.get("home_score_after")
                away = p.get("away_score_after")
                if home is None or away is None:
                    continue
                series.append((p, float(home - away) if winner_home
                               else float(away - home)))
            threshold = 0.0
        last_in_doubt = -1
        for index, (_, value) in enumerate(series):
            if value <= threshold:
                last_in_doubt = index
        if series and last_in_doubt + 1 < len(series):
            decisive = series[last_in_doubt + 1][0]
            decided_inning = decisive.get("inning")
            decided_half = decisive.get("half")

    return GameShape(
        home_team=game_row.get("home_team"), away_team=game_row.get("away_team"),
        home_score=home_final, away_score=away_final,
        n_plays=len(plays), lead_changes=lead_changes,
        decided_inning=decided_inning, decided_half=decided_half,
        decided_basis=basis, wp_available=bool(game_row.get("wp_available")),
    )


# ---------------------------------------------------------------------------
# THE VERDICT RULE
# ---------------------------------------------------------------------------

def classify(decision, review, game_row: Optional[Mapping],
             pivot: Optional[Pivot]) -> tuple:
    """Return `(verdict, qualifier, basis)` from a FIXED, ordered rule.

    THE RULE, IN FULL. First match wins; every branch names the field it
    fired on, so a verdict can always be traced back to a stored fact.

    R1 INFORMATION_MISSING -- something knowable-but-unknown to us decided it.
       Fires on either of two facts, both recorded, neither inferred:
         (a) the ReviewRecord carries `late_information` or
             `missed_information` -- a real InformationEvent landed after the
             decision was frozen (`settle_slate.late_information_for`).
         (b) LATE SCRATCH: the decision's `assumption_exposure` shows it was
             assuming a probable pitcher, and the pitcher who actually took
             the ball (gameflow's `home_starter_id`/`away_starter_id`, read
             off the first play of each half-inning) is not the probable the
             game record carries. We cannot have reasoned correctly about a
             starter who never pitched.
       R1 is checked FIRST on purpose: if the board we decided on was wrong,
       neither of the other two verdicts is a claim we are entitled to make.

    R2 REASONING_WRONG -- the thing the pick was built on is what failed.
       Requires the decision to have made a claim a game could contradict,
       and the game to have contradicted it:
         (a) `thesis_outcome == "REFUTED"` -- at least one recorded
             mechanism check came back refuted, or
         (b) `counterargument_realized` is non-empty -- a counterargument the
             decision itself wrote down actually happened.
       Note what is NOT here: losing. Losing is not evidence the reasoning
       was wrong; that inference is exactly the back door this module exists
       to keep shut.

    R3 VARIANCE -- everything else. The reasoning held, or made no claim, and
       the game turned on something the pick never predicted. Qualified:
         mechanism_confirmed      when checks existed and all held
         no_falsifiable_mechanism when no checkable claim was made at all
       The second qualifier is not a good result. It means the loss (or the
       win) is uninformative about the thesis, and the fix is to make theses
       record mechanism checks -- not to change any parameter.

    WHY THIS CAN HONESTLY REACH ALL THREE. R1 fires on stored events and a
    computed roster fact, R2 on stored mechanism checks, R3 on the absence of
    both. None of the three consults the outcome except to know that there
    is one to explain: the same rule run over a WON bet reaches the same
    three classes, which is what makes the win control meaningful.
    """
    basis = []
    late = tuple(getattr(review, "late_information", ()) or ())
    missed = tuple(getattr(review, "missed_information", ()) or ())
    if late:
        basis.append(f"late_information: {len(late)} event(s) after the "
                     "decision was frozen")
    if missed:
        basis.append(f"missed_information: {len(missed)} item(s)")

    scratch = _late_scratch(decision, game_row)
    if scratch:
        basis.append(scratch)

    if late or missed or scratch:
        return VERDICT_INFORMATION_MISSING, None, tuple(basis)

    outcome = getattr(review, "thesis_outcome", "UNTESTED")
    realized = tuple(getattr(review, "counterargument_realized", ()) or ())
    checks = tuple(getattr(review, "mechanism_checks", ()) or ())
    if outcome == "REFUTED":
        refuted = [c.get("name") for c in checks
                   if isinstance(c, Mapping) and c.get("verdict") == "refuted"]
        basis.append(f"mechanism check(s) refuted: {refuted or 'unnamed'}")
        return VERDICT_REASONING_WRONG, None, tuple(basis)
    if realized:
        basis.append(f"counterargument_realized: {len(realized)} of the "
                     "decision's own counterarguments happened")
        return VERDICT_REASONING_WRONG, None, tuple(basis)

    if checks:
        basis.append(f"{len(checks)} mechanism check(s) recorded, none refuted")
        qualifier = QUALIFIER_MECHANISM_CONFIRMED
    else:
        basis.append("no mechanism checks were recorded on this decision, so "
                     "no part of its thesis could be refuted by any game")
        qualifier = QUALIFIER_NO_FALSIFIABLE_MECHANISM
    if pivot is not None and pivot.pitcher_was_starter is False:
        basis.append("the pivot came off a relief pitcher, not a starter the "
                     "decision named")
    return VERDICT_VARIANCE, qualifier, tuple(basis)


def _late_scratch(decision, game_row: Optional[Mapping]) -> Optional[str]:
    """R1(b): the probable we assumed is not the pitcher who took the ball.

    Reads the probable off the GAME record (the schedule's own pre-game
    claim, stored on the gameflow game row) and the actual starter off the
    game's first play. Returns None -- never a guess -- when either is
    missing, or when the decision recorded no probable-pitcher assumption at
    all.
    """
    if not game_row:
        return None
    exposure = getattr(decision, "assumption_exposure", None) or {}
    hits = []
    for side in ("home", "away"):
        if not exposure.get(f"A:{side}_probable_id"):
            continue
        probable = game_row.get(f"{side}_probable_id")
        actual = game_row.get(f"{side}_starter_id")
        if probable is None or actual is None:
            continue
        if int(probable) != int(actual):
            hits.append(f"{side} starter was {actual}, not the probable "
                        f"{probable} the decision assumed (late scratch)")
    return "; ".join(hits) if hits else None


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _signatures(pm_verdict, qualifier, shape, pivot, market_key) -> tuple:
    """Corpus-level pattern keys. Never read for a single post-mortem."""
    out = [f"verdict:{pm_verdict}", f"market:{market_key}"]
    if qualifier:
        out.append(f"qualifier:{qualifier}")
    if pivot is not None:
        inning = pivot.inning or 0
        bucket = ("innings_1_3" if inning <= 3 else
                  "innings_4_6" if inning <= 6 else "innings_7_plus")
        out.append(f"pivot_inning:{bucket}")
        if pivot.event:
            out.append(f"pivot_event:{pivot.event}")
        if pivot.pitcher_was_starter is not None:
            out.append("pivot_pitcher:"
                       + ("starter" if pivot.pitcher_was_starter else "reliever"))
    if shape is not None and shape.decided_inning:
        out.append("decided:"
                   + ("early" if shape.decided_inning <= 5 else "late"))
    return tuple(out)


def build_postmortem(decision, review, wager: Mapping,
                     flow: Optional[Mapping],
                     *, legacy_join: bool = False) -> PostMortem:
    """One post-mortem. `flow` is `gameflow.load_game(...)` or None."""
    decision_key = tuple(review.decision_key)
    settlement_rule = wager.get("settlement_rule") or wager.get("market_key") or ""
    side = wager.get("side") or ""
    # The wager store writes `line` as whatever the book sent -- a real
    # number for some rows, the string "8.5" for others. The proxy does
    # arithmetic on it, so coerce once here and treat an uncoercible value as
    # NO line (which makes the proxy refuse, honestly) rather than crash.
    line = _as_float(wager.get("line"))

    limitations = []
    shape = pivot = half_pivot = None
    if flow is None:
        limitations.append(
            "no play-by-play in the gameflow store for this game -- run "
            "`python3 -m src.cli gameflow --date <date>`; nothing about the "
            "pivot is knowable without it")
    else:
        game_row = flow["game"]
        plays = flow["plays"]
        shape = _game_shape(game_row, plays)

        series = None
        metric = reason = None
        if settlement_rule == "h2h":
            series = _wp_series(plays, side)
            if series is not None:
                metric = PIVOT_METRIC_WIN_PROBABILITY
                reason = ("this bet settles on the full-game winner, which is "
                          "exactly what MLB's win-probability series predicts")
        if series is None:
            series = _margin_series(plays, settlement_rule, side, line)
            metric = PIVOT_METRIC_RUN_MARGIN
            if settlement_rule == "h2h":
                reason = ("PROXY: MLB served no win-probability series for "
                          "this game, so the pivot is measured on the run "
                          "margin instead")
            else:
                reason = (f"PROXY: settlement rule {settlement_rule!r} does "
                          "not settle on the full-game winner MLB's "
                          "win-probability series predicts, so the pivot is "
                          "measured on the run margin instead")
            limitations.append(
                "the pivot is measured on a run-margin PROXY, not a win "
                "probability -- it can say how many runs the game moved "
                "against this bet, never by how much the chance of winning it "
                "changed")
        if series is None:
            limitations.append(
                f"no usable metric series for settlement rule "
                f"{settlement_rule!r} side {side!r} -- no pivot computed")
        else:
            pivot = _pivot_from(series, plays, game_row, metric, reason)
            half_pivot = _half_inning_pivot_from(series, metric)
            if pivot is None:
                limitations.append(
                    "no play in this game moved the game against this "
                    "selection at all")

    verdict, qualifier, basis = classify(
        decision, review, flow["game"] if flow else None, pivot)

    if legacy_join:
        limitations.append(
            "this review carries a pre-B4 4-field decision_key (no "
            "system_id); it was joined to its wager on the four fields it "
            "does carry, uniquely -- but the decision behind it may not have "
            "been recoverable, in which case the thesis above reads '(none "
            "recorded)'")

    if qualifier == QUALIFIER_NO_FALSIFIABLE_MECHANISM:
        limitations.append(
            "this decision recorded no mechanism check, so this post-mortem "
            "cannot distinguish 'the reasoning held' from 'the reasoning was "
            "never testable' -- the VARIANCE verdict here is a statement "
            "about the thesis, not a defence of it")

    return PostMortem(
        decision_key=decision_key,
        system_id=wager.get("system_id") or "",
        market_key=wager.get("market_key") or "",
        side=side, line=line,
        game_pk=game_pk_key(wager.get("game_pk")),
        settled=review.settled,
        thesis=(getattr(decision, "thesis", "") or "") if decision else "",
        thesis_outcome=getattr(review, "thesis_outcome", "UNTESTED"),
        flow_available=flow is not None,
        shape=shape, pivot=pivot, half_inning_pivot=half_pivot,
        verdict=verdict, verdict_qualifier=qualifier, verdict_basis=basis,
        limitations=tuple(limitations),
        signatures=_signatures(verdict, qualifier, shape, pivot,
                               wager.get("market_key") or ""),
    )


def build_postmortems(decisions: Sequence, reviews: Sequence,
                      wagers: Sequence[Mapping], flow_rows: Sequence[Mapping],
                      *, outcomes=("loss", "win"),
                      date: Optional[str] = None) -> dict:
    """Post-mortems for every settled decision, losses AND the won control.

    `outcomes` defaults to both on purpose. Calling this with
    `outcomes=("loss",)` is legal (a caller may want only the losses to
    render) but `summarize` will then have no control to compare against and
    says so rather than reporting a loss-only distribution as if it meant
    something.
    """
    from src.pipeline import gameflow

    # LEGACY 4-TUPLE REVIEW KEYS. `ReviewRecord.decision_key` gained
    # `system_id` in the B4 fix (2026-09-03, see
    # `src.factory.scorecard.decision_key_for`); reviews written before it
    # carry a 4-tuple that can never equal a 5-tuple again. Those reviews
    # simply stop joining -- correct for the calibration path, which must
    # never risk pairing one system's decision with another's review, but it
    # would silently drop most of the settled history from a DESCRIPTIVE
    # artifact. Here they are joined on the 4 fields they do carry, and ONLY
    # when exactly one wager matches: an ambiguous legacy key is skipped with
    # its reason recorded, never resolved by picking one.
    wager_by_key = {}
    wager_by_legacy_key: dict = {}
    for w in wagers:
        key = (w.get("event_id"), w.get("system_id"), w.get("market_key"),
               w.get("selection_id"), w.get("decision_utc"))
        wager_by_key[key] = w
        legacy = (w.get("event_id"), w.get("market_key"),
                  w.get("selection_id"), w.get("decision_utc"))
        wager_by_legacy_key.setdefault(legacy, []).append(w)
    decision_by_key = {}
    for d in decisions:
        decision_by_key[(d.event_id, d.system_id, d.market_key, d.selection_id,
                         d.decision_utc)] = d

    flow_cache: dict = {}
    built, skipped = [], []
    for review in reviews:
        if review.settled not in outcomes:
            continue
        key = tuple(review.decision_key)
        legacy_join = False
        wager = wager_by_key.get(key)
        if wager is None and len(key) == 4:
            candidates = wager_by_legacy_key.get(key, [])
            if len(candidates) == 1:
                wager = candidates[0]
                legacy_join = True
            elif candidates:
                skipped.append({
                    "decision_key": key,
                    "reason": f"legacy 4-field decision_key matches "
                              f"{len(candidates)} wagers (systems: "
                              f"{sorted(c.get('system_id') for c in candidates)})"
                              " -- ambiguous, never resolved by guessing"})
                continue
        if wager is None:
            skipped.append({"decision_key": key,
                            "reason": "no paper wager row matches this "
                                      "review's decision_key"})
            continue
        if date is not None and wager.get("date") != date:
            continue
        game_pk = wager.get("game_pk")
        if game_pk not in flow_cache:
            flow_cache[game_pk] = gameflow.load_game(flow_rows, game_pk)
        decision = decision_by_key.get(key)
        if decision is None and legacy_join:
            decision = decision_by_key.get(
                (wager.get("event_id"), wager.get("system_id"),
                 wager.get("market_key"), wager.get("selection_id"),
                 wager.get("decision_utc")))
        built.append(build_postmortem(decision, review, wager,
                                      flow_cache[game_pk],
                                      legacy_join=legacy_join))

    built.sort(key=lambda pm: (pm.settled, pm.decision_key))
    return {"postmortems": tuple(built), "skipped": tuple(skipped)}


# ---------------------------------------------------------------------------
# Corpus: patterns, and the control
# ---------------------------------------------------------------------------

def summarize(postmortems: Sequence[PostMortem]) -> dict:
    losses = [pm for pm in postmortems if pm.settled == "loss"]
    wins = [pm for pm in postmortems if pm.settled == "win"]
    return {
        "n_losses": len(losses),
        "n_wins": len(wins),
        "loss_verdicts": dict(Counter(pm.verdict for pm in losses)),
        "win_verdicts": dict(Counter(pm.verdict for pm in wins)),
        "loss_qualifiers": dict(Counter(pm.verdict_qualifier for pm in losses
                                        if pm.verdict_qualifier)),
        "win_qualifiers": dict(Counter(pm.verdict_qualifier for pm in wins
                                       if pm.verdict_qualifier)),
        "flow_missing": sum(1 for pm in postmortems if not pm.flow_available),
        "proxy_pivots": sum(1 for pm in postmortems if pm.pivot is not None
                            and pm.pivot.metric == PIVOT_METRIC_RUN_MARGIN),
    }


def suggest_research(postmortems: Sequence[PostMortem]) -> dict:
    """Signatures over-represented among losses vs the won control.

    Returns `{"suggestions": [...], "notes": [...]}`. A signature qualifies
    only when it appears in at least MIN_PATTERN_N losses, covers at least
    MIN_PATTERN_SHARE of them, and appears at least MIN_PATTERN_LIFT times
    more often among losses than among wins. The lift term is the important
    one: a property present in half our losses and half our wins is a
    property of the games we bet, not of the bets we lost.

    Every output is a QUESTION to prespecify and test on data this
    post-mortem did not see. Nothing here is a parameter, and the
    `_REFUSED_SUGGESTION_TERMS` guard drops any sentence that drifts into
    being one.
    """
    losses = [pm for pm in postmortems if pm.settled == "loss"]
    wins = [pm for pm in postmortems if pm.settled == "win"]
    notes = []
    if len(losses) < MIN_PATTERN_N:
        notes.append(
            f"{len(losses)} loss(es) examined. One game is an anecdote and "
            f"{MIN_PATTERN_N} is this module's floor for saying the word "
            "'pattern' at all -- nothing is suggested from this sample.")
        return {"suggestions": [], "notes": notes}
    if not wins:
        notes.append(
            "no won bets were examined, so no control exists: any signature "
            "common among these losses may be equally common among the wins. "
            "Suggestions are withheld rather than published without a "
            "control.")
        return {"suggestions": [], "notes": notes}

    loss_counts = Counter(s for pm in losses for s in set(pm.signatures))
    win_counts = Counter(s for pm in wins for s in set(pm.signatures))

    suggestions = []
    for signature, count in sorted(loss_counts.items()):
        share = count / len(losses)
        win_share = win_counts.get(signature, 0) / len(wins)
        if count < MIN_PATTERN_N or share < MIN_PATTERN_SHARE:
            continue
        lift = (share / win_share) if win_share else float("inf")
        if lift < MIN_PATTERN_LIFT:
            continue
        text = (
            f"'{signature}' appears in {count}/{len(losses)} losses "
            f"({share:.0%}) against {win_share:.0%} of the won control "
            f"(lift {lift:.1f}x). QUESTION to prespecify and test on data "
            "this post-mortem has not seen: is that difference real, or is it "
            "this sample? Nothing about it justifies changing a live "
            "parameter (docs/RESEARCH_CATALOGUE.md T8).")
        if any(term in text.lower() for term in _REFUSED_SUGGESTION_TERMS):
            notes.append(
                f"a suggestion for '{signature}' was DROPPED: it read as a "
                "parameter change, which a post-mortem may never propose.")
            continue
        suggestions.append(text)

    if not suggestions:
        notes.append(
            f"No signature cleared the pattern floor (>= {MIN_PATTERN_N} "
            f"losses, >= {MIN_PATTERN_SHARE:.0%} of losses, >= "
            f"{MIN_PATTERN_LIFT:.0f}x the rate in the won control). These "
            "losses look like individual games, not a family.")
    return {"suggestions": suggestions, "notes": notes}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd"}


def _ordinal(n) -> str:
    if n is None:
        return "?"
    return _ORDINALS.get(n, f"{n}th")


def _bases_phrase(label) -> str:
    if not label or label == "empty":
        return "bases empty"
    if label == "loaded":
        return "bases loaded"
    parts = label.split("+")
    if len(parts) == 1:
        return f"runner on {parts[0]}"
    return "runners on " + " and ".join(parts)


def _outs_phrase(outs) -> str:
    if outs is None:
        return "outs unknown"
    return "1 out" if outs == 1 else f"{outs} out"


def render_pivot(pivot: Optional[Pivot]) -> str:
    if pivot is None:
        return "No play moved the game against this selection."
    half = {"top": "top", "bottom": "bottom"}.get(pivot.half, pivot.half or "?")
    where = (f"{half} {_ordinal(pivot.inning)}, {_bases_phrase(pivot.bases_before)}, "
             f"{_outs_phrase(pivot.outs_before)}")
    if pivot.metric == PIVOT_METRIC_WIN_PROBABILITY:
        movement = (f"win probability {pivot.before:.0%} -> {pivot.after:.0%} "
                    f"({pivot.swing:+.0%})")
    else:
        movement = (f"run margin (PROXY, not a probability) "
                    f"{pivot.before:+.0f} -> {pivot.after:+.0f} "
                    f"({pivot.swing:+.0f} runs)")
    what = (pivot.description or pivot.event or "").rstrip(". ")
    return f"{where}: {what}. Our side: {movement}."


def render_half_inning_pivot(half_pivot: Optional[HalfInningPivot]) -> str:
    if half_pivot is None:
        return "No half-inning moved the game against this selection."
    half = half_pivot.half or "?"
    if half_pivot.metric == PIVOT_METRIC_WIN_PROBABILITY:
        movement = (f"win probability {half_pivot.before:.0%} -> "
                    f"{half_pivot.after:.0%} ({half_pivot.swing:+.0%})")
    else:
        movement = (f"run margin (PROXY) {half_pivot.before:+.0f} -> "
                    f"{half_pivot.after:+.0f} ({half_pivot.swing:+.0f} runs)")
    return (f"Worst half-inning: {half} {_ordinal(half_pivot.inning)}, "
            f"{half_pivot.runs_scored} RBI -- {movement}.")


def render_postmortem(pm: PostMortem) -> str:
    lines = []
    label = pm.settled.upper()
    control = " (WON -- control)" if pm.settled == "win" else ""
    lines.append(f"### {label}{control}: {pm.system_id} / {pm.market_key} "
                 f"{pm.side}{'' if pm.line is None else f' {pm.line}'} "
                 f"(game {pm.game_pk})")
    lines.append("")
    lines.append(f"Thesis: {pm.thesis or '(none recorded)'}")
    lines.append("")

    lines.append("**What happened.**")
    if pm.shape is None:
        lines.append("Unknown -- no play-by-play stored for this game.")
    else:
        s = pm.shape
        score = (f"{s.away_team or 'away'} {s.away_score} at "
                 f"{s.home_team or 'home'} {s.home_score}")
        lines.append(f"{score}; {s.n_plays} plate appearances, "
                     f"{s.lead_changes} lead change(s).")
        if s.decided_inning:
            lines.append(f"Stopped being in doubt in the {s.decided_half} of the "
                         f"{_ordinal(s.decided_inning)} -- {s.decided_basis}.")
        else:
            lines.append(f"When it stopped being in doubt could not be read off "
                         f"the record ({s.decided_basis}).")
    lines.append("")

    lines.append("**The pivot.**")
    lines.append(render_pivot(pm.pivot))
    lines.append(render_half_inning_pivot(pm.half_inning_pivot))
    if pm.pivot is not None:
        lines.append(f"Metric: {pm.pivot.metric} -- {pm.pivot.metric_reason}.")
        if pm.pivot.pitcher_was_starter is not None:
            lines.append("Pitcher on the mound was the "
                         + ("starter." if pm.pivot.pitcher_was_starter
                            else "bullpen, not the starter."))
    lines.append("")

    lines.append(f"**Verdict: {pm.verdict}"
                 + (f" ({pm.verdict_qualifier})" if pm.verdict_qualifier else "")
                 + "**")
    for reason in pm.verdict_basis:
        lines.append(f"- {reason}")
    lines.append(f"- settlement's own thesis_outcome: {pm.thesis_outcome}")
    lines.append("")

    if pm.limitations:
        lines.append("**What this post-mortem could not determine.**")
        for limitation in pm.limitations:
            lines.append(f"- {limitation}")
        lines.append("")
    return "\n".join(lines)


def _degenerate_notes(summary: Mapping) -> list:
    """Say it out loud when the classifier separated nothing.

    A table where one verdict holds every loss AND every win looks like a
    finding and is the opposite of one: it means the rule had nothing to fire
    on. Left unsaid, a reader takes "52 VARIANCE losses" as evidence the
    reasoning is sound. It is evidence of no such thing, and the report has to
    be the thing that says so.
    """
    notes = []
    verdicts = set(summary["loss_verdicts"]) | set(summary["win_verdicts"])
    total = summary["n_losses"] + summary["n_wins"]
    if total and len(verdicts) <= 1:
        only = next(iter(verdicts), "n/a")
        notes.append(
            f"WARNING: every one of the {total} settled decisions examined "
            f"landed in the same class ({only}). This classifier separated "
            "NOTHING here -- do not read the column of losses as evidence "
            "about the reasoning.")
    unfalsifiable = summary["loss_qualifiers"].get(
        QUALIFIER_NO_FALSIFIABLE_MECHANISM, 0)
    if summary["n_losses"] and unfalsifiable == summary["n_losses"]:
        notes.append(
            "Every loss examined came from a decision that recorded NO "
            "mechanism check, so not one of them could have been classed "
            "REASONING_WRONG by any game. The gap this exposes is in what the "
            "systems write down at decision time, not in any parameter.")
    return notes


def render_section(postmortems: Sequence[PostMortem], *,
                   heading: str = "## Post-mortem") -> str:
    """The whole section: losses, the won control, the corpus read, patterns.

    Deterministic -- no clock, no randomness, no environment.
    """
    lines = [heading, ""]
    if not postmortems:
        lines.append("No settled decisions to examine.")
        lines.append("")
        return "\n".join(lines) + "\n"

    summary = summarize(postmortems)
    lines.append(
        f"{summary['n_losses']} loss(es) and {summary['n_wins']} won "
        "control(s) examined with the same rule.")
    lines.append("")
    lines.append("| verdict | losses | wins (control) |")
    lines.append("| --- | --- | --- |")
    for verdict in VERDICTS:
        lines.append(f"| {verdict} | {summary['loss_verdicts'].get(verdict, 0)} "
                     f"| {summary['win_verdicts'].get(verdict, 0)} |")
    lines.append("")
    lines.append(
        "Read the two columns together. A verdict class that appears at the "
        "same rate among wins as among losses is describing the games we bet, "
        "not the bets we lost.")
    lines.extend(_degenerate_notes(summary))
    if summary["proxy_pivots"]:
        lines.append(f"{summary['proxy_pivots']} pivot(s) were measured on the "
                     "run-margin PROXY, not a win probability.")
    if summary["flow_missing"]:
        lines.append(f"{summary['flow_missing']} settled decision(s) had no "
                     "play-by-play stored and could not be examined at all.")
    lines.append("")

    research = suggest_research(postmortems)
    lines.append("### What this suggests researching")
    for note in research["notes"]:
        lines.append(f"- {note}")
    for suggestion in research["suggestions"]:
        lines.append(f"- {suggestion}")
    lines.append("")
    lines.append("A post-mortem is a description of what happened, never "
                 "evidence for a strategy change (docs/RESEARCH_CATALOGUE.md "
                 "T8: no rescue by threshold change).")
    lines.append("")

    for pm in postmortems:
        lines.append(render_postmortem(pm))
    return "\n".join(lines) + "\n"
