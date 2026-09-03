# Market catalogue

Source of truth: `src/board/ids.py::MARKET_CATALOGUE`. This document is a
rendering of that table, not a second definition of it — if the two ever
disagree, the code wins and this file is stale. Regenerate by hand whenever
the catalogue changes; a test does not currently enforce sync (the table is
small enough that a diff review is sufficient today).

A market absent from this table cannot be assigned a `selection_id` and
cannot reach a decision. `status` values: **LIVE** (captured and settled
today), **PROBE** (captured for evidence, not yet priced by any system),
**DECLARED** (named and settlement-mapped, capture not yet wired), **BLOCKED**
(named on purpose so it can never be silently added — see
`ARCHITECTURE_BETTING_ENGINE.md` guard 8, the product data-path guard).

Settlement rules live in `src/board/settle.py` for game-level markets, and in
`src/board/settle_props.py` for pitcher/batter props; the latter plugs its
rules into `settle.SETTLEMENT_RULES` via `settle.register_rule`, invoked by
`settle_props.register_all()` (called automatically on `import src.board`).
`collection_blocked` means the market is catalogued but has no settlement
path at all yet -- today that is only `same_game_parlay`, named on purpose so
it can never be silently priced.

| Market key | Scope | Subject | Sides | Has line | Settlement rule | Status | Correlation group |
|---|---|---|---|---|---|---|---|
| `h2h` | game | — | home/away | no | `h2h` | LIVE | game_outcome |
| `spreads` | game | — | home/away | yes | `spreads` | LIVE | game_outcome |
| `totals` | game | — | over/under | yes | `totals` | LIVE | game_total |
| `team_totals` | game | — | over/under | yes | `team_totals` | PROBE | game_total |
| `alternate_spreads` | game | — | home/away | yes | `spreads` | PROBE | game_outcome |
| `alternate_totals` | game | — | over/under | yes | `totals` | PROBE | game_total |
| `h2h_1st_5_innings` | first_five | — | home/away | no | `h2h_1st_5` | PROBE | first_five_outcome |
| `spreads_1st_5_innings` | first_five | — | home/away | yes | `spreads_1st_5` | PROBE | first_five_outcome |
| `totals_1st_5_innings` | first_five | — | over/under | yes | `totals_1st_5` | PROBE | first_five_total |
| `first_inning_run` | first_inning | — | yes/no | no | `first_inning_run` | DECLARED | first_inning |
| `first_inning_score_home` | first_inning | — | yes/no | no | `first_inning_score_home` | DECLARED | first_inning |
| `first_inning_score_away` | first_inning | — | yes/no | no | `first_inning_score_away` | DECLARED | first_inning |
| `pitcher_strikeouts` | game | pitcher | over/under | yes | `pitcher_strikeouts` | DECLARED | pitcher_line |
| `pitcher_outs` | game | pitcher | over/under | yes | `pitcher_outs` | DECLARED | pitcher_line |
| `pitcher_hits_allowed` | game | pitcher | over/under | yes | `pitcher_hits_allowed` | DECLARED | pitcher_line |
| `pitcher_earned_runs` | game | pitcher | over/under | yes | `pitcher_earned_runs` | DECLARED | pitcher_line |
| `pitcher_walks` | game | pitcher | over/under | yes | `pitcher_walks` | DECLARED | pitcher_line |
| `batter_hits` | game | batter | over/under | yes | `batter_hits` | DECLARED | batter_line |
| `batter_total_bases` | game | batter | over/under | yes | `batter_total_bases` | DECLARED | batter_line |
| `batter_home_runs` | game | batter | over/under | yes | `batter_home_runs` | DECLARED | batter_line |
| `batter_rbis` | game | batter | over/under | yes | `batter_rbis` | DECLARED | batter_line |
| `batter_runs` | game | batter | over/under | yes | `batter_runs` | DECLARED | batter_line |
| `batter_walks` | game | batter | over/under | yes | `batter_walks` | DECLARED | batter_line |
| `batter_strikeouts` | game | batter | over/under | yes | `batter_strikeouts` | DECLARED | batter_line |
| `batter_stolen_bases` | game | batter | over/under | yes | `batter_stolen_bases` | DECLARED | batter_line |
| `batter_hits_runs_rbis` | game | batter | over/under | yes | `batter_hits_runs_rbis` | DECLARED | batter_line |
| `same_game_parlay` | game | — | (none) | no | `collection_blocked` | **BLOCKED** | sgp |

## Gradeable-from source (today)

- `h2h`: `data/processed/odds_multibook.jsonl`, live capture, byte-round-trips
  through `src/board/project.py::project_h2h_row` / `unproject_h2h_row`.
- `spreads`, `totals`, `team_totals`, `alternate_*`, first-five variants: no
  capture path in this repo yet; `src/board/project.py::project_line_market_row`
  is the projector another lane's capture code will call once its row shape
  lands (it accepts either a `point` or a `line` field for the line value).
- `first_inning_*`: settlement rule exists; no capture path.
- Pitcher/batter props: settlement rule exists (`src/board/settle_props.py`,
  registered into `src.board.settle.SETTLEMENT_RULES` via
  `settle_props.register_all()`, invoked at import time by
  `src/board/__init__.py`); no capture path yet, hence still DECLARED.
- `same_game_parlay`: no settlement rule in this package by design — see
  `settle.py` module docstring.
