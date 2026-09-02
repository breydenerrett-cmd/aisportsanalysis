# Adversarial review — V3 timing first read (transaction_first_seen)

Date: 2026-09-02. Reviewer: independent methodology pass (Opus tier),
read-only, against HEAD 4d6f846. Verdict: **FAIL — numbers reproduce,
inference not defensible as written.** The read stays unpromoted until a
correction packet lands and a second review passes. This file is the
record of what the first review found; the correction is appended to
docs/RESEARCH_V3_TIMING.md as a dated second addendum, never by
rewriting the first.

Reproduction: `python3 -m src.cli timing --test` matched every headline
number in the addendum (56 measurable, 39/56 censored, S(0)=1.000,
CI [1,1], p=0.000, complete-case median diff 118.85, KM median diff
164.87, both halves 1.000). Full suite at that head: 3,144 tests, 0
failures, 2 skipped, 603 s.

## Findings by question

**A. Coded test vs frozen wording — REFUTED.**
1. Class tested is broader than the class registered, in the direction
   that favours H1. Frozen `il_roster_move` = "IL placement/activation,
   trade, recall affecting the game" (RESEARCH_V3_TIMING.md:43).
   rosterwatch emits an event for every transaction id first seen.
   Type mix of the 56: 18 Status Change, 11 Recalled, 5 Optioned, 4
   Assigned, 4 Signed FA, 2 Trade, 2 DFA, 2 Released, 2 Selected, 3
   untyped. A market that correctly ignores a Triple-A option is scored
   as hours of "latency". Not disclosed in the addendum.
2. "pre-event relevance estimate (frozen rule, below)" (:56) is never
   defined anywhere and nothing computes it; the umpire amendment (:87)
   propagates the phantom reference.
3. S(0) substituted for the pre-registered median, post hoc and
   unnecessary. The equivalence median>0 iff S(0)>0.5 holds for the true
   survival function, not for the KM estimator, which is pinned at 1.0
   whenever the smallest uncensored value exceeds 0. The pre-registered
   statistic is computable: KM median(diff) 164.87, clustered bootstrap
   95% CI [118.85, not reached] (752/2000 draws not reached);
   complete-case median(diff) CI [74.27, 164.87].
4. Floor assignment wrong for 20 of 56 events. timingtest.py:166-168
   infers the floor from `minutes_to_start <= 180`; the spacing in force
   is recorded in `event["interval"]` (all 56 brackets 14.3-17.6 min).
   Using the recorded brackets: min observed diff 74.17, KM median diff
   209.87 (larger, so the error was conservative, but the published
   "36 dense / 20 hourly" regime line is a derived value stated as an
   observation, and it is false).
5. il_roster_move <-> transaction_first_seen naming: CONFIRMED consistent.

**B. Censoring — direction correct, conclusion overstated.**
Right-censoring at (minutes to first pitch - floor) is correct and
implemented correctly; complete-case bias direction (down) verified.
But 69.6% censoring is largely a design artefact: 92 of 167 events are
dropped by the >=6-books-in-90-min gate, which selects games already
near first pitch; 36/56 survivors are within 180 min of first pitch; 9
censored events have follow-up windows under 60 min (one is 8.1 min).
Establishes: in 39/56 events, 6 of 11 books had not each moved >=1
de-vigged pp before first pitch. Does not establish: that books are slow
to react. first_move_minutes min 0.0, median 59.4; 2 events had a first
mover inside 15 min, 29/53 inside 60; the 25% rung's minimum is exactly
15.0 (at the floor). 3 events had zero movers, 15 exactly one. Honest
headline: "breadth of repricing is slow/incomplete", not "latency exists".

**C. S(0)=1.000, CI [1,1], p=0.000 — CONFIRMED degenerate; p overstates.**
All 2,000 bootstrap draws are exactly 1.0. The "CI" has zero width by
construction; `p_one_sided` is the only value the procedure could
return, and it is emitted machine-readably with no degeneracy flag.
Defensible alternatives: cluster-level exact sign test, 20/20 clusters
on the H1 side, one-sided p = 0.5^20 = 9.5e-7; rule of three on the
counterexample rate, 0/20 clusters -> 95% upper bound ~0.15.

**D. Clustering — REFUTED (inadequate).**
20 clusters, and only 6 carry any observed reaction; 3 of them carry 12
of the 17. The 17 observations are 6 distinct values repeated within
games. A cluster-level sign test or per-game aggregation is strictly
more defensible. Split-half: 10 vs 11 clusters sharing one (823908),
but the halves are 2026-08-31 (30 events, 13 observed) vs 2026-09-01
(26 events, 4 observed): one calendar day each, not a replication. The
concentration check required by :120-121 was not run: two days, 14
matchups, DET@MIN alone 8 events.

**E. FDR denominator — REFUTED (inconsistent in the same commit set).**
RESEARCH_V3_TIMING.md:238 says 4; timingtest.py:100 says 4; the CLI
prints "4-class family"; RESEARCH_CATALOGUE.md:160 says 4;
RESEARCH_V3_UMPIRE_CLASS.md:117-128 says 5 and timingreport already
emits the fifth class. Adding a class after a read moves the denominator
4->5, the conservative direction, but the amendment must state the
rule: denominator monotone non-decreasing; classes added never removed;
correction applied at read time with the denominator in force at the
last read; a class admitted after a read re-corrects the whole family
including already-read p-values. Naming drift: the amendment registers
`umpire_crew_revealed` (four-person crew), not the home-plate umpire.

**F. Leakage / PIT — CONFIRMED clean; a real selection effect, opposite
direction.** No outcome column is read; game start traces to the
scheduled first pitch; eventstudy truncates every quote series at the
start cap. All events are 2026-08-31/09-01. The "club's next game not
yet played" exclusion (17 events) biases toward SHORTER observed
windows, inflating the censoring rate and depressing KM medians:
conservative for magnitude, but it makes 69.6% a settlement artefact.
The inclusion rule is calendar-dependent: the doc records 166/165; the
identical command on the reviewer's head returned 168/167 because
forward capture appended during the read.

**G. Framing — one false claim, one pseudo-interval.**
RESEARCH_CATALOGUE.md:160 "every observed and lower-bounded diff exceeds
its floor" is false: one censored lower bound is -6.9 min (the addendum
itself discloses it at :275 and hedges with "consistent with").
RESEARCH_V3_TIMING.md:252 "~2.75-3.75 hour median latency" fuses KM
median diff (164.87) and KM median reaction (224.87) into a fake
interval. No edge/exploitability language found; the stale-window block
the CLI prints (30.4%, 59.48 min, 4 observations) is not in the addendum.

## Required before the read is treated as a result

1. Apply the registered "affecting the game" relevance rule (defined
   blind to per-type results) and re-read; publish the all-transactions
   read as secondary with its type mix.
2. Floor = recorded bracket width, not the 180-minute proxy; correct the
   regime line.
3. Primary = KM median(diff) with the clustered interval, not-reached
   draws coded +inf; S(0) demoted; degeneracy flag.
4. Replace p=0.000 with the cluster sign test and rule-of-three bound.
5. Delete the false catalogue sentence.
6. Publish the concentration check and the split-half caveat.
7. Reconcile the denominator (5) everywhere and state the monotone rule.
8. Pin the read: commit hash and store fingerprints.
9. Separate the two KM quantities.

Recommended: define or retract the relevance-estimate field; publish
the countervailing descriptives; state the gate's role in the censoring
rate; replace the test that enshrines p==0.0; per-rung n in the leadlag
ladder; name the umpire mechanism; record the stale-window block.

Correction packet: lane L16 (same day). Second review: required, Opus
tier, before any status doc calls this class "read".

## Second review — 2026-09-02 — PASS

Independent Opus-tier re-review of ADDENDUM 2 (commits 24bf74d + dd2b2c5,
reproduced in the pinned worktree; suite 3,159 tests green there).

Required findings: 1, 2, 3, 4, 5, 7, 8, 9 FIXED; 6 PARTIALLY FIXED (the
concentration check is published and reproduces; the split-half caveat was
missing and is now appended to ADDENDUM 2 as a post-review note).
Recommended 10–16: all FIXED.

Independent checks by the reviewer: all nine store hashes byte-identical;
every ADDENDUM 2 number reproduced by `timing --test` (56/19/37, floors
14.28–17.56 min, 39/56 censored, KM median diff 209.82 with CI [163.8, not
reached] and 445/2000 not-reached draws, sign test 19/0 with one mixed
cluster dropped, p = 1.9e-6, concentration 2 days / 20 clusters / 14
matchups / DET@MIN 8); the old floor logic on the same sample reproduces
ADDENDUM 1's 164.87 exactly; the 42-vs-56 root cause reproduced by
removing the historical transactions store (relevant subset unchanged at
19). Relevance rule judged outcome-blind and a verbatim transcription of
the frozen line-43 list; no single-category relaxation except the
type-less `null` bucket reaches the floor. Denominator consistent at 5
with the monotone rule at all five sites. No new post-hoc choice, no
edge language, no leakage.

Non-blocking items for the next append (not a gate): CLI leading block
still labels the class "at floor" from the unfiltered count
(timingreport.py); a censored row with a negative lower bound is coded
"minus" rather than uninformative in the cluster sign test (conservative
here, could mis-sign later); loose wording at ADDENDUM 2 on which
categories would reach 30; an unconsumed `game_date` field; one
self-contradictory-sounding sentence about the 36/20 regime.

Overall: PASS. The record is a below-floor pre-registered primary (19 of
30; no result read) with a disclosed, never-promoted secondary.
