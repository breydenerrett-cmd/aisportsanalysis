# Beta acceptance criteria

Owner directive 2026-09-06: the beta is done when Brey can open it and do the
thirteen things below. Each point is mapped to the surface that must carry it,
the data path behind it, the check that proves it, and its status as of
`docs/BETA_GAP_ASSESSMENT.md` (recon at 16a2b97). Status: DONE / PARTIAL /
MISSING. Nothing here relaxes an evidence rule in `docs/RESEARCH_CATALOGUE.md`
or the honesty invariants in `src/ledger/records.py`.

## The one distinction the whole product turns on

**MODEL LIKES THE SIDE** and **PRICE OFFERS VALUE** are different facts and are
shown as different things.

- *Model likes the side* = the engine's `p_model` for that side is above the
  de-vigged consensus, AND its `p_model_provenance` is `model_derived`. Today
  no live system has a model-derived probability (research families V1–V5,
  F5 and totals all closed null; systems run `placeholder` or
  `market_derived` provenance, and `DecisionRecord` refuses an `edge_bps`
  on anything else). So the beta shows this panel as **NO INDEPENDENT MODEL
  YET** with the provenance word, never a fabricated percentage.
- *Price offers value* = the best available price beats the de-vigged
  consensus fair price by a stated amount (Engine 1, `src/analysis/prices.py`).
  This is line-shopping value, real regardless of who wins, and is the only
  "edge" the beta may call an edge. It is shown with the fair price, the
  book, the book count and the capture time.

A 70% favorite at a bad price must read as PRICE: OVERPRICED even while the
side panel says the market likes it.

## Vocabulary the product may use

| Word on screen | Definition | Source field |
|---|---|---|
| Implied probability | book price → probability, vig included | `src/analysis/prices.py` |
| Fair probability / fair price | de-vigged multi-book consensus (≥6 books) | same |
| Model probability | engine `p_model` **with its provenance shown** | `evidence/decisions_v2.jsonl` |
| Price value | best price minus fair price, in points and %, book named | prices + board |
| Edge / EV | only when provenance is `model_derived`; otherwise not rendered | `DecisionRecord.edge_bps` |
| Evidence tier | P1-5 rule (sample, completeness, depth, staleness, agreement); not a probability | to build |
| Verdict | STRONG VALUE / VALUE / LEAN / FAIR PRICE / PASS / OVERPRICED / FADE ALERT / INSUFFICIENT DATA, computed from price value + evidence tier by a documented, tested rule | P1-3 |

## The thirteen points

| # | Brey can… | Surface | Data path | Check | Status |
|---|---|---|---|---|---|
| 1 | see today's MLB slate | Today / Games | MLB schedule (live) + odds board (`data/processed/odds_multibook.jsonl`, baked per deploy) | staging `/games/{today}` lists every scheduled game | DONE |
| 2 | see fresh market prices | Odds board, game cards | forward capture → multibook store → hourly staging redeploy | `captured_at` on every board ≤ 60 min old during game hours; stale flag at 30 min | PARTIAL (freshness bounded by deploy cadence, not live) |
| 3 | identify the strongest current opportunities immediately | Today hero + ranked list | engine decisions (`evidence/decisions_v2.jsonl`, `paper_wagers_v2.jsonl`) + price value | a ranked list ordered by price value then evidence tier; PASS days show "nothing today" honestly | MISSING (no ranking; engine decisions not exposed to the product API) |
| 4 | understand model probability vs market probability | game card, Bet Check | `p_model` + provenance vs fair probability | both numbers side by side; provenance word shown; no edge when provenance forbids | MISSING (model panel absent by design; needs the honest NO-INDEPENDENT-MODEL rendering) |
| 5 | understand why each pick exists | game card, Bet Check "THE CASE" | `DecisionRecord.thesis` / mechanism predicates (R1) + `thesis_support` claims | every reason tagged OBSERVED FACT / MODEL INFERENCE / HISTORICAL SIGNAL / MARKET SIGNAL / UNKNOWN; NULL-family signals never appear as support (P1-4 registry test) | PARTIAL (support claims exist; provenance tags and registry gate missing) |
| 6 | see warnings and uncertainty | cards, Bet Check COUNTERARGUMENT | thin board, stale capture, missing lineup, vetoes from `decisions_v2` | warning present whenever any input is stale/thin/missing | PARTIAL (thin/stale present; lineup/veto warnings not surfaced) |
| 7 | use Bet Check on a selected wager | Bet Check | POST /betcheck | all twelve Bet Check fields in `docs/BETA_GAP_ASSESSMENT.md` §3 present; verdict word always rendered (INSUFFICIENT DATA when inputs missing) | PARTIAL (5 of 10 blocks NOT YET AVAILABLE; verdict usually absent) |
| 8 | see previous paper performance | Performance | `data/paper_accounts/*.jsonl`, `evidence/reviews_v2.jsonl`, `scorecards_v2.jsonl`, `eod_reviews_v2.jsonl` | W/L/push, ROI, odds, CLV, calibration, bankroll, drawdown; BET WON split from REASONING CORRECT | MISSING |
| 9 | trust timestamps and freshness | everywhere | capture timestamps carried through | every number shows its capture time; never a computed-now time presented as capture time | DONE for boards; MISSING for engine decisions (not exposed) |
| 10 | watch data update autonomously | Today | Actions capture → commit → deploy dispatch | staging redeploys within the hour of a capture commit without any interactive session | PARTIAL (first external run green; scheduled proof pending) |
| 11 | have capture continue when Claude is offline | – | `.github/workflows/forward-capture.yml` cron */15 | a `schedule`-event run green with its own commit; two consecutive days without an in-session capture | PARTIAL (P0-1) |
| 12 | see no broken or placeholder surface | all | – | no NOT YET AVAILABLE block on a primary screen; demo/replay clearly labelled | MISSING (5 Bet Check placeholder blocks; no demo mode) |
| 13 | understand this is probabilistic decision support | landing, Today, Bet Check | copy | disclaimer visible on every primary screen, not just the Odds board | PARTIAL |

## Non-negotiables carried into the beta

- Paper accounts only. No bet placement code, no sportsbook deep links.
- No probability, rank or edge is ever invented to fill a card. Absence is
  rendered as absence.
- Research families that closed NULL or REJECTED are never cited as support.
- Frozen decisions are shown as frozen: the product reads the ledgers, it
  does not re-decide.
- Demo / historical replay is labelled on every surface it touches.

## Order of work implied

P0-1 (capture offline) → P0-2 (daily loop offline) → P0-3 (evidence-based
health) → P1-4 signal registry → P1-1/P1-2 engine-decisions-to-product bridge
and ranked slate → P1-3 Bet Check verdict → P1-5 evidence tiers → P1-6
Performance → P1-7 demo mode → P2 onboarding/feedback.
