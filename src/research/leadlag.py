"""Cross-book lead/lag: the empirical sportsbook response table.

eventstudy.measure() answers "what happened around ONE event". This module
aggregates many measured events into the table V3 actually wants to read:
which book typically moves first, each book's median response latency,
which books lag, whether leadership is stable over time, and whether the
stale prices that appear were still observable when the rest of the market
had already repriced.

DESCRIPTIVE, BY REGISTRATION
----------------------------
Everything here is a description of captured prices. A book appearing at
the top of the first-mover table is not an oracle, and a book at the bottom
is not a free lunch: no entry in this table is an edge claim, and the
pre-registration (docs/RESEARCH_V3_TIMING.md) bars promoting any of it
without a fresh family. Latency medians are reported with their sample
sizes, leadership stability is measured rather than asserted, and every
aggregate refuses to exist below the event floor.
"""

from __future__ import annotations

# Below this many admitted events, a per-class table is a story, not a
# table. Matches the pre-registration's class floor.
MIN_EVENTS = 30

# A book must appear in at least this many events before its personal
# latency median is quoted -- five observations of one book is gossip.
MIN_BOOK_EVENTS = 10


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def response_table(measured, *, min_events=MIN_EVENTS) -> dict:
    """Aggregate measured (non-excluded) events into the response table.

    measured: list of eventstudy.measure() results, already filtered to one
    event class by the caller -- mixing classes here would average a lineup
    posting with a trade and mean nothing.
    """
    usable = [m for m in measured if m and m.get("excluded") is None]
    if len(usable) < min_events:
        return {"skipped": (f"{len(usable)} measurable events is below the "
                            f"{min_events}-event floor; no table")}

    first_counts, latencies, appearances = {}, {}, {}
    stale_events = 0
    stale_minutes, stale_observations = [], []
    ladder_rows = {rung: [] for rung in ("25%", "50%", "75%", "100%")}

    for event in usable:
        for book in event.get("first_movers", []):
            first_counts[book] = first_counts.get(book, 0) + 1
        for book, move in (event.get("moves") or {}).items():
            latencies.setdefault(book, []).append(move["minutes"])
        # Appearance = the book quoted pre-event, whether or not it moved;
        # counting movers only would flatter slow books that simply never
        # react inside the window.
        for book in set((event.get("moves") or {}))\
                .union(event.get("stale_books") or {})\
                .union(event.get("first_movers") or []):
            appearances[book] = appearances.get(book, 0) + 1
        stale = event.get("stale_books") or {}
        if stale:
            stale_events += 1
            for entry in stale.values():
                stale_minutes.append(entry["minutes"])
                stale_observations.append(entry["observations"])
        for rung, value in (event.get("ladder_minutes") or {}).items():
            if value is not None:
                ladder_rows[rung].append(value)

    books = {}
    for book, times in sorted(latencies.items()):
        if appearances.get(book, 0) < MIN_BOOK_EVENTS:
            books[book] = {"n": appearances.get(book, 0),
                           "note": (f"seen in {appearances.get(book, 0)} "
                                    f"events; under the {MIN_BOOK_EVENTS} "
                                    "floor, no median quoted")}
            continue
        books[book] = {
            "n": appearances[book],
            "moved_n": len(times),
            "median_minutes": round(_median(times), 2),
            "first_mover_count": first_counts.get(book, 0),
        }

    return {
        "events": len(usable),
        "first_mover_counts": dict(sorted(first_counts.items(),
                                          key=lambda kv: (-kv[1], kv[0]))),
        "ladder_medians_minutes": {
            rung: (round(_median(vals), 2) if vals else None)
            for rung, vals in ladder_rows.items()},
        "books": books,
        "stale": {
            "events_with_a_stale_book": stale_events,
            "share": round(stale_events / len(usable), 4),
            "median_window_minutes": (round(_median(stale_minutes), 2)
                                      if stale_minutes else None),
            "median_observations_while_stale": (
                _median(stale_observations) if stale_observations else None),
        },
        "note": ("descriptive only -- no entry here is an edge claim; see "
                 "docs/RESEARCH_V3_TIMING.md"),
    }


def leadership_stability(measured, *, halves=None) -> dict:
    """Is the first-mover ranking the same in the first and second half?

    The caller passes events in time order (or explicit halves). Stability
    is the overlap of the top-3 first movers across halves -- a crude,
    honest measure: 3/3 is stable leadership, 0/3 says the "leader" was an
    artifact of the sample.
    """
    usable = [m for m in measured if m and m.get("excluded") is None]
    if halves is None:
        middle = len(usable) // 2
        halves = (usable[:middle], usable[middle:])
    first, second = halves
    if len(first) < MIN_EVENTS // 2 or len(second) < MIN_EVENTS // 2:
        return {"skipped": "one half is under the floor; stability unjudged"}

    def top3(events):
        counts = {}
        for event in events:
            for book in event.get("first_movers", []):
                counts[book] = counts.get(book, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [book for book, _ in ranked[:3]]

    top_first, top_second = top3(first), top3(second)
    overlap = len(set(top_first) & set(top_second))
    return {"first_half_top3": top_first, "second_half_top3": top_second,
            "overlap": overlap,
            "note": "3 = stable leadership, 0 = sample artifact"}
