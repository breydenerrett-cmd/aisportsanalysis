# The AI analyst

A model-written analysis of every game that makes a call on every market we hold a
price for, frozen before the game and graded in public.

> Written by an AI model from the data on this page. Unproven. Analysis, not advice.

That sentence is on every surface that shows the analyst's work. The record starts
empty. Nothing here is a claim that the analyst is any good; the record is how that
gets measured, in the open, including every loss and every pass.

## What it is for

The owner's words: "Every single player prop, every single sports bet per matchup,
whether it's the money line, the run total, the run total per team ... we need to be
able to have 'pick this, not this, and this is why.'" The voice he wants: "even though
the Chicago White Sox are +128, I'm finding that the odds are really good for what
might be a coin flip. Because they've had really good games and really good
momentum..."

The product had no model reasoning at all. This adds one, with the one property that
makes it publishable: **every sentence can be walked back to a fact in a frozen packet,
and a checker strikes what cannot.**

## The four steps

```
packet.py    freeze every fact the model may use into one hashable packet
analyst.py   ask the model for a call on every market the packet prices
critic.py    strike or downgrade any call the packet does not support
ledger.py    publish what survived (hash-chained) and grade it afterwards
```

`source.py` reads the stores, `grading.py` grades, `cli.py` runs it. Nothing in the
package places a bet or can.

### 1. The packet (`src/analyst/packet.py`)

One self-contained object per game, built from data the repo already holds: the game
payload (`GET /game/...` sections), the multi-book price store (moneyline, run line
and total, per book), the derivative store (team totals), the batter and pitcher prop
stores, and the repo's own prop board (its model probability, season rate and expected
plate appearances for a batter).

- **Every stat has an as-of.** Each section is `{as_of, as_of_basis, values}`. Team and
  starter stats are as of the newest result in the results store before the game.
- **Every price has a book and a capture time.** `markets.<slot>.options[n].quotes` is a
  list of `{book, price, captured_utc}`. The newest quote per book wins.
- **No future.** Quotes captured after the packet was built, or at or after first pitch,
  are dropped. The game block is a whitelist (identity, venue, first pitch, state,
  probable starters); the final scores that the payload carries once a game is over never
  enter it.
- **Explicit holes.** `missing` lists every absent, stale or thin input with the reason:
  the payload's own gap messages (no lineup yet, no matchup history), a quote older than
  180 minutes, team or starter stats that stop more than 3 days before the game (an ingest
  stopped), a section stamped more than 14 days before the game, an empty bullpen or travel
  window, props left out by the per-game cap.
- **Deterministic and hashable.** Built from its arguments only: no clock, no disk, no
  network. `packet_hash` is a sha256 of the canonical JSON. Same inputs, same hash, in any
  row order.
- **Works with or without the neighbouring pieces.** If the game payload carries a `read`
  (the deterministic per-game read), it becomes `sections.read`. If it does not, nothing
  changes. Live game state is read from `game.state`; the ledger refuses a game that is
  not `pending`. Run-line and total prices come from the multi-book store directly, so the
  packet does not wait on any payload change to carry them.

**Slots.** `markets` is keyed by slot id: `moneyline`, `run_line`, `total`,
`team_total_away`, `team_total_home`, `prop_01` ... Each lists its options with the
**lean** first, the side the books favour (higher de-vigged probability). That is what
makes the verdicts unambiguous:

| verdict | meaning |
|---|---|
| `TAKE` | bet the lean (the first option) |
| `TAKE_OTHER_SIDE` | bet the other option, the side the books do not favour |
| `PASS` | bet nothing in this market |

A one-sided market (a home-run prop: nobody quotes the under) has one option, so it can
be a TAKE or a PASS and never a TAKE_OTHER_SIDE.

**Props are capped** at `max_props_per_game` (16): starting pitchers' strikeout props
first, then the repo's prop board order (how likely the outcome is, never the gap
against the price: `src/analysis/propboard.py` measured that ordering and the gap lost),
at most half the cap from one stat. The rest are counted in `missing`.

**Not analyzed** (stated in the packet's `limits`): alternate run lines and totals,
first-five markets, every line but the most-quoted one.

**The path grammar.** The benchmark in `docs/AI_CRITIC_BENCHMARK.md` recorded a critic
that wrote every fact path as `data.best_price` where the checker wanted `best_price`:
right values, wrong paths, 102 times, because the instruction never said what a path
looked like. Here a path is always rooted at the packet:
`markets.moneyline.options[0].best.price`, `sections.starters.values.home_sp_era`.
Dot-separated keys and `[n]` indexes only. The prompt gives two real examples,
`resolve_path` is the only resolver, and a path that fails says why (the `data.` mistake
has its own message). Every key in the packet is path-safe (`Away Games` becomes
`Away_Games`).

### 2. The analyst (`src/analyst/analyst.py`)

One Messages API call per game over HTTPS with `urllib` (no SDK dependency in `src/`).
Model id, price per million tokens, effort and caps come from `config/analyst.json`
(default `claude-sonnet-5-5`). The key comes from `ANTHROPIC_API_KEY` at the moment of the
call and is never stored, logged or put in a packet, row or error message. The request
asks for a JSON schema through `output_config.format`; no `temperature`, `thinking` or
prefill is sent (the current models reject the first two when they are not default and the
third outright). Thinking is the model's default, adaptive, at `effort: medium`.

A malformed answer (wrong shape, wrong summary length, a missing slot) gets **one**
repair attempt with the reasons appended; the second attempt is paid for like the first.
A refusal or a truncated answer is not retried and nothing is published for that game. The API's
server-side refusal fallback is **not** enabled: it re-runs a declined request on another model and
bills that at the other model's rate, which the spend cap's single price table would understate. The
request is one non-streaming call (`max_tokens` 16,000, timeout 600 seconds).

#### The prompt, verbatim (`PROMPT_VERSION = analyst_prompt_v1`)

```
You are a baseball betting analyst. You write the analysis of one MLB game and make a call on every market the packet prices. You are an AI model and the reader knows it. Your work is published before the game, graded afterward, and shown next to its record whatever that record turns out to be. Write like a sharp human analyst talking to a smart friend: plain words, a point of view, no hype.

THE PACKET IS YOUR ONLY SOURCE
1. Reason only from the packet. Use no outside knowledge of any team, player, injury, weather, standing or result, even if you are sure of it. If something matters and is not in the packet, say it is missing.
2. A claim without a packet path is forbidden. Every reason has evidence: a list of {path, value}. A path names one value in the packet and starts at the packet's own top-level key. The value is copied exactly. Examples of real paths: markets.moneyline.options[0].best.price and sections.starters.values.home_sp_era. Never start a path with data. or packet.
3. Every number you write in prose must appear in the packet, or be a price or probability you are yourself giving in a call. Do no arithmetic of your own on packet numbers in prose (no differences, sums or ratios); quote the packet's numbers. Do not write clock times.
4. `missing` lists what is absent, stale or thin. Weigh it. A call that rests on something listed there is a PASS.

THE CALLS
5. Make exactly one call for every entry in `slots`, in the same order, using its slot_id and its market. `selection` must be one of that slot's selections, written exactly as listed. The first selection is the lean: the side the books favour.
6. Verdicts. TAKE: bet the lean (the first selection) at the price you name. TAKE_OTHER_SIDE: bet the other selection, the side the books do not favour. PASS: bet nothing in this market.
7. PASS is the default. When the evidence is thin, or the packet gives you nothing about this market beyond its own price, PASS. Say plainly when the market is probably right, and what makes you think so.
8. Never TAKE any bet at a price of -200 or worse, in any market (-200, -250, -325 and so on). PASS it, or if the other side is the one you like, take that.
9. price and book: the quote you would take, copied from the selection's quotes in the packet. For a PASS you may give the best quote or null.
10. fair_estimate: your own probability that the selection wins, between 0.01 and 0.99. The books' own de-vigged number is in the packet as fair_probability, and for props the repo model's number is in context. If you depart from the books by more than a few points, the reasons must show what the packet knows that the price does not. For a PASS you may give null.
11. pass_price: the American price at which the selection stops being worth taking, which is the break-even price of your fair_estimate. On a PASS, the price at which you would start to take it, or null if no price would do.
12. confidence: low, medium or high. High only when several independent packet facts agree and nothing relevant is in `missing`.
13. what_would_change_it: one sentence naming a specific new fact that would flip the call, such as a lineup change or a scratch. If it names a price, that price is your pass_price.

THE WORDS
14. Never write: lock, guaranteed, free money, sure thing, can't lose, +EV. Never claim a profit, an edge you have, or certainty. No exclamation marks.
15. Do not recommend a stake size and do not describe anything as a bet you or we placed.

THE SUMMARY
16. `summary` is the argument in 120 to 200 words of plain prose, one or two paragraphs, no lists, no markdown. Say where you lean and why, where you pass, what the market probably has right, and which missing inputs matter. A voice like: "Even though TB is -127, I like it: the starter has the better numbers over his last starts and the price is close to a coin flip." Only with facts that are actually in the packet.

Reply with one JSON object that matches the schema and nothing else.
```

#### The schema, verbatim

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "summary",
    "calls"
  ],
  "properties": {
    "summary": {
      "type": "string"
    },
    "calls": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "slot_id",
          "market",
          "selection",
          "verdict",
          "price",
          "book",
          "fair_estimate",
          "confidence",
          "reasons",
          "pass_price",
          "what_would_change_it"
        ],
        "properties": {
          "slot_id": {
            "type": "string"
          },
          "market": {
            "type": "string"
          },
          "selection": {
            "type": "string"
          },
          "verdict": {
            "type": "string",
            "enum": [
              "TAKE",
              "PASS",
              "TAKE_OTHER_SIDE"
            ]
          },
          "price": {
            "anyOf": [
              {
                "type": "integer"
              },
              {
                "type": "null"
              }
            ]
          },
          "book": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "fair_estimate": {
            "anyOf": [
              {
                "type": "number"
              },
              {
                "type": "null"
              }
            ]
          },
          "confidence": {
            "type": "string",
            "enum": [
              "low",
              "medium",
              "high"
            ]
          },
          "reasons": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "claim",
                "evidence"
              ],
              "properties": {
                "claim": {
                  "type": "string"
                },
                "evidence": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "additionalProperties": false,
                    "required": [
                      "path",
                      "value"
                    ],
                    "properties": {
                      "path": {
                        "type": "string"
                      },
                      "value": {
                        "anyOf": [
                          {
                            "type": "string"
                          },
                          {
                            "type": "number"
                          },
                          {
                            "type": "boolean"
                          },
                          {
                            "type": "null"
                          }
                        ]
                      }
                    }
                  }
                }
              }
            }
          },
          "pass_price": {
            "anyOf": [
              {
                "type": "integer"
              },
              {
                "type": "null"
              }
            ]
          },
          "what_would_change_it": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

The model is not allowed to make up a market: `slot_id` must be one the packet lists,
`market` must match it, `selection` must be one of its selections. Ranges the schema
cannot express (a probability between 0 and 1, a summary of 120 to 200 words, one call
per slot in slot order) are checked in `validate_output`.

### 3. The critic (`src/analyst/critic.py`)

Deterministic first, always on, free and exact. A call is **struck** when:

- an evidence path does not resolve, or resolves to a group instead of a value;
- the value the analyst claims for a path is not the packet's value (strings compare
  case-insensitively; numbers compare at the precision written, so 3.86 matches 3.8602
  and a bare 4 matches only a whole 4);
- a number quoted in a reason or in `what_would_change_it` is not a number in the packet
  or a price or probability the analyst itself gives in a call (a percentage matches a
  packet fraction at the precision written; a date in words is fine);
- a banned word appears: lock, guaranteed, free money, sure thing, can't lose, +EV, or
  "edge" unless it is denied ("no edge here");
- a person is named who is not in the packet. Any run of two or more capitalised words is read as
  a name and must be in the packet's text (a printed "Last, First" counts as "First Last"), or be a
  club or city, or ordinary vocabulary ("Division Series", "Run Line"). This is the benchmark's
  original failure, a pitcher nobody had verified. One capitalised word is not checked, and a name
  cannot be assembled from two real players' pieces. The rule leans strict on purpose: a false
  strike costs a PASS, a missed name costs a published claim with no source;
- the selection is not one of the slot's, or the verdict disagrees with it (TAKE must name
  the lean, TAKE_OTHER_SIDE the other side);
- the price and book are not a quote in the packet for that selection;
- a TAKE is at a price of -200 or worse, in any market. The owner's rulings: no moneyline at -200
  or worse, ever (2026-09-20), and no public pick at -200 or worse on any sport (2026-09-22). The
  build brief named the moneyline; the later ruling is broader, so the floor holds for every market,
  heavy-juice props included. Narrowing it is one `if` in `critic.check_call`. The other side of the
  same market is not caught by it;
- the call contradicts itself: a fair estimate at or below the break-even of the price it
  says to take, a pass price that is not the break-even price of the estimate (within 2
  points of probability) or is a better price than the one taken, a TAKE with no estimate
  or pass price.

A struck call is **published as a PASS whose reason is "Could not be verified."** It keeps
the selection and quote only when they are real, loses the estimate and the reasons, and
never reaches a reader with a claim the packet does not support, not even to say it was
unsupported. The original goes to the ledger row (`struck`) so the audit trail keeps what
the model said and why it failed. A call that is only overconfident (high confidence on
one cited fact, or on a stale price) is **downgraded** one step, not struck. A summary that
fails (an unsupported number, a banned word) is withheld and replaced on the page by a plain
notice; the calls still publish.

The optional **model critic** (`model_critic.enabled` in config, or `--model-critic`) is a
second call that reads the packet and the published calls and says which reasons overreach
their evidence. It can only strike. If it cannot be reached the calls stand on the first pass
and the row records `model_critic: "did not run"`.

**What the critic cannot catch.** It checks that quoted facts are true and the call is
coherent. It cannot tell whether a true fact is a good reason, whether the summary and the
calls agree in spirit, or whether the model's probabilities are any good. Its number check is
against the packet's numbers, not their meaning (the evidence values carry the meaning). Its name
check does not look at single capitalised words. A claim can quote true numbers and real names and
still draw a conclusion they do not support: the optional model critic is the second line for that,
and the record is the last.

#### The critic prompt, verbatim

```
You check one analyst's published calls against the fact packet it was written from. You add no facts and make no calls of your own. For each call decide whether every reason's claim is actually supported by the evidence values it cites, and whether the verdict follows from the reasons. A claim that goes beyond its evidence, reads a number the wrong way, or draws a conclusion the cited facts do not support is not supported. Do the same for the summary. Be strict: when in doubt, it is not supported. Reply with one JSON object that matches the schema and nothing else.
```

### 4. The ledger (`src/analyst/ledger.py`)

`evidence/analyst_v1.jsonl`, append-only and hash-chained on the same primitive as every
ledger here (`src/ledger/chain.py`). `src/appstate/card_ledger.py` is fingerprinted, so its
pattern is copied and none of its code is shared or edited. It is a different file, different
rows and a different record from the cards.

| row | when | holds |
|---|---|---|
| `analyst_published` | before first pitch | the calls, each with its grading spec; summary and its status; the struck originals; packet hash and path; model, prompt hash; run cost |
| `analyst_graded` | after the game | each call's result from the results the cards use |
| `analyst_correction` | when a grade was wrong | the corrected fields and a reason; the graded row is untouched |

- **Refuses to publish** for a game that has started, whose first pitch is unknown, or whose
  state is not `pending`. The CLI asks the same question before calling the model, so a game
  that cannot be published is never paid for.
- **Frozen.** A second `publish` returns the first row. `--refresh` writes a new version
  (`supersedes` the old) while the game has not started and has not been graded. Every version
  stays in the file; only the newest of a game counts.
- **The packet is a file**, `evidence/analyst_packets_v1/<date>/<game>_<hash12>.json.gz`, named
  by its hash. `verify` checks the chain and that every packet file hashes to what its row says.
- **Corrections append, never rewrite.**
- **Size.** A published row is about 14 KB with terse reasons and will be more with real ones, call it
  15 to 30 KB a game: fifteen games a day is roughly 10 to 15 MB a month for `analyst_v1.jsonl`, plus
  about 5 KB a game for the packet file. GitHub refuses files over 100 MB, so this store needs the
  cold-storage rotation the capture stores have (`src/pipeline/store_archive.py`) in about eight
  months. `HashChainLedger` already reads rotated stores, so registering the store is the whole job.
  It is not registered today.

`evidence/analyst_usage_v1.jsonl` is the cost log: one chained row per game attempt with tokens,
estimated dollars and the price they were computed with, so cost per day is a fold
(`analyst record` prints it).

## How grading works

`analyst grade --date D` grades every published game of that date from the results the cards
use: the results store for score-based markets and the box-score store for props.

- Moneyline, run line and game total call the card ledger's own `grade_pick` and
  `grade_total_pick`, so the analyst and a card can never disagree about who won. Props use
  `src/board/settle_props.settle`, the rule the card's props use, against batter or pitcher box
  rows. A team total (which the cards do not publish) is graded with the same three comparisons.
- **WIN, LOSS, PUSH** (the line landed on the number), **VOID** (a player with no recorded
  appearance in a captured box, an unusable price, a result marked void), **UNRESOLVED** (no
  result yet; never a loss, never a void).
- **Each market family is graded and counted on its own:** moneyline, run line, game total,
  team totals, player props. A good run in one cannot hide a bad one in another.
- Returns are flat one-unit stakes at the published price. That is a way to add results up, not a
  claim that anyone staked anything.
- **A PASS is not a bet.** It carries `would_have`, the result the passed side would have had at
  its best quoted price, so the record can show whether the passes were right without counting
  them as wins or losses.
- A later grade replaces an earlier one only when it adds a result. Grading twice changes nothing.

**The public record** (`GET /analyst/record`, the "AI analyst record" section of the record page)
shows counts by family always. A win rate and units appear for a family only at **30 graded
calls** (win, loss or push); below that the page prints "fewer than 30 graded calls (n so far)".
The server sends null, and the page never computes a rate of its own.

## Where it shows

- **Game page**, one self-contained section: the summary, then the calls grouped by market with
  verdict, price and book, confidence, the reasons, and the pass price. PASS is drawn exactly as
  large as TAKE. `GET /analyst/{date}/{away}/{home}` serves it, behind the same gate as
  `GET /game/...`, from the ledger only: **a page view never calls the model.**
- **Record page**, the analyst table by market family, with the label.

## What it does not claim

- That it is right. The record is empty and unproven, and the label says so everywhere.
- Any profit, any edge, any expected value. It never says "lock", "guaranteed" or "free money",
  and the critic strikes any call that does.
- That a verified call is a good call. Verified means the facts it quotes are in the packet and the
  call does not contradict itself. Whether it was worth taking is what the record measures.
- That the summary and the calls agree in spirit. Both are checked against the packet; nobody
  checks one against the other.
- That it saw anything outside the packet: no search, no tools, no memory of other games.
- That the card is affected. It changes no card rule, gate, pick or published result and shares
  no row with the card record.
- A stake size, or that anyone should bet. It recommends no stake and places nothing.

## Cost model

**Everything below is an estimate until the first measured day.** The log records the real
numbers from the usage the API returns; replace these with those after a week.

Assumptions:

| item | value | source |
|---|---|---|
| model | `claude-sonnet-5-5` | config default |
| price | $2.00 per million input tokens, $10.00 per million output tokens, $0.20 cache read | the claude-api reference's model table (cached 2026-09-25); in `config/analyst.json`, so a price change is one edit |
| packet | about 31,000 characters, about 9,000 to 10,000 tokens | measured on 2026-10-03 NYY@TB with 16 props |
| prompt and schema | about 1,300 tokens | measured in characters, not tokens |
| input per game | about 11,000 tokens (the CLI's deliberately high estimate is 11,743) | |
| output per game | about 6,000 to 9,000 tokens: about 270 for the summary, about 180 to 250 for each of about 19 calls, plus adaptive thinking at medium effort (not measured) | assumption |
| prompt caching | not used: the stable prefix is under the minimum cacheable length | no saving claimed |

Per game: input about $0.022 plus output about $0.06 to $0.09 is **about $0.08 to $0.11**.
Worst case, a full 16,000-token output, is $0.18 (this is what the spend cap reserves before each
call). A fifteen-game day is **about $1.20 to $1.70**, a month of slate days **about $35 to $50**.
The optional model critic adds about 11,000 input and 500 output tokens a game, about $0.03.
A repair attempt on a malformed answer costs another call. These are not measured.

**The hard cap** (`spend_cap` in config): $6.00 and 600,000 tokens per run. It is checked
BEFORE every call against the worst that call can cost and charged AFTER it from the API's usage,
so a run can stop short of the cap and never pass it. It stops the whole run with
`STOPPED: spend cap reached ...`, exit code 4. At the worst case that is about 33 games.

## Running it

```
python -m src.cli analyst run --date 2026-10-03 --dry-run --game NYY@TB --print-request
python -m src.cli analyst run --date 2026-10-03            # needs ANTHROPIC_API_KEY
python -m src.cli analyst grade --date 2026-10-02
python -m src.cli analyst record
```

- Without `ANTHROPIC_API_KEY`, `run` prints `BLOCKED: ...` and exits 3 before building, calling or
  writing anything. `--dry-run` needs no key: it builds the packet and the exact request that would
  be sent, prints a summary (the whole body with `--print-request`), and calls and writes nothing.
- A game already published is frozen and skipped without a model call; `--refresh` publishes a new
  version before first pitch. A game that has started, is not pending, or prices no market is skipped
  before any call.
- Exit codes: 0 ok, 2 error, 3 blocked, 4 spend cap.
- `scripts/analyst_step.sh` is the daily job's step: it grades yesterday and the day before (no key
  needed) and runs today only when the key is set. It always exits 0 and never prints ESCALATE, so it
  cannot fail the loop it sits in.

How to turn it on, what it costs a day and how to turn it off again:
`docs/decisions/AI_ANALYST_ENABLE.md`.

## Tests

`tests/test_analyst_packet.py`, `test_analyst_model.py`, `test_analyst_critic.py`,
`test_analyst_ledger.py`, `test_analyst_cli.py`, `test_analyst_api.py`, `test_analyst_web.py`, all
offline (the HTTP caller is injected; the shared fixtures read no repo data), plus the wording sweeps
`test_web_register_sweep`, `test_customer_language` and `test_no_developer_notes_on_screen`.
`tests/test_analyst_model.py` pins that the prompt in this file is the prompt in the code.
