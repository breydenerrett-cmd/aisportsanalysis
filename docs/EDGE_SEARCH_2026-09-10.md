# Where to look for an edge — what was tried, what it found, what is next

Written 2026-09-10 in response to a direct question: what are other systems
doing, what are they *not* doing, and what could we find that they have not.

**The headline is that no edge was found.** What was found is a way of
measuring our own model against the entire betting market thousands of times
a day without waiting for a single game to finish, and two concrete faults
it immediately exposed. That is worth more than a weak edge would have been,
and it is written up here as the actual result rather than buried under the
activity that produced it.

---

## What everyone else is doing

Roughly in order of how common:

| approach | who | our position |
|---|---|---|
| Power ratings plus situational adjustments | every public handicapper | we have a run-expectancy version of this |
| Starting-pitcher projections (FIP/xFIP/SIERA) | most | in the model, from real logs |
| Park, weather, umpire adjustments | most | captured, **not in the model** |
| Bullpen fatigue | some | captured, **not in the model** |
| Lineup-level projections | fewer | captured, **not in the model** |
| Plate-appearance-level simulation | quant shops | no |
| Market-informed models (closing line as prior) | quant shops | the card already takes the market's side |
| Closing-line value as the objective | quant shops | measured, and it is why the model demotes rather than promotes |

Nothing on that list is a secret and nothing on it is where a small operator
wins. The full-game moneyline is the most heavily priced market in the sport.

## What is structurally *less* done, and why

Three asymmetries a small operator can actually stand on. Each one is a
place where effort is unevenly distributed rather than a place where someone
is stupid.

1. **Derivative markets get less attention than the main line.** First-five
   innings, team totals, alternate lines. Several books appear to generate
   them from the main line by rule rather than repricing them.
2. **Cross-market consistency is arithmetic, not opinion.** A book's
   moneyline, run line and total are three questions about one distribution
   of runs. Checking whether its own three answers agree requires no view of
   the game at all.
3. **Publishing losers.** Almost nobody does it, and it is the whole basis
   of this product's positioning.

(3) is already the product. This document is about (2), which was built, and
(1), which is next.

---

## What was built: the consistency instrument

`src/analysis/consistency.py`. Take one book at one instant, solve its
moneyline and total for two run means, read off the run line those means
imply, and compare with the run line it is actually offering.

**It was built looking for market error and it found ours, twice.**

### First pass: a big number, killed by its own control

Run over 3,575 (book, game, instant) triples on 2026-09-09, the raw
disagreement looked bimodal and the spread between books looked large — p95
of 13.44 points.

Splitting by run-line direction showed the bimodality was our own two code
branches. Restricting the between-book comparison to instants where every
book agrees on the favourite collapsed the spread to p95 **3.49**. No
finding.

### What was underneath: our distribution is the wrong shape

The two direction clusters were **+3.57** and **−8.42** points, with
interquartile ranges about one point wide — far too tight for market
disagreement and the signature of a deterministic model property.

Final scores agreed independently: per-team run variance is **2.31× the
mean** conditional on the model's own per-game means, over 3,792 team-games,
where Poisson is 1.000 by construction. 72.7% of real games are decided by
two or more runs; independent Poissons say 61.0%.

Full account and the pre-registered test:
[`PREREG_RUN_DISPERSION.md`](PREREG_RUN_DISPERSION.md). The correction cut
run-line calibration error by 93% out of sample and was **not adopted**,
because the pre-registered stability check failed.

### Second pass: subtract our known error, look at what is left

Re-running the instrument with the overdispersed distribution (diagnostic
only, adopting nothing):

| | Poisson | overdispersed |
|---|---|---|
| disagreement, mean | +0.38 | **−2.38** |
| disagreement, sd | 5.288 | **0.933** |
| home lays the runs, median | +3.57 | −2.12 |
| home takes the runs, median | −8.42 | −2.79 |
| spread between books, same direction, p95 | 3.49 | 3.37 |

The standard deviation falls by a factor of five and the two clusters
converge. The correction explains nearly all of the disagreement.

**What remains is a uniform −2.3 points across all eleven books**, from
−2.03 (BetUS) to −2.69 (FanDuel). Eleven independent books do not make the
same mistake to within seven tenths of a point. That residual is almost
certainly ours as well, and the obvious remaining candidate is the second
assumption in the joint: the two teams' scores are modelled as
**independent**, and in a real game they are not — a pitchers' duel
suppresses both sides at once.

**So: still no market finding. A third model finding.**

The between-book spread is unchanged by the correction at about **2.1 points
median**, which is genuine book-to-book disagreement and is simply
line-shopping value on the run line — real, small, and already what the
price board measures.

---

## Why the instrument is worth keeping anyway

It is a **feedback loop that does not need games to finish.**

Every other check in this repo waits for settlement: a pick graded tomorrow,
a hypothesis waiting on 60 games, a falsification battery needing 30
selections per system. This one produces thousands of independent readings
of our distribution's shape *per day*, from a market that has already priced
every game, with no outcome involved and therefore no variance from luck.

That is the difference between measuring a model change in a fortnight and
measuring it in an afternoon. It found two model faults in one session that
settled results would have taken a month to surface.

**It is a calibration instrument, not a bet-finder, and it should be
described that way.** The temptation to read a disagreement as an
opportunity is exactly the 2026-09-09 incident's shape, and the first pass
here demonstrates how easily a control turns a headline into nothing.

---

## What is next, in order

### 1. Correlation between the two teams' scores

The residual −2.3 points names its own suspect. Measurable directly from
2,153 final scores: the correlation between away and home runs in the same
game, against the zero our joint assumes. If it is materially negative, the
joint needs it, and the consistency instrument will say immediately whether
adding it explains the residual.

**This is the highest-value next measurement** and it costs one probe.

### 1a. Correlation — RULED OUT, 2026-09-10

Residual correlation between the two clubs' runs, conditional on the model's
own per-game means: **−0.0203 over 1,896 games, z = −0.88.** Independence is
fine. Do not add a correlation term.

### 1b. The de-vig method — RULED OUT, and it validated something

The next suspect was the de-vig. Proportional splitting assumes a book takes
the same relative margin on both sides, which is known to be wrong on an
asymmetric market like a −1.5 run line — and proportional is what
`src/analysis/prices.py` uses for **every number this product publishes**,
so an answer here reached much further than one probe.

All four methods, same games, same distribution, residual disagreement:

| method | mean | sd |
|---|---|---|
| **proportional** | **−2.38** | **0.933** |
| shin | −2.77 | 0.958 |
| additive | −2.77 | 0.958 |
| power | −2.97 | 1.080 |

**Proportional is the best of the four**, and by a clear margin. The
hypothesis is dead, and the unexpected win is that the de-vig this product
already uses is now validated against an independent criterion — the one
that makes the books' own boards most internally self-consistent, measured
over 3,575 triples. That was never checked before; it was chosen as the
simplest rule.

**Three suspects, three ruled out.** The remaining uniform −2.3 points is
most likely the residual shape error of a single-parameter negative binomial
— small, uniform, and not worth chasing ahead of the things below.

### 1b. The bullpen — DONE, 2026-09-10

Replaced the whole-season stand-in with a real relief-only rate. Measured
both ways and both are in [`THE_CARD.md`](THE_CARD.md): **+0.00216 nats** on
a window fixed before running, **−0.00034** over the full season
walk-forward, the difference explained by thin April samples. The
pre-specified window is the one that counts and the other number is printed
at the same size.

### 2. First-five innings — TESTED AND REFUTED, 2026-09-10

**The argument was wrong. Drop the direction.**

It was blocked on data for most of the day — the boxscore store carried a
first-five result for 111 of 1,896 games — so the season was backfilled
(free, MLB API, no odds credits) and the probe re-run on **894 decisive
first-five games**.

| outcome | model | base rate | gain |
|---|---|---|---|
| full game | 0.68737 | 0.69232 | **+0.00495** |
| first five | 0.69038 | 0.68990 | **−0.00048** |

Over nine innings the model beats a base rate. **Over five it is worse than
knowing nothing.** That is the opposite of the prediction.

**The obvious confound is ruled out.** The probe builds its F5 line by
scaling offence to five ninths, which assumes runs spread evenly across
innings — they do not, the first inning scores more than the fourth. If
those means were biased, this would be measuring the construction rather
than the model. They are not: predicted first-five total **4.914** against
an observed **4.991**, a bias of −0.077 runs over ~1,000 games. The probe
now refuses a verdict at all if that bias exceeds 0.20.

**What the negative actually tells us**, and it is worth more than the
hypothesis was: the model's (small) predictive value is **not** coming from
its starting-pitcher component. If it were, isolating the innings the
starter throws would sharpen it. It comes from the team-level scoring rates,
which apply across all nine.

That reframes the whole "where to look" question. The starter features are
real, carefully built, point-in-time — and on this evidence they are not
what makes the model work. The next thing to measure is which component
carries the +0.00495, by ablation, rather than which market to point the
existing model at.

The argument that failed, recorded so it is not re-derived from scratch in
three months:

The argument is specific rather than hopeful:

- Our model's strongest input is **starting-pitcher quality**, from real
  per-start logs.
- Its weakest is the bullpen — `bullpen_rate` is currently the team's whole
  season allowance, which includes the starters.
- **First-five innings removes the bullpen almost entirely.**
- F5 markets are quoted by fewer books and priced with less attention.

So the market where our model is least handicapped is also the market that
is least efficiently priced. We already capture `h2h_1st_5_innings`,
`totals_1st_5_innings` and `spreads_1st_5_innings` daily.

The same consistency instrument extends here and gets sharper: a book's F5
line should be consistent with its full-game line under any sensible innings
split. A book deriving F5 by a fixed rule is wrong on exactly the unusual
games — a dominant starter in front of a poor bullpen, or the reverse.

### 3. The three inputs already captured and not used

Park, weather, and posted lineups all reach the dossier and none reaches
`run_means`. Bullpen workload is captured and stands in as a season average.
Each is a known, measurable omission rather than a hope.

`docs/THE_CARD.md` lists these in order of expected size; the bullpen rate
is first.

---

## What this search did not find, stated plainly

- No market inefficiency.
- No basis for the card to rank by model disagreement. That remains
  forbidden for the reason in `THE_CARD.md`: the model beats a home-field
  base rate by 0.0012 nats on the moneyline.
- No reason to publish totals.
- Nothing that changes what the front page is allowed to claim.

The card still takes the market's side, uses our model only for agreement,
and promises a frozen graded pick rather than a winning one.
