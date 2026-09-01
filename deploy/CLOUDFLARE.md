# Cloudflare readiness: execute-later runbook

Working brand: Linehound (temporary, pending trademark/domain clearance --
Brey 2026-09-01). The eventual domain is `linehound.???` -- TBD pending
that clearance. This file does not name, recommend, or suggest purchasing
any specific domain; that stays blocked until clearance completes.

Decision 4 in `docs/LAUNCH_DECISIONS.md` (naming/domain) blocks everything
in this file -- there is no DNS to configure until a domain exists. This
file is the exact, ready-to-run plan for the day both a domain and a
Cloudflare account exist, so that day costs an hour, not a research
session. Nothing here is executable yet; no API call, no account, no
token.

## The exact Brey asks

1. **A domain**, purchased through any registrar Brey chooses (Decision 4
   is naming, not registrar choice -- any registrar works, Cloudflare
   Registrar is convenient only because it skips a second account for
   DNS delegation, not required).
2. **A Cloudflare account** with that domain added as a zone (free tier
   covers everything below -- proxy, universal SSL, basic WAF/rate-limit
   rules, and cache rules are all free-tier features). If Brey would
   rather not hold this personally, delegated access (Cloudflare's
   "invite" flow, scoped to one zone) is enough for this task's own agent
   session to configure it without Brey doing every click by hand -- this
   file works either way.

Until both exist, this file is complete but unusable -- same boundary as
`deploy/STAGING.md`'s Fly token ask.

## 1. DNS records, once the domain + zone exist

Point the domain at whichever Fly app is live (staging first, production
later -- `deploy/DEPLOY_RUNBOOK.md`'s promotion checklist covers when to
add a second record set for production).

| Type | Name | Content | Proxy status |
|------|------|---------|--------------|
| CNAME | `staging` (or `app`, `www` -- Brey's naming call) | `<real-app-name>.fly.dev` | Proxied (orange cloud) |
| CNAME | `api` (if the API gets its own subdomain from a future web frontend) | `<real-app-name>.fly.dev` | Proxied (orange cloud) |

Fly's own docs require a CNAME (not an A record pointing at a fixed IP)
for apps behind Fly's shared proxy, since Fly's edge IPs are not fixed
per-app. `fly certs add <hostname> --app <real-app-name>` is the Fly-side
command to issue a certificate for the custom hostname once the CNAME
resolves -- run after the DNS record exists, not before.

**Proxy ON (orange cloud), not DNS-only (grey cloud):** the point of
Cloudflare here is the WAF/rate-limit/cache layer below, none of which
apply to a DNS-only record. Proxying also gives Cloudflare's own edge TLS
termination in front of Fly's, which is what the SSL mode below governs.

## 2. SSL/TLS mode

**Full (strict)**, not Flexible. Fly already terminates TLS with a valid
cert per `fly certs add` above -- Flexible mode would have Cloudflare talk
to Fly's origin over plain HTTP, which is unnecessary here and is exactly
the misconfiguration Cloudflare's own docs warn causes redirect loops
against origins (like Fly) that already redirect HTTP to HTTPS
(`force_https = true` in both `deploy/fly.staging.toml` and
`deploy/fly.production.toml`). Full (strict) additionally verifies the
origin cert is valid and not self-signed, which Fly's Let's Encrypt cert
satisfies.

## 3. WAF / rate-limit rules that complement, not duplicate, in-process limits

`api/app.py`'s own rate limiting (see its module docstring for the exact
in-process limiter) already protects every route from a single client
hammering it. Cloudflare's rules below are for what the in-process
limiter structurally cannot see or stop:

- **Rate-limit rule, coarse edge-level backstop**: 300 requests / 1 minute
  per IP across the whole zone, action "Block" for 1 minute on breach.
  This is intentionally looser than anything in-process would set for a
  single route -- its job is catching a distributed or scripted flood
  before it reaches the origin at all (an edge-level backstop cannot see
  per-route logic, so it should never be tighter than the loosest
  legitimate use across every route combined).
- **WAF managed ruleset**: enable Cloudflare's free "Cloudflare Managed
  Ruleset" at default sensitivity -- catches generic SQLi/XSS/known-CVE
  probe patterns before they reach uvicorn. This is a backstop, not a
  replacement for anything in `api/`'s own input validation (pydantic
  models already reject malformed request bodies at the framework layer).
- **Bot Fight Mode**: on (free tier). Filters obvious scraper/bot traffic
  at the edge, which is otherwise indistinguishable from legitimate load
  by the time it reaches `api/app.py`'s own rate limiter.

None of these substitute for the in-process limiter -- they exist because
Cloudflare's edge is the only layer that sees traffic BEFORE it costs this
process a socket, a thing no in-process check can do for itself.

## 4. Cache rules

- **`/web/*` (or wherever static frontend assets eventually live) --
  Cacheable, Edge TTL 1 hour, honoring the origin's own `Cache-Control` if
  set.** Static assets (JS/CSS/images) change only on deploy, and caching
  them at Cloudflare's edge is pure latency/bandwidth win with no
  correctness risk.
- **Every API route (`/health`, `/today`, `/games/*`, `/my-bets`,
  `/betcheck`, `/admin/*`, anything under `api/`) -- Bypass cache,
  always.** These responses are per-user (auth-gated, `Authorization:
  Bearer` header) or time-sensitive (live odds, live schedule) --
  caching any of them at a shared edge would either leak one user's
  authenticated response to another or serve stale odds as if they were
  live. This is a hard rule, not a tuning knob: a cache rule that
  accidentally catches an API route is a correctness bug, not a
  performance one.

A concrete rule expression for the bypass, once this is configured in
Cloudflare's dashboard or via Terraform:

```
(http.request.uri.path matches "^/(health|today|games|my-bets|betcheck|admin)")
```
-> Cache eligibility: Bypass cache.

## What this file does NOT cover

- Actually purchasing anything, or creating any account -- Decision 4 and
  the Cloudflare account ask above are both Brey's calls.
- Terraform/API-driven config-as-code for the above (mentioned as an
  option in `docs/LAUNCH_DECISIONS.md`'s "WHAT WE CAN PREPARE WITHOUT ANY
  ACCOUNT TODAY" list) -- writing a working Terraform Cloudflare provider
  config against a zone that does not exist yet would be untestable
  guesswork; the dashboard steps above are exact enough to execute by
  hand in under an hour once the zone exists, which is the higher-value
  deliverable for a one-time setup at this scale.
