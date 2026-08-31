# The machinery validation gate

Before the exploratory interaction family (V4) may be pre-registered, the
research machinery itself — the spec compiler, the funnel, the matchup
matrix and the falsification battery — had to pass seven checks. This
document records all seven, including the one that FAILED, what was amended
because of it, and how the amendment was validated as a general rule rather
than a patch for the case that exposed it.

The rule throughout: **no check was weakened to open the gate.** One check
failed; the machinery was fixed and revalidated; the check itself never
moved.

## The seven checks

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Recover a planted positive effect | PASS | `tests/test_validation_planted.py` — a planted +12.5pp edge, replicated across two seasons, eight clubs, two books and a real dose gradient, comes out `status=candidate`, `q_pass=True`, no fatal battery check |
| 2 | Reject planted nulls | PASS | same module — ten deterministic noise specs (win counts pinned at ~half) produce zero candidates, with the FDR denominator equal to the full family size on every row |
| 3 | Reproduce an established null | PASS | V1's platoon analogs, run through the funnel on the real 2023–24 matrix: `lineup_platoon_share` dies at replication (2023 +1.0pp → 2024 −3.77pp, a sign flip mirroring Stage 2's −15.5/+17.5), `starter_platoon_gap` is killed by the battery (pooled +1.14pp, p≈0.39, matching Stage 2's p=0.44). The machinery reproduces in seconds what Stage 2 took a full bespoke pass to establish |
| 4 | Re-falsify the known false positive (M3) | **FAILED, then fixed** | see below — the story of this gate |
| 5 | Matchup matrix is point-in-time safe | PASS | `tests/test_validation_pit.py` — feature data injected AFTER a game's cutoff leaves the built row byte-identical; the same payload dated before the cutoff moves the row (so the silence is meaningful, not a broken detector); sealed seasons (2025, 2026) are refused structurally; repeated builds are byte-identical |
| 6 | Compiler path equals hand-written logic | PASS | `tests/test_validation_equivalence.py` — an independent hand implementation matches the compiled spec path to 10 decimal places, both directions |
| 7 | Battery cannot mutate the primary hypothesis | PASS | `tests/test_validation_immutability.py` — input rows byte-identical after a run, dose rows never leak into non-dose checks, repeated runs byte-identical, no module-level mutable state |

## Check 4: the failure, verbatim

On the real M3 false positive — 5,276 graded deviations, 249 selections at
the registered 2pp threshold, effect +8.49pp, clustered p = 0.006, exactly
the candidate `docs/RESULTS_V2.md` documents being killed by hand —
`battery.run(...)` returned **survives=True**. The battery, built to
automate the kill-tests that destroyed M3, passed M3.

Two rule gaps, found by adversarial adjudication:

1. **Dose rule.** M3's above-spike band held 7 rows — under the 30-row
   judgement floor — so the rule's "at least one judgeable band above the
   spike" precondition failed and the check reported non-fatal, even though
   the band below the spike was judgeable and negative (−0.33pp over 5,027
   rows). An unjudgeable upper tail was rescuing the exact signature the
   rule exists to kill.
2. **Concentration rule.** Leaving FanDuel out dropped the effect from
   +8.49pp to +5.53pp at p = 0.159. The fatal condition required p > 0.10
   AND effect < the 1pp floor; the effect leg held it open. A candidate
   could lose its significance and a third of its size to one book and
   still pass.

## The amendments, and why they are general rules

Both amendments were made **before any family was registered**, are written
without any M3-specific name, book, constant or branch, and are versioned:
`battery.RULES_VERSION = "2.0.0"`, with a content fingerprint
(`battery.rules_fingerprint()`) hashing the fatal-rule implementations and
constants, echoed into every verdict.

1. **Dose rule (spike signature).** A spike over a judgeable ≤0 below-band
   is now fatal unless some judgeable band above the spike carries at least
   half the spike's effect. Doubt BELOW the spike still protects (an
   unjudgeable below-band, or a spike in the bottom band, stays non-fatal —
   the kill needs positive evidence against). Doubt ABOVE no longer rescues:
   once the band below has judged against, the burden of showing a dose
   gradient is the candidate's, and an upper tail too sparse to judge is
   not a gradient.
2. **Concentration rules (team and book).** A second fatal leg: when the
   full slice is itself significant (p ≤ 0.05), losing one unit is fatal if
   it pushes p above 0.10 AND shrinks the effect below 0.75× the full
   effect. The shrinkage leg is what keeps the rule honest for real
   effects: a uniform effect loses significance to sample size when a sixth
   of its rows leave, but keeps its size; an effect that loses both was
   that one slice.

### The generality matrix

Per the standing directive, an amendment that kills M3 is acceptable only if
it is a general skeptical rule. `tests/test_battery_generality.py` holds a
controlled six-case validation matrix — a uniform genuine effect, a real
monotonic dose-response, a one-book concentrated artifact, a sparse
unjudgeable upper tail (with conservatism companions), a sign-flipping
effect, and pure deterministic noise — plus a source-level check that no
fatal rule contains an M3-specific identifier. Legitimate effects survive;
artifacts die; sparse evidence below a spike still protects. M3 itself is
pinned as a regression case in `tests/test_validation_m3.py`, which rebuilds
the candidate from raw price paths (asserting the reproduction matches the
documented 249/+8.49pp before asserting anything about the verdict) and
requires survives=False under both the registered bands and the funnel's own
band construction.

One deliberate call inside the matrix deserves its own record. The
exact-null control is KILLED by the concentration checks — leg (i), the
original pre-registered rule: an effect under the floor that cannot hold
significance through leave-one-out "was never a market-wide effect", and
zero effect is the limiting case. The pre-amendment battery returns the
identical verdict on the same rows, so this is the original rule behaving
as written, not a side effect of the amendments. It was left alone for
three reasons: re-judging a pre-registered rule after seeing what it kills
is the exact move the battery forbids; the verdict's direction is
conservative (it can only ever stop a promotion); and in the funnel a null
never reaches the battery — the screen and replication gates sit upstream.
What the null test DOES require is that no shape-claiming rule
(season_split, extreme_removal, dose_response) fires on pure noise, and
that an exact null is never endorsed.

### The shadow comparison

The old battery (commit 915bae6) and the amended battery were run
side-by-side over every previously evaluated candidate with reproducible
inputs — M3 under both band constructions, the planted edge, all ten planted
noise specs through the funnel itself, and the V1 platoon analogs on the
real matrix. **15 comparisons, 2 changes, 0 unexpected:**

| Candidate | Old verdict | New verdict | Expected? |
|---|---|---|---|
| M3, registered bands | survives | fatal: book_concentration, dose_response | expected — the point of the amendment |
| M3, funnel bands | survives | fatal: book_concentration | expected |
| planted edge | candidate | candidate | unchanged, as required |
| 10 planted noise specs | each dead at its designed exit | identical | unchanged |
| real-matrix platoon share | blocked_coverage | blocked_coverage | unchanged |
| real-matrix starter gap | killed_by_battery (4 checks) | killed_by_battery (same 4) | unchanged |

## Verdict

All seven checks green under the amended, versioned battery
(RULES_VERSION 2.0.0); the skeptical adjudication result is recorded below.
Only after that adjudication returned gate_open=true was the V4 family
eligible for registration.

## Adjudication

_(recorded when the post-amendment adjudication completes)_
