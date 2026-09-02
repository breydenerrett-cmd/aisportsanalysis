# LINEHOUND MASTER PLAN — end-state reverse-engineering

2026-09-02. Written under Brey's MASTER STRATEGIC RESET directive.
PLANNING ONLY — nothing in this document is built, changed, or purchased.
Status of every capability is labeled: LIVE TODAY · EXISTS INTERNALLY ·
QUICKLY ADDABLE · REQUIRES NEW DATA · REQUIRES RESEARCH · REQUIRES
VALIDATION · LONG-TERM R&D · ASPIRATIONAL.

---

## 1. EXECUTIVE THESIS

Five claims drive everything below. Each is grounded in evidence this
project already produced, not in optimism.

**1. The vision is reachable, but the order is dictated by our own
results.** Four pre-registered families (V1, V2, V4, V5) against the MLB
full-game moneyline: zero survivors. A public-grade Elo loses to the
close by 0.008 log-loss/game (p=0.0003). An 8,811-strategy evolutionary
sweep over 2023–24 found LESS apparent edge than placebo noise
(percentile 13.3, below the placebo median — docs/EVOLAB_PHASE2B_RESULTS.md).
External evidence agrees (1,547 public strategies ≈ chance rate of
profitability). Conclusion: the full-game closing moneyline is efficient
beyond the power of our current information set. That is not a dead end
— it is the map. The mature platform gets built by pointing the same
machinery at markets where the same tests do NOT return null, and our
strongest conditional candidates (pitcher-prop timing, F5 derivation
error, information timing) already point there.

**2. The fastest honest currency of skill is beating the close, not
winning bets.** A strategy's win/loss record needs 1,000+ bets to
separate skill from luck; whether its entry prices systematically beat
the closing price separates them in ~10x fewer observations, because
price-vs-close variance is far smaller than outcome variance and the
close is the sharpest public estimate of the truth (our Elo benchmark
proved that yardstick works). Closing-price comparison becomes the
primary promotion metric; profit is the final judge but never the first
filter. This single change is the answer to "the machine must not reward
luck": a 14-5 run with entries WORSE than close is luck by construction;
an 8-11 run with entries consistently better than close is a candidate.
(Terminology note: this is the standard closing-line-value concept. Our
standing rule that the late_move detector must never be CALLED CLV is
about a mislabeled detector and stands; the metric itself, computed
properly as entry-price-vs-close, is legitimate and central.)

**3. The moat is time-stamped forward data that cannot be bought
retroactively.** Nobody sells historically-honest "what was the prop
board at 3:07 PM, before the lineup posted" data. We already capture
h2h/F5/spreads/totals forward with timestamps. Every day we do not
capture prop prices, weather forecasts, and listing times is a day of
moat lost forever. Principle: CAPTURE NOW, RESEARCH LATER — any data
stream that is (a) cheap, (b) point-in-time honest only if captured
live, and (c) plausibly useful, starts capturing before research needs
it.

**4. Scale without a global false-discovery budget is a
belief-manufacturing machine.** At 10 hypotheses, per-family FDR
suffices (we have it). At 10,000 lifetime strategies, the platform
itself becomes the multiple-comparisons problem. The 100x system's
load-bearing component is a GLOBAL registry where every hypothesis ever
evaluated spends from an explicit error budget, plus placebo ceilings
(already built in Evolab) and sealed rolling forward windows. This is
what lets us run "massive strategy diversity + massive automated
testing" without lying to ourselves.

**5. The product ships real value at every stage of that ladder, and
picks are the summit, not the entry fee.** Today: price quality
(genuinely valuable, fully earned), deep honest analysis, verification,
tracking. Next: calibrated ratings on the components we can defend.
Last: official picks with an immutable public record — launched only
when a strategy has survived the full gauntlet, and made one of the
strongest marketing assets in the category precisely because the record
is auditable.

## 2. THE ULTIMATE PRODUCT

One platform, two fundamental modes, one research engine underneath.

**MODE A — "I have a bet."** Universal Bet Check: any supported wager
(ML, run line, totals, F5 ML/totals, team totals, pitcher/hitter props,
2-leg parlays, SGP — expanding with validated market support). Returns:
the bet decomposed; the case for; the case against; matchup depth;
price quality vs market-implied consensus AND vs our model when one is
production-tier; historical analogues with samples; what's missing;
failure variables; evidence reliability tier; comparison against
today's other opportunities; the strongest devil's-advocate line; and —
only when scientifically earned — estimated probability, estimated
advantage, and calibrated confidence.

**MODE B — "Find me bets."** The Opportunity Scanner: every capture
cycle, the production scorer sweeps every supported market on the slate
and ranks what it can defend — Best Bets, by market, by sport, by
rating band, best prices, best dogs, parlay candidates. It searches
harder than any bettor can. When nothing clears the bar it says so —
but the personality is "here is the best of what exists and exactly why
it does/doesn't qualify," never "betting is risky, abstain."

**Surfaces (mature):** Gameday · Best Bets/Top Picks · Bet Check ·
Game Analyzer · Player Analyzer · Prop Finder · Parlay Lab · Odds board
· My Bets · Watchlist+Alerts · What Changed · Performance (public
record) · Research Library. Casual users get one fast answer; serious
users go deeper; experts can inspect methodology, model versions, and
the full pick history. Simplicity on the surface, machinery underneath.

**Honesty tiers as a UI primitive:** every number on every surface
carries one of LIVE / FORWARD-TESTING / VALIDATED / NOT YET AVAILABLE,
traceable to a registry entry. This is how breadth and integrity
coexist.

## 3. CURRENT STATE (forensic)

**Data (LIVE, growing):** 4 seasons results; 2.7M-pitch rebuilt store;
pitcher logs/arsenals; lineups (posted, timestamped); bullpen logs;
handedness; park; travel; transactions/IL feed (timestamped);
multi-book odds: 10,860 multibook rows (8–11 US books), 4,362 snapshot
rows across h2h/spreads/totals, dense 15-min pre-game grid, F5 closes
(201 rows), prop LISTING audit (293 rows; 7 books list pitcher Ks);
forward ledger n=187 entries; ~53,000 API credits (~25x monthly burn
headroom).

**Research machinery (LIVE, validated):** point-in-time matrix +
7-check validated funnel/compiler; BH-FDR; clustered bootstrap;
falsification battery RULES_VERSION 2.0.0 (frozen, generality-tested);
sealed 2026 holdout; forward ledger discipline; Evolab: genome registry,
leakage-proof replay (WorldView), sweep driver, placebo-ceiling
adjudication — all exercised for real in Phase 2B.

**Research results (the graveyard is an asset):** 4 families zero
survivors; Elo-vs-close benchmark; M1–M5 market-structure nulls; V3
timing OPEN_LIVE (28/30 events to first read); V6 ranking: zero
unconditional candidates, C1 (pitcher-K props priced before lineups)
strongest conditional, C2 (F5 derivation error) second; 73 ideas
classified in docs/RESEARCH_CATALOGUE.md so nothing dead returns as new.

**Product (LIVE on staging):** honest Analyzer + Bet Check + Odds +
My Bets + free tier (3 lifetime) + Stripe TEST signup/entitlement/
period-end cancel/reactivate + designed V1 frontend (visual-passed) +
V2 design lane in flight + funnel events + ops runbooks/monitors.
2,200+ green tests. Deployed via CI to Fly staging.

**Known limitations:** JSONL stores scanned linearly; research
throughput = one hand-built family at a time outside Evolab; no CLV
metric spine; no model/strategy serving registry; no calibration
harness; prop PRICES not captured (listing only — policy-gated); no
weather capture; single-node compute; LLM agents underused for
hypothesis generation.

## 4. EXCEPTIONALLY VALUABLE (preserve at all costs)

1. The falsification stack (PIT audits, sealed holdout, FDR, battery,
   placebo ceilings, forward ledger). This is rare even among funded
   quant teams and it is the platform's spine.
2. The forward capture discipline + timestamped stores. The moat seed.
3. The pitch-level rebuilt store (leak-free, our own).
4. Evolab's replay/registry/adjudication skeleton — the 100x chassis
   already exists in miniature; Phase 2B proved it can kill its own
   favorite idea, which is exactly the property we need at scale.
5. The research graveyard + catalogue (73 classified ideas): the map of
   where NOT to spend, which is most of the value of research.
6. Product honesty contracts (Rule S samples, never-empty
   counterargument, no fabricated freshness) — the trust surface picks
   will someday inherit.
7. The honest null itself: knowing the full-game close is efficient
   against public data is a costly, valuable fact competitors don't act
   on.

## 5. UNDERPOWERED (10x these)

- **Evolab**: built for one market + one fitness (movement). Needs:
  per-market fitness functions (log-loss vs market price, price-vs-
  close), multi-market genomes, LLM hypothesis proposers, and a
  continuous (not one-shot) cycle. The chassis is right.
- **Storage/compute for research**: JSONL → columnar mirror
  (DuckDB/Parquet). One box can then replay millions of simulated
  decisions per night. QUICKLY ADDABLE.
- **Market coverage**: we capture 4 markets; the product vision needs
  props, team totals, alternates — capture design exists for props at
  ~18 credits/day. REQUIRES POLICY DECISION (already drafted).
- **The ledger**: forward ledger is research-grade; the recommendation
  ledger (immutable, hash-chained, versioned, public-consumable) is its
  product-grade descendant. QUICKLY ADDABLE (schema now, used later).
- **Calibration**: nothing today measures "when we say 60%, does 60%
  happen" because nothing production-tier says 60% yet. The harness
  must exist BEFORE the first model does, so the model meets a waiting
  bar. QUICKLY ADDABLE.
- **AI leverage**: agents today execute; they should also PROPOSE
  (hypotheses, mutations, adversarial critiques) into the registry
  under the global budget.

## 6. REPLACE / RETIRE

- **Hand-run one-family-at-a-time research cadence** → compiled sweeps
  through Evolab under the global registry. The V4/V5 style (weeks per
  ~10 hypotheses) was the right way to validate the machinery; it is
  the wrong way to search at scale.
- **Detector dual-role confusion** → detectors remain as Analyzer
  evidence generators (product content); strategy search moves wholly
  to Evolab genomes. One concept, one job.
- **JSONL as the analytical substrate** → mirrored columnar store
  (JSONL stays the append-only capture format; analysis reads the
  mirror).
- **Legacy report surfaces** (static dashboard/demo pages superseded by
  web/) → freeze, don't maintain. (artifacts/demo_latest.html stays
  untouched per standing rule.)
- **The implicit assumption that MLB h2h is the target market** →
  replaced by evidence-driven market allocation (§12).
- NOT replaced: the battery, the funnel, the sealed holdout, the
  forward capture, the app backend, the design system. Sunk cost was
  examined; these survive on merit.

## 7. THE 10X SYSTEM (order-of-magnitude more capable; weeks-scale)

1. **Research mirror**: DuckDB/Parquet mirror of all stores + a
   decision-time index (every game × capture-instant × market ×
   information state). Millions-row joins in seconds on one box.
2. **CLV spine**: entry-vs-close computation for every market we
   capture, wired into ledger, Evolab fitness, and promotion rules.
3. **Capture expansion**: pitcher-prop prices (~18 cr/day, gated on the
   drafted policy amendment), weather forecasts (free/cheap), listing
   times, alternate lines listing. All forward, all timestamped.
4. **Market Learnability Audit v1** (§12) across the 6 markets we
   already hold data for — h2h, F5 h2h, totals, F5 totals, spreads
   (run line), team totals where present — plus props as capture
   accrues.
5. **Evolab v2**: per-market fitnesses (log-loss vs de-vigged market,
   CLV), genome grammar over the matchup matrix + market features,
   global registry with alpha-spending, nightly automated cycle,
   graveyard auto-classification.
6. **Global hypothesis registry**: every evaluated genome/family ever,
   with its error-budget spend — the single source of "how hard have we
   searched," which the battery's priors consume.
7. **Calibration harness + rating skeleton**: reliability curves,
   Brier/log-loss vs market baseline, rating-band monotonicity checks —
   running against paper outputs before anything customer-facing.
8. **Recommendation-ledger schema** (hash-chained, append-only,
   model-versioned) built and exercised by paper picks only.

## 8. THE 100X SYSTEM (a research platform; months-scale, gated)

- **Strategy population at scale**: thousands of live genomes across
  markets; generation = grammar enumeration + mutation operators + LLM
  proposers writing GENOMES (not code); niching by market to preserve
  diversity; selection by information metrics + battery survival, never
  raw ROI; automated retirement with cause. "Thousands of bots" is
  thousands of REGISTERED GENOMES evaluated by vectorized replay — not
  thousands of processes, and NOT thousands of LLM calls.
- **Per-market model families**: where the learnability audit says a
  market has structure, purpose-built models (a pitcher-K distribution
  model is a different object than an F5 total model) trained under PIT
  constraints, benchmarked against that market's own close.
- **Paper-pick program**: production-candidate strategies emit
  timestamped paper picks into the recommendation ledger daily;
  calibration and CLV accumulate toward the picks gates.
- **Continuous monitors**: decay/demotion rules pre-declared at
  promotion; regime dashboards; auto-alerts.
- **NBA data spike** (read-only research of feeds/costs) to price
  expansion before building it.
- **Compute**: one large VM + burst batch for sweeps; managed Postgres
  for app when customer load justifies.

## 9. THE 1000X SYSTEM (the mature machine; aspirational shape)

- Multi-sport packs (MLB, NBA, NFL, …) on one spine; sport-specific
  intelligence with shared capture/settlement/validation/serving.
- A standing population of production + candidate strategies per
  market per sport, continuously challenged by new generations; a
  research scheduler allocating compute and API budget by expected
  information gain.
- Distributed replay farm (spot instances) running full-history
  counterfactual simulations on demand.
- The public record as the front page: every official pick, every
  price, every unit, hash-verifiable; performance windows by
  sport/market/model version; the strongest legal marketing asset in
  the category because it cannot be cherry-picked even by us.
- Personalization (watchlists, alert conditions, book preferences,
  bankroll views) on top of the same truth layer.

## 10. TARGET END-TO-END ARCHITECTURE

Seven planes, cleanly layered:

1. **Capture plane** — providers, dense grids, listing audits, weather,
   news/rosters. Append-only JSONL + object storage. Immutable.
2. **Truth plane** — PIT feature matrices per sport; the decision-time
   index; the columnar research mirror; settlement.
3. **Research plane** — hypothesis sources (grammar, mutations, LLM
   proposers, literature miner) → global registry (alpha budget) →
   vectorized replay → funnel (screen/replicate/FDR) → battery →
   placebo ceilings.
4. **Promotion plane** — the ladder (§18), calibration harness, sealed
   rolling forward windows, pre-declared demotion rules.
5. **Serving plane** — model/strategy registries (versioned), the
   scorer (per-bet rating components), the opportunity scanner.
6. **Product plane** — Bet Check, Best Bets, Analyzer, Odds, My Bets,
   Performance pages; honesty tiers bound to registry state.
7. **Record plane** — recommendation ledger (immutable, hash-chained),
   public performance derivation, feedback into calibration/allocation.

## 11. MLB INTELLIGENCE ENGINE

HAVE (PIT-graded): pitcher logs (FIP/ERA/WHIP/K-BB/IP), arsenals,
hitter-vs-pitch-type, platoon, posted lineups w/ timestamps, bullpen
usage/rest, travel/schedule, park (dimensions/roof/altitude), records/
splits, transactions/IL, multi-book prices w/ instants.
BUILD (ranked): (1) weather FORECAST capture (forward-only honesty;
totals/park interactions; cheap); (2) umpire assignments (free feed;
verify reliability first — B10); (3) batted-ball/xstat aggregates from
our own pitch store (no purchase needed); (4) catcher framing/defense
aggregates; (5) starter workload/injury-return features from the
transaction stream; (6) hitter velocity-band profiles (exists partially
via arsenals path). Each lands as a matrix column with a PIT test
before any strategy may read it. Models stay market-specific: a K-prop
distribution model, an F5 run-scoring model, and a full-game winner
model are different objects sharing features, not one model.

## 12. MARKET-SELECTION RESEARCH PROGRAM (the allocation mechanism)

The question "which betting problems are most learnable" becomes a
standing, pre-registered audit, refreshed as data accrues. Per market:
- **Internal consistency**: cross-book dispersion, de-vig disagreement,
  best-vs-consensus gap frequency/size, arb frequency, ladder
  coherence. (Much already measured for h2h; extend.)
- **Reaction speed**: repricing latency after information events (V3's
  machinery generalized per market — lineup post → prop/F5/total moves).
- **Close predictability**: can public-data models predict the CLOSE
  (not the outcome)? A market whose close is predictable from early
  public info has an exploitable window by construction.
- **Outcome structure**: signal-to-noise of the underlying quantity
  (K's are a 1-pitcher process; game winners aggregate everything —
  lower-variance targets are more learnable per observation).
- **Practicalities**: book coverage, listing windows, limits knowable?,
  data cost, PIT reconstructability.
Output: a ranked allocation table that DIRECTS Evolab compute and data
spend. Priors from evidence in hand: pitcher props (C1 — 7 books,
priced pre-lineup) and F5 derivations (C2) rank above full-game h2h,
which our four families and Phase 2B place at the bottom. The audit
either confirms or embarrasses those priors; either way we learn where
to dig. REQUIRES: prop price capture (policy amendment) for the prop
rows; everything else runs on data in hand.

## 13. STRATEGY DISCOVERY / EVOLUTION SYSTEM

Brey's evolutionary intuition, corrected by our own Phase 2B evidence:
- **Population = genomes, not processes.** A genome: (market, feature
  expressions from a typed grammar over the matrix + market state,
  direction, entry rule, gates). Deduped by semantic hash.
- **Generation**: combinatorial enumeration under coverage constraints;
  mutation/crossover operators; LLM proposers that read the graveyard
  and literature and emit genomes with mechanisms (never code, never
  free-form claims); mandatory diversity quotas per market.
- **Fitness (the correction)**: NOT simulated-bankroll tournaments —
  bankroll is a maximally noisy statistic and "keep top 80% biweekly"
  would select luck (Brey's own suspicion, confirmed by our math).
  Fitness = calibrated log-loss improvement vs the market's own price +
  price-vs-close on triggered entries + robustness (season/book/regime
  splits), evaluated by deterministic replay, judged against placebo
  ceilings, FDR-controlled through the GLOBAL registry.
- **Survival/retirement**: statistical, staged, with the battery as the
  killer and the graveyard recording cause of death. Champions spawn
  variants; dead branches are pruned from the search grammar itself so
  the machine stops re-proposing them.
- **Cadence**: continuous nightly cycles, sized to the compute budget.
Phase 2B is the proof the loop works end-to-end (it ran 8,811 genomes
and correctly refused to believe any of them); v2 changes the fitness
and the markets, not the philosophy.

## 14. LARGE-SCALE BACKTESTING

Vectorized replay over the decision-time index: every (game, instant,
market, book) with exactly the information that existed then, the price
actually quoted then (our own captured boards — never idealized), the
decision, the settlement, the bankroll path, and the close for CLV.
Deterministic code end to end; agents never execute simulations.
Millions of simulated wagers/night on one box via the columnar mirror.
Execution realism ladder: quoted-price fills now → add fill-probability
and limit haircuts later (limits are unobservable; model conservatively
and say so). Every replay run is reproducible from (code hash, store
snapshot, genome, seed).

## 15. VALIDATION / FALSIFICATION

Keep: PIT audits, per-family FDR, battery 2.0.0 (versioned upgrades
only via its own generality gate), sealed 2026 holdout, placebo
ceilings, 7-check machinery gate, published losers.
Add: **global alpha-spending registry** (the 100x keystone — every
genome ever evaluated spends error budget; family-level FDR nests
inside it); **rolling sealed forward windows** (each candidate's first
N forward weeks auto-sealed until its read date); **calibration
harness**; **adversarial agent critique** as a standing stage on every
survivor (an LLM whose only job is to write the strongest kill case,
which the battery then formalizes); **correlation accounting** between
strategies (near-duplicate genomes must not each collect full budget,
and an ensemble of 50 correlated survivors is one bet, not fifty).
The better a result looks, the more the system spends trying to kill it.

## 16. BET-RATING SYSTEM

Architecture: **decomposed components, separately earned; composite
only when calibrated.**
- **P — Price Quality** (LIVE TODAY): best-vs-consensus, improvement
  points/return, book dispersion. Fully honest now.
- **E — Evidence Quality** (LIVE TODAY): the Analyzer's case — findings,
  samples, gaps, counterarguments — summarized as a tiered evidence
  score (Observation → Validated ladder already defined in contracts).
- **M — Model Advantage** (REQUIRES RESEARCH+VALIDATION): calibrated
  probability vs market-implied, from production-tier models only.
  Empty until earned; the UI renders its absence honestly.
- **U — Uncertainty** (ships with M): interval width, model agreement,
  regime flags, sample depth.
Composite "BET RATING 87" exists ONLY when M is populated and the
composite passes the calibration harness: forward rating-band
monotonicity (80s must beat 70s on outcomes and CLV), reliability
curves, and per-market calibration. An evidence score is never a win
probability; a strong case at a terrible price scores low; a model edge
with huge U is capped. Every rating decomposes on tap and cites its
model version. Scale meaning is proven by the public bins, not
asserted.

## 17. PICKS / OPPORTUNITY DISCOVERY

The scanner (Mode B) is the scorer swept across the slate each capture
cycle — same components, ranked. The staged ladder:
- **Stage 0 (LIVE)**: Best Price Board — genuinely valuable, fully
  earned today.
- **Stage 1 (internal)**: candidate strategies emit paper picks into
  the recommendation ledger; nobody sees them but us.
- **Stage 2 (subscriber-visible, labeled)**: "FORWARD TESTING — not a
  recommendation" feed with live CLV/calibration stats, for users who
  want to watch the science. Optional, honest, differentiating.
- **Stage 3 (official picks)**: gates in §27 pass; picks ship with
  rating, reasoning, price captured at publication, model version, and
  enter the public record irrevocably.
Every stage feeds the same ledger so the record predates the marketing.

## 18. PARLAY RESEARCH PROGRAM

Sequenced honestly: (1) calibrated single-leg models are prerequisites
— a parlay recommender without leg probabilities is astrology; (2)
cross-game 2-leg parlays are then a composition layer (product of
calibrated legs vs offered price; independence approximately holds);
(3) SGP correlation research REQUIRES SGP price capture (a data
decision) and joint modeling — books' correlation pricing is the
research target, our own joint model (player-level simulation) the
long-term instrument; (4) customer-facing parlay ratings inherit the
same gates as picks. Books price SGP correlation crudely in both
directions — it is a genuine research target, and also where fake-edge
products live, so the evidence bar is the same as everywhere.
LONG-TERM R&D; the design decision now is only to capture what future
parlay research cannot backfill.

## 19. DATA ROADMAP (ranked by expected information per dollar, PIT-honest)

1. **Pitcher-prop prices, forward** (~18 cr/day ≈ 540/mo vs ~53k
   balance): unlocks the top-ranked market program (C1). Needs the
   drafted policy amendment. CAPTURE NOW.
2. **Weather forecasts, forward** (free/cheap API): totals/park work;
   only honest if captured pre-game. CAPTURE NOW.
3. **Listing/repricing times across all markets** (zero new credits —
   metadata of captures we already make). CAPTURE NOW.
4. **Umpire assignments** (free; verify source reliability first).
5. **Batted-ball/xstat aggregates** from our own pitch store ($0).
6. **Historical prop odds purchase**: DEFER until forward prop capture
   + learnability audit says the market has structure; then the buy
   decision is evidence-priced, pre-registered.
7. **Deeper h2h backfill (2020–22)**: cheap but low value — the
   full-game null is already powered. Skip for now.
8. **Public betting %**: unavailable at our tier; wanting it does not
   create it. BLOCKED, stays blocked.
9. **NBA feeds** (spike only in 100x phase).
Useless-until-proven: umpire "tendencies" from third-party scrapes,
social sentiment, injury rumor feeds — each may enter only through a
pre-registered experiment.

## 20. AI AGENT ARCHITECTURE

**Propose/dispose split**: agents PROPOSE (hypotheses with mechanisms,
genome mutations, adversarial kill cases, literature syntheses, failure
investigations, new-sport onboarding audits, customer-facing prose from
verified facts); deterministic systems DISPOSE (simulate, settle,
score, promote, demote). Agents never touch a simulation result, never
compute a statistic the pipeline reports, never write directly to a
store. Orchestration stays as today (Fable orchestrates; Sonnet
executes; Opus for high-risk methodology). LLM spend is a budget line
with per-cycle caps; the hypothesis-proposer's value is measured (do
agent-proposed genomes outperform grammar-enumerated ones per unit
cost? — itself an experiment).

## 21. COMPUTE / INFRASTRUCTURE

- **Now ($~0 infra + API credits)**: single node + scripts + SQLite
  (app) — sufficient through 10x with the DuckDB mirror.
- **10x (+$0–50/mo)**: same box, columnar mirror, nightly sweep cycle.
- **100x (+$150–500/mo)**: bigger VM or burst spot instances for
  sweeps; object storage for store snapshots; managed Postgres when
  customer load (not research) demands it; LLM proposer budget
  ($50–200/mo, capped).
- **1000x (priced when earned)**: distributed replay farm, multi-sport
  capture fleet.
Every step is gated on evidence produced by the previous one; no
premature infrastructure. Storage doubles as reproducibility: store
snapshots are versioned so any historical claim can be re-derived.

## 22. CUSTOMER PRODUCT (connection to the engine)

The product reads ONLY the serving plane: registries + scorer +
ledger. No screen computes analysis client-side; no screen shows a
number without a registry-backed tier label. Bet Check is the universal
entry (paste/select any supported bet); Best Bets is the scanner's
ranked output; the Analyzer is the depth behind both; Odds is the
price truth; My Bets + Watchlist personalize it; Performance renders
the public ledger. The V2 design lane proceeds against the reconciled
capability contract (design/linehound-v2/RECONCILED_CONTRACT_CURRENT_HEAD.md)
— nothing in this plan changes its scope; new surfaces enter design
only when their data tier exists. Broadcast-quality visual identity
stays the bar; design serves truth.

## 23. SUBSCRIPTION / BUSINESS ARCHITECTURE (conceptual)

- **Free**: 3 lifetime Bet Checks, delayed/limited board, public
  performance record (the record is marketing — never paywalled).
- **Core ($19.99 founding, current)**: unlimited Bet Check, full board
  and freshness, My Bets, What Changed, alerts (when built).
- **Pro (later, priced when earned)**: official picks + ratings +
  prop tools + Stage-2 forward-testing feed + advanced research
  access. Picks are premium BECAUSE the record is public — the record
  sells the subscription; the subscription sells the detail.
- Sport packages at multi-sport stage. No annual lock-in during beta.
  Packaging decisions final only after Stage-3 gates and real cohort
  data; nothing here binds them.

## 24. THE LONG-TERM MOAT

(1) The forward capture corpus — timestamped market+information states
no one can buy retroactively; compounds daily. (2) The public,
hash-verifiable pick record — trust that cannot be faked or bought,
and survives bad months because it was designed to. (3) The graveyard
— thousands of documented dead ideas = the negative space of edge,
invisible to competitors. (4) Calibration history per market/model.
(5) The falsification machinery itself — the capacity to say no at
scale is the rarest asset in this category. Customer data stays a
product input (watchlists/alerts), never a research shortcut.

## 25. MULTI-SPORT EXPANSION

Spine (shared): capture, odds/wager/market schema, settlement, ledger,
funnel/battery/registries, calibration, serving, product surfaces,
billing. Packs (per sport): providers, feature builders, PIT rules,
market list, models, domain detectors, vocabulary. The MULTISPORT_AUDIT
already classifies src/ along exactly this line (STRUCTURAL vs
PARAMETRIC vs INCIDENTAL) — the refactor happens opportunistically as
the 10x work touches files, not as a big bang. Order: **MLB proves the
full loop → NBA** (props-dense, data-rich, high volume, the classic
soft-market complement; spike first) **→ NFL** (huge demand, tiny
samples — enters with humility as a price/analysis product before a
model product). Tennis/others priced later. Entry gate per sport: the
capture cost model + a learnability pre-audit on purchasable data.

## 26. MASTER DEPENDENCY ROADMAP

- **Phase 0 (now)**: this plan; owner review. Standing ops (capture,
  monitors, V2 design lane, beta launch path) continue unchanged.
- **Phase 1 — Foundations (post-approval)**: research mirror + CLV
  spine + global registry + capture expansion (props/weather/listing)
  + calibration harness + recommendation-ledger schema + Evolab v2
  fitness. Learnability Audit v1 on data in hand. No customer-visible
  change. (Product lane in parallel: V2 design → implement → paid
  beta, per the existing critical path.)
- **Phase 2 — Search**: Evolab continuous cycles on audit-ranked
  markets; per-market model spikes for the top 2; paper-pick program
  begins; V3 first read at floor; F5 review at ~2wk data.
- **Phase 3 — Ratings**: components P+E ship as designed surfaces
  (labeled); M enters Stage 1/2 as candidates emerge; NBA spike.
- **Phase 4 — Picks**: Stage-3 gates pass → official picks + public
  record + Pro tier. Date is evidence-determined, not calendar-set.
Dependencies are strict: no rating composite before calibration
harness; no public number before the ledger; no pick before the gates;
no sport 2 before sport 1 closes the loop.

## 27. PROMOTION GATES

**Scientific (strategy → production)**: pre-registered in the global
registry → discovery significance + effect floor on 2023–24 →
replication → survives battery + placebo ceiling + adversarial critique
→ positive price-vs-close over ≥300 forward paper entries with CI
excluding zero → calibration in-band → Brey freeze sign-off. (The
existing 4-condition Ranker unlock, made precise.)
**Product**: a surface ships when its data tier is LIVE, its states
are designed, visual acceptance passes, and its copy survives the
banned-vocabulary tripwire. Picks additionally require the ledger
running ≥60 days with paper picks and the public-record pages built.
**Data**: a purchase requires a pre-registered experiment naming the
decision it changes, a cost cap, and a PIT-honesty plan.
**Cost**: credit floor 5,000 stands; any new recurring spend > $50/mo
or one-time > $200 is a Brey decision; LLM proposer budget capped
per cycle.
**Demotion (pre-declared at promotion)**: rolling CLV below zero over
a declared window, calibration drift beyond bound, or regime-break
flags → automatic demotion to Stage 1 + public annotation. Model
versions are immutable; a successor gets a new version and the old
record stays.

## 28. COST CONTROL

Today's burn: ~132 credits/day dense grid (~4k/mo vs 100k plan) + Fly
hobby + $0 LLM baseline. Phase-1 adds ~540 credits/mo (props) + ~$0–50
infra. Every phase's spend is enumerated before it starts; research
allocation follows the audit, not enthusiasm; a monthly one-line cost
report goes into the overnight log. Kill-switches: capture degrades
gracefully to the credit floor; sweeps are budget-boxed; agents are
capped per cycle.

## 29. FAILURE MODES (and their controls)

1. **False-discovery explosion at scale** → global alpha ledger,
   placebo ceilings, correlation accounting, sealed forwards. (The #1
   scientific risk of this whole vision.)
2. **PIT leakage in a fast-growing feature space** → every matrix
   column ships with its own injection test; mutation-tested; the
   probable-pitcher audit is the template.
3. **Every market proves efficient** → the product still stands on
   price quality + analysis + record-keeping (a real business), and
   the null corpus itself is licensable credibility. This outcome is
   survivable by design.
4. **Public record hubris** (marketing small samples) → display gates
   by sample size; fixed windows; losing categories shown; the ledger
   makes cherry-picking structurally impossible.
5. **Backtest-vs-live divergence** (fills, limits) → conservative
   execution model, forward paper as the binding stage, CLV as the
   leading indicator of decay.
6. **Complexity collapse / orchestration sprawl** → registries as the
   single source of truth; fewer, deeper systems; the stop-doing list.
7. **API/provider dependency** → capture redundancy where cheap;
   stores are ours; provider swap is a capture-plane change only.
8. **Legal/marketing exposure for a picks product** (state advertising
   rules, T&Cs, "not gambling advice") → counsel review is a HARD GATE
   before Stage-3 marketing; existing legal drafts are labeled
   not-legal-advice.
9. **Brey as bottleneck** → the owner queue stays ≤5 standing items;
   everything else pre-delegated by this plan.
10. **A losing public month** → designed for: the record survives
    because it never promised perfection, only honesty; Stage-2
    labeling and drawdown context ship WITH the record from day one.

## 30. STOP DOING

- Hand-building one-off research families outside Evolab (after
  Phase-1 lands).
- Any further detector work aimed at the full-game moneyline.
- Maintaining superseded static report surfaces.
- Treating "no_play" as the end of the product sentence — the scanner
  reframe (§17) replaces it with "here is the best available, and
  here is exactly what it would take to qualify."
- Debating architectures we can measure (the audit decides market
  allocation; the proposer experiment decides agent value).

## 31. TOP 10 HIGHEST-LEVERAGE MOVES

1. CLV spine (metric + storage + fitness integration).
2. Prop-price + weather + listing-time forward capture (the moat
   clock is running).
3. Market Learnability Audit v1 (allocation by evidence).
4. DuckDB research mirror + decision-time index (unlocks scale).
5. Global hypothesis registry with alpha-spending (unlocks honest
   scale).
6. Evolab v2 fitness/markets + nightly cycle.
7. Recommendation-ledger schema + paper-pick program (starts the
   clock on every future gate).
8. Calibration harness (the bar every model must meet, built first).
9. LLM hypothesis-proposer pipeline (measured against the grammar).
10. Two per-market model spikes on the audit's top markets (likely
    pitcher-K distribution + F5 total/derivation).
Product continues in parallel on its existing critical path (V2 design
→ implement → paid beta); nothing above blocks it.

## 32. AUTONOMOUS EXECUTION ARCHITECTURE (post-approval)

Parent (Fable) runs the standing loop against this plan's phases:
Sonnet workers execute; Opus for methodology/PIT/high-risk; scripts own
all capture/simulation; every research artifact pre-registered; every
commit tested; overnight log + command center kept current; checkpoint
reports while working. Standing ops (hourly capture, monitors, daily
loop, staging) continue untouched. Parent executes Phases 1–2 fully
autonomously within the cost gates; Phase 3 customer-visible surfaces
go through the existing design/visual-acceptance gates; Phase 4
requires the owner queue below. Weekly: a one-screen progress digest
(what moved, what died, spend, next).

## 33. MINIMAL OWNER DECISION QUEUE

1. **Approve this master plan + authorize Phase 1** (foundations +
   capture expansion + learnability audit).
2. **Set the monthly budget envelope**: proposed ceiling $100/mo
   infra+LLM until Phase 2 evidence, plus ~540 credits/mo props
   capture from the existing balance. One number to approve or change.
3. **Sign the prop-collection policy amendment** (one line, already
   drafted in docs/PROBE_PROP_LISTING.md §6 / COLLECTION_POLICY.md).
4. **Postseason/spring admissibility ruling** (existing item, needed
   before 2026-09-29).
5. **(Later, flagged now)** Engage counsel before any Stage-3 public
   picks marketing. No action needed today.

Everything else in this document is pre-delegated.

---

## APPENDIX A — Public performance / units accounting (design)

**Units definition (one methodology, documented, permanent):** flat
risk of 1.00 unit per official pick at the captured price. Net units =
Σ(win: price payout on 1u risk; loss: −1.00; push/void: 0). ROI = net
units ÷ units risked. No risk-to-win convention (it flatters favorite
records); no variable staking in the official record. If confidence-
based stake recommendations ever ship, they form a SECOND, separately
labeled series ("recommended-bankroll performance") derived from the
same immutable picks — model performance and staking performance never
mix.

**The ledger:** append-only, hash-chained (each entry carries the
previous entry's hash), git-committed and served read-only. Entry:
timestamp (pre-event, enforced against first pitch), sport, market,
selection, line, book + price captured at publication, units risked,
model/strategy version, rating, official-status flag, and later:
result, settled units, close price (for CLV context, never for
settlement). A pick cannot become official retroactively; a void keeps
its row. Backtest, out-of-sample, sealed-holdout, forward-paper, and
official-pick series are five permanently separate labels — no surface
may blend them.

**Presentation:** fixed windows only (today / 7d / MTD / 30d / season /
all-time), per sport / market / model version / rating band; every
figure with n; categories below a display floor render "n too small"
rather than a rate; losing categories render exactly like winning
ones; max drawdown and average odds accompany units; "last updated"
timestamps everywhere. The homepage module consumes the same derived
stats — marketing can never have numbers the record page lacks.

**Feedback:** the ledger feeds calibration (rating-band monotonicity),
decay monitors (CLV drift), research allocation (market-level
performance), and demotion. If 80-rated picks underperform 70-rated
picks, that is a calibration incident with an automatic response, not
a marketing problem.

**Before official picks launch, must exist:** the ledger + derivation
pipeline (≥60 days exercised by paper picks), the public record pages,
the display floors, the versioning registry, counsel review of the
marketing language, and Brey's Stage-3 sign-off.

## APPENDIX B — Self-critique (red-team of this plan)

- **Where naive:** CLV assumes the close is the best public estimate —
  true for MLB h2h (we measured it), NOT guaranteed for soft prop
  markets where the close itself can be wrong; therefore promotion in
  soft markets weighs outcome-based metrics more, close-based less —
  the gates in §27 must be per-market-calibrated, not copied.
- **Execution realism gap:** we do not observe limits; prop markets
  especially may be unbettable at size. Conservative haircuts + the
  Stage-2 paper period are the mitigation; a real-money pilot (Brey's
  own, small) may eventually be the only honest fill test — flagged,
  not planned.
- **Correlated-strategy inflation:** thousands of genomes on shared
  features are NOT independent; naive FDR over-counts the search but
  under-counts the correlation of survivors. The registry must track
  genome similarity and the battery must treat clustered survivors as
  one finding. Named in §15; the hardest open methodology problem in
  this plan.
- **Data-cost optimism:** historical prop data, if we ever buy it, is
  the item most likely to be 5–10x the naive estimate once PIT-grade
  timestamps are demanded. Hence forward-first.
- **Agent proposer risk:** LLM proposers may cluster around published
  ideas (which are priced in) — diversity quotas and measuring their
  hit-rate against the grammar keeps them honest, and the graveyard
  keeps them from re-proposing corpses.
- **Product complexity risk:** the mature surface list could bloat the
  beta. The phase gating (§26) keeps today's product on its existing
  critical path; nothing new ships before its data tier exists.
- **What a sharp competitor would exploit:** our public record's
  transparency telegraphs our markets. Accepted cost — the moat is
  capture-time data + validated calibration, which watching our picks
  does not confer.
- **Where we may be over-spending skepticism:** the price-quality
  product is already real and marketable; we should not let the edge
  hunt starve the (live, honest) line-shopping value proposition that
  needs no research at all to be worth $19.99.
