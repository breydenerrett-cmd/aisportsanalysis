# Go live tomorrow: the exact steps

Owner-run only -- no step here is something an agent session does for you.
Every command below is safe to run from your own machine (or the Fly/
Stripe dashboards in a browser); nothing is pasted to anyone else.
`deploy/DEPLOY_RUNBOOK.md` is the longer staging-first version of this
same plan if you want more context on any step.

## 1. Activate your Stripe account

1. Go to https://dashboard.stripe.com and finish account activation
   (business/individual details, bank account for payouts, ID
   verification). This is the one step only you can do -- Stripe requires
   your own identity, not an API call.
2. Toggle to **Live mode** (top-left switch in the dashboard) once
   activation clears.

## 2. Create the product and price

1. Dashboard -> **Product catalog** -> **+ Add product**.
2. Name: `Linehound (beta)` (working brand -- see `deploy/CLOUDFLARE.md`
   for why it's not final).
3. Pricing model: **Recurring**, **Monthly**, amount **$19.99**.
4. Save, then open the price you just created and copy its id -- it looks
   like `price_1AbCdEfGhIjKlMnO`. You'll set this as `STRIPE_BETA_PRICE_ID`
   in step 4.

## 3. Create the app and its storage (one time)

```bash
fly apps create linehound-prod
fly volumes create app_data_production --app linehound-prod --region iad --size 1
```

Region must be `iad` -- it has to match `primary_region` in
`deploy/fly.production.toml`, already checked in.

## 4. Set secrets (you run this, never paste keys to anyone else)

```bash
fly secrets set \
    STRIPE_API_KEY=sk_live_... \
    STRIPE_BETA_PRICE_ID=price_... \
    APP_ADMIN_TOKEN="$(openssl rand -base64 32)" \
    BILLING_PROVIDER=stripe \
    -a linehound-prod
```

Billing is **four** variables, not two -- `BILLING_PROVIDER` and
`STRIPE_API_KEY` alone still silently waitlist every paying customer
(`deploy/secrets.md`). `STRIPE_BETA_PRICE_ID` is the id you copied in
step 2. `APP_ADMIN_TOKEN` gates `POST /admin/invites` (the Whop fallback
below needs it).

`api/billing.py`'s webhook route reads a signing secret
(`STRIPE_WEBHOOK_SECRET`) -- get its value from step 5 below, then run:

```bash
fly secrets set STRIPE_WEBHOOK_SECRET=whsec_... -a linehound-prod
```

Optional: `STRIPE_TRIAL_DAYS` if you want a trial length other than 7
days (`0` disables the trial and charges immediately):

```bash
fly secrets set STRIPE_TRIAL_DAYS=7 -a linehound-prod
```

## 5. Add the Stripe webhook endpoint

1. Dashboard -> **Developers** -> **Webhooks** -> **+ Add endpoint**.
2. Endpoint URL: `https://linehound.app/billing/webhook`
   (`api/billing.py`'s `POST /billing/webhook` route).
3. Events to send: `checkout.session.completed`,
   `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`.
4. Save, then open the endpoint and copy its **Signing secret**
   (`whsec_...`) -- that's the value for `STRIPE_WEBHOOK_SECRET` in
   step 4 above. Set it, then continue.

## 6. DNS and the cert

Order matters -- deploying before the domain resolves sends Stripe's
checkout redirect nowhere (`deploy/fly.production.toml`'s own comment on
this). Deploy first (step 7), then:

```bash
fly certs add linehound.app -a linehound-prod
```

Then in Cloudflare (the domain's registrar/DNS), add the two records from
`deploy/CLOUDFLARE.md`:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| CNAME | `@` | `linehound-prod.fly.dev` | Proxied (orange cloud) |
| CNAME | `www` | `linehound-prod.fly.dev` | Proxied (orange cloud) |

SSL/TLS mode: **Full (strict)**, not Flexible (`deploy/CLOUDFLARE.md`
explains why Flexible causes a redirect loop against Fly).

## 7. Dispatch the production deploy

`.github/workflows/deploy-prod.yml` is **workflow_dispatch only**. It
never runs automatically on a push. It needs its own repository secret,
**`FLY_PROD_API_TOKEN`**. Do not reuse `FLY_API_TOKEN`: that one belongs to
staging. Create it and set it once (you run these):

```bash
fly tokens create deploy -a linehound-prod
gh secret set FLY_PROD_API_TOKEN --repo breydenerrett-cmd/aisportsanalysis
```

(`gh` prompts for the value, so paste the token there.) Then deploy:

- GitHub UI: Actions tab -> "deploy-prod" -> **Run workflow**.
- Or: `gh workflow run deploy-prod.yml --repo breydenerrett-cmd/aisportsanalysis`

It always deploys the working branch's code (the checkout is pinned),
whichever branch you run it from.

## 8. Smoke test (three lines)

```bash
curl -s https://linehound.app/health | grep -o '"checkout":{[^}]*}'
curl -s -o /dev/null -w '%{http_code}\n' https://linehound.app/today   # expect 401 (paid gate is on)
curl -s -X POST https://linehound.app/signup -H 'content-type: application/json' -d '{"email":"you@example.com"}'
```

Line 1 must say `"status":"ok"`, never `"broken"` -- broken means a
paying customer would be charged and land nowhere. Line 3's response
should carry a `checkout_url` pointing at `checkout.stripe.com` -- open
it and pay with a real card once to confirm the full path (or a Stripe
test card first, in test mode, before flipping to live keys, if you'd
rather rehearse this on staging).

---

## Fallback: if Stripe refuses a betting-picks business

Some payment processors decline sports-analysis/picks products outright.
If Stripe activation is refused or your account gets flagged and
suspended:

1. Create a paid Whop product ($19.99/mo) at https://whop.com -- Whop
   is used by sports-content creators specifically and does not carry
   Stripe's card-network MCC restrictions the same way.
2. For each customer who pays through Whop, mint them access manually:
   `POST /admin/invites` (`api/auth.py`), header
   `X-Admin-Token: <APP_ADMIN_TOKEN>`, body `email=<their email>` -- hand
   them back the one-time token it returns. This bypasses
   `src/appstate/billing.py` entirely (no Stripe involved) and uses the
   same invite-token auth path the private alpha already runs on.
3. This is manual, not automated -- fine at a handful of customers a day;
   revisit if volume makes it a bottleneck.

---

## Note on workflow registration

GitHub only lists a `workflow_dispatch` workflow once its file exists on
the repository's **default branch** (`claude/cowork-session-migration-tn3sx2`).
**Done 2026-09-21** (commit `034d8341`), so no action is needed. If you
change `deploy-prod.yml`, keep both branches' copies identical.
