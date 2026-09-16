# Pre-registration: DAILY_CARD_BEST_BETS_V2

**Rule id:** `DAILY_CARD_BEST_BETS_V2`
**REGISTERED_UTC: <set at commit>**
**Family:** CARD_V2 (MLB daily card)
**Status:** DRAFT, not registered. Questions 3 and 4 are answered (Brey, 2026-09-15, section 15), and so is question 1. It becomes registered only when Brey has answered section 15 questions 5 to 8 himself (or explicitly accepted each default), dated, the frozen parameter file of 11.2 exists, the code the `code_fingerprint` of 11.2 covers is merged, and this file is committed with those answers, that file's sha256, the fingerprint value and the `v1_code_fingerprint` value of section 10; no V2 pick exists before that instant
**Succeeds on the customer card:** `DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1` and `DAILY_CARD_PROP_LIKELY_AND_CLEARS_PRICE_V1` (V1), which keep running in shadow with their record kept separately
**Diagnosis:** `docs/CARD_V2_DIAGNOSIS_2026-09-15.md` · **Build:** `docs/CARD_V2_BUILD_PLAN.md` · **Roadmap:** R16-34

The commit that sets `REGISTERED_UTC` is the registration instant. Every number
below is fixed at that instant. Changing any of them afterwards is a new rule
id with its own registration and its own window; it is never an edit to this
file. The only permitted later edits are listed in section 16.

---

## 0. What this registers, and what it does not claim

It registers a selection rule for the MLB daily card and a single forward read
of how that rule's picks do against the closing market and at the price.

The card lists three bets on a day whose board offers three that clear the
first checks (owner, 2026-09-15: "Always show 3"). On a day when fewer than
three pass every gate, the rest are **fills**: the closest calls, labelled on
their face as not picks, published and graded like picks and kept apart from
them on the record. On a day whose board offers fewer than three candidates at
all, the card lists fewer, down to none, and says why (section 6, copy C13).
The forward read this registers is of the picks only; the fills are reported
beside it and can never change it (sections 6, 11 and 12).

It claims no edge, no positive expected return and no guarantee. On the one
already-seen board used to design it (2026-09-15), the market's own number
cleared the best available price on **0 of 82 game-market sides** (30
moneyline, 26 run line, 26 totals) and on **0 of 56 props**, where the 56 were
only the side of each contract the market already makes likely (the board's
`most_likely` list, not both sides as section 2 defines props). That is one
board, not a law. It means that on that board every "Take" this rule could
publish rested on **our own number** clearing the price, and our number has
not been shown to beat the market's (`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`).
The customer copy says so on every pick (section 13).

## 1. Evidence rules this registration obeys, and where it does not yet

- **Data split**, verbatim from `docs/DEBRIEF.md:24-28`: "2023–24 discovery ·
  2025 tuning-only forever (its `2025-08-26..2025-09-28` sub-split is already
  burned by four looks) · **2026-01-01 → 2026-08-27 SEALED**, one evaluation
  ever, only after a policy freeze plus Brey's explicit go · 2026-08-28 onward
  is forward proof, never folded back into tuning." The model this draft was
  designed with does **not** meet that wording: it rests on numbers fitted on
  sealed-window games (section 1.1). Section 1.2 decides what V2 registers
  instead, and why. The rule's own gate constants were not
  fitted; each comes from the owner's words (2026-09-15), from an existing repo
  constant named beside it, or from one prior measurement cited beside it.
- **Verdict bar:** `docs/VALIDATION_CRITERIA.md`: closing-line value, meaning
  whether the prices taken were better than the market closed at, is the
  pass/fail metric; ROI is secondary; all five stop conditions apply; no
  verdict below 300 graded picks; a mid-sample model change restarts the
  sample. The one criterion not applied, and why, is in 11.3 (D6).
- **No rescue by threshold change.** A near miss at the read opens a new
  registration, never an adjustment here.
- **Every loser published.** Every pick ever shown as a pick is graded and
  stays on the record, locked or withdrawn (section 9), and so does every
  shadow pick and every fill (section 6).
- **Point in time.** A pick uses only quotes, lineups and model outputs that
  existed at the publish run that wrote it.

### 1.1 Fitted inputs and the sealed window

Every number in the model that was fitted or measured on game results, with
its window. Counted on 2026-09-15 on this machine's stores with each fit's own
row selection, by date only; no outcome field was read and nothing was re-fitted
or re-evaluated (`scratchpad/card_v2_revise/fit_window_counts.py`).

| Input | Used for | Fitted or measured on | Rows dated 2026-01-01 to 08-27 | Source |
|---|---|---|---|---|
| Card moneyline calibration (Platt `a`, `b`) | Our number on moneylines (G6 to G8) | Every completed 2026 game from 2026-04-15 through yesterday, refit every night by `scripts/fit_card_calibration.py` (`min_date` at `:56`) from `scripts/daily_loop.sh`. The committed file read: n 1,987, `b` 0.744719 through 09-13 (commit `6a568b83`); n 1,997, `b` 0.769145 through 09-14 (`7db02b0a`, the file section 14 used); n 1,911, `b` 0.735183 through 09-14 (`4359deda`, 21:04Z) | 1,753 of the 1,901 rows the fit selects on this machine's stores (92.2%; those stores reach 2026-09-10). The other 148 are dated 2026-08-28 onward, so the refit also folds forward games into fitting | `data/processed/card_calibration.json` |
| `DISPERSION = 2.3352` (`nb1`) | Spread of the run distribution: our number on moneylines and run lines | Fit 2026-04-15 to 2026-07-15 (1,186 games); held-out check 2026-07-16 onward (710 games) | All 1,186 fit games; most of the check window | `docs/PREREG_RUN_DISPERSION.md:131,213-216`; `src/analysis/strength.py:160,186` |
| `RHO = 0.05065` | Prop board, `batter_hits` only (`batter_total_bases` is not rho-corrected, `src/analysis/playerprops.py:657-658`) | Fit 2026-06-17 to 2026-08-05 (7,665 batter games); test 2026-08-06 onward (9,076) | All 7,665 fit batter games; part of the test window | `src/analysis/playerprops.py:522-548`; `scripts/test_prop_dispersion.py:83-85` |
| `SLOT_PLATE_APPEARANCES` | Prop board plate appearances by batting slot | 3,417 batter-games with a posted lineup and a box score (`scripts/probe_lineup_slot.py`); the window is not recorded beside the constant | Not known, not verified | `src/analysis/playerprops.py:115-148` |
| The two prop markets (`daily_card.PROP_MARKETS`) | Which props are candidates | A choice made from `scripts/backtest_player_props.py` over 16,741 2026 batter games; window not recorded | Not known; a choice of markets, not a number | `src/analysis/playerprops.py:200-240` |
| "0.0012 nats over 1,896 games" | The reason neither V1 nor V2 ranks by our number | Walk-forward evaluation over 2026-04-15 to 2026-09-06 | Most of it (an evaluation already run, quoted, not re-run) | `src/analysis/daily_card.py:43-50`, `docs/THE_CARD.md:197-199` |
| G8's 10-point cap | Disagreement cap | Props settled 2026-09-08 to 09-12 | None. Forward dates before registration, never counted (11.1) | `docs/PROP_CALIBRATION_2026-09-14.md:167,223-224` |

Not fitted, and listed so that "no fitted number" is never read as "no sealed
game": the run model's inputs at call time (each club's 2026 runs scored and
allowed, starter logs, relief rates, league runs per game, the FIP constant)
and the prop board's season rates are read point in time from 2026 stores that
include games dated 2026-01-01 to 08-27. They are inputs to a prediction about
a later game; no result chooses a parameter through them. The model's other
constants are published or fixed in advance (`strength.py:101-131`,
`playerprops.py:88-112`, `GAME_REGRESSION` at `:318`).

Our number drives G6, G7 and G8, so on the design board every V2 pick rested on
the first three rows of this table.

### 1.2 The decision on the sealed-window fits

**(a) Does it break the sealed rule as the repo words it?** The wording, besides
the split quoted above: "never touch sealed 2026 without explicit instruction"
(`docs/ROADMAP.md:31`); hard stop "(2) anything touching sealed
2026-01-01→08-27" (`docs/ROADMAP.md:50`); "not read, not summarised, not peeked
at for coverage counts" and "A refit is invalid if it (a) reads sealed data"
(`docs/PREREG_CALIBRATED_PROBABILITY.md:82-86`). The research code refuses the
window by name before any read (`src/evolab/replay.py:124-126`,
`src/research/f5_eligibility.py:63`); the card model's fit and backtest scripts
have no such guard.

Observed: every fit in the first three rows of 1.1 read games inside the
window, from 2026-09-10 onward, under V1. No document found records a policy
freeze or Brey's explicit go for any of them: neither `docs/THE_CARD.md` nor
`docs/PREREG_RUN_DISPERSION.md` mentions the seal (a search of `docs/` for
"sealed" matches neither). So, as worded, **the rule was already broken by V1**,
and V1's nightly refit broke it again every night until Brey stopped it on
2026-09-15 ("Freeze it now"; record
`docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`). That freeze changes nothing in
this registration: V2 reads no number from the nightly file under any answer
(11.2). The counts in 1.1 are
themselves a coverage count of sealed rows, made on the orchestrator's
instruction to establish this; they read dates only.

Interpretation, not a measurement:

1. A fit that is frozen before V2's first counted game does not contaminate
   V2's forward read. The counted games are played after the fit, so they are
   out of sample for it, whichever model V2 registers.
2. What the fits used up is the seal. The window's one evaluation exists to
   confirm a frozen policy on games nobody fitted or looked at. For any rule
   built on this run model, its calibration or the prop model, that can no
   longer happen: parameters were chosen on the window and the model was
   evaluated on it repeatedly (the 1,896-game walk-forward, the `DISPERSION`
   hold-out, the `RHO` test window). This is a finding about V1 as much as V2
   (diagnosis section 0).
3. Registering V2 on those fits adopts, in a new registration, inputs the
   repo's own refit rule calls invalid. Only Brey can authorise touching the
   seal, so doing it without his dated go would ratify V1's breach by default.

**(b) The honest options.**

- **O1. Fit once on 2025 only, freeze, then register.** 2025 is tuning-only,
  so fitting on it is permitted and no 2025 number is evidence. V2's model then
  reads no sealed and no forward game through any fitted number. Blockers,
  checked on 2026-09-15: the results store holds 2,186 2025 games that pass the
  calibration's row selection, but the pitcher-log store (8,298 appearances)
  and the bullpen log (18,365 rows) hold 2026 only, so 0 of those 2,186 rows
  have a starter FIP or a relief rate. A 2025 fit today would calibrate a
  team-rates-only model, not the model the card runs. It needs a backfill of
  2025 starter logs, relief appearances and box scores from the free MLB Stats
  API, into stores kept apart from the live 2026 stores:
  `pitchers.league_fip_constant` sums every appearance before its cutoff with
  no season filter, so 2025 rows in the shared store would change V1's live numbers. The
  existing 2025 dispersion estimate, 2.3265, came from
  `scripts/test_run_dispersion_2025.py` reading the same pitcher store, which
  holds no 2025 starts today, so it probably rests on the team-rates-only model
  too (not verified against the store as it was on 2026-09-10). A 2025 fit may
  also transfer to 2026 less well; FAIL conditions 2 and 3 (11.5) catch that,
  and it cannot be tuned afterwards.
- **O2. The market's number for G6 and G7; our number only a disclosed veto.**
  Our number could then only remove a pick. On the design board G7 on the
  market's number passes 0 of 82 game-market sides and 0 of 56 props, so the
  card would be empty almost every day, and anything that passed would pass
  because one book's price beat the consensus. That is line shopping, which
  the owner ruled out (2026-09-10, 2026-09-11) and the repo calls price
  improvement, never value (`docs/DEBRIEF.md` hard rules). A veto still lets
  the sealed-window fit choose which picks exist.
- **O3. Keep the two fits made only on sealed-window games, `DISPERSION` and
  `RHO`, frozen at registration, and label the evaluation "not independent of
  the sealed window".** V2's forward read stays valid; the record says
  permanently that V2 and this model can never be confirmed on the sealed
  window. It needs Brey's explicit, dated go. Even then three numbers are not
  kept. The moneyline calibration read forward games when it was fitted (148
  of the 1,901 rows in 1.1), which the next bullet rules out under any answer,
  and the slot table's window is not recorded, so it cannot be shown to
  exclude them. No side-level run-line calibration exists, and fitting one on 2026
  games would be a new sealed read. All three are fitted once on 2025 after
  O1's backfill, with the kept `DISPERSION` as a model input, and registration
  waits for that as under O1.
- A fit on forward games from 2026-08-28 is not an option: the split says
  forward proof is "never folded back into tuning", and Brey's go covers only
  the sealed window. That rules out keeping the nightly moneyline calibration
  under any answer, O3 included.

**(c) What this registration adopts.** O1, **answered by Brey on 2026-09-15**
("Rebuild on 2025", question 3 answered no; section 15). It is the only option
that restores the evidence standard without needing
Brey to authorise use of the sealed window and without emptying the card; its
cost is
free data work (build plan T0a), not a relaxed rule. If T0a cannot build the
2025 inputs, V2 is not registered until Brey decides; nothing falls back to
2026 games. O2 is not adopted because it contradicts the owner's line-shopping
ruling and still selects through the fit. O3 is not adopted: the choice was
genuinely Brey's, because only he can authorise use of the sealed window, and
he did not authorise it. No sealed-window fit is carried into V2, so no
published read of V2 carries the "not independent of the sealed window" label.
Two dependences remain and are
disclosed, not removed: the choice of the two prop markets was made on 2026
games, and the model's unfitted inputs read 2026 stores point in time.

---

## 2. Candidate set

A candidate is one side of one bet on one MLB game on the slate date
(America/New_York calendar date, the `SLATE_DATE` used by
`scripts/capture_slot.sh`), evaluated at one publish run.

| Kind | Candidates | Price | Market number | Our number |
|---|---|---|---|---|
| Moneyline | Both sides of every game | Best available price for that side on the newest multi-book board | De-vigged multi-book consensus for that side at that board (`market_implied_probability`, as V1) | Run model `strength.model_line` with the frozen `DISPERSION` of 11.2 and the frozen moneyline calibration of 11.2 applied to `p_home` / `p_away` |
| Run line | Both sides at exactly +1.5 and -1.5 (no alternate lines) | Best available price at that line | Consensus probability at that line (`src.report.card.run_line_rows`) | `strength.run_line_probability` with the `DISPERSION` of 11.2, family `nb1`, passed through the frozen side-level run-line calibration of 11.2. **Today no calibration touches run-line numbers:** `src/report/card.py:953-957` replaces only `p_home` and `p_away`, and `strength.run_line_probability` (`:610-620`) reads the raw `p_*_plus` / `p_*_minus`. `docs/PREREG_RUN_DISPERSION.md` calibrated only the chance a game is decided by 2 or more runs, not which side covers. The section 14 illustration uses those raw numbers |
| Player prop | Both sides of every `batter_hits` and `batter_total_bases` contract (`daily_card.PROP_MARKETS`) | Best available price | De-vigged market probability on the contract (`market_probability`) | Prop board probability (`propboard.build` via `src.report.props.board_for_date`) with the frozen `RHO` and slot table of 11.2, not calibrated |
| Game totals | **Not candidates.** `TOTALS_ON_CARD` stays `False`. Adding totals is a new registration. | | | |
| NFL, tennis | Not covered. | | | |

"Best available price" is the price shown to the reader with its book, exactly
as V1 shows it. No gate and no ranking step compares one book's price with
another's or with the market's own number.

## 3. Gates

A candidate is a **pick** only if it passes every gate. Probabilities are
fractions; prices are American odds.

| Gate | Test | Moneyline and run line | Player prop |
|---|---|---|---|
| G1 Not started | First pitch strictly after the publish instant, fail-closed (`src.report.card._has_started`) | yes | yes |
| G2 Books | Books quoting this exact selection at the board | at least 6 (`prices.MIN_BOOKS`) | at least 2 (`propboard.MIN_BOOKS`) |
| G3 Fresh | `publish instant - observed_utc` of the quote; a missing or unparseable `observed_utc` fails | at most 3,600 seconds (`grade.FRESH_SECONDS`) | at most 3,600 seconds (`grade.FRESH_SECONDS`) |
| G4 Worst price | `price >= -160` (so -160 passes and -161 fails); no limit on the long side, because G5 makes a plus-money pick rare (section 4) | yes | yes |
| G5 Market likely | market number `> 0.50` | yes | yes |
| G6 Ours likely | our number `> 0.50` | yes | yes |
| G7 Price test | our number `> breakeven(price)` (section 4) | yes | yes |
| G8 Disagreement cap | `abs(our number - market number) <= 0.10` | yes | yes |
| G9 Calibrated | the frozen parameter file of 11.2 is loaded with its `sha256` as registered, and holds the moneyline calibration (for a moneyline) or the run-line cover calibration (for a run line). A candidate failing G9 is neither a pick nor a close call | yes | not applicable |
| G10 Prop data | lineup posted (`expected_pa_source == "batting_slot"`), and `season_games >= 15` (`daily_card.MIN_SEASON_GAMES_FOR_PRELINEUP`; missing `season_games` fails) | not applicable | yes |
| G11 One per game or player | At most one entry per game across moneyline and run line; at most one entry per player on props; picks and fills (section 6) count alike; a game that already has a locked game entry takes no other game entry | yes | yes |
| G12 Ceiling | At most 10 picks on the date, locked picks included (owner, 2026-09-15: "3-10 bets"). Fills are not picks and are not counted against it; they exist only while the entries shown number fewer than 3 (section 6). Because the ceiling counts picks only, and a fill once shown is not removed when picks arrive later, a date that begins thin can list 13 bets at once, 10 picks and 3 fills. That is more than the 10 he named; the departure is stated in section 6 and in question 1 for him to rule on before registration | yes | yes |

A **fill** (section 6) is not a pick and does not pass every gate. It must pass
G1, G2, G4, G5 and G9, have our number available, and fail at least one of G3,
G6, G7, G8 and G10. It is labelled as not a pick and says which check it failed.

Where the gate constants come from: 0.50 (G5, G6) is the owner's "more than
likely" (2026-09-11); -160 (G4) is the owner's 2026-09-15 word, confirmed by
him the same day against -150 (question 4); 10 (G12) is from the same message;
6, 2, 3,600 and 15 are the existing repo constants named in the table. An
earlier draft used 4 books and 25 games for props; neither had a source, and
25 would have shut props out of every 2026 pick, because `season_games` counts
a batter's prior rows in `data/processed/boxscores_2026.jsonl`, which starts
2026-08-30 (on 2026-09-15 no batter had more than 15; the season ends
2026-09-27). With 15, props rest on 15 to about 27 games of history in 2026.

Where G8 comes from: `docs/PROP_CALIBRATION_2026-09-14.md`, where prop
contracts with our number 10 or more points above the market's hit 40.6%
against our stated 62.1% (n=32; 25 of the 32 rows, 78%, from one date). That
is a **prop-only, mostly single-date** measurement of the 10-point-and-over
tail. It is not evidence about game markets, and nothing on disk measures the
band from 0 to 10 points; the same document found the market's own number
tracked results at least as well as ours on every cut. G8 removes the tail the
measurement flagged; it does not show the band below it is safe (section 4).

## 4. The value test

```
breakeven(price) = src.core.odds.american_to_probability(price)   # vig included
passes G7        = our_number > breakeven(price)
```

The market's number is not required to clear `breakeven(price)`: a de-vigged
consensus clearing the best price is a disagreement between books, which is
line shopping. On the design board it happened on 0 of 82 game-market sides
and 0 of 56 likely-side props.

**What G7 does in practice.** When the market's number is below the price's
break-even, which was every candidate on the design board, a candidate passes
G7 only if **our number is above the market's by more than that gap** (the
"vig gap", `breakeven(price) - market number`). Among the 34 design-board
candidates inside -160 with the market above 0.50, the vig gap ran 0.8 to 4.0
points (median 2.8). So G7 is a disagreement threshold, and every pick sits in
a positive-disagreement band from its vig gap up to G8's 10 points: of the 15
game candidates passing G1, G2, G4 and G5 (G3 set aside), exactly two passed
G7, at +9.3 points (Angels +1.5) and +2.9 (Twins +1.5). Model-over-market
disagreement is what the 2026-09-09 incident showed selects the model's own
errors; here it is used as a filter, not a ranking, and our number never
enters the ranking (section 5), but that does not make it safe. The hit rate of
that band is unmeasured, so it is watched from the first counted picks by a
pre-registered, one-way harm check (11.4) and published by S2.

**Plus money.** G5 requires the market's number above 0.50. Unless one book's
price is better than the market's own number, which did not happen once on the
design board, that puts the break-even above 50%, so a pick is priced shorter
than even money. On the design board, 0 of the 27 game and prop candidates
priced +100 or longer had the market above 0.50, and the longest price among
the 84 candidates with the market above 0.50 was -108. Whether a market
underdog at plus money may be a pick is owner question 5 (default no).

## 5. Ranking

Picks are ordered by, in turn, on unrounded numbers:

1. `breakeven(price)`, ascending: the longest price first (owner question 8;
   the default follows the 2026-09-11 directive to establish a bet is likely
   first and then sort the survivors by price; if Brey answers no, this key
   is removed and the order starts at key 2);
2. market number, descending;
3. `abs(our number - market number)`, ascending;
4. books quoting, descending;
5. first pitch, ascending;
6. the bet sentence, alphabetical.

No key uses a comparison between books or between our number and the price.
If a moneyline and a run line on the same game both pass, the one ranked higher
by this order is kept and the other is dropped (G11). Locked picks count
toward the ceiling, so provisional candidates compete for the slots that
remain. The served order applies the same key to every pick on the date,
locked or provisional, using each pick's own frozen numbers.

Fills are not ranked by this key and never mix with the picks: they are ordered
by the close-call order of section 6 and are listed below every pick.

## 6. Pick count, the floor of three, fills, thin days and stale boards

- **Floor: 3 entries. Ceiling: 10 picks. Most listed at once: 13.** The card
  lists three bets on every day whose board offers three candidates past G1,
  G2, G4, G5 and G9 (owner, 2026-09-15: "Always show 3"), and fewer, down to
  none, on a board that offers fewer (the "Fewer than 3 entries" bullet below).
  The rule never adds a **pick** to reach
  the floor and never relaxes a gate on a thin day. The floor is met by
  **fills**, which are not picks, say so on their face, and go on the record.
- **Close calls.** A candidate that passes G1, G2, G4, G5 and G9, has our
  number available, is not a pick, and fails at least one of G3, G6, G7, G8 or
  G10 is a close call. G3 is not required of a close call, so a prop whose
  only price is the pre-lineup capture can still qualify, although it rarely
  ranks first (section 8); every close call
  shows how old its price is (copy C6). Close calls are ordered
  by: fewest failed gates (G10's lineup and sample tests count separately);
  then shortfall `max(0, breakeven(price) - our number)`, ascending; then
  market number, descending; then first pitch; then the sentence.
- **Fill.** A fill is the highest-ranked close call in that order, added only
  while the entries currently shown for the date, picks and fills together,
  number fewer than 3. A withdrawn entry is not shown, so it holds no slot. At
  most one entry per game or player across picks and fills (G11), and no fill
  for a game or player that has a pick. Because a fill passes G4 and G5 it is
  never priced shorter than -160 and never a side the market makes less likely
  than not; because G3 is not required of it, a fill may rest on a price last
  checked more than an hour ago, and it says so on its face (copy C6).
- **Close calls that are not fills are not shown.** The non-pick entries on the
  card are exactly the fills, at most 3 at a time. A day whose first publish run
  already has 3 picks never shows one; a day that starts thin shows the fills
  it added and keeps them (the bullet below). So
  every bet the card lists is graded on the record, and there is no second
  class of listed-but-ungraded entries. The close calls that are not shown are
  still frozen on the ledger row for audit.
- **Fills on the record.** A fill is published, frozen, locked and graded
  exactly as a pick is (section 9), flat 1 unit at its own graded price (owner,
  2026-09-15, choosing "Always show 3": "Those fills go on the record and can
  drag it down"). A fill is never a counted pick: the primary metric, the
  floors, the harm check, the verdict and the retirement result read counted
  picks only, and fills are published beside them as a pre-declared separate
  line (11.1, 11.3, 11.5, 12). No fill can rescue or sink the rule's verdict.
- **A fill can become a pick.** From the first publish run whose fresh read of
  it passes G1 to G12, it is a pick, and it locks, is graded and is counted as
  a pick. A pick never becomes a fill: a pick that fails a gate on a fresh read
  is withdrawn under L3 and is still graded as a pick.
- **A fill once shown stays.** Picks appearing later in the day do not remove
  it. It is carried, locked and graded like a provisional pick, and is
  withdrawn only as L3 withdraws a pick: on a fresh read that fails it on G1,
  G2, G4 or G5, or when G11 gives its game or player a pick. So a day that
  begins thin can end with three fills beside several picks, and all of them
  are graded. At most 3 fills are shown at any one time; a withdrawn fill frees
  its slot, so a date with withdrawals can put more than 3 fills on the record,
  each graded at its last shown version and each reported in D3.
- **The largest card, and a departure from "3-10 bets".** G12's ceiling of 10
  counts picks only, and the bullet above keeps a fill once it is shown, so the
  most this rule can list at one time is **13 bets: 10 picks and 3 fills**,
  every one of them published and graded. The owner named "3-10 bets" on
  2026-09-15 and was not shown this consequence when he answered "Always show
  3", so it is written here, in G12, in question 1 and in the diagnosis's
  2026-09-15 row for him to rule on before registration; until he does, the
  rule stands as his answer left it. Neither way of holding the total at 10 was
  taken without him: refusing a pick once 3 fills are shown hides a bet that
  passed every gate, and withdrawing a shown fill to make room removes a bet
  already published. Each changes what goes on the public record, which is his
  decision and not a drafting one.
- **Fewer than 3 entries.** If fewer than 3 candidates pass G1, G2, G4, G5 and
  G9 with our number available, the card shows fewer and says so in one plain
  line (copy C13). It never relaxes a gate to reach three. This is not only a
  capture failure: on a small slate of one-sided games every favourite can be
  priced shorter than -160 (failing G4) while every underdog is below 0.50 by
  the market's number (failing G5), so the board itself can offer fewer than
  three candidates, and with no qualifying prop the card can show none at all.
  That state is published as a count, never filled.
- **Thin day.** Fewer than 3 picks is shown as the pick count, with the fills
  beneath it (copy C4).
- **Stale quotes and the capture schedule.** The dense capture prices every
  game only while some game is within 180 minutes of first pitch; before
  that it widens to the full slate once an hour, in the first 15 minutes of
  the hour, or when the newest capture is 55 or more minutes old
  (`scripts/capture_slot.sh:355-388`). G3's 3,600 seconds matches that hourly
  full-slate pass. A late pass or a lagging chain can still leave a quote
  stale, so: a stale read **never adds** a pick and **never withdraws** one.
  A provisional pick whose newest read is stale stays on the card as last
  shown, without "Take", marked as waiting for fresh prices (copy C2b), until
  a fresh read confirms or withdraws it (L3). A stale read **may add a fill**,
  because the floor is met at every run and G3 is not required of a fill; that
  fill shows how old its price is, and it is graded at that price. A stale read
  never withdraws a fill.
- **Stale board.** If no quote on the newest board for the slate is within
  3,600 seconds of the publish instant, the served card shows its locked picks
  and carried provisional picks (neither with "Take"), its fills to the floor
  with their price ages, and the stale-board line (copy C5) with the age read
  from the board.

## 7. Labels and the headline verb

- No STRONG, LEAN, SLIGHT or SPLIT label, and no chip on a pick or a fill. The
  card has two section heads: "Today's picks" and "Close calls, not picks"
  (`docs/DESIGN_SYSTEM.md` section 4 removes per-card label chips). The second
  section holds the fills, and is absent when the day has none.
- **Headline-verb rule.** The sentence begins "Take" if and only if the entry
  is a pick **and the newest publish run's read of that selection is fresh
  (G3) and passes G1 to G12 there**, which includes the newest best price
  inside G4 and our number above that price's break-even (G7). This holds for
  locked picks too: from its lock until first pitch, which is when most people
  bet, a locked pick keeps "Take" only while the newest fresh read still
  passes; otherwise it shows without a verb, with its locked price and the
  reason (copy C2b), and it is still graded at its locked price. A provisional
  pick whose newest read is stale shows without a verb, marked as waiting for
  fresh prices. A fill begins with the selection, never a verb, whatever its
  numbers do, and carries on its face the line saying it is not a pick, which
  check it failed, and that it is graded on the record apart from the picks
  (copy C6 and C12). Nothing outside the picks section ever carries "Take".
- Every pick shows, on the card face, at every rank and every screen width,
  **both** C2 lines: the market's number, the break-even of its price and our
  number; and the sentence saying which of the two numbers clears the price
  and that our number has not been shown to beat the market's. Neither line
  may sit behind a "View breakdown" control. That disclosure is mandatory; it
  is not a reason to withhold "Take".

## 8. Props safeguards (collected)

Market in `batter_hits` or `batter_total_bases`; at least 2 books
(`propboard.MIN_BOOKS`); lineup posted; at least 15 games of history
(`daily_card.MIN_SEASON_GAMES_FOR_PRELINEUP`); one pick per player; G5 to G8 as
for games. A prop with no posted lineup can only ever be a fill.

What a reader sees: batter props are captured twice per game, once 5 to 7
hours before first pitch (baseline, before lineups) and once 0 to 2 hours
before (gate, after the lineup for about 85% of games;
`src/pipeline/batter_props.py:25-30`, `CAPTURE_LEAD_MINUTES = 120`). Before its
lineup posts a prop can appear only as a fill, on a day whose picks number
fewer than 3, showing "lineup not posted yet" and how old its price is, and
usually it will not appear at all. Its only pre-lineup price is the baseline
capture, so from
about an hour after that capture it fails two tests (G3 and G10's lineup test),
and any close call failing one test ranks ahead of it (section 6). In roughly
the first hour after the baseline capture it fails only the lineup test and
can rank first. EXPLORATORY, on the design board with game prices
treated as fresh and prop prices as stale: the board gave 2 picks and 1 fill,
and the fill was Cubs to win at -135, failing only G7; Royals +1.5 and Giants
+1.5 were the next close calls and were not shown; none of the 19 props that
qualified as close calls was shown
(`scratchpad/owner_answers/fill_illustration.py`, which reuses
`scratchpad/card_v2_revise/close_calls_props_stale.py`'s pool and gate tests).
A prop can
become a pick only from a fresh read after its lineup posts, which in practice
means the gate capture, 0 to 2 hours before first pitch, and it then locks at
once (L2).

## 9. Lock, withdrawal and grading

Fills (section 6) follow every rule here, with the gates a fill must pass
(G1, G2, G4, G5, G9) in place of G1 to G12, and are graded on the record apart
from the picks.

- **L1.** A pick is provisional until the first publish run at or after first
  pitch minus 4 hours (`card_ledger.LOCK_LEAD_HOURS`). A fill is provisional on
  the same schedule.
- **L2 (as V1).** At that run, a pick on the newest published row locks **as
  last published**: the price, book, both numbers and quote time the reader
  was shown, whatever that run reads (`card_ledger._lock_and_merge`: "the
  reader saw that bet at that price"). A selection not previously shown becomes
  a pick at a run at or after that point only if that run's own fresh read
  passes G1 to G12, and it locks at that run. A fill locks the same way, and a
  selection not previously shown becomes a fill at such a run only if that run
  reads it as a close call and the floor of 3 is still short at that run. If no publish run happens at or
  after first pitch minus 4 hours (the capture chain was down), the pick as
  last published is graded, and counted as "graded without a lock run" (D4).
- **L3 (withdrawal).** Before its lock, a provisional pick is withdrawn only
  when a publish run whose read of that selection is fresh fails it on a gate,
  or when G11 or G12 displaces it. A stale read never withdraws a pick
  (section 6). A withdrawn pick is written to the row's `withdrawn` list with
  the run instant and failed gates, carried forward on every later row for the
  date, **graded at its last shown version**, and shown on the record apart
  from locked picks (R5). A withdrawn selection that passes again before its
  lock returns as the same pick and is graded once, at its last shown version;
  the withdrawal stays in the ledger history. Withdrawn picks do not hold a
  G11 or G12 slot after withdrawal. A provisional fill is withdrawn only on a
  fresh read that fails it on G1, G2, G4 or G5, or when G11 gives its game or
  player a pick; picks appearing later never withdraw it, and a withdrawn fill
  is graded at its last shown version like a withdrawn pick.
- **L4.** A locked pick is carried forward verbatim and graded whatever later
  runs read. Its headline verb follows section 7. A locked fill is carried
  forward verbatim, graded, and keeps its label.
- **Grading.** Flat 1 unit at the graded version's price. Game picks by
  `card_ledger.grade_pick` (moneyline winner; run line by margin plus line).
  Props by `card_ledger.grade_prop_pick`. Fills by the same two functions.
  Voids are counted and reported, never dropped. Every graded entry carries the
  class it held at its graded version, pick or fill, and is graded once.

## 10. Rules computed in shadow on the same days

Each is published every run to its own ledger, locked by its own lock rule,
graded the same way, and never shown to customers.

| Rule id | Definition | Ledger |
|---|---|---|
| `DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1` and `DAILY_CARD_PROP_LIKELY_AND_CLEARS_PRICE_V1` (V1) | The selection logic, constants and lock rule of `src/analysis/daily_card.py` and `card_ledger` exactly as committed at registration, with the calibration file V1 reads. Its nightly refit, which read sealed-window and forward games (section 1.2; diagnosis section 0), was stopped by Brey on 2026-09-15 ("Freeze it now"; record `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`, commit `ba09312c`), before V2's first counted day, so V1's **calibration file** does not change during V2's sample. That is all the freeze delivers: it covers only that file's `a` and `b` and says so in terms. The rest of V1's model and its selection code stay live and editable for a sample the read date puts around August 2027, and 11.2 records 15 commits to the model files in five days and 12 to `src/report/card.py` since 2026-08-28. So V1 is pinned by measurement, not by assumption: every V1 shadow row carries a `v1_code_fingerprint`, the sha256 of `src/analysis/strength.py`, `src/analysis/playerprops.py`, `src/analysis/propboard.py`, `src/report/props.py`, `src/analysis/daily_card.py`, `src/report/card.py`, `src/appstate/card_ledger.py` and `data/processed/card_calibration.json`, with the registration-commit value written into section 16. A row carrying another value is reported under 11.6 with the dates and the commits that changed it, never assumed away. Comment-only, docstring-only and customer-copy-only edits (build plan T10, T10b and the interim V1 copy change) are not a change to V1's selection, and a fingerprint change made only of those is reported as such | `evidence/cards_v1.jsonl` until the cutover date, `evidence/cards_v1_shadow.jsonl` from the cutover date; no date in both |
| `DAILY_CARD_BEST_BETS_V2_SHADOW_A_BAND_ONLY` (A) | V2 with G6, G7 and G8 removed; everything else identical | `evidence/cards_v2_shadow_a.jsonl` |
| `DAILY_CARD_BEST_BETS_V2_SHADOW_C_OTHER_WORST_PRICE` (C) | V2 with G4 set to the other answer to owner question 4: `price >= -150` if V2 registers -160, `price >= -160` if V2 registers -150; everything else identical | `evidence/cards_v2_shadow_c.jsonl` |

A tests whether the gates on our number do anything. C tests the other of the
two worst prices the owner named ("-150 or -160"), which he settled at -160 on
2026-09-15 (question 4). V1 is the rule being replaced.

A and C carry V2's floor of 3 and its fill rule unchanged, so their records are
read the same way: picks apart, fills apart, and the two together. On the
design board A published 10 picks and no fill, C 2 picks and 1 fill (14.3).

---

## 11. Evaluation plan

### 11.1 Population

A V2 pick is **counted** if all hold:

- it was shown as a pick on at least one published V2 row and graded under
  section 9: locked (L2), graded without a lock run (L2), or withdrawn (L3).
  Withdrawn picks are counted because leaving them out would let the gates
  choose which shown picks are measured; every metric is also reported for
  locked and withdrawn picks apart;
- its first pitch is strictly after `REGISTERED_UTC`;
- its game is a regular-season game (MLB `gameType` `R`, read from the
  `game_type` frozen on the pick). Postseason picks are published, graded and
  shown on the record, but not counted;
- the `code_fingerprint` frozen on its row matches the model definition in
  11.2 for the current count.

2026-09-15 and every earlier date are never counted. Shadow picks are counted
by the same rules, each under its own rule's lock (V1 keeps its own), for the
comparisons in 11.6.

**Fills are never counted picks.** An entry counts as a pick only if it was
shown as a pick on at least one published row; an entry shown only as a fill is
never in that population, whatever its numbers or its result. Graded fills form
their own population, **counted fills**, defined by the same four conditions
with "shown as a fill on at least one published V2 row, and a fill at its
graded version" in place of the first. The two populations do not overlap: a
fill that becomes a pick (section 6) is a counted pick and is not a counted
fill. Counted fills never enter the primary metric, the secondary metrics, the
floors, the harm check, the verdict, the retirement result or any comparison.
They are reported beside them (11.3).

### 11.2 Model definition

Part of this rule as registered. Owner question 3 was answered no on
2026-09-15 ("Rebuild on 2025"), so option O1 below is what V2 uses and O3 is
recorded only as the option not taken (section 1.2):

- `model_id` `run_expectancy_poisson_v1`, family `nb1`, with the run model's
  inputs as the card reads them today (team rates, starters, relief rates).
- **The frozen parameter file** `data/processed/card_v2_frozen_params.json`
  holds every fitted number V2 uses: `DISPERSION`, the moneyline Platt `a` and
  `b`, the side-level run-line cover calibration, `RHO` and the slot
  plate-appearance table. V2 reads them only from this file and passes them to
  the model explicitly. The module constants and the nightly
  `data/processed/card_calibration.json` that V1 uses are not changed.
- **Adopted (question 3 answered no, 2026-09-15), option O1:** one script, committed
  before it runs, fits every number in the file **once** on 2025
  regular-season games from 2025-04-15, after 2025 starter logs, relief
  appearances and box scores are backfilled into stores kept apart from the
  live 2026 stores (build plan T0a). It refuses any 2026 row. `DISPERSION` is
  estimated in that run with the full model inputs; the earlier 2025 figure,
  2.3265, is not used, because the stores it was computed from hold no 2025
  starter or relief data today (section 1.2, O1). The script's output is
  frozen as it comes out; it is never re-run to get a different answer. If the backfill or the fit cannot be
  built, the rule is not registered until Brey decides.
- **Not taken, option O3 (question 3 answered yes):** the file would have held
  `DISPERSION =
  2.3352` and `RHO = 0.05065`, the two numbers fitted only on sealed-window
  games, frozen, and every published read of V2 would have carried the label
  "not independent of the sealed window". The moneyline calibration, the slot
  table and the run-line
  cover calibration would still have been fitted once on 2025 as in O1, by the
  same script
  with `DISPERSION = 2.3352` as its model input: the nightly moneyline
  calibration read forward games from 2026-08-28, which no answer can
  authorise; the slot table's window is not recorded (1.1), so it cannot be
  shown to exclude them; and a run-line fit on 2026 would be a new sealed
  read. Brey did not authorise the sealed window, so none of this applies and
  no V2 read carries that label. It is kept here so the record shows what was
  offered and refused.
- Under either option there is **no daily refit** under this rule id: a refit reads
  2026 games, which are sealed or forward. The file's sha256 is written into
  section 16 at registration.
- The prop board probability method in `src/analysis/playerprops.py`,
  `src/analysis/propboard.py` and `src/report/props.py` as committed, with the
  frozen `RHO` and slot table passed in.
- `code_fingerprint`: sha256 of `src/analysis/strength.py`,
  `src/analysis/playerprops.py`, `src/analysis/propboard.py`,
  `src/report/props.py`, `src/analysis/best_bets_card.py`,
  `src/report/card_v2.py` (where `card_v2_for_date` reads the frozen parameter
  file and passes its numbers to the model) and the frozen parameter file,
  frozen on every row. Every one of these files exists and is merged before
  the registration commit (build plan order), so the value is computed at that
  commit and written into section 16; the first count is of rows carrying that
  value.

A change to any fingerprinted file or to `model_id` restarts the counted
sample (`docs/VALIDATION_CRITERIA.md`: "Changing the model restarts the
sample"). Picks from before the restart stay on the record and are reported as
their own count. Every restart is recorded in section 16.

**How likely a restart is.** The model files changed in 15 distinct commits
between 2026-09-10 and 2026-09-14 (`git log --since=2026-08-28` on
`strength.py`, `playerprops.py`, `propboard.py`, `props.py` and
`fit_card_calibration.py`; 9 of them on the first, third and last). A 2027 restart
is expected unless the prop board reads the box-score store for the slate's
season before registration (`src/report/props.py:36` hard-codes
`boxscores_2026.jsonl`; build plan T0a). Plan on at least one restart.

### 11.3 Metrics

**Primary: closing-line value at the price taken**, as
`docs/VALIDATION_CRITERIA.md` defines it ("whether you consistently bet at
better prices than the market closed at") and as `src/report/clv.py` computes
its mandated `clv_bps`. For each counted game pick:

```
needs    = breakeven(graded price)            # the price the reader was shown, vig included
board    = src.report.clv.closing_board(entry, market_key, side, line)
           # the closing instant is chosen FIRST: the market's last capture strictly
           # before first pitch. The line and the 6-book floor are then checked inside
           # that capture; fewer than 6 books at that instant is CLOSING_BOARD_THIN
p_close  = src.report.clv.closing_consensus(board, market_key, side)   # de-vigged
clv_bps  = (p_close - needs) * 10,000          # = consensus_move_bps + price_standing_bps
CLV%     = p_close / needs - 1
beats the close = CLV% > 0
```

Reported: **share of counted game picks that beat the close**, and **mean
CLV%**. This starts negative by the pick's vig gap (0.8 to 4.0 points on the
design board), so a pick beats the close only if the fair market moves toward
it by more than that. That is the bar `docs/VALIDATION_CRITERIA.md` sets, and
it is expected to be hard to pass. An earlier draft used the move in the
de-vigged consensus from lock to close as the primary metric; that is a
different, looser measure, it is kept only as S4 under the name "consensus
drift", and it is never called CLV (`docs/DEBRIEF.md:126-130`).

A game pick has no CLV% (counted separately by reason, never zero-filled) when:
`CLOSING_BOARD_THIN` at the closing instant; the close was captured more than
5,400 seconds before first pitch (`clv.CLOSING_LEAD_STALE_SECONDS`); the
closing capture is the capture the pick's quote came from
(`CLOSING_BOARD_IS_DECISION_BOARD`); the closing capture is older than the
pick's quote (`CLOSE_PRECEDES_DECISION`); or the game cannot be joined to an
odds event. Props are not in the primary metric: on the design board no prop
had 6 books.

**Secondary.**

- S1 **ROI** at graded prices, 1 unit, over counted picks graded WIN or LOSS
  (game and prop together, and each kind shown apart), with a 95% interval
  from a bootstrap over slate dates (10,000 resamples, seed 20260915).
- S2 **Calibration by disagreement**: counted picks bucketed by
  `our number - market number` in points: below 0, 0 to under 3, 3 to under
  6, 6 to 10. Each bucket: n, mean our number, mean market number, mean
  break-even, hit rate. Because of G7, nearly every pick is in a positive
  bucket (section 4). Published with the result; never used to change G8; its
  3-points-and-over rows feed the harm check in 11.4.
- S3 **Data completeness**: share of counted game picks on complete data. A
  game pick is on complete data when, at its graded version, both probable
  starters were named and its quote passed G2 and G3: the knowledge grade's
  core facts other than lineups (`src/analysis/grade.py:30-53`). Lineups are
  left out because the run model ignores them (`src/analysis/strength.py:81`,
  "Lineups are ignored entirely") and because the lock comes before them by
  design: EXPLORATORY, of 51 games from 2026-08-31 with both lineups seen
  (`data/watch/lineups_watch.jsonl`, availability only), both posted at least
  4 hours before first pitch in 0 and the median lead was 2.87 hours, and V1's
  40 locked game picks carried grade A 5, C 23, D 2, none 10. Requiring grade A
  would make this stop condition fire from the lock schedule alone. Counted
  props are complete by G10.
- S4 **Consensus drift** (never called CLV): `p_close / p_lock - 1`, with
  `p_lock` the market number frozen on the graded version. Share positive and
  mean. Never a pass or fail condition, never shown to customers as beating
  the close.
- S5 **Log loss against the market**: over counted picks graded WIN or LOSS,
  mean log loss of our number against the result beside mean log loss of the
  market number (game and prop together, and apart).
- S6 **Live calibration error of our number**: over counted picks graded WIN or
  LOSS, bins by our number [0.50, 0.55), [0.55, 0.60), [0.60, 0.65),
  [0.65, 1.00]; `ECE = sum over bins of (n_bin / N) * abs(mean our number -
  hit rate)`.

**Fills, reported apart (F1).** Over counted fills, published beside every
number above and never inside one: n; won-lost-push and units at the graded
prices; ROI; the share beating the close and the mean CLV% computed exactly as
the primary metric computes them for picks; the count by the check each fill
failed (G3, G6, G7, G8, G10 lineup, G10 sample); and the count of fills whose
price was more than 3,600 seconds old when they were added. F1 is pre-declared
here so that the fills are published whatever they do. No F1 number is a pass,
a fail or an input to one, and no F1 number is compared with a pick number to
draw a conclusion about the rule; a fill can therefore neither rescue nor sink
the verdict. The same line is published for each shadow rule that carries the
floor (section 10).

**Descriptive only, never graded.** D2 the share of counted picks that would
fail G4 or G7 at the median book's price instead of the best. D3 fills per
date, the check each failed, and the share of dates whose floor was met by one
or more fills. D4 per-date pick counts, dates with fewer
than 3 picks, dates with fewer than 3 entries, dates with a stale board at
every run, withdrawals per date,
picks graded without a lock run, picks shown without "Take" after their lock.
D5 knowledge-grade distribution (A to D) of counted game picks. D6 not applied:
`docs/VALIDATION_CRITERIA.md`'s "live vs backtest ECE, drift > 0.04", because
no backtest of this rule exists and none may be run on the sealed window.

### 11.4 Floors, the harm check, the read date and the stop date

One read, at the first settlement run after which **both** hold. Counted picks
only; no fill counts toward either floor, however many fills the card
publishes:

- (a) at least 300 counted game picks with a CLV%; and
- (b) at least 300 counted picks graded WIN or LOSS, across at least 60
  distinct slate dates.

Before that the read script prints `PENDING` and the counts, with no interval
and no direction. **There is no early verdict and no continuation after the
read.** The record page shows V2's running win-loss and units every day
(R5); that is a record, not a read, and it is not a verdict. Per-pick closing
measurements may be written to the ledger as they settle, but nobody summarises
CLV%, S2, S4, S5 or S6 over counted picks before the read, except the harm
check below.

**Harm check (one-way, pre-registered, cannot be rescued).** Run once at each
threshold and published with its counts. Counted picks only; a fill neither
triggers it nor delays it:

- at the first settlement run after 100 counted game picks have a CLV%: if the
  share beating the close is below 50% **and** the 95% bootstrap interval of
  mean CLV% (over slate dates, 10,000 resamples, seed 20260915) is entirely
  below zero;
- at the first settlement run after 50 counted picks graded WIN or LOSS have
  our number at least 3 points above the market's: if the 95% Wilson interval
  on their hit rate lies entirely below the mean break-even of their graded
  prices.

If either fires, the result is `HARM_STOP`: from the next publish day V2 keeps
selecting, locking, grading and counting under this id, so the registered read
still happens, and the floor of 3 and the fill rule keep running with their
labels, but no entry carries "Take" and the card uses copy C11 in the
form for the arm that fired (the closing-price form for the first arm, the
hit-rate form for the second, both sentences if both have fired). A
`HARM_STOP` is never reversed under this id; a passing later read does not
restore "Take" without a new registration.

**Expected read date.** 300 counted game picks with a CLV% at about 2 a day
(the illustration's count) is about 150 slate dates. The 2026 regular season
has at most 12 left after 2026-09-15 (it ends 2026-09-27,
`docs/SEASON_END_PLAN.md:11`), so the read falls around August 2027 with no
restart and 2 counted picks every day, and not in 2027 at 1 a day. A restart
(11.2) pushes it later.

**The ROI fail arm.** At 300 bets the 95% interval on ROI is about plus or
minus 9 points at -150 and 11 at -115 (`1.96 * sqrt((d - 1) / 300)`), so that
arm fires only on a point estimate below about -10%. It catches a very bad
rule, not a mildly losing one.

**Stop date.** If the floors are not met by the end of the 2027 MLB
postseason, the result is `UNDERPOWERED`: the counts and every 11.3 statistic
are published once as a named non-verdict read, V2 stops publishing picks
under this id, and the card uses copy C9 until a successor rule is registered.

**A successor before the read.** A rule registered to replace V2 before the
read must, in its registration commit, publish V2's CLV% and ROI at that
moment as a named non-verdict read ("V2 interim at successor registration"),
so that abandoning V2 after a bad run is visible.

The floors are not lowered because a season was short.

### 11.5 Verdict

Thresholds and stop conditions from `docs/VALIDATION_CRITERIA.md`; all five
stop conditions are applied, and the one criterion not applied is D6. Every
condition below reads **counted picks only**. Counted fills are published
beside the verdict as F1 and enter no condition, so a good or bad run of fills
can neither rescue nor sink it.

- **FAIL** if any of:
  1. share beating the close below 50%, or mean CLV% at or below 0%;
  2. our number's log loss higher than the market number's (S5, all counted
     picks graded WIN or LOSS);
  3. live calibration error above 0.06 (S6);
  4. ROI point estimate below -5% with the whole 95% interval below zero;
  5. fewer than 60% of counted game picks on complete data (S3).
- **PASS** if share beating the close is at least 55%, mean CLV% is at least
  +1.5%, and no FAIL condition holds. If PASS coincides with an ROI interval
  entirely below zero, execution and grading are investigated and the finding
  is written up before the verdict is published.
- **INCONCLUSIVE** otherwise.

### 11.6 Comparisons on the same days

At the same read instant, V2 is compared with V1 (shadow), A and C, on counted
picks only; fills are outside every comparison. Brey froze V1's nightly
calibration refit on 2026-09-15, before V2's first counted day
(`docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`), so V1's calibration file does
not change inside the sample. **That is all the freeze delivers.** It covers
only that file's `a` and `b`; `DISPERSION`, `RHO`, the slot table and V1's
selection code stay live and editable across the whole sample, and the model
files changed in 15 commits in the five days before this draft (11.2). So the
comparison is read against the `v1_code_fingerprint` frozen on every V1 shadow
row (section 10): if any row in the sample carries a value other than the
registration-commit value in section 16, and the commits behind the change are
not all comment-only, docstring-only or customer-copy-only, the V1 comparison
is published as a comparison with a model that changed during the sample,
naming the dates and the files. The same caveat applies if the nightly refit
restarts. Its record before the freeze is still the record of a model that
changed nightly, so no verdict on V1 itself is drawn from the comparison either
way ("Changing the model restarts the sample",
`docs/VALIDATION_CRITERIA.md`).

- Statistic: over slate dates on which both rules have at least one counted
  game pick with a CLV%, the mean of (V2's daily mean CLV% minus the other
  rule's daily mean CLV%).
- Interval and p-value: bootstrap over those dates, 10,000 resamples, seed
  20260915; two-sided p is twice the smaller tail share at zero.
- Multiple comparisons: Holm correction across the three comparisons at a
  family-wise 0.05.
- The same procedure is applied to daily ROI as a second family of three.
- Results are published with the verdict. **No comparison result changes the
  published rule.** A challenger that beats V2 can only be adopted through its
  own new registration, counted from after that registration.

### 11.7 The retirement result

Read on counted picks only; the fills' F1 line is published beside the result
and never decides it.

On **FAIL** or **UNDERPOWERED**, within one publish day:

1. `DAILY_CARD_BEST_BETS_V2` stops publishing picks and fills;
2. the customer card shows shadow A's list under copy that makes no pick
   claim and uses no "Take" (copy C9) until a successor rule is registered;
3. the verdict or non-verdict read, every counted pick, every counted fill with
   its F1 line, and every comparison are published under `docs/`;
4. no parameter in this file is changed and re-run under this id.

On **HARM_STOP** (11.4), V2 keeps running without "Take" under copy C11, and
the harm-check result is published under `docs/` within one publish day.

### 11.8 What each result licenses

- **PASS** licenses an internal statement that this rule's picks were taken at
  better prices than the market closed at, on the registered measure (price
  taken against the de-vigged close). Customer copy may state the measured
  share and n with their dates only after the G7 owner sign-off in
  `docs/ARCHITECTURE_BETTING_ENGINE.md`. S4 (consensus drift) is never
  presented to customers as beating the close. No result of this registration
  licenses customer copy that claims an edge, value or a guarantee. The
  evidence rules forbid a customer claim of an edge or a guarantee outright,
  and `tests/test_customer_language.py` allows "edge" and "guaranteed" only
  negated. No result licenses any statement about the fills: F1 is published as
  a record of what the card listed, never as a finding.
- **INCONCLUSIVE** licenses nothing, ever. V2 may keep publishing with its
  unproven copy. Any further test is a new registration with a window that
  starts after it.
- **FAIL** and **UNDERPOWERED** are published as stops; **HARM_STOP** is
  published as a stop of "Take".

## 12. Record keeping

- **R1.** V2 picks, fills, provisional versions, withdrawn picks and fills, the
  close calls that were not shown, and
  stale-board states are written to `evidence/cards_v2.jsonl`, hash-chained,
  one row per publish run that changed anything and at least one row per slate
  date, **including dates with 0 picks**. Every row carries
  `rule: DAILY_CARD_BEST_BETS_V2`, the gate constants in force, the floor and
  the `code_fingerprint` (11.2); every pick and every fill carries its
  `game_type`, its class (pick or fill) and, on a fill, the checks it failed
  and its quote age when it was added.
- **R2.** Shadow rules write only to their own files (section 10).
- **R3.** `evidence/cards_v1.jsonl` is never rewritten. It receives no rows
  dated on or after the cutover date.
- **R4.** Records are computed per file. No number anywhere adds V1 and V2
  picks together, on the page, in the API or in a report.
- **R5.** The record page shows V2's record, and V1's record through the
  cutover date as a separate, closed block, both read from their ledgers at
  request time. **Each block shows game picks, player props and game totals
  together, and each kind apart**, with the kind lines of C8 (V2 has no totals,
  section 2, so its block never shows a totals line; V1's block shows one only
  if a V1 total was graded); V2's block also shows withdrawn picks apart.
  **V2's block shows three headline figures: the picks, the fills and all
  entries together, each with its own won-lost-push and units.** The picks
  figure is the rule's record; the fills figure is the record of what the floor
  of 3 put on the card; the combined figure is what a reader who took every
  listed bet would have. No figure mixes a pick with a fill inside it, and the
  page names which is which. The verdict of 11.5 is read on the picks only,
  and the page never presents a fills or combined figure as the rule's result.
  V1's headline today (`card_ledger.record()`, `card_ledger.py:956-1115`)
  counts game picks only and keeps props under `by_kind`, so the staging card's
  "26-12, +4.82 units" leaves out V1's prop picks. EXPLORATORY, store
  `evidence/cards_v1.jsonl`, `card_settled` rows through 2026-09-14, WIN or
  LOSS: games 26-12, +4.8194 units; props 9-5, -0.6418; together 35-17,
  +4.1776. The closed V1 block uses the together figure as its headline.
- **R6.** For 14 days from the cutover date the card shows the switch banner
  (copy C10).

## 13. Customer copy

Every string passes `tests/test_no_nothing_clears_the_bar.py` and
`tests/test_customer_language.py`. Percentages are rendered by one server
function as whole numbers, rounded half up; if any two of the three numbers on
a pick would show the same text while their frozen 4-decimal values differ,
all three show one decimal, then two, until no such pair shows the same text.
The client never re-rounds. Braces are fields read from the payload.

- **C1 Section head and purpose.** "Today's picks" · "Picks today: {n}" ·
  "Each pick is priced no shorter than -160, the market makes it more likely
  than not, and our number is above what the price needs. Because the market
  has to make it more likely than not, a pick is almost never plus money. The
  card lists three bets on a day when three clear the first checks. On a day
  when fewer than three pass every check, the closest calls are listed under
  the picks and marked as not picks, and on a day when the board offers fewer
  than three at all the card lists fewer and says so."
- **C2 A pick.** Headline: "Take {selection} at {price}" (only under the
  section 7 rule). Meta: "{book}" and the provisional, "Lock pending · graded
  as published" or locked state from `docs/DESIGN_SYSTEM.md` (true under L2,
  which locks as last published). First line, on the card face: "Market says
  {market}%. Needs {needs}% to break even at {price}. Our number: {ours}%."
  Second line, also on the card face (`why[1]`): when the market's number is
  below the break-even: "The market's number is below what this price needs
  and ours is above it. Our number has not been shown to beat the market's."
  When the market's number is at or above it: "Both the market's number and
  ours are above what this price needs. Our number has not been shown to beat
  the market's."
- **C2b A pick shown without "Take"** (section 7). Headline: "{selection} at
  {price}". Added line, one of: locked, newest fresh read fails: "Locked at
  {price} ({book}). On the newest price check the best price is {now_price},
  and our number is below what that price needs, or the price is shorter than
  -160." Locked, selection missing from the newest fresh read: "Locked at
  {price} ({book}). No current price for this bet on the newest check."
  Newest read stale: "Waiting for fresh prices. Prices were last checked {age}
  ago." The C2 lines stay on the face.
- **C3 Added lines.** When the market's number is below 0.55: "The market
  makes this only slightly more likely than not." Run line +1.5: "+1.5 wins if
  the {team} win, or lose by one run." Run line -1.5: "-1.5 wins only if the
  {team} win by two or more runs." Prop: "{player} is batting {ordinal} in the
  posted lineup, with {season_games} games of history."
- **C4 Fewer than 3 picks (including 0).** Under C1: "Only bets that pass every
  check are picks, so some days have fewer than three. The bets below fill the
  card to three. They are not picks, each one says which check it did not pass,
  and each is graded on the record apart from the picks."
- **C5 Stale board.** "Picks today: {n} so far. Prices were last checked
  {age} ago. New picks are only made from prices checked in the last hour, so
  this list waits for the next check. The bets below are not picks. They fill
  the card to three, or to as many as the board offers, at the prices last
  seen, and they are graded at those prices."
- **C6 The fills, listed under "Close calls, not picks".** Head: "Close calls,
  not picks". Entry: "{selection} at
  {price} ({book}). Price checked {age} ago. Market says {market}%. Needs
  {needs}% to break even. Our number: {ours}%. Not a pick: {reasons}."
  Reasons, joined with "; ": G3 "price not checked in the last hour"; G6 "our
  number does not make it more likely than not"; G7 "our number is below what
  the price needs"; G8 "our number is more than 10 points away from the
  market's"; G10 lineup "lineup not posted yet"; G10 sample "fewer than 15
  games of history". (A fill has already passed G1, G2, G4, G5 and G9,
  so no other reason can apply.) Every entry in this section also carries C12.
- **C7 Disclaimer.** "These are picks, not guarantees. Our number has not been
  shown to beat the market's, and every pick shows both numbers and what the
  price needs. Every pick is published before its game. A pick still on the
  card four hours before its game is graded at the price shown then, win or
  lose. A pick removed earlier is graded too, at the price it was last shown
  at, and listed as removed. The bets listed as not picks are graded the same
  way, and kept apart from the picks on the record."
- **C8 Record line.** "Card picks, rule v2 · {first} to {last} · {n} picks ·
  {w}-{l}-{p} · {units} units at the published prices. Game picks
  {gw}-{gl}-{gp}, {gunits} units. Player props {pw}-{pl}-{pp}, {punits} units.
  Picks removed before their lock, included above: {rw}-{rl}-{rp}, {runits}
  units. Bets listed as not picks, kept apart from the picks: {fw}-{fl}-{fp},
  {funits} units. Picks and those bets together: {aw}-{al}-{ap}, {aunits}
  units. Preliminary: not enough picks yet to show an edge or its absence." V1
  block: "Rule v1, on the card until {cutover}: {w}-{l}-{p} over {days} days,
  {units} units at the published prices. Game picks {gw}-{gl}-{gp}, {gunits}
  units. Player props {pw}-{pl}-{pp}, {punits} units. Game totals
  {tw}-{tl}-{tp}, {tunits} units. Kept as it was, and not added to rule v2's
  numbers." A kind with no graded picks is left out of the line rather than
  shown as zero; V1 graded no totals through 2026-09-14, so today its block
  shows no totals line. The two sentences about bets listed as not picks are
  left out while no such bet has been graded, and V1's block never carries
  them, because V1 has none.
- **C9 After a FAIL or UNDERPOWERED.** Head "Today's board". Purpose "Bets
  priced no shorter than -160 that the market makes more likely than not,
  listed in the order of section 5. These are not picks." No verb on any
  entry.
- **C10 Switch banner.** "From {cutover} the card uses a new rule: no pick is
  priced shorter than -160, and on a day when fewer than three bets pass every
  check the card lists the closest calls beside the picks, marked as not picks
  and kept apart on the record. The old
  rule's record is kept below, separately." It says how the shortfall is
  filled, never how many entries a given day will have, so it stands beside
  C13 as well as beside C4 and C5.
- **C11 After a HARM_STOP.** Head "Today's list". Purpose, in the form for the
  harm-check arm that fired (11.4). Closing-price arm: "These bets pass our
  checks, but a check on the first graded ones found they were getting worse
  prices than the market settled at, so we no longer say take them. They are
  not picks." Hit-rate arm: "These bets pass our checks, but a check on the
  first graded picks where our number was well above the market's found they
  won less often than their prices needed, so we no longer say take them.
  They are not picks." If both arms have fired, the purpose is "These bets pass
  our checks, but checks on the first graded ones found they were getting
  worse prices than the market settled at, and that picks where our number was
  well above the market's won less often than their prices needed, so we no
  longer say take them. They are not picks." No verb on any entry; the C2 lines
  and the record stay. The fills keep their own head, their C6 entry and C12.
- **C12 The line on every fill** (section 6, section 7). On the face of every
  entry under "Close calls, not picks", under its C6 line: "This one did not
  pass every check, so it is not a pick. It is listed because the card shows
  three bets on a day when three clear the first checks, and it is graded on
  the record apart from the picks."
- **C13 Fewer than three entries.** Used whenever the board offers fewer than
  three bets that pass the first checks: in place of C4, and in place of C5's
  two fill sentences ("The bets below are not picks. They fill the card to
  three, or to as many as the board offers, at the prices last seen, and they
  are graded at those prices."), so that no string on the card promises three
  bets beside two entries. On a stale board C5's first three sentences stay and
  C13 follows them. The string: "Today {n} bets are
  listed. Before a bet is listed at all, its game has to be unstarted, enough
  books have to be quoting the price, the price has to be no shorter than
  -160, and the market has to make that side more likely than not. Today the
  board had {n} of those." At n = 0 the card shows this line and no entry,
  which is the one state the floor cannot fix without breaking G4 or G5, and it
  never breaks them (section 6).

No string on the card claims an edge, value or a guarantee, and none uses
"STRONG", "sure", "fair price", "best of N books" or calls a model number a
chance of winning. "Edge" appears only inside the negated record line from
`docs/DESIGN_SYSTEM.md` (C8), and "lock" only as "Locked", "Locked at
{price}", "Lock pending" and "before their lock", never as "a lock".

---

## 14. What this rule would have published on 2026-09-15

**Illustration on already-seen data, not evidence.** The design used this
board, so it is excluded from every count in section 11. Source:
`scratchpad/card_v2/candidate_pool_2026-09-15.csv` (138 candidates rebuilt
live at about 17:15Z with the repo's own functions) and the published V1 row
(16:42:48Z). Script: `scratchpad/card_v2/ap_v2_screen.py` (ranks on unrounded
numbers and recomputes each break-even from the price; it supersedes
`v2_final_screen.py`, which sorted on numbers rounded to one decimal).

**Which model.** The numbers are the pre-registration model's: the card
calibration of 14:37Z (n 1,997, `b` 0.769145), `DISPERSION = 2.3352` and
`RHO = 0.05065`, all fitted on sealed-window games and the calibration on
forward games too (section 1.1), and **raw,
uncalibrated run-line numbers**, with G9 treated as passed for run lines
because no run-line calibration exists yet. The registered default model
(11.2) would give different numbers, so this shows what the gates do, not what
the registered model would pick. Independent re-screen of the same pool:
`scratchpad/card_v2_revise/verify_pool.py` (reproduces the picks, close calls,
shadow lists and candidate counts below; the quote ages come from the V1 row).
The floor of 3 and the fills were added to that re-screen, unchanged in every
other respect, by `scratchpad/owner_answers/fill_illustration.py`, and the
lists below are its output.

**Quote times.** The pool's 56 game rows have an empty `observed_utc`. The game
board's capture time, 14:31:29Z, is read from the published V1 row and is the
newest row in `data/processed/odds_multibook.jsonl` on this machine; prop quote
times (04:09:29Z to 04:09:34Z) are in the pool. Prop rows carry no first pitch;
the script maps each batter's club to its game (every game on the slate started
22:40Z or later). The pool must be rebuilt with game quote timestamps before it
is used as the T12 fixture.

### 14.1 As registered

At the 16:42:48Z publish instant every game quote was 7,879 seconds old and
every prop quote over 12 hours old, all above G3's 3,600. **V2 publishes 0
picks and 3 fills**, and serves C5 ("Picks today: 0 so far. Prices were last
checked 2 h 11 min ago. New picks are only made from prices checked in the last
hour, so this list waits for the next check. The bets below are not picks. They
fill the card to three, or to as many as the board offers, at the prices last
seen, and they are graded at those prices."). The board offered more than three
candidates past G1, G2, G4, G5 and G9, so C13 does not fire and C5's fill
sentences stand. The three fills, in the close-call order of section 6, each
with its price age and its C12 line, and 33 close calls available:

| # | Entry | Books | Market | Needs | Ours | Not a pick |
|---|---|---:|---:|---:|---:|---|
| 1 | Angels +1.5 at -114 (FanDuel) | 11 | 52.0% | 53.3% | 61.3% | price not checked in the last hour |
| 2 | Twins +1.5 at -112 (LowVig) | 10 | 51.3% | 52.8% | 54.1% | price not checked in the last hour |
| 3 | Matt Olson under 1.5 total bases at -157 (Caesars) | 4 | 57.8% | 61.1% | 65.7% | price not checked in the last hour; lineup not posted yet |

Under the owner's answer these three go on the record and are graded at prices
that were over two hours old, because the floor is met at every publish run and
a fill does not have to pass G3. Michael Harris II under 1.5 at -148 and Pete
Alonso under 1.5 at -150 were the next close calls and would not be shown.
Before the answer the same three appeared as close calls and were never graded.

### 14.2 With G3 set aside, as if the capture chain had kept the board fresh

Totals excluded (paused). 112 moneyline, run-line and prop candidates.

**Picks: 2**, in the default order of section 5 (longest price first)

| # | Headline | Book (books) | Market | Needs | Ours | Gap |
|---|---|---|---:|---:|---:|---:|
| 1 | Take Twins +1.5 at -112 (NYY at MIN) | LowVig (10) | 51.3% | 52.8% | 54.1% | 2.9 |
| 2 | Take Angels +1.5 at -114 (SEA at LAA) | FanDuel (11) | 52.0% | 53.3% | 61.3% | 9.3 |

With question 8 answered no (market number first), the same two picks in the
other order. Pick 2 as it would read: "Take Angels +1.5 at -114" · "Market
says 52%. Needs 53% to break even at -114. Our number: 61%." · "The market's
number is below what this price needs and ours is above it. Our number has not
been shown to beat the market's." · "The market makes this only slightly more
likely than not." · "+1.5 wins if the Angels win, or lose by one run." Under C1
and C4.

**Fills: 1**, because 2 picks leave one slot to reach the floor of 3. The
close-call order puts the three pre-lineup props first: each fails one gate with
no shortfall, so they rank ahead
of the game close calls that fail G7 (Cubs to win at -135: market 56.2%, needs
57.4%, ours 57.1%; Royals +1.5 at -150; Giants +1.5 at -149). Of the 31 close
calls available, one is shown.

| Shown | Entry | Books | Market | Needs | Ours | Not a pick |
|---|---|---:|---:|---:|---:|---|
| fill | Matt Olson under 1.5 total bases at -157 (Caesars) | 4 | 57.8% | 61.1% | 65.7% | lineup not posted yet |
| no | Michael Harris II under 1.5 total bases at -148 (Caesars) | 3 | 57.0% | 59.7% | 64.9% | lineup not posted yet |
| no | Pete Alonso under 1.5 total bases at -150 (Caesars) | 3 | 56.2% | 60.0% | 62.7% | lineup not posted yet |

All three rest on 15 games of history. No prop contract on the 04:09Z board had
a posted lineup, so no prop could be a pick. The card would therefore be two
picks and one fill: three entries, of which one is graded apart and carries
C12.

**With game prices fresh and prop prices stale**, the state the capture
schedule produces for most of the day: the same 2 picks, and the fill is Cubs
to win at -135 (market 56.2%, needs 57.4%, ours 57.1%), failing G7 alone.
Royals +1.5 at -150 and Giants +1.5 at -149 are next and are not shown, and no
prop is shown (section 8).

**None of V1's 8 published picks passes.** All five game picks fail G4 (-230,
-225, -210, -210, -186) and G7. Cole Young under 1.5 (-184) fails G4 and the
lineup test. Matt Olson under 1.5 (-157) and Michael Harris II under 1.5 (-148)
pass G2 (4 and 3 books against a book floor of 2), G4 and the 15-game test, and
fail only the lineup test; they are the first two close calls, and Olson is the
one fill.

### 14.3 Shadow rules on the same board (G3 set aside)

| Rule | Picks | Fills | Notes |
|---|---:|---:|---|
| V1 | 8 | not applicable | As published (section 1 of the diagnosis); V1 fills to 3 from its SPLIT pile, which did not fire on this board |
| A, band only, default order | 10 (the ceiling; 15 passed before G11 and G12) | 0 | Red Sox -108, Twins +1.5 -112, Angels +1.5 -114, Brewers -1.5 -117, Padres -1.5 -119, Phillies -1.5 -120, Mets -128, Blue Jays -133, Cubs -135, Dodgers -1.5 -140. Our number was above the break-even on 2 of the ten (Twins, Angels); lowest was Padres -1.5 at 36.2% |
| A, band only, market number first | 10 | 0 | Cardinals -160, Royals +1.5 -150, D-backs -148, Guardians -144, Dodgers -1.5 -140, Cubs -135, Blue Jays -133, Mets -128, Phillies -1.5 -120, Padres -1.5 -119 (market 53.12%, which ranks it above Brewers -1.5 at 53.08%). Our number was below the break-even on all ten; lowest was Padres -1.5 at 36.2% |
| C, -150 | 2 | 1 | Same two picks as V2. Its one fill is Michael Harris II under 1.5 at -148, not Olson, whose -157 fails C's band; Alonso -150 and Cubs -135 are next and are not shown |

### 14.4 What cannot be read from this

One date, already seen, with a stale board and the pre-registration model. It
shows the gates do what they say. It says nothing about whether V2 picks win,
beat the close or return money, and must never be quoted as either "V2 works"
or "V2 is too strict". It does show the likely shape: few picks, priced a
little shorter than even money, close to a coin flip by the market's number,
each resting on our own number sitting a few points above the market's.

It also shows what the floor of 3 costs. On this board the card is 2 picks and
1 fill with fresh prices, and 0 picks and 3 fills at the real publish instant,
so on a day like this most of what the reader sees, and between a third and all
of what goes on the record, is bets the rule itself says are not picks. Whether
fills win or lose here is unknowable from one already-seen board and is not
read; what is known in advance is that they are graded, published and kept
apart, and that they never touch the verdict (11.1, 11.5).

---

## 15. Owner decisions this needs

Each question is one yes or no. An answered question records Brey's own words
with the date and time he gave them; an open question shows the default the
build, the V2 ledger and the `?rule=v2` preview use until he answers. The line
under each question says which of his words it departs from, or what it
settles.

**Answered so far: 1, 3 and 4, all by Brey on 2026-09-15 at about 22:35Z
(3:35pm Pacific), in chat, in reply to the four questions put to him in plain
words. Open: 2, 5, 6, 7 and 8.** Registration still requires his explicit
answer to each open question, or his explicit acceptance of its default, with
its date; nobody else may accept one for him.

**Question 2 departs from a standing owner directive. The customer card does
not switch from V1 to V2 until it is answered.**

1. **On a day when fewer than 3 bets pass every check, does the card fill to 3
   with the closest calls, labelled as not picks, or show fewer? ANSWERED
   2026-09-15 about 22:35Z: "Always show 3."**
   He was given both options in plain words and chose the second: "Show fewer
   (Recommended): publish only what passes, even 0, with up to 3 near misses
   listed underneath and clearly not called picks", or "Always show 3: fill to
   3 with the closest near misses, labelled as not passing the value test.
   Those fills go on the record and can drag it down." So the floor of 3 stands
   and is met by fills, which are graded and kept apart from the picks
   (sections 6, 9, 11 and 12). This honours "three to five bets every day"
   (2026-09-10) and the floor of the "3-10 bets" of 2026-09-15 on every board
   that offers three candidates past G1, G2, G4, G5 and G9. **It still departs
   from both on the board that does not.** No gate was loosened to reach three:
   a fill still passes those five gates, so it is never priced shorter than
   -160 and never a side the market makes less likely than not, and where a
   board offers fewer than three such candidates the card lists fewer, down to
   none, and says why (copy C13). That state is published as a count. Its cost,
   stated in the option he chose: entries the rule itself says are not picks go
   on the public record and can drag it down. The rule's verdict is protected
   from that by reading picks only (11.1, 11.5).
   **Departs from "3-10 bets" on the maximum, and he has not ruled on that.**
   G12's ceiling of 10 counts picks only, and a fill once shown is not removed
   when picks arrive later (section 6), so a date that begins thin can list 13
   bets at once: 10 picks and 3 fills, every one of them graded. That is more
   than the 10 he named. It follows from this answer and was not in front of
   him when he gave it, so it is written here for him to rule on before
   registration; until he does, the rule stands as his answer left it. The two
   ways to hold the total at 10 were not taken without him: one hides a pick
   that passed every gate, the other withdraws a fill already published, and
   each changes what goes on the public record.
2. **May a player prop become a pick only from a price checked after its
   lineup posts, in practice the last 2 hours before first pitch, so that
   before then it appears at most as a fill on a day with fewer than 3 picks,
   and on most days not at all? Default: yes.**
   Departs from props analysis that "needs to be ran pre emptively"
   (2026-09-14). The analysis still runs early, but a reader mostly will not
   see it: before its lineup posts a prop's only price comes from the capture
   5 to 7 hours before first pitch and is more than an hour old for most of
   that time, so close calls with fresh prices rank ahead of it (section 8; on
   the design board with game prices fresh, the one fill was a game bet and
   none of 19 props was shown). In 2026 a
   prop also needs 15 games of history, because the box-score store starts
   2026-08-30. If no, V2 is not cut over and nothing here is loosened; a rule
   that publishes pre-lineup props as picks needs its own registration.

**Questions 5 to 8 are still to be answered by Brey himself, or he explicitly
accepts the default, before the commit that sets `REGISTERED_UTC`; each answer
is recorded in section 16 with its date. Nobody else may accept a default for
him. After that commit a different answer is a new rule id. Questions 3 and 4
are answered below, in his words, with the date and time.**

3. **May V2 keep the two model numbers that were fitted only on sealed-window
   games, frozen at registration, with its record saying it can never be
   confirmed on the sealed window? ANSWERED 2026-09-15 about 22:35Z: no.**
   He was asked, in plain words, whether to rebuild the two settings on last
   season instead, and answered "Rebuild on 2025". So option O1 of section 1.2
   is adopted, not merely the default: every fitted number V2 uses is fitted
   once on 2025 games after a free 2025 data backfill, then frozen (11.2,
   build plan T0a, now owner-approved). The two numbers not kept are the
   run-spread number 2.3352 (fitted on 2026-04-15 to 07-15) and the prop
   correlation 0.05065 (fitted on 2026-06-17 to 08-05); their held-out checks
   also read games from 2026-08-28
   onward (section 1.1). The sealed window is not touched, and no V2 read
   carries a "not independent of the sealed window" label. If the backfill or
   the fit cannot be built,
   V2 is not registered until he decides again. The card
   calibration is not kept under any answer: its nightly fit read forward games
   from 2026-08-28
   (148 of the 1,901 games counted here; 1,753 are sealed), and the split
   reserves no go for folding forward games into a fit, so it is fitted on
   2025, as are the batting-slot table (fit window not recorded) and the
   run-line calibration.
4. **Is -160 the shortest price allowed, rather than -150? ANSWERED
   2026-09-15 about 22:35Z: "-160."**
   He was asked what the shortest price a pick may have is, and answered -160.
   He had written "-150 or -160"; shadow C keeps running -150 beside the rule
   (section 10), and no V2 pick or fill is ever priced shorter than -160 (G4).
5. **May a pick be a side the market makes less likely than not, at plus
   money, when our number beats its price? Default: no.**
   Under the default a pick is almost never plus money (section 4), which
   departs from the "-150, -115, +100, or higher" prices in your message.
6. **Is a pick acceptable when the market makes it only a little more than 50%
   likely, provided the page says so (copy C3)? Default: yes, floor 0.50.**
   Settles "high-confidence": both design-board picks were 51% and 52% by the
   market's number.
7. **Is it acceptable that every "Take" rests on our own number clearing the
   price, although our number has not been shown to beat the market's,
   provided every pick says so (copy C2)? Default: yes.**
   Settles "the value is great": on the 2026-09-15 board the market's number
   cleared the price on none of 82 game-market sides and none of 56 likely
   props. "Take" stops for good if the harm check fires (11.4). If no, the card
   uses no "Take" and shows shadow A's list under copy C9, as a separate
   registration.
8. **Among picks that pass every check, list the longest price first rather
   than the most likely first? Default: yes.**
   Settles the 2026-09-11 order: likely bets first, then sorted by price. The
   other order puts the shortest prices at the top.

One decision about V1, not V2, is not in this list: whether V1's nightly
calibration refit keeps reading the sealed window. It is set out in the
diagnosis, section 0, and Brey answered it on 2026-09-15 at about 22:35Z,
"Freeze it now": V1's nightly calibration refit is stopped and today's settings
are locked for the current card until V2 replaces it. That work is done
separately from this registration and its record is
`docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`. It changes no number here.

## 16. Amendment log

Permitted entries only: a typo that changes no number or rule; the recorded
owner answers with their dates, the frozen parameter file's sha256, the
`code_fingerprint` value (11.2) and the `v1_code_fingerprint` value
(section 10) at the registration commit; the recorded
cutover date; a recorded model restart under 11.2; a recorded change to the
`v1_code_fingerprint` under 11.6, which qualifies the V1 comparison and
changes no V2 number; links
to the published harm check and read. Anything else is a new rule id.

That restriction runs from `REGISTERED_UTC`. Rows dated before it record
changes to a draft that is not yet registered, which is where a rule may still
change at all; each says what changed and on whose word.

| Date (UTC) | Entry |
|---|---|
| 2026-09-15 about 22:35Z | Owner answer, question 1: "Always show 3", given in chat in reply to a plain-words question offering "Show fewer (Recommended)" or "Always show 3: fill to 3 with the closest near misses, labelled as not passing the value test. Those fills go on the record and can drag it down." Draft amended before registration: floor of 3 met by labelled fills; sections 0, 1, 3, 5, 6, 7, 8, 9, 10, 11.1, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 12, 13 (C1, C4, C5, C6, C7, C8, C10 revised; C12 and C13 added), 14 and 15 |
| 2026-09-15 about 22:35Z | Owner answer, question 4: "-160." -160 stands as G4; shadow C keeps -150 |
| 2026-09-15 about 22:35Z | Owner answer, question 3: no, "Rebuild on 2025." Option O1 of 1.2 adopted as the owner's answer rather than as the draft's default; no sealed-window fit is carried into V2; build plan T0a is owner-approved |
| 2026-09-15 about 22:35Z | Owner decision about V1, not this rule: "Freeze it now." V1's nightly calibration refit is stopped; record `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`, commit `ba09312c`. Recorded here because section 10's shadow V1 and 11.6's comparison describe it |
| 2026-09-16 | Draft correction, on the orchestrator's instruction after a verification pass, no owner answer involved and no number changed. The claim that the freeze stops V1's model changing was narrowed to what the freeze covers, its `a` and `b`; section 10 and 11.6 now pin V1 by a `v1_code_fingerprint` on every shadow row, and 11.6's caveat fires on any change to V1's model or selection files, not only on a refit restart. Sections 10, 11.6, 15 (status line) and 16 |
| 2026-09-16 | Draft correction, same instruction. C1, C5, C10 and C12 no longer promise three bets on a day the rule itself lets list fewer, and C13 is declared to replace C5's two fill sentences as well as C4. Sections 0, 6 (the floor bullet) and 13 (C1, C5, C10, C12, C13) |
| 2026-09-16 | Draft correction, same instruction. Question 1's claim that the floor "honours" the 2026-09-10 directive is limited to boards that offer three candidates, with the departure on thinner boards restored in the words the draft used before the amendment. Section 15, question 1; diagnosis section 6's 2026-09-10 row |
| 2026-09-16 | Draft correction, same instruction. The largest card this rule can list, 13 bets (10 picks and 3 fills), is stated as a departure from the owner's "3-10 bets" in G12, section 6, question 1 and the diagnosis's 2026-09-15 row, for him to rule on before registration. No cap was imposed and no gate changed |

## Review record

Adversarial review of 2026-09-15 (three reviewers: evidence and statistics;
owner intent, customer truth and buildability; live system reality), applied
to this draft before registration in two passes. Each finding was checked
against the repo before it was applied, and checked again against the current
text in the second pass so that none was applied twice. Findings filed against
the build plan are recorded in that file's Review record; four of them also
changed this file (sections 6, 7, 10, 11.1, 11.2 and R1).

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| high | Model rests on sealed-window fits (calibration window, `DISPERSION = 2.3352`, the 1,896-game result) while claiming compliance | Applied | Confirmed and extended: 1,753 of the 1,901 rows the calibration selects are dated 2026-04-15 to 08-27; `RHO` (fit 2026-06-17 to 08-05) is a third sealed fit; no 2025 starter or relief data exists on disk, so a 2025 fit needs a backfill. Sections 1.1 and 1.2 list every fit, rule on the sealed wording (already broken under V1), set out O1 to O3 and adopt O1 as default; 11.2 freezes one parameter file; question 3 rewritten |
| high | S3 counts only grade A, which needs lineups that post after the 4-hour lock, so FAIL fires from the schedule | Applied | Confirmed in `grade.py:44-53` and the lineup lead times; complete data defined as starters named plus a board passing G2 and G3, with the reason (the run model ignores lineups); 60% kept. `VALIDATION_CRITERIA.md` does not define complete data, so this sets the definition before any sample rather than loosening one |
| high | Primary metric swapped to consensus drift while claiming the validation bar is unchanged | Applied | Confirmed against `VALIDATION_CRITERIA.md` and `clv.py`; primary is now price taken against the de-vigged close, drift kept as S4 and never called CLV |
| high | G10's 25 games and props' 4 books have no source; 25 shuts props out of 2026 | Applied | Confirmed: box-score store starts 2026-08-30, max 15 prior games on 09-15; replaced by `daily_card.MIN_SEASON_GAMES_FOR_PRELINEUP` (15) and `propboard.MIN_BOOKS` (2); question 2 states the fact |
| high | Plus money is unreachable but copy and questions say it is possible | Applied | Confirmed on the pool (0 of 27 plus-money candidates with the market above 0.50); upper bound and old question 4 dropped, C1 and C10 rewritten, question 5 on market underdogs added |
| high | Verdict drops validation stop conditions 2 and 3 | Applied | Confirmed; log loss against the market (S5) and live calibration error above 0.06 (S6) restored as FAIL conditions; the one criterion not applied is named (D6) |
| high | Duplicate of the S3 finding (product review) | Applied | Same change as above |
| high | Picks shown as "Take" could be dropped ungraded under the fresh-read lock; `settle` grades unlocked picks; "Lock pending · graded as published" false | Applied | Confirmed in `card_ledger._lock_and_merge` and `settle`; lock reverts to V1's "as last published", withdrawn picks are graded and listed apart and counted, C7 rewritten |
| medium | Retirement cannot fire for over a year; no interim stop; restart likely | Applied | Confirmed (15 commits on the model files from 2026-09-10 to 09-14, 12 dates left, ROI arm width); read date, restart likelihood, one-way harm check, stop date and 2027 restart note added |
| medium | G7 is in practice a positive-disagreement threshold; G8's evidence is prop-only and single-date | Applied | Confirmed on the pool; section 4 rewritten, G8 source restated, S2 feeds the harm check |
| medium | V1 record block leaves out prop losers | Applied | Confirmed in `card_ledger.record()`; R5 and C8 require all kinds together and apart |
| medium | Ranking by market likelihood contradicts the recorded 2026-09-11 directive | Applied | Confirmed against the directive note; question 8 added with the directive's order as default |
| medium | Question 2 hides that pre-lineup props vanish under the freshness gate | Applied | Confirmed in `batter_props.py`; G3 no longer required of close calls, ages shown, question 2 rewritten |
| medium | Run-line numbers are uncalibrated although G9 reads as covering them | Applied | Confirmed in `card.py:953-957` and `strength.py:610-620`; section 2 says so, G9 now requires a frozen run-line calibration |
| medium | "No number fitted" is false (product duplicate of the sealed-window finding) | Applied | Same change as the first finding |
| medium | Closing board defined two incompatible ways (product duplicate of a low finding) | Applied | Confirmed in `clv.py:629-734`; p_close defined as `closing_board` then `closing_consensus`, thin board an absence |
| medium | "Take" persists on a locked pick after the price moves | Applied | Confirmed (`DESIGN_SYSTEM.md` has no moved-price state); "Take" now needs the newest fresh read to pass, else C2b |
| owner brief | Section 15 must be complete, one yes/no line per question with the build's default, and must state every departure from "-150 or -160" and "3-10 bets" | Applied | Questions rewritten as one question line each with its default and the words it departs from; question 1 names the missing floor, question 4 the -150 alternative, question 5 the unreachable plus-money prices; there is no upper price bound to ask about |

Low findings, all applied: p_close defined once (with the medium duplicate);
G9 and run lines (with the medium duplicate); corrected shadow A list, Cubs
break-even 57.4% and unrounded ranking; missing `observed_utc` fails G3 and the
pool needs quote timestamps; the "0 of 138" count restated per candidate kind;
"no early look" rewritten with a successor read; rounding beyond one decimal;
only Brey may accept a default. Second pass: the section 4 median vig gap
corrected from 2.9 to 2.8 points on an independent re-screen
(`scratchpad/card_v2_revise/verify_pool.py`). No finding was rejected.

### Verification pass

An independent verifier then checked all findings against the text and the
repo, found one medium only partly resolved and six new problems, and listed
three low items. Each was re-checked before it was applied; none was rejected.

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| high | O3 froze the nightly moneyline calibration, which also fits forward games from 2026-08-28, and question 3 called yes the go the split reserves, although the split reserves none for forward data | Applied, extended | Confirmed: 148 of the 1,901 rows in 1.1 are forward, and 1.2 already ruled forward fits out. O3 now keeps only `DISPERSION` and `RHO`, the two fits made only on sealed-window games; the moneyline calibration is fitted on 2025 under either answer (1.2, 11.2, question 3). Extended to the slot table, whose fit window is not recorded and so cannot be shown to exclude forward games. A check of the box-score store as committed at `30f8a287`, which added the table (3,322 batter rows, 2026-08-30 to 09-09), could not settle the window: the prop dispersion test run the same day read 16,741 batter games from a local store that commit does not hold (`scratchpad/card_v2_revise/slot_box_at_commit.py`) |
| medium | Finding 38 only partly resolved: the 3-close-call cap ranks one-test game close calls ahead of pre-lineup props, so question 2 and section 8 overstate what a reader sees | Applied | Confirmed EXPLORATORY on the design board with game prices fresh and prop prices stale: close calls Cubs, Royals +1.5 and Giants +1.5, 6 game close calls failing one test, none of 19 props shown (`scratchpad/card_v2_revise/close_calls_props_stale.py`). Sections 6 and 8 and question 2 now say a pre-lineup prop appears at most as one of the 3 and usually not. The rule is unchanged: the owner answers question 2 on the true picture |
| medium | `code_fingerprint` names `best_bets_card.py`, which the plan created after T0; the ledger could not exist from registration; `card_v2_for_date` was not fingerprinted | Applied (verifier's option a) | Confirmed in the build plan's order table. T2 to T5 are merged before T0 and tested on fixtures only, T0 writes the fingerprint value into section 16, and T6 follows T0 in the same push. `card_v2_for_date` moves to a new fingerprinted `src/report/card_v2.py`; `src/report/card.py` itself is not fingerprinted because V1 edits it often (12 commits since 2026-08-28), which would restart the count for changes that do not touch V2. Status line, 11.2 and section 16 updated |
| medium | C11 gave one reason for a two-arm harm check, false when the hit-rate arm fires | Applied | Confirmed in 11.4. C11 has a closing-price form, a hit-rate form and a combined form, and 11.4 selects by the arm that fired. The new strings trip none of the lists in `tests/test_customer_language.py` or `tests/test_no_nothing_clears_the_bar.py` |
| medium | 11.8 implied the full gate could license "guarantee" (and "edge") as a claim | Applied | Confirmed against the evidence rules and `NEGATION_ONLY`. 11.8 now says no result licenses such a claim, and the evidence rules forbid a customer claim of an edge or a guarantee outright |
| low | R5 names game totals in record blocks but C8 had no totals line | Applied | C8's V1 block gains a totals line under the existing omission rule (V1 graded no totals through 2026-09-14); R5 says V2's block never shows one |

The other two low items (build plan T6 line numbers; the live doc's
confirmation date) are recorded in those files.

### Owner answers of 2026-09-15, applied to the draft

Brey answered four questions in chat at about 22:35Z. Three of them changed
this file; the fourth is about V1. The draft stays a draft: questions 2, 5, 6,
7 and 8 are open, and registration still needs his explicit answer or his
acceptance of each default.

| Answer | Applied where | Note |
|---|---|---|
| Question 1, "Always show 3" | 0, 1, 3, 5, 6, 7, 8, 9, 10, 11.1, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 12, 13, 14, 15, 16 | The floor is met by fills, never by relaxing a gate. A fill passes G1, G2, G4, G5 and G9, is labelled on its face as not a pick with the check it failed, is graded on the public record, and is excluded by name from the primary metric, the floors, the harm check, the verdict and every comparison. Close calls beyond the fills are not shown, so every listed bet is graded. The known cost is written down in 14.4 and in question 1 itself |
| Question 4, "-160" | 3 (G4), 10, 15 | No number changed; the band was already -160 and shadow C already ran -150 |
| Question 3, "Rebuild on 2025" | 1.2(c), 11.2 reads as adopted, 15 | O1 moves from default to owner answer. No sealed-window fit enters V2, so the "not independent of the sealed window" label is not used |
| The V1 freeze, "Freeze it now" | 1.2(a), 10, 11.6, 15, 16 | Not part of this registration. It narrows the "model changed during the sample" caveat on the V1 shadow comparison to what the freeze covers: V1's calibration file stops changing from before V2's first counted day, the rest of V1's model does not, and the caveat now fires on any change a `v1_code_fingerprint` detects (section 10, 11.6) |

The illustration of section 14 was re-run on the same already-seen pool with
the fill rule added and nothing else changed
(`scratchpad/owner_answers/fill_illustration.py`, built on
`scratchpad/card_v2_revise/verify_pool.py`). It is an illustration on
already-seen data, not evidence. Consistency of the band, the floors, the fill
rule, the rule id and the copy strings across this file, the build plan and the
diagnosis was checked by
`scratchpad/owner_answers/consistency_check.py`.

### Verification pass on the amendment (2026-09-16)

An independent verifier re-read the three amended documents against the repo,
found no way for the fill rule to put a bet on the record that a base gate
refuses, and confirmed that no evidence threshold, floor, FAIL condition or
stop date moved. It filed eleven problems, none high. The four with substance
were re-checked against the text and the repo before they were applied; none
was rejected. No number in section 11 changed, and the draft is still a draft.

| Severity | Finding | Outcome | Reason |
|---|---|---|---|
| medium | "V1's model does not change during V2's sample" (section 10) and "inside the sample" (11.6) claim more than the freeze delivers | Applied | Confirmed in `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`: "This freeze covers only the card calibration (`a`, `b` above). It says nothing about `DISPERSION` or `RHO`". This file already recorded 15 commits to the model files in five days (11.2) and 12 to `src/report/card.py` since 2026-08-28, for a sample running to about August 2027, so the sentence asserted what a one-file freeze cannot deliver and 11.6's caveat fired only on a refit restart. Both sentences narrowed to the calibration file; V1 pinned by a `v1_code_fingerprint` on every shadow row, registered in section 16; 11.6's caveat now fires on any detected change that is not comment-only, docstring-only or customer-copy-only; build plan T3, T7 and T14 carry the field, the escalation and the check |
| medium | C1, C12 and C5 promise three bets a day on days the rule allows fewer, and C13 was declared to replace C4 only | Applied | Confirmed against section 6's "Fewer than 3 entries" bullet and C13's own "At n = 0 the card shows this line and no entry". On a stale board that also offers fewer than three candidates, C5 would have promised three bets beside two entries. C1 and C12 now say three bets on a day when three clear the first checks; C5 says "to three, or to as many as the board offers"; C10 says how the shortfall is filled rather than how many entries a day has; section 6's floor bullet carries the same condition; C13 replaces C5's two fill sentences as well as C4. Every changed string was re-checked against `tests/test_customer_language.py`, `tests/test_no_nothing_clears_the_bar.py` and `tests/test_web_structure.py` (which imports the same three lists), with no violation |
| medium | Question 1 and the diagnosis's 2026-09-10 row claim the floor "honours"/"keeps" the three-to-five directive, where the pre-amendment draft recorded a departure | Applied | Confirmed: the same documents say a board can offer fewer than three candidates past G1, G2, G4, G5 and G9, and that state is published as a count with no entry. Both now honour the directive on every board that offers three and name the one state that departs, with C13 |
| medium | The card can list 13 bets (10 picks plus 3 fills) against the owner's "3-10 bets", and no document stated it | Applied | Confirmed: G12 counts picks only and section 6 keeps a fill when picks arrive later. No cap was imposed, because each way of holding the total at 10 changes what goes on the public record and that is the owner's call. The maximum and the departure are now stated in G12, section 6, question 1 and the diagnosis's 2026-09-15 row, for him to rule on before registration |

The seven remaining items were read and left as they stand: the diagnosis
states the fill rule in plainer words than the registration and is an
abbreviation of it rather than a contradiction; the close-call counts, the
G12 and section 6 wordings of the fill trigger, section 1.1's present tense,
the freeze commit (now cited in section 10 and 16), the stale-price grading
(disclosed and owner-accepted) and the surviving "default" fragments change no
number and no rule.
