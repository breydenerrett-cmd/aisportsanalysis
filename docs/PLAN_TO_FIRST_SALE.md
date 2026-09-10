# Two tracks to the first sale

Written 2026-09-10. Brey's instruction: keep improving the model **and** get
the first sale ready, split evenly, run in parallel.

Everything here is either done, in flight, or has a named next action. No
item is on this list without one.

---

## Where the product actually is, in one paragraph

The thing works. Open the site and you get three to five bets a day in plain
English — "Take Yankees −1.5 at −149" — with the reasoning underneath,
frozen before first pitch and written to a tamper-evident ledger. The model
behind it was measurably improved today. **What does not exist is proof:**
zero days of graded results, with the first grading tomorrow morning. And
nothing can be sold to a stranger without a domain.

So the two tracks are: **build the proof surface and the buying path** (A),
and **keep making the picks better** (B). Neither blocks the other and they
touch different files.

---

## TRACK A — first sale

### A1. The record page — IN FLIGHT
The single asset that sells "picks with receipts". The receipts exist; no
page shows them. Building `GET /card/history` and a real day-by-day page:
every pick, what happened, what it returned, losses in the same weight as
wins, voids reported, chain status in plain English.

**Blocks:** nothing. **Needs Brey:** no.

### A2. Landing page tells the truth about the card — TODO
The page still carries wording from when the product was line-shopping. One
false claim was already fixed today ("some nights that list is empty" — the
card is never empty). The rest needs a pass against what the card actually
does now, including the run-line alternative and the frozen-then-graded
promise.

**Blocks:** cold outreach. **Needs Brey:** no.

### A3. Checkout, end to end — TODO, PARTLY BLOCKED
`checkout_delivery_ready()` already refuses a charge when `PUBLIC_BASE_URL`
is unset, so nobody can be charged and receive nothing. What is untested is
the whole path with real Stripe test keys: landing → CTA → signup →
checkout → webhook → token → the card.

**Needs Brey:** Stripe test-mode keys, and the domain for a real
`success_url`.

### A4. Outreach, drafted not sent — TODO
Jacob and warm contacts first. Everything drafted and targeted by me; **every
send approved by Brey**, because it is his voice and his accounts and the
disclosure has to be true.

**Needs Brey:** approval per send.

### A5. The offer — NEEDS A DECISION
`docs/PRICING_OFFER_VALIDATION.md` still has no founding-cohort size. Any
"first N members" copy is blocked on it.

**Needs Brey:** a number.

### A0. THE DOMAIN — BLOCKING EVERYTHING ABOVE
`linehound.app` appeared free; `linehound.com` is held. Production deploy,
real checkout and all outreach sit behind it. **This is the single item
that, done, unblocks the most.**

**Needs Brey:** a purchase. I cannot.

---

## TRACK B — the model

Today's ablation (`scripts/probe_model_ablation.py`, 1,896 games) says where
the model's skill actually lives, and three of my five written expectations
were wrong:

| component | contribution |
|---|---|
| run dispersion | +0.00424 nats |
| starting pitcher | +0.00269 |
| home field | +0.00105 |
| **team scoring rates** | **−0.00051 — the model is better without them** |
| **bullpen** | **−0.00059 — same** |

### B1. Test removing what the ablation says is hurting — NEXT
Two components are, on a full season, costing the model. An ablation is
descriptive; removing a component is a change and needs a window fixed in
advance like everything else. This is the highest-value model work
outstanding because it is a measured finding waiting to be acted on.

### B2. Lineups — the last captured-but-unused input
Posted lineups are stored and join to games. They never reach `run_means`.
Structural caveat to check first: the card freezes four hours before the
earliest game, and lineups often post later than that — so this may be
unusable at freeze time for most games, which is worth knowing before
building.

### B3. Totals — the park factor is built and waiting
`src.pipeline.parkfactors` is done, tested, point-in-time, and switched
**off**, because its pre-specified test declined it for the moneyline and
predicted in advance that it belongs in totals. If totals ever ship, it is
the first thing to turn on and its measurement already exists.

### B4. The run-line selection, revisited
Deleted today because one of its inputs was measured wrong. That input is
now fixed. Reinstating the comparison is a separate question with its own
pre-registration.

### B5. The tier ladder — PENDING, self-firing
`docs/PREREG_TIER_LADDER.md` refused for want of data: 5 usable dates
against 20. It runs nightly and escalates on its own the moment it is
answerable. No action until then.

---

## What "ready to sell" actually means

Three things, and only one of them is code:

1. **A buying path that works** — A0, A3.
2. **A page that proves the claim** — A1, plus days of real results.
3. **A reason to believe it now** — A4. Warm contacts can buy on "founding
   member, watch the record build". A stranger cannot, and should not.

**The honest timeline:** domain today → able to take money this week.
Roughly thirty days of published results before a stranger should pay. That
part cannot be compressed by working harder; it accrues one slate at a time,
starting tomorrow morning.
