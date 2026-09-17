# The never-ran register

Stage 18 H1. On 2026-09-16 the NFL card path was found never to have produced a
card — not once, ever — while printing "no game cleared the bar," a sentence
that reads like a decline and was in fact a dead path. Green tests existed.
They covered the functions, not the path. This register is the systematic
version of that discovery: for every production code path in this repo that can
emit a customer-visible or evidence-bearing artifact, it asks the only question
a test cannot answer — *has this thing ever actually written anything?* — and
answers it from the stores and the git history rather than from the code.

**45 paths audited: 24 LIVE, 9 DORMANT, 12 NEVER-RAN.** Of the twelve
never-ran, seven are expected and documented as such (Card V2 and its shadows
and variants are deliberately unregistered; tennis is a constants-only stub;
shadow D is deregistered by name on purpose). Five are alarming.

**Fix first: the live window.** It is three artifacts from one root
(`data/live/<sport>/<date>.jsonl`, `data/live/<sport>/window_gaps.jsonl`,
`evidence/live_candidates_v1.jsonl`) and not one of them has ever existed, in
the working tree or anywhere in git history. That is worse than the NFL card
was, because the NFL card is reached by one nightly command on an
`experimental=True` sport out of season, whereas the live window is wired into
*three* independent schedulers that are all running right now:
`scripts/capture_slot.sh` dispatches `live-window.yml` for `mlb` and `nfl`
every capture slot; `.github/workflows/live-window.yml` exists and is
dispatchable; and `scripts/daily_loop.sh` calls
`python3 -m src.appstate.live_ledger settle` every night against a store that
has never had a row in it. `src/pipeline/live_window.py:939` even stages
`data/live` and `evidence/live_candidates_v1.jsonl` for commit — and git has
never recorded a single one. MLB's season is live and its card publishes daily.
Three schedulers producing zero bytes for the sport that is actually playing is
the exact shape of the bug this stage exists to stop.

Nothing here was fixed. Per the task's explicit instruction, this pass is
register-only.

Evidence cutoff: 2026-09-16 (working tree and `git log --all` as of that date).
`data/historical/statcast`, `data/historical/lineups.jsonl` and
`data/tennis_trial/` are excluded by instruction — live jobs write there.

## The register

| Path | Artifact | First seen | Last seen | Verdict | Expected/Alarming | Command used |
|---|---|---|---|---|---|---|
| MLB card publish (`src/appstate/card_ledger.py:54`, via `src.cli card publish`) | `evidence/cards_v1.jsonl` (`card_published`) | 2026-09-10 | 2026-09-16 | LIVE | N/A | `git log --all --diff-filter=A --date=short -- evidence/cards_v1.jsonl`; 140 `card_published` rows |
| MLB card settle (`src.cli card settle`, `daily_loop.sh:272`) | `evidence/cards_v1.jsonl` (`card_settled`) | 2026-09-10 | 2026-09-16 | LIVE | N/A | event-kind tally of `cards_v1.jsonl`: 6 `card_settled` |
| Slip engine (`src/engine/slip.py`) | `evidence/slips_v1.jsonl` | 2026-09-09 | 2026-09-16 | LIVE | N/A | `wc -l` = 256; `git log --all --diff-filter=A` |
| Stand-downs (`src/report/stand_downs.py:33`) | `evidence/stand_downs_v1.jsonl` | 2026-09-09 | 2026-09-16 | LIVE | N/A | `wc -l` = 8,737; git first-add 2026-09-09 |
| Forward ledger recommendations (`src/ledger/bridge.py:39`) | `evidence/forward_ledger.jsonl` (`recommendation`) | 2026-08-28 | 2026-09-16 | LIVE | N/A | 332 `recommendation` rows; max ts `2026-09-16T10:13:53` |
| Settlement (`src/engine/settle_slate.py`) | `evidence/forward_ledger.jsonl` (`settlement`) | 2026-08-28 | 2026-09-16 | LIVE | N/A | 259 `settlement` rows in the same store |
| CLV / closing backfill (`src/report/clv.py`) | `evidence/forward_ledger.jsonl` (`closing_backfill`) | 2026-08-28 | 2026-09-16 | LIVE | N/A | 210 `closing_backfill` rows |
| V2 decision ledger (`src/ledger/bridge.py:40`) | `evidence/decisions_v2.jsonl` | 2026-09-03 | 2026-09-16 | LIVE | N/A | `wc -l` = 17,449; git last-touch `5b4ffbd7` |
| V2 reviews (`src/ledger/writer.py:28`) | `evidence/reviews_v2.jsonl` | 2026-09-03 | 2026-09-16 | LIVE | N/A | `wc -l` = 2,379 |
| V2 scorecards (`src/ledger/writer.py:29`) | `evidence/scorecards_v2.jsonl` | 2026-09-03 | 2026-09-16 | LIVE | N/A | `wc -l` = 332 |
| EOD review (`src/report/eod.py:60`, `daily_loop.sh:349`) | `evidence/eod_reviews_v2.jsonl` | 2026-09-03 | 2026-09-15 | LIVE | N/A | 33 rows; max date field `2026-09-15` |
| Paper wagers (`src/engine/slate.py:105`) | `evidence/paper_wagers_v2.jsonl` | 2026-09-03 | 2026-09-16 | LIVE | N/A | `wc -l` = 2,479 |
| Multibook odds capture | `data/processed/odds_multibook.jsonl` | — (untracked) | 2026-09-16 11:46 | LIVE | N/A | `wc -l` = 184,877; `date -r` |
| Odds snapshots | `data/processed/odds_snapshots.jsonl` | — | 2026-09-16 11:46 | LIVE | N/A | `wc -l` = 26,606 |
| Raw odds archive (`src/providers/odds.py`) | `data/raw/oddsapi/YYYY/MM/DD/*.jsonl` | 2026-09-03 (dir) | 2026-09-16 | LIVE | N/A | `find data/raw/oddsapi -type f \| wc -l` = 2,337; 98 newer than 2026-09-15 |
| Weather enrichment | `data/processed/weather_forecast.jsonl` | — | 2026-09-16 11:46 | LIVE | N/A | `wc -l` = 9,481 |
| Information events | `data/processed/information_events.jsonl` | — | 2026-09-16 11:46 | LIVE | N/A | `wc -l` = 2,493 |
| Boxscore ingest (current season) | `data/processed/boxscores_2026.jsonl` | — | 2026-09-16 11:46 | LIVE | N/A | `wc -l` = 7,235 |
| Batter prop capture | `data/processed/batter_props.jsonl` | — | 2026-09-16 11:46 | LIVE | N/A | `wc -l` = 66,720 |
| L1 projection (`src/pipeline`) | `data/processed/l1_observations.jsonl` + `l1_projection_state.json` | — | 2026-09-16 11:55 | LIVE | N/A | `wc -l` = 16,570; state file 387 bytes |
| Credit accounting (`src/capture/budget.py`) | `data/processed/credit_log.jsonl` | — | 2026-09-16 11:46 | LIVE | N/A | `wc -l` = 2,125 |
| Event↔game map | `data/processed/event_game_map.jsonl` | — | 2026-09-16 11:46 | LIVE | N/A | `wc -l` = 2,754 |
| Research registry (`src/research/alpha_registry.py`) | `data/research/alpha_registry.jsonl` | — | 2026-09-15 20:56 | LIVE | N/A | 92 rows: 48 mlb, 42 verdict, 2 nfl |
| Capture scheduler tick (`scripts/capture_tick.ps1`) | `data/logs/capture_tick.log` | — | 2026-09-17T00:55Z | LIVE | N/A | `tail -25 data/logs/capture_tick.log` |
| Paper accounts (`src/report/paper_performance.py:87`) | `data/paper_accounts/*.jsonl` | — | 2026-09-15/16 | LIVE | N/A | `ls -la data/paper_accounts` (52 files) |
| App analytics (`api/`, `data/app/app.db`) | `analytics_events` table | — | — | LIVE | N/A | `select count(*)` = 235 |
| Watch pollers (`src/pipeline/rosterwatch.py`, `umpirewatch.py`) | `data/watch/{lineups,probables,umpires,transactions}_watch.jsonl` | 2026-08-31 | 2026-09-14 21:26 (git 2026-09-15) | DORMANT | N/A | `ls -la data/watch`; `git log -1 --date=short -- data/watch/lineups_watch.jsonl` |
| Player-prop price capture | `data/processed/prop_prices.jsonl`, `prop_listing.jsonl` | — | 2026-09-15 13:32 | DORMANT | N/A | `date -r`; 3,360 / 2,571 rows |
| Derivative-market capture | `data/processed/derivative_markets{,_raw}.jsonl` | — | 2026-09-15 13:32 | DORMANT | N/A | `date -r`; 129,092 / 918 rows |
| F5 close capture (`src/pipeline/f5_tminus2.py`) | `data/processed/f5_close.jsonl` | — | 2026-09-14 20:22 | DORMANT | N/A | `date -r`; 1,327 rows |
| Adversary gate | `data/processed/gate_results.jsonl` | 2026-09-02 | 2026-09-06 16:25 | DORMANT | N/A | `head -c 400`; only 2 rows, first dated `2026-09-02` |
| Pre-registration predictions | `evidence/predictions.jsonl` | 2026-08-27 | 2026-08-27 | DORMANT | N/A | 21 rows, every one dated 2026-08-27; `git log -1` = `45988366` (2026-08-27) |
| Mismatch flags | `evidence/mismatch_flags.jsonl` | 2026-08-27 | 2026-08-27 | DORMANT | N/A | 2 rows, both 2026-08-27; git last-touch 2026-08-27 |
| Research scoreboard / shadow battery | `data/research/scoreboard.jsonl`, `shadow_battery_report.json` | — | 2026-09-06 16:25 | DORMANT | N/A | `ls -la data/research/*.json*` |
| Evolab sweep (`src/evolab/sweep.py`) | `data/research/evolab/*.json` | 2026-08-31 | 2026-08-31 (drift), sweep file undated | DORMANT | N/A | `find data/research/evolab -maxdepth 2` |
| Free-check grants (`api/betcheck.py`) | `free_check_grants` table | — | — | DORMANT | N/A | `select count(*)` = 2 (and `tokens` = 0, `users` = 1) |
| **Live window event store** (`src/pipeline/live_window.py`, `livefeed_mlb.py:35`, `livefeed_nfl.py:25`) | `data/live/<sport>/<YYYY-MM-DD>.jsonl` | never | never | **NEVER-RAN** | **ALARMING** | `find data/live` → only an empty `data/live/mlb/`; no `data/live/nfl`; `git log --all -- data/live` empty; `git ls-files data/live` empty |
| **Live candidate ledger** (`src/appstate/live_ledger.py:70`) | `evidence/live_candidates_v1.jsonl` | never | never | **NEVER-RAN** | **ALARMING** | `git log --all --diff-filter=A -- evidence/live_candidates_v1.jsonl` → no output; file absent |
| **Live window gap log** (`src/pipeline/live_window.py:401,414`) | `data/live/<sport>/window_gaps.jsonl` | never | never | **NEVER-RAN** | **ALARMING** | same `find data/live` / `git log --all -- data/live` |
| **NFL card** (`src/sports/nfl.py:39`, `src/report/nfl_card.py`) | `evidence/cards_nfl_v1.jsonl` | never | never | **NEVER-RAN** | **ALARMING** | file absent; `git log --all --oneline -- evidence/cards_nfl_v1.jsonl` → 0 commits |
| **F5 sealed-season results** (`src/engine/settle_slate.py:55`) | `data/historical/first_five_results.jsonl` | never | never | **NEVER-RAN** | **ALARMING** | file absent; `git log --all -- <path>` empty; `ls data/historical/odds_first_five` is also empty (contents live only as `.gz` under `data/archive/`) |
| In-play odds capture (`src/pipeline/live_odds.py:31,36`) | `data/live/odds_inplay.jsonl`, `data/live/credit_log_live.jsonl` | never | never | NEVER-RAN | Expected — ROADMAP.md Stage 18 B2 lists the private in-play watcher (W-16) as not yet run ("One real match watched end to end" is the *acceptance*, not a past fact) | `[ -e data/live/odds_inplay.jsonl ]` → no |
| Tennis card (`src/sports/tennis.py:22`) | `evidence/cards_tennis_v1.jsonl` | never | never | NEVER-RAN | Expected — `src/sports/tennis.py` docstring: "Constants-only stub: the provider lands later, so the two adapters are None and `experimental=True` keeps it out of anything customer-facing" (`schedule_fn=None`, `team_abbrev_fn=None`) | file absent; 0 commits |
| Card V2 store (`src/appstate/card_ledger.py:1435`) | `evidence/cards_v2.jsonl` | never | never | NEVER-RAN | Expected — ROADMAP.md Stage 18 B1 acceptance is "Named tests green; **nothing registered**"; T0 registration blocked on owner questions 12–14 | file absent; 0 commits |
| Card V2/V1 shadow stores (`card_ledger.py:1436-1439`) | `cards_v2_shadow_{a,c,e}.jsonl`, `cards_v1_shadow.jsonl` | never | never | NEVER-RAN | Expected — same B1 gate; shadows only run once V2 is registered | all four absent; 0 commits each |
| Card V2 variant stores (`card_ledger.py:1440-1445`) | `cards_v2_var_{strict_nocap,loose_cap3,loose_nocap}.jsonl` | never | never | NEVER-RAN | Expected — ROADMAP.md B1: "Card V2 T2v and T3v — the variant runner and per-variant ledgers" is queued work, not shipped work | absent; 0 commits |
| Card V2 shadow D | `evidence/cards_v2_shadow_d.jsonl` | never | never | NEVER-RAN | Expected **by design** — `card_ledger.py:1446-1450`: "THERE IS NO `CARD_STORE_V2_SHADOW_D`. Registration section 10 deregisters shadow D; `evidence/cards_v2_shadow_d.jsonl` must never be created by this module" | absent; 0 commits — the correct outcome |
| Cadence SLO (`src/capture/cadence.py:56`, `src.cli cadence`) | `data/processed/cadence_slo.jsonl` | never | never | NEVER-RAN | Expected, with a caveat — it is a manual CLI command; `grep -rn "cadence" scripts/*.sh .github/workflows/*.yml` finds no invocation, so nothing claims it runs. See the note below the alarms | `[ -e ]` → no; `git log --all -- <path>` empty |

## The alarms, and what to check next

### The live window — event store, gap log, and candidate ledger

These are one failure wearing three hats, so treat them as one investigation.
`data/live/` contains exactly one empty directory (`mlb/`, created 2026-09-16
11:55) and nothing else. `data/live/nfl/` does not exist. `git log --all --
data/live` returns nothing, and `evidence/live_candidates_v1.jsonl` has never
been added in any commit on any branch. So: no event rows, no gap rows, no
candidates, ever, for either sport.

What makes this alarming rather than idle is that three schedulers reference
it. `scripts/capture_slot.sh:571-595` runs
`python3 -m src.pipeline.live_window --should-dispatch --sport "$sport"` for
`mlb` and `nfl` on every capture slot, then `gh workflow run live-window.yml`
with three retries when the output starts with `DISPATCH`.
`.github/workflows/live-window.yml` exists and runs `scripts/live_window.sh`.
`scripts/daily_loop.sh:329` calls `python3 -m src.appstate.live_ledger settle`
nightly against a store that has never had a row.

What I would check next, in order. **One:** run
`python3 -m src.pipeline.live_window --should-dispatch --sport mlb` by hand
during an MLB game window and read whether it ever prints `DISPATCH` — if it
never does, the bug is in the should-dispatch predicate and no workflow was
ever launched, which would explain the total absence more cleanly than
anything downstream. **Two:** if it does print `DISPATCH`, list the actual
`live-window.yml` runs in Actions (`gh run list --workflow live-window.yml`) —
zero runs means the `gh workflow run` call is failing silently, and note that
`capture_slot.sh` swallows it behind `|| true` and only prints "failed to
dispatch ... after 3 attempts" to stdout, where nothing reads it. **Three:** if
runs exist and are green, the write path is the suspect — check whether the
workflow's commit step (`live_window.py:939` stages `data/live` and the
candidate ledger) ever had anything to stage, and whether the runner's
checkout even contains `data/live` (`live_remote.py:9` says the image "does not
copy `data/live`"). **Four:** independently confirm that the window ever had
upstream data to see — an in-play odds feed it can read — because
`data/live/odds_inplay.jsonl` is also absent, and a window with no feed under
it produces an honest zero that looks identical to a broken one. That last
check is what separates "never triggered" from "triggered and threw."

### The NFL card

`evidence/cards_nfl_v1.jsonl` has never existed. This is the path that started
Stage 18, and H3 has since fixed its empty-branch honesty, but fixing the
message does not make the path produce a card, and it still has not. It is
reached on a schedule: `scripts/capture_slot.sh:557` runs
`python3 -m src.cli card publish --sport nfl --date "$SLATE_DATE"` every slate
pass, and `scripts/daily_loop.sh:282` runs `card settle --sport nfl` nightly.
`src/sports/nfl.py` marks NFL `experimental=True`, which is a real mitigation —
it keeps NFL off customer surfaces — but experimental is not the same as
unscheduled, and a nightly job that has produced nothing since it was written
deserves an answer rather than a shrug.

What to check next. `src/analysis/prices.py:317` already carries a comment
about a join that "made `nfl_card.select()` return `[]` for every game,
always" — start by confirming whether that join is fixed and, on a real
Thursday slate, whether `src/pipeline/nfl_slate.py` returns a non-empty entry
list at all. If entries are empty, walk one game backwards: does the odds
provider return `americanfootball_nfl` h2h quotes, and do at least
`prices.MIN_BOOKS` books survive the de-vig? If entries are non-empty and the
card is still empty, the bar itself is the answer and the register entry
becomes EXPECTED. Roadmap B4 ("NFL live window observed firing for the first
time ... A real dispatch → capture → candidate row, **or an honest no-trigger
with the reason**") is the right template: the acceptable outcome is a reason,
not a silence.

### The F5 sealed-season results store

`src/engine/settle_slate.py:55` defines
`FIRST_FIVE_RESULTS_PATH = historical_path("first_five_results.jsonl")` and
`load_first_five_results()` is called from the CLI settle path
(`src/cli.py:2722`). The file has never existed in the tree or in git, and
`data/historical/odds_first_five/` is likewise an empty directory — its real
contents survive only as `mlb_{2023,2024,2025}.jsonl.gz` under
`data/archive/historical/odds_first_five/`. The module's own docstring calls
this "a frozen historical store," which is precisely the class of thing F2
("Evidence-store durability — a build product was committed while its input was
lost") exists to catch.

What to check next. Read `load_first_five_results()`'s behaviour on a missing
file: if it returns `{}` rather than raising, then every F5 settlement over the
sealed 2023-24 seasons has been silently settling against an empty dictionary,
and any F5 result computed from that path is not a null — it is an artefact of
a missing input, and every number downstream of it needs re-deriving. Then
check whether the archive `.gz` is the same store under a different name (a
restore script exists: `scripts/restore_historical.sh`), in which case the bug
is a path that names the unarchived location while the data lives archived —
cheap to fix, but it must be proven by byte-comparing a restored file against
what the loader expects, not assumed from the filename.

### A note on the cadence SLO, which I did not call alarming

`data/processed/cadence_slo.jsonl` has never been written, and
`src/capture/cadence.py:29` describes it as an append-only store of "one row
per (date, source)". I graded it EXPECTED because no scheduler, workflow or
document claims it runs — it is reachable only through `src.cli cadence` by
hand, and a manual command that nobody has run is not a broken path. It is
listed here anyway because a capture-cadence SLO that has never produced a row
is a monitoring surface the project believes it has and does not, which is the
same species of gap as the four accidents that opened Stage 18 even though it
is not the same severity. If it is meant to run, it needs a schedule; if it is
not, the module docstring should say so.

## What this register does not cover

Read-only surfaces that derive from the stores above and emit no artifact of
their own — `api/daily.py`, `api/digest.py`, `api/performance.py`,
`api/today.py`, `api/mybets.py`, `src/report/daily_record.py`,
`src/report/clv.py`'s report views, `api/tennis.py`'s board — are out of scope
by construction: their "never-ran" question is answered by whether the store
underneath them has rows, which the table already answers. The right follow-up
for those is H5 (monitor-target correctness), not this pass.

One observation that is not a never-ran finding but should not be lost: at the
time of this audit, `data/logs/capture_tick.log` had been printing
`skip capture: a run is already in flight` every fifteen minutes since
2026-09-17T00:10Z, while the newest write anywhere under `data/processed/` was
2026-09-16 11:55 local. A LIVE path that has stopped producing while its
scheduler reports a healthy skip is the DORMANT-in-progress case, and it is
worth a look independently of this register.
