# F1 Diagnosis: why the evolab genome systems write zero decision rows on the GitHub Actions runner

Scope note: this is a diagnostic document only. Nothing in this file changes
production code, the ledger, or any store. The one proposed diff at the end
is a diff to consider, not applied here.

## Bottom line

The genomes are not missing an input file. Every store the genome decision
path reads (Statcast pitch accumulator, the event->game_pk map, the
lineups_watch/probables_watch capture stores) is present, fresh, and
correctly populated on the runner's own checkout as of this investigation.

The actual cause is a **scheduling mismatch introduced by P0-2**, not a
missing store:

- `daily-loop.yml` now invokes `engine slate --date $TODAY` exactly once a
  day, at a fixed cron of `0 10 * * *` (10:00 UTC) --
  `.github/workflows/daily-loop.yml:30`, deliberately chosen (line 27's own
  comment) to run "well before the earliest MLB first pitch (~16:00Z)".
- `decision_time_for_game` (`src/engine/slate.py:489-536`) picks the
  decision instant `t` as the **latest L1 odds capture already on disk at
  the moment `engine slate` runs**, clamped to `commence_time - 5min`
  (`DEFAULT_PRE_GAME_MARGIN_MINUTES = 5`, `src/engine/glue.py:76`). Because
  the loop now runs only once, at 10:00-10:07Z, `t` ends up pinned to
  ~10:00-10:07Z for literally every game on the slate, regardless of how
  late that game's own first pitch is.
- MLB lineups post roughly 2-3 hours before each game's own first pitch --
  confirmed below with real per-game timestamps, all in the 17:00Z-22:00Z
  range for 2026-09-05's slate, none earlier.
- Every registered genome (all 16 -- 12 h2h + 4 F5) has
  `eligibility.require_lineup = True` (`src/evolab/genome.py:509-510`
  default h2h eligibility; `F5_ELIGIBILITY` dict,
  `src/engine/adapters/evolab_system.py:393-395`). `decide_with_reason`
  checks this FIRST, before market/book eligibility
  (`src/evolab/decide.py:248-249`):

  ```python
  if genome.eligibility.require_lineup and not worldview.lineup_posted:
      return NO_PLAY, NO_LINEUP
  ```

- At `t`~10:06Z, `worldview.lineup_posted` is false for every game, every
  day, by construction of the schedule -- not because a store is missing,
  but because the fact ("this team's lineup is posted") genuinely does not
  exist yet at that clock time. This is a real, honest `NO_LINEUP`, not a
  data outage.
- `EvolabGenomeSystem.propose()` then collapses that honest, specific
  refusal into an untraceable empty tuple
  (`src/engine/adapters/evolab_system.py:99-104`):

  ```python
  def propose(self, view: PriceBlindSnapshot) -> tuple:
      worldview = _rebuild_worldview(self.genome, view)
      decision, reason = decide_with_reason(
          self.genome, worldview, registry=self.registry)
      if not decision:
          return ()
  ```

  `reason` (here, literally the string `"NO_LINEUP"`) is computed and then
  thrown away on the very next line. `analyze()`'s PROPOSE loop
  (`src/engine/analyze.py:232`, `for proposal in system.propose(snapshot):`)
  iterates zero times over that empty tuple -- no `Candidate` is built, no
  adversary ever runs, and no `DecisionRecord` of any kind (not even a
  `refused_*` one) is written. This is why genomes vanish with zero forensic
  trace while `trivial_always_home`/`market_derived_consensus_*` keep
  writing `refused_thin`/`refused_stale` rows on the same bad days: those
  systems propose unconditionally (no `require_lineup`, no `min_books` gate
  in `propose()` itself) and only get judged after the fact, by the ATTACK
  phase, which DOES write a row for every candidate it vetoes.

Book depth and Statcast/asof-store freshness are both **ruled out** below,
with evidence -- not assumed away. The break is 100% attributable to the
single fixed 10:00Z cron now being the only time `engine slate` ever runs,
colliding with `require_lineup=True` on every genome.

---

## 1. The code path, with line numbers

`EvolabGenomeSystem.propose()` (`src/engine/adapters/evolab_system.py:99-104`):

```
 99  def propose(self, view: PriceBlindSnapshot) -> tuple:
100      worldview = _rebuild_worldview(self.genome, view)
101      decision, reason = decide_with_reason(
102          self.genome, worldview, registry=self.registry)
103      if not decision:
104          return ()
```

`decide_with_reason` (`src/evolab/decide.py:224-283`) is the single place
that can return `NO_PLAY`, always paired with one of seven named reasons
(`NO_LINEUP`, `MARKET_UNAVAILABLE`, `INSUFFICIENT_BOOKS`, `NOT_SIMULTANEOUS`,
`NO_SIGNAL`, `BELOW_ENTRY`, `CONFLICTING_SIGNALS` -- lines 80-86). The
lineup check runs first, before market selection:

```
248  if genome.eligibility.require_lineup and not worldview.lineup_posted:
249      return NO_PLAY, NO_LINEUP
```

`worldview.lineup_posted` traces back to `glue.build_snapshot`
(`src/engine/glue.py:341-421`):

```
384  ref = _resolve_ref(game, game_pk_map)
385  as_of_snapshot = None
386  if ref.asof_key is not None:
387      as_of_snapshot = asof_module.as_of(ref.asof_key, t, stores=as_of_stores)
388  if lineup_posted is None:
389      lineup_posted = bool(
390          as_of_snapshot is not None
391          and as_of_snapshot.get("home_lineup") is not None
392          and as_of_snapshot.get("away_lineup") is not None)
```

`t` (the instant this whole read is stopped at) is chosen once, per game, by
`decision_time_for_game` (`src/engine/slate.py:489-536`):

```
523  margin_cutoff = commence_dt - timedelta(minutes=margin_minutes)
524  rows = glue_module.read_l1_observations(game_key, path=l1_path)
525  eligible = [_parse_utc(r.observed_utc) for r in rows
526             if _parse_utc(r.observed_utc) <= margin_cutoff]
...
531  t_dt = max(eligible)
```

`eligible` can only contain L1 captures that already exist on disk **at the
moment `run_slate` executes**. `run_slate` calls
`glue_module.build_snapshot(game_key, t, board=board, game_pk_map=game_pk_map)`
at `src/engine/slate.py:816-817`, immediately after computing `t` this way,
inside the per-game loop that starts at line 768.

**Conclusion for item 1 of the ask**: "nothing" is a silent `return ()`
inside `EvolabGenomeSystem.propose()` itself. It is neither an exception
(nothing in `analyze.py`'s PROPOSE loop, `src/engine/analyze.py:229-233`, or
`slate.py`'s per-game loop wraps `system.propose(...)`/`analyze(...)` in
`try`/`except`) nor a guard in `slate.py` that skips the system before
calling it -- `run_slate` calls `analyze(snapshot, board, systems=systems,
...)` with every registered system, genomes included, on every game, every
day; the guard that turns the genome's honest refusal into nothing lives
entirely inside the adapter, at the two lines quoted above.

---

## 2. Every input the genome path touches, checked against tracked / bootstrap / rebuilt

| Input | Read by | Git-tracked? | Restored by `daily_bootstrap.sh`? | Rebuilt by `daily_loop.sh` itself? | Status on this checkout |
|---|---|---|---|---|---|
| `data/historical/statcast/` (pitch store) | `src/engine/features.py:_build_live` via `_accumulate_cached`/`_pitch_coverage_end` | No (`data/historical/*` gitignored) | Yes -- restored from `data-seed/statcast` orphan branch if manifest missing (`scripts/daily_bootstrap.sh` step 1) | Extended by `statcast --catchup` (`daily_loop.sh`) | N/A on this Windows box (empty `data/historical/`, expected -- laptop never had it); bootstrap's own restore path is real and unconditional on a fresh runner |
| `data/historical/handedness.json` | `features.py:_load_handedness` (feeds only `lineup_platoon_share`, not the other 5 registered features) | No | Not restored (bootstrap's own comment: populated live by the briefing step); cached across runs by `daily-loop.yml`'s `actions/cache` block | Self-heals per-game inside `daily` | Not the blocker -- 5 of 6 registered features don't touch it, and it only ever weakens one feature, never produces `NO_LINEUP` |
| `data/processed/event_game_map.jsonl` (gamekey: event_id -> game_pk) | `glue._resolve_ref` -> `gamekey.game_pk_for_event` | **Yes** (`!data/processed/event_game_map.jsonl` in `.gitignore`; `git ls-files` confirms it) | N/A (tracked, ships with checkout) | Extended by `gamekey --date $YESTERDAY --end $TODAY` (`daily_loop.sh`) before `engine slate` runs | **Verified fully resolved for every h2h event that actually got a decision on 09-05/09-06/09-07** (38/38 checked, all `resolved: true` with a real `game_pk`) -- ruled out, see section 3 |
| `data/watch/lineups_watch.jsonl`, `data/watch/probables_watch.jsonl` (the actual live `as_of` source for lineup/probable-pitcher features) | `asof.as_of()` via `src/core/asof.py:244-263` `_default_stores()` | Yes | N/A | Written every 15 min by `forward-capture.yml` -> `scripts/capture_slot.sh` -> `python3 -m src.cli watch` -> `rosterwatch.poll` (`src/cli.py:2107-2131`), a workflow independent of the daily-loop migration | **Actively growing through 09-05/09-06/09-07** (69/96/13 rows respectively), with real, non-empty `home_lineup`/`away_lineup` payloads -- ruled out as "missing", see section 3 |
| L1 odds observations (`data/processed/l1_observations.jsonl`) | `glue.build_board`, `decision_time_for_game` | Gitignored, self-refreshed | N/A -- explicitly NOT bootstrap's job (bootstrap's own header) | Refreshed by `run_slate` itself immediately before use | Present and deep: h2h book counts of 5-11 on every date checked |

None of the genome path's inputs are the missing/never-restored file the
bootstrap-coverage framing suggested. The one input that is **structurally
absent at the moment it's read** is not a *file* at all: it's the fact "this
team's lineup is posted", which literally does not exist yet at
`t`~10:06Z UTC for any game whose first pitch is hours away. That is a
timing problem, not a data-plane restoration gap.

---

## 3. Proof, without writing to any store

### 3a. Book depth is not the blocker (ruled out with real ledger data)

Queried `evidence/decisions_v2.jsonl` (read-only) for `books_at_decision` by
`market_key` on 2026-09-05/06/07:

```
('2026-09-05', 'h2h')     {11: 45}
('2026-09-06', 'h2h')     {11: 45}
('2026-09-07', 'h2h')     {5: 6, 8: 6, 9: 12}
```

Every h2h decision on every one of these dates was made against 5-11
quoting books -- always comfortably above every genome's
`eligibility.min_books = 3`. If book depth were the gate, it would explain
thin *spreads* refusals (which do show up: `refused_thin: 60`,
`refused_stale: 15` in `docs/eod/2026-09-05.md`'s adversary-veto section --
all `thin_board`, all against `spreads`/`totals`, never against the deep
h2h board) but it cannot explain zero h2h genome decisions on a slate whose
own h2h board is 5-11 books deep.

### 3b. The gamekey map is not the blocker (ruled out with real data)

Every `event_id` that produced an h2h decision on 09-05/06/07 (38 total)
was checked against `data/processed/event_game_map.jsonl`: all 38 are
`resolved: true` with a populated `game_pk`. `ref.asof_key` is not None for
any of these games, so `as_of_snapshot` is built for all of them.

### 3c. The lineups_watch/probables_watch stores are not stale or empty

`data/watch/lineups_watch.jsonl` carries 568 total rows spanning
2026-08-31 through 2026-09-07 with no gap, including real (non-"poll")
entries with populated `home_lineup`/`away_lineup` arrays. `probables_watch`
likewise. Both are written every 15 minutes by `forward-capture.yml`
(`cron: "*/15 * * * *"`), a workflow untouched by the daily-loop migration.

### 3d. When the 09-05 lineups actually posted, vs. when the slate ran

The 09-05 `engine slate` run recorded `decision_utc` = `2026-09-05T10:06:25Z`
(from `evidence/decisions_v2.jsonl`). Checking `data/watch/lineups_watch.jsonl`
for the 15 games that got an h2h decision that day, the first instant each
game had **both** sides' lineup posted:

```
822850  first both-sides-posted 2026-09-05T21:16:13Z
823094  first both-sides-posted 2026-09-05T22:17:02Z
823257  first both-sides-posted 2026-09-05T20:16:24Z
823335  first both-sides-posted 2026-09-05T20:16:24Z
823419  first both-sides-posted 2026-09-05T19:16:48Z
823577  first both-sides-posted 2026-09-05T18:16:18Z
823823  first both-sides-posted 2026-09-05T17:16:09Z
823904  first both-sides-posted 2026-09-05T22:17:02Z
824066  first both-sides-posted 2026-09-05T20:16:24Z
824145  first both-sides-posted 2026-09-05T21:16:13Z
824310  first both-sides-posted 2026-09-05T22:39:44Z
824389  first both-sides-posted 2026-09-05T19:16:48Z
824468  first both-sides-posted 2026-09-05T19:16:48Z
824553  first both-sides-posted 2026-09-05T21:16:13Z
824795  first both-sides-posted 2026-09-05T20:16:24Z
```

Every single one is 7-12 hours **after** the 10:06Z decision instant. At
`t`=10:06Z, `lineup_posted` was false for all 15 games on the real 09-05
slate -- not a guess, the actual per-game evidence.

This also explains the *historical* success: querying `decisions_v2.jsonl`
for every genome's own `decision_utc` time-of-day, every single genome
decision ever recorded clusters in `16:25`-`01:51` UTC (afternoon through
overnight), never near `10:00` UTC:

```
4a7700d36b3855ab  HH:MM seen: 01:31, 18:01, 23:47
606be696ff199952  HH:MM seen: 00:01, 00:02, 01:31, 16:25, 16:55, 22:31, 23:31, 23:47
8974e1cb85d58bcb  HH:MM seen: 00:01, 01:31, 01:51, 16:46, 16:55, 19:01, 19:31, 22:19, 23:31
... (12 genomes, same pattern)
```

The pre-migration cloud session was invoking the loop repeatedly across the
day (afternoon/evening/overnight UTC, exactly the window lineups actually
post in), so `t` for each game routinely landed after that game's own
lineup post. The Actions cron collapsed this to one run, fixed at 10:00Z,
which by design (line 27's own comment) never lands after any lineup post.

### 3e. Direct, isolated code execution (no store writes)

Ran a standalone script (`AISPORTS_DATA_DIR` pointed at an empty temp
directory; no `run_slate`/`run_settle`/ledger writer called; imports only
`REGISTERED_GENOMES`, `EvolabGenomeSystem`, `decide_with_reason`,
`PriceBlindSnapshot`) against genome `4a7700d36b3855ab`
(`eligibility=Eligibility(markets=('h2h',), min_books=3, require_lineup=True)`),
holding books (11) and every registered feature deliberately generous so
only `lineup_posted` varies:

```
lineup_posted=False  ->  decide_with_reason: (NO_PLAY, 'NO_LINEUP')
lineup_posted=True   ->  decide_with_reason: Decision(market='h2h', side='away', score=1.0, ...)

lineup_posted=False  ->  EvolabGenomeSystem.propose(): ()            (len=0)
lineup_posted=True   ->  EvolabGenomeSystem.propose(): (Proposal(...),)  (len=1)
```

This confirms, by direct execution rather than by reading, that
`decide_with_reason` computes a real, specific, named reason
(`'NO_LINEUP'`) and that `EvolabGenomeSystem.propose()` discards it and
returns an empty tuple indistinguishable from "this system had nothing to
say" -- the exact silent-swallow mechanism described in section 1, exercised
end to end on a real registered genome.

---

## 4. Should a genome that cannot get its inputs be silent?

No. The lab's own stated discipline is to refuse loudly: `decide.py`'s
`NO_PLAY`/reason vocabulary (`NO_LINEUP`, `INSUFFICIENT_BOOKS`,
`NOT_SIMULTANEOUS`, `NO_SIGNAL`, `BELOW_ENTRY`, `CONFLICTING_SIGNALS`,
`MARKET_UNAVAILABLE` -- `src/evolab/decide.py:80-86`) exists specifically so
"why did this system not play" is always answerable, matching design
section 9's "death-label vocabulary" that the rest of the system (adversary
`refused_*` verdicts, `docs/eod` reporting) is built around. A `Decision`
that dies silently defeats the entire purpose of that vocabulary.

Two distinct defects are present, and they are not the same defect:

1. **The scheduling mismatch** (single 10:00Z cron vs. lineups posting
   2-3h pre-game, staggered through the evening) means genomes are
   currently *structurally* excluded from ever playing under the live
   Actions schedule -- not broken, but never given a fair chance. This may
   or may not be something anyone actually wants changed (running at
   10:00Z is deliberately conservative -- "well before the earliest first
   pitch" -- so no game is ever staked in-play); it is at minimum an
   unreviewed interaction between two independently reasonable choices
   (early-safe cron timing + `require_lineup=True`) that nobody connected
   when P0-2 shipped.
2. **The silence itself** is a defect regardless of (1). Even if running
   this early is the intended, permanent behaviour, a genome that refuses
   for a real, nameable reason should leave exactly as much of a trace as
   `trivial_always_home` leaves when a board is thin -- something
   `docs/eod/*.md` and a human glancing at `evidence/decisions_v2.jsonl`
   can see. Today it leaves none, which is why this required a multi-file,
   multi-store investigation instead of a one-line grep. The silence is
   the thing I would fix first: it is cheap, safe, and it would have made
   this exact diagnosis take minutes instead of hours the next time
   something upstream changes.

## 5. Proposed fix (diff only -- not applied)

**Not proposed**: changing `.github/workflows/daily-loop.yml`'s cron or
adding a second scheduled `engine slate` pass. That is the fix that would
actually let genomes play again, but it is a product/scheduling decision
(how many times a day should the loop run, what does that cost in
compute/credits, does a second pass on `daily_loop.sh` re-run the expensive
results/pitcher/bullpen/settle steps or need a slate-only variant, does it
race `forward-capture`'s shared concurrency group) that belongs to whoever
owns P0-2, not something to slip in as a "small" diagnostic-adjacent patch.

**Proposed** (genuinely small, additive, zero schema/behavioural risk): make
`EvolabGenomeSystem.propose()`'s decline visible in the run's own log
output, without touching the ledger, `DecisionRecord`, or any store. A
market-less/selection-less refusal cannot honestly become a
`DecisionRecord` under the current schema (every `DecisionRecord` names a
`market_key`/`selection_id`, which `NO_LINEUP`/`NO_SIGNAL`/etc. never
reach) -- inventing that record shape is a real schema decision belonging
to whoever owns `src/ledger/records.py`, not a small fix. A log line is:

```diff
--- a/src/engine/adapters/evolab_system.py
+++ b/src/engine/adapters/evolab_system.py
@@ -99,7 +99,11 @@ class EvolabGenomeSystem:
     def propose(self, view: PriceBlindSnapshot) -> tuple:
         worldview = _rebuild_worldview(self.genome, view)
         decision, reason = decide_with_reason(
             self.genome, worldview, registry=self.registry)
         if not decision:
+            # Refuse loudly (decide.py's own discipline -- NOTHING IN THIS
+            # PACKAGE IS EVIDENCE, but every NO_PLAY has a name and it
+            # should not vanish without one). Stdout only: no ledger/store
+            # write, so this cannot affect determinism, replay, or any
+            # existing test that asserts on decisions_v2.jsonl content.
+            print(f"  [{self.id}] declined: {reason} "
+                  f"(game_pk={view.game_pk} t={view.t})")
             return ()
```

Test to add: a unit test on `EvolabGenomeSystem.propose()` (not
`run_slate`/`run_settle`) that constructs a `PriceBlindSnapshot` with
`lineup_posted=False` (mirroring section 3e above) and asserts the decline
is printed/logged with the genome's id and the `NO_LINEUP` reason, while
still asserting `propose()` returns `()` -- i.e. pin the current *return*
behaviour exactly, only add visibility. This can be written and run without
touching `evidence/`, `data/`, or any file in the off-limits list.

**Risk of applying this blind before the next 10:00Z slate**: low, but not
zero. `daily_loop.sh` redirects `engine slate`'s combined stdout/stderr into
`/tmp/daily_run.out` and greps it for lines starting `^ESCALATE:`
(`scripts/daily_loop.sh`, the "Fail the job on any ESCALATE line" step in
`daily-loop.yml`). A `print()` here is inert with respect to that grep (it
does not start with `ESCALATE:`), but it does add up to 27 lines of stdout
per game to the Actions log for every slate run, every day, forever, given
the confirmed diagnosis that every genome will decline on every game under
the current schedule -- noisy, not unsafe. The bigger real risk is not this
diff at all: it's mistaking "now it logs a reason" for "now it's fixed" and
treating F1 as closed when the underlying scheduling mismatch (section 4,
defect 1) is still there and genomes are still not playing.
