# Card V2 build plan

For roadmap item R16-34. Builds `DAILY_CARD_BEST_BETS_V2` exactly as registered
in `docs/PREREG_CARD_V2.md`; the diagnosis is
`docs/CARD_V2_DIAGNOSIS_2026-09-15.md`. When this plan and the registration
disagree, the registration wins and this plan is wrong.

**Workers.** Tasks marked **Haiku** are mechanical: fixed edits, source-level
checks, wiring a named call. Tasks marked **Sonnet** need judgement about
correctness: rule logic, ledger semantics, statistics, rendering. Every task
ends with a separate checker (not the worker that built it) running the named
tests and the acceptance line; the maker never grades its own work.

**Standing constraints for every task.**

- V1 logic and constants in `src/analysis/daily_card.py` do not change. V1
  rows in `evidence/cards_v1.jsonl` are never rewritten. V1's model constants
  (`strength.DISPERSION`, `playerprops.RHO`, the slot table), its live stores
  and its nightly `data/processed/card_calibration.json` do not change either;
  V2's fitted numbers come only from `data/processed/card_v2_frozen_params.json`
  (T0a).
- No test reads a live store. Every board, contract, ledger and results row is
  injected (a temporary path or an in-memory fixture). A test that depends on
  what is on disk passes or fails by machine.
- Where a new invariant can be pointed at V1, write it as a checker function
  first, run it against V1's `daily_card.select` / `select_props` output on the
  fixture, and keep a permanent `test_v1_*` case asserting V1 violates it.
  That records the diagnosis in code and proves the checker can fail.
- The 2026-09-15 numbers used in fixtures are design-period data. Using them to
  build fixtures is fine; using them to evaluate anything is not.
- Customer strings come only from `docs/PREREG_CARD_V2.md` section 13.

---

## Order at a glance

| # | Task | Worker | Depends on | Sessions (estimate) |
|---|---|---|---|---|
| TI | Interim V1 copy change, only with Brey's yes | Sonnet | Brey's yes | 1 |
| T10 | V1 comment tidy | Haiku | none; before T0 | 0.5 |
| T10b | V1 `CARD_BASIS` and `CARD_DISCLAIMER` (CTS-1 strings) | Sonnet | none; before T0 | 0.5 |
| T1 | Read-only pre-build checks | Haiku | none | 0.5 |
| T0a | 2025 backfill, the one-time 2025 fit into the frozen parameter file, a season-aware prop store (**owner-approved 2026-09-15**) | Sonnet | T1 | 2 to 3 |
| T2 | Pure rule module, built and tested on fixtures only | Sonnet | T1; before T0 | 2 |
| T3 | Ledger: V2 files, empty days, lock as last published, withdrawals | Sonnet | T2; before T0 | 2 |
| T4 | Closing-line measurement for card rows | Sonnet | T3; before T0 | 1 |
| T5 | Report, API, landing record and CLI wiring, `?rule=v2` preview | Sonnet | T0a, T2, T3; before T0 | 1.5 |
| T0 | Brey answers 5 to 8, commit the registration with the fingerprint value | orchestrator | T0a, T2, T3, T4, T5, T10, T10b | 0.5 |
| T6 | Schedule: publish V2 and shadows, settle all files | Haiku | T5; committed in the same push as T0, directly after it | 0.5 |
| T7 | Publication audit for V2 | Sonnet | T3, T5 | 1 |
| T8 | The registered read script | Sonnet | T3, T4 | 1.5 |
| T9 | Web rendering of V2, the record page and landing | Sonnet | T5, R16-05 groups `gameday-card` and `results` | 2 |
| T11 | Docs | Haiku | T9 | 0.5 |
| T12 | Staging verification at phone width | Sonnet (verifier, not a builder) | T6, T7, T9 | 1 |
| T13 | Cutover | orchestrator | owner answer 2 (1 is answered), T12 | 0.5 |
| T14 | Independent end-to-end check | Sonnet or Opus checker | T13 | 1 |

About 19 to 21 working sessions in all, plus the wait for R16-05's
`gameday-card` group, which is order 2 in `docs/DESIGN_BUILD_PLAN.json` and not
started while group 1 runs. This does not fit one or two sessions, so the
defect Brey reported stays on the customer card until T13 unless TI ships.

**Why T2 to T5 come before T0.** The registration's `code_fingerprint`
(registration 11.2) covers `src/analysis/best_bets_card.py` (T2) and
`src/report/card_v2.py` (T5), so those files must exist, merged, when T0
computes the fingerprint and writes its value into registration section 16.
They are built and tested on injected fixtures only; nothing calls them on
live data before T0 (T5's CLI default stays `v1`, and `?rule=v2` reads the V2
ledger, which is empty until T6 runs). T6 is committed directly after T0 in the
same push, so the first capture slot after `REGISTERED_UTC` publishes V2 and
the V2 ledger has a row for every slate date from registration onward
(registration R1). T4 is merged before T0 so no counted pick lacks the
closing-line join.

**What customers see meanwhile, and if question 2 is no.** The V1 card, with
TI's copy change if Brey approves it, and without it otherwise. Question 1 was
answered on 2026-09-15 ("Always show 3"), so the card has a floor of 3 met by
labelled fills and that answer no longer blocks the cutover. If question 2
is answered no, there is no cutover: V2 and its shadows keep running and
counting in the background, and the customer card stays V1 (with TI if
approved) until a successor that publishes pre-lineup props as picks is
registered.

**The floor of 3 and fills, in one place.** Registration section 6 is the
source; every task below implements it and none of them may soften it. A
**pick** passes G1 to G12. A **fill** is the highest-ranked close call (the
close-call order of registration section 6), added only while the picks and
fills already shown for the date number fewer than 3; it must pass G1, G2, G4,
G5 and G9, so it is never priced shorter than -160 and never a side the market
makes less likely than not, and it may fail G3, G6, G7, G8 or G10. Fills carry
no verb, say which check they failed (copy C6 and C12), lock and are graded
exactly as picks are, and are reported apart from the picks everywhere: the
record page, the API, the audit and the registered read. Close calls that are
not fills are not shown. When fewer than 3 candidates pass G1, G2, G4, G5 and
G9 the card shows fewer, under copy C13, and no string on the page promises
three bets on such a day. G12's ceiling of 10 counts picks only and a shown
fill is not removed when picks arrive later, so the largest card the rule can
list at once is 13 bets, 10 picks and 3 fills; that is a stated departure from
the owner's "3-10 bets" (registration G12, section 6 and question 1), not a
number for a task here to cap.

---

## TI. Interim V1 copy change (Sonnet; needs Brey's yes before it ships)

The defect Brey reported, "Take" and STRONG printed on a pick whose own copy
says the price is against you, can be fixed in copy now without touching V1's
selection. It changes the customer card, so it ships only after Brey says yes.

- On any V1 pick, game or prop, whose frozen our number is at or below the
  break-even of its published price: no "Take" at the start of the sentence
  (the selection and price only) and no STRONG, LEAN, SLIGHT or SPLIT chip or
  legend. Applied where the payload is served or rendered, never in the ledger.
  No selection, constant, lock or record changes; `evidence/cards_v1.jsonl` is
  untouched.
- Owner: whichever group owns the rendering file at the time (`gameday-card`
  for `web/js/card.js`); coordinate rather than editing a file another group
  owns.
- Test: a V1 fixture with Phillies -210 (ours 0.539, needs 0.677) renders
  without "Take" or STRONG; a V1 fixture whose our number clears its
  break-even keeps both.
- Registration section 10 records that this copy-only change is not a change to
  V1's selection.

## T10 and T10b. V1 comments and strings (before T0)

Scheduled before T0 so that nothing edits `src/analysis/daily_card.py` after
registration. `docs/DESIGN_BUILD_PLAN.json` lists that file under the R16-05
`copy-truth-sweep` group, and ROADMAP R16-04 moved that group's CTS-1 task (the
`CARD_BASIS` and `CARD_DISCLAIMER` rewrite) into this build; do both here, in
one change coordinated with that group, and tell it the file is done.

- T10 (Haiku), comments and docstrings only: `prop_rank_probability`'s
  docstring (`:1351-1362`) states the actual gate (market above 50%, our number
  above break-even), matching `:1380-1387`; the block above
  `RUNLINE_AS_ALTERNATIVE` (`:116-143`) notes that `strength.DISPERSION` was
  adopted on 2026-09-10 and the run line is still only an alternative under V1
  by rule, not because the correction is missing.
- T10b (Sonnet), CTS-1 exactly as `docs/DESIGN_BUILD_PLAN.json` specifies it:
  `CARD_BASIS` and `CARD_DISCLAIMER` only; no change to `CARD_RULE` or any
  logic. Do not ship the `docs/DESIGN_SYSTEM.md` replacement basis sentence
  that says "or the pick does not qualify" (V1 fills to 3 from SPLIT).
- Acceptance: `git diff` shows only comment, docstring and those two string
  constants in that file; `tests/test_customer_language.py` and
  `tests/test_no_nothing_clears_the_bar.py` green; full suite otherwise
  unchanged. Registration section 10 treats both as not changing V1's
  selection.

## T0a. The 2025 backfill, the frozen parameter file and the prop store (Sonnet, before T0)

**Owner-approved.** Brey answered question 3 no on 2026-09-15 at about 22:35Z
("Rebuild on 2025"), so this task runs registration 11.2 and section 1.2,
option O1, as the owner's answer and not as a default: every fitted number V2
uses is fitted once on 2025 and frozen, and nothing is copied over from the
sealed-window fits. The O3 branch that would have kept `DISPERSION = 2.3352`
and `RHO = 0.05065` is not built. No further owner answer gates this task.

- **Backfill, free MLB Stats API, 2025 regular season only**, into stores kept
  apart from the live 2026 stores: starter logs (`pitchers.build_log_store`),
  relief appearances (`bullpen.build_log`) and batter box scores
  (`boxscores.ingest_date`). The slot table also needs each batter's batting
  order: the Stats API boxscore carries it, but `boxscores.build_rows` does not
  store it today, so the 2025 backfill writes it into the 2025 store (a new
  field, read only by the fit script). Checked on 2026-09-15: the pitcher-log store
  (8,298 appearances) and the bullpen log (18,365 rows) hold 2026 only, so 0 of
  the 2,186 2025 games that pass the calibration's row selection have a starter
  FIP or a relief rate, and no 2025 box score is on disk. The live stores must
  not receive 2025 rows: `pitchers.league_fip_constant` sums every appearance
  before its cutoff with no season filter, so 2025 starts in the shared store
  would change V1's live 2026 numbers.
- **Additive parameters, defaults unchanged:** `strength.model_line` gains an
  optional `dispersion`, and `playerprops.price_prop` optional `rho` and slot
  table arguments, so V2 can pass frozen values while V1 keeps the module
  constants. Both files are fingerprinted, so this lands before T0.
- **One fit script**, committed before it runs, reads only the 2025 stores and
  refuses any 2026 row. In one run it estimates `DISPERSION` (`nb1`, the
  procedure of `scripts/test_run_dispersion_2025.py`) with the full model
  inputs, then fits the moneyline Platt calibration (the procedure of
  `scripts/fit_card_calibration.py`, relief rates included), the side-level
  run-line cover calibration on `p_*_plus` / `p_*_minus`, `RHO` (the procedure
  of `scripts/test_prop_dispersion.py`, fit only, no test window) and the slot
  plate-appearance table (the procedure of `scripts/probe_lineup_slot.py`). It
  writes `data/processed/card_v2_frozen_params.json` once; its sha256 goes into
  registration section 16. The output is never re-run for a different answer.
  The nightly `data/processed/card_calibration.json` is not touched.
- `src/report/props.py` reads the box-score store for the slate's season
  instead of the hard-coded `boxscores_2026.jsonl`, with no other change, so a
  2027 slate does not need a code change that would restart the count.
- If the backfill or any fit cannot be built, stop and put that to Brey; do not
  fall back to 2026 games and do not register.
- Tests: the fit script raises on a 2026 row; the run-line calibration is
  applied to `p_*_plus` / `p_*_minus`; `model_line` and `price_prop` with no new
  argument return byte-identical output for a V1 fixture (hash compared), and
  with the frozen values return different output; the live stores' row counts
  and V1's 2026 model lines for a fixture date are unchanged after the backfill;
  the props store path follows the slate date's year.

## T0. Registration (orchestrator)

- Put questions 5 to 8 of `docs/PREREG_CARD_V2.md` section 15 to Brey, with the
  section 14 illustration in front of him. Record each as his own answer or
  his explicit acceptance of the default, with its date, in the registration.
  The orchestrator never accepts a default for him. If any answer differs from
  a default, edit the number in the registration and the matching constant in
  `src/analysis/best_bets_card.py` (`longest_price_first`) **before**
  computing the fingerprint and committing.
- Questions 1, 3 and 4 are answered (2026-09-15, section 15): the floor of 3
  met by fills, O1's one-time 2025 fit, and -160. They are not re-asked. The
  answers are already in the registration's sections 15 and 16; T0 checks that
  `best_bets_card.RuleParams` carries `worst_price=-160`, `floor=3` and
  `SHADOW_C` at -150 before the fingerprint is computed.
- Compute the `code_fingerprint` over the files registration 11.2 lists, as
  merged. Commit `docs/PREREG_CARD_V2.md` with the sha256 of
  `data/processed/card_v2_frozen_params.json` and the fingerprint value in
  section 16. Set `REGISTERED_UTC` to the commit time in that commit. No V2
  code runs against live data before this commit; T6 follows it in the same
  push.
- Acceptance: the file on the branch shows a UTC timestamp, not the
  placeholder, a dated answer for each of questions 1 and 3 to 8, a sha256 in
  section 16 equal to `sha256sum data/processed/card_v2_frozen_params.json` at
  that commit, and a fingerprint value equal to the one recomputed from that
  commit's files.
- The V1 decision in diagnosis section 0 (whether V1's nightly refit keeps
  reading the sealed window) was put to Brey and answered on 2026-09-15 about
  22:35Z: "Freeze it now." It is implemented separately, and its record is
  `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`. It is not part of V2's
  registration and this build changes nothing in V1 because of it.

## T1. Read-only pre-build checks (Haiku)

No file writes. Output goes in the task report.

1. Confirm constants the registration cites: `prices.MIN_BOOKS == 6`,
   `propboard.MIN_BOOKS == 2`, `grade.FRESH_SECONDS == 3600`,
   `daily_card.MIN_SEASON_GAMES_FOR_PRELINEUP == 15`,
   `card_ledger.LOCK_LEAD_HOURS == 4.0`, `daily_card.PROP_MARKETS ==
   ("batter_hits", "batter_total_bases")`, `strength.DISPERSION == 2.3352`
   and `playerprops.RHO == 0.05065` (V1's values; V2 reads its own from the
   frozen parameter file), `strength.DISPERSION_FAMILY == "nb1"`,
   `clv.CLOSING_LEAD_STALE_SECONDS == 5400`, `src/report/card.py`
   `TOTALS_ON_CARD is False`. (All confirmed on 2026-09-15; re-check.)
1a. What T0a must backfill: count, by date only, 2025 rows in the results
   store, the pitcher logs, the bullpen log and any 2025 box-score store
   (`history.read_results`, `pitchers.read_logs`, `bullpen.read_log`). Read no
   outcome. On 2026-09-15: 2,186 results rows pass the fit's selection; 0 pitcher
   appearances, 0 bullpen rows and no box scores from 2025.
2. The sealed-boundary question from the diagnosis section 4.3: list the game
   dates inside `scripts/backtest_card_rule.py`'s 97 settled games by reading
   the script's selection code and its documented output only. Do not run it.
   If the code admits 2026-08-27, report that; do not re-run anything.
3. List every test file that imports `src.analysis.daily_card`,
   `src.appstate.card_ledger` or `api.card`, so later tasks know what to run.

## T2. Pure rule module (Sonnet, before T0)

**File:** new `src/analysis/best_bets_card.py`, fingerprinted by registration
11.2, so it is merged before T0 and tested on fixtures only. Pure, stdlib plus
`src.core.odds`, `src.analysis.strength` and `src.analysis.propboard`, no I/O,
no clock (every `now` is an argument). A new module rather than more code in
`daily_card.py`, so V1's selection stays exactly as registered; the only edits
to `daily_card.py` in this build are T10 and T10b, both before T0.

**Functions and constants.**

- `@dataclass(frozen=True) class RuleParams`: `rule_id`, `worst_price=-160`,
  `market_floor=0.50`, `our_floor=0.50`, `price_test=True`,
  `disagreement_cap=0.10`, `game_min_books=6` (`prices.MIN_BOOKS`),
  `prop_min_books=2` (`propboard.MIN_BOOKS`), `prop_min_season_games=15`
  (`daily_card.MIN_SEASON_GAMES_FOR_PRELINEUP`), `fresh_seconds=3600`
  (`grade.FRESH_SECONDS`), `longest_price_first=True` (question 8),
  `ceiling=10`, `floor=3` (owner, 2026-09-15: "Always show 3"),
  `fill_to_floor=True`. Constants are imported from their named
  modules, not retyped. There is no `best_price`, and there is no parameter
  that lets a fill skip G1, G2, G4, G5 or G9.
- `V2 = RuleParams("DAILY_CARD_BEST_BETS_V2")`;
  `SHADOW_A = replace(V2, rule_id="DAILY_CARD_BEST_BETS_V2_SHADOW_A_BAND_ONLY", our_floor=None, price_test=False, disagreement_cap=None)`;
  `SHADOW_C = replace(V2, rule_id="DAILY_CARD_BEST_BETS_V2_SHADOW_C_OTHER_WORST_PRICE", worst_price=-150)`
  (or -160 if question 4 registers -150).
- `breakeven(price) -> Optional[float]` via `odds.american_to_probability`.
- `in_band(price, params) -> bool` (`price >= worst_price`).
- `quote_age_seconds(observed_utc, now) -> Optional[float]`; `None` for a
  missing or unparseable time, which fails G3.
- `game_candidates(games, *, model_lines, moneyline_rows, runline_rows, calibrated) -> list`: both moneyline sides and both run-line sides at exactly 1.5, carrying `kind`, `market`, `line`, `side`, `price`, `book`, `books`, `observed_utc`, `market_probability`, `our_probability`, identity fields and `knowledge` when attached upstream.
- `prop_candidates(contracts) -> list`: both sides of `PROP_MARKETS` contracts.
- `failed_gates(candidate, *, now, params) -> list[str]` returning gate codes
  `G1_STARTED`, `G2_BOOKS`, `G3_STALE`, `G4_BAND`, `G5_MARKET`, `G6_OURS`,
  `G7_PRICE`, `G8_DISAGREEMENT`, `G9_UNCALIBRATED`, `G10_LINEUP`,
  `G10_SAMPLE`. G11 and G12 are applied in `select`.
- `rank_key(c)` and `close_call_key(c, fails)` exactly as registration
  sections 5 and 6, on unrounded numbers (break-even ascending first while
  `longest_price_first`). A close call requires G1, G2, G4, G5 and G9, not G3,
  and carries its quote age.
- `select(candidates, *, now, params, prior=None) -> dict` with `picks` (game),
  `prop_picks`, `fills`, `close_calls_not_shown`, `withdrawn`, `all_bets`,
  `n_picks`, `n_fills`,
  `stale_board` (`{"age_seconds": ...}` or `None`), `rule`, `basis`,
  `disclaimer`, `params` (the constants as a dict). Every pick carries `take`
  (true only when this run's read of it is fresh and passes G1 to G12,
  section 7) and, when `take` is false, `no_take_reason` (`LOCKED_READ_FAILS`,
  `LOCKED_NOT_ON_BOARD`, `STALE_READ`) with `now_price` where one exists. A
  stale read never adds or withdraws a pick.
- **The floor, in `select`** (registration section 6): after picks are chosen
  and capped at `ceiling`, fills are taken from the close-call order while the
  entries currently shown for the date, picks plus fills from `prior` and this
  run with withdrawn entries excluded, number fewer
  than `floor`; each fill carries `entry_class="fill"`, `failed_gates`, its
  quote age and, from `prior`, the run that added it. Every pick carries
  `entry_class="pick"`. At most one entry per game or player across picks and
  fills. A fill already shown is never removed because a pick appeared later; a
  fill whose fresh read passes G1 to G12 becomes a pick from that run; a pick
  that fails is withdrawn, never turned into a fill. A stale read may add a
  fill and never withdraws one. The close calls that were not shown are
  returned in `close_calls_not_shown` for the ledger row, never for the page.
  `select` never emits more than `floor` fills on one run and never emits a
  fill that fails G1, G2, G4, G5 or G9. A withdrawn fill frees its floor slot,
  so a date with withdrawals can carry more than `floor` graded fills, each at
  its last shown version.
- `format_triplet(market, needs, ours) -> tuple[str, str, str]`: whole
  percents rounded half up; when two values that differ at 4 decimals would
  show the same text, all three get one decimal, then two.
- `bet_sentence(pick)`, `why_sentences(pick)` (both C2 lines as `why[0]` and
  `why[1]`), `no_take_sentence(pick)` (C2b), `fill_sentence(entry, fails)`
  (C6's entry line), `fill_note()` (C12, the same line on every fill),
  `short_card_sentence(n)` (C13, used in place of C4 when the board offers
  fewer than `floor` entries),
  `stale_sentence(n, age_seconds)`, `BASIS`, `DISCLAIMER`, the C9 string and
  `harm_stop_sentence(arms)` returning the C11 form for the harm-check arms
  that fired (closing-price, hit-rate, or both): from registration section 13
  only.

**Tests to add** (all injected fixtures; each V2 invariant has its V1 case):

| Test file | Asserts | V1 case |
|---|---|---|
| `tests/test_card_v2_price_band.py` | No pick shorter than -160; -160 passes, -161 fails; +170 is not refused by G4; shadow C uses -150 | `test_v1_publishes_a_minus_210_favourite`: V1 `select` on the Phillies -210 fixture returns it |
| `tests/test_card_v2_likelihood.py` | Market 0.50 fails G5, 0.5001 passes; ours 0.50 fails G6; a market underdog at +120 with ours above its break-even is not a pick (question 5 default) | none (V1 has G5 by construction) |
| `tests/test_card_v2_price_test.py` | Our number equal to or below break-even never a pick; above passes | `test_v1_takes_padres_below_breakeven`: V1 picks Padres at -186 with ours 0.507 against 0.650 |
| `tests/test_card_v2_disagreement_cap.py` | Gap 0.10 passes, 0.1001 fails, both signs | none |
| `tests/test_card_v2_rank.py` | Order is break-even ascending, then market number; changing our number within the gates never reorders picks; ranking uses unrounded numbers (Padres -1.5 market 0.5312 ranks above Brewers -1.5 at 0.5308 when break-even is removed); tie-breaks in registered order | none |
| `tests/test_card_v2_run_line.py` | Angels +1.5 at -114 fixture (market 0.520, ours 0.613, 11 books) is a pick while Angels are the moneyline underdog; the run-line number passes through the run-line calibration, and a missing run-line calibration fails G9 | `test_v1_cannot_select_a_run_line`: no V1 pick has `market == "run_line"` for any fixture |
| `tests/test_card_v2_one_per_game.py` | Moneyline and run line on one game both passing yield one pick, the higher-ranked; one prop pick per player | none |
| `tests/test_card_v2_props.py` | Lineup not posted fails G10; `season_games` 14 fails, 15 passes, missing fails; 1 book fails G2, 2 passes | `test_v1_takes_a_pre_lineup_15_game_prop`: V1 `select_props(require_lineup=False)` picks the Olson fixture |
| `tests/test_card_v2_freshness.py` | Quote 3,600 s old passes, 3,601 s fails; missing `observed_utc` fails; a stale read neither adds nor withdraws a provisional pick and sets `take` false with `STALE_READ`; an all-stale board sets `stale_board`, adds no provisional picks, and still lists close calls with their ages | `test_v1_ignores_quote_age`: V1 picks from a 7,879 s old board |
| `tests/test_card_v2_count.py` | 0 to 10 picks; 11 passing gives 10; no pick added to reach the floor; locked picks count toward 10; a withdrawn pick frees its slot | V1 floor already pinned by `TheCardAlwaysHasAFloor.test_the_floor_is_met_by_filling_from_the_split_pile` in `tests/test_no_nothing_clears_the_bar.py`; reference it, do not copy it |
| `tests/test_card_v2_fills.py` | on a first run, 0 picks gives 3 fills, 2 picks 1 fill, 3 picks 0 fills, 10 picks 0 fills; fills come in the close-call order (a fill failing one gate ranks ahead of one failing two, then by shortfall, then market number); a candidate failing G1, G2, G4 or G5 is never a fill (a -161 close call and a market-0.49 close call are both refused, so the card shows fewer); a G9 failure is neither pick nor fill; no fill for a game or player with a pick; only 2 qualifying candidates gives 2 entries and `short_card_sentence`; a stale-only board still produces fills, each carrying its quote age; a fill already shown stays when a pick appears later; a fill whose fresh read passes every gate becomes a pick and is no longer a fill; a failing fresh read withdraws a fill and a stale one does not, and a withdrawn fill frees its slot so the next close call is added while it stays on the record; `select` never returns more than 3 fills on one run | none (V1 fills to 3 from its SPLIT pile with no price band; `TheCardAlwaysHasAFloor` pins that) |
| `tests/test_card_v2_copy.py` | "Take" begins a sentence if and only if `take` is true and the entry is a pick; no fill sentence ever starts with a verb, whatever its numbers; every fill carries `fill_note()` saying it is not a pick and is graded on the record, and its C6 line names every check it failed; `short_card_sentence` is used in place of C4 when the entries are fewer than the floor, and in place of C5's two fill sentences when the board is stale and the entries are fewer than the floor at once, so no rendered card promises three bets beside fewer than three entries; no pick, fill or purpose string promises three bets without naming the condition that three clear the first checks; a locked pick whose newest fresh read fails G7 renders C2b without a verb; every pick's `why[0]` contains the three numbers from `format_triplet` and `why[1]` contains "has not been shown to beat the market's"; `harm_stop_sentence` returns the closing-price C11 form for that arm, the hit-rate form for that arm, and the combined form for both; collision rule at one and two decimals; "only slightly more likely than not" iff market below 0.55; run-line and prop lines; no "best of", "STRONG", "value", "edge" outside the record line; each string passes the phrase lists imported from `tests/test_no_nothing_clears_the_bar.py` and `tests/test_customer_language.py` | `test_v1_says_take_under_price_is_against_you`: V1 `_why_sentences` for Phillies contains "price is against" while `_bet_sentence` starts "Take" |
| `tests/test_card_v2_shadows.py` | `SHADOW_A` ignores G6 to G8 and nothing else; `SHADOW_C` differs from V2 only in `worst_price`; both carry `floor=3`; rule ids are distinct strings | none |
| `tests/test_card_v2_illustration.py` | On the rebuilt 2026-09-15 pool fixture (with game quote times), the module reproduces registration section 14 exactly: as registered, 0 picks and 3 fills, Angels +1.5, Twins +1.5, Olson, in that order; with G3 set aside, picks Twins then Angels and one fill, Olson, with Harris and Alonso not shown; with game prices fresh and prop prices stale, picks Twins then Angels and one fill, Cubs -135; shadow A's two lists of 10 with no fill; shadow C 2 picks and the Harris fill | none |

Acceptance: all of the above green; the V1 cases fail if the invariant checker
is broken (verify once by pointing the checker at V2 output for a V1 case and
seeing it pass, then restoring).

## T3. Ledger (Sonnet, before T0)

**File:** `src/appstate/card_ledger.py`. Additive only.

- Constants: `CARD_STORE_V2 = evidence/cards_v2.jsonl`,
  `CARD_STORE_V2_SHADOW_A = evidence/cards_v2_shadow_a.jsonl`,
  `CARD_STORE_V2_SHADOW_C = evidence/cards_v2_shadow_c.jsonl`,
  `CARD_STORE_V1_SHADOW = evidence/cards_v1_shadow.jsonl`.
- `V2_FROZEN_FIELDS`: V1's `FROZEN_FIELDS` plus `kind`, `our_probability`,
  `breakeven`, `gap`, `lineup_posted`, `season_games`, `failed_gates` (empty on
  a pick), `game_type` (MLB `gameType`, needed for 11.1's regular-season
  filter), `entry_class` (`pick` or `fill`, registration 11.1), `take`,
  `no_take_reason`. Row-level: `code_fingerprint` (sha256 of
  the files registration 11.2 lists, needed for its restarts), `params`
  (including `floor`), `rule`. `FILL_FROZEN_FIELDS` for fills: the same fields
  plus the quote age at the run that added the fill and the run instant that
  added it; `NEAR_FROZEN_FIELDS` for the close calls that were not shown, with
  quote age, which are never graded.
- `v1_code_fingerprint` on every row written to `CARD_STORE_V1_SHADOW`: sha256
  of the eight paths registration section 10 lists (`strength.py`,
  `playerprops.py`, `propboard.py`, `props.py`, `daily_card.py`, `card.py`,
  `card_ledger.py` and `data/processed/card_calibration.json`), computed the
  same way as `code_fingerprint`. It restarts nothing and gates nothing; it
  exists so that 11.6 can say whether the V1 the comparison ran against is the
  V1 that was registered, instead of assuming the calibration freeze covered
  the whole model. V1's own `publish` and `cards_v1.jsonl` are not touched.
- `publish_v2(card, *, now, path)`: accepts a card with zero picks (V1's
  `publish` refuses one at `card_ledger.py:503-508` and keeps refusing);
  writes `fills`, `close_calls_not_shown`, `withdrawn`, `stale_board`,
  `params`, `rule`,
  `code_fingerprint`; appends only when picks, prop picks, fills, withdrawals,
  the unshown close
  calls, a `take` flag or the stale state changed, and always writes at least
  one row per slate date.
- `_lock_and_merge_v2(prior, fresh, *, moment, lock_lead_hours, key_fn,
  frozen_fn, fresh_seconds)`: the registration's L1 to L4, applied to picks and
  to fills. At the first run at
  or after first pitch minus 4 hours a prior pick locks **as last published**,
  as V1's `_lock_and_merge` does. Before that, a prior provisional pick absent
  from a **fresh** read, or failing it, moves to `withdrawn` with the run
  instant and failed gates and is carried forward; a stale read changes
  nothing. A withdrawn selection that passes again returns as the same pick. A
  locked pick is carried verbatim. A game with a locked game pick rejects any
  other game entry (G11). A fill locks on the same schedule and is carried
  verbatim once locked; a provisional fill is withdrawn only by a fresh read
  that fails it on G1, G2, G4 or G5, or when its game or player gains a pick,
  and never because the picks reached the floor. An entry that was a fill and
  whose fresh read passes every gate is carried as a pick from that run, with
  its earlier fill versions kept in the row history; a pick is never rewritten
  as a fill. V1's `_lock_and_merge` is not modified.
- `record(..., until=None, entry_class=None)`: add an inclusive `until` date
  filter and a class filter.
  Default behaviour unchanged. Readers of a record block (API, landing, record
  page)
  use `by_kind` to show game, prop and total picks together and apart
  (registration R5); the V2 reader reports picks, fills and the two combined as
  three figures, each with its own won-lost-push and units, and reports
  `withdrawn` apart. No figure mixes a pick with a fill inside it.
- `settle_v2(date, results, *, prop_box_rows, path)`: grades every pick and
  every fill on the
  newest row for the date (locked, or provisional as last published when no
  lock run happened, marked `graded_without_lock_run`) and every entry in its
  `withdrawn` list at its last shown version, each once, each carrying the
  `entry_class` it held at its graded version. Close calls that were never
  shown are not graded. V1's `settle`
  (which grades every pick on the newest row with no `locked` filter) is not
  modified and is still used per V1 file. `verify` already takes `path`.

**Tests to add.**

| Test file | Asserts |
|---|---|
| `tests/test_card_v2_ledger_paths.py` | V2 rows land only in `cards_v2.jsonl` with the V2 rule id; each shadow only in its file; `record(path=...)` on each file counts only that file; a V1 row and a V2 row for the same date never appear in one `record()` result |
| `tests/test_card_v2_ledger_empty_day.py` | `publish_v2` writes a 0-pick row carrying its fills; V1 `publish` still raises on an empty `picks` (pins V1) |
| `tests/test_card_v2_lock_and_withdraw.py` | At T-4h a provisional pick locks as last published even when that run's read is stale or fails; before T-4h a fresh failing read withdraws it and a stale read does not; a withdrawn pick that passes again returns once; a locked pick is carried verbatim; a locked moneyline blocks a later run line on the same game; ceiling of 10 counts locked picks and not withdrawn ones; a fill locks the same way, is not withdrawn when the picks reach 3, is withdrawn by a fresh read that fails G4, and is carried as a pick from the first run whose fresh read passes every gate |
| `tests/test_card_v2_settle.py` | `settle_v2` grades locked picks and locked fills, a provisional entry of either class left on the last row when no lock run happened (flagged), and every withdrawn entry at its last shown price, each exactly once and each with its `entry_class`; an unshown close call is never graded; `record` returns picks, fills and the combined figure with no figure mixing the two; run-line fixtures for +1.5 losing by one, +1.5 losing by two, -1.5 winning by one and by two |
| `tests/test_card_v2_frozen_fields.py` | Every V2 pick and fill carries `game_type` and `entry_class`; every row carries `code_fingerprint` and `params.floor`; the fingerprint covers exactly the files registration 11.2 lists, `src/report/card_v2.py` included; changing a fingerprinted file's bytes changes the fingerprint; every `cards_v1_shadow.jsonl` row carries `v1_code_fingerprint`, it covers exactly the eight paths registration section 10 lists, and changing any one of their bytes changes it while leaving `code_fingerprint` alone |
| `tests/test_card_v2_v1_rows_unchanged.py` | Publishing V1 through the existing `publish` produces rows byte-identical to the pre-change output for a fixture card (hash compared) |

Run unchanged: `tests/test_card_ledger.py`, `tests/test_card_locks_per_game.py`,
`tests/test_card_ledger_sport_paths.py`, `tests/test_card_frozen_first.py`,
`tests/test_card_calendar.py`, `tests/test_card_record_page.py`.

## T4. Closing-line measurement for card rows (Sonnet, before T0)

**File:** new `src/report/card_clv.py`, reusing `src/report/clv.py`
(`pregame_index`, `closing_board`, `closing_consensus`); no new de-vig math.

- `measure_pick(pick, index) -> dict`: primary, price taken against the close:
  `needs = breakeven(graded price)`, `clv_bps = (p_close - needs) * 10000`
  (asserted equal to `clv.py`'s `consensus_move_bps + price_standing_bps`),
  `clv_pct = p_close / needs - 1`, `beats_close = clv_pct > 0`; secondary
  `consensus_drift_pct = p_close / p_lock - 1` (never labelled CLV); closing
  `observed_utc`, lead seconds, `books_at_close`. `p_close` is
  `clv.closing_consensus(clv.closing_board(...))`: the closing instant is the
  market's last pre-game capture, chosen before the line or the book floor is
  checked. Or an absence with one reason: `NO_EVENT`, `NO_MARKET`,
  `CLOSING_BOARD_THIN` (fewer than 6 books at the closing instant),
  `CLOSE_STALE` (lead over 5,400 s), `CLOSING_BOARD_IS_DECISION_BOARD`,
  `CLOSE_PRECEDES_DECISION`, `PROP_NOT_MEASURED`.
- Market keys: moneyline `h2h`; run line `spreads` at the pick's own signed line.
- `measure_ledger(path, index) -> list`, covering withdrawn picks and fills
  too; each measurement carries the entry's `entry_class`, so the read script
  can compute the picks' metrics and the fills' F1 line from the same pass
  without mixing them (registration 11.3).

**Tests to add:** `tests/test_card_v2_clv.py`: arithmetic on an injected
board (price -112, needs 0.5283, p_close 0.53 gives `clv_pct` +0.32% and
`clv_bps` +17; p_lock 0.5126 gives consensus drift +3.39%); a newer capture
with only 5 books quoting the line yields `CLOSING_BOARD_THIN`, never an older
6-book board; each other absence reason from its own fixture; a run line is
matched on sign and 1.5 exactly; a prop always returns `PROP_NOT_MEASURED`
below 6 books; the index is injected and the test never opens
`data/processed/odds_multibook.jsonl`.

## T5. Report, API and CLI (Sonnet, before T0)

**Files and functions.**

- New `src/report/card_v2.py`, fingerprinted by registration 11.2:
  `card_v2_for_date(entries, opportunity_rows, *, date, now,
  params=best_bets_card.V2)` reusing `_game_identity`, `moneyline_rows`,
  `run_line_rows`, `_prop_identity_by_game_pk`, `attach_knowledge` and the prop
  board read already in `_build_prop_picks` (imported from
  `src/report/card.py`), with every fitted number read from
  `data/processed/card_v2_frozen_params.json` (registration 11.2) and passed to
  the model explicitly, never from the nightly `card_calibration.json`; a
  missing file or a sha256 that differs from the registered one fails G9. It
  lives in its own module so the fingerprint covers the step that hands the
  frozen numbers to the model, without restarting the count on every V1 edit
  to `card.py`.
- `src/report/card.py`: `ACTIVE_CARD_RULE = "v1"` (switched only in T13);
  `CUTOVER_DATE = None`; `frozen_card_v2(date, *, path)`; `publish_all(date, *,
  now)` publishing V2 (through `card_v2.card_v2_for_date`), shadow A, shadow
  C, and V1 to `cards_v1.jsonl` before `CUTOVER_DATE` or
  `cards_v1_shadow.jsonl` from it.
- `api/card.py`: optional `rule` query parameter (`v1` or `v2`, default
  `ACTIVE_CARD_RULE`) on `GET /card`, `GET /card/{date}`, `GET /card/record`
  and `GET /card/history` (which backs the record page). `/card/record`
  returns `rule`, game, prop and total records together and apart from
  `by_kind`, V2's picks, fills and combined figures as three labelled blocks
  (registration R5), V2's withdrawn picks apart, and, when V2 is served and
  `CUTOVER_DATE` is set, a `retired_v1` block from
  `record(path=CARD_STORE, until=day before CUTOVER_DATE)` with the same
  together-and-apart shape. The default responses are unchanged while
  `ACTIVE_CARD_RULE == "v1"`.
- `api/meta.py` `_card_record` (`:112-127`, today `card_ledger.record()` on the
  V1 file for the landing page): read the active rule's ledger and label it
  with `rule`; after cutover it must not present V1's record as the live one
  (registration R4, R5).
- `src/cli.py`: `card publish --rule v1|v2|shadow-a|shadow-c|all` and
  `card settle --rule ...|all`, default `v1` so existing scripts behave as
  today until T6.

**Tests.** Add `tests/test_api_card_v2.py`: `?rule=v2` serves the V2 payload
shape (`fills`, `withdrawn`, `stale_board`, `n_picks`, `n_fills`, `rule`,
`take` and `entry_class` on
each entry); a 0-pick payload still carries its fills; default `/card` is
byte-identical to today's shape;
`/card/record?rule=v2` never includes V1 numbers and returns the picks, fills
and combined figures separately, with no figure mixing the two; `retired_v1`
stops at the
day before cutover and carries props; `/card/history?rule=v2` lists only V2
rows; `api/meta.py`'s card record follows `ACTIVE_CARD_RULE` and reports the
picks figure as the live one. Update
`tests/test_api_card.py` only to add cases, not to change existing ones.

## T6. Schedule (Haiku; committed directly after T0, in the same push)

- `scripts/capture_slot.sh`: in place of the existing V1 `card publish` call
  (`:535-536` on 2026-09-15; the file shifts, so find the `== card publish`
  echo), run `python3 -m src.cli card publish --date "$SLATE_DATE" --rule all`,
  output tailed, `|| true`, never failing the slot. The V1-only call is
  removed in the same edit.
- `scripts/daily_loop.sh`: `card settle --rule all` in place of the V1-only
  settle (`:271-279`), keeping the ESCALATE line.
- `evidence/` is already added wholesale by `capture_slot.sh:622-623` (the
  `git add ... evidence data/paper_accounts` line); confirm the four new files
  are picked up.
- No default-branch sync. The scheduled workflows on the default branch
  already check out `claude/sports-betting-analysis-review-g1o0co` and run its
  scripts (`.github/workflows/forward-capture.yml:95,171,240`,
  `daily-loop.yml:58,138`), so a change to the scripts alone deploys. A sync
  is needed only if a later change edits workflow YAML; T6 does not.
- Test: `tests/test_schedule_publishes_card_v2.py`, source-level: both scripts
  call `--rule all` and neither fails the run on its exit code.

## T7. Publication audit (Sonnet)

**File:** `scripts/publication_audit.py`, new `audit_card_v2(date_iso, now)`
beside `audit_card` (`:402`), called from the same entry point.

- ESCALATE: a pick priced shorter than -160; a sentence starting "Take" whose
  our number is at or below the break-even of the price in that row, or whose
  row's read of that selection is older than 3,600 s; a pick first added from a
  quote older than 3,600 s at the run that added it; a withdrawal written by a
  run whose read was stale; a fill containing "Take" or missing its C12 line;
  more than 10
  picks; two game entries on one game; a withdrawn pick missing from the settled
  row; any row in `cards_v2.jsonl` with a rule id other than V2, or a V2 rule id
  in `cards_v1.jsonl`; a V2 row without `code_fingerprint` or an entry without
  `game_type` or `entry_class`; any date present in both `cards_v1.jsonl` and
  `cards_v1_shadow.jsonl`; a record response summing across files, or leaving
  out props; a V2 row whose `code_fingerprint` differs from the value in
  registration section 16 with no restart recorded there; a row in
  `cards_v1_shadow.jsonl` with no `v1_code_fingerprint`.
- WARN, V1 drift: a `cards_v1_shadow.jsonl` row whose `v1_code_fingerprint`
  differs from the value in registration section 16, reported with the date and
  the files that changed. It is a WARN and not an ESCALATE because V1's code is
  not this rule's to hold still; what 11.6 needs is to know it moved. It
  changes no V2 number and never restarts V2's count.
- ESCALATE, the floor and the fills: a fill priced shorter than -160, or with a
  market number at or below 0.50, or below its book floor, or on a started
  game, or failing G9; more than 3 fills shown on one row; a fill on a game or
  player
  that already has a pick; a fill shown while the date has 3 or more picks and
  no earlier row shows that fill; a fill dropped from a later row without a
  withdrawal written; a settled fill missing from the graded rows; a record or
  API response that counts a fill inside a picks figure, or presents the
  combined figure as the rule's record.
- WARN: 7 or more of the last 14 slate dates with fewer than 3 picks; 3 or more
  of the last 14 with a stale board at every run; 3 or more of the last 14 with
  a fill added from a quote older than 3,600 s; any date with fewer than 3
  entries, and 3 or more such dates in the last 14 (monitoring thresholds, not
  rule parameters).
- INFO: today's pick count, fill count with the check each failed, entries
  shown, stale state.
- Test: `tests/test_publication_audit_card_v2.py`, one fixture per ESCALATE and
  WARN, one clean fixture producing no ESCALATE. V1 case:
  `test_v1_card_of_2026_09_15_escalates` builds the 8-pick V1 row as a fixture
  and asserts the band and "Take" checks fire.

## T8. The registered read (Sonnet)

**File:** new `scripts/card_v2_read.py`, read-only.

- Implements registration section 11 exactly: population filters (picks
  shown and graded as locked, graded without a lock run, or withdrawn; first
  pitch strictly after `REGISTERED_UTC` parsed from the doc; `game_type == "R"`
  from the frozen field; `code_fingerprint` and `model_id` for restarts),
  primary (price taken against the close) and secondary metrics S1 to S6,
  descriptive outputs, the harm check at its two thresholds (recording which
  arm fired, which chooses the C11 form), floors, verdict
  with all five FAIL conditions, the stop date, comparisons with Holm,
  bootstrap with seed 20260915.
- **Picks only, everywhere it counts.** Every metric, floor, harm-check
  threshold, verdict condition and comparison reads entries whose
  `entry_class` is `pick` at their graded version. Fills are read into the
  separate F1 line of registration 11.3 (n, won-lost-push, units, ROI, share
  beating the close, mean CLV%, the count by failed check, the count added from
  a stale quote) and printed beside the result, labelled as not part of it. The
  script raises rather than printing a verdict if any counted pick carries
  `entry_class == "fill"`, and prints F1 even when it is empty.
- Below the floors it prints `PENDING` and counts only; at a harm-check
  threshold it prints only the harm-check result and its counts.
- Raises an error, not a skip, on any row dated 2026-01-01 to 2026-08-27.
  Rows on or before the registration date are not an error: picks whose first
  pitch is at or before `REGISTERED_UTC` are excluded by the population filter,
  because the V2 ledger holds rows on the registration date itself.
- Test: `tests/test_card_v2_read.py` on synthetic injected rows: no interval
  or direction printed below either floor; floors need both conditions; Holm
  on fixed p-values (0.01, 0.03, 0.04: 0.01 is below 0.05/3 and is rejected,
  0.03 is above 0.05/2 so testing stops and neither of the other two is
  rejected); a `code_fingerprint` or `model_id` change restarts the count;
  postseason rows excluded by `game_type`; a sealed-date row raises; a pick on
  the registration date with first pitch before `REGISTERED_UTC` is excluded
  and one after it is counted; withdrawn picks are counted; each harm-check arm
  fires on its fixture and not on a clean one; FAIL by each of the five
  conditions, PASS, INCONCLUSIVE and UNDERPOWERED each reached by a fixture; a
  ledger of 300 picks plus 300 losing fills gives the same verdict, floors and
  harm-check results as the same 300 picks alone, and the F1 line reports the
  fills; a fill that later became a pick is counted once, as a pick.

## T9. Web (Sonnet)

`web/js/card.js` and `web/css/card.css` belong to the R16-05 group
`gameday-card`; `web/js/cardrecord.js` to `results` (`docs/DESIGN_BUILD_PLAN.json`).
`docs/DESIGN_SYSTEM.md` was read for this plan and is not edited by it. This
task lands **after** `gameday-card` ships `compactPickCard`, through that
function, not beside it.

- Card (`web/js/card.js`), when the payload `rule` is V2: section head "Today's
  picks" with "Picks today: {n_picks}" read from the field; purpose line C1;
  C4 under it when `n_picks < 3`, or C13 in place of C4 when the entries shown
  are fewer than the floor; compact cards for `all_bets` in payload order
  with **both `why[0]` and `why[1]` rendered whole on the card face, at every
  rank and every width**, including phone rank 4 and below, where the compact
  anatomy has no "View breakdown" control (`docs/DESIGN_BUILD_PLAN.json:367`);
  neither line may move into a breakdown; the headline verb read from `take`,
  with C2b when it is false; the provisional, "Lock pending · graded as
  published" and locked states exactly as `docs/DESIGN_SYSTEM.md` section 4
  specifies (true under V2's lock as last published); no label chip, no grade
  chip, no "best of N books" (today at `web/js/card.js:146`, `:269`, `:378`); a
  second section "Close calls, not picks" from `fills`, rendered without a
  verb, with each price age, each failed check (C6) and the C12 line on every
  entry's face; that section is absent when `fills` is empty, which is the
  normal state of a day whose picks reached 3 at its first run; the C5 stale
  state when `stale_board` is set;
  disclaimer C7; C9, or C11 in the form for the harm-check arm that fired,
  when the payload says so. A fill is never rendered by the pick renderer and
  never carries a verb, whatever its numbers.
- **Empty V2 days.** Today a payload with no bets goes through
  `payloadHasBets` to `lastPublishedCard`, which walks back to yesterday's
  card, then to `emptyCard`'s "NO CARD TODAY" (`web/js/card.js:709-752`,
  `:822-900`). For a V2 payload this branch must not run: a 0-pick V2 day
  renders C4 (or C5, or C13) and its fills, and never walks back to another
  day. A 0-pick day normally still shows three entries, because of the floor.
  The V1 walk-back stays for V1 payloads, and its `/card/{day}` fetch carries
  the `rule` parameter so a V2 preview can never show a V1 card.
- Landing (`web/js/landing-live.js`, reads `apiGet("/card")` at `:279`): a
  0-pick V2 card renders its count and its fills rather than an empty or
  older card; the landing record reads `api/meta.py`'s rule-labelled record
  (T5) and shows the picks figure, never the combined one, as the live record.
- Preview: `#/today?rule=v2` requests `/card?rule=v2`. No link to it in the
  navigation.
- Record (`web/js/cardrecord.js`): V2 block with record line C8 (game, prop,
  removed-before-lock picks, the fills and the combined figure each shown
  apart, and the picks figure named as the rule's record) and, when present, the closed
  `retired_v1` block with game and prop picks together and apart, read from
  `/card/record` and `/card/history` with the `rule` parameter. Nothing adds
  the two blocks.
- Banner C10 for 14 days from `CUTOVER_DATE`, dismissible.
- Phone rules from `docs/DESIGN_SYSTEM.md` section 7: 15px text floor, 44px
  targets, 16px gutters, one column, no horizontal scroll at 320px, only the
  tab bar fixed.

**Tests.** Add `tests/test_web_card_v2.py` (source level, comments stripped
with the helpers in `tests/test_no_nothing_clears_the_bar.py`): the V2 branch
reads `n_picks` rather than counting the DOM; the V2 pick renderer emits
`why[0]` and `why[1]` outside any breakdown disclosure, in both the full and
the phone rank-4-and-below layouts; the headline verb comes from `take` and
from `entry_class === "pick"`; the
fill renderer never emits "Take" and always emits the C12 line; no "best of" string remains in
`web/js/card.js`; no STRONG, LEAN, SLIGHT or SPLIT chip is rendered for a V2
payload; the stale branch reads `stale_board.age_seconds`; a V2 payload never
reaches `lastPublishedCard`; the walk-back fetch carries `rule`;
`landing-live.js` handles a 0-pick V2 card with three fills;
`cardrecord.js` renders the picks, fills and combined figures as three labelled
lines and adds none of them together. Update deliberately, with the
reason in the commit message: `tests/test_web_card_props.py` (if it asserts
the removed meta line), `tests/test_card_record_page.py` and
`tests/test_whose_record_is_it.py` (two record blocks; `today.js` must still
call `renderCardRecordStrip`), `tests/test_web_all_bets.py` (its
`:183` assertion that `if (!payloadHasBets(payload)) {` appears exactly twice
changes once the V2 branch bypasses those gates), and
`tests/test_landing_record_from_ledger.py` (the landing record becomes
rule-labelled and follows `ACTIVE_CARD_RULE`).

**Design conflicts to raise, not resolve here.** `docs/DESIGN_SYSTEM.md`
section 6 gives the Gameday purpose line "Ranked by how strongly the betting
market favours each pick." That stays true of V2's order but omits the checks;
V2 uses C1. The same document's replacement `CARD_BASIS` for V1 says "or the
pick does not qualify", which is not what V1 does (V1 fills to 3 from SPLIT);
do not ship that string on V1. Both go to the design owner.

## T11. Docs (Haiku)

- `docs/THE_CARD.md`: add a V2 section summarising the registration and
  linking it; keep the V1 text as history, marked as the rule through the
  cutover date.
- `docs/ROADMAP.md` R16-34 status line, by the orchestrator.

## T12. Staging verification at phone width (Sonnet verifier)

Run by an agent that built none of T2 to T9. Evidence is screenshots plus the
API payloads they were taken from, saved with the task report.

1. On staging, open `#/today?rule=v2` at 390x844, 360x780 and 320x568, and the
   default `#/today` at 390x844.
2. For the V2 view, check against `GET /card?rule=v2` fetched in the same
   minute: the count equals `n_picks`; no pick is priced shorter than -160;
   every pick shows, on its face and without opening anything, both the line
   with the three numbers and the line saying our number has not been shown to
   beat the market's, **including picks ranked 4 and below at 390, 360 and 320
   px**; every "Take" has `take` true, `entry_class` `pick` and our number
   above the break-even; no
   fill has a verb, and each shows its price age, the check it failed and the
   C12 line; picks plus fills is 3 unless the picks are 3 or more, or the
   payload says fewer candidates cleared the first checks (C13); no fill is
   priced shorter than -160 or has a market number at or below 50%; no "best
   of", STRONG or
   grade chip; the stale line appears if and only if `stale_board` is set, with
   the same age; a 0-pick V2 payload shows C4 or C5 and its fills, never
   "NO CARD TODAY" or an older day's card; no text under 15px; no horizontal
   scroll at 320px; only the tab bar is fixed.
3. Default view: V1 card while `ACTIVE_CARD_RULE == "v1"` (with TI's copy
   change if it shipped).
4. Record page `#/record-card?rule=v2`: V2 numbers match
   `record(path=evidence/cards_v2.jsonl)`, with game and prop picks shown
   together and apart, and the picks, fills and combined figures shown as three
   labelled lines with no fill inside a picks figure; nothing summed with V1.
   Landing page record carries the
   active rule's label and shows the picks figure.
5. Run `scripts/publication_audit.py` for the date: no ESCALATE from
   `audit_card_v2`.
6. Run `tests/test_card_v2_illustration.py` on the 2026-09-15 pool rebuilt
   with game quote timestamps and confirm the module reproduces
   `docs/PREREG_CARD_V2.md` section 14 exactly (as registered: 0 picks and 3
   fills, Angels +1.5, Twins +1.5, Olson; with G3 set aside: picks Twins then
   Angels and one fill, Olson; with game prices fresh and prop prices stale:
   the same 2 picks and the Cubs -135 fill; shadow A's two lists of 10 with no
   fill; shadow C 2 picks and the Harris fill).
   `scratchpad/card_v2/ap_v2_screen.py` is the reference for the picks and
   `scratchpad/owner_answers/fill_illustration.py` for the fills; both rank on
   unrounded
   numbers and recompute break-evens from the price. A difference means the
   build or the illustration is wrong; find which before going on.

Acceptance: every check passes, or each failure is filed with its screenshot
and payload.

## T13. Cutover (orchestrator)

Only after Brey answers question 2 of the registration's section 15 with yes,
and T12 passes. Question 1 is answered (2026-09-15, "Always show 3"), so the
floor of 3 met by labelled fills is what cuts over.

- Set `ACTIVE_CARD_RULE = "v2"` and `CUTOVER_DATE` to the next slate date.
- From that date V1 publishes to `evidence/cards_v1_shadow.jsonl`.
- Record the cutover date in the registration's section 16.
- Next day: audit clean, banner shown, V1 retired block matches
  `record(path=evidence/cards_v1.jsonl, until=...)` for game picks, props and
  the together figure.

If question 2 is answered no: no cutover. V2 and its shadows keep running and
counting under the registration; the customer card stays V1, with TI's copy
change if Brey approved it; the owner's preferred alternative needs its own
registration.

## T14. Independent end-to-end check (Sonnet or Opus checker)

- Full test suite green.
- Walk from real entry points, not components: the capture slot's publish call
  produces rows in all four files for a real date; the daily loop settles
  them; `/card` and `/card/record` serve them; the page shows them. A green
  unit test proves a component works, not that anything runs it.
- Confirm no V2 row predates `REGISTERED_UTC`, and the first V2 row's
  `code_fingerprint` equals the value in registration section 16.
- Confirm the first `cards_v1_shadow.jsonl` row carries a `v1_code_fingerprint`
  equal to the value in registration section 16, and that editing any one of
  the eight paths section 10 lists changes it. The check proves V1 drift is
  detected; it does not require V1 to stay still.

---

## Ledger and API changes, collected

| Change | Where | Compatibility |
|---|---|---|
| Four new ledgers | `evidence/cards_v2.jsonl`, `cards_v2_shadow_a.jsonl`, `cards_v2_shadow_c.jsonl`, `cards_v1_shadow.jsonl` | New files; `cards_v1.jsonl` untouched and closed at cutover |
| `publish_v2`, `_lock_and_merge_v2`, `settle_v2`, `V2_FROZEN_FIELDS` (with `game_type`, `entry_class`, `take`), row `code_fingerprint`, `withdrawn`, `FILL_FROZEN_FIELDS`, `NEAR_FROZEN_FIELDS`, row `v1_code_fingerprint` on the V1 shadow file only | `src/appstate/card_ledger.py` | Additive; V1 `publish`, `_lock_and_merge` and `settle` unchanged, and `cards_v1.jsonl` unchanged |
| `record(until=, entry_class=)` | same | Default unchanged |
| `rule` query parameter on `/card`, `/card/{date}`, `/card/record`, `/card/history`; `retired_v1` block; kinds together and apart; picks, fills and combined figures apart | `api/card.py` | Default responses unchanged until cutover |
| Rule-labelled landing record | `api/meta.py` | Unchanged while `ACTIVE_CARD_RULE == "v1"` except the label |
| `--rule` on `card publish` and `card settle` | `src/cli.py` | Default `v1` |
| `ACTIVE_CARD_RULE`, `CUTOVER_DATE`, `frozen_card_v2`, `publish_all` | `src/report/card.py` | Additive |
| `card_v2_for_date` (fingerprinted) | new `src/report/card_v2.py` | New module, merged before T0 |
| 2025 backfill stores, the one-time 2025 fit, `data/processed/card_v2_frozen_params.json`; optional `dispersion`, `rho` and slot-table arguments; season-aware prop store | new fit script and stores (T0a); `src/analysis/strength.py`, `src/analysis/playerprops.py`, `src/report/props.py` | Before registration; V1's constants, live stores and nightly calibration untouched, pinned by byte-identity tests |

## Risks

1. **No verdict this season, and probably not soon.** The regular season ends
   2026-09-27. At about 2 counted game picks a day the read falls around
   August 2027 with no restart, later with one, and a restart is likely
   (registration 11.2). The harm check at 100 counted picks can remove "Take"
   well before that. Anyone expecting an answer in October will not get one,
   and the registration forbids lowering the floors.
2. **Stale quotes, from the schedule and from lag.** On 2026-09-15 every quote
   was more than 2 hours old at publication, so the registered rule would
   have shown 0 picks and, under the floor, 3 fills at those old prices, all
   three graded. Stale quotes are not only a capture
   failure: before any game is within 180 minutes of first pitch the dense
   pass prices the full slate only once an hour (`scripts/capture_slot.sh:355-388`).
   The registration answers this with a one-hour freshness limit
   (`grade.FRESH_SECONDS`) and by never withdrawing a pick on a stale read, so
   picks do not blink on and off each hour; a stale pick loses "Take" and says
   it is waiting for fresh prices. A lagging chain still leaves new picks
   waiting. What the freshness limit does not protect is the floor: a fill may
   be added from a stale quote, because otherwise a stale board would show
   nothing, so on a lagging day the record fills with entries priced over an
   hour ago. The audit WARN in T7 watches both; the fix is capture reliability,
   not the gate.
3. **Thin days, fills and owner expectations.** The design board gave 2 picks,
   both
   close to even money by the market's number. The owner asked for 3 to 10
   high-confidence picks, and named +100 prices, which V2 will almost never
   publish. He answered the thin-day question on 2026-09-15 ("Always show 3"),
   so the card fills to three with labelled close calls rather than showing
   fewer. That answer also moves the other end: because the ceiling counts
   picks only and a shown fill stays, a date that begins thin can list 13 bets,
   10 picks and 3 fills, more than the 10 he named. The registration states
   that departure (G12, section 6, question 1) and no task caps it; he rules on
   it before registration. Questions 5, 6 and 7 must still be answered with the
   illustration in front of him, before registration, as section 15 says.
3a. **The fills go on the record, and they are not picks.** By the owner's
   answer the card publishes and grades bets the rule itself says do not pass.
   On the design board that is 1 of 3 entries with fresh prices and 3 of 3 at
   the real publish instant, the last three at prices over two hours old,
   because a fill does not have to pass G3. Expect the fills' won-lost line to
   be worse than the picks', and expect a reader to see the combined figure.
   The guards are structural, not optional: `entry_class` on every entry, three
   separate figures on the record with none mixing the two, the verdict and
   every floor and harm-check threshold reading picks only (T8 raises rather
   than counting a fill), the audit's floor and fill checks (T7), and the
   registered F1 line that publishes the fills' result whatever it is. What
   these do not do is protect the reader's money; only the labels do that, so
   T9 and T12 treat a missing C12 line or a verb on a fill as a stop.
4. **Every "Take" rests on our unproven number, in a disagreement band nobody
   has measured.** G7 in practice selects bets where our number sits a few
   points above the market's. Honest copy mitigates it; it does not remove it.
   The harm check (registration 11.4) is the pre-registered early stop, and
   S2 cannot be used to retune G8.
5. **Best price enters two gates.** G4 and G7 use the best available price, as
   the reader is told to take it. A pick can pass because one book is a few
   cents better than the rest. D2 measures how often; it is not a gate.
6. **Withdrawals.** A pick shown and later withdrawn before its lock is
   graded at its last shown price and counted; the lock itself is V1's, as
   last published. The risk is a date with many withdrawals looking busy on
   the record. T3's lock-and-withdraw and settle tests are the guard; D4
   reports withdrawals per date, and the audit escalates a withdrawal written
   on a stale read.
7. **Run-line grading has one live precedent.** V1 graded one run-line pick
   ever. `grade_pick` handles signed lines; `tests/test_card_v2_settle.py` in
   T3 carries the +1.5 and -1.5 margin fixtures.
8. **Ownership collisions with R16-05.** `card.js`, `card.css` and
   `cardrecord.js` are owned by redesign groups in flight, and
   `src/analysis/daily_card.py` is listed under `copy-truth-sweep`. T9 waits
   for `gameday-card`; T10 and T10b run before T0 and are coordinated with
   `copy-truth-sweep`; TI goes through whichever group owns the rendering file.
   Doing any of it beside those groups creates two implementations.
9. **The banned-phrase test and meaning.** `tests/test_no_nothing_clears_the_bar.py`
   bans a meaning, not only spellings, and its docstring records the
   2026-09-10 directive: three to five bets every day. The owner's 2026-09-15
   answer keeps a floor of 3, so a normal V2 day lists three bets and the
   directive is honoured in meaning as well as in spelling on every board that
   offers three candidates past the first checks. It is not honoured on a board
   that offers fewer, which the registration states as a departure rather than
   fixing by relaxing a gate. Two cases remain to
   watch, and T9 and T12 check both: a day with fewer than 3 candidates past
   the first checks, which shows C13 and a count, and a day with a board so
   stale that the three entries are all fills at old prices, which shows C5;
   when both hold at once, C13 replaces C5's two fill sentences, so no string
   promises three bets beside two entries.
   The first case is not only a capture failure: a small slate of one-sided
   games can leave every favourite outside -160 and every underdog below 50%,
   so the board itself offers fewer than three candidates, and at zero the card
   shows a count and no entry. The rule does not fill past that, and the
   monitoring for it is T7's WARN and D4's per-date counts.
   Add `src/analysis/best_bets_card.py` to that file's `CUSTOMER_FILES` and
   `CUSTOMER_STRING_MODULES`; the banned lists stay as they are, and the
   docstring is amended only to record the 2026-09-15 answer beside the
   2026-09-10 directive.
10. **Settlement depends on the daily loop.** It failed or was cancelled on
    2026-09-12 to 2026-09-14 (`scripts/capture_slot.sh` comments). Unsettled
    days delay the read; they do not bias it, as long as voids stay counted.
11. **Default-branch schedule copy.** Not a risk for T6: the default-branch
    workflows check out the working branch and run its scripts. It becomes one
    only if a later change edits workflow YAML, which must then be synced.
12. **Postseason exclusion.** Picks from 2026-09-29 onward are published and
    graded but not counted. Say so on the record page if postseason picks are
    shown, so nobody reads them as evidence.
13. **The 2025 backfill gates registration.** Question 3 was answered no on
    2026-09-15, so nothing registers until 2025 starter logs, relief
    appearances
    and box scores are backfilled and every number is fitted once on 2025
    (T0a). A Stats API gap or a
    failed fit stops registration and goes back to Brey; it never falls back
    to 2026 games. The backfill must stay out of the live stores, because
    `pitchers.league_fip_constant` has no season filter and would move V1's
    numbers. A 2025 fit may also calibrate 2026 less well; the registered FAIL
    conditions on log loss and calibration error catch that, and nothing may
    be tuned in response.
14. **V1's sealed-window refit, now stopped, and the rest of V1, not stopped.**
    V1's nightly calibration refit
    read sealed-window games every night (diagnosis section 0) until Brey
    stopped it on 2026-09-15 ("Freeze it now"). That work and its record,
    `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md` (commit `ba09312c`), are
    separate from this build,
    which still changes nothing in V1's selection. What it changes here is the
    V1 shadow comparison, which no longer spans a calibration file that changes
    nightly (registration 11.6). The freeze covers only that file's `a` and
    `b`, and says so in terms: `DISPERSION`, `RHO`, the slot table and V1's
    selection code stay live and editable for the whole sample, and the model
    files changed in 15 commits in the five days before this plan. So the
    caveat is not retired, it is made measurable: T3 writes a
    `v1_code_fingerprint` on every V1 shadow row, T7 WARNs when it moves, T14
    checks it, and 11.6 publishes the comparison as against a changed model
    when it has moved for any reason other than a comment, a docstring or
    customer copy. A refit restart is one such reason, not the only one.

## Tests to update deliberately, collected

| Test | Change | Why |
|---|---|---|
| `tests/test_no_nothing_clears_the_bar.py` | Add `src/analysis/best_bets_card.py` to `CUSTOMER_FILES` and `CUSTOMER_STRING_MODULES`; amend the docstring to record the 2026-09-15 answer ("Always show 3") beside the 2026-09-10 directive. `TheCardAlwaysHasAFloor` stays, pinning V1 | New customer strings must be scanned; V1 constants do not change, and V2 now has a floor of its own, met by labelled fills |
| `tests/test_customer_language.py` | None expected; it scans all of `src/analysis` and `src/report`. If gate codes trip it, rename the codes rather than allowlisting | Keeps the scan strict |
| `tests/test_api_card.py` | Add `rule` cases only | Default shape unchanged until cutover |
| `tests/test_web_card_props.py` | Only if it asserts the "best of N books" meta line | That line is removed |
| `tests/test_card_record_page.py`, `tests/test_whose_record_is_it.py` | Two record blocks, each with kinds together and apart, and the V2 block with its picks, fills and combined figures apart | R5 of the registration |
| `tests/test_web_all_bets.py` | The `:183` count of `if (!payloadHasBets(payload)) {` changes when the V2 branch bypasses the walk-back and empty-card gates; the V1 path keeps both | A 0-pick V2 day must show its count and close calls, never yesterday's card (T9) |
| `tests/test_landing_record_from_ledger.py` | The landing record reads the active rule's ledger with a `rule` label | After cutover the landing page must not show V1's record as the live one (R4, R5) |

---

## Review record

Adversarial review of 2026-09-15, applied before registration in two passes.
Each finding was checked against the repo, and in the second pass against the
current text, so none was applied twice. Registration findings that changed
this plan (lock and settle, the illustration fixture, the sealed-window fits)
are recorded in the registration's Review record; the sealed-window decision
reached this plan as T0a, T0, T1, T5, T7, risks 13 and 14.

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| high | T9 renders only `why[0]` on the card face, so the mandatory "has not been shown to beat the market's" line sits behind "View breakdown", and phone rank 4 and below has no breakdown at all | Applied | Confirmed in `docs/DESIGN_BUILD_PLAN.json:367`; T9 renders `why[0]` and `why[1]` on the face at every rank and width; `test_card_v2_copy`, `test_web_card_v2` and T12 step 2 check it |
| high | Customer surfaces missing: the empty-card walk-back to yesterday, the landing record from V1's ledger, `landing-live.js`, `/card/history` | Applied | Confirmed in `web/js/card.js:709-752,822-900`, `api/meta.py:112-127`, `web/js/landing-live.js:279`, `tests/test_web_all_bets.py:183`; added to T5, T9, T12 and the tests-to-update table |
| medium | The 30-minute freshness gate fights the hourly full-slate capture, so picks blink on and off | Applied | Confirmed in `scripts/capture_slot.sh:355-388`; the registration uses `grade.FRESH_SECONDS` (3,600) and a stale read neither adds nor withdraws a pick; risks 2 and 6 rewritten |
| medium | T8 raises on the registration date, contradicting registration 11.1 | Applied | Confirmed; T8 raises only on sealed dates and filters by first pitch against `REGISTERED_UTC` |
| medium | Frozen fields carry no game type or code version, so 11.1's regular-season filter and 11.2's restart cannot be applied | Applied | Confirmed (no such field in `card.py` or `card_ledger.py`); `game_type` and `code_fingerprint` in T3, T7 and T8; the fingerprint now covers `playerprops.py` and the frozen parameter file |
| medium | Plan does not fit one or two sessions, leaves the reported defect live, and says nothing for question 1 "no" | Applied | Confirmed against ROADMAP R16-05 and R16-34; session estimates (now 19 to 21 with T0a), TI interim copy change with Brey's yes, and the question-1-no outcome |
| medium | T10 collides with the `copy-truth-sweep` group and the CTS-1 strings have no task | Applied | Confirmed in `docs/DESIGN_BUILD_PLAN.json` and ROADMAP R16-04; T10b added, T10 and T10b scheduled before T0 |

Low findings, both applied: T6's default-branch sync limited to workflow YAML
(confirmed in `.github/workflows/forward-capture.yml` and `daily-loop.yml`);
the floor test cited by its real name,
`TheCardAlwaysHasAFloor.test_the_floor_is_met_by_filling_from_the_split_pile`
(confirmed at `tests/test_no_nothing_clears_the_bar.py:288,296`). No finding
was rejected.

### Verification pass

An independent verifier then checked the applied findings. Its items that
touch this plan were re-checked and applied; none was rejected.

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| medium | The registered `code_fingerprint` covers `src/analysis/best_bets_card.py`, which T2 created only after T0; R1 needs a ledger row for every date from registration, but T2 to T6 came after T0; `card_v2_for_date` in `src/report/card.py` was not fingerprinted | Applied (verifier's option a) | Confirmed in the order table (T2 depended on T0). T2 to T5 now come before T0, on fixtures only; T0 computes the fingerprint and writes its value into registration section 16; T6 is committed directly after T0 in the same push; `card_v2_for_date` moves to a new fingerprinted `src/report/card_v2.py`. T3's fingerprint test, T7's audit and T14 check the value. Sessions unchanged (19 to 21): the tasks moved, none was added |
| high (from the registration) | Under O3 the nightly moneyline calibration, fitted partly on forward games, would have been kept | Applied | T0a now fits the moneyline calibration, the slot table and the run-line cover calibration on 2025 under either answer, and puts question 3 to Brey before the fit runs, because the answer decides what is fitted |
| medium (from the registration) | C11 gave one reason for two harm-check arms | Applied | T2's `harm_stop_sentence(arms)` and its test, T8 recording the arm, and T9 rendering the matching form |
| low | T6 cited `capture_slot.sh:504-506` for the card publish call and `:591-592` for staging `evidence/` | Applied | Confirmed on 2026-09-15: the `== card publish` echo and call are at `:535-536` (504-506 are slip comments) and `git add ... evidence data/paper_accounts` is at `:622-623`. T6 now names the echo line too, because the file shifts |

### Owner answers of 2026-09-15, applied to this plan

Brey answered four questions in chat at about 22:35Z (registration section 15
and 16). What changed here, and nothing else did:

| Answer | Applied where |
|---|---|
| Question 1, "Always show 3" | The floor-and-fills summary under the order table; T2's `RuleParams` (`floor=3`, `fill_to_floor=True`, no `close_calls`), `select`'s floor step and the three new copy functions; T2's test table (`test_card_v2_fills.py` added, count, copy, shadows and illustration rows rewritten); T3's frozen fields, `publish_v2`, `_lock_and_merge_v2`, `record` and `settle_v2` and their tests; T4's `measure_ledger`; T5's payload and record shapes and tests; T7's fill and floor escalations; T8's picks-only rule and the F1 line; T9's second section, C12, C13 and record lines; T12 steps 2, 4 and 6; risks 3, 3a and 9; the ledger and API table; the tests-to-update table |
| Question 4, "-160" | Nothing to change: `worst_price=-160` and `SHADOW_C` at -150 were already the plan's numbers. T0 now checks them rather than asking |
| Question 3, "Rebuild on 2025" | T0a marked owner-approved and its O3 branch dropped; T0 asks questions 5 to 8 only; risk 13 |
| The V1 freeze, "Freeze it now" | T0's V1 paragraph and risk 14; no task changes V1's selection |

The 2026-09-15 illustration was re-run with the fill rule by
`scratchpad/owner_answers/fill_illustration.py` and the numbers T2 and T12 must
reproduce come from it. Consistency with the registration and the diagnosis was
checked by `scratchpad/owner_answers/consistency_check.py`. Session estimates
are unchanged at 19 to 21: the fill rule adds one test file and work inside
tasks that already existed.

### Verification pass on the amendment (2026-09-16)

An independent verifier re-read the amended documents. Four problems with
substance were applied; three of them touch this plan. No task was added, no
session estimate moved and no gate, floor or threshold changed.

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| medium | The registration claimed the calibration freeze stops V1's model changing during the sample, which the freeze record itself limits to `a` and `b` | Applied | Confirmed in `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`. T3 now writes a `v1_code_fingerprint` on every `cards_v1_shadow.jsonl` row over the eight paths registration section 10 lists, T7 WARNs when it moves, T14 checks it, `test_card_v2_frozen_fields.py` covers it and risk 14 is rewritten. It restarts nothing and gates nothing; it only lets 11.6 say whether V1 moved |
| medium | C1, C12 and C5 promised three bets on days the rule lets the card list fewer, and C13 replaced C4 only | Applied | Confirmed against registration section 6 and C13. The registration's strings are fixed; here, `test_card_v2_copy.py` gains the two assertions (C13 replaces C5's fill sentences on a stale, thin board; no string promises three bets a day unconditionally) and risk 9 names the combined case |
| medium | The card can list 13 bets, 10 picks and 3 fills, against the owner's "3-10 bets", and nothing said so | Applied | Confirmed: the ceiling counts picks only and a shown fill stays. No cap added, because both ways of holding the total at 10 change what goes on the public record and that is the owner's decision. The floor-and-fills summary and risk 3 now state the maximum and point at the registration, where he rules on it before registration |
