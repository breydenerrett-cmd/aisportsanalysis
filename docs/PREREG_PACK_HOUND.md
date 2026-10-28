# Pre-registration: the Pack Consensus hound

**FROZEN 2026-10-28, committed before the engine (`src/hounds/pack/pack_consensus_hound.py`) was written and
before the hound has placed or evaluated a single bet.** Paper only. Forward only: a replay of this hound is
refused and a replay never counts. No profit or edge is claimed. This is a hypothesis under test and a null is as
publishable as any other result. Companion docs: `docs/PREREG_HOUSE_PACK_V1.md` (runner, board, grading, CLV: all
unchanged and reused), `docs/PREREG_AI_HOUNDS.md` (the forward-only runner it rides), `docs/PREREG_HOUND_VERDICT.md`
(the referee).

## 1. The idea, and how it differs from Pack Leader

The owner's ask (2026-10-28): "the ultimate hound" built from the kennel's own decisions. The tested claim is
narrow: **when two or more hounds that have each independently beaten the closing price over a real sample agree on
a side, does that side beat the close?** Hounds that have not shown that are never asked.

`pack_leader` (docs/hounds/pack_leader.md) is a different thing and is not reused:

| | Pack Leader | Pack Consensus |
|---|---|---|
| Who votes | seven hand-picked hounds, fixed in code | every hound that passes a record test, recomputed daily |
| Evidence a voter is asked | none: any hound with no edge votes | mean CLV > 0 with a 95% lower bound > 0 over >= 30 forward bets |
| How it reads a vote | re-runs each voter's rule on the board | reads the voter's recorded ticket from the ledgers, written before the decision |
| Replayable | yes (it is a pure rule) | no (forward only: a replay would let today's record choose yesterday's voters) |
| Duplicated voters | counts them separately | counts one vote per lineage / rule family |

Overlap: both are "bet where hounds agree". The consensus hound is the version that has to earn its voters.

## 2. Membership rule (point in time, recomputed for each game's date)

A hound is a **voter** for a game dated D if, using only rows with `graded_utc` at or before the decision instant and
bets dated strictly before D:

1. It has **N = 30** or more FORWARD bets (`segment: "forward"`) with a measurable closing price (`clv_pts` not
   null). 30 is the smallest sample at which a date-clustered t interval is usable at all; below it the interval is
   mostly the t critical value. It is NOT a claim that 30 bets prove anything, which is why membership also needs
   the interval below and the hound's own gate needs 150 bets (section 5).
2. Its mean CLV is **> 0 and the lower bound of its date-clustered 95% interval is > 0** (`pack_settle.clustered_ci`,
   the same machinery the /hounds payload's `clv {n, mean_pts, ci_low}` uses). It needs at least two distinct dates.
3. It is **not** a control or entertainment hound: categories `random`, `simple`, `esoteric`, `numerology` and
   `baseline` are excluded (Coin-Flip Collie, Dartboard Dalmatian, Chalk Chihuahua, Home Dog Hank, the Numerology
   Newfie, Lunar Lab, the Gematria Hound and every baseline-kind hound). Pack Leader and this hound itself are
   excluded too (an ensemble of ensembles double counts). The Learner is allowed.
4. Only forward bets of the house ledger (`evidence/hounds_house_v1.jsonl`) and the AI/Learner ledger
   (`evidence/ai_hounds_v1.jsonl`) are read. Shadow challenger rows (`role: "challenger"`) are ignored.

Because rule 2 demands a positive LOWER bound, the pack may stay empty for a long time, possibly for ever. That is
the honest outcome if no hound has shown closing-line skill.

**Pack formed** means at least **3 voters from at least 3 different lineage families** (section 4) qualify.
Fewer: the hound bets nothing and says: "Not enough proven hounds yet to form a pack." (`Pack Consensus: not enough
proven hounds yet to form a pack` with the counts, on its page.)

## 3. Bet rule

* A game-market side is a candidate when **>= 2 lineage families** (one vote per family, section 4) recorded a
  ticket on that same side of that same game and market, with `written_utc` at or before the pack's own decision
  instant and before the game's start.
* The pack's **decision instant** is the runner's `now` for that pass (the AI runner's hourly pass). The pack bets the
  game only if its lock (60 minutes before the start) has passed and the start has not; the board, its
  **board-average price** and the grading are the pack's shared mechanics at that lock, so the price is the average
  of the books at the lock. A ticket written after the decision instant is invisible to it.
* The opposing side of the same market must have **zero** votes, and no voter ticket may back the other club in
  another market (moneyline vs spread), else it passes (one side per game).
* **Never -200 or worse** (the runner refuses it; the band is -199 to +400).
* Markets: moneyline, spread, total, in the sports the voters covered. One side per game: if several markets
  qualify, the one with more family votes, ties to moneyline then spread then total.
* Stake **1 unit flat**. **At most 3 bets per day** (`MAX_BETS_PER_DAY = 3`, the pack's `MAX_PER_DAY`), earliest
  locks first.
* It may pass any game and any day.

## 4. Independence: what counts as one vote

Voter tickets are not independent evidence when they come from one source. One vote per **lineage family**:

* A hound and its versions (champion `hound_version` rows, same `hound_id`) are one hound; challengers are ignored.
* Hounds sharing a rule family count once: `steamy_setter` and `contrary_corgi` (one line-movement signal read in
  opposite directions), `professor_paws` and `totals_terrier` (the one house run model), and every AI hound of one
  config `family` (the model is the family).
* If two members of a family agree the family casts one vote; if they disagree it casts none.

This reduces, and does not remove, dependence: all hounds read the same board, so agreement is partly the market
speaking. Stated, not fixed.

## 5. Evaluation, kill and fail criteria (stated in advance)

* **Primary metric: mean CLV (points, vs the closing fair probability, `pack_settle`'s `clv_pts`) over >= 150 forward
  bets**, with the date-clustered 95% interval. Units are secondary and never decide anything. The verdict is the
  referee's (`src/hounds/verdict.py`), unchanged.
* **Gate (pass).** At >= 150 measurable forward bets: mean CLV > 0 with ci_low > 0. Nothing is promoted or advertised
  before that; passing the gate still claims nothing about profit, only that it beat the close.
* **Fail.** At >= 150 bets: mean CLV <= 0, or ci_high < 0. A fail is published on the hound's page and the hound is
  retired by the same rule as any hound. 150 to 300 bets with 0 inside the interval is "inconclusive": keep
  collecting to 300, then it is a fail unless ci_low > 0.
* **Early stop.** After 60 measurable bets with ci_high < 0 the hound is stopped as a fail.
* **No rescue by threshold change.** N = 30, the lower-bound rule, 2 families, 3 voters, the -200 cap, 3 bets a day
  and the lock timing are frozen. A different value is a different, newly registered hound, never an edit of this one.
  A bug fix is recorded in the Changelog with its reason.
* **Losers are published.** Every bet shows on its page whatever the result; the voters and the reason are on each
  bet row.

## 6. Known risks (stated, not solved)

* **Survivorship / selection.** Voters are chosen BECAUSE their recorded CLV was positive. Choosing the best of many
  hounds on past CLV selects noise: with about 40 hounds, some will clear a 95% bound by chance. Regression to zero
  is the expected result. The forward-only, >= 150 bet gate on the pack's own bets is the only defence.
* **Correlation.** Section 4 reduces it. Residual: same board, same books.
* **Thin timing.** Voter tickets are written between the lock and the start by other runners; the pack's pass sees
  only what exists at its instant. Some agreeing games will be missed. That is a cost in bets, not a bias in the
  ones taken.
* **CLV is not profit.** Beating the close at the average price is the metric because it is measured per bet; it does
  not promise units.

## 7. Where it lives

Code `src/hounds/pack/pack_consensus_hound.py`; config entry `pack_consensus` in `config/ai_hounds.json` (family
`pack_consensus`, forward only); run by `src/hounds/ai_runner.py` with the Learner; its bets go to the AI hounds' ledger
(`ai_defs.ledger_path`: on the Fly volume in production, `ai_hounds_v1.jsonl`). It reads the house ledger
`evidence/hounds_house_v1.jsonl` (baked into the image, so a house ticket reaches the production runner when the
image is next redeployed: a lag of up to an hour, which only costs the pack bets) and the AI ledger above. The code,
config and evidence are in the Docker image (`COPY src/`, `COPY config/`, `COPY evidence/`).

## Changelog

* 2026-10-28: frozen. Same day, before any engine code: section 7 corrected to say where the ledgers physically live.
