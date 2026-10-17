# Decision: the public MLB value picks are paused after 2026-10-16

For Brey. Owner decision of 2026-10-16, wired the same day. One config value
turns it back on. It is the MLB twin of `docs/decisions/UFC_FAVOURITES_PAUSED.md`.

## The decision

New public MLB value picks stop after **2026-10-16**: the MAIN and PLUS player
props, the moneyline picks and the fills of the V2 value card
(`DAILY_CARD_BEST_BETS_V2`). The slate dated 2026-10-16 publishes exactly as it
does now; every later date is paused.

## Why (evidence)

`docs/research/loss_diagnosis/00_SYNTHESIS.md` (three diagnoses, scripts under
`scripts/diagnosis/`, a fourth agent reran them and tried to refute them):

- Every one of the 178 graded V2 entries was priced worse than the market's own
  number: a mean premium of +2.36 probability points per bet. At the market's
  numbers they were expected to lose 7.55u; they lost 1.42u. The card ran lucky.
- The model's disagreement with the market carries no information: on 6,818
  priced prop contracts the model's log loss is worse than the market's, and
  the best weight to give our disagreement is zero or below.
- The card ranks by exactly that disagreement, so it publishes our largest
  errors by construction.
- Closing-line value is negative wherever it can be measured: -1.69 points per
  bet [-2.09, -1.28] on 82 bets.

In one line for a customer: the picks paid a premium over the market's price and
our forecasts carried nothing the market did not already know.

## What stops

For a slate date AFTER the config date:

| Where | Before | Now |
|---|---|---|
| `python3 -m src.cli card publish --date D` (default rule v1; `scripts/afternoon_slate.sh`) | published V1 into `evidence/cards_v1_shadow.jsonl` | prints `  no card: value picks paused after 2026-10-16 (config/mlb_public_card.json)`, writes nothing, exits 0 |
| `card publish --date D --rule v2` | published the public V2 card | same line, nothing written, exit 0 |
| `card publish --date D --rule all` (`scripts/capture_slot.sh`, every slot) | published V1, V2 and the three shadows from one board | same line; V1 and V2 are NOT built or written; the shadows below still run |
| `GET /card/{date}` and `GET /card` (sport mlb, any `rule`) | the frozen card, or one built live from the odds board | `paused: true`, `picks: []`, `reason`, `links`, `paused_after`. No ledger read, no board build, no cache |
| The card page (`#/today`) | tonight's card | the reason as the empty state, with links to the record, a sample brief and the price board |

The shell scripts need no change: they already treat a `  no card:` line as a
fact about the slate and exit 0 (`|| true` in `capture_slot.sh`; the
`grep -q "^  no card:"` branch in `afternoon_slate.sh`).

The reason a reader sees, verbatim from the API:

> MLB picks are paused. Our picks paid a premium over the market's own price, and our forecasts carried nothing the market did not already know. Picks come back only if a test we register in advance shows we beat the closing price. The daily brief and the price board continue, and every pick made so far stays on the record page.

## What continues

- **The shadows (forward tests, not public).** `--rule all` still builds and
  publishes shadows A, C and E into `evidence/cards_v2_shadow_{a,c,e}.jsonl`, and
  `--rule shadow-a|shadow-c|shadow-e` are untouched. They are the evidence a
  future value product is judged on. (`card.publish_all` always includes V2, and
  `src/report/card.py` is fingerprinted, so `src/cli.py` publishes the three
  shadows itself in the paused case, each into its own store.)
- **`python3 -m src.analysis.mlb_value_shadow publish`**, the other shadow
  forward test: a separate command, not gated.
- **Every published pick, row and record.** No ledger row was edited, deleted or
  re-signed. `card settle` is not gated, so published picks still grade.
- **The record.** `GET /card/record`, `GET /card/history` and the record page do
  not read the pause.
- **The brief and the board.** The daily brief, the price board, the props board,
  the postseason page and all odds capture are unchanged.
- **Dates on or before the config date.** Served and published exactly as before.
- No fingerprinted file was edited (`card_v2.py`, `best_bets_card.py`,
  `card_ledger.py`, `card.py`, `daily_card.py`, `playerprops.py`).

## How to reverse it

One value: `value_picks_last_public_date` in `config/mlb_public_card.json`. Set it
to the last date picks should publish for (a date far ahead turns everything
back on), commit, and let it deploy. The capture runner reads the file from its
checkout, so the next slot follows it; the API reads it from the deployed image
(`deploy/Dockerfile` copies `config/`).

A missing, unreadable or malformed config never turns the picks back on: it
falls back to the built-in 2026-10-16 (`DEFAULT_LAST_PUBLIC_DATE` in
`src/appstate/mlb_public_card.py`), so later dates stay paused and one warning
is logged naming the problem.

## What must be true to resume

From `docs/handoff/WEEK_2026-10-16_PLAN.md`: a positive forward record is NOT the
bar (luck passes it). The bar is **closing-line value whose confidence interval
excludes zero on a pre-registered forward sample, under a rule registered before
the sample starts.** On the day of this decision the number is -1.69 points per
bet [-2.09, -1.28], no rule in the repo meets the bar, and the diagnosis expects
no reweighting of the present inputs to meet it. The only candidate direction
the data supports is information the market lacks at the moment of the bet
(earlier lineups, starters, weather at lock), which track C of the week plan
(a pre-registration to be written as `docs/PREREG_INFO_TIMING.md`) tests. Changing the date back is the owner's call and does not by itself
satisfy this bar.

## What a reader sees, and when

The card's date is the date in the request. The page asks the API for "today"
with no date, which is the server's own date (UTC on Fly). So at 00:00 UTC on
2026-10-17 (8pm Eastern on the 16th) the page's "today" is the 17th and reads as
paused, while some 2026-10-16 games are still being played. Those picks stay on
the record page once graded. A date typed into the API is paused or served by
the same comparison on its own date.

## Where it lives

- `config/mlb_public_card.json`: the one place that decides it.
- `src/appstate/mlb_public_card.py`: reads it (anchored at the repository root),
  holds the reason sentence, the links and the fallback;
  `python3 -m src.appstate.mlb_public_card` prints the date.
- `src/cli.py` (`cmd_card`), `api/card.py`, `web/js/card.js`: act on it.
- Tests: `tests/test_mlb_public_card.py`, `tests/test_cli_card_mlb_paused.py`,
  `tests/test_api_card_mlb_paused.py`, `tests/test_web_mlb_paused_page.py`.

## Not changed here

Public copy that still describes MLB picks as live (the landing page hero and
FAQ, the pricing page, the daily Discord post, the front page's "tonight's
card" call to action) is the owner's call and was left alone. Downstream reads
that say "No card published for DATE" (`scripts/daily_post.py`,
`scripts/publication_audit.py`) will now say so on paused dates, which is true.
