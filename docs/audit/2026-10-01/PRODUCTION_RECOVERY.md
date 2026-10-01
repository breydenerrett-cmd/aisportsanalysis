# Production recovery, 2026-10-01

Controlled recovery authorised by the owner: cancel the stuck production
deploy once the current Linux CI run is green, let one clean deploy proceed,
then soak for 45 to 60 minutes.

## Before cancelling (recorded 21:20Z to 21:35Z)

1. **Stuck run.** `deploy-prod` run `36905290084`, dispatched 18:13:57Z on
   `64c39a91`, in its "Deploy" step ever since.
2. **What deploys next.** `deploy-prod.yml` checks out the working-branch
   head at run time. Code revision `bd22b433`; anything after it on the
   branch is a runner data commit. The waiting run is `36919667679`.
3. **The release contains** (each an ancestor of `bd22b433`): postseason
   page `e5568bdf`, buying path `1c1a9a60`, one-build-at-a-time memory fix
   `407a9a7e`, Linux CI fix `c025c181`, `/meta` cache `36db1fe6`, NFL
   game-day refresh `8aa3b070`, record split `f18517db`, `/health` runtime
   figures `bd22b433`.
4. **It does not activate:**
   - production billing: `fly secrets list -a linehound-prod` returns no
     secrets at all (no `BILLING_PROVIDER`, no `STRIPE_*`), and production
     `/health` reports `checkout: off`;
   - the Discord feed: the repository has no `DISCORD_WEBHOOK_URL` or
     `DISCORD_WEBHOOK_URLS` secret (names listed: `API_TENNIS_KEY`,
     `BALLDONTLIE_API_KEY`, `FLY_API_TOKEN`, `FLY_PROD_API_TOKEN`,
     `ODDS_API_KEY`);
   - any card rule: `git diff 6769e84e bd22b433` over the fingerprinted and
     rule files (strength, playerprops, propboard, report/props, daily_card,
     report/card, card_ledger, card_calibration.json, best_bets_card,
     card_v2, nfl_value, nfl_card, ufc_card, mlb_value_shadow) is empty, and
     `ACTIVE_CARD_RULE` is "v2" at both.
5. **Staging on the same code.** `deploy-staging` run `36927619729` for
   `bd22b433`: success. Staging `/health` at 21:24Z: status ok, started
   21:18:32Z, peak RSS 573.5 MB, RSS 247.8 MB, builds max_running 1 of 16.
   Staging could not be soaked past eleven minutes: it now stops when idle
   (Fly log 21:29:00Z "excess capacity, autostopping"), which is the cost
   setting from this morning, not a fault.
6. **CI on the release.** `tests` run `36927619866` for `bd22b433`: see
   "Timeline".
7. **Rollback target.** Production runs release v11, image
   `registry.fly.io/linehound-prod:deployment-01M3WA8SSQHGSPTSZXHN9SJAVE`,
   digest `sha256:1f472772fa614b41378c9fd5bce062639c582a8bacf2d8cc0d4c4b4c69e03ac9`,
   built from `6769e84e` (deploy-prod run `36904146753`, 18:04:49Z).

## Timeline

- 21:38:26Z `tests` run `36927619866` on `bd22b433`: success on Python 3.10,
  3.11 and 3.12. All seven checks true. Branch tip `ac5ee3a9` = `bd22b433`
  plus one runner data commit ("Forward capture slot 21:19Z"), no code.
- 21:38:42Z cancel requested for run `36905290084` only. It ended
  "cancelled" at 21:39:53Z. No capture or data workflow was touched.
- 21:39:58Z the one waiting run, `36919667679`, started. Checkout
  21:39:59Z, Deploy 21:40:16Z to 21:41:15Z, its own health check
  21:41:15Z to 21:43:01Z, success. Fly release v12, image tag
  `deployment-01M3WPJDWYRW6W7QN182RF04W5`. (The image label reads
  `GH_SHA=62069baf`: that is the SHA the run was dispatched on. The job
  checks out the branch head, and the deployed `/health` carries the
  `runtime` block that only exists from `bd22b433` on.)
- 21:41:05Z production process started.

## Acceptance at 21:44Z to 21:47Z (browser, linehound-prod.fly.dev)

- `/health`: ok. started 21:41:05Z; first warm-up pass finished 21:41:49Z;
  RSS 234.6 MB, peak 572.5 MB; builds max_running 1 (15 total).
- `/meta`: first request 1,845 ms, repeat 113 ms. Billing `checkout: off`
  (null provider; production has no secrets set at all).
- Public, 200: `/card/record`, `/card/history`, `/postseason`, landing,
  signup, record page, postseason page.
- Protected, 401 without a token: `/card`, `/card/{date}`, `/today`,
  `/games/{date}`, `/odds/{date}`, `/props/{date}`, `/billing/status`.
  `/admin/*`: 404 (no admin token is configured in production).
- Landing: all four buttons read "Get notified when checkout opens"; "free
  trial" appears nowhere; record 16-17, -5.05 units, 6 nights, 2026-09-22
  to 2026-09-27. Signup: "Checkout is not open yet." / "Save my email".
- Postseason page: available; scores through Sept 30; standings 2026-09-27
  (fetched, because production's stored standings end 09-08); pitcher logs
  on file end Sept 7 and bullpen Sept 6, both stated at the top; 1 game
  CONFIRMED_CURRENT (PHI at ATL, starters through Sept 25, from logs fetched
  at build time), 11 PROJECTED_CURRENT (slot shows TBD, labelled scenario),
  4 STALE_REFERENCE_ONLY, 0 UNAVAILABLE. No silent use of the old stores:
  every stale input is named with its date and left out of the number.

## Soak


One read of production `/health` a minute at first, then every few minutes
(25 reads from 21:43:47Z to 22:26:50Z, every one HTTP 200). The figures
are cumulative since the process started, so a restart between reads would
show as a new `started_utc`, a smaller `uptime_s` and a reset pass count.

| Read at (Z) | Uptime | Warm-up passes done | RSS MB | Peak RSS MB | Cache builds | Most builds at once |
|---|---|---|---|---|---|---|
| 21:43:47 | 2 min 38 s | 1 | 234.6 | 572.5 | 15 | 1 |
| 21:52:47 | 11 min 37 s | 2 | 292.4 | 576.5 | 31 | 1 |
| 22:04:00 | 22 min 50 s | 3 | 317.6 | 588.6 | 46 | 1 |
| 22:15:35 | 34 min 25 s | 4 | 340.0 | 588.6 | 61 | 1 |
| 22:23:33 | 42 min 24 s | 5 | 344.0 | 588.6 | 73 | 1 |
| 22:26:50 | 45 min 41 s | 5 | 347.0 | 588.6 | 76 | 1 |
| 22:31:16 | 50 min 07 s | 5 | 347.0 | 588.6 | 76 | 1 |
| 22:38:57 | 57 min 48 s | 6 | 359.0 | 588.6 | 91 | 1 |
| 22:41:36 | 60 min 27 s | 6 | 358.0 | 588.6 | 91 | 1 |

- **60-minute result (22:41:36Z):** same process (`started_utc` 21:41:05Z), uptime 3,627 s, restart count 0, six refresh cycles, 91 cache builds, never more than one at a time. Peak 588.6 MB, unchanged since the third cycle. Resident memory between cycles: 347.0 -> 359.0 -> 358.0 MB, so the rise has slowed to about 12 MB over the last two cycles; it is flattening, not yet flat.
- **Uptime:** one process, started 21:41:05Z, never restarted in 60 minutes (the old build was killed at 658 s and 666 s). Restart count 0. Fly machine version 12, last updated 21:41:03Z, health check passing; the last 100 log lines (22:05Z to 22:26Z) contain no "Out of memory", SIGKILL or restart line.
- **Old failure point passed:** the second warm-up pass, the one that killed the old build, completed at about 697 s of uptime with the builds still one at a time.
- **Memory:** 234.6 MB after the first pass; peak during the first pass 572.5 MB, during later passes 588.6 MB (machine: 1,024 MB). Between passes it sits at 292.4 to 347.0 MB.
- **Not a clean plateau:** resident memory between passes has risen with each cycle (234.6 -> 292.4 -> 317.6 -> 340.0 -> 344.0 -> 347.0 MB), about 20 MB a cycle at first and less in the last two. The peak has not moved since the third pass. At this rate it is hours from the limit, and the hourly refresh restarts the process anyway, but a level-off has not been shown yet.
- **Serialised:** `builds.max_running` is 1 after 76 cache builds.
- **Verdict:** the memory incident is production-verified for the 60-minute soak the owner preferred (45 was the minimum): no restart, no memory kill, six refresh cycles completed. The slow rise between passes is left open and is watched on `/health`.


## Credit change: not confirmed

`credit_efficiency_2026-10-01T2217Z.txt`. From 18:42Z (done markers
committed) to 22:17Z, 3.6 hours:

- Spend: 24 credits, 6.7 an hour, against 23.6 an hour before. NFL 12, prop
  listing 9, MMA 1, prop prices 1, batter props 1.
- NFL captures: four, at 19:06, 20:05, 21:19 and 22:16Z, each a scheduled
  phase (t72h, t24h, t6h or t2h for some game), about 820 rows each. The
  25-minute game-day refresh shipped at 19:43Z has NOT fired once: every
  slot that ran either found a phase due or came less than 25 minutes after
  one.
- NFL card freshness (a kickoff within 6 hours and the board under 60
  minutes old): 202 of 215 minutes, 94%. The 13 stale minutes fall between
  the 20:05Z and 21:19Z captures.
- That gap is not the cadence rule. Capture slots themselves stopped
  completing: a single slot ran 44 minutes (20:55Z to 21:39Z) because
  "engine slate" took 19 minutes, twice, and the capture job shares one lock
  with the afternoon-slate job, which takes about 20 minutes of every 30.
  Slots completed about 4.5 an hour before 19:06Z and about 1 an hour after.
  So part of the lower spend is simply fewer slots, which is a loss, not a
  saving. MLB capture instants: 3 in 3.6 hours.
- MMA: 85 captures before, 1 after. No UFC card was due today; whether a
  fight-week card needs more than the phase captures is not measured.
- Verdict: keep the change (the every-slot re-buy was 80% of spend and
  bought the same board again), but do not count the saving until the
  refresh has fired on a game day with slots completing normally. Sunday is
  the test. The slow engine slate is being profiled separately.
