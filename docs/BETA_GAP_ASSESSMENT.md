# Beta gap assessment (recon, 2026-09-06 23:2xZ)

Read-only inventory of the customer surface (`api/app.py`, `web/`) against the owner's beta requirements. Produced by a Haiku recon worker, checked by the orchestrator; file:line pointers are as of 16a2b97. Status words: PRESENT / PARTIAL / MISSING.


## 1. ROUTE INVENTORY

| Method | Path | Purpose | Data Stores |
|--------|------|---------|-------------|
| GET | `/health` | Health check, no auth | (none) |
| GET | `/today` | Today's slate as JSON (authed/paid) | `src/pipeline/history` (git-tracked results), MLB schedule (live fetch) |
| GET | `/games/{date}` | Slate list + verdicts for a date (authed/paid) | MLB schedule (live), `history.read_results()` (git-tracked) |
| GET | `/game/{date}/{away}/{home}` | One game quick+advanced views (authed/paid) | MLB schedule (live), results store |
| GET | `/changed/{date}` | What Changed band for date (authed/paid) | MLB schedule, dossier detections |
| GET | `/odds/{date}` | Full board for slate (authed/paid) | MLB schedule, `data/processed/odds_multibook.jsonl` (baked into image) |
| GET | `/odds/{date}/{away}/{home}` | One game's board (authed/paid) | Same odds store |
| POST | `/betcheck` | Bet Check analysis (authed/paid) | MLB schedule, odds store, dossier |
| POST | `/betcheck/free` | Free Bet Check (anonymous, 3 lifetime) | Same + `src/appstate/freechecks.py` (in-memory budget) |
| GET | `/my-bets` | Saved bets list (authed) | `APP_DB_PATH=/app/data/app/app.db` (persistent SQLite) |
| POST | `/my-bets` | Save a bet (authed) | Same SQLite |
| DELETE | `/my-bets/{bet_id}` | Delete saved bet (authed) | Same SQLite |
| GET | `/digest` | Personal digest (authed) | Slate + user-scoped data |
| POST | `/funnel/event` | Analytics beacon (public) | `src/appstate/events.py` record (optional, fire-and-forget) |
| POST | `/support` | Support message (anonymous) | SQLite support table |
| GET | `/admin/support` | Support list (admin) | SQLite support table |
| POST | `/admin/support/{id}/status` | Mark support resolved (admin) | Same |
| POST | `/signup` | Register account (public) | SQLite users table |
| GET | `/signup/complete` | Stripe checkout success (public) | SQLite |
| POST | `/billing/checkout` | Start Stripe checkout (authed) | SQLite, Stripe API (live) |
| GET | `/billing/status` | Subscription status (authed) | SQLite billing record |
| POST | `/billing/cancel` | Cancel subscription (authed) | SQLite, Stripe API |
| POST | `/billing/reactivate` | Reactivate subscription (authed) | SQLite, Stripe API |
| POST | `/billing/webhook` | Stripe webhook (public) | SQLite, Stripe event |
| POST | `/admin/invites` | Mint invite token (admin, disabled until APP_ADMIN_TOKEN set) | SQLite users table |
| GET | `/admin/overview` | Admin dashboard (admin) | SQLite aggregates |
| GET | `/admin/users` | Admin user list (admin) | SQLite users |
| GET | `/admin/funnel` | Funnel analytics (admin) | `events.py` recorded data |
| GET | `/onboarding` | Post-signup form (authed) | (none) |
| GET | `/meta` | Static metadata (public) | Static JSON responses |
| GET | `/web` / `/web/{path}` | Serve index.html and assets (public) | Files from `web/` directory (baked into image) |

**Data Store Summary:**
- **Git-tracked, baked into image:** `data/processed/odds_multibook.jsonl` (multi-book price history), `src/pipeline/history` (past results)
- **Live/computed:** MLB schedule (fetched each request), dossier analyses
- **Persistent (volume-mounted):** SQLite at `/app/data/app/app.db` for users, billing, support, saved bets
- **In-memory only:** Free check budget (`freechecks.py`), rate limit counters

---

## 2. SCREEN INVENTORY

| Screen | Route(s) | API Calls Made | Purpose |
|--------|----------|----------------|---------|
| **Today (Gameday V2)** | `#/today` | `GET /today`, `GET /games/{date}`, `GET /odds/{date}`, `GET /changed/{date}` | Featured hero verdict (no_play/flagged/unavailable), featured bet carousel, slate rail, What Changed band |
| **Odds Board** | `#/odds/{date}` | `GET /odds/{date}`, `GET /odds/{date}/{away}/{home}` (via hash nav) | Full moneyline market board, per-book quotes, consensus, spread_cents, stale flags, game-specific detail |
| **Games / Slate List** | `#/games/{date}` | `GET /games/{date}`, `GET /odds/{date}` (optional fallback) | Slate grid with tile cards, verdicts, game navigation |
| **Game Quick View** | `#/game/{date}/{away}/{home}` | `GET /game/{date}/{away}/{home}` | Team records, probable starters, verdict, price panels, price standing spotlight (Featured Bet) |
| **Game Advanced** | `#/game/{date}/{away}/{home}` (toggled) | Same as Quick, no extra fetch | Coverage ledger (11 gap reasons), book-vs-book table, matchup history, splits, lineups, starters (all marked absent/unavailable as applicable) |
| **Bet Check** | `#/betcheck` | `POST /betcheck` (authed/paid) or `POST /betcheck/free` (anonymous) | 10-block skeleton: THE BET, THE MARKET, THE CASE, COUNTERARGUMENT, [WHAT CHANGED, HISTORICAL SUPPORT, EVIDENCE, SIMILAR BETS, YOUR HISTORY — all NOT YET AVAILABLE], BOTTOM LINE |
| **My Bets** | `#/mybets` | `GET /my-bets`, `POST /my-bets`, `DELETE /my-bets/{id}` | Saved-bet table: game, side, price, settlement status, closing price |
| **Landing / Signin** | `landing.html`, `#/signin` | `POST /funnel/event` (analytics only), `POST /signup`, `POST /billing/checkout` | Token entry, signup form, 3-free-check offer, Stripe checkout link |

---

## 3. REQUIREMENT MATRIX

### SLATE ITEMS (Gameday, Odds, Games screens)

| Feature | Status | Evidence | Notes |
|---------|--------|----------|-------|
| **Matchup** | PRESENT | `web/js/today.js:309-352` (matchup context panel), `web/js/odds.js:405-412` (game card matchup) | Away @ Home displayed with team badges and full names |
| **Market (board available)** | PRESENT | `web/js/odds.js:114-120` (boardVariant), tables throughout | Three variants: full (consensus available), thin (<6 books), no-board (unavailable) |
| **Book/Consensus** | PRESENT | `web/js/odds.js:199-230` (consensusPanel) | De-vigged consensus with implied probability shown as percentage; displayed per-side |
| **Available Price** | PRESENT | `web/js/odds.js:175-192` (bestPanel), price cells | Best price across all books tied, with book count |
| **Implied Probability** | PRESENT | `web/js/odds.js:214-216`, `web/js/betcheck.js:~369` | Formatted as consensus share percentage (e.g., "52%"), never as a probability claim |
| **De-vig Probability** | PRESENT | `web/js/odds.js:201` | Same as "implied probability" above; derived from consensus via standard de-vigging |
| **Model Probability** | MISSING | No endpoint carries a model win probability field; deliberately omitted per handoff | `web/js/today.js:20-23` docstring: "dossier not a stable contract, omitted" |
| **Edge** | PARTIAL | `web/js/today.js:154-162` (pointsBetter), `web/js/betcheck.js:~369-374` | Gap against consensus shown as "PTS BETTER" (line-shopping value); never phrased as EV or edge |
| **Expected Value** | MISSING | No EV field in contracts; forbidden boundary ("never compute... edge") | By design per `web/js/featuredbet.js:46` and `web/js/betcheck.js:97` docstrings |
| **Evidence/Confidence Tier** | PARTIAL | `web/js/betcheck.js:~365-370` (`evidence_status` shown as "Observation" always) | Only tier is "Observation"; no real tiers tied to data yet |
| **Market Depth** | PRESENT | `web/js/odds.js:421-422` (book count per game), `web/js/today.js:209-212` (deepest/thinnest) | Real per-game book count displayed; slate aggregates on Today screen |
| **Last Updated / Freshness** | PRESENT | `web/js/odds.js:425-432` ("CAPTURED {time} · {age}"), `web/js/today.js:533-537` | Absolute time + relative age (minutes/hours/days); stale flag at 30 minutes (odds.js:75) |
| **Key Reasons** | PARTIAL | `web/js/today.js:301-345` (price context panel); no team/matchup detail shown | Price context (best vs consensus) only; full team records/splits on Game screen, not here |
| **Warnings** | PRESENT | `web/js/odds.js:245-268` (thin alert for <6 books), `web/js/today.js:570-612` (no board amber) | Amber panels for thin boards ("no consensus") and no-board states |
| **Status (play/no_play/pending/settled)** | PRESENT | `web/js/today.js:615-629` (verdict rendering: no_play, flagged, market_unavailable) | Three verdict states rendered as hero panels; no_play is 93% (hardcoded per ledger, not live) |
| **Filter/Rank Controls** | MISSING | No sort/filter UI on any slate screen (Odds, Games, Today); tiles are chronological | Per handoff: earliest-game fallback when no gap exists |

### BET CHECK ITEMS

| Field | Status | Evidence | Notes |
|-------|--------|----------|-------|
| **What the bet is** | PRESENT | `web/js/betcheck.js:212-225` (block 01 THE BET, renders query.raw) | Bet query parsed into: game, side, price; all three fields shown in panel |
| **Current Price** | PRESENT | `web/js/betcheck.js:~360-374` (block 02 THE MARKET) | Best available price + all competing books tied |
| **Implied Probability** | PRESENT | `web/js/betcheck.js:~369` | Consensus implied probability as percentage |
| **Model Probability** | MISSING | No field on POST /betcheck contract (see `web/js/featuredbet.js:44-69` docstring) | Never computed here; would be uncalibrated anyway |
| **Estimated Edge** | MISSING | `price_improvement.label` shown instead (line-shopping, not EV) | `web/js/betcheck.js:84-86` docstring: "never 'edge', never 'EV'" |
| **Fair Price** | PRESENT | `web/js/betcheck.js:~369` (consensus implied_price shown as American) | De-vigged consensus price displayed as American format |
| **Confidence/Evidence** | PRESENT | `web/js/betcheck.js:~365-370` (evidence_status, "Observation" only today) | Always "Observation" tier; no real tiers yet |
| **Supporting Factors** | PRESENT | `web/js/betcheck.js:231-255` (block 03 THE CASE, thesis_support claims) | Real `thesis_support` claims rendered with sample_n when present; empty state honest |
| **Risks** | PRESENT | `web/js/betcheck.js:261-288` (block 04 COUNTERARGUMENT, never empty) | Constructor-enforced non-empty; either real claims or padding string |
| **Book Disagreement** | MISSING | No per-book comparison on POST /betcheck response; only best-price + consensus | Would require raw board for each book; not in contract |
| **Good/Fair/Bad Price Statement** | PARTIAL | `web/js/betcheck.js:~369-374` (price_improvement.label shown as verdict text) | One line from API (`price_improvement.label`); honest but minimal |
| **Verdict Word** | PARTIAL | Featured Bet card shows "STRONG VALUE" / "VALUE" / "LEAN" / "FAIR PRICE" / "PASS" / "OVERPRICED" / "FADE ALERT" / "INSUFFICIENT DATA" — but only if priceStanding is supplied | `web/js/featuredbet.js:~270-300` renders verdict when present; usually NOT AVAILABLE on POST /betcheck (see module docstring) |

### PERFORMANCE ITEMS (My Bets screen only)

| Feature | Status | Evidence | Notes |
|---------|--------|----------|-------|
| **Historical Paper Picks List** | PRESENT | `web/js/mybets.js:70-124` (renderBetsTable) | User-saved bets table with columns: Game, Side, Price, Saved, Settlement, Closing price |
| **W/L/Push** | PRESENT | `web/js/mybets.js:101-103` (settlement_status in table) | `renderUnknown()` displays status + reason when resolved |
| **ROI** | MISSING | No ROI computation in My Bets table | Would require comparing price taken vs closing price; could be computed client-side but isn't |
| **Odds** | PRESENT | `web/js/mybets.js:96-98` (price column shows american format) | American price taken shown |
| **CLV** | MISSING | No closing line value shown; only closing price (absolute, not vs bet price) | `web/js/mybets.js:16-27` (formatClosingLine) renders closing price and when captured, never a CLV |
| **Calibration** | MISSING | No historical win% by confidence tier or other calibration plot | No endpoint or data for this |
| **Running Bankroll** | MISSING | No bankroll tracker anywhere on the product | No endpoint, no persistent tracking |
| **Drawdown** | MISSING | No drawdown chart | No endpoint |
| **Reasoning Outcome** | MISSING | No link between "what the bet check said" and "what actually happened" | No post-settlement analysis screen |

### TRUST ITEMS

| Feature | Status | Evidence | Notes |
|---------|--------|----------|-------|
| **Timestamps on Data** | PRESENT | `web/js/odds.js:425-432` (captured_at), `web/js/today.js:533-537` (observed_utc) | ISO timestamps shown for every board; displayed as ET clock |
| **Freshness Indicator** | PRESENT | `web/js/odds.js:75` (STALE_AFTER_SECONDS = 1800), `web/js/today.js:226-237` (ageNoSeconds) | "OUR 30-MINUTE THRESHOLD" flag on old rows; relative age (MIN/HR/DAY AGO) |
| **Demo/Historical Replay Labeling** | MISSING | Landing page offers "3 Bet Checks, no card" but no "demo mode" label; free checks are real analysis, not replay | By design: free tier is the real product, not a degraded preview |
| **"Probabilistic Decision Support, Not Guaranteed Profit" Disclaimer** | PARTIAL | `web/js/odds.js:469-470` (disclaimer on board: "Comparison only. No sportsbook link...") | One line on Odds screen; no prominent disclaimer on Gameday or Bet Check |
| **Empty/No-Opportunity State Copy** | PRESENT | `web/js/states.js:148-179` (renderEmptySlate), `web/js/today.js:859-872` | "No games to show tonight", "Nothing has moved yet", "Nothing scheduled" — honest absence statements |

---

## 4. PLACEHOLDER / HARDCODED / "COMING SOON" SURFACE

| Item | File:Line | Text | Status |
|------|-----------|------|--------|
| Forward ledger stats | `web/js/today.js:289-293` | "27 hypotheses pre-registered across this product's V1-V5 research record, zero surviving. Static constant, not tonight's count." | HARDCODED – deliberate per docstring (closed research record, not live data) |
| No_play percentage | `web/js/today.js:11-12` | "93.0% of forward-ledger entries" | HARDCODED – from research record, same as above |
| Min books for consensus | `web/js/featuredbet.js:109` | `const MIN_BOOKS = 6` | HARDCODED – mirrors `src/analysis/prices.py`, repeated for caption only |
| Betcheck input placeholders | `web/js/betcheck.js:697-704` | `placeholder: "SD"`, `placeholder: "CIN"`, `placeholder: "-140"` | SAMPLE HINTS – form field examples, not data |
| NOT YET AVAILABLE blocks | `web/js/betcheck.js:21-25` (blocks 05, 06, 08, 09) | "WHAT CHANGED", "HISTORICAL SUPPORT", "SIMILAR BETS", "YOUR HISTORY" | BY DESIGN – five of ten blocks are placeholder slots (no backing field in contract) |
| Stale after threshold | `web/js/odds.js:75` | `STALE_AFTER_SECONDS = 1800` | CLIENT DECISION – labeled as "OUR 30-MINUTE THRESHOLD", not a server verdict |
| Board freshness detail disclosure | `web/js/today.js:937-945` | Folded `<details>` panel with raw staleness fields | HONEST DETAIL – open-when-clicked; never fabricated |

---

## 5. SUMMARY OF GAPS FOR ORCHESTRATOR

**Missing entirely:**
- Model win probabilities (deliberately; model is uncalibrated)
- EV/edge calculations (forbidden boundary)
- Performance history beyond settle status (no CLV, ROI, calibration, drawdown, bankroll)
- Per-book price comparison in Bet Check
- Historical paper-pick analysis linking reasoning to outcome
- Any "Good Price" / "Bad Price" verdict on Bet Check (usually NOT AVAILABLE unless priceStanding supplied externally)

**Partial / honest-absence implementation:**
- Confidence tiers: only "Observation" tier exists today (fixture, not real)
- Filtering/ranking on slates: none (earliest fallback, no user controls)
- Matchup detail: team records/starters on Game screen only, explicitly omitted from Today screen per handoff rule
- Verdict words: only rendered if priceStanding supplied (Post /betcheck has no board to compute rank from)

**Present and accurate:**
- Market board availability (three variants: full/thin/no-board)
- Freshness timestamps and age indicators
- Best prices and tied books
- De-vigged consensus prices and implied probabilities
- Thesis support and counterargument claims with samples
- Settlement status on saved bets
- Honest empty-state copy throughout

**Hardcoded constants (safe, not fabricated):**
- "27 hypotheses pre-registered" (research record closure, documented as static)
- 93.0% no_play rate (from ledger, documented as not-tonight's-count)
- 30-minute stale threshold (client decision, labeled as ours)

---

**All screens honor the core principle:** never invent a probability, a rating, a rank, or an edge. When data does not exist to fill a contracted field, the screen renders that field's honest-absence state (NOT AVAILABLE, NOT YET AVAILABLE, or omitted entirely), never a placeholder.
