# DEBRIEF — full project catch-up

**Written 2026-08-31 ~20:15 UTC.** One authoritative document for a reader with
no access to prior conversation. Every number here is either verified live at
that timestamp or quoted from a document named beside it. Where a fact is not
measured, it says "not measured" rather than guessing.

Repo: `aisportsanalysis`, branch `claude/sports-betting-analysis-review-g1o0co`,
clean, all pushed. Owner: Brey (breydenerrett@gmail.com).

---

## A. ORIGINAL GOAL

Build software that finds MLB bets worth making, and that explains itself well
enough that a knowledgeable bettor learns something.

**Success is defined by evidence, not by output.** The pre-registered bar
(`docs/VALIDATION_CRITERIA.md`, written before any model existed): closing-line
value is the pass/fail metric, ROI secondary; ≥55% of picks beating the close
and mean CLV ≥ +1.5%, on a **floor of 300 graded forward picks** — below 300 no
verdict is drawn whatever the numbers say. A stop is an acceptable outcome.

**The data split, non-negotiable:** 2023–24 discovery · 2025 tuning-only forever
(its `2025-08-26..2025-09-28` sub-split is already burned by four looks) ·
**2026-01-01 → 2026-08-27 SEALED**, one evaluation ever, only after a policy
freeze plus Brey's explicit go · 2026-08-28 onward is forward proof, never
folded back into tuning.

**Permanent hard rules:** no real-money betting and no bet-placement code, ever ·
never fabricate a value (`None` over a guess) · no future leakage · pre-register
before inference · publish every loser · FDR over the full pre-registered family ·
falsification battery before any promotion · **line-shopping value is PRICE
IMPROVEMENT, never EV or "edge"** · never call a decision-to-late-move delta
"CLV" · zero survivors is a valid result and an edge is never manufactured.

---

## B. CURRENT PRODUCT

Two tools, deliberately split because they need different standards of proof
(`docs/PLAN_TWO_TOOLS.md`, now the historical design record — every work item in
it shipped).

**The Analyzer — shipping, user-facing, polished.** Deep per-matchup analysis
whose job is to make a bettor better informed, not to promise profit. What it
does today:

- One card per game for tonight's slate (`python3 -m src.cli brief`), plus
  arbitrary matchups (`analyze --away NYY --home BOS`, real games resolved
  point-in-time, hypotheticals rendered with their gaps named).
- Eleven detectors, each stating a claim in plain language with its sample size
  inside the sentence and an **evidence label** attached; the eight that were
  tested carry `TESTED_NULL` ("Tested — no edge") and rank *below* open
  questions, so a refuted claim with a big number cannot lead the page.
- A **synthesis layer** — the ranked "3–5 things that matter tonight" block.
- **Debunks as a feature:** "he's 7-for-18 lifetime against this pitcher — that
  is 18 at-bats and it means nothing."
- Matchup depth (this lineup's hitters vs this starter's pitches, counts shown),
  starter "stuff" (velocity gap vs league, career ground-ball share), a
  "what changed" roster-event section with descriptive relevance tiers built
  only from pre-cutoff data, price-improvement figures, per-game permalinks and
  a season archive index.
- **"No play" is a real answer**, and most nights it is the right one. A page
  header states plainly that nothing here is a proven edge.

**The Ranker — built, shipped as a shell, GATED.** Two engines, deliberately
separate. Engine 1 (price improvement: best available vs de-vigged consensus,
dispersion, the gap) works. **Engine 2 (predicted value) is empty because
nothing has been proven.** The Ranker's output is Engine 1 × Engine 2, so it
ranks nothing — and a **test enforces the gate**, so it cannot be removed by
accident. It unlocks only on all four conditions: a pre-registered hypothesis
clearing significance *and* effect-size gates on discovery data; surviving the
falsification battery; holding on 300+ forward selections it was never fitted
to; and Brey signing off on a decision-policy freeze.

**A mismatch scanner** also runs, flagging candidate games (fires on ~10.2% of
games, ~1.4/day, before the market screen) and routing them to the first-five
moneyline. It is a logged forward experiment, not a product claim.

---

## C. CURRENT ARCHITECTURE

**Three execution tiers (set 2026-08-31 by Brey's master directive).**

| tier | who | what |
|---|---|---|
| Orchestrator | Fable 5 | decisions, task decomposition, verification standards, talking to Brey |
| Workers | Opus 5 | implementation, research, red-teaming. Persistent definitions in `.claude/agents/opus-{research,data,builder,product,validator,redteam}.md`; tasks handed over as OBJECTIVE / WHY / INPUTS / BOUNDARIES / DELIVERABLE / ACCEPTANCE / EVIDENCE RULES. High-impact work gets a second worker attacking the first's deliverable. |
| Deterministic scripts | no model | routine collection: `scripts/forward_capture.sh` (hourly), `scripts/daily_loop.sh` (daily 10:00 UTC). A no-op capture must never consume model reasoning. |

**Trigger and escalation plane.** The hourly trigger runs watch + dense odds grid
+ F5 close pass; the daily trigger runs snapshot → ingest → briefing → settle →
grade; a 4-hourly model session works the roadmap queue. Both scripts commit and
push their own data changes and print `ESCALATE:` lines for the only four
conditions that need a human or a model: credit floor, missed capture window,
settlement gap, crash. **A model reads only the ESCALATE lines.**

**Research machinery** (`src/research/`): `matrix.py` builds the point-in-time
matchup matrix (sealed seasons refused structurally); `funnel.py` compiles a
frozen family spec into the fixed pipeline — coverage → 2023 screen → 2024
replication → pooled → BH-FDR at q=0.10 over the *full registered denominator*
(early deaths enter at p=1.0) → automatic falsification battery; `battery.py` is
the battery, frozen at **RULES_VERSION 2.0.0** with a content fingerprint
(`ac74c7a7f715f9ec`) echoed into every verdict. Supporting cores: `pricepath`,
`eventstudy`, `leadlag`, `coverage`, `elobench`, `f5_store`, `timingreport`,
`scoreboard`, and one module per V2 hypothesis (`m1`–`m5`).

**Falsification battery** — season split, team concentration, book
concentration, extreme-date removal, dose-response, plus the funnel's upstream
screen/replication gates. Two fatal rules were amended after it failed on M3
(see F) and were validated as *general* skeptical rules against a six-case
generality matrix, a 15-comparison old-vs-new shadow run (only M3's verdict
changed) and an independent adjudication returning `gate_open=true`
(`docs/VALIDATION_GATE.md`).

**Evidence packages.** Every major evaluation writes an immutable package — code
commit, family version, policy version, input hashes, price definitions, exact
selection set, exclusions, sample sizes, results, CIs, FDR output, robustness
output, timestamp. An evaluation that cannot be reproduced from its package is
incomplete. Frozen artifacts live in `data/research/` (family JSONs, results
JSONs, matrices, scoreboard, shadow battery report) and `evidence/`.

**Forward ledger** (`src/pipeline/ledger.py` → `evidence/forward_ledger.jsonl`,
append-only, 160 rows). Records what the system would have bet, at what price,
before the game; settles afterwards. Five price concepts are kept strictly
separate — recommendation price / best available at recommendation / consensus
at recommendation / `late_move` snapshot / true close — and `late_move` is
**never** called CLV.

---

## D. DATA ASSETS

Verified 2026-08-31 ~20:15 UTC unless noted.

| asset | count | note |
|---|---|---|
| Game results store | **9,319 games**, span 2023-03-01..2026-08-30 | 871 dates with games; **251 dates inside the span never fetched** (holes, being backfilled); 122 unresolved |
| Statcast pitch store | **180 windows, 2,737,968 pitch rows** | rebuilt point-in-time, carries `bb_type` (present on 17.4% = the balls-in-play rate), 0 failed windows |
| Forward h2h snapshots | `data/processed/odds_snapshots.jsonl` — **894 rows**, 2026-08-27..08-31 | verified by line count |
| Forward multi-book boards | `data/processed/odds_multibook.jsonl` — **981 rows**, 2026-08-31 only, **11 books** | store is one day old |
| F5 closes | `data/processed/f5_close.jsonl` **DOES NOT EXIST** | the F5 close pass has produced nothing; under active repair |
| Watch stores | lineups 44 · probables 47 · transactions 54 rows | `data/watch/*.jsonl`, verified |
| Forward ledger | 160 rows = 58 games recorded, 46 settled, 12 pending | `evidence/forward_ledger.jsonl` |
| Historical odds backfill | 1,800 snapshots, 7,439 games matched to a near-closing price (2026-08-28 log) | median gap to first pitch 84 min; 74–75% inside 3h; books/game 18 (2023) → 12 (2024) → 11 (2025), market consolidation not coverage decay |
| Historical first-five | 661 games (2023: 265, 2024: 189, 2025: 207) | prop/F5 history begins ~May 2023 |
| F5 settlement store | 181 dates, 2,512 games, **0 odds credits** | free MLB StatsAPI linescores |
| Pitcher game logs / bullpen / arsenals | 40,289 appearances · 1,004 bullpen rows · 1,071 pitchers, 956 hitters | 2026-08-28 log |
| Posted lineups (historical) | 4,892 games of 2023–24 with handedness for 799 players | |
| Frozen research artifacts | 8 files in `data/research/` | md5-verified unchanged across the V4 reproducibility audit |

---

## E. RESEARCH HISTORY

**The headline, stated explicitly: the current number of demonstrated
predictive edges is ZERO.**

### V1 — single-feature baseball detectors (`docs/RESULTS_STAGE2.md`)

*Question:* do we read baseball better than the market? *Registered:* 21
detector×market hypotheses over 11 detectors, frozen 2026-08-28. Ran
point-in-time on 4,859 games (4,395 priced), 26,932 findings, effects vs
de-vigged consensus, date-clustered throughout. 8 detectors produced
side-bearing selections; 3 are side-less by design.

**Outcome: ZERO of 8 clear BH-FDR q=0.10 plus a 1pp effect floor. Every interval
includes zero.**

| detector | n | effect | clustered 95% CI | p | ROI | 2023 / 2024 |
|---|---|---|---|---|---|---|
| bullpen_exposure | 1508 | +1.65pp | −0.70..+4.04 | .18 | +2.2% | +0.72 / +2.61 |
| bullpen_workload | 2499 | +0.79 | −0.81..+2.34 | .32 | +0.1% | +0.61 / +0.97 |
| pitch_mix_mismatch | 3339 | +0.60 | −0.74..+2.07 | .40 | +0.0% | +1.15 / +0.05 |
| platoon_mismatch | 104 | +3.84 | −5.79..+13.37 | .44 | +10.5% | **−15.5 / +17.5** |
| starter_mismatch | 2295 | −0.75 | −2.74..+1.27 | .48 | −2.9% | +0.10 / −1.64 |
| travel_load | 604 | +0.38 | −3.40..+4.24 | .85 | −0.4% | +4.28 / −3.60 |
| stale_book | 2949 | +0.03 | −1.35..+1.48 | .97 | −1.0% | +0.51 / −0.69 |
| lineup_vs_starter | 26 | — | — | — | — | below the 30-selection floor, no verdict computed |

`late_move` is ~zero (+0.000 to +0.002) for every detector — the market does not
even *drift* toward these ideas. `platoon_mismatch`'s +10.5% ROI is 104 games
whose seasons point in opposite directions: the definition of noise.

### V2 — market structure (`docs/RESEARCH_V2.md` → `docs/RESULTS_V2.md`)

*Question:* forget out-analyzing the books — does the market misprice *itself*?
Five hypotheses, 2023–24 only, **zero credits**, run 2026-08-29. **Zero
survivors.**

- **M5 (de-vig method choice)** — NULL. n=4,486; log loss agrees to the fifth
  decimal across proportional / additive / power / Shin; the "best" method flips
  between metrics. Two keepers: proportional stands system-wide; Shin is
  *identical* to additive on two-way markets to 13 decimals.
- **M1 (price-change reversal, from a 2024 Management Science result)** — NULL
  **and the sign is wrong**: 62,183 consecutive change pairs, lag-1
  autocorrelation **+0.013** (p=0.13) — weak momentum, not reversal. Fading
  loses 3.5%, following loses 3.3%; both pay the vig. Honest limit: the paper had
  tick data, we have 4–5 snapshots/game.
- **M3 (cross-book dispersion)** — the canonical **FALSE POSITIVE**, see F.
- **M2 (weekend day-game staleness)** — INCONCLUSIVE on resolution, not on
  evidence: the strict test qualified only **197 games in two seasons, three of
  them weekend afternoons**.
- **M4 (F5 vs full-game bullpen gap)** — UNDERPOWERED: 308 games with both
  prices, 270 decided, 38 ties (**14% of F5 moneylines end level**). F5 price is
  well calibrated (+1.25pp, p=0.67). "We cannot tell", not "the market is right".
  It also recorded a trap: at 217 games the buckets showed a clean monotone
  gradient (+8.3, +7.2, −5.3, −0.8, −0.6) that **dissolved** with the full sample.

### V3 — information timing / market microstructure — **OPEN, LIVE**

See section H. Frozen 2026-08-31, forward-only, denominator 4 admitted classes.
**No event-response result exists anywhere yet**, and by construction V3 claims
**no edge**: measurable latency is a *necessary* condition for a timing edge,
never sufficient — executability, limits and price-vs-fair stay separate
questions.

### V4 — exploratory interactions (`docs/RESEARCH_V4_EXPLORATORY.md`)

Six unit-vs-weakness interaction specs, byte-frozen after the validation gate
opened; thresholds set at the pooled p70 of |signal| from **feature
distributions only**. Run 2026-08-31 02:16 UTC. **Zero survivors.**

Three died in the 2023 screen pointing the wrong way (`stacked_top_platoon`
−0.98pp/856; `platoon_pressure` −0.75/243; `stacked_top_vs_pitch` −0.85/602);
two sign-flipped at 2024 replication (`handed_lineup_vs_pitch` +0.15 → −3.55;
`stacked_top_weak_starter` +0.79 → −0.44); one, `pitch_lean_vulnerability`,
replicated and reached the battery — pooled +1.06pp over 1,090 at p=0.45 and
**fatal on team concentration, book concentration AND extreme-date removal**.

### V5 — stuff decline and contact shape (`docs/RESEARCH_V5_STUFF.md`)

Three hypotheses on genuinely new store-derived features (as-of-cutoff fastball
velocity vs league; career ground-ball share), both byte-level point-in-time
injection-tested before registration. Run 2026-08-31 07:54 UTC. **Zero
survivors — all three died at 2024 replication.**

| spec | 2023 screen | 2024 replication |
|---|---|---|
| `facing_soft_stuff` | +0.27pp (n=374) | +0.46pp, wrong side of the half-floor |
| `stacked_top_vs_groundballer` | +1.96pp (n=481) | **−3.39pp — sign flip** |
| `fastball_leaning_decliner` | +1.60pp (n=371) | −0.33pp — sign flip |

`stacked_top_vs_groundballer` is the instructive one: exactly the shape the
family was built to find, 481 screen selections, and the held-out season flipped
its sign outright.

### Elo benchmark (`docs/BENCHMARK_ELO.md`)

*Question, with its answer pre-stated:* does a free public-style projection beat
the closing consensus? **Expected: no.** No external source is honestly
replayable (FanGraphs never archives game odds; FiveThirtyEight's Elo died
mid-2023 with its files gone; Savant/B-R win probabilities are retroactive, not
pre-game; free odds archives stop at 2021; tout "past picks" are self-attested),
so a pitcher-free Elo was **reconstructed** point-in-time with FiveThirtyEight's
published constants — chosen a priori, never fitted on our data. 2023 burn-in,
2,234 scored 2024 games:

| forecaster | log-loss | Brier |
|---|---|---|
| close consensus | **0.67275** | **0.23999** |
| public-style Elo | 0.68076 | 0.24391 |

Per-game differential +0.00801 (Elo worse), date-clustered p=**0.0003**. This is
now the yardstick for every data-acquisition decision: an input that cannot beat
this baseline adds nothing the market lacks.

### V6 — design notes only (`docs/RESEARCH_V6_CANDIDATES.md`, 2026-08-31)

Nothing registered, nothing frozen, no outcome column read. Twelve mechanisms
tested against a **raised bar**: a season-level feature family now needs a
mechanism the market plausibly **CANNOT** price — structural reasons only
(information the books do not consume; a market too thin to attract correcting
money; reaction-time physics). "They might miss it" is explicitly not a reason.
**Ten of twelve rejected. Zero clear the bar unconditionally. The recommendation
is to register nothing.**

Two conditional survivors: **C1 — pitcher-strikeout props posted before lineups
exist** (the strongest: fills the structural slot twice over — the lineup does
not exist when the line is made, and a 3–4-book market cannot even form a
consensus by this program's own 6-book floor; and it is the only candidate whose
prior is unspent, because every death so far was against the *h2h* close and
nothing has ever measured the *prop* close). **C2 — the F5 price as a
mechanically derived, state-dependently wrong quantity** (conditional, and not
new: it is U1/L2/B3 restated).

### Running score

Four pre-registered families against the MLB h2h moneyline — **V1, V2, V4, V5 —
zero survivors.** Plus one benchmark (the close wins decisively) and one live
family that has produced no result.

### The four lessons the record actually proves

1. **Screen-then-flip is what a dead idea looks like here.** A screen-year
   number in the right direction carries essentially no information; the
   replication season decides, and a sign flip is death by pre-registered rule
   rather than by judgement.
2. **The market absorbs season-level features — all of them, so far.** The
   conclusion is not "we measured badly": it is that the h2h close already
   carries whatever the pitch store measures. External base rate agrees — 1,547
   simple MLB moneyline strategies tested in the literature, ~0.45% profitable
   at the 1% level, which is the rate chance alone produces.
3. **Timing and market depth are the live lanes precisely because they ask a
   different question** — earlier rather than smarter, thinner rather than
   sharper.
4. **"We cannot tell" is a distinct verdict worth protecting.** N8 (26
   selections), M2 (3 qualifying weekend afternoons), M4 (270 decided games) all
   died of power or resolution, not evidence, and are recorded as such.

---

## F. IMPORTANT BUGS FOUND

The ones that materially changed trust. Each nearly produced, or did produce, a
believed result that was false.

**1. `bool("0")` is `True` — the label bug (2026-08-28, commit e80c64f).** The
results store is a CSV, so the home-win label arrives as the string `"0"` or
`"1"`. Coercing with `bool()` made every selection's outcome read as *"did we
pick the home side"* rather than *"did the pick win"*. The first run reported
`travel_load` at **+9.6 points over the market with p = 0.000002** — a
spectacular, entirely fictional edge on a detector that mostly picks home teams.
Nothing raised; every number was plausible. Caught by **one diagnostic**:
comparing the actual home win rate against the mean implied home probability,
which must agree to about a point in a calibrated market and did not. That check
now runs first on every new evaluation, and `_label` returns `None` for anything
unrecognisable so a game counts as *unresolved* rather than being silently
scored.

**2. Impossible innings-per-start, and the one-start artifact.** A starter's
innings-per-start came out at **13.56** — total innings divided by start count,
so a swingman's relief innings were attributed to his starts. Physically
impossible, silently produced, and it fed a detector claiming the bullpen would
barely be used. The mirror case: a starter "averaging 1.00 innings" who had made
exactly one start. Both mattered because they were *the product debunking bad
sample sizes while committing the same sin*; the fix is the sample-size guard
now attached to every claim.

**3. The point-in-time full-season leak — the statSplits discovery (2026-08-28,
commit 2e496e5).** MLB's splits endpoint **accepts `startDate` and `endDate` and
ignores them.** Verified directly: April only, April-through-August, and August
only for the same pitcher return byte-identical numbers — 113 batters faced
versus left-handers at a .756 OPS in every case. The same holds for Savant's
arsenal leaderboards and the `vsPlayer` matchup endpoint: all three are
season-or-career-to-date snapshots with no as-of parameter, so applying any of
them to a past game leaks results that had not happened yet. This is why the
entire 2.74M-row pitch store exists: splits, arsenals and matchup history were
**rebuilt from raw pitch-level data**, and the audit is enforced as data rather
than convention (each input declares its status; a detector inherits the worst
status of its inputs; `require_clean` **raises** rather than warns; an unaudited
input is UNKNOWN, not clean).

**4. The historical price join graded games against the NEXT game's odds
(2026-08-28, commit 65aa034).** `index_price_pairs` keyed events by
(away, home, date) with each event indexed under two dates, so in any
consecutive-day series the next game **overwrote** the previous game's key.
**55% of matched 2023 selections were priced from the following game's market,
including 1,966 whose "recommendation-time" snapshot was taken hours AFTER the
graded game had finished.** The same audit found every Diamondbacks game
silently unpriced (results store says `AZ`, the price index said `ARI`) and the
FDR gate being fed an *unclustered* p. Consequence: **every number in
`docs/RESULTS_2023_24.md` and `docs/VALIDATION_PACKAGE_1.md` is INVALIDATED and
uncitable**, including the believed +4.08pp `bullpen_exposure` candidate — which
on correct joins is +1.65pp at p=.18. The prior signal was substantially the
bug.

**5. M3 — the false positive that passed the battery and forced two general rule
amendments.** Cross-book dispersion looked like a discovery: at a 2pp deviation
threshold, 249 selections / 223 events / 162 dates, hit rate 60.6% vs 52.2%
implied, **+8.49pp, clustered p = 0.0063, CI [+2.34, +14.28], ROI +18.1%.** The
pre-committed battery killed it by hand: dose-response **inverted** (the band
immediately below the threshold, n=940, is −1.56pp); it is **one book** (FanDuel
+15.49pp on n=74, BetMGM −9.44pp on n=27; excluding FanDuel drops it to +5.53pp
at p=0.16); no season replication; one bad price makes six correlated selections
through the leave-one-out consensus; and it is a **0.4% tail** — 249 of 59,297
observations. Then the validation gate found something worse: the **automated**
battery returned `survives=True` on M3 — it passed the exact case it existed to
kill. Two rule gaps: an *unjudgeable* upper dose band was rescuing a spike over
a judged-negative lower band, and the concentration rule's effect leg held the
door open for a candidate that lost its significance and a third of its size to
one book. Both were amended as **general** skeptical rules with no M3-specific
identifier, validated against a six-case generality matrix and a 15-comparison
shadow run (only M3's verdict changed), independently adjudicated, and frozen at
RULES_VERSION 2.0.0 with a content fingerprint in every verdict. M3 is pinned as
a regression test. **An 18% ROI in a liquid market is a reason for suspicion,
not celebration.**

**6. Dense capture going blind to the West Coast slate after 00:00 UTC
(2026-08-31, commit 72c43be).** The dense grid's date handling meant that once
UTC rolled past midnight, the still-unplayed West Coast games were no longer in
window. It was **losing closing lines nightly** — the single most valuable
observation of the day, on the games least covered elsewhere, unbackfillable at
any price.

**7. Game identity merging a night game with the next day's matinee (same
round).** `game_key` collapsed a night game and the following day's matinee into
one identity, letting **Saturday's close settle Sunday's game**. Same family of
error as bug 4, in the forward path rather than the historical one — which is
exactly why it mattered: the forward ledger is the evidence that eventually
satisfies the Ranker's unlock condition 3, and a corrupted identity there is not
recoverable.

**8. The market board read from two stores, showing two book counts
(2026-08-31, commit fb94b4e).** The `stale_book` detector and the rendered price
table read *different* stores for the same market, so one game's card could
state two different book counts for the same board. Unified: one market, one
store. It mattered less for the number than for what it revealed — a rendering
layer can quietly disagree with the evidence layer, and a reader has no way to
tell which one is the record.

**9. `data/processed/*` was gitignored, so forward odds captures lived only on
one ephemeral container's disk (found and fixed 2026-08-31, commit 56b8ccf).**
See section I — this is the most consequential finding of the day and is
reported there in full.

---

## G. WHAT SHIPPED SINCE THE MASTER AUTONOMY DIRECTIVE (2026-08-31)

Chronological, meaningful units only, from git log (all on 2026-08-31 UTC).

| ~time | unit |
|---|---|
| 02:08 | Validation gate's M3 hole closed: general battery amendments, proven general (six-case matrix, shadow run) |
| 02:13–02:17 | Interaction features in the compiler; gate adjudicated open; **V4 registered, run once, zero survivors** |
| 03:20 | Roadmap gains its permanent AUTONOMOUS CONTROL section (continuous loop, ready queue, hard gates) |
| 03:24–03:27 | V3 draft pre-registration + frozen measurement core; cross-book lead/lag aggregation (the sportsbook response table) |
| 03:33–03:36 | Projection-benchmark scouting logged (no free source is replayable); **Elo-vs-close benchmark: the close wins, p=0.0003** |
| 03:38 | Analyzer matchup depth: the unit-vs-specific-weakness decomposition |
| 05:14 | **V3 frozen** (four B-grade forward classes) + `docs/COLLECTION_POLICY.md` + timestamp audit log |
| 05:43–05:46 | **V3 capture prerequisites live:** multi-book odds store, rosterwatch poller, poll-on-every-dense-moment hook, F5 close pass |
| 05:48–05:52 | Price-improvement library (Engine 1); wired into the Analyzer; **Ranker shell that refuses to rank until an edge is earned** |
| 05:59–06:11 | Any-matchup mode + `starter_velocity_gap` feature; ledger resilience (write-time dedup, settle-gap alert); V3 timing report command; narrative pass over all eleven detector claims |
| 06:36–07:49 | Savant `IncompleteRead` retry; **pitch store re-ingested with `bb_type` — 2,737,968 rows, exact parity, 0 failed windows** |
| 07:52–07:55 | `starter_groundball_share` feature; **V5 registered, run once, zero survivors** |
| 08:58 | Two-tools plan closed out: every work item shipped |
| 13:03 | Analyzer shows the starter's stuff (velocity gap, ground-ball share) |
| 14:01 | **Resource architecture:** data-plane scripts, six Opus worker definitions, four-horizon roadmap, RESUME + RUNBOOK |
| 14:08 | **Research catalogue: every idea classified under one taxonomy (73 entries)** |
| 14:09–14:10 | Slate health monitor + `health` CLI; its first finding investigated and cleared (empty lineup store is store age, not a fetch bug) |
| 14:21 | Analyzer synthesis layer: ranked "what matters tonight" per game card |
| 14:24 | **Collection red-team: six reproduced bugs fixed with regression tests** (incl. the West Coast blindness and the game-identity merge) |
| 14:42 | **Product red-team: nine rendering honesty fixes** (worst: the Ranker banner claiming every row "beats the consensus" above an all-negative board; hypotheticals rendered as real games) |
| 14:46 | **V4 reproducibility audit: reproduces exactly, bit-for-bit, from its frozen package** |
| 14:48–15:18 | Closing staleness on settlement rows + marker polled-dates; pre-event relevance tiers; product write-up batch (real denominators, scoped warnings) |
| 15:27–15:43 | **Market-board unification** (one market, one store); "what changed" roster events on game cards; per-game permalinks + season archive |
| 17:02–17:06 | **V6 candidate design notes — 12 mechanisms, none registrable today**; prop-listing probe designed and gated on Brey |
| 20:07 | **Forward odds captures made evidence: tracked instead of gitignored** |
| 20:12 | **Evolution Lab assessment**: reframe + phased plan, written before any implementation |

Plus, throughout: hourly forward captures and watch polls, and one clean daily
loop (2026-08-31, 12 ledger entries, 1 stale game settled).

---

## H. CURRENT V3 STATE

**Frozen 2026-08-31** (`docs/RESEARCH_V3_TIMING.md`). Nothing below changes
because early results disappoint.

*The question:* when genuinely new information enters, how quickly do books
react, which react first, how large is the adjustment, and does an observable
stale-price window exist? **Not** "did the team win".

**Family denominator: 4 admitted classes**, all grade B (bracketed between our
own polls), all forward-only:

| class | admitted-B mechanism | events / admissible / measurable @ 20:15Z |
|---|---|---|
| `lineup_posted` | bracketed between successive rosterwatch polls | **13 / 13 / 0** |
| `il_roster_move` (runtime: `transaction_first_seen`) | transaction id first seen between polls | **21 / 20 / 0** |
| `starter_scratch` | probable-pitcher change between polls | no events reported |
| `hitter_scratch` | posted lineup loses a listed player between polls | no events reported |

**Floor: 30 admitted events per class before ANY class-level statement.** Nothing
is readable below it, and reading early is forbidden. **All events are currently
unmappable** — no event can be joined to a price response, so measurable = 0
across the board. **Under active repair by a concurrent worker.**

**Timestamp grades:** A = exact publication time · B = bounded between two known
instants, both bracket times recorded, the bound *is* the event time carried as
an interval · C = reconstructed or date-only · D = unusable. **Only A and B may
support any timing claim.** A transaction DATE is never treated as a TIME.
Grade A is unreachable for `il_roster_move` because the MLB feed itself is
day-only. First-sighting lineup rows (no prior poll to bracket against) are
grade C and inadmissible.

**Cadence:** hourly poll baseline (60-minute brackets), 15-minute brackets inside
dense windows, T−25 close pass. The reaction ladder's resolution floor is the
poll spacing in force at each event, and the primary hypothesis is stated
against exactly that floor: *median time to 50%-of-books reaction exceeds the
capture-spacing floor.* BH-FDR q=0.10 across the family of admitted classes.

**Books:** minimum 6 quoting pre-event (the M3 line — consensus over fewer is
not a consensus); the multibook store currently carries **11 books**.

**Forbidden to read early:** any class below its 30-event floor; 2025 (tuning
only); sealed 2026-01-01..08-27, ever, without Brey's explicit go. Secondary
measurements (lead/lag tables, stale-window distributions, magnitudes) are
DESCRIPTIVE and may never be promoted to findings without their own
pre-registration.

**Expected accumulation time:** at freeze the estimate was ~27 team-lineups/day
for `lineup_posted` and ~20 game-relevant transactions/day for `il_roster_move`,
which would clear 30 in days. **Observed accumulation is far below that** — 13
and 21 events total since the clock started ~05:46Z on 2026-08-31 — and with
zero currently measurable, **no honest estimate of time-to-floor can be given
until the join repair lands.** Not measured.

Excluded at freeze, not downgraded: `reliever_status` (no announcement source
exists), `weather_roof` (roof has no feed; weather is a single unstamped
reading), and **all historical replay of 2023–24** (every class is grade C/D —
transactions day-only, lineups date-only, no probables history, historical odds
sampled 3×/day so any bracket is 6–15 hours wide).

---

## I. FORWARD DATA HEALTH

**CRITICAL FINDING, 2026-08-31 — forward captures were being thrown away.**
`data/processed/*` was gitignored. That rule was written when the directory held
reproducible provider pulls; **forward captures were added to it later and
silently inherited an ignore meant for regenerable files.** They are not
regenerable — a price observed at 19:47 tonight cannot be fetched back at any
price tomorrow — and this project runs on **ephemeral containers whose disks are
reclaimed**. Found with five days of h2h snapshots and a day of multi-book
boards living nowhere but one container's disk. **Fixed in commit 56b8ccf:**
`odds_snapshots.jsonl` and `odds_multibook.jsonl` are now explicitly un-ignored
and tracked as evidence, alongside `evidence/` which was already tracked for the
same stated reason. This is the single most consequential defect found in the
program's history that did *not* corrupt a number — it silently risked the
entire forward proof lane.

**Ledger (Stage 7, live since 2026-08-28).** 58 games recorded, 46 settled, 12
pending, **0 unsettled past dates, 0 orphan settlements**. Verdicts: no_play 54,
flagged 2, market_unavailable 2. Append-only integrity verified through git
history; every settlement joins. Note that `market_unavailable` is deliberately
distinct from `no_play` — a consequence applied after the finding that 30.0% of
scanner candidates have no first-five market at all.

**Latest capture:** 2026-08-31 20:02Z (`odds_snapshots.jsonl` 894 rows spanning
08-27..08-31; `odds_multibook.jsonl` 981 rows, 08-31 only, 11 books).

**Close status.** The dense T−25 close pass runs; a game reaching first pitch
without a capture in its last 30 minutes is reported as a **missed window**,
never papered over and never backfilled. Known defect logged 2026-08-31:
settlements carried `closing=null` (the CLI never threaded it), so **no CLV can
currently be computed from the ledger**; closing staleness is now recorded on
settlement rows.

**F5 status: BROKEN.** `data/processed/f5_close.jsonl` **does not exist** — the
F5 close pass has produced nothing since it shipped at 05:46Z. Under active
repair. The health monitor confirms: h2h / spreads / totals present today, **F5
no data**. `docs/RESUME.md` still describes F5 closes as "accumulating in
data/processed/f5_close.jsonl", which is currently false.

**Missed windows.** A long gap on 2026-08-31 roughly 17:15Z through 01:15Z while
a session was held in plan mode — those firings executed late or found no game
in window (one run: 0 captures, stopped early). Separately, **32 of 58 window
games had zero observations in their final 3 pre-pitch hours** (the plan-mode
outage plus cadence). Missed windows are gone permanently and are recorded, not
reconstructed.

**Monitor status (today).** 7 games with quotes, median 11 books/game,
h2h/spreads/totals present, F5 no data.

**Active problems:** (1) F5 close pass producing nothing; (2) V3 event→price
joins unmappable; (3) 251 dates inside the results span never fetched (being
backfilled) and 122 unresolved games; (4) `closing=null` on settlements blocking
ledger CLV; (5) a corrupt ledger line halts recording until a human intervenes —
this is **deliberate and documented**, because a tolerant dedup scan risks
double-recording after a crash, which is worse for evidence than a loud halt
that names its line; (6) `closing_observation` ignores `book_last_update`, so a
suspended book can supply "the close" — written up, not fixed, because changing
it changes closing semantics and needs a decision.

---

## J. MARKET DEPTH

Everything below comes from one deliberate 24-credit probe on 2026-08-31
(`docs/COLLECTION_POLICY.md`) plus historical coverage measurements. Costs are
per event per snapshot unless stated.

| market | books | availability | cost | status |
|---|---|---|---|---|
| **MLB h2h (moneyline)** | 11 forward today (18 → 12 → 11 historically, 2023→2025) | universal | baseline, already collected | the hardest market on the board; the close beats a public-grade Elo at p=0.0003 |
| **Run line (spreads)** | present today per the health monitor | broad | baseline | never evaluated as a bet target in any family |
| **Totals** | present today per the health monitor | broad | baseline | **never evaluated as a bet target in any family** — no totals hypothesis has ever been registered |
| **F5 h2h (`h2h_1st_5_innings`)** | **5 forward** | **30.0% of 454 candidate 2023–24 games had NO F5 market at all**; F5 odds coverage in the matchup matrix is **9.3%**; **14% of F5 moneylines end level (ties)** | **1 credit** | collected forward via the dense close pass — but the store is currently empty (see I) |
| **F5 spreads / totals** | 3 | thin | 1 credit | not collected |
| **Alternate spreads / totals** | **7** | 130–160 outcome rows per event | **1 credit** — the best information-per-credit measured on the board | deliberately **OFF**: an option, priced and documented, switched on when a registered hypothesis needs it |
| **Pitcher strikeouts** | **3–4, listing-dependent** | prop history from ~May 2023 | not measured for a prop fetch — the repo's odds provider has **no props support at all** and rejects any non-featured market key | the C1 candidate market; the audit that would measure it is gated (see O) |
| **Other props** | not measured | not measured | not measured | — |
| **Historical 5-minute grid** | **12 books** | 2023–24 | **10 credits** — e.g. 100 event-windows × 12 snapshots ≈ **12,000 credits** | HARD APPROVAL GATE |
| Per-event markets endpoint | — | — | **1 credit** — a coverage scanner | — |

Structural note that shapes every choice above: a 3–4 book prop market **cannot
form a consensus by this program's own 6-book floor**, and **limits are not
observable from the odds API at all** — so "measurable" never implies
"executable", and no claim about limits or acceptance is ever made from this
data.

---

## K. API / RESOURCE STATUS

- **Odds credits: 53,083 remaining** as of 2026-08-31, after the 24-credit market
  probe (53,332 was the 2026-08-29 figure). **Absolute floor: 5,000** — when hit,
  the pipeline prints `skipped: credit floor`, stops spending, and reports;
  nothing resumes without Brey.
- **Approved envelope: ~132 credits/day** (the dense 15-minute grid). Actual
  spend runs far below it because dense no-ops on quiet hours; the collection
  policy uses that headroom deliberately but **total daily spend stays inside the
  already-approved 132**, enforced in code order: if a day would exceed it,
  added markets are skipped first, then the grid thins.
- **What spends:** the daily loop's slate snapshots; the hourly dense h2h grid;
  the T−25 close pass; the piggybacked F5 add-on (+1 credit/event/moment,
  expected +15–40/day).
- **What is free:** rosterwatch (MLB lineups/probables/transactions feeds), the
  `/events` index, the F5 settlement store (MLB StatsAPI linescores — 181 dates,
  2,512 games, 0 odds credits), Statcast pitch ingest, every historical research
  run on data already on disk (V2, V4, V5 and the Elo benchmark each cost
  **zero credits**).
- **Standing order of protection:** forward evidence first — live snapshots,
  lineup/news timestamps, recommendation state, close capture, settlement,
  ledger integrity. Historical and research work yield to these, always.
- `ODDS_API_KEY` lives only in a gitignored `.env`; a fresh clone lacks it.

---

## L. TEST / REPRODUCIBILITY STATUS

- **1,637 tests green** (`python3 -m unittest discover -s tests -q`), verified at
  the debrief timestamp. Growth this session: 1,319 → 1,377 → 1,507 → 1,587 →
  1,637. The suite is green at **every** commit; that is the done-standard, not
  an aspiration.
- **Reproducibility guarantees.** Frozen families are byte-checked before a run
  executes: the funnel re-reads the registered family file and its
  pre-registration check must pass before any level runs. The V4 family was
  independently re-audited on 2026-08-31 — all six specs, **every published
  field, zero mismatches**, re-run in 8.66s, under the identical battery
  fingerprint `ac74c7a7f715f9ec`, with md5s of all eight `data/research/` files
  unchanged before and after. Drift was checked rather than assumed: the matrix
  had been fully rewritten by the V5 re-ingest, and a field-by-field comparison
  showed **0 differences across every V4-relevant column**.
- **Structural guards, not conventions:** sealed seasons are refused by the
  matrix builder; point-in-time injection tests assert that a fact dated after a
  cutoff leaves the built row **byte-identical** while the same payload dated
  before it moves the row (so the silence is meaningful, not a broken detector);
  the compiler path matches an independent hand implementation to 10 decimals;
  the battery cannot mutate its input rows; the Ranker's empty-Engine-2 gate is
  a test; `artifacts/demo_latest.html` is preserved.
- **Known technical debt** (written up, not fixed): `bullpen_workload`'s
  "sample" is a period, not a denominator; the thin-starter warning overreaches
  onto adequately-sampled velocity figures; "<20 IP" parses as a 20-IP sample;
  the synthesis layer's suppressed-items audit trail is computed but never
  rendered (a product call, not a defect); `closing_observation` ignoring
  `book_last_update`; the deliberate corrupt-ledger-line halt. Plus the four
  active data problems in section I.

---

## M. CURRENT BLOCKERS

**BLOCKED BY POLICY**
- **Prop-listing audit** — `docs/COLLECTION_POLICY.md` forbids prop collection
  without a registered hypothesis, and C1 is deliberately unregistered. Genuine
  chicken-and-egg: the prerequisite for registration is the thing policy forbids
  collecting before registration.
- **Sealed 2026-01-01..08-27** — one evaluation ever, needs a Stage 5 policy
  freeze plus Brey's go. **There is currently no candidate to confirm, so the
  gate is moot as well as shut.**
- **2025 re-evaluation** — retired; burned by four looks, tuning-only forever.
- **Rescuing a dead hypothesis by threshold change** — forbidden by rule.
- **Real-money betting or any bet-placement capability** — never, permanently.

**BLOCKED BY DATA**
- **Reverse line movement / any contrarian family** — needs public betting
  percentages. No source we can reach provides them, and inferring public
  sentiment from price movement **invents the data**.
- **V3 historical replay (2023–24)** — every event class is grade C/D. Not a
  spend problem; unsupportable at any price.
- **Wind vector / roof effects** — `orientation_deg` is `None` for all 30 parks
  *by design* (a bearing wrong by 180° inverts a real effect confidently and
  silently), so `classify_wind` returns `None`. Roof state has no feed at all.
  ~1 hour of satellite imagery would unblock the wind half.
- **Umpire effects** — source not verified.
- **Hitter-side velocity bands / contact-power profiles** — not in the matchup
  matrix point-in-time; blocked until built and passing the byte-level PIT
  injection test.
- **Q6/Q7/Q8 (F5 line structure)** — need posted first-five *totals* per game
  historically, which we do not have.
- **V3's own joins** — events exist but are unmappable to price responses today
  (active repair).
- **F5 forward closes** — the store is empty (active repair).

**BLOCKED BY SAMPLE ACCUMULATION**
- **V3, every class** — floors are 30 admitted events; current best is 21, and
  none are measurable yet.
- **The forward ledger** — 46 settled against a 300-pick floor, with
  `closing=null` blocking CLV grading in the meantime.
- **The mismatch scanner's own hypothesis** — needs ~200 decided flags at
  roughly one a day, i.e. most of a season. First decided flag was 0-1.
- **F5 coverage/book review** — wants ~2 weeks of closes; currently has zero.
- **M2 (weekend day-game staleness)** — needs enough weekend-afternoon cells from
  the dense forward grid.

**BLOCKED BY BREY'S APPROVAL**
- The **prop-listing audit** (18 credits/day, ~340 total, hard cap 400) — needs a
  one-line policy amendment distinguishing *feasibility measurement* from
  *research collection*.
- **The 2024 question** for the Evolution Lab (see O) — irreversible in one
  direction.
- **Historical F5 backfill** (would make M4 answerable) and the **targeted
  historical lead/lag purchase** (~12,000 credits) — both large historical
  purchases.
- **Ranker Engine 2 activation** and any **decision-policy freeze**.
- **Multi-sport expansion (KBO/NPB/NBA/NFL)** — explicitly deferred: "stay on
  MLB" until MLB has a validated forward result.

**NOT BLOCKED** (executable today, free)
- Repairing the V3 event→price joins and the F5 close pass (in flight).
- Backfilling the 251 missing result dates and resolving the 122 unresolved games.
- Threading `closing` into settlements so the ledger can grade CLV.
- **Phase 3 of the Evolution Lab plan: a regularised model against the close** —
  never run, cheaper than everything else, and it answers the prediction
  question most directly. `python3 -m src.cli status` still reports
  `probability: UNCALIBRATED -- no fitted model yet`.
- Park orientations (U9), Q3 (threshold sensitivity measured against **fire
  rate**, never results), Q4 (divergence from priors on linescores already on
  disk), third-time-through-order as **Analyzer content**.
- Season-end handling: the slate empties in late September and the off-season
  capture posture is undefined.

---

## N. ROADMAP

**TODAY.** Repair the two broken forward paths — V3's unmappable event→price
joins and the empty F5 close store. Both are lane-A forward evidence, both are
free, and everything downstream of them is stalled. Protect the hourly capture.

**THIS WEEK.** Let V3 accumulate and do not read it early. Get `closing` threaded
onto settlements so the ledger can grade CLV rather than accumulating ungradeable
rows. Backfill the 251 missing result dates. Decide the two questions in section
O — both are Brey's and both are currently blocking real work.

**THIS MONTH.** The first V3 class-floor analysis *if* a class reaches 30 admitted
and measurable events; the F5 coverage/book review once ~2 weeks of closes
exist; season-end handling (the slate empties in late September and the
off-season posture is undefined — this is a hard deadline, not a preference).
Run the regularised-model-vs-close test: it is cheap, it has never been done,
and its answer changes how much compute prediction deserves at all.

**NEXT 90 DAYS.** The program branches on evidence, not on plan:
- **PATH A — V3 shows measurable latency:** falsification battery on it → forward
  shadow ledger ≥300 selections → the four Ranker unlock conditions → Brey's
  sign-off. Note that even a clean V3 result is a *measurement*, not a tradeable
  edge.
- **PATH B — V3 null, F5/depth promising:** design the first F5 family from
  forward-captured closes; a costed historical F5 backfill proposal goes to Brey.
- **PATH C — all markets null:** the Analyzer *is* the product. Off-season goes to
  reliability, KBO/NPB feasibility, and 2027 capture architecture.
- **PATH D — something survives everything:** decision-policy freeze → the
  one-shot sealed-2026 request. One evaluation, ever, reported honestly either
  way.

**What actually matters, stated bluntly.** The research lane is correctly idle:
V6 examined twelve mechanisms and registered none, which is the right call.
Nothing is gained by inventing a sixth feature family. The value is in (a) making
the forward evidence real — the gitignore finding proves how fragile it has been —
(b) letting V3 and the F5 coverage review speak, and (c) the Evolution Lab's
**placebo calibration**, which is the one instrument that would tell us how good
a backtest has to look before it beats what our own search manufactures from
noise. That is worth more than any individual hypothesis on the list.

---

## O. OPEN QUESTIONS AND PENDING DECISIONS

**Awaiting Brey (both block work today).**

1. **The prop-listing audit.** `docs/PROBE_PROP_LISTING.md`: 18 credits/day,
   ~340 total, hard cap 400, inside the daily envelope. It measures *listing
   times, book counts, and whether the market reprices after lineups post* — no
   prices analysed, no inference run. It can **falsify C1 outright without a
   registration**, which is exactly why it is worth running. Blocked by
   `docs/COLLECTION_POLICY.md`. Recommendation on file: **Option A, narrowly** —
   permit *feasibility measurement* as distinct from *research collection*, with
   results recorded as a feasibility artifact and explicitly cited as prior
   knowledge in any later pre-registration. Option B (keep it parked) costs a
   day of unrecoverable listing-time data per day.
2. **The 2024 question** (`docs/EVOLUTION_LAB_ASSESSMENT.md` §7). Either (A)
   treat all of 2023–24 as one **non-evidential search substrate** and let the
   forward stream be the only true holdout — the recommendation: slower,
   defensible; or (B) spend 2024 as a walk-forward validation window — faster,
   and **irreversibly** contaminating the last clean historical season. Once
   2024 has been used to *select*, it cannot be restored.

**The Evolution Lab, in one paragraph** (proposed by Brey; assessed
2026-08-31 before any implementation). The **replay engine is excellent and
should be built**. The evolutionary search **as specified would be a machine for
manufacturing false discoveries**: with 4,859 discovery games a selective
strategy takes 500–1,000 of them, while distinguishing a +2% ROI strategy from a
0% one at two standard errors needs ~10,000 selections — we are 10–20× short
before any multiplicity correction. The reframe that makes it worth building:
**make the primary product the noise ceiling, not the champion** — run the
identical search over placebo worlds (outcomes shuffled within date, teams
permuted, signals date-shifted) and report the distribution of the best strategy
found. If the real champion sits inside the placebo distribution, the space is
barren, rigorously and far more convincingly than the individual nulls managed.
Four supporting constraints: fitness is **CLV-primary** (144 selections vs
10,000 to detect a signal), the genome is **split** so execution genes are frozen
during predictive search (otherwise evolution discovers line shopping and dresses
it as prediction), **mechanism directions are frozen — evolution may not flip a
sign** (screen-then-flip is exactly how V4 and V5 died), and meta-learning runs
inside the placebo harness too or it is just hidden adaptivity. Phases are
sequenced so each can kill the next; Phase 4+ (actual evolution) is conditional
on Phase 2 showing real signal above the placebo ceiling.

**Genuine open research questions.** Does measurable information latency exist at
our capture resolution (V3, unanswered)? Is the prop close soft — nothing in this
program has ever measured a market other than the h2h close, and every prior we
hold is a prior about a *different* market? Do F5 prices move independently of
the full-game price within a book (free, uses data already being collected, and
it is the precondition test for C2 that should run before any F5 family is
designed)? Does point-in-time lineup K-rate vary enough game to game to move a
half-strikeout line (feature-side only, free, and the cheapest available way to
kill C1)? Should a totals family ever be registered — no totals hypothesis has
existed in the entire program?

**Documented contradictions in the source docs, so a reader is not misled.**

1. **The hypothesis denominator.** `docs/RESUME.md` and
   `docs/RESEARCH_V5_STUFF.md` say "27 pre-registered hypotheses" (V1:13 · V2:5 ·
   V4:6 · V5:3), but **the 13 is itself V1+V2, so V2 is counted twice**.
   `docs/EVOLUTION_LAB_ASSESSMENT.md` says 25; `docs/OVERNIGHT_RUN.md` said 24 at
   V4 time; `docs/PLAN_TWO_TOOLS.md` is internally inconsistent on the same
   point. Consistent alternatives: **25** at detector/spec level (11+5+6+3) or
   **35** at registered-hypothesis level (21+5+6+3). No verdict changes — every
   family's FDR ran against its own frozen denominator (V1: 21 registered / 8
   corrected; V2: 5; V4: 6; V5: 3) — but "27" should not be repeated without this
   note. `docs/RESEARCH_CATALOGUE.md` already documents this.
2. **"Tuned Elo".** `docs/RESUME.md` and `docs/EVOLUTION_LAB_ASSESSMENT.md` both
   describe the benchmark as beating a "tuned" Elo. `docs/BENCHMARK_ELO.md` is
   explicit that the constants came from FiveThirtyEight's published methodology,
   were **chosen a priori and never tuned on our data**. The benchmark doc is
   correct; the two summaries overstate.
3. **F5 closes.** `docs/RESUME.md` says F5 closes are "accumulating in
   `data/processed/f5_close.jsonl`". That file does not exist.

---

*Source documents, in descending usefulness for a continuing reader:
`docs/RESEARCH_CATALOGUE.md` (73 ideas under one taxonomy — the single best
index), `docs/ROADMAP.md` (the map and the standing autonomous loop),
`docs/RESUME.md` (cold-start handoff), `docs/RUNBOOK.md` (operator guide),
`docs/OVERNIGHT_RUN.md` (running operational log), `docs/VALIDATION_GATE.md`,
`docs/RESULTS_STAGE2.md`, `docs/RESULTS_V2.md`,
`docs/RESEARCH_V3_TIMING.md`, `docs/RESEARCH_V4_EXPLORATORY.md`,
`docs/RESEARCH_V5_STUFF.md`, `docs/RESEARCH_V6_CANDIDATES.md`,
`docs/BENCHMARK_ELO.md`, `docs/COLLECTION_POLICY.md`,
`docs/VALIDATION_CRITERIA.md`, `docs/EVOLUTION_LAB_ASSESSMENT.md`,
`docs/PROBE_PROP_LISTING.md`, `docs/REPRODUCIBILITY_AUDIT_V4.md`.
`docs/RESULTS_2023_24.md` and `docs/VALIDATION_PACKAGE_1.md` are INVALIDATED —
kept only as a record of what was once believed.*
