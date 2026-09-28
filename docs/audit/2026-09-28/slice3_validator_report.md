# Slice 3 validator report (independent), 2026-09-28

Change under test: the streaming reads in `701c3e6f` (tennis board, NFL
card, `/today` date, engine join, derivative store, freshness single-flight).
Validator: a separate Sonnet agent, read-only, own scripts (scratchpad
`verify/*.py`), never the implementer's. Verdict: **SHIP**, on the condition
(met) that the CLI test fix ships in the same commit.

## Equivalence on real stores (old module from `git show HEAD:` vs working tree)

- Tennis board 2026-09-28, 09-21, 09-22 (2,210 rows): byte-identical.
- NFL rows for a date vs naive read+filter+dedup on 6 dates including the
  254,602-row Sunday 09-27: exact match; `nfl_value.latest_quotes` fed old
  raw vs new deduped rows: 0 mismatches across up to 462 keys per date.
- `derivative_prices.candidates_for_date` on 6 dates: byte-identical.
- `engine_bridge.decisions_for_date` on 5 dates plus a zero-event date:
  byte-identical; the empty date returns `{}` without raising.
- Whole store through `iter_multibook(sport=None)`: 809,468 rows, equal to
  `read_multibook` and to the raw `store_archive.iter_lines` count, so all 8
  archive segments are read.
- Synthetic edges (Eastern-date boundary, missing `sport`, `sport=None`,
  duplicate physical row): pass.
- `load_decisions()` untouched (`git diff` empty); streamed filters are a
  verbatim copy, proven on a synthetic ledger with genesis, correction and
  `event_id=None` rows.
- Freshness single-flight: 20/20 race trials; an exception releases the
  slot; a stale hit returns immediately with `stale=True`.

## Memory (fresh subprocess, `K32GetProcessMemoryInfo` every 20 ms)

| warm-up pass | peak working set | peak private | time |
|---|---|---|---|
| old tennis_board.py + nfl_card.py | 1,470.5 MB | 1,459.7 MB | 34.0 s |
| new (streamed) | 539.5 MB | 526.5 MB | 27.3 s |

The swap was done with `git show HEAD:` bytes and restored, sha256 checked
before and after.

## Findings

- A: the diff broke `tests/test_cli_nfl_card_publish.py` (it mocked the
  old `read_multibook` seam and its fixture priced a 09-17 card with a
  09-30 game). Fixed in the same commit: the test mocks `iter_multibook`
  and asks for the game's own date. 3/3 pass.
- B (pre-existing, unrelated): `test_card_memory_budget` fails at 96 MB vs
  a 60 MB budget because `data/historical/bullpen_log.jsonl` grew 3.3x
  since the budget was set.
- Design note: the freshness guard is now one rebuild per cache instance,
  not per key; a second stale key waits longer for its own refresh.

Targeted tests: 233, 0 failures.
