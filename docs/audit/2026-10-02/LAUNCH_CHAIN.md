# Launch chain, 2026-10-02: domain, production, tracking, funnel

## 1. Domain (verified 04:59Z)

Canonical address: `https://linehound.app`.

| Check | Result |
|---|---|
| TLS, apex and www | TLS 1.3, Let's Encrypt, each certificate names its own host, valid to 2026-12-31 |
| `http://linehound.app/` | 301 to https |
| `https://linehound.app/` | 307 to `/web/landing.html` (query kept) |
| `https://www.linehound.app/<anything>` | 308 to the same path and query on `linehound.app` (one hop, no loop) |
| Landing, record (`/web/index.html#/record-card`), postseason page | 200 |
| `/health`, `/meta`, `/card/record`, `/card/history`, `/postseason` | 200 |
| `/card`, `/today`, `/props` with no user token | 401 |
| `/admin/overview`, `/admin/users`, `/admin/funnel` with no or a wrong admin token | 401 |
| Phone width (390 px): landing and record page | load, no sideways scroll, product headline and button on the first screen |
| `linehound-prod.fly.dev` | still answers (same app); nothing links to it any more |

Canonical tags, link previews and both outreach batches point at
`linehound.app`.

## 2. Production is on the tested head

| | |
|---|---|
| Latest tested commit (Linux CI green, Python 3.10/3.11/3.12) | `fe9ddaf5` |
| Production | `fe9ddaf5`, deployed 04:56Z by `deploy-prod` run 36966674771 (the existing workflow; its own health and page checks passed) |
| Match | yes |
| Rollback target | Fly release v14 |
| Billing | off. No Stripe secret, no Discord secret, no card-rule change in this release |

Seen once and worth knowing: for the first three or four minutes after a
deploy the landing page can show dashes in the record panel (the first
`/meta` is slow while the caches warm). A reload after that shows the
numbers. Not fixed here.

## 3. Funnel

On the real domain, with the labelled link
`https://linehound.app/web/index.html?utm_source=internal-test&utm_medium=internal&utm_campaign=funnel_test#/record-card`:

| Step | Result on production |
|---|---|
| Visitor lands on the record page | page loads; first touch stored in the browser (`internal-test`); the visit beacon answered 200 |
| Goes to the landing page | first touch unchanged; landing beacon 200 |
| Clicks the hero button | click beacon 200; signup form opens at `/web/index.html#/signup` |
| Signup form opened | beacon 200; one email field, one button |
| Submits the form | NOT done by Claude: creating an account on the live site is the owner's click |
| Admin page shows one lead under that source | needs the admin token: the owner's check |

The same chain run end to end against a temporary database with the same
code (visit twice, landing, click, form, signup, a second signup by the same
email through another lead's link, one real visitor):

- two visits are two page views and no lead;
- one signup is one user and one `account_created`, under `internal-test`;
- the same email arriving again through a different link is the same user,
  and its source stays the first one;
- the admin funnel refuses a request with no token or a wrong one;
- every `internal-test` event sits in its own row under "By source" and is
  left out of the funnel totals (`internal_events_excluded: 6`), while a real
  visitor from `l012-unit-circle` is counted.

The exclusion of `internal` sources from the totals is committed and goes to
production with the tester-access release; until then the row is visible
and the totals include it.

How a site signup becomes a counted lead: the outreach link carries the
lead's id as `utm_source`, so the admin "By source" row is named after the
lead. When that row shows a signup, run
`python scripts/outreach_batch.py signup --lead <id>`. The survival dashboard
counts only rows of `docs/sales/outreach_queue.csv`, one per lead, so page
views, repeat visits and a second link for the same person cannot add a
lead.
