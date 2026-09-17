"""THE RECEIPTS. Every published card, frozen before first pitch and graded.

WHY THIS IS THE PRODUCT
-----------------------
The card itself is an opinion, and opinions are cheap -- every handicapping
site on the internet has three of them a day. What almost none of them have
is a public, immutable list of every pick they ever made, including the ones
that lost, with the price and the book they quoted at the time.

That is what this file writes. A card published tonight is hashed into an
append-only chain and cannot be edited afterwards, which means the record
page cannot flatter itself and neither can we.

TWO RULES, BOTH LOAD-BEARING
----------------------------
1. FROZEN ON FIRST PUBLICATION. `publish` writes a date's card once. Calling
   it again for the same date is a no-op that returns the existing row
   rather than an updated one, because a card that could be rewritten at
   20:00 for a game that started at 19:05 is not a record of anything. The
   engine's slip has followed this rule since it existed; the card follows
   the same one for the same reason.

2. GRADED, NEVER RE-SCORED. `settle` appends a SEPARATE row carrying the
   outcome. The published row is never touched. So the file reads as a
   history of what was claimed and then what happened, in that order, and
   nothing in it can be quietly improved after the fact.

WHAT A GRADE MEANS HERE
-----------------------
A moneyline pick wins if the club wins. A run-line pick wins if the club
covers -- wins by more than the line as a favourite, or loses by less than
it (or wins) as an underdog. Both are decided from the final score in
`src.pipeline.history`, which is the same store the paper ledger settles
from, so a card and a paper wager on the same game can never disagree about
who won.

Return is at FLAT ONE-UNIT STAKES at the price that was published, which is
the only stake plan this project uses anywhere. It is not a claim that
anyone bet that amount.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict as _asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence

from src.core import odds as odds_math
from src.ledger.chain import HashChainLedger

CARD_STORE = os.path.join("evidence", "cards_v1.jsonl")
LOCK_LEAD_HOURS_DEFAULT = 4.0

KIND_PUBLISHED = "card_published"
KIND_SETTLED = "card_settled"

RESULT_WIN = "WIN"
RESULT_LOSS = "LOSS"
RESULT_PUSH = "PUSH"
RESULT_VOID = "VOID"

# The fields of a pick that are frozen. Deliberately a fixed list rather than
# "whatever the card happened to carry": a ledger whose columns drift with
# the renderer stops being comparable across dates, and the first thing
# anyone will do with this file is compare across dates.
FROZEN_FIELDS = (
    "rank", "label", "bet", "why", "market", "line", "side",
    "team", "team_name", "opponent_name", "price", "book", "books",
    "confidence", "market_probability", "model_probability",
    "model_probability_moneyline", "game_id", "game_pk", "event_id",
    "away_team", "home_team", "first_pitch_utc", "observed_utc", "model",
    # The run line offered alongside the pick. Frozen with it because it was
    # shown to the reader, and anything shown is part of what was claimed --
    # but NEVER graded: `settle` scores `market`/`line`/`price`, which are
    # the pick's own, and an alternative nobody was told to take is not a
    # bet this record gets credit or blame for.
    "alternative",
    # The knowledge grade shown beside the pick (src/analysis/grade.py):
    # how complete our read of the game was when the pick was frozen. Shown
    # to the reader, so part of what was claimed; never graded, because it
    # is not a bet.
    "knowledge",
)

# The fields of a PROP pick that are frozen. ADDED 2026-09-12, same
# reasoning as FROZEN_FIELDS above: a fixed list, not "whatever the card
# happened to carry", so the ledger's columns do not drift with the
# renderer. `position` is deliberately absent -- like a game pick's own
# `rank` vs. `position` split (see `_served_order`), `rank` is the frozen
# receipt of where a prop pick sat when IT locked, and `position` is
# recomputed at serve time by `_served_prop_order` in src/report/card.py.
PROP_FROZEN_FIELDS = (
    "kind", "rank", "label", "bet", "why", "player", "team",
    "game_pk", "event_id", "away_team", "home_team", "first_pitch_utc",
    "market", "line", "side", "probability", "market_probability",
    "breakeven", "price", "book", "books", "batting_slot", "expected_pa",
    "expected_pa_source", "observed_utc",
    # ADDED 2026-09-14 for pre-lineup props: whether a posted batting order
    # stood behind this pick when it was frozen. Shown to the reader
    # (the why-sentence says the same thing in words), so it is part of
    # what was claimed and belongs on the receipt.
    "lineup_posted",
    # ADDED 2026-09-14 (Opus checker problem 4): the sample size the why-
    # sentence's season rate was measured over. Shown to the reader in
    # words ("...in all 11 games we have for him this season"), so it too
    # is part of what was claimed.
    "season_games",
)

# The fields of a TOTAL pick that are frozen. ADDED 2026-09-14, same
# reasoning as PROP_FROZEN_FIELDS above -- a fixed list, not "whatever the
# card happened to carry". `rank` is the receipt of where it sat when IT
# locked; `position` is recomputed at serve time by
# `src/report/card.py`'s `_served_total_order`, exactly like a prop pick's
# own rank/position split.
TOTAL_FROZEN_FIELDS = (
    "rank", "label", "bet", "why", "line", "side", "price", "book", "books",
    "market_probability", "model_probability", "game_id", "game_pk",
    "event_id", "away_team", "home_team", "first_pitch_utc", "observed_utc",
)


class CardLedgerError(RuntimeError):
    pass


def _ledger(path: Optional[str] = None) -> HashChainLedger:
    return HashChainLedger(path or CARD_STORE)


def _frozen_pick(pick: Mapping) -> dict:
    row = {key: pick.get(key) for key in FROZEN_FIELDS}
    # For non-MLB sports, also preserve sport when present. game_id is
    # already in FROZEN_FIELDS so it's included if set. MLB frozen picks
    # are byte-identical: game_id is None and sport is not present.
    if pick.get("sport") is not None:
        row["sport"] = pick["sport"]
    return row


def _frozen_prop_pick(pick: Mapping) -> dict:
    return {key: pick.get(key) for key in PROP_FROZEN_FIELDS}


def _frozen_total_pick(pick: Mapping) -> dict:
    return {key: pick.get(key) for key in TOTAL_FROZEN_FIELDS}


def _shape_for_compare(picks, fields, sort_key) -> list:
    """The comparable shape of a pick list: its FROZEN fields plus `locked`
    (never `locked_at` -- see `_same_picks`), sorted so two lists holding
    the same picks in a different order still compare equal."""
    out = []
    for pick in picks or ():
        row = {key: pick.get(key) for key in fields}
        row["locked"] = bool(pick.get("locked"))
        out.append(row)
    return sorted(out, key=sort_key)


def _same_picks(left, right) -> bool:
    """Would appending `right` say anything `left` does not, about the GAME
    picks?

    Compared on the FROZEN FIELDS ONLY, deliberately. `locked_at` is a
    timestamp that moves every run, so including it would make every publish
    look like a change and write an identical row five times a day, burying
    the versions that matter under noise. `locked` itself is derived from the
    first pitch and the clock, so a pick that locked since the last run
    ALREADY differs on nothing else -- and that transition is worth a row,
    which is why `locked` is compared and `locked_at` is not.
    """
    key = lambda r: (str(r.get("game_pk")), str(r.get("market")), str(r.get("line")))
    return (_shape_for_compare(left, FROZEN_FIELDS, key)
            == _shape_for_compare(right, FROZEN_FIELDS, key))


def _same_prop_picks(left, right) -> bool:
    """`_same_picks`'s counterpart for PROP picks. game_pk alone does not
    make two prop picks the same bet -- a slate can carry several players'
    props on one game -- so the sort/identity key also carries the player
    and the market."""
    key = lambda r: (str(r.get("game_pk")), str(r.get("player")),
                     str(r.get("market")), str(r.get("line")))
    return (_shape_for_compare(left, PROP_FROZEN_FIELDS, key)
            == _shape_for_compare(right, PROP_FROZEN_FIELDS, key))


def _same_total_picks(left, right) -> bool:
    """`_same_picks`'s counterpart for TOTAL picks. game_pk alone is
    already unique (one total pick per game, like a moneyline pick), but the
    line joins it for the same reason `_pick_key` below carries `line` too:
    a republish that only moved the line is a real change worth a new row."""
    key = lambda r: (str(r.get("game_pk")), str(r.get("line")),
                     str(r.get("side")))
    return (_shape_for_compare(left, TOTAL_FROZEN_FIELDS, key)
            == _shape_for_compare(right, TOTAL_FROZEN_FIELDS, key))


# HOW LONG BEFORE ITS OWN FIRST PITCH A PICK STOPS CHANGING.
#
# Matches src/report/card.py's CARD_FREEZE_LEAD_HOURS. Inside this window the
# pick is the bet of record and nothing later can alter it; outside it, a
# later run may replace it with a better read.
LOCK_LEAD_HOURS = 4.0


def store_path(sport: Optional[str] = None) -> str:
    """The card ledger file path for a given sport.

    sport=None or "" means MLB, which uses CARD_STORE.
    Other sports resolve via src.sports.spec().

    Raises CardLedgerError if the sport is unknown.
    """
    if sport is None or sport == "":
        return CARD_STORE

    # Lazy import to avoid cycles: card_ledger imports src.sports at runtime
    try:
        from src.sports import spec as sport_spec
        try:
            s = sport_spec(sport)
            return s.card_ledger_path
        except sport_spec.UnknownSport:
            raise CardLedgerError(f"unknown sport {sport!r}")
    except (ImportError, AttributeError) as e:
        raise CardLedgerError(f"could not resolve sport {sport!r}: {e}")


def lock_lead_for(sport: Optional[str] = None) -> float:
    """The lock-lead hours for a given sport.

    sport=None or "" means MLB, which uses LOCK_LEAD_HOURS.
    Other sports resolve via src.sports.spec().

    Raises CardLedgerError if the sport is unknown.
    """
    if sport is None or sport == "":
        return LOCK_LEAD_HOURS

    # Lazy import to avoid cycles: card_ledger imports src.sports at runtime
    try:
        from src.sports import spec as sport_spec
        try:
            s = sport_spec(sport)
            return s.lock_lead_hours
        except sport_spec.UnknownSport:
            raise CardLedgerError(f"unknown sport {sport!r}")
    except (ImportError, AttributeError) as e:
        raise CardLedgerError(f"could not resolve sport {sport!r}: {e}")


def _parse_utc(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_locked(pick: Mapping, moment: datetime,
               lead_hours: float = LOCK_LEAD_HOURS) -> bool:
    """Is this pick close enough to ITS OWN first pitch to be final?

    PER PICK, NOT PER SLATE, AND THAT IS THE WHOLE POINT. The card used to
    freeze once for the whole day, measured against the day's EARLIEST game,
    so a 7:40pm pick was locked at 8:15am to protect a 12:15pm matinee. A
    scratch at 6pm could not touch it, and the recorded bet was one made
    eleven hours before the game with information nobody would bet on.

    The owner, 2026-09-11: "The last run scheduled or finished before the
    game first pitch should be recorded, not the preview or early bets. Even
    if they're rock solid... it could change within the time frame to first
    pitch."

    A pick with no readable first pitch is treated as LOCKED. That fails
    closed: the alternative is a pick that can be rewritten forever because
    its timestamp was unparseable, which is the one outcome this ledger
    exists to make impossible.
    """
    first_pitch = _parse_utc(pick.get("first_pitch_utc"))
    if first_pitch is None:
        return True
    return moment >= first_pitch - timedelta(hours=lead_hours)


def _pick_key(pick: Mapping):
    """What makes two picks the same BET on the same game.

    For non-MLB sports (when "sport" field is present), uses game_id.
    For MLB, uses game_pk. Both are stringified deliberately -- the results
    store round-trips through CSV, and the int/str mismatch has already cost
    this project two separate all-VOID incidents (see `_score`).
    """
    if pick.get("sport"):
        # Non-MLB sport: use game_id
        game_key = str(pick.get("game_id"))
    else:
        # MLB: use game_pk
        game_key = str(pick.get("game_pk"))
    return (game_key, pick.get("market"), pick.get("line"))


def _prop_pick_key(pick: Mapping):
    """What makes two picks the same PROP bet -- game_pk AND player, never
    the market or the line.

    FIXED 2026-09-14 (Opus checker problem 5, the duplicate hazard it flags
    as the same shape as problem 2). The key used to be `(game_pk, player,
    market, line)`, on the reasoning that a game_pk alone collides across
    players -- true, but the fix over-corrected: `select_props` already
    enforces ONE PICK PER PLAYER (his own highest-probability surviving
    contract, whatever the market), so two picks for the same player in the
    same game are never two different bets, they are the same bet read at
    two different times. The old key let them collide only when the market
    AND line matched exactly. A season-average pick on Devers at `batter_
    hits 0.5` that locked, followed by a lineup posting and `select_props`
    preferring his `batter_total_bases 1.5` contract instead, produced a
    FRESH key -- `_lock_and_merge` would not find it in `locked` and would
    append it beside the still-locked hits pick, same player, same game, two
    graded prop bets on one bettor's decision. `docs/PRODUCT_DOCTRINE.md`
    5.4 described the replacement as "same game and market" when the code
    keyed on market and line too; both the doctrine and the key undersold
    what "the same bet" has to mean here. `game_pk` and `player` alone is
    everything `select_props`'s own invariant already guarantees is unique.
    """
    return (str(pick.get("game_pk")), pick.get("player"))


def _total_pick_key(pick: Mapping):
    """What makes two picks the same TOTAL bet -- ONE PER GAME, game_pk
    alone.

    FIXED 2026-09-14 (Opus checker problem 2). The key used to be `(game_pk,
    line, side)`, on the reasoning that it should match `_same_total_picks`'
    own compare key (below) -- that reasoning was backwards. THIS key
    decides whether a FRESH total pick replaces or joins a LOCKED one in
    `_lock_and_merge`; `_same_total_picks` only sorts two already-built
    lists into a stable order before checking whether publishing would add
    anything. `build_total_candidates` already prices at most one total per
    game (one side, one line, per game), so "the same TOTAL bet" is "the
    same game", full stop -- exactly like a moneyline pick's own `_pick_key`
    (`(game_pk, market, line)`, where `market` never varies for a given
    row). Keyed on line and side, a board move split a locked pick from its
    own game: 'Over 8.5' locked at 19:00Z, the board moved to 9.0 and
    flipped to 'Under' by 20:00Z, and the fresh 'Under 9.0' candidate's key
    no longer matched the locked entry's -- `_lock_and_merge` carried the
    locked pick forward AND appended the new one, so one game carried two
    graded total bets on opposite sides, and `total_picks` could exceed
    `MAX_TOTAL_PICKS`. A locked pick has to block any fresh total for the
    same game, so the key is the game alone.
    """
    return (str(pick.get("game_pk")),)


def published_row(date: str, *, path: Optional[str] = None,
                   sport: Optional[str] = None) -> Optional[dict]:
    """The card of record for `date`, or None.

    THE NEWEST published row, not the first. Publish now appends a new
    version each time the picks change, carrying every already-locked pick
    forward untouched (see `publish`), so the newest row is by construction
    the full current composition: locked picks exactly as they were locked,
    open picks as of the latest read.

    It used to return the FIRST row, because a date was published once and
    never again. Nothing else in this module had to change when that did --
    which is the point of composing in `publish` rather than here.
    """
    # THE LAST MATCHING ROW IN THE CHAIN. A hash-chained append-only log
    # cannot have a row inserted into its middle -- that is the property the
    # chain exists to guarantee -- so physical order IS publication order and
    # no timestamp comparison is needed or wanted. The first version of this
    # sorted on `published_utc` with a fallback for unparseable stamps, and
    # that fallback could have selected an OLDER row than one already held.
    resolved_path = path if path is not None else store_path(sport)
    newest = None
    for row in _ledger(resolved_path).read():
        if row.get("kind") == KIND_PUBLISHED and row.get("date") == date:
            newest = row
    return newest


def published_versions(date: str, *, path: Optional[str] = None,
                       sport: Optional[str] = None) -> list:
    """Every published version for `date`, oldest first.

    The receipt is not just the final card -- it is that the card CHANGED and
    when. A reader who wants to check that we did not quietly improve a pick
    after the fact reads this.
    """
    resolved_path = path if path is not None else store_path(sport)
    return [row for row in _ledger(resolved_path).read()
            if row.get("kind") == KIND_PUBLISHED and row.get("date") == date]


def settled_row(date: str, *, path: Optional[str] = None,
                sport: Optional[str] = None) -> Optional[dict]:
    resolved_path = path if path is not None else store_path(sport)
    for row in _ledger(resolved_path).read():
        if row.get("kind") == KIND_SETTLED and row.get("date") == date:
            return row
    return None


def _lock_and_merge(prior, fresh_source, *, moment, lock_lead_hours, key_fn, frozen_fn):
    """One publish's worth of lock-and-carry-forward, generic over game
    picks and prop picks alike -- ADDED 2026-09-12 by pulling the logic
    `publish` already used for game picks out from under it, rather than
    writing a second copy for props that could quietly drift from the
    first. `key_fn` is `_pick_key` or `_prop_pick_key`; `frozen_fn` is
    `_frozen_pick` or `_frozen_prop_pick`.
    """
    locked: dict = {}
    for pick in prior:
        if pick.get("locked"):
            locked[key_fn(pick)] = pick
        elif _is_locked(pick, moment, lock_lead_hours):
            # It was provisional when written and its game has since come
            # within the window. This run is the one that locks it, and it
            # locks the pick AS LAST PUBLISHED -- the reader saw that bet at
            # that price, and the lock records what was shown, not a fresh
            # read taken after the window closed.
            stamped = dict(pick)
            stamped["locked"] = True
            stamped["locked_at"] = moment.isoformat()
            locked[key_fn(pick)] = stamped

    merged = []
    seen = set()
    for pick in fresh_source:
        key = key_fn(pick)
        seen.add(key)
        if key in locked:
            merged.append(locked[key])
            continue
        fresh = frozen_fn(pick)
        if _is_locked(pick, moment, lock_lead_hours):
            fresh["locked"] = True
            fresh["locked_at"] = moment.isoformat()
        else:
            fresh["locked"] = False
            fresh["locked_at"] = None
        merged.append(fresh)

    # A locked pick this run no longer makes is still a bet of record.
    for key, pick in locked.items():
        if key not in seen:
            merged.append(pick)
    return merged


def publish(card: Mapping, *, now: Optional[str] = None,
            path: Optional[str] = None,
            lock_lead_hours: Optional[float] = None,
            sport: Optional[str] = None) -> dict:
    """Publish one date's card. A pick locks at ITS OWN game's first pitch.

    WHAT CHANGED ON 2026-09-11, AND WHY
    -------------------------------------
    This used to be idempotent per DATE: the first publish won and every
    later run was a no-op. Combined with src/report/card.py's freeze gate --
    which opens four hours before the day's EARLIEST game -- that meant the
    whole card was fixed once, in the morning, to protect a matinee. A 7:40pm
    pick was locked at 8:15am. A scratch at 6pm could not touch it, and what
    went on the record was a bet made eleven hours early on information
    nobody would bet on.

    The owner: "The last run scheduled or finished before the game first
    pitch should be recorded, not the preview or early bets."

    So publish now runs several times a day and composes:

      * a pick within `lock_lead_hours` of its own first pitch is LOCKED and
        is carried forward VERBATIM from the version that locked it -- no
        later run can alter it, and `locked_at` records when it happened;
      * a pick whose game is further out is provisional and is replaced by
        this run's read;
      * a locked pick whose game this run no longer picks is still carried
        forward. Dropping it would erase a bet of record.

    NOTHING IS EVER REWRITTEN. Each call appends a new row, so the ledger
    reads as the full history of what was claimed and when, and a reader can
    check for themselves that no pick improved after its game began --
    `published_versions` returns the lot. The receipt was never "we only said
    it once"; it is "we wrote down what we said, when we said it, and you can
    see every version."

    Returns the row. `already_published` is True when this run changed
    nothing and no row was appended -- it is not part of the hashed payload.
    """
    resolved_path = path if path is not None else store_path(sport)
    resolved_lock_lead = lock_lead_hours if lock_lead_hours is not None else lock_lead_for(sport)

    date = card.get("date")
    if not date:
        raise CardLedgerError("a card with no date cannot be published")
    picks = card.get("picks") or []
    if not picks:
        raise CardLedgerError(
            f"the card for {date} has no picks; there is nothing to freeze. "
            "An empty card is a real state -- see src/report/card.py's "
            "_empty_reason -- but it is not evidence and is not recorded.")
    # A card with NO PROP picks, or no TOTAL picks, is a real state (a thin
    # prop board, or a totals board where nothing agreed and cleared its
    # price) -- not an error, unlike an empty `picks`, which refuses above.
    # Neither `select_props` nor `select_totals` has a floor to fail, so
    # nothing here should either.
    prop_picks_in = card.get("prop_picks") or []
    total_picks_in = card.get("total_picks") or []

    moment = _parse_utc(now) or datetime.now(timezone.utc)
    previous = published_row(date, path=resolved_path)
    prior_picks = list((previous or {}).get("picks") or ())
    prior_prop_picks = list((previous or {}).get("prop_picks") or ())
    prior_total_picks = list((previous or {}).get("total_picks") or ())

    merged = _lock_and_merge(prior_picks, picks, moment=moment,
                             lock_lead_hours=resolved_lock_lead,
                             key_fn=_pick_key, frozen_fn=_frozen_pick)
    merged_props = _lock_and_merge(prior_prop_picks, prop_picks_in, moment=moment,
                                   lock_lead_hours=resolved_lock_lead,
                                   key_fn=_prop_pick_key, frozen_fn=_frozen_prop_pick)
    merged_totals = _lock_and_merge(prior_total_picks, total_picks_in, moment=moment,
                                    lock_lead_hours=resolved_lock_lead,
                                    key_fn=_total_pick_key, frozen_fn=_frozen_total_pick)

    # NOTHING CHANGED, NOTHING APPENDED. Publishing five times a day would
    # otherwise write five identical rows and bury the versions that matter.
    # All three halves have to agree nothing changed -- a slate whose
    # moneyline picks are stable but whose totals board just moved a line
    # is a real change and still earns a new row.
    if (previous is not None and _same_picks(prior_picks, merged)
            and _same_prop_picks(prior_prop_picks, merged_props)
            and _same_total_picks(prior_total_picks, merged_totals)):
        out = dict(previous)
        out["already_published"] = True
        return out

    picks = merged
    prop_picks = merged_props
    total_picks = merged_totals
    payload = {
        "kind": KIND_PUBLISHED,
        "date": date,
        "published_utc": now or datetime.now(timezone.utc).isoformat(),
        "rule": card.get("rule"),
        "basis": card.get("basis"),
        "disclaimer": card.get("disclaimer"),
        "model_id": card.get("model_id"),
        "calibrated": card.get("calibrated"),
        "calibration": card.get("calibration"),
        "n_picks": len(picks),
        "n_filled": card.get("filled"),
        "games_on_slate": card.get("games_on_slate"),
        # ALREADY FROZEN-SHAPED. Re-running `_frozen_pick` here would strip
        # `locked`/`locked_at` straight back off, because they are not in
        # FROZEN_FIELDS -- every pick would land unlocked and a later run
        # could rewrite a bet whose game had already started.
        "picks": picks,
        "n_locked": sum(1 for p in picks if p.get("locked")),
        # PROP PICKS, carried the same way -- see `_lock_and_merge`.
        "prop_picks": prop_picks,
        "n_prop_picks": len(prop_picks),
        "n_prop_locked": sum(1 for p in prop_picks if p.get("locked")),
        # TOTAL PICKS, carried the same way -- ADDED 2026-09-14.
        "total_picks": total_picks,
        "n_total_picks": len(total_picks),
        "n_total_locked": sum(1 for p in total_picks if p.get("locked")),
        # WHETHER TOTALS WERE SWITCHED OFF when this version was built
        # (2026-09-14, owner-approved wording fix). Without it an empty
        # `total_picks` read back as "no total cleared its price" -- a claim
        # that totals were checked -- while they were paused and never
        # evaluated. Recorded on the row because the switch can change later
        # and a frozen card must keep describing the day it was frozen.
        "totals_paused": bool(card.get("totals_paused")),
    }
    row = _ledger(resolved_path).append(payload)
    out = dict(row)
    out["already_published"] = False
    return out


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def _score(value) -> Optional[int]:
    """A final score as an int, or None. NEVER an isinstance check.

    THE RESULTS STORE KEEPS SCORES AS STRINGS. `history.read_results()`
    round-trips through CSV, so a 7-9 game arrives as `("7", "9")`. An
    `isinstance(value, int)` guard here rejected all 2,153 stored games and
    would have graded every pick on every card VOID -- and a card settling
    0-0 with three voids does not read as a bug, it reads as a postponed
    slate. The public record would simply have stopped recording, quietly,
    forever.

    Found 2026-09-10 by a research probe that used the same isinstance guard
    and reported "only 0 finished games". The same trap, twice, in one day:
    see also the int/str game_pk join in src/cli.py's `card settle`.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def grade_pick(pick: Mapping, result: Mapping) -> dict:
    """One frozen pick against one final score.

    `result` is a `src.pipeline.history` row: `away_score`, `home_score`,
    `home_won`. A game with no final score grades VOID, never LOSS -- an
    ungraded pick counted as a loss would make a postponed slate look like a
    bad night, which is the single easiest way for a public record to become
    quietly wrong in the flattering direction's opposite.
    """
    away = _score(result.get("away_score"))
    home = _score(result.get("home_score"))
    if away is None or home is None:
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": "no final score stored for this game"}

    side = pick.get("side")
    if side not in ("away", "home"):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"unknown side {side!r} on a frozen pick"}

    margin = home - away  # home minus away, everywhere in this repo
    market = pick.get("market")

    if market == "run_line":
        line = pick.get("line")
        if not isinstance(line, (int, float)):
            return {"result": RESULT_VOID, "profit_units": 0.0,
                    "reason": "run-line pick carries no line"}
        # `line` is signed from the PICKED side's point of view: +1.5 means
        # this side is getting the runs, -1.5 means giving them.
        own_margin = margin if side == "home" else -margin
        adjusted = own_margin + float(line)
        if abs(adjusted) < 1e-9:
            return {"result": RESULT_PUSH, "profit_units": 0.0,
                    "reason": "the run line landed exactly on the margin"}
        won = adjusted > 0
    else:
        won = (margin > 0) if side == "home" else (margin < 0)

    price = pick.get("price")
    try:
        profit = (odds_math.american_to_decimal(price) - 1.0) if won else -1.0
    except (odds_math.OddsError, TypeError, ValueError):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"unusable published price {price!r}"}

    return {
        "result": RESULT_WIN if won else RESULT_LOSS,
        "profit_units": round(profit, 4),
        "away_score": away,
        "home_score": home,
        "margin": margin,
    }


def _index_prop_box_rows(rows: Optional[Sequence]) -> dict:
    """{(str(game_pk), player_name): batter box row} for prop grading.

    Keyed by NAME, not player_id -- the prop feed carries no player id (see
    src/report/props.py's module docstring), so grading has to join a
    player to his game the same way pricing did. `game_pk` is stringified
    for the same reason `_pick_key` and `_score` are: the box store and the
    frozen pick can disagree on int vs. str, and this project has already
    shipped that exact bug twice (see `_score`'s docstring).
    """
    out: dict = {}
    for row in rows or ():
        if row.get("type") != "batter":
            continue
        key = (str(row.get("game_pk")), row.get("player_name"))
        out[key] = row
    return out


def grade_prop_pick(pick: Mapping, box_by_game_and_player: Mapping) -> dict:
    """One frozen prop pick against one date's batter box rows.

    Delegates the actual over/under/push arithmetic to
    `src.board.settle_props.settle` -- the same settlement rule a backtest
    would use for the same market -- rather than re-deriving it here. A
    batter with no box row for this game (didn't play, game postponed) grades
    VOID, never LOSS, for the same reason `grade_pick` refuses to guess a
    missing final score.
    """
    from src.board import settle_props

    market = pick.get("market")
    stat = settle_props.PROP_STAT_RULES.get(market)
    if stat is None:
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"no settlement rule for market {market!r}"}

    line = pick.get("line")
    if not isinstance(line, (int, float)):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": "prop pick carries no line"}

    side_word = str(pick.get("side") or "").strip().lower()
    if side_word not in ("over", "under"):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"unknown side {pick.get('side')!r} on a frozen prop pick"}

    row = box_by_game_and_player.get(
        (str(pick.get("game_pk")), pick.get("player")))
    try:
        outcome = settle_props.settle(
            row, {"subject_id": None, "stat": stat,
                  "line": f"{float(line):g}", "side": side_word})
    except settle_props.SettleError as exc:
        return {"result": RESULT_VOID, "profit_units": 0.0, "reason": str(exc)}

    if outcome == "void":
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": "no box score found for this player in this game"}
    if outcome == "push":
        return {"result": RESULT_PUSH, "profit_units": 0.0}

    won = outcome == "win"
    price = pick.get("price")
    try:
        profit = (odds_math.american_to_decimal(price) - 1.0) if won else -1.0
    except (odds_math.OddsError, TypeError, ValueError):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"unusable published price {price!r}"}

    return {"result": RESULT_WIN if won else RESULT_LOSS,
            "profit_units": round(profit, 4)}


def grade_total_pick(pick: Mapping, result: Mapping) -> dict:
    """One frozen total pick against one final score.

    Same shape as `grade_pick`: `result` carries `away_score`/`home_score`
    from the same `src.pipeline.history` row, and a missing score grades
    VOID rather than a guessed LOSS, for the same reason. Over/under/push
    reads exactly `src.board.settle._settle_totals`'s arithmetic -- not
    called directly (that function wants a `GameResult`, this a frozen
    pick), but the same three comparisons: total runs above the line wins
    Over, below wins Under, exactly on it pushes.
    """
    away = _score(result.get("away_score"))
    home = _score(result.get("home_score"))
    if away is None or home is None:
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": "no final score stored for this game"}

    line = pick.get("line")
    if not isinstance(line, (int, float)):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": "total pick carries no line"}

    side = pick.get("side")
    if side not in ("over", "under"):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"unknown side {side!r} on a frozen total pick"}

    total_runs = away + home
    if abs(total_runs - float(line)) < 1e-9:
        return {"result": RESULT_PUSH, "profit_units": 0.0,
                "reason": "the total landed exactly on the line"}
    won = (total_runs > line) if side == "over" else (total_runs < line)

    price = pick.get("price")
    try:
        profit = (odds_math.american_to_decimal(price) - 1.0) if won else -1.0
    except (odds_math.OddsError, TypeError, ValueError):
        return {"result": RESULT_VOID, "profit_units": 0.0,
                "reason": f"unusable published price {price!r}"}

    return {
        "result": RESULT_WIN if won else RESULT_LOSS,
        "profit_units": round(profit, 4),
        "away_score": away,
        "home_score": home,
        "total_runs": total_runs,
    }


def settle(date: str, results_by_game_pk: Mapping, *,
           prop_box_rows: Optional[Sequence] = None,
           now: Optional[str] = None, path: Optional[str] = None,
           sport: Optional[str] = None, results_by_game_id: Optional[Mapping] = None) -> Optional[dict]:
    """Grade one published card and append the outcome as a NEW row.

    `prop_box_rows` is this date's batter box-score rows (the same shape
    `src.pipeline.boxscores.read` yields), used to grade the card's prop
    picks alongside the game picks -- see `grade_prop_pick`. Omitted or
    empty, every prop pick grades VOID rather than guessing, exactly like a
    game pick with no final score in `results_by_game_pk`.

    `results_by_game_id` is an alias for `results_by_game_pk` for non-MLB sports
    where game_id is used instead of game_pk.

    Returns None when there is nothing to do -- no card for that date, or it
    is already settled. Never edits the published row.
    """
    resolved_path = path if path is not None else store_path(sport)

    # Support results_by_game_id as an alias
    results_map = results_by_game_id if results_by_game_id is not None else results_by_game_pk

    published = published_row(date, path=resolved_path)
    if published is None:
        return None
    if settled_row(date, path=resolved_path) is not None:
        return None

    graded, staked, profit = [], 0, 0.0
    for pick in published.get("picks") or ():
        # For result lookup, use game_id only for non-MLB (when "sport" is present).
        # For MLB, always use game_pk (even if game_id is in FROZEN_FIELDS).
        if pick.get("sport"):
            lookup_key = pick.get("game_id")
        else:
            lookup_key = pick.get("game_pk")
        result = (results_map.get(lookup_key)
                  or results_map.get(str(lookup_key))
                  or {})
        grade = grade_pick(pick, result)
        graded_pick = {"rank": pick.get("rank"), "bet": pick.get("bet"),
                       "label": pick.get("label"), "market": pick.get("market"),
                       "price": pick.get("price"), "game_pk": pick.get("game_pk"), **grade}
        # For non-MLB sports, preserve game_id and sport
        if "game_id" in pick:
            graded_pick["game_id"] = pick["game_id"]
        if "sport" in pick:
            graded_pick["sport"] = pick["sport"]
        graded.append(graded_pick)
        if grade["result"] in (RESULT_WIN, RESULT_LOSS):
            staked += 1
            profit += grade["profit_units"]

    wins = sum(1 for g in graded if g["result"] == RESULT_WIN)
    losses = sum(1 for g in graded if g["result"] == RESULT_LOSS)

    box_by_game_and_player = _index_prop_box_rows(prop_box_rows)
    prop_graded, prop_staked, prop_profit = [], 0, 0.0
    for pick in published.get("prop_picks") or ():
        grade = grade_prop_pick(pick, box_by_game_and_player)
        prop_graded_pick = {
            "rank": pick.get("rank"), "bet": pick.get("bet"),
            "label": pick.get("label"), "player": pick.get("player"),
            "market": pick.get("market"), "line": pick.get("line"),
            "side": pick.get("side"), "price": pick.get("price"),
            "game_pk": pick.get("game_pk"), **grade}
        # For non-MLB sports, preserve game_id and sport
        if "game_id" in pick:
            prop_graded_pick["game_id"] = pick["game_id"]
        if "sport" in pick:
            prop_graded_pick["sport"] = pick["sport"]
        prop_graded.append(prop_graded_pick)
        if grade["result"] in (RESULT_WIN, RESULT_LOSS):
            prop_staked += 1
            prop_profit += grade["profit_units"]

    prop_wins = sum(1 for g in prop_graded if g["result"] == RESULT_WIN)
    prop_losses = sum(1 for g in prop_graded if g["result"] == RESULT_LOSS)

    # TOTAL PICKS, graded from the SAME results map the game picks above
    # use -- a total is graded off the same final score, so there is no
    # second results argument to thread through.
    total_graded, total_staked, total_profit = [], 0, 0.0
    for pick in published.get("total_picks") or ():
        # For result lookup, use game_id only for non-MLB (when "sport" is present).
        # For MLB, always use game_pk (even if game_id is in FROZEN_FIELDS).
        if pick.get("sport"):
            lookup_key = pick.get("game_id")
        else:
            lookup_key = pick.get("game_pk")
        result = (results_map.get(lookup_key)
                  or results_map.get(str(lookup_key))
                  or {})
        grade = grade_total_pick(pick, result)
        total_graded_pick = {
            "rank": pick.get("rank"), "bet": pick.get("bet"),
            "label": pick.get("label"), "line": pick.get("line"),
            "side": pick.get("side"), "price": pick.get("price"),
            "game_pk": pick.get("game_pk"), **grade}
        # For non-MLB sports, preserve game_id and sport
        if "game_id" in pick:
            total_graded_pick["game_id"] = pick["game_id"]
        if "sport" in pick:
            total_graded_pick["sport"] = pick["sport"]
        total_graded.append(total_graded_pick)
        if grade["result"] in (RESULT_WIN, RESULT_LOSS):
            total_staked += 1
            total_profit += grade["profit_units"]

    total_wins = sum(1 for g in total_graded if g["result"] == RESULT_WIN)
    total_losses = sum(1 for g in total_graded if g["result"] == RESULT_LOSS)

    payload = {
        "kind": KIND_SETTLED,
        "date": date,
        "settled_utc": now or datetime.now(timezone.utc).isoformat(),
        "published_row_hash": published.get("row_hash"),
        "n_picks": len(graded),
        "n_staked": staked,
        "wins": wins,
        "losses": losses,
        "pushes": sum(1 for g in graded if g["result"] == RESULT_PUSH),
        "voids": sum(1 for g in graded if g["result"] == RESULT_VOID),
        "profit_units": round(profit, 4),
        "roi_pct": round(profit / staked * 100.0, 3) if staked else None,
        "picks": graded,
        # PROP PICKS, graded and totalled the same way, flat one-unit stakes
        # -- kept under their own keys rather than pooled into the numbers
        # above so a game pick's win rate is never diluted by a prop pick's,
        # or the reverse (see `record`'s `by_kind`).
        "prop_picks": prop_graded,
        "n_prop_picks": len(prop_graded),
        "n_prop_staked": prop_staked,
        "prop_wins": prop_wins,
        "prop_losses": prop_losses,
        "prop_pushes": sum(1 for g in prop_graded if g["result"] == RESULT_PUSH),
        "prop_voids": sum(1 for g in prop_graded if g["result"] == RESULT_VOID),
        "prop_profit_units": round(prop_profit, 4),
        "prop_roi_pct": (round(prop_profit / prop_staked * 100.0, 3)
                         if prop_staked else None),
        # TOTAL PICKS, graded and totalled the same way, under their own
        # keys for the same reason the prop keys above are separate --
        # ADDED 2026-09-14.
        "total_picks": total_graded,
        "n_total_picks": len(total_graded),
        "n_total_staked": total_staked,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "total_pushes": sum(1 for g in total_graded if g["result"] == RESULT_PUSH),
        "total_voids": sum(1 for g in total_graded if g["result"] == RESULT_VOID),
        "total_profit_units": round(total_profit, 4),
        "total_roi_pct": (round(total_profit / total_staked * 100.0, 3)
                          if total_staked else None),
    }
    return _ledger(resolved_path).append(payload)


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------

def record(*, path: Optional[str] = None, since: Optional[str] = None,
           sport: Optional[str] = None) -> dict:
    """The running record: every settled card, pooled.

    Pooled is CORRECT here and is not the pooling mistake this repo warns
    about elsewhere. The card is one system with one rule, so its picks are
    one population; the warning applies to pooling DIFFERENT systems, where
    a control and a forward test get averaged into a number describing
    neither.

    VOIDS ARE COUNTED AND REPORTED, never dropped. A record that silently
    omits postponed games is a record with a hole in it that nobody can see.
    """
    resolved_path = path if path is not None else store_path(sport)

    days, wins, losses, pushes, voids, staked = 0, 0, 0, 0, 0, 0
    profit = 0.0
    by_label = {}
    prop_wins = prop_losses = prop_pushes = prop_voids = prop_staked = 0
    prop_profit = 0.0
    prop_by_label = {}
    total_wins = total_losses = total_pushes = total_voids = total_staked = 0
    total_profit = 0.0
    total_by_label = {}
    for row in _ledger(resolved_path).read():
        if row.get("kind") != KIND_SETTLED:
            continue
        if since and (row.get("date") or "") < since:
            continue
        days += 1
        wins += row.get("wins") or 0
        losses += row.get("losses") or 0
        pushes += row.get("pushes") or 0
        voids += row.get("voids") or 0
        staked += row.get("n_staked") or 0
        profit += row.get("profit_units") or 0.0
        for pick in row.get("picks") or ():
            label = pick.get("label") or "UNLABELLED"
            slot = by_label.setdefault(
                label, {"wins": 0, "losses": 0, "staked": 0, "profit_units": 0.0})
            if pick.get("result") == RESULT_WIN:
                slot["wins"] += 1
            elif pick.get("result") == RESULT_LOSS:
                slot["losses"] += 1
            if pick.get("result") in (RESULT_WIN, RESULT_LOSS):
                slot["staked"] += 1
                slot["profit_units"] += pick.get("profit_units") or 0.0

        # PROP PICKS, pooled the same way but never into the same totals --
        # see `by_kind` below. An old settled row with no prop keys at all
        # contributes zero here, exactly like a row with no prop picks.
        prop_wins += row.get("prop_wins") or 0
        prop_losses += row.get("prop_losses") or 0
        prop_pushes += row.get("prop_pushes") or 0
        prop_voids += row.get("prop_voids") or 0
        prop_staked += row.get("n_prop_staked") or 0
        prop_profit += row.get("prop_profit_units") or 0.0
        for pick in row.get("prop_picks") or ():
            label = pick.get("label") or "UNLABELLED"
            slot = prop_by_label.setdefault(
                label, {"wins": 0, "losses": 0, "staked": 0, "profit_units": 0.0})
            if pick.get("result") == RESULT_WIN:
                slot["wins"] += 1
            elif pick.get("result") == RESULT_LOSS:
                slot["losses"] += 1
            if pick.get("result") in (RESULT_WIN, RESULT_LOSS):
                slot["staked"] += 1
                slot["profit_units"] += pick.get("profit_units") or 0.0

        # TOTAL PICKS, pooled the same way but never into the same totals --
        # ADDED 2026-09-14, same reasoning as the prop pooling just above.
        total_wins += row.get("total_wins") or 0
        total_losses += row.get("total_losses") or 0
        total_pushes += row.get("total_pushes") or 0
        total_voids += row.get("total_voids") or 0
        total_staked += row.get("n_total_staked") or 0
        total_profit += row.get("total_profit_units") or 0.0
        for pick in row.get("total_picks") or ():
            label = pick.get("label") or "UNLABELLED"
            slot = total_by_label.setdefault(
                label, {"wins": 0, "losses": 0, "staked": 0, "profit_units": 0.0})
            if pick.get("result") == RESULT_WIN:
                slot["wins"] += 1
            elif pick.get("result") == RESULT_LOSS:
                slot["losses"] += 1
            if pick.get("result") in (RESULT_WIN, RESULT_LOSS):
                slot["staked"] += 1
                slot["profit_units"] += pick.get("profit_units") or 0.0

    for slot in by_label.values():
        slot["profit_units"] = round(slot["profit_units"], 4)
        slot["win_rate"] = (round(slot["wins"] / slot["staked"], 4)
                            if slot["staked"] else None)
    for slot in prop_by_label.values():
        slot["profit_units"] = round(slot["profit_units"], 4)
        slot["win_rate"] = (round(slot["wins"] / slot["staked"], 4)
                            if slot["staked"] else None)
    for slot in total_by_label.values():
        slot["profit_units"] = round(slot["profit_units"], 4)
        slot["win_rate"] = (round(slot["wins"] / slot["staked"], 4)
                            if slot["staked"] else None)

    game_summary = {
        "days": days,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "voids": voids,
        "n_staked": staked,
        "win_rate": round(wins / staked, 4) if staked else None,
        "profit_units": round(profit, 4),
        "roi_pct": round(profit / staked * 100.0, 3) if staked else None,
        "by_label": by_label,
    }
    prop_summary = {
        "days": days,
        "wins": prop_wins,
        "losses": prop_losses,
        "pushes": prop_pushes,
        "voids": prop_voids,
        "n_staked": prop_staked,
        "win_rate": round(prop_wins / prop_staked, 4) if prop_staked else None,
        "profit_units": round(prop_profit, 4),
        "roi_pct": (round(prop_profit / prop_staked * 100.0, 3)
                    if prop_staked else None),
        "by_label": prop_by_label,
    }
    total_summary = {
        "days": days,
        "wins": total_wins,
        "losses": total_losses,
        "pushes": total_pushes,
        "voids": total_voids,
        "n_staked": total_staked,
        "win_rate": round(total_wins / total_staked, 4) if total_staked else None,
        "profit_units": round(total_profit, 4),
        "roi_pct": (round(total_profit / total_staked * 100.0, 3)
                    if total_staked else None),
        "by_label": total_by_label,
    }

    return {
        # TOP-LEVEL FIELDS UNCHANGED. Every existing reader of `record()`
        # (the /card/record route, the dashboard) keeps reading the pooled
        # GAME totals exactly where it always has -- `by_kind` is additive,
        # ADDED 2026-09-12 (props) and 2026-09-14 (totals), so every
        # population can also be read apart.
        "days": days,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "voids": voids,
        "n_staked": staked,
        "win_rate": game_summary["win_rate"],
        "profit_units": game_summary["profit_units"],
        "roi_pct": game_summary["roi_pct"],
        "by_label": by_label,
        "since": since,
        "by_kind": {"game": game_summary, "prop": prop_summary,
                    "total": total_summary},
    }


def _frozen_for_graded(graded: Mapping, frozen_picks: Sequence) -> Mapping:
    """The published pick a graded game pick came from -- by game_pk, then
    by the bet sentence when a day holds two picks on one game, then by
    rank only for a pick that carries no game_pk at all. See `history`."""
    pk = graded.get("game_pk")
    if pk is not None:
        same_game = [p for p in frozen_picks
                     if p.get("game_pk") is not None and str(p.get("game_pk")) == str(pk)]
        if len(same_game) == 1:
            return same_game[0]
        if same_game:
            for p in same_game:
                if p.get("bet") == graded.get("bet"):
                    return p
            return same_game[0]
        return {}
    for p in frozen_picks:
        if p.get("game_pk") is None and p.get("rank") == graded.get("rank"):
            return p
    return {}


def history(*, path: Optional[str] = None, limit: Optional[int] = 60,
            sport: Optional[str] = None) -> dict:
    """Every settled day, newest first, each joined back to its own
    PUBLISHED row for the book and team names a settled row does not carry.

    WHY THE JOIN. `settle` deliberately appends a SEPARATE row (rule 2 in
    this module's docstring) carrying only what grading needs: rank, bet,
    label, market, price, game_pk, the result and the score. The book, the
    books-compared count and the team names are FROZEN_FIELDS on the
    PUBLISHED row alone -- they describe what a reader was shown at
    publish time, not what grading needed -- so a page that wants "took
    -140 at DraftKings, best of 11 books" beside a graded pick has to read
    both rows for the date and match them up.

    MATCHED BY GAME, NOT BY RANK (2026-09-12). This used to match on `rank`
    on the argument that rank is unique within one date's picks -- true
    until the 2026-09-11 change to `publish`, which composes a day's card
    from picks locked at different times, each carrying the rank it was
    frozen with. The 09-11 card has nine picks and ranks 1..5 twice over.
    Joined by rank, the record page printed the Brewers pick (rank 3,
    CIN@MIL, final 0-20) with the Guardians' clubs beside it (also rank 3,
    CLE@MIN): "CLE 0 -- MIN 20" next to a bet on Milwaukee, live, the
    morning after the first composed card settled. `game_pk` is the key a
    pick is graded by (`settle` looks its result up by it), so it is the
    key the page reads it back by; the bet sentence breaks a tie if a day
    ever carries two picks on one game, and a pick with no game_pk (none
    published so far, but the ledger is append-only and old) falls back to
    rank as before.

    `limit` caps how many days come back, newest first -- the ledger only
    grows, and the public record page has no reason to pull every day that
    ever settled just to show the last couple of months. Capped, never
    silently truncated: `total_days` and `truncated` say exactly what
    happened, so a caller can render "60 of 214 days" instead of a number
    that just looks complete. `limit=None` returns every settled day; the
    API route never does this (see api/card.py) but a script reading the
    whole history should not have to pass an arbitrarily large number.
    """
    resolved_path = path if path is not None else store_path(sport)
    ledger = _ledger(resolved_path)
    published_by_date: dict = {}
    settled: list = []
    for row in ledger.read():
        kind = row.get("kind")
        if kind == KIND_PUBLISHED:
            published_by_date[row.get("date")] = row
        elif kind == KIND_SETTLED:
            settled.append(row)

    # Lexicographic order on YYYY-MM-DD is chronological order.
    settled.sort(key=lambda r: r.get("date") or "", reverse=True)
    total_days = len(settled)
    capped = settled if limit is None else settled[:max(limit, 0)]

    days = []
    for row in capped:
        published = published_by_date.get(row.get("date")) or {}
        frozen_picks = list(published.get("picks") or ())
        picks = []
        for graded in row.get("picks") or ():
            frozen = _frozen_for_graded(graded, frozen_picks)
            picks.append({
                "rank": graded.get("rank"),
                "bet": graded.get("bet"),
                "label": graded.get("label"),
                "market": graded.get("market"),
                "price": graded.get("price"),
                "book": frozen.get("book"),
                "books": frozen.get("books"),
                "away_team": frozen.get("away_team"),
                "home_team": frozen.get("home_team"),
                "team_name": frozen.get("team_name"),
                "opponent_name": frozen.get("opponent_name"),
                "result": graded.get("result"),
                "profit_units": graded.get("profit_units"),
                "away_score": graded.get("away_score"),
                "home_score": graded.get("home_score"),
                # Populated only for a VOID pick (see grade_pick) -- the
                # plain-English reason nothing here could be graded.
                "reason": graded.get("reason"),
            })

        # PROP PICKS, joined the same way -- keyed by (game_pk, player) per
        # `_prop_pick_key` (FIXED 2026-09-14, see that function) rather than
        # `rank` alone, because unlike a game's picks a slate's prop picks
        # are not one-per-game: `rank` repeats across dates but never
        # collides WITHIN one date's prop picks (select_props assigns it
        # 1..MAX_PROP_PICKS), so the richer key is only needed because
        # `frozen_by_rank`'s simpler join does not carry over -- game picks
        # and prop picks are ranked in separate spaces.
        frozen_props_by_key = {
            _prop_pick_key(p): p for p in (published.get("prop_picks") or ())
        }
        prop_picks = []
        for graded in row.get("prop_picks") or ():
            frozen = frozen_props_by_key.get(_prop_pick_key(graded)) or {}
            prop_picks.append({
                "rank": graded.get("rank"),
                "bet": graded.get("bet"),
                "label": graded.get("label"),
                "player": graded.get("player"),
                "market": graded.get("market"),
                "line": graded.get("line"),
                "side": graded.get("side"),
                "price": graded.get("price"),
                "book": frozen.get("book"),
                "books": frozen.get("books"),
                "team": frozen.get("team"),
                "away_team": frozen.get("away_team"),
                "home_team": frozen.get("home_team"),
                "result": graded.get("result"),
                "profit_units": graded.get("profit_units"),
                # Populated only for a VOID pick (see grade_prop_pick) -- the
                # plain-English reason nothing here could be graded.
                "reason": graded.get("reason"),
            })

        # TOTAL PICKS, joined the same way -- keyed by (game_pk, line, side)
        # per `_total_pick_key`, ADDED 2026-09-14.
        frozen_totals_by_key = {
            _total_pick_key(p): p for p in (published.get("total_picks") or ())
        }
        total_picks = []
        for graded in row.get("total_picks") or ():
            frozen = frozen_totals_by_key.get(_total_pick_key(graded)) or {}
            total_picks.append({
                "rank": graded.get("rank"),
                "bet": graded.get("bet"),
                "label": graded.get("label"),
                "line": graded.get("line"),
                "side": graded.get("side"),
                "price": graded.get("price"),
                "book": frozen.get("book"),
                "books": frozen.get("books"),
                "away_team": frozen.get("away_team"),
                "home_team": frozen.get("home_team"),
                "result": graded.get("result"),
                "profit_units": graded.get("profit_units"),
                # Populated only for a VOID pick (see grade_total_pick) --
                # the plain-English reason nothing here could be graded.
                "reason": graded.get("reason"),
            })

        days.append({
            "date": row.get("date"),
            "settled_utc": row.get("settled_utc"),
            "wins": row.get("wins") or 0,
            "losses": row.get("losses") or 0,
            "pushes": row.get("pushes") or 0,
            "voids": row.get("voids") or 0,
            "n_staked": row.get("n_staked") or 0,
            "profit_units": row.get("profit_units"),
            "roi_pct": row.get("roi_pct"),
            # This settled row's own hash, and the PUBLISHED row's hash it
            # was graded against -- two different receipts. The published
            # hash is the one a reader wants: "this is what was claimed,
            # before the game, and here is the exact entry that proves it."
            "row_hash": row.get("row_hash"),
            "published_row_hash": row.get("published_row_hash"),
            "picks": picks,
            "prop_picks": prop_picks,
            "prop_wins": row.get("prop_wins") or 0,
            "prop_losses": row.get("prop_losses") or 0,
            "prop_pushes": row.get("prop_pushes") or 0,
            "prop_voids": row.get("prop_voids") or 0,
            "n_prop_staked": row.get("n_prop_staked") or 0,
            "prop_profit_units": row.get("prop_profit_units"),
            "prop_roi_pct": row.get("prop_roi_pct"),
            "total_picks": total_picks,
            "total_wins": row.get("total_wins") or 0,
            "total_losses": row.get("total_losses") or 0,
            "total_pushes": row.get("total_pushes") or 0,
            "total_voids": row.get("total_voids") or 0,
            "n_total_staked": row.get("n_total_staked") or 0,
            "total_profit_units": row.get("total_profit_units"),
            "total_roi_pct": row.get("total_roi_pct"),
        })

    # PUBLISHED BUT NOT YET GRADED, carried separately.
    #
    # `days` above is settled days only, and that is right for the record: an
    # ungraded day has no result to put in a tally. But it is wrong for a
    # CALENDAR, which is the question "what did you say, and when" before it
    # is the question "how did it go". A calendar built from `days` alone
    # shows nothing at all on the day a card is published and only fills in
    # the morning after -- so on the first day of the product, and on every
    # day before that night's settle, it reads as if nothing was published.
    #
    # Kept as its own key rather than mixed into `days` so no existing
    # consumer of `days` starts seeing rows with no result in them. A caller
    # that wants both merges them and knows which is which.
    pending = []
    settled_dates = {row.get("date") for row in settled}
    for date, row in published_by_date.items():
        if date in settled_dates:
            continue
        pending.append({
            "date": date,
            "published_utc": row.get("published_utc"),
            "n_filled": row.get("n_filled") or 0,
            "row_hash": row.get("row_hash"),
            "picks": [{
                "rank": p.get("rank"),
                "bet": p.get("bet"),
                "label": p.get("label"),
                "market": p.get("market"),
                "price": p.get("price"),
                "book": p.get("book"),
                "books": p.get("books"),
                "away_team": p.get("away_team"),
                "home_team": p.get("home_team"),
                "team_name": p.get("team_name"),
                "opponent_name": p.get("opponent_name"),
            } for p in (row.get("picks") or ())],
            "prop_picks": [{
                "rank": p.get("rank"),
                "bet": p.get("bet"),
                "label": p.get("label"),
                "player": p.get("player"),
                "market": p.get("market"),
                "line": p.get("line"),
                "side": p.get("side"),
                "price": p.get("price"),
                "book": p.get("book"),
                "books": p.get("books"),
                "team": p.get("team"),
                "away_team": p.get("away_team"),
                "home_team": p.get("home_team"),
            } for p in (row.get("prop_picks") or ())],
            "total_picks": [{
                "rank": p.get("rank"),
                "bet": p.get("bet"),
                "label": p.get("label"),
                "line": p.get("line"),
                "side": p.get("side"),
                "price": p.get("price"),
                "book": p.get("book"),
                "books": p.get("books"),
                "away_team": p.get("away_team"),
                "home_team": p.get("home_team"),
            } for p in (row.get("total_picks") or ())],
        })
    pending.sort(key=lambda r: r.get("date") or "", reverse=True)

    return {
        "days": days,
        "pending_days": pending,
        "limit": limit,
        "total_days": total_days,
        "truncated": total_days > len(days),
    }


def verify(*, path: Optional[str] = None, sport: Optional[str] = None):
    """Walk the chain. A published record whose chain is broken is not a
    record, and the page that shows it has to be able to say so."""
    resolved_path = path if path is not None else store_path(sport)
    return _ledger(resolved_path).verify()


# ---------------------------------------------------------------------------
# V2 LEDGER (build plan T3; rule registered in docs/PREREG_CARD_V2.md)
# ---------------------------------------------------------------------------
#
# WHY A SEPARATE SECTION IN THE SAME FILE, NOT A SEPARATE MODULE
# ------------------------------------------------------------------
# The build plan is explicit: "File: src/appstate/card_ledger.py. Additive
# only." V1's publish/settle/record keep grading evidence/cards_v1.jsonl
# exactly as they always have -- nothing above this line changes -- but V2
# needs its own store, its own lock-and-withdraw rule (a fill can be carried,
# withdrawn or graduated to a pick; V1 has no such state) and its own record
# shape (main-band picks, plus-money picks and fills reported apart, never
# pooled the way V1 pools game/prop/total). Reusing HashChainLedger,
# grade_pick, grade_prop_pick, _index_prop_box_rows, _parse_utc and the
# RESULT_* constants below is right; re-deriving the pooling and locking
# logic for a rule with a genuinely different shape (price classes, fills, a
# floor that fills up to, a ceiling that counts fills) would have forced one
# of the two rules to bend toward the other's assumptions.
#
# WHAT "PRICE_CLASS IS FROZEN AND NEVER RECOMPUTED AT READ TIME" MEANS HERE
# ----------------------------------------------------------------------------
# _frozen_v2_entry computes price_class once, at publish_v2/write time, from
# the price on THAT version of the row, and stores it. record_v2 and
# settle_v2 below only ever READ the stored value -- neither calls
# best_bets_card.price_class again. If the MAIN/PLUS_MONEY band in
# RuleParams ever changes, a row settled under the old band keeps the class
# it was graded under, because nothing here recomputes it from the row's own
# price a second time.

from src.analysis import best_bets_card as _v2_rule

CARD_STORE_V2 = os.path.join("evidence", "cards_v2.jsonl")
CARD_STORE_V2_SHADOW_A = os.path.join("evidence", "cards_v2_shadow_a.jsonl")
CARD_STORE_V2_SHADOW_C = os.path.join("evidence", "cards_v2_shadow_c.jsonl")
CARD_STORE_V2_SHADOW_E = os.path.join("evidence", "cards_v2_shadow_e.jsonl")
CARD_STORE_V1_SHADOW = os.path.join("evidence", "cards_v1_shadow.jsonl")
CARD_STORE_V2_VAR_STRICT_NOCAP = os.path.join(
    "evidence", "cards_v2_var_strict_nocap.jsonl")
CARD_STORE_V2_VAR_LOOSE_CAP3 = os.path.join(
    "evidence", "cards_v2_var_loose_cap3.jsonl")
CARD_STORE_V2_VAR_LOOSE_NOCAP = os.path.join(
    "evidence", "cards_v2_var_loose_nocap.jsonl")
# THERE IS NO CARD_STORE_V2_SHADOW_D. Registration section 10 deregisters
# shadow D; evidence/cards_v2_shadow_d.jsonl must never be created by this
# module. A test pins the absence of the name, not just the absence of a
# file, because a name that exists unused is the first step toward a file
# that quietly gets written again.

# The eight paths registration section 10 lists for v1_code_fingerprint --
# frozen on every CARD_STORE_V1_SHADOW row so 11.6 can say whether the V1 the
# comparison ran against is the V1 that was registered, without assuming the
# 2026-09-15 calibration freeze covered files it never touched.
V1_FINGERPRINT_FILES = (
    "src/analysis/strength.py",
    "src/analysis/playerprops.py",
    "src/analysis/propboard.py",
    "src/report/props.py",
    "src/analysis/daily_card.py",
    "src/report/card.py",
    "src/appstate/card_ledger.py",
    "data/processed/card_calibration.json",
)

# The paths registration 11.2 lists for V2's own code_fingerprint.
# src/report/card_v2.py and data/processed/card_v2_frozen_params.json are
# T5/T0a's deliverables and do not exist yet in this repo state; see
# code_fingerprint's docstring for why an absent path still counts rather
# than being skipped.
V2_FINGERPRINT_FILES = (
    "src/analysis/strength.py",
    "src/analysis/playerprops.py",
    "src/analysis/propboard.py",
    "src/report/props.py",
    "src/analysis/best_bets_card.py",
    "src/report/card_v2.py",
    "data/processed/card_v2_frozen_params.json",
)


def code_fingerprint(paths: Sequence[str] = V2_FINGERPRINT_FILES,
                      *, root: Optional[str] = None) -> str:
    """sha256 over the named files' exact bytes, in the given order.

    Each path contributes its own name AND its bytes to the hash (rather
    than just concatenating bytes) so that swapping two same-sized files
    between two path slots -- which would leave a bytes-only concatenation
    unchanged -- still changes the fingerprint.

    A MISSING file contributes a fixed sentinel rather than being skipped.
    Skipping it would mean a fingerprint computed today, before
    src/report/card_v2.py exists, is IDENTICAL to one computed after a
    change to a file that came into existence later -- the two states are
    not the same and must not hash the same. This also means the value
    returned right now, before T5/T0a land, is a real, stable, testable
    fingerprint of "every registered file that exists so far plus fixed
    placeholders for the two that do not yet" -- not a placeholder itself.
    """
    hasher = hashlib.sha256()
    base = Path(root) if root is not None else Path.cwd()
    for rel in paths:
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        try:
            hasher.update((base / rel).read_bytes())
        except OSError:
            hasher.update(b"<absent>")
        hasher.update(b"\0")
    return hasher.hexdigest()


# V2_FROZEN_FIELDS: V1's FROZEN_FIELDS plus every field registration 11's
# frozen-fields list names for a V2 pick. price_class, our_probability_used
# (the marked-down number), breakeven, value_need and gap are computed and
# stamped by _frozen_v2_entry at write time, never left to whatever the
# candidate dict happened to carry, so a row is comparable across dates even
# if a future caller changes what keys it builds candidates with.
V2_FROZEN_FIELDS = FROZEN_FIELDS + (
    "kind", "our_probability", "our_probability_used", "score", "price_class",
    "breakeven", "value_need", "gap", "lineup_posted", "expected_pa_source",
    "season_games", "failed_gates", "game_type", "entry_class", "take",
    "no_take_reason", "player", "player_id", "game_id",
)

# Fills carry everything a pick carries PLUS the quote age and run instant
# that ADDED the fill -- registration: "the quote age at the run that added
# the fill and the run instant that added it". Both are stamped once, at the
# run that first turns a close call into a shown fill, and are never
# refreshed on a later run that merely carries the fill forward.
FILL_FROZEN_FIELDS = V2_FROZEN_FIELDS + ("fill_quote_age_seconds", "fill_added_run_utc")

# Close calls that were NEVER shown are frozen with the quote age alone, for
# the audit trail -- and, per T3's ledger test table, are never graded:
# settle_v2 only ever reads all_bets and withdrawn, never
# close_calls_not_shown.
NEAR_FROZEN_FIELDS = V2_FROZEN_FIELDS + ("quote_age_seconds",)


def _v2_first_pitch(entry: Mapping) -> Optional[str]:
    """first_pitch_utc if the candidate carries it (the report layer's field
    name), else first_pitch (the fixture/test shorthand used in
    tests/test_best_bets_card.py). Both name the same instant; accepting
    either means a V2 candidate built by either caller locks correctly."""
    return entry.get("first_pitch_utc") or entry.get("first_pitch")


def _is_locked_v2(entry: Mapping, moment: datetime,
                   lead_hours: float = LOCK_LEAD_HOURS_DEFAULT) -> bool:
    """_is_locked's V2 counterpart -- same fail-closed rule (an entry with no
    readable first pitch is treated as locked), reading _v2_first_pitch
    instead of the single first_pitch_utc key."""
    first_pitch = _parse_utc(_v2_first_pitch(entry))
    if first_pitch is None:
        return True
    return moment >= first_pitch - timedelta(hours=lead_hours)


def _v2_entry_key(entry: Mapping):
    """The identity _lock_and_merge_v2 and G11 key on: player_id if the
    entry carries one (a prop), else game_id/game_pk -- exactly
    best_bets_card._game_key's rule, so the ledger's notion of "the same
    bet" never drifts from the rule's own G11 dedup."""
    return entry.get("player_id") or entry.get("game_id") or entry.get("game_pk")


def _v2_quote_age(entry: Mapping, moment: datetime) -> Optional[float]:
    observed = _parse_utc(entry.get("observed_utc"))
    if observed is None:
        return None
    return (moment - observed).total_seconds()


def _isoformat(value):
    """A candidate's `observed_utc`/`first_pitch*` may arrive as a real
    `datetime` (that is what `tests/test_best_bets_card.py`'s own fixtures
    build, and what a live caller that just called `datetime.now(utc)`
    would hand in) or as an ISO string (what a JSONL-backed store round-
    trips). The ledger row must always be JSON-serialisable, so a `datetime`
    is frozen to its isoformat string here, once, at write time -- never
    left for `HashChainLedger.append`'s `json.dumps` to fail on."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _frozen_v2_entry(entry: Mapping, params) -> dict:
    """One candidate, dict-shaped and price_class/our_probability_used/
    breakeven/value_need/gap stamped from best_bets_card's own formulas --
    never re-typed here (see the module's WHY THIS IS A NEW MODULE note)."""
    is_fill = entry.get("entry_class") == "fill"
    fields = FILL_FROZEN_FIELDS if is_fill else V2_FROZEN_FIELDS
    row = {key: entry.get(key) for key in fields}
    for date_field in ("observed_utc", "first_pitch_utc", "first_pitch"):
        if date_field in row:
            row[date_field] = _isoformat(row[date_field])

    price = entry.get("price")
    our_p = entry.get("our_probability")
    pcls = entry.get("price_class")
    if pcls is None and price is not None:
        pcls = _v2_rule.price_class(price)
    row["price_class"] = pcls
    row["kind"] = "prop" if _v2_rule._kind_is_prop(entry) else (entry.get("kind") or "game")
    row["failed_gates"] = list(entry.get("failed_gates") or ())

    if price is not None:
        row["breakeven"] = _v2_rule.breakeven(price)
        row["value_need"] = _v2_rule.value_need(price, params)
    if price is not None and our_p is not None:
        row["our_probability_used"] = _v2_rule.marked_down(our_p, params)
        be = row.get("breakeven")
        row["gap"] = (our_p - be) if be is not None else None

    if entry.get("sport") is not None:
        row["sport"] = entry["sport"]
    return row


def _apply_g11_v2(merged: list) -> list:
    """G11 at the ledger level: a LOCKED game/prop entry rejects any other
    entry sharing its identity. A locked moneyline pick therefore blocks a
    later run's run-line candidate on the same game -- the two would
    otherwise carry the same _v2_entry_key (the same game_id) and both
    survive the merge, which is the exact double-booking G11 exists to
    prevent inside one publish run; this is that same rule applied across
    runs."""
    locked_keys = {
        _v2_entry_key(e) for e in merged
        if e.get("locked") and e.get("entry_class") == "pick"
    }
    out = []
    seen = set()
    for e in merged:
        key = _v2_entry_key(e)
        if key is None:
            out.append(e)
            continue
        if e.get("locked"):
            out.append(e)
            seen.add(key)
            continue
        if key in locked_keys and key not in seen:
            continue  # rejected: a locked entry already owns this identity
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _apply_plus_money_subcap_v2(merged: list, params) -> list:
    """G14 at the ledger level (D4, D7). select() already applies the
    sub-cap to ONE run's fresh candidates, but a LOCKED plus-money pick from
    an earlier run and a fresh plus-money pick from this run can together
    exceed plus_money_subcap even though neither run's own candidate pool
    did -- each run only ever sees its own picks. Locked picks are never
    demoted (a lock is a lock); the lowest-scored UNLOCKED plus-money picks
    beyond the room a locked pick leaves are moved out of merged and
    returned here, mirroring plus_money_dropped_by_subcap from select()."""
    if params.plus_money_subcap is None:
        return []
    plus_picks = [e for e in merged
                  if e.get("entry_class") == "pick" and e.get("price_class") == "PLUS_MONEY"]
    locked = [e for e in plus_picks if e.get("locked")]
    unlocked = [e for e in plus_picks if not e.get("locked")]
    unlocked.sort(key=lambda e: -(e.get("score") or 0.0))
    room = max(0, params.plus_money_subcap - len(locked))
    drop = unlocked[room:]
    if drop:
        drop_ids = {id(e) for e in drop}
        merged[:] = [e for e in merged if id(e) not in drop_ids]
    return drop


def _apply_ceiling_v2(merged: list, params) -> list:
    """G12 at the ledger level, counting PICKS AND FILLS TOGETHER -- the
    owner's 2026-09-16 answer (best_bets_card.RuleParams.ceiling's own
    docstring). Locked entries are never refused (a lock is a lock); the
    lowest-scored unlocked picks, then unlocked fills, beyond the room a
    locked entry leaves are moved out of merged and returned as
    ceiling_refused, mirroring select()'s own field of that name."""
    locked_shown = [e for e in merged if e.get("locked")]
    unlocked_picks = [e for e in merged
                      if not e.get("locked") and e.get("entry_class") == "pick"]
    unlocked_fills = [e for e in merged
                      if not e.get("locked") and e.get("entry_class") == "fill"]
    unlocked_picks.sort(key=lambda e: -(e.get("score") or 0.0))
    room = max(0, params.ceiling - len(locked_shown))
    candidates = unlocked_picks + unlocked_fills
    keep_ids = {id(e) for e in candidates[:room]}
    refused = [e for e in candidates if id(e) not in keep_ids]
    if refused:
        refused_ids = {id(e) for e in refused}
        merged[:] = [e for e in merged if id(e) not in refused_ids]
    return refused


def _lock_and_merge_v2(prior: Sequence[Mapping], fresh: Sequence[Mapping], *,
                        moment: datetime, lock_lead_hours: float, params,
                        fresh_seconds: Optional[float] = None):
    """The registration's L1 to L4, for V2 entries (picks and fills alike).

    Returns (merged, withdrawn, plus_money_dropped_by_subcap,
    ceiling_refused). prior is last run's all_bets + withdrawn; fresh is
    this run's _frozen_v2_entry-shaped candidates (already scored, classed
    and gated by best_bets_card.select).

    * A prior entry already LOCKED is carried forward verbatim.
    * A prior PROVISIONAL entry whose game now falls inside the lock window
      locks AS LAST PUBLISHED -- the reader saw that bet at that price, so a
      stale or failing fresh read at the locking run does not change it.
    * Outside the window, a STALE fresh read (missing, or older than
      fresh_seconds when given) changes nothing.
    * A FRESH read that fails a prior PICK withdraws it; a FRESH read that
      fails a prior FILL only on a hard gate (anything but G3/G7, mirroring
      best_bets_card.is_fill_eligible) withdraws it -- a fill is never
      withdrawn merely because the picks reached the floor, because nothing
      here removes a fill for that reason.
    * A prior FILL whose fresh read clears every gate graduates to a PICK
      this run.
    * A WITHDRAWN entry whose fresh read clears every gate returns as the
      same pick, once.
    """
    prior = list(prior or ())
    fresh = list(fresh or ())

    locked: dict = {}
    withdrawn_by_key: dict = {}
    for entry in prior:
        key = _v2_entry_key(entry)
        if entry.get("locked"):
            locked[key] = entry
        elif entry.get("withdrawn"):
            withdrawn_by_key[key] = entry

    fresh_by_key = {_v2_entry_key(e): e for e in fresh}

    merged: list = []
    withdrawn: list = list(withdrawn_by_key.values())
    seen: set = set()

    for key, entry in locked.items():
        merged.append(entry)
        seen.add(key)

    for entry in prior:
        key = _v2_entry_key(entry)
        if key in locked or key in withdrawn_by_key:
            continue
        fresh_entry = fresh_by_key.get(key)

        if _is_locked_v2(entry, moment, lock_lead_hours):
            stamped = dict(entry)
            stamped["locked"] = True
            stamped["locked_at"] = moment.isoformat()
            merged.append(stamped)
            seen.add(key)
            continue

        if fresh_entry is None:
            stale = True
        elif fresh_seconds is not None:
            age = _v2_quote_age(fresh_entry, moment)
            stale = age is None or age > fresh_seconds
        else:
            stale = False

        if stale:
            merged.append(entry)
            seen.add(key)
            continue

        fails = fresh_entry.get("failed_gates") or []
        was_fill = entry.get("entry_class") == "fill"

        if was_fill:
            if not fails:
                graduated = dict(fresh_entry)
                graduated["entry_class"] = "pick"
                graduated["locked"] = False
                graduated["locked_at"] = None
                merged.append(graduated)
                seen.add(key)
                continue
            hard_fail = bool(set(fails) - _v2_rule._FILL_ALLOWED_FAILURES)
            if hard_fail:
                w = dict(entry)
                w["withdrawn"] = True
                w["withdrawn_at"] = moment.isoformat()
                w["withdrawal_reason"] = fails
                withdrawn.append(w)
                seen.add(key)
                continue
            merged.append(entry)
            seen.add(key)
            continue

        if fails:
            w = dict(entry)
            w["withdrawn"] = True
            w["withdrawn_at"] = moment.isoformat()
            w["withdrawal_reason"] = fails
            withdrawn.append(w)
            seen.add(key)
            continue

        merged.append(fresh_entry)
        seen.add(key)

    for key, fresh_entry in fresh_by_key.items():
        if key in seen:
            continue
        if key in withdrawn_by_key:
            # A previously-withdrawn key's fresh entry is handled ONLY by
            # the withdrawn-return pass below, never here -- adding it here
            # too would double-count it (once as a "new" pick, once still
            # sitting in `withdrawn`, since this loop marks the key `seen`
            # before that pass gets a chance to check it).
            continue
        if fresh_entry.get("entry_class") not in ("pick", "fill"):
            # A brand-new candidate with no prior entry that hard-failed
            # this run (entry_class is None). It was never shown, so it is
            # never added -- unlike a PRIOR key's failing fresh read (the
            # branch above), there is no earlier row for this key to
            # withdraw FROM.
            continue
        entry = dict(fresh_entry)
        if _is_locked_v2(entry, moment, lock_lead_hours):
            entry["locked"] = True
            entry["locked_at"] = moment.isoformat()
        else:
            entry["locked"] = False
            entry["locked_at"] = None
        merged.append(entry)
        seen.add(key)

    still_withdrawn = []
    for w in withdrawn:
        key = _v2_entry_key(w)
        fresh_entry = fresh_by_key.get(key)
        if (fresh_entry is not None and key not in seen
                and not (fresh_entry.get("failed_gates") or [])):
            returned = dict(fresh_entry)
            locked_now = _is_locked_v2(returned, moment, lock_lead_hours)
            returned["locked"] = locked_now
            returned["locked_at"] = moment.isoformat() if locked_now else None
            merged.append(returned)
            seen.add(key)
            continue
        still_withdrawn.append(w)

    merged = _apply_g11_v2(merged)
    plus_money_dropped_by_subcap = _apply_plus_money_subcap_v2(merged, params)
    ceiling_refused = _apply_ceiling_v2(merged, params)

    return merged, still_withdrawn, plus_money_dropped_by_subcap, ceiling_refused


def publish_v2(card: Mapping, *, now: Optional[str] = None,
               path: Optional[str] = None,
               lock_lead_hours: Optional[float] = None,
               fresh_seconds: Optional[float] = None,
               family_id: Optional[str] = None,
               arm: Optional[str] = None,
               pool_hash: Optional[str] = None,
               published: Optional[bool] = None) -> dict:
    """Publish one date's V2 card. Additive counterpart to publish.

    UNLIKE V1's publish, a card with ZERO picks is accepted -- registration
    section 6 makes "no bet cleared today" a real, recordable state, and
    T3's empty-day test pins this refusal NOT firing for V2 while it keeps
    firing for V1 (publish at :503-508 is untouched). The first call for a
    date always appends, even with nothing to show, so record_v2 never has
    to guess whether a quiet day was ever actually evaluated.

    `family_id`/`arm`/`pool_hash`/`published` are T3v's per-variant row
    stamps (registration 17.6, R7): row-level, like `code_fingerprint`,
    never per-entry, so a reader can tell which arm and which publish run a
    ledger row belongs to without re-deriving anything. Left `None` by a
    caller that isn't part of the variant family (T3's own callers, and
    every existing test), in which case the key is simply absent -- this
    function does not require the family machinery to exist to publish a
    plain V2 card.
    """
    resolved_path = path or CARD_STORE_V2
    lead = lock_lead_hours if lock_lead_hours is not None else LOCK_LEAD_HOURS_DEFAULT

    date = card.get("date")
    if not date:
        raise CardLedgerError("a V2 card with no date cannot be published")

    params = card.get("params") or _v2_rule.V2
    moment = _parse_utc(now) or datetime.now(timezone.utc)

    all_bets_in = card.get("all_bets")
    if all_bets_in is None:
        all_bets_in = (list(card.get("picks") or ())
                       + list(card.get("prop_picks") or ())
                       + list(card.get("fills") or ()))

    prior_row = published_row(date, path=resolved_path)
    prior_all = list((prior_row or {}).get("all_bets") or ())
    prior_withdrawn = list((prior_row or {}).get("withdrawn") or ())

    fresh_frozen = []
    for src_entry in all_bets_in:
        frozen = _frozen_v2_entry(src_entry, params)
        # NOT defaulted to "pick". A caller may hand in a candidate that
        # hard-failed this run (entry_class is None, failed_gates non-empty)
        # purely so `_lock_and_merge_v2` can see WHY a prior key's fresh
        # read failed, rather than reading it as merely absent/stale -- see
        # that function's docstring. Such an entry must never be added as a
        # NEW pick/fill of its own; `_lock_and_merge_v2`'s new-entries loop
        # filters on entry_class for exactly this reason.
        frozen["entry_class"] = src_entry.get("entry_class")
        fresh_frozen.append(frozen)

    merged, withdrawn, dropped_subcap, ceiling_refused = _lock_and_merge_v2(
        prior_all + prior_withdrawn, fresh_frozen, moment=moment,
        lock_lead_hours=lead, params=params, fresh_seconds=fresh_seconds)

    picks = sorted(
        [e for e in merged if e.get("entry_class") == "pick"],
        key=lambda e: -(e.get("score") or 0.0))
    for i, e in enumerate(picks, start=1):
        e["rank"] = i
    fills = [e for e in merged if e.get("entry_class") == "fill"]
    game_picks = [e for e in picks if e.get("kind") != "prop"]
    prop_picks = [e for e in picks if e.get("kind") == "prop"]

    def _shape(entries):
        rows = [{k: e.get(k) for k in
                ("price", "price_class", "entry_class", "locked",
                 "our_probability", "market", "line", "player", "game_id",
                 "game_pk")}
               for e in entries]
        return sorted(rows, key=lambda r: str(sorted(r.items())))

    unchanged = (
        prior_row is not None
        and _shape(prior_all) == _shape(merged)
        and _shape(prior_withdrawn) == _shape(withdrawn)
    )
    if unchanged:
        out = dict(prior_row)
        out["already_published"] = True
        return out

    payload = {
        "kind": KIND_PUBLISHED,
        "date": date,
        "published_utc": now or moment.isoformat(),
        "rule": params.rule_id,
        "code_fingerprint": code_fingerprint(),
        "params": _asdict(params),
        "all_bets": merged,
        "picks": game_picks,
        "prop_picks": prop_picks,
        "fills": fills,
        "withdrawn": withdrawn,
        "close_calls_not_shown": [
            {key: (_isoformat(v) if key in ("observed_utc", "first_pitch_utc", "first_pitch") else v)
             for key, v in dict(c).items() if key != "__params__"}
            for c in (card.get("close_calls_not_shown") or ())
        ],
        "stale_board": card.get("stale_board"),
        "n_picks": len(picks),
        "n_fills": len(fills),
        "n_plus_money_picks": sum(1 for e in picks if e.get("price_class") == "PLUS_MONEY"),
        "plus_money_dropped_by_subcap": dropped_subcap,
        "ceiling_refused": ceiling_refused,
        "basis": card.get("basis") or _v2_rule.BASIS,
        "disclaimer": card.get("disclaimer") or _v2_rule.DISCLAIMER,
    }
    if family_id is not None:
        payload["family_id"] = family_id
    if arm is not None:
        payload["arm"] = arm
    if pool_hash is not None:
        payload["pool_hash"] = pool_hash
    if published is not None:
        payload["published"] = published
    row = _ledger(resolved_path).append(payload)
    out = dict(row)
    out["already_published"] = False
    return out


def publish_v1_shadow(card: Mapping, *, now: Optional[str] = None,
                       path: Optional[str] = None) -> dict:
    """Publish a V1 shadow row carrying v1_code_fingerprint (registration
    section 10). This is NOT V1's own publish -- it never touches
    CARD_STORE/cards_v1.jsonl and it does not enforce V1's non-empty-picks
    refusal, because registration 11.6 needs a fingerprinted shadow row for
    every date, including a date V1 itself picked nothing for. card must
    already be V1-shaped (picks/prop_picks/total_picks as publish expects);
    this function only adds the fingerprint and writes to
    CARD_STORE_V1_SHADOW."""
    resolved_path = path or CARD_STORE_V1_SHADOW
    date = card.get("date")
    if not date:
        raise CardLedgerError("a V1 shadow row with no date cannot be published")
    payload = {
        "kind": KIND_PUBLISHED,
        "date": date,
        "published_utc": now or datetime.now(timezone.utc).isoformat(),
        "rule": card.get("rule"),
        "v1_code_fingerprint": code_fingerprint(V1_FINGERPRINT_FILES),
        "picks": list(card.get("picks") or ()),
        "prop_picks": list(card.get("prop_picks") or ()),
        "total_picks": list(card.get("total_picks") or ()),
    }
    return _ledger(resolved_path).append(payload)


def settle_v2(date: str, results_by_game_pk: Mapping, *,
              prop_box_rows: Optional[Sequence] = None,
              now: Optional[str] = None,
              path: Optional[str] = None) -> Optional[dict]:
    """Grade one published V2 card and append the outcome as a NEW row.

    Grades every entry on the newest row for date: every entry in all_bets
    (locked picks AND locked/provisional fills -- a provisional entry left
    on the last row because no lock run ever happened for it is graded and
    flagged graded_without_lock_run, never silently skipped) and every entry
    in withdrawn, each exactly once, each carrying the entry_class and
    price_class it held at ITS OWN graded version. close_calls_not_shown is
    never graded -- those were never shown to a reader and are not bets of
    record.

    Reuses grade_pick and grade_prop_pick unmodified: V2's grading
    arithmetic (moneyline/run-line win-loss-push, prop over/under/push, flat
    one-unit stakes) is identical to V1's, only the population and the price
    classing around it differ.
    """
    resolved_path = path or CARD_STORE_V2
    row = published_row(date, path=resolved_path)
    if row is None:
        return None
    if settled_row(date, path=resolved_path) is not None:
        return None

    all_bets = row.get("all_bets") or ()
    graded_without_lock_run = bool(all_bets) and not any(e.get("locked") for e in all_bets)
    box_index = _index_prop_box_rows(prop_box_rows)

    def _grade_one(entry: Mapping, *, withdrawn: bool) -> dict:
        if entry.get("kind") == "prop":
            grade = grade_prop_pick(entry, box_index)
        else:
            lookup_key = entry.get("game_id") if entry.get("sport") else entry.get("game_pk")
            result = (results_by_game_pk.get(lookup_key)
                     or results_by_game_pk.get(str(lookup_key)) or {})
            grade = grade_pick(entry, result)
        out = dict(entry)
        out.update(grade)
        out["withdrawn"] = withdrawn
        out["graded_without_lock_run"] = (not withdrawn) and graded_without_lock_run
        return out

    graded = [_grade_one(e, withdrawn=False) for e in all_bets]
    graded += [_grade_one(e, withdrawn=True) for e in (row.get("withdrawn") or ())]

    def _tally(entries):
        wins = sum(1 for g in entries if g["result"] == RESULT_WIN)
        losses = sum(1 for g in entries if g["result"] == RESULT_LOSS)
        pushes = sum(1 for g in entries if g["result"] == RESULT_PUSH)
        voids = sum(1 for g in entries if g["result"] == RESULT_VOID)
        staked = wins + losses
        profit = round(sum(g.get("profit_units") or 0.0 for g in entries
                           if g["result"] in (RESULT_WIN, RESULT_LOSS)), 4)
        return wins, losses, pushes, voids, staked, profit

    wins, losses, pushes, voids, staked, profit = _tally(graded)

    payload = {
        "kind": KIND_SETTLED,
        "date": date,
        "settled_utc": now or datetime.now(timezone.utc).isoformat(),
        "rule": row.get("rule"),
        "graded": graded,
        "wins": wins, "losses": losses, "pushes": pushes, "voids": voids,
        "n_staked": staked, "profit_units": profit,
        "graded_without_lock_run": graded_without_lock_run,
    }
    return _ledger(resolved_path).append(payload)


def record_v2(*, path: Optional[str] = None, since: Optional[str] = None,
              until: Optional[str] = None, price_class: Optional[str] = None,
              entry_class: Optional[str] = None) -> dict:
    """The V2 reader (registration R5): main-band picks, plus-money picks
    and fills reported APART, never pooled into one figure, plus combined
    (D9 -- the sum of the two PICK class figures, a description, never the
    rule's own result) and withdrawn (a count, apart from every figure).

    since/until are both inclusive date-string bounds. price_class/
    entry_class narrow the whole call to one class -- the value read back is
    exactly the value _frozen_v2_entry froze at publish time, never
    recomputed here from the row's own price a second time.
    """
    resolved_path = path or CARD_STORE_V2

    def _blank():
        return {"days": 0, "wins": 0, "losses": 0, "pushes": 0, "voids": 0,
                "n_staked": 0, "profit_units": 0.0, "win_rate": None,
                "roi_pct": None}

    main_fig, plus_fig, fills_fig, combined = _blank(), _blank(), _blank(), _blank()
    withdrawn_n = 0
    days_seen = set()

    def _add(fig, entry):
        result = entry.get("result")
        if result == RESULT_WIN:
            fig["wins"] += 1
        elif result == RESULT_LOSS:
            fig["losses"] += 1
        elif result == RESULT_PUSH:
            fig["pushes"] += 1
        elif result == RESULT_VOID:
            fig["voids"] += 1
        if result in (RESULT_WIN, RESULT_LOSS):
            fig["n_staked"] += 1
            fig["profit_units"] += entry.get("profit_units") or 0.0

    for row in _ledger(resolved_path).read():
        if row.get("kind") != KIND_SETTLED:
            continue
        date = row.get("date") or ""
        if since and date < since:
            continue
        if until and date > until:
            continue
        entries = row.get("graded") or ()
        if entries:
            days_seen.add(date)
        for entry in entries:
            if price_class is not None and entry.get("price_class") != price_class:
                continue
            if entry_class is not None and entry.get("entry_class") != entry_class:
                continue
            if entry.get("withdrawn"):
                withdrawn_n += 1
                continue
            if entry.get("entry_class") == "fill":
                _add(fills_fig, entry)
                continue
            if entry.get("price_class") == "PLUS_MONEY":
                _add(plus_fig, entry)
                _add(combined, entry)
            elif entry.get("price_class") == "MAIN":
                _add(main_fig, entry)
                _add(combined, entry)

    for fig in (main_fig, plus_fig, fills_fig, combined):
        fig["days"] = len(days_seen)
        fig["profit_units"] = round(fig["profit_units"], 4)
        fig["win_rate"] = (round(fig["wins"] / fig["n_staked"], 4)
                           if fig["n_staked"] else None)
        fig["roi_pct"] = (round(fig["profit_units"] / fig["n_staked"] * 100.0, 3)
                          if fig["n_staked"] else None)

    return {
        "since": since, "until": until,
        "main": main_fig, "plus_money": plus_fig, "fills": fills_fig,
        "combined": combined, "withdrawn": withdrawn_n,
    }


# ---------------------------------------------------------------------------
# T3v -- per-variant ledgers (registration 12 R7/R8, 17.6)
# ---------------------------------------------------------------------------

# Arm id -> its own store. A2/A3/A4 are paper; A1's store is CARD_STORE_V2,
# unchanged from T3, so nothing about where the published card lives moves
# because the family exists.
_VARIANT_STORE_BY_ARM = {
    "A1": CARD_STORE_V2,
    "A2": CARD_STORE_V2_VAR_STRICT_NOCAP,
    "A3": CARD_STORE_V2_VAR_LOOSE_CAP3,
    "A4": CARD_STORE_V2_VAR_LOOSE_NOCAP,
}


def publish_variants(family_result: Mapping[str, Mapping], *, now: Optional[str] = None,
                      lock_lead_hours: Optional[float] = None,
                      fresh_seconds: Optional[float] = None,
                      store_by_arm: Optional[Mapping[str, str]] = None) -> dict:
    """Write each arm's card to that arm's own store, using T3's
    `publish_v2` machinery unchanged (registration 17.6: "R2's rule
    extends -- a paper arm writes only to its own file and nothing writes
    to evidence/cards_v2.jsonl but A1").

    `family_result` is `card_variants.run_family`'s return, with a `date`
    key added to each arm's result by the caller first (`select()` itself
    is date-less -- it only ever sees one night's pool -- so the publish
    job stamps the slate date once, the same way it already does for V1's
    `publish` and T3's `publish_v2`). Each arm's dict already carries that
    arm's `pool_hash`, `family_id`, `arm` and `published` (stamped by the
    runner, not re-derived here -- this
    function trusts the runner's stamps rather than recomputing pool_hash
    from the arm's own output, because hashing an arm's OUTPUT instead of
    the shared INPUT pool would prove nothing: two arms can select
    different picks from the identical pool by design, so an output hash
    would legitimately differ between arms even when they saw the same
    board, defeating the one thing pool_hash exists to prove).

    One call per publish run, so the four files are written from one
    `family_result` and can never drift apart by a run reaching some arms
    and not others (a caller that wants that guarantee should call this
    once per run, not once per arm).

    There is no cross-arm return value here and no per-arm win-loss figure
    -- see `src/analysis/card_variants.py`'s module docstring for why that
    is a hard rule and not an oversight. This function's return is just
    `{arm_id: publish_v2's own return}`, so a caller can see whether each
    write was a no-op (`already_published`) without this module summing
    anything across arms.
    """
    stores = dict(_VARIANT_STORE_BY_ARM)
    if store_by_arm:
        stores.update(store_by_arm)

    out: dict = {}
    for arm_id, result in family_result.items():
        path = stores[arm_id]
        card = dict(result)
        out[arm_id] = publish_v2(
            card,
            now=now,
            path=path,
            lock_lead_hours=lock_lead_hours,
            fresh_seconds=fresh_seconds,
            family_id=result.get("family_id"),
            arm=result.get("arm", arm_id),
            pool_hash=result.get("pool_hash"),
            published=result.get("published", arm_id == "A1"),
        )
    return out
