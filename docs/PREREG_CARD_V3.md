# Pre-registration (DRAFT): DAILY_CARD_BRIEF_V3

**Rule id (proposed):** `DAILY_CARD_BRIEF_V3`
**Status:** DRAFT, 2026-10-16. **NOT REGISTERED.** `REGISTERED_UTC` is unset. No row
exists in `alpha_registry` for this id, no V3 sample is counting, and nothing in this
file binds anyone until a commit sets `REGISTERED_UTC` and the owner has answered
section 12 in his own words. A draft is an argument, not a rule; it may be rewritten
freely until that commit, and from that commit no number below may change (changing one
is a new rule id with its own window, as in `docs/PREREG_CARD_V2.md`).

**Family:** CARD (MLB daily card)
**Succeeds on the customer card:** `DAILY_CARD_BEST_BETS_V2` (V2), which this file
proposes to retire as a value card. See section 9 for what happens to V2's sample.
**Evidence:** `docs/research/loss_diagnosis/00_SYNTHESIS.md` and reports 01 to 03.
**Patches this registration depends on:** `docs/decisions/card_v3/` (README.md there
says what each does and what it costs to apply).
**Companion registration, not written here:** `docs/PREREG_INFO_TIMING.md` (being
written by another worker). It is referred to by name only; this file does not state its
hypothesis, its rule or its sample.

---

## 0. What this registers, and what it does not claim

It registers a **product**, not a betting rule: a brief that, for every market the model
prices on an MLB slate, says what it calls, how sure the market is, the case against
the call, which inputs it did not have, and then grades every call in public. It
publishes **no value picks**. It registers one **gate**: the single, named condition
under which a value pick may ever appear on the public card again (section 5). It claims
no edge and no positive expected return, and no result of this registration can license
that claim by itself (section 8).

Why this shape. The loss diagnosis found, by three independent measurements:

1. every one of the 178 graded V2 bets paid a premium over the market's own fair price
   (mean +2.36 probability points), so at the market's numbers the card was expected to
   lose 7.55 units; it lost 1.42, which is luck, not edge (03 section 3);
2. the model's disagreement with the market carries no information: on 6,818 priced prop
   contracts the model's log loss is worse than the market's by +0.0103 nats
   [+0.0064, +0.0153], and the best weight on our disagreement when blending with the
   market is -0.20 [about -0.46, +0.07] (01 section 2; 00 fact 2);
3. a card that ranks by that disagreement publishes our largest errors by construction
   (score vs model-minus-market correlation 0.98; 02 section 1).

A value card built on a model whose disagreement has weight zero cannot recover a
premium it pays on every bet. The honest product on the evidence is therefore the part
that does not depend on beating the market: calling every market, showing the market's
number first, and grading the calls where anyone can look.

**Every figure cited from the diagnosis is hindsight on V2's open window (2026-09-22 to
2026-10-15). None of it is a V3 result, none counts toward any V3 floor, and none
licenses anything beyond choosing what to test forward.**

## 1. Evidence rules this registration obeys

* **Sealed window.** 2026-01-01 to 2026-08-27 outcomes stay sealed. Nothing here reads
  them and no V3 constant is set from them.
* **2025 is tuning-only.** No V3 constant is fitted on 2025 or later data in this
  registration. The frozen parameter file V2 uses
  (`data/processed/card_v2_frozen_params.json`, sha256
  `64e96b4a9a8d56753fa38f2f0b97b51eb87b3c48adaf29db199eb10b6467db3d`) is carried over
  unchanged; V3 adds no fit.
* **V3's sample starts at `REGISTERED_UTC`.** A call counts only if its first pitch is
  strictly after it. V2's open window is never counted toward V3.
* **Point in time.** Every number on a V3 brief is computed from data observed before
  the brief's publish instant; the quote time of every price shown is on the brief.
* **No rescue by threshold change.** Section 5's bar is fixed here. If a candidate rule
  fails it, the rule is retired, not re-tuned on the sample that failed.

## 2. Product: a brief that calls every market

For each slate date the V3 brief covers, **per game and per player-prop contract the
model prices**, these five items, and nothing is omitted because it looks bad:

1. **The call.** The side the market's de-vigged consensus makes more likely than not
   ("likely first", the owner's ordering that `src/analysis/propboard.most_likely`
   applies to our number; here it is applied to the market's), with
   *the market's number first and ours second* and an explicit flag where the two sides
   disagree ("model difference", never "value"). A game or prop priced at exactly 50% is
   shown as "no lean". The diagnosis found our disagreement carries no information, so
   the brief never ranks by it and never describes it as an edge.
2. **The case against.** At least one reason the call could be wrong, drawn from the
   fields the model actually reads, written to the same standard as the V2 copy tests
   (`tests/test_customer_language.py`): no "lock", "guaranteed", "free money", and "edge"
   only negated.
3. **Missing inputs.** Every input the model did not have for this contract, by name:
   no posted lineup (batting slot unknown, so season-average plate appearances were
   used), fewer than 15 prior games, no opposing-starter term (the prop model has none;
   01 section 3c), no postseason adjustment (01 section 3c), thin book count, stale
   quote age. The brief states what it did not know before it states what it thinks.
4. **The board.** The price at the **board average** with the number of books and the
   quote age, and the best single price beside it as a second figure. No verb ("Take",
   "bet") appears anywhere. The brief reports prices; it does not recommend buying them.
5. **The grade.** After the game, the call is marked right or wrong, and the brief
   records (a) the model's and the market's log loss on that contract, and (b) the
   result at the board-average price (section 6). Every call is graded, including calls
   the model later changed (section 6.3).

**Coverage rule, so "every market" cannot quietly mean "the flattering ones".** The
covered set is every contract that clears V2's G1, G2 and G10 style admission (unstarted,
at least 2 two-way books for a prop and 6 for a game, at least 15 prior games for a
prop) **before** any value or disagreement test. A contract that is priced but not shown
is listed with the reason (the refusal census already produced by `propboard.build`
`refused`, which today records why a contract could not be priced). Markets the model
does not price (home runs: no fair price; RBI and hits+runs+RBI: model not good enough;
`playerprops.NOT_PUBLISHABLE`) are listed as "not called" with the reason, so absence is
visible.

**Heavy favourites.** The owner's ruling (2026-09-20 and 2026-09-22) is that no pick at
-200 or worse appears on any public card. A V3 call is not a bet, but the ruling is
carried over literally: a side whose board-average price is -200 or worse is listed
under "priced out" with its price and no call framing, and is not graded in the call
record. This is an owner decision to confirm (section 12, Q3).

## 3. What the patches change in the numbers (and why V3 needs them)

| patch | what the V3 brief and record get from it | registration consequence |
|---|---|---|
| `tb_correction.patch` | Total bases over 0.5 is priced through the same correlation-corrected path as hits over 0.5 (the same event). The diagnosis measured the old path +2.95 points high on identical player-games, +2.7 to +3.9 in 2024 and 2025 | edits `src/analysis/playerprops.py` (fingerprinted) |
| `grade_average_odds.patch` | The grade price is the board average, with the best price kept as a second field. Implements the owner's 2026-09-21 ruling, which V2 never applied | edits `propboard.py`, `props.py`, `card_v2.py`, `card_ledger.py`, `prices.py`, `opportunities.py` |
| `stale_board_real.patch` | `stale_board` is computed from the quote ages the freshness gate uses; V2 recorded `None` on all 175 rows | edits `best_bets_card.py` (fingerprinted) |
| `ml_fill_lock_price.patch` | A locked moneyline is graded at a price that was on the board at lock | edits `card_ledger.py` |
| `withdrawn_label.patch` | Withdrawn calls are reported with their own result, in a labelled figure | edits `card_ledger.py` |

Applying any of them changes a fingerprint (section 10) and, under V2, would restart
V2's counted sample. They are applied **once, together, at V3's registration commit**
and not before; V2 keeps running unmodified until then.

## 4. Grading

* **Price basis: the board average.** A call is graded at the mean decimal price of the
  books on the board at the quote instant (`propboard.average_decimal` for props; the
  `prices.snapshot` side average for games), over the same books the best price was taken
  from. The recorded best price is kept in the same row as a second field and is never the
  graded figure. An entry with no recorded average (a board too thin to average, or an
  entry frozen before the field existed) is graded at its best price **and labelled
  `best_price_no_average_recorded`**, never given a guessed average.
* **Outcome grade.** Win, loss, push (whole-number lines) and void follow
  `src/appstate/card_ledger.grade_pick` and `grade_prop_pick` unchanged.
* **Withdrawn calls are graded and labelled.** A call the model withdrew after
  publishing it (a fresh read no longer supports it) is still shown to readers during
  its life, so it is graded at the price it was last shown, appears in the record as
  `withdrawn`, and is reported in its own figure beside the shown calls: two numbers with
  their labels, never one pooled number. (V2 produced "97-81" and "86-75" from the same
  ledger; the first included 17 withdrawn picks, the second did not, and neither was
  labelled.)
* **`stale_board` is real.** It is set when no quote on the newest board is within
  3,600 seconds of the publish instant (the V2 registration's own definition and G3's
  threshold, which the V2 registration ties to the hourly full-slate capture pass). The
  brief shows the board's age whenever it is set.
* **Moneyline lock price.** A moneyline locked inside the lock window is graded at the
  price on the board at lock, with `price_when_shown` kept beside it; a lock-time board
  that has left the registered price band withdraws the entry rather than locking it at
  a price nobody can take.

## 5. The value-pick gate (the only way a pick returns)

The public card shows **no value pick** under this registration. A value pick may be
added to the public card only by a **separate registration** that satisfies every
condition below, in this order:

1. **A named forward test, registered first.** A rule `R` is written down in full
   (its inputs, its constants, its fingerprint files, its population, its price basis)
   **before** the sample that tests it exists. Its first-pitch cutoff is its own
   `REGISTERED_UTC`; nothing earlier is counted.
2. **The bar.** Over **at least 150 bets with a measurable closing-line value**,
   produced by `R` after its registration, the **95% confidence interval of mean
   closing-line value excludes zero from above** (lower bound strictly greater than 0).
   * Closing-line value is V2's definition (`docs/PREREG_CARD_V2.md` 11.3,
     `src/report/clv.py`): the de-vigged consensus at the last capture strictly before
     first pitch, minus the break-even of the price taken, with V2's exclusions
     (`CLOSING_BOARD_THIN`, a close more than 5,400 s before first pitch, the closing
     capture being the decision capture, a close older than the quote, an unjoinable
     event). **The price taken is the graded price, i.e. the board average (section 4)**,
     so the bar is not met by the best-price premium alone. The result at the best price
     is reported beside it and is not the bar.
   * The interval is a bootstrap over slate dates (10,000 resamples, seed 20261016),
     two-sided, 95%.
   * A bet with no measurable closing-line value is reported by reason and **does not
     count toward the 150**. The diagnosis could measure 82 of 178 V2 bets (props
     rarely have a later two-sided capture); the registration of `R` must say how many
     bets it expects to need, and the 150 counts only measurable ones.
3. **One read.** The first settlement run after the 150th measurable bet is the only
   read. There is no early look at the interval, no continuation, no second read on the
   same sample. A change to any file in `R`'s fingerprint restarts its sample.
4. **Verdicts.** `PASS` (lower bound > 0), `FAIL` (upper bound < 0), `INCONCLUSIVE`
   (interval contains 0). `INCONCLUSIVE` licenses nothing, ever; a further test is a new
   registration with a window that starts after it. Only `PASS` can put a value pick on
   the public card, and then only for `R`, only for the price class and market `R` was
   registered on, and only after the dated owner sign-off required by
   `docs/ARCHITECTURE_BETTING_ENGINE.md` G7.
5. **The size of the bar, stated.** On V2's measurable bets the per-bet standard
   deviation of closing-line value was about 1.9 points (a half-width of about 0.4 points on
   82 bets implies it; the interval is date-clustered, so this is approximate), so 150
   bets give a standard error of roughly 0.16 points. The bar can
   detect a true mean closing-line value of a few tenths of a point. That is a low bar
   for *information*; it is a high bar for a rule that pays a 2.4-point premium per bet,
   which is the point.
6. **The candidate.** The **only** candidate value rule this registration leaves open is
   **information timing**: betting on a fact the market did not yet have when the bet was
   struck (an earlier lineup, starter, weather or scratch read). Its hypothesis, rule,
   sample and fingerprint are the subject of `docs/PREREG_INFO_TIMING.md` and are
   **not** stated or implied here. This file registers the gate it must clear and nothing
   about the rule. No other candidate is open: a rule that re-weights the existing
   inputs (the diagnosis' blend weight on our disagreement is -0.20 [about -0.46, +0.07])
   or re-tunes G7/G8 on V2's sample is **excluded by this registration**, because that
   sample selected it.

## 6. What a call is graded on

* **Primary: log loss against the market**, per contract, the model's number minus the
  market's de-vigged consensus, aggregated by market and by month, with the date-clustered
  bootstrap of V2's 11.3. It is reported, not used to change the brief mid-sample.
* **Secondary:** hit rate of the call; calibration by probability bucket; the result at
  the board-average price (units), descriptive only and never a headline.
* **The headline sentence is fixed in advance** (customer copy to be written under the
  V2 copy tests): it states the number of calls, the hit rate, the market's own expected
  hit rate on the same calls, and units at the board average, each with its date range;
  it does not describe the result as skill.
* **Calls the model changed.** A call changed after publication is a new call from its
  publish instant; the old one is graded and labelled `withdrawn` (section 4).

## 7. Population and counting

A call is **counted** if it was published on a V3 row, its first pitch is strictly after
`REGISTERED_UTC`, its game is a regular-season game, and the `code_fingerprint` frozen on
its row matches the current definition (section 10). Postseason calls are published and
graded and not counted, exactly as V2 11.1, until a postseason adjustment exists
(01 section 3c measured October prop probabilities 6 to 11 points high and the model has no
postseason term; this registration does not add one).

## 8. What each result licenses

* The brief's record licenses a description of what was published and how it graded.
* No V3 result licenses a claim of edge, value, or a guarantee, and customer copy stays
  inside `tests/test_customer_language.py`.
* A `PASS` under section 5 licenses one thing: opening the separate registration that
  would add `R`'s picks, subject to owner sign-off. It never licenses a statement about
  any other rule, class or market.

## 9. V2 at the moment of successor registration

V2's registration (11.4, "A successor before the read") requires the successor's
registration commit to publish V2's closing-line value and ROI **at that moment** as a
named non-verdict read, "V2 interim at successor registration", so that abandoning V2 after
a bad run is visible. The block below is the draft of that read, **from the loss
diagnosis' figures as of 2026-10-15 settlements**, and **must be recomputed from
`evidence/cards_v2.jsonl` at the registration commit** (`python3
scripts/diagnosis/prices.py --section clv` and `selection.py ledger`). It is a
non-verdict read: no floor was met (V2's floors are 300 counted picks with a closing-line
value and 300 graded across 60 slate dates), and it licenses nothing.

| quantity (all hindsight, V2 open window 2026-09-22 to 2026-10-15) | value |
|---|---|
| graded entries (picks, fills, withdrawn) | 178: 97-81, -1.42u (ROI -0.8%) |
| excluding the 17 withdrawn picks (what `record_v2` reports) | 161: 86-75, -6.43u |
| public headline (regular-season MAIN picks, counted) | 16-17, -5.05u; postseason shown, not counted: 27-33, -9.22u |
| mean closing-line value, graded price vs de-vigged close | -1.69 points per bet [-2.09, -1.28], 82 measurable of 178 |
| same results at the board-average price (not the graded price) | -4.04u on the 170 with a rebuilt board (-0.69u at the graded price), `docs/decisions/card_v3/measured_grade_average_odds.json` |
| expected units at the market's own numbers | -7.55u |

V2's counted sample **ends at V3's registration commit** (proposed; section 12 Q1). Its
ledger stops accruing counted picks, stays on the record, and keeps being settled. V2 is
not re-read after that; its interim read above is its last published figure.

## 10. Code fingerprint and the read rule

`code_fingerprint` (V3) is the sha256 of the exact bytes of, in this order, each file
named, as in `src.appstate.card_ledger.code_fingerprint()`:

1. `src/analysis/strength.py`
2. `src/analysis/playerprops.py`  *(patch 1)*
3. `src/analysis/propboard.py`  *(patch 2)*
4. `src/report/props.py`  *(patch 2)*
5. `src/analysis/best_bets_card.py`  *(patch 3)*
6. `src/report/card_v2.py`  *(patch 2)*
7. `src/analysis/prices.py`  *(patch 2; produces the moneyline average)*
8. `src/analysis/opportunities.py`  *(patch 2)*
9. `src/appstate/card_ledger.py`  *(patches 2, 4, 5; settlement and lock)*
10. `data/processed/card_v2_frozen_params.json`
11. the brief renderer module, named when it exists (not written by this draft)
12. any module `docs/PREREG_INFO_TIMING.md` registers for its own rule (that file's
    fingerprint is its own; it is listed here only so the V3 row never claims a model
    the other registration changed)

**Open decision (section 12 Q2):** V2 left `card_ledger.py` out of its fingerprint (it is
a member of the V1 shadow fingerprint, `V1_FINGERPRINT_FILES`; V2's section 16 log records
three settlement edits to it on 2026-09-23, 09-25 and 09-27 that did not restart V2's
sample). V3's settlement and lock rules live in that file, so leaving it out would let a
change to how a call is graded go undetected. Two options:
(a) hash the whole file (V2's convention; a V1 edit restarts V3's count), or (b) hash a
normalised digest of only the named functions (`settle_v2`, `_grade_at_average_odds`,
`_lock_and_merge_v2`, `_lock_moneyline_fill_at_board_price`, `record_v2`, `history_v2`,
`_frozen_v2_entry`, `V2_FROZEN_FIELDS`). Recommended: (b), which needs a small helper that
this draft does not write.

**Read rule.**
* A change to any fingerprinted file or to the model id restarts the counted sample.
  Calls from before the restart stay on the record and are reported as their own count.
  Comment-only, docstring-only and customer-copy-only edits are not changes, and a
  fingerprint change made only of those is reported as such (as V2 11.6 does for V1).
* The two content-fingerprint pins in `tests/test_card_v2_candidate_enumeration.py`
  (`V1_CONTENT_FINGERPRINT`, `V2_CONTENT_FINGERPRINT`) fail the moment a patch is applied.
  That is the tripwire working. The registration commit updates them in the same commit
  that applies the patches and writes the new `code_fingerprint` here.
* There is **no early read** of any V3 figure other than the running record (a record is
  not a read). Section 5's interval is computed once per candidate rule, at its 150th
  measurable bet, by a script committed before the sample starts.
* A read that cannot be reproduced from `evidence/` and the committed scripts is void.

## 11. Record keeping

* The V3 ledger is its own hash-chained store (proposed `evidence/cards_v3.jsonl`); V2's
  store is untouched.
* Every row carries the V3 `code_fingerprint`, the quote instant and quote age of every
  price shown, the average and best price, `stale_board`, and `graded_price_basis`.
* No `alpha_registry` row is created by this draft. The row is created in the registration
  commit, with the status line changed from DRAFT to REGISTERED and the
  `REGISTERED_UTC` set.

## 12. Owner decisions this needs

Each is one yes or no and none is answered by this draft.

1. **Retire V2 as the public value card at V3 registration, ending its counted sample?**
   (Section 9.) The alternative is to keep V2 running unmodified in parallel until its own
   read; the cost is a public card that the diagnosis says pays a premium on every bet.
2. **Fingerprint `card_ledger.py` whole, or by a normalised digest of the named
   functions?** (Section 10.) Recommended: the digest.
3. **Carry the -200 ruling literally onto a brief that makes no bets?** (Section 2.) The
   ruling was about picks. If the brief is not a pick, a heavy favourite could be
   *called* and graded; the draft does not do that, to stay inside the ruling as written.
4. **Confirm that "always three bets with labelled fills" (2026-09-15) is superseded for
   the V3 product.** It was an instruction about a value card; a brief that calls every
   market has no floor of three and no fills. The draft assumes it does not apply.
5. **Confirm the plus-money wish is deferred.** The owner has asked for +100 to +250
   underdogs. The only plus-money evidence is negative or null (V2's own registration
   expects the class to read `UNDERPOWERED` rather than reach a verdict, 11.4; the 2024
   rebuild of the enumerated plus-money moneyline class went -8.1% over 379 bets; SR1 was
   killed, `UNDERPOWERED_NULL`). Under this draft plus money returns only through
   section 5.
6. **Product naming and customer copy** go through `tests/test_customer_language.py` and
   the existing copy rules; this draft writes none.

## 13. Amendment log

| date | change |
|---|---|
| 2026-10-16 | Draft written from the loss diagnosis and the patches in `docs/decisions/card_v3/`. Not registered. |
