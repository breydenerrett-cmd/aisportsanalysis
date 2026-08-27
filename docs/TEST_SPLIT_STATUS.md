# Test split status — the 2025 holdout is burned

**Declared 27 Aug 2026.** This document exists because the alternative is quietly
continuing to describe a split as "held-out" when it is not.

## What happened

The 2025 test split — `2025-08-26 .. 2025-09-28`, 456 rows — was evaluated **four
times** during development:

1. The one-shot evaluation of the locked model.
2. Team-only features, in the pitcher comparison.
3. Team-plus-pitcher features, in the same comparison.
4. A check of the prediction distribution (spread, share above 0.5).

Each was individually defensible. The first was the intended single look. The
second and third were a genuine question — does pitcher information help? — that
happened to be asked of the wrong split. The fourth was diagnostic curiosity.

Together they mean the split has been seen four times, and every number reported
from it is optimistically biased by an unknown amount.

## Why this matters more than it sounds

A holdout is evidence only while it is unseen. The bias is not that any single
evaluation cheated; it is that what was learned fed back into the next decision.
Knowing how the model scored on the test set influenced which comparison to run
next, and that channel is exactly what a holdout is supposed to close.

The amount of bias is unknown and unknowable. That is the point — if it could be
estimated, it could be corrected for.

## What is affected

These numbers should be treated as **optimistic**, not out-of-sample:

| Reported | Value | Status |
|---|---|---|
| Test log loss | 0.680695 | Optimistically biased |
| Test Brier | 0.243832 | Optimistically biased |
| Test ECE | 0.0297 (later 0.0180) | Optimistically biased |
| "Beats baseline on held-out data" | +0.0115 | **Weaker than stated** |

The validation-set numbers were always understood to be selection-influenced —
sixteen hyperparameter configurations were compared on them — and are unaffected
by this declaration because they were never claimed as clean.

## What is NOT affected

The **methodology** is unchanged and was never in question:

- Point-in-time feature construction is proven leak-free by tests that inject
  future results and assert byte-identical output.
- Splits are chronological, never random.
- The scaler is fitted on training data only.

This is a bookkeeping failure about how many times a number was looked at, not a
contamination of the features or the split boundaries.

## The fix

### 1. The seal

`src/model/seal.py` records every evaluation against a split on disk, keyed by the
split's date boundaries and row count. Re-cutting the same boundaries is recognised
as the same split, so rebuilding the table cannot reset the count. Any evaluation
past the first reports itself as such.

The 2025 split is recorded with `declared_burned: true` and a count of 4.
`declare_burned()` is a deliberately named, explicit function rather than a quiet
increment, so backdating history shows up in a diff.

### 2. The only genuinely sealed split is the future

A holdout carved from data already in hand can always be peeked at, and the seal
depends on discipline that has now demonstrably failed once.

Games that have not been played cannot be peeked at by anyone, including by
accident. Forward evaluation is therefore **strictly stronger** than any historical
holdout, and it is what `docs/VALIDATION_CRITERIA.md` already rests on: 300
CLV-graded predictions on games that had not happened when the model was fitted.

The prediction log started accumulating on 27 Aug 2026. Every entry in it is, by
construction, on an unplayed game at the time of prediction.

### 3. If a historical holdout is needed again

Re-cut it from a season the model has never been fitted on. Once 2024 or earlier is
ingested, one of those seasons can be sealed and left alone. It must be evaluated
once, at the end, with the count visible.

## The honest summary

The model is calibrated and beats a base-rate baseline. That finding is probably
real — the improvement appeared on validation before test, and the direction is
consistent — but its **magnitude on the test split is overstated by an unknown
amount**, and it was never the criterion that matters anyway.

The criterion that matters is beating the de-vigged market, which requires
historical closing odds that have not been acquired. Nothing here changes that,
and nothing here justifies a bet.
