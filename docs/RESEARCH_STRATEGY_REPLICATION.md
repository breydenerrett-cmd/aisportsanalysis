# Research lane: Strategy Replication

**Status: DESIGN DOCUMENT ONLY. Nothing registered, nothing evaluated, no data
read for outcomes.** This document proposes a lane; it does not open one.
Pre-registration of any shortlisted family still requires its own document and
Fable review before a single row is read against results, per standing rule.

**Opened:** 2026-08-31 (renumbered 2026-09-01 in session), following V1/V2/V4/V5
(all zero survivors) and the EvoLab Phase 2B null (`BELOW_PLACEBO_CEILING`,
docs/EVOLAB_PHASE2B_RESULTS.md). Read against docs/RESEARCH_CATALOGUE.md so
nothing refuted gets re-proposed under a new name.

## Why this lane, and why now

V1 asked "do we know baseball better than the market" (no). V2 asked "does the
market misprice its own structure" (no, four-of-five ways, one false positive
caught by the battery). V4/V5 asked "does a smarter feature combination survive"
(no). EvoLab asked "does a huge automated search over this same feature space
find anything a placebo world doesn't find more of" (no — the real max sat
*below the median* of three placebo generators).

Strategy replication asks a different, narrower question: **do the specific,
publicly documented strategies that retail bettors, forums and academic papers
actually claim work, in fact replicate inside our frozen machinery on our own
2023–24 data?** This is not a new mechanism hunt — it deliberately does not
invent anything. Its value is independent of the answer:

- If something replicates, it is validated by a battery already proven capable
  of catching a false positive (F1/M3) that a naive test would have shipped.
- If nothing replicates — the base-rate-consistent, expected outcome — the
  product gets an honest, evidence-backed answer to "have you tried the famous
  strategies", which no other lane produces, because V1–V5 are our own
  inventions, not the market's canon.

## Standing rules this lane inherits, unchanged

2023 screen / 2024 replication; FDR (BH q=0.10) over the full pre-registered
family, whatever its size; falsification battery (RULES_VERSION 2.0.0, frozen,
docs/VALIDATION_GATE.md) on every survivor; 1pp effect floor; date-clustered
CIs; losers published in full; 2025 tuning-only; 2026-01-01..2026-08-27 sealed,
untouched, one look ever, after Stage 5 freeze + Brey's go; no rescue by
threshold change; no recycling of anything in RETIRED or TESTED_NULL under a
new name. Line-shopping value is PRICE IMPROVEMENT, never EV — irrelevant to
mechanism claims here but restated because this lane will touch execution
framing (e.g. "beat the closing number") where the distinction is easy to blur.

---

## 1. Source inventory

Public strategies live in four tiers of citability. Grade reflects whether the
claim is precise enough to encode without inventing a rule the source didn't
state.

| tier | source | grade | notes |
|---|---|---|---|
| Academic | Sung & Johnson, *Do profitable wagering strategies indicate an inefficient market? ... MLB moneyline markets*, Applied Economics 57(34), 2025 — 1,547 simple strategies, 1999–2016, 2.46% profitable at 5%, 0.45% at 1% | **A** | Already cited in docs/RESEARCH_V2.md and docs/RESEARCH_CATALOGUE.md (RETIRED T1). This paper is the base-rate anchor for the whole lane (§5), not a source of new candidates — its *families* (see below) are what's citable, not a strategy list we have access to. |
| Academic | *Inefficient Forecasts at the Sportsbook: An Analysis of Real-Time Betting Line Movement*, Management Science 70(12), 2024 (3,681 MLB games) | **A** — already exhausted | Produced V2's M1 (line reversal, TESTED_NULL/N13) and M2 (weekend day-game staleness, BLOCKED/B2). Both already run or blocked. Nothing new to extract for this lane. |
| Betting-forum canon | "Fade the public" — bet the side receiving the minority of ticket count/handle | **B** (precise mechanism, blocked data) | Requires public bet percentages/handle splits. See BLOCKED. |
| Betting-forum canon | Reverse line movement (RLM) — line moves against the side receiving majority of tickets, read as sharp money | **B** (precise mechanism, blocked data) | Same missing feed as fade-the-public; RLM is the price-side detector version of the same idea. Already listed BLOCKED/B1 in the catalogue with the same reasoning ("inferring public sentiment from price alone invents the data"). Restated here, not re-derived, per the cross-reference rule. |
| Betting-forum canon | Home underdog systems (e.g. "home dogs +100 to +150 have positive ROI"; division home dogs after a loss) — sourced from public system-selling sites (docs/sports/betting angle blogs, no peer review) | **C** (encodable, low-trust source) | Precise enough to encode (price band × home/away × situational filter) entirely from odds + schedule data we hold. No public handle data needed. The claimed mechanism ("public overvalues favorites," favorite-longshot bias) is a real, separately-documented market phenomenon (see M5 in V2, N12 — de-vig divergence measures exactly this) but the *specific system's* numbers are unaudited, cherry-picked-window claims from commercial tout sites, not a controlled study. |
| Betting-forum canon | Unders on low-ticket-percentage games ("unders under 20% of tickets have hit ~54% since 2005 in division games") | **D** (mechanism entangled with blocked data) | The claimed edge is defined *by* the missing ticket-percentage feed; without it there is nothing left to encode except "bet unders," which is not the strategy. BLOCKED. |
| Betting-forum canon | Situational angles: getaway-day fatigue, series-finale letdown/look-ahead, day-game-after-night-game, revenge-game narratives | **C** (encodable, mechanism-thin) | All fully encodable from schedule + odds data alone (no missing feed). All are close cousins of V1's `travel_load` (N6, TESTED_NULL, +0.38pp p=.85) and the situational-fatigue family the catalogue's Lesson 2 already generalizes ("the market absorbs season-level and schedule-level features, all of them, so far"). "Revenge game" and "letdown spot" carry no falsifiable mechanism beyond narrative — R9's standing rule ("no stated mechanism survived being written down") applies directly. |
| Betting-forum canon | Umpire strike-zone tendency → totals (large/small zone umpires shift run environment) | **B** (mechanism real, feed unverified) | Already BLOCKED/B10 in the catalogue ("source not yet verified") — restated, not new. |
| Published tipster methodology | Public "expert consensus" / most-picked-side sites (e.g. aggregated tout pick percentages) | **D** | Self-attested picks, no verifiable settlement history independent of the tout's own claims — this is exactly the class T5 already closed ("tout past picks are self-attested"). Excluded outright, not shortlisted. |
| Book-buying-behavior heuristic | Closing-line-value (CLV) literature as a *strategy target* rather than a measurement (Miller & Davidow, *Sharp Sports Betting*; industry consensus that beating the close predicts long-run profitability) | **A/B mixed** | This is not a standalone bettable strategy — it is a validity criterion the forward ledger (L3, docs/RESEARCH_CATALOGUE.md) already uses. Noted here only to exclude it from the candidate list: CLV is an evaluation method, not a mechanism, and registering "beat the close" as a hypothesis with no stated mechanism for *why* would be exactly the R9 violation. |

### Cross-reference to refuted/blocked entries (exclusions, explicit)

The following are excluded from candidacy because the catalogue already
resolved them:

- **Reverse line movement / fade-the-public / any contrarian-on-handle
  family** — BLOCKED/B1, missing public betting percentages, "retracted as
  incoherent" if inferred from price. Not re-proposed.
- **Weekend day-game staleness** — BLOCKED/B2 (M2), ran, inconclusive on too
  few qualifying games; already the exact strategy from the Management Science
  paper. Not re-proposed as new; if it resolves it resolves through B2's own
  path (dense forward snapshot grid), not through this lane.
- **Cross-book-outlier / stale-book strategies** — TESTED_NULL (N7, +0.03pp
  p=.97) and TESTED_FALSE_POSITIVE (F1/M3, the canonical case). Any forum
  variant of "bet the outlier book" is this family under a new name. Excluded.
- **Travel/fatigue detectors** — TESTED_NULL (N6, travel_load). Getaway-day and
  fatigue framing is this family with schedule-position substituted for
  distance; same market absorption expected, noted in the table above rather
  than shortlisted.
- **Umpire zone size** — BLOCKED/B10, unverified source, unchanged status.
- **Season-level feature combinations generally** — RETIRED/T2, standing bar:
  needs a mechanism the market plausibly *cannot* price. Home-dog and
  situational-angle systems do not meet this bar on their face (see §3).
- **Tout consensus / published-pick methodologies as a data source** —
  RETIRED/T5, self-attested, not independently verifiable.
- **Line reversal / autocorrelation strategies** — TESTED_NULL (N13/M1), wrong
  sign, dies on granularity per its own honest caveat. Not re-proposed.

---

## 2. Encodability test

For each surviving (non-excluded) candidate, the question is whether it can be
built entirely from data we point-in-time-verifiably hold: multibook boards
(3x/day historical, denser forward), lineups, transactions, and the pitch
store. Read-only row counts, checked for this document only (no outcomes
read):

| store | rows (as of this check) | point-in-time status |
|---|---|---|
| `data/historical/odds_history/mlb_2023.jsonl` | 600 event-date shards (2,491 events per docs/RESEARCH_V2.md header) | PIT-validated (VALIDATION_GATE check 5) |
| `data/historical/odds_history/mlb_2024.jsonl` | 600 event-date shards | same |
| `data/historical/odds_first_five/mlb_{2023,2024}.jsonl` | 265 / 189 | thin, per B3's 308-game F5 sample discussion |
| `data/historical/lineups.jsonl` | 4,892 | date-only granularity (RETIRED/B5: "a transaction DATE is never treated as a TIME") |
| `data/historical/transactions.jsonl` | 26,893 | day-only granularity, same B5 limitation |
| Statcast pitch store (`data/historical/statcast*`) | 2,737,968 pitch rows (per docs/DEBRIEF.md, rebuilt with `bb_type`) | rebuilt PIT, 0 failed windows |

Feeds we do **not** have, verified by absence from the store list and by the
catalogue's own BLOCKED entries:

- **Public bet percentages / handle splits** (any book, any source) — not in
  any store, no vendor integrated. Confirmed absent by directory scan; nothing
  named "handle", "tickets", or "public_pct" exists under `data/`.
- **Live in-game prices** — the odds stores are pre-game snapshots only
  (3x/day historical cadence); no in-play feed exists (B14, "Phase 4 live
  infrastructure" not yet built).
- **Umpire assignment feed** — not in any store (B10).
- **Roof-state feed** — not in any store (B6/B8).

### Encodability verdicts

| candidate | needs | verdict |
|---|---|---|
| Home underdog price-band systems | odds history only | **ENCODABLE** |
| Getaway-day / schedule-fatigue angles | odds history + schedule (game_pk/date sequencing, already in results store) | **ENCODABLE** |
| Series-finale letdown/look-ahead | odds history + schedule position (series game number, next-opponent identity) | **ENCODABLE**, mechanism-thin (see §3) |
| Day-game-after-night-game | odds history + start-time metadata (already in odds/schedule stores) | **ENCODABLE** |
| Umpire zone size → totals | umpire assignment feed | **BLOCKED** — no feed |
| Fade-the-public / RLM / handle-conditioned unders | public betting percentages | **BLOCKED** — no feed (restated from B1) |
| Tout consensus following | independently verifiable tout settlement history | **BLOCKED** — no verifiable source exists (T5) |
| CLV-as-strategy | n/a — not a mechanism | **EXCLUDED**, not a candidate (see §1) |

### BLOCKED list (this lane), with exact missing feed

| id | strategy | missing feed | disposition |
|---|---|---|---|
| SR-B1 | Fade the public / bet-percentage-weighted contrarian plays | Public bet percentage or handle-split feed, any book | Same gap as catalogue B1; no new vendor identified during this design pass. Stays blocked. |
| SR-B2 | Reverse line movement (price-based inference of the above) | Same — inferring "public side" from price movement alone is the retracted move the catalogue already rejected | Stays blocked, not reopened. |
| SR-B3 | Handle-conditioned unders (e.g. "unders <20% tickets") | Public bet percentage feed | Stays blocked (subset of SR-B1). |
| SR-B4 | Umpire zone size → totals angle | Umpire assignment feed with historical zone-size stats, none integrated | Stays blocked, same as catalogue B10. |
| SR-B5 | Any live/in-game strategy replication (e.g. "buy back after a lead") | Live in-game price feed | Blocked; same gap as B14. |
| SR-B6 | Tout/"expert consensus" following | Independently verifiable settlement history for any tout service | Permanently excluded, not merely blocked — no such feed can exist by the nature of self-attested picks (T5 reasoning applies without qualification). |

---

## 3. Coverage-ranked candidate shortlist (V4-style ranking)

Ranked on: usable n (2023+2024 combined, before any screen), PIT completeness,
mechanism quality (does the source state *why* it should work, and could the
market plausibly fail to price it), direction definable before results are
read, and uniqueness vs. every refuted family above. This is a feature-side
ranking only — no outcome has been read for any row below.

| rank | id | strategy | usable n (approx, odds-covered games) | PIT completeness | mechanism quality | direction pre-definable | uniqueness vs. refuted | net read |
|---|---|---|---|---|---|---|---|---|
| 1 | SR1 | **Home underdog, moneyline price band +100 to +150** | ~full 2-season odds coverage (thousands of games; exact n at registration) | Full — odds history only | Medium — favorite-longshot bias is independently documented (V2's M5/N12 measured the de-vig divergence directly; this is a live, real market phenomenon, just not yet tested as a *trading* rule at this exact band) | Yes — direction (back the dog) fixed by the source, band fixed before any read | High — no prior family bet on price-band-conditioned home dogs; genuinely different from V1's baseball-knowledge features and V2's structural-pricing features | Best candidate: real, named mechanism (bettor overpricing of favorites) with independent internal corroboration from N12, cleanly encodable, one clean price-band rule |
| 2 | SR2 | **Division home underdog, moneyline** (same mechanism, narrower slice: divisional matchups only) | Subset of SR1, roughly 1/6 to 1/4 of games depending on schedule balance | Full | Medium — same as SR1, claimed reasoning is familiarity/rivalry compressing lines, unstated why divisional specifically differs from the general home-dog effect | Yes | Medium — overlaps SR1's mechanism; registered as a *sub-hypothesis* of the same family rather than a separate mechanism, to avoid denominator inflation the catalogue's R1 warns against | Only worth registering jointly with SR1 as one family testing the general effect and the divisional subgroup as a pre-specified interaction, not as two independent bets on the same mechanism |
| 3 | SR3 | **Day game after night game — home team price drift/fade** | Large (any game following a night game the previous day for the same home team) | Full — start-time + date sequencing already in odds/schedule stores | Low-medium — fatigue mechanism, close cousin of V1's `travel_load` (N6, TESTED_NULL) which already tested a fatigue-adjacent mechanism and found +0.38pp, p=.85 | Yes | Low-medium — closely related family to a tested null; registering it tests whether *this specific* schedule fatigue channel differs from travel fatigue, which is a narrower and defensible claim, but expectations should be calibrated by N6 | Encodable and clean, but goes in with a pre-registered LOW prior exactly as V2's M3 did, given N6's adjacency |
| 4 | SR4 | **Series-finale, team down 0-2, "desperation" moneyline lean** | Moderate — only 3-game or 4-game series' final games where a team trails, roughly 15-20% of series | Full — series position and cumulative series record derivable from schedule + results | Low — mechanism is narrative ("plays starters harder," "must win") not measured; the V1/V4 lesson is that mechanism-free products earn nothing (R9) | Yes, but weakly — direction (back the trailing team) is stated by the source but not derived from any measured quantity | Medium — schedule-position framing is new, but mechanism quality is R9-shaped | Marginal; include in the top-3 pre-registration templates only if SR1-SR3 need a fourth for FDR power reasons, otherwise demote |
| 5 | SR5 | **Getaway-day (travel day following) — road team fade** | Large — any getaway-day road game | Full | Low — same fatigue-narrative issue as SR3/SR4, and directly overlaps N6's already-tested mechanism (travel) | Yes | Low — this is closer to a re-cut of N6 (travel_load) than a new idea; risks being T8's "no rescue by threshold/redefinition change" in spirit even though it's a different detector | Lowest-ranked encodable candidate; borderline re-litigating a TESTED_NULL under new framing — flag for Fable review specifically on this point before registering |
| — | SR6 | Weekend day-game staleness (M2's exact test, wider net) | Same as B2 | Full for the loose test; strict test underpowered (B2 already documented) | High — directly from the Management Science paper's own finding | Already defined | None — this is not a new candidate, it is B2 continuing on its existing forward-collection path | **Not part of this shortlist** — belongs to L2/B2's existing lane, listed here only to explain why it is not re-proposed |
| — | SR7 | Cross-book dispersion re-cut at a different threshold or on totals-only | n/a | n/a | n/a | n/a | **None** | **Excluded outright** — T8 forbids rescue by threshold change; this is F1/M3 with new dressing |
| — | SR8 | "Revenge game" / narrative angles generally | Large | Full | None stated | No — "back the team that lost last time" has no source-stated mechanism strong enough to fix a direction | None | **Excluded at ranking** (R9-shaped: no mechanism survives being written down) |

**Top-3 for pre-registration (§4): SR1 (with SR2 as a nested sub-hypothesis),
SR3.** SR4 and SR5 are named and ranked but not drafted in full — both carry
either R9 mechanism-thinness (SR4) or near-duplication of a TESTED_NULL (SR5,
N6), and drafting fewer, better hypotheses avoids inflating the family
denominator the catalogue explicitly warns against (Lesson elsewhere: "R1 ...
pure denominator inflation"). If Fable wants a fourth or fifth registered
hypothesis for FDR power, SR4 is the next in line, drafted the same way, with
its mechanism weakness stated up front rather than discovered at the battery.

---

## 4. Pre-registration templates (drafted, NOT registered)

These are templates only. No family file exists, no hash is frozen, and no row
has been read against outcomes. Registration requires a separate act (a frozen
spec file, as V4/V5 did) plus Fable review before any evaluation begins.

### Template A — SR1/SR2: Home underdog price-band effect

- **Rationale.** Favorite-longshot bias (bettors overpay for favorites,
  underpay for dogs) is a well-documented market phenomenon in horse racing and
  sports betting broadly, and V2's M5 (N12) already measured that de-vig
  methods diverge specifically on lopsided prices in our own data — i.e., the
  raw ingredient this strategy claims to exploit is independently present.
  What has never been tested is whether that divergence, combined with home
  field advantage, is large enough and one-directional enough to be
  profitable at a specific price band, as forum "system" sites claim.
- **Exact feature/rule.** Home team is priced as an underdog (American odds
  between +100 and +150 inclusive, at the recommendation-time consensus
  price) → back the home team, moneyline. Sub-hypothesis (nested, not a
  separate family member): the same rule restricted to divisional matchups.
- **Direction.** Back the home underdog. Fixed by the source before any read.
- **Market.** MLB moneyline (h2h), full game.
- **Sample gate.** Minimum 30 qualifying selections per season per
  sub-hypothesis (consistent with N8's floor rule); expected n is large
  (home dogs in this band occur regularly across a season) so the gate is not
  expected to bind, but is stated in advance regardless.
- **Effect floor.** +1pp over de-vigged consensus implied probability
  (standing floor), date-clustered 95% CI must exclude zero.
- **Replication criterion.** 2023 screen, 2024 replication; both years must
  agree in sign; BH-FDR q=0.10 applied over this family jointly with Template
  B (and Template C if drafted).
- **Falsification criteria (battery, RULES_VERSION 2.0.0).** Team
  concentration (no small set of clubs carrying the effect), book
  concentration (survives leave-one-out across books), season-split
  stability, dose-response if a price sub-band gradient is claimed (it is
  not, for the base rule — flat band, no gradient claimed, so dose-response
  is not applicable and will be marked as such rather than force-fit),
  extreme-date removal.
- **Pre-registered prior, stated now.** MEDIUM-LOW. The mechanism is real
  (N12 shows the divergence exists) but N12 did not test whether trading the
  divergence is profitable — it tested calibration, not ROI — and the
  catalogue's Lesson 2 (the market absorbs essentially everything tested so
  far) argues for caution. Recorded before any look, per the M3 precedent of
  stating priors early so a positive gets extra scrutiny.

### Template B — SR3: Day-game-after-night-game home price drift

- **Rationale.** Forum claim: a home team playing a day game the day after a
  night game is undervalued by the market because bettors do not price
  short-rest fatigue for the *home* club specifically (most fatigue framing in
  public content focuses on the road team). This is adjacent to, but distinct
  from, N6's travel-distance fatigue detector.
- **Exact feature/rule.** Home team played a night game (start time ≥ 18:00
  local) the previous calendar day, and today's game starts before 16:00
  local → back the home team, moneyline.
- **Direction.** Back the home team. Fixed by source before any read.
- **Market.** MLB moneyline (h2h), full game.
- **Sample gate.** 30 selections per season minimum.
- **Effect floor.** +1pp, date-clustered CI excludes zero.
- **Replication + falsification.** Identical structure to Template A: 2023
  screen / 2024 replication / joint FDR / full battery.
- **Pre-registered prior, stated now.** LOW. This is a schedule-fatigue
  mechanism and N6 (travel_load, a different but adjacent fatigue channel)
  already came back flat (+0.38pp, p=.85) with no sign consistency across
  seasons in other V4/V5 families. Recorded now, before any read, exactly as
  V2 recorded a low prior for M3 given N7.

### Template C — SR4: Series-finale desperation lean (drafted, deprioritized)

- **Rationale.** Forum claim: a team trailing 0-2 (or more) in a series plays
  its final game with elevated effort/bullpen usage the market does not fully
  price.
- **Exact feature/rule.** Team is 0-2 or worse in a 3+ game series entering
  the series' final game → back that team, moneyline.
- **Direction.** Back the trailing team. Stated by source, not derived from
  any measured quantity — this is the template's acknowledged weakness.
- **Market/sample/effect floor/replication/falsification.** Same structure as
  A and B.
- **Pre-registered prior, stated now.** LOW-TO-NONE. No mechanism survives
  being written down beyond "they'll try harder," which is the exact R9
  standard for automatic rejection. Included in this document for
  completeness and ranking transparency, not recommended for registration
  ahead of A and B. If Fable wants a third hypothesis in the family for power,
  this is the next-best candidate, registered with this weak prior stated in
  the frozen spec itself.

---

## 5. Honesty section

### Base-rate expectation

Sung & Johnson found 0.45% of 1,547 simple MLB moneyline strategies profitable
at the 1% significance level — at or below the rate pure chance alone
produces. This program is 27-for-27 null across four registered families (V1,
V2, V4, V5) plus a fifth negative result from a fully independent instrument
(EvoLab's 8,811-strategy automated search landing *below the median* of three
placebo worlds). The honest, pre-stated expectation for this lane is the same
as for every prior lane: **most likely zero survivors**, and the forum/tout
sourced candidates (SR3-SR5) carry additional risk because their originating
literature (commercial system-selling sites) is lower-trust than the two
academic papers already exhausted by V2.

There is one structural reason this lane's prior is not identical to V1-V5's:
SR1's mechanism (favorite-longshot bias) is the one candidate in this document
with independent internal corroboration already on record (N12's de-vig
divergence measurement) rather than a fresh, untested claim. That raises SR1's
prior from "matches the literature's 0.45%" to "somewhat above it, still well
under 50/50" — stated now, before any read, so a positive result gets
scrutiny rather than a victory lap, per the M3 precedent.

### Kill criteria (restated, standing rules)

- Wrong sign at the 2023 screen → dead, no further look (V4's pattern).
- Sign flip at 2024 replication → dead (V4/V5's pattern, the single most
  common death in this program).
- Fails BH-FDR q=0.10 over the joint family → dead regardless of any
  individual p-value.
- Survives FDR but dies in the falsification battery (team/book
  concentration, dose-response, season stability, extreme-date removal) →
  dead, classified TESTED_FALSE_POSITIVE, published with the exact failing
  check (F1/F2 precedent).
- Underpowered (below the 30-selection floor) → no verdict drawn, classified
  as such rather than forced into null or candidate (N8/B3 precedent).
- No rescue by threshold, band, or definition change after seeing results
  (T8, absolute).

### What a null buys us

A clean null across SR1-SR3 (or however many are ultimately registered) is a
publishable, marketing-honest result this program cannot currently produce any
other way: **"we tested the strategies retail bettors and forums actually
believe in, on our own frozen validation machinery, and here is exactly what
happened to each one."** V1-V5 tested *our own* inventions; a customer reading
the research catalogue has no way to check whether we tried the things they've
already heard of. This lane closes that gap regardless of outcome. The
marketing value is explicitly a content/trust asset, separate from and
never substituting for evidence — a null here is reported with the same full
numbers, same battery detail, and same "zero survivors is a valid result"
framing as every prior family, and the marketing use of that null (e.g. "we
checked home-dog systems so you don't have to lose money finding out") is
written and reviewed as a separate downstream artifact, never folded into or
allowed to color the registration, the analysis, or the verdict language
itself.

---

## Summary table (for the catalogue, once this lane produces a verdict)

| candidate | status at end of this design pass |
|---|---|
| SR1/SR2 — home underdog price band | READY_UNTESTED (top-ranked, drafted in full) |
| SR3 — day-after-night home drift | READY_UNTESTED (drafted, low prior stated) |
| SR4 — series-finale desperation | REJECTED_AT_RANKING-adjacent — drafted for completeness, deprioritized on mechanism quality, not recommended as one of the initial three |
| SR5 — getaway-day road fade | REJECTED_AT_RANKING-adjacent — too close to N6 (TESTED_NULL) to be a distinct family member; flagged for explicit Fable review before any registration |
| SR-B1..B6 | BLOCKED / EXCLUDED, missing feeds named |
| SR6 (weekend staleness), SR7 (dispersion re-cut), SR8 (revenge game) | Not proposed — already covered by an existing lane (SR6) or excluded outright at ranking (SR7 forbidden rescue, SR8 no mechanism) |

**Nothing above is registered.** The next step, if Brey approves, is a
separate pre-registration act (frozen spec file + hash, following the V4/V5
pattern) for Template A and Template B jointly as one family, then Fable
review of that registration before any 2023 screen is run.
