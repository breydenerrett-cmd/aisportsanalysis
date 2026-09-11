# Direction test: the answer is "this instrument cannot see yet", and it can say why

**2026-09-11.** `scripts/probe_event_direction.py`, against the criterion in
`docs/PREREG_EVENT_DIRECTION.md`, committed before the probe was written.

**Result: all three primary hypotheses UNDETERMINED, and the positive control
did not confirm — so by the pre-registered rule, none of the nulls is evidence
of anything.**

That sounds like the sixth null in a row. It is not, and the difference is the
point of this document.

---

## What ran

| | events that carry a direction | usable | moved | hit rate | 98.33% CI | verdict |
|---|---|---|---|---|---|---|
| **CONTROL** temp → total | 107 | 17 | 10 | 0.500 | [0.222, 0.857] | UNDETERMINED |
| **H1** IL placement → team down | 24 | 6 | 6 | 0.500 | [0.000, 1.000] | UNDETERMINED |
| **H2** IL activation → team up | 35 | 23 | 23 | 0.435 | [0.143, 0.700] | UNDETERMINED |

Three tests, Bonferroni-corrected, clustered by game. Nothing clears
anything. The floor of `n >= 25` is not reached by any of them.

## Why the control is the whole story

Five nulls were already on this repo's record and **not one could tell "there
is no effect" from "the instrument is blind."** So this test carried a
hypothesis that had to come back true: warm air is thinner, the ball carries,
a rising forecast temperature raises a total. Public to every book, no claim
of edge, and about as well-established as anything in baseball.

It came back 0.500 on ten events.

The pre-registration says what that means, and the probe prints it in those
words: **no null beside a failed control is evidence of absence.** H1 and H2
are not "no effect found." They are "not looked at yet."

**This is the first null in this repo that knows what it does not know.**

## And then it says why — which is the useful part

The probe reports where every event went. The three hypotheses failed for
three *different* reasons, and only one of them is a dead end.

### The control is starved structurally. Polling harder cannot fix it.

```
                                hours before first pitch
  totals board opens                     median 23.4h
  temperature change (control)           median 27.0h   p90 42.0h
```

**Thirty of fifty-six temperature changes arrive before any book has priced
the game.** A market that does not exist cannot react. Books open an MLB game
about a day out; weather forecasts update two days out. Of 107 signable
changes, 32 had no board at all, 38 preceded the board, 2 followed it, and 18
had no quote inside the window — leaving 17, of which 7 sat perfectly still,
because a posted total moves in half-run steps and often just doesn't.

This is not a spending decision. The featured odds endpoint bills once for the
whole slate, so breadth is already free; the limit is that **no book has
opened the game yet.**

### H1 is starved by a defect in our own ledger, and it is a real one

```
  il_placement (H1)   median  -18.5h     <- NEGATIVE. After first pitch.
```

`src/board/events.py::transaction_events` maps a roster move to the game its
team played **on the move's own date**. A placement announced after Tuesday
night's game is therefore filed against Tuesday's game — already played —
when the game it actually affects is Wednesday's.

**Fourteen of twenty-four IL placements are observed after first pitch of the
game they are attached to.**

This is *not* a leakage bug: `src/core/asof.py` filters on
`observed_utc <= T`, so a late event can never reach a pre-game query. It is
the opposite — **information loss.** The roster move is filed where nothing
can read it, and the game it genuinely affects never learns of it.

The fix is to attach the move to the team's next game at or after
`observed_utc`. That needs a **persisted forward schedule**, which does not
exist on disk: `data/historical/mlb_results.csv` stops at yesterday and
`boxscores_2026.jsonl` holds only played games. So the correction is a real
piece of work, not a one-line change, and it is recorded here rather than
half-done.

### H2 is the one that is merely early

```
  il_activation (H2)  median  +4.1h      <- inside the priceable window
```

Activations are announced before the game, because the player has to be on the
card. Twenty-three of thirty-five were usable — the healthiest yield of the
three — and the hypothesis is **two events short of its own reporting floor.**

Nothing is wrong with H2 except the calendar.

## When does this become answerable?

Power, at the Bonferroni α, for the hit rate to clear 0.50:

| true hit rate | events that must move |
|---|---|
| 0.55 | ~1,044 |
| 0.60 | ~259 |
| 0.65 | ~114 |
| 0.70 | ~63 |

H2 accrues about **2.2 usable events per day**. It crosses the reporting floor
within days; it reaches power for a *strong* effect (0.65) in roughly six
weeks, and for a moderate one (0.60) in roughly three and a half months.

**A 0.55 edge is out of reach in this sport this season, and would be worth a
great deal.** That is worth knowing before more is spent chasing it.

## The measurement nobody asked for, that changes what to build next

The one event kind with **both** a large sample and the right timing is the
one with no hypothesis attached to it:

```
  lineup_posted    n=255 usable    median 2.9h before first pitch
```

255 usable events, accruing at ~27/day, landing squarely inside the window
where a market exists and is liquid. It is reported here as unsigned —
0.537 [0.441, 0.630] on "did the home number rise", which is noise by
construction, because no direction was declared for it.

**That is where the next pre-registration goes.** Signing a posted lineup —
is this batting order stronger or weaker than the one the price was built on
— is genuinely hard and needs a lineup-strength estimate. But it is the only
place in this data where the sample and the timing are both already there, and
at 27 events a day it reaches power for a 0.60 effect in **ten days**, not
three months.

## What was NOT done, deliberately

- **The control was not re-run against over/under prices.** The posted total
  is coarse (7 of 17 events did not move it at all) and a price-based
  consensus would be more sensitive. Switching metrics *after seeing a null*
  is the rescue clause the pre-registration forbids. If it is worth doing it
  is worth pre-registering as its own test, with its own sign, in advance.
- **No window was swept, no subset promoted, no hypothesis dropped.** H1 came
  back on six events and is reported on six events.

## Instrument

`tests/test_event_direction.py` — 29 tests, and the four mutants that matter
were each confirmed to turn them red before being restored: a home/away
inversion (which would flip every transaction result while printing a
plausible number), a tie counted as a hit, peak substituted for net movement,
and a bootstrap resampling events instead of games. The clustering test failed
to catch its mutant on the first attempt and was rewritten until it did.

## Honest status

- **No edge is claimed. None was found. None was ruled out either.**
- The single reusable result is the diagnosis: **we collect news at hours when
  we hold no prices, and we file roster moves against games that have already
  been played.** Both are ours to fix; neither is about the market.
- Everything here is sport-agnostic. Nothing in the probe knows about
  baseball except which store the events come from — the same test runs on a
  UFC fight week or an NFL injury report the moment those events are recorded
  with an `observed_utc`.
