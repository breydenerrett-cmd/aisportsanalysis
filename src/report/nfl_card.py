"""The NFL card: published picks and their settlement record.

WHY THIS EXISTS
---------------
The card is the published opinion on a slate of games. It is read from either
the frozen ledger (historical) or from the live analysis (today). A card with
no picks is a real state -- see _empty_reason_v2 -- but nothing empty is frozen.
A frozen card is evidence and cannot be edited; a published version replaces
an older one only when the picks themselves change, never when just the
timestamp changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from src.analysis import nfl_card as nfl_v1_rule
from src.analysis import nfl_value
from src.appstate import card_ledger
from src.pipeline import nfl_slate, snapshots
from src.providers import odds as odds_provider

# THE LIVE RULE. NFL_CARD_V1 (src/analysis/nfl_card.py, the market favourite
# in every game) was retired 2026-09-20 on the owner's ruling after it
# published San Francisco -950; its published and settled rows stay in the
# ledger as its own record. NFL_CARD_V2 is src/analysis/nfl_value.py.
LIVE_RULE = nfl_value.RULE_ID
RETIRED_RULE = nfl_v1_rule.NFL_CARD_RULE
# Every rule id an NFL ledger row can carry, retired first. /card/record and
# /card/history take one of these as `?rule=` so the retired record stays
# reachable on its own -- never pooled with the live one.
RULES = (RETIRED_RULE, LIVE_RULE)
NOTICE = ("Every pick here is part of an ongoing test. Value means a better "
          "price than the rest of the market, not a sure thing -- bet at your "
          "own risk.")

# The note each rule's card carries ("How this card works" on the page).
# A frozen row stores its own. Every V1 row in evidence/cards_nfl_v1.jsonl
# (2026-09-17 and 2026-09-20) holds nulls for all three, so a V1 row reads
# V1's own constants instead -- never a blank note (review, 2026-09-20).
_NOTE_BY_RULE = {
    RETIRED_RULE: {"basis": nfl_v1_rule.CARD_BASIS,
                   "disclaimer": nfl_v1_rule.CARD_DISCLAIMER,
                   "model_id": nfl_v1_rule.MODEL_ID},
    LIVE_RULE: {"basis": nfl_value.CARD_BASIS,
                "disclaimer": nfl_value.CARD_DISCLAIMER,
                "model_id": nfl_value.MODEL_ID},
}


def _parse_utc(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _has_model(rule: str, picks: Iterable) -> bool:
    """Whether this card shows any probability of OUR OWN.

    THE PAGE KEYS ITS MODEL COPY ON THIS (review, 2026-09-20).
    web/js/card.js printed "Our own probabilities are running uncalibrated
    right now" on the live V2 card, because V2 sent `calibrated: False` --
    and V2 has no probability of its own to calibrate: its fair price is the
    market's consensus (`model_probability` is None on every pick). So an
    NFL payload says `has_model: False` when that is the case, and
    `calibrated` is None rather than False: "not calibrated" is a claim
    about a model, and there is none. NFL_CARD_V2 has no model by
    construction; any other rule is judged by its own picks (V1's
    team-strength check never put a probability on a published pick)."""
    if rule == LIVE_RULE:
        return False
    return any(isinstance(p.get("model_probability"), (int, float))
               and not isinstance(p.get("model_probability"), bool)
               for p in picks or ())


def _kickoff(entry: dict, rows: list) -> Optional[datetime]:
    """The entry's own kickoff, else any stored quote's for its matchup."""
    when = _parse_utc(entry.get("kickoff_utc"))
    if when is not None:
        return when
    key = (entry.get("home_team"), entry.get("away_team"))
    for row in rows:
        if (row.get("home_team"), row.get("away_team")) == key:
            when = _parse_utc(row.get("commence_time"))
            if when is not None:
                return when
    return None


def _upcoming_rows(entries: list, rows: list, now: datetime) -> list:
    """This date's quotes on games that have not kicked off -- the only
    quotes V2 ever judges (`nfl_value.value_candidates` drops the rest)."""
    names = {(e.get("home_team"), e.get("away_team")) for e in entries}
    out = []
    for row in rows:
        if (row.get("home_team"), row.get("away_team")) not in names:
            continue
        kickoff = _parse_utc(row.get("commence_time"))
        if kickoff is not None and kickoff > now:
            out.append(row)
    return out


def _priced_games(entries: list, rows: list, now: datetime) -> int:
    """How many of this date's games have at least one upcoming quote.

    UPCOMING, as the name always said (review, 2026-09-20): it used to count
    any stored row for the matchup, before or after kickoff, so a date whose
    games had all started still read as "priced" and fell through to the
    "looked and declined" sentence for a board nobody judged."""
    return len({(r.get("home_team"), r.get("away_team"))
                for r in _upcoming_rows(entries, rows, now)})


def _empty_reason_v2(entries: Optional[list], rows: list, now: datetime) -> str:
    """Why a V2 card has no picks -- a different fact, a different sentence.

    "We had nothing to look at" must never read like "we looked and
    declined". Before V1 drew that line, both said "No NFL game cleared the
    bar" -- and on 2026-09-16 that wording was traced to a join bug that had
    emptied every board, every day: the page read as judgment when no
    candidate had ever been built to judge.

    Two more of those facts added 2026-09-20/21 from review: every game on
    the date has already kicked off (V2 never judges a started game, so the
    board was never looked at), and the only prices held are too old to
    judge (`nfl_value`'s board-age rule)."""
    if not entries:
        return "No NFL games on this date."
    kickoffs = [_kickoff(e, rows) for e in entries]
    if all(k is not None and k <= now for k in kickoffs):
        return "Every game on this date has already started."
    if not _priced_games(entries, rows, now):
        if any(k is not None and k <= now for k in kickoffs):
            return ("No priced board was available for the games still to "
                    "start on this date, so nothing could be evaluated.")
        return ("No priced board was available for this date, so nothing "
                "could be evaluated.")
    # Looked up rather than imported by name: the board-age gate is
    # nfl_value's (src/analysis/nfl_value.py, `has_fresh_board`); this only
    # words its outcome.
    has_fresh_board = getattr(nfl_value, "has_fresh_board", None)
    if has_fresh_board is not None and not has_fresh_board(
            _upcoming_rows(entries, rows, now), now=now):
        minutes = int(getattr(nfl_value, "FRESH_BOARD_SECONDS", 3600) // 60)
        return (f"The newest prices we hold for this date's games are more "
                f"than {minutes} minutes old -- too old to judge, so nothing "
                "was evaluated.")
    # "we could judge": on a date where some games' boards are stale, those
    # games were never looked at (review verifier, 2026-09-21).
    return ("No NFL line we could judge today was priced better than the rest "
            "of the market by enough to publish -- no pick is better than a "
            "bad pick.")


def _one_per_game(picks: list) -> list:
    """At most one pick per game_id, the first (highest-value) kept.

    `nfl_value.select` keeps one pick per odds-API EVENT; two event ids for
    one scheduled game (a re-listed event) would map to the same game_id
    through the team-name join and reach the ledger as two bets on one
    game. Ranks are renumbered only when something was dropped."""
    seen, kept = set(), []
    for pick in picks:
        gid = str(pick.get("game_id"))
        if gid in seen:
            continue
        seen.add(gid)
        kept.append(pick)
    if len(kept) != len(picks):
        kept = [{**p, "rank": i + 1} for i, p in enumerate(kept)]
    return kept


def _frozen_payload(date_str: str, frozen: dict) -> dict:
    """A published row as the card payload the page reads.

    THE NOTE STORED WITH THE CARD TRAVELS WITH IT (review, 2026-09-20). This
    used to return the picks and dates only, so every published NFL card --
    which is the card served almost all day, with a publish every ~13
    minutes -- rendered "Note stored with this card" over two empty
    paragraphs, and V2's disclaimer ("not advice ... bet at your own risk")
    never appeared beside a published V2 pick. `frozen_at` rides too, as on
    MLB's frozen card (src/report/card.py), so the page can say when the
    card locked and warn when its prices are hours old."""
    picks = frozen.get("picks") or []
    # A frozen card keeps the rule it was published under.
    rule = frozen.get("rule") or RETIRED_RULE
    note = _NOTE_BY_RULE.get(rule, {})
    has_model = _has_model(rule, picks)
    # WHEN THE PICKS LOCKED, NOT WHEN THE ROW WAS LAST WRITTEN (review
    # verifier, 2026-09-21). An NFL Sunday card is built across several
    # publishes; its newest row's published_utc is the LAST publish, so the
    # page read "Locked at 1:29 PM PDT, before kickoff" above picks for
    # 10:00 AM games. One shared lock time is shown; several are not (the
    # page then says "Locked, before kickoff"). The stale-price warning counts
    # from the OLDEST lock -- the oldest price on the card.
    # A card with nothing locked yet keeps the row's own publish time, as
    # before.
    lock_times = sorted({p.get("locked_at") for p in picks if p.get("locked_at")})
    if not lock_times:
        frozen_at = frozen.get("published_utc")
    else:
        frozen_at = lock_times[0] if len(lock_times) == 1 else None
    prices_as_of = lock_times[0] if lock_times else frozen.get("published_utc")
    return {
        "date": date_str,
        "sport": "nfl",
        "rule": rule,
        "picks": picks,
        "count": len(picks),
        "reason": None,
        "experimental": True,
        "notice": NOTICE,
        "frozen": True,
        "published_utc": frozen.get("published_utc"),
        "generated_utc": frozen.get("published_utc"),  # Same as published
        "frozen_at": frozen_at,
        "prices_as_of": prices_as_of,
        "week": frozen.get("week"),
        "games_considered": frozen.get("games_on_slate"),
        "basis": frozen.get("basis") or note.get("basis"),
        "disclaimer": frozen.get("disclaimer") or note.get("disclaimer"),
        "model_id": frozen.get("model_id") or note.get("model_id"),
        # See `_has_model`: a card with no model of its own never says
        # whether that model is calibrated, whatever an older row stored.
        "calibrated": frozen.get("calibrated") if has_model else None,
        "calibration": frozen.get("calibration") if has_model else None,
        "has_model": has_model,
    }


def card_for_date(date_str: str, *, now: Optional[datetime] = None,
                  entries: Optional[list] = None,
                  rows: Optional[list] = None,
                  prefer_frozen: bool = True,
                  path: Optional[str] = None,
                  hold_game_ids: Optional[Iterable] = None) -> dict:
    """The NFL card payload for one date, frozen or live.

    A frozen card comes from the ledger (historical data). A live card is
    built from entries and the current selection rule.

    Args:
        date_str: ISO date string ("2026-09-14").
        now: Current UTC datetime (default: now).
        entries: Live entry dicts (default: lazy nfl_slate.entries_for_date).
        prefer_frozen: Return frozen card if one exists (default: True).
        path: Card ledger path (default: sport-specific path).
        hold_game_ids: game_ids the live read must leave alone because the
            date's card already holds their bet of record (see
            `card_to_publish`). Only a publisher passes this.

    Returns:
        Card payload dict with date, sport, rule, picks, count, reason,
        experimental, notice, frozen, published_utc, generated_utc, week,
        games_considered, basis, disclaimer, model_id, calibrated,
        calibration, has_model (and frozen_at on a frozen card).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Try frozen first if preferred
    if prefer_frozen:
        frozen = card_ledger.published_row(date_str, sport="nfl", path=path)
        if frozen:
            return _frozen_payload(date_str, frozen)

    # Build the live card. `rows` is the raw multi-book NFL store V2 prices
    # every line from. Read from disk ONLY when the caller injected nothing:
    # a test that hands in `entries` without `rows` gets an empty board, never
    # whatever happens to be in data/processed on the machine running it.
    if rows is None and entries is None:
        rows = snapshots.read_multibook(sport="nfl")
    if entries is None:
        entries = nfl_slate.entries_for_date(date_str, now=now, rows=rows)
    rows = list(rows or ())

    # Settlement keys results on the schedule's game_id; V2 joins its picks
    # to it by full team names, which both sides carry. A held game (its bet
    # of record is already locked on this date's card) is left out, so
    # `select` -- which skips a game with no id -- never spends one of its
    # MAX_PICKS slots on a game the ledger would refuse anyway.
    held = {str(g) for g in (hold_game_ids or ())}
    game_ids = {(e.get("home_team"), e.get("away_team")): e.get("game_id")
                for e in entries
                if e.get("game_id") and str(e.get("game_id")) not in held}
    picks = _one_per_game(nfl_value.select(rows, now=now, game_ids=game_ids))

    # Determine week and games_considered from entries
    week = None
    games_considered = len(entries)
    if entries:
        week = entries[0].get("week")

    # PROVENANCE. Same fields src/appstate/card_ledger.py's `publish()`
    # reads off an MLB card (`basis`, `disclaimer`, `model_id`,
    # `calibrated`, `calibration`). V2's fair price is the market's own
    # consensus, not a fitted model, so there is nothing to calibrate:
    # `calibrated` is None, not False, and `has_model` is False -- see
    # `_has_model` for the false warning False used to print (2026-09-20).
    provenance = {
        "basis": nfl_value.CARD_BASIS,
        "disclaimer": nfl_value.CARD_DISCLAIMER,
        "model_id": nfl_value.MODEL_ID,
        "calibrated": None,
        "calibration": None,
        "has_model": False,
    }

    if picks:
        return {
            "date": date_str,
            "sport": "nfl",
            "rule": LIVE_RULE,
            "picks": picks,
            "count": len(picks),
            "reason": None,
            "experimental": True,
            "notice": NOTICE,
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
            "rule": LIVE_RULE,
            "picks": [],
            "count": 0,
            "reason": _empty_reason_v2(entries, rows, now),
            "experimental": True,
            "notice": NOTICE,
            "frozen": False,
            "published_utc": None,
            "generated_utc": now.isoformat(),
            "week": week,
            "games_considered": games_considered,
            **provenance,
        }


def card_to_publish(date_str: str, *, now: Optional[datetime] = None,
                    entries: Optional[list] = None,
                    rows: Optional[list] = None,
                    path: Optional[str] = None) -> dict:
    """The card a publish at `now` would write for `date_str` -- or, with no
    picks and a `reason`, why nothing would be written.

    THE ONE WAY IN FOR EVERY NFL PUBLISHER (review, 2026-09-20). Both
    `publish_for_date` and `card publish --sport nfl` (src/cli.py, what
    scripts/capture_slot.sh runs every ~13 minutes) build through this
    function. The CLI used to build with `card_for_date` and write with
    `card_ledger.publish` itself, so the rule guard below -- then only in
    `publish_for_date`, which nothing in production calls -- never ran on the
    real publish path.

    Two rules live here, both from the review:

    1. NEVER MIX RULES INSIDE ONE DATE. `card_ledger.publish` carries locked
       picks forward from the date's previous publish; if that publish was
       made under NFL_CARD_V1, its locked favourites would be merged straight
       into a row stamped V2 and counted in V2's record. A date already
       published under another rule keeps it. (card_ledger.publish refuses
       the same merge underneath, as a floor.)

    2. ONE BET PER GAME ACROSS PUBLISHES. `nfl_value.select` keeps one pick
       per game within one run. A game whose pick on this date is already
       locked -- or locks on this very publish, because its kickoff is now
       inside the window -- is left out of the fresh read, so a later run
       whose best line on it has moved never adds a second bet beside the
       first (DET -6.5 then NYJ +7 on one game, graded PUSH and WIN).
       card_ledger's own NFL pick key (the game alone) holds the same line.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    existing = card_ledger.published_row(date_str, sport="nfl", path=path)
    existing_rule = (existing.get("rule") or RETIRED_RULE) if existing else None
    if existing and existing_rule != LIVE_RULE:
        return {
            "date": date_str, "sport": "nfl", "rule": LIVE_RULE,
            "picks": [], "count": 0, "refused": True,
            "reason": (f"{date_str} already carries a {existing_rule} card; "
                       f"{LIVE_RULE} starts on the next date without one"),
        }

    held = card_ledger.locked_game_ids(existing, now=now, sport="nfl")
    card = card_for_date(date_str, now=now, entries=entries, rows=rows,
                         prefer_frozen=False, path=path, hold_game_ids=held)
    if not held:
        return card
    # THE HELD PICKS RIDE ALONG, exactly as the ledger holds them. The ledger
    # carries them over anything anyway (a locked pick owns its game's key);
    # handing them in keeps the publish that STAMPS a newly-locked pick from
    # being skipped as "no picks" when every open game is held.
    carried = [p for p in (existing.get("picks") or ())
               if str(p.get("game_id")) in held]
    # AT MOST MAX_PICKS PER DATE, NOT PER PUBLISH (prereg rule 6; review
    # verifier, 2026-09-21). With held games no longer taking slots in the
    # fresh read, a Sunday built across kickoff windows reached 10 locked
    # picks. The fresh read only gets the room the day's locked picks leave,
    # and is ranked after them so no rank appears twice.
    room = max(0, nfl_value.MAX_PICKS - len(carried))
    fresh = [{**p, "rank": len(carried) + i + 1}
             for i, p in enumerate((card.get("picks") or [])[:room])]
    card = dict(card)
    card["picks"] = fresh + carried
    card["count"] = len(card["picks"])
    card["reason"] = None
    return card


def publish_for_date(date_str: str, *, now: Optional[datetime] = None,
                     entries: Optional[list] = None,
                     rows: Optional[list] = None,
                     path: Optional[str] = None) -> dict:
    """Publish one date's card to the ledger.

    An empty card is never published -- nothing empty is evidence. Returns
    {"published": False, "reason": ...} when the card has no picks, or when
    `card_to_publish` refuses the date (another rule's card is on it).

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

    card = card_to_publish(date_str, now=now, entries=entries, rows=rows,
                           path=path)

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
