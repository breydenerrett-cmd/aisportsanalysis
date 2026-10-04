# The AI analyst

A model-written analysis of every game that makes a call on every market we hold a
price for, frozen before the game and graded in public.

> Written by an AI model from the data on this page. Unproven. Analysis, not advice.

That sentence is on every surface that shows the analyst's work. The record starts
empty. Nothing here is a claim that the analyst is any good; the record is how that
gets measured, in the open, including every loss and every pass.

The sections below describe the MLB analyst. UFC has its own at the end of this file,
"The UFC analyst": the same machinery with a fight packet, a fight prompt and its own
ledger and record.

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

#### The prompt, verbatim (`PROMPT_VERSION = analyst_prompt_v3`)

```
You are a baseball betting analyst. You write the analysis of one MLB game and make a call on every market the packet prices. You are an AI model and the reader knows it. Your work is published before the game, graded afterward, and shown next to its record whatever that record turns out to be. Write like a sharp human analyst talking to a smart friend: plain words, a point of view, no hype.

THE PACKET IS YOUR ONLY SOURCE
1. Reason only from the packet. Use no outside knowledge of any team, player, injury, weather, standing or result, even if you are sure of it. If something matters and is not in the packet, say it is missing.
2. A claim without a packet path is forbidden. Every reason has evidence: a list of {path, value}. A path names one value in the packet and starts at the packet's own top-level key. The value is copied exactly. Examples of real paths: markets.moneyline.options[0].best.price and sections.starters.values.home_sp_era. Never start a path with data. or packet.
3. Every number you write in prose must appear in the packet, or be a price or probability you are yourself giving in a call. Do no arithmetic of your own on packet numbers in prose (no differences, sums or ratios); quote the packet's numbers. Do not write clock times.
3a. The one exception to doing arithmetic is a calculation you declare. A number you work out yourself (a difference, a sum, a ratio, a percent change, the days between two dates, the chance a price implies, a count or an average) may appear in a reason, a case against or the summary only if that item lists it in `derived` as {value, unit, op, inputs, note}. `op` is one of difference, sum, ratio, percent_change, days_between, implied_probability, count, mean. `inputs` are packet paths, in order: difference is the first minus the second, ratio is the first over the second, percent_change is the change from the first to the second as a percent of the first, days_between is the calendar days between two dates in UTC (later minus earlier), implied_probability takes one American price, count takes one list. `unit` is what the value is measured in (days, runs, percent, and so on) and `note` says in plain words what it is. The checker recomputes every derived value from the packet, and a wrong one strikes the call. Put the summary's in `summary_derived`. An item with no calculated number has an empty `derived`.
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
13a. case_against: for a TAKE or a TAKE_OTHER_SIDE, the strongest reason from the packet that this bet loses, written as {claim, evidence} and built like a reason. It must name a specific weakness in this bet, such as a number in the packet that points the other way, not general risk: "anything can happen in baseball" is not a case against. Cite at least one packet path, and quote only numbers that are in the packet. Argue it as hard as you would argue the other side. For a PASS it is null.

THE WORDS
14. Never write: lock, guaranteed, free money, sure thing, can't lose, +EV. Never claim a profit, an edge you have, or certainty. No exclamation marks.
15. Do not recommend a stake size and do not describe anything as a bet you or we placed.

THE SUMMARY
16. `summary` is the argument in 120 to 200 words of plain prose, one or two paragraphs, no lists, no markdown. Say where you lean and why, where you pass, what the market probably has right, and which missing inputs matter. A voice like: "Even though TB is -127, I like it: the starter has the better numbers over his last starts and the price is close to a coin flip." Only with facts that are actually in the packet.

Reply with one JSON object that matches the schema and nothing else.
```

#### Prompt v2, prompt v3 and the schema, verbatim

`analyst_prompt_v2` (2026-10-03) added one rule, 13a, and one required call field, `case_against`:
for a TAKE or a TAKE_OTHER_SIDE, `{claim, evidence}`, the strongest reason from the packet that the
bet loses (a specific weakness, not general risk); for a PASS, null. v1 never ran against the API
(no ledger file existed), so changing it lost no record. The rule is numbered 13a so every later
rule keeps its number: the situation section (arm B) takes 17 to 20.

`analyst_prompt_v3` (2026-10-04) adds rule 3a and the `derived` field, described in the next
section. **No row has been published under v2**, so the change cost no record: every row written
from here on carries v3 and the v3 prompt hash (`prompt_hash`, which also covers the schema). Rule 3
keeps its words and its number; 3a is the one exception to it, so the later rules and the situation
section still number as before. Arm B's version moves with it (`analyst_prompt_v3_situation`).

The schema below is `analyst.MLB_RESPONSE_SCHEMA`. The UFC analyst shares the model call and the
critic but not these fields: it keeps using the shared `analyst.RESPONSE_SCHEMA` (the same schema
without `case_against` or `derived`), `schema_for(packet)` picks by the packet (a game packet versus
a bout packet), and the UFC request, prompt hash and critic are unchanged. The critic ignores a
`derived` key on a UFC reason, so a UFC number is checked against the packet exactly as before.

#### Declared derivations (prompt v3)

The number rule is unchanged and strict: a number in prose must be in the packet. The checker
struck a call that said "11 days" because the model had computed the 11 itself, and that stays
rejected. But some calculated facts are legitimate, and the owner's ruling of 2026-10-04 allows
them "when deterministic code verifies their source inputs, calculation, units and time
convention", with the provenance kept beside the report. So the model may **declare** a calculation
and the code **redoes** it from packet values; the model's number is never trusted, only compared.

Each reason, each case against and the summary (as `summary_derived`, beside `summary`) may carry
`derived`, a list of `{value, unit, op, inputs, note}`. `inputs` are packet paths, in order. The
checker (`critic.verify_derivations`) reads each input, recomputes the op, checks the unit is one
the op allows, and compares with the op's tolerance. Only then is that value allowed in the prose
of **that item and no other**: a correct derivation does not license a different number in the same
sentence, in another reason, or in `what_would_change_it`. A derivation whose op is unknown, whose
inputs are absent, not numbers or not the kind the op needs, whose unit the op does not allow or
whose value differs from the recomputed one **strikes the call** (or withholds the summary), with a
plain reason in the audit trail. A number that is neither in the packet nor a verified derivation is
rejected exactly as it always was.

| op | inputs | convention | tolerance |
|---|---|---|---|
| `difference` | 2 numbers | first minus second, signed | 0.05 (0.5 in percentage points) |
| `sum` | 2 to 12 numbers | the total | 0.05 (0.5 in percent or percentage points) |
| `mean` | 2 to 12 numbers | the arithmetic mean | 0.05 (0.5 in percent or percentage points) |
| `ratio` | 2 numbers | first over second; a zero second is refused | 0.05 (0.5 in percent) |
| `percent_change` | 2 numbers | from the first to the second, as a percent of the absolute value of the first; a zero first is refused | 0.5 percent |
| `days_between` | 2 ISO dates or datetimes | calendar days between the two dates in UTC, later minus earlier, never negative; a date alone is that day in UTC, a datetime is converted to UTC first (no offset is read as UTC) and its time of day is dropped | exact |
| `implied_probability` | 1 American price | the price's break-even probability, margin left in | 0.5 percent, or 0.005 as a probability |
| `count` | 1 packet list | its length | exact |

**Rounding.** A declared value agrees with the recomputed one when it is within half a unit of the
last decimal place it was written to (3.5 for 3.4876 is rounding), and never by more than the cap in
the table, so a whole number cannot stand in for 0.6. A cap of "exact" means the whole number the
op returns. The unit sets the scale: `percent` and `percentage points` are 100 times a fraction (the
packet holds probabilities as fractions), `probability` is the fraction itself. Each op allows only
its own units (`analyst.DERIVATION_UNITS`, which is also the schema's enum): `days` for
`days_between`; `percent` for `percent_change`; `percent` or `probability` for
`implied_probability`; `ratio`, `times` or `percent` for `ratio`; a counting noun for `count`; and
for `difference`, `sum` and `mean` a baseball quantity (runs, points, games, wins, innings, hits,
strikeouts, degrees, mph, units) or, where a fraction is being scaled, percentage points or
percent. The prose number must itself match the derived value at the precision written (the
absolute value is allowed, so a gap is said without its sign), and a probability may be said as a
percentage. A verified derivation the sentence does not use is dropped, not kept.

**What is not checked.** The derivation licenses a NUMBER, not the words around it: the prose's own
unit is not parsed, so "11 runs" would pass beside a verified 11-day derivation. The note is kept
in the ledger for the audit and never shown. The shape is checked in `validate_output` (a malformed
`derived` is a shape error and earns the one repair attempt); whether it is true is the critic's.

**Provenance.** Each verified derivation is stored in the published row, inside the reason that used
it (the summary's at the row's top level as `summary_derived`): the op, unit and value, the packet
paths it was computed from with a plain label and the value read at each, and the note. A row with
no derivation is byte for byte what it was. `ledger.game_view` serves each reason with
`derivations`, one short plain sentence per calculation, for example "11 days: calendar days (UTC)
from starter last start date to first pitch.", and the whole analysis with `summary_derivations`.
The page (`web/js/analyst.js`) draws the sentence small under the reason or the summary. It never
shows a path.

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "summary",
    "calls",
    "summary_derived"
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
          "what_would_change_it",
          "case_against"
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
                "evidence",
                "derived"
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
                },
                "derived": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "additionalProperties": false,
                    "required": [
                      "value",
                      "unit",
                      "op",
                      "inputs",
                      "note"
                    ],
                    "properties": {
                      "value": {
                        "type": "number"
                      },
                      "unit": {
                        "type": "string",
                        "enum": [
                          "books",
                          "days",
                          "degrees",
                          "entries",
                          "games",
                          "hits",
                          "innings",
                          "items",
                          "mph",
                          "percent",
                          "percentage points",
                          "players",
                          "points",
                          "probability",
                          "quotes",
                          "ratio",
                          "runs",
                          "strikeouts",
                          "times",
                          "units",
                          "wins"
                        ]
                      },
                      "op": {
                        "type": "string",
                        "enum": [
                          "difference",
                          "sum",
                          "mean",
                          "ratio",
                          "percent_change",
                          "days_between",
                          "implied_probability",
                          "count"
                        ]
                      },
                      "inputs": {
                        "type": "array",
                        "items": {
                          "type": "string"
                        }
                      },
                      "note": {
                        "type": "string"
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
          },
          "case_against": {
            "anyOf": [
              {
                "type": "object",
                "additionalProperties": false,
                "required": [
                  "claim",
                  "evidence",
                  "derived"
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
                  },
                  "derived": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "additionalProperties": false,
                      "required": [
                        "value",
                        "unit",
                        "op",
                        "inputs",
                        "note"
                      ],
                      "properties": {
                        "value": {
                          "type": "number"
                        },
                        "unit": {
                          "type": "string",
                          "enum": [
                            "books",
                            "days",
                            "degrees",
                            "entries",
                            "games",
                            "hits",
                            "innings",
                            "items",
                            "mph",
                            "percent",
                            "percentage points",
                            "players",
                            "points",
                            "probability",
                            "quotes",
                            "ratio",
                            "runs",
                            "strikeouts",
                            "times",
                            "units",
                            "wins"
                          ]
                        },
                        "op": {
                          "type": "string",
                          "enum": [
                            "difference",
                            "sum",
                            "mean",
                            "ratio",
                            "percent_change",
                            "days_between",
                            "implied_probability",
                            "count"
                          ]
                        },
                        "inputs": {
                          "type": "array",
                          "items": {
                            "type": "string"
                          }
                        },
                        "note": {
                          "type": "string"
                        }
                      }
                    }
                  }
                }
              },
              {
                "type": "null"
              }
            ]
          }
        }
      }
    },
    "summary_derived": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "value",
          "unit",
          "op",
          "inputs",
          "note"
        ],
        "properties": {
          "value": {
            "type": "number"
          },
          "unit": {
            "type": "string",
            "enum": [
              "books",
              "days",
              "degrees",
              "entries",
              "games",
              "hits",
              "innings",
              "items",
              "mph",
              "percent",
              "percentage points",
              "players",
              "points",
              "probability",
              "quotes",
              "ratio",
              "runs",
              "strikeouts",
              "times",
              "units",
              "wins"
            ]
          },
          "op": {
            "type": "string",
            "enum": [
              "difference",
              "sum",
              "mean",
              "ratio",
              "percent_change",
              "days_between",
              "implied_probability",
              "count"
            ]
          },
          "inputs": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "note": {
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
per slot in slot order) are checked in `validate_output`. An absent `case_against` is read as null
there, and the critic strikes a TAKE that has none.

### 3. The critic (`src/analyst/critic.py`)

Deterministic first, always on, free and exact. A call is **struck** when:

- an evidence path does not resolve, or resolves to a group instead of a value;
- the value the analyst claims for a path is not the packet's value (strings compare
  case-insensitively; numbers compare at the precision written, so 3.86 matches 3.8602
  and a bare 4 matches only a whole 4);
- a number quoted in a reason or in `what_would_change_it` is not a number in the packet
  or a price or probability the analyst itself gives in a call (a percentage matches a
  packet fraction at the precision written; a date in words is fine), or, in that one reason or
  case against or the summary, a calculation it declares in `derived` that the checker recomputed
  from the packet (see "Declared derivations");
- a declared derivation does not hold: an unknown op or unit, an input that is absent, not a
  number (or not a date, a price or a list, as the op needs) or a group, a value that differs from
  the recomputed one beyond the op's tolerance, a wrong sign, a zero denominator, more than six
  in one item. A summary that fails this is withheld;
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
- a TAKE or TAKE_OTHER_SIDE has no `case_against`, or its case against fails the same checks a
  reason does (it cites no path, a path does not resolve or holds another value, a number is not in
  the packet, a banned word, a name not in the packet). The struck call is published as a PASS and
  the audit trail says why. A PASS publishes no case against whatever the model sent;
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
against the packet's numbers, not their meaning (the evidence values carry the meaning). A verified
derivation licenses a number, not the unit the prose puts after it. Its name
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
| `analyst_published` | before first pitch | the calls, each with its grading spec and, in a reason that used one, its verified derivations; summary and its status (and `summary_derived` when it used one); the struck originals; packet hash and path; model, prompt hash; run cost |
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
  Each TAKE shows "The case against" under its reasons, and the section lists what the analysis
  could not use (the packet's `missing` list, capped at six with a count). A reason or summary
  that rests on a calculated number shows one small plain sentence under it saying where the
  number came from (see "Declared derivations").
- **Record page**, the analyst table by market family, with the label, and under it, when the pilot
  has published, "Supervised-session briefs" as a separate block.

## The supervised-session pilot (`src/analyst/pilot.py`)

The analyst needs an API key the owner has not added. The owner approved a pilot in the meantime:
a supervised Claude session writes the model's answer from the exact request the API call would
send, and the SAME validation, code checker and ledger publish it, honestly labelled. It is not a
second pipeline: `pilot.py` calls `validate_output`, `critic.verify` and `ledger.publish`, and adds
three commands, separate stores and a provenance.

```
python -m src.cli analyst pilot prepare --date 2026-10-03 --game NYY@TB [--scratch DIR]
python -m src.cli analyst pilot check   --dir evidence/analyst_pilot/2026-10-03_NYY-TB --response answer.json
python -m src.cli analyst pilot publish --dir evidence/analyst_pilot/2026-10-03_NYY-TB --response answer.json \
    --model <name> [--tokens-in N --tokens-out N --seconds S --operator-minutes M] [--refresh]
```

- **prepare** builds the packet with the same loader and builder a run uses, refuses a started or
  unpriced game with the same messages, and writes `packet.json`, `request.json` (the exact request
  body) and `prepare.json` (packet hash, prompt version and hash, built time, first pitch, token
  estimate, model) to `evidence/analyst_pilot/<date>_<AWAY>-<HOME>/`. With `--scratch` it writes to
  that folder instead and marks it a rehearsal.
- **check** validates and runs the checker against the saved packet and prints, per call, kept or
  struck and why, with totals. It publishes nothing and works on rehearsal folders.
- **publish** reloads the saved packet and refuses unless: the folder is not a rehearsal; the packet
  hash matches `prepare.json` and the prompt has not changed since; the game has not started
  (`ledger.publish_refusal`); the packet was built no more than `pilot.max_packet_age_minutes` ago
  (`config/analyst.json`, 90); the game has no pilot row yet (or `--refresh`, still refused once
  graded); and the response passes the shape check. A response that passes the shape check but has
  false claims is published with those calls struck to PASS, as the API path does.
- **Stores.** `evidence/analyst_pilot_v1.jsonl`, `evidence/analyst_pilot_usage_v1.jsonl` and
  `evidence/analyst_pilot_packets_v1/`, separate from the main analyst's. No pilot command writes a
  main store. A row carries `provenance: "session_assisted"`, and its `run` records the mode, the
  model name given, the token counts, a dollar figure labelled an estimate at list price (tokens
  times `config/analyst.json` prices, not a bill; none when tokens are not reported), seconds and
  operator minutes.
- **Grading and record.** `analyst grade` also grades pilot rows once the pilot store exists, and
  `analyst record` prints them under "SUPERVISED-SESSION BRIEFS". They are never added to the main
  record.
- **Serving.** A game page gets the main ledger's row when it has one, otherwise the pilot's, with
  `PILOT_LABEL`: "Written by an AI model in a supervised session, from the data frozen before the
  game. Unproven. Analysis, not advice." Each served call carries its `case_against`; the analysis
  carries the packet's `missing` list and the `provenance`. `GET /analyst/record` returns the pilot's
  record as a separate `pilot` block.
- **The public sample.** `config/sample_brief.json` names one game (`{"date", "away", "home"}`, or
  null). `GET /sample/brief` (public, rate-limited like the record) serves only that game's pilot
  view, or `available: false`; `web/sample.html` draws it with the analyst section, says when it was
  frozen and when the game starts, shows the result once graded, links the public record and the
  landing page, and states the offer in one line. The page stores the visitor's first touch with
  `attribution.js`'s `captureFirstTouch`, as the landing page does.

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
`test_analyst_ledger.py`, `test_analyst_derived.py` (the declared derivations: each op right and
wrong, the provenance and what the page is served), `test_analyst_cli.py`, `test_analyst_api.py`, `test_analyst_web.py`, all
offline (the HTTP caller is injected; the shared fixtures read no repo data), plus the wording sweeps
`test_web_register_sweep`, `test_customer_language` and `test_no_developer_notes_on_screen`.
`tests/test_analyst_docs.py` pins that the prompt and the schema in this file are the ones in the
code. The pilot has `tests/test_analyst_pilot.py`, `test_analyst_pilot_serving.py` and
`test_sample_brief.py`.

## The UFC analyst

The same analyst for fights: every bout on a card gets a model-written call, with reasons, on every
market we hold a price for, frozen before the bout and graded in public. It is the MLB analyst's
machinery with a fight packet, a fight prompt and its own ledger and record.

> Written by an AI model from the data on this page. Unproven. Analysis, not advice.

The public UFC favourites rule is paused (`docs/decisions/UFC_FAVOURITES_PAUSED.md`) until each fight
has a real breakdown behind it. This is that breakdown, built so it can be checked. It changes no card
rule, pick or published result, shares no row with the card record or the MLB analyst record, and
places nothing.

### What is shared and what is new

| piece | where | UFC |
|---|---|---|
| model call, schema, shape check, repair, spend meter and cap | `src/analyst/analyst.py` | shared (the prompt is a parameter) |
| deterministic critic, the -200 rule, banned words, name check | `src/analyst/critic.py` | shared (the name vocabulary is a parameter) |
| fact packet | `src/analyst/ufc_packet.py` | new |
| prompt, request, verify bound to the fight vocabulary | `src/analyst/ufc_analyst.py` | new |
| grading | `src/analyst/ufc_grading.py` | new |
| ledger and record | `src/analyst/ufc_ledger.py`, `evidence/analyst_ufc_v1.jsonl` | new, same chain primitive |
| CLI | `src/analyst/ufc_cli.py`, `--sport ufc` | new, the MLB commands are untouched |
| routes | `api/analyst_ufc.py` | new |
| page module | `web/js/analyst_ufc.js` | new, not mounted on any page |

### 1. The packet (`src/analyst/ufc_packet.py`)

One frozen, hashable packet per bout, built by `build_packet(store, bout_id, built_at=...)` from
`src.datasvc.ufc.matchup.matchup(store, a, b, as_of=<the bout's scheduled start>)`: the data layer's own
fact sheet (fighters' records and rates with their own samples, style labels, differences, shared
opponents, previous meetings, physical comparison, layoff) plus `matchup.bout_odds`. The packet adds no
statistic of its own. Its shape is the MLB packet's on purpose (`markets`, `slots`, `missing`, `limits`,
the same option and quote objects, the same path grammar), so the critic, the ledger and the page read it
the same way.

**No leakage, four ways.**

1. Features are as of the bout's scheduled start. A result, the bout's own or a later one, is invisible
   to them: that is the data layer's rule (`docs/datasvc/UFC_FEATURES.md`), and the packet tests rebuild
   the packet from a world that ends at the start and from the full world and require them to be equal.
2. The bout block is a whitelist: identity, event, start, state, weight class, rounds, card segment, the
   two fighters. The winner, method, round and time a finished bout carries never enter it.
3. A price enters only when its odds row was fetched before the packet was built and strictly before the
   bout's scheduled start. The data layer keeps one odds row per provider per bout and overwrites it on
   every fetch, so a row fetched after the start (a closing line written once the fight was over) is
   dropped whole and `missing` says why. A row that cannot be dated is dropped too, and so is a row marked
   as the closing line. The `close` prices are never read.
4. The live in-play provider ("ESPN Bet - Live Odds") is never used, whatever it quotes, even when it is
   the only row.

The overall professional record and the UFC.com career figures are not as-of-date (the data layer labels
both `as_of_safe: false`). They enter only when their own fetch time is before the bout's start, so
neither can hold its result, and they are labelled as covering more than the store.

**Slots.** A slot exists only when every price it needs is quoted: both sides of the moneyline, the line
and both prices of the total, the one price of a method outcome. Nothing is inferred.

| slot | market | selections (lean first) | verdicts |
|---|---|---|---|
| `moneyline` | `moneyline` | each fighter, the favourite first | TAKE, TAKE_OTHER_SIDE, PASS |
| `rounds_total` | `rounds_total` | `Over 4.5`, `Under 4.5` (the likelier side first) | TAKE, TAKE_OTHER_SIDE, PASS |
| `method_a_ko`, `method_b_ko` | `method` | `<fighter> by KO/TKO/DQ` | TAKE, PASS |
| `method_a_sub`, `method_b_sub` | `method` | `<fighter> by submission` | TAKE, PASS |
| `method_a_dec`, `method_b_dec` | `method` | `<fighter> by decision` | TAKE, PASS |

The six method outcomes are not a two-way market, so each is its own one-option slot: there is no other
side to take, and the critic strikes a TAKE_OTHER_SIDE on one. Each option carries its quote (`book` is
the provider, `price` the current price, `captured_utc` the odds row's fetch time), `fair_probability`
(the price as a probability with the margin divided out, from the data layer; for a method price only
when all six are quoted), `implied_probability` (the same price with the margin left in) and `open_price`
(and `open_line` for a total, because an open price is priced at the open line).

**Holes.** `missing` lists every absent, stale or thin input with the reason: a figure the sheet could
not compute, a fighter with no fights or fewer than three in the store, fights without statistics, an
earlier bout with no recorded result, a quote older than 180 minutes (one entry per slot, so the critic
can lower a confident call that rests on it), a market with no price, an odds row withheld and why, a
fighter with no name.

**Names.** A fighter the store cannot name is labelled `Fighter A` or `Fighter B` and `name_known` is
false. The packet never invents a name. The CLI refuses to publish such a bout: an analysis that cannot
say who is fighting is not worth publishing.

**Not analyzed** (stated in the packet's `limits`): round betting, the spread and every other market;
injuries, weight cuts, camp news, short-notice replacements and rankings are not in the data. Counts and
rates cover only the UFC fights in the data store (the packet says where it begins), not a career.

**How to read it** (the packet's `how_to_read`): which fighter is `a`, that a difference is a minus b, that
`previous_meetings` are written from fighter a's side, what a figure's `fights` and `minutes` mean, and the
difference between `fair_probability` and `implied_probability`. It is in the frozen packet so the file
explains itself.

### 2. The prompt, verbatim (`UFC_PROMPT_VERSION = analyst_ufc_prompt_v1`)

Every sentence of the MLB prompt is in it word for word except the few that name baseball, which are
reworded (`tests/test_analyst_ufc_model.py` lists them and fails if an MLB rule is added or changed without
the UFC prompt carrying it). The fight guidance is rules 14 to 19.

```
You are a mixed martial arts betting analyst. You write the analysis of one UFC bout and make a call on every market the packet prices. You are an AI model and the reader knows it. Your work is published before the bout, graded afterward, and shown next to its record whatever that record turns out to be. Write like a sharp human analyst talking to a smart friend: plain words, a point of view, no hype.

THE PACKET IS YOUR ONLY SOURCE
1. Reason only from the packet. Use no outside knowledge of any fighter, opponent, camp, injury, weight cut, ranking or result, even if you are sure of it. If something matters and is not in the packet, say it is missing. Name fighters exactly as the packet spells them, and name nobody who is not in it.
2. A claim without a packet path is forbidden. Every reason has evidence: a list of {path, value}. A path names one value in the packet and starts at the packet's own top-level key. The value is copied exactly. Examples of real paths: markets.moneyline.options[0].best.price and sections.fighter_a.values.figures.finish_rate.value. Never start a path with data. or packet.
3. Every number you write in prose must appear in the packet, or be a price or probability you are yourself giving in a call. Do no arithmetic of your own on packet numbers in prose (no differences, sums or ratios); quote the packet's numbers, including the differences it already holds in sections.matchup. Do not write clock times.
4. `missing` lists what is absent, stale or thin. Weigh it. A call that rests on something listed there is a PASS.

THE CALLS
5. Make exactly one call for every entry in `slots`, in the same order, using its slot_id and its market. `selection` must be one of that slot's selections, written exactly as listed. The first selection is the lean: the side the books favour. A slot with a single selection (one fighter to win by one method) has no other side, so it is a TAKE or a PASS.
6. Verdicts. TAKE: bet the lean (the first selection) at the price you name. TAKE_OTHER_SIDE: bet the other selection, the side the books do not favour. PASS: bet nothing in this market.
7. PASS is the default. When the evidence is thin, or the packet gives you nothing about this market beyond its own price, PASS. Say plainly when the market is probably right, and what makes you think so.
8. Never TAKE any bet at a price of -200 or worse, in any market (-200, -250, -325 and so on). PASS it, or if the other side is the one you like, take that.
9. price and book: the quote you would take, copied from the selection's quotes in the packet. For a PASS you may give the best quote or null.
10. fair_estimate: your own probability that the selection wins, between 0.01 and 0.99. The books' own number is in the packet: fair_probability is the price as a probability with the bookmaker's margin taken out, and implied_probability is the same price with the margin left in. A method of victory price has a fair_probability only when all six method prices are quoted; otherwise it is null. If you depart from the books by more than a few points, the reasons must show what the packet knows that the price does not. For a PASS you may give null.
11. pass_price: the American price at which the selection stops being worth taking, which is the break-even price of your fair_estimate. On a PASS, the price at which you would start to take it, or null if no price would do.
12. confidence: low, medium or high. High only when several independent packet facts agree and nothing relevant is in `missing`.
13. what_would_change_it: one sentence naming a specific new fact that would flip the call, such as a late price move or a change of opponent. If it names a price, that price is your pass_price.

THE FIGHT
14. Style matchup. `sections.matchup.values.styles` holds labels (wrestler, striker, finisher and so on) computed from each fighter's own numbers, with the evidence behind each. They describe what the numbers show and predict nothing. A label under `not_assessed` was not judged because the sample was too small, which is not the same as not applying. Labels matter in pairs: a fighter who takes opponents down against one who defends takedowns poorly, or a high-volume striker against a fighter who absorbs a lot, is a matchup. Two styles that never meet say little.
15. Finishing threat against durability. Set how often each fighter finishes (finish_rate, knockdowns_landed_per_15, submission_attempts_per_15) against how often the other has been finished (been_finished_rate, knockdowns_suffered_per_15), and read how their fights ended in record.wins_by_method, record.losses_by_method and last_three. A method price needs its own route: a fighter who has only won on the scorecards has not shown he can win by knockout.
16. Pace and fight time against the rounds total. The line is in rounds and a round is five minutes: over a line of 2.5 the bout must last past the middle of the third round. Use average_fight_time_s, distance_rate, finish_rate and been_finished_rate for both fighters and the scheduled_rounds, and say whether the price already holds them. Two fighters who rarely finish and are rarely finished point to a long bout; two who finish often point to a short one.
17. Layoff and short notice. The layoff (sections.matchup.values.layoff) and each fighter's days_since_last_fight are packet facts: a long layoff or a very short turnaround is a reason for care, never a verdict. Short notice, injuries, weight cuts and camp changes are not in the packet. Never claim one; say that you cannot see it.
18. Thin samples. The packet counts only the UFC fights in its data store, so a fighter can have two or three fights there where his career has twenty. Every figure carries its own fights and minutes, and a rate from one or two fights is not a rate. When the sample is thin (see `missing`, thin_sample and each figure's fights), prefer PASS, say it is thin, and lean on what is solid: the records and the last fights. Career figures, when the packet has them, say how far back they go; use them as that and no more.
19. Keep the calls consistent with each other and with the summary. A fighter you expect to win on the scorecards is not also a good knockout bet.

THE WORDS
20. Never write: lock, guaranteed, free money, sure thing, can't lose, +EV. Never claim a profit, an edge you have, or certainty. No exclamation marks.
21. Do not recommend a stake size and do not describe anything as a bet you or we placed.

THE SUMMARY
22. `summary` is the argument in 120 to 200 words of plain prose, one or two paragraphs, no lists, no markdown. Say where you lean and why, where you pass, what the market probably has right, and which missing inputs matter. A voice like: "The favourite is the right side on the moneyline, but the price already says so and the sample behind his numbers is thin, so I pass." Only with facts that are actually in the packet.

Reply with one JSON object that matches the schema and nothing else.
```

**The schema** is the MLB schema, verbatim, section 2 above (`analyst.RESPONSE_SCHEMA`): a call per slot
with verdict, price, book, fair_estimate, confidence, reasons with evidence, pass_price and
what_would_change_it, and a summary of 120 to 200 words. The model cannot make up a slot, a market or a
selection; `validate_output` checks the rest.

**The critic** is the MLB critic with one thing changed, the name vocabulary (`ufc_analyst.known_names`).
A call is struck when a path does not resolve, a value is not the packet's, a number in prose is not a
packet number, a banned word appears, a person is named who is not in the packet, the selection or
verdict does not fit the slot, the price and book are not a real quote, a TAKE is at -200 or worse in any
market (method prices and totals included), or the call contradicts itself. A UFC claim may say
"Unanimous Decision" or "Women's Flyweight" without being struck as a stranger; no baseball club is
vouched for. A struck call is published as a PASS whose reason is "Could not be verified." The original
goes to the ledger row's `struck` list. The packet's own text vouches for the fighters and their
opponents; a name stitched from two real ones is struck.

### 3. The ledger (`src/analyst/ufc_ledger.py`)

`evidence/analyst_ufc_v1.jsonl`, append-only and hash-chained on `HashChainLedger`, with the frozen
packets in `evidence/analyst_ufc_packets_v1/<date>/<bout>_<hash12>.json.gz` and the cost log in
`evidence/analyst_ufc_usage_v1.jsonl`. None of the MLB analyst's or the cards' files is read or written.

| row | when | holds |
|---|---|---|
| `analyst_ufc_published` | before the bout | the calls, each with its grading spec (the fighter it backs, the method, the side and line); summary and its status; the struck originals; packet hash and path; model, prompt version and hash; run cost |
| `analyst_ufc_graded` | after the bout | each call's result from the data layer's bout record, and what the result was |
| `analyst_ufc_correction` | when a grade was wrong | the corrected fields and a reason; the graded row is untouched |

- **Refuses to publish** for a bout that has started, whose scheduled start is unknown, or whose state is
  not `scheduled`. The CLI asks the same question before calling the model, so a bout that cannot be
  published is never paid for. ESPN gives every bout of a card segment the segment's start, so the real
  bout begins later than the time it is refused at: the rule is conservative by construction.
- **Frozen.** A second `publish` returns the first row. `--refresh` writes a new version while the bout
  has not started and has not been graded; only the newest version counts.
- **`date` is the event's date** (the UTC date of the event's start). Every bout of an event carries it,
  including main-card bouts that start after midnight UTC, and `grade --date` uses it.
- **Size.** A published row is about 8 KB with terse reasons (measured on the test fixtures) and will be
  more with real ones, call it 8 to 15 KB a bout, plus about 5 KB for the packet file. A 14-bout card adds
  roughly 0.2 to 0.3 MB, about 10 to 15 MB a year at a card a week. The store is not registered for the
  cold-storage rotation the capture stores have (`src/pipeline/store_archive.py`); at that rate the 100 MB
  file limit is several years away.

### 4. How grading works (`src/analyst/ufc_grading.py`)

Families are graded and counted on their own: `moneyline`, `method`, `rounds_total`. WIN, LOSS, PUSH,
VOID and UNRESOLVED mean what they mean for MLB. Returns are flat one-unit stakes at the published price.
A PASS is not a bet; it carries `would_have`, what the passed side would have done at its best quote.

| market | rule |
|---|---|
| moneyline | WIN when the fighter the call backs is the recorded winner, LOSS when the other fighter is. A disqualification win is a win. |
| method | WIN when the backed fighter won and the way he won is the priced method: `KO_TKO` and `DQ` are `ko_tko_dq`, `SUB` is `submission`, `DEC_UNANIMOUS`, `DEC_SPLIT`, `DEC_MAJORITY` and `DECISION` are `decision`. LOSS otherwise. `OTHER` is VOID, except that its raw label for a stoppage by the doctor (`tko---doctors-stoppage`, all 11 `OTHER` results among the 1,591 finished bouts in the store on 2026-10-03) is a TKO, as every book's method market counts it. |
| rounds total | elapsed seconds are (`end_round` - 1) x 300 + `end_time_s`, compared with the line x 300. Over wins when the bout lasted longer than the line, Under when it ended before it. A bout that went the distance ends at the last round's 300 seconds, so it is over every line below its scheduled rounds. |
| draw, no contest | VOID in every family, including a no contest the data layer records with a winner. |
| canceled | VOID. |
| not final yet | UNRESOLVED: never a loss, never a void. |
| final, no usable result | UNRESOLVED (no winner, no method, no end round or time, a clock outside a round). A later ingest may supply it. |

**The half-round boundary.** A line is a half-round ("over 2.5": past the middle of the third round). A bout
that ends exactly on the line, 2:30 of round 3 against 2.5, is a PUSH for either side: the stake comes back.
That is the usual treatment of a total that lands on its line and the only one that does not pick a winner
by an arbitrary clock tie-break. It was not checked against any one book's published rule (the work had no
network), so it is stated here for the record to be checked against. It is rare (4 of the 1,591 timed bouts in the store on 2026-10-03 ended at exactly 150.0 seconds). Seconds are
compared, not floats of rounds, so 4.5 x 300 = 1350 is exact. If a book's own rule differs, a `correction`
row fixes the grade and the record shows it as corrected.

**The public record** (`GET /analyst/ufc/record`) shows counts by family always. A win rate and units
appear for a family only at **30 graded calls** (win, loss or push); below that the server sends null and
the reason, and the page never computes a rate of its own.

### 5. Where it shows

- `GET /analyst/ufc/{event_id}` (`api/analyst_ufc.py`): one event's published analysis, every bout in card
  order with its grades, from the ledger only. It is mounted behind the same gate as `GET /game/...` and
  `GET /analyst/...`. **A page view never calls the model.** An event with nothing published answers
  `available: false` and a plain reason.
- `GET /analyst/ufc/record`: the public record. It never serves a pick for a bout that has not settled.
- `web/js/analyst_ufc.js`: a self-contained module. It is not mounted on any page by this work. To mount
  the section on the fight-night page, two lines and nothing else:

```js
import { fetchUfcAnalyst, renderUfcAnalystEvent } from "./analyst_ufc.js";
const data = await fetchUfcAnalyst(eventId);          // null on any failure: the section is just absent
if (data) screen.appendChild(renderUfcAnalystEvent(data));
```

  `renderUfcAnalystRecord(record)` and `mountUfcAnalystRecord(screen)` do the same for the record page.
  Every call is drawn by the MLB module's `callNode`, so a PASS is exactly as large as a TAKE. The styles
  are in `web/css/analyst.css`, which `web/index.html` already links.

  A page that lays out its own bout cards can fetch the event once and draw one bout where it belongs:
  `data.analysis.bouts` is keyed by `bout_id`, the id the data layer uses, and `boutNode(bout)` renders
  one of them. Each bout carries `fighter_a`, `fighter_b`, `weight_class`, `card_segment`, `match_number`,
  `start_utc`, `summary` and `summary_status`, `calls` (grouped by `family`), `result_text` once it has been
  graded, and `graded`.

### 6. Running it

```
python -m src.cli analyst run --sport ufc --date 2026-10-10 --dry-run
python -m src.cli analyst run --sport ufc --date 2026-10-10 --event 600061541 --dry-run --print-request
python -m src.cli analyst run --sport ufc --date 2026-10-10            # needs ANTHROPIC_API_KEY
python -m src.cli analyst grade --sport ufc --date 2026-10-10
python -m src.cli analyst record --sport ufc
```

- It is the same `ANTHROPIC_API_KEY` as the MLB analyst: nothing new for the owner to create. Without it,
  `run` prints `BLOCKED: ...` and exits 3 before loading, building, calling or writing anything.
  `--dry-run` needs no key: it builds each packet and the exact request that would be sent, prints its size,
  slot count and worst-case cost, and calls and writes nothing.
- `--date` selects the events that start on that date (UTC); `--event ID` selects one of them. Bouts are
  taken earliest start first, main event first within a start, so a run that begins close to the first bout
  publishes what it still can.
- A bout already published is frozen and skipped without a model call. A bout that has started, whose start
  is unknown, that is not `scheduled`, that prices no market, or whose fighters the store cannot name is
  skipped before any call. Exit codes: 0 ok, 2 error, 3 blocked, 4 spend cap.
- `scripts/analyst_step.sh` is the MLB daily step and was not changed. Wiring `--sport ufc` into the daily
  job is a separate decision (it needs the data service's odds capture to run before the analyst, and a
  workflow edit that is the owner's).

**A dry run on the real data**, from the main checkout's store, on 2026-10-03 at 20:14Z, a quarter of an
hour after UFC 332's early prelims started (`AISPORTS_DATA_DIR` pointed at the main checkout's `data`):

```
$ python -m src.cli analyst run --sport ufc --date 2026-10-03 --event 600061182 --dry-run
SKIP 401912274 Fighter A vs Fighter B: the bout's scheduled start 2026-10-03T20:00:00Z has passed or is inside the 0.0-minute lock; nothing can be published
...
DRY RUN 401912278 Fighter A vs Fighter B: packet 048de59eb8d0 (22312 characters), 8 slots, 13 missing items, request ~9904 input tokens (high estimate), worst case $0.18; nothing sent, nothing written
  slots: moneyline, rounds_total, method_a_ko, method_a_sub, method_a_dec, method_b_ko, method_b_sub, method_b_dec
  NOTE: no name is stored for fighter A and B; a real run skips this bout until the data store has them
...
dry run over 8 bout(s) of 14: 64 slots, ~79467 input tokens, worst case $1.44 (a run stops at its $6.00 cap); nothing sent, nothing written
```

Bout 401912278 is the UFC 332 main event (Women's Flyweight, title bout, five rounds). Its packet prices all
eight slots: the moneyline at -205 and +170 (fair 0.6447 and 0.3553, opened at -198 and +164), the rounds
total at 4.5 (over -280, under +210, opened -315 and +230) and six method prices from +2200 (the second
fighter by submission) to -110 (the first by decision). The six bouts skipped started at 20:00Z, which is the
refusal rule working on real data. **Today a real run would skip every bout**, because the main checkout's
store has no `fighters.jsonl` yet: no fighter has a name. The first thing the UFC analyst needs from the data
layer is that file (and, for the career blocks, `ufccom_profiles.jsonl`).

### 7. Cost per card

**Everything below is an estimate until the first measured day.** The cost log
(`evidence/analyst_ufc_usage_v1.jsonl`) records the real tokens and dollars per bout from the usage the API
returns, and `analyst record --sport ufc` prints cost per day.

| item | value | source |
|---|---|---|
| model and price | `claude-sonnet-5-5`, $2.00 per million input tokens, $10.00 per million output tokens | `config/analyst.json`, shared with MLB |
| packet, all 8 slots priced | 21,300 to 24,100 characters, mean 22,400 | measured by the dry run above, 8 UFC 332 bouts |
| packet, moneyline only (a week out) | 16,700 to 17,600 characters | measured on the 2026-10-10 card, 10 bouts |
| prompt and schema | 7,000 and 1,400 characters | measured in characters, not tokens |
| input per bout | about 9,600 to 10,500 tokens (the CLI's deliberately high estimate is 3 characters a token and leaves the schema out) | |
| output per bout | 3,500 to 7,000 tokens: about 270 for the summary, about 200 for each of 8 calls, plus adaptive thinking at medium effort (not measured) | assumption |
| prompt caching | not used: the stable prefix is under the minimum cacheable length | no saving claimed |

Per bout with all eight slots: input about $0.02 plus output $0.035 to $0.07 is **about $0.05 to $0.09**.
Worst case, a full 16,000-token answer, is $0.18 (what the spend cap reserves before each call). A 13- or
14-bout card is **about $0.70 to $1.25**; the same card's worst case is $2.34. A card a week out, where only
moneylines are priced, is about $0.03 to $0.05 a bout, $0.30 to $0.60 for a card. At four to five events a
month that is **about $3 to $6 a month**. The optional model critic adds about $0.03 a bout. A repair
attempt on a malformed answer costs another call. The hard cap is the MLB one: $6.00 and 600,000 tokens per
run, checked before every call, stopping the run with `STOPPED: spend cap reached`. At the worst case that
is about 33 bouts.

### 8. What it does not claim

- That it is right. The record is empty and unproven, and the label says so everywhere.
- Any profit, any edge, any expected value. It never says "lock", "guaranteed" or "free money", and the
  critic strikes any call that does.
- That a verified call is a good call. Verified means the facts it quotes are in the packet and the call
  does not contradict itself. Whether it was worth taking is what the record measures.
- That it saw anything outside the packet: no search, no tools, no memory of other bouts.
- Anything about injuries, weight cuts, camp news or short notice. They are not in the data.
- That the card is affected. It changes no card rule, gate, pick or published result and shares no row
  with the card record or the MLB analyst record.
- A stake size, or that anyone should bet. It recommends no stake and places nothing.

### 9. Tests

`tests/test_analyst_ufc_packet.py` (shape, slots, determinism, no leakage, holes),
`test_analyst_ufc_model.py` (the prompt, the request, the call), `test_analyst_ufc_critic.py`,
`test_analyst_ufc_grading.py` (every result kind), `test_analyst_ufc_ledger.py`, `test_analyst_ufc_cli.py`,
`test_analyst_ufc_api.py`, `test_analyst_ufc_web.py` (under node) and `test_analyst_ufc_docs.py`, all offline:
the store is the data layer's synthetic world in a temporary directory, the HTTP caller is injected, and no
test reads the repo's real UFC data. `tests/test_analyst_ufc_docs.py` pins that the prompt in this file is
the prompt in the code.

## The situation arm (arm B)

Everything above is **arm A**: the analyst that reads the matchup statistics. It is unchanged, byte for
byte, and `tests/test_situation_analyst.py` pins its prompts, its packets and its ledger rows by hash.

**Arm B** is the same analyst with the situation layer (`src/situation/`, `docs/SITUATION_LAYER.md`): the
same packet plus a `sections.situation` section (rest and rhythm, form, stakes, pressure history, head to
head, availability, venue for MLB; layoff, form, card slot, previous meeting and weight class for UFC) and
the same prompt plus a "THE SITUATION" section of four rules on weighing it (MLB rules 17 to 20, UFC 23 to
26; the text is in `docs/SITUATION_LAYER.md` and pinned to the code). It writes to its own ledgers,
`evidence/analyst_v1_situation.jsonl` and `evidence/analyst_ufc_v1_situation.jsonl`, with its own cost logs
and frozen packets, and `python -m src.cli analyst compare` sets the two arms side by side, by sport and
market family, withholding rates under 30 graded calls.

**It is off.** `config/analyst.json` `situation_arm.enabled` is false; `analyst run --arm B` or `--arm both`
runs it for one run. Turning the switch on **roughly doubles the analyst's cost** (a second call per game with
about 2,500 to 3,800 more input tokens: about $0.09 to $0.13 a game for B against $0.08 to $0.11 for A; both
arms about $0.17 to $0.24 a game, $2.60 to $3.60 for a fifteen-game day). The spend cap is shared by both
arms. Raise the console spend limit before turning it on (`docs/decisions/AI_ANALYST_ENABLE.md`).
