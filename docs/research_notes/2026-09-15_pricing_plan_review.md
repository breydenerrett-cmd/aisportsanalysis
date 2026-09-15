# Review: per-sport pricing plan (2026-09-15 proposal)

**Verdict: don't build this as written.** The Stripe mechanics conflict with each other. The access design locks out the current alpha users and leaks MLB content to NFL-only and Tennis-only subscribers. The customer-facing record display amounts to an earnings claim. I checked the plan against the code under `C:\Users\KC\Desktop\aisportsanalysis`. Items marked [code] are confirmed there. Items marked [unverified] still need a source or counsel.

## A. Steps that don't match the code

**A1. `/today` is left out and would leak MLB (HIGH, [code]).**
- **Quote:** "The games, card, props and performance routers use `require_sport_access`."
- **Why:** `/today` is not in any router. It is mounted on the app directly with `dependencies=_authed_paid` (`api/app.py:256`) and serves `mlb.fetch_games`. The code map missed it too. Under the plan it keeps the "any active plan" gate, so an NFL-only subscriber gets the MLB Gameday slate.
- **Fix:** Gate `/today` with a fixed MLB check, and add it to the access-gate tests.

**A2. The "no sport" pages are MLB content, so "any active plan" leaks (HIGH, [code]).**
- **Quote:** "`require_paid_access` (any active plan) stays for pages with no sport: Bet Check, daily, odds, opportunities and live."
- **Why:**
  - `/opportunities` is built from `api.games._build_entries`, which is MLB.
  - `/daily`, `/daily/{date}` and `/record` are the MLB frozen pregame record.
  - `/odds` and `POST /betcheck` have no sport parameter and are MLB.
  - `/live` does take a sport: `sport: str = "mlb"`, checked against `("mlb","nfl")` at `api/live.py:126,165`. It is not sport-less.
  - Result: a Tennis-only buyer gets MLB Top Opportunities, the daily picks, odds, Bet Check and live MLB/NFL.
- **Fix:** No route should use "any active plan" if it serves one sport's content. Use a fixed-sport check (`require_sport("mlb")`) on opportunities, daily, record, odds, betcheck and today. Use the per-request sport check on `/live`.

**A3. The gate can be fooled with `?sport=` on routes that ignore it (HIGH, [code]).**
- **Quote:** "validates the `sport` query param (default `mlb`)", plus "Add a validated `sport: str = "mlb"`" to props and performance.
- **Why:** `/game/{date}/{away}/{home}` and `/changed/{date}` in the games router take no sport and always serve MLB (`api/games.py:406-450`). A router-level check that reads `?sport=` would let an NFL-only user call `/game/...?sport=nfl`: the check passes and MLB comes back. The same happens on `/props?sport=nfl` and `/performance?sport=nfl` after step 5, unless those endpoints actually branch on sport. Validating against `src.sports.keys()` accepts nfl and tennis for routes that only have MLB data.
- **Fix:** Each route declares the sports it serves. The check rejects any other sport with 400 before it looks at entitlement. Routes that only serve MLB use a fixed `require_sport("mlb")` and never read the query string. Add a test that an NFL-only user on `/props?sport=nfl` and `/game/...?sport=nfl` does not get MLB data.

**A4. "Results stay open" has no build step, and step 4 closes it (HIGH, [code]).**
- **Quote:** "Results stay open to everyone"
- **Why:** The RESULTS nav entry is `#/record-card`, which calls `GET /card/record` and `/card/history` (`web/js/main.js:95-114`). Both live in `card_router`, which step 4 gates per sport. In production they are behind login and payment today, so "stay open" is false.
- **Other things to handle:**
  - `#/performance` is the research surface of "forward-test detector systems' paper standings" (main.js:93-104). It must not become public "Results", or be read by the price rule. Step 5 adds a sport parameter there as if it were Results.
  - `web/js/signup.js:54` already says "the record is checkable". That is untrue for people who haven't paid while Results is gated.
- **Fix:** Move `/card/record` and `/card/history` to a new public router with no auth. Keep `/card` and `/card/{date}` gated. Keep `/performance` gated and label it research.

**A5. `FREE_SPORTS` locks out today's invite users (HIGH, [code]).**
- **Quote:** "`FREE_SPORTS` replaces today's unwritten rule that a user with no subscription row gets through."
- **Why:** The rule is written down. The `require_paid_access` docstring (`api/auth.py:97-127`) says gating those users "would revoke the private alpha's whole user base the day billing shipped." Invite users are created with `plan="none"` and no billing row (`api/auth.py:190`). The one-time copy only moves billing rows, so they get nothing. Unless MLB is in `FREE_SPORTS` (decision 4 is still open), they get 402 on deploy, with a "Not available yet" button and no way to pay.
- **Fix:** Keep the passthrough for users with no billing rows, as an explicit `LEGACY_INVITE_GRANTS = all currently served sports` with an end date and notice. Add a test: an invite user with no rows keeps MLB, NFL and Tennis.

**A6. Legacy beta subscribers lose NFL and Tennis (HIGH, [code]).**
- **Quote:** "a legacy `beta` plan that grants MLB"
- **Why:** Beta payers can reach `/card?sport=nfl`, `/games?sport=nfl`, `/tennis/board` and `/live?sport=nfl` today (`api/card.py:83-91`, `api/games.py:385`). Granting only MLB removes paid features in the middle of a billing period with no notice.
- **Fix:** Beta grants mlb, nfl and tennis, or the bundle. Any reduction waits for the 30-day notice.

**A7. Coming-soon sports can never build a record (MED).**
- **Quote:** Decision 6, "off sale until they have a public graded record", plus "An NFL-only subscriber gets 402".
- **Why:** If NFL is gated and can't be bought, nobody receives the picks, so nothing is "published before the game".
- **Fix:** Put coming-soon sports in `FREE_SPORTS` while their record builds. Alternatively, publish a hash of each card before games and reveal the picks after grading.

**A8. The new 402 body breaks the client (MED, [code]).**
- **Quote:** "returns 402 with `{sport, plan_ids, price_cents}`"
- **Why:** `web/js/dom.js:409` looks for `{"error":"subscription_expired"}`. The new body has no `error` key.
- **Fix:** Return `{"error":"sport_not_in_plan","message":..., "sport", "plan_ids", "price_cents"}` and update `dom.js`.

**A9. Checkout idempotency doesn't handle several plans (MED, [code]).**
- **Why:** `create_checkout`'s `plan_id` argument is really the Stripe price id (`line_items[0][price]: plan_id`, `src/appstate/billing.py:593`). The key resolver and the `billing_checkout_idempotency` table use primary key `(user_id, plan_id)`. If a user changes their selection, reusing a stored key with different line items makes Stripe reject the request as an idempotency mismatch. Reusing the key with the same items returns a stale session. The plan doesn't mention this.
- **Fix:** If you keep multi-plan checkout, build the key from the sorted plan set. Better, use one plan per checkout (see B1).

**A10. Rollback serves stale data (MED).**
- **Quote:** "The old table stays for rollback."
- **Why:** After deploy, webhooks only write `billing_entitlements`. Rolling back reads a frozen `billing_subscriptions`: new buyers are locked out and cancelled users keep access.
- **Fix:** Write to both tables until the new one is confirmed, or state that rollback means replaying Stripe events.

**A11. `beta` is still for sale (MED).**
- **Quote:** "`STRIPE_BETA_PRICE_ID` is kept."
- **Why:** Nothing marks beta as not sellable. The existing allowlist tests (`tests/test_api_billing.py:108,118`) would keep `plan_id="beta"` checkout working next to `mlb`.
- **Fix:** Give beta `status="legacy"`, and have checkout return 400 for it.

**A12. `users.plan` is left behind (LOW, [code]).**
- **Quote:** "Replaces the hard-coded values at ... `users.py:76`"
- **Why:** `users.plan` is one value per user, and `api/admin.py:63,100` reports on it. Adding the per-sport ids to `VALID_PLANS` means nothing, because the column can't hold several.
- **Fix:** Freeze `users.plan` as a legacy field. Admin stats read the entitlements table.

## B. Stripe mechanics

**B1. Line items and per-sport cancel contradict each other (HIGH).**
- **Quote:** "one line item per plan" versus "Cancel and reactivate work per subscription" and "Cancelling one sport must leave the other active."
- **Why:** A subscription Checkout with several recurring prices creates one subscription with several items. `cancel_at_period_end` applies to the whole subscription, so cancelling cancels every sport. Dropping one sport means deleting a subscription item. That takes effect immediately with proration and removes access now. It breaks the "access through the paid period" rule in `has_paid_access`.
- **Fix:** One subscription per plan: one plan per Checkout, and the bundle covers multi-sport buyers. Cancel, reactivate, grandfathering and proration then stay per subscription, matching today's code. If you must keep multiple items, you need subscription schedules to drop an item at period end. That is much more work.

**B2. The metadata is on the wrong object for the first webhook (HIGH).**
- **Quote:** "`subscription_data[metadata][plan_ids]`" and the webhook "writes one row per plan from that metadata".
- **Why:** `subscription_data.metadata` lands on the Subscription. The `checkout.session.completed` object only has `subscription` as an id and its own session `metadata`. The handler (`billing.py:824-843`) makes no Stripe calls, so it can't see the plan ids.
- **Fix:** Put the plan on each Stripe Price as `metadata.plan_id`. It rides along in `items.data[].price.metadata` on every subscription event, survives grandfathering, and isn't lost if someone edits the subscription in the Dashboard. Also set session `metadata[plan_id]` for the completed event. Keep a list of historical price ids per plan in `plans.py` as a fallback.

**B3. Legacy beta subscriptions have no metadata (HIGH).**
- **Why:** Existing beta subscriptions were created without plan metadata. Their `customer.subscription.updated` and `.deleted` events (renewal, cancel, failed payment) wouldn't map to any plan. The copied `beta` row would never update, so a cancelled beta user keeps access indefinitely.
- **Fix:** When metadata is missing, match the existing row by subscription id, or treat price id == `STRIPE_BETA_PRICE_ID` as `beta`. Test a legacy-sub cancel with no metadata.

**B4. The table key contradicts the plan, and late events lock out payers (HIGH, existing bug made worse, [code]).**
- **Quote:** "primary key `(user_id, plan_id)`" versus "keyed by subscription id".
- **Why:** Today, `customer.subscription.updated` and `.deleted` overwrite by user without checking the subscription id (`billing.py:844-857`). Keeping `(user_id, plan_id)` means a late or retried `deleted` event for an old MLB subscription overwrites the row of a new active MLB subscription, and a paying customer gets 402. With multi-item subscriptions, removing an item doesn't change the metadata, so the removed sport stays unlocked.
- **Fix:** Store `(stripe_subscription_id, plan_id)` rows. Entitlement means any row for the user with a qualifying status that grants the sport. Only apply an event to the row with its own subscription id. The duplicate-event guard also uses the subscription id.

**B5. Bundle and single plans overlap, causing double charges (HIGH, consumer).**
- **Quote:** "Skip plans the user already has" and "Reject ... a bundle combined with single sports".
- **Why:** That check only looks inside one request, by plan id. A user with MLB who later buys the bundle pays for both. A bundle holder who buys MLB isn't skipped, because `mlb` isn't `all`. A user who scheduled a cancel and buys again is "skipped" and can't re-buy.
- **Fix:** Check sport coverage, not plan ids. Refuse a purchase whose sports are already covered. Offer "switch to bundle" as a subscription update (swap the price, prorate or start next period). Send scheduled-cancel users to reactivate.

**B6. Subscription lookup (MED).**
- **Quote:** "match by subscription id, not `subs[0]`"
- **Why:** This is correct, but the cancel and reactivate APIs don't say how the caller picks which subscription.
- **Fix:** `POST /billing/cancel {plan_id}` looks up the local row's subscription id, then calls `GET /v1/subscriptions/{id}` directly. Don't list the customer's subscriptions.

**B7. Moving subscribers to a lower price (MED).**
- **Quote:** Decision 7, "move existing subscribers down".
- **Why:** Updating the item's price defaults to prorations mid-period.
- **Fix:** Use `proration_behavior=none`, effective at renewal, with the Price metadata from B2 so the plan still maps.

**B8. Free MLB while beta subscribers pay (MED, consumer).**
- **Quote:** Decision 4, "keep MLB free through the 2026 postseason".
- **Why:** Beta subscribers would keep paying $19.99 for something free to everyone.
- **Fix:** If you choose this, use `pause_collection` or a 100% coupon on beta subscriptions for that stretch. More generally, don't bill a sport through its offseason: pause automatically between seasons, or disclose the offseason clearly before purchase.

**B9. Grandfathering needs its catch disclosed (LOW, consumer).**
- **Quote:** "Existing subscribers keep the price they signed up at ... Stripe does this natively."
- **Why:** Stripe does handle this, but only while the subscription stays active. `docs/PRICING_OFFER_VALIDATION.md:84` says so; the plan's customer text doesn't.
- **Fix:** Show the caveat at checkout and in cancel emails.

## C. The pricing rule: gaming and unverified inputs

**C1. Graded at the best of about 11 books (HIGH, [code]).**
- **Quote:** "at the odds shown when the pick was published"
- **Why:** The card freezes `best_price` across books (`src/report/card.py:323-326`), and history shows "best of 11 books" (`src/appstate/card_ledger.py:1152`). The record, and any price rise, is inflated compared with what a one-book subscriber can actually get. It also breaks FTC expectations about typical results.
- **Fix:** For pricing, grade at a fixed reference price (median or consensus, or one named book). Show both prices if you like.

**C2. Which picks count isn't fixed (HIGH).**
- **Why:** The card mixes game picks, props (added 09-12) and totals (added 09-14). Picks lock at different times (card_ledger.py:1155-1162). The operator could choose which categories count.
- **Fix:** Define the eligible pick set in `plans.py`, tied to a start date. Any change resets the window.

**C3. Rewards volume (HIGH).**
- **Why:** Dollar profit at $10 flat rises with the number of picks: the mean grows with n, the margin with the square root of n. Publishing more thin-edge picks raises the price. At about 9 picks a day, "1% of a $1,000 bankroll" isn't meaningful.
- **Fix:** Base the step-up on the lower bound of units per pick, multiplied by a fixed reference volume (for example 100 picks a month), not on actual volume.

**C4. The confidence margin assumes independent bets at -110 (MED).**
- **Why:** Several picks per game or per day are correlated. NFL can only reach 500 picks in 6 months with several picks per game. Props at +300 have far higher variance.
- **Fix:** Compute variance from actual payouts, with a block bootstrap by game or date.

**C5. Many chances for a lucky rise (MED).**
- **Why:** Five sports times four reviews a year gives many chances for a false positive at 95% one-sided.
- **Fix:** Require a positive lower bound in two quarters in a row, or adjust the confidence level for the number of sports.

**C6. "Published before the game" can't be checked (MED).**
- **Why:** The picks go only to paying users, so the pregame timing is self-attested.
- **Fix:** Post a public hash of each frozen card, with a timestamp, before first game. Reveal after grading.

**C7. The worked example's arithmetic is wrong (LOW).**
- **Quote:** "The step-up is 10% of $36, which is $3.60. New subscribers pay $23.99"
- **Why:** $19.99 + $3.60 = $23.59. The margin itself checks out: about ±$380, about $220 low end.
- **Fix:** State a rounding rule, for example round the step-up down to whole dollars.

**C8. Customers can game refunds (LOW).**
- **Why:** The refund rule in `docs/PRICING_OFFER_VALIDATION.md:78-82` is "once per customer per plan". With per-sport plans that allows up to about six free weeks.
- **Fix:** Once per customer.

**C9. The bundle is mispriced with one live sport (MED).**
- **Quote:** "Suggest 25% off the combined price of the live sports."
- **Why:** With only MLB live, the bundle costs $14.99, less than MLB alone. Everyone buys it and gets future sports at a grandfathered price.
- **Fix:** Sell the bundle only when two or more sports are live, and never below the most expensive single sport.

**C10. Inputs needing a source (LOW).**
- The 8,811-strategy figure is sourced in `docs/EVOLAB_PHASE2B_RESULTS.md:21`.
- "The MLB picks show no positive estimated return against the market benchmark" has no citation in the plan. [unverified]
- The Federal Register doc number 2022-04679 needs checking. [unverified]

## D. Wording that implies profit, and consumer-protection gaps

**D1. The displayed figure is an earnings claim (HIGH).**
- **Quote:** "Each sport's pricing section shows: ... the luck-adjusted figure".
- **Why:** In Part B that figure is dollars of monthly profit at a stated stake. Showing it next to a price is an earnings claim, whatever words are banned.
- **Fix:** Show only W-L-P, units at a flat stake (with the grading price basis), sample size, dates, and a confidence range that includes values below zero. Never show dollars per month, and never "luck-adjusted profit".

**D2. The price itself signals profit (HIGH).**
- **Quote:** "Price reflects this sport's published, graded record."
- **Why:** Paired with a rising price, the net impression is "a higher price means it makes you money."
- **Fix:** Say "Price may change quarterly under a published rule based on the graded pick record. A higher price does not mean you will profit." Add a typical-results line: "We do not track subscriber results. The record uses best-available prices."

**D3. "Verified" (MED).**
- **Quote:** "verified public record" (TL;DR) and "MLB has no verified positive record."
- **Why:** "Verified" implies an independent audit. The grading is self-performed.
- **Fix:** Use "self-graded, timestamped record", or get third-party tracking.

**D4. The locked panel puts the record next to Subscribe (MED).**
- **Why:** A record summary beside a Subscribe button is advertising and needs the full disclosures from D1 and D2 in the panel itself. The disclaimer "Past graded results do not predict future results" alone isn't enough.

**D5. The worked example must stay internal (LOW).**
- **Quote:** "+$600 ... matches the owner's $100/month on $1,000".
- **Fix:** Label it as internal only so it never reaches marketing copy.

**D6. Missing law (MED, [unverified], for counsel).**
- The plan cites the Endorsement Guides and the Business Opportunity Rule. It leaves out:
  - FTC Act Section 5 substantiation, which covers the service's own record even with no endorsements;
  - ROSCA (15 U.S.C. 8401-8405) for online recurring billing;
  - state automatic-renewal laws. California's was amended in 2024 with its own timing and content rules for price-change notices. Check "at least 30 days" against them.
- Don't rely on the FTC Click-to-Cancel rule, which I understand was vacated in 2025.
- Also missing: age gating and responsible-gambling messages next to pick records.

**D7. The demo is safe only while production stays clean (LOW, [code]).**
- **Quote:** "`PUBLIC_DEMO` still has no access checks, so the demo is unchanged."
- **Why:** This is accurate. `deploy/fly.production.toml:53` deliberately leaves `APP_PUBLIC_DEMO` out, and staging sets it (`fly.staging.toml:43`). But the staging URL serves every sport's paid content to anyone who has it, and the new test "PUBLIC_DEMO opens everything" locks that in.
- **Fix:** Add a test that `fly.production.toml` never sets `APP_PUBLIC_DEMO`. Don't share the staging link in marketing.

## E. What is sound

- Not pricing from backtests. The owner's 5-20% rule honestly gives about $0, and the 8,811-strategy search result is sourced.
- A cost floor that isn't tied to performance.
- Price only rises when the statistical lower bound is positive, with a 500-pick minimum and a 2x cap.
- Fixed quarterly review dates, prices falling as readily as they rise, and decision 7's move down.
- Grandfathering by keeping the subscription's price id is native Stripe behaviour, matching `PRICING_OFFER_VALIDATION.md:97-99`.
- New prices do nothing until each environment variable is set. This mirrors today's `not_configured` path, and no Stripe object is created.
- A new entitlements table instead of rebuilding the primary key in SQLite, with a copy of existing billing rows so current payers keep a row.
- Dropping `subs[0]`.
- Rejecting coming-soon plans, unknown plans, and a bundle plus singles in one request.
- `scripts/price_review.py` only proposes; a person edits `plans.py` and creates the Stripe Price.
- Excluding pooled or placed bets, per `LEGAL_COMPLIANCE_RESEARCH.md`.
- Public Results (decision 5). Once A4 is done this makes signup's "checkable" claim true.
- A 30-day notice consistent with `PRICING_OFFER_VALIDATION.md:85`, plus a public price-change log and the past-results disclaimer.
- Banning ROI, "make $X" and bankroll-growth wording.
- Access tests run against the real app with a temporary database and must fail on the current code first. Plan and price tests loop over every plan. Billing and access control need the owner's go-ahead plus `/ultra-review` before merge.
- Recognising the MLB offseason problem (decision 4).

## F. Tests the plan is missing

1. An invite user with no billing rows keeps every sport they have today.
2. A beta subscriber keeps NFL and Tennis.
3. An NFL-only subscriber is refused on `/today`, `/opportunities`, `/daily`, `/record`, `/odds`, `/betcheck`, `/live?sport=mlb`, `/props?sport=nfl` and `/game/...?sport=nfl`.
4. `/card/record` works without auth, and `/card` does not.
5. A late `subscription.deleted` for an old subscription doesn't revoke a new one.
6. A legacy beta subscription event with no metadata still updates its row.
7. A bundle bought over an existing single sport is refused or switched, never billed twice.
8. The 402 body keeps the `error` key.
9. `fly.production.toml` never sets `APP_PUBLIC_DEMO`.