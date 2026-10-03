# Release 2026-10-03: customer discovery tooling, the tester's first screen, the expired-tester path

Billing stays off. No card rule, gate or published pick changes.

## What is in it

| Part | What changed | Why |
|---|---|---|
| Signed-in card page | Each bet on a V2 card is drawn as its own card with its own sentence; picks before fills; the headline count matches; our own number is shown; no "%%" | Every V2 card since 2026-09-22 drew the first pick repeated with the bet line blank. It is the first screen a tester sees. `SIGNED_IN_CARD_RENDER.md` |
| Activation | "Activated" means a signed-in tester opened real content, not that they signed in. Returning means again 12 hours or more later. The admin page shows both per tester, plus which features were used, and exports the totals without emails | The owner's rule: a signup who never opens the product is not activation |
| Outreach queue | One record per human, a private local store for names and exact words, eleven reply types, sending groups, milestones, the customer section of the dashboard | Batch 1 is a customer-discovery experiment; the repository is public |
| Expired tester | A tester whose week ended sees that it ended and when. With billing on, a button starts checkout on their own account from their own token. The signup form never starts a checkout for a tester's email | The old path was a dead end ("invited"). The first fix let an email open someone else's account; review caught it before push. `EXPIRED_TESTER_PAID_PATH.md` |
| Billing faults found on the way | A payment event redelivered after a subscription ended no longer revives it. Extending a tester who has a subscription record is refused with a reason | Found by the review; fixed with tests |
| Production watch | Flags a deploy unfinished for 20 minutes | `PROD_DEPLOY_HANG.md` |

## Status

| Stage | State |
|---|---|
| Implemented | yes |
| Targeted tests | pass (each worker's modules, re-run after merging them together) |
| Independent review | done for the expired-tester path (adversarial, 8 defects pinned as tests, all now passing); done by the orchestrator for the card page, activation and outreach |
| Local browser | card page, admin Testers and activity block, expired-token sign-in, tester checkout route with billing off: all seen working on localhost |
| Full suite (Windows) | 9,969 tests, no failure outside the eight known Windows-only identities |
| Linux CI simulation (no FastAPI) | 651 tests in the changed modules, 0 failures |
| Committed | yes |
| Pushed | 17:16Z, `5398c83d` (inside the minute 15 to 39 window) |
| Linux CI | success on Python 3.10, 3.11 and 3.12 (run 37139917877) |
| Staging | verified from outside 17:20Z: health ok, checkout in Stripe test mode, restarted 17:17Z; `/admin/activation`, `/admin/testers` and `POST /billing/tester-checkout` refuse without a valid token (401); new `card.js`, `signin.js`, `admin.js` served. The staging click-through with a card is the owner's (`docs/billing/PURCHASE_REHEARSAL.md`) |
| Production | deployed 17:42Z (run 37139264169, after two hung runs were cleared); verified from outside 17:47Z: health ok, billing off, new `card.js`, `signin.js` and `admin.js` served, `/admin/activation`, `/admin/testers`, `/admin/overview`, `/card` and `POST /billing/tester-checkout` refuse without a valid token (401), landing, index, `/meta` and `/postseason` answer 200 |

## Not in it

- The second-free-week decision, the old-event-after-new-subscription guard
  and the staging click-through: `docs/billing/PURCHASE_REHEARSAL.md`.
- Moneyline use is not measurable (no page serves it on its own).
- The prop numbers still ignore the opposing starter
  (`docs/analysis/MLB_2026-10-03.md`, last section).
- The deploy job still has no time limit until the owner applies the
  one-line patch.

## Log

- 17:16Z pushed `5398c83d` after fetch, merge, quick tests and the no-FastAPI run.
- 17:20Z staging verified from outside (see table).
- 17:38Z Linux CI green. Production was blocked behind a second hung deploy (run 37135966540, since 16:11Z); the owner cancelled it at 17:40Z.
- 17:42Z production restarted on the release; verified from outside at 17:47Z (see table).
- Example accounts (`/card/accounts`, the "If you had followed every pick" section) were merged after this push and are not in production yet.
