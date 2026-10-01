# Capture slots stopped completing: cause and fix (2026-10-01)

## What was observed

From 19:06Z capture slots completed about once an hour against about 4.5
before. Most `forward-capture` runs were cancelled while waiting; the ones
that ran took 20 to 30 minutes. Production's odds went stale with them (the
hourly refresh only fires on a completed first slot of the hour): at 23:01Z
production was still serving the 21:19Z board.

## Cause (measured, not inferred)

A separate worker replayed `python3 -m src.cli engine slate --date 2026-10-01`
on a copy of the runner's branch and stores, with every write confined to
the copy.

| Step | Time | Share |
|---|---|---|
| Whole command | 1,285.9 s | 100% |
| `src.board.l1.run` (via `refresh_l1_if_stale`) | 1,273.5 s | 99.0% |
| of which `_match_raw` | | 98.3% of samples |
| `preflight.check` | 12.4 s | 1.0% |

The runner's own time for the step was 1,144 s, the same order.

`_match_raw` ran once per observation (191,052 for the day). Each call
listed and sorted the day's raw-capture directory and yesterday's, parsed
every file name's timestamp, and re-opened, un-gzipped and re-parsed every
capture inside the 120-second window. The same 233 files were read about
190,000 times. `l1_observations.jsonl` is not tracked and not cached, so a
fresh runner rebuilds the day from nothing on every job, and the cost grows
with (observations so far today) x (raw files so far today): it got worse
all day. The step runs in both the capture slot and the afternoon slate,
which share one lock.

## Fix

`src/board/l1.py`: one `_RawIndex` per `run()`. A day's directory is listed
once, each file name parsed once, each capture read and indexed once by
(event, book, market). `_match_raw` asks the index. No rule, window or
output field changed.

## Verification

Same replay copy, same stores, `since=2026-10-01`:

| | Runner's code | Changed code |
|---|---|---|
| Full day, 191,052 observations | 1,273.5 s | 12.6 s |
| Output file | 120,003,523 bytes, sha256 386eb5e89c4915e3... | identical bytes, same sha256 |
| Snapshot store alone, 22,624 observations (same hash seed) | 116.6 s, 35,586 gzip opens | 1.6 s, 207 gzip opens |
| Snapshot output | | byte-identical (`cmp`) |

`tests/test_l1_raw_index.py` keeps the old walk verbatim as a reference and
checks the indexed answer against it on window edges, name mismatches,
yesterday's files and unreadable captures, and that a capture is opened once.

Status: IMPLEMENTED, TARGETED TESTED, REPLAY VERIFIED on real stores, PUSHED
(5a85b867, 23:15:53Z), RUNNER VERIFIED:

- afternoon-slate run 36940725689 (first to run the step on the new code):
  `engine slate` 23:28:19Z to 23:29:24Z, 65 s against 1,144 s; the whole
  slate pass 134 s against about 20 minutes; the job 5 minutes end to end.
- forward-capture run 36937934023: "Capture one slot" 85 s (that slot
  skipped the engine step: no new lineup), job done in 4 minutes.

Still to watch: slots completing at the normal rate over the next hours, and
production's hourly refresh firing again at 00:00Z.

## Not fixed here (measured, small)

- `glue.commence_time_for` rescans the 41 MB snapshot store once per game
  (about 35 s for 2 games; grows with the slate).
- `ledger.bridge.ensure_genesis` reads the whole decision ledger on every
  append (about 0.84 s per new decision).
- A known quirk kept as it was: `_match_raw` walks today and yesterday in
  set order, so an observation within two minutes of midnight that matches a
  capture on both days can name either. Output for 2026-10-01 was identical
  regardless.
