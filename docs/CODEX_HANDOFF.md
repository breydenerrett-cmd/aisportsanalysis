# Handoff prompt for Codex — 2026-09-08 night

Paste the block below to Codex. It states what Claude is holding tonight, what
is free to take, and the rules that are not negotiable in this repo.

---

## PROMPT

You are working in `aisportsanalysis` — an MLB betting-analysis product owned
by Brey. Branch: `claude/sports-betting-analysis-review-g1o0co`.

**Read `docs/PRODUCT_DOCTRINE.md` first. It is LOCKED and it governs.** Then
skim `docs/AUTONOMOUS_TONIGHT_2026-09-08.md` for tonight's plan.

### What this product is

It sells a short, ranked nightly slip of MLB picks — a flagship Top 3, a
tracked Top 5, and the published remainder — each frozen to a hash-chained
ledger before first pitch. The pitch is prediction quality; the moat is that
the record cannot be retconned and the losses are published too.

Current honest state: **42 research hypotheses, 34 null, zero confirmed. No
strategy has ever cleared the promotion gate. No model-derived probability
exists anywhere.** The product is an early-access forward-test slip, labelled
as such. It may not claim a win rate or an edge percentage.

### CLAUDE IS HOLDING THESE FILES TONIGHT — DO NOT EDIT

```
src/analysis/families.py            tests/test_analysis_families.py
src/engine/slip.py                  tests/test_engine_slip.py
src/report/clv.py                   tests/test_report_clv.py
src/pipeline/news.py                tests/test_pipeline_news.py
src/pipeline/lineup_store.py        src/ledger/records.py
scripts/forward_capture.sh          scripts/daily_loop.sh
.github/workflows/forward-capture.yml
.github/workflows/daily-loop.yml
src/cli.py  (the `engine slip` command specifically)
docs/PRODUCT_DOCTRINE.md
```

### WHAT YOU CAN SAFELY TAKE

Pick from these; they do not collide with the above.

1. **`scripts/factory_masks_from_sweep.py` is broken.** It exits 1 with
   `PlaceboError: a world needs at least one game` from
   `placebo.real_world(...)`. `data/research/matchup_matrix_2023.jsonl` (2,430
   rows) and `_2024.jsonl` (2,429) both exist = the documented 4,859-game
   universe, so the inputs are there. Trace which upstream read returns empty
   and fix it. The masks `.bin` is deliberately gitignored and regenerable —
   nothing is lost, but the overlap report cannot currently be rebuilt.

2. **A second, related bug:** the overlap-report generator will happily
   overwrite a *recorded research result* with "decision-level overlap: not yet
   computable" when that regenerable cache is merely cold. It did exactly that
   to `docs/FACTORY_OVERLAP_REPORT.md` (destroying the 8,811-strategies →
   1,062-families result, restored from git). Make it refuse, or preserve the
   prior, rather than silently downgrade a finding.

3. **Web/API surfaces that do not touch picks** — the two undesigned routes
   still reachable by customers: `#/billing` renders a raw JSON dump, and
   `#/mybets` is an unstyled table whose free-text form does not join to
   anything Bet Check produces.

4. **The hardcoded honesty number.** The homepage prints "27 hypotheses
   pre-registered … zero surviving" as a literal constant. The registry
   (`data/research/alpha_registry.jsonl`) says 42. A product whose pitch is
   "we don't make numbers up" must not hand-type that one. Derive it.

### RULES THAT ARE NOT NEGOTIABLE

- **Never fabricate a value.** A named absence with a reason is correct; a
  guessed or zero-defaulted one is corruption. Zero is a real, middling value
  and must never stand in for "unknown".
- **Never compute or name an edge, EV, win probability, or confidence score.**
  `edge_bps` is structurally null and raises if set without a model-derived
  probability. Price standing is *execution quality*, never predictive merit —
  the consensus is derived from the same prices, so their difference can never
  be evidence the market is wrong.
- **Never call a late line move "CLV"** unless it is genuinely measured
  against the closing price.
- **Every test must fail when the behaviour it guards is broken.** Introduce
  the bug, confirm red, restore, confirm green — and say you did. This repo has
  shipped fake guards before: a line-pooling test passed with the bug present
  because both fixtures reused the same book names. Watch for fixtures too
  uniform to tell the bug from the fix.
- **Never `git add -A`.** Stage explicit paths; parallel agents are writing.
- **Never print, echo, or commit secret values.** `ODDS_API_KEY` and
  `FLY_API_TOKEN` are GitHub Actions repository secrets — use them by name
  only. Do not commit `.env`.
- **Do not reimplement what exists once on purpose.** There is exactly one
  de-vig (`src/analysis/prices.py`, `MIN_BOOKS = 6`) and one Jaccard clustering
  (`src/evolab/overlap.py`). A second copy of either is a defect.
- **Point-in-time correctness.** `matchup_history` reads a LEAKY career-totals
  endpoint with no as-of parameter and is deliberately TODAY-only. Do not
  extend it backwards to "fill gaps".
- 2025 is tuning-only, 2026 is sealed. Credits buy more data, never a weaker
  gate.

### HOUSE STYLE

Docstrings explain *why* a choice was made and what alternative was rejected,
not what the code does. Every threshold is a named module constant with its
justification beside it — a threshold a caller can tune silently is one that
can be tuned to manufacture a result. Read two or three neighbouring modules
before writing; match their register.

### ENVIRONMENT

Windows. Python via `PYTHONPATH=<repo root>`. Run tests with
`python -m unittest tests.<module>`. About 45 pre-existing failures in the full
suite are Windows-only (`bash -n` script parsing, `chmod +x` checks, a sqlite
path) — they are not yours and not regressions. Verify against targeted
modules, not the full discover run.

Report what you changed, what you measured, and anything you are unsure about.
If a floor or threshold is missing, say so rather than inventing one.
