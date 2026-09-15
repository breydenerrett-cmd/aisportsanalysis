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
| strong-tier-drift | 2026-09-10 | a constant calibrated against a population has drifted | orchestrator, per Stage 16 R16-06 | 2026-09-15 | open | The tier ladder (`docs/PREREG_TIER_LADDER.md`) is the fix, and it is a pre-registered recalibration that refuses to run until it has 20 usable dates -- it currently has 5. `scripts/calibration_drift_audit.py` is correctly reporting that `slip.EVIDENCE_STRONG` (and the share of published picks graded STRONG) is still calibrated against the stale 2026-09-08 population until that pre-registration is answerable; raising the threshold by hand to quiet the audit is exactly the manufactured-confidence move `docs/INCIDENT_2026-09-10_STRONG_TIER.md` forbids. |
| research-readiness-battery | 2026-09-15 | forward-test system(s) now have 30+ graded selections | orchestrator, per Stage 16 R16-06 | 2026-09-15 | fix in progress | wiring landed 2026-09-15; the line stops on the first daily settle that writes battery verdicts; then mark fixed. |
