# The watchdog: it tells you when a deploy, the tests or the data are stuck

Code: `src/ops/watchdog.py`. Runs inside production (Fly app `linehound-prod`) every 10 minutes. Read-only: it reads
GitHub's public API and the app's own health, writes one small file on the volume, and **cannot cancel, re-run or
deploy anything**. It exists because of 2026-10-03: a deploy hung for six hours and nobody was looking
(`docs/audit/2026-10-03/PROD_DEPLOY_HANG.md`).

## What it watches, and what you do

| It says | When | What you do |
|---|---|---|
| "Deploy to production is stuck (34 min)" | a deploy-prod run in progress or queued more than **25 min** (normal is 6 to 12) | The email has the run link. Open it, click **Cancel workflow**. Claude redeploys. |
| "The test run is stuck" | tests run in progress or queued more than **45 min** (normal about 20) | Same: open the link, **Cancel workflow**, Claude re-runs. |
| "The data-capture run is stuck" | forward-capture run in progress or queued more than **130 min** (normal 65 to 75; two can overlap while one waits) | Same. |
| "The afternoon slate run is stuck" | afternoon-slate run more than **60 min** | Same. |
| "The tests are failing on the working branch" | the newest finished `tests` run failed (it says when it is 2 in a row) | Tell Claude. The email names the failing job and step and links the run; with a `GITHUB_TOKEN` it names the failing test. Production keeps its last good version meanwhile. |
| "Production is 2 h 10 min behind the code" | production runs a commit more than **90 min** older than the branch's newest, **while the tests are green** | Click **Run workflow** on the link, or ask Claude. (If the tests are red, only the red-tests alert fires.) |
| "Data capture has stopped" | no successful forward-capture run in **3 hours** | Open the link; if the newest run is red tell Claude, else click **Run workflow**. |
| the app's own alerts | the freshness checks that already feed `/feeds/alerts.rss` (odds old, a store old, checkout broken...) | Those alerts already email you once a day. The watchdog adds the **all-clear** when one clears. |
| "AI spend is at 85% of its cap" | the paid AI analyst's run is at 80% of `spend_cap` in `config/analyst.json` | Nothing is overspent; the analyst stops itself at 100%. Raise the cap (ask Claude) or let it stop. Skipped while no paid usage store exists (today: none; the session "pilot" costs are estimates, not bills, and are not counted). |
| "The watchdog cannot see GitHub" | every GitHub check failed for 90 min | See *If the watchdog goes blind*. An empty inbox does not mean all is well while this lasts. |

**One email per incident, one more when it clears.** The Zap fires on a new item. A stuck deploy that stays stuck
for three hours is still one email; when it clears you get "Resolved: ..." with an "All clear" sentence. A check that
cannot get its facts (GitHub down) neither raises nor clears anything: it says "unknown" on the admin view.

## Where alerts arrive

The watchdog writes into the same feed your existing **Owner alerts** Zap reads: `https://linehound.app/feeds/alerts.rss`
(Zap 3 in `docs/ZAPS.md`: RSS by Zapier, New Item in Feed, then Email by Zapier with `{{Title}}` and `{{Description}}`).
**No Zap change is needed for email.** Cost: 1 Zapier task per email, so 2 per incident (opened and resolved). Expect
0 to 20 a month.

To look any time (needs your admin token): `curl.exe -s https://linehound.app/admin/watchdog -H "X-Admin-Token: $env:APP_ADMIN_TOKEN"`.
It shows the last check, each check's state, open incidents (live text), the last resolved ones, the commit
production runs and how it knows, and the GitHub request budget. No token or log text is in it.

## Also get a push on your phone

Add one step to the existing Owner alerts Zap. Each alert then costs 2 tasks instead of 1.

**Option A: Discord (best, free, no number to verify).** You already connect Discord for the kennel Zap.
1. Open https://zapier.com/app/zaps and click the **Owner alerts** Zap to open its editor.
2. Under the last step click **+**, search **Discord**, choose the event **Send Channel Message** (or **Send Direct Message** if your Discord connection lists it).
3. Choose your connected Discord account, pick a private channel of your own (create a server just for you if needed).
4. Message: `{{Title}}` then a new line `{{Description}}`. Click **Continue**, then **Test step**.
5. Click **Publish** (top right).
6. On your phone, in the Discord app: tap your profile picture, **Notifications**, turn on push; then long-press that channel, **Notification settings**, **All messages**. Help: https://support.discord.com

**Option B: a text message with SMS by Zapier.**
1. Open the same Zap editor (step 1 above), click **+** under the last step and search **SMS by Zapier**.
2. Event **Send SMS**. Zapier asks you to verify your phone number with a code the first time.
3. Message: `{{Title}}` plus a short `{{Description}}` (texts are short; the email still has everything).
4. **Test step**, then **Publish**.
Zapier's SMS limits and plan rules change; I could not confirm them from here, so check https://zapier.com/apps/sms/integrations before relying on it. Discord has no such limit.

**Option C (zero setup):** turn on notifications for your email app (Gmail: Settings, your account, Notifications, **High priority only**, then star the sender once). The alerts come from your own Zap, so they are easy to mark.

Do not make a new Zap; edit the existing one. A failed push step does not stop the email step above it.

## If the watchdog goes blind (optional GitHub token)

GitHub allows 60 anonymous requests an hour per IP. The watchdog uses 6 every 10 minutes (36 an hour, plus a
restart's refetch) and refuses to spend more than its budget. Fly shares IPs, so another app's traffic can still
use up the limit. A token lifts it to 5,000 and lets the watchdog read test logs.
1. Open https://github.com/settings/personal-access-tokens/new . Name it `linehound-watchdog`, expiration 1 year, **Repository access: Public repositories (read-only)**. Click **Generate token** and copy it. If it will not name failing tests, also give it Repository access **Only select repositories** (`aisportsanalysis`) with the permission **Actions: Read-only**. Without logs the alerts still name the failing job and step and link the run.
2. Give it to Fly through a hidden prompt (nothing is printed or saved in history), PowerShell:

```powershell
$s = Read-Host 'Paste the GitHub token' -AsSecureString
$v = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
fly secrets set -a linehound-prod "GITHUB_TOKEN=$v"; $v = $null
```
The app restarts. `/admin/watchdog` then says `token_present: true`. The token is only ever sent to api.github.com.

## Kill switch

`WATCHDOG = "on"` is in `[env]` of `deploy/fly.production.toml`. Change it to `"off"` (or delete the line) and redeploy: the loop stops and
the watchdog's items leave the feed. Ask Claude to do it. Anything but the word `on` is off.

## How production knows its own commit

The check "production behind" needs the commit the running image was built from. The deploy command passes no
build arguments and workflow files are yours, so the image reads it from the checkout:
`deploy/Dockerfile` copies `.git/HEAD`, `FETCH_HEAD`, `packed-refs` and `refs/` (`.dockerignore` admits exactly those, never `.git/config`,
which holds the checkout's token), `python -m src.ops.watchdog write-version` turns them into `/app/VERSION`, and
the copy is deleted. It cannot fail the build (wildcard copies, `|| echo`). If it cannot name the commit, the
watchdog infers it from the deploy-prod run whose time window contains the app's start and labels it "inferred".
Check which it used: `/admin/watchdog`, `production_commit.source`. **After the first deploy that carries this change, look at that field**: "VERSION file written when the image was built" is the good answer.

## What it cannot do

- It runs inside production. If the machine is down it cannot tell you; Fly's own health check and `scripts/prod_watch.py` cover that.
- It does not prevent a hang. `docs/decisions/deploy-timeout.patch` (a 15 minute `timeout-minutes` on the deploy job) makes a hung deploy end itself; it is a workflow edit, so it is yours to apply.
- Limits are constants at the top of `src/ops/watchdog.py` (`STUCK_MINUTES_BY_WORKFLOW`, `BEHIND_MINUTES`, `CAPTURE_STALL_HOURS`). They come from measured runs; change them there.
