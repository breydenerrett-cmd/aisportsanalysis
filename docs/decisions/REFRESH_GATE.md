# Decision: when production refreshes itself

For Brey. One decision, two lines of workflow change. Written 2026-10-02.

**Corrected 2026-10-03.** Fault 2 below was overstated. It said the hourly
refresh never fires in quiet hours. On 2026-10-03 it fired every hour from
04:05Z to 16:00Z, overnight included, because that night's slots happened
to land inside minute 00 to 14. Whether it fires depends on where the slots
fall against the hour, which drifts from night to night. The freeze is real
but intermittent, not nightly. The larger fault seen since is different and
comes first: one stalled deploy blocked every refresh for six hours
(`docs/audit/2026-10-03/PROD_DEPLOY_HANG.md`); its fix is a one-line job
timeout (`docs/decisions/deploy-timeout.patch`).

## Current behaviour

Production's data is baked into its image, so it only updates when
`deploy-prod` runs. The capture workflow dispatches that deploy when ALL of
these hold: the capture slot finishes in minute 00 to 14 of an hour, the slot
made a capture commit, and the latest COMPLETED test run on the branch is
green.

Two things follow that nobody intended:

1. **It can ship code before its tests finish.** "Latest completed" is the
   run for the previous push while a new push is still being tested, and the
   deploy takes the branch head. A push late in an hour can reach production
   untested. (Not seen to happen; avoided so far by not pushing between
   minute 45 and minute 15.)
2. **It can stop refreshing for many hours.** In quiet hours slots are 60
   minutes apart. When they happen to land outside minute 00 to 14, the test
   fails every hour until the spacing changes. Observed 2026-10-02: last refresh 00:04Z; slots at 01:31Z and
   02:31Z both said "not the first slot of the hour"; at 02:38Z production
   was still serving the 23:51Z odds and did not have the 00:16Z push (the
   UFC grading), although CI was green.

## Proposed change

In `.github/workflows/forward-capture.yml`, step "Dispatch production data
refresh":

- Replace "minute 00 to 14" with "the last successful `deploy-prod` run
  started 55 or more minutes ago" (one API call, the same kind the step
  already makes).
- Before dispatching, also require that no `tests` run on the branch is
  queued or in progress.

Nothing else changes: still at most one refresh an hour, still only on a
green suite, still the same `deploy-prod` workflow with its own health and
page checks.

## Why

Production should show data at most about an hour old whenever captures are
running, and should never run code no suite has passed.

## Risk

Low. The step can only dispatch a workflow that already exists and already
runs hourly. Worst case of a mistake in the new condition: a refresh is
skipped (what happens today) or fires on consecutive slots (bounded by
`deploy-prod`'s single-run lock; costs a restart).

## Benefit

Fresh odds and cards on production through the evening, which is when people
look; pushes can be made at any minute without a rule to remember.

## Cost

No money. About ten lines of YAML. One evening of watching the first few
refreshes.

## Rollback

Revert the one commit. The old condition returns on the next slot.

## If we do nothing

Production freezes on the nights the slots land outside minute 00 to 14
(seen 2026-10-02; not seen 2026-10-03), and every push needs the
minute-45-to-15 rule to stay safe.

## Recommendation

**Do it.** It is free, reversible, changes no betting rule, and both faults
are observed, not theoretical. I am not permitted to edit workflow files, so
this needs either your edit or your explicit go-ahead for me to make it.

Order of work: the job timeout first (one line, protects against a six-hour
freeze that has happened), this change second.
