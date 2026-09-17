# Where this project disagrees with itself

Written 2026-09-17. Ordered by what depends on the contradiction, not by how
interesting it is.

---

## C1 — The pre-registration cites 38 sources that have never existed. **BLOCKING.**

| | |
|---|---|
| SOURCE A | `docs/PREREG_CARD_V2.md` — 38 citations to `scratchpad/...` paths as the source of its computed numbers |
| SOURCE B | `git ls-files \| grep "^scratchpad/"` → 0 files. `ls scratchpad` → absent. `git log --all --diff-filter=A -- "scratchpad/*"` → empty. **No scratchpad file has ever been committed to this repository.** |
| WHAT CONFLICTS | A pre-registration's entire function is to be checkable by someone who does not trust the author. Every number this document computed for itself is sourced to code that no independent reader — including us, later — can run. |
| LIKELY EXPLANATION | The work was done in a session-local scratch directory and never committed, and nobody noticed because the numbers looked fine in the document. |
| VERIFIED | Yes, directly, this session. |

**What is and is not affected — this distinction matters and must not be lost:**

REPRODUCIBLE, traced to committed sources: the registered MECHANISM. `MARKDOWN=0.038` and `BASE_EDGE=0.010` → `docs/PROP_CALIBRATION_2026-09-14.md` via `scripts/probe_prop_calibration.py` (commit 4d735318). `DISPERSION=2.3352` → `scripts/test_run_dispersion_2025.py` (130d1a34). `RHO=0.05065` → `scripts/test_prop_dispersion.py` (75d11bee). The rule itself can be checked.

NOT REPRODUCIBLE: everything computed *about* the rule. Section 14's headline illustration of what V2 would have published; section 1.1's "1,753 of 1,901 rows, 92.2% sealed contamination" (which **drives the decision to fit on 2025** and carries no exploratory caveat); section 11.4's "6,952 to 19,311 bets" power figures (which underwrite a registered timeline); sections 4.4/4.5's robustness tables; the "0 violations" copy checks; section 17's multiplicity budget arithmetic.

**Worse than 14.3b.** Yesterday 14.3b was flagged NOT REPRODUCIBLE. Sections 14.1–14.4 share both of its defects — missing script AND the overwritten calibration — and carry **no such banner**. A reader who stops before 14.3b would reasonably believe the headline illustration is solid.

**CONSEQUENCE, and this is a decision not a suggestion: V2 registration is HALTED.** Registering freezes a document as the project's contract with itself. Freezing one whose numbers cannot be checked would make the registration ceremonial. See "What happens now" at the end.

---

## C2 — The canonical card document still presents leaked numbers as findings. **HIGH.**

| | |
|---|---|
| SOURCE A | `docs/THE_CARD.md:196-207`, last touched commit 9d9b8ebd, 2026-09-10 — presents in the present tense, with no caveat: walk-forward log-loss 0.69137, Brier 0.24905, accuracy 53.5% over "1,896 games, 2026-04-15 to 2026-09-06"; "the model beats a coin that knows only the home-field base rate by 0.0012 nats"; fitted `b ≈ 0.51`/`0.708` described as "Tested, and the worry was wrong"; a win-rate/ROI table over 2026-08-31 to 09-10 |
| SOURCE B | `docs/CARD_V2_DIAGNOSIS_2026-09-15.md:33-52` names `THE_CARD.md:197-199` by line number as contaminated, and `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md` states "no V1 closing-line or return verdict can be drawn from that record" |
| WHAT CONFLICTS | The document a reader goes to for "what do we know about the card" asserts numbers that two sister documents say cannot be trusted. Every date in that table is inside the sealed window. |
| LIKELY EXPLANATION | The fix was scoped as T11 in `docs/CARD_V2_BUILD_PLAN.md:1235-1237` and never landed. |
| CHECKED | The stale figures ("0.0012 nats", "53.5%", "0.00089") do **NOT** appear in `src/report/`, `web/` or `api/`. This is an internal-truth problem, not customer deception. |
| WHAT MUST BE VERIFIED | Whether the 0.0012-nats figure, quoted onward by `docs/EDGE_SEARCH_2026-09-10.md` and `docs/PREREG_RUN_DISPERSION.md` as live justification, is load-bearing for any decision still standing. |

**Why this one is insidious:** the 0.0012-nats figure is cited repo-wide as the reason the model is never ranked by its own disagreements. That is a *conservative* conclusion drawn from a *contaminated* number. The contamination would, if anything, flatter the model — so the conservative choice is probably still right, but it is right by luck, and the number behind it cannot be quoted.

---

## C3 — "No independent model probability exists" versus a model that appears independent. **HIGH, UNRESOLVED.**

| | |
|---|---|
| SOURCE A | `src/analysis/families.py:22` — "No independent model probability exists anywhere in this project (`edge_bps` is structurally null; see `src.ledger.records`)" |
| SOURCE B | `src/ledger/records.py:92-122` enforces that `edge_bps` may be non-null ONLY for `model_derived` provenance — a probability "fitted on information independent of the price being compared against". Meanwhile `src/analysis/strength.py:286` `run_means()` builds its probability from team runs scored/allowed per game, shrunk toward league rate; `market_probabilities()` takes only the two Poisson means. Neither reads a price. |
| WHAT CONFLICTS | Either families.py's flat assertion is stale/scoped-to-the-engine-track and the card's probability IS independent, or the card's probability is not what it appears and V2's value comparison is circular by the project's own standard. |
| WHY IT MATTERS MOST | **V2's entire premise is comparing our number to the price.** If our number were market-derived, `score = p − (1−p)/(d−1)` would be arithmetic on the price against itself. The evidence says it is NOT — strength.py reads no prices — but a load-bearing comment in the codebase says otherwise and must be reconciled before anyone relies on the comparison. |
| WHAT MUST BE VERIFIED | Trace the card's `model_probability` from `features` → `run_means` → `market_probabilities` → the Platt calibration, and confirm no stage admits a price. Note the calibration IS fit on outcomes, which is a separate question from price-independence. Then correct whichever of the two statements is wrong. |

---

## C4 — Product copy versus what the live rule can do. **MEDIUM.**

| | |
|---|---|
| SOURCE A | The owner's requirement, 2026-09-15: best bets not favourites, nothing below −150/−160 |
| SOURCE B | `src/analysis/daily_card.py` ranks by market confidence with no price test; measured output is 48 of 48 favourites, 7 at −200 or worse, worst −230 (`docs/PRICE_BAND_EVIDENCE_2026-09-17.md`) |
| WHAT CONFLICTS | The live rule structurally cannot satisfy a requirement made two days ago, and V2 which would is not registered. |
| STATUS | Known, tracked as Stage 18 F3. Recorded here because C1 has now DELAYED the fix, which makes this contradiction older, not resolved. |

---

## C5 — Definitional drift: "edge", "value", "price improvement", "CLV". **MEDIUM.**

| | |
|---|---|
| SOURCE A | `src/pipeline/snapshots.py:844` `closing_line_value()` — taken price versus where the market closed. Genuine CLV. |
| SOURCE B | `src/analysis/prices.py` `improvement_points` — best available price versus the de-vigged consensus at one instant. A cross-book spread, NOT a time-series measurement. |
| SOURCE C | `edge_bps` in `src/ledger/records.py` — model probability minus fair probability, structurally null absent a model-derived probability. |
| WHAT CONFLICTS | Three different quantities, all colloquially "how much better we did than the market". `ranker.py` and `dashboard.py` were checked and correctly say "price improvement" and never "edge" — that discipline is real and should be preserved. |
| RESIDUAL RISK | The three are *currently* kept apart in the modules checked. The risk is a future surface pooling them. Worth a test that fails when one module's word reaches another's number. |

---

## C6 — Five scheduled paths that have never produced anything. **MEDIUM.**

Covered fully in `docs/NEVER_RAN_REGISTER.md` (commit 623f2b03) and not restated here. The live-window trio, the NFL card (since fixed), and an F5 results file that `settle_slate.py:55` and `cli.py:2722` both load and which has never existed. The contradiction is between "wired into a schedule" and "has never produced an artifact".

---

## SUSPECTED — not proven this pass

- **S1.** Whether `docs/CARD_V2_DIAGNOSIS_2026-09-15.md` and `docs/CARD_V2_BUILD_PLAN.md` have the same missing-source disease as C1. Same authors, same week, same habits. Settling it: repeat the grep-for-scratchpad method on both.
- **S2.** Whether `PREREG_CARD_V2.md` has ever been through the independent reproduction process that `docs/REPRODUCIBILITY_AUDIT_V2.md` and `_V4.md` applied to Research Families V2 and V4 (which reproduced ~200 numeric fields exactly and self-flagged their one unpinned reconstruction). Evidence suggests not. Those audits demonstrate the standard this codebase CAN meet, which makes C1 a regression rather than a limitation.
- **S3.** Whether the roadmap's older "already fetched/built" claims hold. Two were spot-checked under W-18 (Statcast held exactly; box-score counts off by +1 in two of three seasons). The rest are unchecked.

---

## What happens now

1. **V2 registration is halted** until C1 is resolved. Not abandoned — halted.
2. **The resolution is not to re-run the missing scripts.** They are gone and re-deriving every illustration would take days the product does not have while V1 publishes −230 favourites. The resolution is to **separate the mechanism from the illustrations**: the mechanism is reproducible and can be registered; every number sourced to a missing scratchpad file gets 14.3b's banner, verbatim and without exception, or is deleted. A registration may contain an unreproducible illustration that says so. It may not contain one that does not.
3. **C2 is fixed by landing T11** — mark THE_CARD.md's evidence section as produced under the leak, keeping the text as history.
4. **C3 must be resolved before V2 registers**, because V2's core claim depends on which statement is true.
