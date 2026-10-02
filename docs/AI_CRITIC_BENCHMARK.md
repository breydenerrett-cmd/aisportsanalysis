# AI critic benchmark (v1, frozen)

## What it is

`scripts/ai_analyst.py` builds an evidence packet for one MLB game and
machine-checks a critic's report. Only two sample reviews existed and the
first was format-valid and false (`evidence/ai_analyst/REVIEW_2026-09-25_NYM-WSH.md`:
the largest of three scores called "one of the smaller", a pitcher named
that nobody had verified). That failed review is preserved untouched and is
the history behind case 8.

This benchmark is eight hand-built cases in `evidence/ai_analyst/benchmark_v1/`
plus a deterministic scorer, `scripts/critic_benchmark.py` (stdlib, no
network, no model call). Each case directory holds:

- `packet.json` - everything a critic may see (the shape `ai_analyst`
  hands a critic, so the existing verifier runs on the reply);
- `key.json` - ground truth, expected action, required flags, statements
  that would be unsupported. The critic never sees it;
- `PROVENANCE.md` - which parts are real captured repo data (store and date)
  and which are a labelled perturbation.

Frozen means: do not edit the case files. A change is a new version
(`benchmark_v2/`). Tests pin the shape and hash the original failed review.

## The eight cases (types only)

| case | type | market | real game it is built on |
|---|---|---|---|
| 01 | clean | moneyline, plus price | HOU-ATH 2026-09-25 |
| 02 | clean | run line, minus price | CLE-KC 2026-09-25 |
| 03 | stale information | moneyline, plus price | WSH-DET 2026-09-23 |
| 04 | wrong starter | moneyline, minus price | TB-NYY 2026-09-23 |
| 05 | conflicting sources | moneyline, plus price | CLE-KC 2026-09-25 |
| 06 | market alternative | moneyline, plus price | MIN-SF 2026-09-23 |
| 07 | missing information | moneyline, plus price | HOU-SEA 2026-09-23 |
| 08 | the original failure pattern | moneyline, plus price | NYM-WSH 2026-09-25 |

All dates are 2026-09-10 or later; nothing is read from the sealed window.
Game outcomes are in no packet.

## Scoring rules (per case, then a Markdown table)

`python3 scripts/critic_benchmark.py score <reply.json> --case <case_dir>`
prints one JSON; `score-all <reports_dir>` scores `<case_dir_name>.json` for
every case and prints the table (`--out-dir` also writes the JSONs).

1. **Verifier**: does `ai_analyst.verify_and_report` pass, and which checks fail.
2. **Factual correctness**: every `Fact`, `Ranking`, `CORRECT_INPUT` value
   and every prose ranking sentence recomputed against `key.facts` (packet
   data when the key lists no value).
3. **Source correctness**: every cited id exists; every number in a
   `verified_assumptions` sentence is in the claims that triple cites; every
   `Ranking` value is a real packet number.
4. **Unsupported claims**: count of `must_not_claim` items asserted (key plus
   a generic list: no new probability, no gate edit), wrong facts or
   rankings, unsupported citations, invented numerical effects and, on clean
   cases only, false-alarm STALE/MISSING/CONTRADICTED labels. Components are
   reported separately.
5. **Flags detected**: every `must_flag` entry matched by a
   `verified_assumptions` verdict that starts with the label and cites a
   target claim id.
6. **Correct action**: strict equality with `key.correct_action`;
   `acceptable_actions` is reported beside it.
7. **Recalculation justified**: a CORRECT_INPUT or RECALCULATE request only
   where the key says one is justified.
8. **Invented numerical effect**: a probability-shaped, percentage or
   effect-unit number not derivable from packet numbers (a difference of
   headline numbers, home-vs-away of one field, an implied probability).

The text checks (`must_not_claim`, prose ranking, number scan) are lexical:
a sentence with a negation or conditional cue ("not", "if", "would") is not
counted as an assertion. Structural checks (facts, rankings, attribution,
action) have no such gap.

## Comparing three arms

`python3 scripts/critic_benchmark.py compare [--reports-dir DIR]` scores, per
case, correct action, flags detected and unsupported claims for:

- **A, model only**: always NO_ADJUSTMENT.
- **B, model + verified information**: a deterministic rule, no model. The
  schedule feed's `probable:` claim is authoritative for starter identity.
  It contradicting a model starter assumption gives CORRECT_INPUT with that
  id; two authoritative claims disagreeing, a pitcher log more than 3 days
  behind the game, or an absent starter figure gives a flag and no action;
  a same-side market claim at a better price gives COMPARE_MARKET. Its
  output is a real `CriticFinding` scored by the same scorer.
- **C, model + same information + AI critic**: replies read from
  `--reports-dir`. Without replies `compare` prints A and B and says C is
  pending.

## How a blind critic run is performed

1. One fresh agent per case, no memory of other cases. Give it ONLY the
   contents of that case's `packet.json` and the instruction below. Never
   `key.json`, `PROVENANCE.md`, this document, the scorer or any other case.
2. It writes ONE JSON object. Save it as
   `evidence/ai_analyst/benchmark_v1/reports/<run_id>/<case_dir_name>.json`.
3. Score: `python3 scripts/critic_benchmark.py score-all
   evidence/ai_analyst/benchmark_v1/reports/<run_id> --out-dir
   evidence/ai_analyst/benchmark_v1/reports/<run_id>/scores`, then `compare
   --reports-dir` the same directory.

Exact instruction text:

```
You are reviewing one MLB recommendation made by a statistical model. The
attached packet is your only source: `recommendation` is what the model
recommended and `claims` is a list of dated, sourced claims. Use no outside
knowledge, no search, and nothing about the game's result.

Reply with ONE JSON object and nothing else, with exactly these fields:
game_id; verified_assumptions (list of [assumption, verdict, [claim_ids]]);
challenged_assumption (string); case_against (string, required even if you
conclude no adjustment); action (one of CORRECT_INPUT, REQUEST_SCENARIO,
COMPARE_MARKET, RECALCULATE, NO_ADJUSTMENT); action_payload; facts (list of
{claim_id, field_path, value}); rankings (list of {metric, subject_value,
compared_values, claimed_rank}, rank 1 = highest); pitcher_attribution (null
or {side, name, identity_claim_id}); notes (string).

action_payload keys by action:
  CORRECT_INPUT    {input_path, current_value, verified_value, source_claim_ids}
  REQUEST_SCENARIO {scenario, inputs_varied, source_claim_ids}
  COMPARE_MARKET   {market, reason, source_claim_ids}
  RECALCULATE      {reason, changed_input, source_claim_ids}
  NO_ADJUSTMENT    {checked_claim_ids}

Rules.
1. Each verdict starts with one label then " -- ": VERIFIED, UNVERIFIED,
   CONTRADICTED, STALE or MISSING. Use UNVERIFIED when two sources disagree
   and neither outranks the other, or when a link between two facts is not
   supported by the packet. Cite the claim ids each verdict is about.
2. Every number you write in prose must appear in the packet, or be listed in
   `facts` (copied exactly from a claim's `data`) or in `rankings`. State no
   probability, percentage or effect size of your own. You never supply or
   change a probability or a threshold.
3. Do not name a player unless a `probable:` claim confirms him as a starter;
   if you name him, declare it in `pitcher_attribution`. Refer to roster
   transactions by claim id.
4. CORRECT_INPUT only when a CONFIRMED claim contradicts a model input.
   If an input is stale, absent or in conflict, label it and do not fill the
   gap or recalculate. If a better price exists for the same bet, say so with
   COMPARE_MARKET and use price language only. NO_ADJUSTMENT is a complete
   answer when nothing sourced contradicts the model.
```

## Limits

Eight hand-built cases measure whether the critic is safe and useful on known
failure types. They do not measure betting value, they cannot show the critic
is right in general, and a critic that passes may still fail on a failure type
not represented here. Most content is real captured data. The invented or
inferred parts are only: case 03's pitcher-log date claim, case 05's second
starter listing, and case 04's assumed starter id (inferred from a real feed
change event). The recommendation rows of cases 02 and 04 are assembled from
candidate rows the run did not select, and cases 06 and 08 add real-valued
claims (a second quote; the slate's scores). PROVENANCE.md says exactly which.

### Known gaps in the existing verifier (the scorer covers some of them)

These pass `validate_hard_limits` today: `Ranking` values that are not packet
numbers; a prose ranking ("one of the smaller") when no `Ranking` is
supplied; a transaction claim accepted as the identity source for a starter
attribution; a pitcher name absent from the packet, or only a surname;
`word:number` text (stripped as if it were a claim id); `current_value` and
string `verified_value` in CORRECT_INPUT; RECALCULATE resting only on an
unconfirmed claim; a VERIFIED verdict on an unconfirmed claim. The packet
builder also attaches the moneyline quote as the market claim of a run-line
recommendation. None is fixed here: the benchmark scores against the verifier
as it is.
