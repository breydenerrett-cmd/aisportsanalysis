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
| **H1** IL placement → team down | 28 | 9 | 9 | 0.556 | [0.222, 0.889] | UNDETERMINED |
| **H2** IL activation → team up | 44 | 32 | 32 | 0.438 | [0.207, 0.676] | UNDETERMINED |

Three tests, Bonferroni-corrected, clustered by game. Nothing clears
anything. Only H2 reaches the `n >= 25` floor, and its interval straddles
chance.

### A join was fixed between the first run and this table

`_game_sides` and `_first_pitch` read `data/historical/mlb_results.csv`,
which holds only **settled** games and therefore lags the event ledger. 41
game_pks carrying events were absent from it, and **every one of them was
present in the capture's own `event_game_map.jsonl`** — those events were
being dropped by a broken join, not by the pre-registered population rule.
Both helpers now fall back to the event map (translating its full club names
back through `src/data/labels.py`, skipping any club that table does not
know rather than guessing a code), with settled results still winning where
they exist.

**This is a defect fix, not a rescue.** The pre-registration defines the
population as every event whose game is on a captured board with quotes on
both sides; a game missing from a settled-results CSV was never part of that
definition. The criterion, the signs, the window, the correction and the
decision rule are all untouched.

And the reason it can be trusted: **not one verdict changed.** H1 went from
6 usable to 9, H2 from 23 to 32, and all three hypotheses were UNDETERMINED
before the fix and are UNDETERMINED after it. The control is unaffected —
its losses are structural, not clerical. The first-run numbers are recorded
above in this same paragraph rather than quietly replaced.

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
  totals board opens                     median 24.9h
  temperature change (control)           median 23.1h   p90 42.9h
```

**Fifty-two of a hundred and seven temperature changes arrive before any book
has priced the game.** A market that does not exist cannot react. Books open
an MLB game about a day out; weather forecasts update two days out. Of 107
signable changes, 32 had no board at all, 38 preceded the board, 2 followed
it, and 18 had no quote inside the window — leaving 17, of which 7 sat
perfectly still, because a posted total moves in half-run steps and often
just doesn't.

This is not a spending decision. The featured odds endpoint bills once for the
whole slate, so breadth is already free; the limit is that **no book has
opened the game yet.**

### H1 is starved by a defect in our own ledger, and it is a real one

```
  il_placement (H1)   median  -10.4h     <- NEGATIVE. After first pitch.
```

`src/board/events.py::transaction_events` maps a roster move to the game its
team played **on the move's own date**. A placement announced after Tuesday
night's game is therefore filed against Tuesday's game — already played —
when the game it actually affects is Wednesday's.

**Fifteen of twenty-eight IL placements are observed after first pitch of the
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

### H2 is the one that actually got measured

```
  il_activation (H2)  median  +3.7h      <- inside the priceable window
```

Activations are announced before the game, because the player has to be on the
card. **Thirty-two of forty-four were usable** — the healthiest yield of the
three by a wide margin, and the only hypothesis to clear its own `n >= 25`
floor.

Its answer is an honest UNDETERMINED: 0.438, interval [0.207, 0.676],
straddling chance. The point estimate sits *below* 0.50, which if anything
leans against the declared sign, but at n=32 the interval is far too wide to
say so and the pre-registration forbids reading a point estimate as a result.

Nothing is wrong with H2 except sample size — and, until the control passes,
its null means nothing either.

## When does this become answerable?

Power, at the Bonferroni α, for the hit rate to clear 0.50:

| true hit rate | events that must move |
|---|---|
| 0.55 | ~1,044 |
| 0.60 | ~259 |
| 0.65 | ~114 |
| 0.70 | ~63 |

H2 accrues about **3.0 usable events per day**. It has already crossed the
reporting floor; it reaches power for a *strong* effect (0.65) in roughly four
more weeks, and for a moderate one (0.60) in roughly two and a half months.

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
— is genuinely hard and needs a lineup-strength estimate.

Three things were measured before claiming it is feasible, and they qualify
the promise:

- **A baseline is reconstructable.** All 287 lineup events resolve to a
  (team, game-date) once the join above is fixed, giving **255 distinct
  posted lineups across all 30 clubs**. Of those, **165 have three or more
  prior lineups** for the same club to average against, and 225 have at
  least one. So the signable sample is ~165, not 255 — a third smaller than
  the headline, and the honest number to plan against.
- **There is real churn to sign.** A posted lineup differs from that club's
  previous one by a mean of **2.22 batters out of 9**; only 24 of 255 are
  identical. If lineups barely moved there would be nothing to predict.
- **And that is also the trap.** Most of those 2.22 are routine rotation —
  rest days, platoon splits — which the market already expects and has
  already priced. A test that scores "different from last night" as news
  will mostly be measuring the weekly rest schedule. The baseline has to
  approximate *what the market expected*, not *what happened last night*,
  and getting that wrong is the way this test fails while appearing to work.

At ~165 signable events already in hand and ~16/day accruing, a 0.60 effect
is reachable in roughly **six days** of further collection, not three months.
That is what makes it the next thing to build.

## What was NOT done, deliberately

- **The control was not re-run against over/under prices.** The posted total
  is coarse (7 of 17 events did not move it at all) and a price-based
  consensus would be more sensitive. Switching metrics *after seeing a null*
  is the rescue clause the pre-registration forbids. If it is worth doing it
  is worth pre-registering as its own test, with its own sign, in advance.
- **No window was swept, no subset promoted, no hypothesis dropped.** H1 came
  back on six events and is reported on six events.

## Instrument

`tests/test_event_direction.py` — 33 tests, and the four mutants that matter
were each confirmed to turn them red before being restored: a home/away
inversion (which would flip every transaction result while printing a
plausible number), a tie counted as a hit, peak substituted for net movement,
and a bootstrap resampling events instead of games. The clustering test failed
to catch its mutant on the first attempt and was rewritten until it did.

The join fix added four more, including that an unrecognised club name drops
out of the side mapping rather than being assigned a code, and that no two
clubs share a full name — either would put events on the wrong side of the
board, which is the same silent inversion the mutation test exists to catch.

## Honest status

- **No edge is claimed. None was found. None was ruled out either.**
- The reusable results are all diagnoses, and all three are ours to fix rather
  than facts about the market: **we collect news at hours when we hold no
  prices**, **we file roster moves against games that have already been
  played**, and **we were joining the ledger to a store that only holds
  settled games** — the last of which was fixed here and cost 41 games'
  worth of events while it stood.
- Everything here is sport-agnostic. Nothing in the probe knows about
  baseball except which store the events come from — the same test runs on a
  UFC fight week or an NFL injury report the moment those events are recorded
  with an `observed_utc`.

## Re-run, 2026-09-12 (after the join fix, 41 more games of events)

Same criterion, same instrument, nothing changed but the data.

| row | n | hit | 98.33% CI | verdict |
|---|---|---|---|---|
| CONTROL temperature -> total | 14 | 0.500 | [0.300, 0.778] | UNDETERMINED |
| H1 IL placement -> team down | 9 | 0.556 | [0.222, 0.889] | UNDETERMINED |
| H2 IL activation -> team up | 32 | 0.438 | [0.207, 0.676] | UNDETERMINED |

The positive control still did not confirm, so nothing above it is
evidence of anything. H2 crossed its n=30 floor for the first time and
the answer is the same. Structural finding unchanged: the moneyline board
opens a median 26h before first pitch and IL placements land a median
17.6h AFTER first pitch of the game they are filed against, so most of
H1 can never be measured on this feed.
