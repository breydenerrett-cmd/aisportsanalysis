# Security handoff to LINEHOUND Launch Ops (2026-09-01)

A defensive secure-code review of the commerce/auth surface ran before the
first live Stripe TEST checkout. Two code defects were found and fixed in this
repo (activation-token one-time retrieval made atomic; webhook verifier now
fails closed on an out-of-range timestamp instead of raising a 500) with
regression tests; the fixes land on the launch branch and will reach staging
on the next deploy. The items below are **configuration checks only Launch Ops
can perform** — they are not code changes.

## Config checks before / during the dry-run purchase

1. **Webhook secret must match this deploy.** `STRIPE_WEBHOOK_SECRET` has to be
   the signing secret of the exact dashboard endpoint pointed at
   `https://linehound-staging.fly.dev/billing/webhook`. While it is unset the
   route returns 501 and webhooks are silently inert, so `GET /billing/status`
   never advances past what `POST /billing/cancel` writes. Verify: send a test
   event, confirm a `{"received": true}` 200, then confirm the
   `billing_subscriptions` row updated.

2. **Rate-limiter behind the Fly proxy.** The container runs uvicorn WITHOUT
   `--proxy-headers`, so the limiter keys on the Fly edge peer, not the
   visitor. Two failure modes to check in staging: if all visitors collapse to
   one proxy IP, the signup (10/hr) and funnel (60/hr) limits become a single
   shared global bucket that over-limits real users. Do **not** fix this by
   adding `--proxy-headers --forwarded-allow-ips="*"` — that makes
   `X-Forwarded-For` client-settable and turns the IP limit into a no-op. The
   correct setting is `--proxy-headers` scoped to Fly's proxy CIDR only.

3. **Single process only.** The limiter is a per-process dict; more than one
   worker multiplies the effective limits by the worker count. Keep staging
   single-process (it already is, per the sqlite single-writer constraint) or
   move the limiter to a shared store before relying on the numbers.

4. **Fake transport must be off.** `STRIPE_FAKE_TRANSPORT` must be unset and
   the key must not start with `sk_test_synthetic` in staging/live. The fake is
   guarded, but the tripwire is a loud stderr banner — grep staging logs to
   confirm "STRIPE FAKE TRANSPORT ACTIVE" never prints.

## Watch during the first live checkout

- **Public `POST /signup` returns 500 on a real Stripe error** (e.g. a wrong
  `STRIPE_BETA_PRICE_ID`, a transient Stripe 5xx, or a customer-create
  failure). This fails closed — no user is activated and nothing leaks — but it
  is a poor first-run experience. It is deliberately NOT swallowed into
  "waitlisted" so a genuine misconfig stays visible. Watch signup 5xx during
  the first checkout; if it fires, the cause is almost always the price id or
  the key, not the code.

## Already verified sound (no action needed)

Webhook forgery (no/blank/wrong signature → 400; unset secret → 501; 5-minute
timestamp tolerance; constant-time compare; unknown customer/session mutates
nothing); activation tokens minted only inside the signature-verified
`checkout.session.completed` path and indistinguishable 404s across
unknown/unpaid/used; `POST /signup` can only write `pending_payment`/
`waitlisted` (active is reachable only via a signed webhook); the funnel public
endpoint refuses any kind outside `{landing_view, signup_started}`; the API key
appears only in the outbound `Authorization` header to Stripe, never in a
response, log line, or exception; rate-limit keys cannot be set by a request
header.


## UPDATE 2026-09-01 04:2x — all review findings fixed in code

Every finding is now fixed on the launch branch (commits b03064f, 6489bfa)
and green; they reach staging on the next deploy. **F1 was BLOCKING for
`BILLING_PROVIDER=stripe`: `/billing/checkout` had let the client name its own
Stripe price — now locked to the server-side beta price (400 otherwise).
Confirm staging is on a build at or after commit 6489bfa before enabling the
Stripe provider.** Also fixed: checkout/signup/cancel return a structured
error (not a 500 or a raw Stripe body) on a live Stripe failure; checkout and
cancel are rate-limited 20/min/user; the funnel event `properties` field is
capped at 2 KB; stale unretrieved activation tokens are scrubbed past the token
TTL. The config checks earlier in this doc still stand.
