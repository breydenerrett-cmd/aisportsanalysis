# Decision needed: what should the slip's STRONG tier mean now?

**Status: OPEN. Needs the owner. Nothing in this note has been applied.**
`src/engine/slip.py` still has `EVIDENCE_STRONG_MIN_FAMILIES = 3`, and no
file under `src/`, `web/` or `api/` was touched by the work that produced
this note.

Written 2026-10-17 from `docs/research/TIER_LADDER_RESULT.md`.

## Where it stands

- The slip's STRONG grade (green, "Multiple independent systems agree, at the
  strongest signal they check for") fires at 3 or more independent families.
  It was set when 3 was the largest agreement ever seen on the live ledger.
- 2026-10-17: **20** families is the largest published, and **90.5%** of
  published slip picks (879 of 971 through 2026-10-16) are STRONG; 87.0% of
  the 184 distinct wagers that ever appeared on a slip. The grade was meant to
  be rare. It is not. (Part of this is selection: the slip ranks by family
  count first, so what it publishes is already the highest-agreement wagers.
  That does not make the label true; it explains why the share is so high.)
- The pre-registered fix (`docs/PREREG_TIER_LADDER.md`) was read on the
  forward ledger and **does not adopt**: real family agreement is below the
  permutation null (5.03 against 7.13 families per wager), and the null's own
  percentiles are not stable across halves (STRONG 16/16, BUILDING 10/12; the
  rule allows 1). A ladder from that null would be STRONG at 16 families,
  BUILDING at 11, THIN at 6; only 2.0% of real wagers reach 16.
- What the registration says to do when the read fails, in full: "no
  threshold changes" and the current threshold stays with the debt still
  recorded. **It does not say whether to keep, relabel, retire or recalibrate
  under a successor.** That is why this is a decision and not a procedure.

## What a failed read does and does not mean

It means this rule, on this population, cannot support a data-derived ladder.
It does **not** mean 3 is the right threshold, and it does not make the label
true. "Strongest signal they check for" is still printed next to a tier that
90% of picks carry. The two are separate facts and the first does not repair
the second.

## The choices

**A. Keep the number, change the words.** STRONG stays "3+ independent
families agree" and the sentence stops claiming rarity or strength: for
example "3 or more independent system families back this pick", with the
family count shown on the pick (it already is in the data). Nothing is
calibrated against a population any more, so the two stale entries in
`scripts/calibration_drift_audit.py` are removed in the same change, with the
reason. Cheapest, honest today, and it makes no claim the ledger can't
support. It gives up the idea of a rare green grade.

**B. Retire the four-tier ladder.** Drop STRONG/BUILDING/THIN/MINIMAL and the
colours; show the raw independent-family count and the rung depth, which a
reader can already check. This is what the registered null's failure most
directly suggests (the count is real information; the buckets are not
calibrated to anything). Larger change: `web/js/slip.js`,
`scripts/publication_audit.py`, `STRONG_TIER_RECALIBRATION_OWED`, the drift
register and their tests.

**C. Successor registration, then recalibrate.** Write a new pre-registration
before reading anything, with a null the data can actually test. One concrete
lead, labelled as a lead and not as a result: the family map used by the
registered rule is partly fitted on the same forward decisions it is then used
to count (behavioural overlap at 0.8), so "real below null" is partly built
in. A successor would fit the map on an earlier span (or from genome
structure alone) and count agreement on a later one. An exploratory structural-only map gave the same
direction (5.65 against 7.79) with 36 plays unmapped, so the circularity is
not the whole story. Needs at least another 20 usable dates; until then the
threshold and the incident stand unchanged, so C should be paired with A as
the interim.

**D. Leave it as it is.** Not recommended. The audit keeps escalating, and the
label keeps saying something the ledger contradicts.

## The exact choice needed

Reply with one line, either of these shapes:

- `A` (keep 3, relabel, retire the two drift entries), or
- `B` (retire the ladder), or
- `C with A as interim` or `C with nothing as interim`, or
- `D`.

Then one builder change implements it: `src/engine/slip.py` (labels, and the
constants or the ladder), `scripts/calibration_drift_audit.py` (remove or
re-baseline the two STRONG entries), `scripts/publication_audit.py`
(`STRONG_TIER_RECALIBRATION_OWED`, share alarm), `web/js/slip.js` copy, the
tests that pin them, and the `strong-tier-drift` row in `docs/ESCALATIONS.md`.
Those files were deliberately not touched here.

## What stays loud until you choose

The drift audit's two lines (`slip.EVIDENCE_STRONG threshold`, `share of
published picks graded STRONG`) and the loop's wrapper line keep printing, and
`docs/ESCALATIONS.md` keeps them acknowledged as `open`. They are true. They
stop when the choice lands and the drift register is changed to match it, not
before.

Separately, the one line that *does* go quiet is the loop's "tier ladder
pre-registration is now answerable and did not adopt": that read is performed
and recorded. Its quieting needs the owner to apply
`docs/decisions/tier_ladder_recorded_read.patch` to `scripts/daily_loop.sh`
(an edit the work that produced this note was not permitted to make).
