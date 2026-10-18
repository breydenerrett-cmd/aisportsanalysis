# Director reviews

One file a month. `python -m src.hounds.learning director-pack --month YYYY-MM` writes
`YYYY-MM.request.md` here: every hound's record, the system scorecard, the month's proposals, refusals,
promotions and retirements, the live challengers, every lesson, and (with `--run-tests`) the failures of the
hounds' test modules. Give it to a frontier model and save the answer by hand as `YYYY-MM.md`.

The answer is **advice** (keep, bench, bugs, questions). Nothing in this program reads these files back and
nothing in them is applied automatically; a test (`tests/test_hounds_learning_views.py`) fails if any source
file reads this directory. See `docs/PREREG_LEARNING_LOOP.md` section 11.
