# Audit — is `*_probable_id` a point-in-time leak for 2023–24?

Raised by `docs/EVOLAB_PHASE0_FEASIBILITY.md` §3 and §8, and by hazard H13:
`away_probable_id` / `home_probable_id` come from MLB's `probablePitcher`
hydrate (`src/providers/mlb.py:163`, flattened at `:200-201` through
`_pitcher_id` at `:495-496`), fetched retroactively for games that had already
finished. If that field reflects who *actually* started rather than who was
*announced*, every historical feature conditioned on "the opposing starter"
carries knowledge no pre-game system could have.

Measured 2026-08-31, read-only. Nothing outside this file was written; no code,
test or store was touched; no network call was made; no credit was spent.

**Evidence boundaries observed.** 2023 and 2024 only. 2025 is tuning-only and
was not read. **2026-01-01..2026-08-27 is SEALED and was not opened** — the
statcast windows keyed `2026-*`, `data/watch/*` and `data/processed/*` were
never read by any script behind this audit.

---

## The answer, up front

| question | answer |
|---|---|
| Does the stored probable equal the pitcher who actually started? | **Yes, 99.90% (2023) and 99.92% (2024) of the time.** |
| Measured disagreement, side-level | **5 / 4,859 = 0.1029% (2023)** · **4 / 4,852 = 0.0824% (2024)** |
| Are the 9 disagreements scratches? | **No. Not one of them is.** They are openers, bulk-pitcher listings, and one pitcher who never threw. |
| Is the leak real? | **Yes.** The agreement rate is ~12–41× too high to be a pre-game announcement snapshot. |
| Exposure | **~110–370 starter-sides across 2023–24 ≈ 2.3%–7.6% of the 4,819-game replay universe** — and that range rests on an *estimate*, not a measurement. |
| Does it overturn any published conclusion? | **No.** The leak inflates apparent feature quality, and all four families produced zero survivors. It makes the existing nulls **stronger**. |
| Is the forward path affected? | **No.** Pre-game the hydrate can only return the announcement. `briefing` is fine. |

---

## 1. The mechanism, from the code

`fetch_schedule` requests `hydrate=probablePitcher,team,linescore`
(`src/providers/mlb.py:163`). `parse_game` copies
`teams.{away,home}.probablePitcher.id` straight into `*_probable_id`
(`:200-201`). `src/pipeline/history.py:49` writes those two columns verbatim
into `data/historical/mlb_results.csv`. There is no second source and no
reconciliation step: whatever the hydrate said at fetch time is what the store
holds, forever.

**The fetch was unambiguously retroactive.** The repository's first commit is
`be8c99b`, dated **2026-08-27**. Every 2023 and 2024 row in the store was
fetched two to three years after those games finished. Whatever the hydrate
returns for a completed game is what this project has.

**Where it lands.** `src/research/matrix.py:221-222` performs the crossing —
each side's lineup is scored against the *opposing* `*_probable_id` — and nine
features are gated on that single id being present and correct:
`lineup_platoon_share`, `starter_platoon_gap`, `lineup_vs_primary_pitch`,
`primary_pitch`, `primary_pitch_share`, `top_minus_bottom`,
`lineup_vs_starter_history`, `starter_velocity_gap`,
`starter_groundball_share`. Families V1, V4 and V5 read those columns. (V2 —
de-vig method and price autocorrelation — does not touch starter identity and
is unaffected by anything in this document.)

---

## 2. Measurement 1 — stored probable vs the pitcher who threw the first pitch

**Method.** Derived independently of the schedule endpoint, from the 2023/2024
statcast windows only (94 windows, 1,432,440 pitch rows scanned out of
the 2,737,968-row store, via the same file layout `src/providers/statcast_pitches.py`
reads).

- For each `game_pk`, take every inning-1 pitch. The pitcher of an at-bat is
  the pitcher of that at-bat's **first** pitch — mid-at-bat pitching changes
  exist and an earlier version of this script got one case wrong by ignoring
  them (2024-06-05 DET@TEX, Maeda→Wentz on at-bat 4).
- The away team always bats first, so the pitcher of the lowest at-bat number
  is the **home** starter.
- The **away** starter is the pitcher of the first at-bat whose batter appears
  in that game's *home* lineup (`data/historical/lineups.jsonl`). This survives
  a home-side pitching change inside the top of the first, which a naive
  "first different pitcher" rule does not.

**Result.**

| | 2023 | 2024 |
|---|---|---|
| regular-season games in the results store | 2,430 | 2,429 |
| games with inning-1 statcast rows and a derivable both-side starter | 2,430 | 2,427 |
| starter-sides compared | 4,859 | 4,852 |
| sides where stored `*_probable_id` **≠** actual first-pitch thrower | **5** | **4** |
| **side-level disagreement rate** | **0.1029%** | **0.0824%** |
| distinct games affected | 5 (0.206%) | 3 (0.124%) |
| sides with no stored probable at all | 1 | 2 |

Two 2024 games have no statcast inning-1 rows and were not compared.

---

## 3. Measurement 2 — an independent cross-check on a different endpoint

Statcast and the schedule hydrate are both MLB properties, so a single method
is not enough. The second measurement uses `data/historical/pitcher_logs.jsonl`
— MLB's `people/{id}/stats?stats=gameLog` (`src/providers/mlb.py:347`), a
different endpoint with a different field — and asks a different question: for
each stored probable, does that pitcher's own game log show `games_started ≥ 1`
on that date?

| | 2023 | 2024 |
|---|---|---|
| stored probables checked | 4,859 | 4,856 |
| **started that date** | 4,854 | 4,852 |
| appeared but `games_started = 0` | 5 | 4 |
| no appearance at all | 0 | 0 |
| **"did not start" rate** | **0.1029%** | **0.0824%** |

**The two methods return identical rates and the identical case list.** Nine
cases, the same nine. A derivation error in one would have to be mirrored
exactly by the other for that to be coincidence.

---

## 4. The nine disagreements, itemised — none is a scratch

| date | game | side | stored probable | actual first-pitch thrower | what it is |
|---|---|---|---|---|---|
| 2023-05-13 | 718203 NYM@WSH | away | Stephen Nogosek | Joey Lucchesi | Nogosek pitched the same game from inning 3 (46 pitches) |
| 2023-05-24 | 718037 OAK@SEA | away | Ken Waldichuk | Austin Pruitt | Waldichuk from inning 2, 77 pitches — bulk behind an opener |
| 2023-06-09 | 717837 LAD@PHI | away | Michael Grove | id 624647 (14 pitches) | textbook opener; Grove threw 85 |
| 2023-07-26 | 717251 OAK@SF | away | Hogan Harris | id 676206 (49 pitches) | Harris from inning 3, 51 pitches |
| 2023-09-10 | 716638 AZ@CHC | away | Brandon Pfaadt | Joe Mantiply (13 pitches) | opener + second reliever, Pfaadt 78 pitches |
| 2024-06-26 | 746942 TOR@BOS | away | Ryan Burr | Yariel Rodríguez | both sides mismatch on one game — the resumption signature |
| 2024-06-26 | 746942 TOR@BOS | home | Nick Pivetta | Kutter Crawford | Pivetta from inning 2, 93 pitches |
| 2024-07-28 | 744902 TEX@TOR | away | Jon Gray | id 642546 (36 pitches) | **Gray threw no pitch in this game** |
| 2024-08-27 | 746755 TEX@CWS | home | Chris Flexen | Garrett Crochet (4 pitches) | Crochet faced one batter; Flexen threw 95 |

Eight of the nine stored probables pitched in the very game they were listed
for, just not first. In every one of those, MLB's own game log agrees they were
not the official starter — so the store is **not** a literal copy of the box
score's starting pitcher either. The single case where the stored probable
threw nothing at all is **1 in 9,711 sides = 0.010%**.

This matters for the verdict below: the residue is *structural* (openers, bulk
listings, suspended-game resumptions), not *informational*. There is no
population of scratches hiding in the disagreements.

---

## 5. Verdict — the leak is real

The question is not whether 99.9% agreement is high. It is whether 99.9%
agreement is *possible* for a genuine pre-game snapshot.

`docs/RESEARCH_V3_TIMING.md:143` estimates **`starter_scratch` at 0.3–1
events/day league-wide** — a probable-pitcher change between polls. (The
0.3–2/day figure sometimes quoted merges that row with `hitter_scratch`, which
the same table puts at 1–2/day. Starter scratches are the narrower 0.3–1.)

Over 367 regular-season game days in 2023–24 that is **110 to 367 scratched
starter-sides**. Against 9,711 compared sides:

| | expected mismatch if the store held a pre-game announcement | measured |
|---|---|---|
| at 0.3 scratches/day | ~1.1% of sides | **0.093%** |
| at 1 scratch/day | ~3.8% of sides | **0.093%** |

The store is **12× to 41× too clean**. And the nine disagreements it does carry
are openers and resumptions, not scratches — so the observed scratch count in
the historical store is effectively **zero**. A pre-game feed cannot be that
clean, because scratches are real.

**Conclusion: the stored value is the terminal, pre-first-pitch state of the
starter announcement.** Every scratch that occurred between the announcement
and first pitch has been silently absorbed.

**What the stores cannot settle, stated honestly.** Two mechanisms produce this
observable and nothing in `data/` distinguishes them:

1. MLB overwrites `probablePitcher` for completed games with the game's actual
   starter; or
2. MLB updates `probablePitcher` live as scratches are announced, and a fetch
   years later simply reads the last pre-first-pitch value.

**For a replay the distinction is immaterial.** Under either mechanism the
field a replay reads at T = 12 hours before first pitch is a value that was not
knowable until much later. The nine residual cases are mildly more consistent
with (2) — an overwrite to the box-score starter would have left zero.

**And one alternative I cannot exclude.** If the true day-of scratch rate for
2023–24 were genuinely ~0.1%, the store would be an honest pre-game feed and
there would be no leak. I judge that implausible — 0.1% is roughly five
scratches per season across all thirty clubs, or one per five weeks — but the
V3 figure it is being tested against is an **estimate at freeze, not a
measurement**: `docs/DEBRIEF.md:475` records that the forward watcher has
reported **no `starter_scratch` events yet**. The rate this verdict leans on is
therefore not measured anywhere in this repo, and the honest statement is:
*the leak is real conditional on MLB scratches being commoner than 1-in-1000
starts.*

---

## 6. Exposure

Nearly every row depends on this field: only 3 of 9,718 regular-season sides have no
stored probable at all (99.97% populated). So the exposure is set by the scratch rate,
not by coverage.

| | count | share of the 4,819-game replay universe |
|---|---|---|
| starter-sides in the universe | 9,638 | — |
| scratched sides at 0.3/day | ~110 | **2.3% of games** |
| scratched sides at 1/day | ~367 | **7.6% of games** |
| sides where the store visibly disagrees with the actual starter | 9 | 0.17% of games |
| sides where the stored probable never threw a pitch | 1 | 0.02% of games |

A scratch on either side contaminates that game's row for both sides, because
the matrix crosses each lineup against the opposing starter.

**The effective exposure is smaller than the headline range**, and the honest
version says so. A contaminated row only matters if (a) the class-C feature is
non-null for that side — coverage runs 33.7%–92.0% depending on feature, per
`docs/EVOLAB_PHASE0_FEASIBILITY.md` §3 — and (b) a detector actually fires on
it. For a detector firing on 10–20% of games, the number of *selections* built
on a scratched starter across both seasons is on the order of **5 to 50**.
Not measured per detector; that would take re-running each family's selection
set against a scratch list that does not exist.

---

## 7. Impact on published work — no conclusion is overturned, and the nulls get stronger

Reasoned through explicitly, because the direction is what settles it.

**The leak's sign is favourable to the features.** On a scratched game the
historical matrix scored the lineup against the pitcher who genuinely threw,
using his real pitch mix, platoon split, velocity and ground-ball profile. A
live pre-game system would have scored it against the announced pitcher and
been wrong. So the historical features were, on the affected slice, **better
informed than the live system could ever be**. Any measured effect is an
upper bound on the honest one.

**All four families produced zero survivors.**
`docs/RESEARCH_CATALOGUE.md`: V1 — zero of eight clear FDR + the 1pp floor,
every interval includes zero. V2 — null. V4 — zero survivors, three of six
wrong-signed in the screen year and both replications sign-flipped. V5 — zero
survivors, all three died at 2024 replication.

**Therefore:** features that were handed a small advantage still found nothing.
Removing the advantage cannot manufacture a survivor from a detector whose
confidence interval already spans zero and whose replication year flipped sign.
**The leak makes the published nulls stronger, not weaker.**

Four things this does *not* license saying:

1. **It is not why the families failed.** The affected fraction is 2–8% of
   rows and the perturbation within a row is one starter swapped for another
   pitcher off the same staff — noise in a feature, not a signal. Blaming the
   nulls on this leak would be as wrong as ignoring it.
2. **"Cannot manufacture a survivor" is a judgement, not a proof.** A leak can
   in principle destroy a real signal as well as fake one — that would need the
   contamination to be anti-correlated with the true effect, and there is no
   mechanism for that here. The claim is *no reversal is plausible*, not *no
   reversal is possible*. It was not tested by re-running any family, and it
   should not be described as if it had been.
3. **V2 is untouched.** N12 and N13 never read a starter id.
4. **This does not rehabilitate anything.** Nothing in `docs/RESULTS_2023_24.md`
   or `docs/VALIDATION_PACKAGE_1.md` becomes citable; those are invalidated by
   the price-join bug (catalogue T4), which is a separate and far larger defect
   than this one.

**Recording the miss.** `docs/EVOLAB_PHASE0_FEASIBILITY.md` §3 asserted "the
stored value is the actual starter" and §8 recorded the magnitude as not
measured. The assertion is now supported by measurement, and the magnitude is
measured here. The audit that flagged it was right to flag it and right to say
it had not been quantified.

---

## 8. Consequence for the Evolution Lab, and what the replay engine must do

**Why the lab is the sharp end.** A manual family tests a dozen pre-registered
hypotheses. The lab will search a genome space orders of magnitude larger and
will keep whatever scores. A 2–8% slice of rows carrying information the live
system cannot have is exactly the shape of defect an automated search converts
into a false survivor — and unlike the manual families, the lab has no prior
belief to be embarrassed by a wrong-signed screen. This must be closed *before*
Phase 2 selects anything, not audited afterwards.

**It cannot be repaired.** No archived probables feed with fetch timestamps
exists for 2023–24, none can be bought (`docs/EVOLAB_PHASE0_FEASIBILITY.md`
§8), and `rosterwatch`'s `fetched_utc` history starts 2026-08. Reconstructing
an announcement history would be fabrication.

**Recommendation — five items.**

1. **Make starter identity a named, versioned engine parameter**, as hazard
   H13 already requires, with the default written out on every artifact:
   `starter_identity = "actual_at_first_pitch"`,
   `announced_probable_available = false`,
   `measured_agreement_with_actual = 0.9990 (2023) / 0.9992 (2024)`.
   Never silent, never inferred from context.
2. **Bar the engine from claiming starter identity is point-in-time.** It is
   availability class C with a *known-false* availability time, not class B.
   `src/model/pointintime.py` marks the rebuilt inputs CLEAN on the basis of
   cutoff-respecting accumulation, which is correct and is a different claim
   from "the pitcher id was knowable at T". The distinction should be visible
   in the audit rather than left to a reader.
3. **Attach a scratch-perturbation sensitivity run to every candidate that
   survives.** Concretely: resample a random 4% of games (the midpoint of the
   measured-exposure range), replace the opposing starter with another starter
   from the same club's rotation in that month, rebuild the affected features,
   re-run the strategy. A candidate whose survival moves materially under that
   perturbation is leak-sensitive and is not a survivor. This is cheap, local,
   deterministic under a stated seed, and spends no credits.
4. **Require forward re-validation for anything that survives.** The forward
   path is the only place an honestly-timed probable exists: `rosterwatch`
   records probable changes bracketed between polls with `fetched_utc`. A
   2023–24 survivor is a hypothesis to be tested forward, not a result.
5. **Print the exposure on the artifact.** "~2–8% of rows may carry a starter
   the live system could not have known; residual visible disagreement 0.09%."
   A reader should not have to find this document to know the number.

---

## 9. The forward path is not affected — do not confuse the two

`src/pipeline/briefing.py:333` and `:349-350` read the same
`away_probable_id` / `home_probable_id` fields, and `src/cli.py:526` supplies
them from a **live** `mlb.fetch_games(args.date)` on the day's slate.

Pre-game the hydrate has nothing else to return. The game has not been played,
there is no actual starter yet, and the field can only carry the announcement
as it stands at fetch time. A briefing built at 14:00 for a 19:10 first pitch
holds the 14:00 announcement — genuinely point-in-time, by construction.

`src/pipeline/rosterwatch.py:307-325` (`_probable_events`) then treats a change in that field as a
`starter_scratch` event and brackets it between two of our own polls. That
module only makes sense because the forward value *moves*; it is the direct
evidence that the pre-game field is an announcement rather than a result.

**So: the historical store leaks and the forward system does not.** They are
the same two column names and completely different guarantees.

One secondary note, non-blocking: `src/cli.py:800-801` builds a retrospective
card by reading `*_probable_id` out of the historical store. That path inherits
the post-hoc value. It is correct for what it is — a card about a game that has
already happened — but it is not a reconstruction of the pre-game card, and
should not be presented as one.

---

## 10. Not measured

- **The actual 2023–24 late-scratch rate.** No source in the repo carries it.
  The exposure range in §6 rests on the V3 freeze *estimate* of 0.3–1/day, and
  `docs/DEBRIEF.md:475` records that the forward watcher has produced no
  `starter_scratch` events yet, so that estimate remains unvalidated.
- **Which mechanism MLB uses** (post-hoc overwrite vs live update). Would need
  a probables feed captured pre-game for 2023–24 and compared against the same
  endpoint fetched today. The pre-game half does not exist.
- **Per-detector selection counts built on a scratched starter.** Needs a
  scratch list that does not exist.
- **Whether de-leaking changes any published effect size.** Not tested. §7
  argues no reversal is plausible from the sign of the leak and the zero
  survivor count; it does not re-run a family.
- **2025, and the sealed 2026-01-01..2026-08-27 window.** Not read.

---

*Read-only audit. Only this file was written. Scratch scripts lived under
/tmp and touched nothing in the tree.*
