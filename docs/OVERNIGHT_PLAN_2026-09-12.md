# Overnight workload, 2026-09-12

Written to be worked top to bottom without supervision. Every item has a
done-criterion that can be checked without asking anyone, and the tiers are
ordered so that stopping at any point leaves the most valuable work finished.

**Standing rules that do not get suspended because it is late:** measure
before promoting, publish the losers, pre-register before evaluating, and
never rank a customer surface by a number this repo has measured to be
adversely selected.

---

## Progress log (updated as the night goes)

- **T1.1 Bet Check purge — DONE** (`ba8e036`). The retired register is gone
  from Bet Check; verified on the running app, desktop and 375px. Server
  copy followed (`_bottom_line_text`, `_market_context` notes).
- **Found while doing it: the research count drifted again — DONE**
  (`52a3bef`). Block 07 said 41, block 10 said 27, same page. The Python
  constant now reads the registry.
- **T2 Today featured tile — DONE** (`3e448b9`). The same tile headlined
  Today as "LARGEST PRICE GAP" and fired a POST /betcheck on every load.
  `chooseGapCandidate` deliberately kept (it picks the hero's game) —
  owner decision, see below.
- **T2 My Bets form-above-wall — DONE** (`985e808`).
- **T1.2 Knowledge grade — DONE, one gap** (`5e55cd6`). Live on the Games
  grid (15 tiles, C/D at 2am, correctly: no lineups, stale boards). The
  card's frozen branch in `api/card.py` bypasses `card_for_date`, so a
  frozen card carries no legend yet — fixing next.
- **Owner decision added:** the hero on Today is still *chosen* by "largest
  price gap against consensus" (`chooseGapCandidate`). The tile that
  announced that rule is gone; the rule still picks the headline game.
- **T1.2 gap closed** (`7d6c98d`): a frozen card carries the legend too.
- **Found on Today, not in any test: the card printed "3 OF 9" twice.**
  Picks lock through the day and keep the `rank` they froze with (a frozen
  field), so the served row carried ranks `[3,2,3,1,2,4,5,5,4]`. The report
  layer now orders the served picks by the card's own stated rule and
  stamps `position`; `rank` is untouched as the receipt.
- **T2 sweep — DONE for every route.** `#/odds`: `SPREAD_CENTS`, a raw
  `has_board false / observed_utc null` key dump and the engineering rule
  "Never 'no odds'…" were on screen; all gone. **And the spread itself was
  wrong**: "205c between books" for LAA quoted between -105 and +100 (five
  cents apart) — plain subtraction across the hole in the American scale.
  The slate's WIDEST SPREAD headline was that artefact. Fixed with a test
  that fails on the old arithmetic. `#/day`: "no linescore row found in
  boxscores_2026.jsonl for game_pk=822767", "Under +8", raw
  `h2h_1st_5_innings`, "(a system id was stored here)" — all fixed.
  `#/billing`: the gate said "view tonight's board"; now names no route.
  `#/signup`: still sold the fair price across every book — rewritten in
  the owner's order (likely first, then what the price needs).
  `landing.html`: said "nothing here states a win probability or a
  predicted winner" and "the recommendation field stays permanently empty"
  while the card two clicks away says "64% to win" — both false; fixed,
  the "What line shopping is actually worth" section removed, hero
  rewritten to likelihood + break-even. `#/game` quick view, `#/support`:
  clean. Today's systems slip: "Backing the home side of h2h … (1)
  primary_pitch_share…" — engine prose now names the market in words and
  leads with the quantity (stored theses keep their old text; new ones
  read plainly).
- **Props are in the bottom nav** (took ODDS's tab; `#/odds` stays linked
  from the card, Today and every game page).
- **Two things the first pass missed, caught by re-opening the pages:**
  the landing hero is refilled at runtime by `landing-live.js` from
  `/opportunities` — the price-gap ranker — so it still read "Best of 11
  books · Caesars +175, ~~+160~~ Everywhere else" over the rewritten copy.
  It now leads with the card's first pick: who, how likely by the market,
  the price, and the win rate it needs. And the systems slip on Today
  printed "Moneyline at -182 (betrivers)" with no club: the slip names a
  pick by event id and a selection hash. `GET /today` now renders the
  club, side and book through `src/board/readable.py` on the way out
  ("Milwaukee Brewers (home) moneyline (-182, BetRivers)"); the ledger row
  is untouched.
- **`#/game` SHOW ADVANCED ANALYSIS — DONE.** It was the retired register
  end to end: SPOTLIGHT · PRICE STANDING (the featuredbet tile: BEATS
  CONSENSUS, IMPROVEMENT -1.38 pts, "line-shopping value", 11 BOOKS
  COMPARED), MODEL vs MARKET "ranked by price against the fair price only",
  BOOK VERSUS BOOK "the comparison that is real", and a MARKET REFUSAL that
  said player props were refused (false since the prop board shipped). The
  tile, its mapper and the verdict block are deleted from games.js; the
  board is "THE BOARD · every book's price from one capture instant"; OTHER
  MARKETS links the prop board. Tests that pinned the old wiring flipped.
- **Landing hero at 375px** clipped its new sentences (the block sized to
  its longest line, 451px on a 375px screen); fixed and measured.
- **T3 lineup store:** diagnosed. The runner restores `lineups.jsonl` from
  an actions cache and the 09-11 evening runs DID write rows
  (`lineups: games=15, written=2` at 22:55Z) — the script's `git add` for
  the file landed after those runs, so nothing reached git yet. First
  commit expected from tonight's afternoon slots (lineups ~16:30Z+).
  **Verify after 18:00Z:** `git log -1 -- data/historical/lineups.jsonl`
  shows a 09-12 capture commit.
- **T3 V6 forward reader — DONE.** `scripts/probe_lineup_direction.py
  --forward`: postings strictly after the registration instant
  (2026-09-11T20:38:15Z), PENDING below 150, family-wise α only. Ran it:
  12 of 150, PENDING. V6's discovery read is now recorded in the registry
  as `candidate` (read, not a survivor, not killed).
- **T3 slot test — PRE-REGISTERED (V7)** before any post-lineup quote
  exists: `docs/PREREG_SLOT_PROP.md`, reader `scripts/probe_slot_prop.py`
  (PENDING until 150 UP / 150 FLAT / 100+100 control rows), registry row
  `V7:lineup_slot_prop_repricing:batter_hits`. Market-only design (a
  batter against his own prior nights) so it needs no extra credits; the
  timing version needs a ~T-6h baseline capture and is the owner's spend
  call — see the doc.
- **Found in the registry while registering V7: "41 tested" was never
  true.** Five registered hypotheses have no verdict row — four V3
  forward-window tests still waiting on data, and now V7. `public_research_counts`
  now returns `read` and `pending` beside the total; every customer surface
  prints the READ count (37), the landing sentence says "tested, and none
  has survived", and the family-wise α still divides by all 42.
- **T4 event probe re-run — DONE.** Same verdicts; H2 crossed its floor
  (n=32) and is still UNDETERMINED; the control still does not confirm.
  Appended to `docs/EVENT_DIRECTION_RESULT.md`.
- **T5 debt:** the three doc-churn stashes and the `%SystemDrive%/` junk
  need a `git stash drop` / `rm` the harness would not run unattended —
  left for the owner (two commands, both listed in Tier 5).
- **T4 home runs, likelihood only — DONE.** `propboard.likelihood_only`:
  a market the model is measured good on (HR: calibrated to ~2 pts) with
  no under ever quoted joins the board with OURS and PRICE NEEDS, the
  market's own number absent and the row saying why in words. Ranked by
  probability like everything else, so it sits low — a home run is a
  ~10–20% event. Refused by name when no over is quoted either.
- **…and they are on the page.** A home run never clears the "more likely
  than not" list, so `/props` now carries `long_shots` — the ten likeliest
  home runs — under the heading "Home runs — none of these is likely".
  Verified on `#/props/2026-09-11`: "Rafael Devers over 0.5 home runs ·
  OURS 20% · PRICE NEEDS 17% · +500 at Caesars", with the absent market
  number said in words on every row. Found on the same page: books
  printed as feed keys (`williamhill_us`); fixed. `#/support` had no
  sentence saying what it was for; it has one.
- **T4 umpire signing — CANNOT, and why:** `umpirewatch` brackets WHEN a
  crew is revealed; no per-umpire run-environment history exists in
  `data/historical/`. Signing `umpire_assigned` needs an outside source
  of per-umpire strike-zone/run data. Not promised.
- **T5 reachability audit** already reads the default branch's workflows
  (`_default_branch_workflows`, done before tonight). Ran it: my four
  pre-registered readers were orphans by its rule and are now declared
  with the reason (run by hand at the floor; on a schedule they would
  read early). Still orphaned and not mine to declare cold:
  `_propboard.py`, `backfill_handedness.py`, `prereg_market_vs_model.py`,
  `probe_information_edge.py`, `probe_line_shopping.py`,
  `probe_lineup_slot.py`, `probe_platoon_split.py`.
- **Dead views deleted.** `web/js/featuredbet.js` (the tile) and
  `web/js/opportunities.js` (the value-points board) were imported by
  nothing that runs; both are gone with the tests that pinned their
  contents. `valuemeter.js` stays — `matchups.js` still uses it. The
  `.fb-`/`.opp-` rules in `screens.css` (~170 lines) are inert and left
  for a CSS pass.
- **`#/performance`** printed system ids as keys
  (`market_derived_consensus_totals_under`); they read in words now.
- **INCIDENT, mine, ~08:40–08:50 UTC:** the dead-view deletion missed the
  one remaining importer (`today.js` kept `opportunities.js` alive with a
  `void renderOpportunities;` line). My grep for importers was piped
  through `head` and the list was cut short. With no build step, one
  missing module fails the whole graph: the app rendered nothing, and
  since staging deploys on push, staging was blank for the minutes
  between `ade8477` and the fix. Tests were green throughout — none
  checks that imports resolve. `tests/test_web_imports_resolve.py` now
  does, and it is the test that would have gone red.

## Tier 1 — things the owner asked for that are still not done

### 1.1 Bet Check: delete the line-shopping register

**The complaint, verbatim, 2026-09-10:** *"this whole 'we do price
verification and see which book has the better odds, dude,' that has to
stop. None of that's important. Nobody fucking cares."*

Swept live on 2026-09-12 and it is still the dominant content of the page:

```
  BEATS CONSENSUS            No
  IMPROVEMENT                -1.89 pts best -190 (LowVig) vs a fair price…
  BOARD DEPTH                10 books, above the 6-book floor
  10 BOOKS COMPARED
  02  THE MARKET  ·  YOUR PRICE / FAIR PRICE / BEST AVAILABLE
  YOUR PRICE BEATS THE MARKET-IMPLIED CONSENSUS: NO
  PRICE VERDICT  ·  PASS
  "price improvement / line-shopping value — a better execution price…"   x2
```

**Rebuild it around the two questions in the owner's order:** is this likely,
and what does the price need. The comparison across books becomes one line of
execution detail at the bottom, never a section and never a verdict.

- Keep: the bet, our probability if we have one, the break-even, the case,
  the counterargument, what changed.
- Demote to a single line: which book, what price, how many books quoted.
- Delete: `BEATS CONSENSUS`, `IMPROVEMENT`, `PRICE VERDICT`, the whole `02
  THE MARKET` block, and both copies of the "price improvement /
  line-shopping value" caption.

**Done when:** `#/betcheck` on staging contains none of those strings, a test
asserts they stay gone, and the page still answers "should I take this".

### 1.2 Grade tomorrow's slate

The owner, 2026-09-12: *"tomorrow's bets... pre-analyzed and screened
thoroughly and have starter ideas for what's looking A+ Grade setups, B Grade
and everything below a C+."*

**A letter must mean something honest.** Our model's value estimates are
measured adversely selected (`-13.4%` against a `-9.1%` control), so grading
on "how much we beat the price" would put an A+ on a signal known to mislead.

**So the grade is a KNOWLEDGE grade, and the page says so in one line:** how
much do we actually hold on this game, not how much we expect to win.

| input | why it is honest |
|---|---|
| lineup posted, both sides | the batting order is a fact, and it sets plate appearances |
| both starters confirmed | a probable that changes invalidates the read |
| board depth and freshness | a thin or stale board is a thin read |
| sample behind each number | a 40-PA batter is not a 400-PA batter |
| our number vs break-even | **shown**, never ranked on |

`A+` = everything known and the number clears its price. `C+` and below =
something material is missing. The band boundaries are declared in the module
before any slate is scored, not tuned until the distribution looks nice.

**Done when:** a grade appears on every game for tomorrow, the definition is
one sentence on the page, and a test fails if the grade is ever computed from
the price gap alone.

---

## Tier 2 — defects found by looking at the live site

- **`#/mybets` shows a save form above a "SIGN IN REQUIRED" wall.** Offering a
  control that cannot work. Hide the form behind the same gate, or move the
  wall above it.
- **Nothing saves from Bet Check**, while `#/mybets` still instructs "Save a
  bet from Bet Check to track it here". Either wire it or remove the
  instruction. Removing is honest and cheap.
- **Player props are not in the bottom nav** — reachable only from the Today
  link and the footer. Decide: sixth tab, or replace `ODDS` (a price board,
  which is the register being retired anyway).
- **Finish the sweep.** `#/games`, `#/odds`, `#/day/{date}`, `#/support`,
  `#/signup`, `#/billing`, and `landing.html` have not been opened. Each at
  desktop and 375px, reading every sentence, console clean.

---

## Reconciliation with the sibling session (2026-09-11 overnight)

A second session worked this repo last night and its findings are in
`docs/CARD_MARKET_BREADTH_FINDINGS.md`. Three of them this plan did not have,
one it corrects, and one corrects this plan.

**Did not have, now folded in:**

1. **The mechanism keeping every other market off the card is two filters,
   not one.** `api/card.py:107` passes moneyline rows only, and
   `src/report/card.py:348` drops non-`h2h` a second time. This plan's Tier
   1.2 grading and any future card change has to go through both.
2. **`src/analysis/opportunities.py:361` already ranks every market on one
   measure.** Run on real slates: 2026-09-09 found five bets worth calling,
   **none a moneyline** — the same day the card published five moneyline
   favourites. The cross-market ranker exists; the card never receives it.
3. **The "thin boards" justification for moneyline-only was stale.**
   Re-measured: 424 priced derivative contracts on 09-09 — 46 team totals,
   30 strikeout props, 26 first-five totals. The docstring has been
   corrected.

**Corrects them:** the finding that derivative and pitcher-prop capture
"died 2026-09-10 with no workflow running them" was true when measured and
is not true now — `derivative_markets.jsonl` and `prop_prices.jsonl` both
carry observations from 02:11 UTC today. They run through
`scripts/forward_capture.sh` (`PROP_PRICES=1 DERIVATIVES=1`), which
`forward-capture.yml` invokes every fifteen minutes; a grep of the workflow
YAMLs alone does not see it. So "scheduled spend" is not an open owner
decision — it is already scheduled.

**Corrects this plan:** `batter_props.jsonl` has **not** written since
2026-09-11 07:10 UTC. The `CAPTURE_LEAD_MINUTES` change landed on the branch
at 02:48 UTC on 09-12 — after every T-2h window for tonight's slate had
already closed. **The first post-lineup batter-prop capture is tomorrow
evening, not tonight.** The owner was told "first real data tonight"; that
was wrong and is corrected below.

---

## Tier 3 — make tomorrow's new data usable

Two pipelines changed today. One produces its first real output tomorrow
evening, the other tonight. Build the readers now so nothing waits on me.

- **Verify the prop capture actually moved — tomorrow, not tonight.**
  `CAPTURE_LEAD_MINUTES = 120` landed at 02:48 UTC, after tonight's windows.
  Before it, all 9,672 batter-prop quotes landed 04:00-09:10 UTC. **Done
  when** the store holds a quote taken within two hours of a first pitch on
  the 2026-09-12 slate — the first one this product has ever had. Check
  after ~22:00 UTC on 09-12. If the 04:00 UTC run tonight writes nothing,
  that is the gate working (games are 17h out), not a failure.
- **Verify the lineup store is committing.** It had not moved since
  2026-09-08 because `forward_capture.sh` never staged it. **Done when**
  `data/historical/lineups.jsonl` carries tonight's date and the prop board
  reports a non-zero `batting_slot` count.
- **Pre-register the slot test.** A batter starting higher than his recent
  norm gains plate appearances, so his over should shorten. Sign fixed in
  advance, stopping rule declared, criterion committed **before** the first
  post-lineup quotes are read. This is the test the whole capture change
  exists to enable and it must not be written after seeing the data.
- **Lineup-direction forward replication.** `V6:lineup_surprise_direction:h2h`
  is registered and held at a floor of 150 out-of-sample postings collected
  after 2026-09-11. Build the reader that reports PENDING until the floor and
  refuses to read early, the same shape `V3:transaction_first_seen` is under.

---

## Tier 4 — research that is unblocked right now

- **Re-run the event-direction probe on the fixed join.** It gained 41 games
  of events this morning; `il_activation` crossed its floor to n=32. Cheap to
  re-read as the ledger grows.
- **Home runs, likelihood only.** 3,351 quotes and zero unders, so no fair
  price exists and none will be shown. But "how often does this batter go
  deep" is a real number we can stand behind, and the market is one the owner
  asked for by name. Surface it with the break-even column explicitly absent
  and labelled as to why.
- **Sign the other event kinds.** `umpire_assigned` (116 events) has an
  obvious directional claim — a pitcher-friendly plate umpire lowers a total
  — and needs per-umpire history to sign it. Check whether that history
  exists before promising anything.

---

## Tier 5 — debt that is cheap and keeps biting

- `scripts/reachability_audit.py` reads the working tree's workflows, but
  schedules live on the **default** branch. A script wired only in a
  working-branch workflow looks reachable while cron never runs it — exactly
  how the lineup-cadence gate hid.
- Two leftover `autostash` entries and two of mine in `git stash list`.
- A junk `%SystemDrive%/` directory sitting in the repo root, untracked.
- **Stolen bases are not collected at all.** Price the change: it is a
  per-event market, so cost it against `docs/RESOURCE_POLICY.md` before
  proposing, not after.

---

## Owner decisions surfaced tonight (not made)

- **Today gives two answers to "what do I bet".** TONIGHT'S CARD (the
  product: 3–5 picks, frozen, graded) sits above TONIGHT'S PICKS ("where
  our systems currently see the strongest case" — the engine slip, ranked
  by how many systems agree). `docs/PRODUCT_DOCTRINE.md` §5 names the
  slip as #1; the card did not exist when that was written. One should
  lead and the other should be labelled as research, or go. Which is a
  product call.
- **The hero on Today is chosen by "largest price gap against consensus"**
  (`chooseGapCandidate`) — the retired register still picks the headline
  game even though nothing on screen says so.
- **A ~T-6h baseline prop capture** (about one credit per game per night)
  would unlock the timing version of the slot test (`docs/PREREG_SLOT_PROP.md`,
  "Why this version"). Spend decision.
- **Drop the stashes and the junk directory** — `git stash drop` ×3 (all
  three are the same generated-doc churn) and `rm -rf '%SystemDrive%'`.

## What I will not do without being asked

- **Change what the card ranks on.** It ranks by how confident the market is,
  which is why every pick is a heavy favourite. Fixing that is a product
  decision with a real tension behind it — our own value estimates are
  measured adversely selected, so "rank by our edge instead" is not obviously
  better and may be worse. The honest options go to the owner with numbers,
  not into a commit at 3am.
- **Drop picks our model says lose.** Same reason. Tonight's card has four of
  five below their own break-even; whether that means publish fewer or
  publish differently is his call.
- **Turn on anything that spends materially more credits.**
