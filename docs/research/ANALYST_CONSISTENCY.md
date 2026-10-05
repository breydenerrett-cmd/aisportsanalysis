# Analyst consistency: three answers to one frozen request (Braves at Dodgers, 2026-10-04, v2)

Status: diagnostic, written 2026-10-05. It uses no outcome data and does not say which answer was right.
Three samples from one model are a look at how stable the model's calls are, not sporting evidence.

Inputs: `evidence/analyst_consistency/2026-10-04_ATL-LAD/` (the preserved answers, see its README),
the frozen packet `ccef50623366` (`evidence/analyst_pilot/2026-10-04_ATL-LAD/packet.json`) and the
prompt's written rules (`src/analyst/analyst.py`, `analyst_prompt_v5`). The table below is the output of
`python scripts/analyst_consistency.py evidence/analyst_consistency/2026-10-04_ATL-LAD --report ...`.

## What was compared

| Label | What it is | Full answer? |
|---|---|---|
| [1] attempt 1 | First answer. Rejected by the checker (moneyline, prop_11 struck) for unrelated violations. Survives only as the transcript record. | No, calls table and summary only |
| [2] attempt 2 | Written after attempt 1's four rejection lines were passed back. Published as version 2. | Yes |
| [3] sample 3 | Independent answer to the same request, no rejection lines, never offered for publication. | Yes |

**Attempt 2 is not a clean replicate.** It differed from the other two in one input: it was given the
four rejection lines. They said nothing about prop_01 (they quoted -200 and +201 as "not a number in the
data" and flagged the word "edge"), yet prop_01 changed. A re-answer redraws every call, not only the
struck ones. Attempt 1 and sample 3 are the two draws made from the same input; attempt 2 is a draw
made with extra input.

## Per slot

| slot | [1] attempt 1 (partial) | [2] attempt 2 (published) | [3] sample 3 | flags |
|---|---|---|---|---|
| moneyline | PASS LAD -212 draftkings fair 0.66 | PASS LAD -212 draftkings fair 0.66 | PASS LAD -212 draftkings fair - | |
| run_line | PASS ATL +1.5 -112 lowvig fair 0.52 | PASS ATL +1.5 -112 lowvig fair 0.52 | PASS ATL +1.5 -112 lowvig fair - | |
| total | PASS Under 8 -110 lowvig fair 0.51 | PASS Under 8 -110 lowvig fair 0.51 | PASS Under 8 -110 lowvig fair - | |
| **prop_01** | **TAKE_OTHER_SIDE Under 6.5 +120 draftkings fair 0.52** | **PASS Over 6.5 -120 fanduel fair -** | **TAKE_OTHER_SIDE Under 6.5 +120 draftkings fair 0.52** | **ACTION (one answer bets, another passes)** |
| prop_02 .. prop_11 | PASS | PASS | PASS | none (same selection, price and book in all three) |

Thirteen of fourteen slots agree on verdict, selection, price and book across all three answers. The
only disagreement is prop_01, and it is a disagreement about whether to bet at all. (A PASS may leave
`fair_estimate` empty, so a missing estimate on a PASS is not counted as a disagreement.) The full
fourteen-row table: run the script.

## prop_01, field by field (attempt 2 against sample 3, with attempt 1's partial record)

| field | attempt 2 | sample 3 | attempt 1 (partial) |
|---|---|---|---|
| verdict | PASS | TAKE_OTHER_SIDE | TAKE_OTHER_SIDE |
| selection | Over 6.5 (the lean) | Under 6.5 | Under 6.5 |
| price, book | -120, fanduel (the best Over quote) | +120, draftkings (the best Under quote) | +120, draftkings |
| fair_estimate | null | 0.52 | 0.52 |
| confidence | low | low | not recorded; summary calls it "a thin read on a nine-start sample" |
| pass_price | null | -108 (the break-even of 0.52) | not recorded |
| `derived` calculations | none | none | not recorded |
| case_against | null (it is a PASS) | Snell's 11.6016 strikeouts per nine and the books' Over fair of 0.5259 | not recorded |
| what_would_change_it | word on his expected pitch count | a report of an extended pitch count, or the Under at -108 or shorter | not recorded |

Reasons, where both full answers exist:

* **Shared facts.** Both cite `home_sp_ip_per_start` 4.741 and `home_sp_recent_ip_per_start` 3.556, and
  both read them the same way: reaching seven strikeouts needs a longer outing than he has been getting.
  Both cite DraftKings as the odd book. Both name the pitch-count plan as the unknown. Both say low
  confidence. Attempt 1's summary says the same three things (workload, thin sample, other books near
  even on the Under).
* **The same fact used in opposite directions.** Attempt 2's third reason is that the books disagree
  (DraftKings Over -154 against BetMGM -125), "so the data gives us no reason to side with one book"; it
  is the reason to pass. Sample 3's second reason is that DraftKings is the outlier at +120 while other
  books have the Under near even money, "so the price is better than the books' fair number of 0.4741
  suggests"; it is the reason to bet. Attempt 2 reads the books' Over fair of 0.5259 as "the market leans
  only slightly to the over"; sample 3 files the same number as its case against.
* **Different extra facts.** Sample 3 adds 8 days of rest and 9 starts of 42.67 innings; attempt 2 adds
  the DraftKings -154 against BetMGM -125 comparison on the Over. Neither contains a declared
  calculation, so no arithmetic differs.

## The frozen packet's prop_01

* Seven books quote it, all captured 2026-10-04T21:14:42Z (packet built 21:21:24Z). The packet's lean is
  Over 6.5. The books' fair probability is 0.5259 for the Over and 0.4741 for the Under.
* Over quotes: -125 betmgm, -130 betonlineag, -120 bovada, **-154 draftkings**, -125 fanatics, -120
  fanduel, -124 mybookieag. Under quotes: -105, +101, -110, **+120 draftkings**, -105, -106, -111.
* `context` holds only `{"player": "Blake Snell", "stat": "pitcher_strikeouts"}`. There is no
  `repo_model_probability` for this slot. (Of the eleven props only prop_02 has one.) Rule 10 of the
  prompt says "for props the repo model's number is in context"; for this slot it is not.
* The starter numbers are in `sections.starters.values` (as of 2026-10-03): K/9 11.6016, 4.741 innings
  per start, 3.556 over his last three starts, 8 days of rest, 9 starts, 42.67 innings. There is no pitch
  count and no strikeout-per-start figure.
* Arithmetic of mine, not in any answer: the +120 Under breaks even at 0.4545, so 0.52 sits 6.5 points
  above the price and 4.6 points above the books' fair 0.4741. DraftKings' own pair (Over -154, Under
  +120) de-vigs to an Under of 0.4285, the lowest of the seven books (the others run 0.4681 to 0.4899).
  So DraftKings is both the best Under price and the book that rates the Under least likely; whether
  that is a stale price, a shaded one or information is not something the packet says.
* `missing` lists props as thin overall (66 of 86 priced props had fewer than two books; 9 were cut by
  the per-market limit). That is a statement about the props not analyzed; prop_01 has seven books.

## The prompt's written rules that bear on it

* Rule 6: TAKE_OTHER_SIDE bets the side the books do not favour. Rule 7: PASS is the default, "when
  the evidence is thin, or the packet gives you nothing about this market beyond its own price". The
  packet does give starter workload numbers, so rule 7 neither forces a pass nor permits a bet.
* Rule 10: `fair_estimate` is the model's own probability; "if you depart from the books by more than a
  few points, the reasons must show what the packet knows that the price does not." "A few" is not a
  number. Sample 3's 0.52 is 4.6 points from the books' 0.4741, and its reasons offer workload, which the
  books presumably already price; the packet cannot tell us whether they do.
* Rule 9: `price` and `book` are "the quote you would take". Nothing says whether a single quote that is
  far from the other six may be the quote taken.
* Rule 12: confidence is low, medium or high; nothing ties it to whether a TAKE is allowed. Low
  confidence appears on the TAKE and the PASS alike.
* Nothing in the prompt gives a minimum gap between the model's estimate and the price below which a
  TAKE is forbidden, and nothing converts innings per start and strikeouts per nine into a probability
  for a strikeout line (arithmetic of mine: 11.6016/9 x 4.741 = 6.11 and x 3.556 = 4.58 strikeouts, against
  a line of 6.5; the prompt asks for no such calculation and the answers declare none).

## Classification

**A decision threshold and market-call policy that the prompt leaves open.** The five candidate causes,
set against what is on the page:

* *Evidence interpretation*: not the main difference. All three read the workload numbers the same way and
  name the same unknown. The one place interpretation visibly diverges (the DraftKings outlier) is itself
  a question of policy: the prompt does not say whether an outlier quote is an opportunity or noise.
* *A calculation*: no. No answer declares one, and the only numbers that differ (0.52 against null) are the
  model's own estimate, not a computation from the packet.
* *Uncertainty wording*: no. All three call the read thin and low confidence; the wording did not change
  the action.
* *Generation variance with identical numeric inputs*: possible and not separable. Attempt 1 and sample 3
  are the two draws with the same input and they agree exactly on selection, price, book and estimate
  (0.52); attempt 2 is the odd one but had a different input. Two agreeing draws and one draw with extra
  input cannot estimate a variance.
* *The open threshold*: all three sit at the boundary the prompt does not draw. The estimate is close
  enough to the price that "bet or pass" depends on how much gap counts as enough, and the prompt gives no
  number. Two of three decided one way, one the other, on identical caveats.

**What the evidence supports:** the model's reading of the facts is stable; the action taken on a
borderline call is not fixed by the prompt, so it is not stable.

**What it cannot show:** that the take was wrong or right (no outcome data is used); how often a re-draw flips a
call (three draws, one of them not a replicate); whether the 0.52 comes from a stable internal habit (two
independent draws arriving at exactly 0.52 is suggestive and unexplained); or whether the books' Under
price carried information.

## Two side findings

* **The checker did not judge the decision.** Re-run on the current code, the checker reproduces the
  published row's single strike (run_line, for the name "two braves"). On sample 3 it keeps prop_01 and
  strikes prop_11 (-200 quoted) and withholds the summary ("blake snell under" is not a name in the
  packet): it would itself have been rejected for violations unrelated to prop_01. The checker verifies
  that claims are in the packet; whether a TAKE is justified is outside it.
* **A re-answer redraws everything.** Attempt 2 was a fresh answer to the whole request, so twelve
  correct calls were redrawn along with the two struck ones, and one of them (prop_01) changed. The
  publication rule (`docs/AI_ANALYST.md`) allows only the rejection lines as extra input; it does not and
  cannot pin the calls the checker kept.

## Proposed shadow candidate (not implemented)

**Code makes the take/pass decision; the model supplies the estimate.** For every slot the model gives
its probability for the selection it likes best (`fair_estimate`, and the selection) and keeps its
reasons; code then decides TAKE or PASS from three things only: the model's estimate, the quoted price,
and written limits in `config/analyst.json`:

1. no estimate, no TAKE;
2. TAKE only if the estimate exceeds the quote's break-even by at least `min_margin`;
3. no TAKE where the estimate is more than `max_departure` from the books' fair probability unless the
   slot carries LineHound's own model number to back it; and the existing -200 floor (already code).

The published verdict is the code's; the model's own verdict is kept on the row as `model_verdict` so
the two are always visible. This turns "how much gap is enough" from a per-draw judgment into one number
the owner fixes before any evaluation, and what is left to vary across draws is only the estimate itself.
Applied to this game it would not decide anything by itself: attempt 2 gave no estimate (PASS), and
attempt 1 and sample 3 gave 0.52, so the call would hinge on `min_margin` and `max_departure`. Those two
numbers must be pre-registered by the owner before any evaluation; they must not be chosen from this
game (no rescue by threshold change).

Shadow protocol: run it as a post-processor over the answers the pilot already writes, publishing
nothing different, on the next several briefs, and compare the code's decisions across repeated draws of
the same frozen request (agreement across draws against the model's own verdict agreement). The draws
are diagnostic only and drawn after the brief is published. It needs the model to give an estimate on
every slot, which is a prompt change, and so a new prompt version; that is why it is a shadow candidate
and not a patch.

## Text recommended for docs/BRIEF_RUNBOOK.md

The parent owns that file; this is the text to add.

```
### Answering a prepared game: the publication rule

The first answer is the candidate. Nobody picks among answers.

1. The writer answers from request.json and nothing else. Run `pilot check` on the file; that records
   attempt 1 in the folder (attempts.jsonl, attempt_1.json).
2. If check says CLEAN, publish it. Do not write another answer "to see if it differs": an answer that
   follows a clean one is a reroll and `pilot publish` refuses it.
3. If check says REJECTED, the writer may answer again, at most twice more (three attempts in all). The
   only extra input is the REJECTION LINES check printed, word for word. Add no hints, do not paste the
   earlier answer, do not say which calls were kept. Expect unflagged calls to change: a re-answer
   redraws the whole answer.
4. Publish the latest attempt only. `pilot publish` refuses a response that was never checked, one that
   is not the latest attempt, one that follows an unrejected attempt, and a fourth attempt. The row keeps
   `attempts` and `attempt_hashes`.
5. Stability samples (extra answers to the same request, for diagnosis) are drawn only after the brief
   is published, are never offered to `pilot publish`, and are saved under
   evidence/analyst_consistency/<date>_<game>/ and compared with scripts/analyst_consistency.py.
6. Preparing a game again freezes a new request and starts a new attempt count.
```
