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

import os
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional, Sequence

from src.core import odds as odds_math
from src.ledger.chain import HashChainLedger

CARD_STORE = os.path.join("evidence", "cards_v1.jsonl")

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


class CardLedgerError(RuntimeError):
    pass


def _ledger(path: Optional[str] = None) -> HashChainLedger:
    return HashChainLedger(path or CARD_STORE)


def _frozen_pick(pick: Mapping) -> dict:
    return {key: pick.get(key) for key in FROZEN_FIELDS}


def _same_picks(left, right) -> bool:
    """Would appending `right` say anything `left` does not?

    Compared on the FROZEN FIELDS ONLY, deliberately. `locked_at` is a
    timestamp that moves every run, so including it would make every publish
    look like a change and write an identical row five times a day, burying
    the versions that matter under noise. `locked` itself is derived from the
    first pitch and the clock, so a pick that locked since the last run
    ALREADY differs on nothing else -- and that transition is worth a row,
    which is why `locked` is compared and `locked_at` is not.
    """
    def _shape(picks):
        out = []
        for pick in picks or ():
            row = {key: pick.get(key) for key in FROZEN_FIELDS}
            row["locked"] = bool(pick.get("locked"))
            out.append(row)
        return sorted(out, key=lambda r: (str(r.get("game_pk")),
                                          str(r.get("market")),
                                          str(r.get("line"))))
    return _shape(left) == _shape(right)


# HOW LONG BEFORE ITS OWN FIRST PITCH A PICK STOPS CHANGING.
#
# Matches src/report/card.py's CARD_FREEZE_LEAD_HOURS. Inside this window the
# pick is the bet of record and nothing later can alter it; outside it, a
# later run may replace it with a better read.
LOCK_LEAD_HOURS = 4.0


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

    game_pk is the join everywhere else in this module and it is kept as a
    STRING deliberately -- the results store round-trips through CSV, and the
    int/str mismatch has already cost this project two separate all-VOID
    incidents (see `_score`).
    """
    return (str(pick.get("game_pk")), pick.get("market"), pick.get("line"))


def published_row(date: str, *, path: Optional[str] = None) -> Optional[dict]:
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
    newest = None
    for row in _ledger(path).read():
        if row.get("kind") == KIND_PUBLISHED and row.get("date") == date:
            newest = row
    return newest


def published_versions(date: str, *, path: Optional[str] = None) -> list:
    """Every published version for `date`, oldest first.

    The receipt is not just the final card -- it is that the card CHANGED and
    when. A reader who wants to check that we did not quietly improve a pick
    after the fact reads this.
    """
    return [row for row in _ledger(path).read()
            if row.get("kind") == KIND_PUBLISHED and row.get("date") == date]
    return None


def settled_row(date: str, *, path: Optional[str] = None) -> Optional[dict]:
    for row in _ledger(path).read():
        if row.get("kind") == KIND_SETTLED and row.get("date") == date:
            return row
    return None


def publish(card: Mapping, *, now: Optional[str] = None,
            path: Optional[str] = None,
            lock_lead_hours: float = LOCK_LEAD_HOURS) -> dict:
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
    date = card.get("date")
    if not date:
        raise CardLedgerError("a card with no date cannot be published")
    picks = card.get("picks") or []
    if not picks:
        raise CardLedgerError(
            f"the card for {date} has no picks; there is nothing to freeze. "
            "An empty card is a real state -- see src/report/card.py's "
            "_empty_reason -- but it is not evidence and is not recorded.")

    moment = _parse_utc(now) or datetime.now(timezone.utc)
    previous = published_row(date, path=path)
    prior_picks = list((previous or {}).get("picks") or ())

    # Every pick already locked by an earlier run, kept exactly as it was.
    locked: dict = {}
    for pick in prior_picks:
        if pick.get("locked"):
            locked[_pick_key(pick)] = pick
        elif _is_locked(pick, moment, lock_lead_hours):
            # It was provisional when written and its game has since come
            # within the window. This run is the one that locks it, and it
            # locks the pick AS LAST PUBLISHED -- the reader saw that bet at
            # that price, and the lock records what was shown, not a fresh
            # read taken after the window closed.
            stamped = dict(pick)
            stamped["locked"] = True
            stamped["locked_at"] = moment.isoformat()
            locked[_pick_key(pick)] = stamped

    merged = []
    seen = set()
    for pick in picks:
        key = _pick_key(pick)
        seen.add(key)
        if key in locked:
            merged.append(locked[key])
            continue
        fresh = _frozen_pick(pick)
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

    # NOTHING CHANGED, NOTHING APPENDED. Publishing five times a day would
    # otherwise write five identical rows and bury the versions that matter.
    if previous is not None and _same_picks(prior_picks, merged):
        out = dict(previous)
        out["already_published"] = True
        return out

    picks = merged
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
    }
    row = _ledger(path).append(payload)
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


def settle(date: str, results_by_game_pk: Mapping, *,
           now: Optional[str] = None, path: Optional[str] = None) -> Optional[dict]:
    """Grade one published card and append the outcome as a NEW row.

    Returns None when there is nothing to do -- no card for that date, or it
    is already settled. Never edits the published row.
    """
    published = published_row(date, path=path)
    if published is None:
        return None
    if settled_row(date, path=path) is not None:
        return None

    graded, staked, profit = [], 0, 0.0
    for pick in published.get("picks") or ():
        pk = pick.get("game_pk")
        result = (results_by_game_pk.get(pk)
                  or results_by_game_pk.get(str(pk))
                  or {})
        grade = grade_pick(pick, result)
        graded.append({"rank": pick.get("rank"), "bet": pick.get("bet"),
                       "label": pick.get("label"), "market": pick.get("market"),
                       "price": pick.get("price"), "game_pk": pk, **grade})
        if grade["result"] in (RESULT_WIN, RESULT_LOSS):
            staked += 1
            profit += grade["profit_units"]

    wins = sum(1 for g in graded if g["result"] == RESULT_WIN)
    losses = sum(1 for g in graded if g["result"] == RESULT_LOSS)
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
    }
    return _ledger(path).append(payload)


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------

def record(*, path: Optional[str] = None, since: Optional[str] = None) -> dict:
    """The running record: every settled card, pooled.

    Pooled is CORRECT here and is not the pooling mistake this repo warns
    about elsewhere. The card is one system with one rule, so its picks are
    one population; the warning applies to pooling DIFFERENT systems, where
    a control and a forward test get averaged into a number describing
    neither.

    VOIDS ARE COUNTED AND REPORTED, never dropped. A record that silently
    omits postponed games is a record with a hole in it that nobody can see.
    """
    days, wins, losses, pushes, voids, staked = 0, 0, 0, 0, 0, 0
    profit = 0.0
    by_label = {}
    for row in _ledger(path).read():
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

    for slot in by_label.values():
        slot["profit_units"] = round(slot["profit_units"], 4)
        slot["win_rate"] = (round(slot["wins"] / slot["staked"], 4)
                            if slot["staked"] else None)

    return {
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
        "since": since,
    }


def history(*, path: Optional[str] = None, limit: Optional[int] = 60) -> dict:
    """Every settled day, newest first, each joined back to its own
    PUBLISHED row for the book and team names a settled row does not carry.

    WHY THE JOIN. `settle` deliberately appends a SEPARATE row (rule 2 in
    this module's docstring) carrying only what grading needs: rank, bet,
    label, market, price, game_pk, the result and the score. The book, the
    books-compared count and the team names are FROZEN_FIELDS on the
    PUBLISHED row alone -- they describe what a reader was shown at
    publish time, not what grading needed -- so a page that wants "took
    -140 at DraftKings, best of 11 books" beside a graded pick has to read
    both rows for the date and match them up. Matched by `rank`, which is
    unique within one date's picks (1..daily_card.MAX_PICKS) and is carried
    unchanged on both the frozen pick and its graded counterpart.

    `limit` caps how many days come back, newest first -- the ledger only
    grows, and the public record page has no reason to pull every day that
    ever settled just to show the last couple of months. Capped, never
    silently truncated: `total_days` and `truncated` say exactly what
    happened, so a caller can render "60 of 214 days" instead of a number
    that just looks complete. `limit=None` returns every settled day; the
    API route never does this (see api/card.py) but a script reading the
    whole history should not have to pass an arbitrarily large number.
    """
    ledger = _ledger(path)
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
        frozen_by_rank = {p.get("rank"): p for p in (published.get("picks") or ())}
        picks = []
        for graded in row.get("picks") or ():
            frozen = frozen_by_rank.get(graded.get("rank")) or {}
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
        })
    pending.sort(key=lambda r: r.get("date") or "", reverse=True)

    return {
        "days": days,
        "pending_days": pending,
        "limit": limit,
        "total_days": total_days,
        "truncated": total_days > len(days),
    }


def verify(*, path: Optional[str] = None):
    """Walk the chain. A published record whose chain is broken is not a
    record, and the page that shows it has to be able to say so."""
    return _ledger(path).verify()
