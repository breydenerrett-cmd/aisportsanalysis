# Card calibration freeze, 2026-09-15

## Owner decision

Question put to Brey on 2026-09-15 at about 22:35Z (3:35pm Pacific):

> "The current card's model is refit every night on this season's games,
> including games our research rules say must stay untouched for a
> one-time final test. Stop that now?"
>
> Options: "Freeze it now (Recommended): lock today's model settings for
> the current card until the new card replaces it; picks barely change;
> the protected games stop being used" / "Keep refitting."

Answer, given in chat at about 22:35Z: **"Freeze it now."**

This record implements that answer. It changes only the nightly refit
step; it does not change `data/processed/card_calibration.json` itself,
which is already frozen at whatever the committed file holds as of this
decision.

## What is frozen

`data/processed/card_calibration.json` holds the Platt scaling the card
applies to the raw model's win probability (`src/report/card.py:
load_calibration`, used by `src/analysis/daily_card.py`): two numbers,
`a` and `b`, mapping the raw probability to a calibrated one. `b` below 1
means the raw model is being told to be less sure than it looks; on the
2026 season `b` has run near 0.5, meaning the raw model's stated
confidence is roughly twice what its accuracy earns. Without this file
the card serves the raw, overconfident number instead
(`src/report/card.py` docstring on `load_calibration`).

Until now, `scripts/fit_card_calibration.py` refit `a` and `b` every night
from `scripts/daily_loop.sh`, on every completed 2026 game back to
2026-04-15. As of this decision that nightly refit no longer runs. The
file stays exactly as committed until a new dated owner decision unfreezes
it.

## The frozen file

- Path: `data/processed/card_calibration.json`
- Committed at: `b238942033a0b7b86044d8c9e90ed835ef39b3b0` (HEAD at the
  time of this freeze)
- sha256 (of the committed blob, `git show
  b238942033a0b7b86044d8c9e90ed835ef39b3b0:data/processed/card_calibration.json`,
  not the working-tree copy, whose line endings can differ):
  `ea3ea23c808bcedb097bdf36aba00edeb480dd63827305a6e0c138fd9998c368`
- From that file: `n=1911`, `b=0.735183` (also `a=0.028644`,
  `fitted_through="2026-09-14"`, `fitted_at="2026-09-15T21:04:00.873598+00:00"`)

## Why: the fit window (docs/CARD_V2_DIAGNOSIS_2026-09-15.md, section 0)

The canonical split reserves 2026-01-01 through 2026-08-27 as the sealed
window: one evaluation ever, only after a policy freeze plus Brey's
explicit go, and 2026-08-28 onward as forward proof that is never folded
back into tuning. The diagnosis found the nightly refit reading the
sealed window anyway: of the 1,901 rows it selects on that count, 1,753
rows (92.2%) fall inside 2026-04-15 through 2026-08-27 -- inside the
sealed window -- and only 148 are forward games from 2026-08-28 onward.
(Those 1,901/1,753/148 counts are from the window-composition check
described in that document, run by date only with no outcome read; they
predate the frozen file's own last refit by a few hours, hence the
frozen file's slightly larger `n=1911`.) The refit ran again every night,
so the breach repeated nightly starting 2026-09-10.

## What this freeze does not undo

- V1's forward record to date is still of a model whose calibration
  changed every night up through this freeze.
  `docs/VALIDATION_CRITERIA.md`: "Changing the model restarts the
  sample" -- so no V1 closing-line or return verdict can be drawn from
  that record as if it were one continuous, fixed model.
- The sealed window's one evaluation cannot confirm any rule built using
  these fits: the calibration's parameters were chosen on the window and
  evaluated against it repeatedly before this freeze. Freezing the file
  today stops new breaches; it does not restore the seal's ability to
  confirm anything already built on it.
- This freeze covers only the card calibration (`a`, `b` above). It says
  nothing about `DISPERSION` or `RHO` (docs/CARD_V2_DIAGNOSIS_2026-09-15.md
  section 0, owner question 3 in `docs/PREREG_CARD_V2.md`), which are
  separate decisions.

## How to lift this freeze

Two things, both required:

1. A new, dated owner decision to resume refitting the live card
   calibration (this record is not a standing default -- it takes an
   explicit decision to reverse it, the same way it took one to start).
2. Passing `--overwrite-frozen-store` to `scripts/fit_card_calibration.py`
   in addition to letting `--out` default to the live store -- the script
   refuses to write `data/processed/card_calibration.json` without that
   flag (see the script's module docstring). Re-adding the step to
   `scripts/daily_loop.sh`'s nightly loop is a separate, explicit edit;
   it is not restored by passing the flag alone.
