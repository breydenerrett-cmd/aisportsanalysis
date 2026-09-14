# Product doctrine — LINEHOUND

**Status: LOCKED 2026-09-08 by Brey.** Nine amendments applied. This document
governs product decisions. Where it conflicts with an older doc, this wins.
Changing it requires Brey, not a worker and not a context reset.

---

## 0. Measured state at lock time

HEAD `308f6a7`. Every number here was measured, not recalled.

| Measurement | Value |
|---|---|
| Research hypotheses / verdicts | 42 ids · **34 null, 2 false positive, 1 withdrawn, 0 confirmed** |
| Strategies swept / promoted | 8,811 genomes, 1,062 families · **0 promoted** |
| Backtest verdict | `BELOW_PLACEBO_CEILING`; CSCV PBO 0.61 |
| Forward-test settled (deduped) | **72 bets, 4 days, 43-26-3, +15.16u, +21.05%** |
| Tonight's staked positions | **121** — 111 CONTROL/MARKET_REFERENCE, **10 FORWARD_TEST** |
| `p_model_provenance == model_derived` | **zero rows** |
| Reviews classified CONFIRMED/REFUTED/VARIANCE | **0 of 624 — all UNTESTED** |
| Live homepage headline | `LAST 7 DAYS 273-259-18 · -0.0%` (**pooled across all classes**) |

Read together: the research programme has honestly found nothing yet, and the
site currently advertises a record that mostly belongs to null baselines we
would never sell. Both facts are load-bearing for everything below.

---

## 1. The nine amendments

1. **The core product is AI sports picks and betting edge.** Provability and
   auditability are the *trust moat* — what makes the picks believable — not
   a substitute for prediction quality. We are in the business of being right,
   and of being able to prove we said so first.
2. **No permanent 0-3 definition.** **Top 3 is the flagship cohort. Top 5 is a
   secondary tracked cohort.** Evidence determines the ideal cutoff.
3. **Public performance tracks four cohorts separately:** Top 3, Top 5, all
   published picks, and research/control systems.
4. **Confidence and edge meters are gated today and required tomorrow.** Once
   trustworthy model-derived probabilities exist they ship. Four axes stay
   separate and are never collapsed into one score: **win probability ·
   value/edge · evidence confidence · unit sizing.**
5. **The customer buys the strongest AI-generated picks.** Frozen records,
   published losses, pre-registration, CLV and falsification are what make
   those picks credible.
6. **"Zero picks tonight" is acceptable but must emerge from the evidence
   threshold**, not from an ideological preference for abstention.
7. **The research factory runs continuously:** search for better strategies,
   retire weak ones, learn from post-game reasoning failures, improve the
   ranking — **without ever changing frozen historical results.**
8. **Ranker improvement is forward-epoch only.** A new ranker version starts a
   new epoch. **Graded history is never re-ranked to choose a winning
   version.** Comparing rankers means comparing forward epochs.
9. **Agreement is family-aware, never a raw system count.** Duplicated or
   closely related genomes must not manufacture confidence.

### 1.1 Why amendment 8 is a hard constraint, not a preference

The ranker is a hypothesis. If we iterate it and score each version against
the same graded history, we are running an unregistered search over that
history and selecting the winner — which is exactly the move that produced
CSCV PBO 0.61 and the `BELOW_PLACEBO_CEILING` verdict on the genome sweep.
Re-ranking history would let us manufacture a better-looking record without
making a single better pick. Forward epochs cost time; retrospective
re-ranking costs the credibility that is the entire moat.

### 1.2 How amendment 9 is computed

Two genomes are in the same family when they are **structurally or
behaviourally near-duplicates**:

- **Behavioural:** decision-set Jaccard >= 0.8 (`overlap.FAMILY_THRESHOLD`,
  the same threshold `lifecycle.admit()` already uses to refuse a candidate
  that duplicates a retired family). Computed over **forward** decisions in
  `evidence/decisions_v2.jsonl` — forward-only, consistent with amendment 8.
- **Structural:** identical signal feature sets. With small n, two genomes
  can agree by construction long before their decision sets have had room to
  diverge, so structural similarity is the safer prior early on.

Family = the union of those two relations (connected components).

**A family contributes at most 1 to the agreement count.** Both `n_systems`
and `n_families` are recorded on the decision; **ranking reads
`n_families`.** Reporting both is what makes the discount auditable rather
than an unexplained number.

The 8,811-genome sweep collapsed to 1,062 families — the largest single family
held 4,019 members. That ratio is the whole argument: a raw system count is
not a measure of agreement, it is a measure of how many near-copies happen to
be registered.

---

## 2. Product thesis

LINEHOUND is an AI handicapper that publishes a ranked nightly slip of MLB
bets — a flagship Top 3, a tracked Top 5, and the full published list beneath
— each committed to a hash-chained ledger before first pitch with its
mechanism, its counterargument and its sample size on the card. The pitch is
prediction quality; the proof is a record that cannot be retconned and losses
published as loudly as wins. Every tout claims a record. We are the one that
can show the picks were written before the games, that the losing hypotheses
were published too, and that nothing was re-graded after the fact.

**Where we honestly stand today:** no model-derived probability exists, no
strategy has cleared the promotion gate, and the forward record is 72 bets
over 4 days. Today's product is therefore an **early-access forward-test
slip** — real picks, ranked, published, unproven, labelled as such — with the
credibility apparatus already built. That is sellable. What it may not yet
claim is a win rate or an edge percentage.

## 3. Customer

A bettor loyal to one or two books who bets most nights and is losing slowly
to the hold and to their own selection. They are not switching books for eight
cents. They are hiring us for **the strongest few bets on the board and a
reason to trust them.** On open they want, in order: *what are we on tonight,
why, and how has that been going.*

## 4. The recommendation funnel

```
full slate
  -> market-coverage floor            MIN_BOOKS = 6
  -> every registered system decides  price-blind (PROPOSE sees no price)
  -> keep FORWARD_TEST only           controls/market-ref never published
  -> top play per system per game     TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1
  -> EVIDENCE THRESHOLD               must clear to publish at all
  -> DAY RANK across all systems      family-aware, see below
  -> cohort tags: TOP_3 / TOP_5 / PUBLISHED   frozen at decision time
  -> freeze to ledger -> publish
```

Both new stages are pre-registered and versioned before they run, exactly like
the existing named rules.

**The evidence threshold** is what makes selectivity emerge rather than be
imposed (amendment 6). A candidate publishes only if it clears floors on
evidence tier, fired-confirmation count, and family-aware agreement. Zero
qualifying candidates is then a *measurement*, and the page says which floor
was missed and by how much.

**The day-ranking rule must change.** Today it is
`TOP_N_PER_SYSTEM_PER_DAY_BY_PRICE_STANDING_V1`, ranked on
`price_standing_bps` — which `slate.py` itself calls execution quality and
"emphatically NOT an edge." Ranking a picks slip by how good the price is
ranks the wrong thing. The replacement ranks on case strength:

1. **Family-aware agreement** — distinct families landing on the same
   selection (amendment 9). Not system count.
2. **Confirmation strength** — signals fired vs the genome's
   `min_confirmations`.
3. **Evidence tier** — book depth and board freshness.
4. **Price standing** — retained as the *last* term. Execution quality is a
   tiebreak, not the thesis.

Versioned `_V1`, stamped on every decision, frozen. A later `_V2` starts a new
epoch and never re-ranks history (amendment 8).

## 5. Homepage information hierarchy

1. **TONIGHT'S PICKS** — the ranked slip. Top 3 as flagship cards; 4-5
   directly below, visibly the same list, labelled as the Top 5 cohort;
   further published picks under a fold. This is the first five seconds. On a
   zero night: the closest candidate, which floor it missed, by how much.
2. **THE RECORD** — cohort selector defaulting to Top 3, n rendered at the
   same visual weight as the return.
3. What we checked and refused tonight.
4. The board / full slate.
5. Bet Check.
6. Research programme — nulls, published losers, retired strategies.

### 5.1 The pick card

Ships today: bet (market · side · line · price · book), rank and cohort badge,
thesis in English, counterargument, evidence tier, **family-aware agreement
(showing both families and systems)**, price standing with book count, stake
(1u flat), freeze timestamp, and that cohort's forward record with n.

Reserved and gated — four separate axes, never one score. This is
`MASTER_PLAN` §16's P/E/M/U decomposition and it stands:

| Axis | Unlocks when |
|---|---|
| **Win probability** | a `model_derived` p_model exists and clears the calibration harness |
| **Value / edge** | p_model is independent of the price it is diffed against — `edge_bps` stops being structurally null |
| **Evidence confidence** | **live today** — tier, book depth, n |
| **Unit sizing** | variable staking only after edge exists and the Kelly gate is deliberately opened |

### 5.2 Homepage leads with the card, not the slip (2026-09-12)

**Owner-approved, docs/DECISION_TODAY_ONE_ANSWER.md, options A1 + B1.** The
ordered list at the top of this section was never updated after THE CARD
(src/analysis/daily_card.py, market-confidence ranked) shipped and started
leading the homepage in its place — so this document kept specifying that
the slip led while the running app said the card did: two documents
describing one screen, disagreeing.

**What leads `#/today` now, and why:**

- **THE CARD is #1.** It is what the owner told this product to sell, and
  it is the more defensible claim: 3–5 bets a night, ranked by market
  confidence, frozen before first pitch and graded either way.
- **TONIGHT'S PICKS (the slip, agreement-ranked) is off the homepage
  entirely.** It moved to the performance page (`#/performance`,
  `web/js/slip.js`'s `renderTonightsPicks`), under a heading that states
  plainly it is research, not the card. On the two nights checked before
  this decision (09-10, 09-11), the slip's own #1 pick named a *different
  game* than the card's #1 pick, both nights — a customer reading both in
  one scroll had no way to tell which one this product actually stood
  behind. The slip has also tagged only seven bets "published" ever, as of
  this decision — too thin for any record of its own, and none is claimed
  for it on the performance page.
- **The hero panel on `#/today`, below the card, now reads the card's own
  #1 pick** (`web/js/card.js`'s `renderCard` return value) to choose which
  game to feature, never a price-gap computation against consensus.
  `chooseGapCandidate` is deleted, not left dormant.

The ordered list above this subsection is left exactly as written, as the
record of what this document specified before today — read it as history,
not as the current spec. Its item 1 (TONIGHT'S PICKS leads) and any
homepage-hierarchy conclusion drawn from it are superseded by this section.

### 5.3 Player props are on the card (2026-09-12)

**The owner, on the morning of 09-12, looking at a card of five moneyline
picks:** *"Did you wire everything? It's still showing ML's."* The standing
directive behind it: *"none of that price matters until we know it's a MORE
THAN LIKELY BET, once we have the almost guaranteed bets, then we find the
best sports picks of those with the best value."* The card had been
moneyline-first by rule (§5.1: side by market confidence, moneyline unless
the run line prices the same opinion better), and the prop board had shipped
as its own page. Two surfaces, one product, and the one the owner sells did
not carry the market he asked for.

**The rule, pure and declared** (`src/analysis/daily_card.select_props`,
`PROP_CARD_RULE = DAILY_CARD_PROP_LIKELY_AND_CLEARS_PRICE_V1`):

- Candidates are the prop board's contracts for the date in **`PROP_MARKETS =
  (batter_hits, batter_total_bases)`** — the two markets the card can
  describe in a sentence and settle from a box score. Never home runs (not
  de-viggable, likelihood-only), never runs scored (no sentence, no
  settlement rule under that name — caught by the second check on the day
  it shipped).
- A candidate must be **more likely than not** by our number
  (`probability > propboard.LIKELY_FLOOR`, 0.50), must **clear its price**
  (`probability > breakeven`), must stand on a **posted lineup**
  (`expected_pa_source == batting_slot`; the season-average fallback is not
  a card pick), and its game must not have started.
- **One pick per player**, the player's own likeliest contract.
- **Ranked by our probability, descending — never by the gap over the
  price.** The gap is measured adversely selected in this repo
  (docs/PLAYER_PROPS_NEXT.md); ranking on it would put the most-wrong
  numbers first.
- **At most three** (`MAX_PROP_PICKS = 3`), no minimum. Labels are the
  card's own bands read off our probability: STRONG ≥ 0.62, LEAN ≥ 0.55,
  SLIGHT above the floor. There is no SPLIT label for a prop — there is no
  separate market-vs-model side to disagree about.
- The why is two sentences composed from the numbers on the contract and
  nothing else: the batter's season rate for the outcome the bet needs (an
  Under quotes the under rate), the batting slot and expected trips, then
  what the market makes it and what the price needs to break even.

**Same receipts as the game picks.** Prop picks freeze on the same ledger
row (`evidence/cards_v1.jsonl`, `PROP_FROZEN_FIELDS`), lock per their own
game's first pitch under the same four-hour lead, are carried forward
verbatim once locked, and are graded from box scores through
`src/board/settle_props` — the settlement a backtest would use — flat one
unit, VOID when the batter has no box row.

**Records are read apart, never pooled invisibly.** `card_ledger.record()`'s
headline numbers stay the game record; `by_kind.game` and `by_kind.prop`
carry the two populations separately. A 9-3 game record must not quietly
absorb prop results, and a prop record must not borrow the game record's
nights.

**What the card says when nothing qualifies.** On a live build:
"No player prop posted with a lineup behind it clears its price tonight."
On a frozen row that recorded an empty evaluation, the same in the past
tense. On a row frozen before props existed: "Player props were not part of
this card when it was frozen." Three different facts, three sentences —
never "nothing cleared the bar" and never a claim that props were checked
when they were not.

**Open owner decisions, surfaced not made:** (1) the minimum number of books
behind a card prop — today it is the board's own two-book de-vig floor,
while a game pick needs six for an A grade; (2) whether a heavy favourite
that is likely but expensive (the first live pick was an Under 1.5 hits at
-250, our number 76% against a 71% break-even) belongs on a card sold as
"bets", or whether a price ceiling is part of the rule; (3) whether the
public record page should ever headline the two populations together.

### 5.4 All bets, merged, and totals join the card (2026-09-14)

> **Status at ship, 2026-09-14 (orchestrator):** totals are built, frozen,
> graded and rendered, but **paused on the live card**
> (`src/report/card.py` `TOTALS_ON_CARD = False`). On the day they shipped the
> run model's expected total sat above the market's line in 8 of 9 games and
> below it only at Coors, and every total it would have published cleared its
> price on our number alone at a 50–52% market. They go live when the run
> model's totals are measured against finished games — an owner decision.
> Props rank by the market's number and require the market to call them more
> likely than not, with our number clearing the price
> (`PROP_RANK_SOURCE = "both"`, docs/PROP_CALIBRATION_2026-09-14.md).

**The owner, that morning, with today's slate already live and no bets on
the page:** *"get todays games and analysis up and running, merge the today
bets for ALL BETS not just MLs include all best bets like player props ...
need bets asap for today"* — and, separately, that analysis on props, run
lines and "the niche bets" runs **pre-emptively, ahead of first pitch**, on
no fixed clock, and that the product's own clock is **Pacific, not
Eastern**. The card carried moneylines and props (§5.3); everything else the
scout found priced (run totals) sat in the odds store unread, and the two
kinds that did exist were never shown as one list.

**Game totals are now a third kind of pick**
(`src.analysis.daily_card.build_total_candidates` /
`select_totals`, `TOTAL_CARD_RULE =
DAILY_CARD_TOTAL_MARKET_SIDE_MODEL_AGREEMENT_V1`):

- Candidates come from the multi-book totals board at each game's **own
  consensus line** — the total most books are currently quoting for that
  game. There is no fixed standard the way the run line has 1.5; a total
  moves with the park and the day's two starters, so the line is read off
  the board, per game, rather than declared in advance.
- The **side** is whichever the de-vigged multi-book consensus makes more
  likely at that line.
- **Agreement**: our own run model must also make that side more likely
  than not, at that exact line. There is no fallback pile the way a thin
  moneyline night fills from its SPLIT pile — a total nobody agrees on is
  not a total pick.
- **Clears its price**: our probability must beat the break-even the best
  available price demands.
- Ranked by **market** probability, descending — the same axis the
  moneyline card ranks on. Labelled by the same STRONG/LEAN/SLIGHT bands,
  read off that market number. No SPLIT label: disagreement disqualifies a
  total candidate outright rather than demoting it.
- **At most three** (`MAX_TOTAL_PICKS = 3`), no minimum — a thin totals
  board is a true state, exactly like a thin prop board.
- Same receipts as the other two kinds: frozen on the ledger row as
  `total_picks` (`TOTAL_FROZEN_FIELDS`), locked per the pick's own first
  pitch four hours out and carried forward verbatim once locked
  (`card_ledger._lock_and_merge`, the same function every kind uses), graded
  in `card_ledger.settle` by `grade_total_pick` (total runs from the same
  final-score map the game picks grade from: over the line wins Over, under
  it wins Under, exactly on it pushes), and pooled in `record()`'s
  `by_kind.total` — never merged into the game or prop populations. A
  locked total pick is identified by `game_pk` alone
  (`card_ledger._total_pick_key`, fixed 2026-09-14) — there is at most one
  total pick per game by construction, so a board move that flips the line
  or the side after a pick locks cannot add a second, contradictory total
  bet on the same game; keying on the line and side too let exactly that
  happen (Over 8.5 locked, the board moving to Under 9.0, and the ledger
  carrying both).
- **A whole-number line can push, and the push has to come out of BOTH
  sides before either is compared to anything.** Fixed 2026-09-14: `p_over`
  at the market's own line already excludes a push on the Over side (it is
  a strict `>`), but the Under side read as `1 - p_over`, which on a
  whole-number line folds the push in with the Under win — and the
  market's de-vigged number and the price's own break-even are both
  measured ignoring the push, so an Under measured with it included is
  compared against two things on a different basis than itself. Live, BAL
  @NYM at 8.0 runs: P(over) 47.54%, P(push) 7.54%, the push-inflated Under
  read 52.46% — clearing -110's 52.38% break-even — when the push-excluded
  Under is really 48.58%, under both 50% and the break-even; the model
  actually leaned Over. `src.report.card.card_for_date` now asks the model
  for the line one half-run below any whole-number total too, and
  `build_total_candidates` divides the push back out of both sides before
  the agreement or clears-price gates ever see a number. A half-point line
  cannot push and is unaffected.

**Player props go on the card before any lineup posts.** The owner's ask
was explicit: analysis "needs to be ran pre emptively before any games."
`propboard.build`'s `expected_pa_source == "season_average"` contracts —
built from the batter's own season rate of plate appearances, with no
posted batting order behind them — are no longer refused by the card; they
carry `"lineup_posted": false` and a why-sentence that says plainly the
lineup is not posted yet and the estimate is the season-average trips to
the plate, not tonight's actual slot — and, fixed 2026-09-14, is refused
outright as a card pick when the season rate behind it comes from fewer
than `MIN_SEASON_GAMES_FOR_PRELINEUP` (15) prior box rows. Live today the
top three `all_bets` rows (84%/81%/78%) rested on 11-13 games each, and a
season rate that thin is the likeliest source of the suspected UNDER bias
on the prop board (five of the top ten contracts were unders at Coors
Field) — a small, one-park, one-pitcher sample dressed as a season number.
A contract WITH a posted lineup is not gated by this floor; only the
season-average estimate this section exists to allow before one posts.

The existing open-pick replacement in `card_ledger.publish` (an unlocked
pick is replaced wholesale by the next publish's read) is what swaps a
season-average contract for a `batting_slot` one the moment a lineup posts
and the pick is still open. **Fixed 2026-09-14** (Opus checker problem 5):
this section used to say "same game and market," and the identity key
(`card_ledger._prop_pick_key`) used to include the market and the line too
— so a lineup posting that moved `select_props`'s own pick to a different
market or line for the SAME PLAYER (it selects one contract per player,
whichever is highest-probability, not one per market) produced a fresh key
that did not match the locked one, and both were kept: two graded prop
bets standing on one bettor's decision, the identical duplicate hazard
totals had before the fix above. The key is now `(game_pk, player)` alone
— everything `select_props`'s own one-pick-per-player rule already
guarantees is unique — so a locked prop pick blocks any fresh prop for the
same player in the same game, whatever market or line it is priced on.

**Ranking a prop pick against the OTHER kinds is a separate question from
ranking props against each other.** `select_props`'s own rule — rank by our
probability, never the gap — is untouched (§5.3, and the measurement
behind it). `daily_card.prop_rank_probability(contract)`, gated by
`PROP_RANK_SOURCE`, is the declared seam for the cross-kind question only:
`"model"` (our number), `"market"` (the de-vigged market number) or
`"both"` (our number and the market's both clear the contract's own
break-even, the market's also clears 50%, ranked by the market's).

**Set to `"both"` 2026-09-14 (integrator), from
`docs/PROP_CALIBRATION_2026-09-14.md` rev. 2.** On 1,200 settled prop
contracts the market's number scored at least as well as ours on every cut
(Brier 0.2406 vs 0.2469, and in each of the three markets). Ours leans to
Unders: Overs hit 53.2% against our 48.4%, and among contracts both numbers
call likely, Unders hit 53.6% against our 61.7% (n=332) while Overs matched.
Where ours ran 10+ points above the market, 32 contracts hit 40.6% against
our 62.1%. The sample is small and concentrated (5 dates, one of them 69% of
rows), so this is not proof the market is right; it is a refusal to rank a
prop above a game on our number alone while the only settled evidence says
it runs high. It also puts the merged list on one axis, since game and
total picks already rank by the market's number. Neither number is compared
to the other; there is no gap ranking. This setting changes ORDER in
`all_bets` only; which props reach the card is still `select_props`.

**`all_bets`: one ranked list, every kind.** `payload["all_bets"]`
(`daily_card.merge_all_bets`) merges `picks`, `total_picks` and
`prop_picks` into one array: `{kind, position, index, probability, label,
bet, first_pitch_utc, lineup_posted}`, `position` 1..n across the whole
list, `index` the pick's own position back in whichever of the three arrays
it came from. Ranked by market probability for a game or total pick,
`prop_rank_probability` for a prop pick. The three arrays a reader already
knows — `picks`, `total_picks`, `prop_picks` — are unchanged and still what
the ledger freezes and grades; `all_bets` is a view built fresh over them,
live or frozen, so it can never say something the three arrays underneath
it do not. **`lineup_posted` added 2026-09-14** (Opus checker problem 3):
`None` for a game or total pick, which never turns on a lineup either way;
a prop pick's own `lineup_posted` value otherwise. Before the fix, a page
drawing its ranking straight off `all_bets` could show a pre-lineup prop at
position one with nothing marking it as such — the label lived one hop
away, on `prop_picks[index]`, not on the row a reader actually reads.

**What is still NOT on the card, and why:**

- **First-five markets, team totals, and alternate lines** — no model
  probability exists for any of them yet (`src.analysis.strength` — not
  `src.model.strength`, which is not a module in this repo — prices the
  full-game moneyline, run line and total only). Publishing a pick with no
  model behind it would be the market's opinion alone, which is the exact
  thing this product refuses to sell as a pick (§1).
- **Pitcher strikeouts** — same reason: no model.
- **Home runs, RBIs, hits+runs+RBIs** — blocked by design, not by a missing
  model. Home runs have no fair price to clear (no book quotes the under,
  so nothing to de-vig against — `propboard.likelihood_only`); RBIs and the
  combined market are refused by `playerprops.publishable` because the
  model is not good enough on them yet. See `propboard`'s own module
  docstring for the measurement behind each refusal.

**Timezone.** The owner: "we are in PST not EST." Every timestamp this
module reads and writes is UTC on the wire, as it always has been — the
correction is in how a human reads the card's own first-pitch times against
"today," not in the pick logic itself, and belongs to the surface that
renders them for a reader, not to the selection rule.

## 6. Public performance

Four cohorts, always reported together, never merged:

| Cohort | What it is | Where |
|---|---|---|
| **TOP 3** | the flagship slip | headline record, default view |
| **TOP 5** | secondary tracked cohort | beside Top 3, always |
| **ALL PUBLISHED** | every pick that cleared the threshold | one click away |
| **RESEARCH / CONTROL** | `trivial_*`, `market_derived_consensus_*` | research page only, never headline |

- **Cohort definitions are pre-registered before the first pick grades under
  them**, and all four report every time. That is what makes "evidence
  determines the cutoff" a measurement rather than reporting whichever cut
  happened to win.
- A pick's cohort is **frozen at decision time**, never reassigned.
- `n` renders at the same visual weight as the return.
- All-time leads; 30/7-day windows are secondary.
- Only settled, published, FORWARD_TEST rows. No backtests, replays,
  unpublished positions or controls.
- **CLV reported per cohort** as the leading indicator, realized return as the
  lagging one.

## 7. The autonomous research loop

**Nightly** — capture, slate on cadence as lineups post, threshold, rank,
freeze, publish.

**Post-game** — settle, then **evaluate the `mechanism_predicates` frozen with
each pick**, classifying CONFIRMED / REFUTED / VARIANCE. This is amendment 7's
"learn from post-game reasoning failures." It is fully wired and has produced
**0 classifications in 624 reviews**. Turning it on is what separates "this
genome is unlucky" from "this genome's reasoning is wrong," which is what
retirement actually needs.

**On accumulated evidence** — `retest_due` fires on >= 10 new game-days (never
wall clock); CSCV/SPA over accumulated forward evidence; genomes whose
predicates keep landing REFUTED retire. Retirement is a **forward** action;
historical rows are never rewritten.

**Continuous search** — new genomes enumerated as registry features grow; each
candidate clears `admit()` (pre-registration + Jaccard < 0.8 against every
retired family, so a near-duplicate of something already killed cannot
re-enter as fresh evidence).

**Ranking improvement** — pre-registered, versioned, frozen per epoch, stamped
on each decision, **history never re-ranked** (amendment 8).

**Scoreboard** — CLV per cohort, weekly.

**Frozen, not automatable:** feature registry and ladders, enumeration spec,
sealed seasons, the promotion gate, and every threshold. Credits buy more
data, never a weaker gate.

## 8. Known misalignments at lock time

1. **The headline record is the instruments' record.** `LAST 7 DAYS
   273-259-18` pools CONTROL and MARKET_REFERENCE — 111 of tonight's 121
   positions. A prospect's first impression is a flat record produced by
   systems we would never sell.
2. **The picks are not on the page.** FORWARD_TEST plays appear only inside a
   collapsed `<details>` on qualifying opportunity cards, while Today leads
   with "NOTHING CLEARS THE BAR."
3. **"TOP PLAY" ranks the wrong thing** — price standing, not case strength.
4. **The funnel widens at the last stage** — 10 per system per day × 12
   systems, with no day-level rank or threshold.
5. **CLV has never been measured** and **no falsification battery has run on
   any live genome** (every scorecard `battery_verdict: NOT_RUN`, every review
   `UNTESTED`).

6. **The product's own systems decide ~10 minutes before first pitch.**
   Measured 2026-09-08 over 1,055 played decisions: FORWARD_TEST median lead
   time before first pitch is **9.9 minutes**, and **72% of forward-test picks
   freeze inside 30 minutes of it**. The null baselines, which need no lineup,
   decide with a median lead of ~8 hours (CONTROL 484m, MARKET_REFERENCE
   524m).

   **Root cause — CORRECTED 2026-09-08.** My first diagnosis, that
   `lineup_store` refreshes too rarely, was **wrong**, and the correction
   matters because it changes the fix entirely.

   `lineup_store` gates no live decision at all. `src/engine/features.py:848`
   branches on the decision instant: before 2025-01-01Z it takes
   `_build_replay`, and `lineup_store_mod.read` (line 646) is called ONLY in
   that replay branch. Every live 2026 decision takes `_build_live`. The
   `lineup_posted` flag `evolab.decide` actually checks is derived at
   `src/engine/glue.py:388` from an as-of read of
   `data/watch/lineups_watch.jsonl`, a store the capture cadence already
   refreshes. So no lineup-store cadence could ever have moved this number.

   The real cause is that **nothing was running.** `decision_time_for_game`
   sets the decision instant to the latest L1 capture at or before
   `commence - 5min`, and every slate pass refreshes L1 before reading it, so
   the instant lands wherever the pass runs. Only two slate passes are
   scheduled in Actions: `daily-loop` at 10:00Z and `afternoon-slate` at
   21:10Z. At 10:00Z no lineup has posted, so every genome refuses NO_LINEUP
   and only the null baselines record — which is exactly why CONTROL and
   MARKET_REFERENCE carry seven-to-nine-hour leads while the genomes carry
   ten minutes. All 85 forward-test decisions on the ledger came from *ad-hoc
   late passes*.

   The "slate on a cadence" change (`135440b`) touched
   `scripts/capture_tick.ps1` — the LOCAL PowerShell scheduler, which only
   runs when Brey's machine is on. In the cloud the cadence never existed.

   Measured slack: the first capture holding a complete posted lineup sits a
   median **160 minutes** before first pitch, and the median forward-test
   decision was frozen **137 minutes after its own gating input was already
   visible**. Nothing was waiting on data. Nothing was running.

   This costs three things at once. A pick delivered ten minutes before first
   pitch is commercially near-useless -- the customer has no time to act and
   the line has already moved. It is unmeasurable for CLV by construction: the
   closing board IS the decision board, which is why 56 of 85 forward-test
   decisions were refused a CLV for exactly that reason. And it means the
   forward record is being built out of the worst prices the day had to offer.

   The fix is therefore a **slate pass on the capture cadence**, gated on
   whether a complete posted lineup is newer than the last frozen decision
   set — not a lineup-store refresh. That is the single highest-leverage
   operational change available, and it is what turns the published slip from
   a novelty into a product.

*Smaller but corrosive:* the homepage prints "27 hypotheses pre-registered …
zero surviving" as a **hardcoded constant**. The registry says 42. A product
whose pitch is "we don't make numbers up" must not hand-type that number.

*Correcting an earlier read in this same document's first draft:* the capture
cadence is NOT the CLV blocker. The board is captured a median 9.9 minutes
before first pitch, 67% of it within 15 minutes -- that part works. The
blocker is the decision lead time above.

*Known broken:* `scripts/factory_masks_from_sweep.py` fails to rebuild the
sweep decision masks — `placebo.real_world` receives zero games although
`matchup_matrix_2023/2024.jsonl` hold 4,859 rows. The masks `.bin` is
correctly gitignored and regenerable, so nothing is lost, but the overlap
report cannot currently be regenerated and a run of it will silently downgrade
recorded family counts to "not computable." Diagnose before re-running it.
