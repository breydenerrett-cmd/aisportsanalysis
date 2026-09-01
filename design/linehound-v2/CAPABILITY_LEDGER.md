> **AUDITED AT SHA `3dca767`. NOT CURRENT-PRODUCTION TRUTH.**
> Branch HEAD at push time was `cfe6bcb` (5 commits later, incl. a canvas-first frontend
> rebuild). Parent must reconcile against current HEAD before treating findings as
> authoritative. Two findings are already confirmed superseded — see
> `RECONCILIATION_REQUIRED.md`. No finding has been weakened or removed.

# LINEHOUND CAPABILITY LEDGER — the design contract

Repo `/Users/breydenerrett/Desktop/SportsAnalystToolDesign/linehound-repo`, branch `claude/sports-betting-analysis-review-g1o0co`, HEAD `3dca767` "Forward capture 21:01Z" (verified; one untracked design file). Merged from four adversarially-verified domain reports; the load-bearing constants below were re-read at HEAD before writing.

## 0. FIVE FACTS THAT DOMINATE EVERY DESIGN DECISION

1. **Zero findings on every game, today.** `findings: []` and `top_findings: []` on 15/15 games on the live slate. Every "why this game is interesting" region renders the constant `NO_EDGE_HEADLINE = "Interesting matchup, but no demonstrated betting edge."` (`src/analysis/synthesis.py:186`, verified verbatim) and the dashboard's `"No detector had anything to say about this game."` (`src/report/dashboard.py:987`). The zero-findings state is the **primary** state, not the empty state.
2. **4 sections, 12 gaps.** Every game dossier from the API carries sections `park, price_improvement, multibook_board, what_changed` (the last on 12/15) and gaps `teams, starters, weather, news, lineups, matchup_depth, bullpen, arsenals, travel, splits, matchup_history, market`. All four API builders call `briefing.build_slate(games, store)` with **zero enrichment kwargs**: `api/games.py:115`, `api/today.py:122`, `api/digest.py:65`, `api/betcheck.py:180`. The signature accepts 17 (`src/pipeline/briefing.py:54-61`).
3. **Nothing in the shipped client is designed.** All unpinned payload goes through `renderUnknown` → `<dl class="raw-fields">` (`web/js/dom.js:139-160`), by documented rule: a hand-built template "implies an assumed shape docs/API_CONTRACTS.md does not yet guarantee" (`web/README.md:120-124`). There is no existing designed presentation of any block to iterate on.
4. **Every human-readable label is missing.** Teams on the wire are abbreviations (`src/providers/mlb.py:268-269` → `_team_abbrev` → `abbreviation.upper()`, `:559-562`). Books are raw provider keys (`fanduel`, `williamhill_us`, `betonlineag`). No display-name map, no logos, anywhere.
5. **Commerce is inert out of the box.** `DEFAULT_BILLING_PROVIDER = "null"` (`src/appstate/billing.py:851`, verified); `NullBillingProvider.create_checkout` returns `""` (`:189-195`). **Every signup waitlists in a default deployment**, even with both Stripe env vars set. The 402 `subscription_expired` state is therefore unreachable without Stripe wiring (`api/auth.py:120` returns early with no subscription record; `api/billing.py:265-266` skips the write when `provider_ref` is None).

---

## 1. EXISTS TODAY — designable now

### 1.1 `GET /games/{date}` — the Gameday card feed
`slate_game_summary`, `src/analysis/gamepayload.py:171-189` (re-read; exact). One row:

| Field | Shape / values | Note |
|---|---|---|
| `game_id` | `"SD-CIN-2026-09-01-1"` — `AWAY-HOME-DATE-N` | verified live |
| `away_team` / `home_team` | 2–3 char abbrev, uppercase (`"SD"`, `"NYY"`) | **not** club names |
| `date` | `"2026-09-01"` (MLB official Eastern date) | |
| `first_pitch_utc` | `"2026-09-01T22:40:00Z"` | |
| `venue` | full string (`"Great American Ball Park"`) | |
| `verdict` | `"no_play"` — the only value in production, 15/15 (`src/pipeline/mismatch.py:131`) | |
| `market_implied_consensus` | **always `null`** — reads `dossier.get("market")`, a gap (`gamepayload.py:133-144`) | dead field |
| `board_summary` | `{books:int, observed_utc:iso, age_seconds:float, has_board:bool}` (`:146-153`) | the card's **entire** price content |
| `data_quality` | `{has_market, has_lineups, has_starters, has_price_board, gaps:{…12…}}` (`:155-169`) | full gap ledger ships on the list row |

**No `best_price`, no `best_book`, no improvement figures on this endpoint.** Those require a per-game fetch.

### 1.2 `GET /odds/{date}` and `/odds/{date}/{away}/{home}` — richest live surface
`api/odds.py:63,79`, mounted paid at `api/app.py:68`. Pinned field-by-field in `docs/API_CONTRACTS.md:159-198` **and** contract-tested (`tests/test_api_contracts.py:453-580`, incl. `test_mobile_readiness`). Bind with the same confidence as `/today`.

- Slate summary: `{games_count:int, widest_spread_game:{game_id, side, spread_cents}, books_disagree_on_favorite_count:int}` (`src/analysis/oddspayload.py:311-313`).
- Per game: `game_id, away_team, home_team, date, first_pitch_utc, venue, markets.h2h`.
- `markets.h2h` (`oddspayload.py:184-215`, re-read):
  - `board_available: bool`, `reason: str|null`
  - `board: [{book, away_price, home_price, captured_at}]` — American ints
  - `best: {away:{price, books:[…all ties…]}, home:{…}}`
  - `consensus: {away:{implied_probability, implied_price}, home:{…}, books:int} | null`
  - `consensus_unavailable_reason` — **key is ABSENT when there is no board at all** (`oddspayload.py:194-202`); present only when a board exists but is below floor. Use `hasOwnProperty`, never truthiness.
  - `spread_cents: {away:int|null, home:int|null}`
  - `staleness: {observed_utc, age_seconds|null, …}` — honest nulls
- `MARKETS = ("h2h",)` (`oddspayload.py:58`, verified). Pre-game only. Doubleheaders carry a `note`. Empty slate = 200. Errors 400 / 404 / 502.

### 1.3 `POST /betcheck` — the analysis engine
- Five-field structured request: `date, away, home, side, american_price` (`api/betcheck.py:139,148-152`).
- Price gate `100 ≤ |price| ≤ 100000` → 422 (`:106-107,153-162`); ISO date gate → 400 (`:123`); structured 404 naming games searched (`:203-206`); doubleheader → earlier game + `note` (`:221-227`).
- `best_available_price: {book, american_price, observed_utc}` — refuses a nameless book (`src/analysis/contracts.py:149-159`).
- `market_consensus.implied_probability` — **a fraction in (0,1)**, not a percent (`contracts.py:170-180`).
- `price_improvement` with a **mandatory** label; negative is normal (`contracts.py:189-208`; label text `src/analysis/prices.py:33-34`).
- `your_price_beats_consensus: bool` — `true` means the customer's price is **better** (`contracts.py:474-480`).
- `counterargument_lines` — **never empty**, constructor-enforced (`contracts.py:516-518`).
- `recommendation` — permanently `null`, `__post_init__` raises otherwise (`contracts.py:495,497-501`, re-read verbatim).
- **Rule S**: a quantitative claim without `sample_n` + `sample_unit` **raises** (`contracts.py:230-249`, re-read). This refusal is the product.
- `bottom_line` — mechanically composed: finding count + price clause + permanent disclaimer (`src/analysis/betcheck.py:586-633`).
- `evidence_status: "Observation"` is reachable and is the only reachable value.
- Rate limits: 30/min paid (`api/betcheck.py:72`), 10/hr free (`:84`).

### 1.4 `GET|POST|DELETE /my-bets`
`_serialize`, `api/mybets.py:142-158` — 8 fields: `id, game, side, price, saved_at, snapshot_digest, settlement_status, settlement_reason, settled_at`. Free text only: **no game_id, no date, no market, no book** (`src/appstate/savedbets.py:76-86`). Append-only + soft delete; **no `update_bet` exists** (`:3-12,171-180`). Delete button is wired and is the only account-data action a customer can perform (`web/js/mybets.js:87-96`).

### 1.5 Auth / commerce mechanics that work
- One credential type: invite token == activation token, `secrets.token_urlsafe(32)`, sha256-stored, **14-day TTL** (`src/appstate/users.py:250-267`, `:62` verified, `:92-95`). Two production minters: `api/auth.py:203` (admin) and `src/appstate/billing.py:845` (paid signup).
- `POST /signup` — 4 response shapes, **all HTTP 200** (`api/signup.py:166-190`). Rate-limited 10/hr/IP → 429 (`:89,104-108`). Idempotent per email.
- `GET /signup/complete` → `{user_id, token}`, one-time, wiped on read (`api/signup.py:222-235`; `src/appstate/customers.py:440-453`). Single indistinguishable 404 for never-paid / forged / already-retrieved.
- `GET /billing/status` → `{status, stripe_subscription_id, cancel_at, current_period_end, updated_at}` or `{"status":"not_configured"}` (`api/billing.py:133-165`).
- Free Bet Checks: `FREE_CHECK_LIFETIME_LIMIT = 3` (`src/appstate/freechecks.py:72`, verified), server-minted anonymous token, **not tied to an account**.
- Status codes: 401 (`api/auth.py:88,90,175`), 402 subscription_expired (`:124-127`, re-read), 402 free_checks_exhausted (`api/betcheck.py:263-280`), 503 provider not configured (`:85-86`), 429 (`api/signup.py:107-108`), 404 admin-when-unconfigured (`api/auth.py:166`).

---

## 2. PARTIAL — exists but constrained; say exactly how

| Capability | The exact constraint |
|---|---|
| **Multi-book consensus** | Requires `MIN_BOOKS = 6` (`src/analysis/prices.py:31`, verified). Below floor → `consensus: null` + `consensus_unavailable_reason`, board still renders raw prices. **This is live, not theoretical:** at the newest instant (2026-09-01T21:01:34Z) 27 games carry books `{11:15, 7:8, 6:1, 3:2, 2:1}` — **3 games below floor now**. Across the 39 committed boards: 11 books on 27 (69%), 7 on 8, 3 below floor. Across all 790 game-instants in the store: min 1, **median 8**, max 11; only 42% carry 11; **6.5% below floor**. Design a variable book count centered on 8 with a ~1-in-15 total-collapse state. "11 BOOKS SCANNED" is a ceiling. |
| **Price improvement** | Real, but **usually negative**. Across all 39 boards: only 8 (22%) have any side beating consensus; **8 of 72 side-values positive (11%)**; median −0.6 probability points; max +2.97. On the live slate: 3 of 15 games. Four in five heroes render a negative number plus `NO_IMPROVEMENT_NOTE`, ~60 words (`src/analysis/prices.py:41-48`). **Design that paragraph, not just the badge.** Wire field on the Quick view is renamed: `improvement_probability_points` (`src/analysis/gamepayload.py:279`, verified) — `improvement_points` is internal only. |
| **Board freshness** | Every price surface carries its capture instant (`prices.py:50-54`). But `/odds` **computes no stale verdict** — `DEFAULT_ODDS_MAX_AGE_S = 1800` exists (`src/appstate/freshness.py:69`) and is never applied there; the JS branch for it is dead (`web/js/odds.js:60-63`). Measured live: freshest board `age_seconds 2573.9` (~43 min) — already past threshold, shown raw with no flag. Cadence: median gap 15.0 min, max 608.7 min (10.1 h overnight), 4 of 31 gaps over 30 min. |
| **What Changed** | Renders. But on the deployed path it is **~96% lineup postings** — measured `/changed/2026-09-01` → 24 items: `lineup_posted` 23, `starter_scratch` 1, `transaction_first_seen` **0**. All 23 postings are tier `MEDIUM` with `basis: []` and the identical `tier_sentence: "relevance MEDIUM"` (`src/analysis/relevance.py:133-142`). Twenty-three visually identical cards. `game_id` and `market_reaction` always null. Player **IDs, not names** (`src/pipeline/briefing.py:278-283`). |
| **Ten-block Bet Check skeleton** | Ten blocks designed on the frozen artboard (`design/linehound-v1/LINEHOUND Gameday.dc.html`; `docs/VISUAL_ACCEPTANCE_TRACK1.md:19`); **five** rendered (`web/js/betcheck.js:9-13`, pinned `tests/test_web_structure.py:89-94,97`); WHAT CHANGED is nested as an `<h3>` inside BOTTOM LINE, not a peer block (`betcheck.js:164-167`). |
| **PRICE CHECK block** | Four independent collapse-to-null conditions, each with a stated reason routed into `bottom_line` (`src/analysis/betcheck.py:510-524,588-589`). Only three have regression tests. |
| **`thesis_support`** | Can be `[]`. `counterargument_lines` cannot. |
| **Detector coverage** | 11 registered (`src/detect/detectors.py:928-934`); 9 reachable in Bet Check — `thin_matchup_history` and `park_and_weather` emit `side=NEITHER` and are filtered out. All produce **0 findings in production** because their inputs are gaps. |
| **Everything computed but never served** | Starters (FIP/ERA/WHIP/K-BB%/IP, `src/pipeline/pitchers.py:294-350`), bullpen (`src/pipeline/bullpen.py:190-238`), travel (`src/pipeline/travel.py:96-133`), lineups + platoon + BvP (`src/pipeline/lineups.py:93-99,272-302,338-368`), weather (`src/providers/weather.py:163-170`), market de-vig section (`src/detect/dossier.py:203-244`), matchup depth (`src/analysis/matchup.py:429-453`). **Code real, CLI-only or gap-always, never on any HTTP endpoint.** |
| **Spreads / totals / F5** | Captured and shipped in the image — `data/processed/odds_snapshots.jsonl` = 2,931 rows (`totals` 978 / `spreads` 977 / `h2h` 976), 8 dates; `f5_close.jsonl` = 94 rows across 9 books. **No API endpoint reads either.** |
| **Support as recovery** | `POST /support` is the shipped account-recovery channel, built for "whose token expired before they used it" (`api/support.py:9-23,131-153`). Anonymous path requires an email. Nothing comes back into the product — the reply is email only (`docs/CUSTOMER_HELP.md:100-102`). |
| **Manual token delivery** | `#/signup/complete?token=RAW` renders a token with no Stripe session (`web/js/signup.js:109`; `web/js/main.js:24`). Real, undesigned, and the only non-curl way to deliver an admin-minted token. |
| **`#/billing`** | Exists but is **not in the nav** (`web/js/main.js:44-50`, verified: Today, Games, Check, Odds, Bets). The only in-app link is inside the 402 expired state (`web/js/dom.js:192`). A customer in good standing must type the hash. |
| **`cancel_at_period_end`** | The field that says renewal is stopped. `status` stays `"active"` for a scheduled cancel (`api/billing.py:275-277`). A UI reading `status` to answer "cancelled?" will be wrong. Under the null provider, `POST /billing/cancel` returns a `"canceled"` body that was **never persisted** (`src/appstate/billing.py:204-208`; `api/billing.py:265-266`). |

---

## 3. NOT AVAILABLE — must render as an explicit "not yet available" state, never estimated

Grouped by where a designer would be tempted to put it.

**Analysis / game data**
- Team W-L record — no `leagueRecord/wins/losses` in `src/providers/mlb.py`.
- Pitch mix, velocity — code exists on two paths (`src/providers/statcast.py`, `src/pipeline/rebuilt.py:287-351`); **store not in the image** (`data/historical/` is gitignored, `.gitignore:13`, and not copied by `deploy/Dockerfile:58-60`).
- **xwOBA** — dead field. `grep "est_woba"` returns exactly one line, `src/providers/statcast.py:66`, with no consumer. Every downstream number is actual wOBA.
- **xFIP** — deliberately absent (`src/pipeline/pitchers.py:22-30`, pinned `tests/test_pipeline_pitchers.py:201-205`).
- Wind direction / any wind interpretation — `orientation_deg` is `None` for all 30 parks by design (`src/data/parks.py:17-19`); detector emits `evidence=BLOCKED` (`src/detect/detectors.py:756-763`).
- Line-movement history endpoint — `snapshots.movement()` exists (`src/pipeline/snapshots.py:470`), callers are CLI only (`src/cli.py:1490,1507`); `grep movement api/` → nothing.
- `market_implied_consensus` / `has_market` with real values on HTTP — structurally always null/false.
- `sample_quality_warnings`, `baseline`, `market_relevance`, `detector`, `kind`, `surprise`, `side` on a Claim — dropped before the wire.
- `historical_support` = Moderate or Strong — thresholds require tier ≥3 (`src/analysis/betcheck.py:579-583`); **max reachable tier is 1** (`contracts.py:104-115`).
- `evidence_status` above tier 1 — "Exploratory"/"Historical support"/"Forward testing"/"Validated" defined (`contracts.py:117-126`), unreachable.
- Small-sample debunks in Bet Check — all three DEBUNK emitters are `side=NEITHER`.

**Odds / market**
- Second provider; Pinnacle / exchange / aggregator; non-US regions; player-prop prices; in-play odds as product.
- Multi-book spreads / totals / F5 on any endpoint.
- Book display names or logos; team full club names on the wire; `book_last_update` on the wire (zero hits repo-wide).
- Hold / vig %; closing-line value; a `freshness` or `stale` block on `/odds`; provider status on any customer endpoint.
- De-vig method choice — four implemented (`src/core/odds.py:205,209,214,249`), but `src/analysis/prices.py:95` calls `devig_two_way(away, home)` with no method. **Proportional is the only method on any customer path.**

**Account / commerce**
- `#/signin` route or sign-in screen — `grep -rn "signin" web/ api/` → **zero hits** (re-verified). The topbar token form is the entire mechanic (`web/js/main.js:79-110`, mounted `:167`, host `web/index.html:27`).
- Password / email-link / OAuth / Clerk login — `ClerkProvider` always raises (`src/appstate/authproviders.py:143-157`).
- `GET /me` / account page / own email / join date — not in the route inventory.
- Token renewal, expiry warning, refresh route.
- Server-side revoke or logout — `revoke_token` has zero non-test call sites and takes the raw token the server never stored (`src/appstate/users.py:306-314`).
- Suspend/unsuspend as a route.
- **Free Bet Check reachable from any UI** — `POST /betcheck/free` exists (`api/betcheck.py:283`) and **no client calls it**; `web/js/betcheck.js:221` posts to the paid `/betcheck`. Every "Try 3 Bet Checks free" CTA links to `#/signup`. Largest commerce gap.
- Cancel / reactivate / checkout controls in `web/` — `web/js/billing.js` (42 lines) only reads `/billing/status`.
- **Onboarding checklist UI** — `GET /onboarding` returns 4 steps (`token_redeemed, first_today_view, first_bet_check, first_saved_bet`) each `{complete, completed_at}` (`api/onboarding.py:22-31`); **zero client code calls it**.
- Admin invite-creation UI — curl only.
- Any transactional email — welcome, waitlist, receipt, token resend. `docs/RESEND_INTEGRATION_PLAN.md:1` is a draft.
- Payment reconciliation if the webhook never fires.
- Working checkout in a default deployment.
- Editing a saved bet (append-only by design); re-settle / correct a graded bet.
- **Reason text for an unsettled bet** — computed, never persisted (`src/appstate/settlement.py:193-196,207-210`). An unsettled row is three nulls with no explanation available to the UI.
- Record / ROI / units / streak / win-rate on My Bets — side-won grading only, no money math (`settlement.py:26-32`).
- `users.plan` as a meaningful field — never written outside tests; always `"none"`.
- Account/data deletion or 30-day retention — promised at `docs/CUSTOMER_HELP.md:91-92`, does not exist.
- Refund policy — **not decided**, explicitly forbidden to promise (`docs/CUSTOMER_HELP.md:44-46,61-65`), yet asserted live in `web/js/pricing.js:26`.
- Bet placement or sportsbook deep links — no URL field on `QuotedPrice` (`contracts.py:149-153`); `docs/API_CONTRACTS.md:449`: no bet-placement endpoint "ever."

---

## 4. HARD PROHIBITIONS — never show these

The system cannot produce them honestly. Each is enforced in code, not convention.

| Never show | Why | Anchor |
|---|---|---|
| **Model win probability / true probability / p(win)** | Not computed, read, or threaded anywhere. `grep "win_probability\|p_win\|true_probability" api/ src/analysis/` → **zero hits** (re-verified). | `src/analysis/betcheck.py:678-680` (re-read verbatim); `docs/API_CONTRACTS.md:27`; `src/analysis/gamepayload.py:33` |
| **Expected value / EV / edge** | `odds.edge()` is defined with **zero callers**. The one probability-vs-price comparison that ships is `price_improvement`, which carries a **mandatory label** saying it is execution price, **not EV and not a prediction**. | `src/core/odds.py:306`; `src/analysis/prices.py:33-34`; `contracts.py:189-208` |
| **A pick, "bet this", or any editorial verdict** | `recommendation: None` with a raising `__post_init__`. `bottom_line` is mechanically composed from four count shapes + a price clause + a permanent disclaimer. The canvas's editorial bottom line ("The pitching argument is real. The price is not.") cannot be produced. | `contracts.py:495,497-501` (re-read); `betcheck.py:586-633` |
| **Confidence score / strength meter / star rating** | No such field exists. The only strength vocabulary is the evidence ladder, and nothing reaches above tier 1. | `contracts.py:104-126` |
| **Hit rate, record, ROI, units, streak, win %** | Settlement is side-won only; counts exist in a batch return no endpoint exposes. | `src/appstate/settlement.py:26-32,215-220` |
| **Public betting %, sharp money, steam, line-movement arrows** | No such data captured. Movement series exists but is CLI-only and has no endpoint. | `grep movement api/` → nothing |
| **A bare rate or percentage without its sample** | Rule S: the constructor **refuses** a quantitative claim without `sample_n` + `sample_unit`. | `contracts.py:230-249`; `:9-12` |
| **"Since you last looked" / any personalized diff** | `__post_init__` raises if `personalized`. The fixed label is `"Nothing has changed since this morning."` | `contracts.py:308,576-577,585-588` |
| **"BELOW MARKET" as a badge** | Retired, semantically-inverted name for `your_price_beats_consensus`. Use the field's own polarity: `true` = customer's price is better. | `contracts.py:474-479` |
| **`MODERATE` / `STRONG` historical support** | Unreachable value **and** wrong word set (contract accepts Weak/Moderate/Strong; the canvas shows LIMITED·MODERATE·STRONG). | `betcheck.py:579-583`; `contracts.py:506-507` |
| **"UPDATED 32 SEC AGO"** | Bet Check payload has **no age field at all** (`grep "stale\|freshness\|age_seconds"` across the three modules → zero). Capture is hourly (`scripts/forward_capture.sh:2`), 4/hr in slate window; measured live age was 43 minutes. | `api/betcheck.py`, `src/analysis/betcheck.py`, `contracts.py` |
| **"7 PTS BETTER AT FANDUEL" as a hero number** | `_cents_delta` is consumed only inside `bottom_line` prose. It is not a field. | `betcheck.py:480-494,607-631` |
| **"OPEN AT FANDUEL" / any book link** | No URL field exists on any price object. | `contracts.py:149-153` |
| **A fixed "11 BOOKS" or "BEST OF 11 BOOKS"** | 42nd-percentile best case; median 8; 6.5% below the floor entirely. | `src/analysis/prices.py:31,140` |
| **Grouping evidence by team name** | **Side is a pointer, not a subject.** A sentence opening "NYY's starter…" can legitimately sit in the *counterargument* for an NYY bet — verified side-flips at `detectors.py:413,605-606,679,833,918`. Group by the `thesis_support` / `counterargument` arrays only. | as cited |
| **Refund terms, "cancel in one click", "confirmation emailed instantly", "no card required"** | All four are live copy the code contradicts. See §5 copy table. | `web/js/pricing.js:25-26`; `web/landing.html:92,372,381,469-470` |

---

## 5. EXACT VOCABULARY — field name → customer translation

**Enums (surface these values; never invent one)**

| Field | Real values | Customer translation |
|---|---|---|
| `verdict` | `"no_play"` (`src/pipeline/mismatch.py:131`) — the only value in production | "No demonstrated edge" — not "pass" or "avoid" |
| `side` | `"away"` / `"home"` / `null` (always `null` today) | which club the statement points at, **not** who it favors |
| `evidence_label` (on the wire, internal vocabulary) | `"observed"`, `"unproven"`, `"tested_null"`, `"blocked"`, `"historical_candidate"`, `"tuning_evidence"`, `"provisional"`, `"forward_testing"`, `"proven"` (`src/detect/base.py:45-57`; `synthesis.py:161`) | Map client-side via `contracts.py:102-128`: observed/unproven → **"Observation"** (tier 1, **no badge**); tested_null → **"Tested — did not hold up"** (tier 1, **badge**); blocked → **"Not available with our data"** (tier 0, no badge). **Tiers 2–5 are unreachable.** `customer_evidence` never reaches the wire (`_deep()` is bare `asdict`, `contracts.py:605-607`) — the client must do this mapping. |
| `evidence_status` (Bet Check block 09) | `"Observation"` — the only reachable value | keep as-is; this is the one canvas/code agreement |
| relevance `tier` | `LOW` / `MEDIUM` / `HIGH` / `UNKNOWN` — **UNKNOWN sits OUTSIDE the order** (`src/analysis/relevance.py:50-57`, re-read) | never render UNKNOWN as lowest; it means "cannot characterize," and it must never be averaged as zero |
| `settlement_status` | `"won"`, `"lost"`, `"push"`, `"void-unmatchable"`, **or three nulls = not settled yet** (`src/appstate/savedbets.py:71`, verified) | "Won" / "Lost" / "Push — game ended tied" / "Can't match this bet to a game" / "Not settled yet" |
| `settlement_reason` | written only for `push` (`"game ended tied (suspended, never resumed)"`) and `void-unmatchable` (`"side {side!r} does not name either club in {game}"`) — `src/analysis/../settlement.py:169-181` | for won/lost there is **no reason key**; for unsettled there is **no reason at all** |
| `user.status` | `invited`, `active`, `suspended`, `pending_payment`, `waitlisted` (`src/appstate/users.py:64-74`) | never exposed on a customer route today |
| `user.plan` | `"none"` / `"beta"` — **always `"none"`** in production | do not read |
| subscription `status` | `active`, `trialing` = entitled (`customers.py:246`); plus Stripe's others | **"cancelled?" is `cancel_at_period_end`, not `status`** |
| signup response `status` | `"waitlisted"` (dominant), `"error"`, or an echoed user status (`active`/`suspended`/`invited`); or a `checkout` object | see §6 Signup |
| `ChangeItem.category` | class string, else `event["class"]`, else the literal `"roster"` (`betcheck.py:647-649`) | |
| roster event classes | `transaction_first_seen`, `lineup_posted`, `hitter_scratch`, `starter_scratch` (`src/pipeline/rosterwatch.py:83-86`) | on the API path today: 96% `lineup_posted` |
| gap keys (all 12) | `teams, starters, weather, news, lineups, matchup_depth, bullpen, arsenals, travel, splits, matchup_history, market` | each carries its own reason string — render the reason, not the key |
| section keys (all 4) | `park, price_improvement, multibook_board, what_changed` | |

**Fields with a naming trap**

| Wire name | Trap |
|---|---|
| `improvement_probability_points` | the Quick-view name; `improvement_points` is internal only (`gamepayload.py:279`) |
| `market_consensus.implied_probability` | a **fraction in (0,1)**, not a percent |
| `market_implied_consensus` | deliberately named to mean "implied by the board at one instant," **not** who wins — and it is always `null` on HTTP |
| `your_price_beats_consensus` | `true` = customer's price is **better** |
| `consensus_unavailable_reason` | **key absent** with no board; present only when a board exists below floor |
| `board_summary.books` | count at one capture instant, not a store total |
| `spread_cents` | per-side cents of disagreement between books, **not** a point spread |
| `first_five` | a schedule flag from MLB (`src/providers/mlb.py:280`), unrelated to the F5 odds store |
| `capability_state` | dead constant, always `"REAL_TODAY"` — never varies |
| `not_an_edge` | verbatim string attached to every changed item (`relevance.py:80-83`; `gamepayload.py:380`) — surface it, do not paraphrase |

---

## 6. STATE MATRIX — what each state actually means per screen

### Gameday (`GET /games/{date}`, `#/games`)
| State | Real meaning |
|---|---|
| Loading | one fetch; `view-loading` hook already exists |
| Empty | `games_count` 0 → no MLB games that date. Distinct from a full slate of zero-finding cards. |
| **Default (not "empty")** | 15 cards, each `verdict: "no_play"`, `market_implied_consensus: null`, `data_quality.gaps` with 12 entries. The card's whole price content is `board_summary`. **This is the normal card.** |
| Stale | `board_summary.age_seconds` — no server verdict. If you draw a threshold, draw it client-side at 1800 s (`freshness.py:69`) and label it as your own. Overnight gaps reach 10.1 h. |
| Unavailable | `has_board: false` → `board_summary` fields null. Also means **unmatched club name** — boards drop rows whose club the translator does not recognize (`prices.py:249-251,270-271`); the payload cannot distinguish "never captured" from "name unmatched." Say "no price board recorded for this game," not "no odds." |
| Error | 401 (no/invalid token) → auth-required; 402 (`subscription_expired`) → billing (Stripe-gated, unreachable by default); 5xx generic |

### Game Quick (`GET /game/{date}/{away}/{home}` → `quick`)
`gamepayload.py:295-315` — 7 identity/verdict scalars (`game_id, away_team, home_team, verdict, side, market, summary`) + `headline` + `top_findings[]` + `price`. **No `venue`, no `first_pitch_utc`** — fetch them from the slate row or `advanced.game`.

| State | Real meaning |
|---|---|
| **Default** | `top_findings: []` on every game; `headline` is the constant no-edge sentence. Design the screen for zero statements plus one price block. |
| Populated | ≤5 ranked statements, each carrying its sample. Never render a statement without its `sample_n`/`sample_unit`. |
| Price present | `best_price`, `best_book`, `consensus_probability`, `improvement_probability_points`, `improvement_return_pct`. Improvement is **negative ~80% of the time** → the ~60-word `NO_IMPROVEMENT_NOTE` is the normal render. |
| Price unavailable | board below the 6-book floor or absent → the whole price block collapses with a stated reason |
| Stale / Error | same as Gameday |

### Game Advanced (`… → advanced`)
Keys: `game_id, away_team, home_team, game, verdict, side, market, summary, information_time, sections, gaps, findings, staleness` (`gamepayload.py:322-349`).

| State | Real meaning |
|---|---|
| **Default** | 4 sections, 12 gaps, 0 findings. **The gap ledger and the price block are the only content this screen has.** Design the ledger as the primary surface. |
| Unavailable | each gap carries its own reason string — render the reason. "Blocked" (evidence tier 0, `"Not available with our data"`) is a data gap, never a badge on the ladder. |
| Warning | `docs/API_CONTRACTS.md:65`: the dossier is "not yet a stable per-field contract; treat as opaque today." No test names any section. Any hand-built section template is unpinned and may break. Fields are added, never reshaped (`:8-14`). |

### Bet Check (`POST /betcheck`, `#/betcheck`)
| State | Real meaning |
|---|---|
| Pre-submit | five-field form. The shipped empty state reads `"Paste a bet to begin."` (`web/js/betcheck.js:209`) — **the form offers no paste affordance.** Fix the copy or build the parser (`parse()` at `betcheck.py:186` has no HTTP caller). |
| Loading | one POST |
| Success | ten designed blocks, five built. THE CASE / WATCH OUT statements are **2–4-line sentences** (e.g. `detectors.py:907-915`) — the six-word ceiling applies to **labels only** (`VISUAL_ACCEPTANCE_TRACK1.md:31`). |
| PRICE CHECK collapsed | 4 independent causes, each with its reason routed into `bottom_line` (`betcheck.py:510-524`). Below-floor board is one of them, ~6.5% of instants. |
| No counterarguments | **impossible** — `counterargument_lines` is never empty by constructor. `thesis_support` **can** be `[]`. |
| Unsupported market | `SUPPORTED_MARKETS` is moneyline only; 19 aliases refused **by name** (`betcheck.py:84-113`) — the refusal names the market, so say it. |
| 422 | price outside `100 ≤ \|price\| ≤ 100000` |
| 400 | non-ISO date |
| 404 | structured, **names the games searched** — render that list |
| 402 | `free_checks_exhausted` (`remaining`, `limit: 3`, `free_check_token` echoed **in the body only**, never a response header) — currently unreachable, nothing calls `/betcheck/free` |
| Stale | **no age field exists on this payload.** Never show a freshness number here. |

### Odds (`GET /odds/{date}`, `#/odds`, primary nav `web/js/main.js:47`)
| State | Real meaning |
|---|---|
| Loading | `view-loading` (`web/js/odds.js:39,116`) |
| Empty | 200 with `games_count: 0` |
| **Board variant A — full** | 11 books, consensus present. 69% of committed boards, 42% of instants. |
| **Board variant B — thin, consensus null** | 2–5 books. `consensus: null` + `consensus_unavailable_reason` **present**; board still renders raw prices. **Live today on 3 of 27 games.** First-class variant, not an edge case. |
| **Board variant C — no board** | `board_available: false`, `reason: NO_BOARD_REASON`, `board: []`, `best`/`consensus` null, and `consensus_unavailable_reason` **key absent**. Use `hasOwnProperty`. |
| Stale | `staleness.age_seconds` raw, `null` when unknown. **No `stale` flag, no `freshness` block, no `book_last_update`.** Live board measured at 43 min old with no flag. |
| Labels | book = raw key, team = abbrev. Every display name is frontend work that does not exist. |
| Error | 400 bad date / 404 / 502; auth 401, 402, or pass-through (three outcomes, `api/auth.py:88,120-127`) |
| Ties | `best.{side}.books` is an array — render **all** tying books, never one |

### My Bets (`GET|POST|DELETE /my-bets`, `#/mybets`)
| State | Real meaning |
|---|---|
| Empty | `"No saved bets yet."` / `"Save a bet from Bet Check to track it here."` — **the second line is aspirational**; Bet Check has no save action (`web/js/betcheck.js` has one `apiPost`, to `/betcheck`). |
| Rows | free text. `game` must be exactly `AWAY@HOME` and `side` `home`/`away` or a club abbrev optionally suffixed `ML`/`MONEYLINE` for grading to work (`settlement.py:70-82,109-127`) — the form does not enforce this. |
| Unsettled | three nulls, **no reason available**. Say "not settled yet" and nothing more. |
| Settled | `won`/`lost` carry **no reason**; `push`/`void-unmatchable` carry a fixed sentence. |
| Never | record, ROI, units, streak, win rate, or any money figure |
| Actions | Delete only (soft). **No edit path exists**, by design. |
| Error | 400 empty game/side; 422 bad price; 404 on delete of an unknown/foreign id; 429 on POST only (60/min) |

### Signup (`#/signup`, `POST /signup`)
All four outcomes are **HTTP 200** (`api/signup.py:166-190`) — never treat a non-200 as the branch discriminator.

| State | Real meaning |
|---|---|
| **Default outcome — waitlisted** | `{user_id, status: "waitlisted"}`. **This is the out-of-the-box path**, because `BILLING_PROVIDER` defaults to `"null"` (`billing.py:851`) regardless of Stripe env vars. Copy: `"You're on the waitlist. We'll email you when a beta spot opens up."` — **nothing sends that email.** Design a waitlist confirmation that promises nothing. |
| Checkout available | `{user_id, checkout:{status:"redirect", checkout_url}}` → "Continue to checkout". Stripe-configured deployments only. |
| Provider failed | `{user_id, status:"error", message:"checkout could not be started; try again shortly"}` — **has no client handler**, falls into the unrecognized-shape branch (`web/js/signup.js:79-84`). |
| Already registered | `{user_id, status: <"active"|"suspended"|"invited">}` |
| 429 | `{error:"rate_limited", retry_after}` — 10/hr/IP |
| 404 | `"Signup is not yet open."` |
| Signup complete | `"You're in"`, one-time raw token in `<code data-hook="signup-token">`, `"copy it now, it will not be shown again"` — **no copy button exists**. 404 covers never-paid / forged / already-retrieved indistinguishably; there is **no reconciliation path**, so the design must route to `POST /support`. |
| Price | `$19.99/mo`, `BETA_PLAN_PRICE_CENTS = 1999` (`billing.py:93-95`), mirrored `web/js/pricing.js:20-27` — the two must stay in sync. `billing_note` currently promises a 7-day refund that policy **forbids** promising. |

### Sign In
**The screen does not exist.** `grep -rn "signin" web/ api/` → zero hits (re-verified at HEAD). Two docs assert otherwise and are stale: `docs/VISUAL_ACCEPTANCE_TRACK1.md:52` and `design/linehound-v1/DESIGN_REQUEST_TRACK2.md:46`.

| What actually exists | Detail |
|---|---|
| The whole mechanic | a topbar `<input type="password" id="invite-token-input">` + "Save token" / "Clear token" + a `role="status"` region — `web/js/main.js:79-110`, mounted `:167`, host `web/index.html:27` inside `.app-topbar` |
| States | token absent (bare requests go out unauthenticated, `web/js/api.js:69-72`); `"Token saved."` (`main.js:101`); `"Token cleared."` (`:106`) |
| Unauthenticated | 401 → `renderAuthRequired` (`web/js/dom.js:167-180,209-211`), which dumps the raw API detail verbatim at `:176-178` |
| Expired | one 401 message covers missing/invalid/expired/revoked **deliberately** (`api/auth.py:88`) — the UI **cannot** tell the user which. There is no "your token expired" state and no renewal route. |
| "Log out" | client-side `clearToken()` only (`api/js/api.js:40-46`) — the credential stays live server-side until its 14-day TTL |
| Recovery | `POST /support` only |

---

### Two designer traps worth repeating
- **`design/linehound-v1/DESIGN_REQUEST_TRACK2.md:15-18`** describes the odds board as "8–11 US books, each with price + `book_last_update`; freshness metadata (observed_utc, stale/age_seconds)… spreads/totals captured." Three of those do not exist: `book_last_update` (zero hits repo-wide), a `stale` flag on `/odds`, and multi-book spreads/totals on any endpoint. Measured range is **2–11**, not 8–11.
- **`docs/CAPABILITY_RECONCILIATION.md:30`** ("auth, billing, deployment — none exist"), **`:27,61`** and **`docs/PRODUCT_DESIGN_HANDOFF.md:1098,2651`** (Statcast ingestion), **`:60,63,65`** ("starters / bullpen / context REAL TODAY"), and **`docs/LAUNCH_DECISIONS.md:139-142`** ("a canceled subscriber keeps access FOREVER") are all **stale at this HEAD**. The bullpen row in particular rests on `src/model/bullpen_grade.py`, which has **zero importers anywhere in the repo, tests included**.

No files were modified; nothing was committed or pushed.