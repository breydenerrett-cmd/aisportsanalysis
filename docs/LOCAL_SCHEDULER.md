# The local clock (GitHub Actions is the worker, not the clock)

## Why this exists

Measured on 2026-09-07, across a full day:

| | Expected | Actual |
|---|---|---|
| `forward-capture` schedule firings | ~96 (a `*/15` cron) | **3** |
| `daily-loop` schedule firing | 10:00Z | **15:20Z** |
| Total `event=schedule` runs all day | ~97 | **4** |

Every other capture that day came from a watchdog: a human-in-the-loop
session noticing the board was stale and dispatching by hand. That is not an
architecture, and it dies the moment the session dies.

The runs themselves were never the problem. Every dispatched run succeeded.
GitHub Actions is a reliable *worker* and an unreliable *clock*.

`scripts/capture_tick.ps1` is that watchdog written down.

## What it does

One tick, run on a timer:

1. **forward-capture** — if a run is queued or in progress, do nothing. Else,
   if the newest completed run is older than `-StaleMinutes` (default 45),
   dispatch one.
2. **daily-loop** — only after 10:00Z, so a healthy cron always wins the
   race. If a run already exists for the UTC date, do nothing. Else dispatch.

Every decision is written to `data/logs/capture_tick.log`, including the
decision to do nothing — a silent scheduler is indistinguishable from a dead
one. That log is gitignored: it is machine-local evidence, not repo history.

## What it deliberately does not do

- **No duplicate spend.** It never dispatches while a run is in flight, and
  never dispatches a second daily loop for a date. (That loop is idempotent
  anyway — run 34137806549 reported `settled 0 new (15 already settled)`
  against an earlier same-day run — but not dispatching is still cheaper
  than relying on it.)
- **No secrets.** `gh` uses its own stored credential. `ODDS_API_KEY` lives
  only in GitHub Actions secrets and is never read, printed or passed here.
- **No workflow changes.** Both workflows stay dispatchable by hand and by
  GitHub's own cron exactly as they are. This adds a clock; it removes
  nothing.
- **No model tokens.** It is a PowerShell script and a timer.
- **It does not throw.** A scheduler that throws is a scheduler that stops,
  so each check is wrapped and a failure is logged and stepped over.

## Trying it without installing anything

`-WhatIf` reports the decision and dispatches nothing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\capture_tick.ps1 -WhatIf
```

Force the dispatch branch to prove it fires, still dispatching nothing:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\capture_tick.ps1 -WhatIf -StaleMinutes 5
```

## Installing it (requires Brey)

This registers a Windows Scheduled Task that runs every 15 minutes under the
logged-in user. It is persistent configuration on Brey's machine, so it is
his call, not the agent's.

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\Users\KC\Desktop\aisportsanalysis\scripts\capture_tick.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "linehound-capture-tick" `
  -Action $action -Trigger $trigger -Description "Local clock for LINEHOUND capture and daily loop"
```

To watch it:

```powershell
Get-Content .\data\logs\capture_tick.log -Tail 20 -Wait
```

To remove it completely:

```powershell
Unregister-ScheduledTask -TaskName "linehound-capture-tick" -Confirm:$false
```

## Known gotchas, both hit while building this

- **`$PSScriptRoot` came back empty** under `powershell -File`, which rooted
  the log at `C:\data\logs` — outside the repo, exactly where a scheduler's
  only evidence goes to get lost. The script now resolves its own directory
  from `$MyInvocation` as a fallback and refuses to guess if neither works.
  If a stray `C:\data\logs\capture_tick.log` exists from before that fix, it
  is safe to delete; nothing reads it.
- **`--json a, b, c` does not work in PowerShell.** The comma-separated list
  is split into separate arguments and `gh` reads the second as a subcommand
  (`unknown command "status"`). It must be one quoted token.

## What this does not fix

The laptop has to be on. This is a local clock, so it is only as available as
the machine. That is still strictly better than a cron firing 4% of the time,
but if the box sleeps overnight the captures stop, and the honest next step
if that becomes a problem is an external scheduler rather than a bigger local
one.
