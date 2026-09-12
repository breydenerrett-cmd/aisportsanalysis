# Pre-registration: when a batter is posted higher than his norm, does the market shorten his Over?

Registered 2026-09-12, before any post-lineup batter-prop quote existed in
this repo. The capture gate (`src/pipeline/batter_props.CAPTURE_LEAD_MINUTES
= 120`) landed at 02:48 UTC on 09-12, after every window for the 09-11
slate had closed; the first quotes it is allowed to take arrive the evening
of 09-12 UTC. This document is committed before they do. Reader:
`scripts/probe_slot_prop.py`. Registry id
`V7:lineup_slot_prop_repricing:batter_hits`.

## The question

A hitter who moves up the order gets more plate appearances. That is
measured, not assumed: `playerprops.SLOT_PLATE_APPEARANCES` runs from 4.47
leading off to 3.46 batting ninth, a 29% difference. More plate appearances
make "at least one hit" more likely. So when a batter is posted well above
his usual slot, his hits Over should be more likely than it usually is for
him, and a market that reads lineups should price that in.

Does it? This is a question about the market, not about us. It is the
first thing the T-2h capture exists to answer, and it is written down
before the capture has produced a row.

## Why this version and not the timing version

The obvious test is "does the price move after the lineup posts". That
needs a quote from BEFORE the posting. We do not hold one and will not:
the gate takes quotes only inside two hours of first pitch, and lineups
post a median 3.0 hours before it (`scripts/probe_event_direction.py`,
n=317 postings). Every quote we will ever hold under the gate is
post-lineup.

A baseline capture at roughly six hours out would fix that at about one
extra credit per game per night. That is a spend decision and it is the
owner's, so it is not made here. This test needs no extra spend, reads the
quotes the gate already takes, and is the honest first question.

## Population

One row per (batter, slate date, market, line) with all of:

- a quote observed at or after the game's lineup posting time
  (`lineups.jsonl`'s `observed_utc` for that game) and no more than 120
  minutes before first pitch — the post-lineup window;
- at least two books quoting both sides of that line at their newest
  quote (`propboard.fair_and_best`), so a de-vigged Over exists;
- a batting slot for the batter from that game's posted lineup;
- at least 10 prior posted lineups for the batter in the store;
- at least 3 prior nights with a post-lineup fair Over for the same
  batter, market and line (the baseline).

Primary market: `batter_hits`. Secondary, declared here so it cannot be
added later and decides nothing: `batter_total_bases`. Regular season
only; postseason lineups and prop boards behave differently and are
excluded.

## Definitions, fixed before any row exists

- **norm slot** — the median of the batter's slot over his last 10 posted
  lineups before the date.
- **Δslot** — norm slot minus tonight's slot. Positive means he moved up.
- **groups** — UP: Δslot ≥ +2. FLAT: Δslot = 0. DOWN: Δslot ≤ −2. Rows
  with |Δslot| = 1 are in no group and are not used.
- **fair Over** — the de-vigged Over probability from the books' newest
  post-lineup quotes for that line.
- **baseline** — the median fair Over over the batter's previous
  post-lineup nights with the same market and line (at least 3).
- **Δfair** — fair Over tonight minus baseline.

A batter compared with himself, at the same line. Nothing here uses our
own probability model, so nothing here can be wrong because the model is.

## The sign, fixed

**H1:** mean Δfair(UP) − mean Δfair(FLAT) > 0.

**Mirror, secondary, declared now:** mean Δfair(DOWN) − mean Δfair(FLAT)
< 0. It is reported; it decides nothing.

## The decision rule

Point estimate: the difference of the two group means. Interval: the
percentile interval from 2,000 bootstrap draws that resample slate DATES
with replacement, because a night's quotes share a board and are not
independent. Seed 20260912. α is 0.05 divided by the number of hypotheses
in `data/research/alpha_registry.jsonl` when the read happens (42 at
registration, so 0.00119) — the family-wise bar this programme holds
every hypothesis to, not the kinder one. The interval is two-sided at
1−α; **CONFIRMED** when its lower bound is above zero; **NOT SUPPORTED**
otherwise. No threshold here moves after the first read.

## The positive control, and what a null is worth without it

The instrument has to be able to see plate-appearance effects at all.
On the same nights, in the same market at its most common line, the fair
Over of batters posted in slots 1–2 must exceed that of batters in slots
8–9, by the same interval method at the same α. That effect is certain
to exist in the market; if this instrument cannot see it, it cannot see
anything, and every row above is **UNDETERMINED**. A null on H1 with a
failed control is not evidence of absence and will not be described as
one.

## Floors and the stopping rule

The read happens once, when UP and FLAT each hold at least 150 rows and
the two control groups each hold at least 100. Until then the reader
prints PENDING with the counts and nothing else — no interval, no
direction. There is no early look and no continuation after the read.

If the 2026 regular season ends before the floors are met, the read waits
for 2027 with the same floors. The floors are not lowered because the
season was short.

## What a result can and cannot say

A confirmed H1 says the market re-prices a batter's hits Over when his
slot rises relative to his own recent history. It says nothing about
beating that price and nothing about when the re-pricing happens
relative to the posting — that is the timing test above, which needs the
baseline capture. A null says the market does not, within the power this
instrument has, which the control bounds.

Nothing here is promoted to a customer surface on the strength of one
read. If it confirms, it is a fact about the market that the prop board
can state; it is not an edge.

## Secondary, descriptive, declared now

- The same read on `batter_total_bases`.
- The dose: mean Δfair by Δslot in {+2, +3, ≥+4}.
- The UP group's mean Δfair by whether the batter's baseline nights were
  all at a lower slot than tonight.

None decides anything.
