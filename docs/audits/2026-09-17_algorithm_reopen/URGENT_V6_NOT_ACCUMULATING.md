# URGENT: the one live positive signal is not collecting evidence

Found 2026-09-17. The most important operational finding of the audit.

## The correction that led here

"92 hypotheses, zero survivors" has been stated project-wide, by me included,
and it is WRONG. Counting the registry's 42 verdict rows directly
(`data/research/alpha_registry.jsonl`):

| result | count |
|---|---|
| null | 35 |
| false_positive | 2 |
| **candidate** | **2** |
| audit | 2 |
| withdrawn | 1 |

Two hypotheses are not dead. "Zero survivors" collapses *nothing has been
promoted* (true) into *everything died* (false) — the exact inference failure
this audit was commissioned to find, committed by the audit itself.

## The live one

**`V6:lineup_surprise_direction:h2h`** — when a club posts a lineup missing
players who normally start, the market moves against that club over the next
two hours.

- `docs/LINEUP_DIRECTION_RESULT.md`, 2026-09-11, produced by
  `scripts/probe_lineup_direction.py` against `docs/PREREG_LINEUP_DIRECTION.md`,
  which was committed before the probe was written.
- **n=149, hit rate 0.584, CI [0.5033, 0.6691].** The lower bound is above
  chance.
- Clears the alpha its own pre-registration declared; does NOT clear the one
  the programme's ledger implies at the registry's real family size.
- **NOT PROMOTED**, correctly, and held for forward replication.

The registry's forward window for it:
`{'floor': 150, 'n': 0, 'pending': True, 'start': '2026-09-11T20:38:15+00:00'}`

## The problem

**`n` is 0. It has been 0 for six days.**

`scripts/probe_lineup_direction.py` exists and works. It appears in no
workflow and no shell script:

```
grep -rn "probe_lineup_direction" scripts/*.sh .github/workflows/*.yml
  -> (nothing)
```

Nothing runs it. The forward replication that would promote or kill this
project's only live positive signal is not accumulating, and will not, until
something schedules it.

## Why this matters more than anything else in the audit

Every other finding today is about a system that looks like it works. This is
the inverse: a result found honestly, registered correctly, declared NOT
PROMOTED with real restraint — and then left to collect nothing.

The discipline held perfectly right up to the point where it had to produce
evidence, and there it silently stopped. Six more days of lineups have been
posted and priced since, and not one was measured.

It is also the hypothesis this audit independently ranked most promising:
H1 in `ALTERNATIVE_HYPOTHESES.md` — closing prices efficient, the pre-close
lineup-confirmation window not — written without knowing V6 already existed
and had already read positive. Two independent routes to the same place is
weak evidence about the world but strong evidence that this is where to look.

## What to do, in order

1. **Schedule the probe.** It belongs in the daily loop, after lineups post
   and before first pitch. Until it runs, everything else about V6 is moot.
2. **Backfill what was missed.** Lineup postings since 2026-09-11 are in
   `data/historical/lineups.jsonl` with `observed_utc`; the odds series is in
   `odds_multibook.jsonl`. The six lost days are plausibly recoverable
   point-in-time — verify that before relying on it, because a lineup row
   whose `observed_utc` is the capture time rather than the posting time
   would silently break the as-of discipline this hypothesis lives or dies by.
3. **Do not promote on the backfill.** Forward means forward. A backfilled
   window replicates the discovery; it is not an out-of-sample test, and must
   be labelled as such or it is worthless.
4. **Fix the "zero survivors" line** wherever it appears, including this
   audit's own `CHATGPT_HANDOFF.md`.

## The honest caveat

n=149 at a 0.584 hit rate is one read, on one season, of one market, at one
prediction window. The CI's lower bound sits at 0.5033 — barely above chance.
It failed the stricter ledger-implied alpha for a reason. This is the most
promising thing in the project and it is still probably nothing. The point is
that we cannot find out while the counter reads zero.
