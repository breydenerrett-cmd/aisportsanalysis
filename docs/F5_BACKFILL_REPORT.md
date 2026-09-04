# First-five historical backfill — what was bought, and what it yields

**Owner authorization, 2026-09-04:** up to 45,000 credits;
2023-05-10..2024-10-07; F5 moneyline only; one snapshot per game; preserve
timestamp/book metadata; dedupe against holdings; verify settlement/join
quality continuously; stop and escalate on material divergence.

Executed 2026-09-04 05:0x-05:5xZ. **No hypothesis was evaluated in this
lane** — acquisition and verification only.

---

## 1. Headline

| | spec target | actual |
|---|---|---|
| credits | 45,000 authorized | **36,451** |
| games fetched | ~4,423 | 3,580 new + 439 already held |
| rows in window | — | **4,013** |
| **rows carrying an F5 moneyline** | — | **2,804 (69.9%)** |
| **decided (non-tie) = the bettable sample** | ~3,791 | **2,418** |
| settlement join | ~97% | **100.0%** |
| books | — | 15 distinct, mean 4.9/game |
| timestamps | preserve | 19,560 book entries, all stamped |
| storage | — | 8.1 MB |

Credits remaining after the purchase: **73,196**. Came in **8,549 under**
the ceiling.

## 2. The free prerequisite that made it gradeable

Before buying, the settlement store covered only 181 of the window's 326
dates — a **56.5% join rate**, 1,878 ungradeable games. Buying first would
have spent ~17,000 credits on rows with no outcome to grade against.

A zero-credit StatsAPI backfill closed it to **100.0%** (4,315/4,315) first.
Two real defects were found and fixed doing so, both recorded in `bdd424a`
and the `f5_store` docstring:

- **Date-level resumability.** A date interrupted mid-run was recorded as
  present with games missing permanently. Now keyed on `game_pk`.
- **Postponed/suspended games locked in as false voids.** A game's id first
  seen under its originally-scheduled date was written as "0 innings, void",
  and the real result under the played date was then skipped as already
  present. **34 games corrupted in this window alone**; 32 corrected. Fixed
  by only locking a result once MLB itself marks the game final.

Ties are represented as `winner: null` (14.35%, matching the documented
baseline), never coerced to a side. Two genuine StatsAPI gaps (0.03%) stay
honest voids.

## 3. The material divergence: 29.9% of rows carry no price

**1,199 of 4,013 rows (29.9%) came back with zero bookmakers.** This is the
gap between the spec's ~3,791 expected decisions and the 2,418 actually
obtained, and it is a divergence worth reporting rather than absorbing.

**Cause, measured — not a provider failure, a snapshot-timing mismatch.**
Lead time between the snapshot instant and first pitch:

| | n | median lead | min | max |
|---|---|---|---|---|
| zero-book rows | 1,199 | **+23.91 h** | −5.10 | +27.42 |
| priced rows | 2,814 | **+2.87 h** | −2.64 | +27.42 |

The purchase spec's own probe established that F5 markets post between
**T−24h and T−12h**. `SNAPSHOT_INSTANTS = ("16:50:00Z", "22:50:00Z")` is a
fixed wall-clock pair, so for a large share of games the earlier instant
lands at ~T−24h — *before the market exists*. The books were not missing;
they had not opened yet.

**These rows are recoverable.** Re-querying the 1,199 at an instant closer
to first pitch would cost ~11,990 credits (1,199 x 10) and would raise the
decided sample from 2,418 to roughly 3,400 — at or above the spec's target.
That exceeds the original 45,000 authorization (36,451 + 11,990 = 48,441)
and is therefore **an owner decision, not taken here.**

Also recorded: **291 unmatched** games (~7%, vs ~3% budgeted) — present in
the results file with no matching event in the odds feed. Recorded, never
silently dropped; cause not yet diagnosed. **5 failed** date lookups.

## 4. Bought outside the ask, at no charge

The per-event endpoint returned **1,886 `totals_1st_5_innings` markets** in
the same payloads. The authorization was moneyline only; these arrived free
and unrequested. They are on disk and **no research may use them without the
owner widening scope** — noted here so their presence is never mistaken for
an approved purchase.

## 5. What this unlocks

`docs/RESEARCH_CATALOGUE.md` **B3** is the direct beneficiary: the F5-vs-
full-game bullpen-gap question died of sample size, not evidence — 308 games
with both prices, 270 decided, minimum detectable effect **8.52pp**.

At 2,418 decided the MDE is roughly **2.85pp**; at the recovered ~3,400 it
reaches the spec's **2.28pp**. Either is a different question from the one
that died.

Also newly reachable: **U1** (a real F5 family with a 2023 screen and a 2024
replication split, rather than one undersized pool).

## 6. Next, in order

1. **Freeze the eligible universe** — a hashed manifest naming exactly which
   games and decisions are eligible, so the family cannot later be widened to
   fit a result.
2. **Pre-register the F5 hypotheses BEFORE searching for winners.** Same
   gates as everywhere: 2023 screens, 2024 replicates, FDR over the full
   frozen family, the frozen battery on survivors, every loser published.
3. Diagnose the 291 unmatched before the freeze, so the denominator is
   understood rather than assumed.

No evidence standard is relaxed by this spend. Credits bought more data,
never a weaker gate.
