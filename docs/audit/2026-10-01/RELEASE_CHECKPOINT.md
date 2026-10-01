# Release checkpoint, 2026-10-01

Release train: buying path, postseason page, feed gate. Pushed as `c9054371`
at 20:13Z. States are tracked separately; "done" is not used.

| | Buying path | Postseason page | NFL game-day refresh |
|---|---|---|---|
| Implemented | yes | yes | yes |
| Targeted tests | 18 acceptance + 500 or so module tests, green | 156, green | 24 (312 across NFL modules), green |
| Local browser | checkout OFF state only (landing, signup, sign-in, completion page, record) | yes, on real 2026 data | not applicable |
| Full suite | 9,165 tests at `e5568bdf`: 18 failures, all in the baseline | same run | pushed earlier (19:43Z) on its module tests; in the same full run |
| Committed | `1c1a9a60` | `e5568bdf` | `8aa3b070` |
| Pushed | 20:13Z (`c9054371`) | 20:13Z | 19:43Z (`87237fbc`) |
| Staging verified | see "Staging" below | see below | first refresh not yet observed |
| Production verified | NO | NO | not applicable (runners) |

## Postseason

- Current-data status (local build, 20:10Z): bracket, seeds and every score
  match the MLB feed (independent check). Team results current through
  2026-09-30. Stored pitcher logs end 2026-09-07 and bullpen logs 2026-09-06.
- Stale-data behaviour: a starter is in a game's number only when both sides
  are confirmed by the schedule with numbers no more than 3 days behind the
  results. Bullpens are in the number only when their log is that current;
  today they are left out of every estimate. A named starter's own log is
  fetched from the feed at build time (up to 24 lookups), which is how one
  game today is CONFIRMED_CURRENT with a store that is three weeks old.
- Counts on the real page: 16 unplayed games; 1 CONFIRMED_CURRENT,
  11 PROJECTED_CURRENT, 4 STALE_REFERENCE_ONLY (the lookup cap), 0 UNAVAILABLE.
- Starter scenarios, one matchup, three states: `postseason_starter_demo_NYY_at_TB.txt`.
  Confirmed: TB 56.3%. Projected, not announced: slot shows TBD, estimate
  TB 48.5% (no starters), scenario line TB 56.3% labelled "not the estimate".
  No usable current starter: TB 48.5%, no scenario. The two non-confirmed
  states give the identical no-starter number.
- Disclosed, not removed: where a starter is used, the league-wide pitching
  average his rate is compared with is still computed from the stored logs
  (ending Sept 7). The page says so beside the caveats.
- Local browser proof: page rendered at localhost on the real payload;
  PHI at ATL game 3 reads "Starters confirmed, current numbers used ...
  3 of 4 inputs are current and used"; NYY at TB game 1 reads "NYY: TBD ·
  TB: Drew Rasmussen ... 2 of 4 inputs" with the scenario block beneath; no
  banned word, no "undefined"/"NaN", no horizontal overflow at 1265px; the
  call to action reads "get notified when checkout opens" (checkout is off).
  Not checked by eye: the 390px layout after the last two rounds of changes
  (screenshots timed out with the pane hidden; width was measured, not seen).

## Billing

- End-to-end, in-process Stripe stand-in (never a real request), all passing
  in `tests/test_billing_acceptance_path.py`:
  new user -> checkout -> both webhooks -> entitlement on disk (status
  trialing, access granted) -> token collected -> re-read window lapses ->
  the token alone still opens a paid page.
  Duplicate webhook x3: one token, one session row, one subscription.
  Forged webhook: refused, nothing written.
  Cancel: renewal off, paid-through access kept; after the period, 402
  `subscription_expired`; `deleted` with time left keeps access until then.
  Each of four settings removed one at a time: explicit "payments are not
  available right now; nothing has been charged", no checkout session
  opened, `/meta` says "unavailable", `/health` says "broken" (HTTP 200).
  Billing off: status "waitlisted", page says "Checkout is not open yet".
- Recovery without the tab: the completion link works for 72 hours if never
  read (10 minutes after first read); after that support re-issues with
  `POST /admin/users/token` (admin token; paid access required; old tokens
  revoked). There is no email sender, so there is no self-service recovery.
- Found in my review after the worker and the independent reviewer:
  checkout opened with no webhook secret; `/health` "ok" with the API key,
  price id or webhook secret missing; the paid-through date read only from
  the pre-2025 Stripe field; a billing misconfiguration turned `/health`
  into a 503, which is what Fly routes on.
- Not tested against real Stripe. First real proof is the owner's own test
  purchase.
- Deferred, on the dashboard: failed renewal keeps access to period end;
  a redelivered or out-of-order event can restore access; the 366-day token
  is not renewed automatically.
- Owner actions: Stripe verification (date of birth, phone, identity);
  create the webhook endpoint; set the five Fly secrets in ONE command;
  one real purchase and refund; monitor the support address.
- Wording decision for the owner: with checkout off the buttons say "Get
  notified when checkout opens". Nothing sends that notice automatically.

## Tests

`full_suite_e5568bdf_comparison.txt`: PRE_EXISTING 18 (identical identities,
all Windows-environment), FIXED 0 against the baseline, NEW_EXPECTED 0
failing (489 tests added, all passing), NEW_REGRESSION 0, UNKNOWN 0.
Linux CI on `c9054371`: see "Staging".

## Cost

`credit_efficiency_2026-10-01T2010Z.txt`. Not called a success yet.

- Before the change (00:00Z to 18:42Z): 441 credits, 23.6 an hour; NFL 266
  and MMA 85 of them (85 capture instants each).
- After (18:42Z to 20:10Z, 1.5 hours, 2 NFL captures): 13 credits, 8.9 an
  hour; NFL 6, MMA 1.
- NFL card-usable time (a kickoff within 6 hours and the board under 60
  minutes old): 100% of the 88 minutes observed so far, at 4.1 credits per
  usable hour against 591 before.
- Coverage lost on purpose: NFL and MMA price snapshots between phases on
  days and hours with no game near (about 75 a day each). Coverage that was
  lost by accident this morning and restored at 19:43Z: the NFL card's fresh
  board inside the six hours before kickoff. Both NFL captures observed so
  far were phase captures; the 25-minute refresh itself has not fired yet.
- Not measured: whether the MMA card needs the same freshness rule.

## Release

- Commits on origin since this morning's base: `4ebaaed2` (capture and
  grading fixes), `eb850168` (settle fix), `f18517db` (record split),
  `8aa3b070` (NFL refresh), `1c1a9a60` (buying path), `dc614a5e` (loop feed
  gate), `e5568bdf` (postseason page), plus evidence and dashboard commits.
- Active on push: staging redeploys; the runners use the new capture and
  loop code from their next run; the 10:10Z loop will write the first
  postseason forecast rows and, with no webhook secret set, post nothing to
  Discord. PRODUCTION: the hourly refresh deploys the branch head when the
  latest tests run is green, so this release reaches production on the
  first refresh that runs. One is waiting behind a deploy stuck since 18:13Z.
- Not activated by this release: billing (provider unset in production),
  the Discord feed (no secret), any change to a card rule or gate.
- Experimental or shadow: the postseason estimates (no track record, said on
  the page), every shadow ledger, the NFL value card's thin output.
