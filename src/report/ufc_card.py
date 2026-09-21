"""The UFC card: published UFC_CARD_V1 picks and their settlement record.

WHY THIS EXISTS
---------------
Same division of labour as `src.report.nfl_card`: this module is the one
place that builds a live UFC card, publishes it through the shared
`card_ledger` (locking each bout 90 minutes before ITS OWN commence_time,
via `src/sports/mma.py`'s `lock_lead_hours`), and settles it against a
manually-entered result. `src.analysis.ufc_card` owns the selection rule
and the wording; nothing here decides which fighter is picked.

WHERE THIS DIFFERS FROM NFL/MLB
--------------------------------
UFC has no separate schedule provider (`entries_for_date` has nothing to
call) -- bouts are discovered straight from the multibook store's own rows,
the same way `src.analysis.ufc_card.select` reads them. And there is no
results API to settle against: `settle_for_date` reads
`src.pipeline.ufc_results`, the manually-entered store `ufc result` writes
to, keyed by FIGHTER NAMES rather than a provider id.

FIGHTER-CHANGE VOID, FOR FREE. `ufc_results.result_for_fight` only matches
a manual result to a bout when the two fighter names agree (in either
order) with what was published. If a fighter pair changed after a pick
locked, whoever enters the result types the fighters who actually fought --
which will not match the locked pick's names, so no result is found for
that bout, and `card_ledger.grade_pick` VOIDs it exactly as it VOIDs any
pick with no final score. No separate "did the fighters change" check is
needed; the name-matched lookup IS that check.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Iterable, Optional

from src.analysis import ufc_card as ufc_rule
from src.appstate import card_ledger
from src.pipeline import snapshots, ufc_results

RULE_ID = ufc_rule.RULE_ID
NOTICE = ("UFC_CARD_V1 is a brand-new test with no track record yet. Every "
          "pick is published before the bout and graded win, loss or void "
          "-- being tested, bet at your own risk.")


def _parse_utc(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _date_of(commence_time) -> Optional[str]:
    """The UTC calendar date a bout's commence_time falls on -- how bouts
    are grouped into "one UFC card, one date" the same way a Saturday's
    prelims-through-main-event session is sold as one event."""
    when = _parse_utc(commence_time)
    return when.date().isoformat() if when is not None else None


def _rows_for_date(rows: Iterable, date_str: str) -> list:
    return [r for r in rows if _date_of(r.get("commence_time")) == date_str]


def _empty_reason(rows_for_date: list, all_rows: list, date_str: str, now: datetime) -> str:
    """Why a UFC card has no picks -- distinguishing "nothing to look at"
    from "looked and declined", same reasoning as nfl_card._empty_reason_v2."""
    if not rows_for_date:
        return "No UFC bouts captured for this date."
    upcoming = [r for r in rows_for_date
               if (_parse_utc(r.get("commence_time")) or now) > now]
    if not upcoming:
        return "Every bout on this date has already started."
    bouts = {(r.get("home_team"), r.get("away_team")) for r in upcoming}
    thin = []
    for event_id, group in _group_by_event(upcoming).items():
        consensus = ufc_rule.bout_consensus(group)
        if consensus is None:
            thin.append(event_id)
    if len(thin) == len(bouts):
        return (f"No bout on this date has at least {ufc_rule.MIN_BOOKS} "
                "books quoting it, so nothing could be evaluated.")
    return ("No bout we could judge today had a consensus favourite better "
            "than -200 or an underdog at +100 to +150 rated 45%+ by the "
            "market -- no pick is better than a bad pick.")


def _group_by_event(rows: list) -> dict:
    out: dict = {}
    for (event_id, _book), row in ufc_rule.latest_quotes(rows).items():
        out.setdefault(event_id, []).append(row)
    return out


def _frozen_payload(date_str: str, frozen: dict) -> dict:
    picks = frozen.get("picks") or []
    lock_times = sorted({p.get("locked_at") for p in picks if p.get("locked_at")})
    frozen_at = lock_times[0] if len(lock_times) == 1 else (
        None if len(lock_times) > 1 else frozen.get("published_utc"))
    prices_as_of = lock_times[0] if lock_times else frozen.get("published_utc")
    return {
        "date": date_str,
        "sport": "mma",
        "rule": frozen.get("rule") or RULE_ID,
        "picks": picks,
        "count": len(picks),
        "reason": None,
        "experimental": True,
        "notice": NOTICE,
        "frozen": True,
        "published_utc": frozen.get("published_utc"),
        "generated_utc": frozen.get("published_utc"),
        "frozen_at": frozen_at,
        "prices_as_of": prices_as_of,
        "basis": frozen.get("basis") or ufc_rule.CARD_BASIS,
        "disclaimer": frozen.get("disclaimer") or ufc_rule.CARD_DISCLAIMER,
        "model_id": frozen.get("model_id") or ufc_rule.MODEL_ID,
        "calibrated": None,
        "calibration": None,
        "has_model": False,
    }


def card_for_date(date_str: str, *, now: Optional[datetime] = None,
                  rows: Optional[list] = None, prefer_frozen: bool = True,
                  path: Optional[str] = None,
                  hold_game_ids: Optional[Iterable] = None) -> dict:
    """The UFC card payload for one date, frozen or live."""
    if now is None:
        now = datetime.now(timezone.utc)

    if prefer_frozen:
        frozen = card_ledger.published_row(date_str, sport="mma", path=path)
        if frozen:
            return _frozen_payload(date_str, frozen)

    if rows is None:
        rows = snapshots.read_multibook(sport="mma")
    all_rows = list(rows or ())
    rows_for_date = _rows_for_date(all_rows, date_str)

    held = {str(g) for g in (hold_game_ids or ())}
    game_ids = {(r.get("home_team"), r.get("away_team")): r.get("event_id")
                for r in rows_for_date
                if r.get("event_id") and str(r.get("event_id")) not in held}
    picks = ufc_rule.select(rows_for_date, now=now, game_ids=game_ids)
    picks = [p for p in picks if str(p.get("game_id")) not in held]

    provenance = {
        "basis": ufc_rule.CARD_BASIS,
        "disclaimer": ufc_rule.CARD_DISCLAIMER,
        "model_id": ufc_rule.MODEL_ID,
        "calibrated": None,
        "calibration": None,
        "has_model": False,
    }

    base = {
        "date": date_str,
        "sport": "mma",
        "rule": RULE_ID,
        "notice": NOTICE,
        "frozen": False,
        "published_utc": None,
        "generated_utc": now.isoformat(),
        "bouts_considered": len({(r.get("home_team"), r.get("away_team"))
                                 for r in rows_for_date}),
        **provenance,
    }
    if picks:
        base.update({"picks": picks, "count": len(picks), "reason": None,
                     "experimental": True})
    else:
        base.update({"picks": [], "count": 0,
                     "reason": _empty_reason(rows_for_date, all_rows, date_str, now),
                     "experimental": True})
    return base


def card_to_publish(date_str: str, *, now: Optional[datetime] = None,
                    rows: Optional[list] = None, path: Optional[str] = None) -> dict:
    """The card a publish at `now` would write for `date_str`, carrying
    forward any already-locked bout untouched -- same lock-and-merge
    contract as `nfl_card.card_to_publish`, applied to bouts instead of
    games."""
    if now is None:
        now = datetime.now(timezone.utc)

    existing = card_ledger.published_row(date_str, sport="mma", path=path)
    held = card_ledger.locked_game_ids(existing, now=now, sport="mma")
    card = card_for_date(date_str, now=now, rows=rows, prefer_frozen=False,
                         path=path, hold_game_ids=held)
    if not held:
        return card

    carried = [p for p in (existing.get("picks") or ())
              if str(p.get("game_id")) in held]
    room = max(0, ufc_rule.MAX_PICKS - len(carried))
    fresh = [{**p, "rank": len(carried) + i + 1}
             for i, p in enumerate((card.get("picks") or [])[:room])]
    card = dict(card)
    card["picks"] = fresh + carried
    card["count"] = len(card["picks"])
    card["reason"] = None
    return card


def publish_for_date(date_str: str, *, now: Optional[datetime] = None,
                     rows: Optional[list] = None, path: Optional[str] = None) -> dict:
    """Publish one date's UFC card to the ledger. An empty card is never
    published."""
    if now is None:
        now = datetime.now(timezone.utc)

    card = card_to_publish(date_str, now=now, rows=rows, path=path)
    if not card.get("picks"):
        return {"published": False, "reason": card.get("reason")}

    return card_ledger.publish(card, now=now.isoformat(), path=path, sport="mma")


def _results_by_game_id(date_str: str, picks: list,
                        results_path=None) -> dict:
    """{game_id: {"home_score", "away_score"}} synthesized from manual
    results, so this can be graded through `card_ledger.grade_pick`'s
    existing moneyline arithmetic unchanged (winner's side scores 1, the
    other 0). A bout with no matching result -- not yet entered, OR its
    fighter pair changed since lock (see module docstring) -- is simply
    absent from this map, which `grade_pick` already treats as VOID. A
    draw/no-contest/cancelled result is also left absent, for the same
    reason: none of those settle a moneyline bet either way.
    """
    kwargs = {"path": results_path} if results_path is not None else {}
    out = {}
    for pick in picks:
        home, away = pick.get("home_team"), pick.get("away_team")
        result = ufc_results.result_for_fight(date_str, home, away, **kwargs)
        if result is None or result.get("outcome") in ufc_results.VOID_OUTCOMES:
            continue
        winner = result.get("winner")
        home_won = ufc_results.normalize_name(winner) == ufc_results.normalize_name(home)
        gid = pick.get("game_id")
        out[gid] = {"home_score": 1 if home_won else 0,
                    "away_score": 0 if home_won else 1}
    return out


def settle_for_date(date_str: str, *, now: Optional[datetime] = None,
                    path: Optional[str] = None,
                    results_path=None) -> Optional[dict]:
    """Settle one date's UFC card against manually-entered results.

    Returns None when there is nothing to settle (no published card, or
    already settled) -- same contract as `nfl_card.settle_for_date`.
    """
    published = card_ledger.published_row(date_str, sport="mma", path=path)
    if published is None:
        return None
    if card_ledger.settled_row(date_str, sport="mma", path=path) is not None:
        return None

    results_map = _results_by_game_id(
        date_str, published.get("picks") or [], results_path=results_path)

    return card_ledger.settle(
        date_str, results_map, sport="mma",
        now=now.isoformat() if now is not None else None, path=path)
