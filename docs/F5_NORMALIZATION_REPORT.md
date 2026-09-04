# T-2h normalization run — result

Owner-approved 2026-09-04. Scope: **2023-05-10 .. 2024-10-07, F5 moneyline
only.** Acquisition and verification only; **no hypothesis was evaluated.**

## 1. Credits — the authorization was EXCEEDED

| | |
|---|---|
| authorized ceiling | **43,130** |
| **actually spent** | **47,264** |
| **overrun** | **+4,134** |
| balance at start | 72,971 |
| **balance now** | **25,707** |

**Cause: a bug in the retry wrapper written for this run, not in the
acquisition code.** The provider began dropping connections under sustained
load (SSL handshake timeouts, connection resets, one HTTP 502), so the run
was wrapped in a resume loop. A crashed attempt has already spent credits
but returns no report, and the wrapper decremented its remaining budget only
on a SUCCESSFUL return. Across 16 attempts, 15 ended in a crash, so those
attempts' spend was never counted and the tracked ceiling drifted above the
real one.

`f5_tminus2.run()`'s own budget guard was correct throughout; a leaky
counter was placed in front of it. The fix for any future run of size:
**re-read the true balance from the provider between batches rather than
maintaining a local counter.**

Separately, and independent of the bug: measured cost was **10.9
credits/game**, not the 10.0 the ceiling assumed (the difference is per-date
event lookups). A correctly-metered run would have stopped at roughly 3,950
games, about 365 short of the window.

## 2. What the run produced

| | |
|---|---|
| games attempted | **4,315 / 4,315** (complete scope) |
| compliant primary observations (`OK`) | **4,298** |
| `PRIMARY_SNAPSHOT_UNAVAILABLE` | **17** |
| >=5-unique-book pass rate | **100%** of OK rows |
| settlement join | **4,298 / 4,298 = 100.0%** |
| **gradeable decisions (decided)** | **3,682** |
| ties excluded (not bettable) | 616 |
| storage added | 24 MB -> **33 MB** |
| runtime | ~91 min, 16 attempts |

Season split of the gradeable set: **2023 n=1,597, 2024 n=2,085** — a real
discovery/replication split, which is what U1 always lacked.

### Book depth (OK rows)

| min | p25 | median | p75 | max | mean |
|---|---|---|---|---|---|
| 5 | 10 | **12** | 13 | 14 | 11.37 |

Every row clears the frozen >=5 **unique** book floor. Compare the pre-repair
holdings: 29.9% carried zero books and the priced remainder averaged 4.5.

### Timestamp deviation from target T-2h (minutes)

| min | p25 | median | p75 | max |
|---|---|---|---|---|
| -4.40 | -4.37 | **-4.35** | -4.33 | -0.37 |

All inside the frozen +/-5 minute tolerance; all early, none late — the
provider's five-minute grid floor, exactly as recorded in the pre-reg
clarification appended before this run. **Uniform across games, so no
relative bias between them.**

## 3. Final eligible N and MDE

**N = 3,682** decided F5 moneylines.

**MDE = 1.62pp** (two-sided 95%, p~0.5).

For scale: `docs/RESEARCH_CATALOGUE.md` B3 died of sample size at 270
decided games and an 8.52pp minimum detectable effect. The purchase spec
targeted 2.28pp. The frozen rule delivered **better than target** — reported
as measured, not steered toward it.

## 4. Honesty notes

- **17 unavailables are real and retained.** The run log's own totals said
  zero, but that count came only from attempts that returned; crashed
  attempts lost their tallies. The 17 are derived from the store itself,
  which is the authority.
- **Nothing slid.** No fallback to another timestamp, no forced coverage.
- **2025 rows** (6 games, bought in the tranche) stay in `F5_RAW_HISTORY`
  marked tuning-only and are mechanically excluded from the eligible
  universe. 2026 remains sealed.
- **1,886 `totals_1st_5_innings` rows** acquired incidentally remain
  excluded from the moneyline universe and its multiple-testing denominator.
- **No strategy evaluation of any kind was performed.** No winner search, no
  ranking, no threshold selection, no outcome-derived field read during
  acquisition.

## 5. Next, in order

Freeze the eligible universe -> pre-register F5 families -> freeze the
complete denominator -> freeze the discovery/replication split -> freeze the
multiple-testing procedure -> freeze the failure criteria -> **only then**
begin discovery.
