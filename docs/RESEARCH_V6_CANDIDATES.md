# V6 candidates — design notes only

**Status: DESIGN ONLY. Nothing here is registered, nothing is frozen, no
outcome column was read, no store was opened, no funnel/matrix/battery code
was run to write it.** Every number quoted below is copied from a document
named in the citation beside it. This file exists to answer one question
honestly: *is there a V6 worth registering yet?*

**Written 2026-08-31**, from `docs/RESEARCH_CATALOGUE.md`,
`docs/RESEARCH_V4_EXPLORATORY.md`, `docs/RESEARCH_V5_STUFF.md`,
`docs/RESEARCH_V3_TIMING.md`, `docs/BENCHMARK_ELO.md`,
`docs/COLLECTION_POLICY.md`, `docs/ROADMAP.md`.

## Standing constraints, restated because they bind every line below

- **Discovery window is 2023–24 only.** **2025 is tuning-only, forever** — a
  candidate may be tuned there once, and every 2025 number is tuning evidence
  permanently. The 2025 sub-split `2025-08-26..2025-09-28` is already burned by
  four looks (`docs/TEST_SPLIT_STATUS.md`).
- **2026-01-01 .. 2026-08-27 is SEALED.** One evaluation, ever, after Stage 5
  policy freeze plus Brey's explicit go. **No candidate below may be resolved,
  scoped, sized, or coverage-checked against it.** There is currently no
  candidate to confirm, so the gate is moot as well as shut (B13).
- **2026-08-28 onward is forward proof**, never folded back into tuning.
- **Line-shopping value is PRICE IMPROVEMENT, never EV or "edge"** (L5). Two
  candidates below get rejected *specifically* because they collapse into this.
- Zero survivors is a valid result. "None of these clear the bar" is a valid
  deliverable, and it is the one this document reaches.

---

## The bar

`docs/RESEARCH_CATALOGUE.md` T2 raises it and states it: **another
season-level feature family needs a mechanism the market plausibly CANNOT
price, not merely one it might not.** Four pre-registered families against the
MLB h2h moneyline — V1, V2, V4, V5 — zero survivors. `late_move` is ~zero for
every V1 detector, so the market does not even drift toward these ideas. The
close beats a clean public-grade Elo by 0.00801 log-loss per game at
p = 0.0003 (N22, `docs/BENCHMARK_ELO.md`). The reading the program published
is not "we measured badly" — it is that **the h2h close already carries
whatever the pitch store measures**.

So each candidate must fill five slots, and slot 2 is the gate:

1. **Mechanism** — what is true about the world.
2. **Why the market plausibly CANNOT price it** — *structural reasons only*:
   (a) information the books do not consume, (b) a market too small or too
   thin to attract the money that would correct it, (c) reaction-time physics.
   "They might miss it", "it is a subtle interaction", "club-level pricing
   averages it out" are **not** structural reasons — the last one is the
   literal mechanism text of V4 #2 and V5 #2, both dead.
3. **Data** — does it exist, is it point-in-time, is it affordable under
   `docs/COLLECTION_POLICY.md`.
4. **Which prior death it must distinguish itself from** — by catalogue id.
5. **What would falsify it** — stated before anything is run.

**A candidate that cannot fill slot 2 with a structural reason is listed
REJECTED with that reason. That is the expected outcome for most of them, and
it is the outcome for ten of the twelve below.**

One further filter, discovered while writing this and worth stating as a rule:
**an incoherence between two prices tells you the pair is wrong, it does not
tell you which leg is wrong.** Converting "these two quotes disagree" into a
side requires a defensible fair price, and no family has ever supplied one
(L5, Ranker Engine 2 is empty and a test enforces it). Any candidate whose
output is "these two numbers are inconsistent" is either a two-leg execution
construction — which is price improvement, lane L5, never an edge — or it is
nothing. This kills C3 and C4 below on their own merits, independently of
slot 2.

---

## Verdict summary

| # | candidate | verdict |
|---|---|---|
| C1 | Pitcher-K props posted before lineups exist | **CONDITIONAL — strongest; not registrable today** |
| C2 | F5 price as a mechanically derived quantity, state-dependent error | **CONDITIONAL — blocked on B3's spend gate / L2's coverage review; and not new (U1)** |
| C3 | Within-book alternate spread/total ladder coherence | REJECTED — resolves to L5, and limits are unobservable |
| C4 | Within-book h2h vs run-line coherence | REJECTED — same, plus M3's shape |
| C5 | Third-time-through-order, measured rather than approximated | REJECTED — slot 2 empty; T2 |
| C6 | Hitter-side velocity bands / contact-power profiles | REJECTED — slot 2 empty; also B9-blocked |
| C7 | Umpire assignment | REJECTED — slot 2 unestablished; B10 source unverified |
| C8 | Totals × park × weather | REJECTED — books demonstrably consume it; B6-blocked |
| C9 | Late-season motivation / eliminated clubs | REJECTED — the information *is* the lineup, which books read |
| C10 | Doubleheader / makeup-game staleness | REJECTED — power, and it is V3's question already |
| C11 | Reverse line movement / contrarian anything | REJECTED — B1, the data does not exist anywhere we can reach |
| C12 | Market non-availability as a signal | REJECTED — carries no side |

**Zero candidates clear the bar unconditionally. Two survive as conditional,
and one of those two is not new.** The recommendation at the end is to
register nothing.

---

## C1 — Pitcher-strikeout props posted before lineups exist

**CONDITIONAL PASS. The strongest candidate in this document, and still not
registrable today.**

**1. Mechanism.** A pitcher's strikeout line is a function of the nine hitters
he actually faces. The opposing lineup's as-of-cutoff strikeout rate — the
real one, for the nine names posted tonight, not the club's season average —
varies materially game to game through rest days, platoon cards, September
call-ups and injury replacements. A prop line posted from a season-long
pitcher projection with a club-level opponent adjustment does not contain
tonight's specific nine.

**2. Why the market plausibly CANNOT price it — structural.** This is the only
candidate that fills slot 2 with two of the three admissible reasons at once:

- *Information not consumed at posting time, by construction.* Prop lines are
  posted hours before lineups are published. At the moment of posting the
  information does not exist yet. This is not "the book might overlook it" —
  the input is not in the world when the price is made. Whether the book
  **reprices when the lineup posts** is a separate, measurable question, and
  it is exactly what V3's `lineup_posted` class was frozen to measure (L1,
  `docs/RESEARCH_V3_TIMING.md`).
- *A market too small to attract the money that corrects it.* The probe
  measured **3–4 books, listing-dependent** for pitcher strikeouts
  (`docs/COLLECTION_POLICY.md`), against 12 books on historical h2h. V3's own
  consensus floor is 6 books — a prop market cannot even form a consensus by
  this program's own definition. Fewer books, lower limits, and none of the
  attention that made the h2h close beat a public Elo at p = 0.0003.

**Note the load-bearing asymmetry.** Every dead family lost to the *h2h
close*, which N22 established is the sharpest object on the board. Nothing in
this program has ever measured how good the **prop** close is. That is not a
licence to assume it is soft — it is the reason the candidate is conditional
rather than rejected: the prior that killed V1/V4/V5 is a prior about a
different market.

**3. Data.**
- *Feature side:* buildable. The pitch store is 2,737,968 rows rebuilt
  point-in-time with `bb_type` (U4, `docs/OVERNIGHT_RUN.md`), so a
  point-in-time lineup strikeout rate is derivable from data already on disk
  at zero credits. **It must pass the same byte-level PIT injection test
  V5's features passed before it is written into any registration** — this is
  the standing gate on the whole R3–R8 shortlist and it is not waived here.
- *Market side:* the constraint. Prop history runs from ~May 2023 and props
  are **deliberately not collected** — priced and documented as an option, to
  be switched on when a registered hypothesis needs them (`COLLECTION_POLICY`:
  "option value comes from knowing the cost, not from hoarding rows"). Forward
  collection is affordable inside the envelope; a **historical** prop pull is
  a purchase and therefore a HARD APPROVAL GATE, Brey's call, and it stands
  against the standing rule that credits go to candidates that survive free
  robustness (B3's precedent).
- *Coverage is unmeasured.* "Listing-dependent, 3–4 books" is the whole of
  what is known. A coverage audit comes before a mechanism, per the standing
  family procedure.

**4. Which prior deaths it must distinguish itself from.**
- **T2 / the four dead families.** C1 is *not* exempt just because the market
  is different. If the claim degenerates to "our K projection is better than
  the book's", that is V1's question in a new market and it inherits V1's
  prior. The claim must stay tied to the *specific* structural gap — the line
  was made before the lineup existed — or it is T2 again.
- **R2 / N8 (`lineup_vs_starter_history`).** Batter-vs-pitcher wOBA:
  coverage 14%/51%, **median history 9 PA**, structurally underpowered, and
  N8 produced 26 selections against a 30 floor. C1 must not become BvP with a
  new label: the feature is a *lineup-level aggregate K-rate*, which is
  hundreds of PA per hitter, not a nine-PA matchup history. If the design
  drifts toward per-batter-vs-this-pitcher anything, it is R2 and it dies.
- **U3.** The catalogue already lists a pitcher-strikeout prop family as
  READY_UNTESTED on the grounds that it is "priced and namable". C1's
  contribution is not the market — it is the *mechanism* that would let such a
  family clear T2 rather than be a fifth feature family in fancy dress.
- **L5.** If the finding is "book A's prop line is better than book B's", that
  is price improvement, not edge.

**5. What would falsify it.** In the order the evidence would arrive:

- **Falsifier 0 (the gating one, and it is not ours to run — V3 owns it).** If
  V3's `lineup_posted` class shows books reacting to lineup postings *within
  the capture-spacing floor* — i.e. no measurable latency — then the
  "information not consumed" half of slot 2 is empirically false for h2h, and
  the burden shifts to showing props behave differently from h2h, with no
  data in hand that would show it. C1 weakens to a coverage question.
- **Falsifier 1.** A prop coverage audit showing lines are in fact *re-posted
  or repriced after lineups drop* on most games. Then the information is
  consumed and slot 2 is empty. This is measurable forward, free-ish, and
  should be run before anything else about C1 is written.
- **Falsifier 2.** Lineup-level point-in-time K-rate having too little
  game-to-game spread to move a half-strikeout line — if the realistic swing
  is smaller than the quantization of the market, there is nothing to bet
  regardless of who knows what. Measurable on feature-side data alone, free,
  and it is the kind of check that should kill the idea *before* a single
  credit is spent.
- **Falsifier 3.** The standard family battery: 2023 screen / 2024
  replication, sign flip is death, BH-FDR q = 0.10 over the whole registered
  denominator, RULES_VERSION 2.0.0 concentration and dose-response checks. The
  screen-then-flip shape (N20: +1.96pp on 481 screen selections → −3.39pp) is
  what a dead idea looks like here, and a screen-year number in the right
  direction carries essentially no information in this program.
- **Falsifier 4 (fatal even if everything above passes).** Limits. A 3-book
  prop market with $200 maxima that moves the moment anyone bets it is not a
  tradeable finding, and **limits are not observable from the odds API**. This
  is stated up front because it is the same trap C3/C4 fall into, and because
  "measurable is not executable" is V3's own frozen caveat.

---

## C2 — The F5 price as a mechanically derived quantity

**CONDITIONAL, and it is not new: this is U1/L2/B3 territory, restated with a
sharper mechanism.**

**1. Mechanism.** A first-five moneyline is not obviously priced by an
independent model. If books derive it from the full-game price by a stable
transform — full-game price, minus a bullpen term, plus a tie term — then the
derivation's error is **state-dependent**: it should be largest exactly where
the two clubs' bullpens diverge most from whatever the transform assumes.
That is a different claim from "the F5 line is biased on average".

**2. Why the market plausibly CANNOT price it — structural, partially.**
Market thinness is real and measured: **5 books forward** on
`h2h_1st_5_innings` at 1 credit/event/moment, versus 12 books on historical
h2h (`COLLECTION_POLICY`); N23 found **30.0% of 454 candidate 2023–24 games
had no first-five market at all**, and R7 recorded **9.3% F5 odds coverage**
in the matchup matrix. A market a third of games do not have, quoted by five
books, is structurally not where the correcting money is.

**But the "derived, not priced" half of slot 2 is an assumption, not an
established fact.** We have never observed a book's F5 pricing process, and
the one measurement we have points the other way: B3 found the F5 price
**well calibrated** — actual home 54.4% vs implied 53.2%, +1.25pp, p = 0.67,
CI [−4.56, +7.12], mean implied gap across all games +0.001, no bucket
significant. That is a weak instrument (270 decided games) but it is not
encouraging, and B3 also records the trap: at 217 games the buckets showed a
clean monotone gradient (+8.3, +7.2, −5.3, −0.8, −0.6) that **dissolved** with
the full sample.

**3. Data.** This is where it stops. Historical F5 depth is a **HARD APPROVAL
GATE** — a large historical purchase, Brey's call, nothing spent without it
(B3). Forward F5 closes are accumulating free (L2) and the roadmap's next step
is a **coverage/book review over ~2 weeks of closes** (ready queue #3) — which
has not happened yet. Designing a family before that review is designing
against unknown coverage.

**4. Which prior deaths it must distinguish itself from.** **B3/M4** directly:
B3 asked whether the market's implied bullpen opinion is systematically
biased and answered "we cannot tell" on 270 decided games with 38 ties (14% of
F5 moneylines end level — the tie rate alone is a design constraint most F5
ideas forget). C2 is only a distinct hypothesis if it names the *state* in
which the derivation fails, in advance, and that naming needs the coverage
review first. Also **T6/B11**: the settling version of the F5 questions needs
posted F5 totals per game historically, which we do not have.

**5. What would falsify it.** The L2 coverage review showing F5 books quote
too few games, too few books, or too close to the full-game-implied value to
support a family at all. Or: the derived-price claim failing its own
precondition — if F5 prices move *independently* of the full-game price
within a book across the forward capture grid, they are not derived, and the
mechanism is gone. That precondition test is free, uses forward data already
being collected, and **should be run before any F5 family is designed, let
alone before any historical backfill is proposed.**

---

## C3 — Within-book coherence of the alternate spread/total ladder

**REJECTED.**

**Mechanism (real).** 130–160 alternate outcome rows per event at 1 credit,
7 books (`COLLECTION_POLICY` — the best information-per-credit on the board).
A ladder that dense is machine-generated from one distribution; if the implied
distribution is non-monotone or otherwise incoherent, that is an error no
human made and no human is watching.

**Slot 2 — the structural argument is genuinely available here**: deep
alternate rows carry near-zero volume, so there is no money to correct them,
and nobody prices row 47 by hand. That is admissible.

**Why it is rejected anyway, on two independent grounds:**

1. **It resolves to L5, not to edge.** An incoherent ladder tells you the pair
   is wrong, not which leg is wrong. The only way to monetize it without a
   fair price is a two-leg construction inside one book — which is an
   execution product, i.e. **price improvement**, the thing this program is
   most careful never to call EV or edge. Engine 2 is empty; a coherence
   finding does not fill it.
2. **Executability is unobservable and this candidate lives or dies on it.**
   Deep alternates carry the smallest limits on the board, and the odds API
   exposes no limit, no acceptance, no fill. V3 already carries the frozen
   caveat that a publicly quoted price is called "executable" only in the
   narrow sense that it stayed quoted, with **no claim about limits ever made
   from this data**. A finding that is 100% about a market's willingness to
   take the bet, measured with an instrument that cannot see willingness, is
   not a research finding.

**Prior death it would have had to distinguish itself from:** F1/M3, the
canonical case. Cross-book dispersion looked like +8.49pp / p = 0.0063 / ROI
+18.1% and was killed by inverted dose-response, one-book concentration
(FanDuel +15.49pp, BetMGM −9.44pp), no season replication, correlated
selections through the leave-one-out consensus, and a 0.4% tail (249 of
59,297). C3 is within-book rather than cross-book, so it is not literally M3
— but "a tiny tail of weird quotes pays" is exactly M3's shape, and an 18% ROI
in a liquid market is a reason for suspicion, not celebration.

**Disposition:** if anyone wants this, it belongs in lane L5 as an execution
diagnostic, never as a V6 family. Alternates stay switched OFF; the option is
priced and that is the whole point of pricing it.

## C4 — Within-book h2h vs run-line coherence

**REJECTED**, for C3's reason 1 verbatim, plus: the two prices come from the
same engine at the same instant, so coherence is the expected state, and the
residual is the M3 tail again. Additionally, the only reading that produces a
*side* requires knowing the correct win-by-2 probability — a fair price — which
is the unproven object. Same disposition: diagnostic, not family.

## C5 — Third-time-through-order, measured rather than approximated

**REJECTED — slot 2 is empty.**

U4 is genuinely ready: the 2.74M-pitch store is rebuilt point-in-time with
`bb_type`, 0 failed windows, and TTO was the one priority detector still
approximated. That makes it a good *feature*. It does not make it a
mechanism the market cannot price. Third-time-through is one of the most
publicly discussed effects in baseball, it is visibly acted on by managers
every night, and books read the same box scores. There is no information the
books do not consume, no market too thin, no reaction-time story.

**T2 applies exactly:** this is a season-level feature family, and the
catalogue's lesson 2 states the finding plainly — the market absorbs
season-level features, *all of them, so far*: platoon splits, pitch mix,
bullpen workload, travel, starter FIP (V1), the same features multiplied (V4),
and genuinely new store-derived measurements — as-of-cutoff fastball velocity
and career ground-ball share (V5). **New features alone are not new edge.**
TTO is a fifth swing at the same pitch.

**Legitimate disposition:** ship it as Analyzer content. The product's value
is honest decision support (Stage 9), and "we measure TTO rather than
approximating it" is a real improvement to what the Analyzer says. It is not
a hypothesis.

## C6 — Hitter-side velocity bands, contact/power profiles

**REJECTED — slot 2 is empty, and it is blocked regardless.**

B9: not in the matchup matrix point-in-time; named as V6 candidates in both
V4 and V5 and deliberately not smuggled into either family; blocked until the
feature is built and passes the byte-level PIT injection test. R3 and R4 are
the same ideas rejected at ranking.

Even fully unblocked it fails the bar for C5's reason. Note the specific
precedent: R3 was "starter velocity profile × hitter velocity-band
performance". **The starter half was later built** as `starter_velocity_gap`,
became V5 #1 (`facing_soft_stuff`) — the strongest a-priori mechanism in that
family — and "showed nothing in either season worth the name" (+0.27pp screen,
+0.46pp replication, wrong side of the half-floor). Building the hitter half
so the pair can be multiplied is precisely the move R9 rejected: *no stated
mechanism survived being written down, and V4 had just demonstrated what
mechanism-free products earn.*

## C7 — Umpire assignment

**REJECTED — slot 2 is asserted, not established; and the source is not
verified.**

B10 records the blocker: umpire zone size / called-strike rate /
run-environment tendency, **source not verified**. The tempting structural
story — "assignments post the morning of the game and books don't consume
them" — is exactly the sentence the bar forbids stating without evidence. We
have never observed a book's response to an umpire assignment, and unlike C1
there is no forward instrument being built that would tell us.

Second problem: the effect, if real, is a **run-environment** effect, so it
routes to totals — and **no totals family has ever been registered** (U5, N10).
A candidate whose natural market does not yet have a family is a market
decision, not a mechanism.

## C8 — Totals × park × wind

**REJECTED — the market demonstrably consumes this, and it is blocked.**

B6: `orientation_deg` is `None` for all 30 parks *by design*, because a
bearing wrong by 180° inverts a real effect confidently and silently, so
`classify_wind` returns `None` and `wind_effect` reports
`applicable: False`. Roof state has **no feed at all** in any source the
project uses. U9 would unblock the wind half in ~1 hour of satellite imagery.

But unblocking it does not help: wind and park are the most visibly priced
inputs in the baseball totals market — books move totals on weather openly.
Slot 2 has no candidate reason. Do U9 because it is a bounded task that
removes a `None` from the Analyzer, not because it opens a family.

## C9 — Late-season motivation / eliminated clubs

**REJECTED — the information is the lineup, and books read lineups.**

The proposed structural claim is "books price the club, not the intent to
win". It fails because the mechanism by which an eliminated club plays
differently *is the posted lineup*, which is the single most universally
consumed input in the market — V3 admitted `lineup_posted` as an event class
precisely because everyone reacts to it. This is also the archetypal retail
angle, which is a mark against it rather than for it: T1 is closed on the
external base rate of **0.45% of 1,547 tested MLB moneyline strategies
profitable at the 1% level — the rate chance alone produces.** Power is bad
too (a few weeks, a subset of clubs), and the season-end window collides with
the 2025 sub-split already burned by four looks.

## C10 — Doubleheader and makeup-game staleness

**REJECTED — underpowered, and it is V3's question.**

The structural story here is reaction-time physics: a rescheduled game gets a
late-opened, thin market. That is admissible in kind — but it *is* the V3
lane, and V3 is frozen with denominator 4 and a 30-event floor per class, of
which **no class has produced any result anywhere yet**. Adding a fifth class
by the back door of a V6 family would be exactly the contamination the
program's family separation exists to prevent. Doubleheader counts are also
small enough that N8's fate (26 selections against a 30 floor) is the likely
outcome. If this is worth anything it is a V3 amendment after V3 reports, not
a V6.

## C11 — Reverse line movement, contrarian anything

**REJECTED — B1. The data does not exist.**

Restated so it cannot be re-proposed as new: it needs **public betting
percentages**, no source we can access provides them, and inferring public
sentiment from price movement **invents the data** — earlier notes listing RLM
as buildable were retracted as incoherent. Related: T3, "steam" detection is
retired because three snapshots a day cannot detect synchronised book
movement, and it was renamed to what it actually is.

## C12 — Market non-availability as a signal

**REJECTED — it carries no side.**

N23 is a real and interesting descriptive result: **136 of 454 candidate games
(30.0%) had no first-five market at all**, and the consequence was applied —
forward logging now records *market unavailable* as distinct from *no play*.
The temptation is to read a book's refusal to post as information about the
game. It fails the same way N9/N10/N11 failed: **side-less by design**. A
missing market tells you not to bet; it does not tell you what to bet. Keep it
as product honesty, never as a hypothesis.

---

## Recommendation

**Register nothing. Wait for V3's first class floor and the F5 coverage
review.**

Ten of twelve candidates cannot fill slot 2 with a structural reason, which is
the expected outcome and is the whole content of T2. The two that survive
(C1, C2) are both **conditional on evidence that is currently accumulating and
has produced no result anywhere**:

- V3 is frozen forward-only, denominator 4, and **no event-response result
  exists yet**; nothing is readable until a class hits its 30-event floor.
  C1's entire slot-2 argument — that books do not consume lineup information
  into a price in time — is a claim V3 was built to test and has not yet
  tested.
- F5 forward closes are accumulating at ~1 credit/event/moment, and the next
  step named in the ready queue is a **coverage/book review over ~2 weeks of
  closes**, not a family. C2 without that review is a design against unknown
  coverage, and B3 already recorded what reading a partial F5 run does to you.

The honest position: **the strongest V6 candidate is C1 (pitcher-K props
priced before lineups exist)** — it is the only idea in this document that
fills slot 2 with two admissible structural reasons at once (information that
does not exist at posting time; a 3–4-book market that cannot even form a
consensus by this program's own 6-book floor), and the only one whose prior is
not already spent, because every death so far was against the h2h close and
nothing has ever measured the prop close. It is *still* not registrable today.
Before one word of a C1 pre-registration is written, in this order and all of
it free or nearly free:

1. **V3's `lineup_posted` class reaching its floor and reporting.** If books
   react inside the capture-spacing floor, C1's best argument is empirically
   damaged and should be treated as such.
2. **A forward prop-listing audit** — how many books, how many games, when
   lines post relative to lineups, and whether they reprice afterward. This is
   the coverage-audit-before-mechanism step every family in this program has
   run first, and it can falsify C1 outright without a registration.
3. **A feature-side spread check** — does point-in-time lineup K-rate vary
   enough game to game to move a half-strikeout line at all. Feature data
   only, no outcomes, no credits, and it is the cheapest available way to kill
   the idea.
4. **Only then**, a pre-registration — with the honest note that a historical
   prop pull is a HARD APPROVAL GATE and that limits remain unobservable, so
   even a clean result is a *measurement*, not a tradeable edge. That
   separation is V3's, and it is the right one.

This document registers nothing, freezes nothing, and adds nothing to
`data/research/`. Its conclusion is that the correct next action on the
research lane is to keep collecting and to let V3 and L2 speak first — which
is also what the roadmap's ready queue already says.
