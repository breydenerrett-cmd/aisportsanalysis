# PREREG: the Hounds breeding program

Registered 2026-10-19, BEFORE any breeding code exists (`src/hounds/breeding/`)
and before any number below has been computed on real data. The owner's ask,
quoted: "every week or every few days pick the best strategies, make babies of
the best strategies, and take the worst ones off or change them." This file is
how that is done without copying luck. A change to any number or rule is a NEW
dated section at the end of this file first, never a quiet edit of the old one.

PAPER ONLY. Every hound makes simulated flat one-unit bets. Nothing here places,
sizes or suggests a real bet, and nothing here claims an edge or a profit. The
-200-or-worse cap is enforced in code on every bet a baby shadows, exactly as on
every other challenger; breeding cannot touch it.

## 0. What breeding is, and what it is not

Breeding CHOOSES WHICH CHALLENGERS GET TESTED. It never promotes, never changes
a running hound's rule, and never edits a recorded result. A baby is an ordinary
challenger of the learning loop (`docs/PREREG_LEARNING_LOOP.md`): it is proposed
through the same door (`proposals.propose_pack`), so every guard of that
prereg's section 3 applies to it; it runs in shadow, forward only, from the
instant it is born; and only the referee (sections 5 to 7 of that prereg) can
make it a champion. Breeding adds a selection rule (who the parents are), a
recombination rule (what the baby's knobs are) and a culling rule (who is taken
off), and nothing else.

The failure it must not repeat: selecting parents on hindsight (a replay of past
boards) copies whatever happened to win in the past, which is mostly luck.
So parents are selected on FORWARD bets only, with a shrinkage that discounts
small samples, and a baby starts at 0-0 and must still win the referee's paired
test against its champion. At 25 bets the fitness ranking is still mostly noise
(section 2); that is acceptable only because the referee, not the ranking,
decides what is promoted.

## 1. Cadence

* A **cycle date** is `2026-10-21` plus a whole multiple of **3** days
  (2026-10-21, 2026-10-24, 2026-10-27, ...). 2026-10-21 is the first cycle date
  after this registration.
* A cycle runs at the **first capture slot at or after 12:00 UTC** on its cycle
  date: `scripts/capture_slot.sh` calls `python -m src.hounds.breeding tick`
  (after the learning loop's tick, capped at 120 seconds, never failing the
  slot) and the tick runs the newest cycle date whose 12:00 UTC has passed, if
  the ledger has no row for it yet. A later slot that day finds the row and does
  nothing. If every slot of a cycle date is missed, the next tick before the
  next cycle date runs it late, under its own date.
* A cycle date that passed with no row and whose successor has also begun is
  recorded as `missed` (one row each, at most 10 per tick) and never run.
* **Seed = the cycle date.** Every random draw of a cycle comes from
  `random.Random("breeding|<cycle date>|<hound id>")`, one stream per family,
  so a cycle re-run on the same inputs produces the same babies, byte for byte.

## 2. Members and fitness (forward only, never hindsight)

**Members.** For each TUNABLE house pack hound H (one that declares `tunable`
knobs in `config/house_pack.json`; eleven today): its current champion version
(id `H`, version n from the learning ledger) and every LIVE pack challenger of H
in the house learning ledger (a coach's or a baby). H with its members is a
**family**. Archived versions, user hounds, engine hounds and every hound
without a knob declaration are not members.

**Settled forward bet.** A bet row with `segment: "forward"` whose graded row
says WIN, LOSS or PUSH (VOID and UNRESOLVED do not count):

* champion H, version n: `evidence/hounds_house_v1.jsonl`, `hound_id` H,
  `hound_version` n (a row without one is version 1);
* challenger c: `evidence/hounds_challengers_v1.jsonl`, `hound_id` c.

All of the version's forward bets count, across seasons (a season is a display
reset; the rule did not change). Rows with `segment: "replay"`, the coach
report card's hindsight and shadow ledgers, and any other replay are NEVER
read by selection or culling.

**Fitness.**

* `n` = settled forward bets; `m` = the number of them with a measured
  closing-line value (`clv_pts` on the graded row, written by
  `src/hounds/pack_settle.py`: 100 x (close consensus fair - break-even of the
  average price)); `clv_mean` = their mean (0 when m = 0).
* **Primary: shrunk CLV** = `clv_mean * m / (m + 50)`. The prior weight of
  50 bets at 0 points is `sigma^2 / tau^2` with a per-bet CLV standard
  deviation of about 3 points and a spread of true hound means of about 0.4
  points (9 / 0.16 = 56, rounded to 50). At m = 25 a mean is cut to a third;
  at m = 150, to three quarters.
* **Tie-break: units per settled bet at the average price** (the
  `units_average_price` of the graded rows, summed, divided by n), higher
  first; then member id, alphabetical. Shrunk CLV is compared rounded to 4
  decimal places.
* **Eligible** = n >= **25**. Only eligible members can be parents or be
  culled.

## 3. Parents and pairing

1. Rank every eligible member of every family by fitness. The **top 4** are
   the parent pool.
2. Knobs differ across hounds, so a baby has parents from ONE family only.
   Families are taken in the order of their best pool member's rank. A family
   with 2 or more members in the pool gives one **pair litter**: its two best
   members (a crossover). A family with exactly 1 member in the pool gives one
   **single-parent litter** (that parent plus a mutation). One litter per
   family per cycle.
3. Cull replacements (section 6) come after the pool's litters.
4. Litters are attempted in that order until the litter cap (section 5) stops
   them.

## 4. The baby's knobs

* **Crossover.** For each knob, in name order, one draw: below 0.5 the knob
  comes from parent A (the better-ranked), else from parent B. Both parents'
  values are on the knob's grid inside its bounds, so the baby's are.
* **Mutation.** One draw: below **0.5** the baby mutates: one knob chosen
  uniformly (name order), moved **one step** up or down (one draw each way);
  a move that would leave `[min, max]` goes the other way instead. A
  single-parent baby ALWAYS mutates, and so does a crossover that came out
  identical to either parent (a copy is not a baby).
* The baby is then proposed through `proposals.propose_pack` with
  `proposed_by: "breeding"`, a code-written hypothesis naming the cycle, the
  parents and where each knob came from, and evidence references to the cycle
  and the parents. Every guard applies, including: the champion version needs
  50 graded forward bets (3.3); one accepted proposal per hound per 7 days
  (3.4); at most 3 live challengers per hound and 30 in the scope (3.5); at
  most 2 knobs different from the champion (2b); no near-duplicate of the
  champion, a live challenger or a challenger retired in the last 90 days
  (3.8).
* **Known consequence, stated before any run.** Rule 3.8 calls two knob sets
  near-duplicates when every knob is within one step. A single-parent baby is
  its parent with one knob moved one step, so it is ALWAYS a near-duplicate of
  its parent, and its parent is the champion or a live challenger. Every
  single-parent baby (and every cull replacement) will therefore be refused
  under 3.8 as long as rule 3.8 and the one-step mutation both stand. The
  refusal is recorded; it is not worked around. Babies that can be born are
  crossovers whose parents differ by more than one step on some knob. Changing
  this (for example a two-step mutation) is an owner decision and would be a
  new dated section here.
* A refusal (any guard) is recorded in the breeding ledger with the guard's
  code and message. The learning ledger records it too, as it records every
  refusal, except the two codes that never reach the guards (coach switched
  off, loop paused).
* The coach switch (`config/hounds_coach.json`) governs the coach, not
  breeding: breeding has its own switch (section 8). The learning loop's
  auto-pause DOES stop births (the proposal door refuses everything while the
  loop is paused).

## 5. Litter size and the live cap

* At most **2** litters attempted per cycle (a refused attempt counts: at most
  2 proposals per cycle, so a cycle can never spam the learning ledger).
* At most **6** live babies in total (live challengers with `proposed_by:
  "breeding"`); at 6, no litter is attempted and the cycle row says so.

## 6. Culling

* Culling runs only when at least **4** members are eligible (so "bottom 2" is
  a judgment relative to others, not the whole field).
* The **bottom 2** eligible members by fitness are culled if, each, n >= **40**
  AND shrunk CLV < **0**. At most 2 culls per cycle.
* **Never culled:** the controls and fun dogs, by id (`coin_flip_collie`,
  `dartboard_dalmatian`, `numerology_newfie`, `lunar_lab`) and by category
  (`random`, `esoteric`, `baseline`). None of them declares knobs today, so none
  is a member; the guard is in code anyway.
* **What a cull does.**
  * A live challenger or baby is RETIRED: a `decision` event (outcome
    `retired`, reason `breeding_cull`) in the house learning ledger, which stops
    its shadow running and blocks a near-duplicate re-proposal for 90 days like
    any lost challenger, plus a lesson row written by code.
  * A champion is NOT retired by breeding: a running hound's rule changes only
    through a promotion, and retirement of a public hound stays with the
    existing rules (-25 units, long negative-CLV runs) and the owner. Instead
    breeding proposes a **replacement**: a mutation (section 4) of the best
    eligible relative in the family other than the culled champion (the
    champion itself if there is none). If the referee later promotes it, the
    champion is replaced as a new version; the old version keeps its record.
  * Every cull is a `cull` row in the breeding ledger with the member's
    numbers and the action taken.

## 7. Honesty

* A baby starts at 0-0: its record is its own challenger-ledger rows, from the
  instant of its proposal forward. Its parents' records are never added to it.
* Selection and culling read forward rows only (section 2). This version
  computes no hindsight at all; if a future page ever shows a baby's replay over
  past boards, it is labelled "rehearsal, not counted" and is read by nothing.
* The family tree shows every baby with its parents, generation, knob values,
  status (from the learning ledger) and record, and every cull, refusal and
  skipped cycle, losers included.
* **Generation.** A champion and a coach's challenger are generation 0; a baby
  is 1 + the larger of its parents' generations.

## 8. The kill switch and the auto-pause

* `config/breeding.json` `{"enabled": true}`. Ships ENABLED, per the owner's
  ask. Off: each cycle date gets one `skipped` row, reason `disabled`, and
  nothing else happens.
* **Auto-pause.** A **birth cycle** is a cycle with at least one accepted
  baby. A baby ends badly when the referee ends it as HURT (outcome
  `retired`, reason `harm`) or TOO EARLY (outcome `undecided`, reason
  `expired`). When the last **3** birth cycles have each ended ALL their babies
  badly, breeding PAUSES: a `pause` row in the breeding ledger with the reason.
  While paused, each cycle date gets one `skipped` row, reason `paused`. Only
  the owner lifts it: `python -m src.hounds.breeding resume --reason "..."`
  (a `resume` row). A baby still live, culled by breeding, superseded or
  promoted does not end badly; a birth cycle with a live baby is not yet
  judged. (In practice this cannot trigger for months: harm needs 100 paired
  slots, expiry 180 days.)

## 9. While nobody is eligible (expected for weeks)

Season 2 began 2026-10-18 and most hounds have fewer than 10 settled forward
bets. Until some member reaches 25, every cycle writes ONE `cycle` row,
outcome `skipped`, reason `no eligible parents: n/25 bets` (n = the most
settled forward bets of any member), and does nothing else: no baby, no cull.
The family tree's eligibility table shows every member's progress toward 25.

## 10. The ledger and the commands

* `evidence/hounds_breeding_v1.jsonl`: hash-chained, append-only. Row kinds:
  `cycle` (one per cycle date: ran / skipped / missed, the reason, the
  eligibility table), `birth`, `birth_refused`, `cull`, `pause`, `resume`.
  No row is ever rewritten or deleted.
* `python -m src.hounds.breeding tick` runs a due cycle. `tick --dry-run`
  computes the due cycle (or, if none is due, the next one) on real data,
  running the proposal guards against a temporary copy of the house learning
  ledgers, and writes nothing anywhere.
* `GET /hounds/breeding` serves the family tree read-only: generations,
  parents, babies with status and record, culls, the next cycle time and the
  eligibility table.

## 11. Not claimed

Breeding does not claim that a baby is better than its parents, that the
parent pool is the best set of rules, or that any hound has an edge. A cycle
that breeds nothing, for months, is working as designed.
