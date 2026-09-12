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
