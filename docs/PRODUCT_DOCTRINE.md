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
