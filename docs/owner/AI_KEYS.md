# AI hounds: one key, one spend limit, one switch

Code: `src/ai/router.py` (the model layer and the $ cap), `src/hounds/ai_runner.py` (the schedule),
`api/ai.py` (the status panel). Rules: `docs/PREREG_AI_HOUNDS.md`. Everything is OFF until `AI_HOUNDS=on`.

**Decision 2026-10-20:** Claude Haiku 5.5 is the one model. It is cheap (about $0.0002 a call, so a 15-game day is
a few tenths of a cent), and the code stops it at **$5 a month** whatever else happens. The free-tier models
(Gemini, Groq, OpenRouter) and a local Ollama are parked: not built, and listed nowhere. The router is ready for
a second model later (a config entry and one adapter), and the Council Hound is written but parked until then.

## 1. Get the key (once; it is already set on `linehound-prod`)
1. Open https://console.anthropic.com/settings/keys and click **Create Key**.
2. Name it `linehound-prod`, create it, and copy it now (it is shown once).
3. Put it on Fly without it ever being typed on screen or saved in history. Run this in PowerShell, paste the key at
   the hidden prompt, press Enter:
```powershell
$k=Read-Host "ANTHROPIC_API_KEY" -AsSecureString; fly secrets set -a linehound-prod "ANTHROPIC_API_KEY=$([Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($k)))"
```
Fly restarts the app when a secret changes. Never put the key in a file, a chat, `fly.production.toml` or the repo.

## 2. Set the $5 monthly spend limit in the Anthropic console (the second wall)
The code cap is the first wall; this one is Anthropic's own, so a bug in our code still cannot spend more.
1. Open https://console.anthropic.com/settings/limits.
2. In the **spend limit** section set the monthly limit to **$5** and save. If the page offers a notification
   threshold, set it to $4.
3. Check the org is the one that owns the key above (the org name is top left of the console).

If that limit is reached, Anthropic answers our calls with a usage-limit error; the router treats it as "resting"
for six hours and the hounds pass. Raising the limit later is the same page.

## 3. Turn the hounds on (after the deploy that contains this change)
The change adds the `anthropic` package to `api/requirements.txt`; the image has to be rebuilt with it first
(the hourly deploy does that when CI is green). Then, in PowerShell:
```powershell
fly secrets set -a linehound-prod "AI_HOUNDS=on"
```
`AI_HOUNDS` and `AI_PAID_CAP_USD` are not secrets, but `fly secrets set` is the one way to flip them without a
deploy. Turn them off the same way: `fly secrets set -a linehound-prod "AI_HOUNDS=off"` (or `fly secrets unset
-a linehound-prod AI_HOUNDS`). The loop reads the switch at boot, so the restart Fly does is the switch.

## 4. Check it
```
curl https://linehound.app/admin/ai/status -H "X-Admin-Token: $APP_ADMIN_TOKEN"
```
(`APP_ADMIN_TOKEN` is your existing admin token.) It shows:
* `switch`: whether `AI_HOUNDS` is on;
* `router.providers`: Haiku, whether it is enabled (`disabled_reason` says why not: no key, switched off, cap 0),
  `usable_now`, calls today against its daily cap of 400, and any cooldown;
* `router.paid`: this month's spend, the cap (5), what is left, and `cap_reached`;
* `router.last_errors`: the last ten failed calls (never a key);
* `runner`: the last pass and its counts, and `ledger`: AI bets and grades so far and today's decisions by
  reason (`model_bet`, `model_pass`, `outside_band`, `no_answer`...).

Refreshing it calls no model and costs nothing. The Claude Hound shows on https://linehound.app/hounds in the
**AI** category once it has a bet; until then it reads "not started".

## 5. When the model is capped or down
The hounds **pass** (each game that locks gets one logged decision with the reason, and is never asked again),
`degraded` reads true in the panel, and nothing is guessed or back-filled. Ask calls no model, so it keeps
answering from each dog's own data; the line for a place that wants one is "My AI brain is resting, here's what
my rules say." A content job that wants the batch API (half price, for recaps and hype lines) gets
"not submitted" back from the router when it is capped or cooling down, and waits for its next scheduled run;
`Router.submit_batch` and `collect_batch` are in place, but no content job calls them yet.

## 6. Settings
| Name | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset (off) | the Claude key; without it the router has no provider |
| `AI_PAID_CAP_USD` | `5` | hard monthly cap in dollars, checked before every paid call; `0` turns paid calls off |
| `AI_HOUNDS` | off | `on` starts the 15-minute loop; anything else starts nothing |
| `AI_HOUNDS_INTERVAL_SECONDS` | `900` | time between passes (floor 60) |
| `AI_USAGE_PATH`, `AI_HOUNDS_LEDGER`, `AI_HOUNDS_DECISIONS` | beside the app database | the usage meter, the AI bets, the decision log (all on the Fly volume, so they survive deploys) |

`config/ai_providers.json` holds the model id (`claude-haiku-5-5`), effort (`low`), prices ($0.10 and $0.50 per
million tokens), the daily call cap and the cooldown minutes. `config/ai_hounds.json` holds the hounds. Both are
read at boot.

## 7. What is parked, and how to add a model later
Not built: Gemini Flash, Groq, OpenRouter free models, a local Ollama. To add one: write an adapter class for its
API in `src/ai/router.py` and register it in `ADAPTER_KINDS`, add a provider entry (with `"enabled": true` and its
env key) to `config/ai_providers.json` and put its id in `order`, then add a hound entry that names it in
`providers`. Free keys would be a separate short doc then. The Council Hound turns on by setting its `enabled`
flag in `config/ai_hounds.json` once at least three model hounds exist.
