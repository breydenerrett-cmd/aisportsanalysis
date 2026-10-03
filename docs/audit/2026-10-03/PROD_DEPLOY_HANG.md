# Production data frozen for seven hours (2026-10-03)

**What a visitor saw.** The site stayed up and `/health` stayed green, but
everything on it was as of 09:02Z: odds seven hours old by mid-morning
Pacific on a four-game playoff day, and none of the day's card versions
(13:06Z, 15:08Z) were on the site.

**Timeline (UTC).**

| Time | Event |
|---|---|
| 09:02 | Last good hourly deploy (run 37111706924). |
| 10:07 | Hourly deploy 37115351324 starts. `fly deploy` stalls at 10:08:51 while pushing image layers to the registry and never returns. |
| 11:00 to 16:00 | Seven more hourly deploys are dispatched. Each waits behind the stalled one, then is cancelled when the next arrives (one pending slot per concurrency group). |
| 15:55 | `scripts/prod_watch.py` run by hand: "newest odds on the site: 6.9 h old". Traced to the stalled run. |
| 15:56 | Cancelling the stalled run was refused to the assistant (permission). |
| 16:07 | GitHub's six-hour job limit kills the stalled run. |
| 16:08 | The queued deploy runs; production restarts on fresh data. Odds 0.2 h old at 16:11. |

**Cause.** An outside stall (the image push) met two settings in
`deploy-prod.yml`: no `timeout-minutes` on the job, so the limit was GitHub's
default of 360 minutes; and `cancel-in-progress: false`, so nothing behind it
could run.

**Why it went unseen for six hours.** Nothing watches production between
sessions. The watch script was only run when a session resumed, and its odds
alarm had been dismissed earlier as overnight noise. `/health` reports the
process, not the age of what it serves.

**Done.**

- `scripts/prod_watch.py` now reads 20 deploy runs and flags any deploy
  unfinished for more than 20 minutes ("production deploy: a run has been
  unfinished for N min"). It also no longer calls a restart "unexplained"
  when the deploy that caused it sits behind a queue of cancelled runs.
- `docs/decisions/deploy-timeout.patch`: a four-line patch adding
  `timeout-minutes: 15` to the deploy job. Workflow files are the owner's to
  change; `git apply --check` passes against the current file.

**Not done.**

- The patch is not applied.
- Nothing runs the watch on a schedule. Until something does, a repeat is
  bounded at 15 minutes by the timeout (once applied), not by anyone noticing.
- The daily loop fails each run on 2026-10-02, a day with no MLB games:
  "engine settle failed (exit 2)" and "eod self-review refused: no recorded
  decisions". The loop's other work completes; the failure is the off-day
  handling, and it will repeat on every off day in the postseason.
