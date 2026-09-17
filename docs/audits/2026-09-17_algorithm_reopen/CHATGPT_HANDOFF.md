# LineHound — handoff for a fresh expert reviewer

Written 2026-09-17 by Claude (Opus 5) for ChatGPT or any other model entering
cold. Not marketing copy. Failures, abandoned ideas, contradictions and
UNKNOWNs are included deliberately, and where something is unknown it says
UNKNOWN rather than guessing.

Repo: `breydenerrett-cmd/aisportsanalysis`
Working branch: `claude/sports-betting-analysis-review-g1o0co`
Default branch: `claude/cowork-session-migration-tn3sx2` (an ORPHAN branch
holding only workflow files — scheduled jobs live there and check out the
working branch)
Scale: ~1,705 commits, 186 docs, 236 src modules, 384 test modules.

---

## 1. What the product is

A sports-betting ANALYSIS product. MLB first. It publishes a small daily
"card" of ranked picks, frozen to a hash-chained public ledger BEFORE first
pitch, and graded afterwards win or lose, including the losses.

**Hard rule, absolute: no real-money betting and no bet-placement code, ever.**
Everything is paper, flat 1-unit stakes.

Product direction (owner-stated): MLB first; roughly 3-10 ranked daily picks
as the core; deep on-demand matchup analysis; moneyline, run line, totals,
pitcher props, hitter props; other sports later; eventual live in-game
analysis and alerts (ideally push/text). **Explicitly NOT the identity:
sportsbook price-shopping / "Bet Check"** — the owner killed that direction
on 2026-09-10 ("nobody fucking cares"). See contradiction C-OPP below: the
frontend obeyed, the paid API route did not.

## 2. The honesty discipline — read this before judging anything else

This is the most unusual thing about the project and the reviewer should
understand it before criticising the modelling.

- **Pre-registration before evaluation.** A hypothesis is registered, with its
  kill condition and sign, before anyone looks at a result.
- **Published losers.** Deaths are written up. `src/research/alpha_registry.py`
  is append-only and `record_verdict()` refuses a second verdict per row.
- **Sealed window: 2026-01-01 to 2026-08-27.** Not read, not fit on. 2025 is
  tuning-only. 2023-24 are discovery — "diagnostic, never evidence."
  2026-08-28 onward is forward proof.
- **No promotion without the full gate** (G0-G7). **No rescue by threshold
  change.** Point-in-time correctness everywhere.
- **`edge_bps` is structurally null unless the probability is
  `model_derived`** — `src/ledger/records.py:92-122` enforces that comparing a
  market-derived probability against the price it came from is circular and
  must not be recorded as a measured edge. This is a genuinely good piece of
  design and a reviewer should note it.

**Current evidential position: 92 registry rows, 42 verdicts, ZERO
survivors.** Nothing has been shown to beat the market.

## 3. Architecture, briefly

- `src/` — pure standard library, no third-party deps. Providers, pipelines,
  analysis, report, appstate (ledgers), research, evolab, engine.
- `api/` — FastAPI. `web/` — vanilla ES modules, no framework, no build step.
- `tests/` — 384 modules, unittest only (**no pytest in CI**), run as
  `python -m unittest discover -s tests -t .`
- Scheduled work: `.github/workflows/` — daily-loop, forward-capture,
  afternoon-slate, live-window, deploy-staging, balldontlie-harvest,
  tennis-results-check.
- **Deployment: staging ONLY.** `linehound-staging.fly.dev`. There is NO
  automated path to production; `deploy/DEPLOY_RUNBOOK.md` treats creating
  the prod app as a future checklist item. A reviewer should not assume a
  production system exists.

## 4. The models

**Card V1 — LIVE** (`src/analysis/daily_card.py`, rule
`DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1`). Side = the market favourite;
the model must agree or SPLIT; **ranked by market confidence; NO price test**.
Floor 3 picks, max 5, filled by lowering the LABEL not by inventing a claim.
STRONG = market ≥ 0.62.
**Structural consequence, measured:** it cannot pick anything but favourites,
because the market's favourite IS its ranking key.

**Card V2 — BUILT, TESTED, NOT REGISTERED** (`src/analysis/best_bets_card.py`,
`DAILY_CARD_BEST_BETS_V2`). Ranks by
`score = p − (1−p)/(d−1)` — a Kelly fraction on the marked-down probability,
i.e. value × probability as one number. Price band −160..+250.
`required_edge(price) = BASE_EDGE × d(price)/d(BASE_PRICE)` — the margin
WIDENS with the odds. `MARKDOWN = 0.038`, `BASE_EDGE = 0.010`. Gates G1-G14,
applied G11 → G14 → G12. Frozen calibration at
`data/processed/card_v2_frozen_params.json`, sha256
`674790B50879B8FAB6F73710CD69F134D521729800F6BD103DC7742C6841D36A`, fit on
2025 only, deterministic across two runs. Four variant arms A1-A4 over one
shared pool (`src/analysis/card_variants.py`), pool_hash over the POOL.

**The underlying probability model** (`src/analysis/strength.py`): Poisson run
means from team runs scored/allowed, shrunk to league rate by the log5
odds-ratio rule, then a joint grid read for moneyline, run line and total so
they cannot disagree. `DISPERSION = 2.3352`. Its own docstring is honest that
**lineups, park and weather are ignored entirely** — "Coors Field is priced
like Petco."

## 5. Major results — the nulls matter most

| Result | Where | What it says |
|---|---|---|
| Phase 2A | evolab | Essentially no LINEAR incremental information beyond the MLB closing market in ONE tested setup. Empty L1; L2 about **+0.0000412 log-loss/game WORSE, p≈0.914** |
| Evolab Phase 2B | `docs/EVOLAB_PHASE2B_RESULTS.md` | `BELOW_PLACEBO_CEILING`, PBO 0.61. The evolutionary-search direction was killed by its own pre-registered criterion |
| SR1 home-underdog | `docs/SR1_RESULT_2026-09-16.md` | Band A −3.51pp (2023); band B +7.77pp (2023) → −2.14pp (2024), a sign flip. Dead |
| Stage 2 detectors | `docs/RESULTS_STAGE2.md` | No detector beats the market's own price. One eye-catching row (platoon_mismatch +10.5% ROI, n=104) explicitly flagged as noise, not promoted |
| Card model vs base rate | `docs/THE_CARD.md:60` | "+0.0012 nats" — **but see §7, this was produced under a calibration leak** |
| Price band, live money | `docs/PRICE_BAND_EVIDENCE_2026-09-17.md` | 7 days, 48 of 48 picks were FAVOURITES. Split at −160: in-band 62.5% hit / +2.07u; worse-than-−160 **66.7% hit / +0.31u**. Winning more often, earning nothing |

**There are no positive results.** Nothing has survived.

## 6. Known leakage and data problems — a reviewer should attack these first

1. **The V1 calibration was refit nightly ON THE SEALED WINDOW** until
   2026-09-15. `b` wandered 0.708 → 0.769 → 0.735 across six days.
   Frozen on owner order; freeze verified to have held. **Every card
   published 09-10 to 09-15 ran under this.** The first frozen-calibration
   day (09-16) was the worst day on the board. That is ONE day and proves
   nothing, but it is a testable prediction.
2. **The pre-registration cites 38 `scratchpad/...` sources. Zero scratchpad
   files have ever been committed to this repository.** The registered
   MECHANISM traces to real committed scripts; every number computed ABOUT
   the rule does not. See `CONTRADICTION_LEDGER.md` C1. **V2 registration is
   currently HALTED over this.**
3. **Probable-starter historical replay issue** — starter identity/scratch
   sensitivity. UNKNOWN to this handoff exactly which conclusions survive it;
   flagged for the autopsy.
4. **An F5 results file that has never existed** is loaded nightly by
   `src/engine/settle_slate.py:418` via `run_settle()`, returning `{}`
   silently. Every nightly engine settle has run with empty F5 results.
5. **Historical odds grid's finest gap is 177 minutes** — may be too coarse to
   see intraday market microstructure at all. A null on line-movement
   hypotheses could mean "no effect" OR "cannot see it"; experiments must
   distinguish those.
6. **The test suite's own failure count swung 18 → 43 on one identical tree**
   (roadmap H7). Until fixed, "the suite is green" is not a reliable claim.
7. **The whole-suite forward-store guard had never run on Windows** while
   printing a false reason for skipping. Fixed 2026-09-17.

## 7. Definitional drift — likely source of a wrong number

Found 2026-09-17, mostly unresolved:

- **"confidence"** = the MARKET consensus probability in V1
  (`daily_card.py:431`), and the MODEL's marked-down probability in V2
  (`best_bets_card.py`). **Both rules run side by side.** Any comparison
  joining on `confidence` compares two different physical quantities.
- **"grade"** has at least FOUR unrelated senses on pick-like records: data-timing
  A-D (`src/core/asof.py:58`), settlement outcome (`card_ledger.py:619`),
  information-completeness (`nfl_grade.py`), capture-cadence health
  (`cadence.py:146`). `nfl_card.py:230` reads a bare `entry.get("grade")`.
- **"value"** = market-only price standing in `priceverdict.py:25`
  (`value_points`, explicitly "Not a model"), model-based in V2's
  `passes_value_test()`. And "STRONG VALUE" is customer-facing while
  `docs/PRODUCT_DESIGN_HANDOFF.md:2320` says we never say "value" —
  `tests/test_customer_language.py` has no rule for bare "value".
- **CLV vs price improvement vs late move** — these ARE kept rigorously
  separate, enforced in docs and code. Good discipline; note it.

## 8. Data inventory, briefly

On disk: `data/processed/odds_multibook.jsonl` ~185k rows, 11 books;
`data/historical/statcast` 94 window files, ~1.43M pitches for 2023-24;
`data/historical/lineups.jsonl` 5,003 rows with `observed_utc`;
2025 pitcher logs 8,830 appearances / bullpen 27,483 / boxscores 74,189;
weather forecasts; `data/watch/*_watch.jsonl` including umpires.
BALLDONTLIE ALL-ACCESS was bought — **what is actually wired vs discussed is
UNKNOWN to this handoff**; `src/providers/balldontlie.py` exists.
API-Tennis was trialled and **SKIPPED** on 2026-09-17: price latency median
54.0s against a 10s bar, 104 moments priced while suspended, second-set
markets quoted on 59.9% of matches against 80%.

## 9. What the owner actually wants — verbatim

- *"The goal is to find the best bets for the day, not the best favorites."*
- *"we need an algorithm of value x confidence / likelihood"*
- *"+100 to +250 picks offer really good value"*
- *"I need you to forward test different strategies every day, not just a
  blanket statement of 'oh, let's go with the home team'... We're looking for
  player props. We're looking for things that we can find statistics on,
  historical data, and make an accurate estimate."*
- *"exactly why we dont just pick the favorites or no underdogs, thats just
  never gonna be a winning strategy hence why were looking for VALUE and
  PROBABILITY algorithm"*

Full chronology: `BREY_FEEDBACK_LEDGER.md` in this directory.

## 10. Open disagreements

- **Should V2 publish while unregistered?** No — registration is a gate, not
  paperwork. But V1 publishes prices the owner has ruled out every day it
  waits. That cost is real and currently being paid.
- **Should the owner see which variant arm is winning?** He asked to. The
  registration refuses it (a number you can watch is a number you steer by).
  Decided by Claude under delegation, 2026-09-17. **A reviewer should
  challenge this decision.**
- **Is the card's model probability price-independent?** `strength.py` reads
  no prices, but `src/analysis/families.py:22` asserts "no independent model
  probability exists anywhere in this project". Unresolved. V2's entire value
  claim depends on the answer.

## 11. Key paths

| What | Where |
|---|---|
| Live card rule | `src/analysis/daily_card.py` |
| V2 rule | `src/analysis/best_bets_card.py` |
| Variant family | `src/analysis/card_variants.py` |
| Probability model | `src/analysis/strength.py` |
| Props model | `src/analysis/playerprops.py` (`RHO = 0.05065`) |
| Registration | `docs/PREREG_CARD_V2.md` |
| Registry | `src/research/alpha_registry.py` |
| Validation bar | `docs/VALIDATION_CRITERIA.md` (300 picks, CLV primary) |
| Promotion gate | `docs/ARCHITECTURE_BETTING_ENGINE.md:326` (G6: ≥300 selections, ≥60 ledger days) |
| Ledgers | `src/appstate/card_ledger.py`, `live_ledger.py` |
| Never-ran register | `docs/NEVER_RAN_REGISTER.md` |
| Live-money price finding | `docs/PRICE_BAND_EVIDENCE_2026-09-17.md` |

## 12. Glossary

**CLV** — closing line value; taken price vs where the market closed. The
primary metric. **Price improvement** — best available price vs de-vigged
consensus at ONE instant; a cross-book spread, NOT CLV. **Late move** — how
the consensus moved; never to be called CLV. **Unit** — a stake size the
reader chooses; never a dollar amount. **ROI per unit staked** — units won ÷
bets made; NOT bankroll growth. **Marked-down probability** — our number
minus `MARKDOWN` (0.038), a haircut for our own overconfidence.
**Fill** — a card entry that is not a pick; fails G3 or G7, labelled as not a
pick. **SPLIT** — model and market disagree; the label is lowered rather than
the pick dropped. **Sealed window** — 2026-01-01 to 2026-08-27, never read.

---

# QUESTIONS FOR CHATGPT

Challenge us on these. Where you think we are wrong, say so directly.

**On the nulls**
1. Phase 2A tested one target, one model family, one representation, one
   market, one prediction time. Which of those five does the project now
   treat as though it were all five?
2. A zero-survivor registry after 92 hypotheses — how would you distinguish
   "the market is efficient" from "the search space was narrow"? What test
   separates them?
3. Evolab Phase 2B died `BELOW_PLACEBO_CEILING` with PBO 0.61. Does that kill
   evolutionary search, or that parameterisation of it?
4. "+0.0012 nats over the base rate" was produced under a calibration leak
   that would, if anything, FLATTER the model — and the conclusion drawn was
   conservative (never rank by the model's own disagreements). Is a
   conservative conclusion from a contaminated number safe to keep?

**On representation and structure**
5. Which rejected variable concepts were rejected on ONE representation?
   `strength.py` uses runs scored/allowed per game shrunk to league rate —
   what does that representation destroy?
6. The model ignores lineups, park and weather entirely, by its own docstring.
   Is that a defensible simplification or the main problem?
7. Where does early aggregation destroy signal? Specifically: 1.43M Statcast
   pitches exist and the model consumes team run averages.
8. Should the probability model be distributional per-market rather than one
   joint Poisson grid read three ways?

**On market and time**
9. Is the closing line being used as benchmark, feature, target, or oracle —
   consistently? Where is it used two ways at once?
10. Our finest historical odds gap is 177 minutes. Which hypotheses are
    untestable with that cadence, and are we mistaking "invisible" for
    "absent"?
11. Which market × prediction-time cells are genuinely untouched? We suspect
    props × post-lineup and alternates × any.
12. What is knowable BEFORE the market fully prices it, that we already
    capture?

**On the product's own premises**
13. Nobody has tested whether our stated confidence predicts our own accuracy.
    The card ranks by it. Is ranking unsupported until that is run?
14. Is CLV the right primary metric for a product that may never place a bet
    at the closing price? What does CLV-primary assume about execution?
15. Is 300 graded picks a power calculation or a round number? What is the
    minimum detectable effect at n=300 for a 2% ROI edge?
16. The product wants 3-10 picks from 15 games. Is a selective/abstaining
    model measurable with the metrics we use, or do our metrics penalise
    exactly the specialist behaviour the product needs?

**On our own reasoning**
17. Which of our conclusions would a bookmaker attack first?
18. Where are we most likely fooling ourselves with multiplicity? The variant
    family is four arms on one pool with a Holm budget — is that enough?
19. `MARKDOWN = 0.038` haircuts our probability for overconfidence. Is
    haircutting a probability the right response to not trusting it, or does
    it just move the error?
20. V2's `required_edge` widens with the odds. Is that the correct shape, or
    should it widen with our UNCERTAINTY, which is not the same thing?
21. We refuse to show the owner a running per-arm scoreboard on multiplicity
    grounds. Is that defensible, or paternalism dressed as rigour?
22. Three artifacts this week outlived their inputs (a deleted store, an
    overwritten calibration, an untracked parameter file). Is that a process
    failure or an architecture failure?
23. What simple baseline have we never actually beaten — or never actually
    tried? Has anything been compared to "bet the market favourite at every
    price" or "bet nothing"?
24. Which of our research gates are protective, and which are now just
    expensive?
25. We have never run a model family other than a shrunk-Poisson generative
    model plus Platt scaling. What would you run first, and why that?
