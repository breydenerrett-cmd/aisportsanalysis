# Acknowledged escalations ledger

The scheduled daily loop (`scripts/daily_loop.sh`, `.github/workflows/daily-loop.yml`)
fails its final step whenever `/tmp/daily_run.out` contains a line starting
`ESCALATE:`. That check is not being weakened -- every audit keeps printing
its `ESCALATE:` lines exactly as before, on every run they are true. What
changes is the job's verdict: `scripts/escalations.py --check` reads this
ledger and fails the job only when an `ESCALATE:` line does **not** match a
row below, i.e. only on something nobody has seen and acknowledged yet.

A red job with two known causes on it every single morning is a red job that
carries no information -- the two lines below are why 2026-09-15's job (and
every morning before it) was red, and everyone already knew it. This file is
what turns "known, still true, not news" into "green", without ever hiding
the underlying line: `scripts/escalations.py --check` prints every
`ESCALATE:` line it finds, labelled `KNOWN` or `NEW`, so nothing here is
silent.

## How this ledger works

- **pattern** is a stable substring of the `ESCALATE:` line (not the whole
  line -- exact text like counts and dates changes run to run). A run's
  `ESCALATE:` line is classified `KNOWN` if it contains the `pattern` of any
  row whose `status` is `open` or `fix in progress`; otherwise it is `NEW`
  and fails the job.
- **status**:
  - `open` -- acknowledged, still true, not yet resolvable (see "why it is
    still open" for the blocking condition).
  - `fix in progress` -- acknowledged, actively being wired up; still
    counted as `KNOWN` so the job stays green while the fix lands.
  - `fixed` / `retired` -- no longer expected. A row in this state is
    **not** matched against new `ESCALATE:` lines, so if the underlying
    condition ever recurs it is reported `NEW` again rather than silently
    re-absorbed forever.
- Adding a row here is an acknowledgement, not a fix. It says a human has
  seen this exact escalation, understands why it fires, and is choosing not
  to be paged by it again every morning. It must never be used to quiet an
  escalation nobody has actually looked at.

## Ledger

| id | first_seen | pattern | acknowledged_by | acknowledged_on | status | why it is still open |
|---|---|---|---|---|---|---|
| strong-tier-drift | 2026-09-10 | a constant calibrated against a population has drifted | orchestrator, per Stage 16 R16-06 | 2026-09-15 | open | UPDATED 2026-10-17. The tier ladder (`docs/PREREG_TIER_LADDER.md`) became answerable (22 usable dates) and was READ: it does NOT adopt (`docs/research/TIER_LADDER_RESULT.md`; real family agreement is below the permutation null, and the split halves disagree by 2 families against an allowance of 1). The registered rule therefore leaves the threshold where it is and says nothing about what `slip.EVIDENCE_STRONG` should mean, so this row stays open on a different blocker: an owner choice, `docs/decisions/evidence_strong_tier.md`. `scripts/calibration_drift_audit.py` is still correctly reporting that `slip.EVIDENCE_STRONG` (and the share of published picks graded STRONG, 0.91 against 0.10) is calibrated against the stale 2026-09-08 population; raising the threshold by hand to quiet the audit is exactly the manufactured-confidence move `docs/INCIDENT_2026-09-10_STRONG_TIER.md` forbids. Close this row only when the owner's choice has landed and the drift register entry has been changed to match it. |
| research-readiness-battery | 2026-09-15 | forward-test system(s) now have 30+ graded selections | orchestrator, per Stage 16 R16-06 | 2026-09-15 | fix in progress | wiring landed 2026-09-15 and has written battery verdicts for all 22 systems whose settle-path count reaches the floor (23 are READY by the readiness count). UPDATED 2026-10-17: the one system still named (606be696ff199952) is not a wiring failure. `scripts/research_readiness.py` counts 32 graded selections for it (paper-account settlements); the settle path counts 27 (decision/review pairs settled WIN or LOSS), because five 2026-08-31 launch-day wagers were graded in the paper account and never reviewed, so 27 < `battery.MIN_N` (30) and NOT_RUN is the honest scorecard. The battery was run on the 32 readiness rows (`docs/research/TIER_LADDER_RESULT.md`, part 2): it ran, judged none of its five fatal rules, and is vacuous, so no row was appended to the scorecard chain. The line stops when the system gains 3 more reviewed selections, or when the readiness count is made to use the settle path's join (the second is a deliberate edit to `scripts/research_readiness.py`, not made here). Then mark fixed. |
