# Production refresh is phase-locked out (found 2026-10-30, 1:30 pm PT run)

**Owner action (workflow YAML, blocked for sessions).** Nothing below is applied.

## What happened

Production (`linehound.app`) has not been refreshed by the automation since 23:14Z on 2026-10-29
(`deploy-prod` run 40971750848, actor `github-actions[bot]`). The two later deploys (03:05Z and
07:33Z on 10-30) were hand dispatches from the owner's account. Since then the site has served the
10-28 MIL at TB sample brief and odds 13 hours old while `/health` stays green.

Cause, read from the working-branch `forward-capture.yml` and the slot logs: the production refresh
step dispatches `deploy-prod.yml` only when `date -u +%M` at the time the step runs is 00 to 14.
In quiet hours the capture chain spaces slots 60 minutes apart, so every slot today started at
minute 17 (16:17Z, 17:17Z, 18:17Z, 19:17Z, 20:17Z) and the step ran at minute 27 to 35, every
hour. Run 41113999946 (19:17Z): `minute 27: not the first slot of the hour -- no production
refresh this run`. Run 41013186155 (06:17Z): `minute 35`. The gate can only pass again when the
chain's phase moves (a game day's 13-minute spacing, or a hand dispatch that lands a slot in
00-14).

## Now

```
gh workflow run deploy-prod.yml --ref claude/sports-betting-analysis-review-g1o0co
```

Then `python scripts/prod_watch.py` after ~8 minutes; the sample brief should read CAR at GB.

## Fix (working-branch `.github/workflows/forward-capture.yml`, production refresh step)

Replace the minute test with "no completed production deploy in the last 50 minutes and none
running", so the refresh does not depend on which minute the chain happens to sit on:

```diff
       - name: Dispatch production data refresh (hourly, CI-green, once prod exists)
         if: always()
         env:
           GH_TOKEN: ${{ github.token }}
           PROD_TOKEN_PRESENT: ${{ secrets.FLY_PROD_API_TOKEN != '' }}
         run: |
           BRANCH="claude/sports-betting-analysis-review-g1o0co"
-          MINUTE=$(date -u +%M)
+          API="https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/workflows/deploy-prod.yml/runs"
+          HDR=(-H "Authorization: Bearer ${GH_TOKEN}" -H "Accept: application/vnd.github+json")
+          # Minutes since the newest completed deploy-prod run (9999 when none or unreadable).
+          SINCE=$(curl -sS "${HDR[@]}" "${API}?status=completed&per_page=1" \
+            | python3 -c "import json,sys,datetime as d; r=json.load(sys.stdin).get('workflow_runs') or []; print(int((d.datetime.now(d.timezone.utc)-d.datetime.fromisoformat(r[0]['updated_at'].replace('Z','+00:00'))).total_seconds()//60) if r else 9999)" || echo 9999)
+          # A deploy already queued or running: dispatching would cancel it (concurrency group).
+          BUSY=$(for s in queued in_progress; do curl -sS "${HDR[@]}" "${API}?status=${s}&per_page=1" \
+            | python3 -c "import json,sys; print(json.load(sys.stdin).get('total_count') or 0)" || echo 1; done | paste -sd+ | bc)
           if [ "$PROD_TOKEN_PRESENT" != "true" ]; then
             echo "FLY_PROD_API_TOKEN not set -- production not live yet, no refresh"
-          elif [ "${MINUTE#0}" -ge 15 ]; then
-            echo "minute ${MINUTE}: not the first slot of the hour -- no production refresh this run"
+          elif [ "${BUSY:-1}" != "0" ]; then
+            echo "a production deploy is queued or running -- no refresh this run"
+          elif [ "${SINCE}" -lt 50 ]; then
+            echo "production refreshed ${SINCE} min ago -- no refresh this run"
           elif ! git log -1 --pretty=%s | grep -q "^Forward capture slot"; then
```

The staging step above it has the same minute test; leave it (staging rebuilds on every push).
`scripts/prod_watch.py` already flags odds older than 3 hours, which is how this was seen.
