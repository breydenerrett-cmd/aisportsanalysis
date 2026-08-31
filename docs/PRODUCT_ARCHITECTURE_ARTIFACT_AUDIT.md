# Artifact Audit: Published Claude Artifacts vs. Product

All eight artifacts read successfully via `Artifact action:"read"`. None are customer-facing product screens — they are internal narrative/planning documents written across several Claude Code sessions on 2026-08-27 (one, Nine Books, is undated but self-describes as same-day). All are static HTML snapshots (no live data refresh); none are wired to the actual `src/cli` pipeline or updated automatically. **Nothing was deleted, modified, or redeployed as part of this audit.**

## Summary table

| # | Name | What it actually is | Real data? | Snapshot date | Duplicates | Disposition |
|---|------|----------------------|-----------|---------------|------------|--------------|
| 1 | Alpha Through Delta | Project history/dossier reconciling 4 disconnected build eras | No (narrative + status claims) | Compiled 27 Aug 2026, evergreen-ish | `docs/RESUME.md`/`docs/DEBRIEF.md`-style content | INTERNAL RESEARCH |
| 2 | Zero to Edge | 13-phase, 61-task build plan / prompt queue for reaching a verdict on edge | No (plan, no data) | Evergreen | `docs/ROADMAP.md`, `docs/GAME_PLAN.md`, `docs/ALPHA_ROADMAP.md` | INTERNAL RESEARCH |
| 3 | Alpha One | "Ship log" of one night's build (pipeline stood up, tests passing) | Yes (live-verified stats: 272 tests, backfill numbers) | Snapshot of 27 Aug 2026 build state | `docs/RESULTS_*.md`, `docs/DEBRIEF.md` | LEGACY DEMO |
| 4 | Tonight's Slate | Live-data slate page with real games, odds, weather, and a fitted model's self-assessment | Yes — real games, real odds, real weather | Snapshot: MLB Thursday Aug 27 (7 games) | **Directly duplicates the purpose of `artifacts/briefing.html`** | ARCHIVE (superseded by briefing.html) |
| 5 | Nine Books | Single-issue research memo on line-shopping across 9 sportsbooks | Yes (measured live gaps: 1.85%/4.14%) | Snapshot, dated implicitly 27 Aug 2026 | `docs/MISMATCH_SCANNER.md`, `docs/RESEARCH_V*.md` | INTERNAL RESEARCH |
| 6 | The First Five | Narrative of a strategy pivot (EV model → "mismatch scanner") with one real scan run | Yes (one real 7-game scan) | Snapshot: 27 Aug 2026 scan | `docs/MISMATCH_SCANNER.md`, `docs/RESEARCH_V6_CANDIDATES.md` | INTERNAL RESEARCH |
| 7 | What Survives the Reframe | Module-by-module audit + roadmap after the mismatch-scanner pivot | No (planning/architecture prose) | Evergreen (written 27 Aug 2026) | `docs/ROADMAP.md`, `docs/EVOLUTION_LAB_ASSESSMENT.md` | INTERNAL RESEARCH |
| 8 | Start From Zero | Plain-language "catch-up" explainer of the whole project for a non-technical read | Mix: cites real findings (7 bugs, 16% tie rate, 1.85% book gap) inside prose | Snapshot: 27 Aug 2026 | `docs/DEBRIEF.md`, `docs/RESUME.md` | INTERNAL RESEARCH |

**Genuinely customer-product-shaped:** only **Tonight's Slate** (#4) is laid out like an actual product screen (a slate dashboard with real games/odds/weather and a "how to read this" panel) — and that shape is exactly what `artifacts/briefing.html` already is and supersedes. Everything else is explanatory/planning prose dressed in artifact styling, not a screen meant for repeated end-user consumption.

**Confidence:** high on classification (purpose, real-data-vs-prose, and duplication calls are well supported by the text extracted from each artifact); moderate on exact "supersedes" claims since `artifacts/briefing.html`'s current content wasn't diffed line-by-line against Tonight's Slate, only structurally compared.

---

## 1. Alpha Through Delta

**What it is:** A "project dossier" reconciling four unconnected build eras (2022-23 concept, Mar 2025 manual screenshot template, Aug 2025 Streamlit prototype, Jul 2026 Flask/CLI system) into one account of what exists vs. what's fiction, plus two urgent action items (push the local repo, rotate a leaked API key).

**Purpose:** Internal explainer / project-history reconciliation.

**Real data:** Mostly status claims about the codebase (repo empty, ~79% Alpha-layer coverage "reported, unverified", 0 graded results) rather than betting data. It is honest, self-aware prose, not a demo of output.

**Snapshot vs evergreen:** Says "Compiled 27 Aug 2026" but describes a static historical narrative — reads as evergreen reference, not a daily artifact.

**Duplication:** Overlaps heavily with `docs/RESUME.md`, `docs/DEBRIEF.md`, and `docs/REPRODUCIBILITY_AUDIT_V2/V4.md` in spirit (reconciling what's real vs. aspirational). No `artifacts/*.html` equivalent exists — this is prose, not a data page.

**Disposition: INTERNAL RESEARCH.** It's a one-time reconciliation memo with genuinely useful project-history context (the leaked API key warning in particular), not a product screen and not disposable — keep as internal record.

---

## 2. Zero to Edge

**What it is:** A 13-phase, 61-task build plan written as literal prompt blocks meant to be pasted into fresh agent sessions, taking the project from "empty repo" to "a verdict on whether the system beats the market."

**Purpose:** Strategy/roadmap document — explicitly "not a reading document, it is a queue."

**Real data:** None — it's pure planning content (standing rules, assumptions, phase dependency chain, task prompts).

**Snapshot vs evergreen:** Evergreen artifact of the project's plan-of-record at the time it was written; not tied to any one day's slate.

**Duplication:** Substantially overlaps `docs/ROADMAP.md`, `docs/GAME_PLAN.md`, `docs/ALPHA_ROADMAP.md`, and `docs/AUTONOMOUS_PLAN.md`. Given 25+ pre-registered hypotheses with zero surviving edges, some of Zero to Edge's optimistic "path to a verdict" framing is likely stale relative to later findings (What Survives the Reframe / Start From Zero already reflect the pivot away from EV modeling).

**Disposition: INTERNAL RESEARCH.** Useful historical planning artifact; the actual roadmap content should live in `docs/` going forward rather than as a separate artifact link, but it's not a "delete" candidate on its own.

---

## 3. Alpha One

**What it is:** A same-night "ship log" artifact: 272 tests passing, zero runtime dependencies, a live-verified MLB Stats API backfill benchmark (96 games in 3.4s), a component status table (de-vig math, calibration metrics, staking — all "Built"; probability model — "Does not exist"), and pricing for buying historical odds ($59 for 3 seasons of moneyline).

**Purpose:** Internal engineering/methodology status report — a "here's what got built tonight" demo, not a slate or a product screen.

**Real data:** Yes — the backfill numbers, test counts, and one live `slate` command's real (schedule/weather-only, no odds key) CLI output are real and verified live, per the artifact's own text.

**Snapshot vs evergreen:** Snapshot of a specific build milestone dated 27 Aug 2026; not a recurring page format.

**Duplication:** Overlaps `docs/RESULTS_V2.md`, `docs/VALIDATION_GATE.md`/`VALIDATION_CRITERIA.md`, and `docs/DEBRIEF.md` in reporting build/test status. No `artifacts/*.html` equivalent — it predates a working model and predates `briefing.html`'s odds-bearing output.

**Disposition: LEGACY DEMO.** It documents a since-superseded milestone (no odds key, no model yet) that later artifacts (Tonight's Slate, Alpha One) overtook within the same week. Historically interesting but stale as a reference.

---

## 4. Tonight's Slate

**What it is:** A live-feed page for one real MLB slate (Thursday, Aug 27, 7 games) showing real odds (FanDuel, de-vigged fair probabilities), real weather (Open-Meteo), and a fitted logistic regression model's calibration stats (2,428 training games, ECE 0.018) alongside its own honest disclaimer that it does **not** justify a bet.

**Purpose:** Customer-facing-shaped product screen — a slate dashboard, the same functional role as `artifacts/briefing.html`.

**Real data:** Yes, entirely — real games, real de-vigged prices, real weather, real model metrics for that specific date.

**Snapshot vs evergreen:** Explicit snapshot of Thursday, August 27, 2026's 7-game slate. Not evergreen; would go stale immediately.

**Duplication:** This is the one artifact that **directly duplicates the purpose of `artifacts/briefing.html`** — the current slate dashboard the CLI (`python3 -m src.cli brief`) generates. It reflects a specific historical state of the model (2,428 games, ECE 0.018) that briefing.html's live generation has since moved past. Consistent with the project record of zero surviving predictive edges, its own text says the model "does not justify a bet" — appropriately caveated, not a false edge claim.

**Disposition: ARCHIVE.** Superseded by the live `briefing.html` generation pipeline; keep as a dated historical snapshot of the model's Aug 27 state, not as a live reference.

---

## 5. Nine Books

**What it is:** A single-issue research memo on line-shopping: nine sportsbooks quote the same game, the project only ever stores/uses one, and the price gap between best and worst averages 1.85% (peaks 4.14%) of implied probability — framed as an "autonomous day plan" with concrete engineering tasks (capture all 9 books, best-price lookup, no-vig consensus).

**Purpose:** Internal methodology/results explainer plus a task backlog for one specific improvement.

**Real data:** Yes — the 1.85%/4.14% gap figures are described as "measured live, minutes ago, on tonight's real slate."

**Snapshot vs evergreen:** Snapshot of a specific measurement run, but the surrounding task plan (Block A/B) is evergreen backlog content.

**Duplication:** Content and the "capture all 9 books" task overlap with `docs/MISMATCH_SCANNER.md`, `docs/RESEARCH_V4_EXPLORATORY.md`/`RESEARCH_V6_CANDIDATES.md`, and likely `docs/PLAN_TWO_TOOLS.md`.

**Disposition: INTERNAL RESEARCH.** A genuinely load-bearing finding (line-shopping is the one edge that doesn't require prediction) that should be tracked in `docs/`, not just as a one-off artifact.

---

## 6. The First Five

**What it is:** A narrative of a strategic pivot: from an EV/value-betting model to a "mismatch scanner" that flags only visually-obvious talent gaps not yet priced in, motivated directly by a user quote about rejecting a Yamamoto-vs-Sale game despite good EV. Includes one real scan run against 7 real Aug 27 games (1 flagged).

**Purpose:** Internal narrative/explainer of a methodology change, with one demonstration run.

**Real data:** Yes for the scan run (4,432 games ingested, 476 pitchers, real flagged/no-play output for real games) — but framed as a story about *why* the change happened, not a reusable dashboard.

**Snapshot vs evergreen:** Snapshot tied to the first live run on 27 Aug 2026; the reasoning/rules content (suppression logic) is evergreen but now presumably encoded in the actual scanner code rather than needing to live in an artifact.

**Duplication:** Same content territory as `docs/MISMATCH_SCANNER.md` and `docs/RESEARCH_V6_CANDIDATES.md`. No `artifacts/analyze_*.html` overlap — those are single-matchup pages, this is a strategy narrative referencing a full-slate scan.

**Disposition: INTERNAL RESEARCH.** Valuable as an explanation of *why* the scanner logic exists (useful onboarding/context for Brey or a future agent), not something to keep updating as an artifact.

---

## 7. What Survives the Reframe

**What it is:** A module-by-module audit of the codebase after the mismatch-scanner pivot (what's kept unchanged, what's "demoted" — the logistic regression model becomes a control group, not the product) plus a 4-phase sequenced roadmap and a categorized research-question backlog (free/answerable now vs. blocked on a $59 purchase).

**Purpose:** Strategy/roadmap + internal architecture explainer.

**Real data:** No — pure planning/audit prose (dispositions and rationale), no live numbers beyond referencing earlier findings.

**Snapshot vs evergreen:** Evergreen planning document, dated 27 Aug 2026 but not tied to a slate.

**Duplication:** Overlaps `docs/ROADMAP.md`, `docs/EVOLUTION_LAB_ASSESSMENT.md`, `docs/EVOLAB_DESIGN.md`, and `docs/VALIDATION_GATE.md`. Explicitly documents the project's honest self-assessment ("its own diagnostic already says its ranking isn't actionable") consistent with the zero-surviving-edges record — no false-edge claims here.

**Disposition: INTERNAL RESEARCH.** A good single source of "what's real vs. deprioritized" as of that date; worth folding into `docs/ROADMAP.md` rather than existing only as a separate artifact link.

---

## 8. Start From Zero

**What it is:** A plain-language, no-jargon "catch-up" explainer of the entire project — what it is, where it started (four dead ChatGPT sessions, an empty repo), what's built, the EV→mismatch-scanner pivot story (same Yamamoto anecdote as The First Five), and a "six things worth knowing" findings list (7 silent bugs found, 16% of first-five bets tie, 14% of games flip leaders after 5 innings, zero correlation between talent gap and early scoring, 1.4 games/day clear the mismatch bar, 1.85% average book-shopping gap).

**Purpose:** One-off narrative piece / onboarding explainer for a non-technical reader (explicitly "like you've never seen it, no jargon").

**Real data:** Cites real, specific findings (bug counts, tie rate, leader-flip rate, correlation study over 953 games) embedded in explanatory prose — a mix, weighted toward narrative framing of real results rather than a live data display.

**Snapshot vs evergreen:** Snapshot dated 27 Aug 2026 ("Catch-up") capturing the project state as of that day; not meant to refresh.

**Duplication:** Overlaps `docs/DEBRIEF.md` and `docs/RESUME.md` in intent (a plain-English status catch-up), and restates findings that also live in Nine Books / The First Five / What Survives the Reframe.

**Disposition: INTERNAL RESEARCH.** Good as a single "explain it to a normal person" reference document; consistent with the project's honest zero-edge framing ("nothing has been proven to work"). Not a product screen, not disposable, but redundant with `docs/DEBRIEF.md`-style content once that's kept current.

---

## Notes on the zero-surviving-edges context

None of the eight artifacts claim a proven, validated edge. Several (Tonight's Slate, What Survives the Reframe, Start From Zero) go out of their way to say the fitted model does *not* justify a bet and that nothing has been validated — consistent with the project's actual research record of 25+ pre-registered hypotheses with zero surviving predictive edges. The one artifact showing a genuine, non-predictive advantage (line-shopping across 9 books, in Nine Books/The First Five/Start From Zero) is explicitly framed as "arithmetic, not prediction," which matches the project's honest posture rather than contradicting it.
