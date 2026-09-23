# Pre-registration: DAILY_CARD_BEST_BETS_V2

**Rule id:** `DAILY_CARD_BEST_BETS_V2`
**REGISTERED_UTC: 2026-09-22T14:35:00Z**
**Registration-time note, part of this registration (orchestrator review,
2026-09-22).** The three PAPER arms of section 17 (A2-A4) have no production
wiring at this instant: no CLI or capture step publishes them yet (build plan
T6). They start on the first slate date after that wiring lands, and that date
is recorded here in a section 16 permitted edit. No arm's result is read
before section 17's read date either way. The published arm A1
(`DAILY_CARD_BEST_BETS_V2`) and the V1 shadow run from the cutover date
`2026-09-23`.

**Family:** CARD_V2 (MLB daily card)
**Status:** REGISTERED, 2026-09-22T14:35:00Z. All of questions 1 to 11 are
answered by Brey himself (2026-09-15 and 2026-09-16, section 15). Questions
12, 13 and 14 are answered 2026-09-17 by Claude (Opus 5) under Brey's explicit
delegation ("I need you to take over, take charge, and make the correct
choices ... I just don't need to be answering these questions for you. You
need to be solving them."), all three YES at their stated defaults (section
15b): the variant family registers as written (12), the published card A1
keeps the strict bar while the loose pair runs only on paper (13), and the
layout experiment licenses a rendering change and nothing else (14). The
frozen parameter file of 11.2 exists at `data/processed/card_v2_frozen_params.json`,
sha256 `64e96b4a9a8d56753fa38f2f0b97b51eb87b3c48adaf29db199eb10b6467db3d`. The
code the `code_fingerprint` of 11.2 covers is merged; its value at this commit
is `8a641de0ee76091972d482cc316b47924a474e063334d67056333513ee4d2061`
(`src.appstate.card_ledger.code_fingerprint()`, computed over
`V2_FINGERPRINT_FILES`). The `v1_code_fingerprint` of section 10 at this
commit is `10f5cac7191ff23d0afcebc1f3566c8e747b9e4286a1eacbbfd8be09bf1c92ee`
(computed over `V1_FINGERPRINT_FILES`). No V2 pick and no paper-arm pick
existed before this instant: `evidence/cards_v2.jsonl` and every family/shadow
store did not exist before this commit (checked directly, not assumed). The
one further condition on plus-money picks is also satisfied: the SR1 read
already registered in `docs/RESEARCH_STRATEGY_REPLICATION.md` and
`docs/PREREG_SR1_HOME_UNDERDOG.md` ("home underdog, moneyline price band +100
to +150") was run and killed on 2026-09-16, UNDERPOWERED_NULL, no edge in
either band, published at `docs/SR1_RESULT_2026-09-16.md`, before this
registration commit and therefore before the first plus-money pick. Its
result does not gate registration, licenses nothing here and changes no
number in this file (11.9 item 3).
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
first checks (owner, 2026-09-15: "Always show 3"), and **never more than ten
bets in total, picks and fills together** (owner, 2026-09-16 about 00:45Z). On
a day when fewer than three pass every gate, the rest are **fills**: the
closest calls, labelled on their face as not picks, published and graded like
picks and kept apart from them on the record. On a day whose board offers fewer
than three candidates at all, the card lists fewer, down to none, and says why
(section 6, copy C13). The forward read this registers is of the picks only;
the fills are reported beside it and can never change it (sections 6, 11
and 12).

Picks come in **two classes, graded apart from each other and never pooled**
(section 3, 11.1):

- **MAIN**, priced -160 to -100, where the market's own number makes the side
  more likely than not. This is the band the draft registered.
- **PLUS_MONEY**, priced +100 to +250, where the market makes the side the
  underdog. New, on the owner's direction of 2026-09-16 (section 0.1). It is
  published with a label on its face, on its own record line, under its own
  floors, its own harm check and its own retirement result, and capped at 3 of
  the card's slots until he rules otherwise (question 9).

**Four rule variants run on the same board every day, and exactly one of them
is published.** Section 17 registers a fixed family of four arms over the two
settings the owner disputed on 2026-09-16 about 03:10Z: how far our own number
is marked down before it may clear a price, and whether the card caps
plus-money picks at three. The arm registered above, `DAILY_CARD_BEST_BETS_V2`,
is the one customers see. The other three select, lock, grade and keep a record
on paper, are never served to a customer, and can replace the published card
only through the promotion rule of 17.4, which is fixed before any result
exists and is charged against a multiplicity budget (17.3). The family answers
a strategy question with a pre-registered comparison instead of an open-ended
search; what it costs and what it cannot deliver are in 17.8.

It claims no edge, no positive expected return and no guarantee. On the one
already-seen board used to design it (2026-09-15), the market's own number
cleared the best available price on **0 of 82 game-market sides** (30
moneyline, 26 run line, 26 totals) and on **0 of 56 props**, where the 56 were
only the side of each contract the market already makes likely (the board's
`most_likely` list, not both sides as section 2 defines props). That is one
board, not a law. It means that on that board every "Take" this rule could
publish rested on **our own number** clearing the price, and our number has
not been shown to beat the market's (`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`).
The customer copy says so on every pick (section 13). Under this revision our
number is **marked down by a fixed amount, registered in advance**, before it
is allowed to clear any price (section 4), and a candidate whose market number
already clears its own best price is refused outright as line shopping (G13).

## 0.1 Supersession: what the owner changed on 2026-09-16, and what it replaces

Recorded here, with both quotes and both dates, because the change is a
reversal of a standing directive and must not be applied quietly.

**The standing directive, 2026-09-11** (`docs/PLAYER_PROPS_NEXT.md:5-7`,
`docs/LIVE_BETTING_SYSTEM.md:558-562`), verbatim:

> "none of that price matters until we know it's a MORE THAN LIKELY BET, once
> we have the almost guaranteed bets, then we find the best sports picks of
> those with the best value, not the other way around."

The draft carried that directive out through G5 and G6, which required both the
market's number and ours to be above 0.50, and through a ranking that sorted
survivors by price.

**The superseding answers, 2026-09-16 about 00:50Z** (5:50pm Pacific 9/15),
verbatim, in reply to plain-words questions about this draft:

> "BOOM KEY QUESTION! Theres a lot of times where trhe underdog actuall makes
> more sens than the favorite and those are the real bangers, vewgas doesnt
> always get the stats right and sometimes the underdog isnt because his
> likelihood iof winning is low, it might be due to other factors and
> especially UFC when we get to it there so many underdogs, and same with
> fidning +100 to +250 poicks offer rally good value"

> "even confidence of 30-45+ percent if high enough value (+150, +200 etc etc)
> we need an algorithm of value x confidence / likelihood"

> "again based on cionfidence x value alrogirthm that we need to dial in"

**What is superseded, and what is not.** For the card, from this revision:
"establish a bet is more than likely first, then look at price" no longer
governs the plus-money class. G5 and G6 keep their 0.50 tests in the MAIN band,
where he did not ask for a change, and are replaced in the plus-money band by a
market band of 0.20 to below 0.50 and a hard floor of 0.30 on our own number,
which is his own number. The ranking key is replaced, in both classes, by the
single value-times-confidence score he asked for (sections 4 and 5). Both
directives stay in the record. The 2026-09-16 one governs sections 3 to 6 from
here; the 2026-09-11 one still governs the MAIN band's 0.50 tests and still
governs every other rule in the repo that cites it, none of which this
registration changes.

**A second answer, the same instant**, on player props:

> Q: "Player props: may a prop become a pick only after the lineup is posted,
> roughly the last 2 hours before first pitch?" A: **"No, allow earlier."**

That answers question 2 no, and it removes the lineup test from G10 (sections 3
and 8). It is not a side effect of the score; it is its own gate change, and it
matches what the live V1 card already does
(`src/report/card.py:717` calls `daily_card.select_props(..., require_lineup=False)`;
`src/analysis/daily_card.py:1274-1280`). Keeping the lineup test would have made
V2 stricter on props than the product running today, against a direct answer.

## 0.2 The honest problem this design does not refuse

A value-times-confidence score is an estimate of expected value, and expected
value is only as good as the probability inside it. Stated plainly, before any
of the mechanism:

- Five separate measurements in this repo fail to show our probability beats
  the market's, on any market or window
  (`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`): team model +0.004 nats over a
  base rate, prop model +0.0133, a head-to-head paired log-loss difference
  whose 95% interval spans zero with a blend curve that worsens monotonically
  away from zero weight on our number, two betting probes with no finding, and
  a card-rule backtest whose intervals are 20 to 75 points wide.
- Every populated bucket of the only live reliability table we have is
  overconfident: 50-60% by +3.8 points (n=212), 60-70% by +4.8 (n=361),
  70-80% by +18.3 (n=27) (`docs/PROP_CALIBRATION_2026-09-14.md`).
- The slice that most resembles what a value score surfaces first, contracts
  where our number sat 10 or more points above the market's, is the worst
  measured: 40.6% actual against a 62.1% claim, n=32, on settled outcomes.
- **Nothing on disk measures our probability below 0.50 at all.** Every
  calibration table this repo has built scored only the side we favour, which
  by construction sits at or above 0.50. A bet where our own number reads 41%
  has never been compared against a result anywhere in this project. The band
  the owner now wants most is the one band that has never been checked.
- The arithmetic is one-sided. Expected value lost per point of overstatement
  equals the decimal odds: 1.62% at -160, 2.00% at +100, 3.00% at +200, 3.50%
  at +250. The same error costs about 2.2 times more at the long prices he
  wants weighted most heavily than at the short ones the draft favoured.

The design does not refuse the direction. It answers it with mechanisms that
stay inside the evidence rules, each named where it lives: a fixed markdown of
our number registered in advance and never fitted (section 4); a required edge
that grows with the price (section 4); a hard floor under our own number
(G6, which on a **pick** is dominated by that required edge at every price G4
allows, in **both** classes, and does work of its own only on a **fill**,
stated in G6 and measured in 4.5 and 4.6 rather than claimed as a live
protection it is not); an unchanged
disagreement cap (G8); a new price ceiling (G4); a new
refusal of line shopping (G13); a small cap on how many plus-money picks a card
may hold (G14); and a separately graded, separately floored, separately
retired record for the plus-money class (11.1, 11.4, 11.7). What it cannot do
is manufacture the sample that would settle the question: see 11.4, which
states in the evaluation plan itself how long that is.

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

Every number in the model, **and every constant in this rule**, that was fitted
or measured on game or contract results, with its window. The rule's own
constants are the last three rows; they are not model parameters, and they are
in this table because a reader checking what was measured on outcomes should
find all of them in one place rather than only in the sections that derive
them. Counted on 2026-09-15 on this machine's stores with each fit's own
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
| `MARKDOWN = 0.038` | The markdown taken off our number before G7, before the score and before the figure shown on the card | Props settled 2026-09-08 to 09-12: the 50-60% reliability bucket, n=212, predicted 0.5712 and hit 0.5330, +3.8 points (4.1) | None. Forward dates before registration, never counted (11.1) | `docs/PROP_CALIBRATION_2026-09-14.md`, section 4.1 |
| `BASE_EDGE = 0.010` | The edge G7 requires on top of break-even at the base price, scaled with the decimal odds | The same document, window and table: the spread between the 50-60% bucket (+3.8, n=212) and the 60-70% bucket (+4.8, n=361) (4.2) | None. Forward dates before registration, never counted (11.1) | `docs/PROP_CALIBRATION_2026-09-14.md`, section 4.2 |

Not fitted, and listed so that "no fitted number" is never read as "no sealed
game": the run model's inputs at call time (each club's 2026 runs scored and
allowed, starter logs, relief rates, league runs per game, the FIP constant)
and the prop board's season rates are read point in time from 2026 stores that
include games dated 2026-01-01 to 08-27. They are inputs to a prediction about
a later game; no result chooses a parameter through them. The model's other
constants are published or fixed in advance (`strength.py:101-131`,
`playerprops.py:88-112`, `GAME_REGRESSION` at `:318`).

Our number drives G6, G7, G8 and the score of section 4, so on the design board
every V2 pick rested on the first three rows of this table. The markdown of
section 4 reduces what our number is allowed to claim; it does not change where
our number comes from.

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

**Price class.** Every candidate carries a `price_class`, fixed by its price
alone and frozen on its row: `MAIN` when `-160 <= price <= -100`, `PLUS_MONEY`
when `+100 <= price <= +250`, and no class at all outside those two ranges, in
which case it fails G4 and is neither a pick nor a fill. American odds take no
value between -99 and +99, so inside G4's band the two classes are exhaustive
and cannot overlap, and G4 is exactly the test that a candidate has a class.
Three gates read the class (G5, G6 and G14); every other gate is the same for
both.

| Gate | Test | Moneyline and run line | Player prop |
|---|---|---|---|
| G1 Not started | First pitch strictly after the publish instant, fail-closed (`src.report.card._has_started`) | yes | yes |
| G2 Books | Books quoting this exact selection at the board | at least 6 (`prices.MIN_BOOKS`) | at least 2 (`propboard.MIN_BOOKS`) |
| G3 Fresh | `publish instant - observed_utc` of the quote; a missing or unparseable `observed_utc` fails | at most 3,600 seconds (`grade.FRESH_SECONDS`) | at most 3,600 seconds (`grade.FRESH_SECONDS`) |
| G4 Price band | `-160 <= price <= -100` or `+100 <= price <= +250`. The short end is unchanged (owner, 2026-09-15: "-160"). The long end is new (owner, 2026-09-16: "+100 to +250"); section 4 says why the ceiling exists and why it is there | yes | yes |
| G5 Market band | `MAIN`: market number `> 0.50`, unchanged. `PLUS_MONEY`: `0.20 <= market number < 0.50`, an underdog by the market's own de-vigged number, not a side the market itself calls near-impossible | yes | yes |
| G6 Our floor | `MAIN`: our number `> 0.50`, unchanged. `PLUS_MONEY`: our number `>= 0.30` (owner's own number, 2026-09-16: "confidence of 30-45+ percent"). Read on the **raw** model or prop-board number, before the markdown of section 4, and applied to a fill exactly as to a pick. **On a pick neither floor can bind at any price G4 allows**: G7 already demands a raw number of 34.53% at the +250 ceiling, 45.34% at +150, 55.03% at +100 and 66.34% at -160 (4.6), so the smallest number G7 accepts anywhere in the plus-money band is 34.53%, above this gate's 0.30, and the smallest anywhere in the main band is 55.03%, above this gate's 0.50. Both floors are strictly dominated on the pick path. They bind only on a **fill**, which is allowed to fail G7, and on the design board that is exactly where the plus-money floor fired (4.5). It is registered as the owner's own floor and stated here as dominated, rather than listed as a protection that cannot fire on a pick, for the same reason section 4 declines to register a score cap | yes | yes |
| G7 Value test | `our number - MARKDOWN >= breakeven(price) + required_edge(price)` (section 4). Replaces the draft's `our number > breakeven(price)` and is never weaker than it at any price | yes | yes |
| G8 Disagreement cap | `abs(our number - market number) <= 0.10`, on the **raw** numbers. Unchanged, both classes, on purpose | yes | yes |
| G9 Calibrated | the frozen parameter file of 11.2 is loaded with its `sha256` as registered, and holds the moneyline calibration (for a moneyline) or the run-line cover calibration (for a run line). A candidate failing G9 is neither a pick nor a close call | yes | not applicable |
| G10 Prop data | `season_games >= 15` (`daily_card.MIN_SEASON_GAMES_FOR_PRELINEUP`; missing `season_games` fails). **The lineup test is removed** (owner, 2026-09-16: "No, allow earlier"); whether a lineup is posted is a disclosure on the entry's face, not a gate (section 8, copy C15) | not applicable | yes |
| G11 One per game or player | At most one entry per game across moneyline and run line; at most one entry per player on props; picks and fills (section 6) count alike, and both classes count alike, so one game never holds a `MAIN` entry and a `PLUS_MONEY` entry at once; a game that already has a locked game entry takes no other game entry. **Applied before G14 and G12** (section 5) | yes | yes |
| G12 Ceiling | At most **10 entries on the date in total, picks and fills together**, locked entries included (owner, 2026-09-16 about 00:45Z, replacing the draft's ceiling of 10 picks that let 13 be listed). A day with 10 picks shows no fill; a fill already shown holds one of the 10 | yes | yes |
| G13 No line shopping | `market number <= breakeven(price)`. A candidate whose own de-vigged consensus already clears its best available price is refused outright: that is a disagreement between books, which the owner ruled out (2026-09-10, 2026-09-11) and which section 4 already refused in prose. New, made a gate so no future board can produce such a pick | yes | yes |
| G14 Plus-money sub-cap | At most **3** of the card's entries are `PLUS_MONEY` **picks**. Applied after G11 and before G12, dropping the lowest-scored plus-money picks beyond the third. Fills are not counted against it (a fill carries no verb and enters no counted-pick record). Default, owner question 9 | yes | yes |

A **fill** (section 6) is not a pick and does not pass every gate. It must pass
G1, G2, G4, G5, G6, G8, G9, G10 and G13, have our number available, and fail at
least one of G3 and G7. It is labelled as not a pick and says which check it
failed. Two of those are deliberate strengthenings of the draft, which let a
fill fail G6 or G8: the probability floor is the owner's own floor and a floor
that bound only picks would publish an entry he said should never be published
at all, and G8 is the one gate built from a direct measurement of harm, so the
floor of three must not put the measured-worst tail on the public record.

Where the gate constants come from: 0.50 (G5, G6, `MAIN`) is the owner's "more
than likely" (2026-09-11), kept where he did not supersede it; 0.30 (G6,
`PLUS_MONEY`) and the +250 ceiling (G4) are his own words of 2026-09-16; -160
(G4) is his 2026-09-15 word, confirmed the same day against -150 (question 4);
10 entries (G12) is his 2026-09-16 00:45Z answer; 0.20 (G5, `PLUS_MONEY`) and 3
(G14) are this draft's, stated as defaults and put to him as question 9;
6, 2, 3,600 and 15 are the existing repo constants named in the table. An
earlier draft used 4 books and 25 games for props; neither had a source, and
25 would have shut props out of every 2026 pick, because `season_games` counts
a batter's prior rows in `data/processed/boxscores_2026.jsonl`, which starts
2026-08-30 (on 2026-09-15 no batter had more than 15; the season ends
2026-09-27). With 15, props rest on 15 to about 27 games of history in 2026.

Where G8 comes from, and why it is not loosened for the class the owner is most
enthusiastic about: `docs/PROP_CALIBRATION_2026-09-14.md`, where prop
contracts with our number 10 or more points above the market's hit 40.6%
against our stated 62.1% (n=32; 25 of the 32 rows, 78%, from one date). That
is a **prop-only, mostly single-date** measurement of the 10-point-and-over
tail. It is not evidence about game markets, and nothing on disk measures the
band from 0 to 10 points; the same document found the market's own number
tracked results at least as well as ours on every cut. G8 removes the tail the
measurement flagged; it does not show the band below it is safe (section 4).
It is measured in exactly the direction a plus-money pick runs, our number
above the market's on the side we want to bet, so loosening it for that class
would be loosening the one gate built from the one measurement that warns
against it. EXPLORATORY, on the already-seen design board: 12 of all 112
candidates exceed the cap, of which 10 sit inside G4's price band and are
refused by G8 (the other 2 fail G4 first). Three of the twelve are tied at the
board's largest gap, 16.9 points, and one of those three is the entry shadow A
puts at the top of its list: Rockies run line +1.5 at +106, market 46.9%, our
raw number 63.8%, a gap larger than the tail the measurement flagged. It is
also the gate the card is most
sensitive to: at a cap of 0.06 the same board yields no picks at all
(section 4's sensitivity table).

## 4. The score: one number for the value test and for the ranking

The owner asked for "an algorithm of value x confidence" and for that same
number to decide what goes at the top of the card (2026-09-16, section 0.1).
This is it, with every constant fixed here and justified here.

```python
from src.core import odds

# Registered constants. Each is fixed at REGISTERED_UTC and comes from the
# owner's words, from an existing repo constant, or from one prior measurement
# cited beside it. None is fitted: this rule has produced no outcome, and no
# result it later produces may move any of them (11.7). A different value is a
# new rule id.

MARKDOWN   = 0.038    # fixed markdown of our own number (4.1)
BASE_EDGE  = 0.010    # required edge at the base price (4.2)
BASE_PRICE = -160     # shortest price allowed; leverage 1.0 here by definition
BEST_PRICE = 250      # longest price allowed (4.3)

def marked_down(our_probability):
    """Our number after the registered markdown. The value test, the score and
    the 'our number' figure shown on the card all read this. G6's floor and
    G8's cap read the RAW number, because one is the owner's floor on our own
    confidence and the other is a cap on how far our raw number may sit from
    the market's."""
    return max(0.0, our_probability - MARKDOWN)

def required_edge(price):
    """Edge required on top of break-even, growing with the decimal odds
    because the same probability error costs proportionally more at a longer
    price: expected value per unit is p*d - 1, so it loses exactly `d` per
    point of overstatement."""
    return BASE_EDGE * (odds.american_to_decimal(price)
                        / odds.american_to_decimal(BASE_PRICE))

def passes_value_test(our_probability, price):                          # G7
    return marked_down(our_probability) >= (
        odds.american_to_probability(price) + required_edge(price))

def score(our_probability, price):
    """Value times confidence, as a Kelly fraction on the marked-down number:
    the share of a bankroll this confidence at this price would justify.
    RANKING KEY ONLY -- computed only for a candidate that has already passed
    every gate, so a high score never rescues a candidate a gate refused. No
    stake size is ever published, grading is flat 1 unit (section 9), and any
    positive constant multiple of this key gives the same order, so no
    fractional-Kelly multiplier and no score cap is registered: neither would
    change a selection or an order, and listing one as a safeguard would credit
    a protection that cannot fire."""
    d = odds.american_to_decimal(price)
    p = marked_down(our_probability)
    return p - (1.0 - p) / (d - 1.0)
```

`breakeven(price)` is `odds.american_to_probability(price)`, which is `1/d`,
vig included. So `score > 0` exactly when the marked-down number is above
break-even, and G7 requires it to be above break-even by `required_edge`;
every pick therefore has a positive score by construction, and the score can
never order a candidate the value test refused.

### 4.1 Where MARKDOWN = 0.038 comes from

`docs/PROP_CALIBRATION_2026-09-14.md`'s reliability table for our own number,
on 1,200 settled contracts from 2026-09-08 to 09-12: the 50-60% bucket
predicted 0.5712 and hit 0.5330, **+3.8 points overconfident, n=212**. It is
the least extreme of the two adequately populated buckets; the other, 60-70%,
is +4.8 points at n=361, and both are used again in 4.2.

Three numbers in the same document are deliberately **not** used to size it.
The 70-80% bucket (+18.3 points) has n=27. The 10-point-and-over disagreement
tail (+21.5 points) has n=32 with 78% of its rows from one date, and it already
sizes G8; using it twice would count one protection as two and would leave the
typical case, which the markdown exists for, unaddressed. The market's own
overconfidence on the same table is not used at all, because the markdown
corrects our number, not the market's.

What this is not: the window it was measured on (2026-09-08 to 09-12) is
forward, not sealed and not tuning, so using it is not a sealed-window breach;
but it is forward-window evidence informing a design choice before the read
date, exactly as G8's own source already is, and the same caveat applies. And
it was measured on props, on the side we favour, so **every application of it
below 0.50 is a transfer, not a measurement** (0.2 and 11.9).

### 4.2 Where BASE_EDGE = 0.010 comes from

The spread between the two adequately populated measured figures: 4.8 minus
3.8 is 1.0 point. It stands for how uncertain the markdown itself is. It is not
a standard error and is not called one; it is a fixed, published, unfitted
number of the right order, used as the margin at the base price and scaled up
with the decimal odds so that the probability bar itself, not only the expected
value bar, rises with the price.

The bar a candidate's **raw** number must clear over break-even, and the
overstatement a pick at that bar can absorb before its expected value turns
negative (they are the same number, because expected value is zero when the
true probability equals break-even):

| Price | decimal | `required_edge` | total raw edge needed | EV lost per point of error |
|---|---:|---:|---:|---:|
| -160 | 1.625 | 1.00 pt | **4.80 pt** | 1.62% |
| -140 | 1.714 | 1.05 pt | **4.85 pt** | 1.71% |
| -114 | 1.877 | 1.16 pt | **4.96 pt** | 1.88% |
| -100 | 2.000 | 1.23 pt | **5.03 pt** | 2.00% |
| +110 | 2.100 | 1.29 pt | **5.09 pt** | 2.10% |
| +150 | 2.500 | 1.54 pt | **5.34 pt** | 2.50% |
| +200 | 3.000 | 1.85 pt | **5.65 pt** | 3.00% |
| +250 | 3.500 | 2.15 pt | **5.95 pt** | 3.50% |

Read plainly: the design tolerates 4.8 points of overstatement in our raw
number at -160 and 5.95 at +250 before a pick that is exactly at the bar turns
negative. The one error this repo has actually measured on a similar slice is
21.5 points. If the real error in the plus-money band is anywhere near that,
these picks lose money and no threshold here stops them quickly; what stops
them is the harm check of 11.4, and the owner is told so in plain words.

### 4.3 Where BEST_PRICE = +250 comes from

It is the top of the owner's own named range ("+100 to +250"), and it is the
longest price this repo has ever looked at with our own number: the 138-row
design board tops out at **+206** on the game side and never reaches plus money
on any prop, and the paper-trading accounts report only a pooled ">+100"
bucket. Past it the arithmetic is monotone worse in both directions that matter
(expected value lost per point of error keeps rising with the decimal odds,
and the sample needed to tell the band apart from noise keeps rising with it
too, 11.4), and no owner word asks for anything longer. On the design board
the ceiling refused nothing, so it is precautionary there, not the thing doing
the excluding.

### 4.4 What the value test does in practice

The market's number is not required to clear `breakeven(price)`; G13 now
refuses a candidate whose number does. That is a disagreement between books,
which is line shopping. On the design board it happened on 0 of 112 candidates,
so G13 refused nothing there and exists so that no future board can.

When the market's number is below break-even, which was every candidate on the
design board, a candidate passes G7 only if our raw number is above the
market's by more than the vig gap (`breakeven - market number`) plus the
markdown plus the required edge. So G7 is still a disagreement threshold, now a
higher one, and every pick sits in a band from that threshold up to G8's 10
points. EXPLORATORY, measured on the design board, the vig gap and the width of
that band. "Max raw edge" is `0.10 - mean vig gap`, the most a candidate in
that band could carry without breaching G8; "bar" is `MARKDOWN +
required_edge` at the reference price named beside the band, because the bar
varies with the price inside a band:

| Band | n | mean vig gap | max raw edge under G8 | bar (at) | window |
|---|---:|---:|---:|---:|---:|
| -160..-110 | 33 | 2.56 pt | 7.44 pt | 4.87 pt (-135) | **2.57 pt** |
| -109..-100 | 2 | 1.21 pt | 8.79 pt | 5.00 pt (-105) | 3.78 pt |
| +100..+150 | 17 | 0.89 pt | 9.11 pt | 5.18 pt (+125) | 3.92 pt |
| +151..+250 | 10 | 0.51 pt | 9.49 pt | 5.65 pt (+200) | 3.85 pt |

Every band stays reachable, and the narrowest is the main band, not the
plus-money one: the markdown and the required edge eat two thirds of the raw
edge G8 leaves at -135. That is a real cost of marking our number down while
keeping the disagreement cap, and it is stated rather than engineered away.
It also says where the design is fragile: the main band would close if the
markdown were raised much above 0.048 or the cap tightened below 0.08.

Model-over-market disagreement is what the 2026-09-09 incident showed selects
the model's own errors. Here it is used as a filter and, through the score, in
the ranking; the markdown is the answer to that, not a denial of it. The hit
rate of the band is unmeasured, so it is watched from the first counted picks
by a pre-registered, one-way harm check (11.4) and published by S2, per class.

### 4.5 Sensitivity of the constants

EXPLORATORY, on the one already-seen design board, G3 set aside, picks by class
(`scratchpad/value_score/final_extra.py`). Published here, inside the
registration, so that nobody has to take on trust that these constants were not
chosen to produce a particular card:

| MARKDOWN (BASE_EDGE 0.010) | 0.028 | 0.033 | **0.038** | 0.043 | 0.048 |
|---|---:|---:|---:|---:|---:|
| MAIN / PLUS_MONEY picks | 3 / 3 | 3 / 3 | **2 / 3** | 1 / 3 | 1 / 3 |

| BASE_EDGE (MARKDOWN 0.038) | 0 | 0.005 | 0.0075 | **0.010** | 0.0125 | 0.015 | 0.020 |
|---|---:|---:|---:|---:|---:|---:|---:|
| MAIN / PLUS_MONEY picks | 3 / 3 | 3 / 3 | 3 / 3 | **2 / 3** | 2 / 3 | 1 / 3 | 1 / 2 |

| G6 plus-money floor | 0.25 | **0.30** | 0.35 | 0.40 |
|---|---:|---:|---:|---:|
| MAIN / PLUS_MONEY picks | 2 / 3 | **2 / 3** | 2 / 3 | 2 / 3 |

| G8 cap | 0.06 | 0.08 | **0.10** | 0.12 | 0.15 |
|---|---:|---:|---:|---:|---:|
| MAIN / PLUS_MONEY picks | 0 / 0 | 1 / 2 | **2 / 3** | 2 / 3 | 2 / 3 |

| G14 sub-cap | 1 | 2 | **3** | 4 | 10 |
|---|---:|---:|---:|---:|---:|
| MAIN / PLUS_MONEY picks | 2 / 1 | 2 / 2 | **2 / 3** | 2 / 4 | 2 / 4 |

No constant is knife-edge: one notch either way on the markdown or the required
edge moves the card by one pick, not from empty to full. Two facts the table
makes plain and this draft does not hide. **G8's cap is the load-bearing
constant**, not the markdown: at 0.06 the board yields nothing at all. And
**G6's plus-money floor of 0.30 cannot change a pick at any allowed price, and
the flat sweep above is arithmetic, not luck.** The smallest raw number G7
accepts is 34.53% at +250 and rises at every shorter price (4.6), so a raw
number between 0.30 and 0.3453 cannot reach a pick anywhere in G4's band
whatever the sweep is set to. The same holds in the main band, where G7's smallest raw number is 55.03% at
-100 and G6's floor there is 0.50, so **neither** of G6's floors can refuse a
pick. Their only live path is a **fill**, which
is allowed to fail G7. On this board that path fired once: of 27 plus-money
candidates exactly one had our raw number below 0.30, Guardians -1.5 at +150 at
29.96%, and G6 is the only gate that keeps it off the fill list. Its
marked-down number of 26.2% is far below that price's 41.5% bar, so G7 refuses
it as a pick, but G7 does not refuse fills. The draft said here that "the value
test would have refused it in any case"; that is true of the pick path and
false of the fill path, and it is corrected rather than left standing, because
the fill path is the whole reason G6 binds fills at all (section 3). The band
above the floor is reachable and was reached: the board's published plus-money
picks include our number at 41.1%, inside the owner's 30-to-45 band, and 4.6
says which part of that band the rule can and cannot serve.

### 4.6 What the owner's direction actually gets, and what it still refuses

- **"+100 to +250 offer really good value."** Published, as the `PLUS_MONEY`
  class, when the price is in band, the market's own number is 0.20 to below
  0.50, our raw number is at least 0.30, the marked-down number clears the
  price by `required_edge`, the raw gap from the market is at most 10 points,
  and the class has a slot left under G14. On the design board 3 of 5 picks
  were plus money.
- **"Confidence of 30-45+ percent if high enough value (+150, +200 etc etc)."**
  Served at the long end of his prices, **shut at the short end, including the
  first price he named**, and he should see which before he registers this.
  What decides it is G7's bar on the **raw** number, which is
  `breakeven(price) + required_edge(price) + MARKDOWN`:

  | Price | +100 | +110 | +125 | +140 | **+150** | +160 | +175 | +200 | +225 | +250 |
  |---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
  | Smallest raw number a pick may carry | 55.03% | 52.71% | 49.63% | 46.94% | **45.34%** | 43.86% | 41.86% | 38.98% | 36.57% | 34.53% |

  So at +150 the 30-to-45 band is closed: a raw number inside it cannot be a
  pick there at any size of disagreement, because the bar is 45.34%. The band
  opens at about +152, is 0.1 of a point wide at +153, 1.1 points at +160, 6.0
  at +200 and 10.5 at +250. The bottom of his band is never reached at all:
  34.53% at the +250 ceiling is the smallest raw number this rule can publish
  anywhere, so "30 per cent" is outside it at every allowed price. What the
  rule serves is the upper part of his range at the longer half of his prices.
  Reached on the design board: the Athletics moneyline at +202 is a pick with
  our number at 41.1%, and the Reds moneyline at +206 at 41.4% was dropped only
  because G11 gave that game to a higher-scored entry. Of 27 plus-money
  candidates 15 had our number in that band, and 1 of those 15 became a pick.
  Opening the band at shorter prices means cutting `MARKDOWN` or `BASE_EDGE`;
  both are fixed here, neither is moved to reach a band, and a different value
  is a new rule id (section 4, 11.7). If he wants the short end of his band
  open, that is a decision to take before registration, not an adjustment
  afterwards.
- **"The underdog actually makes more sense than the favorite."** Published
  when the disagreement is inside G8 and the market is not calling the side
  near-impossible; the two run-line picks on the design board are exactly this
  case, our number calling a side outright likely that the market prices as the
  underdog.
- **Still refused, whatever the score.** Anything outside -160 to -100 or +100
  to +250 (G4). Anything more than 10 points from the market's own number
  (G8), a deliberate refusal of the version of his favourite trade where our
  raw number alone carries the whole gap, because that is the one slice the
  repo has measured and it measured 40.6% against a 62.1% claim. Anything the
  market itself prices below 0.20 (G5). Anything our own raw number puts below
  0.30 (G6), though the credit for that refusal belongs to G7, which refuses
  everything below 34.53% first at every allowed price; G6's own work is on
  fills, and it is listed here as the owner's floor rather than as a live check
  on a pick. Anything whose market number already clears its own best price
  (G13). None of these has an exception for a large score.

## 5. Ranking

Owner question 8 is answered, 2026-09-16 about 00:50Z: "again based on
cionfidence x value alrogirthm that we need to dial in". So the score of
section 4 is the ranking key, and the draft's price-first key is superseded
along with the directive behind it (0.1).

Picks are ordered by, in turn, on unrounded numbers:

1. `score(our number, price)`, **descending**;
2. `abs(our number - market number)`, ascending (the smaller disagreement
   first, so a tie is broken toward the candidate leaning less on our own
   number);
3. books quoting, descending;
4. first pitch, ascending;
5. the bet sentence, alphabetical.

No key uses a comparison between books, and no key uses price alone or the
market's number alone. **Both classes are ranked together in one list**, so a
plus-money pick can top the card when its score is highest; each entry carries
its class on its face (copy C14) and the two are graded apart (11.1). Whether
he would rather see plus-money picks grouped in their own section below the
main picks is question 10; until he answers, they are interleaved, because
interleaving is what his own answer to question 8 says.

**Order of operations, which matters and is fixed here.** Gates G1 to G10 and
G13 first, on each candidate alone; then the score on the survivors; then the
rank above; then **G11** dedup in rank order (one entry per game or player,
higher score kept); then **G14** (drop the lowest-scored plus-money picks
beyond 3); then **G12** (cut to 10 entries); then fills to the floor of 3
(section 6). Applying G14 before G11 would drop a plus-money pick that dedup
was about to remove anyway and leave a slot unused; the illustration of
section 14 is run in the order given here.

Locked entries count toward G12 and G14, so provisional candidates compete for
the slots that remain. The served order applies the same key to every pick on
the date, locked or provisional, using each pick's own frozen numbers.

Fills are not ranked by this key and never mix with the picks: they are ordered
by the close-call order of section 6 and are listed below every pick.

## 6. Pick count, the floor of three, fills, thin days and stale boards

- **Floor: 3 entries. Ceiling: 10 entries in total, picks and fills together.**
  The card lists three bets on every day whose board offers three candidates
  past G1, G2, G4, G5, G6, G8, G9, G10 and G13 (owner, 2026-09-15: "Always
  show 3"), and fewer, down to none, on a board that offers fewer (the "Fewer
  than 3 entries" bullet below). It never lists more than ten (owner,
  2026-09-16 about 00:45Z). The rule never adds a **pick** to reach the floor
  and never relaxes a gate on a thin day. The floor is met by **fills**, which
  are not picks, say so on their face, and go on the record.
- **Close calls.** A candidate that passes G1, G2, G4, G5, G6, G8, G9, G10 and
  G13, has our number available, is not a pick, and fails G3 or G7 is a close
  call. G3 is not required of a close call, so a prop whose only price is the
  pre-lineup capture can still qualify; every close call shows how old its
  price is (copy C6). Close calls are ordered by: fewest failed checks; then
  shortfall `max(0, breakeven(price) + required_edge(price) - marked_down(our
  number))`, ascending; then **score, descending**; then books quoting,
  descending; then first pitch; then the sentence. The score key matters
  because on a stale board every candidate fails G3 alone and has zero
  shortfall, so without it the order would fall through to a tie-break with no
  bearing on the bet.
- **Fill.** A fill is the highest-ranked close call in that order, added only
  while the entries currently shown for the date, picks and fills together,
  number fewer than 3. A withdrawn entry is not shown, so it holds no slot. At
  most one entry per game or player across picks and fills (G11), and no fill
  for a game or player that has a pick. Because a fill passes G4 it is never
  priced shorter than -160 or longer than +250; because it passes G5, G6 and
  G8 it is never a side the market prices below 0.20, never below the class's
  floor on our own number, and never more than 10 points from the market's
  number; because G3 is not required of it, a fill may rest on a price last
  checked more than an hour ago, and it says so on its face (copy C6). A fill
  carries its class like a pick and is graded on that class's fill line (11.3,
  F1). G14 does not apply to fills.
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
  it passes G1 to G14, it is a pick, and it locks, is graded and is counted as
  a pick in its class. A pick never becomes a fill: a pick that fails a gate on
  a fresh read is withdrawn under L3 and is still graded as a pick. A fill that
  would become a plus-money pick when G14's three slots are already taken stays
  a fill and is graded as one; it is not promoted and then dropped.
- **A fill once shown stays.** Picks appearing later in the day do not remove
  it. It is carried, locked and graded like a provisional pick, and is
  withdrawn only as L3 withdraws a pick: on a fresh read that fails it on G1,
  G2, G4, G5, G6, G8, G10 or G13, or when G11 gives its game or player a pick.
  So a day that begins thin can end with three fills beside several picks, and
  all of them are graded. At most 3 fills are shown at any one time; a withdrawn
  fill frees its slot, so a date with withdrawals can put more than 3 fills on
  the record, each graded at its last shown version and each reported in D3.
- **The card's maximum: 10 entries, answered.** The draft's G12 counted picks
  only and kept a fill once shown, so it could list 13 bets at one time, more
  than the "3-10 bets" the owner named on 2026-09-15. He was asked and answered
  on **2026-09-16 about 00:45Z: cap the card at 10 listed bets in total, picks
  and fills together.** G12 now counts every entry. The consequence he chose,
  written down here because it is the cost of his answer: on a day that begins
  thin and then fills with picks, a bet that passed every gate can be refused a
  slot because a fill already shown is holding one. The rule does not withdraw
  a published fill to make room, because that would remove a bet already shown
  to readers; it declines the eleventh entry instead, and D4 counts every date
  where that happened. At 10 picks no fill is added at all.
- **Fewer than 3 entries.** If fewer than 3 candidates pass G1, G2, G4, G5, G6,
  G8, G9, G10 and G13 with our number available, the card shows fewer and says
  so in one plain line (copy C13). It never relaxes a gate to reach three. This
  is not only a capture failure: on a small slate every favourite can be priced
  shorter than -160 and every underdog longer than +250 (failing G4), or every
  candidate can sit more than 10 points from the market's number (failing G8),
  so the board itself can offer fewer than three candidates, and with no
  qualifying prop the card can show none at all. That state is published as a
  count, never filled.
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
  section holds the fills, and is absent when the day has none. Both classes
  sit in the first section, interleaved by score (section 5); a plus-money
  entry is not a chip or a grade but a sentence on its own face (copy C14)
  saying the market makes the side the underdog, that our number after the
  markdown is still above what the price needs, and that these are kept on
  their own record. **That sentence never says our number makes the side more
  likely than not**, because on most of this class it does not: on the design
  board every plus-money entry showed a number below 50% (14.2). A prop entry
  with no posted lineup carries copy C15 on its
  face. Neither line may sit behind a "View breakdown" control.
- **Headline-verb rule.** The sentence begins "Take" if and only if the entry
  is a pick **and the newest publish run's read of that selection is fresh
  (G3) and passes G1 to G14 there**, which includes the newest best price
  inside G4 and the marked-down number clearing that price's break-even by the
  required edge (G7). This holds for
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
  number after the markdown; and the sentence saying that the market's number
  is below what the price needs, that ours is above it after being marked down
  for how much it has run high in the past, and that our number has not been
  shown to beat the market's. Because G13 refuses any candidate whose market
  number already clears its own price, the draft's second form of that
  sentence ("both numbers are above what this price needs") can no longer
  occur and is removed. Neither line may sit behind a "View breakdown"
  control. That disclosure is mandatory; it is not a reason to withhold "Take".
  **The owner answered question 7 on 2026-09-16 about 03:10Z, "Yes, publish
  with the line."** So the pairing is his own condition, not this draft's
  default: "Take" may rest on our own number clearing the price because the
  line ships with it. Removing the line, moving it behind a control, or
  shortening it so it no longer says our number has not been shown to beat the
  market's breaks the condition he attached to his own yes, and is not a copy
  change but a change to what he agreed to.

## 8. Props safeguards (collected)

**Owner answer, 2026-09-16 about 00:50Z, question 2: "No, allow earlier."**
Asked whether a prop may become a pick only after its lineup is posted, roughly
the last 2 hours before first pitch, he answered no. **The lineup test is
removed from G10.** A prop may be a pick before its lineup posts, priced off
the batter's season-average plate appearances, exactly as the live V1 card
already does it (`src/report/card.py:717` calls
`daily_card.select_props(..., require_lineup=False)`; the season-average path
and its 15-game guard are `src/analysis/daily_card.py:1274-1280`). Keeping the
test would have made V2 stricter on props than the product running today,
against a direct answer, so the change is recorded here on its own line and in
0.1, not folded into the score.

The safeguards that remain, none of which is about lineups: market in
`batter_hits` or `batter_total_bases` (`daily_card.PROP_MARKETS`); at least 2
books (`propboard.MIN_BOOKS`); **at least 15 games of history**
(`daily_card.MIN_SEASON_GAMES_FOR_PRELINEUP`), which is the whole of G10 now;
one pick per player (G11); G5, G6, G7, G8 and G13 as for games; props are not
in the primary metric because no prop on the design board had 6 books (11.3).

**The disclosure stays and becomes mandatory on the face.** Every prop entry
says whether a lineup is posted. When none is, it carries copy C15: no lineup
is posted yet for that game, and plate appearances are priced off the batter's
season average rather than his spot in the order. That line is on the card
face, not behind a control, on a pick exactly as on a fill.

What a reader sees now: batter props are captured twice per game, once 5 to 7
hours before first pitch (baseline, before lineups) and once 0 to 2 hours
before (gate, after the lineup for about 85% of games;
`src/pipeline/batter_props.py:25-30`, `CAPTURE_LEAD_MINUTES = 120`). Under the
draft, a prop could be a pick only from a fresh read after its lineup posted,
which meant the gate capture. Under this answer it can be a pick from the
baseline capture too, for about the first hour after it, while G3 still holds;
after that hour it is a close call failing G3, as any stale game bet is. The
practical effect is that props reach the card earlier and more often, which is
what he asked for, and that a prop pick can rest on a price about an hour old
and on a plate-appearance estimate that a posted lineup would sharpen.

EXPLORATORY, the size of the change on the already-seen design board
(`scratchpad/value_score/final_extra.py`, `final_verify.py`): of 56 prop
candidates, 37 are outside G4's price band, 0 reach plus money at all, and 0
have a posted lineup; 19 pass G2 and G4; of those, 13 fail G10's 15-game floor
(2 of the 13 also fail G8), leaving **6 eligible where the draft's lineup test
left 0**. One of the six becomes a pick with G3 set
aside (Michael Harris II under 1.5 total bases at -148), and it is the only
prop the rule publishes on that board (section 14).

## 9. Lock, withdrawal and grading

Fills (section 6) follow every rule here, with the gates a fill must pass
(G1, G2, G4, G5, G6, G8, G9, G10, G13) in place of G1 to G14, and are graded on
the record apart from the picks and apart by price class.

- **L1.** A pick is provisional until the first publish run at or after first
  pitch minus 4 hours (`card_ledger.LOCK_LEAD_HOURS`). A fill is provisional on
  the same schedule.
- **L2 (as V1).** At that run, a pick on the newest published row locks **as
  last published**: the price, book, both numbers and quote time the reader
  was shown, whatever that run reads (`card_ledger._lock_and_merge`: "the
  reader saw that bet at that price"). A selection not previously shown becomes
  a pick at a run at or after that point only if that run's own fresh read
  passes G1 to G14, and it locks at that run. A fill locks the same way, and a
  selection not previously shown becomes a fill at such a run only if that run
  reads it as a close call and the floor of 3 is still short at that run. If no publish run happens at or
  after first pitch minus 4 hours (the capture chain was down), the pick as
  last published is graded, and counted as "graded without a lock run" (D4).
- **L3 (withdrawal).** Before its lock, a provisional pick is withdrawn only
  when a publish run whose read of that selection is fresh fails it on a gate,
  or when G11, G12 or G14 displaces it. A stale read never withdraws a pick
  (section 6). A withdrawn pick is written to the row's `withdrawn` list with
  the run instant and failed gates, carried forward on every later row for the
  date, **graded at its last shown version**, and shown on the record apart
  from locked picks (R5). A withdrawn selection that passes again before its
  lock returns as the same pick and is graded once, at its last shown version;
  the withdrawal stays in the ledger history. Withdrawn picks do not hold a
  G11, G12 or G14 slot after withdrawal. A provisional fill is withdrawn only
  on a fresh read that fails it on G1, G2, G4, G5, G6, G8, G10 or G13, or when
  G11 gives its game or player a pick; picks appearing later never withdraw it, and a withdrawn fill
  is graded at its last shown version like a withdrawn pick.
- **L4.** A locked pick is carried forward verbatim and graded whatever later
  runs read. Its headline verb follows section 7. A locked fill is carried
  forward verbatim, graded, and keeps its label.
- **Grading.** Flat 1 unit at the graded version's price. Game picks by
  `card_ledger.grade_pick` (moneyline winner; run line by margin plus line).
  Props by `card_ledger.grade_prop_pick`. Fills by the same two functions.
  Voids are counted and reported, never dropped. Every graded entry carries the
  class it held at its graded version, pick or fill, **and its `price_class`,
  `MAIN` or `PLUS_MONEY`, frozen from the price it is graded at**, and is
  graded once. No grading number ever adds a `MAIN` entry to a `PLUS_MONEY`
  one (11.1, R5).

## 10. Everything computed on the same days

One list of every rule that screens the same board at the same publish instant.
Each is written every run to its own ledger, locked by its own lock rule and
graded the same way, and none but the published arm is ever shown to a
customer. The **Kind** column is the difference that matters and is fixed here:

- **shadow**: never published to a customer, no promotion path, spends none of
  the multiplicity budget of 17.3. A shadow result informs and is published;
  it can never change the published rule (11.6).
- **family variant**: paper, promotable under the rule of 17.4 and only under
  that rule, charged against the budget of 17.3. Registered in section 17.
- **published**: the arm customers see, which is `DAILY_CARD_BEST_BETS_V2`
  itself and is also arm A1 of the family.

| Rule id | Kind | Definition | Ledger |
|---|---|---|---|
| `DAILY_CARD_BEST_BETS_V2` (A1) | published, and family arm | This registration, with `MARKDOWN = 0.038`, `BASE_EDGE = 0.010` and G14's sub-cap of 3 (sections 3 and 4). It is the incumbent every family comparison of 17.4 is measured against | `evidence/cards_v2.jsonl` |
| `DAILY_CARD_BEST_BETS_V2_VAR_STRICT_NOCAP` (A2) | family variant (paper) | A1 with G14 removed. Nothing else differs (17.1) | `evidence/cards_v2_var_strict_nocap.jsonl` |
| `DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_CAP3` (A3) | family variant (paper) | A1 with `MARKDOWN = 0.0090` and `BASE_EDGE = 0.0024`. Nothing else differs (17.1) | `evidence/cards_v2_var_loose_cap3.jsonl` |
| `DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_NOCAP` (A4) | family variant (paper) | A1 with `MARKDOWN = 0.0090`, `BASE_EDGE = 0.0024` and G14 removed (17.1) | `evidence/cards_v2_var_loose_nocap.jsonl` |
| `DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1` and `DAILY_CARD_PROP_LIKELY_AND_CLEARS_PRICE_V1` (V1) | shadow | The selection logic, constants and lock rule of `src/analysis/daily_card.py` and `card_ledger` exactly as committed at registration, with the calibration file V1 reads. Its nightly refit, which read sealed-window and forward games (section 1.2; diagnosis section 0), was stopped by Brey on 2026-09-15 ("Freeze it now"; record `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`, commit `ba09312c`), before V2's first counted day, so V1's **calibration file** does not change during V2's sample. That is all the freeze delivers: it covers only that file's `a` and `b` and says so in terms. The rest of V1's model and its selection code stay live and editable for a sample the read date puts around August 2027, and 11.2 records 15 commits to the model files in five days and 12 to `src/report/card.py` since 2026-08-28. So V1 is pinned by measurement, not by assumption: every V1 shadow row carries a `v1_code_fingerprint`, the sha256 of `src/analysis/strength.py`, `src/analysis/playerprops.py`, `src/analysis/propboard.py`, `src/report/props.py`, `src/analysis/daily_card.py`, `src/report/card.py`, `src/appstate/card_ledger.py` and `data/processed/card_calibration.json`, with the registration-commit value written into section 16. A row carrying another value is reported under 11.6 with the dates and the commits that changed it, never assumed away. Comment-only, docstring-only and customer-copy-only edits (build plan T10, T10b and the interim V1 copy change) are not a change to V1's selection, and a fingerprint change made only of those is reported as such | `evidence/cards_v1.jsonl` until the cutover date, `evidence/cards_v1_shadow.jsonl` from the cutover date; no date in both |
| `DAILY_CARD_BEST_BETS_V2_SHADOW_A_BAND_ONLY` (A) | shadow | V2 with G6, G7, G8 **and G14** removed; everything else identical, including the markdown inside the score, G11's dedup, G12's ceiling of 10, the floor of 3 and the fill rule. **Why G14 goes too, stated rather than assumed:** A exists to measure what the gates on our own number refuse, and G14 is a cap on the card's composition, not a gate on our number. Left in, it would drop V2's own plus-money picks to make room for the three higher-scored ones G8 refuses, so A would not contain V2's picks and the difference between the two records would stop being "what G6, G7 and G8 refused". What that costs is not hidden: A then differs from V2 in four respects, not three, and its card can be almost all plus money (7 of 10 on the design board, 14.3), so A is not a like-for-like comparison of card shape, only of what those three gates keep out | `evidence/cards_v2_shadow_a.jsonl` |
| `DAILY_CARD_BEST_BETS_V2_SHADOW_C_OTHER_WORST_PRICE` (C) | shadow | V2 with G4's short end set to the other answer to owner question 4: `price >= -150` if V2 registers -160, `price >= -160` if V2 registers -150; the +250 ceiling unchanged; everything else identical | `evidence/cards_v2_shadow_c.jsonl` |
| `DAILY_CARD_BEST_BETS_V2_SHADOW_E_LIKELY_FIRST` (E) | shadow | The superseded rule: the draft's G4 (`price >= -160`, no ceiling), G5 and G6 at 0.50 for every candidate, G7 as `our raw number > breakeven(price)`, G8 unchanged, no markdown, no plus-money class, ranked longest price first. Its ceiling and floor follow V2's (10 entries, floor 3) so the two records are the same shape | `evidence/cards_v2_shadow_e.jsonl` |

A tests whether the gates on our number do anything, and is the one shadow
exempt from G14, for the reason written into its row. C tests the other of the
two worst prices the owner named ("-150 or -160"), which he settled at -160 on
2026-09-15 (question 4). **E keeps the superseded 2026-09-11 directive measured
rather than discarded**, so that "more than likely first, then price" has a
record of its own beside the rule that replaced it. V1 is the rule being
replaced.

A, C and E carry V2's floor of 3, its ceiling of 10 and its fill rule
unchanged, and C and E carry G14 unchanged as well; A is the single exception,
for the reason in its row. So their records are read the same way: picks apart,
fills apart, each class apart, and all together. No shadow result changes the
published rule (11.6). On the design board, G3 set aside, V2 published 5 picks;
A published 10, C 5 and E 2 (14.3).

**Shadow D is deregistered before registration, and absorbed by the family's
loose arms.** An earlier draft of this section registered
`DAILY_CARD_BEST_BETS_V2_SHADOW_D_NO_MARKDOWN`, which was V2 with
`MARKDOWN = 0`, to measure what the markdown costs and what it saves. The loose
arms A3 and A4 measure the same thing, at a bar within 0.74 points of D's at
every price G4 allows, and unlike D they carry a promotion rule, so they answer
the question the owner actually asked instead of only describing it. Two arms
that close together would pick the same card on almost every board and could
never separate, and keeping both would spend multiplicity budget (17.3) on a
comparison that cannot resolve. EXPLORATORY, on the already-seen 2026-09-15
board with G3 set aside: shadow D and arm A3 produce the **identical** 7-pick
card in the identical order
(`scratchpad/variants/shadow_d_vs_loose.py`). What the swap costs is stated
rather than hidden: D was a clean one-factor contrast, markdown only with the
base edge held, and the loose arms move both constants together, because the
owner's own two numbers set both (17.1). This deregistration is permitted
because it happens before `REGISTERED_UTC`, which is the only point at which a
rule in this file may still change at all (section 16).

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

**Counted picks split by price class, and the two halves are never pooled.**
Every counted pick is in exactly one of two populations, by the `price_class`
frozen on its graded version:

- **counted MAIN picks** (`price <= -100`),
- **counted PLUS_MONEY picks** (`price >= 100`).

Every metric in 11.3, every floor and harm check in 11.4, every verdict
condition in 11.5 and every retirement result in 11.7 is computed **separately
for each population**, and no number in this registration adds one to the
other. A third figure over all counted picks together is published as a
description only (D9) and decides nothing: it is never a floor, never a
verdict input, never a comparison. Counted fills split the same way.

Why the split is structural and not a reporting nicety: a plus-money pick is,
by this rule's construction, almost always a case of our own raw number sitting
several points above the market's, which is the one slice this repo has
measured and measured badly (0.2). Pooling the two would let a good main-band
run carry a bad plus-money run past the point it should have stopped, and let a
bad main-band run retire a plus-money class that was doing nothing wrong. That
is the same pooling mistake `card_ledger.record()`'s own docstring warns about,
one level further down.

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
CLV%**, computed **separately for counted MAIN picks and counted PLUS_MONEY
picks** (11.1), by the same machinery, against the same bar. Plus money is
judged by the same measure as everything else, never a softer one. This starts
negative by the pick's vig gap (0.5 to 3.3 points by band on the design board,
section 4.4), so a pick beats the close only if the fair market moves toward it
by more than that. That is the bar `docs/VALIDATION_CRITERIA.md` sets, and
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

**Secondary. Every one of S1 to S6 is computed separately for counted MAIN
picks and counted PLUS_MONEY picks, and never over the two together.**

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
  LOSS, `ECE = sum over bins of (n_bin / N) * abs(mean our number - hit rate)`.
  Bins for `MAIN`: [0.50, 0.55), [0.55, 0.60), [0.60, 0.65), [0.65, 1.00].
  Bins for `PLUS_MONEY`: [0.30, 0.35), [0.35, 0.40), [0.40, 0.45),
  [0.45, 0.50), [0.50, 1.00]. The `PLUS_MONEY` bins are the **first
  measurement this repo will ever have of our own number below 0.50** (0.2),
  which is why they are declared here, in advance, rather than chosen when the
  data arrives. S6 is computed on the **raw** number, not the marked-down one,
  and additionally on the marked-down one, so the record shows both what our
  model claimed and what the rule published.

**Fills, reported apart (F1), and split by class.** Over counted fills,
published beside every number above and never inside one, once for `MAIN` fills
and once for `PLUS_MONEY` fills: n; won-lost-push and units at the graded
prices; ROI; the share beating the close and the mean CLV% computed exactly as
the primary metric computes them for picks; the count by the check each fill
failed (G3, G7); and the count of fills whose
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
than 3 picks, dates with fewer than 3 entries, dates where G12's ceiling of 10
refused an eleventh entry, dates with a stale board at every run, withdrawals
per date,
picks graded without a lock run, picks shown without "Take" after their lock.
D5 knowledge-grade distribution (A to D) of counted game picks. D6 not applied:
`docs/VALIDATION_CRITERIA.md`'s "live vs backtest ECE, drift > 0.04", because
no backtest of this rule exists and none may be run on the sealed window.
**D7 plus money on the card**: per date, the count of `PLUS_MONEY` picks and
fills, their prices, and the count of dates where G14's sub-cap dropped a
plus-money pick that had passed every gate. Reported from pick number one,
because `evidence/cards_v1.jsonl` has never carried a single row priced at plus
money, published or settled, win, loss, push, void or locked (diagnosis 4.3),
and the day that stops being true should be visible in the record.
**D8 props before the lineup**: per date, the count and share of prop picks and
prop fills whose `lineup_posted` was false at their graded version, and the
count of prop picks whose plate appearances came from the season-average path
rather than a batting slot. The owner's answer of 2026-09-16 turned this from
impossible to normal (section 8), so it is counted from the first day.
**D9 all counted picks together**: n, won-lost-push, units and ROI over `MAIN`
and `PLUS_MONEY` together. Shown to readers as the card's overall record and
used for nothing else: it is never a floor, never a verdict condition, never a
harm-check input and never a comparison statistic.

### 11.4 Floors, the harm check, the read date and the stop date

**Each class reads its own verdict, at its own floor, and neither waits for
nor rescues the other.** One read per class, at the first settlement run after
which **both** hold for that class. Counted picks of that class only; no fill
counts toward either floor, however many fills the card publishes:

- (a) at least 300 counted game picks of that class with a CLV%; and
- (b) at least 300 counted picks of that class graded WIN or LOSS, across at
  least 60 distinct slate dates.

The plus-money class gets **no smaller floor than the main band**. Pooling the
two to reach 300 faster would let a good main-band run mask a bad plus-money
one, which is the one thing the split exists to prevent.

Before a class's floors are met the read script prints `PENDING` for that class
and the counts, with no interval and no direction. **There is no early verdict
and no continuation after the read.** The record page shows V2's running
win-loss and units every day (R5); that is a record, not a read, and it is not
a verdict. Per-pick closing measurements may be written to the ledger as they
settle, but nobody summarises CLV%, S2, S4, S5 or S6 over counted picks before
the read, except the harm check below.

**How long the plus-money class will read `PENDING`, stated here rather than
in a footnote.** At the rate the one already-seen board produced (3 plus-money
picks of 36 base-eligible candidates on a full slate, and 0 props able to reach
plus money at all), 300 counted plus-money picks is a matter of one to several
years, on top of the main band's own read, which already falls around August
2027 (below). And a verdict on the class is a weaker question than the one the
owner is really asking. Telling a plus-money class apart from a favourite class
at a true ROI gap of 3 to 5 points needs, under a flat 1-unit bet and the
variance a fair price implies (`Var = d - 1`), **6,952 to 19,311 bets in the
plus-money band alone** for a two-sample read, and 4,710 to 13,082 to tell the
plus-money band apart from zero
(`scratchpad/value_score/power_calc.py`, reproducing the method of the
diagnosis 4.4). At 300 counted picks the 95% interval on ROI is about plus or
minus 13.9 points at +150, far wider than the gap in question. **This is not a
reason to lower the floor.** It is a reason to expect `PENDING` from the
plus-money class for a long time, to say so to the owner in plain words before
the first plus-money pick is published, and to treat the harm check below, not
the verdict, as the check that will actually fire on this class. It is also the
reason the registration requires the already-registered SR1 read
(`docs/RESEARCH_STRATEGY_REPLICATION.md`, "home underdog, moneyline price band
+100 to +150", READY_UNTESTED, zero rows read) to be run and published before
the first plus-money pick is shown (status line, build plan T0c): it reads the
same idea on its own purpose-built sample instead of waiting on this card's
volume.

**Harm check (one-way, pre-registered, cannot be rescued). Run independently
for each class, at the same thresholds.** Run once per class at each threshold
and published with its counts. Counted picks of that class only; a fill neither
triggers it nor delays it:

- at the first settlement run after 100 counted game picks of the class have a
  CLV%: if the share beating the close is below 50% **and** the 95% bootstrap
  interval of mean CLV% (over slate dates, 10,000 resamples, seed 20260915) is
  entirely below zero;
- at the first settlement run after 50 counted picks of the class graded WIN or
  LOSS have our **raw** number at least 3 points above the market's: if the 95%
  Wilson interval on their hit rate lies entirely below the mean break-even of
  their graded prices.

**The second arm is the plus-money class's real tripwire, and it is read that
way on purpose.** Because a plus-money pick is, by this rule's construction,
almost always a case of our raw number sitting several points above the
market's, the plus-money class reaches that arm's 50-pick threshold in far
fewer picks of its own than the main band does, and far sooner in calendar time
than any 300-pick floor. That is not tuned to happen; it falls out of what the
class is. It is the earliest honest signal this design can produce that the
0.30-to-0.45 band behaves the way the adjacent measured prop tail (40.6%
against a 62.1% claim) suggests it might.

If an arm fires for a class, the result is `HARM_STOP` **for that class only**:
from the next publish day V2 keeps selecting, locking, grading and counting
that class under this id, so the registered read still happens, and the floor
of 3 and the fill rule keep running with their labels, but **no entry of that
class carries "Take"** and the card uses copy C11 in the form for the arm that
fired and the class it fired for (the closing-price form for the first arm, the
hit-rate form for the second, both sentences if both have fired; C9b when only
one class is stopped). Entries of the other class keep "Take" if that class has
not itself been stopped. A `HARM_STOP` is never reversed under this id; a
passing later read does not restore "Take" without a new registration.

**Expected read date, main band.** 300 counted game picks with a CLV% at about
2 a day (the illustration's count) is about 150 slate dates. The 2026 regular
season has at most 12 left after 2026-09-15 (it ends 2026-09-27,
`docs/SEASON_END_PLAN.md:11`), so the read falls around August 2027 with no
restart and 2 counted picks every day, and not in 2027 at 1 a day. A restart
(11.2) pushes it later. The plus-money read is later still, per the paragraph
above.

**The ROI fail arm.** At 300 bets the 95% interval on ROI is about plus or
minus 9 points at -150 and 11 at -115 (`1.96 * sqrt((d - 1) / 300)`), so that
arm fires only on a point estimate below about -10%. It catches a very bad
rule, not a mildly losing one.

**Stop date.** If a class's floors are not met by the end of the 2027 MLB
postseason, that class's result is `UNDERPOWERED`: the counts and every 11.3
statistic for it are published once as a named non-verdict read, **that class**
stops publishing picks under this id, and the card uses copy C9 (both classes
stopped) or C9b (one class stopped) until a successor rule is registered. The
plus-money class is expected to reach this outcome rather than a verdict, for
the reason given above; that is a safe result, not a useful one, and it is
named in advance so nobody reads an absence of bad news as good news.

**A successor before the read.** A rule registered to replace V2 before the
read must, in its registration commit, publish V2's CLV% and ROI at that
moment as a named non-verdict read ("V2 interim at successor registration"),
so that abandoning V2 after a bad run is visible.

The floors are not lowered because a season was short.

### 11.5 Verdict

Thresholds and stop conditions from `docs/VALIDATION_CRITERIA.md`; all five
stop conditions are applied, and the one criterion not applied is D6. Every
condition below reads **counted picks only**, and is evaluated **once per
class, on that class's own counted picks**, producing one verdict for `MAIN`
and one for `PLUS_MONEY`. Neither verdict reads a pick of the other class, and
D9's combined figure enters none of them. Counted fills are published beside
each verdict as F1 and enter no condition, so a good or bad run of fills can
neither rescue nor sink either.

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

**These shadow comparisons and the family comparisons of 17.3 are two different
objects and are corrected separately, on purpose.** The three comparisons above
license nothing: V1, A and C have no promotion path, and no result of theirs can
move a constant, a gate or the published card. They are described, published
and corrected at their own family-wise 0.05 because that is how a description
is reported honestly, not because anything hangs on them. The **six** family
comparisons of 17.3 are the only comparisons in this registration that can
change what customers see, and they carry the 0.05 family-wise budget that
matters. Nobody may combine the two sets into one ladder, and nobody may report
a shadow comparison as though it had cleared the family's bar. The
`PENDING`-before-the-read rule of 11.4 applies to both sets alike.

### 11.7 The retirement result

Read on counted picks only; the fills' F1 line is published beside the result
and never decides it. **The result is class-scoped: a class retires on its own
verdict, and neither class's good run ever rescues the other's bad one.**

On **FAIL** or **UNDERPOWERED** for a class, within one publish day:

1. `DAILY_CARD_BEST_BETS_V2` stops publishing picks and fills **of that
   class**; the other class keeps publishing under its own read if it has not
   itself failed;
2. if both classes have stopped, the customer card shows shadow A's list under
   copy that makes no pick claim and uses no "Take" (copy C9) until a successor
   rule is registered; if one class has stopped, that class's entries are shown
   without a verb under copy C9b and the other class's picks are unchanged;
3. the verdict or non-verdict read for that class, every counted pick of it,
   every counted fill with its F1 line, and every comparison are published
   under `docs/`;
4. no parameter in this file is changed and re-run under this id. In
   particular a bad plus-money read retires plus-money picks; it does not
   loosen `MARKDOWN`, `BASE_EDGE`, G6's floor, G8's cap or G14 to try again.

On **HARM_STOP** (11.4) for a class, V2 keeps running that class without
"Take" under copy C11 (or C9b when only one class is stopped), and the
harm-check result is published under `docs/` within one publish day.

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
- Every licence above is **class-scoped**. A PASS on `MAIN` licenses nothing
  about `PLUS_MONEY` and the reverse, and no statement may be made about the
  two together: D9's combined figure is a description of what the card listed,
  never a finding.

### 11.9 The failure mode of this design, stated honestly

Written before any result exists, so that it cannot be written afterwards to
fit one.

**The largest assumption.** `MARKDOWN = 0.038` is measured on props, on the
side we favour, which by construction sits at or above 0.50, and it is applied
unchanged to game markets and to our own numbers between 0.30 and 0.50, where
nothing in this repo has ever measured anything (0.2). That transfer is the
load-bearing step of the whole design. If the true overstatement in the
plus-money band is smaller than 3.8 points, the rule is too strict and quietly
refuses bets the owner is asking for, in the name of a caution the evidence
does not require at that size. If it is larger, and the one adjacent
measurement of the same mechanism, our number sitting well above the market's,
found 21.5 points, then a pick can clear every gate here, carry a high score,
and still rest on a probability that is wrong in exactly the direction that
costs the most, because the design tolerates only 4.8 to 6.0 points of
overstatement (4.2) and 21.5 is far outside that.

**What the mechanism structurally prefers, and why that is uncomfortable.**
On the design board 3 of 5 picks and the 2nd, 3rd and 4th ranks were plus
money. The mechanism that produces that is **not** the Kelly form of the score,
which works the other way. Writing `e` for the marked-down number less
break-even, the score is exactly `e * d/(d-1)`, and that multiplier **falls**
with the decimal odds: 2.600 at -160, 2.140 at -114, 1.800 at +125, 1.500 at
+200, 1.400 at +250. At equal edge the score therefore penalises the long
price, and the board's own picks show it, at near-equal edge: Angels +1.5 at
-114 carries 4.20 points and scores +0.0899, Reds +1.5 at +124 carries 4.25 and
scores +0.0767, Athletics at +202 carries 4.18 and scores +0.0625, which is
shortest price first, not longest.

What actually lifts plus money is upstream of the score, and 4.4 already
measured it: the vig gap between a price's break-even and the market's own
number is 2.56 points in the -160..-110 band against 0.51 points at +151..+250,
so the same raw disagreement with the market leaves several more points of edge
at a long price, and more plus-money candidates clear G7 at all. On this board
3 of the 27 candidates in the plus-money band became picks against 2 of the 35
in the main band. The preference is real and it is what the owner asked for; it
is also exactly the band the evidence says is least trustworthy.
`required_edge` pushes back on it, and G14 caps it at 3 slots, but neither
claims to correct a bias nobody has measured. And the correction this leaves
undone is named rather than implied: if the vig gap is small at plus money
because those prices are efficient rather than generous, this mechanism keeps
surfacing them and nothing in the rule detects it. The family's loose arms
(section 17) and the plus-money arm of the harm check are the only instruments
pointed at that.

**What it cannot do.** Isolation prevents contamination; it does not
manufacture a sample. 11.4's arithmetic says the plus-money class may publish
for years under a label and a separate record without ever reaching a verdict,
not because it is safe but because the card cannot produce enough of its own
kind of bet to find out.

**The first measurements that would expose it**, in the order they can arrive:

1. **The harm check's hit-rate arm on `PLUS_MONEY`**, at 50 counted picks of
   that class with our raw number 3 or more points above the market's (11.4).
   Nearly every plus-money pick qualifies, so this is the earliest in-card
   signal, well before any floor.
2. **S6 restricted to `PLUS_MONEY`**, worth reading as soon as 20 to 30
   plus-money picks settle, not as a verdict but as the first direct look this
   project has ever had at our own number below 0.50. It is declared with its
   bins in 11.3 precisely so it cannot be chosen after the fact.
3. **SR1**, outside this rule entirely: registered in
   `docs/RESEARCH_STRATEGY_REPLICATION.md` and `docs/PREREG_SR1_HOME_UNDERDOG.md`
   (amendment 1, sha256 `07b5c9728e6efbf818e24196b7f565ca4c962f09770886c0c367635aa15e0a37`,
   registry rows 88-89 of `data/research/alpha_registry.jsonl`), covering the
   exact band this class publishes into (+100 to +150 home underdogs, plus a
   +151 to +250 band). Required to be run and published before the first
   plus-money pick (status line, build plan T0c). **RUN 2026-09-16, RESULT:
   KILLED, UNDERPOWERED_NULL, no edge in either band** (band A n=528, effect
   -3.51pp, decision p 0.1105, union CI [-8.06, +0.58]pp; band B +7.77pp
   (2023, n=138) then -2.14pp (2024, n=116), a sign flip; BH q=0.10 clears
   neither). Full result: `docs/SR1_RESULT_2026-09-16.md`. Per T0c's own
   acceptance line, a negative or inconclusive SR1 result does not by itself
   stop the plus-money class; it is evidence the owner reads before the class
   starts publishing. This condition is therefore satisfied and the
   plus-money class registers as written, with the SR1 finding on the record
   as a caution rather than a licence: SR1's own null does not say the
   30-to-45 band is safe, only that this particular narrow replication could
   not see the effect it was built to detect.
4. **The loose arms A3 and A4** (section 17), which are the same rule at a
   markdown of 0.0090 and a base edge of 0.0024, and are the way to learn,
   without changing the published card, whether the registered markdown refused
   bets that would have won. They replace the deregistered shadow D, which
   measured the same thing without a promotion rule (section 10). A4 is also
   the arm this section's warning applies to most sharply: on the design board
   its card is 7 plus money out of 10, every entry resting on our raw number
   sitting 4.0 to 9.3 points above the market's, so it is the arm most likely
   to reach a `HARM_STOP` rather than a verdict (17.8).

### 11.10 The variant family inside the evaluation plan

Section 17 registers the family. This subsection says what it changes in the
plan above, and what it deliberately leaves alone.

**What does not change: the published card's own verdict.** A1 is read exactly
as 11.4 to 11.8 already say. Its floors stay at 300 counted picks of a class
with a CLV%, 300 graded WIN or LOSS across 60 distinct slate dates. Its verdict
stays PASS at 55 per cent beating the close and mean CLV% at or above +1.5 per
cent with no FAIL condition, INCONCLUSIVE otherwise, FAIL on any of the five
conditions. Its harm check keeps both arms at 100 and 50 counted picks. Its
stop date stays the end of the 2027 MLB postseason. None of those numbers moves
because paper arms exist, in either direction: the family may not lower a floor
to reach a verdict sooner, and it does not raise A1's own floor either, because
A1's verdict is a one-sample read of the published rule and is not one of the
six comparisons the budget of 17.3 pays for.

**What is added: a second, stricter set of floors that apply only to a
promotion decision.** They are the registered floors multiplied by 1.5428, the
sample cost of the Holm rank-1 bar (17.3), rounded up:

| Floor | A1's own verdict (11.4) | A promotion decision (17.4) |
|---|---:|---:|
| counted picks of the class with a CLV% | 300 | **463** |
| counted picks of the class graded WIN or LOSS | 300 | **463** |
| distinct slate dates | 60 | **93** |

The promotion floors are read on **both** arms separately and again on the
**discordant set** between them, defined in 17.4 clause 1. Fills count toward
none of them, exactly as in 11.1. Each paper arm also reads its own 11.5
verdict on its own counted picks at the ordinary 300 and 60 floors, published
with its counts; that verdict is a read of that arm and is not by itself a
promotion (17.4 clause 4).

**The paper arms' counted populations are defined exactly as 11.1 defines
V2's**, with the arm's own rule id in place of V2's, the arm's own lock, and
the same four conditions: shown as a pick on at least one published row of that
arm's ledger and graded under section 9, first pitch strictly after
`REGISTERED_UTC`, regular season by the frozen `game_type`, and the shared
`code_fingerprint` of 11.2. The class split of 11.1 applies to every arm, and
no number anywhere adds one arm's picks to another's or one class to another's.

**The harm check of 11.4 runs on every arm, per class, at the same two
thresholds**, and its consequence is arm-scoped. A `HARM_STOP` on the published
arm removes "Take" from that class of the customer card, as 11.4 already says.
A `HARM_STOP` on a paper arm removes nothing from any customer surface, because
that arm has no customer surface; it retires that arm for that class from the
family permanently (17.5), while the arm keeps selecting, locking, grading and
counting so that its record is complete and its loser is published.

**Nothing is read before the read date, on any arm.** 11.4's rule that nobody
summarises CLV%, S2, S4, S5 or S6 over counted picks before the read applies to
all four arms, with **one exception and no others: the one-way harm check**.
A plain running win-loss-and-units line is published for **A1 only**, which is
what R5 already publishes on the customer record page. **No paper arm's running
units line is computed, printed, logged or shown anywhere before that arm's
read date**, because four such lines side by side are the arm scoreboard this
design refuses (17.8), whatever each line is called on its own. No comparison
statistic, no p-value, no arm ranking and no "arm A4 is up 3 units" exists
before the read date. This clause is written out because the
owner asked to see which arm is profitable, and the way that question destroys
itself is by being answered early and often (17.8).

**How a promotion is recorded, so the published record stays readable across
the switch.** A promotion is not a switch flipped at the read. Every step below
happens in the same publish day, and 11.4's "successor before the read" clause
is what requires most of it:

1. The winning arm is registered as a **new rule id**,
   `DAILY_CARD_BEST_BETS_V3`, in its own pre-registration file, with its own
   `REGISTERED_UTC` and with **both classes' constants written in
   explicitly**: the winner's constants on the class it was promoted on, and
   the incumbent's constants, unchanged, on the class it was not (17.4 clause
   8). V3 is therefore a two-class rule with at most one class changed per
   promotion, never a whole-card cutover won on one class's evidence. It
   becomes the published card only from that instant.
2. **V3's counted sample starts at zero.** No pick from the paper window is
   folded into V3's record, quoted as V3's evidence, or added to any V3 number.
   The paper window bought the decision; it is spent. 11.7's rule that a result
   never moves a constant is unchanged.
3. **A1's record is closed and published at the same instant**, as a named
   non-verdict read ("V2 interim at successor registration", 11.4), with its
   CLV%, ROI and counts per class. A bad incumbent run is visible rather than
   quietly replaced.
4. `evidence/cards_v2.jsonl` receives no row dated on or after the V3 cutover
   date, exactly as R3 already holds for `evidence/cards_v1.jsonl`. The record
   page shows V2's block as a separate, closed block beside V3's, and R4's rule
   that no number adds two rules' picks together extends to it unchanged.
5. **Every losing arm's full record is published** under `docs/`, with its
   counts and its losing numbers, at the same instant.
6. The family closes. One promotion per family, ever (17.4).

**If nothing promotes, which is the expected outcome** (17.8): A1 keeps
publishing under its own verdict, every arm's record is published with its
counts, and the family's result is written up as what it is. An absence of a
promotion is not a finding about the card; it is the family reporting that it
could not separate its members, and 11.8's rule that INCONCLUSIVE licenses
nothing applies to it word for word.

## 12. Record keeping

- **R1.** V2 picks, fills, provisional versions, withdrawn picks and fills, the
  close calls that were not shown, and
  stale-board states are written to `evidence/cards_v2.jsonl`, hash-chained,
  one row per publish run that changed anything and at least one row per slate
  date, **including dates with 0 picks**. Every row carries
  `rule: DAILY_CARD_BEST_BETS_V2`, the gate constants in force (including
  `MARKDOWN`, `BASE_EDGE`, the price band, G6's two floors, G8's cap, G14's
  sub-cap and G12's ceiling), the floor and
  the `code_fingerprint` (11.2); every pick and every fill carries its
  `game_type`, its class (pick or fill), its **`price_class`** (`MAIN` or
  `PLUS_MONEY`), its **raw** number, its **marked-down** number, its
  **`score`**, and, for a prop, **`lineup_posted`** and the plate-appearance
  source; and, on a fill, the checks it failed and its quote age when it was
  added. A row also carries the count of plus-money picks G14 dropped and
  whether G12's ceiling refused an entry that day (D4, D7).
- **R2.** Shadow rules and paper family arms write only to their own files
  (section 10, 17.6). Nothing but A1 writes to `evidence/cards_v2.jsonl`.
- **R3.** `evidence/cards_v1.jsonl` is never rewritten. It receives no rows
  dated on or after the cutover date.
- **R4.** Records are computed per file. No number anywhere adds V1 and V2
  picks together, or a paper arm's pick to a published pick, on the page, in
  the API or in a report.
- **R5.** The record page shows V2's record, and V1's record through the
  cutover date as a separate, closed block, both read from their ledgers at
  request time. **Each block shows game picks, player props and game totals
  together, and each kind apart**, with the kind lines of C8 (V2 has no totals,
  section 2, so its block never shows a totals line; V1's block shows one only
  if a V1 total was graded); V2's block also shows withdrawn picks apart.
  **V2's block shows four headline figures: main-band picks, plus-money picks,
  the fills and all entries together, each with its own won-lost-push and
  units.** The two pick figures are the rule's record, one per class, and are
  never added together except in the fourth, clearly-labelled figure (D9); the
  fills figure is the record of what the floor of 3 put on the card; the
  combined figure is what a reader who took every listed bet would have. No
  figure mixes a pick with a fill inside it, no figure mixes the two classes
  inside a class figure, and the page names which is which. The verdict of 11.5
  is read per class on the picks only, and the page never presents a fills or
  combined figure as the rule's result.
  V1's headline today (`card_ledger.record()`, `card_ledger.py:956-1115`)
  counts game picks only and keeps props under `by_kind`, so the staging card's
  "26-12, +4.82 units" leaves out V1's prop picks. EXPLORATORY, store
  `evidence/cards_v1.jsonl`, `card_settled` rows through 2026-09-14, WIN or
  LOSS: games 26-12, +4.8194 units; props 9-5, -0.6418; together 35-17,
  +4.1776. The closed V1 block uses the together figure as its headline.
- **R6.** For 14 days from the cutover date the card shows the switch banner
  (copy C10).
- **R7.** Every row of every family arm, A1's included, carries `rule` (the
  arm's own id), `published` (true on A1, false on A2, A3 and A4),
  `family_id: CARD_V2_VARIANTS_2026_09`, `arm` (`A1` to `A4`), the arm's own
  constants in force, the shared `code_fingerprint` of 11.2, and `pool_hash`,
  the sha256 of the shared candidate pool the run screened (17.6). A reader can
  prove from the ledgers alone that all four arms screened the same board, and
  a `pool_hash` mismatch between arms on one publish run is a fault, not a
  difference between rules.
- **R8.** No customer-facing route, template, serializer or record figure reads
  a paper arm's ledger or names a paper arm's rule id. The record page's four
  headline figures of R5 stay on A1's ledger alone. This is asserted by a test,
  not left to care (17.7).

## 13. Customer copy

Every string passes `tests/test_no_nothing_clears_the_bar.py` and
`tests/test_customer_language.py`. Percentages are rendered by one server
function as whole numbers, rounded half up; if any two of the three numbers on
a pick would show the same text while their frozen 4-decimal values differ,
all three show one decimal, then two, until no such pair shows the same text.
The client never re-rounds. Braces are fields read from the payload.

- **C1 Section head and purpose.** "Today's picks" · "Picks today: {n}" ·
  "Every pick is priced between -160 and +250. On a main-band pick the market
  makes that side more likely than not. On a plus-money pick the market makes
  it the underdog, and our own number, after it is marked down for how much it
  has run high in the past, is still above what the price needs. Plus-money
  picks are new, are labelled, and are kept on a separate record. The card
  lists three bets on a day when three clear the first checks. On a day when
  fewer than three pass every check, the closest calls are listed under the
  picks and marked as not picks, and on a day when the board offers fewer than
  three at all the card lists fewer and says so. The card never lists more than
  ten bets in total."
- **C2 A pick.** Headline: "Take {selection} at {price}" (only under the
  section 7 rule). Meta: "{book}" and the provisional, "Lock pending · graded
  as published" or locked state from `docs/DESIGN_SYSTEM.md` (true under L2,
  which locks as last published). First line, on the card face: "Market says
  {market}%. Needs {needs}% to break even at {price}. Our number: {ours}%."
  `{ours}` is the **marked-down** number, which is the number the rule acted
  on; the raw model number is never shown on the card, because showing a number
  the rule did not use would put a larger claim in front of the reader than the
  rule makes. Second line, also on the card face (`why[1]`): "The market's
  number is below what this price needs and ours is above it, after our number
  is marked down for how much it has run high in the past. Our number has not
  been shown to beat the market's." There is only one form of this line now:
  G13 refuses any candidate whose market number already clears its own price,
  so the draft's second form ("Both the market's number and ours are above what
  this price needs") can no longer occur and is removed.
- **C2b A pick shown without "Take"** (section 7). Headline: "{selection} at
  {price}". Added line, one of: locked, newest fresh read fails: "Locked at
  {price} ({book}). On the newest price check the best price is {now_price},
  and our number is below what that price needs, or the price is outside -160
  to +250." Locked, selection missing from the newest fresh read: "Locked at
  {price} ({book}). No current price for this bet on the newest check."
  Newest read stale: "Waiting for fresh prices. Prices were last checked {age}
  ago." The C2 lines stay on the face.
- **C3 Added lines.** When the market's number is between 0.50 and 0.55: "The
  market makes this only slightly more likely than not." Run line +1.5: "+1.5
  wins if the {team} win, or lose by one run." Run line -1.5: "-1.5 wins only
  if the {team} win by two or more runs." Prop with a posted lineup: "{player}
  is batting {ordinal} in the posted lineup, with {season_games} games of
  history." Prop with no posted lineup: "{player} has {season_games} games of
  history this season." (followed by C15, which is mandatory in that case).
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
  Reasons, joined with "; ": G3 "price not checked in the last hour"; G7 "our
  number is below what the price needs after the markdown". (A fill has
  already passed G1, G2, G4, G5, G6, G8, G9, G10 and G13, so no other reason
  can apply; the draft's G6, G8 and G10-lineup reasons are gone, two because a
  fill must now pass those gates and one because the lineup test is no longer a
  check at all.) Every entry in this section also carries C12, and a
  plus-money entry also carries C14, and a prop with no posted lineup also
  carries C15.
- **C7 Disclaimer.** "These are picks, not guarantees. Our number has not been
  shown to beat the market's, and every pick shows both numbers and what the
  price needs. Every pick is published before its game. A pick still on the
  card four hours before its game is graded at the price shown then, win or
  lose. A pick removed earlier is graded too, at the price it was last shown
  at, and listed as removed. The bets listed as not picks are graded the same
  way, and kept apart from the picks on the record."
- **C8 Record line.** "Card picks, rule v2 · {first} to {last} · {n} picks ·
  {w}-{l}-{p} · {units} units at the published prices. Main-band picks:
  {mw}-{ml}-{mp}, {munits} units. Plus-money picks, kept on their own record:
  {qw}-{ql}-{qp}, {qunits} units. Game picks
  {gw}-{gl}-{gp}, {gunits} units. Player props {pw}-{pl}-{pp}, {punits} units.
  Picks removed before their lock, included above: {rw}-{rl}-{rp}, {runits}
  units. Bets listed as not picks, kept apart from the picks: {fw}-{fl}-{fp},
  {funits} units. Picks and those bets together: {aw}-{al}-{ap}, {aunits}
  units. Preliminary: not enough picks yet to show an edge or its absence." The
  two class sentences are left out while that class has graded nothing, under
  the same omission rule the kind lines already use. V1
  block: "Rule v1, on the card until {cutover}: {w}-{l}-{p} over {days} days,
  {units} units at the published prices. Game picks {gw}-{gl}-{gp}, {gunits}
  units. Player props {pw}-{pl}-{pp}, {punits} units. Game totals
  {tw}-{tl}-{tp}, {tunits} units. Kept as it was, and not added to rule v2's
  numbers." A kind with no graded picks is left out of the line rather than
  shown as zero; V1 graded no totals through 2026-09-14, so today its block
  shows no totals line. The two sentences about bets listed as not picks are
  left out while no such bet has been graded, and V1's block never carries
  them, because V1 has none.
- **C9 After a FAIL or UNDERPOWERED on both classes.** Head "Today's board".
  Purpose "Bets priced between -160 and +250 that pass our first checks, listed
  in the order this rule ranks them. These are not picks." No verb on any
  entry.
- **C9b After a FAIL, UNDERPOWERED or HARM_STOP on one class only** (11.4,
  11.7). The stopped class's entries stay on the card, without a verb, under
  this line, and the other class's picks are unchanged. Plus-money form: "The
  plus-money bets below are still listed, but they are no longer picks. A
  check on the first graded ones did not come out well enough for us to keep
  saying take them. The rest of the picks are unchanged." Main-band form: the
  same sentence with "main-band bets" in place of "plus-money bets".
- **C10 Switch banner.** "From {cutover} the card uses a new rule: no pick is
  priced shorter than -160 or longer than +250, some picks are on sides the
  market makes the underdog and those are kept on a separate record, the card
  never lists more than ten bets, and on a day when fewer than three bets pass
  every check the card lists the closest calls beside the picks, marked as not
  picks and kept apart on the record. The old
  rule's record is kept below, separately." It says how the shortfall is
  filled, never how many entries a given day will have, so it stands beside
  C13 as well as beside C4 and C5.
- **C11 After a HARM_STOP.** Head "Today's list". Purpose, in the form for the
  harm-check arm that fired **and the class it fired for** (11.4); when only
  one class is stopped, C9b is used instead and the other class keeps "Take".
  Closing-price arm: "These bets pass our
  checks, but a check on the first graded ones found they were getting worse
  prices than the market settled at, so we no longer say take them. They are
  not picks." Hit-rate arm: "These bets pass our checks, but a check on the
  first graded picks where our number was well above the market's found they
  won less often than their prices needed, so we no longer say take them.
  They are not picks." Plus-money hit-rate arm: "These bets pass our checks,
  but a check on the first graded plus-money picks found they won less often
  than their prices needed, so we no longer say take them. They are not picks.
  The other picks are unchanged." If both arms have fired, the purpose is
  "These bets pass
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
  books have to be quoting the price, the price has to be between -160 and
  +250, and the market's own number has to be no higher than what that price
  needs. Today the board had {n} of those." At n = 0 the card shows this line
  and no entry, which is the one state the floor cannot fix without breaking a
  gate, and it never breaks one (section 6).
- **C14 The line on every plus-money entry** (sections 5 and 7). On the face of
  every pick and every fill whose price is +100 or longer, under its C2 or C6
  lines: "This is a plus-money pick: the market makes this side the underdog,
  and our number, after it is marked down, is still above what the price needs.
  Picks like this are kept on their own record, apart
  from the rest, so a bad run here cannot hide inside the other picks and a
  good run there cannot cover for one here. There is no record for this kind of
  pick yet." On a fill the first four words read "This is a plus-money bet"
  instead, because a fill is never called a pick. **The clause the draft
  carried here, "and our number does not", was struck on 2026-09-16 as untrue
  of the class it is printed on.** Our number usually makes the side an
  underdog too; what it says is that the side is a better underdog than the
  price pays. On the design board all three plus-money entries showed a number
  below 50% (Reds +1.5 at +124 showing 48.9%, Athletics at +202 showing 37.3%,
  Orioles at +117 showing 48.7%, and the Athletics raw number 41.1% is below it
  as well, 14.2), so the struck clause would have contradicted the "Our number:
  {ours}%" line printed one line above it, on the class the owner asked for
  most. The wording that replaces it is C1's, which was already true of the
  class. **No string on a plus-money entry may state or imply that our number
  makes that side more likely than not**, and the build plan pins that as an
  assertion against a below-0.50 fixture rather than as prose
  (`docs/CARD_V2_BUILD_PLAN.md`, `tests/test_card_v2_copy.py`).
- **C15 The line on every prop with no posted lineup** (section 8). On the
  face, under C3: "No lineup is posted yet for this game. Plate appearances are
  priced off this batter's season average, not his spot in today's order." It
  is mandatory on a pick exactly as on a fill, and never sits behind a control.
- **C16 Layout section labels** (17.2, the display experiment). Three plain
  labels, used only by layout treatments L2 and L3 and by nothing else: "Main
  band", "Plus money", and the jump link "Skip to plus money". They name a
  class that every entry already carries on its face under C14. They make no
  claim about either class, carry no verb, and no treatment may add any other
  string. The entries under either label are the same entries, in the same
  within-class order, as treatment L1 renders in one list.

**The variant family of section 17 adds no customer string beyond C16 and
changes no existing one.** The paper arms are never rendered, so they touch no
copy at all; the display experiment changes the order and grouping of entries
the card already shows, under labels that name a class the card already names.
`tests/test_customer_language.py` and `tests/test_no_nothing_clears_the_bar.py`
bind on C16 exactly as on every other string here.

No string on the card claims an edge, value or a guarantee, and none uses
"STRONG", "sure", "fair price", "best of N books" or calls a model number a
chance of winning. "Edge" appears only inside the negated record line from
`docs/DESIGN_SYSTEM.md` (C8), and "lock" only as "Locked", "Locked at
{price}", "Lock pending" and "before their lock", never as "a lock". Every
string changed or added by this revision (C1, C2, C3, C6, C8, C9, C9b, C10,
C11, C13, C14, C15) was checked against `HARD_BANNED`, `NEGATION_ONLY` and
`NEGATORS` imported from `tests/test_customer_language.py` (the same import
`tests/test_web_structure.py` uses) and against `BANNED_PHRASES` and
`BANNED_JARGON` imported from `tests/test_no_nothing_clears_the_bar.py`:
18 strings, 0 violations
(`scratchpad/value_score/final_copy_check.py`). C16's three labels were checked
against the same five lists, imported the same way:
0 violations (`scratchpad/variants/family_consistency.py`).

---

## 14. What this rule would have published on 2026-09-15

**EXPLORATORY. Illustration on already-seen data, not evidence for or against
anything.** The design used this board, so it is excluded from every count in
section 11 and from every count of every shadow rule. It shows what the gates
and the score do; it says nothing about whether any of these bets would have
won. Source: `scratchpad/value_score/candidate_pool_2026-09-15.csv` (the same
138-candidate pool the draft's own illustration used, rebuilt live at about
17:15Z with the repo's own functions and copied into this session's scratch
directory) and the published V1 row (16:42:48Z). Script:
`scratchpad/value_score/final_rule.py`, which implements sections 3 to 6 as
revised, reuses `src.core.odds` for every price and probability conversion,
recomputes each break-even from the price, ranks on unrounded numbers, and
applies G11 before G14 and G12 in the order section 5 fixes. Supporting counts:
`scratchpad/value_score/final_extra.py`.

**Which model.** The numbers are the pre-registration model's: the card
calibration of 14:37Z (n 1,997, `b` 0.769145), `DISPERSION = 2.3352` and
`RHO = 0.05065`, all fitted on sealed-window games and the calibration on
forward games too (section 1.1), and **raw,
uncalibrated run-line numbers**, with G9 treated as passed for run lines
because no run-line calibration exists yet. The registered model (11.2) is
fitted once on 2025 and would give different numbers, so this shows what the
gates and the score do, not what the registered model would pick.

**Quote times.** The pool's 56 game rows have an empty `observed_utc`. The game
board's capture time, 14:31:29Z, is read from the published V1 row and is the
newest row in `data/processed/odds_multibook.jsonl` on this machine; prop quote
times (04:09:29Z to 04:09:34Z) are in the pool. Prop rows carry no first pitch;
the script maps each batter's club to its game (every game on the slate started
22:40Z or later). The pool must be rebuilt with game quote timestamps before it
is used as the T12 fixture.

**The candidate pool under the revised gates.** Of 138 rows, 26 are totals and
are not candidates (section 2). Of the remaining 112: 50 are outside G4's band
(-160 to -100 or +100 to +250), 35 are `MAIN` and 27 are `PLUS_MONEY`. After
G1, G2, G5, G6, G8, G9, G10 and G13, **36 candidates are eligible to be a pick
or a fill**. Counted by check rather than by candidate, so a candidate failing
two appears under both: 13 fail G10's 15-game floor (all props), 10 fail G8's
disagreement cap, 8 fail G6's floor on our own number, 1 fails G5's market
band, and **0 fail G13**, which refused nothing on this board. (Two further
candidates exceed G8's cap but sit outside G4's band and are refused there
first, so 12 of all 112 exceed it.) The longest price on the board is +206, so
G4's +250 ceiling refused nothing either, and of 27 plus-money candidates
exactly 1 had our own raw number below G6's 0.30 floor, a candidate whose
marked-down number was in any case far below its price's bar.

### 14.1 As registered

At the 16:42:48Z publish instant every game quote was 7,879 seconds old and
every prop quote over 12 hours old, all above G3's 3,600. **V2 publishes 0
picks and 3 fills**, and serves C5 ("Picks today: 0 so far. Prices were last
checked 2 h 11 min ago. New picks are only made from prices checked in the last
hour, so this list waits for the next check. The bets below are not picks. They
fill the card to three, or to as many as the board offers, at the prices last
seen, and they are graded at those prices."). The board offered more than three
candidates past the base gates, so C13 does not fire and C5's fill sentences
stand. The three fills, in the close-call order of section 6 (all fail one
check, all have zero shortfall, so the score orders them), each with its price
age, its C12 line and, on the two plus-money entries, its C14 line; 36 close
calls were available:

| # | Entry | Class | Books | Market | Needs | Ours (marked down) | Score | Not a pick |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | Angels +1.5 at -114 (FanDuel) | MAIN | 11 | 52.0% | 53.3% | 57.5% | +0.0899 | price not checked in the last hour |
| 2 | Reds +1.5 at +124 (LowVig) | PLUS_MONEY | 9 | 43.7% | 44.6% | 48.9% | +0.0767 | price not checked in the last hour |
| 3 | Athletics to win at +202 (LowVig) | PLUS_MONEY | 11 | 32.8% | 33.1% | 37.3% | +0.0625 | price not checked in the last hour |

Two of the three fills are plus money, which is new: the draft's fills on this
board were Angels +1.5, Twins +1.5 and Matt Olson under 1.5, all priced shorter
than even money. Reds moneyline +206 (score +0.0731) and Angels moneyline +149
(+0.0705) ranked above the Athletics but were dropped by G11, because a
higher-scored entry already held their game. Under the owner's answer these
three go on the record and are graded at prices that were over two hours old,
because the floor is met at every publish run and a fill does not have to pass
G3.

### 14.2 With G3 set aside, as if the capture chain had kept the board fresh

Totals excluded (paused). 112 moneyline, run-line and prop candidates, 36
eligible past the base gates.

**Picks: 5. Fills: 0** (five entries already clear the floor of 3). Ranked by
score, both classes interleaved, as section 5 directs. Prices are the best
available with the book that quoted them; "ours" is the marked-down number the
rule acted on, and the raw number is shown beside it here only because this is
an internal illustration.

| # | Headline | Class | Book (books) | Market | Needs | Ours raw | Ours marked down | Raw edge | Bar | Score |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Take Angels +1.5 at -114 (SEA at LAA) | MAIN | FanDuel (11) | 52.0% | 53.3% | 61.3% | 57.5% | 8.00 pt | 4.96 pt | +0.0899 |
| 2 | Take Reds +1.5 at +124 (LAD at CIN) | PLUS_MONEY | LowVig (9) | 43.7% | 44.6% | 52.7% | 48.9% | 8.05 pt | 5.18 pt | +0.0767 |
| 3 | Take Athletics to win at +202 (ATH at TB) | PLUS_MONEY | LowVig (11) | 32.8% | 33.1% | 41.1% | 37.3% | 7.98 pt | 5.66 pt | +0.0625 |
| 4 | Take Orioles to win at +117 (BAL at NYM) | PLUS_MONEY | BetOnline (11) | 45.2% | 46.1% | 52.5% | 48.7% | 6.41 pt | 5.14 pt | +0.0484 |
| 5 | Take Michael Harris II under 1.5 total bases at -148 | MAIN | William Hill (3) | 57.0% | 59.7% | 64.9% | 61.1% | 5.25 pt | 4.83 pt | +0.0360 |

Dropped before the card, in the order section 5 fixes:

| Dropped by | Entry | Class | Score | Why |
|---|---|---|---:|---|
| G11 | Reds to win at +206 | PLUS_MONEY | +0.0731 | Reds +1.5 already holds that game at a higher score |
| G11 | Angels to win at +149 | PLUS_MONEY | +0.0705 | Angels +1.5 already holds that game at a higher score |
| G14 | Pirates to win at +190 | PLUS_MONEY | +0.0351 | the plus-money sub-cap's three slots were taken |

**What this says about the owner's direction, on this one board.** Three of the
five picks are plus money, and **one** of those three is in the 30-to-45 per
cent band of our own number: the Athletics at 41.1%. The other two, Reds +1.5
at 52.7% and Orioles at 52.5%, are above 0.50 on the raw number and below it
only after the markdown. The Reds moneyline at +206 and 41.4% would have been a
second, and was dropped by G11. (The draft said two of the three were in the
band and then named an entry that is not one of the three; corrected
2026-09-16, and the same sentence is corrected in the diagnosis's 5.3.) So the
part of his range this board actually reached is one pick in fifteen candidates
that sat in it: 4.6 gives the reason, which is that the band is shut below
about +152. Both run-line picks are the case he described: our number calls a
side outright likely that the market prices as the underdog. The prop pick
exists only because the lineup test was removed from G10; no prop contract on
the 04:09Z board had a posted lineup, so under the draft it could not have been
a pick, and it carries copy C15 on its face.

**What the rule refused that a looser one would have taken.** Rockies +1.5 at
+106 (market 46.9%, our raw number 63.8%, a 16.9-point gap, tied with two other
candidates for the largest gap on the board) is refused by G8, a gap larger
than the tail `docs/PROP_CALIBRATION_2026-09-14.md` measured hitting 40.6%
against a 62.1% claim. So are Nationals +1.5 at +110 (11.6-point gap) and White
Sox to win at +135 (10.9). All three appear in shadow A's list below, at its
top three ranks, which is what A is for.

**Closest misses on the value test.** Pirates +1.5 at +110 (raw edge 4.90 pt
against a 5.09 pt bar) and Matt Olson under 1.5 at -157 (4.56 against 4.81)
are the two nearest, and on a day with fewer than three picks they would be the
first fills.

### 14.3 Shadow rules on the same board (G3 set aside)

| Rule | Picks | Fills | Notes |
|---|---:|---:|---|
| V2 (this rule) | 5 | 0 | 2 MAIN, 3 PLUS_MONEY, listed above |
| V1 | 8 | not applicable | As published (section 1 of the diagnosis); V1 fills to 3 from its SPLIT pile, which did not fire on this board |
| A, G6, G7, G8 and G14 removed (section 10) | 10 (the ceiling; 48 passed before G11, 21 after it) | 0 | Rockies +1.5 +106, Nationals +1.5 +110, White Sox +135, Angels +1.5 -114, Reds +1.5 +124, Athletics +202, Orioles +117, Michael Harris II u1.5 -148, Pirates +190, Matt Olson u1.5 -157. The first three are exactly the disagreements G8 refuses, and they take the top three ranks, which is what A exists to measure. Seven of the ten are plus money, which is what dropping G14 costs, and the list holds all five of V2's picks, which is what dropping it buys: the difference between the two lists is exactly what G6, G7 and G8 refused. Carrying G14 in A instead would drop Reds +124, Athletics +202, Orioles +117 and Pirates +190 and fill those four slots with main-band entries whose marked-down number is below break-even (Pete Alonso u1.5 -150, Red Sox -108, Drake Baldwin u1.5 -159, Dominic Canzone u1.5 -159, scores -0.029 to -0.225), which measures the sub-cap and not the three gates. Both readings were computed on this pool; the registered one is the one printed here (`scratchpad/value_score/fix_verify.py`) |
| C, worst price -150 | 5 | 0 | The same five picks as V2: no V2 pick on this board is priced between -160 and -151, so C's shorter band changes nothing here |
| E, the superseded "likely first" rule | 2 | 1 | Twins +1.5 -112 and Angels +1.5 -114, ranked longest price first, with Matt Olson u1.5 -157 as the fill. These are the draft's own figures for this board, reproduced from the pre-amendment section 14.2 rather than recomputed, because E is the draft rule unchanged. No plus-money entry, no prop pick |

### 14.3b The four family arms on the same board

**EXPLORATORY, and the strongest warning in this section applies to it: this is
an illustration of what the arms DO, on one already-seen date, and must never
be quoted as one arm beating another.** No arm's numbers here enter any count
in section 11 or 17. Source
`scratchpad/variants/variant_family.py`, on the same 138-candidate pool.

**NOT REPRODUCIBLE AS WRITTEN — established 2026-09-17, before
`REGISTERED_UTC`, and left standing rather than quietly deleted.**
An independent check tried to re-derive this table from the committed tree
and could not, for two reasons that are worth separating:

1. The cited source, `scratchpad/variants/variant_family.py`, does not exist
   anywhere in this repository, and neither do the other scratchpad files
   section 14 cites. The numbers below were produced by code that was never
   committed.
2. The model side needs the calibration as it stood at the publish instant --
   `b=0.769145, n=1997`, fitted 2026-09-15T14:36Z. `data/processed/card_calibration.json`
   no longer holds it: a later daily loop refit it at 21:04Z the same day to
   `b=0.735183, n=1911`. The original survives ONLY at commit `7db02b0a`, and
   a reader working from the current tree would silently get the wrong model
   and wrong numbers with nothing to warn them.

What IS confirmed from the committed tree: the raw board is there --
`data/processed/odds_multibook.jsonl` yields 14,989 quote rows for
2026-09-15 at or before 16:42:48Z, whose newest observation is 14:31:29Z,
matching 14.3's stated capture instant exactly. `DISPERSION = 2.3352`
(`src/analysis/strength.py`) and `RHO = 0.05065` (`src/analysis/playerprops.py`)
match this document. So the inputs were real; it is the derivation that is
unavailable.

This table therefore records **what the code did once, on a date, by a route
no independent reader can currently re-run.** That is weaker than it reads,
and it is stated here rather than fixed by deletion because deleting an
inconvenient illustration from a pre-registration is the worse act. It costs
the registration nothing: 14.3b is exploratory, enters no count in section 11
or 17, and no promotion, floor or threshold anywhere depends on it.

The lesson generalises and is logged as Stage 18 F2: this project has now
found three artifacts whose supporting input was not kept -- the lineup store
an automated job deleted nine times, this calibration, and the V2 frozen
parameter file, which was gitignored while the registration cited its sha256
(fixed at c59300fd). An artifact that outlives its input cannot be checked by
anyone, including us.

**At the real publish instant (16:42:48Z, every quote stale).** All four arms
publish **0 picks and 3 fills**. A1 and A2 are byte-identical to each other;
A3 and A4 are byte-identical to each other; the two pairs differ by one entry.

| Arm | Picks | Fills | The three fills |
|---|---:|---:|---|
| A1, A2 | 0 | 3 (1 MAIN, 2 PLUS_MONEY) | Angels +1.5 -114; Reds +1.5 +124; Athletics +202 |
| A3, A4 | 0 | 3 (2 MAIN, 1 PLUS_MONEY) | Angels +1.5 -114; Reds +1.5 +124; Michael Harris II u1.5 -148 |

On the counted population, which is picks only, this date gives the family
**nothing at all**: every arm contributed zero counted picks. That is the most
important line here, and 17.8 builds its calendar on it.

**With G3 set aside, as 14.2 does.**

| Arm | Picks | MAIN | PLUS_MONEY | Adds against A1 | Drops against A1 |
|---|---:|---:|---:|---:|---:|
| A1 STRICT_CAP3 (published) | 5 | 2 | 3 | 0 | 0 |
| A2 STRICT_NOCAP | 6 | 2 | 4 | 1 | 0 |
| A3 LOOSE_CAP3 | 7 | 4 | 3 | 2 | 0 |
| A4 LOOSE_NOCAP | 10 (the ceiling) | 3 | 7 | 5 | 0 |

- **A2** adds **Pirates +190** and nothing else. G14 was the only thing
  refusing it.
- **A3** adds **Matt Olson u1.5 -157** and **Pete Alonso u1.5 -150**, both
  `MAIN`, and adds **no plus-money pick at all**, because the sub-cap was
  already full at three. Its plus-money overflow of six candidates (Pirates
  +190, Royals +146, Cubs -1.5 +154, Giants +147, Twins +155, Tigers +121) is
  entirely refused by G14.
- **A4** adds Matt Olson u1.5 -157, Pirates +190, Royals +146, Cubs -1.5 +154
  and Giants +147. It hits G12's ceiling of 10 and drops Pete Alonso u1.5 -150,
  Twins +155 and Tigers +121. Its card is **7 plus money out of 10**.
- **The deregistered shadow D** (`MARKDOWN = 0`, `BASE_EDGE = 0.010`) produces
  the **identical** 7-pick card to A3, in the identical order, which is the
  measured reason section 10 absorbs D into the loose arms rather than running
  both (`scratchpad/variants/shadow_d_vs_loose.py`).

**Four things follow, and 17.8 says them again because they decide whether this
family ever resolves.** Every arm's pick set here is a strict superset of A1's,
so no arm drops an A1 pick on this board. A2 differs from the published card by
one pick. A3, with the cap on, does not reach plus money at all, so the arm
that loosens the bar while keeping the cap answers a main-band question. And A4
is the only arm that separates quickly and is the one the measured evidence
warns about most.

### 14.4 What cannot be read from this

One date, already seen, with a stale board and the pre-registration model. It
shows the gates and the score do what they say. It says nothing about whether
V2 picks win, beat the close or return money, and must never be quoted as
either "V2 works" or "V2 is too strict". Nothing in 14.2, 14.3 or 14.3b is a
comparison between rules: five picks against two, or ten against five, is a
count of what each rule listed on one already-seen board, not evidence that
either is better. In particular, A4 listing twice as many bets as A1 is not a
point in A4's favour and is not a point against it; it is the reason A4 will
reach a read first and the reason its harm check will fire first (17.8).

It does show the likely shape: few picks, most of them plus money, each resting
on our own number sitting five to eight points above the market's before the
markdown and still above the price after it. That shape is the thing 0.2 and
11.9 warn about, and it is visible here on the first board anyone looked at.

It also shows what the floor of 3 costs. On this board the card is 5 picks and
0 fills with fresh prices, and 0 picks and 3 fills at the real publish instant,
so on a day like that everything the reader sees, and everything that goes on
the record, is bets the rule itself says are not picks. Whether fills win or
lose here is unknowable from one already-seen board and is not read; what is
known in advance is that they are graded, published and kept apart, and that
they never touch the verdict (11.1, 11.5).


## 15. Owner decisions this needs

Each question is one yes or no. An answered question records Brey's own words
with the date and time he gave them; an open question shows the default the
build, the V2 ledger and the `?rule=v2` preview use until he answers. The line
under each question says which of his words it departs from, or what it
settles.

**Answered: 1 (both parts), 2, 3, 4, 5, 6, 7, 8, 9, 10 and 11.** Questions 1, 3
and 4 were answered by Brey on 2026-09-15 at about 22:35Z (3:35pm Pacific);
question 1's open part (the card's maximum) at about 00:45Z on 2026-09-16;
questions 2, 5, 6 and 8 at about 00:50Z on 2026-09-16 (5:50pm Pacific 9/15);
and questions 7, 9, 10 and 11 at about 03:10Z on 2026-09-16 (8:10pm Pacific
9/15). All were given in chat, in reply to plain-words questions about this
draft. **Open: 12, 13 and 14**, all new, all arising from the answers of
2026-09-16 about 03:10Z. Registration still requires his explicit answer to
each open question, or his explicit acceptance of its default, with its date;
nobody else may accept one for him.

**The answers of 2026-09-16 about 03:10Z did not choose between the options
they were given.** Asked which single setting to register on three of the four,
he answered that the disputed settings are themselves strategies and should be
run against each other and judged on profit. That is a legitimate answer and it
is taken literally, with one constraint he did not ask for and cannot be
dropped: running several rules and publishing whichever looks best is the
standard way to manufacture a false finding, so the answer is a **fixed
pre-registered family with a multiplicity budget and a promotion rule written
before any result**, which is section 17, and not an open-ended search. What
his answer buys, what it costs and what it cannot deliver are in 17.3, 17.4
and 17.8. His four answers, verbatim and in the order they were asked:

> Q: "Your example was +150 at 30-45 per cent. After the markdown that protects
> against our model running hot, that band only opens at about +152, and 30 per
> cent never qualifies. Accept, or loosen?"
>
> A: **"Can we try both strategies and see which one is profitable? These are
> the types of strategies that we should be changing not necessarily just the
> type of bedding strategy like changing these differences are strategy
> changes. Does that make sense?"**

> Q: "Plus-money picks are capped at 3 a day so a thin day cannot become an
> all-underdog card. Keep that cap?"
>
> A: **"Again, these are different strategies that we should be trying because
> maybe one of them profitable and one of them is not so like try and be more"**

> Q: "How should the card display the two kinds (one list by score, or separate
> sections)?"
>
> A: **"Try different strategies on this. Try both separate I want. Try to try
> mix a hybrid."**

> Q: "Every Take rests on our own number beating the price, and our number has
> not been shown to beat the market. Each pick will say so. Acceptable?"
>
> A: **"Yes, publish with the line."**

**What each answer closes.** The first closes question 11 and the second closes
question 9, not by choosing a value but by turning each into one factor of the
2 x 2 family of 17.1. The third closes question 10, not as a strategy question
at all but as a display experiment that can never count as a strategy result
(17.2). The fourth answers question 7 yes, outright.

**The answers of 2026-09-16 about 00:50Z supersede a standing directive of
2026-09-11.** Both quotes and both dates are in section 0.1, which is the
record of that supersession. Nothing was applied quietly and nothing was
inferred: each answer below is his own text.

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
   that offers three candidates past the base gates. **It still departs from
   both on the board that does not.** No gate was loosened to reach three: a
   fill still passes G1, G2, G4, G5, G6, G8, G9, G10 and G13, so it is never
   priced outside -160 to +250, never below the class's floor on our own
   number, and never more than 10 points from the market's; and where a board
   offers fewer than three such candidates the card lists fewer, down to none,
   and says why (copy C13). That state is published as a count. Its cost,
   stated in the option he chose: entries the rule itself says are not picks go
   on the public record and can drag it down. The rule's verdict is protected
   from that by reading picks only (11.1, 11.5).
   **The open part of this question, the card's maximum, is now ANSWERED
   2026-09-16 about 00:45Z: cap the card at 10 listed bets in total, picks and
   fills together.** The draft's G12 counted picks only and kept a fill once
   shown, so it could list 13 bets at one time, more than the "3-10 bets" he
   named on 2026-09-15. He was shown that consequence and ruled on it. G12 now
   counts every entry, and the 13-bet state cannot occur. The cost of his
   answer is written into section 6: on a day that begins thin and then fills
   with picks, an eleventh entry that passed every gate is refused a slot
   rather than a published fill being withdrawn to make room, and D4 counts
   every date where that happened.
2. **May a player prop become a pick only from a price checked after its
   lineup posts, in practice the last 2 hours before first pitch, so that
   before then it appears at most as a fill on a day with fewer than 3 picks,
   and on most days not at all? ANSWERED 2026-09-16 about 00:50Z: "No, allow
   earlier."**
   Asked in exactly those words, he answered no. **The lineup test is removed
   from G10** (sections 0.1, 3 and 8). A prop may be a pick before its lineup
   posts, priced off the batter's season-average plate appearances, which is
   what the live V1 card already does (`src/report/card.py:717`,
   `src/analysis/daily_card.py:1274-1280`). The safeguards that are not about
   lineups all stay: 2 books, 15 games of history, one pick per player, and
   G5 to G8 and G13 as for games. **The disclosure stays and is mandatory on
   the face of every prop with no posted lineup** (copy C15): no lineup is
   posted, and plate appearances are priced off a season average. This answer
   honours "needs to be ran pre emptively" (2026-09-14), which the draft's
   default did not. EXPLORATORY, its size on the design board: 6 prop
   candidates become eligible where the lineup test left 0, and 1 becomes a
   pick (section 8, section 14).
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
   The long end of G4, +250, comes from his answer to question 5 and is new.
5. **May a pick be a side the market makes less likely than not, at plus
   money, when our number beats its price? ANSWERED 2026-09-16 about 00:50Z:
   yes.** His words, verbatim, in reply to "Underdogs at plus money: our number
   sometimes says an underdog beats its price while the market says he is under
   50% to win. Allow those as picks?":

   > "BOOM KEY QUESTION! Theres a lot of times where trhe underdog actuall
   > makes more sens than the favorite and those are the real bangers, vewgas
   > doesnt always get the stats right and sometimes the underdog isnt because
   > his likelihood iof winning is low, it might be due to other factors and
   > especially UFC when we get to it there so many underdogs, and same with
   > fidning +100 to +250 poicks offer rally good value"

   So G5's "market above 0.50" is removed for plus-money candidates and
   replaced by a market band of 0.20 to below 0.50, a price band of +100 to
   +250 taken from his own named range, and a separate, separately graded
   `PLUS_MONEY` class (sections 0.1, 3, 4, 11.1). This supersedes the
   2026-09-11 directive for the card, which is recorded with both quotes in
   0.1. What it costs, stated to him in plain words and written in 0.2 and
   11.9: our number has never been checked below 0.50 anywhere in this repo,
   every bucket that has been checked runs hot, and a fixed-size error costs
   about 2.2 times more expected value at +250 than at -160.
6. **Is a pick acceptable when the market makes it only a little more than 50%
   likely, provided the page says so (copy C3)? ANSWERED 2026-09-16 about
   00:50Z, and the answer goes further than the question.** His words,
   verbatim, in reply to "A side the market makes only 51% likely is still
   likely. Allow picks that barely clear 50%?":

   > "even confidence of 30-45+ percent if high enough value (+150, +200 etc
   > etc) we need an algorithm of value x confidence / likelihood"

   So the floor on our own number is 0.50 in the main band, unchanged, and
   **0.30 in the plus-money band**, which is his number, not a drafting choice
   (G6). The "algorithm of value x confidence" is section 4's score, used both
   to select and to rank. On the design board the band he named is reached, not
   just allowed: the Athletics moneyline at +202 is a pick with our number at
   41.1% (section 14).
7. **Is it acceptable that every "Take" rests on our own number clearing the
   price, although our number has not been shown to beat the market's,
   provided every pick says so (copy C2)? ANSWERED 2026-09-16 about 03:10Z:
   "Yes, publish with the line."**
   Asked in those words, he answered yes and named the condition himself: the
   line ships with the pick. So copy C2's second sentence, which states that
   our number has not been shown to beat the market's and names the markdown,
   is **mandatory on the face of every pick at every rank and every width**,
   never behind a control, and the build pins it as an assertion rather than
   prose (build plan T2, T9, T12). His answers of 2026-09-16 about 00:50Z had
   presupposed this and made it more load-bearing, not less: with the
   plus-money class the whole pick rests on our own number, and the markdown of
   section 4 is the only thing standing between his direction and an unmarked
   model number. He has now answered it directly rather than by presupposition.
   It also settles "the value is great": on the 2026-09-15 board the market's
   own number cleared the price on none of 112 candidates, and G13 now refuses
   any candidate where it does. The answer licenses nothing else: "Take" still
   stops for good, per class, if the harm check fires (11.4), and no result of
   this registration ever licenses customer copy claiming an edge or a
   guarantee (11.8).
8. **Among picks that pass every check, list the longest price first rather
   than the most likely first? ANSWERED 2026-09-16 about 00:50Z, by replacing
   the question.** His words, verbatim, in reply to "Among bets that pass every
   check, what goes at the top of the card?":

   > "again based on cionfidence x value alrogirthm that we need to dial in"

   So neither of the two orders the draft offered is used. The ranking key is
   the score of section 4, descending, across both classes in one list
   (section 5). Question 10 below asks the one thing his answer does not
   settle: whether he wants plus-money picks grouped in their own section
   rather than interleaved.
9. **Should at most 3 of the card's 10 entries be plus-money picks? CLOSED
   2026-09-16 about 03:10Z as a single choice, and made one factor of the
   family: "Again, these are different strategies that we should be trying
   because maybe one of them profitable and one of them is not so like try and
   be more."**
   He was given the cap and its alternative and declined to pick one, saying
   both should run. So G14's sub-cap of 3 is **kept on the published card** and
   its removal runs as a registered paper arm: A2 is the published rule with
   G14 removed and nothing else changed, and A4 is the loose bar with G14
   removed (17.1). Neither can replace the published card except under 17.4.
   The reasoning that made this a question stands and is why the cap stays on
   the card customers see: the class is brand new, its record is empty,
   `docs/RESEARCH_STRATEGY_REPLICATION.md`'s SR1 treats a slice of this exact
   band as an open, unread hypothesis, and on the one board checked, removing
   the cap turned a 5-pick card into a 6-pick card at the strict bar and a
   7-pick card into a 10-pick card with 7 plus money at the loose one (14.3b).
   What he should know about it, from 17.8: A2 differs from the published card
   by about one pick a slate, so "the sub-cap did nothing measurable" is the
   most likely honest answer and it will take about 463 slate dates to say it.
10. **Should plus-money picks be listed in their own section below the main
    picks, instead of interleaved with them by score? CLOSED 2026-09-16 about
    03:10Z as a strategy question, and reopened as a display experiment: "Try
    different strategies on this. Try both separate I want. Try to try mix a
    hybrid."**
    He asked for all three: one list, separate sections, and a hybrid. None of
    the three changes a gate, a score, a rank, a selection or a ledger row;
    they change the order in which the same entries are rendered. So this is
    registered as a **product experiment** in 17.2, with three treatments (L1
    one list by score, the registered behaviour; L2 plus money grouped below
    main; L3 one list by score with a class divider and a jump link), assigned
    per visitor, measured on product metrics only, and bound by an invariant
    that the ledger row written for a slate date is byte-identical whichever
    layout the visitor saw. **Its outcome licenses a rendering change and
    nothing else.** A layout cannot beat the close and cannot return money; it
    enters no alpha-registry row, spends none of the family's multiplicity
    budget, and may never be reported as a strategy result. That sentence is in
    the registration in those words so that a future session cannot report "the
    hybrid layout won" as evidence about picks. Until the experiment ships, L1
    is what the card does, which is what his answer to question 8 says. Every
    plus-money entry carries copy C14 on its face and is graded on its own
    record under every treatment.
11. **His confidence band, "30-45+ percent", is shut below about +152,
    including +150, the first price he named. CLOSED 2026-09-16 about 03:10Z as
    a single choice, and made the other factor of the family: "Can we try both
    strategies and see which one is profitable? These are the types of
    strategies that we should be changing not necessarily just the type of
    bedding strategy like changing these differences are strategy changes. Does
    that make sense?"**
    He was asked to accept the band as shut or to loosen it, and answered that
    both should run. So `MARKDOWN = 0.038` and `BASE_EDGE = 0.010` **stand on
    the published card**, and a loose pair derived from his own two numbers,
    `MARKDOWN = 0.0090` and `BASE_EDGE = 0.0024`, runs as registered paper arms
    A3 and A4 (17.1). **One part of his direction is refused outright, by
    arithmetic and not by judgement, and no arm serves it**: at +150 the price
    itself breaks even at 40.00 per cent, so a bet with a true 30 per cent
    chance returns `0.30 x 2.5 - 1 = -0.250` per unit before any gate, any
    markdown and any vig. The bottom of his band is positive expectation only
    at +234 and longer, a 16-point slice at the very top of G4's range (17.0).
    What the loose pair does reach: under it his 0.30 floor is reachable at
    exactly one price, +250, where the bar is 29.99 per cent, and at +150 the
    band opens from 41.27 per cent upward, which is the whole
    positive-expectation part of his 30-to-45 range at that price less 1.27
    points of protection. G7's bar on the raw number under the registered
    constants is 55.03% at +100, 45.34% at +150, 43.86% at +160, 38.98% at
    +200 and 34.53% at +250 (4.6), and those are the numbers the published card
    keeps. Question 13 puts that consequence to him directly, because it is the
    part of his answer that will not be visible on the customer card for at
    least a season.
12. **NEW, and open. Register the variant family of section 17 as it is
    written: four arms over the two settings above, one published and three on
    paper, a Holm budget across six comparisons at a family-wise 0.05, floors
    of 463 counted picks and 93 slate dates for a promotion decision, a
    promotion rule fixed before any result, one promotion per family ever, and
    no readout of which arm is winning before the read date? Default: yes.**
    The last clause is the one he is most likely to object to and it is stated
    plainly rather than buried: he asked to see which strategy is profitable,
    and this registration will not give him a monthly scoreboard, because that
    scoreboard is the mechanism by which a family of four turns into a false
    finding, and because 17.8's arithmetic says such a readout would be noise
    for at least a year. What he does get every day is four ledgers on the same
    board, proof they screened the same pool, a per-date record of how far apart
    the arms are, and a harm check that can fire within weeks and only ever says
    stop. He does **not** get a running win-loss-and-units line for any paper
    arm; that line exists for the published card A1 only (11.10), because four
    of them side by side are the arm scoreboard this registration refuses. If he wants a
    different number of arms, that is a decision to take now: 17.3 prices the
    alternatives and a fifth and sixth arm cost every arm another 46 picks and
    9 slate dates.
13. **NEW, and open. The published card keeps the strict bar, so his 30-to-45
    band stays shut below about +152 on the card customers actually see, for at
    least a season and probably longer, while the loose bar runs only on paper.
    Register it that way? Default: yes.**
    This is the residual of question 11 and the single thing in this revision
    most likely to be different from what he pictured. His answer was "try
    both"; a family runs both, but only one of the two can be the card, and
    17.1 makes that A1 for a stated reason: A1's constants come from a
    measurement (`docs/PROP_CALIBRATION_2026-09-14.md`), the loose pair comes
    from a target, and the one measurement this repo owns warns in exactly the
    direction the loose pair runs. Publishing the loosest arm while its bar is
    untested would put the measured-worst slice on the customer card. If he
    wants the loose bar published instead, that is a different registration
    with A3 or A4 as its published arm, taken before `REGISTERED_UTC`, and it
    can never be made afterwards to rescue a thin card (11.7).
14. **NEW, and open. Register the layout experiment as a product experiment
    whose result licenses a rendering change and nothing else, enters no
    alpha-registry row, spends none of the family's multiplicity budget, and
    may never be reported as a strategy result? Default: yes.**
    He asked to try all three layouts, and all three are built. This question
    is only about what their result may be used for. A layout cannot beat the
    close and cannot return money, so a layout result is a product finding
    about what readers open, not a finding about picks. The invariant that
    enforces it is in 17.2: the ledger row for a slate date must be
    byte-identical whichever layout the visitor saw, asserted by a test, and if
    a layout can change a row the experiment stops.

One decision about V1, not V2, is not in this list: whether V1's nightly
calibration refit keeps reading the sealed window. It is set out in the
diagnosis, section 0, and Brey answered it on 2026-09-15 at about 22:35Z,
"Freeze it now": V1's nightly calibration refit is stopped and today's settings
are locked for the current card until V2 replaces it. That work is done
separately from this registration and its record is
`docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`. It changes no number here.


## 15b. Answers to questions 12, 13 and 14

**Answered 2026-09-17. Decided by Claude (Opus 5) under an explicit
delegation, not by the owner.** Asked to choose, he replied: "I need you to
take over, take charge, and make the correct choices ... I just don't need to
be answering these questions for you. You need to be solving them." That is
recorded verbatim because who decided a registration question, and on what
authority, is part of the registration.

**12 — the variant family, registered as written. YES, the default.**
Four arms, one published and three on paper, Holm across six comparisons at a
family-wise 0.05, floors of 463 counted picks and 93 slate dates, promotion
rule fixed before any result, one promotion per family ever, and **no readout
of which arm leads before the read date**.

The owner's standing wish is to know which strategies work, and he repeated
it when delegating. This registration still refuses the arm scoreboard, and
the reason is not bureaucratic: with four arms on one pool, a number you can
watch is a number you will steer by, and steering by it is precisely how a
family of four manufactures a winner that is not there. 17.8's arithmetic
says such a readout is noise for at least a year, so it would not even be
informative while it corrupted the result.

What he gets instead, daily and without waiting: four ledgers on one board,
proof they screened the same pool, a per-date record of how far apart the
arms sit, and a harm check that can fire within weeks and only ever says
stop. A KILL is fast and is real knowledge; a promotion is slow. That
asymmetry is the honest answer to "which ones are working", and it is met
properly by the separate strategy programme (Stage 19), not by weakening this
registration.

**13 — strict bar on the published card, loose on paper. YES, the default.**
A1's constants come from a measurement this repo owns
(`docs/PROP_CALIBRATION_2026-09-14.md`); the loose pair comes from a target,
and that one measurement warns in exactly the direction the loose pair runs.
Publishing the loosest arm while its bar is untested would put the
measured-worst slice on the customer card. The owner's 30-to-45 band
therefore stays shut below about +152 on the public card for at least a
season, and runs on paper beside it from day one. If the paper arm earns it,
promotion is the mechanism -- not an edit to this line.

**14 — the layout experiment licenses a rendering change and nothing else.
YES, the default.** No alpha-registry row, none of the family's multiplicity
budget, never reported as a strategy result. A layout cannot move a price, so
a layout result is a fact about what readers open. 17.2's invariant enforces
it: a slate date's ledger row must be byte-identical whichever layout the
visitor saw, asserted by a test, and the experiment stops if a layout can
change a row.

**What these answers cost, stated plainly.** The owner wanted to watch the
horse race. He is not getting that on this family, by my decision, and he
should hold me to the alternative: Stage 19 must actually deliver daily
forward-tested strategies with their deaths published, or this refusal was
just a refusal.

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
| 2026-09-16 | Draft correction, same instruction. The largest card this rule can list, 13 bets (10 picks and 3 fills), is stated as a departure from the owner's "3-10 bets" in G12, section 6, question 1 and the diagnosis's 2026-09-15 row, for him to rule on before registration. No cap was imposed and no gate changed. **Superseded by the row below: he ruled on it the same day** |
| 2026-09-16 about 00:45Z | Owner answer, question 1's open part: cap the card at **10 listed bets in total, picks and fills together**, replacing the draft's ceiling of 10 picks that let 13 be listed. G12 now counts every entry; the 13-bet state and every statement of it are removed from sections 0, 6, G12, question 1 and the diagnosis's 2026-09-15 row. The cost of the answer (an eleventh entry that passed every gate is refused a slot rather than a published fill being withdrawn) is written into section 6 and counted by D4 |
| 2026-09-16 about 00:50Z | Owner answer, question 2: **"No, allow earlier."** G10's lineup test is removed; a prop may be a pick before its lineup posts, priced off the batter's season-average plate appearances, as the live V1 card already does (`src/report/card.py:717`). The 15-game floor, the 2-book floor, one pick per player and G5 to G8 and G13 are unchanged, and the no-lineup disclosure becomes mandatory on the face (copy C15). Sections 0.1, 3 (G10), 8, 13 (C3, C6, C15), 14, 15 |
| 2026-09-16 about 00:50Z | Owner answer, question 5: yes, plus-money underdogs may be picks ("BOOM KEY QUESTION!... theres a lot of times where trhe underdog actuall makes more sens than the favorite... +100 to +250 poicks offer rally good value", quoted in full in 0.1 and question 5). G5's 0.50 test is replaced for plus-money candidates by a market band of 0.20 to below 0.50; G4 gains a +250 ceiling; a separately graded `PLUS_MONEY` class is created. Sections 0, 0.1, 3, 4, 5, 6, 10, 11.1, 11.3, 11.4, 11.5, 11.7, 11.8, 11.9, 12, 13, 14, 15 |
| 2026-09-16 about 00:50Z | Owner answer, question 6: **"even confidence of 30-45+ percent if high enough value (+150, +200 etc etc) we need an algorithm of value x confidence / likelihood."** G6 becomes a floor of 0.50 in the main band and **0.30** in the plus-money band, his own number, applied to fills as well as picks; the "algorithm of value x confidence" is registered as the score of section 4, used for both selection and ranking. Sections 3 (G6, G7), 4, 5, 15 |
| 2026-09-16 about 00:50Z | Owner answer, question 8: **"again based on cionfidence x value alrogirthm that we need to dial in."** The draft's price-first ranking key is replaced by the score, descending, with both classes interleaved in one list. Sections 4, 5, 15; new questions 9 and 10 added for the two things his answers do not settle (the plus-money sub-cap and the card's section order) |
| 2026-09-16 | Supersession recorded, not applied quietly: the standing directive of 2026-09-11 ("none of that price matters until we know it's a MORE THAN LIKELY BET...") is superseded for the card by the answers of 2026-09-16 about 00:50Z. Both quotes and both dates are in a new section 0.1, in question 5, in question 8 and in the diagnosis's owner-directive table. The directive is kept for the main band's 0.50 tests and is measured on its own record by new shadow rule E (section 10) |
| 2026-09-16 | Draft revision applying the four answers above, on the orchestrator's instruction, after an adversarial design competition and an independent judgement. New: the markdown of our own number (`MARKDOWN = 0.038`, section 4.1), the price-scaled required edge (`BASE_EDGE = 0.010`, section 4.2), the +250 ceiling (4.3), the score (section 4), G13 (no line shopping), G14 (plus-money sub-cap), the two price classes and their separate records (11.1), class-scoped floors, harm checks, verdicts and retirement (11.4, 11.5, 11.7), the statistical-power arithmetic moved into the evaluation plan (11.4), the failure-mode section (11.9), the constant-sensitivity table (4.5), descriptive lines D7, D8 and D9, shadow rules D and E, and copy C9b, C14 and C15. The section 14 illustration was re-run under the revised rule on the same already-seen pool (`scratchpad/value_score/final_rule.py`). No evidence threshold, floor, FAIL condition, verdict bar or stop date was loosened; the floors, the 300-pick and 60-date bars and all five stop conditions are unchanged and now apply per class |
| 2026-09-16 | Draft correction, on the orchestrator's instruction after a verification pass on the revision, no owner answer involved and **no gate, constant, threshold, floor, FAIL condition, verdict bar or stop date changed**. Six things the revision stated wrongly or left unsaid were fixed, each checked against the design pool first (`scratchpad/value_score/fix_verify.py`, `fix_verify2.py`). (1) **Customer truth:** copy C14 told every plus-money reader that our number does not make the side the underdog, while the number printed one line above it was 48.9%, 37.3% or 48.7% on the three entries the registration's own illustration produces. The clause is struck and replaced with C1's wording, which was already true of the class; sections 7 and 13 now state the rule that no plus-money string may imply our number makes the side more likely than not, and the build plan pins it as an assertion against a below-0.50 fixture. (2) **Shadow A** could not produce 14.3's list under section 10's definition. A is now defined as exempt from G14 with the reason written out, the printed list stands, and the build plan's two test rows are aligned so they cannot both pass. (3) **G6** is stated as strictly dominated by G7 on a pick at every allowed price, live only on a fill, in G6, 0.2 and 4.5. (4) **4.5's** claim that the value test would have refused the Guardians fill "in any case" is corrected: it is true of the pick path and false of the fill path. (5) **4.6** gains the smallest raw number a pick may carry at each price, and says plainly that the owner's 30-to-45 band is shut below about +152, including the +150 he named, and that its 30 per cent floor is unreachable everywhere; new open question 11 puts that to him. (6) **11.9** had the ranking mechanism backwards: the Kelly multiplier `d/(d-1)` falls from 2.600 at -160 to 1.400 at +250, so at equal edge the score penalises long prices; what lifts plus money is the smaller vig gap 4.4 already measured. Also corrected: 14.2 and the diagnosis's 5.3 said two of the three plus-money picks were inside his band when one is, and 1.1's inventory of measured numbers gained rows for `MARKDOWN` and `BASE_EDGE`, which come from the same document and window as G8's cap. Sections 0.2, 1.1, 3 (G6), 4.5, 4.6, 7, 10, 11.9, 13 (C14), 14.2, 14.3, 15 (status line, new question 11), 16 |

| 2026-09-16 about 03:10Z | Owner answer, question 7: **"Yes, publish with the line."** Every "Take" may rest on our own number clearing the price, provided copy C2's second sentence ships on the face of every pick at every rank and width. Question 7 is answered yes and is no longer open. Sections 0 (status), 7, 13 (C2), 15 (question 7), 16 |
| 2026-09-16 about 03:10Z | Owner answer, question 11, which does not choose: **"Can we try both strategies and see which one is profitable? These are the types of strategies that we should be changing not necessarily just the type of bedding strategy like changing these differences are strategy changes. Does that make sense?"** The markdown and required edge stop being a single choice and become one factor of the registered variant family (new section 17). `MARKDOWN = 0.038` and `BASE_EDGE = 0.010` stand on the published card; a loose pair derived from his own two numbers, `MARKDOWN = 0.0090` and `BASE_EDGE = 0.0024`, runs as paper arms A3 and A4. The part of his direction arithmetic refuses, a true 30 per cent bet at +150 returning -0.250 per unit, is stated in 17.0 and served by no arm. Sections 0, 10, 11.10, 12 (R7, R8), 14.3b, 15 (question 11, new question 13), 16, 17 |
| 2026-09-16 about 03:10Z | Owner answer, question 9, which does not choose: **"Again, these are different strategies that we should be trying because maybe one of them profitable and one of them is not so like try and be more"** G14's sub-cap of 3 stops being a single choice and becomes the second factor of the family. The cap stands on the published card; its removal runs as paper arms A2 and A4. Sections 0, 10, 11.10, 14.3b, 15 (question 9), 16, 17 |
| 2026-09-16 about 03:10Z | Owner answer, question 10, which replaces the question: **"Try different strategies on this. Try both separate I want. Try to try mix a hybrid."** The card's section order stops being a strategy question and is registered as a display experiment with three treatments (17.2), whose result licenses a rendering change and nothing else, enters no alpha-registry row and spends none of the family's multiplicity budget. New copy C16 (three plain layout labels) is added and checked against the banned lists. Sections 13 (C16), 15 (question 10, new question 14), 16, 17.2 |
| 2026-09-16 | Draft revision applying the four answers above, on the orchestrator's instruction. **New section 17**, the card-rule variant family: four arms over exactly the two disputed settings (17.1), the display experiment (17.2), the multiplicity budget with its arithmetic (17.3), the promotion rule (17.4), the retirement and tie rules (17.5), the mechanics and per-arm ledgers (17.6), the customer-isolation rules (17.7) and the honest limit (17.8). New 11.10 puts the family inside the evaluation plan. Section 10 becomes one list of everything computed on the same days, with a Kind column separating shadows from family variants. **Shadow D is deregistered before registration and absorbed by the loose arms**, which measure the same thing at a bar within 0.74 points of D's at every allowed price and, unlike D, carry a promotion rule; on the already-seen design board D and arm A3 produce the identical 7-pick card (`scratchpad/variants/shadow_d_vs_loose.py`). New R7 and R8 in section 12; new 14.3b. **No evidence threshold, floor, FAIL condition, verdict bar, harm-check arm, stop date or retirement result of the published card was loosened**: A1's own verdict still reads at 300 counted picks and 60 slate dates with the same five FAIL conditions and the same 2027 stop date, and the family's 463-pick, 93-date floors are a strictening that applies only to a promotion decision (11.10) |
| 2026-09-16 | Draft correction, same instruction, no owner answer involved and no number changed. Every reference to shadow D outside section 16 and this review record was repointed at the loose arms: 11.9's list of first measurements, 11.9's named instruments, 14.3's shadow table and the build plan's `SHADOW_D` parameter set, store constant and three test rows |
| 2026-09-17 | Claude (Opus 5) answers questions 12, 13 and 14 under Brey's explicit delegation ("I need you to take over, take charge, and make the correct choices ... I just don't need to be answering these questions for you. You need to be solving them."), all three at their stated default of YES: the variant family registers as written (12); the published card A1 keeps the strict bar while the loose pair runs only on paper (13); the layout experiment licenses a rendering change and nothing else, spends none of the family's multiplicity budget and enters no alpha-registry row (14). Recorded verbatim, with the reasoning for each, in new section 15b |
| 2026-09-23 | **Recorded change to the `v1_code_fingerprint` under 11.6, on the owner's ruling of 2026-09-22 ("Ceiling: restore the existing ten-entry limit"). No V2 number changes and no threshold moves.** `src/appstate/card_ledger.py` is a member of `V1_FINGERPRINT_FILES`, so repairing `_apply_ceiling_v2` moves the value recorded at the registration commit. LF-normalised: `1d79e1ba9038dac0bc43af784a86a13c1a19e80daeca82723bb6533243bacd2b` -> `ea858a545afbd2ecd981a951841cb537fb32bfcc085f8d3deecbdeafa3f793d7`; as checked out on the Windows tree (CRLF): `73613c2bf43f5de6217261dcb96b8d2c78dcc90c50c7dac60c597c1a2f13e9d0` -> `b760c4ba199c1148dd32bc3e05d8c7baaa740bfebbec3da1dec985d995d87ad7`. Both conventions are given because `code_fingerprint` hashes raw bytes and is therefore checkout-dependent, and because the value this section records for the registration commit does not reproduce from that commit's content under either convention -- both findings are written up in `docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md` (E3, E4), which this row does not attempt to fix. **The changed function is on V2's publish path only.** `_apply_ceiling_v2` is reached from `_lock_and_merge_v2`, which `publish_v2` calls; V1 publishes through `publish` and `_lock_and_merge` and calls neither. No V1 selection, probability or published row is altered by this change, so the 11.6 caveat is recorded here in full rather than being stated as a model change: the file moved, the V1 model did not. The commits behind it are not comment-only, so 11.6's disclosure applies and this row is it. `code_fingerprint` (11.2, V2) is **unchanged**: `card_ledger.py` is not in `V2_FINGERPRINT_FILES`, so V2's counted sample does not restart. Implementation version `v2_admission_2026_09_23`, stamped on every V2 row published from this change forward as `ceiling_admission_version` |
| 2026-09-22T14:35:00Z | **REGISTERED_UTC set. Registration commit.** Frozen parameter file `data/processed/card_v2_frozen_params.json` confirmed to exist, sha256 `64e96b4a9a8d56753fa38f2f0b97b51eb87b3c48adaf29db199eb10b6467db3d`. `code_fingerprint` (11.2, `V2_FINGERPRINT_FILES`) at this commit: `8a641de0ee76091972d482cc316b47924a474e063334d67056333513ee4d2061`. `v1_code_fingerprint` (section 10, `V1_FINGERPRINT_FILES`) at this commit: `10f5cac7191ff23d0afcebc1f3566c8e747b9e4286a1eacbbfd8be09bf1c92ee`. Checked directly before this commit: no row exists in `evidence/cards_v2.jsonl` or any family/shadow store, so no V2 pick and no paper-arm pick predates `REGISTERED_UTC`. SR1 (build plan T0c) was already run and published 2026-09-16, killed, `UNDERPOWERED_NULL`, before this instant and therefore before any plus-money pick; see `docs/SR1_RESULT_2026-09-16.md`, cited in the status line and 11.9. Status line changed from DRAFT to REGISTERED |

---

## 17. The card-rule variant family

Registered on the owner's answers of 2026-09-16 about 03:10Z (section 15), which
turned three single choices into strategy questions to be settled by running
them. This section is the whole of that answer: the arms, what each one is, how
many comparisons the family may spend, what promotes one, what retires one,
what happens on a tie, where the rows are written, and what the family cannot
deliver. Every clause here is fixed at `REGISTERED_UTC` and none may move
afterwards. A different arm, a different constant or a different bar is a new
family with its own registration and its own window.

**Family id:** `CARD_V2_VARIANTS_2026_09`

### 17.0 The part of his direction arithmetic refuses

Stated first, because the loose arm below is built to serve every part of his
direction that can be served and no part that cannot.

He asked for "30 to 45 per cent confidence at +150". At +150 the price itself
breaks even at **40.00 per cent**. A bet with a true 30 per cent chance at +150
returns `0.30 x 2.5 - 1 = -0.250` per unit, before any gate, any markdown and
any vig. That is not a threshold that can be loosened; it is what the price
means.

| Price | Break-even | Expected value per unit of a true 30 per cent bet |
|---|---:|---:|
| +150 | 40.00% | **-0.250** |
| +200 | 33.33% | **-0.100** |
| +234 | 29.94% | +0.002 |
| +250 | 28.57% | **+0.050** |

The bottom of his band is positive expectation only at **+234 and longer**, a
16-point slice at the very top of G4's allowed range. Everything below it is a
losing bet by definition. No arm in this family serves it, and no future
loosening of any constant can, because the refusal is arithmetic and not a
judgement (`scratchpad/variants/shadow_d_vs_loose.py`).

### 17.1 The family

Four arms. A full 2 x 2 factorial over exactly the two settings he disputed,
and nothing else.

**The first factor: the markdown and the required edge.**

- **STRICT**, the registered constants: `MARKDOWN = 0.038`, `BASE_EDGE = 0.010`.
  Both come from `docs/PROP_CALIBRATION_2026-09-14.md`, cited in 4.1 and 4.2:
  3.8 points of measured overconfidence in the 50-60 per cent bucket (n=212),
  and the 1.0 point spread between that bucket and the 60-70 per cent bucket
  (n=361).
- **LOOSE**, new and derived from his own two numbers before any result:
  `MARKDOWN = 0.0090`, `BASE_EDGE = 0.0024`.

**Where LOOSE comes from, so that it is a derivation and not a dial.** The raw
bar a pick must clear is `bar(price) = breakeven(price) + MARKDOWN +
BASE_EDGE * d(price) / d(-160)`. His two numbers give two constraints:

1. His bottom number reachable at his top price: `bar(+250) <= 0.30`, so
   `MARKDOWN + 2.1538 * BASE_EDGE <= 0.014286`.
2. His top number qualifying at his named price: `bar(+150) <= 0.45`, so
   `MARKDOWN + 1.5385 * BASE_EDGE <= 0.050000`.

Solving both as equalities returns a **negative** `BASE_EDGE` of -0.058: his own
band is wider relative to break-even at +150 than at +250, so no constant pair
hits both exactly. Constraint 1 is strictly binding and constraint 2 then clears
with room. Solving constraint 1 while preserving the registered 3.8 to 1.0 shape
of the protection gives a scale factor of 0.2399 on both constants, that is
0.009118 and 0.002399 unrounded. Rounded to the precision this registration
uses, and rounded so the constraint holds rather than grazes it: **0.0090 and
0.0024**, a ratio of 3.75 to 1. The LOOSE bar at +250 is then 29.99 per cent and
at +150 is 41.27 per cent, both inside his constraints
(`scratchpad/variants/shadow_d_vs_loose.py`).

**What the two settings do, on the raw number a pick must carry:**

| Price | STRICT bar | LOOSE bar | Difference |
|---:|---:|---:|---:|
| -160 | 66.34% | 62.68% | 3.66 pt |
| -110 | 57.36% | 53.56% | 3.79 pt |
| +100 | 55.03% | 51.20% | 3.84 pt |
| **+150** | **45.34%** | **41.27%** | 4.07 pt |
| +200 | 38.98% | 34.68% | 4.30 pt |
| **+250** | **34.53%** | **29.99%** | 4.54 pt |

Under LOOSE his 0.30 floor is reachable at exactly one price, +250. Under
STRICT it is reachable nowhere in the band (4.6).

**The second factor: the plus-money sub-cap.** `CAP3` is G14 exactly as section
3 registers it, at most 3 plus-money picks a day. `NOCAP` removes G14 entirely,
so plus-money picks are limited only by G11's one-per-game and G12's ceiling of
10 entries.

**The four arms:**

| Arm | Rule id | MARKDOWN | BASE_EDGE | G14 sub-cap | Status |
|---|---|---:|---:|---:|---|
| **A1** | `DAILY_CARD_BEST_BETS_V2` | 0.0380 | 0.0100 | 3 | **published to customers** |
| A2 | `DAILY_CARD_BEST_BETS_V2_VAR_STRICT_NOCAP` | 0.0380 | 0.0100 | none | paper |
| A3 | `DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_CAP3` | 0.0090 | 0.0024 | 3 | paper |
| A4 | `DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_NOCAP` | 0.0090 | 0.0024 | none | paper |

**Everything else is identical across all four**, and this list is exhaustive:
G1 to G13 unchanged, G4's band -160 to +250, G5's market bands, G6's floors of
0.50 and 0.30, G8's 10-point disagreement cap, G9, G10's 15-game floor with no
lineup test, G11's dedup, G12's ceiling of 10 entries, the floor of 3, the fill
rule, the Kelly-on-marked-down-number ranking key of sections 4 and 5, the
order of operations of section 5, the lock and withdrawal rules of section 9,
copy C2's honesty line on every pick, and the frozen model of 11.2. An arm that
differs in anything not in the table above is not an arm of this family.

**Why four and not more.** The 2 x 2 is the smallest design that answers both
of his questions and the interaction between them. Three one-factor arms cannot
tell "the cap matters" from "the cap only matters once the bar is loose", and
on the one board we have, that interaction is the entire story: with the cap on,
loosening the bar adds two main-band props and no plus-money pick at all
(14.3b). Going larger is priced rather than argued (17.3):

| Arms | Comparisons | Holm rank-1 bar | Sample multiplier | 300 becomes | 60 becomes |
|---:|---:|---:|---:|---:|---:|
| 2 | 2 | 0.025000 | 1.211 | 364 | 73 |
| 3 | 4 | 0.012500 | 1.421 | 427 | 86 |
| **4** | **6** | **0.008333** | **1.543** | **463** | **93** |
| 6 | 10 | 0.005000 | 1.696 | 509 | 102 |
| 8 | 14 | 0.003571 | 1.797 | 540 | 108 |

A fifth and sixth arm would cost every arm another 46 picks and 9 slate dates
on a design whose plus-money class is already expected to read `UNDERPOWERED`
(17.8). Four is where the budget stops.

**What is deliberately not in the family.** Shadow A (G6, G7, G8 and G14
removed) stays a shadow and is never promotable: its top three picks on the
design board are the three largest model-over-market gaps, which is exactly the
slice `docs/PROP_CALIBRATION_2026-09-14.md` measured hitting 40.6 per cent
against a 62.1 per cent claim (14.3). Shadow C (-150) and shadow E (the
superseded likely-first rule) stay shadows: he settled -160 on 2026-09-15 and
did not reopen it, and E is a retired directive. Shadow D is deregistered and
absorbed by A3 and A4 (section 10). Shadows compute, publish losers and inform.
Only family arms can be promoted, and only family arms spend the alpha budget.

**Which one customers see, and why.** A1. It is the only arm whose constants
come from a measurement rather than from a target, and the one measurement this
repo owns warns in exactly the direction LOOSE runs (0.2). Publishing the
loosest arm while its bar is untested would put the measured-worst slice on the
customer card. A2, A3 and A4 run in paper on the same games, in the same
publish runs, and are never served. Question 13 puts that consequence to the
owner directly.

### 17.2 Layout is a display experiment, not a strategy

He asked for one list, separate sections and a hybrid (question 10). None of the
three changes a gate, a score, a rank, a selection or a ledger row. They change
the order in which the same entries are rendered. It therefore runs as a product
experiment, entirely separate from the family:

- **Three treatments.** **L1**, one list by score, which is the registered
  behaviour of section 5. **L2**, plus-money picks grouped below main-band
  picks. **L3**, a hybrid: one list by score with a class divider and a jump
  link. Labels from copy C16 only.
- **Assignment.** Per visitor, sticky, recorded in the web analytics store and
  never in `evidence/`.
- **Measured on product metrics only:** which entries get opened, whether the
  record page is reached, session length, return rate.
- **Hard invariant, enforced by a test.** The ledger row written for a slate
  date is byte-identical whichever layout the visitor saw. Selection and
  grading happen before rendering. If a layout can change a row, the experiment
  stops.
- **This is never a strategy result.** A layout cannot beat the close and cannot
  return money. Its outcome licenses a rendering change and nothing else. It
  enters no alpha-registry row, spends none of the family's multiplicity budget,
  and may never be reported as evidence about picks. Written in those words so
  that a future session cannot report "the hybrid layout won" as a finding about
  the card.

### 17.3 The multiplicity budget

**The hazard, in numbers.** With k independent tests at the usual 5 per cent
bar, the chance at least one clears by luck alone is `1 - 0.95^k`. At k=6 that
is **26.5 per cent**. Publishing whichever arm looked best would mean selling
variance about one time in four.

**Method: Holm-Bonferroni at a family-wise alpha of 0.05**, the same correction
11.6 already applies to its shadow comparisons. Holm rather than plain
Bonferroni because it is uniformly more powerful and controls the same
family-wise error rate with no extra assumption.

**The 6 charged tests are the promotion decisions only.** They are the
comparisons that can move the customer card, and they are the only reads this
budget licenses to move anything.

**The family also publishes 8 one-sample reads that this budget does not
charge**, and they are named here so that nobody later mistakes one for a
result: A1's own 11.5 verdict per class, and each paper arm's own 11.5 verdict
per class at the ordinary 300 and 60 floors (11.10), which is 2 + 6 = 8 reads
at the uncorrected 5 per cent bar. At 8 such reads, `1 - 0.95^8` is **33.7 per
cent** that at least one reads PASS on noise alone. They are not charged
because none of them can promote anything: clause 4 of 17.4 makes an arm's own
PASS a necessary condition inside a conjunction, never a sufficient one. What
they are is **descriptive reads that license nothing on their own**, under
11.8's `INCONCLUSIVE` rule word for word, and every publication of one of them
prints the count of how many such reads this family produces, **8**, beside it.
A sentence of the form "A4's plus-money picks beat the close" is such a read,
is published with that 8 beside it, and is never reported as a finding about
which strategy is better.

**The family is k = 6 comparisons**: three challengers (A2, A3, A4) against the
incumbent A1, each read once for `MAIN` and once for `PLUS_MONEY`. The two
classes are corrected inside one family rather than as two families of three,
because the owner's question is one decision and either class can carry it; two
families of three would leave the overall error at about 9.75 per cent.

**The ladder, fixed now.** Sort the six p-values ascending and compare `p(i)`
against `0.05 / (6 - i + 1)`. Stop at the first failure; every comparison after
it fails too.

| Rank | Bar |
|---:|---:|
| 1 | 0.008333 |
| 2 | 0.010000 |
| 3 | 0.012500 |
| 4 | 0.016667 |
| 5 | 0.025000 |
| 6 | 0.050000 |

The worst-case bar is **0.008333**, a 6.0x tightening.

**The ladder needs all six p-values at once, and 17.8 says they will not exist
at once.** A4's comparison may read in 2027, A3's in 2028, A2's is expected to
read `UNDERPOWERED`, and A3's `PLUS_MONEY` comparison may never read at all. A
Holm rank is a function of the p-values actually observed, so a comparison read
alone, with five siblings absent, has no determined rank: rank 1 of 6 is
0.008333 and rank 1 of 1 available is 0.050000, a 6.0x difference a future
reader could take in good faith. So the bar is registered flat rather than
ranked:

- **Any comparison read while any other comparison in this family is unread is
  judged at a fixed Bonferroni bar of 0.008333.** No rank is computed and no
  sibling's absence loosens anything.
- The Holm ladder above applies only in the one case where all six p-values
  exist at the same read, which this design does not expect.
- **A comparison is read once.** It is never re-read at a looser bar after its
  siblings expire as `UNDERPOWERED`, are retired, or run out of calendar. An
  expired sibling frees no alpha.
- Every hypothesis row therefore carries `alpha_declared` **0.008333** at
  registration, which is a registered number rather than a rank that does not
  yet exist.

**What the bar costs in sample.** At 80 per cent power, two-sided, the required
n scales as `((z(1 - alpha/2) + z(0.80)) / (z(0.975) + z(0.80)))^2`. With
`z(0.975) = 1.9600`, `z(0.80) = 0.8416` and `z(1 - 0.008333/2) = 2.6383`, the
multiplier is `(2.6383 + 0.8416)^2 / (1.9600 + 0.8416)^2 = 12.109 / 7.849 =
1.5428`. So the promotion floors are the registered floors inflated by that
multiplier and rounded up: **463** counted picks with a CLV%, **463** graded WIN
or LOSS, **93** distinct slate dates, per arm and per class (11.10). This is a
strictening, which `docs/VALIDATION_CRITERIA.md`'s amendment rule permits at any
time, and it satisfies `docs/ARCHITECTURE_BETTING_ENGINE.md` G6 (300 forward
selections, 60 ledger days) with margin.

**The sample that matters is the discordant one.** The arms screen the same
board. On a day when two arms hold identical pick sets, their paired daily CLV
difference is exactly zero and carries no information, only a data point that
shrinks the apparent variance. So the floors above are floors on **discordant
counted picks**: picks held by exactly one of the two arms being compared, of
the class being read. Each arm must separately meet its own 463 and 93 for its
own 11.5 verdict as well.

**Where the spend is recorded.** `data/research/alpha_registry.jsonl`, through
`src/research/alpha_registry.py`, at the registration commit:

- One `sweep` row, id `card_v2_variant_family_2026-09-16`, family `daily_card`,
  `spec_id` `DAILY_CARD_BEST_BETS_V2_FAMILY`, sport `mlb`, `market` the card's
  market, `alpha_declared` `0.05` (family-wise, Holm), `candidates_evaluated`
  **6**, `data_window` `{discovery: null, replication: "forward from
  REGISTERED_UTC", sealed_untouched: true}`, `source_doc`
  `docs/PREREG_CARD_V2.md` section 17, `code_hash` of the variant runner. This
  follows the module's own precedent, cited in its docstring: Evolab Phase 2B is
  one `sweep` row charging 8,811 internally, never expanded into per-candidate
  rows.
- **Six `hypothesis` rows, one per challenger per class**, with ids
  `DAILY_CARD_BEST_BETS_V2_VAR_STRICT_NOCAP:MAIN`,
  `DAILY_CARD_BEST_BETS_V2_VAR_STRICT_NOCAP:PLUS_MONEY`,
  `DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_CAP3:MAIN`,
  `DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_CAP3:PLUS_MONEY`,
  `DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_NOCAP:MAIN` and
  `DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_NOCAP:PLUS_MONEY`, each with
  `alpha_declared` **0.008333**, the fixed bar registered above. One row per
  comparison, not one per arm, because `record_verdict()` keys its append-only
  guard on the id alone and a verdict row carries no class field: three ids for
  six reads would raise on the second class of each arm, years after
  registration, at the moment the family is finally readable
  (`src/research/alpha_registry.py`, `record_verdict()`, which refuses any
  second verdict for an id unless its result is exactly `withdrawn`). The two
  classes are never pooled into one verdict, which 11.1 forbids, and no id is
  registered after `REGISTERED_UTC`, which would add uncharged rows.
  `register()` refuses a second row per id and `record_verdict()` refuses a
  second verdict, so the append-only discipline holds with no special handling.
- **How to read the two together, checked against the module rather than
  assumed.** `total_searched()` keeps `hypotheses` and `sweep_candidates` in
  separate buckets and never folds a sweep's `candidates_evaluated` into the
  `hypotheses` count, so it does not double-count. But a reader who adds the two
  buckets would charge this family 12 for a spend of 6. **The family's spend is
  the sweep row's `candidates_evaluated` of 6**, and every published statement
  of it says so and names the six hypothesis rows as the per-comparison verdict
  anchors they are, not as additional searches.

### 17.4 The promotion rule

Written before any result exists. Every clause is fixed at registration and none
may move afterwards.

A paper arm replaces A1 as the published card only if **all eight** hold for one
price class, and **a promotion carries only the class it was won on**:

1. **Sample.** Both arms have at least 463 counted picks of that class with a
   CLV% and at least 463 graded WIN or LOSS, across at least 93 distinct slate
   dates; **and** the discordant set between them holds at least 463 counted
   picks of that class across at least 93 slate dates on which the two arms'
   pick sets differed. Fills count toward none of these, exactly as in 11.1.
2. **Primary metric.** Mean CLV% on the discordant set, computed by
   `src/report/clv.py` against the price actually taken, vig included, in the
   direction of the challenger. Where every arm's pick set is a superset of
   A1's, as it was on the design board (14.3b), the discordant set is the picks
   the challenger adds and the question reduces to a one-sample read: do the
   added picks beat the close? Where an arm also drops an A1 pick, both
   directions are computed and published and the statistic is the signed
   difference. The symmetric difference is computed in both directions on every
   read, because G11's dedup and G12's ceiling can reshuffle when the scores
   change and nesting is not guaranteed by construction.
3. **Margin.** Which test runs is fixed by the shape of the discordant set and
   not chosen at the read, and the bar is +1.5 percentage points in both cases:
   - **Superset case**, where the incumbent holds no picks of that class in the
     discordant set, which is the case the design board produced (14.3b, every
     arm a strict superset of A1): the statistic is the **added picks' own mean
     CLV%**, and the bar is **at least +1.5 percentage points against zero**.
   - **Mixed case**, where both sides hold discordant picks: the statistic is
     the **signed difference** between the two arms' mean CLV% on the
     discordant days, and the bar is **at least +1.5 percentage points** on
     that difference.
   The +1.5 is **this document's own choice** of margin, registered here before
   any result. `docs/VALIDATION_CRITERIA.md` sets +1.5 as a one-sample PASS bar
   against zero for mean CLV, which is the superset case above; using the same
   number as a between-arm margin is this registration's decision and is not
   inherited from that document. Stated plainly because a margin can be cleared
   by a challenger at -0.5 per cent against an incumbent at -2.0 per cent;
   clause 4, not this clause, is what refuses that; **and** the lower bound of the
   bootstrap interval on the difference (10,000 resamples over slate dates, seed
   20260915) is above zero at that comparison's registered bar of 0.008333
   (17.3), or at its Holm rank only in the single case where all six p-values
   exist at the same read.
4. **The challenger passes on its own.** It independently reads PASS on its own
   11.5 verdict for that class: at least 55 per cent beating the close, mean
   CLV% at least +1.5 per cent, and no FAIL condition. **A challenger that
   merely loses less than a failing incumbent is not promoted.** If A1 FAILs,
   11.7's retirement result applies and that class stops publishing; it is not
   handed to the least-bad arm.
5. **ROI is secondary and can never promote alone.** ROI with its bootstrap
   interval is published for both arms and for the discordant set. A positive
   CLV read alongside an ROI interval entirely below zero triggers the 11.5
   investigation before anything is promoted. ROI can block a promotion; it can
   never cause one.
6. **No harm stop.** An arm carrying a `HARM_STOP` on that class can never be
   promoted, at any CLV, ever. A `HARM_STOP` is not reversed by a later read.
7. **Owner sign-off**, `docs/ARCHITECTURE_BETTING_ENGINE.md` G7, explicit and
   dated.
8. **Class scope.** The promotion changes the selection of the promoted class
   only. The successor card is the incumbent's constants on the class that did
   not promote plus the winner's constants on the class that did, and the
   successor's registration writes both in. A1's constants and A1's gates
   continue to govern the other class until that class wins its own promotion
   under these same eight clauses. This clause exists because A3 and A4 differ
   from A1 in `MARKDOWN` and `BASE_EDGE`, which govern the main band as much as
   the plus-money band (on the design board A3 doubles A1's `MAIN` card, adding
   Matt Olson u1.5 at -157 and Pete Alonso u1.5 at -150), so a whole-card
   cutover on a `PLUS_MONEY` read would put an arm's untested, or retired, or
   failing `MAIN` configuration in front of customers on evidence about a
   different class. That is exactly what 11.8 forbids: a PASS on one class
   licenses nothing about the other. An arm that is retired, FAILing or
   harm-stopped on a class can never supply that class's constants to the
   successor, at any CLV, ever.

**A promotion rescues nothing, and the mechanics that guarantee it are in
11.10:** the winner registers as a new rule id carrying only the promoted
class's selection with its counted sample starting
at zero, A1's record is closed and published as a named non-verdict read at the
same instant, every losing arm's full record is published, no constant is
tweaked and re-run, and **the family closes on promotion: one promotion per
family, ever.** A promoted arm may register its own family with its own budget
from scratch. Without that last clause the family would become an open-ended
search with a fresh alpha each time it failed.

### 17.5 Retirement, and the tie rule

**What retires an arm.**

- **HARM_STOP.** Either arm of the 11.4 harm check firing for a class retires
  that arm from the family for that class permanently. It keeps selecting,
  locking, grading and counting under its own id so its record is complete and
  its loser is published, but it is out of the running.
- **FAIL.** An arm that reaches its floors and reads FAIL on any 11.5 condition
  is retired for that class and published as a loser.
- **UNDERPOWERED.** Floors not met by the end of the **2028** MLB postseason,
  one season later than the published card's own stop date because the family's
  floors are 1.5428 times the registered ones, is `UNDERPOWERED` for that arm
  and class, published as a named non-verdict read with its counts. The
  published card's own stop date, the end of the 2027 postseason, is unchanged
  (11.4, 11.10).
- **No arm is ever retired by deleting it.** Every arm's ledger stays and every
  loser is published, which is the standing commitment of
  `docs/STRATEGY_LAB_PLAN.md` section 2 ("We publish the losers") applied here
  unchanged.

**If two arms qualify at once**, the tie-break is pre-registered and applied in
order, with no judgement:

1. The larger lower bound on the CLV difference against the incumbent, each at
   its own registered bar (17.3).
2. If still tied, the arm that differs from the incumbent in **fewer**
   registered settings, so a single-factor arm (A2 or A3) beats the
   double-factor arm (A4). Prefer the smaller change.
3. If still tied, **the incumbent stays.** Never both, never a blend of their
   constants, never "run them both live and see". A blend is a fifth arm that
   was never registered and never charged.

### 17.6 Mechanics: one capture, one board, four screens

The publish job builds the candidate pool **once** per publish run from the
newest captured board, then hands that same in-memory pool to each of the four
arms' selection functions. The arms differ only in three constants, so they need
no data the published card does not already fetch. **Zero additional API spend,
by construction rather than by policy.**

Enforced, not trusted:

- The variant runner takes the pool as an argument and its module must not
  import the capture client. A test asserts that (build plan T2v).
- Every row of every arm, A1's included, carries `pool_hash`, the sha256 of the
  shared candidate pool that produced the run's cards (R7). A reader can prove
  all four screened the same board, and a mismatch between arms on one publish
  run is a fault rather than a difference between rules.

**Ledgers.**

| Arm | File |
|---|---|
| A1 (published) | `evidence/cards_v2.jsonl`, unchanged |
| A2 | `evidence/cards_v2_var_strict_nocap.jsonl` |
| A3 | `evidence/cards_v2_var_loose_cap3.jsonl` |
| A4 | `evidence/cards_v2_var_loose_nocap.jsonl` |

R2's rule extends: a paper arm writes only to its own file and nothing writes to
`evidence/cards_v2.jsonl` but A1. R4's rule extends: no number anywhere adds a
paper pick to a published pick.

**Grading a paper arm uses identical machinery and no shortcuts.** A paper pick
locks under section 9's L1 to L3 on the same schedule, freezes its own price
from the shared board and never assumes the published card's price, grades flat
1 unit at its graded price, and takes its close from `src/report/clv.py` by the
same `closing_board` and `closing_consensus` calls, with the same
`CLOSING_BOARD_THIN`, `CLOSE_PRECEDES_DECISION` and stale-lead exclusions
counted by reason and never zero-filled. Paper arms produce fills too, graded
and published, and counted fills stay outside every metric exactly as 11.1
requires.

**Compute and storage, measured rather than asserted.** The screen is arithmetic
over roughly 112 to 140 candidate rows; four passes instead of one. On the
2026-09-15 pool the whole four-arm run including load and reporting completes in
well under a second. At about 16 publish runs per slate date (measured from
`evidence/cards_v1.jsonl`: 112 rows over 7 dates), the daily marginal cost of
the three paper arms is a few seconds of CPU. Storage, from the measured V1
ledger (mean row 12,355 bytes, 16.0 rows per slate date): about 193 KB per arm
per date at V1-sized rows, or 386 KB if V2 rows run to roughly double for their
frozen close calls, so **about 0.6 to 1.1 MB a day and 105 to 210 MB per
186-date season** for the three paper arms together. For scale,
`evidence/decisions_v2.jsonl` is already 53 MB
(`scratchpad/variants/budget.py`).

### 17.7 The customer never sees a paper arm

- The API and the card route read `evidence/cards_v2.jsonl` only.
- The record page's four headline figures stay exactly as R5 defines them, on
  A1's ledger alone (R8).
- A test in the shape of `tests/test_web_structure.py` asserts that no
  customer-facing template, route or serializer references any
  `cards_v2_var_` path or any `DAILY_CARD_BEST_BETS_V2_VAR_` rule id.
- Customer copy is unchanged apart from C16's three layout labels. The arms
  change no word on the page, so `tests/test_customer_language.py` and
  `tests/test_no_nothing_clears_the_bar.py` bind as before.

### 17.8 The honest limit

**The calendar comes first.** The 2026 regular season ends 2026-09-27
(`docs/SEASON_END_PLAN.md`), which is 12 counted slate dates from 2026-09-16.
Postseason games are published and graded but not counted (11.1). Then there is
no baseball until spring 2027, so the family's real sample begins in late March
2027.

**How long the family takes to separate its members**, at the discordance rates
of the design board and assuming a fresh board every day, which 2026-09-15 was
not:

The floor of 17.4 clause 1 is a floor on discordant counted picks **of the
class being read**, so the calendar is per class and not pooled. Counting the
design board's discordance by class:

| Challenger | Discordant `MAIN` per slate | Slates to 463 `MAIN` | Discordant `PLUS_MONEY` per slate | Slates to 463 `PLUS_MONEY` |
|---|---:|---:|---:|---:|
| A2 versus A1 | 0 | never reads | 1 | 463 |
| A3 versus A1 | 2 | 232 | 0 | never reads |
| A4 versus A1 | 1 | 463 | 4 | 116 |

So: **A4 versus A1** is the only comparison expected to read, and it needs about
**116** discordant slate dates on `PLUS_MONEY`, not the 93 an earlier draft of
this table printed by pooling both classes against a per-class floor. That is
roughly two thirds of the 2027 season, so a plausible first read late in 2027
rather than at the All-Star break. Its `MAIN` comparison needs about 463 and
should be expected to read `UNDERPOWERED`. **A3 versus A1** needs about 232 on
`MAIN`, roughly 1.2 seasons, so late 2028 at the earliest, and its
`PLUS_MONEY` comparison has zero expected discordance and **will never read**.
**A2 versus A1** needs about 463 on `PLUS_MONEY`, about 2.5 seasons, and should
be expected to read `UNDERPOWERED`; its `MAIN` comparison has zero expected
discordance and **will never read**. A2 is registered anyway, because "the sub-cap did
nothing measurable" is the honest answer to his question and must be reachable.
Those are the optimistic numbers: if a quarter of dates are stale, add a third
to every figure. On the one real publish instant we have, every arm produced
zero picks and the date contributed nothing.

**Telling a plus-money class apart from a favourite class on profit is out of
reach entirely.** 11.4's power arithmetic
(`scratchpad/value_score/power_calc.py`) puts it at 6,952 to 19,311 plus-money
bets for a two-sample read at a true 3 to 5 point ROI gap, and 4,710 to 13,082
to tell plus money apart from zero. At 463 counted picks the 95 per cent
interval on ROI is about plus or minus 11 points at +150. **Nothing in this
family will ever answer "which is more profitable" on profit**, and the owner
should be told that in those words rather than discovering it in 2028.

**The earliest readable signal is the harm check, not the verdict.** The harm
check's second arm fires on 50 counted picks of a class graded WIN or LOSS whose
raw number sits at least 3 points above the market's. On the design board every
pick of every arm clears that 3-point threshold (A1's gaps run 7.3 to 9.3
points, A4's 4.0 to 9.3), so the threshold is reached in 50 picks of the class,
not in some fraction of them:

Every figure below is rounded **up**, because a partial slate does not reach a
threshold:

| Arm | Plus-money picks per fresh slate | Fresh slates to 50 |
|---|---:|---:|
| A1 | 3 | 17 |
| A2 | 4 | 13 |
| A3 | 3 | 17 |
| A4 | 7 | 8 |

**A4's plus-money class can trip its harm check in about eight fresh slates and
A1's in about seventeen.** That is weeks, not years, and it is the only
fast-moving instrument this design has. It is one-way: it can stop "Take", it
can never award anything, and it cannot be rescued by a later good run. The
first harm arm (100 counted picks of the class with a CLV%) lands around 34
slates for A1's plus-money class and around 15 for A4's.

**What the owner should expect to learn, stated in advance.**

- **In one month (by 2026-10-16):** nothing about which strategy is profitable.
  Twelve counted regular-season dates, then postseason games published and
  graded but not counted. What he will have: four ledgers on the same board,
  proof they screened the same pool, a per-date record of how far apart the arms
  are (a count of differing picks, no arm's units line and no statistic), and
  possibly a first harm-check read on `PLUS_MONEY` if the boards are fresh. Anything else read as a result in October is a record, not a read.
- **In three months (by 2027-01-16):** the offseason, zero additional counted
  picks. The right moment for the work that does not need baseball: the 2025
  refit of the frozen parameter file (build plan T0a), the SR1 read that 11.4
  requires before the first plus-money pick, and the capture-chain work so that
  2027 does not repeat the 2026-09-15 stale board that gave every arm zero
  picks.
- **In one season (through 2027):** realistically one harm-check verdict per
  class per arm, a `MAIN` verdict for A1 around August 2027 as 11.4 already
  projects, a first readable A4-against-A1 comparison on `PLUS_MONEY` late in
  2027 at the earliest and only if the boards cooperate, and `PENDING` or
  `UNDERPOWERED` on everything else.
- **The single most likely outcome of the whole family, written here so it
  cannot be reported later as a surprise:** A4 trips its harm check, A2 reads
  `UNDERPOWERED`, A3's plus-money comparison never accumulates a discordant set,
  and the published card stays A1. A promotion would be the surprise, and it
  would be treated as one and verified twice before anything moved.

**What this design refuses to give him.** He asked to run both and keep whichever
is profitable. This gives him four fixed arms, a bar tightened 6.0x for the fact
that there are four, a promotion rule written before the first pick, and every
loser published. What it will not give him is a monthly readout of which arm is
winning, because that readout is the mechanism by which a family of four turns
into a false finding, and because the arithmetic above says such a readout would
be noise for at least a year. The instrument that will actually fire, and fire
soon, is the harm check, and it only ever says stop.

---

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
this file; the fourth is about V1. The draft stayed a draft: at that point
questions 2, 5, 6, 7 and 8 were open. He answered four of those five the
following morning; the table after this one records that. Only question 7, and
the two new questions his answers raised, are open now.

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
| medium | The card can list 13 bets (10 picks plus 3 fills) against the owner's "3-10 bets", and no document stated it | Applied, then settled by the owner | Confirmed: G12 counted picks only and section 6 keeps a fill when picks arrive later. No cap was imposed at the time, because each way of holding the total at 10 changes what goes on the public record and that is the owner's call. He was shown it and answered on 2026-09-16 about 00:45Z: 10 listed bets in total. G12 now counts every entry and the 13-bet state cannot occur |

The gate lists in the two tables above describe the draft as it then stood.
Under the revision of 2026-09-16 a fill passes G1, G2, G4, G5, G6, G8, G9, G10
and G13, and the base gates a board's candidate must clear to be counted
against the floor of 3 are the same nine. Nothing in those findings was
reopened; only the gate numbering and the fill's gate list changed.

The seven remaining items were read and left as they stand: the diagnosis
states the fill rule in plainer words than the registration and is an
abbreviation of it rather than a contradiction; the close-call counts, the
G12 and section 6 wordings of the fill trigger, section 1.1's present tense,
the freeze commit (now cited in section 10 and 16), the stale-price grading
(disclosed and owner-accepted) and the surviving "default" fragments change no
number and no rule.

### Owner answers of 2026-09-16, applied to the draft

Brey answered four more questions in chat, one at about 00:45Z and three at
about 00:50Z. All four changed this file. The draft stays a draft: questions 7,
9 and 10 are open, and registration still needs his explicit answer or his
acceptance of each default.

| Answer | Applied where | Note |
|---|---|---|
| "10 listed bets in total" (00:45Z) | 0, 3 (G12), 6, 11.3 (D4), 15 (question 1), 16 | Replaces the ceiling that counted picks only. The 13-bet state is gone from every document. The cost, an eleventh gate-passing entry refused a slot rather than a published fill withdrawn, is written into section 6 and counted |
| "No, allow earlier" (00:50Z, question 2) | 0.1, 3 (G10), 8, 13 (C3, C6, C15), 14, 15, 16 | The lineup test leaves G10; the 15-game floor is the whole of G10 now; the no-lineup disclosure becomes mandatory on the face. Matches V1's live behaviour, which the draft would have been stricter than |
| The plus-money answer (00:50Z, question 5) | 0, 0.1, 3, 4, 5, 6, 10, 11.1, 11.3, 11.4, 11.5, 11.7, 11.8, 11.9, 12, 13, 14, 15, 16 | Creates the `PLUS_MONEY` class with its own gates, its own record, its own floors, its own harm check and its own retirement result. Supersedes the 2026-09-11 directive for the card, with both quotes and both dates in 0.1 |
| "even confidence of 30-45+ percent... value x confidence" and "again based on cionfidence x value alrogirthm" (00:50Z, questions 6 and 8) | 3 (G6, G7), 4, 5, 15, 16 | Registers the score: a Kelly fraction on the marked-down number, used to select (with `required_edge`) and to rank, both classes in one list |

**How the revision was produced, and what was rejected.** Three independent
designs for the score were written against the same grounding report and judged
by a fourth reviewer who re-implemented all three against the design board
rather than trusting their own scripts. Two were rejected for reasons that
matter here and are recorded so they are not re-proposed: one shrank our number
80% toward the market's, which combined with G8's 10-point cap makes the main
band structurally unreachable (only candidates with a vig gap under 1 point can
pass, which is almost exclusively plus money); the other set the plus-money
band's required edge at 21.5 points, which `breakeven(+250) = 28.57%` makes
mathematically impossible for any sub-50% number at any allowed price, so its
0.30 floor was a dead letter. The design adopted here was then changed on the
judgement's instruction in nine ways: G11 is applied before G14 (the winning
design's own script had them the wrong way round and under-reported its own
output); a markdown of our number was added, which that design lacked
altogether; `BASE_EDGE` was re-derived from a measured overconfidence instead
of the market's vig gap; the sensitivity table was moved into the registration;
the ranking was interleaved rather than sectioned, and the sub-cap and the
section order were put to the owner as questions 9 and 10; G13 was added; the
prop supersession was recorded in its own dated form; the statistical-power
arithmetic was moved from a footnote into 11.4; the score cap was dropped
because it could not fire; and SR1 was made a precondition of the first
plus-money pick.

**What was checked.** Every customer string changed or added was scanned
against `HARD_BANNED`, `NEGATION_ONLY` and `NEGATORS` imported from
`tests/test_customer_language.py` and `BANNED_PHRASES` and `BANNED_JARGON`
imported from `tests/test_no_nothing_clears_the_bar.py`: 18 strings, 0
violations (`scratchpad/value_score/final_copy_check.py`). The section 14
illustration was re-run on the same already-seen pool under the revised rule
(`scratchpad/value_score/final_rule.py`), with the supporting counts, the
feasibility windows and the sensitivity sweep in
`scratchpad/value_score/final_extra.py`. Consistency of the band, the
constants, the gates, the floors, the ceiling, the sub-cap, the rule id and the
shared copy strings across this file, the build plan and the diagnosis was
checked by `scratchpad/value_score/final_consistency.py`.

### Verification pass on the revision (2026-09-16)

The revision above was reviewed again against the repo and against the design
pool, and six findings were applied. Each was re-derived before it was applied,
from `src.core.odds` and the 2026-09-15 candidate pool rather than from the
documents (`scratchpad/value_score/fix_verify.py` and `fix_verify2.py`); none
was accepted on the reviewer's word. **No gate, constant, threshold, floor,
FAIL condition, verdict bar, harm-check arm, stop date or retirement result
changed, and the sealed window was not touched.** Section 16's last row lists
what moved.

The finding that mattered most was customer truth. Copy C14, mandatory on the
face of every plus-money entry, told the reader that "the market makes this
side the underdog and our number does not", while the "Our number" figure
printed one line above it is 48.9%, 37.3% or 48.7% on the three plus-money
entries this rule produces on its own illustration board, and 41.1% raw on one
of them. The clause was struck, C1's already-true wording put in its place, and
the rule behind it written into section 7 and into the build plan's copy test
so it is an assertion against a below-0.50 fixture rather than prose.

Three findings were honesty gaps, all in the same direction: this file was less
exact about the plus-money class than about the main band. G6's floors were
credited as protections when G7 dominates both of them on the pick path; 4.5's
account of the one candidate the plus-money floor refused was right about picks
and wrong about fills; and 4.6 answered the owner's "30-45+ percent (+150,
+200)" with "reachable and reached" without saying that his band is shut at
+150 and that its 30 per cent floor is out of reach at every allowed price. The
last of those is now open question 11, because it is a decision he should take
and not a detail he should find later.

One finding was reproducibility: section 14.3's shadow A list could not be
produced by section 10's definition of A, and the build plan pinned both
readings. A is now registered as exempt from G14, with the reason written into
its row, the printed list stands, and both build-plan rows were aligned so a
test built from one cannot pass while contradicting the other. One was an
arithmetic error in the section written to be honest about the failure mode:
11.9 said the Kelly score grows with the decimal odds when `d/(d-1)` falls from
2.600 at -160 to 1.400 at +250. And one was completeness: 1.1's inventory of
measured numbers carried G8's cap but not `MARKDOWN` or `BASE_EDGE`, which come
from the same document and the same settled-outcome window.

Two further errors were found while checking those and are corrected in the
same pass: 14.2 and the diagnosis's 5.3 each said two of the three plus-money
picks sat inside the owner's confidence band when one does, and G6's main-band
floor of 0.50 is dominated by G7 exactly as the plus-money one is, which
neither document said.

**What was checked after.** The 19 customer strings, including both forms of
the new C14, against `HARD_BANNED`, `NEGATION_ONLY` and `NEGATORS` imported
from `tests/test_customer_language.py` and `BANNED_PHRASES` and `BANNED_JARGON`
imported from `tests/test_no_nothing_clears_the_bar.py`: 0 violations
(`scratchpad/value_score/final_copy_check.py`). The cross-document consistency
script, extended with a section that holds these six findings closed and
re-derives the band arithmetic from `src.core.odds` rather than reading it back
out of the prose. Those checks are scoped to the live text of the section each
one governs, because section 16 and this record quote the struck wording on
purpose and a whole-file search would read the record of a fix as the defect:
0 failures
(`scratchpad/value_score/final_consistency.py`).

### Owner answers of 2026-09-16 about 03:10Z, applied to the draft

Brey answered the four remaining questions in chat at about 03:10Z (8:10pm
Pacific 9/15). One of the four is a plain yes. The other three decline to
choose between the options they were given and say the disputed settings are
themselves strategies to be run against each other and judged on profit. All
four are quoted verbatim in section 15 and in section 16.

| Answer | What it closes | Applied where |
|---|---|---|
| "Yes, publish with the line." | Question 7, answered yes | 0 (status), 7, 13 (C2), 15 (question 7), 16 |
| "Can we try both strategies and see which one is profitable?..." | Question 11, closed as a single choice and made the markdown factor of the family | 0, 10, 11.9, 11.10, 12 (R7, R8), 14.3b, 15 (question 11, new 13), 16, 17 |
| "Again, these are different strategies that we should be trying..." | Question 9, closed as a single choice and made the sub-cap factor of the family | 0, 10, 11.10, 14.3b, 15 (question 9), 16, 17 |
| "Try different strategies on this. Try both separate I want. Try to try mix a hybrid." | Question 10, closed as a strategy question and reopened as a display experiment | 13 (C16), 15 (question 10, new 14), 16, 17.2 |

**How the family was produced, and the one thing it refuses him.** The design
was written before any variant was run against any board, and the promotion
rule, the budget, the floors, the tie-break and the retirement rule were fixed
before the illustration of 14.3b was computed. The hazard being controlled is
named in 17.3 in his own terms: six independent tests at a 5 per cent bar
produce at least one apparent winner by luck alone 26.5 per cent of the time.
The one thing the registration refuses him is the thing he asked for most
directly, a running answer to "which one is profitable": 17.8 says why, says
what he gets instead, and says it in advance rather than as an excuse later.

**What was checked.** The four arms were run against the same already-seen
2026-09-15 pool the rest of section 14 uses
(`scratchpad/variants/variant_family.py`), and the claim that shadow D
duplicates the loose arms was checked by re-running D on the same pool, where
it produces the identical 7-pick card to A3 in the identical order
(`scratchpad/variants/shadow_d_vs_loose.py`). The LOOSE constants were
re-derived from the owner's two numbers with `src.core.odds` rather than taken
from prose, and the expected value of a true 30 per cent bet at each of his
named prices was computed the same way. The multiplicity arithmetic, the Holm
ladder, the 1.5428 sample multiplier, the discordance calendar and the storage
figures were reproduced by `scratchpad/variants/budget.py`. `total_searched()`
in `src/research/alpha_registry.py` was read rather than assumed, and what it
does with a sweep row beside six hypothesis rows is written into 17.3.
`record_verdict()`'s append-only guard (`:353-362`) was read the same way: it
keys on the id alone and a verdict row carries no class field, which is why
17.3 registers one hypothesis row per comparison rather than one per arm.
Copy C16's three labels were scanned against `HARD_BANNED`, `NEGATION_ONLY` and
`NEGATORS` imported from `tests/test_customer_language.py` and `BANNED_PHRASES`
and `BANNED_JARGON` imported from `tests/test_no_nothing_clears_the_bar.py`.
Consistency of the variant table, the constants, the bars, the caps, the
ledgers and the shared copy strings across this file, the build plan and the
diagnosis was checked by `scratchpad/variants/family_consistency.py`.

**No evidence threshold, floor, FAIL condition, verdict bar, harm-check arm,
stop date or retirement result of the published card was loosened by this
revision.** A1 still reads its verdict at 300 counted picks of a class and 60
slate dates, under the same five FAIL conditions, with the same two harm-check
arms and the same 2027 stop date. The family's 463-pick, 93-date floors are
strictly larger and apply only to a promotion decision (11.10). The sealed
window was not touched.

### Verifier pass on the family, and the fixes it forced (2026-09-16)

An independent verifier re-implemented the family from the prose rather than
from the writer's scripts, reproduced 14.3b exactly, and reproduced every
multiplicity, bar and calendar figure. It refused the draft on six points.
All six are closed here, and no threshold of the published card moved.

1. **Six comparisons were planned against three registry ids.**
   `record_verdict()` refuses a second verdict for an id unless its result is
   exactly `withdrawn` (`src/research/alpha_registry.py:353-362`), and a
   verdict row carries no class field, so the second class of each arm would
   have raised years after registration. 17.3 now registers **six hypothesis
   rows, one per comparison**, and the naive bucket sum it warns about becomes
   12 against a spend that is still 6.
2. **The decision bar was undefined once the comparisons matured years apart.**
   A Holm rank needs all six p-values at once and 17.8 says they will never
   exist at once. 17.3 now registers a **fixed Bonferroni bar of 0.008333** for
   any comparison read while a sibling is unread, writes that number into every
   hypothesis row's `alpha_declared`, and states that a comparison is read once
   and is never re-read at a looser bar after a sibling expires.
3. **A promotion won on one class would have changed the other class's rule.**
   17.4 gains **clause 8**: a promotion carries only the promoted class's
   selection, the successor keeps the incumbent's constants on the class that
   did not promote, and an arm retired, FAILing or harm-stopped on a class can
   never supply that class's constants. 11.10 step 1 says the same in its
   mechanics. This is 11.8's class-scoped licence applied to the switch itself.
4. **17.8's separation calendar pooled the classes against a per-class floor.**
   The table is now per class: A4 needs about **116** `PLUS_MONEY` slates, not
   93, and about 463 on `MAIN`; A2's `MAIN` comparison and A3's `PLUS_MONEY`
   comparison have zero expected discordance and are stated as never reading.
5. **The budget charged the 6 comparisons but not the 8 one-sample reads the
   same design publishes.** 17.3 now names them, prints `1 - 0.95^8 = 33.7 per
   cent`, and binds every one of them to 11.8's licences-nothing rule with the
   count 8 published beside it.
6. **The margin clause specified two different tests and mis-attributed its
   bar.** 17.4 clause 3 now names the test per case, the superset case
   one-sample against +1.5 and the mixed case a signed difference against +1.5,
   and registers the +1.5 as this document's own choice rather than inherited
   from `docs/VALIDATION_CRITERIA.md`, which sets it as a one-sample bar.

Three smaller defects the verifier also found are closed with them: 11.10
allowed and forbade the per-arm running units line in consecutive sentences
while question 12 promised it, so that line is now **A1's only** and question 12
no longer promises it; the harm-check calendar rounded down in four places,
always toward firing sooner, and now rounds up (A2 13 slates, A4 8, and 34 and
15 on the first harm arm); and the build plan's stale `shadow-d` CLI target is
removed, which its own test already forbade.

**Nothing in this pass loosened the published card.** A1's verdict still reads
at 300 counted picks of a class and 60 slate dates, under the same five FAIL
conditions, the same two harm-check arms and the same 2027 stop date. Every
change above either tightens a bar, narrows what a result licenses, or corrects
a number in the direction that makes a read later rather than sooner. The
registration stays a **DRAFT**: questions 12, 13 and 14 are open.
