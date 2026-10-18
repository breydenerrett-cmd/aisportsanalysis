# Pre-registration: the Desk and persona hounds

Committed before any forward bet. Written 2026-10-18 for the two AI-driven hound
families in `src/hounds/desk/`. Companion docs: `docs/DESK_HOUNDS.md` (how it
works), `docs/BRIEF_RUNBOOK.md` section "Desk and persona hounds" (the parent
session's steps), `docs/PREREG_HOUND_VERDICT.md` (the referee, unchanged and
not re-opened here).

Paper only. Nothing here places, sizes or routes a real bet. Nothing here
claims an advantage, a profit or a certainty.

## 1. What is being registered

Seven hounds, all `who_decided: "model"`, all fed by the same frozen fact
packet the AI analyst uses (`src/analyst/packet.py` for baseball,
`src/analyst/nfl_packet.py` for football), nothing else.

| Hound id | Name | Category | What it is |
|---|---|---|---|
| `desk_ai` | The Desk | `ai-desk` | a small AI trading-firm-style process: four analysts, a bull, a bear and a desk head who decides |
| `desk_sharp` | The Sharp | `persona` | one request, a fixed philosophy: bets only when the best quote beats the books' own de-vigged number |
| `desk_square` | The Square | `persona` | one request; a deliberate control: favourites and overs only |
| `desk_fader` | The Fader | `persona` | one request; fades the favoured side: underdogs, teams getting points, unders |
| `desk_weather` | The Weather Nerd | `persona` | one request; game totals and team totals only, weather and park |
| `desk_grinder` | The Grinder | `persona` | one request; unders and short favourites, small gaps only |
| `desk_historian` | The Historian | `persona` | one request; head-to-head and series history only |

The personas are archetypes. No real person's name or likeness is used.
The personas are one underlying model reading the same data under different
instructions; they are not independent opinions, and agreement among them is
not confirmation.

## 2. The decision menu (fixed, the same for every hound)

For each market slot in the frozen packet, a hound's decision is exactly one of:

* `TAKE <selection> at <price> <book>` with a stated probability that the
  selection wins, and the reasons and the strongest case against, each reason
  carrying packet paths with the values copied exactly; or
* `PASS`.

A hound lists only its TAKEs. A slot it does not list is a PASS. A hound that
lists nothing passes everything, which is a valid and expected outcome. The
price and book must be the selection's best quote in the packet (the packet's
`best`). Moneyline, run line or point spread, game total, team totals and
player props are all menu items where the packet prices them.

## 3. The code risk manager (the model cannot override it)

Applied in this order to every hound's TAKEs, whatever the model says. A TAKE
that fails a rule is struck to a PASS and the reason is saved. A strike by
rules R1 to R5 does not earn a new answer.

* R1 **Price in the data.** The price and book named must be the selection's
  best quote in the packet. Anything else is struck.
* R2 **The -200 cap.** A TAKE whose price taken, or whose board average
  price, is -200 or worse is struck. No exception, every market, every hound.
* R3 **Beat the market's own number.** The stated probability must be greater
  than both the books' de-vigged consensus probability for that selection (the
  packet's `fair_probability`) and the break-even probability of the board
  average price. A selection with no de-vigged consensus cannot be taken.
* R4 **The persona's own rule** (section 5), where the hound has one.
* R5 **At most 2 TAKEs per game per hound.** If more survive, the two with the
  largest margin (stated probability minus the break-even probability of the
  average price) are kept; ties go to slot order. The rest are struck.
* R6 **The checker** (`src/analyst/critic.py`, unchanged, and for football
  `src/analyst/nfl_analyst.py`'s additional number-line check). Every evidence
  path must resolve to a value in the packet and match it; every number in
  prose must be a packet number, a probability the hound states, or a
  calculation it declares and the checker recomputes; every person named must
  be a name in the packet; banned words are struck. A TAKE the checker strikes
  is a PASS ("could not be verified") and the checker's rejection lines are
  the only extra input a re-answer may receive (section 4).

Every stage answer, not only decisions, goes through the checker: the four
analyst reports and the bull and bear cases are held to the same number, path,
name and word rules.

## 4. The publication rule (the analyst pilot's rule, per stage)

Taken from `src/analyst/pilot.py` and enforced by the same attempt record code.

1. The first answer to a stage's request is the candidate.
2. It may be answered again only because the checker rejected it (a struck
   finding or call, a withheld text, or a failed shape check), and at most
   twice: three attempts per stage.
3. The only extra input a re-answer receives is the checker's rejection lines,
   word for word.
4. Every attempt is saved. The latest attempt is the one used. A response that
   was never checked, one that is not the latest, one that follows an
   unrejected attempt, and a fourth attempt are refused.
5. Nobody picks among answers. A stability sample is never offered for
   publication.
6. Later stages receive only checked material from earlier stages: a report's
   text if the checker passed it, and only the findings that were not struck.
7. If the desk head is never cleanly answered, the latest attempt is used and
   its struck calls are passes; if the head produced no usable answer the
   Desk passes the game.
8. `publish` refuses: a rehearsal; a game that has started or whose start is
   unknown; a packet built more than 90 minutes earlier
   (`config/analyst.json` `pilot.max_packet_age_minutes`); a request prompt
   that has changed since prepare; a game already published for that hound.

Caps per run: at most 2 games, and at most 30 subagent answers (every attempt
counts).

## 5. The persona rules (code, so the copy is true)

The system text of each persona states its philosophy. Where a philosophy is
checkable from the packet, code also enforces it as rule R4:

* **The Sharp** (`desk_sharp`): the break-even probability of the best quote is
  below the books' de-vigged consensus probability for that selection.
* **The Square** (`desk_square`): only the moneyline favourite, or the Over on
  the game total. No props, no team totals, no spreads, no unders, no
  underdogs.
* **The Fader** (`desk_fader`): only the moneyline underdog, a side that gets
  points on the run line or point spread, or an Under (game total, team total
  or prop). No favourites, no overs, no sides that lay points.
* **The Weather Nerd** (`desk_weather`): only the game total and the team
  totals.
* **The Grinder** (`desk_grinder`): only an Under, or a moneyline favourite
  whose best price is -150 or shorter (nearer to even); and the stated
  probability may exceed the books' de-vigged consensus by at most 5
  percentage points (a larger claimed gap is treated as more likely a mistake
  than a finding).
* **The Historian** (`desk_historian`): every packet path cited in a TAKE's
  reasons must be a price path (`markets.`), a game path (`game.`) or the
  head-to-head / series history section
  (`sections.matchup_history` for baseball,
  `sections.matchup.values.head_to_head` for football), and at least one must
  be in that section.

The packet holds no betting percentages, no ticket counts and, for baseball,
no line-movement history. The Square and the Fader therefore use the market
favourite and the over as their stand-in for what a casual bettor takes. That
is a stated proxy, not a measurement of the public.

## 6. Rows, forward only, and grading

* Rows go to the hash-chained ledger `evidence/hounds_desk_v1.jsonl`
  (`src/ledger/chain.py`): definition rows (`kind: "hound"`), bet rows
  (`kind: "hound_bet"`), graded rows (`kind: "hound_graded"`) and one
  `desk_game` row per published game.
* Forward only. There is no replay segment for these hounds. A model cannot be
  replayed honestly on boards it might have seen discussed. Every row is
  `segment: "forward"`; the first row is written at registration, which is the
  first `publish`.
* A bet row carries `price_best` (the price taken, the best quote in the
  packet), `price_average` (the mean decimal price of the books quoting that
  selection in the packet, as an American price), `consensus_fair`, the stated
  probability, `lock_utc` (the instant of the board the hound read: the
  packet's `built_at`), `published_utc` (when the row was written), the packet
  hash and the transcript hash.
* Grading uses the analyst's grading code (the card ledger's own `grade_pick`
  and `grade_total_pick`, and the props settlement rule) against the same
  results. Flat one-unit paper stakes, settled at the best price and at the
  average price. A push returns the stake. Nothing is ever graded as a bet
  that was a PASS.
* The closing-price comparison (`close_price`, `clv_pts`) is the referee's
  (`src/hounds/stats.py`, from the odds store by `event_id`); the graded row
  leaves those two fields null rather than guess them.

## 7. The honest expectation

These hounds are model-written analysis. They are unproven. They are judged by
the same closing-price referee as every other hound
(`docs/PREREG_HOUND_VERDICT.md`): `TOO EARLY` until 150 bets have a
measurable closing price, then one of the three labels from the closing-line
comparison, whichever way it falls. Units never move the label. At most two
games a run and at most two TAKEs per hound per game means volume is low, so
reaching 150 measurable bets will take weeks, and most days a hound will pass.

A language model's answers are not stable: two answers to the same frozen
request can differ. A published decision is one model reading, the first one
that cleared the checker, not the model's view. The checker proves that quoted
facts are true and that a call is coherent; it cannot prove a true fact is a
good reason. The market is the benchmark, the market is hard to beat, and the
expected outcome of an unproven process is that it pays the book's margin. If
the record shows that, it is published like any other result. No hound here is
exempt from the referee's mechanical retirement rules.

## 8. Changes

The prompt text lives in `src/hounds/desk/roles.py`; `config/desk_hounds.json`
carries each hound's prompt version and sha256, and every row carries them. A
change to any prompt, schema, risk rule or persona rule after the first
forward bet is a new version: new hound ids, an empty record, and the old
hounds keep their record. No threshold is changed to rescue a record.
