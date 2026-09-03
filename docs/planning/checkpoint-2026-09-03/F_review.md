# F — Adversarial review of A–E (checkpoint verification)

Read-only. All line refs against HEAD `f0da91f` in `/home/user/aisportsanalysis`.
Every claim below was re-executed, not read off the reports.

## Verdicts

| Report | Verdict |
|---|---|
| A_engine.md | **CORRECTED** — every structural claim stands; the Q6 demo it presents as the engine's live decision is on an **in-play** board (2h08m after first pitch), which A does not say and which makes its headline numbers (`price_american=3500`, `edge_bps=2979`) meaningless. |
| B_markets_accounts.md | **CORRECTED** — market matrix, row counts and the prop `TypeError` all reproduce exactly; its Step-12 closing-price conclusion is right by accident (wrong reason), and its "one-line" framing of the prop defect is wrong. |
| C_factory_fitness.md | **STANDS** — all zero-caller and absent-code claims independently reproduced. |
| D_matchup_matrix.md | **CORRECTED** — one stated grep result is false; the conclusion it supports is still true. |
| E_autonomy.md | **STANDS, strengthened** — `forward-capture.yml` is not even registered with GitHub Actions (API 404), i.e. it has never run once. |

---

## A — engine

**Reproduced.** `run_current.py` produced output **byte-identical** to A's paste
(`features={}`, `assumption_exposure={}`, one `DecisionRecord`, `known_at_grade="A"`,
MAJOR `degraded_information`). `run_replay.py` reproduced exactly too (2,406-game 2023
universe, game 718781, fanduel away +150 / home -178, `CONSENSUS_EXECUTION` `price=None`,
`DEGRADED_INFORMATION`, decided AWAY/SF, winner NYY → **loss published**).
Independently confirmed: `FORBIDDEN_PRICE_NAMES` (`snapshot.py:42-47`); seven `asof.py`
stores with zero bullpen refs; `p_model=None` always (`evolab_system.py:94-111`);
`src/cli.py:2047` hard-wires `TrivialAlwaysHomeSystem`; all 56,680 L1 rows `game_pk:
null`; `src/research/matrix.py:113-115` refuses any season outside (2023, 2024).

**CORRECTION 1 (material, unreported by A):** the Q6 "current slate" decision is an
**in-play** board. Event `0b03739…` is BOS vs SEA, `commence_time=2026-09-02T20:11:00Z`
(from `odds_snapshots.jsonl`), but `t = latest_capture_time(...) = 22:19:22Z` — 2h08m
after first pitch. That is why home ML is +3500. There is **no commence-time or
first-pitch guard anywhere in `src/engine/`** (`grep -n "commence|first_pitch|in_play"
src/engine/*.py` → zero hits). `glue.latest_capture_time` (`glue.py:179-187`) takes the
day's max `observed_utc`, and `sample_truncation_inputs` (`glue.py:344-366`) uses the
same `t` — so the shipped `src.cli engine truncation` runs on in-play boards too, and
the one committed G4 record (`data/processed/gate_results.jsonl`, 2026-09-02, PASS, n=8)
was computed that way. The G4 *leakage* property is still validly tested; the
*decision-quality* numbers are not. `src.evolab.replay` gets this right
(`replay.py:927-943`) — the defect is specific to the `glue` seam.

**Q4 answer — is `known_at_grade="A"` a real correctness bug? YES.**
`src/engine/analyze.py:309-319` initialises `grade = "D"`, branches on
`if snapshot.assumption_exposure:`, and in the `else:` (empty) branch sets `grade = "A"`.
But empty is exactly the case where **no as-of read happened at all** — `glue.py:244-246`
skips `as_of` entirely when `game_pk` is None. It fails **open**, asserting maximum
provenance quality precisely when provenance is unknown, and is contradicted on the same
record by the `DegradedInformation` adversary. Not a labelling quibble: `known_at_grade`
is a validated ledger field (`src/board/record.py:139`, `src/ledger/records.py:134`) that
downstream gates read. Correct behaviour on empty exposure is `"D"`, or a distinct
"no read" state.

## B — markets and paper accounts

**Reproduced.** `paper_loop_demo.py` re-ran to identical numbers: 3 real `PaperBet`s,
settled against `mlb_results.csv` (SF 7 – ATL 3) loss/loss/win, bankroll 1000.0 →
998.952380952381, `roi_units=-0.3492`, `drawdown_max=2.0`, `verify()` ok → tamper →
ok=False at line 1 with the exact hash-mismatch reason. Row counts re-derived **exact**:
L1 56,680 (h2h 45,822 / totals 5,096 / spreads 5,092 / f5 670); `prop_prices` 37 (32 k);
`prop_listing` 454 (413); `batter_props` 510 (TB 202, hits 186, HR 98, HRR 12, RBI 12);
zero derivative/team-total/alternate files; `MARKET_CATALOGUE` 27 entries;
`same_game_parlay` BLOCKED (`ids.py:220-225`); zero hits for `race_to`, `kalshi`,
`polymarket`, `prediction_market`.

**Q3 answer — the prop-settlement TypeError, reproduced.**
```
>>> settle('pitcher_strikeouts', 'over', GameResult(home_runs=5, away_runs=3), line='6.5')
TypeError: _make_stat_rule.<locals>.rule() takes 2 positional arguments but 3 were given
```
Exact mismatch: `src/board/settle.py:292` dispatches `return fn(side, line, result)`
(3 positional args: `str`, `str|None`, `GameResult`), while every prop rule built by
`src/board/settle_props.py:150` is `def rule(row, selection)` (2 args: a box-store
`dict`, a selection `dict`).

**CORRECTION 2 — this is NOT a one-line fix; B's "signature mismatch" framing
understates it.** No re-ordering of the dispatcher's three arguments produces a correct
call: `settle()` holds a `GameResult` (team run totals) and a line string; the prop rule
needs a per-player box row (it immediately does `row.get("type")`, `settle_props.py:81`)
plus a selection dict carrying `subject_id`. The data the prop rule needs is not in the
dispatcher's arguments at all. The only honest one-line change is a **guard** in
`settle()` raising a named error for prop keys instead of a TypeError; the real fix is a
prop-aware path (box-row lookup + `settle_props.settle`) and a branch in
`src/accounts/paper.py:142 settle_bet` that routes to it.

**Why it was never caught:** `tests/test_board_settle_wiring.py:90-95` calls
`SETTLEMENT_RULES[spec.settlement_rule](row, selection)` **directly**, bypassing
`settle.settle()`. The test that exists to prove the wiring proves the registry mapping
only, never the dispatcher. B's "wired-looking, silently-never-tested integration"
characterisation is exactly right — with this as the mechanism.

**CORRECTION 3 (Step 12, closing prices):** B concludes "no closing-price comparison is
available for anything captured live right now," reasoning from
`backfill.closing_prices(2026) → 0` because `DEFAULT_STORE = data/historical/odds_history`
has no 2026 file. That reasoning is wrong — B tested the historical backtest path and
missed the live one. Closing machinery for 2026 **does** exist and does run:
`data/processed/f5_close.jsonl` (335 rows, all 2026-08/09) is a 2026 closing store, and
its rows land in L1 as the only 670 `is_close=True` rows; `odds_snapshots.jsonl` holds
7,626 2026 rows; `snapshots.closing_observation` (`src/pipeline/snapshots.py:514`) and
`grading._closing_line_value` (`src/pipeline/grading.py:199-215`) are wired into
`cmd_grade`; and `evidence/forward_ledger.jsonl` already contains **210
`closing_backfill` rows** with `closing_price`/`closing_observed_utc`.
B's *conclusion* nevertheless survives on the numbers: of the **73** settlement rows in
that ledger, **0** carry a non-null `closing` (sampled reason: `"no snapshots recorded
for this game"`), so CLV is genuinely 0-for-73 on 2026 — a coverage failure, not a
missing-code failure. B should say that instead.

**CORRECTION 4 (under-claim, affects A, B and D):** all three imply nothing on disk
pairs a live game with a `game_pk`. `evidence/forward_ledger.jsonl` (427 rows, written by
`cmd_brief` via `src/pipeline/ledger.py`) carries `game_pk` (populated on 217 rows),
teams, `commence_time`, per-market `prices` with de-vigged fairs, `information_time`,
`verdict`, `lineup_status`. Not an `event_id` join — but the freeze→settle loop therefore
already exists in production (144 `recommendation` + 73 `settlement` rows), and a live
`game_pk` resolver is a small data-backed job: `src/providers/mlb.py:231 fetch_schedule`
already returns `gamePk` + teams + start time at zero odds-API cost.

**Honesty check on that ledger:** the system's entire live recommendation record is 3
`flagged` first-five plays out of 144 recommendations (rest `no_play`/
`market_unavailable`). All three are settled: 824637 home F5 won, 824874 home F5 pushed
(0-0), 823984 away F5 won. Small, published, not inflated.

## C — factory / fitness

**STANDS.** Reproduced: `accounts.paper` importers → only `tests/test_accounts_paper.py`;
`factory.fitness`/`factory.gates` importers → only their own tests
(`src/engine/truncation.py:114,117` mentions `gates.py` in a docstring, does not import);
`grep -c "season-end" src/cli.py` → 0; `grep -n evolab src/cli.py` → one comment (2029),
no call; no `def mutate|crossover|breed` anywhere; `ReviewRecord` has zero production
constructors. C is the most conservative and most accurate of the five.

## D — matchup matrix

**CORRECTED, conclusion intact.** The 16-row matrix, the 6-feature registry, the
9 matrix-computed columns, the 11 detector classes, the absence of `src/detectors/` and
`src/features/`, and `matrix.py`'s 2023/2024-only guard all check out.

**CORRECTION 5:** D's MARKET MOVEMENT row asserts `grep -n "engine.glue\|engine.truncation"
src/cli.py` → *no matches*. That is false: it returns 10 lines, including a real import
at `src/cli.py:2036-2038` inside `_cmd_engine_truncation`, which is a registered
subcommand (`src/cli.py:2352, 2409`). D's underlying point — that `cmd_brief` never
touches the engine path — is true, but the evidence as stated is not.
Re "could `src/research/matrix.py` features already be reached?": **no**, and by
deliberate guard, not omission — `matrix.py:113-115` raises `MatrixError` for any season
outside (2023, 2024) with the message "2025+ is tuning/sealed data". D's NOT-BUILT
markings here are correct and are a sealed-data safeguard working as intended.

## E — autonomy

**STANDS, and is if anything too generous.** Confirmed via the GitHub API:
- Exactly two branches; `.github/workflows` **does not exist** on
  `claude/cowork-session-migration-tn3sx2` (API: path not found).
- `GET /actions/workflows/forward-capture.yml/runs` → **404**: the workflow is not
  registered with Actions at all, has never run once, and the `*/15` cron has never
  fired. E's "unknown / blocked" is answerable: **never ran**.
- All 508 recorded runs are `tests`/`deploy-staging`, `push`-triggered on the working
  branch, several titled "Forward capture 01:01Z" — the data pushes that trigger deploys
  come from the in-session Routine, exactly as E says. (E omits `tests.yml`; immaterial.)

---

## Consolidated confirmed bugs

| # | file:line | Bug | Severity |
|---|---|---|---|
| 1 | `src/engine/analyze.py:309-319` | Empty `assumption_exposure` → `known_at_grade="A"`. Fails open: asserts grade A exactly when no as-of read occurred. | **Blocking** |
| 2 | `src/board/settle.py:292` vs `src/board/settle_props.py:150` | Dispatcher calls `fn(side, line, result)`; all 14 prop rules are `rule(row, selection)` → `TypeError`. Blocks every prop `PaperBet` via `src/accounts/paper.py:142`. Untested because `tests/test_board_settle_wiring.py:90-95` bypasses the dispatcher. | **Blocking** |
| 3 | `src/engine/glue.py:179-187, 344-366` | No first-pitch guard: `t` = day's latest capture, so `analyze()` and the shipped `engine truncation` CLI decide on **in-play** boards. Demonstrated: BOS/SEA commence 20:11Z, decision at 22:19Z, home ML +3500, `edge_bps=2979`. | **Blocking** |
| 4 | `src/engine/snapshot.py:281` | `Friction.book_count = len(rows)`, i.e. quote **rows**, not books. Same board/selection reports `book_count=575` alongside `books_at_decision=11`. | **Blocking** (a friction input to RATE) |
| 5 | `src/engine/snapshot.py:270-272` | `dispersion` = max−min implied over **all rows through t** (26h of history), not across books at t. Field's own comment says "across quoting books". Reported 0.644 is a time-mixing artifact. | **Blocking** |
| 6 | `src/engine/snapshot.py:194-205` | `best()` scans every row through t, returning the best price **ever seen**, not the price available at t. Coincidentally latest in the demo; not in general. | **Blocking** |
| 7 | `src/board/ids.py:251-271` | `selection_id` hashes (sport, market, side, subject, line) with **no game/event component**, so it collides across games (verified: `9e8d61f45a38abf0` appears on two different events). `DecisionRecord.selection_id` alone does not identify a bet. | Non-blocking (documented design; needs an event-scoped key downstream) |
| 8 | `src/engine/analyze.py:373` | `stake_units=0.0` hard-coded on every record — no sizing exists on the engine path. | Non-blocking (known gap, honestly reported by A) |

No leakage, sealed-data access, credit spend, or bet-placement capability was found.
No terminology drift found: `late_move` (`src/model/discovery.py:219,254,258`) and CLV
(`src/pipeline/grading.py:184-201`) are separate and never conflated; nothing labels
price improvement as EV or edge. Losers and pushes are published in both demos and in
the forward ledger. Full suite: see the line at the end of this file.

## Could not verify

- Whether `claude/cowork-session-migration-tn3sx2` is actually the repo's *default*
  branch (E's core §1 premise). The API exposes the branch list but not the default from
  the tools available here; E sources it from `docs/CAPTURE_EXTERNALIZATION.md`. The
  404 on `forward-capture.yml` makes the point moot either way.
- Whether an `ODDS_API_KEY` repository secret exists (secret existence is not readable).
- Fly.io runtime state (E's §3 rests on `deploy/Dockerfile` + both `fly.*.toml`, which I
  confirmed as files; no deployed machine was inspected).
- B's Step-2 assertion that `analyze()` could not be driven on that event "inside a
  reasonable script" — I did not attempt it; `run_current.py` shows `analyze()` running
  fine on a *different* event, so the specific obstruction is unconfirmed.
- C's claim that no `season/month/market stability` metric exists anywhere: I confirmed
  the greps, but absence-across-a-whole-repo is only as good as the search terms.

## My estimate of the owner's end-to-end milestone: **~30%**

The chain is: one slate → same engine analyzes every matchup → inspects every supported
market → selects candidates → places them in simulated accounts → freezes → settles →
updates fitness → EOD self-review. Piece by piece, as *working code exercised on real
data today*: "every matchup" is ~40% — two disconnected stacks, the legacy brief covering
~10 of 16 matchup dimensions across a real 15-game slate, and the intended engine running
on `features={}` with a self-described placeholder system, so the *same* engine does not
analyze every matchup. "Every supported market" is ~15% — 4 of 27 catalogue entries have
live rows plus settlement that actually executes; all 14 prop markets die at bug #2.
"Selects candidates" is ~35% — the legacy path produced 3 flagged plays in 144
recommendations and the engine path produces structurally valid `DecisionRecord`s, but
with no stake sizing and, per bug #3, off in-play boards. "Simulated accounts" is ~10% —
`PaperAccount` is complete, tested and tamper-evident, and has zero production callers.
"Freeze / settle later" is the strongest link at ~70%: `evidence/forward_ledger.jsonl`
really does freeze 144 priced recommendations and settle 73 of them against real results.
"Updates fitness" is ~5% — `Fitness`/`gates` are well-formed contracts whose only caller
in the repo is their own test file. "EOD self-review" is ~10% — no such module exists;
`cmd_grade`'s CLV report is the nearest thing and returns 0 CLV on 73 settlements.
Weighting those roughly evenly gives ~30%. The encouraging half of that number is that
most of the deficit is **wiring, not algorithms** — de-vig, CSCV, SPA, BH-FDR, the
falsification battery, the hash-chain ledger, the as-of reader and the settlement rules
are all real, tested math. The discouraging half is that the two stacks that each work
are not the one the owner described, and the seam between them (`glue.build_snapshot`'s
`features`, and an `event_id`→`game_pk` resolver) is still empty. 35% would be defensible
if bugs #3–#6 did not sit directly on the engine's own decision path; 80% is not.
