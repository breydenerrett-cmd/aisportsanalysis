# Password reset

Members can reset their own password. Sign-in page, "Forgot your password?", under the Sign in button.

## What happens
1. They type their email. The page always says: "If that email has an account, a reset link is on its way." It never says whether the account exists.
2. If the account exists, the server makes a one-time link that works for 30 minutes (only a hash is stored).
3. They open the link (`/web/#/reset?token=...`), pick a new password (same rules as sign-up), and are signed in. Their other sessions, access codes included, stop working. A comp or tester keeps their access, under a new session.
4. Limits: 3 requests per hour per email, 10 per hour per IP.

An account with no password (a comp or tester you added) uses the same link to set its first one.

## Which path is live
- Email is sent only if `RESEND_API_KEY` is set on the Fly app (`docs/owner/RESEND_ATTACH.md`) and `linehound.app` is verified in Resend. The docs say the key is set on `linehound-prod`; check with `GET /admin/email/status` (shows enabled or disabled) and send a test via `POST /admin/email/test`. Until the domain shows Verified, Resend refuses the send and the log says "failed".
- If email is not configured or fails, the server logs one safe line (masked address, no token): "password reset requested for x***@g***.com but no email provider is configured". Nothing reaches the member, so use the fallback.

## Fallback: send the link yourself
Admin -> People -> the person's Actions -> **Send password reset link**. Enter a reason, press Make reset link. The link shows once (copy it, text it). Same 30 minutes, same single use. It is audited (reason, hashed user, never the link).

## Why a comp can fail to sign in
Adding someone as a free member (Give free access, or a login code) never sets a password. Email + password sign-in then says "That email and password do not match", the same message as a wrong password or an unknown email, on purpose. Fix: they use Forgot your password, or you send the reset link. If you used "Give free access" for an email that had no account yet, there is no account to reset: they must create the free account first (the free access attaches on sign-up).
