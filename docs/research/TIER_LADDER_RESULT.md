# Result: does family agreement on a played wager exceed chance, so the evidence tiers can be percentiles of a null?

**Rule id** `TIER_LADDER_V1` · **Registry id**
`TIER_LADDER:permutation_null_family_agreement:evidence_tier` (kind `audit`) ·
**Registration** `docs/PREREG_TIER_LADDER.md`, commit
`266ef6552bc7dede1fad148979d176bcce1485b7` (2026-09-10T12:32:47-07:00).
**Instrument** `scripts/test_tier_ladder.py`, run unmodified through
`scripts/tier_ladder_read.py`. **Read performed** 2026-10-17 on the forward
ledger through 2026-10-16. **Artifact**
`data/research/tier_ladder/tier_ladder_result.json`.

**Freeze check.** The sha256 of the registration's rule text (everything above
its `## Status` heading, LF-normalised) is
`fdac9a6defed743a2e828e619892495bb0e9f0ed41b87fb651531fae2fdd3ceb`. It was
recomputed from the blob at the freeze commit and from the working copy, and
the two are equal (the only later edits to the document are inside Status). It
is stored in the artifact (`registration.rule_sha256`) and is the value
`verify_recorded` re-checks every night. The rule constants and the
null and percentile code in the script are unchanged since the freeze; two
things in the script were revised afterwards, both before any twenty-date read:
the family-map source (the first draft called a `glue.family_map` fallback and
silently counted systems; the same day it was replaced by the live slip's own
clustering and the fallback became a refusal), and archive-aware reads on
2026-09-28. Disclosed, neither touches the rule.

**This reads agreement among systems against a chance null. It has no price,
makes no claim about winning, and authorizes nothing. It changes no live
number: `slip.EVIDENCE_STRONG_MIN_FAMILIES` is still 3.**

## The registered rule, in its own words

> **H1.** Family agreement on a real wager exceeds what the same systems,
> playing the same number of wagers, would produce by chance — and the tier
> thresholds are the percentiles of that null.

Per slate date, hold fixed which systems played and how many wagers each
played, and how many backers each wager attracted; reassign backers at random;
recompute family counts through the real clustering.

| tier | rule |
|---|---|
| STRONG | family count ≥ the 95th percentile of the null |
| BUILDING | ≥ the 75th percentile |
| THIN | above the null's median |

> **What would make this fail.** Any of these, and no threshold changes: The
> real family counts are not above the null […] The split-half check disagrees
> by more than one family. Fewer than 20 usable dates.

10,000 permutations, seeded (20260910), over every date with at least 5 played
wagers and 5 playing systems.

## Verdict, by the registered rule

**NOT ADOPT.** Answerable (22 usable dates against the 20 required), and two of
the three failure conditions hold:

| check | result |
|---|---|
| enough dates (≥ 20) | PASS, 22 |
| real agreement exceeds the null | **FAIL**: real mean 5.032 families per wager, null mean 7.132 |
| split halves within 1 family | **FAIL**: STRONG 16 / 16, BUILDING 10 / 12, disagreement 2 |

Not "not answerable": the sample floor was met. Not "adopt": a ladder from this
null would be STRONG ≥ 16, BUILDING ≥ 11, THIN ≥ 6, and the rule refuses it.
Consequence, as registered: no threshold changes and the debt stays recorded.

## The read

- **Ledger.** `evidence/decisions_v2.jsonl`, forward-test systems, verdict
  `play`, decision dates 2026-08-31 to 2026-10-16 (33 dates). All after the
  2026-08-27 seal, and **no outcome of any kind was read**: this study counts
  who backed what, not who won.
- **Usable dates: 22** (2026-08-31 to 2026-10-15): 347 wagers, 454
  permutations per date, 157,538 null draws. 57 forward-test systems collapse
  into 28 families through the live clustering; 0 plays fell back to a raw
  system count.
- **Reproduction.** The shares below are computed by `tier_ladder_read.py`;
  the report is computed by the registered script. The read refuses to record
  unless the two agree on the real mean, the null mean and the wager count,
  and they do.

### STRONG share, and what the registration predicted

The registration predicted two things. If agreement were chance, each tier
would catch its percentile of wagers (5% at STRONG, 25% at BUILDING, 50% at
THIN). If agreement were real, real wagers would sit above those cutoffs, and
it said that outcome "would mean the agreement is real, and it would be
reported as such". The observed share of real wagers at each cutoff:

| cutoff | families ≥ | real wagers | null draws |
|---|---|---|---|
| STRONG (null 95th) | 16 | **2.0%** | 7.8% |
| BUILDING (null 75th) | 11 | **13.0%** | 27.9% |
| THIN (null median) | 6 | **34.6%** | 54.2% |
| live STRONG threshold | 3 | **65.1%** | 74.0% |

(The null's share at its own 95th percentile is 7.8% rather than 5% because the
count is discrete and ties sit on the cutoff.) Real wagers are below the null
at every cutoff, not above it. The prediction that would have vindicated the
ladder did not come true.

On the published slips under the live threshold (slips dated up to
2026-10-16): **879 of 971 picks (90.5%) are STRONG**, 160 of 184 distinct
wagers (87.0%), largest family count 20. The drift register expected 10% when
the constant was set. Those picks are the slip's top-ranked wagers (it ranks
on family count first), so this share is higher than the 65.1% of all played
wagers; it is not a separate finding.

## A surprise, and what was checked

Real agreement *below* a chance null is the opposite of the expected sign, and
a surprising result means the instrument is the first suspect. Checked:

1. **The instrument reproduces.** Reproducing the registered script's counts
   from its own functions and draw order matches its report exactly (above).
2. **The clustering is the likely cause, in part.** The family map merges
   systems whose forward decision sets overlap (Jaccard ≥ 0.8) or whose
   genomes share a feature set. Systems that back the same wagers are merged
   into one family *by construction*, so a real wager's backers fall in fewer
   families than a random reassignment of the same backer slots (which breaks
   the co-selection the map was fitted on). That is a reading, not a proof.
3. **Exploratory, post hoc, not registered, cannot change the verdict:** the
   same null with a family map built from genome structure alone. Real mean
   5.65 against null mean 7.79: the same direction, so the fitted-on-the-same-
   decisions circularity is not the whole explanation. 36 plays had no
   structural family and were counted individually, which weakens that check.
4. **Split-half instability** is a separate failure and does not depend on the
   direction: the BUILDING cutoff moves from 10 to 12 between halves (the
   early weeks have fewer wagers per date than the later ones).

None of these rescues the rule. They are the reasons a successor registration
(`docs/decisions/evidence_strong_tier.md`, option C) would need a different
null, not a loosening of this one.

## Part 2: the falsification battery

**System.** `606be696ff199952`, the one forward-test system whose latest
scorecard still read `battery_verdict: NOT_RUN` while the readiness check
counted 30+ graded selections.

**Entry point.** `src.research.battery.run`, unmodified, called by
`scripts/readiness_battery_read.py`. Artifact
`data/research/battery_reads/606be696ff199952_2026-10-16.json`.

**Why the settle path did not write a verdict.** The two counts are different
counts. `scripts/research_readiness.py` counts paper-account WIN/LOSS
settlements joined to the decision's `consensus_fair`: **32**.
`src/engine/settle_slate.py`'s `_battery_research_for` counts decision/review
pairs settled WIN or LOSS: **27**. The five missing are 2026-08-31 launch-day
wagers, graded in the paper account and never reviewed. 27 is below
`battery.MIN_N` = 30, so `NOT_RUN` was the honest scorecard; the settle path
was right and the escalation fired on a premise the wiring does not share.
The other 22 ready systems (readiness lists 23) all reach 30 by the settle
join and all carry a real verdict.

**Result on the 32 rows** (`ran: true`, `survives: true`, fatal rules fired:
none): baseline effect −0.099 (mean of won − implied; 95% CI −0.282 to +0.100,
date-clustered, 14 clusters; p = 0.316). **Vacuous.** None of the five
pre-registered fatal rules had the data to be judged: `season_split`,
`team_concentration`, `book_concentration` and `dose_response` were skipped
(the rows carry no season, team, book or dose), and `extreme_removal` left 28
rows, under the 30-row floor, so it read no effect. The scorecard the existing
builder produces from this result would read `battery_verdict: PASS`, with
zero judged fatal rules. That is exactly the vacuous `survives` that
`scripts/research_readiness.py`'s docstring warns reads as evidence and
cannot be withdrawn.

**Scorecard recorded, not appended.** The built scorecard is in the artifact.
It was not appended to `evidence/scorecards_v2.jsonl`: the hourly loop owns
that hash chain and a row appended from a branch forks it on merge;
`run_settle` is its only writer and joined 27, not 32; and the result is
vacuous.

**A finding that goes beyond this system.** Settlement hands the battery only
`{date, won, implied}`. On those rows exactly one of the five fatal rules,
`extreme_removal`, can ever be judged: this holds for all 22 systems that reach
30 rows. So every `PASS` (300 rows) and `FAILED` (193 rows) now in
`evidence/scorecards_v2.jsonl` (all rules version 2.0.0, none the `unknown`
error shape) can only be that one rule's verdict, and "not falsified" means
"survived 1 of 5 kill tests". Nothing here changes the battery or the
ledger; it is reported so a `PASS` is not read as more than it is
(`tests/test_tier_ladder_recorded_read.py`, `BatteryReadJudgeabilityTest`,
pins it).

## What each ESCALATE does now

Run print-only on 2026-10-17: the same three check commands and conditionals
the loop uses, without commits or writes (`scripts/daily_loop.sh` itself was
not executed under the worktree guard that blocked it).

| line | before | after this change | silenced? |
|---|---|---|---|
| tier ladder "answerable and did not adopt" | printed nightly | prints `RECORDED: tier ladder pre-registration read NOT_ADOPT ...` | **Yes, legitimately, once `docs/decisions/tier_ladder_recorded_read.patch` is applied to `scripts/daily_loop.sh`.** The loop edit itself was refused to this worker, so on the committed loop the line still prints. |
| drift: `slip.EVIDENCE_STRONG threshold` and `share of published picks graded STRONG` (and the loop's wrapper line) | printed nightly | unchanged | **No, and it should not.** The constant is still miscalibrated (20 vs 3; 0.905 vs 0.10). A recorded read does not change that. It stays acknowledged `open` in `docs/ESCALATIONS.md` and ends when the owner chooses (`docs/decisions/evidence_strong_tier.md`) and the register is changed to match. |
| research readiness "30+ graded selections … still NOT_RUN" | printed nightly | unchanged | **No.** Honest `NOT_RUN` on the settle join (27 < 30). Ends when the system gains 3 reviewed selections, or when the readiness count uses the settle join (a deliberate edit to `scripts/research_readiness.py`, not made). |

What the recorded read must keep satisfying to silence the first line
(`scripts/tier_ladder_read.py --check-recorded`): the artifact is present and
parseable with verdict `NOT_ADOPT`; the registration's rule text still hashes
to the frozen value; the registered script's nine constants still equal the
ones the read used; and the alpha registry carries a verdict row naming the
artifact's sha256. A recorded `ADOPT` never verifies, so it escalates.

## Limits that travel with this result

- A fixed cut: 22 usable dates, early weeks thin. More dates could change the
  answer; they cannot change *this* read, and a later "adopt" on a re-run would
  be a new registration's job, not this one's (the loop's ADOPT branch is
  untouched and a recorded ADOPT is refused as an all-clear).
- The family map is the live map at read time, built from the whole forward
  history (its fingerprint is in the artifact), not cut at 2026-10-16.
- The null conditions on a clustering fitted on the same decisions. See the
  surprise section.
- Agreement among systems is not a probability of winning, and nothing here
  says any system has an edge.

## Registry

An `audit` registration (`registered_utc` 2026-09-10T19:32:47Z, the freeze
commit; the registry learned of it on 2026-10-17, disclosed in the row) and a
`result: "audit"` verdict naming the artifact's sha256. `kind: audit` on
purpose, as for SR1's amendment: `public_research_counts()` counts only
hypotheses, so the product's "N pre-registered" does not move; `total_searched`
audits and `read` each rise by one.

## Reproduce

`python3 scripts/tier_ladder_read.py read --through 2026-10-16` prints the read
(`--write --register` records it; it refuses to overwrite).
`python3 scripts/tier_ladder_read.py --check-recorded` verifies the record.
`python3 scripts/readiness_battery_read.py --system 606be696ff199952 --as-of
2026-10-16`. Tests: `tests/test_tier_ladder_recorded_read.py`.
