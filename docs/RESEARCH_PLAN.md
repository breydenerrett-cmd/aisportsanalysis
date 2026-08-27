# Research plan

**Written 27 Aug 2026.** What to study, in what order, and — the part that decides the
order — **what can be answered with data already in hand versus what is blocked**.

Most research plans fail by listing interesting questions. The useful axis is
availability: a question answerable today with free data should be answered today, and
a question that needs a purchase or needs a season to pass should be identified as such
before any effort goes into it.

## The discipline that applies to every question below

1. **Write the hypothesis and the threshold down before running the query.** Every
   threshold in the scanner is pre-registered and asserted in a test, so a later quiet
   tweak toward whatever would have won fails a test rather than passing as a diff
   nobody reads. Anything found here inherits that rule.
2. **A result measured without odds is a statement about baseball, not about betting.**
   Predicting first-five runs is not the same as beating a line, and the gap between
   them is the bookmaker's entire business.
3. **Never re-cut a split that has been looked at.** The 2025 holdout is burned and
   declared so in `docs/TEST_SPLIT_STATUS.md`. The only genuinely sealed evidence is
   games that have not been played.

---

## Tier 1 — Answerable now, free, no purchase

### Q1. Do starter pairs carry information about first-five runs? *(started)*

**Method.** Point-in-time combined starter FIP against actual first-five runs, over
completed regular-season games.

**Measured, 953 games, 1 June – 14 August 2026** (799 with both starters past the
20-inning threshold):

| First-five runs | Value |
|---|---|
| Mean | 5.06 |
| Median | 5 |
| Std dev | 3.34 |
| Over 4.5 | 50.5% |

The market's standard 4.5 line sits almost exactly on the coin flip, which is a good
sign the books have the centre right and a warning about how much room there is.

By combined starter FIP, split into quarters:

| Quartile | Combined FIP | Mean F5 runs | Over 4.5 |
|---|---|---|---|
| Best 25% | 6.48 | 4.50 | 45.7% |
| Second | 7.62 | 5.15 | 48.7% |
| Third | 8.50 | 4.97 | 50.8% |
| Worst 25% | 9.89 | 5.48 | 54.5% |

Correlation is **+0.075** — small, but the gradient is monotone across the extremes and
worth 8.8 points of over-rate between the best and worst quarters.

**The honest caveat, which is large.** This compares every game against a *fixed* 4.5.
Books do not post a fixed line; they post 3.5 on the good matchups and 5.5 on the bad
ones, and the entire quartile gradient may be exactly what that line movement already
prices. **This measurement cannot distinguish "starters predict runs" from "starters
predict the line".** It establishes that the signal exists in the outcome, nothing more.

**What settles it:** posted first-five totals, per game. Blocked (see Tier 2).

### Q2. What does the scanner's own flag set look like on first-five runs? *(answered — the pre-registration was wrong)*

**Pre-registered before running:** *"the flag set should skew toward the low-scoring end
if the routing logic is sound, because a flagged game is one with a real starter
advantage on one side."*

**Result, 953 completed games, 79 clearing the talent bar:**

| | n | Mean F5 runs | Over 4.5 |
|---|---|---|---|
| Candidates | 79 | 4.99 | 50.6% |
| Everything else | 874 | 5.07 | 50.5% |

Those are the same number. **The scanner's talent bar carries no information about
first-five run totals at all.** The prediction was wrong, and it was wrong in the
direction that costs something: the routing argument was built for the totals market.

What the talent bar *does* appear to track is **who leads**. The candidate side led
through five in **37 of 61 decided games (60.7%)**, with 18 ties. That is 61 games, and
these are favourites — a price would very likely have said something similar. It is a
direction to test, not a result.

**Consequence, applied immediately.** The scanner's market constant was renamed from
`first_five_totals` to `first_five`, and it screens the first-five **moneyline** — which
is what it was already doing, and now what it says it does. Leaving the name would have
quietly asserted a link between a talent gap and a run total that the data does not
show.

**This does not mean the named market is dead.** It means a *talent-gap* signal is the
wrong input to it. First-five run totals may well be predictable from park, weather,
lineup quality and bullpen usage — none of which the scanner looks at, and one of which
(weather) is already collected and unused. That is Phase 1 work, and it is now clear it
needs its own model rather than a reroute of this one.

### Q3. Do the pre-registered thresholds sit anywhere sensible?

Not "do they win" — that is Tier 3 and must not be answered here. The question is
descriptive: at a full run of FIP and a run per game of differential, the scanner fires
on 10.2% of games (≈1.4/day) before the market screen. Does moving each threshold change
that rate smoothly, or is 1.00 sitting on a cliff?

A threshold on a cliff is fragile for reasons that have nothing to do with whether it is
profitable, and finding that out is not tuning — provided the sensitivity is measured
against **fire rate**, never against **results**.

### Q4. How often, and how early, do games diverge from their priors?

Groundwork for live betting, answerable entirely on historical linescores. If a team
expected to score is held scoreless through two, how much does that shift the rest of
the game? This is the empirical content of *"statistics that just don't align with
previous history"*, and it can be studied a full phase before any live infrastructure
is built.

---

## Tier 2 — Blocked on the $59 for historical odds

These are not "nice to have with odds". They are the questions that **cannot be
approached at all** without them.

- **Q5. Does the market screen do anything?** It is one of the scanner's three
  suppressions and the one carrying *"advantages other people aren't finding"*. With no
  historical prices it has never run on a single past game. 10.2% is an upper bound on
  the fire rate and the true rate is unknown.
- **Q6. Is Q1's gradient already in the line?** The decisive follow-up, and unanswerable
  without posted totals.
- **Q7. Where is the first-five line relative to the full-game line?** Measured live on
  two games, first-five prices came in *shorter* than full-game prices. Two games is an
  anecdote. Three seasons is a finding.
- **Q8. Is 0.65 the right screen?** And relatedly, whether the same number should apply
  to a conditional first-five price and an unconditional full-game one — currently
  flagged as a known open question rather than a validated choice.

**Recommendation: buy them.** Not for the model, which was the original justification —
for the scanner, where four separate questions are stopped dead. At $59 once for three
seasons, it is the cheapest unblocking available and there is nothing else in the
project it competes with.

---

## Tier 3 — Only answerable forward, and only by waiting

No amount of work shortens these. They are why the flag log started on 27 August.

- **Q9. Does a flagged side beat the price it was flagged at?** The scanner's actual
  hypothesis. 200 decided flags at roughly one a day: most of a season.
- **Q10. Does the scanner beat the model?** Both log to `evidence/`, both grade forward.
  If the demoted logistic regression matches the scanner, the scanner is finding nothing
  a model could not, and that is worth knowing.
- **Q11. Does live divergence carry information the pre-game priors did not?** Requires
  Phase 4 built and then a season of it.

## What not to research

Stated so the temptation is named rather than resisted repeatedly:

- **Do not tune thresholds against settled flags.** A threshold fitted to the results it
  is being tested on stops being a hypothesis and becomes a description of them. If the
  scanner fails, it fails, and the finding is that the thresholds were wrong.
- **Do not re-evaluate the 2025 test split.** Burned, four evaluations, declared.
- **Do not research staking or bankroll growth.** Both presuppose an edge that has not
  been demonstrated, and modelling returns on an unproven edge is the most reliable way
  to start believing in one.
