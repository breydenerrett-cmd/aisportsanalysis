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

---

# Release 2 (21:16Z): UFC fight night with the AI analyst, the UFC data in the image, playoff rest days

Billing stays off. No card rule, gate or published pick changes. UFC picks stay paused.

## What is in it

| Part | What changed | Why |
|---|---|---|
| UFC fight night | The UFC page shows the next card bout by bout: who is fighting, each fighter's form, strengths and weaknesses from the fight statistics, the price, and a written read. It replaces the empty "picks paused" screen | The owner: "are we actually doing matchup analysis?" `docs/UFC_FIGHT_NIGHT.md` |
| UFC AI analyst | A model-written call on every priced market of every bout, frozen before the bout and graded in public on its own record, mounted inside each bout. It runs only once the owner adds the API key | `docs/AI_ANALYST.md` |
| UFC data in the image | The normalised UFC files (156 events, 1,689 bouts, 3,182 statistics rows, 4,033 odds rows, 1,075 fighters, ~14 MB) are committed and copied into the image | Without them production would have loaded an empty store and said no card is booked |
| UFC data kept current | The daily loop runs `ufc update` (last 10 days of results, next 21 days of cards) and commits the files. Rehearsed from an empty cache as the runner runs it: 225 requests, 125 s, 0 errors; it picked up tonight's UFC 332 and its finished prelims | Nothing refreshed the files |
| UFC data status | A booked card no longer counts as the newest data (the status said a December date and a negative age) | `src/datasvc/ufc/store.py` |
| Playoff rest days | The starter card's DAYS REST counts postseason outings and says when and in what game he last pitched; the model input does not move | A Wild Card starter showed 14 days (the cap) |

## Status

| Stage | State |
|---|---|
| Full suite (Windows) on `83f58326` | 12,153 tests, no failure outside the known Windows-only identities |
| Targeted tests for the later commits | pass (datasvc, image, daily loop, game route and page, analyst packet, read) |
| Linux CI simulation (no FastAPI) | 655 tests in the 18 changed modules plus 34 for the rest-day change, 0 failures |
| Pushed | 21:16Z, `fa13daad` (inside the minute 15 to 39 window) |
| Staging | deployed 21:22Z; verified from outside: health ok and no store reported stale (pitcher logs through 2026-10-03, results through 2026-10-02, standings through 2026-09-27, the last regular-season day), new `gamestory.js` and `main.js` served, `/game/...` carries `advanced.starter_rest` for all six games checked (2026-10-03 and 10-04), `/ufc/fight-night` refuses without a token (401) |
| Linux CI | success on Python 3.10, 3.11 and 3.12 (run 37154528035, 21:37Z) |
| Production | deployed 22:10Z (deploy-prod on `00951748`, a capture commit that contains `fa13daad`); verified from outside 22:11Z: health ok, no store stale (results through 2026-10-02, pitcher logs through 2026-10-03), new `gamestory.js`, `main.js`, `ufcfights.js` and `analyst_ufc.js` served, `/ufc/fight-night` and `/games/...` refuse without a token (401), `/analyst/ufc/record` answers with 0 bouts published (the analyst is off until the owner adds the key), landing, `/meta` and `/postseason` answer 200. The signed-in pages were checked on staging |

## Log

- 21:16Z pushed `fa13daad` after fetch, merge, the full suite on `83f58326`, targeted tests on the later commits and the no-FastAPI run.
- 21:22Z staging deployed and verified (see table).
- 21:37Z Linux CI green.
- 22:10Z production deployed; verified from outside at 22:11Z (see table).
