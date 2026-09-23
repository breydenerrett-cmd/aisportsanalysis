# LINEHOUND — state of play, 2026-09-22

Handoff document. Written for someone (or some model) with zero prior context
who needs to know where the project stands, what is true, what is broken, and
what decisions are open. Every number here came from the repo, the ledgers or
the live site, not from memory.

Repo: `C:\Users\KC\Desktop\aisportsanalysis`
GitHub: `breydenerrett-cmd/aisportsanalysis`
Working branch: `claude/sports-betting-analysis-review-g1o0co` (all code and data)
Default branch: `claude/cowork-session-migration-tn3sx2` (workflow YAML only —
GitHub reads cron schedules from here, which has caused two separate outages)

---

## 1. What the product is

A sports-betting **analysis** subscription. It publishes picks before games,
grades every one in public including losses, and never places bets or holds
money. Repo rule, permanent: no bet-placement code, ever.

Owner: Brey. Stack: pure-stdlib Python `src/`, FastAPI `api/`, vanilla JS
`web/`, unittest only, GitHub Actions for all scheduled work, Fly.io hosting.

---

## 2. Live state

| Thing | State |
|---|---|
| Staging site | `https://linehound-staging.fly.dev` — live, all pages 0.2-0.6 s |
| Production `linehound.app` | **NOT live.** Domain bought, DNS not pointed, Fly app not created |
| Payments | Stripe built and tested (`src/appstate/billing.py`), **test mode only**. One plan: Founding access $19.99/mo, 7-day free trial. Owner was mid-Stripe-activation on 2026-09-22 |
| Customers | Zero |
| MLB | Public card. Regular season ends **2026-09-27** |
| NFL | Live, value rule (`NFL_CARD_V2`). 13 graded rows |
| UFC | Live, `UFC_CARD_V1`. 18 published rows, **none graded** — no results feed |
| Tennis | Research board only. No picks: results feed unsubscribed |
| NBA / NHL | "Coming soon" pages only |

### Records (verified 2026-09-22)

- **MLB card V1** (market-favourite rule, now retired to shadow): **68-35,
  +8.93 units over 12 graded days**, 103 picks. Every pick was a favourite;
  16 were priced at −200 or worse, which breaks the owner's own rule.
- **MLB card V2** (the value rule, registered 2026-09-22T14:35Z, public from
  2026-09-23): 0 graded. On its first live day it published **0 picks and 3
  labelled close calls** — nothing on the board met its bar.
- **NFL**: 13 rows across two rules. The retired favourites rule went 5-3 and
  **lost 1.03 units** on 2026-09-20 — the −950 and −400 prices ate it.
- **Research programme**: 47 pre-registered hypotheses, 37 read, **zero
  survivors**. Registry `data/research/alpha_registry.jsonl`.

### The honest position on edge

The repo's own document `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md` states: *"no
measurement has shown that it does, and five independent ones point the same
way."* The MLB team model beats a base rate by +0.004 nats. The prop model is
stronger (+0.0133 nats over 16,741 batter-games) but its disagreements with
the market lose money (−13.4% ROI vs a −9.1% control). A 68-35 record over 12
days has a 95% interval of roughly **[−5%, +21%] ROI** — encouraging, not
proof.

**Owner's instruction (2026-09-22):** show model numbers and edges confidently;
stop leading with self-deprecation. The line that must hold: never claim profit
is guaranteed or proven. That claim is what gets picks businesses dropped by
payment processors.

---

## 3. What shipped this week (2026-09-15 → 09-22)

998 commits, most automated captures. The substantive work:

**Outages found and fixed**
1. **Six days of capture loss** (09-15 → 09-21). One `git add` line with a
   missing path silently staged nothing. Every morning capture was written to
   a runner and destroyed. Fixed `scripts/capture_slot.sh`; a failed save now
   turns the job red.
2. **100 MB file wall** (09-21). `data/processed/odds_multibook.jsonl` crossed
   GitHub's per-file limit; every push was rejected for ~3 hours. Fixed with
   automatic gzip archive rotation (`src/pipeline/store_archive.py`) plus a
   size warning at 75 MB.
3. **The MLB engine was betting NFL games.** The odds store labelled every row
   "mlb"; 84 paper bets landed on NFL on 09-20 and blocked settlement. Fixed
   in `src/engine/glue.py`.
4. **Stale cache blinded the engine for a week.** A 09-15 cache entry scoped to
   the working branch shadowed every fresh daily save, because GitHub searches
   the run's own branch before the default branch. Deleted; test strategies
   started deciding again the same day.
5. **Site speed**: the main board took 15-18 s and sometimes 502'd. Now
   0.15 s, via date-windowed store reads, per-route caches and a background
   warm-up (`api/warmup.py`). Deploy checks now wait for the warm-up.

**Product**
6. **NFL value rule** `NFL_CARD_V2` registered — spreads/totals/moneylines
   that beat a leave-one-book-out consensus under three de-vig methods, never
   worse than −200. Replaced the favourites rule.
7. **UFC end to end**: capture, `UFC_CARD_V1` selector, manual results entry,
   publish/settle, web page, pre-registration. Four bugs caught in review
   (price averaging across even money, unwired cost probe, hourly cadence,
   unknown sport key).
8. **MLB value card V2 registered and switched on** for 2026-09-23, with a
   hard block on any −200-or-worse moneyline reaching a public ledger.
9. **Landing page rebuilt**: live record panel, no Bet Check marketing, no
   demo door, never features a −200 pick. Founding-price framing: the price
   moves with the public record and founding members keep theirs.
10. **7-day free trial** added to Stripe checkout, plus a real bug fix — every
    non-"active" status was treated as canceled, which would have locked out
    every trial user.
11. **Production deploy readiness**: `deploy-prod.yml` (dispatch-only, pinned
    checkout, its own token), hourly data refresh gated on green CI, and
    `docs/GO_LIVE_TOMORROW.md` with the owner's exact steps.

**Cost control**
12. Capture spend cut from ~1,575 to ~660 credits/day: 40-minute re-price
    cooldown with a guaranteed pre-lock capture, research derivatives paused,
    tennis capture paused while ungradable.

---

## 4. What is broken or unfinished

Ordered by how much it matters.

| # | Problem | Evidence |
|---|---|---|
| 1 | **Production does not exist.** Owner must create the Fly app, set keys, point DNS, dispatch the deploy | `docs/GO_LIVE_TOMORROW.md` |
| 2 | **Leave-one-book-out bug**: the best book is inside the consensus it is compared against, inflating every "beats the market" claim — **direction corrected 2026-09-23, see §4.1.1: it understates, not inflates** | `src/analysis/prices.py:146-181` |
| 3 | **Two live model inputs are stale**: pitcher logs end 09-07, bullpen logs end 09-06, while cards publish daily — **characterisation corrected 2026-09-23, see §4.1.4: root cause is a named resume-predicate bug, not simple neglect** | `data/historical/pitcher_logs.jsonl`, `bullpen_log.jsonl` |
| 4 | **The paid 2023-25 odds purchase is unreachable** — reader points at a directory the files were moved out of. Three seasons of backtest data, unusable | `src/board/l1_historical.py:154` vs `data/archive/historical/odds_history/` |
| 5 | **BALLDONTLIE harvest payloads are gone** — manifest claims 461 files / 115,649 rows; only `.cursor` files survive — **corrected 2026-09-23, see §4.1.2: they are not gone, they are GitHub release assets** | `data/historical/balldontlie/` |
| 6 | **Statcast ends 2024-09-30** while `src/engine/features.py:17` claims coverage through 2026. No 2025-26 pitch data exists — **corrected 2026-09-23, see §4.1.3: that date describes a stale local copy, not the live store** | `data/historical/statcast/manifest.json` |
| 7 | **UFC cannot grade itself** — no legal free results feed; results must be typed in by hand | `src/pipeline/ufc_results.py` |
| 8 | **Tennis cannot pick** — results feed implemented but tier unsubscribed (~$20/mo) | `src/providers/tennis_results.py:215`, `api/card.py:148` |
| 9 | **Search effort does not accumulate** across families/time; cross-family multiplicity correction exists in prose only | `docs/research_architecture/2026-09-17/VERIFIED_AUDIT_CORRECTIONS.md` H1 |
| 10 | **No free tier mechanism.** Access is binary at the router; no partial/preview payload, no blur UI anywhere | `api/app.py:87`, `api/app.py:64` comment |
| 11 | MLB engine paper strategies: 14 systems have 30+ selections but their falsification battery still reports NOT_RUN | daily-loop ESCALATE, `evidence/scorecards_v2.jsonl` |
| 12 | The STRONG confidence tier fires on 86% of picks; it was calibrated to be rare | daily-loop ESCALATE, `docs/INCIDENT_2026-09-10_STRONG_TIER.md` |

---

### 4.1 Corrections to items 2, 3, 5 and 6 above (verified 2026-09-23T00:14Z)

Four claims in the table above were re-checked and found wrong or
mischaracterised. **Root cause common to all four: each one was written from a
local working-tree read (this machine's checkout, or a git-ignored partial
copy on it) mistaken for the system's live state**, instead of from the
GitHub release, the default-branch workflow copy, or the actual GitHub
Actions run that the deployed product runs on. Environment this correction
pass was done from: branch `claude/sports-betting-analysis-review-g1o0co`,
HEAD `b525c54e` (0 ahead / 22 behind `origin/claude/sports-betting-analysis-review-g1o0co`,
all 22 routine automated capture/live-window/afternoon-slate commits, no
manual code changes); every file cited below as SOURCE-CODE VERIFIED was
diffed HEAD-vs-origin and is byte-identical on both. Labels: **SOURCE-CODE
VERIFIED** = read the code; **RUNTIME OBSERVED** = ran it / read a live log
and saw the behaviour; these are not interchangeable.

#### 4.1.1 Price-comparison bias runs the other way

**Claimed:** including the evaluated best book in its own reference
consensus *inflates* "beats the market" claims.

**True:** it *understates* them. `snapshot()` (`src/analysis/prices.py:152-154`)
averages the de-vigged fair probability of every quoting book, including the
best-priced one, into the consensus that best price is then measured against
(`:181`). Because the best-priced book's own fair number pulls the consensus
toward itself, the gap the module reports shrinks, not grows. Algebraically:
`improvement_INCL = ((n-1)/n)·improvement_EXCL − (1/n)·r·m_X/(1+m_X)` (r =
the price/margin term between the best book and the rest, m_X = the best
book's own margin) — the subtracted term means INCL is always ≤ (n-1)/n ×
EXCL, i.e. conservative/shrunk toward zero. In practice this is a 12-44%
understatement of the true edge, growing toward ~97% when the best book also
carries a high hold. Do not call the excluding (LOBO) reference "the true
probability" — it is LOBO-relative (leave-one-book-out), itself an estimate,
not ground truth.

`src/analysis/lobo_value.py` already does this correctly — "Fair price for
book B's quote = the mean, over every OTHER book quoting the same line...B is
never in its own consensus" (module docstring, confirmed by direct read) — and
is **not affected**. It backs the registered `NFL_CARD_V2` rule
(`src/analysis/nfl_value.py`) and the MLB value-shadow arm.

**Actual affected callers** (direct callers of `src/analysis/prices.py`'s
`snapshot()`/`by_matchup()`/`boards_by_matchup()`, confirmed by grep
2026-09-23): `src/analysis/betcheck.py`, `src/analysis/derivative_prices.py`,
`src/analysis/oddspayload.py`, `src/analysis/opportunities.py` (feeds
`priceverdict.value_points` — still true today, confirmed at
`opportunities.py:312-320`), `src/analysis/priceverdict.py`, `src/cli.py`,
`src/pipeline/briefing.py`, `src/pipeline/livefeed_mlb.py`,
`src/pipeline/live_window.py`, `src/report/card.py`, `src/report/clv.py`,
`src/report/ranker.py`, `src/report/tennis_board.py`, `api/odds.py`,
`scripts/backtest_card_rule.py`. The module's own docstring
(`prices.py:14-22`) already labels this "price improvement / line-shopping
value," explicitly not expected value or a predictive edge — the metric's
name was never the problem, only this document's claimed direction of bias.

Evidence tier: **SOURCE-CODE VERIFIED** (`src/analysis/prices.py:127-204`,
`src/analysis/lobo_value.py:1-40`, `src/analysis/opportunities.py:295-320`,
and the caller list above). Prior art:
`docs/research_architecture/2026-09-17/VERIFIED_AUDIT_CORRECTIONS.md` §N1
(2026-09-17) already recorded the correct direction ("shrinking measured
improvement toward zero... conservative in direction, but biased") — this
document's claim was a regression from that earlier, correct finding, not a
new discovery.

#### 4.1.2 BALLDONTLIE payloads are not gone

**Claimed:** manifest claims 461 files / 115,649 rows; only `.cursor` files
survive, i.e. the harvest was lost.

**True, in four separate parts:**
- **(a) What exists:** 959 assets on the GitHub release
  `balldontlie-harvest-2026-09` (created 2026-09-15T16:51:40Z), all
  `.jsonl.gz`, no duplicate names — **RUNTIME OBSERVED**,
  `gh release view balldontlie-harvest-2026-09 --json assets`, 2026-09-23.
  They were never meant to be in the working tree or git history; only
  `MANIFEST.json` and in-progress `.cursor` sidecars are committed
  (`.github/workflows/balldontlie-harvest.yml`'s own header comment).
- **(b) Which returned rows:** the repo's `data/historical/balldontlie/MANIFEST.json`
  is a narrower catalog than the release, not the full asset list: 461
  entries (429 `complete: true`, 32 `complete: false`); of those, 198 have
  `rows > 0` and 263 have `rows: 0` (empty or failed responses) — counted
  directly 2026-09-23, **data verified by direct read**. The 959-vs-461
  difference is two different units counting two different things: 959 =
  physical files stored on the release; 461 = entries the local manifest
  happens to log (mostly season-level games/rankings/tournament files) — many
  of the per-day/per-week odds-sweep files that were uploaded were never
  logged into `MANIFEST.json` at all. State both numbers with their units;
  neither alone is "the" count.
- **(c) Which fields are usable:** not verified this pass. The manifest's
  own schema per entry is `{bytes, complete, endpoint, file, harvested_utc,
  params, rows, sha256, sport}`; the per-row field content of the underlying
  `.jsonl.gz` payloads was not inspected, to avoid any bulk download beyond
  the single entitlement check in (d). **Not verified.**
- **(d) Entitlement / does a re-harvest need new spending:** `BALLDONTLIE_API_KEY`
  exists as a GitHub Actions repository secret, added **2026-09-21T03:42:54Z**
  — **RUNTIME OBSERVED**, `gh secret list` — one day before this audit and
  newer than the "secret not yet set" state recorded 2026-09-15. I could not
  personally confirm the key is live: it is not in the local `.env` (only
  `API_TENNIS_KEY` is present there), and the sanctioned cheap check — the
  `balldontlie-harvest` workflow's `mode: probe` input, "one cheap per-sport
  request to check rate-limit state" — is **not currently dispatchable**:
  `gh workflow run balldontlie-harvest.yml -f mode=probe` fails with `HTTP
  422: Unexpected inputs provided: ["mode"]`, because GitHub reads
  workflow_dispatch input schemas from the **default branch**
  (`claude/cowork-session-migration-tn3sx2`, HEAD `28cde3e5`), whose copy of
  this workflow predates the `mode` input added later on the working branch.
  Dispatching today with no `mode` would run the OLD workflow's unconditional
  full-harvest path, not a cheap probe, so I did not dispatch it — that would
  have been the bulk harvesting this task was told not to do. **This is a
  live, separate, blocking finding on its own**: the probe safety valve exists
  in the working tree but is not the copy GitHub actually runs. Net effect:
  entitlement is **not verified**. Do not write that a re-harvest "requires
  new spending" — a secret exists and may already be valid — but nobody has
  made the one cheap call that would confirm it, and the safe way to make
  that call is currently broken.

Prior art: `docs/audits/2026-09-17_algorithm_reopen/CONTRADICTION_LEDGER.md`
("CORRECTION, same day — C7 was nearly recorded as a fabricated manifest")
already caught and corrected this exact "gone" misreading on 2026-09-17 —
"It is not true, and the manifest is accurate... The data exists" — and
independently named the same root cause: "'Not where I looked' is not 'not
there'." This document's item 5 was a regression from that already-correct
finding, not a new discovery.

#### 4.1.3 Statcast is current, not stale

**Claimed:** the pitch store ends 2024-09-30; no 2025-26 pitch data exists.

**True:** 2024-09-30 is real, but it describes only this machine's
git-ignored, uncommitted, out-of-date local copy of `data/historical/statcast/`
(confirmed 2026-09-23: newest local file is
`pitches_2024-09-28..2024-09-30.jsonl.gz`; `.gitignore:13`,
`data/historical/*`, covers this whole directory including `manifest.json` —
**RUNTIME OBSERVED**, `git check-ignore -v`). The live/production store is a
different artifact:
- **RAW DATA**: seeded from the `data-seed/statcast` branch (committed
  2026-09-06; its tree runs through
  `pitches_2026-09-03..2026-09-05.jsonl.gz` — **SOURCE-CODE VERIFIED**, `git
  ls-tree origin/data-seed/statcast`), restored into every `daily-loop` run
  via `actions/cache` (`.github/workflows/daily-loop.yml:78-96`) and extended
  daily by `python3 -m src.cli statcast --catchup`
  (`scripts/daily_loop.sh:192-193`). Today's actual production run
  (`daily-loop` run `35738754285`, 2026-09-22T14:15Z) logged: `statcast
  catchup -- last covered before: 2026-09-21, through: 2026-09-21` — **RUNTIME
  OBSERVED**. The raw pitch store is current through 2026-09-21, one day
  behind the run.
- **REFRESHED FEATURES**: `src/engine/features.py`'s own docstring (lines
  12-22) already records that this was checked against the real store rather
  than assumed — "`data/historical/statcast/manifest.json` holds 180 four-day
  windows running 2023-03-30 through 2026-08-27" — and wires all seven of
  `src.research.matrix`'s numeric per-side columns, via
  `src.pipeline.rebuilt.accumulate`, on both the frozen 2023-24 replay era and
  the live 2025+ era. **SOURCE-CODE VERIFIED.**
- **ACTUAL MODEL CONSUMPTION**: the same production run's engine-slate step
  (`== engine slate (today, 2026-09-22) ==`, 14:15-14:27Z) executed its paper
  strategies against `PriceBlindSnapshot`s built through `glue.build_snapshot`,
  which carries the `build_features` output above. **RUNTIME OBSERVED, today.**
  This is the ENGINE's paper-strategy grading path, not the customer-facing
  MLB card probability — §5 below already correctly documents that the
  published MLB moneyline model (`src/analysis/strength.py`) uses ten numbers
  and does not read Statcast at all; that fact is separate and unaffected by
  this correction.

One concrete source-to-forecast path was verified end to end today: raw
Statcast pitch store (current through 2026-09-21) → `rebuilt.accumulate` →
`engine/features.py build_features` (source-verified wiring) →
`glue.build_snapshot` → `PriceBlindSnapshot.features` → engine-slate
paper-strategy evaluation for 2026-09-22 (runtime-observed in today's log).

#### 4.1.4 Pitcher/bullpen logs: a named bug, not neglect

**Claimed:** two live model inputs are stale (pitcher logs end 09-07,
bullpen logs end 09-06) while cards publish daily.

**True:** the dates for the *local repo copies* are accurate — confirmed
2026-09-23 by direct read: `data/historical/pitcher_logs.jsonl` max date
2026-09-07 (25,023 lines), `data/historical/bullpen_log.jsonl` max date
2026-09-06 (59,808 lines). But the deployed job does not read this local
copy: `daily-loop.yml`'s "Restore historical + processed data cache" step
(lines 78-96) restores a separate, larger GitHub Actions cache copy of both
files — today's run reported "720 in store, 28505 appearances" for pitchers,
versus 25,023 lines in the local file. **The real defect is a resume/refresh
predicate bug in `src/pipeline/pitchers.py`'s `build_log_store()`** (another
worker is repairing this file; described here, not edited). Its own
docstring (lines 129-168) names it precisely: the legacy
`resume=True, refresh=False` contract's `_has_season()` check treats ANY
single cached row for the season — including an empty "not yet debuted"
marker — as done forever, so a starter activated later, or who simply makes
a later start, is never refetched again. Documented in-code as "the bug
found 2026-09-22... '0 pitchers fetched' for five straight daily runs since
2026-09-19." A `refresh=True` mode (freshness-marker based, `_coverage_marker`
/ `_marker_is_stale`, ~20h TTL) has since been added and is wired at the live
call site (`src/cli.py:2053`). I independently reproduced the symptom today:
the same production run (`35738754285`, 2026-09-22T14:15Z) logged `[3/9]
refresh pitcher logs for 2026 → 0 pitcher(s) fetched, 720 in store, 28505
appearances` and `[4/9] refresh bullpen appearances for 2026-09-21 → 0
appearance(s) from 0 game(s)` — i.e. even with the refresh-mode fix wired in,
today's run still fetched nothing. That may be a legitimate no-op (nothing
past the 20h TTL yet) or a residual bug in the staleness predicate; not
diagnosed further here since another worker owns the fix. Do not
characterise this as simple neglect — it is a specific, named,
actively-being-repaired resume-predicate defect, and the deployed store is
larger (28,505 appearances) than the local repo file alone would suggest.

Evidence tier for 4.1.4: **RUNTIME OBSERVED** (today's `daily-loop` run log)
+ direct read of the local data files + **SOURCE-CODE VERIFIED**
(`src/pipeline/pitchers.py`, read-only).

---

## 5. The analysis-depth audit (the live question)

Brey's judgement on 2026-09-22: the analysis "feels like you look at a couple
of factors and call it good", and it must be deep enough to justify $5,000/mo.
Three independent explorations of the codebase confirmed he is right.

**The MLB moneyline model uses exactly ten numbers per game**
(`src/analysis/strength.py:299-363`): each team's runs scored and allowed per
game, games played, each starter's FIP / innings / IP per start, each
bullpen's relief rate, and league runs per game.

**Collected, paid for, or computed — and feeding no probability:**

- **Park factors** — `src/pipeline/parkfactors.py:86` exists and is
  point-in-time correct. `strength.py:363` defaults park to 1.0 because
  nothing passes it. The model's own comment: *"Coors Field is priced like
  Petco."* This is why game totals are switched off
  (`src/report/card.py:725 TOTALS_ON_CARD = False`).
- **Weather** — 19,756 forecast rows including wind bearing on every row.
  `src/detect/detectors.py:704`: *"used by nothing."*
- **Lineups** — ignored by the team model. *"A club resting four regulars is
  priced as its season self."*
- **Statcast** — 1,432,440 pitches. Reaches research features only, never a
  published probability.
- **Umpires** — captured daily (1,276 rows); used only to emit a timestamp.
  No strike-zone or run-environment tendency exists anywhere.
- **Injuries (NFL)** — fetched by `src/providers/nfl.py:309`, read by nothing.
- **NFL EPA team ratings + win probability** — `src/analysis/nfl_strength.py`
  computes them, `api/games.py:322` serves them, **no web page renders them.**
- **The dossier** — `src/detect/dossier.py` assembles 15+ sections with 11
  detectors per MLB game (bullpen workload, platoon mismatch, travel load,
  park and weather, pitch-mix mismatch...). It is real analysis, it is served
  at `/game/{date}/{away}/{home}`, and it feeds **no probability and no pick**.

**Markets with no model at all:** team totals, first five innings (captured
and priced only), pitcher strikeouts, and every UFC market beyond moneyline.

**What genuinely does not exist** and would have to be collected: catcher
framing, park orientation (0 of 30 parks), third-time-through-order, per-
reliever availability, line-movement features, market microstructure (limits,
ticket/handle), fighter statistics of any kind, tennis player form data.

**The honest summary:** the depth Brey wants is roughly half-built and
disconnected. The fastest path to real depth is wiring what already exists
into the probabilities, not inventing new machinery.

---

## 6. Money

**Costs today:** The Odds API $59/mo (100,000 credits) + Fly hosting ~$25-45/mo.
BALLDONTLIE status unverified — the code documents a 48-hour trial, not a paid
plan, and its tennis endpoints return 401.

**Credits:** 900/day envelope, 5,000 hard floor, ~4,300 usable until an assumed
~10-01 reset. Spend was cut to ~660/day. MLB's season ending on 09-27 removes
most of the demand.

**Decided 2026-09-22:** spend nothing more until there is revenue. UFC results
get typed in by hand. Tennis grading (~$20/mo) waits.

**Prices:** Founding access $19.99/mo, 7-day free trial, price rises with the
public record, founding members grandfathered. Tiers beyond this are designed
but not built (`docs/PER_SPORT_PRICING_PLAN.md`).

---

## 7. Open decisions

1. **Finish Stripe activation and go live.** Steps in
   `docs/GO_LIVE_TOMORROW.md`: activate Stripe (individual/sole proprietor is
   fine, no LLC needed to start), create the $19.99 product, create the Fly app,
   set secrets, add 2 DNS records, dispatch the deploy. ~30 minutes.
   Risk: Stripe may refuse a betting-picks business; Whop is the fallback.
2. **Tier ladder.** Proposed but unapproved: free account (limited preview),
   ~$9.99 one sport picks-only, $19.99 one sport full, ~$39.99 all sports,
   ~$99 pro. Needs per-sport entitlements, which do not exist yet.
3. **The free tier / blurred paywall.** Not built. Needs a preview seam in
   `api/` (no partial payload exists today) and blur UI in `web/js/`. This is
   the thing Brey believes drives signups.
4. **Deep-analysis scope.** Owner wants every market in every sport, every day.
   The realistic order, given the data: MLB (wire park/weather/lineups, turn
   totals back on), NFL (render the model that already exists, add injuries),
   UFC (needs fighter data from scratch), tennis (needs the feed), soccer (needs
   capture + a goals model). Soccer and tennis have the highest event volume,
   which is what makes graded proof accumulate fastest.
5. **Whether to buy back the broken assets**: re-running the BALLDONTLIE
   harvest and repointing the odds-history reader would restore three seasons
   of backtest data for ~$0 (harvest) and one small code fix.
6. **LLC and business banking** — optional now, worth doing before revenue
   grows. Personal/sole proprietor is fine for launch. Note: a California LLC
   carries an $800/year minimum tax.

---

## 8. The week plan that was being designed

Two design agents were mapping a 7-day autonomous build when the session ended;
their output was lost. The intended shape, for whoever picks it up:

- **Day 1 — foundations**: fix the stale inputs, repoint the odds archive, fix
  the leave-one-book-out bug, feed park factors into the run model, catch
  Statcast up, and publish an audit of every analysis input and whether
  anything reads it.
- **Day 2 — MLB depth**: park + weather + lineups into the run model; build
  first-five and team-total models off the same distribution; recalibrate the
  prop model where it is overconfident; turn totals back on under a registered
  rule.
- **Day 3 — NFL depth**: render the EPA model that already exists, add
  injuries, rest and weather, build spread/total/team-total reads.
- **Day 4 — UFC depth**: fighter database, rating model, method and round
  markets, grading path.
- **Day 5 — tennis and soccer**: the two highest-volume sports; surface-adjusted
  ratings for tennis, a goals model for soccer.
- **Day 6 — product**: the per-market deep-read payload, the free tier with
  blurred previews, tiers.
- **Day 7 — evidence**: cross-family multiplicity accounting, live CLV per
  sport, and a nightly automated self-critique of every graded pick.

Every new rule must be pre-registered before it publishes, graded forward, and
its losers published. That is not optional caution; it is the product's entire
differentiator.

---

## 9. Rules that must not be broken

From `CLAUDE.md` and `docs/RESEARCH_CATALOGUE.md`:

- Pre-registration before evaluation. Published losers. No rescue by threshold
  change. Point-in-time correctness.
- 2023-24 is discovery. **2025 is tuning-only forever. 2026-01-01 to 08-27 is
  sealed.** Forward proof starts 2026-08-28.
- No real-money betting or bet placement, ever.
- No moneyline at −200 or worse on any public card (owner, 09-20 and 09-22).
- Never advertise Bet Check (owner, 09-22).
- Never claim a proven edge or guaranteed profit.

---

## 10. Where to look first

```
docs/reports/2026-09-21_WHERE_WE_ARE.md     the long status report
docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md   sports + pricing plan
docs/GO_LIVE_TOMORROW.md                    the owner's launch steps
docs/launch/LAUNCH_KIT.md                   launch copy and 7-day push
docs/DOES_THE_MODEL_BEAT_THE_MARKET.md      the honest evidence position
docs/PREREG_CARD_V2.md                      the live MLB rule, registered
docs/PER_SPORT_PRICING_PLAN.md              per-sport pricing design
src/analysis/strength.py                    the MLB model (ten inputs)
src/detect/dossier.py                       the deep analysis that feeds nothing
src/analysis/nfl_strength.py                the NFL model nothing renders
src/capture/budget.py                       credit rules
```
