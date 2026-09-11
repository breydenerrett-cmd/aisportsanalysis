# Knowing first: the question this project had never asked

**2026-09-11.** `scripts/probe_information_edge.py`. No verdict yet — but the
question is now framed, the data is there, and two wrong answers have been
ruled out.

---

## The distinction that had been missed

Every measurement in `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md` compares **our
number** to **the market's number**. All of them come back at or below the
market.

That is a question about *modelling*. The owner named a different one:

> "being a master of knowledge... knowing if someone posted online that they
> saw Connor McGregor walking to a medical clinic a week or two before the
> fight... but the video didn't come out viral until after, like there's real
> value there."

That is an **information** edge: not a better estimate of the same facts, but
the same estimate made *earlier*, before the price reflects a fact that
already exists. **A null result on the first question says nothing about the
second**, and this project had been treating them as one thing.

## What already exists

`data/processed/information_events.jsonl` — **1,221 events**, newest minutes
old, every one graded `A` for timing precision, each stamped with
`observed_utc`: the instant *we* saw it.

| event kind | count |
|---|---|
| `transaction_relevant` | 335 |
| `weather_forecast_updated` | 315 |
| `lineup_posted` | 287 |
| `boxscore_final` | 152 |
| `umpire_assigned` | 116 |
| `lineup_changed` | 14 |
| `probable_changed` | 2 |

Fed by four watch stores polling every 15 minutes, and consumed by
`src/board/events.py`, `src/engine/glue.py` and `src/core/asof.py`. The
machinery for "know it first" was built and running. Nobody had asked whether
knowing it first is worth anything.

## What was measured, and why it does not yet answer

For every event landing on a game whose board we were capturing (618 of
1,221), how far the de-vigged consensus travelled in the two hours after —
against a control anchored at moments with no event.

**Two control designs, both wrong, and the second is the interesting one.**

**First: random instants on the same games, 3h clear of any event.** Produced
+0.62 points with an interval nowhere near zero. Then the check:

```
hours before first pitch    event anchors   median  2.9h
                            control anchors median 22.2h
```

Events cluster near first pitch — lineups post two to four hours out — and
the clearance rule pushed the control into the dead hours of the previous
day. That compares a busy board to a sleeping one and calls it news.

**Second: matched on lead time**, control anchors drawn from *other* games at
the same distance from first pitch. Closed the gap from 19.3h to 3.8h and
collapsed the control to n=45 — still unmatched, and the probe refuses to
report a number when the arms are not comparable.

**Why it collapsed is the finding.** In the three hours before first pitch,
on a game we are capturing, there is almost always an event — because that is
when lineups post. **A comparable moment with no news barely exists at that
hour.** The events are not incidental to the busy period; they *are* the busy
period.

## What would actually answer it

**Direction, not magnitude — and it sidesteps the confound entirely.**

Knowing a price will move is not bettable. Knowing *which way* is. And a
direction test does not need a quiet-hour control: if, after a scratch, the
affected team's win probability falls more often than chance, that is an edge
whether or not boards are generally busy at that hour.

That needs a per-event-kind expectation — a scratched star lowers his team's
number, a favourable umpire raises the over — which is real work and is not
attempted here.

## Honest status

- The **window** is plausible and unproven: the median event is seen ~75
  minutes before the price finishes moving, but that number is measured
  against a control that does not match.
- `lineup_changed` (n=10) and `lineup_posted` (n=255) show the largest
  movement of any kind. Suggestive of where to look; nothing more.
- **Nothing here is evidence of an edge**, and the probe is written to say so
  rather than print a number when its arms are not comparable.

The value of this document is that the question is now separated from the one
that keeps failing, and the data to answer it is already being collected every
fifteen minutes.
