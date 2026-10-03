# Turning the AI analyst on

Status: built, tested, **off**. It runs only when `ANTHROPIC_API_KEY` is set in the daily job.
Until then every step says so and moves on; nothing is called, nothing is written, nothing breaks.

Design and prompt: `docs/AI_ANALYST.md`. This page is only the owner's steps.

## The steps (about five minutes)

### 1. Create the key

1. console.anthropic.com, Settings, API keys, Create key. Name it `linehound-analyst`.
2. **Set a monthly spend limit on that workspace in the console** (suggested: $60). The code has its
   own hard cap per run ($6 and 600,000 tokens, `config/analyst.json`), but the console limit is the one
   that holds even if someone edits the config.
3. Copy the key once. Do not paste it into chat, a file, a commit or a log.

### 2. Add the repository secret, by name

GitHub, repository Settings, Secrets and variables, Actions, New repository secret.

- Name: `ANTHROPIC_API_KEY` (exactly, same as the environment variable)
- Value: the key

or, from a terminal that is logged in to `gh`, which prompts for the value so it never enters your
shell history: `gh secret set ANTHROPIC_API_KEY`.

### 3. Apply the one workflow line

`docs/decisions/ai-analyst-key.patch` adds one line to the "Run the daily loop" step of
`.github/workflows/daily-loop.yml`:

```
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

```
git apply docs/decisions/ai-analyst-key.patch
# if your checkout has CRLF line endings and git complains:
git apply --ignore-whitespace docs/decisions/ai-analyst-key.patch
```

**Apply it to the copy of the file the schedule actually reads.** GitHub runs a scheduled workflow from
the default branch's copy of the file, and this repo's default branch is not the working line (see the
header of `daily-loop.yml`). Put the line in both copies, or the 10:00Z run will not see the secret.
Nothing under `.github/` was edited by the work that built the analyst; this patch is the whole change.

The daily job already calls the analyst: `scripts/daily_loop.sh` runs `scripts/analyst_step.sh` after
settlement. That step grades yesterday and the day before (no key needed), then runs today **only if
the key is set**. It always exits 0 and never prints `ESCALATE`, so a bad analyst day cannot fail the
data collection around it.

### 4. Check it

- Free check of what would be sent: `python -m src.cli analyst run --date 2026-10-03 --game NYY@TB --dry-run`
  (no key, no cost; add `--print-request` for the full body).
- One real game, about $0.10:
  `ANTHROPIC_API_KEY=... python -m src.cli analyst run --date <today> --game <AWAY@HOME>`
  then `python -m src.cli analyst record`, which prints the record, the ledger integrity check and
  the cost per day. A real local run writes to YOUR checkout's `evidence/analyst_v1.jsonl`,
  `evidence/analyst_usage_v1.jsonl` and `evidence/analyst_packets_v1/`. Do not commit or push them (the
  daily job owns those files and a second chain would not merge); discard them when you have looked.
- In the daily job's log, look for lines starting `analyst:`. `PUBLISHED <game>` is a game published;
  `STOPPED: spend cap reached` is the cap doing its job; `SKIP` lines say why a game was left alone.

## Expected cost

**Estimates until the first measured day** (the usage log, `evidence/analyst_usage_v1.jsonl`, records the
real tokens and dollars per game; `analyst record` prints cost per day). Assumptions are in
`docs/AI_ANALYST.md`, "Cost model".

| | estimate |
|---|---|
| per game | about $0.08 to $0.11 (about 11,000 tokens in, 6,000 to 9,000 out, at $2 and $10 per million) |
| fifteen-game day | about $1.20 to $1.70 |
| a month of slate days | about $35 to $50 |
| worst case per game | $0.18 (a full 16,000-token answer) |
| hard cap per run | $6.00 and 600,000 tokens, then it stops and says so |
| optional model critic | about +$0.03 per game, off by default |

This is a new recurring cost on top of the data budget (`docs/RESOURCE_POLICY.md`, the survival mandate in
`docs/SURVIVAL_DASHBOARD.md`). Whether it earns its place is a call for the owner; the record is how it
will show whether it does. Nothing about the card depends on it.

## One decision to make: when it runs

The daily job runs at **10:00Z**. That is before most lineups post, so every game is analysed and frozen
without one, the packet says so (`missing`), and the model is told that PASS is the default when evidence
is thin: expect most player props to pass at that hour. The better hour is later, when lineups exist.
Two ways, neither needed to turn it on:

- Move the call: run `bash scripts/analyst_step.sh <today> <yesterday>` from `scripts/afternoon_slate.sh`
  (15:40Z) instead of from `scripts/daily_loop.sh`, and give `afternoon-slate.yml` the same one-line
  secret in place of the daily loop's.
- Keep 10:00Z and add a later `analyst run --date <today> --refresh`: a game that has not started can be
  published again as a new version, every version stays in the ledger, and only the newest counts.

A plain run never pays twice for a game that is already published (it is frozen and skipped before any
call); only `--refresh` does, on purpose.

## Turning it off

Any one of these; the first is enough.

1. Delete the repository secret `ANTHROPIC_API_KEY`. The next run prints `analyst: ANTHROPIC_API_KEY is not
   set; today's analysis was not run` and spends nothing. Grading of games already published continues
   (it needs no key).
2. Revoke the key in console.anthropic.com. A run then fails at the API, prints `FAIL ... HTTP 401`, and
   stops after two games in a row fail.
3. Remove the `ANTHROPIC_API_KEY` line from the workflow.

Turning it off deletes nothing. The ledger (`evidence/analyst_v1.jsonl`), its packets and the record page
section stay exactly as they were, so the record of what it did remains checkable.
