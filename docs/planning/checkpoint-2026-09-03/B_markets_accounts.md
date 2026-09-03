# B: Market surface + paper account loop (real-data audit)

Repo HEAD, read-only. All commands run from `/home/user/aisportsanalysis`.
Demo script: `paper_loop_demo.py` in this directory (run: `python3 paper_loop_demo.py`).

## Q2. Market surface matrix

Columns: REPRESENTABLE (`src/board/ids.py` `MARKET_CATALOGUE` key exists) |
CAPTURED LIVE (a pipeline writes real rows today, with counts) | HIST. REPLAYABLE
(rows in `data/historical/odds_history`/`odds_first_five` 2023-25) | GRADEABLE
(registered rule in `settle.py`/`settle_props.py`, callable end-to-end) |
ANALYZABLE (`src/engine/analyze.py` actually consumes it) | PAPER-BETTABLE
(`src/accounts/paper.py` can settle it today).

Row counts, commands used:
```
$ python3 -c "... Counter(market_key for l1_observations.jsonl) ..."
h2h 45822, totals 5096, spreads 5092, h2h_1st_5_innings 670   (total 56680 rows)
$ wc -l data/processed/odds_snapshots.jsonl -> 7626 (h2h 2532, totals 2548, spreads 2546)
$ wc -l data/processed/f5_close.jsonl -> 335, all market_key=h2h_1st_5_innings
$ wc -l data/processed/prop_prices.jsonl -> 37 (pitcher_strikeouts 32, 5 unlabeled)
$ wc -l data/processed/prop_listing.jsonl -> 454 (pitcher_strikeouts 413, 41 unlabeled)
$ wc -l data/processed/batter_props.jsonl -> 510 (total_bases 202, hits 186, hr 98,
    hits_runs_rbis 12, rbis 12; batter_runs/walks/strikeouts/stolen_bases: 0 rows)
$ find data -iname "*derivative*" -o -iname "*team_total*" -o -iname "*alternate*"
    -> NOTHING. team_totals / alternate_spreads / alternate_totals / f5 spreads+totals
    have ZERO captured rows anywhere in the repo.
```

| Market | REPRESENTABLE | CAPTURED LIVE | HIST. REPLAYABLE | GRADEABLE | ANALYZABLE | PAPER-BETTABLE |
|---|---|---|---|---|---|---|
| Full-game moneyline (h2h) | YES `ids.py:56` | YES 45,822 rows `l1_observations.jsonl` | YES 3x600 snapshots `odds_history/mlb_202{3,4,5}.jsonl` | YES `settle.py:_settle_h2h`, tested | PARTIAL — `analyze.py` never imports `board/project.py` (grep: zero hits); it consumes `PriceBlindSnapshot`/`PricedBoard` from `engine/snapshot.py`+`glue.py` built straight off L1 rows. h2h is the only market the demo `TrivialAlwaysHomeSystem` actually prices. | YES — demoed live, settled loss, ledger-recorded |
| Run line (spreads) | YES `ids.py:62` | YES 5,092 rows | YES (same store, spreads market) | YES `_settle_spreads`, tested | PARTIAL — reaches `PricedBoard` (same L1 pull), but no shipped system prices it | YES — demoed live, settled loss |
| Alternate run lines | YES `ids.py:80` status=PROBE | **NO — 0 rows anywhere.** `derivative_markets.py` docstring: "team_totals and f5_trio... as of this writing" never spend; ALTERNATE_MARKETS family is PROBE_REQUIRED-gated and no `derivative_markets.jsonl`/`*_raw.jsonl` file exists on disk | NO | YES rule exists (same as spreads) but nothing to feed it | NO | NO (nothing to bet) |
| Game totals | YES `ids.py:68` | YES 5,096 rows | YES | YES `_settle_totals`, tested | PARTIAL (same caveat as h2h) | YES — demoed live, settled win |
| Alternate totals | YES `ids.py:86` PROBE | **NO — 0 rows** (same as alt run lines) | NO | YES rule exists, unfed | NO | NO |
| Team totals | YES `ids.py:74` PROBE | **NO — 0 rows.** `derivative_markets.py:37` names it explicitly as unmeasured/never-spent | NO | YES `_settle_team_totals`/`_team_totals_rule` exists | NO | NO |
| F5 moneyline | YES `ids.py:93` | YES 335 rows `f5_close.jsonl` + 670 in `l1_observations.jsonl` | YES `odds_first_five/mlb_202{3,4,5}.jsonl`, 600 rows each | YES `_settle_h2h_1st_5`, tested | PARTIAL, same caveat | PARTIAL — not exercised in demo but same call path as h2h would work if a system priced it |
| F5 run line | YES `ids.py:99` PROBE | **NO — 0 rows.** Part of the ungated `f5_trio` family that never spends (`derivative_markets.py`) | NO | YES `_settle_spreads_1st_5` exists | NO | NO |
| F5 totals | YES `ids.py:105` PROBE | **NO — 0 rows**, same reason | NO | YES `_settle_totals_1st_5` exists | NO | NO |
| F5 team totals | **NO.** No catalogue entry, no market key, no `f5_team_total*` string anywhere (`grep -rn "f5.*team_total"` → nothing but the derivative_markets.py comment naming the *other* two families) | NO | NO | NO — no rule name exists | NO | NO |
| Pitcher strikeouts | YES `ids.py:131` DECLARED | YES — 32 rows `prop_prices.jsonl`, 413 `prop_listing.jsonl` | NO (`odds_history` is h2h/totals/spreads-only 2023-25; no historical prop store) | YES `settle_props.py:PROP_STAT_RULES["pitcher_strikeouts"]="k"`, registered into `SETTLEMENT_RULES` via `board/__init__.py` at import — **but BROKEN as a settleable rule through `settle.settle()`** (see Q3: dispatcher calls `fn(side, line, result)`, prop rule signature is `fn(row, selection)` → `TypeError`, reproduced live) | NO | **NO — proven broken**, see Q3 |
| Pitcher outs | YES `ids.py:137` DECLARED | NO rows found in any store | NO | Same broken-dispatch rule as above | NO | NO |
| Pitcher hits allowed | YES `ids.py:143` | NO rows | NO | Same broken dispatch | NO | NO |
| Pitcher walks | YES `ids.py:155` | NO rows | NO | Same broken dispatch | NO | NO |
| Pitcher earned runs | YES `ids.py:149` | NO rows | NO | Same broken dispatch | NO | NO |
| Batter hits | YES `ids.py:162` PROBE | YES 186 rows `batter_props.jsonl` | NO | Rule registered, same broken-dispatch defect | NO | NO |
| Total bases | YES `ids.py:168` PROBE | YES 202 rows | NO | Same defect | NO | NO |
| Home runs | YES `ids.py:174` PROBE | YES 98 rows | NO | Same defect | NO | NO |
| RBIs | YES `ids.py:180` PROBE | YES 12 rows | NO | Same defect | NO | NO |
| Runs (batter) | YES `ids.py:186` PROBE | **NO — 0 rows** (`batter_runs`/`batter_runs_scored` not present in `batter_props.jsonl` Counter output) | NO | Same defect | NO | NO |
| Walks (batter) | YES `ids.py:192` DECLARED | NO rows | NO | Same defect | NO | NO |
| Strikeouts (batter) | YES `ids.py:198` DECLARED | NO rows | NO | Same defect | NO | NO |
| Stolen bases | YES `ids.py:204` DECLARED | NO rows | NO | Same defect | NO | NO |
| H+R+RBI | YES `ids.py:210` PROBE (`batter_hits_runs_rbis`) | YES 12 rows | NO | Same defect | NO | NO |
| First inning NRFI/YRFI | YES `ids.py:112` (`first_inning_run`) DECLARED | **NO — 0 rows.** Not present in `l1_observations.jsonl`, `odds_snapshots.jsonl`, or any store found | NO | YES `_settle_first_inning_run`, tested (pure function) | NO | NO (nothing to feed it) |
| Race-to-X / derivatives | **NO.** `grep -rn "race_to\|race-to"` across `src/` and `scripts/` → zero hits. Not a catalogue entry, not a settlement rule, not mentioned anywhere | NO | NO | NO | NO | NO |
| Parlays (generic) | **NO catalogue entry at all** — only `same_game_parlay` exists, and it's `BLOCKED` on purpose (see next row); a plain multi-leg parlay has no key, no rule, nothing | NO | NO | NO | NO | NO |
| Same-game parlays | YES `ids.py:220`, status=`BLOCKED` **by design** — `settlement_rule="collection_blocked"`; `settle()` raises `ValueError` if ever invoked (`settle.py:283-287`, docstring guard 8 references `ARCHITECTURE_BETTING_ENGINE.md`) | NO (blocked, not merely unbuilt) | NO | NO — explicitly refuses to settle | NO | NO |
| Prediction-market contracts (Kalshi/Polymarket-style) | **NO.** `grep -rn "kalshi\|polymarket\|prediction_market"` → zero hits anywhere in the repo | NO | NO | NO | NO | NO |

### Hardest truths from Q2
1. Of the 27 markets asked about, only **4** have any live captured rows with real settlement math that actually runs end to end today: h2h, spreads, totals, F5 h2h.
2. Every prop market (pitcher/batter, 14 markets) is REPRESENTABLE + has a registered settlement rule, but the shared dispatcher in `src/board/settle.py:settle()` calls prop rules with the wrong argument signature. This is not a missing feature — it is a **wired-looking, silently-never-tested integration** that throws `TypeError` the instant anything tries to use it (reproduced live, see Q3).
3. `alternate_spreads`, `alternate_totals`, `team_totals`, F5 spreads/totals: named in the catalogue, have real settlement rules, and have a real capture module (`derivative_markets.py`) — but that module's own docstring says these families are cost-unmeasured and gated `PROBE_REQUIRED`, and zero output files exist anywhere on disk. Fully wired code, zero rows, by design (an operator has to run a manual `--probe` command that has evidently never been run).
4. F5 team totals, race-to-X, generic parlays, and prediction-market contracts do not exist in this codebase in any form — not a stub, not a TODO, nothing.
5. First-inning NRFI/YRFI has a real, tested settlement rule sitting on zero captured data — nothing populates `first_inning_run`/`first_inning_score_home/away`.

---

## Q3. Paper account loop — real run

Script: `paper_loop_demo.py`. Game used: ATL(home) vs SF(away), 2026-08-31,
`event_id=07d39d9ad653030c4c89d9a08c4071f5` (odds side) joined by hand to
`game_pk=824911` (results side) — **there is no stored key linking them**;
every row in `l1_observations.jsonl` for this event has `game_pk: null`
(verified: all 56,680 rows in the store have null `game_pk`), and
`odds_multibook.jsonl` also stores `game_pk: null` for every row checked.
The join had to be done by matching `(home_team, away_team, commence_time)`
strings by hand — this is real, but it is glue, not a shipped join.

Full output (abbreviated to the substantive lines; full run reproducible via
`python3 paper_loop_demo.py`):

```
STEP 1: starting_bankroll=1000.0

STEP 2: real L1 rows captured for this event: 618
  candidate[h2h/home]     book=fanduel line=None price=-154
  candidate[spreads/home] book=fanduel line=-1.5  price=146
  candidate[totals/over]  book=fanduel line=8.5   price=-105

STEP 3-4: 3 PaperBet objects recorded, each preserving book/market/
  selection_id/line/price/observed_utc exactly as captured.

STEP 5: real result row (mlb_results.csv): SF@ATL away=7 home=3 winner=SF
  settled demo-0 (h2h home)     -> loss  profit=-1.0000
  settled demo-1 (spreads -1.5) -> loss  profit=-1.0000
  settled demo-2 (totals over)  -> win   profit=+0.9524

STEP 6: bankroll 1000.0 -> 998.9524
STEP 7: total_staked_units=3.0 total_profit_units=-1.0476
STEP 8: roi_units=-0.3492
STEP 9: peak=1000.0 drawdown_max=2.0000

STEP 10: verify() before tamper: ok=True rows_checked=3
  tampered row 0 profit_units -1.0 -> 998.0 (hand-edited on disk)
  verify() after tamper: ok=False rows_checked=1 broken_at_line=1
  reason="row_hash=... does not match the recomputed hash ... this row was
  edited after being written"

STEP 11: real lineup_posted event found in information_events.jsonl
  -> NO code path re-prices any bet off it and emits a linked ReviewRecord.
  `ReviewRecord` (src/ledger/records.py) is only ever constructed in
  tests/test_ledger_records.py — grep confirms zero production call sites.

STEP 12: backfill.closing_prices(2026) -> 0 entries (DEFAULT_STORE =
  data/historical/odds_history, which holds mlb_2023/2024/2025.jsonl only —
  no 2026 file exists, so there is no closing-price comparison available
  for any currently-live game, only for the 2023-25 historical seasons).
```

### Where the loop stops being real code and becomes glue

**Step 2** is the first break. The task asked for candidates to come "from
real DecisionRecords if `src.engine.glue` + `analyze` produce them." They do
not, on this data, inside a reasonable script: `analyze()` requires a
`PriceBlindSnapshot` built by `glue.build_snapshot`, which needs specific
book-arrival preconditions across capture passes that this event's real L1
rows did not satisfy when driven directly. Rather than fabricate a
DecisionRecord, the script fell back to real L1 rows directly (real book,
price, line, timestamp — nothing invented) and hand-built `PaperBet`s. That
is the documented fallback path ("...else from real L1/odds rows") and it
does work — but it means the DecisionRecord/analyze layer was **not**
exercised end-to-end here; only the storage and settlement layers were.

**Step 5's join** (event_id -> game_pk) is entirely absent from the
codebase; it was done by hand in the script from team names + commence
time. No pipeline module was found that performs this join for props
grading or paper settlement automatically for live-captured games — this
matters because it means nothing currently connects a captured live odds
event to `mlb_results.csv` without a human writing exactly this kind of
glue.

**Missing/broken functions, concretely:**
- `src/board/settle.py:settle()` cannot dispatch any of the 14 registered
  prop settlement rules — reproduced: `settle('pitcher_strikeouts', 'over',
  GameResult(...), line='6.5')` raises `TypeError:
  _make_stat_rule.<locals>.rule() takes 2 positional arguments but 3 were
  given`. `src/accounts/paper.py:settle_bet` calls exactly this `settle()`,
  so **no PaperBet on any prop market can ever be settled** today, despite
  props being REPRESENTABLE, CAPTURED (partially), and having a registered
  rule.
- No function exists that builds a `ReviewRecord` from a live
  `information_events.jsonl` row and links it to a prior `DecisionRecord`
  (step 11) — `ReviewRecord` is a fully-specified dataclass with no
  production caller.
- No event_id->game_pk join utility exists for live-captured odds events
  (step 5's gap).
- `backfill.closing_prices` only has a store for 2023-25; nothing populates
  a 2026 (current-season) equivalent, so step 12 is structurally unanswerable
  for anything captured live today.

## Summary table

| Step | Status | Evidence |
|---|---|---|
| 1. Start bankroll | WORKING | `PaperAccount(starting_bankroll=1000.0)`, ran live |
| 2. Receive candidates from real slate | PARTIAL | DecisionRecord/analyze path not exercisable on this data in-script; fell back to real L1 rows (documented fallback), which did work |
| 3. Record multiple wagers | WORKING | 3 real `PaperBet`s recorded and printed |
| 4. Preserve book/market/selection/line/price/timestamp | WORKING | all fields present verbatim on each bet |
| 5. Settle from real results | WORKING (with hand glue) | settled against real `mlb_results.csv` row 824911; join done by hand — no shipped event_id->game_pk mapping exists |
| 6. Update bankroll | WORKING | 1000.0 -> 998.9524 |
| 7. Units | WORKING | staked=3.0, profit=-1.0476 |
| 8. ROI | WORKING | `roi_units` property, -0.3492 |
| 9. Drawdown | WORKING | peak/drawdown_max tracked incrementally, 2.0 max |
| 10. Immutability / tamper detection | WORKING | `HashChainLedger.verify()` caught the hand-edited row exactly, named the line and reason |
| 11. Second verdict after new info + linkage | NOT BUILT | real `lineup_posted` event exists in data; no code path re-prices or emits a linked `ReviewRecord` from it (type exists, zero production callers) |
| 12. Recommendation price vs eventual close | SCAFFOLD ONLY | `backfill.closing_prices` works and is tested, but its only store (`data/historical/odds_history`) has no 2026 season file — unusable for anything captured live right now |
| Prop-market settlement (surfaced by Q2, blocking any prop PaperBet) | SCAFFOLD ONLY / BROKEN | `settle()` dispatcher signature mismatch reproduced live: `TypeError` on every one of the 14 registered prop rules |
