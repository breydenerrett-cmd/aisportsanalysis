"""V3 measurement core: how fast prices react after an information event.

WHAT THIS MODULE IS, AND IS NOT
-------------------------------
This is the measurement layer of the V3 information-timing family
(docs/RESEARCH_V3_TIMING.md): given one EVENT with a trustworthy timestamp
and the captured per-book quotes around it, compute the frozen quantities --
who moved first, how long until the market had moved, how big the moves
were, and whether any book sat still on a stale price while the rest of the
market repriced. Every definition here restates the pre-registration; if the
two ever disagree, the pre-registration wins and this module is wrong.

It is NOT an edge detector. A measured latency says the market takes time to
digest information at our capture resolution -- a necessary condition for a
timing edge and nothing more. Nothing in this module knows who won a game,
and nothing downstream may quietly turn a stale-window distribution into a
bet list; that would be a new family with the full funnel.

TIMESTAMP DISCIPLINE
--------------------
Events carry either an exact timestamp (grade A) or a bracketing interval
(grade B: the event happened between two of our own capture instants).
Grade B events are measured from the interval's END -- the conservative
choice, because measuring from the start would count capture lag as market
lag and flatter every latency number. Grade C/D events must never reach this
module; admission is the caller's job and the pre-registration's gate.

All timestamps are ISO-8601 strings with timezone; comparisons are on
parsed datetimes. A quote row without a parseable timestamp is dropped with
a note, never guessed.
"""

from __future__ import annotations

import datetime as dt

from src.core import odds as odds_math

# The frozen quality gates (docs/RESEARCH_V3_TIMING.md). Restated, not
# invented here.
MIN_BOOKS = 6
MOVE_FLOOR = 0.010          # de-vigged probability points
STALE_QUORUM = 0.5          # fraction of books moved before "stale" means anything
LADDER = (0.25, 0.5, 0.75, 1.0)
MAX_PRE_GAP_MINUTES = 90    # a pre-event quote older than this is not "immediately before"


class EventStudyError(RuntimeError):
    """Raised when an event cannot be measured honestly."""


def _parse(ts):
    if isinstance(ts, dt.datetime):
        return ts
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def event_time(event) -> dt.datetime:
    """The instant to measure from: the timestamp, or a grade-B interval's END.

    Measuring a bracketed event from its interval end is conservative on
    purpose -- latency measured from the start would include our own capture
    lag and overstate how slow the market is.
    """
    if event.get("ts") is not None:
        parsed = _parse(event["ts"])
        if parsed is None:
            raise EventStudyError(f"unparseable event ts {event['ts']!r}")
        return parsed
    interval = event.get("interval")
    if interval and len(interval) == 2:
        parsed = _parse(interval[1])
        if parsed is None:
            raise EventStudyError(f"unparseable interval end {interval[1]!r}")
        return parsed
    raise EventStudyError("event carries neither ts nor interval")


def _fair_home(quote):
    """De-vigged home probability, or None when the pair cannot be de-vigged."""
    try:
        _, home = odds_math.devig_two_way(
            quote["away_price"], quote["home_price"], method="proportional")
    except odds_math.OddsError:
        return None
    return home


def _by_book(quotes):
    """{book: [(parsed_ts, fair_home), ...] sorted by time}, silently
    dropping rows that cannot be parsed or de-vigged -- each drop is a row,
    never a fabricated value."""
    series = {}
    for quote in quotes:
        when = _parse(quote.get("ts"))
        fair = _fair_home(quote)
        book = quote.get("book")
        if when is None or fair is None or not book:
            continue
        series.setdefault(book, []).append((when, fair))
    for rows in series.values():
        rows.sort(key=lambda pair: pair[0])
    return series


def measure(event, quotes, *, game_start=None,
            expected_sign=None) -> dict:
    """The frozen V3 measurements for one admitted event.

    event: {"ts": iso} (grade A) or {"interval": (start, end)} (grade B),
    plus whatever identifying fields the caller carries through.
    quotes: [{"ts", "book", "away_price", "home_price"}, ...] spanning the
    window around the event (the caller decides the window; this module
    uses everything it is given).
    game_start: ISO instant; post-start quotes are ignored and stale windows
    are capped there.
    expected_sign: +1 if the information should RAISE the home side's fair
    probability, -1 if lower, None when the class has no frozen direction.

    Returns a dict of measurements, or {"excluded": reason} when the event
    fails a frozen gate. Exclusion is a first-class answer: an event that
    cannot be measured honestly is reported as excluded, never bent to fit.
    """
    when = event_time(event)
    start_cap = _parse(game_start) if game_start else None
    if start_cap is not None and when >= start_cap:
        return {"excluded": "event at or after first pitch"}

    series = _by_book(quotes)
    if start_cap is not None:
        series = {book: [(t, f) for t, f in rows if t < start_cap]
                  for book, rows in series.items()}

    # The last quote strictly before the event, per book, within the
    # freshness gate. "Immediately before" is a promise, not a vibe.
    horizon = when - dt.timedelta(minutes=MAX_PRE_GAP_MINUTES)
    pre = {}
    for book, rows in series.items():
        before = [(t, f) for t, f in rows if t < when and t >= horizon]
        if before:
            pre[book] = before[-1]
    if len(pre) < MIN_BOOKS:
        return {"excluded": (f"only {len(pre)} books quoted within "
                             f"{MAX_PRE_GAP_MINUTES} minutes before the "
                             f"event; the floor is {MIN_BOOKS}")}

    pre_consensus = sum(f for _, f in pre.values()) / len(pre)

    # Per book: the first post-event capture whose de-vigged move from the
    # book's own pre-event quote crosses the floor.
    moves = {}
    for book, (pre_t, pre_f) in pre.items():
        for t, f in series[book]:
            if t < when:
                continue
            if abs(f - pre_f) >= MOVE_FLOOR:
                moves[book] = {
                    "minutes": (t - when).total_seconds() / 60.0,
                    "magnitude": round(f - pre_f, 5),
                    "at": t,
                }
                break

    moved = sorted(moves.items(), key=lambda kv: (kv[1]["at"], kv[0]))
    total = len(pre)

    # Reaction ladder: minutes until each fraction of pre-quoting books has
    # moved. A rung never reached is None -- absence, not zero.
    ladder = {}
    for fraction in LADDER:
        need = max(1, int(round(fraction * total)))
        ladder[f"{int(fraction * 100)}%"] = (
            round(moved[need - 1][1]["minutes"], 2) if len(moved) >= need
            else None)

    # First mover(s): every book whose crossing landed on the earliest
    # post-event capture instant. Ties within one capture are ties -- the
    # grid cannot order what it observed simultaneously.
    first_movers, first_magnitude = [], None
    if moved:
        first_at = moved[0][1]["at"]
        first_movers = sorted(b for b, m in moved if m["at"] == first_at)
        first_magnitude = moved[0][1]["magnitude"]

    # Stale books: after the 50% quorum has moved, a book still quoting
    # within the floor of its own pre-event price. The window runs to that
    # book's eventual move, or to first pitch -- "observable that whole
    # time" is the only executability claim this data can support.
    quorum_needed = max(1, int(round(STALE_QUORUM * total)))
    stale = {}
    if len(moved) >= quorum_needed:
        quorum_at = moved[quorum_needed - 1][1]["at"]
        for book, (pre_t, pre_f) in pre.items():
            if book in moves and moves[book]["at"] <= quorum_at:
                continue
            after = [t for t, f in series[book] if t > quorum_at]
            if not after:
                continue
            end = moves[book]["at"] if book in moves else (
                start_cap if start_cap is not None else max(after))
            stale[book] = {
                "minutes": round((end - quorum_at).total_seconds() / 60.0, 2),
                "observations": len([t for t in after if t <= end]),
                "closed_by": "moved" if book in moves else "first_pitch",
            }

    # Consensus move: mean de-vigged home probability over the pre-quoting
    # books, tracked at each post-event capture instant where at least the
    # book floor still quotes.
    post_instants = sorted({t for rows in series.values()
                            for t, _ in rows if t >= when})
    consensus_path, final_consensus = [], None
    for instant in post_instants:
        values = []
        for book in pre:
            past = [(t, f) for t, f in series[book] if t <= instant]
            if past:
                values.append(past[-1][1])
        if len(values) >= MIN_BOOKS:
            level = sum(values) / len(values)
            consensus_path.append((instant, level))
            final_consensus = level
    consensus_move = (round(final_consensus - pre_consensus, 5)
                      if final_consensus is not None else None)

    direction = None
    if expected_sign is not None:
        direction = {
            "first_move_agrees": (None if first_magnitude is None else
                                  (first_magnitude > 0) == (expected_sign > 0)),
            "consensus_agrees": (None if consensus_move is None else
                                 (consensus_move > 0) == (expected_sign > 0)
                                 if abs(consensus_move) >= MOVE_FLOOR else None),
        }

    return {
        "excluded": None,
        "event_time": when.isoformat(),
        "books_pre": total,
        "pre_consensus": round(pre_consensus, 5),
        "books_moved": len(moved),
        "first_movers": first_movers,
        "first_move_minutes": (round(moved[0][1]["minutes"], 2)
                               if moved else None),
        "first_move_magnitude": first_magnitude,
        "ladder_minutes": ladder,
        "moves": {b: {"minutes": round(m["minutes"], 2),
                      "magnitude": m["magnitude"]} for b, m in moves.items()},
        "stale_books": stale,
        "consensus_move": consensus_move,
        "direction": direction,
    }
