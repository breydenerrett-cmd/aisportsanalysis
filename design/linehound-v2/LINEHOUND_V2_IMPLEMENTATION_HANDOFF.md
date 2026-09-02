> **AUDITED AT SHA `3dca767`. NOT CURRENT-PRODUCTION TRUTH.**
> Branch HEAD at push time was `cfe6bcb` (5 commits later, incl. a canvas-first frontend
> rebuild). Parent must reconcile against current HEAD before treating findings as
> authoritative. Two findings are already confirmed superseded — see
> `RECONCILIATION_REQUIRED.md`. No finding has been weakened or removed.

# LINEHOUND V2 — Implementation Handoff

Grounded against the engineering repo at HEAD `3dca767`, branch
`claude/sports-betting-analysis-review-g1o0co`, verified by a 10-agent adversarial read.
Companion files: `CAPABILITY_LEDGER.md` (the contract), `LINEHOUND_V2_DESIGN_PLAN.md`
(the plan), `CODEX_V2_PRINCIPLES.md` (benchmark notes).

**Do not modify Track 1 production files under `web/`.** This is design source of truth.

---

## 1. THE FIVE FACTS THAT SHOULD DRIVE IMPLEMENTATION ORDER

1. **Zero findings is the primary state.** `findings: []` and `top_findings: []` on 15/15
   live games; every game returns `verdict: "no_play"`. The real constant is
   `NO_EDGE_HEADLINE = "Interesting matchup, but no demonstrated betting edge."`
   (`src/analysis/synthesis.py:186`). Build this state first — it is the daily experience.
2. **Odds is the richest surface and is contract-tested.** `GET /odds/{date}` is pinned
   field-by-field in `docs/API_CONTRACTS.md:159-198` and covered by
   `tests/test_api_contracts.py:453-580`. Bind to it with confidence. Build it second.
3. **4 sections, 12 gaps.** All four API builders call `briefing.build_slate(games, store)`
   with zero enrichment kwargs (`api/games.py:115`, `api/today.py:122`, `api/digest.py:65`,
   `api/betcheck.py:180`) against a 17-parameter signature. The gap ledger IS the
   Advanced view.
4. **Every human label is missing.** Teams are abbreviations; books are raw provider keys.
   A display-name map is frontend work that does not exist yet — and is cheap, high-value.
5. **Commerce is inert by default.** `DEFAULT_BILLING_PROVIDER = "null"`
   (`src/appstate/billing.py:851`) → every signup waitlists regardless of Stripe env vars.
   402 `subscription_expired` is unreachable until Stripe is wired.

---

## 2. SCREEN → ENDPOINT → REAL FIELDS

| Screen | Endpoint | What it can actually render |
|---|---|---|
| Gameday | `GET /games/{date}` | `game_id, away_team, home_team, date, first_pitch_utc, venue, verdict, board_summary{books, observed_utc, age_seconds, has_board}, data_quality.gaps{12}`. `market_implied_consensus` is **always null** — dead field, do not bind. |
| Game Quick | `GET /game/{d}/{a}/{h}` → `quick` | `game_id, away_team, home_team, verdict, side, market, summary, headline, top_findings[], price{best_price, best_book, consensus_probability, improvement_probability_points, improvement_return_pct}`. **No venue, no first_pitch** — carry from the slate row. |
| Game Advanced | `… → advanced` | `sections{park, price_improvement, multibook_board, what_changed}` + `gaps{12, each with a reason}` + `findings[]` + `staleness`. Dossier is explicitly "opaque today" (`API_CONTRACTS.md:65`) — do not hand-build unpinned section templates. |
| Bet Check | `POST /betcheck` | `best_available_price{book, american_price, observed_utc}`, `market_consensus.implied_probability` (**fraction 0–1**), `price_improvement` + mandatory label, `your_price_beats_consensus`, `thesis_support[]` (can be empty), `counterargument_lines[]` (**never empty**), `evidence_status: "Observation"`, `bottom_line`, `recommendation: null` (permanent). |
| Odds | `GET /odds/{date}` | `games_count, widest_spread_game, books_disagree_on_favorite_count`; per game `markets.h2h{board_available, reason, board[{book, away_price, home_price, captured_at}], best{side:{price, books[]}}, consensus{…}|null, consensus_unavailable_reason, spread_cents, staleness}`. |
| My Bets | `GET/POST/DELETE /my-bets` | 8 fields: `id, game, side, price, saved_at, snapshot_digest, settlement_status, settlement_reason, settled_at`. Free text only. Append-only + soft delete. **No update path.** |
| Signup | `POST /signup`, `GET /signup/complete` | Four outcomes, **all HTTP 200**. Default is `waitlisted`. Complete returns a one-time `{user_id, token}`. |
| Access | topbar token form | One credential, 14-day TTL. **No `#/signin` route exists.** |

---

## 3. IMPLEMENTATION RULES THAT WILL BREAK IF IGNORED

1. `consensus_unavailable_reason` — the **key is absent** when there is no board at all;
   present only when a board exists below the 6-book floor. Use `hasOwnProperty`, never
   truthiness.
2. `best.{side}.books` is an **array of all tying books**. Render every one.
3. `market_consensus.implied_probability` is a **fraction in (0,1)**. Multiply for display.
4. `your_price_beats_consensus: true` means the customer's price is **better**. The old
   name `your_price_below_market` was semantically inverted and is retired.
5. `spread_cents` = cents of disagreement between books, **not** a point spread.
6. `counterargument_lines` is constructor-guaranteed non-empty; `thesis_support` is not.
   Design and code must both handle "support empty, counterargument present".
7. Any quantitative claim without `sample_n` + `sample_unit` **raises** in the constructor
   (`contracts.py:230-249`). Make `sample` a required prop on any rate-rendering component.
8. `recommendation` must never become a displayed pick — `__post_init__` raises if set.
9. Relevance tier `UNKNOWN` sits **outside** LOW/MEDIUM/HIGH. Never sort it lowest, never
   average it as zero.
10. `has_board: false` also occurs when a club name fails to match. Copy must read
    "no price board recorded for this game", never "no odds".
11. No server staleness verdict exists. Any stale threshold is a **client** decision —
    draw it at 1800 s (`freshness.py:69`) and label it as ours.
12. Bet Check has **no age field**. Never render freshness there.
13. Moneyline only. 19 other markets are refused **by name** — surface the name.

---

## 4. GAPS THAT ARE CHEAP AND HIGH-VALUE (recommended, not designed around)

- **Display-name map** for 11 book keys and MLB team abbreviations. Pure frontend, no
  backend change, and it removes the single most visible rawness in the product.
- **Wire `/betcheck/free`.** It exists (`api/betcheck.py:283`) and **no client calls it** —
  every "try 3 free" CTA currently routes to `#/signup`. This is the largest commerce gap.
- **Copy button** on the one-time activation code. It is shown once and there is no
  reconciliation path.
- **Onboarding checklist.** `GET /onboarding` returns 4 real steps and no client reads it.
- **Fix live copy the code contradicts**: refund promise (`web/js/pricing.js:26`),
  "cancel in one click", "no card required", "confirmation emailed instantly".

---

## 5. STALE DOCS — do not ground on these
- `docs/CAPABILITY_RECONCILIATION.md:30` ("auth, billing, deployment — none exist") is
  false at HEAD.
- `docs/PRODUCT_DESIGN_HANDOFF.md:60,63,65` ("starters / bullpen / context REAL TODAY").
  `src/model/bullpen_grade.py` has **zero importers repo-wide**.
- `docs/LAUNCH_DECISIONS.md:139-142` ("cancelled subscriber keeps access forever").
- `design/linehound-v1/DESIGN_REQUEST_TRACK2.md:15-18` — `book_last_update`, a `stale`
  flag on `/odds`, and multi-book spreads/totals **do not exist**. Range is 2–11, not 8–11.
- `docs/VISUAL_ACCEPTANCE_TRACK1.md:52` asserts a `#/signin` screen. It does not exist.

---

## 6. NUMERIC PROVENANCE AUDIT — every displayed figure must trace to a field

**Governing rule:** a number appears in an artboard only if an implementer can trace it to
a real field, or to a deterministic client-side calculation over fields actually received
*on that screen*. Every figure in the V2 artboards is **REPRESENTATIVE ARTBOARD CONTENT**,
bound at implementation time. **No figure ships as a literal.**

### The "what we checked" counter panel — audited at current HEAD

| Shown | Verdict | Source / action |
|---|---|---|
| **15 GAMES** | ✅ **REAL, date-dependent** | `games_count = len(game_odds)` (`src/analysis/oddspayload.py:311`); slate list length on the games feed. Bind at runtime — never literal 15. |
| **11 BOOKS** | ⚠️ **NOT a slate-level field** | The only real field is `board_summary.books`, which is **per game**, derived from the price-improvement dispersion (`src/analysis/gamepayload.py:150`). No slate-wide book count exists on any endpoint. Median 11, **min observed 5**. Either render per-game where that game's board is held, or relabel as a derived distinct-book count across tonight's boards and say so. If not derivable on the screen, **remove**. |
| **164 QUOTES** | ❌ **REMOVED from Gameday** | No slate-level quote total exists. Quotes are board rows inside each game's board on the **Odds** payload only (`src/analysis/betcheck.py:258-260`). The Gameday feed gives only `board_summary.books` per game, so a slate-wide quote total is **not derivable there** — printing it would invent a number. Legitimately derivable on the Odds screen as a client-side sum of rows actually received; label it as such. |
| **27 HYPOTHESES** | ⚠️ **Real number, wrong context** | Verified: V1 13 · V2 5 · V4 6 · V5 3 = 27 (`docs/RESUME.md:16`, `docs/OVERNIGHT_RUN.md:365`). But it is a **cumulative research-programme constant**, not tonight's work. Beside "15 games" it reads as a nightly count and misleads. Move to an evidence/methodology context, labelled a static constant kept in sync with the research docs — or drop. |

### Timestamps
**`PRICES CAPTURED 10:31pm ET`** — pattern is correct and honest, but the value is
**representative only**. Bind to the real `observed_utc` from
`best_available_price.observed_utc` (constructor-required,
`src/analysis/contracts.py:153,158`) or the board's `observed_utc`
(`contracts.py:555,561`), formatted client-side to the viewer's timezone.
**Never a static timestamp.** Sub-minute liveness claims remain prohibited — capture
cadence is 15–60 min and a live board measured ~81 minutes old.

### Everything else with a number
Same rule, per figure: prices, records, win pct, runs/game, sample `n`, book counts,
first pitch, free-checks remaining. Each binds to a named field. Anything whose source
cannot be named must come out of the design.
