# Pre-registration — SR: home underdog price band (moneyline)

**Status: FROZEN PRE-REGISTRATION, amendment 1. Written, amended and re-frozen
before any outcome row was read.**

This file is the frozen spec `docs/RESEARCH_STRATEGY_REPLICATION.md` §4 and
`docs/SR1_RESULT_2026-09-16.md` §5 said had to exist before a single 2023 row
could be graded. It promotes SR1/SR2 from *drafted template* to *registered
hypothesis*. Two rows have been appended to `data/research/alpha_registry.jsonl`
through `src.research.alpha_registry.register()`, both before any read:

1. `SR:home_underdog_price_band:h2h` — the registration, at the first freeze.
   It carries the sha256 of the **v1** text and is never edited.
2. `SR:home_underdog_price_band:h2h:amendment-1-2026-09-16` — the amendment
   (§17), carrying the sha256 of **this** text. It registers no new search and
   spends no alpha (§13).

**The freeze check is: recompute `sha256` of this file and compare it to the
`note` on the amendment row.** If the two disagree, this document has been
edited after registration and nothing computed from it is admissible.

**Nothing in this document was informed by an outcome**, at either freeze. The
candidate counts, book counts, price distributions, date counts, team
concentration, breakeven gaps and power figures in §4, §9 and §10 were computed
from the odds archive alone
(`data/archive/historical/odds_history/mlb_{2023,2024}.jsonl.gz`). The
2023 and 2024 game-result rows were not opened — as §11 records, they are not
on disk at all.

---

## 1. Provenance, and the one deliberate change to the draft

The owner, 2026-09-16: *"Theres a lot of times where trhe underdog actuall
makes more sens than the favorite and those are the real bangers ... +100 to
+250 poicks offer rally good value"*.

`docs/RESEARCH_STRATEGY_REPLICATION.md` Template A drafts the matching
candidate, SR1, at **+100 to +150 inclusive**. The owner's spoken range is
**+100 to +250**. `docs/SR1_RESULT_2026-09-16.md` §5 flagged that the two are
not the same rule and that the band could not be widened *after* a look without
violating the standing "no rescue by threshold or definition change" rule (T8).

This registration resolves that the only way it may honestly be resolved: the
wider range is split into **two bands declared as two separate sub-hypotheses,
before any read**, so that neither can be used to rescue the other afterwards.

| sub-hypothesis | band (consensus home American price) | source |
|---|---|---|
| **A** | +100 to +150 inclusive | SR1's drafted rule, unchanged |
| **B** | +151 to +250 inclusive | the owner's stated range, minus the part band A already covers |

Bands A and B are exhaustive and mutually exclusive over +100..+250. A
selection belongs to exactly one. **Merging them, re-splitting them, or
reporting a pooled +100..+250 number is forbidden after any read** — the
declared family is two tests, not three and not one.

The divisional restriction (SR2) is **not** registered as a family member and,
under amendment 1, **is not computed in this run at all**. See §7 for the
decision and its reasoning.

## 2. Mechanism, and the prior recorded before the look

Favourite–longshot bias: bettors are held to overpay for favourites and
underpay for longshots. It is a documented effect in other markets. **This
project has no internal evidence for it, and one internal measurement against
it.**

**Correction, amendment 1 (§17), made before any outcome row was read.** The
first frozen version of this section claimed *"independent internal
corroboration that the raw ingredient exists in its own data — V2's M5
(catalogue N12) measured that de-vig methods diverge specifically on lopsided
prices"*. That reads a null result as a positive one. N12's verdict, verbatim
from `docs/RESEARCH_CATALOGUE.md` line 85:

> **NULL.** n=4,486. Log loss 0.674168 / 0.674160 / 0.674177 / 0.674160; Brier
> 0.240707 / 0.240708 / 0.240719 / 0.240708 — agreement to the fifth decimal,
> the "best" method flips between metrics. Median between-method disagreement
> 0.37pp.

The same row records that Shin is *identical* to additive on two-way markets to
13 decimals. So the repo's own measurement of two-way prices — the exact market
this family trades — found **no exploitable de-vig divergence**, which if
anything is evidence against the mechanism rather than for it. The error was
inherited from `docs/RESEARCH_STRATEGY_REPLICATION.md` lines 193, 222 and 288
and carried forward without opening the catalogue. **There is no independent
internal corroboration of this mechanism. The sentence claiming there was is
withdrawn.**

The one correct use of N12 in this document is in §3 — "the system-wide
primitive M5/N12 confirmed" refers to N12's actual keeper, that proportional
de-vig stands system-wide. That sentence stands unchanged.

**Pre-registered prior: MEDIUM-LOW**, the label carried over from Template A,
but recorded now as sitting at the **bottom** of that band rather than the
middle: the external literature is unchanged, the single piece of in-house
mechanism support has been withdrawn, and it pointed the other way. Band B is
additionally a structural bet on a handful of bad teams (§10), which lowers its
prior below band A's.

Base rate this family is judged against: Sung & Johnson found 0.45% of 1,547
simple MLB moneyline strategies profitable at the 1% level; this program is
zero-for-46 registered hypotheses plus one 8,811-candidate sweep that landed
below the median of three placebo worlds. **The pre-stated expectation is zero
survivors.**

## 3. The selection rule, fixed

**Universe.** Every MLB event in `data/archive/historical/odds_history/mlb_2023
.jsonl.gz` (sha256 `e22f6bef8d2baef8c77381cfd51e0178013039985aa02d3fd025c885075c6e34`,
2,931,333 bytes) and `mlb_2024.jsonl.gz` (sha256
`881a2eb639a19b0308770eac2df6702bd44514eb005bb4eba8d2ae6537fc5949`,
2,199,377 bytes), market key `h2h`, full game. No other market, no other
season. 2025 is tuning-only and is not touched by this registration ever.
2026-01-01..2026-08-27 is sealed and is not touched.

**Postseason and spring training, settled explicitly (amendment 1).** The
universe is *every* priced MLB event in those two files, **including the
postseason** — no calendar filter is applied, because the source rule states
none and adding one after the counts were seen would be a definition change.
The archive holds **12 (2023) and 15 (2024)** priced events after the regular
season ends, of which **exactly 1** falls in a band (band A, 2024); the
published result must carry that count. Spring training is not an issue: **zero
priced events fall before Opening Day** in either season, so the archive's
2023-02-27 first snapshot leaks no exhibition game into the sample.

**Decision instant.** For each event, the **latest stored snapshot at least
`src.pipeline.backfill.RECOMMENDATION_LEAD_MINUTES` = 360 minutes before that
event's own `commence_time`**. This is the repo's own recommendation-time
convention (`backfill.price_pair`, `pricepath.quote_at`), chosen because it is
a price the system could actually have acted on. Snapshots at or after
`commence_time` are dropped at read time, not filtered downstream
(`pricepath._build`). Nothing later than the decision instant may enter any
selection field.

The historical cadence is roughly three snapshots per day, so "latest at least
6 h out" is in practice a **median of 8.9 hours** before first pitch (§9). That
is recorded as `gap_minutes` on every selection and stratified in §6, not
silently averaged in.

**Consensus, and what it is not.** At the decision instant, take every book
quoting **both** sides of `h2h` whose pair admits a proportional two-way de-vig
(`src.core.odds.devig_two_way`, default method `proportional`, the system-wide
primitive M5/N12 confirmed). Require at least **6 such books**
(`src.evolab.baseline.MIN_BOOKS`). Then, verbatim from the repo's own
`src.evolab.feed.CONSENSUS_PRICE_DEFINITION`:

> home_price/away_price are the MEAN DECIMAL PAYOUT across exactly the books
> that entered the de-vigged consensus at the decision instant, converted back
> to American. A consensus is the board's opinion, not a price any book quoted:
> this number is the board's average price with the vig still in it, no book is
> named and no best price is picked, and **it is not a takeable price.**

The consensus home American price is **rounded half-up to the nearest integer**
before banding, so the bands are exact integer ranges with no boundary
ambiguity.

**De-vigged consensus probability** (the baseline the effect is measured
against) is the **mean across the same book set** of each book's proportionally
de-vigged home probability — `src.research.m5_devig.consensus(quotes,
"proportional")`. It is computed from the same books, at the same instant, as
the price that defined the band.

**Qualification.**

- Band A: rounded consensus home American price in `[100, 150]`.
- Band B: rounded consensus home American price in `[151, 250]`.

**Direction.** Back the **home** team on the moneyline. Fixed by the source
before any read. There is no second direction and no "fade" variant.

**Note on the word "underdog".** The rule qualifies on **price alone**, exactly
as the source states it; it does not additionally require the home de-vigged
probability to be below the away side's. A price of +100 with a sharp enough
away number can leave the home side nominally the favourite. That case is
reported as a pre-registered descriptive count (`home_fair >= away_fair`) and
**no selection is dropped for it** — dropping them would be a rule the source
never stated.

**One selection per event.** Doubleheaders are two events with two
`commence_time`s and resolve to two games by the repo's own ±3 h event-gap rule
(`pricepath.MAX_EVENT_GAP_SECONDS = 10800`). No event contributes twice.

## 4. Stake, outcome, test statistic, effect floor

- **Stake.** Flat **1 unit** per selection (`FLAT_1U`, the only staking the
  architecture permits; Kelly is registered disabled). No parlays, no
  correlation, no bankroll, no compounding.
- **Outcome.** `won = 1` if the home team won the game, else `0`, from the
  repo's own result store via `pricepath.read_results` — which already drops
  any game without a decided winner rather than defaulting it.
- **Per-selection statistic.** `diff = won − implied`, where `implied` is the
  de-vigged consensus home probability from §3. This is the repo's own
  `src.research.battery._prepared` row shape (`date`, `won`, `implied`).
- **Effect.** `mean(diff)` over the sub-hypothesis's selections in one season,
  reported in percentage points.
- **Effect floor.** **+1.00 percentage point** (`src.model.family.MIN_EFFECT =
  0.010`), over the de-vigged consensus. An effect below the floor does not
  pass, however significant.
- **ROI is reported, never promoted.** Flat-1u return at the consensus price is
  published as a secondary column with the standing caveat that the consensus
  price is not takeable. It is not the test statistic and cannot rescue a
  failed effect test.

### The floor is below breakeven, and the four breakeven figures are frozen here

**Amendment 1, computed from prices only, before any outcome was read.** The
+1.00 pp floor is measured against the **de-vigged** consensus. The vig at the
consensus price is larger than the floor in every cell, so a cell can clear
every gate in this document and still be a losing bet. The gap — mean raw
implied probability of the consensus home price (`odds.break_even_probability`)
minus mean de-vigged consensus home probability (§3), over that cell's own
selections — is pre-registered here:

| cell | mean raw implied at the consensus price | mean de-vigged consensus p | **breakeven gap** |
|---|---|---|---|
| Band A 2023 | .45510 | .43855 | **1.65 pp** |
| Band A 2024 | .45615 | .44058 | **1.56 pp** |
| Band B 2023 | .36215 | .34868 | **1.35 pp** |
| Band B 2024 | .37085 | .35780 | **1.31 pp** |

**Consequence, fixed in the verdict language (§10):** clearing the +1 pp floor
is a statement about **calibration** — the home side beat the de-vigged
consensus — and is **explicitly not a profitability finding**. Pre-registered
here, computed from the same prices: a home side beating the de-vigged consensus
by **exactly** the +1 pp floor, staked flat 1 u at the consensus price, returns

| cell | flat-1u return at a +1 pp edge | (at a zero edge, the pure vig drag) |
|---|---|---|
| Band A 2023 | **−1.43%** | −3.64% |
| Band A 2024 | **−1.20%** | −3.40% |
| Band B 2023 | **−0.94%** | −3.72% |
| Band B 2024 | **−0.81%** | −3.51% |

— a **loser in every cell**. No artifact may present a cleared floor as value,
profit, ROI or "good price".

**Direction of the untakeable-price caveat, stated so §4 is not ambiguous.**
The consensus is the **mean** decimal payout across the book set, not the best
of it. A line-shopper taking the best of the ~16 books quoting in 2023 (~11 in
2024) would get a **better** price than consensus, so the realised breakeven for
such a bettor is **lower** than the figures above. **Whether best-of-book
shopping closes the 1.31–1.65 pp gap is not measured by this design and may not
be assumed in either direction** — this run prices one number, the board's
average, and says nothing about the top of the board.

## 5. Interval, p-value, sample gate

**Amended by amendment 1 (§17), before any outcome was read.** The first frozen
version declared date clustering alone. That is the wrong dimension for this
family and the numbers in this document say so: mean selections per date are
3.12 / 2.97 / 1.34 / 1.31 (§10) and two different games on one night have
independent winners, so a date correction does almost nothing here — while the
correlation that actually threatens the standard error is **by home team**. A
team's season-long deviation from the market's consensus is persistent by
construction, so `won − implied` residuals correlate *within team across dates*,
not within slate. Band A averages **18.7 (2023) / 16.9 (2024) selections per
home team** and band B **8.4 / 7.9**, with 74.8% / 79.7% of band B on five teams
(§10). A date-clustered interval alone would be materially too narrow, and §12
forbids changing the key after a read — so it is changed now.

- **Two clusterings, both computed, both published.** The same two frozen
  functions are run twice per cell, once per cluster key:
  - **date** — the `date` field of the joined game in the results store;
  - **home team** — the joined game's home team, handed to the same functions
    in the same field (both `discovery.clustered_two_sided_p` and
    `discovery.clustered_bootstrap` group on `row["date"]` as an opaque,
    sortable cluster label, so this is the frozen estimator unmodified, fed a
    different label; no new statistical code is written for this run).
- **p:** `src.model.discovery.clustered_two_sided_p` under each key.
  **The decision p is `max(p_date, p_team)`** — the conservative envelope. It
  is a deterministic function of both numbers, so there is no choice left to
  make after they are seen.
- **95% interval:** `src.model.discovery.clustered_bootstrap` under each key —
  percentile bootstrap **resampling clusters, not selections**,
  `resamples = 2000`, `seed = 20260828` (`discovery.BOOTSTRAP_RESAMPLES`,
  `discovery.BOOTSTRAP_SEED`, both frozen defaults, restated here so the
  interval is reproducible from this file alone). Cluster keys are sorted
  before resampling, so each interval is a function of the data and not of row
  order. **The decision interval is the union of the two:**
  `[min(low_date, low_team), max(high_date, high_team)]`. Both raw intervals
  are published beside it.
- **Why the envelope rather than a two-way estimator.** A date-by-team two-way
  cluster-robust variance is the textbook answer and this repo does not have
  one. Writing new statistical code for a frozen pre-registration is the larger
  risk, and the envelope is conservative against either single dimension by
  construction. This is recorded as a declared approximation, not as the best
  possible estimator.
- **Stated limit on the team clustering itself.** Band B has only **17 (2023)
  and 15 (2024) distinct home teams**. Cluster-robust variance with that few
  clusters is itself approximate and biased downward even with the `g/(g−1)`
  correction the frozen function applies. That is one more reason this family
  is published as underpowered rather than as evidence, and it may not be
  presented as a precise interval.
- **Counting-proxy note.** The counts in §9 and §10 were produced before any
  result store existed for these seasons and used the proxy
  `(commence_time_utc − 8 h).date()` for dates and the odds store's home-team
  name for teams. Both are counting devices for this document only; the run's
  cluster keys come from the joined game.
- **Sample gate.** **30 qualifying selections per season per sub-hypothesis**
  (`src.research.battery.MIN_N = 30`, and N8's floor precedent). Below it, no
  effect, no p and no interval are computed for that cell; the verdict recorded
  is `below_floor` and the cell is published as underpowered, never as null.
  The `p = 1.0` / `effect = 0.0` such a cell hands to `family.apply_gates`
  (§6.6) is a **placeholder that keeps the family denominator at 2**, not a
  computed statistic, and is published as such.

## 6. Design: 2023 screen, 2024 replication

1. **2023 screen.** Compute, for band A and band B independently: the effect,
   and — under **both** cluster keys of §5 — the clustered p and the clustered
   95% CI, plus the decision p (`max(p_date, p_team)`) and the decision
   interval (the union).
2. **Sign gate.** A band whose 2023 effect is **negative** is dead on the spot.
   No 2024 look for it. (V4's pattern.)
3. **2024 replication.** For a band that survived (1) and (2), compute the same
   numbers, both clusterings included, on 2024.
4. **Sign agreement required.** Both seasons must be **positive**. A sign flip
   kills the band — the single most common death in this program.
5. **Both seasons must clear the +1pp floor**, separately. There is no pooled
   two-season number in the decision path; a pooled figure may be published as
   a descriptive footnote only, clearly labelled as such.
6. **FDR.** Benjamini–Hochberg at **q = 0.10** (`src.model.family.FDR_Q`) over
   the **full declared family of 2 sub-hypotheses**, applied with
   `family.apply_gates`, which requires FDR **and** the effect floor together.
   The whole family is published — both bands, survivor or not — because
   publishing only survivors is how a family of two becomes a claim about one.

   **The BH input, named exactly (amendment 1).** `family.apply_gates` consumes
   **one `p` and one `effect` per family member** (`family.benjamini_hochberg`
   sorts on `r["p"]`; there is no season dimension in it), and the first frozen
   version never said which p that is — a free parameter available after the
   numbers were seen. It is fixed here:

   - the `p` handed to `apply_gates` for each band is that band's **2023 screen
     decision p** (§5's envelope, `max(p_date, p_team)`);
   - the `effect` handed to `apply_gates` is that band's **2023 effect**;
   - **2024 is not a second p.** It is the independent replication gate of
     §6.3–6.5 — sign agreement and the +1 pp floor — and enters the decision
     only there. Its p and interval are published, and are never BH-corrected
     into this family;
   - therefore the **family size is 2, not 4**, and the BH threshold ladder is
     `q·1/2` and `q·2/2`.

   **The denominator is 2 whatever happens.** A band that dies at the 2023 sign
   gate still counts. A cell below the 30-selection gate (§5) has no effect, no
   p and no interval, so — to keep it from either raising `KeyError` on
   `r["p"]` or silently shrinking the denominator to 1 — it enters
   `apply_gates` as **`p = 1.0`, `effect = 0.0`**, which cannot survive either
   gate, and is reported as `below_floor`, never as a test that was run.
7. **What replication can and cannot prove here (amendment 1).** The 2024
   replication runs on a **different measuring apparatus** than the 2023 screen,
   in two ways at once:
   - **snapshot cadence** — 2023 stores 600 lines covering **572 distinct
     snapshot instants across 193 days** (3 instants on 187 of those days, 1–2
     on five, 4 on one, and 28 stored lines repeating a stamp already stored);
     2024 stores 600 lines covering **600 distinct instants across 200 days, a
     flat 3 per day with no repeats**;
   - **book depth at the decision instant** — band A averages **16.4 books in
     2023 and 11.2 in 2024** (§9); the market consolidated between the seasons.

   A sign flip between seasons is therefore **partly uninformative about the
   hypothesis**: it can be an apparatus difference rather than an absent effect.
   This does not relax the kill — a flip still kills the band under §6.4 — but
   it bounds what the kill may be *said* to prove, and the published result must
   carry this paragraph.
8. **Report-only stratifications**, declared now so they cannot be mined later.
   Each is published with its numbers and is **incapable of producing a
   candidate, a promotion, a verdict change or a customer claim**:
   - `gap_minutes ≤ 720` vs `> 720` (price staleness at the decision instant);
   - per-season book-count regime (2023 ≈ 16 books, 2024 ≈ 11 — the market
     consolidated between the two seasons, §9).

   The divisional split is **not** on this list any more: under amendment 1 it
   is not computed at all in this run (§7).

## 7. The divisional restriction (SR2) — declared, and not computed

SR2 is **not** registered as a family member, and **under amendment 1 it is not
computed in this run at all.**

Two reasons, both recorded before any read:

1. **Its own draft states no mechanism** for why divisional games should differ
   from the general home-dog effect. R9's standing rule applies.
2. **Division membership for 2023–24 is not on disk.** The only standings
   snapshot present (`data/historical/standings.jsonl`) is **2026 only** (30
   rows). Assigning 2023–24 divisions from it requires the assumption that MLB
   alignment was unchanged 2023→2026 (it was, and the 2025 OAK→ATH rename is
   handled by mapping both spellings to the same division) — but that is an
   assumption, not a point-in-time fact this repo holds, and nothing promotable
   may rest on one.

**A third reason was given in the first frozen version and is withdrawn as a
bad reason (amendment 1).** It read: *"Denominator inflation. Adding it would
take the family from 2 tests to 4, raising the BH bar on the only two cells
with any power at all."* Declining a test because correcting for it would make
the other tests harder to pass is the forking path stated out loud. It is
struck. Reasons 1 and 2 carry the decision on their own.

**And the report-only stratum is withdrawn too.** The first version froze the
divisional slice as a report-only number published alongside the family. A
report-only number that "worked" is exactly how the path re-opens — it cannot
be un-seen, and its existence invites a later re-reading. Since the slice can
never be promoted and rests on a 2026-standings assumption, **the divisional
effect is not computed, not published and not looked at in this run.** The
registration-time *counts* in §9 and §10 stay on the record as what was known
before the read, labelled as counts only; no `diff` is ever computed for them.

**Any later interest in the divisional slice is a new pre-registration on a new
window, with point-in-time division membership actually on disk, never a
re-reading of this one.**

## 8. Falsification battery

Every band that survives §6 goes through `src.research.battery.run` at
`RULES_VERSION 2.0.0`, fingerprint `ac74c7a7f715f9ec` (the same frozen battery
V4 and V5 were killed by), `effect_floor = 0.01`. Fatal checks, with the rules
as the module already enforces them:

| check | rule | note for this family |
|---|---|---|
| `season_split` | both seasons must hold the effect | overlaps §6.4; both are applied |
| `team_concentration` | leave out each of the **top 5 home teams by selection count**; FATAL if dropping one leaves `p > 0.10` **and** (effect below floor, or — for a full slice significant at 0.05 — effect below 0.75× the full effect) | **stated in advance: band B is 74.8% (2023) and 79.7% (2024) top-5 concentrated (§10). A team-concentration kill on band B is the expected outcome, not a post-hoc excuse.** |
| `book_concentration` | same leave-one-out over books | the 2023→2024 book-count drop from ~16 to ~11 is the regime this check reads against |
| `extreme_removal` | drop the most extreme 5% of dates | |
| `dose_response` | **NOT APPLICABLE and marked so, not force-fit** | band A claims a flat band with no gradient inside it. Band B likewise. The *two bands together* are not a declared dose ladder: they are two independent tests, and "the effect is bigger in B than A" is not a pre-registered prediction and may not be reported as dose-response evidence. |

A band that clears FDR and the floor but dies in the battery is
`TESTED_FALSE_POSITIVE`, published with the exact failing check and the
leave-one-out table — the F1/F2 precedent.

**The battery's own p stays date-clustered, and that is recorded rather than
changed (amendment 1).** `battery._prepared` computes its internal p with
`discovery.clustered_two_sided_p` on the game date (line 171), and the battery
is frozen at `RULES_VERSION 2.0.0` / fingerprint `ac74c7a7f715f9ec` — the value
this registration and the V4/V5 rows all carry. Editing it would break that
fingerprint and with it the comparability those rows depend on. So the
`LOO_P_CEILING` rule inside the battery reads a **date-clustered** p while §5's
decision numbers read the envelope, and the battery's leave-one-out p is
therefore the **narrower**, less conservative of the two. Two consequences,
stated in advance: the battery is a **kill mechanism only** and can never
promote anything, so a too-narrow p there makes it *easier*, not harder, to
kill a band; and the team dimension is already attacked directly by
`team_concentration`, which drops each of the top five home teams in turn.

## 9. Candidates on disk, counted before any outcome was read

Counted from the odds archive alone, using the §3 rule exactly as written.

**Reconciliation (all events, per season).**

| | 2023 | 2024 |
|---|---|---|
| snapshot lines stored (**a fetch cap, not a coverage fact** — see below) | 600 | 600 |
| distinct snapshot instants inside those lines | 572 | 600 |
| events seen (≥ 1 snapshot strictly before first pitch) | 2,475 | 2,472 |
| quote-rows dropped for being at/after first pitch | 1,792 | 1,699 |
| events with **no snapshot ≥ 6 h out** → excluded | 204 | 144 |
| events with **< 6 books** at the decision instant → excluded | 73 | 134 |
| **events priced (eligible universe)** | **2,198** | **2,194** |
| mean / median books at the decision instant, **over every event that has one** (i.e. before the 6-book filter) | 16.0 / 17 | 10.7 / 11 |
| events that have a decision instant at all | 2,271 | 2,328 |
| odds event dates present | 186 | 191 |
| dates inside the season span with **no odds event at all** | 6 | 11 |
| **priced** events after the regular season ends (kept, §3) | 12 | 15 |
| priced events before Opening Day | 0 | 0 |
| team names the odds store itself could not spell out | 0 | 0 |

**Both files hold exactly 600 lines. That is the historical-fetch quota, not a
statement about the market (amendment 1).** 2023 spreads 600 stored lines over
572 distinct snapshot instants across 193 days (28 lines repeat a stamp); 2024
spends 600 lines on 600 instants across 200 days, a flat 3 per day. Every downstream "hole" in this table is
therefore at least partly an artifact of that cap: the **204 / 144** events with
no snapshot ≥ 6 h out, and the **6 / 11** dates with no odds event at all, are
what a capped 600-snapshot fetch missed, not what the board declined to price.
§11's hole table carries the upstream cause on its own row.

**The last row means only what it says (amendment 1).** In the first frozen
version it was headed "team names the join could not resolve | 0 | 0", which
reads as a clean odds-to-StatsAPI join. It is not one: there is **no 2023–24
results store to join against** (§11), so the figure counts only odds-store team
names that could not be normalised. The join itself is **completely untested**,
and amendment 1 adds an outcome-blind audit of it below.

**Qualifying selections.**

| cell | 2023 n | 2023 dates | 2023 home teams | 2024 n | 2024 dates | 2024 home teams | mean de-vigged home p |
|---|---|---|---|---|---|---|---|
| **Band A** (+100..+150) | **543** | 174 | 29 | **507** | 171 | 30 | .4386 / .4406 |
| **Band B** (+151..+250) | **143** | 107 | 17 | **118** | 90 | 15 | .3487 / .3578 |
| Band A, divisional *(counts only — never computed after the read, §7)* | 185 | 122 | — | 164 | 108 | — | .4374 / .4351 |
| Band B, divisional *(counts only — never computed after the read, §7)* | 52 | 48 | — | 42 | 39 | — | .3436 / .3583 |

Both family cells clear the 30-selection gate in both seasons by a wide margin,
so the gate is not expected to bind. `gap_minutes` at the decision instant:
band A 2023 min 379, p25 414, median 534, p75 1,044, max 1,284; band A 2024 min
360, median 535, max 2,723. Consensus price range actually observed: band A
+100..+150 (median +119 / +117), band B +151..+241 (2023) and +151..+240
(2024), median +172 / +165.5. Books at the decision instant **inside band A**:
mean 16.4 (2023) and 11.2 (2024) — the apparatus difference §6.7 names.
`home_fair ≥ away_fair` (the §3 "nominally not a dog" descriptive count): **0**
in all four cells.

Selections are spread across every month of both seasons (band A: 68–106 per
month in 2023, 68–90 in 2024), so no cell is a single hot stretch. Exactly one
in-band selection is a postseason game (band A, 2024); it is kept (§3).

**Who produced these counts, and what must happen to them (amendment 1).**
`pricepath._build` cannot produce them: it calls `read_results()` and joins
every event to a played game before it emits a path, and there is no 2023–24
result store (§11), so every event would come back `unjoined`. These counts
therefore come from a **reader that reuses the repo's own primitives in the
same order** — `backfill.read_season` for the archive, the same
`snapshot_at >= commence_time` drop, `pricepath.quote_at(path, 360)` for the
decision instant, `odds.devig_two_way(..., "proportional")` for book
eligibility, `evolab.feed`'s mean-decimal-payout consensus recipe for the price,
and `m5_devig.consensus` for the de-vigged probability — with only the results
join absent, because it cannot exist yet. **A second, independently written
recount reproduced every figure in this section exactly** — 543 / 507 / 143 /
118 selections, 174 / 171 / 107 / 90 dates, mean de-vigged p at every published
decimal, 2,475 / 2,472 events seen, 1,792 / 1,699 quote-rows dropped after first
pitch, 204 / 144 and 73 / 134 exclusions, 2,198 / 2,194 priced, 16.00 / 10.68
mean books, 186 / 191 odds event dates, 6 / 11 empty dates in span, and top-5
home-team concentration 74.8% / 79.7%.
They are still **not the numbers the run will produce**: once the backfill
lands, the selection set must be re-derived through `pricepath` itself, and
**any delta against this table is published, never silently adopted.**

**Outcome-blind join audit, declared now and required before the read.** The
odds-to-StatsAPI join is completely untested on these seasons, and §12 spends
the single permitted read of 2023 on it. So, after the §11 backfill and before
any `diff` is computed: match every priced event to a game on **date and team
names only**, count and publish `unjoined` and `undecided` per band per season,
and compare them to the 10% kill line. **The winner column is not read, and no
`won` value enters the audit.** This audit does **not** consume the one
permitted read of either season; it reads the join, not the outcome. If it
fails the 10% line, the affected cell is `COVERAGE_COMPROMISED` before any
effect is ever computed.

## 10. Power, computed honestly, before any outcome was read

Method, stated so it can be checked: under the null the per-selection variance
of `won − implied` is `p(1−p)` with `p` the de-vigged consensus probability
(taken from the prices in §9, not from any result); using `p̄(1−p̄)` rather than
mean `p(1−p)` is conservative by Jensen, which is the right direction. The
clustered design effect is `1 + (k̄ − 1)ρ` with `k̄` the mean selections per
cluster and `ρ` the within-cluster outcome correlation.

**The table below is the DATE axis**, kept as first frozen. **ρ = 0 is the
honest baseline on this axis** — two different games on one night have
independent winners — and ρ = 0.05 is carried as a conservative bound.

| cell | n | k̄ date | SE | 95% CI half-width | MDE at 80% power | n needed for +1pp at 80% |
|---|---|---|---|---|---|---|
| Band A 2023 | 543 | 3.12 | 2.13 pp | 4.17 pp | **5.97 pp** | **19,332** |
| Band A 2024 | 507 | 2.97 | 2.21 pp | 4.32 pp | **6.18 pp** | **19,351** |
| Band B 2023 | 143 | 1.34 | 3.99 pp | 7.81 pp | **11.17 pp** | **17,831** |
| Band B 2024 | 118 | 1.31 | 4.41 pp | 8.65 pp | **12.37 pp** | **18,041** |
| Band A divisional 2023 *(counts only, §7)* | 185 | 1.52 | 3.65 pp | 7.15 pp | 10.22 pp | 19,321 |
| Band B divisional 2024 *(counts only, §7)* | 42 | 1.08 | 7.40 pp | 14.50 pp | 20.73 pp | 18,052 |

At ρ = 0.05 the band A numbers worsen to 6.28 pp / 6.47 pp MDE; nothing about
the conclusion changes. (An independent recomputation reproduces every SE, CI
half-width and MDE for the **four family cells** to within ±0.01 pp, and every
"n needed" to within 10 selections; the two divisional rows were not
recomputed, and under §7 they are never used for anything.)

### The same table on the HOME-TEAM axis, which is the binding one

**Amendment 1.** §5 now makes the home team a cluster key, because that is where
the correlation is. The date axis above is near-trivial — k̄ of 1.3–3.1 at
ρ ≈ 0 — while **band A averages 18.7 (2023) and 16.9 (2024) selections per home
team, and band B 8.4 and 7.9**, over 29 / 30 and 17 / 15 distinct home teams.
There is no honest ρ = 0 baseline on this axis: a team's season-long deviation
from the consensus is persistent by construction, so ρ_team = 0.05 and 0.10 are
both carried, and neither is a worst case.

| cell | n | teams | k̄ team | ρ | DEFF | SE | 95% CI half-width | MDE at 80% | n for +1pp |
|---|---|---|---|---|---|---|---|---|---|
| Band A 2023 | 543 | 29 | 18.72 | 0.05 | 1.89 | 2.92 pp | 5.73 pp | **8.19 pp** | 36,453 |
| Band A 2023 | 543 | 29 | 18.72 | 0.10 | 2.77 | 3.55 pp | 6.95 pp | **9.93 pp** | 53,579 |
| Band A 2024 | 507 | 30 | 16.90 | 0.05 | 1.80 | 2.95 pp | 5.79 pp | **8.28 pp** | 34,724 |
| Band A 2024 | 507 | 30 | 16.90 | 0.10 | 2.59 | 3.55 pp | 6.95 pp | **9.94 pp** | 50,104 |
| Band B 2023 | 143 | 17 | 8.41 | 0.05 | 1.37 | 4.67 pp | 9.14 pp | **13.07 pp** | 24,431 |
| Band B 2023 | 143 | 17 | 8.41 | 0.10 | 1.74 | 5.26 pp | 10.31 pp | **14.73 pp** | 31,037 |
| Band B 2024 | 118 | 15 | 7.87 | 0.05 | 1.34 | 5.11 pp | 10.02 pp | **14.33 pp** | 24,227 |
| Band B 2024 | 118 | 15 | 7.87 | 0.10 | 1.69 | 5.73 pp | 11.23 pp | **16.06 pp** | 30,419 |

SE inflation against the ρ = 0 date row, at ρ_team = 0.05 / 0.10: band A
**×1.37 / ×1.66** (2023) and **×1.34 / ×1.61** (2024); band B **×1.17 / ×1.32**
(2023) and **×1.16 / ×1.30** (2024).

**And team clusters are very unequal**, which the `k̄` form understates. Using
the variance-weighted cluster size `m̃ = Σk²/n` (26.1 / 26.5 in band A, 21.0 /
18.6 in band B — band B's five-team concentration shows up here) the MDEs at
ρ_team = 0.10 become **11.18 / 11.64 pp** (band A) and **19.32 / 20.56 pp**
(band B). Those are recorded as the conservative end of the declared range.

**What this does to §10's conclusion: it makes it worse, not better.** The
first frozen version's "the sample cannot see +1 pp" finding was computed on the
axis where the correction does nothing. On the axis that binds, band A's real
detection floor is **8–11 pp**, not 6 pp, and band B's is **13–21 pp**, not
11–12 pp. Every ruling-out claim in this section must be read against those
numbers.

### The finding, stated plainly

**No. The sample cannot see a +1 percentage point effect. It is not close.**

On the **date** axis at ρ = 0 — the most favourable reading available — band A
would need roughly **19,300 selections per season** to detect its own declared
+1 pp floor at 80% power, and has **543** and **507**: short by a factor of
about **36**, about **37 MLB seasons** of qualifying home underdogs at this
band. Even the weaker criterion "the 95% interval excludes zero", which is only
~50% power, needs about 9,460 selections — still 17 seasons. Band B needs
~18,000 per season and has 143 and 118 — short by a factor of about **140**.

**On the home-team axis, which is the one that binds (amendment 1), it is worse
again:** at ρ_team = 0.05 / 0.10 band A needs **34,700–53,600** per season
(short by a factor of **67–99**) and band B **24,200–31,000** (short by
**171–258**). Whichever axis is read, the answer is the same and the amendment
only deepens it.

The declared design compounds this: §6 requires **both** seasons to clear the
floor **and** agree in sign **and** survive BH at q = 0.10 over two tests. A
true +1 pp effect would clear all of that by chance at a rate barely above the
false-positive rate itself. **This design has essentially no ability to confirm
the hypothesis as drafted.**

### What the run can still do, declared now

1. **Rule out large effects — by the interval's upper bound, never by the
   MDE (corrected, amendment 1).** If the 2023 decision interval for band A
   comes back −2 pp..+2 pp, what is ruled out at 95% confidence is **anything
   above +2 pp** — the upper bound of that interval — not "+6 pp or more". The
   first frozen version said +6 pp, reading the ruling-out threshold off the
   MDE; that is wrong and it is struck. **The MDE answers a different question:
   how large an effect this sample would usually *detect* (80% of the time),
   not what the realised data excludes.** The two coincide only by accident.
   The forum claim that home dogs at +100..+150 are a *system* implies an
   effect far larger than the vig, and if the realised interval is tight enough
   its upper bound will exclude that; whether it does is a fact about the
   realised interval and cannot be promised here.
2. **Kill it on sign.** A negative point estimate in 2023 kills the band under
   §6.2 regardless of power, and a negative estimate is a perfectly informative
   outcome.
3. **Produce the honest customer answer the lane exists for** — "we tested the
   home-dog system on our own frozen machinery, here is exactly what happened,
   and here is exactly what our sample was and was not able to see."
   **Labelled, always, as a discovery-window diagnostic (amendment 1):** 2023
   and 2024 are discovery data, which the standing rule says is diagnostic and
   never a customer claim. This statement is admissible only because it is a
   *ruling-out* statement about what was measured, carrying the mandatory
   sentence below — it is never a promotion, never a performance claim, and the
   words "worth forward-testing" are the ceiling on it (§12).

### What the run may never say

**A null from this family is `UNDERPOWERED_NULL`, never "there is no effect".**
The published verdict language is fixed here, in advance, **keyed to the
realised interval rather than to the MDE (amendment 1)**:

> Over N selections the home side beat the de-vigged consensus by X pp (95% CI
> a..b, the wider of the date-clustered and team-clustered intervals). **Effects
> above [b] pp are ruled out at 95% confidence; this sample reaches 80% power
> only at [MDE] pp, so it cannot distinguish a +1 pp effect from zero.** This is
> a statement about calibration, not about profit: breakeven at the consensus
> price in this cell is [gap] pp above the de-vigged consensus (§4), so an
> effect below that is a losing bet even if it is real. Nothing here says the
> mechanism is absent at sizes this sample cannot see.

Every bracket is filled from the realised numbers. **The upper bound `b` is the
only ruling-out number; the MDE may never be used as one.** No marketing
artifact, landing page, card, or customer-facing claim may quote a number from
this family without the two bolded sentences and the breakeven sentence
attached.

## 11. Coverage-hole policy — decided now, not after seeing the holes

**Blocking hole, found during this registration and recorded here rather than
discovered mid-run.** `data/historical/mlb_results.csv` currently holds
**4,586 games spanning 2025-03-27..2026-09-10 only** (2025: 2,428; 2026:
2,158), and its manifest's earliest date is 2025-03-20. **There are no 2023 or
2024 game results on disk anywhere under `data/`.** `docs/DEBRIEF.md` line 140
still describes this store as "9,319 games, span 2023-03-01..2026-08-30"; that
figure is **stale** relative to the file as it stands on 2026-09-16.

Consequence, decided now:

- **The 2023 screen may not run until the 2023–24 results backfill exists.**
  It must be produced with the repo's own `src.pipeline.history.ingest_range`
  against the free MLB StatsAPI (no odds credits, no paid call), covering at
  minimum 2023-03-30..2023-10-07 and 2024-03-20..2024-10-07, and its per-date
  manifest must be published with the result.
- The backfill is a **results** fetch only. It reads no price and changes no
  price. It does not constitute a look at outcomes for this hypothesis: the
  look happens when a `diff` is computed, and that happens once, after the
  backfill is complete and reconciled.

**Standing rules for every other hole, fixed now:**

| hole | policy |
|---|---|
| **Upstream cause of the two rows below: the archive is a capped quota sample** — exactly 600 stored snapshot lines per season (572 distinct instants in 2023, 600 in 2024), because that is what the historical fetch bought, not what the market published (amendment 1). | **Named on every artifact that quotes a coverage number from this family.** No imputation and no reweighting to "what a full fetch would have seen": the sample is what it is. |
| Event with no snapshot ≥ 6 h before first pitch | **Not a selection.** Counted and published (`no_recommendation_snapshot`: 204 / 144) — **an artifact of the fetch cap, not of the board.** |
| Fewer than 6 books with a valid two-way de-vig at the decision instant | **Not a selection.** Counted and published (`below_min_books`: 73 / 134). |
| Qualifying event that will not join a played game within ±3 h (`pricepath.MAX_EVENT_GAP_SECONDS`) | **Not a selection.** Counted and published as `unjoined`. Never matched to the nearest-looking game. |
| Joined game with no decided winner (postponed, suspended, tied) | **Not a selection.** Counted and published as `undecided`. Never defaulted to 0 or 1. |
| Calendar date inside the season span with no odds event at all | Published as an odds coverage hole (6 dates in 2023, 11 in 2024) — **also downstream of the fetch cap.** **No imputation, no reweighting, no interpolation.** |
| Missing de-vigged consensus for a book pair | That book is excluded from the consensus; if fewer than 6 remain the event is excluded as above. |

**Reconciliation is mandatory and additive.** The published result must contain,
per band per season, a table in which `events_priced = qualifying +
out_of_band` and `qualifying = selections + unjoined + undecided`, adding
exactly. A run whose reconciliation does not add is void.

**Join-loss kill line, set now:** if `unjoined + undecided` exceeds **10% of
qualifying selections** in either band in either season, that season's cell is
published as `COVERAGE_COMPROMISED` and **no verdict is drawn for it**. The
line is 10% and may not be moved after the counts are seen. **It is measured by
the outcome-blind join audit declared in §9, before any `diff` exists**, so a
coverage kill never costs a read.

## 12. Stopping rule

- **One read of 2023. One read of 2024**, and 2024 only for a band that
  survived §6.2. There is no second pass, no re-run "with a fix", and no
  exploratory look first. A bug found after a read is disclosed with the read
  it affected; it does not buy a fresh read. The §9 join audit is **not** a
  read: it never touches the winner column.
- **Stopping is per band, not per family (amendment 1).** The first frozen
  version said "the run stops permanently" without saying whether one band's
  death stops the other, which §6.2 only implied. It is fixed here: **bands A
  and B stop independently.** A band A death at the 2023 sign gate does not stop
  band B's 2024 look, and vice versa. Both bands are published either way, and
  the BH denominator stays 2 (§6.6) however many bands survive to a second
  season. The only family-wide stop is a **void** run under the last bullet of
  §16 — a rule change after a read voids everything.
- **No re-cut of anything** after any read: not the bands, not the 6-hour lead,
  not the 6-book floor, not the de-vig method, not the cluster key, not the
  bootstrap seed, not the effect floor, not q. T8, absolute.
- **A band stops permanently** at the first of: sample gate failed
  (`below_floor`), negative 2023 sign, 2024 sign flip, FDR failure, any fatal
  battery check, or a `COVERAGE_COMPROMISED` cell **for that band**. Its
  remaining steps are not run and its row is published with the reason.
- **Exactly one verdict row** per registered id, via
  `alpha_registry.record_verdict`. A later correction to the numbers is a new
  id (`…-correction-<date>`), never a rewrite.
- **Losers are published in full**, with n, effect, CI, p, ROI, the battery
  table and the reconciliation — the same detail a survivor would get.
- **2025 is not read by this family, ever.** The sealed window
  2026-01-01..2026-08-27 is not read by this family, ever. Forward evidence
  from 2026-08-28 onward is a separate registration on a separate window, not a
  continuation of this one.
- **A survivor is not a product, and may still be a losing bet (amendment 1).**
  Clearing §6 and §8 licenses the phrase "worth forward-testing" and nothing
  else — and when the realised effect is **below that cell's breakeven gap**
  (§4: 1.65 / 1.56 / 1.35 / 1.31 pp), the phrase may be used only with the
  sentence *"at the consensus price this is still a losing bet; what cleared is
  a calibration floor, not a profit"* attached. Promotion requires G0–G7
  (`docs/ARCHITECTURE_BETTING_ENGINE.md` §5), including ≥300 forward
  selections and owner sign-off.

## 13. Alpha declared, and what it spends

`alpha_declared = 0.10` — the **family BH-FDR q**, the same convention V1, V2,
V3, V4 and V5 rows carry, over a declared family of **2** sub-hypotheses
(bands A and B). It is a new family (`SR`), not a draw on any existing family's
budget: no prior registered hypothesis has bet on a price-band-conditioned home
side, and the semantic hash below collides with nothing on the ledger.

Search already spent before this row, per `alpha_registry.total_searched()`
(D4's required citation):

- **Overall:** 46 hypotheses, 1 sweep (8,811 internal candidates), 1 audit; 38
  read, 10 not read.
- **MLB `h2h`:** 28 hypotheses, 1 sweep, 1 audit.
- **On the 2023 discovery window:** 9 hypotheses. **On 2024:** 9 hypotheses and
  1 audit.

This registration adds **one row carrying two declared sub-hypotheses**. The
one-row form was a constraint on the writing session, not a statement that this
is one test: the row records `candidates_evaluated: 2` and says so in its
`note`. **`total_searched()` will count this as 1 hypothesis while the true
multiplicity is 2** — flagged here and on the row so the ledger is not read
wrongly. The honest long-term form is one row per band, and any future
re-registration of this family should take it.

**What amendment 1 adds to the ledger, and what it does not (amendment 1).**
Re-freezing this document changes its sha256, which makes the freeze hash on the
original row stale, so a second row is appended. The ledger is append-only and
`register()` refuses a duplicate id, so the amendment is a **new id**:
`SR:home_underdog_price_band:h2h:amendment-1-2026-09-16`, `kind: "audit"`,
`alpha_declared: 0.0`. Three consequences, stated so nobody reads the ledger
wrongly:

- **It registers no new search and spends no alpha.** The family's alpha is
  declared once, on the parent row, and is unchanged at q = 0.10 over 2
  sub-hypotheses. No new hypothesis, band, direction or window is created.
- **It is `audit`, not `hypothesis`, on purpose.** `public_research_counts()`
  counts only `kind == "hypothesis"`, so the customer-facing "hypotheses
  pre-registered" figure stays at 47 — the honest number, because the count of
  ideas searched did not change. A `hypothesis` row would have inflated it.
- **It does move two counters.** `total_searched()` reads `audits` 1 → 2 and
  `not_read` +1 (an amendment carries no verdict and never will). Any future
  citation of those numbers must subtract this row, exactly as this section
  does.

The original row stays on the ledger forever, unedited, and is superseded — not
replaced — by the amendment.

## 14. The registered row

```
family     SR
id         SR:home_underdog_price_band:h2h
spec_id    home_underdog_price_band
market     h2h
sport      mlb
data_window  {"discovery": "2023", "replication": "2024", "sealed_untouched": true}
direction  back the home moneyline when the de-vigged-consensus-eligible book set's
           mean decimal payout on the home side, converted to American and rounded,
           falls in +100..+150 (band A) or +151..+250 (band B) at the latest
           snapshot at least 360 minutes before first pitch
alpha_declared     0.10   (family BH-FDR q over 2 declared sub-hypotheses)
feature_expr_hash  26e0b634b5920c04e7a3e1638ee6f03840bef4f5e427c0e266ee16c3134fade6
code_hash          ac74c7a7f715f9ec   (battery RULES_VERSION 2.0.0 fingerprint,
                                      same value V4/V5 rows carry)
source_doc         docs/PREREG_SR1_HOME_UNDERDOG.md
candidates_evaluated  2
```

Semantic hash atoms (v0, identity grid `(150.0, 250.0)`):

```
("home_consensus_american_price_100_to_150", "in_band_inclusive", "h2h", "back_home", 150.0)
("home_consensus_american_price_151_to_250", "in_band_inclusive", "h2h", "back_home", 250.0)
```

**The selection rule is unchanged by amendment 1**, so `feature_expr_hash`,
the semantic atoms, the bands, the direction, the lead time, the book floor,
the de-vig method, the effect floor and q are all **identical** to the original
row. The amendment changes only how uncertainty is estimated (§5), which p
enters BH (§6.6), what the verdict may say (§4, §10), what is not computed
(§7), and what is disclosed (§9, §11). Nothing it changes can make a selection
qualify that did not qualify before.

## 15. Reproducibility anchors

| artifact | hash |
|---|---|
| `src/research/battery.py` | `cc4acf7cd4175c93b718d572ab45c2733c6bb9c3` |
| `src/model/discovery.py` | `a1c099a3c1f19ac68d99aa6eeb07e6bda82aef5c` |
| `src/model/family.py` | `15977e005f0a14467562677398c060099b0ce23a` |
| `src/research/pricepath.py` | `b0be396135ae1b755923150a703e86b20f9810c9` |
| `src/pipeline/backfill.py` | `ee470153064f9b86be9242986c789fe8a0a4d119` |
| `src/core/odds.py` | `0537a6a6cb872e4b94d550d2c1b43992c9b7c712` |
| `src/research/m5_devig.py` *(added by amendment 1)* | `2c09cea88d21ee6fd0226a3608976533d3119b9b` |
| `src/evolab/feed.py` *(added by amendment 1)* | `421e8224aa8a16a926b2b179a77a1384d2e3a42c` |
| `src/research/alpha_registry.py` *(added by amendment 1)* | `1105dad65f5ddf4b9809ba4384817c91d573243a` |

(git blob sha1, as `alpha_registry.git_blob_hash` computes them, at freeze time.)

**All six original anchors recompute to the same values at amendment 1**, so no
code changed between the two freezes: the amendment is a change to this
document and to the ledger, and to nothing that executes. The three added rows
are the modules the §9 counting reader and the freeze mechanism use, anchored
now because the first version referenced them without pinning them.

## 16. Kill criteria, restated as one list

Each applies **per band** (§12), and every band is published whatever happens
to the other.

1. Fewer than 30 selections in a cell → `below_floor`, no verdict, published as
   underpowered; the cell still enters BH as `p = 1.0`, `effect = 0.0` so the
   family denominator stays 2 (§6.6).
2. Negative 2023 effect → dead, no 2024 look for that band.
3. Sign flip 2023 → 2024 → dead.
4. Either season below the +1 pp floor → dead. (Clearing it is a calibration
   result, not a profit result — §4.)
5. Fails BH at q = 0.10 over the family of 2, on the **2023 decision p**
   (§6.6, the `max(p_date, p_team)` envelope of §5) → dead regardless of any
   single season's p.
6. Any fatal battery check → `TESTED_FALSE_POSITIVE`, published with the check.
7. Join loss above 10% in a cell, measured by the outcome-blind audit of §9 →
   `COVERAGE_COMPROMISED`, no verdict for it.
8. Any attempt to widen, narrow, merge, re-snapshot or re-book-floor after a
   read — or to change the cluster keys, the envelope rule, the BH input or the
   effect floor after a read — → the run is void and is published as void.

## 17. Amendment log

The ledger is append-only and so is this log. An amendment may only be made
**before** the data it governs has been read; an amendment after a read is a
new pre-registration on a new window, never a repair of this one.

**Amendment 1 — 2026-09-16, before any 2023 or 2024 outcome row was read.**
Prompted by an adversarial review of the first frozen version. Five corrections,
each a weakening or a disclosure, none a loosening of a gate:

| # | section | what changed |
|---|---|---|
| 1 | §2 | The claim of "independent internal corroboration" from V2's M5 / catalogue N12 is **withdrawn**: N12 is a **NULL**, and it measured the opposite of what was claimed. Prior stays MEDIUM-LOW but is recorded at the bottom of that band. |
| 2 | §4, §10, §12 | The four **breakeven gaps** (1.65 / 1.56 / 1.35 / 1.31 pp) are pre-registered, and the verdict language now states that clearing the +1 pp floor is calibration, not profitability. The direction of the untakeable-price caveat is stated. |
| 3 | §6.6, §12, §16 | The **BH input is named**: each band's 2023 decision p, family size 2, 2024 as the replication gate and never a second p; a `below_floor` cell enters as `p = 1.0`, `effect = 0.0`; stopping is **per band**. |
| 4 | §5, §8, §10 | **Home-team clustering** added as a decision-grade cluster key alongside date, with the decision p and interval taken as the conservative envelope; the power table is recomputed on the team axis, where the detection floor is 8–11 pp (band A) and 13–21 pp (band B). |
| 5 | §10 | The frozen verdict sentence is **keyed to the realised interval**: what is ruled out is everything above the upper 95% bound, not everything above the MDE. The same conflation is fixed in §10 item 1. |

Applied at the same time, from the same review, as disclosures rather than
design changes: the 600-line **fetch cap** and its downstream holes (§9, §11);
the 2023-vs-2024 **apparatus difference** in cadence and book depth and what it
does to replication (§6.7); the provenance of the §9 counts and the requirement
to re-derive through `pricepath` and publish any delta (§9); an **outcome-blind
join audit** that does not consume a read (§9, §11); **postseason and spring
training** settled explicitly (§3); the divisional slice **not computed at all**
and its "denominator inflation" justification struck as a forking path (§7);
§10 item 3 labelled a discovery-window diagnostic; the battery's internal
date-clustered p recorded as a known, deliberately unchanged limit (§8).

**Re-freeze.** This file's sha256 changed with these edits. The new hash is
carried on registry id `SR:home_underdog_price_band:h2h:amendment-1-2026-09-16`
(`kind: "audit"`, `alpha_declared: 0.0`, appended through
`alpha_registry.register()`); the original row
`SR:home_underdog_price_band:h2h` is unedited and still carries the v1 hash
`706cd09152514bde921e1ec699f50d2841ccfa044a851225b56c5a2e8fcfe164`, which is
now the hash of a **superseded** text. **The freeze check is: recompute this
file's sha256 and compare it to the amendment row's `note`.** If they disagree,
this document has been edited after registration and nothing computed from it is
admissible.

**Known defect outside this document, recorded because it will mislead
otherwise:** `docs/DEBRIEF.md` line 140 still describes the results store as
"9,319 games, span 2023-03-01..2026-08-30". The file on disk holds 4,586 games
spanning 2025-03-27..2026-09-10 (§11). That line is stale and belongs to no
file this registration may edit; it should be corrected before a future run
reads it as coverage.
