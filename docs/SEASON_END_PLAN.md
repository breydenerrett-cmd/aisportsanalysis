# Season-end and off-season posture

Written 2026-08-31. Design only — no code changed, no credits spent beyond the
free MLB schedule calls used to verify the dates below.
(`https://statsapi.mlb.com/api/v1/schedule`, queried live 2026-08-31.)

## 0. The verified 2026 calendar

| phase | dates | gameType(s) | games/day |
|---|---|---|---|
| Regular season (remaining) | through **2026-09-27** | `R` | 15 (full slate, confirmed) |
| Off day | 2026-09-28 | — | 0 |
| Wild Card | 2026-09-29 – 10-01 | `F` | 4 |
| Division Series | 2026-10-03 – 10-10 | `D` | 2–4 |
| League Championship | 2026-10-11 – 10-20 | `L` | 1–2 |
| World Series | 2026-10-23 – 10-31 (scheduled through; actual end depends on series length) | `W` | 1 |
| Off-season | after the WS ends (≤2026-10-31) until 2027 spring games | none | 0 |

All dates came back from the live schedule endpoint with `gameType` exactly as
shown; nothing here is assumed from a typical calendar. The World Series' real
end date is unknown until the series is played (a sweep ends 10-27) — treat
10-31 as the outside bound, not a prediction.

**This means the "taper" is not a gradual shrink.** Every team plays every day
through 2026-09-27 (15 games, confirmed), then the slate drops off a cliff:
0 games on 9-28, 4 on 9-29, and down from there. The decision in §1 needs to
exist *before* 2026-09-29, not eased into during September.

## 1. The taper

### 1a. What each collector does mechanically, unmodified, right now

Checked against code, not assumed:

- `src/providers/mlb.py:fetch_schedule` has **no `gameType` filter**. Verified
  live: `GET schedule?sportId=1&date=2026-10-05` (no gameType param) returns
  two `D` (Division Series) games. Every forward module that calls
  `mlb.fetch_games`/`fetch_schedule` — `dense.py`'s free pre-check,
  `rosterwatch.py`'s poll, `health.py`'s slate source — **will pick up
  postseason games automatically** with zero code change, exactly as they pick
  up any other day's games today. (Only `history.py`'s point-in-time ingest
  filters by `game_types=mlb.TRAINING_GAME_TYPES`, and that module is
  read-only historical reconstruction, not forward capture.)
- `dense.py` fires on **any** game inside its 180-minute window regardless of
  type, and its credit spend already scales with games-in-window — a 2-game
  Division Series night costs a fraction of a 15-game night automatically,
  with no configuration change. Same for the F5 close pass and
  `F5_CLOSE_MAX_EVENTS` (8): the ceiling just won't bind on a small slate.
- `rosterwatch.py` polls the same free endpoints (schedule, lineups,
  transactions) whether the day is `R`, `F`, `D`, `L`, or `W`. Postseason
  rosters change too (expanded/active-roster substitutions between series),
  so it will keep producing change rows.
- `prop_listing.py` samples from `provider.list_events` (free), which lists
  whatever the odds API is carrying — postseason games included once books
  price them. It keeps running under its own switch and caps (§1c) with no
  playoff-specific logic.

**None of this is a decision. It is what the code already does by default.**
The decision is whether that default is what we want.

### 1b. V3 admissibility — quoting the freeze, not reinterpreting it

`docs/RESEARCH_V3_TIMING.md` is frozen 2026-08-31. Searched in full: it
contains **no mention of `gameType`, "postseason", "playoff", or "World
Series" anywhere.** What it says admission turns on is exclusively this:

> "Admission of each class is decided by the timestamp-quality audit and
> recorded here at freeze; a class whose events cannot meet the quality gate
> is EXCLUDED, not downgraded."

and the per-event quality gates (§ Quality gates, frozen): minimum 6 books
quoting pre-event, the 30-event floor per class, the grade-B interval-width
cap, and the exclusion rules (10-minute contamination window, events after
first pitch, no pre-event snapshot inside 90 minutes). Every one of these
gates is about **timestamp quality and market depth**, not game type.

**What this means, stated plainly and without extending the freeze:** the
freeze's own text does not exclude postseason events, because it was never
written with postseason games in view — the freeze predates the postseason
by a month and the admitted-class table only discusses "forward" vs
"historical replay, 2023-24" as its axis. Silence is not the same as an
inclusive ruling. A `lineup_posted` or `il_roster_move` event bracketed the
same way during the ALDS meets every gate the freeze names, so a *literal*
reading admits it — but whether postseason lineup/scratch/IL events should be
pooled into the same four-class family as regular-season events, given they
happen under materially different incentives (must-win urgency, short rosters,
letting a starter go on short rest, quicker hooks) is a question the freeze
never considered and did not decide. That is exactly the kind of
after-the-fact reinterpretation the freeze protocol exists to prevent me from
doing unilaterally.

**This is a decision item for Brey (§3), not resolved here.** Two honest
options, presented without a recommendation: (a) admit postseason `R`-style
events into the existing four classes on the letter of the frozen gates, and
report a postseason/regular-season concentration check per the freeze's own
"Concentration checks adapted descriptively" clause (`a latency result carried
by one book, one team, or one week is reported as exactly that` — postseason
would need its own descriptive slice for the same reason); or (b) exclude
postseason `gameType` values from V3's event stream by policy note pending an
explicit amendment, the same way historical 2023-24 is excluded today, and
revisit only if a future family is designed around postseason specifically.
Nothing below assumes either answer.

### 1c. F5 / prop admissibility under the collection policy

`docs/COLLECTION_POLICY.md` also names no `gameType` restriction anywhere in
its three-layer policy, the feasibility-measurement amendment, or the prop
probe's caps. Its constraints are credit-based (the 132/day envelope,
`F5_CLOSE_MAX_EVENTS`, the prop probe's 18/day and 400-total caps) and
hypothesis-based (no research collection ahead of a registered hypothesis),
not game-type-based. Read literally, F5 and the prop-listing audit continue
into the postseason under their existing caps and switches with no code
change needed, and the credit cost falls automatically as the slate shrinks
(§1a). The prop-listing audit specifically expires on its own terms — the
400-credit cap or an abort criterion in `docs/PROBE_PROP_LISTING.md`,
whichever comes first, flipped off at the single switch already built into
`scripts/forward_capture.sh` (`PROP_LISTING_AUDIT`) — so no season-boundary
logic needs to be added there either.

One caveat worth naming: a 2-4 game Division Series slate makes the prop
audit's "3 games/day x 6 slots" sampling scheme sample a much larger fraction
of the available games than it does in the regular season. That changes the
audit's coverage properties (less random, closer to a census) but not its
budget or its risk — noted, not treated as a problem requiring a decision.

### 1d. The mirror-image case: spring training

The same absence of a `gameType` filter cuts both ways. When 2027 spring
training games appear on the free schedule (`gameType S`, typically
mid-February), `dense.py`, `rosterwatch.py`, and `prop_listing.py` will treat
them exactly like regular-season games with zero code change, the same way
they will treat postseason games this fall. Whatever admissibility decision
Brey makes for postseason events in §1b should be written down as one
decision framework that also covers spring training, not re-litigated in
February — this is flagged again in the spring restart checklist (§4).

## 2. The empty state

Verified against what the scripts and modules actually do on an empty
schedule, not assumed:

### Hourly loop (`scripts/forward_capture.sh`)

- `watch` (rosterwatch.poll) — free MLB endpoints only. **Zero credits**, on
  any day, confirmed by inspection of `rosterwatch.py`.
- `dense` — calls `mlb.fetch_schedule` (free) to build `_upcoming()` *before*
  touching the odds API at all; `dense.py:296-303` breaks the loop
  immediately with `reason = "no game inside the window"` when
  `games_in_window() == 0`. The one metered call made regardless is
  `odds_provider.quota()`, which the code's own comment states is "not
  metered." **Verified: dense costs zero credits on a slate-less day.**
- `prop_listing` — calls `provider.list_events` (free `/events`, confirmed 0
  credits per `docs/COLLECTION_POLICY.md`); with zero events, `by_date` is
  empty, the per-date loop never runs, and no fetch, no row, no marker is
  written. **Verified: zero credits.**
- The escalation checks at the bottom of the script (credit floor, missed
  window, F5-silent-collection) are simple string greps over already-produced
  output — no additional cost, and on an empty day none of them fire, so the
  script prints its section headers, "no data changes" (nothing to commit),
  and exits. **No git commit is made** (nothing changed), so no push either.
- **Model-wake cost: the script is invoked once per hour by whatever fires
  it (a trigger or cron entry) and produces one short, ESCALATE-free
  transcript.** The model reading it does zero reasoning work beyond
  confirming there's nothing to react to — which is the design intent stated
  in the script's own header comment. This holds whether or not the slate is
  empty; an empty slate just makes every section print its "nothing happened"
  line.

### Daily loop (`scripts/daily_loop.sh`)

- `cmd_grade`, `cmd_scan_grade`, `cmd_settle`/ledger status, pitcher-log and
  bullpen refresh — all read from stores already on disk or from free MLB
  endpoints (results, pitcher game logs, transactions). **Zero credits.**
- `cmd_predict`/briefing (`do_brief`) — builds `artifacts/briefing.html`;
  reads whatever forward ledger/matchup data exists. No games means no
  matchups to brief; this step should complete near-instantly and cheaply,
  though it is not purely free — the briefing path can call other data
  sources depending on flags (`no_odds` etc. are all False by default in
  `do_brief`), which is the same surface as the next finding.
- **Finding, verified from code, not assumed:** `do_snapshot()`
  (`src/cli.py:1280`) calls `snapshots.capture()` **unconditionally, every
  single day, with no free-schedule pre-check.** `snapshots.capture()` calls
  `odds_provider.fetch_normalized()` directly — the *paid* whole-sport
  h2h/spreads/totals call (`DEFAULT_MARKETS = ("h2h", "spreads", "totals")`,
  3 markets x 1 region). Per the provider's own documented billing model
  (`docs/COLLECTION_POLICY.md` and `src/providers/odds.py`'s comments: cost =
  markets x regions per call, not per game returned), **this call is billed
  the same whether the sport has 15 games that day or zero.** Unlike
  `dense.py`, `daily_loop.sh`'s snapshot step has no equivalent
  free-schedule gate before spending.
  - **This is the one non-zero, ongoing off-season cost in the current
    scripts: an estimated 3 credits/day, every day, for as long as
    `daily_loop.sh` keeps running through the off-season** — roughly 300-350
    credits across a ~3.5 month off-season (Nov 1 - mid Feb), against a
    53,000 balance and a 5,000 absolute floor. Small in absolute terms, but
    it is not the "~zero" this section was asked to verify, and it was
    heretofore undocumented.
  - **Unverified, stated honestly rather than guessed:** whether the odds
    API's billing behaves identically once MLB is fully off-season (as
    opposed to "in season with 0 games scheduled today," which is the only
    empty-slate condition currently testable) is not something the code or
    docs establish either way — The Odds API's per-sport availability during
    a true off-season is untested here. The cheap way to find out is to read
    the `x-requests-used` delta on the first off-season daily run rather than
    assume; do not extrapolate further than that single data point.
  - This is not something to fix by editing scripts today — boundaries here
    are docs-only — but it belongs in the off-season work map as a small,
    concrete reliability fix (§3), not as a Brey decision: gate
    `do_snapshot()` on the same free-schedule check `dense.py` already uses,
    so a slate-less day costs the same zero credits the hourly loop already
    achieves.
  - **DONE 2026-09-01.** `dense.any_game_scheduled()` (the same free
    yesterday/today/tomorrow schedule check `dense._upcoming` powers)
    now gates both the daily-loop snapshot step (`do_snapshot`) and the
    standalone `cmd_snapshot`: a slate confirmed empty skips the paid
    capture; a schedule OUTAGE (`None`) still captures, because missed
    movement on a live day is unrecoverable and an outage is not evidence
    the season is over. Regression tests: `tests/test_dense.py`
    (`AnyGameScheduledTests`) and `tests/test_cli_snapshot_gate.py`. The
    off-season daily cost is now the same ~zero the hourly loop already
    had. The `x-requests-used`-delta verification below is still the honest
    next step — the gate removes the spend on a confirmed-empty slate, but
    the true-off-season billing question it names is unchanged.
- Git behavior: `daily_loop.sh` stages `data`, `docs/OVERNIGHT_RUN.md`,
  `artifacts`, resets the always-regenerated `demo_latest.html`, and commits
  only `if ! git diff --cached --quiet`. On a day where `snapshot` wrote one
  new (probably identical-shaped, likely empty) row and nothing else changed
  meaningfully, whether that counts as "a diff" depends on whether the odds
  snapshot file changed at all — an empty snapshot (0 events) may still
  append a row with `captured: 0`, which would be a diff and would produce a
  daily commit of a single no-data marker. Not harmful, but worth knowing:
  **the daily loop will likely keep committing small marker-only diffs
  through the off-season**, which is fine for auditability but is not "no
  activity."

**Net verified answer to the question asked:** hourly loop is genuinely
~zero credits and ~zero model reasoning on an empty day, as designed.
Daily loop is ~zero model reasoning but **not quite zero credits** — a small,
identified, fixable gap (~3 credits/day) rather than the assumed zero.

## 3. Off-season work map

### IMPOSSIBLE (no code fix changes this — the input doesn't exist)

- Forward capture of anything: no odds movement, no lineup posts, no
  scratches, no F5 closes, no prop listings to measure. The forward evidence
  base is frozen at whatever it holds when the last game (postseason or not)
  ends.
- V3 accumulation. Every admitted class (`lineup_posted`, `starter_scratch`,
  `hitter_scratch`, `il_roster_move`) is forward-only by the freeze's own
  admission table; its clock stops the day games stop, full stop, regardless
  of how §1b is resolved.
- Forward ledger growth (Stage 7) — no games to recommend on or settle.
- F5 forward-series review growing further — whatever closes exist by the
  last game are what exist until 2027.

### IDEAL (this is exactly the window for this work — no live-evidence
opportunity cost while doing it)

- **SaaS build.** COMMAND_CENTER already names this the biggest bottleneck
  ("No deployable product... nothing makes them reachable by a customer").
  The off-season removes any tension between building the product and
  protecting forward-capture attention, since forward capture needs none.
  Domain-layer extraction, Bet Check/Debunker logic, API contract
  dataclasses, auth/subscription groundwork (once
  `PRODUCT_DESIGN_HANDOFF.md`/`SAAS_APPLICATION_ARCHITECTURE.md` land) — all
  already queued in COMMAND_CENTER's Wave 2 / Next 5.
- **Evolution Lab iterations on the frozen 2023-24 discovery set.** Zero
  credit cost by construction (`docs/EVOLUTION_LAB_ASSESSMENT.md` — replay
  engine, placebo-world noise-ceiling runs, Phase 2B sweep). None of it
  touches live data, so the off-season is not a constraint on it at all —
  but it also isn't blocked by the season being live today, so this item is
  "ideal to keep running through the off-season," not "newly unblocked by
  it."
- **Multi-sport prep, docs-only.** Stage 11 (KBO/NPB/NBA/NFL) stays
  explicitly BLOCKED/deferred by Brey ("stay on MLB") — that instruction is
  not overridden by the season ending. What *is* unblocked and already
  queued (COMMAND_CENTER item 8): the multi-sport hardcoding audit — finding
  every place MLB is assumed (season windows, `sportId=1`, gameType tables,
  team counts) — as a docs-only exercise that produces no commitment to
  collect anything.
- **Reliability (Stage 10).** Automation, retry coverage, the daily-loop
  credit-gate fix named in §2, reproducibility audits, a full regression pass
  with no live-data pressure competing for attention. This is close to a
  best-possible time to do this work: nothing forward is moving, so nothing
  is lost by spending model and script cycles on the pipeline's own
  correctness instead of on today's slate.
- **Documentation and evidence-package archiving** of everything accumulated
  in 2026 forward capture before the off-season, so the record is clean
  going into 2027 rather than reconstructed from memory later.

### DECIDED BY BREY (presented as decision items — not decided here)

1. **Postseason admissibility for V3 and for F5/props** (§1b, §1c). Needs an
   answer before 2026-09-29 (first Wild Card game) or the default (silent
   admission, per the code's current behavior) takes effect by omission.
2. **Winter-league / KBO / NPB feasibility collection.** Stage 11 in
   `docs/ROADMAP.md` defers multi-sport work pending "a validated forward
   result" and Brey's explicit go ("stay on MLB"). That instruction stands.
   What's new since it was given: MLB now has zero games to protect credits
   for, for roughly 3.5 months, which is a different cost calculus than when
   the deferral was made. This is surfaced as a live decision item, not a
   proposal to override the deferral: is a small, bounded *feasibility-only*
   measurement (same "does the market list this at all" pattern as the
   pitcher-strikeout probe, not price collection) of a winter league or
   KBO/NPB odds board worth a few hundred credits during the MLB dead
   period, purely to inform the eventual multi-sport decision with real
   numbers instead of assumptions? Recommendation: none given here on
   purpose. Options: (a) do nothing, resume the multi-sport discussion only
   after a validated MLB result as originally planned; (b) run a
   time-boxed, capped feasibility probe (structure mirrors
   `docs/PROBE_PROP_LISTING.md`) during the off-season and archive the
   result for whenever Stage 11 actually opens; (c) explicitly re-affirm
   "stay on MLB, no exceptions" and close this question for the season.
3. **Whether to spend anything on a full-season 2026 historical odds
   backfill now that the season is final.** The existing hard gate on large
   historical purchases (`docs/ROADMAP.md` — "Historical Purchases" in
   `docs/COLLECTION_POLICY.md`: none without a registered hypothesis naming
   the window, plus Brey sign-off) is unchanged by the season ending; this
   item exists only to note that the off-season is when the 2026 season's
   odds history becomes maximally complete and static, which is the best
   possible time to price such a purchase if a hypothesis ever names that
   window — not a recommendation to do so now.
4. **Whether `daily_loop.sh`/`forward_capture.sh` should keep firing on
   their current hourly/daily cadence through the confirmed dead period**
   (post-World-Series through spring training) at all, given §2's finding
   that they cost effectively nothing to leave running (~3 credits/day
   worst case, zero model reasoning). Recommendation: leave them running
   unmodified — the near-zero cost of running is lower than the risk of
   forgetting to re-enable them correctly in February (see §4) — but this is
   Brey's operational call, not assumed here.

## 4. Spring restart checklist (2027)

Everything that must be explicitly re-verified before or as 2027 forward
capture begins — not assumed to "just still work" because nothing broke over
the winter:

1. **Season bounds in providers.** `src/providers/statcast_pitches.py`'s
   `SEASON_WINDOWS` dict (verified: entries for 2023-2026 only, no 2027 row)
   needs a 2027 entry added from the real published 2027 schedule before any
   point-in-time Statcast rebuild touches 2027 games. Do not estimate the
   2027 window from a typical calendar — read it from the schedule endpoint
   once MLB publishes it, the same way this document's 2026 dates were
   verified rather than assumed.
2. **The gameType question, resolved once, applied twice.** Whatever Brey
   decides in §3.1 for postseason admissibility should be written down as one
   rule that also governs spring training (`gameType S`) admission for the
   same forward-only V3 classes (§1d) — verify at restart that spring
   training games are being handled per that rule, not silently admitted by
   the same code-level absence of a filter that this document surfaced.
3. **Store health**, run before trusting anything: `health.py`'s per-store
   `present`/anomaly checks against the first live 2027 slate day, to catch
   exactly the class of silent failure the 2026-08-31 forward-evidence audit
   found (a store believed to be accumulating that wrote nothing) before it
   repeats across a winter-cold container or credential.
4. **Trigger/schedule state.** Confirm the hourly and daily triggers are
   still enabled at the intended cadence — whether or not §3.4 is decided to
   leave them running through the winter, explicitly confirm the state
   matches the decision rather than discovering in March that they were
   paused (or never paused) by accident.
5. **Credit budget re-baseline.** Re-read the actual balance and re-run
   `estimate_daily_credits`/`odds_provider.estimate_credits` from the live
   configuration rather than trusting this document's 2026 figures — the
   layers active in 2027 (F5, the prop-listing audit's status — expired,
   cumulative-capped, or otherwise — any new market) may differ from what
   `docs/COLLECTION_POLICY.md` describes today, and the 132/day envelope and
   5,000 floor should be explicitly re-affirmed as still current, not
   inherited silently.
6. **The daily-loop credit gate (§2's finding).** If it was fixed during the
   off-season (§3, reliability item), verify it still correctly detects "no
   game today" on the first few real 2027 days without false-negatively
   skipping a real slate.

## 5. Explicit dates (repeated for a scannable summary)

- **2026-09-27** — last full 15-game regular-season day (verified).
- **2026-09-28** — a decision on postseason admissibility (§1b, §1c) is
  needed by end of this day. This is the last day before postseason games
  exist; the default (current code, no filter) takes effect automatically at
  the next game if nothing is decided.
- **2026-09-29** — first Wild Card game (`gameType F`); the postseason
  taper begins here for real, not gradually.
- **2026-10-03 to 2026-10-31 (bound; actual end depends on series length)**
  — Division Series through World Series; slate shrinks from 2-4 games/day
  to at most 1.
- **After the World Series ends (≤2026-10-31)** — the empty state (§2)
  begins in earnest and the off-season work map (§3) becomes the operating
  posture until 2027 spring games appear on the schedule (date not yet
  published; do not assume one).
