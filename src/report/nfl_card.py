"""The NFL card: published picks and their settlement record.

WHY THIS EXISTS
---------------
The card is the published opinion on a slate of games. It is read from either
the frozen ledger (historical) or from the live analysis (today). A card with
no picks is a real state -- see _empty_reason -- but nothing empty is frozen.
A frozen card is evidence and cannot be edited; a published version replaces
an older one only when the picks themselves change, never when just the
timestamp changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.analysis import nfl_card
from src.appstate import card_ledger
from src.pipeline import nfl_slate
from src.providers import odds as odds_provider


def _empty_reason(entries: Optional[list]) -> str:
    """Why the card has no picks.

    Two different facts read the same on the page if this collapses them:
    no game ever had a priced board to look at (nfl_slate found no
    moneyline quotes at all -- e.g. boards_by_matchup(sport="nfl") returned
    nothing) versus every game had a board and every candidate was refused
    by a gate (MIN_BOOKS, kickoff passed, 0.5 consensus). The first is "we
    had nothing to look at"; the second is "we looked and declined". Before
    this distinction existed, both said "No NFL game cleared the bar for
    this date" -- on 2026-09-16 that wording was traced to a join bug
    (boards_by_matchup resolving NFL team names through the MLB-only
    translator) that emptied every board, every day, since NFL entries
    existed. The page would have read as the model exercising judgment on
    2026-09-17's forward-testing debut when in fact no candidate was ever
    built to judge.
    """
    if not entries:
        return "No NFL games on this date."
    if not any(entry.get("h2h_quotes") for entry in entries):
        return ("No priced board was available for this date, so nothing "
                "could be evaluated.")
    return "No NFL game cleared the bar for this date."


def card_for_date(date_str: str, *, now: Optional[datetime] = None,
                  entries: Optional[list] = None,
                  prefer_frozen: bool = True,
                  path: Optional[str] = None) -> dict:
    """The NFL card payload for one date, frozen or live.

    A frozen card comes from the ledger (historical data). A live card is
    built from entries and the current selection rule.

    Args:
        date_str: ISO date string ("2026-09-14").
        now: Current UTC datetime (default: now).
        entries: Live entry dicts (default: lazy nfl_slate.entries_for_date).
        prefer_frozen: Return frozen card if one exists (default: True).
        path: Card ledger path (default: sport-specific path).

    Returns:
        Card payload dict with date, sport, rule, picks, count, reason,
        experimental, notice, frozen, published_utc, generated_utc, week,
        games_considered.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Try frozen first if preferred
    if prefer_frozen:
        frozen = card_ledger.published_row(date_str, sport="nfl", path=path)
        if frozen:
            picks = frozen.get("picks") or []
            return {
                "date": date_str,
                "sport": "nfl",
                "rule": "NFL_CARD_V1",
                "picks": picks,
                "count": len(picks),
                "reason": None,
                "experimental": True,
                "notice": "Experimental selections. Performance is still being evaluated.",
                "frozen": True,
                "published_utc": frozen.get("published_utc"),
                "generated_utc": frozen.get("published_utc"),  # Same as published
                "week": frozen.get("week"),
                "games_considered": frozen.get("games_on_slate"),
            }

    # Build live card from entries
    if entries is None:
        entries = nfl_slate.entries_for_date(date_str, now=now)

    # Select picks
    picks = nfl_card.select(entries, now=now)

    # Determine week and games_considered from entries
    week = None
    games_considered = len(entries)
    if entries:
        week = entries[0].get("week")

    # PROVENANCE. Same four fields src/appstate/card_ledger.py's `publish()`
    # reads off an MLB card (`basis`, `disclaimer`, `model_id`,
    # `calibrated`) -- added 2026-09-19 after every published NFL row was
    # found to carry null for all four (see src/analysis/nfl_card.py's
    # MODEL_ID/CARD_BASIS/CARD_DISCLAIMER docstring). `calibrated` is always
    # False and `calibration` always None here, honestly: NFL_CARD_V1 is a
    # market-consensus rule with no fitted probability curve, unlike MLB's
    # `strength.Calibration` -- there is nothing to calibrate and claiming
    # otherwise would be worse than the null it replaces.
    provenance = {
        "basis": nfl_card.CARD_BASIS,
        "disclaimer": nfl_card.CARD_DISCLAIMER,
        "model_id": nfl_card.MODEL_ID,
        "calibrated": False,
        "calibration": None,
    }

    if picks:
        return {
            "date": date_str,
            "sport": "nfl",
            "rule": "NFL_CARD_V1",
            "picks": picks,
            "count": len(picks),
            "reason": None,
            "experimental": True,
            "notice": "Experimental selections. Performance is still being evaluated.",
            "frozen": False,
            "published_utc": None,
            "generated_utc": now.isoformat(),
            "week": week,
            "games_considered": games_considered,
            **provenance,
        }
    else:
        return {
            "date": date_str,
            "sport": "nfl",
            "rule": "NFL_CARD_V1",
            "picks": [],
            "count": 0,
            "reason": _empty_reason(entries),
            "experimental": True,
            "notice": "Experimental selections. Performance is still being evaluated.",
            "frozen": False,
            "published_utc": None,
            "generated_utc": now.isoformat(),
            "week": week,
            "games_considered": games_considered,
            **provenance,
        }


def publish_for_date(date_str: str, *, now: Optional[datetime] = None,
                     entries: Optional[list] = None,
                     path: Optional[str] = None) -> dict:
    """Publish one date's card to the ledger.

    An empty card is never published -- nothing empty is evidence. Returns
    {"published": False, "reason": ...} when the card has no picks.

    Args:
        date_str: ISO date string ("2026-09-14").
        now: Current UTC datetime (default: now).
        entries: Live entry dicts (default: lazy nfl_slate.entries_for_date).
        path: Card ledger path (default: sport-specific path).

    Returns:
        Published row if picks exist, or {"published": False, "reason": ...}.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    card = card_for_date(date_str, now=now, entries=entries,
                         prefer_frozen=False, path=path)

    if not card.get("picks"):
        return {
            "published": False,
            "reason": card.get("reason"),
        }

    # Publish to ledger
    row = card_ledger.publish(
        card, now=now.isoformat(), path=path, sport="nfl")

    return row


def settle_for_date(date_str: str, *, now: Optional[datetime] = None,
                    results: Optional[dict] = None,
                    path: Optional[str] = None) -> dict:
    """Settle one date's card with final results.

    Args:
        date_str: ISO date string ("2026-09-14").
        now: Current UTC datetime (default: now).
        results: {game_id: {home_score, away_score, completed}, ...}
                 (default: lazy nfl_slate.results_for_date).
        path: Card ledger path (default: sport-specific path).

    Returns:
        Settled row from card_ledger.settle().
    """
    # NOTHING TO GRADE, NOTHING TO FETCH. The scores endpoint costs credits
    # (2 with daysFrom) and the daily loop runs this every morning of the
    # year; without this check it bought scores on every day no NFL card was
    # published -- most days.
    if card_ledger.published_row(date_str, sport="nfl", path=path) is None:
        return None
    if card_ledger.settled_row(date_str, sport="nfl", path=path) is not None:
        return None

    if results is None:
        results = nfl_slate.results_for_date(date_str)

    # card_ledger.settle() writes `now` verbatim as the settled_utc field of
    # a hash-chained, JSON-serialized ledger row -- it only falls back to
    # datetime.now(timezone.utc).isoformat() itself when `now` is falsy, so a
    # raw datetime object (this function's own parameter type) reaches
    # json.dumps() unconverted and raises TypeError. publish_for_date already
    # stringifies before crossing this same boundary; settle_for_date must
    # too, for every caller that passes an explicit (e.g. fake/injected)
    # clock rather than relying on the default.
    return card_ledger.settle(date_str, results, sport="nfl",
                             now=now.isoformat() if now is not None else None,
                             path=path)


def _cached_scores_fetch(*, scores=None):
    """A `fetch_results(date_str)` closure for `card_ledger.settle_recent`
    that hits the odds API's `/scores` endpoint AT MOST ONCE, however many
    stale dates a settle_recent() pass ends up checking.

    THE CREDIT RULE THIS EXISTS TO PROTECT (owner directive 2026-09-19):
    `odds.fetch_scores(sport="nfl", days_from=3)` costs 2 credits per call.
    `nfl_slate.results_for_date`'s own default fetches fresh every time it
    is called with no `scores=` -- exactly right for the old single-shot
    settle (one date, one call), exactly wrong for a 7-day retry window,
    which would otherwise re-buy the same handful of recent scores up to
    7 times a night. This closure fetches once, on the FIRST date that
    actually needs it (a fully caught-up week costs zero calls), and every
    later date in the same pass reads the cached list.

    `scores` lets a caller (tests, or a future caller with its own fetch
    already in hand) inject the normalized score list directly and skip the
    network path entirely -- when given, no API call is ever made.
    """
    cache: dict = {}

    def fetch(date_str: str) -> dict:
        if "scores" not in cache:
            if scores is not None:
                cache["scores"] = scores
            else:
                scores_raw = odds_provider.fetch_scores(sport="nfl", days_from=3)
                cache["scores"] = [odds_provider.normalize_score(s) for s in scores_raw]
        return nfl_slate.results_for_date(date_str, scores=cache["scores"])

    return fetch


def settle_recent(*, now: Optional[datetime] = None, today: Optional[str] = None,
                  path: Optional[str] = None, window_days: Optional[int] = None,
                  fetch_results=None) -> dict:
    """R-2026-09-19: what scripts/daily_loop.sh should call instead of one
    `settle_for_date(--date $YESTERDAY)` a night -- grades yesterday's NFL
    card plus any date in the last week that is still published and
    unsettled, self-healing the single-shot gap that left the 2026-09-17
    Bills pick ungraded two days after the game (see
    `src.appstate.card_ledger`'s own `settle_recent` docstring for the full
    story and why a bare "nothing to settle" is not printed by this path).

    `fetch_results` is injectable so a test (or a future caller) can supply
    canned per-date results with no network or API key required; defaults
    to `_cached_scores_fetch()`, which fetches the Odds API's NFL scores at
    most once for the whole pass regardless of how many dates it checks.

    Returns card_ledger.settle_recent's own shape:
    `{"dates_checked", "settled", "misses": [{"date","reason"}]}`.
    """
    kwargs = {}
    if window_days is not None:
        kwargs["window_days"] = window_days
    return card_ledger.settle_recent(
        sport="nfl",
        fetch_results=fetch_results or _cached_scores_fetch(),
        path=path,
        now=now.isoformat() if now is not None else None,
        today=today,
        **kwargs,
    )
