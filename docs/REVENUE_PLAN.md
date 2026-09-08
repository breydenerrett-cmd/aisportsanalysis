# Getting paid for this — the plan, and the one thing that would kill it

Written 2026-09-08 by the local Parent, after correcting defect E-1 and
recomputing the honest record.

## The strategic fact everything else follows from

There are two products in this repo, and they have different truth
requirements:

| | What it claims | Can we sell it today? |
|---|---|---|
| **The price checker** | "The number you are about to take is worse than eleven books' de-vigged consensus." | **Yes.** Deterministic, verifiable in ten seconds, true regardless of whether we can predict a single game. |
| **The picks** | "Bet this side; we have an edge." | **No.** 72 forward-test bets across four days. |

The honest deduped record, all time:

    FORWARD_TEST (thesis-carrying)   72 bets  43-26-3  +15.16u  +21.05%
    CONTROL + MARKET_REFERENCE      402 bets 192-197-13 -14.45u   -3.60%

Two readings, both true:

- The nulls lose about 3.6%, which is roughly the hold. A null baseline
  that loses at the hold is a methodology working correctly. That is a
  real, quiet, good sign.
- The forward-test +21% is 72 bets over FOUR DAYS: +30.8%, +36.3%, +5.8%,
  −50.2%. At that sample a 21% ROI and a −21% ROI are both entirely
  ordinary. It is not evidence of anything yet.

**Selling picks on 72 bets is the single thing that could kill this
business.** Not because the number is bad — because it will revert, and a
subscriber who paid for an edge and met the reversion churns and tells
people. The line-shopping value does not revert. It is arithmetic.

So: **sell the tool, publish the record, gate the picks.**

## The offer that is a no-brainer today

**"Never take a bad number again."**

Not "our AI picks winners." The pitch a bettor can verify before paying:

> Paste the bet you were about to place. We price it against a de-vigged
> eleven-book consensus and tell you whether that number is fair, better,
> or costing you money — before you fire.

Why this converts where a picks product would not:

- **It is checkable in ten seconds.** They paste a real bet, they see a
  real answer, they can go look at the books themselves.
- **It is true every single night**, including the ~93% of nights where
  nothing clears the bar. A picks product has nothing to say on those
  nights. This one always does.
- **Losing 20 cents of price on every bet is a bigger, more certain leak
  than not having an edge.** A bettor placing 200 bets a year at -110
  instead of -105 gives away real money with certainty. That is the pain,
  and it is arithmetic, not a forecast.

Free tier stays three checks for life (already built). Paid at $19.99/mo
(already built) unlocks unlimited checks, the full board, and the frozen
record.

## What has to be true on the page before asking for money

Ranked by conversion impact ÷ build cost. This is the P1 queue.

### 1. The money moment (highest value, ~half a day)
Bet Check currently answers "is this price fair". It does not yet say what
the bad price COSTS. Add, on every check:

    You: -115 · Best available: -105 (LowVig, 11 books)
    That gap is $4.35 per $100. Over 200 bets a year: $87 left on the table.

One sentence, computed from numbers already on screen. That is the line
that makes someone subscribe, and it requires no new data.

### 2. Land on the checker, not the slate
`/` currently sells a story and links into the app; `/app` opens Today,
which on most nights honestly says "nothing clears the bar". That is the
right answer and the wrong first impression for a paid tool.
Make the hero's primary action **Check a bet** with the input right there,
prefilled with tonight's biggest price gap. Today stays one click away.

### 3. The record as a trust asset, not a sales claim
Publish the honest record with the sample size shouting, not whispered:

    Forward-test systems: 72 bets over 4 days. +21% ROI.
    That is far too few bets to mean anything, and we will say so until
    it isn't. Here is every call, settled, including the -50% day.

An industry of deleted screenshots makes "here is our worst day" a
differentiator. It also inoculates against the reversion.

### 4. Line-move alerts (the retention hook)
The store already captures at T-3h / T-90m / T-30m. "The number you saved
moved from -105 to -120" is a reason to keep paying past month one. Saved
bets already exist behind an invite token.

## The gate before picks are ever sold

Written down now so it cannot be relaxed later under revenue pressure:

- **300+ settled forward-test bets** (currently 72), and
- **positive closing-line value** measured against the closing consensus,
  not against our own opening price, and
- **the pre-registered evaluation gate in the research record**, unchanged.

Until all three: the record is published, never sold. No "premium picks"
tier, no upsell copy that implies one.

## Autonomous workflow — how this gets built

Order is fixed; each step is verifiable and deployable on its own.

**P0 — correctness (today, blocking).** E-1: the slate re-stakes on every
run, so 2026-09-07 displays 251 positions where 101 exist, showing −1.82%
where the truth is −10.00%. Fix the cause in the engine, dedupe the
reporting, label the affected day. No revenue work ships on top of a
number that is wrong and flattering.

**P1 — the conversion path.** Items 1–3 above, in order. Each is a
half-day, each is independently shippable, each is verified in a browser
at both widths before it is called done.

**P2 — retention.** Line-move alerts; saved bets out from behind the
invite token for paid users.

**P3 — the compounding loop.** Two things that improve on their own:
- **CLV measurement.** Every frozen decision already carries its price and
  instant; the closing board is captured. Computing closing-line value
  turns four days of noise into the one metric that predicts edge long
  before ROI does. This is the highest-value research item in the repo.
- **Market coverage.** First-five and props are captured and ranked;
  most contracts are too thin to price. More capture instants at the
  right moments widens what can honestly be checked.

## What I will not do

- Sell picks, or write copy that implies an edge, before the gate above.
- Show a ROI figure without its sample size beside it.
- Let a rollup include a day whose ledger is known to be double-counted.
- Present +21% on 72 bets as anything but noise.
