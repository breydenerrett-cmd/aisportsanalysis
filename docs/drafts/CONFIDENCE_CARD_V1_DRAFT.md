# DRAFT pre-registration: CONFIDENCE_CARD_V1 (not registered, not live)

**Status: DRAFT ONLY.** This is a discussion document, not a registration.
No rule id exists, no code exists, no pick has ever been produced under this
name. It exists to turn the owner's 2026-09-21 thesis into a rule concrete
enough for him to approve or correct before anyone writes it into
`docs/PREREG_*` for real. Nothing here supersedes `DAILY_CARD_BEST_BETS_V2`
(`docs/PREREG_CARD_V2.md`), `NFL_CARD_V2` (`docs/PREREG_NFL_CARD_V2.md`), or
`MLB_VALUE_SHADOW_V1` (`docs/PREREG_MLB_VALUE_SHADOW_V1.md`), all of which
keep running and keep their own records.

**Owner's thesis, verbatim (2026-09-21):** "Our entire business is finding
the best picks, not the best price... We're just going to pick the average
odds, and we're going to go with that because the actual sports bet is rock
solid... the value does not matter if the confidence is not high."

This is a real change of emphasis from `NFL_CARD_V2` and
`MLB_VALUE_SHADOW_V1`, both of which are **price-vs-consensus value rules**:
they publish a pick only when one book pays more than the market itself
thinks the bet is worth. That is the opposite operation from "pick the side
we're most sure of and take whatever the average price is." Both rules stay
registered and keep running; this draft is not an edit to either.

## a) What "confidence" means, concretely, and what produces it

A confidence-first rule needs one number per candidate: the rule's own
probability that the pick wins. Where that number comes from is different in
each sport, and the difference matters more than anything else in this
document.

### MLB

**Confidence = the repo's calibrated probability model, informed by the
market.** Concretely: `strength.model_line` (moneylines), the run model
passed through `strength.run_line_probability` (run lines), and the prop
board (`propboard.build`, total bases and hits), each read the same way
`DAILY_CARD_BEST_BETS_V2` reads them (`docs/PREREG_CARD_V2.md` section 2).
This is a real, independent number, not the market's own de-vigged price
relabeled — but it has not been shown to beat the market's number. Five
separate measurements in this repo fail to show it does, on any market or
window (`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`, quoted in
`PREREG_CARD_V2.md` section 0.2): team model +0.004 nats over a base rate,
prop model +0.0133, a paired log-loss difference whose 95% interval spans
zero, two betting probes with no finding, and a card-rule backtest with
20-to-75-point-wide intervals. The live reliability table is overconfident
in every populated bucket: 50-60% by +3.8 points (n=212), 60-70% by +4.8
(n=361), 70-80% by +18.3 (n=27) (`docs/PROP_CALIBRATION_2026-09-14.md`).

### NFL

**There is no model beyond the market today.** `src/analysis/nfl_value.py`
has no probability estimator of its own; `NFL_CARD_V2`'s own registration
says so in plain words: "V2's fair price is the market's own consensus...
V2's cards carry `has_model: false`" (`docs/PREREG_NFL_CARD_V2.md`, "No
model, so no calibration claim"). If a confidence-first NFL rule is built
today, its "confidence" number can only be the market's own de-vigged
consensus probability — there is nothing else in the repo to compute it
from.

## The honest core point

**If confidence equals the market's own consensus probability, picking the
market favourite and grading at the average price loses roughly the vig
over time.** This is not a caveat to the rule; it is arithmetic. A
sportsbook's two-way price always sums to more than 100% implied
probability — that margin is the vig, and it is what the book is paid for
taking the bet. If our "confidence" is just the market's number with the
vig removed, then on average, over enough picks, we win exactly as often as
the market's number says we should — and we pay the vig on every bet,
because we're betting at the market's own (vigged) average price, not the
de-vigged fair price. **The rule only makes money where our confidence
knows something the market doesn't** — i.e., where our number is a better
estimate of the true probability than the market's own de-vigged number is.
For MLB that is an open, currently-unproven question (the five measurements
above). For NFL there is, today, no candidate number that could be better
than the market's, because there is no other number.

**Break-even arithmetic**, decimal odds `d`, break-even probability `1/d`:

| American price | Decimal | Break-even probability |
|---|---:|---:|
| -300 | 1.333 | 75.0% |
| -200 | 1.500 | 66.7% |
| -160 | 1.625 | 61.5% |
| -150 | 1.667 | 60.0% |
| -125 | 1.800 | **55.6%** |
| -110 | 1.909 | 52.4% |
| +100 | 2.000 | 50.0% |
| +125 | 2.250 | 44.4% |
| +150 | 2.500 | 40.0% |
| +200 | 3.000 | 33.3% |

Read it as: a -125 favourite needs to win 55.6% of the time just to break
even at that price. If our "confidence" is the market's own number, a
favourite's market-implied win probability is *already* very close to that
break-even line by construction (that's what the vig is), so betting every
"high confidence" favourite at the average price is, on average, a
structural small loser — not because the favourite is unlikely to win (it
usually does), but because the price already charges for that likelihood
plus the house's cut. The same arithmetic is why the -200-or-worse rule
exists at all: at -200 you need to win two times out of three just to
break even, and the closer confidence sits to the market's own number, the
harder that bar is to clear at a price this short.

## b) The -200 cap

Unchanged from every other rule in this repo. No selection priced at -200
or worse is ever a candidate, in any market, any sport. -199 passes, -200
does not (`docs/PREREG_NFL_CARD_V2.md` rule 2; `docs/PREREG_MLB_VALUE_SHADOW_V1.md`
rule 10). This is a standing owner ruling, not something this draft
proposes — it is restated here because a confidence-first rule with no
price filter would happily publish -600 "high confidence" favourites, which
is exactly what the cap exists to stop.

## c) Grading: consensus average price at lock, not best-of-book

This is the one place this draft actually changes how a LINEHOUND rule
works, and it is the direct implementation of "we're just going to pick the
average odds." Every other live rule (`DAILY_CARD_BEST_BETS_V2`,
`NFL_CARD_V2`, `MLB_VALUE_SHADOW_V1`) either shows the best available price
across books, or compares one book's price to a leave-one-book-out
consensus of the others in order to find a mispriced book. This rule does
neither: it takes the **full multi-book de-vigged consensus at the lock
instant** as both the confidence number (informed by the model, MLB only)
and the price the pick is graded at. That is also what
`docs/PER_SPORT_PRICING_PLAN.md` section 2 already specifies for the
pricing step-up's own reference price ("each pick is graded at the market
consensus price at publication, not the best of about 11 books the card
shows today") — this draft reuses that same choice rather than inventing a
third convention.

Concretely: at lock, take every book's price on the selection, de-vig each
one (proportional, Shin, power — the same three methods `NFL_CARD_V2` and
`MLB_VALUE_SHADOW_V1` already use, `src/core/odds.py` `devig_two_way`),
average across books and methods, and grade the pick at that number
converted back to American odds. A minimum book count applies (proposed: 5,
matching `NFL_CARD_V2`'s and most `MLB_VALUE_SHADOW_V1` arms' existing
"other books" minimum) — below it, the average is not published.

## d) Markets in scope, per sport

Per the owner's own standing rules, restated here rather than re-derived:

- **MLB:** player props — **total bases** and **total hits**, over and
  under, plus **run lines** (`spreads`, normally ±1.5). Not moneylines —
  the owner's 2026-09-20 direction for MLB is "player props... total bases
  and total hits, then run lines" (quoted in
  `docs/PREREG_MLB_VALUE_SHADOW_V1.md`, "Why"). Game totals are not in the
  owner's MLB list and are not proposed here.
- **NFL:** spreads, totals (game and, once built, team totals) and player
  props. **Team totals and player props do not exist in the capture today**
  — `docs/PREREG_NFL_CARD_V2.md`'s own "Known limits" says the capture's
  featured call is "moneyline, spread and total only." A confidence-first
  NFL rule can launch on spreads and game totals; team totals and props are
  a build item, not a config flip.

## e) Picks per day, and lock times

Proposed, not registered — owner confirmation needed (see (g)):

- **MLB:** at most **3 picks a day**, matching the existing card's own
  "always show 3" floor and 10-entry ceiling design
  (`docs/PREREG_CARD_V2.md` section 6), so this rule's daily footprint is
  familiar rather than a new shape. Lock: props are judgeable "essentially
  only after the gate capture" — 2 hours to first pitch, after lineups for
  about 85% of games (`docs/PREREG_MLB_VALUE_SHADOW_V1.md`, "Known
  limits"); run lines lock the same 4-hour-to-first-pitch window
  `MLB_VALUE_SHADOW_V1` already uses.
- **NFL:** at most **5 picks a date**, matching `NFL_CARD_V2`'s own cap
  (`docs/PREREG_NFL_CARD_V2.md` rule 6). Lock: **4 hours before kickoff**,
  same as `NFL_CARD_V2`, for the same reason — a later publish must not add
  a second, contradictory pick on a game whose price has since moved.

## f) The evidence gate for calling this "working"

Reusing the standard already written for the sport/bet-type scoreboard
(`docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md` section 4), not
inventing a new one:

- **Sample size.** Section 4.2's table gives 50%/80%-power sample sizes by
  price and edge size. At a typical -125 (near the table's -110 row), a
  modest 3% edge needs roughly **3,880 picks at 50% power, ~7,900 at 80%
  power**; at -200 (the table's own -246 row is the closest priced
  example), a 3% edge needs roughly **1,740 / 3,550**. Read this as "how
  many picks before a real edge of this size would be *caught*," not as a
  number that proves anything by itself — a sample this size that comes
  back positive is still one data point.
- **Multiple comparisons.** Section 4.3: checking several (sport,
  bet-type) cells at once means some will look great by chance even with
  no real edge — the same trap that already produced "0 of 8,811 EvoLab
  strategies survived." A Bonferroni-style correction applies before any
  cell here is called "working," roughly doubling the sample needed once a
  handful of cells (MLB props, MLB run line, NFL spread, NFL total) are
  tracked side by side.
- **The pricing ladder itself.** `docs/PER_SPORT_PRICING_PLAN.md` section 2
  and `docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md` section 4.5:
  **500+ eligible graded picks in the trailing 6 months**, with the
  one-sided 95% block-bootstrap lower bound on units/pick staying **above
  zero in two consecutive quarters**, before any customer-facing pricing
  decision is made. Below 500, the answer is "too early," not "no."
- **What "working" is not.** A positive raw win rate on favourites proves
  nothing on its own — see `docs/PREREG_CARD_V2.md` section 0's own finding
  that on one design board the market's own number already cleared the
  best available price on 0 of 82 game-market sides. The gate is the
  bootstrapped ROI lower bound, never the win-loss record alone.

## g) Numbers the owner must confirm before this is registered

Nothing above is registered. Each of these needs Brey's own answer, dated,
before a real `docs/PREREG_CONFIDENCE_CARD_V1.md` is written:

1. **Does the NFL leg run at all**, given (a) above: NFL's "confidence"
   today can only be the market's own number, which the arithmetic in the
   honest-core-point section says loses roughly the vig by construction. Is
   NFL confidence-first shadow-only until a real NFL model exists, or does
   it publish anyway on the theory that "the sports bet is rock solid" is a
   judgment call the market doesn't fully price?
2. **The minimum book count for the consensus average** (proposed: 5 —
   confirm or change).
3. **The de-vig methods and how they're combined** into one average
   (proposed: mean of proportional/Shin/power, matching existing rules —
   confirm or change).
4. **Picks per day per sport** (proposed: 3 MLB, 5 NFL — confirm or
   change).
5. **Lock times** (proposed: MLB props at the post-lineup gate capture,
   ~2h to first pitch; MLB run lines and NFL at 4h to game start — confirm
   or change).
6. **MLB market scope**: props and run lines only, no moneylines, no game
   totals — confirm this matches "total bases and total hits, then run
   lines" or state the intended priority differently.
7. **Whether a minimum confidence floor applies at all**, and if so what it
   is — the owner's thesis says price doesn't matter if confidence is high,
   but says nothing about *how* high "high" has to be. A rule with no floor
   publishes -190 "confidence 51%" picks, which is a coin flip at a price
   that already charges for being one.
8. **Shadow-first or public-first.** Every other rule in this repo that
   changes the actual bet-selection logic (not just its price filter) has
   run shadow before any customer sees it (`MLB_VALUE_SHADOW_V1`'s own
   registration). Does this rule launch the same way?
9. **The 500-pick / two-quarter gate itself** (f, above): accept as written,
   or set different numbers for this specific rule.
