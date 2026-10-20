# Resend: verify the domain and send a test email

Code: `src/notify/email.py` (client), `email_jobs.py` (Keep, nightly, Sunday), `api/email_routes.py` (unsubscribe + admin).
Everything is OFF while `RESEND_API_KEY` is unset. It is already set on Fly app `linehound-prod`.

## 1. Verify the domain
1. Open https://resend.com/domains and click `linehound.app`.
2. Status must read **Verified**. If it says Pending, click **Verify DNS Records** (records were auto-added in Cloudflare: https://dash.cloudflare.com , DNS tab for linehound.app). Propagation can take up to an hour.
3. Until it is Verified, Resend rejects sends from `hounds@linehound.app` (the send log records the failure; nothing else breaks).

## 2. Send a test
```
curl -X POST https://linehound.app/admin/email/test \
  -H "X-Admin-Token: $APP_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"to": "you@example.com"}'
curl https://linehound.app/admin/email/status -H "X-Admin-Token: $APP_ADMIN_TOKEN"
```
The status route shows enabled/disabled, the scheduler loop, the last runs and send counts. It never shows the key, full addresses or bodies.

## 3. Settings (Fly secrets / env)
| Name | Default | Purpose |
|---|---|---|
| `RESEND_API_KEY` | unset (off) | Resend key |
| `EMAIL_FROM` | `LINEHOUND <hounds@linehound.app>` | sender |
| `EMAIL_JOBS` | on | `off` stops the nightly/Sunday scheduler |
| `PUBLIC_BASE_URL` | `https://linehound.app` | base for links |
| `EMAIL_SIGNING_SECRET` | auto file `email_signing.key` beside the users db | signs unsubscribe links |

## 4. What sends, and when
- **Keep confirmation**: `POST /auth/signup` with `hound_id` of a dog the new account owns (hook in `api/free_signup.py`); the keep flow may also call `send_keep_confirmation(user, dog)` once a dog is saved.
- **Nightly "{Dog} went W-L"**: about 9:00 AM ET, only for users whose dogs settled bets that day.
- **Sunday pack summary**: 10:00 AM ET.
- Nightly and Sunday respect the per-user unsubscribe flag (signed one-click link in every footer). Idempotent per (user, kind, date); append-only log `email_send_log.jsonl` beside the users db, no bodies.

## Open owner item
- **Physical mailing address**: add `"postal_address": "<street, city, region, zip>"` to `config/business.json`. None is set, so footers currently omit it (never invented). TODO before sending to a wide list.
