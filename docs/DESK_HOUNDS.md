# The Desk and persona hounds

Two AI-driven hound families in the LineHound Hounds race (`docs/HOUNDS.md`). Paper
only, not advice: no hound stakes money, and nothing here tells anyone what to bet.
Pre-registered before any forward bet in `docs/PREREG_DESK_HOUNDS.md`; the steps a
parent Claude Code session runs are in `docs/BRIEF_RUNBOOK.md`, "Desk and persona
hounds". Code is `src/hounds/desk/`.

## What they are

The idea is borrowed from two open-source projects: TradingAgents (a trading firm of
specialised analysts, a bull and a bear who debate, a trader, a risk manager and a
portfolio manager who approves or rejects) and ai-hedge-fund (analyst agents with
distinct investing philosophies who disagree about the same asset). Nothing is copied
from either; the shape of the idea is used and everything is tied to this project's
discipline: one frozen fact packet, a checker that proves every number, and a referee
that judges against the closing price.

| Hound | Family | In one line |
|---|---|---|
| The Desk (`desk_ai`) | ai-desk | four analysts, a bull, a bear, a desk head who decides or passes the game |
| The Sharp (`desk_sharp`) | persona | only bets when the best quote beats the books' own de-vigged number |
| The Square (`desk_square`) | persona | favourites and overs; the deliberate control |
| The Fader (`desk_fader`) | persona | underdogs, sides that get points, unders |
| The Weather Nerd (`desk_weather`) | persona | game and team totals only |
| The Grinder (`desk_grinder`) | persona | unders and short favourites, small gaps only |
| The Historian (`desk_historian`) | persona | head-to-head and series history only |

They are one underlying model reading the same data under different instructions.
Agreement among them is not confirmation, and a split is not a signal. Personas are
archetypes; no real person's name or likeness is used.

## One game, step by step

```
prepare      freeze the data (the analyst's own packet) and write prepare.json
wave 1       analyst_stats, analyst_situation, analyst_market, analyst_injury   +  six persona requests
wave 2       bull, bear         (each reads the four CHECKED reports)
wave 3       head               (reads the data, four reports, bull and bear; decides)
publish      bets, transcript, disagreement table, ledger rows
grade        after the game
```

Every stage is one request file answered by one foreground Sonnet subagent that reads
only that file and writes only its answer file. The model never sees another stage's
request. A later stage is built from earlier stages' checked material only: a report's
text if the checker passed it, and the findings the checker did not strike.

A request file has the shape of the analyst pilot's `request.json` (the body an API
call would be sent): the role's system text, the schema, and one user message holding
the frozen data, the slot ids, and for later stages the checked material. A re-answer's
only extra input is the checker's rejection lines. `tests/test_desk_hounds_flow.py`
pins that a first-wave request contains the packet and the role text and nothing else.

### The roles

* Stats analyst: team and player numbers, sample sizes, thin windows.
* Situation and news analyst: rest, travel, schedule, park, weather (or that none is
  stored), standings, transactions. Only facts that are in the data.
* Market analyst: how many books quote each side, the spread of quotes, the books'
  de-vigged number, the age of each quote, whether the markets agree. The data holds only
  the newest quote per book, so it holds no movement history; the market analyst is told
  to say so and never to describe a line moving.
* Injury and lineup analyst: probable starters, lineups posted or not, injury and
  transaction notes, the football injury report and quarterback.
* Bull: the strongest honest case for the one or two best-supported bets, or an honest
  "nothing is supported".
* Bear: the strongest honest case that the market is right and a bet loses.
* Desk head: weighs everything, answers the bear's strongest point, and decides.

All of the text is in `src/hounds/desk/roles.py`, which also generates
`config/desk_hounds.json` (`python -m src.hounds.desk config --write`; a test regenerates
it and compares).

## The decision menu and the code risk manager

For each market slot: TAKE a selection at its best quoted price with a stated probability,
or PASS. A hound lists only its TAKEs; an unlisted slot is a PASS; listing nothing passes
the game. Then code, not a model, applies R1 to R5 (price in the data, the -200 cap,
beat the market's own number, the persona's rule, at most two TAKEs) and the analyst's
checker (R6) checks every number, name and path. The rules and their reasons are in
`docs/PREREG_DESK_HOUNDS.md` sections 3 and 5 and in the docstring of
`src/hounds/desk/risk.py`. A code strike is a PASS and never earns a new answer; a checker
rejection earns a re-answer under the publication rule.

## The publication rule

The analyst pilot's, per stage and enforced by the pilot's own attempt code
(`src/analyst/pilot.py`): the first answer is the candidate; a re-answer only after a
checker rejection, at most twice (three attempts); only the rejection lines as extra
input; the latest attempt is the one used; every attempt saved under
`stages/<stage>/`. An answer file that cannot be read as JSON is a rejected attempt with a
reason. An answer to a stage that is already clean is refused and not recorded.

## Files

Under `evidence/hounds_desk/<date>_<AWAY>-<HOME>/` (football: `<date>_nfl_<A>-<H>`):

| File | What |
|---|---|
| `packet.json`, `prepare.json` | the frozen data and what was prepared (hashes, caps, event id, token estimates) |
| `requests/<stage>_a<N>.json` | the request for attempt N of a stage |
| `answers/<stage>_a<N>.json` | the subagent's answer file |
| `stages/<stage>/attempts.jsonl`, `attempt_N.json` | the publication rule's record |
| `transcript.json` (`transcript_2.json` for a later batch) | every stage, every attempt, every checker verdict, every code strike, the final decisions: for "how the desk argued" |
| `disagreement.json` | per slot, what each hound decided and a status: split, agree, lone, none |

The ledger is `evidence/hounds_desk_v1.jsonl`, hash-chained like the analyst's
(`src/ledger/chain.py`; `python -m src.hounds.desk verify`). Row kinds:

* `hound`: a definition (written once per hound, at the first publish, which is registration);
* `hound_bet`: `hound_id, date, sport, event_id, game_pk` (football: `nfl_game_id`) `, game_id, away, home,
  start_utc, lock_utc, published_utc, slot_id, market, selection, side, line, price_best, price_average, price,
  book, book_count, consensus_fair, probability, reason, who_decided: "model", segment: "forward", bet_id,
  grading, packet_hash, transcript, transcript_sha256, prompt_version, prompt_hash`;
* `hound_graded`: `hound_id, bet_id, event_id, market, selection, result, units_average_price,
  units_best_price, units, close_price, clv_pts` (the last two null: the referee measures them);
* `desk_game`: one per publish call for a game: the hounds published and their TAKE counts, the packet hash,
  the transcript and table paths and the transcript's sha256. It has no `hound_id`, on purpose: the
  leaderboard's reader turns every row with a `hound_id` into a bet.

`lock_utc` is the instant of the board the hound read (the packet's `built_at`); `published_utc` is
when the row was written, at most 90 minutes later and before the start. `price_best` is the price taken (the
best quote in the data); `price_average` is the mean decimal price over the books quoting that selection, as an
American price.

## Cost: what a game takes (estimates, not measurements)

The packet is repeated in every request, so it drives the cost. High estimates at about 3 characters a
token, from `python -m src.hounds.desk prepare` (`token_estimates` in `prepare.json`):

| Game | One first-wave request | Desk (7 requests) in / out | Six personas in / out | All 13 in / out |
|---|---|---|---|---|
| MLB, 16 props (TB at CLE packet of 2026-10-17) | ~18,000 | ~148,000 / ~14,000 | ~114,000 / ~14,000 | ~262,000 / ~29,000 |
| NFL, 3 markets (LAC at KC, 2026-10-18) | ~8,700 | ~83,000 / ~14,000 | ~59,000 / ~14,000 | ~142,000 / ~29,000 |

Output sizes are estimates from the schema limits; nothing has been answered yet. A run is at most 2 games and
30 answers: 2 games is 26 answers, which leaves 4 re-answers. `publish` records the reported tokens, and a cost
figure at list price when both are given, in the `desk_game` row.

## What it cannot do

* It is one model. Seven hounds are not seven opinions.
* The packet holds no betting percentages, no ticket counts and, for baseball, no line-movement history. The
  Square and the Fader use the favourite and the over as a stated stand-in for the popular side.
* An answer is not stable: two answers to the same request can differ. The published one is the first that
  cleared the checker.
* The checker proves quoted facts are true and calls are coherent; it cannot prove a true fact is a good reason.
* Volume is low (at most two TAKEs per hound per game, two games a run). The referee says `TOO EARLY` until 150
  bets have a measurable closing price.
* It never places or sizes a bet, and no API key exists or is used.

## Integration notes for the leaderboard

* The ledger path `evidence/hounds_desk_v1.jsonl` is not in `ledgers.Sources.pack_ledgers`; adding
  `("house", evidence_path("hounds_desk_v1.jsonl"))` makes the existing reader pick it up (rows are in its shape,
  and `tests/test_desk_hounds_grade.py` runs `pack_ledger_rows` over a desk ledger to prove it).
* The definition rows' `category` is `ai-desk` or `persona`, neither in `contract.CATEGORIES`.
* The transcript and disagreement files are under `evidence/`, which the image copies whole.

## Changing a hound

The prompt text, schemas, risk rules and persona rules are the strategy. A change after the first forward bet is
a new version: new hound ids and an empty record. `config/desk_hounds.json` carries each hound's prompt version
and sha256 and every bet row repeats them, so a record always says what made it.
