# Card V2 diagnosis: why the card publishes best favourites, not best bets

Written 2026-09-15 for roadmap item R16-34. Diagnosis only: no code, ledger or
config was changed to produce it. The successor rule is registered separately
in `docs/PREREG_CARD_V2.md` and its build is in `docs/CARD_V2_BUILD_PLAN.md`.

---

## 0. Bad news first: the card model has already used the sealed window

The canonical split, verbatim from `docs/DEBRIEF.md:24-28`: "2023–24 discovery
· 2025 tuning-only forever (its `2025-08-26..2025-09-28` sub-split is already
burned by four looks) · **2026-01-01 → 2026-08-27 SEALED**, one evaluation
ever, only after a policy freeze plus Brey's explicit go · 2026-08-28 onward is
forward proof, never folded back into tuning." The roadmap adds "never touch
sealed 2026 without explicit instruction" and lists "anything touching sealed
2026-01-01→08-27" as a hard stop (`docs/ROADMAP.md:31,50`).

**What happened (observed).** The model behind V1's card, the one this morning's
picks were built on, was fitted and evaluated on sealed-window games, starting
2026-09-10:

- **The card calibration** was refit every night by
  `scripts/fit_card_calibration.py` from `scripts/daily_loop.sh`, on every
  completed 2026 game from 2026-04-15, until the owner stopped it on
  2026-09-15. Of the 1,901 rows it selects on this
  machine's stores, 1,753 (92.2%) are dated 2026-04-15 to 08-27 and 148 are
  forward games from 2026-08-28, which the split says are "never folded back
  into tuning". Counted by date only, no outcome read
  (`scratchpad/card_v2_revise/fit_window_counts.py`). The committed file
  changed with each refit: `b` 0.744719 (through 09-13), 0.769145 and 0.735183
  (both through 09-14, the second at 21:04Z today).
- **`DISPERSION = 2.3352`** was fitted on 2026-04-15 to 07-15 and checked on
  2026-07-16 onward (`docs/PREREG_RUN_DISPERSION.md:131,213-216`).
- **The prop correlation `RHO = 0.05065`**, used on every `batter_hits` prop,
  was fitted on 2026-06-17 to 08-05 and tested from 2026-08-06
  (`src/analysis/playerprops.py:522-548`).
- **The walk-forward "0.0012 nats over 1,896 games"** (section 2.2) is an
  evaluation over 2026-04-15 to 2026-09-06 (`docs/THE_CARD.md:197-199`).

No document found records a policy freeze or Brey's explicit go for any of
these: neither `docs/THE_CARD.md` nor `docs/PREREG_RUN_DISPERSION.md` mentions
the seal. The research code refuses the window by name
(`src/evolab/replay.py:124-126`); the card model's fit and backtest scripts
have no guard. **As the repo words the rule, it has been broken since
2026-09-10, and the nightly refit broke it again every night until it was
stopped on 2026-09-15.**

**What it costs (interpretation, not a measurement).**

1. The seal's one evaluation cannot confirm any rule built on this run model,
   its calibration or the prop model: their parameters were chosen on the
   window and the model was evaluated on it repeatedly. That covers V1 and any
   V2 that keeps these fits.
2. V1's own forward record through 2026-09-15 is of a model whose calibration
   changed every
   night. `docs/VALIDATION_CRITERIA.md` says "Changing the model restarts the
   sample", so no V1 closing-line or return verdict can be drawn from that
   record. The freeze of 2026-09-15 stops the change from here on; it does not
   repair the record behind it.
3. It does not make V1's forward picks leak: each night's fit uses only games
   finished before that card (the script's docstring; `fitted_through` is
   always the day before). The breach is of the seal and of the
   forward-proof clause, not of point-in-time correctness.

**Decided by the owner on 2026-09-15, about 22:35Z.** Whether V1's nightly
refit keeps reading the sealed window was Brey's to decide (roadmap hard stop
2), and it changes the live card, so this document proposed nothing. It was put
to him beside the V2 questions in plain words, with the options "Freeze it now
(Recommended): lock today's model settings for the current card until the new
card replaces it; picks barely change; the protected games stop being used" and
"Keep refitting". **He answered "Freeze it now."** V1's nightly calibration
refit is stopped and today's calibration settings, the file's `a` and `b`, are
locked for the current card until V2
replaces it; the implementation and its record are
`docs/CARD_CALIBRATION_FREEZE_2026-09-15.md` (commit `ba09312c`), written
separately, and no number
in this document changes because of it. What the freeze does not do is undo the
reads already made: the seal was used, and the consequences in the next
paragraphs stand. What it also does not do is freeze the rest of V1: that
record says in terms that it covers only `a` and `b` and says nothing about
`DISPERSION` or `RHO`, and V1's selection code stays live and editable, so any
later comparison against V1 is read against the `v1_code_fingerprint` of
`docs/PREREG_CARD_V2.md` section 10 rather than assumed stable.

The successor rule's decision on these fits, with
its options, is `docs/PREREG_CARD_V2.md` section 1.2. Whether V2 may keep the
two made only on sealed-window games, `DISPERSION` and `RHO`, was owner
question 3, answered no the same day ("Rebuild on 2025"): V2 keeps neither, and
every number it uses is fitted once on 2025 and frozen. V2 does not keep the
card calibration under any answer, because its fit
also reads forward games, and the split reserves no go for that.

**Evidence status of every other number here.** Everything computed from the
card ledger, the paper accounts or today's board is **EXPLORATORY**: it was
read off data that already existed, no pre-registration covered the cut, and
it cannot count as evidence for or against any rule. The power calculation in
section 4.4 is arithmetic, not an observation. No table below reads a game,
price or result dated 2026-01-01 to 2026-08-27 or any 2025 result; every table
is built from 2026-08-31 onward. The model numbers ("ours") in those tables,
on the card and in the candidate pool (`scratchpad/card_v2/build_pool.py:146`
loads the card calibration), still come from the fits above.

---

## 1. What the owner saw and asked

Brey, 2026-09-15, 10:00am PT, verbatim, sent with five phone screenshots of
that morning's staging card:

> "I'm not feeling confident that our best picks for the day are showing not
> only strong confidence but also good value. Again, we're trying to find the
> best bet, something that has really good value, so that we don't throw one
> unit to risk winning 0.25 or 0.3 units back. The goal is to find the best
> bets for the day, not the best favorites.  If the price is -200 or higher,
> it's typically not going to be a good bet because not only do they expect
> them to win, but there's no value in it. If they lose, you have to risk so
> much to win even anything noticeable. The idea would be that the 3-10 bets
> for the day are the best of the best of the best of the best bets. Not only
> are they -150, -115, +100, or higher, but they wouldn't be any lower than
> -150 or -160, if that makes sense. If it's a high-confidence bet and the
> value is great, that's what we're looking for. Also, we need to find out how
> to make a live bet system and incorporate it into our MLB, as well as the NFL
> and tennis."

The screenshots showed picks 4 to 8 of 8. The full card is the newest
published row for 2026-09-15 in `evidence/cards_v1.jsonl`: rule
`DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1`, published 2026-09-15T16:42:48Z
(the 13th version that day), row hash beginning `7258f88f`, `totals_paused`
true, nothing filled from the SPLIT pile. Read with
`card_ledger.published_row("2026-09-15")`. "Market" is the de-vigged
multi-book consensus frozen on the pick; "ours" is the frozen model or prop
probability; "needs" is the break-even of the published price
(`src.core.odds.american_to_probability`).

| # | Published bet | Book (books) | Label | Market | Ours | Needs | Quote observed |
|---|---|---|---|---:|---:|---:|---|
| 1 | Take Dodgers to win at -230 | lowvig (11) | STRONG | 67.6% | 59.7% | 69.7% | 14:31:29Z |
| 2 | Take Rays to win at -225 | fanduel (11) | STRONG | 67.2% | 59.4% | 69.2% | 14:31:29Z |
| 3 | Take Brewers to win at -210 | betus (11) | STRONG | 66.1% | 60.3% | 67.7% | 14:31:29Z |
| 4 | Take Phillies to win at -210 | betus (11) | STRONG | 65.8% | 53.9% | 67.7% | 14:31:29Z |
| 5 | Take Padres to win at -186 | betrivers (11) | STRONG | 63.2% | 50.7% | 65.0% | 14:31:29Z |
| 6 | Take Cole Young under 1.5 total bases at -184 | draftkings (3) | STRONG | 61.1% | 66.5% | 64.8% | 04:09:34Z |
| 7 | Take Matt Olson under 1.5 total bases at -157 | williamhill_us (4) | STRONG | 57.8% | 65.7% | 61.1% | 04:09:29Z |
| 8 | Take Michael Harris II under 1.5 total bases at -148 | williamhill_us (3) | STRONG | 57.0% | 64.9% | 59.7% | 04:09:29Z |

What the table says, plainly:

- All 8 carry STRONG and all 8 say "Take".
- All 8 are priced -148 or shorter. Three of the five game picks the owner did
  not see were shorter than the ones he did (-230, -225, -210).
- On all 5 game picks **both** the market's number and our own number are
  below what the price needs. The owner flagged Phillies and Padres; the same
  is true of Dodgers, Rays and Brewers.
- On all 3 props the market's number is below what the price needs and our
  number is above it. All 3 are Unders, all 3 have no posted lineup, all 3
  rest on 15 games of history, and all 3 are priced at 3 or 4 books.
- Every game quote was 2 h 11 min old at publication (observed 14:31:29Z,
  which is also the newest row in `data/processed/odds_multibook.jsonl` on this
  machine). Every prop quote was 12 h 33 min old.
- All 5 game picks carried knowledge grade C.

---

## 2. Why V1 published these picks

V1 is doing what it was written to do. The defect is in what it was written to
do, and in the copy that describes it. Every line reference is to the file as
committed at `0fb4b03a`.

### 2.1 The moneyline path has no price test at all

`src/analysis/daily_card.py`:

- **Side.** `_consensus_side` (`:418-429`) takes whichever side the market's
  consensus makes more likely. That is always the market favourite.
- **Agreement.** `agrees = model_p > 0.5` (`:474`). This is the whole of the
  model's role on a moneyline pick: our number has to lean the same way at
  all. It never has to clear the price.
- **Compare the other two kinds.** Totals refuse a candidate unless
  `model_p > breakeven` (`:872-876`). Props refuse unless
  `probability > breakeven` (`:1271-1272`). Nothing in
  `build_pick_candidates` (`:446-531`) or `select` (`:632-680`) does the same
  for a moneyline. Padres at 50.7% against a 65.0% break-even passes.

### 2.2 Ranking by market confidence selects the shortest prices

`_rank_key` (`:608-629`) sorts by `confidence`, the market's consensus
probability, descending, with price standing only as a tie-break. A higher
market probability is a shorter price, so the rank key pushes the most
expensive favourites to the top by construction. `select` then takes up to
`MAX_PICKS = 5` (`:91`). There is no price ceiling anywhere in the module.

The module docstring records why it ranks by the market and not by our model:
the run model beats a home-field base-rate coin by 0.0012 nats walk-forward over
1,896 games (`:43-50`; an evaluation over 2026-04-15 to 2026-09-06, so mostly
sealed-window games, quoted here and not re-run), so ranking by
model-versus-market disagreement selects the model's own largest errors (the
2026-09-09 incident). V2 keeps that reasoning for its ranking. It does not
escape it entirely: V2's price test works in practice as a positive
model-over-market disagreement filter (`docs/PREREG_CARD_V2.md` section 4).
What V1 never added was the second half the owner asked for on 2026-09-11:
once a bet is likely, check the price.

### 2.3 STRONG is not a value label, and it means two different things

- **Game picks.** `_label` (`:403-411`) returns STRONG when
  `confidence >= BAND_STRONG` (`:108`, 0.62), read off the market's moneyline
  consensus. Any favourite priced around -165 or shorter clears it. STRONG on a
  game pick means "the market is at least 62% sure", nothing else.
- **Props.** `_prop_label` (`:1022-1031`) applies the same 0.62 band to **our
  own** number, not the market's. Today's three props are STRONG because our
  number said 65 to 67%, while the market said 57 to 61%. That is the direction
  `docs/PROP_CALIBRATION_2026-09-14.md` measured as overconfident: among
  contracts both numbers call likely, Unders hit 53.6% against our 61.7%
  (n=332), and where our number ran 10 or more points above the market's, n=32
  hit 40.6% against our 62.1%.
- **The legend is wrong on both.** `web/js/card.js:49` explains STRONG as "The
  market and our numbers both make this side a clear favourite." On today's
  game picks our number is 51 to 60%, and on today's props the market is 57 to
  61%. The code comment at `web/js/card.js:176-186` already notes the sentence
  "on most picks it is not even true" and removed it from the card face, but it
  stays in the tooltip and legend.

### 2.4 "Take" is unconditional; the honest sentence is prose, not a gate

`_bet_sentence` (`:221-231`) writes "Take ..." for every published pick. The
sentence under it, "lower than the market, so we agree on the winner but the
price is against you. This is a read on the game, not value at this price. At
-210 you need 68% to break even." comes from `_why_sentences` (`:342-348`,
with the break-even added on 2026-09-11 at `:305-330`). It is computed after
selection and nothing reads it back. So the page can print "not value at this
price" directly under a STRONG "Take". The 2026-09-11 fix made the gap
readable; it did not make it matter.

### 2.5 Why 8 picks when the maximum is 5

`MAX_PICKS = 5` bounds only the moneyline array. The card is three arrays:
`picks` (at most 5), `total_picks` (at most `MAX_TOTAL_PICKS = 3`, `:726`, but
zero while `TOTALS_ON_CARD = False`, `src/report/card.py:583`) and
`prop_picks` (at most `MAX_PROP_PICKS = 3`, `:960`). `merge_all_bets`
(`:1405-1464`) builds one ranked view and `web/js/card.js:970-991` renders that
view as one list numbered against its own length. Five plus three is eight. No
cap was broken; three caps were stacked and shown as one list with one label
vocabulary.

### 2.6 Run lines can never be the pick

`RUNLINE_AS_ALTERNATIVE = True` (`:144`) and `_attach_run_line`
(`:544-601`) attach the run line only as an alternative beside the moneyline
favourite. A run-line underdog can never be selected. On today's board the only
game-market candidates inside the owner's price range where our number cleared
the price and sat within 10 points of the market's were two run-line underdogs,
Angels +1.5 at -114 and Twins +1.5 at -112 (section 5.3). V1 could not see
either. (The comment block above `:144` also still says the run-distribution
correction "is NOT being applied yet"; `src/analysis/strength.py:186` has
applied `DISPERSION = 2.3352` since its adoption on 2026-09-10. The comment is
stale.)

### 2.7 No freshness test on the price

Neither `select` nor `select_props` checks how old a quote is. The card is
republished every capture slot (`scripts/capture_slot.sh:484-506`), but a slot
that has no newer board republishes the old one. Today that meant 2 h 11 min
old game prices and 12 h 33 min old prop prices at 16:42Z.

### 2.8 A docstring that says a gate exists when it does not

`prop_rank_probability`'s docstring (`:1350-1362`) says "both our probability
and the market's clear the contract's own break-even". The code (`:1380-1387`)
requires the market's number to clear 50% and **our** number to clear the
break-even. The orchestrator comment directly above the code (2026-09-14)
records that requiring the market's number to clear break-even was tried,
blocked nearly everything, and is line shopping. One of the three Card V2
design proposals read the docstring literally and specified a gate that passes
0 of 138 candidates on today's board. The docstring should be corrected.

### 2.9 Nothing audits any of this

`scripts/publication_audit.py:402` (`audit_card`) checks the pick-count floor,
started-game leakage, price and book presence, calibration staleness and the
hash chain. It has no check for a price band, for "Take" on a pick our own
number prices below break-even, for STRONG share on the card, or for quote age.
Today's card would pass it.

---

## 3. What STRONG and the "C" chip mean today, and the debrief sentence

### 3.1 The debrief sentence was misleading

This morning's `docs/DEBRIEF_LATEST.md:8-9` says: "One is a research grade that
has been firing on almost every pick since September 10 (customers never see
it)."

**That is misleading, for two separate reasons.**

1. **The research grade is on a public page.** The grade is the engine slip's
   evidence tier (`EVIDENCE_STRONG`, `src/engine/slip.py`), the subject of
   `docs/INCIDENT_2026-09-10_STRONG_TIER.md`. It is rendered as a chip by
   `evidenceTierChip` (`web/js/slip.js:44`, called at `:83`) inside
   `renderEngineSlipSection` on `#/performance`
   (`web/js/performance.js:575`, mounted at `:680`), which reads the `slip`
   field of `GET /today` (`api/today.py:161`). That page is linked from the
   site footer on every page as "RESEARCH" (`web/js/meta.js` as committed at
   `0fb4b03a`, lines 175-176). Its eyebrow calls it the engine's own slip and
   research, not the card, but any visitor can reach it. On this machine's copy of
   `evidence/slips_v1.jsonl`, the newest slip row per date shows: 2026-09-11,
   6 picks, all STRONG; 2026-09-12, 1 pick, STRONG; 2026-09-14, 3 picks, all
   STRONG; 2026-09-10, 2026-09-13 and 2026-09-15 (so far), `NOTHING_CLEARED`,
   for which the section renders nothing. So on three of the five dates from
   2026-09-10 to 2026-09-14, the slip that page served at the end of the day
   carried only STRONG chips. (Earlier rows on those dates were not checked.)
2. **The STRONG the owner was looking at is a different label.** The card's
   STRONG comes from `daily_card.BAND_STRONG` (section 2.3), is on the page
   customers land on, and was on 8 of 8 picks this morning. The incident doc
   says so itself: "THE CARD is unaffected. It does not use these tiers."
   The debrief sentence answered a question about a system the owner was not
   looking at and did not mention the one he was.

The underlying fact about the engine tier is true: it fires on almost every
engine pick, and `scripts/publication_audit.py` prints
`STRONG_TIER_RECALIBRATION_OWED` on every run. The parenthesis was the false
part.

### 3.2 STRONG on the card

See section 2.3: market consensus at least 62% for game picks, our own number
at least 62% for props. It measures neither value nor our confidence in the
bet. On the graded record it is the label most concentrated at short prices:
14 of 15 graded STRONG game picks were priced -161 or shorter (section 4.2).

### 3.3 The "C" chip

The letter is the knowledge grade from `src/analysis/grade.py`, not a
confidence or value grade. Its bands (`grade.py:44-53`): A means lineups
posted, both starters named, a board at or above the book floor, and a board
captured within `FRESH_SECONDS` (3,600 s); C means "a board exists but lineups
OR starters are missing". All five game picks were C at 16:42Z because evening
lineups post between 17:16Z and 22:39Z (`docs/CARD_PUBLISH_WINDOW.md`). It is
frozen with the pick (`card_ledger.FROZEN_FIELDS`, `:66-89`) and rendered at
`web/js/card.js:116-129`. `docs/DESIGN_SYSTEM.md` section 4 already removes
grade chips and STRONG/LEAN/SPLIT chips from the card face.

---

## 4. The graded record by price band (EXPLORATORY)

### 4.1 The headline

`card_ledger.record()` with no arguments reads `evidence/cards_v1.jsonl`,
settled rows only: 5 days (2026-09-10 to 2026-09-14), 26 wins, 12 losses, 0
pushes, 0 voids, 38 staked, win rate 0.6842, +4.8194 units. That is the "26-12,
68%, +4.82 units" on the staging card. **It counts game picks only.** Props are
in `by_kind.prop`: 9 wins, 5 losses, -0.6418 units, not in the headline.
Combined, 35-17 and +4.1776 units. The successor registration requires every
record block, V1's closed one included, to show all kinds together and each
apart (`docs/PREREG_CARD_V2.md` R5, C8). Totals: none staked; every row since
2026-09-14 has `totals_paused` true.

### 4.2 By price band

Store `evidence/cards_v1.jsonl`, rows of kind `card_settled`, picks with result
WIN or LOSS, bucketed on the published price. Script:
`scratchpad/card_v2/verify_bands.py`.

**Game picks (37 moneyline, 1 run line), n=38**

| Price band | Bets | W-L | Win % | Avg needs | Units | ROI |
|---|---:|---|---:|---:|---:|---:|
| -200 or shorter | 3 | 3-0 | 100.0% | 67.5% | +1.443 | +48.1% |
| -199 to -161 | 13 | 9-4 | 69.2% | 64.4% | +0.940 | +7.2% |
| -160 to -150 | 4 | 3-1 | 75.0% | 61.2% | +0.903 | +22.6% |
| -149 to -120 | 15 | 9-6 | 60.0% | 56.7% | +0.795 | +5.3% |
| -119 to +100 | 3 | 2-1 | 66.7% | 52.7% | +0.739 | +24.6% |
| longer than +100 | 0 | | | | | |

**Game picks, label by band (counts)**

| Label | -200 or shorter | -199 to -161 | -160 to -150 | -149 to -120 | -119 to +100 | Total |
|---|---:|---:|---:|---:|---:|---:|
| STRONG | 3 | 11 | 0 | 1 | 0 | 15 |
| LEAN | 0 | 2 | 3 | 8 | 0 | 13 |
| SLIGHT | 0 | 0 | 0 | 4 | 2 | 6 |
| SPLIT | 0 | 0 | 1 | 2 | 1 | 4 |

**Prop picks, n=14**

| Price band | Bets | W-L | Win % | Avg needs | Units | ROI |
|---|---:|---|---:|---:|---:|---:|
| -200 or shorter | 8 | 5-3 | 62.5% | 71.6% | -1.015 | -12.7% |
| -199 to -161 | 4 | 3-1 | 75.0% | 63.6% | +0.724 | +18.1% |
| -160 to -150 | 1 | 1-0 | 100.0% | 60.6% | +0.649 | +64.9% |
| -149 to -120 | 1 | 0-1 | 0.0% | 56.9% | -1.000 | -100.0% |
| -119 or longer | 0 | | | | | |

Read these as a description of what V1 selects, not of what wins:

- 16 of 38 graded game picks and 12 of 14 graded props were priced -161 or
  shorter. No graded pick of either kind was plus money.
- 22 of 38 game picks were already inside a -160 limit. The problem is
  concentrated in the label the page presents as the best: 14 of 15 STRONG
  game picks were -161 or shorter.
- Every cell is 0 to 15 bets over 5 days. Section 4.4 shows why none of the
  ROI differences between cells means anything.

A closing-price comparison per band was also computed during this review
(`scratchpad/card_v2/clv_bucket.py`, 37 of 37 moneyline picks measurable). It
compares a price with the vig in it against a close with the vig removed, which
is negative by construction and more negative at shorter prices, so it cannot
separate bands and is not read here. That same price-against-close measure is
the pass/fail metric the successor registration uses, read forward only, where
it is expected to be hard to pass (`docs/PREREG_CARD_V2.md` 11.3). Props had no
closing board with the six books `src/report/clv.py` requires.

### 4.3 Other forward records, briefly

- The 14 forward-test paper systems with at least 30 graded selections
  (`data/paper_accounts/*.jsonl`, 2026-08-31 to 2026-09-14, all moneyline)
  placed 250 of 532 bets at longer than +100, computed during this review by
  `scratchpad/card_v2/paper_bucket.py`. The card's absence of plus-money bets
  is a property of the card's rule, not of what the engine prices. Their
  pooled band returns are not quoted: they pool different systems, and in the
  -160 to -150 band 26 losses came from 8 games, which is the pooling mistake
  `card_ledger.record()`'s own docstring warns about.
- The one backtest of the card rule itself, quoted from
  `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md:67-72` and not re-run: every
  consensus favourite, n=97, ROI -7.8% [-25.1, +9.5]; favourite with model
  agreement, n=72, ROI -9.7% [-29.1, +9.8]. The document reads none of the
  point estimates. Open check: `scripts/backtest_card_rule.py:23` says its
  store starts 2026-08-27, which is the last sealed day. Whether any
  2026-08-27 game is inside its 97 was not checked here; it is a task in the
  build plan.

### 4.4 Power: what sample would tell price bands apart

For a flat one-unit bet at decimal odds d with no edge, the variance of the
return is d - 1. Two-sample comparison, two-sided alpha 0.05, 80% power, bets
needed **per band** (`scratchpad/card_v2/power2.py`):

| Band A | Band B | True ROI gap 3 points | True ROI gap 5 points |
|---|---|---:|---:|
| -210 | -150 | 9,967 | 3,589 |
| -210 | -120 | 11,421 | 4,112 |
| -210 | +100 | 12,874 | 4,635 |

One band against zero: at 300 graded bets the 95% interval on ROI is about
plus or minus 8.9 points at -160, 9.2 at -150, 10.6 at -115 and 11.3 at +100.
Detecting a true +5% ROI against zero with 80% power needs about 2,094 bets at
-150 and 2,731 at -115.

The card ledger has 0 to 15 bets per band. **No record on disk can say whether
short favourites or mid-priced bets return more.** The case for a price band is
the owner's payout-shape preference plus the arithmetic that a short price
needs a high win rate, not a measured return difference.

---

## 5. Where honest value can and cannot come from today

### 5.1 What cannot supply it

| Source | Status | Where |
|---|---|---|
| Our model beating the market | Not shown by any of five measurements; the pre-registered prop head-to-head is UNDETERMINED, paired diff +0.00655 nats, 95% CI [-0.00137, +0.01455] | `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md` |
| A large gap between our number and the market's | Measured as a warning sign: n=32 props with our number 10+ points above hit 40.6% against our 62.1% (p=0.011) and the market's 50.2% (p=0.181) | `docs/PROP_CALIBRATION_2026-09-14.md:44-47` |
| Best price beating the market's own number (line shopping) | Ruled out by the owner on 2026-09-10 and 2026-09-11. Also empty on today's board: 0 of 82 game-market sides (moneyline, run line, totals) and 0 of 56 props had a best price whose break-even was below the market's own number, where the 56 props were only the side the market already makes likely. One board, not a general finding | `probability-before-price` directive; `docs/RESEARCH_CATALOGUE.md` L5; `scratchpad/card_v2/candidate_pool_2026-09-15.csv` |
| A pre-registered research family | Four completed MLB moneyline families, V1, V2, V4 and V5, zero survivors | `docs/RESEARCH_CATALOGUE.md:36` |

### 5.2 What can supply it, and what each licenses

1. **The market's number as the likelihood read.** It is the best-measured
   predictor in the repo (it beats a public-grade Elo, log loss 0.67275 against
   0.68076, p=0.0003, `docs/RESEARCH_CATALOGUE.md:134`). Using it for "more
   likely than not" needs no new evidence. It licenses "the market makes this
   more likely than not", nothing about return.
2. **Arithmetic on the price.** A break-even is not a model claim. Gating on it
   is how "Take" stops appearing under "the price is against you".
3. **Our own number, used only to remove.** Our number may decide whether a
   likely, in-range bet is a pick. It must never rank, and a large disagreement
   must disqualify. On today's board this is the only place a V2 "Take" could
   come from, because the market's own number cleared the best price on none
   of the candidates (5.1). Used this way it still selects bets where our
   number sits a few points above the market's, which is a disagreement band
   nobody has measured. **The customer copy has to say that on every pick.**
4. **A forward, pre-registered measurement.** Closing-line value at the price
   taken, as `docs/VALIDATION_CRITERIA.md` defines it, and the realized return,
   read once at its floors (300 graded picks). Only that can later earn a
   claim.
5. **An information edge or live markets.** Unbuilt or research-only
   (`docs/INFORMATION_EDGE_FIRST_LOOK.md`; four live hypotheses registered in
   `docs/PREREG_MULTI_SPORT_2026-09-14.md` with zero reads; the live system is
   R16-35). Nothing here reaches the card.

### 5.3 What a price-gated card would have shown today

Applying the rule registered in `docs/PREREG_CARD_V2.md` to the already-seen
2026-09-15 board (illustration only, the full walk is section 14 of that
file):

Re-run on 2026-09-16 under the revised rule, after the owner's four answers of
that morning. The figures below replace the pre-revision ones.

- With the one-hour freshness gate: **0 picks and 3 fills**, because every
  price on file was more than 2 hours old. Under his answer of 2026-09-15
  ("Always show 3") the card fills to three with the closest calls, each
  labelled as not a pick and each graded on the record: Angels +1.5 at -114,
  **Reds +1.5 at +124** and **Athletics to win at +202**, all three failing
  only the freshness check, all three at prices over two hours old. Two of the
  three are plus money, which could not have happened before his 2026-09-16
  answer, and each carries the plus-money line on its face.
- With freshness set aside: **5 picks, 0 fills**, ranked by the score he asked
  for, both classes interleaved: Angels +1.5 at -114 (market 52.0%, needs
  53.3%, our number 61.3% raw and 57.5% after the markdown); Reds +1.5 at +124
  (43.7%, 44.6%, 52.7% raw); Athletics to win at +202 (32.8%, 33.1%, 41.1%
  raw); Orioles to win at +117 (45.2%, 46.1%, 52.5% raw); Michael Harris II
  under 1.5 total bases at -148 (57.0%, 59.7%, 64.9% raw). Three of the five
  are plus money, and **one** of those three is in the 30-to-45 per cent band
  of our own number he named: the Athletics at 41.1%. The other two sit just
  above 0.50 on the raw number and fall below it only after the markdown. (An
  earlier version of this line said two of the three, counting the Reds
  moneyline at 41.4% that G11 dropped; corrected 2026-09-16, with the same
  correction in `docs/PREREG_CARD_V2.md` 14.2.) The prop exists only because
  the lineup test left G10. Reds
  to win at +206 and Angels to win at +149 scored higher than two of the
  published picks but lost their games to a higher-scored entry (one per game),
  and Pirates to win at +190 was dropped by the plus-money sub-cap.
- What the rule refused that a looser one would have taken: Rockies +1.5 at
  +106, where our raw number is 16.9 points above the market's, tied with two
  other candidates for the largest gap on the board, a larger gap
  than the tail `docs/PROP_CALIBRATION_2026-09-14.md` measured hitting 40.6%
  against a 62.1% claim. The disagreement cap refuses it and is not loosened
  for the class the owner is most enthusiastic about. It is the top-ranked
  entry on shadow A's list, which is what that shadow exists to measure.
- These numbers come from the model as it stands, with its sealed-window fits
  and raw run-line numbers; the registered model, fitted once on 2025 by the
  owner's answer to question 3, would differ.

- **What his confidence band actually gets, which he has not been told until
  now.** He wrote "even confidence of 30-45+ percent if high enough value
  (+150, +200 etc etc)". The rule can serve the top of that band at the long
  end of those prices and cannot serve it at +150, the first price he named.
  The bar G7 puts on our raw number is 55.03% at +100, 45.34% at +150, 43.86%
  at +160, 38.98% at +200 and 34.53% at +250, so a number inside 30-to-45 can
  be a pick only from about +152 upward, and 30 per cent itself is out of reach
  at every allowed price. That also means the 0.30 floor he named (G6) can
  never refuse a pick: the value test is stricter than it everywhere. This is
  arithmetic from the 3.8-point markdown and the required edge, not a judgement
  about his instinct, and it is now question 11 in
  `docs/PREREG_CARD_V2.md` section 15, for him to settle before registration.
  Opening the short end means cutting the markdown, which is the one mechanism
  answering the fact that every measured bucket of our number runs hot.

That is the honest shape of the answer to the owner. Inside the price range he
first named, "high confidence" by the market's number and "the price pays
enough" do not coincide, which is why the card was thin. His 2026-09-16 answers
open the plus-money band, and that is where most of the card now comes from:
three of five picks, each resting on our own number, marked down, sitting a few
points above what the price needs. That is more bets, and it is also more
weight on the number this project has never checked below 50 per cent
(`docs/PREREG_CARD_V2.md` 0.2 and 11.9). The owner has chosen to keep three
entries a day as well, with the shortfall made up by bets the rule itself calls
not picks, published, labelled and graded apart
(`docs/PREREG_CARD_V2.md` sections 6 and 15, question 1).

### 5.4 The calendar

The 2026 regular season ends 2026-09-27 (`docs/SEASON_END_PLAN.md:11`), at
most 12 slate dates after this one. `docs/VALIDATION_CRITERIA.md` draws no
verdict below 300 graded picks. At about 2 counted game picks a day the read
falls around August 2027 with no model restart, and not in 2027 at 1 a day. A
restart is likely: the model's files changed in 15 commits between 2026-09-10
and 09-14, and the prop board hard-codes the 2026 box-score store. Before any
of that, the registered model needs a 2025 data backfill and a
one-time 2025 fit, which the owner chose on 2026-09-15 ("Rebuild on 2025";
section 0, `docs/PREREG_CARD_V2.md` 11.2), so no V2 pick is
counted until that work is done. The fills the floor of 3 publishes are graded
but never counted, so they do not bring the read any closer. The
registration therefore adds a one-way harm check at 100 counted picks that can
remove "Take", and a stop date at the end of the 2027 postseason
(`docs/PREREG_CARD_V2.md` 11.4).

**The plus-money class makes the calendar worse, not better, and the
registration says so in its own evaluation plan.** Each class now reads its own
verdict at its own 300-pick, 60-date floor, and neither is pooled with the
other to get there faster. At the rate the one already-seen board produced, a
300-pick plus-money sample is one to several years beyond the main band's own
read. And a verdict on the class is weaker than the question actually being
asked: telling a plus-money class apart from a favourite class at a true ROI
gap of 3 to 5 points needs 6,952 to 19,311 bets in the plus-money band alone
(section 4.4's method, re-run in
`scratchpad/value_score/power_calc.py`). The floors are not lowered for that.
What can fire far sooner is the harm check's hit-rate arm on the plus-money
class, at 50 counted picks with our raw number 3 or more points above the
market's, which nearly every plus-money pick is by construction. The other
thing that answers the owner's instinct sooner is outside the card entirely:
SR1 in `docs/RESEARCH_STRATEGY_REPLICATION.md` ("home underdog, moneyline price
band +100 to +150") is registered, top-ranked and has never been run, and the
registration now requires it to be run and published before the first
plus-money pick is shown.

**The variant family makes the calendar longer still, and the arithmetic is in
the registration rather than here.** The owner's answers of 2026-09-16 about
03:10Z turned two disputed settings into a four-arm family
(`docs/PREREG_CARD_V2.md` section 17). Four arms mean six comparisons, and six
independent tests at an uncorrected 5 per cent bar produce at least one
apparent winner by luck alone 26.5 per cent of the time, so the family carries a
family-wise 0.05 correction whose bar is 0.008333. The six comparisons mature
years apart and two of them are expected never to read at all, so the bar is
registered flat at 0.008333 for any comparison read while a sibling is unread,
and a comparison is read once and never re-read at a looser bar (17.3). That bar
costs 1.5428 times the sample at 80 per cent power, so a **promotion** decision
needs 463 counted picks of a class and 93 slate dates, on both arms and again on
the set of picks only one of them holds (17.3, 11.10). The published card's own
verdict is untouched at 300 picks and 60 dates.

What that means in dates, at the discordance rates of the design board,
assuming a fresh board every day, and counting discordance **per class**,
because the floor is per class: the loose, uncapped arm separates from the
published card on `PLUS_MONEY` in about 116 slate dates, roughly two thirds of
the 2027 season, and on `MAIN` in about 463; the loose, capped arm separates on
`MAIN` in about 232, roughly 1.2 seasons, and its `PLUS_MONEY` comparison has
zero expected discordance and never reads; and the arm that only removes the
sub-cap needs about 463 on `PLUS_MONEY`, about 2.5 seasons, which should be
expected to read `UNDERPOWERED`, while its `MAIN` comparison never reads
either. The family's real sample starts in late March 2027, because
the 2026 regular season leaves 12 counted dates. **Nothing in the family will
ever answer "which is more profitable" on profit**: that needs 6,952 to 19,311
plus-money bets (4.4's method, `docs/PREREG_CARD_V2.md` 17.8). The instrument
that fires soonest is again the harm check, which the loose uncapped arm can
trip in about eight fresh slates because its card is 7 plus money out of 10, and
which the published card can trip in about seventeen.

**A promotion is scoped to the class it was won on.** The arms differ in
`MARKDOWN` and `BASE_EDGE`, which govern the main band as much as the
plus-money band, so a successor card registered on a `PLUS_MONEY` read keeps
the published card's constants on `MAIN` unchanged (17.4 clause 8). Without
that, an arm retired as a loser on one class could reach customers on the
strength of the other.

---

## 6. Owner directives this changes

| Date | Directive (quoted) | V1 today | Card V2 |
|---|---|---|---|
| 2026-09-10 | "the page may never again tell a paying reader that nothing cleared the bar"; "There have to be three to five bets every day" (`daily_card.py:6-14`, `tests/test_no_nothing_clears_the_bar.py:1-8`) | Met by filling to 3 from SPLIT picks regardless of price | **Kept on every board that offers three candidates, answered 2026-09-15 ("Always show 3"); departs on the boards that do not.** The floor of 3 stays, but nothing is filled from the SPLIT pile and no gate is relaxed: the shortfall is filled with the closest calls, which stay inside the -160 to +250 band and inside their class's floors on the market's number and on ours, are labelled on their face as not picks with the check each failed, and are graded on the record apart from the picks and apart by price class. Where the board itself offers fewer than three candidates past G1, G2, G4, G5, G6, G8, G9, G10 and G13, the card lists fewer, down to none, and says why (`docs/PREREG_CARD_V2.md` section 6, copy C13); on those days the directive is not met, and the registration says so in question 1 rather than reaching three by relaxing a gate. The banned phrases stay banned. |
| 2026-09-10 | "if the game is Nationals-Padres there needs to be a bet, and it needs to say take the Padres" (`daily_card.py:7-9`) | "Take" on every pick | **Narrows.** "Take" only on a pick that passed every check and whose price our number clears. |
| 2026-09-10 | Line-shopping copy: "that has to stop. None of that's important. Nobody fucking cares." (`daily_card.py:357-364`) | Removed as a reason, still printed as "best of N books" at `web/js/card.js:146`, `:269`, `:378` | **Completes it.** "Best of N books" is removed; the book name stays so a reader knows where the price is. |
| 2026-09-11 | "none of that price matters until we know it's a MORE THAN LIKELY BET, once we have the almost guaranteed bets, then we find the best sports picks of those with the best value, not the other way around"; "move completely away from price checking multiple books" | Likely first (market), price never checked on moneylines | **SUPERSEDED for the card by the owner's answers of 2026-09-16 about 00:50Z, recorded in the next row and in full in `docs/PREREG_CARD_V2.md` section 0.1.** It still governs the main band, where G5 and G6 keep their 0.50 tests unchanged, and it still governs every other rule in the repo that cites it. It no longer governs plus-money candidates, and it no longer sets the order: the ranking key is now the score he asked for. The line-shopping half is not superseded and is strengthened: G13 refuses outright any candidate whose own market number already clears its best price, and no cross-book comparison gates or ranks anything. |
| **2026-09-16 about 00:50Z** | "BOOM KEY QUESTION! Theres a lot of times where trhe underdog actuall makes more sens than the favorite and those are the real bangers, vewgas doesnt always get the stats right and sometimes the underdog isnt because his likelihood iof winning is low, it might be due to other factors and especially UFC when we get to it there so many underdogs, and same with fidning +100 to +250 poicks offer rally good value"; "even confidence of 30-45+ percent if high enough value (+150, +200 etc etc) we need an algorithm of value x confidence / likelihood"; "again based on cionfidence x value alrogirthm that we need to dial in" | No plus-money row has ever existed in `evidence/cards_v1.jsonl`, published or settled (section 4.3) | **Supersedes the 2026-09-11 row above, for the card only, and is the reason this file's V2 column changed.** A separate `PLUS_MONEY` class is created, priced +100 to +250, where the market's own number is 0.20 to below 0.50 and our own raw number is at least 0.30; selection and ranking both use one score, a Kelly fraction on our number after a fixed, registered markdown. The class is labelled on its face, graded on its own record, floored, harm-checked and retired on its own, and capped at 3 of the card's 10 slots pending his answer to the new question 9. What it costs is stated in `docs/PREREG_CARD_V2.md` 0.2 and 11.9 and is not softened here: our number has never been measured below 0.50 anywhere in this repo, every measured bucket runs hot, and the same error costs about 2.2 times more at +250 than at -160. |
| 2026-09-11 | "The last run scheduled or finished before the game first pitch should be recorded" (`card_ledger.py:276-279`) | Per-pick lock 4 h before first pitch, as last published | **Keeps** the lock as last published 4 h before first pitch. Adds: a pick withdrawn earlier is still graded, at its last shown price, and listed apart; "Take" shows only while the newest price check (at most an hour old) still passes, so a locked pick whose price has moved loses the verb but is still graded at its locked price. |
| 2026-09-11 | "the value just isn't there still" (-205, ours 51%, market 65%) | Break-even printed, not used | **Turns the disclosure into a gate.** |
| 2026-09-12 | Knowledge grades A/B/C | C chip on the card face | Grade stays in the breakdown (per `docs/DESIGN_SYSTEM.md`); props need a posted lineup to be picks. |
| 2026-09-14 | "merge the today bets for ALL BETS ... like run lines and the niche bets" | Run line only an alternative; totals paused | **Extends it.** Run lines, both sides, become selectable. Totals stay paused. |
| 2026-09-14 | Props analysis "needs to be ran pre emptively before any games" (`daily_card.py:1245-1249`) | Pre-lineup props can be picks at 15 games | **Kept, answered 2026-09-16 about 00:50Z: "No, allow earlier."** The draft had made a prop a pick only from a price checked after its lineup posted; asked in plain words, he answered no. The lineup test is removed from G10, so a prop may be a pick before its lineup posts, priced off the batter's season-average plate appearances, which is what V1 already does today (`src/report/card.py:717`). The 15-game history floor, the 2-book floor and one pick per player stay, and every prop with no posted lineup carries that fact on its face with the reason its plate appearances are estimated (`docs/PREREG_CARD_V2.md` section 8, copy C15). EXPLORATORY, on the design board: 19 of 56 prop candidates are inside the price band and have enough books, 13 of those fail the 15-game floor, so 6 become eligible where the lineup test left 0, and 1 becomes a pick. |
| 2026-09-15 | "the 3-10 bets for the day are the best of the best ... wouldn't be any lower than -150 or -160"; "high-confidence ... and the value is great" | No band, 8 of 8 STRONG favourites | **Implements the worst price and the ceiling of 10, and keeps the floor of 3.** -160 confirmed by him on 2026-09-15 against -150, which keeps running in shadow. **"+100, or higher" is now reachable**, because his answer of 2026-09-16 creates the plus-money class: on the design board 3 of 5 picks are priced +117 to +202. The floor of 3 and "high confidence" cannot both be honoured on thin days, and he chose the floor ("Always show 3"): the card fills to three with labelled close calls that are not picks, inside the same price band and the same class gates, graded apart. **The maximum no longer departs from "3-10 bets", answered 2026-09-16 about 00:45Z: 10 listed bets in total, picks and fills together.** The draft's ceiling of 10 counted picks only and could list 13 at once; he was shown that and ruled on it, G12 now counts every entry, and the 13-bet state cannot occur. |
| **2026-09-16 about 03:10Z** | Asked which single setting to register on three disputed points, he declined to choose on all three: "Can we try both strategies and see which one is profitable? These are the types of strategies that we should be changing not necessarily just the type of bedding strategy like changing these differences are strategy changes. Does that make sense?" (the markdown and required edge); "Again, these are different strategies that we should be trying because maybe one of them profitable and one of them is not so like try and be more" (the plus-money sub-cap); "Try different strategies on this. Try both separate I want. Try to try mix a hybrid." (the card's section order). On the fourth he answered plainly: "Yes, publish with the line." | V1 has no variants, no shadow rules and one layout | **Turns three settings into a registered variant family, and one into a display experiment.** The three disputed settings stop being single choices. Four arms run on the same board every day over a 2 x 2 of the markdown pair and the sub-cap: A1 (published, `MARKDOWN` 0.038, `BASE_EDGE` 0.010, sub-cap 3), A2 (sub-cap removed), A3 (`MARKDOWN` 0.0090, `BASE_EDGE` 0.0024), A4 (both). Only A1 is served; the other three run on paper and can replace it only under the promotion rule of `docs/PREREG_CARD_V2.md` 17.4, which is fixed before any result and charged against a Holm budget of six comparisons at a family-wise 0.05 (17.3). The layout answer is a product experiment whose result licenses a rendering change and nothing else (17.2). **One part of his direction is refused outright, by arithmetic**: at +150 a true 30 per cent bet returns -0.250 per unit before any gate, so the bottom of his band is positive expectation only at +234 and longer, and no arm serves it (17.0). "Yes, publish with the line" answers question 7 and makes copy C2's honesty line his own condition rather than the draft's default (`docs/PREREG_CARD_V2.md` section 7). |
| 2026-09-15 | "make a live bet system ... MLB, as well as the NFL and tennis" | None on the customer surface | Out of scope here; R16-35, `docs/LIVE_BETTING_SYSTEM.md`. |

The owner questions are listed in `docs/PREREG_CARD_V2.md` section 15: the
answered ones with his words and the date, the open ones each as one yes or no
with the default the build uses. Answered on 2026-09-15 at about 22:35Z:
question 1 ("Always show 3"), question 3 ("Rebuild on 2025") and question 4
("-160"), plus the V1 refit decision here in section 0 ("Freeze it now").
Answered on 2026-09-16 at about 00:45Z: question 1's open part, the card's
maximum (10 listed bets in total). Answered on 2026-09-16 at about 00:50Z:
question 2 ("No, allow earlier"), question 5 (the plus-money answer quoted in
full in the table above), question 6 ("even confidence of 30-45+ percent if
high enough value... we need an algorithm of value x confidence / likelihood")
and question 8 ("again based on cionfidence x value alrogirthm that we need to
dial in"). Answered on 2026-09-16 at about 03:10Z: question 7 ("Yes, publish
with the line"), and questions 9, 10 and 11, none of which he answered as a
single choice. He said the three disputed settings are themselves strategies
and should be run against each other and judged on profit, so 9 and 11 became
the two factors of the variant family of `docs/PREREG_CARD_V2.md` section 17
and 10 became the display experiment of 17.2.

**Open: three new questions, all raised by that answer.** Question 12, whether
to register the family as section 17 writes it, including the clause that there
will be no readout of which arm is winning before the read date. Question 13,
whether the published card may keep the strict bar, which leaves his 30-to-45
band shut below about +152 on everything a customer sees for at least a season,
while the loose bar runs only on paper. Question 14, whether the layout
experiment's result licenses a rendering change and nothing else. Question 13
is the one that most deserves his own words, because it is where the card still
does not do what he pictured.

---

## 7. How this was produced

Three read-only reviews (rule archaeology, today's candidate pool, record by
price band) and an inventory of value sources; three competing V2 designs
(price edge first, probability band, strategy-lab population); an adversarial
judge that re-applied each design to the candidate pool. The strategy-lab
design won because it was the only one that stays inside the band, never
relaxes a threshold to fill a quota and reproduces its own claimed output; its
required changes and the best parts of the other two are folded into the
registration. The other two failed on reproducible grounds: one specified a
value gate that passes 0 of 138 candidates, the other relaxed its price limit
to -175 on the first night to reach three picks.

Scratch scripts, all read-only against the repo, under
`C:\Users\KC\AppData\Local\Temp\claude\C--Users-KC-Desktop\3d973f1d-f098-4537-81b3-29618ed19de8\scratchpad\card_v2\`:
`today_row.py`, `verify_bands.py`, `slip_tiers.py`, `power2.py`,
`v2_final_screen.py` (superseded: it ranked on rounded numbers),
`ap_v2_screen.py` (the revised draft's illustration), `build_pool.py` (produced
`candidate_pool_2026-09-15.csv`, live rebuild at about 17:15Z),
`clv_bucket.py`, `paper_bucket.py`. The second revision pass added, under
`C:\Users\KC\AppData\Local\Temp\claude\C--Users-KC-Desktop\77c3095f-39f1-44e0-ade4-190cec7dca26\scratchpad\card_v2_revise\`:
`fit_window_counts.py` (the fit-window row counts in section 0, dates only) and
`verify_pool.py` (an independent re-screen of the pool for section 5.3). An
adversarial review of all three documents, applied the same day, is recorded
at the end of each. The owner's answers of the same evening added, under
`C:\Users\KC\AppData\Local\Temp\claude\C--Users-KC-Desktop\77c3095f-39f1-44e0-ade4-190cec7dca26\scratchpad\owner_answers\`:
`fill_illustration.py` (section 5.3 re-run with the floor of 3 and its fills,
built on `verify_pool.py` and changing nothing else) and
`consistency_check.py` (the band, floors, fill rule, rule id and copy strings
compared across the three documents).

The revision of 2026-09-16, applying the owner's four answers of that morning,
was produced the same way: a grounding measurement report on our probability in
the 0.30-0.45 and plus-money bands, three competing designs for the
value-times-confidence score written against it, and an adversarial judge that
re-implemented all three against the same candidate pool rather than trusting
their own scripts. Two designs were rejected on reproducible grounds recorded
in `docs/PREREG_CARD_V2.md`'s review record: one made the main band
structurally unreachable, the other printed a 0.30 confidence floor over a band
its own arithmetic made impossible to reach at any allowed price. Its scratch
scripts, all read-only against the repo, are under
`C:\Users\KC\AppData\Local\Temp\claude\C--Users-KC-Desktop\77c3095f-39f1-44e0-ade4-190cec7dca26\scratchpad\value_score\`:
`pool_bands.py`, `plus_money_detail.py`, `ev_arithmetic.py`, `ledger_bands.py`
and `power_calc.py` (the grounding report), `final_rule.py` (the revised rule
and the section 14 illustration), `final_extra.py` (refusal counts, vig gaps,
feasibility windows, the constant sweep and the shadow lists),
`final_copy_check.py` (every new customer string against the real banned-word
lists) and `final_consistency.py` (the constants, gates, band, floors, ceiling,
sub-cap, rule id and shared copy strings compared across the three documents).

That revision was then verified adversarially a second time, and six findings
were closed on 2026-09-16 with no gate, constant or evidence threshold changed
(`docs/PREREG_CARD_V2.md` section 16, last row). The one that mattered most was
a customer-truth defect: the plus-money line told the reader our number does
not make the side the underdog, while the number printed one line above it was
below 50% on all three plus-money entries the rule produces on this board. Two
others are recorded above, in 5.3: the corrected count of picks inside his
confidence band, and the new question 11. The verification scripts are
`fix_verify.py` and `fix_verify2.py` in the same directory; both are read-only
against the repo and both re-derive their numbers from `src.core.odds` rather
than from the documents.

---

## Review record

The adversarial review of 2026-09-15 filed no finding against this file by
name. The high and medium findings below were filed against the registration
but named or depended on text here; each was checked against the repo and
against the current text before it was applied, and none was applied twice.

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| high | The model rests on sealed-window fits, while this file said it reads nothing sealed and quoted the 1,896-game result | Applied | Confirmed with date-only counts (1,753 of 1,901 calibration rows sealed; `DISPERSION` and `RHO` fit windows sealed; no recorded go). Section 0 now leads with it, states the V1 consequences and the open V1 decision |
| high | Primary metric swapped to consensus drift | Applied | Section 4.2's closing paragraph and 5.2 item 4 now name price taken against the close as the registered metric |
| high | Plus money unreachable though the owner named "+100, or higher" | Applied, and later answered by the owner | Section 6's 2026-09-15 row said so and pointed to question 5. He answered question 5 yes on 2026-09-16 about 00:50Z, and the plus-money class now exists, so the row records the answer instead of the gap |
| high | "Take" picks could go ungraded under a fresh-read lock; this file's 2026-09-11 lock row said "Keeps" | Applied | The registration reverted to V1's lock as last published, so "Keeps" is now true; the row lists what V2 adds |
| medium | Retirement cannot fire for over a year | Applied | Section 5.4 gives the read date, the restart likelihood (15 commits), the harm check and the stop date |
| medium | G7 works as a positive-disagreement filter | Applied | Sections 2.2 and 5.2 item 3 say so |
| medium | V1's record block leaves out prop losers | Applied | Section 4.1 gives games, props and the combined figure, confirmed with `card_ledger.record()` |
| medium | Ranking by market likelihood contradicts the 2026-09-11 directive; this file said the directive is kept | Applied | Section 6's row now says the filter order is kept and the sort is owner question 8 |

Low: the "0 of 138" line in 5.1 restated per candidate kind and no longer
generalised. No finding was rejected.

### Verification pass

An independent verifier then checked the applied findings. Two of its items
touch this file; both were re-checked and applied, and none was rejected.

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| medium | Section 6's 2026-09-14 row said pre-lineup props "show as close calls with their price age all day", more than the rule allows: only 3 close calls show and one-test game close calls rank first | Applied | Confirmed EXPLORATORY on the design board with game prices fresh and prop prices stale (none of 19 props among the 3; `scratchpad/card_v2_revise/close_calls_props_stale.py`). The row now says a pre-lineup prop appears at most as one of the 3 and usually not, as the registration's sections 6 and 8 do |
| high (from the registration) | Keeping the nightly calibration under question 3 would fold forward games into V2's fit | Applied | Section 0's open decision now says question 3 covers only `DISPERSION` and `RHO`, and V2 does not keep the card calibration under any answer |

### Owner answers of 2026-09-15, applied to this file

Brey answered four questions in chat at about 22:35Z. Three of them are
recorded in `docs/PREREG_CARD_V2.md` sections 15 and 16; the fourth is the V1
decision this file raised. Changes here, and nothing else:

| Answer | Applied where |
|---|---|
| The V1 refit, "Freeze it now" | Section 0: the observed-fact bullet and the headline sentence say the nightly refit ran until 2026-09-15; the open decision becomes the answer, with the options as they were put to him and the record `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`; consequence 2 now separates the record behind the freeze from the state after it. The freeze does not undo the reads already made, and no number in this file changes |
| Question 1, "Always show 3" | Section 5.3 re-run with the floor and its fills; section 6's 2026-09-10, 2026-09-14 and 2026-09-15 rows; section 5.4 (fills are graded and never counted); section 7's script list |
| Question 3, "Rebuild on 2025" | Section 0's closing paragraph and section 5.4: V2 keeps neither sealed-window fit |
| Question 4, "-160" | Section 6's 2026-09-15 row; no number changes |

Evidence status is unchanged: the re-run of 5.3 is an illustration on
already-seen data, by
`scratchpad/owner_answers/fill_illustration.py`, and is not evidence for or
against any rule.

### Verification pass on the amendment (2026-09-16)

An independent verifier re-read the amended documents. Three of the four
problems it filed with substance touch this file; each was re-checked before it
was applied and none was rejected. No number in this file changed.

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| medium | Section 6's 2026-09-10 row recorded the directive as "Kept", where the pre-amendment draft recorded a departure, although a board can offer fewer than three candidates and that state is published as a count with no entry | Applied | Confirmed against `docs/PREREG_CARD_V2.md` section 6 and copy C13. The row now says kept on every board that offers three candidates and names the one state that departs |
| medium | Section 6's 2026-09-15 row said only that the ceiling of 10 is implemented, where the answered floor let the card list more than ten at once | Applied, then settled by the owner | Confirmed at the time: the ceiling counted picks only and a shown fill is not removed when picks arrive later. He was shown that and answered on 2026-09-16 about 00:45Z, "10 listed bets in total", so the row now records his answer and G12 counts picks and fills together |
| medium | Section 0 said the freeze locks "today's settings", broader than the freeze record, which covers only `a` and `b` | Applied | Confirmed in `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`. Section 0 now names `a` and `b`, cites the freeze commit, and says the rest of V1 stays live, so a later comparison reads V1 against the `v1_code_fingerprint` of the registration's section 10 |

### Owner answers of 2026-09-16, applied to this file

Brey answered four more questions in chat, one at about 00:45Z and three at
about 00:50Z. The verbatim text of each is in `docs/PREREG_CARD_V2.md` section
0.1 and section 15; section 6's table here carries the two that change a
standing directive.

| Answer | Applied where | Note |
|---|---|---|
| "10 listed bets in total" (00:45Z) | Section 6's 2026-09-15 row | The 13-bet departure is settled and removed. G12 now counts picks and fills together |
| "No, allow earlier" (00:50Z, props) | Section 6's 2026-09-14 row | The lineup test leaves G10. The row now records the answer, the remaining safeguards, the mandatory no-lineup disclosure and the measured size of the change on the design board |
| The plus-money answer (00:50Z) | Section 6: a new 2026-09-16 row, and the 2026-09-11 and 2026-09-15 rows; sections 5.3 and 5.4 | The 2026-09-11 "more than likely first" directive is recorded as superseded for the card, with both quotes and both dates, and is kept where it still governs. 5.3 is re-run under the revised rule; 5.4 adds the plus-money class's own floor and the power arithmetic behind it |
| "value x confidence" (00:50Z, questions 6 and 8) | Section 6's 2026-09-11 and 2026-09-16 rows; the open-questions paragraph | The ranking key is the score. Questions 9 and 10 are new and open |

Evidence status is unchanged: the re-run of 5.3 is an illustration on
already-seen data, by `scratchpad/value_score/final_rule.py`, and is not
evidence for or against any rule. No number in sections 0 to 4 of this file
changed, and no evidence threshold, floor or stop condition moved.

### Owner answers of 2026-09-16 about 03:10Z, applied to this file

Brey answered the four remaining questions in chat at about 03:10Z (8:10pm
Pacific 9/15). One is a plain yes; three decline to choose between the options
they were given and say the disputed settings are strategies to be run against
each other and judged on profit. All four are quoted verbatim in
`docs/PREREG_CARD_V2.md` sections 15 and 16, and the three that change a
standing directive are in section 6's table here.

| Answer | Applied where | Note |
|---|---|---|
| "Yes, publish with the line." (question 7) | Section 6's new 2026-09-16 about 03:10Z row; the open-questions paragraph | The honesty line on every pick becomes his own condition rather than the draft's default. Question 7 is closed |
| "Can we try both strategies and see which one is profitable?..." (question 11) | Section 6's new row; 5.4; the open-questions paragraph | The markdown and required edge become one factor of a registered four-arm family. The published card keeps the strict pair; the loose pair runs on paper |
| "Again, these are different strategies that we should be trying..." (question 9) | Section 6's new row; 5.4 | The plus-money sub-cap becomes the second factor. The cap stands on the published card; its removal runs on paper |
| "Try different strategies on this. Try both separate I want. Try to try mix a hybrid." (question 10) | Section 6's new row; the open-questions paragraph | The card's section order becomes a display experiment whose result licenses a rendering change and nothing else, and can never be reported as a strategy result |

**What this file says about the answers, and what it refuses to say.** Section 6
records what each answer changes about a standing directive. 5.4 records what
the family costs in calendar time and states plainly that it will never answer
the profit question on profit. Neither section reports any variant as better or
worse than another: the four-arm illustration on the already-seen 2026-09-15
board lives in `docs/PREREG_CARD_V2.md` 14.3b, is labelled EXPLORATORY there,
and is an illustration of what the arms do rather than evidence about any of
them.

Evidence status is unchanged. No number in sections 0 to 4 of this file changed,
no evidence threshold, floor, FAIL condition, verdict bar, harm-check arm or
stop condition moved on the published card, and the sealed window was not
touched. The one part of the owner's direction this revision refuses is
arithmetic and is stated as such: a true 30 per cent bet at +150 returns -0.250
per unit before any gate, so no arm of the family serves the bottom of his
confidence band at the price he named.
