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

Sampler: one `/health` read a minute from 21:43:47Z (scratch
`soak/prod_health.jsonl`). Result recorded below when it has run.
