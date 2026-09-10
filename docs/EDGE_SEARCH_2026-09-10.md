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

### 2. First-five innings, where our model has its best structural case

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
