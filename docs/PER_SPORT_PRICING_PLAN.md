# Per-sport subscriptions and pricing: plan

Status: proposal, 2026-09-15. **Nothing is built.** Written in answer to the
owner ("Every category needs its own sub menu so people can pay for each and
every sport individually ... If the system shows profit of $100 every month on a
$1000 bankroll then that sport per month should be 5-20% of what the expected
profit is"), then corrected after a payments-engineering and consumer-protection
review that checked it against the code. Legal context:
[MANAGED_BETTING_AND_POOL_ASSESSMENT.md](MANAGED_BETTING_AND_POOL_ASSESSMENT.md).

**In one paragraph.** Each sport is its own product with its own sub menu and
its own monthly subscription. A bundle appears once two or more sports are on
sale. Every sport starts at a fixed floor price that covers costs. A sport's
price may rise above the floor only from its own public, timestamped,
self-graded pick record, under a published rule that also lets it fall. Today
every sport sits at its floor, and no page shows profit in dollars.

## 1. What the customer sees

- **Sport menu:** MLB on sale; NFL and TENNIS marked "Coming soon" in red; NBA
  and NHL added later. Data for all of them is already covered by the
  BALLDONTLIE ALL-ACCESS subscription the owner bought on 2026-09-15.
- **Each sport's sub menu:** Gameday, Matchups, Props (where the sport has
  them), Results.
- **A sport you have not bought:** Gameday, Matchups and Props show a locked
  panel with that sport's price, its record summary (with the disclosures in
  section 3) and one Subscribe button.
- **Results are public for every sport**, because the record is the evidence
  behind the price. Research pages (`#/performance`) stay behind login and are
  labelled research, never "Results".
- **Coming-soon sports are free to signed-in members while their record
  builds**, and go on sale only after their picks have been published before
  games and graded publicly. Otherwise nobody receives the picks and no record
  can ever exist.
- **Bundle:** sold only when two or more sports are on sale, never priced below
  the most expensive single sport.

## 2. The pricing rule

**What the owner's rule gives today.** On the MLB record (0 of 8,811 strategies
survived, [EVOLAB_PHASE2B_RESULTS.md](EVOLAB_PHASE2B_RESULTS.md); the published
picks show no positive estimated return under the market benchmark), "5 to 20%
of expected monthly profit" prices MLB at or near zero. NFL and tennis have no
public record. Backtests never count.

**Part A: floor.** A fixed monthly price per sport covering data, hosting,
payment fees and support. Not tied to performance; the price never goes below
it. Suggested: $19.99 (today's beta price).

**Part B: step-up, all conditions required.**
1. **Eligible picks, fixed in config with a start date:** which pick kinds count
   (game picks, props, totals) is written in `plans.py`; changing the set
   resets the window.
2. **Record basis:** only picks published before the game, locked by the
   ledger's per-pick rule, and graded publicly. A public hash of each frozen
   card is posted with a timestamp before the first game, so "published before
   the game" can be checked by anyone.
3. **Reference price:** each pick is graded at the market consensus price at
   publication, not the best of about 11 books the card shows today
   (`src/report/card.py`, "best of 11 books" in `src/appstate/card_ledger.py`),
   so the record reflects what a one-book customer could get.
4. **Measure:** units won per pick at a flat one-unit stake.
5. **Uncertainty:** the lower bound of a one-sided 95% range, computed by a
   block bootstrap by date (picks on the same day and game are correlated,
   props pay far more unevenly than moneylines).
6. **Minimum sample:** 500 eligible graded picks in the last 6 months. Below
   that, the floor.
7. **Persistence:** the lower bound must be above zero in **two quarters in a
   row**, because five sports reviewed four times a year gives many chances for
   a lucky rise.
8. **Size:** step-up = 10% of (lower-bound units per pick x a fixed reference
   volume of 100 picks a month x $10), inside the owner's 5 to 20% range,
   rounded down to whole dollars, capped at 2x the floor. Using a fixed
   reference volume stops more, thinner picks from raising the price.
9. **Schedule and direction:** reviewed on the first business day of January,
   April, July and October. Prices fall as readily as they rise, down to the
   floor. A price drop moves existing subscribers down at renewal; a rise
   applies to new subscribers only.
10. **Grandfathering:** existing subscribers keep their price while their
    subscription stays active. The catch (cancelling loses it) is shown at
    checkout and in cancel emails.

**Worked example, internal only, never for marketing.** Floor $19.99. 600
eligible picks in 6 months with a lower-bound of +0.03 units per pick in two
consecutive quarters. Step-up = 10% x (0.03 x 100 x $10) = $3.00. New
subscribers pay $22.99. If the lower bound falls to zero next quarter, the price
returns to $19.99 at the next review.

## 3. What pages may say

- **Record displays show only:** wins-losses-pushes, units at a flat stake with
  the grading price basis named, sample size, dates, and a range that visibly
  includes values below zero.
- **Never shown:** dollars per month, "expected profit", ROI, bankroll growth,
  "luck-adjusted profit", "verified" (the grading is self-performed: say
  "self-graded, timestamped").
- **Next to any price:** "Price may change quarterly under a published rule
  based on the graded pick record. A higher price does not mean you will
  profit. We do not track subscriber results. Past results do not predict
  future results."
- **At the floor:** "This price covers costs and is not based on performance."
- **Notice:** 30 days' notice before any change that affects a subscriber, and a
  public price-change log. ROSCA and state automatic-renewal laws (California
  amended in 2024) govern the notice timing and content; confirm with counsel.
- **The locked panel** carries all of the above, plus age gating and
  responsible-gambling messaging.

## 4. Build (touches billing and access control: owner go-ahead and `/ultra-review` before merge)

1. **`src/appstate/plans.py` (new, the only price config):** plans `mlb`, `nfl`,
   `tennis`, `nba`, `nhl`, `all`, plus `beta` with `status="legacy"` (not
   sellable; checkout returns 400). Each plan: sports granted, status
   (`on_sale`, `coming_soon`, `legacy`), floor and price, eligible pick set and
   its start date, the env var holding its Stripe price id
   (`STRIPE_PRICE_ID_MLB`, ...), and a list of historical price ids.
   `LEGACY_INVITE_GRANTS` keeps today's invite users (no billing row) on every
   sport they reach today, with an end date and notice. `beta` grants MLB, NFL
   and tennis, because beta payers reach all three today.
2. **Stripe: one subscription per plan.** One plan per Checkout; multi-sport
   buyers use the bundle. Cancel, reactivate, grandfathering and proration then
   stay per subscription, as in today's code. Each Stripe Price carries
   `metadata.plan_id`; Checkout sessions also set `metadata[plan_id]`.
3. **Entitlements table:** rows keyed `(stripe_subscription_id, plan_id)`, with
   user, price id, status and period fields. A webhook event only updates the
   row with its own subscription id, so a late `subscription.deleted` for an
   old subscription cannot revoke a new one. Legacy beta events with no
   metadata map by subscription id or by `STRIPE_BETA_PRICE_ID`. Webhooks write
   to both the new and old tables until the new one is confirmed, so rollback
   does not serve stale access. `users.plan` is frozen as a legacy field; admin
   stats read entitlements.
4. **Access checks, by the sport each route actually serves:**
   - `require_sport("mlb")`, fixed, never reading the query string, on `/today`
     (mounted directly on the app today), `/opportunities`, `/daily`,
     `/daily/{date}`, `/record`, `/odds`, `POST /betcheck`, `/game/...`,
     `/changed/...`, `/props`, and the MLB branch of `/games` and `/card`.
   - Routes that serve several sports declare them; any other `?sport=` gets
     400 before entitlement is checked (`/card`, `/games`, `/live`).
   - `/card/record` and `/card/history` move to a public router with no auth.
     `/performance` stays gated.
   - 402 bodies keep the `error` key the client reads:
     `{"error": "sport_not_in_plan", "message", "sport", "plan_ids", "price_cents"}`,
     and `web/js/dom.js` handles it.
5. **Checkout:** refuse a purchase whose sports are already covered (checked by
   sport, not plan id); offer "switch to bundle" as a subscription price update
   at renewal; send scheduled-cancel users to reactivate. Refund rule: once per
   customer, not once per plan.
6. **`scripts/price_review.py` (new):** reads only eligible graded picks, applies
   Part B, prints a proposed price. It changes nothing; a person edits
   `plans.py` and creates the Stripe Price.
7. **Frontend:** per-sport and bundle cards in `web/js/billing.js`, tiers
   mirrored in `web/js/pricing.js`, the locked panel in each sport's sub menu
   (the redesign in [SITE_REDESIGN_2026-09-15.md](SITE_REDESIGN_2026-09-15.md)
   leaves room for it).

**Charges nothing until the owner creates the Stripe Prices:** unset price env
vars return `not_configured` and the buttons read "Not available yet". The
access checks and public Results take effect on deploy.

**Tests required before merge** (each run against the real app with a temporary
database, each shown failing on the current code first):
1. An invite user with no billing rows keeps every sport they reach today.
2. A beta subscriber keeps MLB, NFL and tennis.
3. An NFL-only subscriber is refused on `/today`, `/opportunities`, `/daily`,
   `/record`, `/odds`, `/betcheck`, `/live?sport=mlb`, `/props?sport=nfl` and
   `/game/...?sport=nfl`.
4. `/card/record` works without auth; `/card` does not.
5. A late `subscription.deleted` for an old subscription does not revoke a new
   one.
6. A legacy beta subscription event with no metadata still updates its row.
7. A bundle bought over an existing single sport is refused or switched, never
   billed twice.
8. The 402 body keeps the `error` key.
9. `deploy/fly.production.toml` never sets `APP_PUBLIC_DEMO` (staging does, so
   the staging link must not be used in marketing).
10. `price_review.py`: backtests excluded, below minimum sample gives the floor,
    a non-positive lower bound gives the floor, one positive quarter is not
    enough, the cap applies, the reference volume is used.

## 5. Decisions for the owner

1. **Floor price per sport** (suggest $19.99).
2. **Bundle price** once two sports are on sale (suggest the most expensive
   single sport plus 50%, never below it).
3. **Step-up rule** as written (6-month window, 500 picks, two quarters, 10%,
   2x cap), or changes.
4. **MLB through the offseason:** the regular season ends in late September.
   Options: pause billing between seasons automatically, or keep MLB free
   through the 2026 postseason and start charging on 2027 Opening Day (beta
   payers then need a pause or a 100% coupon for that stretch).
5. **Public Results** for every sport (recommended yes).
6. **Coming-soon sports free to members while the record builds** (recommended
   yes).
7. **The go-ahead to build section 4**, which changes billing and access
   control.
