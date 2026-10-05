# Test gate that finishes (2026-10-06)

## What changed in `scripts/test_parallel.py`

| Behaviour | Detail |
|---|---|
| Serial modules | `tests.test_daily_bootstrap` and `tests.test_capture_no_set_time` are removed from the parallel shards and run afterwards ALONE, one at a time, in this thread. Flag `--serial-modules <mods...>` overrides the list; `--no-serial` restores the old all-parallel behaviour. A serial module that is not in the selected set (`--modules`, exclude file) is not invented. |
| Output | Separate block `SERIAL MODULES (run alone, one at a time, ...)` with one line per module. Counts, failures and exit code include both phases. Final line keeps the old prefix: `OK:`/`FAILED: N tests in Xs wall (W workers) -- failures=.. errors=.. skipped=..`, plus ` (parallel=P serial=S)` when a serial phase ran, plus ` timeouts=N` when any. Failing-worker output (`Ran N tests`, `FAIL:`/`ERROR:` identities) is still dumped to stderr; the section header now says `serial module` for serial ones. |
| Heartbeat | stderr lines `[hb HH:MM:SS] worker 3 started: ...`, `... finished in 41.2s: 87 tests [OK]`, and every 60 s while anything runs `[hb ..] 4 shard(s) still running after 300s: worker 1 (300s), ...`. The `[hb` prefix cannot collide with the parsed lines. |
| `--timeout-minutes N` | Overall deadline across both phases. When it fires the still-running shards are named (`worker 2 still running after 1800s: <modules>`), their process trees are killed (`taskkill /T` on Windows, `killpg` elsewhere), they are reported as `TIMED OUT` with return code 124, counted in `timeouts=`, fail the run, and an `OVERALL TIMEOUT:` block lists them. A serial module not yet started is reported as `not started`. |

Unit tests: `tests/test_test_parallel_serial.py` (16 tests, ~4 s). They cover
partitioning (default pair, missing modules, name normalisation, nothing lost
or duplicated), the summary arithmetic with fake results, serial one-at-a-time
ordering, the not-started-after-deadline path, and a real child process
against fake on-disk modules (ok / failing / sleeping) proving the overall
timeout names and kills the slow shard in about 3 s instead of waiting 60 s.
A smoke run of `main()` with one parallel and one serial module printed the
serial section and the correct combined totals and exit code.

## The two serial modules, run alone on this machine (Windows 11, Git Bash)

Commands: `python -m unittest tests.test_daily_bootstrap`, then
`python -m unittest tests.test_capture_no_set_time` (nothing else running from
this session).

| Module | Tests | Failures | Errors | Seconds | Result |
|---|---|---|---|---|---|
| `tests.test_daily_bootstrap` | 21 | 1 | 0 | 88.5 | FAILED (failures=1) |
| `tests.test_capture_no_set_time` | 55 | 1 | 0 | 62.0 | FAILED (failures=1) |

Neither failure is a timeout. Both are Windows-only conditions:

1. `DailyBootstrapParsesTest.test_is_executable` asserts
   `scripts/daily_bootstrap.sh` has an exec bit (`st_mode & 0o111`). The git
   index records the file as mode `100755`, so Linux CI (and the runner) pass;
   an NTFS checkout reports mode 0. Windows-only (exec bit).
2. `DenseWindowStalenessFallback.test_a_recent_capture_stays_at_the_narrow_window`
   expected 180, got 1440. The test prepends a fake `date` stub directory to
   `PATH`, but Git Bash's startup reorders `PATH` so `/usr/bin` precedes the stub
   directory (checked: `command -v date` prints `/usr/bin/date` with the stub
   first on the Windows-side PATH), so the real `date` runs and the "recent
   capture" branch is never seen. The two sibling tests in that class expect
   1440 and pass for either reason, so they cannot catch this. Windows-only
   (PATH/bash environment), not a defect in `capture_slot.sh`.

Time note: run alone, the pair costs 150 s on an idle PC. Their hard
subprocess timeouts are 8 s (`test_daily_bootstrap` line 138) and 30 s (lines
217 and 287, plus `test_capture_no_set_time` line 658); `_run_bootstrap`
defaults to 60 s. Under the old all-parallel run these share CPU with every
other worker, which is the 2026-10-04 stall. No timeout fired when run alone.

## Usage

```
python scripts/test_parallel.py --workers 8 --timeout-minutes 45
python scripts/test_parallel.py --no-serial          # old behaviour
python scripts/test_parallel.py --serial-modules tests.test_x tests.test_y
```

On Windows expect the full run to exit 1 solely from the two failures above;
on Linux both pass.
